# Immortal & Retirement Arena System - Implementation Plan (COMPLETE)

**Date**: 2026-08-08 (Final 2026-08-11)
**Scope**: Add The Elite Spire and The The Soul Spire as completely separate arena instances with independent schedulers, admin tabs, and data files
**Architecture**: Three independent league instances sharing the same warrior/team database but operating on separate turn cycles

---

## EXECUTIVE SUMMARY

Create **three completely separate arena instances** that operate independently:

| Arena | Code | Instance Type | Death Mechanic | Tier System | Admin Tab | Scheduler | Data Files |
|-------|------|---|---|---|---|---|---|
| **The Agony Amphitheatre** | `"normal"` | Primary instance | Permanent death | RECRUITS → CHAMPIONS | Normal | Normal Scheduler | Downloads, teams.json, standings.json |
| **The Elite Spire** | `"elite"` | Separate instance | Auto-resurrection | ADVANCED RECRUITS → ADVANCED CHAMPION | Elite Spire | Elite Scheduler | Downloads, teams_elite.json, standings_elite.json |
| **The Soul Spire** | `"soul"` | Separate instance | Auto-resurrection | DEATHLY RECRUITS → DEATHLY CHAMPION | Soul Spire | Soul Spire Scheduler | Downloads, teams_soul.json, standings_soul.json |

**Key Principle:** Each arena is a **completely independent league** that operates independently:
- **Normal Arena:** Mortal warriors with permanent death risk
- **Elite Spire:** Promoted elite warriors with resurrection
- **Soul Spire:** Admin-resurrected dead warriors with resurrection

Warriors in Normal/Elite follow promotion paths. Warriors in Soul Spire are exclusively admin-selected from dead warriors. All arenas have independent tier progressions and records.

---

## 1. TIER SYSTEMS BY ARENA

### Regular Arena (The Agony Amphitheatre)
- RECRUITS (0-12)
- ROOKIES (13-25)
- INITIATES (26-40)
- ADEPTS (41-55)
- VETERANS (56-70)
- EXPERTS (71-86)
- ELITES (87-100)
- CHAMPION (Champion status)

### Elite Spire (The Elite Spire)
- ADVANCED RECRUITS (0-12)
- ADVANCED ROOKIES (13-25)
- ADVANCED INITIATES (26-40)
- ADVANCED ADEPTS (41-55)
- ADVANCED VETERANS (56-70)
- ADVANCED EXPERTS (71-86)
- ADVANCED ELITES (87-100)
- ADVANCED CHAMPION (Champion status)

### The Soul Spire (The Soul Spire - Resurrected Dead Warriors)
- DEATHLY RECRUITS (0-12)
- DEATHLY ROOKIES (13-25)
- DEATHLY INITIATES (26-40)
- DEATHLY ADEPTS (41-55)
- DEATHLY VETERANS (56-70)
- DEATHLY EXPERTS (71-86)
- DEATHLY ELITES (87-100)
- DEATHLY CHAMPION (Champion status)

---

## 2. PROMOTION & ARENA TRANSITIONS

### 2.1 Promotion Eligibility Criteria

**For Elite Spire:**
```
Minimum Fights:  40
Win Rate:        55%+ (or custom %)
Total Wins:      ≥ 22 (derived from 40 fights at 55%)
```

**Selection:** Batch promotion each turn (auto-promote all eligible) or scheduled (e.g., weekly)

### 2.2 Deferred Promotion Workflow (Two-Turn Process)

**Turn N (Eligibility Turn):**
1. Warrior becomes eligible
2. `pending_promotion = "elite"` or `"veteran"` set
3. `pending_promotion_turn = N` recorded
4. Newsletter announces: "Warrior marked for [arena] ascension!"

**Turn N+1 (Final Mortal Fight Turn):**
1. Warrior fights in NORMAL arena (not yet promoted)
2. Fight narrative tagged: "FINAL MORTAL CHALLENGE"
3. If DIES (immortality shield activates):
   - Narrative: "Warrior falls in their final mortal clash!"
   - Post-fight: Set `current_arena = "elite"` or `"veteran"`
   - Newsletter: "Though fallen, Warrior's spirit ascends!"
4. If SURVIVES:
   - Narrative: "Warrior claims one final victory as a mortal!"
   - Post-fight: Set `current_arena = "elite"` or `"veteran"`
   - Newsletter: "Warrior ascends to [arena]!"
5. Clear `pending_promotion` flag

**Turn N+2 onward:**
- Warrior fights in new arena, subject to resurrection on death

### 2.3 Promotion Data Transfer

**What carries forward unchanged:**
- Full warrior object with all stats (STR, DEX, CON, INT, PRE, SIZE)
- Fight record (W-L-K intact, never resets)
- Skills and weapon proficiencies
- Equipment (weapons, armor, helm)
- **Permanent injuries at promotion time** (persist, but no new injuries added)
- Luck modifier (1-30 bonus carries forward)
- Strategy configurations

**What resets on promotion:**
- Recognition rating: Drops to 0 (starts fresh in new arena's tier system)
- Popularity: Resets to starting value

### 2.4 Admin Resurrection to The Soul Spire (Primary Entry Method)

**The Soul Spire is exclusively populated by admin-selected dead warriors.** There is no automatic promotion or manager choice involved.

**Selection Process:**
- Admin opens resurrection panel from admin dashboard
- Filters dead warriors by win rate, fight count, manager
- Bulk selects desired dead warriors
- Confirms resurrection

**Data Transfer on Resurrection:**
- Full warrior object resurrected as-is
- Fight record carries forward (W-L-K intact)
- Stats (STR, DEX, CON, INT, PRE, SIZE) unchanged
- Skills and weapon proficiencies intact
- Equipment preserved
- Permanent injuries at time of death are retained
- Luck modifier carries forward

**What resets on resurrection:**
- Recognition rating: Drops to 0 (starts fresh in DEATHLY tiers)
- Popularity: Resets to starting value
- is_dead flag: Cleared

**Resurrection Mechanics:**
- Direct resurrection (no pending_promotion state)
- Set `current_arena = "soul"`
- Recognition resets to 0
- Warrior ready to fight in The Soul Spire immediately

### 2.5 Resurrection from Playtest (Auto-Populate Initial Arena)

**Selection Criteria for Initial Seeding:**
- Died in playtest (flagged in results)
- Minimum 20 fights before death
- Win rate filtering:
  - 50%+ → Elite Arena (direct promotion)
  - <50% → The Soul Spire (direct promotion)

**Process:**
1. Parse playtest results
2. Identify dead warriors with 20+ fights
3. Tier by win rate
4. Set `current_arena` directly (skip pending promotion)
5. Clear `is_dead` flag, set `promoted_at_turn`

**Note:** Playtest resurrection follows same tier-based routing as other resurrections, but can be automated during initial arena population.

---

## 3. ARENA-SPECIFIC MECHANICS

### 3.1 Death & Resurrection Logic

**Normal Arena:**
- Permanent death possible
- Roll death check on HP ≤ 0
- Can die and be removed from roster

**Elite Spire & The Soul Spire:**
- NO permanent death
- Auto-resurrect on HP ≤ 0
- HP restored to full on next turn

### 3.2 Injury Accumulation

**Normal Arena:**
- Injuries accumulate normally
- New injuries can be sustained each fight

**Elite Spire & The Soul Spire:**
- NO new permanent injuries accumulate
- Injuries from before promotion are retained
- New injury rolls are skipped

### 3.3 Blood Challenges Restriction

**Blood Challenges (Revenge Bouts):**
- **ONLY available in Normal Arena**
- When warrior dies in Normal Arena, blood challenge system activates (3-turn window)
- **Immortal and Soul Spire warriors CANNOT be targeted for blood revenge**
- **Immortal and Soul Spire warriors CANNOT use blood challenges**
- **Cross-arena revenge is NOT allowed**

**Rationale:** No permanent death in elite/soul spire, so revenge mechanic doesn't apply.

### 3.4 Peasant Opponent Scaling

**Peasant Fights (AI Filler Opponents):**
- **Normal Arena:** Existing scaling (current system)
- **Elite Spire:** Scaled **2-3x stronger** (elite opponents)
- **The Soul Spire:** Scaled **1.5-2x stronger** (experienced opponents)

### 3.5 Monster Fights Restriction

**Monster Fights:**
- **Normal Arena:** Allowed (opt-in)
- **Elite Spire:** NOT ALLOWED
- **The Soul Spire:** NOT ALLOWED

**Rationale:** Monster fights are proving grounds for mortal warriors; immortal and resurrected warriors transcend mortal challenges.

### 3.6 Training Difficulty

**Skill Training:**
- **Normal Arena:** Existing training system
- **Elite Spire:** Training **33% harder** (difficulty increase)
- **The Soul Spire:** Existing training system (same as normal)

**How 33% Harder Works:**
```python
# Normal arena success_chance = base_chance + int_bonus + luck + modifiers

# Elite arena
success_chance = (base_chance + int_bonus + luck + modifiers) * 0.67
# Warriors need higher INT or luck to succeed at training
```

### 3.7 Scouting Across Arenas

**Scouting:**
- Managers CAN scout warriors from different arenas
- Scout reports include current arena assignment
- Information advantage valuable across all arenas

### 3.8 Concede/Mercy System

**Concede Mechanics:**
- **All Arenas:** Existing system unchanged
- Concede available in elite/soul spire as well

### 3.9 Recognition/Tier Progression

**Tier System Per Arena:**
- Each arena tracks recognition independently (0-99 scale)
- Warriors start at 0 recognition when promoted
- Gain/lose recognition based on fight outcomes (existing formulas, per arena)
- Tier names are arena-specific
- Champions can exist in each arena (separate status per arena)

---

## 4. CHALLENGES (ARENA-SPECIFIC)

**Challenge Pool Isolation:**
- Warriors can ONLY challenge warriors in the **same arena**
- Challenge lists generated per-arena only
- No cross-arena challenges allowed

**Challenge Range Rules (Per Arena):**
- Can challenge warriors in your same tier
- Can challenge warriors 1 tier above your tier
- Cannot challenge warriors below your tier
- Cannot challenge warriors in different arenas

**Example:**
- ADEPTS in Normal → can challenge ADEPTS and VETERANS in Normal only
- ADVANCED ADEPTS in Elite → can challenge ADVANCED ADEPTS and ADVANCED VETERANS in Elite only
- DEATHLY ADEPTS in Soul Spire → can challenge DEATHLY ADEPTS and DEATHLY VETERANS in Soul Spire only

---

## 5. SCOUTING (ARENA-SPECIFIC)

**Scouting Limits:**
- Each arena allows up to **3 warriors scouted simultaneously**
- Total across all arenas: **up to 9 warriors** can be scouted at once

**Scouting Pool (Arena-Specific):**
- Scouting list only shows warriors from the **current arena tab**
- Regular Arena tab: shows only Regular Arena warriors
- Elite Spire tab: shows only Elite Spire warriors
- The Soul Spire tab: shows only The Soul Spire warriors

**Scout Report Information:**
```
Includes:
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

Does NOT include:
- Strategy configuration
- Training slots
```

**Full Fight Log Details:**
- Each minute of fight broken down
- All attack/dodge/hit outcomes
- Damage descriptions
- Weapon effectiveness
- Final result and narrative
- Does NOT show strategy switches or training info

---

## 6. FRONTEND UI

### 6.1 Arena Tab Navigation
- Left-side tabs: Regular Arena | Elite Spire | The Soul Spire
- Shows only warriors/teams from selected arena
- Same UI layout for all tabs, just filtered data

### 6.2 Arena-Specific Upload/Download

**Actions Menu:**
- **Regular Arena**
  - Upload: Regular Arena warriors only
  - Download: Regular Arena results only
  - Limitation: 1 download per turn
  
- **Elite Spire**
  - Upload: Elite Spire warriors only
  - Download: Elite Spire results only
  - Limitation: None (no permanent death)
  
- **The Soul Spire**
  - Upload: The Soul Spire warriors only
  - Download: The Soul Spire results only
  - Limitation: None (no permanent death)

### 6.3 Warrior Tab Availability

**Regular Arena - All tabs:**
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

**The Soul Spire - Limited tabs:**
- Stats/Strats ✅
- Fights ✅
- Challenges ✅

### 6.4 Newsletters Tab

**Layout:**
- Arena dropdown: Regular Arena | Elite Spire | The Soul Spire
- Turn dropdown: Dynamic (shows only turns available for selected arena)
- Newsletter content: Arena-filtered (only warriors/fights/events from that arena)

**Newsletter Format (Same for all 3 arenas):**
```
═══════════════════════════════════════════════════════
[ARENA NAME] - TURN [X]
═══════════════════════════════════════════════════════

FIGHT SUMMARY
[Fight details by team/warrior]

NOTABLE EVENTS
[Deaths/Resurrections/Promotions/Achievements]

STANDINGS UPDATE
[Team rankings]

WARRIOR HIGHLIGHTS
[Notable warrior performances]
```

**Newsletter Content (Arena-Specific):**
- Fights between warriors in that arena only
- Warriors currently in that arena
- Promotions/retirements involving that arena
- Deaths (normal) or Resurrections (elite/veteran) in that arena
- Team records for that arena only
- Standings for that arena only

---

## 7. ADMIN PANEL

### 7.1 Three Separate Admin Tabs

Each tab includes:
- Current turn display (independent counter)
- Status indicator
- Warrior count in that arena
- Team count
- [RUN TURN] button
- [LOAD RESULTS] button
- [CLEAR ARENA] button
- [RESURRECTION PANEL] button
- Recent turn results log

### 7.2 Admin Resurrection Panel

**Purpose:** Allow manual selection and bulk resurrection of dead warriors

**Features:**
1. **Filter & Search Dead Warriors**
   - Filter by manager (dropdown or search)
   - Filter by win rate range (e.g., 50-75%)
   - Filter by fight count (minimum/maximum)
   - Real-time result count

2. **Eligibility Criteria**
   - Admin defines criteria (e.g., "50%+ win rate AND 20+ fights")
   - System shows eligibility status for each warrior
   - Admin can manually override and resurrect ineligible warriors

3. **Warrior Preview & Selection**
   - Display table of filtered warriors
   - Checkboxes for bulk selection
   - "Select All" / "Deselect All" buttons
   - Warrior count displayed

4. **Confirmation & Promotion**
   - Preview panel showing selected warriors
   - Confirmation dialog before promoting
   - Warnings if promoting ineligible warriors
   - [Resurrect Selected Warriors] button

5. **Activity Logging**
   - Log each resurrection event
   - Include: admin user, warrior name, team, record, timestamp
   - Summary message per resurrection

**Resurrection Details:**
- Warriors promoted directly to Elite (no pending process)
- Recognition resets to 0
- Individual record carries over
- Team record starts at 0-0-0

### 7.3 Admin Arena Clear Functions

**Three separate clear endpoints:**

```python
@app.post("/api/admin/clear_elite_spire")
@app.post("/api/admin/clear_veteran_keep")
@app.post("/api/admin/clear_all_advanced_arenas")
```

**Safety Features:**
- Confirmation dialog required
- Shows count of warriors to be removed
- Shows teams affected
- **CRITICAL:** States "The Agony Amphitheatre will NOT be affected"
- Logs all actions with admin user and timestamp
- Verifies The Agony Amphitheatre remains untouched

**What Gets Cleared:**
- All warriors from target arena(s) removed
- Team records for cleared arena(s) reset to 0-0-0
- Turn counter reset for arena
- Does NOT affect other arenas

---

## 8. WARRIOR & TEAM RECORDS

### 8.1 Individual Warrior Records (Continuous)
- W-L-K never resets
- Carries forward across arenas
- Example: 20-12-2 before promotion → 21-12-2 after first elite win

### 8.2 Team Records (Arena-Specific, Fresh Start)
- Each arena has separate team record (starts 0-0-0)
- Only warriors currently in that arena contribute
- Promoted warriors stop contributing to old arena's record immediately
- Example:
  - Before promotion: Team 77-78-10 (all warriors in normal)
  - After promotion: Team normal 77-78-10 (minus promoted warrior's future fights), Team elite 0-0-0

---

## 9. DATA FILE ORGANIZATION

### 9.1 Shared Files (One Copy)
```
shared_data/
├── warriors.json              # Master warrior list (all warriors, current_arena field)
├── managers.json              # All managers
└── checksums.json             # Validation checksums
```

### 9.2 Arena-Specific Files

```
saves/normal/                  # THE AGONY AMPHITHEATRE
├── teams.json
├── standings.json
├── league_config_normal.json
├── activity.jsonl
└── turn_XX/

saves/elite/                   # THE ELITE SPIRE
├── teams_elite.json
├── standings_elite.json
├── league_config_elite.json
├── activity_elite.jsonl
└── turn_XX/

saves/veteran/                 # THE VETERAN'S KEEP
├── teams_veteran.json
├── standings_veteran.json
├── league_config_veteran.json
├── activity_veteran.jsonl
└── turn_XX/
```

### 9.3 Upload/Download Structure

**Manager Downloads:**
- Regular Arena results folder (if warriors in regular)
- Elite Spire results folder (if warriors in elite)
- The Soul Spire results folder (if warriors in veteran)
- Manifest with metadata

**Manager Uploads:**
- Regular Arena update file
- Elite Spire update file (optional)
- The Soul Spire update file (optional)

---

## 10. INDEPENDENT SCHEDULERS

**Architecture:**
Use the same Turn Schedule system currently in place, but configure it separately for each arena. Each arena gets its own independent scheduler instance using the existing scheduling mechanism.

**Three separate schedulers (using existing Turn Schedule system):**
- **Normal Arena Scheduler** (tracks normal_turn counter, uses existing system)
- **Elite Spire Scheduler** (tracks elite_turn counter, uses existing system)
- **The Soul Spire Scheduler** (tracks veteran_turn counter, uses existing system)

**Admin Panel Scheduler Controls:**
Each arena tab in the admin panel includes:
- Current turn number display
- Schedule status (enabled/disabled)
- Next scheduled run time
- [Run Now] button (manual trigger, bypasses schedule)
- [Edit Schedule] button (configure auto-run interval for this arena)
- [Enable/Disable] toggle (activate or pause this arena's scheduler)

**How It Works:**
1. Each arena can be independently configured with its own auto-run schedule
2. Normal Arena might run every 24 hours
3. Elite Spire might run every 24 hours on different time
4. The Soul Spire might run every 48 hours
5. Each scheduler tracks its own turn counter independently
6. Can manually trigger any arena's turn from admin panel at any time
7. Schedulers can be enabled/disabled independently
8. Each arena runs at its own pace (not synchronized with others)

**Scheduler Configuration (per arena):**
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

**Key Points:**
✅ Uses existing Turn Schedule system (replicated 3 times, one per arena)
✅ Each arena has independent turn counter
✅ Each arena can have different auto-run schedule
✅ Each arena can be manually triggered independently
✅ Each arena can be enabled/disabled independently
✅ Same scheduling mechanism, just applied separately to each arena

---

## 11. IMPLEMENTATION GUIDE

### 9.1 Function Signatures and Arena-Aware Data Loading

**Core Data Loading Functions (arena-aware):**

```python
def load_standings(arena: str) -> dict:
    """Load standings for a specific arena"""
    arena_dir = f"saves/{arena}"
    if arena == "normal":
        path = os.path.join(arena_dir, "standings.json")
    else:
        path = os.path.join(arena_dir, f"standings_{arena}.json")
    with open(path) as f:
        return json.load(f)

def load_teams(arena: str) -> list:
    """Load teams for a specific arena"""
    arena_dir = f"saves/{arena}"
    if arena == "normal":
        path = os.path.join(arena_dir, "teams.json")
    else:
        path = os.path.join(arena_dir, f"teams_{arena}.json")
    with open(path) as f:
        return json.load(f)

def load_warriors(arena: str = None) -> list:
    """Load all warriors, optionally filtered by arena"""
    with open("shared_data/warriors.json") as f:
        all_warriors = json.load(f)
    
    if arena:
        return [w for w in all_warriors if w.get("current_arena") == arena]
    return all_warriors

def save_standings(arena: str, standings: dict):
    """Save standings for a specific arena"""
    arena_dir = f"saves/{arena}"
    if arena == "normal":
        path = os.path.join(arena_dir, "standings.json")
    else:
        path = os.path.join(arena_dir, f"standings_{arena}.json")
    with open(path, 'w') as f:
        json.dump(standings, f, indent=2)
```

### 9.2 Tier System Implementation

**Tier Prefix Mapping:**

```python
TIER_PREFIXES = {
    "normal": "",           # No prefix: RECRUITS, ROOKIES, etc.
    "elite": "ADVANCED ",   # Prefix: ADVANCED RECRUITS, etc.
    "soul": "DEATHLY ",     # Prefix: DEATHLY RECRUITS, etc.
}

TIER_NAMES = [
    "RECRUITS", "ROOKIES", "INITIATES", "ADEPTS",
    "VETERANS", "EXPERTS", "ELITES", "CHAMPION"
]

TIER_RECOGNITION_RANGES = {
    "RECRUITS": (0, 12),
    "ROOKIES": (13, 25),
    "INITIATES": (26, 40),
    "ADEPTS": (41, 55),
    "VETERANS": (56, 70),
    "EXPERTS": (71, 86),
    "ELITES": (87, 100),
    "CHAMPION": (101, 9999),
}

def get_tier_name(recognition: int, arena: str, is_champion: bool = False) -> str:
    """Get full tier name with arena-specific prefix"""
    if is_champion:
        base_tier = "CHAMPION"
    else:
        for tier, (min_rec, max_rec) in TIER_RECOGNITION_RANGES.items():
            if min_rec <= recognition <= max_rec:
                base_tier = tier
                break
        else:
            base_tier = "RECRUITS"
    
    prefix = TIER_PREFIXES.get(arena, "")
    return prefix + base_tier
```

### 9.3 Warrior State Transitions: Promotion and Resurrection

**Complete Field Specification for Promotion (Normal → Elite or Soul Spire):**

```python
def promote_warrior(warrior_id: str, target_arena: str, current_turn: int):
    """
    Promote warrior from normal arena to elite or soul spire.
    
    Fields that CARRY FORWARD (unchanged):
    - warrior_id, name, team_id, team_name, manager_id
    - stats (STR, DEX, CON, INT, PRE, SIZE)
    - wins, losses, kills (continuous total record)
    - skills, proficiencies
    - equipment (weapon, armor, helm)
    - injuries (from normal arena, no new ones)
    - luck_modifier
    - hp (full heal)
    - race, gender, appearance
    
    Fields that RESET:
    - current_arena: "normal" → target_arena
    - recognition: any value → 0 (starts fresh in new tier system)
    - tier: old tier → RECRUITS/ADVANCED RECRUITS/DEATHLY RECRUITS
    - promoted_at_turn: set to current_turn
    - promoted_arena: set to target_arena
    - pending_promotion: cleared
    - is_dead: false (no death in elite/soul)
    - promoted_timestamp: current datetime
    """
    warrior = load_warrior_by_id(warrior_id)
    
    # Carry forward
    warrior["wins"] = warrior.get("wins", 0)
    warrior["losses"] = warrior.get("losses", 0)
    warrior["kills"] = warrior.get("kills", 0)
    # All stats, skills, equipment unchanged
    
    # Reset for new arena
    warrior["current_arena"] = target_arena
    warrior["recognition"] = 0
    warrior["tier"] = get_tier_name(0, target_arena)
    warrior["promoted_at_turn"] = current_turn
    warrior["promoted_arena"] = target_arena
    warrior["pending_promotion"] = None
    warrior["is_dead"] = False
    warrior["promoted_timestamp"] = datetime.now().isoformat()
    
    # If no permanent injuries yet, stay at 0
    # If has injuries from normal, keep them (but no new ones in elite/soul)
    
    save_warrior(warrior)
```

**Complete Field Specification for Resurrection (Dead → Soul Spire):**

```python
def resurrect_warrior(warrior_id: str, current_turn: int):
    """
    Resurrect dead warrior directly to Soul Spire.
    
    Fields that CARRY FORWARD (unchanged):
    - warrior_id, name, team_id, team_name, manager_id
    - stats (STR, DEX, CON, INT, PRE, SIZE)
    - wins, losses, kills (continuous total record - NOT reset)
    - skills, proficiencies
    - equipment (weapon, armor, helm)
    - injuries (from when they died - no new ones accumulated)
    - luck_modifier
    - race, gender, appearance
    
    Fields that RESET:
    - current_arena: dead → "soul"
    - recognition: any value → 0
    - tier: → DEATHLY RECRUITS
    - is_dead: true → false
    - hp: 0 or negative → full health
    - popularity: current value → reset to starting value
    - promoted_at_turn: set to current_turn
    - promoted_arena: set to "soul"
    - promoted_timestamp: current datetime
    - promotion_type: "resurrection" (not "promotion")
    """
    warrior = load_warrior_by_id(warrior_id)
    
    if not warrior.get("is_dead"):
        raise ValueError(f"Warrior {warrior_id} is not dead")
    
    # Carry forward (record continues, injuries persist)
    # Don't reset wins/losses/kills
    
    # Reset for resurrection
    warrior["current_arena"] = "soul"
    warrior["recognition"] = 0
    warrior["tier"] = get_tier_name(0, "soul")
    warrior["is_dead"] = False
    warrior["hp"] = get_max_hp(warrior)  # Full heal
    warrior["popularity"] = 0  # Reset to starting
    warrior["promoted_at_turn"] = current_turn
    warrior["promoted_arena"] = "soul"
    warrior["promoted_timestamp"] = datetime.now().isoformat()
    warrior["promotion_type"] = "resurrection"
    
    save_warrior(warrior)
```

### 9.4 Admin Resurrection Panel Implementation

**API Endpoint:**

```python
@app.post("/api/admin/resurrect")
async def resurrect_warriors(request_data: dict):
    """
    Bulk resurrect dead warriors to Soul Spire.
    
    Request body:
    {
      "warrior_ids": ["warrior_1", "warrior_2", ...],
      "target_arena": "soul"  (always "soul" for resurrections)
    }
    
    Response:
    {
      "status": "success",
      "resurrected_count": 3,
      "warriors": [
        {"warrior_id": "warrior_1", "name": "Bloodfang", "new_tier": "DEATHLY RECRUITS"},
        ...
      ]
    }
    """
    warrior_ids = request_data.get("warrior_ids", [])
    current_turn = load_current_turn("soul")
    
    resurrected = []
    for wid in warrior_ids:
        try:
            resurrect_warrior(wid, current_turn)
            warrior = load_warrior_by_id(wid)
            resurrected.append({
                "warrior_id": wid,
                "name": warrior["name"],
                "new_tier": warrior["tier"]
            })
        except Exception as e:
            print(f"Error resurrecting {wid}: {e}")
    
    return {
        "status": "success",
        "resurrected_count": len(resurrected),
        "warriors": resurrected
    }

@app.get("/api/admin/dead_warriors")
async def get_dead_warriors_filtered(
    min_fights: int = 0,
    min_win_rate: float = 0.0,
    max_win_rate: float = 1.0,
    manager_id: str = None
):
    """
    Get all dead warriors with optional filtering.
    
    Query params:
    - min_fights: minimum fight count before death
    - min_win_rate: minimum win % (0.0 to 1.0)
    - max_win_rate: maximum win % (0.0 to 1.0)
    - manager_id: filter by manager (optional)
    
    Response:
    {
      "dead_warriors": [
        {
          "warrior_id": "warrior_1",
          "name": "Bloodfang",
          "wins": 42,
          "losses": 18,
          "kills": 15,
          "win_rate": 0.70,
          "team_name": "At Sea",
          "manager_name": "John Doe",
          "manager_id": "manager_1",
          "died_turn": 50
        },
        ...
      ]
    }
    """
    warriors = load_warriors()
    dead = [w for w in warriors if w.get("is_dead")]
    
    # Filter by fight count
    dead = [w for w in dead if w.get("total_fights", 0) >= min_fights]
    
    # Filter by win rate
    for w in dead:
        total = w.get("wins", 0) + w.get("losses", 0)
        if total > 0:
            wr = w.get("wins", 0) / total
            if not (min_win_rate <= wr <= max_win_rate):
                dead.remove(w)
    
    # Filter by manager
    if manager_id:
        dead = [w for w in dead if w.get("manager_id") == manager_id]
    
    # Format response
    result = []
    for w in dead:
        total = w.get("wins", 0) + w.get("losses", 0)
        wr = w.get("wins", 0) / total if total > 0 else 0
        result.append({
            "warrior_id": w["warrior_id"],
            "name": w["name"],
            "wins": w.get("wins", 0),
            "losses": w.get("losses", 0),
            "kills": w.get("kills", 0),
            "win_rate": wr,
            "team_name": w.get("team_name"),
            "manager_name": w.get("manager_name"),
            "manager_id": w.get("manager_id"),
            "died_turn": w.get("died_turn", "unknown")
        })
    
    return {"dead_warriors": result}
```

### 9.5 Newsletter Generation (Arena-Aware)

**Main Function Signature:**

```python
def generate_newsletter(arena: str, turn_num: int, processed_date: str = None) -> str:
    """
    Generate arena-specific newsletter.
    
    Args:
        arena: "normal", "elite", or "soul"
        turn_num: Turn number for this arena
        processed_date: Optional date override
    
    Returns:
        Formatted newsletter text with arena-specific content
    """
    # Load arena-specific data
    teams = load_teams(arena)
    warriors = load_warriors(arena)  # Filtered by current_arena
    standings = load_standings(arena)
    card = load_turn_card(arena, turn_num)
    
    # Get arena-specific configuration
    arena_name = get_arena_name(arena)  # "The Agony Amphitheatre", "The Elite Spire", etc.
    arena_id = get_arena_id(arena)
    
    # Load previous champion state
    champion_state = load_champion_state(arena)
    prev_champion_state = load_previous_champion_state(arena)
    
    # Generate sections
    header = _header(arena_name, arena_id, turn_num, processed_date)
    standings_section = _team_standings(teams, turn_num, card)
    tiers_section = _warrior_tiers(teams, arena, champion_state, card, turn_num)
    fights_section = _fights_section(card, arena, champion_state, prev_champion_state)
    
    # Deaths only in Normal Arena
    deaths = load_deaths(arena, turn_num) if arena == "normal" else []
    dead_section = _dead_section(deaths, turn_num) if arena == "normal" else ""
    
    # Monster fights only in Normal Arena
    monster_section = _monster_kills_section(card) if arena == "normal" else ""
    
    # Blood challenges only in Normal Arena
    # (Already filtered in _fights_section by arena)
    
    race_report = _race_report(teams)
    
    # Combine all sections
    newsletter = "\n".join(filter(None, [
        header,
        standings_section,
        tiers_section,
        fights_section,
        dead_section,
        monster_section,
        race_report
    ]))
    
    return newsletter

def get_arena_name(arena: str) -> str:
    """Return display name for arena"""
    names = {
        "normal": "THE AGONY AMPHITHEATRE",
        "elite": "THE ELITE SPIRE",
        "soul": "THE SOUL SPIRE"
    }
    return names.get(arena, "UNKNOWN ARENA")

def get_arena_id(arena: str) -> int:
    """Return arena ID for display"""
    ids = {"normal": 1, "elite": 2, "soul": 3}
    return ids.get(arena, 0)

def load_turn_card(arena: str, turn_num: int) -> list:
    """Load fight card for specific arena and turn"""
    path = f"saves/{arena}/turn_{turn_num:02d}/fight_card.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []
```

**Modified Tier Function (Arena-Aware):**

```python
def _warrior_tier(warrior, is_champion: bool, arena: str) -> str:
    """Get full tier name with arena-specific prefix"""
    if is_champion:
        base_tier = "CHAMPION"
    else:
        recognition = getattr(warrior, "recognition", 0)
        if recognition >= 87:
            base_tier = "ELITES"
        elif recognition >= 71:
            base_tier = "EXPERTS"
        elif recognition >= 56:
            base_tier = "VETERANS"
        elif recognition >= 41:
            base_tier = "ADEPTS"
        elif recognition >= 26:
            base_tier = "INITIATES"
        elif recognition >= 13:
            base_tier = "ROOKIES"
        else:
            base_tier = "RECRUITS"
    
    prefix = TIER_PREFIXES.get(arena, "")
    return prefix + base_tier
```

### 9.6 Challenge and Scouting Filtering

**Challenge List Generation (Arena-Isolated):**

```python
def get_challenge_list(warrior_id: str, arena: str) -> list:
    """
    Get list of warriors this warrior can challenge (same arena only).
    """
    warrior = load_warrior_by_id(warrior_id)
    warrior_arena = warrior.get("current_arena")
    
    if warrior_arena != arena:
        return []  # Cannot challenge outside current arena
    
    # Get all warriors in same arena
    arena_warriors = [w for w in load_warriors(arena) if not w.get("is_dead")]
    
    # Get warrior's tier
    warrior_tier = get_tier_level(warrior.get("recognition", 0))  # 0-7 (RECRUITS to ELITES)
    
    # Challenge eligibility: same tier or one tier above
    valid_targets = []
    for target in arena_warriors:
        if target["warrior_id"] == warrior_id:
            continue  # Can't challenge self
        target_tier = get_tier_level(target.get("recognition", 0))
        if target_tier in [warrior_tier, warrior_tier + 1]:
            valid_targets.append(target)
    
    return valid_targets
```

**Scouting List Generation (Arena-Isolated):**

```python
def get_scouting_list(manager_id: str, arena: str) -> list:
    """
    Get list of warriors available for scouting (same arena, max 3 per arena).
    """
    # Get this manager's scouts for this arena
    scouts = load_manager_scouts(manager_id, arena)
    available_slots = 3 - len(scouts)
    
    if available_slots <= 0:
        return []  # No slots available
    
    # Get all unscouted warriors in this arena
    arena_warriors = load_warriors(arena)
    already_scouted_ids = {s["warrior_id"] for s in scouts}
    
    unscouted = [
        w for w in arena_warriors
        if w["warrior_id"] not in already_scouted_ids and not w.get("is_dead")
    ]
    
    return unscouted[:available_slots]
```

### 9.7 Multi-Arena Scheduler Setup

**Scheduler Initialization:**

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

class MultiArenaScheduler:
    def __init__(self):
        self.schedulers = {}
        self.turn_counters = {"normal": 0, "elite": 0, "soul": 0}
    
    def initialize_arena_scheduler(self, arena: str):
        """Initialize scheduler for a specific arena"""
        scheduler = AsyncIOScheduler()
        
        # Load arena configuration
        config = load_arena_config(arena)
        interval_hours = config.get("turn_interval_hours", 24)
        
        # Schedule the turn execution job
        job_id = f"{arena}_turn"
        scheduler.add_job(
            self.run_arena_turn,
            'interval',
            hours=interval_hours,
            args=[arena],
            id=job_id,
            name=f"Run {arena} arena turn"
        )
        
        self.schedulers[arena] = scheduler
        return scheduler
    
    async def run_arena_turn(self, arena: str):
        """Execute a turn for a specific arena"""
        if arena == "normal":
            await run_normal_arena_turn()
        elif arena == "elite":
            await run_elite_spire_turn()
        elif arena == "soul":
            await run_soul_spire_turn()
    
    def start_all_schedulers(self):
        """Start all three schedulers"""
        for arena in ["normal", "elite", "soul"]:
            if arena in self.schedulers:
                self.schedulers[arena].start()
    
    def manual_trigger_turn(self, arena: str):
        """Manually trigger a turn for specific arena"""
        return asyncio.run(self.run_arena_turn(arena))

# Initialize globally
multi_scheduler = MultiArenaScheduler()
multi_scheduler.initialize_arena_scheduler("normal")
multi_scheduler.initialize_arena_scheduler("elite")
multi_scheduler.initialize_arena_scheduler("soul")
multi_scheduler.start_all_schedulers()
```

**Arena Configuration File (league_config_{arena}.json):**

```json
{
  "arena": "elite",
  "arena_display_name": "The Elite Spire",
  "arena_id": 2,
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
    "training_difficulty_multiplier": 1.33,
    "peasant_scaling": 2.5,
    "injury_accumulation": false,
    "auto_resurrect_on_death": true
  },
  "tier_system": {
    "tier_prefix": "ADVANCED ",
    "tier_names": [
      "ADVANCED RECRUITS", "ADVANCED ROOKIES", "ADVANCED INITIATES",
      "ADVANCED ADEPTS", "ADVANCED VETERANS", "ADVANCED EXPERTS",
      "ADVANCED ELITES", "ADVANCED CHAMPION"
    ]
  },
  "promotion_criteria": {
    "min_fights": 40,
    "min_win_rate": 0.55,
    "allow_automatic_promotion": true
  }
}
```

### 9.8 Soul Spire Narrative Blocks

**New narrative blocks for Soul Spire newsletter (resurrection/ascension theme):**

```python
_BLK_SOUL_SPIRE_INTRO = [
    "The boundary between death and continuation proved permeable once again in The Soul Spire this turn. Warriors called back from the dead faced the arena anew, their resolve tested against opponents drawn from the same shadowed realm.",
    "Death released its grip on several souls this turn, and they found themselves resurrected in The Soul Spire to fight once more. The line between final defeat and another chance has become less clear with each passing cycle.",
    "The Soul Spire operated independently this turn, a realm where fallen warriors receive a chance at redemption. The resurrected tested themselves against one another, building new legacies from old stories.",
    "In The Soul Spire, death is not an ending but a transition. This turn, the resurrected warriors proved that legends can be written twice.",
    "The Soul Spire knows no permanent endings, only pauses and resurrections. This turn saw the resurrected warriors continue their eternal struggles.",
]

_BLK_SOUL_SPIRE_NOTABLE = [
    "• {warrior} continues their resurrected legacy with a {record} performance",
    "• {warrior} proves worthy of their resurrection with continued strength",
    "• The resurrected warriors of {team} show no sign of decline from their previous deaths",
    "• {warrior} reminds the arena why they were deemed worthy of resurrection",
    "• Another cycle complete in The Soul Spire—the resurrected endure",
]

_BLK_SOUL_SPIRE_WARRIOR_HI = [
    "The resurrection of {warrior} has proven judicious. Against {opponent}, {warrior} demonstrated that death could not diminish what made them dangerous.",
    "{warrior}'s continued excellence since resurrection suggests the selection was wise. {Opponent} discovered what the arena already knew.",
    "Death was merely an interruption in {warrior}'s story. The performance against {opponent} this turn proves the resurrected can still rise.",
    "{warrior} honors their resurrection with performances that justify the decision to bring them back. Against {opponent}, mastery was on full display.",
    "The resurrected {warrior} reminds the arena that some warriors refuse to fade, even after death. {Opponent} learned this lesson directly.",
]
```

**Usage in newsletter generation:**

```python
def _get_narrative_pool(arena: str, block_type: str):
    """Get appropriate narrative blocks for arena"""
    if arena == "soul":
        if block_type == "intro":
            return _BLK_SOUL_SPIRE_INTRO
        elif block_type == "notable":
            return _BLK_SOUL_SPIRE_NOTABLE
        elif block_type == "warrior_hi":
            return _BLK_SOUL_SPIRE_WARRIOR_HI
    elif arena == "normal":
        if block_type == "intro":
            return _BLK_INTRO
        elif block_type == "notable":
            return _BLK_NOTABLE  # (existing blocks)
        elif block_type == "warrior_hi":
            return _BLK_WARRIOR_HI  # (existing blocks)
    # ... etc for elite
    
    return []  # Fallback
```

### 9.9 API Endpoints Summary

**New/Modified Endpoints Required:**

```python
# NEWSLETTER
GET  /api/newsletter/{arena}/{turn}      # Get arena-specific newsletter
GET  /api/newsletters/available_turns/{arena}  # Get available turns for arena

# STANDINGS & DATA
GET  /api/standings/{arena}              # Get arena-specific standings
GET  /api/teams/{arena}                  # Get teams for specific arena
GET  /api/warriors/{arena}               # Get warriors for specific arena

# ADMIN CONTROLS
POST /api/admin/resurrect                # Bulk resurrect dead warriors
GET  /api/admin/dead_warriors            # Get dead warriors with filters
POST /api/admin/run_turn/{arena}         # Manually trigger turn for arena
POST /api/admin/clear_arena/{arena}      # Clear all data for arena

# CHALLENGES & SCOUTING
GET  /api/challenges/{warrior_id}/{arena}  # Get challenges for warrior in arena
GET  /api/scouting/{manager_id}/{arena}    # Get scouting options in arena
POST /api/scout/{manager_id}/{warrior_id}/{arena}  # Scout warrior in arena

# PROMOTION/RESURRECTION
POST /api/promote/{warrior_id}           # Promote warrior to elite
POST /api/resurrect/{warrior_id}         # Resurrect warrior to soul spire
```

### 9.10 Complete Warrior State Diagram

```
WARRIOR LIFECYCLE

┌─ NORMAL ARENA (Permanent Death Possible) ─────────────┐
│                                                       │
│  New Warrior (Turn 0)                                 │
│  ├─ current_arena: "normal"                           │
│  ├─ recognition: 0                                    │
│  ├─ tier: RECRUITS                                    │
│  ├─ is_dead: false                                    │
│  └─ wins/losses/kills: 0/0/0                          │
│         │                                             │
│         ├─ Fights in Normal (repeated)                │
│         │  ├─ Win: recognition +5-15, wins +1         │
│         │  ├─ Loss (survives): losses +1              │
│         │  └─ Loss (dies): is_dead = true ✗           │
│         │         │                                   │
│         │         ├─→ Blood Challenge Window (3 turns)│
│         │         └─→ Manager option: resurrection    │
│         │            (goes to Soul Spire)             │
│         │                                             │
│         └─ Promotion Eligible (40+ fights, 55%+ WR)   │
│            ├─ pending_promotion: "elite"              │
│            ├─ Final Mortal Fight (next turn)           │
│            ├─ Promoted to Elite                       │
│            │  (even if dies in final fight)           │
│            └─ All stats/record carry forward          │
│               recognition resets to 0                 │
└───────────────────────────────────────────────────────┘

┌─ ELITE SPIRE (No Permanent Death) ────────────────────┐
│                                                       │
│  Promoted Warrior (Turn N)                            │
│  ├─ current_arena: "elite"                            │
│  ├─ recognition: 0 (reset on promotion)               │
│  ├─ tier: ADVANCED RECRUITS                           │
│  ├─ is_dead: false                                    │
│  ├─ wins/losses/kills: (continuous from normal)       │
│  └─ injuries: (carry forward, no new ones)            │
│         │                                             │
│         └─ Fights in Elite (repeated)                 │
│            ├─ Win: recognition +5-15, wins +1         │
│            ├─ Loss: losses +1, auto-resurrect         │
│            └─ NEVER permanent death                   │
│               (hp restored, is_dead stays false)      │
└───────────────────────────────────────────────────────┘

┌─ SOUL SPIRE (Resurrection Arena - No Permanent Death) ┐
│                                                       │
│  Dead Warrior (selected by admin)                     │
│  ├─ current_arena: "soul"                             │
│  ├─ recognition: 0 (reset on resurrection)            │
│  ├─ tier: DEATHLY RECRUITS                            │
│  ├─ is_dead: false (resurrected)                      │
│  ├─ wins/losses/kills: (continuous - NOT reset)       │
│  ├─ injuries: (carry forward, no new ones)            │
│  └─ popularity: 0 (reset on resurrection)             │
│         │                                             │
│         └─ Fights in Soul Spire (repeated)            │
│            ├─ Win: recognition +5-15, wins +1         │
│            ├─ Loss: losses +1, auto-resurrect         │
│            └─ NEVER permanent death                   │
│               (hp restored, is_dead stays false)      │
└───────────────────────────────────────────────────────┘
```

---

## 12. KEY IMPLEMENTATION INVARIANTS

✅ Individual warrior records are **continuous** (never reset, accumulate across arenas)
✅ Team records are **per-arena** (separate records for Regular, Elite, Veteran)
✅ Team records are **fresh** (start at 0-0-0 per arena)
✅ Only warriors currently in an arena contribute to that arena's team record
✅ Promoted warriors stop contributing to old arena's team record immediately
✅ Team standings are per-arena (separate leaderboards)
✅ Warriors move one-way (Normal → Elite/Veteran, never backwards)
✅ Recognition resets to 0 on promotion (start fresh tier progression)
✅ Stats and skills carry forward unchanged
✅ Injuries at promotion persist, but no new injuries accumulate in elite/veteran
✅ No permanent death in elite/veteran (auto-resurrection)
✅ Blood challenges only in normal arena
✅ Monsters only in normal arena
✅ Training 33% harder in elite arena
✅ Peasant scaling higher in elite/veteran arenas
✅ Challenges and scouting isolated per arena
✅ Newsletters separate for each arena
✅ Data files separate for each arena

---

## 13. NEXT STEPS FOR IMPLEMENTATION

1. Update warrior data model (add current_arena field, record structure)
2. Update team data model (arena-specific records)
3. Create three separate scheduler instances
4. Split turn execution into three independent functions
5. Reorganize file storage by arena
6. Update frontend to add arena tabs and filter data
7. Implement arena-specific upload/download
8. Add arena isolation to challenges and scouting
9. Update newsletter generation (3 separate newsletters)
10. Implement admin resurrection panel
11. Implement admin arena clear functions
12. Update combat logic (death, resurrection, injuries)
13. Update matchmaking (arena filtering, peasant scaling)
14. Update promotions logic (eligibility, deferred promotion, data transfer)
15. Test complete flow: warrior progression through all arenas
