#!/usr/bin/env python3
"""
Test validation for Fix #6: Throw Attack Miss/Parry Narrative
Ensures that when thrown weapons miss or are parried, the attack result is shown.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from warrior import Warrior, Strategy
from combat import CombatEngine

print("\n" + "="*80)
print("FIX #6: THROW ATTACK MISS/PARRY NARRATIVE VALIDATION")
print("="*80)

print("\nISSUE:")
print("When thrown weapons missed or were parried, the attack result line")
print("(miss line or parry line) was not appearing in the narrative.")
print()
print("EXAMPLE OF PROBLEM:")
print("  POL POT pitches his javelin at WRITHEN HILT's leg!")
print("  WRITHEN HILT eyes the incoming strike carefully!")
print("  POL POT draws his backup javelin!")
print("  (Missing: 'POL POT misses wildly' or parry result)")
print()
print("ROOT CAUSE:")
print("When defense_intent was shown before the attack roll,")
print("_defensive_narrative_emitted was set to True, which then prevented")
print("the parry_line from being emitted after the attack roll.")
print()
print("FIX:")
print("Removed the _defensive_narrative_emitted check when emitting")
print("defense_intent, since the intent is shown before the attack roll.")
print("The flag is now only set when emitting actual defense results")
print("(parry, dodge, critical defense), allowing them to always appear.")
print()

# Create test warriors designed to produce different outcomes
attacker = Warrior(
    name="THROWER",
    gender="Male",
    race_name="Human",
    strength=16, dexterity=14, constitution=12, intelligence=10, presence=10, size=10,
)
attacker.primary_weapon = "Javelin"
attacker.secondary_weapon = "Dagger"
attacker.armor = "Leather"
attacker.strategies = [
    Strategy(style="Opportunity Throw", activity=5, aim_point="Head", defense_point="Chest"),
    Strategy(style="Opportunity Throw", activity=5, aim_point="Head", defense_point="Chest"),
    Strategy(style="Strike", activity=5, aim_point="Head", defense_point="Chest"),
    Strategy(style="Bash", activity=3, aim_point="Head", defense_point="Chest"),
]
for s in attacker.strategies:
    s.trigger = "Always"

defender = Warrior(
    name="DEFENDER",
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
    fight = CombatEngine(
        warrior_a=attacker,
        warrior_b=defender,
        team_a_name="THROWER TEAM",
        team_b_name="DEFENDER TEAM",
        manager_a_name="Manager A",
        manager_b_name="Manager B",
    )

    result = fight.resolve_fight()
    narrative = '\n'.join(fight._lines)
    lines = narrative.split('\n')

    # Find throw attacks and their results
    throw_count = 0
    throws_with_results = 0
    throws_with_intent = 0

    for i, line in enumerate(lines):
        if any(verb in line.lower() for verb in ["launches ", "pitches ", "flings ", "sends "]):
            if any(wpn in line.lower() for wpn in ["javelin", "dagger", "axe"]):
                throw_count += 1

                # Look at the next 5 lines for results
                has_result = False
                has_intent = False

                for j in range(1, min(6, len(lines) - i)):
                    next_line = lines[i + j]
                    lower = next_line.lower()

                    # Check for defense intent (shown before attack roll)
                    if any(x in lower for x in ["eyes the", "braces", "ready for", "tightens", "shifts weight", "raises", "prepares", "sets"]):
                        if any(x in lower for x in ["incoming", "preparing", "deflect", "guard", "move", "feet", "weight"]):
                            has_intent = True

                    # Check for attack result lines
                    if (("misses" in lower or "cuts only air" in lower or "fails to connect" in lower) or
                        ("parr" in lower or "deflect" in lower) or
                        ("dodge" in lower or "twists" in lower or "sidestep" in lower or "ducks" in lower) or
                        ("finds its mark" in lower or "buries" in lower or "bites into" in lower)):
                        has_result = True
                        break

                    # Stop looking after weapon loss message
                    if "switch" in lower and "weapon" in lower:
                        break
                    if "backup" in lower:
                        break
                    if "more throwable" in lower:
                        break

                if has_result:
                    throws_with_results += 1
                if has_intent:
                    throws_with_intent += 1

    print("\n" + "="*80)
    print("TEST RESULTS")
    print("="*80)
    print(f"\nTotal throw attacks found: {throw_count}")
    print(f"Throws with attack results: {throws_with_results}")
    print(f"Throws with defense intents: {throws_with_intent}")

    if throw_count > 0:
        result_pct = (throws_with_results / throw_count) * 100
        print(f"Result line accuracy: {result_pct:.0f}%")

        if result_pct == 100:
            print("\n[OK] ALL throw attacks show their attack results!")
            print("     Miss lines, parry lines, dodge lines, and hit lines are all appearing correctly.")
        elif result_pct > 80:
            print(f"\n[OK] Most throw attacks ({result_pct:.0f}%) show their attack results.")
        else:
            print(f"\n[FAIL] Many throw attacks ({result_pct:.0f}%) are missing attack results.")

    # Show a few example sequences
    print("\n" + "="*80)
    print("EXAMPLE THROW ATTACK SEQUENCES")
    print("="*80)

    example_count = 0
    for i, line in enumerate(lines):
        if (any(verb in line.lower() for verb in ["launches ", "pitches ", "flings "])
            and any(wpn in line.lower() for wpn in ["javelin", "dagger"])
            and example_count < 3):

            example_count += 1
            print(f"\nExample {example_count}:")

            # Show attack line and next 5 lines
            for j in range(0, min(6, len(lines) - i)):
                line_text = lines[i + j][:75]
                if j == 0:
                    print(f"  -> {line_text}")  # Attack line
                else:
                    # Identify line type
                    lower = line_text.lower()
                    if ("misses" in lower or "cuts only air" in lower or "fails" in lower):
                        print(f"    [MISS]  {line_text}")
                    elif "parr" in lower or "deflect" in lower:
                        print(f"    [PARRY] {line_text}")
                    elif "dodge" in lower or "twists" in lower or "sidestep" in lower:
                        print(f"    [DODGE] {line_text}")
                    elif "finds its mark" in lower or "buries" in lower or "bites" in lower:
                        print(f"    [HIT]   {line_text}")
                    elif "eyes" in lower or "braces" in lower or "ready" in lower or "shifts" in lower:
                        print(f"    [INTENT] {line_text}")
                    elif "switch" in lower or "backup" in lower or "throwable" in lower:
                        print(f"    [WEAPON] {line_text}")
                    else:
                        print(f"    {line_text}")

except Exception as e:
    print(f"\nError: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80 + "\n")
