#!/usr/bin/env python3
"""
Test simultaneous strategy triggers fix.
Creates two warriors with triggers designed to fire at the same moment.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from warrior import Warrior, Strategy
from combat import CombatEngine
from narrative import counterstrike_line

# Create AGGRESSOR with high damage output
# Trigger 3: "Your foe has taken heavy damage" → Calculated Attack
aggressor = Warrior(
    name="AGGRESSOR",
    gender="Male",
    race_name="Human",
    strength=18,
    dexterity=14,
    constitution=14,
    intelligence=10,
    presence=10,
    size=10,
)

# Set weapons and equipment
aggressor.primary_weapon = "Warhammer"
aggressor.secondary_weapon = "Open Hand"
aggressor.armor = "Brigandine"
aggressor.helm = "Steel Cap"

# Add some skills
aggressor.skills["bash"] = 4
aggressor.skills["parry"] = 2

# Set up AGGRESSOR's strategies with trigger for "Your foe has taken heavy damage"
aggressor.strategies = [
    Strategy(style="Bash", activity=5, aim_point="Head", defense_point="Chest"),
    Strategy(style="Bash", activity=5, aim_point="Head", defense_point="Chest"),
    Strategy(style="Calculated Attack", activity=4, aim_point="Head", defense_point="Chest"),
    Strategy(style="Bash", activity=5, aim_point="Head", defense_point="Chest"),
]
aggressor.strategies[0].trigger = "Your foe has taken heavy damage"
aggressor.strategies[1].trigger = "You are very tired"
aggressor.strategies[2].trigger = "Your foe has taken heavy damage"
aggressor.strategies[3].trigger = "Always"

# Create DEFENDER with decent durability
# Trigger 2: "You have taken heavy damage" → Wall of Steel
defender = Warrior(
    name="DEFENDER",
    gender="Female",
    race_name="Dwarf",
    strength=12,
    dexterity=10,
    constitution=16,
    intelligence=10,
    presence=10,
    size=10,
)

# Set weapons and equipment
defender.primary_weapon = "Battle Axe"
defender.secondary_weapon = "Target Shield"
defender.armor = "Cuir Boulli"
defender.helm = "Helm"

# Add some skills
defender.skills["parry"] = 3
defender.skills["dodge"] = 1

# Set up DEFENDER's strategies with trigger for "You have taken heavy damage"
defender.strategies = [
    Strategy(style="Wall of Steel", activity=3, aim_point="None", defense_point="Chest"),
    Strategy(style="Wall of Steel", activity=3, aim_point="None", defense_point="Chest"),
    Strategy(style="Strike", activity=3, aim_point="Head", defense_point="Chest"),
    Strategy(style="Martial Combat", activity=4, aim_point="None", defense_point="Chest"),
]
defender.strategies[0].trigger = "You have taken heavy damage"
defender.strategies[1].trigger = "You have taken heavy damage"
defender.strategies[2].trigger = "You are very tired"
defender.strategies[3].trigger = "Always"

print("\n" + "="*80)
print("SIMULTANEOUS TRIGGER TEST - COMBAT SIMULATION")
print("="*80)
print("\nSetup:")
print(f"  AGGRESSOR: {aggressor.name} ({aggressor.race.name} {aggressor.gender})")
print(f"    - Damage-heavy warrior with Warhammer")
print(f"    - Trigger 3: 'Your foe has taken heavy damage' -> Calculated Attack")
print(f"  DEFENDER: {defender.name} ({defender.race.name} {defender.gender})")
print(f"    - Durable warrior with Battle Axe")
print(f"    - Trigger 1/2: 'You have taken heavy damage' -> Wall of Steel")
print("\nExpected behavior:")
print("  When AGGRESSOR deals heavy damage (50%+ of max HP) to DEFENDER:")
print("    - DEFENDER's trigger should fire -> switches to strategy 1/2")
print("    - AGGRESSOR's trigger should ALSO fire -> switches to strategy 2")
print("    - BOTH switches should be emitted CONSECUTIVELY")
print("    - No crowd text or other narrative between them")

try:
    # Create and run the fight
    fight = CombatEngine(
        warrior_a=aggressor,
        warrior_b=defender,
        team_a_name="TEST AGGRESSOR TEAM",
        team_b_name="TEST DEFENDER TEAM",
        manager_a_name="Test Manager A",
        manager_b_name="Test Manager B",
    )

    result = fight.resolve_fight()

    # Extract the fight narrative
    narrative = '\n'.join(fight._lines)

    print("\n" + "="*80)
    print("FIGHT NARRATIVE")
    print("="*80)
    print(narrative)

    # Analyze the narrative for simultaneous triggers
    print("\n" + "="*80)
    print("ANALYSIS")
    print("="*80)

    lines = narrative.split('\n')

    # Find strategy switch lines
    switches = []
    for i, line in enumerate(lines):
        if 'switches to strategy' in line:
            switches.append((i, line.strip()))

    print(f"\nFound {len(switches)} strategy switches:")
    for idx, (line_num, line_text) in enumerate(switches):
        print(f"  {idx + 1}. Line {line_num}: {line_text}")

    # Check if any two consecutive switches are adjacent (indicating simultaneous emission)
    if len(switches) >= 2:
        print("\nChecking for simultaneous triggers...")
        for i in range(len(switches) - 1):
            curr_line, curr_text = switches[i]
            next_line, next_text = switches[i + 1]

            # Check if these switches are consecutive (no other narrative between them)
            between = '\n'.join(lines[curr_line + 1:next_line])

            # Count non-empty lines between them
            between_lines = [l.strip() for l in between.split('\n') if l.strip() and not l.startswith('* ')]

            if len(between_lines) == 0:
                print(f"  [OK] Lines {curr_line} and {next_line}: CONSECUTIVE (no narrative between)")
                print(f"    {curr_text}")
                print(f"    {next_text}")
            else:
                print(f"  [FAIL] Lines {curr_line} and {next_line}: SEPARATED")
                print(f"    {curr_text}")
                print(f"    Between them:")
                for l in between_lines[:3]:  # Show first 3 lines between
                    print(f"      - {l}")
                print(f"    {next_text}")

except Exception as e:
    print(f"\nError during fight simulation: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80 + "\n")
