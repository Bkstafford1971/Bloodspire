"""
Soul Spire Watch -- a per-turn HTML report on warriors who are close to leaving the
Soul Spire, one way or the other.

  * LAST LIFE      -- one death from being claimed by the land of the dead for good.
  * CLOSE TO ELITE -- near the requirements for a second life in the Elite Spire,
                      with exactly what each warrior still needs.

Written to saves/league/reports/soul_spire_watch_turn_NNNN.html by the Soul Spire
turn. Pure functions over team dicts: no imports from league_server, so it can be
tested on its own. It is not linked from the web page.
"""
from __future__ import annotations

import html
import math
import os
import time
from typing import Dict, List, Optional

# A warrior counts as "close" to the Elite Spire when every requirement is met or within
# these margins. Override with arena_rules["watch_margins"] in saves/veteran/config.json.
DEFAULT_MARGINS = {
    "fights":      10,    # lifetime fights still needed
    "trains":      10,    # skill + attribute trains still needed
    "soul_fights":  5,    # Soul Spire fights still needed
    "win_rate":  0.05,    # how far below the win rate requirement (5 points)
}


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _trains(w: dict) -> int:
    skills = w.get("skills") or {}
    gains = w.get("attribute_gains") or {}
    try:
        return int(sum(skills.values()) + sum(gains.values()))
    except Exception:
        return 0


def _soul_fights(w: dict) -> int:
    return sum(1 for f in (w.get("fight_history") or [])
               if isinstance(f, dict) and f.get("arena") == "veteran")


def _wins_needed(wins: int, total: int, target: float) -> int:
    """Straight wins needed to lift the win rate to `target`."""
    if total <= 0 or wins / total >= target or target >= 1:
        return 0
    return max(0, math.ceil((target * total - wins) / (1 - target)))


def assess(w: dict, criteria: dict, min_soul_fights: int, max_deaths: int) -> dict:
    """Work out one Soul Spire warrior's lives and Elite progress."""
    wins, losses = int(w.get("wins") or 0), int(w.get("losses") or 0)
    total = wins + losses
    rate = wins / total if total else 0.0
    min_fights = int(criteria.get("min_fights", 40))
    min_rate = float(criteria.get("min_win_rate", 0.65))
    min_trains = int(criteria.get("min_trains", 45))
    trains, soul = _trains(w), _soul_fights(w)
    deaths = int(w.get("soul_spire_deaths") or 0)
    return {
        "name": w.get("name", "?"),
        "wins": wins, "losses": losses, "kills": int(w.get("kills") or 0),
        "total": total, "rate": rate,
        "trains": trains, "soul": soul,
        "lives_left": max(0, max_deaths - deaths), "lives_max": max_deaths,
        "need_fights": max(0, min_fights - total),
        "need_trains": max(0, min_trains - trains),
        "need_soul": max(0, min_soul_fights - soul),
        "rate_gap": max(0.0, min_rate - rate),
        "need_wins": _wins_needed(wins, total, min_rate),
        "min_fights": min_fights, "min_rate": min_rate,
        "min_trains": min_trains, "min_soul": min_soul_fights,
    }


def _is_close(a: dict, m: dict) -> bool:
    return (a["need_fights"] <= m["fights"] and a["need_trains"] <= m["trains"]
            and a["need_soul"] <= m["soul_fights"] and a["rate_gap"] <= m["win_rate"])


def _gap_score(a: dict) -> float:
    """Smaller = closer. Each requirement's shortfall as a share of what it asks for."""
    return (a["need_fights"] / max(1, a["min_fights"]) + a["need_trains"] / max(1, a["min_trains"])
            + a["need_soul"] / max(1, a["min_soul"]) + a["rate_gap"] / max(0.01, a["min_rate"]))


def _hearts(left: int, mx: int) -> str:
    return "&#9829;" * left + "&#9825;" * max(0, mx - left)


def _needs_text(a: dict) -> str:
    parts = []
    if a["need_fights"]:
        parts.append(f"{a['need_fights']} more fight{'s' if a['need_fights'] != 1 else ''}")
    if a["rate_gap"] > 0:
        parts.append(f"win rate up to {int(a['min_rate'] * 100)}% (about {a['need_wins']} straight win"
                     f"{'s' if a['need_wins'] != 1 else ''})")
    if a["need_trains"]:
        parts.append(f"{a['need_trains']} more train{'s' if a['need_trains'] != 1 else ''}")
    if a["need_soul"]:
        parts.append(f"{a['need_soul']} more Soul Spire fight{'s' if a['need_soul'] != 1 else ''}")
    return "; ".join(parts) if parts else "Meets every requirement"


def collect(teams: List[dict], criteria: dict, min_soul_fights: int, max_deaths: int,
            margins: Optional[dict] = None) -> Dict[str, list]:
    """Return {'last_life': [...], 'close_elite': [...], 'in_spire': int}. Each entry is an
    assess() dict plus team_name / manager_name."""
    m = {**DEFAULT_MARGINS, **(margins or {})}
    last_life, close, count = [], [], 0
    for td in teams:
        for sec in ("warriors", "archived_warriors"):
            for w in (td.get(sec) or []):
                if (not isinstance(w, dict) or w.get("is_dead") or w.get("is_retired")
                        or (w.get("current_arena") or "normal") != "veteran"):
                    continue
                count += 1
                a = assess(w, criteria, min_soul_fights, max_deaths)
                a["team_name"] = td.get("team_name", "?")
                a["manager_name"] = td.get("manager_name", "")
                if a["lives_left"] <= 1:
                    last_life.append(a)
                if _is_close(a, m):
                    close.append(a)
    last_life.sort(key=lambda a: (-a["total"], a["name"]))
    close.sort(key=lambda a: (_gap_score(a), a["name"]))
    return {"last_life": last_life, "close_elite": close, "in_spire": count}


_CSS = """
:root{--bg:#f6f1e7;--card:#fffdf8;--tx:#2b2418;--dim:#7a6e58;--line:#d9cdb4;--hd:#5a2a1a;--bad:#a3261f;--good:#2f6b3a;--gold:#9a6b14}
@media (prefers-color-scheme:dark){:root{--bg:#17130e;--card:#211b14;--tx:#eadfc8;--dim:#a39880;--line:#3b3224;--hd:#e0a577;--bad:#ff7b72;--good:#7fd18b;--gold:#e3b04b}}
*{box-sizing:border-box}body{margin:0;padding:16px;background:var(--bg);color:var(--tx);font:14px/1.45 Georgia,serif}
.wrap{max-width:1000px;margin:0 auto}h1{margin:0 0 2px;color:var(--hd);font-size:24px}
.sub{color:var(--dim);margin:0 0 14px;font-size:13px}h2{color:var(--hd);margin:22px 0 4px;font-size:18px;border-bottom:1px solid var(--line);padding-bottom:3px}
.note{color:var(--dim);font-size:12px;margin:0 0 8px}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 12px;min-width:120px}
.stat b{display:block;font-size:20px}.stat span{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line)}
th,td{padding:5px 9px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--dim);background:var(--bg)}td.n{text-align:right}
td.wrapc{white-space:normal;min-width:240px}.hearts{color:var(--bad);letter-spacing:2px}.ok{color:var(--good)}.warn{color:var(--bad)}
.empty{background:var(--card);border:1px dashed var(--line);padding:10px 12px;color:var(--dim);border-radius:6px}
.ev{background:var(--card);border-left:4px solid var(--gold);padding:6px 10px;margin:4px 0;border-radius:0 6px 6px 0}
.ev.dead{border-left-color:var(--bad)}
"""


def render_html(data: Dict[str, list], turn_num: int, max_deaths: int, criteria: dict,
                min_soul_fights: int, ascended: Optional[list] = None,
                fallen: Optional[list] = None, generated: Optional[str] = None) -> str:
    ascended, fallen = ascended or [], fallen or []
    generated = generated or time.strftime("%Y-%m-%d %H:%M")
    ll, ce = data["last_life"], data["close_elite"]

    def stat(n, label):
        return f'<div class="stat"><b>{n}</b><span>{_esc(label)}</span></div>'

    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Soul Spire Watch - Turn {turn_num}</title><style>{_CSS}</style></head><body><div class='wrap'>",
           f"<h1>Soul Spire Watch</h1><p class='sub'>After turn {turn_num} &middot; generated {_esc(generated)}</p>",
           "<div class='stats'>",
           stat(data["in_spire"], "In the Soul Spire"), stat(len(ll), "On their last life"),
           stat(len(ce), "Close to Elite"), stat(len(ascended), "Ascended this turn"),
           stat(len(fallen), "Fell for good this turn"), "</div>"]

    if ascended or fallen:
        out.append("<h2>This turn</h2>")
        for e in ascended:
            out.append(f"<div class='ev'><b>{_esc(e.get('warrior_name'))}</b> ({_esc(e.get('team_name'))}) "
                       f"ascended to the Elite Spire, {_esc(e.get('record', ''))}.</div>")
        for e in fallen:
            out.append(f"<div class='ev dead'><b>{_esc(e.get('name'))}</b> ({_esc(e.get('team'))}) "
                       f"was claimed by the land of the dead, slain by {_esc(e.get('killed_by'))}.</div>")

    out.append("<h2>On their last life</h2>")
    out.append(f"<p class='note'>The next death in the Soul Spire is permanent for these warriors "
               f"({max_deaths} lives in total).</p>")
    if ll:
        out.append("<div class='tw'><table><tr><th>Warrior</th><th>Team</th><th>Manager</th><th>Lives</th>"
                   "<th class='n'>Record</th><th class='n'>Soul fights</th></tr>")
        for a in ll:
            out.append(f"<tr><td><b>{_esc(a['name'])}</b></td><td>{_esc(a['team_name'])}</td>"
                       f"<td>{_esc(a['manager_name'])}</td><td class='hearts'>{_hearts(a['lives_left'], a['lives_max'])}</td>"
                       f"<td class='n'>{a['wins']}-{a['losses']}-{a['kills']}</td><td class='n'>{a['soul']}</td></tr>")
        out.append("</table></div>")
    else:
        out.append("<div class='empty'>Nobody is on their last life.</div>")

    out.append("<h2>Close to the Elite Spire</h2>")
    out.append(f"<p class='note'>Requirements for a second life in the Elite Spire: {criteria.get('min_fights', 40)} career fights, "
               f"{int(float(criteria.get('min_win_rate', 0.65)) * 100)}% wins, {criteria.get('min_trains', 45)} skill and attribute trains, "
               f"and at least {min_soul_fights} Soul Spire fights. Shown here when every requirement is met or nearly met. Closest first.</p>")
    if ce:
        out.append("<div class='tw'><table><tr><th>Warrior</th><th>Team</th><th>Manager</th><th class='n'>Fights</th>"
                   "<th class='n'>Win %</th><th class='n'>Trains</th><th class='n'>Soul fights</th><th>Still needs</th></tr>")
        for a in ce:
            def cell(val, short):
                return f"<td class='n {'warn' if short else 'ok'}'>{val}</td>"
            out.append(f"<tr><td><b>{_esc(a['name'])}</b></td><td>{_esc(a['team_name'])}</td><td>{_esc(a['manager_name'])}</td>"
                       + cell(f"{a['total']}/{a['min_fights']}", a["need_fights"])
                       + cell(f"{int(a['rate'] * 100)}%", a["rate_gap"] > 0)
                       + cell(f"{a['trains']}/{a['min_trains']}", a["need_trains"])
                       + cell(f"{a['soul']}/{a['min_soul']}", a["need_soul"])
                       + f"<td class='wrapc'>{_esc(_needs_text(a))}</td></tr>")
        out.append("</table></div>")
    else:
        out.append("<div class='empty'>Nobody is close to the Elite Spire yet.</div>")

    out.append("</div></body></html>")
    return "".join(out)


def write_report(teams: List[dict], criteria: dict, min_soul_fights: int, max_deaths: int,
                 turn_num: int, output_dir: str, ascended: Optional[list] = None,
                 fallen: Optional[list] = None, margins: Optional[dict] = None) -> str:
    """Build and write this turn's report. Returns the file path."""
    data = collect(teams, criteria, min_soul_fights, max_deaths, margins)
    page = render_html(data, turn_num, max_deaths, criteria, min_soul_fights, ascended, fallen)
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"soul_spire_watch_turn_{turn_num:04d}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path
