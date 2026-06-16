#!/usr/bin/env python3
import json

s = json.load(open('saves/league/standings.json'))

warrior_records = {}
for team_key, team_data in s.items():
    team_name = team_data.get("team_name", "?")
    for warrior_id, warrior_data in team_data.get("warriors", {}).items():
        name = warrior_data.get("name", "?")
        if name == "?" or not name:
            continue

        w = warrior_data.get("wins", 0)
        l = warrior_data.get("losses", 0)
        k = warrior_data.get("kills", 0)
        fights = warrior_data.get("fights", 0)

        entry = {
            "wins": w,
            "losses": l,
            "kills": k,
            "team": team_name,
            "fights": fights
        }

        # Keep the entry with the most fights (most recent/current data)
        if name not in warrior_records or fights > warrior_records[name]["fights"]:
            if name == "SYRKYN JHALEIN":
                print(f"Keeping {team_key}: {w}-{l}-{k} fights={fights}")
            warrior_records[name] = entry

print(f"\nFinal SYRKYN JHALEIN: {warrior_records.get('SYRKYN JHALEIN')}")
