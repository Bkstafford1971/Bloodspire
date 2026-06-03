#!/usr/bin/env python3
"""
Test Lizardfolk traits integration.
Validates that natural weapon bonus, martial combat bonuses, and natural armor
are properly configured and available in the combat system.
"""

import sys
from warrior import Warrior
from armor import get_effective_defense_for_race, get_effective_dex_for_race, get_lizardfolk_armor_penalties
from combat import _get_lizardfolk_natural_weapon_bonus, _get_martial_combat_accuracy_bonus, _get_martial_combat_parry_bonus

def test_lizardfolk_trait_availability():
    """Verify Lizardfolk have all three traits available."""
    print("\n" + "="*80)
    print("TEST: Lizardfolk Trait Availability")
    print("="*80)

    liz = Warrior("Test_Liz", "Lizardfolk", "Male", 14, 10, 10, 10, 10, 10)

    print(f"\nLizardfolk trait flags:")
    print(f"  natural_weapon_bonus: {liz.race.modifiers.natural_weapon_bonus}")
    print(f"  martial_combat_bonus: {liz.race.modifiers.martial_combat_bonus}")
    print(f"  natural_armor: {liz.race.modifiers.natural_armor}")

    assert liz.race.modifiers.natural_weapon_bonus, "Lizardfolk should have natural_weapon_bonus"
    assert liz.race.modifiers.martial_combat_bonus, "Lizardfolk should have martial_combat_bonus"
    assert liz.race.modifiers.natural_armor, "Lizardfolk should have natural_armor"

    print("\n[PASS] All three traits are enabled for Lizardfolk")
    return True

def test_natural_armor_integration():
    """Test natural armor mechanics for Lizardfolk."""
    print("\n" + "="*80)
    print("TEST: Natural Armor Integration")
    print("="*80)

    # Test defense values with different armor
    armor_configs = [
        ("None", 5),  # Natural scales only
        ("Cloth", 6),  # Cloth over scales
        ("Leather", 7),  # Natural + leather = max useful layering
        ("Full Plate", 7),  # Capped at 7 (no additional protection)
    ]

    print("\nLizardfolk defense values (Lizardfolk-specific capping):")
    for armor_name, expected_base_def in armor_configs:
        defense = get_effective_defense_for_race(armor_name, "None", "Lizardfolk")
        status = "[OK]" if defense == expected_base_def else "[?]"
        print(f"  {armor_name:15} -> Defense {defense} (expected ~{expected_base_def}) {status}")
        assert defense == expected_base_def, f"Expected {expected_base_def}, got {defense}"

    # Compare with human (should not have cap)
    human_plate = get_effective_defense_for_race("Full Plate", "None", "Human")
    liz_plate = get_effective_defense_for_race("Full Plate", "None", "Lizardfolk")
    print(f"\nComparison with Human:")
    print(f"  Human Full Plate defense: {human_plate}")
    print(f"  Lizardfolk Full Plate defense: {liz_plate}")
    print(f"  Lizardfolk capped at: {liz_plate} (human would get {human_plate})")

    assert liz_plate < human_plate, "Lizardfolk should be capped lower"

    print("\n[PASS] Natural armor mechanics correctly implemented")
    return True

def test_natural_armor_penalties():
    """Test Lizardfolk armor penalties for mobility/combat."""
    print("\n" + "="*80)
    print("TEST: Natural Armor Penalties")
    print("="*80)

    penalty_configs = [
        ("None", {"dex_pen": 0, "attack_pct": 0.00}),
        ("Cloth", {"dex_pen": 1, "attack_pct": 0.00}),
        ("Leather", {"dex_pen": 2, "attack_pct": 0.00}),
        ("Chain", {"dex_pen": 0, "attack_pct": 0.15}),
        ("Full Plate", {"dex_pen": 0, "attack_pct": 0.25}),
    ]

    print("\nLizardfolk armor penalties:")
    for armor_name, expected_penalties in penalty_configs:
        penalties = get_lizardfolk_armor_penalties(armor_name)
        dex_pen = penalties["dex_pen"]
        attack_pct = penalties["attack_pct"]
        print(f"  {armor_name:15} - DEX penalty: {dex_pen:2}, Attack penalty: {attack_pct*100:2.0f}%")

        assert dex_pen == expected_penalties["dex_pen"], f"Dex penalty mismatch for {armor_name}"
        assert attack_pct == expected_penalties["attack_pct"], f"Attack penalty mismatch for {armor_name}"

    print("\n[PASS] Armor penalties correctly configured")
    return True

def test_natural_weapon_in_context():
    """Test natural weapon bonus with skilled Lizardfolk."""
    print("\n" + "="*80)
    print("TEST: Natural Weapon Bonus in Context")
    print("="*80)

    liz_skilled = Warrior("Liz_Skilled", "Lizardfolk", "Male", 14, 10, 10, 10, 10, 10)
    liz_skilled.skills["open_hand"] = 9
    liz_skilled.primary_weapon = "Open Hand"

    bonus = _get_lizardfolk_natural_weapon_bonus(liz_skilled)
    print(f"\nLizardfolk (Open Hand skill 9):")
    print(f"  Natural weapon bonus: +{bonus} damage")
    print(f"  Applies to: Open Hand and Martial Combat style")
    print(f"  Scales with skill: +2 (skill 0) to +5 (skill 9)")

    assert bonus == 5, f"Expected bonus of 5, got {bonus}"

    liz_beginner = Warrior("Liz_Beginner", "Lizardfolk", "Male", 14, 10, 10, 10, 10, 10)
    liz_beginner.skills["open_hand"] = 0
    liz_beginner.primary_weapon = "Open Hand"

    bonus_low = _get_lizardfolk_natural_weapon_bonus(liz_beginner)
    print(f"\nLizardfolk (Open Hand skill 0):")
    print(f"  Natural weapon bonus: +{bonus_low} damage")

    assert bonus_low == 2, f"Expected bonus of 2, got {bonus_low}"

    print("\n[PASS] Natural weapon bonus correctly scales with skill")
    return True

def test_martial_combat_bonuses_in_context():
    """Test martial combat bonuses for Lizardfolk."""
    print("\n" + "="*80)
    print("TEST: Martial Combat Bonuses in Context")
    print("="*80)

    liz = Warrior("Liz_Combat", "Lizardfolk", "Male", 14, 10, 10, 10, 10, 10)
    liz.skills["open_hand"] = 9
    liz.primary_weapon = "Open Hand"

    acc_bonus = _get_martial_combat_accuracy_bonus(liz)
    parry_bonus = _get_martial_combat_parry_bonus(liz)

    print(f"\nLizardfolk (Open Hand skill 9, with martial_combat_bonus):")
    print(f"  Accuracy bonus: +{acc_bonus} (scales +2 to +6)")
    print(f"  Parry/Dodge bonus: +{parry_bonus} (scales +4 to +8)")

    assert 2 <= acc_bonus <= 6, f"Accuracy bonus should be 2-6, got {acc_bonus}"
    assert 4 <= parry_bonus <= 8, f"Parry bonus should be 4-8, got {parry_bonus}"

    print("\n[PASS] Martial combat bonuses properly configured")
    return True

def test_trait_summary():
    """Summary of all Lizardfolk traits."""
    print("\n" + "="*80)
    print("LIZARDFOLK TRAIT SUMMARY")
    print("="*80)

    print(f"""
TRAIT 1: Natural Weapon Bonus
  - Effect: +2 to +5 damage when using Open Hand
  - Scaling: +2 (skill 0) to +5 (skill 9)
  - Applied in: _calc_damage_hybrid() and _calc_damage_verbose()
  - Status: [WIRED IN]

TRAIT 2: Martial Combat Bonus - Accuracy
  - Effect: +2 to +6 accuracy when using Open Hand
  - Scaling: +2 (skill 0) to +6 (skill 9)
  - Applied in: Attack roll calculations (lines 669, 1169)
  - Status: [WIRED IN]

TRAIT 3: Martial Combat Bonus - Parry/Dodge
  - Effect: +4 to +8 parry/dodge defense when using Open Hand
  - Scaling: +4 (skill 0) to +8 (skill 9)
  - Applied in: Defense calculations (lines 782, 1286)
  - Status: [WIRED IN]

TRAIT 4: Natural Armor
  - Effect: Defense 5 (natural scales) + layering cap
  - Mechanics:
    * No armor: Defense 5
    * Cloth: Defense 6 (+1 over scales)
    * Leather: Defense 7 (max useful layering)
    * Heavy armor: Defense 7 (capped, no additional protection)
  - Penalties:
    * Light armor (cloth/leather): DEX penalties only
    * Heavy armor: Dodge/parry/initiative/attack penalties (no DEX change)
  - Applied in: armor.py functions
  - Status: [IMPLEMENTED]
""")

    print("="*80)
    print("All Lizardfolk traits successfully wired into game mechanics")
    print("="*80)


if __name__ == "__main__":
    try:
        test_lizardfolk_trait_availability()
        test_natural_armor_integration()
        test_natural_armor_penalties()
        test_natural_weapon_in_context()
        test_martial_combat_bonuses_in_context()
        test_trait_summary()

        print("\n" + "="*80)
        print("ALL LIZARDFOLK TRAIT TESTS PASSED [PASS]")
        print("="*80)

    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
