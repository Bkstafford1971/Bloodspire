#!/usr/bin/env python3
"""
Simple turn 6 newsletter regeneration using properly loaded champion state.
"""

import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

def main():
    print("Regenerating turn 6 newsletter...")

    turn_num = 6

    # Import after path setup
    from save import load_champion_state, load_all_teams
    from league_server import _load_config, _load_uploads

    # 1. Load the champion state (now correctly has Impending Doom)
    champ_state = load_champion_state()
    print(f"  Champion state: {champ_state}")

    if not champ_state.get("name"):
        print("  ERROR: Champion state is empty!")
        return False

    # 2. Load all teams
    all_teams = load_all_teams()
    print(f"  Loaded {len(all_teams)} teams")

    # 3. Load turn 6 uploads
    uploads = _load_uploads(turn_num)
    print(f"  Loaded {len(uploads)} uploads")

    # 4. Load turn 6 newsletter that user manually fixed
    turn_dir = os.path.join(BASE_DIR, "saves", "league", f"turn_{turn_num:04d}")
    nl_path = os.path.join(turn_dir, "newsletter.txt")

    # Read the current (manually fixed) newsletter
    if os.path.exists(nl_path):
        with open(nl_path, 'r', encoding='utf-8') as f:
            current_nl = f.read()
        print(f"  Read current newsletter ({len(current_nl)} chars)")
    else:
        print("  ERROR: Newsletter file not found!")
        return False

    # 5. Extract the fight results from uploads to build a proper card
    # Simpler approach: just extract basic bout data
    card = []
    all_deaths = []

    for mid, upload_data in uploads.items():
        bouts = upload_data.get("bouts", [])
        card.extend(bouts)

        deaths = upload_data.get("deaths", [])
        all_deaths.extend(deaths)

    print(f"  Found {len(card)} bouts and {len(all_deaths)} deaths")

    # 6. Generate newsletter with champion state
    print("  Generating newsletter with champion state...")
    from newsletter import generate_newsletter
    import datetime

    try:
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
        os.chmod(nl_path, 0o644)
        with open(nl_path, "w", encoding="utf-8") as f:
            f.write(newsletter_text)

        print(f"  [OK] Written to {nl_path}")

        # Push to GitHub
        try:
            from github_push import push_to_github_pages
            push_to_github_pages({"turn_6_newsletter.html": newsletter_text})
            print("  [OK] Pushed to GitHub Pages")
        except Exception as e:
            print(f"  [WARN] GitHub push failed: {e}")

        print(f"\n[OK] Turn 6 newsletter regenerated successfully!")
        print(f"  Champion: {champ_state.get('name')} from {champ_state.get('team_name')}")
        return True

    except Exception as e:
        print(f"  ERROR during generation: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if main():
        print("\n[OK] Done")
    else:
        print("\n[FAILED] Could not regenerate newsletter")
        sys.exit(1)
