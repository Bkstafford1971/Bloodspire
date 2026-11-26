# Bloodspire: Non-Weapon Skill Audit

Date: 2026-10-24
Method: static code read of `warrior.py`, `combat.py`, `strategy.py`, `team.py`, `ai.py`, `ai_brain.py`, `matchmaking.py`, `scout_report.py`, `combat_debug_logger.py`, `league_server.py` and the client skill list. The game was not run and save files were not inspected. "Wired" means the skill level is read by live combat code and changes an outcome.

> **Update (same day):** Strike, Sweep and Throw are now implemented in `combat.py`. The sections below describe the state *before* that change; see "Implemented fixes" at the end.

## Summary

`NON_WEAPON_SKILLS` in `warrior.py:458` holds **16** skills. The header comment on line 9 still says "10 non-weapon", which is out of date.

| Skill | Status | One-line verdict |
|---|---|---|
| Dodge | Wired, strong | Core defense |
| Parry | Wired, strong | Core defense, feeds counters |
| Initiative | Wired, strong | Turn order, plus a small dual-wield bonus |
| Feint | Wired, solid | Attack bonus on every swing, plus Decoy |
| Lunge | Wired, style-gated | Only does anything in the Lunge style |
| Charge | Wired, solid | Thrusts, shields and Martial Combat |
| Acrobatics | Wired, broad | Dodge, ground recovery, endurance |
| Riposte | Wired, solid | Counterattack on strong parries |
| Slash | Wired, narrow | Bleeding with slash weapons |
| Cleave | Partly wired | Parry penetration only |
| Bash | Partly wired | Same effect as Cleave |
| Disarm | Wired, weak | Small add-on to a rare event |
| Brawl | Barely wired | Ground recovery only |
| **Strike** | **Not wired** | **Does nothing** |
| **Sweep** | **Not wired** | **Does nothing** |
| **Throw** | **Not wired** | **Does nothing** |

Three skills (Strike, Sweep, Throw) can be trained but have no effect. Brawl, Cleave and Bash are only partly wired. Details follow.

---

## Fully wired skills

### Dodge
- **Effect:** `+4 × level` on the dodge roll (`combat.py:1026`). The defender's own weapon skill adds `+2 × level` to the same roll.
- **Also used by:**
  - the critical-defense skill contest (`combat.py:3981`)
  - the "best defense skill" term that reduces the chance of a thrown weapon landing (`combat.py:1206`)
  - the post-fight observation pool
  - AI training for many presets
- **Verdict:** healthy and central.

### Parry
- **Effect:** `+4 × level` on the parry roll (`combat.py:1009`), plus `+3 × level` from the weapon skill.
- **Also used by:**
  - Counterstrike style counter chance, `30 + 5 × level` (`combat.py:4086`)
  - the defender's chance to read a Decoy feint, `55 + 3 × level` (`combat.py:1147`)
  - the critical-defense contest
  - throw-landing reduction
- **Verdict:** healthy. It is the best-integrated skill in the game.

### Initiative
- **Effect:** adds to the turn-order roll, `×3` per level, or `×4` at level 5 and above (`combat.py:784`). It also adds up to +3.6% to the Elf dual-wield off-hand chance (`combat.py:316`).
- **Concern:** the second initiative function at `combat.py:1437` uses a flat `×3` with no `×4` step at level 5 and above. If that function is a debug or explain mirror, it will report different numbers than live combat for levels 5-9. If it is live, the two paths disagree.
- **Verdict:** healthy, with one possible inconsistency to check.

### Feint
- **Effect:**
  - `+2 × level` on every attack roll (`combat.py:901`), regardless of style.
  - It drives the Decoy pre-attack roll, `25 + 5 × level + DEX bonus`, capped at 85% (`combat.py:1153`).
  - It adds up to +2.7% to the Elf off-hand chance.
- **Verdict:** healthy.

### Lunge
- **Effect:** `+3 × level` on the attack roll **only when the active style is Lunge** (`combat.py:902`).
- **Note:** under any other style, training Lunge does nothing. That is a reasonable design, but it should be visible to the player. The Acrobatics endurance relief for Lunge and Engage & Withdraw is a separate skill (see Acrobatics).
- **Verdict:** wired, conditional.

### Charge
- **Effect:**
  - Attack roll `+3 × level` with thrust weapons, shields, or Martial Combat (`combat.py:845`).
  - Damage `+⅓ × level` on those same attacks (`combat.py:863`).
  - `-3 × level` off the defender's parry roll against spear-category weapons (`combat.py:872`).
  - It also decides the flavor text "rush" versus "bash" at level 4 and above (`combat.py:486`).
- **Verdict:** healthy, and it is one of the better-designed skills.

### Acrobatics
- **Effect:**
  - Dodge `+2 × level`, with Tabaxi getting `+3 × level`, plus a bonus in Engage & Withdraw (`combat.py:1039`).
  - Ground recovery: `15% × level` (cap 85%) when the warrior won initiative, and `8% × level` (cap 40%) when they lost it (`combat.py:3727`, `combat.py:4503`).
  - Endurance: removes the extra 10% burn on Lunge and Engage & Withdraw, 1% per level (`combat.py:2338`).
- **Verdict:** healthy, with three separate uses.

### Riposte
- **Effect:**
  - After a strong parry (margin of -30 or worse), the chance of a counterattack is `40% + 5% × level` (`combat.py:4075`).
  - It is zero at level 0 for non-Gnomes.
  - Gnomes also get a mastery path of `15% + 4% × level`, and a weak-parry path of `4% + 2% × level`.
  - It adds up to +4.5% to the Elf off-hand chance.
  - Attacker Cleave level 3 and above reduces it (`-15` per level above 2).
- **Verdict:** healthy. Riposte only fires off a parry, never off a dodge. A dodge-oriented warrior gets nothing from it.

### Slash
- **Effect:** with a slash-category weapon, `5% × level` chance per hit to add a bleeding wound (`combat.py:4296`). Each wound bleeds for damage at a 40% tick chance.
- **Gap:** the debug logger prints a "slash skill bonus" damage line (`combat_debug_logger.py:371`), but nothing in the damage code ever sets `slash_bonus`. The only effect is bleeding.
- **Verdict:** wired and working, but narrow.

---

## Partly wired skills

### Cleave and Bash (the same mechanic)
- **Effect:** when a heavy hit lands in the "strong parry" band and the attacker's weapon is in the Cleave or Bash weapon set:
  - Chance to punch through the parry is `5% × level` (+15% of that under the Bash style).
  - On success it deals flat `weapon weight × 2` damage and ends the exchange (`combat.py:4009-4046`).
  - Cleave level 3 and above also cuts the defender's riposte chance.
- **Problems:**
  1. The two skills are functionally identical. The code takes `max(cleave, bash)` and only the flavor text differs. Great Sword and Halberd are in both sets, so the player gets no choice there.
  2. The penetration damage is **flat and unmodified**. It ignores armor, strength, aim and critical effects, and it returns early. At 5% × 9 = 45% it is a strong effect, but it skips the whole normal damage pipeline.
  3. The debug logger expects `cleave_bonus`, `bash_bonus`, and a `cleave_master_mult` (×1.25 at level 9). **Nothing in `combat.py` ever sets them.** The "master" bonuses described in the logger do not exist in live combat.
- **Verdict:** half-built. The parry penetration works. The damage bonuses and the level-9 mastery bonus never got connected.

### Disarm
- **Effect:** when a parried attack's roll exceeds `defender STR × 4` and the defense point is not covering the aim, the base chance is 8% plus 2% × level to knock the weapon out of the defender's hands (`combat.py:4131`).
- **Problems:**
  - It stacks on a rare precondition, so the real-world rate is low. The most it can reach is 26%, and only on those rare events.
  - It is the attacker's skill, but `STYLE_SKILL_SYNERGY` lists it for Parry and Defend styles, which are defensive. A defender-style warrior who trains Disarm gets very little from it.
  - Cestus and Open Hand fighters cannot be disarmed.
- **Verdict:** wired but low impact. A candidate for a buff or a rework.

### Brawl
- **Effect:** ground recovery only. `+6% × level` when the warrior won initiative, `+3% × level` when they lost it (`combat.py:3724`, `combat.py:4500`). It is combined with Acrobatics through `max()`, not added, so a warrior with high Acrobatics gets nothing extra from Brawl.
- **Problems:**
  - It does not affect Martial Combat attack, damage or defense. `STYLE_SKILL_SYNERGY` lists it first for Martial Combat, which implies it should.
  - The debug logger references a "brawl master (lv9) ×1.10" multiplier that is never set.
  - Monsters get Brawl 7 for free, but it only changes how often they stand up.
- **Verdict:** nearly empty. It works, but it is too small to justify a training slot.

---

## Not wired (trainable, no effect)

### Strike
- Nothing in combat, damage, defense or initiative reads `skills["strike"]`.
- It appears in the trainable list, the client's training dropdown (`bloodspire_client.html:4838`), the `STYLE_SKILL_SYNERGY` map, and a debug-logger loop looking for `strike_bonus`. Nothing sets that value.
- It is easy to confuse with the **Strike combat style**, which is separate and works. The skill has no tie to it.
- **Impact:** a player who trains Strike spends training sessions for no benefit.

### Sweep
- Nothing reads `skills["sweep"]`.
- The weapon flag `can_sweep` is set on many weapons in `weapons.py` (flails, staffs, polearms, scimitar, and others), but `combat.py` never checks it. The only "sweep" strings in combat are flavor text.
- `scout_report.py:175` describes Sweep as "going for the legs", so scouts report a tactic that cannot happen.
- Monsters are given Sweep 7 (`team.py:946`), which does nothing.
- **Impact:** dead skill and a dead weapon flag. It looks like the knockdown mechanic was planned and never built.

### Throw
- Nothing reads `skills["throw"]`. Opportunity Throw attack and damage use the thrown **weapon's** skill (`combat.py:1299`). The comment at `combat.py:1306` says damage requires "skill training in throw/weapon", but the code only uses the weapon skill.
- `ai_brain.py:114` has an AI preset (a "skirmisher") whose training list is `["throw", "dexterity", "dodge"]`. That AI wastes a third of its training on a skill with no effect.
- **Impact:** dead skill. The Opportunity Throw style is functional, but Throw is not part of it.

---

## Systemic findings

1. **`STYLE_SKILL_SYNERGY` is never used** (`strategy.py:650`). Its comment says "As a warrior trains these skills, the natural flaws of the style are gradually reduced" and "Used by the training advisor". Nothing in the code reads it. It is the only place that connects Strike, Sweep, Throw and Brawl to a style, and none of those connections are real.
2. **Header comment is stale.** `warrior.py:9` says "10 non-weapon", and the list has 16.
3. **The debug logger is ahead of the code.** It prints damage terms and master multipliers (`cleave_bonus`, `bash_bonus`, `slash_bonus`, `strike_bonus`, `cleave_master_mult`, `brawl_master_mult`) that live combat never produces. They look like a planned design that was dropped.
4. **AI training uses only a handful of skills.** Computer-controlled teams train `dodge`, `parry`, `initiative`, `lunge`, `feint`, and `throw` (dead). They never train Riposte, Acrobatics, Charge, Slash, Cleave, Bash, Disarm or Brawl. The post-fight observation pool is also limited to `parry`, `initiative`, `dodge`, `feint` and the opponent's weapon. League AI will therefore never exercise most of these skills.
5. **Style-gating is invisible.** Lunge only works under the Lunge style, and Cleave and Bash only on matching weapon sets. Nothing in the data or UI warns the player, so training them under the wrong style or weapon silently wastes sessions.

## Suggested priorities

1. **Fix or hide the three dead skills** (Strike, Sweep, Throw). Either implement them or remove them from `NON_WEAPON_SKILLS` and the client dropdown so players cannot waste sessions. Sweep is the closest to ready, because the weapon flag `can_sweep` already exists.
2. **Reconnect the missing damage terms** the logger already expects (`cleave_bonus`, `bash_bonus`, `slash_bonus`, `strike_bonus`, mastery multipliers), or delete the logger lines.
3. **Differentiate Cleave from Bash.** Right now they are one skill with two names.
4. **Give Brawl a real job** in Martial Combat, which is what the synergy map says it is for.
5. **Resolve the initiative `×3` / `×4` inconsistency** at `combat.py:1437` versus `combat.py:784`.
6. **Decide on the synergy map.** Implement the style flaw reduction it describes or delete it.
7. **Update the AI trainers** to use the wired skills (Riposte, Acrobatics, Charge, Slash) and drop `throw`.

---

## Implemented fixes (all in `combat.py`)

| Skill | Effect now |
|---|---|
| **Throw** | Opportunity Throw only: `+3 × level` on the attack roll, `+0.5 × level` on the damage ceiling. Applied in both the live and explain copies of the attack and damage code. |
| **Strike** | Armor-piercing: `3% × level` of the target's armor is ignored (27% at level 9) with `STRIKE_WEAPONS`: stiletto, dagger, epee, small/military/pick-axe/great picks, short/boar/long spear, trident, javelin. Feeds the existing bypass term in the damage calculation. |
| **Sweep** | On a landed melee hit with a `can_sweep` weapon (spears, trident, flails, quarterstaff, great staff, ball and chain): `3% × level` chance to knock the target down. Reduced 1% per size point above 12, halved for Tabaxi, and never fires on thrown attacks. |

Verification (scratch script, not part of the project): at level 9, Short Spear damage against Full Plate went from about 15 to 18, and a non-piercing Long Sword was unchanged. Javelin Opportunity Throw damage went from 18 to 22 at a fixed margin. Sweep measured 27.2% at level 9 and 0% at level 0 or on non-sweep weapons. 150 full fights ran without errors, with 213 sweep knockdowns.

Not done: Sweep while unarmed under Martial Combat (left out pending a decision), and the other items in the priority list above.

### Martial Combat additions (Sweep and Brawl)

"Martial Combat stance" means the Martial Combat style while fighting unarmed (primary weapon Open Hand).

| Skill | Effect in Martial Combat stance |
|---|---|
| **Sweep** | `4% × level` knockdown chance on a landed hit (36% at level 9), versus 3% per level with sweeping weapons. Same size and Tabaxi adjustments. |
| **Brawl** | `+2 × level` on the attack roll and `+0.5 × level` on the damage ceiling. Ground recovery (all styles) is unchanged. |

Constants are `SWEEP_MARTIAL_PER_LEVEL`, `BRAWL_ATTACK_PER_LEVEL` and `BRAWL_DAMAGE_PER_LEVEL` in `combat.py`. Neither skill does anything outside the stance.

### Tuning after mirror-matchup tests
- **Brawl** attack bonus lowered to `+1 × level` (damage ceiling stays `+0.5 × level`).
- **Strike** armor bypass raised to `4% × level` (36% at level 9). Earlier figures in this report that say 3% or `+2` are superseded.
- Full Plate fighters (Human, STR/CON 14) run out of endurance in about 2 minutes in every mirror fight, so those fights are decided by exhaustion rather than damage. This is a separate balance question.
- **Brawl** damage ceiling lowered again to `+0.35 × level` (attack `+1 × level`). Mirror test: Brawl 3 / 6 / 9 wins about 64% / 69% / 77% against an identical fighter.
- **Strike vs Full Plate** tested with a Full Plate / Full Helm / Broad Sword / Target Shield defender (Parry, Defend or Counterstrike at activity 2) against a Brigandine or Cuir Boulli attacker (activity 7) using a spear, military pick or epee. Strike 9 raised the attacker's win rate by about 2 points against a weak tank, 7 against a trained tank and 6 against an elite tank, with large gains for Total Kill and Engage & Withdraw.

### Initiative fix
`_initiative_roll_verbose` (used whenever the debug logger is on) disagreed with the live `_initiative_roll`: it used `×3` at every level instead of `×4` at level 5+, it left out the Half-Orc DEX initiative tiers, and it ignored head and leg injury penalties. It now mirrors the live function. Its breakdown key `init_skill_x3` was renamed `init_skill`.

### Cleave and Bash riders
Both skills still break through a parry with a `5% × level` chance for flat `weight × 2` damage. The Bash style's `+15%` now applies only to Bash penetrations. Weapons in both lists (Great Sword, Halberd) use whichever skill is higher.
- **Cleave** also splits the defender's guard: one stack per cleave through a parry (cap 4), each stack `-3` on the defender's later parry rolls. The existing riposte suppression stays.
- **Bash** also drains `1.5% × level` of the defender's max endurance and has a `3% × level` chance to knock them down (reduced 1% per size point above 12, halved for Tabaxi).
- Constants: `GUARD_DAMAGE_STACK_CAP`, `GUARD_DAMAGE_PARRY_PEN`, `BASH_ENDURANCE_DRAIN_PER_LEVEL`, `BASH_KNOCKDOWN_PER_LEVEL`.
- Measured at level 9 against a parry specialist: Cleave win rate 64% to 70% with the rider, Bash 47% to 80%. Bash's rider is clearly stronger than Cleave's and probably needs trimming.

### Bash trim and debug-roll fix
- **Bash trimmed:** wind-out `1% × level` of max endurance (was 1.5%), knockdown `2% × level` (was 3%). At level 9 the rider now adds about 14-18 win-rate points (was 21-33), against about 7-9 for Cleave.
- **`_defense_roll_verbose` now matches `_defense_roll`.** It had been missing the Half-Orc DEX penalty reductions (parry and dodge), the head, arm and leg injury penalties, and Tactician's Edge. Verified identical across 12,096 combinations of race, DEX, style, shield, injuries, guard damage, encumbrance, ground and endurance states.
- **Still open:** `_attack_roll_verbose` differs from `_attack_roll`. It ignores head and primary-arm injury penalties and weapon-dropped penalty, and it leaves out the Halfling +4 accuracy bonus.

### Attack roll parity fix
`_attack_roll_verbose` was missing head and primary-arm injury penalties, the dropped-weapon penalty and the Halfling +4 accuracy bonus. Fixed. Live and debug versions of the initiative, attack, defense and damage calculations now give identical results in every combination tested (about 33,000 combinations across races, styles, weapons, armor and fight states).

### Correction: Disarm was not weak
The earlier audit called Disarm low impact. That came from a test setup where every fighter's defense point matched the aim point, which blocks the disarm check completely. With defense points off, a parry fighter was disarmed about 0.9 times per fight at Disarm 0 and 1.8 times at Disarm 9, and the win rate rose from 34% to 62%.

### Disarm rework
The chance is now `3% + 3% × level` (3% to 30%) plus a flat weapon bonus, in percentage points: Swordbreaker `+10`; Epee, Heavy Whip, Scythe, Net and Ball and Chain `+5`. The better of the attacking weapon and the off-hand weapon counts, so a Swordbreaker works in the off-hand. The trigger (attack roll above defender Strength × 4, defender not guarding the aimed spot) and the effect of a disarm are unchanged. Constants: `DISARM_BASE_CHANCE`, `DISARM_PER_LEVEL`, `DISARM_WEAPON_BONUS`; function `_disarm_chance`.
Measured disarms per fight at Disarm 0: Long Sword 0.37, Epee 0.70, Long Sword with off-hand Swordbreaker 1.13. At Disarm 9 the three are 1.83, 1.83 and 2.17: the weapon bonus matters most for untrained fighters.

### Stale code cleanup
- `warrior.py` header now says 16 non-weapon + 48 weapon skills.
- `combat.py` header rewritten to match the current rules (initiative x4 at level 5+, 25% luck chance, margin/55 damage fraction, percentage armor, skill bonuses, the 10/20/30/40% death-check tiers).
- `weapons.py` flag docs corrected: `can_sweep` and `can_disarm` weapon lists updated, and `mc_compatible`, `flail_bypass` and `charge_attack` marked informational (combat does not read them).
- `combat_debug_logger.py`: the damage breakdown described an older damage formula (it printed "weapon base 0.00", "Ceiling: 0" and a nonsense raw value) and referenced the never-implemented master multipliers. `log_damage` was rewritten to print the current calculation: damage range, bonuses (STR, weapon skill, Charge, Throw, Brawl), floor and ceiling, fraction, modifiers, armor with bypass sources (including Strike), then final damage.
- `STYLE_SKILL_SYNERGY` removed from `strategy.py` (nothing read it; its comment promised style-flaw reductions that were never built). Its contents, kept for reference:

| Style | Skills it favoured |
|---|---|
| Counterstrike | Parry, Initiative, Feint, Riposte |
| Decoy | Feint, Parry, Acrobatics, Riposte |
| Lunge | Lunge, Initiative, Dodge, Charge |
| Wall of Steel | Initiative, Parry, Dodge, Feint, Riposte, Strike |
| Martial Combat | Brawl, Sweep, Dodge, Acrobatics, Charge |
| Bash | Charge, Bash, Strike |
| Sure Strike | Feint, Riposte, Strike |
| Engage & Withdraw | Dodge, Lunge, Acrobatics, Charge, Riposte |
| Defend | Disarm, Sweep, Acrobatics |
| Slash | Slash, Cleave, Strike |
| Parry | Parry, Riposte, Disarm |
| Opportunity Throw | Throw, Initiative, Feint |
| Calculated Attack | Initiative, Slash, Strike, Feint, Riposte |
| Strike | Strike, Initiative, Bash, Cleave, Charge |

---

## Weapon flags now wired (flail_bypass, charge_attack, mc_compatible)

These three weapon tags used to be documented but ignored by combat. They now work.

**flail_bypass** (all Flails, Ball & Chain): a flail wraps around a block. Against one, the defender loses the shield's flat bonus (+5, or +10 for shield-bonus races), the Defend-style shield bonus and the off-hand shield skill bonus. Every parry also takes `FLAIL_PARRY_PENALTY` (-3). Dodging is unaffected. Result: a Flail against Long Sword + Target Shield goes from about 33% to about 52% wins; against an unshielded Long Sword, from about 48% to about 54%.

**charge_attack** (Short/Boar/Long Spear, Pole Axe, Halberd, Trident, Javelin): two effects.
- The existing "spear drives through a parry" penalty (-3 parry per Charge level) is now keyed to this flag instead of the weapon category, so Pole Axe and Halberd get it too.
- New: the first swing of the fight is a running charge, worth +8 attack plus +2 per Charge level (`SPEAR_CHARGE_OPENER_BASE`, `SPEAR_CHARGE_OPENER_PER_LEVEL`). It fires once per fight, never on a thrown weapon, and has its own narrative line. Measured on its own it adds about 1.5 to 3 points of win rate.

**mc_compatible** (Stiletto, Knife, Dagger, Quarterstaff, Great Staff, Cestus, Net, Open Hand): Martial Combat now works with these weapons, not only bare hands. While the warrior is using the Martial Combat style they get the style's +1 accuracy, the racial Martial Combat accuracy/parry/extra-attack bonuses, Brawl, and the martial Sweep chance (4% per level). Those bonuses scale off the weapon's own skill. In any other style, or with a non-tagged weapon, nothing changes. Lizardfolk natural-weapon damage, claws, and the unarmed Charge bonus still require Open Hand.

Verification: roll-level live-vs-debug parity is 0 mismatches over 1,260 new combinations (flail/spear defense, MC and charge attack); 600-fight random smoke test has 0 crashes.

Balance note: armed Martial Combat with Brawl 5 and Sweep 5 beats an unskilled mirror opponent about 72-77% of the time (about 93% for Halflings), about the same payoff as unarmed Brawl. Long Spear is already strong at high Charge (about 83% against a Long Sword at Charge 5, before the opener), which predates this change.

**Follow-up: spear parry penalty reduced.** `CHARGE_PARRY_PEN_PER_LEVEL` went from 3 to 1. At 3 per level, a Charge 5 Long Spear beat a Parry 7 / Brigandine pure-Parry fighter 78% of the time. At 1 per level it wins 62% (Wall of Steel 18%, Counterstrike 31%, Engage & Withdraw 51%, Decoy 46%). Pure Parry results at 3/2/1/0 per level: 78/72/62/51%.

## Net entangle

The Net's description promised entangle attacks, but `_check_entangle` only handled the Bola and Heavy Whip. A landed Net hit now entangles the target's legs and drops them (same fall as the whip): 5% + 2% per Net level (`NET_ENTANGLE_BASE`, `NET_ENTANGLE_PER_LEVEL`), so 15% at level 5 and 23% at level 9. Net 5 against a Long Sword 5 goes from about 58% to about 64% wins. Higher first values (20% + 3%/level) pushed it to 74%, which was too strong.

## Weapon note audit follow-ups

- **Heavy Whip entangle now scales with Heavy Whip skill:** 30% + 4% per level (`HEAVY_WHIP_ENTANGLE_BASE`, `HEAVY_WHIP_ENTANGLE_PER_LEVEL`), so 50% at level 5 (the old flat rate) and 66% at level 9.
- **Swordbreaker disarm bonus (+10) is now conditional.** It only applies when the target's weapon is a one-handed Sword/Knife-family blade under 5.0 lbs (`SWORDBREAKER_MAX_WEIGHT`). Bastard Sword (4.8 lbs but two-handed) and Great Sword are excluded, as are axes, blunt weapons, spears and unarmed targets. Against those the fighter still gets the base Disarm chance, Disarm skill and any other weapon's bonus (for example an Epee primary).
- Left as is by decision: weapon attack-rate wording (combat uses a fixed 10 actions per minute), Flail "size not STR", Great Pick vs light armor, Battle Flail Half-Elf extra attack. Some of those notes date from the original version.
