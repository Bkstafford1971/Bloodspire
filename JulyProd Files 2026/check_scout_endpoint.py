#!/usr/bin/env python3
"""
Diagnostic script to check why scout/targets endpoint returns empty warriors list.
"""
import sys
sys.path.insert(0, '.')

import json
import os
from save import TEAMS_DIR, load_champion_state
from league_server import _load_config, _load_managers, _check_mgr_pw

# Test parameters (same as the client would use)
mid = "21"
pw = "Tin@0302"

print("=" * 70)
print("SCOUT/TARGETS ENDPOINT DIAGNOSTIC")
print("=" * 70)

# 1. Check manager authentication
print("\n1. Checking manager authentication...")
mgrs = _load_managers()
if mid not in mgrs:
    print(f"   ERROR: Manager {mid} not found!")
    print(f"   Available managers: {list(mgrs.keys())}")
    sys.exit(1)

if not _check_mgr_pw(mgrs[mid], pw):
    print(f"   ERROR: Password check failed for manager {mid}")
    sys.exit(1)

print(f"   OK: Manager {mid} authenticated")
print(f"   Manager name: {mgrs[mid].get('manager_name')}")
print(f"   Own team IDs: {mgrs[mid].get('team_ids')}")

# 2. Check team files
print("\n2. Checking team files...")
own_team_ids = set(int(t) for t in mgrs[mid].get("team_ids", []) if isinstance(t,(int,str)) and str(t).isdigit())
cfg = _load_config()
current_turn = cfg.get("current_turn", 0)
print(f"   Current turn: {current_turn}")

try:
    fnames = sorted(os.listdir(TEAMS_DIR))
except FileNotFoundError:
    print(f"   ERROR: Teams directory not found: {TEAMS_DIR}")
    sys.exit(1)

team_files = [f for f in fnames if f.startswith('team_') and f.endswith('.json')]
print(f"   Total team files: {len(team_files)}")

# 3. Try to load teams
print("\n3. Loading and filtering teams...")
champ_state = load_champion_state()
champion_name = (champ_state.get("name") or "").lower()

warriors = []
loaded = 0
own_teams_skipped = 0
inactive_teams_skipped = 0
dead_warriors_skipped = 0

for fname in team_files:
    fpath = os.path.join(TEAMS_DIR, fname)
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            tdata = json.load(f)
    except Exception as e:
        print(f"   ERROR loading {fname}: {e}")
        continue

    loaded += 1

    tid = tdata.get("team_id", 0)
    if tid in own_team_ids:
        own_teams_skipped += 1
        continue

    last_turn_ran = tdata.get("last_turn_ran", 0)
    if current_turn > 0 and last_turn_ran > 0 and (current_turn - last_turn_ran) > 3:
        inactive_teams_skipped += 1
        continue

    team_name = tdata.get("team_name", "?")
    manager_name = tdata.get("manager_name", "?")

    for w in tdata.get("warriors", []):
        if not w or w.get("is_dead"):
            dead_warriors_skipped += 1
            continue

        wname = w.get("name", "?")
        warriors.append({
            "name"        : wname,
            "team_name"   : team_name,
            "team_id"     : tid,
            "manager_name": manager_name,
            "race"        : w.get("race", "?"),
            "gender"      : w.get("gender", "?"),
            "wins"        : w.get("wins", 0),
            "losses"      : w.get("losses", 0),
            "kills"       : w.get("kills", 0),
            "max_hp"      : w.get("max_hp", 0),
            "height_in"   : w.get("height_in", 0),
            "weight_lbs"  : w.get("weight_lbs", 0),
            "total_fights": w.get("total_fights", 0),
            "recognition" : w.get("recognition", 0),
            "is_champion" : bool(champion_name and wname.lower() == champion_name),
        })

print(f"   Loaded: {loaded} teams")
print(f"   Skipped (own teams): {own_teams_skipped}")
print(f"   Skipped (inactive): {inactive_teams_skipped}")
print(f"   Skipped (dead warriors): {dead_warriors_skipped}")
print(f"   TOTAL WARRIORS: {len(warriors)}")

# 4. Try tier calculation
print("\n4. Calculating tiers...")
try:
    from warrior import get_warrior_tier, TIER_ORDER, TIER_CHAMPION
    tiers_present = set()
    errors = 0
    for w_data in warriors:
        try:
            class TempWarrior:
                def __init__(self, data):
                    self.total_fights = data.get("total_fights", 0)
                    self.recognition = data.get("recognition", 0)
            temp_w = TempWarrior(w_data)
            tier = get_warrior_tier(temp_w)
            if tier != TIER_CHAMPION:
                tiers_present.add(tier)
        except Exception as e:
            errors += 1
            if errors <= 3:  # Show first 3 errors only
                print(f"   ERROR calculating tier for {w_data.get('name')}: {e}")

    if errors > 3:
        print(f"   ... and {errors - 3} more errors")

    sorted_tiers = sorted(tiers_present, key=lambda t: TIER_ORDER.index(t) if t in TIER_ORDER else 999)
    eligible_champion_tiers = sorted_tiers[:2]
    print(f"   Eligible tiers: {eligible_champion_tiers}")
except Exception as e:
    print(f"   ERROR with tier calculation: {e}")
    import traceback
    traceback.print_exc()

# 5. Summary
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"Warriors available for scouting: {len(warriors)}")

if len(warriors) == 0:
    print("\nWARNING: No warriors available!")
    print("Possible causes:")
    print("  1. All teams are inactive (no activity in last 3 turns)")
    print("  2. All teams are owned by this manager")
    print("  3. All warriors are dead")
    print("  4. Team data is corrupted")
else:
    print(f"\nSample warriors:")
    for w in warriors[:3]:
        print(f"  - {w['name']} ({w['team_name']}, {w['manager_name']})")

# 6. Test JSON serialization
print("\n5. Testing JSON serialization...")
response = {"success": True, "warriors": warriors, "eligible_champion_tiers": eligible_champion_tiers}
try:
    json_str = json.dumps(response, default=str)
    print(f"   OK: JSON response is {len(json_str)} bytes")
except Exception as e:
    print(f"   ERROR: Could not serialize response: {e}")

print("\n" + "=" * 70)
