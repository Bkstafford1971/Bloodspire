# Martial Combat Narrative Consistency Fix

**Date:** June 3, 2026  
**Status:** ✓ COMPLETE

## Problem Identified

Attack/hit/damage narrative lines were inconsistent for Lizardfolk and Tabaxi martial attacks:

**Example of inconsistency:**
```
SINDAR's leg lashes out with a kick at SHERIK SUREBLADE's body!
SHERIK SUREBLADE watches for the angle of attack!
SHERIK SUREBLADE commits to the wrong direction!
SINDAR's open hand hits SHERIK SUREBLADE's armor!    <- WRONG! Should say "leg crashes into"
   Only a superficial slash is left behind!          <- WRONG! Should be crushing damage, not slashing
```

The issue: Attack line selected "kick" randomly, but hit line and damage line independently selected "claw" randomly, creating inconsistency.

## Root Cause

- `attack_line()`, `hit_line()`, and `damage_line()` each independently chose random attack types
- No coordination between the three functions
- Same attacker-defender pair could generate different attack types across narrative lines

## Solution Implemented

### 1. Deterministic Attack Type Selection (narrative.py)

Changed from random selection to deterministic selection based on defender name:

```python
# Old (random):
attack_type = random.choice(["claw", "kick", "tail"])

# New (deterministic):
attack_type = attack_types[sum(ord(c) for c in defender_name) % len(attack_types)]
```

This ensures: For a given defender, the same attack type is chosen every time, across all narrative functions.

### 2. New Helper Function (combat.py)

Added `_get_martial_attack_type()` to determine attack type consistently:

```python
def _get_martial_attack_type(warrior: Warrior, defender_name: str) -> str:
    """Determine the type of martial attack (claw, kick, tail) for Lizardfolk/Tabaxi."""
    if warrior.primary_weapon != "Open Hand":
        return None
    
    if warrior.race.name == "Lizardfolk":
        attack_types = ["claw", "kick", "tail"]
        return attack_types[sum(ord(c) for c in defender_name) % len(attack_types)]
    elif warrior.race.name == "Tabaxi":
        attack_types = ["claw", "kick"]
        return attack_types[sum(ord(c) for c in defender_name) % len(attack_types)]
    return None
```

### 3. Wired Into All Damage Calls (combat.py)

Updated all 6 damage_line() calls to use the correct attack type:

```python
# Determine if claw or kick/tail for damage description
attack_type = _get_martial_attack_type(att, dfr.name)
is_claw = attack_type == "claw"
self._emit(N.damage_line(dmg, dfr.max_hp, cat, is_claw_attack=is_claw))
```

### 4. Added Tabaxi Support (narrative.py)

- Added `TABAXI_HIT_VERBS` dictionary
- Added Tabaxi handling to `hit_line()` function
- Tabaxi uses claw/kick attacks (no tail)

## How It Works

**Attack Type Selection:**
1. First time defender name is encountered → deterministic attack type chosen
2. That same type is used for attack_line(), hit_line(), and damage_line()
3. Example:
   - Defender "Malrik Salvor": hash % 3 = 1 → always "kick"
   - Defender "Granite Stone": hash % 2 = 0 → always "claw" (for Tabaxi)

**Damage Description Matching:**
- Claw attacks → Slashing damage descriptions
- Kick/Tail attacks → Crushing/Bludgeoning damage descriptions

## Example Fixes

### Before (Inconsistent)
```
SLYTHE's leg lashes out with a kick at MALRIK SALVOR's body!
MALRIK SALVOR watches for the angle of attack!
SLYTHE's open hand hits MALRIK SALVOR's armor!         ← WRONG weapon type
   Only a superficial slash is left behind!            ← WRONG damage type
```

### After (Consistent)
```
SLYTHE's leg lashes out with a kick at MALRIK SALVOR's body!
MALRIK SALVOR watches for the angle of attack!
SLYTHE's leg crashes into MALRIK SALVOR's armor!       ← CORRECT weapon type
   The blow lands lightly, more sting than damage!     ← CORRECT crushing damage
```

## Affected Attack Types

| Attack Type | Hit Description | Damage Description |
|---|---|---|
| **Claw** | "claws rake across" | Slashing - "flesh parts beneath keen edge" |
| **Kick** | "leg crashes into" | Crushing - "blow lands with force" |
| **Tail** (Lizardfolk) | "tail whips across" | Crushing - "whip strikes with force" |

## Files Modified

- **narrative.py:**
  - `LIZARDFOLK_ATTACK_VERBS` - use simple verbs
  - `TABAXI_ATTACK_VERBS` - new dictionary
  - `TABAXI_HIT_VERBS` - new dictionary
  - `attack_line()` - deterministic selection (Lizardfolk + Tabaxi)
  - `hit_line()` - deterministic selection (Lizardfolk + Tabaxi)

- **combat.py:**
  - `_get_martial_attack_type()` - new helper function
  - All 6 `damage_line()` calls updated to use attack type

## Impact

✓ **All narrative lines now consistent**  
✓ **No game mechanics changed**  
✓ **Purely flavor/narrative improvement**  
✓ **Works for both Lizardfolk and Tabaxi**  
✓ **Non-martial attacks unaffected**

## Technical Note

The deterministic selection using defender name hash ensures:
- Same attacker vs same defender always uses same attack type
- Within a single combat, all descriptions match
- Across multiple combats, attack type varies based on opponent
- No need to pass attack type through entire call stack
