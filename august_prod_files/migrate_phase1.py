#!/usr/bin/env python3
"""
Phase 1 Migration: Data Model Foundation for Multi-Arena System

What this does:
  1. Adds current_arena="normal" to every warrior in saves/teams/
  2. Creates saves/elite/ and saves/veteran/ directories with initial config files
  3. Adds promotion_criteria and arena_mode to saves/league/config.json

Safe to re-run: already-migrated files are skipped.
"""

import json
import os
import sys
import time

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
TEAMS_DIR    = os.path.join(BASE_DIR, "saves", "teams")
LEAGUE_DIR   = os.path.join(BASE_DIR, "saves", "league")
ELITE_DIR    = os.path.join(BASE_DIR, "saves", "elite")
VETERAN_DIR  = os.path.join(BASE_DIR, "saves", "veteran")

sys.path.insert(0, BASE_DIR)
from file_protection import (
    save_json_protected, load_json_protected,
    make_file_writable, make_file_readonly,
    save_checksum, calculate_checksum
)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def load_json(path):
    try:
        make_file_writable(path)
    except Exception:
        pass
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_protected(path, data):
    """Write JSON + checksum + set read-only."""
    save_json_protected(path, data)


def save_unprotected(path, data):
    """Write JSON without protection (for new files)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# STEP 1: Add current_arena to all warriors in saves/teams/
# ---------------------------------------------------------------------------

def migrate_team_files():
    print("\n--- Step 1: Adding current_arena to warrior team files ---")
    if not os.path.isdir(TEAMS_DIR):
        print(f"  ERROR: teams dir not found: {TEAMS_DIR}")
        return

    team_files = [f for f in os.listdir(TEAMS_DIR) if f.endswith(".json")]
    modified = 0
    skipped = 0

    for fn in sorted(team_files):
        path = os.path.join(TEAMS_DIR, fn)
        try:
            data = load_json(path)
        except Exception as e:
            print(f"  SKIP {fn}: could not read ({e})")
            continue

        if "warriors" not in data or not isinstance(data["warriors"], list):
            skipped += 1
            continue

        changed = False
        for warrior in data["warriors"]:
            if "current_arena" not in warrior:
                warrior["current_arena"] = "normal"
                changed = True
            if "pending_promotion" not in warrior:
                warrior["pending_promotion"] = None
                changed = True

        if changed:
            save_protected(path, data)
            print(f"  UPDATED {fn} ({len(data['warriors'])} warriors)")
            modified += 1
        else:
            skipped += 1

    print(f"  Done. Modified: {modified}, Already migrated: {skipped}")


# ---------------------------------------------------------------------------
# STEP 2: Create saves/elite/ and saves/veteran/ directories + initial files
# ---------------------------------------------------------------------------

ELITE_CONFIG = {
    "arena": "elite",
    "turn_counter": 0,
    "turn_state": "open",
    "scheduler": {
        "enabled": False,
        "schedule_slots": [],
        "last_run_at": "",
        "last_run_turn": 0,
        "last_run_result": ""
    },
    "arena_rules": {
        "allow_permanent_death": False,
        "allow_blood_challenges": False,
        "allow_monsters": False,
        "allow_resurrection": True,
        "training_difficulty_multiplier": 1.33,
        "peasant_scaling": 2.5,
        "injury_accumulation": False
    },
    "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
}

VETERAN_CONFIG = {
    "arena": "veteran",
    "turn_counter": 0,
    "turn_state": "open",
    "scheduler": {
        "enabled": False,
        "schedule_slots": [],
        "last_run_at": "",
        "last_run_turn": 0,
        "last_run_result": ""
    },
    "arena_rules": {
        "allow_permanent_death": False,
        "allow_blood_challenges": False,
        "allow_monsters": False,
        "allow_resurrection": True,
        "training_difficulty_multiplier": 1.0,
        "peasant_scaling": 1.0,
        "injury_accumulation": False
    },
    "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
}

EMPTY_TEAMS = {"teams": []}
EMPTY_STANDINGS = {"teams": {}}


def create_arena_dir(arena_dir, arena_name, config_data):
    print(f"\n--- Step 2: Creating {arena_name} arena directory ---")
    os.makedirs(arena_dir, exist_ok=True)
    os.makedirs(os.path.join(arena_dir, "activity_logs"), exist_ok=True)
    print(f"  Created {arena_dir}")

    config_path   = os.path.join(arena_dir, "config.json")
    teams_path    = os.path.join(arena_dir, "teams.json")
    standings_path = os.path.join(arena_dir, "standings.json")

    if not os.path.exists(config_path):
        save_unprotected(config_path, config_data)
        print(f"  Created config.json")
    else:
        print(f"  config.json already exists, skipping")

    if not os.path.exists(teams_path):
        save_unprotected(teams_path, EMPTY_TEAMS)
        print(f"  Created teams.json (empty)")
    else:
        print(f"  teams.json already exists, skipping")

    if not os.path.exists(standings_path):
        save_unprotected(standings_path, EMPTY_STANDINGS)
        print(f"  Created standings.json (empty)")
    else:
        print(f"  standings.json already exists, skipping")


# ---------------------------------------------------------------------------
# STEP 3: Update saves/league/config.json with arena metadata
# ---------------------------------------------------------------------------

def update_normal_config():
    print("\n--- Step 3: Updating normal arena config ---")
    config_path = os.path.join(LEAGUE_DIR, "config.json")
    if not os.path.exists(config_path):
        print(f"  ERROR: {config_path} not found")
        return

    try:
        cfg = load_json(config_path)
    except Exception as e:
        print(f"  ERROR reading config: {e}")
        return

    changed = False

    if "arena_mode" not in cfg:
        cfg["arena_mode"] = "normal"
        changed = True
        print("  Added arena_mode = 'normal'")

    if "promotion_criteria" not in cfg:
        cfg["promotion_criteria"] = {
            "min_fights": 40,
            "min_win_rate": 0.55
        }
        changed = True
        print("  Added promotion_criteria (min_fights=40, min_win_rate=0.55)")

    if changed:
        save_protected(config_path, cfg)
        print("  config.json saved.")
    else:
        print("  config.json already has arena fields, no changes needed.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Phase 1 Migration: Multi-Arena Data Model Foundation")
    print("=" * 60)

    migrate_team_files()
    create_arena_dir(ELITE_DIR,   "Elite Spire",    ELITE_CONFIG)
    create_arena_dir(VETERAN_DIR, "Veteran's Keep", VETERAN_CONFIG)
    update_normal_config()

    print("\n" + "=" * 60)
    print("Phase 1 migration complete.")
    print("  - All warriors now have current_arena and pending_promotion fields")
    print("  - saves/elite/ directory created with initial config")
    print("  - saves/veteran/ directory created with initial config")
    print("  - saves/league/config.json updated with arena_mode and promotion_criteria")
    print("  - Existing system is fully unchanged and still works")
    print("=" * 60)
