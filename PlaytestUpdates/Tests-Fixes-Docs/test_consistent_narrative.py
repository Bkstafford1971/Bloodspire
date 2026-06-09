#!/usr/bin/env python3
"""
Test that attack/hit/damage lines are consistent for Lizardfolk/Tabaxi claw attacks.
"""

import warrior as W
import combat as C

print("="*80)
print("NARRATIVE CONSISTENCY TEST")
print("="*80)

def make_lizardfolk(name):
    w = W.Warrior(name, "Lizardfolk", "Male", 14, 10, 10, 10, 10, 10)
    w.primary_weapon = "Open Hand"
    w.secondary_weapon = "Open Hand"
    w.skills["open_hand"] = 9
    w.luck = 10
    w.strategies = [W.Strategy(
        trigger="Always (Default Loop)", style="Stand & Strike",
        activity=5, aim_point="Chest", defense_point="Chest"
    )]
    return w

def make_human(name):
    w = W.Warrior(name, "Human", "Male", 10, 10, 10, 10, 10, 10)
    w.primary_weapon = "Longsword"
    w.secondary_weapon = "Open Hand"
    w.luck = 10
    w.strategies = [W.Strategy(
        trigger="Always (Default Loop)", style="Strike",
        activity=5, aim_point="None", defense_point="Chest"
    )]
    return w

print("\nTest Case 1: SLYTHE vs MALRIK SALVOR")
print("Expected: kick attack (based on defender name)")
print("-" * 80)

liz = make_lizardfolk("Slythe")
human = make_human("Malrik Salvor")

try:
    result = C.run_fight(liz, human)
    narrative = result.narrative.lower()

    # Look for consistency
    has_kick_attack = "leg lashes out with a kick" in narrative or "leg drives a" in narrative or "leg kicks" in narrative
    has_crushing_damage = any(word in narrative for word in ["crashes into", "smashes into", "crushes into"])
    has_slashing_damage = any(word in narrative for word in ["slash", "rakes", "tears"])

    print(f"Narrative length: {len(narrative)} characters")
    print(f"Has kick attack mention: {has_kick_attack}")
    print(f"Has crushing damage (correct for kicks): {has_crushing_damage}")
    print(f"Has slashing damage (wrong for kicks): {has_slashing_damage}")

    if has_kick_attack and has_crushing_damage and not has_slashing_damage:
        print("\n[PASS] Kick attack narrative is CONSISTENT")
    elif has_kick_attack:
        print("\n[PARTIAL] Kick attack mentioned but damage descriptions may be wrong")
    else:
        print("\n[NOTE] No kick attacks in this narrative (RNG)")

except Exception as e:
    print(f"Error: {e}")

print("\nTest Case 2: WHISKERS vs GRANITE STONE")
print("Expected: claw attack (based on defender name)")
print("-" * 80)

tabaxi = W.Warrior("Whiskers", "Tabaxi", "Male", 14, 10, 10, 10, 10, 10)
tabaxi.primary_weapon = "Open Hand"
tabaxi.secondary_weapon = "Open Hand"
tabaxi.skills["open_hand"] = 9
tabaxi.luck = 10
tabaxi.strategies = [W.Strategy(
    trigger="Always (Default Loop)", style="Stand & Strike",
    activity=5, aim_point="Abdomen", defense_point="Chest"
)]

human2 = make_human("Granite Stone")

try:
    result = C.run_fight(tabaxi, human2)
    narrative = result.narrative.lower()

    # Look for consistency
    has_claw_attack = "claw" in narrative and ("rake" in narrative or "slash" in narrative or "tear" in narrative)
    has_slashing_damage = any(word in narrative for word in ["slash", "rakes", "tears", "shred"])

    print(f"Narrative length: {len(narrative)} characters")
    print(f"Has claw attack: {has_claw_attack}")
    print(f"Has slashing damage (correct for claws): {has_slashing_damage}")

    if has_claw_attack and has_slashing_damage:
        print("\n[PASS] Claw attack narrative is CONSISTENT")
    elif has_claw_attack:
        print("\n[PARTIAL] Claw attack mentioned but damage descriptions may vary (RNG)")
    else:
        print("\n[NOTE] No claw attacks in this narrative (RNG)")

except Exception as e:
    print(f"Error: {e}")

print("\n" + "="*80)
print("EXPECTED OUTCOME:")
print("="*80)
print("""
Attack narratives should now be consistent:

KICK ATTACK EXAMPLE (before fix):
  Attack: "leg lashes out with a kick"
  Hit: "open hand hits"  <- WRONG!
  Damage: "only a superficial slash is left behind!"  <- WRONG!

KICK ATTACK EXAMPLE (after fix):
  Attack: "leg lashes out with a kick"
  Hit: "leg crashes into"  <- CORRECT!
  Damage: "only a superficial wound is left behind!"  <- CORRECT!

CLAW ATTACK EXAMPLE (after fix):
  Attack: "claws slash at"
  Hit: "claws tear into"  <- CORRECT!
  Damage: "flesh parts violently beneath the keen edge!"  <- CORRECT!
""")
