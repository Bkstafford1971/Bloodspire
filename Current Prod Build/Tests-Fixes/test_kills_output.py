#!/usr/bin/env python3
from arena_stats import _get_top_warriors_by_kills, _load_standings_data

standings = _load_standings_data()
warriors = _get_top_warriors_by_kills(standings)

print("Top 10 by kills:")
for i, w in enumerate(warriors, 1):
    record = f"{w['wins']}-{w['losses']}-{w['kills']}"
    print(f"{i:2}. {w['name']:20} {record:6} rec={w['recognition']:2} team={w['team']}")
    if 'SYRKYN' in w['name']:
        print(f"    ^^^ SYRKYN JHALEIN data: wins={w['wins']}, losses={w['losses']}, kills={w['kills']}")
