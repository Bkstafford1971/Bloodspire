# Immortal & Retirement Arena System - Implementation Plan (REVISED)

**Date**: 2026-08-08 (Revised 2026-08-11)
**Scope**: Add The Elite Spire and The Veteran's Keep as completely separate arena instances with independent schedulers, admin tabs, and data files
**Architecture**: Three independent league instances sharing the same warrior/team database but operating on separate turn cycles

---

## EXECUTIVE SUMMARY

Create **three completely separate arena instances** that operate independently:

| Arena | Code | Instance Type | Death Mechanic | Tier System | Admin Tab | Scheduler | Data Files |
|-------|------|---|---|---|---|---|---|
| **The Agony Amphitheatre** | `"normal"` | Primary instance | Permanent death | Recruits → Champions | Normal | Normal Scheduler | Downloads, teams.json, standings.json |
| **The Elite Spire** | `"immortal"` | Separate instance | Auto-resurrection | Ascended → Godly | Elite Spire | Elite Spire Scheduler | Downloads, teams_elite.json, standings_elite.json |
| **The Veteran's Keep** | `"veteran"` | Separate instance | Auto-resurrection | Rookie → Timeless | Veteran | Veteran Scheduler | Downloads, teams_veteran.json, standings_veteran.json |

**Key Principle:** Each arena is a **completely independent league** that happens to share the same warrior pool. Warriors can exist in multiple arenas simultaneously, earning records and tier progression in each independently.

---

## ARCHITECTURE: THREE INDEPENDENT INSTANCES

### 1.1 Admin Panel Layout

```
┌─────────────────────────────────────────────────────────────┐
│ ADMIN CONTROL PANEL                                         │
├─────────────┬─────────────┬─────────────────────────────────┤
│ Normal ▼    │ Elite Spire▼ │ Veteran's Keep ▼               │
├─────────────┴─────────────┴─────────────────────────────────┤
│                                                             │
│ THE AGONY AMPHITHEATRE (NORMAL ARENA)                       │
│ ┌───────────────────────────────────────────────────────┐   │
│ │ Current Turn: 52                                      │   │
│ │ Status: Ready for turn execution                      │   │
│ │ Warriors Active: 47                                   │   │
│ │ Teams: 6                                              │   │
│ │                                                       │   │
│ │ [RUN TURN]  [LOAD RESULTS]  [CLEAR DATA]            │   │
│ │                                                       │   │
│ │ Recent Turn Results:                                  │   │
│ │ • Turn 51: 23 fights, 4 deaths                        │   │
│ │ • Turn 50: 22 fights, 2 deaths                        │   │
│ └───────────────────────────────────────────────────────┘   │
│                                                             │
│ [Admin Tools]                                               │
│ • Upload manager team file                                  │
│ • Download league standings                                 │
│ • View warrior records                                      │
│ • Manage promotions                                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Three separate tab sections:**
1. **Normal Arena Tab** - Agony Amphitheatre management
2. **Elite Spire Tab** - Immortal arena management  
3. **Veteran's Keep Tab** - Retirement arena management

Each tab has:
- Current turn display (independent counter per arena)
- Status indicator (ready/running/complete)
- Warrior count in that arena
- Team count with warriors in that arena
- [RUN TURN] button (runs ONLY that arena's turn)
- [LOAD RESULTS] button (downloads results for that arena)
- [CLEAR DATA] button (wipes that arena only)
- Recent turn results log
- Arena-specific admin tools

### 1.2 Independent Schedulers

**Three separate scheduler instances:**

```python
# league_server.py

# Normal Arena Scheduler (existing system)
normal_scheduler = AsyncIOScheduler()
normal_scheduler.add_job(run_normal_arena_turn, 'interval', hours=24, id='normal_turn')

# Elite Spire Scheduler (new)
elite_scheduler = AsyncIOScheduler()
elite_scheduler.add_job(run_elite_spire_turn, 'interval', hours=24, id='elite_turn')

# Veteran's Keep Scheduler (new)
veteran_scheduler = AsyncIOScheduler()
veteran_scheduler.add_job(run_veteran_keep_turn, 'interval', hours=24, id='veteran_turn')

# Start all three
normal_scheduler.start()
elite_scheduler.start()
veteran_scheduler.start()
```

**Each scheduler independently:**
- Tracks its own turn counter (normal_turn, elite_turn, veteran_turn)
- Runs at its own interval
- Manages its own queue of turn executions
- Can be paused/resumed independently
- Can be manually triggered from admin panel

**Scheduler Configuration:**
```json
{
  "arenas": {
    "normal": {
      "scheduler_enabled": true,
      "turn_interval_hours": 24,
      "current_turn": 52,
      "last_turn_executed": "2026-08-11 14:30:00",
      "next_scheduled_turn": "2026-08-12 14:30:00"
    },
    "elite": {
      "scheduler_enabled": true,
      "turn_interval_hours": 24,
      "current_turn": 8,
      "last_turn_executed": "2026-08-10 08:15:00",
      "next_scheduled_turn": "2026-08-11 08:15:00"
    },
    "veteran": {
      "scheduler_enabled": true,
      "turn_interval_hours": 24,
      "current_turn": 3,
      "last_turn_executed": "2026-08-09 12:00:00",
      "next_scheduled_turn": "2026-08-10 12:00:00"
    }
  }
}
```

### 1.3 Separate Data File Structure

**File organization by arena:**

```
saves/
├── normal/                          # The Agony Amphitheatre
│   ├── teams.json                   # Normal arena teams (separate from elite/veteran)
│   ├── standings.json               # Normal arena leaderboard
│   ├── turn_52/
│   │   ├── result_team1_turn_52.json
│   │   ├── result_team2_turn_52.json
│   │   ├── newsletter_turn_52.txt
│   │   └── arena_stats_turn_52.html
│   ├── managers.json                # Managers with warriors in normal arena
│   └── league_config_normal.json
│
├── elite/                           # The Elite Spire
│   ├── teams_elite.json             # Elite spire teams (SEPARATE from normal)
│   ├── standings_elite.json         # Elite spire leaderboard (SEPARATE)
│   ├── turn_08/
│   │   ├── result_team1_turn_08.json
│   │   ├── result_team2_turn_08.json
│   │   ├── newsletter_turn_08.txt
│   │   └── arena_stats_turn_08.html
│   ├── managers_elite.json          # Managers with warriors in elite arena
│   └── league_config_elite.json
│
└── veteran/                         # The Veteran's Keep
    ├── teams_veteran.json           # Veteran arena teams (SEPARATE)
    ├── standings_veteran.json       # Veteran arena leaderboard (SEPARATE)
    ├── turn_03/
    │   ├── result_team1_turn_03.json
    │   ├── result_team2_turn_03.json
    │   ├── newsletter_turn_03.txt
    │   └── arena_stats_turn_03.html
    ├── managers_veteran.json        # Managers with warriors in veteran arena
    └── league_config_veteran.json
```

**Key Differences:**
- **teams.json** splits into `teams.json` (normal), `teams_elite.json` (elite), `teams_veteran.json` (veteran)
- **standings.json** splits into three separate files per arena
- **Turn result files** stored in separate directories (turn_52 for normal, turn_08 for elite, turn_03 for veteran)
- **Newsletter** generated separately for each arena
- **Manager records** track which managers have warriors in which arenas
- **League config** is separate per arena (allows independent settings)

### 1.4 Warrior & Team Management Across Arenas

**Warriors move between arenas (one-way progression):**

```python
# shared_data/warriors.json (ONE master file for all warriors)
{
  "warrior_id_1": {
    "name": "Bloodfang",
    "team_id": "at_sea",
    "team_name": "At Sea",
    
    # Current arena (single value, not array)
    "current_arena": "elite",  # Moved here from normal
    
    # Stats (carry forward unchanged)
    "str": 18, "dex": 16, "con": 15,
    "skills": {...},
    "equipment": {...},
    
    # Single continuous record (never resets, tracks across arenas)
    "record": {
      "wins": 50,           # Started: 42 in normal, +8 in elite
      "losses": 20,         # Started: 18 in normal, +2 in elite
      "kills": 18,          # Started: 15 in normal, +3 in elite
      "recognition": 45,    # Current elite recognition (reset on promotion)
      "tier": "Ascended"    # Current elite tier
    },
    
    # Promotion tracking
    "promoted_at_turn": 1,  # Elite turn 1 (or normal turn 51 if tracking both)
    "promoted_arena": "elite",
    
    # Status (single, for current arena)
    "is_dead": false,
    "injuries": {...},      # Injuries carry forward, no new ones in elite
    
    # Last fight info
    "last_fight": {
      "arena": "elite",
      "turn": 8,
      "opponent": "...",
      "result": "loss"
    }
  }
}
```

**Team Structure:**

```python
# saves/normal/teams.json (Normal arena only)
[
  {
    "team_id": "at_sea",
    "team_name": "At Sea",
    "manager_id": "manager1",
    "manager_name": "John Doe",
    
    # Warriors CURRENTLY in normal arena
    "warriors": ["warrior_id_2", "warrior_id_3", "warrior_id_5", ...],  # Bloodfang removed (promoted to elite)
    
    # Team record for normal arena
    "record": {"wins": 47, "losses": 18, "kills": 10},
    "standing_rank": 2
  }
]

# saves/elite/teams_elite.json (Elite Spire only)
[
  {
    "team_id": "at_sea",
    "team_name": "At Sea",
    "manager_id": "manager1",
    
    # Warriors CURRENTLY in elite arena (promoted from normal)
    "warriors": ["warrior_id_1"],  # Only Bloodfang (moved here from normal)
    
    # Team record for elite arena
    "record": {"wins": 8, "losses": 2, "kills": 3},
    "standing_rank": 1
  }
]
```

**Critical Points:**
- **Warriors move between arenas** (one-way: Normal → Elite or Normal → Veteran)
- **One continuous record per warrior** (W-L-K never resets, carries forward)
- **Recognition resets on promotion** (start tier 0 in new arena's tier system)
- **Stats and skills carry forward** (all attributes, proficiencies, equipment intact)
- **Injuries at promotion persist, no new ones** (if promoted with 3 permanent injuries, stays 3, can't gain new ones in elite)
- **Each team appears in ONLY ONE arena's team roster** (warrior removed from normal roster when promoted to elite)
- **Each arena maintains independent standings** (based on teams/warriors currently in that arena)

---

## 2. TURN EXECUTION: THREE INDEPENDENT PROCESSES

### 2.1 Normal Arena Turn (Existing Logic)

```python
async def run_normal_arena_turn():
    """Run one complete turn for The Agony Amphitheatre"""
    
    # Load all normal-arena warriors
    normal_warriors = load_warriors(arena="normal")
    normal_teams = load_teams(arena="normal")
    
    # Standard turn execution
    fight_card = build_fight_card(normal_warriors)
    for fight in fight_card:
        result = run_fight(fight)
        # Handle permanent death, record updates, standings
    
    # Save results
    save_turn_results(arena="normal", turn_number)
    generate_newsletter(arena="normal")
    update_standings(arena="normal")
    update_team_records(arena="normal")
    
    # Increment normal turn counter
    increment_turn(arena="normal")
```

### 2.2 Elite Spire Turn (New)

```python
async def run_elite_spire_turn():
    """Run one complete turn for The Elite Spire"""
    
    # Load all elite-arena warriors (arena_assignments contains "elite")
    elite_warriors = load_warriors(arena="elite")
    elite_teams = load_teams(arena="elite")
    
    # Turn execution (same as normal, but no permanent death)
    fight_card = build_fight_card(elite_warriors)
    for fight in fight_card:
        result = run_fight(fight, arena="elite")  # Resurrect on death
        # NO permanent death, auto-resurrect on HP <= 0
    
    # Save results (ELITE-specific files)
    save_turn_results(arena="elite", turn_number)
    generate_newsletter(arena="elite")
    update_standings(arena="elite")
    update_team_records(arena="elite")
    
    # Increment elite turn counter (separate from normal)
    increment_turn(arena="elite")
```

### 2.3 Veteran's Keep Turn (New)

```python
async def run_veteran_keep_turn():
    """Run one complete turn for The Veteran's Keep"""
    
    # Load all veteran-arena warriors
    veteran_warriors = load_warriors(arena="veteran")
    veteran_teams = load_teams(arena="veteran")
    
    # Same execution logic as elite
    fight_card = build_fight_card(veteran_warriors)
    for fight in fight_card:
        result = run_fight(fight, arena="veteran")  # Resurrect on death
    
    # Save results (VETERAN-specific files)
    save_turn_results(arena="veteran", turn_number)
    generate_newsletter(arena="veteran")
    update_standings(arena="veteran")
    update_team_records(arena="veteran")
    
    # Increment veteran turn counter
    increment_turn(arena="veteran")
```

### 2.4 Turn Counters (Independent Per Arena)

```python
# league_config.json
{
  "turn_trackers": {
    "normal": 52,      # The Agony Amphitheatre is on turn 52
    "elite": 8,        # The Elite Spire is on turn 8
    "veteran": 3       # The Veteran's Keep is on turn 3
  }
}
```

**Example Timeline:**

```
Turn 1 (Normal):    All three arenas start
Turn 1 (Elite):     (Not yet running)
Turn 1 (Veteran):   (Not yet running)

[Elite starts with warriors promoted from normal]

Turn 2 (Normal):    Agony Amphitheatre runs turn 2
Turn 1 (Elite):     Elite Spire runs its turn 1
Turn 1 (Veteran):   (Not yet running)

[Veteran starts with resurrected playtest warriors]

Turn 3 (Normal):    Agony Amphitheatre runs turn 3
Turn 2 (Elite):     Elite Spire runs turn 2
Turn 1 (Veteran):   Veteran's Keep runs turn 1

...continuing independently...

Turn 52 (Normal):   47 warriors in normal arena
Turn 8 (Elite):     12 warriors in elite arena
Turn 3 (Veteran):   8 warriors in veteran arena
```

**Each arena moves at its own pace**, not synchronized.

---

## 3. WARRIOR PROMOTION FLOW

### 3.1 Normal → Elite Spire

**Eligibility Check (runs each normal turn):**
```python
def check_elite_promotion_eligibility():
    """Check all normal-arena warriors for elite promotion"""
    for warrior in load_warriors(arena="normal"):
        if warrior.records["normal"]["wins"] >= 22 and warrior.records["normal"]["win_rate"] >= 0.55:
            warrior.pending_promotion = "elite"
            log_promotion_event(warrior, "elite")
```

**Promotion Process (two-turn process for normal arena):**

*Normal Turn N (Eligibility):*
- Warrior becomes eligible
- `pending_promotion = "elite"` set
- Normal arena newsletter announces pending status

*Normal Turn N+1 (Final Mortal Fight):*
- Warrior fights in normal arena with "immortality shield" active
- If dies: Still promoted to elite (shield protects)
- If survives: Also promoted to elite
- `arena_assignments` updated to include "elite"
- Warrior added to elite arena fighter pool for next elite turn

**After Promotion:**
- Warrior's `current_arena` changes from "normal" to "elite"
- Warrior is REMOVED from normal arena's team roster
- Warrior is ADDED to elite arena's team roster
- One continuous record continues accumulating (no reset)
- Recognition resets to 0 for new arena's tier system
- Warrior fights ONLY in elite arena from now on (never returns to normal)

### 3.2 Normal → Veteran's Keep (Manager Choice)

**Manager retires warrior to veteran arena:**
- Same two-turn process as elite promotion
- Warrior fights one final "farewell bout" in normal arena
- Can die in farewell without stopping promotion (immortality shield)
- Promoted to veteran arena after farewell turn
- `arena_assignments` updated to include "veteran"
- Can continue fighting in veteran arena indefinitely

### 3.3 Playtest Resurrection → Elite Spire

**Admin resurrection panel (manual selection):**
- Admin filters dead warriors by win rate, fight count, manager
- Bulk selects warriors for elite resurrection
- Confirms resurrection
- Warriors added directly to elite arena (no pending process)
- `arena_assignments = ["elite"]`
- Elite turn counter doesn't reset (they enter existing elite arena)

---

## 4. ADMIN PANEL CONTROLS

### 4.1 Three Separate Admin Tabs

**Tab 1: Normal Arena Management**
```
THE AGONY AMPHITHEATRE (TURN 52)
┌─────────────────────────────────┐
│ Status: Ready                   │
│ Warriors: 47 / 50               │
│ Teams: 6                        │
│ Recent Deaths: 3 (turn 51)      │
│                                 │
│ [RUN TURN NOW]                  │
│ [LOAD TURN 52 RESULTS]          │
│ [VIEW STANDINGS]                │
│ [CLEAR ARENA]                   │
│ [MANAGE PROMOTIONS]             │
│ [RESURRECTION PANEL]            │
│                                 │
│ Turn History:                   │
│ Turn 51: 23 fights, 3 deaths    │
│ Turn 50: 21 fights, 2 deaths    │
└─────────────────────────────────┘
```

**Tab 2: Elite Spire Management**
```
THE ELITE SPIRE (TURN 8)
┌─────────────────────────────────┐
│ Status: Ready                   │
│ Warriors: 12 / 20               │
│ Teams: 4 (with elite warriors)  │
│ Recent Deaths: 0 (turn 7)       │
│                                 │
│ [RUN TURN NOW]                  │
│ [LOAD TURN 8 RESULTS]           │
│ [VIEW STANDINGS]                │
│ [CLEAR ARENA]                   │
│ [RESURRECTION PANEL]            │
│                                 │
│ Turn History:                   │
│ Turn 7: 6 fights, 0 deaths      │
│ Turn 6: 5 fights, 0 deaths      │
└─────────────────────────────────┘
```

**Tab 3: Veteran's Keep Management**
```
THE VETERAN'S KEEP (TURN 3)
┌─────────────────────────────────┐
│ Status: Ready                   │
│ Warriors: 8 / 15                │
│ Teams: 3 (with veteran warriors)│
│ Recent Deaths: 0 (turn 2)       │
│                                 │
│ [RUN TURN NOW]                  │
│ [LOAD TURN 3 RESULTS]           │
│ [VIEW STANDINGS]                │
│ [CLEAR ARENA]                   │
│ [RESURRECTION PANEL]            │
│                                 │
│ Turn History:                   │
│ Turn 2: 4 fights, 0 deaths      │
│ Turn 1: 5 fights, 0 deaths      │
└─────────────────────────────────┘
```

### 4.2 Admin Controls Per Tab

**[RUN TURN NOW] Button:**
- Manually trigger that arena's turn execution immediately
- Bypasses scheduler
- Shows progress indicator
- Updates turn counter when complete

**[LOAD RESULTS] Button:**
- Downloads all result files for that turn
- Includes result_*.json files, newsletter, arena_stats.html
- **Arena-specific files only** (normal arena results don't show elite data)

**[CLEAR ARENA] Button:**
- Confirmation dialog: "Clear all warriors and records from The Elite Spire?"
- Shows count: "12 warriors will be removed"
- Removes ALL warriors with that arena in arena_assignments
- Resets team records for that arena
- Resets turn counter for that arena
- Does NOT affect other arenas
- Logs admin action with timestamp and user

**[RESURRECTION PANEL] Button:**
- Opens resurrection panel for that arena
- Lists only dead warriors
- Can resurrect to ONLY that arena
- Adds arena to warrior's arena_assignments if not already there

**[MANAGE PROMOTIONS] Button (Normal Arena Only):**
- Shows pending promotions awaiting final mortal fight
- Shows warriors eligible for promotion
- Can trigger final mortal fight manually
- Can cancel pending promotion

**[VIEW STANDINGS] Button:**
- Shows leaderboard for ONLY that arena
- Shows team rankings
- Shows warrior rankings by tier/recognition

---

## 5. DATA FILE ORGANIZATION

### 5.1 Shared Files (One Instance for All)

```
shared_data/
├── warriors.json                # ALL warriors (shared pool)
├── managers.json                # ALL managers
└── checksums.json               # Checksum validation for shared data
```

### 5.2 Arena-Specific Files (Three Instances)

```
saves/normal/
├── teams.json                   # Normal arena teams only
├── standings.json               # Normal arena leaderboard
├── league_config_normal.json    # Normal arena settings
├── turn_52/
│   ├── result_team1_turn_52.json
│   ├── newsletter_turn_52.txt
│   └── arena_stats_turn_52.html
└── activity.jsonl               # Normal arena activity log

saves/elite/
├── teams_elite.json             # Elite spire teams only
├── standings_elite.json         # Elite spire leaderboard
├── league_config_elite.json     # Elite spire settings
├── turn_08/
│   ├── result_team1_turn_08.json
│   ├── newsletter_turn_08.txt
│   └── arena_stats_turn_08.html
└── activity_elite.jsonl         # Elite spire activity log

saves/veteran/
├── teams_veteran.json           # Veteran arena teams only
├── standings_veteran.json       # Veteran arena leaderboard
├── league_config_veteran.json   # Veteran arena settings
├── turn_03/
│   ├── result_team1_turn_03.json
│   ├── newsletter_turn_03.txt
│   └── arena_stats_turn_03.html
└── activity_veteran.jsonl       # Veteran arena activity log
```

### 5.3 Team File Upload/Download

**Managers upload team files for each arena separately:**

```
At Sea (Manager1) might upload:
├── At_Sea_normal.json           # Warriors for normal arena (45 warriors)
├── At_Sea_elite.json            # Warriors for elite arena (2 warriors: Bloodfang, HMS Hood)
└── At_Sea_veteran.json          # Warriors for veteran arena (0 warriors)
```

**Each arena's team JSON includes:**
```json
{
  "team_id": "at_sea",
  "team_name": "At Sea",
  "manager_id": "manager1",
  "warriors": [
    {
      "warrior_id": "warrior_1",
      "name": "Bloodfang",
      "current_record_arena": {"wins": 42, "losses": 18, "kills": 15},
      "current_tier": "Champion",
      "current_recognition": 78
    }
  ]
}
```

---

## 6. CRITICAL IMPLEMENTATION NOTES

### 6.1 Warrior Record Structure

**Each warrior has ONE continuous record (never resets):**
```python
# Bloodfang's record
warrior.record = {
    "wins": 50,              # 42 from normal + 8 from elite (never resets)
    "losses": 20,            # 18 from normal + 2 from elite (never resets)
    "kills": 18,             # 15 from normal + 3 from elite (never resets)
    "recognition": 45,       # Current arena's recognition (resets to 0 on promotion)
    "tier": "Ascended",      # Current arena's tier name
    "promoted_at_turn": 1    # When promoted to current arena (elite turn 1)
}

# Bloodfang's current arena
warrior.current_arena = "elite"  # Single value: "normal", "elite", or "veteran"
```

**Tier Systems by Arena:**

| Recognition | Regular Arena | Elite Spire | Veteran's Keep |
|-------------|---------------|-------------|---|
| 87-100 | ELITES | ADVANCED ELITES | VETERAN ELITES |
| 71-86 | EXPERTS | ADVANCED EXPERTS | VETERAN EXPERTS |
| 56-70 | VETERANS | ADVANCED VETERANS | VETERAN VETERANS |
| 41-55 | ADEPTS | ADVANCED ADEPTS | VETERAN ADEPTS |
| 26-40 | INITIATES | ADVANCED INITIATES | VETERAN INITIATES |
| 13-25 | ROOKIES | ADVANCED ROOKIES | VETERAN ROOKIES |
| 0-12 | RECRUITS | ADVANCED RECRUITS | VETERAN RECRUITS |
| Champion | CHAMPION | ADVANCED CHAMPION | VETERAN CHAMPION |

**Recognition and Tier System:**
- **On promotion:** Recognition resets to 0, tier resets to bottom of new arena's progression
- **On each fight:** Recognition gained/lost is specific to that arena's tier system
- **Overall record:** Continues accumulating across arenas, never resets

### 6.2 Team Record Structure (Arena-Specific, Independent Accumulation)

**Core Principle:** Team records are **per-arena** and **start fresh** when warriors are promoted. Individual warrior records are **continuous** and **never reset**.

**Individual Warrior Records (Continuous - Never Reset):**
```python
# Critical Mass record progression
Before promotion to Elite:     20-12-2
After 1st Elite win:           21-12-2  (record continues, doesn't reset)
After 2nd Elite loss:          21-13-2  (accumulates in new arena)
```

**Team Records (Arena-Specific, Start Fresh Per Arena):**
```python
# In saves/normal/teams.json
team.record = {
    "wins": 77,              # Accumulates ONLY from warriors currently in normal arena
    "losses": 78,            # (excludes promoted warriors like Critical Mass)
    "kills": 10,
    "standing": 2
}

# In saves/elite/teams_elite.json (SEPARATE FILE)
team.record = {
    "wins": 1,               # Starts at 0-0-0, accumulates from warriors currently in elite arena
    "losses": 0,             # (Critical Mass's pre-promotion 20-12-2 does NOT transfer)
    "kills": 0,
    "standing": 1
}
```

**Example: Critical Mass Promotion**

**Before Promotion (Turn 50):**
```
Vestian Renegades - Regular Arena Record: 77-78-10
- Critical Mass: 20-12-2 (individual, all-time)
- Other warriors: remaining record
```

**Turn 51 - Critical Mass Promoted to Elite:**
```
Critical Mass promoted to Elite Spire
- Moved from Regular roster to Elite roster
- Individual record CONTINUES: 20-12-2 (carries over)
```

**Turn 52 - Critical Mass Fights in Elite, Wins:**
```
Critical Mass Victory:
- Individual record: 20-12-2 → 21-12-2 ✓ (continuous)
- Vestian Renegades Regular Arena: 77-78-10 (unchanged - Critical Mass no longer there)
- Vestian Renegades Elite Arena: 0-0-0 → 1-0-0 ✓ (starts fresh, grows)
```

**Turn 53 - Other Vestian Warriors Fight in Regular Arena:**
```
Other Vestian warriors fight in Regular Arena (1 win, 1 loss):
- Individual records update (continuous)
- Vestian Renegades Regular Arena: 77-78-10 → 78-79-10 (accumulated from warriors still there)
- Vestian Renegades Elite Arena: 1-0-0 (unchanged - only Critical Mass fights here)
```

**How Team Records Work:**
1. **Initial State:** Team starts with all warriors in Regular Arena (saves/normal/teams.json)
2. **On Promotion:** Warrior removed from old arena roster, added to new arena roster
3. **Record Accumulation:** 
   - Regular Arena record continues from remaining warriors only
   - New Arena record starts fresh at 0-0-0
   - Promoted warrior's individual record continues (carries over)
4. **Per-Arena Independence:** Each arena has separate team roster, separate record, separate standings
5. **Promotion Example:**
   - Before: Team record 77-78-10 (all warriors in Regular)
   - After promotion: Regular stays 77-78-10 (minus promoted warrior's future fights), Elite starts 0-0-0

**Key Invariants:**
✅ Individual warrior records are **continuous** (never reset, accumulate across arenas)
✅ Team records are **per-arena** (separate records for Regular, Elite, Veteran)
✅ Team records are **fresh** (start at 0-0-0 per arena)
✅ Only warriors currently in an arena contribute to that arena's team record
✅ Promoted warriors stop contributing to old arena's team record immediately
✅ Team standings are per-arena (separate leaderboards)

### 6.3 Combat Engine Changes

**Death resolution per arena:**
```python
def check_death(warrior, arena):
    if arena == "normal":
        # Existing permanent death logic
        roll_death_check()
    elif arena in ["elite", "veteran"]:
        # Auto-resurrect on death (no permanent death)
        warrior.record["losses"] += 1
        warrior.hp = full_health
        resurrection_narrative()

# Injury accumulation per arena
def apply_permanent_injury(warrior, arena, location, severity):
    if arena == "normal":
        # Normal: injuries accumulate as normal
        apply_injury(warrior, location, severity)
    elif arena in ["elite", "veteran"]:
        # Elite/Veteran: NO new injuries accumulate
        # Injuries from before promotion are retained, but no new ones
        pass  # Do nothing, skip injury application
```

**Key Mechanics:**
1. **Normal Arena:** Permanent death possible, injuries accumulate normally
2. **Elite/Veteran Arenas:** No permanent death, auto-resurrect on HP ≤ 0
3. **Injury Retention:** Injuries at time of promotion are kept, but NO new injuries are added in elite/veteran

### 6.4 Matchmaking Per Arena

**Build separate fight cards per arena (warriors in that arena only):**
```python
def build_global_fight_card():
    normal_warriors = [w for w in all_warriors if w.current_arena == "normal"]
    elite_warriors = [w for w in all_warriors if w.current_arena == "elite"]
    veteran_warriors = [w for w in all_warriors if w.current_arena == "veteran"]
    
    normal_card = build_card(normal_warriors)
    elite_card = build_card(elite_warriors)
    veteran_card = build_card(veteran_warriors)
    
    return {
        "normal": normal_card,
        "elite": elite_card,
        "veteran": veteran_card
    }
```

**Note:** Warriors only appear in ONE arena's matchmaking at a time. Once promoted from normal to elite, they never fight in normal arena again.

---

## 7. SCHEDULER CONFIGURATION

### 7.1 Independent Scheduler Setup

**Architecture:**
Use the same Turn Schedule system currently in place, but configure it separately for each arena. Each arena gets its own independent scheduler instance using the existing scheduling mechanism.

**Three separate schedulers (using existing Turn Schedule system):**
- **Normal Arena Scheduler** (tracks normal_turn counter, uses existing system)
- **Elite Spire Scheduler** (tracks elite_turn counter, uses existing system)
- **Veteran's Keep Scheduler** (tracks veteran_turn counter, uses existing system)

### 7.2 Admin Panel Scheduler Controls

Each arena tab in the admin panel includes:
- Current turn number display
- Schedule status (enabled/disabled)
- Next scheduled run time
- [Run Now] button (manual trigger, bypasses schedule)
- [Edit Schedule] button (configure auto-run interval for this arena)
- [Enable/Disable] toggle (activate or pause this arena's scheduler)

### 7.3 How It Works

1. Each arena can be independently configured with its own auto-run schedule
2. Normal Arena might run every 24 hours at one time
3. Elite Spire might run every 24 hours at a different time
4. Veteran's Keep might run every 48 hours
5. Each scheduler tracks its own turn counter independently
6. Can manually trigger any arena's turn from admin panel at any time
7. Schedulers can be enabled/disabled independently
8. Each arena runs at its own pace (not synchronized with others)

### 7.4 Scheduler Configuration (per arena)

```json
{
  "arenas": {
    "normal": {
      "scheduler_enabled": true,
      "turn_interval_hours": 24,
      "current_turn": 52,
      "last_turn_executed": "2026-08-11 14:30:00",
      "next_scheduled_turn": "2026-08-12 14:30:00"
    },
    "elite": {
      "scheduler_enabled": true,
      "turn_interval_hours": 24,
      "current_turn": 8,
      "last_turn_executed": "2026-08-10 08:15:00",
      "next_scheduled_turn": "2026-08-11 08:15:00"
    },
    "veteran": {
      "scheduler_enabled": true,
      "turn_interval_hours": 24,
      "current_turn": 3,
      "last_turn_executed": "2026-08-09 12:00:00",
      "next_scheduled_turn": "2026-08-10 12:00:00"
    }
  }
}
```

### 7.5 Manual Turn Triggers

Admin endpoints for manual control:

```python
@app.post("/api/admin/run_turn")
async def run_turn_manual(arena: str):
    """Manually trigger a turn execution for a specific arena"""
    if arena == "normal":
        await run_normal_turn()
    elif arena == "elite":
        await run_elite_spire_turn()
    elif arena == "veteran":
        await run_veteran_keep_turn()
    return {"status": "complete", "arena": arena, "turn": current_turn[arena]}
```

### 7.6 Key Points

✅ Uses existing Turn Schedule system (replicated 3 times, one per arena)
✅ Each arena has independent turn counter
✅ Each arena can have different auto-run schedule
✅ Each arena can be manually triggered independently
✅ Each arena can be enabled/disabled independently
✅ Same scheduling mechanism, just applied separately to each arena

---

## 8. SUMMARY OF CHANGES FROM ORIGINAL PLAN

**Major Architectural Shifts:**

1. **Three Separate Instances** (not filtered subsets)
   - Each arena is completely independent
   - Each has its own turn counter
   - Each has its own scheduler
   - Each has its own data files

2. **Admin Panel Reorganization**
   - Three tabs instead of unified panel
   - Each tab controls ONLY that arena
   - Independent turn execution
   - Independent clear/reset functions

3. **Data File Structure**
   - `teams.json` → `teams.json`, `teams_elite.json`, `teams_veteran.json`
   - `standings.json` → Three separate files per arena
   - Results stored in separate directories by arena
   - Shared warrior pool in `shared_data/warriors.json`

4. **Warrior/Team Model**
   - Warriors can be in multiple arenas simultaneously
   - Records tracked per-arena (not combined)
   - Teams maintained separately per arena
   - Teams can have warriors in multiple arenas

5. **Turn Execution**
   - Three independent turn processes
   - No synchronization required
   - Each arena runs on its own schedule
   - Manual triggers available per arena

**What This Enables:**
- The Elite Spire can run at different cadence than normal arena
- Veteran's Keep can be paused while normal arena runs
- Complete data isolation per arena
- Granular admin control (clear only elite arena, etc.)
- Realistic "separate leagues" feel

---

## 8.5 FRONTEND UI CHANGES

### 8.5.1 Arena Tab Navigation

**Add left-side tab navigation to existing UI:**

```
┌──────────────────────────────────────────────────────┐
│ BLOODSPIRE LEAGUE MANAGER                            │
├─────────────┬──────────────────────────────────────┤
│ ARENAS      │  [Existing UI Layout - unchanged]   │
├─────────────┤                                      │
│             │  Shows only warriors/teams from      │
│ Regular     │  the selected arena                  │
│ (active)    │                                      │
│             │  Same display format:                │
│ Elite Spire │  • Team name                         │
│             │  • Warrior list                      │
│ Veteran     │  • Records & tiers                   │
│ Keep        │  • Action buttons                    │
│             │  • Team standing                     │
│             │                                      │
│             │  All filtered by current arena tab   │
└─────────────┴──────────────────────────────────────┘
```

### 8.5.1 Upload & Download (Arena-Specific)

**Action Menu Structure:**

```
Actions Menu
├── Regular Arena
│   ├── Upload (Regular Arena warriors)
│   └── Download (Regular Arena results) - 1 per turn limit
├── Elite Spire
│   ├── Upload (Elite Spire warriors)
│   └── Download (Elite Spire results) - Unlimited
└── Veteran's Keep
    ├── Upload (Veteran's Keep warriors)
    └── Download (Veteran's Keep results) - Unlimited
```

**Regular Arena Upload/Download (Existing Behavior):**
- Upload: Sends only warriors designated for Regular Arena
- Download: Gets Regular Arena turn results
- **Limitation:** 1 download per turn (prevents overwriting dead warrior slots)

**Elite Spire Upload/Download (New):**
- Upload: Sends only warriors designated for Elite Spire
- Download: Gets Elite Spire turn results
- **Limitation:** None (no permanent death, safe to re-download)

**Veteran's Keep Upload/Download (New):**
- Upload: Sends only warriors designated for Veteran's Keep
- Download: Gets Veteran's Keep turn results
- **Limitation:** None (no permanent death, safe to re-download)

**Key Benefits:**
✅ Managers control each arena independently
✅ Upload only warriors relevant to that arena
✅ Download only the results they need
✅ Elite/Veteran can be re-downloaded without risk
✅ Regular Arena safety mechanism preserved

### 8.5.2 Tab Behavior

**Regular Arena Tab:**
- Shows teams with warriors in regular arena only
- Displays warrior records (continuous total)
- Shows tier progression for regular arena
- Team record for regular arena only
- Action: "Promote Warrior" button (to elite/veteran)

**Elite Spire Tab:**
- Shows teams with warriors in elite arena only
- Displays warrior records (continuous total)
- Shows tier progression for elite arena (Ascended → Godly)
- Team record for elite arena only
- Action: "Retire to Veteran" button (optional)

**Veteran's Keep Tab:**
- Shows teams with warriors in veteran arena only
- Displays warrior records (continuous total)
- Shows tier progression for veteran arena (Rookie → Timeless)
- Team record for veteran arena only
- Action: None (warriors stay here)

### 8.5.3 Arena-Specific Tabs

**Regular Arena (Normal) - All tabs available:**
- Stats/Strats ✅
- Fight Options ✅
- Fights ✅
- Challenges ✅
- Replacement ✅
- The Crypts ✅
- Shady Pines ✅

**Elite Spire - Limited tabs:**
- Stats/Strats ✅
- Fights ✅
- Challenges ✅
- Fight Options ❌ (N/A for elite arena)
- Replacement ❌ (N/A for elite arena)
- The Crypts ❌ (N/A - no permanent death in elite)
- Shady Pines ❌ (N/A for elite arena)

**Veteran's Keep - Limited tabs:**
- Stats/Strats ✅
- Fights ✅
- Challenges ✅
- Fight Options ❌ (N/A for veteran arena)
- Replacement ❌ (N/A for veteran arena)
- The Crypts ❌ (N/A - no permanent death in veteran)
- Shady Pines ❌ (N/A for veteran arena)

**Implementation:**
```javascript
// Show/hide tabs based on arena
function updateAvailableTabs(arena) {
  if (arena === "normal") {
    showTabs(["Stats/Strats", "Fight Options", "Fights", "Challenges", "Replacement", "The Crypts", "Shady Pines"]);
  } else if (arena === "elite" || arena === "veteran") {
    showTabs(["Stats/Strats", "Fights", "Challenges"]);
    hideTabs(["Fight Options", "Replacement", "The Crypts", "Shady Pines"]);
  }
}
```

### 8.5.4 Implementation Notes

**No UI layout changes needed:**
- Keep existing roster display
- Keep existing team info display
- Keep existing standings/league tabs
- Changes: 
  1. Add tab selector for arenas
  2. Filter data by `current_arena` field
  3. Show/hide warrior-specific tabs based on arena

**Tab State:**
- Default tab on load: "Regular"
- Remember selected tab in browser localStorage
- Switch tabs instantly (no page reload)
- When switching arenas, show only available tabs for that arena

**Data Filtering:**
```javascript
// Pseudo-code for tab filtering
function displayWarriors(arena) {
  let filtered_warriors = warriors.filter(w => w.current_arena === arena);
  renderWarriorsList(filtered_warriors);
  updateTeamRecord(arena);
  updateStandings(arena);
  updateAvailableTabs(arena);  // Show/hide tabs based on arena
}
```

### 8.5.5 Newsletters Tab (Arena & Turn Selection)

**Newsletter Viewer Layout:**

```
NEWSLETTERS TAB
┌─────────────────────────────────────────────────────┐
│ Arena: [Regular Arena ▼]                            │
│ Turn:  [31 ▼]                                       │
│                                                     │
│ [Load Newsletter]                                   │
│                                                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│ THE AGONY AMPHITHEATRE - TURN 31                   │
│                                                     │
│ [Newsletter content displays here]                  │
│                                                     │
│ [Previous Turn] [Next Turn]                         │
└─────────────────────────────────────────────────────┘
```

**Dropdown Behavior:**

1. **Arena Dropdown** (first selection):
   - Options: Regular Arena | Elite Spire | Veteran's Keep
   - Default: Regular Arena

2. **Turn Dropdown** (second selection, dynamic):
   - Populates based on selected arena
   - Shows ONLY turns that have been run for that arena
   - Example:
     - Regular Arena selected → Shows turns 1-31
     - Elite Spire selected → Shows turns 1-8
     - Veteran's Keep selected → Shows turns 1-3

**Example Scenarios:**

| Arena | Available Turns | Dropdown Shows |
|-------|-----------------|----------------|
| Regular | Turns 1-31 run | [31 ▼] [30 ▼] [29 ▼] ... [1 ▼] |
| Elite Spire | Turns 1-8 run | [8 ▼] [7 ▼] [6 ▼] ... [1 ▼] |
| Veteran's Keep | Turns 1-3 run | [3 ▼] [2 ▼] [1 ▼] |

**Implementation:**

```javascript
// When arena is selected, load available turns for that arena
function onArenaSelected(arena) {
  let available_turns = loadAvailableTurns(arena);
  // available_turns for "regular" = [1, 2, 3, ..., 31]
  // available_turns for "elite" = [1, 2, 3, 4, 5, 6, 7, 8]
  // available_turns for "veteran" = [1, 2, 3]
  
  populateTurnDropdown(available_turns);
}

// When turn is selected, load and display newsletter
function onTurnSelected(arena, turn_number) {
  let newsletter = loadNewsletter(arena, turn_number);
  // Loads from: saves/{arena}/turn_{turn_number}/newsletter_turn_{turn_number}.txt
  displayNewsletter(newsletter);
}
```

**Backend Endpoint:**

```python
@app.get("/api/newsletters/available_turns")
async def get_available_turns(arena: str):
    """Return list of available turns for specified arena"""
    if arena == "normal":
        available = [1, 2, 3, ..., 31]  # Turns 1-31
    elif arena == "elite":
        available = [1, 2, 3, 4, 5, 6, 7, 8]  # Turns 1-8
    elif arena == "veteran":
        available = [1, 2, 3]  # Turns 1-3
    
    return {"arena": arena, "available_turns": available}

@app.get("/api/newsletters/content")
async def get_newsletter(arena: str, turn: int):
    """Return newsletter content for specific arena and turn"""
    # Load from: saves/{arena}/turn_{turn}/newsletter_turn_{turn}.txt
    newsletter_path = f"saves/{arena}/turn_{turn}/newsletter_turn_{turn}.txt"
    with open(newsletter_path) as f:
        content = f.read()
    return {"arena": arena, "turn": turn, "content": content}
```

**Features:**

✅ Arena dropdown filters turn availability
✅ Turn dropdown updates dynamically when arena changes
✅ Shows only turns that exist for selected arena
✅ Default view: Most recent turn of selected arena
✅ Previous/Next buttons for navigation between turns
✅ Newsletter displays in readable text format

### 8.5.6 Newsletter Content (Arena-Specific Filtering)

**Newsletter Format (Same for all 3 arenas):**

All newsletters follow the same template structure:
```
═══════════════════════════════════════════════════════
[ARENA NAME] - TURN [X]
═══════════════════════════════════════════════════════

FIGHT SUMMARY
─────────────────────────────────────────────────────

[Fight details by team/warrior]

NOTABLE EVENTS
─────────────────────────────────────────────────────

[Deaths/Resurrections/Promotions/Achievements]

STANDINGS UPDATE
─────────────────────────────────────────────────────

[Team rankings]

WARRIOR HIGHLIGHTS
─────────────────────────────────────────────────────

[Notable warrior performances]
```

**Newsletter Content (Arena-Specific):**

Each arena's newsletter includes ONLY:
- Fights between warriors in that arena
- Warriors currently in that arena
- Promotions/retirements involving that arena
- Deaths (normal) or Resurrections (elite/veteran) in that arena
- Team records for that arena only
- Standings for that arena only

**Example Differences:**

**Regular Arena Newsletter (Turn 31):**
```
═══════════════════════════════════════════════════════
THE AGONY AMPHITHEATRE - TURN 31
═══════════════════════════════════════════════════════

FIGHT SUMMARY
[Shows 23 fights between regular arena warriors]

NOTABLE EVENTS
• Bloodfang achieved promotion eligibility (marked for elite ascension)
• 3 warriors fell in battle
• Blood challenges initiated for fallen warriors

STANDINGS UPDATE
1. Storm           52-15-18
2. At Sea          47-18-10
3. Phoenix         41-25-12

WARRIOR HIGHLIGHTS
• HMS Hood continues dominance with 24-5-6 record
• Shadow Blade recovers from injury
```

**Elite Spire Newsletter (Turn 8):**
```
═══════════════════════════════════════════════════════
THE ELITE SPIRE - TURN 8
═══════════════════════════════════════════════════════

FIGHT SUMMARY
[Shows 6 fights between elite arena warriors only]

NOTABLE EVENTS
• Bloodfang ascends to The Elite Spire (promoted from normal)
• 0 warriors permanently lost (auto-resurrection active)
• 2 warriors resurrected after defeat

STANDINGS UPDATE
1. At Sea          8-2-3
2. Storm           5-3-2

WARRIOR HIGHLIGHTS
• Bloodfang debuts with dominant victory
• Excelsior claims 3 consecutive wins
```

**Veteran's Keep Newsletter (Turn 3):**
```
═══════════════════════════════════════════════════════
THE VETERAN'S KEEP - TURN 3
═══════════════════════════════════════════════════════

FIGHT SUMMARY
[Shows 4 fights between veteran arena warriors only]

NOTABLE EVENTS
• Haven of safety: 0 permanent deaths
• 1 warrior resurrected after defeat
• Warriors continue legacy in sanctuary arena

STANDINGS UPDATE
1. At Sea          3-1-1

WARRIOR HIGHLIGHTS
• OldVeteran still strong at 2-1-0
```

**Newsletter Generation (Backend):**

```python
def generate_newsletter(arena: str, turn: int):
    """Generate arena-specific newsletter"""
    
    # Load only warriors in this arena
    warriors = load_warriors(arena=arena)
    
    # Load only fights from this arena/turn
    fights = load_fights(arena=arena, turn=turn)
    
    # Load only standings for this arena
    standings = load_standings(arena=arena)
    
    # Build newsletter with arena-specific content only
    newsletter_content = f"""
═══════════════════════════════════════════════════════
{ARENA_NAMES[arena]} - TURN {turn}
═══════════════════════════════════════════════════════

FIGHT SUMMARY
{format_fights(fights)}

NOTABLE EVENTS
{format_events(arena, turn)}

STANDINGS UPDATE
{format_standings(standings)}

WARRIOR HIGHLIGHTS
{format_warrior_highlights(warriors, fights)}
"""
    
    # Save to arena-specific location
    save_path = f"saves/{arena}/turn_{turn}/newsletter_turn_{turn}.txt"
    with open(save_path, 'w') as f:
        f.write(newsletter_content)
    
    return newsletter_content
```

**Arena Names in Headers:**
- Regular Arena → "THE AGONY AMPHITHEATRE"
- Elite Spire → "THE ELITE SPIRE"
- Veteran's Keep → "THE VETERAN'S KEEP"

**Key Points:**
✅ Same template format for all 3 newsletters
✅ Content filtered by arena (only show warriors/fights from that arena)
✅ No cross-arena content mixing
✅ Separate newsletter file generated per arena per turn
✅ Storage: `saves/{arena}/turn_{turn}/newsletter_turn_{turn}.txt`
✅ Deaths/Resurrections shown appropriately per arena (deaths in normal, resurrections in elite/veteran)

### 8.5.7 Challenges (Arena-Specific)

**Challenge Pool Isolation:**
- Warriors can ONLY challenge warriors in the **same arena** they currently occupy
- Challenge lists are generated per-arena only
- No cross-arena challenges allowed

**Example - Critical Mass Promotion:**

**Before Promotion (Regular Arena):**
- Critical Mass (ADEPTS tier) can challenge:
  - Other ADEPTS in Regular Arena (same tier)
  - VETERANS in Regular Arena (1 tier above)
  - **Cannot see** Elite warriors in challenge list

**After Promotion (Elite Spire):**
- Critical Mass (ADVANCED ADEPTS tier) can challenge:
  - Other ADVANCED ADEPTS in Elite Spire (same tier)
  - ADVANCED VETERANS in Elite Spire (1 tier above)
  - **Cannot see** Regular Arena warriors anymore
  - **Cannot challenge** Regular Arena warriors (different arena)

**Challenge Range Rules (Per Arena):**
```
Challenge Eligibility (applies within each arena independently):
- Can challenge warriors in your same tier
- Can challenge warriors 1 tier above your tier
- Cannot challenge warriors below your tier
- Cannot challenge warriors in different arenas
```

**Implementation Details:**

```python
def get_challenge_list(warrior):
    """Get valid challenge targets for warrior"""
    # Only warriors in same arena
    same_arena_warriors = [w for w in all_warriors if w.current_arena == warrior.current_arena]
    
    # Filter by tier eligibility (same tier or 1 tier above)
    warrior_tier = get_tier(warrior)
    valid_targets = []
    
    for target in same_arena_warriors:
        target_tier = get_tier(target)
        # Same tier or one tier above
        if target_tier in [warrior_tier, tier_above(warrior_tier)]:
            valid_targets.append(target)
    
    return valid_targets
```

**Arena-Specific Tiers for Challenge Eligibility:**

**Regular Arena Challenge Ranges:**
- RECRUITS can challenge: RECRUITS, ROOKIES
- ROOKIES can challenge: ROOKIES, INITIATES
- INITIATES can challenge: INITIATES, ADEPTS
- ADEPTS can challenge: ADEPTS, VETERANS
- VETERANS can challenge: VETERANS, EXPERTS
- EXPERTS can challenge: EXPERTS, ELITES
- ELITES can challenge: ELITES, CHAMPION
- CHAMPION can challenge: CHAMPION

**Elite Spire Challenge Ranges:**
- ADVANCED RECRUITS can challenge: ADVANCED RECRUITS, ADVANCED ROOKIES
- ADVANCED ROOKIES can challenge: ADVANCED ROOKIES, ADVANCED INITIATES
- (same pattern as Regular, but with ADVANCED prefix)
- ADVANCED CHAMPION can challenge: ADVANCED CHAMPION

**Veteran's Keep Challenge Ranges:**
- VETERAN RECRUITS can challenge: VETERAN RECRUITS, VETERAN ROOKIES
- VETERAN ROOKIES can challenge: VETERAN ROOKIES, VETERAN INITIATES
- (same pattern as Regular, but with VETERAN prefix)
- VETERAN CHAMPION can challenge: VETERAN CHAMPION

**Key Rules:**
✅ Challenge list only shows warriors in same arena
✅ Cannot challenge across arenas
✅ Tier-based range applies within each arena
✅ When warrior promoted, old challenge list cleared
✅ New challenge list generated for new arena

### 8.5.8 Scouting (Arena-Specific)

**Scouting Limits:**
- Each arena allows up to **3 warriors scouted simultaneously**
- Regular Arena: up to 3 scouts
- Elite Spire: up to 3 scouts
- Veteran's Keep: up to 3 scouts
- **Total across all arenas:** up to 9 warriors can be scouted at once

**Scouting Pool (Arena-Specific):**
- Scouting list only shows warriors from the **current arena tab**
- Regular Arena tab: shows only Regular Arena warriors available to scout
- Elite Spire tab: shows only Elite Spire warriors available to scout
- Veteran's Keep tab: shows only Veteran's Keep warriors available to scout

**Example - Scout Management:**

**Regular Arena Tab Active:**
- Scout list shows: Regular Arena warriors only
- Can scout up to 3 Regular warriors
- Cannot see Elite or Veteran warriors in scout list

**Elite Spire Tab Active:**
- Scout list shows: Elite Spire warriors only
- Can scout up to 3 Elite warriors
- Cannot see Regular or Veteran warriors in scout list
- Even if scouting a Regular warrior before promotion, after promotion the scout moves to Elite list

**Veteran's Keep Tab Active:**
- Scout list shows: Veteran's Keep warriors only
- Can scout up to 3 Veteran warriors
- Cannot see Regular or Elite warriors in scout list

**Scouting Information Provided:**
```
Scout Report includes:
- Warrior name, team, record (W-L-K)
- Current arena assignment
- Race, gender, height, weight
- Popularity rating
- Stats (STR, DEX, CON, INT, PRE, SIZE)
- Current tier and recognition
- Equipment (armor, helm, weapons)
- Skills and proficiencies
- Injuries (if any)
- FULL FIGHT LOG (detailed turn-by-turn combat narrative from recent fights)

Scout Report DOES NOT include:
- Strategy configuration
- Training slots
```

**Full Fight Log in Scout Reports:**

Scout reports include the **complete fight narrative** showing turn-by-turn combat details:

```
WARRIOR vs OPPONENT
[Warrior stats, appearance, equipment]
vs
[Opponent stats, appearance, equipment]

MINUTE 1
[Detailed combat actions, dodges, strikes, damage, etc.]

MINUTE 2
[Continued combat narrative]

[Final result and outcome narrative]
```

**Fight Log Details Include:**
- Each minute of the fight broken down
- All attack attempts and outcomes (hit/miss/dodge)
- Damage descriptions
- Weapon effectiveness commentary
- Final result (victory/defeat/concede)
- Victory/defeat narrative

**Fight Log Details EXCLUDE:**
- Strategy configuration (kept secret)
- Training slots (kept secret)
- Strategy switches during combat (not revealed)

**Arena-Specific Fight Logs:**
- Fight logs show only fights from warrior's current arena
- Regular Arena: fights against Regular Arena opponents
- Elite Spire: fights against Elite Spire opponents
- Veteran's Keep: fights against Veteran's Keep opponents
- Logs clearly show opponent's arena and team

**Tactical Value:**
Managers can analyze:
- Warrior's fighting patterns and tendencies
- Weapon effectiveness against different opponents
- How warrior responds to pressure
- Defensive capabilities
- Aggression level and risk tolerance
- Performance under different conditions

**Scout Report Arena Clarity:**
- Reports clearly indicate which arena the scouted warrior is in
- Example: "CRITICAL MASS scouted in THE ELITE SPIRE"
- Example: "SHADOW BLADE scouted in THE AGONY AMPHITHEATRE"

**Promotion Impact on Scouting:**
- If a scouted warrior is promoted:
  - Scout slot opens in old arena
  - Warrior can be re-scouted in new arena if desired
  - Scout information carries over (record, stats, etc.)

**Key Rules:**
✅ Each arena allows 3 scouts maximum
✅ Scout lists filtered by current arena tab
✅ No cross-arena scouting visible
✅ Regular Arena unchanged from current implementation
✅ Elite/Veteran scouts isolated to their respective arenas
✅ Scout reports include arena designation
✅ Total of 9 scouts possible across all arenas simultaneously

---

## 8.6 LOCAL FILE STORAGE STRUCTURE

### 8.5.1 Complete Directory Layout

```
League_Root/
│
├── shared_data/                          # SHARED across all arenas
│   ├── warriors.json                     # Master warrior list (all warriors, with current_arena field)
│   ├── managers.json                     # All managers and their info
│   └── checksums.json                    # Checksums for data integrity
│
├── saves/
│   │
│   ├── normal/                           # THE AGONY AMPHITHEATRE
│   │   ├── teams.json                    # Teams with warriors currently in normal arena
│   │   ├── standings.json                # Leaderboard for normal arena
│   │   ├── league_config_normal.json     # Config: turn counter, scheduler settings, arena-specific rules
│   │   ├── activity.jsonl                # Activity log (promotions, deaths, fights, etc.)
│   │   │
│   │   ├── turn_50/
│   │   │   ├── result_team_AtSea_turn_50.json
│   │   │   ├── result_team_Storm_turn_50.json
│   │   │   ├── result_team_Phoenix_turn_50.json
│   │   │   ├── newsletter_turn_50.txt
│   │   │   └── arena_stats_turn_50.html
│   │   │
│   │   ├── turn_51/
│   │   │   ├── result_team_AtSea_turn_51.json
│   │   │   ├── result_team_Storm_turn_51.json
│   │   │   ├── newsletter_turn_51.txt
│   │   │   └── arena_stats_turn_51.html
│   │   │
│   │   ├── turn_52/
│   │   │   ├── result_team_AtSea_turn_52.json
│   │   │   ├── result_team_Storm_turn_52.json
│   │   │   ├── newsletter_turn_52.txt
│   │   │   └── arena_stats_turn_52.html
│   │   │
│   │   └── managers/                     # Manager upload area for normal arena
│   │       ├── manager1_AtSea_normal.json
│   │       ├── manager2_Storm_normal.json
│   │       └── manager3_Phoenix_normal.json
│   │
│   ├── elite/                            # THE ELITE SPIRE
│   │   ├── teams_elite.json              # Teams with warriors currently in elite arena
│   │   ├── standings_elite.json          # Leaderboard for elite arena
│   │   ├── league_config_elite.json      # Config: turn counter, scheduler settings, arena-specific rules
│   │   ├── activity_elite.jsonl          # Activity log for elite arena
│   │   │
│   │   ├── turn_01/
│   │   │   ├── result_team_AtSea_turn_01.json
│   │   │   ├── result_team_Storm_turn_01.json
│   │   │   ├── newsletter_turn_01.txt
│   │   │   └── arena_stats_turn_01.html
│   │   │
│   │   ├── turn_02/
│   │   │   ├── result_team_AtSea_turn_02.json
│   │   │   ├── result_team_Storm_turn_02.json
│   │   │   ├── newsletter_turn_02.txt
│   │   │   └── arena_stats_turn_02.html
│   │   │
│   │   ├── turn_08/
│   │   │   ├── result_team_AtSea_turn_08.json
│   │   │   ├── result_team_Storm_turn_08.json
│   │   │   ├── newsletter_turn_08.txt
│   │   │   └── arena_stats_turn_08.html
│   │   │
│   │   └── managers/                     # Manager upload area for elite arena
│   │       ├── manager1_AtSea_elite.json
│   │       └── manager2_Storm_elite.json
│   │
│   └── veteran/                          # THE VETERAN'S KEEP
│       ├── teams_veteran.json            # Teams with warriors currently in veteran arena
│       ├── standings_veteran.json        # Leaderboard for veteran arena
│       ├── league_config_veteran.json    # Config: turn counter, scheduler settings, arena-specific rules
│       ├── activity_veteran.jsonl        # Activity log for veteran arena
│       │
│       ├── turn_01/
│       │   ├── result_team_AtSea_turn_01.json
│       │   ├── newsletter_turn_01.txt
│       │   └── arena_stats_turn_01.html
│       │
│       ├── turn_02/
│       │   ├── result_team_AtSea_turn_02.json
│       │   ├── newsletter_turn_02.txt
│       │   └── arena_stats_turn_02.html
│       │
│       ├── turn_03/
│       │   ├── result_team_AtSea_turn_03.json
│       │   ├── newsletter_turn_03.txt
│       │   └── arena_stats_turn_03.html
│       │
│       └── managers/                     # Manager upload area for veteran arena
│           └── manager1_AtSea_veteran.json
│
└── backups/                              # Backup copies before each turn
    ├── normal_backup_turn_52.zip
    ├── elite_backup_turn_08.zip
    └── veteran_backup_turn_03.zip
```

### 8.5.2 Shared Data Files (One Copy For All Arenas)

**shared_data/warriors.json**
```json
{
  "warriors": [
    {
      "warrior_id": "warrior_1",
      "name": "Bloodfang",
      "team_id": "team_at_sea",
      "team_name": "At Sea",
      "manager_id": "manager_1",
      
      "current_arena": "elite",                    // Single current location
      "promoted_at_turn": 1,
      "promoted_arena": "elite",
      
      "stats": {
        "str": 18, "dex": 16, "con": 15, "int": 14, "pre": 13, "size": 10
      },
      
      "record": {
        "wins": 50,                                // Continuous, never resets
        "losses": 20,
        "kills": 18,
        "total_fights": 70
      },
      
      "current_arena_progress": {
        "recognition": 45,                        // Resets when promoted
        "tier": "Ascended",
        "tier_progression": "elite"                // Which arena's tier system
      },
      
      "skills": {
        "sword": 85, "shield": 72, "dodge": 68, ...
      },
      
      "equipment": {
        "weapon": "Bloodreaver Sword", "armor": "Plate Armor", "helm": "Iron Helm"
      },
      
      "injuries": {
        "right_arm": { "severity": 2, "acquired_turn": 23 },
        "left_leg": { "severity": 1, "acquired_turn": 35 }
      },                                          // Retained from normal, none added in elite
      
      "status": {
        "is_dead": false,
        "hp": 145
      },
      
      "metadata": {
        "created_turn": 1,
        "last_fight_turn": 8,
        "last_fight_arena": "elite"
      }
    },
    {
      "warrior_id": "warrior_2",
      "name": "Shadow Blade",
      "current_arena": "normal",                   // Still in normal arena
      "promoted_at_turn": null,
      ...
    }
  ]
}
```

**shared_data/managers.json**
```json
{
  "managers": [
    {
      "manager_id": "manager_1",
      "name": "John Doe",
      "team_id": "team_at_sea",
      "team_name": "At Sea",
      
      "warriors_by_arena": {
        "normal": ["warrior_2", "warrior_3", "warrior_5"],     // Warriors still in normal
        "elite": ["warrior_1"],                                 // Warriors promoted to elite
        "veteran": []                                           // No warriors in veteran yet
      },
      
      "contact": "john@example.com",
      "last_upload": "2026-08-11T14:30:00Z",
      "last_download": "2026-08-11T14:45:00Z"
    }
  ]
}
```

### 8.5.3 Arena-Specific Files (Normal Arena Example)

**saves/normal/teams.json**
```json
{
  "teams": [
    {
      "team_id": "team_at_sea",
      "team_name": "At Sea",
      "manager_id": "manager_1",
      "manager_name": "John Doe",
      
      "warriors": [
        "warrior_2",      // Shadow Blade (still in normal)
        "warrior_3",      // Ironblade (still in normal)
        "warrior_5"       // Excelsior (still in normal)
        // Note: warrior_1 (Bloodfang) is NOT here - promoted to elite
      ],
      
      "record": {
        "wins": 47,
        "losses": 18,
        "kills": 10,
        "standing_rank": 2
      }
    },
    {
      "team_id": "team_storm",
      "team_name": "Storm",
      "manager_id": "manager_2",
      "warriors": ["warrior_6", "warrior_7", "warrior_8"],
      "record": {"wins": 52, "losses": 15, "kills": 18, "standing_rank": 1}
    }
  ]
}
```

**saves/normal/standings.json**
```json
{
  "arena": "normal",
  "turn": 52,
  "standings": [
    {"rank": 1, "team_id": "team_storm", "team_name": "Storm", "wins": 52, "losses": 15, "kills": 18},
    {"rank": 2, "team_id": "team_at_sea", "team_name": "At Sea", "wins": 47, "losses": 18, "kills": 10},
    {"rank": 3, "team_id": "team_phoenix", "team_name": "Phoenix", "wins": 41, "losses": 25, "kills": 12}
  ]
}
```

**saves/normal/league_config_normal.json**
```json
{
  "arena": "normal",
  "turn_counter": 52,
  "scheduler": {
    "enabled": true,
    "interval_hours": 24,
    "last_run": "2026-08-11T14:30:00Z",
    "next_run": "2026-08-12T14:30:00Z"
  },
  "arena_rules": {
    "allow_permanent_death": true,
    "allow_blood_challenges": true,
    "allow_monsters": true,
    "training_difficulty_multiplier": 1.0,
    "peasant_scaling": 1.0
  },
  "promotion_criteria": {
    "min_fights": 40,
    "min_win_rate": 0.55
  }
}
```

**saves/normal/activity.jsonl** (line-delimited JSON)
```
{"timestamp": "2026-08-11T14:00:00Z", "type": "fight", "warrior": "warrior_2", "opponent": "Shadow Master", "result": "win", "new_record": "35-12-8"}
{"timestamp": "2026-08-11T14:05:00Z", "type": "fight", "warrior": "warrior_3", "opponent": "Grim Challenger", "result": "loss", "new_record": "28-14-9"}
{"timestamp": "2026-08-11T14:10:00Z", "type": "promotion_eligible", "warrior": "warrior_1", "criteria_met": true, "marked_for_promotion": "elite"}
{"timestamp": "2026-08-11T14:15:00Z", "type": "fight", "warrior": "warrior_1", "opponent": "Grim Challenger", "result": "loss", "note": "Final mortal fight - immortality shield activated"}
{"timestamp": "2026-08-11T14:20:00Z", "type": "promotion_complete", "warrior": "warrior_1", "destination_arena": "elite", "record_at_promotion": "42-18-15"}
```

**saves/normal/turn_52/result_team_AtSea_turn_52.json**
```json
{
  "turn": 52,
  "arena": "normal",
  "team_id": "team_at_sea",
  "team_name": "At Sea",
  "fights": [
    {
      "fight_id": "fight_001",
      "turn": 52,
      "warrior_id": "warrior_2",
      "warrior_name": "Shadow Blade",
      "opponent_id": "ai_peasant_123",
      "opponent_name": "Shadow Master",
      "warrior_record_before": "34-12-8",
      "warrior_record_after": "35-12-8",
      "result": "win",
      "narrative": "[Fight narrative text]",
      "injuries_sustained": [],
      "final_hp": 142
    },
    {
      "fight_id": "fight_002",
      "turn": 52,
      "warrior_id": "warrior_3",
      "warrior_name": "Ironblade",
      "opponent_id": "ai_peasant_124",
      "opponent_name": "Grim Challenger",
      "warrior_record_before": "28-13-9",
      "warrior_record_after": "28-14-9",
      "result": "loss",
      "narrative": "[Fight narrative text]",
      "injuries_sustained": [{"location": "right_shoulder", "severity": 1}],
      "final_hp": -25,
      "death_check_result": "survived",
      "resurrected": false
    }
  ],
  "team_record_before": {"wins": 46, "losses": 18, "kills": 10},
  "team_record_after": {"wins": 47, "losses": 18, "kills": 10},
  "summary": "2 fights: 1 win, 1 loss. At Sea maintains position 2."
}
```

### 8.5.4 Elite Spire Files (Similar Structure)

**saves/elite/teams_elite.json** (SEPARATE from normal)
```json
{
  "teams": [
    {
      "team_id": "team_at_sea",
      "team_name": "At Sea",
      "manager_id": "manager_1",
      
      "warriors": [
        "warrior_1"        // Bloodfang (promoted from normal)
        // Only this warrior from At Sea is in elite arena
      ],
      
      "record": {
        "wins": 8,         // Separate from normal arena
        "losses": 2,
        "kills": 3,
        "standing_rank": 1
      }
    },
    {
      "team_id": "team_storm",
      "team_name": "Storm",
      "warriors": ["warrior_6_elite"],  // Storm also has an elite warrior
      "record": {"wins": 5, "losses": 3, "kills": 2, "standing_rank": 2}
    }
  ]
}
```

**saves/elite/standings_elite.json**
```json
{
  "arena": "elite",
  "turn": 8,
  "standings": [
    {"rank": 1, "team_id": "team_at_sea", "team_name": "At Sea", "wins": 8, "losses": 2, "kills": 3},
    {"rank": 2, "team_id": "team_storm", "team_name": "Storm", "wins": 5, "losses": 3, "kills": 2}
  ]
}
```

**saves/elite/league_config_elite.json**
```json
{
  "arena": "elite",
  "turn_counter": 8,
  "scheduler": {
    "enabled": true,
    "interval_hours": 24,
    "last_run": "2026-08-10T08:15:00Z",
    "next_run": "2026-08-11T08:15:00Z"
  },
  "arena_rules": {
    "allow_permanent_death": false,
    "allow_blood_challenges": false,
    "allow_monsters": false,
    "allow_resurrection": true,
    "training_difficulty_multiplier": 1.33,       // 33% harder
    "peasant_scaling": 2.5,                        // 2-3x stronger
    "injury_accumulation": false                   // No new injuries in elite
  }
}
```

**saves/elite/turn_08/result_team_AtSea_turn_08.json**
```json
{
  "turn": 8,
  "arena": "elite",
  "team_id": "team_at_sea",
  "fights": [
    {
      "fight_id": "elite_fight_001",
      "turn": 8,
      "warrior_id": "warrior_1",
      "warrior_name": "Bloodfang",
      "opponent_name": "Elite Shadow Warrior",
      "warrior_record_before": "49-20-17",
      "warrior_record_after": "50-20-18",
      "result": "win",
      "arena": "elite",
      "recognition_gained": 8,
      "new_tier": "Eternal",
      "narrative": "[Immortal arena fight narrative]"
    }
  ],
  "team_record_before": {"wins": 7, "losses": 2, "kills": 3},
  "team_record_after": {"wins": 8, "losses": 2, "kills": 3},
  "summary": "Bloodfang claims victory in The Elite Spire"
}
```

### 8.5.5 Manager Download Structure

**When a manager downloads from the admin panel:**

```
Manager1_AtSea_Download_Turn52_20260811.zip
│
├── Normal_Arena/
│   ├── team_AtSea_normal.json           // Their team roster in normal arena
│   ├── warriors_normal.json             // All their warriors in normal arena (detailed)
│   ├── turn_52_results.json             // Their turn 52 results for normal arena
│   ├── standings_normal_turn_52.json    // Normal arena leaderboard
│   └── newsletter_normal_turn_52.txt    // Normal arena newsletter
│
├── Elite_Spire/                         // ONLY if they have warriors in elite
│   ├── team_AtSea_elite.json            // Their team roster in elite arena
│   ├── warriors_elite.json              // All their warriors in elite arena (detailed)
│   ├── turn_08_results.json             // Their turn 08 results for elite arena
│   ├── standings_elite_turn_08.json     // Elite arena leaderboard
│   └── newsletter_elite_turn_08.txt     // Elite arena newsletter
│
├── Veteran_Keep/                        // ONLY if they have warriors in veteran
│   ├── team_AtSea_veteran.json
│   ├── warriors_veteran.json
│   ├── turn_XX_results.json
│   ├── standings_veteran.json
│   └── newsletter_veteran.txt
│
└── manifest.json                        // Metadata about this download
    {
      "download_time": "2026-08-11T14:45:00Z",
      "arenas_included": ["normal", "elite"],
      "turn_numbers": {
        "normal": 52,
        "elite": 8
      },
      "warriors_summary": {
        "normal": 3,
        "elite": 1,
        "veteran": 0
      }
    }
```

### 8.5.6 Manager Upload Structure

**When a manager uploads an updated team file for normal arena:**

```
Manager1_AtSea_normal_turn52_update.json

{
  "arena": "normal",
  "team_id": "team_at_sea",
  "team_name": "At Sea",
  "manager_id": "manager_1",
  "upload_turn": 52,
  
  "warriors": [
    {
      "warrior_id": "warrior_2",
      "name": "Shadow Blade",
      "current_record": "35-12-8",
      "strategy": {...},
      "equipment_changes": {...}
    },
    {
      "warrior_id": "warrior_3",
      "name": "Ironblade",
      "current_record": "28-14-9",
      "strategy": {...}
    }
  ],
  
  "manifest": {
    "uploaded": "2026-08-11T15:00:00Z",
    "version": 1,
    "checksum": "abc123def456"
  }
}
```

---

### 8.5.7 Checksum File Structure

**shared_data/checksums.json**
```json
{
  "warriors": {
    "checksum": "sha256_hash_of_warriors_json",
    "last_updated": "2026-08-11T14:20:00Z"
  },
  "managers": {
    "checksum": "sha256_hash_of_managers_json",
    "last_updated": "2026-08-11T14:20:00Z"
  },
  "arenas": {
    "normal": {
      "teams": "sha256_hash",
      "standings": "sha256_hash",
      "config": "sha256_hash",
      "last_updated": "2026-08-11T15:30:00Z"
    },
    "elite": {
      "teams": "sha256_hash",
      "standings": "sha256_hash",
      "config": "sha256_hash",
      "last_updated": "2026-08-10T08:20:00Z"
    },
    "veteran": {
      "teams": "sha256_hash",
      "standings": "sha256_hash",
      "config": "sha256_hash",
      "last_updated": null
    }
  }
}
```

---

### 8.5.8 Key Storage Principles

| Aspect | Rule |
|--------|------|
| **Warrior Data** | Lives in `shared_data/warriors.json` - one copy for all arenas |
| **Team Rosters** | Split by arena (`teams.json`, `teams_elite.json`, `teams_veteran.json`) |
| **Results** | Stored in arena-specific turn directories |
| **Standings** | Separate file per arena (`standings.json`, `standings_elite.json`, etc.) |
| **Config** | Separate per arena (each has own turn counter, scheduler, rules) |
| **Activity Log** | Separate per arena (`activity.jsonl`, `activity_elite.jsonl`, etc.) |
| **Manager Uploads** | Saved to arena-specific `managers/` folder |
| **Backups** | Before each turn, backup that arena's data |
| **Checksums** | Validate all files, especially warrior.json (critical) |

---



When ready to implement, follow this sequence:

1. **Data Model Changes**
   - Update warrior.records to per-arena structure
   - Update team structure for per-arena records
   - Create shared_data/warriors.json layout

2. **Admin Panel**
   - Create three separate tabs
   - Add tab controls (run turn, load results, clear arena, etc.)
   - Implement manual turn triggers

3. **Schedulers**
   - Create three AsyncIOScheduler instances
   - Add start/stop/pause/resume controls
   - Implement status monitoring

4. **Turn Execution**
   - Split run_turn() into run_normal_turn(), run_elite_spire_turn(), run_veteran_keep_turn()
   - Implement arena-specific logic in each
   - Add independent turn counters

5. **File Organization**
   - Reorganize saves/ directory structure
   - Create arena-specific team files
   - Split standings.json into three files

6. **Testing**
   - Verify independent turn execution
   - Test scheduler start/stop
   - Verify data isolation between arenas
   - Test promotion flow across arenas
