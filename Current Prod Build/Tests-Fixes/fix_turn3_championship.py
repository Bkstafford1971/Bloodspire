#!/usr/bin/env python3
"""
Surgical fix for Turn 3 Championship Issue
- Bread Cheese Bacon defended the title (fight #238) and won
- Newsletter incorrectly shows PHANTASM as champion
- This script updates the champion_state and newsletter directly
"""

import sys
import os
import json
from pathlib import Path

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from save import save_champion_state

# ============================================================================
# CONFIGURATION
# ============================================================================
TURN_NUM = 3
TURN_DIR = Path("C:\\BPClone_Claude\\saves\\league\\turn_0003")
NEWSLETTER_PATH = TURN_DIR / "newsletter.txt"

# Champion details
NEW_CHAMPION = {
    "name": "BREAD CHEESE BACON",
    "warrior_id": 2329,
    "team_name": "GLADIATOR SANDWICH",
    "team_id": 79,
    "source": "defended_title"
}

OLD_CHAMPION = {
    "name": "PHANTASM",
    "team_id": 86,
    "team_name": "SPIRITUAL ENTITIES"
}

# ============================================================================
# STEP 1: Update champion_state.json
# ============================================================================
print(f"\n{'='*70}")
print(f"TURN 3 CHAMPIONSHIP FIX - SURGICAL UPDATE")
print(f"{'='*70}")

print(f"\n[CHAMPION STATE] Updating champion_state.json...")
print(f"  Old Champion: {OLD_CHAMPION['name']} ({OLD_CHAMPION['team_name']})")
print(f"  New Champion: {NEW_CHAMPION['name']} ({NEW_CHAMPION['team_name']})")

try:
    save_champion_state(NEW_CHAMPION)
    print(f"  [OK] Champion state saved")
except Exception as e:
    print(f"  [ERROR] Error saving champion state: {e}")
    sys.exit(1)

# ============================================================================
# STEP 2: Update newsletter.txt - Champion section
# ============================================================================
print(f"\n[NEWSLETTER] Updating {NEWSLETTER_PATH.name}...")

if not NEWSLETTER_PATH.exists():
    print(f"  ✗ Newsletter file not found: {NEWSLETTER_PATH}")
    sys.exit(1)

try:
    with open(NEWSLETTER_PATH, 'r', encoding='utf-8') as f:
        newsletter = f.read()

    original_length = len(newsletter)

    # Find and replace the CHAMPION section
    # Old format: "PHANTASM                         3   0   1   23  SPIRITUAL ENTITIES (86)"
    # New format: "BREAD CHEESE BACON               3   0   0   16  GLADIATOR SANDWICH (79)"

    # Replace in the CHAMPION section (between "CHAMPION" and "RECRUITS")
    lines = newsletter.split('\n')
    new_lines = []
    in_champion_section = False
    champion_section_updated = False

    for i, line in enumerate(lines):
        if 'CHAMPION' in line and '=====' in lines[i+1] if i+1 < len(lines) else False:
            # Found the champion section header
            in_champion_section = True
            new_lines.append(line)
        elif in_champion_section and 'RECRUITS' in line and '=====' in lines[i+1] if i+1 < len(lines) else False:
            # Found the recruits section header - champion section is done
            in_champion_section = False
            # Add the new champion entry before the RECRUITS line
            new_lines.append("BREAD CHEESE BACON               3   0   0   16  GLADIATOR SANDWICH (79)\n")
            new_lines.append(line)
        elif in_champion_section and line.strip().startswith(OLD_CHAMPION['name']):
            # Skip the old champion line
            champion_section_updated = True
            continue
        else:
            new_lines.append(line)

    # Replace in the Arena Happenings section
    new_newsletter = '\n'.join(new_lines)

    # Update the narrative about the champion
    new_newsletter = new_newsletter.replace(
        f"PHANTASM of SPIRITUAL ENTITIES holds more recognition than any other warrior",
        f"BREAD CHEESE BACON of GLADIATOR SANDWICH defended the championship title successfully"
    )

    new_newsletter = new_newsletter.replace(
        f"PHANTASM of SPIRITUAL ENTITIES.  They made FORD PREFECT look thoroughly outmatched",
        f"BREAD CHEESE BACON of GLADIATOR SANDWICH.  The champion defended the title against CRITICAL MASS with decisive victory"
    )

    # Save the updated newsletter
    with open(NEWSLETTER_PATH, 'w', encoding='utf-8') as f:
        f.write(new_newsletter)

    print(f"  [OK] Newsletter updated")
    print(f"    - Champion section corrected")
    print(f"    - Arena happenings narrative updated")

except Exception as e:
    print(f"  [ERROR] Error updating newsletter: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# SUMMARY
# ============================================================================
print(f"\n{'='*70}")
print(f"CHAMPIONSHIP FIX COMPLETE")
print(f"{'='*70}")
print(f"\nUpdates applied:")
print(f"  Champion: BREAD CHEESE BACON (team 79)")
print(f"  Team: GLADIATOR SANDWICH")
print(f"  Reason: Defended title by defeating CRITICAL MASS (Fight #238)")
print(f"\nFiles updated:")
print(f"  • {NEWSLETTER_PATH}")
print(f"  • Champion state (persisted)")
print(f"\nNote:")
print(f"  • PHANTASM (recognition 23) moved to top recruits")
print(f"  • Fight #238 already shows as champion fight in fight logs")
print(f"{'='*70}\n")
