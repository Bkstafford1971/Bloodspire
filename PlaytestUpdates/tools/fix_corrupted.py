#!/usr/bin/env python3
# =============================================================================
# fix_corrupted.py - Easy File Update Tool
# =============================================================================
# User-friendly interface for updating team, warrior, and manager files
# while maintaining proper checksums.
#
# Usage:
#   python fix_corrupted.py --help
#
# Examples:
#   python fix_corrupted.py --team 80 --name "New Team Name"
#   python fix_corrupted.py --team 80 --manager "New Manager Name"
#   python fix_corrupted.py --list-teams        # Show all teams
#   python fix_corrupted.py --fix-all            # Repair all checksums
# =============================================================================

import json
import os
import sys
import argparse
from typing import Optional, Tuple

# Import the file protection and repair functions
from file_protection import make_file_writable, make_file_readonly, save_checksum, load_json_protected, save_json_protected
from file_repair import update_team_file, repair_directory, verify_file

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVES_DIR = os.path.join(BASE_DIR, "saves")
TEAMS_DIR = os.path.join(SAVES_DIR, "teams")
LEAGUE_DIR = os.path.join(SAVES_DIR, "league")


def get_team_filepath(team_id: int) -> str:
    """Get the path to a team's JSON file."""
    return os.path.join(TEAMS_DIR, f"team_{team_id:04d}.json")


def list_all_teams() -> None:
    """Display all available teams."""
    if not os.path.isdir(TEAMS_DIR):
        print("No teams directory found.")
        return

    teams = []
    for filename in sorted(os.listdir(TEAMS_DIR)):
        if filename.startswith("team_") and filename.endswith(".json"):
            try:
                filepath = os.path.join(TEAMS_DIR, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Extract ID from filename or data
                try:
                    tid = int(filename.replace("team_", "").replace(".json", ""))
                except:
                    tid = int(data.get('team_id', 0))

                # Calculate totals for active warriors
                tw = tl = tk = 0
                for w in data.get('warriors', []):
                    if w:
                        tw += w.get('wins', 0)
                        tl += w.get('losses', 0)
                        tk += w.get('kills', 0)
                
                teams.append({
                    'id': tid,
                    'name': data.get('team_name', 'Unknown'),
                    'manager': data.get('manager_name', 'Unknown'),
                    'warriors': len([w for w in data.get('warriors', []) if w]),
                    'record': f"{tw}-{tl}-{tk}"
                })
            except (ValueError, json.JSONDecodeError, IOError):
                pass

    if not teams:
        print("No teams found.")
        return

    print("\n" + "=" * 85)
    print(f"{'ID':>4} {'Team Name':<28} {'Manager':<20} {'Warr':>4} {'Record':>12}")
    print("-" * 85)
    for team in teams:
        print(f"{team['id']:>4} {team['name']:<28} {team['manager']:<20} {team['warriors']:>4} {team['record']:>12}")
    print("=" * 85 + "\n")


def find_dirty_records() -> None:
    """Scan all team files for non-zero records, archived data, or turn history."""
    print("Scanning all server teams for dirty data (non-zero records)...")
    found = False
    for filename in sorted(os.listdir(TEAMS_DIR)):
        if not (filename.startswith("team_") and filename.endswith(".json")):
            continue
        filepath = os.path.join(TEAMS_DIR, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            tid = data.get('team_id', '?')
            mgr = data.get('manager_name', 'Unknown')
            
            # Check for non-zero records or existing history lists
            active_dirty = any(w and (w.get('wins', 0) > 0 or w.get('losses', 0) > 0) for w in data.get('warriors', []))
            archive_dirty = len(data.get('archived_warriors', [])) > 0
            history_dirty = len(data.get('turn_history', [])) > 0

            if active_dirty or archive_dirty or history_dirty:
                if not found:
                    print(f"\n{'TEAM ID':<8} {'MANAGER':<20} {'DIRTY REASON'}")
                    print("-" * 60)
                
                reasons = []
                if active_dirty:  reasons.append("Active Warriors")
                if archive_dirty: reasons.append("Archived Warriors")
                if history_dirty: reasons.append("Turn History")
                
                print(f"{tid:<8} {mgr:<20} {', '.join(reasons)}")
                found = True
        except: continue
    
    if not found:
        print("No dirty records found. All teams on server are clean (0-0-0).")
    print()


def reset_manager_record(manager_id: str) -> None:
    """
    Resets the career record for a specific manager in standings.json
    and forces a client-side reset by updating managers.json.
    """
    print(f"Attempting to reset career record for manager ID: {manager_id}")

    # --- Load and update managers.json ---
    managers_path = os.path.join(LEAGUE_DIR, "managers.json")
    managers_data = {}
    try:
        managers_data = load_json_protected(managers_path, allow_tampered=True)
    except Exception as e:
        print(f"[ERROR] Could not load managers.json: {e}")
        return

    if manager_id not in managers_data:
        print(f"[ERROR] Manager ID {manager_id} not found in managers.json.")
        return

    manager_name = managers_data[manager_id].get("manager_name", "Unknown")
    print(f"  Found manager: {manager_name}")

    # Reset acknowledged_reset_count to force client to re-sync
    config_path = os.path.join(LEAGUE_DIR, "config.json")
    cfg = {}
    try:
        cfg = load_json_protected(config_path, allow_tampered=True)
    except Exception as e:
        print(f"[ERROR] Could not load config.json: {e}")
        pass # Continue without config if it's corrupted, but warn

    current_reset_count = cfg.get("reset_count", 0)
    managers_data[manager_id]["acknowledged_reset_count"] = current_reset_count - 1 # Set to one less to trigger refresh
    save_json_protected(managers_path, managers_data)
    print(f"  Reset 'acknowledged_reset_count' for manager {manager_id} to {current_reset_count - 1}.")

    # --- Load and update standings.json ---
    standings_path = os.path.join(LEAGUE_DIR, "standings.json")
    standings_data = load_json_protected(standings_path, allow_tampered=True)

    if manager_id not in standings_data:
        print(f"[WARNING] Manager ID {manager_id} not found in standings.json. Nothing to reset there.")
        return

    # Reset all warrior records for this manager in standings.json
    mgr_standings = standings_data[manager_id]
    mgr_standings["turns_played"] = 0
    mgr_standings["turns_counted"] = []
    
    # Reset individual warrior records within the manager's standings entry
    for wname, ws in mgr_standings.get("warriors", {}).items():
        ws["wins"] = 0
        ws["losses"] = 0
        ws["kills"] = 0
        ws["fights"] = 0
    
    save_json_protected(standings_path, standings_data)
    print(f"  Successfully reset career record for manager '{manager_name}' (ID: {manager_id}) in standings.json.")
    print("  The client should now show 0-0-0 after checking for updates.")


def list_team_warriors(team_id: int) -> None:
    """Display warriors in a specific team."""
    filepath = get_team_filepath(team_id)

    if not os.path.exists(filepath):
        print(f"Team {team_id:04d} not found.")
        return

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            team_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error reading team file: {e}")
        return

    team_name = team_data.get('team_name', 'Unknown')
    manager = team_data.get('manager_name', 'Unknown')
    warriors = team_data.get('warriors', [])

    print(f"\n{'='*70}")
    print(f"Team {team_id:04d}: {team_name}")
    print(f"Manager: {manager}")
    print(f"{'='*70}")

    if not warriors:
        print("No warriors found.")
        return

    print(f"\n{'Index':<6} {'Name':<25} {'Race':<15} {'Status':<10}")
    print("-" * 70)

    for idx, warrior in enumerate(warriors):
        if warrior is None:
            print(f"{idx:<6} [EMPTY SLOT]")
        else:
            name = warrior.get('name', 'Unknown')
            # Race can be either a dict {'name': 'Human'} or a string 'Human'
            race_data = warrior.get('race', {})
            if isinstance(race_data, dict):
                race = race_data.get('name', 'Unknown')
            else:
                race = str(race_data) if race_data else 'Unknown'
            status = "DEAD" if warrior.get('is_dead', False) else "ACTIVE"
            print(f"{idx:<6} {name:<25} {race:<15} {status:<10}")

    print("=" * 70 + "\n")


def update_team_name(team_id: int, new_name: str) -> None:
    """Update a team's name."""
    filepath = get_team_filepath(team_id)

    if not os.path.exists(filepath):
        print(f"[ERROR] Team {team_id:04d} not found.")
        return

    success, message = update_team_file(filepath, {'team_name': new_name})
    print(f"[{('OK' if success else 'ERROR')}] {message}")


def update_manager_name(team_id: int, new_name: str) -> None:
    """Update a team's manager name."""
    filepath = get_team_filepath(team_id)

    if not os.path.exists(filepath):
        print(f"[ERROR] Team {team_id:04d} not found.")
        return

    success, message = update_team_file(filepath, {'manager_name': new_name})
    print(f"[{('OK' if success else 'ERROR')}] {message}")


def update_warrior_field(team_id: int, warrior_index: int, field: str, value) -> None:
    """Update a specific field in a warrior."""
    filepath = get_team_filepath(team_id)

    if not os.path.exists(filepath):
        print(f"[ERROR] Team {team_id:04d} not found.")
        return

    try:
        # Load current data
        with open(filepath, 'r', encoding='utf-8') as f:
            team_data = json.load(f)

        if 'warriors' not in team_data:
            print(f"[ERROR] Team has no warriors array.")
            return

        if warrior_index >= len(team_data['warriors']):
            print(f"[ERROR] Warrior index {warrior_index} out of range.")
            return

        warrior = team_data['warriors'][warrior_index]
        if warrior is None:
            print(f"[ERROR] Warrior at index {warrior_index} is None.")
            return

        # Update the field
        old_value = warrior.get(field)
        warrior[field] = value

        # Save the file
        make_file_writable(filepath)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(team_data, f, indent=2)
        save_checksum(filepath, team_data)
        make_file_readonly(filepath)

        warrior_name = warrior.get('name', 'Unknown')
        print(f"[OK] Updated {warrior_name}.{field}: {old_value} -> {value}")

    except Exception as e:
        print(f"[ERROR] {e}")


def fix_all_corrupted() -> None:
    """Repair all corrupted files in the save directory."""
    print("Repairing all corrupted files...\n")
    repair_directory(SAVES_DIR)


def main():
    parser = argparse.ArgumentParser(
        description="Easy file update tool for BLOODSPIRE saves",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fix_corrupted.py --list-teams
  python fix_corrupted.py --team 80 --list-warriors
  python fix_corrupted.py --team 80 --name "Dragon Slayers"
  python fix_corrupted.py --team 80 --manager "New Manager"
  python fix_corrupted.py --fix-all
        """
    )

    parser.add_argument('--list-teams', action='store_true',
                        help='Show all saved teams')
    parser.add_argument('--find-dirty', action='store_true',
                        help='Find any teams with non-zero records or history')
    parser.add_argument('--reset-manager-record', metavar='MANAGER_ID',
                        help='Reset career record for a specific manager (in standings.json and managers.json)')
    parser.add_argument('--team', type=int, metavar='ID',
                        help='Target a specific team by ID')
    parser.add_argument('--list-warriors', action='store_true',
                        help='List warriors in a team (use with --team)')
    parser.add_argument('--nuke-records', action='store_true',
                        help='Reset all records, archives, and history for this team to zero')
    parser.add_argument('--name', metavar='NAME',
                        help='Update team name (use with --team)')
    parser.add_argument('--manager', metavar='NAME',
                        help='Update manager name (use with --team)')
    parser.add_argument('--warrior', type=int, metavar='INDEX',
                        help='Target a specific warrior by index (use with --team)')
    parser.add_argument('--warrior-name', metavar='NAME',
                        help='Update warrior name (use with --team and --warrior)')
    parser.add_argument('--warrior-field', metavar='FIELD',
                        help='Update a warrior field (use with --team and --warrior)')
    parser.add_argument('--value', metavar='VALUE',
                        help='Value to set (use with --warrior-field)')
    parser.add_argument('--fix-all', action='store_true',
                        help='Repair checksums for all corrupted files')

    args = parser.parse_args()

    if not any([args.list_teams, args.team, args.fix_all, args.find_dirty, args.reset_manager_record]):
        parser.print_help()
        return

    # Handle --fix-all
    if args.fix_all:
        fix_all_corrupted()
        return

    # Handle --list-teams
    if args.list_teams:
        list_all_teams()
        return
    
    if args.find_dirty:
        find_dirty_records()
        return

    if args.reset_manager_record:
        reset_manager_record(args.reset_manager_record)
        return

    # Handle team operations
    if args.team:
        if args.nuke_records:
            filepath = get_team_filepath(args.team)
            if not os.path.exists(filepath):
                print(f"[ERROR] Team {args.team:04d} not found.")
            else:
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # Reset active warriors
                    for w in data.get('warriors', []):
                        if w:
                            for stat in ['wins', 'losses', 'kills', 'total_fights', 'monster_kills']:
                                w[stat] = 0
                            w['fight_history'] = []
                    
                    # Clear archives and history
                    data['archived_warriors'] = []
                    data['turn_history'] = []
                    data['fallen_warriors'] = []
                    
                    # Save and recalculate checksum
                    make_file_writable(filepath)
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2)
                    save_checksum(filepath, data)
                    make_file_readonly(filepath)
                    print(f"[OK] All records, archives, and history nuked for team {args.team}.")
                except Exception as e:
                    print(f"[ERROR] {e}")
        elif args.list_warriors:
            list_team_warriors(args.team)
        elif args.name:
            update_team_name(args.team, args.name)
        elif args.manager:
            update_manager_name(args.team, args.manager)
        elif args.warrior is not None:
            if args.warrior_name:
                update_warrior_field(args.team, args.warrior, 'name', args.warrior_name)
            elif args.warrior_field and args.value:
                # Try to convert value to appropriate type
                try:
                    # Try int first
                    value = int(args.value)
                except ValueError:
                    try:
                        # Try float
                        value = float(args.value)
                    except ValueError:
                        # Keep as string
                        value = args.value

                update_warrior_field(args.team, args.warrior, args.warrior_field, value)
            else:
                print(f"Error: --warrior requires --warrior-name or (--warrior-field with --value)")
        else:
            print(f"Error: --team requires an action (--list-warriors, --name, --manager, etc.)")


if __name__ == '__main__':
    main()
