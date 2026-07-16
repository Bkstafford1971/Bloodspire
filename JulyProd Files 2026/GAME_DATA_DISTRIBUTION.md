# How Users Get the Updated game_data.json

## The Current Architecture

The BLOODSPIRE client uses a **cache-first** strategy for game data:

```
User launches client
    ↓
Client checks: Does game_data.json exist locally?
    ├─ YES → Use cached version (fast load)
    └─ NO  → Fetch from server: GET /api/game_data
            ↓
         Server returns JSON (includes "Hand Axe")
            ↓
         Client saves to local game_data.json
            ↓
         Client uses the data
```

## How Users Get the Updated Data

There are **four ways** users will receive the updated game_data.json with "Hand Axe":

### **Method 1: New Installation (GUARANTEED UPDATE)**
- **When:** User installs the app fresh or clears their app data
- **What happens:**
  - No cached `game_data.json` exists
  - Client automatically fetches from `/api/game_data` endpoint
  - Server returns the updated data with "Hand Axe"
  - File is cached locally
- **Status:** ✓ Automatic, no user action needed

### **Method 2: Manual Cache Clear (USER ACTION)**
- **When:** User manually deletes their `game_data.json` cache
- **Where file lives:**
  - Windows: `%AppData%\Local\BLOODSPIREClient\` (or similar app data folder)
  - Mac: `~/Library/Application Support/BLOODSPIREClient/`
  - Linux: `~/.config/BLOODSPIREClient/`
- **Steps:**
  1. User finds and deletes `game_data.json`
  2. Restarts the client
  3. Client fetches fresh from server
  4. Gets updated data with "Hand Axe"
- **Status:** Manual process, needs user intervention

### **Method 3: League Data Download (RECOMMENDED FOR ACTIVE USERS)**
- **When:** User downloads turn results via "Download League Data" button
- **What happens:**
  - User connects to league server
  - Downloads latest results
  - May trigger game data refresh
  - Gets latest game data if refresh is included
- **Status:** Semi-automatic for active league players

### **Method 4: App Update/Reinstall (GUARANTEED)**
- **When:** You push an app update or user reinstalls
- **What happens:**
  - Fresh app data folder created
  - No cached files exist
  - Client fetches all data from server
  - Gets updated "Hand Axe" version
- **Status:** Automatic with app updates

## The Server-Side Endpoint

The server endpoint that serves this data:

```python
# league_server.py, line 3616-3643
GET /api/game_data

Returns:
{
  "weapons": ["Axe", "Battle Axe", "Dagger", ..., "Hand Axe", ...],
  "armor": [...],
  "helms": [...],
  "races": [...],
  "styles": [...],
  ... (10 other fields)
}
```

**Key point:** This endpoint **automatically** returns "Hand Axe" because:
- It reads from `weapons.py`
- Which uses `w.display` field
- Which we already updated to "Hand Axe"
- ✓ No server code changes needed

## Recommended Distribution Strategy

### **For Immediate Updates to Active Users:**

1. **Include in next app release:**
   - Package the generated `game_data.json` with the app
   - When users update the app, fresh install gets new data
   - Cache is refreshed automatically

2. **Server-side (No code change needed):**
   - The `/api/game_data` endpoint already returns "Hand Axe"
   - Any user who clears cache or fetches fresh gets it
   - No server deployment needed

3. **Document for users:**
   - If someone has an old cached version, they can:
     - Delete `game_data.json` from their app folder and restart
     - Or uninstall/reinstall the app
     - Or download fresh league data

### **For Casual/Offline Users:**

Users who run the client offline with no server connection:
- Will continue using cached `game_data.json`
- Need to either:
  - Clear cache manually
  - Update/reinstall the app
  - Re-enable server connection to fetch fresh data

## Timeline Summary

| Scenario | When They Get Update | Status |
|----------|-------------------|--------|
| New user | First launch | ✓ Automatic |
| Existing user who clears cache | Next launch | ✓ Automatic |
| Existing user (no action) | Never (stuck with old cache) | ⚠ Manual action needed |
| User downloads app update | Next launch | ✓ Automatic |
| User downloads league data | During download if refresh triggered | ~ Depends on refresh logic |

## What We've Already Done

✓ Updated weapon display name in `weapons.py`  
✓ Generated `game_data.json` with "Hand Axe"  
✓ Verified server endpoint returns correct data  
✓ Server requires NO code changes (uses .display field)

## No Code Changes Needed on Server

The server-side `/api/game_data` endpoint is already **dynamic**:
- It reads from `WEAPONS` dictionary in weapons.py
- It uses the `display` field
- Since we updated the `display` field, the server automatically returns "Hand Axe"
- No server deployment needed

## Summary for Distribution

1. **Push the generated `game_data.json`** to your repo (optional but recommended)
2. **Include it in your app package** for next release
3. **No server code changes needed** (endpoint already dynamic)
4. **Old cached versions** will be replaced when users:
   - Clear cache
   - Update the app
   - Reinstall the app
   - Fetch fresh league data (if refresh is included)

The system is designed well - users get updates automatically unless they're offline and never clear their cache!
