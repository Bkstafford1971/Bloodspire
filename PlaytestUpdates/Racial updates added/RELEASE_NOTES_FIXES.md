# BPClone Combat Narrative Fixes - Release Notes

## Summary
This document tracks all combat narrative fixes applied to improve consistency, logical flow, and accuracy of fight descriptions.

---

## Fix #1: Counter-Attack Parameter Order

**Status:** ✅ COMPLETED & VALIDATED

**Issue:**
When a defender successfully parried an attack and triggered an immediate counter-attack, the original attacker's weapon would incorrectly be shown as landing damage instead of the counter-attacker's weapon. This created a logical inconsistency where a successful parry didn't actually prevent the original attack from landing.

**Example of Problem:**
```
DEFENDER makes an extraordinary effort, and parries the strike!
DEFENDER turns the parry into an immediate counter!
The dagger finds its mark!  [WRONG - this is the original attacker's dagger]
ATTACKER's dagger finds DEFENDER's torso!
   A clean slash draws a heavy flow of blood!
```

**Root Cause:**
The `_counterstrike()` method was being called with attacker/defender states in the wrong order:
- **Incorrect:** `_counterstrike(as_, ds_, ax, dx, minute)` 
  - Treated original attacker as the counter-attacker
- **Correct:** `_counterstrike(ds_, as_, dx, ax, minute)`
  - Treats defender (who parried) as the counter-attacker

**Files Modified:**
- `combat.py` - Lines 3106, 3114, 3121, 3142, 3192, 3195

**Changes Made:**
Swapped parameter order in all 6 `_counterstrike()` calls to reverse attacker/defender roles:
1. Gnome mastery path (line 3106)
2. Standard riposte skill path (line 3114)
3. Counterstrike style path (line 3121)
4. Weak parry gnome mastery path (line 3142)
5. Critical dodge double counterstrike - first counter (line 3192)
6. Critical dodge double counterstrike - second counter (line 3195)

**Expected Narrative After Fix:**
```
DEFENDER makes an extraordinary effort, and parries the strike!
DEFENDER turns the parry into an immediate counter!
The battle axe finds its mark!  [CORRECT - defender's weapon]
DEFENDER's battle axe finds ATTACKER's torso!
   A crushing blow draws spurting blood!
```

**Validation:**
- Manual code review of all 4 counter-attack paths
- Verified parameter swapping correctly reverses attacker/defender roles
- Confirmed strategy parameters are also swapped (dx, ax)

---

## Fix #2: Simultaneous Strategy Trigger Emission

**Status:** ✅ COMPLETED & VALIDATED

**Issue:**
When two warriors' strategy triggers fired from the same damage event (e.g., "You have taken heavy damage" and "Your foe has taken heavy damage" occurring simultaneously), the narrative would show one strategy switch immediately after damage, then other narrative text (crowd flavor, low-HP commentary, etc.), and then show the second strategy switch much later. This violates the design principle that simultaneous triggers should be emitted together.

**Example of Problem:**
```
BANSHEE's dagger finds LYSSARA's flank!
   The edge bites deep and draws crimson!
 * LYSSARA switches to strategy 2  [Trigger: "You have taken heavy damage"]
A dog runs loose in the upper tier!  [Crowd flavor text]
LYSSARA unleashes a ceaseless barrage of strikes...
BANSHEE keeps his feet light and ready!
 * BANSHEE switches to strategy 3  [DELAYED - Trigger: "Your foe has taken heavy damage"]
But the dodge isn't quite enough!
```

**Root Cause:**
Strategy checks at lines 3325-3326 were making two separate function calls to `_check_defender_strategy_only()`. While the function calls were sequential, there was no guarantee both switches would be emitted before other narrative code executed.

**Files Modified:**
- `combat.py` - Lines 3325-3329 (in `_resolve_action()`)

**Changes Made:**
Replaced two separate `_check_defender_strategy_only()` calls with inline strategy evaluation that:
1. Evaluates both warriors' triggers using the same fighter states
2. Collects both strategy changes before emitting ANY narrative
3. Emits both switches consecutively (if they occur)
4. Then continues with other narrative effects (low-HP commentary, etc.)

**Code Pattern:**
```python
# Old: Two separate function calls
self._check_defender_strategy_only(ds_, as_, minute)
self._check_defender_strategy_only(as_, ds_, minute)

# New: Atomic evaluation and emission
fs_defender = ds_.to_fighter_state()
fs_attacker = as_.to_fighter_state()

new_strat_def, new_idx_def = evaluate_triggers(...)
new_strat_att, new_idx_att = evaluate_triggers(...)

# Emit both together
if new_idx_def != ds_.active_strat_idx:
    self._emit(strategy_switch_line(...))
    # update state
    
if new_idx_att != as_.active_strat_idx:
    self._emit(strategy_switch_line(...))
    # update state
```

**Expected Narrative After Fix:**
```
BANSHEE's dagger finds LYSSARA's flank!
   The edge bites deep and draws crimson!
 * LYSSARA switches to strategy 2
 * BANSHEE switches to strategy 3
A dog runs loose in the upper tier!
LYSSARA unleashes a ceaseless barrage of strikes...
```

**Validation:**
- Created test with two warriors specifically designed to trigger simultaneous strategy changes
- Confirmed both strategy switches appear on consecutive lines (97-98) in test output
- Verified no narrative text appears between the two switches
- Test fight: `test_simultaneous_triggers.py`
- Test Result: `[OK] Lines 97 and 98: CONSECUTIVE (no narrative between)`

---

## Fix #3: Counter-Attack Strategy Check Enhancement

**Status:** ✅ COMPLETED & VALIDATED

**Issue:**
When a counter-attack was executed following a parry, only the original attacker's (now defender's) strategy was checked in response to damage taken. The counter-attacker's strategy was not being checked in response to the foe's updated HP, creating an asymmetry in trigger evaluation.

**Root Cause:**
The `_counterstrike()` method at line 3589 only called:
```python
self._check_defender_strategy_only(ds_, as_, minute)
```

This checked the strategy of the warrior taking damage (ds_), but didn't check the counter-attacker's strategy in response to the foe's HP.

**Files Modified:**
- `combat.py` - Line 3589 in `_counterstrike()`

**Changes Made:**
Added a second strategy check after the first:
```python
self._check_defender_strategy_only(ds_, as_, minute)  # defender (original attacker) reacts to their HP drop
self._check_defender_strategy_only(as_, ds_, minute)  # counter-attacker reacts to foe's HP
```

**Impact:**
Ensures that both warriors' strategies are evaluated immediately after counter-attack damage, similar to how regular attacks handle strategy checks. This maintains consistency across all combat actions.

**Validation:**
- Included in simultaneous trigger test
- Verified through counter-attack scenarios in validation tests

---

## Fix #4: Armor-Specific Narrative Descriptions

**Status:** ✅ COMPLETED & VALIDATED

**Issue:**
Attack narratives referenced armor features that didn't match the opponent's actual armor type. For example, a warrior using Calculated Attack against an opponent in Cuir Boulli (soft leather armor with no metal plates) would say "analyzes the gaps in the iron plate" - but Cuir Boulli has no iron plates, only leather.

**Example of Problem:**
```
ATTACKER (using Calculated Attack) vs DEFENDER (wearing Cuir Boulli)
ATTACKER analyzes the gaps in the iron plate to maximize the impending trauma
[WRONG - Cuir Boulli is leather, not metal plate armor]
```

**Root Cause:**
Attack intent narratives were selected from generic pools that didn't account for the opponent's armor type. Styles like "Calculated Attack", "Bash", and "Sure Strike" contain armor-specific references, but the narrative selection logic only considered the fighting style, not what the opponent was wearing.

**Files Modified:**
- `narrative.py` - Added armor-specific narrative pools and selection logic (lines 905-977)
- `combat.py` - Line 2852: Updated call to `style_intent_line()` to pass defender's armor

**Changes Made:**

1. **Created armor category system** (narrative.py):
   - 4 armor categories: `"plate"`, `"chain"`, `"leather"`, `"none"`
   - Mapping function `_get_armor_category()` classifies armors:
     - `"plate"` = Full Plate, Half-Plate, Brigandine
     - `"chain"` = Chain, Scale
     - `"leather"` = Leather, Cuir Boulli
     - `"none"` = No armor or unarmored

2. **Added ARMOR_SPECIFIC_INTENT_POOLS** (narrative.py):
   - Created armor-specific narratives for 3 styles: Bash, Sure Strike, Calculated Attack
   - Each style has 4 variants (one per armor category)
   - Narratives now reference the actual armor features

3. **Enhanced style_intent_line()** (narrative.py):
   - Added optional `foe_armor` parameter
   - Checks armor-specific pool first if available
   - Falls back to generic pool for backward compatibility

4. **Updated combat.py** (line 2852):
   - Now passes defender's armor to `style_intent_line()`

**Example Narratives by Armor Type:**

Calculated Attack style examples:
```
Against Plate:     "analyzes the gaps between the metal plates with surgical precision"
Against Chain:     "analyzes gaps in the metal mesh for the perfect strike"
Against Leather:   "analyzes the seams in the leather to maximize impending trauma"
Against None:      "analyzes the bare, vulnerable target with cold precision"
```

Bash style examples:
```
Against Plate:     "looks to bash through the metal plating with brutal force"
Against Chain:     "winds up to pummel the chain links into submission"
Against Leather:   "looks to cave in the leather and crack ribs"
Against None:      "looks to break bone and shatter resolve"
```

**Expected Narrative After Fix:**
```
ATTACKER (using Calculated Attack) vs DEFENDER (wearing Cuir Boulli)
ATTACKER analyzes the seams in the leather to maximize impending trauma
[CORRECT - narrative now matches leather armor]
```

**Validation:**
- Created comprehensive test file: `test_armor_narrative.py`
- Verified all 8 armor types correctly mapped to categories
- Generated live narratives for different armor types
- All armor-specific variants produce contextually appropriate text
- Backward compatible: styles without armor variants use generic pools
- Test Result: ✅ All mappings and narratives validated

---

## Testing & Validation Summary

| Fix | Test File | Status |
|-----|-----------|--------|
| Counter-Attack Parameter Order | Manual code review + existing fights | ✅ PASS |
| Simultaneous Trigger Emission | `test_simultaneous_triggers.py` | ✅ PASS |
| Counter-Attack Strategy Check | `test_simultaneous_triggers.py` | ✅ PASS |
| Armor-Specific Narratives | `test_armor_narrative.py` | ✅ PASS |
| Explicit Challenge Type Narratives | `test_challenge_types.py` | ✅ PASS |
| Thrown Weapon Attack Results | `test_throw_fix_validation.py` + `test_emit_debug.py` | ✅ PASS |
| Favorite Weapon Flavor Timing | `test_favorite_weapon_timing.py` | ✅ PASS |

---

## Files Changed Summary

### combat.py
- Lines 3106, 3114, 3121, 3142: Counter-attack parameter order fixes
- Lines 3325-3329: Simultaneous trigger emission refactoring
- Line 3590: Added counter-attacker strategy check
- Line 2852: Pass defender armor to style_intent_line()
- Lines 2871-2884: Fix defense intent blocking defense results (Throw Attack Fix)
- Lines 2886-2891: Removed (moved favorite weapon flavor to after successful hits)
- Lines 3280-3291: Added favorite weapon flavor after hit damage (Flavor Timing Fix)

### narrative.py
- Lines 447-463: Completely redesigned challenge flavor pools (4 pools total)
- Lines 465-516: Updated get_challenge_flavor_line() logic for all challenge types
- Lines 905-977: Added ARMOR_SPECIFIC_INTENT_POOLS and _get_armor_category() function
- Lines 951-988: Enhanced style_intent_line() to accept foe_armor parameter

### Test Files Created
- `test_counter_narrative.py` - Demonstrates counter-attack narrative fix
- `test_trigger_timing.py` - Shows simultaneous trigger timing issue and solution
- `test_simultaneous_triggers.py` - Full validation test with actual combat simulation
- `test_armor_narrative.py` - Validates armor-specific narrative selection
- `test_challenge_types.py` - Validates all challenge type narratives are explicit
- `test_throw_miss_narrative.py` - Reproduces throw attack narrative gap issue
- `test_emit_debug.py` - Debug trace tool for tracking emitted narrative lines
- `test_throw_fix_validation.py` - Validates throw attack results now appear correctly
- `test_favorite_weapon_timing.py` - Validates flavor timing and consistency

---

## Known Issues Addressed

✅ Narrative inconsistency where successful parries allowed original attacks to still land
✅ Delayed trigger responses where simultaneous triggers weren't emitted together
✅ Asymmetric strategy evaluation in counter-attacks
✅ Armor description mismatches (e.g., "iron plates" for leather armor)
✅ Ambiguous challenge narratives that didn't clearly identify challenge type
✅ Missing attack result narratives for thrown weapons that miss or are parried
✅ Spoiler and contradiction in favorite weapon flavor narrative

---

## Future Fix Template

For each new fix going forward, use this template:

```markdown
## Fix #N: [Title]

**Status:** [IN PROGRESS / COMPLETED & VALIDATED]

**Issue:**
[Description of the problem]

**Example of Problem:**
[Before code sample]

**Root Cause:**
[Explanation of why it happens]

**Files Modified:**
- [file.py] - Lines [X-Y]

**Changes Made:**
[Detailed description of what was changed]

**Expected Narrative After Fix:**
[After code sample]

**Validation:**
[How it was tested and confirmed to work]
```

---

---

## Fix #5: Explicit Challenge Type Narratives

**Status:** ✅ COMPLETED & VALIDATED

**Issue:**
Challenge narratives didn't clearly indicate what type of challenge was occurring. A normal challenge, blood challenge, monster challenge, and title challenge all needed to be unmistakably distinct so the reader knows immediately what they're witnessing.

**Example of Problem:**
```
Before: ALEXANDER THE GREAT has singled out REJ CHYLDE for combat!
        [Unclear - could be any challenge type]

After:  ALEXANDER THE GREAT has declared a Blood Challenge against REJ CHYLDE!!
        [Clear - definitely a Blood Challenge]
```

**Root Cause:**
Challenge flavor narratives were generic and didn't explicitly name the challenge type in every line. Some lines like "has singled out for combat" didn't contain the word "Challenge" at all, making it impossible to know what type of challenge was happening.

**Files Modified:**
- `narrative.py` - Lines 447-516: Redesigned challenge flavor pools

**Changes Made:**

1. **Redesigned all challenge pools to be explicit:**
   - **Normal Challenge Pool**: Every line contains the word "Challenge"
   - **Blood Challenge Pool**: Every line explicitly includes "Blood Challenge"
   - **Monster Challenge Pool**: Every line explicitly mentions "Monster" or "Monster Challenge"
   - **Champion/Title Challenge Pool** (NEW): Every line explicitly includes "Title" or "Title Challenge"

2. **Updated selection logic:**
   - Added support for "champion" fight_type
   - Enhanced fallback logic to handle champion fights

**Example Narratives by Challenge Type:**

```
Normal:       "ATTACKER issues a Challenge to DEFENDER!!"
Blood:        "ATTACKER has declared a Blood Challenge against DEFENDER!!"
Monster:      "ATTACKER dares to challenge the Monster DEFENDER!!"
Champion:     "ATTACKER issues a Title Challenge to the champion DEFENDER!!"
```

**Expected Narrative After Fix:**
```
Before: ALEXANDER THE GREAT has singled out REJ CHYLDE for combat!
After:  ALEXANDER THE GREAT has declared a Blood Challenge against REJ CHYLDE!!
        [Now unmistakably clear it's a Blood Challenge]
```

**Validation:**
- Test file: `test_challenge_types.py`
- All 4 challenge type pools validated
- Every narrative in every pool includes required keyword(s)
- Live generation test confirms correct pool selection
- Test Result: ✅ All challenge types unmistakably explicit

---

## Fix #6: Thrown Weapon Attack Result Narratives

**Status:** ✅ COMPLETED & VALIDATED

**Issue:**
When thrown weapons (via Opportunity Throw style) were parried or missed, the attack result line was not appearing in the narrative. Players would see the defender preparing to defend, then immediately see the weapon being drawn for the next attack, with no indication of what happened to the throw.

**Example of Problem:**
```
POL POT pitches his javelin at WRITHEN HILT's lead leg!
WRITHEN HILT eyes the incoming strike carefully!
POL POT draws his backup javelin!
WRITHEN HILT swings at POL POT's weapon arm with his battle axe
[MISSING: No indication of whether the javelin missed, was parried, or hit!]
```

**Root Cause:**
The `_defensive_narrative_emitted` flag was set to True when a defense_intent line was emitted (before the attack roll, to show the defender's preparation). Then, when the attack was evaluated (after the roll), the parry_line code checked this flag and **skipped the parry result** if the flag was already set. This created a gap where defending warriors could successfully parry but show no result.

The issue only affected FAILED attacks (misses and parries), not successful hits, because hits had special handling with the `defense_fail_line` function.

**Files Modified:**
- `combat.py` - Lines 2871-2884

**Changes Made:**
Separated the concept of "defense intent" (shown before attack roll) from "defensive narrative result" (shown after attack roll):

1. **Before (WRONG):**
   - Emit defense_intent at line 2881
   - Set _defensive_narrative_emitted = True immediately
   - Later, skip parry_line if _defensive_narrative_emitted is True
   - Result: parry lines are hidden if defense_intent was shown

2. **After (CORRECT):**
   - Emit defense_intent at line 2881
   - Do NOT set _defensive_narrative_emitted = True
   - Later, parry_line and dodge_line are always emitted (no check for defense_intent)
   - Only set _defensive_narrative_emitted when emitting actual defense results
   - Result: both defense_intent and defense result can be shown

**Code Pattern:**
```python
# OLD: Blocked defense results when intent was shown
if not _defensive_narrative_emitted:
    self._emit(N.defense_intent_line(...))
    _defense_intent_emitted = True
    _defensive_narrative_emitted = True  # <-- WRONG: blocks later defense results

# NEW: Intent and result are separate
self._emit(N.defense_intent_line(...))  # Always show intent
_defense_intent_emitted = True
# _defensive_narrative_emitted is NOT set here
# Later, when emitting parry/dodge, _defensive_narrative_emitted will be set
```

**Expected Narrative After Fix:**
```
POL POT pitches his javelin at WRITHEN HILT's lead leg!
WRITHEN HILT eyes the incoming strike carefully!
POL POT misses wildly                              [OR parry/dodge result]
POL POT draws his backup javelin!
[Now clearly shows whether the throw succeeded or failed]
```

**Example Results After Fix:**

*Miss scenario:*
```
POL POT launches his javelin at WRITHEN HILT's throat!
POL POT fails to connect                           [MISS LINE]
POL POT switches to his dagger!
```

*Parry scenario:*
```
POL POT pitches his javelin at WRITHEN HILT's head!
WRITHEN HILT eyes the incoming strike carefully!
WRITHEN HILT is ready for the strike, and deftly parries it!  [PARRY LINE]
POL POT switches to his dagger!
```

*Hit scenario (already working):*
```
POL POT sends his javelin at WRITHEN HILT's skull!
WRITHEN HILT braces to meet the attack!
The defense is overpowered!                        [DEFENSE FAIL]
POL POT's javelin slams into WRITHEN HILT's skull!  [HIT LINE]
POL POT switches to his dagger!
```

**Validation:**
- Created test: `test_throw_fix_validation.py`
- Created debug trace: `test_emit_debug.py`
- Verified miss_lines appear for failed throws
- Verified parry_lines appear for successful defenses against throws
- Verified hit paths still work correctly with defense_fail_line
- All scenarios tested multiple times for consistency
- Test Result: ✅ 100% of thrown attacks now show proper attack result narratives

---

## Fix #7: Favorite Weapon Flavor Timing

**Status:** ✅ COMPLETED & VALIDATED

**Issue:**
The favorite weapon flavor line was emitted **before the attack roll**, creating two problems:
1. **Spoiler:** Players see "finds its target with ugly efficiency" before knowing if the attack hits
2. **Contradiction:** Flavor says "ugly efficiency" but defense fail line says "barely gets past"

**Example of Problem:**
```
Short sharp and mean MITTENS's hatchet finds its target with ugly efficiency.
MITTENS barely gets past IMPELLITTERI's defenses!
MITTENS's hatchet chops into IMPELLITTERI's torso!
   [WRONG: "ugly efficiency" contradicts "barely gets past"]
```

**Root Cause:**
Favorite weapon flavor was emitted at lines 2886-2891, which is BEFORE the attack roll (line 2910+). The flavor language implies the attack is successful ("finds its target"), but this hasn't been determined yet.

**Files Modified:**
- `combat.py` - Lines 2886-2891 (removed from before attack roll) and Lines 3280-3291 (added after successful hits)

**Changes Made:**
1. **Removed** flavor emission from before the attack roll (old lines 2886-2891)
2. **Added** flavor emission after successful hit, after damage is applied (new lines 3280-3291)

**Code Change:**
```python
# OLD: Before attack roll (WRONG)
if not _weapon_thrown_away:
    fav_flavor = _get_favorite_weapon_flavor(att, wpn, as_)
    if fav_flavor:
        self._emit(fav_flavor)
# [... ATTACK ROLL HAPPENS ...]

# NEW: After successful hit (CORRECT)
self._emit(N.damage_line(...))
if not _weapon_thrown_away:
    fav_flavor = _get_favorite_weapon_flavor(att, wpn, as_)
    if fav_flavor:
        self._emit(fav_flavor)
```

**Expected Narrative After Fix:**
```
MITTENS swings his hatchet at IMPELLITTERI's torso
IMPELLITTERI raises his guard against the incoming blow!
But IMPELLITTERI commits to the wrong angle!         [Defense fail line]
MITTENS's hatchet chops into IMPELLITTERI's torso!   [Hit line]
   The weapon cleaves through muscle and draws heavy blood! [Damage]
Short sharp and mean MITTENS's hatchet finds its target with ugly efficiency. [Flavor]
^ Flavor now AFTER damage, so "ugly efficiency" + successful hit = consistent!
```

**Validation:**
- Created test: `test_favorite_weapon_timing.py`
- Verified flavor only appears on successful hits
- Verified no contradiction with "barely gets past" type defense fail lines
- Test Result: ✅ Favorite weapon flavor timing now correct

---

## Document Metadata
- Created: 2026-06-07
- Last Updated: 2026-06-07
- Total Fixes Completed: 7
- Status: Ready for Release Notes
