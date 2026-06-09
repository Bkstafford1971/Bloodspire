# Martial Combat Grammar Fixes for Claw Attacks

**Date:** June 3, 2026  
**Status:** ✓ COMPLETE

## Problem Identified

Original attack lines had poor grammar and awkward sentence structure:

**Before:**
```
SLYTHE slashes at with claws MALRIK SALVOR's body!
```

The issue was:
1. Awkward phrase "slashes at with claws" inserted between attacker and defender
2. Improper grammar and word order
3. Looks confusing and unprofessional

## Solution Implemented

Completely restructured the attack line format for Lizardfolk and Tabaxi to use proper grammar:

**After:**
```
Slythe's claws slash at Malrik Salvor's body!
Whiskers's leg kicks at Granite Stone's abdomen!
Slythe's tail sweeps at Malrik Salvor's chest!
```

## Changes Made

### 1. Updated Verb Lists (narrative.py)

**LIZARDFOLK_ATTACK_VERBS** and **TABAXI_ATTACK_VERBS**
- Changed from verbs with prepositions to clean base/conjugated forms
- Separated singular and plural verbs for proper subject-verb agreement

**Before:**
```python
"claw"  : ["rakes at", "slashes at with claws", "tears at", "rends at with razor claws"],
"kick"  : ["kicks at", "stomps toward", "drives a powerful kick at", ...],
"tail"  : ["sweeps at with tail", "lashes at with tail", ...],
```

**After:**
```python
"claw"  : ["rake", "slash", "tear", "rend"],           # plural verbs for plural subject
"kick"  : ["kicks", "stomps", "drives a powerful kick", ...],  # singular verbs for singular subject
"tail"  : ["sweeps", "lashes", "swings", ...],         # singular verbs for singular subject
```

### 2. Improved Attack Line Format (narrative.py)

**New Format:**
```
{Attacker}'s {weapon} {verb} at {Defender}'s {location}!
```

**Examples:**
- Slythe's claws slash at Malrik Salvor's torso!
- Whiskers's claws tear at Granite Stone's belly!
- Slythe's leg drives a powerful kick at Malrik Salvor's chest!
- Whiskers's leg stomps at Granite Stone's flank!
- Slythe's tail swings at Malrik Salvor's rib cage!

### 3. Added Tabaxi Support

Added TABAXI_ATTACK_VERBS dictionary with proper conjugation
- Tabaxi can use claws and kicks (no tail)
- Same grammatical format as Lizardfolk

## Subject-Verb Agreement

The system now respects English grammar:

| Subject | Verb Form | Example |
|---------|-----------|---------|
| claws (plural) | plural | Slythe's claws **slash** at... |
| leg (singular) | singular | Whiskers's leg **kicks** at... |
| tail (singular) | singular | Slythe's tail **swings** at... |

## Affected Attack Types

✓ **Lizardfolk with Open Hand**
- Claw attacks: rakes, slashes, tears, rends
- Kick attacks: kicks, stomps, drives powerful kick, lashes out
- Tail attacks: sweeps, lashes, swings, brings around

✓ **Tabaxi with Open Hand**
- Claw attacks: rakes, slashes, tears, rends
- Kick attacks: kicks, stomps, drives powerful kick, lashes out

✓ **Other attacks** (non-Open Hand)
- Standard weapon attacks unaffected
- Proper formatting maintained

## Grammar Quality Comparison

| Type | Before | After | Status |
|------|--------|-------|--------|
| Sentence structure | Poor | Excellent | ✓ Fixed |
| Subject-verb agreement | Wrong | Correct | ✓ Fixed |
| Readability | Confusing | Clear | ✓ Fixed |
| Professionalism | Awkward | Professional | ✓ Fixed |

## Test Results

Tested with `test_claw_grammar.py`:
- Lizardfolk claw/kick/tail attacks: All grammatically correct
- Tabaxi claw/kick attacks: All grammatically correct
- Proper pronoun usage: "his/her" not duplicated
- Proper verb conjugation: Plural subjects with plural verbs

---

**Files Modified:**
- narrative.py: LIZARDFOLK_ATTACK_VERBS, TABAXI_ATTACK_VERBS, attack_line() function

**Impact:**
- Purely cosmetic/flavor text improvement
- No game mechanics changed
- All combat functionality preserved
- Enhanced narrative quality
