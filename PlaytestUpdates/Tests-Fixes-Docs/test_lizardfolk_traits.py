#!/usr/bin/env python3
"""
Test Lizardfolk racial traits:
1. Natural Weapon Bonus: +2 to +5 damage with Open Hand
2. Martial Combat Bonus: Accuracy and parry improvements
"""

import sys
from warrior import Warrior
from strategy import Strategy
from combat import _calc_damage_hybrid, _get_lizardfolk_natural_weapon_bonus

def test_natural_weapon_bonus():
    """Test Lizardfolk natural weapon bonus scaling with Open Hand skill."""
    print("\n" + "="*80)
    print("TEST: Lizardfolk Natural Weapon Bonus")
    print("="*80)

    # Create Lizardfolk warrior with low Open Hand skill
    liz_low_skill = Warrior(
        "Liz_Low", "Lizardfolk", "Male",
        15, 10, 10, 10, 10, 10
    )
    liz_low_skill.skills["open_hand"] = 0
    liz_low_skill.primary_weapon = "Open Hand"
    liz_low_skill.secondary_weapon = "Open Hand"

    # Lizardfolk with high Open Hand skill
    liz_high_skill = Warrior(
        "Liz_High", "Lizardfolk", "Male",
        15, 10, 10, 10, 10, 10
    )
    liz_high_skill.skills["open_hand"] = 9
    liz_high_skill.primary_weapon = "Open Hand"
    liz_high_skill.secondary_weapon = "Open Hand"

    # Human with Open Hand (no bonus)
    human_warrior = Warrior(
        "Human_Open", "Human", "Male",
        15, 10, 10, 10, 10, 10
    )
    human_warrior.skills["open_hand"] = 9
    human_warrior.primary_weapon = "Open Hand"
    human_warrior.secondary_weapon = "Open Hand"

    # Get bonuses
    low_bonus = _get_lizardfolk_natural_weapon_bonus(liz_low_skill)
    high_bonus = _get_lizardfolk_natural_weapon_bonus(liz_high_skill)
    human_bonus = _get_lizardfolk_natural_weapon_bonus(human_warrior)

    print(f"\nLizardfolk (Open Hand skill 0): +{low_bonus} damage")
    print(f"Lizardfolk (Open Hand skill 9): +{high_bonus} damage")
    print(f"Human (Open Hand skill 9): +{human_bonus} damage")

    # Validate
    assert low_bonus == 2, f"Low skill should be +2, got +{low_bonus}"
    assert high_bonus == 5, f"High skill should be +5, got +{high_bonus}"
    assert human_bonus == 0, f"Human shouldn't get bonus, got +{human_bonus}"
    assert low_bonus < high_bonus, "Bonus should scale with skill"

    print("\n[PASS] Natural weapon bonus scaling works correctly")
    return True


def test_damage_calculation_with_bonus():
    """Test that natural weapon bonus is applied in damage calculation."""
    print("\n" + "="*80)
    print("TEST: Natural Weapon Bonus in Damage Calculation")
    print("="*80)

    # Lizardfolk attacker
    attacker = Warrior(
        "Liz_Attacker", "Lizardfolk", "Male",
        14, 10, 10, 10, 10, 10
    )
    attacker.skills["open_hand"] = 9
    attacker.primary_weapon = "Open Hand"
    attacker.secondary_weapon = "Open Hand"

    # Human defender
    defender = Warrior(
        "Human_Defender", "Human", "Male",
        10, 12, 10, 10, 10, 10
    )

    # Strategy with Open Hand
    strategy = Strategy(
        style="Stand & Strike",
        defense_point="Chest"
    )

    # Calculate damage with high margin (close to maximum)
    dmg_high_margin, _ = _calc_damage_hybrid(attacker, strategy, "Open Hand", defender, margin=50)

    print(f"\nLizardfolk with Open Hand (skill 9):")
    print(f"  Damage with margin 50: {dmg_high_margin}")
    print(f"  Expected natural bonus: +5")

    # Compare with human using same setup
    human_attacker = Warrior(
        "Human_Attacker", "Human", "Male",
        14, 10, 10, 10, 10, 10
    )
    human_attacker.skills["open_hand"] = 9
    human_attacker.primary_weapon = "Open Hand"
    human_attacker.secondary_weapon = "Open Hand"

    dmg_human, _ = _calc_damage_hybrid(human_attacker, strategy, "Open Hand", defender, margin=50)

    print(f"\nHuman with Open Hand (skill 9):")
    print(f"  Damage with margin 50: {dmg_human}")

    # Lizardfolk should do more damage due to +5 bonus
    diff = dmg_high_margin - dmg_human
    print(f"\nDamage difference (Lizardfolk - Human): +{diff}")
    print(f"Natural weapon bonus should be around 5 (some reduction from armor)")

    assert dmg_high_margin > dmg_human, "Lizardfolk should do more damage"
    assert diff > 0, "Damage difference should be positive"

    print("\n[PASS] Natural weapon bonus correctly applied in damage calculation")
    return True


def test_lizardfolk_only_bonus():
    """Test that only Lizardfolk get the natural weapon bonus."""
    print("\n" + "="*80)
    print("TEST: Lizardfolk-Only Bonus (Not for Other Races)")
    print("="*80)

    races_to_test = [
        ("Lizardfolk", True),
        ("Human", False),
        ("Halfling", False),
        ("Gnome", False),
        ("Elf", False),
        ("Goblin", False),
    ]

    for race_name, should_get_bonus in races_to_test:
        warrior = Warrior(
            f"{race_name}_Test", race_name, "Male",
            14, 10, 10, 10, 10, 10
        )
        warrior.skills["open_hand"] = 9
        warrior.primary_weapon = "Open Hand"
        warrior.secondary_weapon = "Open Hand"

        bonus = _get_lizardfolk_natural_weapon_bonus(warrior)

        if should_get_bonus:
            assert bonus > 0, f"{race_name} should get natural weapon bonus"
            print(f"  {race_name}: +{bonus} [CORRECT]")
        else:
            assert bonus == 0, f"{race_name} shouldn't get natural weapon bonus"
            print(f"  {race_name}: +{bonus} [CORRECT]")

    print("\n[PASS] Only Lizardfolk get natural weapon bonus")
    return True


def test_bonus_requires_open_hand():
    """Test that bonus only applies when using Open Hand."""
    print("\n" + "="*80)
    print("TEST: Bonus Requires Open Hand Weapon")
    print("="*80)

    warrior = Warrior(
        "Liz_Weapon", "Lizardfolk", "Male",
        14, 10, 10, 10, 10, 10
    )
    warrior.skills["open_hand"] = 9

    # With Open Hand
    warrior.primary_weapon = "Open Hand"
    bonus_open = _get_lizardfolk_natural_weapon_bonus(warrior)

    # With other weapon
    warrior.primary_weapon = "Longsword"
    bonus_other = _get_lizardfolk_natural_weapon_bonus(warrior)

    print(f"\nLizardfolk with Open Hand: +{bonus_open}")
    print(f"Lizardfolk with Longsword: +{bonus_other}")

    assert bonus_open > 0, "Should get bonus with Open Hand"
    assert bonus_other == 0, "Should not get bonus with other weapons"

    print("\n[PASS] Bonus correctly requires Open Hand weapon")
    return True


if __name__ == "__main__":
    try:
        test_natural_weapon_bonus()
        test_damage_calculation_with_bonus()
        test_lizardfolk_only_bonus()
        test_bonus_requires_open_hand()

        print("\n" + "="*80)
        print("ALL LIZARDFOLK TRAIT TESTS PASSED [PASS]")
        print("="*80)
        print("\nValidated:")
        print("  [PASS] Natural weapon bonus scales with Open Hand skill (0-9)")
        print("  [PASS] Bonus correctly applied in damage calculations")
        print("  [PASS] Only Lizardfolk receive the natural weapon bonus")
        print("  [PASS] Bonus only applies when using Open Hand weapon")

    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
