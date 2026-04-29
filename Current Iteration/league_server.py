#!/usr/bin/env python3
# =============================================================================
# league_server.py — BLOODSPIRE League Server
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
import webbrowser
from typing import Optional

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
LEAGUE_DIR   = os.path.join(BASE_DIR, "saves", "league")
DEFAULT_PORT = 8766
sys.path.insert(0, BASE_DIR)

_lock          = threading.Lock()
_turn_progress = {"running": False, "done": 0, "total": 0, "message": ""}
_global_server = None  # Reference for graceful shutdown from request handlers


# =============================================================================
# STORAGE HELPERS
# =============================================================================

def _ensure_dirs():
    os.makedirs(LEAGUE_DIR, exist_ok=True)

def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

def _config_path():   return os.path.join(LEAGUE_DIR, "config.json")
def _managers_path(): return os.path.join(LEAGUE_DIR, "managers.json")
def _standings_path():return os.path.join(LEAGUE_DIR, "standings.json")

def _turn_dir(turn_num):
    d = os.path.join(LEAGUE_DIR, f"turn_{turn_num:04d}")
    os.makedirs(d, exist_ok=True)
    return d

def _load_config():
    cfg = _load_json(_config_path(), {
        "current_turn": 1,
        "turn_state": "open",
        "host_password_hash": "",
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
    })
    # Ensure new flags exist in old configs
    for key, default in [
        ("show_favorite_weapon", False),
        ("show_luck_factor", False),
        ("show_max_hp", False),
        ("ai_teams_enabled", True),
        ("schedule_enabled", False),
        ("admin_debug_manager_id", ""),
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
def _load_managers():    return _load_json(_managers_path(), {})
def _save_managers(m):   _save_json(_managers_path(), m)
def _load_standings():   return _load_json(_standings_path(), {})
def _save_standings(s):  _save_json(_standings_path(), s)

def _load_uploads(turn_num):
    td = _turn_dir(turn_num)
    if not os.path.exists(td): return {}
    uploads = {}
    for fname in sorted(os.listdir(td)):
        if not (fname.startswith("upload_") and fname.endswith(".json")):
            continue
        data = _load_json(os.path.join(td, fname), None)
        if not data:
            continue
        mid     = data.get("manager_id") or ""
        team_id = data.get("team_id") or (data.get("team") or {}).get("team_id", "")
        # Key by manager_id+team_id so multiple teams from same manager coexist
        key = f"{mid}_team{team_id}" if team_id else mid
        uploads[key] = data
    return uploads

def _save_upload(turn_num, manager_id, data):
    team_id = data.get("team_id") or (data.get("team") or {}).get("team_id", "")
    if team_id:
        fname = f"upload_{manager_id}_team{team_id}.json"
    else:
        fname = f"upload_{manager_id}.json"
    _save_json(os.path.join(_turn_dir(turn_num), fname), data)

def _load_result(turn_num, manager_id):
    return _load_json(os.path.join(_turn_dir(turn_num), f"result_{manager_id}.json"), None)

def _save_result(turn_num, manager_id, data):
    # Include team_id in filename so a manager with multiple teams has separate files
    team_id = data.get("team_id", "")
    if team_id:
        fname = f"result_{manager_id}_team{team_id}.json"
    else:
        fname = f"result_{manager_id}.json"
    _save_json(os.path.join(_turn_dir(turn_num), fname), data)


# =============================================================================
# AUTH HELPERS
# =============================================================================

def _hash_pw(password, salt):
    return hashlib.sha256((salt + password).encode()).hexdigest()

def _check_host_pw(cfg, password):
    return _hash_pw(password, cfg["host_password_salt"]) == cfg["host_password_hash"]

def _check_mgr_pw(mgr, password):
    return _hash_pw(password, mgr["salt"]) == mgr["password_hash"]

def _next_fid(cfg):
    cfg["fight_counter"] = cfg.get("fight_counter", 0) + 1
    return cfg["fight_counter"]


def _make_mirror_narrative(
    narrative        : str,
    training_results : dict,
    a_name           : str,
    b_name           : str,
) -> str:
    """
    Return a version of the fight narrative from warrior_b's manager's perspective:
      - warrior_b's training shows the actual skills/stats learned
      - warrior_a's training shows "Skill" or "Stat" (generic)

    The narrative is identical up to the training section at the end.  We
    reconstruct that section with the `is_opponent` flags swapped, then
    replace it via a suffix match so the fight body is never touched.
    """
    from narrative import training_summary as _ts

    a_res = training_results.get("warrior_a", [])
    b_res = training_results.get("warrior_b", [])

    # Compute what the FORWARD training block looks like (warrior_a perspective)
    fwd_parts = []
    if a_res:
        fwd_parts.append(_ts(a_name, a_res, is_opponent=False))
    if b_res:
        fwd_parts.append(_ts(b_name, b_res, is_opponent=True))

    # Compute the MIRROR training block (warrior_b perspective)
    mir_parts = []
    if b_res:
        mir_parts.append(_ts(b_name, b_res, is_opponent=False))
    if a_res:
        mir_parts.append(_ts(a_name, a_res, is_opponent=True))

    if not fwd_parts and not mir_parts:
        return narrative  # nothing to swap

    # The training block is appended as: "\n" (blank-line join) + "\n".join(parts)
    # which in the joined narrative looks like "\n\n<line1>\n<line2>..."
    fwd_block = "\n\n" + "\n".join(fwd_parts)
    mir_block = "\n\n" + "\n".join(mir_parts)

    if narrative.endswith(fwd_block):
        return narrative[: -len(fwd_block)] + mir_block

    # Fallback: couldn't find the expected suffix — return unchanged
    return narrative


def _store_scout_narrative(warrior_name: str, narrative: str, turn_num: int) -> None:
    """
    Persist the fight narrative for a scouted warrior so the client can
    retrieve it via the scout report without needing to chase fight_ids.
    Stored at saves/league/scout_narratives.json keyed by warrior name.
    """
    path = os.path.join(LEAGUE_DIR, "scout_narratives.json")
    try:
        data = _load_json(path, {})
        data[warrior_name] = {"narrative": narrative, "turn": turn_num}
        _save_json(path, data)
    except Exception:
        pass


# =============================================================================
# FIGHT RUNNER
# =============================================================================

def _run_turn(request_password, rerun_turn=None):
    """Run all fights for the current (or re-run) turn, including 12 AI teams."""
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
            else: stuck = True # No timestamp found
            if not stuck:
                return {"success": False, "error": "Turn is already running."}
        if rerun_turn:
            # Only the most recently completed turn may be re-run
            last_completed = cfg["current_turn"] - 1
            if rerun_turn != last_completed:
                return {"success": False,
                        "error": f"Only turn {last_completed} (the last completed turn) can be re-run."}
        turn_num = rerun_turn if rerun_turn else cfg["current_turn"]
        uploads  = _load_uploads(turn_num)

        # Inject AI teams as pseudo-uploads (only when the flag is enabled)
        ai_teams = []
        if cfg.get("ai_teams_enabled", True):
            try:
                from ai_league_teams import get_or_create_ai_teams
                ai_teams = get_or_create_ai_teams()
                for ai_team in ai_teams:
                    mid = ai_team["manager_id"]
                    if mid not in uploads:
                        uploads[mid] = {
                            "manager_id"  : mid,
                            "manager_name": ai_team["manager_name"],
                            "team"        : ai_team,
                            "uploaded_at" : "AI (auto)",
                            "is_ai"       : True,
                        }
            except Exception as e:
                print(f"  WARNING: Could not load AI teams: {e}")
        else:
            print("  AI teams disabled — skipping AI team injection.")

        if not uploads:
            return {"success": False, "error": "No teams (player or AI) available."}
        # Capture feature flags now — these must survive the turn and must
        # only be changed by the admin explicitly unchecking them.
        _FLAG_KEYS = ("show_favorite_weapon", "show_luck_factor", "show_max_hp", "ai_teams_enabled")
        _turn_start_flags = {k: cfg.get(k) for k in _FLAG_KEYS}
        print(f"  [flags] Captured at turn start: "
              f"fav_wpn={_turn_start_flags.get('show_favorite_weapon')} "
              f"luck={_turn_start_flags.get('show_luck_factor')} "
              f"max_hp={_turn_start_flags.get('show_max_hp')}")
        cfg["turn_state"] = "processing"
        import datetime as _dt2
        cfg["processing_started_at"] = _dt2.datetime.now().isoformat()
        _save_config(cfg)
        _turn_progress = {"running": True, "done": 0, "total": len(uploads),
                          "message": "Starting..."}

    from team        import Team
    from matchmaking import build_fight_card
    from combat      import run_fight, set_show_favorite_weapon, set_show_luck_factor, set_show_max_hp

    # Apply feature flags from config
    cfg = _load_config()
    set_show_favorite_weapon(_turn_start_flags.get("show_favorite_weapon", False))
    set_show_luck_factor(_turn_start_flags.get("show_luck_factor", False))
    set_show_max_hp(_turn_start_flags.get("show_max_hp", False))

    # Build debug warrior set — fights involving these warriors get verbose logs
    # uploads keys are like "20_team1", "20_team22", so match on manager_id field
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

    team_map    = {}   # upload key -> Team object
    real_mid_map = {}  # upload key -> real manager_id (for same-manager exclusion)
    for mid, upload in uploads.items():
        try:
            team = Team.from_dict(upload["team"])
            team.manager_name = upload["manager_name"]
            team_map[mid] = team
            real_mid_map[mid] = upload.get("manager_id", mid)
        except Exception as e:
            print(f"  WARN: could not load team for {upload.get('manager_name','?')}: {e}")

    cfg         = _load_config()
    all_results = {}
    done_count  = 0

    # Load champion state once (shared by all managers)
    try:
        from save import load_champion_state
        champ_state = load_champion_state()
    except Exception:
        champ_state = {}

    # ===========================================================================
    # PRE-PASS: Guarantee each player warrior fights exactly once per turn.
    #
    # Problem: build_fight_card() is called independently per manager, so a
    # player warrior can appear as pw in their own manager's card AND as ow in
    # another manager's card — fighting twice, producing duplicate newsletter
    # entries.
    #
    # Solution:
    #   1. Build fight cards for all non-AI managers up front.
    #   2. For every player-vs-player pair found, run the fight ONCE and store
    #      the result keyed by both warrior names (_pvp_by_warrior).
    #   3. In the main loop, when a warrior's name is in _pvp_by_warrior, inject
    #      the pre-computed (possibly mirrored) result instead of fighting again.
    #
    # If the pre-pass fails for any reason, _fight_cards and _pvp_by_warrior
    # will be empty and the main loop falls back to the old per-manager approach.
    # ===========================================================================

    _fight_cards    = {}   # manager_id -> (pre_team, List[ScheduledFight])
    _pvp_by_warrior = {}   # warrior_name -> pvp_data dict

    # Shared across EVERY build_fight_card call this turn (pre-pass + main loop,
    # AI and non-AI).  Each warrior can be scheduled at most once per turn, and
    # since team size is exactly 5, this also caps every team at 5 fights/turn —
    # a hard rule with no exceptions.
    _global_used    = set()

    # Belt-and-suspenders: per-turn fight count per TEAM NAME.  Incremented each
    # time a bout is accepted into the final fight stream.  Monsters/Peasants are
    # excluded.  Any bout that would push either team past 5 is DROPPED outright
    # before it reaches run_fight — this is the last-word enforcement of the
    # 5-fights-per-team cap, no exceptions.
    _team_fight_count = {}
    _FODDER_TEAMS     = {"The Monsters", "The Peasants"}

    # AI warrior name -> manager_id.  Used to register MIRROR BOUTS: when an AI
    # warrior fights as OW in another manager's iteration, their own team's
    # result would otherwise miss the fight.  The mirror bout (flipped to their
    # perspective) is added to _ai_mirror_bouts for merging after the main loop.
    ai_warrior_to_mid = {}
    for _mid, _upl in uploads.items():
        if _mid.startswith("ai_"):
            for _wd in (_upl["team"].get("warriors") or []):
                if _wd and _wd.get("name"):
                    ai_warrior_to_mid[_wd["name"]] = _mid
    _ai_mirror_bouts = {}   # mid -> list of bout dicts (mirrored perspective)

    try:
        # warrior_name -> manager_id for all non-AI player warriors
        player_warrior_to_mid = {}
        for _mid, _upl in uploads.items():
            if not _mid.startswith("ai_"):
                for _wd in (_upl["team"].get("warriors") or []):
                    if _wd and _wd.get("name"):
                        player_warrior_to_mid[_wd["name"]] = _mid

        # Pre-build non-AI fight cards
        for _mid, _upl in uploads.items():
            if _mid.startswith("ai_"):
                continue
            try:
                _pt = Team.from_dict(_upl["team"])
                _pt.manager_name = _upl["manager_name"]
            except Exception as _pe:
                print(f"  PRE-PASS WARN: could not load team for {_upl.get('manager_name','?')}: {_pe}")
                continue
            try:
                _this_real = _upl.get("manager_id", _mid)
                _opp_list = [
                    t for mid2, t in team_map.items()
                    if mid2 != _mid and real_mid_map.get(mid2, mid2) != _this_real
                ]
                _fc = build_fight_card(_pt, _opp_list, champion_state=champ_state,
                                       global_used=_global_used)
                _fight_cards[_mid] = (_pt, _fc)
            except Exception as _fce:
                print(f"  PRE-PASS WARN: build_fight_card failed for {_upl.get('manager_name','?')}: {_fce}")
                # Leave this manager out of _fight_cards; main loop will build a fresh card

        # ------------------------------------------------------------------
        # Deduplicate AI opponent usage: each named AI warrior (e.g. the
        # champion) may only appear in ONE player's fight card per turn.
        # Excess uses are replaced with a peasant fight so the player
        # warrior still fights — they just don't get the champion bout.
        # Monsters and Peasants are unlimited fodder and are NOT limited.
        # ------------------------------------------------------------------
        _used_ai_opponents = set()
        _fodder_races = {"Monster", "Peasant"}
        try:
            from team import create_peasant_team as _cpt
            from matchmaking import ScheduledFight as _SF_sub
            import random as _rnd_sub
            for _mid_ai in list(_fight_cards.keys()):
                _pt_ai, _card_ai = _fight_cards[_mid_ai]
                _new_card = []
                for _b_ai in _card_ai:
                    _ow_ai = _b_ai.opponent
                    # Player warriors → P-vs-P logic handles them; fodder → always OK
                    if (player_warrior_to_mid.get(_ow_ai.name) is not None
                            or getattr(_ow_ai.race, "name", "") in _fodder_races):
                        _new_card.append(_b_ai)
                        continue
                    # Named AI warrior — allow only the first user, substitute peasant for rest
                    if _ow_ai.name in _used_ai_opponents:
                        try:
                            _pteam   = _cpt()
                            _peasant = _rnd_sub.choice(_pteam.active_warriors)
                            _new_card.append(_SF_sub(
                                player_warrior   = _b_ai.player_warrior,
                                opponent         = _peasant,
                                player_team      = _pt_ai,
                                opponent_team    = _pteam,
                                opponent_manager = "The Arena",
                                fight_type       = "peasant",
                            ))
                            print(f"  PRE-PASS: {_b_ai.player_warrior.name} vs {_ow_ai.name} "
                                  f"— AI warrior already scheduled; substituted peasant")
                        except Exception:
                            pass  # warrior skips this turn — acceptable fallback
                        continue
                    _used_ai_opponents.add(_ow_ai.name)
                    _new_card.append(_b_ai)
                _fight_cards[_mid_ai] = (_pt_ai, _new_card)
        except Exception as _ai_dedup_err:
            print(f"  PRE-PASS WARN: AI opponent dedup failed: {_ai_dedup_err}")

        # Run each unique P-vs-P fight exactly once; track by warrior name
        for _mid, (_pt, _card) in _fight_cards.items():
            _mname = uploads[_mid]["manager_name"]
            for _bout in _card:
                _pw  = _bout.player_warrior
                _ow  = _bout.opponent
                if player_warrior_to_mid.get(_ow.name) is None:
                    continue  # ow is not a player warrior
                # Skip if either warrior is already assigned to a pre-fought match
                if _pw.name in _pvp_by_warrior or _ow.name in _pvp_by_warrior:
                    continue
                try:
                    # Pre-assign fight ID so both managers share the same narrative ID
                    _pre_fid = _next_fid(cfg)
                    _pre_dbg = None
                    if _debug_warrior_names and (_pw.name in _debug_warrior_names or _ow.name in _debug_warrior_names):
                        from combat_debug_logger import CombatDebugLogger as _CDBLogger
                        _pre_dbg = _CDBLogger()
                        _pre_dbg.fight_id   = _pre_fid
                        _pre_dbg.turn_num   = turn_num
                        _pre_dbg.debug_team = _dbg_mgr_name
                    _result  = run_fight(
                        _pw, _ow,
                        team_a_name    = _pt.team_name,
                        team_b_name    = _bout.opponent_team.team_name,
                        manager_a_name = _mname,
                        manager_b_name = _bout.opponent_manager,
                        is_monster_fight = False,
                        challenger_name = getattr(_bout, 'challenger_name', None),
                        debug_logger   = _pre_dbg,
                    )
                    if _pre_dbg and _dbg_turn_dir:
                        _pre_log = os.path.join(_dbg_turn_dir, f"fight_{_pre_fid:05d}_{_pw.name}_vs_{_ow.name}.txt")
                        try:
                            _pre_dbg.write_to_file(_pre_log)
                        except Exception as _pre_log_err:
                            print(f"  DEBUG LOG WARN (pre-pass): {_pre_log_err}")
                    # Scout flavor text injection
                    try:
                        from save import get_all_scouted_warriors
                        _scouted = get_all_scouted_warriors(turn_num)
                        _attending = set()
                        for _ww in (_pw, _ow):
                            for _mgr in _scouted.get(_ww.name, []):
                                _attending.add(_mgr)
                        if _attending:
                            _scout_line = (
                                f"\n[A scout from {', '.join(sorted(_attending))}'s stable is in "
                                f"attendance, watching the proceedings with a keen eye.]\n"
                            )
                            from combat import FightResult as _FR
                            _result = _FR(
                                winner=_result.winner, loser=_result.loser,
                                loser_died=_result.loser_died, minutes_elapsed=_result.minutes_elapsed,
                                narrative=_scout_line + _result.narrative,
                                training_results=_result.training_results,
                            )
                        # Persist scout narrative
                        for _ww in (_pw, _ow):
                            if _ww.name in _scouted:
                                _store_scout_narrative(_ww.name, _result.narrative, turn_num)
                    except Exception:
                        pass
                    _pvp_data = {
                        "result"         : _result,
                        "fid"            : _pre_fid,
                        "canonical_pw"   : _pw.name,
                        "canonical_ow"   : _ow.name,
                        "pw_team"        : _pt.team_name,
                        "ow_team"        : _bout.opponent_team.team_name,
                        "pw_manager"     : _mname,
                        "ow_manager"     : _bout.opponent_manager,
                        "fight_type"     : _bout.fight_type,
                        "pw_race"        : _pw.race.name,
                        "ow_race"        : _ow.race.name,
                        "pw_trained_dict": _pw.to_dict(),
                        "ow_trained_dict": _ow.to_dict(),
                    }
                    _pvp_by_warrior[_pw.name] = _pvp_data
                    _pvp_by_warrior[_ow.name] = _pvp_data
                    print(f"  PRE-FIGHT (P-vs-P): {_pw.name} vs {_ow.name} — fid={_pre_fid}")
                except Exception as _pvp_err:
                    print(f"  PRE-FIGHT WARN: P-vs-P fight {_pw.name} vs {_ow.name} failed: {_pvp_err}; will fight normally")
                    # Remove partial entries so both warriors fight fresh in main loop
                    _pvp_by_warrior.pop(_pw.name, None)
                    _pvp_by_warrior.pop(_ow.name, None)

        # ------------------------------------------------------------------
        # Final cleanup pass: any card bout where ow is a player warrior
        # already booked in a P-vs-P fight (i.e. ow.name in _pvp_by_warrior)
        # must be replaced with a peasant, because that opponent is spoken
        # for.  Without this, the main loop would call run_fight() on the
        # booked warrior a second time (the pw check fires, but ow check
        # does not — so the fight runs fresh).
        # ------------------------------------------------------------------
        try:
            from team import create_peasant_team as _cpt2
            from matchmaking import ScheduledFight as _SF2
            import random as _rnd2
            for _mid_cl in list(_fight_cards.keys()):
                _pt_cl, _card_cl = _fight_cards[_mid_cl]
                _new_cl = []
                for _b_cl in _card_cl:
                    _ow_cl = _b_cl.opponent
                    _pw_cl = _b_cl.player_warrior
                    # Only substitute when:
                    #   • pw is NOT pre-fought (it will fall through to run_fight)
                    #   • ow IS booked as the other side of a P-vs-P fight
                    if (_pw_cl.name not in _pvp_by_warrior
                            and _ow_cl.name in _pvp_by_warrior
                            and player_warrior_to_mid.get(_ow_cl.name) is not None):
                        try:
                            _pt_sub  = _cpt2()
                            _p_sub   = _rnd2.choice(_pt_sub.active_warriors)
                            _new_cl.append(_SF2(
                                player_warrior   = _pw_cl,
                                opponent         = _p_sub,
                                player_team      = _pt_cl,
                                opponent_team    = _pt_sub,
                                opponent_manager = "The Arena",
                                fight_type       = "peasant",
                            ))
                            print(f"  PRE-PASS: {_pw_cl.name} vs {_ow_cl.name} "
                                  f"— opponent already booked in P-vs-P; substituted peasant")
                        except Exception:
                            _new_cl.append(_b_cl)  # keep original as last resort
                    else:
                        _new_cl.append(_b_cl)
                _fight_cards[_mid_cl] = (_pt_cl, _new_cl)
        except Exception as _cl_err:
            print(f"  PRE-PASS WARN: cleanup pass failed: {_cl_err}")

    except Exception as _prepass_err:
        import traceback; traceback.print_exc()
        print(f"  PRE-PASS ERROR: {_prepass_err} — falling back to per-manager fight cards")
        _fight_cards    = {}
        _pvp_by_warrior = {}

    for manager_id, upload in uploads.items():
        mname = upload["manager_name"]
        done_count += 1
        _turn_progress["done"]    = done_count
        _turn_progress["message"] = f"Fighting: {mname} ({done_count}/{len(uploads)})"
        print(f"\n  [{mname}] processing fights...")
        try:
            if manager_id.startswith("ai_") and manager_id in team_map:
                # AI: reuse the team_map instance so fight updates accumulated
                # when this team's warriors appeared as OW in earlier iterations
                # are preserved on the final saved result.  Fresh Team.from_dict
                # here would discard those updates and leave the team looking
                # like it fought fewer than 5 times.
                player_team = team_map[manager_id]
                player_team.manager_name = mname
            else:
                player_team = Team.from_dict(upload["team"])
                player_team.manager_name = mname
        except Exception as e:
            print(f"  SKIP {mname}: {e}"); continue

        # Exclude all teams owned by the same manager (real manager_id match)
        this_real_mid = upload.get("manager_id", manager_id)
        is_ai_manager = manager_id.startswith("ai_")
        try:
            if is_ai_manager:
                # AI teams only fight other AI teams
                opp_list = [
                    t for mid, t in team_map.items()
                    if mid != manager_id and mid.startswith("ai_")
                ]
                card = build_fight_card(player_team, opp_list, champion_state=champ_state,
                                        global_used=_global_used)
            else:
                # Non-AI: remap pre-built card so player_warrior objects point into
                # the fresh player_team (ensures all in-place updates land on the
                # right warrior objects when we call player_team.to_dict() later).
                from matchmaking import ScheduledFight as _SF
                _pre_pt, _pre_card = _fight_cards.get(manager_id, (None, []))
                card = []
                for _b in _pre_card:
                    _fresh_pw = player_team.warrior_by_name(_b.player_warrior.name)
                    if _fresh_pw is None:
                        continue
                    card.append(_SF(
                        player_warrior   = _fresh_pw,
                        opponent         = _b.opponent,
                        player_team      = player_team,
                        opponent_team    = _b.opponent_team,
                        opponent_manager = _b.opponent_manager,
                        fight_type       = _b.fight_type,
                    ))
                if not card:
                    # Fallback: build fresh card
                    opp_list = [
                        t for mid, t in team_map.items()
                        if mid != manager_id
                        and real_mid_map.get(mid, mid) != this_real_mid
                    ]
                    card = build_fight_card(player_team, opp_list, champion_state=champ_state,
                                            global_used=_global_used)
        except Exception as _card_err:
            import traceback; traceback.print_exc()
            print(f"  ERROR building fight card for {mname}: {_card_err} — skipping manager")
            continue

        # HARD CAP ENFORCEMENT: drop any bout that would push either team past
        # 5 fights this turn.  Monsters/Peasants are unlimited fodder.  This is
        # the last-word guard — even if upstream matchmaking leaks, no team can
        # slip past 5 fights in the final fight stream.
        #
        # NOTE: P-vs-P bouts appear in BOTH managers' cards (each side sees the
        # other as opponent) but are a SINGLE physical fight.  We only count
        # them on the canonical side and skip counting on the mirror so the cap
        # reflects real fights, not double-counted perspectives.
        _capped_card = []
        for _bout in card:
            _pw_team = getattr(_bout.player_team, "team_name", "?")
            _ow_team = getattr(_bout.opponent_team, "team_name", "?")
            _pw_name = _bout.player_warrior.name
            _ow_name = _bout.opponent.name
            _pvp_rec = _pvp_by_warrior.get(_pw_name)
            _is_pvp_mirror = (_pvp_rec is not None
                              and _pvp_rec.get("canonical_pw") != _pw_name)
            if _is_pvp_mirror:
                # Mirror view of a P-vs-P already counted on the canonical side.
                # Keep the bout (the result gets injected downstream) but do not
                # increment team counts again.
                _capped_card.append(_bout)
                continue
            _pw_count = _team_fight_count.get(_pw_team, 0)
            _ow_count = _team_fight_count.get(_ow_team, 0)
            _pw_would_cap = (_pw_team not in _FODDER_TEAMS and _pw_count >= 5)
            _ow_would_cap = (_ow_team not in _FODDER_TEAMS and _ow_count >= 5)
            if _pw_would_cap or _ow_would_cap:
                _who = _pw_team if _pw_would_cap else _ow_team
                print(f"  5-FIGHT CAP: dropping {_pw_name} vs {_ow_name} "
                      f"— {_who} already at 5 fights")
                continue
            if _pw_team not in _FODDER_TEAMS:
                _team_fight_count[_pw_team] = _pw_count + 1
            if _ow_team not in _FODDER_TEAMS:
                _team_fight_count[_ow_team] = _ow_count + 1
            _capped_card.append(_bout)
        card = _capped_card

        fight_logs, bouts = {}, []
        for bout in card:
            pw  = bout.player_warrior
            ow  = bout.opponent

            # ------------------------------------------------------------------
            # P-vs-P INJECTION: if pw was pre-fought in the pre-pass, inject
            # the stored result rather than running a second fight.
            # ------------------------------------------------------------------
            _pvp = _pvp_by_warrior.get(pw.name)
            if _pvp is not None:
                result = _pvp["result"]
                fid    = _pvp["fid"]
                _is_canonical_pw = (pw.name == _pvp["canonical_pw"])
                if _is_canonical_pw:
                    opp_name    = _pvp["canonical_ow"]
                    opp_race    = _pvp["ow_race"]
                    opp_team    = _pvp["ow_team"]
                    opp_manager = _pvp["ow_manager"]
                    opp_tf      = _pvp["ow_trained_dict"]["total_fights"]
                    trained_d   = _pvp["pw_trained_dict"]
                    training_key= "warrior_a"
                else:
                    opp_name    = _pvp["canonical_pw"]
                    opp_race    = _pvp["pw_race"]
                    opp_team    = _pvp["pw_team"]
                    opp_manager = _pvp["pw_manager"]
                    opp_tf      = _pvp["pw_trained_dict"]["total_fights"]
                    trained_d   = _pvp["ow_trained_dict"]
                    training_key= "warrior_b"

                # Copy fight-modified fields (record_result + training) from the
                # pre-pass warrior onto the fresh pw in player_team.
                pw.wins           = trained_d.get("wins",           pw.wins)
                pw.losses         = trained_d.get("losses",         pw.losses)
                pw.kills          = trained_d.get("kills",          pw.kills)
                pw.total_fights   = trained_d.get("total_fights",   pw.total_fights)
                pw.streak         = trained_d.get("streak",         pw.streak)
                pw.skills         = trained_d.get("skills",         pw.skills)
                pw.attribute_gains= trained_d.get("attribute_gains",pw.attribute_gains)
                pw.strength       = trained_d.get("strength",       pw.strength)
                pw.dexterity      = trained_d.get("dexterity",      pw.dexterity)
                pw.constitution   = trained_d.get("constitution",   pw.constitution)
                pw.intelligence   = trained_d.get("intelligence",   pw.intelligence)
                pw.presence       = trained_d.get("presence",       pw.presence)
                pw.injuries.from_dict(trained_d.get("injuries", {}))
                pw.recalculate_derived()

                pw_won = result.winner is not None and result.winner.name == pw.name
                killed = result.loser_died and pw_won
                slain  = result.loser_died and not pw_won
                pwr    = "win" if pw_won else "loss"

                _champ_name = champ_state.get("name", "") if isinstance(champ_state, dict) else ""
                fight_type_to_record = (
                    "champion" if (_champ_name and (
                        opp_name == _champ_name or pw.name == _champ_name
                    )) else _pvp["fight_type"]
                )

                # Store the correct perspective for each manager.
                # canonical_pw is warrior_a — their manager gets the forward narrative
                # (own training shown specifically, opponent shown as "Skill").
                # The opposing manager (canonical_ow) needs the mirror narrative.
                if _is_canonical_pw:
                    fight_logs[str(fid)] = result.narrative
                else:
                    fight_logs[str(fid)] = _make_mirror_narrative(
                        result.narrative,
                        result.training_results,
                        _pvp["canonical_pw"],
                        _pvp["canonical_ow"],
                    )

                pw.update_popularity(won=pw_won)
                pw.update_recognition(
                    won=pw_won,
                    killed_opponent=killed,
                    self_hp_pct=result.winner_hp_pct if pw_won else result.loser_hp_pct,
                    opp_hp_pct=result.loser_hp_pct   if pw_won else result.winner_hp_pct,
                    self_knockdowns=result.winner_knockdowns if pw_won else result.loser_knockdowns,
                    opp_knockdowns=result.loser_knockdowns   if pw_won else result.winner_knockdowns,
                    self_near_kills=result.winner_near_kills if pw_won else result.loser_near_kills,
                    opp_near_kills=result.loser_near_kills   if pw_won else result.winner_near_kills,
                    minutes_elapsed=result.minutes_elapsed,
                    opponent_total_fights=opp_tf,
                )
                pw.fight_history.append({
                    "turn": turn_num, "opponent_name": opp_name,
                    "opponent_race": opp_race, "opponent_team": opp_team,
                    "result": pwr, "minutes": result.minutes_elapsed, "fight_id": fid,
                    "warrior_slain": slain, "opponent_slain": killed, "is_kill": killed,
                    "fight_type": fight_type_to_record,
                })
                if slain:
                    player_team.kill_warrior(pw, killed_by=opp_name, killer_fights=opp_tf)
                opp_trained_d = _pvp["ow_trained_dict"] if _is_canonical_pw else _pvp["pw_trained_dict"]
                bouts.append({
                    "warrior_name": pw.name, "opponent_name": opp_name,
                    "opponent_race": opp_race, "opponent_team": opp_team,
                    "opponent_manager": opp_manager, "fight_type": fight_type_to_record,
                    "result": pwr.upper(), "minutes": result.minutes_elapsed, "fight_id": fid,
                    "warrior_slain": slain, "opponent_slain": killed,
                    "ascension": False,  # P-vs-P never involves monsters
                    "opponent_wins":   opp_trained_d.get("wins",   0),
                    "opponent_losses": opp_trained_d.get("losses", 0),
                    "opponent_kills":  opp_trained_d.get("kills",  0),
                    "training": result.training_results.get(training_key, []),
                })
                continue  # skip the normal run_fight path below

            _dbg_logger = None
            fid = None
            if _debug_warrior_names and (pw.name in _debug_warrior_names or ow.name in _debug_warrior_names):
                from combat_debug_logger import CombatDebugLogger as _CDBLogger2
                fid = _next_fid(cfg)
                _dbg_logger = _CDBLogger2()
                _dbg_logger.fight_id   = fid
                _dbg_logger.turn_num   = turn_num
                _dbg_logger.debug_team = _dbg_mgr_name
            result = run_fight(
                pw, ow,
                team_a_name    = player_team.team_name,
                team_b_name    = bout.opponent_team.team_name,
                manager_a_name = mname,
                manager_b_name = bout.opponent_manager,
                is_monster_fight=(bout.opponent_team.team_name == "The Monsters"),
                challenger_name = getattr(bout, 'challenger_name', None),
                debug_logger   = _dbg_logger,
            )
            # Inject scout-attendance flavor text if any manager is watching either warrior
            try:
                from save import get_all_scouted_warriors
                scouted  = get_all_scouted_warriors(turn_num)
                attending= set()
                for warrior in (pw, ow):
                    for mgr in scouted.get(warrior.name, []):
                        attending.add(mgr)
                if attending:
                    mgr_list   = ", ".join(sorted(attending))
                    scout_line = (
                        f"\n[A scout from {mgr_list}'s stable is in attendance, "
                        f"watching the proceedings with a keen eye.]\n"
                    )
                    from combat import FightResult
                    result = FightResult(
                        winner           = result.winner,
                        loser            = result.loser,
                        loser_died       = result.loser_died,
                        minutes_elapsed  = result.minutes_elapsed,
                        narrative        = scout_line + result.narrative,
                        training_results = result.training_results,
                    )
            except Exception:
                pass

            # Persist fight narrative for any scouted warrior in this bout
            try:
                for _w in (pw, ow):
                    if _w.name in scouted:
                        _store_scout_narrative(_w.name, result.narrative, turn_num)
            except Exception:
                pass

            if fid is None:
                fid = _next_fid(cfg)
            if _dbg_logger and _dbg_turn_dir:
                _log_path = os.path.join(_dbg_turn_dir, f"fight_{fid:05d}_{pw.name}_vs_{ow.name}.txt")
                try:
                    _dbg_logger.write_to_file(_log_path)
                except Exception as _log_err:
                    print(f"  DEBUG LOG WARN (main): {_log_err}")
            fight_logs[str(fid)] = result.narrative
            pw_won = result.winner is not None and result.winner.name == pw.name
            killed = result.loser_died and pw_won
            slain  = result.loser_died and not pw_won
            pwr    = "win" if pw_won else "loss"

            # If either warrior is the reigning champion, record as a champion title fight
            _champ_name = champ_state.get("name", "") if isinstance(champ_state, dict) else ""
            fight_type_to_record = (
                "champion" if (_champ_name and (
                    ow.name == _champ_name or pw.name == _champ_name
                )) else bout.fight_type
            )

            # NOTE: record_result() is already called inside run_fight() (combat.py).
            # Do NOT call it again here — wins/losses/kills would be double-counted.

            # Update popularity and recognition (NOT called inside run_fight)
            pw.update_popularity(won=pw_won)
            pw.update_recognition(
                won=pw_won,
                killed_opponent=killed,
                self_hp_pct=result.winner_hp_pct if pw_won else result.loser_hp_pct,
                opp_hp_pct=result.loser_hp_pct if pw_won else result.winner_hp_pct,
                self_knockdowns=result.winner_knockdowns if pw_won else result.loser_knockdowns,
                opp_knockdowns=result.loser_knockdowns if pw_won else result.winner_knockdowns,
                self_near_kills=result.winner_near_kills if pw_won else result.loser_near_kills,
                opp_near_kills=result.loser_near_kills if pw_won else result.winner_near_kills,
                minutes_elapsed=result.minutes_elapsed,
                opponent_total_fights=ow.total_fights,
            )

            pw.fight_history.append({
                "turn": turn_num, "opponent_name": ow.name,
                "opponent_race": ow.race.name, "opponent_team": bout.opponent_team.team_name,
                "result": pwr, "minutes": result.minutes_elapsed, "fight_id": fid,
                "warrior_slain": slain, "opponent_slain": killed, "is_kill": killed,
                "fight_type": fight_type_to_record,
            })
            if slain:
                player_team.kill_warrior(pw, killed_by=ow.name, killer_fights=ow.total_fights)

            # Monster ascension: if the player warrior slew a monster, they
            # are absorbed into The Monsters roster (replacing the fallen
            # opponent) and their slot on the player team opens for a
            # replacement, just as if they had died.
            ascended = False
            if killed and bout.fight_type == "monster":
                pw.monster_kills = getattr(pw, "monster_kills", 0) + 1
                pw.ascended_to_monster = True
                from matchmaking import _absorb_into_monsters
                _absorb_into_monsters(pw, player_team, ow, bout.opponent_team)
                ascended = True
                print(f"  !!! {pw.name} has SLAIN a monster and joins The Monsters! !!!")

            bouts.append({
                "warrior_name": pw.name, "opponent_name": ow.name,
                "opponent_race": ow.race.name, "opponent_team": bout.opponent_team.team_name,
                "opponent_manager": bout.opponent_manager, "fight_type": fight_type_to_record,
                "result": pwr.upper(), "minutes": result.minutes_elapsed, "fight_id": fid,
                "warrior_slain": slain, "opponent_slain": killed,
                "ascension": ascended,
                "opponent_wins":   ow.wins,
                "opponent_losses": ow.losses,
                "opponent_kills":  ow.kills,
                "training": result.training_results.get("warrior_a", []),
            })

            # MIRROR BOUT: when ow belongs to a different AI team, register
            # the fight from the OW perspective so that team's result reflects
            # it. Without this, AI teams that had warriors fight as OW see their
            # bouts list under-count and their "last 5 turns" standings show
            # fewer than 5 fights per turn. Also append to ow.fight_history
            # since run_fight/record_result don't track per-fight history.
            _ow_mid = ai_warrior_to_mid.get(ow.name)
            if _ow_mid and _ow_mid != manager_id:
                try:
                    _ow_narr = result.narrative if hasattr(result, "narrative") else ""
                    fight_logs[str(fid)] = fight_logs.get(str(fid), _ow_narr)
                    _mirror = {
                        "warrior_name":     ow.name,
                        "opponent_name":    pw.name,
                        "opponent_race":    pw.race.name,
                        "opponent_team":    player_team.team_name,
                        "opponent_manager": mname,
                        "fight_type":       fight_type_to_record,
                        "result":           "LOSS" if pw_won else "WIN",
                        "minutes":          result.minutes_elapsed,
                        "fight_id":         fid,
                        "warrior_slain":    killed,
                        "opponent_slain":   slain,
                        "ascension":        False,
                        "opponent_wins":    pw.wins,
                        "opponent_losses":  pw.losses,
                        "opponent_kills":   pw.kills,
                        "training":         result.training_results.get("warrior_b", []),
                        "_fight_log":       _ow_narr,
                    }
                    _ai_mirror_bouts.setdefault(_ow_mid, []).append(_mirror)
                    ow.fight_history.append({
                        "turn": turn_num, "opponent_name": pw.name,
                        "opponent_race": pw.race.name, "opponent_team": player_team.team_name,
                        "result": "loss" if pw_won else "win",
                        "minutes": result.minutes_elapsed, "fight_id": fid,
                        "warrior_slain": killed, "opponent_slain": slain, "is_kill": slain,
                        "fight_type": fight_type_to_record,
                    })
                except Exception as _mb_err:
                    print(f"  WARN: mirror bout registration failed for {ow.name}: {_mb_err}")

        # Create two versions:
        # 1. team_slim: for server-side storage (strip fight_history to save space)
        # 2. team_full: for client download (keep fight_history so client has complete picture)
        team_full = player_team.to_dict()
        
        # Enrich warrior data with UI fields (height/weight/hp/injuries) before saving result
        for i, w_obj in enumerate(player_team.warriors):
            if w_obj and i < len(team_full.get("warriors", [])):
                wd = team_full["warriors"][i]
                if wd:
                    wd["height_in"] = getattr(w_obj, "height_in", 0)
                    wd["weight_lbs"] = getattr(w_obj, "weight_lbs", 0)
                    wd["max_hp"] = getattr(w_obj, "max_hp", 0)
                    if hasattr(w_obj, "injuries") and hasattr(w_obj.injuries, "to_dict"):
                        wd["injuries"] = w_obj.injuries.to_dict()

        # Server storage version: stripped fight_history
        team_slim = dict(team_full)
        team_slim["warriors"] = []
        for wd in team_full.get("warriors", []):
            if not wd:
                team_slim["warriors"].append(None)
                continue
            ws = dict(wd)
            ws.pop("fight_history", None)   # strip — large and not needed server-side
            team_slim["warriors"].append(ws)
        
        # Client version: KEEP fight_history for complete record display
        team_for_client = dict(team_full)
        # Don't strip fight_history — clients need it to verify record accuracy
        
        # Preserve archived warriors (they have stats but no fight_history)
        team_slim["archived_warriors"] = team_full.get("archived_warriors", [])
        team_for_client["archived_warriors"] = team_full.get("archived_warriors", [])
        
        # Update turn_history with this turn's results.
        # The upload now includes the client's existing turn_history so we can
        # build an accurate last-5-turns record.  Remove any stale entry for
        # this turn first (handles reruns), then append the fresh one.
        if "turn_history" not in team_for_client:
            team_for_client["turn_history"] = []
        team_for_client["turn_history"] = [
            e for e in team_for_client["turn_history"]
            if e.get("turn") != turn_num
        ]
        team_for_client["turn_history"].append({
            "turn": turn_num,
            "w": sum(1 for b in bouts if b.get("result") == "WIN"),
            "l": sum(1 for b in bouts if b.get("result") == "LOSS"),
            "k": sum(1 for b in bouts if b.get("opponent_slain")),
        })

        mgr_res = {
            "turn"        : turn_num,
            "manager_name": mname,
            "team_id"     : player_team.team_id,
            "team_name"   : player_team.team_name,
            "bouts"       : bouts,
            "team"        : team_for_client,  # Use FULL version with fight_history for client
            "fight_logs"  : fight_logs,
        }
        _save_result(turn_num, manager_id, mgr_res)
        all_results[manager_id] = mgr_res

    # Merge mirror bouts: AI teams whose warriors fought as OW in another
    # manager's iteration need those fights in their own bouts list so the
    # "last 5 turns" standings and bout display reflect 5 fights/turn.
    for _mid, _mbouts in _ai_mirror_bouts.items():
        if _mid not in all_results:
            continue
        _res = all_results[_mid]
        _res.setdefault("bouts", [])
        _res.setdefault("fight_logs", {})
        _existing_fids = {str(b.get("fight_id")) for b in _res["bouts"]}
        for _mb in _mbouts:
            _fid = str(_mb.get("fight_id"))
            if _fid in _existing_fids:
                continue  # already present (e.g., duplicate registration)
            _log_text = _mb.pop("_fight_log", None)
            if _log_text and _fid not in _res["fight_logs"]:
                _res["fight_logs"][_fid] = _log_text
            _res["bouts"].append(_mb)
            _existing_fids.add(_fid)
        # Refresh turn_history for this team with the merged bouts so
        # evolve_ai_teams computes the correct W/L/K for "last 5".
        _team = _res.get("team") or {}
        _th = _team.setdefault("turn_history", [])
        _th[:] = [e for e in _th if e.get("turn") != turn_num]
        _th.append({
            "turn": turn_num,
            "w": sum(1 for b in _res["bouts"] if b.get("result") == "WIN"),
            "l": sum(1 for b in _res["bouts"] if b.get("result") == "LOSS"),
            "k": sum(1 for b in _res["bouts"] if b.get("opponent_slain")),
        })
        # Persist the augmented result to disk
        _save_result(turn_num, _mid, _res)

    # Update standings (skip AI-only results from standings if desired, but include them)
    try:
        standings = _load_standings()
        for mid, res in all_results.items():
            if mid not in standings:
                standings[mid] = {"manager_name": res["manager_name"], "turns_played": 0,
                                  "warriors": {}, "is_ai": mid.startswith("ai_"),
                                  "turns_counted": []}
            e = standings[mid]
            # Track which turns have been counted to avoid double-counting on reruns
            if "turns_counted" not in e:
                e["turns_counted"] = []
            if turn_num not in e["turns_counted"]:
                e["turns_played"] += 1
                e["turns_counted"].append(turn_num)
            
            # Process both active and archived warriors to ensure career stats 
            # are never lost from the standings after a replacement.
            all_fighters = (res["team"].get("warriors", []) + res["team"].get("archived_warriors", []))
            for wd in all_fighters:
                if not wd: continue
                wn = wd["name"]
                if wn not in e["warriors"]:
                    e["warriors"][wn] = {"wins":0,"losses":0,"kills":0,"fights":0}
                ws = e["warriors"][wn]
                ws.update(wins=wd.get("wins",0), losses=wd.get("losses",0),
                          kills=wd.get("kills",0), fights=wd.get("total_fights",0))
        _save_standings(standings)
    except Exception as _se:
        import traceback; traceback.print_exc()
        print(f"  WARNING: standings update failed: {_se}")

    # Evolve AI teams — apply fight results, handle deaths, train survivors
    try:
        from ai_league_teams import evolve_ai_teams
        ai_results = {mid: r for mid,r in all_results.items() if mid.startswith("ai_")}
        if ai_teams:
            evolve_ai_teams(ai_teams, ai_results)
            print(f"  AI teams evolved and saved ({len(ai_results)} teams processed).")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  WARNING: AI team evolution failed: {e}")

    with _lock:
        # Re-load from disk to pick up any admin edits made while fighting.
        # Carry forward only the fields this function owns: fight_counter,
        # turn_state, and current_turn.
        in_memory_fight_counter = cfg.get("fight_counter", 0)
        cfg = _load_config()
        cfg["fight_counter"] = max(cfg.get("fight_counter", 0),
                                   in_memory_fight_counter)
        if not rerun_turn:
            cfg["turn_state"]   = "results_ready"
            cfg["current_turn"] = turn_num + 1
        else:
            cfg["turn_state"] = "results_ready"
        import datetime as _dt3
        _completed_at = _dt3.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if cfg.get("schedule_last_run_turn") == turn_num:
            cfg["schedule_last_run_result"] = f"Completed at {_completed_at}"
            for _slot in cfg.get("schedule_slots", []):
                if _slot.get("last_run_turn") == turn_num:
                    _slot["last_run_result"] = f"Completed at {_completed_at}"
                    break

        # Restore UI visibility flags ONLY if they are missing from reloaded config.
        # This prevents accidental resets if the disk read failed, but allows manual
        # edits to take effect immediately for the next turn run.
        for k, start_val in _turn_start_flags.items():
            if k not in cfg:
                cfg[k] = start_val

        print(f"  [flags] Saved at turn end: "
              f"fav_wpn={cfg.get('show_favorite_weapon')} "
              f"luck={cfg.get('show_luck_factor')} "
              f"max_hp={cfg.get('show_max_hp')}")
        _save_config(cfg)
        _turn_progress = {"running": False, "done": len(uploads), "total": len(uploads),
                          "message": f"Turn {turn_num} complete — {len(all_results)} managers."}

        # Auto-carry: snapshot each qualifying team's post-turn state as an
        # upload for the NEXT turn, so managers don't have to re-upload unless
        # a warrior died.  A team qualifies only if it still has 5 active
        # warriors (none is_dead, no empty slots).  A team that lost a warrior
        # this turn is skipped — the manager must build a replacement and
        # upload manually before that team can fight again.  Manual uploads
        # are never overwritten; auto-carries from a prior run of this same
        # turn are (so reruns refresh cleanly).
        # Teams that were replaced/withdrawn (removed from manager's team_ids)
        # are never auto-carried, even if they ran this turn.
        _next_turn    = cfg["current_turn"]
        _auto_ts      = time.strftime("%Y-%m-%d %H:%M:%S")
        _mgrs_current = _load_managers()
        for _key, _res in all_results.items():
            if _key.startswith("ai_"):
                continue
            _team_dict = _res.get("team") or {}
            _warriors  = _team_dict.get("warriors") or []
            if len(_warriors) != 5:
                continue
            if any((w is None) or w.get("is_dead") for w in _warriors):
                continue
            _real_mid = _key.split("_team")[0]
            _tid      = _res.get("team_id") or _team_dict.get("team_id", "")
            # Skip auto-carry if this team is no longer in the manager's roster
            # (covers replaced/withdrawn teams).
            try:
                _int_tid = int(_tid)
                _mgr_tids = [int(t) for t in _mgrs_current.get(_real_mid, {}).get("team_ids", [])
                             if str(t).isdigit()]
            except (ValueError, TypeError):
                _mgr_tids = []
                _int_tid  = None
            if _int_tid not in _mgr_tids:
                print(f"  [auto-carry] Skipping team {_tid} for {_real_mid} — no longer in manager roster.")
                continue
            _fname    = (f"upload_{_real_mid}_team{_tid}.json" if _tid
                         else f"upload_{_real_mid}.json")
            _target   = os.path.join(_turn_dir(_next_turn), _fname)
            _existing = _load_json(_target, None)
            if _existing and not _existing.get("auto_uploaded"):
                continue
            _save_upload(_next_turn, _real_mid, {
                "manager_id"   : _real_mid,
                "manager_name" : _res.get("manager_name", ""),
                "team_id"      : _tid,
                "team"         : _team_dict,
                "uploaded_at"  : f"{_auto_ts} (auto-carry)",
                "auto_uploaded": True,
            })

    # Generate arena newsletter for this turn
    newsletter_text = ""
    try:
        import sys as _sys; _sys.path.insert(0, BASE_DIR)
        from newsletter import generate_newsletter, _update_champion
        from save import load_champion_state, save_champion_state, load_newsletter_voice
        import datetime as _dt

        # Build team objects from result data (non-AI only for newsletter)
        nl_teams = []
        for mid2, res in all_results.items():
            if mid2.startswith("ai_"): continue
            try:
                from team import Team
                t = Team.from_dict(res["team"])
                # turn_history already has this turn appended in team_for_client above
                nl_teams.append(t)
            except Exception:
                pass

        # Include AI teams in newsletter standings
        try:
            from ai_league_teams import load_ai_teams
            from warrior import Warrior
            for at in (load_ai_teams() or []):
                try:
                    t = Team.from_dict(at)
                    nl_teams.append(t)
                except Exception:
                    pass
        except Exception:
            pass

        # Deaths this turn — pull real W/L/K from the team result data
        deaths_nl = []
        _seen_deaths = set()
        for mid2, res in all_results.items():
            team_dict = res.get("team", {})
            warriors_by_name = {
                wd["name"]: wd
                for wd in team_dict.get("warriors", []) if wd
            }
            for b in res.get("bouts", []):
                if b.get("warrior_slain"):
                    wname = b.get("warrior_name", "?")
                    if wname in _seen_deaths:
                        continue
                    _seen_deaths.add(wname)
                    wd    = warriors_by_name.get(wname, {})
                    deaths_nl.append({
                        "name"     : wname,
                        "team"     : res.get("team_name","?"),
                        "w"        : wd.get("wins",  b.get("wins",  0)),
                        "l"        : wd.get("losses", b.get("losses", 0)),
                        "k"        : wd.get("kills",  b.get("kills",  0)),
                        "killed_by": b.get("opponent_name","?"),
                    })
                elif b.get("opponent_slain"):
                    # Opponent (rival/AI) was killed by the player's warrior —
                    # AI teams don't fight player teams from their own perspective,
                    # so this death would otherwise be invisible to the deaths list.
                    oname = b.get("opponent_name", "?")
                    if oname in _seen_deaths:
                        continue
                    _seen_deaths.add(oname)
                    deaths_nl.append({
                        "name"     : oname,
                        "team"     : b.get("opponent_team", "?"),
                        "w"        : b.get("opponent_wins",   0),
                        "l"        : b.get("opponent_losses", 0),
                        "k"        : b.get("opponent_kills",  0),
                        "killed_by": b.get("warrior_name", "?"),
                    })

        # Build a minimal card-like list for the newsletter — all managers including AI
        class _Bout:
            pass
        fake_card = []
        for mid2, res in all_results.items():
            try:
                t = Team.from_dict(res["team"])
                for b in res.get("bouts",[]):
                    bout = _Bout()
                    bout.player_warrior = next(
                        (w for w in t.warriors if w and w.name==b.get("warrior_name")),
                        type("W",(),{"name":b.get("warrior_name","?"),"race":type("R",(),{"name":"Human"})()})()
                    )
                    bout.opponent       = type("W",(),{"name":b.get("opponent_name","?"),"race":type("R",(),{"name":"Human"})()})()
                    bout.player_team    = t
                    bout.opponent_team  = type("T",(),{"team_name":b.get("opponent_team","?"),"team_id":0})()
                    bout.opponent_manager = b.get("opponent_manager","?")
                    bout.fight_type     = b.get("fight_type","rivalry")
                    pw_won = b.get("result","LOSS")=="WIN"
                    bout.result         = type("R",(),{
                        "winner"       : bout.player_warrior if pw_won else bout.opponent,
                        "loser"        : bout.opponent if pw_won else bout.player_warrior,
                        "loser_died"   : b.get("warrior_slain",False) or b.get("opponent_slain",False),
                        "minutes_elapsed": b.get("minutes",3),
                    })()
                    fake_card.append(bout)
            except Exception:
                pass

        # VALIDATION: Check for fight frequency violations
        from matchmaking import validate_warrior_fight_frequency, validate_team_fight_count
        warrior_violations = validate_warrior_fight_frequency(fake_card)
        team_violations = validate_team_fight_count(fake_card, max_fights=5)
        
        if warrior_violations:
            print(f"  WARNING: Found {len(warrior_violations)} warrior(s) fighting more than once per turn:")
            for v in warrior_violations:
                print(f"    - {v['warrior']} ({v['team']}): {v['fight_count']} fights (expected max 1)")
        
        if team_violations:
            print(f"  WARNING: Found {len(team_violations)} team(s) with more than 5 fights:")
            for v in team_violations:
                print(f"    - {v['team']}: {v['fight_count']} fights (expected max {v['max_allowed']})")

        champ_state = load_champion_state()

        # Detect if the reigning champion was beaten this turn.
        # The champion retains the title unless they actually lose a fight —
        # not fighting, or fighting a peasant, never costs them the title.
        _champ_beaten_by   = None
        _champ_beaten_team = None
        _cur_champ = champ_state.get("name", "")
        if _cur_champ:
            for _bout in fake_card:
                _pw_won  = _bout.result.winner.name == _bout.player_warrior.name
                _winner  = _bout.player_warrior if _pw_won else _bout.opponent
                _loser   = _bout.opponent       if _pw_won else _bout.player_warrior
                _w_team  = (_bout.player_team.team_name if _pw_won
                            else _bout.opponent_team.team_name)
                if _loser.name == _cur_champ:
                    _champ_beaten_by   = _winner.name
                    _champ_beaten_team = _w_team
                    break

        prev_champion_name = champ_state.get("name", "")
        champ_state, is_new_champion = _update_champion(nl_teams, champ_state, deaths_nl,
                                                         champion_beaten_by=_champ_beaten_by,
                                                         champion_beaten_team=_champ_beaten_team,
                                                         prev_champion_name=prev_champion_name)
        save_champion_state(champ_state)

        voice = load_newsletter_voice()
        date_str = _dt.date.today().strftime("%m/%d/%Y")
        newsletter_text = generate_newsletter(
            turn_num           = turn_num,
            card               = fake_card,
            teams              = nl_teams,
            deaths             = deaths_nl,
            champion_state     = champ_state,
            voice              = voice,
            processed_date     = date_str,
            is_new_champion    = is_new_champion,
        )
        # Save newsletter to league turn directory
        nl_path = os.path.join(_turn_dir(turn_num), "newsletter.txt")
        with open(nl_path, "w", encoding="utf-8") as _f:
            _f.write(newsletter_text)
        print(f"  Newsletter written: {nl_path}")
    except Exception as _e:
        import traceback; traceback.print_exc()
        print(f"  WARNING: newsletter generation failed: {_e}")

    total_fights = sum(len(r["bouts"]) for r in all_results.values())
    print(f"\n  Turn {turn_num} complete — {len(all_results)} manager(s), {total_fights} fight(s).")
    return {"success": True, "turn_number": turn_num,
            "managers": len(all_results), "fights": total_fights,
            "newsletter": newsletter_text}


def _filter_warrior_for_client(warrior_dict: dict, cfg: dict) -> dict:
    """
    Filter warrior data for client download based on feature flags.
    Removes sensitive fields if flags are disabled.
    """
    w = warrior_dict.copy()
    # Remove luck factor if flag is off
    if not cfg.get("show_luck_factor", False):
        w.pop("luck", None)
    # Remove favorite weapon if flag is off  
    if not cfg.get("show_favorite_weapon", False):
        w.pop("favorite_weapon", None)
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
# ADMIN PAGE (HTML) — Updated with Delete Manager Dropdown + Button
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
                     f"({', '.join(parts)}) — {mgr_upload_times.get(mid,'')}</b>")
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
    if ai_count:
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
    # Manager options for delete dropdown
    manager_options = ""
    for mid, mgr in managers.items():
        manager_options += f'<option value="{mid}">{mgr["manager_name"]} (ID: {mid})</option>'

    _dbg_mid = cfg.get("admin_debug_manager_id", "")
    _dbg_display = managers.get(_dbg_mid, {}).get("manager_name", "None (disabled)") if _dbg_mid else "None (disabled)"

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BLOODSPIRE League — Admin</title>
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
</style></head><body>
<div class="bar">⚔ BLOODSPIRE League — Admin
 <span>Turn {turn}</span>
 <span class="state">{state_display}</span>
 <span id="sched-top-badge" style="display:none;background:#060;color:#fff;padding:2px 8px;border-radius:3px;font-size:10px;margin-left:8px;vertical-align:middle;border:1px solid #0a0">AUTO-SCHEDULE ON</span>
 <span>{len(mgr_upload_counts)}/{len(managers)} players + {ai_count} AI uploaded</span>
</div>
<div id="msg"></div>
{'<div style="background:#0a3;color:#fff;padding:10px 18px;font-size:13px;border-bottom:2px solid #080;display:flex;align-items:center;gap:12px"><span style="font-size:18px">✓</span><span><strong>Auto-scheduled turn ' + str(last_sched_turn) + ' completed</strong> — ' + last_sched_result.replace("Completed at ","") + '</span></div>' if auto_completed else ''}
<div class="wrap">
 <div class="panel" style="min-width:260px;max-width:340px">
  <h3>Run Turn {turn}</h3>
  <p style="font-size:11px;color:#555;margin:0 0 6px">
   {len(uploads)} of {len(managers)} players uploaded.<br>
   {ai_count} AI teams auto-included. Players who haven't uploaded are skipped.
  </p>
  Host password:<br>
  <input type="password" id="hp" style="width:200px"><br>
  <button onclick="runTurn()">▶ Run Turn {turn}</button>
  <button title="Force unlock if hung" onclick="unlockTurn()" style="background:#eee;border-color:#ccc;color:#666;margin-left:4px">🔓</button>
  <div id="prog-wrap" class="prog-wrap" style="display:none">
   <div id="prog-bar" class="prog-bar" style="width:0%"></div>
   <div id="prog-lbl" class="prog-lbl">Starting...</div>
  </div>
  {rerun_section}
 </div>
 <div class="panel">
  <h3>Upload Status — Turn {turn}</h3>
  <table><tr><th>Manager</th><th>Status</th></tr>{urows}</table>
 </div>
 <div class="panel" style="min-width:220px;max-width:280px">
  <h3>Arena Reset</h3>
  <p style="font-size:11px;color:#800;margin:0 0 8px">
   ⚠ Full wipe: deletes ALL turn history, fight records, standings,<br>
   manager registrations, and teams. AI teams are regenerated.<br>
   Every player will need to re-register after this.
  </p>
  <button class="danger" onclick="resetArena()">🗑 Reset Arena to Turn 1</button>
 </div>
 <div class="panel" style="min-width:220px;max-width:320px">
  <h3>Feature Flags (Testing)</h3>
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
  <div style="margin-top:8px;font-size:10px;color:#888">
   Changes apply on next turn run.
  </div>
 </div>
 <div class="panel" style="min-width:260px;max-width:380px">
  <h3>Turn Schedule</h3>
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
 <!-- ====================== DELETE MANAGER PANEL ====================== -->
 <div class="panel" style="min-width:300px;">
  <h3 style="color:#c00;">Delete Manager (DANGER ZONE)</h3>
  <p style="color:#c00;font-size:12px;margin-bottom:10px;">
   ⚠ This will permanently delete the selected manager and all their uploaded data for the current turn.
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
 <!-- ====================== COMBAT DEBUG LOGGING ====================== -->
 <div class="panel" style="min-width:260px;max-width:340px">
  <h3>Combat Debug Logging</h3>
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
</div>

<script>
let _pollTimer=null;
let _isNavigating=false;  // prevents beforeunload from killing server on auto-reload
let _seenRunning=false;   // ensures poll only fires completion after turn actually started

// Existing functions (runTurn, rerunTurn, resetArena, etc.)
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
  if(!d.success){{show('Error: '+d.error,'err');stopPoll();}}
 }}catch(e){{show('Connection error: '+e.message,'err');stopPoll();}}
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
  if(!d.success){{show('Error: '+d.error,'err');stopPoll();}}
 }}catch(e){{show('Connection error: '+e.message,'err');stopPoll();}}
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
   show(`Done — ${{d.message}}`,'ok');
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
  if(!pw){{show('Schedule not saved — host password required.','err');return false;}}
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
    show(`Saved: ${{enabled?'enabled':'disabled'}} — ${{slotDesc}}`,'ok');
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
    ? `Last auto-run: turn ${{d.schedule_last_run_turn}}${{d.schedule_last_run_at?` at ${{d.schedule_last_run_at}}`:''}}${{d.schedule_last_run_result?` — ${{d.schedule_last_run_result}}`:''}}` : 'Last auto-run: never';
   el.textContent=`${{nextTxt}} | ${{last}}`;
   const badge=document.getElementById('sched-top-badge');
   if(badge) badge.style.display=d.schedule_enabled?'inline-block':'none';
  }}catch(e){{}}
}}

setTimeout(refreshScheduleStatus, 0);

// Persist feature-flag toggles so they survive turn reloads.
window.toggleFlag = async function(evt,key){{
  // currentTarget can be null in inline onchange handlers in some browsers — fall back to target
  const el=evt?(evt.currentTarget||evt.target):null;
  const val=el?el.checked:false;
 let pw=pw_val();
 if(!pw){{
  pw=prompt('Host password required to save this flag:');
  if(!pw){{
   show('Flag not saved — host password required.','err');
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
    if (!confirm(`⚠ DANGER ZONE ⚠\n\nYou are about to PERMANENTLY delete:\n\n${{managerName}}\n\nAll their teams and results for the current turn will be removed.\n\nThis action CANNOT be undone.\n\nContinue?`)) {{
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
// =====================================================================

document.addEventListener('DOMContentLoaded',()=>{{
 // Wire feature-flag checkboxes via JS so no inline onchange globals needed
 document.querySelectorAll('input[data-flag]').forEach(el=>{{
  el.addEventListener('change', async function(){{
   const key=this.dataset.flag;
   const val=this.checked;
   let pw=pw_val();
   if(!pw){{
    pw=prompt('Host password required to save this flag:');
    if(!pw){{show('Flag not saved — host password required.','err');this.checked=!val;return;}}
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

// Browser close detection — only shut down on real tab close, not auto-reloads
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
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

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
                    "last_upload_timestamp": mgr.get("last_upload_timestamp", "—")
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
            }); return

        if path == "/api/newsletter":
            q        = self.qs()
            turn_num = int(q.get("turn", 0))
            if not turn_num:
                self.send_json({"success":False,"error":"turn required"}); return
            nl_path = os.path.join(_turn_dir(turn_num), "newsletter.txt")
            if not os.path.exists(nl_path):
                self.send_json({"success":False,"error":f"No newsletter for turn {turn_num}"}); return
            with open(nl_path,"r",encoding="utf-8") as _f:
                nl_text = _f.read()
            self.send_json({"success":True,"turn":turn_num,"newsletter":nl_text}); return

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
                    with open(nl_path,"r",encoding="utf-8") as _f:
                        nl_text = _f.read()
                    self.send_json({"success":True,"turn":turn_num,"newsletter":nl_text}); return
            self.send_json({"success":False,"error":"No newsletters found"}); return

        if path == "/api/fight_log":
            q       = self.qs()
            turn_n  = int(q.get("turn",  0))
            fid     = int(q.get("fight_id", 0))
            mid     = q.get("manager_id", "")
            pw      = q.get("password", "")
            if not turn_n or not fid:
                self.send_json({"success":False,"error":"turn and fight_id required"}); return
            # Auth check — require valid manager credentials
            mgrs = _load_managers()
            if mid and pw:
                if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                    self.send_json({"success":False,"error":"Not authorised."},401); return
            # Search result files for this turn.
            # Priority: check the requesting manager's own file(s) first so that
            # each manager sees their perspective of the training section.
            # Fall back to any result file if the fight_id isn't in the manager's own.
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
            }); return

        if path == "/api/game_data":
            # Static dropdown data the standalone client needs (races, weapons,
            # armor, triggers, styles, etc.). Cached by the client after first fetch.
            from warrior import (
                ATTRIBUTES, FIGHTING_STYLES, TRIGGERS, AIM_DEFENSE_POINTS,
                NON_WEAPON_SKILLS, WEAPON_SKILLS,
            )
            from weapons import WEAPONS
            from armor   import armor_selection_menu, helm_selection_menu
            from races   import list_playable_races
            self.send_json({
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
            }); return

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

        if path == "/api/results":
            q  = self.qs()
            mid= q.get("manager_id","")
            pw = q.get("password","")
            mgrs = _load_managers()
            if mid not in mgrs:
                self.send_json({"success":False,"error":"Manager not found. Register first."}, 404); return
            if not _check_mgr_pw(mgrs[mid], pw):
                self.send_json({"success":False,"error":"Wrong password."}, 401); return
            cfg = _load_config()
            res_turn = cfg["current_turn"] - 1
            if res_turn < 1:
                self.send_json({"success":False,"error":"No completed turns yet."}, 404); return
            # Collect ALL result files for this manager (one per uploaded team)
            td = _turn_dir(res_turn)
            team_results = []
            if os.path.exists(td):
                for fname in sorted(os.listdir(td)):
                    if fname.startswith(f"result_{mid}") and fname.endswith(".json"):
                        r = _load_json(os.path.join(td, fname), None)
                        if r:
                            # Strip only fight_logs (large narratives ~7KB each).
                            # Keep fight_history on warriors (~230 bytes/entry) --
                            # the client needs it for the Fights tab and View Fight.
                            r_slim = {k: v for k, v in r.items() if k != "fight_logs"}
                            team_results.append(r_slim)
            # Include newsletter for this turn if available
            nl_text = ""
            nl_path = os.path.join(_turn_dir(res_turn), "newsletter.txt")
            if os.path.exists(nl_path):
                with open(nl_path, "r", encoding="utf-8") as _nf:
                    nl_text = _nf.read()
            # If there are no team results, allow the request to succeed if a newsletter exists
            if not team_results and not nl_text:
                self.send_json({"success":False,"error":"No results found for your manager this turn."}); return
            # Filter results based on feature flags
            team_results = _filter_results_for_client(team_results, cfg)
            # Newsletter is served separately via /api/newsletter?turn=N
            # to keep /api/results payload small and avoid Windows socket aborts
            self.send_json({"success":True,"results":team_results,
                            "turn":res_turn,"has_newsletter":bool(nl_text)}); return

        if path == "/api/scout/status":
            q = self.qs()
            mid = q.get("manager_id","")
            pw  = q.get("password","")
            mgrs = _load_managers()
            if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                self.send_json({"success":False,"error":"Not authorised."}, 401); return
            from save import get_manager_scouting
            cfg = _load_config()
            selections = get_manager_scouting(mid, cfg["current_turn"])
            self.send_json({
                "success": True,
                "selections": selections,
                "slots_left": max(0, 3 - len(selections)),
            }); return

        if path == "/api/scout/targets" or path == "/api/challenge/targets":
            q = self.qs()
            mid = q.get("manager_id","")
            pw  = q.get("password","")
            mgrs = _load_managers()
            if mid not in mgrs or not _check_mgr_pw(mgrs[mid], pw):
                self.send_json({"success":False,"error":"Not authorised."}, 401); return
            # Exclude the caller's own teams from the target list.
            own_team_ids = set(int(t) for t in mgrs[mid].get("team_ids", []) if isinstance(t,(int,str)) and str(t).isdigit())
            # For /api/challenge/targets, also allow excluding one specific team
            # (the attacking team itself — its own warriors can't be challenged).
            try:    exclude_tid = int(q.get("team_id","0") or 0)
            except: exclude_tid = 0
            from save import TEAMS_DIR
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
                except Exception:
                    continue
                tid = tdata.get("team_id", 0)
                if tid in own_team_ids: continue
                if exclude_tid and tid == exclude_tid: continue
                team_name = tdata.get("team_name", "?")
                for w in tdata.get("warriors", []):
                    if not w or w.get("is_dead"): continue
                    warriors.append({
                        "name"        : w.get("name", "?"),
                        "team_name"   : team_name,
                        "team_id"     : tid,
                        "race"        : w.get("race", "?"),
                        "gender"      : w.get("gender", "?"),
                        "wins"        : w.get("wins", 0),
                        "losses"      : w.get("losses", 0),
                        "kills"       : w.get("kills", 0),
                        "max_hp"      : w.get("max_hp", 0),
                        "height_in"   : w.get("height_in", 0),
                        "weight_lbs"  : w.get("weight_lbs", 0),
                        "total_fights": w.get("total_fights", 0),
                    })
            self.send_json({"success": True, "warriors": warriors}); return

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
            scout_text = generate_scout_report(warrior_obj, last_fight, found_team_name)
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

        self.send_json({"error":"Not found."}, 404)

    # ── POST ──────────────────────────────────────────────────────────────
    def do_POST(self):
        path = self.p()
        b = self.body()

        if path == "/api/register":
            mname = (b.get("manager_name") or "").strip()
            pw = (b.get("password") or "").strip()
            if not mname or not pw:
                self.send_json({"success":False,"error":"manager_name and password required."}); return
            if len(pw) < 4:
                self.send_json({"success":False,"error":"Password must be at least 4 characters."}); return
            with _lock:
                mgrs = _load_managers()
                for existing_mid, m in mgrs.items():
                    if m["manager_name"].lower() == mname.lower():
                        if _check_mgr_pw(m, pw):
                            self.send_json({"success":True,"manager_id":existing_mid,"manager_name":m["manager_name"]}); return
                        self.send_json({"success":False,"error":"Manager name already taken."}); return
                # Numeric IDs, starting at 20 and incrementing. Legacy non-numeric
                # IDs (hex uuids from older builds) are skipped so they don't
                # poison the sequence.
                numeric_ids = [int(k) for k in mgrs.keys() if k.isdigit()]
                mid = str(max(numeric_ids) + 1) if numeric_ids else "20"
                salt = secrets.token_hex(16)
                mgrs[mid] = {"manager_name":mname,"salt":salt,
                             "password_hash":_hash_pw(pw,salt),
                             "registered_at":time.strftime("%Y-%m-%d %H:%M:%S")}
                _save_managers(mgrs)
            self.send_json({"success":True,"manager_id":mid,"manager_name":mname}); return

        if path == "/api/check_manager_name":
            mname = (b.get("manager_name") or "").strip()
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
            mid = (b.get("manager_id") or "").strip()
            pw  = (b.get("password")   or "").strip()
            team_name     = (b.get("team_name") or "").strip()
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
                manager_name = mgrs[mid]["manager_name"]
            from team    import Team, TEAM_SIZE
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
                    name = (wd.get("name") or "").strip()
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
                    team.add_warrior(w)
                save_team(team)
            except Exception as e:
                import traceback; traceback.print_exc()
                self.send_json({"success":False,"error":f"{e}"}); return
            # Record the team under the manager so the host has a manifest.
            with _lock:
                mgrs = _load_managers()
                if mid in mgrs:
                    tids = mgrs[mid].setdefault("team_ids", [])
                    if team.team_id not in tids:
                        tids.append(team.team_id)
                    _save_managers(mgrs)
            self.send_json({"success":True,"team_id":team.team_id,"team":team.to_dict()}); return

        if path == "/api/scout/select":
            mid   = (b.get("manager_id")   or "").strip()
            pw    = (b.get("password")     or "").strip()
            wname = (b.get("warrior_name") or "").strip()
            tname = (b.get("team_name")    or "").strip()
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
            ok, err = add_manager_scouting(mid, cfg["current_turn"], wname, tname, tid, confirmed=True)
            selections = get_manager_scouting(mid, cfg["current_turn"])
            self.send_json({
                "success": ok, "error": err if not ok else "",
                "selections": selections,
                "slots_left": max(0, 3 - len(selections)),
            }); return

        if path == "/api/scout/remove":
            mid   = (b.get("manager_id")   or "").strip()
            pw    = (b.get("password")     or "").strip()
            wname = (b.get("warrior_name") or "").strip()
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
            mid = (b.get("manager_id") or "").strip()
            pw = (b.get("password") or "").strip()
            team = b.get("team")
            if not all([mid, pw, team]):
                self.send_json({"success":False,"error":"manager_id, password and team required."}); return
            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs:
                    self.send_json({"success":False,"error":"Manager not found. Register first."}); return
                if not _check_mgr_pw(mgrs[mid], pw):
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
                    print(" WARNING: turn_state was stuck as 'processing' — auto-recovering.")
                    cfg["turn_state"] = "open"; _save_config(cfg)
                if cfg["turn_state"] == "results_ready":
                    cfg["turn_state"] = "open"; _save_config(cfg)
                turn_num = cfg["current_turn"]
                team_id = team.get("team_id", "") if isinstance(team, dict) else ""
                upload_time = time.strftime("%Y-%m-%d %H:%M:%S")
                _save_upload(turn_num, mid, {
                    "manager_id" : mid,
                    "manager_name": mgrs[mid]["manager_name"],
                    "team_id" : team_id,
                    "team" : team,
                    "uploaded_at" : upload_time,
                })
                mgrs[mid]["last_upload_timestamp"] = upload_time
                _save_managers(mgrs)
            self.send_json({"success":True,"turn":turn_num,
                            "message":f"Team uploaded for turn {turn_num}."}); return

        if path == "/api/team/withdraw":
            # Remove a team's upload from the current turn and from the
            # manager's team_ids registry. Called when a client replaces a team
            # so the old team stops being auto-carried by the server.
            mid     = (b.get("manager_id") or "").strip()
            pw      = (b.get("password")   or "").strip()
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
                    os.remove(fpath)
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
            rerun = b.get("rerun_turn")
            self.send_json(_run_turn(b.get("host_password",""),
                                     rerun_turn=int(rerun) if rerun else None)); return

        if path == "/api/team/get_my_team":
            mid = (b.get("manager_id") or "").strip()
            pw  = (b.get("password")   or "").strip()
            team_id = b.get("team_id") # Optional: if manager has multiple teams, specify which one
            if not all([mid, pw]):
                self.send_json({"success":False,"error":"manager_id and password required."}); return
            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs:
                    self.send_json({"success":False,"error":"Manager not found. Register first."}); return
                if not _check_mgr_pw(mgrs[mid], pw):
                    self.send_json({"success":False,"error":"Wrong password."}); return

                from save import load_team
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

                self.send_json({"success":True,"teams":filtered_teams}); return

        if path == "/api/arena/reset":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password","")):
                self.send_json({"success":False,"error":"Not authorised."}); return
            import shutil
            for entry in os.listdir(LEAGUE_DIR):
                full = os.path.join(LEAGUE_DIR, entry)
                if entry.startswith("turn_") and os.path.isdir(full):
                    shutil.rmtree(full)
            for fname in ("ai_teams.json", "managers.json", "standings.json",
                          "scout_narratives.json", "scouting.json"):
                fpath = os.path.join(LEAGUE_DIR, fname)
                if os.path.exists(fpath):
                    os.remove(fpath)

            # The live scouting store is actually saves/scouting.json, so clear
            # that file too; otherwise old turn-1 selections survive a reset and
            # reappear when current_turn is reset back to 1.
            from save import TEAMS_DIR, GRAVEYARD_DIR, SCOUTING_FILE, save_champion_state
            for fpath in (SCOUTING_FILE,):
                if os.path.exists(fpath):
                    os.remove(fpath)

            # Clean up global teams, graveyard and reset champion state
            if os.path.exists(TEAMS_DIR):
                for f in os.listdir(TEAMS_DIR):
                    if f.startswith("team_") and f.endswith(".json"):
                        try: os.remove(os.path.join(TEAMS_DIR, f))
                        except: pass
            if os.path.exists(GRAVEYARD_DIR):
                for f in os.listdir(GRAVEYARD_DIR):
                    try: os.remove(os.path.join(GRAVEYARD_DIR, f))
                    except: pass
            try:
                save_champion_state({})
            except Exception:
                pass

            cfg["current_turn"] = 1; cfg["turn_state"] = "open"; cfg["fight_counter"] = 0
            cfg["schedule_last_run_at"] = ""
            cfg["schedule_last_run_turn"] = 0
            cfg["schedule_last_run_result"] = ""
            for _sl in cfg.get("schedule_slots", []):
                _sl["last_run_at"] = ""; _sl["last_run_turn"] = 0; _sl["last_run_result"] = ""
            cfg["reset_count"] = cfg.get("reset_count", 0) + 1
            _save_config(cfg)
            self.send_json({"success":True,
                            "message":"League fully reset to turn 1. All manager registrations and standings cleared."}); return

        if path == "/api/admin/update":
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password","")):
                self.send_json({"success":False,"error":"Not authorised."}, 401); return
            for bool_key in ("show_favorite_weapon", "show_luck_factor",
                             "show_max_hp", "ai_teams_enabled", "schedule_enabled"):
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
            _save_config(cfg)
            global _turn_progress
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
            self.send_json({
                "success": True,
                "is_local_backend": True,
                "server_url": f"http://localhost:{args.port}"
            }); return

        if path == "/api/local/read":
            q = self.qs()
            fpath = _safe_path(q.get("path"))
            if not fpath or not os.path.exists(fpath):
                self.send_json({"success": False, "error": "File not found"}, 404); return
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                if fpath.endswith(".json"):
                    self.send_json({"success": True, "data": json.loads(content)})
                else:
                    self.send_json({"success": True, "text": content})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500); return
            return

        if path == "/api/local/write":
            fpath = _safe_path(b.get("path"))
            if not fpath:
                self.send_json({"success": False, "error": "Invalid path"}, 400); return
            try:
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, "w", encoding="utf-8") as f:
                    if "data" in b:
                        json.dump(b["data"], f, indent=2)
                    else:
                        f.write(b.get("text", ""))
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500); return
            return

        if path == "/api/local/delete":
            fpath = _safe_path(b.get("path"))
            if fpath and os.path.exists(fpath):
                try: os.remove(fpath)
                except: pass
            self.send_json({"success": True}); return

        if path == "/api/local/list":
            q = self.qs()
            dpath = _safe_path(q.get("path"))
            if not dpath or not os.path.isdir(dpath):
                self.send_json({"success": True, "files": []}); return
            files = [f for f in os.listdir(dpath) if os.path.isfile(os.path.join(dpath, f))]
            self.send_json({"success": True, "files": sorted(files)}); return

        # ==================== DELETE MANAGER (FIXED) ====================
        if path == "/api/admin/delete_manager":
            # Load cfg FIRST so it's defined before the check
            cfg = _load_config()
            if not _check_host_pw(cfg, b.get("host_password","")):
                self.send_json({"success":False,"error":"Not authorised."}, 401); return

            mid = (b.get("manager_id") or "").strip()
            if not mid:
                self.send_json({"success":False,"error":"manager_id required."}); return

            with _lock:
                mgrs = _load_managers()
                if mid not in mgrs:
                    self.send_json({"success":False,"error":"Manager not found."}); return

                manager_name = mgrs[mid]["manager_name"]

                # Delete the manager
                del mgrs[mid]
                _save_managers(mgrs)

                # Clean up current turn files
                turn_num = cfg["current_turn"]
                td = _turn_dir(turn_num)
                if os.path.exists(td):
                    for fname in list(os.listdir(td)):
                        if fname.startswith(f"upload_{mid}_") or fname.startswith(f"result_{mid}_"):
                            try:
                                os.remove(os.path.join(td, fname))
                            except Exception:
                                pass

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
            mid = (b.get("manager_id") or "").strip()
            mname = ""
            if mid:
                managers = _load_managers()
                if mid not in managers:
                    self.send_json({"success": False, "error": "Manager not found."}); return
                mname = managers[mid]["manager_name"]
            cfg["admin_debug_manager_id"] = mid
            _save_config(cfg)
            self.send_json({"success": True, "manager_name": mname}); return

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

    _ensure_dirs()
    cfg  = _load_config()
    salt = cfg.get("host_password_salt") or secrets.token_hex(16)
    cfg["host_password_salt"] = salt
    cfg["host_password_hash"] = _hash_pw(args.host_password, salt)
    _save_config(cfg)

    # Use a threading server so GET requests (results, status, etc.) are handled
    # concurrently while a turn is running — prevents 10053 socket abort on Windows
    class ThreadedLeagueServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True   # threads die with the server process

    server = ThreadedLeagueServer(("0.0.0.0", args.port), LeagueHandler)
    _global_server = server
    url    = f"http://localhost:{args.port}"

    print()
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║     BLOODSPIRE LEAGUE SERVER                 ║")
    print("  ╚══════════════════════════════════════════════╝")
    print(f"\n  Admin panel :  {url}/admin")
    print(f"  Player URL  :  http://YOUR_LAN_IP:{args.port}")
    print(f"  Current turn:  {cfg['current_turn']}")
    print(f"\n  ⚠  Share your LAN/public IP, not 'localhost', with other players.")
    print(f"  ⚠  Forward port {args.port} on your router for internet play.\n")

    threading.Timer(0.8, lambda: webbrowser.open(f"{url}/admin")).start()

    # ── Auto-scheduler thread ──────────────────────────────────────────────
    # Checks every minute whether a scheduled turn should fire.
    _DAYS = ("Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday")

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
                    break  # one turn per check — don't fire two slots at once
            except Exception as _se:
                print(f"  [scheduler] Error: {_se}")

    threading.Thread(target=_scheduler, daemon=True, name="bp-scheduler").start()
    # ──────────────────────────────────────────────────────────────────────

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  League server stopped.")

if __name__ == "__main__":
    main()
