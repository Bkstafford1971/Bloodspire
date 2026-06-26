#!/usr/bin/env python3
"""
Recalculate win/loss/kill records based on actual fight history.
"""

import json
import os
import stat

TEAMS_DIR = r"C:\BPClone_Claude\saves\teams"

TEAMS_TO_FIX = [
    "team_0055.json",
    "team_0056.json",
    "team_0059.json",
    "team_0063.json",
    "team_0071.json",
]

def recalculate_records(team_data):
    """Recalculate wins, losses, and kills based on fight_history."""
    changes_made = False
    
    # Process active warriors
    for warrior in team_data.get("warriors", []):
        if not warrior:
            continue
        
        name = warrior.get("name", "?")
        fights = warrior.get("fight_history", [])
        
        # Calculate from fights
        new_wins = sum(1 for f in fights if f.get("result", "").lower() == "win")
        new_losses = sum(1 for f in fights if f.get("result", "").lower() == "loss")
        new_kills = sum(1 for f in fights if f.get("opponent_slain", False))
        
        # Check if different
        old_wins = warrior.get("wins", 0)
        old_losses = warrior.get("losses", 0)
        old_kills = warrior.get("kills", 0)
        
        if old_wins != new_wins or old_losses != new_losses or old_kills != new_kills:
            changes_made = True
            print(f"    {name}: {old_wins}W-{old_losses}L-{old_kills}K -> {new_wins}W-{new_losses}L-{new_kills}K")
            warrior["wins"] = new_wins
            warrior["losses"] = new_losses
            warrior["kills"] = new_kills
        else:
            print(f"    {name}: {new_wins}W-{new_losses}L-{new_kills}K (unchanged)")
    
    # Process archived warriors
    for warrior in team_data.get("archived_warriors", []):
        if not warrior:
            continue
        
        name = warrior.get("name", "?")
        fights = warrior.get("fight_history", [])
        
        new_wins = sum(1 for f in fights if f.get("result", "").lower() == "win")
        new_losses = sum(1 for f in fights if f.get("result", "").lower() == "loss")
        new_kills = sum(1 for f in fights if f.get("opponent_slain", False))
        
        old_wins = warrior.get("wins", 0)
        old_losses = warrior.get("losses", 0)
        old_kills = warrior.get("kills", 0)
        
        if old_wins != new_wins or old_losses != new_losses or old_kills != new_kills:
            changes_made = True
            print(f"    {name} (archived): {old_wins}W-{old_losses}L-{old_kills}K -> {new_wins}W-{new_losses}L-{new_kills}K")
            warrior["wins"] = new_wins
            warrior["losses"] = new_losses
            warrior["kills"] = new_kills
        else:
            print(f"    {name} (archived): {new_wins}W-{new_losses}L-{new_kills}K (unchanged)")
    
    return changes_made

def fix_team_file(filename):
    """Fix win/loss/kill records for a team file."""
    filepath = os.path.join(TEAMS_DIR, filename)
    
    print(f"\nProcessing: {filename}")
    
    # Make writable
    try:
        os.chmod(filepath, stat.S_IWRITE)
    except:
        pass
    
    # Load
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            team_data = json.load(f)
    except Exception as e:
        print(f"  ERROR loading: {e}")
        return False
    
    team_name = team_data.get("team_name", "?")
    print(f"  Team: {team_name}")
    
    # Recalculate
    if recalculate_records(team_data):
        # Save
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(team_data, f, indent=2, default=str)
            print(f"  [SAVED] Records updated")
            
            # Make read-only
            os.chmod(filepath, stat.S_IREAD)
            return True
        except Exception as e:
            print(f"  ERROR saving: {e}")
            return False
    else:
        print(f"  [UNCHANGED] All records correct")
        os.chmod(filepath, stat.S_IREAD)
        return True

def main():
    print(f"\n{'='*60}")
    print(f"RECALCULATING WIN/LOSS/KILL RECORDS")
    print(f"{'='*60}")
    
    success_count = 0
    for filename in TEAMS_TO_FIX:
        if fix_team_file(filename):
            success_count += 1
    
    print(f"\n{'='*60}")
    print(f"SUMMARY: {success_count}/{len(TEAMS_TO_FIX)} teams processed")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
