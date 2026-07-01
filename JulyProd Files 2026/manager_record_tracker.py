#!/usr/bin/env python3
"""
Manager Record Tracker
Analyzes league results to determine manager records.
Shows: Wins - Losses - Kills for a specific manager against all opponents.
"""

import json
from pathlib import Path
from collections import defaultdict

def get_results_dir():
    r"""Get the results directory path (C:\BloodspireArena\results by default)."""
    # Check if C:\BloodspireArena\results exists, otherwise use local saves
    results_path = Path("C:\\BloodspireArena\\results")
    if results_path.exists():
        return results_path
    # Fallback to local saves
    return Path(__file__).parent / "saves"

def get_team_ids_for_manager(results_dir, target_manager, league_only=True):
    """Find all team IDs managed by target_manager from result files.
    If league_only=True, returns only original 5 league teams.
    """
    all_team_ids = set()

    for result_file in results_dir.glob('team_*_turn_*.json'):
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data.get('manager_name') == target_manager:
                    all_team_ids.add(data.get('team_id'))
        except Exception:
            pass

    team_ids = sorted(list(all_team_ids))

    # If league_only, filter to original 5 teams (IDs 38, 39, 40, 83, 94)
    if league_only:
        original_leagues = {38, 39, 40, 83, 94}
        team_ids = [tid for tid in team_ids if tid in original_leagues]

    return team_ids

def get_all_team_info(results_dir):
    """Get team name and manager for all teams from result files."""
    team_info = {}

    for result_file in results_dir.glob('team_*_turn_*.json'):
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                team_id = data.get('team_id')
                if team_id not in team_info:
                    team_info[team_id] = {
                        'team_name': data.get('team_name'),
                        'manager_name': data.get('manager_name')
                    }
        except Exception:
            pass

    return team_info

def scan_results(results_dir, target_team_ids, exclude_npcs=True):
    """
    Scan all result files for target teams and aggregate records.
    Returns: {opponent_manager: {wins, losses, kills, deaths}}
    Kills = number of opponents' warriors permanently slain (opponent_slain: true)
    Deaths = number of own warriors permanently slain (warrior_slain: true)
    """
    records = defaultdict(lambda: {'wins': 0, 'losses': 0, 'kills': 0, 'deaths': 0})
    total_wins = 0
    total_losses = 0
    total_kills = 0
    total_deaths = 0

    # Ghost accounts to exclude (but include "The Arena" for Monster/Peasant fights)
    excluded = {'BloodiedEntrails'}

    for result_file in sorted(results_dir.glob('team_*_turn_*.json')):
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

                if data.get('team_id') not in target_team_ids:
                    continue

                # Process each bout in this result file
                for bout in data.get('bouts', []):
                    opponent_manager = bout.get('opponent_manager')

                    # Skip excluded opponents
                    if exclude_npcs and opponent_manager in excluded:
                        continue

                    result = bout.get('result')
                    opponent_slain = bout.get('opponent_slain', False)
                    warrior_slain = bout.get('warrior_slain', False)

                    if result == 'WIN':
                        records[opponent_manager]['wins'] += 1
                        total_wins += 1
                    elif result == 'LOSS':
                        records[opponent_manager]['losses'] += 1
                        total_losses += 1

                    # Count kills as opponents' warriors permanently slain
                    if opponent_slain:
                        records[opponent_manager]['kills'] += 1
                        total_kills += 1

                    # Count deaths as own warriors permanently slain
                    if warrior_slain:
                        records[opponent_manager]['deaths'] += 1
                        total_deaths += 1

        except Exception as e:
            pass

    return records, total_wins, total_losses, total_kills, total_deaths

def print_record(target_manager, records, total_wins, total_losses, total_kills, total_deaths):
    """Print a formatted record table."""
    if not records:
        print(f"\nNo fight records found for manager: {target_manager}")
        return

    print(f"\n{'='*90}")
    print(f"Manager Record: {target_manager}")
    print(f"{'='*90}\n")

    # Sort by total fights descending
    sorted_records = sorted(
        records.items(),
        key=lambda x: (x[1]['wins'] + x[1]['losses']),
        reverse=True
    )

    print(f"{'Opponent Manager':<30} {'W':<4} {'-':<2} {'L':<4} {'-':<2} {'K':<4} {'Deaths':<6}")
    print(f"{'-'*90}")

    for opponent, record in sorted_records:
        w = record['wins']
        l = record['losses']
        k = record['kills']
        d = record['deaths']
        print(f"{opponent:<30} {w:<4} {'-':<2} {l:<4} {'-':<2} {k:<4} {d:<6}")

    print(f"{'-'*90}")
    print(f"{'TOTAL':<30} {total_wins:<4} {'-':<2} {total_losses:<4} {'-':<2} {total_kills:<4} {total_deaths:<6}")
    print(f"{'='*90}\n")

def main():
    import sys

    results_dir = get_results_dir()

    if not results_dir.exists():
        print(f"Error: results directory not found at {results_dir}")
        return

    # Get target manager name from argument or prompt
    print("Manager Record Tracker")
    print("=" * 80)

    if len(sys.argv) > 1:
        target_manager = " ".join(sys.argv[1:]).strip()
    else:
        target_manager = input("Enter manager name to track (e.g., 'The Chosen One'): ").strip()

    if not target_manager:
        print("No manager name provided.")
        return

    print(f"\nScanning results in {results_dir}...")

    # Get league teams for this manager (original 5 teams only)
    target_team_ids = get_team_ids_for_manager(results_dir, target_manager, league_only=True)

    if not target_team_ids:
        print(f"No league teams found for manager: {target_manager}")
        return

    print(f"Found league teams with IDs: {target_team_ids}")

    # Scan results
    records, total_wins, total_losses, total_kills, total_deaths = scan_results(results_dir, target_team_ids)

    # Print record
    print_record(target_manager, records, total_wins, total_losses, total_kills, total_deaths)

if __name__ == "__main__":
    main()
