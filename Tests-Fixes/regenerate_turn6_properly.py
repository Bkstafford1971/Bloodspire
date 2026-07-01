#!/usr/bin/env python3
"""
Regenerate turn 6 newsletter properly using league_server's actual processing flow.
"""

import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

def main():
    print("Regenerating turn 6 newsletter using proper league_server flow...")

    turn_num = 6
    print(f"  Turn: {turn_num}")

    # Import league_server functions
    from league_server import _load_config, _load_uploads, _load_standings

    # Load config
    cfg = _load_config()
    print(f"  Current turn from config: {cfg.get('current_turn')}")

    # Load all uploads for turn 6
    print(f"  Loading uploads for turn {turn_num}...")
    uploads = _load_uploads(turn_num)
    print(f"    Loaded {len(uploads)} uploads")

    # Load all teams
    print("  Loading all teams...")
    from save import load_all_teams
    all_teams = load_all_teams()
    print(f"    Loaded {len(all_teams)} teams")

    # Build team_map like league_server does
    team_map = {}
    for team in all_teams:
        key = f"{team.manager_id}_{team.team_id}" if hasattr(team, 'manager_id') else str(team.team_id)
        team_map[key] = team

    # Load deaths
    print("  Collecting death records...")
    deaths_nl = []
    for mid, res in uploads.items():
        for death in res.get("deaths", []):
            deaths_nl.append(death)
    print(f"    Found {len(deaths_nl)} deaths")

    # Build the fight card using league_server's approach
    print("  Building fight card...")
    from matchmaking import build_global_fight_card
    from save import load_champion_state

    champ_state = load_champion_state()
    print(f"    Champion: {champ_state.get('name')} (ID {champ_state.get('warrior_id')})")

    # Collect all player teams from uploads
    all_player_teams = []
    for mid, upload_data in uploads.items():
        team_data = upload_data.get("team")
        if team_data:
            # Find the actual Team object for this data
            team_id = team_data.get("team_id")
            for team in all_teams:
                if team.team_id == team_id:
                    all_player_teams.append(team)
                    break

    print(f"    Found {len(all_player_teams)} player teams")

    # Build global fight card
    global_card = build_global_fight_card(
        player_teams=all_player_teams,
        opponent_teams=[],
        champion_state=champ_state
    )
    print(f"    Built global card with {len(global_card)} potential bouts")

    # Filter to only bouts with results (like league_server does)
    fake_card = [f for f in global_card if f.result is not None]
    print(f"    Filtered to {len(fake_card)} bouts with results")

    # Now generate the newsletter
    print("  Generating newsletter...")
    from newsletter import generate_newsletter
    import datetime

    newsletter_text = generate_newsletter(
        turn_num=turn_num,
        card=fake_card,
        teams=all_teams,
        deaths=deaths_nl,
        champion_state=champ_state,
        processed_date=datetime.date.today().strftime("%m/%d/%Y"),
        is_new_champion=False,
    )

    # Write newsletter
    turn_dir = os.path.join(BASE_DIR, "saves", "league", f"turn_{turn_num:04d}")
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

    print(f"\n[OK] Turn 6 newsletter regenerated with {len(fake_card)} bouts processed!")
    print(f"  Champion: {champ_state.get('name')} from {champ_state.get('team_name')}")

if __name__ == "__main__":
    main()
