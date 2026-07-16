# Release Notes: July 15, 2026

**Version:** 3.1.0
**Release Date:** July 15, 2026
**Build Status:** ✅ Complete and Ready for Deployment

---

## 📋 Overview

This release adds **warrior retirement** as a standalone feature (mirroring death, but voluntary), a new **Shady Pines** client tab for warriors who left the roster without dying (retirees *and* monster-ascended warriors), and fixes two pre-existing newsletter bugs uncovered while testing the new feature. All changes are backward compatible with existing team files and saves.

---

## 🎯 Major Features & Improvements

### 1. Warrior Retirement

**Context:** Warriors with 50+ fights (`can_retire`) can already flag `want_retire`. Previously this flag had no reliable server-side handling — the design now **exactly mirrors death**: a retiring warrior fights their final turn as normal, then gets flagged `is_retired = True` on the same warrior object. Nothing is auto-archived or auto-replaced server-side — the manager builds the replacement manually via the existing Replacement tab, exactly as for a death.

**Changes:**
- **`warrior.py`** (line 596-597) — added `is_retired: bool` field, wired into `to_dict()`/`from_dict()`, and reset in `revert_to_initial()`
- **`team.py`**
  - `retire_warrior()` (line 312) — rewritten to mirror `kill_warrior()`: just flags the warrior and returns `bool` (previously auto-generated an AI replacement and returned `Optional[Warrior]` — that approach silently broke because the client's sync/merge logic assumes replacements are always manager-built and uploaded, never invented server-side)
  - `active_warriors` (line 138) — now excludes `is_retired` warriors from the next turn's matchmaking pool, same as `is_dead`
- **`matchmaking.py`**
  - Deleted the old "STEP 1c: RETIREMENTS" block from `build_fight_card()` that pulled a retiring warrior out of the fight card *before* they fought — this was the original bug ("warrior didn't fight")
  - `run_turn()` (line 1662) — collects retirements from `archived_warriors` for its own local newsletter call (simulation-tooling path only)
- **`league_server.py`**
  - New turn-scoped `retirements_this_turn` list (line 873)
  - Post-combat retirement processing block (line 1107), inserted between the monster-ascension block and blood-challenge resolution — checks both `fight.player_warrior` and `fight.opponent`, skips a warrior who died in the same fight (`and not slain`/`and not opp_slain`, death takes precedence), rejects retirement if `can_retire` is false
  - Retirements wired into `generate_newsletter(...)` alongside the existing `bully_events` parameter
  - Auto-carry-next-turn eligibility now also excludes teams with a warrior awaiting retirement-replacement
  - Scouting/challenge target list now excludes retired warriors (slot is just waiting on a replacement)
  - Admin API payloads include `is_retired` for parity with `is_dead`
- **`newsletter.py`** — new `_retired_section()` (line 640) renders a "RETIRED THIS TURN" table; `generate_newsletter()` takes `retirements=None`
- **`save.py`** — full game-reset routine also resets `is_retired`, mirroring `is_dead`

---

### 2. "Shady Pines" Tab (Client)

**Context:** Dead and retired/ascended warriors were previously lumped together in a single "The Crypts" tab. Retired warriors — and, after user feedback, warriors who **ascended to Monsterdom** — now get a separate tab, since neither of them actually died.

**Changes (`bloodspire_client.html`):**
- Warrior detail panel gains a **Shady Pines** tab alongside Stats/Strats, Fight Options, Fights, Challenges, Replacement, and The Crypts
- **The Crypts** (`buildArchivesTab`) now filters out any archived warrior tagged `archived_retired`
- New **`buildRetiredTab(team)`** (line 4809) renders Shady Pines — same layout as The Crypts (stats, skills, injuries, fight history), but with a 🏆/👹 icon and send-off text that distinguishes retirement ("Retired after N fights — a hero's send-off") from ascension ("Ascended to Monsterdom after N fights — joined The Monsters")
- The `/api/warrior/replace` handler (line 1855) tags the outgoing warrior with `archived_retired = true` when either `is_retired` **or** `ascended_to_monster` is set, so both routes land on Shady Pines instead of The Crypts
- Replacement tab activation, header text, and the roll-up editor's header icon all branch on `is_retired` (🏆) vs. the death path (✝) — ascension already had its own dedicated 👹 message
- Tree sidebar shows a 🏆 RETIRED badge (separate from the existing 🏆 "retirement pending" flag icon, which represents the *pre-fight* `want_retire` request, and the existing 👹 ASCENDED badge)
- `mergeResults()` syncs `is_retired` from server to local the same way `is_dead`/`killed_by` already are (gated on the warrior having fresh `fight_history` this download)

**Follow-up fix — Monster Ascension routing:** initially only retirees were tagged `archived_retired`; ascended warriors still fell into The Crypts, which reads as "died" even though they were absorbed into The Monsters, not slain. Fixed by including `ascended_to_monster` in the same tagging check (`matchmaking.py` line ~1664 also guards its legacy "RETIRED THIS TURN" scan so an ascended warrior can't get mislabeled as a retiree there).

---

## 🐛 Bug Fixes

| Issue | Cause | Fix | Status |
|-------|-------|-----|--------|
| Retiring warrior skipped their final fight | `build_fight_card()` pulled `want_retire` warriors out of the card before matchmaking | Deleted the pre-fight retirement block; retirement now resolves post-combat | ✅ Fixed |
| Monster-ascension crash risk (`ModuleNotFoundError: No module named 'save'`) mentioned in migration doc | N/A in this codebase — `save.py` is already imported via the correct flat path (`from save import save_monster_team`) | No change needed; confirmed not reproducible here | ✅ N/A |
| Ascended warriors showed up in The Crypts as if they'd died | Client only tagged `is_retired` warriors as `archived_retired`, not `ascended_to_monster` | Both flags now route to Shady Pines; distinct icon/text per reason | ✅ Fixed |
| "Top Managers This Turn" / "Top Managers Career" tables rendered with headers but zero rows | `_should_hide_manager()` scanned `manager_records.json` for a consecutive-miss streak; a pre-existing 44-turn gap in that file (turns 23–65 never persisted) made every active manager look like they'd "missed 3+ consecutive turns" | Replaced with `_manager_recently_active()`, which checks each manager's own teams' `last_turn_ran` directly — the same recency source `_team_standings`/`_warrior_tiers` already use, so it can't be thrown off by gaps in the separate ledger file | ✅ Fixed |

---

## 📊 Affected Files

### Python Backend
- ✅ `warrior.py` — `is_retired` field, serialization, reset on revert
- ✅ `team.py` — `retire_warrior()` rewrite, `active_warriors` exclusion
- ✅ `matchmaking.py` — removed pre-fight retirement block, `run_turn()` newsletter wiring, ascension-exclusion guard
- ✅ `league_server.py` — post-combat retirement processing, newsletter wiring, auto-carry/scouting exclusions, admin API parity
- ✅ `newsletter.py` — `_retired_section()`, `generate_newsletter()` signature, `_manager_recently_active()` replacing `_should_hide_manager()`
- ✅ `save.py` — full-reset routine includes `is_retired`

### Client-Side
- ✅ `bloodspire_client.html` — Shady Pines tab, Crypts filter, replacement-tab/tree-badge/`mergeResults` updates, ascension routing

---

## 🔄 Backward Compatibility

✅ **Fully backward compatible**

- `is_retired` defaults safely via `.get("is_retired", False)` on load — older save files without the field behave as "not retired"
- No database/save-file migration required
- Existing death/replacement flow is unaffected — regression-tested by inspection (death still archives to The Crypts, not Shady Pines)

---

## 🚀 Deployment Instructions

### Step 1: Deploy Server Updates
1. Update `warrior.py`, `team.py`, `matchmaking.py`, `league_server.py`, `newsletter.py`, `save.py` on the server
2. **Restart the league server process** — it will not pick up any of these changes without a restart
3. Note: the "Top Managers" fix only affects newsletters generated *after* the restart — the already-written `turn_0066/newsletter.txt` (or whichever turn was affected) keeps its empty tables; the very next turn processed will self-correct since `manager_records.json` gets a fresh, unbroken entry from that point on

### Step 2: Deploy Client Updates
1. Use the new build: `BloodspireArena-3.1.0 Setup.exe` (rebuilt via `npm run make`)
2. Fully quit any running instance before installing — Squirrel-based installs can silently leave an old instance running otherwise
3. Push `.nupkg` and `RELEASES` files to update server if using auto-update

### Step 3: Verification
- [ ] Mark a 50+-fight warrior to retire → run the turn → confirm they fought their final fight → confirm newsletter shows them under "RETIRED THIS TURN" → Replacement tab activates with the retirement message → after saving a replacement, the retiree appears in **Shady Pines**, not The Crypts
- [ ] Force (or wait for) a monster ascension → confirm the ascended warrior lands in **Shady Pines** with "Ascended to Monsterdom..." text, not The Crypts
- [ ] Confirm a normal warrior death still archives to **The Crypts** (regression check — highest-risk area since so much logic is shared with retirement)
- [ ] Confirm "Top Managers This Turn" and "Top Managers Career" show rows for active managers after a turn runs post-restart

---

## 📝 Known Limitations & Future Work

- The already-generated newsletter for the turn where "Top Managers" first broke won't be retroactively corrected (see Step 1 note above)
- `run_turn()`'s retirement-collection for the newsletter (simulation-tooling path in `matchmaking.py`) uses a simpler scan-based approach than the live server's turn-scoped collection in `league_server.py`; low-stakes since it isn't user-facing, but not fully consistent if anyone extends the simulation tooling further

---

**Release prepared:** July 15, 2026
**Ready for deployment:** ✅ Yes
**Breaking changes:** ❌ None
