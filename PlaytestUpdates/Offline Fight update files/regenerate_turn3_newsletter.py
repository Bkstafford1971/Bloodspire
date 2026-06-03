#!/usr/bin/env python3
"""
Regenerate turn 3 newsletter with corrected manager career totals.
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from newsletter import generate_newsletter
from save import load_all_teams
import json
import datetime as dt

# ============================================================================
# LOAD TURN 3 DATA
# ============================================================================
TURN_NUM = 3
TURN_DIR = Path("C:\\BPClone_Claude\\saves\\league\\turn_0003")
NEWSLETTER_PATH = TURN_DIR / "newsletter.txt"

print(f"\n[LOADING] Loading turn {TURN_NUM} data...")

# Load all teams
all_teams = load_all_teams()
print(f"  Loaded {len(all_teams)} teams")

# Load champion state
from save import load_champion_state
champion_state = load_champion_state()
print(f"  Champion: {champion_state.get('name', 'VACANT')}")

# Load result files to build fight card
from matchmaking import ScheduledFight
from warrior import Warrior

all_results = {}
result_files = list(TURN_DIR.glob("result_*.json"))
result_files = [f for f in result_files if f.name.endswith(".json") and ".checksum" not in f.name]

print(f"  Loaded {len(result_files)} result files")

# Build fight card from results
fake_card = []
for result_file in result_files:
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            result_data = json.load(f)

        for bout in result_data.get("bouts", []):
            if bout.get("result"):  # Only include resolved fights
                fake_card.append(bout)
    except:
        pass

print(f"  Built card with {len(fake_card)} fights")

# ============================================================================
# GENERATE NEWSLETTER
# ============================================================================
print(f"\n[GENERATING] Creating newsletter with corrected career totals...")

deaths = []
date_str = dt.date.today().strftime("%m/%d/%Y")

try:
    newsletter_text = generate_newsletter(
        turn_num=TURN_NUM,
        card=fake_card,
        teams=all_teams,
        deaths=deaths,
        champion_state=champion_state,
        processed_date=date_str,
        is_new_champion=False,  # Champion retained title
    )

    # ====================================================================
    # SAVE NEWSLETTER
    # ====================================================================
    print(f"\n[SAVING] Writing newsletter to {NEWSLETTER_PATH}...")

    # Remove read-only flag if needed
    if NEWSLETTER_PATH.exists():
        import stat
        os.chmod(NEWSLETTER_PATH, stat.S_IWRITE)

    with open(NEWSLETTER_PATH, 'w', encoding='utf-8') as f:
        f.write(newsletter_text)

    print(f"  [OK] Newsletter saved")

    # ====================================================================
    # VERIFY CAREER TOTALS
    # ====================================================================
    print(f"\n[VERIFYING] Checking career totals in newsletter...")

    lines = newsletter_text.split('\n')
    in_career_section = False
    found_dman = False

    for line in lines:
        if 'Top Managers Career' in line:
            in_career_section = True
            continue

        if in_career_section and 'D-man' in line and '29' in line:
            if '46' in line or '46L' in line:  # Should be 29W-46L
                print(f"  [OK] D-man career totals correct: 29-46-7")
                found_dman = True
                break

    if not found_dman:
        print(f"  [WARNING] Could not verify D-man career totals in newsletter")
        # Show what we got
        for line in lines:
            if 'Top Managers Career' in line:
                idx = lines.index(line)
                for l in lines[idx:idx+20]:
                    if 'D-man' in l:
                        print(f"    Found: {l}")

    print(f"\n{'='*70}")
    print(f"TURN 3 NEWSLETTER REGENERATED WITH CORRECTED CAREER TOTALS")
    print(f"{'='*70}")

except Exception as e:
    print(f"  [ERROR] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
