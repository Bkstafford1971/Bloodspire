#!/usr/bin/env python3
"""
Generate game_data.json file for client distribution.
This matches the /api/game_data endpoint in league_server.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from warrior import (
    ATTRIBUTES, FIGHTING_STYLES, TRIGGERS, AIM_DEFENSE_POINTS,
    NON_WEAPON_SKILLS, WEAPON_SKILLS,
)
from weapons import WEAPONS
from armor import armor_selection_menu, helm_selection_menu
from races import list_playable_races

def generate_game_data():
    """Generate the game_data.json structure"""
    game_data = {
        "weapons": sorted([w.display for w in WEAPONS.values()]),
        "armor": armor_selection_menu() + ["None"],
        "helms": helm_selection_menu() + ["None"],
        "triggers": TRIGGERS,
        "styles": FIGHTING_STYLES,
        "aim_points": AIM_DEFENSE_POINTS,
        "races": list_playable_races(),
        "genders": ["Male", "Female"],
        "attributes": ATTRIBUTES,
        "non_weapon_skills": NON_WEAPON_SKILLS,
        "weapon_skills": sorted(WEAPON_SKILLS),
        "train_skills": sorted(
            ["Strength", "Dexterity", "Constitution", "Intelligence", "Presence"] +
            [s.replace("_", " ").title() for s in NON_WEAPON_SKILLS] +
            [w.display for w in WEAPONS.values()]
        ),
    }
    return game_data

def main():
    """Generate and save game_data.json"""
    print("Generating game_data.json...")
    print("-" * 70)

    game_data = generate_game_data()

    # Save to file
    output_path = Path(__file__).parent / "game_data.json"
    with open(output_path, "w") as f:
        json.dump(game_data, f, indent=2)

    print(f"[OK] Generated game_data.json at: {output_path}")
    print()

    # Verify Hand Axe is in weapons list
    weapons = game_data["weapons"]
    print(f"Total weapons in game_data: {len(weapons)}")
    print()

    if "Hand Axe" in weapons:
        print("[OK] 'Hand Axe' found in weapons list")
        idx = weapons.index("Hand Axe")
        print(f"     Position: {idx + 1} of {len(weapons)}")
        print(f"     Context: {weapons[max(0, idx-2):idx+3]}")
    else:
        print("[FAIL] 'Hand Axe' NOT found in weapons list")
        return False

    if "Fransisca" in weapons:
        print("[FAIL] Old 'Fransisca' still in weapons list")
        return False
    else:
        print("[OK] Old 'Fransisca' removed from weapons list")

    print()
    print("=" * 70)
    print(f"game_data.json successfully generated and ready for distribution")
    print("=" * 70)
    print()
    print("Next steps:")
    print("1. Copy game_data.json to your client distribution folder")
    print("2. Push to your repository if version control is used")
    print("3. Users will load the updated file on next client launch")

    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
