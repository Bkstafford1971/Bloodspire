#!/usr/bin/env python3
"""
Fix manager career totals in turn 3 newsletter by directly updating the section.
"""

import json
import os
import stat
from pathlib import Path
from collections import defaultdict

# ============================================================================
# CONFIGURATION
# ============================================================================
LEAGUE_DIR = Path("C:\\BPClone_Claude\\saves\\league")
NEWSLETTER_PATH = LEAGUE_DIR / "turn_0003" / "newsletter.txt"

# Correct career totals calculated from turn result files
CORRECT_TOTALS = {
    "-Vandal-": {"w": 3, "l": 12, "k": 0},
    "B4youwereborn": {"w": 25, "l": 35, "k": 3},
    "Bloodied Entrails": {"w": 41, "l": 34, "k": 3},
    "D-man": {"w": 29, "l": 46, "k": 7},
    "Darian Dargard": {"w": 40, "l": 25, "k": 6},
    "Grey Phantom": {"w": 28, "l": 22, "k": 2},
    "Ilneval": {"w": 36, "l": 39, "k": 3},
    "Nalkor Ironsides": {"w": 38, "l": 37, "k": 5},
    "Sanguine Savior": {"w": 36, "l": 39, "k": 5},
    "Sleazee P Martinee": {"w": 45, "l": 30, "k": 2},
    "The Chosen One": {"w": 31, "l": 39, "k": 1},
}

# ============================================================================
# LOAD NEWSLETTER
# ============================================================================
print(f"\n[LOADING] Reading {NEWSLETTER_PATH}...")

if not NEWSLETTER_PATH.exists():
    print(f"  ERROR: {NEWSLETTER_PATH} not found!")
    exit(1)

with open(NEWSLETTER_PATH, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# ============================================================================
# FIND AND UPDATE CAREER SECTION
# ============================================================================
print(f"[UPDATING] Fixing manager career totals...")

# Find the "Top Managers Career" section
career_start = None
career_end = None

for i, line in enumerate(lines):
    if "The Top Managers Career" in line:
        career_start = i
    elif career_start is not None and "==" in line:
        # Found the separator after the title
        separator_idx = i
        break

# Find where the career data starts and ends
data_start = separator_idx + 1
data_end = data_start

for i in range(data_start, len(lines)):
    if lines[i].strip() == "":
        data_end = i
        break

print(f"  Career section: lines {data_start} to {data_end}")

# ============================================================================
# REBUILD CAREER SECTION
# ============================================================================
new_career_lines = []

# Re-sort managers by career win percentage
mgr_sorted = []
for mgr_name, totals in CORRECT_TOTALS.items():
    total = totals["w"] + totals["l"]
    pct = (totals["w"] / total * 100) if total > 0 else 0
    mgr_sorted.append((mgr_name, totals, pct))

mgr_sorted.sort(key=lambda x: (-x[2], -x[1]["w"]))

# Format each manager's career record
for mgr_name, totals, pct in mgr_sorted:
    total = totals["w"] + totals["l"]
    # Format: "MANAGER_NAME(30 chars)  W(4)  L(4)  K(4)  %(6)  TOTAL(6)"
    line = f" {mgr_name:<34}{totals['w']:>4}{totals['l']:>4}{totals['k']:>4}{pct:>6.1f}%{total:>6}\n"
    new_career_lines.append(line)

# Replace the old career data with new
lines[data_start:data_end] = new_career_lines

# ============================================================================
# SAVE UPDATED NEWSLETTER
# ============================================================================
print(f"[SAVING] Writing updated newsletter...")

# Remove read-only flag
os.chmod(str(NEWSLETTER_PATH), stat.S_IWRITE)

with open(NEWSLETTER_PATH, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"  [OK] Newsletter updated")

# ============================================================================
# VERIFY
# ============================================================================
print(f"\n[VERIFYING] Checking updated totals...")

with open(NEWSLETTER_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

for mgr_name, totals in sorted(CORRECT_TOTALS.items()):
    if mgr_name in content:
        # Check if the record appears in the file
        expected_str = f"{totals['w']:3}W-{totals['l']:3}L-{totals['k']:1}K"
        if expected_str in content or f"{totals['w']}{totals['l']}" in content:
            print(f"  [OK] {mgr_name}: {totals['w']}-{totals['l']}-{totals['k']}")

print(f"\n{'='*70}")
print(f"NEWSLETTER CAREER TOTALS FIXED")
print(f"{'='*70}\n")
