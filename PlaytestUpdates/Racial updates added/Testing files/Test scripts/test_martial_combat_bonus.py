#!/usr/bin/env python3
"""
Test Martial Combat Bonus effectiveness for Lizardfolk and Halflings.
Validates accuracy and parry bonuses are properly applied.
"""

import sys
from warrior import Warrior
from strategy import Strategy
from combat import (
    _get_martial_combat_accuracy_bonus,
    _get_martial_combat_parry_bonus,
    _has_martial_combat_bonus,
    _is_using_martial_combat
)

def test_martial_combat_bonus_availability():
    """Test that Lizardfolk and Halflings have martial_combat_bonus."""
    print("\n" + "="*80)
    print("TEST: Martial Combat Bonus Availability")
    print("="*80)

    # Races that should have the bonus
    races_with_bonus = ["Lizardfolk", "Halfling"]
    races_without_bonus = ["Human", "Elf", "Gnome", "Goblin"]

    print("\nRaces WITH martial_combat_bonus:")
    for race in races_with_bonus:
        warrior = Warrior(f"{race}_Test", race, "Male", 10, 10, 10, 10, 10, 10)
        has_bonus = _has_martial_combat_bonus(warrior)
        print(f"  {race}: {has_bonus} [CORRECT]")
        assert has_bonus, f"{race} should have martial_combat_bonus"

    print("\nRaces WITHOUT martial_combat_bonus:")
    for race in races_without_bonus:
        warrior = Warrior(f"{race}_Test", race, "Male", 10, 10, 10, 10, 10, 10)
        has_bonus = _has_martial_combat_bonus(warrior)
        print(f"  {race}: {has_bonus} [CORRECT]")
        assert not has_bonus, f"{race} shouldn't have martial_combat_bonus"

    print("\n[PASS] Martial combat bonus correctly assigned to Lizardfolk and Halflings")
    return True


def test_martial_combat_accuracy_bonus():
    """Test accuracy bonus scaling with Open Hand skill."""
    print("\n" + "="*80)
    print("TEST: Martial Combat Accuracy Bonus Scaling")
    print("="*80)

    for race in ["Lizardfolk", "Halfling"]:
        # Low skill
        warrior_low = Warrior(f"{race}_Low", race, "Male", 10, 10, 10, 10, 10, 10)
        warrior_low.skills["open_hand"] = 0
        warrior_low.primary_weapon = "Open Hand"

        # High skill
        warrior_high = Warrior(f"{race}_High", race, "Male", 10, 10, 10, 10, 10, 10)
        warrior_high.skills["open_hand"] = 9
        warrior_high.primary_weapon = "Open Hand"

        acc_low = _get_martial_combat_accuracy_bonus(warrior_low)
        acc_high = _get_martial_combat_accuracy_bonus(warrior_high)

        print(f"\n{race}:")
        print(f"  Skill 0: +{acc_low} accuracy")
        print(f"  Skill 9: +{acc_high} accuracy")

        assert acc_low >= 2, f"{race} low skill should be at least +2"
        assert acc_high >= 6, f"{race} high skill should be at least +6"
        assert acc_high > acc_low, f"Accuracy should scale with skill"

    print("\n[PASS] Accuracy bonus correctly scales with Open Hand skill")
    return True


def test_martial_combat_parry_bonus():
    """Test parry bonus scaling with Open Hand skill."""
    print("\n" + "="*80)
    print("TEST: Martial Combat Parry/Dodge Bonus Scaling")
    print("="*80)

    for race in ["Lizardfolk", "Halfling"]:
        # Low skill
        warrior_low = Warrior(f"{race}_Low", race, "Male", 10, 10, 10, 10, 10, 10)
        warrior_low.skills["open_hand"] = 0
        warrior_low.primary_weapon = "Open Hand"

        # High skill
        warrior_high = Warrior(f"{race}_High", race, "Male", 10, 10, 10, 10, 10, 10)
        warrior_high.skills["open_hand"] = 9
        warrior_high.primary_weapon = "Open Hand"

        parry_low = _get_martial_combat_parry_bonus(warrior_low)
        parry_high = _get_martial_combat_parry_bonus(warrior_high)

        print(f"\n{race}:")
        print(f"  Skill 0: +{parry_low} parry/dodge")
        print(f"  Skill 9: +{parry_high} parry/dodge")

        assert parry_low >= 4, f"{race} low skill should be at least +4"
        assert parry_high >= 8, f"{race} high skill should be at least +8"
        assert parry_high > parry_low, f"Parry should scale with skill"

    print("\n[PASS] Parry/dodge bonus correctly scales with Open Hand skill")
    return True


def test_bonus_requires_open_hand():
    """Test that martial combat bonuses only apply with Open Hand weapon."""
    print("\n" + "="*80)
    print("TEST: Martial Combat Bonus Requires Open Hand Weapon")
    print("="*80)

    warrior = Warrior("Lizardfolk_Test", "Lizardfolk", "Male", 10, 10, 10, 10, 10, 10)
    warrior.skills["open_hand"] = 9

    # With Open Hand
    warrior.primary_weapon = "Open Hand"
    acc_open = _get_martial_combat_accuracy_bonus(warrior)
    parry_open = _get_martial_combat_parry_bonus(warrior)

    # With other weapon
    warrior.primary_weapon = "Longsword"
    acc_other = _get_martial_combat_accuracy_bonus(warrior)
    parry_other = _get_martial_combat_parry_bonus(warrior)

    print(f"\nWith Open Hand:")
    print(f"  Accuracy: +{acc_open}")
    print(f"  Parry: +{parry_open}")

    print(f"\nWith Longsword:")
    print(f"  Accuracy: +{acc_other}")
    print(f"  Parry: +{parry_other}")

    assert acc_open > 0, "Should have accuracy bonus with Open Hand"
    assert parry_open > 0, "Should have parry bonus with Open Hand"
    assert acc_other == 0, "Should not have accuracy bonus with other weapons"
    assert parry_other == 0, "Should not have parry bonus with other weapons"

    print("\n[PASS] Bonuses correctly require Open Hand weapon")
    return True


def test_non_martial_races_no_bonus():
    """Test that races without martial_combat_bonus get no bonuses."""
    print("\n" + "="*80)
    print("TEST: Non-Martial Races Get No Bonuses")
    print("="*80)

    non_martial_races = ["Human", "Elf", "Gnome", "Goblin"]

    for race in non_martial_races:
        warrior = Warrior(f"{race}_Test", race, "Male", 10, 10, 10, 10, 10, 10)
        warrior.skills["open_hand"] = 9
        warrior.primary_weapon = "Open Hand"

        acc = _get_martial_combat_accuracy_bonus(warrior)
        parry = _get_martial_combat_parry_bonus(warrior)

        assert acc == 0, f"{race} shouldn't have accuracy bonus"
        assert parry == 0, f"{race} shouldn't have parry bonus"
        print(f"  {race}: No bonuses [CORRECT]")

    print("\n[PASS] Non-martial races correctly receive no bonuses")
    return True


if __name__ == "__main__":
    try:
        test_martial_combat_bonus_availability()
        test_martial_combat_accuracy_bonus()
        test_martial_combat_parry_bonus()
        test_bonus_requires_open_hand()
        test_non_martial_races_no_bonus()

        print("\n" + "="*80)
        print("ALL MARTIAL COMBAT BONUS TESTS PASSED [PASS]")
        print("="*80)
        print("\nValidated:")
        print("  [PASS] Lizardfolk and Halflings have martial_combat_bonus")
        print("  [PASS] Accuracy bonus scales +2 to +6 with Open Hand skill")
        print("  [PASS] Parry/dodge bonus scales +4 to +8 with Open Hand skill")
        print("  [PASS] Bonuses only apply when using Open Hand weapon")
        print("  [PASS] Other races do not receive these bonuses")

    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
