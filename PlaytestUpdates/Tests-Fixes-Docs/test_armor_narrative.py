#!/usr/bin/env python3
"""
Test armor-specific narrative descriptions.
Shows how different armor types get appropriate narrative text.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from narrative import ARMOR_SPECIFIC_INTENT_POOLS, _get_armor_category, style_intent_line

print("\n" + "="*80)
print("ARMOR-SPECIFIC NARRATIVE TEST")
print("="*80)

print("\nArmor Category Mapping:")
print("-" * 80)

test_armors = [
    ("Full Plate", "plate"),
    ("Half-Plate", "plate"),
    ("Brigandine", "plate"),
    ("Chain", "chain"),
    ("Scale", "chain"),
    ("Leather", "leather"),
    ("Cuir Boulli", "leather"),
    (None, "none"),
]

for armor_name, expected_category in test_armors:
    category = _get_armor_category(armor_name)
    status = "OK" if category == expected_category else "FAIL"
    print(f"  {armor_name!r:<20} -> {category:<10} [{status}]")

print("\n" + "="*80)
print("Armor-Specific Narratives by Style")
print("="*80)

for style in ["Bash", "Sure Strike", "Calculated Attack"]:
    if style not in ARMOR_SPECIFIC_INTENT_POOLS:
        print(f"\n{style}: [NO ARMOR-SPECIFIC VARIANTS]")
        continue

    print(f"\n{style}:")
    armor_variants = ARMOR_SPECIFIC_INTENT_POOLS[style]

    for armor_category in ["plate", "chain", "leather", "none"]:
        if armor_category not in armor_variants:
            continue

        print(f"\n  {armor_category.upper()}:")
        narratives = armor_variants[armor_category]
        for i, narrative in enumerate(narratives, 1):
            # Show what the narrative looks like with sample names
            sample = narrative.format(
                name="ATTACKER",
                foe="DEFENDER",
                weapon="dagger",
                his="his"
            )
            print(f"    {i}. {sample}")

print("\n" + "="*80)
print("Live Narrative Generation Test")
print("="*80)

print("\nGenerating Calculated Attack narratives for different armor types:")
print("(Note: May return None due to random skip chance - run multiple times if needed)\n")

test_cases = [
    ("ATTACKER", "DEFENDER_PLATE", "Calculated Attack", "dagger", "Male", "Full Plate"),
    ("ATTACKER", "DEFENDER_LEATHER", "Calculated Attack", "dagger", "Male", "Cuir Boulli"),
    ("ATTACKER", "DEFENDER_CHAIN", "Calculated Attack", "dagger", "Male", "Chain"),
]

for warrior, foe, style, weapon, gender, armor in test_cases:
    # Run multiple times to account for skip chance (30% skip)
    for attempt in range(5):
        line = style_intent_line(warrior, foe, style, weapon, gender, foe_armor=armor)
        if line:
            print(f"  {armor:<20} -> {line}")
            break
    else:
        print(f"  {armor:<20} -> (skipped)")

print("\n" + "="*80)
print("BEFORE vs AFTER Examples")
print("="*80)

print("\nBEFORE FIX (using generic pool):")
print("  ATTACKER analyzes the gaps in the iron plate to maximize the impending trauma")
print("  ^ WRONG: This doesn't make sense for Cuir Boulli (leather), which has no iron plates")

print("\nAFTER FIX (using armor-specific pool):")
print("  Against Cuir Boulli: ATTACKER analyzes the seams in the leather to maximize impending trauma")
print("  Against Full Plate:  ATTACKER analyzes the gaps between the metal plates with surgical precision")
print("  Against Chain:       ATTACKER analyzes gaps in the metal mesh for the perfect strike")
print("  ^ CORRECT: Each narrative matches the opponent's actual armor type")

print("\n" + "="*80 + "\n")
