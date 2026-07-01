# Fractional APM & Parry System Implementation

## Overview
Implemented a fractional action system where weapon skills provide real, tangible benefits at every level through probabilistic bonus actions and defensive bonuses.

## Changes Made

### 1. **Modified `_calc_apm()` Function**
- **Return Type**: Changed from `int` to `Tuple[int, float]`
- **Returns**: `(base_apm, fraction)` where:
  - `base_apm` is the guaranteed number of actions per minute
  - `fraction` is 0.0-0.99, representing the percentage chance (as decimal) for a bonus action

**Example**: APM of 4.35 returns `(4, 0.35)` → warrior gets 4 actions guaranteed, plus 35% chance at a 5th action that minute.

### 2. **Heavy Weapon APM Bonus**
Added skill-based APM bonus for weapons weighing 4.0+ (heavy weapons):

```
Skill 1-2: +0.5 APM per level
Skill 3-4: +1.0 APM per level
Skill 5-6: +1.5 APM per level
Skill 7-8: +2.0 APM per level
Skill 9:   +3.0 APM
```

This bonus is applied BEFORE the fractional calculation, so:
- Skill 1 War Hammer with Bash style + Activity 6: Base 4.5 + 0.5 = 5.0 → **(5, 0.0)** = guaranteed 5 APM
- Skill 5 War Hammer with Bash style + Activity 6: Base 4.5 + 1.5 = 6.0 → **(6, 0.0)** = guaranteed 6 APM
- Skill 9 War Hammer with Bash style + Activity 6: Base 4.5 + 3.0 = 7.5 → **(7, 0.5)** = 7 APM guaranteed, 50% chance at 8th

### 3. **New `_resolve_fractional_apm()` Function**
```python
def _resolve_fractional_apm(base_apm: int, fraction: float) -> int:
    """
    Rolls to determine if warrior gets a bonus action that minute.
    fraction is converted to percentage (0-99%).
    Returns the actual APM for this minute.
    """
```

- Converts fraction to percentage chance
- Random roll determines if bonus action is granted
- Returns final APM for that minute

### 4. **Updated Fight Loop**
In the main combat loop (around line 1850):

```python
# OLD:
apm_a = _calc_apm(...)
apm_b = _calc_apm(...)

# NEW:
apm_a_base, apm_a_frac = _calc_apm(...)
apm_b_base, apm_b_frac = _calc_apm(...)
apm_a = _resolve_fractional_apm(apm_a_base, apm_a_frac)
apm_b = _resolve_fractional_apm(apm_b_base, apm_b_frac)
```

Each minute, a fresh roll is made for both warriors, creating variability while preserving expected values over time.

### 5. **Enhanced Parry Defense with Fractional Bonuses**
Updated `_defense_roll()` to apply fractional bonuses to parry:

- **Parry Skill Bonus**: `skill_level * 4` with fractional roll
- **Weapon Skill Bonus (Parry)**: `skill_level * 3` with fractional roll

Example: Parry skill 5 normally gives +20. Now it gives +20 guaranteed, with a chance at +1 more.

This applies the same fractional philosophy: every skill point matters, even if the benefit is probabilistic.

## Balance Implications

### Why This Works
1. **Skills matter at EVERY level** — No "invisible" levels where progression isn't felt
2. **Heavy weapons stay balanced** — APM boost scales naturally, doesn't inflate damage
3. **Consistent expected value** — Over many minutes, averages are predictable
4. **Exciting moments** — RNG creates engagement without breaking gameplay

### Example: War Hammer Progression
| Skill | APM Bonus | Bash+Act6 | Effective | 50 Minute Average |
|-------|-----------|-----------|-----------|-------------------|
| 0 | 0 | 4.5 | 4-5 | ~4.5 |
| 1 | +0.5 | 5.0 | 5 | ~5.0 |
| 3 | +1.0 | 5.5 | 5-6 | ~5.5 |
| 5 | +1.5 | 6.0 | 6 | ~6.0 |
| 7 | +2.0 | 6.5 | 6-7 | ~6.5 |
| 9 | +3.0 | 7.5 | 7-8 | ~7.5 |

A master heavy weapon user (level 9) gets ~67% more actions per minute than unskilled.

## Technical Notes

- Changes are localized to `combat.py`
- No breaking changes to external APIs
- Maintains backward compatibility with debug logger
- Returns tuples cleanly separate base and fraction for future modifications
- Uses standard `random.randint(1, 100)` for RNG

## Testing Recommendations

1. **Unit test**: Verify `_resolve_fractional_apm()` gives correct distribution
2. **Integration test**: Run 1000-minute simulated fights with various skill levels, verify expected averages
3. **Balance test**: Compare win rates for heavy weapon users before/after implementation
4. **Edge cases**: Test with very low/high stats to ensure clipping works correctly
