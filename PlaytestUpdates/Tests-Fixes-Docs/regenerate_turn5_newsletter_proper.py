#!/usr/bin/env python3
"""
Properly regenerate turn 5 newsletter from actual turn 5 fight results
using the league_server's generate_newsletter function.
"""

import os
import sys
import json
import glob

# Add the project to path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from league_server import (
    _load_standings, _load_json, _turn_dir,
    load_teams_by_manager_id, load_team_by_id
)
from newsletter import generate_newsletter

TURN_NUM = 5
TURN_DIR = _turn_dir(TURN_NUM)
NEWSLETTER_PATH = os.path.join(TURN_DIR, "newsletter.txt")
STANDINGS_PATH = os.path.join(BASE_DIR, "saves", "league", "standings.json")

def load_turn_results():
    """Load all result files for the turn."""
    results = {}
    result_files = sorted(glob.glob(os.path.join(TURN_DIR, "result_*.json")))

    for filepath in result_files:
        try:
            data = _load_json(filepath)
            if data:
                manager_id = data.get("manager_id")
                if manager_id:
                    results[manager_id] = data
        except Exception as e:
            print(f"  WARNING: Could not load {filepath}: {e}")

    return results

def regenerate_newsletter():
    """Regenerate the turn 5 newsletter."""
    print(f"Regenerating Turn {TURN_NUM} newsletter with corrected career records...")

    # Load all result data
    all_results = load_turn_results()
    print(f"  Loaded {len(all_results)} team results")

    if not all_results:
        print("  ERROR: No turn results found")
        return False

    # Reconstruct fight card from results
    fights = []
    for manager_id, res in all_results.items():
        bouts = res.get("bouts", [])
        for bout in bouts:
            fights.append(bout)

    print(f"  Reconstructed {len(fights)} fights")

    # Load teams
    teams = []
    for manager_id, res in all_results.items():
        team_data = res.get("team")
        if team_data:
            teams.append(team_data)

    print(f"  Loaded {len(teams)} teams")

    # Load standings (which now has corrected career data)
    standings = _load_standings()

    # Try to call generate_newsletter
    try:
        newsletter_content = generate_newsletter(
            turn_num=TURN_NUM,
            card=fights,
            teams=teams,
            deaths=[],  # Deaths would need to be tracked separately
            champion_state=None,
            processed_date=None,
            is_new_champion=False
        )

        # Write the newsletter
        with open(NEWSLETTER_PATH, 'w', encoding='utf-8') as f:
            f.write(newsletter_content)

        print(f"  Successfully regenerated {NEWSLETTER_PATH}")
        return True

    except Exception as e:
        print(f"  ERROR generating newsletter: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = regenerate_newsletter()
    if success:
        print("\nNewsletter regenerated successfully!")
    else:
        print("\nFailed to regenerate newsletter.")
