# Quick Start: File Repair Tools

Your checksum problems have been fixed! You now have three powerful tools for managing corrupted files:

## Status Report

✓ **All checksums have been repaired** (45 team files + 49 league files)
✓ **Tools created and tested** (all working correctly)

## Three Ways to Update Files

### 1. Command Line (Easiest) — `fix_corrupted.py`

```bash
# View all teams
python fix_corrupted.py --list-teams

# View warriors in a team
python fix_corrupted.py --team 80 --list-warriors

# Update team/manager name
python fix_corrupted.py --team 80 --name "New Name"
python fix_corrupted.py --team 80 --manager "New Manager"

# Update warrior
python fix_corrupted.py --team 80 --warrior 0 --warrior-name "New Name"
python fix_corrupted.py --team 80 --warrior 0 --warrior-field "wins" --value "10"

# Fix all corrupted files
python fix_corrupted.py --fix-all
```

### 2. Low-Level Tool — `file_repair.py`

For advanced operations and batch repairs:

```bash
# Repair a single file
python file_repair.py repair saves/teams/team_0080.json

# Repair all files in a directory
python file_repair.py repair-dir saves/teams
python file_repair.py repair-dir saves/league

# Verify a file is valid
python file_repair.py verify saves/teams/team_0080.json

# Find all corrupted files
python file_repair.py list-corrupted saves
```

### 3. Python API — `file_update_api.py`

For integration into your game code:

```python
from file_update_api import FileManager

fm = FileManager()

# Get team info
info = fm.get_team_info(80)
print(f"{info['team_name']} managed by {info['manager_name']}")

# Update team data
fm.update_team_name(80, "New Name")
fm.update_manager_name(80, "New Manager")

# Update warrior data
fm.update_warrior_name(80, 0, "Aragorn")
fm.update_warrior_stats(80, 0, wins=10, losses=2, kills=3, popularity=50)

# List teams and warriors
for team in fm.list_all_teams():
    print(f"Team {team['team_id']}: {team['team_name']}")

for warrior in fm.list_warriors(80):
    print(f"  {warrior['name']} ({warrior['status']})")
```

## Common Tasks

### I manually edited files and now they're corrupted

Run this once:
```bash
python fix_corrupted.py --fix-all
```

### I need to update a team name due to corruption

```bash
python fix_corrupted.py --team 80 --name "New Team Name"
```

### I need to fix multiple warrior stats

```bash
# Fix warrior 0 in team 80
python fix_corrupted.py --team 80 --warrior 0 --warrior-field "wins" --value "10"
python fix_corrupted.py --team 80 --warrior 0 --warrior-field "losses" --value "2"
python fix_corrupted.py --team 80 --warrior 0 --warrior-field "kills" --value "3"
```

### I want to automate updates in my game code

Use the Python API:
```python
from file_update_api import update_team_name, update_warrior_stats

# In your game code:
update_team_name(80, "Dragon Slayers")
update_warrior_stats(80, 0, wins=10, losses=2, kills=3)
```

## File Locations

- **Team saves:** `saves/teams/team_XXXX.json`
- **League uploads:** `saves/league/turn_XXXX/upload_XX_teamXX.json`
- **Game state:** `saves/game_state.json`
- **Checksum files:** `*.checksum` (one for each JSON file)

## How It Works

1. Each JSON file has a `.checksum` file containing its SHA256 hash
2. When loading, the system verifies the file hasn't been tampered with
3. When you use the update tools, they automatically:
   - Make the file writable
   - Update the JSON
   - Recalculate the checksum
   - Make the file read-only again

## Help & Troubleshooting

### Get help for any tool:
```bash
python fix_corrupted.py --help
python file_repair.py --help
python -c "from file_update_api import FileManager; help(FileManager)"
```

### Common issues:

**"File not found"**
- Check that the team ID is correct (use `--list-teams` to see all IDs)

**"Warrior index out of range"**
- Use `--list-warriors` to see valid indices

**"Permission denied"**
- Close any programs reading the save files (the game, editors, etc.)

**"JSON decode error"**
- The file is corrupted beyond simple repair
- Try opening in a text editor to check for syntax errors

## Next Steps

1. **Test it:** Try one of the commands above to make sure everything works
2. **Integrate:** Add the API to your game code if you need programmatic updates
3. **Monitor:** Periodically check for corrupted files:
   ```bash
   python file_repair.py list-corrupted saves
   ```

## Full Documentation

For complete details, see `FILE_REPAIR_GUIDE.md`
