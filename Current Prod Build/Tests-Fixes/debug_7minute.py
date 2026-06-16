#!/usr/bin/env python3
import arena_stats
import os

newsletter_path = os.path.join('saves', 'league', 'turn_0006', 'newsletter.txt')
recognition, teams = arena_stats._extract_warrior_data_from_newsletter(newsletter_path)

# Find 7 MINUTE ABS
names_with_7 = [name for name in recognition.keys() if '7' in name.upper()]
print("Warriors with '7' in name:")
for name in names_with_7:
    print(f"  {name}: rec={recognition.get(name)}, team={teams.get(name)}")

# Also check directly in file
print("\nSearching newsletter file directly:")
with open(newsletter_path, 'r') as f:
    for line in f:
        if '7 MINUTE' in line.upper():
            print(f"  {line.rstrip()}")
