#!/usr/bin/env python3
"""
Fix the turn 5 newsletter by replacing only the career records section
(right column) with corrected data while preserving the "This Turn" section.
"""

import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEWSLETTER_PATH = os.path.join(BASE_DIR, "saves", "league", "turn_0005", "newsletter.txt")
STANDINGS_PATH = os.path.join(BASE_DIR, "saves", "league", "standings.json")

def load_json(path):
    """Load JSON file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"ERROR: {e}")
        return {}

def get_manager_records():
    """Extract corrected manager career records."""
    standings = load_json(STANDINGS_PATH)
    manager_records = {}

    for team_key, team_data in standings.items():
        mgr_name = team_data.get("manager_name")
        if not mgr_name or mgr_name == "?":
            continue

        if mgr_name not in manager_records:
            manager_records[mgr_name] = {"w": 0, "l": 0, "k": 0}

        warriors = team_data.get("warriors", {})
        for warrior_key, warrior_data in warriors.items():
            manager_records[mgr_name]["w"] += warrior_data.get("wins", 0)
            manager_records[mgr_name]["l"] += warrior_data.get("losses", 0)
            manager_records[mgr_name]["k"] += warrior_data.get("kills", 0)

    return manager_records

def fix_newsletter():
    """Replace career records in newsletter."""
    print("Fixing Turn 5 newsletter career records...")

    # Read current newsletter
    try:
        with open(NEWSLETTER_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"ERROR reading newsletter: {e}")
        return False

    # Get corrected career records
    career_records = get_manager_records()

    # Build manager list
    manager_list = []
    for mgr_name, rec in career_records.items():
        total = rec["w"] + rec["l"]
        pct = (rec["w"] / total * 100) if total > 0 else 0
        manager_list.append({
            "name": mgr_name,
            "w": rec["w"],
            "l": rec["l"],
            "k": rec["k"],
            "pct": pct,
            "total": total,
        })

    # Sort by win percentage and wins
    manager_list.sort(key=lambda x: (-x["pct"], -x["w"]))

    # Format career data rows
    career_rows = []
    for mgr in manager_list:
        # Format: " MANAGER_NAME                      W   L   K      %  TOTAL"
        # Right-aligned at column 72+
        line = f" {mgr['name']:<34}{mgr['w']:>4}{mgr['l']:>4}{mgr['k']:>4}{mgr['pct']:>6.1f}%{mgr['total']:>6}"
        career_rows.append(line)

    # Find the career section in the newsletter
    # Look for the line with "The Top Managers Career" header
    career_header_idx = -1
    for i, line in enumerate(lines):
        if "The Top Managers Career" in line and i > 60:  # Should be near line 66
            career_header_idx = i
            break

    if career_header_idx == -1:
        print("ERROR: Could not find career section header")
        return False

    # Find the separator line after the header
    sep_idx = -1
    for i in range(career_header_idx + 1, len(lines)):
        if "====" in lines[i]:
            sep_idx = i
            break

    if sep_idx == -1:
        print("ERROR: Could not find separator after career header")
        return False

    # Find the end of the career records (next separator or empty section)
    end_idx = -1
    for i in range(sep_idx + 1, len(lines)):
        if "====" in lines[i]:
            end_idx = i
            break

    if end_idx == -1:
        print("ERROR: Could not find end of career section")
        return False

    # Replace the career records
    # Keep everything before the separator, add new records, keep separator and after
    new_lines = (
        lines[:sep_idx + 1] +  # Everything up to and including first separator
        [line + "\n" for line in career_rows] +  # New career records
        lines[end_idx:]  # Everything from end separator onwards
    )

    # Write updated newsletter
    try:
        with open(NEWSLETTER_PATH, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print(f"Successfully updated {NEWSLETTER_PATH}")
        return True
    except Exception as e:
        print(f"ERROR writing newsletter: {e}")
        return False

if __name__ == "__main__":
    if fix_newsletter():
        print("\nNewsletter fixed successfully!")
    else:
        print("\nFailed to fix newsletter.")
