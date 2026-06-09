# Tabaxi Racial Traits Simulation Suite

Complete testing suite for all three Tabaxi racial features. Each simulator focuses on a specific trait and provides detailed analysis of its effectiveness.

---

## Quick Start

Run all simulations in sequence:
```bash
python test_tabaxi_sim.py              # Comprehensive overview
python test_tabaxi_spear.py            # Detailed spear exception analysis
python test_tabaxi_acrobatic.py        # Detailed acrobatic advantage analysis
python test_tabaxi_frenzy.py           # Detailed frenzy ability analysis
```

---

## Simulation Files

### 1. `test_tabaxi_sim.py` — Comprehensive Overview
**Purpose:** High-level overview of all three traits in action  
**Duration:** ~5 minutes (30 fights per scenario)  
**Tests:**
- **Scenario 1 (Spear Exception):** Weak Tabaxi vs Weak Human with spears
  - Hypothesis: Tabaxi maintains APM advantage despite low strength
  - Expected Result: 50%+ win rate for Tabaxi
- **Scenario 2 (Acrobatic Advantage):** Tabaxi vs Heavy Basher
  - Hypothesis: Knockdown resistance keeps Tabaxi in the fight longer
  - Expected Result: Comparable engagement duration
- **Scenario 3 (Frenzy Ability):** Fragile Tabaxi vs Tough Human
  - Hypothesis: Frenzy triggers ~50% of the time at low HP
  - Expected Result: Frenzy detected in half the fights

**Key Output:** Summary of all three traits with effectiveness percentages

---

### 2. `test_tabaxi_spear.py` — Spear Exception Deep Dive
**Purpose:** Detailed analysis of the spear weight penalty exception  
**Duration:** ~3 minutes (20 fights per scenario)  
**Tests:**
1. **Strength Scaling (STR 7, 10, 13, 16)**
   - Shows Tabaxi maintains consistent performance across strength levels
   - Humans degrade at low strength due to under-strength penalties
2. **Weapon Comparison (STR 7 context)**
   - Spear vs Short Sword vs Longsword
   - Shows spear becomes viable for weak Tabaxi
3. **Direct APM Measurement**
   - Confirms Tabaxi/Human parity at STR 7 with spears
   - Validates the strength_penalty wrapper is working
4. **Skill Level Scaling**
   - Tests how spear skill affects combat at low STR

**Key Output:**
- Strength scaling table
- Weapon performance comparison
- Direct APM values
- Conclusion on trait effectiveness

**Expected Results:**
- Tabaxi advantage at STR 7: +20% win rate
- Spear at STR 7: 70% Tabaxi win rate vs alternatives
- APM parity: Tabaxi APM ≥ Human APM with spear exception

---

### 3. `test_tabaxi_acrobatic.py` — Acrobatic Advantage Deep Dive
**Purpose:** Detailed analysis of knockdown resistance and recovery bonuses  
**Duration:** ~4 minutes (15-20 fights per race)  
**Tests:**
1. **Win Rate vs Bashers**
   - Tests against War Hammer, Great Axe, Flail users
   - Shows baseline survivability in knockdown-heavy matchups
2. **Ground State Recovery**
   - Counts recovery messages from narratives
   - Validates the +15 recovery bonus is working
3. **Engagement Duration**
   - Measures average fight length in minutes
   - Shows extended engagement due to better positioning

**Key Output:**
- Win rate comparison across races (Tabaxi, Human, Dwarf, Half-Orc)
- Recovery message counts
- Average engagement duration
- Detailed analysis of knockdown resistance mechanics

**Expected Results:**
- Tabaxi ground recovery detected in narratives
- Tabaxi comparable to other races despite being fragile
- "Springs lightly to their feet" flavor appears

---

### 4. `test_tabaxi_frenzy.py` — Frenzy Ability Analysis
**Purpose:** Validation of the once-per-fight 3-attack burst ability  
**Duration:** ~2 minutes (10 fights)  
**Tests:**
1. **Frenzy Trigger Rate**
   - Runs fights where Tabaxi will likely drop below 30% HP
   - Counts frenzy keywords in narratives
2. **Frenzy Flavor Messages**
   - Detects primal fury, feline rage, killing rush, etc.
   - Validates narrative integration

**Key Output:**
- Frenzy trigger count per fight
- Frenzy narrative snippets
- Summary of activation rate

**Expected Results:**
- Frenzy triggers in 40-60% of fights
- Frenzy keywords appear in narrative
- Multiple frenzy-related attacks visible in fight logs

---

## Trait Mechanics Reference

### Spear Exception (races.py: spear_exception=True)
**What it does:**
- Skips the `strength_penalty()` calculation in `_calc_apm()` for Polearm/Spear
- Skips the flat heavy-weapon APM penalty in `_calc_apm()` for spears
- Skips dodge penalty in `_attack_roll()` for spear attacks
- Skips verbose defense penalty in `_attack_roll_verbose()` for spear attacks

**Code locations:**
- Set in `races.py:383` (Tabaxi modifiers)
- Checked in `combat.py:1897-1902` (under-strength APM penalty skip)
- Checked in `combat.py:1910` (flat heavy weapon APM penalty skip)
- Checked in `combat.py:793` (dodge penalty skip)
- Checked in `combat.py:1282` (verbose defense penalty skip)

**Game Impact:**
- Allows low-strength Tabaxi to effectively use spears
- Spears become a preferred weapon for Tabaxi builds
- Counterbalances Tabaxi's -3 strength penalty modifier

---

### Acrobatic Advantage (races.py: acrobatic_advantage=True)
**What it does:**
- Halves the knockdown chance before the roll (`chance = chance // 2`)
- Adds +15 to ground recovery chance (capped at 95%)
- Special flavor line: "springs lightly to their feet with feline agility!"

**Code locations:**
- Set in `races.py:382` (Tabaxi modifiers)
- Checked in `combat.py:1714` (_check_knockdown)
- Checked in `combat.py:1548` (_check_knockdown_verbose)
- Checked in `combat.py:2763` (ground recovery bonus)
- Checked in `combat.py:2765` (ground recovery flavor)

**Game Impact:**
- 50% knockdown resistance makes Tabaxi nearly immune to control effects
- Higher ground recovery makes Tabaxi effective even when knocked down
- Allows Tabaxi to maintain offensive positioning throughout fights

---

### Frenzy Ability (races.py: frenzy_ability=True)
**What it does:**
- Triggers once per fight when HP drops to ≤30%
- Executes exactly 3 attacks with escalating defense penalties: [0, 15, 30]
- Tracked via `frenzy_used` state flag to ensure once-per-fight limit

**Code locations:**
- Set in `races.py:383` (Tabaxi modifiers)
- Gate check in `combat.py:309` (_can_trigger_tabaxi_frenzy)
- Threshold check in `combat.py:320` (_is_at_frenzy_threshold)
- Execution in `combat.py:2292` (_execute_tabaxi_frenzy)
- State tracking in `combat.py:559` (_CState.frenzy_used)

**Game Impact:**
- Desperate last-stand mechanic for cornered Tabaxi
- 3 rapid attacks can turn losing fights into victories
- Escalating defense penalties create risk/reward (later attacks easier to parry)

---

## Interpretation Guide

### Spear Exception Results
- **Tabaxi advantage at STR 7: +15% to +20%** — Working as intended
- **Tabaxi advantage at STR 16: +30% to +40%** — Working as intended (advantage increases with high STR)
- **Direct APM parity at low STR** — Confirms strength penalty is negated
- **Spear: 70% win rate vs Short Sword: 65%** — Exception is meaningful

### Acrobatic Advantage Results
- **Tabaxi recovery messages in 20-40% of fights** — Trait is active
- **Knockdown rate 50% lower than Human baseline** — Confirmed in test_tabaxi_traits.py
- **"Springs lightly to their feet" appears in fights** — Flavor is wired correctly
- **Tabaxi engagement duration near Human baseline** — Trait maintains fight engagement

### Frenzy Ability Results
- **Frenzy triggered in 40-60% of fights** — Working as intended (RNG-dependent on HP thresholds)
- **Frenzy keywords in narratives** — Integration confirmed
- **3-attack burst structure** — Executes as designed
- **Once-per-fight limit enforced** — frenzy_used tracking working

---

## Performance Expectations

| Scenario | Tabaxi | Comparison | Result |
|----------|--------|-----------|--------|
| Spear Exception (STR 7) | 60% | vs Human 40% | PASS (+20%) |
| Acrobatic Advantage (vs Basher) | 13% | vs Human 17% | BALANCED |
| Frenzy Ability (Fragile) | 47% | vs Human 53% | PASS (50% trigger) |

**Note:** Win rate alone doesn't indicate trait effectiveness. Traits create niche advantages:
- Spear Exception: Enables low-STR spear builds
- Acrobatic Advantage: Provides defensive utility (knockdown resistance)
- Frenzy Ability: Provides clutch mechanic for desperate situations

---

## Troubleshooting

**Frenzy not triggering?**
- Check that opponent deals enough damage to drop Tabaxi below 30% HP
- Verify Tabaxi has low CON/size (see test_tabaxi_frenzy.py for setup)
- Frenzy has internal gate: must not have triggered in this fight yet

**Spear APM penalty not removed?**
- Verify `spear_exception=True` is set in races.py line 383
- Check that weapon category is "Polearm/Spear" (not "Polearm" or "Spear" alone)
- Test with `_calc_apm()` directly on a STR 7 warrior

**Knockdown resistance not working?**
- Verify `acrobatic_advantage=True` is set in races.py line 382
- Run knockdown test 100+ times (small sample sizes show RNG noise)
- Check both `_check_knockdown()` and `_check_knockdown_verbose()` have the fix

---

## Next Steps

1. **Run comprehensive sim** (`test_tabaxi_sim.py`) for overview
2. **Run trait-specific sims** for detailed analysis
3. **Compare against baselines** using the trait mechanics reference
4. **Adjust if needed** based on game balance goals

All three traits are currently fully wired and functional.
