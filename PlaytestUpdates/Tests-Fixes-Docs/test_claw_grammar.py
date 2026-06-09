#!/usr/bin/env python3
"""
Test that Lizardfolk and Tabaxi attack lines have proper grammar.
"""

import narrative as N
from warrior import Strategy

print("="*80)
print("MARTIAL COMBAT GRAMMAR TEST")
print("="*80)

# Test Lizardfolk attack lines
print("\n1. LIZARDFOLK ATTACK LINES:\n")

strategy = Strategy(style="Stand & Strike", aim_point="Chest")

for i in range(10):
    line = N.attack_line("Slythe", "Malrik Salvor", "Open Hand", "Oddball",
                        "Stand & Strike", "Chest", "Male", attacker_race="Lizardfolk")
    print(f"  {line}")

# Test Tabaxi attack lines
print("\n2. TABAXI ATTACK LINES:\n")

for i in range(10):
    line = N.attack_line("Whiskers", "Granite Stone", "Open Hand", "Oddball",
                        "Strike", "Abdomen", "Male", attacker_race="Tabaxi")
    print(f"  {line}")

# Test non-claw attacks (should use standard format)
print("\n3. STANDARD ATTACK LINES (non-Open Hand):\n")

for i in range(5):
    line = N.attack_line("Slythe", "Malrik Salvor", "Longsword", "Sword/Knife",
                        "Slash", "Head", "Male", attacker_race="Lizardfolk")
    print(f"  {line}")

print("\n" + "="*80)
print("EXPECTED IMPROVEMENTS:")
print("="*80)
print("""
BEFORE (Bad Grammar):
  SLYTHE slashes at with claws MALRIK SALVOR's body!

AFTER (Good Grammar):
  Slythe's claws slash at Malrik Salvor's body!

Format: {Name}'s {weapon} {verb} at {Target}'s {location}!

Examples:
  [OK] Slythe's claws rake at Malrik Salvor's chest!
  [OK] Whiskers's claws tear at Granite Stone's abdomen!
  [OK] Slythe's tail sweeps at Malrik Salvor's legs!
  [OK] Whiskers's leg kicks at Granite Stone's head!
""")
