# Plan: Heavy Barbed Whip Redesign

## Context
The Heavy Barbed Whip (skill_key: `heavy_whip`) is currently the weakest weapon for its weight class. Its only coded special ability is a flat 50% entangle/trip on every successful hit. Despite its notes describing "barbs or hooks" dealing "blunt and slashing damage," it has no access to the bleed system, no disarm capability, and no meaningful second threat mode. Managers have no incentive to choose it because low damage (10–13) + a coin-flip trip is outclassed by weapons that do similar damage with actual bleed or disarm utility.

The goal is to give the whip a clear **two-mode threat** identity:
- **Entangle mode (50% base + skill scaling)**: Trip the opponent to the ground
- **Wrap Arm mode (~40%)**: On hits that don't entangle, the lash wraps the arm — reducing the defender's next attack roll by ~10

Combined with bleed access and disarm capability, this creates a control + attrition weapon that mounts pressure through multiple channels.

---

## Proposed Changes

### 1. Entangle: Flat 50% Base + Skill Scaling
Keep the 50% base entangle chance but add skill scaling: +3% per `heavy_whip` skill level, capped at 75%.

```python
elif weapon.skill_key == "heavy_whip":
    whip_skill = attacker.skills.get("heavy_whip", 0)   # need attacker passed in
    entangle_chance = min(75, 50 + whip_skill * 3)
    if random.randint(1, 100) <= entangle_chance:
        ...  # existing trip logic
```

Scaling: skill 0 = 50%, skill 3 = 59%, skill 5 = 65%, skill 8 = 74%, skill 9+ = 75% (cap)

**Note:** `_check_entangle` currently receives the defender (`warrior`) and their state, not the attacker. The attacker object will need to be passed as an additional parameter so we can read their `heavy_whip` skill level.

### 2. New "Wrap Arm" Debuff — On Non-Entangle Hits (`combat.py`)
On hits where the entangle roll fails, the lash still catches the arm.
When the heavy whip hits but does NOT entangle, apply a secondary effect: the lash wraps around the defender's weapon arm, penalizing their next attack roll.

**New field on `_CState` dataclass** (~line 741):
```python
arm_wrapped : int = 0   # rounds remaining on whip arm-wrap debuff
```

**In `_check_entangle` (lines 2086–2093)** — after the entangle check fails for `heavy_whip`, return a second flag:
```python
elif weapon.skill_key == "heavy_whip":
    whip_skill = attacker.skills.get("heavy_whip", 0)
    entangle_chance = min(75, 50 + whip_skill * 3)
    if random.randint(1, 100) <= entangle_chance:
        msg = f"The barbed whip wraps around {warrior.name.upper()}'s legs, dragging them to the ground!"
        return True, False, msg   # entangled=True, arm_wrap=False
    elif random.randint(1, 100) <= 40:   # separate roll on non-entangle
        msg = f"The barbed whip rakes across {warrior.name.upper()}'s weapon arm!"
        return False, True, msg   # entangled=False, arm_wrap=True
    return False, False, None
```

**In the hit resolution block** (~line 4241), after the entangle check:
```python
entangled, arm_wrapped, whip_msg = _check_entangle(dfr, ds_, weapon, was_thrown, ax)
if entangled and whip_msg:
    self._emit(whip_msg)
    ds_.is_on_ground = True
    as_.knockdowns_dealt += 1
    fall_dmg = random.randint(1, 3)
    ds_.current_hp -= fall_dmg
elif arm_wrapped and whip_msg:
    self._emit(whip_msg)
    ds_.arm_wrapped = 1   # penalty applies for 1 round
```

**In `_attack_roll()`** — consume the debuff when calculating the defender's attack (find where attack bonuses/penalties are tallied):
```python
# Arm-wrap debuff from heavy whip
if state.arm_wrapped > 0:
    roll -= 10
    state.arm_wrapped -= 1
```

The `_check_entangle` function signature changes from `(warrior, state, weapon, was_thrown)` to `(defender, def_state, weapon, was_thrown, attacker)` and returns `Tuple[bool, bool, Optional[str]]`. Update the caller to pass the attacker object and handle the new 3-tuple.

### 3. Add to `SLASH_WEAPONS` (`combat.py`, line 125)
Add `"heavy_whip"` to the `SLASH_WEAPONS` set. The barbs lacerate flesh, enabling the existing Slash skill bleed mechanic.

- Effect: At Slash level 5, every hit has a 25% chance to stack a bleed wound
- Rewards cross-training `heavy_whip` + `slash`
- No new mechanics — just one string added to an existing set

### 4. Add `can_disarm = True` (`weapons.py`, ~line 1074)
A barbed whip wrapping around a weapon and yanking it free is thematically natural. This activates the existing disarm-on-parry logic already wired for Net, Swordbreaker, Scythe, and Ball & Chain.

### 5. Minor Damage Bump (`weapons.py`)
Raise `damage_top` from 13 to 14 (1-point ceiling lift). The weapon stays in the low-damage tier, but bleed + wrap arm + entangle make the total output competitive over longer fights.

### 6. Expand Preferred Styles (`weapons.py`)
Add `"Feint"` to `preferred_styles` alongside `"Slash"` and `"Engage & Withdraw"`. Gives managers a deceptive-approach option without incurring the style-compatibility penalty.

---

## Files to Modify

| File | Change |
|---|---|
| `weapons.py` ~line 1074 | `can_disarm=True`, `damage_top=14`, add `"Feint"` to `preferred_styles` |
| `combat.py` ~line 125 | Add `"heavy_whip"` to `SLASH_WEAPONS` set |
| `combat.py` ~line 741 | Add `arm_wrapped: int = 0` to `_CState` dataclass |
| `combat.py` lines 2066–2093 | Update `_check_entangle` — add attacker param, skill-scaled entangle, wrap-arm branch |
| `combat.py` ~line 4241 | Update caller to handle new 3-tuple return from `_check_entangle` |
| `combat.py` `_attack_roll()` | Consume `arm_wrapped` debuff: `-10` to roll, decrement counter |

---

## What This Does NOT Do
- No new skills introduced
- No changes to APM or weapon weight
- Does not touch the bleed system itself — just adds whip to the existing set

---

## Verification
1. Run 20–30 fights with a high-`heavy_whip` + `slash` warrior via `tools/game_balance_simulator.py`
2. Check fight logs for: bleed procs on whip hits, entangle trips (more frequent at higher skill), arm-wrap narrative lines
3. Verify arm-wrap actually reduces attack roll (observable as opponent misses on the following action)
4. Verify disarm fires (compare to a Swordbreaker for baseline reference)
5. Reference: `Tests-Fixes/test_scripts/test_francisca_in_combat.py` as a test pattern
