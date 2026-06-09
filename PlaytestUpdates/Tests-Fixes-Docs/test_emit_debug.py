#!/usr/bin/env python3
"""
Debug test to track what's being emitted during throw attacks.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from warrior import Warrior, Strategy
from combat import CombatEngine

# Monkey-patch the _emit function to log what's being emitted
original_resolve_action = None
emit_log = []

def debug_emit(self, line: str):
    emit_log.append(line)
    self._lines.append(line)

# Apply monkey patch
CombatEngine._emit = debug_emit

# Create test warriors
attacker = Warrior(
    name="POL POT",
    gender="Male",
    race_name="Human",
    strength=16, dexterity=14, constitution=12, intelligence=10, presence=10, size=10,
)
attacker.primary_weapon = "Javelin"
attacker.secondary_weapon = "Dagger"
attacker.armor = "Leather"
attacker.strategies = [
    Strategy(style="Opportunity Throw", activity=5, aim_point="Head", defense_point="Chest"),
    Strategy(style="Strike", activity=5, aim_point="Head", defense_point="Chest"),
    Strategy(style="Bash", activity=3, aim_point="Head", defense_point="Chest"),
    Strategy(style="Bash", activity=3, aim_point="Head", defense_point="Chest"),
]
for s in attacker.strategies:
    s.trigger = "Always"

defender = Warrior(
    name="WRITHEN HILT",
    gender="Male",
    race_name="Elf",
    strength=10, dexterity=18, constitution=12, intelligence=12, presence=10, size=10,
)
defender.primary_weapon = "Battle Axe"
defender.armor = "None"
defender.strategies = [
    Strategy(style="Strike", activity=5, aim_point="Head", defense_point="Chest"),
    Strategy(style="Dodge Counter", activity=3, aim_point="Head", defense_point="Chest"),
    Strategy(style="Bash", activity=4, aim_point="Head", defense_point="Chest"),
    Strategy(style="Martial Combat", activity=4, aim_point="None", defense_point="Chest"),
]
for s in defender.strategies:
    s.trigger = "Always"

try:
    # Run just one round
    fight = CombatEngine(
        warrior_a=attacker,
        warrior_b=defender,
        team_a_name="TEST A",
        team_b_name="TEST B",
        manager_a_name="Manager A",
        manager_b_name="Manager B",
    )

    # Run the full fight
    result = fight.resolve_fight()

    # Find throw attacks in the emit log
    print("="*80)
    print("EMIT LOG ANALYSIS - Looking for Throw Attacks")
    print("="*80)

    for i, line in enumerate(emit_log):
        # Look for "launches", "pitches", or "flings" in attack lines (thrown weapon attacks)
        is_throw_attack = any(x in line.lower() for x in ["launches ", "pitches ", "flings ", "sends "])
        is_weapon_attack = any(x in line.lower() for x in ["javelin", "dagger"])
        if is_throw_attack and is_weapon_attack and "weapon" not in line.lower():
            print(f"\nFound throw attack at line {i}: {line}")

            # Show the following 15 lines with full content
            print("Following emits (showing next 15 lines):")
            has_attack_result = False
            for j in range(i+1, min(i+16, len(emit_log))):
                next_line = emit_log[j]
                marker = ""

                # Try to identify what type of line this is
                if "misses" in next_line.lower() or "cuts only air" in next_line.lower() or "fails to connect" in next_line.lower():
                    marker = " [MISS LINE]"
                    has_attack_result = True
                elif "parr" in next_line.lower() and "barely" not in next_line.lower():
                    marker = " [PARRY LINE]"
                    has_attack_result = True
                elif "dodge" in next_line.lower() or "twists" in next_line.lower() or "sidestep" in next_line.lower() or "ducks" in next_line.lower():
                    marker = " [DODGE LINE]"
                    has_attack_result = True
                elif "finds its mark" in next_line.lower() or "buries" in next_line.lower() or "bites into" in next_line.lower():
                    marker = " [HIT LINE]"
                    has_attack_result = True
                elif "barely grazes" in next_line.lower():
                    marker = " [GRAZE LINE]"
                    has_attack_result = True
                elif "switch" in next_line.lower() and ("weapon" in next_line.lower() or "backup" in next_line.lower()):
                    marker = " [WEAPON LOSS]"
                elif "eyes the" in next_line.lower() or "braces" in next_line.lower() or "ready for" in next_line.lower() or "tightens" in next_line.lower():
                    marker = " [DEFENSE INTENT]"
                elif "Blood" in next_line or "puncture" in next_line or "slash" in next_line or "wound" in next_line or "chop" in next_line:
                    marker = " [DAMAGE LINE]"
                    has_attack_result = True

                print(f"  {j}: {next_line[:70]}{marker}")

            if not has_attack_result:
                print("  WARNING: NO ATTACK RESULT FOUND!")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80)
print(f"Total emitted lines: {len(emit_log)}")
print("="*80 + "\n")
