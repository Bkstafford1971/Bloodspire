#!/usr/bin/env python3
"""
Regenerate turn 6 newsletter with corrected champion logic.
"""

import os
import sys
import json
import glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

def load_config():
    cfg_path = os.path.join(BASE_DIR, "saves", "league", "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"ERROR loading config: {e}")
        return {}

def load_json(path):
    """Load JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  Warning: Could not load {path}: {e}")
        return {}

def load_uploads(turn_num):
    """Load uploads for a given turn."""
    turn_dir = os.path.join(BASE_DIR, "saves", "league", f"turn_{int(turn_num):04d}")
    uploads = {}

    if not os.path.exists(turn_dir):
        print(f"  Error: Turn directory not found: {turn_dir}")
        return uploads

    try:
        result_files = [f for f in os.listdir(turn_dir) if f.startswith("result_") and f.endswith(".json")]
    except Exception as e:
        print(f"  Error: Could not list turn directory: {e}")
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
    print("Regenerating turn 6 newsletter with corrected champion logic...")

    # Load config
    cfg = load_config()
    turn_num = 6
    print(f"  Turn: {turn_num}")

    # Load all teams
    print("  Loading teams...")
    from save import load_all_teams
    teams = load_all_teams()
    print(f"    Loaded {len(teams)} teams")

    # Load uploads for turn 6
    print(f"  Loading uploads for turn {turn_num}...")
    uploads = load_uploads(turn_num)
    print(f"    Loaded {len(uploads)} uploads")

    # Build team_map keyed by upload key
    team_map = {}
    for upload_id, upload in uploads.items():
        team_data = upload.get("team", {})
        team_id = team_data.get("team_id")
        for team in teams:
            if team.team_id == team_id:
                team_map[upload_id] = team
                break

    # Generate newsletter
    print("  Generating newsletter...")
    from newsletter import generate_newsletter

    # Load the updated champion state directly from champion.json
    champ_state = load_json(os.path.join(BASE_DIR, "saves", "champion.json"))
    print(f"    Using champion: {champ_state.get('name')} (ID {champ_state.get('warrior_id')})")

    # Load actual turn 6 data through league_server logic
    print("  Loading turn 6 results from server...")
    from league_server import _load_uploads, _load_config

    turn_uploads = _load_uploads(turn_num)
    card = []
    deaths = []

    # Extract all bouts and deaths from uploads
    for mid, upload_data in turn_uploads.items():
        bouts = upload_data.get("bouts", [])
        card.extend(bouts)

        deaths_data = upload_data.get("deaths", [])
        deaths.extend(deaths_data)

    print(f"    Processing {len(card)} bouts")

    # Generate newsletter
    newsletter_text = generate_newsletter(
        turn_num=turn_num,
        card=card,
        teams=teams,
        deaths=deaths,
        champion_state=champ_state,
        processed_date=None,
        is_new_champion=False,
    )

    # Write newsletter
    turn_dir = os.path.join(BASE_DIR, "saves", "league", f"turn_{turn_num:04d}")
    nl_path = os.path.join(turn_dir, "newsletter.txt")
    with open(nl_path, "w", encoding="utf-8") as f:
        f.write(newsletter_text)

    print(f"  Written to {nl_path}")

    # Push to GitHub
    try:
        from github_push import push_to_github_pages
        # Read the newsletter file
        with open(nl_path, "r", encoding="utf-8") as f:
            nl_content = f.read()

        push_to_github_pages({"turn_6_newsletter.html": nl_content})
        print("  Pushed to GitHub Pages")
    except Exception as e:
        print(f"  Warning: GitHub push failed: {e}")

    print("\n[OK] Turn 6 newsletter regenerated successfully!")
    print(f"  Champion: {champ_state.get('name')} from {champ_state.get('team_name')}")

if __name__ == "__main__":
    main()
