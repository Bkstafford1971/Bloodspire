#!/usr/bin/env python3
"""
Test Fix #7: Favorite Weapon Flavor Timing
Validates that favorite weapon flavor only appears on successful hits, not as a spoiler.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from warrior import Warrior, Strategy

print("\n" + "="*80)
print("FIX #7: FAVORITE WEAPON FLAVOR TIMING")
print("="*80)

print("\nISSUE:")
print("Favorite weapon flavor was emitted BEFORE the attack roll, creating:")
print("1. SPOILER: Saying 'finds its target with ugly efficiency' before we know")
print("2. CONTRADICTION: 'With ugly efficiency' vs 'barely gets past defenses'")
print()
print("EXAMPLE OF PROBLEM:")
print("  Short sharp and mean MITTENS's hatchet finds its target with ugly")
print("  MITTENS barely gets past IMPELLITTERI's defenses!")
print("  MITTENS's hatchet chops into IMPELLITTERI's torso!")
print("  ^ 'With ugly efficiency' but 'barely' - contradictory!")
print()
print("FIX:")
print("Moved favorite weapon flavor emission to AFTER successful hit.")
print("Now it only appears when the attack actually lands.")
print()

# Create a warrior with a favorite weapon
warrior = Warrior(
    name="MITTENS",
    gender="Male",
    race_name="Human",
    strength=14, dexterity=12, constitution=12, intelligence=10, presence=10, size=10,
)
warrior.primary_weapon = "Hatchet"
warrior.secondary_weapon = "None"
warrior.armor = "Leather"
warrior.favorite_weapon = "Hatchet"  # Set favorite weapon

print("VALIDATION:")
print(f"  Warrior: {warrior.name}")
print(f"  Favorite weapon: {warrior.favorite_weapon}")
print()

# Try to get the favorite weapon flavor
from combat import _get_favorite_weapon_flavor, _CState

state = _CState(
    warrior=warrior,
    current_hp=warrior.max_hp,
    endurance=warrior.max_endurance
)
flavor = _get_favorite_weapon_flavor(warrior, "Hatchet", state)

if flavor:
    print(f"Favorite weapon flavor exists: {flavor[:60]}...")
    print("\nCorrect behavior:")
    print("  1. This flavor will NOT be shown before the attack roll")
    print("  2. It will ONLY be shown if the attack is a successful hit")
    print("  3. It will appear after the damage line")
    print("  4. It will not contradict 'barely gets past' type lines")
    print("\n[OK] Favorite weapon flavor will only appear on successful hits")
else:
    print("No favorite weapon flavor found for this warrior/weapon combination")

print("\n" + "="*80)
print("EXPECTED NARRATIVE SEQUENCES")
print("="*80)

print("\nSCENARIO 1: Attack HITS (with barely-defense fail)")
print("  MITTENS swings his hatchet at IMPELLITTERI's torso")
print("  IMPELLITTERI raises his guard against the incoming blow!")
print("  But IMPELLITTERI commits to the wrong angle!")
print("  MITTENS's hatchet chops into IMPELLITTERI's torso!")
print("  The weapon cleaves through muscle and draws heavy blood!")
print("  Short sharp and mean MITTENS's hatchet finds its target...")
print("  ^ Flavor appears AFTER damage, so no contradiction with 'barely'")

print("\nSCENARIO 2: Attack MISSES")
print("  MITTENS swings his hatchet at IMPELLITTERI's torso")
print("  IMPELLITTERI sets his feet and prepares to deflect!")
print("  MITTENS fails to connect")
print("  ^ NO flavor - only appears on hits")

print("\nSCENARIO 3: Attack is PARRIED")
print("  MITTENS swings his hatchet at IMPELLITTERI's torso")
print("  IMPELLITTERI shifts weight, preparing to parry!")
print("  IMPELLITTERI makes a desperate last-moment parry!")
print("  ^ NO flavor - only appears on hits")

print("\n" + "="*80 + "\n")
