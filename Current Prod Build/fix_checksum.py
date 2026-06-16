#!/usr/bin/env python3
"""Fix the champion.json checksum."""

import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from file_protection import calculate_checksum

# Load champion.json
champ_path = os.path.join(BASE_DIR, 'saves', 'champion.json')
with open(champ_path, 'r', encoding='utf-8') as f:
    champ_data = json.load(f)

print("Champion data loaded:")
print(f"  Name: {champ_data.get('name')}")
print(f"  Team ID: {champ_data.get('team_id')}")

# Calculate correct checksum
correct_checksum = calculate_checksum(champ_data)
print(f"\nCorrect checksum: {correct_checksum}")

# Save the checksum
checksum_path = os.path.join(BASE_DIR, 'saves', 'champion.checksum')
with open(checksum_path, 'w', encoding='utf-8') as f:
    f.write(correct_checksum)

print(f"✓ Saved checksum to {checksum_path}")
