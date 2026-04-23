#!/usr/bin/env python3
# =============================================================================
# gui_server.py — BLOODSPIRE Client HTTP Server
# =============================================================================
# Run: python gui_server.py
# Opens http://localhost:8765 in your default browser automatically.
#
# Serves Bloodspire_client.html and provides a REST JSON API for all game data.
# =============================================================================

import http.server
import json
import os
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from accounts  import create_account, login, add_team, get_account, MAX_TEAMS
from warrior   import (
    Warrior, Strategy, generate_base_stats,
    ATTRIBUTES, FIGHTING_STYLES, TRIGGERS, AIM_DEFENSE_POINTS,
    NON_WEAPON_SKILLS, WEAPON_SKILLS, SKILL_LEVEL_NAMES,
)
from team      import Team, TEAM_SIZE
from save      import save_team, load_team, next_team_id, increment_turn, current_turn, load_fight_log
from weapons   import WEAPONS
from armor     import armor_selection_menu, helm_selection_menu
from races     import list_playable_races

PORT     = 8765
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE= os.path.join(BASE_DIR, "Bloodspire_client.html")
LEAGUE_SETTINGS_FILE = os.path.join(BASE_DIR, "saves", "league_settings.json")

# Global server reference for graceful shutdown from request handlers
_global_server = None

import time as _time


def _exit_and_close_terminal():
    """Shut down Python and close the console window (Windows)."""
    import sys, ctypes
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    except Exception:
        pass
    sys.exit(0)


# ---------------------------------------------------------------------------
# JSON CONVERSION HELPERS
# ---------------------------------------------------------------------------

def warrior_to_json(w: Warrior) -> dict:
    """Serialize a warrior to a JSON-compatible dict for the client."""
    d = w.to_dict()
    d["max_hp"]      = w.max_hp
    d["height_in"]   = w.height_in
    d["weight_lbs"]  = w.weight_lbs
    d["kills"]       = w.kills
    d["monster_kills"] = getattr(w, "monster_kills", 0)
    d["luck"]        = w.luck
    d["is_dead"]     = getattr(w, "is_dead",   False)
    d["ascended_to_monster"] = getattr(w, "ascended_to_monster", False)
    d["killed_by"]   = getattr(w, "killed_by", "")
    d["streak"]      = getattr(w, "streak", 0)
    d["turns_active"]= getattr(w, "turns_active", 0)
    d["popularity"]  = getattr(w, "popularity", 0)
    d["want_monster_fight"] = getattr(w, "want_monster_fight", False)
    d["want_retire"]        = getattr(w, "want_retire", False)
    d["avoid_warriors"]     = getattr(w, "avoid_warriors", [])

    # Format height as ft'in"
    ft  = w.height_in // 12
    ins = w.height_in % 12
    d["height_str"]  = f"{ft}' {ins}\""

    # Build skills list (only trained skills)
    skill_lines = []
    for skill, level in sorted(w.skills.items(), key=lambda x: -x[1]):
        if level > 0:
            desc = SKILL_LEVEL_NAMES.get(level, "Unknown")
            name = skill.replace("_", " ").title()
            skill_lines.append(f"Has {desc.lower()} ({level}) in {name}")
    d["skills_text"] = skill_lines

    # Build injury list
    injury_lines = []
    from warrior import INJURY_DESCRIPTIONS, INJURY_LOCATIONS
    for loc in INJURY_LOCATIONS:
        lvl = w.injuries.get(loc)
        if lvl > 0:
            desc     = INJURY_DESCRIPTIONS.get(lvl, "Unknown")
            loc_name = loc.replace("_", " ").title()
            injury_lines.append(f"Has a {desc.lower()} ({lvl}) injury to the {loc_name}")
    d["injuries_text"] = injury_lines

    # Include injury raw levels too
    d["injury_levels"] = w.injuries.to_dict()

    # Stat display with initial values
    d["stat_display"] = {}
    for attr in ATTRIBUTES:
        current = getattr(w, attr)
        if w.initial_stats and attr in w.initial_stats:
            initial = w.initial_stats[attr]
            d["stat_display"][attr] = f"{current} ({initial})" if current != initial else str(current)
        else:
            d["stat_display"][attr] = str(current)

    return d


def team_to_json(team: Team) -> dict:
    """Serialize a team to JSON for the client."""
    total_w = total_l = total_k = 0

    # Active warriors
    warriors = []
    for w in team.warriors:
        if w is None:
            warriors.append(None)
        else:
            warriors.append(warrior_to_json(w))
            total_w += w.wins
            total_l += w.losses
            total_k += w.kills

    # Archived (dead/replaced) warriors — record is cumulative across all who ever served
    for aw in getattr(team, "archived_warriors", []):
        if not aw: continue
        total_w += aw.get("wins",   0) if isinstance(aw, dict) else getattr(aw, "wins",   0)
        total_l += aw.get("losses", 0) if isinstance(aw, dict) else getattr(aw, "losses", 0)
        total_k += aw.get("kills",  0) if isinstance(aw, dict) else getattr(aw, "kills",  0)

    return {
        "team_id"              : team.team_id,
        "team_name"            : team.team_name,
        "manager_name"         : team.manager_name,
        "record"               : f"{total_w}-{total_l}-{total_k}",  # W-L-K
        "warriors"             : warriors,
        "archived_warriors"    : getattr(team, "archived_warriors", []),
        "pending_replacements" : {str(k): v for k, v in getattr(team, "pending_replacements", {}).items()},
        "turn_history"         : getattr(team, "turn_history", []),
        "challenges"           : dict(getattr(team, "challenges", {})),
        "blood_challenges"     : getattr(team, "blood_challenges", []),
        "avoid_managers"       : getattr(team, "avoid_managers", []),
    }


# ---------------------------------------------------------------------------
# REQUEST HANDLER
# ---------------------------------------------------------------------------

class BloodspireHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # Suppress console noise

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
        _exit_and_close_terminal()

    # --- Helpers ---

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, filepath: str, content_type: str = "text/html; charset=utf-8"):
        if not os.path.exists(filepath):
            self.send_response(404)
            self.end_headers()
            return
        with open(filepath, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def qs(self) -> dict:
        if "?" in self.path:
            return dict(urllib.parse.parse_qsl(self.path.split("?", 1)[1]))
        return {}

    def path_only(self) -> str:
        return self.path.split("?")[0]

    def query_params(self) -> dict:
        if "?" not in self.path:
            return {}
        from urllib.parse import parse_qsl
        return dict(parse_qsl(self.path.split("?", 1)[1]))

    # --- CORS preflight ---

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # --- GET ---

    def do_GET(self):
        p = self.path_only()

        # Serve the HTML client
        if p in ("/", "/index.html"):
            self.send_file(HTML_FILE)
            return

        # Serve static assets (images, etc.)
        if p.startswith("/static/"):
            fname = p[len("/static/"):]
            fpath = os.path.join(BASE_DIR, fname)
            ext = os.path.splitext(fname)[1].lower()
            ctype = {".png": "image/png", ".jpg": "image/jpeg",
                     ".jpeg": "image/jpeg", ".gif": "image/gif",
                     ".svg": "image/svg+xml"}.get(ext, "application/octet-stream")
            self.send_file(fpath, ctype)
            return

        # --- API routes ---

        if p == "/api/game_data":
            # All static dropdown data the client needs
            self.send_json({
                "weapons"         : sorted([w.display for w in WEAPONS.values()]),
                "armor"           : armor_selection_menu() + ["None"],
                "helms"           : helm_selection_menu() + ["None"],
                "triggers"        : TRIGGERS,
                "styles"          : FIGHTING_STYLES,
                "aim_points"      : AIM_DEFENSE_POINTS,
                "races"           : list_playable_races(),
                "genders"         : ["Male","Female"],
                "attributes"      : ATTRIBUTES,
                "non_weapon_skills": NON_WEAPON_SKILLS,
                "weapon_skills"   : sorted(WEAPON_SKILLS),
                "train_skills"    : sorted(
                ["Strength","Dexterity","Constitution","Intelligence","Presence"] +
                [s.replace("_"," ").title() for s in NON_WEAPON_SKILLS] +
                [w.display for w in WEAPONS.values()]
            ),
            })

        elif p == "/api/rollup":
            # Generate 5 fresh base stat sets (for new team creation)
            rolls = [generate_base_stats() for _ in range(TEAM_SIZE)]
            self.send_json({"rolls": rolls})

        elif p == "/api/rollup_single":
            # Generate one fresh base stat set (for replacement warrior)
            self.send_json({"base": generate_base_stats()})

        elif p == "/api/account":
            q   = self.qs()
            acc = get_account((q.get("id") or "").strip())
            if acc:
                self.send_json({"success": True, "account": acc})
            else:
                self.send_json({"success": False, "error": "Account not found."}, 404)

        elif p == "/api/team":
            q = self.qs()
            try:
                from warrior import assign_favorite_weapon as _afw
                team = load_team(int(q.get("id", 0)))
                changed = False
                for _w in team.warriors:
                    if _w and not getattr(_w, "favorite_weapon", ""):
                        _afw(_w)
                        changed = True
                if changed:
                    save_team(team)
                self.send_json({"success": True, "team": team_to_json(team)})
            except FileNotFoundError:
                self.send_json({"success": False, "error": "Team not found."}, 404)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)

        elif p == "/api/fight/narrative":
            q = self.qs()
            try:
                text = load_fight_log(int(q.get("id", 0)))
                self.send_json({"success": True, "narrative": text})
            except FileNotFoundError:
                self.send_json({"success": False, "error": "Fight log not found."}, 404)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)

        elif p == "/api/league/settings":
            self.send_json(_get_league_settings())

        elif p == "/api/league/status":
            self.send_json(_league_proxy_get("/league/status", self.qs()))

        elif p == "/api/league/standings":
            self.send_json(_league_proxy_get("/league/standings", self.qs()))

        elif p == "/api/league/results":
            self.send_json(_league_proxy_get("/league/results", self.qs()))

        elif p == "/api/league/narrative":
            self.send_json(_league_proxy_get("/league/narrative", self.qs()))

        elif p == "/api/league/admin":
            self.send_json(_league_proxy_get("/league/admin", self.qs()))

        elif p == "/api/league_settings":
            # Return saved league server URL and manager credentials (per-manager)
            q = self.qs()
            manager_name = q.get("manager_name", "").strip().upper()
            self.send_json(_get_league_settings_for(manager_name))

        elif p == "/api/session":
            from save import load_session
            import base64 as _b64
            sess = load_session()
            pw_stored = sess.pop("pw_stored", "")
            if pw_stored:
                try:    sess["password"] = _b64.b64decode(pw_stored.encode()).decode()
                except: sess["password"] = ""
            self.send_json(sess)

        elif p == "/api/full_reset":
            # Hard reset — wipes everything except accounts.json.
            # Hit this URL in a browser: http://localhost:8765/api/full_reset?confirm=YES
            q = self.query_params()
            if q.get("confirm") != "YES":
                self.send_json({
                    "success": False,
                    "error"  : "Add ?confirm=YES to the URL to execute the reset.",
                    "url"    : "/api/full_reset?confirm=YES",
                })
                return
            self.send_json(_full_reset())

        elif p == "/api/newsletters":
            from save import list_newsletters
            self.send_json({"turns": list_newsletters()})

        elif p == "/api/newsletter":
            q = self.query_params()
            turn_num = int(q.get("turn", 0))
            if not turn_num:
                self.send_json({"success": False, "error": "turn required"}, 400); return
            from save import load_newsletter
            text = load_newsletter(turn_num)
            if text is None:
                self.send_json({"success": False, "error": f"Newsletter for turn {turn_num} not found"}, 404); return
            self.send_json({"success": True, "turn": turn_num, "text": text})

        elif p == "/api/newsletter/voice":
            from save import load_newsletter_voice
            self.send_json({"voice": load_newsletter_voice()})

        elif p == "/api/league/latest_newsletter":
            # Fetch the most recent newsletter from league server (for new users)
            self.send_json(_fetch_latest_league_newsletter())

        elif p == "/api/scout/status":
            from save import get_manager_scouting, current_turn
            q          = self.qs()
            manager_id = (q.get("manager_id") or "").strip()
            turn       = current_turn()
            selections = get_manager_scouting(manager_id, turn)
            self.send_json({"success": True, "turn": turn, "selections": selections,
                            "slots_used": len(selections), "slots_left": 3 - len(selections)})

        elif p == "/api/challenge/targets":
            from save import load_all_teams
            from accounts import get_account
            from ai_league_teams import get_or_create_ai_teams
            q          = self.qs()
            manager_id = (q.get("manager_id") or "").strip()
            team_id    = int(q.get("team_id", 0))
            acc        = get_account(manager_id)
            own_ids    = set(acc.get("team_ids", [])) if acc else set()
            if team_id:
                own_ids.add(team_id)
            _NPC = {"The Monsters", "The Peasants"}
            warriors = []

            # Player teams — use Team objects (already fully parsed)
            for t in load_all_teams():
                if t.team_id in own_ids or t.team_name in _NPC:
                    continue
                for w in t.active_warriors:
                    warriors.append({
                        "name"         : w.name,
                        "team_name"    : t.team_name,
                        "manager_name" : t.manager_name,
                        "race"         : w.race.name if hasattr(w.race, "name") else str(w.race),
                        "total_fights" : w.total_fights,
                        "wins"         : w.wins,
                        "losses"       : w.losses,
                        "kills"        : w.kills,
                    })

            # AI teams — read raw dicts to avoid any Warrior.from_dict failures
            for at in get_or_create_ai_teams():
                team_name = at.get("team_name", "")
                if team_name in _NPC:
                    continue
                mgr_name = at.get("manager_name", "")
                for wd in at.get("warriors", []):
                    if not wd or wd.get("is_dead"):
                        continue
                    warriors.append({
                        "name"         : wd.get("name", "Unknown"),
                        "team_name"    : team_name,
                        "manager_name" : mgr_name,
                        "race"         : wd.get("race", "Human"),
                        "total_fights" : wd.get("total_fights", 0),
                        "wins"         : wd.get("wins", 0),
                        "losses"       : wd.get("losses", 0),
                        "kills"        : wd.get("kills", 0),
                    })

            warriors.sort(key=lambda x: x["total_fights"])
            self.send_json({"success": True, "warriors": warriors})

        elif p == "/api/scout/targets":
            from save import load_all_teams, current_turn
            from accounts import get_account
            from team import Team
            from ai_league_teams import get_or_create_ai_teams
            q          = self.qs()
            manager_id = (q.get("manager_id") or "").strip()
            acc        = get_account(manager_id)
            own_ids    = set(acc.get("team_ids", [])) if acc else set()
            warriors   = []
            _NPC       = {"The Monsters", "The Peasants"}

            def _add_team_warriors(t):
                for w in t.active_warriors:
                    fh      = w.fight_history or []
                    last_fid= fh[-1].get("fight_id") if fh else None
                    warriors.append({
                        "name"            : w.name,
                        "team_name"       : t.team_name,
                        "team_id"         : t.team_id,
                        "race"            : w.race.name if hasattr(w.race, "name") else str(w.race),
                        "gender"          : w.gender,
                        "wins"            : w.wins,
                        "losses"          : w.losses,
                        "kills"           : w.kills,
                        "total_fights"    : w.total_fights,
                        "armor"           : w.armor or "None",
                        "helm"            : w.helm or "None",
                        "primary_weapon"  : w.primary_weapon or "Open Hand",
                        "secondary_weapon": w.secondary_weapon or "Open Hand",
                        "backup_weapon"   : w.backup_weapon or "None",
                        "last_fight_id"   : last_fid,
                    })

            # Player teams (excluding own)
            for t in load_all_teams():
                if t.team_id in own_ids or t.team_name in _NPC:
                    continue
                _add_team_warriors(t)

            # AI league teams
            for at in get_or_create_ai_teams():
                try:
                    t = Team.from_dict(at)
                    if t.team_name not in _NPC:
                        _add_team_warriors(t)
                except Exception:
                    continue

            warriors.sort(key=lambda x: x["name"])
            self.send_json({"success": True, "warriors": warriors})

        elif p == "/api/scout/report":
            from save import load_all_teams, load_fight_log
            from accounts import get_account
            from team import Team
            from ai_league_teams import get_or_create_ai_teams
            q            = self.qs()
            warrior_name = q.get("warrior_name", "")
            manager_id   = (q.get("manager_id") or "").strip()
            acc          = get_account(manager_id)
            own_ids      = set(acc.get("team_ids", [])) if acc else set()
            target_w     = None
            target_t     = None
            _NPC         = {"The Monsters", "The Peasants"}
            # Search player teams first
            for t in load_all_teams():
                if t.team_id in own_ids or t.team_name in _NPC:
                    continue
                for w in t.active_warriors:
                    if w.name.lower() == warrior_name.lower():
                        target_w = w; target_t = t; break
                if target_w: break
            # Then search AI league teams
            if not target_w:
                for at in get_or_create_ai_teams():
                    try:
                        t = Team.from_dict(at)
                        if t.team_name in _NPC: continue
                        for w in t.active_warriors:
                            if w.name.lower() == warrior_name.lower():
                                target_w = w; target_t = t; break
                    except Exception:
                        continue
                    if target_w: break
            if not target_w:
                self.send_json({"success": False, "error": f"Warrior '{warrior_name}' not found"}); return
            fh            = target_w.fight_history or []
            last_fight_entry = next(
                (e for e in reversed(fh) if e.get("fight_id") or e.get("opponent_name")),
                None
            )
            from scout_report import generate_scout_report
            scout_text = generate_scout_report(target_w, last_fight_entry, target_t.team_name)
            self.send_json({"success": True, "report": {
                "warrior_name"    : target_w.name,
                "team_name"       : target_t.team_name,
                "race"            : target_w.race.name if hasattr(target_w.race, "name") else str(target_w.race),
                "gender"          : target_w.gender,
                "wins"            : target_w.wins,
                "losses"          : target_w.losses,
                "kills"           : target_w.kills,
                "total_fights"    : target_w.total_fights,
                "armor"           : target_w.armor or "None",
                "helm"            : target_w.helm or "None",
                "primary_weapon"  : target_w.primary_weapon or "Open Hand",
                "secondary_weapon": target_w.secondary_weapon or "Open Hand",
                "backup_weapon"   : target_w.backup_weapon or "None",
                "scout_report"    : scout_text,
            }})

        else:
            self.send_json({"error": "Not found."}, 404)

    # --- POST ---

    def do_POST(self):
        p    = self.path_only()
        body = self.read_body()

        if p == "/api/account/create":
            result = create_account(
                body.get("manager_name", ""),
                body.get("email", ""),
                body.get("password", ""),
            )
            self.send_json(result)

        elif p == "/api/account/login":
            result = login(
                body.get("manager_name", ""),
                body.get("password", ""),
            )
            if result.get("success"):
                from save import save_session
                save_session(body.get("manager_name", ""),
                             body.get("password", ""))
            self.send_json(result)

        elif p == "/api/team/create":
            self.send_json(_create_team(body))

        elif p == "/api/turn/run":
            self.send_json(_run_turn_for_team(body))

        elif p == "/api/league/settings":
            self.send_json(_save_league_settings(body))

        elif p == "/api/league/register":
            self.send_json(_league_proxy_post("/league/register", body))

        elif p == "/api/league/upload":
            self.send_json(_do_league_upload(body))

        elif p == "/api/league/run_turn":
            self.send_json(_league_proxy_post("/league/run_turn", body))

        elif p == "/api/heartbeat":
            self.send_json({"ok": True})

        elif p == "/api/shutdown":
            # Browser closed or user requested shutdown
            self.send_json({"success": True, "message": "Shutting down..."})
            # Schedule shutdown for after response is sent
            threading.Timer(0.5, self._shutdown_server).start()

        elif p == "/api/league/get_results":
            self.send_json(_do_league_get_results(body))

        elif p == "/api/league_settings":
            # Save league server URL and manager credentials (per-manager)
            self.send_json(_save_league_settings_for(body))

        elif p == "/api/warrior/replace":
            # Confirm a replacement warrior for a dead slot
            self.send_json(_confirm_replacement(body))

        elif p == "/api/arena/reset":
            from save import reset_arena_complete
            result = reset_arena_complete()
            self.send_json(result)

        elif p == "/api/team/challenge":
            team_id      = int(body.get("team_id", 0))
            warrior_name = body.get("warrior_name", "")
            target_name  = body.get("target_name", "")
            action       = body.get("action", "add")
            if not warrior_name or not target_name:
                self.send_json({"success": False, "error": "warrior_name and target_name required"}); return
            team = load_team(team_id)
            if action == "add":
                if warrior_name not in team.challenges:
                    team.challenges[warrior_name] = []
                existing = team.challenges[warrior_name]
                if len(existing) >= 3:
                    self.send_json({"success": False, "error": "Already 3 challenges queued for this warrior."}); return
                if target_name not in existing:
                    existing.append(target_name)
            elif action == "remove":
                if warrior_name in team.challenges:
                    try: team.challenges[warrior_name].remove(target_name)
                    except ValueError: pass
                    if not team.challenges[warrior_name]:
                        del team.challenges[warrior_name]
            save_team(team)
            self.send_json({"success": True, "challenges": dict(team.challenges)})

        elif p == "/api/team/blood_challenge":
            # Set or update the selected challenger for a blood challenge
            team_id           = int(body.get("team_id", 0))
            target_name       = body.get("target_name", "")  # killer's name
            challenger_name   = body.get("challenger_name", "")  # selected warrior
            if not target_name:
                self.send_json({"success": False, "error": "target_name required"}); return
            team = load_team(team_id)
            if not challenger_name:
                self.send_json({"success": False, "error": "challenger_name required"}); return
            success = team.set_blood_challenge_challenger(target_name, challenger_name)
            if success:
                save_team(team)
                self.send_json({"success": True, "blood_challenges": team.blood_challenges})
            else:
                self.send_json({"success": False, "error": "Warrior not found or blood challenge not available"})

        elif p == "/api/warrior/avoid_warrior":
            # Add or remove a specific warrior to avoid for a specific warrior
            team_id           = int(body.get("team_id", 0))
            warrior_name      = body.get("warrior_name", "")  # warrior doing the avoiding
            avoid_warrior_name = body.get("avoid_warrior_name", "")  # warrior to avoid
            action            = body.get("action", "add")  # "add" or "remove"
            if not warrior_name or not avoid_warrior_name:
                self.send_json({"success": False, "error": "warrior_name and avoid_warrior_name required"}); return
            team = load_team(team_id)
            warrior = team.warrior_by_name(warrior_name)
            if not warrior:
                self.send_json({"success": False, "error": "Warrior not found"}); return
            if action == "add":
                success = warrior.add_avoid_warrior(avoid_warrior_name)
                if not success:
                    self.send_json({"success": False, "error": "Cannot add: list full or already exists"}); return
            elif action == "remove":
                success = warrior.remove_avoid_warrior(avoid_warrior_name)
                if not success:
                    self.send_json({"success": False, "error": "Warrior not in avoid list"}); return
            else:
                self.send_json({"success": False, "error": "Invalid action"}); return
            save_team(team)
            self.send_json({"success": True, "avoid_warriors": warrior.avoid_warriors})

        elif p == "/api/team/avoid_manager":
            # Add or remove a manager to avoid at the team level
            team_id      = int(body.get("team_id", 0))
            manager_name = body.get("manager_name", "")  # manager name to avoid
            action       = body.get("action", "add")  # "add" or "remove"
            if not manager_name:
                self.send_json({"success": False, "error": "manager_name required"}); return
            team = load_team(team_id)
            if action == "add":
                success = team.add_avoid_manager(manager_name)
                if not success:
                    self.send_json({"success": False, "error": "Cannot add: list full or already exists"}); return
            elif action == "remove":
                success = team.remove_avoid_manager(manager_name)
                if not success:
                    self.send_json({"success": False, "error": "Manager not in avoid list"}); return
            else:
                self.send_json({"success": False, "error": "Invalid action"}); return
            save_team(team)
            self.send_json({"success": True, "avoid_managers": team.avoid_managers})

        elif p == "/api/scout/select":
            from save import add_manager_scouting, get_manager_scouting, current_turn
            manager_id   = (body.get("manager_id") or "").strip()
            warrior_name = body.get("warrior_name", "")
            team_name    = body.get("team_name", "")
            team_id      = int(body.get("team_id", 0))
            turn         = current_turn()
            
            success, error = add_manager_scouting(manager_id, turn, warrior_name, team_name, team_id, confirmed=True)
            if not success:
                self.send_json({"success": False, "error": error})
                return
            
            selections = get_manager_scouting(manager_id, turn)
            self.send_json({
                "success": True,
                "selections": selections,
                "slots_used": len(selections),
                "slots_left": 3 - len(selections)
            })

        elif p == "/api/scout/remove":
            from save import remove_manager_scouting, get_manager_scouting, current_turn
            manager_id   = (body.get("manager_id") or "").strip()
            warrior_name = body.get("warrior_name", "")
            turn         = current_turn()
            
            success, error = remove_manager_scouting(manager_id, turn, warrior_name)
            if not success:
                self.send_json({"success": False, "error": error})
                return
            
            selections = get_manager_scouting(manager_id, turn)
            self.send_json({
                "success": True,
                "selections": selections,
                "slots_used": len(selections),
                "slots_left": 3 - len(selections)
            })

        elif p == "/api/scout/confirm":
            from save import confirm_manager_scouting, get_manager_scouting, current_turn
            manager_id   = (body.get("manager_id") or "").strip()
            warrior_name = body.get("warrior_name", "")
            turn         = current_turn()
            
            success, error = confirm_manager_scouting(manager_id, turn, warrior_name)
            if not success:
                self.send_json({"success": False, "error": error})
                return
            
            selections = get_manager_scouting(manager_id, turn)
            self.send_json({
                "success": True,
                "selections": selections,
                "slots_used": len(selections),
                "slots_left": 3 - len(selections)
            })

        elif p == "/api/team/run_next_turn":
            from accounts import set_run_next_turn
            ok, err = set_run_next_turn(
                (body.get("manager_id") or "").strip(),
                int(body.get("team_id", 0)),
                bool(body.get("value", True)),
            )
            self.send_json({"success": ok, "error": err})

        elif p == "/api/team/remove":
            from accounts import remove_team
            from save import archive_replaced_team
            manager_id = (body.get("manager_id") or "").strip()
            team_id    = int(body.get("team_id", 0))
            try:
                team = load_team(team_id)
                archive_replaced_team(team, reason="removed")
            except Exception:
                pass
            ok, err = remove_team(manager_id, team_id)
            self.send_json({"success": ok, "error": err})

        elif p == "/api/team/replace":
            from save import archive_replaced_team, next_team_id
            manager_id  = (body.get("manager_id") or "").strip()
            old_team_id = int(body.get("old_team_id", 0))
            try:
                old_team = load_team(old_team_id)
                for w in old_team.warriors:
                    if not w: continue
                    snap = w.to_dict()
                    snap["archived_killed_by"] = "Team Replaced"
                    snap["archived_turns"]     = getattr(w, "turns_active", 0)
                    old_team.archived_warriors.append(snap)
                archive_replaced_team(old_team, reason="replaced")
                save_team(old_team)
            except Exception as e:
                print(f"  WARNING: could not archive old team: {e}")
            new_tid = next_team_id()
            self.send_json({"success": True, "new_team_id": new_tid,
                            "old_team_id": old_team_id, "manager_id": manager_id})

        elif p == "/api/account/swap_team":
            from accounts import replace_team
            manager_id  = (body.get("manager_id") or "").strip()
            old_team_id = int(body.get("old_team_id", 0))
            new_team_id = int(body.get("new_team_id", 0))
            ok, err = replace_team(manager_id, old_team_id, new_team_id)
            self.send_json({"success": ok, "error": err})

        elif p == "/api/run_all_turns":
            from accounts        import get_teams_to_run
            from ai_league_teams import get_or_create_ai_teams, evolve_ai_teams
            from matchmaking     import run_turn as _do_run_turn
            from save            import load_champion_state, load_all_teams
            from team            import Team
            manager_id = (body.get("manager_id") or "").strip()
            team_ids   = [int(x) for x in body.get("team_ids", [])]
            to_run     = get_teams_to_run(manager_id, team_ids)
            if not to_run:
                self.send_json({"success": False, "error": "No teams flagged to run."}); return
            ai_teams   = get_or_create_ai_teams()
            champion_state = load_champion_state()
            # Build opponent pool: all AI teams + all player teams not owned by this manager
            own_ids = set(to_run)
            opponent_teams = []
            for at in ai_teams:
                try:
                    opponent_teams.append(Team.from_dict(at))
                except Exception:
                    pass
            for pt in load_all_teams():
                if pt.team_id not in own_ids:
                    opponent_teams.append(pt)
            results        = []
            turn_num       = increment_turn()
            ai_results_agg = {}
            global_used    = set()
            for tid in to_run:
                try:
                    team = load_team(tid)
                    card = _do_run_turn(team, opponent_teams, verbose=False,
                                       champion_state=champion_state,
                                       global_used=global_used)
                    bouts = []
                    for bout in card:
                        pw = bout.player_warrior; r = bout.result
                        if not r: continue
                        pw_won = r.winner and r.winner.name == pw.name
                        bouts.append({
                            "warrior_name"  : pw.name,
                            "opponent_name" : bout.opponent.name,
                            "fight_type"    : bout.fight_type,
                            "result"        : "WIN" if pw_won else "LOSS",
                            "minutes"       : r.minutes_elapsed,
                            "warrior_slain" : r.loser_died and r.loser is pw,
                        })
                        if bout.opponent_team.team_id >= 9000:
                            mid_ai = f"ai_{(bout.opponent_team.team_id - 9000):02d}"
                            ow_won = not pw_won
                            ai_results_agg.setdefault(mid_ai, {"bouts":[],"team":bout.opponent_team.to_dict()})
                            ai_results_agg[mid_ai]["bouts"].append({
                                "result": "WIN" if ow_won else "LOSS",
                                "opponent_slain": r.loser_died and ow_won,
                            })
                    results.append({"team_id": tid, "team_name": team.team_name,
                                    "bouts": bouts, "success": True})
                except Exception as e:
                    results.append({"team_id": tid, "success": False, "error": str(e)})
            if ai_results_agg:
                evolve_ai_teams(ai_teams, ai_results_agg)

            try:
                from ai_league_teams import save_ai_teams as _save_ai_teams
                _ai_chg = _process_scout_fights(
                    manager_id, turn_num, opponent_teams, ai_teams
                )
                if _ai_chg:
                    _save_ai_teams(ai_teams)
            except Exception as _se:
                print(f"  WARNING: scout fight generation failed: {_se}")

            self.send_json({"success": True, "turn_number": turn_num, "results": results})

        elif p == "/api/league/upload_all":
            from accounts import get_teams_to_run
            manager_id = (body.get("manager_id") or "").strip()
            team_ids   = [int(x) for x in body.get("team_ids", [])]
            league_url = body.get("league_url", "")
            league_id  = body.get("league_manager_id", "")
            password   = body.get("password", "")
            to_upload  = get_teams_to_run(manager_id, team_ids)
            if not to_upload:
                self.send_json({"success": False, "error": "No teams flagged to upload."}); return
            import urllib.request as _ur
            uploaded = []; errors = []
            for tid in to_upload:
                try:
                    team    = load_team(tid)
                    slim = _slim_team_for_upload(team_to_json(team))
                    payload = json.dumps({
                        "manager_id": league_id, "password": password,
                        "team": slim,
                    }).encode()
                    req  = _ur.Request(f"{league_url}/api/upload", data=payload,
                                       headers={"Content-Type":"application/json"}, method="POST")
                    resp = json.loads(_ur.urlopen(req, timeout=30).read())
                    if resp.get("success"):
                        uploaded.append({"team_id": tid, "team_name": team.team_name})
                    else:
                        errors.append({"team_id": tid, "error": resp.get("error","?")})
                except Exception as e:
                    errors.append({"team_id": tid, "error": str(e)})
            self.send_json({"success": True, "uploaded": uploaded, "errors": errors})

        elif p == "/api/league/upload_one":
            # Upload a single team to the league server. Used by the client's
            # progress-indicator loop so each team ticks through individually.
            team_id    = int(body.get("team_id", 0))
            league_url = body.get("league_url", "")
            league_id  = body.get("league_manager_id", "")
            password   = body.get("password", "")
            if not team_id:
                self.send_json({"success": False, "error": "team_id required"}); return
            try:
                import urllib.request as _ur
                team = load_team(team_id)
                slim = _slim_team_for_upload(team_to_json(team))
                payload = json.dumps({
                    "manager_id": league_id, "password": password,
                    "team": slim,
                }).encode()
                req  = _ur.Request(f"{league_url}/api/upload", data=payload,
                                   headers={"Content-Type":"application/json"}, method="POST")
                resp = json.loads(_ur.urlopen(req, timeout=30).read())
                if resp.get("success"):
                    self.send_json({"success": True, "team_id": team_id,
                                    "team_name": team.team_name, "turn": resp.get("turn")})
                else:
                    self.send_json({"success": False, "team_id": team_id,
                                    "team_name": team.team_name,
                                    "error": resp.get("error","?")})
            except Exception as e:
                self.send_json({"success": False, "team_id": team_id, "error": str(e)})

        elif p == "/api/session/save":
            from save import save_session
            save_session(body.get("manager_name",""), body.get("password",""))
            self.send_json({"success": True})

        elif p == "/api/newsletter/save":
            # Browser fetched newsletter directly from league server; save it locally
            from save import save_newsletter
            turn = int(body.get("turn", 0))
            text = body.get("text", "")
            if turn and text:
                save_newsletter(turn, text)
                self.send_json({"success": True})
            else:
                self.send_json({"success": False, "error": "turn and text required"})

        elif p == "/api/newsletter/voice":
            voice = body.get("voice", "snide")
            if voice not in ("snide", "neutral"):
                self.send_json({"success": False, "error": "voice must be 'snide' or 'neutral'"}); return
            from save import save_newsletter_voice
            save_newsletter_voice(voice)
            self.send_json({"success": True, "voice": voice})

        elif p == "/api/league/download_all":
            # Fetch results for ALL of the manager's teams from the league server
            # and apply each one to its matching local team.
            self.send_json(_league_download_all(body))

        elif p == "/api/league/check_reset":
            self.send_json(_check_league_reset())

        elif p == "/api/league/acknowledge_reset":
            self.send_json(_acknowledge_league_reset(body))

        elif p == "/api/apply_league_results":
            # Apply results downloaded from the league server to the local team
            self.send_json(_apply_league_results(body))

        else:
            self.send_json({"error": "Not found."}, 404)

    # --- PUT ---

    def do_PUT(self):
        p    = self.path_only()
        body = self.read_body()

        if p == "/api/warrior":
            self.send_json(_update_warrior(body))
        else:
            self.send_json({"error": "Not found."}, 404)


# ---------------------------------------------------------------------------
# SCOUT FIGHTS
# ---------------------------------------------------------------------------

def _process_scout_fights(manager_id: int, turn_num: int,
                           opponent_teams: list, ai_teams: list):
    """
    For each warrior scouted this turn that hasn't fought yet, simulate an
    exhibition fight against a peasant so the scout report has a narrative.

    Returns True if ai_teams were modified.
    """
    import random
    from save            import get_manager_scouting, save_fight_log, current_turn as _ct
    from combat          import run_fight
    from team            import create_peasant_team
    from warrior         import Warrior

    scouted_names = get_manager_scouting(manager_id, turn_num - 1)
    if not scouted_names:
        return False

    ai_changed = False

    for warrior_name in scouted_names:
        # Search AI team dicts first
        found_ai_team = None
        found_ai_idx  = None
        found_ai_w    = None

        for at in ai_teams:
            wlist = at.get("warriors", [])
            for j, wd in enumerate(wlist):
                if wd and wd.get("name", "").lower() == warrior_name.lower():
                    try:
                        found_ai_w   = Warrior.from_dict(wd)
                        found_ai_team = at
                        found_ai_idx  = j
                    except Exception:
                        pass
                    break
            if found_ai_team:
                break

        # Search opponent teams (player teams loaded as Team objects)
        found_team = None
        found_w    = None
        if not found_ai_team:
            for ot in opponent_teams:
                for w in ot.active_warriors:
                    if w.name.lower() == warrior_name.lower():
                        found_team = ot
                        found_w    = w
                        break
                if found_team:
                    break

        if not found_ai_team and not found_team:
            continue

        target_w  = found_ai_w if found_ai_team else found_w
        team_name = found_ai_team["team_name"] if found_ai_team else found_team.team_name
        mgr_name  = found_ai_team.get("manager_name", "Unknown") if found_ai_team \
                    else found_team.manager_name

        if any(e.get("turn") == turn_num and e.get("fight_id")
               for e in (target_w.fight_history or [])):
            continue

        try:
            peasant_team = create_peasant_team(
                target_fight_count=max(1, target_w.total_fights)
            )
            peasants = peasant_team.active_warriors
            if not peasants:
                continue
            opp = random.choice(peasants)

            result = run_fight(
                target_w, opp,
                team_a_name    = team_name,
                team_b_name    = "The Peasants",
                manager_a_name = mgr_name,
                manager_b_name = "The Arena",
            )

            header = (
                f"[Scout Exhibition — {warrior_name} of {team_name}]\n"
                f"[This fight was observed by your scout and recorded for review.]\n\n"
            )
            _, fight_id = save_fight_log(
                header + result.narrative,
                team_name, "The Peasants",
            )

            w_won = result.winner and result.winner.name == target_w.name
            target_w.fight_history.append({
                "turn"          : turn_num,
                "opponent_name" : opp.name,
                "opponent_race" : opp.race.name if hasattr(opp.race, "name") else str(opp.race),
                "opponent_team" : "The Peasants",
                "result"        : "win" if w_won else "loss",
                "minutes"       : result.minutes_elapsed,
                "fight_id"      : fight_id,
                "warrior_slain" : False,
                "opponent_slain": False,
                "scout_fight"   : True,
            })

            if found_ai_team:
                found_ai_team["warriors"][found_ai_idx] = target_w.to_dict()
                ai_changed = True

            print(f"  Scout fight created for {warrior_name} (fight #{fight_id})")

        except Exception as exc:
            print(f"  WARNING: Could not create scout fight for {warrior_name}: {exc}")

    return ai_changed


# ---------------------------------------------------------------------------
# BUSINESS LOGIC
# ---------------------------------------------------------------------------

def _create_team(body: dict) -> dict:
    """Create a new team from the GUI team-creation form data."""
    manager_id   = body.get("manager_id")
    manager_name = body.get("manager_name", "")
    team_name    = body.get("team_name", "").strip()
    warriors_data= body.get("warriors", [])

    if not team_name:
        return {"success": False, "error": "Team name cannot be blank."}
    if len(warriors_data) < TEAM_SIZE:
        return {"success": False, "error": f"Need exactly {TEAM_SIZE} warriors."}

    team = Team(
        team_name    = team_name.upper(),
        manager_name = manager_name,
        team_id      = next_team_id(),
    )

    for wd in warriors_data:
        name = wd.get("name", "").strip()
        if not name:
            return {"success": False, "error": "All warriors must have a name."}
        try:
            import random as _rand
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
            # Store creation stats for the "current (initial)" display
            w.initial_stats = {
                attr: int(wd[attr])
                for attr in ATTRIBUTES
            }
        except Exception as e:
            return {"success": False, "error": f"Warrior '{name}': {e}"}

        team.add_warrior(w)

    save_team(team)

    ok, err = add_team(manager_id, team.team_id)
    if not ok:
        return {"success": False, "error": err}

    return {"success": True, "team_id": team.team_id, "team": team_to_json(team)}


def _update_warrior(body: dict) -> dict:
    """Update a warrior's gear, strategies, or training from the client."""
    try:
        team = load_team(int(body["team_id"]))
        idx  = int(body["warrior_idx"])
        w    = team.warriors[idx]
        if w is None:
            return {"success": False, "error": "Warrior slot is empty."}

        # Fight-option flags (cleared by matchmaking after use)
        if "want_monster_fight" in body:
            w.want_monster_fight = bool(body["want_monster_fight"])
        if "want_retire" in body:
            w.want_retire = bool(body["want_retire"])

        # Equipment
        for field in ["armor","helm","primary_weapon","secondary_weapon","backup_weapon","blood_cry"]:
            if field in body:
                val = body[field]
                if val == "None":
                    val = None
                setattr(w, field, val)

        # Training queue
        if "trains" in body:
            raw = body["trains"]
            w.trains = [t.lower().replace(" ","_") for t in raw if t and t != "—"][:3]

        # Strategies
        if "strategies" in body:
            w.strategies = []
            for sd in body["strategies"]:
                if sd.get("trigger"):
                    w.strategies.append(Strategy(
                        trigger       = sd["trigger"],
                        style         = sd.get("style", "Strike"),
                        activity      = int(sd.get("activity", 5)),
                        aim_point     = sd.get("aim_point", "None"),
                        defense_point = sd.get("defense_point", "None"),
                    ))
            if not w.strategies:
                w.strategies = [Strategy()]

        save_team(team)

        # Return updated warrior data
        return {"success": True, "warrior": warrior_to_json(w)}

    except Exception as e:
        import traceback; traceback.print_exc()
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# TURN RUNNER
# ---------------------------------------------------------------------------

def _run_turn_for_team(body: dict) -> dict:
    """
    Run one full turn for a player team.
    Returns a JSON summary with per-fight results and the refreshed team data.
    """
    try:
        from matchmaking     import run_turn as _do_run_turn
        from ai_league_teams import get_or_create_ai_teams, evolve_ai_teams
        from save            import load_champion_state, load_all_teams

        team_id = int(body.get("team_id", 0))
        team    = load_team(team_id)

        # Build opponent pool: AI league teams + all other saved teams
        ai_teams  = get_or_create_ai_teams()
        ai_team_objects = []
        ai_tid_to_mid = {}
        for at in ai_teams:
            try:
                t = Team.from_dict(at)
                if t.active_warriors:
                    ai_team_objects.append(t)
                    ai_tid_to_mid[t.team_id] = at["manager_id"]
            except Exception:
                pass

        all_saved = load_all_teams()
        ai_team_ids = {t.team_id for t in ai_team_objects}
        opponent_teams = ai_team_objects + [
            t for t in all_saved
            if t.team_id != team_id and t.team_id not in ai_team_ids
        ]

        turn_num = increment_turn()
        champion_state = load_champion_state()

        card = _do_run_turn(team, opponent_teams, verbose=False, champion_state=champion_state)

        # Update AI team records from this turn's fights
        ai_results = {}
        for bout in card:
            mid = ai_tid_to_mid.get(bout.opponent_team.team_id)
            if mid is None:
                continue
            ow_won = bout.result and bout.result.winner and \
                     bout.result.winner.name == bout.opponent.name
            entry = ai_results.setdefault(mid, {"bouts": [], "team": None})
            entry["bouts"].append({
                "result": "WIN" if ow_won else "LOSS",
                "opponent_slain": bout.result and bout.result.loser_died
                                  and ow_won,
                "warrior_slain" : bout.result and bout.result.loser_died
                                  and not ow_won,
            })
            entry["team"] = bout.opponent_team.to_dict()
        if ai_results:
            evolve_ai_teams(ai_teams, ai_results)

        bouts = []
        for bout in card:
            pw = bout.player_warrior
            r  = bout.result
            if not r:
                continue
            if r.winner and r.winner.name == pw.name:
                result_str = "WIN"
            elif r.winner is None:
                result_str = "DRAW"
            else:
                result_str = "LOSS"

            bouts.append({
                "warrior_name"   : pw.name,
                "opponent_name"  : bout.opponent.name,
                "opponent_race"  : bout.opponent.race.name,
                "opponent_team"  : bout.opponent_team.team_name,
                "opponent_manager": bout.opponent_manager,
                "fight_type"     : bout.fight_type,
                "result"         : result_str,
                "minutes"        : r.minutes_elapsed,
                "warrior_slain"  : r.loser_died and r.loser is bout.player_warrior,
                "opponent_slain" : r.loser_died and r.winner is not None
                                   and r.winner.name == pw.name,
                "opponent_wins"  : getattr(bout.opponent, "wins",   0),
                "opponent_losses": getattr(bout.opponent, "losses", 0),
                "opponent_kills" : getattr(bout.opponent, "kills",  0),
                "fight_id"       : bout.fight_id,
                "training"       : r.training_results.get("warrior_a", []),
            })

        # Reload fresh team (may contain replacement warriors)
        fresh_team = load_team(team_id)

        return {
            "success"     : True,
            "turn_number" : turn_num,
            "bouts"       : bouts,
            "team"        : team_to_json(fresh_team),
        }

    except Exception as e:
        import traceback; traceback.print_exc()
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# LEAGUE SETTINGS (local file per player)
# ---------------------------------------------------------------------------


def _load_all_league_settings() -> dict:
    """Load the full per-manager settings dict, migrating old flat format if needed."""
    if not os.path.exists(LEAGUE_SETTINGS_FILE):
        return {}
    try:
        with open(LEAGUE_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Migrate: if the file is the old flat format (has "url" at top level), wrap it
        if isinstance(data, dict) and ("url" in data or "managerId" in data):
            old_name = data.get("managerName", "").strip().upper()
            if old_name:
                return {old_name: data}
            return {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _get_league_settings() -> dict:
    """Legacy: return settings without filtering by manager (used by run_turn helpers)."""
    all_s = _load_all_league_settings()
    if not all_s:
        # Return default settings with server URL from config
        from accounts import _load_league_config
        config = _load_league_config()
        default_url = config.get("league_server_url", "").strip()
        return {"success": True, "settings": {"url": default_url} if default_url else {}}
    # Return first entry found
    first = next(iter(all_s.values()))
    return {"success": True, "settings": first}


def _get_league_settings_for(manager_name: str) -> dict:
    """Return league settings for a specific manager account."""
    all_s = _load_all_league_settings()
    key = manager_name.strip().upper()
    settings = all_s.get(key, {})
    
    # If no server URL is configured, use the default from league_config.json
    if not settings.get("url", "").strip():
        from accounts import _load_league_config
        config = _load_league_config()
        default_url = config.get("league_server_url", "").strip()
        if default_url:
            settings["url"] = default_url
    
    # Calculate lastTurnRan from team turn_history if not explicitly set
    if "lastTurnRan" not in settings or not settings["lastTurnRan"]:
        from save import load_all_teams
        try:
            # Get all teams owned by this manager
            teams = load_all_teams()
            manager_key = manager_name.strip().upper()
            last_turn = None
            for team in teams:
                # Match teams with same manager name (case-insensitive)
                team_mgr = (team.manager_name or "").strip().upper()
                if team_mgr == manager_key and team.turn_history:
                    # Get the most recent turn from this team's turn_history
                    most_recent = team.turn_history[-1].get("turn")
                    if most_recent:
                        last_turn = max(last_turn, most_recent) if last_turn else most_recent
            if last_turn:
                settings["lastTurnRan"] = last_turn
        except Exception:
            pass  # Fall back to saved value or undefined
    
    return {"success": True, "settings": settings}


def _save_league_settings_for(body: dict) -> dict:
    """Save league settings for the manager named in body['manager_name']."""
    os.makedirs(os.path.dirname(LEAGUE_SETTINGS_FILE), exist_ok=True)
    manager_name = body.get("manager_name", "").strip().upper()
    if not manager_name:
        # Fallback: use managerName from the settings payload itself
        manager_name = body.get("managerName", "").strip().upper()
    if not manager_name:
        return {"success": False, "error": "manager_name required"}
    all_s = _load_all_league_settings()
    # Store everything except the account-level manager_name key
    entry = {k: v for k, v in body.items() if k != "manager_name"}
    all_s[manager_name] = entry
    with open(LEAGUE_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_s, f, indent=2)
    return {"success": True}


def _save_league_settings(body: dict) -> dict:
    settings = body.get("settings", {})
    os.makedirs(os.path.dirname(LEAGUE_SETTINGS_FILE), exist_ok=True)
    with open(LEAGUE_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    return {"success": True}


# ---------------------------------------------------------------------------
# LEAGUE PROXY HELPERS
# ---------------------------------------------------------------------------

def _league_url(path: str) -> str:
    """Build full league server URL from stored settings."""
    try:
        s = _get_league_settings().get("settings", {})
        base = s.get("server_url", "").rstrip("/")
        if not base:
            return None
        return base + path
    except Exception:
        return None


def _league_proxy_get(path: str, params: dict = None) -> dict:
    url = _league_url(path)
    if not url:
        return {"success": False, "error": "No league server URL configured."}
    if params:
        qs = urllib.parse.urlencode(params)
        url = f"{url}?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"success": False, "error": f"Could not reach league server: {e}"}


def _league_proxy_post(path: str, body: dict) -> dict:
    url = _league_url(path)
    if not url:
        return {"success": False, "error": "No league server URL configured."}
    try:
        data = json.dumps(body).encode("utf-8")
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"success": False, "error": f"Could not reach league server: {e}"}


def _fetch_latest_league_newsletter() -> dict:
    """Fetch the most recent newsletter from league server (for new users)."""
    url = _league_url("/api/latest_newsletter")
    if not url:
        return {"success": False, "error": "No league server URL configured."}
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
            if data.get("success"):
                # Save the newsletter locally
                from save import save_newsletter
                save_newsletter(data["turn"], data["newsletter"])
            return data
    except Exception as e:
        return {"success": False, "error": f"Could not fetch newsletter: {e}"}


def _do_league_upload(body: dict) -> dict:
    """Load the player's team from local disk, attach credentials, upload."""
    try:
        acct_name = body.get("manager_name", "").strip().upper()
        settings  = _get_league_settings_for(acct_name).get("settings", {})
        team_id   = int(body.get("team_id", 0))
        mgr_id    = settings.get("manager_id")
        password  = settings.get("password", "")

        if not mgr_id:
            return {"success": False, "error": "Not registered with league server."}

        team = load_team(team_id)
        return _league_proxy_post("/league/upload", {
            "manager_id": mgr_id,
            "password"  : password,
            "team"      : team.to_dict(),
        })
    except Exception as e:
        return {"success": False, "error": str(e)}


def _do_league_get_results(body: dict) -> dict:
    """Fetch results from league server and apply to the local team."""
    try:
        acct_name = body.get("manager_name", "").strip().upper()
        settings  = _get_league_settings_for(acct_name).get("settings", {})
        mgr_id    = settings.get("manager_id")
        password  = settings.get("password", "")
        team_id   = int(body.get("team_id", 0))

        if not mgr_id:
            return {"success": False, "error": "Not registered with league server."}

        url = _league_url(
            f"/league/results?manager_id={mgr_id}&password="
            + urllib.parse.quote(password)
        )
        if not url:
            return {"success": False, "error": "No league server URL configured."}

        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())

        if not data.get("success"):
            return data

        # Apply the updated team from the server to local storage
        updated = data.get("updated_team")
        if updated:
            from team import Team
            new_team = Team.from_dict(updated)
            save_team(new_team)

        return {
            "success"     : True,
            "turn"        : data.get("turn"),
            "bouts"       : data.get("bouts", []),
            "team"        : team_to_json(load_team(team_id)) if updated else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# REPLACEMENT WARRIOR HANDLER
# ---------------------------------------------------------------------------

def _confirm_replacement(body: dict) -> dict:
    """
    Confirm a player-created replacement warrior for a dead slot.
    Expects:
      team_id, slot_idx,
      name, race, gender,
      strength, dexterity, constitution, intelligence, presence, size
    """
    try:
        team    = load_team(int(body["team_id"]))
        idx     = int(body["slot_idx"])
        dead    = team.warriors[idx] if idx < len(team.warriors) else None

        if dead is None or not getattr(dead, "is_dead", False):
            return {"success": False, "error": "Slot is not awaiting a replacement."}

        name = (body.get("name") or "").strip().upper()
        if not name:
            return {"success": False, "error": "Replacement warrior needs a name."}

        new_w = Warrior(
            name         = name,
            race_name    = body.get("race", "Human"),
            gender       = body.get("gender", "Male"),
            strength     = int(body.get("strength",     10)),
            dexterity    = int(body.get("dexterity",    10)),
            constitution = int(body.get("constitution", 10)),
            intelligence = int(body.get("intelligence", 10)),
            presence     = int(body.get("presence",     10)),
            size         = int(body.get("size",         10)),
        )
        import random as _r
        new_w.luck          = _r.randint(1, 30)
        new_w.initial_stats = {
            attr: int(body.get(attr, 10)) for attr in ATTRIBUTES
        }

        ok = team.confirm_replacement(idx, new_w)
        if not ok:
            return {"success": False, "error": "Could not complete replacement."}

        save_team(team)
        return {"success": True, "team": team_to_json(team)}

    except Exception as e:
        import traceback; traceback.print_exc()
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# LEAGUE RESULT APPLICATOR
# ---------------------------------------------------------------------------

def _slim_team_for_upload(team_json: dict) -> dict:
    """
    Strip fields the league server doesn't need for running fights.
    Keeps: team identity, warrior stats, gear, strategies, trains, skills, injuries,
           archived_warriors.
    Drops: fight_history, turn_history, pending_replacements — bulk data not needed
           server-side.
    """
    slim = {
        "team_id"     : team_json.get("team_id"),
        "team_name"   : team_json.get("team_name"),
        "manager_name": team_json.get("manager_name"),
        "warriors"    : [],
        "archived_warriors": team_json.get("archived_warriors", []),
        # Preserve turn_history so the server can build an accurate last-5-turns record
        "turn_history": team_json.get("turn_history", []),
    }
    for w in team_json.get("warriors", []):
        if not w:
            slim["warriors"].append(None)
            continue
        slim["warriors"].append({
            "name"          : w.get("name"),
            "race"          : w.get("race"),
            "gender"        : w.get("gender"),
            "strength"      : w.get("strength"),
            "dexterity"     : w.get("dexterity"),
            "constitution"  : w.get("constitution"),
            "intelligence"  : w.get("intelligence"),
            "presence"      : w.get("presence"),
            "size"          : w.get("size"),
            "primary_weapon"  : w.get("primary_weapon"),
            "secondary_weapon": w.get("secondary_weapon"),
            "backup_weapon"   : w.get("backup_weapon"),
            "armor"         : w.get("armor"),
            "helm"          : w.get("helm"),
            "skills"        : w.get("skills", {}),
            "strategies"    : w.get("strategies", []),
            "trains"        : w.get("trains", []),
            "luck"          : w.get("luck", 15),
            "wins"          : w.get("wins", 0),
            "losses"        : w.get("losses", 0),
            "kills"         : w.get("kills", 0),
            "total_fights"  : w.get("total_fights", 0),
            "popularity"    : w.get("popularity", 0),
            "recognition"   : w.get("recognition", 0),
            "attribute_gains": w.get("attribute_gains", {}),
            "training_weight_bonus": w.get("training_weight_bonus", 0),
            "is_dead"            : w.get("is_dead", False),
            "want_monster_fight" : w.get("want_monster_fight", False),
            "want_retire"        : w.get("want_retire", False),
            # Needed for favorite-weapon flavor text in fight narratives
            "favorite_weapon"    : w.get("favorite_weapon", ""),
            "injuries"           : w.get("injuries", {}),
        })
    return slim


def _league_download_all(body: dict) -> dict:
    """
    Fetch results for all of a manager's teams from the league server,
    then apply each result to the matching local team file.

    Matches results to local teams by team_name (the name used when uploading).
    Returns a summary of what was applied.
    """
    import urllib.request as _ur
    import urllib.error   as _ue

    league_url = body.get("league_url",  "")
    league_id  = body.get("league_manager_id", "")
    password   = body.get("password",    "")
    team_ids   = [int(x) for x in body.get("team_ids", [])]

    if not league_url or not league_id:
        return {"success": False, "error": "League URL and manager ID required."}

    # 1. Fetch all results from league server
    try:
        url = (f"{league_url}/api/results"
               f"?manager_id={_ur.quote(str(league_id))}"
               f"&password={_ur.quote(str(password))}")
        resp_raw = _ur.urlopen(url, timeout=60).read()
        resp = json.loads(resp_raw)
    except _ue.HTTPError as e:
        try:   err_body = json.loads(e.read())
        except: err_body = {}
        return {"success": False, "error": err_body.get("error", f"HTTP {e.code}")}
    except Exception as e:
        return {"success": False, "error": f"Could not reach server: {e}"}

    if not resp.get("success"):
        return {"success": False, "error": resp.get("error", "Server error")}

    # Support both old single-result format and new multi-result format
    team_results = resp.get("results") or ([resp["result"]] if resp.get("result") else [])
    if not team_results:
        return {"success": False, "error": "No results returned from server."}

    turn_num = resp.get("turn") or (team_results[0].get("turn") if team_results else None)

    # Fetch newsletter separately (it was split out to keep /api/results payload small)
    newsletter_saved = False
    nl_text = ""
    if resp.get("has_newsletter") and turn_num:
        try:
            nl_url   = (f"{league_url}/api/newsletter"
                        f"?turn={turn_num}"
                        f"&manager_id={_ur.quote(str(league_id))}"
                        f"&password={_ur.quote(str(password))}")
            nl_resp  = json.loads(_ur.urlopen(nl_url, timeout=30).read())
            nl_text  = nl_resp.get("newsletter","")
        except Exception as e:
            print(f"  WARNING: could not fetch newsletter: {e}")

    # Save newsletter locally
    if nl_text and turn_num:
        try:
            from save import save_newsletter
            save_newsletter(int(turn_num), nl_text)
            newsletter_saved = True
        except Exception as e:
            print(f"  WARNING: could not save newsletter: {e}")

    # 2. Build local team name → team_id and team_id set from ALL saved team files
    #    (not just account.team_ids which may be empty after reset)
    name_to_id = {}
    known_tids  = set(int(x) for x in team_ids if x)  # from client hint
    from save import TEAMS_DIR
    import glob as _glob
    for fpath in _glob.glob(os.path.join(TEAMS_DIR, "team_*.json")):
        try:
            with open(fpath, "r", encoding="utf-8") as _f:
                td = json.loads(_f.read())
            tid  = td.get("team_id")
            tname= td.get("team_name","").lower()
            if tid:
                known_tids.add(int(tid))
                name_to_id[tname] = int(tid)
        except Exception:
            pass

    # 3. Apply each result to its matching local team
    applied    = []
    not_matched= []

    for result in team_results:
        # Try to match by team_id first, then by team_name
        local_tid = None
        server_tid = result.get("team_id")
        if server_tid and int(server_tid) in known_tids:
            local_tid = int(server_tid)
        else:
            tname = result.get("team_name", "").lower()
            local_tid = name_to_id.get(tname)

        if not local_tid:
            not_matched.append(result.get("team_name", "Unknown"))
            continue

        app = _apply_league_results({
            "team_id": local_tid,
            "result" : result,
        })
        if app.get("success"):
            applied.append({
                "team_id"   : local_tid,
                "team_name" : result.get("team_name", "?"),
                "bouts"     : app.get("bouts", []),
                "team"      : app.get("team"),
            })
        else:
            not_matched.append(f"{result.get('team_name','?')}: {app.get('error','?')}")

    return {
        "success"          : True,
        "turn_number"      : turn_num,
        "applied"          : applied,
        "not_matched"      : not_matched,
        "newsletter_saved" : newsletter_saved,
    }


def _check_league_reset() -> dict:
    """
    Fetch /api/status from the league server and compare reset_count to the
    locally stored last_reset_count.  Returns reset_detected=True if they differ.
    """
    import urllib.request as _ur
    settings = _get_league_settings().get("settings", {})
    league_url = (settings.get("url") or settings.get("server_url") or "").rstrip("/")
    if not league_url:
        return {"success": False, "error": "Not connected to a league server."}
    try:
        resp = json.loads(_ur.urlopen(f"{league_url}/api/status", timeout=10).read())
    except Exception as e:
        return {"success": False, "error": f"Could not reach league server: {e}"}
    server_reset_count = resp.get("reset_count", 0)
    local_reset_count  = settings.get("last_reset_count", 0)
    return {
        "success"            : True,
        "reset_detected"     : server_reset_count != local_reset_count,
        "server_reset_count" : server_reset_count,
        "local_reset_count"  : local_reset_count,
    }


def _acknowledge_league_reset(body: dict) -> dict:
    """
    Called after the user confirms the reset prompt.
    Season reset — clears fight records, injuries, and fallen warriors while
    preserving each warrior's identity, stats, gear, and strategies. Stores the
    new reset_count so the prompt won't reappear. The user must re-register
    with the league server before uploading for the new season.
    """
    from save import reset_arena_season
    result = reset_arena_season()
    if not result.get("success"):
        return result
    settings_data = {"last_reset_count": body.get("server_reset_count", 0)}
    _save_league_settings({"settings": settings_data})
    return {"success": True,
            "message": "Season reset. Fight records, injuries, and fallen warriors cleared. "
                       "Warriors, stats, gear, and strategies preserved — re-register to upload."}


def _apply_league_results(body: dict) -> dict:
    """
    Apply results received from the league server to a local team save.

    Updates from the league result (authoritative — server ran the fight):
      - wins / losses / kills / total_fights
      - popularity / streak / turns_active
      - skills (from training)
      - attribute_gains (from training)
      - injuries
      - fight_history  (new entries for this turn, with league fight_ids)
      - is_dead / killed_by

    Preserved from local copy (user-set — server has no business changing these):
      - trains        (training queue the user set in the UI)
      - strategies    (tactics the user configured)
      - initial_stats (creation stats display)
      - gear          (armor/helm/weapons — user controls these)
    """
    try:
        result = body.get("result", {})
        if not result:
            return {"success": False, "error": "No result data provided."}

        team_id = int(body.get("team_id", 0))
        if not team_id:
            return {"success": False, "error": "team_id required."}

        from save import load_team, save_team
        from warrior import Warrior

        team        = load_team(team_id)
        server_warriors = result.get("team", {}).get("warriors", [])

        for idx, wd in enumerate(server_warriors):
            if wd is None or idx >= len(team.warriors):
                continue

            local_w = team.warriors[idx]
            server_w = Warrior.from_dict(wd)

            if local_w is None:
                team.warriors[idx] = server_w
                continue

            # ── Apply authoritative stats from server ────────────────────
            local_w.wins          = server_w.wins
            local_w.losses        = server_w.losses
            local_w.kills         = server_w.kills
            local_w.total_fights  = server_w.total_fights
            local_w.popularity    = server_w.popularity
            # Take the higher of local (historical) and server (this turn) values.
            # Then enforce minimum floor: total_fights (wins + losses).
            local_w.recognition   = max(local_w.recognition, server_w.recognition)
            _min_rec = local_w.total_fights
            local_w.recognition   = max(local_w.recognition, _min_rec)
            local_w.streak        = server_w.streak
            local_w.turns_active  = server_w.turns_active
            local_w.injuries      = server_w.injuries
            local_w.is_dead       = server_w.is_dead
            local_w.killed_by     = server_w.killed_by
            # Monster ascension flags — server-authoritative
            local_w.ascended_to_monster = getattr(server_w, "ascended_to_monster", False)
            local_w.monster_kills       = getattr(server_w, "monster_kills", 0)

            # ── Skills — merge: take max so local gains are never lost ───
            for sk, val in server_w.skills.items():
                if val > local_w.skills.get(sk, 0):
                    local_w.skills[sk] = val

            # ── Attribute gains — take server value (training ran there) ─
            local_w.attribute_gains = server_w.attribute_gains

            # ── Recalculate derived stats from updated attributes ─────────
            # Update raw attributes if server training raised them
            for attr in ("strength","dexterity","constitution",
                         "intelligence","presence"):
                server_val = getattr(server_w, attr, None)
                if server_val and server_val > getattr(local_w, attr, 0):
                    setattr(local_w, attr, server_val)

            local_w.recalculate_derived()

            # ── Fight history — apply new entries from this turn ────────
            # server_w.fight_history may be empty if result was stored by old
            # code that stripped it. Fall back to reconstructing from bouts.
            source_history = server_w.fight_history
            if not source_history:
                turn_n = result.get("turn", 0)
                for b in result.get("bouts", []):
                    if b.get("warrior_name") == local_w.name:
                        source_history = [{
                            "turn"          : turn_n,
                            "opponent_name" : b.get("opponent_name", "?"),
                            "opponent_race" : b.get("opponent_race", "?"),
                            "opponent_team" : b.get("opponent_team", "?"),
                            "result"        : b.get("result", "?").lower(),
                            "minutes"       : b.get("minutes", 0),
                            "fight_id"      : b.get("fight_id"),
                            "warrior_slain" : b.get("warrior_slain", False),
                            "opponent_slain": b.get("opponent_slain", False),
                            "is_kill"       : b.get("opponent_slain", False),
                        }]
                        break

            if source_history:
                # The league server is authoritative for the turns it ran.
                # Remove any local entries for those turns first (handles fight_id
                # collisions between the local counter and the league server's
                # counter, which are independent and can overlap if the player
                # ran local test turns before joining the league).
                source_turns = {e.get("turn") for e in source_history if e.get("turn")}
                if source_turns:
                    local_w.fight_history = [
                        e for e in local_w.fight_history
                        if e.get("turn") not in source_turns
                    ]
                local_w.fight_history.extend(source_history)

            # ── Keep local user-set fields ────────────────────────────────
            # (trains, strategies, gear, initial_stats preserved as-is)

        # ── Merge team turn_history from server results ───────────────────
        # Update the team's record of wins/losses/kills per turn
        server_team_dict = result.get("team", {})
        server_turn_history = server_team_dict.get("turn_history", [])
        if server_turn_history:
            local_known_turns = {e.get("turn") for e in team.turn_history}
            for entry in server_turn_history:
                turn_n = entry.get("turn")
                if turn_n and turn_n not in local_known_turns:
                    team.turn_history.append(entry)
                    local_known_turns.add(turn_n)

        save_team(team)

        # Scouting locks reset after a league turn is downloaded.
        try:
            from accounts import get_manager_for_team
            from save     import clear_manager_scouting
            mid = get_manager_for_team(team_id)
            if mid is not None:
                clear_manager_scouting(mid)
        except Exception:
            pass

        # Build bout summary for the turn-results view
        bouts = list(result.get("bouts", []))

        return {
            "success"     : True,
            "turn_number" : result.get("turn"),
            "bouts"       : bouts,
            "team"        : team_to_json(team),
        }

    except Exception as e:
        import traceback; traceback.print_exc()
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# FULL ARENA RESET
# ---------------------------------------------------------------------------

def _full_reset() -> dict:
    """
    Wipe the entire arena state while preserving accounts and passwords.
    Removes:
      - All team save files  (saves/teams/)
      - All fight logs       (saves/fights/)
      - All turn logs        (saves/logs/)
      - All newsletters      (saves/newsletters/)
      - All team archives    (saves/team_archives/)
      - League server data   (saves/league/  — all turns, standings, ai_teams, uploads)
      - Champion state       (saves/champion.json)
      - Legacy rivals pool    (saves/rivals.json — if present)
      - League client settings (saves/league_client.json, saves/league_settings.json)
      - Session cache        (saves/session.json)
      - Game state counters  (turn number, fight ID — reset to 0/1)
    Keeps:
      - saves/accounts.json  (manager names and hashed passwords)
    """
    import shutil

    BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves")

    # Directories to wipe entirely then recreate empty
    dirs_to_wipe = [
        os.path.join(BASE, "teams"),
        os.path.join(BASE, "fights"),
        os.path.join(BASE, "logs"),
        os.path.join(BASE, "newsletters"),
        os.path.join(BASE, "team_archives"),
        os.path.join(BASE, "league"),
    ]
    for d in dirs_to_wipe:
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)

    # Individual files to delete (league_settings.json is preserved —
    # the manager's league registration survives an arena reset)
    files_to_delete = [
        os.path.join(BASE, "champion.json"),
        os.path.join(BASE, "rivals.json"),
        os.path.join(BASE, "league_client.json"),   # old name — safe to delete
        os.path.join(BASE, "newsletter_settings.json"),
        os.path.join(BASE, "session.json"),
    ]
    for fpath in files_to_delete:
        if os.path.exists(fpath):
            os.remove(fpath)

    # Reset game state counters (turn → 0, fight_id → 1, team_id preserved)
    from save import load_game_state, save_game_state
    state = load_game_state()
    state["turn_number"]   = 0
    state["next_fight_id"] = 1
    # next_team_id stays intact so new IDs never collide with old archived data
    save_game_state(state)

    # Strip team_ids from all accounts (teams are gone) but keep accounts themselves
    accounts_file = os.path.join(BASE, "accounts.json")
    if os.path.exists(accounts_file):
        with open(accounts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for acc in data.get("accounts", []):
            acc["team_ids"]      = []
            acc["run_next_turn"] = {}
        with open(accounts_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    print("  *** FULL ARENA RESET COMPLETE ***")
    return {
        "success": True,
        "message": (
            "Full arena reset complete. "
            "All teams, warriors, fight records, logs, newsletters, "
            "league data have been wiped. "
            "Accounts and passwords preserved."
        ),
    }


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

def main():
    global _global_server
    server = http.server.HTTPServer(("127.0.0.1", PORT), BloodspireHandler)
    _global_server = server
    url    = f"http://localhost:{PORT}"

    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║     BLOODSPIRE CLIENT - v1.2         ║")
    print("  ╚══════════════════════════════════════╝")
    print(f"\n  Server running at: {url}")
    print("  Opening browser... (Ctrl+C to stop)\n")

    if not os.path.exists(HTML_FILE):
        print(f"  ERROR: Bloodspire_client.html not found at {HTML_FILE}")
        print("  Make sure all game files are in the same directory.")
        return

    threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped. Farewell from the BLOODSPIRE.")


if __name__ == "__main__":
    main()
