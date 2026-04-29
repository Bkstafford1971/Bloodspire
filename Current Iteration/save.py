# =============================================================================
# save.py — BLOODSPIRE Save & Load System
# =============================================================================
# All data is stored as JSON files under the saves/ directory.
#
# Directory layout:
#   saves/
#     game_state.json         — global state (next team ID, turn counter)
#     teams/
#       team_0001.json        — one file per team
#       team_0002.json
#       ...
#     fights/
#       fight_0001.txt        — plain-text fight log
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
import zipfile
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
# Central manager registry owned by league_server.py — the source of truth
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
        with open(MONSTER_TEAM_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Team.from_dict(data)
    except (json.JSONDecodeError, IOError, KeyError) as e:
        print(f"  WARNING: Could not load monster_team.json ({e}). Using hardcoded roster.")
        return None


def save_monster_team(team: Team):
    """Persist the monster team to disk."""
    _ensure_dirs()
    try:
        with open(MONSTER_TEAM_FILE, "w", encoding="utf-8") as f:
            json.dump(team.to_dict(), f, indent=2)
    except IOError as e:
        print(f"  ERROR: Could not save monster_team.json: {e}")


# ---------------------------------------------------------------------------
# GAME STATE (global counters)
# ---------------------------------------------------------------------------

DEFAULT_GAME_STATE = {
    "next_team_id" : 1,
    "next_fight_id": 1,
    "turn_number"  : 0,
}


def load_game_state() -> dict:
    """Load global game state. Returns defaults if no save exists yet."""
    _ensure_dirs()
    if not os.path.exists(GAME_STATE_FILE):
        return DEFAULT_GAME_STATE.copy()
    try:
        with open(GAME_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        # Fill in any missing keys with defaults (handles version upgrades)
        for k, v in DEFAULT_GAME_STATE.items():
            state.setdefault(k, v)
        return state
    except (json.JSONDecodeError, IOError) as e:
        print(f"  WARNING: Could not load game_state.json ({e}). Using defaults.")
        return DEFAULT_GAME_STATE.copy()


def save_game_state(state: dict):
    """Persist global game state to disk."""
    _ensure_dirs()
    try:
        with open(GAME_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
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

    filepath = _team_filepath(team.team_id)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(team.to_dict(), f, indent=2)
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
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Team.from_dict(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Corrupted save file for team {team_id}: {e}")


def load_all_teams() -> List[Team]:
    """
    Load every team save file found in the teams directory.
    Skips and warns on any corrupted files.
    Returns a list of Team objects, sorted by team_id.
    """
    _ensure_dirs()
    teams = []
    for filename in sorted(os.listdir(TEAMS_DIR)):
        if not filename.startswith("team_") or not filename.endswith(".json"):
            continue
        try:
            id_str  = filename.replace("team_", "").replace(".json", "")
            team_id = int(id_str)
            team    = load_team(team_id)
            teams.append(team)
        except (ValueError, FileNotFoundError) as e:
            print(f"  WARNING: Skipping '{filename}': {e}")
    return teams


def delete_team(team_id: int) -> bool:
    """
    Delete a team's save file.
    Returns True if deleted, False if the file didn't exist.
    """
    filepath = _team_filepath(team_id)
    if os.path.exists(filepath):
        os.remove(filepath)
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
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
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

    Fight logs are plain text — the full blow-by-blow narrative exactly
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
            f.write(f"Fight #{fight_id}\n")
            f.write(f"{team_a_name}  vs  {team_b_name}\n")
            f.write("=" * 76 + "\n\n")
            f.write(narrative_text)
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
            filepath = os.path.join(FIGHTS_DIR, filename)
            with open(filepath, "r", encoding="utf-8") as f:
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
    except IOError as e:
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
                if f.endswith(".json"):
                    zf.write(os.path.join(TEAMS_DIR, f), os.path.join("teams", f))
        # 2. Fight Narratives
        if os.path.exists(FIGHTS_DIR):
            for f in os.listdir(FIGHTS_DIR):
                if f.endswith(".txt"):
                    zf.write(os.path.join(FIGHTS_DIR, f), os.path.join("fights", f))
        # 3. Newsletters
        if os.path.exists(NEWSLETTERS_DIR):
            for f in os.listdir(NEWSLETTERS_DIR):
                if f.endswith(".txt"):
                    zf.write(os.path.join(NEWSLETTERS_DIR, f), os.path.join("newsletters", f))
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
    for filename in os.listdir(TEAMS_DIR):
        if filename.endswith(".json"):
            src = os.path.join(TEAMS_DIR, filename)
            dst = src.replace(".json", f".{backup_suffix}")
            shutil.copy2(src, dst)
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
    """Build HTML table rows for the fight summary — kept outside f-strings
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
        f"BLOODSPIRE — MATCHMAKING LOG",
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
<title>BLOODSPIRE — Turn {turn_num} Fight Log</title>
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
<h1>⚔ BLOODSPIRE — Fight Log</h1>
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
      - newsletter_settings.json (voice preferences — app config, not arena data)
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
    _rm_file(MONSTER_TEAM_FILE)
    _rm_file(os.path.join(SAVES_DIR, "league_settings.json"))
    _rm_file(os.path.join(SAVES_DIR, "rivals.json"))
    _rm_file(os.path.join(SAVES_DIR, "league_client.json"))

    state = load_game_state()
    state["turn_number"]   = 0
    state["next_fight_id"] = 1
    save_game_state(state)

    print("  Full arena reset complete. Accounts, teams, and all arena state cleared.")
    return {"success": True,
            "message": "Arena fully reset. All accounts, teams, and records cleared. Turn counter at 0."}


def reset_arena_season():
    """
    Season reset — clear fight records, injuries, and fallen warriors, but keep
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


# ---------------------------------------------------------------------------
# NEWSLETTERS
# ---------------------------------------------------------------------------

NEWSLETTERS_DIR  = os.path.join(SAVES_DIR, "newsletters")
CHAMPION_FILE    = os.path.join(SAVES_DIR, "champion.json")
VOICE_SETTINGS_FILE = os.path.join(SAVES_DIR, "newsletter_settings.json")


def save_newsletter(turn_num: int, text: str):
    """Save a newsletter text to saves/newsletters/turn_NNN.txt."""
    os.makedirs(NEWSLETTERS_DIR, exist_ok=True)
    path = os.path.join(NEWSLETTERS_DIR, f"turn_{turn_num:04d}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def load_newsletter(turn_num: int) -> Optional[str]:
    """Load a specific newsletter. Returns None if not found."""
    path = os.path.join(NEWSLETTERS_DIR, f"turn_{turn_num:04d}.txt")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
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
        with open(CHAMPION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
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
    with open(CHAMPION_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def load_newsletter_voice() -> str:
    """Return 'snide' or 'neutral'."""
    try:
        with open(VOICE_SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("voice", "snide")
    except Exception:
        return "snide"


def save_newsletter_voice(voice: str):
    """Persist voice preference."""
    _ensure_dirs()
    with open(VOICE_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump({"voice": voice}, f)


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
        with open(SCOUTING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_scouting(data: dict) -> None:
    """Persist scouting selections."""
    _ensure_dirs()
    with open(SCOUTING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_manager_scouting(manager_id: int, current_turn: int) -> list:
    """
    Return this manager's scout list for the current turn (all selections, confirmed or not).
    Automatically resets to [] if stored turn doesn't match current_turn.
    Returns list of dicts with: warrior_name, team_name, team_id, confirmed.
    """
    data = load_scouting()
    key  = str(manager_id)
    entry= data.get(key, {})
    if entry.get("turn") != current_turn:
        return []
    return list(entry.get("selections", []))


def set_manager_scouting(manager_id: int, current_turn: int, selections: list) -> None:
    """Persist scout selections for a manager/turn (max 3 warriors)."""
    data = load_scouting()
    data[str(manager_id)] = {"turn": current_turn, "selections": selections[:3]}
    save_scouting(data)


def add_manager_scouting(manager_id: int, current_turn: int, warrior_name: str, team_name: str, team_id: int, confirmed: bool = True) -> tuple:
    """
    Add a warrior to scout for a manager/turn. Returns (success, error_msg).
    Confirmed selections cannot be removed.
    """
    data = load_scouting()
    key  = str(manager_id)
    entry= data.get(key, {})
    
    # Reset if different turn
    if entry.get("turn") != current_turn:
        entry = {"turn": current_turn, "selections": []}
    
    # Check if already scouting
    for sel in entry.get("selections", []):
        if sel.get("warrior_name") == warrior_name:
            return (False, "Already scouting that warrior")
    
    # Check if at max capacity
    if len(entry.get("selections", [])) >= 3:
        return (False, "All 3 scout slots are full")
    
    # Add the selection
    entry.setdefault("selections", []).append({
        "warrior_name": warrior_name,
        "team_name": team_name,
        "team_id": team_id,
        "confirmed": confirmed
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
    # Read the league server's manager registry directly — the old accounts.py
    # local store is gone; manager records live at saves/league/managers.json.
    mgrs = {}
    try:
        if os.path.exists(LEAGUE_MANAGERS_FILE):
            with open(LEAGUE_MANAGERS_FILE, "r", encoding="utf-8") as _f:
                mgrs = json.load(_f) or {}
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
            if wname:
                result.setdefault(wname, []).append(mname)
    return result


# ---------------------------------------------------------------------------
# SESSION (remember last-used credentials)
# ---------------------------------------------------------------------------

SESSION_FILE = os.path.join(SAVES_DIR, "session.json")


def save_session(manager_name: str, password: str = ""):
    """
    Persist login credentials for auto-login on next launch.
    Password is stored obfuscated (base64) — not plaintext, not cryptographically
    protected.  This is purely convenience; security relies on the server-side
    bcrypt/sha256 check in accounts.py.
    """
    _ensure_dirs()
    import base64 as _b64
    pw_stored = _b64.b64encode(password.encode()).decode() if password else ""
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump({"manager_name": manager_name, "pw_stored": pw_stored}, f)
    except IOError:
        pass


def load_session() -> dict:
    """
    Return {manager_name, pw_stored} or {} if no session saved.
    pw_stored is base64-encoded; decode with base64.b64decode().
    """
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2, default=str)
    return path
