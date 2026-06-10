#!/usr/bin/env python3
"""
Regenerate team roster HTML now.
"""

import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from team_roster import generate_team_roster_html, write_team_roster
from save import load_all_teams

def load_config():
    cfg_path = os.path.join(BASE_DIR, "saves", "league", "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"ERROR loading config: {e}")
        return {}

def load_uploads(turn_num):
    """Load uploads for a given turn."""
    turn_dir = os.path.join(BASE_DIR, "saves", "league", f"turn_{int(turn_num):04d}")
    uploads = {}

    if not os.path.exists(turn_dir):
        print(f"  Warning: Turn directory not found: {turn_dir}")
        return uploads

    try:
        result_files = [f for f in os.listdir(turn_dir) if f.startswith("result_") and f.endswith(".json")]
    except Exception as e:
        print(f"  Warning: Could not list turn directory: {e}")
        return uploads

    for fname in result_files:
        fpath = os.path.join(turn_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                manager_id = data.get("manager_id") or data.get("manager_name")
                if manager_id:
                    uploads[manager_id] = data
        except Exception as e:
            print(f"  Warning: Could not load {fname}: {e}")

    return uploads

def main():
    print("Regenerating team roster HTML...")

    # Load config
    cfg = load_config()
    turn_num = cfg.get("current_turn", 1)
    print(f"  Current turn: {turn_num}")

    # Load all teams
    print("  Loading teams...")
    teams = load_all_teams()
    print(f"    Loaded {len(teams)} teams")

    # Load uploads for current turn
    print(f"  Loading uploads for turn {turn_num}...")
    uploads = load_uploads(turn_num)
    print(f"    Loaded {len(uploads)} uploads")

    # Build team_map keyed by upload key (manager_id_team_id from uploads)
    team_map = {}
    for upload_id, upload in uploads.items():
        # Try to find matching team
        team_data = upload.get("team", {})
        team_id = team_data.get("team_id")
        for team in teams:
            if team.team_id == team_id:
                team_map[upload_id] = team
                break

    # Generate roster HTML
    print("  Generating team roster HTML...")
    roster_html = generate_team_roster_html(uploads, team_map, turn_num)

    # Write and push
    reports_dir = os.path.join(BASE_DIR, "saves", "league", "reports")
    print(f"  Writing to {reports_dir}...")
    write_team_roster(roster_html, reports_dir)

    print("\n[OK] Team roster regenerated successfully!")
    print(f"  File: {os.path.join(reports_dir, 'team_roster.html')}")

if __name__ == "__main__":
    main()
