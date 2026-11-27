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

SERVER_VERSION = "4.0.0"

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
LEAGUE_DIR   = os.path.join(BASE_DIR, "saves", "league")
DEFAULT_PORT = 8766
sys.path.insert(0, BASE_DIR)

_lock          = threading.Lock()
_turn_progress = {"running": False, "done": 0, "total": 0, "message": ""}

# Download lock, per arena ("normal", "elite", "veteran") -> the turn number being processed.
# Set when a turn really starts running and cleared only when the turn function has completely
# finished (the "Turn N complete" console lines), so a player can never download half-written
# results or a half-written newsletter. In memory only: a restart clears it, and a crash clears
# it through the try/finally in _run_turn / _run_immortal_turn.
_processing_arenas = {}


def _lock_downloads(arena, turn):
    _processing_arenas[arena] = turn


def _unlock_downloads(arena):
    _processing_arenas.pop(arena, None)


def _processing_block(handler, arena, turn=None):
    """If this arena's turn is still being processed, tell the client and return True.
    With `turn` given, only that turn (or a later one) is blocked; older finished turns stay available."""
    locked = _processing_arenas.get(arena)
    if locked is None:
        return False
    if turn is not None and turn < locked:
        return False
    handler.send_json({"success": False, "processing": True,
                       "error": f"Turn {locked} is still being processed. Please try again in a few minutes."})
    return True
_global_server = None  # Reference for graceful shutdown from request handlers
_server_port   = DEFAULT_PORT  # Set by main() once args are parsed


# =============================================================================
# STORAGE HELPERS
# =============================================================================

def _ensure_dirs():
    os.makedirs(LEAGUE_DIR, exist_ok=True)
    os.makedirs(os.path.join(LEAGUE_DIR, "activity_logs"), exist_ok=True)

def _roll_registry():
    """The stat-roll registry, pointed at this server's saves folder."""
    import roll_registry
    roll_registry.configure(os.path.join(BASE_DIR, "saves"))
    return roll_registry

def _load_team_file_dict(team_id):
    """Raw dict of a team's saved file in the normal arena, or None."""
    from save import _team_filepath as _tfp
    try:
        path = _tfp(int(team_id))
    except (TypeError, ValueError):
        return None
    if not os.path.exists(path):
        return None
    try:
        return load_json_protected(path, allow_tampered=True)
    except Exception:
        return None

_PROXY_HEADERS = ("X-Forwarded-For", "X-Forwarded-Host", "X-Real-IP", "Forwarded",
                  "CF-Connecting-IP", "CF-Ray", "True-Client-IP")

def _is_server_machine(handler):
    """True only for a request made from the machine running the server itself.
    A tunnel or reverse proxy on the same machine (e.g. Cloudflare) makes every
    outside request arrive from 127.0.0.1, so any proxy header disqualifies it."""
    if handler.client_address[0] not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return False
    return not any(handler.headers.get(h) for h in _PROXY_HEADERS)

def _confined_path(rel_path, root, within=None):
    """Resolve rel_path under `root`, refusing anything that escapes it (.., absolute
    paths, drive letters, symlinks). With `within`, the result must also lie inside
    that folder. Returns the full path, or None."""
    if not rel_path or not isinstance(rel_path, str) or "\0" in rel_path:
        return None
    root_real = os.path.realpath(root)
    full = os.path.realpath(os.path.join(root_real, rel_path))
    limit = os.path.realpath(within) if within else root_real
    try:
        if os.path.commonpath([full, root_real]) != root_real:
            return None
        if os.path.commonpath([full, limit]) != limit:
            return None
    except ValueError:      # different drives
        return None
    return full

def _authorize_team_owner(b, team_id, arena=None):
    """Check the request's manager_id/password and that the team is theirs.
    Returns (True, manager_name, 200) or (False, error_message, http_status).

    A team is theirs if its id is in the manager's team_ids or immortal_team_ids.
    For Spire (elite/veteran) requests, pass `arena`: a team that was replaced in the
    normal arena is withdrawn from team_ids while its warriors live on in a Spire, so
    ownership there is also accepted when the arena's own copy of the team names this
    manager. The password check always applies."""
    mid = str(b.get("manager_id") or "").strip()
    pw  = str(b.get("password")   or "").strip()
    with _lock:
        mgrs = _load_managers()
        if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
            return False, "Not authorised.", 401
        owned = [str(t) for t in (mgrs[mid].get("team_ids") or [])] + \
                [str(t) for t in (mgrs[mid].get("immortal_team_ids") or [])]
        if str(team_id) in owned:
            return True, mgrs[mid]["manager_name"], 200
        if arena in ("elite", "veteran"):
            my_name = str(mgrs[mid].get("manager_name") or "").strip().lower()
            for _t in _load_immortal_teams(arena):
                try:
                    if int(_t.get("team_id", 0)) != int(team_id):
                        continue
                except (TypeError, ValueError):
                    continue
                if my_name and str(_t.get("manager_name") or "").strip().lower() == my_name:
                    return True, mgrs[mid]["manager_name"], 200
        return False, "Team not found for this manager.", 403

# Version gate. Clients must report a version at least MIN_CLIENT_VERSION to log in,
# upload, download results or roll up warriors. Both values can be overridden in
# saves/league/config.json ("min_client_version", "client_download_url"), and the gate
# can be switched off with "enforce_client_version": false.
MIN_CLIENT_VERSION = "3.7.0"
CLIENT_DOWNLOAD_URL = "https://mega.nz/file/t6AnGLxA#GPM1LGLDSZGgZ8u3uLVgRU855i0Py_JyANxAMHYEONs"

def _parse_version(v):
    """'3.7.0' / 'v3.7' -> (3, 7, 0); None if there is no usable version."""
    import re as _re
    parts = _re.findall(r"\d+", str(v or ""))[:3]
    if not parts:
        return None
    return tuple(int(x) for x in parts) + (0,) * (3 - len(parts))

def _outdated_message(their_version=None, html=False):
    """Refusal text for an out-of-date client.
    html=True is only for the results download dialog, which shows the text as HTML
    (so it can carry a clickable link). Everywhere else old clients show plain text, so
    the message is kept short and points at the Update Required pop-up they get at login
    (a long URL would just be cut off in those small boxes)."""
    try:
        cfg = _load_config()
    except Exception:
        cfg = {}
    need = str(cfg.get("min_client_version") or MIN_CLIENT_VERSION).lstrip("vV")
    url  = str(cfg.get("client_download_url") or CLIENT_DOWNLOAD_URL)
    mine = f"version {str(their_version).lstrip('vV')}" if _parse_version(their_version) else "an older version"
    if html:
        import html as _h
        return (f"Your Bloodspire client is out of date ({mine}). The current version is {need} "
                f"and you must update to continue playing.<br><br>"
                f"<a href=\"{_h.escape(url, quote=True)}\" target=\"_blank\" "
                f"style=\"color:var(--text-info);font-weight:bold;text-decoration:underline;\">"
                f"Click here to download the update</a><br><br>"
                f"Close Bloodspire, run the installer, then open the game again.")
    return (f"Update required: your Bloodspire is out of date ({mine}); the current version is {need}. "
            f"Log out and log back in (or close and reopen Bloodspire) - an 'Update Required' window with the download link will appear.")

OUTDATED_CLIENT_MSG = "Your Bloodspire client is out of date. Download the latest installer and install it."  # legacy; see _outdated_message()

def _update_announcement(client_version):
    """Pop-up announcement telling an out-of-date client to download the new installer,
    or None when the client is current / the gate is off. The id changes on every call so
    pressing OK doesn't hide it for good - it comes back until the client is updated."""
    cfg = _load_config()
    if not cfg.get("enforce_client_version", True):
        return None
    need_s = str(cfg.get("min_client_version") or MIN_CLIENT_VERSION)
    need, have = _parse_version(need_s), _parse_version(client_version)
    if have is not None and need is not None and have >= need:
        return None
    mine = f"version {str(client_version).lstrip('vV')}" if have else "an older version"
    return {
        "id": f"update_required_{int(time.time())}",
        "title": "Update Required",
        "message": (f"You are running {mine} of Bloodspire. The current version is {need_s.lstrip('vV')}.\n\n"
                    f"You must install the new version to log in, upload your team and download results. "
                    f"Click the link below to download the installer, close Bloodspire, run it, then open the game again."),
        "url": str(cfg.get("client_download_url") or CLIENT_DOWNLOAD_URL),
        "active": True, "created_at": time.time(), "expires_at": None,
    }

_VERSION_GATED_POST = {
    "/api/register", "/api/upload", "/api/team/get_my_team", "/api/team/create",
    "/api/rollup", "/api/rollup_single", "/api/warrior/replace", "/api/immortal_upload",
}
_VERSION_GATED_GET = {"/api/results"}

def _client_version_blocked(handler, path, version):
    """True (after sending a 426 with the update message) if this client is too old."""
    if getattr(handler, "_body_malformed", False):
        # The request body was unreadable, so no client_version could be read. That says
        # nothing about the client's age: report the real problem instead of "update".
        handler.send_json({
            "success": False, "code": "unreadable_body",
            "error": ("The server could not read your upload (the data was damaged in transit or in "
                      "your local save file). Nothing was changed. Please try again; if it keeps "
                      "failing, use Actions > Resync Teams from Server, then upload again."),
        }, 400)
        return True
    try:
        cfg = _load_config()
    except Exception:
        return False
    if not cfg.get("enforce_client_version", True):
        return False
    need = _parse_version(cfg.get("min_client_version") or MIN_CLIENT_VERSION)
    have = _parse_version(version)
    if have is not None and need is not None and have >= need:
        return False
    _note_outdated_request(path, {"client_version": version})
    handler.send_json({
        "success": False, "outdated_client": True,
        "required_version": str(cfg.get("min_client_version") or MIN_CLIENT_VERSION),
        "download_url": str(cfg.get("client_download_url") or CLIENT_DOWNLOAD_URL),
        "error": _outdated_message(version, html=(path == "/api/results")),
    }, 426)
    return True

def _note_outdated_request(path, b):
    """Console line for the host: an old client hit something it can no longer do."""
    try:
        print(f"  [CLIENT] out-of-date client request to {path} "
              f"(client_version={b.get('client_version') or 'none/older than 3.7.0'})")
    except Exception:
        pass

def _record_client_version(mid, manager_name, b):
    """Remember which client version each manager last uploaded with, so the host can
    see who is still on an old client. Best-effort; never blocks an upload."""
    try:
        import datetime as _dtc
        path = os.path.join(LEAGUE_DIR, "client_versions.json")
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data[str(mid)] = {
            "manager_name": manager_name,
            "client_version": str(b.get("client_version") or "older than 3.7.0"),
            "last_upload": _dtc.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def _check_new_warrior(wd, find_roll, rr):
    """Validate a warrior a client wants created (new team or replacement).

    `find_roll(roll_id)` returns the roll record the server issued, or None.
    Returns (True, cleaned_dict) or (False, error_message). The starting stats
    come only from the issued roll plus a legal spend of the rollup points; the
    client's own totals are checked against that, never trusted.
    """
    from upload_guard import build_lookups
    from races import list_playable_races
    if not isinstance(wd, dict):
        return False, "Malformed warrior."
    name = " ".join(str(wd.get("name") or "").split()).upper()
    if not name:
        return False, "All warriors must have a name."
    if len(name) > 25:
        return False, f"Warrior name '{name[:25]}...' is too long (25 characters max)."
    race = wd.get("race")
    if race not in list_playable_races():
        return False, f"'{race}' is not a playable race."
    gender = wd.get("gender")
    if gender not in ("Male", "Female"):
        return False, "Gender must be Male or Female."
    if not wd.get("roll_id"):
        return False, _outdated_message()   # an older client rolls stats itself and sends no roll id
    roll = find_roll(wd.get("roll_id"))
    if not roll:
        return False, ("This stat roll was not issued by the server or has already been "
                       "used. Go back and roll up again.")
    try:
        stats = rr.final_stats(roll["base"], wd)
    except ValueError as e:
        return False, f"Invalid stats for {name}: {e}"
    lk = build_lookups()
    armor = wd.get("armor") if wd.get("armor") in lk["armor"] else "None"
    helm = wd.get("helm") if wd.get("helm") in lk["helm"] else "None"
    primary = wd.get("primary_weapon") if wd.get("primary_weapon") in lk["weapons"] else "Open Hand"
    secondary = wd.get("secondary_weapon") if wd.get("secondary_weapon") in lk["weapons"] else "Open Hand"
    backup = wd.get("backup_weapon") if wd.get("backup_weapon") in lk["weapons"] else None
    return True, {"name": name, "race": race, "gender": gender, "stats": stats,
                  "armor": armor, "helm": helm, "primary_weapon": primary,
                  "secondary_weapon": secondary, "backup_weapon": backup}

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
def _announcements_path(): return os.path.join(LEAGUE_DIR, "announcements.json")

def _load_announcements():
    """Load announcements from file, return empty list if not found."""
    data = _load_json(_announcements_path(), {"announcements": []}, protected=False)
    return data.get("announcements", [])

def _save_announcements(announcements):
    """Save announcements to file."""
    _save_json(_announcements_path(), {"announcements": announcements}, protected=False)

def _get_active_announcements():
    """Return only active, non-expired announcements."""
    announcements = _load_announcements()
    active = []
    current_time = time.time()
    for ann in announcements:
        # Check if active
        if not ann.get("active", True):
            continue
        # Check if not expired
        expires = ann.get("expires_at")
        if expires and current_time > expires:
            continue
        active.append(ann)
    return active

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
        "ai_manager_count": 16,
        "schedule_enabled": False,
        "schedule_slots": [],
        "github_push_enabled": True,
        "immortal_arenas_enabled": False,
        "ai_happenings_enabled": False,
    }, allow_tampered=True)
    # Ensure new flags exist in old configs
    for key, default in [
        ("show_favorite_weapon", False),
        ("show_luck_factor", False),
        ("show_max_hp", False),
        ("ai_teams_enabled", True),
        ("ai_manager_count", 16),
        ("schedule_enabled", False),
        ("admin_debug_manager_id", ""),
        ("rerun_count", 0),
        ("rerun_turn", 0),
        ("github_push_enabled", True),
        ("immortal_arenas_enabled", False),
        ("ai_happenings_enabled", False),
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

def _conceal_ai_in_standings(standings):
    """Return a client-safe copy of standings: drop the is_ai flag and remap the
    internal ai_ manager-id keys to the AI team's (player-like) team_id, so a
    player inspecting the raw payload cannot tell which managers are AI. Admin
    tools read the on-disk standings directly and still see everything."""
    ai_tid = {}
    try:
        from ai_league_teams import load_ai_teams
        for at in (load_ai_teams() or []):
            if at.get("manager_id") and at.get("team_id"):
                ai_tid[at["manager_id"]] = str(at["team_id"])
    except Exception:
        pass
    import re
    try:
        from ai_league_teams import inactive_ai_ids
        _off = inactive_ai_ids()
    except Exception:
        _off = set()
    out = {}
    taken = {str(k) for k in standings if not str(k).startswith("ai_")}
    for mid, sd in standings.items():
        if mid in _off:
            continue   # AI manager switched off by the AI manager count setting
        entry = {k: v for k, v in sd.items() if k != "is_ai"} if isinstance(sd, dict) else sd
        if str(mid).startswith("ai_"):
            try:    idx = int(re.match(r"ai_(\d+)", str(mid)).group(1))
            except Exception: idx = 0
            key = ai_tid.get(mid) or str(1000 + idx)
            while key in taken or key in out:
                key = str(900000 + idx)   # last-resort, effectively never hit
            out[key] = entry
        else:
            out[str(mid)] = entry
    return out

def _build_game_data():
    """Build the game_data object (races, weapons, armor, skills, etc) for API endpoints.
    Used by /api/game_data and included in /api/results downloads."""
    from warrior import (
        ATTRIBUTES, FIGHTING_STYLES, TRIGGERS, AIM_DEFENSE_POINTS,
        NON_WEAPON_SKILLS, WEAPON_SKILLS,
    )
    from warrior import TIER_ORDER, TIER_THRESHOLDS, TIER_RECRUITS, MAX_FIGHTS
    from warrior import stat_descriptions_for_client
    from weapons import WEAPONS
    from armor import armor_selection_menu, helm_selection_menu
    from races import list_playable_races

    return {
        # Rules the client displays but must not define for itself.
        "tiers"            : {"order": TIER_ORDER, "thresholds": [list(t) for t in TIER_THRESHOLDS],
                              "lowest": TIER_RECRUITS},
        "rules"            : {"retire_min_fights": MAX_FIGHTS},
        "stat_descriptions": stat_descriptions_for_client(),
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
    survived = set()     # (name, fight_id) the warrior's own result reports as not slain
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
                                "fight_id": fight_id,
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
                                "fight_id": fight_id,
                            })
                    # A warrior's own result is authoritative: if it says they
                    # survived (Soul Spire transcendence, promotion shield), the
                    # winner's "opponent_slain" is not a death.
                    if bout.get("warrior_slain") is False and not bout.get("transcended"):
                        survived.add((bout.get("warrior_name"), bout.get("fight_id", 0)))
    except Exception as e:
        print(f"  ERROR loading deaths from results: {e}")
        import traceback
        traceback.print_exc()

    return [d for d in deaths if (d["name"], d["fight_id"]) not in survived]

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


_RECOVER_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bloodspire - Recover My Files</title>
<style>
body{background:#14110f;color:#e8e0d4;font-family:Segoe UI,Arial,sans-serif;margin:0;padding:24px}
.card{max-width:460px;margin:40px auto;background:#201b18;border:1px solid #4a3b30;border-radius:8px;padding:24px}
h1{margin:0 0 8px;font-size:22px;color:#d9a441}
p,li{line-height:1.5;font-size:14px}
label{display:block;margin:14px 0 4px;font-size:13px}
input{width:100%;box-sizing:border-box;padding:9px;background:#14110f;color:#e8e0d4;border:1px solid #4a3b30;border-radius:4px;font-size:15px}
button{margin-top:18px;width:100%;padding:11px;background:#8b2a1f;color:#fff;border:0;border-radius:4px;font-size:15px;cursor:pointer}
button:disabled{opacity:.5;cursor:wait}
#msg{margin-top:14px;font-size:14px;min-height:20px}.err{color:#ff7b6b}.ok{color:#8fd18f}
</style></head><body><div class="card">
<h1>Recover My Files</h1>
<p>Download froze or failed? Enter your account number and password to get a ZIP of all your teams, results and newsletters.</p>
<label for="mid">Account number</label><input id="mid" name="bs_recover_acct" inputmode="numeric" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" readonly onfocus="this.removeAttribute('readonly')">
<label for="pw">Password</label><input id="pw" name="bs_recover_pass" type="password" autocomplete="new-password" autocapitalize="off" autocorrect="off" spellcheck="false" readonly onfocus="this.removeAttribute('readonly')">
<button id="go">Download my files</button>
<div id="msg"></div>
<p style="margin-top:20px"><b>To restore:</b></p>
<ol><li>Open the Bloodspire client.</li><li>Preferences &rarr; Restore from ZIP&hellip;</li><li>Choose the ZIP you just downloaded.</li></ol>
</div>
<script>
const go=document.getElementById('go'),msg=document.getElementById('msg');
function say(t,c){msg.textContent=t;msg.className=c||''}
async function run(){
  const mid=document.getElementById('mid').value.trim(),pw=document.getElementById('pw').value;
  if(!mid||!pw){say('Enter your account number and password.','err');return}
  go.disabled=true;say('Building your ZIP...');
  try{
    const r=await fetch('/api/my_files_zip',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({manager_id:mid,password:pw})});
    if(!r.ok){let e='Download failed.';try{e=(await r.json()).error||e}catch(_){}say(e,'err');return}
    const blob=await r.blob(),a=document.createElement('a');
    a.href=URL.createObjectURL(blob);a.download='manager_'+mid+'_files.zip';
    document.body.appendChild(a);a.click();a.remove();
    say('Done. Check your Downloads folder.','ok');
  }catch(e){say('Could not reach the server: '+e,'err')}
  finally{go.disabled=false}
}
// Never keep credentials around: clear on load, on back/forward cache restore, and
// shortly after load in case a password manager filled the fields anyway.
const typed={mid:false,pw:false};
['mid','pw'].forEach(id=>document.getElementById(id).addEventListener('keydown',()=>{typed[id]=true}));
function wipe(force){['mid','pw'].forEach(id=>{if(force||!typed[id])document.getElementById(id).value=''})}
wipe(true);setTimeout(wipe,300);setTimeout(wipe,1200);
window.addEventListener('pageshow',()=>{typed.mid=typed.pw=false;wipe(true)});
go.addEventListener('click',run);
document.getElementById('pw').addEventListener('keydown',e=>{if(e.key==='Enter')run()});
</script></body></html>
"""


def _build_manager_zip(mid, managers):
    """Build the restore ZIP (teams, results, newsletters, MANIFEST, README) for one
    manager and return it as bytes. Shared by the admin and self-service endpoints."""
    import zipfile
    mname = managers[mid]["manager_name"]
    from io import BytesIO
    zip_buffer = BytesIO()
    manifest = []  # Track files and their target locations

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add all team files for this manager. team_ids covers normal-arena
        # teams; immortal_team_ids covers teams that ascended to the Elite or
        # Veteran (immortal) arenas, whose snapshots live in a separate
        # per-arena directory and were previously skipped entirely here.
        mgr_teams = set(int(t) for t in managers[mid].get("team_ids", []) if isinstance(t,(int,str)) and str(t).isdigit())
        mgr_immortal_teams = set(int(t) for t in managers[mid].get("immortal_team_ids", []) if isinstance(t,(int,str)) and str(t).isdigit())
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
        for team_id in mgr_immortal_teams:
            for arena in ("elite", "veteran"):
                team_file = os.path.join(_immortal_team_dir(arena), f"team_{int(team_id):04d}.json")
                if os.path.exists(team_file):
                    # Store in <arena>/teams/ subdirectory in ZIP, matching the
                    # client's expected on-disk layout for immortal teams.
                    arcname = f"{arena}/teams/team_{int(team_id):04d}.json"
                    zf.write(team_file, arcname=arcname)
                    manifest.append({
                        "source": arcname,
                        "target": arcname,
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
    return zip_buffer.getvalue()


def _utility_newest_turn(arena_root):
    """(turn number, folder) of the newest turn_NNNN folder under arena_root, or (0, '')."""
    import re
    best_n, best_d = 0, ""
    try:
        names = os.listdir(arena_root)
    except OSError:
        return 0, ""
    for name in names:
        m = re.match(r"^turn_(\d+)$", name)
        full = os.path.join(arena_root, name)
        if m and os.path.isdir(full) and int(m.group(1)) > best_n:
            best_n, best_d = int(m.group(1)), full
    return best_n, best_d


def _build_utility_bundle(saves_dir=None):
    """ZIP of what the host's utilities (Challenge Finder) read, laid out like the server's saves folder so a
    copy on another machine can be pointed at it unchanged. Host-only. It never includes managers.json,
    password hashes (league/config.json is rewritten to the two keys the tools use), logs, or scouting data.
    Returns (zip_bytes, manifest dict)."""
    import zipfile
    from io import BytesIO
    saves = saves_dir or os.path.join(BASE_DIR, "saves")
    league = os.path.join(saves, "league")
    buf = BytesIO()
    counts = {"teams": 0, "elite_teams": 0, "veteran_teams": 0, "latest_turn_files": 0}
    turns = {}

    def add_dir_json(zf, src_dir, arc_dir, key, prefix=None):
        try:
            names = sorted(os.listdir(src_dir))
        except OSError:
            return
        for fn in names:
            if not fn.endswith(".json") or (prefix and not fn.startswith(prefix)):
                continue
            full = os.path.join(src_dir, fn)
            if os.path.isfile(full):
                zf.write(full, arcname=f"{arc_dir}/{fn}")
                counts[key] = counts.get(key, 0) + 1

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        add_dir_json(zf, os.path.join(saves, "teams"), "teams", "teams", "team_")
        add_dir_json(zf, os.path.join(saves, "elite", "teams"), "elite/teams", "elite_teams", "team_")
        add_dir_json(zf, os.path.join(saves, "veteran", "teams"), "veteran/teams", "veteran_teams", "team_")

        ai = os.path.join(league, "ai_teams.json")
        if os.path.isfile(ai):
            zf.write(ai, arcname="league/ai_teams.json")
        # Sanitized config: only the keys the tools read. The real file holds the host password hash and salt.
        cfg = {}
        try:
            with open(os.path.join(league, "config.json"), "r", encoding="utf-8") as f:
                real = json.load(f)
            cfg = {"current_turn": real.get("current_turn", 0), "ai_manager_count": real.get("ai_manager_count", 16)}
        except Exception:
            cfg = {"current_turn": 0, "ai_manager_count": 16}
        zf.writestr("league/config.json", json.dumps(cfg, indent=2))
        turns["normal"] = cfg["current_turn"]

        for arc, src in (("champion.json", os.path.join(saves, "champion.json")),
                         ("elite/champion.json", os.path.join(saves, "elite", "champion.json"))):
            if os.path.isfile(src):
                zf.write(src, arcname=arc)

        # The newest turn's uploads, results and newsletter for each arena.
        for arena, root, arc_root in (("normal", league, "league"), ("elite", os.path.join(saves, "elite"), "elite"),
                                      ("veteran", os.path.join(saves, "veteran"), "veteran")):
            n, d = _utility_newest_turn(root)
            if arena != "normal":
                turns[arena] = n
            if not d:
                continue
            for fn in sorted(os.listdir(d)):
                full = os.path.join(d, fn)
                if os.path.isfile(full) and ((fn.startswith(("upload_", "result_")) and fn.endswith(".json"))
                                             or fn == "newsletter.txt"):
                    zf.write(full, arcname=f"{arc_root}/{os.path.basename(d)}/{fn}")
                    counts["latest_turn_files"] += 1
        for arena in ("elite", "veteran"):
            up = os.path.join(saves, arena, "uploads")
            try:
                names = sorted(os.listdir(up))
            except OSError:
                names = []
            for fn in names:
                full = os.path.join(up, fn)
                if os.path.isfile(full) and fn.endswith(".json"):
                    zf.write(full, arcname=f"{arena}/uploads/{fn}")
                    counts["latest_turn_files"] += 1

        manifest = {"kind": "bloodspire_utility_bundle", "format": 1, "server_version": SERVER_VERSION,
                    "generated": time.strftime("%Y-%m-%d %H:%M:%S"), "current_turn": cfg["current_turn"],
                    "turns": turns, "counts": counts}
        zf.writestr("UTILITY_MANIFEST.json", json.dumps(manifest, indent=2))
    return buf.getvalue(), manifest


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


def _fight_diag(result, me, opp, i_won: bool, fight_type: str = "") -> dict:
    """Why-did-it-happen snapshot of one fight from `me`'s point of view. Used
    only by the AI learning engine (attached to AI managers' bouts)."""
    try:
        won = bool(i_won)
        my_hp  = result.winner_hp_pct if won else result.loser_hp_pct
        op_hp  = result.loser_hp_pct if won else result.winner_hp_pct
        my_end = result.winner_end_pct if won else result.loser_end_pct
        op_end = result.loser_end_pct if won else result.winner_end_pct
        my_kd  = result.winner_knockdowns if won else result.loser_knockdowns
        op_kd  = result.loser_knockdowns if won else result.winner_knockdowns
        my_nk  = result.winner_near_kills if won else result.loser_near_kills
        op_nk  = result.loser_near_kills if won else result.winner_near_kills
        if result.loser_died:
            ended = "death"
        elif result.exhaustion_end:
            ended = "exhaustion"
        else:
            ended = "decision"

        def _gear(w):
            return {
                "weapon": getattr(w, "primary_weapon", None),
                "offhand": getattr(w, "secondary_weapon", None),
                "armor": getattr(w, "armor", None),
                "helm": getattr(w, "helm", None),
                "str": getattr(w, "strength", 0), "dex": getattr(w, "dexterity", 0),
                "con": getattr(w, "constitution", 0), "size": getattr(w, "size", 0),
                "hp": getattr(w, "max_hp", 0), "end": getattr(w, "max_endurance", 0),
                "fights": getattr(w, "total_fights", 0),
            }
        return {
            "won": won, "ended_by": ended, "minutes": result.minutes_elapsed,
            "fight_type": fight_type or "",
            "my_hp_end": round(my_hp, 3), "opp_hp_end": round(op_hp, 3),
            "my_end_end": round(my_end, 3), "opp_end_end": round(op_end, 3),
            "my_knockdowns": my_kd, "opp_knockdowns": op_kd,
            "my_near_kills": my_nk, "opp_near_kills": op_nk,
            "me": _gear(me), "opp": _gear(opp),
        }
    except Exception:
        return {}


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
      - Minimum fights    (default 40)
      - Minimum win rate  (default 65%)
      - Minimum combined trains -- skill levels + attribute gains (default 45)

    Sets pending_promotion='elite' on eligible warriors.
    Returns list of {name, team, record} dicts for newsletter/logging.
    """
    promo_cfg    = cfg.get("promotion_criteria", {})
    min_fights   = int(promo_cfg.get("min_fights",   40))
    min_win_rate = float(promo_cfg.get("min_win_rate", 0.65))
    min_trains   = int(promo_cfg.get("min_trains",   45))
    newly_eligible = []
    for team in all_teams:
        for w in team.active_warriors:
            if not w:
                continue
            if getattr(w, "current_arena", "normal") != "normal":
                continue
            if getattr(w, "pending_promotion", None) is not None:
                continue
            if _is_monster(w):
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
                                   "manager": team.manager_name, "team_id": team.team_id,
                                   "record": f"{w.wins}-{w.losses}-{w.kills}"})
            print(f"  PROMOTION ELIGIBLE: {w.name} ({team.team_name}) - "
                  f"{w.wins}W/{w.losses}L ({win_rate:.1%}), {trains} trains "
                  f"-> pending Elite Spire promotion next turn.")
    return newly_eligible


def _is_monster(w) -> bool:
    race = getattr(w, "race", None)
    return getattr(race, "name", race) == "Monster"


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
            if _is_monster(w):
                w.pending_promotion = None
                continue
            if getattr(w, "current_arena", "normal") not in ("normal",):
                continue
            if w.is_dead:
                print(f"  SHIELD REVIVE: {w.name} fell in their final mortal fight - "
                      f"immortality shield triggers, promotion proceeds.")
                w.is_dead  = False
                w.hp       = max(1, getattr(w, "max_hp", 100) // 2)
            w.current_arena     = target
            w.pending_promotion = None
            w.is_promoted       = True
            w.recognition       = 0
            events.append({
                "type":         "promotion",
                "warrior_name": w.name,
                "team_name":    team.team_name,
                "team_id":      team.team_id,
                "manager_name": team.manager_name,
                "from_arena":   "normal",
                "to_arena":     target,
                "record":       f"{w.wins}-{w.losses}-{w.kills}",
                "turn":         turn_num,
            })
            _disp = {"elite": "THE ELITE SPIRE", "veteran": "THE SOUL SPIRE"}.get(target, target.upper())
            print(f"  PROMOTED: {w.name} ({team.team_name}) -> {_disp} "
                  f"({w.wins}W/{w.losses}L/{w.kills}K)")
    return events


def _run_turn(request_password, rerun_turn=None):
    try:
        _n = int(rerun_turn) if rerun_turn else int(_load_config().get("current_turn", 0))
    except Exception:
        _n = 0
    try:
        with _turn_log(f"turn_{_n:04d}"):
            return _run_turn_inner(request_password, rerun_turn)
    finally:
        _unlock_downloads("normal")


def _run_turn_inner(request_password, rerun_turn=None):
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

        # Autopilot: AI-run human manager accounts (saves/league/autopilot.json).
        # Never allowed to fail the turn.
        try:
            import autopilot
            autopilot.run(uploads, turn_num, _save_upload)
        except Exception as _ap_e:
            print(f"  [AUTOPILOT] disabled for this turn: {_ap_e}")

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

        # One-time migration: the new procedural learning roster reuses the ai_
        # manager ids but with brand-new managers/warriors, so wipe the stale
        # legacy AI standings entries once. New entries rebuild the same turn.
        if ai_teams and not cfg.get("ai_roster_v2"):
            try:
                _st = _load_standings()
                _rm = [k for k in list(_st) if str(k).startswith("ai_")]
                for k in _rm:
                    _st.pop(k, None)
                if _rm:
                    _save_standings(_st)
                    print(f"  [AI] Migration: cleared {len(_rm)} legacy AI standings entries.")
                cfg["ai_roster_v2"] = True
                _save_config(cfg)
            except Exception as _mig_e:
                print(f"  [AI] standings migration skipped: {_mig_e}")

        if not uploads:
            return {"success": False, "error": "No teams (player or AI) available."}

        _FLAG_KEYS = ("show_favorite_weapon", "show_luck_factor", "show_max_hp", "ai_teams_enabled")
        _turn_start_flags = {k: cfg.get(k) for k in _FLAG_KEYS}

        # Archive old results instead of deleting (CRITICAL: preserve for auditing)
        _archive_old_results(turn_num)

        cfg["turn_state"] = "processing"
        _lock_downloads("normal", turn_num)
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
                if not isinstance(team_data, dict):
                    continue
                if team_data.get("team_id") == champ_tid or str(team_key).endswith(f"_team{champ_tid}"):
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

    from save import build_warrior_id_index, enforce_unique_active_ids, reconcile_warrior_ids, restore_archived_ids
    _wid_index = build_warrior_id_index()
    for mid, upload in uploads.items():
        try:
            _up_tid = (upload.get("team") or {}).get("team_id") if isinstance(upload.get("team"), dict) else None
            if _up_tid:
                for _n, _old, _new in enforce_unique_active_ids(upload["team"], _up_tid, _wid_index):
                    print(f"    [ID FIX] team_{_up_tid} warrior '{_n}' id {_old} -> {_new}")
                restore_archived_ids(upload["team"], _up_tid)
            team = Team.from_dict(upload["team"])
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

            # The server's own team save is the authority on who is alive right now.
            # save_team() writes it after every turn (deaths included), and it is what
            # an admin revive/revert updates.  Old result files are immutable history:
            # after a revive they still carry is_dead=True for that warrior_id and would
            # silently re-kill them on every turn inside the 4-turn window above --
            # dropping the team below 5 active warriors so it never enters the fight
            # card.  See PEOPLE WHO STANK / GO ON, GIT! / THE CONDEMNED / THE B TEAM,
            # turn 42.  So collect the ids the live save reports alive and let them
            # override the historical results.
            _alive_in_save = set()
            try:
                from save import load_team as _lt_alive
                for _sw in (_lt_alive(_this_team_id).warriors or []):
                    if _sw and _sw.warrior_id is not None and not getattr(_sw, "is_dead", False):
                        _alive_in_save.add(_sw.warrior_id)
            except Exception:
                pass  # brand-new or unreadable save - fall back to results-only enforcement

            # Apply dead status from results - matched by warrior_id, not name.
            for _w in team.warriors:
                if _w and _w.warrior_id in _dead_in_results:
                    if _w.warrior_id in _alive_in_save:
                        print(f"    [INTEGRITY CHECK] Warrior {_w.name} (id={_w.warrior_id}) is dead in an old "
                              f"result file but alive in the team save - honouring the save (revived)")
                        continue
                    _dead_entry = _dead_in_results[_w.warrior_id]
                    _w.is_dead = True
                    _w.killed_by = _dead_entry["killed_by"]
                    print(f"    [INTEGRITY CHECK] Warrior {_w.name} (id={_w.warrior_id}) was dead in recent results - enforced is_dead=True")

            # Restore pending_promotion and server-computed combat stats from the
            # server's persistent file. `team` above was built straight from the
            # client's raw upload (Team.from_dict(upload["team"])) -- this IS the
            # object the turn's fights run against, so anything not restored here
            # feeds fight resolution with whatever the client last had, not what
            # the server actually computed.
            #
            # pending_promotion: client uploads never carry this field. Without
            # restoring it, a warrior flagged pending_promotion='elite' would
            # never be promoted -- _execute_promotions sees None every turn and
            # _check_promotion_eligibility re-sets it at the end, an infinite stall.
            #
            # recognition/wins/losses/kills/total_fights/popularity/is_promoted/
            # current_arena: these are entirely server-computed (update_recognition,
            # record_result, promotion execution). A manager's client can fall
            # behind the server (stale cache, missed sync, a bugfix that hasn't
            # reached them yet) -- restoring these here, not just at upload-save
            # time, closes that gap for the one place that actually matters: the
            # in-memory Team object this turn's fights are resolved against.
            try:
                from save import load_team as _lt_promo
                _promo_src = _lt_promo(_this_team_id)
                _server_state = {
                    w.name: w for w in (_promo_src.warriors or []) if w
                }
                _restore_fields = ("wins", "losses", "kills", "total_fights",
                                    "recognition", "popularity", "is_promoted",
                                    "current_arena")
                for _pw in (team.warriors or []):
                    if not _pw or _pw.name not in _server_state:
                        continue
                    _sw = _server_state[_pw.name]
                    if getattr(_sw, "pending_promotion", None) and not getattr(_pw, "pending_promotion", None):
                        _pw.pending_promotion = _sw.pending_promotion
                        print(f"    [PROMO] Restored pending_promotion={_sw.pending_promotion} for {_pw.name}")
                    for _f in _restore_fields:
                        _server_val = getattr(_sw, _f, None)
                        if _server_val is not None and getattr(_pw, _f, None) != _server_val:
                            print(f"    [STATS] {_pw.name}: client upload had {_f}={getattr(_pw, _f, None)!r}, "
                                  f"restoring server value {_server_val!r}")
                            setattr(_pw, _f, _server_val)
            except Exception:
                pass

            # Validate team has exactly 5 active warriors before running
            active_count = len(team.active_warriors)
            if active_count != 5:
                print(f"  SKIP: {team.team_name} (ID:{team.team_id}) - Only {active_count}/5 active warriors - Manager: {upload['manager_name']}")
                continue

            # Check if team is marked to run this turn
            if not upload["team"].get("auto_upload_enabled", True):
                print(f"  SKIP: {team.team_name} (ID:{team.team_id}) - 'Run Next Turn' is unchecked - Manager: {upload['manager_name']}")
                continue

            team_map[mid] = team
            # Remember whether this turn's fights come from an auto-carried upload,
            # so the auto-run limit can count it after the fights are saved.
            team._ran_on_auto = bool(upload.get("auto_uploaded")) and not mid.startswith("ai_")
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
    # ONE-SHOT: Recalibrate recognition to flat scoring formula
    # Runs exactly once (gated by config flag), before any fights execute.
    # Covers ALL saved teams, not just those who uploaded this turn, so
    # warriors on inactive teams get corrected too.
    # Formula: min(100, 3*W + 2*K + L)
    # ===================================================================
    if not cfg.get("recognition_recalibrated_v4", False):
        print("  [RECAL] One-shot recognition recalibration (flat scoring)...")
        from save import load_all_teams, save_team
        recal_count = 0

        def _recal_warrior(w):
            nonlocal recal_count
            if w is None:
                return
            w_wins   = getattr(w, "wins",   0)
            w_losses = getattr(w, "losses", 0)
            w_kills  = getattr(w, "kills",  0)
            new_rec  = min(100, 3 * w_wins + 2 * w_kills + w_losses)
            old_rec  = getattr(w, "recognition", 0)
            w.recognition = new_rec
            if old_rec != new_rec:
                print(f"    {w.name}: {old_rec} -> {new_rec}")
                recal_count += 1

        # Recalibrate in-memory teams (those uploading this turn)
        uploaded_team_ids = set()
        for _team in all_player_teams:
            for _w in _team.active_warriors:
                _recal_warrior(_w)
            uploaded_team_ids.add(getattr(_team, "team_id", None))

        # Recalibrate and persist all other saved teams not in this turn's uploads
        try:
            for _saved_team in load_all_teams():
                if getattr(_saved_team, "team_id", None) in uploaded_team_ids:
                    continue  # already handled in-memory above
                changed = False
                for _w in (_saved_team.warriors or []):
                    old = getattr(_w, "recognition", 0) if _w else 0
                    _recal_warrior(_w)
                    if _w and getattr(_w, "recognition", 0) != old:
                        changed = True
                if changed:
                    save_team(_saved_team)
        except Exception as _re:
            print(f"  [RECAL] WARNING: could not recalibrate saved teams: {_re}")

        cfg["recognition_recalibrated_v4"] = True
        _save_config(cfg)
        print(f"  [RECAL] Done -- {recal_count} warrior(s) adjusted.\n")

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
    # Do NOT reset challenge_strategy_enabled yet -- warriors need that flag
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
    transcendence_events   = []  # warriors who transcend to THE SOUL SPIRE on death
    fight_counter = cfg.get("fight_counter", 0)

    # Track team objects for updating
    team_by_id = {t.team_id: t for t in all_player_teams}

    # CRITICAL: Preserve original weapon loadout values
    # Combat can mutate primary_weapon/secondary_weapon in-fight (disarms, weapon
    # breaks, drawing a backup, throwing away a secondary) and clear backup_weapon
    # if it gets drawn. These are meant to be purely within-fight tactical states -
    # if the fight ends before a disarmed warrior gets a chance to re-arm, whatever
    # mid-fight weapon state they were left in would otherwise get permanently
    # saved as their gear loadout, corrupting it for every future turn.
    weapon_loadout_backup = {}
    for team in all_player_teams:
        weapon_loadout_backup[team.team_id] = {}
        for w in team.active_warriors:
            if w:
                weapon_loadout_backup[team.team_id][w.name] = (
                    w.primary_weapon, w.secondary_weapon, w.backup_weapon,
                )

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
            "challenger_name": fight.challenger_name,
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
                "challenger_name": fight.challenger_name,
            })

        # Transcendence flags, recorded on the result bouts so the newsletter still lists
        # the death (in THE DEAD) while the warrior is summoned to the Soul Spire.
        _pl_trans = False
        _op_trans = False

        # Immortality shield: warriors with a pending promotion cannot be
        # permanently killed during their final mortal fight in the normal arena.
        if slain and getattr(fight.player_warrior, "pending_promotion", None):
            print(f"  SHIELD: {fight.player_warrior.name}'s immortality shield absorbed "
                  f"their death. They will be promoted after this turn.")
            slain = False

        # Auto-transcendence: worthy warriors who die transcend to THE SOUL SPIRE
        # instead of dying permanently.  Criteria: 20+ fights and 55%+ win rate.
        # Warriors killed in a monster fight chose that path -- no Soul Spire.
        if slain and fight.fight_type != "monster":
            _w   = fight.player_warrior
            _tot = _w.wins + _w.losses
            _wr  = _w.wins / _tot if _tot > 0 else 0.0
            if _tot >= 20 and _wr >= 0.55:
                print(f"  TRANSCENDENCE: {_w.name} ({_wr:.1%}, {_tot} fights) "
                      f"transcends to THE SOUL SPIRE.")
                _w.current_arena = "veteran"
                _w.is_dead       = False
                _w.is_promoted   = True
                _w.hp            = max(1, getattr(_w, "max_hp", 100))
                _w.recognition   = 0
                # Only announce in the newsletter and seed the Soul Spire when
                # the arena is live; otherwise the warrior is silently flagged
                # and will be seeded automatically once the toggle is enabled.
                if cfg.get("immortal_arenas_enabled", False):
                    transcendence_events.append({
                        "warrior_name": _w.name,
                        "team_name":    fight.player_team.team_name,
                        "team_id":      fight.player_team.team_id,
                        "manager_name": fight.player_team.manager_name,
                        "record":       f"{_w.wins}-{_w.losses}-{_w.kills}",
                        "win_rate":     round(_wr, 4),
                        "total_fights": _tot,
                    })
                slain = False
                _pl_trans = True
                # Transcending spares him from the grave, but he was still beaten to
                # death by another warrior: his teammates may avenge him.
                fight.player_team.add_blood_challenge(
                    _w.name, fight.opponent.name, fight_type_to_record)

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
                      f"transcends to THE SOUL SPIRE.")
                _ow.current_arena = "veteran"
                _ow.is_dead       = False
                _ow.is_promoted   = True
                _ow.hp            = max(1, getattr(_ow, "max_hp", 100))
                _ow.recognition   = 0
                if cfg.get("immortal_arenas_enabled", False):
                    transcendence_events.append({
                        "warrior_name": _ow.name,
                        "team_name":    fight.opponent_team.team_name,
                        "team_id":      fight.opponent_team.team_id,
                        "manager_name": fight.opponent_team.manager_name,
                        "record":       f"{_ow.wins}-{_ow.losses}-{_ow.kills}",
                        "win_rate":     round(_wr, 4),
                        "total_fights": _tot,
                    })
                opp_slain = False
                _op_trans = True
                fight.opponent_team.add_blood_challenge(
                    _ow.name, fight.player_warrior.name, fight_type_to_record)

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

        # Retirement -- processed AFTER the warrior's fight this turn (their final bout),
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

        # Blood challenge resolution -- always consumes the challenge (win or loss)
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
            "transcended": _pl_trans,
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
            "exhaustion_collapse": bool(getattr(result, "exhaustion_end", False)
                                        and getattr(result, "loser", None) is not None
                                        and result.loser.name == fight.player_warrior.name),
        }

        # Append Elite Spire promotion announcement for warriors fighting their
        # final mortal bout under the immortality shield this turn
        from narrative import elite_spire_shield_line as _shield_line
        for _shield_w in (fight.player_warrior, fight.opponent):
            if getattr(_shield_w, "pending_promotion", None) == "elite" and not _is_monster(_shield_w):
                result.narrative += "\n" + _shield_line(_shield_w.name)

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
            if str(player_manager_id).startswith("ai_"):
                player_bout["diag"] = _fight_diag(result, fight.player_warrior, fight.opponent,
                                                  pw_won, fight_type_to_record)
            all_results[player_manager_id]["bouts"].append(player_bout)
            all_results[player_manager_id]["fight_logs"][str(fid)] = result.narrative

        # Store result for opponent manager (if not NPC)
        if opponent_manager_id and fight.opponent_team.team_id >= 0:
            # DEBUG: Track problematic managers
            if opponent_manager_id in ['22', 22, '24', 24, '26', 26]:
                print(f"    [STORE] Storing opponent result for manager {opponent_manager_id}")
            opponent_bout = {
                "transcended": _op_trans,
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
                "exhaustion_collapse": bool(getattr(result, "exhaustion_end", False)
                                            and getattr(result, "loser", None) is not None
                                            and result.loser.name == fight.opponent.name),
            }
            if str(opponent_manager_id).startswith("ai_"):
                opponent_bout["diag"] = _fight_diag(result, fight.opponent, fight.player_warrior,
                                                    opp_won, fight_type_to_record)
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

    # CRITICAL: Restore original weapon loadout values before saving teams
    # Combat can mutate primary/secondary/backup weapon in-fight; we want to
    # preserve the original loadout regardless of how any fight ended.
    for team in all_player_teams:
        team_id = team.team_id
        if team_id in weapon_loadout_backup:
            for w in team.active_warriors:
                if w and w.name in weapon_loadout_backup[team_id]:
                    w.primary_weapon, w.secondary_weapon, w.backup_weapon = \
                        weapon_loadout_backup[team_id][w.name]

    # Execute any pending promotions (warriors who fought with the immortality
    # shield this turn) -- must happen before teams are saved so the updated
    # current_arena and cleared pending_promotion are persisted.
    _immortal_on = cfg.get("immortal_arenas_enabled", False)
    promotion_events = _execute_promotions(all_player_teams, turn_num) if _immortal_on else []

    # Check eligibility for warriors who may have crossed the threshold this turn;
    # their pending_promotion flag will be saved now and the shield will activate
    # for their final mortal fight next turn.
    newly_eligible = _check_promotion_eligibility(all_player_teams, cfg) if _immortal_on else []

    # Append Elite Spire call announcement to fight logs for warriors who
    # newly qualified this turn -- both player and opponent perspectives
    if newly_eligible:
        from narrative import elite_spire_call_line as _call_line
        for _ne in newly_eligible:
            _ne_name = _ne.get("name", "")
            _promo_msg = "\n" + _call_line(_ne_name)
            for _mid, _res in all_results.items():
                for _bout in _res.get("bouts", []):
                    _is_warrior  = _bout.get("warrior_name",  "").upper() == _ne_name.upper()
                    _is_opponent = _bout.get("opponent_name", "").upper() == _ne_name.upper()
                    if _is_warrior or _is_opponent:
                        _fid_str = str(_bout.get("fight_id", ""))
                        if _fid_str in _res.get("fight_logs", {}):
                            _res["fight_logs"][_fid_str] += _promo_msg
                        break

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
            # Auto-run limit: consecutive auto-carried turns, reset by a manual upload.
            # Reruns are not new turns, so they don't move the counter.
            if not rerun_turn and not str(manager_id).startswith("ai_"):
                from team import AUTO_RUN_TURN_LIMIT
                if team.record_turn_run(getattr(team, "_ran_on_auto", False)):
                    print(f"  [AUTO-RUN] {team.team_name} (ID:{team.team_id}) ran "
                          f"{AUTO_RUN_TURN_LIMIT} turns on auto-run and is now paused. "
                          f"The manager must turn auto-run back on to resume.")
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
            # Seed the arena-specific team file for any warrior promoted this turn.
            # _execute_promotions() already set current_arena='elite'/'veteran' on the
            # warrior; save_team() above wrote that to saves/teams/.  But the migration
            # won't pick it up (already_seeded=True), so we must explicitly add the new
            # warrior to saves/{arena}/teams/ now so they appear in the Elite Spire /
            # Soul Spire tab immediately after the turn completes.
            # We merge rather than overwrite so we don't clobber existing fighters'
            # current-turn stats with stale main-file data.
            # Seeding is skipped when immortal arenas are disabled -- warriors are
            # flagged internally (current_arena set) but won't appear in arena tabs
            # until the toggle is enabled and the next turn seeds them.
            _team_dict_for_arena = team.to_dict()
            if _immortal_on:
                for _pa in ("elite", "veteran"):
                    _newly_promoted = [
                        w for w in (_team_dict_for_arena.get("warriors") or [])
                        if isinstance(w, dict)
                        and (w.get("current_arena") or "normal") == _pa
                        and w.get("is_promoted")
                        and not w.get("is_dead", False)
                    ]
                    if not _newly_promoted:
                        continue
                    try:
                        _pa_dir  = _immortal_team_dir(_pa)
                        os.makedirs(_pa_dir, exist_ok=True)
                        _pa_file = os.path.join(_pa_dir, f"team_{team.team_id:04d}.json")
                        if os.path.exists(_pa_file):
                            with open(_pa_file, encoding="utf-8") as _pf:
                                _pa_td = json.load(_pf)
                        else:
                            _pa_td = {
                                "team_id":      team.team_id,
                                "team_name":    team.team_name,
                                "manager_name": team.manager_name,
                                "warriors": [], "archived_warriors": [],
                            }
                        _existing_names = {
                            w.get("name") for w in
                            list(_pa_td.get("warriors") or []) +
                            list(_pa_td.get("archived_warriors") or [])
                            if isinstance(w, dict)
                        }
                        for _nw in _newly_promoted:
                            if _nw.get("name") not in _existing_names:
                                _pa_td.setdefault("archived_warriors", []).append(_nw)
                                _existing_names.add(_nw.get("name"))
                                print(f"  Added {_nw.get('name')} to {_pa} team file "
                                      f"(team {team.team_id}).")
                        with open(_pa_file, "w", encoding="utf-8") as _pf:
                            json.dump(_pa_td, _pf, indent=2)
                    except Exception as _pe:
                        print(f"  WARNING: could not update {_pa} team file for "
                              f"team {team.team_id}: {_pe}")
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
            arena_sel   = sel.get("arena", "normal") or "normal"
            scout_name, scout_type = _get_or_assign_scout_persona(real_manager_id, _scout_mgrs)

            # ── Immortal arena scout (Elite Spire / Soul Spire) ──────────────
            if arena_sel in ("elite", "veteran"):
                from warrior import Warrior as _WClass
                from scout_report import _sat_out_message as _som
                _arena_dir  = os.path.join(BASE_DIR, "saves", arena_sel)
                _teams_dir  = os.path.join(_arena_dir, "teams")
                _imm_wd     = None
                _imm_tname  = t_team_name
                if os.path.exists(_teams_dir):
                    for _tf in sorted(os.listdir(_teams_dir)):
                        if not _tf.endswith(".json"): continue
                        try:
                            with open(os.path.join(_teams_dir, _tf), encoding="utf-8") as _f:
                                _td = json.load(_f)
                        except Exception:
                            continue
                        for _wd in (_td.get("warriors") or []):
                            if _wd and _wd.get("name","").upper() == t_name.upper():
                                _imm_wd = _wd; _imm_tname = _td.get("team_name", t_team_name); break
                        if not _imm_wd:
                            for _wd in (_td.get("archived_warriors") or []):
                                if isinstance(_wd, dict) and _wd.get("name","").upper() == t_name.upper():
                                    _imm_wd = _wd; _imm_tname = _td.get("team_name", t_team_name); break
                        if _imm_wd: break
                if not _imm_wd:
                    report_text = _som(t_name, scout_type, arena=arena_sel)
                    scout_reports.append({"warrior_name": t_name, "team_name": t_team_name,
                                          "arena": arena_sel,
                                          "scout_name": scout_name, "scout_type": scout_type,
                                          "scout_report": report_text})
                    continue
                _fh = _imm_wd.get("fight_history") or []
                _last = _fh[-1] if _fh else None
                _narrative = ""
                if _last:
                    _lt = _last.get("turn")
                    if _lt:
                        _tdir = os.path.join(_arena_dir, f"turn_{int(_lt):04d}")
                        if os.path.exists(_tdir):
                            for _rf in os.listdir(_tdir):
                                if not _rf.startswith("result_team"): continue
                                try:
                                    with open(os.path.join(_tdir, _rf), encoding="utf-8") as _f:
                                        _rd = json.load(_f)
                                except Exception:
                                    continue
                                for _bout in (_rd.get("bouts") or []):
                                    if _bout.get("warrior_name","").upper() == t_name.upper():
                                        _fid = str(_bout.get("fight_id",""))
                                        if _fid and _fid in (_rd.get("fight_logs") or {}):
                                            _narrative = _strip_training_block(
                                                _strip_strategy_table(_rd["fight_logs"][_fid]))
                                        break
                                if _narrative: break
                try:
                    _wobj = _WClass.from_dict(_imm_wd)
                except Exception:
                    _wobj = _imm_wd
                report_text = generate_scout_report(
                    _wobj, _last, _imm_tname,
                    scout_name=scout_name, scout_type=scout_type,
                    fight_narrative=_narrative,
                    is_debut_fight=(len(_fh) == 1),
                    arena=arena_sel,
                )
                scout_reports.append({
                    "warrior_name"    : t_name,
                    "team_name"       : _imm_tname,
                    "arena"           : arena_sel,
                    "wins"            : _imm_wd.get("wins", 0),
                    "losses"          : _imm_wd.get("losses", 0),
                    "kills"           : _imm_wd.get("kills", 0),
                    "max_hp"          : _imm_wd.get("max_hp", 0),
                    "height_in"       : _imm_wd.get("height_in", 0),
                    "weight_lbs"      : _imm_wd.get("weight_lbs", 0),
                    "total_fights"    : _imm_wd.get("total_fights", 0),
                    "armor"           : _imm_wd.get("armor") or "None",
                    "helm"            : _imm_wd.get("helm") or "None",
                    "primary_weapon"  : _imm_wd.get("primary_weapon") or "Open Hand",
                    "secondary_weapon": _imm_wd.get("secondary_weapon") or "Open Hand",
                    "backup_weapon"   : _imm_wd.get("backup_weapon"),
                    "scout_name"      : scout_name,
                    "scout_type"      : scout_type,
                    "scout_report"    : report_text,
                })
                continue
            # ── Normal arena scout ──────────────────────────────────────────────

            target_team = team_by_id.get(t_team_id)
            target_w    = target_team.warrior_by_name(t_name) if target_team else None
            fh          = (target_w.fight_history or []) if target_w else []
            last_entry  = fh[-1] if fh else None
            fought_this_turn = bool(target_w and last_entry and last_entry.get("turn") == turn_num)

            if not fought_this_turn:
                # Target died/retired/was swapped off the roster, or their team
                # didn't upload this turn - nothing for the scout to report.
                from scout_report import _sat_out_message
                report_text = _sat_out_message(t_name, scout_type, arena=arena_sel)
                scout_reports.append({
                    "warrior_name": t_name, "team_name": t_team_name,
                    "arena": arena_sel,
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
                arena=arena_sel,
            )
            scout_reports.append({
                "warrior_name"    : target_w.name,
                "team_name"       : t_team_name,
                "arena"           : arena_sel,
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
            if res.get("team_id") not in (None, ""):
                e["team_id"] = res["team_id"]
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
            evolve_ai_teams(ai_teams, ai_results, turn_num)
            print(f"  AI teams evolved and saved ({len(ai_results)} teams processed).")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  WARNING: AI team evolution failed: {e}")

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
        # Build live-team lookup so dead warriors from this turn are visible.
        # all_results["team"] is a snapshot taken at first-fight time and does
        # not reflect deaths that happened in later fights of the same turn.
        _live_team_by_id = {t.team_id: t for t in all_player_teams}
        # Remove any stale auto-carry files already in next-turn dir that have dead warriors.
        _next_turn_dir_path = _turn_dir(_next_turn)
        if os.path.isdir(_next_turn_dir_path):
            import glob as _acglob
            for _ac_path in _acglob.glob(os.path.join(_next_turn_dir_path, "upload_*.json")):
                try:
                    _ac_data = _load_json(_ac_path, None)
                    if not _ac_data or not _ac_data.get("auto_uploaded"):
                        continue
                    try:
                        _ac_tid = int(_ac_data.get("team_id", 0))
                    except (TypeError, ValueError):
                        continue
                    _ac_live = _live_team_by_id.get(_ac_tid)
                    if _ac_live and any(getattr(w, "is_dead", False) for w in (_ac_live.warriors or []) if w):
                        make_file_writable(_ac_path)
                        _ac_chk = _ac_path.replace(".json", ".checksum")
                        if os.path.exists(_ac_chk):
                            make_file_writable(_ac_chk)
                            os.remove(_ac_chk)
                        os.remove(_ac_path)
                        print(f"  [AUTO-CARRY] Removed stale carry file for team {_ac_tid} (dead warriors detected).")
                except Exception as _ace:
                    print(f"  [AUTO-CARRY] Warning: could not validate {_ac_path}: {_ace}")
        for _key, _res in all_results.items():
            if _key.startswith("ai_"):
                continue
            _team_dict = _res.get("team") or {}
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
            # Prefer live Team object for post-fight warrior state
            _live_team = _live_team_by_id.get(_int_tid)
            if _live_team:
                _warriors = [w.to_dict() if w is not None else None
                             for w in (_live_team.warriors or [])]
                _save_dict = _live_team.to_dict()
            else:
                _warriors = _team_dict.get("warriors") or []
                _save_dict = _team_dict
            if len(_warriors) != 5:
                continue
            if any((w is None) or w.get("is_dead") or w.get("is_retired") for w in _warriors):
                continue
            if not _save_dict.get("auto_upload_enabled", True):
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
                "team": _save_dict,
                "uploaded_at": f"{_auto_ts} (auto-carry)",
                "auto_upload_enabled": _save_dict.get("auto_upload_enabled", True),
                "auto_uploaded": True,
            })

    # ===================================================================
    # STEP 6: Generate newsletter
    # ===================================================================
    newsletter_text = ""
    try:
        from newsletter import generate_newsletter, _update_champion, _is_npc_team, _block_commentary_elite, _block_commentary_veteran
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
                _name_match = (_loser.name.upper() == _cur_champ.upper() and _loser_team.team_id == _cur_champ_tid)
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

        # If the warrior who just claimed the title via combat (RULE 1) is also
        # being promoted out of the normal arena this same turn, they cannot hold
        # the title -- they vacate immediately and the highest-recognition warrior
        # remaining in the normal arena is crowned instead.
        if _champ_beaten_by and promotion_events and champ_state.get("name"):
            _promoted_names = {e.get("warrior_name", "").upper() for e in promotion_events}
            if champ_state.get("name", "").upper() in _promoted_names:
                print(f"  [CHAMPION] {champ_state['name']} claimed the title but is promoted this turn -- title vacates.")
                _npc_team_names = {"The Monsters", "The Peasants"}
                # Exclude: all promoted warriors + the beaten champion (can't reclaim immediately)
                _excl = set(_promoted_names)
                if prev_champion_name:
                    _excl.add(prev_champion_name.upper())
                _vac_best_w, _vac_best_t, _vac_best_rec = None, None, -1
                _vac_fought = set()
                for _fb in fake_card:
                    _vac_fought.add((_fb.player_team.team_id, _fb.player_warrior.name))
                    _vac_fought.add((_fb.opponent_team.team_id, _fb.opponent.name))
                for _vt in all_player_teams:
                    if getattr(_vt, "team_name", "") in _npc_team_names:
                        continue
                    for _vw in (_vt.warriors or []):
                        if not _vw or getattr(_vw, "is_dead", False):
                            continue
                        if getattr(_vw, "current_arena", "normal") != "normal":
                            continue
                        if getattr(_vw, "name", "").upper() in _excl:
                            continue
                        if _vac_fought and (getattr(_vt, "team_id", 0), _vw.name) not in _vac_fought:
                            continue  # must have fought this turn
                        _vr = getattr(_vw, "recognition", 0)
                        if _vr > _vac_best_rec:
                            _vac_best_rec = _vr
                            _vac_best_w   = _vw
                            _vac_best_t   = _vt
                if _vac_best_w:
                    champ_state = {
                        "name":       _vac_best_w.name,
                        "warrior_id": getattr(_vac_best_w, "warrior_id", None),
                        "team_name":  getattr(_vac_best_t, "team_name", ""),
                        "team_id":    getattr(_vac_best_t, "team_id", 0),
                        "source":     "promotion_vacancy",
                    }
                    print(f"  [CHAMPION] Title awarded to {champ_state['name']} after promotion vacancy.")
                else:
                    champ_state = {}
                    print("  [CHAMPION] No eligible warrior found -- title is vacant.")
                is_new_champion = champ_state.get("name", "") != prev_champion_name
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

        # Record who holds the main-arena title this turn (feeds the newsletter's
        # Champion History section). Never allowed to block the newsletter.
        try:
            from save import record_champion_turn
            _ch_mgr = ""
            if champ_state.get("name"):
                for _ct in list(nl_teams) + list(all_player_teams):
                    if getattr(_ct, "team_id", None) == champ_state.get("team_id"):
                        _ch_mgr = getattr(_ct, "manager_name", "") or ""
                        break
            record_champion_turn(turn_num, champ_state, _ch_mgr)
        except Exception as _che:
            print(f"  WARNING: could not record champion history for turn {turn_num}: {_che}")

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
            promotion_pending=newly_eligible,
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

    # Reports are built after the newsletter is written, so the stats pages (e.g. Top 10
    # Teams, which reads the latest newsletter) show this turn, not the previous one.
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

    total_fights = sum(len(r["bouts"]) for r in all_results.values())
    print(f"\n  Turn {turn_num} complete - {len(all_results)} manager(s), {total_fights} fight(s)")
    print(f"  Expected fights: {total_warriors} warriors -> {total_warriors} fights")
    if total_fights == total_warriors:
        print("  [OK] PERFECT: Each warrior fought exactly once!")
    else:
        print(f"  [WARN] WARNING: Fight count mismatch! {total_fights} fights vs {total_warriors} warriors")

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
    This file is the source of truth for immortal turns -- normal-arena uploads never
    touch it, eliminating cross-arena contamination.
    """
    d = _immortal_team_dir(arena)
    os.makedirs(d, exist_ok=True)
    tid = team_dict.get("team_id", 0)

    # Keep only warriors relevant to this arena
    snapshot = {k: v for k, v in team_dict.items()
                if k not in ("warriors", "archived_warriors")}
    # A warrior who just took their final Soul Spire death is kept (grayed out in the
    # client) until the next turn or the manager's next upload clears them.
    snapshot["warriors"] = [
        w for w in (team_dict.get("warriors") or [])
        if isinstance(w, dict)
        and (not w.get("is_dead", False) or w.get("soul_spire_final_death"))
        and (w.get("current_arena") or "normal") == arena
    ]
    snapshot["archived_warriors"] = [
        w for w in (team_dict.get("archived_warriors") or [])
        if isinstance(w, dict)
        and (not w.get("is_dead", True) or w.get("soul_spire_final_death"))
        and (w.get("current_arena") or "normal") == arena
    ]

    fp = os.path.join(d, f"team_{tid:04d}.json")
    if os.path.exists(fp):
        make_file_writable(fp)
    with open(fp, "w", encoding="utf-8") as _f:
        json.dump(snapshot, _f, indent=2)
    return fp


def _add_warrior_to_immortal_team(arena: str, team_dict: dict, warrior_name: str):
    """Put one newly promoted/resurrected warrior into a team's arena file.

    If the team has no file for this arena yet, it is created from team_dict as
    usual. Otherwise only that warrior's entry is added (replacing any existing
    entry for the same warrior) -- the other warriors already in the arena keep
    their arena records, fight history and recognition, which the main team file
    does not carry.
    """
    fp = os.path.join(_immortal_team_dir(arena), f"team_{team_dict.get('team_id', 0):04d}.json")
    if not os.path.exists(fp):
        return _save_immortal_team(arena, team_dict)
    new_entry, new_section = None, "archived_warriors"
    for section in ("warriors", "archived_warriors"):
        for w in (team_dict.get(section) or []):
            if (isinstance(w, dict) and w.get("name") == warrior_name
                    and not w.get("is_dead", section == "archived_warriors")
                    and (w.get("current_arena") or "normal") == arena):
                new_entry, new_section = w, section
    if new_entry is None:
        return fp
    with open(fp, encoding="utf-8") as _f:
        snapshot = json.load(_f)
    wid = new_entry.get("warrior_id")
    def _same(w):
        if not isinstance(w, dict):
            return False
        if wid is not None and w.get("warrior_id") is not None:
            return w.get("warrior_id") == wid
        return w.get("name") == warrior_name
    for section in ("warriors", "archived_warriors"):
        snapshot[section] = [w for w in (snapshot.get(section) or []) if not _same(w)]
    snapshot.setdefault(new_section, []).append(new_entry)
    for k in ("team_name", "manager_name"):
        if team_dict.get(k):
            snapshot[k] = team_dict[k]
    _text = json.dumps(snapshot, indent=2)
    make_file_writable(fp)
    with open(fp, "w", encoding="utf-8") as _f:
        _f.write(_text)
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

    'Stuck' warriors have is_dead=True but current_arena=elite/veteran -- they were
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

            # If the arena was already seeded and we only repaired the main
            # file, skip re-seeding -- the arena-specific file already has the
            # authoritative post-turn stats and overwriting it with stale
            # main-file data would roll back the last turn's results.
            # Only seed if this team's arena file doesn't exist yet (new team).
            _team_arena_file = os.path.join(_tdir, f"team_{_t.team_id:04d}.json")
            if _already_seeded and os.path.exists(_team_arena_file):
                continue

            # Seed the arena-specific file for teams with arena warriors
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


def _seed_missing_immortal_warriors(arena: str) -> list:
    """Add promoted/transcended warriors to this arena's team files when they are missing.

    A warrior flagged for an immortal arena in the regular team files (current_arena set and
    is_promoted) has to exist in saves/{arena}/teams/ to fight there. Seeding normally
    happens when the promotion runs, but it can be skipped (immortal arenas off at the time,
    the warrior already moved to the archived list, a missed upload...), leaving the warrior
    on the manager's regular roster but absent from the Spire. Run before each Spire turn.
    Anyone already present in EITHER Spire is left alone, so nobody is added twice.
    Returns [(team_id, warrior_name)] for what was added.
    """
    from file_protection import load_json_protected
    from save import TEAMS_DIR
    import re as _re

    present = set()           # (team_id, warrior_id) and (team_id, name) in either Spire
    # Warriors permanently dead in the Soul Spire must never be seeded back in.
    present |= _soul_fallen_keys()
    for _a in ("elite", "veteran"):
        sources = list(_load_immortal_teams(_a)) + list(_load_immortal_uploads(_a).values())
        for td in sources:
            for sec in ("warriors", "archived_warriors"):
                for w in (td.get(sec) or []):
                    if isinstance(w, dict):
                        present.add((td.get("team_id"), w.get("warrior_id")))
                        present.add((td.get("team_id"), w.get("name")))

    def _append(path, team_stub, entry):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                td = json.load(f)
        else:
            td = dict(team_stub); td["warriors"] = []; td["archived_warriors"] = []
        td.setdefault("archived_warriors", []).append(entry)
        text = json.dumps(td, indent=2)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    added = []
    for fname in sorted(os.listdir(TEAMS_DIR)):
        if not _re.fullmatch(r"team_\d+\.json", fname):
            continue
        try:
            d = load_json_protected(os.path.join(TEAMS_DIR, fname), allow_tampered=True)
        except Exception:
            continue
        tid = d.get("team_id")
        for sec in ("warriors", "archived_warriors"):
            for w in (d.get(sec) or []):
                if (not isinstance(w, dict) or (w.get("current_arena") or "normal") != arena
                        or not w.get("is_promoted")):
                    continue
                if (tid, w.get("warrior_id")) in present or (tid, w.get("name")) in present:
                    continue
                entry = json.loads(json.dumps(w))
                entry["is_dead"] = False
                entry["hp"] = max(1, int(entry.get("max_hp") or entry.get("hp") or 100))
                entry["recognition"] = 0
                stub = {"team_id": tid, "team_name": d.get("team_name"), "manager_name": d.get("manager_name")}
                _append(os.path.join(_immortal_team_dir(arena), f"team_{int(tid):04d}.json"), stub, entry)
                up = os.path.join(_immortal_upload_dir(arena), f"team_{int(tid):04d}.json")
                if os.path.exists(up):
                    _append(up, stub, json.loads(json.dumps(entry)))
                present.add((tid, w.get("warrior_id"))); present.add((tid, w.get("name")))
                added.append((tid, w.get("name")))
                print(f"  [SPIRE SEED] Added {w.get('name')} (team {tid}) to the {arena} arena files.")
    return added


# ---------------------------------------------------------------------------
# SOUL SPIRE: death limit and ascension to the Elite Spire
# ---------------------------------------------------------------------------
# A warrior may die in the Soul Spire (arena key "veteran") only so many times.
# The death that reaches the limit is permanent. Deaths only count from the point
# this rule shipped (Warrior.soul_spire_deaths starts at 0 for everyone).
# A warrior who has fought enough Soul Spire fights AND meets the Elite criteria
# is restored and moved to the Elite Spire.
_SOUL_DEFAULT_MAX_DEATHS = 2
_SOUL_DEFAULT_MIN_FIGHTS_FOR_ELITE = 10


def _soul_rules(arena_cfg: dict) -> tuple:
    """Return (max_deaths, min_soul_fights_for_elite) from the veteran arena config."""
    rules = (arena_cfg or {}).get("arena_rules", {}) or {}
    try:
        max_deaths = max(1, int(rules.get("max_soul_deaths", _SOUL_DEFAULT_MAX_DEATHS)))
    except Exception:
        max_deaths = _SOUL_DEFAULT_MAX_DEATHS
    try:
        min_fights = max(0, int(rules.get("min_soul_fights_for_elite", _SOUL_DEFAULT_MIN_FIGHTS_FOR_ELITE)))
    except Exception:
        min_fights = _SOUL_DEFAULT_MIN_FIGHTS_FOR_ELITE
    return max_deaths, min_fights


def _soul_spire_fight_count(w) -> int:
    """Soul Spire fights a warrior has fought. Counts fights logged before this rule
    existed, because every Spire fight is already tagged arena='veteran'.
    Accepts a Warrior object or a warrior dict."""
    fh = (w.get("fight_history") if isinstance(w, dict) else getattr(w, "fight_history", None)) or []
    return sum(1 for f in fh if isinstance(f, dict) and f.get("arena") == "veteran")


_SERVER_OWNED_WARRIOR_FIELDS = ("soul_spire_deaths", "soul_spire_final_death")


def _keep_server_owned_fields(upload_td: dict, base_td: dict) -> None:
    """A client upload is applied over the saved Spire team at turn time. Fields only the
    server may change (the Soul Spire death counter and final-death flag) are copied back
    from the saved copy, so an out-of-date upload can never reset or revive anyone."""
    base = {}
    for sec in ("warriors", "archived_warriors"):
        for w in (base_td.get(sec) or []):
            if isinstance(w, dict):
                base[w.get("warrior_id") if w.get("warrior_id") is not None else w.get("name")] = w
                base[w.get("name")] = w
    for sec in ("warriors", "archived_warriors"):
        for w in (upload_td.get(sec) or []):
            if not isinstance(w, dict):
                continue
            src = base.get(w.get("warrior_id")) if w.get("warrior_id") is not None else None
            src = src or base.get(w.get("name"))
            if src is None:
                continue
            for k in _SERVER_OWNED_WARRIOR_FIELDS:
                if k in src:
                    w[k] = src[k]
                else:
                    w.pop(k, None)


def _soul_fallen_path() -> str:
    return os.path.join(BASE_DIR, "saves", "veteran", "fallen_warriors.json")


def _load_soul_fallen() -> list:
    """Warriors permanently dead in the Soul Spire. Kept so nothing (the Spire seeding
    step, a stale client upload) can bring them back."""
    try:
        with open(_soul_fallen_path(), encoding="utf-8") as _f:
            data = json.load(_f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _register_soul_fallen(team_id, warrior, turn_num: int, killed_by: str) -> None:
    entries = _load_soul_fallen()
    wid = getattr(warrior, "warrior_id", None)
    for e in entries:
        if e.get("team_id") == team_id and (
                (wid is not None and e.get("warrior_id") == wid) or e.get("name") == warrior.name):
            return
    entries.append({"team_id": team_id, "warrior_id": wid, "name": warrior.name,
                    "killed_by": killed_by, "turn": turn_num})
    os.makedirs(os.path.dirname(_soul_fallen_path()), exist_ok=True)
    with open(_soul_fallen_path(), "w", encoding="utf-8") as _f:
        json.dump(entries, _f, indent=2)


def _soul_fallen_keys() -> set:
    keys = set()
    for e in _load_soul_fallen():
        keys.add((e.get("team_id"), e.get("name")))
        if e.get("warrior_id") is not None:
            keys.add((e.get("team_id"), e.get("warrior_id")))
    return keys


def _strip_soul_fallen(team_dicts: list) -> int:
    """Remove permanently fallen Soul Spire warriors from loaded team dicts, in place."""
    keys = _soul_fallen_keys()
    if not keys:
        return 0
    removed = 0
    for td in team_dicts:
        tid = td.get("team_id")
        for sec in ("warriors", "archived_warriors"):
            kept = []
            for w in (td.get(sec) or []):
                if (isinstance(w, dict) and (w.get("current_arena") or "normal") == "veteran"
                        and ((tid, w.get("name")) in keys
                             or (w.get("warrior_id") is not None and (tid, w.get("warrior_id")) in keys))):
                    removed += 1
                    continue
                kept.append(w)
            if sec in td:
                td[sec] = kept
    return removed


def _update_crypt_entry(team_id, warrior, killed_by: str) -> bool:
    """Write a permanently fallen Soul Spire warrior's final career into the team's main
    file, so the Crypts tab shows the full record (regular arena plus Soul Spire).

    The warrior already sits in the main file as a snapshot taken when they transcended.
    That entry is replaced with the warrior's current data (record, skills, attributes,
    injuries and the full fight history, whose Spire fights carry arena='veteran').
    Returns True when the file was written.
    """
    from save import _team_filepath
    td = _load_team_file_dict(team_id)
    if not td:
        return False
    final = warrior.to_dict()
    final["is_dead"] = True
    final["killed_by"] = killed_by
    final["current_arena"] = "veteran"
    wid = getattr(warrior, "warrior_id", None)

    def _same(w):
        if not isinstance(w, dict):
            return False
        if wid is not None and w.get("warrior_id") is not None:
            return w.get("warrior_id") == wid
        return w.get("name") == warrior.name and (w.get("current_arena") or "normal") == "veteran"

    done = False
    for sec in ("archived_warriors", "warriors"):
        lst = td.get(sec) or []
        for i, w in enumerate(lst):
            if _same(w):
                merged = {**w, **final}
                merged["archived_killed_by"] = killed_by
                lst[i] = merged
                done = True
                break
        if done:
            break
    if not done:
        final["archived_killed_by"] = killed_by
        td.setdefault("archived_warriors", []).append(final)
    _save_json(_team_filepath(int(team_id)), td)
    return True


def _purge_soul_fallen_from_team_file(team_id) -> int:
    """Drop warriors flagged soul_spire_final_death from a team's Soul Spire file.
    Called when the manager uploads, which is when the grayed-out warrior goes away."""
    fp = os.path.join(_immortal_team_dir("veteran"), f"team_{int(team_id):04d}.json")
    if not os.path.exists(fp):
        return 0
    with open(fp, encoding="utf-8") as _f:
        td = json.load(_f)
    n = 0
    for sec in ("warriors", "archived_warriors"):
        kept = [w for w in (td.get(sec) or [])
                if not (isinstance(w, dict) and w.get("soul_spire_final_death"))]
        n += len(td.get(sec) or []) - len(kept)
        if sec in td:
            td[sec] = kept
    if n:
        make_file_writable(fp)
        with open(fp, "w", encoding="utf-8") as _f:
            json.dump(td, _f, indent=2)
    return n


def _promote_soul_to_elite(cfg: dict, arena_cfg: dict, turn_num: int) -> list:
    """Move eligible Soul Spire warriors to the Elite Spire. Runs after the Soul Spire
    team files are saved for the turn.

    Eligible = alive, fought at least min_soul_fights_for_elite Soul Spire fights, and
    meets the Elite criteria (lifetime record): promotion_criteria min_fights /
    min_win_rate / min_trains. On promotion the body is fully restored (all injuries
    cleared, HP to max), recognition reset, and the death counter cleared.
    Returns a list of event dicts for the newsletter and fight logs.
    """
    from warrior import Warrior, PermanentInjuries
    promo = cfg.get("promotion_criteria", {}) or {}
    min_fights   = int(promo.get("min_fights", 40))
    min_win_rate = float(promo.get("min_win_rate", 0.65))
    min_trains   = int(promo.get("min_trains", 45))
    _, min_soul  = _soul_rules(arena_cfg)

    events = []
    for td in _load_immortal_teams("veteran"):
        tid = int(td.get("team_id", 0))
        changed = False
        for section in ("warriors", "archived_warriors"):
            for wd in list(td.get(section) or []):
                if (not isinstance(wd, dict) or wd.get("is_dead", False)
                        or (wd.get("current_arena") or "normal") != "veteran"):
                    continue
                try:
                    w = Warrior.from_dict(wd)
                except Exception:
                    continue
                if _is_monster(w) or getattr(w, "is_retired", False):
                    continue
                if _soul_spire_fight_count(wd) < min_soul:
                    continue
                total = w.wins + w.losses
                if total < min_fights or (w.wins / total if total else 0.0) < min_win_rate:
                    continue
                if _warrior_total_trains(w) < min_trains:
                    continue

                # Restore the body and move the warrior to the Elite Spire.
                w.injuries = PermanentInjuries()
                w.soul_spire_injury_baseline = None
                w.soul_spire_deaths = 0
                try:
                    w.hp = max(1, int(getattr(w, "max_hp", 100)))
                except Exception:
                    pass
                w.is_dead = False
                w.current_arena = "elite"
                w.pending_promotion = None
                w.is_promoted = True
                w.recognition = 0
                new_wd = w.to_dict()

                td[section] = [x for x in (td.get(section) or []) if x is not wd]
                changed = True
                stub = {"team_id": tid, "team_name": td.get("team_name"),
                        "manager_name": td.get("manager_name"),
                        "warriors": [], "archived_warriors": [new_wd]}
                try:
                    _add_warrior_to_immortal_team("elite", stub, w.name)
                except Exception as _pe:
                    # Elite write failed: leave the warrior where they were.
                    td[section].append(wd)
                    print(f"  WARNING: could not move {w.name} to the Elite Spire: {_pe}")
                    continue
                events.append({
                    "type": "ascension", "warrior_name": w.name, "team_name": td.get("team_name"),
                    "team_id": tid, "manager_name": td.get("manager_name"),
                    "from_arena": "veteran", "to_arena": "elite",
                    "record": f"{w.wins}-{w.losses}-{w.kills}", "turn": turn_num,
                    "soul_fights": _soul_spire_fight_count(wd),
                })
                print(f"  ASCENDED: {w.name} ({td.get('team_name')}) -> THE ELITE SPIRE "
                      f"({w.wins}W/{w.losses}L, {_soul_spire_fight_count(wd)} Soul Spire fights)")
        if changed:
            _save_immortal_team("veteran", td)
    return events


def _run_immortal_turn(arena: str, request_password: str) -> dict:
    try:
        _n = int(_load_config().get("current_turn", 0))
    except Exception:
        _n = 0
    try:
        with _turn_log(f"turn_{_n:04d}_{arena}"):
            return _run_immortal_turn_inner(arena, request_password)
    finally:
        _unlock_downloads(arena)


def _run_immortal_turn_inner(arena: str, request_password: str) -> dict:
    """Run one turn for The Elite Spire ('elite') or THE SOUL SPIRE ('veteran') arena.

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

    if not cfg.get("immortal_arenas_enabled", False):
        return {"success": False, "error": "Immortal arenas are not yet enabled. Turn the feature on in the Admin panel (Maintenance tab)."}

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
        _lock_downloads(arena, arena_cfg.get("turn_counter", 0) + 1)
        with open(arena_cfg_path, "w", encoding="utf-8") as _f:
            json.dump(arena_cfg, _f, indent=2)

    # Arena-specific death chance multiplier (arena_rules.death_chance_multiplier).
    # Missing or invalid -> the combat.py default for this Spire (0.5 = half the normal chance).
    import combat as _combat_mod
    _dcm_default = _combat_mod.SPIRE_DEATH_CHANCE_MULT_DEFAULTS.get(arena, 1.0)
    try:
        death_chance_multiplier = max(0.0, float(
            (arena_cfg.get("arena_rules", {}) or {}).get("death_chance_multiplier", _dcm_default)))
    except (TypeError, ValueError):
        print(f"  WARNING: invalid death_chance_multiplier in {arena} config; using {_dcm_default}.")
        death_chance_multiplier = _dcm_default
    _combat_mod.SPIRE_DEATH_CHANCE_MULT[arena] = death_chance_multiplier
    print(f"  [{arena.upper()}] Death chance multiplier: {death_chance_multiplier}")

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
    # saves/{arena}/teams/ is the sole source of truth -- normal-arena uploads never
    # touch these files, so there is no cross-arena contamination.
    # If the client uploaded arena-specific data (saves/{arena}/uploads/), merge
    # those uploads over the base snapshot so the latest warrior stats are used.
    try:
        _seed_missing_immortal_warriors(arena)
    except Exception as _se:
        print(f"  WARNING: could not seed missing {arena} warriors: {_se}")
    _base_dicts  = _load_immortal_teams(arena)
    _upload_dicts = _load_immortal_uploads(arena)

    _team_dicts = []
    for _bd in _base_dicts:
        _tid = int(_bd.get("team_id", 0))
        # Prefer upload if present (client sent latest stats)
        _chosen = _upload_dicts.pop(_tid, _bd)
        if _chosen is not _bd:
            _keep_server_owned_fields(_chosen, _bd)
        _team_dicts.append(_chosen)
    # Any uploads for teams not yet in base (shouldn't happen, but include them)
    _team_dicts.extend(_upload_dicts.values())
    if arena == "veteran":
        # A stale client upload must not revive someone the gods already claimed.
        _gone = _strip_soul_fallen(_team_dicts)
        if _gone:
            print(f"  [SOUL SPIRE] Ignored {_gone} permanently fallen warrior(s) found in team data.")

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
            if _aw.get('run_this_turn', True) == False:
                print(f"  Skipping {_aw.get('name','?')} ({_t.team_name}) -- sitting out this turn")
                continue
            try:
                _w = Warrior.from_dict(_aw)
                _t.warriors.append(_w)
                _injected[_w.name] = (_t, _idx)
                print(f"  Injected archived warrior: {_w.name} ({_t.team_name})")
            except Exception as _ie:
                print(f"  WARNING: could not inject archived warrior "
                      f"{_aw.get('name', '?')}: {_ie}")

    _arena_display = {"elite": "THE ELITE SPIRE", "veteran": "THE SOUL SPIRE"}
    print(f"\n  ===== {_arena_display.get(arena, arena.upper())} -- TURN {turn_num} =====")
    print(f"  Warriors in this arena: {arena_warrior_count}")

    if arena_warrior_count == 0:
        with _lock:
            arena_cfg["turn_state"] = "open"
            with open(arena_cfg_path, "w", encoding="utf-8") as _f:
                json.dump(arena_cfg, _f, indent=2)
        return {"success": False, "error": f"No warriors in {arena} arena."}

    # Arena rule: no monster fights unless the arena allows them. A request left
    # over from the warrior's regular-arena career (or re-sent by a client upload)
    # is dropped, so the warrior goes through normal matching (peasants if unmatched).
    if not arena_cfg.get("arena_rules", {}).get("allow_monsters", False):
        for _t in all_teams:
            for _w in (_t.warriors or []):
                if _w and getattr(_w, "want_monster_fight", False):
                    print(f"  [ARENA RULES] {_w.name} ({_t.team_name}): monster fights not allowed "
                          f"in {arena} - request ignored")
                    _w.want_monster_fight = False

    # Arena rule: every warrior enters this arena with 0 recognition. A warrior with no
    # fights here yet must not carry recognition from its previous arena or from a
    # turn that was reset and re-run.
    for _t in all_teams:
        for _w in (_t.warriors or []):
            if not _w or (getattr(_w, "current_arena", None) or arena) != arena:
                continue
            if any((h.get("arena") or "normal") == arena for h in (getattr(_w, "fight_history", None) or [])):
                continue
            if getattr(_w, "recognition", 0):
                print(f"  [ARENA RULES] {_w.name} ({_t.team_name}): first {arena} fight - "
                      f"recognition {_w.recognition} reset to 0")
                _w.recognition = 0

    # --- Build fight card ---
    # Elite Spire: the reigning champion can be challenged (title fights), same
    # rules as the regular arena - only the top two tiers present may challenge.
    # (Not enabled for the Soul Spire.)
    _card_champion_state = {}
    if arena == "elite":
        from save import load_arena_champion_state as _lacs
        _card_champion_state = _lacs(arena) or {}
    global_card = build_global_fight_card(
        player_teams=all_teams,
        opponent_teams=[],
        champion_state=_card_champion_state,
        arena=arena,
    )
    print(f"  Fights scheduled: {len(global_card)}")

    # CRITICAL: Preserve original weapon loadout values (see matching block in
    # _run_turn for the full rationale) - combat can mutate primary/secondary/
    # backup weapon in-fight, and this arena's fight loop had no equivalent
    # protection against that leaking into the saved roster.
    weapon_loadout_backup = {}
    for team in all_teams:
        weapon_loadout_backup[team.team_id] = {}
        for w in team.warriors:
            if w and not isinstance(w, dict):
                weapon_loadout_backup[team.team_id][w.name] = (
                    w.primary_weapon, w.secondary_weapon, w.backup_weapon,
                )

    # --- Execute fights ---
    all_results: dict = {}   # team_id -> result dict
    fight_counter_local = 0
    _soul_max_deaths, _ = _soul_rules(arena_cfg)
    import combat as _combat_mod
    _combat_mod.SOUL_SPIRE_MAX_DEATHS = _soul_max_deaths   # lets combat skip the resurrection line on the final death
    _soul_final_deaths: list = []   # permanent Soul Spire deaths this turn (newsletter)
    _soul_ascensions:   list = []   # Soul -> Elite promotions this turn (newsletter)
    _fight_log_notes:   dict = {}   # fight id -> narrative lines appended to both fight logs
    from newsletter import _NPC_TEAM_NAMES as _NPC_NAMES_SOUL

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
                arena          = arena,
                # Needed for the challenge line before Minute 1 (same as the regular turn)
                challenger_name = getattr(fight, "challenger_name", None),
                bully_info      = getattr(fight, "bully_info", None),
            )
            fight.result = result
        except Exception as _fe:
            import traceback; traceback.print_exc()
            print(f"  ERROR running fight: {_fe}")
            continue

        pw_won  = result.winner is not None and result.winner.name == fight.player_warrior.name
        opp_won = not pw_won

        # In immortal arenas a kill is still a kill -- it just means resurrection next turn.
        _imm_killed = result.loser_died and pw_won   # player_warrior killed opponent
        _imm_slain  = result.loser_died and not pw_won  # player_warrior was killed
        # combat.py sets is_dead=True on the loser when they die; undo that here
        # so the warrior is saved back to the roster and returns next turn.
        if result.loser_died and result.loser is not None:
            result.loser.is_dead = False

            # Soul Spire death limit: the death that reaches the limit is permanent.
            # Peasants and monsters (fodder) are never counted.
            if arena == "veteran":
                _loser_obj  = fight.opponent        if pw_won else fight.player_warrior
                _loser_team = fight.opponent_team   if pw_won else fight.player_team
                _killer_obj = fight.player_warrior  if pw_won else fight.opponent
                if (getattr(_loser_team, "team_id", -1) >= 0
                        and getattr(_loser_team, "team_name", "") not in _NPC_NAMES_SOUL
                        and not _is_monster(_loser_obj)):
                    _loser_obj.soul_spire_deaths = int(getattr(_loser_obj, "soul_spire_deaths", 0) or 0) + 1
                    _left = _soul_max_deaths - _loser_obj.soul_spire_deaths
                    print(f"  [SOUL SPIRE] {_loser_obj.name} has died in the Soul Spire "
                          f"({_loser_obj.soul_spire_deaths}/{_soul_max_deaths}).")
                    if _left <= 0:
                        _loser_obj.is_dead = True
                        _loser_obj.soul_spire_final_death = True
                        result.loser.is_dead = True
                        _loser_obj.killed_by = _killer_obj.name
                        try:
                            _register_soul_fallen(_loser_team.team_id, _loser_obj, turn_num, _killer_obj.name)
                        except Exception as _re:
                            print(f"  WARNING: could not record fallen Soul Spire warrior: {_re}")
                        from narrative import soul_spire_final_death_line as _sfd_line
                        _final_line = _sfd_line(_loser_obj.name)
                        _fight_log_notes[fid] = "\n" + _final_line
                        _soul_final_deaths.append({
                            "line": _final_line,
                            "name": _loser_obj.name, "team": _loser_team.team_name,
                            "team_id": _loser_team.team_id, "manager": _loser_team.manager_name,
                            "killed_by": _killer_obj.name,
                            "obj": _loser_obj,   # record is read later, after this fight is tallied
                        })
                        print(f"  [SOUL SPIRE] {_loser_obj.name} is PERMANENTLY DEAD "
                              f"(slain by {_killer_obj.name}).")

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
                won=won, killed_opponent=(result.loser_died and won),
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
            "warrior_slain": _imm_slain, "opponent_slain": _imm_killed, "is_kill": _imm_killed,
            "fight_type": fight.fight_type,
            "primary_weapon": fight.player_warrior.primary_weapon or "Unknown",
            "challenger_name": fight.challenger_name,
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
            "warrior_slain": _imm_killed, "opponent_slain": _imm_slain, "is_kill": _imm_slain,
            "fight_type": fight.fight_type,
            "primary_weapon": fight.opponent.primary_weapon or "Unknown",
            "challenger_name": fight.challenger_name,
        })

        # Collect result for each team
        # For opponent team, use mirror narrative so their training shows actual skills
        _mirror_narrative = None
        for (tid, team_name, mgr_name, warrior, w_won, is_opponent) in [
            (fight.player_team.team_id,   fight.player_team.team_name,   fight.player_team.manager_name,   fight.player_warrior, pw_won, False),
            (fight.opponent_team.team_id, fight.opponent_team.team_name, fight.opponent_manager,           fight.opponent,       opp_won, True),
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
                "warrior_slain": (result.loser_died and not w_won),
                "opponent_slain": (result.loser_died and w_won),
                "fight_type": fight.fight_type,
            })
            # For opponent team, use mirror narrative so their warrior's training shows actual skills
            if is_opponent:
                if _mirror_narrative is None:
                    _mirror_narrative = _make_mirror_narrative(
                        result.narrative,
                        result.training_results,
                        fight.player_warrior.name,
                        fight.opponent.name,
                        fight.player_warrior,
                        fight.opponent,
                    )
                all_results[tid]["fight_logs"][str(fid)] = _mirror_narrative
            else:
                all_results[tid]["fight_logs"][str(fid)] = result.narrative

        # Final-death note goes at the end of the fight log for both sides.
        if fid in _fight_log_notes:
            for _nt in (fight.player_team.team_id, fight.opponent_team.team_id):
                _lg = all_results.get(_nt, {}).get("fight_logs", {})
                if str(fid) in _lg:
                    _lg[str(fid)] += _fight_log_notes[fid]

        outcome = "WON" if pw_won else "LOST"
        print(f"  Result: {fight.player_warrior.name} {outcome} in {result.minutes_elapsed} minutes")

    # --- Graveyard legacy files for Soul Spire final deaths ---
    # Written after the loop so the fatal fight and the final record are included.
    # Spire fights use per-turn fight ids that do not exist in saves/fights/ (a lookup
    # would return an unrelated regular-arena log), so their narrative lookup is skipped.
    if _soul_final_deaths:
        import copy as _copy
        from save import archive_warrior_history as _archive_wh
        for _fd in _soul_final_deaths:
            try:
                _proxy = _copy.copy(_fd["obj"])
                _proxy.fight_history = [
                    dict(_e, fight_id=None) if (_e.get("arena") or "normal") in ("veteran", "elite") else _e
                    for _e in (getattr(_fd["obj"], "fight_history", None) or [])
                ]
                _archive_wh(_fd["team"], _proxy)
                print(f"  Graveyard file written for {_fd['name']}.")
            except Exception as _ge:
                print(f"  WARNING: Could not write graveyard file for {_fd['name']}: {_ge}")
            try:
                if _update_crypt_entry(_fd["team_id"], _fd["obj"], _fd["killed_by"]):
                    print(f"  Crypt entry updated for {_fd['name']}.")
            except Exception as _ce:
                print(f"  WARNING: Could not update Crypt entry for {_fd['name']}: {_ce}")

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

    # CRITICAL: Restore original weapon loadout values before saving teams
    # (see matching block in _run_turn) - undo any in-fight primary/secondary/
    # backup weapon mutation left over from combat.
    for team in all_teams:
        team_id = team.team_id
        if team_id in weapon_loadout_backup:
            for w in team.warriors:
                if w and not isinstance(w, dict) and w.name in weapon_loadout_backup[team_id]:
                    w.primary_weapon, w.secondary_weapon, w.backup_weapon = \
                        weapon_loadout_backup[team_id][w.name]

    # --- Update arena champion (BEFORE saving teams so champion fields are included) ---
    from newsletter import _update_arena_champion
    from save import load_arena_champion_state, save_arena_champion_state
    prev_champ_state = load_arena_champion_state(arena)
    new_champ_state, is_new_champ = _update_arena_champion(
        all_teams, arena, prev_state=prev_champ_state, card=global_card)
    if new_champ_state:
        save_arena_champion_state(arena, new_champ_state)
        prev_champ_name = prev_champ_state.get("name")
        new_champ_name = new_champ_state.get("name")

        # Track champion changes on warriors
        if prev_champ_name and prev_champ_name != new_champ_name:
            # Previous champion is no longer champion - record their reign
            for team in all_teams:
                for w in (team.warriors or []):
                    if w.name == prev_champ_name and w.current_arena == arena:
                        # Record end of reign
                        reign_start = prev_champ_state.get("turn_start", turn_num - 1)
                        reign_length = turn_num - reign_start
                        if arena not in w.spire_champions:
                            w.spire_champions[arena] = []
                        w.spire_champions[arena].append({
                            "start_turn": reign_start,
                            "end_turn": turn_num - 1,
                            "defenses": w.current_champion_defenses,
                        })
                        w.current_champion_arena = None
                        w.current_champion_turns = 0
                        w.current_champion_defenses = 0

        # Elite/Soul fighters sit in archived_warriors (dicts), which the loops above skip
        for team in all_teams:
            for _ad in (getattr(team, "archived_warriors", None) or []):
                if not isinstance(_ad, dict) or (_ad.get("current_arena") or "normal") != arena:
                    continue
                if prev_champ_name and prev_champ_name != new_champ_name and _ad.get("name") == prev_champ_name:
                    _reign_start = prev_champ_state.get("turn_start", turn_num - 1)
                    _sc = _ad.get("spire_champions")
                    if not isinstance(_sc, dict):
                        _sc = {}
                    _sc.setdefault(arena, []).append({
                        "start_turn": _reign_start,
                        "end_turn": turn_num - 1,
                        "defenses": _ad.get("current_champion_defenses", 0),
                    })
                    _ad["spire_champions"] = _sc
                    _ad["current_champion_arena"] = None
                    _ad["current_champion_turns"] = 0
                    _ad["current_champion_defenses"] = 0
                elif new_champ_name and _ad.get("name") == new_champ_name:
                    if prev_champ_name == new_champ_name:
                        # Held the title through another turn
                        _ad["current_champion_turns"] = _ad.get("current_champion_turns", 0) + 1
                        _ad["current_champion_defenses"] = _ad.get("current_champion_defenses", 0) + 1
                    else:
                        _ad["current_champion_arena"] = arena
                        _ad["current_champion_turns"] = 1
                        _ad["current_champion_defenses"] = 0

        # New champion tracking
        if new_champ_name:
            _champ_found = False
            for team in all_teams:
                for w in (team.warriors or []):
                    if w.name == new_champ_name:
                        if w.current_arena == arena:
                            w.current_champion_arena = arena
                            w.current_champion_turns = 1
                            w.current_champion_defenses = 0
                            _champ_found = True
                        break
                if _champ_found:
                    break

        if is_new_champ or prev_champ_name != new_champ_name:
            print(f"  {_arena_display.get(arena, arena.upper())} Champion: {new_champ_name or '?'}")
            # Update champion state with turn info for tracking
            new_champ_state["turn_start"] = turn_num
            save_arena_champion_state(arena, new_champ_state)

    # --- Save updated stats back to arena-specific team files ---
    # Write to saves/{arena}/teams/ -- NOT the main saves/teams/ files.
    # This keeps the arena isolated: normal-arena uploads can never overwrite these.
    for team in all_teams:
        try:
            # Challenges last one turn only (as in the regular arena): clear them once
            # this turn's fights are done, so they can't carry over or be re-queued.
            team.clear_challenges()
            _save_immortal_team(arena, team.to_dict())
        except Exception as _se:
            print(f"  WARNING: could not save arena team {team.team_id}: {_se}")

    # --- Clear stale uploads so they don't override freshly-saved stats next turn ---
    # Uploads are client snapshots from before this turn ran; the saves/{arena}/teams/
    # files now contain the authoritative post-turn stats, so old uploads are obsolete.
    _upload_dir = _immortal_upload_dir(arena)
    if os.path.isdir(_upload_dir):
        for _uf in os.listdir(_upload_dir):
            if _uf.startswith("team_") and _uf.endswith(".json"):
                try:
                    os.remove(os.path.join(_upload_dir, _uf))
                except Exception as _ue:
                    print(f"  WARNING: could not clear stale upload {_uf}: {_ue}")

    # --- Soul Spire -> Elite Spire ascension (after the Soul team files are saved) ---
    if arena == "veteran":
        try:
            _soul_ascensions = _promote_soul_to_elite(cfg, arena_cfg, turn_num)
        except Exception as _ae:
            import traceback; traceback.print_exc()
            print(f"  WARNING: Soul -> Elite promotion step failed: {_ae}")
            _soul_ascensions = []
        if _soul_ascensions:
            from narrative import soul_to_elite_ascension_line as _asc_line
            for _ev in _soul_ascensions:
                _note = "\n" + _asc_line(_ev["warrior_name"])
                _ev["line"] = _note.strip()
                _last_fid = None
                _res_t = all_results.get(_ev["team_id"], {})
                for _b in _res_t.get("bouts", []):
                    if _b.get("warrior_name") == _ev["warrior_name"]:
                        _last_fid = str(_b.get("fight_id", ""))
                if _last_fid:
                    for _r in all_results.values():
                        if _last_fid in _r.get("fight_logs", {}):
                            _r["fight_logs"][_last_fid] += _note

    # --- Soul Spire Watch report (HTML, one file per turn in the reports folder) ---
    # Warriors on their last life and warriors close to the Elite Spire. Built from the
    # saved Soul Spire files, after promotions, so it shows who is still in the Spire.
    if arena == "veteran":
        try:
            import soul_spire_report as _ssr
            _watch_max, _watch_min = _soul_rules(arena_cfg)
            _watch_path = _ssr.write_report(
                _load_immortal_teams("veteran"),
                cfg.get("promotion_criteria", {}) or {},
                _watch_min, _watch_max, turn_num,
                os.path.join(LEAGUE_DIR, "reports"),
                ascended=_soul_ascensions, fallen=_soul_final_deaths,
                margins=(arena_cfg.get("arena_rules", {}) or {}).get("watch_margins"),
            )
            print(f"  Soul Spire Watch report written: {_watch_path}")
        except Exception as _we:
            print(f"  WARNING: could not write the Soul Spire Watch report: {_we}")

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

    # Peasants and Monsters are arena fodder: they never appear in standings and
    # never accumulate a record. Also prune any entry an earlier turn left behind.
    from newsletter import _NPC_TEAM_NAMES
    for _k in [k for k, v in standings.get("teams", {}).items()
               if v.get("team_name") in _NPC_TEAM_NAMES]:
        del standings["teams"][_k]

    for tid, res in all_results.items():
        if res.get("team_name") in _NPC_TEAM_NAMES:
            continue
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
                if bout.get("opponent_slain"):
                    ts["kills"] = ts.get("kills", 0) + 1
            else:
                ts["losses"] = ts.get("losses", 0) + 1
            wn = bout.get("warrior_name", "")
            ts.setdefault("warriors", {}).setdefault(wn, {"wins": 0, "losses": 0, "kills": 0})
            ws = ts["warriors"][wn]
            ws["wins"]   = bout.get("wins",   ws["wins"])
            ws["losses"] = bout.get("losses",  ws["losses"])
            ws["kills"]  = bout.get("kills",   ws.get("kills", 0))

    standings["turn"] = turn_num
    with open(standings_path, "w", encoding="utf-8") as _f:
        json.dump(standings, _f, indent=2)

    # --- Generate newsletter (formatted to match regular arena newsletter style) ---
    _disp = _arena_display.get(arena, arena.upper())
    _processed_date = time.strftime("%B %d, %Y")
    # ANSI styling -- identical codes to regular newsletter (newsletter.py)
    _H1   = "\033[1;999m"    # masthead title   (HDR_TITLE)
    _H2   = "\033[1;998m"    # masthead subtitle (HDR_SUBTITLE)
    _SEC  = "\033[1;31;98m"  # main section header  (HDR_RED_LG)
    _SSEC = "\033[1;31;99m"  # sub-section header   (HDR_RED)
    _BOLD = "\033[1;99m"     # table header bold    (HDR_BOLD)
    _RED  = "\033[1;31m"     # inline manager/team names
    _RST  = "\033[0m"        # reset
    _W    = 95               # newsletter width

    _SEP = "=" * _W
    _sep = "-" * _W

    # ── Build arena warrior list (used by multiple sections below) ────
    _completed = [f for f in global_card if f.result and f.result.winner]
    _draws      = [f for f in global_card if f.result and not f.result.winner]

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

    # ── MASTHEAD ─────────────────────────────────────────────────────
    nl_lines = [
        f"Date: {_processed_date}",
        f"{_H1}{_disp}{_RST}{_H2}Turn - {turn_num}{_RST}",
        "",
    ]

    # ── TEAM STANDINGS (career only -- no Last 5 Turns) ───────────────
    sorted_teams = sorted(
        ((k, v) for k, v in standings.get("teams", {}).items()
         if v.get("team_name") not in _NPC_TEAM_NAMES),
        key=lambda x: (
            x[1].get("wins", 0) / max(x[1].get("wins", 0) + x[1].get("losses", 0), 1),
            x[1].get("wins", 0),
            -x[1].get("losses", 0),
        ),
        reverse=True,
    )
    nl_lines.append(
        f"\n{_BOLD}{'The Top Teams':<15}{_RST}{_disp.upper()} CAREER STANDINGS"
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
        _pct = f"{100*_tw/(_tw+_tl):.1f}%" if (_tw + _tl) > 0 else "  --  "
        _mgr_raw = ts.get("manager_name", "?")
        _mgr_field = f"({_mgr_raw})"
        nl_lines.append(
            f"{rank:<5} {ts['team_name']:<32} {_RED}{_mgr_field:<24}{_RST}"
            f"  {_tw:>4} {_tl:>4} {_tk:>4}  {_pct:>6}"
        )
    nl_lines.append(_SEP)

    # ── TOP MANAGERS THIS TURN + CAREER ──────────────────────────────
    # This Turn: tally from global_card
    _mgr_turn = {}
    for _fight in _completed:
        _pw_won = _fight.result.winner.name == _fight.player_warrior.name
        _pm = getattr(_fight.player_team,  'manager_name', None) or '?'
        _om = getattr(_fight.opponent_team, 'manager_name', None) or '?'
        for _mn, _won, _tm in ((_pm, _pw_won, _fight.player_team),
                               (_om, not _pw_won, _fight.opponent_team)):
            if getattr(_tm, 'team_name', '') in _NPC_TEAM_NAMES:
                continue   # The Arena (peasants/monsters) is not a manager
            _mgr_turn.setdefault(_mn, {'w': 0, 'l': 0, 'k': 0})
            if _won:
                _mgr_turn[_mn]['w'] += 1
                if getattr(_fight.result, 'loser_died', False):
                    _mgr_turn[_mn]['k'] += 1
            else:
                _mgr_turn[_mn]['l'] += 1
    for _fight in _draws:
        for _mn, _tm in ((getattr(_fight.player_team, 'manager_name', None) or '?', _fight.player_team),
                         (getattr(_fight.opponent_team, 'manager_name', None) or '?', _fight.opponent_team)):
            if getattr(_tm, 'team_name', '') in _NPC_TEAM_NAMES:
                continue
            _mgr_turn.setdefault(_mn, {'w': 0, 'l': 0, 'k': 0})

    # Career: tally from each warrior's fight_history filtered by arena
    _mgr_career = {}
    for _w_obj, _t in _arena_warriors:
        _pm = _t.manager_name or '?'
        _fh = getattr(_w_obj, 'fight_history', []) or []
        _af = [f for f in _fh if (f.get('arena') or 'normal') == arena]
        _mgr_career.setdefault(_pm, {'cw': 0, 'cl': 0, 'ck': 0})
        _mgr_career[_pm]['cw'] += sum(1 for f in _af if f.get('result') == 'win')
        _mgr_career[_pm]['cl'] += sum(1 for f in _af if f.get('result') == 'loss')
        _mgr_career[_pm]['ck'] += sum(1 for f in _af if f.get('is_kill', False))

    _mgr_turn_list   = sorted(_mgr_turn.items(),
        key=lambda x: (-x[1]['w'] / max(1, x[1]['w'] + x[1]['l']), -x[1]['w']))
    _mgr_career_list = sorted(_mgr_career.items(),
        key=lambda x: (-x[1]['cw'] / max(1, x[1]['cw'] + x[1]['cl']), -x[1]['cw']))

    _mgr_SEP     = "=" * 140
    _mgr_lt      = f"The Top Managers This Turn ({turn_num})"
    _mgr_rt      = "The Top Managers Career"
    # Same column widths as newsletter.py: >= 2 spaces between 4-digit W/L/K totals.
    _NW, _WW, _LW, _KW, _PW, _TW = 34, 6, 6, 5, 7, 6
    _PANEL = 1 + _NW + _WW + _LW + _KW + _PW + _TW
    _mgr_SEP     = "=" * (_PANEL * 2 + 20)
    _mgr_HDR     = (f"{'  MANAGER':<{1 + _NW}}{'W':>{_WW}}{'L':>{_LW}}{'K':>{_KW}}{'%':>{_PW}}{'TOTAL':>{_TW}}"
                    f"{'':20}{'  MANAGER':<{1 + _NW}}{'W':>{_WW}}{'L':>{_LW}}{'K':>{_KW}}{'%':>{_PW}}{'TOTAL':>{_TW}}")
    nl_lines += [
        "",
        f"\n{_BOLD}{_mgr_lt:<{_PANEL + 1}}{_RST}{'':20}{_BOLD}{_mgr_rt}{_RST}",
        _mgr_HDR, _mgr_SEP,
    ]
    for _i in range(max(len(_mgr_turn_list), len(_mgr_career_list))):
        _left = ""
        if _i < len(_mgr_turn_list):
            _mn, _mr = _mgr_turn_list[_i]
            _pct = _mr['w'] / max(1, _mr['w'] + _mr['l']) * 100
            _left = (f" {_mn[:_NW - 1]:<{_NW}}{_mr['w']:>{_WW}}{_mr['l']:>{_LW}}{_mr['k']:>{_KW}}"
                     f"{_pct:>{_PW - 1}.1f}%{(_mr['w'] + _mr['l']):>{_TW}}")
        _right = ""
        if _i < len(_mgr_career_list):
            _mn, _mr = _mgr_career_list[_i]
            _pct = _mr['cw'] / max(1, _mr['cw'] + _mr['cl']) * 100
            _right = (f" {_mn[:_NW - 1]:<{_NW}}{_mr['cw']:>{_WW}}{_mr['cl']:>{_LW}}{_mr['ck']:>{_KW}}"
                      f"{_pct:>{_PW - 1}.1f}%{(_mr['cw'] + _mr['cl']):>{_TW}}")
        nl_lines.append(f"{_left:<{_PANEL}}{'':20}{_right}")

    # ── ARENA HAPPENINGS ─────────────────────────────────────────────
    from newsletter import _block_commentary_elite, _block_commentary_veteran
    _happenings_fn = _block_commentary_veteran if arena == "veteran" else _block_commentary_elite
    from ai_happenings import rewrite_happenings
    nl_lines.append(rewrite_happenings(_happenings_fn(
        global_card, all_teams, turn_num,
        arena_name=_disp, arena_warriors=_arena_warriors,
        prev_champion_name=prev_champ_state.get("name"),
        champion_name=(new_champ_state or {}).get("name"),
    ), _disp, turn_num))

    # ── TIER RANKINGS ────────────────────────────────────────────────
    # Same recognition thresholds as the regular arena, with Spire-specific names
    # and a champion tier on top (Elite ladder below; the Soul Spire overrides it). Internal tier keys (warrior.py TIER_*) used by
    # matchmaking are untouched; these are display names only.
    _tier_defs = [
        ("SOVEREIGN",  101, 101),   # champion - placed explicitly, never by score
        ("DEMIGODS",    87, 100),
        ("TITANS",      71,  86),
        ("SPIRELORDS",  56,  70),
        ("SPIREBLADES", 41,  55),
        ("SPIREGUARD",  26,  40),
        ("SPIREBORN",   13,  25),
        ("NEWBLOOD",     0,  12),
    ]
    if arena != "elite":
        # Soul Spire has its own ladder (display names only, as for the Elite Spire)
        _tier_defs = [
            ("WRAITHLORD",  101, 101),   # champion - placed explicitly, never by score
            ("DEATHLORDS",   87, 100),
            ("SOULREAVERS",  71,  86),
            ("SOULWARDENS",  56,  70),
            ("SOULBLADES",   41,  55),
            ("SOULGUARD",    26,  40),
            ("SOULBOUND",    13,  25),
            ("NEWDEAD",       0,  12),
        ]
    _lowest_tier = _tier_defs[-1][0]
    _champ_tier = _tier_defs[0][0]   # SOVEREIGN (Elite) / WRAITHLORD (Soul Spire)
    _sovereign_name = (new_champ_state or {}).get("name")
    _fought_this_turn = set()
    for _f in _completed + _draws:
        _fought_this_turn.add(_f.player_warrior.name)
        _fought_this_turn.add(_f.opponent.name)

    _tier_buckets = {_td[0]: [] for _td in _tier_defs}
    for _w_obj, _t in _arena_warriors:
        _rec = getattr(_w_obj, 'recognition', 0)
        _aw  = getattr(_w_obj, 'wins', 0) or 0
        _al  = getattr(_w_obj, 'losses', 0) or 0
        _ak  = getattr(_w_obj, 'kills', 0) or 0
        if _sovereign_name and _w_obj.name == _sovereign_name:
            _tier_name = _champ_tier
        else:
            _tier_name = next(
                (_td[0] for _td in _tier_defs if _td[1] <= _rec <= min(_td[2], 100)
                 and _td[0] != _champ_tier), _lowest_tier
            )
        _disp_wname = (_w_obj.name if _w_obj.name in _fought_this_turn
                       else f"- {_w_obj.name}")
        _tier_buckets[_tier_name].append({
            'display_name': _disp_wname, 'team': _t.team_name,
            'w': _aw, 'l': _al, 'k': _ak, 'rec': _rec,
        })

    _tier_COL_HDR = f"{'NAME':<30}{'W':>4}{'L':>4}{'K':>4}  {'REC':>3}  TEAM"
    _tier_SEP = "=" * 80
    nl_lines += ["", f"\n{_SEC}WARRIOR RANKINGS{_RST}"]
    _any_tier = False
    for _tier_name, _, _ in _tier_defs:
        _bucket = _tier_buckets[_tier_name]
        if not _bucket:
            continue
        _any_tier = True
        _bucket.sort(key=lambda x: (-x['rec'], -(x['w'] / max(1, x['w'] + x['l']))))
        nl_lines.append(f"\n{_SSEC}{_tier_name}{_RST}")
        nl_lines.append(_tier_COL_HDR)
        nl_lines.append(_tier_SEP)
        for _wd in _bucket:
            nl_lines.append(
                f"{_wd['display_name']:<30}{_wd['w']:>4}{_wd['l']:>4}{_wd['k']:>4}"
                f"  {_wd['rec']:>3}  {_wd['team']}"
            )
    if _any_tier:
        nl_lines.append("\n(-) denotes a warrior that did not fight this turn")

    # ── LAST TURN'S FIGHTS ───────────────────────────────────────────
    from newsletter import _death_verb, _fight_outcome_verb, _fight_style_word
    nl_lines += ["", f"\n{_SEC}LAST TURN'S FIGHTS{_RST}", _SEP]
    if _completed or _draws:
        nl_lines.append(f"{_SSEC}IMMORTAL ARENA MATCHUPS{_RST}")
        nl_lines.append(_SEP)
        for fight in _completed:
            _pw_won = fight.result.winner.name == fight.player_warrior.name
            _winner = fight.player_warrior if _pw_won else fight.opponent
            _loser  = fight.opponent       if _pw_won else fight.player_warrior
            _mins   = fight.result.minutes_elapsed
            _whp    = fight.result.winner_hp_pct
            _style  = _fight_style_word(_mins)
            if fight.result.loser_died:
                _verb = _death_verb(_mins, _whp)
            else:
                _verb = _fight_outcome_verb(_mins, _whp)
            _ftype = fight.fight_type
            if (arena == "elite" and _ftype == "challenge"
                    and prev_champ_state.get("name")
                    and prev_champ_state["name"] in (fight.player_warrior.name, fight.opponent.name)):
                _ftype = "championship"
            nl_lines.append(
                f"{_winner.name} {_verb} {_loser.name}"
                f" in a {_mins} minute {_style} {_ftype} bout."
            )
        for fight in _draws:
            nl_lines.append(
                f"{fight.player_warrior.name} vs {fight.opponent.name}"
                f" -- DRAW after {fight.result.minutes_elapsed} min."
            )
    else:
        nl_lines.append("  No bouts completed this turn.")

    # ── THE DEAD ─────────────────────────────────────────────────────
    # Immortals are resurrected, but who fell this turn is still worth reporting,
    # in the same section the regular arena uses. Each warrior is listed with their
    # overall career record (all arenas, including this turn's fight).
    from newsletter import _dead_section
    _spire_deaths = []
    for fight in _completed:
        if not getattr(fight.result, 'loser_died', False):
            continue
        _pw_won = fight.result.winner.name == fight.player_warrior.name
        _dead_w   = fight.opponent      if _pw_won else fight.player_warrior
        _dead_t   = fight.opponent_team if _pw_won else fight.player_team
        _killer_w = fight.player_warrior if _pw_won else fight.opponent
        if getattr(_dead_t, 'team_name', '') in _NPC_TEAM_NAMES:
            continue   # peasants and monsters never appear in the dead list
        _dw, _dl, _dk = (getattr(_dead_w, 'wins', 0) or 0, getattr(_dead_w, 'losses', 0) or 0,
                         getattr(_dead_w, 'kills', 0) or 0)
        _spire_deaths.append({
            'name': _dead_w.name, 'team': getattr(_dead_t, 'team_name', '?'),
            'w': _dw, 'l': _dl, 'k': _dk, 'killed_by': _killer_w.name,
        })
    _dead_text = _dead_section(_spire_deaths, turn_num)
    if _dead_text:
        nl_lines += ["", _dead_text]

    # ── THE GODS' JUDGMENT (Soul Spire only) ─────────────────────────
    if _soul_ascensions or _soul_final_deaths:
        nl_lines += ["", f"\n{_SEC}THE GODS' JUDGMENT{_RST}", _SEP]
        for _ev in _soul_ascensions:
            nl_lines += [
                f"{_SSEC}ASCENDED TO THE ELITE SPIRE{_RST}",
                f"{_ev['warrior_name']} ({_ev['team_name']}) -- {_ev['record']}",
                _ev.get("line", ""), "",
            ]
        for _fd in _soul_final_deaths:
            _o = _fd.get("obj")
            _rec = f"{_o.wins}-{_o.losses}-{_o.kills}" if _o is not None else "?"
            nl_lines += [
                f"{_SSEC}CLAIMED BY THE LAND OF THE DEAD{_RST}",
                f"{_fd['name']} ({_fd['team']}) -- {_rec}, slain by {_fd['killed_by']}",
                _fd["line"], "",
            ]

    # ── BATTLE REPORT ────────────────────────────────────────────────
    from collections import defaultdict as _dd
    _rf = _dd(int); _rw = _dd(int); _rl = _dd(int); _rk = _dd(int)
    for _w_obj, _t in _arena_warriors:
        _race_n = _w_obj.race.name if hasattr(_w_obj.race, 'name') else 'Unknown'
        _fh     = getattr(_w_obj, 'fight_history', []) or []
        _af     = [f for f in _fh if (f.get('arena') or 'normal') == arena]
        _rf[_race_n] += len(_af)
        _rw[_race_n] += sum(1 for f in _af if f.get('result') == 'win')
        _rl[_race_n] += sum(1 for f in _af if f.get('result') == 'loss')
        _rk[_race_n] += sum(1 for f in _af if f.get('is_kill', False))
    _races = sorted(_rf.keys(), key=lambda r: -_rf[r])
    _br_sep = "=" * 75
    nl_lines += [
        "",
        f"\n                      {_SEC}BATTLE REPORT{_RST}\n",
        f"{'MOST POPULAR RACE':<25}  {'RECORD IN ' + _disp.upper():<38}",
        _br_sep,
        f"{'|RACE':<17}{'FIGHTS':>8}  {'RACE':<18}{'W':>5} - {'L':>4} - {'K':>4}  {'PERCENT':>7}|",
        _br_sep,
    ]
    for _race in _races:
        _tw = _rw[_race]; _tl = _rl[_race]; _tk = _rk[_race]
        _pct_r = int(_tw / max(1, _tw + _tl) * 100)
        nl_lines.append(
            f"|{_race:<16}{_rf[_race]:>8}  {_race:<18}{_tw:>5} - {_tl:>4} - {_tk:>4}  {_pct_r:>6}%|"
        )
    nl_lines.append(_br_sep)

    # ── TOP WARRIOR BY MANAGER ────────────────────────────────────────
    _mgr_best = {}
    for _w_obj, _t in _arena_warriors:
        _pm  = _t.manager_name or '?'
        _fh  = getattr(_w_obj, 'fight_history', []) or []
        _af  = [f for f in _fh if (f.get('arena') or 'normal') == arena]
        _aw  = sum(1 for f in _af if f.get('result') == 'win')
        _al  = sum(1 for f in _af if f.get('result') == 'loss')
        _ak  = sum(1 for f in _af if f.get('is_kill', False))
        _sc  = _aw * 3 + _ak * 2 - _al
        if _pm not in _mgr_best or _sc > _mgr_best[_pm]['score']:
            _mgr_best[_pm] = {
                'warrior': _w_obj.name, 'w': _aw, 'l': _al, 'k': _ak,
                'score': _sc, 'team': _t.team_name,
            }
    if _mgr_best:
        nl_lines += [
            "",
            f"\n\n                      {_SEC}TOP WARRIOR by MANAGER{_RST}\n",
            f"{'MANAGER':<22}{'WARRIOR':<30}{'W':>4}{'L':>4}{'K':>3}  TEAM NAME",
            "=" * 85,
        ]
        for _pm in sorted(_mgr_best.keys()):
            _mb = _mgr_best[_pm]
            nl_lines.append(
                f"{_pm:<22}{_mb['warrior']:<30}{_mb['w']:>4}{_mb['l']:>4}{_mb['k']:>3}"
                f"  {_mb['team']}"
            )

    # ── HALL OF CHAMPIONS ────────────────────────────────────────
    _current_champ = new_champ_state.get("name") if new_champ_state else None
    if _current_champ:
        # Show previous champions from this turn's history
        _past_champs = []
        for _t in all_teams:
            for _w in (_t.warriors or []):
                if getattr(_w, 'spire_champions', {}).get(arena):
                    for _reign in _w.spire_champions[arena]:
                        _past_champs.append({
                            'warrior': _w.name,
                            'team': _t.team_name,
                            'start': _reign.get('start_turn'),
                            'end': _reign.get('end_turn'),
                            'defenses': _reign.get('defenses', 0),
                        })
            for _ad in (getattr(_t, 'archived_warriors', None) or []):
                if not isinstance(_ad, dict):
                    continue
                _sc = _ad.get('spire_champions')
                if isinstance(_sc, dict):
                    for _reign in (_sc.get(arena) or []):
                        _past_champs.append({
                            'warrior': _ad.get('name', '?'),
                            'team': _t.team_name,
                            'start': _reign.get('start_turn') or 0,
                            'end': _reign.get('end_turn') or 0,
                            'defenses': _reign.get('defenses', 0),
                        })

        # Both Spires show their champion as the top tier row (Sovereign / Wraithlord),
        # so the Hall of Champions appears only once there is a past reign to list.
        _show_current = False
        if _show_current or _past_champs:
            nl_lines += ["", f"\n{_SEC}HALL OF CHAMPIONS{_RST}", _SEP]
        if _show_current:
            nl_lines += [
                f"\n{_SSEC}Current Champion{_RST}",
                f"{_current_champ} ({new_champ_state.get('team_name', '?')})"
                f" — {new_champ_state.get('recognition', 0)} recognition",
            ]

        if _past_champs:
            nl_lines += ["", f"{_SSEC}Previous Reigns{_RST}"]
            _past_champs.sort(key=lambda x: -x['end'])
            for _pc in _past_champs[:5]:  # Show last 5 reigns
                _reign_length = _pc['end'] - _pc['start'] + 1
                nl_lines.append(
                    f"{_pc['warrior']} ({_pc['team']}) — "
                    f"Turns {_pc['start']}-{_pc['end']} ({_reign_length}T), {_pc['defenses']} defenses"
                )

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
    print(f"\n  {_disp} Turn {turn_num} complete -- {len(all_results)} team(s), {total_bouts} bout(s).")
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


def _announcements_admin_section():
    """Generate the announcements management section for the admin panel."""
    announcements = _load_announcements()
    rows = ""
    for ann in announcements:
        is_active = "✓" if ann.get("active", True) else "✗"
        rows += f"""<tr>
            <td style="word-break:break-word">{ann.get('title', '')}</td>
            <td style="word-break:break-word;max-width:200px">{ann.get('message', '')[:100]}...</td>
            <td style="font-size:11px;color:#666">{ann.get('id', '')[:16]}...</td>
            <td style="text-align:center">{is_active}</td>
            <td style="text-align:center">
                <button style="font-size:10px;padding:2px 6px" onclick="editAnnouncement('{ann.get('id', '')}')">Edit</button>
                <button style="font-size:10px;padding:2px 6px" onclick="deleteAnnouncement('{ann.get('id', '')}')">Del</button>
            </td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="5" style="color:#888;text-align:center">No announcements</td></tr>'

    return f"""
    <h3>Manage Announcements</h3>
    <div style="margin-bottom:12px">
        <label>Title: <input type="text" id="ann-title" style="width:200px;padding:4px;border:1px solid #999" placeholder="e.g., New Client Version"></label><br>
        <label style="display:block;margin-top:6px">Message: <textarea id="ann-message" style="width:100%;height:60px;padding:4px;border:1px solid #999;font-family:monospace;font-size:11px" placeholder="Announcement text"></textarea></label><br>
        <label style="display:block;margin-top:6px">Download URL (optional): <input type="text" id="ann-url" style="width:100%;padding:4px;border:1px solid #999" placeholder="https://..."></label><br>
        <button onclick="createAnnouncement()" style="margin-top:6px">Create Announcement</button>
        <span id="ann-msg" style="display:none;margin-left:10px;font-size:11px"></span>
    </div>

    <h3>Current Announcements</h3>
    <table style="font-size:11px;width:100%">
        <thead>
            <tr>
                <th>Title</th>
                <th>Message Preview</th>
                <th>ID</th>
                <th>Active</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>

    <div id="edit-modal" style="display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:#fff;border:3px solid #000;padding:16px;z-index:1000;min-width:400px;max-width:600px;box-shadow:0 0 20px rgba(0,0,0,0.5)">
        <h3 style="margin-top:0">Edit Announcement</h3>
        <label>Title: <input type="text" id="edit-title" style="width:100%;padding:4px;border:1px solid #999;box-sizing:border-box"></label><br>
        <label style="display:block;margin-top:6px">Message: <textarea id="edit-message" style="width:100%;height:60px;padding:4px;border:1px solid #999;font-family:monospace;font-size:11px;box-sizing:border-box"></textarea></label><br>
        <label style="display:block;margin-top:6px">URL: <input type="text" id="edit-url" style="width:100%;padding:4px;border:1px solid #999;box-sizing:border-box"></label><br>
        <label style="display:block;margin-top:6px"><input type="checkbox" id="edit-active"> Active</label><br>
        <button onclick="saveAnnouncement()" style="margin-top:10px">Save Changes</button>
        <button onclick="closeEditModal()" style="margin-top:10px">Cancel</button>
    </div>

    <div id="edit-overlay" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.3);z-index:999" onclick="closeEditModal()"></div>
    """

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
    mgr_running_counts = {}
    mgr_sitting_out_counts = {}
    mgr_upload_times = {}
    for key, udata in uploads.items():
        uid = udata.get("manager_id", key.split("_team")[0])
        if udata.get("auto_uploaded"):
            mgr_auto_counts[uid] = mgr_auto_counts.get(uid, 0) + 1
        else:
            mgr_manual_counts[uid] = mgr_manual_counts.get(uid, 0) + 1

        # Check if team is marked to run this turn
        is_running = udata.get("team", {}).get("auto_upload_enabled", True)
        if is_running:
            mgr_running_counts[uid] = mgr_running_counts.get(uid, 0) + 1
        else:
            mgr_sitting_out_counts[uid] = mgr_sitting_out_counts.get(uid, 0) + 1

        mgr_upload_times[uid] = udata.get("uploaded_at","?")
    mgr_upload_counts = {m: mgr_manual_counts.get(m,0) + mgr_auto_counts.get(m,0)
                         for m in set(mgr_manual_counts) | set(mgr_auto_counts)}
    urows_uploaded = ""
    urows_not_uploaded = ""
    uploaded_count = 0
    not_uploaded_count = 0
    for mid, mgr in managers.items():
        manual = mgr_manual_counts.get(mid, 0)
        auto   = mgr_auto_counts.get(mid, 0)
        total  = manual + auto
        running = mgr_running_counts.get(mid, 0)
        sitting_out = mgr_sitting_out_counts.get(mid, 0)
        mname  = mgr['manager_name']
        mid_cell = f"<span style='color:#888;font-size:10px;margin-left:5px'>(ID: {mid})</span>"
        if total:
            parts = []
            if manual: parts.append(f"{manual} manual")
            if auto:   parts.append(f"{auto} auto-carry")
            status_parts = []
            if running: status_parts.append(f"{running} running")
            if sitting_out: status_parts.append(f"{sitting_out} sitting out")
            badge = (f"<b style='color:#060'>✓ {total} team(s) uploaded "
                     f"({', '.join(parts)}) — {', '.join(status_parts)} -- {mgr_upload_times.get(mid,'')}</b>")
            urows_uploaded += f"<tr><td>{mname}{mid_cell}</td><td>{badge}</td></tr>"
            uploaded_count += 1
        else:
            badge = "<span style='color:#800'>✗ not uploaded</span>"
            urows_not_uploaded += f"<tr><td>{mname}{mid_cell}</td><td>{badge}</td></tr>"
            not_uploaded_count += 1
    if not urows_uploaded and not urows_not_uploaded:
        urows_uploaded = "<tr><td colspan=2 style='color:#888'>No managers registered yet</td></tr>"
    if not urows_uploaded:
        urows_uploaded = "<tr><td colspan=2 style='color:#888'>No managers have uploaded yet</td></tr>"
    if not urows_not_uploaded:
        urows_not_uploaded = "<tr><td colspan=2 style='color:#060'>All managers have uploaded!</td></tr>"
    # AI count
    try:
        from ai_league_teams import load_ai_teams as _lat
        ai_count = len(_lat() or [])
    except Exception:
        ai_count = 0
    ai_row = ""
    if ai_count and cfg.get("ai_teams_enabled", True):
        ai_row = f"<tr><td colspan=2 style='color:#555;font-style:italic'>+ {ai_count} AI teams (auto-included)</td></tr>"
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
        # Count immortal arena warriors/teams from the arena-specific team files
        # (saves/{arena}/teams/), which are the authoritative source for each arena.
        # The normal-arena files (saves/teams/) only know about warriors that
        # transcended through the normal arena and miss those added via migration
        # or direct upload.
        def _imm_count(arena):
            _tds = _load_immortal_teams(arena)
            def _alive(w):
                if isinstance(w, dict):
                    return not w.get("is_dead", True)
                return w and not getattr(w, "is_dead", True)
            wcount = sum(
                1 for _td in _tds
                for _w in (_td.get("warriors") or []) + (_td.get("archived_warriors") or [])
                if _w and _alive(_w))
            tcount = len({_td.get("team_id") for _td in _tds if any(
                _alive(_w)
                for _w in (_td.get("warriors") or []) + (_td.get("archived_warriors") or [])
                if _w)})
            return wcount, tcount
        elite_warrior_count, elite_team_count = _imm_count("elite")
        vet_warrior_count,   vet_team_count   = _imm_count("veteran")
        # Still need normal-arena teams for pending promotion count
        from save import load_all_teams as _lat
        _all_t = _lat()
        # Promotion pending count
        promo_pending_count = sum(
            1 for _t in _all_t for _w in (_t.active_warriors or [])
            if _w and getattr(_w, "pending_promotion", None))
    except Exception:
        elite_warrior_count = vet_warrior_count = 0
        elite_team_count = vet_team_count = 0
        promo_pending_count = 0

    # Spire upload status: a team with a file in saves/{arena}/uploads/ was uploaded
    # manually this turn. A team with no file runs on auto-run from its saved copy.
    import html as _html
    from datetime import datetime as _dt
    _spire_upload_html = ""
    try:
        for _spire_arena, _spire_label in (("elite", "THE ELITE SPIRE"), ("veteran", "THE SOUL SPIRE")):
            _spire_uploads = _load_immortal_uploads(_spire_arena)
            _spire_teams = [
                _std for _std in _load_immortal_teams(_spire_arena)
                if any(isinstance(_sw, dict) and not _sw.get("is_dead", True)
                       for _sw in (_std.get("warriors") or []) + (_std.get("archived_warriors") or []))
            ]
            _n_manual = sum(1 for _std in _spire_teams if int(_std.get("team_id", 0)) in _spire_uploads)
            _n_auto = len(_spire_teams) - _n_manual
            _upload_dir = _immortal_upload_dir(_spire_arena)
            _mgr_groups = {}
            for _std in _spire_teams:
                _mgr_groups.setdefault(str(_std.get("manager_name", "?")), []).append(_std)
            _mgr_html = ""
            for _mname in sorted(_mgr_groups, key=str.lower):
                _mteams = sorted(_mgr_groups[_mname], key=lambda _t: str(_t.get("team_name", "")).lower())
                _up_times = [
                    os.path.getmtime(os.path.join(_upload_dir, f"team_{int(_t.get('team_id', 0)):04d}.json"))
                    for _t in _mteams if int(_t.get("team_id", 0)) in _spire_uploads
                ]
                if _up_times:
                    _when = _dt.fromtimestamp(max(_up_times)).strftime("%Y-%m-%d %H:%M")
                    _when_html = f"<b style='color:#060'>uploaded {_when}</b>"
                else:
                    _when_html = "<span style='color:#336'>auto-run only</span>"
                _rows = ""
                for _std in _mteams:
                    _is_manual = int(_std.get("team_id", 0)) in _spire_uploads
                    _badge = ("<b style='color:#060'>✓ manual upload</b>" if _is_manual
                              else "<span style='color:#336'>auto-run</span>")
                    _rows += (f"<tr><td>{_html.escape(str(_std.get('team_name', '?')))}</td>"
                              f"<td>{_badge}</td></tr>")
                _mgr_html += (
                    f"<details style='border-bottom:1px solid #dde;padding:4px 0'>"
                    f"<summary style='cursor:pointer;font-size:12px'><b>{_html.escape(_mname)}</b>"
                    f"<span style='font-size:11px;margin-left:10px'>{_when_html}</span></summary>"
                    f"<table style='width:100%;font-size:11px;border-collapse:collapse;margin:4px 0 2px'>"
                    f"<tr style='background:#eee'><th style='text-align:left;padding:3px 6px'>Team</th>"
                    f"<th style='text-align:left;padding:3px 6px'>Status</th></tr>"
                    f"{_rows}</table></details>")
            if not _mgr_html:
                _mgr_html = "<div style='font-size:11px;color:#888'>No teams in this arena</div>"
            _spire_upload_html += (
                f"<div style='flex:1;min-width:300px'>"
                f"<b style='font-size:12px'>{_spire_label}</b> "
                f"<span style='font-size:11px;color:#555'>{_n_manual} manual upload, {_n_auto} auto-run</span>"
                f"<div style='margin-top:4px'>{_mgr_html}</div></div>")
    except Exception as _sue:
        print(f"  WARNING: could not build Spire upload status: {_sue}")
        _spire_upload_html = "<span style='font-size:11px;color:#800'>Could not load Spire upload status.</span>"

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
  <h3>Upload Status -- Turn {turn}</h3>
  <div style="display:flex;gap:0;margin-bottom:6px;border-bottom:2px solid #999;">
   <button id="upld-tab-uploaded" onclick="showUploadTab('uploaded')"
    style="padding:4px 14px;font-size:11px;border:1px solid #999;border-bottom:none;background:#e0ddd6;cursor:pointer;border-radius:3px 3px 0 0;font-weight:bold;">
    ✓ Uploaded ({uploaded_count})</button>
   <button id="upld-tab-missing" onclick="showUploadTab('missing')"
    style="padding:4px 14px;font-size:11px;border:1px solid #ccc;border-bottom:none;background:#f5f5f5;cursor:pointer;border-radius:3px 3px 0 0;margin-left:3px;">
    ✗ Not Uploaded ({not_uploaded_count})</button>
  </div>
  <div id="upld-pane-uploaded">
   <table style="width:100%;font-size:11px;border-collapse:collapse;">
    <tr style="background:#eee;"><th style="text-align:left;padding:3px 6px;">Manager</th><th style="text-align:left;padding:3px 6px;">Status</th></tr>
    {urows_uploaded}{ai_row}
   </table>
  </div>
  <div id="upld-pane-missing" style="display:none;">
   <table style="width:100%;font-size:11px;border-collapse:collapse;">
    <tr style="background:#eee;"><th style="text-align:left;padding:3px 6px;">Manager</th><th style="text-align:left;padding:3px 6px;">Status</th></tr>
    {urows_not_uploaded}
   </table>
  </div>
  <script>
  function showUploadTab(tab) {{
   document.getElementById('upld-pane-uploaded').style.display = tab==='uploaded' ? '' : 'none';
   document.getElementById('upld-pane-missing').style.display  = tab==='missing'  ? '' : 'none';
   document.getElementById('upld-tab-uploaded').style.background = tab==='uploaded' ? '#e0ddd6' : '#f5f5f5';
   document.getElementById('upld-tab-uploaded').style.fontWeight = tab==='uploaded' ? 'bold' : 'normal';
   document.getElementById('upld-tab-missing').style.background  = tab==='missing'  ? '#e0ddd6' : '#f5f5f5';
   document.getElementById('upld-tab-missing').style.fontWeight  = tab==='missing'  ? 'bold' : 'normal';
   document.getElementById('upld-tab-uploaded').style.borderColor = tab==='uploaded' ? '#999' : '#ccc';
   document.getElementById('upld-tab-missing').style.borderColor  = tab==='missing'  ? '#999' : '#ccc';
  }}
  </script>
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
  <h3>🏟️ Warriors by Arena</h3>
  <p style="font-size:11px;margin:0 0 8px;color:#555">
   Active warriors broken down by arena -- Normal, Elite Spire, and Soul Spire.
  </p>
  <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;">
   <button onclick="loadWarriorsByArena()">🏟️ Generate Arena Breakdown</button>
   <button onclick="exportArenaBreakdownCSV()" id="arena-csv-btn" disabled style="padding:2px 8px;font-size:11px">CSV Export</button>
  </div>
  <div id="warriors-by-arena-container" style="border:1px solid #ccc;height:400px;overflow-y:auto;background:#f9f9f9;font-size:10px;font-family:monospace;">
   <div style="padding:8px;color:#999;">Click "Generate Arena Breakdown" to load...</div>
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
 <div class="panel" style="min-width:400px;max-width:900px">
  <h3>🧠 AI Learning Report</h3>
  <p style="font-size:11px;margin:0 0 8px;color:#555">
   What the AI managers have learned from their fights: win% by archetype, strategy package, weapon and armor.
   hpMrg / endMrg = average HP / endurance left versus the opponent at the end (positive = ahead); kd = knockdown difference.
   Older fights fade a little each turn.
  </p>
  <button onclick="showAILearningReport()">🧠 Generate AI Learning Report</button>
  <div id="ai-learning-container" style="margin-top:8px;border:1px solid #ccc;height:420px;overflow:auto;background:#f9f9f9;font-size:11px;font-family:monospace;white-space:pre;padding:6px">
   <div style="color:#999">Click "Generate AI Learning Report" to load...</div>
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
 <div style="margin-top:8px">
  <button onclick="validateWarriorIds()" title="Writes Turn_XX_Warrior_Registry.md to the game folder">🆔 Generate Warrior Registry</button>
  <button onclick="loadSpireSittingOut()" title="Lists Elite Spire and Soul Spire warriors set to sit out the next turn">🚫 Spire Sit-Outs</button>
  <button onclick="generateSpireRegistry()" title="Writes Turn_XX_Spire_Warrior_Registry.md (Elite Spire and Soul Spire) to the game folder">🏛 Generate Spire Registry</button>
 </div>
 <div id="spire-sitout-results" style="display:none;margin-top:8px;border:1px solid #ccc;max-height:300px;overflow-y:auto;background:#fff;font-size:11px;"></div>
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
   <div style="margin:8px 0 0 20px;font-size:12px">
    AI managers:
    <input type="number" id="ai-mgr-count" min="1" max="20" value="{int(cfg.get('ai_manager_count', 16))}" style="width:55px">
    <button type="button" onclick="saveAiCount()">Save</button>
    <div style="font-size:10px;color:#666;margin-top:3px">
     1-20. Each AI manager runs 2-3 teams. Takes effect on the next turn.
     Lowering it pauses the highest-numbered managers (they return if you raise it again).
    </div>
   </div>
  </div>
  <div style="margin-top:8px;border-top:1px solid #ddd;padding-top:8px">
   <label style="display:block;margin:6px 0"><input type="checkbox" id="gh-push" data-flag="github_push_enabled" style="cursor:pointer" {'checked' if cfg.get('github_push_enabled', True) else ''}>
    <span style="cursor:pointer;user-select:none">Push stats to GitHub Pages after each turn</span></label>
   <div style="font-size:10px;color:#666;margin-left:20px">
    Uncheck when running test sims to avoid overwriting live stats on the website.
   </div>
  </div>
  <div style="margin-top:8px;border-top:1px solid #ddd;padding-top:8px">
   <label style="display:block;margin:6px 0"><input type="checkbox" id="ai-happenings" data-flag="ai_happenings_enabled" style="cursor:pointer" {'checked' if cfg.get('ai_happenings_enabled', False) else ''}>
    <span style="cursor:pointer;user-select:none">AI-rewrite Arena Happenings (Claude)</span></label>
   <div style="font-size:10px;color:#666;margin-left:20px">
    Requires llm.json with an api_key. If the AI call fails, the normal template text is used.
   </div>
  </div>
  <div style="margin-top:8px;border-top:1px solid #ddd;padding-top:8px">
   <label style="display:block;margin:6px 0"><input type="checkbox" id="immortal-enabled" data-flag="immortal_arenas_enabled" style="cursor:pointer" {'checked' if cfg.get('immortal_arenas_enabled', False) else ''}>
    <span style="cursor:pointer;user-select:none">Immortal Arenas enabled (Elite Spire &amp; Soul Spire)</span></label>
   <div style="font-size:10px;color:#666;margin-left:20px">
    When unchecked, running an immortal arena turn returns an error and nothing processes. Enable when ready to roll out to players.
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

 <div class="panel" style="min-width:220px;max-width:280px;background:#f9f3e0;border-color:#d4a574">
  <h3 style="color:#8b5a2b">📥 Pre-Reset: Export Archives</h3>
  <p style="font-size:11px;color:#666;margin:0 0 8px">
   Before resetting, export all Elite Spire and Soul Spire warriors<br>
   with their complete fight history. Users can download these archives<br>
   on their next login.
  </p>
  <button class="success" onclick="exportArchives()" style="width:100%;margin-bottom:8px">📥 Export Archives</button>
  <button class="warning" onclick="resetArenaSelective()" style="width:100%">⚙️ Selective Reset</button>
  <p style="font-size:10px;color:#666;margin:8px 0 0">
   Selective Reset: deletes normal arena teams/warriors, keeps<br>
   Elite/Soul Spire, resets turn to 1. Managers can create<br>
   new normal teams.
  </p>
 </div>

 <div class="panel" style="min-width:220px;max-width:280px;background:#eef3f7;border-color:#7a9bb5">
  <h3 style="color:#2f5d7c">💻 Utility Data</h3>
  <p style="font-size:11px;color:#666;margin:0 0 8px">
   Download the newest turn's data (all teams, champions, latest uploads<br>
   and results) as a ZIP for the host's Challenge Finder. Works from any<br>
   browser. Never includes passwords.
  </p>
  <button class="success" onclick="downloadUtilityData()" style="width:100%">💻 Download utility data</button>
 </div>

 <div class="panel" style="min-width:220px;max-width:280px">
  <h3>⚠️ Full Arena Reset</h3>
  <p style="font-size:11px;color:#800;margin:0 0 8px">
   ⚠ Full wipe: deletes ALL turn history, fight records, standings,<br>
   manager registrations, and teams. AI teams are regenerated.<br>
   Every player will need to re-register after this.
  </p>
  <button class="danger" onclick="resetArena()">🗑 Full Reset to Turn 1</button>
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

 <!-- Initialize Arenas strip -->
 <div style="background:#f0f4f0;border-bottom:1px solid #bdb;padding:8px 12px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
  <b style="font-size:12px">ARENA INITIALIZATION</b>
  <span style="font-size:11px;color:#555">Run once to create arena directories, configs, and add arena fields to all warriors. Safe to re-run.</span>
  <button onclick="initImmortalArenas()" style="font-size:11px;padding:3px 10px;background:#e8f4e8;border-color:#888">
   ⚙ Initialize Arenas
  </button>
  <span id="init-arenas-msg" style="font-size:11px"></span>
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

 <!-- Spire upload status strip -->
 <div style="background:#f0f4fa;border-bottom:1px solid #bcd;padding:8px 12px">
  <b style="font-size:12px">IMMORTAL ARENA UPLOAD STATUS -- Turn {turn}</b>
  <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:6px">{_spire_upload_html}</div>
 </div>

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
   <button onclick="unlockImmortalTurn('elite')" title="Force unlock if hung"
           style="font-size:11px;padding:3px 8px;background:#eee;border-color:#ccc;color:#666">
    🔓 Unlock
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
   <button onclick="resetImmortalToTurn1('elite')"
           class="danger" style="font-size:11px;padding:3px 8px"
           title="Reset turn counter and newsletters to Turn 1. Warriors are preserved.">
    ↺ Reset to Turn 1
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

 <!-- ── THE SOUL SPIRE Panel ── -->
 <div class="panel" style="min-width:320px;max-width:420px;border-color:#550;background:#fffff8">
  <h3 style="color:#550">&#9760; THE SOUL SPIRE</h3>
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
   <button onclick="unlockImmortalTurn('veteran')" title="Force unlock if hung"
           style="font-size:11px;padding:3px 8px;background:#eee;border-color:#ccc;color:#666">
    🔓 Unlock
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
   <button onclick="resetImmortalToTurn1('veteran')"
           class="danger" style="font-size:11px;padding:3px 8px"
           title="Reset turn counter and newsletters to Turn 1. Warriors are preserved.">
    ↺ Reset to Turn 1
   </button>
  </div>
  <div id="veteran-prog-wrap" class="prog-wrap" style="display:none">
   <div id="veteran-prog-bar" class="prog-bar" style="width:0%"></div>
   <div id="veteran-prog-lbl" class="prog-lbl">Running...</div>
  </div>
  <div id="veteran-msg" style="font-size:11px;margin:4px 0"></div>

  <h3 style="color:#550;margin-top:10px">📅 Soul Spire Schedule</h3>
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
async function exportArchives(){{
 const pw=pw_val();
 if(!pw){{show('Enter the host password first.','err');return;}}
 if(!confirm('Export all Elite/Soul Spire warriors and their fights?\\n\\nThis will create archive files that users can download on their next login.'))return;
 try{{
  show('Exporting archives...','');
  const r=await fetch('/api/admin/export_archives',{{method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{host_password:pw}})}});
  const d=await r.json();
  if(d.success){{
   const msg=`✓ Archives Created!\\n\\nWarriors Archived: ${{d.total_warriors}}\\nFights Preserved: ${{d.total_fights}}\\nManagers: ${{d.managers_archived}}\\nFiles Created: ${{d.files_created}}`;
   show(msg,'ok');
  }} else show('Error: '+d.error,'err');
 }}catch(e){{show('Connection error: '+e.message,'err');}}
}}
async function downloadUtilityData(){{
 const pw=pw_val()||prompt('Enter host password:');
 if(!pw){{show('Download cancelled - no password provided.','err');return;}}
 const hp=document.getElementById('hp'); if(hp) hp.value=pw;
 try{{
  show('Building utility data...','');
  const r=await fetch('/api/admin/utility_bundle',{{method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{host_password:pw}})}});
  if(!r.ok || (r.headers.get('Content-Type')||'').indexOf('zip')<0){{
   let e='Download failed.'; try{{e=(await r.json()).error||e;}}catch(_){{}}
   show('Error: '+e,'err'); return;
  }}
  const blob=await r.blob(), url=window.URL.createObjectURL(blob), a=document.createElement('a');
  const cd=r.headers.get('Content-Disposition')||'', m=/filename=([^;]+)/.exec(cd);
  a.href=url; a.download=m?m[1]:'bloodspire_utility_data.zip';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
  show('Downloaded utility data ('+Math.round(blob.size/1024)+' KB). Unzip it and point Challenge Finder at the folder.','ok');
 }}catch(e){{show('Download error: '+e.message,'err');}}
}}
async function resetArenaSelective(){{
 const pw=pw_val();
 if(!pw){{show('Enter the host password first.','err');return;}}
 if(!confirm('Selective Arena Reset?\\n\\nThis will:\\n✓ Keep Elite Spire teams and warriors\\n✓ Keep Soul Spire teams and warriors\\n✓ Keep manager accounts\\n✗ Delete normal arena teams/warriors\\n✗ Reset turn to 1\\n\\nYou should run \"Export Archives\" first!'))return;
 try{{
  show('Running selective reset...','');
  const r=await fetch('/api/arena/reset_selective',{{method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{host_password:pw}})}});
  const d=await r.json();
  if(d.success){{
   const msg=`✓ Selective Reset Complete!\\n\\nNormal Teams Deleted: ${{d.stats.normal_teams_deleted}}\\nNormal Warriors Deleted: ${{d.stats.normal_warriors_deleted}}\\nElite Teams Preserved: ${{d.stats.elite_teams_preserved}}\\nElite Warriors: ${{d.stats.elite_warriors_preserved}}\\nVeteran Teams: ${{d.stats.veteran_teams_preserved}}\\nVeteran Warriors: ${{d.stats.veteran_warriors_preserved}}`;
   show(msg,'ok');
   setTimeout(()=>{{_isNavigating=true;location.href='/admin?t='+Date.now();}},2000);
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
 show('Generating warrior registry...', 'ok');
 try {{
  const r = await fetch('/api/admin/validate_warrior_ids', {{
   method: 'POST',
   headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{host_password: pw}})
  }});
  const d = await r.json();
  if (!d.success) {{ show('Error: ' + d.error, 'err'); return; }}
  show(`Saved ${{d.filename}} — ${{d.total_warriors}} warriors, ${{d.missing_count}} missing ID, ${{d.duplicate_count}} duplicate ID(s).`,
       (d.missing_count || d.duplicate_count) ? 'err' : 'ok');
 }} catch(e) {{ show('Error: ' + e.message, 'err'); }}
}}

async function loadSpireSittingOut() {{
 const pw = pw_val();
 if (!pw) {{ show('Enter the host password first.', 'err'); return; }}
 const box = document.getElementById('spire-sitout-results');
 box.style.display = 'block';
 box.innerHTML = '<div style="padding:8px;color:#999;">Loading...</div>';
 try {{
  const r = await fetch('/api/admin/spire_sitting_out', {{
   method: 'POST',
   headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{host_password: pw}})
  }});
  const d = await r.json();
  if (!d.success) {{ box.innerHTML = '<div style="padding:8px;color:#c00;">Error: ' + d.error + '</div>'; return; }}
  const section = (title, rows) => {{
   let h = '<div style="padding:6px 8px;font-weight:bold;background:#eee;">' + title + ' (' + rows.length + ' sitting out)</div>';
   if (!rows.length) return h + '<div style="padding:6px 8px;color:#777;">No warriors sitting out.</div>';
   h += '<table style="width:100%;border-collapse:collapse;font-size:11px;"><tr style="text-align:left;color:#555;"><th style="padding:3px 8px;">Manager</th><th style="padding:3px 8px;">Team</th><th style="padding:3px 8px;">Warrior</th><th style="padding:3px 8px;">Set from</th></tr>';
   for (const x of rows) h += '<tr style="border-top:1px solid #eee;"><td style="padding:3px 8px;">' + x.manager + '</td><td style="padding:3px 8px;">' + x.team_name + ' (' + x.team_id + ')</td><td style="padding:3px 8px;font-weight:bold;">' + x.warrior + '</td><td style="padding:3px 8px;color:#777;">' + x.source + '</td></tr>';
   return h + '</table>';
  }};
  box.innerHTML = section('Elite Spire', d.elite) + section('Soul Spire', d.veteran);
 }} catch(e) {{ box.innerHTML = '<div style="padding:8px;color:#c00;">Error: ' + e.message + '</div>'; }}
}}

async function generateSpireRegistry() {{
 const pw = pw_val();
 if (!pw) {{ show('Enter the host password first.', 'err'); return; }}
 show('Generating Spire registry...', 'ok');
 try {{
  const r = await fetch('/api/admin/generate_spire_registry', {{
   method: 'POST',
   headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{host_password: pw}})
  }});
  const d = await r.json();
  if (!d.success) {{ show('Error: ' + d.error, 'err'); return; }}
  const bad = d.missing_count || d.duplicate_count || d.dead_count;
  show(`Saved ${{d.filename}} — ${{d.total_warriors}} warriors (Elite ${{d.elite_count}}, Soul ${{d.soul_count}}), `
       + `${{d.missing_count}} missing ID, ${{d.duplicate_count}} duplicate ID(s), ${{d.dead_count}} marked dead.`, bad ? 'err' : 'ok');
 }} catch(e) {{ show('Error: ' + e.message, 'err'); }}
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

let _arenaBreakdownData = null;

async function loadWarriorsByArena() {{
 const pw = pw_val();
 if (!pw) {{ show('Enter the host password first.', 'err'); return; }}
 const container = document.getElementById('warriors-by-arena-container');
 container.innerHTML = '<div style="padding:8px;color:#999;">Loading...</div>';
 try {{
  const r = await fetch('/api/admin/warriors_by_arena', {{
   method: 'POST',
   headers: {{'Content-Type': 'application/json'}},
   body: JSON.stringify({{host_password: pw}})
  }});
  const d = await r.json();
  if (!d.success) {{
   container.innerHTML = `<div style="padding:8px;color:#c00;">Error: ${{d.error}}</div>`;
   return;
  }}
  _arenaBreakdownData = d;
  document.getElementById('arena-csv-btn').disabled = false;
  const arenas = [
   {{key:'normal',  label:'⚔️ Normal Arena',   color:'#336',  bg:'#eef',  data:d.normal,  count:d.normal_count}},
   {{key:'elite',   label:'✊ Elite Spire',     color:'#363',  bg:'#efe',  data:d.elite,   count:d.elite_count}},
   {{key:'veteran', label:'☠ Soul Spire',    color:'#663',  bg:'#ffe',  data:d.veteran, count:d.veteran_count}},
  ];
  let html = '';
  arenas.forEach(a => {{
   html += `<div style="margin-bottom:14px;">`;
   html += `<div style="background:${{a.bg}};border-left:4px solid ${{a.color}};padding:4px 8px;font-weight:bold;font-size:12px;color:${{a.color}}">${{a.label}} &mdash; ${{a.count}} warrior(s)</div>`;
   if (!a.data || a.data.length === 0) {{
    html += `<div style="padding:4px 8px;color:#999;font-style:italic;">No warriors.</div>`;
   }} else {{
    html += '<table style="width:100%;border-collapse:collapse;font-size:10px;">';
    html += '<tr style="background:#ddd;"><th style="padding:3px 6px;text-align:left;border:1px solid #bbb;">Warrior</th><th style="padding:3px 6px;text-align:left;border:1px solid #bbb;">Team</th><th style="padding:3px 6px;text-align:left;border:1px solid #bbb;">Manager</th><th style="padding:3px 6px;text-align:center;border:1px solid #bbb;">W-L-K</th><th style="padding:3px 6px;text-align:center;border:1px solid #bbb;">Win%</th></tr>';
    a.data.forEach(w => {{
     const wp = a.key === 'normal' ? '' : `${{(w.win_rate*100).toFixed(1)}}%`;
     html += `<tr style="border-bottom:1px solid #ddd;"><td style="padding:2px 6px;border:1px solid #eee;"><b>${{w.warrior_name}}</b></td><td style="padding:2px 6px;border:1px solid #eee;color:#555;">${{w.team_name}}</td><td style="padding:2px 6px;border:1px solid #eee;color:#555;">${{w.manager_name}}</td><td style="padding:2px 6px;border:1px solid #eee;text-align:center;">${{w.record}}</td><td style="padding:2px 6px;border:1px solid #eee;text-align:center;">${{wp}}</td></tr>`;
    }});
    html += '</table>';
   }}
   html += '</div>';
  }});
  container.innerHTML = html;
 }} catch(e) {{
  container.innerHTML = `<div style="padding:8px;color:#c00;">Error: ${{e.message}}</div>`;
 }}
}}

function exportArenaBreakdownCSV() {{
 if (!_arenaBreakdownData) {{ show('Load the report first.', 'err'); return; }}
 const d = _arenaBreakdownData;
 let csv = 'Arena,Warrior,Team,Manager,W-L-K,Wins,Losses,Kills,Fights,Win%\\n';
 const arenas = [
  {{label:'Normal Arena', data:d.normal}},
  {{label:'Elite Spire',  data:d.elite}},
  {{label:'Soul Spire', data:d.veteran}},
 ];
 arenas.forEach(a => {{
  (a.data || []).forEach(w => {{
   const wp = w.total_fights > 0 ? (w.win_rate*100).toFixed(1) : '0.0';
   const parts = w.record.split('-');
   const wins = parts[0] || '0', losses = parts[1] || '0', kills = parts[2] || '0';
   csv += `"${{a.label}}","${{w.warrior_name}}","${{w.team_name}}","${{w.manager_name}}","${{w.record}}",${{wins}},${{losses}},${{kills}},${{w.total_fights}},${{wp}}\n`;
  }});
 }});
 const blob = new Blob([csv], {{type:'text/csv;charset=utf-8;'}});
 const link = document.createElement('a');
 link.href = URL.createObjectURL(blob);
 link.download = 'warriors_by_arena.csv';
 link.click();
 show('Arena breakdown exported as CSV', 'ok');
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

async function saveAiCount(){{
 const el=document.getElementById('ai-mgr-count');
 let n=parseInt(el.value,10);
 if(isNaN(n)||n<1||n>20){{show('AI manager count must be 1-20.','err');return;}}
 let pw=pw_val();
 if(!pw){{
  pw=prompt('Host password required to save this setting:');
  if(!pw){{show('Not saved - host password required.','err');return;}}
  const hp=document.getElementById('hp');if(hp) hp.value=pw;
 }}
 try{{
  const r=await fetch('/api/admin/update',{{method:'POST',
   headers:{{'Content-Type':'application/json'}},
   body:JSON.stringify({{host_password:pw,ai_manager_count:n}})}});
  const d=await r.json();
  if(d.success){{show('Saved: '+n+' AI managers (applies next turn)','ok');}}
  else{{show('Error: '+(d.error||'update failed'),'err');}}
 }}catch(e){{show('Connection error: '+e.message,'err');}}
}}

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
  const label={{'elite':'The Elite Spire','veteran':'THE SOUL SPIRE'}}[arena]||arena;
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

async function resetImmortalToTurn1(arena){{
  const pw=getPw();
  if(!pw){{alert('Enter host password first.');return;}}
  const label={{'elite':'The Elite Spire','veteran':'The Soul Spire'}}[arena]||arena;
  if(!confirm('Reset '+label+' to Turn 1?\\n\\nThis will:\\n- Clear all newsletters and fight results for this arena\\n- Revert warrior W-L-K records to their pre-arena stats\\n- Reset the turn counter to 0\\n\\nWarrior stats, equipment, skills, and training are preserved.\\n\\nContinue?'))return;
  const msg=document.getElementById(arena+'-msg');
  msg.textContent='Resetting...';
  try{{
    const r=await fetch('/api/admin/reset_immortal_to_turn1',{{method:'POST',
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

async function initImmortalArenas(){{
  const pw=getPw();
  if(!pw){{alert('Enter host password first.');return;}}
  const msgEl=document.getElementById('init-arenas-msg');
  msgEl.textContent='Running...';
  try{{
    const r=await fetch('/api/admin/init_immortal_arenas',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{host_password:pw}})}});
    const d=await r.json();
    if(d.success){{
      msgEl.innerHTML='<span style="color:#080">Done.</span>';
      if(d.output){{
        const pre=document.createElement('pre');
        pre.style.cssText='background:#f5f5f5;border:1px solid #ccc;padding:8px;font-size:10px;max-height:200px;overflow-y:auto;margin:8px 0;white-space:pre-wrap';
        pre.textContent=d.output;
        msgEl.appendChild(pre);
      }}
    }}else{{
      msgEl.innerHTML='<span style="color:#800">Error: '+(d.error||'unknown')+'</span>';
    }}
  }}catch(e){{msgEl.innerHTML='<span style="color:#800">'+e.message+'</span>';}}
}}

async function unlockImmortalTurn(arena){{
  const pw=getPw();
  if(!pw){{alert('Enter host password first.');return;}}
  const label={{'elite':'The Elite Spire','veteran':'The Soul Spire'}}[arena]||arena;
  if(!confirm('Force unlock the '+label+' turn state?\\n\\nOnly do this if a previous run crashed or hung.'))return;
  const msg=document.getElementById(arena+'-msg');
  try{{
    const r=await fetch('/api/admin/unlock_immortal',{{method:'POST',
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

async function showAILearningReport(){{
  const pw=getPw();
  if(!pw){{alert('Enter host password first.');return;}}
  const box=document.getElementById('ai-learning-container');
  box.textContent='Loading...';
  try{{
    const r=await fetch('/api/admin/ai_learning_report',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{host_password:pw}})}});
    const d=await r.json();
    box.textContent=d.success?d.report:(d.error||'Failed');
  }}catch(e){{box.textContent='Error: '+e;}}
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
      html+=`<button onclick="_resurrectSelected('veteran')" style="background:#3a2a00;color:#fc8;border:1px solid #760;padding:4px 14px;cursor:pointer;border-radius:3px">&#9760; Send to Soul Spire</button>`;
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

    // ── Living Warriors -- Elite Eligible ──────────────────────────────────────
    if(d.living_eligible.length){{
      html+='<h4 style="color:#080;margin:14px 0 4px">Living Warriors -- Elite Eligible ('+d.living_eligible.length+')</h4>';
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
      html+='<thead style="background:#1a3a1a;color:#9f9;position:sticky;top:0"><tr><th style="padding:3px 6px;text-align:left">Warrior</th><th style="padding:3px 6px;text-align:left">Team</th><th style="padding:3px 6px">Record</th><th style="padding:3px 6px">Win%</th><th style="padding:3px 6px">Trains</th><th style="padding:3px 6px"></th></tr></thead><tbody>';
      d.elite_roster.forEach(w=>{{
        html+=`<tr style="border-bottom:1px solid #2a4a2a"><td style="padding:2px 6px"><b>${{w.warrior_name}}</b></td><td style="padding:2px 6px;color:#888">${{w.team_name}}</td><td style="padding:2px 6px;text-align:center">${{w.record}}</td><td style="padding:2px 6px;text-align:center">${{(w.win_rate*100).toFixed(1)}}%</td><td style="padding:2px 6px;text-align:center">${{w.total_trains}}</td><td style="padding:2px 6px"><button onclick="doRemoveFromElite(${{w.team_id}},'${{w.warrior_name}}')" style="font-size:11px;padding:1px 6px;background:#c66;color:#fff">Remove</button></td></tr>`;
      }});
      html+='</tbody></table></div>';
    }}else{{
      html+='<p style="color:#666;font-size:12px;font-style:italic;margin:2px 0 10px">No warriors currently in The Elite Spire.</p>';
    }}
    html+='<h5 style="color:#fc8;margin:8px 0 4px">&#9760; THE SOUL SPIRE &mdash; '+d.veteran_roster.length+' warrior(s)</h5>';
    if(d.veteran_roster.length){{
      html+='<div style="max-height:160px;overflow-y:auto;border:1px solid #760;border-radius:3px">';
      html+='<table style="width:100%;font-size:12px;border-collapse:collapse">';
      html+='<thead style="background:#3a2a00;color:#fc8;position:sticky;top:0"><tr><th style="padding:3px 6px;text-align:left">Warrior</th><th style="padding:3px 6px;text-align:left">Team</th><th style="padding:3px 6px">Record</th><th style="padding:3px 6px">Win%</th><th style="padding:3px 6px">Trains</th><th style="padding:3px 6px"></th></tr></thead><tbody>';
      d.veteran_roster.forEach(w=>{{
        html+=`<tr style="border-bottom:1px solid #4a3a10"><td style="padding:2px 6px"><b>${{w.warrior_name}}</b></td><td style="padding:2px 6px;color:#888">${{w.team_name}}</td><td style="padding:2px 6px;text-align:center">${{w.record}}</td><td style="padding:2px 6px;text-align:center">${{(w.win_rate*100).toFixed(1)}}%</td><td style="padding:2px 6px;text-align:center">${{w.total_trains}}</td><td style="padding:2px 6px"><button onclick="doMoveToElite(${{w.team_id}},'${{w.warrior_name}}')" style="font-size:11px;padding:1px 6px;background:#9f9;color:#000">→ Elite</button></td></tr>`;
      }});
      html+='</tbody></table></div>';
    }}else{{
      html+='<p style="color:#666;font-size:12px;font-style:italic;margin:2px 0">No warriors currently in THE SOUL SPIRE.</p>';
    }}

    // ── Restore Removed Warriors ──────────────────────────────────────────────────
    html+='<hr style="margin:18px 0 12px;border:none;border-top:1px solid #555">';
    html+='<h4 style="margin:0 0 8px;color:#c80">RESTORE WARRIOR TO ELITE SPIRE</h4>';
    html+='<p style="font-size:11px;color:#666;margin:0 0 8px">Accidentally removed a warrior from Elite Spire? Restore them by entering their name and record.</p>';
    html+='<div style="display:grid;grid-template-columns:1fr 1fr 1fr 100px;gap:8px;align-items:center;font-size:12px">';
    html+='<div><label style="display:block;font-weight:bold;margin-bottom:2px">Warrior Name</label><input type="text" id="restore-name" placeholder="e.g. BOFUVUM" style="width:100%;padding:4px;border:1px solid #ccc;border-radius:3px"></div>';
    html+='<div><label style="display:block;font-weight:bold;margin-bottom:2px">Wins</label><input type="number" id="restore-wins" placeholder="21" style="width:100%;padding:4px;border:1px solid #ccc;border-radius:3px" min="0"></div>';
    html+='<div><label style="display:block;font-weight:bold;margin-bottom:2px">Losses</label><input type="number" id="restore-losses" placeholder="10" style="width:100%;padding:4px;border:1px solid #ccc;border-radius:3px" min="0"></div>';
    html+='<button onclick="doRestoreWarrior()" style="background:#1a3a1a;color:#9f9;border:1px solid #4a7;padding:6px 12px;cursor:pointer;border-radius:3px;height:fit-content">Restore</button>';
    html+='</div>';
    html+='<div id="restore-status" style="font-size:11px;color:#666;margin-top:8px"></div>';

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
  const label={{'elite':'The Elite Spire','veteran':'THE SOUL SPIRE'}}[targetArena]||targetArena;
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
  const label={{'elite':'The Elite Spire','veteran':'THE SOUL SPIRE'}}[target]||target;
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
  if(!confirm('Mark '+warriorName+' for retirement to THE SOUL SPIRE?'))return;
  const r=await fetch('/api/admin/retire_warrior',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{host_password:pw,team_id:teamId,warrior_name:warriorName}})}});
  const d=await r.json();
  if(d.success){{alert(d.message);showPromotionPanel();}}
  else{{alert('Error: '+(d.error||'unknown'));}}
}}

async function doMoveToElite(teamId, warriorName){{
  const pw=getPw();
  if(!confirm('Move '+warriorName+' from THE SOUL SPIRE to The Elite Spire?'))return;
  const r=await fetch('/api/admin/move_to_elite',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{host_password:pw,team_id:teamId,warrior_name:warriorName}})}});
  const d=await r.json();
  if(d.success){{alert(d.message);showPromotionPanel();}}
  else{{alert('Error: '+(d.error||'unknown'));}}
}}

async function doRemoveFromElite(teamId, warriorName){{
  const pw=getPw();
  if(!confirm('REMOVE '+warriorName+' from The Elite Spire? This cannot be undone.'))return;
  const r=await fetch('/api/admin/remove_from_elite',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{host_password:pw,team_id:teamId,warrior_name:warriorName}})}});
  const d=await r.json();
  if(d.success){{alert(d.message);showPromotionPanel();}}
  else{{alert('Error: '+(d.error||'unknown'));}}
}}

async function doRestoreWarrior(){{
  const pw=getPw();
  const name=(document.getElementById('restore-name').value||'').trim();
  const wins=parseInt(document.getElementById('restore-wins').value||'-1');
  const losses=parseInt(document.getElementById('restore-losses').value||'-1');
  const status=document.getElementById('restore-status');

  if(!name){{status.textContent='✗ Enter warrior name';status.style.color='#c00';return;}}
  if(wins<0||losses<0){{status.textContent='✗ Enter wins and losses';status.style.color='#c00';return;}}

  status.textContent='Searching...';
  status.style.color='#666';

  try{{
    const r=await fetch('/api/admin/restore_to_elite',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{host_password:pw,warrior_name:name,wins:wins,losses:losses}})}});
    const d=await r.json();
    if(d.success){{
      status.textContent='✓ '+d.message;
      status.style.color='#080';
      document.getElementById('restore-name').value='';
      document.getElementById('restore-wins').value='';
      document.getElementById('restore-losses').value='';
      setTimeout(()=>showPromotionPanel(),1500);
    }}else{{
      status.textContent='✗ '+d.error;
      status.style.color='#c00';
    }}
  }}catch(e){{
    status.textContent='✗ Error: '+e.message;
    status.style.color='#c00';
  }}
}}
// ── end Immortal Arena JS ──────────────────────────────────────────────────

// ── Announcements Management JS ────────────────────────────────────────────
let _currentEditId = null;

async function createAnnouncement() {{
  const title = document.getElementById('ann-title').value.trim();
  const message = document.getElementById('ann-message').value.trim();
  const url = document.getElementById('ann-url').value.trim();
  if (!title || !message) {{ alert('Title and message required'); return; }}

  const r = await fetch('/api/admin/announcements/create', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{title, message, url}})
  }});
  const d = await r.json();
  if (d.success) {{
    alert('Announcement created!');
    document.getElementById('ann-title').value = '';
    document.getElementById('ann-message').value = '';
    document.getElementById('ann-url').value = '';
    location.reload();
  }} else {{
    alert('Error: ' + (d.error || 'unknown'));
  }}
}}

async function editAnnouncement(annId) {{
  _currentEditId = annId;
  const r = await fetch('/api/admin/announcements/list', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{}})
  }});
  const d = await r.json();
  const ann = d.announcements.find(a => a.id === annId);
  if (!ann) {{ alert('Announcement not found'); return; }}

  document.getElementById('edit-title').value = ann.title;
  document.getElementById('edit-message').value = ann.message;
  document.getElementById('edit-url').value = ann.url || '';
  document.getElementById('edit-active').checked = ann.active !== false;

  document.getElementById('edit-modal').style.display = 'block';
  document.getElementById('edit-overlay').style.display = 'block';
}}

async function saveAnnouncement() {{
  if (!_currentEditId) return;
  const r = await fetch('/api/admin/announcements/update', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{
      id: _currentEditId,
      title: document.getElementById('edit-title').value,
      message: document.getElementById('edit-message').value,
      url: document.getElementById('edit-url').value,
      active: document.getElementById('edit-active').checked
    }})
  }});
  const d = await r.json();
  if (d.success) {{
    alert('Announcement updated!');
    closeEditModal();
    location.reload();
  }} else {{
    alert('Error: ' + (d.error || 'unknown'));
  }}
}}

async function deleteAnnouncement(annId) {{
  if (!confirm('Delete this announcement?')) return;
  const r = await fetch('/api/admin/announcements/delete', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{id: annId}})
  }});
  const d = await r.json();
  if (d.success) {{
    alert('Announcement deleted!');
    location.reload();
  }} else {{
    alert('Error: ' + (d.error || 'unknown'));
  }}
}}

function closeEditModal() {{
  document.getElementById('edit-modal').style.display = 'none';
  document.getElementById('edit-overlay').style.display = 'none';
  _currentEditId = null;
}}
// ── end Announcements JS ────────────────────────────────────────────────────

// Browser close detection - only shut down on real tab close, not auto-reloads
window.addEventListener('beforeunload', () => {{
  if(!_isNavigating) navigator.sendBeacon('/api/shutdown', '');
}});
</script>

<div class="panel" style="width:100%;margin-top:20px">
{_announcements_admin_section()}
</div>

</body></html>"""
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
        # Stream in 64KB chunks to handle large responses
        chunk_size = 65536
        try:
            for i in range(0, len(body), chunk_size):
                self.wfile.write(body[i:i+chunk_size])
            self.wfile.flush()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # The client closed the connection before the reply arrived (e.g. the
            # page or program that sent the request went away). Nothing to report.
            pass

    def send_html(self, html, status=200):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type",   "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control",  "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma",         "no-cache")
        self.send_header("Expires",        "0")
        self.end_headers()
        # Stream in 64KB chunks to avoid buffering massive responses
        chunk_size = 65536
        try:
            for i in range(0, len(body), chunk_size):
                self.wfile.write(body[i:i+chunk_size])
            self.wfile.flush()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # The browser closed the page before it finished loading. Nothing to report.
            pass

    def body(self):
        self._body_malformed = False
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError) as _je:
            # Never print the start of the body: it carries the manager's password.
            _pos = getattr(_je, "pos", None)
            _where = ""
            if _pos is not None:
                import re as _re
                _ctx = raw[max(0, _pos - 60):_pos + 60].decode("utf-8", "replace")
                _ctx = _re.sub(r'("password"\s*:\s*)"[^"]*"', r'\1"***"', _ctx)
                _where = f" at char {_pos}: ...{_ctx!r}..."
            _nuls = raw.count(b"\x00")
            if _nuls:
                _first = raw.index(b"\x00")
                _run = len(raw[_first:]) - len(raw[_first:].lstrip(b"\x00"))
                _where += f" [NUL bytes: {_nuls} total, first at {_first}, first run {_run} bytes]"
            self._body_malformed = True
            print(f"  WARNING: Malformed JSON body on {self.path.split('?')[0]} from {self.client_address[0]} "
                  f"({len(raw)} bytes, Content-Length {n}): {type(_je).__name__}: {_je}{_where}")
            return {}

    def qs(self):
        from urllib.parse import parse_qsl
        return dict(parse_qsl(self.path.split("?",1)[1])) if "?" in self.path else {}

    def p(self):
        return self.path.split("?")[0].rstrip("/") or "/"

    def _log_incoming(self):
        """One console/log line per OPTIONS or POST so the host can see whether a
        manager's request arrived at all (no passwords or bodies are logged)."""
        try:
            origin = self.headers.get("Origin") or "-"
            clen   = self.headers.get("Content-Length") or "0"
            print(f"  [req] {time.strftime('%H:%M:%S')} {self.command} {self.p()} "
                  f"from {self.client_address[0]} origin={origin} bytes={clen}")
        except Exception:
            pass

    def do_OPTIONS(self):
        self._log_incoming()
        self.send_response(200); self._cors(); self.end_headers()

    # ── Crash guard ───────────────────────────────────────────────────────
    # An uncaught exception in a handler used to kill the thread and drop the
    # connection with no reply, which browsers report as "Failed to fetch".
    # Log the traceback and send a readable JSON 500 instead.

    def _guarded(self, fn):
        try:
            fn()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            raise  # client went away; handle_error() already ignores these
        except Exception as e:
            import traceback
            who = self.client_address[0] if self.client_address else "?"
            print(f"  ERROR: unhandled exception in {self.command} {self.path} from {who}: {e!r}")
            traceback.print_exc()
            try:
                self.send_json({"success": False,
                                "error": f"Server error: {type(e).__name__}: {e}. "
                                         "The host can find the details in the server log."}, 500)
            except Exception:
                pass  # response already started or socket gone

    def do_GET(self):
        self._guarded(self._do_GET_inner)

    def do_POST(self):
        self._log_incoming()
        if self.p() == "/api/warrior":
            # Same handler as PUT. Lets a client whose PC cannot run curl (needed for cross-origin
            # PUT in the desktop app) update gear / training / strategies with an ordinary POST.
            return self._guarded(self.do_PUT)
        self._guarded(self._do_POST_inner)

    # ── GET ───────────────────────────────────────────────────────────────

    def _do_GET_inner(self):
        path = self.p()

        if path in _VERSION_GATED_GET and _client_version_blocked(self, path, self.qs().get("client_version")):
            return

        if path.startswith("/api/local/") and path != "/api/local/status" and not _is_server_machine(self):
            self.send_json({"success": False,
                            "error": "The local file API is only available on the server machine."}, 403); return

        if path == "/api/ping":
            cfg = _load_config()
            self.send_json({
                "status":     "ok",
                "turn":       cfg.get("current_turn", 1),
                "turn_state": cfg.get("turn_state", "open"),
            }); return

        if path in ("/", "/admin"):
            self.send_html(_admin_page()); return

        if path == "/recover":
            self.send_html(_RECOVER_PAGE); return

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
            if turn_num and _processing_block(self, "normal", turn_num): return
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

        if path == "/api/announcements":
            # Public endpoint -- no auth required.
            # Returns active, non-expired announcements to client.
            announcements = _get_active_announcements()
            # An out-of-date client (or one that reports no version) also gets an
            # "update required" pop-up with a clickable download link, shown first.
            try:
                _upd = _update_announcement(self.qs().get("client_version"))
                if _upd:
                    announcements = [_upd] + list(announcements)
            except Exception:
                pass
            self.send_json({"success":True,"announcements":announcements}); return

        if path == "/api/immortal_team":
            # Returns the full team file from any arena directory so the client
            # can store it locally (needed for upload and team detail view).
            # Accepts team_id as query string param (GET endpoint).
            _qs = self.qs()
            tid = int(_qs.get("team_id") or 0)
            if not tid:
                self.send_json({"success": False, "error": "team_id required"}); return
            # ?arena=elite|veteran returns that arena's own snapshot (current stats and
            # arena fight history) - what the client caches for offline viewing.
            _arena_q = (_qs.get("arena") or "").strip()
            if _arena_q in ("elite", "veteran"):
                _ap = os.path.join(_immortal_team_dir(_arena_q), f"team_{tid:04d}.json")
                if not os.path.exists(_ap):
                    self.send_json({"success": False, "error": f"Team {tid} has no {_arena_q} file"}); return
                with open(_ap, encoding="utf-8") as _af:
                    self.send_json({"success": True, "arena": _arena_q, "team": json.load(_af)}); return
            from save import load_team_any_arena
            try:
                team_dict = load_team_any_arena(tid)
                self.send_json({"success": True, "team": team_dict}); return
            except FileNotFoundError:
                self.send_json({"success": False, "error": f"Team {tid} not found"}); return

        if path == "/api/immortal_warriors":
            # Public endpoint -- no auth required.
            # Reads directly from the arena-specific team files (saves/{arena}/teams/)
            # so normal-arena uploads cannot contaminate the result.
            _mgrs2 = _load_managers()
            _tid_to_mgr = {}
            for _mid2, _md2 in _mgrs2.items():
                # Check both team_ids (normal) and immortal_team_ids (elite/veteran)
                for _t2id in list(_md2.get("team_ids") or []) + list(_md2.get("immortal_team_ids") or []):
                    _tid_to_mgr[int(_t2id)] = _md2.get("manager_name", "")

            # Soul Spire death limit, so the client can show lives remaining.
            try:
                with open(os.path.join(BASE_DIR, "saves", "veteran", "config.json"), encoding="utf-8") as _vf:
                    _soul_max, _ = _soul_rules(json.load(_vf))
            except Exception:
                _soul_max = _SOUL_DEFAULT_MAX_DEATHS

            def _iw_entries(arena_name):
                result_list = []
                for _td in _load_immortal_teams(arena_name):
                    _tname = _td.get("team_name", "?")
                    _tid   = int(_td.get("team_id", 0))
                    _tmgr  = _td.get("manager_name") or _tid_to_mgr.get(_tid, "")
                    def _entry(_wd, _an=arena_name, _tn=_tname, _ti=_tid, _tm=_tmgr):
                        fh = _wd.get("fight_history") or []
                        af = [f for f in fh if (f.get("arena") or "normal") == _an]
                        _e = {
                            **_wd,
                            "team_name":    _tn,
                            "team_id":      _ti,
                            "manager_name": _tm,
                            "arena_wins":   sum(1 for f in af if f.get("result") == "win"),
                            "arena_losses": sum(1 for f in af if f.get("result") == "loss"),
                            "arena_kills":  sum(1 for f in af if f.get("is_kill", False)),
                        }
                        if _an == "veteran":
                            # Lives left before the final death (0 once they have fallen).
                            _e["soul_lives_max"]  = _soul_max
                            _e["soul_lives_left"] = max(0, _soul_max - int(_wd.get("soul_spire_deaths", 0) or 0))
                        return _e
                    for _w in (_td.get("warriors") or []):
                        if isinstance(_w, dict) and (not _w.get("is_dead", False)
                                                     or _w.get("soul_spire_final_death")):
                            result_list.append(_entry(_w))
                    for _w in (_td.get("archived_warriors") or []):
                        if isinstance(_w, dict) and (not _w.get("is_dead", True)
                                                     or _w.get("soul_spire_final_death")):
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
            if _processing_block(self, arena): return
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
            if _processing_block(self, arena, turn): return
            nl_path = os.path.join(BASE_DIR, "saves", arena,
                                   f"turn_{turn:04d}", "newsletter.txt")
            if not os.path.exists(nl_path):
                self.send_json({"success": False,
                                "error": f"Newsletter for {arena} turn {turn} not found."}); return
            with open(nl_path, encoding="utf-8") as _f:
                content = _f.read()
            self.send_json({"success": True, "arena": arena, "turn": turn, "content": content}); return

        if path == "/api/immortal_result":
            _pb_arena = (urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "").get("arena", [""])[0]).strip()
            if _pb_arena in ("elite", "veteran") and _processing_block(self, _pb_arena): return
            # Return the result file(s) for a manager's teams in one immortal arena turn.
            # Includes fight_logs so clients can save narratives locally for offline viewing.
            # GET  ?arena=elite&turn=N&manager_id=Y
            _raw_qs = self.path.split("?", 1)[1] if "?" in self.path else ""
            _qs2    = urllib.parse.parse_qs(_raw_qs)
            arena   = _qs2.get("arena", [""])[0].strip()
            turn    = int(_qs2.get("turn", ["0"])[0] or 0)
            mid     = _qs2.get("manager_id", [""])[0].strip()
            if arena not in ("elite", "veteran"):
                self.send_json({"success": False, "error": "arena must be 'elite' or 'veteran'"}); return
            if not turn:
                self.send_json({"success": False, "error": "turn parameter required"}); return
            # Each result file holds that team's fight logs, including its own strategy
            # tables, so a manager may only download the files for their own teams -
            # authenticated the same way as the regular arena's /api/results.
            _mgrs3 = _load_managers()
            _mgr3  = _mgrs3.get(mid)
            if not _mgr3:
                self.send_json({"success": False, "error": "Manager not found."}, 404); return
            if not _check_mgr_pw(_mgr3, _qs2.get("password", [""])[0]):
                self.send_json({"success": False, "error": "Wrong password."}, 401); return
            turn_dir = os.path.join(BASE_DIR, "saves", arena, f"turn_{turn:04d}")
            if not os.path.isdir(turn_dir):
                self.send_json({"success": True, "results": []}); return
            _own_ids = {int(t) for t in (_mgr3.get("team_ids") or []) + (_mgr3.get("immortal_team_ids") or [])}
            _own_name = (_mgr3.get("manager_name") or "").strip().lower()
            results_out = []
            for fname in sorted(os.listdir(turn_dir)):
                if not (fname.startswith("result_team") and fname.endswith(".json")):
                    continue
                # Extract team_id from filename (result_teamXXXX.json)
                try:
                    file_tid = int(fname[len("result_team"):-len(".json")])
                except ValueError:
                    continue
                r = _load_json(os.path.join(turn_dir, fname), None, protected=False)
                # Only this manager's teams: by team ID, or by manager name for a Spire
                # team that is no longer on the manager's regular team list.
                if r and (file_tid in _own_ids
                          or (_own_name and (r.get("manager_name") or "").strip().lower() == _own_name)):
                    results_out.append(r)
            self.send_json({"success": True, "arena": arena, "turn": turn, "results": results_out}); return

        if path == "/api/latest_newsletter":
            if _processing_block(self, "normal"): return
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
            # Usage: /newsletter/turn/1 or /newsletter to list all.
            # The Spires have the same pages under /newsletter/elite/... and
            # /newsletter/soul/... (e.g. /newsletter/elite/turn/3).
            _nl_arena = "normal"
            for _seg, _ar in (("elite", "elite"), ("soul", "veteran")):
                if path == f"/newsletter/{_seg}" or path.startswith(f"/newsletter/{_seg}/"):
                    _nl_arena = _ar
                    path = "/newsletter" + path[len(f"/newsletter/{_seg}"):]
                    break
            if _nl_arena == "normal":
                _nl_base, _nl_dir = "/newsletter", LEAGUE_DIR
                _nl_title, _nl_name = "THE AGONY AMPHITHEATRE", "The Agony Amphitheatre"
                _nl_client_dir = "newsletters"
            else:
                _nl_base = "/newsletter/" + ("elite" if _nl_arena == "elite" else "soul")
                _nl_dir = os.path.join(BASE_DIR, "saves", _nl_arena)
                _nl_title = "THE ELITE SPIRE" if _nl_arena == "elite" else "THE SOUL SPIRE"
                _nl_name = "The Elite Spire" if _nl_arena == "elite" else "The Soul Spire"
                _nl_client_dir = f"{_nl_arena}/newsletters"
            _nl_turn_dir = lambda t: os.path.join(_nl_dir, f"turn_{int(t):04d}")
            _nl_nav = " &nbsp;|&nbsp; ".join(
                (f'<b>{_lbl}</b>' if _ar == _nl_arena else f'<a href="{_href}">{_lbl}</a>')
                for _ar, _href, _lbl in (("normal", "/newsletter", "The Agony Amphitheatre"),
                                         ("elite", "/newsletter/elite", "The Elite Spire"),
                                         ("veteran", "/newsletter/soul", "The Soul Spire")))
            parts = path.split("/")
            turn_num = 0

            # Check if just /newsletter with no turn specified
            if path == "/newsletter" or len(parts) <= 3 or (len(parts) == 4 and parts[3] == ""):
                # List available newsletters
                available = []
                try:
                    if os.path.exists(_nl_dir):
                        for turn_dir in os.listdir(_nl_dir):
                            if turn_dir.startswith("turn_"):
                                turn_path = os.path.join(_nl_dir, turn_dir)
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
                        newsletter_links += f'            <li><a href="{_nl_base}/turn/{turn}">Turn {turn}</a></li>\n'
                else:
                    newsletter_links = '            <li><em>No newsletters available yet</em></li>\n'

                html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_nl_name} -- Newsletters</title>
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
            <h1>⚔ {_nl_title} ⚔</h1>
            <p>Arena Newsletters</p>
            <p style="margin-top:10px; font-size:0.95em;">{_nl_nav}</p>
        </div>

        <ul class="newsletter-list">
{newsletter_links}        </ul>

        <div class="footer">
            <p>{_nl_name} Arena League</p>
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

            nl_path = os.path.join(_nl_turn_dir(turn_num), "newsletter.txt")
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
    <title>{_nl_name} -- Newsletter Turn {turn_num}</title>
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
            <h1>⚔ {_nl_title} ⚔</h1>
            <p>Arena Newsletter -- Turn {turn_num}</p>
            <p style="margin-top:10px; font-size:0.95em;"><a href="{_nl_base}" style="color:#ff9999;">All {_nl_name} newsletters</a></p>
        </div>

        <div class="button-row">
            <button onclick="downloadNewsletter()">📥 Download Newsletter</button>
        </div>

        <div class="newsletter-content">
{formatted_content}
        </div>

        <div class="footer">
            <p>Newsletter for Turn {turn_num} | {_nl_name} Arena League</p>
            <p style="margin-top: 10px; font-size: 0.85em;">After downloading, place the file in your client's <code>{_nl_client_dir}</code> folder to view it in the game.</p>
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
            # Auth check - wrong credentials are refused; without valid credentials the
            # caller is treated as owning no team.
            mgrs = _load_managers()
            if mid and pw:
                if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                    self.send_json({"success":False,"error":"Not authorised."},401); return
            _authed  = bool(mid and pw)
            _mgr_fl  = mgrs.get(mid, {}) if _authed else {}
            _own_ids = {int(t) for t in (_mgr_fl.get("team_ids") or []) + (_mgr_fl.get("immortal_team_ids") or [])}
            _own_nm  = (_mgr_fl.get("manager_name") or "").strip().lower()

            # Who may read a fight log (same rule in every arena):
            #   - a manager with a warrior in the fight gets their own team's copy;
            #   - a manager scouting one of the fighters gets a copy with the strategy
            #     table, strategy switches and training results removed, the same
            #     treatment as the fight in a scout report;
            #   - anyone else is refused.
            def _scout_copy(text):
                if not isinstance(text, str):
                    return text
                text = _strip_training_block(_strip_strategy_table(text))
                return "\n".join(l for l in text.split("\n") if "switches to strategy" not in l)

            def _is_scouting(fighters, fight_arena):
                # Selections are kept for one turn per manager. A regular-arena selection
                # covers that turn's fights; a Spire selection covers the scouted warrior's
                # fight in that Spire's latest turn, which is what its scout report shows.
                if not _authed:
                    return False
                from save import load_scouting
                entry = load_scouting().get(str(mid)) or {}
                if fight_arena == "normal":
                    if entry.get("turn") != turn_n:
                        return False
                else:
                    try:
                        with open(os.path.join(BASE_DIR, "saves", fight_arena, "config.json"), encoding="utf-8") as _cf:
                            if int(json.load(_cf).get("turn_counter", 0)) != turn_n:
                                return False
                    except Exception:
                        return False
                for sel in entry.get("selections") or []:
                    if not sel.get("confirmed") or (sel.get("arena") or "normal") != fight_arena:
                        continue
                    try:
                        key = (int(sel.get("team_id") or 0), (sel.get("warrior_name") or "").upper())
                    except (TypeError, ValueError):
                        continue
                    if key in fighters:
                        return True
                return False

            def _is_own(fname, r):
                if not _authed:
                    return False
                if fname.startswith("result_team"):
                    try:
                        if int(fname[len("result_team"):-len(".json")]) in _own_ids:
                            return True
                    except ValueError:
                        pass
                    return bool(_own_nm) and (r.get("manager_name") or "").strip().lower() == _own_nm
                return fname.startswith(f"result_{mid}")

            # Directories to search, in order. A regular-arena request falls back to the
            # Spire turn folders (stopping at the first folder that has the fight).
            if arena in ("elite", "veteran"):
                _dirs = [(os.path.join(BASE_DIR, "saves", arena, f"turn_{turn_n:04d}"), arena)]
            else:
                _dirs = [(_turn_dir(turn_n), "normal")] + [
                    (os.path.join(BASE_DIR, "saves", _ia, f"turn_{turn_n:04d}"), _ia)
                    for _ia in ("elite", "veteran")]
            narrative = None
            found = False
            for td, _fa in _dirs:
                if not os.path.exists(td):
                    continue
                own_log = other_log = None
                fighters = set()   # (team_id, WARRIOR NAME) of both combatants
                for fname in sorted(os.listdir(td)):
                    if not (fname.startswith("result_") and fname.endswith(".json")):
                        continue
                    r = _load_json(os.path.join(td, fname), None, protected=(_fa == "normal"))
                    if not r:
                        continue
                    logs = r.get("fight_logs", {})
                    if str(fid) not in logs:
                        continue
                    for _b in (r.get("bouts") or []):
                        if _b.get("fight_id") == fid:
                            try:
                                fighters.add((int(r.get("team_id") or 0), (_b.get("warrior_name") or "").upper()))
                            except (TypeError, ValueError):
                                pass
                    if own_log is None and _is_own(fname, r):
                        own_log = logs[str(fid)]
                    elif other_log is None:
                        other_log = logs[str(fid)]
                if own_log is None and other_log is None:
                    continue
                found = True
                if own_log is not None:
                    narrative = own_log
                elif _is_scouting(fighters, _fa):
                    narrative = _scout_copy(other_log)
                break
            if not found:
                self.send_json({"success":False,"error":f"Fight log {fid} not found for turn {turn_n}."},404); return
            if narrative is None:
                self.send_json({"success":False,"error":"You can only view fights involving your own "
                                "warriors or a warrior you are scouting."},403); return
            self.send_json({"success":True,"narrative":narrative,"fight_id":fid,"turn":turn_n}); return

        if path == "/api/standings":
            cfg = _load_config()
            standings = _conceal_ai_in_standings(_load_standings())
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

        if path == "/api/taunt_triggers":
            # Return available triggers for taunts/jeers selection
            from strategy import TAUNT_TRIGGER_OPTIONS
            self.send_json({"success": True, "triggers": TAUNT_TRIGGER_OPTIONS}); return

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
            if _processing_block(self, "normal"): return
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
            latest_turn = cfg["current_turn"] - 1
            if latest_turn < 1:
                self.send_json({"success":False,"error":"No completed turns yet."}, 404); return

            # CHANGE: Backfill every turn a manager missed downloading (e.g. away for
            # several turns while auto-carry keeps their team playing), not just the
            # single latest one. last_downloaded_turn already tracked how far behind a
            # manager was - previously only used to detect a same-turn re-download, now
            # also used to compute the start of the range to serve.
            last_dl = int(mgrs[mid].get("last_downloaded_turn", 0) or 0)
            last_dl_mtime = float(mgrs[mid].get("last_downloaded_result_mtime", 0))
            if last_dl <= 0:
                start_turn = latest_turn   # first-ever download: just the current turn
            elif last_dl >= latest_turn:
                start_turn = latest_turn   # no new turn; only re-serve if regenerated below
            else:
                start_turn = last_dl + 1   # missed one or more turns - backfill from there

            turns_payload = []
            newest_result_mtime = 0.0  # newest mtime across every turn served, for the already_current check
            for t in range(start_turn, latest_turn + 1):
                td = _turn_dir(t)
                team_results = []
                turn_mtime = 0.0   # newest mtime among this manager's result files for turn t
                if os.path.exists(td):
                    for fname in sorted(os.listdir(td)):
                        if fname.startswith(f"result_{mid}") and fname.endswith(".json"):
                            fpath = os.path.join(td, fname)
                            fm = os.path.getmtime(fpath)
                            if fm > turn_mtime:
                                turn_mtime = fm
                            r = _load_json(fpath, None)
                            if r:
                                # Verify ownership: only show results for teams the
                                # manager still officially owns.
                                tid = r.get("team_id")
                                tids = [str(tt) for tt in mgrs[mid].get("team_ids", [])]
                                if tids:
                                    if not tid or str(tid) not in tids:
                                        continue # Result for an old/replaced team

                                # Include everything including fight_logs for offline viewing.
                                # Bandwidth increase is negligible (~35KB per team).
                                team_results.append(r.copy())
                # Include newsletter for this turn if available
                nl_text = ""
                nl_path = os.path.join(td, "newsletter.txt")
                if os.path.exists(nl_path): # Newsletter is a text file, not JSON, but should be read-only
                    make_file_writable(nl_path) # Temporarily make writable to read
                    with open(nl_path, "r", encoding="utf-8") as _nf:
                        nl_text = _nf.read()
                    make_file_readonly(nl_path) # Set back to read-only
                    if turn_mtime == 0.0:
                        turn_mtime = os.path.getmtime(nl_path)
                if turn_mtime > newest_result_mtime:
                    newest_result_mtime = turn_mtime
                # Skip a turn with nothing for this manager (e.g. a bye), but don't
                # fail the whole request over it - other turns in the range may have data.
                if not team_results and not nl_text:
                    continue
                turns_payload.append({
                    "turn": t,
                    "results": _filter_results_for_client(team_results, cfg),
                    "has_newsletter": bool(nl_text),
                })

            # If the manager already downloaded the latest turn's results AND the result
            # files haven't been regenerated since (mtime unchanged), return already_current.
            # This allows re-download after an arena revert+rerun even on the same turn number.
            # (A real gap - last_dl < latest_turn - always has something new, so this only
            # applies when there was no gap to begin with.)
            same_generation = newest_result_mtime > 0 and abs(newest_result_mtime - last_dl_mtime) < 1.0
            # The one-download limit is OFF by default now that the server handles the replacement
            # rollup. Set "limit_one_download": true in saves/league/config.json to bring it back.
            if cfg.get("limit_one_download", False) and last_dl >= latest_turn and same_generation:
                _log_activity("download_already_current", mid, mgrs[mid]["manager_name"],
                              f"Already downloaded turn {latest_turn} - returning already_current")
                self.send_json({
                    "success": True, "already_current": True,
                    "turn": latest_turn,
                }); return

            if not turns_payload:
                self.send_json({"success":False,"error":"No results found for your manager this turn."}); return

            # Include any pending deletions for this manager
            deleted_teams_list = []
            for key, val in cfg.items():
                if key.startswith("deleted_team_") and str(val.get("manager_id")) == str(mid):
                    deleted_teams_list.append(val)

            # Mark the latest served turn as downloaded for this manager (include mtime
            # for revert detection)
            mgrs[mid]["last_downloaded_turn"] = latest_turn
            mgrs[mid]["last_downloaded_result_mtime"] = newest_result_mtime
            _save_managers(mgrs)

            # Log the download
            team_count = sum(len(tp["results"]) for tp in turns_payload)
            turns_str = ", ".join(str(tp["turn"]) for tp in turns_payload)
            _log_activity("download_success", mid, mgrs[mid]["manager_name"],
                        f"Downloaded {team_count} team result(s) across turn(s) {turns_str}")

            latest_entry = turns_payload[-1]
            self.send_json({
                "success": True,
                # Backward-compatible top-level fields: the latest turn only
                "results": latest_entry["results"],
                "turn": latest_entry["turn"],
                "has_newsletter": latest_entry["has_newsletter"],
                # Full backlog, oldest first, so callers can backfill every missed turn
                "turns": turns_payload,
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
            from save import TEAMS_DIR, load_champion_state, load_arena_champion_state
            # Load current turn to filter inactive teams
            cfg = _load_config()
            current_turn = cfg.get("current_turn", 0)
            # Load champion name so we can flag that warrior in the response.
            # Each arena has its own champion; only the regular arena and the Elite
            # Spire take champion challenges (the Soul Spire flags no one).
            if arena == "normal":
                champ_state = load_champion_state()
            elif arena == "elite":
                champ_state = load_arena_champion_state(arena) or {}
            else:
                champ_state = {}
            champion_name = (champ_state.get("name") or "").lower()
            warriors = []
            # For immortal arenas read from saves/{arena}/teams/ so stats reflect
            # the latest turn results (main saves/teams/ files are not updated by
            # immortal turns and would show stale pre-promotion stats).
            _scan_dir = _immortal_team_dir(arena) if arena in ("elite", "veteran") else TEAMS_DIR
            try:
                fnames = sorted(os.listdir(_scan_dir))
            except FileNotFoundError:
                fnames = []
            # AI teams can exist both as a saves/teams file and in ai_teams.json (which is
            # added below). ai_teams.json is the authoritative copy, so skip the file copy
            # here -- otherwise every such warrior is listed twice.
            _ai_ids = set()
            if arena == "normal":
                try:
                    from ai_league_teams import load_ai_teams as _lat_ids
                    _ai_ids = {at.get("team_id") for at in (_lat_ids() or []) if at.get("team_id")}
                except Exception:
                    _ai_ids = set()
            for fname in fnames:
                if not (fname.startswith("team_") and fname.endswith(".json")):
                    continue
                fpath = os.path.join(_scan_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        tdata = json.load(f)
                except Exception as e:
                    print(f"    Error loading {fname}: {e}")
                    continue
                tid = tdata.get("team_id", 0)
                if tid in _ai_ids: continue
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
                    # Immortal arena files only contain warriors for that arena --
                    # include all living warriors from both sections.
                    for w in tdata.get("warriors", []):
                        if not w or w.get("is_dead") or w.get("is_retired"): continue
                        _add_w(w)
                    for w in tdata.get("archived_warriors", []):
                        if not w or not isinstance(w, dict): continue
                        if w.get("is_dead", True): continue
                        _add_w(w)

            # AI teams live in ai_teams.json (not saves/teams/), so add them here
            # -- otherwise players could never scout or challenge them. Normal
            # arena only; same active-within-3-turns and own-team exclusions.
            if arena == "normal":
                try:
                    from ai_league_teams import load_ai_teams
                    for at in (load_ai_teams() or []):
                        a_tid = at.get("team_id", 0)
                        if a_tid in own_team_ids: continue
                        if exclude_tid and a_tid == exclude_tid: continue
                        a_ltr = at.get("last_turn_ran", 0)
                        if current_turn > 0 and a_ltr > 0 and (current_turn - a_ltr) > 3:
                            continue
                        a_team = at.get("team_name", "?")
                        a_mgr  = at.get("manager_name", "?")
                        for w in at.get("warriors", []):
                            if not w or w.get("is_dead") or w.get("is_retired"): continue
                            wname = w.get("name", "?")
                            warriors.append({
                                "name": wname, "team_name": a_team, "team_id": a_tid,
                                "manager_name": a_mgr, "race": w.get("race", "?"),
                                "gender": w.get("gender", "?"), "wins": w.get("wins", 0),
                                "losses": w.get("losses", 0), "kills": w.get("kills", 0),
                                "max_hp": w.get("max_hp", 0), "height_in": w.get("height_in", 0),
                                "weight_lbs": w.get("weight_lbs", 0),
                                "total_fights": w.get("total_fights", 0),
                                "recognition": w.get("recognition", 0),
                                "is_champion": bool(champion_name and wname.lower() == champion_name),
                            })
                except Exception as _ai_e:
                    print(f"  [Scout] AI target load failed: {_ai_e}")
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
            found_arena = found_w.get("current_arena") or "normal"
            scout_text = generate_scout_report(warrior_obj, last_fight, found_team_name,
                                               scout_name=scout_name, scout_type=scout_type,
                                               arena=found_arena)
            self.send_json({
                "success": True,
                "report": {
                    "warrior_name"    : found_w.get("name", "?"),
                    "team_name"       : found_team_name,
                    "arena"           : found_arena,
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
            return _confined_path(rel_path, os.path.join(BASE_DIR, "saves", "client"))

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
    def do_PUT(self):
        path = self.p()
        b = self.body()

        if path == "/api/warrior" and _client_version_blocked(self, path, b.get("client_version")):
            return

        if path == "/api/warrior":
            # PUT endpoint to update warrior equipment, training, and strategies
            # Handles both normal warriors (warrior_idx) and immortal warriors (warrior_name, current_arena)
            try:
                team_id = int(b.get("team_id", 0))
                if not team_id:
                    self.send_json({"success": False, "error": "team_id required"}); return

                warrior_idx = b.get("warrior_idx")
                warrior_name = b.get("warrior_name")
                is_immortal = warrior_name is not None and warrior_idx is None

                if not is_immortal and warrior_idx is None:
                    self.send_json({"success": False, "error": "warrior_idx or warrior_name required"}); return

                # Only the team's own manager may change it, and only to legal values.
                if not b.get("manager_id") and not b.get("password"):
                    _note_outdated_request(path, b)
                    self.send_json({"success": False, "outdated_client": True, "error": _outdated_message(b.get("client_version"))}, 426); return
                _ok, _who, _code = _authorize_team_owner(b, team_id)
                if not _ok:
                    self.send_json({"success": False, "error": _who}, _code); return
                from upload_guard import clean_settings, build_lookups, CLIENT_OWNED_FIELDS
                _clean = clean_settings(b, {}, build_lookups())
                for _f in CLIENT_OWNED_FIELDS:
                    if _f in b:
                        if _f in _clean: b[_f] = _clean[_f]
                        else: del b[_f]
                if "taunts_jeers_update" in b:
                    _tu = b["taunts_jeers_update"]
                    if (isinstance(_tu, dict) and isinstance(_tu.get("trigger"), str)
                            and isinstance(_tu.get("text", ""), str)):
                        _tu["trigger"] = _tu["trigger"][:80]
                        _tu["text"] = _tu.get("text", "")[:500]
                    else:
                        del b["taunts_jeers_update"]

                from save import load_team, save_team
                from warrior import Strategy
                team = load_team(team_id)
                if not team:
                    self.send_json({"success": False, "error": "Team not found"}); return

                warrior = None
                if is_immortal:
                    # Find immortal warrior by name in archived_warriors
                    for w in (team.archived_warriors or []):
                        # Handle both Warrior objects and dicts
                        w_name = w.name if hasattr(w, 'name') else w.get('name') if isinstance(w, dict) else None
                        if w_name == warrior_name:
                            warrior = w
                            break
                    if not warrior:
                        # Promoted/transcended warriors keep their roster slot until the
                        # manager rolls up a replacement - look there too.
                        for w in (team.warriors or []):
                            if w and getattr(w, "name", None) == warrior_name and \
                                    getattr(w, "current_arena", "normal") in ("elite", "veteran"):
                                warrior = w
                                break
                    if not warrior:
                        self.send_json({"success": False, "error": f"Warrior '{warrior_name}' not found"}); return
                else:
                    # Normal warrior by index
                    try:
                        idx = int(warrior_idx)
                        if 0 <= idx < len(team.warriors):
                            warrior = team.warriors[idx]
                        else:
                            self.send_json({"success": False, "error": "warrior_idx out of range"}); return
                    except (ValueError, TypeError):
                        self.send_json({"success": False, "error": "Invalid warrior_idx"}); return

                if warrior is None:
                    self.send_json({"success": False, "error": "Warrior slot is empty -- upload the team first to sync a new warrior to the server"}); return

                # Update warrior fields (handle both dict and object access)
                is_dict = isinstance(warrior, dict)

                if "armor" in b:
                    val = str(b["armor"]) if b["armor"] else "None"
                    if is_dict: warrior["armor"] = val
                    else: warrior.armor = val
                if "helm" in b:
                    val = str(b["helm"]) if b["helm"] else "None"
                    if is_dict: warrior["helm"] = val
                    else: warrior.helm = val
                if "primary_weapon" in b:
                    val = str(b["primary_weapon"]) if b["primary_weapon"] else "Open Hand"
                    if is_dict: warrior["primary_weapon"] = val
                    else: warrior.primary_weapon = val
                if "secondary_weapon" in b:
                    val = str(b["secondary_weapon"]) if b["secondary_weapon"] else "Open Hand"
                    if is_dict: warrior["secondary_weapon"] = val
                    else: warrior.secondary_weapon = val
                if "backup_weapon" in b:
                    val = str(b["backup_weapon"]) if b["backup_weapon"] else None
                    if is_dict: warrior["backup_weapon"] = val
                    else: warrior.backup_weapon = val

                # Update training slots (normalize to lowercase_underscore to match Warrior.from_dict)
                if "trains" in b:
                    trains_list = b.get("trains", [])
                    if isinstance(trains_list, list):
                        val = [str(t).lower().replace(" ", "_").replace("&", "and") for t in trains_list if t]
                        if is_dict: warrior["trains"] = val
                        else: warrior.trains = val

                # Update strategies (convert dicts to Strategy objects to avoid to_dict() failure)
                if "strategies" in b:
                    if is_dict: warrior["strategies"] = b["strategies"]
                    else: warrior.strategies = [Strategy.from_dict(s) if isinstance(s, dict) else s for s in b["strategies"]]
                if "challenge_strategies" in b:
                    if is_dict: warrior["challenge_strategies"] = b["challenge_strategies"]
                    else: warrior.challenge_strategies = [Strategy.from_dict(s) if isinstance(s, dict) else s for s in b["challenge_strategies"]]
                if "challenge_strategy_enabled" in b:
                    val = bool(b.get("challenge_strategy_enabled", False))
                    if is_dict: warrior["challenge_strategy_enabled"] = val
                    else: warrior.challenge_strategy_enabled = val
                if "want_monster_fight" in b:
                    val = bool(b.get("want_monster_fight", False))
                    if is_dict: warrior["want_monster_fight"] = val
                    else: warrior.want_monster_fight = val
                if "want_retire" in b:
                    val = bool(b.get("want_retire", False))
                    if is_dict: warrior["want_retire"] = val
                    else: warrior.want_retire = val
                if "run_this_turn" in b:
                    val = bool(b.get("run_this_turn", True))
                    if is_dict: warrior["run_this_turn"] = val
                    else: warrior.run_this_turn = val

                # Update taunts/jeers (trigger -> text dict)
                if "taunts_jeers_update" in b:
                    update = b.get("taunts_jeers_update", {})
                    trigger = update.get("trigger")
                    text = update.get("text", "").strip()
                    # Immortal (archived) warriors are plain dicts, where hasattr() is always
                    # False - the old check reset their taunts to {} on every update, so only
                    # the newest taunt survived. Look the dict up properly instead.
                    if is_dict:
                        if not isinstance(warrior.get("taunts_jeers"), dict):
                            warrior["taunts_jeers"] = {}
                    elif not isinstance(getattr(warrior, "taunts_jeers", None), dict):
                        warrior.taunts_jeers = {}
                    if trigger:
                        if text:
                            if is_dict: warrior["taunts_jeers"][trigger] = text
                            else: warrior.taunts_jeers[trigger] = text
                        else:
                            if is_dict: warrior["taunts_jeers"].pop(trigger, None)
                            else: warrior.taunts_jeers.pop(trigger, None)

                # Save main team file
                save_team(team)

                # For immortal warriors, update the arena snapshot directly by
                # loading the existing snapshot and patching only the changed fields.
                # This prevents stale combat stats in the main team file from
                # overwriting server-authoritative stats in the snapshot.
                if is_immortal:
                    arena = b.get("arena")
                    if arena in ("elite", "veteran"):
                        snap_path = os.path.join(_immortal_team_dir(arena), f"team_{team_id:04d}.json")
                        if os.path.exists(snap_path):
                            make_file_writable(snap_path)
                            with open(snap_path, "r", encoding="utf-8") as _sf:
                                snapshot = json.load(_sf)
                            # Patch only non-combat fields on the warrior in the snapshot
                            _gear_fields = ("armor", "helm", "primary_weapon", "secondary_weapon",
                                            "backup_weapon", "trains", "strategies",
                                            "challenge_strategies", "challenge_strategy_enabled",
                                            "want_monster_fight", "want_retire", "run_this_turn", "taunts_jeers")
                            # Plain-data view of the warrior (roster entries are Warrior
                            # objects whose strategies are not JSON-serializable).
                            _wsrc = warrior if isinstance(warrior, dict) else warrior.to_dict()
                            for _section in ("warriors", "archived_warriors"):
                                for _sw in (snapshot.get(_section) or []):
                                    if isinstance(_sw, dict) and _sw.get("name") == warrior_name:
                                        for _f in _gear_fields:
                                            if _f in b:
                                                _val = b[_f]
                                                if _f == "trains" and isinstance(_val, list):
                                                    _val = [str(t).lower().replace(" ", "_") for t in _val if t]
                                                _sw[_f] = _val
                                            elif _f in _wsrc:
                                                _sw[_f] = _wsrc[_f]
                                        break
                            # Serialize fully before opening the file so a failure can't
                            # leave a truncated snapshot behind.
                            _snap_text = json.dumps(snapshot, indent=2)
                            with open(snap_path, "w", encoding="utf-8") as _sf:
                                _sf.write(_snap_text)

                self.send_json({"success": True}); return

            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"success": False, "error": str(e)}); return

        self.send_json({"success": False, "error": "Unknown PUT endpoint"}); return

    def _do_POST_inner(self):
        path = self.p()
        b = self.body()

        if path in _VERSION_GATED_POST and _client_version_blocked(self, path, b.get("client_version")):
            return

        if path.startswith("/api/local/") and path != "/api/local/status" and not _is_server_machine(self):
            self.send_json({"success": False,
                            "error": "The local file API is only available on the server machine."}, 403); return

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

        if path in ("/api/rollup", "/api/rollup_single"):
            # The server remembers every roll it issues so that the stats submitted
            # later can be checked against them (see roll_registry.py). Rolls are
            # sticky per manager: asking again returns the same roll.
            mid = str(b.get("manager_id") or "").strip()
            pw  = str(b.get("password")   or "").strip()
            if not mid and not pw:
                # Older clients ask for rolls without logging in.
                _note_outdated_request(path, b)
                self.send_json({"success": False, "outdated_client": True, "error": _outdated_message(b.get("client_version"))}, 426); return
            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                    self.send_json({"success": False, "error": "Not authorised."}, 401); return
                owned_ids = [str(t) for t in mgrs[mid].get("team_ids", [])]
            rr = _roll_registry()
            if path == "/api/rollup":
                from team import TEAM_SIZE
                rolls = rr.get_team_rolls(mid, TEAM_SIZE)
                self.send_json({"rolls": [r["base"] for r in rolls],
                                "roll_ids": [r["roll_id"] for r in rolls]}); return
            try:
                tid  = int(b.get("team_id"))
                slot = int(b.get("warrior_idx"))
            except (TypeError, ValueError):
                self.send_json({"success": False, "error": "team_id and warrior_idx required."}); return
            if str(tid) not in owned_ids or not (0 <= slot < 5):
                self.send_json({"success": False, "error": "Team not found for this manager."}); return
            r = rr.get_replacement_roll(mid, tid, slot, reroll=bool(b.get("reroll")))
            self.send_json({"base": r["base"], "roll_id": r["roll_id"],
                            "rerolled": r["rerolled"], "reroll_denied": r["reroll_denied"]}); return

        if path == "/api/warrior/replace":
            # Build a replacement warrior on the server. The client sends the name,
            # race, gender and final stats it wants; the server checks them against
            # the roll it issued, rolls the warrior's luck itself, archives the
            # fallen warrior, and returns the finished warrior for the client to save.
            mid = str(b.get("manager_id") or "").strip()
            pw  = str(b.get("password")   or "").strip()
            try:
                tid  = int(b.get("team_id"))
                slot = int(b.get("warrior_idx"))
            except (TypeError, ValueError):
                self.send_json({"success": False, "error": "team_id and warrior_idx required."}); return
            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                    self.send_json({"success": False, "error": "Not authorised."}, 401); return
                if str(tid) not in [str(t) for t in mgrs[mid].get("team_ids", [])]:
                    self.send_json({"success": False, "error": "Team not found for this manager."}); return
                if _load_config().get("turn_state") == "processing":
                    self.send_json({"success": False, "error": "Turn is running. Try again shortly."}); return
            rr = _roll_registry()
            ok, res = _check_new_warrior(b, lambda rid: rr.find_replacement_roll(mid, tid, slot, rid), rr)
            if not ok:
                self.send_json({"success": False, "error": res}); return
            try:
                import random as _rand
                from save import load_team, save_team
                from warrior import Warrior
                from team import TEAM_SIZE
                team = load_team(tid)
                if not (0 <= slot < TEAM_SIZE) or slot > len(team.warriors):
                    self.send_json({"success": False, "error": "Invalid warrior slot."}); return
                old = team.warriors[slot] if slot < len(team.warriors) else None
                if old is not None and not (
                        getattr(old, "is_dead", False) or getattr(old, "is_retired", False)
                        or getattr(old, "ascended_to_monster", False) or getattr(old, "is_promoted", False)
                        or getattr(old, "current_arena", "normal") in ("elite", "veteran")):
                    self.send_json({"success": False,
                                    "error": f"{old.name} is still an active warrior and cannot be replaced."}); return
                w = Warrior(name=res["name"], race_name=res["race"], gender=res["gender"], **res["stats"])
                w.luck = _rand.randint(1, 30)
                w.initial_stats = dict(res["stats"])
                w.armor = res["armor"]
                w.helm = res["helm"]
                w.primary_weapon = res["primary_weapon"]
                w.secondary_weapon = res["secondary_weapon"]
                w.backup_weapon = res["backup_weapon"]
                w.slot_index = slot
                if old is not None:
                    snap = old.to_dict()
                    snap["archived_killed_by"] = getattr(old, "killed_by", "")
                    snap["archived_turns"] = getattr(old, "turns_active", 0)
                    # Retirees/ascended and promoted warriors were not killed; the
                    # client files them on the Shady Pines tab, not The Crypts.
                    if old.is_retired or old.ascended_to_monster:
                        snap["archived_retired"] = True
                    if old.is_promoted:
                        snap["archived_promoted"] = True
                    team.archived_warriors.append(snap)
                if slot == len(team.warriors):
                    team.warriors.append(w)
                else:
                    team.warriors[slot] = w
                team.pending_replacements.pop(slot, None)
                save_team(team)
                rr.consume_replacement_roll(mid, tid, slot)
            except FileNotFoundError:
                self.send_json({"success": False, "error": "The server has no record of this team."}); return
            except Exception as e:
                import traceback; traceback.print_exc()
                self.send_json({"success": False, "error": f"{e}"}); return
            _log_activity("warrior_replaced", mid, mgrs[mid]["manager_name"],
                          f"Team {tid} slot {slot}: {res['name']} replaces "
                          f"{getattr(old, 'name', '(empty)')}")
            self.send_json({"success": True, "warrior": w.to_dict()}); return

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
            if len(warriors_data) != TEAM_SIZE:
                self.send_json({"success":False,"error":f"Need exactly {TEAM_SIZE} warriors."}); return
            if len(team_name) > 25:
                self.send_json({"success":False,"error":"Team name must be 25 characters or fewer."}); return
            # Every warrior's stats must be a roll THIS SERVER issued to this manager
            # plus a legal spend of the 16 points. Nothing else is accepted.
            rr = _roll_registry()
            checked = []
            seen_rolls = set()
            for wd in warriors_data:
                ok, res = _check_new_warrior(wd, lambda rid: rr.find_team_roll(mid, rid), rr)
                if not ok:
                    self.send_json({"success":False,"error":res}); return
                if wd.get("roll_id") in seen_rolls:
                    self.send_json({"success":False,"error":"The same stat roll was used twice."}); return
                seen_rolls.add(wd.get("roll_id"))
                checked.append(res)
            try:
                team = Team(
                    team_name    = team_name.upper(),
                    manager_name = manager_name,
                    team_id      = next_team_id(),
                )
                import random as _rand
                for cw in checked:
                    w = Warrior(
                        name         = cw["name"],
                        race_name    = cw["race"],
                        gender       = cw["gender"],
                        **cw["stats"],
                    )
                    w.luck = _rand.randint(1, 30)
                    w.initial_stats = dict(cw["stats"])
                    w.armor = cw["armor"]
                    w.helm = cw["helm"]
                    w.primary_weapon = cw["primary_weapon"]
                    w.secondary_weapon = cw["secondary_weapon"]
                    w.backup_weapon = cw["backup_weapon"]
                    team.add_warrior(w)
                rr.consume_team_rolls(mid)
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
                _record_client_version(mid, mgrs[mid]["manager_name"], b)
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

                # VALIDATION & AUTO-ASSIGN: Detect and auto-assign missing warrior_ids
                # If a manager's upload is missing warrior_ids, it indicates the client is not
                # properly preserving them, which can cause stats to be inherited from other
                # warriors with the same name. See: name-reuse bug (turn 48).
                if isinstance(team, dict) and team_id:
                    from save import enforce_unique_active_ids, restore_archived_ids
                    for _n, _old, _new in enforce_unique_active_ids(team, team_id):
                        print(f"  INFO: team_{team_id} warrior '{_n}' id {_old} -> {_new} (server-issued, unique)")
                    restore_archived_ids(team, team_id)

                # SERVER-AUTHORITATIVE REBUILD: the turn runner fights whatever is in the
                # saved upload, so it must never contain client-supplied stats. Every
                # warrior is rebuilt from the server's own copy; only the settings a
                # manager may change (gear, training picks, strategies, flags, taunts)
                # are taken from the upload, after validation. See upload_guard.py.
                # Set "strict_upload_validation": false in config.json to fall back to
                # accepting warriors the server has no record of (data-recovery only).
                if isinstance(team, dict):
                    from upload_guard import sanitize_uploaded_team, build_lookups, UploadRejected
                    try:
                        _guard_notes = sanitize_uploaded_team(
                            team,
                            _load_team_file_dict(team_id) if team_id else None,
                            build_lookups(),
                            manager_name=mgrs[mid]["manager_name"],
                            strict=bool(cfg.get("strict_upload_validation", True)),
                        )
                    except UploadRejected as _rej:
                        _log_activity("upload_rejected", mid, mgrs[mid]["manager_name"], str(_rej))
                        self.send_json({"success": False, "error": str(_rej)}); return
                    for _gn in _guard_notes:
                        _log_activity("upload_tampering", mid, mgrs[mid]["manager_name"],
                                      f"team {team_id}: {_gn}")

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

                # 'Run Next Turn' travels with the team dict. A team with the box
                # unchecked is still uploaded -- it is only marked as sitting out, so
                # the turn runner skips it and the admin panel can report it.
                _runs_this_turn = True
                if isinstance(team, dict):
                    _runs_this_turn = bool(team.get("auto_upload_enabled", True))

                upload_time = time.strftime("%Y-%m-%d %H:%M:%S")
                _save_upload(turn_num, mid, {
                    "manager_id" : mid,
                    "manager_name": mgrs[mid]["manager_name"],
                    "team_id" : team_id,
                    "team" : team,
                    "uploaded_at" : upload_time,
                    "auto_upload_enabled": _runs_this_turn,
                })

                # --- FIX: Update persistent team file immediately ---
                # This ensures that a subsequent download/sync gets the version with the replacement
                from team import Team
                from save import save_team, load_team
                try:
                    t_obj = Team.from_dict(team)
                    # Server-computed combat stats must never be overwritten by a client
                    # upload, for ANY warrior -- not just ones promoted to the immortal
                    # arena. A manager's local client can fall behind the server (stale
                    # cache, missed sync, an unmerged bugfix, etc.), and if its upload is
                    # trusted verbatim, a stale value silently clobbers the server's
                    # authoritative one and corrupts data the client had no business
                    # editing in the first place (e.g. recognition, which the server alone
                    # computes after every fight).
                    try:
                        existing = load_team(int(team_id))
                        # Build lookup of warrior ID -> server-authoritative data.
                        # CRITICAL: Must use warrior_id, not name, to prevent name-reuse bugs.
                        # When a manager reuses a warrior name (after the old one died),
                        # matching by name alone causes the new warrior to inherit the old
                        # warrior's stats. See: COME THE CARNIVORE, THE BLACKENING (turn 48).
                        _server_authoritative = {}
                        _combat_fields = ("current_arena", "wins", "losses", "kills",
                                          "fight_history", "recognition", "total_fights",
                                          "popularity", "is_dead", "is_promoted", "pending_promotion")
                        for _ew in (existing.warriors or []):
                            if _ew and _ew.warrior_id is not None:
                                _server_authoritative[_ew.warrior_id] = {
                                    f: getattr(_ew, f, None) for f in _combat_fields
                                }
                        for _ew in (getattr(existing, "archived_warriors", []) or []):
                            # An archived copy must never override the ACTIVE warrior with the
                            # same id: stale duplicates (e.g. MARVIN, JEEPERS) held an old
                            # record and silently reset the live warrior's wins/losses/kills.
                            if (isinstance(_ew, dict) and _ew.get("warrior_id") is not None
                                    and _ew.get("warrior_id") not in _server_authoritative):
                                _server_authoritative[_ew.get("warrior_id")] = {
                                    f: _ew.get(f) for f in _combat_fields
                                }
                        # Apply server-authoritative data to the incoming team object
                        if _server_authoritative:
                            for _uw in (t_obj.warriors or []):
                                if _uw and _uw.warrior_id is not None and _uw.warrior_id in _server_authoritative:
                                    for _f, _v in _server_authoritative[_uw.warrior_id].items():
                                        if _v is not None:
                                            setattr(_uw, _f, _v)
                            for _uw in (getattr(t_obj, "archived_warriors", []) or []):
                                if isinstance(_uw, dict) and _uw.get("warrior_id") and _uw.get("warrior_id") in _server_authoritative:
                                    for _f, _v in _server_authoritative[_uw.get("warrior_id")].items():
                                        if _v is not None:
                                            _uw[_f] = _v
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
            _sit_note = "" if _runs_this_turn else " (sitting out -- 'Run Next Turn' unchecked)"
            _log_activity("upload_success", mid, mgrs[mid]["manager_name"],
                        f"Team {team_name} (ID:{team_id}) uploaded for turn {turn_num}{_sit_note}")
            _msg = (f"Team uploaded for turn {turn_num}." if _runs_this_turn
                    else f"Team uploaded for turn {turn_num}, marked to sit this turn out.")
            self.send_json({"success":True,"turn":turn_num,"message":_msg}); return

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
            _add_warrior_to_immortal_team(target, team.to_dict(), warrior.name)
            _disp = {"elite": "The Elite Spire", "veteran": "THE SOUL SPIRE"}.get(target, target)
            self.send_json({"success": True,
                            "message": f"{warrior.name} has been manually promoted to {_disp}.",
                            "warrior": warrior.name, "team": team.team_name, "arena": target}); return

        if path == "/api/immortal_upload":
            # Upload team data for an immortal arena (Elite Spire or Soul Spire).
            # Completely separate from the normal-arena upload -- writes to
            # saves/{arena}/uploads/team_XXXX.json only.
            # Body: {arena, team_id, team, manager_id, password}
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
            _ok, _who, _code = _authorize_team_owner(b, _i_tid, arena=_i_arena)
            if not _ok:
                self.send_json({"success": False, "error": _who}, _code); return
            from upload_guard import clean_settings, build_lookups
            _i_lookups = build_lookups()
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
                        # Take ONLY the settings a manager can change from the upload.
                        # Everything else (record, history, recognition, injuries,
                        # skills, attributes, training gains, HP...) is computed by the
                        # server; clients build Spire uploads from the warrior's
                        # regular-arena copy, so trusting those fields wiped Spire training.
                        _iw.update(clean_settings(_src, _iw, _i_lookups))
            if _i_arena == "veteran":
                # A warrior who took the final Soul Spire death stays grayed out until
                # the manager uploads; then they leave the Soul Spire roster for good.
                for _section in ("warriors", "archived_warriors"):
                    if _section in _i_merged:
                        _i_merged[_section] = [w for w in (_i_merged.get(_section) or [])
                                               if not (isinstance(w, dict) and w.get("soul_spire_final_death"))]
                try:
                    _purge_soul_fallen_from_team_file(_i_tid)
                except Exception as _pe:
                    print(f"  WARNING: could not clear fallen Soul Spire warriors for team {_i_tid}: {_pe}")
            with open(_iu_path, "w", encoding="utf-8") as _f:
                json.dump(_i_merged, _f, indent=2)
            self.send_json({"success": True, "arena": _i_arena,
                            "team_id": _i_tid,
                            "message": f"Team {_i_tid} uploaded for {_i_arena}."}); return

        if path == "/api/admin/retire_warrior":
            # Retire a warrior directly to THE SOUL SPIRE (manager request path).
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
                            "message": f"{warrior.name} is marked for retirement to THE SOUL SPIRE. "
                                       f"They will fight one final bout next turn before moving.",
                            "warrior": warrior.name, "team": team.team_name}); return

        if path == "/api/admin/move_to_elite":
            # Move a warrior from Soul Spire (veteran) to Elite Spire.
            # Body: {host_password, team_id, warrior_name}
            pw     = b.get("host_password", "")
            cfg    = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            tid    = int(b.get("team_id", -1))
            w_name = str(b.get("warrior_name", "")).strip()

            vet_team_dict = None
            warrior_dict = None
            warrior_idx = -1
            warrior_section = None
            team_name = ""
            manager_name = ""

            # Try loading from veteran arena first
            vet_teams = _load_immortal_teams("veteran")
            vet_team_dict = next((t for t in vet_teams if int(t.get("team_id", 0)) == tid), None)

            # If not found in veteran arena, search in normal arena for warriors marked as veteran
            if not vet_team_dict:
                from save import load_team
                try:
                    normal_team = load_team(tid)
                    if normal_team:
                        vet_team_dict = normal_team.to_dict()
                except Exception:
                    pass

            if not vet_team_dict:
                self.send_json({"success": False, "error": f"Team {tid} not found."}); return

            team_name = vet_team_dict.get("team_name")
            manager_name = vet_team_dict.get("manager_name")

            # Check main warriors list
            for i, w in enumerate(vet_team_dict.get("warriors") or []):
                if w and w.get("name") == w_name:
                    # Verify warrior is marked as veteran
                    if w.get("current_arena") == "veteran":
                        warrior_dict = w
                        warrior_idx = i
                        warrior_section = "warriors"
                        break

            # Check archived_warriors if not found in main list
            if not warrior_dict:
                for i, w in enumerate(vet_team_dict.get("archived_warriors") or []):
                    if w and w.get("name") == w_name:
                        if w.get("current_arena") == "veteran":
                            warrior_dict = w
                            warrior_idx = i
                            warrior_section = "archived_warriors"
                            break

            if not warrior_dict:
                self.send_json({"success": False, "error": f"Warrior '{w_name}' not found or not marked as in Soul Spire."}); return

            # Move to elite
            warrior_dict["current_arena"] = "elite"
            warrior_dict["pending_promotion"] = None
            warrior_dict["recognition"] = 0
            # The Soul Spire death limit no longer applies once a warrior is in the Elite Spire.
            warrior_dict["soul_spire_deaths"] = 0
            warrior_dict["soul_spire_final_death"] = False

            # Save updated team (with warrior removed)
            if warrior_section == "warriors":
                vet_team_dict["warriors"][warrior_idx] = None
            else:
                vet_team_dict["archived_warriors"].pop(warrior_idx)

            # Save to appropriate location
            if vet_teams:  # Was found in veteran arena
                _save_immortal_team("veteran", vet_team_dict)
            else:  # Was found in normal arena
                from save import save_team
                from team import Team
                normal_team = Team.from_dict(vet_team_dict)
                save_team(normal_team)

            # Load or create elite team and add warrior
            elite_teams = _load_immortal_teams("elite")
            elite_team_dict = next((t for t in elite_teams if int(t.get("team_id", 0)) == tid), None)
            if not elite_team_dict:
                # Create new elite team if doesn't exist
                elite_team_dict = {
                    "team_name": team_name,
                    "manager_name": manager_name,
                    "team_id": tid,
                    "warriors": [],
                    "archived_warriors": []
                }

            # Add warrior to elite team
            elite_team_dict["warriors"] = elite_team_dict.get("warriors") or []
            elite_team_dict["warriors"].append(warrior_dict)
            _save_immortal_team("elite", elite_team_dict)

            self.send_json({"success": True,
                            "message": f"{warrior_dict.get('name')} has been moved from The Soul Spire to The Elite Spire.",
                            "warrior": warrior_dict.get('name'), "team": team_name}); return

        if path == "/api/admin/remove_from_elite":
            # Remove a warrior from The Elite Spire.
            # Body: {host_password, team_id, warrior_name}
            pw     = b.get("host_password", "")
            cfg    = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            tid    = int(b.get("team_id", -1))
            w_name = str(b.get("warrior_name", "")).strip()

            # Load warrior from elite arena
            elite_teams = _load_immortal_teams("elite")
            elite_team_dict = next((t for t in elite_teams if int(t.get("team_id", 0)) == tid), None)
            if not elite_team_dict:
                self.send_json({"success": False, "error": f"Team {tid} not found in elite arena."}); return

            warrior_idx = -1
            warrior_section = None

            # Check main warriors list
            for i, w in enumerate(elite_team_dict.get("warriors") or []):
                if w and w.get("name") == w_name:
                    warrior_idx = i
                    warrior_section = "warriors"
                    break

            # Check archived_warriors if not found in main list
            if warrior_idx == -1:
                for i, w in enumerate(elite_team_dict.get("archived_warriors") or []):
                    if w and w.get("name") == w_name:
                        warrior_idx = i
                        warrior_section = "archived_warriors"
                        break

            if warrior_idx == -1:
                self.send_json({"success": False, "error": f"Warrior '{w_name}' not found in elite team."}); return

            # Remove warrior from elite roster
            if warrior_section == "warriors":
                removed_warrior = elite_team_dict["warriors"].pop(warrior_idx)
            else:
                removed_warrior = elite_team_dict["archived_warriors"].pop(warrior_idx)
            _save_immortal_team("elite", elite_team_dict)

            self.send_json({"success": True,
                            "message": f"{removed_warrior.get('name')} has been removed from The Elite Spire.",
                            "warrior": removed_warrior.get('name'), "team": elite_team_dict.get("team_name")}); return

        if path == "/api/admin/restore_to_elite":
            # Restore a warrior to Elite Spire by searching all teams by name and record.
            # Body: {host_password, warrior_name, wins, losses}
            pw     = b.get("host_password", "")
            cfg    = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            w_name = str(b.get("warrior_name", "")).strip()
            wins   = int(b.get("wins", -1))
            losses = int(b.get("losses", -1))

            if wins < 0 or losses < 0:
                self.send_json({"success": False, "error": "wins and losses required"}); return

            # Search all teams for this warrior
            from save import load_all_teams, save_team
            all_teams = load_all_teams()

            found_warrior = None
            found_team = None
            found_idx = -1

            for team in all_teams:
                for i, w in enumerate(team.warriors or []):
                    if w and w.name == w_name and w.wins == wins and w.losses == losses:
                        found_warrior = w
                        found_team = team
                        found_idx = i
                        break
                if found_warrior:
                    break

            if not found_warrior:
                self.send_json({"success": False, "error": f"Warrior '{w_name}' with record {wins}W-{losses}L not found in any team."}); return

            # Move to elite
            found_warrior.current_arena = "elite"
            found_warrior.pending_promotion = None
            found_warrior.recognition = 0

            # Save updated normal team
            save_team(found_team)

            # Load or create elite team and add warrior
            elite_teams = _load_immortal_teams("elite")
            elite_team_dict = next((t for t in elite_teams if int(t.get("team_id", 0)) == found_team.team_id), None)
            if not elite_team_dict:
                # Create new elite team
                elite_team_dict = {
                    "team_name": found_team.team_name,
                    "manager_name": found_team.manager_name,
                    "team_id": found_team.team_id,
                    "warriors": [],
                    "archived_warriors": []
                }

            # Add warrior to elite team
            elite_team_dict["warriors"] = elite_team_dict.get("warriors") or []
            elite_team_dict["warriors"].append(found_warrior.to_dict())
            _save_immortal_team("elite", elite_team_dict)

            self.send_json({"success": True,
                            "message": f"{found_warrior.name} ({wins}W-{losses}L) from team {found_team.team_name} has been restored to The Elite Spire.",
                            "warrior": found_warrior.name, "team": found_team.team_name, "record": f"{wins}W-{losses}L"}); return

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

            _disp = {"elite": "The Elite Spire", "veteran": "THE SOUL SPIRE"}.get(target, target)

            # 1. Search active warriors list (Warrior objects)
            warrior = next((w for w in (team.warriors or []) if w and w.name == w_name), None)
            if warrior is not None:
                if not warrior.is_dead:
                    self.send_json({"success": False,
                                    "error": f"{warrior.name} is not dead. Use promote_warrior instead."}); return
                # Leave the warrior in his roster slot, flagged as promoted, like a normal
                # transcension. Emptying the slot left managers with no replacement option
                # (the client skips null slots).
                warrior.is_dead           = False
                warrior.is_promoted       = True
                warrior.current_arena     = target
                warrior.pending_promotion = None
                warrior.recognition       = 0
                warrior.hp = max(1, getattr(warrior, "max_hp", 100))
                save_team(team)
                _add_warrior_to_immortal_team(target, team.to_dict(), warrior.name)
                self.send_json({"success": True,
                                "message": f"{warrior.name} has been resurrected and placed in {_disp}.",
                                "warrior": warrior.name, "team": team.team_name, "arena": target}); return

            # 2. Search archived_warriors (raw dicts -- historical dead)
            arch_idx = next(
                (i for i, w in enumerate(team.archived_warriors or [])
                 if isinstance(w, dict) and w.get("name") == w_name),
                None
            )
            if arch_idx is None:
                self.send_json({"success": False,
                                "error": f"Warrior '{w_name}' not found in team {tid}."}); return
            arch_dict = team.archived_warriors[arch_idx]
            # Update the archived entry in-place -- no roster slot consumed.
            # Immortal arena warriors live in archived_warriors with is_dead=False.
            arch_dict["is_dead"]           = False
            arch_dict["current_arena"]     = target
            arch_dict["pending_promotion"] = None
            arch_dict["recognition"]       = 0
            arch_dict["hp"] = max(1, int(arch_dict.get("max_hp") or arch_dict.get("hp") or 100))
            save_team(team)
            _add_warrior_to_immortal_team(target, team.to_dict(), arch_dict["name"])
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
            min_win_rate = float(promo_cfg.get("min_win_rate", 0.65))
            min_trains   = int(promo_cfg.get("min_trains",   45))
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
                        "total_trains": _warrior_total_trains(w), "min_trains": min_trains,
                    }
                    if getattr(w, "pending_promotion", None):
                        pending.append(entry)
                    elif (total >= min_fights and wr >= min_win_rate
                          and entry["total_trains"] >= min_trains):
                        eligible.append(entry)
                    else:
                        ineligible.append(entry)
            self.send_json({"success": True, "pending": pending,
                            "eligible": eligible, "ineligible": ineligible}); return

        if path == "/api/admin/ai_learning_report":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}); return
            try:
                from ai_brain import get_brain
                brain = get_brain()
                rep_txt = brain.learning_report(float(b.get("min_n", 5)))
                if not brain.kb.get("diagnostics"):
                    rep_txt = "No fight diagnostics recorded yet - run a turn and they will appear here."
                self.send_json({"success": True, "report": rep_txt})
            except Exception as e:
                self.send_json({"success": False, "error": f"Could not build report: {e}"})
            return

        if path == "/api/admin/promotion_panel_data":
            # Unified data for the Manage Promotions admin panel.
            # Scans both team.warriors (Warrior objects) and team.archived_warriors (dicts).
            # Dead warriors: all with 1+ fight shown -- no win-rate pre-filter, admin decides.
            pw  = b.get("host_password", "")
            cfg = _load_config()
            if not _check_host_pw(cfg, pw):
                self.send_json({"success": False, "error": "Not authorised."}); return
            promo_cfg    = cfg.get("promotion_criteria", {})
            min_fights   = int(promo_cfg.get("min_fights",   40))
            min_win_rate = float(promo_cfg.get("min_win_rate", 0.65))
            min_trains   = int(promo_cfg.get("min_trains",   45))
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

            def _race_name(w):
                r = _wval(w, "race")
                return getattr(r, "name", r)

            # Warriors currently on an Elite/Soul Spire roster, per the arenas' own
            # team files. A resurrected warrior can still have an old dead copy on
            # the regular team (archive or a re-uploaded roster) - never list those.
            _immortal_ids, _immortal_names = set(), set()
            for _arena in ("elite", "veteran"):
                for _td in _load_immortal_teams(_arena):
                    for _iw in (_td.get("warriors") or []) + (_td.get("archived_warriors") or []):
                        if isinstance(_iw, dict) and not _iw.get("is_dead", False):
                            if _iw.get("warrior_id") is not None:
                                _immortal_ids.add(_iw["warrior_id"])
                            _immortal_names.add((_td.get("team_id"), _iw.get("name"), _race_name(_iw)))

            def _in_immortal_arena(team_id, w):
                # Same warrior_id, or same team + name + race (old duplicate copies of
                # one warrior can carry different ids). Race keeps a different warrior
                # who later reused the name on that team from being hidden.
                wid = _wval(w, "warrior_id")
                if wid is not None and wid in _immortal_ids:
                    return True
                return (team_id, _wval(w, "name"), _race_name(w)) in _immortal_names

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
                        if _in_immortal_arena(team.team_id, w):
                            continue
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

                # --- archived warriors (dicts -- historical dead + immortal arena members) ---
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
                    # Old dead copy of a warrior who has since been resurrected
                    if _in_immortal_arena(team.team_id, w):
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
                # Check both active warriors AND archived (post-replacement) warriors
                all_w = list(team.warriors or []) + list(getattr(team, "archived_warriors", None) or [])
                for w in all_w:
                    if not w:
                        continue
                    if getattr(w, "current_arena", "normal") == arena:
                        w.current_arena     = "normal"
                        w.pending_promotion = None
                        w.is_promoted       = False
                        moved  += 1
                        changed = True
                    # Also clear any warriors pending INTO this arena from normal
                    if getattr(w, "pending_promotion", None) == arena:
                        w.pending_promotion = None
                        changed = True
                if changed:
                    try:
                        save_team(team)
                    except Exception as _se:
                        print(f"  WARNING clear_arena: save_team failed: {_se}")
            # Delete the arena's own team files so _load_immortal_teams returns empty
            arena_teams_dir = os.path.join(BASE_DIR, "saves", arena, "teams")
            if os.path.isdir(arena_teams_dir):
                import glob as _glob
                for _tf in _glob.glob(os.path.join(arena_teams_dir, "*.json")):
                    try:
                        os.remove(_tf)
                        _cs = _tf.replace(".json", ".checksum")
                        if os.path.exists(_cs):
                            os.remove(_cs)
                    except Exception as _de:
                        print(f"  WARNING clear_arena: could not delete {_tf}: {_de}")
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
            _disp = {"elite": "The Elite Spire", "veteran": "THE SOUL SPIRE"}.get(arena, arena)
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
            _disp = {"elite": "THE ELITE SPIRE", "veteran": "THE SOUL SPIRE"}.get(arena, arena.upper())
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

        if path == "/api/team/challenge":
            # Add or remove a challenge for a warrior in a team.
            # Works for both normal and immortal (elite/veteran) arena teams.
            # Body: {team_id, warrior_name, target_name, action, password, manager_id}
            mid   = str(b.get("manager_id") or "").strip()
            pw    = str(b.get("password")   or "").strip()
            tid   = int(b.get("team_id", -1))
            w_name = str(b.get("warrior_name", "")).strip()
            t_name = str(b.get("target_name", "")).strip()
            action = str(b.get("action", "add")).strip()
            arena_req = str(b.get("arena") or "normal").strip()
            if arena_req not in ("normal", "elite", "veteran"):
                arena_req = "normal"

            if not all([mid, pw, w_name, t_name]):
                self.send_json({"success":False,"error":"manager_id, password, warrior_name, target_name required."}); return

            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                    self.send_json({"success":False,"error":"Not authorised."}, 401); return

                if tid not in mgrs[mid].get("team_ids", []) and tid not in mgrs[mid].get("immortal_team_ids", []):
                    self.send_json({"success":False,"error":"Team does not belong to this manager."}); return

            from save import load_team_any_arena, save_team
            from team import Team

            # Load the team from the arena the client is viewing. A team can exist
            # in several arena dirs at once (normal roster plus promoted immortals),
            # so load_team_any_arena -- which returns the normal copy first -- would
            # miss an immortal warrior. Load the requested arena's file directly.
            try:
                if arena_req in ("elite", "veteran"):
                    _fp = os.path.join(_immortal_team_dir(arena_req), f"team_{tid:04d}.json")
                    if not os.path.exists(_fp):
                        self.send_json({"success":False,"error":f"Team {tid} not found in {arena_req} arena."}); return
                    team_dict = load_json_protected(_fp, allow_tampered=True)
                else:
                    team_dict = load_team_any_arena(tid)
            except (FileNotFoundError, ValueError):
                self.send_json({"success":False,"error":f"Team {tid} not found."}); return

            if not isinstance(team_dict, dict):
                self.send_json({"success":False,"error":f"Team {tid} not found."}); return

            # Locate the challenging warrior. Normal-arena warriors live in the
            # active roster ("warriors") and are keyed by slot_index. Immortal-arena
            # warriors (Elite/Soul Spire) live in "archived_warriors" with an empty
            # active roster and an unreliable slot_index, so they are keyed by name
            # -- matchmaking resolves challenge keys by warrior name as a fallback.
            challenge_key = None
            warrior_arena = "normal"
            for w in (team_dict.get("warriors") or []):
                if isinstance(w, dict) and w.get("name") == w_name:
                    si = w.get("slot_index")
                    challenge_key = str(si) if si is not None else w_name
                    warrior_arena = w.get("current_arena") or "normal"
                    break
            if challenge_key is None:
                for w in (team_dict.get("archived_warriors") or []):
                    if isinstance(w, dict) and w.get("name") == w_name and not w.get("is_dead", False):
                        challenge_key = w_name  # name-keyed for immortal warriors
                        warrior_arena = w.get("current_arena") or "normal"
                        break

            if challenge_key is None:
                self.send_json({"success":False,"error":f"Warrior '{w_name}' not found in team {tid}."}); return

            # Update the challenges map (keys are strings in the stored dict).
            challenges = team_dict.get("challenges")
            if not isinstance(challenges, dict):
                challenges = {}
            current = list(challenges.get(challenge_key) or [])
            if action == 'remove':
                current = [t for t in current if t != t_name]
            else:  # add
                if t_name not in current:
                    if len(current) >= 3:
                        self.send_json({"success":False,"error":"A warrior may queue at most 3 challenges per turn."}); return
                    current.append(t_name)
            challenges[challenge_key] = current
            team_dict["challenges"] = challenges

            # Persist to the correct arena location.
            try:
                if warrior_arena in ("elite", "veteran"):
                    _save_immortal_team(warrior_arena, team_dict)
                else:
                    save_team(Team.from_dict(team_dict))
                self.send_json({"success":True,"team":team_dict}); return
            except Exception as e:
                self.send_json({"success":False,"error":f"Failed to save team: {str(e)}"}); return

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
                    # Return elite/veteran teams so client can restore local copies
                    from save import load_team_any_arena
                    for tid in mgrs[mid].get("immortal_team_ids", []):
                        try:
                            team_dict = load_team_any_arena(int(tid))
                            teams_out.append({"team_id": int(tid), "team": team_dict})
                        except Exception:
                            pass
                    _save_managers(mgrs)
                    self.send_json({"success": True, "teams": teams_out, "full_reset": False, "clear_local_results": True}); return
                else:
                    # Manager no longer exists (full reset) - just acknowledge
                    self.send_json({"success": True, "teams": [], "full_reset": True, "clear_local_results": True}); return

        if path == "/api/league/list_archives":
            mid = str(b.get("manager_id") or "").strip()
            mgrs = _load_managers()

            if mid not in mgrs:
                self.send_json({"success": False, "error": "Manager not found"}); return

            manager_name = mgrs[mid].get("name", "Unknown")
            archive_base = os.path.join(SAVES_DIR, "fight_archives")
            manager_dir = os.path.join(archive_base, manager_name.replace(" ", "_"))

            archives = []
            if os.path.isdir(manager_dir):
                for filename in sorted(os.listdir(manager_dir)):
                    if filename.endswith('.json') and filename.startswith('team_'):
                        filepath = os.path.join(manager_dir, filename)
                        try:
                            data = load_json_protected(filepath)
                            file_size = os.path.getsize(filepath)
                            warrior_count = len(data.get("warriors", []))
                            fight_count = sum(len(w.get("fights", [])) for w in data.get("warriors", []))
                            created_at = data.get("export_metadata", {}).get("created_at", "")
                            team_name = data.get("export_metadata", {}).get("team_name", "Unknown")
                            archives.append({
                                "filename": filename,
                                "team_id": data.get("export_metadata", {}).get("team_id"),
                                "team_name": team_name,
                                "size_bytes": file_size,
                                "warriors": warrior_count,
                                "fights": fight_count,
                                "created_at": created_at
                            })
                        except Exception as e:
                            print(f"  WARNING: Could not read archive {filename}: {e}")

            self.send_json({"success": True, "archives": archives, "manager_name": manager_name}); return

        if path == "/api/league/download_archive":
            mid = str(b.get("manager_id") or "").strip()
            filename = str(b.get("filename") or "").strip()

            # Validate filename - must be a team archive
            if not filename or not filename.startswith('team_') or not filename.endswith('.json'):
                self.send_json({"success": False, "error": "Invalid archive filename"}); return

            mgrs = _load_managers()
            if mid not in mgrs:
                self.send_json({"success": False, "error": "Manager not found"}); return

            manager_name = mgrs[mid].get("name", "Unknown")
            archive_base = os.path.join(SAVES_DIR, "fight_archives")
            manager_dir = os.path.join(archive_base, manager_name.replace(" ", "_"))
            filepath = os.path.join(manager_dir, filename)

            # Verify file exists and is in the right directory (prevent directory traversal)
            if not os.path.isfile(filepath) or not os.path.abspath(filepath).startswith(os.path.abspath(manager_dir)):
                self.send_json({"success": False, "error": "Archive not found"}); return

            try:
                data = load_json_protected(filepath)
                # Return as JSON - client will handle the download
                self.send_json({"success": True, "archive": data, "filename": filename}); return
            except Exception as e:
                self.send_json({"success": False, "error": f"Could not read archive: {str(e)}"}); return

        if path == "/api/admin/export_archives":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password","")):
                self.send_json({"success":False,"error":"Not authorised."}); return

            try:
                from save import create_fight_archives
                result = create_fight_archives()
                self.send_json(result); return
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"success": False, "error": f"Export failed: {str(e)}"}); return

        if path == "/api/arena/reset_selective":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password","")):
                self.send_json({"success":False,"error":"Not authorised."}); return

            try:
                from save import reset_arena_selective
                with _lock:
                    result = reset_arena_selective()
                self.send_json(result); return
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"success": False, "error": f"Reset failed: {str(e)}"}); return

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
                             "github_push_enabled", "immortal_arenas_enabled",
                             "ai_happenings_enabled"):
                if bool_key in b:
                    cfg[bool_key] = bool(b[bool_key])
            if "ai_manager_count" in b:
                try:
                    cfg["ai_manager_count"] = max(1, min(20, int(b["ai_manager_count"])))
                except (TypeError, ValueError):
                    self.send_json({"success":False,"error":"AI manager count must be a number from 1 to 20."}, 400); return
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

        if path == "/api/admin/reset_immortal_to_turn1":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return
            arena = str(b.get("arena", "")).strip()
            if arena not in ("elite", "veteran"):
                self.send_json({"success": False, "error": "arena must be 'elite' or 'veteran'"}); return
            arena_dir = os.path.join(BASE_DIR, "saves", arena)
            arena_cfg_path = os.path.join(arena_dir, "config.json")

            # Delete all turn_XXXX/ subdirectories (newsletters, fight results)
            turns_cleared = 0
            if os.path.isdir(arena_dir):
                for entry in os.listdir(arena_dir):
                    if entry.startswith("turn_"):
                        turn_path = os.path.join(arena_dir, entry)
                        if os.path.isdir(turn_path):
                            try:
                                shutil.rmtree(turn_path, ignore_errors=True)
                                turns_cleared += 1
                            except Exception:
                                pass

            # Revert warrior records by stripping this arena's fights from fight_history
            warriors_reverted = 0
            teams_dir = os.path.join(arena_dir, "teams")
            if os.path.isdir(teams_dir):
                for fname in os.listdir(teams_dir):
                    if not (fname.startswith("team_") and fname.endswith(".json")):
                        continue
                    team_path = os.path.join(teams_dir, fname)
                    try:
                        with open(team_path, encoding="utf-8") as _f:
                            team_data = json.load(_f)

                        def _revert_warrior(w):
                            if not isinstance(w, dict):
                                return w
                            history = w.get("fight_history") or []
                            # Keep only fights NOT from this immortal arena
                            pre_arena = [f for f in history if f.get("arena") != arena]
                            arena_fights = [f for f in history if f.get("arena") == arena]
                            # Take this arena's fights off the record rather than rebuilding
                            # it from the remaining history: older histories can hold extra
                            # entries (e.g. a previous warrior of the same name), and the
                            # record field is the verified career record.
                            wins   = max(0, (w.get("wins")   or 0) - sum(1 for f in arena_fights if f.get("result") == "win"))
                            losses = max(0, (w.get("losses") or 0) - sum(1 for f in arena_fights if f.get("result") == "loss"))
                            kills  = max(0, (w.get("kills")  or 0) - sum(1 for f in arena_fights if f.get("is_kill")))
                            w["wins"]         = wins
                            w["losses"]       = losses
                            w["kills"]        = kills
                            w["total_fights"] = wins + losses
                            w["fight_history"] = pre_arena
                            # Warriors start each arena with 0 recognition
                            w["recognition"]   = 0
                            return w

                        changed = False
                        if team_data.get("warriors"):
                            new_ws = []
                            for w in team_data["warriors"]:
                                if w and any(f.get("arena") == arena for f in (w.get("fight_history") or [])):
                                    w = _revert_warrior(w)
                                    warriors_reverted += 1
                                    changed = True
                                new_ws.append(w)
                            team_data["warriors"] = new_ws
                        if team_data.get("archived_warriors"):
                            new_aws = []
                            for w in team_data["archived_warriors"]:
                                if w and isinstance(w, dict) and any(f.get("arena") == arena for f in (w.get("fight_history") or [])):
                                    w = _revert_warrior(w)
                                    warriors_reverted += 1
                                    changed = True
                                new_aws.append(w)
                            team_data["archived_warriors"] = new_aws
                        if changed:
                            with open(team_path, "w", encoding="utf-8") as _f:
                                json.dump(team_data, _f, indent=2)
                    except Exception as _we:
                        print(f"  WARNING reset_immortal: could not process {fname}: {_we}")

            # Reset turn_counter to 0 and state to open in arena config
            if os.path.exists(arena_cfg_path):
                with open(arena_cfg_path, encoding="utf-8") as _f:
                    arena_cfg = json.load(_f)
            else:
                arena_cfg = {}
            arena_cfg["turn_counter"] = 0
            arena_cfg["turn_state"] = "open"
            arena_cfg.pop("processing_started_at", None)
            with open(arena_cfg_path, "w", encoding="utf-8") as _f:
                json.dump(arena_cfg, _f, indent=2)

            # Clear the career standings - each turn adds onto this file, so stale
            # totals would be counted again when turn 1 is re-run.
            with open(os.path.join(arena_dir, "standings.json"), "w", encoding="utf-8") as _f:
                json.dump({"teams": {}, "turn": 0}, _f, indent=2)

            _disp = {"elite": "The Elite Spire", "veteran": "The Soul Spire"}.get(arena, arena)
            self.send_json({"success": True,
                "message": f"{_disp} reset to Turn 1. {turns_cleared} newsletter turn(s) cleared. {warriors_reverted} warrior record(s) reverted to pre-arena stats."}); return

        if path == "/api/admin/unlock_immortal":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return
            arena = str(b.get("arena", "")).strip()
            if arena not in ("elite", "veteran"):
                self.send_json({"success": False, "error": "arena must be 'elite' or 'veteran'"}); return
            arena_cfg_path = os.path.join(BASE_DIR, "saves", arena, "config.json")
            if not os.path.exists(arena_cfg_path):
                self.send_json({"success": False, "error": f"Arena '{arena}' not initialised."}); return
            with open(arena_cfg_path, encoding="utf-8") as _f:
                arena_cfg = json.load(_f)
            arena_cfg["turn_state"] = "open"
            arena_cfg.pop("processing_started_at", None)
            with open(arena_cfg_path, "w", encoding="utf-8") as _f:
                json.dump(arena_cfg, _f, indent=2)
            _disp = {"elite": "The Elite Spire", "veteran": "The Soul Spire"}.get(arena, arena)
            self.send_json({"success": True, "message": f"{_disp} turn state reset to OPEN."}); return

        # ==================== LOCAL CLIENT STORAGE ENDPOINTS ====================
        # Used by bloodspire_client.html when running in 'Local Server Mode'

        def _safe_path(rel_path):
            # For restore from ZIP backup, paths come as "saves/teams/team_*.json",
            # relative to BASE_DIR. Nothing outside the saves folder is reachable
            # (so game code and config in BASE_DIR cannot be read or overwritten).
            return _confined_path(rel_path, BASE_DIR, within=os.path.join(BASE_DIR, "saves"))

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
            if len(new_name) > 25:
                self.send_json({"success": False, "error": "Team name must be 25 characters or fewer."}); return

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

        if path == "/api/admin/spire_sitting_out":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return
            arena_label = {"elite": "Elite Spire", "veteran": "Soul Spire"}
            out = {"elite": [], "veteran": []}
            for arena in ("elite", "veteran"):
                # Same source the turn reads: the pending upload if there is one, else the team file.
                base = {int(t.get("team_id", 0)): t for t in _load_immortal_teams(arena)}
                ups = _load_immortal_uploads(arena) if "_load_immortal_uploads" in globals() else {}
                for tid, team in base.items():
                    src = ups.get(tid) or team
                    for slot, key in (("active", "warriors"), ("archived", "archived_warriors")):
                        for wd in (src.get(key) or []):
                            if not isinstance(wd, dict) or wd.get("is_dead"):
                                continue
                            if (wd.get("current_arena") or arena) != arena:
                                continue
                            if wd.get("run_this_turn") is False:
                                out[arena].append({
                                    "team_id": tid,
                                    "team_name": src.get("team_name") or team.get("team_name", "?"),
                                    "manager": src.get("manager_name") or team.get("manager_name", ""),
                                    "warrior": wd.get("name", "?"),
                                    "source": "upload" if src is not team else "team file",
                                })
                out[arena].sort(key=lambda r: (r["manager"].lower(), r["team_name"], r["warrior"]))
            self.send_json({"success": True,
                            "elite": out["elite"], "veteran": out["veteran"],
                            "elite_count": len(out["elite"]), "soul_count": len(out["veteran"])}); return

        if path == "/api/admin/generate_spire_registry":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return
            import datetime as _dt
            from collections import Counter
            arena_label = {"elite": "Elite Spire", "veteran": "Soul Spire"}
            entries, teams_scanned = [], 0
            try:
                for arena in ("elite", "veteran"):
                    for td in _load_immortal_teams(arena):
                        teams_scanned += 1
                        for slot, key in (("active", "warriors"), ("archived", "archived_warriors")):
                            for w in td.get(key) or []:
                                if not isinstance(w, dict):
                                    continue
                                # Record earned inside this Spire: only the fights tagged with it
                                # (mortal-arena history carries no arena tag).
                                _fh = [f for f in (w.get("fight_history") or [])
                                       if isinstance(f, dict) and f.get("arena") == arena]
                                _aw = sum(f.get("result") == "win" for f in _fh)
                                _al = sum(f.get("result") == "loss" for f in _fh)
                                _ak = sum(bool(f.get("is_kill")) for f in _fh)
                                entries.append({
                                    "arena": arena_label[arena], "warrior_name": w.get("name", "Unnamed"),
                                    "warrior_id": w.get("warrior_id"),
                                    "record": f"{w.get('wins', 0)}-{w.get('losses', 0)}-{w.get('kills', 0)}",
                                    "arena_record": f"{_aw}-{_al}-{_ak}",
                                    "team_id": td.get("team_id", "?"), "team_name": td.get("team_name", "Unknown"),
                                    "manager_name": td.get("manager_name", "Unknown"), "slot": slot,
                                    "dead": bool(w.get("is_dead")),
                                })
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}); return

            owners = Counter(e["warrior_id"] for e in entries if e["warrior_id"])
            dups = {k for k, n in owners.items() if n > 1}
            for e in entries:
                e["status"] = ("missing" if not e["warrior_id"] else "duplicate" if e["warrior_id"] in dups
                               else "dead" if e["dead"] else "ok")
            entries.sort(key=lambda e: (e["arena"], e["team_id"] if isinstance(e["team_id"], int) else 0, e["warrior_name"]))
            by_arena = Counter(e["arena"] for e in entries)

            def _md(v):
                return str(v if v is not None else "--").replace("|", "\\|")

            def _row(e):
                return (f"| {_md(e['warrior_name'])} | {_md(e['warrior_id'])} | {e['record']} | {e['arena_record']} | {e['arena']} "
                        f"| {_md(e['team_name'])} ({_md(e['team_id'])}) | {_md(e['manager_name'])} | {e['slot']} | {e['status'].upper()} |")

            hdr = ["| Warrior | ID | Career Record (W-L-K) | Arena Record (W-L-K) | Arena | Team | Manager | Slot | Status |",
                   "|---|---|---|---|---|---|---|---|---|"]
            turn = cfg.get("current_turn", 1)
            missing = sum(e["status"] == "missing" for e in entries)
            dead = sum(e["dead"] for e in entries)
            lines = [f"# Spire Warrior Registry — Turn {turn}", "",
                     f"Generated {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
                     f"- Spire team files scanned: {teams_scanned}",
                     f"- Warriors: {len(entries)} (Elite Spire {by_arena['Elite Spire']}, Soul Spire {by_arena['Soul Spire']})",
                     f"- Missing warrior_id: {missing}",
                     f"- Duplicate warrior_id(s): {len(dups)}",
                     f"- Marked dead: {dead}", ""]
            problems = [e for e in entries if e["status"] != "ok"]
            if problems:
                lines += ["## Problems", ""] + hdr + [_row(e) for e in problems] + [""]
            for label in ("Elite Spire", "Soul Spire"):
                lines += [f"## {label} ({by_arena[label]})", ""] + hdr + [_row(e) for e in entries if e["arena"] == label] + [""]

            filename = f"Turn_{turn}_Spire_Warrior_Registry.md"
            try:
                with open(os.path.join(BASE_DIR, filename), "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
            except Exception as e:
                self.send_json({"success": False, "error": f"Could not write {filename}: {e}"}); return
            self.send_json({"success": True, "filename": filename, "total_warriors": len(entries),
                            "elite_count": by_arena["Elite Spire"], "soul_count": by_arena["Soul Spire"],
                            "missing_count": missing, "duplicate_count": len(dups), "dead_count": dead}); return

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
                        if not (fn.startswith("team_") and fn.endswith(".json")) or ".backup" in fn:
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
                                    "warrior_id": wid,
                                    "record": f"{w.get('wins', 0)}-{w.get('losses', 0)}-{w.get('kills', 0)}"
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

            import datetime as _dt
            turn = cfg.get("current_turn", 1)
            filename = f"Turn_{turn}_Warrior_Registry.md"

            def _md(v):
                return str(v if v is not None else "--").replace("|", "\\|")

            lines = [
                f"# Warrior Registry — Turn {turn}",
                "",
                f"Generated {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "",
                f"- Teams scanned: {total_teams}",
                f"- Warriors: {len(all_warriors)}",
                f"- Missing warrior_id: {missing_count}",
                f"- Duplicate warrior_id(s): {len(duplicate_ids)}",
                "",
            ]
            problems = [e for e in all_warriors if e["status"] != "ok"]
            if problems:
                problems.sort(key=lambda e: (e["status"], str(e["warrior_id"]), e["warrior_name"]))
                lines += ["## Problems", "",
                          "| Warrior | ID | Record (W-L-K) | Team | Manager | Slot | Status |",
                          "|---|---|---|---|---|---|---|"]
                lines += [f"| {_md(e['warrior_name'])} | {_md(e['warrior_id'])} | {e['record']} | {_md(e['team_name'])} ({_md(e['team_id'])}) "
                          f"| {_md(e['manager_name'])} | {e['slot']} | {e['status'].upper()} |" for e in problems]
                lines.append("")
            lines += ["## All Warriors", "",
                      "| Warrior | ID | Record (W-L-K) | Team | Manager | Slot | Status |",
                      "|---|---|---|---|---|---|---|"]
            lines += [f"| {_md(e['warrior_name'])} | {_md(e['warrior_id'])} | {e['record']} | {_md(e['team_name'])} ({_md(e['team_id'])}) "
                      f"| {_md(e['manager_name'])} | {e['slot']} | {e['status'].upper()} |" for e in all_warriors]

            try:
                with open(os.path.join(BASE_DIR, filename), "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
            except Exception as e:
                self.send_json({"success": False, "error": f"Could not write {filename}: {e}"}); return

            self.send_json({
                "success": True,
                "filename": filename,
                "total_teams": total_teams,
                "total_warriors": len(all_warriors),
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

            zip_bytes = _build_manager_zip(mid, managers)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            filename = f"manager_{mid}_files.zip"
            self.send_header("Content-Disposition", f"attachment; filename={filename}")
            self.send_header("Content-Length", len(zip_bytes))
            self.end_headers()
            self.wfile.write(zip_bytes)
            return

        if path == "/api/admin/utility_bundle":
            # Host-only data bundle for the host's utilities (Challenge Finder) when away from the server.
            cfg = _load_config()
            if not _check_host_pw(cfg, str(b.get("host_password", ""))):
                time.sleep(1)       # slow down password guessing
                _log_activity("utility_bundle_denied", "host", "host", f"Bad host password from {self.client_address[0]}")
                self.send_json({"success": False, "error": "Not authorised."}, 401); return
            if _processing_arenas:
                turns = ", ".join(f"{a} turn {t}" for a, t in sorted(_processing_arenas.items()))
                self.send_json({"success": False, "processing": True,
                                "error": f"A turn is still being processed ({turns}). Try again in a few minutes."}); return
            try:
                zip_bytes, manifest = _build_utility_bundle()
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"success": False, "error": f"Could not build the bundle: {type(e).__name__}: {e}"}, 500); return
            _log_activity("utility_bundle", "host", "host",
                          f"Utility bundle turn {manifest.get('current_turn')} ({len(zip_bytes)} bytes) to {self.client_address[0]}")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition",
                             f"attachment; filename=bloodspire_utility_data_turn{manifest.get('current_turn')}.zip")
            self.send_header("Content-Length", str(len(zip_bytes)))
            self.end_headers()
            try:
                self.wfile.write(zip_bytes)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass
            return

        if path == "/api/my_files_zip":
            # Self-service recovery ZIP. Same package the host used to build by hand
            # (/api/admin/download_manager_files). Deliberately NOT version-gated and does
            # not touch last_downloaded_turn, so a failed results download can be recovered.
            mid = str(b.get("manager_id") or "").strip()
            pw  = str(b.get("password") or "")
            managers = _load_managers()
            mgr = managers.get(mid)
            if not mgr or not pw or not _check_mgr_pw(mgr, pw):
                _log_activity("self_service_zip_denied", mid or "?", (mgr or {}).get("manager_name", "?"),
                              f"Bad credentials from {self.client_address[0]}")
                self.send_json({"success": False, "error": "Account number or password is incorrect."}, 401); return
            zip_bytes = _build_manager_zip(mid, managers)
            _log_activity("self_service_zip", mid, mgr["manager_name"],
                          f"Self-service files ZIP ({len(zip_bytes)} bytes)")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f"attachment; filename=manager_{mid}_files.zip")
            self.send_header("Content-Length", str(len(zip_bytes)))
            self.end_headers()
            try:
                self.wfile.write(zip_bytes)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass
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

        if path == "/api/admin/warriors_by_arena":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return
            try:
                from save import load_all_teams
                normal, elite, veteran = [], [], []
                all_teams = load_all_teams()

                # --- Normal arena: from main team files ---
                for team in all_teams:
                    for w in (team.warriors or []):
                        if not w:
                            continue
                        if getattr(w, "is_dead", False) or getattr(w, "is_retired", False):
                            continue
                        arena = getattr(w, "current_arena", "normal") or "normal"
                        if arena != "normal":
                            continue
                        wins   = getattr(w, "wins",   0)
                        losses = getattr(w, "losses", 0)
                        kills  = getattr(w, "kills",  0)
                        normal.append({
                            "warrior_name": w.name,
                            "team_id":      team.team_id,
                            "team_name":    team.team_name,
                            "manager_name": team.manager_name or "",
                            "record":       f"{wins}-{losses}-{kills}",
                            "total_fights": wins + losses,
                            "win_rate":     round(wins / (wins + losses), 4) if wins + losses > 0 else 0.0,
                        })

                # --- Elite Spire & Soul Spire: from immortal arena files ---
                for (arena_key, bucket) in (("elite", elite), ("veteran", veteran)):
                    for team_dict in _load_immortal_teams(arena_key):
                        tid       = team_dict.get("team_id", "?")
                        tname     = team_dict.get("team_name", "")
                        mname     = team_dict.get("manager_name", "")
                        all_ws    = list(team_dict.get("warriors", []) or []) + \
                                    list(team_dict.get("archived_warriors", []) or [])
                        for w in all_ws:
                            if not isinstance(w, dict) or not w.get("name"):
                                continue
                            if w.get("is_dead", False):
                                continue
                            w_arena = w.get("current_arena") or "normal"
                            if w_arena != arena_key:
                                continue
                            wins   = w.get("wins",   0)
                            losses = w.get("losses", 0)
                            kills  = w.get("kills",  0)
                            bucket.append({
                                "warrior_name": w["name"],
                                "team_id":      tid,
                                "team_name":    tname,
                                "manager_name": mname,
                                "record":       f"{wins}-{losses}-{kills}",
                                "total_fights": wins + losses,
                                "win_rate":     round(wins / (wins + losses), 4) if wins + losses > 0 else 0.0,
                            })

                normal.sort(key=lambda x: (x["team_id"], x["warrior_name"]))
                elite.sort(key=lambda x: (-x["win_rate"], -x["total_fights"]))
                veteran.sort(key=lambda x: (-x["win_rate"], -x["total_fights"]))
                self.send_json({
                    "success": True,
                    "normal":  normal,  "normal_count":  len(normal),
                    "elite":   elite,   "elite_count":   len(elite),
                    "veteran": veteran, "veteran_count": len(veteran),
                }); return
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

                # Use the last completed turn - current_turn is the one still open
                # for uploads, which has no results yet.
                turn_num = cfg.get("current_turn", 1) - 1
                if turn_num < 1:
                    self.send_json({"success": False, "error": "No completed turns yet."}); return
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

                # Use the last completed turn - current_turn is the one still open
                # for uploads, so its "this turn" stats would all be zero.
                turn_num = cfg.get("current_turn", 1) - 1
                if turn_num < 1:
                    self.send_json({"success": False, "error": "No completed turns yet."}); return
                uploads = _load_uploads(turn_num)
                teams = load_all_teams()
                team_map = {}
                for team in teams:
                    # Match by manager_name + team_id
                    for upload_key, upload in uploads.items():
                        if upload.get("manager_name") == team.manager_name and upload.get("team_id") == team.team_id:
                            team_map[upload_key] = team
                            break

                reports_dir = os.path.join(LEAGUE_DIR, "reports")
                generate_arena_stats(uploads, team_map, turn_num, reports_dir)

                self.send_json({"success": True, "message": f"Arena stats regenerated and pushed for Turn {turn_num}"}); return
            except Exception as e:
                import traceback; traceback.print_exc()
                self.send_json({"success": False, "error": str(e)}); return

        if path == "/api/admin/init_immortal_arenas":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password", "")):
                self.send_json({"success": False, "error": "Not authorised."}, 401); return

            try:
                import io, sys as _sys
                # Capture stdout from the migration functions
                _buf = io.StringIO()
                _old_stdout = _sys.stdout
                _sys.stdout = _buf
                try:
                    import migrate_phase1 as _m1
                    _m1.migrate_team_files()
                    _m1.create_arena_dir(_m1.ELITE_DIR,   "Elite Spire",    _m1.ELITE_CONFIG)
                    _m1.create_arena_dir(_m1.VETERAN_DIR, "Veteran's Keep", _m1.VETERAN_CONFIG)
                    _m1.update_normal_config()
                finally:
                    _sys.stdout = _old_stdout
                output = _buf.getvalue()
                self.send_json({"success": True, "output": output}); return
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

        # ── Announcement Management (Admin Only) ───────────────────────────
        if path == "/api/admin/announcements/create":
            title = str(b.get("title", "")).strip()
            message = str(b.get("message", "")).strip()
            url = str(b.get("url", "")).strip()
            if not title or not message:
                self.send_json({"success": False, "error": "title and message required"}); return

            announcements = _load_announcements()
            new_ann = {
                "id": f"ann_{int(time.time())}_{secrets.token_hex(4)}",
                "title": title,
                "message": message,
                "url": url,
                "active": True,
                "created_at": time.time(),
                "expires_at": None,
            }
            announcements.append(new_ann)
            _save_announcements(announcements)
            self.send_json({"success": True, "announcement": new_ann}); return

        if path == "/api/admin/announcements/update":
            ann_id = str(b.get("id", "")).strip()
            if not ann_id:
                self.send_json({"success": False, "error": "id required"}); return

            announcements = _load_announcements()
            for ann in announcements:
                if ann["id"] == ann_id:
                    if "title" in b: ann["title"] = str(b["title"]).strip()
                    if "message" in b: ann["message"] = str(b["message"]).strip()
                    if "url" in b: ann["url"] = str(b["url"]).strip()
                    if "active" in b: ann["active"] = bool(b["active"])
                    if "expires_at" in b: ann["expires_at"] = b["expires_at"]
                    _save_announcements(announcements)
                    self.send_json({"success": True, "announcement": ann}); return

            self.send_json({"success": False, "error": "announcement not found"}); return

        if path == "/api/admin/announcements/delete":
            ann_id = str(b.get("id", "")).strip()
            if not ann_id:
                self.send_json({"success": False, "error": "id required"}); return

            announcements = _load_announcements()
            original_len = len(announcements)
            announcements = [ann for ann in announcements if ann["id"] != ann_id]
            if len(announcements) < original_len:
                _save_announcements(announcements)
                self.send_json({"success": True}); return

            self.send_json({"success": False, "error": "announcement not found"}); return

        if path == "/api/admin/announcements/list":
            announcements = _load_announcements()
            self.send_json({"success": True, "announcements": announcements}); return

        self.send_json({"error":"Not found."}, 404)

# =============================================================================
# ENTRY POINT
# =============================================================================

_turn_log_file = None


class _turn_log:
    """While active, everything printed is also saved to saves/server_logs/<label>.log"""
    def __init__(self, label):
        self.label = label
    def __enter__(self):
        global _turn_log_file
        try:
            import datetime
            d = os.path.join(BASE_DIR, "saves", "server_logs")
            os.makedirs(d, exist_ok=True)
            f = open(os.path.join(d, self.label + ".log"), "a", encoding="utf-8", errors="replace")
            f.write(f"\n===== {self.label} started {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            f.flush()
            _turn_log_file = f
        except Exception:
            _turn_log_file = None
        return self
    def __exit__(self, *exc):
        global _turn_log_file
        f, _turn_log_file = _turn_log_file, None
        if f:
            try:
                if exc[0] is not None:
                    import traceback; f.write("".join(traceback.format_exception(*exc)))
                f.write("===== end =====\n"); f.close()
            except Exception:
                pass
        return False


class _Tee:
    """Copies everything printed to the console into a log file as well."""
    def __init__(self, console, logfile, lock):
        self._c, self._f, self._l = console, logfile, lock
    def write(self, text):
        try:
            if self._c: self._c.write(text)
        except Exception:
            pass
        try:
            with self._l:
                self._f.write(text); self._f.flush()
                if _turn_log_file is not None:
                    _turn_log_file.write(text); _turn_log_file.flush()
        except Exception:
            pass
        return len(text)
    def flush(self):
        try:
            if self._c: self._c.flush()
        except Exception:
            pass
    def isatty(self):
        return False
    def __getattr__(self, name):
        return getattr(self._c, name)


def _start_log_file():
    """Keep a permanent copy of the console output: saves/server_logs/server_YYYY-MM-DD.log"""
    import datetime
    log_dir = os.path.join(BASE_DIR, "saves", "server_logs")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"server_{datetime.date.today().isoformat()}.log")
    f = open(path, "a", encoding="utf-8", errors="replace")
    lock = threading.Lock()
    f.write(f"\n===== Server started {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
    f.flush()
    sys.stdout = _Tee(sys.stdout, f, lock)
    sys.stderr = _Tee(sys.stderr, f, lock)


def main():
    parser = argparse.ArgumentParser(description="BLOODSPIRE League Server")
    parser.add_argument("--host-password", required=True,
                        help="Password for host admin access and running turns")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    global _server_port
    _server_port = args.port

    _start_log_file()

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
