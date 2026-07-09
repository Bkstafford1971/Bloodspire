# Champion Selection Tie-Breaker Implementation Plan

## Overview
Currently, when the current champion misses a turn (doesn't fight), the system evaluates warriors by recognition score alone. **If there's a tie in recognition, the spot becomes vacant.** We need to implement progressive tie-breakers to ensure a champion is always crowned.

---

## Current Flow (In newsletter.py: `_update_champion`)

```
RULE 1: Champion beaten in combat
  → Defeater becomes new champion immediately
  
RULE 2/3: No champion OR champion didn't fight
  → Find warrior with highest recognition
  → If TIE in recognition → VACANT THRONE (current behavior)
  
RULE 4: Champion fought this turn
  → Retain title (unless beaten in combat)
  → EXCEPTION: If Gladiatorial Commission strips title → follow RULES 2/3
```

---

## NEW Tie-Breaker Flow (RULES 2/3 ONLY)

When champion doesn't fight (or doesn't exist) and we need to select a new champion:

### Step 1: Get All Eligible Warriors
- Filter: active warriors, not dead, not ineligible
- Create list: `[(warrior_obj, team_name, team_id), ...]`

### Step 2: First Grouping - By Recognition (Highest Wins)
```python
all_warriors.sort(key=lambda x: (-recognition, ...))
best_rec = all_warriors[0].recognition
candidates = [w for w in all_warriors if w.recognition == best_rec]
```

### Step 3: Apply Tie-Breaker Chain
**If `len(candidates) == 1`:** Champion found → Return winner

**If `len(candidates) > 1`:** Apply tie-breakers in order:

#### Tie-Breaker #1: Most Kills
```python
candidates.sort(key=lambda x: (-kills, ...))
best_kills = candidates[0].kills
candidates = [w for w in candidates if w.kills == best_kills]
```
If `len(candidates) == 1` → Champion found → Return winner

#### Tie-Breaker #2: Most Wins
```python
candidates.sort(key=lambda x: (-wins, ...))
best_wins = candidates[0].wins
candidates = [w for w in candidates if w.wins == best_wins]
```
If `len(candidates) == 1` → Champion found → Return winner

#### Tie-Breaker #3: Fewest Losses
```python
candidates.sort(key=lambda x: (losses, ...))  # Note: ascending order
best_losses = candidates[0].losses
candidates = [w for w in candidates if w.losses == best_losses]
```
If `len(candidates) == 1` → Champion found → Return winner

#### Tie-Breaker #4: Highest Popularity
```python
candidates.sort(key=lambda x: (-popularity, ...))
best_pop = candidates[0].popularity
candidates = [w for w in candidates if w.popularity == best_pop]
```
If `len(candidates) == 1` → Champion found → Return winner

#### Tie-Breaker #5: Alphabetical (Warrior Name)
```python
candidates.sort(key=lambda x: x.name)
champion = candidates[0]
```
**This ensures we ALWAYS get a champion** (no more vacant thrones from excessive ties)

---

## Implementation Details

### Location
**File:** `newsletter.py`, function `_update_champion()` (currently lines 97-274)

### Changes Required

#### 1. Create Helper Function
New function: `_apply_tiebreakers(candidates: list) -> Optional[tuple]`

**Purpose:** Apply tie-breaker chain to a list of (warrior_obj, team_name, team_id) tuples

**Signature:**
```python
def _apply_tiebreakers(candidates: list) -> Optional[tuple]:
    """
    Apply tie-breaker chain: kills → wins → losses (ascending) → popularity → name.
    Returns: (warrior_obj, team_name, team_id) or None if no candidates
    """
```

**Algorithm:**
```python
def _apply_tiebreakers(candidates):
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    
    # Tie-breaker 1: Most Kills
    best_kills = max(getattr(c[0], 'kills', 0) for c in candidates)
    candidates = [c for c in candidates if getattr(c[0], 'kills', 0) == best_kills]
    if len(candidates) == 1:
        return candidates[0]
    
    # Tie-breaker 2: Most Wins
    best_wins = max(getattr(c[0], 'wins', 0) for c in candidates)
    candidates = [c for c in candidates if getattr(c[0], 'wins', 0) == best_wins]
    if len(candidates) == 1:
        return candidates[0]
    
    # Tie-breaker 3: Fewest Losses
    best_losses = min(getattr(c[0], 'losses', 0) for c in candidates)
    candidates = [c for c in candidates if getattr(c[0], 'losses', 0) == best_losses]
    if len(candidates) == 1:
        return candidates[0]
    
    # Tie-breaker 4: Highest Popularity
    best_pop = max(getattr(c[0], 'popularity', 0) for c in candidates)
    candidates = [c for c in candidates if getattr(c[0], 'popularity', 0) == best_pop]
    if len(candidates) == 1:
        return candidates[0]
    
    # Tie-breaker 5: Alphabetical by Name
    candidates.sort(key=lambda c: c[0].name)
    return candidates[0]
```

#### 2. Modify `_update_champion()` Function
**Section: RULES 2 & 3 (lines ~229-274)**

**Before (Current Logic):**
```python
# RULES 2 & 3: Find warrior with highest recognition
all_warriors = [...]  # [warrior, team_name, team_id], sorted by recognition

# Get the highest recognition score
best_rec = all_warriors[0].recognition

# Check if there's a tie for highest recognition
tied = [x for x in all_warriors if x[0].recognition == best_rec]

if len(tied) > 1:
    # THERE IS A TIE - Leave spot vacant
    is_new = (prev_champ != "")
    return {}, is_new

# NO TIE - Award to the warrior with highest recognition
champ_w, champ_t, champ_tid = all_warriors[0]
new_state = {...}
return new_state, is_new
```

**After (New Logic with Tie-Breakers):**
```python
# RULES 2 & 3: Find warrior with highest recognition
all_warriors = [...]  # [warrior, team_name, team_id]

# Get the highest recognition score
if not all_warriors:
    return {}, False

best_rec = getattr(all_warriors[0][0], 'recognition', 0)

# Get all warriors tied at highest recognition
tied = [x for x in all_warriors if getattr(x[0], 'recognition', 0) == best_rec]

if len(tied) > 1:
    # Multiple warriors with same highest recognition - apply tie-breakers
    result = _apply_tiebreakers(tied)
    if result:
        champ_w, champ_t, champ_tid = result
        new_state = {"name": champ_w.name, "warrior_id": getattr(champ_w, 'warrior_id', None),
                     "team_name": champ_t, "team_id": champ_tid, "source": "recognition_tiebreak"}
        is_new = (champ_w.name != prev_champ)
        print(f"[DEBUG CHAMPION] Tie-breaker awarded champion: {champ_w.name} (kills={getattr(champ_w,'kills',0)}, wins={getattr(champ_w,'wins',0)})")
        return new_state, is_new
    else:
        return {}, (prev_champ != "")
else:
    # No tie - single highest recognition warrior
    champ_w, champ_t, champ_tid = tied[0]
    new_state = {"name": champ_w.name, "warrior_id": getattr(champ_w, 'warrior_id', None),
                 "team_name": champ_t, "team_id": champ_tid, "source": "recognition"}
    is_new = (champ_w.name != prev_champ)
    print(f"[DEBUG CHAMPION] Champion {champ_w.name} awarded by recognition")
    return new_state, is_new
```

---

## Data Fields Verified

From `warrior.py`, warriors have these fields available:
- `recognition` (int) - Base metric for champion selection
- `kills` (int) - Tie-breaker #1
- `wins` (int) - Tie-breaker #2
- `losses` (int) - Tie-breaker #3
- `popularity` (int) - Tie-breaker #4
- `name` (str) - Tie-breaker #5 (alphabetical)

All fields are accessible via `getattr()` with fallback defaults to 0.

---

## Edge Cases Handled

1. **Empty Candidate List:** Returns empty state (no eligible warriors)
2. **Excessive Ties:** Alphabetical order ensures ALWAYS a champion at the end
3. **Null/Missing Fields:** `getattr()` with default 0 prevents errors
4. **Logging:** Each step logs the tie-breaker decision for debugging

---

## Backward Compatibility

- **Source Field:** New tie-breaker path uses `"source": "recognition_tiebreak"` vs. `"source": "recognition"` for easier tracking
- **Behavior Change:** Previously vacant throne → Now always crowned champion (improvement)
- **API Response:** No change to API structure or external interfaces

---

## Testing Scenarios

### Scenario 1: No Tie
- Warriors A, B, C with recognitions 45, 30, 20
- **Result:** A crowned (no tie-breaker needed)

### Scenario 2: Tie Resolved by Kills
- Warriors A, B both at recognition 40
- A has 15 kills, B has 10 kills
- **Result:** A crowned (kills tie-breaker)

### Scenario 3: Multiple Tie-Breakers
- Warriors A, B, C all at recognition 40 and 15 kills
- A has 25 wins, B has 25 wins, C has 20 wins
- A has 8 losses, B has 6 losses, C has 7 losses
- **Result:** B crowned (fewest losses among tied at kills & wins)

### Scenario 4: Name-Based Resolution
- Warriors "Alice" and "Bob" tied through all metrics (recognition, kills, wins, losses, popularity)
- **Result:** "Alice" crowned (alphabetical)

---

## Summary of Changes

| Section | Change | Impact |
|---------|--------|--------|
| `_apply_tiebreakers()` | NEW function | Applies 5-level tie-breaker chain |
| `_update_champion()` | Modified logic | Uses tie-breaker chain instead of returning vacant state |
| Debug output | Enhanced | Logs which tie-breaker resolved the selection |
| Source field | New value | `"recognition_tiebreak"` marks tie-breaker crowning |

---

## Approval Checklist

- [ ] Flow makes logical sense for the game
- [ ] Tie-breaker order is correct (recognition → kills → wins → losses → popularity → name)
- [ ] All warrior fields are available and accessible
- [ ] Implementation won't break existing champion retention rules
- [ ] Logging is clear for debugging

