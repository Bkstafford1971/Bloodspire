#!/usr/bin/env python3
import json, os

config_path = os.path.join('saves', 'league', 'config.json')
with open(config_path) as f:
    config = json.load(f)
    print(f'Current turn: {config["current_turn"]}')

# Check which newsletter files exist
league_dir = os.path.join('saves', 'league')
for i in range(10, 0, -1):
    path = os.path.join(league_dir, f'turn_{i:04d}', 'newsletter.txt')
    if os.path.exists(path):
        print(f'Most recent newsletter: turn_{i:04d}')
        break
