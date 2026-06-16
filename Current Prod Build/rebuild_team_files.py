#!/usr/bin/env python3
"""
Rebuild actual team files from turn result files.
Updates warrior records (W-L-K) and training data for teams 55, 56, 59, 63, 71.
"""

import json
import os
import sys
from typing import Dict, List, Any
import re

TEAMS_DIR = os.path.join(os.path.dirname(__file__), "node_modules", "saves", "teams")
LEAGUE_DIR = os.path.join(os.path.dirname(__file__), "saves", "league")
TEAMS_TO_REBUILD = [55, 56, 59, 63, 71]

def parse_training_line(line: str) -> Dict[str, Any]:
    """Parse a training message to extract attribute and new value."""
    # Format: "Constitution trained: 12 → 13 (45% chance)" with Unicode arrow
    match = re.search(r"(\w+) trained: (\d+) . (\d+)", line)
    if match:
        attr = match.group(1)
        old_val = int(match.group(2))
        new_val = int(match.group(3))
        return {"attribute": attr, "old": old_val, "new": new_val}
    return None

def rebuild_team(team_id: int) -> bool:
    """Rebuild a single team from turn result files."""
    print(f"\n=== Rebuilding Team {team_id} ===")

    # Load the actual team file
    team_file = os.path.join(TEAMS_DIR, f"team_{team_id:04d}.json")

    if not os.path.exists(team_file):
        print(f"  ERROR: Team file not found at {team_file}")
        return False

    print(f"  Found team file: {os.path.basename(team_file)}")

    with open(team_file, 'r') as f:
        team_data = json.load(f)

    # Process both turns
    for turn in [1, 2]:
        turn_dir = os.path.join(LEAGUE_DIR, f"turn_{turn:04d}")

        if not os.path.exists(turn_dir):
            print(f"  Turn {turn} directory not found")
            continue

        # Find result file for this team in this turn
        result_file = None
        for fname in os.listdir(turn_dir):
            if fname.startswith(f"result_") and f"_team{team_id}_team{team_id}.json" in fname:
                result_file = os.path.join(turn_dir, fname)
                break

        if not result_file:
            print(f"  No result file for turn {turn}")
            continue

        print(f"  Processing turn {turn}...")

        with open(result_file, 'r') as f:
            result_data = json.load(f)

        # Process each bout
        for bout in result_data.get("bouts", []):
            warrior_name = bout.get("warrior_name")

            # Find warrior in team
            warrior = None
            for w in team_data.get("warriors", []):
                if w and w.get("name") == warrior_name:
                    warrior = w
                    break

            if not warrior:
                print(f"    WARNING: Warrior '{warrior_name}' not found in team")
                continue

            # Update W-L-K record based on fight result
            result = bout.get("result", "").upper()
            if result == "WIN":
                warrior["wins"] = warrior.get("wins", 0) + 1
                print(f"    {warrior_name}: WIN (now {warrior['wins']} total)")
            elif result == "LOSS":
                warrior["losses"] = warrior.get("losses", 0) + 1
                print(f"    {warrior_name}: LOSS (now {warrior['losses']} total)")

            warrior["kills"] = warrior.get("kills", 0) + bout.get("kills", 0)

            # Process training - parse and apply attribute increases
            for training_msg in bout.get("training", []):
                training_info = parse_training_line(training_msg)
                if training_info:
                    attr = training_info["attribute"].lower()
                    # Map to full attribute names as stored in warrior JSON
                    attr_map = {
                        "constitution": "constitution",
                        "strength": "strength",
                        "dexterity": "dexterity",
                        "intelligence": "intelligence",
                        "presence": "presence",
                        "size": "size"
                    }
                    if attr in attr_map:
                        attr_key = attr_map[attr]
                        if attr_key in warrior:
                            warrior[attr_key] = training_info["new"]
                            print(f"    {warrior_name}: {attr.upper()} -> {training_info['new']}")

    # Save updated team file (remove read-only flag first)
    import stat
    try:
        os.chmod(team_file, stat.S_IWRITE)
    except:
        pass

    with open(team_file, 'w') as f:
        json.dump(team_data, f, indent=2)

    print(f"  SAVED: {os.path.basename(team_file)}")
    return True

def main():
    """Rebuild all specified teams."""
    print(f"Rebuilding teams from {LEAGUE_DIR}")

    success_count = 0
    for team_id in TEAMS_TO_REBUILD:
        try:
            if rebuild_team(team_id):
                success_count += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n=== Summary ===")
    print(f"Successfully rebuilt {success_count}/{len(TEAMS_TO_REBUILD)} teams")

if __name__ == "__main__":
    main()
