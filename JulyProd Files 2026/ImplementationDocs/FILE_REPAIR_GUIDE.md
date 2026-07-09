# File Repair & Update Guide

This guide explains how to use the file repair tools to fix corrupted save files and safely update team, warrior, and manager data while maintaining proper checksums.

## Overview

BLOODSPIRE uses checksums to protect save files from tampering. When you manually edit JSON files, the checksums become invalid and the system prevents loading those files. These tools help you:

1. **Repair checksums** — Recalculate checksums for manually edited files
2. **Safely update files** — Modify files while automatically maintaining correct checksums
3. **Find corrupted files** — Identify which files have checksum mismatches
4. **Manage teams & warriors** — Update team/manager/warrior data through a simple interface

## Tools Included

### 1. `file_repair.py` — Low-level repair utility

This is the core tool that handles checksum calculations and file repairs.

#### Commands:

```bash
# Repair a single file's checksum
python file_repair.py repair <filepath>

# Repair all JSON files in a directory
python file_repair.py repair-dir <directory>

# Verify a file is not corrupted
python file_repair.py verify <filepath>

# Find all corrupted files in a directory
python file_repair.py list-corrupted <directory>

# Update a team file with new data
python file_repair.py update-team <filepath> --name "New Name" --manager "Manager Name"
```

#### Examples:

```bash
# Fix all team checksums
python file_repair.py repair-dir saves/teams

# Fix all league checksums
python file_repair.py repair-dir saves/league

# Check if a specific team is corrupted
python file_repair.py verify saves/teams/team_0080.json

# Find all corrupted files
python file_repair.py list-corrupted saves

# Update team 80's name
python file_repair.py update-team saves/teams/team_0080.json --name "Dragon Slayers"
```

### 2. `fix_corrupted.py` — User-friendly interface

This is the recommended tool for most operations. It provides an easy-to-use interface for updating teams and warriors.

#### Commands:

```bash
# Show all teams
python fix_corrupted.py --list-teams

# List warriors in a team
python fix_corrupted.py --team 80 --list-warriors

# Update team name
python fix_corrupted.py --team 80 --name "New Team Name"

# Update manager name
python fix_corrupted.py --team 80 --manager "New Manager Name"

# Update a warrior's name
python fix_corrupted.py --team 80 --warrior 0 --warrior-name "New Warrior Name"

# Update a warrior's specific field
python fix_corrupted.py --team 80 --warrior 0 --warrior-field "popularity" --value "50"

# Repair all corrupted files
python fix_corrupted.py --fix-all
```

#### Examples:

```bash
# List all teams in the system
python fix_corrupted.py --list-teams

# Show warriors in team 80
python fix_corrupted.py --team 80 --list-warriors

# Rename team 80
python fix_corrupted.py --team 80 --name "The Dragons"

# Rename the manager of team 80
python fix_corrupted.py --team 80 --manager "Dragon Master"

# Rename the first warrior (index 0) in team 80
python fix_corrupted.py --team 80 --warrior 0 --warrior-name "Aragorn"

# Increase warrior popularity
python fix_corrupted.py --team 80 --warrior 0 --warrior-field "popularity" --value "100"

# Fix wins, losses, kills for a warrior
python fix_corrupted.py --team 80 --warrior 0 --warrior-field "wins" --value "10"
python fix_corrupted.py --team 80 --warrior 0 --warrior-field "losses" --value "2"
python fix_corrupted.py --team 80 --warrior 0 --warrior-field "kills" --value "3"
```

## Workflow for Fixing Corrupted Files

### If you manually edited JSON files:

1. **Repair checksums** for all files:
   ```bash
   python fix_corrupted.py --fix-all
   ```

2. **Verify** the files are now valid:
   ```bash
   python file_repair.py verify saves/teams/team_0080.json
   python file_repair.py verify saves/league/turn_0001/upload_22_team80.json
   ```

3. The system should now load your files without errors.

### If you need to update a team due to corruption:

1. **View the team** to see current state:
   ```bash
   python fix_corrupted.py --team 80 --list-warriors
   ```

2. **Make updates** using the appropriate commands:
   ```bash
   # Update team name
   python fix_corrupted.py --team 80 --name "New Name"
   
   # Update manager
   python fix_corrupted.py --team 80 --manager "New Manager"
   
   # Fix warrior stats
   python fix_corrupted.py --team 80 --warrior 0 --warrior-field "wins" --value "5"
   ```

3. **Verify** your changes took effect by viewing the team again.

## How It Works

### Checksum System

The system uses SHA256 checksums to verify file integrity:

1. Each JSON file has a corresponding `.checksum` file (e.g., `team_0080.json` → `team_0080.checksum`)
2. When you load a file, the system verifies the checksum matches the file's content
3. If they don't match, the file is considered "tampered" and loading is blocked

### Safe Updates

When you use the update tools:

1. **Load** the current JSON data
2. **Apply** your updates to the data
3. **Make file writable** (temporarily)
4. **Write** the updated JSON to disk
5. **Recalculate** the SHA256 checksum
6. **Make file read-only** again

This ensures the checksum always matches the file content.

## Common Issues

### "File was tampered with! The checksum does not match"

This means the file content doesn't match its stored checksum. Solutions:

1. **If you manually edited the file**, run:
   ```bash
   python file_repair.py repair <filepath>
   ```

2. **If the file is corrupted**, use the update tool to fix specific fields:
   ```bash
   python fix_corrupted.py --team 80 --list-warriors
   # Then fix individual warriors as needed
   ```

### "File not found" when trying to update

Make sure:
- The team ID is correct (use `--list-teams` to see all teams)
- The file path is correct (use relative paths like `saves/teams/team_0080.json`)

### Warrior index out of range

The warrior index is the position in the team's array (0-indexed). Use `--list-warriors` to see which indices are occupied:

```bash
python fix_corrupted.py --team 80 --list-warriors
# Shows something like:
# Index  Name          Race           Status
# 0      Aragorn       Human          ACTIVE
# 1      Gimli         Dwarf          ACTIVE
# 2      Legolas       Elf            ACTIVE
```

## Advanced: Batch Updates

To update multiple warriors or teams, create a script:

```bash
#!/bin/bash

# Fix team 80
python fix_corrupted.py --team 80 --name "Dragon Slayers"
python fix_corrupted.py --team 80 --manager "Dragon Master"

# Fix warriors
python fix_corrupted.py --team 80 --warrior 0 --warrior-name "Aragorn"
python fix_corrupted.py --team 80 --warrior 1 --warrior-name "Gimli"
python fix_corrupted.py --team 80 --warrior 2 --warrior-name "Legolas"

echo "Done!"
```

## File Locations

- **Teams:** `saves/teams/team_XXXX.json`
- **League uploads:** `saves/league/turn_XXXX/upload_XX_teamXX.json`
- **Game state:** `saves/game_state.json`
- **Scouting:** `saves/scouting.json`
- **Monster team:** `saves/monster_team.json`

## Troubleshooting

### Tools say "No teams found"

This means either:
- The `saves/teams/` directory doesn't exist yet
- There are no `.json` files in that directory

### Permission denied errors

If you get permission errors:
- Close any programs that might be reading the save files (the game, editors, etc.)
- On Windows, make sure the file isn't marked as read-only in file properties

### JSON decode errors

The file is corrupted beyond repair. In this case:
- Try opening it in a text editor and checking for obvious syntax errors
- If you can't fix it, consider restoring from a backup

## Next Steps

After repairing your files:

1. **Verify** everything loads correctly by launching the game
2. **Keep backups** of important save files (before making updates)
3. **Check regularly** for corrupted files using:
   ```bash
   python file_repair.py list-corrupted saves
   ```

## Support

If you encounter issues:

1. Try running `python fix_corrupted.py --help` to see all available commands
2. Check the error messages carefully — they usually indicate what went wrong
3. Make sure you're in the correct directory (`C:\BPClone_Claude`)
4. Ensure Python 3.7+ is installed and available
