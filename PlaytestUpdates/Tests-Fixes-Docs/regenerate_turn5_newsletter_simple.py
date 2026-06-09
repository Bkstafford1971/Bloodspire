#!/usr/bin/env python3
"""
Regenerate turn 5 newsletter from actual turn 5 results
with corrected standings data.
"""

import os
import sys
import json
import glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

TURN_NUM = 5
TURN_DIR = os.path.join(BASE_DIR, "saves", "league", f"turn_{TURN_NUM:04d}")
NEWSLETTER_PATH = os.path.join(TURN_DIR, "newsletter.txt")

def load_json(path):
    """Load JSON file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ERROR loading {path}: {e}")
        return {}

def regenerate():
    """Regenerate newsletter by loading results and calling newsletter code."""
    print(f"Regenerating Turn {TURN_NUM} newsletter...")

    try:
        # Import after path is set
        from newsletter import generate_newsletter

        # Load all result files to get fights and teams
        result_files = sorted(glob.glob(os.path.join(TURN_DIR, "result_*.json")))
        print(f"  Found {len(result_files)} result files")

        all_results = {}
        for filepath in result_files:
            data = load_json(filepath)
            if data:
                # Use manager_name if manager_id not available
                manager_id = data.get("manager_id") or data.get("manager_name")
                if manager_id:
                    all_results[manager_id] = data

        print(f"  Loaded {len(all_results)} manager records")

        # Extract data for newsletter generation
        card = []  # Fight card (bouts)
        teams = []  # Team data
        deaths = []  # Deaths

        for manager_id, res in all_results.items():
            # Collect bouts
            bouts = res.get("bouts", [])
            print(f"    {manager_id}: {len(bouts)} bouts")
            for bout in bouts:
                card.append(bout)

            # Collect team data
            team_data = res.get("team")
            if team_data:
                teams.append(team_data)

        print(f"  Loaded {len(card)} bouts and {len(teams)} teams")

        # Generate newsletter
        # Provide default champion_state if missing
        champion_state = {
            "name": "",
            "manager": "",
            "wins": 0,
            "streak": 0
        }

        newsletter_content = generate_newsletter(
            turn_num=TURN_NUM,
            card=card,
            teams=teams,
            deaths=deaths,
            champion_state=champion_state,
            processed_date=None,
            is_new_champion=False
        )

        # Write newsletter
        with open(NEWSLETTER_PATH, 'w', encoding='utf-8') as f:
            f.write(newsletter_content)

        print(f"  Successfully wrote {NEWSLETTER_PATH}")
        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if regenerate():
        print("\nNewsletter regenerated successfully!")
    else:
        print("\nFailed to regenerate newsletter.")
