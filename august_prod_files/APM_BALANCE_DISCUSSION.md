# APM Balance Discussion — Summary & Next Steps

Written to hand off this conversation to a different computer. Covers the full
arc: the original bug, every design considered, why each was set aside, and a
concrete spec for the next thing to prototype (flat 10 APM / minute, split by
the existing initiative roll).

**Nothing in `combat.py` has been changed as a result of this discussion.**
The only file actually modified is `apm_calculator.html`, which now has four
experimental modes bolted on for side-by-side comparison (all opt-in via a
dropdown; the default "Today's Formula" mode is untouched and still mirrors
the real game exactly). Full details in "What's already built" below.

---

## 1. The original bug

Reported: an Elf with 15 STR / 15 DEX / 15 INT, Wall of Steel style, using
Martial Combat-adjacent gear, showed **identical APM whether wielding a
Dagger or a Scimitar** — despite each weapon having a distinct `apm` rating
in `weapons.py` (Dagger=6, Scimitar=5, War Hammer=4, Great Sword=3.5, etc.,
range 3–7 across all 48 weapons).

**Root cause**: `weapon.apm` is defined on every weapon and is real,
documented data ("Attacks per minute for this weapon (3-7)" — `weapons.py`
line ~165), but it is **never read by the real combat formula**,
`_calc_apm_with_fraction()` in `combat.py` (currently starting at line
**2345**). That formula starts every warrior from a flat `base = 3.0`
regardless of weapon, and the only weapon-derived input anywhere in it is
`weapon.weight` (used for the under-strength penalty check) and
`weapon.two_hand` — never `weapon.apm`. Confirmed by grepping the whole
codebase: only two other files reference `weapon.apm` at all
(`tools/weapon_balance_analysis.py`, display-only; `warrior_strategy_optimizer.py`,
an unrelated scoring heuristic), and neither feeds it into actual combat.

So: **the calculator (`apm_calculator.html`) was accurately mirroring the
real game.** The bug is in the real game's formula never using data that
exists and is clearly meant to matter.

---

## 2. A second, pre-existing problem surfaced along the way

While investigating, we found `_calc_apm_with_fraction()` already has a hard
ceiling: `base = max(1.0, min(10.0, base))` (line **2452**, and mirrored at
line ~503 in the calculator's `calculateApm()`). This ceiling is *not new* —
it exists today, with zero weapon-speed fix applied.

The problem: well-built warriors already hit this 10.0 ceiling today. A
Human at Wall of Steel / activity 8 / weapon skill 9 with modest DEX/INT
already computes to a **guaranteed 10 APM, 0% chance of more** — the formula
computes higher than 10 internally and just discards everything above it. At
a theoretical max build (DEX 25, INT 25, skill 9, Wall of Steel, activity
10), the *uncapped* internal value was measured at **14.55** — meaning
**4.55 points of raw stat/skill/style investment are silently thrown away**
by the clamp, and two very differently-built "maxed" warriors become
indistinguishable at a flat, guaranteed 10 APM.

This matters for weapon-speed fixes specifically: any change that increases
APM for fast weapons pushes them into this pre-existing ceiling *sooner*
(at lower skill), which is what triggered the "9-10 APM in unskilled hands"
concern.

The user's framing for why 10 is the right ceiling to *keep* (not remove):
D&D-style reasoning — a combat round ≈ 6 seconds of real time, so 10 rounds
naturally fills a minute. The conclusion from that: **10 stays as the
absolute ceiling**, but the *path* to reaching it should reward skill more
smoothly than a hard wall that flattens everyone once they're "good enough."

---

## 3. Options explored, roughly in the order discussed

### Option 1 — Small additive weapon-speed offset
`base += (weapon.apm - 5) * scale` (5 = "neutral," e.g. Scimitar-like).
Added on top of the existing flat-3.0-start formula, everything else
unchanged. Contained, predictable, easy to tune the `scale` constant later.
**Not implemented in combat.py** — modeled by hand only.

### Option 2 — Weapon's own apm sets the starting base
`base = weapon.apm` instead of `base = 3.0`. Bigger structural change:
every *multiplicative* penalty in the formula (armor weight, heavy armor,
under-strength weight, Lizardfolk armor) now compounds against a different
starting point per weapon, so heavy weapons get hit harder by those
penalties than they do today, on top of their own lower base. Modeled with
real numbers across 4 real player warriors (see section 5) — found this
punishes untrained heavy-weapon users much more than Option 1 does, because
the "heavy weapon skill bonus" that's meant to compensate only kicks in once
skill > 0.

### Reworked activity formula
Original: `base += activity * 0.25` (activity range is **0–9**, clamped in
`warrior.py` line 425 — not 1–10 as initially assumed early in the
conversation). Every point is a pure bonus; activity 5 (the default) already
contributes +1.25.

Proposed: `base += (activity - 5) * 0.25` — recenters so activity 5 is
neutral (0 contribution), activity 0–4 becomes a genuine penalty, 6–9 a
bonus. Same total spread (2.25 APM end to end) as before, just re-centered
around "5 = normal" instead of "5 = already ahead." This uniformly lowers
most builds' APM by about 1 point at the default activity level, which
incidentally gives back some of the headroom the 10-cap problem was eating.

**Combining Option 2 (weapon-as-base) + this activity rework was tested and
rejected**: a Dagger-wielding Elf at default activity/stats hit the 10 APM
cap at **weapon skill 0**, before any training at all — worse than the
original cap problem, because the two changes compound instead of offsetting
(higher base + still-net-positive-at-default-activity stacks upward for fast
weapons specifically).

### Dead-Zone Design (the version that stuck, and got built into the calculator)
The most-refined idea. Two core principles:
1. **Weapon's own `apm` sets the starting base** (same mechanism as Option
   2), but paired with...
2. **Stats have a "dead zone"** — a normal/expected range with *no* bonus
   and *no* penalty. Only stat values *outside* that range contribute
   anything, and only proportionally to how far outside they are.

Specific rules landed on:
- **STR**: dead zone = `[weapon's min STR requirement, min STR + 5]`. Above
  that, `+RATE` per point. *Below* the weapon's min STR, the dead-zone system
  does nothing — the **existing** under-strength weight-penalty mechanism
  (already in the real formula, untouched) handles that case exactly as it
  does today, to avoid double-penalizing.
- **DEX / INT**: fixed dead zone `[9, 14]` (not weapon-dependent, since
  there's no per-weapon DEX/INT requirement in the game). Below 9: penalty.
  Above 14: bonus. Both sides use the same rate.
- **Activity**: same recentered-at-5 formula as above.

Rate constants, after two rounds of tuning at the user's request:
- `STR_DEAD_ZONE_RATE` — started at 0.10, **changed to 0.05** (user: "this
  change did not move the needle very much at all" after the DEX/INT cut
  alone, so STR was cut too, matching).
- `DEX_INT_DEAD_ZONE_RATE` — started at 0.10, **changed to 0.05** (first
  rate cut of the two).
- `STR_DEAD_ZONE_WIDTH = 5` (points above min-STR before bonus starts).
- `DEX_INT_DEAD_ZONE_LO = 9`, `DEX_INT_DEAD_ZONE_HI = 14`.
- `ACTIVITY_MIDPOINT = 5`, `ACTIVITY_RATE = 0.25`.

This was tested against 4 of the user's real warrior builds (exact stats in
section 5) with reasonable, non-extreme results — nothing hit the 10-cap
at skill 0, and weapon choice produced a real, felt difference in APM.

### "No DEX/INT" variant
User's question: what if DEX/INT contributed *nothing* to APM at all, and
were instead written into a future accuracy/to-hit formula (not built —
noted as "we can work off that later")? Modeled as a toggle
(`includeDexInt` flag) on the same Dead-Zone function. Finding: **barely
moves the number** — even at extreme DEX 25 / INT 3, the difference vs.
including them (at the already-halved 0.05 rate) was only ~0.1–0.25 APM.
Confirms DEX/INT were already a minor lever in this design; removing them
outright costs little.

### "No weapon speed" variant
User's question: what if weapon `apm` were scrapped entirely, and every
weapon started from the same flat baseline, with weapon choice mattering
*only* through the STR dead-zone / under-strength mechanism (can the
warrior wield it effectively)? Modeled as a second toggle (`useWeaponApm`
flag, baseline = 5.0, the midpoint of the 3–7 weapon range). Finding:
**this re-collapses the original bug.** Dagger vs. Great Sword (each
wielded by a warrior who competently meets that weapon's own STR
requirement) went from a ~2.65 APM gap (weapon speed on) down to ~0.15 APM
gap (weapon speed off) — nearly back to indistinguishable, which is very
close to the exact problem that started this whole conversation.

**Conclusion on Dead-Zone Design overall**: coherent, tunable, doesn't
reintroduce the original bug, doesn't cause the "trained warrior maxes out
the cap at skill 0" failure the Option-2-plus-activity combo did. This is
the version the user wants to carry to a test machine and try in real
gameplay via `simulation_tool.py` — **not yet done**, was the natural next
step when the conversation moved to the newest idea instead (section 6).

---

## 4. A structural concern raised mid-discussion: counterstrikes

Independent of which APM formula wins, the user asked whether counterstrikes
are counted in APM. Checked directly in `combat.py`:

- Counterstrikes trigger inside `_resolve_action()` (~line 3492 onward) when
  the **defender** successfully parries and a riposte/Counterstrike-mastery
  roll succeeds (~lines 3898–3934), calling `self._counterstrike(...)`
  (defined ~line 4572, current file state — line numbers have shifted
  slightly across edits this session).
- The main loop (~line 3103, `while rem_a > 0 or rem_b > 0`) decrements the
  **attacker's** `rem_a`/`rem_b` budget for the action that *got parried* —
  not the counterstriker's own budget.
- **Conclusion: counterstrikes are genuinely free bonus attacks**, not
  reflected anywhere in the APM number. A build with high riposte skill /
  Counterstrike style / Gnome counterstrike-mastery can land meaningfully
  more real attacks per minute than its calculated APM implies. Worth
  keeping in mind when judging whether any given APM ceiling "feels" too
  high or too low in actual fights — the true action count for
  counter-heavy builds is APM + counterstrikes, not APM alone.

This was not incorporated into any of the modeled formulas above — noted as
a gap in what the APM number represents, not something fixed.

---

## 5. Real warrior test cases used throughout

Two sets of real builds were used to sanity-check every formula variant
against the abstract math. Keep these for any future comparison — they're
useful because they're actual player warriors, not synthetic edge cases.

**Set A** (early testing, single-weapon comparisons):
- Elf, STR 15 / DEX 15 / INT 15, Wall of Steel, activity 6, weapon varied
  across Dagger / Scimitar / War Hammer / Great Sword.

**Set B** (four distinct real warriors, each with a weapon they're actually
suited/qualified for):
1. **Half-Orc** — STR 22, DEX 17, INT 12, Battle Flail (min STR 15, apm
   3.5, two-handed), Wall of Steel, activity 6.
2. **Elf** — STR 11, DEX 17, INT 17, Dagger (min STR 7, apm 6), Wall of
   Steel, activity 6.
3. **Gnome** — STR 15, DEX 9, INT 14, Mace (min STR 12, apm 5),
   Counterstrike, activity 3.
4. **Dwarf** — STR 15, DEX 10, INT 15, Bastard Sword (min STR 12, apm 4,
   two-handed), Counterstrike, activity 4.

Results across formula variants for these four (skill 0 throughout) are in
the earlier conversation; re-derivable from the calculator directly once the
constants above are dialed in.

---

## 6. THE CURRENT IDEA — flat 10 actions/minute, shared pool, split by initiative

This is the newest idea and the one the user wants to prototype and
thoroughly test on a separate machine before touching production code. It is
**structurally different** from everything above — not a formula tweak to
`_calc_apm_with_fraction()`, but a change to the turn-loop itself.

### The core idea, in the user's words
- No more per-warrior variable APM at all. **Every fight has exactly 10
  action slots per minute, period** — this *is* the existing 10.0 ceiling,
  just made the fixed total instead of a sometimes-reachable maximum.
- Those 10 slots are a **shared pool** between the two combatants, not two
  separate per-warrior budgets.
- **The existing initiative roll, completely unmodified**, decides who gets
  each of the 10 slots — same `_initiative_roll()` function, same DEX /
  skill / luck / race / style / activity inputs it already has today.
- STR stops affecting action *count* — it continues to gate minimum
  strength to wield a weapon (existing mechanism) and to affect damage
  (existing mechanism) — both already true today and don't need to change.
- DEX and INT stop affecting action *count* directly — instead they flow
  into the initiative roll (DEX already does, today) and into the
  attack/to-hit roll (INT does not currently feed the attack roll at all —
  worth checking whether that needs to change or whether INT was always
  meant to matter elsewhere, e.g. weapon skill training speed, which it
  already governs via `warrior.py`'s `base_training_chance()`).
- Winning an initiative slot is **not** a guaranteed hit — the existing
  separate attack-roll / defense-roll / damage mechanics still apply exactly
  as they do today, fully untouched. Getting the action ≠ landing the blow.

### Why this needs no new mechanic
The user correctly identified that `_initiative_roll()` (currently `def
_initiative_roll` at line **802** in `combat.py`) already runs **once per
action slot, not once per minute** — it's re-rolled fresh for every single
contested slot in today's loop. That means "10 shared slots, contested by
initiative each time" isn't a new roll type — it's the same roll, at the
same frequency, just deciding who claims from a shared pool of 10 instead of
who goes first within each fighter's own already-computed budget.

### What was verified with real numbers this session
Using the real `_initiative_roll()` function directly (not reimplemented —
called from Python against real `Warrior`/`Strategy`/`_CState` objects),
10,000-iteration Monte Carlo trials showed the actual win-split various
matchups would produce if this system were live:

| Matchup | Split |
|---|---|
| Extreme fast (Elf DEX20, Wall of Steel, act8) vs extreme slow (Dwarf DEX10, Parry, act3) | ~80/20 |
| Both average (DEX12, Strike, act5 both sides) | ~52/48 |
| Moderate DEX gap only (DEX16 vs DEX10, same style/activity) | ~59/41 |
| Same DEX, different style only (Wall of Steel vs Parry) | ~65/35 |
| Same DEX, different activity only (act8 vs act2) | ~62/38 |

Key finding: the user's guessed "7-3" split only actually occurs when a
build stacks *every* speed-favoring factor at once (high DEX **and** fast
style **and** high activity) against a build stacking every slow factor.
Single-factor gaps (just DEX, just style, just activity) produce gentler
splits in the high-50s/low-60s percent range. This means, under this
system, **tactical choices (style, activity) swing the initiative split
about as much as or more than raw DEX does** for isolated factors — worth
being aware of when judging whether the system feels "stat-driven" or
"choice-driven" in practice.

Also confirmed: this preserves real variance. 10 independent (or
60/40-weighted) rolls per minute absolutely can and will produce runs where
the "weaker" side wins 7 or 8 of them in a given minute — that's expected
statistical variance, not a bug, exactly as the user described.

### What would actually need to change in combat.py (not yet done)
The real turn loop is `Fight._run_minute()`, specifically the block starting
at line **3088** (current file state):

```python
apm_a = _calc_apm(self.warrior_a, strat_a, self.state_a)
apm_b = _calc_apm(self.warrior_b, strat_b, self.state_b)
...
rem_a = apm_a;  rem_b = apm_b
...
while rem_a > 0 or rem_b > 0:
    ...
    if rem_a > 0 and rem_b > 0:
        ia = _initiative_roll(...)
        ib = _initiative_roll(...)
        if ia >= ib:
            rem_a -= 1;  act_a += 1   # winner takes from THEIR OWN budget
        else:
            rem_b -= 1;  act_b += 1
    elif rem_a > 0:
        rem_a -= 1;  act_a += 1        # no contest once one side is out of actions
    else:
        rem_b -= 1;  act_b += 1
```

The conceptual change for the flat-10 shared-pool model: replace the two
independent counters (`rem_a`, `rem_b`, each pre-computed from
`_calc_apm`/`_calc_apm_with_fraction`) with **one shared counter**
initialized to 10, and have the initiative-roll winner draw from that shared
pool instead of their own. Roughly:

```python
rem_shared = 10   # instead of rem_a = apm_a; rem_b = apm_b
...
while rem_shared > 0:
    ...
    ia = _initiative_roll(self.warrior_a, strat_a, self.state_a)
    ib = _initiative_roll(self.warrior_b, strat_b, self.state_b)
    if ia >= ib:
        as_, ds_ = self.state_a, self.state_b
        ax, dx = strat_a, strat_b
        act_a += 1
    else:
        as_, ds_ = self.state_b, self.state_a
        ax, dx = strat_b, strat_a
        act_b += 1
    rem_shared -= 1
    ... (rest of the per-action resolution logic is unchanged)
```

This is a **sketch, not a tested implementation** — it has not been written
into `combat.py`, only described. Things that would need real attention
before this is production-ready (none of these were worked out in this
conversation):

- `_calc_apm` / `_calc_apm_with_fraction` would become dead code for this
  purpose (still might be used elsewhere — check callers before deleting
  anything).
- The "fraction" / bonus-11th-action mechanic (`fraction` return value,
  representing a % chance of one extra action) doesn't obviously map onto a
  fixed-10 shared model — decide whether it's dropped entirely or
  repurposed.
- Debug logging (`self.debug_logger.log_minute_start(minute, ..., apm_a,
  apm_b, ...)`) references `apm_a`/`apm_b` directly — would need rework or
  removal of that field if those numbers cease to exist.
- Endurance/fatigue mechanics currently interact with `apm` indirectly
  (state.endurance affects `_calc_apm_with_fraction`'s output) — under a
  fixed 10-slot model, does low endurance instead reduce a fighter's
  initiative-roll odds for the rest of the minute? Not decided.
- Ground-knocked-down state currently halves APM
  (`_calc_apm_with_fraction`: `if state.is_on_ground: base *= 0.5`) and
  initiative (`_initiative_roll`: `if state.is_on_ground: return max(1, roll
  // 2)`) — the initiative-side penalty already exists and would carry over
  naturally; the APM-side halving would need an equivalent under the new
  model (e.g., a knocked-down fighter's initiative rolls get the existing
  penalty, which naturally reduces their slot share — may not need a
  separate mechanic at all).
- Should INT feed into the attack/to-hit roll now that it no longer affects
  action count? **Checked this session**: `_attack_roll()` (`combat.py` line
  864) does NOT use INT at all today — its own docstring confirms the full
  input list: "d100 + DEX + weapon_skill*5 + luck + style_mod + feint +
  lunge bonuses + favorite_weapon bonus". INT's only real combat-relevant
  role currently is governing skill-training speed
  (`warrior.py`'s `base_training_chance()`), not accuracy. If INT is meant
  to matter in combat once it's pulled out of the APM formula, adding it to
  `_attack_roll()` (or a new accuracy term) is a deliberate design decision
  to make, not something already partially wired in.

### Recommended next steps on the new machine
1. Read `_attack_roll()` (`combat.py` line **864**) and `_defense_roll()`
   (line **953**) to confirm exactly what currently feeds the to-hit
   mechanic, before deciding whether INT needs to be added there.
2. Prototype the shared-pool loop change in a **branch or copy** of
   `combat.py`, not directly on the working file, since this touches the
   core fight loop.
3. Run it through `simulation_tool.py` (already has batch-fight
   infrastructure) across a range of build types — fast/light,
   slow/heavy, average — and look at real aggregate outcomes: average
   fight length, win rates by build archetype, whether fights still end
   in reasonable timeframes.
4. Compare against the same builds run through today's formula, to make
   sure this doesn't unintentionally make fights dramatically longer or
   shorter on average.
5. Only after that — consider whether to also fold in the Dead-Zone Design
   weapon/STR ideas from section 3 (they're not mutually exclusive — the
   dead zones could still apply to accuracy/damage even in a flat-10-APM
   world, since STR/DEX/INT still need to matter for *something* beyond
   initiative).

---

## What's already built (in `apm_calculator.html`, this session)

Safe to reference or discard — none of it is live in `combat.py`. The
calculator now has a **Formula → Mode** dropdown with four options:

1. **Today's Formula (real game)** — unchanged, still an exact port of
   `_calc_apm_with_fraction()`.
2. **Dead-Zone Design (experimental)** — the version described in section 3.
   Tunable constants near the top of the `<script>` block:
   `STR_DEAD_ZONE_RATE` (0.05), `STR_DEAD_ZONE_WIDTH` (5),
   `DEX_INT_DEAD_ZONE_RATE` (0.05), `DEX_INT_DEAD_ZONE_LO/HI` (9/14),
   `ACTIVITY_MIDPOINT` (5), `ACTIVITY_RATE` (0.25).
3. **Dead-Zone, no DEX/INT (experimental)** — same as #2 but DEX/INT
   contribute nothing to APM.
4. **Dead-Zone, no weapon speed (experimental)** — same as #2 but every
   weapon starts from a flat `NO_WEAPON_APM_BASELINE` (5.0) instead of its
   own `apm` rating.

All 48 weapons' real `apm` values were added to the calculator's `WEAPONS`
table (previously missing entirely) and verified byte-for-byte against
`weapons.py` via a Python cross-check script — zero mismatches. A
`minStrForWeight()` JS helper was added, ported from `weapons.py`'s
`min_str_for_weight()`.

None of this is relevant to the flat-10-APM idea in section 6 — that idea
doesn't fit the calculator's single-warrior-in-isolation shape at all, since
initiative splits are inherently a two-warrior comparison. It would need its
own tool (or direct testing via `simulation_tool.py`) rather than a mode
toggle here.
