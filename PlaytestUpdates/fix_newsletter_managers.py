#!/usr/bin/env python3
"""Fix the TOP MANAGERS section of an existing newsletter."""

import json
import os
import sys
import re

LEAGUE_DIR = r"C:\BPClone_Claude\saves\league"

def _load_json(path, default=None):
    """Load JSON from file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default if default is not None else {}

def rebuild_top_managers_section(turn_num):
    """Rebuild the TOP MANAGERS section with corrected career records."""

    standings_path = os.path.join(LEAGUE_DIR, "standings.json")
    standings_data = _load_json(standings_path, {})

    if not standings_data:
        print("No standings data found")
        return None

    # Group teams by manager and calculate career records
    manager_records = {}

    # Calculate career records from standings (ALL teams ever managed)
    for match_id, standing_entry in standings_data.items():
        mgr_name = standing_entry.get("manager_name", "?")
        if mgr_name == "?" or mgr_name in {"The Monsters", "The Peasants"}:
            continue

        if mgr_name not in manager_records:
            manager_records[mgr_name] = {
                "career_wins": 0,
                "career_losses": 0,
                "career_kills": 0,
                "teams": []
            }

        # Sum wins/losses/kills from all warriors in this team
        warriors = standing_entry.get("warriors", {})
        for warrior_id, warrior_data in warriors.items():
            manager_records[mgr_name]["career_wins"] += warrior_data.get("wins", 0)
            manager_records[mgr_name]["career_losses"] += warrior_data.get("losses", 0)
            manager_records[mgr_name]["career_kills"] += warrior_data.get("kills", 0)

    # Build the TOP MANAGERS section
    lines = []
    lines.append("TOP MANAGERS")
    lines.append("="*85)
    lines.append("")
    lines.append(f"{'Manager':<30} {'This Turn':<25} {'Career':<25}")
    lines.append(f"{'-'*30} {'-'*25} {'-'*25}")
    lines.append("")

    # Sort by career win percentage
    sorted_managers = []
    for mgr_name, rec in manager_records.items():
        total_fights = rec["career_wins"] + rec["career_losses"]
        if total_fights > 0:
            career_pct = rec["career_wins"] / total_fights * 100
        else:
            career_pct = 0
        sorted_managers.append({
            "name": mgr_name,
            "career_pct": career_pct,
            "career_wins": rec["career_wins"],
            "career_losses": rec["career_losses"],
            "career_kills": rec["career_kills"],
            "total_fights": total_fights
        })

    sorted_managers.sort(key=lambda x: x["career_pct"], reverse=True)

    # Format the managers list
    for mgr in sorted_managers:
        name = mgr["name"][:28]
        career_record = f"{mgr['career_wins']}-{mgr['career_losses']}-{mgr['career_kills']}"
        win_pct = f"{mgr['career_pct']:.1f}%" if mgr['total_fights'] > 0 else "0%"

        line = f"{name:<30} {'0-0':<20} {career_record:<12} {win_pct}"
        lines.append(line)

    return "\n".join(lines)

def fix_newsletter(turn_num):
    """Fix the newsletter for a given turn."""
    turn_dir = os.path.join(LEAGUE_DIR, f"turn_{int(turn_num):04d}")
    newsletter_path = os.path.join(turn_dir, "newsletter.txt")

    if not os.path.exists(newsletter_path):
        print(f"Newsletter not found: {newsletter_path}")
        return

    # Load existing newsletter
    with open(newsletter_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find and replace TOP MANAGERS section
    pattern = r"TOP MANAGERS\n=+\n.*?(?=\n\n[A-Z]|\Z)"
    new_managers_section = rebuild_top_managers_section(turn_num)

    if new_managers_section:
        content = re.sub(pattern, new_managers_section, content, flags=re.DOTALL)

        # Save updated newsletter
        with open(newsletter_path, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"[OK] Newsletter updated for Turn {turn_num}")
        print(f"  File: {newsletter_path}")
        print("\n" + "="*85)
        print("TOP MANAGERS SECTION (UPDATED):")
        print("="*85)
        print(new_managers_section)
    else:
        print("Failed to rebuild TOP MANAGERS section")

if __name__ == "__main__":
    turn = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    fix_newsletter(turn)
