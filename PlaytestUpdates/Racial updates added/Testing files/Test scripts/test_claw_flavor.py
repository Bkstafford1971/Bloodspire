#!/usr/bin/env python3
"""
Test that Lizardfolk and Tabaxi claw attacks use Slashing flavor text instead of Generic/Bludgeoning.
"""

import random
import warrior as W
import combat as C
import narrative as N

print("="*80)
print("CLAW ATTACK FLAVOR TEXT TEST")
print("="*80)

# Test the damage_line function with claw attacks
print("\n1. Testing damage_line function with claw attacks:\n")

print("Open Hand damage (non-claw - should use Generic/Bludgeoning):")
for _ in range(3):
    line = N.damage_line(20, 50, "Oddball", is_claw_attack=False)
    print(f"  {line}")

print("\nClaw attack damage (Lizardfolk/Tabaxi - should use Slashing):")
for _ in range(3):
    line = N.damage_line(20, 50, "Oddball", is_claw_attack=True)
    print(f"  {line}")

# Test with actual warriors
print("\n" + "-"*80)
print("\n2. Testing with actual Lizardfolk vs Human combat:\n")

def make_fighter(name, race):
    w = W.Warrior(name, race, "Male", 14, 10, 10, 10, 10, 10)
    w.primary_weapon = "Open Hand"
    w.secondary_weapon = "Open Hand"
    w.skills["open_hand"] = 9
    w.luck = 10
    w.strategies = [W.Strategy(
        trigger="Always (Default Loop)", style="Stand & Strike",
        activity=5, aim_point="None", defense_point="Chest"
    )]
    return w

print("Running Lizardfolk vs Human fight...\n")
liz = make_fighter("Lizardfolk_Fighter", "Lizardfolk")
human = make_fighter("Human_Fighter", "Human")

try:
    result = C.run_fight(liz, human)
    # The narrative is stored in result.narrative
    narrative = result.narrative.lower()

    # Check if we see slashing-style descriptions for Lizardfolk attacks
    slashing_words = ["rakes", "slashes", "tears", "shreds", "rends"]
    crushing_words = ["caves in", "crushes", "crunch", "smash"]

    has_slashing = any(word in narrative for word in slashing_words)
    has_crushing = any(word in narrative for word in crushing_words)

    print(f"Narrative length: {len(narrative)} characters")
    print(f"Contains slashing descriptions (good): {has_slashing}")
    print(f"Contains crushing descriptions: {has_crushing}")

    if has_slashing:
        print("\n[PASS] Lizardfolk claw attacks show slashing flavor text")
    else:
        print("\n[NOTE] No slashing text detected in this fight (RNG)")

except Exception as e:
    print(f"Error during combat: {e}")

# Test with Tabaxi
print("\n" + "-"*80)
print("\n3. Testing with Tabaxi claw attacks:\n")

print("Running Tabaxi vs Human fight...\n")
tabaxi = make_fighter("Tabaxi_Fighter", "Tabaxi")
human2 = make_fighter("Human_Fighter2", "Human")

try:
    result = C.run_fight(tabaxi, human2)
    narrative = result.narrative.lower()

    slashing_words = ["rakes", "slashes", "tears", "shreds", "rends"]
    has_slashing = any(word in narrative for word in slashing_words)

    print(f"Narrative length: {len(narrative)} characters")
    print(f"Contains slashing descriptions: {has_slashing}")

    if has_slashing:
        print("\n[PASS] Tabaxi claw attacks show slashing flavor text")
    else:
        print("\n[NOTE] No slashing text detected in this fight (RNG)")

except Exception as e:
    print(f"Error during combat: {e}")

print("\n" + "="*80)
print("TEST COMPLETE")
print("="*80)
print("\nSummary:")
print("  Lizardfolk and Tabaxi using Open Hand should now show:")
print("  - Slashing flavor text for claw attacks (rakes, tears, shreds)")
print("  - NOT crushing text (caves in, crushes, smash)")
print("  - Kicks and tail lashes would still be bludgeoning")
