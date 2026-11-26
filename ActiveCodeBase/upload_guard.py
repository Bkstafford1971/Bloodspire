# =============================================================================
# upload_guard.py - Server-side validation of uploaded teams
# =============================================================================
# The client is never trusted with anything the server computes. When a team is
# uploaded, each warrior is rebuilt from the SERVER's saved copy and only the
# settings a manager is allowed to change (gear, training picks, strategies,
# flags, taunts) are taken from the upload, after being checked.
#
# Everything else - attributes, skills, luck, injuries, records, history,
# arena/promotion state - always comes from the server's file, so editing a
# local save (or forging an upload) cannot change it.
# =============================================================================

import copy
from typing import Dict, List, Optional, Set, Tuple

TEAM_SIZE = 5
MAX_STRATEGIES = 6
MAX_TRAINS = 3          # combat.py only applies the first three
MAX_TEXT = 500
MAX_AVOID_WARRIORS = 50
MAX_TAUNTS = 60

# Settings a manager may change. Anything not listed here is server-owned.
CLIENT_OWNED_FIELDS = (
    "armor", "helm", "primary_weapon", "secondary_weapon", "backup_weapon",
    "trains", "strategies", "challenge_strategies", "challenge_strategy_enabled",
    "want_monster_fight", "want_retire", "run_this_turn",
    "taunts_jeers", "blood_cry", "avoid_warriors",
)

# Team-level history the client has no business editing.
SERVER_OWNED_TEAM_FIELDS = ("fallen_warriors", "turn_history", "last_turn_ran", "auto_carry_streak")


class UploadRejected(Exception):
    """The upload cannot be accepted. The message is safe to show the player."""


# ---------------------------------------------------------------------------
# VALID-VALUE LOOKUPS (built from the game's own tables)
# ---------------------------------------------------------------------------

def build_lookups() -> dict:
    """Collect the sets of legal values from the game modules."""
    from warrior import (
        ALL_SKILLS, ATTRIBUTES, FIGHTING_STYLES, TRIGGERS, AIM_DEFENSE_POINTS,
    )
    from weapons import WEAPONS
    from armor import armor_selection_menu, helm_selection_menu

    train_ok: Set[str] = set(ALL_SKILLS) | {a for a in ATTRIBUTES if a != "size"}
    for key, wpn in WEAPONS.items():
        train_ok.add(key)
        train_ok.add(wpn.skill_key)
        train_ok.add(wpn.display.lower().replace(" ", "_").replace("&", "and"))
        train_ok.add(wpn.display.lower().replace(" ", "_"))

    weapons = {w.display for w in WEAPONS.values()} | {"Open Hand"}
    return {
        "train_ok":  train_ok,
        "armor":     set(armor_selection_menu()) | {"None"},
        "helm":      set(helm_selection_menu()) | {"None"},
        "weapons":   weapons,
        "styles":    set(FIGHTING_STYLES),
        "aim":       set(AIM_DEFENSE_POINTS),
        "triggers":  set(TRIGGERS) | {"Always"},
    }


# ---------------------------------------------------------------------------
# FIELD CLEANERS - each returns the cleaned value, or the sentinel _KEEP to
# leave the server's value in place.
# ---------------------------------------------------------------------------

_KEEP = object()


def _clean_gear(value, allowed: Set[str], server_value, none_ok: bool = False):
    if value is None or value == "":
        return None if none_ok else _KEEP
    if not isinstance(value, str):
        return _KEEP
    # Accept a value the server already has (legacy spellings) or a legal one.
    if value in allowed or value == server_value:
        return value
    return _KEEP


def _clean_trains(value, lookups) -> object:
    if not isinstance(value, list):
        return _KEEP
    out = []
    for t in value:
        if not isinstance(t, str):
            continue
        key = t.strip().lower().replace(" ", "_")
        if key in lookups["train_ok"]:
            out.append(key)
        if len(out) >= MAX_TRAINS:
            break
    return out


def _clean_strategies(value, lookups) -> object:
    if not isinstance(value, list):
        return _KEEP
    out = []
    for row in value[:MAX_STRATEGIES]:
        if not isinstance(row, dict):
            continue
        trigger = row.get("trigger")
        if trigger not in lookups["triggers"]:
            continue
        style = row.get("style")
        if style not in lookups["styles"]:
            style = "Strike"
        aim = row.get("aim_point")
        if aim not in lookups["aim"]:
            aim = "None"
        defense = row.get("defense_point")
        if defense not in lookups["aim"]:
            defense = "None"
        try:
            activity = max(0, min(9, int(row.get("activity", 5))))
        except (TypeError, ValueError):
            activity = 5
        out.append({"trigger": trigger, "style": style, "activity": activity,
                    "aim_point": aim, "defense_point": defense})
    return out


def _clean_text(value) -> object:
    if not isinstance(value, str):
        return _KEEP
    return value[:MAX_TEXT]


def _clean_taunts(value) -> object:
    if not isinstance(value, dict):
        return _KEEP
    out = {}
    for k, v in list(value.items())[:MAX_TAUNTS]:
        if isinstance(k, str) and isinstance(v, str):
            out[k[:80]] = v[:MAX_TEXT]
    return out


def _clean_avoid(value) -> object:
    if not isinstance(value, list):
        return _KEEP
    return [n[:60] for n in value[:MAX_AVOID_WARRIORS] if isinstance(n, str)]


def clean_settings(updates: dict, current: dict, lookups: dict) -> dict:
    """Validate the manager-owned settings in `updates`. Returns only the fields
    that passed, cleaned. `current` is the server's warrior (used to tolerate a
    legacy spelling it already holds)."""
    out = {}
    for field in CLIENT_OWNED_FIELDS:
        if field not in updates:
            continue
        value = updates[field]
        if field == "armor":
            cleaned = _clean_gear(value, lookups["armor"], current.get(field))
        elif field == "helm":
            cleaned = _clean_gear(value, lookups["helm"], current.get(field))
        elif field in ("primary_weapon", "secondary_weapon"):
            cleaned = _clean_gear(value, lookups["weapons"], current.get(field))
        elif field == "backup_weapon":
            if isinstance(value, str) and value.strip().lower() in ("none", "open hand", ""):
                cleaned = None
            else:
                cleaned = _clean_gear(value, lookups["weapons"], current.get(field), none_ok=True)
        elif field == "trains":
            cleaned = _clean_trains(value, lookups)
        elif field in ("strategies", "challenge_strategies"):
            cleaned = _clean_strategies(value, lookups)
            # A warrior must always keep a usable main strategy list.
            if field == "strategies" and cleaned is not _KEEP and not cleaned:
                cleaned = _KEEP
        elif field in ("challenge_strategy_enabled", "want_monster_fight",
                       "want_retire", "run_this_turn"):
            cleaned = bool(value)
        elif field == "blood_cry":
            cleaned = _clean_text(value)
        elif field == "taunts_jeers":
            cleaned = _clean_taunts(value)
        elif field == "avoid_warriors":
            cleaned = _clean_avoid(value)
        else:
            cleaned = _KEEP
        if cleaned is not _KEEP:
            out[field] = cleaned
    return out


def apply_client_settings(server_w: dict, uploaded_w: dict, lookups: dict) -> dict:
    """Return a copy of the server's warrior with the manager's settings applied."""
    merged = copy.deepcopy(server_w)
    merged.update(clean_settings(uploaded_w, server_w, lookups))
    return merged


# ---------------------------------------------------------------------------
# TEAM-LEVEL SANITIZING
# ---------------------------------------------------------------------------

def _index_by_id(warriors) -> Dict[int, dict]:
    out = {}
    for w in warriors or []:
        if isinstance(w, dict) and w.get("warrior_id") is not None:
            out.setdefault(w["warrior_id"], w)
    return out


def _find_server_warrior(uw: dict, slot: int, server_active: list,
                         by_id: Dict[int, dict]) -> Optional[dict]:
    """Match an uploaded warrior to the server's copy: by id, or (for an upload
    that lost its id) by same slot AND same name."""
    wid = uw.get("warrior_id")
    if wid is not None:
        return by_id.get(wid)
    if slot < len(server_active):
        sw = server_active[slot]
        if (isinstance(sw, dict)
                and str(sw.get("name", "")).lower() == str(uw.get("name", "")).lower()):
            return sw
    return None


def sanitize_uploaded_team(up: dict, server: Optional[dict], lookups: dict,
                           manager_name: str = "", strict: bool = True) -> List[str]:
    """Rewrite `up` (the uploaded team dict) in place so every server-owned value
    comes from `server` (the team's saved file).

    Returns a list of notes describing anything that was changed or dropped.
    Raises UploadRejected when the upload cannot be trusted at all.
    With strict=False, warriors the server does not know are passed through
    untouched (legacy behaviour) instead of rejected.
    """
    notes: List[str] = []
    if not isinstance(up, dict):
        raise UploadRejected("Upload did not contain a team.")

    if server is None:
        if strict:
            raise UploadRejected(
                "The server has no record of this team. Teams must be created "
                "through the game client. If you believe this is a mistake, "
                "contact the league host.")
        return notes

    if strict and manager_name and str(server.get("manager_name", "")).lower() != manager_name.lower():
        raise UploadRejected("This team does not belong to your manager account.")

    server_active = list(server.get("warriors") or [])
    server_archived = list(server.get("archived_warriors") or [])
    by_id = _index_by_id(server_active)
    for wid, w in _index_by_id(server_archived).items():
        by_id.setdefault(wid, w)

    # ---- active roster -------------------------------------------------
    uploaded = list(up.get("warriors") or [])[:TEAM_SIZE]
    cleaned_roster = []
    for slot, uw in enumerate(uploaded):
        if uw is None:
            cleaned_roster.append(None)
            continue
        if not isinstance(uw, dict):
            raise UploadRejected(f"Warrior in slot {slot + 1} is malformed.")
        sw = _find_server_warrior(uw, slot, server_active, by_id)
        if sw is None:
            if strict:
                raise UploadRejected(
                    f"Warrior '{uw.get('name', '?')}' in slot {slot + 1} was not created "
                    f"by the server. New and replacement warriors must be rolled up "
                    f"in the game client. Close the app completely and reopen it to update, "
                    f"then rebuild this warrior.")
            cleaned_roster.append(uw)
            continue
        merged = apply_client_settings(sw, uw, lookups)
        # A forged stat is silently discarded; log it so the host can see it.
        for field in ("strength", "dexterity", "constitution", "intelligence",
                      "presence", "size", "luck", "skills", "injuries", "attribute_gains",
                      "initial_stats", "max_hp", "wins", "losses", "kills",
                      "recognition", "is_dead", "is_retired", "current_arena"):
            if field in uw and uw[field] != sw.get(field):
                notes.append(f"{sw.get('name', '?')}: client value for '{field}' "
                             f"differed from the server's and was discarded")
        cleaned_roster.append(merged)
    up["warriors"] = cleaned_roster

    # ---- archived warriors --------------------------------------------
    arch_by_id = _index_by_id(server_archived)
    seen = set()
    cleaned_arch = []
    for aw in (up.get("archived_warriors") or []):
        if not isinstance(aw, dict):
            continue
        wid = aw.get("warrior_id")
        if wid is not None and wid in arch_by_id:
            cleaned_arch.append(copy.deepcopy(arch_by_id[wid]))
            seen.add(wid)
        else:
            # Unknown to the server: keep it as history but make it inert so it
            # cannot be used to smuggle a fighter into an arena.
            aw = copy.deepcopy(aw)
            aw["current_arena"] = ""
            aw["pending_promotion"] = None
            cleaned_arch.append(aw)
            notes.append(f"archived warrior '{aw.get('name', '?')}' not known to server; neutralised")
    for wid, aw in arch_by_id.items():
        if wid not in seen:
            cleaned_arch.append(copy.deepcopy(aw))
    up["archived_warriors"] = cleaned_arch

    # ---- team-level history -------------------------------------------
    for field in SERVER_OWNED_TEAM_FIELDS:
        if field in server:
            up[field] = copy.deepcopy(server[field])

    # Blood challenges are created and expired by the server; the manager may
    # only pick which warrior answers a challenge.
    if isinstance(server.get("blood_challenges"), list):
        picks = {}
        for bc in (up.get("blood_challenges") or []):
            if isinstance(bc, dict):
                picks[(bc.get("target_name"), bc.get("dead_warrior_name"))] = bc.get("challenger_name")
        merged_bc = []
        for bc in server["blood_challenges"]:
            bc = copy.deepcopy(bc)
            choice = picks.get((bc.get("target_name"), bc.get("dead_warrior_name")))
            if isinstance(choice, str) and choice:
                bc["challenger_name"] = choice[:60]
            merged_bc.append(bc)
        up["blood_challenges"] = merged_bc

    return notes
