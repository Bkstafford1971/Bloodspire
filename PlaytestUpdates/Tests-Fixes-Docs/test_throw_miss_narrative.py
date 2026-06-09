#!/usr/bin/env python3
"""
Test Opportunity Throw miss narrative.
Reproduces the issue where thrown attacks that miss don't show a miss line.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from warrior import Warrior, Strategy
from combat import CombatEngine

print("\n" + "="*80)
print("OPPORTUNITY THROW MISS NARRATIVE TEST")
print("="*80)

# Create ATTACKER with javelin for throwing
attacker = Warrior(
    name="POL POT",
    gender="Male",
    race_name="Human",
    strength=16,
    dexterity=14,
    constitution=12,
    intelligence=10,
    presence=10,
    size=10,
)

# Set weapons - javelin is throwable
attacker.primary_weapon = "Javelin"
attacker.secondary_weapon = "Dagger"
attacker.armor = "Leather"
attacker.helm = "None"

# Add some skills
attacker.skills["throw"] = 2
attacker.skills["dodge"] = 1

# Set up ATTACKER's strategy to use Opportunity Throw
attacker.strategies = [
    Strategy(style="Opportunity Throw", activity=5, aim_point="Head", defense_point="Chest"),
    Strategy(style="Opportunity Throw", activity=5, aim_point="Head", defense_point="Chest"),
    Strategy(style="Strike", activity=5, aim_point="Head", defense_point="Chest"),
    Strategy(style="Bash", activity=3, aim_point="Head", defense_point="Chest"),
]
for i, strat in enumerate(attacker.strategies):
    strat.trigger = "Always"

# Create DEFENDER with high dodge to make the throw miss
defender = Warrior(
    name="WRITHEN HILT",
    gender="Male",
    race_name="Elf",
    strength=10,
    dexterity=18,  # High dexterity to dodge throws
    constitution=12,
    intelligence=12,
    presence=10,
    size=10,
)

# Set weapons and equipment
defender.primary_weapon = "Battle Axe"
defender.secondary_weapon = "None"
defender.armor = "None"
defender.helm = "None"

# Add skills
defender.skills["dodge"] = 4  # High dodge to help miss the throw
defender.skills["parry"] = 1

# Set up DEFENDER's strategies
defender.strategies = [
    Strategy(style="Strike", activity=5, aim_point="Head", defense_point="Chest"),
    Strategy(style="Bash", activity=4, aim_point="Head", defense_point="Chest"),
    Strategy(style="Dodge Counter", activity=3, aim_point="Head", defense_point="Chest"),
    Strategy(style="Martial Combat", activity=4, aim_point="None", defense_point="Chest"),
]
for i, strat in enumerate(defender.strategies):
    strat.trigger = "Always"

try:
    # Create and run the fight
    fight = CombatEngine(
        warrior_a=attacker,
        warrior_b=defender,
        team_a_name="TEST ATTACKER",
        team_b_name="TEST DEFENDER",
        manager_a_name="Test Manager A",
        manager_b_name="Test Manager B",
    )

    result = fight.resolve_fight()

    # Extract the fight narrative
    narrative = '\n'.join(fight._lines)

    print("\nFIGHT NARRATIVE (First 50 lines):")
    print("="*80)
    lines = narrative.split('\n')
    for i, line in enumerate(lines[:50], 1):
        print(f"{i:3d}: {line}")

    # Analyze the narrative for Opportunity Throw actions
    print("\n" + "="*80)
    print("ANALYSIS")
    print("="*80)

    print("\nSearching for Opportunity Throw attacks...")
    throw_lines = []
    for i, line in enumerate(lines):
        if "pitches" in line.lower() or "javelin" in line.lower():
            throw_lines.append((i, line))

    if throw_lines:
        print(f"Found {len(throw_lines)} throw action lines:")
        for line_idx, line_text in throw_lines:
            print(f"\n  Line {line_idx}: {line_text}")

            # Look at following 5 lines to see what comes after
            print(f"  Following lines (including blank):")
            for j in range(1, min(6, len(lines) - line_idx)):
                next_line = lines[line_idx + j]
                # Show all lines, but mark blank ones clearly
                if not next_line.strip():
                    print(f"    Line {line_idx + j}: [BLANK LINE]")
                    continue
                else:
                    print(f"    Line {line_idx + j}: {next_line}")

                    # Check if this is a miss, hit, parry, or other result
                    if "misses" in next_line.lower() or "cuts only air" in next_line.lower() or "fails to connect" in next_line.lower():
                        print(f"    [OK] MISS LINE FOUND")
                    elif "finds" in next_line.lower() and "mark" in next_line.lower():
                        print(f"    [OK] HIT LINE FOUND")
                    elif "parri" in next_line.lower() or "dodge" in next_line.lower():
                        print(f"    [OK] PARRY/DODGE LINE FOUND")
                    elif "weapon" in next_line.lower() or "backup" in next_line.lower():
                        print(f"    - Weapon loss message (not a result)")
                    elif "swings" in next_line.lower() or "strikes" in next_line.lower():
                        print(f"    - Next action (this indicates attack result is missing!)")
                        break
    else:
        print("No throw actions found in narrative")

except Exception as e:
    print(f"\nError during fight simulation: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80)
print("EXPECTED vs ACTUAL")
print("="*80)

print("\nEXPECTED (correct) sequence for missed throw:")
print("  1. 'POL POT pitches his javelin...' (attack line)")
print("  2. 'WRITHEN HILT eyes...' or similar (defense intent)")
print("  3. 'POL POT misses wildly' or similar (MISS LINE) <-- CURRENTLY MISSING!")
print("  4. 'POL POT draws his backup...' (weapon loss)")
print("  5. Next action")

print("\nACTUAL (broken) sequence:")
print("  1. 'POL POT pitches his javelin...' (attack line)")
print("  2. 'WRITHEN HILT eyes...' (defense intent)")
print("  3. 'POL POT draws his backup...' (weapon loss)")
print("  4. Next action (NO MISS LINE!)")

print("\n" + "="*80 + "\n")
