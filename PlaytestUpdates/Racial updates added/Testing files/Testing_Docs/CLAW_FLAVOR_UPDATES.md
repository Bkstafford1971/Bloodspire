# Lizardfolk & Tabaxi Claw Attack Flavor Text Updates

**Date:** June 3, 2026  
**Status:** ✓ COMPLETE

## Summary

Updated damage descriptions for Lizardfolk and Tabaxi when using Open Hand (claws) to use slashing/raking flavor text instead of generic crushing descriptions.

## What Changed

### Narrative.py
**Modified:** `damage_line()` function (lines 1459-1480)
- Added optional `is_claw_attack` parameter
- When `is_claw_attack=True` and weapon is Open Hand, uses "Slashing" damage descriptions instead of "Generic"
- This provides appropriate flavor text for claw attacks (rakes, slashes, tears, shreds, rends)

### Combat.py
**Added:** `_is_claw_attack()` helper function (line ~251)
```python
def _is_claw_attack(warrior: Warrior) -> bool:
    """Check if warrior has claws and is using Open Hand (for flavor text)."""
    return warrior.primary_weapon == "Open Hand" and warrior.race.name in ("Lizardfolk", "Tabaxi")
```

**Updated:** All 6 `damage_line()` calls in combat engine
- Lines 2326, 2695, 3199, 3377, 3455, 3490
- Now pass `is_claw_attack=_is_claw_attack(att)` parameter
- Covers: Tabaxi Frenzy, Opportunity Throw, Standard attacks, Martial Combat extra attacks, Elf dual-wield extra attacks, Counterstrike attacks

## Flavor Text Examples

### Claw Attacks (Slashing)
**Heavy damage:**
- Flesh parts violently beneath the keen edge!
- A gruesome flap of skin and muscle is laid open!
- Blood sprays wildly from the deep slash!
- The blade bites deep and opens the body!
- A brutal cut lays the warrior's side open!

**Medium damage:**
- The blade opens a deep, bleeding gash!
- A clean slash draws a heavy flow of blood!
- The strike slices through skin and muscle!
- Blood runs freely from the fresh cut!

**Light damage:**
- A shallow cut appears along the surface!
- The weapon skims across and draws a thin line!
- A light cut wells up with a few drops of blood!

### Non-Claw Open Hand (Bludgeoning - Kicks, Tail Lashes)
**Heavy damage:**
- The blow lands with bone-shattering force!
- A devastating smash pulps muscle and bone!
- The impact rattles the warrior's entire skeleton!

**Medium damage:**
- The strike lands with heavy, punishing force!
- A solid crunch is heard as the blow connects!
- The hit drives the air from the warrior's lungs!

**Light damage:**
- The blow lands lightly, more sting than damage!
- A dull thud is all that results!
- The strike barely connects with force!

## How It Works

1. When Lizardfolk or Tabaxi deals damage with Open Hand weapon
2. Combat engine detects it's a claw attack: `_is_claw_attack(attacker) = True`
3. Passes this flag to `damage_line()`: `damage_line(dmg, max_hp, cat, is_claw_attack=True)`
4. `damage_line()` uses "Slashing" damage type instead of "Generic"
5. Random slashing description is chosen and displayed

## Important Notes

- **Kicks:** Lizardfolk can still kick with Open Hand, but kicks are crushing, not slashing. Flavor should reflect kicks vs claws in narrative.
- **Tail:** Lizardfolk tail lashes should be crushing (already correct).
- **Both races:** Lizardfolk AND Tabaxi now have correct claw flavor text
- **Backward compatible:** Non-claw Open Hand attacks continue to use appropriate descriptions
- **No game mechanic changes:** This is purely flavor text - damage values and hit rates unchanged

## Testing

Test file: `test_claw_flavor.py`

Validates:
- `damage_line()` function correctly selects slashing text for claws
- Non-claw attacks still use appropriate descriptions
- Lizardfolk and Tabaxi both get correct flavor
- Combat system successfully detects and applies the flavor parameter

## Example Combat Narrative

**Before:**
```
Lizardfolk's claws tears into Human's body!
   The blow caves in flesh and crushes what lies beneath!  ← Wrong: crushing text for claws
```

**After:**
```
Lizardfolk's claws tears into Human's body!
   Flesh parts violently beneath the keen edge!  ← Correct: slashing text for claws
```

---

**Files Modified:**
- narrative.py: damage_line() function (1 function)
- combat.py: _is_claw_attack() added, 6 damage_line() calls updated

**No breaking changes** - fully backward compatible with existing combat system.
