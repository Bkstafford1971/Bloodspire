#!/usr/bin/env python3
"""
Properly fix the turn 5 newsletter by updating only the right column (Career)
while preserving the left column (This Turn) exactly as-is.
"""

import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_NEWSLETTER = os.path.join(BASE_DIR, "saves", "league", "newsletters", "turn_005.txt")
NEWSLETTER_PATH = os.path.join(BASE_DIR, "saves", "league", "turn_0005", "newsletter.txt")
STANDINGS_PATH = os.path.join(BASE_DIR, "saves", "league", "standings.json")

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"ERROR: {e}")
        return {}

def get_corrected_career_records():
    """Get corrected manager career records from standings."""
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

    # Create sorted list
    manager_list = []
    for mgr_name, rec in manager_records.items():
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

    manager_list.sort(key=lambda x: (-x["pct"], -x["w"]))
    return manager_list

def fix_newsletter():
    """Fix the newsletter by preserving This Turn and updating Career column."""
    print("Fixing turn 5 newsletter properly...")

    # Read original newsletter
    try:
        with open(SOURCE_NEWSLETTER, 'r', encoding='utf-8') as f:
            original_lines = f.readlines()
    except Exception as e:
        print(f"ERROR reading source: {e}")
        return False

    # Get corrected career records
    career_records = get_corrected_career_records()
    print(f"  Loaded {len(career_records)} corrected manager records")

    # Find the managers section (lines 65-82 approximately)
    managers_start = -1
    managers_end = -1

    for i, line in enumerate(original_lines):
        if "The Top Managers This Turn" in line:
            managers_start = i
        elif managers_start != -1 and "=" in line and len(career_records) < 15:
            # Found closing separator
            if i > managers_start + len(career_records) + 3:
                managers_end = i + 1
                break

    if managers_start == -1 or managers_end == -1:
        print("ERROR: Could not find managers section")
        return False

    print(f"  Found managers section: lines {managers_start+1} to {managers_end}")

    # Build new newsletter
    new_lines = original_lines[:managers_start + 3]  # Keep header lines

    # Add data rows: preserve left side (This Turn), replace right side (Career)
    this_turn_lines = original_lines[managers_start + 3 : managers_start + 3 + len(career_records)]

    for idx, this_turn_line in enumerate(this_turn_lines):
        if idx >= len(career_records):
            break

        # Extract the left side (This Turn) - everything before column 70
        left_side = this_turn_line[:70] if len(this_turn_line) >= 70 else this_turn_line

        # Format career record for right side
        career = career_records[idx]
        right_side = f" {career['name']:<34}{career['w']:>4}{career['l']:>4}{career['k']:>4}{career['pct']:>6.1f}%{career['total']:>6}\n"

        # Combine and add
        new_line = left_side + right_side
        new_lines.append(new_line)

    # Add closing separator and rest of newsletter
    new_lines.extend(original_lines[managers_end:])

    # Write fixed newsletter
    try:
        with open(NEWSLETTER_PATH, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print(f"  Successfully fixed {NEWSLETTER_PATH}")
        return True
    except Exception as e:
        print(f"ERROR writing newsletter: {e}")
        return False

if __name__ == "__main__":
    if fix_newsletter():
        print("\nNewsletter fixed successfully!")
    else:
        print("\nFailed to fix newsletter.")
