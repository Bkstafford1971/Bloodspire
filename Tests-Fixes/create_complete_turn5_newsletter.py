#!/usr/bin/env python3
"""
Create a complete turn 5 newsletter with corrected career records.
Uses turn 4 newsletter as a template and updates with turn 5 data.
"""

import os
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEAGUE_DIR = os.path.join(BASE_DIR, "saves", "league")
TURN_DIR = os.path.join(LEAGUE_DIR, "turn_0005")
STANDINGS_PATH = os.path.join(LEAGUE_DIR, "standings.json")
TURN4_NEWSLETTER = os.path.join(LEAGUE_DIR, "turn_0004", "newsletter.txt")
OUTPUT_NEWSLETTER = os.path.join(TURN_DIR, "newsletter.txt")

def load_json(path):
    """Load JSON file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ERROR: {e}")
        return {}

def get_manager_records():
    """Extract manager career records from standings.json"""
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

def load_turn4_newsletter():
    """Load turn 4 newsletter as template."""
    try:
        with open(TURN4_NEWSLETTER, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"  ERROR loading turn 4 newsletter: {e}")
        return None

def create_turn5_newsletter():
    """Create turn 5 newsletter with corrected career data."""
    print("Creating Turn 5 newsletter with corrected career records...")

    # Get career records
    career_records = get_manager_records()
    print(f"  Loaded {len(career_records)} manager career records")

    # Load turn 4 newsletter as template
    template = load_turn4_newsletter()
    if not template:
        print("  ERROR: Could not load turn 4 newsletter template")
        return False

    # Create manager list for career section
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

    # Format the career records section
    career_lines = []
    for mgr in manager_list:
        line = f" {mgr['name']:<34}{mgr['w']:>4}{mgr['l']:>4}{mgr['k']:>4}{mgr['pct']:>6.1f}%{mgr['total']:>6}"
        career_lines.append(line)

    career_section = "\n".join(career_lines)

    # Replace header info
    lines = template.split('\n')

    # Update date and turn
    for i, line in enumerate(lines):
        if line.startswith("Date:"):
            lines[i] = f"Date: {datetime.now().strftime('%m/%d/%Y')}"
        elif line.startswith("Turn -"):
            lines[i] = "Turn - 5"
        elif "The Top Managers Career" in line and i < 200:  # Find in first part
            # This is where we need to replace career records
            # Find the career records section
            sep_count = 0
            start_idx = i
            end_idx = i + 1

            for j in range(i + 1, len(lines)):
                if "=" in lines[j] and len(lines[j].replace("=", "").strip()) < 5:
                    sep_count += 1
                    if sep_count == 2:
                        end_idx = j
                        break

            # Replace the section
            before = lines[:start_idx + 2]  # Keep header
            after = lines[end_idx:]

            new_lines = before + career_lines + after
            lines = new_lines
            break

    # Write the new newsletter
    newsletter_content = "\n".join(lines)

    try:
        with open(OUTPUT_NEWSLETTER, 'w', encoding='utf-8') as f:
            f.write(newsletter_content)
        print(f"  Successfully created {OUTPUT_NEWSLETTER}")
        return True
    except Exception as e:
        print(f"  ERROR writing newsletter: {e}")
        return False

if __name__ == "__main__":
    success = create_turn5_newsletter()
    if success:
        print("\nNewsletter updated successfully!")
    else:
        print("\nFailed to create newsletter. Check errors above.")
