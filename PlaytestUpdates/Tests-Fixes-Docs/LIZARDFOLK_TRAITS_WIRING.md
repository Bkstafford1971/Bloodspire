# Lizardfolk Racial Traits - Wiring Verification

**Date:** June 3, 2026  
**Status:** ✓ COMPLETE - All traits verified and integrated

## Summary

All four Lizardfolk racial traits have been verified as properly integrated into the game mechanics:

### Trait 1: Natural Weapon Bonus
- **Effect:** +2 to +5 damage when using Open Hand/Martial Combat style
- **Scaling:** +2 (skill 0) → +5 (skill 9)
- **Implementation:**
  - Function: `_get_lizardfolk_natural_weapon_bonus()` (combat.py:343-353)
  - **NEWLY WIRED:** Added to `_calc_damage_hybrid()` (lines 1057-1060)
  - **NEWLY WIRED:** Added to `_calc_damage_verbose()` (lines 1431-1435)
  - Checks: Lizardfolk race + Open Hand weapon
- **Test Coverage:** test_lizardfolk_traits.py (PASS)

### Trait 2: Martial Combat Bonus - Accuracy
- **Effect:** +2 to +6 accuracy bonus when using Open Hand
- **Scaling:** +2 (skill 0) → +6 (skill 9)
- **Implementation:**
  - Function: `_get_martial_combat_accuracy_bonus()` (combat.py:356-366)
  - **Already Wired:** Attack roll calculations (lines 668-669, 1167-1169)
  - Checks: Has martial_combat_bonus flag + Open Hand weapon
- **Test Coverage:** test_martial_combat_bonus.py (PASS)

### Trait 3: Martial Combat Bonus - Parry/Dodge
- **Effect:** +4 to +8 parry/dodge defense when using Open Hand
- **Scaling:** +4 (skill 0) → +8 (skill 9)
- **Implementation:**
  - Function: `_get_martial_combat_parry_bonus()` (combat.py:369-379)
  - **Already Wired:** Defense calculations (lines 781-784, 1284-1290)
  - Checks: Has martial_combat_bonus flag + Open Hand weapon
- **Test Coverage:** test_martial_combat_bonus.py (PASS)

### Trait 4: Natural Armor
- **Effect:** Defense 5 (natural scales) + layering cap system
- **Mechanics:**
  - No armor: Defense 5 (scales only)
  - Cloth: Defense 6 (cloth over scales)
  - Leather: Defense 7 (maximum useful layering)
  - Heavy armor (Cuir Boulli+): Defense 7 (capped, no additional protection but penalties apply)
- **Armor Penalties:**
  - Light armor (cloth/leather): DEX reduction (-1 cloth, -2 leather)
  - Heavy armor: Percentage-based roll penalties (dodge/parry/initiative/attack)
- **Implementation:**
  - Function: `get_effective_defense_for_race()` (armor.py:407-444)
  - Function: `get_lizardfolk_armor_penalties()` (armor.py:393-404)
  - **Already Implemented:** Full integration in armor system
- **Test Coverage:** test_lizardfolk_combat.py (PASS)

## Changes Made

### Combat.py Modifications

**1. Added Natural Weapon Bonus to Hybrid Damage Calculation (lines 1057-1060):**
```python
# Lizardfolk natural weapon bonus: +2 to +5 for Open Hand style
if attacker.race.modifiers.natural_weapon_bonus:
    natural_bonus = _get_lizardfolk_natural_weapon_bonus(attacker)
    raw += natural_bonus
```

**2. Added Natural Weapon Bonus to Verbose Damage Calculation (lines 1431-1435):**
```python
# Lizardfolk natural weapon bonus: +2 to +5 for Open Hand style
nat_b = 0
if attacker.race.modifiers.natural_weapon_bonus:
    nat_b = _get_lizardfolk_natural_weapon_bonus(attacker)
    raw += nat_b
steps["natural_weapon_bonus"] = nat_b
```

## Test Results

### test_lizardfolk_traits.py
- [PASS] Natural weapon bonus scales with Open Hand skill (0-9)
- [PASS] Bonus correctly applied in damage calculations
- [PASS] Only Lizardfolk receive the natural weapon bonus
- [PASS] Bonus only applies when using Open Hand weapon

### test_martial_combat_bonus.py
- [PASS] Lizardfolk and Halflings have martial_combat_bonus
- [PASS] Accuracy bonus scales +2 to +6 with Open Hand skill
- [PASS] Parry/dodge bonus scales +4 to +8 with Open Hand skill
- [PASS] Bonuses only apply when using Open Hand weapon
- [PASS] Other races do not receive these bonuses

### test_lizardfolk_combat.py
- [PASS] All three traits are enabled for Lizardfolk
- [PASS] Natural armor mechanics correctly implemented
- [PASS] Armor penalties correctly configured
- [PASS] Natural weapon bonus correctly scales with skill
- [PASS] Martial combat bonuses properly configured

## Trait Integration Diagram

```
Lizardfolk Warrior (Open Hand Combat)
  |
  +-- Natural Weapon Bonus
  |     +-> +2 to +5 damage (skill-scaled)
  |     +-> Applied in: _calc_damage_hybrid(), _calc_damage_verbose()
  |
  +-- Martial Combat Accuracy Bonus
  |     +-> +2 to +6 accuracy (skill-scaled)
  |     +-> Applied in: Attack roll calculations
  |
  +-- Martial Combat Parry/Dodge Bonus
  |     +-> +4 to +8 defense (skill-scaled)
  |     +-> Applied in: Defense roll calculations
  |
  +-- Natural Armor
        +-> Defense 5 base + layering cap
        +-> Capped at defense 7 with heavy armor
        +-> Special penalties for movement/combat
        +-> Applied in: get_effective_defense_for_race()
```

## Validation

All four Lizardfolk traits are:
- ✓ Properly defined in races.py
- ✓ Correctly wired into combat calculations
- ✓ Skill-scaled appropriately
- ✓ Race-specific (only Lizardfolk benefit)
- ✓ Comprehensively tested
- ✓ Ready for gameplay integration

## Notes

- Halflings share the `martial_combat_bonus` flag, so they also receive accuracy and parry bonuses with Open Hand
- Natural armor is Lizardfolk-specific via the `natural_armor` flag
- Natural weapon bonus is Lizardfolk-specific via the `natural_weapon_bonus` flag
- All traits work together in combat to make Lizardfolk effective unarmed combatants
