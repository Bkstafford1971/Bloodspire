#!/usr/bin/env python3
# =============================================================================
# file_repair.py - File Repair & Update Utility
# =============================================================================
# Provides tools to repair checksums and safely update protected files.
# Useful when files are corrupted or need manual fixes.
#
# Usage:
#   python file_repair.py --repair <filepath>         # Recalculate checksum
#   python file_repair.py --repair-dir <directory>    # Fix all JSON files in dir
#   python file_repair.py --update-team <team_id> <json_file>  # Update a team
#   python file_repair.py --list-corrupted            # Find corrupted files
# =============================================================================

import json
import os
import sys
import argparse
from typing import List, Tuple
from file_protection import (
    calculate_checksum, save_checksum, verify_checksum,
    make_file_writable, make_file_readonly, load_json_protected
)

# ---------------------------------------------------------------------------
# REPAIR OPERATIONS
# ---------------------------------------------------------------------------

def repair_checksum(json_filepath: str) -> Tuple[bool, str]:
    """
    Recalculate and save the checksum for a JSON file.
    Useful when a file has been manually edited and the checksum is out of sync.

    Args:
        json_filepath: Path to the JSON file to repair

    Returns:
        (success: bool, message: str)
    """
    if not os.path.exists(json_filepath):
        return False, f"File not found: {json_filepath}"

    try:
        # Load the current JSON data
        with open(json_filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"JSON is corrupted: {e}"
    except IOError as e:
        return False, f"Could not read file: {e}"

    try:
        # Recalculate and save the checksum
        save_checksum(json_filepath, data)
        return True, f"[OK] Checksum repaired for {os.path.basename(json_filepath)}"
    except Exception as e:
        return False, f"Could not save checksum: {e}"


def repair_directory(directory: str, pattern: str = "*.json") -> Tuple[int, int, List[str]]:
    """
    Repair all JSON files in a directory and subdirectories.

    Args:
        directory: Directory to scan
        pattern: File pattern to match (default: *.json)

    Returns:
        (success_count, failure_count, error_messages)
    """
    if not os.path.isdir(directory):
        return 0, 1, [f"Directory not found: {directory}"]

    success_count = 0
    failure_count = 0
    errors = []

    for root, dirs, files in os.walk(directory):
        for filename in files:
            if not filename.endswith('.json'):
                continue

            filepath = os.path.join(root, filename)
            success, message = repair_checksum(filepath)

            if success:
                success_count += 1
                print(f"  {message}")
            else:
                failure_count += 1
                errors.append(f"{filename}: {message}")
                print(f"  [ERROR] {message}")

    return success_count, failure_count, errors


def verify_file(json_filepath: str) -> Tuple[bool, str]:
    """
    Check if a JSON file's checksum is valid.

    Args:
        json_filepath: Path to the JSON file to verify

    Returns:
        (is_valid: bool, message: str)
    """
    if not os.path.exists(json_filepath):
        return False, f"File not found: {json_filepath}"

    try:
        with open(json_filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"JSON is corrupted: {e}"
    except IOError as e:
        return False, f"Could not read file: {e}"

    is_valid = verify_checksum(json_filepath, data)
    status = "[OK] Valid" if is_valid else "[ERROR] Invalid (tampered/corrupted)"
    return is_valid, f"{os.path.basename(json_filepath)}: {status}"


def find_corrupted_files(search_dir: str) -> List[str]:
    """
    Scan a directory tree for files with invalid checksums.

    Args:
        search_dir: Root directory to search

    Returns:
        List of file paths with invalid checksums
    """
    corrupted = []

    for root, dirs, files in os.walk(search_dir):
        for filename in files:
            if not filename.endswith('.json'):
                continue

            filepath = os.path.join(root, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if not verify_checksum(filepath, data):
                    corrupted.append(filepath)
            except Exception:
                # Skip files that can't be read
                pass

    return corrupted


# ---------------------------------------------------------------------------
# SAFE UPDATE OPERATIONS
# ---------------------------------------------------------------------------

def update_team_file(filepath: str, updates: dict) -> Tuple[bool, str]:
    """
    Safely update a team JSON file with new data.
    Loads the file, applies updates, recalculates checksum, and saves.

    Args:
        filepath: Path to the team JSON file
        updates: Dictionary of updates to merge (shallow merge)

    Returns:
        (success: bool, message: str)
    """
    if not os.path.exists(filepath):
        return False, f"File not found: {filepath}"

    try:
        # Load current data
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Apply updates
        data.update(updates)

        # Make file writable
        make_file_writable(filepath)

        # Write updated data
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        # Recalculate checksum
        save_checksum(filepath, data)

        # Make file read-only again
        make_file_readonly(filepath)

        return True, f"[OK] Updated {os.path.basename(filepath)}"
    except Exception as e:
        return False, f"Update failed: {e}"


def update_warrior_in_team(team_filepath: str, warrior_index: int, updates: dict) -> Tuple[bool, str]:
    """
    Update a specific warrior in a team file.

    Args:
        team_filepath: Path to the team JSON file
        warrior_index: Index of the warrior in the team's warriors array
        updates: Dictionary of updates to merge into the warrior

    Returns:
        (success: bool, message: str)
    """
    if not os.path.exists(team_filepath):
        return False, f"File not found: {team_filepath}"

    try:
        # Load current data
        with open(team_filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Update the specific warrior
        if 'warriors' not in data:
            return False, "Team file has no 'warriors' array"

        if warrior_index >= len(data['warriors']):
            return False, f"Warrior index {warrior_index} out of range (team has {len(data['warriors'])} warriors)"

        if data['warriors'][warrior_index] is None:
            return False, f"Warrior at index {warrior_index} is None"

        data['warriors'][warrior_index].update(updates)

        # Make file writable
        make_file_writable(team_filepath)

        # Write updated data
        with open(team_filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        # Recalculate checksum
        save_checksum(team_filepath, data)

        # Make file read-only again
        make_file_readonly(team_filepath)

        warrior_name = data['warriors'][warrior_index].get('name', 'Unknown')
        return True, f"[OK] Updated warrior {warrior_name} in {os.path.basename(team_filepath)}"
    except Exception as e:
        return False, f"Warrior update failed: {e}"


# ---------------------------------------------------------------------------
# CLI INTERFACE
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="File repair and update utility for BLOODSPIRE saves"
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Repair single file
    repair_parser = subparsers.add_parser('repair', help='Repair checksum for a single file')
    repair_parser.add_argument('filepath', help='Path to JSON file to repair')

    # Repair directory
    repair_dir_parser = subparsers.add_parser('repair-dir', help='Repair all files in a directory')
    repair_dir_parser.add_argument('directory', help='Directory to scan and repair')

    # Verify file
    verify_parser = subparsers.add_parser('verify', help='Verify a file is not corrupted')
    verify_parser.add_argument('filepath', help='Path to JSON file to verify')

    # List corrupted
    list_parser = subparsers.add_parser('list-corrupted', help='Find all corrupted files')
    list_parser.add_argument('directory', nargs='?', default='saves',
                             help='Directory to search (default: saves/)')

    # Update team
    team_parser = subparsers.add_parser('update-team', help='Update a team file')
    team_parser.add_argument('filepath', help='Path to team JSON file')
    team_parser.add_argument('--name', help='Update team name')
    team_parser.add_argument('--manager', help='Update manager name')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Handle commands
    if args.command == 'repair':
        success, message = repair_checksum(args.filepath)
        print(message)
        sys.exit(0 if success else 1)

    elif args.command == 'repair-dir':
        print(f"Scanning {args.directory}...\n")
        success, failed, errors = repair_directory(args.directory)
        print(f"\n[OK] Repaired {success} files")
        if failed:
            print(f"[ERROR] Failed to repair {failed} files")
            for error in errors:
                print(f"    {error}")
        sys.exit(0 if failed == 0 else 1)

    elif args.command == 'verify':
        is_valid, message = verify_file(args.filepath)
        print(message)
        sys.exit(0 if is_valid else 1)

    elif args.command == 'list-corrupted':
        print(f"Scanning {args.directory} for corrupted files...\n")
        corrupted = find_corrupted_files(args.directory)
        if corrupted:
            print(f"Found {len(corrupted)} corrupted file(s):\n")
            for filepath in corrupted:
                print(f"  {filepath}")
            sys.exit(1)
        else:
            print("[OK] No corrupted files found")
            sys.exit(0)

    elif args.command == 'update-team':
        updates = {}
        if args.name:
            updates['team_name'] = args.name
        if args.manager:
            updates['manager_name'] = args.manager

        if not updates:
            print("Error: No updates specified. Use --name and/or --manager")
            sys.exit(1)

        success, message = update_team_file(args.filepath, updates)
        print(message)
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
