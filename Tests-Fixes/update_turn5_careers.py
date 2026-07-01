#!/usr/bin/env python3
"""
Update turn 5 newsletter with corrected career records.
Outputs just the corrected career section for manual insertion.
"""

import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEAGUE_DIR = os.path.join(BASE_DIR, "saves", "league")
STANDINGS_PATH = os.path.join(LEAGUE_DIR, "standings.json")

def load_json(path):
    """Load JSON file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  ERROR loading {path}: {e}")
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

        # Sum all warriors' stats for this team
        warriors = team_data.get("warriors", {})
        for warrior_key, warrior_data in warriors.items():
            manager_records[mgr_name]["w"] += warrior_data.get("wins", 0)
            manager_records[mgr_name]["l"] += warrior_data.get("losses", 0)
            manager_records[mgr_name]["k"] += warrior_data.get("kills", 0)

    return manager_records

def format_career_section():
    """Format the corrected career records section."""
    records = get_manager_records()

    manager_list = []
    for mgr_name, rec in records.items():
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

    # Sort by win percentage (descending) and wins (descending)
    manager_list.sort(key=lambda x: (-x["pct"], -x["w"]))

    # Format output
    lines = []
    lines.append("")
    lines.append("The Top Managers Career")
    lines.append("  MANAGER                             W   L   K      %  TOTAL")
    lines.append("===========================================================")

    for mgr in manager_list:
        line = f" {mgr['name']:<34}{mgr['w']:>4}{mgr['l']:>4}{mgr['k']:>4}{mgr['pct']:>6.1f}%{mgr['total']:>6}"
        lines.append(line)

    lines.append("===========================================================")
    lines.append("")

    return '\n'.join(lines)

if __name__ == "__main__":
    print("Corrected Career Records Section for Turn 5 Newsletter:")
    print("=" * 60)
    print(format_career_section())
    print("=" * 60)
    print("\nCopy the above section to replace the career section in the newsletter.")
