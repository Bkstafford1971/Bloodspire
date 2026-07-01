#!/usr/bin/env python3
"""
Regenerate turn 5 newsletter with corrected career records from standings.json
"""

import os
import json
import glob
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEAGUE_DIR = os.path.join(BASE_DIR, "saves", "league")
TURN_DIR = os.path.join(LEAGUE_DIR, "turn_0005")
STANDINGS_PATH = os.path.join(LEAGUE_DIR, "standings.json")
NEWSLETTER_PATH = os.path.join(TURN_DIR, "newsletter.txt")

def load_json(path):
    """Load JSON file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ERROR loading {path}: {e}")
        return {}

def get_manager_career_records():
    """Extract manager career records from standings.json"""
    standings = load_json(STANDINGS_PATH)

    manager_records = {}

    for team_key, team_data in standings.items():
        mgr_name = team_data.get("manager_name")
        if not mgr_name or mgr_name == "?":
            continue

        if mgr_name not in manager_records:
            manager_records[mgr_name] = {"w": 0, "l": 0, "k": 0}

        # Sum all warriors' stats for this team
        warriors = team_data.get("warriors", {})
        for warrior_key, warrior_data in warriors.items():
            manager_records[mgr_name]["w"] += warrior_data.get("wins", 0)
            manager_records[mgr_name]["l"] += warrior_data.get("losses", 0)
            manager_records[mgr_name]["k"] += warrior_data.get("kills", 0)

    return manager_records

def load_current_newsletter():
    """Load the current newsletter to preserve most of its content."""
    try:
        with open(NEWSLETTER_PATH, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"  ERROR loading newsletter: {e}")
        return ""

def extract_manager_section(newsletter_text):
    """Extract the managers section from the current newsletter."""
    lines = newsletter_text.split('\n')

    # Find the start of the career records section
    start_idx = -1
    end_idx = -1

    for i, line in enumerate(lines):
        if "The Top Managers Career" in line:
            start_idx = i
        if start_idx != -1 and i > start_idx and line.strip().startswith("=") and len(line.strip()) > 10:
            # Found the separator after the header
            continue
        if start_idx != -1 and i > start_idx + 2 and (line.strip() == "" or (i < len(lines) - 1 and lines[i+1].strip() == "")):
            end_idx = i
            break

    if start_idx == -1:
        return None, lines

    return lines[start_idx:end_idx], lines

def rebuild_newsletter_with_corrected_careers(current_newsletter, career_records):
    """Rebuild the newsletter with corrected career records."""

    # Extract the manager records section
    mgr_section, lines = extract_manager_section(current_newsletter)

    if mgr_section is None:
        print("  WARNING: Could not locate manager section in newsletter")
        return current_newsletter

    # Rebuild the career records table
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
    SEP = "=" * 70
    left_hdr = f"{'MANAGER':<35}{'W':>4}{'L':>4}{'K':>4}{'%':>7}{'TOTAL':>6}"
    right_title = "The Top Managers Career"

    new_section = [
        f"{right_title}",
        left_hdr,
        SEP,
    ]

    for mgr in manager_list:
        line = (f" {mgr['name']:<34}{mgr['w']:>4}{mgr['l']:>4}{mgr['k']:>4}"
                f"{mgr['pct']:>6.1f}%{mgr['total']:>6}")
        new_section.append(line)

    new_section.append(SEP)

    # Find where to replace in the original lines
    original_text = '\n'.join(lines)

    # Find the indices in the full text
    start_marker = "The Top Managers Career"
    end_marker = "=" * 70

    # Find the position to start replacement
    start_pos = original_text.find(start_marker)
    if start_pos == -1:
        print("  WARNING: Could not find career section marker")
        return original_text

    # Find the end of the section (next separator that's significantly long)
    remainder = original_text[start_pos:]
    lines_after = remainder.split('\n')

    # Count lines to replace
    sep_count = 0
    lines_to_replace = 1  # Include the title line
    for i, line in enumerate(lines_after[1:], 1):
        if line.strip().startswith("=") and len(line.strip()) > 60:
            sep_count += 1
            lines_to_replace = i + 1
            if sep_count == 2:  # Found the end separator
                break
        elif line.strip() == "" and sep_count > 0:
            break
        else:
            lines_to_replace = i + 1

    # Split the text
    before = original_text[:start_pos]
    after_start = start_pos + remainder.find('\n', len(start_marker))
    after = original_text[after_start:]

    # Skip old section content
    lines_in_after = after.split('\n')
    new_after_start = 0
    for i, line in enumerate(lines_in_after):
        if i > 3 and line.strip().startswith("=") and len(line.strip()) > 60:
            new_after_start = sum(len(l) + 1 for l in lines_in_after[:i+1])
            break

    new_content = before + '\n'.join(new_section) + after[new_after_start:]

    return new_content

def regenerate_newsletter():
    """Main function to regenerate the newsletter."""
    print("Regenerating Turn 5 newsletter with corrected career records...")

    # Load career records from standings
    career_records = get_manager_career_records()
    print(f"  Loaded career records for {len(career_records)} managers")

    # Load current newsletter
    current_newsletter = load_current_newsletter()
    if not current_newsletter:
        print("  ERROR: Could not load current newsletter")
        return

    # Rebuild with corrected data
    new_newsletter = rebuild_newsletter_with_corrected_careers(current_newsletter, career_records)

    # Save the updated newsletter
    try:
        with open(NEWSLETTER_PATH, 'w', encoding='utf-8') as f:
            f.write(new_newsletter)
        print(f"  Updated newsletter saved to {NEWSLETTER_PATH}")
    except Exception as e:
        print(f"  ERROR saving newsletter: {e}")

if __name__ == "__main__":
    regenerate_newsletter()
