#!/usr/bin/env python3
"""
Rebuild corrupted team files for manager 25 using fight result data.
Reconstructs complete warrior stats from turn 1, 2, and 3 result files.
"""

import json
import os
from pathlib import Path

LEAGUE_DIR = r"C:\BPClone_Claude\saves\league"
TEAMS_DIR = r"C:\BPClone_Claude\saves\teams"

# Teams to rebuild for manager 25
MANAGER_ID = "25"
TEAMS_TO_REBUILD = {
    55: "team_0055.json",
    56: "team_0056.json",
    59: "team_0059.json",
    63: "team_0063.json",
    71: "team_0071.json",
}

def load_json(path):
    """Load JSON file, handling protected files."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  ERROR loading {path}: {e}")
        return None

def get_latest_result(team_id):
    """Load the most recent result file for a team (turn 3, then 2, then 1)."""
    for turn in [3, 2, 1]:
        result_path = os.path.join(
            LEAGUE_DIR,
            f"turn_{turn:04d}",
            f"result_{MANAGER_ID}_team{team_id}_team{team_id}.json"
        )
        if os.path.exists(result_path):
            result = load_json(result_path)
            if result:
                print(f"  Loaded turn {turn} result for team {team_id}")
                return result, turn

    print(f"  ERROR: No result file found for team {team_id}")
    return None, None

def rebuild_team_file(team_id, team_filename):
    """Rebuild a team file from its result files across turns 1-3."""
    print(f"\n{'='*60}")
    print(f"Rebuilding Team {team_id}")
    print(f"{'='*60}")

    # Get the latest result file (most recent turn)
    result_data, latest_turn = get_latest_result(team_id)
    if not result_data:
        print(f"  SKIPPED: Could not find any result file")
        return False

    # Extract team data from result
    team_data = result_data.get("team", {})
    if not team_data:
        print(f"  ERROR: No team data in result file")
        return False

    print(f"  Team name: {team_data.get('team_name', '?')}")
    print(f"  Warriors: {len(team_data.get('warriors', []))}")

    # Ensure all required fields exist
    if "warriors" not in team_data:
        team_data["warriors"] = []
    if "archived_warriors" not in team_data:
        team_data["archived_warriors"] = []

    # Print warrior reconstruction summary
    for warrior in team_data.get("warriors", []):
        if not warrior:
            continue
        name = warrior.get("name", "?")
        wins = warrior.get("wins", 0)
        losses = warrior.get("losses", 0)
        kills = warrior.get("kills", 0)
        total = warrior.get("total_fights", 0)
        print(f"    {name}: {wins}W-{losses}L-{kills}K ({total} total)")

        # Verify fight_history exists
        if "fight_history" not in warrior:
            warrior["fight_history"] = []
        print(f"      - Fight history: {len(warrior.get('fight_history', []))} fights")

        # Check for skills
        skills = warrior.get("skills", {})
        trained_skills = [s for s, lvl in skills.items() if lvl > 0]
        if trained_skills:
            print(f"      - Skills: {', '.join(trained_skills)}")

        # Check for attribute gains
        attr_gains = warrior.get("attribute_gains", {})
        total_gains = sum(attr_gains.values())
        if total_gains > 0:
            print(f"      - Attribute gains: {attr_gains}")

        # Check for injuries
        injuries = warrior.get("injuries", {})
        injured_parts = [k for k, v in injuries.items() if v > 0]
        if injured_parts:
            print(f"      - Injuries: {injured_parts}")

    # Write the corrected team file
    output_path = os.path.join(TEAMS_DIR, team_filename)
    try:
        os.makedirs(TEAMS_DIR, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(team_data, f, indent=2, default=str)
        print(f"\n  WRITTEN: {output_path}")
        return True
    except Exception as e:
        print(f"  ERROR writing {output_path}: {e}")
        return False

def main():
    """Rebuild all team files for manager 25."""
    print(f"\nTEAM RECONSTRUCTION FOR MANAGER {MANAGER_ID}")
    print(f"Source: {LEAGUE_DIR}")
    print(f"Target: {TEAMS_DIR}")

    success_count = 0
    for team_id, filename in TEAMS_TO_REBUILD.items():
        if rebuild_team_file(team_id, filename):
            success_count += 1

    print(f"\nSUMMARY: {success_count}/{len(TEAMS_TO_REBUILD)} teams rebuilt\n")

if __name__ == "__main__":
    main()
