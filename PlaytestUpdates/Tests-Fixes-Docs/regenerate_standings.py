#!/usr/bin/env python3
"""
Regenerate standings.json from persistent team data.
This rebuilds the standings database from the actual team files in saves/teams.
"""

import os
import json
import glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEAMS_DIR = os.path.join(BASE_DIR, "saves", "teams")
LEAGUE_DIR = os.path.join(BASE_DIR, "saves", "league")
STANDINGS_PATH = os.path.join(LEAGUE_DIR, "standings.json")

def load_json(path):
    """Load JSON file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ERROR loading {path}: {e}")
        return {}

def save_json(path, data):
    """Save JSON file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        print(f"  Saved {path}")
    except Exception as e:
        print(f"  ERROR saving {path}: {e}")

def regenerate_standings():
    """Regenerate standings from team files."""
    print("Regenerating standings.json from persistent team data...")

    standings = {}
    teams_processed = 0

    # Find all team files
    team_files = sorted(glob.glob(os.path.join(TEAMS_DIR, "team_*.json")))
    print(f"  Found {len(team_files)} team files")

    for team_file in team_files:
        try:
            team_data = load_json(team_file)
            if not team_data:
                continue

            team_id = team_data.get("team_id")
            team_name = team_data.get("team_name", "?")
            manager_name = team_data.get("manager_name", "?")

            # Skip NPC/AI teams
            if manager_name == "?" or manager_name.startswith("ai_"):
                continue

            # Create standings entry key
            standings_key = f"{team_id}_{team_name}"

            if standings_key not in standings:
                standings[standings_key] = {
                    "team_id": team_id,
                    "team_name": team_name,
                    "manager_name": manager_name,
                    "turns_played": team_data.get("turns_played", 0),
                    "warriors": {},
                    "is_ai": False,
                    "turns_counted": team_data.get("turns_counted", [])
                }

            entry = standings[standings_key]

            # Add warrior stats from active warriors
            warriors = team_data.get("warriors", [])
            for warrior in warriors:
                if not warrior:
                    continue

                wid = warrior.get("warrior_id")
                wname = warrior.get("name", "?")

                standings_warrior_key = str(wid) if wid else wname

                if standings_warrior_key not in entry["warriors"]:
                    entry["warriors"][standings_warrior_key] = {
                        "wins": 0,
                        "losses": 0,
                        "kills": 0,
                        "fights": 0
                    }

                ws = entry["warriors"][standings_warrior_key]
                ws["name"] = wname
                ws["warrior_id"] = wid
                ws["wins"] = warrior.get("wins", 0)
                ws["losses"] = warrior.get("losses", 0)
                ws["kills"] = warrior.get("kills", 0)
                ws["fights"] = warrior.get("total_fights", 0)

            # Add warrior stats from archived warriors
            archived = team_data.get("archived_warriors", [])
            for warrior in archived:
                if not warrior:
                    continue

                wid = warrior.get("warrior_id")
                wname = warrior.get("name", "?")

                standings_warrior_key = str(wid) if wid else wname

                if standings_warrior_key not in entry["warriors"]:
                    entry["warriors"][standings_warrior_key] = {
                        "wins": 0,
                        "losses": 0,
                        "kills": 0,
                        "fights": 0
                    }

                ws = entry["warriors"][standings_warrior_key]
                ws["name"] = wname
                ws["warrior_id"] = wid
                ws["wins"] = warrior.get("wins", 0)
                ws["losses"] = warrior.get("losses", 0)
                ws["kills"] = warrior.get("kills", 0)
                ws["fights"] = warrior.get("total_fights", 0)

            teams_processed += 1

        except Exception as e:
            print(f"  WARNING: Error processing {team_file}: {e}")
            continue

    # Save the regenerated standings
    save_json(STANDINGS_PATH, standings)
    print(f"\n  Regenerated standings for {teams_processed} teams")
    print(f"  Total teams in standings: {len(standings)}")

if __name__ == "__main__":
    regenerate_standings()
