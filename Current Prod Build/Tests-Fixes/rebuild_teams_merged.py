#!/usr/bin/env python3
"""
Rebuild corrupted team files with MERGED fight history from turns 1, 2, and 3.
"""

import json
import os
import sys

# Force UTF-8 output
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

LEAGUE_DIR = r"C:\BPClone_Claude\saves\league"
TEAMS_DIR = r"C:\BPClone_Claude\saves\teams"

MANAGER_ID = "25"
TEAMS_TO_REBUILD = {
    55: "team_0055.json",
    56: "team_0056.json",
    59: "team_0059.json",
    63: "team_0063.json",
    71: "team_0071.json",
}

def load_json(path):
    """Load JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  ERROR loading {path}: {e}")
        return None

def get_result_for_turn(team_id, turn_num):
    """Load result file for a specific turn."""
    result_path = os.path.join(
        LEAGUE_DIR,
        f"turn_{turn_num:04d}",
        f"result_{MANAGER_ID}_team{team_id}_team{team_id}.json"
    )
    if os.path.exists(result_path):
        return load_json(result_path)
    return None

def merge_fight_histories(team_id):
    """Load and merge fight history from turns 1, 2, and 3."""
    all_fights = {}  # warrior_name -> list of fights
    
    # Load results from each turn in order
    for turn in [1, 2, 3]:
        result = get_result_for_turn(team_id, turn)
        if not result:
            continue
        
        print(f"    Turn {turn}: Found result file")
        
        # Extract fight history from the team object
        team_data = result.get("team", {})
        for warrior in team_data.get("warriors", []):
            if not warrior:
                continue
            
            name = warrior.get("name", "?")
            fight_hist = warrior.get("fight_history", [])
            
            if name not in all_fights:
                all_fights[name] = []
            
            # Add fights from this turn (avoid duplicates by checking fight_id)
            existing_ids = {f.get("fight_id") for f in all_fights[name]}
            for fight in fight_hist:
                if fight.get("fight_id") not in existing_ids:
                    all_fights[name].append(fight)
                    existing_ids.add(fight.get("fight_id"))
    
    return all_fights

def rebuild_team_file(team_id, team_filename):
    """Rebuild team file with merged fight history from all turns."""
    print(f"\n{'='*60}")
    print(f"Rebuilding Team {team_id}")
    print(f"{'='*60}")
    
    # Use turn 3 as base (has latest stats)
    result_data = get_result_for_turn(team_id, 3)
    if not result_data:
        # Fallback to turn 2
        result_data = get_result_for_turn(team_id, 2)
    if not result_data:
        # Fallback to turn 1
        result_data = get_result_for_turn(team_id, 1)
    
    if not result_data:
        print(f"  ERROR: No result file found")
        return False
    
    team_data = result_data.get("team", {})
    if not team_data:
        print(f"  ERROR: No team data in result file")
        return False
    
    print(f"  Team: {team_data.get('team_name', '?')}")
    print(f"  Merging fight history from turns 1, 2, and 3...")
    
    # Get merged fight history from all turns
    merged_fights = merge_fight_histories(team_id)
    
    # Update each warrior with merged fight history
    for warrior in team_data.get("warriors", []):
        if not warrior:
            continue
        
        name = warrior.get("name", "?")
        if name in merged_fights:
            warrior["fight_history"] = sorted(
                merged_fights[name],
                key=lambda f: (f.get("turn", 0), f.get("fight_id", 0))
            )
    
    # Ensure archived_warriors exists
    if "archived_warriors" not in team_data:
        team_data["archived_warriors"] = []
    
    # Print summary
    for warrior in team_data.get("warriors", []):
        if not warrior:
            continue
        
        name = warrior.get("name", "?")
        wins = warrior.get("wins", 0)
        losses = warrior.get("losses", 0)
        kills = warrior.get("kills", 0)
        fights = len(warrior.get("fight_history", []))
        
        print(f"    {name}: {wins}W-{losses}L-{kills}K ({fights} fights in history)")
    
    # Write the corrected team file
    output_path = os.path.join(TEAMS_DIR, team_filename)
    try:
        os.makedirs(TEAMS_DIR, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(team_data, f, indent=2, default=str)
        print(f"\n  [OK] WRITTEN: {output_path}")
        return True
    except Exception as e:
        print(f"  ERROR writing {output_path}: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print(f"\nTEAM REBUILD WITH MERGED FIGHT HISTORY")
    print(f"Source: {LEAGUE_DIR}")
    print(f"Target: {TEAMS_DIR}")
    
    # Make files writable first
    print("\nMaking team files writable...")
    for filename in TEAMS_TO_REBUILD.values():
        filepath = os.path.join(TEAMS_DIR, filename)
        if os.path.exists(filepath):
            try:
                import stat
                os.chmod(filepath, stat.S_IWRITE)
            except:
                pass
    
    success_count = 0
    for team_id, filename in TEAMS_TO_REBUILD.items():
        if rebuild_team_file(team_id, filename):
            success_count += 1
    
    print(f"\nSUMMARY: {success_count}/{len(TEAMS_TO_REBUILD)} teams rebuilt\n")

if __name__ == "__main__":
    main()
