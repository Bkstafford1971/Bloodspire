# =============================================================================
# autopilot.py - AI "autopilot" for human-owned manager accounts
# =============================================================================
# Lets a real manager account (e.g. one of the arena-filler accounts) run itself.
# The account keeps its identity, its warriors and its themes. The owner still
# creates replacement warriors by hand. The autopilot only touches the settings a
# manager is allowed to change (strategies, training, gear blanks), never stats.
#
# What it does, once per turn, on each enabled team's upload:
#   1. NEW warriors (a fresh replacement still on the default one-row strategy
#      and an empty training queue): pick the closest-fitting ai_brain archetype
#      for the warrior's real race/stats/weapon, then set strategies and training.
#      Gear is only filled where it was left blank (the owner's choices stand).
#   2. EXISTING warriors (only when the upload is an auto-carry, i.e. the owner
#      did not upload by hand this turn): make sure the fatigue rows exist,
#      fill an empty training queue, and rework a warrior that is losing, using
#      the brain's league-wide evidence (strategy package / armor tier / training).
#      Weapons are never swapped.
#
# Safety:
#   * A manual upload wins. On a manually uploaded team only brand-new warriors
#     are configured.
#   * "hold" (whole manager, or per team) freezes the AI completely.
#   * dry_run logs what WOULD change and changes nothing.
#   * Every decision is appended to saves/league/autopilot_log.jsonl.
#   * Nothing here can fail a turn: the server wraps run() in try/except.
#
# Config: saves/league/autopilot.json (hand-editable, see DEFAULT_CONFIG).
# Per-warrior memory: saves/league/autopilot_state.json.
# =============================================================================

import copy
import json
import math
import os
import random
import time
from typing import Dict, List, Optional

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
LEAGUE_DIR   = os.path.join(BASE_DIR, "saves", "league")
CONFIG_FILE  = os.path.join(LEAGUE_DIR, "autopilot.json")
STATE_FILE   = os.path.join(LEAGUE_DIR, "autopilot_state.json")
LOG_FILE     = os.path.join(LEAGUE_DIR, "autopilot_log.jsonl")

DEFAULT_CONFIG = {
    "enabled": False,      # master switch
    "dry_run": True,       # log only, change nothing
    "new_warrior_max_fights": 0,   # a default-setup, empty-training warrior with <= this many fights
                                   # still gets the full new-warrior setup (0 = never fought only)
    "rebuild_default": True,       # a warrior that comes back at the default setup (one default row, empty
                                   # training), e.g. from a stale client upload, is rebuilt at ANY fight count.
                                   # Overrides new_warrior_max_fights. Set false to turn this off.
    "managers": {
        # "36": {"name": "Cyrus The Virus", "enabled": true, "hold": false,
        #        "teams": [100, 143],          # optional; default = all of the manager's teams
        #        "hold_teams": [],             # teams the AI must leave alone
        #        "archetype_pool": []}         # optional theme: restrict to these archetype keys
    },
}

MAX_SKILL_LEVEL = 9


# ---------------------------------------------------------------------------
# config / state / log
# ---------------------------------------------------------------------------

def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(_read_json(CONFIG_FILE, {}) or {})
    return cfg


def _log(entry: dict):
    try:
        os.makedirs(LEAGUE_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"  [AUTOPILOT] could not write log: {e}")


# ---------------------------------------------------------------------------
# archetype inference for a warrior the owner built
# ---------------------------------------------------------------------------

_STATS = ("strength", "dexterity", "constitution", "intelligence", "presence", "size")


def infer_archetype(w: dict, pool_keys: Optional[List[str]] = None) -> dict:
    """Closest ai_brain archetype to a real warrior (race, stat shape, weapon class)."""
    from ai_brain import ARCHETYPES, _WEAPON_CLASS
    cands = [a for k, a in ARCHETYPES.items() if not pool_keys or k in pool_keys] or list(ARCHETYPES.values())
    vec = [float(w.get(s, 0) or 0) for s in _STATS]
    nv = math.sqrt(sum(x * x for x in vec)) or 1.0
    primary = w.get("primary_weapon") or ""
    best, best_score = None, -1e9
    for a in cands:
        wt = [float(a["stat_weights"].get(s, 1)) for s in _STATS]
        nw = math.sqrt(sum(x * x for x in wt)) or 1.0
        cos = sum(x * y for x, y in zip(vec, wt)) / (nv * nw)
        score = 4.0 * cos
        if w.get("race") in a["races"]:
            score += 2.0
        if primary in _WEAPON_CLASS.get(a["weapon_class"], []):
            score += 1.5
        if score > best_score:
            best, best_score = a, score
    return best


def _is_default_row(r: dict) -> bool:
    return ((r.get("trigger") or "").strip() in ("Always", "Always (Default Loop)")
            and r.get("style") == "Strike" and int(r.get("activity", 5)) == 5)


def is_unconfigured(w: dict, max_fights: int = 0) -> bool:
    """A freshly created replacement: default one-row strategy, empty training, and at most
    `max_fights` fights (0 = never fought; config "new_warrior_max_fights" raises it so a warrior
    that already fought a turn on the default setup can still be set up). A warrior the owner
    configured (non-default strategy or any training) never qualifies."""
    strats = w.get("strategies") or []
    default_strats = (not strats) or (len(strats) == 1 and _is_default_row(strats[0]))
    return bool(default_strats and not (w.get("trains") or [])
                and int(w.get("total_fights", 0) or 0) <= max(0, int(max_fights or 0)))


# ---------------------------------------------------------------------------
# changes (all return a list of human-readable descriptions)
# ---------------------------------------------------------------------------

def _pick_trains(w: dict, arch: dict) -> List[str]:
    from ai_brain import _weapon_skill_key
    skills = w.get("skills") or {}
    out = []
    wk = _weapon_skill_key(w.get("primary_weapon")) if w.get("primary_weapon") not in (None, "Open Hand") else None
    for k in ([wk] if wk else []) + list(arch.get("train", [])):
        if not k or k in out:
            continue
        if k in skills and int(skills.get(k, 0) or 0) >= MAX_SKILL_LEVEL:
            continue
        out.append(k)
        if len(out) == 3:
            break
    return out


def _fill_gear(w: dict, arch: dict) -> List[str]:
    """Fill ONLY blank gear. The owner's own choices are never overridden."""
    from armor import ARMOR_TIERS, HELM_TIERS, can_wear_armor
    changes = []
    is_dw = (w.get("race") == "Dwarf")
    if (w.get("armor") or "None") == "None":
        order = list(ARMOR_TIERS)
        pref = arch.get("armor", "Leather")
        start = order.index(pref) if pref in order else 1
        for i in range(start, -1, -1):
            if can_wear_armor(order[i], w.get("strength", 10), is_dw)[0]:
                w["armor"] = order[i]
                changes.append(f"armor -> {order[i]}")
                break
    if (w.get("helm") or "None") == "None":
        w["helm"] = HELM_TIERS[min(1, len(HELM_TIERS) - 1)]
        changes.append(f"helm -> {w['helm']}")
    if (w.get("primary_weapon") or "Open Hand") == "Open Hand":
        try:
            from warrior import Warrior
            from ai import _best_wieldable_weapon
            from ai_brain import _WEAPON_CLASS
            wo = Warrior.from_dict(copy.deepcopy(w))
            prim = _best_wieldable_weapon(wo, _WEAPON_CLASS.get(arch["weapon_class"], _WEAPON_CLASS["medium"]))
            if prim != "Open Hand":
                w["primary_weapon"] = prim
                changes.append(f"primary weapon -> {prim}")
                from weapons import get_weapon
                if (w.get("secondary_weapon") or "Open Hand") == "Open Hand" and not get_weapon(prim).two_hand:
                    from ai_brain import _SECONDARY_CLASS
                    sec = _best_wieldable_weapon(
                        wo, _SECONDARY_CLASS.get(arch.get("secondary_class", "none"), ["Open Hand"]),
                        allow_open_hand=True)
                    if sec != "Open Hand":
                        w["secondary_weapon"] = sec
                        changes.append(f"secondary weapon -> {sec}")
        except Exception as e:
            changes.append(f"(weapon fill skipped: {e})")
    return changes


def setup_new_warrior(w: dict, rng: random.Random, pool_keys=None, arch_key=None) -> List[str]:
    """Fit strategies/training/blank gear. arch_key reuses the archetype this warrior was given
    before (so a rebuild keeps the same identity) instead of inferring it again."""
    from ai_brain import _package, ARCHETYPES
    arch = ARCHETYPES.get(arch_key) if arch_key else None
    arch = arch or infer_archetype(w, pool_keys)
    pack = arch["style_package"]
    changes = [f"new warrior: fitted archetype '{arch['key']}', strategy package '{pack}'"]
    w["strategies"] = _package(pack, rng)
    trains = _pick_trains(w, arch)
    if trains:
        w["trains"] = trains
        changes.append(f"trains -> {trains}")
    changes += _fill_gear(w, arch)
    return changes


def tune_existing_warrior(w: dict, state: dict, rng: random.Random, pool_keys=None) -> List[str]:
    """Light-touch maintenance. Returns descriptions of what changed."""
    from ai_brain import (get_brain, ensure_fatigue_rows, _package, _weapon_skill_key,
                          ALL_PACKAGES, TRAIN_VARIANTS, ADAPT_MIN_FIGHTS, ADAPT_COOLDOWN,
                          ADAPT_LOSING_BELOW, ADAPT_MARGIN, ADAPT_MIN_EVIDENCE)
    from armor import ARMOR_TIERS, can_wear_armor
    changes = []
    wid = str(w.get("warrior_id"))
    ws = state.setdefault(wid, {})
    if "archetype" not in ws:
        ws["archetype"] = infer_archetype(w, pool_keys)["key"]
    arch_key = ws["archetype"]

    # 1. fatigue rows (endurance 0 = a lost fight)
    rows = w.get("strategies") or []
    if rows and ensure_fatigue_rows(rows):
        changes.append("added/fixed the fatigue (very tired) strategy row")
    w["strategies"] = rows or w.get("strategies")

    # 2. empty training queue
    if not (w.get("trains") or []):
        from ai_brain import ARCHETYPES
        t = _pick_trains(w, ARCHETYPES[arch_key])
        if t:
            w["trains"] = t
            changes.append(f"trains was empty -> {t}")

    # 3. rework a losing warrior (same evidence rules as AIBrain.adapt_team)
    fights = int(w.get("total_fights", 0) or 0)
    wins, losses = int(w.get("wins", 0) or 0), int(w.get("losses", 0) or 0)
    if (fights < ADAPT_MIN_FIGHTS or (wins + losses) == 0
            or wins / (wins + losses) >= ADAPT_LOSING_BELOW
            or fights - int(ws.get("adapted_at", -99)) < ADAPT_COOLDOWN):
        return changes
    brain = get_brain()
    options = []
    cur_pack = ws.get("stratpack")
    if cur_pack:
        cur_est, _ = brain._estimate("ap", arch_key, cur_pack)
        for pk in ALL_PACKAGES + ("berserker",):
            if pk != cur_pack:
                est, n = brain._estimate("ap", arch_key, pk)
                if n >= ADAPT_MIN_EVIDENCE and est - cur_est >= ADAPT_MARGIN:
                    options.append((est - cur_est, "pack", pk, f"strategy package {cur_pack} -> {pk}"))
    order = list(ARMOR_TIERS)
    cur_arm = w.get("armor")
    if cur_arm in order:
        ci = order.index(cur_arm)
        cur_est, _ = brain._estimate("ar", arch_key, cur_arm)
        for j in (ci - 1, ci + 1):
            if 0 <= j < len(order) and can_wear_armor(order[j], w.get("strength", 10), w.get("race") == "Dwarf")[0]:
                est, n = brain._estimate("ar", arch_key, order[j])
                if n >= ADAPT_MIN_EVIDENCE and est - cur_est >= ADAPT_MARGIN:
                    options.append((est - cur_est, "armor", order[j], f"armor {cur_arm} -> {order[j]}"))
    cur_tr = ws.get("train", "base")
    cur_est, _ = brain._estimate("tr", arch_key, cur_tr)
    for tv in TRAIN_VARIANTS:
        if tv != cur_tr:
            est, n = brain._estimate("tr", arch_key, tv)
            if n >= ADAPT_MIN_EVIDENCE and est - cur_est >= ADAPT_MARGIN:
                options.append((est - cur_est, "train", tv, f"training focus {cur_tr} -> {tv}"))
    if not options:
        return changes
    options.sort(key=lambda o: -o[0])
    _, kind, val, text = options[0]
    if kind == "pack":
        w["strategies"] = _package(val, rng)
        ws["stratpack"] = val
    elif kind == "armor":
        w["armor"] = val
    else:
        new = _weapon_skill_key(w.get("primary_weapon")) if val == "wpn" else (None if val == "base" else val)
        tr = list(w.get("trains") or [])
        if not new or new in tr or not tr:
            return changes
        w["trains"] = tr[:2] + [new] if len(tr) >= 3 else tr + [new]
        ws["train"] = val
    ws["adapted_at"] = fights
    changes.append(f"losing ({wins}-{losses}): {text}")
    return changes


# ---------------------------------------------------------------------------
# validation: every field we touch must pass the same cleaner the upload guard uses
# ---------------------------------------------------------------------------

def _validate(w: dict, original: dict, lookups: dict):
    from upload_guard import clean_settings
    keys = ("armor", "helm", "primary_weapon", "secondary_weapon", "trains", "strategies")
    cleaned = clean_settings({k: w.get(k) for k in keys if k in w}, original, lookups)
    for k, v in cleaned.items():
        w[k] = v


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def _team_enabled(mcfg: dict, team_id) -> bool:
    if not mcfg.get("enabled", True) or mcfg.get("hold"):
        return False
    tid = str(team_id)
    if tid in [str(t) for t in mcfg.get("hold_teams", [])]:
        return False
    teams = mcfg.get("teams")
    return (not teams) or tid in [str(t) for t in teams]


def run(uploads: Dict[str, dict], turn_num: int, save_upload=None) -> List[str]:
    """Apply the autopilot to the human uploads in `uploads` (mutated in place).
    save_upload(turn_num, manager_id, data) persists a changed upload.
    Returns a summary line per changed warrior."""
    cfg = load_config()
    if not cfg.get("enabled"):
        return []
    dry = bool(cfg.get("dry_run", True))
    managers = cfg.get("managers") or {}
    if not managers:
        return []

    from upload_guard import build_lookups
    lookups = build_lookups()
    state = _read_json(STATE_FILE, {})
    summary = []

    for key, up in list(uploads.items()):
        mid = str(up.get("manager_id") or "")
        if mid.startswith("ai_") or mid not in managers:
            continue
        team = up.get("team")
        if not isinstance(team, dict):
            continue
        mcfg = managers[mid]
        tid = up.get("team_id") or team.get("team_id")
        if not _team_enabled(mcfg, tid):
            continue

        manual = (not up.get("auto_uploaded")) and (not up.get("autopilot"))
        pool_keys = mcfg.get("archetype_pool") or None
        # Per-manager override, else the global value (default 0 = only never-fought warriors).
        new_max_fights = mcfg.get("new_warrior_max_fights", cfg.get("new_warrior_max_fights", 0))
        if mcfg.get("rebuild_default", cfg.get("rebuild_default", True)):
            new_max_fights = 10 ** 9   # any fight count: a default, untrained warrior is rebuilt
        work = copy.deepcopy(team) if dry else team
        touched = False

        for slot, w in enumerate(work.get("warriors") or []):
            if not isinstance(w, dict) or w.get("is_dead") or w.get("is_retired"):
                continue
            original = copy.deepcopy(w)
            rng = random.Random(f"autopilot:{turn_num}:{w.get('warrior_id')}")
            try:
                if is_unconfigured(w, new_max_fights):
                    st = state.setdefault(str(w.get("warrior_id")), {})
                    prev_arch = st.get("archetype")
                    changes = setup_new_warrior(w, rng, pool_keys, prev_arch)
                    from ai_brain import ARCHETYPES
                    arch = ARCHETYPES.get(prev_arch) or infer_archetype(w, pool_keys)
                    if prev_arch and int(w.get("total_fights", 0) or 0) > 0:
                        changes.insert(0, "came back at the default setup (stale upload?): rebuilt")
                    st.update({"archetype": arch["key"], "stratpack": arch["style_package"],
                               "train": "base", "adapted_at": int(w.get("total_fights", 0) or 0)})
                elif not manual:
                    changes = tune_existing_warrior(w, state, rng, pool_keys)
                else:
                    changes = []
                if changes:
                    _validate(w, original, lookups)
            except Exception as e:
                changes = []
                w.clear(); w.update(original)
                _log({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "turn": turn_num, "manager": mid,
                      "team_id": tid, "warrior": original.get("name"), "error": str(e)})
                print(f"  [AUTOPILOT] {original.get('name')}: skipped ({e})")
            if changes:
                touched = True
                for c in changes:
                    _log({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "turn": turn_num, "manager": mid,
                          "team_id": tid, "slot": slot, "warrior": original.get("name"),
                          "change": c, "dry_run": dry})
                summary.append(f"{team.get('team_name', tid)} / {original.get('name')}: " + "; ".join(changes))

        if touched and not dry:
            # Counts as an owner-style upload so the 3-turn auto-run pause never trips.
            up["auto_uploaded"] = False
            up["autopilot"] = True
            up["uploaded_at"] = time.strftime("%Y-%m-%d %H:%M:%S") + " (AI autopilot)"
            if save_upload:
                try:
                    save_upload(turn_num, mid, up)
                except Exception as e:
                    print(f"  [AUTOPILOT] could not save upload for team {tid}: {e}")

    if not dry:
        try:
            _write_json(STATE_FILE, state)
        except Exception as e:
            print(f"  [AUTOPILOT] could not save state: {e}")
    for line in summary:
        print(f"  [AUTOPILOT{' DRY-RUN' if dry else ''}] {line}")
    return summary
