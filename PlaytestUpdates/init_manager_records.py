#!/usr/bin/env python3
"""
Initialize or update manager_records.json with Bloodied Entrails' turn 12 record.
Run this once, then regenerate turn 13 newsletter.
"""

import json
import os

# Create the manager_records.json file with turn 12 data
manager_records = {
    "12": {
        "Bloodied Entrails": {
            "w": 0,    # This turn's wins (will be recalculated on regeneration)
            "l": 0,    # This turn's losses
            "k": 0,    # This turn's kills
            "cw": 123, # Career wins (corrected)
            "cl": 142, # Career losses
            "ck": 16   # Career kills
        }
    }
}

league_dir = os.path.dirname(os.path.abspath(__file__))
manager_records_file = os.path.join(league_dir, "manager_records.json")

try:
    # Load existing records if any to preserve other managers/turns
    if os.path.exists(manager_records_file):
        with open(manager_records_file, "r", encoding="utf-8") as f:
            existing = json.load(f)
            # Merge: preserve existing, but override turn 12 with our corrected data
            if "12" not in existing:
                existing["12"] = {}
            existing["12"]["Bloodied Entrails"] = manager_records["12"]["Bloodied Entrails"]
            manager_records = existing

    with open(manager_records_file, "w", encoding="utf-8") as f:
        json.dump(manager_records, f, indent=2)

    print(f"Successfully initialized manager_records.json")
    print(f"Set Bloodied Entrails turn 12 career record to: 123-142-16")
    print(f"\nNow regenerate turn 13's newsletter and it will correctly add 13-12-2 to get 136-154-18")
except Exception as e:
    print(f"ERROR: {e}")
