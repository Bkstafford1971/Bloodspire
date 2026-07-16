# Auto-Distribution of game_data.json via Turn Downloads

**Date:** 2026-07-14  
**Status:** ✓ IMPLEMENTED

## Summary

Modified `league_server.py` to automatically include `game_data` (with updated "Hand Axe" weapon) in every turn download. This ensures users always get the latest game data without needing to clear caches or reinstall.

## Changes Made

### 1. **Created Helper Function: `_build_game_data()` (line ~249)**

```python
def _build_game_data():
    """Build the game_data object (races, weapons, armor, skills, etc) for API endpoints.
    Used by /api/game_data and included in /api/results downloads."""
    from warrior import (...)
    from weapons import WEAPONS
    from armor import armor_selection_menu, helm_selection_menu
    from races import list_playable_races

    return {
        "weapons": sorted([w.display for w in WEAPONS.values()]),
        "armor": armor_selection_menu() + ["None"],
        "helms": helm_selection_menu() + ["None"],
        ... (remaining fields)
    }
```

**Benefits:**
- Single source of truth for game_data
- No code duplication
- Easy to maintain

### 2. **Updated `/api/game_data` Endpoint (line ~3647)**

**Before:**
```python
# 27 lines of inline code building the object
```

**After:**
```python
if path == "/api/game_data":
    # Static dropdown data the standalone client needs...
    self.send_json(_build_game_data()); return
```

**Benefit:** Cleaner, more maintainable code

### 3. **Updated `/api/results` Response (line ~3770)**

**Before:**
```python
self.send_json({
    "success": True, "results": team_results,
    "turn": res_turn, "has_newsletter": bool(nl_text),
    "deleted_teams": deleted_teams_list,
    "result": None
}); return
```

**After:**
```python
self.send_json({
    "success": True, "results": team_results,
    "turn": res_turn, "has_newsletter": bool(nl_text),
    "deleted_teams": deleted_teams_list,
    "game_data": _build_game_data(),  # Include updated game data with each download
    "result": None
}); return
```

## How It Works

### **Flow for Users Downloading Results:**

```
User clicks "Download League Data"
    ↓
Client sends: GET /api/results?manager_id=...&password=...
    ↓
Server processes results and builds response:
    ├─ team_results (fight outcomes)
    ├─ turn number
    ├─ newsletter text
    ├─ deleted_teams list
    └─ game_data ← NEW! Includes "Hand Axe"
    ↓
Client receives complete package
    ↓
Client caches game_data locally
    ↓
Client displays "Hand Axe" in weapon selection and skills
```

## Impact

### **Users Will See Updates When:**

1. **They download turn results** ✓ (Immediate - automatic with download)
2. **First install** ✓ (Automatic via /api/game_data)
3. **Clear cache and reload** ✓ (Automatic via /api/game_data)
4. **App update/reinstall** ✓ (Automatic)

### **Key Advantage for Test Environment:**

Users don't need to do anything special. When they:
- Download turn results → Get updated game_data
- Start app and fetch game_data → Get updated version
- Restart client after cache clear → Get updated version

No manual intervention required!

## Testing Checklist

- [x] league_server.py compiles without errors
- [x] _build_game_data() function created
- [x] /api/game_data endpoint uses helper
- [x] /api/results includes game_data in response
- [ ] Test download results from test league server
- [ ] Verify game_data includes "Hand Axe" (not "Fransisca")
- [ ] Verify client caches and displays correctly

## Deployment Notes

**No client changes needed!** The client already:
- Accepts game_data from server responses
- Caches data it receives
- Updates display when new data is cached

**Server-side only changes** - just update `league_server.py`

## Related Files

- `league_server.py` - Updated (this file)
- `weapons.py` - Already updated with display name
- `game_data.json` - Generated and ready (optional distribution)
- `bloodspire_client.html` - No changes needed

## File Sizes Impact

- Each `/api/results` response adds ~5.6 KB (game_data)
- Negligible bandwidth increase given typical download speeds
- Worth it for automatic data distribution

## Next Steps

1. Deploy updated `league_server.py` to test server
2. Test turn download to verify game_data is included
3. Verify client displays "Hand Axe" after download
4. Rollback old GitHub Pages files if needed (separate action)
