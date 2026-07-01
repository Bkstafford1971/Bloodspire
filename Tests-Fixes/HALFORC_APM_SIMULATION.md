# Half-Orc Heavy Weapon APM Scaling Simulation

## Overview
Added a new simulation test to `simulation_tool.py` to validate the new **fractional APM system** for heavy weapons. This test shows:
1. **How APM increases** as Half-Orc Great Sword skill goes from 1→9
2. **The exact APM values** at each skill level (base + fractional chance)
3. **Win rate improvement** as APM increases vs fixed baseline opponents

## Test Design

### Test Warrior (Half-Orc)
- **Stats**: STR 17, DEX 12, CON 17, INT 9, PRE 4, SIZ 12
- **Weapon**: Great Sword (6.8 weight, two-handed)
- **Armor**: Leather + Steel Cap
- **Fighting Style**: Strike, activity 5
- **Luck**: 15
- **Skill Range**: Tested at levels 1, 2, 3, 4, 5, 6, 7, 8, 9

### Baseline Opponents (All Fixed at Skill 1)

All baselines use **Great Sword skill 1** for consistent comparison. As Half-Orc skill increases, the APM advantage grows, showing the tangible benefit of weapon skill investment.

**Dwarf**
- Stats: STR 17, DEX 12, CON 17, INT 10, PRE 6, SIZ 10
- Weapon: Great Sword (skill 1)
- Armor: Brigandine + Steel Cap
- Style: Strike, activity 5

**Gnome**
- Stats: STR 12, DEX 16, CON 15, INT 15, PRE 6, SIZ 8
- Weapon: Great Sword (skill 1)
- Armor: Brigandine + Steel Cap
- Style: Strike, activity 5

**Human**
- Stats: STR 15, DEX 12, CON 17, INT 11, PRE 6, SIZ 10
- Weapon: Great Sword (skill 1)
- Armor: Brigandine + Steel Cap
- Style: Strike, activity 5

## What's Measured

For each skill level (1-9), the simulation:
1. **Calculates APM** for Half-Orc at that skill level
2. **Shows APM delta** vs baseline (skill 1)
3. **Runs fights** (100-500 configurable) vs Dwarf, Gnome, Human
4. **Tracks win rates** to show APM improvement impact

**Output shows:**
- Win % vs each opponent
- Average win rate across all three
- Trend indicator (↑ improvement, ↓ decline, → flat)
- **APM progression table** (new!)
- Exact APM base + fractional values at each skill level

## Expected Results with New APM System

### Heavy Weapon APM Bonuses (Applied at _calc_apm)
```
Baseline (all races, all stats):  3.0 APM (from base calculation)

Half-Orc additions:
Skill 1-2: +0.5 APM per level  → ~3.5 base
Skill 3-4: +1.0 APM per level  → ~4.0-4.5 base
Skill 5-6: +1.5 APM per level  → ~4.5-5.0 base
Skill 7-8: +2.0 APM per level  → ~5.0-5.5 base
Skill 9: +3.0 APM              → ~6.0 base
```

### Predictions
- **Skill 1**: ~50% win rate — equal APM as baseline
- **Skill 5**: ~55-60% win rate — +1.5 APM advantage
- **Skill 9**: ~65-70% win rate — +3.0 APM advantage

If the new APM system works correctly, we should see:
1. **Consistent APM scaling** in the report (showing exact +0.5, +1.0, +1.5, +2.0, +3.0 bonuses)
2. **Linear win rate improvement** as APM increases (+1-2 percentage points per 0.5 APM gain)
3. **Clear data** showing "skill investment = more actions = better win rate"

## How to Run

1. **Open simulation_tool.py**
2. **Navigate to "Racial Sim" tab**
3. **Select** "Half-Orc — Heavy Weapon APM Scaling Test (Fractional APM System)"
4. **Choose fights**: 100, 250, or 500 per test
5. **Click** "RUN HEAVY WEAPON APM SIM"
6. **Results appear** in text area with trend analysis
7. **Export** results as .txt file via "Download Report" button

## Output Example

```
HALF-ORC HEAVY WEAPON APM SCALING TEST (FRACTIONAL APM SYSTEM)
Half-Orc: STR 17 DEX 12 CON 17 INT 9 PRE 4 SIZ 12, Great Sword (skill 1-9), Strike activity 5
Baselines: All unskilled (skill 1) Great Sword, Strike activity 5
  - Dwarf: STR 17 DEX 12 CON 17 INT 10 PRE 6 SIZ 10, Brigandine + Steel Cap
  - Gnome: STR 12 DEX 16 CON 15 INT 15 PRE 6 SIZ 8, Brigandine + Steel Cap
  - Human: STR 15 DEX 12 CON 17 INT 11 PRE 6 SIZ 10, Brigandine + Steel Cap
Fights per skill level: 500

WIN RATES BY SKILL LEVEL (Half-Orc vs Unskilled Baseline)
  SKILL  vs DWARF   vs GNOME   vs HUMAN   AVERAGE   TREND
  1      48.2%      50.5%      51.2%      50.0%     BASELINE
  2      50.2%      52.4%      53.2%      51.9%     ↑ +1.9%
  3      52.4%      54.8%      55.6%      54.3%     ↑ +2.4%
  4      54.6%      57.2%      57.8%      56.5%     ↑ +2.2%
  5      57.2%      59.8%      60.4%      59.1%     ↑ +2.6%
  6      59.4%      62.2%      62.8%      61.5%     ↑ +2.4%
  7      61.8%      64.6%      65.2%      63.9%     ↑ +2.4%
  8      63.2%      66.2%      66.8%      65.4%     ↑ +1.5%
  9      65.8%      68.4%      69.2%      67.8%     ↑ +2.4%

APM SCALING ANALYSIS
  Baseline APM (skill 1, all races):
    Dwarf: 4 base APM + 0.32 fraction (32% chance for +1)
    Gnome: 4 base APM + 0.38 fraction (38% chance for +1)
    Human: 4 base APM + 0.35 fraction (35% chance for +1)

  Half-Orc APM progression (vs baseline):
    Skill 1: 4 base APM + 0.32 fraction (32% chance for +1) [Δ 0 vs baseline]
    Skill 2: 4 base APM + 0.78 fraction (78% chance for +1) [Δ 0 vs baseline]
    Skill 3: 5 base APM + 0.32 fraction (32% chance for +1) [Δ +1 vs baseline]
    Skill 4: 5 base APM + 0.78 fraction (78% chance for +1) [Δ +1 vs baseline]
    Skill 5: 5 base APM + 0.82 fraction (82% chance for +1) [Δ +1 vs baseline]
    Skill 6: 6 base APM + 0.32 fraction (32% chance for +1) [Δ +2 vs baseline]
    Skill 7: 6 base APM + 0.78 fraction (78% chance for +1) [Δ +2 vs baseline]
    Skill 8: 6 base APM + 0.38 fraction (38% chance for +1) [Δ +2 vs baseline]
    Skill 9: 7 base APM + 0.32 fraction (32% chance for +1) [Δ +3 vs baseline]

WIN RATE ANALYSIS
  Skill 1 average win rate: 50.0%
  Skill 9 average win rate: 67.8%
  Total improvement: +17.8 percentage points
  [PASS] Skill investment is HIGHLY REWARDING - significant win rate improvement

  Matchup progression:
    vs Dwarf:  Skill 1: 48.2%  →  Skill 9: 65.8%
    vs Gnome:  Skill 1: 50.5%  →  Skill 9: 68.4%
    vs Human:  Skill 1: 51.2%  →  Skill 9: 69.2%
```

## Validation Criteria

**PASS Conditions**:
- Skill 1 → Skill 9 improvement: **8%+ percentage points** (shows scaling works)
- Skill 9 average: **45%+** (competitive against baselines)
- Consistent upward trend (no huge drops)

**WARN Conditions**:
- Improvement < 3% (APM scaling too weak)
- Skill 9 < 40% (still underpowered)
- Inconsistent results (some matchups improve, others decline)

## Integration

**File**: `simulation_tool.py`
**Method**: `_sim_halforc_heavy_weapon_apm()`
**Menu Location**: Racial Sim tab → dropdown → "Half-Orc — Heavy Weapon APM Scaling Test"
**Export**: Text format via "Download Report (.txt)" button

## Future Enhancements

1. **Per-skill-level breakdown** — Show exact APM rolls for each fight
2. **Action economy** — Track average actions taken by Half-Orc vs opponent
3. **Damage per action** — Compare efficiency (damage ÷ actions)
4. **Endurance patterns** — Show if APM boost creates different endurance burn
5. **Fractional roll statistics** — Count how often bonus actions are rolled per skill level
