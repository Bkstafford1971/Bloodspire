#!/usr/bin/env python3
# =============================================================================
# league_server.py - THE AGONY AMPHITHEATRE League Server
# =============================================================================
# The host runs this alongside their normal client.
# All other players connect to http://HOST_IP:8766 to upload teams and
# download results.
#
# Usage:
#   python league_server.py --host-password SECRET [--port 8766]
#
# Admin panel: http://localhost:8766/admin
# =============================================================================

import argparse
import hashlib
import http.server
import json
import os
import secrets
import socketserver
import sys
import threading
import time
import shutil
import urllib.parse
from file_protection import save_json_protected, load_json_protected, make_file_readonly, make_file_writable
import webbrowser
from typing import Optional

SERVER_VERSION = "3.0.0"

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
LEAGUE_DIR   = os.path.join(BASE_DIR, "saves", "league")
DEFAULT_PORT = 8766
sys.path.insert(0, BASE_DIR)

_lock          = threading.Lock()
_turn_progress = {"running": False, "done": 0, "total": 0, "message": ""}
_global_server = None  # Reference for graceful shutdown from request handlers
_server_port   = DEFAULT_PORT  # Set by main() once args are parsed


# =============================================================================
# STORAGE HELPERS
# =============================================================================

def _ensure_dirs():
    os.makedirs(LEAGUE_DIR, exist_ok=True)
    os.makedirs(os.path.join(LEAGUE_DIR, "activity_logs"), exist_ok=True)

def _log_activity(action, manager_id, manager_name, details=""):
    """Log user activity (uploads/downloads) to activity log."""
    try:
        log_dir = os.path.join(LEAGUE_DIR, "activity_logs")
        os.makedirs(log_dir, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            "timestamp": timestamp,
            "action": action,
            "manager_id": manager_id,
            "manager_name": manager_name,
            "details": details,
        }
        # Append to activity log file (not protected, just text)
        log_file = os.path.join(log_dir, "activity.jsonl")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"  ERROR writing activity log: {e}")

def _load_json(path, default, protected=True, allow_tampered=False):
    try:
        if protected:
            return load_json_protected(path, allow_tampered=allow_tampered)
        else:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        if protected and isinstance(e, ValueError) and not allow_tampered:
            print(f"  WARNING: Tampered file detected: {path} - {e}")
        return default

def _save_json(path, data, protected=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        if protected:
            save_json_protected(path, data)
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
    except IOError as e:
        print(f"  ERROR: Could not save {path}: {e}")

# Configuration and data paths that should be protected
def _config_path():   return os.path.join(LEAGUE_DIR, "config.json")
def _managers_path(): return os.path.join(LEAGUE_DIR, "managers.json")
def _standings_path():return os.path.join(LEAGUE_DIR, "standings.json")

def _turn_dir(turn_num):
    d = os.path.join(LEAGUE_DIR, f"turn_{int(turn_num):04d}")
    os.makedirs(d, exist_ok=True)
    return d

def _archive_dir(turn_num):
    """Archive directory for preserving result files. CRITICAL: Never delete result files."""
    d = os.path.join(LEAGUE_DIR, f"turn_{int(turn_num):04d}", "archive")
    os.makedirs(d, exist_ok=True)
    return d

def _safe_delete_file(fpath, archive_to_turn=None):
    """Safely delete a file by archiving it first.

    CRITICAL: Never destroy audit files (results and uploads) without archiving.
    If archive_to_turn is specified, archive to that turn's archive dir.
    """
    if not os.path.exists(fpath):
        return True

    try:
        fn = os.path.basename(fpath)
        # Archive audit files (results and uploads) - keep for auditing
        # Delete only temporary/working files
        is_result = fn.startswith("result_") and fn.endswith(".json")
        is_result_checksum = fn.endswith(".checksum") and "_result_" in fn
        is_upload = fn.startswith("upload_") and fn.endswith(".json")
        is_upload_checksum = fn.endswith(".checksum") and "_upload_" in fn

        if is_result or is_result_checksum or is_upload or is_upload_checksum:
            # Archive audit files (results and uploads)
            if archive_to_turn is not None:
                archive_dir = _archive_dir(archive_to_turn)
                import time
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                timestamped_archive = os.path.join(archive_dir, timestamp)
                os.makedirs(timestamped_archive, exist_ok=True)
                dst = os.path.join(timestamped_archive, fn)
                if os.path.exists(dst):
                    os.remove(dst)
                make_file_writable(fpath)
                shutil.move(fpath, dst)
                return True
            # If no archive_to_turn specified, still don't delete audit files
            return True

        # Safe to delete only non-audit files (newsletters, etc.)
        make_file_writable(fpath)
        os.remove(fpath)
        # Also remove checksum
        cf = fpath.replace(".json", ".checksum")
        if os.path.exists(cf):
            make_file_writable(cf)
            os.remove(cf)
        return True
    except Exception as e:
        print(f"  WARNING: Failed to process {fpath}: {e}")
        return False

def _archive_old_results(turn_num):
    """Preserve audit files (results and uploads) by archiving instead of deleting.

    CRITICAL: Result and upload files are the only source of truth for auditing and validation.
    These must be preserved at all costs for manual review and dispute resolution.
    """
    try:
        turn_dir = _turn_dir(turn_num)
        archive_dir = _archive_dir(turn_num)

        if not os.path.exists(turn_dir):
            return

        import time
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        timestamped_archive = os.path.join(archive_dir, timestamp)
        os.makedirs(timestamped_archive, exist_ok=True)

        for fn in os.listdir(turn_dir):
            # Archive result files and newsletter only - never move uploads here,
            # because uploads are the input data and must survive a failed turn run.
            if (fn.startswith("result_") and fn.endswith(".json")) or fn == "newsletter.txt":
                src = os.path.join(turn_dir, fn)
                dst = os.path.join(timestamped_archive, fn)
                try:
                    if os.path.exists(dst):
                        os.remove(dst)
                    shutil.move(src, dst)
                    # Also move checksum if exists
                    if fn.endswith(".json"):
                        cf_src = src.replace(".json", ".checksum")
                        cf_dst = dst.replace(".json", ".checksum")
                        if os.path.exists(cf_src):
                            if os.path.exists(cf_dst):
                                os.remove(cf_dst)
                            shutil.move(cf_src, cf_dst)
                except Exception as e:
                    print(f"  WARNING: Failed to archive {fn}: {e}")
    except Exception as e:
        print(f"  ERROR in _archive_old_results: {e}")

def _load_config():
    # allow_tampered=True for config.json to allow the server to boot and fix its own checksum
    cfg = _load_json(_config_path(), {
        "current_turn": 1,
        "turn_state": "open",
        "host_password_hash": "", # This will be set on first run
        "host_password_salt": "",
        "fight_counter": 0,
        "reset_count": 0,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "show_favorite_weapon": False,
        "show_luck_factor": False,
        "show_max_hp": False,
        "ai_teams_enabled": True,
        "schedule_enabled": False,
        "schedule_slots": [],
        "github_push_enabled": True,
    }, allow_tampered=True)
    # Ensure new flags exist in old configs
    for key, default in [
        ("show_favorite_weapon", False),
        ("show_luck_factor", False),
        ("show_max_hp", False),
        ("ai_teams_enabled", True),
        ("schedule_enabled", False),
        ("admin_debug_manager_id", ""),
        ("rerun_count", 0),
        ("rerun_turn", 0),
        ("github_push_enabled", True),
    ]:
        if key not in cfg:
            cfg[key] = default
    # Migrate old single-slot schedule_day/schedule_time to schedule_slots
    if "schedule_slots" not in cfg:
        old_day  = cfg.get("schedule_day",  "Friday")
        old_time = cfg.get("schedule_time", "20:00")
        cfg["schedule_slots"] = [{
            "day": old_day, "time": old_time,
            "last_run_at":     cfg.get("schedule_last_run_at", ""),
            "last_run_turn":   cfg.get("schedule_last_run_turn", 0),
            "last_run_result": cfg.get("schedule_last_run_result", ""),
        }]
    return cfg

def _save_config(cfg):   _save_json(_config_path(), cfg)
def _load_managers():    return _load_json(_managers_path(), {}) # Protected
def _save_managers(m):   _save_json(_managers_path(), m) # Protected
def _load_standings():   return _load_json(_standings_path(), {}, allow_tampered=True) # Protected (allow admin edits)
def _save_standings(s):  _save_json(_standings_path(), s) # Protected

def _build_game_data():
    """Build the game_data object (races, weapons, armor, skills, etc) for API endpoints.
    Used by /api/game_data and included in /api/results downloads."""
    from warrior import (
        ATTRIBUTES, FIGHTING_STYLES, TRIGGERS, AIM_DEFENSE_POINTS,
        NON_WEAPON_SKILLS, WEAPON_SKILLS,
    )
    from weapons import WEAPONS
    from armor import armor_selection_menu, helm_selection_menu
    from races import list_playable_races

    return {
        "weapons"          : sorted([w.display for w in WEAPONS.values()]),
        "armor"            : armor_selection_menu() + ["None"],
        "helms"            : helm_selection_menu() + ["None"],
        "triggers"         : TRIGGERS,
        "styles"           : FIGHTING_STYLES,
        "aim_points"       : AIM_DEFENSE_POINTS,
        "races"            : list_playable_races(),
        "genders"          : ["Male","Female"],
        "attributes"       : ATTRIBUTES,
        "non_weapon_skills": NON_WEAPON_SKILLS,
        "weapon_skills"    : sorted(WEAPON_SKILLS),
        "train_skills"     : sorted(
            ["Strength","Dexterity","Constitution","Intelligence","Presence"] +
            [s.replace("_"," ").title() for s in NON_WEAPON_SKILLS] +
            [w.display for w in WEAPONS.values()]
        ),
    }

def _load_uploads(turn_num):
    td = _turn_dir(turn_num) # This directory contains protected files
    if not os.path.exists(td): return {}

    # Load manager registry to verify team ownership. This prevents 'ghost'
    # uploads from teams that were replaced or withdrawn but the file lingered
    # (e.g. from an auto-carry).
    mgrs = _load_managers()

    uploads = {}
    for fname in sorted(os.listdir(td)):
        if not (fname.startswith("upload_") and fname.endswith(".json")):
            continue
        data = _load_json(os.path.join(td, fname), None)
        if not data:
            continue # If tampered, _load_json returns None, so it's skipped
        mid     = str(data.get("manager_id") or "")
        team_id = data.get("team_id") or (data.get("team") or {}).get("team_id", "")

        # Verify that this manager exists in the registry.
        if mid not in mgrs: continue

        # Verify team ownership: skip uploads where this manager doesn't own the team.
        # Ghost uploads occur when manager IDs are reshuffled (e.g. after an arena revert)
        # and stale files from old ID assignments remain on disk. Without this check,
        # the same team_id appears under two manager IDs and matchmaking silently drops
        # one of them via the team_id deduplication dict.
        if team_id:
            mgr_teams = [str(t) for t in mgrs[mid].get("team_ids", [])]
            if str(team_id) not in mgr_teams:
                print(f"  [WARN] Skipping {fname}: team {team_id} not in manager {mid}'s registry - ghost upload ignored")
                continue

        # Key by manager_id+team_id so multiple teams from same manager coexist
        key = f"{mid}_team{team_id}" if team_id else mid
        uploads[key] = data
    return uploads

def _normalize_team_challenge_keys(team_dict):
    """Normalize challenge and pending_replacement keys to string slot indices."""
    if not isinstance(team_dict, dict):
        return

    # Build a name-to-slot map from the team's active roster
    name_to_slot = {}
    warriors = team_dict.get("warriors", []) or []
    for i, w in enumerate(warriors):
        if isinstance(w, dict) and w.get("name"):
            name_to_slot.setdefault(w["name"].lower(), []).append(i)

    for field in ("challenges", "pending_replacements"):
        raw_map = team_dict.get(field)
        if not isinstance(raw_map, dict):
            continue

        normalized = {}
        for key, value in raw_map.items():
            key_str = str(key)
            if key_str.isdigit():
                normalized[str(int(key_str))] = value
                continue

            matches = name_to_slot.get(key_str.lower(), [])
            if len(matches) == 1:
                normalized[str(matches[0])] = value
                print(
                    f"  NOTE: Normalized {field} key '{key_str}' to slot {matches[0]} "
                    f"for team '{team_dict.get('team_name', 'Unknown')}'."
                )
            elif len(matches) > 1:
                print(
                    f"  WARNING: Ambiguous {field} key '{key_str}' in team "
                    f"'{team_dict.get('team_name', 'Unknown')}'. Multiple warriors share that name."
                )
                normalized[key_str] = value
            else:
                print(
                    f"  WARNING: Could not normalize {field} key '{key_str}' "
                    f"for team '{team_dict.get('team_name', 'Unknown')}'."
                )
                normalized[key_str] = value

        team_dict[field] = normalized


def _save_upload(turn_num, manager_id, data):
    team_id = data.get("team_id") or (data.get("team") or {}).get("team_id", "")
    if isinstance(data.get("team"), dict):
        _normalize_team_challenge_keys(data["team"])
    if team_id:
        fname = f"upload_{manager_id}_team{team_id}.json"
    else:
        fname = f"upload_{manager_id}.json"
    _save_json(os.path.join(_turn_dir(turn_num), fname), data) # Protected

def _load_result(turn_num, manager_id):
    return _load_json(os.path.join(_turn_dir(turn_num), f"result_{manager_id}.json"), None) # Protected

def _save_result(turn_num, manager_id, data):
    # Include team_id in filename so a manager with multiple teams has separate files
    team_id = data.get("team_id", "")
    if team_id:
        fname = f"result_{manager_id}_team{team_id}.json"
    else:
        fname = f"result_{manager_id}.json"
    path = os.path.join(_turn_dir(turn_num), fname)
    try:
        _save_json(path, data)  # Protected
        # Verify file was created (fail fast for debugging)
        if not os.path.exists(path):
            print(f"  ERROR: Result file was not created at {path}")
    except Exception as e:
        print(f"  ERROR: Failed to save result for {manager_id} to {path}: {e}")
        import traceback
        traceback.print_exc()

def _load_deaths_from_results(turn_num):
    """
    Load all deaths from saved result files for a turn.
    This is the authoritative source - each result file contains all bouts
    that were executed, with warrior_slain and opponent_slain flags.

    Peasants and monsters can die multiple times in a single turn if they
    fight multiple times. We capture all deaths, even if the same peasant
    name appears multiple times (distinguished by fight_id).
    """
    deaths = []
    seen_deaths = set()  # Use (name, fight_id) tuple to allow multiple deaths of same name
    turn_path = _turn_dir(turn_num)

    try:
        if not os.path.isdir(turn_path):
            print(f"  WARNING: Turn directory not found: {turn_path}")
            return deaths

        # Load all result_*.json files from the turn directory
        for fname in os.listdir(turn_path):
            if fname.startswith("result_") and fname.endswith(".json"):
                fpath = os.path.join(turn_path, fname)
                res = _load_json(fpath, None)
                if not res:
                    continue

                # Extract deaths from all bouts in this result file
                for bout in res.get("bouts", []):
                    # Check if player warrior was slain
                    if bout.get("warrior_slain"):
                        wname = bout.get("warrior_name", "?")
                        fight_id = bout.get("fight_id", 0)
                        # Use (name, fight_id) as unique key to allow multiple deaths of same name
                        death_key = (wname, fight_id)
                        if death_key not in seen_deaths:
                            seen_deaths.add(death_key)
                            deaths.append({
                                "name": wname,
                                "team": res.get("team_name", "?"),
                                "team_id": res.get("team_id", 0),
                                "w": bout.get("wins", 0),
                                "l": bout.get("losses", 0),
                                "k": bout.get("kills", 0),
                                "killed_by": bout.get("opponent_name", "?"),
                                "turn": turn_num,
                            })

                    # Check if opponent was slain
                    if bout.get("opponent_slain"):
                        oname = bout.get("opponent_name", "?")
                        fight_id = bout.get("fight_id", 0)
                        # Use (name, fight_id) as unique key to allow multiple deaths of same name
                        death_key = (oname, fight_id)
                        if death_key not in seen_deaths:
                            seen_deaths.add(death_key)
                            deaths.append({
                                "name": oname,
                                "team": bout.get("opponent_team", "?"),
                                "team_id": bout.get("opponent_team_id", 0),
                                "w": bout.get("opponent_wins", 0),
                                "l": bout.get("opponent_losses", 0),
                                "k": bout.get("opponent_kills", 0),
                                "killed_by": bout.get("warrior_name", "?"),
                                "turn": turn_num,
                            })
    except Exception as e:
        print(f"  ERROR loading deaths from results: {e}")
        import traceback
        traceback.print_exc()

    return deaths

def _write_execution_log(turn_num, exec_log):
    """Write a human-readable table of turn execution status for all warriors."""
    exec_log_path = os.path.join(_turn_dir(turn_num), "execution_log.txt")
    try:
        with open(exec_log_path, "w", encoding="utf-8") as f:
            f.write(f"TURN {turn_num} EXECUTION LOG\n")
            f.write(f"Started: {exec_log.get('started_at', 'Unknown')}\n")
            f.write(f"Finished: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*110 + "\n")
            f.write(f"{'MANAGER':<20} {'TEAM':<20} {'WARRIOR':<20} {'STATUS':<25} {'OPPONENT':<20}\n")
            f.write("-"*110 + "\n")
            
            # Sort warriors by manager then team then name
            sorted_warriors = sorted(exec_log["warriors"].values(), 
                                     key=lambda x: (x["manager"], x["team"], x["name"]))
            
            for w in sorted_warriors:
                f.write(f"{w['manager'][:19]:<20} {w['team'][:19]:<20} {w['name'][:19]:<20} "
                        f"{w['status']:<25} {(w['opponent'] or 'None')[:19]:<20}\n")
                if w.get("error"):
                    f.write(f"  ! ERROR: {w['error']}\n")
        print(f"  Execution log written: {exec_log_path}")
    except Exception as e:
        print(f"  WARNING: Could not write execution log: {e}")


# =============================================================================
# AUTH HELPERS
# =============================================================================

def _hash_pw(password, salt):
    return hashlib.sha256((salt + password).encode()).hexdigest()

def _check_host_pw(cfg, password):
    return _hash_pw(password, cfg["host_password_salt"]) == cfg["host_password_hash"]

def _check_mgr_pw(mgr, password):
    return _hash_pw(password, mgr["salt"]) == mgr["password_hash"]


def _get_or_assign_scout_persona(mid: str, mgrs: dict) -> tuple:
    """
    Return (scout_name, scout_type) for this manager.
    If not yet assigned, pick one randomly, persist it, and return it.
    """
    import random
    from scout_report import PERSONA_TYPES, random_persona_name
    mgr = mgrs.get(mid, {})
    scout = mgr.get("scout")
    if scout and scout.get("name") and scout.get("type"):
        return scout["name"], scout["type"]
    # Assign fresh persona
    ptype = random.choice(PERSONA_TYPES)
    pname = random_persona_name(ptype)
    mgr["scout"] = {"name": pname, "type": ptype}
    mgrs[mid] = mgr
    _save_managers(mgrs)
    return pname, ptype

def _next_fid(cfg):
    cfg["fight_counter"] = cfg.get("fight_counter", 0) + 1
    return cfg["fight_counter"]


def _make_mirror_narrative(
    narrative        : str,
    training_results : dict,
    a_name           : str,
    b_name           : str,
    warrior_a        : 'Warrior' = None,
    warrior_b        : 'Warrior' = None,
) -> str:
    """
    Return a version of the fight narrative from warrior_b's manager's perspective:
      - warrior_b is listed first (so their strategy is shown first)
      - warrior_b's training shows the actual skills/stats learned
      - warrior_a's training shows "Skill" or "Stat" (generic)
      - warrior_b's strategy table is shown
    """
    from narrative import training_summary as _ts, _strategy_table

    # Key presence distinguishes dead warriors (key absent - no training line emitted)
    # from alive warriors who trained in nothing (key present, value is []).
    a_alive = "warrior_a" in training_results
    b_alive = "warrior_b" in training_results
    a_res = training_results.get("warrior_a", [])
    b_res = training_results.get("warrior_b", [])
    if isinstance(b_res, dict):
        b_res = []  # safety guard

    # Compute the MIRROR training block (warrior_b perspective)
    mir_parts = []
    if b_alive:
        mir_parts.append(_ts(b_name, b_res, is_opponent=False))
    if a_alive:
        mir_parts.append(_ts(a_name, a_res, is_opponent=True))

    result = narrative

    # Replace warrior A's strategy table with warrior B's
    if warrior_a and warrior_b:
        try:
            from narrative import _strategy_table
            b_strat_lines = _strategy_table(warrior_b)
            if b_strat_lines:
                # Find the strategy table section in the narrative (look for the header)
                hdr = f"{'TRIGGER':<42}{'FIGHTING STYLE':<20}{'LEVEL':>5}  {'AIMING POINT':<16}{'DEFENSE POINT'}"
                if hdr in result:
                    hdr_idx = result.find(hdr)
                    # Find the blank line (double newline) BEFORE the strategy header
                    # Search backwards from the header to find the blank line that precedes it
                    sep_start = result.rfind("\n\n", 0, hdr_idx)
                    if sep_start < 0:
                        # If no double newline found, fall back to finding the last single newline before the header
                        sep_start = result.rfind("\n", 0, hdr_idx)
                        if sep_start < 0:
                            sep_start = 0
                        else:
                            sep_start += 1
                    else:
                        # Found double newline, move past it
                        sep_start += 2

                    # Find the end of the strategy table (next double newline)
                    strat_end = result.find("\n\n", hdr_idx)
                    if strat_end < 0:
                        strat_end = len(result)

                    # Build new strategy section for warrior B
                    new_strat = "\n".join(b_strat_lines)

                    # Replace it
                    result = result[:sep_start] + new_strat + result[strat_end:]
        except Exception:
            pass  # Silently continue if strategy replacement fails

    if not mir_parts:
        return result

    mir_block = "\n\n" + "\n".join(mir_parts)

    # Locate the training section using rfind with the first expected training line.
    # Training is always preceded by a blank line (\n\n) and starts with the first
    # alive warrior's name followed by " has trained in".  Using rfind (search from
    # the end) means even if the warrior's name appears in fight-action text, we
    # always find the LAST occurrence - which is the training block.
    if a_alive:
        needle = f"\n\n{a_name.upper()} has trained in"
    elif b_alive:
        needle = f"\n\n{b_name.upper()} has trained in"
    else:
        needle = ""

    if needle:
        pos = result.rfind(needle)
        if pos >= 0:
            return result[:pos] + mir_block

    # Fallback: reconstruct the forward block and use endswith
    fwd_parts = []
    if a_alive:
        fwd_parts.append(_ts(a_name, a_res, is_opponent=False))
    if b_alive:
        fwd_parts.append(_ts(b_name, b_res, is_opponent=True))
    fwd_block = "\n\n" + "\n".join(fwd_parts) if fwd_parts else ""
    if fwd_block and result.endswith(fwd_block):
        return result[: -len(fwd_block)] + mir_block

    print(f"  WARNING: _make_mirror_narrative could not locate training block for {a_name} vs {b_name}")
    return result


def _strip_strategy_table(narrative: str) -> str:
    """
    Remove the strategy table section from a fight narrative entirely.

    Used for scout reports: a scout observes the fight itself, not either
    combatant's printed strategy table. Reuses the exact same header anchor
    and blank-line boundary search as _make_mirror_narrative() (which swaps
    the table for the opponent's manager) but deletes the section instead
    of substituting a different one.
    """
    hdr = f"{'TRIGGER':<42}{'FIGHTING STYLE':<20}{'LEVEL':>5}  {'AIMING POINT':<16}{'DEFENSE POINT'}"
    if hdr not in narrative:
        return narrative
    hdr_idx = narrative.find(hdr)

    sep_start = narrative.rfind("\n\n", 0, hdr_idx)
    if sep_start < 0:
        sep_start = narrative.rfind("\n", 0, hdr_idx)
        sep_start = 0 if sep_start < 0 else sep_start + 1
    else:
        sep_start += 2

    strat_end = narrative.find("\n\n", hdr_idx)
    if strat_end < 0:
        strat_end = len(narrative)

    return narrative[:sep_start] + narrative[strat_end:]


def _strip_training_block(narrative: str) -> str:
    """
    Remove the trailing per-warrior training summary from a fight narrative.

    Training lines ("<NAME> has trained in ...") are always the last thing
    appended to a fight's narrative (see CombatEngine._make_result in
    combat.py), one per surviving warrior, with nothing after them. A scout
    observes the fight itself, not either warrior's private training results,
    so this is a plain truncation rather than a swap like the strategy table.
    """
    marker = " has trained in"
    idx = narrative.find(marker)
    if idx < 0:
        return narrative

    line_start = narrative.rfind("\n", 0, idx)
    line_start = 0 if line_start < 0 else line_start + 1

    sep_start = narrative.rfind("\n\n", 0, line_start)
    cut = sep_start if sep_start >= 0 else line_start

    return narrative[:cut].rstrip("\n")


def _store_scout_narrative(team_id: int, warrior_name: str, narrative: str, turn_num: int) -> None:
    """
    Persist the fight narrative for a scouted warrior so the client can
    retrieve it via the scout report without needing to chase fight_ids.
    Stored at saves/league/scout_narratives.json keyed by warrior name.
    """ # This is a protected file
    path = os.path.join(LEAGUE_DIR, "scout_narratives.json")
    try:
        data = _load_json(path, {})
        key = f"{team_id}:{warrior_name}"
        data[key] = {"narrative": narrative, "turn": turn_num}
        _save_json(path, data)
    except Exception:
        pass


# =============================================================================
# FIGHT RUNNER
# =============================================================================

def _warrior_total_trains(w) -> int:
    """Return lifetime combined skill + attribute trains for a warrior."""
    skills      = getattr(w, "skills", None) or {}
    attr_gains  = getattr(w, "attribute_gains", None) or {}
    return sum(skills.values()) + sum(attr_gains.values())


def _check_promotion_eligibility(all_teams: list, cfg: dict) -> list:
    """Flag normal-arena warriors who meet Elite Spire promotion criteria.

    Criteria (all three must be satisfied):
      - Minimum fights    (default 30)
      - Minimum win rate  (default 65%)
      - Minimum combined trains — skill levels + attribute gains (default 30)

    Sets pending_promotion='elite' on eligible warriors.
    Returns list of {name, team, record} dicts for newsletter/logging.
    """
    promo_cfg    = cfg.get("promotion_criteria", {})
    min_fights   = int(promo_cfg.get("min_fights",   30))
    min_win_rate = float(promo_cfg.get("min_win_rate", 0.65))
    min_trains   = int(promo_cfg.get("min_trains",   30))
    newly_eligible = []
    for team in all_teams:
        for w in team.active_warriors:
            if not w:
                continue
            if getattr(w, "current_arena", "normal") != "normal":
                continue
            if getattr(w, "pending_promotion", None) is not None:
                continue
            total = w.wins + w.losses
            if total < min_fights:
                continue
            win_rate = w.wins / total if total > 0 else 0.0
            if win_rate < min_win_rate:
                continue
            trains = _warrior_total_trains(w)
            if trains < min_trains:
                continue
            w.pending_promotion = "elite"
            newly_eligible.append({"name": w.name, "team": team.team_name,
                                   "record": f"{w.wins}W/{w.losses}L/{w.kills}K"})
            print(f"  PROMOTION ELIGIBLE: {w.name} ({team.team_name}) - "
                  f"{w.wins}W/{w.losses}L ({win_rate:.1%}), {trains} trains "
                  f"-> pending Elite Spire promotion next turn.")
    return newly_eligible


def _execute_promotions(all_teams: list, turn_num: int) -> list:
    """Move warriors with pending_promotion to their target arena.

    Warriors who died during their final mortal fight are revived by the
    immortality shield before promotion.  Returns list of promotion event dicts.
    """
    events = []
    for team in all_teams:
        for w in (team.warriors or []):
            if not w:
                continue
            target = getattr(w, "pending_promotion", None)
            if not target:
                continue
            if getattr(w, "current_arena", "normal") not in ("normal",):
                continue
            if w.is_dead:
                print(f"  SHIELD REVIVE: {w.name} fell in their final mortal fight - "
                      f"immortality shield triggers, promotion proceeds.")
                w.is_dead  = False
                w.hp       = max(1, getattr(w, "max_hp", 100) // 2)
            w.current_arena    = target
            w.pending_promotion = None
            w.recognition       = 0
            events.append({
                "type":         "promotion",
                "warrior_name": w.name,
                "team_name":    team.team_name,
                "team_id":      team.team_id,
                "from_arena":   "normal",
                "to_arena":     target,
                "record":       f"{w.wins}W/{w.losses}L/{w.kills}K",
                "turn":         turn_num,
            })
            _disp = {"elite": "THE ELITE SPIRE", "veteran": "THE DEAD GROUNDS"}.get(target, target.upper())
            print(f"  PROMOTED: {w.name} ({team.team_name}) -> {_disp} "
                  f"({w.wins}W/{w.losses}L/{w.kills}K)")
    return events


def _run_turn(request_password, rerun_turn=None):
    """Run all fights for the current (or re-run) turn using GLOBAL POOL MATCHMAKING.

    This ensures every warrior fights exactly ONCE per turn, no exceptions.
    """
    # Clear Python cache to ensure fresh weapon/gear data loads
    import shutil
    project_dir = os.path.dirname(os.path.abspath(__file__))
    for root, dirs, files in os.walk(project_dir):
        if '__pycache__' in dirs:
            try:
                shutil.rmtree(os.path.join(root, '__pycache__'))
            except Exception:
                pass

    global _turn_progress
    with _lock:
        cfg = _load_config()
        if not _check_host_pw(cfg, request_password):
            return {"success": False, "error": "Not authorised."}
        if cfg.get("turn_state") == "processing":
            # Safety check: if stuck for > 10 mins, allow override
            import datetime as _dt
            started = cfg.get("processing_started_at", "")
            stuck = False
            if started:
                try:
                    diff = _dt.datetime.now() - _dt.datetime.fromisoformat(started)
                    if diff.total_seconds() > 600:
                        stuck = True
                except: stuck = True
            else: stuck = True
            if not stuck:
                return {"success": False, "error": "Turn is already running."}
        if rerun_turn:
            last_completed = cfg["current_turn"] - 1
            if rerun_turn != last_completed:
                return {"success": False,
                        "error": f"Only turn {last_completed} (the last completed turn) can be re-run."}
        turn_num = rerun_turn if rerun_turn else cfg["current_turn"]
        uploads = _load_uploads(turn_num)

        # Inject AI teams as pseudo-uploads
        ai_teams = []
        if cfg.get("ai_teams_enabled", True):
            try:
                from ai_league_teams import get_or_create_ai_teams
                ai_teams = get_or_create_ai_teams()
                for ai_team in ai_teams:
                    mid = ai_team["manager_id"]
                    if rerun_turn:
                        from team import Team
                        prev_turn = rerun_turn - 1
                        if prev_turn >= 1:
                            td_prev = _turn_dir(prev_turn)
                            res_file = os.path.join(td_prev, f"result_{mid}.json")
                            if os.path.exists(res_file):
                                prev_res = _load_json(res_file, None)
                                if prev_res and prev_res.get("team"):
                                    ai_team.clear(); ai_team.update(prev_res["team"])
                        elif rerun_turn == 1:
                            t_obj = Team.from_dict(ai_team)
                            t_obj.revert_all_progress()
                            ai_team.clear(); ai_team.update(t_obj.to_dict())
                    if mid not in uploads:
                        uploads[mid] = {
                            "manager_id": mid,
                            "manager_name": ai_team["manager_name"],
                            "team": ai_team,
                            "uploaded_at": "AI (auto)",
                            "is_ai": True,
                        }
            except Exception as e:
                print(f"  WARNING: Could not load AI teams: {e}")

        if not uploads:
            return {"success": False, "error": "No teams (player or AI) available."}

        _FLAG_KEYS = ("show_favorite_weapon", "show_luck_factor", "show_max_hp", "ai_teams_enabled")
        _turn_start_flags = {k: cfg.get(k) for k in _FLAG_KEYS}

        # Archive old results instead of deleting (CRITICAL: preserve for auditing)
        _archive_old_results(turn_num)

        cfg["turn_state"] = "processing"
        import datetime as _dt2
        cfg["processing_started_at"] = _dt2.datetime.now().isoformat()
        _save_config(cfg)
        _turn_progress = {"running": True, "done": 0, "total": len(uploads),
                          "message": "Starting global matchmaking..."}

    from team import Team
    from combat import run_fight, set_show_favorite_weapon, set_show_luck_factor, set_show_max_hp

    # Apply feature flags
    cfg = _load_config()
    set_show_favorite_weapon(_turn_start_flags.get("show_favorite_weapon", False))
    set_show_luck_factor(_turn_start_flags.get("show_luck_factor", False))
    set_show_max_hp(_turn_start_flags.get("show_max_hp", False))

    # Build debug warrior set - fights involving these warriors get verbose logs
    _dbg_mid = cfg.get("admin_debug_manager_id", "")
    _debug_warrior_names: set = set()
    _dbg_mgr_name = ""
    if _dbg_mid:
        for _upl in uploads.values():
            if str(_upl.get("manager_id", "")) == str(_dbg_mid):
                try:
                    for _w in (_upl["team"].get("warriors") or []):
                        if _w and _w.get("name"):
                            _debug_warrior_names.add(_w["name"])
                    if not _dbg_mgr_name:
                        _dbg_mgr_name = _upl.get("manager_name", _dbg_mid)
                except Exception:
                    pass
    _dbg_turn_dir = os.path.join(BASE_DIR, "saves", "admin_logs", f"turn_{turn_num:04d}") if _debug_warrior_names else ""
    if _dbg_turn_dir:
        os.makedirs(_dbg_turn_dir, exist_ok=True)
        print(f"  [DEBUG] Logging fights for manager '{_dbg_mgr_name}' ({len(_debug_warrior_names)} warriors) → {_dbg_turn_dir}")

    # Load champion state
    try:
        from save import load_champion_state
        champ_state = load_champion_state()

        # Validate champion exists in current standings
        # If champion file is out of sync, reset it
        if champ_state.get("name"):
            standings_data = _load_standings({})  # Load standings to verify
            champ_name = champ_state.get("name")
            champ_tid = champ_state.get("team_id", 0)
            champ_wid = champ_state.get("warrior_id")
            found = False
            for team_key, team_data in standings_data.items():
                if team_data.get("team_id") == champ_tid:
                    for warrior in team_data.get("warriors", {}).values():
                        w_name = warrior.get("name")
                        w_id = warrior.get("warrior_id")
                        if (w_name == champ_name) and (champ_wid is None or w_id == champ_wid):
                            found = True
                            break
                if found:
                    break
            # If champion not found in standings, reset
            if not found:
                print(f"  WARNING: Champion {champ_name} (ID {champ_tid}) not found in standings. Resetting champion state.")
                champ_state = {}
    except Exception:
        champ_state = {}

    # ===================================================================
    # STEP 1: Build ALL team objects from uploads
    # ===================================================================
    all_player_teams = []
    all_opponent_teams = []
    team_map = {}  # manager_id -> Team object
    manager_info = {}  # manager_id -> {manager_name, is_ai}

    print(f"\n  ===== LOADING TEAMS FOR TURN {turn_num} =====\n")

    for mid, upload in uploads.items():
        try:
            team = Team.from_dict(upload["team"])
            from save import reconcile_warrior_ids
            reconcile_warrior_ids(team, team.team_id)
            team.manager_name = upload["manager_name"]

            # CRITICAL FIX: Ensure warriors marked as dead in recent turn results stay dead
            # This prevents a bug where dead warriors reactivate when loaded from old uploads
            #
            # IMPORTANT: Must key on (team_id, warrior_id), not just name. Managers can run
            # multiple teams, and a name can be reused by a new warrior after the old one
            # died (or collide across a manager's other teams). Matching on name alone will
            # falsely kill an unrelated, living warrior who happens to share a name with a
            # warrior who died elsewhere. See RATAMAHATTA/PHILTH/FRENCH DIP incident, turn 28.
            import glob as _glob_mod
            _real_mid = mid.split("_team")[0] if "_team" in mid else mid
            _this_team_id = team.team_id
            _dead_in_results = {}  # warrior_id -> {is_dead: true, killed_by: ...}

            # Check current turn AND recent previous turns for dead warriors,
            # restricted to result files for THIS specific team only.
            for _check_turn in range(max(1, turn_num - 3), turn_num + 1):
                _res_file_pattern = os.path.join(
                    _turn_dir(_check_turn), f"result_{_real_mid}_team{_this_team_id}_*.json"
                )
                for _res_path in _glob_mod.glob(_res_file_pattern):
                    try:
                        _res_data = _load_json(_res_path, None)
                        if _res_data and _res_data.get("team"):
                            if _res_data["team"].get("team_id") != _this_team_id:
                                continue
                            _res_warriors = _res_data["team"].get("warriors", []) or []
                            for _res_warrior in _res_warriors:
                                if _res_warrior and _res_warrior.get("is_dead"):
                                    _warrior_id = _res_warrior.get("warrior_id")
                                    if _warrior_id is None:
                                        continue
                                    _dead_in_results[_warrior_id] = {
                                        "name": _res_warrior.get("name"),
                                        "is_dead": True,
                                        "killed_by": _res_warrior.get("killed_by", "")
                                    }
                    except Exception:
                        pass

            # Apply dead status from results - matched by warrior_id, not name.
            for _w in team.warriors:
                if _w and _w.warrior_id in _dead_in_results:
                    _dead_entry = _dead_in_results[_w.warrior_id]
                    _w.is_dead = True
                    _w.killed_by = _dead_entry["killed_by"]
                    print(f"    [INTEGRITY CHECK] Warrior {_w.name} (id={_w.warrior_id}) was dead in recent results - enforced is_dead=True")

            team_map[mid] = team
            manager_info[mid] = {
                "manager_name": upload["manager_name"],
                "is_ai": mid.startswith("ai_")
            }
            all_player_teams.append(team)
            print(f"  Loaded: {team.team_name} (ID:{team.team_id}) - {len(team.active_warriors)} warriors - Manager: {upload['manager_name']}")
        except Exception as e:
            print(f"  WARN: could not load team for {upload.get('manager_name','?')}: {e}")

    # AI teams are already in player_teams (they're in uploads)
    # Opponent teams are the same as player teams for global matching
    # (we match player warriors against other player/AI warriors)
    all_opponent_teams = []

    print(f"\n  Total teams: {len(all_player_teams)}")
    total_warriors = sum(
        sum(1 for w in t.active_warriors if getattr(w, 'current_arena', 'normal') == 'normal')
        for t in all_player_teams
    )
    print(f"  Total warriors: {total_warriors}")
    print(f"  Expected fights: {total_warriors} (one per warrior)\n")

    # ===================================================================
    # STEP 2: Build GLOBAL fight card using global pool matchmaking
    # ===================================================================
    from matchmaking import build_global_fight_card
    import matchmaking as MM

    print("  Building global fight card...")
    # IMPORTANT: Only pass player_teams. The function will match them against each other.
    # arena="normal" ensures only normal-arena warriors enter the fight card.
    global_card = build_global_fight_card(
        player_teams=all_player_teams,
        opponent_teams=[],  # Empty - all warriors come from player_teams
        champion_state=champ_state,
        arena="normal",
    )

    # Clear the pending challenge requests now that the fight card is built.
    # Do NOT reset challenge_strategy_enabled yet — warriors need that flag
    # intact so the combat engine can apply their challenge strategies during fights.
    for team in all_player_teams:
        team.clear_challenges(reset_strategy_mode=False)

    print(f"\n  Global fight card built: {len(global_card)} fights scheduled")
    print(f"  Expected fights: {total_warriors}")
    if len(global_card) != total_warriors:
        print(f"  WARNING: Fight count mismatch! {len(global_card)} fights vs {total_warriors} warriors")

    # Precompute who's being scouted this turn, keyed by (team_id, warrior_name)
    # -> [scouting manager_name, ...]. Use turn_num explicitly (not cfg["current_turn"],
    # which doesn't get bumped until STEP 5) so the lookup matches the turn the
    # selections were confirmed against.
    from save import get_all_scouted_warriors
    scouted_this_turn = get_all_scouted_warriors(turn_num)
    # Fight narrative captured per scouted warrior for their scouting managers'
    # reports, built in STEP 3 and consumed in STEP 4. Keyed by (team_id, name).
    scout_fight_narratives = {}

    # ===================================================================
    # STEP 3: Execute all fights and collect results
    # ===================================================================
    all_results = {}  # manager_id -> result dict
    retirements_this_turn  = []  # list of {name, w, l, k, team, manager} for the newsletter
    transcendence_events   = []  # warriors who transcend to The Dead Grounds on death
    fight_counter = cfg.get("fight_counter", 0)

    # Track team objects for updating
    team_by_id = {t.team_id: t for t in all_player_teams}

    # CRITICAL: Preserve original backup_weapon values
    # Combat may clear backup_weapon if used, but we want to save the original values
    backup_weapon_backup = {}
    for team in all_player_teams:
        backup_weapon_backup[team.team_id] = {}
        for w in team.active_warriors:
            if w:
                backup_weapon_backup[team.team_id][w.name] = w.backup_weapon

    # For progress tracking
    total_fights = len(global_card)
    fights_completed = 0

    # Blood-challenge bullying / underdog tracking for this turn, consumed
    # after the fight loop (Commission title-strip check) and by the
    # newsletter's Arena Happenings section.
    import random
    bully_events = []
    stripped_champion_name = None

    for fight in global_card:
        fights_completed += 1
        fight_counter += 1
        fid = fight_counter

        _turn_progress["message"] = f"Fighting: {fight.player_warrior.name} vs {fight.opponent.name} ({fights_completed}/{total_fights})"
        _turn_progress["done"] = fights_completed

        print(f"\n  [{fights_completed}/{total_fights}] {fight.player_warrior.name} vs {fight.opponent.name} [{fight.fight_type}]")

        # Find manager IDs for both teams
        player_manager_id = None
        opponent_manager_id = None
        for mid, team in team_map.items():
            if team.team_id == fight.player_team.team_id:
                player_manager_id = mid
            if team.team_id == fight.opponent_team.team_id:
                opponent_manager_id = mid


        # Build debug logger if this fight involves a tracked warrior
        _dbg_logger = None
        if _debug_warrior_names and (
            fight.player_warrior.name in _debug_warrior_names
            or fight.opponent.name in _debug_warrior_names
        ):
            from combat_debug_logger import CombatDebugLogger as _CDBLogger
            _dbg_logger = _CDBLogger()
            _dbg_logger.fight_id   = fid
            _dbg_logger.turn_num   = turn_num
            _dbg_logger.debug_team = _dbg_mgr_name

        # Track killer participation in blood challenges
        # When a warrior fights, check if they are a BC target and increment their participation counter
        for team in team_map.values():
            # Check if opponent is a BC target
            team.record_killer_participation(fight.opponent.name)
            # Also check if player warrior is a BC target (for symmetry)
            team.record_killer_participation(fight.player_warrior.name)

        # Who's watching this fight? Union of scouts on either combatant -
        # the attendance line never reveals which one is the actual target.
        _player_key   = (fight.player_team.team_id, fight.player_warrior.name)
        _opponent_key = (fight.opponent_team.team_id, fight.opponent.name)
        _attending_scouts = list(dict.fromkeys(
            scouted_this_turn.get(_player_key, []) + scouted_this_turn.get(_opponent_key, [])
        ))

        # Run the fight
        try:
            result = run_fight(
                fight.player_warrior, fight.opponent,
                team_a_name=fight.player_team.team_name,
                team_b_name=fight.opponent_team.team_name,
                manager_a_name=fight.player_team.manager_name,
                manager_b_name=fight.opponent_manager,
                is_monster_fight=(fight.fight_type == "monster"),
                fight_type=fight.fight_type,
                pos_a=fight.pos_a,
                pos_b=fight.pos_b,
                challenger_name=fight.challenger_name,
                debug_logger=_dbg_logger,
                bully_info=getattr(fight, "bully_info", None),
                scouting_info={"scouts": _attending_scouts} if _attending_scouts else None,
            )
            # CRITICAL: Attach the result to the fight object so it can be used for the newsletter
            fight.result = result
            # Capture the raw (non-mirrored) narrative for any scouted combatant,
            # for use building that scouting manager's report in STEP 4. Strip
            # both the strategy table and the training summary - a scout watches
            # the fight, not either warrior's tactics or private training results.
            if _player_key in scouted_this_turn or _opponent_key in scouted_this_turn:
                _scout_narrative = _strip_training_block(_strip_strategy_table(result.narrative))
                if _player_key in scouted_this_turn:
                    scout_fight_narratives[_player_key] = _scout_narrative
                if _opponent_key in scouted_this_turn:
                    scout_fight_narratives[_opponent_key] = _scout_narrative
        except Exception as e:
            import traceback
            print(f"  *** ERROR running fight {fight.player_warrior.name} vs {fight.opponent.name}: {e}")
            traceback.print_exc()
            continue

        # Write debug log file if applicable
        if _dbg_logger and _dbg_turn_dir:
            _log_path = os.path.join(
                _dbg_turn_dir,
                f"fight_{fid:05d}_{fight.player_warrior.name}_vs_{fight.opponent.name}.txt"
            )
            try:
                _dbg_logger.write_to_file(_log_path)
            except Exception as _log_err:
                print(f"  DEBUG LOG WARN: {_log_err}")

        # Determine outcomes
        pw_won = result.winner is not None and result.winner.name == fight.player_warrior.name
        killed = result.loser_died and pw_won
        slain = result.loser_died and not pw_won

        # Determine fight type for record
        _champ_name = champ_state.get("name", "") if isinstance(champ_state, dict) else ""
        fight_type_to_record = (
            "champion" if (_champ_name and (
                fight.opponent.name == _champ_name or fight.player_warrior.name == _champ_name
            )) else fight.fight_type
        )

        # Update player warrior stats
        fight.player_warrior.update_popularity(won=pw_won)
        fight.player_warrior.update_recognition(
            won=pw_won,
            killed_opponent=killed,
            self_hp_pct=result.winner_hp_pct if pw_won else result.loser_hp_pct,
            opp_hp_pct=result.loser_hp_pct if pw_won else result.winner_hp_pct,
            self_knockdowns=result.winner_knockdowns if pw_won else result.loser_knockdowns,
            opp_knockdowns=result.loser_knockdowns if pw_won else result.winner_knockdowns,
            self_near_kills=result.winner_near_kills if pw_won else result.loser_near_kills,
            opp_near_kills=result.loser_near_kills if pw_won else result.winner_near_kills,
            minutes_elapsed=result.minutes_elapsed,
            opponent_total_fights=fight.opponent.total_fights,
        )

        # Add fight history for player warrior
        fight.player_warrior.fight_history.append({
            "turn": turn_num,
            "opponent_name": fight.opponent.name,
            "opponent_race": fight.opponent.race.name,
            "opponent_team": fight.opponent_team.team_name,
            "opponent_team_id": fight.opponent_team.team_id,
            "opponent_manager_name": getattr(fight.opponent_team, "manager_name", "") or '',
            "result": "win" if pw_won else "loss",
            "minutes": result.minutes_elapsed,
            "fight_id": fid,
            "warrior_slain": slain,
            "opponent_slain": killed,
            "is_kill": killed,
            "fight_type": fight_type_to_record,
            "primary_weapon": fight.player_warrior.primary_weapon or 'Unknown',
        })

        # Update opponent warrior stats
        opp_won = not pw_won
        opp_killed = result.loser_died and opp_won
        opp_slain = result.loser_died and not opp_won

        fight.opponent.update_popularity(won=opp_won)
        fight.opponent.update_recognition(
            won=opp_won,
            killed_opponent=opp_killed,
            self_hp_pct=result.winner_hp_pct if opp_won else result.loser_hp_pct,
            opp_hp_pct=result.loser_hp_pct if opp_won else result.winner_hp_pct,
            self_knockdowns=result.winner_knockdowns if opp_won else result.loser_knockdowns,
            opp_knockdowns=result.loser_knockdowns if opp_won else result.winner_knockdowns,
            self_near_kills=result.winner_near_kills if opp_won else result.loser_near_kills,
            opp_near_kills=result.loser_near_kills if opp_won else result.winner_near_kills,
            minutes_elapsed=result.minutes_elapsed,
            opponent_total_fights=fight.player_warrior.total_fights,
        )

        # Blood-challenge bullying penalty / underdog favor (challenger side
        # only). Applies regardless of win/loss. Shared with simulation_tool.py
        # so mock-turn testing matches production behavior exactly.
        _bully_event = MM.apply_blood_challenge_bully_effects(fight)
        if _bully_event:
            bully_events.append(_bully_event)
            if _bully_event.get("stripped") and not stripped_champion_name:
                stripped_champion_name = _bully_event["warrior"]

        # Add fight history for opponent warrior (if not NPC)
        if opponent_manager_id and fight.opponent_team.team_id >= 0:
            fight.opponent.fight_history.append({
                "turn": turn_num,
                "opponent_name": fight.player_warrior.name,
                "opponent_race": fight.player_warrior.race.name,
                "opponent_team": fight.player_team.team_name,
                "opponent_team_id": fight.player_team.team_id,
                "opponent_manager_name": getattr(fight.player_team, "manager_name", "") or '',
                "result": "win" if opp_won else "loss",
                "minutes": result.minutes_elapsed,
                "fight_id": fid,
                "warrior_slain": opp_slain,
                "opponent_slain": opp_killed,
                "is_kill": opp_killed,
                "fight_type": fight_type_to_record,
                "weapon_name": fight.opponent.primary_weapon or 'Unknown',
            })

        # Immortality shield: warriors with a pending promotion cannot be
        # permanently killed during their final mortal fight in the normal arena.
        if slain and getattr(fight.player_warrior, "pending_promotion", None):
            print(f"  SHIELD: {fight.player_warrior.name}'s immortality shield absorbed "
                  f"their death. They will be promoted after this turn.")
            slain = False

        # Auto-transcendence: worthy warriors who die transcend to The Dead Grounds
        # instead of dying permanently.  Criteria: 20+ fights and 55%+ win rate.
        if slain:
            _w   = fight.player_warrior
            _tot = _w.wins + _w.losses
            _wr  = _w.wins / _tot if _tot > 0 else 0.0
            if _tot >= 20 and _wr >= 0.55:
                print(f"  TRANSCENDENCE: {_w.name} ({_wr:.1%}, {_tot} fights) "
                      f"transcends to The Dead Grounds.")
                _w.current_arena = "veteran"
                _w.hp            = max(1, getattr(_w, "max_hp", 100))
                _w.recognition   = 0
                transcendence_events.append({
                    "warrior_name": _w.name,
                    "team_name":    fight.player_team.team_name,
                    "team_id":      fight.player_team.team_id,
                    "record":       f"{_w.wins}W/{_w.losses}L/{_w.kills}K",
                    "win_rate":     round(_wr, 4),
                    "total_fights": _tot,
                })
                slain = False

        # Handle deaths
        if slain:
            fight.player_team.kill_warrior(
                fight.player_warrior,
                killed_by=fight.opponent.name,
                killer_fights=fight.opponent.total_fights,
                fight_type=fight_type_to_record
            )
            fight.player_team.auto_upload_enabled = False
            try:
                from save import archive_warrior_history
                archive_warrior_history(fight.player_team.team_name, fight.player_warrior)
                print(f"  Graveyard file written for {fight.player_warrior.name}.")
            except Exception as _ge:
                print(f"  WARNING: Could not write graveyard file: {_ge}")

        # Auto-transcendence for opponent warriors.
        if opp_slain and opponent_manager_id and fight.opponent_team.team_id >= 0:
            _ow  = fight.opponent
            _tot = _ow.wins + _ow.losses
            _wr  = _ow.wins / _tot if _tot > 0 else 0.0
            if _tot >= 20 and _wr >= 0.55:
                print(f"  TRANSCENDENCE: {_ow.name} ({_wr:.1%}, {_tot} fights) "
                      f"transcends to The Dead Grounds.")
                _ow.current_arena = "veteran"
                _ow.hp            = max(1, getattr(_ow, "max_hp", 100))
                _ow.recognition   = 0
                transcendence_events.append({
                    "warrior_name": _ow.name,
                    "team_name":    fight.opponent_team.team_name,
                    "team_id":      fight.opponent_team.team_id,
                    "record":       f"{_ow.wins}W/{_ow.losses}L/{_ow.kills}K",
                    "win_rate":     round(_wr, 4),
                    "total_fights": _tot,
                })
                opp_slain = False

        if opp_slain and opponent_manager_id and fight.opponent_team.team_id >= 0:
            fight.opponent_team.kill_warrior(
                fight.opponent,
                killed_by=fight.player_warrior.name,
                killer_fights=fight.player_warrior.total_fights,
                fight_type=fight_type_to_record
            )
            try:
                from save import archive_warrior_history
                archive_warrior_history(fight.opponent_team.team_name, fight.opponent)
                print(f"  Graveyard file written for opponent {fight.opponent.name}.")
            except Exception as _ge:
                print(f"  WARNING: Could not write graveyard file for opponent: {_ge}")

        # Monster ascension
        ascended = False
        if killed and fight.fight_type == "monster":
            fight.player_warrior.monster_kills = getattr(fight.player_warrior, "monster_kills", 0) + 1
            fight.player_warrior.ascended_to_monster = True
            from matchmaking import _absorb_into_monsters
            _absorb_into_monsters(fight.player_warrior, fight.player_team, fight.opponent, fight.opponent_team)
            ascended = True
            print(f"  !!! {fight.player_warrior.name} has SLAIN a monster and joins The Monsters! !!!")

        # Retirement — processed AFTER the warrior's fight this turn (their final bout),
        # so the warrior always fights before being archived and replaced.
        if getattr(fight.player_warrior, "want_retire", False) and not slain:
            if not fight.player_warrior.can_retire:
                print(f"  RETIRE REJECTED: {fight.player_warrior.name} only has "
                      f"{fight.player_warrior.total_fights} fights (need 50).")
                fight.player_warrior.want_retire = False
            else:
                retiring_name = fight.player_warrior.name
                retiring_stats = (fight.player_warrior.wins, fight.player_warrior.losses, fight.player_warrior.kills)
                retired_ok = fight.player_team.retire_warrior(fight.player_warrior)
                if retired_ok:
                    print(f"  RETIREMENT: {retiring_name} retires after their final "
                          f"fight this turn. Replacement slot open for {fight.player_team.team_name}.")
                    retirements_this_turn.append({
                        "name": retiring_name,
                        "w": retiring_stats[0], "l": retiring_stats[1], "k": retiring_stats[2],
                        "team": fight.player_team.team_name,
                        "manager": fight.player_team.manager_name,
                    })
                fight.player_warrior.want_retire = False

        if (opponent_manager_id and getattr(fight.opponent, "want_retire", False)
                and not opp_slain and fight.opponent_team.team_id >= 0):
            if not fight.opponent.can_retire:
                print(f"  RETIRE REJECTED: {fight.opponent.name} only has "
                      f"{fight.opponent.total_fights} fights (need 50).")
                fight.opponent.want_retire = False
            else:
                retiring_name = fight.opponent.name
                retiring_stats = (fight.opponent.wins, fight.opponent.losses, fight.opponent.kills)
                retired_ok = fight.opponent_team.retire_warrior(fight.opponent)
                if retired_ok:
                    print(f"  RETIREMENT: {retiring_name} retires after their final "
                          f"fight this turn. Replacement slot open for {fight.opponent_team.team_name}.")
                    retirements_this_turn.append({
                        "name": retiring_name,
                        "w": retiring_stats[0], "l": retiring_stats[1], "k": retiring_stats[2],
                        "team": fight.opponent_team.team_name,
                        "manager": fight.opponent_team.manager_name,
                    })
                fight.opponent.want_retire = False

        # Blood challenge resolution — always consumes the challenge (win or loss)
        if fight.fight_type == "blood_challenge":
            bc_info = getattr(fight, "_blood_challenge_info", {})
            if bc_info:
                bc_target_name = bc_info.get("target_name")
                bc_dead_name = bc_info.get("dead_warrior_name")
                removed = fight.player_team.remove_blood_challenge(bc_target_name, bc_dead_name)
                if removed:
                    if pw_won:
                        print(f"  !!! BLOOD CHALLENGE AVENGED: {fight.player_warrior.name} has avenged {bc_dead_name}! !!!")
                    else:
                        print(f"  The blood challenge for {bc_dead_name} has been fought - the fallen remain unavenged.")

        # Build player bout data
        player_bout = {
            "warrior_name": fight.player_warrior.name,
            "opponent_name": fight.opponent.name,
            "opponent_race": fight.opponent.race.name,
            "opponent_team": fight.opponent_team.team_name,
            "opponent_team_id": fight.opponent_team.team_id,
            "opponent_manager": fight.opponent_manager,
            "fight_type": fight_type_to_record,
            "result": "WIN" if pw_won else "LOSS",
            "minutes": result.minutes_elapsed,
            "fight_id": fid,
            "warrior_slain": slain,
            "opponent_slain": killed,
            "ascension": ascended,
            "wins": fight.player_warrior.wins,
            "losses": fight.player_warrior.losses,
            "kills": fight.player_warrior.kills,
            "opponent_wins": fight.opponent.wins,
            "opponent_losses": fight.opponent.losses,
            "opponent_kills": fight.opponent.kills,
            "training": result.training_results.get("warrior_a", []),
            "challenger_name": fight.challenger_name,
        }

        # Store result for player manager
        if player_manager_id:
            if player_manager_id not in all_results:
                all_results[player_manager_id] = {
                    "bouts": [],
                    "team": fight.player_team.to_dict(),
                    "manager_name": fight.player_team.manager_name,
                    "team_name": fight.player_team.team_name,
                    "team_id": fight.player_team.team_id,
                    "fight_logs": {}
                }
            all_results[player_manager_id]["bouts"].append(player_bout)
            all_results[player_manager_id]["fight_logs"][str(fid)] = result.narrative

        # Store result for opponent manager (if not NPC)
        if opponent_manager_id and fight.opponent_team.team_id >= 0:
            # DEBUG: Track problematic managers
            if opponent_manager_id in ['22', 22, '24', 24, '26', 26]:
                print(f"    [STORE] Storing opponent result for manager {opponent_manager_id}")
            opponent_bout = {
                "warrior_name": fight.opponent.name,
                "opponent_name": fight.player_warrior.name,
                "opponent_race": fight.player_warrior.race.name,
                "opponent_team": fight.player_team.team_name,
                "opponent_team_id": fight.player_team.team_id,
                "opponent_manager": fight.player_team.manager_name,
                "fight_type": fight_type_to_record,
                "result": "WIN" if opp_won else "LOSS",
                "minutes": result.minutes_elapsed,
                "fight_id": fid,
                "warrior_slain": opp_slain,
                "opponent_slain": opp_killed,
                "ascension": False,
                "wins": fight.opponent.wins,
                "losses": fight.opponent.losses,
                "kills": fight.opponent.kills,
                "opponent_wins": fight.player_warrior.wins,
                "opponent_losses": fight.player_warrior.losses,
                "opponent_kills": fight.player_warrior.kills,
                "training": result.training_results.get("warrior_b", []),
                "challenger_name": fight.challenger_name,
            }
            if opponent_manager_id not in all_results:
                all_results[opponent_manager_id] = {
                    "bouts": [],
                    "team": fight.opponent_team.to_dict(),
                    "manager_name": fight.opponent_team.manager_name,
                    "team_name": fight.opponent_team.team_name,
                    "team_id": fight.opponent_team.team_id,
                    "fight_logs": {}
                }
            all_results[opponent_manager_id]["bouts"].append(opponent_bout)
            all_results[opponent_manager_id]["fight_logs"][str(fid)] = _make_mirror_narrative(
                result.narrative,
                result.training_results,
                fight.player_warrior.name,
                fight.opponent.name,
                fight.player_warrior,
                fight.opponent,
            )
        elif opponent_manager_id is None and fight.opponent_team.team_id >= 0:
            # DEBUG: Track when opponent_manager_id is None for player teams
            if fight.opponent_team.team_id >= 0:
                print(f"    [SKIP] opponent_manager_id is None for {fight.opponent.name} (team_id={fight.opponent_team.team_id})")

        # Print result
        if result.winner:
            outcome = "WON" if result.winner is fight.player_warrior else "LOST"
            print(f"  Result: {fight.player_warrior.name} {outcome} in {result.minutes_elapsed} minutes")
        else:
            print(f"  Result: DRAW after {result.minutes_elapsed} minutes")

    # CRITICAL: Restore original backup_weapon values before saving teams
    # Combat clears backup_weapon if used, but we want to preserve the original
    for team in all_player_teams:
        team_id = team.team_id
        if team_id in backup_weapon_backup:
            for w in team.active_warriors:
                if w and w.name in backup_weapon_backup[team_id]:
                    w.backup_weapon = backup_weapon_backup[team_id][w.name]

    # Execute any pending promotions (warriors who fought with the immortality
    # shield this turn) — must happen before teams are saved so the updated
    # current_arena and cleared pending_promotion are persisted.
    promotion_events = _execute_promotions(all_player_teams, turn_num)

    # Check eligibility for warriors who may have crossed the threshold this turn;
    # their pending_promotion flag will be saved now and the shield will activate
    # for their final mortal fight next turn.
    newly_eligible = _check_promotion_eligibility(all_player_teams, cfg)

    # ===================================================================
    # STEP 4: Save all results and update standings
    # ===================================================================
    print(f"\n  Saving results for {len(all_results)} managers...")
    from save import save_team, get_manager_scouting
    from scout_report import generate_scout_report
    _scout_mgrs = _load_managers()
    _scout_reports_done = {}  # real manager_id -> scout_reports, computed once per manager even if they have multiple teams

    for manager_id, res in all_results.items():
        # REFRESH TEAM STATE: The res["team"] dict captured during the execution loop
        # was a premature snapshot. We now use the final updated state from memory.
        if manager_id in team_map:
            team = team_map[manager_id]
            # Update persistent metadata so inactive teams remain eligible for
            # newsletter retention across subsequent turns.
            team.last_turn_ran = turn_num
            if not hasattr(team, "turn_history"):
                team.turn_history = []
            team.turn_history = [
                e for e in team.turn_history
                if e.get("turn") != turn_num
            ]
            team.turn_history.append({
                "turn": turn_num,
                "w": sum(1 for b in res["bouts"] if b.get("result") == "WIN"),
                "l": sum(1 for b in res["bouts"] if b.get("result") == "LOSS"),
                "k": sum(1 for b in res["bouts"] if b.get("opponent_slain")),
            })
            # Clear challenges and reset challenge strategy mode now that all fights are done.
            team.clear_challenges(reset_strategy_mode=True)
            # Decrement and expire any remaining blood challenges for this turn
            team.decrement_blood_challenge_turns()
            # Check for expired BCs before removing them
            for bc in team.blood_challenges:
                if (bc.get("status") == "active" and
                    bc.get("killer_turns_fought", 0) >= 3):
                    print(f"  Blood challenge for {bc.get('dead_warrior_name')} against {bc.get('target_name')} "
                          f"has EXPIRED - killer did not get avenged after participating in 3 fights.")
            # Remove BCs that have been avenged, expired, or where killer fought 3+ times
            team.blood_challenges = [
                bc for bc in team.blood_challenges
                if (bc.get("status") == "active" and
                    bc.get("killer_turns_fought", 0) < 3)
            ]
            save_team(team)
            res["team"] = team.to_dict()

        # Update turn_history in res["team"] - must happen for ALL managers, not just team_map
        # This ensures nl_teams has current turn_history when building the newsletter
        if "turn_history" not in res["team"]:
            res["team"]["turn_history"] = []
        res["team"]["turn_history"] = [
            e for e in res["team"]["turn_history"]
            if e.get("turn") != turn_num
        ]
        res["team"]["turn_history"].append({
            "turn": turn_num,
            "w": sum(1 for b in res["bouts"] if b.get("result") == "WIN"),
            "l": sum(1 for b in res["bouts"] if b.get("result") == "LOSS"),
            "k": sum(1 for b in res["bouts"] if b.get("opponent_slain")),
        })

        # Prepare team for client response (res["team"] now has updated turn_history)
        team_for_client = res["team"]

        # Create server storage version (strip fight_history)
        team_slim = dict(team_for_client)
        team_slim["warriors"] = []
        for wd in team_for_client.get("warriors", []):
            if not wd:
                team_slim["warriors"].append(None)
                continue
            ws = dict(wd)
            ws.pop("fight_history", None)
            team_slim["warriors"].append(ws)
        team_slim["archived_warriors"] = team_for_client.get("archived_warriors", [])

        # Resolve this manager's scout reports for the turn that just processed.
        # Confirmed selections were locked in before the turn ran; the report
        # reflects each target's state AFTER this turn's fights/training, per
        # the scouting rework - see docs in the scouting plan. manager_id here may
        # be a composite "{mid}_team{team_id}" key (see _load_uploads(), which keys
        # uploads that way so a manager with multiple teams gets separate entries) -
        # scouting selections are keyed by the plain manager_id, so strip it back off.
        real_manager_id = manager_id.split("_team")[0] if "_team" in manager_id else manager_id
        if real_manager_id in _scout_reports_done:
            scout_reports = _scout_reports_done[real_manager_id]
        else:
            scout_reports = []
        for sel in ([] if real_manager_id in _scout_reports_done else get_manager_scouting(real_manager_id, turn_num)):
            if not sel.get("confirmed"):
                continue
            t_name      = sel.get("warrior_name", "")
            t_team_id   = sel.get("team_id", 0)
            t_team_name = sel.get("team_name", "")
            scout_name, scout_type = _get_or_assign_scout_persona(real_manager_id, _scout_mgrs)

            target_team = team_by_id.get(t_team_id)
            target_w    = target_team.warrior_by_name(t_name) if target_team else None
            fh          = (target_w.fight_history or []) if target_w else []
            last_entry  = fh[-1] if fh else None
            fought_this_turn = bool(target_w and last_entry and last_entry.get("turn") == turn_num)

            if not fought_this_turn:
                # Target died/retired/was swapped off the roster, or their team
                # didn't upload this turn - nothing for the scout to report.
                from scout_report import _sat_out_message
                report_text = _sat_out_message(t_name, scout_type)
                scout_reports.append({
                    "warrior_name": t_name, "team_name": t_team_name,
                    "scout_name": scout_name, "scout_type": scout_type,
                    "scout_report": report_text,
                })
                continue

            fight_narrative = scout_fight_narratives.get((t_team_id, t_name), "")
            report_text = generate_scout_report(
                target_w, last_entry, t_team_name,
                scout_name=scout_name, scout_type=scout_type,
                fight_narrative=fight_narrative,
                is_debut_fight=(len(fh) == 1),
            )
            scout_reports.append({
                "warrior_name"    : target_w.name,
                "team_name"       : t_team_name,
                "wins"            : target_w.wins,
                "losses"          : target_w.losses,
                "kills"           : target_w.kills,
                "max_hp"          : target_w.max_hp,
                "height_in"       : target_w.height_in,
                "weight_lbs"      : target_w.weight_lbs,
                "total_fights"    : target_w.total_fights,
                "armor"           : target_w.armor or "None",
                "helm"            : target_w.helm or "None",
                "primary_weapon"  : target_w.primary_weapon or "Open Hand",
                "secondary_weapon": target_w.secondary_weapon or "Open Hand",
                "backup_weapon"   : target_w.backup_weapon,
                "scout_name"      : scout_name,
                "scout_type"      : scout_type,
                "scout_report"    : report_text,
            })

        _scout_reports_done[real_manager_id] = scout_reports

        mgr_res = {
            "turn": turn_num,
            "manager_name": res["manager_name"],
            "team_id": res["team_id"],
            "team_name": res["team_name"],
            "bouts": res["bouts"],
            "team": team_for_client,
            "fight_logs": res["fight_logs"],
            "scout_reports": scout_reports,
        }
        _save_result(turn_num, manager_id, mgr_res)

    # Update standings
    try:
        standings = _load_standings()
        for mid, res in all_results.items():
            if mid not in standings:
                standings[mid] = {
                    "manager_name": res["manager_name"],
                    "turns_played": 0,
                    "warriors": {},
                    "is_ai": mid.startswith("ai_"),
                    "turns_counted": []
                }
            e = standings[mid]
            if "turns_counted" not in e:
                e["turns_counted"] = []
            if turn_num not in e["turns_counted"]:
                e["turns_played"] += 1
                e["turns_counted"].append(turn_num)
            
            all_fighters = (res["team"].get("warriors", []) + res["team"].get("archived_warriors", []))
            for wd in all_fighters:
                if not wd:
                    continue
                wn  = wd["name"]
                wid = wd.get("warrior_id")
                # Key by warrior_id when available so same-name warriors don't collide
                standings_key = str(wid) if wid else wn
                if standings_key not in e["warriors"]:
                    e["warriors"][standings_key] = {"wins": 0, "losses": 0, "kills": 0, "fights": 0}
                ws = e["warriors"][standings_key]
                ws["name"] = wn
                ws["warrior_id"] = wid
                ws["race"] = wd.get("race")
                ws["gender"] = wd.get("gender")
                ws["wins"] = wd.get("wins", 0)
                ws["losses"] = wd.get("losses", 0)
                ws["kills"] = wd.get("kills", 0)
                ws["fights"] = wd.get("total_fights", 0)
        _save_standings(standings)
    except Exception as _se:
        import traceback
        traceback.print_exc()
        print(f"  WARNING: standings update failed: {_se}")

    # Evolve AI teams
    try:
        from ai_league_teams import evolve_ai_teams
        ai_results = {mid: r for mid, r in all_results.items() if mid.startswith("ai_")}
        if ai_teams:
            evolve_ai_teams(ai_teams, ai_results)
            print(f"  AI teams evolved and saved ({len(ai_results)} teams processed).")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  WARNING: AI team evolution failed: {e}")

    # Generate arena statistics HTML report
    try:
        from arena_stats import generate_arena_stats
        _reports_dir = os.path.join(LEAGUE_DIR, "reports")
        generate_arena_stats(uploads, team_map, turn_num, _reports_dir)
    except Exception as _rpt_err:
        print(f"  WARNING: arena_stats report failed: {_rpt_err}")

    # Generate team roster HTML report
    try:
        from team_roster import generate_team_roster_html, write_team_roster
        _reports_dir = os.path.join(LEAGUE_DIR, "reports")
        _roster_html = generate_team_roster_html(uploads, team_map, turn_num)
        write_team_roster(_roster_html, _reports_dir)
    except Exception as _rpt_err:
        print(f"  WARNING: team_roster report failed: {_rpt_err}")

    # ===================================================================
    # STEP 5: Finalize config and auto-carry
    # ===================================================================
    with _lock:
        in_memory_fight_counter = fight_counter
        cfg = _load_config()
        cfg["fight_counter"] = max(cfg.get("fight_counter", 0), in_memory_fight_counter)
        if not rerun_turn:
            cfg["turn_state"] = "results_ready"
            cfg["current_turn"] = turn_num + 1
        else:
            cfg["turn_state"] = "results_ready"
            cfg["rerun_count"] = cfg.get("rerun_count", 0) + 1
            cfg["rerun_turn"] = rerun_turn
        
        for k, start_val in _turn_start_flags.items():
            if k not in cfg:
                cfg[k] = start_val
        
        _save_config(cfg)
        _turn_progress = {"running": False, "done": len(uploads), "total": len(uploads),
                          "message": f"Turn {turn_num} complete - {len(all_results)} managers."}

        # Auto-carry for next turn
        _next_turn = cfg["current_turn"]
        _auto_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        _mgrs_current = _load_managers()
        for _key, _res in all_results.items():
            if _key.startswith("ai_"):
                continue
            _team_dict = _res.get("team") or {}
            _warriors = _team_dict.get("warriors") or []
            if len(_warriors) != 5:
                continue
            if any((w is None) or w.get("is_dead") or w.get("is_retired") for w in _warriors):
                continue
            if not _team_dict.get("auto_upload_enabled", True):
                continue
            _real_mid = _key.split("_team")[0] if "_team" in _key else _key
            _tid = _res.get("team_id") or _team_dict.get("team_id", "")
            try:
                _int_tid = int(_tid)
                _mgr_tids = [int(t) for t in _mgrs_current.get(_real_mid, {}).get("team_ids", []) if str(t).isdigit()]
            except (ValueError, TypeError):
                _mgr_tids = []
                _int_tid = None
            if _int_tid not in _mgr_tids:
                continue
            _fname = (f"upload_{_real_mid}_team{_tid}.json" if _tid else f"upload_{_real_mid}.json")
            _target = os.path.join(_turn_dir(_next_turn), _fname)
            _existing = _load_json(_target, None)
            if _existing and not _existing.get("auto_uploaded"):
                continue
            _save_upload(_next_turn, _real_mid, {
                "manager_id": _real_mid,
                "manager_name": _res.get("manager_name", ""),
                "team_id": _tid,
                "team": _team_dict,
                "uploaded_at": f"{_auto_ts} (auto-carry)",
                "auto_upload_enabled": True,
                "auto_uploaded": True,
            })

    # ===================================================================
    # STEP 6: Generate newsletter
    # ===================================================================
    newsletter_text = ""
    try:
        from newsletter import generate_newsletter, _update_champion, _is_npc_team
        from save import save_champion_state, load_all_teams
        import datetime as _dt

        # Build team list for newsletter
        nl_teams = []
        team_ids = set()
        for mid, res in all_results.items():
            if mid.startswith("ai_"):
                continue
            try:
                t = Team.from_dict(res["team"])
                nl_teams.append(t)
                team_ids.add(getattr(t, "team_id", 0))
            except Exception:
                pass

        # Add AI teams only if enabled
        if cfg.get("ai_teams_enabled", True):
            try:
                from ai_league_teams import load_ai_teams
                for at in (load_ai_teams() or []):
                    try:
                        t = Team.from_dict(at)
                        if getattr(t, "team_id", 0) not in team_ids:
                            nl_teams.append(t)
                            team_ids.add(getattr(t, "team_id", 0))
                    except Exception:
                        pass
            except Exception:
                pass

        # Keep recently active saved teams for up to 3 turns of inactivity.
        try:
            for saved_team in load_all_teams():
                saved_id = getattr(saved_team, "team_id", 0)
                if saved_id in team_ids:
                    continue
                if _is_npc_team(saved_team):
                    continue

                last_run = getattr(saved_team, "last_turn_ran", 0)
                if last_run > 0 and last_run >= turn_num - 3:
                    nl_teams.append(saved_team)
                    team_ids.add(saved_id)
                    continue

                hist = getattr(saved_team, "turn_history", [])
                if not hist:
                    continue
                last_turn = max((entry.get("turn", 0) for entry in hist), default=0)
                if last_turn >= turn_num - 3:
                    nl_teams.append(saved_team)
                    team_ids.add(saved_id)
        except Exception:
            pass

        # Collect deaths
        # Load deaths from saved result files (authoritative source)
        deaths_nl = _load_deaths_from_results(turn_num)

        # Retirements captured live during the fight loop above (turn-scoped, no persisted
        # flag needed - avoids re-showing the same retiree in later turns' newsletters)
        retirements_nl = retirements_this_turn

        # Use the actual global_card for the newsletter instead of building a fake one.
        # This ensures each physical fight is listed exactly once and has correct statistics.
        fake_card = [f for f in global_card if f.result is not None]

        # Update champion
        champ_state = load_champion_state()
        _champ_beaten_by = None
        _champ_beaten_by_wid = None
        _champ_beaten_team = None
        _champ_beaten_team_id = 0
        _cur_champ = champ_state.get("name", "")
        _cur_champ_tid = champ_state.get("team_id", 0)
        _cur_champ_wid = champ_state.get("warrior_id")
        if _cur_champ:
            for _bout in fake_card:
                _pw_won = _bout.result.winner.name == _bout.player_warrior.name
                _winner = _bout.player_warrior if _pw_won else _bout.opponent
                _loser  = _bout.opponent if _pw_won else _bout.player_warrior
                _loser_team = _bout.opponent_team if _pw_won else _bout.player_team
                _loser_wid = getattr(_loser, "warrior_id", None)
                # Prefer warrior_id match; always also try name+team_id as a
                # fallback (not just when the id is totally absent) so a
                # stale/mismatched id can't silently hide a real title loss
                _id_match   = bool(_cur_champ_wid and _loser_wid and _cur_champ_wid == _loser_wid)
                _name_match = (_loser.name == _cur_champ and _loser_team.team_id == _cur_champ_tid)
                _loser_is_champ = _id_match or _name_match
                if _loser_is_champ:
                    # Only allow player warriors to claim the championship, not NPCs/peasants
                    _winner_team = _bout.player_team if _pw_won else _bout.opponent_team
                    _winner_team_name = _winner_team.team_name if hasattr(_winner_team, "team_name") else _winner_team.get("team_name", "")
                    if _winner_team_name not in ("The Monsters", "The Peasants"):
                        _champ_beaten_by = _winner.name
                        _champ_beaten_by_wid = getattr(_winner, "warrior_id", None)
                        _champ_beaten_team = _bout.player_team.team_name if _pw_won else _bout.opponent_team.team_name
                        _champ_beaten_team_id = _bout.player_team.team_id if _pw_won else _bout.opponent_team.team_id
                    break

        prev_champion_name = champ_state.get("name", "")
        prev_champion_state = champ_state.copy()  # Save the BEFORE-fight champion state
        champ_state, is_new_champion = _update_champion(
            nl_teams, champ_state, deaths_nl,
            champion_beaten_by=_champ_beaten_by,
            champion_beaten_by_wid=_champ_beaten_by_wid,
            champion_beaten_team=_champ_beaten_team,
            champion_beaten_team_id=_champ_beaten_team_id,
            prev_champion_name=prev_champion_name,
            card=fake_card,
            ineligible_name=stripped_champion_name,
        )
        save_champion_state(champ_state)

        # Determine which champion state to use for the fights section:
        # - If champion was BEATEN this turn: use BEFORE state (to show correct narrative)
        # - If champion didn't fight and lost title to recognition: use AFTER state (no change needed)
        champion_state_for_fights = prev_champion_state if _champ_beaten_by else champ_state

        # Tag champion fights: both for NEW champions (crowned this turn) and EXISTING champions (already champion at start)
        _new_champ = champ_state.get("name", "")
        _champs_to_tag = set()

        # Add new champion (if one was crowned this turn)
        if _new_champ and _new_champ != prev_champion_name:
            _champs_to_tag.add(_new_champ)

        # Add existing champion (if they were already champion and fought)
        if prev_champion_name:
            _champs_to_tag.add(prev_champion_name)

        # Tag all fights involving any champion
        if _champs_to_tag:
            for _mid, _res in all_results.items():
                _updated = False
                for _bout in _res.get("bouts", []):
                    if (_bout.get("fight_type") != "champion" and (
                        _bout.get("warrior_name") in _champs_to_tag or
                        _bout.get("opponent_name") in _champs_to_tag
                    )):
                        _bout["fight_type"] = "champion"
                        _updated = True
                if _updated:
                    # Patch the saved result file with corrected fight types
                    _team_id = _res.get("team_id", "")
                    _fname = (f"result_{_mid}_team{_team_id}.json" if _team_id
                              else f"result_{_mid}.json")
                    _fpath = os.path.join(_turn_dir(turn_num), _fname)
                    if os.path.exists(_fpath):
                        try:
                            _fdata = _load_json(_fpath, None)
                            if _fdata:
                                _fdata["bouts"] = _res["bouts"]
                                _save_json(_fpath, _fdata)
                        except Exception as _pe:
                            print(f"  WARNING: could not patch champion fight_type in {_fname}: {_pe}")
            # Also fix fight_history on the warriors in memory
            for _team in team_map.values():
                for _w in _team.active_warriors:
                    for _h in (_w.fight_history or []):
                        if (_h.get("turn") == turn_num and
                                _h.get("fight_type") != "champion" and (
                                _h.get("opponent_name") in _champs_to_tag or
                                _w.name in _champs_to_tag)):
                            _h["fight_type"] = "champion"
                save_team(_team)

            # Re-save result files with the patched fight_type
            for _mid, _res in all_results.items():
                if _mid in team_map:
                    _res["team"] = team_map[_mid].to_dict()
                    _fname = (f"result_{_mid}_team{_res.get('team_id', '')}.json" if _res.get('team_id')
                              else f"result_{_mid}.json")
                    _fpath = os.path.join(_turn_dir(turn_num), _fname)
                    if os.path.exists(_fpath):
                        try:
                            _fdata = _load_json(_fpath, None)
                            if _fdata:
                                _fdata["team"] = _res["team"]
                                _save_json(_fpath, _fdata)
                        except Exception as _pe:
                            print(f"  WARNING: could not update result file {_fname}: {_pe}")

        date_str = _dt.date.today().strftime("%m/%d/%Y")
        newsletter_text = generate_newsletter(
            turn_num=turn_num,
            card=fake_card,
            teams=nl_teams,
            deaths=deaths_nl,
            champion_state=champ_state,
            processed_date=date_str,
            is_new_champion=is_new_champion,
            champion_state_before=champion_state_for_fights,  # Use correct state for fights identification
            prev_champion_state=prev_champion_state,  # For detecting newly-crowned champions
            bully_events=bully_events,
            retirements=retirements_nl,
            promotions=promotion_events,
            transcendences=transcendence_events,
        )
        nl_path = os.path.join(_turn_dir(turn_num), "newsletter.txt")
        with open(nl_path, "w", encoding="utf-8") as _f:
            _f.write(newsletter_text)
        print(f"  Newsletter written: {nl_path}")

        # Also save to newsletters folder for redownload feature (turn_XXX.txt format)
        try:
            nl_folder = os.path.join(LEAGUE_DIR, "newsletters")
            os.makedirs(nl_folder, exist_ok=True)
            nl_redownload_path = os.path.join(nl_folder, f"turn_{turn_num:03d}.txt")
            with open(nl_redownload_path, "w", encoding="utf-8") as _f:
                _f.write(newsletter_text)
            print(f"  Newsletter (redownload copy) written: {nl_redownload_path}")
        except Exception as _e:
            print(f"  WARNING: Failed to save newsletter redownload copy: {_e}")
    except Exception as _e:
        import traceback
        traceback.print_exc()
        print(f"  WARNING: newsletter generation failed: {_e}")

    total_fights = sum(len(r["bouts"]) for r in all_results.values())
    print(f"\n  Turn {turn_num} complete - {len(all_results)} manager(s), {total_fights} fight(s)")
    print(f"  Expected fights: {total_warriors} warriors -> {total_warriors} fights")
    if total_fights == total_warriors:
        print("  ✓ PERFECT: Each warrior fought exactly once!")
    else:
        print(f"  ⚠ WARNING: Fight count mismatch! {total_fights} fights vs {total_warriors} warriors")

    return {"success": True, "turn_number": turn_num,
            "managers": len(all_results), "fights": total_fights,
            "newsletter": newsletter_text}
def _immortal_team_dir(arena: str) -> str:
    """Return path to the arena-specific team snapshot directory."""
    return os.path.join(BASE_DIR, "saves", arena, "teams")


def _immortal_upload_dir(arena: str) -> str:
    """Return path to the arena-specific uploads directory."""
    return os.path.join(BASE_DIR, "saves", arena, "uploads")


def _save_immortal_team(arena: str, team_dict: dict):
    """Write an arena-specific team snapshot to saves/{arena}/teams/team_XXXX.json.

    Only writes warriors that belong to this arena (is_dead=False, current_arena=arena).
    This file is the source of truth for immortal turns — normal-arena uploads never
    touch it, eliminating cross-arena contamination.
    """
    d = _immortal_team_dir(arena)
    os.makedirs(d, exist_ok=True)
    tid = team_dict.get("team_id", 0)

    # Keep only warriors relevant to this arena
    snapshot = {k: v for k, v in team_dict.items()
                if k not in ("warriors", "archived_warriors")}
    snapshot["warriors"] = [
        w for w in (team_dict.get("warriors") or [])
        if isinstance(w, dict)
        and not w.get("is_dead", False)
        and (w.get("current_arena") or "normal") == arena
    ]
    snapshot["archived_warriors"] = [
        w for w in (team_dict.get("archived_warriors") or [])
        if isinstance(w, dict)
        and not w.get("is_dead", True)
        and (w.get("current_arena") or "normal") == arena
    ]

    fp = os.path.join(d, f"team_{tid:04d}.json")
    with open(fp, "w", encoding="utf-8") as _f:
        json.dump(snapshot, _f, indent=2)
    return fp


def _load_immortal_teams(arena: str) -> list:
    """Load all team dicts from saves/{arena}/teams/. Returns list of dicts."""
    d = _immortal_team_dir(arena)
    if not os.path.isdir(d):
        return []
    teams = []
    for fn in sorted(os.listdir(d)):
        if not (fn.startswith("team_") and fn.endswith(".json")):
            continue
        fp = os.path.join(d, fn)
        try:
            with open(fp, encoding="utf-8") as _f:
                data = json.load(_f)
            teams.append(data)
        except Exception as _e:
            print(f"  WARNING: could not load immortal team {fp}: {_e}")
    return teams


def _load_immortal_uploads(arena: str) -> dict:
    """Load uploaded team dicts from saves/{arena}/uploads/. Returns {team_id: dict}."""
    d = _immortal_upload_dir(arena)
    if not os.path.isdir(d):
        return {}
    uploads = {}
    for fn in sorted(os.listdir(d)):
        if not (fn.startswith("team_") and fn.endswith(".json")):
            continue
        fp = os.path.join(d, fn)
        try:
            with open(fp, encoding="utf-8") as _f:
                data = json.load(_f)
            tid = data.get("team_id")
            if tid is not None:
                uploads[int(tid)] = data
        except Exception as _e:
            print(f"  WARNING: could not load immortal upload {fp}: {_e}")
    return uploads


def _migrate_immortal_teams_once():
    """Startup migration: seed arena-specific team folders and repair stuck warriors.

    'Stuck' warriors have is_dead=True but current_arena=elite/veteran — they were
    resurrected server-side but then a normal-arena upload reverted is_dead to True,
    making them invisible in both the arena tree and the Manage Promotions screen.
    This repairs them (sets is_dead=False) and seeds them into the arena folder.

    Warriors that are already correctly seeded (is_dead=False) are also included.
    Once each arena folder is populated, the migration is idempotent for that arena.
    """
    from save import load_all_teams as _mlat, save_team as _mst
    try:
        _all_teams = _mlat()
    except Exception as _me:
        print(f"  [migrate] Could not load teams: {_me}")
        return

    for _arena in ("elite", "veteran"):
        _tdir = _immortal_team_dir(_arena)
        _already_seeded = os.path.isdir(_tdir) and any(
            fn.endswith(".json") for fn in os.listdir(_tdir)
        )

        _repaired = 0
        _seeded   = 0

        for _t in _all_teams:
            _td = _t.to_dict()
            _changed = False

            # Repair stuck archived warriors: is_dead=True but current_arena=this arena
            for _aw in (_td.get("archived_warriors") or []):
                if not isinstance(_aw, dict):
                    continue
                if (_aw.get("current_arena") or "normal") != _arena:
                    continue
                if _aw.get("is_dead", True):
                    # Resurrect: this warrior was intended for the immortal arena
                    _aw["is_dead"]  = False
                    _aw["hp"]       = max(1, int(_aw.get("max_hp") or _aw.get("hp") or 100))
                    _aw.setdefault("recognition", 0)
                    _changed = True
                    _repaired += 1
                    print(f"  [migrate] Repaired {_aw['name']} "
                          f"({_t.team_name}) → {_arena}")

            if _changed:
                # Write corrected data back to the main team file
                try:
                    _fixed_team = __import__("team").Team.from_dict(_td)
                    _mst(_fixed_team)
                except Exception as _fe:
                    print(f"  [migrate] Could not save repaired team "
                          f"{_t.team_id}: {_fe}")

            if _already_seeded and not _changed:
                continue

            # Seed / re-seed the arena-specific file for teams with arena warriors
            _has_arena = (
                any((w.get("current_arena") or "normal") == _arena
                    for w in (_td.get("warriors") or []) if isinstance(w, dict))
                or
                any((w.get("current_arena") or "normal") == _arena
                    and not w.get("is_dead", True)
                    for w in (_td.get("archived_warriors") or []) if isinstance(w, dict))
            )
            if _has_arena:
                _save_immortal_team(_arena, _td)
                _seeded += 1

        if _repaired:
            print(f"  [migrate] Repaired {_repaired} stuck warrior(s) for {_arena}")
        if _seeded:
            print(f"  [migrate] Seeded/updated {_seeded} team(s) in saves/{_arena}/teams/")


def _run_immortal_turn(arena: str, request_password: str) -> dict:
    """Run one turn for The Elite Spire ('elite') or The Dead Grounds ('veteran') arena.

    Each arena has its own saves/{arena}/teams/ folder that is the sole source of
    truth for warriors in that arena. Normal-arena uploads never touch these files,
    preventing cross-arena contamination.
    Results go to saves/{arena}/turn_{N:04d}/.
    """
    if arena not in ("elite", "veteran"):
        return {"success": False, "error": f"Unknown immortal arena: {arena}"}

    # --- Auth (reuse normal arena password) ---
    cfg = _load_config()
    if not _check_host_pw(cfg, request_password):
        return {"success": False, "error": "Not authorised."}

    # --- Load arena config ---
    arena_dir      = os.path.join(BASE_DIR, "saves", arena)
    arena_cfg_path = os.path.join(arena_dir, "config.json")
    if not os.path.exists(arena_cfg_path):
        return {"success": False, "error": f"Arena '{arena}' not initialised. Run migrate_phase1.py first."}

    with _lock:
        with open(arena_cfg_path, encoding="utf-8") as _f:
            arena_cfg = json.load(_f)
        if arena_cfg.get("turn_state") == "processing":
            return {"success": False, "error": f"{arena} turn is already running."}
        arena_cfg["turn_state"] = "processing"
        with open(arena_cfg_path, "w", encoding="utf-8") as _f:
            json.dump(arena_cfg, _f, indent=2)

    turn_num = arena_cfg.get("turn_counter", 0) + 1
    turn_dir = os.path.join(arena_dir, f"turn_{turn_num:04d}")
    os.makedirs(turn_dir, exist_ok=True)

    from team     import Team
    from warrior  import Warrior
    from combat   import run_fight, set_show_favorite_weapon, set_show_luck_factor, set_show_max_hp
    from matchmaking import build_global_fight_card

    set_show_favorite_weapon(cfg.get("show_favorite_weapon", False))
    set_show_luck_factor(cfg.get("show_luck_factor", False))
    set_show_max_hp(cfg.get("show_max_hp", False))

    # --- Load teams from the arena-specific folder ---
    # saves/{arena}/teams/ is the sole source of truth — normal-arena uploads never
    # touch these files, so there is no cross-arena contamination.
    # If the client uploaded arena-specific data (saves/{arena}/uploads/), merge
    # those uploads over the base snapshot so the latest warrior stats are used.
    _base_dicts  = _load_immortal_teams(arena)
    _upload_dicts = _load_immortal_uploads(arena)

    _team_dicts = []
    for _bd in _base_dicts:
        _tid = int(_bd.get("team_id", 0))
        # Prefer upload if present (client sent latest stats)
        _team_dicts.append(_upload_dicts.pop(_tid, _bd))
    # Any uploads for teams not yet in base (shouldn't happen, but include them)
    _team_dicts.extend(_upload_dicts.values())

    all_teams = []
    for _td in _team_dicts:
        try:
            all_teams.append(Team.from_dict(_td))
        except Exception as _te:
            print(f"  WARNING: could not build Team from arena dict: {_te}")

    # Count BEFORE injection so archived dicts aren't double-counted.
    # Every warrior in the arena-specific files belongs to this arena by construction,
    # but re-check the field defensively.
    arena_warrior_count = sum(
        1 for t in all_teams
        for w in list(t.warriors or []) + list(t.archived_warriors or [])
        if w and (
            (not isinstance(w, dict) and not w.is_dead and not w.is_retired
             and getattr(w, "current_arena", arena) == arena)
            or
            (isinstance(w, dict) and not w.get("is_dead", True)
             and (w.get("current_arena") or arena) == arena)
        )
    )

    # Inject archived warriors (immortal arena members stored outside the TEAM_SIZE
    # cap) into team.warriors so build_global_fight_card can see them via
    # active_warriors.  We track each injection so we can write updated stats back
    # to archived_warriors after combat and then remove them before save.
    _injected: dict = {}  # warrior_name -> (team_obj, archived_list_index)
    for _t in all_teams:
        for _idx, _aw in enumerate(getattr(_t, 'archived_warriors', []) or []):
            if not _aw or not isinstance(_aw, dict):
                continue
            if _aw.get('is_dead', True):
                continue
            if (_aw.get('current_arena') or 'normal') != arena:
                continue
            try:
                _w = Warrior.from_dict(_aw)
                _t.warriors.append(_w)
                _injected[_w.name] = (_t, _idx)
                print(f"  Injected archived warrior: {_w.name} ({_t.team_name})")
            except Exception as _ie:
                print(f"  WARNING: could not inject archived warrior "
                      f"{_aw.get('name', '?')}: {_ie}")

    _arena_display = {"elite": "THE ELITE SPIRE", "veteran": "THE DEAD GROUNDS"}
    print(f"\n  ===== {_arena_display.get(arena, arena.upper())} — TURN {turn_num} =====")
    print(f"  Warriors in this arena: {arena_warrior_count}")

    if arena_warrior_count == 0:
        with _lock:
            arena_cfg["turn_state"] = "open"
            with open(arena_cfg_path, "w", encoding="utf-8") as _f:
                json.dump(arena_cfg, _f, indent=2)
        return {"success": False, "error": f"No warriors in {arena} arena."}

    # --- Build fight card ---
    global_card = build_global_fight_card(
        player_teams=all_teams,
        opponent_teams=[],
        arena=arena,
    )
    print(f"  Fights scheduled: {len(global_card)}")

    # --- Execute fights ---
    all_results: dict = {}   # team_id -> result dict
    fight_counter_local = 0

    for fight in global_card:
        fight_counter_local += 1
        fid = fight_counter_local
        print(f"\n  [{fid}/{len(global_card)}] {fight.player_warrior.name} vs {fight.opponent.name} [{fight.fight_type}]")

        try:
            result = run_fight(
                fight.player_warrior, fight.opponent,
                team_a_name    = fight.player_team.team_name,
                team_b_name    = fight.opponent_team.team_name,
                manager_a_name = fight.player_team.manager_name,
                manager_b_name = fight.opponent_manager,
                fight_type     = fight.fight_type,
                pos_a          = fight.pos_a,
                pos_b          = fight.pos_b,
            )
            fight.result = result
        except Exception as _fe:
            import traceback; traceback.print_exc()
            print(f"  ERROR running fight: {_fe}")
            continue

        pw_won  = result.winner is not None and result.winner.name == fight.player_warrior.name
        opp_won = not pw_won

        # Update both warriors
        for w, won, self_hp, opp_hp, self_kd, opp_kd, self_nk, opp_nk, opp_fights in [
            (fight.player_warrior, pw_won,
             result.winner_hp_pct if pw_won else result.loser_hp_pct,
             result.loser_hp_pct  if pw_won else result.winner_hp_pct,
             result.winner_knockdowns if pw_won else result.loser_knockdowns,
             result.loser_knockdowns  if pw_won else result.winner_knockdowns,
             result.winner_near_kills if pw_won else result.loser_near_kills,
             result.loser_near_kills  if pw_won else result.winner_near_kills,
             fight.opponent.total_fights),
            (fight.opponent, opp_won,
             result.winner_hp_pct if opp_won else result.loser_hp_pct,
             result.loser_hp_pct  if opp_won else result.winner_hp_pct,
             result.winner_knockdowns if opp_won else result.loser_knockdowns,
             result.loser_knockdowns  if opp_won else result.winner_knockdowns,
             result.winner_near_kills if opp_won else result.loser_near_kills,
             result.loser_near_kills  if opp_won else result.winner_near_kills,
             fight.player_warrior.total_fights),
        ]:
            w.update_popularity(won=won)
            w.update_recognition(
                won=won, killed_opponent=False,
                self_hp_pct=self_hp, opp_hp_pct=opp_hp,
                self_knockdowns=self_kd, opp_knockdowns=opp_kd,
                self_near_kills=self_nk, opp_near_kills=opp_nk,
                minutes_elapsed=result.minutes_elapsed,
                opponent_total_fights=opp_fights,
            )

        opp_team = fight.opponent_team.team_name if hasattr(fight.opponent_team, "team_name") else ""
        fight.player_warrior.fight_history.append({
            "turn": turn_num, "arena": arena,
            "opponent_name": fight.opponent.name,
            "opponent_race": fight.opponent.race.name,
            "opponent_team": opp_team,
            "opponent_team_id": fight.opponent_team.team_id,
            "opponent_manager_name": fight.opponent_manager,
            "result": "win" if pw_won else "loss",
            "minutes": result.minutes_elapsed, "fight_id": fid,
            "warrior_slain": False, "opponent_slain": False, "is_kill": False,
            "fight_type": fight.fight_type,
            "primary_weapon": fight.player_warrior.primary_weapon or "Unknown",
        })
        fight.opponent.fight_history.append({
            "turn": turn_num, "arena": arena,
            "opponent_name": fight.player_warrior.name,
            "opponent_race": fight.player_warrior.race.name,
            "opponent_team": fight.player_team.team_name,
            "opponent_team_id": fight.player_team.team_id,
            "opponent_manager_name": fight.player_team.manager_name,
            "result": "win" if opp_won else "loss",
            "minutes": result.minutes_elapsed, "fight_id": fid,
            "warrior_slain": False, "opponent_slain": False, "is_kill": False,
            "fight_type": fight.fight_type,
            "primary_weapon": fight.opponent.primary_weapon or "Unknown",
        })

        # Collect result for each team
        for (tid, team_name, mgr_name, warrior, w_won) in [
            (fight.player_team.team_id,   fight.player_team.team_name,   fight.player_team.manager_name,   fight.player_warrior, pw_won),
            (fight.opponent_team.team_id, fight.opponent_team.team_name, fight.opponent_manager,           fight.opponent,       opp_won),
        ]:
            if tid < 0:
                continue
            if tid not in all_results:
                all_results[tid] = {
                    "team_id": tid, "team_name": team_name,
                    "manager_name": mgr_name, "bouts": [], "fight_logs": {},
                }
            all_results[tid]["bouts"].append({
                "warrior_name": warrior.name,
                "opponent_name": (fight.opponent if w_won == pw_won else fight.player_warrior).name
                                  if False else (fight.opponent.name if warrior is fight.player_warrior else fight.player_warrior.name),
                "result": "WIN" if w_won else "LOSS",
                "minutes": result.minutes_elapsed, "fight_id": fid,
                "wins": warrior.wins, "losses": warrior.losses, "kills": warrior.kills,
                "warrior_slain": False, "opponent_slain": False,
                "fight_type": fight.fight_type,
            })
            all_results[tid]["fight_logs"][str(fid)] = result.narrative

        outcome = "WON" if pw_won else "LOST"
        print(f"  Result: {fight.player_warrior.name} {outcome} in {result.minutes_elapsed} minutes")

    # --- Write updated stats back to archived_warriors dicts, then remove injections ---
    for _wname, (_t, _idx) in _injected.items():
        _inj_w = next(
            (w for w in _t.warriors
             if w is not None and not isinstance(w, dict) and w.name == _wname),
            None,
        )
        if _inj_w is not None:
            _t.archived_warriors[_idx] = _inj_w.to_dict()
    # Strip injected Warrior objects from team.warriors so they aren't double-saved
    _injected_names = set(_injected.keys())
    for _t in all_teams:
        _t.warriors = [
            w for w in _t.warriors
            if not (w is not None and not isinstance(w, dict)
                    and w.name in _injected_names)
        ]

    # --- Save updated stats back to arena-specific team files ---
    # Write to saves/{arena}/teams/ — NOT the main saves/teams/ files.
    # This keeps the arena isolated: normal-arena uploads can never overwrite these.
    for team in all_teams:
        try:
            _save_immortal_team(arena, team.to_dict())
        except Exception as _se:
            print(f"  WARNING: could not save arena team {team.team_id}: {_se}")

    # --- Save result files (include fight_logs so narratives are viewable) ---
    for tid, res in all_results.items():
        rpath = os.path.join(turn_dir, f"result_team{tid:04d}.json")
        with open(rpath, "w", encoding="utf-8") as _f:
            json.dump({
                "turn": turn_num, "arena": arena,
                "team_id": res["team_id"], "team_name": res["team_name"],
                "manager_name": res["manager_name"],
                "bouts": res["bouts"],
                "fight_logs": res.get("fight_logs", {}),
            }, _f, indent=2)

    # --- Update arena standings ---
    standings_path = os.path.join(arena_dir, "standings.json")
    try:
        with open(standings_path, encoding="utf-8") as _f:
            standings = json.load(_f)
    except Exception:
        standings = {"teams": {}}

    for tid, res in all_results.items():
        key = str(tid)
        standings.setdefault("teams", {}).setdefault(key, {
            "team_name": res["team_name"],
            "manager_name": res["manager_name"],
            "wins": 0, "losses": 0, "kills": 0, "warriors": {},
        })
        ts = standings["teams"][key]
        ts["team_name"]    = res["team_name"]
        ts["manager_name"] = res["manager_name"]
        for bout in res["bouts"]:
            if bout.get("result") == "WIN":
                ts["wins"] = ts.get("wins", 0) + 1
            else:
                ts["losses"] = ts.get("losses", 0) + 1
            wn = bout.get("warrior_name", "")
            ts.setdefault("warriors", {}).setdefault(wn, {"wins": 0, "losses": 0, "kills": 0})
            ws = ts["warriors"][wn]
            ws["wins"]   = bout.get("wins",   ws["wins"])
            ws["losses"] = bout.get("losses",  ws["losses"])

    standings["turn"] = turn_num
    with open(standings_path, "w", encoding="utf-8") as _f:
        json.dump(standings, _f, indent=2)

    # --- Generate newsletter (formatted to match regular arena newsletter style) ---
    _disp = _arena_display.get(arena, arena.upper())
    _processed_date = time.strftime("%B %d, %Y")
    # ANSI styling — identical codes to regular newsletter (newsletter.py)
    _H1   = "\033[1;999m"    # masthead title   (HDR_TITLE)
    _H2   = "\033[1;998m"    # masthead subtitle (HDR_SUBTITLE)
    _SEC  = "\033[1;31;98m"  # main section header  (HDR_RED_LG)
    _SSEC = "\033[1;31;99m"  # sub-section header   (HDR_RED)
    _BOLD = "\033[1;99m"     # table header bold    (HDR_BOLD)
    _RED  = "\033[1;31m"     # inline manager/team names
    _RST  = "\033[0m"        # reset
    _W    = 85               # newsletter width (matches _fights_section sep)

    _SEP = "=" * _W
    _sep = "-" * _W

    # ── MASTHEAD ─────────────────────────────────────────────────────
    nl_lines = [
        f"Date: {_processed_date}",
        f"{_H1}{_disp}{_RST}{_H2}Turn - {turn_num}{_RST}",
        "",
    ]

    # ── TEAM STANDINGS ───────────────────────────────────────────────
    sorted_teams = sorted(
        standings.get("teams", {}).items(),
        key=lambda x: (x[1].get("wins", 0), -x[1].get("losses", 0)),
        reverse=True,
    )
    nl_lines.append(
        f"\n{_BOLD}{'The Top Teams':<15}{_RST}{_disp.upper()} STANDINGS"
    )
    nl_lines.append(_SEP)
    nl_lines.append(
        f"{'POS':<5} {'Team Name':<32} {'(Manager)':<24}"
        f" {'W':>4} {'L':>4} {'K':>4}  {'%':>6}"
    )
    nl_lines.append(_SEP)
    for rank, (_, ts) in enumerate(sorted_teams, 1):
        _tw = ts.get("wins", 0)
        _tl = ts.get("losses", 0)
        _tk = ts.get("kills", 0)
        _pct = f"{100*_tw/(_tw+_tl):.1f}%" if (_tw + _tl) > 0 else "  —  "
        _mgr_raw = ts.get("manager_name", "?")
        nl_lines.append(
            f"{rank:<5} {ts['team_name']:<32} ({_RED}{_mgr_raw}{_RST})"
            f"  {_tw:>4} {_tl:>4} {_tk:>4}  {_pct:>6}"
        )
    nl_lines.append(_SEP)

    # ── LAST TURN'S FIGHTS ───────────────────────────────────────────
    _completed = [f for f in global_card if f.result and f.result.winner]
    _draws      = [f for f in global_card if f.result and not f.result.winner]
    nl_lines += ["", f"\n{_SEC}LAST TURN'S FIGHTS{_RST}", _SEP]
    if _completed or _draws:
        nl_lines.append(f"{_SSEC}IMMORTAL ARENA MATCHUPS{_RST}")
        nl_lines.append(_SEP)
        for fight in _completed:
            _pw_won = fight.result.winner.name == fight.player_warrior.name
            _winner = fight.player_warrior if _pw_won else fight.opponent
            _loser  = fight.opponent       if _pw_won else fight.player_warrior
            _mins   = fight.result.minutes_elapsed
            _hp_pct = int((fight.result.winner_hp_pct or 0) * 100)
            nl_lines.append(
                f"{_winner.name} defeated {_loser.name}"
                f" in a {_mins} minute {fight.fight_type} bout. "
                f"(Winner HP: {_hp_pct}%)"
            )
        for fight in _draws:
            nl_lines.append(
                f"{fight.player_warrior.name} vs {fight.opponent.name}"
                f" — DRAW after {fight.result.minutes_elapsed} min."
            )
    else:
        nl_lines.append("  No bouts completed this turn.")

    # ── ARENA HAPPENINGS ─────────────────────────────────────────────
    _long_fights = sorted(_completed, key=lambda f: f.result.minutes_elapsed, reverse=True)
    _quick_wins  = sorted(_completed, key=lambda f: f.result.minutes_elapsed)
    _ko_fights   = [f for f in _completed if f.result.loser_knockdowns > 0]
    nl_lines += ["", f"\n{_SEC}ARENA HAPPENINGS{_RST}", ""]
    nl_lines.append(
        f"  {len(global_card)} bout(s) contested this turn. "
        "No permanent deaths — the compact of immortality holds."
    )
    if _long_fights:
        _lf    = _long_fights[0]
        _lf_pw = _lf.result.winner and _lf.result.winner.name == _lf.player_warrior.name
        _lf_w  = _lf.player_warrior if _lf_pw else _lf.opponent
        _lf_l  = _lf.opponent       if _lf_pw else _lf.player_warrior
        nl_lines.append(
            f"  Longest fight: {_lf_w.name} vs {_lf_l.name} "
            f"({_lf.result.minutes_elapsed} min)"
        )
    if _quick_wins:
        _qw    = _quick_wins[0]
        _qw_pw = _qw.result.winner and _qw.result.winner.name == _qw.player_warrior.name
        _qw_w  = _qw.player_warrior if _qw_pw else _qw.opponent
        _qw_l  = _qw.opponent       if _qw_pw else _qw.player_warrior
        nl_lines.append(
            f"  Quickest finish: {_qw_w.name} over {_qw_l.name} "
            f"({_qw.result.minutes_elapsed} min)"
        )
    if _ko_fights:
        nl_lines.append(
            f"  Knockdowns recorded in {len(_ko_fights)} bout(s) this turn."
        )

    # ── WARRIOR RANKINGS ─────────────────────────────────────────────
    _arena_warriors = []
    for _t in all_teams:
        for _w_obj in (_t.active_warriors or []):
            if getattr(_w_obj, 'current_arena', 'normal') == arena:
                _arena_warriors.append((_w_obj, _t))
        for _aw_dict in (getattr(_t, 'archived_warriors', []) or []):
            if (not _aw_dict or not isinstance(_aw_dict, dict)
                    or _aw_dict.get('is_dead', True)):
                continue
            if (_aw_dict.get('current_arena') or 'normal') != arena:
                continue
            try:
                _arena_warriors.append((Warrior.from_dict(_aw_dict), _t))
            except Exception:
                pass
    if _arena_warriors:
        def _arena_rec(w_t):
            _wo, _ = w_t
            _fh = getattr(_wo, 'fight_history', []) or []
            _af = [f for f in _fh if (f.get('arena') or 'normal') == arena]
            return (
                -sum(1 for f in _af if f.get('result') == 'win'),
                sum(1 for f in _af if f.get('result') == 'loss'),
            )
        _arena_warriors.sort(key=_arena_rec)
        nl_lines += ["", f"\n{_SEC}WARRIOR RANKINGS{_RST}", _SEP]
        nl_lines.append(
            f"  {'Name':<24} {'Race':<14} {'W':>4} {'L':>4} {'K':>4}  Team"
        )
        nl_lines.append("  " + _sep)
        for _w_obj, _t in _arena_warriors:
            _fh = getattr(_w_obj, 'fight_history', []) or []
            _af = [f for f in _fh if (f.get('arena') or 'normal') == arena]
            _aw = sum(1 for f in _af if f.get('result') == 'win')
            _al = sum(1 for f in _af if f.get('result') == 'loss')
            _ak = sum(1 for f in _af if f.get('is_kill', False))
            nl_lines.append(
                f"  {_w_obj.name:<24} {_w_obj.race.name:<14}"
                f" {_aw:>4} {_al:>4} {_ak:>4}  {_t.team_name}"
            )
        nl_lines.append("  " + _sep)

    nl_lines += ["", _SEP]
    nl_text = "\n".join(nl_lines)
    with open(os.path.join(turn_dir, "newsletter.txt"), "w", encoding="utf-8") as _f:
        _f.write(nl_text)

    # --- Finalise arena config ---
    with _lock:
        arena_cfg["turn_counter"]  = turn_num
        arena_cfg["turn_state"]    = "results_ready"
        arena_cfg["last_run_at"]   = time.strftime("%Y-%m-%d %H:%M:%S")
        arena_cfg["last_run_turn"] = turn_num
        with open(arena_cfg_path, "w", encoding="utf-8") as _f:
            json.dump(arena_cfg, _f, indent=2)

    total_bouts = sum(len(r["bouts"]) for r in all_results.values())
    print(f"\n  {_disp} Turn {turn_num} complete — {len(all_results)} team(s), {total_bouts} bout(s).")
    return {
        "success": True, "arena": arena, "turn_number": turn_num,
        "teams": len(all_results), "fights": len(global_card),
        "newsletter": nl_text,
    }


def _filter_warrior_for_client(warrior_dict: dict, cfg: dict) -> dict:
    """
    Filter warrior data for client download based on feature flags.
    Removes sensitive fields if flags are disabled.
    """
    w = warrior_dict.copy()
    # Remove luck factor if flag is off
    if not cfg.get("show_luck_factor", False):
        w.pop("luck", None)
    # favorite_weapon is intentionally NOT stripped here.
    # Stripping it caused the field to be absent from client uploads, triggering
    # assign_favorite_weapon() on every turn re-load - changing the weapon each turn.
    # The client UI already conditionally hides it via S.league.flags.show_favorite_weapon.
    return w


def _filter_results_for_client(results: list, cfg: dict) -> list:
    """
    Filter all team results for client download based on feature flags.
    """
    filtered = []
    for team_result in results:
        tr = team_result.copy()
        # Filter warriors in the team
        if "team" in tr and "warriors" in tr["team"]:
            tr["team"] = tr["team"].copy()
            tr["team"]["warriors"] = [
                _filter_warrior_for_client(w, cfg)
                for w in tr["team"]["warriors"]
            ]
        filtered.append(tr)
    return filtered

_SCHED_DAYS = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]

def _render_schedule_slots(slots):
    """Render one HTML row per schedule slot for the admin panel."""
    _day_opts = lambda sel: "".join(
        f'<option {"selected" if d == sel else ""}>{d}</option>'
        for d in _SCHED_DAYS
    )
    rows = []
    for i, slot in enumerate(slots):
        d = slot.get("day",  "Friday")
        t = slot.get("time", "20:00")
        last = slot.get("last_run_result", "")
        hint = f" title=\"{last}\"" if last else ""
        rows.append(
            f'    <div class="sched-row" data-idx="{i}" style="display:flex;align-items:center;gap:4px">'
            f'<select class="sched-day" onchange="saveSchedule()" style="font-size:12px;border:2px inset #808080">{_day_opts(d)}</select>'
            f'<input class="sched-time" type="time" value="{t}" onchange="saveSchedule()" style="font-size:12px;border:2px inset #808080;width:88px">'
            f'<button onclick="removeSchedSlot(this)"{hint} style="font-size:11px;padding:1px 6px;background:#eee;border-color:#ccc;color:#600">✕</button>'
            f'</div>'
        )
    return "\n".join(rows) + "\n" if rows else ""


# =============================================================================
# ADMIN PAGE (HTML) - Updated with Delete Manager Dropdown + Button
# =============================================================================
def _admin_page():
    cfg = _load_config()
    managers = _load_managers()
    uploads = _load_uploads(cfg["current_turn"])
    standings= _load_standings()
    turn = cfg["current_turn"]
    state = cfg["turn_state"]

    # Detection for auto-scheduled turns
    last_sched_turn   = cfg.get("schedule_last_run_turn", 0)
    last_sched_result = cfg.get("schedule_last_run_result", "")
    was_scheduled = (last_sched_turn > 0 and (turn - 1) == last_sched_turn)
    auto_completed = (was_scheduled and state == "results_ready"
                      and last_sched_result.startswith("Completed"))

    # Define colors for states
    sc = {"open":"#080","processing":"#840","results_ready":"#080"} # Green for completed state

    # Determine the display text for the state banner
    state_display = state.replace("_"," ").upper()
    if state == "results_ready":
        state_display = "TURN RUN COMPLETED SUCCESSFULLY"
        if was_scheduled:
            state_display += " (AUTO-SCHEDULED)"

    # Upload status rows
    mgr_manual_counts = {}
    mgr_auto_counts = {}
    mgr_upload_times = {}
    for key, udata in uploads.items():
        uid = udata.get("manager_id", key.split("_team")[0])
        if udata.get("auto_uploaded"):
            mgr_auto_counts[uid] = mgr_auto_counts.get(uid, 0) + 1
        else:
            mgr_manual_counts[uid] = mgr_manual_counts.get(uid, 0) + 1
        mgr_upload_times[uid] = udata.get("uploaded_at","?")
    mgr_upload_counts = {m: mgr_manual_counts.get(m,0) + mgr_auto_counts.get(m,0)
                         for m in set(mgr_manual_counts) | set(mgr_auto_counts)}
    urows = ""
    for mid, mgr in managers.items():
        manual = mgr_manual_counts.get(mid, 0)
        auto = mgr_auto_counts.get(mid, 0)
        total = manual + auto
        if total:
            parts = []
            if manual: parts.append(f"{manual} manual")
            if auto: parts.append(f"{auto} auto-carry")
            badge = (f"<b style='color:#060'>✓ {total} team(s) uploaded "
                     f"({', '.join(parts)}) - {mgr_upload_times.get(mid,'')}</b>")
        else:
            badge = "<span style='color:#800'>✗ not uploaded</span>"
        urows += f"<tr><td>{mgr['manager_name']}</td><td>{badge}</td></tr>"
    if not urows:
        urows = "<tr><td colspan=2 style='color:#888'>No managers registered yet</td></tr>"
    # AI count
    try:
        ai_path = os.path.join(LEAGUE_DIR, "ai_teams.json")
        ai_count = len(json.loads(open(ai_path).read())) if os.path.exists(ai_path) else 0
    except Exception:
        ai_count = 0
    # Only show AI teams in uploads if they're actually enabled
    if ai_count and cfg.get("ai_teams_enabled", True):
        urows += f"<tr><td colspan=2 style='color:#555;font-style:italic'>+ {ai_count} AI teams (auto-included)</td></tr>"
    # Standings rows
    warriors_flat = []
    for mid, sd in standings.items():
        is_ai = sd.get("is_ai", mid.startswith("ai_"))
        for wname, ws in sd.get("warriors", {}).items():
            warriors_flat.append({"mgr": sd["manager_name"], "name": wname,
                                   "is_ai": is_ai, **ws})
    warriors_flat.sort(key=lambda x: (-x["wins"], x["losses"]))
    srows = "".join(
        f"<tr><td>{'🤖 ' if w['is_ai'] else ''}{w['mgr']}</td><td>{w['name']}</td>"
        f"<td style='text-align:center'>{w['wins']}-{w['losses']}-{w['kills']}</td>"
        f"<td style='text-align:center'>{w['fights']}</td></tr>"
        for w in warriors_flat
    ) or "<tr><td colspan=4 style='color:#888'>No completed turns yet</td></tr>"
    # Re-run section
    if turn > 1:
        last_turn = turn - 1
        rerun_section = (
            f'<div style="margin-top:10px;border-top:1px solid #ddd;padding-top:8px">'
            f'<b style="font-size:11px">Re-run Turn {last_turn}:</b><br>'
            f'<span style="font-size:11px;color:#800">⚠ Replaces all results for turn {last_turn} as if it never ran.</span><br>'
            f'<button onclick="rerunTurn({last_turn})">↺ Re-run Turn {last_turn}</button>'
            f'</div>'
        )
    else:
        rerun_section = ""

    # Dropdown options for Admin actions
    manager_options = ""
    for mid, mgr in managers.items():
        manager_options += f'<option value="{mid}">{mgr["manager_name"]} (ID: {mid})</option>'

    from save import list_saved_teams
    # Create name -> ID map for filtering teams in JS
    name_to_id = {m["manager_name"]: mid for mid, m in managers.items()}
    team_options = ""
    for t in sorted(list_saved_teams(), key=lambda x: x["team_id"]):
        mid = name_to_id.get(t["manager_name"], "Unknown")
        team_options += f'<option value="{t["team_id"]}" data-mid="{mid}">{t["team_name"]} (ID: {t["team_id"]}, Manager: {t["manager_name"]})</option>'
    team_options_json = json.dumps(team_options)

    _dbg_mid = cfg.get("admin_debug_manager_id", "")
    _dbg_display = managers.get(_dbg_mid, {}).get("manager_name", "None (disabled)") if _dbg_mid else "None (disabled)"

    # ── Immortal arena stats for admin tab ────────────────────────────────
    def _load_arena_cfg(arena):
        _p = os.path.join(BASE_DIR, "saves", arena, "config.json")
        if not os.path.exists(_p):
            return {"turn_counter": 0, "turn_state": "not_initialised",
                    "scheduler": {"enabled": False, "schedule_slots": []}}
        try:
            with open(_p, encoding="utf-8") as _f:
                return json.load(_f)
        except Exception:
            return {"turn_counter": 0, "turn_state": "error",
                    "scheduler": {"enabled": False, "schedule_slots": []}}

    elite_cfg_a  = _load_arena_cfg("elite")
    vet_cfg_a    = _load_arena_cfg("veteran")

    try:
        from save import load_all_teams as _lat
        _all_t = _lat()
        def _arena_member(w, arena):
            """True if w (Warrior object or archived dict) is alive in the given arena."""
            if isinstance(w, dict):
                return (not w.get("is_dead", True)
                        and (w.get("current_arena") or "normal") == arena)
            return (w and not w.is_dead
                    and getattr(w, "current_arena", "normal") == arena)
        elite_warrior_count = sum(
            1 for _t in _all_t
            for _w in list(_t.warriors or []) + list(_t.archived_warriors or [])
            if _w and _arena_member(_w, "elite"))
        vet_warrior_count = sum(
            1 for _t in _all_t
            for _w in list(_t.warriors or []) + list(_t.archived_warriors or [])
            if _w and _arena_member(_w, "veteran"))
        elite_team_count = len({_t.team_id for _t in _all_t if any(
            _arena_member(_w, "elite")
            for _w in list(_t.warriors or []) + list(_t.archived_warriors or []) if _w)})
        vet_team_count = len({_t.team_id for _t in _all_t if any(
            _arena_member(_w, "veteran")
            for _w in list(_t.warriors or []) + list(_t.archived_warriors or []) if _w)})
        # Promotion pending count
        promo_pending_count = sum(
            1 for _t in _all_t for _w in (_t.active_warriors or [])
            if _w and getattr(_w, "pending_promotion", None))
    except Exception:
        elite_warrior_count = vet_warrior_count = 0
        elite_team_count = vet_team_count = 0
        promo_pending_count = 0

    elite_sched        = elite_cfg_a.get("scheduler", {})
    vet_sched          = vet_cfg_a.get("scheduler", {})
    elite_sched_on     = elite_sched.get("enabled", False)
    vet_sched_on       = vet_sched.get("enabled", False)
    elite_slots_list   = elite_sched.get("schedule_slots", [])
    vet_slots_list     = vet_sched.get("schedule_slots", [])

    def _render_immortal_slots(arena, slots):
        if not slots:
            return f'<div id="{arena}-slot-list" style="color:#888;font-size:11px">(no slots configured)</div>'
        rows = f'<div id="{arena}-slot-list">'
        for i, s in enumerate(slots):
            rows += (f'<div style="display:flex;align-items:center;gap:4px;margin:2px 0" '
                     f'id="{arena}-slot-{i}">'
                     f'<select onchange="markImmortalSlotDirty(\'{arena}\')" '
                     f'id="{arena}-slot-{i}-day" style="font-size:11px;padding:1px">'
                     + "".join(f'<option {"selected" if s.get("day")==d else ""}>{d}</option>'
                                for d in ("Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"))
                     + f'</select><input type="time" value="{s.get("time","18:00")}" '
                     f'id="{arena}-slot-{i}-time" style="font-size:11px;width:70px" '
                     f'onchange="markImmortalSlotDirty(\'{arena}\')">'
                     f'<span style="font-size:10px;color:#888">'
                     f'{("Last: T"+str(s.get("last_run_turn","?"))) if s.get("last_run_turn") else ""}'
                     f'</span></div>')
        rows += '</div>'
        return rows

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>The Agony Amphitheatre League - Admin v{SERVER_VERSION}</title>
<style>
 body{{font:13px Tahoma,Arial,sans-serif;background:#d4d0c8;margin:0}}
 .bar{{background:#000080;color:#fff;padding:6px 14px;font-weight:bold;font-size:15px;
       display:flex;align-items:center;gap:16px}}
 .bar span{{font-size:11px;font-weight:normal;opacity:.9}}
 .wrap{{padding:10px;display:flex;gap:10px;flex-wrap:wrap}}
 .panel{{border:2px solid #808080;background:#fff;padding:10px;flex:1;min-width:260px}}
 h3{{margin:0 0 8px;font-size:12px;font-weight:bold;border-bottom:1px solid #ccc;padding-bottom:4px}}
 table{{border-collapse:collapse;width:100%;font-size:12px}}
 th{{background:#d4d0c8;border:1px solid #808080;padding:3px 8px;text-align:left}}
 td{{border:1px solid #ddd;padding:2px 8px}}
 tr:nth-child(even){{background:#f5f4f0}}
 input[type=password],input[type=number]{{border:2px inset #808080;padding:3px 6px;font-size:12px}}
 button{{background:#d4d0c8;border:2px solid;border-color:#fff #808080 #808080 #fff;
         padding:3px 14px;font-size:12px;cursor:pointer;margin-top:4px}}
 button:active{{border-color:#808080 #fff #fff #808080}}
 button.danger{{border-color:#f88 #800 #800 #f88;color:#800;background:#c00;color:white}}
 .state{{font-weight:bold;color:{sc.get(state,'#000')}}}
 #msg{{padding:6px 14px;margin:4px 0;display:none;font-size:12px}}
 .ok{{background:#cfc;border-left:4px solid #080}}
 .err{{background:#fcc;border-left:4px solid #800}}
 .prog-wrap{{background:#e0e0e0;border:1px inset #808080;height:18px;margin:6px 0;position:relative}}
 .prog-bar{{background:#000080;height:100%;transition:width .4s}}
 .prog-lbl{{position:absolute;top:0;left:0;right:0;text-align:center;font-size:11px;
            line-height:18px;color:#fff;mix-blend-mode:difference}}
 .tabs{{display:flex;background:#d4d0c8;padding:5px 10px 0;border-bottom:1px solid #808080;gap:2px}}
 .tab-btn{{background:#d4d0c8;border:2px solid;border-color:#fff #808080 #808080 #fff;
          border-bottom:none;padding:6px 16px;font-weight:bold;cursor:pointer;border-radius:4px 4px 0 0;font-size:11px}}
 .tab-btn.active{{background:#fff;border-bottom:2px solid #fff;margin-bottom:-2px;z-index:10}}
 .tab-content{{display:none;padding:10px;flex-wrap:wrap;gap:10px}}
 .tab-content.active{{display:flex}}
</style></head><body>
<script>
function openTab(evt, tabId) {{
  const contents = document.getElementsByClassName("tab-content");
  for (let i = 0; i < contents.length; i++) {{
    contents[i].classList.remove("active");
  }}
  const buttons = document.getElementsByClassName("tab-btn");
  for (let i = 0; i < buttons.length; i++) {{
    buttons[i].classList.remove("active");
  }}
  const tabElement = document.getElementById(tabId);
  if (tabElement) {{
    tabElement.classList.add("active");
  }}
  if (evt && evt.target) {{
    evt.target.classList.add("active");
  }}
}}
</script>
<div class="bar">⚔ THE AGONY AMPHITHEATRE - Admin <span style="margin-left:8px; opacity:0.7;">v{SERVER_VERSION}</span>
 <span>Turn {turn}</span>
 <span class="state">{state_display}</span>
 <span id="sched-top-badge" style="display:none;background:#060;color:#fff;padding:2px 8px;border-radius:3px;font-size:10px;margin-left:8px;vertical-align:middle;border:1px solid #0a0">AUTO-SCHEDULE ON</span>
 <span>{len(mgr_upload_counts)}/{len(managers)} players + {ai_count} AI uploaded</span>
</div>
<div id="msg"></div>
{'<div style="background:#0a3;color:#fff;padding:10px 18px;font-size:13px;border-bottom:2px solid #080;display:flex;align-items:center;gap:12px"><span style="font-size:18px">✓</span><span><strong>Auto-scheduled turn ' + str(last_sched_turn) + ' completed</strong> - ' + last_sched_result.replace("Completed at ","") + '</span></div>' if auto_completed else ''}

<div class="tabs">
 <button class="tab-btn active" onclick="openTab(event, 'tab-ops')">⚔ OPERATIONS</button>
 <button class="tab-btn" onclick="openTab(event, 'tab-mgmt')">👥 MANAGEMENT</button>
 <button class="tab-btn" onclick="openTab(event, 'tab-reports')">📊 REPORTS</button>
 <button class="tab-btn" onclick="openTab(event, 'tab-maint')">🔧 MAINTENANCE</button>
 <button class="tab-btn" onclick="openTab(event, 'tab-arenas')" id="tab-btn-arenas" style="background:#001a3a;color:#9cf">
  ✦ IMMORTAL ARENAS{(' <span style="background:#c80;color:#000;border-radius:3px;padding:0 4px;font-size:10px">' + str(promo_pending_count) + ' PENDING</span>') if promo_pending_count else ''}
 </button>
</div>

<!-- ====================== OPERATIONS TAB ====================== -->
<div id="tab-ops" class="tab-content active">
 <div class="panel" style="min-width:260px;max-width:340px">
  <h3>▶ Run Turn {turn}</h3>
  <p style="font-size:11px;color:#555;margin:0 0 6px">
   {len(mgr_upload_counts)} of {len(managers)} managers uploaded with a total of {len(uploads) + ai_count} teams active.
  </p>
  Host password:<br>
  <input type="password" id="hp" style="width:200px" oninput="savePwToStorage()" placeholder="Password will be remembered"><br>
  <button onclick="runTurn()">▶ Run Turn {turn}</button>
  <button title="Force unlock if hung" onclick="unlockTurn()" style="background:#eee;border-color:#ccc;color:#666;margin-left:4px">🔓</button>
  <div id="prog-wrap" class="prog-wrap" style="display:none">
   <div id="prog-bar" class="prog-bar" style="width:0%"></div>
   <div id="prog-lbl" class="prog-lbl">Starting...</div>
  </div>
  {rerun_section}
 </div>
 <div class="panel">
  <h3>Upload Status - Turn {turn}</h3>
  <table><tr><th>Manager</th><th>Status</th></tr>{urows}</table>
 </div>
 <div class="panel" style="min-width:260px;max-width:380px">
  <h3>📅 Turn Schedule</h3>
  <p style="font-size:11px;margin:0 0 8px;color:#555">
   Automatically run turns up to 7 times per week.<br>
   Add one slot per desired run day. You can still run turns manually at any time.
  </p>
  <label style="display:block;margin:6px 0">
   <input type="checkbox" id="sched-enabled" onchange="toggleSchedule()" style="cursor:pointer" {'checked' if cfg.get('schedule_enabled') else ''}>
   <span style="cursor:pointer;user-select:none">Enable auto-schedule</span>
  </label>
  <div id="sched-details" style="margin-top:10px;padding-left:2px">
   <div id="sched-slots" style="display:flex;flex-direction:column;gap:5px">
{_render_schedule_slots(cfg.get('schedule_slots', []))}   </div>
   <button id="sched-add-btn" onclick="addSchedSlot()" style="margin-top:6px;font-size:11px;padding:2px 8px" {'disabled' if len(cfg.get('schedule_slots',[])) >= 7 else ''}>+ Add time slot</button>
   <div style="margin-top:8px;font-size:10px;color:#888" id="sched-next"></div>
  </div>
 </div>
</div>

<!-- ====================== MANAGEMENT TAB ====================== -->
<div id="tab-mgmt" class="tab-content">
 <div class="panel" style="min-width:300px;">
  <h3 style="color:#c00;">🗑 Delete Manager</h3>
  <p style="color:#c00;font-size:12px;margin-bottom:10px;">
   ⚠ This will delete the selected manager's account and their uploads for the current turn. Their teams will remain in the system and can be accessed if they re-register.
  </p>
  <div style="margin-bottom:10px;">
   <label style="display:block;margin-bottom:4px;">Select Manager:</label>
   <select id="delete-manager-select" style="width:100%;padding:5px;border:2px inset #808080;font-size:13px;">
    <option value="">-- Select a manager to delete --</option>
    {manager_options}
   </select>
  </div>
  <button onclick="deleteSelectedManager()" class="danger" style="width:100%;padding:10px;font-size:13px;">
   DELETE SELECTED MANAGER
  </button>
 </div>
 <div class="panel" style="min-width:300px;">
  <h3>✎ Rename Manager</h3>
  <p style="font-size:12px;margin-bottom:10px;color:#555;">
   Correct a manager's display name without deleting their account, teams, or standings.
  </p>
  <div style="margin-bottom:8px;">
   <label style="display:block;margin-bottom:4px;">Select Manager:</label>
   <select id="rename-manager-select" style="width:100%;padding:5px;border:2px inset #808080;font-size:13px;">
    <option value="">-- Select a manager --</option>
    {manager_options}
   </select>
  </div>
  <div style="margin-bottom:10px;">
   <label style="display:block;margin-bottom:4px;">New Name:</label>
   <input type="text" id="rename-manager-name" placeholder="Enter new manager name"
          style="width:100%;padding:5px;box-sizing:border-box;border:2px inset #808080;font-size:13px;">
  </div>
  <button onclick="renameSelectedManager()" style="width:100%;padding:8px;font-size:13px;">
   RENAME MANAGER
  </button>
 </div>
 <div class="panel" style="min-width:300px;">
  <h3>💾 Download Manager Files</h3>
  <p style="font-size:12px;margin-bottom:10px;color:#555;">
   Download a manager's team files and turn results as a ZIP. Use this to manually send files to a manager who isn't receiving them.
  </p>
  <div style="margin-bottom:8px;">
   <label style="display:block;margin-bottom:4px;">Select Manager:</label>
   <select id="download-manager-select" style="width:100%;padding:5px;border:2px inset #808080;font-size:13px;">
    <option value="">-- Select a manager --</option>
    {manager_options}
   </select>
  </div>
  <button onclick="downloadManagerFiles()" style="width:100%;padding:8px;font-size:13px;">
   DOWNLOAD FILES AS ZIP
  </button>
 </div>
 <div class="panel" style="min-width:300px;">
  <h3 style="color:#c00;">🗑 Delete Team</h3>
  <p style="color:#c00;font-size:12px;margin-bottom:10px;">
   ⚠ Permanently delete a team from the server. The manager will be notified on next login and the team will be removed from their client.
  </p>
  <div style="margin-bottom:8px;">
   <label style="display:block;margin-bottom:4px;">Select Manager:</label>
   <select id="delete-team-manager-select" style="width:100%;padding:5px;border:2px inset #808080;font-size:13px;" onchange="updateDeleteTeamOptions()">
    <option value="">-- Select a manager --</option>
    {manager_options}
   </select>
  </div>
  <div style="margin-bottom:10px;">
   <label style="display:block;margin-bottom:4px;">Select Team:</label>
   <select id="delete-team-select" style="width:100%;padding:5px;border:2px inset #808080;font-size:13px;">
    <option value="">-- Select a team --</option>
   </select>
  </div>
  <button onclick="deleteSelectedTeam()" class="danger" style="width:100%;padding:10px;font-size:13px;">
   DELETE TEAM PERMANENTLY
  </button>
 </div>
 <div class="panel" style="min-width:300px;">
  <h3>✎ Rename Team</h3>
  <p style="font-size:12px;margin-bottom:10px;color:#555;">
   Change a team's name. Useful for fixing duplicate name conflicts or typos.
  </p>
  <div style="margin-bottom:8px;">
   <label style="display:block;margin-bottom:4px;">Select Team:</label>
   <select id="rename-team-select" style="width:100%;padding:5px;border:2px inset #808080;font-size:13px;">
    <option value="">-- Select a team --</option>
    {team_options}
   </select>
  </div>
  <div style="margin-bottom:10px;">
   <label style="display:block;margin-bottom:4px;">New Name:</label>
   <input type="text" id="rename-team-name" placeholder="Enter new team name"
          style="width:100%;padding:5px;box-sizing:border-box;border:2px inset #808080;font-size:13px;">
  </div>
  <button onclick="renameSelectedTeam()" style="width:100%;padding:8px;font-size:13px;">
   RENAME TEAM
  </button>
 </div>
</div>

<!-- ====================== REPORTS TAB ====================== -->
<div id="tab-reports" class="tab-content">
 <div class="panel" style="min-width:400px;max-width:800px">
  <h3>📋 Warriors Report</h3>
  <p style="font-size:11px;margin:0 0 8px;color:#555">
   Complete report of all warriors, their teams, managers, IDs, and roster positions.
  </p>
  <button onclick="loadWarriorsReport()" style="margin-bottom:8px">📋 Generate Warriors Report</button>
  <div style="margin-bottom:8px;display:flex;gap:8px;font-size:11px">
   <label>Export as:</label>
   <button onclick="exportWarriorsAsCSV()" style="padding:2px 8px;font-size:11px" id="csv-export-btn" disabled>CSV</button>
   <button onclick="exportWarriorsAsJSON()" style="padding:2px 8px;font-size:11px" id="json-export-btn" disabled>JSON</button>
  </div>
  <div id="warriors-container" style="border:1px solid #ccc;height:300px;overflow-y:auto;background:#f9f9f9;font-size:10px;font-family:monospace;">
   <div style="padding:8px;color:#999;">Click "Generate Warriors Report" to load...</div>
  </div>
 </div>
 <div class="panel" style="min-width:400px;max-width:900px">
  <h3>📥 Uploaded Warriors by Manager</h3>
  <p style="font-size:11px;margin:0 0 8px;color:#555">
   View warriors currently uploaded for this turn, organized by manager. Filter by manager or view all at once.
  </p>
  <div style="margin-bottom:8px;display:flex;gap:8px;font-size:11px">
   <label style="display:flex;align-items:center;">Manager:</label>
   <select id="manager-filter-select" style="padding:4px;border:2px inset #808080;font-size:12px;flex:1;max-width:300px">
    <option value="ALL">-- All Managers --</option>
   </select>
   <button onclick="loadUploadedWarriors()" style="padding:4px 8px;font-size:11px">📥 Load</button>
  </div>
  <div style="margin-bottom:8px;display:flex;gap:8px;font-size:11px">
   <label>Export as:</label>
   <button onclick="exportUploadedAsCSV()" style="padding:2px 8px;font-size:11px" id="uploaded-csv-btn" disabled>CSV</button>
   <button onclick="exportUploadedAsJSON()" style="padding:2px 8px;font-size:11px" id="uploaded-json-btn" disabled>JSON</button>
  </div>
  <div id="uploaded-warriors-container" style="border:1px solid #ccc;height:300px;overflow-y:auto;background:#f9f9f9;font-size:10px;font-family:monospace;">
   <div style="padding:8px;color:#999;">Select a manager and click "Load" to view their uploaded warriors...</div>
  </div>
 </div>
 <div class="panel" style="min-width:400px;max-width:600px">
  <h3>📊 Activity Log</h3>
  <p style="font-size:11px;margin:0 0 8px;color:#555">
   View upload and download activity from managers.
  </p>
  <div style="margin-bottom:8px;display:flex;gap:8px;font-size:11px">
   <label>Filter by action:</label>
   <select id="activity-action-filter" style="width:120px;padding:2px;font-size:11px">
    <option value="">(all)</option>
    <option value="upload">Upload</option>
    <option value="download">Download</option>
   </select>
   <label style="margin-left:8px;">Entries:</label>
   <input type="number" id="activity-limit" value="50" min="10" max="500" style="width:50px;padding:2px;font-size:11px">
   <button onclick="loadActivityLog()" style="padding:2px 8px;font-size:11px">Load</button>
  </div>
  <div id="activity-log-container" style="border:1px solid #ccc;height:250px;overflow-y:auto;background:#f9f9f9;font-size:10px;font-family:monospace;">
   <div style="padding:8px;color:#999;">Loading...</div>
  </div>
 </div>
 <div class="panel" style="min-width:300px;max-width:500px">
  <h3>🔍 Team Validation Scan</h3>
  <p style="font-size:11px;margin:0 0 8px;color:#555">
   Checks every team file on disk for "phantom" warriors (roster size != 5).
  </p>
  <button onclick="validateTeams()">🔍 Scan All Teams</button>
  <div id="validation-results" style="margin-top:10px;border:1px solid #ccc;height:200px;overflow-y:auto;background:#f9f9f9;font-size:11px;font-family:monospace;">
   <div style="padding:8px;color:#999;">Ready to scan...</div>
  </div>
 </div>
 <div class="panel" style="min-width:400px;max-width:800px">
  <h3>🆔 Warrior ID Validation</h3>
  <p style="font-size:11px;margin:0 0 8px;color:#555">
   Checks every team file (active roster and archived) for warriors missing
   a warrior_id, or a warrior_id shared by more than one warrior.
  </p>
  <button onclick="validateWarriorIds()">🆔 Scan Warrior IDs</button>
  <div id="warrior-id-validation-results" style="margin-top:10px;border:1px solid #ccc;height:350px;overflow-y:auto;background:#f9f9f9;font-size:11px;font-family:monospace;">
   <div style="padding:8px;color:#999;">Ready to scan...</div>
  </div>
 </div>
</div>

<!-- ====================== MAINTENANCE TAB ====================== -->
<div id="tab-maint" class="tab-content">
 <div class="panel" style="min-width:220px;max-width:320px">
  <h3>⚙️ Feature Flags (Testing)</h3>
  <p style="font-size:11px;margin:0 0 10px;color:#555">Enable debug visibility for testing mechanics (hidden by default).</p>
  <label style="display:block;margin:6px 0"><input type="checkbox" id="fav-wpn" data-flag="show_favorite_weapon" style="cursor:pointer" {'checked' if cfg.get('show_favorite_weapon') else ''}>
   <span style="cursor:pointer;user-select:none">Show favorite weapon flavor</span></label>
  <label style="display:block;margin:6px 0"><input type="checkbox" id="luck-fct" data-flag="show_luck_factor" style="cursor:pointer" {'checked' if cfg.get('show_luck_factor') else ''}>
   <span style="cursor:pointer;user-select:none">Show luck factor (1-30)</span></label>
  <label style="display:block;margin:6px 0"><input type="checkbox" id="max-hp" data-flag="show_max_hp" style="cursor:pointer" {'checked' if cfg.get('show_max_hp') else ''}>
   <span style="cursor:pointer;user-select:none">Show warrior max HP</span></label>
  <div style="margin-top:8px;border-top:1px solid #ddd;padding-top:8px">
   <label style="display:block;margin:6px 0"><input type="checkbox" id="ai-enabled" data-flag="ai_teams_enabled" style="cursor:pointer" {'checked' if cfg.get('ai_teams_enabled', True) else ''}>
    <span style="cursor:pointer;user-select:none">AI teams participate each turn</span></label>
   <div style="font-size:10px;color:#666;margin-left:20px">
    Uncheck when running live playtester sessions.
   </div>
  </div>
  <div style="margin-top:8px;border-top:1px solid #ddd;padding-top:8px">
   <label style="display:block;margin:6px 0"><input type="checkbox" id="gh-push" data-flag="github_push_enabled" style="cursor:pointer" {'checked' if cfg.get('github_push_enabled', True) else ''}>
    <span style="cursor:pointer;user-select:none">Push stats to GitHub Pages after each turn</span></label>
   <div style="font-size:10px;color:#666;margin-left:20px">
    Uncheck when running test sims to avoid overwriting live stats on the website.
   </div>
  </div>
  <div style="margin-top:8px;font-size:10px;color:#888">
   Changes apply on next turn run.
  </div>
 </div>
 <div class="panel" style="min-width:260px;max-width:340px">
  <h3>🔍 Combat Debug Logging</h3>
  <p style="font-size:11px;margin:0 0 8px;color:#555">
   Select a manager's team to generate verbose fight logs.<br>
   Every fight involving their warriors produces a detailed breakdown<br>
   in <code>saves/admin_logs/turn_NNNN/</code> (admin-only).
  </p>
  <div style="margin-bottom:8px;font-size:12px">
   Currently logging: <strong id="dbg-current">{_dbg_display}</strong>
  </div>
  <label style="display:block;margin-bottom:4px;font-size:12px">Select team to log:</label>
  <select id="debug-team-select" style="width:100%;padding:4px;border:2px inset #808080;font-size:12px">
   <option value="">-- None (disable logging) --</option>
   {manager_options}
  </select><br>
  <button onclick="setDebugTeam()" style="margin-top:6px">💾 Set Debug Team</button>
 </div>
 <div class="panel" style="min-width:220px;max-width:280px">
  <h3>📊 Reports</h3>
  <p style="font-size:11px;color:#666;margin:0 0 8px">
   Regenerate and push team roster report to GitHub Pages with current data.
  </p>
  <button onclick="regenerateRoster()" style="background-color:#4a7c59;border-color:#4a7c59">📈 Regenerate Rosters</button>
  <p style="font-size:11px;color:#666;margin:8px 0">
   Regenerate and push arena stats (Top Teams, Top Warriors, etc.) to GitHub Pages with current data.
  </p>
  <button onclick="regenerateArenaStats()" style="background-color:#4a7c59;border-color:#4a7c59">📊 Regenerate Arena Stats</button>
 </div>

 <div class="panel" style="min-width:220px;max-width:280px">
  <h3>⚠️ Arena Reset</h3>
  <p style="font-size:11px;color:#800;margin:0 0 8px">
   ⚠ Full wipe: deletes ALL turn history, fight records, standings,<br>
   manager registrations, and teams. AI teams are regenerated.<br>
   Every player will need to re-register after this.
  </p>
  <button class="danger" onclick="resetArena()">🗑 Reset Arena to Turn 1</button>
  <div style="margin-top:12px;border-top:1px solid #ccc;padding-top:8px">
   <p style="font-size:11px;color:#840;margin:0 0 8px">
    Revert Progress: keeps accounts and teams but resets all records,<br>
    skills, and attribute gains back to Turn 1 baseline.
   </p>
   <button onclick="resetProgress()" style="color:#840;border-color:#840">↺ Revert All to Turn 1</button>
  </div>
 </div>
</div>

<!-- ====================== IMMORTAL ARENAS TAB ====================== -->
<div id="tab-arenas" class="tab-content" style="flex-direction:column;gap:0">

 <!-- Modal overlay for promotion/resurrection panels -->
 <div id="arena-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);z-index:1000;align-items:center;justify-content:center">
  <div style="background:#fff;border:2px solid #808080;padding:14px;max-width:700px;width:95%;max-height:80vh;overflow-y:auto;position:relative">
   <button onclick="document.getElementById('arena-modal').style.display='none'" style="position:absolute;top:6px;right:8px;font-size:14px">X</button>
   <div id="arena-modal-content"></div>
  </div>
 </div>

 <!-- Normal Arena Promotions strip -->
 <div style="background:#f5f4f0;border-bottom:1px solid #ccc;padding:8px 12px;display:flex;align-items:center;gap:12px">
  <b style="font-size:12px">THE AGONY AMPHITHEATRE (Normal Arena)</b>
  <span style="font-size:11px;color:#555">Turn {turn} &nbsp;|&nbsp;
   Promotion pending: <b style="color:{'#c80' if promo_pending_count else '#080'}">{promo_pending_count}</b>
  </span>
  <button onclick="showPromotionPanel()" style="font-size:11px;padding:2px 10px">&#9997; Manage Promotions</button>
 </div>

 <div style="display:flex;gap:10px;padding:10px;flex-wrap:wrap">

 <!-- ── Elite Spire Panel ── -->
 <div class="panel" style="min-width:320px;max-width:420px;border-color:#336;background:#f8f8ff">
  <h3 style="color:#336">✦ THE ELITE SPIRE</h3>
  <table style="font-size:12px;margin-bottom:8px">
   <tr><td>Turn</td><td><b>{elite_cfg_a.get('turn_counter',0)}</b></td></tr>
   <tr><td>State</td><td><b id="elite-state">{elite_cfg_a.get('turn_state','?').replace('_',' ').upper()}</b></td></tr>
   <tr><td>Warriors</td><td><b>{elite_warrior_count}</b></td></tr>
   <tr><td>Teams</td><td><b>{elite_team_count}</b></td></tr>
  </table>
  <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:10px">
   <button onclick="runImmortalTurn('elite')" id="elite-run-btn"
           style="background:#001a3a;color:#9cf;border-color:#336">
    ▶ Run Turn {elite_cfg_a.get('turn_counter',0)+1}
   </button>
   <button onclick="loadImmortalNewsletter('elite')"
           style="font-size:11px;padding:3px 8px"
           {'disabled' if elite_cfg_a.get('turn_counter',0) == 0 else ''}>
    📄 Load Results
   </button>
   <button onclick="clearImmortalArena('elite')"
           class="danger" style="font-size:11px;padding:3px 8px">
    🗑 Clear Arena
   </button>
  </div>
  <div id="elite-prog-wrap" class="prog-wrap" style="display:none">
   <div id="elite-prog-bar" class="prog-bar" style="width:0%"></div>
   <div id="elite-prog-lbl" class="prog-lbl">Running...</div>
  </div>
  <div id="elite-msg" style="font-size:11px;margin:4px 0"></div>

  <h3 style="color:#336;margin-top:10px">📅 Elite Schedule</h3>
  <label style="display:block;margin:4px 0;font-size:12px">
   <input type="checkbox" id="elite-sched-enabled" onchange="toggleImmortalSchedule('elite')"
          {'checked' if elite_sched_on else ''}>
   <span>Enable auto-schedule</span>
  </label>
  {_render_immortal_slots("elite", elite_slots_list)}
  <div style="margin-top:6px;display:flex;gap:4px">
   <button onclick="addImmortalSlot('elite')" style="font-size:11px;padding:2px 8px">+ Add slot</button>
   <button id="elite-save-sched-btn" onclick="saveImmortalSchedule('elite')"
           style="font-size:11px;padding:2px 8px;display:none">💾 Save Schedule</button>
  </div>
 </div>

 <!-- ── The Dead Grounds Panel ── -->
 <div class="panel" style="min-width:320px;max-width:420px;border-color:#550;background:#fffff8">
  <h3 style="color:#550">&#9760; THE DEAD GROUNDS</h3>
  <table style="font-size:12px;margin-bottom:8px">
   <tr><td>Turn</td><td><b>{vet_cfg_a.get('turn_counter',0)}</b></td></tr>
   <tr><td>State</td><td><b id="veteran-state">{vet_cfg_a.get('turn_state','?').replace('_',' ').upper()}</b></td></tr>
   <tr><td>Warriors</td><td><b>{vet_warrior_count}</b></td></tr>
   <tr><td>Teams</td><td><b>{vet_team_count}</b></td></tr>
  </table>
  <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:10px">
   <button onclick="runImmortalTurn('veteran')" id="veteran-run-btn"
           style="background:#3a3000;color:#ffd;border-color:#550">
    ▶ Run Turn {vet_cfg_a.get('turn_counter',0)+1}
   </button>
   <button onclick="loadImmortalNewsletter('veteran')"
           style="font-size:11px;padding:3px 8px"
           {'disabled' if vet_cfg_a.get('turn_counter',0) == 0 else ''}>
    📄 Load Results
   </button>
   <button onclick="clearImmortalArena('veteran')"
           class="danger" style="font-size:11px;padding:3px 8px">
    🗑 Clear Arena
   </button>
  </div>
  <div id="veteran-prog-wrap" class="prog-wrap" style="display:none">
   <div id="veteran-prog-bar" class="prog-bar" style="width:0%"></div>
   <div id="veteran-prog-lbl" class="prog-lbl">Running...</div>
  </div>
  <div id="veteran-msg" style="font-size:11px;margin:4px 0"></div>

  <h3 style="color:#550;margin-top:10px">📅 Dead Grounds Schedule</h3>
  <label style="display:block;margin:4px 0;font-size:12px">
   <input type="checkbox" id="veteran-sched-enabled" onchange="toggleImmortalSchedule('veteran')"
          {'checked' if vet_sched_on else ''}>
   <span>Enable auto-schedule</span>
  </label>
  {_render_immortal_slots("veteran", vet_slots_list)}
  <div style="margin-top:6px;display:flex;gap:4px">
   <button onclick="addImmortalSlot('veteran')" style="font-size:11px;padding:2px 8px">+ Add slot</button>
   <button id="veteran-save-sched-btn" onclick="saveImmortalSchedule('veteran')"
           style="font-size:11px;padding:2px 8px;display:none">💾 Save Schedule</button>
  </div>
 </div>

 </div><!-- /flex row -->
</div><!-- /tab-arenas -->

<script>
let _pollTimer=null;
let _isNavigating=false;  // prevents beforeunload from killing server on auto-reload
let _seenRunning=false;   // ensures poll only fires completion after turn actually started

// Tab switching function is defined in an inline script tag near the top of the body

function _abortPoll(msg){{
 stopPoll();
 document.getElementById('prog-wrap').style.display='none';
 const hint=msg.toLowerCase().includes('already')
  ?' - Click 🔓 to unlock if the previous run crashed.':'';
 show('Error: '+msg+hint,'err');
}}
async function runTurn(){{
 const pw=pw_val();
 if(!pw){{show('Enter the host password first.','err');return;}}
 show('Submitting turn...','ok');
 startPoll();
 try{{
  const r=await fetch('/api/run_turn',{{method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{host_password:pw}})}});
  const d=await r.json();
  if(!d.success){{_abortPoll(d.error);return;}}
  _seenRunning=true;
 }}catch(e){{_abortPoll('Connection error: '+e.message);}}
}}
async function rerunTurn(t){{
 const pw=pw_val();
 if(!pw){{show('Enter the host password first.','err');return;}}
 if(!confirm(`Re-run turn ${{t}}? All results from the first run will be replaced as if it never happened.`))return;
 show(`Re-running turn ${{t}}...`,'ok');
 startPoll();
 try{{
  const r=await fetch('/api/run_turn',{{method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{host_password:pw,rerun_turn:t}})}});
  const d=await r.json();
  if(!d.success){{_abortPoll(d.error);return;}}
  _seenRunning=true;
 }}catch(e){{_abortPoll('Connection error: '+e.message);}}
}}
async function regenerateRoster(){{
 const pw=pw_val();
 if(!pw){{show('Enter the host password first.','err');return;}}
 show('Regenerating roster...','ok');
 try{{
  const r=await fetch('/api/admin/regenerate_roster',{{method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{host_password:pw}})}});
  const d=await r.json();
  if(d.success){{show(d.message,'ok');}}
  else show('Error: '+d.error,'err');
 }}catch(e){{show('Connection error: '+e.message,'err');}}
}}
async function regenerateArenaStats(){{
 const pw=pw_val();
 if(!pw){{show('Enter the host password first.','err');return;}}
 show('Regenerating arena stats...','ok');
 try{{
  const r=await fetch('/api/admin/regenerate_arena_stats',{{method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{host_password:pw}})}});
  const d=await r.json();
  if(d.success){{show(d.message,'ok');}}
  else show('Error: '+d.error,'err');
 }}catch(e){{show('Connection error: '+e.message,'err');}}
}}
async function resetArena(){{
 const pw=pw_val();
 if(!pw){{show('Enter the host password first.','err');return;}}
 if(!confirm('Reset the arena to Turn 1?\\n\\nThis is a FULL wipe: all fight records, standings, manager registrations, and teams will be deleted. Every player will need to re-register.'))return;
 try{{
  const r=await fetch('/api/arena/reset',{{method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{host_password:pw}})}});
  const d=await r.json();
  if(d.success){{show('Arena reset. Reloading...','ok');setTimeout(()=>{{_isNavigating=true;location.href='/admin?t='+Date.now();}},1500);}}
  else show('Error: '+d.error,'err');
 }}catch(e){{show('Connection error: '+e.message,'err');}}
}}
async function resetProgress(){{
 const pw=pw_val();
 if(!pw){{show('Enter the host password first.','err');return;}}
 if(!confirm('Revert all progress to Turn 1?\\n\\nThis will keep all accounts and teams, but will reset all win/loss records, skills, and attribute gains to their initial values.\\n\\nThis cannot be undone.'))return;
 try{{
  const r=await fetch('/api/arena/reset_progress',{{method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{host_password:pw}})}});
  const d=await r.json();
  if(d.success){{
   show('All progress reverted. Reloading...','ok');
   setTimeout(()=>{{_isNavigating=true;location.reload();}},1500);
  }} else show('Error: '+d.error,'err');
 }}catch(e){{show('Connection error: '+e.message,'err');}}
}}
async function unlockTurn(){{
 const pw=pw_val();
 if(!pw){{show('Enter the host password first.','err');return;}}
 if(!confirm('Force unlock the turn state? Only do this if a previous run crashed or hung.')) return;
 try{{
  const r=await fetch('/api/admin/unlock',{{method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{host_password:pw}})}});
  const d=await r.json();
  if(d.success){{
   show('Turn state unlocked.','ok');
   setTimeout(()=>{{_isNavigating=true;location.reload();}},1000);
  }} else show('Error: '+d.error,'err');
 }}catch(e){{show('Connection error: '+e.message,'err');}}
}}
function pw_val(){{return document.getElementById('hp')?.value||'';}}
function savePwToStorage(){{
  const hp=document.getElementById('hp');
  if(hp && hp.value){{localStorage.setItem('admin_password',hp.value);}}
}}
function loadPwFromStorage(){{
  const hp=document.getElementById('hp');
  const saved=localStorage.getItem('admin_password');
  if(hp && saved){{hp.value=saved;}}
}}
function startPoll(){{
 _seenRunning=false;
 document.getElementById('prog-wrap').style.display='block';
 _pollTimer=setInterval(pollProgress,800);
}}
function stopPoll(){{clearInterval(_pollTimer);_pollTimer=null;}}
async function pollProgress(){{
 try{{
  const d=await(await fetch('/api/progress')).json();
  const pct=d.total>0?Math.round(d.done/d.total*100):0;
  document.getElementById('prog-bar').style.width=pct+'%';
  document.getElementById('prog-lbl').textContent=d.message||'Running...';
  if(d.running) _seenRunning=true;
  if(!d.running && d.done>0 && _seenRunning){{
   stopPoll();
   show(`Done - ${{d.message}}`,'ok');
   setTimeout(()=>{{_isNavigating=true;location.href='/admin?t='+Date.now();}},2000);
  }}
 }}catch(e){{}}
}}
function show(t,c){{const m=document.getElementById('msg');m.textContent=t;m.className=c;m.style.display='block';}}

const _SCHED_DAYS=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];

function _dayOptions(selected){{
  return _SCHED_DAYS.map(d=>`<option${{d===selected?' selected':''}}>${{d}}</option>`).join('');
}}

function addSchedSlot(){{
  const container=document.getElementById('sched-slots');
  if(!container) return;
  const rows=container.querySelectorAll('.sched-row');
  if(rows.length>=7){{show('Maximum 7 slots (one per day).','err');return;}}
  const div=document.createElement('div');
  div.className='sched-row';
  div.style.cssText='display:flex;align-items:center;gap:4px';
  div.innerHTML=`<select class="sched-day" onchange="saveSchedule()" style="font-size:12px;border:2px inset #808080">${{_dayOptions('Friday')}}</select>`
    +`<input class="sched-time" type="time" value="20:00" onchange="saveSchedule()" style="font-size:12px;border:2px inset #808080;width:88px">`
    +`<button onclick="removeSchedSlot(this)" style="font-size:11px;padding:1px 6px;background:#eee;border-color:#ccc;color:#600">✕</button>`;
  container.appendChild(div);
  const addBtn=document.getElementById('sched-add-btn');
  if(addBtn) addBtn.disabled=(container.querySelectorAll('.sched-row').length>=7);
  saveSchedule();
}}

function removeSchedSlot(btn){{
  const row=btn.closest('.sched-row');
  if(!row) return;
  const container=document.getElementById('sched-slots');
  // Always keep at least 0 rows (schedule can be empty with the checkbox disabled)
  row.remove();
  const addBtn=document.getElementById('sched-add-btn');
  if(addBtn) addBtn.disabled=(container.querySelectorAll('.sched-row').length>=7);
  saveSchedule();
}}

async function saveSchedule(){{
  const pw=pw_val()||prompt('Host password required to save the schedule:');
  if(!pw){{show('Schedule not saved - host password required.','err');return false;}}
  const hp=document.getElementById('hp'); if(hp && !hp.value) hp.value=pw;
  const enabled=!!document.getElementById('sched-enabled')?.checked;
  const slots=[...document.querySelectorAll('#sched-slots .sched-row')].map(row=>{{
    const day=row.querySelector('.sched-day')?.value||'Friday';
    const time=row.querySelector('.sched-time')?.value||'20:00';
    return {{day,time}};
  }});
  try{{
   const r=await fetch('/api/admin/update',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{host_password:pw,schedule_enabled:enabled,schedule_slots:slots}})}});
   const d=await r.json();
   if(d.success){{
    const slotDesc=slots.length?slots.map(s=>`${{s.day}} ${{s.time}}`).join(', '):'no slots';
    show(`Saved: ${{enabled?'enabled':'disabled'}} - ${{slotDesc}}`,'ok');
    await refreshScheduleStatus(); return true;
   }}
   else{{show('Error: '+(d.error||'update failed'),'err');return false;}}
  }}catch(e){{show('Connection error: '+e.message,'err');return false;}}
}}

function toggleSchedule(){{ saveSchedule(); }}

async function refreshScheduleStatus(){{
  try{{
   const r=await fetch('/api/schedule');
   const d=await r.json();
   const el=document.getElementById('sched-next');
   if(!el) return;
   if(!d.success){{el.textContent='Schedule status unavailable.'; return;}}
   let nextTxt='Auto-schedule disabled';
   if(d.schedule_enabled && d.schedule_slots && d.schedule_slots.length){{
    nextTxt='Next runs: '+d.schedule_slots.map(s=>`${{s.day}} ${{s.time}}`).join(', ');
   }}
   const last=d.schedule_last_run_turn
    ? `Last auto-run: turn ${{d.schedule_last_run_turn}}${{d.schedule_last_run_at?` at ${{d.schedule_last_run_at}}`:''}}${{d.schedule_last_run_result?` - ${{d.schedule_last_run_result}}`:''}}` : 'Last auto-run: never';
   el.textContent=`${{nextTxt}} | ${{last}}`;
   const badge=document.getElementById('sched-top-badge');
   if(badge) badge.style.display=d.schedule_enabled?'inline-block':'none';
  }}catch(e){{}}
}}

setTimeout(refreshScheduleStatus, 0);

// Persist feature-flag toggles so they survive turn reloads.
window.toggleFlag = async function(evt,key){{
  // currentTarget can be null in inline onchange handlers in some browsers - fall back to target
  const el=evt?(evt.currentTarget||evt.target):null;
  const val=el?el.checked:false;
 let pw=pw_val();
 if(!pw){{
  pw=prompt('Host password required to save this flag:');
  if(!pw){{
   show('Flag not saved - host password required.','err');
   if(el) el.checked=!val;
   return;
  }}
  const hp=document.getElementById('hp'); if(hp) hp.value=pw;
 }}
 try{{
  const r=await fetch('/api/admin/update',{{method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{host_password:pw,[key]:val}})}});
  const d=await r.json();
  if(d.success){{show(`Saved: ${{key}} = ${{val}}`,'ok');}}
  else{{show('Error: '+(d.error||'update failed'),'err');if(el) el.checked=!val;}}
 }}catch(e){{show('Connection error: '+e.message,'err');if(el) el.checked=!val;}}
}};

// FIXED DELETE MANAGER FUNCTION
async function deleteSelectedManager() {{
    const select = document.getElementById('delete-manager-select');
    const mid = select.value;
    if (!mid) {{
        alert("Please select a manager to delete.");
        return;
    }}

    const fullText = select.options[select.selectedIndex].text;
    const managerName = fullText.split(" (ID:")[0];   // Clean name for display

    // First safety confirmation
    if (!confirm(`⚠ DANGER ZONE ⚠\n\nYou are about to delete the manager account:\n\n${{managerName}}\n\nTheir account and current turn uploads will be removed, but their teams will remain in the system and can be accessed if they re-register.\n\nThis action CANNOT be undone.\n\nContinue?`)) {{
        return;
    }}

    // Second confirmation - must type DELETE
    const confirmText = prompt(`Type the word DELETE to confirm deleting ${{managerName}}:`);
    if (confirmText !== "DELETE") {{
        alert("Delete cancelled.");
        return;
    }}

    // Host password prompt
    const hostPassword = prompt("Enter your host password to proceed with deletion:");
    if (!hostPassword) {{
        alert("Delete cancelled - no password provided.");
        return;
    }}

    try {{
        const resp = await fetch('/api/admin/delete_manager', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{
                host_password: hostPassword,
                manager_id: mid
            }})
        }});

        const result = await resp.json();

        if (result.success) {{
            alert(result.message || `Manager '${{managerName}}' deleted successfully.`);
            _isNavigating=true; location.reload();  // Refresh dropdown and page
        }} else {{
            alert("Failed to delete: " + (result.error || "Unknown error"));
        }}
    }} catch(e) {{
        alert("Connection error: " + e.message);
    }}
}}
// =====================================================================

async function renameSelectedManager() {{
    const select = document.getElementById('rename-manager-select');
    const mid = select.value;
    const newName = document.getElementById('rename-manager-name').value.trim();
    if (!mid) {{ alert('Please select a manager to rename.'); return; }}
    if (!newName) {{ alert('Please enter a new name.'); return; }}

    const oldLabel = select.options[select.selectedIndex].text;
    const oldName  = oldLabel.split(' (ID:')[0];

    if (!confirm(`Rename "${{oldName}}" to "${{newName}}"?\n\nThis will update their manager name in all teams and standings.`)) return;

    const pw = pw_val() || prompt('Enter host password:');
    if (!pw) {{ show('Rename cancelled - no password provided.', 'err'); return; }}
    const hp = document.getElementById('hp'); if (hp) hp.value = pw;

    try {{
        const r = await fetch('/api/admin/rename_manager', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{ host_password: pw, manager_id: mid, new_name: newName }})
        }});
        const d = await r.json();
        if (d.success) {{
            alert(d.message || `Manager renamed successfully.`);
            _isNavigating = true; location.reload();
        }} else {{
            show('Rename failed: ' + (d.error || 'Unknown error'), 'err');
        }}
    }} catch(e) {{
        show('Connection error: ' + e.message, 'err');
    }}
}}
// =====================================================================

async function deleteSelectedTeam() {{
    const select = document.getElementById('delete-team-select');
    const tid = select.value;
    if (!tid) {{ alert('Please select a team to delete.'); return; }}

    const oldLabel = select.options[select.selectedIndex].text;
    const teamName  = oldLabel.split(' (ID:')[0];

    if (!confirm(`⚠ DANGER ⚠\\n\\nDelete team "${{teamName}}" (ID: ${{tid}})?\\n\\nThis will remove it from the server and notify the manager to delete it locally.`)) return;
    
    const pw = pw_val() || prompt('Enter host password:');
    if (!pw) return;

    try {{
        const r = await fetch('/api/admin/delete_team', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{ host_password: pw, team_id: tid }})
        }});
        const d = await r.json();
        if (d.success) {{
            alert(d.message); _isNavigating = true; location.reload();
        }} else {{ alert('Error: ' + d.error); }}
    }} catch(e) {{ alert('Connection error: ' + e.message); }}
}}

async function downloadManagerFiles() {{
    const select = document.getElementById('download-manager-select');
    const mid = select.value;
    if (!mid) {{
        alert('Please select a manager.');
        return;
    }}

    const managerName = select.options[select.selectedIndex].text.split(' (ID:')[0];
    const pw = pw_val() || prompt('Enter host password:');
    if (!pw) {{ show('Download cancelled - no password provided.', 'err'); return; }}
    const hp = document.getElementById('hp'); if (hp) hp.value = pw;

    try {{
        const r = await fetch('/api/admin/download_manager_files', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{ host_password: pw, manager_id: mid }})
        }});

        if (!r.ok) {{ const d = await r.json(); show('Download failed: ' + (d.error || 'Unknown error'), 'err'); return; }}

        const blob = await r.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `manager_${{mid}}_files.zip`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        show(`Downloaded files for ${{managerName}}`, 'ok');
    }} catch(e) {{ show('Download error: ' + e.message, 'err'); }}
}}
// =====================================================================

async function renameSelectedTeam() {{
    const select = document.getElementById('rename-team-select');
    const tid = select.value;
    const newName = document.getElementById('rename-team-name').value.trim();
    if (!tid) {{ alert('Please select a team to rename.'); return; }}
    if (!newName) {{ alert('Please enter a new name.'); return; }}

    const oldLabel = select.options[select.selectedIndex].text;
    const oldName  = oldLabel.split(' (ID:')[0];

    if (!confirm(`Rename team "${{oldName}}" to "${{newName.toUpperCase()}}"?`)) return;

    const pw = pw_val() || prompt('Enter host password:');
    if (!pw) return;

    try {{
        const r = await fetch('/api/admin/rename_team', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{ host_password: pw, team_id: tid, new_name: newName }})
        }});
        const d = await r.json();
        if (d.success) {{
            alert(d.message); _isNavigating = true; location.reload();
        }} else {{ alert('Error: ' + d.error); }}
    }} catch(e) {{ alert('Connection error: ' + e.message); }}
}}

function updateDeleteTeamOptions() {{
 const managerId = document.getElementById('delete-team-manager-select').value;
 const teamSelect = document.getElementById('delete-team-select');
 teamSelect.innerHTML = '<option value="">-- Select a team --</option>';
 if (!managerId) return;
 const allTeams = {team_options_json};
 const parser = new DOMParser();
 const doc = parser.parseFromString('<div>' + allTeams + '</div>', 'text/html');
 const options = doc.querySelectorAll('option');
 options.forEach(opt => {{
  if (opt.getAttribute('data-mid') === managerId) {{
   const newOpt = document.createElement('option');
   newOpt.value = opt.value;
   newOpt.textContent = opt.textContent;
   teamSelect.appendChild(newOpt);
  }}
 }});
}}

async function deleteSelectedTeam() {{
 const managerId = document.getElementById('delete-team-manager-select').value;
 const teamId = document.getElementById('delete-team-select').value;
 if (!managerId) {{ show('Select a manager first', 'err'); return; }}
 if (!teamId) {{ show('Select a team first', 'err'); return; }}
 const teamLabel = document.getElementById('delete-team-select').options[document.getElementById('delete-team-select').selectedIndex].text;
 if (!confirm('⚠️  PERMANENT DELETE CONFIRMATION\\n\\nAre you ABSOLUTELY SURE you want to permanently delete this team?\\n\\nTeam: ' + teamLabel + '\\n\\nThe manager will be notified on next login and the team will be completely removed from their client.')) return;
 const pw = pw_val();
 if (!pw) {{ show('Enter the host password first.', 'err'); return; }}
 try {{
  const r = await fetch('/api/admin/delete_team', {{
   method: 'POST',
   headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{host_password: pw, team_id: parseInt(teamId)}})
  }});
  const d = await r.json();
  if (d.success) {{
   show(d.message, 'ok');
   document.getElementById('delete-team-manager-select').value = '';
   document.getElementById('delete-team-select').value = '';
   document.getElementById('delete-team-select').innerHTML = '<option value="">-- Select a team --</option>';
  }} else {{
   show('Error: ' + d.error, 'err');
  }}
 }} catch(e) {{ show('Connection error: ' + e.message, 'err'); }}
}}

async function loadActivityLog() {{
 const pw = pw_val();
 if (!pw) {{ show('Enter the host password first.', 'err'); return; }}
 const limit = document.getElementById('activity-limit').value || '50';
 const action = document.getElementById('activity-action-filter').value || '';
 const container = document.getElementById('activity-log-container');
 container.innerHTML = '<div style="padding:8px;color:#999;">Loading...</div>';
 try {{
  const url = new URL('/api/admin/activity_log', window.location.origin);
  url.searchParams.append('limit', limit);
  if (action) url.searchParams.append('action', action);
  const r = await fetch(url, {{
   method: 'POST',
   headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{host_password: pw}})
  }});
  const d = await r.json();
  if (d.success) {{
   if (!d.entries || d.entries.length === 0) {{
    container.innerHTML = '<div style="padding:8px;color:#999;">No activity logged yet.</div>';
    return;
   }}
   let html = '';
   d.entries.forEach(entry => {{
    const action = entry.action || '';
    const color = action.includes('upload') ? '#080' : action.includes('download') ? '#08d' : '#666';
    html += `<div style="padding:4px 8px;border-bottom:1px solid #ddd;color:${{color}};">
     <strong>${{entry.timestamp}}</strong> | ${{entry.action}} | ${{entry.manager_name}} (#${{entry.manager_id}})
     <br><span style="color:#666;font-size:9px;">${{entry.details}}</span></div>`;
   }});
   container.innerHTML = html;
  }} else {{
   container.innerHTML = `<div style="padding:8px;color:#c00;">Error: ${{d.error}}</div>`;
  }}
 }} catch(e) {{
  container.innerHTML = `<div style="padding:8px;color:#c00;">Error: ${{e.message}}</div>`;
 }}
}}

async function setDebugTeam() {{
 const sel = document.getElementById('debug-team-select');
 const mid = sel.value;
 const pw = pw_val();
 if (!pw) {{ show('Enter the host password first.', 'err'); return; }}
 try {{
  const r = await fetch('/api/admin/set_debug_team', {{
   method: 'POST',
   headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{host_password: pw, manager_id: mid}})
  }});
  const d = await r.json();
  if (d.success) {{
   const label = mid ? sel.options[sel.selectedIndex].text : 'None (disabled)';
   document.getElementById('dbg-current').textContent = label;
   show('Debug team saved: ' + (d.manager_name || 'None (disabled)'), 'ok');
  }} else show('Error: ' + (d.error || 'update failed'), 'err');
 }} catch(e) {{ show('Connection error: ' + e.message, 'err'); }}
}}

async function validateTeams() {{
 const pw = pw_val();
 if (!pw) {{ show('Enter the host password first.', 'err'); return; }}
 const container = document.getElementById('validation-results');
 container.innerHTML = '<div style="padding:8px;color:#999;">Scanning...</div>';
 try {{
  const r = await fetch('/api/admin/validate_teams', {{
   method: 'POST',
   headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{host_password: pw}})
  }});
  const d = await r.json();
  if (d.success) {{
   if (!d.teams || d.teams.length === 0) {{
    container.innerHTML = '<div style="padding:8px;color:#999;">No teams found.</div>';
    return;
   }}
   let html = '<table style="width:100%;border-collapse:collapse;">';
   html += '<tr style="background:#eee"><th>ID</th><th>Team Name</th><th>Cnt</th><th>Status</th></tr>';
   d.teams.forEach(t => {{
    const statusColor = t.is_valid ? '#060' : '#c00';
    const statusTxt = t.is_valid ? 'OK' : '⚠ PHANTOM';
    const rowBg = t.is_valid ? '' : 'style="background:#fee;"';
    html += `<tr ${{rowBg}} style="border-bottom:1px solid #ddd">
     <td>${{t.team_id}}</td>
     <td title="Warriors: ${{t.warriors.join(', ')}}\">${{t.team_name}}</td>
     <td style="text-align:center">${{t.warrior_count}}</td>
     <td style="color:${{statusColor}};font-weight:bold">${{statusTxt}}</td>
    </tr>`;
   }});
   html += '</table>';
   container.innerHTML = html;
  }} else {{
   container.innerHTML = `<div style="padding:8px;color:#c00;">Error: ${{d.error}}</div>`;
  }}
 }} catch(e) {{ container.innerHTML = `<div style="padding:8px;color:#c00;">Error: ${{e.message}}</div>`; }}
}}

async function validateWarriorIds() {{
 const pw = pw_val();
 if (!pw) {{ show('Enter the host password first.', 'err'); return; }}
 const container = document.getElementById('warrior-id-validation-results');
 container.innerHTML = '<div style="padding:8px;color:#999;">Scanning...</div>';
 try {{
  const r = await fetch('/api/admin/validate_warrior_ids', {{
   method: 'POST',
   headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{host_password: pw}})
  }});
  const d = await r.json();
  if (!d.success) {{
   container.innerHTML = `<div style="padding:8px;color:#c00;">Error: ${{d.error}}</div>`;
   return;
  }}
  _warriorIdData = d.warriors || [];
  const summaryOk = d.missing_count === 0 && d.duplicate_count === 0;
  const summary = summaryOk
   ? `<div style="padding:4px;color:#060;font-weight:bold">✅ All ${{d.total_warriors}} warriors across ${{d.total_teams}} teams have a valid, unique warrior_id.</div>`
   : `<div style="padding:4px;color:#c00;font-weight:bold">⚠ ${{d.missing_count}} missing, ${{d.duplicate_count}} duplicate warrior_id(s) out of ${{d.total_warriors}} warriors</div>`;

  let html = summary;
  html += '<div style="margin:4px 0"><input type="text" id="wid-filter" placeholder="Filter by name/team/manager..." '
   + 'style="width:100%;padding:3px;font-size:11px;box-sizing:border-box" oninput="renderWarriorIdTable()"></div>';
  html += '<div id="wid-table-wrap"></div>';
  container.innerHTML = html;
  renderWarriorIdTable();
 }} catch(e) {{ container.innerHTML = `<div style="padding:8px;color:#c00;">Error: ${{e.message}}</div>`; }}
}}

let _warriorIdData = [];

function renderWarriorIdTable() {{
 const wrap = document.getElementById('wid-table-wrap');
 if (!wrap) return;
 const filterEl = document.getElementById('wid-filter');
 const q = (filterEl ? filterEl.value : '').toLowerCase().trim();
 const rows = _warriorIdData.filter(w => !q ||
  w.warrior_name.toLowerCase().includes(q) ||
  w.team_name.toLowerCase().includes(q) ||
  w.manager_name.toLowerCase().includes(q) ||
  String(w.warrior_id).includes(q));

 const statusColor = {{missing: '#c00', duplicate: '#a60', ok: '#060'}};
 const rowBg = {{missing: 'background:#fee', duplicate: 'background:#ffe8cc', ok: ''}};

 let html = '<table style="width:100%;border-collapse:collapse">';
 html += '<tr style="background:#eee;position:sticky;top:0"><th>Warrior</th><th>ID</th><th>Team</th><th>Manager</th><th>Slot</th><th>Status</th></tr>';
 rows.forEach(w => {{
  html += `<tr style="${{rowBg[w.status]}};border-bottom:1px solid #ddd">
   <td>${{w.warrior_name}}</td>
   <td>${{w.warrior_id ?? '—'}}</td>
   <td>${{w.team_name}} (${{w.team_id}})</td>
   <td>${{w.manager_name}}</td>
   <td>${{w.slot}}</td>
   <td style="color:${{statusColor[w.status]}};font-weight:bold">${{w.status.toUpperCase()}}</td>
  </tr>`;
 }});
 html += '</table>';
 if (rows.length === 0) html = '<div style="padding:8px;color:#999;">No matching warriors.</div>';
 wrap.innerHTML = html;
}}

let _warriorsData = null;

async function loadWarriorsReport() {{
 const pw = pw_val();
 if (!pw) {{ show('Enter the host password first.', 'err'); return; }}
 const container = document.getElementById('warriors-container');
 container.innerHTML = '<div style="padding:8px;color:#999;">Loading...</div>';
 try {{
  const r = await fetch('/api/admin/warriors_report', {{
   method: 'POST',
   headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{host_password: pw}})
  }});
  const d = await r.json();
  if (d.success) {{
   _warriorsData = d.warriors;
   if (!d.warriors || d.warriors.length === 0) {{
    container.innerHTML = '<div style="padding:8px;color:#999;">No warriors found.</div>';
    return;
   }}
   document.getElementById('csv-export-btn').disabled = false;
   document.getElementById('json-export-btn').disabled = false;
   let html = '<table style="width:100%;border-collapse:collapse;font-size:11px;">';
   html += '<tr style="background:#eee;position:sticky;top:0;"><th style="padding:4px;text-align:left;border:1px solid #999;">Warrior Name</th><th style="padding:4px;text-align:center;border:1px solid #999;">Team ID</th><th style="padding:4px;text-align:left;border:1px solid #999;">Team Name</th><th style="padding:4px;text-align:left;border:1px solid #999;">Manager</th><th style="padding:4px;text-align:center;border:1px solid #999;">Slot</th><th style="padding:4px;text-align:center;border:1px solid #999;">W-L-K</th></tr>';
   d.warriors.forEach(w => {{
    const wlk = `${{w.wins}}-${{w.losses}}-${{w.kills}}`;
    const deadMark = w.is_dead ? '†' : '';
    const bgColor = w.is_dead ? 'background:#fee;' : '';
    html += `<tr style="border-bottom:1px solid #ddd;${{bgColor}}"><td style="padding:4px;border:1px solid #ddd;"><span title="${{w.is_dead ? 'DEAD' : 'Active'}}">${{deadMark}}</span> ${{w.warrior_name}}</td><td style="padding:4px;border:1px solid #ddd;text-align:center;">${{w.team_id}}</td><td style="padding:4px;border:1px solid #ddd;">${{w.team_name}}</td><td style="padding:4px;border:1px solid #ddd;">${{w.manager_name}}</td><td style="padding:4px;border:1px solid #ddd;text-align:center;">${{w.slot_index}}</td><td style="padding:4px;border:1px solid #ddd;text-align:center;">${{wlk}}</td></tr>`;
   }});
   html += '</table>';
   container.innerHTML = html;
  }} else {{
   container.innerHTML = `<div style="padding:8px;color:#c00;">Error: ${{d.error}}</div>`;
  }}
 }} catch(e) {{ container.innerHTML = `<div style="padding:8px;color:#c00;">Error: ${{e.message}}</div>`; }}
}}

function exportWarriorsAsCSV() {{
 if (!_warriorsData || _warriorsData.length === 0) {{
  show('No warriors data loaded.', 'err');
  return;
 }}
 let csv = 'Warrior Name,Team ID,Team Name,Manager,Slot Index,Wins,Losses,Kills,Total Fights,Is Dead\\n';
 _warriorsData.forEach(w => {{
  const isDeadStr = w.is_dead ? 'Yes' : 'No';
  csv += `"${{w.warrior_name}}","${{w.team_id}}","${{w.team_name}}","${{w.manager_name}}","${{w.slot_index}}","${{w.wins}}","${{w.losses}}","${{w.kills}}","${{w.total_fights}}","${{isDeadStr}}"\\n`;
 }});
 const blob = new Blob([csv], {{type: 'text/csv;charset=utf-8;'}});
 const link = document.createElement('a');
 link.href = URL.createObjectURL(blob);
 link.download = 'warriors_report.csv';
 link.click();
 show('Warriors report exported as CSV', 'ok');
}}

function exportWarriorsAsJSON() {{
 if (!_warriorsData || _warriorsData.length === 0) {{
  show('No warriors data loaded.', 'err');
  return;
 }}
 const json = JSON.stringify(_warriorsData, null, 2);
 const blob = new Blob([json], {{type: 'application/json;charset=utf-8;'}});
 const link = document.createElement('a');
 link.href = URL.createObjectURL(blob);
 link.download = 'warriors_report.json';
 link.click();
 show('Warriors report exported as JSON', 'ok');
}}

let _uploadedWarriorsData = null;
let _uploadedManagersList = [];

async function initUploadedWarriorsDropdown() {{
 const pw = pw_val();
 if (!pw) return;
 try {{
  const r = await fetch('/api/admin/uploaded_warriors', {{
   method: 'POST',
   headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{host_password: pw}})
  }});
  const d = await r.json();
  if (d.success && d.managers) {{
   _uploadedManagersList = Object.keys(d.managers).sort();
   const sel = document.getElementById('manager-filter-select');
   _uploadedManagersList.forEach(mgr => {{
    const opt = document.createElement('option');
    opt.value = mgr;
    opt.textContent = mgr;
    sel.appendChild(opt);
   }});
  }}
 }} catch(e) {{}}
}}

async function loadUploadedWarriors() {{
 const pw = pw_val();
 if (!pw) {{ show('Enter the host password first.', 'err'); return; }}
 const selectedMgr = document.getElementById('manager-filter-select').value;
 const container = document.getElementById('uploaded-warriors-container');
 container.innerHTML = '<div style="padding:8px;color:#999;">Loading...</div>';
 try {{
  const r = await fetch('/api/admin/uploaded_warriors', {{
   method: 'POST',
   headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{host_password: pw}})
  }});
  const d = await r.json();
  if (d.success && d.managers) {{
   let filteredWarriors = [];
   Object.entries(d.managers).forEach(([mgr, mgr_data]) => {{
    if (selectedMgr === 'ALL' || mgr === selectedMgr) {{
     mgr_data.warriors.forEach(w => {{
      filteredWarriors.push(w);
     }});
    }}
   }});
   _uploadedWarriorsData = filteredWarriors;
   if (filteredWarriors.length === 0) {{
    container.innerHTML = '<div style="padding:8px;color:#999;">No warriors found for selected manager.</div>';
    return;
   }}
   document.getElementById('uploaded-csv-btn').disabled = false;
   document.getElementById('uploaded-json-btn').disabled = false;
   let html = '<table style="width:100%;border-collapse:collapse;font-size:11px;">';
   html += '<tr style="background:#eee;position:sticky;top:0;"><th style="padding:4px;border:1px solid #999;text-align:left;">Warrior Name</th><th style="padding:4px;border:1px solid #999;text-align:left;">Manager</th><th style="padding:4px;border:1px solid #999;text-align:left;">Team</th><th style="padding:4px;border:1px solid #999;text-align:center;">Slot</th><th style="padding:4px;border:1px solid #999;text-align:center;">Wins</th><th style="padding:4px;border:1px solid #999;text-align:center;">Losses</th><th style="padding:4px;border:1px solid #999;text-align:center;">Kills</th><th style="padding:4px;border:1px solid #999;text-align:center;">Total Fights</th><th style="padding:4px;border:1px solid #999;text-align:left;">Uploaded</th></tr>';
   filteredWarriors.forEach(w => {{
    const deadMark = w.is_dead ? '† ' : '';
    const deadBg = w.is_dead ? 'background:#fee;' : '';
    html += `<tr style="border-bottom:1px solid #ddd;${{deadBg}}"><td style="padding:4px;border:1px solid #ddd;">${{deadMark}}${{w.warrior_name}}</td><td style="padding:4px;border:1px solid #ddd;">${{w.manager_name}}</td><td style="padding:4px;border:1px solid #ddd;">${{w.team_name}}</td><td style="padding:4px;border:1px solid #ddd;text-align:center;">${{w.slot_index}}</td><td style="padding:4px;border:1px solid #ddd;text-align:center;">${{w.wins}}</td><td style="padding:4px;border:1px solid #ddd;text-align:center;">${{w.losses}}</td><td style="padding:4px;border:1px solid #ddd;text-align:center;">${{w.kills}}</td><td style="padding:4px;border:1px solid #ddd;text-align:center;">${{w.total_fights}}</td><td style="padding:4px;border:1px solid #ddd;font-size:9px;">${{w.uploaded_at}}</td></tr>`;
   }});
   html += '</table>';
   container.innerHTML = html;
  }} else {{
   container.innerHTML = `<div style="padding:8px;color:#c00;">Error: ${{d.error}}</div>`;
  }}
 }} catch(e) {{ container.innerHTML = `<div style="padding:8px;color:#c00;">Error: ${{e.message}}</div>`; }}
}}

function exportUploadedAsCSV() {{
 if (!_uploadedWarriorsData || _uploadedWarriorsData.length === 0) {{
  show('No warriors data loaded.', 'err');
  return;
 }}
 let csv = 'Warrior Name,Manager,Team,Slot,Wins,Losses,Kills,Total Fights,Is Dead,Uploaded At\\n';
 _uploadedWarriorsData.forEach(w => {{
  const isDeadStr = w.is_dead ? 'Yes' : 'No';
  csv += `"${{w.warrior_name}}","${{w.manager_name}}","${{w.team_name}}","${{w.slot_index}}","${{w.wins}}","${{w.losses}}","${{w.kills}}","${{w.total_fights}}","${{isDeadStr}}","${{w.uploaded_at}}"\\n`;
 }});
 const blob = new Blob([csv], {{type: 'text/csv;charset=utf-8;'}});
 const link = document.createElement('a');
 link.href = URL.createObjectURL(blob);
 link.download = 'uploaded_warriors.csv';
 link.click();
 show('Uploaded warriors exported as CSV', 'ok');
}}

function exportUploadedAsJSON() {{
 if (!_uploadedWarriorsData || _uploadedWarriorsData.length === 0) {{
  show('No warriors data loaded.', 'err');
  return;
 }}
 const json = JSON.stringify(_uploadedWarriorsData, null, 2);
 const blob = new Blob([json], {{type: 'application/json;charset=utf-8;'}});
 const link = document.createElement('a');
 link.href = URL.createObjectURL(blob);
 link.download = 'uploaded_warriors.json';
 link.click();
 show('Uploaded warriors exported as JSON', 'ok');
}}

// =====================================================================

document.addEventListener('DOMContentLoaded',()=>{{
 loadPwFromStorage();  // Load saved password from localStorage
 initUploadedWarriorsDropdown();
 // Wire feature-flag checkboxes via JS so no inline onchange globals needed
 document.querySelectorAll('input[data-flag]').forEach(el=>{{
  el.addEventListener('change', async function(){{
   const key=this.dataset.flag;
   const val=this.checked;
   let pw=pw_val();
   if(!pw){{
    pw=prompt('Host password required to save this flag:');
    if(!pw){{show('Flag not saved - host password required.','err');this.checked=!val;return;}}
    const hp=document.getElementById('hp');if(hp) hp.value=pw;
   }}
   try{{
    const r=await fetch('/api/admin/update',{{method:'POST',
     headers:{{'Content-Type':'application/json'}},
     body:JSON.stringify({{host_password:pw,[key]:val}})}});
    const d=await r.json();
    if(d.success){{show(`Saved: ${{key}} = ${{val}}`,'ok');}}
    else{{show('Error: '+(d.error||'update failed'),'err');this.checked=!val;}}
   }}catch(e){{show('Connection error: '+e.message,'err');this.checked=!val;}}
  }});
 }});
}});

// Browser close detection - only shut down on real tab close, not auto-reloads
window.addEventListener('beforeunload', () => {{
  if(!_isNavigating) navigator.sendBeacon('/api/shutdown', '');
}});

// ── Immortal Arena JS ─────────────────────────────────────────────────────
function getPw(){{return document.getElementById('hp')?.value||'';}}

async function runImmortalTurn(arena){{
  const pw=getPw();
  if(!pw){{alert('Enter host password first.');return;}}
  const wrap=document.getElementById(arena+'-prog-wrap');
  const bar=document.getElementById(arena+'-prog-bar');
  const lbl=document.getElementById(arena+'-prog-lbl');
  const msg=document.getElementById(arena+'-msg');
  const btn=document.getElementById(arena+'-run-btn');
  wrap.style.display='block'; bar.style.width='15%'; lbl.textContent='Submitting...';
  btn.disabled=true; msg.textContent='';
  try{{
    const r=await fetch('/api/run_turn',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{host_password:pw,arena:arena}})}});
    const d=await r.json();
    if(d.success){{
      bar.style.width='100%';lbl.textContent='Done!';
      msg.innerHTML='<span style="color:#080">Turn '+d.turn_number+' complete: '+d.fights+' fights across '+d.teams+' teams.</span>';
      setTimeout(()=>{{bar.style.width='0%';wrap.style.display='none';}},3000);
    }}else{{
      bar.style.width='0%';wrap.style.display='none';
      msg.innerHTML='<span style="color:#800">Error: '+(d.error||'unknown')+'</span>';
    }}
  }}catch(e){{
    wrap.style.display='none';
    msg.innerHTML='<span style="color:#800">Connection error: '+e.message+'</span>';
  }}finally{{btn.disabled=false;}}
}}

async function clearImmortalArena(arena){{
  const pw=getPw();
  if(!pw){{alert('Enter host password first.');return;}}
  const label={{'elite':'The Elite Spire','veteran':'The Dead Grounds'}}[arena]||arena;
  if(!confirm('Clear ALL warriors from '+label+'?\\n\\nWarriors will be returned to the Normal Arena. Turn records and standings will be reset to zero. Individual warrior W-L-K records are preserved.'))return;
  const msg=document.getElementById(arena+'-msg');
  msg.textContent='Clearing...';
  try{{
    const r=await fetch('/api/admin/clear_arena',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{host_password:pw,arena:arena}})}});
    const d=await r.json();
    if(d.success){{
      msg.innerHTML='<span style="color:#080">'+d.message+'</span>';
      setTimeout(()=>{{location.reload();}},1500);
    }}else{{
      msg.innerHTML='<span style="color:#800">Error: '+(d.error||'unknown')+'</span>';
    }}
  }}catch(e){{msg.innerHTML='<span style="color:#800">'+e.message+'</span>';}}
}}

async function loadImmortalNewsletter(arena){{
  const pw=getPw();
  if(!pw){{alert('Enter host password first.');return;}}
  const msg=document.getElementById(arena+'-msg');
  msg.textContent='Loading...';
  try{{
    const r=await fetch('/api/admin/get_arena_newsletter',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{host_password:pw,arena:arena}})}});
    const d=await r.json();
    if(d.success){{
      msg.textContent='';
      document.getElementById('arena-modal-content').innerHTML=
        '<h3 style="margin-top:0">'+d.arena_display+' - Turn '+d.turn+'</h3>'+
        '<pre style="font-size:11px;white-space:pre-wrap;font-family:Courier New,monospace;background:#f5f5f5;padding:10px;max-height:55vh;overflow-y:auto">'+
        (d.content||'(empty)').replace(/</g,'&lt;')+'</pre>';
      document.getElementById('arena-modal').style.display='flex';
    }}else{{
      msg.innerHTML='<span style="color:#800">Error: '+(d.error||'unknown')+'</span>';
    }}
  }}catch(e){{msg.innerHTML='<span style="color:#800">'+e.message+'</span>';}}
}}

function markImmortalSlotDirty(arena){{
  document.getElementById(arena+'-save-sched-btn').style.display='inline-block';
}}

function addImmortalSlot(arena){{
  const list=document.getElementById(arena+'-slot-list');
  if(!list)return;
  if(list.style.color==='rgb(136, 136, 136)'){{
    list.style.color='';list.textContent='';
  }}
  const idx=list.querySelectorAll('[id$="-day"]').length;
  const div=document.createElement('div');
  div.style.cssText='display:flex;align-items:center;gap:4px;margin:2px 0';
  div.id=arena+'-slot-'+idx;
  const days=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  div.innerHTML=`<select id="${{arena}}-slot-${{idx}}-day" onchange="markImmortalSlotDirty('${{arena}}')" style="font-size:11px;padding:1px">
    ${{days.map(d=>`<option>${{d}}</option>`).join('')}}
  </select><input type="time" value="18:00" id="${{arena}}-slot-${{idx}}-time" style="font-size:11px;width:70px" onchange="markImmortalSlotDirty('${{arena}}')">`;
  list.appendChild(div);
  markImmortalSlotDirty(arena);
}}

async function saveImmortalSchedule(arena){{
  const pw=getPw();
  if(!pw){{alert('Enter host password first.');return;}}
  const list=document.getElementById(arena+'-slot-list');
  const slots=[];
  if(list){{
    list.querySelectorAll('[id$="-day"]').forEach(sel=>{{
      const idx=sel.id.match(/\\d+/g).pop();
      const t=document.getElementById(arena+'-slot-'+idx+'-time');
      if(sel.value&&t&&t.value) slots.push({{day:sel.value,time:t.value}});
    }});
  }}
  const enabled=document.getElementById(arena+'-sched-enabled').checked;
  const msg=document.getElementById(arena+'-msg');
  try{{
    const r=await fetch('/api/admin/set_arena_schedule',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{host_password:pw,arena:arena,enabled:enabled,schedule_slots:slots}})}});
    const d=await r.json();
    if(d.success){{
      msg.innerHTML='<span style="color:#080">Schedule saved: '+(d.schedule_slots||[]).length+' slot(s).</span>';
      document.getElementById(arena+'-save-sched-btn').style.display='none';
    }}else{{
      msg.innerHTML='<span style="color:#800">Error: '+(d.error||'unknown')+'</span>';
    }}
  }}catch(e){{msg.innerHTML='<span style="color:#800">'+e.message+'</span>';}}
}}

async function toggleImmortalSchedule(arena){{
  markImmortalSlotDirty(arena);
}}

async function showPromotionPanel(){{
  const pw=getPw();
  if(!pw){{alert('Enter host password first.');return;}}
  document.getElementById('arena-modal-content').innerHTML='<p>Loading...</p>';
  document.getElementById('arena-modal').style.display='flex';
  try{{
    const r=await fetch('/api/admin/promotion_panel_data',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{host_password:pw}})}});
    const d=await r.json();
    if(!d.success){{document.getElementById('arena-modal-content').innerHTML='<p style="color:#800">'+d.error+'</p>';return;}}
    const c=d.criteria;
    let html='<h3 style="margin-top:0;border-bottom:1px solid #ccc;padding-bottom:6px">&#9997; Manage Promotions</h3>';

    // ── Dead Warriors ──────────────────────────────────────────────────────────
    html+='<h4 style="color:#800;margin:10px 0 4px">Dead Warriors Available for Resurrection</h4>';
    html+='<p style="font-size:11px;color:#666;margin:0 0 6px">All dead warriors with 1+ fight. Select warriors and click a destination to resurrect them.</p>';
    if(d.dead_warriors.length){{
      html+='<div style="margin-bottom:4px"><label style="font-size:12px"><input type="checkbox" id="dead-chk-all" onchange="_toggleAllDead(this)"> Select all ('+d.dead_warriors.length+')</label></div>';
      html+='<div style="max-height:260px;overflow-y:auto;border:1px solid #ccc;border-radius:3px">';
      html+='<table style="width:100%;font-size:12px;border-collapse:collapse">';
      html+='<thead style="background:#ddd;position:sticky;top:0"><tr><th style="padding:3px 5px;text-align:left"></th><th style="padding:3px 5px;text-align:left">Warrior</th><th style="padding:3px 5px;text-align:left">Team</th><th>Record</th><th>Win%</th><th>Trains</th></tr></thead><tbody>';
      d.dead_warriors.forEach(w=>{{
        html+=`<tr style="border-bottom:1px solid #eee">
          <td style="padding:2px 5px"><input type="checkbox" class="dead-chk" value="${{w.team_id}}|${{w.warrior_name}}"></td>
          <td style="padding:2px 5px"><b>${{w.warrior_name}}</b></td>
          <td style="padding:2px 5px;color:#555">${{w.team_name}}</td>
          <td style="padding:2px 5px;text-align:center">${{w.record}}</td>
          <td style="padding:2px 5px;text-align:center">${{(w.win_rate*100).toFixed(1)}}%</td>
          <td style="padding:2px 5px;text-align:center">${{w.total_trains}}</td>
        </tr>`;
      }});
      html+='</tbody></table></div>';
      html+='<div style="margin-top:8px;display:flex;gap:8px;align-items:center">';
      html+=`<button onclick="_resurrectSelected('elite')" style="background:#1a3a1a;color:#9f9;border:1px solid #4a7;padding:4px 14px;cursor:pointer;border-radius:3px">&#10009; Resurrect to Elite Spire</button>`;
      html+=`<button onclick="_resurrectSelected('veteran')" style="background:#3a2a00;color:#fc8;border:1px solid #760;padding:4px 14px;cursor:pointer;border-radius:3px">&#9760; Send to Dead Grounds</button>`;
      html+='<span id="resurrect-status" style="font-size:11px;color:#555"></span>';
      html+='</div>';
    }}else{{
      html+='<p style="color:#666;font-size:12px;font-style:italic">No dead warriors meet the display threshold.</p>';
    }}

    // ── Pending Final Mortal Fight ─────────────────────────────────────────────
    if(d.pending.length){{
      html+='<h4 style="color:#c80;margin:14px 0 4px">Pending Final Mortal Fight ('+d.pending.length+')</h4>';
      html+='<p style="font-size:11px;color:#666;margin:0 0 6px">These warriors have been flagged for promotion. They fight once more with the immortality shield, then move to the Elite Spire.</p>';
      html+='<table style="width:100%;font-size:12px;border-collapse:collapse">';
      html+='<thead style="background:#ddd"><tr><th style="padding:3px 5px;text-align:left">Warrior</th><th style="padding:3px 5px;text-align:left">Team</th><th>Record</th><th>Destination</th><th></th></tr></thead><tbody>';
      d.pending.forEach(p=>{{
        html+=`<tr style="border-bottom:1px solid #eee">
          <td style="padding:2px 5px"><b>${{p.warrior_name}}</b></td>
          <td style="padding:2px 5px;color:#555">${{p.team_name}}</td>
          <td style="padding:2px 5px;text-align:center">${{p.record}}</td>
          <td style="padding:2px 5px;text-align:center">${{p.pending_promotion}}</td>
          <td style="padding:2px 5px"><button onclick="doPromoteNow(${{p.team_id}},'${{p.warrior_name}}','${{p.pending_promotion}}','elite')" style="font-size:11px;padding:1px 6px">Promote Now</button></td>
        </tr>`;
      }});
      html+='</tbody></table>';
    }}

    // ── Living Warriors — Elite Eligible ──────────────────────────────────────
    if(d.living_eligible.length){{
      html+='<h4 style="color:#080;margin:14px 0 4px">Living Warriors — Elite Eligible ('+d.living_eligible.length+')</h4>';
      html+='<p style="font-size:11px;color:#666;margin:0 0 6px">These warriors already meet all Elite Spire criteria ('+c.elite_min_fights+'+ fights, '+(c.elite_min_win_rate*100).toFixed(0)+'%+ win rate, '+c.elite_min_trains+'+ trains). They will be auto-flagged on the next normal turn, or you can promote immediately.</p>';
      html+='<table style="width:100%;font-size:12px;border-collapse:collapse">';
      html+='<thead style="background:#ddd"><tr><th style="padding:3px 5px;text-align:left">Warrior</th><th style="padding:3px 5px;text-align:left">Team</th><th>Record</th><th>Win%</th><th>Trains</th><th></th></tr></thead><tbody>';
      d.living_eligible.forEach(w=>{{
        html+=`<tr style="border-bottom:1px solid #eee">
          <td style="padding:2px 5px"><b>${{w.warrior_name}}</b></td>
          <td style="padding:2px 5px;color:#555">${{w.team_name}}</td>
          <td style="padding:2px 5px;text-align:center">${{w.record}}</td>
          <td style="padding:2px 5px;text-align:center">${{(w.win_rate*100).toFixed(1)}}%</td>
          <td style="padding:2px 5px;text-align:center">${{w.total_trains}}</td>
          <td style="padding:2px 5px"><button onclick="doPromoteNow(${{w.team_id}},'${{w.warrior_name}}',null,'elite')" style="font-size:11px;padding:1px 6px">Promote Now</button></td>
        </tr>`;
      }});
      html+='</tbody></table>';
    }}

    if(!d.dead_warriors.length&&!d.pending.length&&!d.living_eligible.length){{
      html+='<p style="color:#555;margin-top:10px">No warriors are currently available for promotion or resurrection.</p>';
    }}

    // ── Current Arena Rosters ─────────────────────────────────────────────────
    html+='<hr style="margin:18px 0 12px;border:none;border-top:1px solid #555">';
    html+='<h4 style="margin:0 0 8px;color:#ccc;letter-spacing:1px">CURRENT IMMORTAL ARENA ROSTERS</h4>';
    html+='<h5 style="color:#9f9;margin:8px 0 4px">&#9994; The Elite Spire &mdash; '+d.elite_roster.length+' warrior(s)</h5>';
    if(d.elite_roster.length){{
      html+='<div style="max-height:160px;overflow-y:auto;border:1px solid #4a7;border-radius:3px;margin-bottom:10px">';
      html+='<table style="width:100%;font-size:12px;border-collapse:collapse">';
      html+='<thead style="background:#1a3a1a;color:#9f9;position:sticky;top:0"><tr><th style="padding:3px 6px;text-align:left">Warrior</th><th style="padding:3px 6px;text-align:left">Team</th><th style="padding:3px 6px">Record</th><th style="padding:3px 6px">Win%</th><th style="padding:3px 6px">Trains</th></tr></thead><tbody>';
      d.elite_roster.forEach(w=>{{
        html+=`<tr style="border-bottom:1px solid #2a4a2a"><td style="padding:2px 6px"><b>${{w.warrior_name}}</b></td><td style="padding:2px 6px;color:#888">${{w.team_name}}</td><td style="padding:2px 6px;text-align:center">${{w.record}}</td><td style="padding:2px 6px;text-align:center">${{(w.win_rate*100).toFixed(1)}}%</td><td style="padding:2px 6px;text-align:center">${{w.total_trains}}</td></tr>`;
      }});
      html+='</tbody></table></div>';
    }}else{{
      html+='<p style="color:#666;font-size:12px;font-style:italic;margin:2px 0 10px">No warriors currently in The Elite Spire.</p>';
    }}
    html+='<h5 style="color:#fc8;margin:8px 0 4px">&#9760; The Dead Grounds &mdash; '+d.veteran_roster.length+' warrior(s)</h5>';
    if(d.veteran_roster.length){{
      html+='<div style="max-height:160px;overflow-y:auto;border:1px solid #760;border-radius:3px">';
      html+='<table style="width:100%;font-size:12px;border-collapse:collapse">';
      html+='<thead style="background:#3a2a00;color:#fc8;position:sticky;top:0"><tr><th style="padding:3px 6px;text-align:left">Warrior</th><th style="padding:3px 6px;text-align:left">Team</th><th style="padding:3px 6px">Record</th><th style="padding:3px 6px">Win%</th><th style="padding:3px 6px">Trains</th></tr></thead><tbody>';
      d.veteran_roster.forEach(w=>{{
        html+=`<tr style="border-bottom:1px solid #4a3a10"><td style="padding:2px 6px"><b>${{w.warrior_name}}</b></td><td style="padding:2px 6px;color:#888">${{w.team_name}}</td><td style="padding:2px 6px;text-align:center">${{w.record}}</td><td style="padding:2px 6px;text-align:center">${{(w.win_rate*100).toFixed(1)}}%</td><td style="padding:2px 6px;text-align:center">${{w.total_trains}}</td></tr>`;
      }});
      html+='</tbody></table></div>';
    }}else{{
      html+='<p style="color:#666;font-size:12px;font-style:italic;margin:2px 0">No warriors currently in The Dead Grounds.</p>';
    }}

    document.getElementById('arena-modal-content').innerHTML=html;
  }}catch(e){{document.getElementById('arena-modal-content').innerHTML='<p style="color:#800">'+e.message+'</p>';}}
}}

function _toggleAllDead(chk){{
  document.querySelectorAll('.dead-chk').forEach(c=>c.checked=chk.checked);
}}

async function _resurrectSelected(targetArena){{
  const pw=getPw();
  const checked=[...document.querySelectorAll('.dead-chk:checked')];
  if(!checked.length){{alert('No warriors selected.');return;}}
  const label={{'elite':'The Elite Spire','veteran':'The Dead Grounds'}}[targetArena]||targetArena;
  if(!confirm('Resurrect '+checked.length+' warrior(s) to '+label+'?'))return;
  const status=document.getElementById('resurrect-status');
  status.textContent='Working...';
  let ok=0,errs=[];
  for(const chk of checked){{
    const[teamId,warriorName]=chk.value.split('|');
    try{{
      const r=await fetch('/api/admin/resurrect_warrior',{{method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{host_password:pw,team_id:parseInt(teamId),warrior_name:warriorName,target_arena:targetArena}})}});
      const d=await r.json();
      if(d.success)ok++;
      else errs.push(warriorName+': '+(d.error||'unknown'));
    }}catch(e){{errs.push(warriorName+': '+e.message);}}
  }}
  let msg='Resurrected '+ok+' warrior(s) to '+label+'.';
  if(errs.length)msg+='\\n\\nErrors:\\n'+errs.join('\\n');
  alert(msg);
  showPromotionPanel();
}}

async function doPromoteNow(teamId, warriorName, pendingTarget, defaultArena){{
  const pw=getPw();
  const target=pendingTarget||defaultArena;
  const label={{'elite':'The Elite Spire','veteran':'The Dead Grounds'}}[target]||target;
  if(!confirm('Promote '+warriorName+' to '+label+' now?'))return;
  const r=await fetch('/api/admin/promote_warrior',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{host_password:pw,team_id:teamId,warrior_name:warriorName,target_arena:target}})}});
  const d=await r.json();
  if(d.success){{alert(d.message);showPromotionPanel();}}
  else{{alert('Error: '+(d.error||'unknown'));}}
}}

async function doRetireNow(teamId, warriorName){{
  const pw=getPw();
  if(!confirm('Mark '+warriorName+' for retirement to The Dead Grounds?'))return;
  const r=await fetch('/api/admin/retire_warrior',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{host_password:pw,team_id:teamId,warrior_name:warriorName}})}});
  const d=await r.json();
  if(d.success){{alert(d.message);showPromotionPanel();}}
  else{{alert('Error: '+(d.error||'unknown'));}}
}}
// ── end Immortal Arena JS ──────────────────────────────────────────────────

// Browser close detection - only shut down on real tab close, not auto-reloads
window.addEventListener('beforeunload', () => {{
  if(!_isNavigating) navigator.sendBeacon('/api/shutdown', '');
}});
</script></body></html>"""
# =============================================================================
# HTTP HANDLER
# =============================================================================

class LeagueHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, *a): pass

    def _shutdown_server(self):
        """Gracefully shutdown the server."""
        import time
        time.sleep(0.2)  # Brief wait to ensure response is fully sent
        global _global_server
        if _global_server:
            try:
                _global_server.shutdown()
                _global_server.server_close()
            except Exception:
                pass
        import sys
        sys.exit(0)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def send_html(self, html, status=200):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type",   "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control",  "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma",         "no-cache")
        self.send_header("Expires",        "0")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            print(f"  WARNING: Malformed JSON body from {self.client_address[0]} ({len(raw)} bytes): {raw[:120]!r}")
            return {}

    def qs(self):
        from urllib.parse import parse_qsl
        return dict(parse_qsl(self.path.split("?",1)[1])) if "?" in self.path else {}

    def p(self):
        return self.path.split("?")[0].rstrip("/") or "/"

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    # ── GET ───────────────────────────────────────────────────────────────

    def do_GET(self):
        path = self.p()

        if path == "/api/ping":
            cfg = _load_config()
            self.send_json({
                "status":     "ok",
                "turn":       cfg.get("current_turn", 1),
                "turn_state": cfg.get("turn_state", "open"),
            }); return

        if path in ("/", "/admin"):
            self.send_html(_admin_page()); return

        # Static asset handling: serve HTML, images and icons from the base directory
        ext = os.path.splitext(path.lower())[1]
        if ext in (".html", ".png", ".jpg", ".jpeg", ".ico", ".gif"):
            fpath = os.path.join(BASE_DIR, os.path.basename(path))
            if os.path.exists(fpath):
                if ext == ".html":
                    with open(fpath, "r", encoding="utf-8") as f:
                        html_data = f.read()
                    self.send_response(200)
                    self._cors()
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html_data.encode())))
                    # Do not cache HTML to ensure updates are seen
                    self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                    self.end_headers()
                    self.wfile.write(html_data.encode())
                    self.wfile.flush()
                    return

                mimes = {".png":"image/png", ".jpg":"image/jpeg", ".jpeg":"image/jpeg", 
                         ".ico":"image/x-icon", ".gif":"image/gif"}
                with open(fpath, "rb") as f:
                    img_data = f.read()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", mimes.get(ext, "application/octet-stream"))
                self.send_header("Content-Length", str(len(img_data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(img_data); return

        if path == "/api/status":
            cfg = _load_config()
            mgrs= _load_managers()
            ups = _load_uploads(cfg["current_turn"])
            # Build manager list with last upload timestamps
            managers_info = []
            for mid, mgr in mgrs.items():
                managers_info.append({
                    "manager_id": mid,
                    "manager_name": mgr["manager_name"],
                    "last_upload_timestamp": mgr.get("last_upload_timestamp", "-")
                })
            self.send_json({
                "current_turn"    : cfg["current_turn"],
                "turn_state"      : cfg["turn_state"],
                "total_managers"  : len(mgrs),
                "uploaded_count"  : len(ups),
                "managers"        : managers_info,
                "uploaded"        : [ups[m]["manager_name"] for m in ups],
                "not_uploaded"    : [mgrs[m]["manager_name"] for m in mgrs if m not in ups],
                "reset_count"     : cfg.get("reset_count", 0),
                "server_version"  : SERVER_VERSION,
            }); return

        if path == "/api/newsletter":
            q        = self.qs()
            turn_num = int(q.get("turn", 0))
            if not turn_num: # Newsletter is a text file, not JSON, but should be read-only
                self.send_json({"success":False,"error":"turn required"}); return

            # Try new newsletters folder first (turn_XXX.txt format)
            nl_path = os.path.join(LEAGUE_DIR, "newsletters", f"turn_{turn_num:03d}.txt")
            if not os.path.exists(nl_path):
                # Fall back to old location for backwards compatibility
                nl_path = os.path.join(_turn_dir(turn_num), "newsletter.txt")

            if not os.path.exists(nl_path):
                self.send_json({"success":False,"error":f"No newsletter for turn {turn_num}"}); return
            make_file_writable(nl_path) # Temporarily make writable to read
            with open(nl_path,"r",encoding="utf-8") as _f:
                nl_text = _f.read()
            self.send_json({"success":True,"turn":turn_num,"newsletter":nl_text}); return

        if path == "/api/immortal_warriors":
            # Public endpoint — no auth required.
            # Reads directly from the arena-specific team files (saves/{arena}/teams/)
            # so normal-arena uploads cannot contaminate the result.
            _mgrs2 = _load_managers()
            _tid_to_mgr = {}
            for _mid2, _md2 in _mgrs2.items():
                for _t2id in (_md2.get("team_ids") or []):
                    _tid_to_mgr[int(_t2id)] = _md2.get("manager_name", "")

            def _iw_entries(arena_name):
                result_list = []
                for _td in _load_immortal_teams(arena_name):
                    _tname = _td.get("team_name", "?")
                    _tid   = int(_td.get("team_id", 0))
                    _tmgr  = _td.get("manager_name") or _tid_to_mgr.get(_tid, "")
                    def _entry(_wd, _an=arena_name, _tn=_tname, _ti=_tid, _tm=_tmgr):
                        fh = _wd.get("fight_history") or []
                        af = [f for f in fh if (f.get("arena") or "normal") == _an]
                        return {
                            **_wd,
                            "team_name":    _tn,
                            "team_id":      _ti,
                            "manager_name": _tm,
                            "arena_wins":   sum(1 for f in af if f.get("result") == "win"),
                            "arena_losses": sum(1 for f in af if f.get("result") == "loss"),
                            "arena_kills":  sum(1 for f in af if f.get("is_kill", False)),
                        }
                    for _w in (_td.get("warriors") or []):
                        if isinstance(_w, dict) and not _w.get("is_dead", False):
                            result_list.append(_entry(_w))
                    for _w in (_td.get("archived_warriors") or []):
                        if isinstance(_w, dict) and not _w.get("is_dead", True):
                            result_list.append(_entry(_w))
                return result_list

            self.send_json({
                "success": True,
                "elite":   _iw_entries("elite"),
                "veteran": _iw_entries("veteran"),
            }); return

        if path == "/api/arena_newsletters":
            # Public: return list of available turn numbers for an immortal arena.
            # ?arena=elite  or  ?arena=veteran
            _raw_qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            qs    = urllib.parse.parse_qs(_raw_qs)
            arena = qs.get("arena", [""])[0].strip()
            if arena not in ("elite", "veteran"):
                self.send_json({"success": False, "error": "arena must be 'elite' or 'veteran'"}); return
            arena_dir = os.path.join(BASE_DIR, "saves", arena)
            turns = []
            if os.path.isdir(arena_dir):
                for entry in sorted(os.listdir(arena_dir)):
                    if entry.startswith("turn_") and os.path.isdir(os.path.join(arena_dir, entry)):
                        nl = os.path.join(arena_dir, entry, "newsletter.txt")
                        if os.path.exists(nl):
                            try:
                                turns.append(int(entry.split("_")[1]))
                            except (IndexError, ValueError):
                                pass
            self.send_json({"success": True, "arena": arena, "turns": sorted(turns)}); return

        if path == "/api/arena_newsletter":
            # Public: return newsletter text for a specific immortal arena turn.
            # ?arena=elite&turn=N
            _raw_qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            qs    = urllib.parse.parse_qs(_raw_qs)
            arena = qs.get("arena", [""])[0].strip()
            turn  = int(qs.get("turn", ["0"])[0] or 0)
            if arena not in ("elite", "veteran"):
                self.send_json({"success": False, "error": "arena must be 'elite' or 'veteran'"}); return
            if not turn:
                self.send_json({"success": False, "error": "turn parameter required"}); return
            nl_path = os.path.join(BASE_DIR, "saves", arena,
                                   f"turn_{turn:04d}", "newsletter.txt")
            if not os.path.exists(nl_path):
                self.send_json({"success": False,
                                "error": f"Newsletter for {arena} turn {turn} not found."}); return
            with open(nl_path, encoding="utf-8") as _f:
                content = _f.read()
            self.send_json({"success": True, "arena": arena, "turn": turn, "content": content}); return

        if path == "/api/latest_newsletter":
            # Return the most recent newsletter (for new users who haven't uploaded yet)
            cfg = _load_config()
            current_turn = cfg["current_turn"]
            if current_turn <= 1:
                self.send_json({"success":False,"error":"No newsletters available yet"}); return
            # Try the current turn first, then go backwards
            for turn_num in range(current_turn, 0, -1):
                nl_path = os.path.join(_turn_dir(turn_num), "newsletter.txt")
                if os.path.exists(nl_path):
                    make_file_writable(nl_path) # Temporarily make writable to read
                    with open(nl_path,"r",encoding="utf-8") as _f:
                        nl_text = _f.read()
                    make_file_readonly(nl_path) # Set back to read-only
                    self.send_json({"success":True,"turn":turn_num,"newsletter":nl_text}); return
            self.send_json({"success":False,"error":"No newsletters found"}); return

        # ==================== NEWSLETTER DOWNLOAD (PUBLIC) ====================
        if path == "/newsletter" or path.startswith("/newsletter/"):
            # Serves newsletter as an HTML page with download button
            # Usage: /newsletter/turn/1 or /newsletter to list all
            parts = path.split("/")
            turn_num = 0

            # Check if just /newsletter with no turn specified
            if path == "/newsletter" or len(parts) <= 3 or (len(parts) == 4 and parts[3] == ""):
                # List available newsletters
                available = []
                try:
                    if os.path.exists(LEAGUE_DIR):
                        for turn_dir in os.listdir(LEAGUE_DIR):
                            if turn_dir.startswith("turn_"):
                                turn_path = os.path.join(LEAGUE_DIR, turn_dir)
                                if os.path.isdir(turn_path):
                                    nl_path = os.path.join(turn_path, "newsletter.txt")
                                    if os.path.exists(nl_path):
                                        try:
                                            turn_num = int(turn_dir.split("_")[1])
                                            available.append(turn_num)
                                        except (ValueError, IndexError):
                                            pass
                except Exception as e:
                    pass

                available.sort(reverse=True)  # Sort by turn number, newest first

                # Create HTML page with list of available newsletters
                newsletter_links = ""
                if available:
                    for turn in available:
                        newsletter_links += f'            <li><a href="/newsletter/turn/{turn}">Turn {turn}</a></li>\n'
                else:
                    newsletter_links = '            <li><em>No newsletters available yet</em></li>\n'

                html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Agony Amphitheatre — Newsletters</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html {{ scroll-behavior: smooth; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a1a 0%, #2d1a1a 100%);
            color: #e8e8e8;
            line-height: 1.6;
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{
            max-width: 99vw;
            margin: 0 auto;
            background: rgba(20, 20, 20, 0.95);
            color: #e8e8e8;
            padding: 20px;
            border: 2px solid #a61a1a;
            border-radius: 6px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
        }}
        .header {{
            text-align: center;
            border-bottom: 3px solid #a61a1a;
            padding-bottom: 25px;
            margin-bottom: 35px;
        }}
        .header h1 {{
            font-size: 2.4em;
            color: #ff4444;
            margin-bottom: 8px;
            font-weight: 700;
            letter-spacing: 2px;
        }}
        .header p {{
            font-size: 1.15em;
            color: #999;
        }}
        .newsletter-list {{
            list-style: none;
            padding: 0;
        }}
        .newsletter-list li {{
            padding: 18px 24px;
            margin-bottom: 12px;
            background: rgba(42, 42, 42, 0.8);
            border-left: 4px solid #a61a1a;
            border-radius: 5px;
            transition: all 0.3s ease;
        }}
        .newsletter-list li:hover {{
            background: rgba(50, 50, 50, 1);
            transform: translateX(5px);
        }}
        .newsletter-list li em {{
            color: #999;
            font-style: italic;
        }}
        .newsletter-list a {{
            color: #ff9999;
            text-decoration: none;
            font-weight: 600;
            font-size: 1.1em;
            transition: color 0.2s ease;
        }}
        .newsletter-list a:hover {{
            color: #ffaaaa;
            text-decoration: underline;
        }}
        .footer {{
            text-align: center;
            margin-top: 35px;
            padding-top: 20px;
            border-top: 1px solid #444;
            color: #777;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚔ THE AGONY AMPHITHEATRE ⚔</h1>
            <p>Arena Newsletters</p>
        </div>

        <ul class="newsletter-list">
{newsletter_links}        </ul>

        <div class="footer">
            <p>The Agony Amphitheatre Arena League</p>
        </div>
    </div>
</body>
</html>"""

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_page.encode("utf-8"))
                return

            try:
                if len(parts) >= 4 and parts[2] == "turn":
                    turn_num = int(parts[3])
            except (IndexError, ValueError):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Invalid turn number")
                return

            if turn_num <= 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Turn number must be positive")
                return

            nl_path = os.path.join(_turn_dir(turn_num), "newsletter.txt")
            if not os.path.exists(nl_path):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(f"Newsletter for turn {turn_num} not found".encode("utf-8"))
                return

            try:
                make_file_writable(nl_path)
                with open(nl_path, "r", encoding="utf-8") as f:
                    nl_content = f.read()
                make_file_readonly(nl_path)

                # Strip ANSI color codes from the content
                import re
                ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                nl_content_clean = ansi_escape.sub('', nl_content)

                # For JavaScript, we need the original content but with proper escaping for JSON string
                # Use json.dumps to properly escape for JavaScript
                js_content = json.dumps(nl_content_clean)

                # Escape HTML and format for display with section-specific formatting
                import html
                escaped_content = html.escape(nl_content_clean)

                # Split content into sections and apply different formatting
                # Look for "ARENA HAPPENINGS" section and the next major section after it
                if "ARENA HAPPENINGS" in escaped_content:
                    parts = escaped_content.split("ARENA HAPPENINGS")
                    standings_part = parts[0] + "ARENA HAPPENINGS"
                    after_happenings = parts[1]

                    # Find the next section header (all caps on its own line)
                    # Look for pattern: blank lines followed by ALL CAPS text
                    import re
                    match = re.search(r'\n\n[A-Z][A-Z\s]+\n', after_happenings)

                    if match:
                        happenings_end = match.start()
                        happenings_narrative = after_happenings[:happenings_end]
                        rest_of_content = after_happenings[happenings_end:]
                    else:
                        happenings_narrative = after_happenings
                        rest_of_content = ""

                    # Standings and initial happenings header: no wrapping
                    formatted_standings = standings_part

                    # Happenings narrative: word wrapping
                    formatted_happenings = happenings_narrative.replace("\n", "<br>")

                    # Rest of content: no wrapping
                    formatted_rest = rest_of_content

                    formatted_content = f'<pre class="newsletter-standings">{formatted_standings}</pre><div class="newsletter-happenings">{formatted_happenings}</div><pre class="newsletter-standings">{formatted_rest}</pre>'
                else:
                    # Fallback: no wrapping
                    formatted_content = f'<pre>{escaped_content}</pre>'

                # Create HTML page with download button using JavaScript
                html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Agony Amphitheatre — Newsletter Turn {turn_num}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html {{ scroll-behavior: smooth; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a1a 0%, #2d1a1a 100%);
            color: #e8e8e8;
            line-height: 1.6;
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{
            max-width: 99vw;
            margin: 0 auto;
            background: rgba(20, 20, 20, 0.95);
            color: #e8e8e8;
            padding: 20px;
            border: 2px solid #a61a1a;
            border-radius: 6px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
        }}
        .header {{
            text-align: center;
            border-bottom: 3px solid #a61a1a;
            padding-bottom: 25px;
            margin-bottom: 35px;
        }}
        .header h1 {{
            font-size: 2.4em;
            color: #ff4444;
            margin-bottom: 8px;
            font-weight: 700;
            letter-spacing: 2px;
        }}
        .header p {{
            font-size: 1.15em;
            color: #999;
        }}
        .button-row {{
            text-align: center;
            margin-bottom: 35px;
        }}
        button {{
            background: linear-gradient(135deg, #a61a1a 0%, #8b0000 100%);
            color: #fff;
            padding: 14px 40px;
            border: none;
            border-radius: 5px;
            font-weight: 600;
            font-size: 1em;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(166, 26, 26, 0.3);
        }}
        button:hover {{
            background: linear-gradient(135deg, #cc2222 0%, #a61a1a 100%);
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(166, 26, 26, 0.5);
        }}
        button:active {{
            transform: translateY(0);
        }}
        .newsletter-content {{
            font-family: 'Courier New', 'Consolas', monospace;
            font-size: 0.82em;
            line-height: 1.5;
            background: #0d0d0d;
            color: #d0d0d0;
            padding: 0;
            border: 1px solid #444;
            border-radius: 5px;
            max-height: 70vh;
            overflow: auto;
        }}
        .newsletter-standings {{
            font-family: 'Courier New', 'Consolas', monospace;
            font-size: 0.82em;
            line-height: 1.5;
            white-space: pre;
            margin: 0;
            padding: 15px 15px 15px 50px;
            color: #d0d0d0;
        }}
        .newsletter-happenings {{
            font-family: 'Courier New', 'Consolas', monospace;
            font-size: 0.82em;
            white-space: pre-wrap;
            word-wrap: break-word;
            line-height: 1.6;
            padding: 15px 15px 15px 50px;
            margin: 0;
            color: #d0d0d0;
        }}
        .newsletter-content::-webkit-scrollbar {{
            width: 8px;
            height: 8px;
        }}
        .newsletter-content::-webkit-scrollbar-track {{
            background: #1a1a1a;
        }}
        .newsletter-content::-webkit-scrollbar-thumb {{
            background: #a61a1a;
            border-radius: 4px;
        }}
        .newsletter-content::-webkit-scrollbar-thumb:hover {{
            background: #cc2222;
        }}
        .footer {{
            text-align: center;
            margin-top: 35px;
            padding-top: 20px;
            border-top: 1px solid #444;
            color: #777;
            font-size: 0.9em;
        }}
        .footer code {{
            background: #2a2a2a;
            color: #ff9999;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚔ THE AGONY AMPHITHEATRE ⚔</h1>
            <p>Arena Newsletter — Turn {turn_num}</p>
        </div>

        <div class="button-row">
            <button onclick="downloadNewsletter()">📥 Download Newsletter</button>
        </div>

        <div class="newsletter-content">
{formatted_content}
        </div>

        <div class="footer">
            <p>Newsletter for Turn {turn_num} | The Agony Amphitheatre Arena League</p>
            <p style="margin-top: 10px; font-size: 0.85em;">After downloading, place the file in your client's <code>newsletters</code> folder to view it in the game.</p>
        </div>
    </div>

    <script>
        function downloadNewsletter() {{
            const content = {js_content};
            const filename = 'turn_{turn_num:03d}.txt';
            const blob = new Blob([content], {{ type: 'text/plain;charset=utf-8' }});
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = filename;
            link.click();
            URL.revokeObjectURL(link.href);
        }}
    </script>
</body>
</html>"""

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_page.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error reading newsletter: {e}".encode("utf-8"))
            return

        # ==================== NEWSLETTER RAW DOWNLOAD ====================
        if path.startswith("/newsletter/download/"):
            # Direct file download endpoint
            parts = path.split("/")
            turn_num = 0
            try:
                if len(parts) >= 5 and parts[3] == "turn":
                    turn_num = int(parts[4])
            except (IndexError, ValueError):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Invalid turn number")
                return

            if turn_num <= 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Turn number must be positive")
                return

            nl_path = os.path.join(_turn_dir(turn_num), "newsletter.txt")
            if not os.path.exists(nl_path):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(f"Newsletter for turn {turn_num} not found".encode("utf-8"))
                return

            try:
                make_file_writable(nl_path)
                with open(nl_path, "r", encoding="utf-8") as f:
                    nl_content = f.read()
                make_file_readonly(nl_path)

                # Send as file download with proper name
                filename = f"turn_{turn_num:03d}.txt"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", len(nl_content.encode("utf-8")))
                self.end_headers()
                self.wfile.write(nl_content.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error reading newsletter: {e}".encode("utf-8"))
            return

        if path == "/api/fight_log":
            q       = self.qs()
            turn_n  = int(q.get("turn",  0))
            fid     = int(q.get("fight_id", 0))
            mid     = q.get("manager_id", "")
            pw      = q.get("password", "")
            arena   = q.get("arena", "normal")
            if not turn_n or not fid:
                self.send_json({"success":False,"error":"turn and fight_id required"}); return
            # Auth check - require valid manager credentials
            mgrs = _load_managers()
            if mid and pw:
                if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                    self.send_json({"success":False,"error":"Not authorised."},401); return
            # Determine which turn directory to search based on arena
            if arena in ("elite", "veteran"):
                td = os.path.join(BASE_DIR, "saves", arena, f"turn_{turn_n:04d}")
            else:
                td = _turn_dir(turn_n)
            narrative = None
            if os.path.exists(td):
                all_files = [f for f in os.listdir(td)
                             if f.startswith("result_") and f.endswith(".json")]
                # Own files first (one manager may have multiple teams)
                own_files  = [f for f in all_files if mid and f.startswith(f"result_{mid}")]
                other_files = [f for f in all_files if f not in own_files]
                for fname in own_files + other_files:
                    r = _load_json(os.path.join(td, fname), None)
                    if not r:
                        continue
                    logs = r.get("fight_logs", {})
                    if str(fid) in logs:
                        narrative = logs[str(fid)]
                        break
            # For regular arena: if still not found, also check immortal arena dirs as fallback
            if narrative is None and arena == "normal":
                for _ia in ("elite", "veteran"):
                    _iatd = os.path.join(BASE_DIR, "saves", _ia, f"turn_{turn_n:04d}")
                    if not os.path.exists(_iatd):
                        continue
                    for fname in sorted(os.listdir(_iatd)):
                        if not (fname.startswith("result_") and fname.endswith(".json")):
                            continue
                        r = _load_json(os.path.join(_iatd, fname), None)
                        if r and str(fid) in (r.get("fight_logs") or {}):
                            narrative = r["fight_logs"][str(fid)]
                            break
                    if narrative is not None:
                        break
            if narrative is None:
                self.send_json({"success":False,"error":f"Fight log {fid} not found for turn {turn_n}."},404); return
            self.send_json({"success":True,"narrative":narrative,"fight_id":fid,"turn":turn_n}); return

        if path == "/api/standings":
            cfg = _load_config()
            standings = _load_standings()
            # Filter warrior data based on feature flags
            filtered_standings = {}
            for mid, sd in standings.items():
                fsd = sd.copy()
                if "warriors" in fsd:
                    fsd["warriors"] = {
                        wname: _filter_warrior_for_client(ws, cfg)
                        for wname, ws in fsd["warriors"].items()
                    }
                filtered_standings[mid] = fsd
            self.send_json(filtered_standings); return

        if path == "/api/progress":
            self.send_json(_turn_progress); return

        if path == "/api/flags":
            cfg = _load_config()
            self.send_json({
                "success"              : True,
                "show_favorite_weapon" : cfg.get("show_favorite_weapon", False),
                "show_luck_factor"     : cfg.get("show_luck_factor",     False),
                "show_max_hp"          : cfg.get("show_max_hp",          False),
                "ai_teams_enabled"     : cfg.get("ai_teams_enabled",     True),
                "game_data"            : _build_game_data(),  # Include fresh game data with flags
            }); return

        if path == "/api/game_data":
            # Static dropdown data the standalone client needs (races, weapons,
            # armor, triggers, styles, etc.).
            # Generate fresh each time to ensure clients always get latest version.
            self.send_json(_build_game_data()); return

        if path == "/api/schedule":
            cfg = _load_config()
            self.send_json({
                "success"                  : True,
                "schedule_enabled"         : cfg.get("schedule_enabled", False),
                "schedule_slots"           : cfg.get("schedule_slots", []),
                "schedule_last_run_at"     : cfg.get("schedule_last_run_at", ""),
                "schedule_last_run_turn"   : cfg.get("schedule_last_run_turn", 0),
                "schedule_last_run_result" : cfg.get("schedule_last_run_result", ""),
            }); return

        if path == "/api/graveyard":
            q   = self.qs()
            mid = q.get("manager_id", "")
            pw  = q.get("password", "")
            warrior_name = q.get("warrior_name", "").strip()
            team_name    = q.get("team_name", "").strip()
            mgrs = _load_managers()
            if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return
            if not warrior_name or not team_name:
                self.send_json({"success": False, "error": "warrior_name and team_name required"}); return
            from save import GRAVEYARD_DIR
            safe_team    = team_name.replace(" ", "_")
            safe_warrior = warrior_name.replace(" ", "_")
            legacy_path  = os.path.join(GRAVEYARD_DIR, f"{safe_team}_{safe_warrior}_legacy.txt")
            if not os.path.exists(legacy_path):
                self.send_json({"success": False, "error": "Legacy file not found."}); return
            make_file_writable(legacy_path)
            with open(legacy_path, "r", encoding="utf-8") as _lf:
                legacy_text = _lf.read()
            self.send_json({"success": True, "legacy": legacy_text}); return

        if path == "/api/results":
            q  = self.qs()
            mid= q.get("manager_id","")
            pw = q.get("password","")
            mgrs = _load_managers()
            if mid not in mgrs:
                _log_activity("download_failed", mid, "?", "Manager not found")
                self.send_json({"success":False,"error":"Manager not found. Register first."}, 404); return
            if not _check_mgr_pw(mgrs[mid], pw):
                _log_activity("download_failed", mid, mgrs[mid]["manager_name"], "Wrong password")
                self.send_json({"success":False,"error":"Wrong password."}, 401); return
            cfg = _load_config()
            res_turn = cfg["current_turn"] - 1
            if res_turn < 1:
                self.send_json({"success":False,"error":"No completed turns yet."}, 404); return
            # Collect ALL result files for this manager (one per uploaded team)
            td = _turn_dir(res_turn)
            team_results = []
            result_mtime = 0.0   # newest mtime among this manager's result files
            if os.path.exists(td):
                for fname in sorted(os.listdir(td)):
                    if fname.startswith(f"result_{mid}") and fname.endswith(".json"):
                        fpath = os.path.join(td, fname)
                        fm = os.path.getmtime(fpath)
                        if fm > result_mtime:
                            result_mtime = fm
                        r = _load_json(fpath, None)
                        if r:
                            # Verify ownership: only show results for teams the
                            # manager still officially owns.
                            tid = r.get("team_id")
                            tids = [str(t) for t in mgrs[mid].get("team_ids", [])]
                            if tids:
                                if not tid or str(tid) not in tids:
                                    continue # Result for an old/replaced team

                            # Include everything including fight_logs for offline viewing.
                            # Bandwidth increase is negligible (~35KB per team).
                            team_results.append(r.copy())
            # Include newsletter for this turn if available
            nl_text = ""
            nl_path = os.path.join(_turn_dir(res_turn), "newsletter.txt")
            if os.path.exists(nl_path): # Newsletter is a text file, not JSON, but should be read-only
                make_file_writable(nl_path) # Temporarily make writable to read
                with open(nl_path, "r", encoding="utf-8") as _nf:
                    nl_text = _nf.read()
                make_file_readonly(nl_path) # Set back to read-only
            # If there are no team results, allow the request to succeed if a newsletter exists
            if not team_results and not nl_text:
                self.send_json({"success":False,"error":"No results found for your manager this turn."}); return
            # Filter results based on feature flags
            team_results = _filter_results_for_client(team_results, cfg)

            # Include any pending deletions for this manager
            deleted_teams_list = []
            for key, val in cfg.items():
                if key.startswith("deleted_team_") and str(val.get("manager_id")) == str(mid):
                    deleted_teams_list.append(val)

            # If the manager already downloaded this exact turn's results AND the result
            # files haven't been regenerated since (mtime unchanged), return already_current.
            # This allows re-download after an arena revert+rerun even on the same turn number.
            last_dl = mgrs[mid].get("last_downloaded_turn", 0)
            last_dl_mtime = float(mgrs[mid].get("last_downloaded_result_mtime", 0))
            # Fall back to newsletter mtime when no per-manager result files exist
            if result_mtime == 0.0 and os.path.exists(nl_path):
                result_mtime = os.path.getmtime(nl_path)
            same_generation = result_mtime > 0 and abs(result_mtime - last_dl_mtime) < 1.0
            if int(last_dl) == int(res_turn) and same_generation:
                _log_activity("download_already_current", mid, mgrs[mid]["manager_name"],
                              f"Already downloaded turn {res_turn} - returning already_current")
                self.send_json({
                    "success": True, "already_current": True,
                    "turn": res_turn,
                }); return

            # Mark this turn as downloaded for this manager (include mtime for revert detection)
            mgrs[mid]["last_downloaded_turn"] = res_turn
            mgrs[mid]["last_downloaded_result_mtime"] = result_mtime
            _save_managers(mgrs)

            # Log the download
            team_count = len(team_results)
            _log_activity("download_success", mid, mgrs[mid]["manager_name"],
                        f"Downloaded {team_count} team result(s) for turn {res_turn}, has_newsletter={bool(nl_text)}")

            self.send_json({
                "success": True, "results": team_results,
                "turn": res_turn, "has_newsletter": bool(nl_text),
                "deleted_teams": deleted_teams_list,
                "game_data": _build_game_data(),  # Include updated game data with each download
                "result": None  # Explicit null when no results exist
            }); return

        if path == "/api/scout/status":
            q = self.qs()
            mid = q.get("manager_id","")
            pw  = q.get("password","")
            mgrs = _load_managers()
            if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                self.send_json({"success":False,"error":"Not authorised."}, 401); return
            arena = q.get("arena", "normal")
            from save import get_manager_scouting
            cfg = _load_config()
            selections = get_manager_scouting(mid, cfg["current_turn"], arena=arena)
            self.send_json({
                "success": True,
                "selections": selections,
                "slots_left": max(0, 3 - len(selections)),
            }); return

        if path == "/api/scout/targets" or path == "/api/challenge/targets":
            q = self.qs()
            mid   = q.get("manager_id","")
            pw    = q.get("password","")
            arena = q.get("arena", "normal")
            mgrs = _load_managers()
            if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                print(f"  [Scout] Auth failed: mid={mid}, pw_present={bool(pw)}, in_mgrs={mid in mgrs}")
                self.send_json({"success":False,"error":"Not authorised."}, 401); return
            # Exclude the caller's own teams from the target list.
            own_team_ids = set(int(t) for t in mgrs[mid].get("team_ids", []) if isinstance(t,(int,str)) and str(t).isdigit())
            print(f"  [Scout] Manager {mid} has teams: {sorted(own_team_ids)}")
            # For /api/challenge/targets, also allow excluding one specific team
            # (the attacking team itself - its own warriors can't be challenged).
            try:    exclude_tid = int(q.get("team_id","0") or 0)
            except: exclude_tid = 0
            from save import TEAMS_DIR, load_champion_state
            # Load current turn to filter inactive teams
            cfg = _load_config()
            current_turn = cfg.get("current_turn", 0)
            # Load champion name so we can flag that warrior in the response
            champ_state   = load_champion_state()
            champion_name = (champ_state.get("name") or "").lower()
            warriors = []
            try:
                fnames = sorted(os.listdir(TEAMS_DIR))
            except FileNotFoundError:
                fnames = []
            for fname in fnames:
                if not (fname.startswith("team_") and fname.endswith(".json")):
                    continue
                fpath = os.path.join(TEAMS_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        tdata = json.load(f)
                except Exception as e:
                    print(f"    Error loading {fname}: {e}")
                    continue
                tid = tdata.get("team_id", 0)
                if tid in own_team_ids: continue
                if exclude_tid and tid == exclude_tid: continue
                # Only include teams active within last 3 turns (skip filter for immortal arenas)
                last_turn_ran = tdata.get("last_turn_ran", 0)
                if arena == "normal" and current_turn > 0 and last_turn_ran > 0 and (current_turn - last_turn_ran) > 3:
                    print(f"    Skipping inactive team {fname} (last_turn_ran={last_turn_ran}, current_turn={current_turn})")
                    continue
                team_name = tdata.get("team_name", "?")
                manager_name = tdata.get("manager_name", "?")
                def _add_w(w):
                    wname = w.get("name", "?")
                    warriors.append({
                        "name"        : wname,
                        "team_name"   : team_name,
                        "team_id"     : tid,
                        "manager_name": manager_name,
                        "race"        : w.get("race", "?"),
                        "gender"      : w.get("gender", "?"),
                        "wins"        : w.get("wins", 0),
                        "losses"      : w.get("losses", 0),
                        "kills"       : w.get("kills", 0),
                        "max_hp"      : w.get("max_hp", 0),
                        "height_in"   : w.get("height_in", 0),
                        "weight_lbs"  : w.get("weight_lbs", 0),
                        "total_fights": w.get("total_fights", 0),
                        "recognition" : w.get("recognition", 0),
                        "is_champion" : bool(champion_name and wname.lower() == champion_name),
                    })
                if arena == "normal":
                    # Normal arena: warriors[] where current_arena is normal
                    for w in tdata.get("warriors", []):
                        if not w or w.get("is_dead") or w.get("is_retired"): continue
                        if (w.get("current_arena") or "normal") != "normal": continue
                        _add_w(w)
                else:
                    # Immortal arena: warriors[] and archived_warriors[] matching arena
                    for w in tdata.get("warriors", []):
                        if not w or w.get("is_dead") or w.get("is_retired"): continue
                        if (w.get("current_arena") or "normal") != arena: continue
                        _add_w(w)
                    for w in tdata.get("archived_warriors", []):
                        if not w or not isinstance(w, dict): continue
                        if w.get("is_dead", True): continue
                        if (w.get("current_arena") or "normal") != arena: continue
                        _add_w(w)
            print(f"  [Scout] Found {len(warriors)} warriors available to scout")

            # Calculate top 2 tiers for champion challenge eligibility
            from warrior import get_warrior_tier, TIER_ORDER, TIER_CHAMPION
            tiers_present = set()
            for w_data in warriors:
                # Create a minimal object for get_warrior_tier
                class TempWarrior:
                    def __init__(self, data):
                        self.total_fights = data.get("total_fights", 0)
                        self.recognition = data.get("recognition", 0)
                temp_w = TempWarrior(w_data)
                tier = get_warrior_tier(temp_w)
                if tier != TIER_CHAMPION:
                    tiers_present.add(tier)

            sorted_tiers = sorted(tiers_present, key=lambda t: TIER_ORDER.index(t) if t in TIER_ORDER else 999)
            eligible_champion_tiers = sorted_tiers[:2]

            self.send_json({"success": True, "warriors": warriors, "eligible_champion_tiers": eligible_champion_tiers}); return

        if path == "/api/scout/report":
            q = self.qs()
            mid = q.get("manager_id","")
            pw  = q.get("password","")
            wname = q.get("warrior_name","")
            mgrs = _load_managers()
            if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                self.send_json({"success":False,"error":"Not authorised."}, 401); return
            if not wname:
                self.send_json({"success":False,"error":"warrior_name required."}); return
            from save         import TEAMS_DIR
            from warrior      import Warrior
            from scout_report import generate_scout_report
            found_w = None; found_team_name = ""
            try:    fnames = sorted(os.listdir(TEAMS_DIR))
            except: fnames = []
            for fname in fnames:
                if not (fname.startswith("team_") and fname.endswith(".json")): continue
                fpath = os.path.join(TEAMS_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        tdata = json.load(f)
                except Exception:
                    continue
                for wd in tdata.get("warriors", []):
                    if wd and wd.get("name","").upper() == wname.upper():
                        found_w = wd
                        found_team_name = tdata.get("team_name", "?")
                        break
                if found_w: break
            if not found_w:
                self.send_json({"success":False,"error":f"Warrior '{wname}' not found."}, 404); return
            # Generate in-character scout report. Falls back to passing the dict
            # if Warrior.from_dict rejects legacy/partial data.
            try:
                warrior_obj = Warrior.from_dict(found_w)
            except Exception:
                warrior_obj = found_w
            fh = found_w.get("fight_history", []) or []
            last_fight = fh[-1] if fh else None
            scout_name, scout_type = _get_or_assign_scout_persona(mid, mgrs)
            scout_text = generate_scout_report(warrior_obj, last_fight, found_team_name,
                                               scout_name=scout_name, scout_type=scout_type)
            self.send_json({
                "success": True,
                "report": {
                    "warrior_name"    : found_w.get("name", "?"),
                    "team_name"       : found_team_name,
                    "wins"            : found_w.get("wins", 0),
                    "losses"          : found_w.get("losses", 0),
                    "kills"           : found_w.get("kills", 0),
                    "max_hp"          : found_w.get("max_hp", 0),
                    "height_in"       : found_w.get("height_in", 0),
                    "weight_lbs"      : found_w.get("weight_lbs", 0),
                    "total_fights"    : found_w.get("total_fights", 0),
                    "armor"           : found_w.get("armor") or "None",
                    "helm"            : found_w.get("helm")  or "None",
                    "primary_weapon"  : found_w.get("primary_weapon")   or "Open Hand",
                    "secondary_weapon": found_w.get("secondary_weapon") or "Open Hand",
                    "backup_weapon"   : found_w.get("backup_weapon")    or "None",
                    "scout_name"      : scout_name,
                    "scout_type"      : scout_type,
                    "scout_report"    : scout_text,
                }
            }); return

        if path == "/api/admin":
            q  = self.qs()
            cfg= _load_config()
            if not _check_host_pw(cfg, q.get("host_password","")):
                self.send_json({"success":False,"error":"Not authorised."}, 401); return
            mgrs = _load_managers()
            ups  = _load_uploads(cfg["current_turn"])
            self.send_json({
                "success":True, "config":cfg, "managers":mgrs,
                "uploads":{m:{"manager_name":u["manager_name"],"uploaded_at":u.get("uploaded_at")} for m,u in ups.items()},
                "standings":_load_standings(),
            }); return

        # ── Browser-mode local file API (GET-safe endpoints) ─────────────
        # These mirror the do_POST /api/local/* handlers so that browsers
        # using plain fetch() (default GET) can reach them without Electron.
        def _safe_path_get(rel_path):
            if not rel_path: return None
            clean = os.path.normpath(rel_path).lstrip(os.sep + (os.altsep or ''))
            if clean.startswith('..'): return None
            return os.path.join(BASE_DIR, "saves", "client", clean)

        if path == "/api/local/status":
            # Return the Host header so remote players get the correct server URL,
            # not a hardcoded "localhost" that only works on the server machine.
            host = self.headers.get("Host", f"localhost:{_server_port}")
            self.send_json({
                "success": True,
                "is_local_backend": True,
                "server_url": f"http://{host}",
            }); return

        if path == "/api/local/read":
            q = self.qs()
            fpath = _safe_path_get(q.get("path"))
            if not fpath or not os.path.exists(fpath):
                self.send_json({"success": False, "error": "File not found"}, 404); return
            try:
                if fpath.endswith(".json"):
                    # load_json_protected returns a dict, not a string - send directly
                    content = load_json_protected(fpath)
                    self.send_json({"success": True, "data": content})
                else:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    self.send_json({"success": True, "text": content})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)
            return

        if path == "/api/local/list":
            q = self.qs()
            dpath = _safe_path_get(q.get("path"))
            if not dpath or not os.path.isdir(dpath):
                self.send_json({"success": True, "files": []}); return
            files = [f for f in os.listdir(dpath) if os.path.isfile(os.path.join(dpath, f))]
            self.send_json({"success": True, "files": sorted(files)}); return

        self.send_json({"error":"Not found."}, 404)

    # ── POST ──────────────────────────────────────────────────────────────
    def do_POST(self):
        path = self.p()
        b = self.body()

        if path == "/api/register":
            mname = str(b.get("manager_name") or "").strip()
            pw = str(b.get("password") or "").strip()
            if not mname or not pw:
                self.send_json({"success":False,"error":"manager_name and password required."}); return
            if len(pw) < 4:
                self.send_json({"success":False,"error":"Password must be at least 4 characters."}); return
            with _lock:
                cfg  = _load_config()
                mgrs = _load_managers()
                current_reset_count = cfg.get("reset_count", 0)
                for existing_mid, m in mgrs.items():
                    if m["manager_name"].lower() == mname.lower():
                        if _check_mgr_pw(m, pw):
                            # Do NOT stamp acknowledged_reset_count here - an existing
                            # manager reconnecting after a reset should still see the
                            # reset modal. The check_reset default handles new-to-feature
                            # managers. Only new registrations get the ack stamp.
                            # Check for pending deletions for this manager
                            deleted_teams_list = [v for k, v in cfg.items() 
                                                 if k.startswith("deleted_team_") and str(v.get("manager_id")) == str(existing_mid)]
                            self.send_json({
                                "success": True, "manager_id": existing_mid,
                                "manager_name": m["manager_name"],
                                "reset_count": current_reset_count,
                                "deleted_teams": deleted_teams_list,
                                "team_ids": m.get("team_ids", [])
                            }); return
                        self.send_json({"success":False,"error":"Manager name already registered - use your original password to reconnect."}); return
                # Numeric IDs, starting at 20 and incrementing. Legacy non-numeric
                # IDs (hex uuids from older builds) are skipped so they don't
                # poison the sequence.
                numeric_ids = [int(k) for k in mgrs.keys() if k.isdigit()]
                mid = str(max(numeric_ids) + 1) if numeric_ids else "20"
                salt = secrets.token_hex(16)
                mgrs[mid] = {"manager_name":mname,"salt":salt,
                             "password_hash":_hash_pw(pw,salt),
                             "registered_at":time.strftime("%Y-%m-%d %H:%M:%S"),
                             "acknowledged_reset_count": current_reset_count}
                _save_managers(mgrs)
            self.send_json({"success":True,"manager_id":mid,"manager_name":mname,
                            "reset_count": current_reset_count}); return

        if path == "/api/check_manager_name":
            mname = str(b.get("manager_name") or "").strip()
            if not mname:
                self.send_json({"available": False, "error": "manager_name required."}); return
            with _lock:
                mgrs = _load_managers()
                available = not any(m["manager_name"].lower() == mname.lower() for m in mgrs.values())
                self.send_json({"available": available}); return

        if path == "/api/rollup":
            # Generate 5 fresh base stat sets for new team creation.
            from warrior import generate_base_stats
            from team    import TEAM_SIZE
            self.send_json({"rolls": [generate_base_stats() for _ in range(TEAM_SIZE)]}); return

        if path == "/api/rollup_single":
            # Generate 1 fresh base stat set for a replacement warrior.
            from warrior import generate_base_stats
            self.send_json({"base": generate_base_stats()}); return

        if path == "/api/team/create":
            # Standalone client creates a team: we validate credentials, assign
            # a unique team_id, build+save the Team server-side (as the host's
            # backup copy), and return the full team dict for the client to
            # save in its own folder via the File System Access API.
            mid = str(b.get("manager_id") or "").strip()
            pw  = str(b.get("password")   or "").strip()
            team_name     = str(b.get("team_name") or "").strip()
            warriors_data = b.get("warriors", [])
            if not mid or not pw:
                self.send_json({"success":False,"error":"manager_id and password required."}); return
            if not team_name:
                self.send_json({"success":False,"error":"Team name cannot be blank."}); return
            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs:
                    self.send_json({"success":False,"error":"Manager not found. Register first."}); return
                if not _check_mgr_pw(mgrs[mid], pw):
                    self.send_json({"success":False,"error":"Wrong password."}); return
                if len(mgrs[mid].get("team_ids", [])) >= 5:
                    self.send_json({"success":False,"error":"Maximum of 5 teams allowed per manager."}); return
                manager_name = mgrs[mid]["manager_name"]
            from team    import Team, TEAM_SIZE # This will be replaced by save_json_protected
            from warrior import Warrior, ATTRIBUTES
            from save    import save_team, next_team_id
            if len(warriors_data) < TEAM_SIZE:
                self.send_json({"success":False,"error":f"Need exactly {TEAM_SIZE} warriors."}); return
            try:
                team = Team(
                    team_name    = team_name.upper(),
                    manager_name = manager_name,
                    team_id      = next_team_id(),
                )
                import random as _rand
                for wd in warriors_data:
                    name = str(wd.get("name") or "").strip()
                    if not name:
                        self.send_json({"success":False,"error":"All warriors must have a name."}); return
                    w = Warrior(
                        name         = name.upper(),
                        race_name    = wd["race"],
                        gender       = wd["gender"],
                        strength     = int(wd["strength"]),
                        dexterity    = int(wd["dexterity"]),
                        constitution = int(wd["constitution"]),
                        intelligence = int(wd["intelligence"]),
                        presence     = int(wd["presence"]),
                        size         = int(wd["size"]),
                    )
                    w.luck = _rand.randint(1, 30)
                    w.initial_stats = {attr: int(wd[attr]) for attr in ATTRIBUTES}
                    w.armor = wd.get("armor", "None") or "None"
                    w.helm = wd.get("helm", "None") or "None"
                    w.primary_weapon = wd.get("primary_weapon", "Open Hand") or "Open Hand"
                    w.secondary_weapon = wd.get("secondary_weapon", "Open Hand") or "Open Hand"
                    w.backup_weapon = wd.get("backup_weapon")
                    team.add_warrior(w)
                save_team(team) # Protected
            except Exception as e:
                import traceback; traceback.print_exc()
                self.send_json({"success":False,"error":f"{e}"}); return
            # Record the team under the manager so the host has a manifest.
            with _lock:
                mgrs = _load_managers()
                if mid in mgrs:
                    tids = mgrs[mid].setdefault("team_ids", [])
                    if team.team_id not in tids:
                        tids.append(team.team_id) # This will be replaced by save_json_protected
                    _save_managers(mgrs)
            self.send_json({"success":True,"team_id":team.team_id,"team":team.to_dict()}); return

        if path == "/api/acknowledge_deleted_teams":
            mid = str(b.get("manager_id") or "").strip()
            pw  = str(b.get("password")   or "").strip()
            if not mid or not pw:
                self.send_json({"success":False,"error":"manager_id and password required."}); return
            with _lock:
                cfg = _load_config()
                mgrs = _load_managers()
                if mid in mgrs and _check_mgr_pw(mgrs[mid], pw):
                    # Clear deletion notification flags in config.json
                    keys_to_del = [k for k, v in cfg.items() if k.startswith("deleted_team_") and str(v.get("manager_id")) == mid]
                    for k in keys_to_del:
                        del cfg[k]
                    _save_config(cfg)
                    # Clear legacy field
                    mgrs[mid]["deleted_teams_notifs"] = []
                    _save_managers(mgrs)
                    self.send_json({"success":True}); return
                else:
                    self.send_json({"success":False,"error":"Not authorised."}, 401); return

        if path == "/api/scout/select":
            mid   = str(b.get("manager_id")   or "").strip()
            pw    = str(b.get("password")     or "").strip()
            wname = str(b.get("warrior_name") or "").strip()
            tname = str(b.get("team_name")    or "").strip()
            try:    tid = int(b.get("team_id", 0) or 0)
            except: tid = 0
            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                    self.send_json({"success":False,"error":"Not authorised."}, 401); return
            if not wname:
                self.send_json({"success":False,"error":"warrior_name required."}); return
            from save import add_manager_scouting, get_manager_scouting
            cfg = _load_config()
            arena_sel = str(b.get("arena") or "normal").strip()
            ok, err = add_manager_scouting(mid, cfg["current_turn"], wname, tname, tid, confirmed=True, arena=arena_sel)
            selections = get_manager_scouting(mid, cfg["current_turn"], arena=arena_sel)
            self.send_json({
                "success": ok, "error": err if not ok else "",
                "selections": selections,
                "slots_left": max(0, 3 - len(selections)),
            }); return

        if path == "/api/scout/remove":
            mid   = str(b.get("manager_id")   or "").strip()
            pw    = str(b.get("password")     or "").strip()
            wname = str(b.get("warrior_name") or "").strip()
            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                    self.send_json({"success":False,"error":"Not authorised."}, 401); return
            if not wname:
                self.send_json({"success":False,"error":"warrior_name required."}); return
            from save import remove_manager_scouting, get_manager_scouting
            cfg = _load_config()
            ok, err = remove_manager_scouting(mid, cfg["current_turn"], wname)
            selections = get_manager_scouting(mid, cfg["current_turn"])
            self.send_json({
                "success": ok, "error": err if not ok else "",
                "selections": selections,
                "slots_left": max(0, 3 - len(selections)),
            }); return

        if path == "/api/upload":
            mid = str(b.get("manager_id") or "").strip()
            pw = str(b.get("password") or "").strip()
            team = b.get("team")
            if not all([mid, pw, team]):
                _log_activity("upload_failed", mid, "?", "Missing required parameters")
                self.send_json({"success":False,"error":"manager_id, password and team required."}); return
            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs:
                    _log_activity("upload_failed", mid, "?", "Manager not found")
                    self.send_json({"success":False,"error":"Manager not found. Register first."}); return
                if not _check_mgr_pw(mgrs[mid], pw):
                    _log_activity("upload_failed", mid, mgrs[mid]["manager_name"], "Wrong password")
                    self.send_json({"success":False,"error":"Wrong password."}); return
                cfg = _load_config()
                if cfg["turn_state"] == "processing":
                    import datetime as _dt
                    started = cfg.get("processing_started_at","")
                    stuck = False
                    if started:
                        try:
                            elapsed = (_dt.datetime.now() - _dt.datetime.fromisoformat(started)).seconds
                            stuck = elapsed > 600
                        except Exception:
                            stuck = True
                    if not stuck:
                        self.send_json({"success":False,"error":"Turn is running. Try again shortly."}); return
                    print(" WARNING: turn_state was stuck as 'processing' - auto-recovering.")
                    cfg["turn_state"] = "open"; _save_config(cfg)
                if cfg["turn_state"] == "results_ready":
                    cfg["turn_state"] = "open"; _save_config(cfg)
                turn_num = cfg["current_turn"]
                team_id = team.get("team_id", "") if isinstance(team, dict) else "" # This will be replaced by save_json_protected

                # REGISTRY SYNC: Ensure this team ID is officially in the manager's
                # manifest. This fixes cases where registry data was lost or out of sync.
                if team_id:
                    tids = mgrs[mid].setdefault("team_ids", [])
                    _norm_tid = int(team_id) if str(team_id).isdigit() else team_id
                    if str(_norm_tid) not in [str(x) for x in tids]:
                        tids.append(_norm_tid)
                        # Save happens below after last_upload_timestamp update

                    # RESTORE SYNC: If this team was previously deleted via Admin Panel,
                    # clear the deletion record so the client stops thinking it's gone.
                    del_key = f"deleted_team_{_norm_tid}"
                    if del_key in cfg:
                        del cfg[del_key]; _save_config(cfg)

                # Check if the user unchecked 'Run This Turn'. If so, remove the
                # participation file for this specific team from the upcoming turn.
                if isinstance(team, dict) and not team.get("auto_upload_enabled", True):
                    fname = f"upload_{mid}_team{team_id}.json" if team_id else f"upload_{mid}.json"
                    fpath = os.path.join(_turn_dir(turn_num), fname)
                    if os.path.exists(fpath):
                        _safe_delete_file(fpath)  # Uploads are safe to delete
                    # Update manager activity timestamp to reflect the request
                    mgrs[mid]["last_upload_timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    _save_managers(mgrs)
                    _log_activity("upload_removed", mid, mgrs[mid]["manager_name"],
                                f"Team {team_id} removed from turn {turn_num}")
                    self.send_json({"success":True,"turn":turn_num,
                                    "message":f"Team removed from turn {turn_num} queue."}); return

                upload_time = time.strftime("%Y-%m-%d %H:%M:%S")
                _save_upload(turn_num, mid, {
                    "manager_id" : mid,
                    "manager_name": mgrs[mid]["manager_name"],
                    "team_id" : team_id,
                    "team" : team,
                    "uploaded_at" : upload_time,
                    "auto_upload_enabled": True, # Manual upload re-enables auto-upload
                })

                # --- FIX: Update persistent team file immediately ---
                # This ensures that a subsequent download/sync gets the version with the replacement
                from team import Team
                from save import save_team, load_team
                try:
                    t_obj = Team.from_dict(team)
                    # Preserve immortal arena assignments — the client's local copy may
                    # still have current_arena="normal" for warriors that were promoted
                    # server-side, so we must not let uploads overwrite those values.
                    try:
                        existing = load_team(int(team_id))
                        # Build lookup of warrior_name -> current_arena for immortal warriors
                        _immortal_arenas = {}
                        for _ew in (existing.warriors or []):
                            if _ew and getattr(_ew, "current_arena", "normal") in ("elite", "veteran"):
                                _immortal_arenas[_ew.name] = _ew.current_arena
                        for _ew in (getattr(existing, "archived_warriors", []) or []):
                            if isinstance(_ew, dict) and not _ew.get("is_dead", True):
                                _ea = _ew.get("current_arena") or "normal"
                                if _ea in ("elite", "veteran"):
                                    _immortal_arenas[_ew.get("name", "")] = _ea
                        # Apply preserved arenas to the incoming team object
                        if _immortal_arenas:
                            for _uw in (t_obj.warriors or []):
                                if _uw and _uw.name in _immortal_arenas:
                                    _uw.current_arena = _immortal_arenas[_uw.name]
                            for _uw in (getattr(t_obj, "archived_warriors", []) or []):
                                if isinstance(_uw, dict) and _uw.get("name") in _immortal_arenas:
                                    _uw["current_arena"] = _immortal_arenas[_uw["name"]]
                    except Exception:
                        pass  # If existing team can't be loaded, proceed without preservation
                    save_team(t_obj)
                    print(f"  Persistent team file updated for team {team_id} (replacement sync).")
                except Exception as e:
                    print(f"  WARNING: Could not update persistent team file during upload: {e}")
                
                # Result files from the previous turn are left in place so the manager
                # can still download them until the next turn actually runs.
                # _archive_old_results() handles cleanup at the start of each new turn.
                mgrs[mid]["last_upload_timestamp"] = upload_time # This will be replaced by save_json_protected
                _save_managers(mgrs)

                # Proactive cleanup: remove any other upload files for this manager
                # in the current turn directory that are no longer in their official
                # team_ids list, including the no-ID legacy file if they use IDs now.
                # Normalize registry for comparison (handle ints/strs/padding)
                tids_norm = [str(int(t)) if str(t).isdigit() else str(t) for t in mgrs[mid].get("team_ids", [])]
                td_path = _turn_dir(turn_num)
                if os.path.exists(td_path):
                    for fn in os.listdir(td_path):
                        is_match = False
                        chk_tid  = None
                        # Check if file belongs to this manager
                        if fn == f"upload_{mid}.json":
                            is_match = True
                        elif fn.startswith(f"upload_{mid}_team") and fn.endswith(".json"):
                            is_match = True
                            try: chk_tid = fn.split("_team")[-1].split(".")[0]
                            except: pass

                        if is_match:
                            # Skip the file we just saved (normalize to handle padding)
                            _cur_tid_str = str(int(team_id)) if str(team_id).isdigit() else str(team_id)
                            _chk_tid_str = str(int(chk_tid)) if chk_tid and chk_tid.isdigit() else chk_tid
                            if _chk_tid_str == _cur_tid_str: continue

                            if tids_norm: # If using IDs, check ID match; no-ID file is stale
                                if not _chk_tid_str or _chk_tid_str not in tids_norm:
                                    fpath = os.path.join(td_path, fn)
                                    # Safe deletion (archives result files, deletes uploads)
                                    _safe_delete_file(fpath, archive_to_turn=turn_num)
            team_name = team.get("team_name", "?") if isinstance(team, dict) else "?"
            _log_activity("upload_success", mid, mgrs[mid]["manager_name"],
                        f"Team {team_name} (ID:{team_id}) uploaded for turn {turn_num}")
            self.send_json({"success":True,"turn":turn_num,
                            "message":f"Team uploaded for turn {turn_num}."}); return

        if path == "/api/team/withdraw":
            # Remove a team's upload from the current turn and from the
            # manager's team_ids registry. Called when a client replaces a team
            # so the old team stops being auto-carried by the server.
            mid     = str(b.get("manager_id") or "").strip()
            pw      = str(b.get("password")   or "").strip()
            team_id = b.get("team_id")
            if not all([mid, pw, team_id]):
                self.send_json({"success": False, "error": "manager_id, password and team_id required."}); return
            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs:
                    self.send_json({"success": False, "error": "Manager not found."}); return
                if not _check_mgr_pw(mgrs[mid], pw):
                    self.send_json({"success": False, "error": "Wrong password."}, 401); return
                cfg      = _load_config()
                turn_num = cfg["current_turn"]
                # Delete the upload file for this team from the current turn dir.
                fname  = f"upload_{mid}_team{team_id}.json"

                fpath  = os.path.join(_turn_dir(turn_num), fname)
                removed_upload = False
                if os.path.exists(fpath):
                    _safe_delete_file(fpath)  # Uploads are safe to delete
                    removed_upload = True
                # Remove the team from the manager's server-side team_ids list.
                tids = mgrs[mid].get("team_ids", [])
                try:
                    int_tid = int(team_id)
                    mgrs[mid]["team_ids"] = [t for t in tids if int(t) != int_tid]
                except (ValueError, TypeError):
                    mgrs[mid]["team_ids"] = [t for t in tids if str(t) != str(team_id)]
                _save_managers(mgrs)
            self.send_json({"success": True, "removed_upload": removed_upload}); return

        if path == "/api/run_turn":
            pw    = b.get("host_password", "")
            arena = b.get("arena", "normal")
            rerun = b.get("rerun_turn")
            if arena in ("elite", "veteran"):
                self.send_json(_run_immortal_turn(arena, pw)); return
            self.send_json(_run_turn(pw, rerun_turn=int(rerun) if rerun else None)); return

        if path == "/api/admin/promote_warrior":
            # Manually promote a warrior to elite or veteran arena.
            # Body: {host_password, team_id, warrior_name, target_arena}
            pw          = b.get("host_password", "")
            cfg         = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            tid         = int(b.get("team_id", -1))
            w_name      = str(b.get("warrior_name", "")).strip()
            target      = str(b.get("target_arena", "elite")).strip()
            if target not in ("elite", "veteran"):
                self.send_json({"success": False, "error": "target_arena must be 'elite' or 'veteran'"}); return
            from save import load_all_teams, save_team
            all_teams = load_all_teams()
            team = next((t for t in all_teams if t.team_id == tid), None)
            if not team:
                self.send_json({"success": False, "error": f"Team {tid} not found."}); return
            warrior = team.warrior_by_name(w_name) if hasattr(team, "warrior_by_name") else None
            if warrior is None:
                warrior = next((w for w in (team.warriors or []) if w and w.name == w_name), None)
            if warrior is None:
                self.send_json({"success": False, "error": f"Warrior '{w_name}' not found in team {tid}."}); return
            if getattr(warrior, "current_arena", "normal") != "normal":
                self.send_json({"success": False, "error": f"Warrior is already in {warrior.current_arena} arena."}); return
            warrior.current_arena    = target
            warrior.pending_promotion = None
            warrior.recognition       = 0
            save_team(team)
            _save_immortal_team(target, team.to_dict())
            _disp = {"elite": "The Elite Spire", "veteran": "The Dead Grounds"}.get(target, target)
            self.send_json({"success": True,
                            "message": f"{warrior.name} has been manually promoted to {_disp}.",
                            "warrior": warrior.name, "team": team.team_name, "arena": target}); return

        if path == "/api/immortal_upload":
            # Upload team data for an immortal arena (Elite Spire or Dead Grounds).
            # Completely separate from the normal-arena upload — writes to
            # saves/{arena}/uploads/team_XXXX.json only.
            # Body: {arena, team_id, team, manager_name}  (no auth — same as normal upload)
            _i_arena = str(b.get("arena", "")).strip()
            if _i_arena not in ("elite", "veteran"):
                self.send_json({"success": False,
                                "error": "arena must be 'elite' or 'veteran'"}); return
            _i_tid  = int(b.get("team_id", 0) or 0)
            _i_team = b.get("team")
            if not _i_tid or not _i_team:
                self.send_json({"success": False,
                                "error": "team_id and team are required"}); return
            if not isinstance(_i_team, dict):
                self.send_json({"success": False,
                                "error": "team must be a dict"}); return
            # Verify this team actually has warriors in this arena (anti-spam)
            _i_base = _load_immortal_teams(_i_arena)
            _i_base_ids = {int(t.get("team_id", 0)) for t in _i_base}
            if _i_tid not in _i_base_ids:
                self.send_json({"success": False,
                                "error": f"Team {_i_tid} has no warriors in {_i_arena}."}); return
            # Write to saves/{arena}/uploads/team_XXXX.json
            _iu_dir = _immortal_upload_dir(_i_arena)
            os.makedirs(_iu_dir, exist_ok=True)
            _iu_path = os.path.join(_iu_dir, f"team_{_i_tid:04d}.json")
            # Merge uploaded warrior stats into the arena snapshot (update only
            # fields that change, preserve current_arena/is_dead from the snapshot)
            _i_snapshot = next((t for t in _i_base if int(t.get("team_id", 0)) == _i_tid), {})
            _i_merged = dict(_i_snapshot)
            # Refresh warrior stats from the upload while keeping arena-specific fields
            _i_name_map = {}
            for _iw in (_i_team.get("warriors") or []) + (_i_team.get("archived_warriors") or []):
                if isinstance(_iw, dict) and _iw.get("name"):
                    _i_name_map[_iw["name"]] = _iw
            for _section in ("warriors", "archived_warriors"):
                for _iw in (_i_merged.get(_section) or []):
                    if not isinstance(_iw, dict): continue
                    _src = _i_name_map.get(_iw.get("name", ""))
                    if _src:
                        _keep = {k: _iw[k] for k in ("current_arena", "is_dead")
                                 if k in _iw}
                        _iw.update(_src)
                        _iw.update(_keep)
            with open(_iu_path, "w", encoding="utf-8") as _f:
                json.dump(_i_merged, _f, indent=2)
            self.send_json({"success": True, "arena": _i_arena,
                            "team_id": _i_tid,
                            "message": f"Team {_i_tid} uploaded for {_i_arena}."}); return

        if path == "/api/admin/retire_warrior":
            # Retire a warrior directly to The Dead Grounds (manager request path).
            # Body: {host_password, team_id, warrior_name}
            pw     = b.get("host_password", "")
            cfg    = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            tid    = int(b.get("team_id", -1))
            w_name = str(b.get("warrior_name", "")).strip()
            from save import load_all_teams, save_team
            all_teams = load_all_teams()
            team = next((t for t in all_teams if t.team_id == tid), None)
            if not team:
                self.send_json({"success": False, "error": f"Team {tid} not found."}); return
            warrior = next((w for w in (team.warriors or []) if w and w.name == w_name), None)
            if warrior is None:
                self.send_json({"success": False, "error": f"Warrior '{w_name}' not found."}); return
            if getattr(warrior, "current_arena", "normal") != "normal":
                self.send_json({"success": False, "error": f"Warrior is already in {warrior.current_arena}."}); return
            warrior.pending_promotion = "veteran"
            save_team(team)
            self.send_json({"success": True,
                            "message": f"{warrior.name} is marked for retirement to The Dead Grounds. "
                                       f"They will fight one final bout next turn before moving.",
                            "warrior": warrior.name, "team": team.team_name}); return

        if path == "/api/admin/resurrect_warrior":
            # Resurrect a dead warrior directly into an immortal arena.
            # Searches team.warriors (Warrior objects) first, then team.archived_warriors (dicts).
            # Body: {host_password, team_id, warrior_name, target_arena}
            pw     = b.get("host_password", "")
            cfg    = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            tid    = int(b.get("team_id", -1))
            w_name = str(b.get("warrior_name", "")).strip()
            target = str(b.get("target_arena", "elite")).strip()
            if target not in ("elite", "veteran"):
                self.send_json({"success": False, "error": "target_arena must be 'elite' or 'veteran'"}); return
            from save import load_all_teams, save_team
            all_teams = load_all_teams()
            team = next((t for t in all_teams if t.team_id == tid), None)
            if not team:
                self.send_json({"success": False, "error": f"Team {tid} not found."}); return

            _disp = {"elite": "The Elite Spire", "veteran": "The Dead Grounds"}.get(target, target)

            # 1. Search active warriors list (Warrior objects)
            warrior = next((w for w in (team.warriors or []) if w and w.name == w_name), None)
            if warrior is not None:
                if not warrior.is_dead:
                    self.send_json({"success": False,
                                    "error": f"{warrior.name} is not dead. Use promote_warrior instead."}); return
                # Move dead warrior from roster to archived_warriors as immortal entry.
                # This frees the roster slot and avoids TEAM_SIZE truncation issues.
                slot_idx = next((i for i, s in enumerate(team.warriors) if s and s.name == w_name), None)
                if slot_idx is not None:
                    team.warriors[slot_idx] = None
                arch_entry = warrior.to_dict()
                arch_entry["is_dead"]           = False
                arch_entry["current_arena"]     = target
                arch_entry["pending_promotion"] = None
                arch_entry["recognition"]       = 0
                arch_entry["hp"] = max(1, getattr(warrior, "max_hp", 100))
                team.archived_warriors = getattr(team, "archived_warriors", None) or []
                team.archived_warriors.append(arch_entry)
                save_team(team)
                _save_immortal_team(target, team.to_dict())
                self.send_json({"success": True,
                                "message": f"{warrior.name} has been resurrected and placed in {_disp}.",
                                "warrior": warrior.name, "team": team.team_name, "arena": target}); return

            # 2. Search archived_warriors (raw dicts — historical dead)
            arch_idx = next(
                (i for i, w in enumerate(team.archived_warriors or [])
                 if isinstance(w, dict) and w.get("name") == w_name),
                None
            )
            if arch_idx is None:
                self.send_json({"success": False,
                                "error": f"Warrior '{w_name}' not found in team {tid}."}); return
            arch_dict = team.archived_warriors[arch_idx]
            # Update the archived entry in-place — no roster slot consumed.
            # Immortal arena warriors live in archived_warriors with is_dead=False.
            arch_dict["is_dead"]           = False
            arch_dict["current_arena"]     = target
            arch_dict["pending_promotion"] = None
            arch_dict["recognition"]       = 0
            arch_dict["hp"] = max(1, int(arch_dict.get("max_hp") or arch_dict.get("hp") or 100))
            save_team(team)
            _save_immortal_team(target, team.to_dict())
            self.send_json({"success": True,
                            "message": f"{arch_dict['name']} has been resurrected and placed in {_disp}.",
                            "warrior": arch_dict["name"], "team": team.team_name, "arena": target}); return

        if path == "/api/admin/list_promotion_candidates":
            # Return all normal-arena warriors eligible for or pending promotion.
            # Body: {host_password}
            pw  = b.get("host_password", "")
            cfg = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            promo_cfg    = cfg.get("promotion_criteria", {})
            min_fights   = int(promo_cfg.get("min_fights",   40))
            min_win_rate = float(promo_cfg.get("min_win_rate", 0.55))
            from save import load_all_teams
            all_teams = load_all_teams()
            pending, eligible, ineligible = [], [], []
            for team in all_teams:
                for w in (team.active_warriors or []):
                    if not w or getattr(w, "current_arena", "normal") != "normal":
                        continue
                    total = w.wins + w.losses
                    wr    = w.wins / total if total > 0 else 0.0
                    entry = {
                        "warrior_name": w.name, "team_name": team.team_name,
                        "team_id": team.team_id, "record": f"{w.wins}W/{w.losses}L/{w.kills}K",
                        "total_fights": total, "win_rate": round(wr, 4),
                        "pending_promotion": getattr(w, "pending_promotion", None),
                        "min_fights": min_fights, "min_win_rate": min_win_rate,
                    }
                    if getattr(w, "pending_promotion", None):
                        pending.append(entry)
                    elif total >= min_fights and wr >= min_win_rate:
                        eligible.append(entry)
                    else:
                        ineligible.append(entry)
            self.send_json({"success": True, "pending": pending,
                            "eligible": eligible, "ineligible": ineligible}); return

        if path == "/api/admin/promotion_panel_data":
            # Unified data for the Manage Promotions admin panel.
            # Scans both team.warriors (Warrior objects) and team.archived_warriors (dicts).
            # Dead warriors: all with 1+ fight shown — no win-rate pre-filter, admin decides.
            pw  = b.get("host_password", "")
            cfg = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            promo_cfg    = cfg.get("promotion_criteria", {})
            min_fights   = int(promo_cfg.get("min_fights",   30))
            min_win_rate = float(promo_cfg.get("min_win_rate", 0.65))
            min_trains   = int(promo_cfg.get("min_trains",   30))
            from save import load_all_teams
            all_teams = load_all_teams()
            pending, living_eligible, dead_warriors = [], [], []
            elite_roster, veteran_roster = [], []
            _dead_seen = set()  # deduplicate by (team_id, name)

            def _wval(w, attr, default=None):
                """Get field from either a Warrior object or a raw dict."""
                if isinstance(w, dict):
                    return w.get(attr, default)
                return getattr(w, attr, default)

            def _trains_from_any(w):
                skills     = _wval(w, "skills") or {}
                attr_gains = _wval(w, "attribute_gains") or {}
                if isinstance(skills, dict) and isinstance(attr_gains, dict):
                    return sum(skills.values()) + sum(attr_gains.values())
                return 0

            for team in all_teams:
                # --- active warrior objects (alive, pending, or recently dead) ---
                for w in (team.warriors or []):
                    if not w:
                        continue
                    wins   = _wval(w, "wins",   0)
                    losses = _wval(w, "losses", 0)
                    kills  = _wval(w, "kills",  0)
                    total  = wins + losses
                    wr     = wins / total if total > 0 else 0.0
                    trains = _trains_from_any(w)
                    is_dead = _wval(w, "is_dead", False)
                    arena   = _wval(w, "current_arena", "normal") or "normal"
                    name    = _wval(w, "name", "")
                    base    = {
                        "warrior_name": name, "team_name": team.team_name,
                        "team_id": team.team_id,
                        "record": f"{wins}W/{losses}L/{kills}K",
                        "total_fights": total, "win_rate": round(wr, 4),
                        "total_trains": trains,
                        "source": "active",
                    }
                    if is_dead:
                        key = (team.team_id, name)
                        if total >= 1 and key not in _dead_seen:
                            _dead_seen.add(key)
                            dead_warriors.append(base)
                    elif arena in ("elite", "veteran"):
                        if arena == "elite":
                            elite_roster.append(base)
                        else:
                            veteran_roster.append(base)
                    elif arena == "normal":
                        pending_promo = _wval(w, "pending_promotion", None)
                        if pending_promo:
                            pending.append({**base, "pending_promotion": pending_promo})
                        elif (total >= min_fights and wr >= min_win_rate
                              and trains >= min_trains):
                            living_eligible.append(base)

                # --- archived warriors (dicts — historical dead + immortal arena members) ---
                for w in (team.archived_warriors or []):
                    if not isinstance(w, dict) or not w.get("name"):
                        continue
                    name  = w.get("name", "")
                    key   = (team.team_id, name)
                    if key in _dead_seen:
                        continue
                    is_arch_dead = w.get("is_dead", True)
                    arena = w.get("current_arena") or "normal"
                    wins   = w.get("wins",   0)
                    losses = w.get("losses", 0)
                    kills  = w.get("kills",  0)
                    total  = wins + losses
                    wr     = wins / total if total > 0 else 0.0
                    trains = _trains_from_any(w)
                    entry = {
                        "warrior_name": name, "team_name": team.team_name,
                        "team_id": team.team_id,
                        "record": f"{wins}W/{losses}L/{kills}K",
                        "total_fights": total, "win_rate": round(wr, 4),
                        "total_trains": trains,
                        "source": "archived",
                    }
                    # Immortal arena members: alive, stored in archive to avoid roster cap
                    if not is_arch_dead and arena in ("elite", "veteran"):
                        _dead_seen.add(key)
                        if arena == "elite":
                            elite_roster.append(entry)
                        else:
                            veteran_roster.append(entry)
                        continue
                    # Skip living archived warriors not in an immortal arena
                    if not is_arch_dead:
                        continue
                    # Dead warriors with current_arena=elite/veteran are in a
                    # "stuck" state (upload reverted is_dead but left the arena tag).
                    # Show them in dead_warriors so the host can re-resurrect them.
                    # Normal (clean) dead warriors have arena="normal" or missing.
                    # Dead warrior available for resurrection
                    if total < 1:
                        continue
                    _dead_seen.add(key)
                    dead_warriors.append(entry)

            dead_warriors.sort(key=lambda x: (-x["win_rate"], -x["total_fights"]))
            living_eligible.sort(key=lambda x: (-x["win_rate"], -x["total_fights"]))
            elite_roster.sort(key=lambda x: (-x["win_rate"], -x["total_fights"]))
            veteran_roster.sort(key=lambda x: (-x["win_rate"], -x["total_fights"]))
            self.send_json({
                "success": True,
                "pending": pending,
                "living_eligible": living_eligible,
                "dead_warriors": dead_warriors,
                "elite_roster": elite_roster,
                "veteran_roster": veteran_roster,
                "criteria": {
                    "elite_min_fights": min_fights,
                    "elite_min_win_rate": min_win_rate,
                    "elite_min_trains": min_trains,
                },
            }); return

        if path == "/api/admin/clear_arena":
            # Remove all warriors from an immortal arena, reset turn counter & standings.
            # Warriors are returned to current_arena="normal" (records preserved).
            # Body: {host_password, arena}
            pw    = b.get("host_password", "")
            cfg   = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            arena = str(b.get("arena", "")).strip()
            if arena not in ("elite", "veteran"):
                self.send_json({"success": False, "error": "arena must be 'elite' or 'veteran'"}); return
            arena_cfg_path = os.path.join(BASE_DIR, "saves", arena, "config.json")
            if not os.path.exists(arena_cfg_path):
                self.send_json({"success": False, "error": f"Arena '{arena}' not initialised."}); return
            from save import load_all_teams, save_team
            all_teams  = load_all_teams()
            moved      = 0
            for team in all_teams:
                changed = False
                for w in (team.warriors or []):
                    if not w:
                        continue
                    if getattr(w, "current_arena", "normal") == arena:
                        w.current_arena    = "normal"
                        w.pending_promotion = None
                        moved   += 1
                        changed  = True
                    # Also clear any warriors pending INTO this arena from normal
                    if getattr(w, "pending_promotion", None) == arena:
                        w.pending_promotion = None
                        changed = True
                if changed:
                    try:
                        save_team(team)
                    except Exception as _se:
                        print(f"  WARNING clear_arena: save_team failed: {_se}")
            # Reset arena config
            with open(arena_cfg_path, encoding="utf-8") as _f:
                arena_cfg = json.load(_f)
            arena_cfg["turn_counter"] = 0
            arena_cfg["turn_state"]   = "open"
            with open(arena_cfg_path, "w", encoding="utf-8") as _f:
                json.dump(arena_cfg, _f, indent=2)
            # Reset standings
            standings_path = os.path.join(BASE_DIR, "saves", arena, "standings.json")
            with open(standings_path, "w", encoding="utf-8") as _f:
                json.dump({"teams": {}, "turn": 0}, _f, indent=2)
            _disp = {"elite": "The Elite Spire", "veteran": "The Dead Grounds"}.get(arena, arena)
            self.send_json({
                "success": True,
                "message": f"{_disp} cleared. {moved} warrior(s) returned to the Normal Arena.",
                "warriors_moved": moved,
            }); return

        if path == "/api/admin/get_arena_newsletter":
            # Return the newsletter text for the latest (or specified) turn of an immortal arena.
            # Body: {host_password, arena, turn (optional)}
            pw    = b.get("host_password", "")
            cfg   = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            arena = str(b.get("arena", "elite")).strip()
            if arena not in ("elite", "veteran"):
                self.send_json({"success": False, "error": "arena must be 'elite' or 'veteran'"}); return
            arena_cfg_path = os.path.join(BASE_DIR, "saves", arena, "config.json")
            if not os.path.exists(arena_cfg_path):
                self.send_json({"success": False, "error": f"Arena '{arena}' not initialised."}); return
            with open(arena_cfg_path, encoding="utf-8") as _f:
                arena_cfg = json.load(_f)
            req_turn = b.get("turn") or arena_cfg.get("turn_counter", 0)
            if not req_turn:
                self.send_json({"success": False, "error": "No turns have been run yet."}); return
            nl_path = os.path.join(BASE_DIR, "saves", arena,
                                   f"turn_{int(req_turn):04d}", "newsletter.txt")
            if not os.path.exists(nl_path):
                self.send_json({"success": False,
                                "error": f"Newsletter for turn {req_turn} not found."}); return
            with open(nl_path, encoding="utf-8") as _f:
                content = _f.read()
            _disp = {"elite": "THE ELITE SPIRE", "veteran": "THE DEAD GROUNDS"}.get(arena, arena.upper())
            self.send_json({
                "success": True, "arena": arena, "arena_display": _disp,
                "turn": req_turn, "content": content,
            }); return

        if path == "/api/admin/get_arena_schedule":
            # Return scheduler config for elite or veteran.
            # Body: {host_password, arena}
            pw    = b.get("host_password", "")
            cfg   = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            arena = str(b.get("arena", "elite")).strip()
            if arena not in ("elite", "veteran"):
                self.send_json({"success": False, "error": "arena must be 'elite' or 'veteran'"}); return
            arena_cfg_path = os.path.join(BASE_DIR, "saves", arena, "config.json")
            if not os.path.exists(arena_cfg_path):
                self.send_json({"success": False, "error": f"Arena '{arena}' not initialised."}); return
            with open(arena_cfg_path, encoding="utf-8") as _f:
                arena_cfg = json.load(_f)
            sched = arena_cfg.get("scheduler", {})
            self.send_json({
                "success": True, "arena": arena,
                "turn_counter": arena_cfg.get("turn_counter", 0),
                "turn_state":   arena_cfg.get("turn_state",   "open"),
                "enabled":      sched.get("enabled", False),
                "schedule_slots": sched.get("schedule_slots", []),
            }); return

        if path == "/api/admin/set_arena_schedule":
            # Update scheduler settings for elite or veteran.
            # Body: {host_password, arena, enabled (bool), schedule_slots (list)}
            pw    = b.get("host_password", "")
            cfg   = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            arena = str(b.get("arena", "elite")).strip()
            if arena not in ("elite", "veteran"):
                self.send_json({"success": False, "error": "arena must be 'elite' or 'veteran'"}); return
            arena_cfg_path = os.path.join(BASE_DIR, "saves", arena, "config.json")
            if not os.path.exists(arena_cfg_path):
                self.send_json({"success": False, "error": f"Arena '{arena}' not initialised."}); return
            with open(arena_cfg_path, encoding="utf-8") as _f:
                arena_cfg = json.load(_f)
            sched = arena_cfg.setdefault("scheduler", {})
            if "enabled" in b:
                sched["enabled"] = bool(b["enabled"])
            if "schedule_slots" in b:
                import re as _re
                _VALID_DAYS = ("Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday")
                _raw   = b["schedule_slots"]
                _clean = []
                _seen  = set()
                if isinstance(_raw, list):
                    for _s in _raw:
                        if not isinstance(_s, dict): continue
                        _d = _s.get("day",  "")
                        _t = str(_s.get("time", ""))
                        if _d not in _VALID_DAYS: continue
                        if not _re.match(r"^\d{2}:\d{2}$", _t): continue
                        _key = f"{_d}_{_t}"
                        if _key in _seen: continue
                        _seen.add(_key)
                        _existing = next(
                            (x for x in sched.get("schedule_slots", [])
                             if x.get("day") == _d and x.get("time") == _t), {}
                        )
                        _clean.append({
                            "day": _d, "time": _t,
                            "last_run_at":     _existing.get("last_run_at", ""),
                            "last_run_turn":   _existing.get("last_run_turn", 0),
                            "last_run_result": _existing.get("last_run_result", ""),
                        })
                sched["schedule_slots"] = _clean
            arena_cfg["scheduler"] = sched
            with open(arena_cfg_path, "w", encoding="utf-8") as _f:
                json.dump(arena_cfg, _f, indent=2)
            self.send_json({
                "success": True,
                "message": f"{arena} scheduler updated.",
                "arena":   arena,
                "enabled": sched.get("enabled", False),
                "schedule_slots": sched.get("schedule_slots", []),
            }); return

        if path == "/api/admin/list_dead_warriors":
            # Return all dead warriors eligible for resurrection.
            # Body: {host_password}
            pw  = b.get("host_password", "")
            cfg = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            from save import load_all_teams
            all_teams  = load_all_teams()
            dead_list  = []
            for team in all_teams:
                for w in (team.warriors or []):
                    if not w or not w.is_dead:
                        continue
                    total = w.wins + w.losses
                    wr    = w.wins / total if total > 0 else 0.0
                    dead_list.append({
                        "warrior_name": w.name, "team_name": team.team_name,
                        "team_id": team.team_id, "record": f"{w.wins}W/{w.losses}L/{w.kills}K",
                        "total_fights": total, "win_rate": round(wr, 4),
                    })
            dead_list.sort(key=lambda x: x["win_rate"], reverse=True)
            self.send_json({"success": True, "dead_warriors": dead_list,
                            "count": len(dead_list)}); return

        if path == "/api/team/get_my_team":
            mid = str(b.get("manager_id") or "").strip()
            pw  = str(b.get("password")   or "").strip()
            team_id = b.get("team_id") # Optional: if manager has multiple teams, specify which one
            if not all([mid, pw]):
                self.send_json({"success":False,"error":"manager_id and password required."}); return
            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs:
                    self.send_json({"success":False,"error":"Manager not found. Register first."}); return
                if not _check_mgr_pw(mgrs[mid], pw):
                    self.send_json({"success":False,"error":"Wrong password."}); return

                from save import load_team # This will be replaced by load_json_protected
                manager_teams = []
                # If a specific team_id is requested, try to load only that one
                if team_id:
                    if team_id in mgrs[mid].get("team_ids", []):
                        try:
                            team = load_team(team_id)
                            manager_teams.append(team.to_dict())
                        except FileNotFoundError:
                            self.send_json({"success":False,"error":f"Team {team_id} not found on server."}); return
                    else:
                        self.send_json({"success":False,"error":f"Team {team_id} does not belong to manager {mid}."}); return
                else: # Load all teams for this manager
                    for tid in mgrs[mid].get("team_ids", []):
                        try:
                            team = load_team(tid)
                            manager_teams.append(team.to_dict())
                        except FileNotFoundError:
                            print(f"  WARNING: Team {tid} listed for manager {mid} but file not found on server.")
                            # Continue to load other teams

                if not manager_teams:
                    self.send_json({"success":False,"error":"No teams found for this manager on the server."}); return

                # Filter team data based on feature flags before sending to client
                cfg = _load_config()
                filtered_teams = []
                for team_dict in manager_teams:
                    filtered_warriors = []
                    for w_dict in team_dict.get("warriors", []):
                        if w_dict:
                            filtered_warriors.append(_filter_warrior_for_client(w_dict, cfg))
                        else:
                            filtered_warriors.append(None)
                    team_dict["warriors"] = filtered_warriors
                    filtered_teams.append(team_dict)
                    # auto_upload_enabled and last_turn_ran are already in team_dict via to_dict()

                self.send_json({"success":True,"teams":filtered_teams}); return

        if path == "/api/league/check_reset":
            mid = str(b.get("manager_id") or "").strip()
            cfg  = _load_config()
            mgrs = _load_managers()

            server_reset_count = cfg.get("reset_count", 0)
            server_rerun_count = cfg.get("rerun_count", 0)
            server_rerun_turn  = cfg.get("rerun_turn",  0)

            manager_exists = mid in mgrs
            # Default to (server_count - 1) so managers who predate this feature
            # still get notified about the most recent reset/rerun event.
            mgr_ack_reset  = mgrs[mid].get("acknowledged_reset_count", max(0, server_reset_count - 1)) if manager_exists else 0
            reset_detected = (not manager_exists) or (server_reset_count > mgr_ack_reset)

            rerun_detected = False
            if manager_exists and not reset_detected and server_rerun_count > 0:
                mgr_ack_rerun  = mgrs[mid].get("acknowledged_rerun_count", max(0, server_rerun_count - 1))
                rerun_detected = server_rerun_count > mgr_ack_rerun

            self.send_json({
                "success":            True,
                "reset_detected":     reset_detected,
                "server_reset_count": server_reset_count,
                "rerun_detected":     rerun_detected,
                "rerun_turn":         server_rerun_turn if rerun_detected else 0,
                "rerun_count":        server_rerun_count,
            }); return

        if path == "/api/league/acknowledge_reset":
            mid      = str(b.get("manager_id") or "").strip()
            pw       = str(b.get("password")   or "").strip()
            ack_type = str(b.get("type", "reset")).strip()  # "reset" or "rerun"

            mgrs = _load_managers()

            if ack_type == "rerun":
                if mid not in mgrs:
                    self.send_json({"success":False,"error":"Manager not found."}); return
                # No password required - this is a read-receipt flag, not a state change
                mgrs[mid]["acknowledged_rerun_count"] = int(b.get("rerun_count", 0))
                _save_managers(mgrs)
                self.send_json({"success": True}); return
            else:
                # "reset" acknowledgment - no password required (read-receipt + team data pull)
                server_reset_count = int(b.get("server_reset_count", 0))
                teams_out = []
                if mid in mgrs:
                    mgrs[mid]["acknowledged_reset_count"] = server_reset_count
                    # Return each reverted team so the client can apply them locally
                    from save import load_team
                    for tid in mgrs[mid].get("team_ids", []):
                        try:
                            team = load_team(int(tid))
                            teams_out.append({"team_id": int(tid), "team": team.to_dict()})
                        except Exception:
                            pass
                    _save_managers(mgrs)
                    self.send_json({"success": True, "teams": teams_out, "full_reset": False, "clear_local_results": True}); return
                else:
                    # Manager no longer exists (full reset) - just acknowledge
                    self.send_json({"success": True, "teams": [], "full_reset": True, "clear_local_results": True}); return

        if path == "/api/arena/reset":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password","")):
                self.send_json({"success":False,"error":"Not authorised."}); return

            def _rm_error(func, path, _):
                make_file_writable(path)
                func(path)

            # Archive all result files before deleting turn directories (CRITICAL: preserve for auditing)
            for entry in os.listdir(LEAGUE_DIR):
                full = os.path.join(LEAGUE_DIR, entry)
                if entry.startswith("turn_") and os.path.isdir(full):
                    try:
                        turn_num = int(entry.split("_")[1])
                        _archive_old_results(turn_num)
                    except:
                        pass
                    shutil.rmtree(full, onerror=_rm_error)

            # Remove individual protected files and their checksums
            for fname in ("ai_teams.json", "managers.json", "standings.json",
                          "scout_narratives.json", "scouting.json"):
                fpath = os.path.join(LEAGUE_DIR, fname)
                checksum_fpath = fpath.replace('.json', '.checksum')
                if os.path.exists(checksum_fpath):
                    make_file_writable(checksum_fpath)
                    os.remove(checksum_fpath)
                if os.path.exists(fpath):
                    make_file_writable(fpath)
                    os.remove(fpath)

            # The live scouting store is actually saves/scouting.json, so clear
            # that file too; otherwise old turn-1 selections survive a reset and
            # reappear when current_turn is reset back to 1.
            from save import TEAMS_DIR, GRAVEYARD_DIR, SCOUTING_FILE, save_champion_state
            # Remove protected files and their checksums
            for fpath in (SCOUTING_FILE,):
                if os.path.exists(fpath):
                    make_file_writable(fpath)
                    os.remove(fpath)
                    checksum_fpath = fpath.replace('.json', '.checksum')
                    if os.path.exists(checksum_fpath):
                        make_file_writable(checksum_fpath)
                        os.remove(checksum_fpath)

            # Clean up global teams, graveyard and reset champion state
            if os.path.exists(TEAMS_DIR):
                for f in os.listdir(TEAMS_DIR):
                    if f.startswith("team_") and f.endswith(".json"): # These are protected files
                        fpath = os.path.join(TEAMS_DIR, f)
                        make_file_writable(fpath)
                        try: os.remove(fpath)
                        except: pass
                        cfpath = fpath.replace('.json', '.checksum')
                        if os.path.exists(cfpath):
                            make_file_writable(cfpath)
                            try: os.remove(cfpath)
                            except: pass
            if os.path.exists(GRAVEYARD_DIR):
                for f in os.listdir(GRAVEYARD_DIR):
                    if f.endswith(".json") or f.endswith(".checksum"): # These are protected files
                        fpath = os.path.join(GRAVEYARD_DIR, f)
                        make_file_writable(fpath)
                        try: os.remove(fpath)
                        except: pass
                    elif f.endswith(".txt"):
                        try:
                            fp = os.path.join(GRAVEYARD_DIR, f)
                            make_file_writable(fp)
                            os.remove(fp)
                        except: pass
            try:
                save_champion_state({})
            except Exception:
                pass

            _turn_progress = {"running": False, "done": 0, "total": 0, "message": "Reset complete"}

            cfg["current_turn"] = 1; cfg["turn_state"] = "open"; cfg["fight_counter"] = 0
            cfg["schedule_last_run_at"] = "" # This will be replaced by save_json_protected
            cfg["processing_started_at"] = ""
            cfg["schedule_last_run_turn"] = 0
            cfg["schedule_last_run_result"] = ""
            for _sl in cfg.get("schedule_slots", []):
                _sl["last_run_at"] = ""; _sl["last_run_turn"] = 0; _sl["last_run_result"] = ""
            cfg["reset_count"] = cfg.get("reset_count", 0) + 1
            _save_config(cfg)
            self.send_json({"success":True,
                            "message":"League fully reset to turn 1. All manager registrations and standings cleared.", "clear_local_results": True}); return

        if path == "/api/arena/reset_progress":
            # Reset progress but keep managers and teams
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password","")):
                self.send_json({"success":False,"error":"Not authorised."}, 401); return
            
            with _lock:
                # 1. Revert all player teams on disk
                from save import TEAMS_DIR, load_team, save_team
                if os.path.exists(TEAMS_DIR):
                    for fn in os.listdir(TEAMS_DIR):
                        if fn.startswith("team_") and fn.endswith(".json"):
                            try:
                                fpath = os.path.join(TEAMS_DIR, fn)
                                # Load directly to avoid brittle ID-padding lookups
                                from team import Team
                                tdata = load_json_protected(fpath, allow_tampered=True)
                                team = Team.from_dict(tdata)
                                team.revert_all_progress()
                                # Explicitly clear archived history that contributes to career totals
                                team.archived_warriors = []
                                team.turn_history = []
                                save_json_protected(fpath, team.to_dict())
                            except Exception as e:
                                print(f"  ERROR reverting team {fn}: {e}")
                
                # 2. Revert AI teams
                ai_teams_path = os.path.join(LEAGUE_DIR, "ai_teams.json")
                if os.path.exists(ai_teams_path):
                    ai_teams_data = _load_json(ai_teams_path, [])
                    if ai_teams_data:
                        from team import Team
                        reverted_ai = []
                        for ad in ai_teams_data:
                            t = Team.from_dict(ad)
                            t.revert_all_progress()
                            # Clear history for AI teams as well
                            t.archived_warriors = []
                            t.turn_history = []
                            reverted_ai.append(t.to_dict())
                        _save_json(ai_teams_path, reverted_ai)
                
                # 3. Clear standings
                _save_standings({})

                # 3b. Clear champion (no champion at turn 1)
                from save import CHAMPION_FILE
                print(f"  DEBUG: Checking for champion file at: {CHAMPION_FILE}")
                if os.path.exists(CHAMPION_FILE):
                    print(f"  DEBUG: Found champion.json, deleting...")
                    make_file_writable(CHAMPION_FILE)
                    os.remove(CHAMPION_FILE)
                    print(f"  DEBUG: champion.json deleted")
                champion_checksum = CHAMPION_FILE.replace('.json', '.checksum')
                print(f"  DEBUG: Checking for checksum at: {champion_checksum}")
                if os.path.exists(champion_checksum):
                    print(f"  DEBUG: Found champion.checksum, deleting...")
                    make_file_writable(champion_checksum)
                    os.remove(champion_checksum)
                    print(f"  DEBUG: champion.checksum deleted")

                # 4. Clear manager registries to force reset-notification and fresh login state
                mgrs = _load_managers()
                for mid in mgrs:
                    mgrs[mid]["acknowledged_reset_count"] = 0
                _save_managers(mgrs)

                # 4. Wipe turn directories (but archive results first - CRITICAL)
                for entry in os.listdir(LEAGUE_DIR):
                    full = os.path.join(LEAGUE_DIR, entry)
                    if entry.startswith("turn_") and os.path.isdir(full):
                        try:
                            turn_num = int(entry.split("_")[1])
                            # Archive all result files before deletion (CRITICAL: preserve for auditing)
                            _archive_old_results(turn_num)
                        except:
                            pass

                        if entry == "turn_0001":
                            # Keep turn_0001 directory but revert data inside uploads
                            from team import Team
                            for fn in os.listdir(full):
                                if fn.startswith("upload_") and fn.endswith(".json"):
                                    fpath = os.path.join(full, fn)
                                    try:
                                        udata = _load_json(fpath, None)
                                        if udata and "team" in udata:
                                            t_obj = Team.from_dict(udata["team"])
                                            t_obj.revert_all_progress()
                                            # Clear history for any turn 1 participation files
                                            t_obj.archived_warriors = []
                                            t_obj.turn_history = []
                                            udata["team"] = t_obj.to_dict()
                                            _save_json(fpath, udata)
                                    except Exception: pass
                                if not fn.startswith("upload_"):
                                    fpath = os.path.join(full, fn)
                                    try:
                                        if os.path.isdir(fpath):
                                            shutil.rmtree(fpath, onerror=lambda func, p, _: (make_file_writable(p), func(p)))
                                        else:
                                            make_file_writable(fpath)
                                            os.remove(fpath)
                                    except Exception: pass
                        else:
                            shutil.rmtree(full, onerror=lambda func, path, _: (make_file_writable(path), func(path)))
                
                # 5. Reset config
                cfg["current_turn"] = 1
                cfg["turn_state"] = "open"
                cfg["fight_counter"] = 0
                cfg["reset_count"] = cfg.get("reset_count", 0) + 1

                # Clear out any stale deletion notifications
                keys_to_del = [k for k in cfg.keys() if k.startswith("deleted_team_")]
                for k in keys_to_del:
                    del cfg[k]

                _save_config(cfg)

                # Clear scout narratives
                scout_narr_path = os.path.join(LEAGUE_DIR, "scout_narratives.json")
                if os.path.exists(scout_narr_path):
                    _save_json(scout_narr_path, {})
                
                _turn_progress = {"running": False, "done": 0, "total": 0, "message": "Progress reset complete"}
            
            self.send_json({"success":True, "message":"All progress reverted to Turn 1 baseline. Accounts and teams preserved.", "clear_local_results": True}); return

        if path == "/api/admin/update":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password","")):
                self.send_json({"success":False,"error":"Not authorised."}, 401); return
            for bool_key in ("show_favorite_weapon", "show_luck_factor",
                             "show_max_hp", "ai_teams_enabled", "schedule_enabled",
                             "github_push_enabled"):
                if bool_key in b:
                    cfg[bool_key] = bool(b[bool_key])
            if "schedule_slots" in b:
                import re as _re
                _valid_days = ("Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday")
                _raw = b["schedule_slots"]
                if isinstance(_raw, list):
                    _clean = []
                    _seen  = set()
                    for _s in _raw:
                        if not isinstance(_s, dict): continue
                        _d = _s.get("day",  "")
                        _t = str(_s.get("time", ""))
                        if _d not in _valid_days: continue
                        if not _re.match(r"^\d{2}:\d{2}$", _t): continue
                        _key = f"{_d}_{_t}"
                        if _key in _seen: continue  # no duplicate day+time
                        _seen.add(_key)
                        # Preserve existing per-slot run history
                        _existing = next(
                            (x for x in cfg.get("schedule_slots", [])
                             if x.get("day") == _d and x.get("time") == _t), {}
                        )
                        _clean.append({
                            "day": _d, "time": _t,
                            "last_run_at":     _existing.get("last_run_at", ""),
                            "last_run_turn":   _existing.get("last_run_turn", 0),
                            "last_run_result": _existing.get("last_run_result", ""),
                        })
                    cfg["schedule_slots"] = _clean
            _save_config(cfg)
            self.send_json({"success":True,"message":"Config updated.","config":cfg}); return

        if path == "/api/admin/unlock":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password","")):
                self.send_json({"success":False,"error":"Not authorised."}, 401); return
            cfg["turn_state"] = "open"
            cfg.pop("processing_started_at", None)  # Clear the stuck turn timestamp
            _save_config(cfg)
            _turn_progress = {"running": False, "done": 0, "total": 0, "message": "Unlocked manually"}
            self.send_json({"success":True,"message":"Turn state reset to OPEN."}); return

        # ==================== LOCAL CLIENT STORAGE ENDPOINTS ====================
        # Used by bloodspire_client.html when running in 'Local Server Mode'

        def _safe_path(rel_path):
            if not rel_path: return None
            # Prevent directory traversal
            clean = os.path.normpath(rel_path).lstrip(os.sep + (os.altsep or ''))
            if clean.startswith('..'): return None
            return os.path.join(BASE_DIR, "saves", "client", clean)

        if path == "/api/local/status":
            # Return the Host header so remote players get the correct server URL,
            # not a hardcoded "localhost" that only works on the server machine.
            host = self.headers.get("Host", f"localhost:{_server_port}")
            self.send_json({
                "success": True,
                "is_local_backend": True,
                "server_url": f"http://{host}",
            }); return

        if path == "/api/local/read":
            q = self.qs()
            fpath = _safe_path(q.get("path"))
            if not fpath or not os.path.exists(fpath):
                self.send_json({"success": False, "error": "File not found"}, 404); return
            try:
                if fpath.endswith(".json"):
                    # load_json_protected returns a dict, not a string - send directly
                    content = load_json_protected(fpath)
                    self.send_json({"success": True, "data": content})
                else:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    self.send_json({"success": True, "text": content})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500); return
            return

        if path == "/api/local/write":
            fpath = _safe_path(b.get("path"))
            if not fpath:
                self.send_json({"success": False, "error": "Invalid path"}, 400); return
            try:
                os.makedirs(os.path.dirname(fpath), exist_ok=True) # Use protected save for JSON, regular for text
                if "data" in b: # Protected
                    save_json_protected(fpath, b["data"])
                else: # Not protected
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(b.get("text", ""))
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500); return
            return

        if path == "/api/local/delete":
            fpath = _safe_path(b.get("path"))
            if fpath and os.path.exists(fpath):
                try: # Also remove checksum file if it exists
                    os.remove(fpath)
                    checksum_fpath = fpath.replace('.json', '.checksum')
                    if os.path.exists(checksum_fpath):
                        os.remove(checksum_fpath)
                except: pass
            self.send_json({"success": True}); return

        if path == "/api/local/list":
            q = self.qs()
            dpath = _safe_path(q.get("path"))
            if not dpath or not os.path.isdir(dpath):
                self.send_json({"success": True, "files": []}); return
            files = [f for f in os.listdir(dpath) if os.path.isfile(os.path.join(dpath, f))]
            self.send_json({"success": True, "files": sorted(files)}); return

        # ==================== RENAME MANAGER ====================
        if path == "/api/admin/rename_manager":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return

            mid      = str(b.get("manager_id") or "").strip()
            new_name = str(b.get("new_name") or "").strip()
            if not mid or not new_name:
                self.send_json({"success": False, "error": "manager_id and new_name required."}); return

            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs:
                    self.send_json({"success": False, "error": "Manager not found."}); return

                old_name = mgrs[mid]["manager_name"]

                # 1. Update managers registry
                mgrs[mid]["manager_name"] = new_name
                _save_managers(mgrs)

                # 2. Update standings
                standings = _load_standings()
                if mid in standings:
                    standings[mid]["manager_name"] = new_name
                    _save_standings(standings)

                # 3. Update team files that belong to this manager
                from save import TEAMS_DIR
                team_ids = mgrs[mid].get("team_ids", [])
                for tid in team_ids:
                    tpath = os.path.join(TEAMS_DIR, f"team_{int(tid):04d}.json")
                    if not os.path.exists(tpath):
                        continue
                    try:
                        tdata = _load_json(tpath, None)
                        if tdata:
                            tdata["manager_name"] = new_name
                            _save_json(tpath, tdata)
                    except Exception as _e:
                        print(f"  WARNING: Could not update team {tid} for rename: {_e}")

                # 4. Update current-turn upload files
                turn_num = cfg["current_turn"]
                td = _turn_dir(turn_num)
                if os.path.exists(td):
                    for fname in os.listdir(td):
                        if fname.startswith(f"upload_{mid}_") and fname.endswith(".json"):
                            fpath = os.path.join(td, fname)
                            try:
                                udata = _load_json(fpath, None)
                                if udata:
                                    udata["manager_name"] = new_name
                                    if isinstance(udata.get("team"), dict):
                                        udata["team"]["manager_name"] = new_name
                                    _save_json(fpath, udata)
                            except Exception as _e:
                                print(f"  WARNING: Could not update upload file {fname}: {_e}")

                # 5. Update scouting selections
                from save import SCOUTING_FILE
                if os.path.exists(SCOUTING_FILE):
                    try:
                        scout_data = _load_json(SCOUTING_FILE, {})
                        if mid in scout_data:
                            scout_data[mid]["manager_name"] = new_name
                            _save_json(SCOUTING_FILE, scout_data)
                    except Exception as _e:
                        print(f"  WARNING: Could not update scouting data for rename: {_e}")

            print(f"  [rename] Manager '{old_name}' (ID: {mid}) renamed to '{new_name}'")
            self.send_json({
                "success": True,
                "message": f"Manager '{old_name}' successfully renamed to '{new_name}'."
            }); return
        # =====================================================

        # ==================== RENAME TEAM ====================
        if path == "/api/admin/rename_team":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return

            tid      = b.get("team_id")
            new_name = str(b.get("new_name") or "").strip().upper()
            if not tid or not new_name:
                self.send_json({"success": False, "error": "team_id and new_name required."}); return
            if len(new_name) > 20:
                self.send_json({"success": False, "error": "Team name must be 20 characters or fewer."}); return

            with _lock:
                from save import load_team, save_team
                try:
                    team = load_team(int(tid))
                    old_name = team.team_name
                    team.team_name = new_name
                    save_team(team)

                    # Update current turn upload file if it exists
                    turn_num = cfg["current_turn"]
                    td = _turn_dir(turn_num)
                    if os.path.exists(td):
                        # Scan for files belonging to this team ID
                        # upload_{mid}_team{tid}.json
                        for fn in os.listdir(td):
                            if fn.startswith("upload_") and (fn.endswith(f"_team{int(tid):04d}.json") or fn.endswith(f"_team{tid}.json")):
                                fpath = os.path.join(td, fn)
                                try:
                                    udata = _load_json(fpath, None)
                                    if udata and isinstance(udata.get("team"), dict):
                                        udata["team"]["team_name"] = new_name
                                        _save_json(fpath, udata)
                                except: pass
                except Exception as e:
                    self.send_json({"success": False, "error": f"Failed to rename team: {e}"}); return

            self.send_json({
                "success": True,
                "message": f"Team '{old_name}' (ID: {tid}) successfully renamed to '{new_name}'."
            }); return
        # =========================================================

        # ==================== DELETE MANAGER (FIXED) ====================
        if path == "/api/admin/delete_manager":
            # Load cfg FIRST so it's defined before the check
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password","")):
                self.send_json({"success":False,"error":"Not authorised."}, 401); return

            mid = str(b.get("manager_id") or "").strip()
            if not mid:
                self.send_json({"success":False,"error":"manager_id required."}); return

            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs:
                    self.send_json({"success":False,"error":"Manager not found."}); return

                manager_name = mgrs[mid]["manager_name"]

                # Delete the manager
                del mgrs[mid] # This will be replaced by save_json_protected
                # Also delete manager's teams from the teams directory
                # This is handled by the client's `Store.deleteTeam`
                _save_managers(mgrs)

                # Clean up current turn files - archive results, delete uploads
                turn_num = cfg["current_turn"]
                td = _turn_dir(turn_num)
                if os.path.exists(td):
                    for fname in list(os.listdir(td)):
                        if fname.startswith(f"upload_{mid}_") or fname.startswith(f"result_{mid}_"):
                            fpath = os.path.join(td, fname)
                            # Archive result files (CRITICAL: preserve for auditing)
                            # Delete upload files (safe - these are working files)
                            _safe_delete_file(fpath, archive_to_turn=turn_num)

            self.send_json({
                "success": True,
                "message": f"Manager '{manager_name}' (ID: {mid}) has been successfully deleted. They can now re-register."
            })
            return
        # ============================================================

        if path == "/api/admin/set_debug_team":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return
            mid = str(b.get("manager_id") or "").strip()
            mname = ""
            if mid:
                managers = _load_managers()
                if mid not in managers:
                    self.send_json({"success": False, "error": "Manager not found."}); return
                mname = managers[mid]["manager_name"]
            cfg["admin_debug_manager_id"] = mid
            _save_config(cfg)
            self.send_json({"success": True, "manager_name": mname}); return

        if path == "/api/admin/validate_teams":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return

            from save import TEAMS_DIR
            teams_data = []
            try:
                if os.path.exists(TEAMS_DIR):
                    for fn in sorted(os.listdir(TEAMS_DIR)):
                        if fn.startswith("team_") and fn.endswith(".json"):
                            fpath = os.path.join(TEAMS_DIR, fn)
                            tdata = load_json_protected(fpath)
                            raw_warriors = tdata.get("warriors", [])
                            warrior_names = []
                            for w in raw_warriors:
                                if w and isinstance(w, dict):
                                    warrior_names.append(w.get("name", "Unnamed"))
                                else:
                                    warrior_names.append("[None]")
                            
                            teams_data.append({
                                "team_id": tdata.get("team_id", "?"),
                                "team_name": tdata.get("team_name", "Unknown"),
                                "manager_name": tdata.get("manager_name", "Unknown"),
                                "warrior_count": len(raw_warriors),
                                "warriors": warrior_names,
                                "is_valid": len(raw_warriors) == 5
                            })
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}); return

            self.send_json({"success": True, "teams": teams_data}); return

        if path == "/api/admin/validate_warrior_ids":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return

            from save import TEAMS_DIR
            from collections import defaultdict
            all_warriors = []
            id_owners = defaultdict(list)
            total_teams = 0
            try:
                if os.path.exists(TEAMS_DIR):
                    for fn in sorted(os.listdir(TEAMS_DIR)):
                        if not (fn.startswith("team_") and fn.endswith(".json")):
                            continue
                        fpath = os.path.join(TEAMS_DIR, fn)
                        tdata = load_json_protected(fpath)
                        team_id = tdata.get("team_id", "?")
                        team_name = tdata.get("team_name", "Unknown")
                        manager_name = tdata.get("manager_name", "Unknown")
                        total_teams += 1

                        for slot, wlist in (("active", tdata.get("warriors", [])),
                                            ("archived", tdata.get("archived_warriors", []))):
                            for w in (wlist or []):
                                if not w or not isinstance(w, dict):
                                    continue
                                wname = w.get("name", "Unnamed")
                                wid = w.get("warrior_id")
                                entry = {
                                    "team_id": team_id, "team_name": team_name,
                                    "manager_name": manager_name,
                                    "warrior_name": wname, "slot": slot,
                                    "warrior_id": wid
                                }
                                all_warriors.append(entry)
                                if wid:
                                    id_owners[wid].append(entry)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}); return

            duplicate_ids = {wid for wid, owners in id_owners.items() if len(owners) > 1}
            for entry in all_warriors:
                if not entry["warrior_id"]:
                    entry["status"] = "missing"
                elif entry["warrior_id"] in duplicate_ids:
                    entry["status"] = "duplicate"
                else:
                    entry["status"] = "ok"

            all_warriors.sort(key=lambda e: (e["team_id"] if isinstance(e["team_id"], int) else 0, e["slot"], e["warrior_name"]))
            missing_count = sum(1 for e in all_warriors if e["status"] == "missing")

            self.send_json({
                "success": True,
                "total_teams": total_teams,
                "total_warriors": len(all_warriors),
                "warriors": all_warriors,
                "missing_count": missing_count,
                "duplicate_count": len(duplicate_ids)
            }); return

        if path == "/api/admin/download_manager_files":
            import zipfile
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return

            mid = str(b.get("manager_id") or "").strip()
            if not mid:
                self.send_json({"success": False, "error": "manager_id required."}); return

            managers = _load_managers()
            if mid not in managers:
                self.send_json({"success": False, "error": "Manager not found."}); return

            mname = managers[mid]["manager_name"]

            # Create ZIP with all manager's files in proper directory structure
            from io import BytesIO
            zip_buffer = BytesIO()
            manifest = []  # Track files and their target locations

            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                # Add all team files for this manager
                mgr_teams = set(int(t) for t in managers[mid].get("team_ids", []) if isinstance(t,(int,str)) and str(t).isdigit())
                from save import TEAMS_DIR
                for team_id in mgr_teams:
                    team_file = os.path.join(TEAMS_DIR, f"team_{int(team_id):04d}.json")
                    if os.path.exists(team_file):
                        # Store in teams/ subdirectory in ZIP
                        arcname = f"teams/team_{int(team_id):04d}.json"
                        zf.write(team_file, arcname=arcname)
                        manifest.append({
                            "source": arcname,
                            "target": f"teams/team_{int(team_id):04d}.json",
                            "type": "team"
                        })

                # Add all result files and newsletters for this manager across all turns
                league_dir = os.path.dirname(_config_path())
                for fname in os.listdir(league_dir):
                    if fname.startswith("turn_") and os.path.isdir(os.path.join(league_dir, fname)):
                        turn_path = os.path.join(league_dir, fname)
                        turn_num = int(fname.split("_")[1])
                        for result_file in os.listdir(turn_path):
                            if result_file.startswith(f"result_{mid}_") and result_file.endswith(".json"):
                                full_path = os.path.join(turn_path, result_file)
                                # Store in league structure in ZIP
                                arcname = f"league/{fname}/{result_file}"
                                zf.write(full_path, arcname=arcname)
                                manifest.append({
                                    "source": arcname,
                                    "target": f"league/{fname}/{result_file}",
                                    "type": "result",
                                    "turn": turn_num
                                })
                        # Include newsletter for this turn if it exists
                        nl_file = os.path.join(turn_path, "newsletter.txt")
                        if os.path.exists(nl_file):
                            arcname = f"newsletters/turn_{turn_num:03d}.txt"
                            zf.write(nl_file, arcname=arcname)
                            manifest.append({
                                "source": arcname,
                                "target": f"newsletters/turn_{turn_num:03d}.txt",
                                "type": "newsletter",
                                "turn": turn_num
                            })

                # Add manifest file
                manifest_json = json.dumps(manifest, indent=2)
                zf.writestr("MANIFEST.json", manifest_json)

                # Add README with instructions
                readme = f"""BLOODSPIRE Restore Package
Manager: {mname} (ID: {mid})
Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}

CONTENTS:
- teams/: Team data files
- league/: Turn results organized by turn number
- MANIFEST.json: File location mapping

TO RESTORE:
1. Download this ZIP file
2. In the BLOODSPIRE client, go to Preferences → Reset Save Folder
3. Select your save folder location
4. Go to Preferences → Restore from ZIP
5. Select this ZIP file
6. Files will be automatically extracted to the correct locations

Or manually:
- Extract teams/*.json to your save folder's teams/ directory
- Extract league/turn_*/result_*.json to your save folder's league/turn_*/ directory
"""
                zf.writestr("README.txt", readme)

            zip_buffer.seek(0)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            filename = f"manager_{mid}_files.zip"
            self.send_header("Content-Disposition", f"attachment; filename={filename}")
            self.send_header("Content-Length", len(zip_buffer.getvalue()))
            self.end_headers()
            self.wfile.write(zip_buffer.getvalue())
            return

        if path == "/api/admin/activity_log":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return

            # Get query parameters for filtering
            q = self.qs()
            limit = int(q.get("limit", "100"))
            action_filter = q.get("action", "")  # e.g., "upload", "download"
            manager_filter = q.get("manager_id", "")  # filter by manager ID

            try:
                log_file = os.path.join(LEAGUE_DIR, "activity_logs", "activity.jsonl")
                entries = []
                if os.path.exists(log_file):
                    with open(log_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            try:
                                entry = json.loads(line.strip())
                                # Apply filters
                                if action_filter and action_filter not in entry.get("action", ""):
                                    continue
                                if manager_filter and manager_filter != entry.get("manager_id", ""):
                                    continue
                                entries.append(entry)
                            except json.JSONDecodeError:
                                continue
                    # Return last N entries (most recent first)
                    entries = entries[-limit:]
                    entries.reverse()

                self.send_json({"success": True, "entries": entries, "total": len(entries)}); return
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}); return

        if path == "/api/admin/warriors_report":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return

            try:
                from save import load_all_teams
                teams = load_all_teams()
                warriors = []

                for team in teams:
                    team_id = team.team_id
                    team_name = team.team_name
                    manager_name = team.manager_name

                    for slot_idx, warrior in enumerate(team.warriors):
                        if warrior is None:
                            continue
                        warriors.append({
                            "warrior_name": warrior.name,
                            "team_id": team_id,
                            "team_name": team_name,
                            "manager_name": manager_name,
                            "slot_index": slot_idx,
                            "wins": warrior.wins,
                            "losses": warrior.losses,
                            "kills": warrior.kills,
                            "total_fights": warrior.total_fights,
                            "is_dead": warrior.is_dead,
                            "is_retired": warrior.is_retired,
                        })

                warriors.sort(key=lambda x: (x["team_id"], x["slot_index"]))
                self.send_json({"success": True, "warriors": warriors, "total": len(warriors)}); return
            except Exception as e:
                import traceback; traceback.print_exc()
                self.send_json({"success": False, "error": str(e)}); return

        if path == "/api/admin/delete_team":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return

            try:
                team_id = int(b.get("team_id", 0))
                if not team_id:
                    self.send_json({"success": False, "error": "team_id required"}); return

                from save import load_team, delete_team
                team = load_team(team_id)
                manager_id = None
                managers_dict = _load_managers()

                # Find which manager owns this team (type-insensitive)
                for mid, mgr_data in managers_dict.items():
                    tids = mgr_data.get("team_ids", [])
                    if any(str(t) == str(team_id) for t in tids):
                        manager_id = mid
                        break

                # FALLBACK: If not in registry, re-sync by loading the team file itself
                if not manager_id:
                    try:
                        from save import load_team
                        team_temp = load_team(team_id)
                        target_mgr_name = team_temp.manager_name
                        for mid, mgr_data in managers_dict.items():
                            if mgr_data.get("manager_name") == target_mgr_name:
                                manager_id = mid
                                # Update registry to prevent future errors
                                tids = mgr_data.setdefault("team_ids", [])
                                if int(team_id) not in [int(x) for x in tids if str(x).isdigit()]:
                                    tids.append(int(team_id))
                                break
                    except Exception as fallback_err:
                        print(f"  Fallback registry re-sync failed: {fallback_err}")

                if not manager_id:
                    self.send_json({"success": False, "error": "Could not find manager for this team"}); return

                # Record the deletion for user notification
                deletion_key = f"deleted_team_{team_id}"
                cfg[deletion_key] = {
                    "deleted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "team_name": team.team_name,
                    "team_id": team_id,
                    "manager_id": manager_id
                }
                _save_config(cfg)

                # Remove team from manager's team_ids list
                mgr = managers_dict[manager_id]
                if "team_ids" in mgr:
                    mgr["team_ids"] = [tid for tid in mgr["team_ids"] if str(tid) != str(team_id)]
                _save_managers(managers_dict)

                # Clean up any current turn upload or result files for this team
                turn_num = cfg["current_turn"]
                td = _turn_dir(turn_num)
                if os.path.exists(td):
                    for fn in os.listdir(td):
                        is_upload = fn.startswith(f"upload_{manager_id}")
                        is_result = fn.startswith(f"result_{manager_id}")
                        if (is_upload or is_result) and fn.endswith(".json"):
                            if "_team" in fn:
                                try:
                                    tid_str = fn.split("_team")[-1].split(".")[0]
                                    if int(tid_str) != team_id: continue
                                except: continue
                            fpath = os.path.join(td, fn)
                            try:
                                make_file_writable(fpath)
                                os.remove(fpath)
                                cf = fpath.replace(".json", ".checksum")
                                if os.path.exists(cf):
                                    make_file_writable(cf); os.remove(cf)
                            except: pass

                # Delete the team files
                delete_team(team_id)

                self.send_json({"success": True, "message": f"Team '{team.team_name}' deleted. Manager will be notified on next login."}); return
            except Exception as e:
                import traceback; traceback.print_exc()
                self.send_json({"success": False, "error": str(e)}); return

        if path == "/api/admin/uploaded_warriors":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return

            try:
                turn = cfg.get("current_turn", 1)
                uploads = _load_uploads(turn)
                managers_dict = _load_managers()
                warriors_by_manager = {}

                for upload_key, upload_data in uploads.items():
                    team_data = upload_data.get("team", {})
                    manager_id = str(upload_data.get("manager_id", ""))
                    team_id = team_data.get("team_id", "")
                    team_name = team_data.get("team_name", "Unknown")
                    manager_info = managers_dict.get(manager_id, {})
                    manager_name = manager_info.get("manager_name", f"Manager {manager_id}")

                    if manager_name not in warriors_by_manager:
                        warriors_by_manager[manager_name] = {
                            "manager_id": manager_id,
                            "teams": [],
                            "warriors": []
                        }

                    warriors = team_data.get("warriors", [])
                    for slot_idx, warrior_data in enumerate(warriors):
                        if not warrior_data:
                            continue
                        warriors_by_manager[manager_name]["warriors"].append({
                            "warrior_name": warrior_data.get("name", "Unknown"),
                            "team_id": team_id,
                            "team_name": team_name,
                            "manager_name": manager_name,
                            "manager_id": manager_id,
                            "slot_index": slot_idx,
                            "wins": warrior_data.get("wins", 0),
                            "losses": warrior_data.get("losses", 0),
                            "kills": warrior_data.get("kills", 0),
                            "total_fights": warrior_data.get("total_fights", 0),
                            "is_dead": warrior_data.get("is_dead", False),
                            "is_retired": warrior_data.get("is_retired", False),
                            "uploaded_at": upload_data.get("uploaded_at", "Unknown"),
                        })

                    if team_name not in warriors_by_manager[manager_name]["teams"]:
                        warriors_by_manager[manager_name]["teams"].append(team_name)

                self.send_json({"success": True, "managers": warriors_by_manager, "total_managers": len(warriors_by_manager)}); return
            except Exception as e:
                import traceback; traceback.print_exc()
                self.send_json({"success": False, "error": str(e)}); return

        if path == "/api/admin/regenerate_roster":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return

            try:
                from team_roster import generate_team_roster_html, write_team_roster
                from save import load_all_teams

                # Load all teams and build team_map keyed by manager+team combo
                teams = load_all_teams()
                team_map = {}
                for team in teams:
                    # Create a simple key like "manager_id_team_id"
                    key = f"{team.manager_name}_{team.team_id}"
                    team_map[key] = team

                # Load current uploads data for the team_map lookup
                turn_num = cfg.get("current_turn", 1)
                uploads = _load_uploads(turn_num)

                # Generate the roster HTML
                roster_html = generate_team_roster_html(uploads, team_map, turn_num)

                # Write and push to GitHub
                reports_dir = os.path.join(LEAGUE_DIR, "reports")
                write_team_roster(roster_html, reports_dir)

                self.send_json({"success": True, "message": f"Team roster regenerated and pushed for Turn {turn_num}"}); return
            except Exception as e:
                import traceback; traceback.print_exc()
                self.send_json({"success": False, "error": str(e)}); return

        if path == "/api/admin/regenerate_arena_stats":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return

            try:
                from arena_stats import generate_arena_stats
                from save import load_all_teams

                # Load all teams and build team_map keyed by manager+team combo
                teams = load_all_teams()
                team_map = {}
                for team in teams:
                    key = f"{team.manager_name}_{team.team_id}"
                    team_map[key] = team

                turn_num = cfg.get("current_turn", 1)
                uploads = _load_uploads(turn_num)

                reports_dir = os.path.join(LEAGUE_DIR, "reports")
                generate_arena_stats(uploads, team_map, turn_num, reports_dir)

                self.send_json({"success": True, "message": f"Arena stats regenerated and pushed for Turn {turn_num}"}); return
            except Exception as e:
                import traceback; traceback.print_exc()
                self.send_json({"success": False, "error": str(e)}); return

        if path == "/api/check_deleted_teams":
            manager_id = b.get("manager_id", "")
            if not manager_id:
                self.send_json({"success": False, "error": "manager_id required"}); return

            try:
                cfg = _load_config()
                deleted_teams = []

                # Check all deleted_team_* entries in config
                for key in cfg.keys():
                    if key.startswith("deleted_team_"):
                        deletion_info = cfg[key]
                        if deletion_info.get("manager_id") == manager_id:
                            deleted_teams.append(deletion_info)

                self.send_json({"success": True, "deleted_teams": deleted_teams}); return
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}); return

        if path == "/api/shutdown":
            self.send_json({"success": True, "message": "Shutting down..."})
            threading.Timer(0.5, self._shutdown_server).start()
            return

        self.send_json({"error":"Not found."}, 404)

# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="BLOODSPIRE League Server")
    parser.add_argument("--host-password", required=True,
                        help="Password for host admin access and running turns")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    global _server_port
    _server_port = args.port

    _ensure_dirs()

    # One-time migration: assign warrior_ids to existing warriors that predate this feature
    try:
        from save import migrate_warrior_ids
        _migrated = migrate_warrior_ids()
        if _migrated:
            print(f"  [startup] Assigned warrior IDs to {_migrated} existing warrior(s).")
    except Exception as _me:
        print(f"  WARNING: warrior ID migration failed: {_me}")

    cfg  = _load_config()
    salt = cfg.get("host_password_salt") or secrets.token_hex(16)
    cfg["host_password_salt"] = salt
    cfg["host_password_hash"] = _hash_pw(args.host_password, salt)
    _save_config(cfg)

    # Use a threading server so GET requests (results, status, etc.) are handled
    # concurrently while a turn is running - prevents 10053 socket abort on Windows
    class ThreadedLeagueServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True   # threads die with the server process

        def handle_error(self, request, client_address):
            import sys
            exc = sys.exc_info()[1]
            if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
                return  # client dropped the connection - harmless, suppress noise
            super().handle_error(request, client_address)

    server = ThreadedLeagueServer(("0.0.0.0", args.port), LeagueHandler)
    _global_server = server
    url    = f"http://localhost:{args.port}"

    # ── One-time migration: seed arena-specific team folders ─────────────────
    # If saves/{arena}/teams/ is empty but the main saves/teams/ files have warriors
    # with current_arena=elite/veteran, copy them over so the new isolated pipeline
    # works immediately without any manual data migration.
    _migrate_immortal_teams_once()

    print()
    print("  +============================================+")
    print(f"  | THE AGONY AMPHITHEATRE SERVER v{SERVER_VERSION:<10} |")
    print("  +============================================+")
    print(f"\n  Admin panel :  {url}/admin")
    print(f"  Player URL  :  http://YOUR_LAN_IP:{args.port}")
    print(f"  Current turn:  {cfg['current_turn']}")
    print(f"\n  !  Share your LAN/public IP, not 'localhost', with other players.")
    print(f"  !  Forward port {args.port} on your router for internet play.\n")

    threading.Timer(0.8, lambda: webbrowser.open(f"{url}/admin")).start()

    # ── Auto-scheduler threads ────────────────────────────────────────────
    # One thread per arena, each polling every 30 s for a matching slot.
    _DAYS = ("Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday")

    def _immortal_scheduler(arena: str, password: str):
        """Poll-based auto-scheduler for elite and veteran arenas.

        Reads scheduler config from saves/{arena}/config.json every 30 s.
        When a matching day+time slot is found the turn is fired in its own
        daemon thread, exactly mirroring the normal-arena scheduler pattern.
        """
        import datetime as _dt
        _arena_cfg_path = os.path.join(BASE_DIR, "saves", arena, "config.json")
        _fired          = set()  # "YYYY-MM-DD HH:MM" strings fired this session
        _tag            = f"{arena}-scheduler"
        while True:
            time.sleep(30)
            try:
                if not os.path.exists(_arena_cfg_path):
                    continue
                with open(_arena_cfg_path, encoding="utf-8") as _f:
                    _acfg = json.load(_f)
                _sched = _acfg.get("scheduler", {})
                if not _sched.get("enabled", False):
                    continue
                if _acfg.get("turn_state") == "processing":
                    continue
                _slots   = _sched.get("schedule_slots", [])
                _now     = _dt.datetime.now()
                _cur_day = _now.strftime("%A")
                _cur_t   = _now.strftime("%H:%M")
                _cur_min = _now.strftime("%Y-%m-%d %H:%M")
                _cur_n   = _acfg.get("turn_counter", 0) + 1
                for _i, _slot in enumerate(_slots):
                    if _slot.get("day")  != _cur_day: continue
                    if _slot.get("time") != _cur_t:   continue
                    if _cur_min in _fired:             continue
                    if _slot.get("last_run_at", "")[:16] == _cur_min: continue
                    print(f"\n  [{_tag}] Auto-running turn {_cur_n} "
                          f"(slot {_i+1}: {_cur_day} {_cur_t})")
                    _slot["last_run_at"]     = _now.strftime("%Y-%m-%d %H:%M:%S")
                    _slot["last_run_turn"]   = _cur_n
                    _slot["last_run_result"] = f"Auto-run started on {_cur_day} at {_cur_t}"
                    _acfg["scheduler"] = _sched
                    with open(_arena_cfg_path, "w", encoding="utf-8") as _f:
                        json.dump(_acfg, _f, indent=2)
                    _fired.add(_cur_min)
                    threading.Thread(
                        target=_run_immortal_turn,
                        args=(arena, password),
                        daemon=True,
                    ).start()
                    break  # one turn per poll cycle
            except Exception as _se:
                print(f"  [{_tag}] Error: {_se}")

    def _scheduler():
        import datetime as _dt
        _fired_minutes = set()  # "YYYY-MM-DD HH:MM" strings fired this session
        while True:
            time.sleep(30)
            try:
                cfg = _load_config()
                if not cfg.get("schedule_enabled", False):
                    continue
                if cfg.get("turn_state") in ("processing",):
                    continue  # already running
                slots    = cfg.get("schedule_slots", [])
                now      = _dt.datetime.now()
                cur_day  = now.strftime("%A")
                cur_time = now.strftime("%H:%M")
                cur_min  = now.strftime("%Y-%m-%d %H:%M")
                cur_turn = cfg.get("current_turn", 1)
                for i, slot in enumerate(slots):
                    if slot.get("day") != cur_day:
                        continue
                    if slot.get("time") != cur_time:
                        continue
                    if cur_min in _fired_minutes:
                        continue  # already fired this minute (in-memory guard)
                    if slot.get("last_run_at", "")[:16] == cur_min:
                        continue  # persistent guard: already recorded in config
                    print(f"\n  [scheduler] Auto-running turn {cur_turn} "
                          f"(slot {i+1}: {cur_day} {cur_time})")
                    slot["last_run_at"]     = now.strftime("%Y-%m-%d %H:%M:%S")
                    slot["last_run_turn"]   = cur_turn
                    slot["last_run_result"] = f"Auto-run started on {cur_day} at {cur_time}"
                    cfg["schedule_last_run_at"]     = slot["last_run_at"]
                    cfg["schedule_last_run_turn"]   = cur_turn
                    cfg["schedule_last_run_result"] = slot["last_run_result"]
                    _save_config(cfg)
                    _fired_minutes.add(cur_min)
                    threading.Thread(
                        target=_run_turn,
                        args=(args.host_password,),
                        daemon=True,
                    ).start()
                    break  # one turn per check - don't fire two slots at once
            except Exception as _se:
                print(f"  [scheduler] Error: {_se}")

    threading.Thread(target=_scheduler, daemon=True, name="bp-scheduler").start()
    threading.Thread(target=_immortal_scheduler, args=("elite",   args.host_password),
                     daemon=True, name="bp-elite-scheduler").start()
    threading.Thread(target=_immortal_scheduler, args=("veteran", args.host_password),
                     daemon=True, name="bp-veteran-scheduler").start()
    # ──────────────────────────────────────────────────────────────────────

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  League server stopped.")

if __name__ == "__main__":
    main()
