# =============================================================================
# save.py - BLOODSPIRE Save & Load System
# =============================================================================
# All data is stored as JSON files under the saves/ directory.
#
# Directory layout:
#   saves/
#     game_state.json         - global state (next team ID, turn counter)
#     teams/
#       team_0001.json        - one file per team
#       team_0002.json
#       ...
#     fights/
#       fight_0001.txt        - plain-text fight log
#       fight_0002.txt
#       ...
#
# Design choices:
#   - One file per team for easy inspection and debugging.
#   - Fight logs are plain text (human-readable narrative).
#   - game_state.json tracks global counters so IDs never collide.
#   - All operations use try/except with clear error messages.
# =============================================================================

import json
import os
import re
import zipfile
from file_protection import save_json_protected, load_json_protected, make_file_readonly, make_file_writable, protect_existing_file
import io
from typing import Optional, List, Dict
from team import Team

# ---------------------------------------------------------------------------
# DIRECTORY PATHS
# ---------------------------------------------------------------------------

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
SAVES_DIR      = os.path.join(BASE_DIR, "saves")
TEAMS_DIR      = os.path.join(SAVES_DIR, "teams")
FIGHTS_DIR     = os.path.join(SAVES_DIR, "fights")
LOGS_DIR       = os.path.join(SAVES_DIR, "logs")
GAME_STATE_FILE= os.path.join(SAVES_DIR, "game_state.json")
EXPORTS_DIR    = os.path.join(BASE_DIR, "exports")
RECORDS_DIR    = os.path.join(BASE_DIR, "arena_records")
SCOUTING_FILE  = os.path.join(SAVES_DIR, "scouting.json")
MONSTER_TEAM_FILE = os.path.join(SAVES_DIR, "monster_team.json")
GRAVEYARD_DIR  = os.path.join(SAVES_DIR, "graveyard")
# Legacy local-accounts file from the retired gui_server. Kept as a path
# constant so reset routines can still wipe it if it lingers on disk.
ACCOUNTS_FILE  = os.path.join(SAVES_DIR, "accounts.json")
# Central manager registry owned by league_server.py - the source of truth
# for manager names now that the local accounts.py has been removed.
LEAGUE_MANAGERS_FILE = os.path.join(SAVES_DIR, "league", "managers.json")


def _ensure_dirs():
    """Create save directories if they don't already exist."""
    for path in (SAVES_DIR, TEAMS_DIR, FIGHTS_DIR, LOGS_DIR, GRAVEYARD_DIR):
        os.makedirs(path, exist_ok=True)


# ---------------------------------------------------------------------------
# MONSTER TEAM PERSISTENCE
# ---------------------------------------------------------------------------
# The Monster team roster is normally rebuilt from the hardcoded MONSTER_ROSTER
# in team.py. But when a player warrior kills a monster, that warrior replaces
# the slain monster on the roster. To make that persistent across turns, we
# snapshot the monster team to disk after absorption. Delete the file to
# reset to the hardcoded default roster.

def load_monster_team() -> Optional[Team]:
    """Load persisted monster team from disk. Returns None if no save exists."""
    _ensure_dirs()
    if not os.path.exists(MONSTER_TEAM_FILE):
        return None
    try:
        data = load_json_protected(MONSTER_TEAM_FILE)
        team = Team.from_dict(data)
    except (FileNotFoundError, ValueError, json.JSONDecodeError, IOError, KeyError) as e:
        print(f"  WARNING: Could not load monster_team.json ({e}). Using hardcoded roster.")
        return None
    if ensure_monster_ids(team):
        save_monster_team(team)
    return team


def next_monster_id() -> str:
    """Monster IDs are their own series (M0000001, M0000002, ...) so they can
    never collide with a player warrior_id."""
    state = load_game_state()
    n = state.get("next_monster_id", 1)
    state["next_monster_id"] = n + 1
    save_game_state(state)
    return f"M{n:07d}"


def ensure_monster_ids(team: Team) -> bool:
    """Give every monster lacking an M-series id its own. Returns True if any changed."""
    changed = False
    seen = set()
    for w in team.warriors or []:
        if not w:
            continue
        wid = getattr(w, "warrior_id", None)
        if not (isinstance(wid, str) and wid.startswith("M")) or wid in seen:
            w.warrior_id = next_monster_id()
            changed = True
        seen.add(w.warrior_id)
    return changed


def save_monster_team(team: Team):
    """Persist the monster team to disk."""
    _ensure_dirs()
    ensure_monster_ids(team)
    data = team.to_dict()
    # Monsters never carry permanent injuries between turns.
    for w in data.get("warriors") or []:
        if isinstance(w, dict):
            w["injuries"] = {k: 0 for k in (w.get("injuries") or {})}
            w["injuries_text"] = []
    try:
        save_json_protected(MONSTER_TEAM_FILE, data)
    except IOError as e:
        print(f"  ERROR: Could not save monster_team.json: {e}")


# ---------------------------------------------------------------------------
# GAME STATE (global counters)
# ---------------------------------------------------------------------------

DEFAULT_GAME_STATE = {
    "next_team_id"    : 1,
    "next_fight_id"   : 1,
    "next_warrior_id" : 1,
    "next_monster_id" : 1,
    "turn_number"     : 0,
}


def load_game_state() -> dict:
    """Load global game state. Returns defaults if no save exists yet."""
    _ensure_dirs()
    if not os.path.exists(GAME_STATE_FILE):
        return DEFAULT_GAME_STATE.copy()
    try:
        # allow_tampered=True to allow the game to recover its turn/ID counters if the file is out of sync
        state = load_json_protected(GAME_STATE_FILE, allow_tampered=True)
        # Fill in any missing keys with defaults (handles version upgrades)
        for k, v in DEFAULT_GAME_STATE.items():
            state.setdefault(k, v)
        return state
    except (FileNotFoundError, ValueError, json.JSONDecodeError, IOError) as e:
        print(f"  WARNING: Could not load game_state.json ({e}). Using defaults.")
        return DEFAULT_GAME_STATE.copy()


def save_game_state(state: dict):
    """Persist global game state to disk."""
    _ensure_dirs()
    try:
        save_json_protected(GAME_STATE_FILE, state)
    except IOError as e:
        print(f"  ERROR: Could not save game_state.json: {e}")


def next_team_id() -> int:
    """Consume and return the next available team ID. Increments the counter."""
    state  = load_game_state()
    new_id = state["next_team_id"]
    state["next_team_id"] += 1
    save_game_state(state)
    return new_id


def next_fight_id() -> int:
    """Consume and return the next available fight log ID."""
    state  = load_game_state()
    new_id = state["next_fight_id"]
    state["next_fight_id"] += 1
    save_game_state(state)
    return new_id


def next_warrior_id() -> int:
    """Consume and return the next available warrior ID. Increments the counter."""
    state  = load_game_state()
    new_id = state.get("next_warrior_id", 1)
    state["next_warrior_id"] = new_id + 1
    save_game_state(state)
    return new_id


def migrate_warrior_ids() -> int:
    """
    One-time migration: assign warrior_ids to every warrior that lacks one.
    Scans all team save files, assigns sequential IDs, and re-saves changed files.
    Returns the number of warriors that received new IDs.
    """
    assigned = 0
    if not os.path.exists(TEAMS_DIR):
        return 0
    for fname in os.listdir(TEAMS_DIR):
        if not fname.startswith("team_") or not fname.endswith(".json"):
            continue
        fpath = os.path.join(TEAMS_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        changed = False
        for section in ("warriors", "archived_warriors"):
            for wd in data.get(section, []):
                if wd and not wd.get("warrior_id"):
                    wd["warrior_id"] = next_warrior_id()
                    assigned += 1
                    changed = True
        if changed:
            try:
                save_json_protected(fpath, data)
            except Exception as e:
                print(f"  WARNING: migrate_warrior_ids could not save {fname}: {e}")
    return assigned


def increment_turn():
    """Advance the global turn counter by 1."""
    state = load_game_state()
    state["turn_number"] += 1
    save_game_state(state)
    return state["turn_number"]


def current_turn() -> int:
    return load_game_state()["turn_number"]


# ---------------------------------------------------------------------------
# TEAM SAVE / LOAD
# ---------------------------------------------------------------------------

def _team_filepath(team_id: int) -> str:
    """Return the full path for a team's JSON save file."""
    return os.path.join(TEAMS_DIR, f"team_{team_id:04d}.json")


def save_team(team: Team) -> str:
    """
    Save a team to disk.
    Assigns a new team_id if the team doesn't have one yet (id == 0).
    Returns the file path written.
    """
    _ensure_dirs()

    # Assign ID on first save
    if team.team_id == 0:
        team.team_id = next_team_id()

    # Assign warrior_ids to any warrior that still lacks one (handles both Warrior objects and dicts)
    for section in (team.warriors, getattr(team, "archived_warriors", [])):
        for w in (section or []):
            if not w:
                continue
            if isinstance(w, dict):
                if not w.get("warrior_id"):
                    w["warrior_id"] = next_warrior_id()
            else:
                if getattr(w, "warrior_id", None) is None:
                    w.warrior_id = next_warrior_id()

    filepath = _team_filepath(team.team_id)
    try:
        team_dict = team.to_dict()
        refresh_skills_text(team_dict)
        # Preserve current_arena=elite/veteran for immortal warriors across every
        # save path (turn processing, upload handler, etc.) by reading the existing
        # server file before overwriting it.
        if os.path.exists(filepath):
            try:
                existing = load_json_protected(filepath, allow_tampered=True)
                # Map warrior_id (not name!) to preserve arena/promotion state.
                # CRITICAL: Must use warrior_id, not name, to prevent name-reuse bugs.
                # If a manager reuses a warrior name after the old one died, matching
                # by name alone would cause the new warrior to inherit the old one's
                # arena assignment and promotion flags.
                _arena_map = {}
                _promo_map = {}
                _champ_map = {}  # champion fields
                for _ew in (existing.get("warriors") or []):
                    if not isinstance(_ew, dict): continue
                    _wid = _ew.get("warrior_id")
                    if _wid is None: continue
                    if (_ew.get("current_arena") or "normal") in ("elite", "veteran"):
                        _arena_map[_wid] = _ew["current_arena"]
                    if _ew.get("pending_promotion"):
                        _promo_map[_wid] = _ew["pending_promotion"]
                    # Preserve champion fields if they're set in existing file
                    if _ew.get("current_champion_arena"):
                        _champ_map[_wid] = {
                            "current_champion_arena": _ew.get("current_champion_arena"),
                            "current_champion_turns": _ew.get("current_champion_turns", 0),
                            "current_champion_defenses": _ew.get("current_champion_defenses", 0),
                        }
                for _ew in (existing.get("archived_warriors") or []):
                    if not isinstance(_ew, dict): continue
                    _wid = _ew.get("warrior_id")
                    if _wid is None: continue
                    if (_ew.get("current_arena") or "normal") in ("elite", "veteran"):
                        _arena_map[_wid] = _ew["current_arena"]
                    if _ew.get("pending_promotion"):
                        _promo_map[_wid] = _ew["pending_promotion"]
                    if _ew.get("current_champion_arena"):
                        _champ_map[_wid] = {
                            "current_champion_arena": _ew.get("current_champion_arena"),
                            "current_champion_turns": _ew.get("current_champion_turns", 0),
                            "current_champion_defenses": _ew.get("current_champion_defenses", 0),
                        }
                for _w in (team_dict.get("warriors") or []):
                    if not isinstance(_w, dict): continue
                    _wid = _w.get("warrior_id")
                    if _wid and _wid in _arena_map and _w.get("current_arena") in (None, ""):
                        _w["current_arena"] = _arena_map[_wid]
                    # Only restore pending_promotion for warriors still in the normal arena;
                    # a promoted warrior has current_arena set and pending_promotion cleared.
                    if (_wid and _wid in _promo_map and not _w.get("pending_promotion")
                            and (_w.get("current_arena") or "normal") == "normal"):
                        _w["pending_promotion"] = _promo_map[_wid]
                    # Restore champion fields from existing file only if new dict doesn't have them set
                    if _wid and _wid in _champ_map and not _w.get("current_champion_arena"):
                        _w.update(_champ_map[_wid])
                for _w in (team_dict.get("archived_warriors") or []):
                    if not isinstance(_w, dict): continue
                    _wid = _w.get("warrior_id")
                    if _wid and _wid in _arena_map and _w.get("current_arena") in (None, ""):
                        _w["current_arena"] = _arena_map[_wid]
                    if (_wid and _wid in _promo_map and not _w.get("pending_promotion")
                            and (_w.get("current_arena") or "normal") == "normal"):
                        _w["pending_promotion"] = _promo_map[_wid]
                    if _wid and _wid in _champ_map:
                        if not _w.get("current_champion_arena"):
                            _w.update(_champ_map[_wid])
            except Exception:
                pass
        save_json_protected(filepath, team_dict)
        return filepath
    except IOError as e:
        raise IOError(f"Could not save team '{team.team_name}': {e}")


def load_team(team_id: int) -> Team:
    """
    Load a team from disk by its ID.
    Raises FileNotFoundError if the save doesn't exist.
    Raises ValueError if the JSON is malformed.
    """
    filepath = _team_filepath(team_id)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"No save file found for team ID {team_id} ({filepath}).")

    try:
        data = load_json_protected(filepath)
        return Team.from_dict(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Corrupted save file for team {team_id}: {e}")


def load_team_any_arena(team_id: int):
    """
    Load a team's raw dict from any arena directory (normal, elite, veteran).
    Returns the dict directly (not a Team object) for use in API responses.
    Raises FileNotFoundError if not found in any arena.
    """
    fname = f"team_{team_id:04d}.json"
    for subdir in ("teams", os.path.join("elite", "teams"), os.path.join("veteran", "teams")):
        filepath = os.path.join(SAVES_DIR, subdir, fname)
        if os.path.exists(filepath):
            try:
                return load_json_protected(filepath, allow_tampered=True)
            except Exception:
                pass
    raise FileNotFoundError(f"Team {team_id} not found in any arena directory.")


def reconcile_warrior_ids(team: Team, team_id: int) -> int:
    """
    Recover permanent warrior_ids for any warrior in `team` (active roster or
    archived) whose warrior_id is None, by name-matching against the
    previously-persisted save for team_id.

    The upload a manager submits each turn doesn't always carry warrior_id
    for every warrior, and without this, save_team() would treat them as
    brand new and mint a fresh id every turn - breaking anything that tracks
    a warrior by id across turns (e.g. the reigning champion record).

    CRITICAL: Only matches warriors that existed in the previous team save.
    - Uses (team_id, name) context to prevent cross-team and cross-manager collisions
    - Excludes archived warriors (a reused name should get a fresh ID, not inherit a dead warrior's)
    - Warns if upload is missing IDs (a sign the client is not preserving warrior_id properly)

    Call this immediately after Team.from_dict(upload) and before the team
    is used anywhere else this turn. Returns the count reconciled.
    """
    try:
        prev_team = load_team(team_id)
    except Exception:
        return 0  # brand-new team, or unreadable prior save - nothing to recover

    # Build name→id map from PREVIOUS save's ACTIVE warriors only.
    # Key: warrior name (case-insensitive)
    # Value: (warrior_id, index) to detect name collisions
    name_to_id = {}
    name_collisions = set()  # Track names that appear multiple times

    for i, w in enumerate(prev_team.warriors or []):
        if w is not None and w.name and w.warrior_id is not None:
            name_lower = w.name.lower()
            if name_lower in name_to_id:
                name_collisions.add(name_lower)  # Multiple warriors with same name
            else:
                name_to_id[name_lower] = w.warrior_id

    # DO NOT include archived warriors. If a manager reuses a name after the old
    # warrior died/retired, the new warrior should get a fresh ID, not inherit the
    # archived warrior's ID. See: THE BLACKENING (turn 48) - archived 0-1-0 was
    # matched to new 0-0-0, causing stat inheritance from a dead warrior.

    reconciled = 0
    warned = False

    for w in (team.warriors or []):
        if w is not None and w.warrior_id is None:
            name_lower = (w.name or "").lower()

            # If this name appears multiple times in the previous save, we cannot
            # safely match by name alone. Require the upload to include warrior_id.
            if name_lower in name_collisions:
                if not warned:
                    print(f"  WARNING: team_{team_id:04d} has upload with missing warrior_id "
                          f"for warrior '{w.name}', which has multiple entries in previous save. "
                          f"Cannot reconcile safely by name alone. This may indicate the client "
                          f"is not preserving warrior_id properly.")
                    warned = True
                continue

            # Otherwise, reconcile by (team_id, name)
            wid = name_to_id.get(name_lower)
            if wid is not None:
                w.warrior_id = wid
                reconciled += 1

    # Reconcile archived warriors the same way
    for wd in (getattr(team, "archived_warriors", None) or []):
        if wd is not None and wd.get("warrior_id") is None:
            name_lower = (wd.get("name") or "").lower()
            if name_lower not in name_collisions:
                wid = name_to_id.get(name_lower)
                if wid is not None:
                    wd["warrior_id"] = wid
                    reconciled += 1

    return reconciled


def refresh_skills_text(team_dict: dict):
    """Archived warriors are stored as raw dicts (often straight from a client
    upload), so their skills_text can lag their skills. Rebuild it."""
    from warrior import build_skills_text
    for section in ("warriors", "archived_warriors"):
        for w in team_dict.get(section) or []:
            if isinstance(w, dict) and isinstance(w.get("skills"), dict):
                w["skills_text"] = build_skills_text(w["skills"])


# ---------------------------------------------------------------------------
# WARRIOR-ID UNIQUENESS (per-arena champions support)
# ---------------------------------------------------------------------------
# Per-arena champion tracking follows a warrior by its permanent warrior_id
# across arenas and promotions, so every ACTIVE warrior's id must be globally
# unique. An upload occasionally carries a stale, duplicated, or another team's
# id (older clients, a copied team, a restored backup). These helpers detect and
# repair that at upload time and at the start of a turn run, WITHOUT touching ids
# that are already healthy -- they are no-ops on a clean league.

_ARENA_TEAM_SUBDIRS = ("teams", os.path.join("elite", "teams"), os.path.join("veteran", "teams"))


def _is_canonical_team_file(fname: str) -> bool:
    """True only for a real team save 'team_<digits>.json' -- excludes stray
    backups/variants like 'team_0069.backup.json' that share the prefix."""
    return (fname.startswith("team_") and fname.endswith(".json")
            and fname[len("team_"):-len(".json")].isdigit())


def _iter_all_team_files():
    """Yield (team_id, raw_dict) for every persisted team file across all arenas."""
    for subdir in _ARENA_TEAM_SUBDIRS:
        d = os.path.join(SAVES_DIR, subdir)
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if not _is_canonical_team_file(fname):
                continue
            try:
                with open(os.path.join(d, fname), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            if isinstance(data, dict):
                yield data.get("team_id"), data


def build_warrior_id_index() -> dict:
    """Map every persisted warrior_id -> (team_id, name_lower), scanning ACTIVE
    and archived warriors across all arena team files. Lets an upload be checked
    for an id that already belongs to a different team. First occurrence wins;
    read-only (never writes)."""
    index = {}
    for tid, data in _iter_all_team_files():
        for section in ("warriors", "archived_warriors"):
            for wd in (data.get(section) or []):
                if not isinstance(wd, dict):
                    continue
                wid = wd.get("warrior_id")
                if wid is not None and wid not in index:
                    index[wid] = (tid, (wd.get("name") or "").lower())
    return index


def enforce_unique_active_ids(team_dict: dict, team_id, wid_index: dict = None):
    """Ensure every ACTIVE warrior in `team_dict` carries a globally-unique
    warrior_id. Generator: yields (name, old_id, new_id) for each reassignment.

    An id is reassigned (minted fresh via next_warrior_id) ONLY on a genuine
    collision: it already belongs to a different team per `wid_index`, or it is
    duplicated by an earlier active warrior in this same upload. Healthy, unique
    ids are left untouched (no-op on a clean league). `team_dict` is the raw
    uploaded dict, mutated in place. `wid_index` is built on demand when omitted
    and is updated with kept/new ids so later teams in a batch collide correctly.
    """
    if not isinstance(team_dict, dict):
        return
    if wid_index is None:
        wid_index = build_warrior_id_index()
    try:
        tid = int(team_id)
    except (TypeError, ValueError):
        tid = team_id

    seen_this_upload = set()  # warrior_ids already claimed earlier in THIS upload
    for wd in (team_dict.get("warriors") or []):
        if not isinstance(wd, dict):
            continue
        wid = wd.get("warrior_id")
        if wid is None:
            continue  # minted later by reconcile_warrior_ids / save_team
        name_lower = (wd.get("name") or "").lower()
        owner = wid_index.get(wid)
        collision = (wid in seen_this_upload) or (owner is not None and owner[0] != tid)
        if collision:
            old_id = wid
            new_id = next_warrior_id()
            wd["warrior_id"] = new_id
            seen_this_upload.add(new_id)
            wid_index[new_id] = (tid, name_lower)
            yield (wd.get("name") or "?"), old_id, new_id
        else:
            seen_this_upload.add(wid)
            wid_index.setdefault(wid, (tid, name_lower))


def restore_archived_ids(team_dict: dict, team_id) -> int:
    """Fill in a missing warrior_id on ARCHIVED warriors in `team_dict` by
    name-matching the previously-persisted save for team_id (its active and
    archived warriors). Only fills ids that are None/absent; never overwrites an
    existing id. Mutates `team_dict` in place; returns the count restored."""
    if not isinstance(team_dict, dict):
        return 0
    archived = team_dict.get("archived_warriors")
    if not archived:
        return 0
    try:
        prev = load_team(team_id)
    except Exception:
        return 0
    name_to_id = {}
    for w in (prev.warriors or []):
        if w is not None and w.name and w.warrior_id is not None:
            name_to_id.setdefault(w.name.lower(), w.warrior_id)
    for wd in (getattr(prev, "archived_warriors", None) or []):
        if isinstance(wd, dict) and wd.get("name") and wd.get("warrior_id") is not None:
            name_to_id.setdefault(wd["name"].lower(), wd["warrior_id"])
    restored = 0
    for wd in archived:
        if isinstance(wd, dict) and wd.get("warrior_id") is None:
            wid = name_to_id.get((wd.get("name") or "").lower())
            if wid is not None:
                wd["warrior_id"] = wid
                restored += 1
    return restored


def load_all_teams() -> List[Team]:
    """
    Load every team save file found in the teams directory.
    Skips and warns on any corrupted files.
    Returns a list of Team objects, sorted by team_id.
    """
    _ensure_dirs()
    teams = []
    for filename in sorted(os.listdir(TEAMS_DIR)):
        # Only real team saves (team_<digits>.json); skips team_0069.backup.json etc.
        if not re.fullmatch(r"team_\d+\.json", filename):
            continue
        try:
            id_str  = filename.replace("team_", "").replace(".json", "")
            team_id = int(id_str)
            team    = load_team(team_id)
            teams.append(team) # This will raise ValueError if tampered
        except (ValueError, FileNotFoundError) as e:
            print(f"  WARNING: Skipping '{filename}': {e}")
    return teams


def delete_team(team_id: int) -> bool:
    """
    Delete a team's save file.
    Returns True if deleted, False if the file didn't exist.
    """
    filepath = _team_filepath(team_id)
    checksum_filepath = filepath.replace('.json', '.checksum')
    if os.path.exists(filepath):
        make_file_writable(filepath)
        os.remove(filepath)
        if os.path.exists(checksum_filepath):
            make_file_writable(checksum_filepath)
            os.remove(checksum_filepath)
        return True
    return False


def list_saved_teams() -> List[dict]:
    """
    Return a lightweight summary list of all saved teams without loading
    full warrior data. Useful for a quick team-picker menu.

    Returns list of {"team_id", "team_name", "manager_name"} dicts.
    """
    _ensure_dirs()
    summaries = []
    for filename in sorted(os.listdir(TEAMS_DIR)):
        if not filename.startswith("team_") or not filename.endswith(".json"):
            continue
        filepath = os.path.join(TEAMS_DIR, filename)
        try: # Use load_json_protected to ensure integrity check
            data = load_json_protected(filepath)
            summaries.append({
                "team_id"     : data.get("team_id",      0),
                "team_name"   : data.get("team_name",    "Unknown"),
                "manager_name": data.get("manager_name", "Unknown"),
            })
        except Exception:
            pass   # Silently skip malformed summaries
    return summaries


# ---------------------------------------------------------------------------
# FIGHT LOG SAVE
# ---------------------------------------------------------------------------

def save_fight_log(narrative_text: str, team_a_name: str, team_b_name: str) -> tuple:
    """
    Save a fight narrative to a timestamped text file.
    Returns (filepath, fight_id).

    Fight logs are plain text - the full blow-by-blow narrative exactly
    as printed to the console.
    """
    _ensure_dirs()
    fight_id = next_fight_id()
    safe_a   = team_a_name.replace(" ", "_")[:20]
    safe_b   = team_b_name.replace(" ", "_")[:20]
    filename = f"fight_{fight_id:04d}_{safe_a}_vs_{safe_b}.txt"
    filepath = os.path.join(FIGHTS_DIR, filename)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Fight #{fight_id} (Turn {current_turn()})\n")
            f.write(f"{team_a_name}  vs  {team_b_name}\n")
            f.write("=" * 76 + "\n\n")
            f.write(narrative_text)
        make_file_readonly(filepath) # Make text files read-only
        return filepath, fight_id

    except IOError as e:
        raise IOError(f"Could not save fight log: {e}")


def load_fight_log(fight_id: int) -> str:
    """
    Load and return the text of a fight log by ID.
    Raises FileNotFoundError if not found.
    """
    _ensure_dirs()
    for filename in os.listdir(FIGHTS_DIR):
        if filename.startswith(f"fight_{fight_id:04d}_"):
            filepath = os.path.join(FIGHTS_DIR, filename) # This is a text file, not JSON
            with open(filepath, "r", encoding="utf-8") as f: # No checksum for text files
                return f.read()
    raise FileNotFoundError(f"No fight log found with ID {fight_id}.")


def archive_warrior_history(team_name: str, warrior):
    """
    Export the entire career narrative of a warrior to a single legacy file.
    Called at death time so all fight logs are still available on disk.
    """
    _ensure_dirs()
    safe_team = str(team_name).replace(" ", "_")
    safe_name = str(warrior.name).replace(" ", "_")
    filename = f"{safe_team}_{safe_name}_legacy.txt"
    filepath = os.path.join(GRAVEYARD_DIR, filename)
    
    try:
        if os.path.exists(filepath):
            make_file_writable(filepath)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("=" * 76 + "\n")
            f.write(f" GLADIATOR LEGACY: {warrior.name.upper()}\n")
            f.write(f" TEAM:             {team_name.upper()}\n")
            f.write(f" FINAL RECORD:     {getattr(warrior, 'record_str', '0-0-0')}\n")
            f.write("=" * 76 + "\n\n")
            
            history = getattr(warrior, "fight_history", [])
            if not history:
                f.write("No recorded fight history found.\n")
                return filepath
                
            for entry in history:
                turn = entry.get("turn", "?")
                opp  = entry.get("opponent_name", "Unknown")
                res  = str(entry.get("result", "loss")).upper()
                fid  = entry.get("fight_id")
                
                f.write(f"--- TURN {turn} vs {opp} [{res}] ---\n")
                if fid:
                    try:
                        narrative = load_fight_log(fid)
                        # Remove the redundant file header from the individual log
                        f.write(narrative.split("=" * 76 + "\n\n")[-1])
                    except Exception:
                        f.write("[Narrative log file not found or inaccessible]\n")
                f.write("\n\n")
        make_file_readonly(filepath) # Protect the archived text file
        return filepath
    except Exception as e:
        print(f"  WARNING: Could not create legacy file for {warrior.name}: {e}")
        return ""


def list_fight_logs() -> List[dict]:
    """
    Return a summary list of all saved fight logs.
    Returns list of {"fight_id", "filename"} dicts, sorted by ID.
    """
    _ensure_dirs()
    logs = []
    for filename in sorted(os.listdir(FIGHTS_DIR)):
        if not filename.startswith("fight_") or not filename.endswith(".txt"):
            continue
        try:
            parts    = filename.split("_")
            fight_id = int(parts[1])
            logs.append({"fight_id": fight_id, "filename": filename})
        except (IndexError, ValueError):
            pass
    return sorted(logs, key=lambda x: x["fight_id"])


# ---------------------------------------------------------------------------
# STATIC ARCHIVE GENERATOR (The "Better System")
# ---------------------------------------------------------------------------

def generate_static_dashboard():
    """
    Generates a full set of HTML files in /arena_records/ that can be opened
    directly in a browser without a server.
    """
    os.makedirs(RECORDS_DIR, exist_ok=True)
    teams = load_all_teams()
    state = load_game_state()
    
    # 1. Generate Master Index (Dashboard)
    index_path = os.path.join(RECORDS_DIR, "index.html")
    
    team_rows = ""
    for t in teams:
        w_list = ", ".join([w.name for w in t.active_warriors])
        team_rows += f"""
        <tr>
            <td><a href="team_{t.team_id}.html"><b>{t.team_name}</b></a></td>
            <td>{t.manager_name}</td>
            <td>{t.record_str}</td>
            <td>{w_list}</td>
        </tr>"""

    html_content = f"""
    <html>
    <head>
        <title>BLOODSPIRE Arena Records</title>
        <style>
            body {{ background: #111; color: #ccc; font-family: sans-serif; padding: 20px; }}
            h1 {{ color: #c80; border-bottom: 2px solid #444; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th {{ background: #222; text-align: left; padding: 10px; color: #888; }}
            td {{ padding: 10px; border-bottom: 1px solid #333; }}
            a {{ color: #4af; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .stats {{ color: #aaa; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <h1>⚔ BLOODSPIRE ARENA RECORDS</h1>
        <p class="stats">Current Turn: {state['turn_number']} | Teams: {len(teams)}</p>
        <table>
            <tr><th>Team Name</th><th>Manager</th><th>Record (W-L-K)</th><th>Active Roster</th></tr>
            {team_rows}
        </table>
        <br>
        <h3>Latest Newsletters</h3>
        <ul>
            {" ".join([f'<li><a href="../saves/newsletters/turn_{n:04d}.txt">Turn {n} Newsletter (Text)</a></li>' for n in list_newsletters()[-5:]])}
        </ul>
    </body>
    </html>
    """
    
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    make_file_readonly(index_path)
    # 2. Generate Individual Team Pages
    for t in teams:
        _generate_team_page(t)

    return index_path

def _generate_team_page(team: Team):
    """Internal helper to create a detailed HTML page for a specific team."""
    path = os.path.join(RECORDS_DIR, f"team_{team.team_id}.html")
    
    warrior_blocks = ""
    for w in team.active_warriors:
        warrior_blocks += f"""
        <div style="background:#1a1a1a; padding:15px; margin-bottom:20px; border-left:4px solid #c80;">
            <h2 style="margin-top:0;">{w.name} <small style="color:#666">({w.race.name} {w.gender})</small></h2>
            <p><b>Record:</b> {w.record_str} | <b>HP:</b> {w.max_hp} | <b>Popularity:</b> {w.popularity}</p>
            <pre style="color:#999; background:#000; padding:10px;">{w.stat_block()}</pre>
        </div>"""

    html = f"""
    <html>
    <head>
        <title>{team.team_name} - Bloodspire</title>
        <style>
            body {{ background: #111; color: #ccc; font-family: sans-serif; padding: 20px; }}
            h1 {{ color: #c80; }}
            .back {{ margin-bottom: 20px; display: block; color: #4af; }}
        </style>
    </head>
    <body>
        <a href="index.html" class="back">← Back to Dashboard</a>
        <h1>TEAM: {team.team_name}</h1>
        <p>Manager: {team.manager_name} | ID: {team.team_id}</p>
        <hr style="border:1px solid #333">
        {warrior_blocks}
    </body>
    </html>
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    make_file_readonly(path)

# ---------------------------------------------------------------------------
# ARCHIVE & EXPORT
# ---------------------------------------------------------------------------

def export_team_text(team: Team) -> str:
    """Save a human-readable .txt summary of the team to the exports folder."""
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    filename = f"team_{team.team_id:04d}_{team.team_name.replace(' ', '_')}.txt"
    filepath = os.path.join(EXPORTS_DIR, filename)
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(team.full_roster())
        return filepath
    except IOError as e: # This will be replaced by save_json_protected
        raise IOError(f"Could not export team text: {e}")


def create_backup_zip() -> bytes:
    """
    Zip up all local saves, fights, and newsletters into a single archive.
    Returns the ZIP data as bytes.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Team JSONs
        if os.path.exists(TEAMS_DIR):
            for f in os.listdir(TEAMS_DIR):
                if f.endswith(".json") or f.endswith(".checksum"):
                    # Temporarily make writable to read, then set back to read-only
                    fpath = os.path.join(TEAMS_DIR, f)
                    make_file_writable(fpath)
                    zf.write(fpath, os.path.join("teams", f))
                    make_file_readonly(fpath)
        # 2. Fight Narratives
        if os.path.exists(FIGHTS_DIR):
            for f in os.listdir(FIGHTS_DIR):
                if f.endswith(".txt"):
                    fpath = os.path.join(FIGHTS_DIR, f)
                    make_file_writable(fpath)
                    zf.write(fpath, os.path.join("fights", f))
                    make_file_readonly(fpath)
        # 3. Newsletters
        if os.path.exists(NEWSLETTERS_DIR):
            for f in os.listdir(NEWSLETTERS_DIR):
                if f.endswith(".txt"):
                    fpath = os.path.join(NEWSLETTERS_DIR, f) # No checksum for text files
                    make_file_writable(fpath)
                    zf.write(fpath, os.path.join("newsletters", f))
                    make_file_readonly(fpath)
        # 4. Critical State Files
        for f in ["game_state.json", "scouting.json", "monster_team.json", "champion.json"]:
            fpath = os.path.join(SAVES_DIR, f)
            if os.path.exists(fpath):
                zf.write(fpath, f)
            
    return buf.getvalue()

 
# ---------------------------------------------------------------------------
# UTILITY: QUICK SAVE & LOAD ALL
# ---------------------------------------------------------------------------

def save_all_teams(teams: List[Team]):
    """Save a list of teams. Prints a status line for each."""
    for team in teams:
        path = save_team(team)
        print(f"  Saved: {team.team_name} → {os.path.basename(path)}")


def backup_all_saves(backup_suffix: str = "bak") -> int:
    """
    Copy every team JSON to a .bak version in the same folder.
    Returns the number of files backed up.

    Useful before running a turn in case something goes wrong.
    """
    import shutil
    count = 0
    for filename in os.listdir(TEAMS_DIR): # This will be replaced by save_json_protected
        if filename.endswith(".json"): # This will be replaced by save_json_protected
            src = os.path.join(TEAMS_DIR, filename) # This will be replaced by save_json_protected
            dst = src.replace(".json", f".{backup_suffix}") # This will be replaced by save_json_protected
            make_file_writable(src) # Ensure file is writable before copying
            shutil.copy2(src, dst)
            make_file_readonly(src) # Set back to read-only
            count += 1
    return count


# ---------------------------------------------------------------------------
# DISPLAY HELPERS
# ---------------------------------------------------------------------------

def print_save_status():
    """Print a summary of what's currently saved to disk."""
    teams    = list_saved_teams()
    fights   = list_fight_logs()
    state    = load_game_state()

    print("\n  === SAVE STATUS ===")
    print(f"  Turn:        {state['turn_number']}")
    print(f"  Teams saved: {len(teams)}")
    for t in teams:
        print(f"    [{t['team_id']:04d}] {t['team_name']}  (Manager: {t['manager_name']})")
    print(f"  Fight logs:  {len(fights)}")
    if fights:
        last = fights[-1]
        print(f"    Latest: {last['filename']}")
    print()


# ---------------------------------------------------------------------------
# TURN LOGS
# ---------------------------------------------------------------------------

def _summary_rows(card) -> str:
    """Build HTML table rows for the fight summary - kept outside f-strings
    so backslashes in attribute values are safe on Python < 3.12."""
    rows = []
    for i, bout in enumerate(card, 1):
        pw_won = (bout.result and bout.result.winner
                  and bout.result.winner.name == bout.player_warrior.name)
        color   = "#0a0" if pw_won else "#c00"
        result  = "WIN"  if pw_won else "LOSS"
        dur     = str(bout.result.minutes_elapsed) + "m" if bout.result else "?m"
        rows.append(
            f"<tr>"
            f"<td>{i}</td>"
            f"<td>{bout.player_warrior.name}</td>"
            f"<td>{bout.opponent.name} ({bout.opponent_manager})</td>"
            f"<td>{bout.fight_type}</td>"
            f"<td style=\"color:{color}\">{result}</td>"
            f"<td>{dur}</td>"
            f"</tr>"
        )
    return "".join(rows)


def write_turn_logs(turn_num: int, card, player_team_name: str):
    """
    Write both a detailed HTML log and a plain-text matchmaking log for a turn.
    Files go to saves/logs/turn_NNN/ and overwrite previous content for that turn.

    card: List[ScheduledFight] with .result, .fight_type, .player_warrior,
          .opponent, .opponent_team, .opponent_manager populated.
    """
    import datetime
    _ensure_dirs()
    turn_log_dir = os.path.join(LOGS_DIR, f"turn_{turn_num:04d}")
    os.makedirs(turn_log_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Matchmaking log (plain text) ──────────────────────────────────────
    mm_lines = [
        f"BLOODSPIRE - MATCHMAKING LOG",
        f"Turn {turn_num}  |  Team: {player_team_name}  |  {ts}",
        "=" * 72,
        f"{'#':<4} {'Fighter':<20} {'Exp':>5} {'vs':<4} {'Opponent':<20} {'Exp':>5} {'Type':<16} {'Result':<8} {'Mins':>4}",
        "-" * 72,
    ]
    for i, bout in enumerate(card, 1):
        pw  = bout.player_warrior
        ow  = bout.opponent
        r   = bout.result
        res = "WIN" if (r and r.winner and r.winner.name == pw.name) else "LOSS"
        mm_lines.append(
            f"{i:<4} {pw.name[:19]:<20} {pw.total_fights:>5}  vs  "
            f"{ow.name[:19]:<20} {ow.total_fights:>5} {bout.fight_type:<16} {res:<8} {r.minutes_elapsed if r else '?':>4}"
        )
    mm_lines += ["", f"Total bouts: {len(card)}", ""]
    mm_path = os.path.join(turn_log_dir, "matchmaking.txt")
    with open(mm_path, "w", encoding="utf-8") as f:
        f.write("\n".join(mm_lines))

    # ── Detailed fight log (HTML) ─────────────────────────────────────────
    def _result_color(pw, r):
        if not r or not r.winner: return "#888"
        return "#0a0" if r.winner.name == pw.name else "#c00"

    def _narrative_html(text):
        lines = text.split("\n")
        out = []
        for ln in lines:
            ln_esc = ln.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            if ln.startswith("===") or ln.startswith("---"):
                out.append(f"<hr style='border-color:#444;margin:4px 0'>")
            elif ln.startswith("***") and ln.endswith("***"):
                out.append(f"<div style='color:#f80;font-weight:bold;margin:4px 0'>{ln_esc}</div>")
            elif "MINUTE" in ln and ln.strip().startswith("["):
                out.append(f"<div style='color:#a80;font-weight:bold;margin-top:6px'>{ln_esc}</div>")
            elif "stone" in ln.lower():
                out.append(f"<div style='color:#c60'>{ln_esc}</div>")
            elif "SLAIN" in ln or "collapses" in ln.lower() or "falls" in ln.lower():
                out.append(f"<div style='color:#c00;font-weight:bold'>{ln_esc}</div>")
            elif "wins" in ln.lower() and ("judge" in ln.lower() or "victory" in ln.lower()):
                out.append(f"<div style='color:#0a0;font-weight:bold'>{ln_esc}</div>")
            elif "trained" in ln.lower() or "observed" in ln.lower():
                out.append(f"<div style='color:#06a'>{ln_esc}</div>")
            elif ln.startswith("  HP") or "HP:" in ln or "damage" in ln.lower():
                out.append(f"<div style='color:#999;font-size:11px'>{ln_esc}</div>")
            elif ln.strip() == "":
                out.append("<br>")
            else:
                out.append(f"<div>{ln_esc}</div>")
        return "\n".join(out)

    fight_cards_html = ""
    for i, bout in enumerate(card, 1):
        pw  = bout.player_warrior
        ow  = bout.opponent
        r   = bout.result
        rc  = _result_color(pw, r)
        res = "WIN" if (r and r.winner and r.winner.name == pw.name) else "LOSS"
        died_note = " <span style=\'color:#c00\'>(SLAIN)</span>" if (r and r.loser_died and r.loser.name == pw.name) else ""
        kill_note = " <span style=\'color:#0a0\'>(KILLED)</span>" if (r and r.loser_died and r.winner and r.winner.name == pw.name) else ""
        narr = _narrative_html(r.narrative) if r else "(no narrative)"
        fight_cards_html += f"""
<div style="background:#1a1a1a;border:1px solid #444;margin:12px 0;border-radius:4px;overflow:hidden;">
  <div style="background:#2a2a2a;padding:8px 14px;display:flex;align-items:center;gap:16px;border-bottom:1px solid #444;">
    <span style="color:#888;font-size:13px;">#{i}</span>
    <span style="font-weight:bold;font-size:14px;">{pw.name}</span>
    <span style="color:#666;">{player_team_name} ({pw.total_fights} fights)</span>
    <span style="color:#555;margin:0 8px;">vs</span>
    <span style="font-weight:bold;font-size:14px;">{ow.name}</span>
    <span style="color:#666;">{bout.opponent_manager} ({ow.total_fights} fights)</span>
    <span style="background:{rc};color:#fff;padding:2px 10px;border-radius:3px;font-size:12px;font-weight:bold;margin-left:auto;">{res}{died_note}{kill_note}</span>
    <span style="color:#888;font-size:12px;">{bout.fight_type}</span>
    <span style="color:#666;font-size:12px;">{r.minutes_elapsed if r else "?"}m</span>
  </div>
  <div style="padding:10px 14px;font-family:monospace;font-size:12px;line-height:1.5;color:#ccc;max-height:600px;overflow-y:auto;">
    {narr}
  </div>
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>BLOODSPIRE - Turn {turn_num} Fight Log</title>
<style>
  body{{background:#111;color:#ccc;font-family:Tahoma,Arial,sans-serif;font-size:13px;margin:0;padding:16px}}
  h1{{color:#c80;margin:0 0 4px}}
  .meta{{color:#666;font-size:11px;margin-bottom:16px}}
  .summary{{background:#1e1e1e;border:1px solid #333;padding:10px 14px;border-radius:4px;margin-bottom:16px}}
  .summary table{{border-collapse:collapse;width:100%}}
  .summary td{{padding:2px 12px;font-size:12px}}
  .summary th{{padding:3px 12px;color:#888;text-align:left;border-bottom:1px solid #333}}
</style>
</head><body>
<h1>⚔ BLOODSPIRE - Fight Log</h1>
<div class="meta">Turn {turn_num} | {player_team_name} | Generated {ts}</div>
<div class="summary">
  <table>
    <tr><th>#</th><th>Fighter</th><th>Opponent</th><th>Type</th><th>Result</th><th>Duration</th></tr>
    {_summary_rows(card)}
  </table>
</div>
{fight_cards_html}
</body></html>"""

    html_path = os.path.join(turn_log_dir, "fights.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Turn logs written: {turn_log_dir}/")
    return mm_path, html_path


# ---------------------------------------------------------------------------
# ARENA RESET
# ---------------------------------------------------------------------------

def reset_arena_state():
    """
    Wipe arena state while keeping accounts and team rosters.
    Clears:
      - Fight history (fight_id references, fight_history on warriors)
      - Fight log files (saves/fights/)
      - Turn logs (saves/logs/)
      - Warriors' fight records (wins/losses/kills/total_fights)
      - Warriors' injuries, popularity, streak, turns_active
      - Turn counter reset to 0
      - Next fight ID reset to 1
    Keeps:
      - Accounts and passwords
      - Teams and their warrior rosters (names, stats, gear, strategies, trains)
      - Team names, manager names
    """
    import shutil
    _ensure_dirs()

    # 1. Wipe fight logs
    if os.path.exists(FIGHTS_DIR):
        shutil.rmtree(FIGHTS_DIR)
    os.makedirs(FIGHTS_DIR, exist_ok=True)

    # 2. Wipe turn logs
    if os.path.exists(LOGS_DIR):
        shutil.rmtree(LOGS_DIR)
    os.makedirs(LOGS_DIR, exist_ok=True)

    # 3. Reset turn counter and fight ID in game state
    state = load_game_state()
    state["turn_number"]   = 0
    state["next_fight_id"] = 1
    save_game_state(state)

    # 4. Wipe records on all team warriors
    if os.path.exists(TEAMS_DIR):
        for fname in os.listdir(TEAMS_DIR):
            if not fname.endswith(".json"): continue
            fpath = os.path.join(TEAMS_DIR, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    team_data = json.load(f)
                for w in team_data.get("warriors", []):
                    if not w: continue
                    w["wins"]         = 0
                    w["losses"]       = 0
                    w["kills"]        = 0
                    w["total_fights"] = 0
                    w["fight_history"]= []
                    w["injuries"]     = {}
                    w["popularity"]   = 0
                    w["streak"]       = 0
                    w["turns_active"] = 0
                    w["attribute_gains"] = {k:0 for k in ["strength","dexterity","constitution","intelligence","presence"]}
                    w["is_dead"]      = False
                    w["killed_by"]    = ""
                # Also wipe team-level state
                team_data["fallen_warriors"]    = []
                team_data["blood_challenges"]   = []
                team_data["archived_warriors"]  = []
                team_data["pending_replacements"] = {}
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump(team_data, f, indent=2)
            except Exception as e:
                print(f"  WARNING: Could not reset {fname}: {e}")

    print("  Arena state reset complete. Accounts and team rosters preserved.")
    return {"success": True, "message": "Arena state reset. Turn counter at 0. All fight records cleared."}


def reset_arena_complete():
    """
    Full wipe for a fresh arena start. Removes everything under saves/ that
    represents player- or arena-state: accounts, teams, scouting, sessions,
    fight logs, turn logs, newsletters, archives, and champion/monster state.
    After this runs, every user must re-register and rebuild their teams.

    Keeps:
      - (None)
    """
    import shutil
    _ensure_dirs()

    def _rm_dir(d):
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)

    def _rm_file(p):
        try:
            if os.path.exists(p):
                make_file_writable(p)
                os.remove(p)
        except OSError as e:
            print(f"  WARNING: Could not delete {p}: {e}")

    _rm_dir(TEAMS_DIR)
    _rm_dir(FIGHTS_DIR)
    _rm_dir(LOGS_DIR)
    _rm_dir(NEWSLETTERS_DIR)
    _rm_dir(TEAM_ARCHIVES_DIR)
    _rm_dir(GRAVEYARD_DIR)

    _rm_file(ACCOUNTS_FILE)
    _rm_file(SCOUTING_FILE)
    _rm_file(SESSION_FILE)
    _rm_file(CHAMPION_FILE)
    _rm_file(CHAMPION_HISTORY_FILE)
    _rm_file(MONSTER_TEAM_FILE)
    _rm_file(os.path.join(SAVES_DIR, "league_settings.json"))
    _rm_file(os.path.join(SAVES_DIR, "rivals.json"))
    _rm_file(os.path.join(SAVES_DIR, "league_client.json"))
    _rm_file(os.path.join(SAVES_DIR, "league", "managers.json"))
    _rm_file(os.path.join(SAVES_DIR, "league", "ai_teams.json"))
    _rm_file(os.path.join(SAVES_DIR, "league", "config.json"))
    _rm_file(os.path.join(SAVES_DIR, "league", "standings.json"))
    _rm_file(os.path.join(SAVES_DIR, "league", "scout_narratives.json"))

    state = load_game_state()
    state["turn_number"]   = 0
    state["next_fight_id"] = 1
    save_game_state(state)

    print("  Full arena reset complete. Accounts, teams, and all arena state cleared.")
    return {"success": True,
            "message": "Arena fully reset. All accounts, teams, and records cleared. Turn counter at 0."}


def reset_arena_season():
    """
    Season reset - clear fight records, injuries, and fallen warriors, but keep
    each warrior's identity, attributes, gear, strategies, trains, and skills.
    Matches the league-reset modal's promise: "warriors, stats, gear, strategies"
    are kept; "wins, losses, kills, fight history, injuries, fallen warriors" are cleared.
    Forces league re-registration by clearing league_settings.json.
    """
    import shutil
    from warrior import PermanentInjuries
    _ensure_dirs()

    def _rm_dir(d):
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)

    def _rm_file(p):
        try:
            if os.path.exists(p):
                make_file_writable(p)
                os.remove(p)
        except OSError as e:
            print(f"  WARNING: Could not delete {p}: {e}")

    _rm_dir(FIGHTS_DIR)
    _rm_dir(LOGS_DIR)
    _rm_dir(NEWSLETTERS_DIR)
    _rm_dir(TEAM_ARCHIVES_DIR)

    _rm_file(SCOUTING_FILE)
    _rm_file(SESSION_FILE)
    _rm_file(CHAMPION_FILE)
    _rm_file(CHAMPION_HISTORY_FILE)
    _rm_file(MONSTER_TEAM_FILE)
    _rm_file(os.path.join(SAVES_DIR, "rivals.json"))
    _rm_file(os.path.join(SAVES_DIR, "league_client.json"))
    _rm_file(os.path.join(SAVES_DIR, "league_settings.json"))

    state = load_game_state()
    state["turn_number"]   = 0
    state["next_fight_id"] = 1
    save_game_state(state)

    teams = load_all_teams()
    for team in teams:
        team.fallen_warriors     = []
        team.archived_warriors   = []
        team.pending_replacements = {}
        team.turn_history        = []
        team.challenges          = {}
        team.blood_challenges    = []
        for w in team.warriors:
            if w is None:
                continue
            w.wins               = 0
            w.losses             = 0
            w.kills              = 0
            w.monster_kills      = 0
            w.total_fights       = 0
            w.fight_history      = []
            w.injuries           = PermanentInjuries()
            w.is_dead            = False
            w.killed_by          = ""
            w.is_retired         = False
            w.ascended_to_monster = False
            w.popularity         = 0
            w.recognition        = 0
            w.streak             = 0
            w.turns_active       = 0
            w.want_monster_fight = False
            w.want_retire        = False
        save_team(team)

    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for acc in data.get("accounts", []):
                acc["run_next_turn"] = {}
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except (IOError, json.JSONDecodeError) as e:
            print(f"  WARNING: Could not update accounts.json: {e}")

    print("  Season reset complete. Warriors, stats, gear, and strategies preserved.")
    return {"success": True,
            "message": "New season started. Fight records, injuries, and fallen warriors cleared. "
                       "Warriors, stats, gear, and strategies preserved. Re-register with the league to upload."}


def create_fight_archives():
    """
    Create JSON archive files for all elite/soul spire warriors before reset.
    Scans saves/teams/, saves/elite/teams/, and saves/veteran/teams/
    Organizes archives by manager ID in saves/fight_archives/
    Returns statistics about what was archived.
    """
    import shutil
    from datetime import datetime

    _ensure_dirs()
    archive_base = os.path.join(SAVES_DIR, "fight_archives")
    os.makedirs(archive_base, exist_ok=True)

    # Load teams from all three directories, tracking which ones come from elite/veteran dirs
    teams_with_source = []  # List of (team, source_arena) tuples

    # Load from saves/teams/
    for team in load_all_teams():
        teams_with_source.append((team, "normal"))

    # Load from elite arena directory
    elite_dir = os.path.join(SAVES_DIR, "elite", "teams")
    if os.path.isdir(elite_dir):
        for filename in sorted(os.listdir(elite_dir)):
            if filename.startswith("team_") and filename.endswith(".json"):
                try:
                    path = os.path.join(elite_dir, filename)
                    data = load_json_protected(path)
                    team = Team.from_dict(data)
                    teams_with_source.append((team, "elite"))
                except Exception as e:
                    print(f"  WARNING: Could not load elite team {filename}: {e}")

    # Load from veteran arena directory
    veteran_dir = os.path.join(SAVES_DIR, "veteran", "teams")
    if os.path.isdir(veteran_dir):
        for filename in sorted(os.listdir(veteran_dir)):
            if filename.startswith("team_") and filename.endswith(".json"):
                try:
                    path = os.path.join(veteran_dir, filename)
                    data = load_json_protected(path)
                    team = Team.from_dict(data)
                    teams_with_source.append((team, "veteran"))
                except Exception as e:
                    print(f"  WARNING: Could not load veteran team {filename}: {e}")

    archives = {}  # {(manager_name, team_id): {team_name, warriors: [...], total_fights: N}}
    seen_warrior_keys = set()  # Track (team_id, warrior_name) to avoid duplicate warriors

    debug_info = {}  # Track skipped warriors for debugging

    for team, source_arena in teams_with_source:
        # Process both active and archived warriors
        all_warriors = (team.warriors or []) + (team.archived_warriors or [])
        team_warriors = []
        team_fights = 0

        for warrior in all_warriors:
            if warrior is None:
                continue

            # Handle both Warrior objects and dicts (archived warriors are dicts)
            if isinstance(warrior, dict):
                warrior_name = warrior.get('name')
                current_arena = warrior.get('current_arena')
            else:
                warrior_name = warrior.name if hasattr(warrior, 'name') else None
                current_arena = getattr(warrior, "current_arena", None)

            if not warrior_name:
                continue

            # Include warrior if:
            # 1. It's in a team from elite/veteran directory (regardless of current_arena field)
            # 2. OR it has current_arena field set to elite/veteran (in normal directory)
            if source_arena in ("elite", "veteran"):
                # Any warrior in elite/veteran directory gets included
                warrior_arena = source_arena
            elif current_arena in ("elite", "veteran"):
                # Warrior in normal directory but marked as elite/veteran
                warrior_arena = current_arena
            else:
                # Skip normal arena warriors
                continue

            # Skip if we've already archived this warrior (avoid duplicates across multiple locations)
            warrior_key = (team.team_id, warrior_name)
            if warrior_key in seen_warrior_keys:
                continue
            seen_warrior_keys.add(warrior_key)

            warrior_dict = warrior.to_dict() if hasattr(warrior, "to_dict") else warrior
            if isinstance(warrior_dict, dict):
                # Get fight history
                fights = warrior_dict.get("fight_history", [])

                warrior_data = {
                    "name": warrior_dict.get("name", "Unknown"),
                    "race": warrior_dict.get("race", "Unknown"),
                    "current_arena": warrior_arena,
                    "final_record": f"{warrior_dict.get('wins', 0)}-{warrior_dict.get('losses', 0)}-{warrior_dict.get('kills', 0)}",
                    "final_stats": {
                        "strength": warrior_dict.get("strength", 0),
                        "dexterity": warrior_dict.get("dexterity", 0),
                        "constitution": warrior_dict.get("constitution", 0),
                        "intelligence": warrior_dict.get("intelligence", 0),
                        "presence": warrior_dict.get("presence", 0),
                        "size": warrior_dict.get("size", 0),
                    },
                    "fights": fights
                }

                team_warriors.append(warrior_data)
                team_fights += len(fights)

        # Only create archive if this team has elite/veteran warriors
        if team_warriors:
            key = (team.manager_name, team.team_id)
            if key in archives:
                # Accumulate warriors from multiple source scans (normal + elite + veteran)
                # so we don't overwrite warriors already found via a different path.
                archives[key]["warriors"].extend(team_warriors)
                archives[key]["total_fights"] += team_fights
            else:
                archives[key] = {
                    "team_name": team.team_name,
                    "warriors": team_warriors,
                    "total_fights": team_fights
                }

    # Create archive files, one per team
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_files = []
    total_warriors = 0
    total_fights = 0

    for (manager_name, team_id), data in archives.items():
        manager_dir = os.path.join(archive_base, manager_name.replace(" ", "_"))
        os.makedirs(manager_dir, exist_ok=True)

        archive_file = os.path.join(manager_dir, f"team_{team_id:04d}_archive_{timestamp}.json")

        archive_data = {
            "export_metadata": {
                "created_at": datetime.now().isoformat(),
                "export_version": "1.0",
                "manager_name": manager_name,
                "team_id": team_id,
                "team_name": data["team_name"],
            },
            "warriors": data["warriors"]
        }

        try:
            save_json_protected(archive_file, archive_data)
            archive_files.append(archive_file)
            total_warriors += len(data["warriors"])
            total_fights += data["total_fights"]
            print(f"  Archived {len(data['warriors'])} warriors from {data['team_name']} (team {team_id})")
        except Exception as e:
            print(f"  WARNING: Could not create archive for team {team_id}: {e}")

    # Create summary file
    summary_file = os.path.join(archive_base, "EXPORT_SUMMARY.json")
    summary_data = {
        "export_date": datetime.now().isoformat(),
        "total_warriors": total_warriors,
        "total_fights": total_fights,
        "teams_archived": len(archives),
        "files_created": len(archive_files)
    }

    try:
        save_json_protected(summary_file, summary_data)
    except Exception as e:
        print(f"  WARNING: Could not create summary file: {e}")

    print(f"  Fight archives complete. {total_warriors} warriors, {total_fights} fights preserved.")

    return {
        "success": True,
        "total_warriors": total_warriors,
        "total_fights": total_fights,
        "teams_archived": len(archives),
        "files_created": len(archive_files),
        "archive_directory": archive_base
    }


def reset_arena_selective():
    """
    Selective arena reset for end-of-playtest:
    - Delete ALL normal arena teams (saves/teams/)
    - Keep Elite Spire teams (saves/elite/teams/)
    - Keep Soul Spire teams (saves/veteran/teams/)
    - Reset turn counter to 1
    - Preserve manager accounts

    Returns statistics about what was deleted/preserved.
    """
    import shutil

    _ensure_dirs()

    # STEP 1: Create archives FIRST
    print("  Step 1: Creating fight archives...")
    archive_result = create_fight_archives()

    # STEP 2: Count and delete normal arena teams
    print("  Step 2: Deleting normal arena teams...")
    teams = load_all_teams()

    normal_teams_deleted = 0
    normal_warriors_deleted = 0
    elite_teams_preserved = 0
    elite_warriors_preserved = 0
    veteran_teams_preserved = 0
    veteran_warriors_preserved = 0

    for team in teams:
        # Count warriors before deletion
        normal_warrior_count = sum(1 for w in (team.warriors or []) if w is not None)
        if delete_team(team.team_id):
            normal_teams_deleted += 1
            normal_warriors_deleted += normal_warrior_count

    # Count elite teams (they're in saves/elite/teams/)
    elite_dir = os.path.join(SAVES_DIR, "elite", "teams")
    if os.path.isdir(elite_dir):
        for filename in os.listdir(elite_dir):
            if filename.startswith("team_") and filename.endswith(".json"):
                try:
                    path = os.path.join(elite_dir, filename)
                    data = load_json_protected(path)
                    elite_teams_preserved += 1
                    elite_warriors_preserved += sum(1 for w in (data.get("warriors", []) or []) if w is not None)
                except Exception:
                    pass

    # Count veteran teams (they're in saves/veteran/teams/)
    veteran_dir = os.path.join(SAVES_DIR, "veteran", "teams")
    if os.path.isdir(veteran_dir):
        for filename in os.listdir(veteran_dir):
            if filename.startswith("team_") and filename.endswith(".json"):
                try:
                    path = os.path.join(veteran_dir, filename)
                    data = load_json_protected(path)
                    veteran_teams_preserved += 1
                    veteran_warriors_preserved += sum(1 for w in (data.get("warriors", []) or []) if w is not None)
                except Exception:
                    pass

    # STEP 3: Delete fight logs and related data
    print("  Step 3: Deleting fight logs and related data...")

    def _rm_dir(d):
        if os.path.exists(d):
            try:
                shutil.rmtree(d, ignore_errors=True)
                os.makedirs(d, exist_ok=True)
            except Exception as e:
                print(f"    WARNING: Could not delete {d}: {e}")

    def _rm_file(p):
        try:
            if os.path.exists(p):
                make_file_writable(p)
                os.remove(p)
        except OSError as e:
            print(f"    WARNING: Could not delete {p}: {e}")

    _rm_dir(FIGHTS_DIR)
    _rm_dir(LOGS_DIR)
    _rm_dir(NEWSLETTERS_DIR)
    _rm_dir(GRAVEYARD_DIR)

    # Clear league newsletters (stored in saves/league/newsletters/, not saves/newsletters/)
    league_newsletters_dir = os.path.join(SAVES_DIR, "league", "newsletters")
    if os.path.isdir(league_newsletters_dir):
        try:
            for fname in os.listdir(league_newsletters_dir):
                fpath = os.path.join(league_newsletters_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
            print("    Cleared league newsletters")
        except Exception as e:
            print(f"    WARNING: Could not clear league newsletters: {e}")

    # Clear league turn result directories (saves/league/turn_XXXX/).
    # These power the Proving Grounds tab; clearing them ensures post-reset
    # managers see only new-season data there.
    league_dir_path = os.path.join(SAVES_DIR, "league")
    if os.path.isdir(league_dir_path):
        cleared_turns = 0
        for entry in os.listdir(league_dir_path):
            if entry.startswith("turn_"):
                turn_path = os.path.join(league_dir_path, entry)
                if os.path.isdir(turn_path):
                    try:
                        shutil.rmtree(turn_path, ignore_errors=True)
                        cleared_turns += 1
                    except Exception as e:
                        print(f"    WARNING: Could not clear league turn dir {entry}: {e}")
        print(f"    Cleared {cleared_turns} league turn result directories (Proving Grounds reset)")

    _rm_file(SCOUTING_FILE)
    _rm_file(SESSION_FILE)
    _rm_file(CHAMPION_FILE)
    _rm_file(CHAMPION_HISTORY_FILE)
    _rm_file(os.path.join(SAVES_DIR, "rivals.json"))
    _rm_file(os.path.join(SAVES_DIR, "scout_narratives.json"))

    # Clear Elite/Soul Spire newsletter turn directories (turn_XXXX/newsletter.txt)
    # but preserve the teams/ subdirectory within each arena
    for arena_subdir in ("elite", "veteran"):
        arena_dir = os.path.join(SAVES_DIR, arena_subdir)
        if os.path.isdir(arena_dir):
            for entry in os.listdir(arena_dir):
                if entry.startswith("turn_"):
                    turn_path = os.path.join(arena_dir, entry)
                    if os.path.isdir(turn_path):
                        try:
                            shutil.rmtree(turn_path, ignore_errors=True)
                        except Exception as e:
                            print(f"    WARNING: Could not delete {turn_path}: {e}")
    print("    Cleared Elite/Soul Spire newsletter turn directories")

    # Delete old uploads from turn_0001 (auto-carry from previous season)
    turn_0001_dir = os.path.join(SAVES_DIR, "league", "turn_0001")
    if os.path.isdir(turn_0001_dir):
        try:
            for filename in os.listdir(turn_0001_dir):
                if filename.startswith("upload_") and filename.endswith(".json"):
                    try:
                        fpath = os.path.join(turn_0001_dir, filename)
                        make_file_writable(fpath)
                        os.remove(fpath)
                    except OSError:
                        pass
            print("    Cleared old uploads from turn_0001")
        except Exception as e:
            print(f"    WARNING: Could not clear old uploads: {e}")

    # Clear manager team_ids -- only remove NORMAL arena team IDs; keep elite/veteran
    print("  Clearing manager team registries (normal arena only)...")
    league_dir = os.path.join(SAVES_DIR, "league")
    managers_file = os.path.join(league_dir, "managers.json")
    if os.path.exists(managers_file):
        try:
            make_file_writable(managers_file)
            managers_data = load_json_protected(managers_file)

            # Build set of all elite/veteran team IDs by scanning those directories
            elite_vet_team_ids = set()
            for arena_subdir in ("elite", "veteran"):
                arena_teams_dir = os.path.join(SAVES_DIR, arena_subdir, "teams")
                if os.path.isdir(arena_teams_dir):
                    for fname in os.listdir(arena_teams_dir):
                        if fname.startswith("team_") and fname.endswith(".json"):
                            try:
                                td = load_json_protected(os.path.join(arena_teams_dir, fname), allow_tampered=True)
                                if isinstance(td, dict) and td.get("team_id") is not None:
                                    elite_vet_team_ids.add(int(td["team_id"]))
                            except Exception:
                                pass

            # Build per-manager elite/veteran team ID lists by scanning directories
            name_to_immortal_ids = {}
            for arena_subdir in ("elite", "veteran"):
                arena_teams_dir = os.path.join(SAVES_DIR, arena_subdir, "teams")
                if os.path.isdir(arena_teams_dir):
                    for fname in os.listdir(arena_teams_dir):
                        if fname.startswith("team_") and fname.endswith(".json"):
                            try:
                                td = load_json_protected(os.path.join(arena_teams_dir, fname), allow_tampered=True)
                                if isinstance(td, dict) and td.get("team_id") is not None:
                                    mname = td.get("manager_name", "")
                                    name_to_immortal_ids.setdefault(mname, set()).add(int(td["team_id"]))
                            except Exception:
                                pass

            # For each manager: clear normal arena team_ids; set immortal_team_ids from directories
            for manager_id in managers_data:
                if isinstance(managers_data[manager_id], dict):
                    mname = managers_data[manager_id].get("manager_name", "")
                    managers_data[manager_id]["team_ids"] = []
                    managers_data[manager_id]["immortal_team_ids"] = sorted(name_to_immortal_ids.get(mname, set()))

            save_json_protected(managers_file, managers_data)
            print(f"    Manager team registries cleared (preserved {len(elite_vet_team_ids)} elite/veteran team IDs)")
        except Exception as e:
            print(f"    WARNING: Could not clear manager registries: {e}")

    # STEP 4: Reset game state
    print("  Step 4: Resetting game state...")
    state = load_game_state()
    state["turn_number"] = 1
    state["current_turn"] = 1
    state["turn_state"] = "open"
    state["fight_counter"] = 0
    state["processing_started_at"] = ""
    state["schedule_last_run_at"] = ""
    state["schedule_last_run_turn"] = 0
    state["schedule_last_run_result"] = ""
    # Note: next_team_id is NOT reset - let it continue from where it was
    save_game_state(state)

    # STEP 5: Reset league config turn counter and increment reset_count to notify clients
    print("  Step 5: Resetting league config turn counter and notifying clients...")
    config_file = os.path.join(SAVES_DIR, "league", "config.json")
    try:
        make_file_writable(config_file)
        cfg = load_json_protected(config_file)
        cfg["current_turn"] = 1
        cfg["turn_state"] = "open"
        cfg["fight_counter"] = 0
        cfg.pop("processing_started_at", None)
        cfg["rerun_turn"] = 0
        cfg["rerun_count"] = cfg.get("rerun_count", 0)
        cfg["reset_count"] = cfg.get("reset_count", 0) + 1
        save_json_protected(config_file, cfg)
        print(f"    League config reset to turn 1 (reset_count={cfg['reset_count']})")
    except Exception as e:
        print(f"    WARNING: Could not reset league config: {e}")

    print("  Selective arena reset complete.")

    return {
        "success": True,
        "message": f"Selective arena reset complete.",
        "stats": {
            "normal_teams_deleted": normal_teams_deleted,
            "normal_warriors_deleted": normal_warriors_deleted,
            "elite_teams_preserved": elite_teams_preserved,
            "elite_warriors_preserved": elite_warriors_preserved,
            "veteran_teams_preserved": veteran_teams_preserved,
            "veteran_warriors_preserved": veteran_warriors_preserved,
            "total_warriors_preserved": elite_warriors_preserved + veteran_warriors_preserved,
            "archive_result": archive_result
        }
    }


# ---------------------------------------------------------------------------
# NEWSLETTERS
# ---------------------------------------------------------------------------

NEWSLETTERS_DIR  = os.path.join(SAVES_DIR, "newsletters")
CHAMPION_FILE    = os.path.join(SAVES_DIR, "champion.json")


def save_newsletter(turn_num: int, text: str):
    """Save a newsletter text to saves/newsletters/turn_NNN.txt."""
    os.makedirs(NEWSLETTERS_DIR, exist_ok=True)
    path = os.path.join(NEWSLETTERS_DIR, f"turn_{turn_num:04d}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    make_file_readonly(path) # Make text files read-only
    return path


def load_newsletter(turn_num: int) -> Optional[str]:
    """Load a specific newsletter. Returns None if not found."""
    path = os.path.join(NEWSLETTERS_DIR, f"turn_{turn_num:04d}.txt")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f: # No checksum for text files
        return f.read()


def list_newsletters() -> List[int]:
    """Return sorted list of turn numbers for which newsletters exist."""
    if not os.path.exists(NEWSLETTERS_DIR):
        return []
    nums = []
    for fname in os.listdir(NEWSLETTERS_DIR):
        if fname.startswith("turn_") and fname.endswith(".txt"):
            try:
                nums.append(int(fname[5:9]))
            except ValueError:
                pass
    return sorted(nums)


def load_champion_state() -> dict:
    """Load the current champion state."""
    if not os.path.exists(CHAMPION_FILE):
        return {}
    try:
        data = load_json_protected(CHAMPION_FILE)
    except Exception:
        return {}
    # Defensive: an older bug wrote the (state, is_new) tuple as a JSON list.
    # Recover the dict half so the game keeps running.
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                return item
        return {}
    return data if isinstance(data, dict) else {}


def save_champion_state(state: dict):
    """Persist champion state."""
    _ensure_dirs()
    save_json_protected(CHAMPION_FILE, state)


# ---------------------------------------------------------------------------
# CHAMPION HISTORY (main arena) - who held the title on each turn.
# Keyed by turn number, so re-running a turn overwrites that turn's entry
# instead of double counting. Feeds the newsletter's Champion History section.
# ---------------------------------------------------------------------------

CHAMPION_HISTORY_FILE = os.path.join(SAVES_DIR, "champion_history.json")


def load_champion_history(strict: bool = False) -> dict:
    """Return {turn_number: {name, warrior_id, team_id, team_name, manager_name}}.

    A missing file is an empty history. If the file exists but cannot be read
    (e.g. it failed its integrity check), strict=True raises so a writer never
    overwrites a history it could not read; strict=False returns {}.
    """
    if not os.path.exists(CHAMPION_HISTORY_FILE):
        return {}
    try:
        data = load_json_protected(CHAMPION_HISTORY_FILE)
    except Exception:
        if strict:
            raise
        return {}
    turns = data.get("turns") if isinstance(data, dict) else None
    out = {}
    for k, v in (turns or {}).items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            continue
    return out


def save_champion_history(history: dict):
    """Persist the champion history ({turn_number: entry})."""
    _ensure_dirs()
    save_json_protected(CHAMPION_HISTORY_FILE,
                        {"turns": {str(t): history[t] for t in sorted(history)}})


def record_champion_turn(turn_num: int, champ_state: dict, manager_name: str = ""):
    """Record who is champion for `turn_num` (call once the turn's champion is final).

    A vacant title records nothing, and clears any stale entry for that turn
    left by an earlier run of the same turn.
    """
    history = load_champion_history(strict=True)
    name = (champ_state or {}).get("name")
    if not name:
        history.pop(int(turn_num), None)
    else:
        history[int(turn_num)] = {
            "name":         name,
            "warrior_id":   champ_state.get("warrior_id"),
            "team_id":      champ_state.get("team_id"),
            "team_name":    champ_state.get("team_name", ""),
            "manager_name": manager_name or "",
        }
    save_champion_history(history)


def load_arena_champion_state(arena: str) -> dict:
    """Load the champion state for a specific arena (elite or veteran/soul)."""
    if arena == "normal":
        return load_champion_state()

    arena_dir = os.path.join(SAVES_DIR, arena)
    champion_file = os.path.join(arena_dir, "champion.json")

    if not os.path.exists(champion_file):
        return {}
    try:
        data = load_json_protected(champion_file)
    except Exception:
        return {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                return item
        return {}
    return data if isinstance(data, dict) else {}


def save_arena_champion_state(arena: str, state: dict):
    """Persist champion state for a specific arena."""
    if arena == "normal":
        save_champion_state(state)
        return

    arena_dir = os.path.join(SAVES_DIR, arena)
    os.makedirs(arena_dir, exist_ok=True)
    champion_file = os.path.join(arena_dir, "champion.json")
    save_json_protected(champion_file, state)




# ---------------------------------------------------------------------------
# SCOUTING (per-manager scout selections, reset each turn)
# ---------------------------------------------------------------------------
# Structure: { str(manager_id): { "turn": int, "selections": [
#   { "warrior_name": str, "team_name": str, "team_id": int, "confirmed": bool }, ...
# ] } }

def load_scouting() -> dict:
    """Load all manager scouting selections."""
    if not os.path.exists(SCOUTING_FILE):
        return {}
    try:
        return load_json_protected(SCOUTING_FILE)
    except Exception:
        return {}


def save_scouting(data: dict) -> None:
    """Persist scouting selections."""
    _ensure_dirs()
    save_json_protected(SCOUTING_FILE, data)


def get_manager_scouting(manager_id: int, current_turn: int, arena: str = None) -> list:
    """
    Return this manager's scout list for the current turn.
    If arena is given, only return selections for that arena.
    Returns list of dicts with: warrior_name, team_name, team_id, confirmed, arena.
    """
    data = load_scouting()
    key  = str(manager_id)
    entry= data.get(key, {})
    if entry.get("turn") != current_turn:
        return []
    selections = list(entry.get("selections", []))
    if arena is not None:
        selections = [s for s in selections if (s.get("arena") or "normal") == arena]
    return selections


def set_manager_scouting(manager_id: int, current_turn: int, selections: list) -> None:
    """Persist scout selections for a manager/turn (max 3 warriors)."""
    data = load_scouting()
    data[str(manager_id)] = {"turn": current_turn, "selections": selections[:3]}
    save_scouting(data)


def add_manager_scouting(manager_id: int, current_turn: int, warrior_name: str, team_name: str, team_id: int, confirmed: bool = True, arena: str = "normal") -> tuple:
    """
    Add a warrior to scout for a manager/turn. Returns (success, error_msg).
    Confirmed selections cannot be removed. Per-arena limit: 3 per arena.
    """
    data = load_scouting()
    key  = str(manager_id)
    entry= data.get(key, {})

    # Reset if different turn
    if entry.get("turn") != current_turn:
        entry = {"turn": current_turn, "selections": []}

    # Check if already scouting this warrior
    for sel in entry.get("selections", []):
        if sel.get("warrior_name") == warrior_name:
            return (False, "Already scouting that warrior")

    # Check per-arena limit (3 per arena)
    arena_count = sum(1 for s in entry.get("selections", []) if (s.get("arena") or "normal") == arena)
    if arena_count >= 3:
        return (False, "All 3 scout slots for this arena are full")
    
    # Add the selection
    entry.setdefault("selections", []).append({
        "warrior_name": warrior_name,
        "team_name": team_name,
        "team_id": team_id,
        "confirmed": confirmed,
        "arena": arena,
    })
    
    data[key] = entry
    save_scouting(data)
    return (True, "")


def remove_manager_scouting(manager_id: int, current_turn: int, warrior_name: str) -> tuple:
    """
    Remove a warrior from scout list (only if not confirmed).
    Returns (success, error_msg).
    """
    data = load_scouting()
    key  = str(manager_id)
    entry= data.get(key, {})
    
    if entry.get("turn") != current_turn:
        return (False, "No active scouting for this turn")
    
    selections = entry.get("selections", [])
    for i, sel in enumerate(selections):
        if sel.get("warrior_name") == warrior_name:
            if sel.get("confirmed"):
                return (False, "Cannot remove a confirmed scout selection")
            selections.pop(i)
            data[key] = entry
            save_scouting(data)
            return (True, "")
    
    return (False, "Warrior not found in scout list")


def confirm_manager_scouting(manager_id: int, current_turn: int, warrior_name: str) -> tuple:
    """
    Confirm a scouting selection (locks it permanently until turn ends).
    Returns (success, error_msg).
    """
    data = load_scouting()
    key  = str(manager_id)
    entry= data.get(key, {})
    
    if entry.get("turn") != current_turn:
        return (False, "No active scouting for this turn")
    
    selections = entry.get("selections", [])
    for sel in selections:
        if sel.get("warrior_name") == warrior_name:
            if sel.get("confirmed"):
                return (False, "Already confirmed")
            sel["confirmed"] = True
            data[key] = entry
            save_scouting(data)
            return (True, "")
    
    return (False, "Warrior not found in scout list")


def clear_manager_scouting(manager_id: int) -> None:
    """Remove all scouting selections for a manager (used after a turn completes)."""
    data = load_scouting()
    key  = str(manager_id)
    if key in data:
        del data[key]
        save_scouting(data)


def get_all_scouted_warriors(current_turn: int) -> dict:
    """
    Return a mapping of warrior_name → [manager_name, ...] for the current turn.
    Only includes confirmed scouts. Used during fight resolution to inject scout-attendance flavor text.
    """
    # Read the league server's manager registry directly - the old accounts.py
    # local store is gone; manager records live at saves/league/managers.json.
    mgrs = {}
    try:
        if os.path.exists(LEAGUE_MANAGERS_FILE):
            mgrs = load_json_protected(LEAGUE_MANAGERS_FILE) or {}
    except (IOError, json.JSONDecodeError):
        mgrs = {}
    data   = load_scouting()
    result = {}
    for mid_str, entry in data.items():
        if entry.get("turn") != current_turn:
            continue
        try:
            acc = mgrs.get(str(mid_str))
            mname = acc.get("manager_name", f"Manager {mid_str}") if acc else f"Manager {mid_str}"
        except Exception:
            mname = f"Manager {mid_str}"
        for sel in entry.get("selections", []):
            # Only count confirmed scouts
            if not sel.get("confirmed"):
                continue
            wname = sel.get("warrior_name", "")
            tid = sel.get("team_id", 0)
            if wname:
                result.setdefault((tid, wname), []).append(mname)
    return result


# ---------------------------------------------------------------------------
# SESSION (remember last-used credentials)
# ---------------------------------------------------------------------------

SESSION_FILE = os.path.join(SAVES_DIR, "session.json")


def save_session(manager_name: str, password: str = ""):
    """
    Persist login credentials for auto-login on next launch.
    Password is stored obfuscated (base64) - not plaintext, not cryptographically
    protected.  This is purely convenience; security relies on the server-side
    bcrypt/sha256 check in accounts.py.
    """
    _ensure_dirs()
    import base64 as _b64
    pw_stored = _b64.b64encode(password.encode()).decode() if password else ""
    try: # Session file is not protected, as it's client-side convenience
        with open(SESSION_FILE, "w", encoding="utf-8") as f: 
            json.dump({"manager_name": manager_name, "pw_stored": pw_stored}, f, indent=2)
    except IOError:
        pass


def load_session() -> dict:
    """
    Return {manager_name, pw_stored} or {} if no session saved.
    pw_stored is base64-encoded; decode with base64.b64decode().
    """
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f: # Session file is not protected
            return json.load(f) 
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# TEAM REPLACEMENT ARCHIVES
# ---------------------------------------------------------------------------

TEAM_ARCHIVES_DIR = os.path.join(SAVES_DIR, "team_archives")


def archive_replaced_team(team, reason: str = "replaced") -> str:
    """
    Save a full snapshot of a team (all warriors) before it is replaced or removed.
    Stored as saves/team_archives/team_XXXX_turnNNN.json.
    Returns the archive file path.
    """
    import datetime
    os.makedirs(TEAM_ARCHIVES_DIR, exist_ok=True)

    snap = team.to_dict() if hasattr(team, "to_dict") else dict(team)
    snap["archived_reason"] = reason
    snap["archived_at"]     = datetime.datetime.now().isoformat()
    snap["archived_turn"]   = current_turn()

    fname = f"team_{team.team_id:04d}_turn{current_turn():04d}.json"
    path  = os.path.join(TEAM_ARCHIVES_DIR, fname)
    save_json_protected(path, snap)
    return path
