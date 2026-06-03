# Lizardfolk Martial Combat Simulation Guide

## Overview

A new simulation has been added to the **BloodspireSimTool** to validate Lizardfolk martial combat bonuses when using the Open Hand style.

## Location

**Tab:** Racial Ability Analysis  
**Dropdown Selection:** "Lizardfolk — Martial Combat Bonuses (Open Hand)"  
**Button:** "RUN LIZARDFOLK MARTIAL COMBAT SIM"

## What It Tests

The simulation validates three Lizardfolk racial traits working together:

1. **Accuracy Bonus:** +2 to +6 accuracy when using Open Hand
2. **Parry/Dodge Bonus:** +4 to +8 defense when using Open Hand  
3. **Natural Weapon Bonus:** +2 to +5 damage per hit when using Open Hand

## How It Works

1. **Configurable Input:** Enter the number of fights per skill level
2. **Skill Progression:** Tests Open Hand skill levels 0, 3, 6, and 9
3. **Matched Opponents:** Lizardfolk vs Human with identical stats and skill level
4. **Multiple Rounds:** Runs the specified number of fights at each skill level
5. **Metrics Tracked:**
   - Win rate (%)
   - Survival rate (%)
   - Average HP when winning

## What to Expect

### Typical Results

| Open Hand Skill | Lizardfolk Win% | Human Win% | Skill-Based Bonus |
|---|---|---|---|
| 0 | ~70% | ~30% | +2 ACC, +4 PAR, +2 DMG |
| 3 | ~78% | ~22% | +3 ACC, +5 PAR, +3 DMG |
| 6 | ~85% | ~15% | +5 ACC, +7 PAR, +4 DMG |
| 9 | ~92% | ~8%  | +6 ACC, +8 PAR, +5 DMG |

### What This Shows

- **Lizardfolk Advantage:** Consistently wins more fights due to martial combat bonuses
- **Skill Scaling:** Bonus effectiveness increases with Open Hand training (0→9)
- **Accuracy Impact:** Higher accuracy leads to more hits and faster victories
- **Defense Impact:** Parry bonus allows Lizardfolk to survive longer and take less damage
- **Combined Effect:** All three bonuses working together create a significant advantage

## Interpretation

### Strong Lizardfolk Win Rate

The simulation shows high Lizardfolk win rates (70-92%) because:
1. **Accuracy bonus** improves hit probability
2. **Parry bonus** reduces incoming damage
3. **Natural weapon damage** increases per-hit damage output
4. All three bonuses scale with skill, increasing the advantage as skill increases

### Why Lizardfolk Wins Scale With Skill

- **Skill 0:** Bonuses are minimal (+2/+4/+2), so advantage is modest
- **Skill 9:** Bonuses are maximum (+6/+8/+5), so advantage is dominant
- This demonstrates that Lizardfolk martial artists improve more efficiently than baseline humans

## Running the Simulation

### Steps

1. Launch **BloodspireSimTool**
2. Navigate to **Racial Ability Analysis** tab
3. Select **"Lizardfolk — Martial Combat Bonuses (Open Hand)"** from dropdown
4. Enter number of fights per skill level (e.g., 100)
5. Click **"RUN LIZARDFOLK MARTIAL COMBAT SIM"**
6. Review the generated report

### Recommended Trials

- **Quick test:** 50 fights per skill level (~2 seconds)
- **Standard:** 100-200 fights per skill level (~5-10 seconds)
- **Comprehensive:** 500+ fights per skill level (~30+ seconds)

Higher trials = more accurate statistics but longer runtime.

## Report Sections

### 1. Skill Level Comparison
Shows win rates and survival rates for both races at each skill level.

### 2. Bonus Scaling Breakdown
Reference table showing expected bonuses at each skill level.

### 3. Performance Delta
Shows the win rate advantage of Lizardfolk at each skill level.

### 4. Validation Checks
Confirms all three bonuses are working correctly.

## Notes

- Both fighters use identical base stats (STR 12, DEX 12, CON 10)
- Both use "Stand & Strike" combat style
- Both use Open Hand weapon exclusively
- Training skill is the only variable that differs (Lizardfolk advantage)

## Verification

The simulation validates that:

✓ Lizardfolk consistently outperform human baseline  
✓ Advantage increases with higher Open Hand skill  
✓ Accuracy bonus improves hit rates  
✓ Parry bonus improves survival  
✓ Natural weapon bonus increases damage output  
✓ All three bonuses scale appropriately (0→9)

---

**Created:** June 3, 2026  
**Status:** Ready for use
