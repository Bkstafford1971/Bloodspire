# =============================================================================
# roll_registry.py - Server-side record of the stat rolls it has handed out
# =============================================================================
# A new warrior's starting stats are random. The server remembers each roll it
# issues (per manager) so that, when a team or replacement warrior is created,
# the submitted stats can be checked against the roll plus the 16 allowed
# points. Rolls are also sticky: asking again returns the same roll, so
# clearing the client cache is not a way to re-roll. Replacement warriors get
# exactly one re-roll.
# =============================================================================

import json
import os
import threading
import time
import uuid
from typing import Dict, List, Optional

from warrior import (
    ATTRIBUTES, ROLLUP_POINTS, STAT_MAX, STAT_MIN, generate_base_stats, max_addable,
)

_lock = threading.RLock()
_PATH: Optional[str] = None


def configure(saves_dir: str) -> None:
    """Point the registry at the saves folder (called once at server start)."""
    global _PATH
    _PATH = os.path.join(saves_dir, "pending_rolls.json")


def _load() -> dict:
    if _PATH and os.path.exists(_PATH):
        try:
            with open(_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
    return {"team": {}, "replacement": {}}


def _save(data: dict) -> None:
    if not _PATH:
        return
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, _PATH)


def _new_roll() -> dict:
    return {"roll_id": uuid.uuid4().hex, "base": generate_base_stats()}


# ---------------------------------------------------------------------------
# ISSUING
# ---------------------------------------------------------------------------

def get_team_rolls(manager_id: str, count: int) -> List[dict]:
    """Return this manager's pending set of rolls for a new team, creating it
    the first time. Same set is returned until the team is created."""
    with _lock:
        data = _load()
        entry = data["team"].get(manager_id)
        if not entry or len(entry.get("rolls", [])) != count:
            entry = {"rolls": [_new_roll() for _ in range(count)], "issued_at": time.time()}
            data["team"][manager_id] = entry
            _save(data)
        return entry["rolls"]


def get_replacement_roll(manager_id: str, team_id: int, slot: int, reroll: bool = False) -> dict:
    """Return the pending roll for a replacement warrior. `reroll` hands out one
    new roll; after that the roll is locked and further requests return it."""
    key = f"{manager_id}:{team_id}:{slot}"
    with _lock:
        data = _load()
        entry = data["replacement"].get(key)
        denied = False
        if entry is None:
            entry = {**_new_roll(), "rerolled": False, "issued_at": time.time()}
            data["replacement"][key] = entry
        elif reroll:
            if entry.get("rerolled"):
                denied = True
            else:
                entry = {**_new_roll(), "rerolled": True, "issued_at": time.time()}
                data["replacement"][key] = entry
        _save(data)
        return {"roll_id": entry["roll_id"], "base": entry["base"],
                "rerolled": bool(entry.get("rerolled")), "reroll_denied": denied}


# ---------------------------------------------------------------------------
# CHECKING + CONSUMING
# ---------------------------------------------------------------------------

def final_stats(base: Dict[str, int], submitted: dict) -> Dict[str, int]:
    """Check `submitted` (final attribute values) is `base` plus a legal spend of
    the rollup points. Returns the stats as ints; raises ValueError if illegal."""
    stats = {}
    spent = 0
    for attr in ATTRIBUTES:
        try:
            final = int(submitted[attr])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Missing or invalid {attr}.")
        added = final - int(base[attr])
        if added < 0:
            raise ValueError(f"{attr.capitalize()} is below the rolled value.")
        if added > max_addable(base, attr):
            raise ValueError(f"{attr.capitalize()} has too many points added.")
        if not (STAT_MIN <= final <= STAT_MAX):
            raise ValueError(f"{attr.capitalize()} is out of range.")
        spent += added
        stats[attr] = final
    if spent != ROLLUP_POINTS:
        raise ValueError(f"Exactly {ROLLUP_POINTS} points must be spent (got {spent}).")
    return stats


def find_team_roll(manager_id: str, roll_id) -> Optional[dict]:
    with _lock:
        entry = _load()["team"].get(manager_id)
        for r in (entry or {}).get("rolls", []):
            if r.get("roll_id") == roll_id:
                return r
    return None


def consume_team_rolls(manager_id: str) -> None:
    with _lock:
        data = _load()
        if data["team"].pop(manager_id, None) is not None:
            _save(data)


def find_replacement_roll(manager_id: str, team_id: int, slot: int, roll_id) -> Optional[dict]:
    with _lock:
        entry = _load()["replacement"].get(f"{manager_id}:{team_id}:{slot}")
        if entry and entry.get("roll_id") == roll_id:
            return entry
    return None


def consume_replacement_roll(manager_id: str, team_id: int, slot: int) -> None:
    with _lock:
        data = _load()
        if data["replacement"].pop(f"{manager_id}:{team_id}:{slot}", None) is not None:
            _save(data)
