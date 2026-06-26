#!/usr/bin/env python3
"""Debug script to check what team data exists for a given turn."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, r"C:\BPClone_Claude")

from save import load_all_teams

def debug_team_data(turn_num):
    """Check team data and turn_history."""

    print(f"Checking team data for Turn {turn_num}...\n")

    # Load all teams
    all_teams = load_all_teams()

    print(f"Total teams loaded: {len(all_teams)}\n")

    manager_totals = {}

    for team in all_teams:
        mgr_name = getattr(team, "manager_name", "?") or "?"
        if mgr_name in ["?", "The Monsters", "The Peasants"]:
            continue

        team_name = getattr(team, "team_name", "?")
        team_id = getattr(team, "team_id", "?")
        turn_history = getattr(team, "turn_history", [])

        if mgr_name not in manager_totals:
            manager_totals[mgr_name] = {"w": 0, "l": 0, "k": 0, "teams": []}

        # Sum turn history
        for entry in turn_history:
            manager_totals[mgr_name]["w"] += entry.get("w", 0)
            manager_totals[mgr_name]["l"] += entry.get("l", 0)
            manager_totals[mgr_name]["k"] += entry.get("k", 0)

        manager_totals[mgr_name]["teams"].append({
            "name": team_name,
            "id": team_id,
            "turn_history_entries": len(turn_history)
        })

    # Display results
    print("Manager Career Records (from loaded teams):")
    print("=" * 80)
    for mgr_name in sorted(manager_totals.keys()):
        data = manager_totals[mgr_name]
        total = data["w"] + data["l"]
        pct = (data["w"] / total * 100) if total > 0 else 0

        print(f"{mgr_name:<30} W:{data['w']:>3} L:{data['l']:>3} K:{data['k']:>2}  {pct:>5.1f}%  ({total} fights)")
        for team in data["teams"]:
            print(f"  - {team['name']:<40} (ID:{team['id']}) turns:{team['turn_history_entries']}")

if __name__ == "__main__":
    turn = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    debug_team_data(turn)
