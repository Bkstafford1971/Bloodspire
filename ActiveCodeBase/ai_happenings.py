"""
ai_happenings.py — Rewrite the "Arena Happenings" newsletter section with Claude.

The section is generated from the turn's real data first (newsletter.py). This
module takes that finished text and asks Claude to retell it in a more immersive
voice. Any failure returns the original text, so a turn can never break here.

Config is read from llm.json in the same directory as this script:
    {"provider": "gemini" | "claude", "api_key": "...", "model": "...", "max_tokens": 4000, "timeout": 45}
Default provider is "gemini" (Google AI Studio key, default model gemini-2.5-flash);
"claude" uses an Anthropic key.
The on/off switch is ai_happenings_enabled in saves/league/config.json.
"""

from __future__ import annotations

import os
import re
import json
import time
import urllib.request
import urllib.error

_BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH     = os.path.join(_BASE_DIR, "llm.json")
_SERVER_CFG_PATH = os.path.join(_BASE_DIR, "saves", "league", "config.json")
_LOG_PATH        = os.path.join(_BASE_DIR, "saves", "league", "activity_logs", "ai_happenings.jsonl")
_API_URL         = "https://api.anthropic.com/v1/messages"
_API_VERSION     = "2023-06-01"
_DEFAULT_MODEL   = "claude-sonnet-5-5"
_GEMINI_URL      = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_GEMINI_FALLBACKS = ["gemini-3.5-flash-lite", "gemini-2.0-flash"]
_TRANSIENT_CODES  = {429, 500, 502, 503, 504}

_ANSI_RE   = re.compile(r"\x1b\[[0-9;]*m")
_HEADER_RE = re.compile(r"^(\s*\x1b\[[0-9;]*mArena Happenings\x1b\[[0-9;]*m\s*)", re.S)
_NAME_RE   = re.compile(r"\b[A-Z][a-zA-Z\-]+\b")   # stops at an apostrophe, so "EARTH's" yields "EARTH"
_NUM_RE    = re.compile(r"\d+")

_SYSTEM_PROMPT = (
    "You are the ringside reporter for a gladiatorial arena newsletter. You will be given the "
    "'Arena Happenings' column for one turn, written from a fixed set of facts. Rewrite it as a "
    "vivid, immersive, natural-sounding piece of arena journalism.\n\n"
    "Rules:\n"
    "- Keep every fact: all warrior, team, manager and champion names, records, ranks, point "
    "totals, deaths and the turn number. Keep numerals as numerals.\n"
    "- Do not invent fights, deaths, promotions, names or numbers that are not in the source.\n"
    "- Keep roughly the same length and the same order of topics, as several paragraphs.\n"
    "- Plain text only: no markdown, no headings, no bullet points, no all-caps lines.\n"
    "- Separate paragraphs with a blank line.\n"
    "- Output only the rewritten column, with no preface or commentary."
)


def _enabled() -> bool:
    """Admin toggle. Defaults to off when the config is missing or unreadable."""
    try:
        with open(_SERVER_CFG_PATH, "r", encoding="utf-8") as f:
            return bool(json.load(f).get("ai_happenings_enabled", False))
    except Exception:
        return False


def _load_config() -> dict:
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


class _TransientError(RuntimeError):
    """Overload/rate-limit/timeout: worth retrying or trying another model."""


class _ModelUnavailable(_TransientError):
    """Model retired or unknown (404): skip it without retrying."""


def _call_gemini(cfg: dict, body_text: str, arena_name: str, turn_num: int, model: str) -> str:
    payload = {
        "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{
            "role": "user",
            "parts": [{"text": f"Arena: {arena_name}\nTurn: {turn_num}\n\n{body_text}"}],
        }],
        # Gemini 2.5 models count internal "thinking" tokens against this limit, so keep it generous.
        "generationConfig": {"maxOutputTokens": int(cfg.get("max_tokens", 4000))},
    }
    req = urllib.request.Request(
        _GEMINI_URL.format(model=model),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-goog-api-key": cfg["api_key"],
            "content-type":   "application/json",
            "User-Agent":     "Bloodspire-Server/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(cfg.get("timeout", 30))) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}"
        if e.code == 404:
            raise _ModelUnavailable(msg)
        raise (_TransientError if e.code in _TRANSIENT_CODES else RuntimeError)(msg)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise _TransientError(f"network error: {e}")
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError(f"no candidates returned: {str(data.get('promptFeedback', data))[:200]}")
    parts = (cands[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts).strip()


def _call_claude(cfg: dict, body_text: str, arena_name: str, turn_num: int) -> str:
    payload = {
        "model":      cfg.get("model", _DEFAULT_MODEL),
        "max_tokens": int(cfg.get("max_tokens", 2000)),
        "system":     _SYSTEM_PROMPT,
        "messages": [{
            "role": "user",
            "content": f"Arena: {arena_name}\nTurn: {turn_num}\n\n{body_text}",
        }],
    }
    req = urllib.request.Request(
        _API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key":         cfg["api_key"],
            "anthropic-version": _API_VERSION,
            "content-type":      "application/json",
            "User-Agent":        "Bloodspire-Server/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(cfg.get("timeout", 30))) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}")
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


def _call_gemini_with_fallback(cfg: dict, body_text: str, arena_name: str, turn_num: int) -> str:
    """Try each model in order (cfg "models", else model + defaults); move on only for transient errors."""
    models = cfg.get("models") or [cfg.get("model") or _DEFAULT_GEMINI_MODEL] + _GEMINI_FALLBACKS
    last = None
    for model in models:
        for attempt in range(2):                      # one quick retry per model
            try:
                return _call_gemini(cfg, body_text, arena_name, turn_num, model)
            except _TransientError as e:
                last = e
                print(f"  AI Arena Happenings: {model} unavailable ({str(e)[:80]})")
                if isinstance(e, _ModelUnavailable):
                    break                             # retired/unknown model: no point retrying
                if attempt == 0:
                    time.sleep(2)
    raise RuntimeError(f"all models failed; last error: {last}")


def _mid_sentence_names(text: str) -> set:
    """Capitalised words that are not merely sentence openers (likely proper names)."""
    names = set()
    for m in _NAME_RE.finditer(text):
        before = text[:m.start()].rstrip()
        if before and before[-1] not in ".!?\"'\n" and m.group(0) not in ("The", "A", "An", "I"):
            names.add(m.group(0))
    return names


def _validate(original: str, rewritten: str) -> str:
    """Return '' if the rewrite is acceptable, else a reason it was rejected."""
    if not rewritten:
        return "empty reply"
    ratio = len(rewritten) / max(1, len(original))
    if not 0.5 <= ratio <= 2.0:
        return f"length ratio {ratio:.2f}"
    for line in rewritten.splitlines():
        s = line.strip()
        if len(s) > 2 and s.isupper():
            return f"all-caps line: {s[:40]}"
    if "arena happenings" in rewritten.lower():
        return "repeats section header"
    missing_nums = {n for n in _NUM_RE.findall(original) if n not in set(_NUM_RE.findall(rewritten))}
    if missing_nums:
        return f"numbers missing: {sorted(missing_nums)[:5]}"
    names = _mid_sentence_names(original)
    if names:
        _rw_lower = rewritten.lower()
        missing = [n for n in names if n.lower() not in _rw_lower]
        if len(missing) > 0.1 * len(names):
            return f"names missing: {missing[:5]}"
    return ""


def _clean(original: str, rewritten: str) -> str:
    """Strip markdown and any title line the model added above the column."""
    text = re.sub(r"\*\*|__", "", rewritten)
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.M)
    first, sep, rest = text.partition("\n\n")
    first_line = first.strip()
    if sep and "\n" not in first_line and len(first_line) < 120 and first_line[-1:] not in ".!?\"'":
        orig_first = original.split("\n\n", 1)[0].strip()
        if not orig_first or first_line[:30] != orig_first[:30]:
            text = rest
    return text.strip()


def _log(entry: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def rewrite_happenings(section_text: str, arena_name: str = "The Agony Amphitheatre",
                       turn_num: int = 0) -> str:
    """Return section_text with its body rewritten by Claude, or unchanged on any failure."""
    try:
        if not _enabled():
            return section_text
        cfg = _load_config()
        if not cfg.get("api_key"):
            print("  WARNING: AI Arena Happenings enabled but llm.json has no api_key; using template text")
            return section_text

        m = _HEADER_RE.match(section_text)
        if not m:
            print("  WARNING: AI Arena Happenings: header not found; using template text")
            return section_text
        header = m.group(1)
        body = _ANSI_RE.sub("", section_text[m.end():]).strip()
        if not body:
            return section_text

        started = time.time()
        call = _call_claude if cfg.get("provider", "gemini").lower() == "claude" else _call_gemini_with_fallback
        rewritten = _clean(body, call(cfg, body, arena_name, turn_num))
        problem = _validate(body, rewritten)
        _log({"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "turn": turn_num,
              "arena": arena_name, "accepted": not problem, "reason": problem,
              "seconds": round(time.time() - started, 1),
              "original": body, "rewritten": rewritten})
        if problem:
            print(f"  WARNING: AI Arena Happenings rewrite rejected ({problem}); using template text")
            return section_text
        print(f"  AI Arena Happenings rewritten ({arena_name}, {time.time() - started:.1f}s)")
        return header + rewritten
    except Exception as e:
        print(f"  WARNING: AI Arena Happenings failed ({e}); using template text")
        return section_text
