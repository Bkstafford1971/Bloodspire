"""
team_roster.py — Generate the team roster HTML report.

Groups all player teams by manager, sorted alphabetically.
Called from arena_stats._generate() so it's included in the GitHub push.
"""

from __future__ import annotations

import os
import json
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

# ── Public interface ───────────────────────────────────────────────────────────

def generate_team_roster_html(uploads: dict, team_map: dict, turn_num: int) -> str:
    """Build and return the team_roster.html content string.

    uploads  : raw upload dict (for manager IDs and fallen_warriors)
    team_map : post-fight Team objects keyed by upload key (for live records)
    turn_num : current turn number
    """
    # Load results from the most recent completed turn
    results = _load_most_recent_results()
    return _build_html(uploads, team_map, turn_num, results)


def write_team_roster(html: str, output_dir: str) -> None:
    """Write team_roster.html to output_dir and push to GitHub Pages."""
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "team_roster.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Team roster report written -> {out_path}")
    try:
        from github_push import push_to_github_pages
        push_to_github_pages({"team_roster.html": html})
    except Exception as _gh_err:
        print(f"  WARNING: team_roster GitHub push failed: {_gh_err}")


# ── Data processing ────────────────────────────────────────────────────────────

def _team_record(team_data: dict):
    """Sum W-L-K across current warriors + fallen warriors for all-time record."""
    tw = tl = tk = 0
    for w in (team_data.get("warriors") or []):
        if w:
            tw += w.get("wins",   0)
            tl += w.get("losses", 0)
            tk += w.get("kills",  0)
    for fw in (team_data.get("fallen_warriors") or []):
        if isinstance(fw, dict):
            tw += fw.get("wins",   0)
            tl += fw.get("losses", 0)
            tk += fw.get("kills",  0)
    return tw, tl, tk


def _warrior_record(w_obj) -> tuple:
    """Extract W-L-K from a Warrior object (post-fight) or raw dict (fallback)."""
    if hasattr(w_obj, "wins"):
        return w_obj.wins, w_obj.losses, w_obj.kills
    return w_obj.get("wins", 0), w_obj.get("losses", 0), w_obj.get("kills", 0)


def _load_most_recent_results() -> dict:
    """Load results from most recent completed turn for EACH team.

    Searches back through turns to find the most recent results for each team.
    Returns dict keyed by {manager_id}_team{team_id} with (result_data, turn_num).
    """
    import re

    base_dir = os.path.dirname(os.path.abspath(__file__))
    league_dir = os.path.join(base_dir, "saves", "league")
    results = {}  # key -> (data, turn_num)

    # Check turns in descending order
    for turn in range(9999, -1, -1):
        turn_dir = os.path.join(league_dir, f"turn_{turn:04d}")
        if not os.path.exists(turn_dir):
            continue

        # Look for result files in this turn
        try:
            for fname in os.listdir(turn_dir):
                if fname.startswith("result_") and fname.endswith(".json"):
                    # Extract manager_id and team_id from filename: result_MANAGER_teamTEAM_teamTEAM.json
                    match = re.search(r'result_(\d+)_team(\d+)', fname)
                    if not match:
                        continue

                    manager_id = int(match.group(1))
                    team_id = int(match.group(2))

                    fpath = os.path.join(turn_dir, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            key = f"{manager_id}_team{team_id}"
                            # Only store if we haven't found results for this team yet
                            if key not in results:
                                results[key] = (data, turn)
                    except Exception:
                        pass
        except Exception:
            pass

    return results


def _get_team_record_from_standings(team_id: int) -> tuple:
    """Load team career record from standings.json (includes all historical warriors)."""
    standings_path = os.path.join(os.path.dirname(__file__), "saves", "league", "standings.json")
    try:
        with open(standings_path, "r", encoding="utf-8") as f:
            standings = json.load(f)
        # Find team entry by team_id
        for team_key, team_data in standings.items():
            if team_data.get("team_id") == team_id:
                tw = tl = tk = 0
                for warrior in team_data.get("warriors", {}).values():
                    tw += warrior.get("wins", 0)
                    tl += warrior.get("losses", 0)
                    tk += warrior.get("kills", 0)
                return tw, tl, tk
    except Exception:
        pass
    return 0, 0, 0


def _build_html(uploads: dict, team_map: dict, turn_num: int, results: dict = None) -> str:
    if results is None:
        results = {}
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Load all data sources ────────────────────────────────────────────────
    standings_data = {}
    standings_path = os.path.join(os.path.dirname(__file__), "saves", "league", "standings.json")
    try:
        with open(standings_path, "r", encoding="utf-8") as f:
            standings_data = json.load(f)
    except Exception as e:
        print(f"  Warning: Could not load standings.json: {e}")

    managers_data = {}
    managers_path = os.path.join(os.path.dirname(__file__), "saves", "league", "managers.json")
    try:
        with open(managers_path, "r", encoding="utf-8") as f:
            managers_data = json.load(f)
    except Exception as e:
        print(f"  Warning: Could not load managers.json: {e}")

    # ── Build mapping: team_id -> manager_id ──────────────────────────────
    team_to_mgr = {}
    for mid_str, mgr_data in managers_data.items():
        for team_id in mgr_data.get("team_ids", []):
            team_to_mgr[int(team_id)] = int(mid_str)

    # ── Filter to player uploads ─────────────────────────────────────────────
    player_uploads = {mid: d for mid, d in uploads.items() if not mid.startswith("ai_")}

    # ── Group by manager_id (numeric), building from standings + uploads ───
    by_manager: Dict[int, List[tuple]] = defaultdict(list)  # mgr_id -> [(upload_key, team_data, upload)]
    manager_names: Dict[int, str]      = {}
    manager_ids: Dict[int, int]        = {}

    # First, add all teams from standings (with their manager_id from team_to_mgr)
    for team_key, team_data in standings_data.items():
        team_id = team_data.get("team_id")
        manager_name = team_data.get("manager_name", "")
        if not team_id or not manager_name or team_id not in team_to_mgr:
            continue

        mgr_id = team_to_mgr[team_id]
        by_manager[mgr_id].append((f"{mgr_id}_team{team_id}", team_data, None))
        manager_names[mgr_id] = manager_name
        manager_ids[mgr_id] = mgr_id

    # Then overlay uploads data (to get the latest from this turn)
    for upload_key, upload in player_uploads.items():
        manager_name = upload.get("manager_name", "")
        manager_id = upload.get("manager_id")
        if not manager_name or manager_id is None:
            continue

        manager_id = int(manager_id)
        manager_names[manager_id] = manager_name
        manager_ids[manager_id] = manager_id

        # Find and update existing team entry from standings
        team_data = upload.get("team", {})
        team_id = team_data.get("team_id")
        if not team_id:
            continue

        found = False
        if manager_id in by_manager:
            for i, (existing_key, existing_team, _) in enumerate(by_manager[manager_id]):
                if existing_team.get("team_id") == team_id:
                    by_manager[manager_id][i] = (upload_key, team_data, upload)
                    found = True
                    break
        if not found:
            by_manager[manager_id].append((upload_key, team_data, upload))

    sorted_mgr_ids = sorted(by_manager.keys())

    # ── Build roster HTML ────────────────────────────────────────────────────
    roster_blocks = ""
    for mgr_id in sorted_mgr_ids:
        mgr_name = manager_names.get(mgr_id, str(mgr_id))
        teams    = sorted(by_manager[mgr_id],
                          key=lambda t: t[1].get("team_id", 0))

        team_blocks = ""
        for upload_key, team_data, upload in teams:
            team_name   = team_data.get("team_name", "?")
            team_id     = team_data.get("team_id",   "?")

            # Prefer post-fight data from results (most recent completed turn for THIS team)
            raw_warriors = []
            last_turn = "—"

            if upload_key in results:
                # Use warriors and turn from most recent results for this team
                result_data, result_turn = results[upload_key]
                result_team = result_data.get("team", {})
                warriors_data = result_team.get("warriors") or []
                if isinstance(warriors_data, dict):
                    raw_warriors = list(warriors_data.values())
                else:
                    raw_warriors = warriors_data
                last_turn = str(result_turn)
            else:
                team_obj = team_map.get(upload_key)
                if team_obj is not None:
                    # Post-fight Team object from team_map
                    raw_warriors = team_obj.warriors or []
                else:
                    # Fallback: read from team data (standings or upload)
                    warriors_data = team_data.get("warriors") or []
                    # Convert dict to list if needed (standings.json uses dict format)
                    if isinstance(warriors_data, dict):
                        raw_warriors = list(warriors_data.values())
                    else:
                        raw_warriors = warriors_data

            # Get team record from result's turn_history (includes all warriors from all turns)
            tw = tl = tk = 0
            if upload_key in results:
                result_data, result_turn = results[upload_key]
                # Sum up all turns from turn_history for career record
                turn_history = result_data.get("team", {}).get("turn_history", [])
                for turn_entry in turn_history:
                    tw += turn_entry.get("w", 0)
                    tl += turn_entry.get("l", 0)
                    tk += turn_entry.get("k", 0)
            else:
                # Fall back to standings.json career record (includes all warriors)
                tw, tl, tk = _get_team_record_from_standings(int(team_id)) if str(team_id).isdigit() else (0, 0, 0)

            warrior_rows = ""
            for i, w in enumerate(raw_warriors):
                if not w:
                    continue
                if hasattr(w, "name"):
                    # Warrior object
                    name   = w.name
                    race   = w.race.name if hasattr(w.race, "name") else str(w.race)
                    gender = w.gender
                    ww, wl, wk = _warrior_record(w)
                    slot   = (w.slot_index if w.slot_index is not None else i) + 1
                    dead   = w.is_dead
                else:
                    # Raw dict fallback
                    name   = w.get("name",   "?")
                    race   = w.get("race",   "?")
                    gender = w.get("gender", "?")
                    ww, wl, wk = _warrior_record(w)
                    slot   = (w.get("slot_index") if w.get("slot_index") is not None else i) + 1
                    dead   = w.get("is_dead", False)

                dead_tag = '<span class="dead-flag">Dead</span>' if dead else ""
                warrior_rows += f"""
          <div class="w-row{'  w-dead' if dead else ''}">
            <span class="w-name">{name}</span>
            <span class="w-race">{race}</span>
            <span class="w-gender">{gender}</span>
            <span class="w-record">{ww}-{wl}-{wk}</span>
            <span class="w-slot">{slot}</span>
            {dead_tag}
          </div>"""

            team_blocks += f"""
        <div class="team-block">
          <div class="team-row">
            <span class="t-name">{team_name} ({team_id})</span>
            <span class="t-record">{tw}-{tl}-{tk}</span>
            <span class="t-spacer"></span>
            <span class="t-turn">Last Ran Turn {last_turn}</span>
          </div>
          {warrior_rows}
        </div>"""

        roster_blocks += f"""
      <div class="mgr-block">
        <div class="mgr-row">Manager: {mgr_name.upper()} ({mgr_id})</div>
        {team_blocks}
      </div>"""

    return _render_page(roster_blocks, turn_num, timestamp)


# ── HTML template ──────────────────────────────────────────────────────────────

def _render_page(roster_blocks: str, turn_num: int, timestamp: str) -> str:
    css = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
        background: #000; color: #fff;
        font-family: 'Courier New', Courier, monospace;
        font-size: 13px;
    }
    /* ── Header ── */
    .site-header {
        background: #000;
        border-bottom: 2px solid #880000;
        padding: 18px 32px 14px;
    }
    .site-name {
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 2.2em; font-weight: bold;
        color: #cc0000; letter-spacing: 2px;
        text-shadow: 0 0 12px #880000;
    }
    .site-subtitle { color: #888; font-size: 0.78em; letter-spacing: 2px; }

    /* ── Content ── */
    .content { padding: 28px 32px 60px; }
    h1 {
        font-family: Georgia, 'Times New Roman', serif;
        color: #fff; font-size: 1.5em;
        text-align: center; letter-spacing: 1px;
        margin-bottom: 4px;
    }
    .meta { color: #555; font-size: 0.80em; text-align: center; margin-bottom: 28px; }

    /* ── Manager block ── */
    .mgr-block { margin-bottom: 28px; }
    .mgr-row {
        color: #cc0000; font-weight: bold;
        font-size: 1.05em; margin-bottom: 6px;
        border-bottom: 1px solid #2a0000;
        padding-bottom: 3px;
    }

    /* ── Team block ── */
    .team-block { margin-left: 16px; margin-bottom: 14px; }
    .team-row {
        display: flex; align-items: center;
        background: #0d0000;
        padding: 4px 10px;
        margin-bottom: 2px;
        border-left: 3px solid #660000;
    }
    .t-name   { flex: 0 0 260px; color: #cc6600; font-weight: bold; }
    .t-record { flex: 0 0 110px; color: #dddddd; }
    .t-spacer { flex: 1; }
    .t-turn   { flex: 0 0 auto; color: #666; font-size: 0.9em; white-space: nowrap; }

    /* ── Warrior rows ── */
    .w-row {
        display: flex; align-items: center;
        padding: 2px 10px 2px 28px;
        border-left: 1px solid #1a1a1a;
        margin-bottom: 1px;
    }
    .w-row:nth-child(odd)  { background: #080808; }
    .w-row:nth-child(even) { background: #050505; }
    .w-dead { opacity: 0.55; }

    .w-name   { flex: 0 0 210px; color: #dddddd; }
    .w-race   { flex: 0 0 110px; color: #aaaaaa; }
    .w-gender { flex: 0 0 80px;  color: #aaaaaa; }
    .w-record { flex: 0 0 100px; color: #cccccc; }
    .w-slot   { flex: 0 0 36px;  color: #555; text-align: right; }
    .dead-flag { flex: 0 0 auto; margin-left: 12px; color: #cc0000; font-weight: bold; font-size: 0.9em; }

    /* ── Footer ── */
    .footer {
        border-top: 1px solid #1a0000; padding: 12px 32px;
        color: #444; font-size: 0.75em;
    }
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bloodspire -- Team Rosters Turn {turn_num}</title>
  <style>{css}</style>
</head>
<body>
  <div class="site-header">
    <div class="site-name">BLOODSPIRE</div>
    <div class="site-subtitle">THE AGONY AMPHITHEATRE</div>
  </div>
  <div class="content">
    <h1>Team Rosters</h1>
    <div class="meta">Turn {turn_num} &nbsp;|&nbsp; Generated: {timestamp}</div>
    {roster_blocks}
  </div>
  <div class="footer">
    All records shown are cumulative (current warriors + fallen warriors).
    Dead warriors are shown at reduced opacity.
  </div>
</body>
</html>
"""
