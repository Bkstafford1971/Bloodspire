#!/usr/bin/env python3
"""
Regenerate turn 6 newsletter using ACTUAL fight results from result JSON files.
"""

import os
import sys
import json
import glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def main():
    print("Regenerating turn 6 newsletter with ACTUAL fight results...")

    turn_num = 6
    print(f"  Turn: {turn_num}")

    # Load config and teams
    from league_server import _load_config
    from save import load_all_teams, load_champion_state

    cfg = _load_config()
    all_teams = load_all_teams()
    print(f"    Loaded {len(all_teams)} teams")

    # Load champion state
    champ_state = load_champion_state()
    print(f"  Champion: {champ_state.get('name')} (ID {champ_state.get('warrior_id')})")

    # Load actual turn 6 fight results from result JSON files
    print(f"  Loading turn 6 fight results...")
    turn_dir = os.path.join(BASE_DIR, "saves", "league", f"turn_{turn_num:04d}")
    result_files = sorted(glob.glob(os.path.join(turn_dir, "result_*.json")))

    card = []
    all_deaths = []

    for result_file in result_files:
        result_data = load_json(result_file)

        # Extract bouts with results
        bouts = result_data.get("bouts", [])
        for bout_data in bouts:
            card.append(bout_data)

        # Extract deaths
        deaths = result_data.get("deaths", [])
        for death in deaths:
            all_deaths.append(death)

    print(f"    Loaded {len(card)} bouts with results")
    print(f"    Loaded {len(all_deaths)} deaths")

    # Generate the newsletter
    print("  Generating newsletter...")
    from newsletter import generate_newsletter
    import datetime

    newsletter_text = generate_newsletter(
        turn_num=turn_num,
        card=card,
        teams=all_teams,
        deaths=all_deaths,
        champion_state=champ_state,
        processed_date=datetime.date.today().strftime("%m/%d/%Y"),
        is_new_champion=False,
    )

    # Write newsletter
    nl_path = os.path.join(turn_dir, "newsletter.txt")

    # Make writable
    if os.path.exists(nl_path):
        os.chmod(nl_path, 0o644)

    with open(nl_path, "w", encoding="utf-8") as f:
        f.write(newsletter_text)

    print(f"  Written to {nl_path}")

    # Push to GitHub
    try:
        from github_push import push_to_github_pages
        push_to_github_pages({"turn_6_newsletter.html": newsletter_text})
        print("  Pushed to GitHub Pages")
    except Exception as e:
        print(f"  Warning: GitHub push failed: {e}")

    print(f"\n[OK] Turn 6 newsletter regenerated with {len(card)} actual fight results!")
    print(f"  Champion: {champ_state.get('name')} from {champ_state.get('team_name')}")

if __name__ == "__main__":
    main()
