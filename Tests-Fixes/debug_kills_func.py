#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from arena_stats import _get_top_warriors_by_kills, _load_standings_data

standings = _load_standings_data()
warriors = _get_top_warriors_by_kills(standings)

for w in warriors:
    if w['name'] == 'SYRKYN JHALEIN':
        print(f"Found: {w}")
