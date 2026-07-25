#!/usr/bin/env python3
"""
Character Sheet Generator for BLOODSPIRE Gladiators
Generates HTML and PDF character sheets for all warriors across all teams.
Each warrior gets their own character sheet: TEAM_NAME_WARRIOR_NAME.html/.pdf
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

# Embedded race data for standalone operation
RACE_DATA = {
    "Human": {
        "description": "The adaptable everyman. No extreme strengths or weaknesses, but supremely adaptable. Humans train attributes more easily and suffer fewer permanent injuries.",
        "bonuses": ["Fast Training: Attributes improve more quickly", "Injury Resistance: Lower chance of permanent injuries"],
        "penalties": [],
    },
    "Half-Orc": {
        "description": "Pure brute force. Devastating damage and high durability, but slow, clumsy, and easy to outmaneuver.",
        "bonuses": ["Damage Bonus: +5", "HP Bonus: +6"],
        "penalties": ["Initiative Penalty: -2", "Dodge Penalty: -3", "Parry Penalty: -2"],
    },
    "Halfling": {
        "description": "Infuriatingly hard to hit. Extremely fast and mobile, but extremely fragile with very light damage output.",
        "bonuses": ["Dodge Bonus: +7", "Attack Rate Bonus: +4", "Martial Combat Bonus: Extra effectiveness in hand-to-hand"],
        "penalties": ["Damage Penalty: -2", "Parry Penalty: -3", "HP Penalty: -2"],
    },
    "Dwarf": {
        "description": "The ultimate tank. Absorbs massive punishment and parries masterfully, but very slow and poor at dodging.",
        "bonuses": ["HP Bonus: +8", "Damage Bonus: +3", "Parry Bonus: +3", "Armor Capacity Bonus: Can wear heavier armor", "Shield Bonus: Extra protection with shields"],
        "penalties": ["Attack Rate Penalty: -2", "Dodge Penalty: -4"],
    },
    "Half-Elf": {
        "description": "Versatile and capable. Slight edge in weapon handling with no major weaknesses or strengths.",
        "bonuses": ["Bigger Weapons: Can wield heavier weapons more easily", "Attack Rate Bonus: +1", "Dodge Bonus: +2", "Damage Bonus: +1"],
        "penalties": [],
    },
    "Elf": {
        "description": "Elusive speed demons. Masters of dual-wielding and evasion, but extremely fragile.",
        "bonuses": ["Dodge Bonus: +5", "Parry Bonus: +5", "Attack Rate Bonus: +5", "Dual Weapon Bonus: Enhanced dual-wield attacks"],
        "penalties": ["HP Penalty: -2"],
    },
    "Goblin": {
        "description": "Tiny dirty fighters. Extremely fast and tricky with thrown weapons, but very weak and fragile.",
        "bonuses": ["Attack Rate Bonus: +5", "Initiative Bonus: +5", "Dodge Bonus: +4", "Thrown Mastery: Bonus to throwing attacks", "Scavenger: Can pick up dropped weapons during combat"],
        "penalties": ["Damage Penalty: -2", "HP Penalty: -3", "Strength Penalty: -4", "Heavy Weapon Penalty: Heavy weapons incur penalties"],
    },
    "Gnome": {
        "description": "Small, surprisingly tough tacticians. Excel at counterstrikes and turning aggression against opponents.",
        "bonuses": ["HP Bonus: +5", "Fast Training: Attributes improve more quickly", "Parry Bonus: +5", "Counterstrike Mastery: Strong ripostes after successful parries", "Tactician's Edge: Better vs aggressive foes, worse vs methodical", "Dodge Bonus: +2"],
        "penalties": ["Damage Penalty: -2", "Attack Rate Penalty: -1"],
    },
    "Lizardfolk": {
        "description": "Savage reptilian predators. Tough, relentless, with natural armor and weapons, but cold-blooded and slower to accelerate.",
        "bonuses": ["HP Bonus: +6", "Natural Armor: Scales provide innate armor protection", "Natural Weapons: Bonus damage with claws and natural attacks", "Martial Combat Bonus: Extra effectiveness in hand-to-hand", "Dodge Bonus: +2"],
        "penalties": ["Attack Rate Penalty: -1"],
    },
    "Tabaxi": {
        "description": "Lightning-quick acrobatic felines. Best evasion in the game, but fragile and tire quickly in long fights.",
        "bonuses": ["Dodge Bonus: +7", "Initiative Bonus: +5", "Acrobatic Advantage: Highly resistant to knockdowns", "Frenzy: Once per fight, gain +3 attack rate burst (3-4 actions)", "Spear Mastery: Spears exempt from heavy weapon penalties"],
        "penalties": ["HP Penalty: -2", "Heavy Weapon Penalty: Heavy weapons incur penalties"],
    },
}

# Try to import PDF libraries
try:
    from xhtml2pdf import pisa
    HAS_XHTML2PDF = True
except ImportError:
    HAS_XHTML2PDF = False

try:
    import weasyprint
    HAS_WEASYPRINT = True
except ImportError:
    HAS_WEASYPRINT = False

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


def get_user_paths():
    """Get saves directory from command-line argument or prompt user."""
    print("=" * 60)
    print("CHARACTER SHEET GENERATOR - PATH CONFIGURATION")
    print("=" * 60)
    print("\nThis tool generates character sheets for YOUR warriors only.")
    print("It reads from your personal saves directory.\n")

    saves_path = None

    # Check if path was provided as command-line argument
    if len(sys.argv) > 1:
        saves_path = sys.argv[1].strip()
        print(f"Using path from command line: {saves_path}\n")
    else:
        # Prompt user for path
        while True:
            saves_path = input("Enter your Bloodspire saves directory path\n(e.g., C:\\BloodspireChosenOne): ").strip()
            if saves_path:
                break
            print("Error: Please enter a path.")

    saves_path = os.path.expanduser(saves_path)

    # Validate the path
    while True:
        if not os.path.isdir(saves_path):
            print(f"\nError: Directory not found: {saves_path}")
            print("Please enter a valid directory path.")
            saves_path = input("Try again: ").strip()
            saves_path = os.path.expanduser(saves_path)
            continue

        # Check for teams subdirectory
        teams_path = os.path.join(saves_path, "teams")
        if not os.path.isdir(teams_path):
            print(f"\nError: Teams directory not found at {teams_path}")
            print("Make sure you selected your Bloodspire saves folder (not the teams subfolder).")
            saves_path = input("Try again: ").strip()
            saves_path = os.path.expanduser(saves_path)
            continue

        # Check if any team files exist
        team_files = [f for f in os.listdir(teams_path) if f.startswith('team_') and f.endswith('.json')]
        if not team_files:
            print(f"\nWarning: No team files found in {teams_path}")
            if len(sys.argv) > 1:
                # If path came from command line, treat missing files as error
                print("Error: No team files found.")
                sys.exit(1)
            else:
                confirm = input("Continue anyway? (y/n): ").strip().lower()
                if confirm != 'y':
                    saves_path = input("Try again: ").strip()
                    saves_path = os.path.expanduser(saves_path)
                    continue

        break

    # Set output directory within saves folder
    output_path = os.path.join(saves_path, "character_sheets")

    try:
        os.makedirs(output_path, exist_ok=True)
        print(f"Output directory: {output_path}\n")
    except Exception as e:
        print(f"\nError: Could not create output directory: {e}")
        print("Make sure you have write permissions to this folder.")
        sys.exit(1)

    return teams_path, output_path


TEAMS_DIR, OUTPUT_DIR = get_user_paths()


def load_json_file(filepath):
    """Load and return JSON file contents."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return None


def get_attribute_description(stat_name, stat_value):
    """Get a human-readable description for an attribute value."""
    descriptions = {
        "strength": {
            (3,  3):  "Jelly-fish like",
            (4,  6):  "Is of feeble strength",
            (7,  8):  "Is of weak strength",
            (9,  11): "Is of ordinary strength",
            (12, 13): "Is of sturdy strength",
            (14, 16): "Is of muscular strength",
            (17, 18): "Is of formidable strength",
            (19, 21): "Is of powerful strength",
            (22, 23): "Is of Mighty strength",
            (24, 25): "Possesses Beastly strength",
        },
        "dexterity": {
            (3,  3):  "Has inert movements",
            (4,  6):  "Has sluggish movements",
            (7,  8):  "Has slow movements",
            (9,  11): "Has stable movements",
            (12, 13): "Has quick movements",
            (14, 16): "Has agile movements",
            (17, 18): "Has nimble movements",
            (19, 21): "Has swift movements",
            (22, 23): "Has blur-like movements",
            (24, 25): "Has lightning quick movements",
        },
        "constitution": {
            (3,  3):  "Has a Flimsy constitution",
            (4,  6):  "Has a puny constitution",
            (7,  8):  "Has a frail constitution",
            (9,  11): "Has a delicate constitution",
            (12, 13): "Has a healthy constitution",
            (14, 16): "Has a tough constitution",
            (17, 18): "Has a brawny constitution",
            (19, 21): "Has a resilient constitution",
            (22, 23): "Has a rugged constitution",
            (24, 25): "Has iron-like constitution",
        },
        "intelligence": {
            (3,  3):  "Is as Dumb as a bedpost",
            (4,  6):  "Sometimes forgets to breathe",
            (7,  8):  "Is just plain dumb",
            (9,  11): "Depends on muscle over mind",
            (12, 13): "Has average intelligence",
            (14, 16): "Is fairly bright",
            (17, 18): "Is a quick thinker",
            (19, 21): "Is a gifted strategist",
            (22, 23): "Possesses great intellect",
            (24, 25): "Is a genius",
        },
        "presence": {
            (3,  3):  "Has no presence whatsoever",
            (4,  6):  "Is easily overlooked",
            (7,  8):  "Makes little impression",
            (9,  11): "Is somewhat noticed",
            (12, 13): "Commands some attention",
            (14, 16): "Has a notable presence",
            (17, 18): "Is quite impressive",
            (19, 21): "Commands great respect",
            (22, 23): "Is supremely commanding",
            (24, 25): "Is a legendary figure",
        },
        "size": {
            (3,  3):  "Is grossly thin",
            (4,  6):  "Could blow away in the wind",
            (7,  8):  "Has a slight build",
            (9,  11): "Has a wiry frame",
            (12, 13): "Is of average build",
            (14, 16): "Is somewhat large",
            (17, 18): "Has a large frame",
            (19, 21): "Is a huge and imposing figure",
            (22, 23): "Is built like a gorilla",
            (24, 25): "Is bigger than a barn",
        }
    }

    key = stat_name.lower()
    if key in descriptions:
        table = descriptions[key]
        for (lo, hi), description in table.items():
            if lo <= stat_value <= hi:
                return description
    return ""


def get_skill_description(skill_level):
    """Get description for skill level."""
    descriptions = {
        0: "No Skill",
        1: "Novice",
        2: "Some Skill",
        3: "Skilled",
        4: "Good Skill",
        5: "Very Skilled",
        6: "Excellent Skill",
        7: "Expert Skill",
        8: "Incredible Skill",
        9: "Master Skill"
    }
    desc = descriptions.get(skill_level, f"Skill Level {skill_level}")
    return f"{desc} ({skill_level})"


def get_injury_description(severity):
    """Get description for injury severity."""
    descriptions = {
        0: "None",
        1: "Annoying",
        2: "Bothersome",
        3: "Irritating",
        4: "Troublesome",
        5: "Painful",
        6: "Dreadful",
        7: "Incapacitating",
        8: "Devastating",
        9: "Fatal"
    }
    desc = descriptions.get(severity, f"Level {severity}")
    return f"{desc} ({severity})"


def get_race_traits_html(race_name):
    """Get comprehensive racial traits separated into bonuses and penalties."""
    # First try to use embedded race data
    if race_name in RACE_DATA:
        return {
            "bonuses": RACE_DATA[race_name]["bonuses"],
            "penalties": RACE_DATA[race_name]["penalties"],
        }

    # Fallback to importing races module if available
    try:
        from races import get_race
        race = get_race(race_name)
        if not race:
            return {"bonuses": [], "penalties": []}

        mods = race.modifiers
        bonuses = []
        penalties = []

        # Stat bonuses/penalties
        if mods.hp_bonus != 0:
            bonuses.append(f"HP Bonus: {mods.hp_bonus:+d}")
        if mods.damage_bonus != 0:
            bonuses.append(f"Damage Bonus: {mods.damage_bonus:+d}")
        if mods.damage_penalty != 0:
            penalties.append(f"Damage Penalty: {mods.damage_penalty}")
        if mods.strength_penalty != 0:
            penalties.append(f"Strength Penalty: {mods.strength_penalty}")

        # Combat modifiers
        if mods.attack_rate_bonus != 0:
            bonuses.append(f"Attack Rate Bonus: {mods.attack_rate_bonus:+d}")
        if mods.attack_rate_penalty != 0:
            penalties.append(f"Attack Rate Penalty: {mods.attack_rate_penalty}")
        if mods.initiative_bonus != 0:
            bonuses.append(f"Initiative Bonus: {mods.initiative_bonus:+d}")
        if mods.dodge_bonus != 0:
            bonuses.append(f"Dodge Bonus: {mods.dodge_bonus:+d}")
        if mods.dodge_penalty != 0:
            penalties.append(f"Dodge Penalty: {mods.dodge_penalty}")
        if mods.parry_bonus != 0:
            bonuses.append(f"Parry Bonus: {mods.parry_bonus:+d}")
        if mods.parry_penalty != 0:
            penalties.append(f"Parry Penalty: {mods.parry_penalty}")

        # Special abilities
        if mods.armor_capacity_bonus:
            bonuses.append("Armor Capacity Bonus: Can wear heavier armor")
        if mods.shield_bonus:
            bonuses.append("Shield Bonus: Extra protection with shields")
        if mods.dual_weapon_bonus:
            bonuses.append("Dual Weapon Bonus: Enhanced dual-wield attacks")
        if mods.martial_combat_bonus:
            bonuses.append("Martial Combat Bonus: Extra effectiveness in hand-to-hand")
        if mods.trains_stats_faster:
            bonuses.append("Fast Training: Attributes improve more quickly")
        if mods.fewer_perms:
            bonuses.append("Injury Resistance: Lower chance of permanent injuries")
        if mods.bigger_weapons_bonus:
            bonuses.append("Bigger Weapons: Can wield heavier weapons more easily")
        if mods.thrown_mastery:
            bonuses.append("Thrown Mastery: Bonus to throwing attacks")
        if mods.scavenger:
            bonuses.append("Scavenger: Can pick up dropped weapons during combat")
        if mods.heavy_weapon_penalty:
            penalties.append("Heavy Weapon Penalty: Heavy weapons incur penalties")
        if mods.counterstrike_mastery:
            bonuses.append("Counterstrike Mastery: Strong ripostes after successful parries")
        if mods.tactician_edge:
            bonuses.append("Tactician's Edge: Better vs aggressive foes, worse vs methodical")
        if mods.natural_armor:
            bonuses.append("Natural Armor: Scales provide innate armor protection")
        if mods.natural_weapon_bonus:
            bonuses.append("Natural Weapons: Bonus damage with claws and natural attacks")
        if mods.acrobatic_advantage:
            bonuses.append("Acrobatic Advantage: Highly resistant to knockdowns")
        if mods.frenzy_ability:
            bonuses.append("Frenzy: Once per fight, gain +3 attack rate burst (3-4 actions)")
        if mods.spear_exception:
            bonuses.append("Spear Mastery: Spears exempt from heavy weapon penalties")

        # Preferred/weak weapons
        if mods.preferred_weapons:
            weapons_str = ", ".join(mods.preferred_weapons[:5])
            if len(mods.preferred_weapons) > 5:
                weapons_str += f", +{len(mods.preferred_weapons) - 5} more"
            bonuses.append(f"Preferred Weapons: {weapons_str}")
        if mods.weak_weapons:
            weapons_str = ", ".join(mods.weak_weapons[:3])
            penalties.append(f"Weak Against: {weapons_str}")

        # Opponent matchups
        if mods.favored_opponents:
            bonuses.append(f"Favored Matchups: {mods.favored_opponents}")
        if mods.disfavored_opponents:
            penalties.append(f"Difficult Matchups: {mods.disfavored_opponents}")

        return {"bonuses": bonuses, "penalties": penalties}
    except (ImportError, ModuleNotFoundError):
        return {"bonuses": [], "penalties": []}
    except Exception as e:
        print(f"Warning: Could not load race info for {race_name}: {e}")
        return {"bonuses": [], "penalties": []}


def get_weapon_analysis(weapon_name, warrior_strength, warrior_size=10):
    """
    Analyze weapon compatibility with warrior's strength.
    Returns dict with weapon info, requirements, and any penalties/bonuses.
    """
    try:
        from weapons import get_weapon, min_str_for_weight, strength_penalty
        weapon = get_weapon(weapon_name)

        if not weapon:
            return {"analysis": [], "warnings": []}

        analysis = []
        warnings = []

        # Get minimum strength required for this weapon
        min_str = min_str_for_weight(weapon.weight, weapon.two_hand)

        # Calculate strength penalty
        penalty_fraction = strength_penalty(weapon.weight, warrior_strength, weapon.two_hand)

        # Determine if there are penalties
        if warrior_strength < min_str:
            str_deficit = min_str - warrior_strength
            analysis.append(f"Strength Deficit: {str_deficit} points below requirement ({warrior_strength}/{min_str})")

            # Calculate penalty percentage
            penalty_pct = int(penalty_fraction * 100)
            if penalty_pct > 0:
                analysis.append(f"Attack Rate Penalty: -{penalty_pct}%")
                analysis.append(f"Damage Penalty: -{penalty_pct}%")
                warnings.append("This weapon is too heavy for your current strength!")
        else:
            str_surplus = warrior_strength - min_str
            if str_surplus >= 3:
                analysis.append(f"Strength Surplus: {str_surplus} points above requirement")
                analysis.append("Bonus: Effective weapon handling")
            else:
                analysis.append(f"Meets Strength Requirement: {warrior_strength}/{min_str}")

        # Check for size considerations if applicable
        if weapon.two_hand:
            analysis.append("Two-handed weapon: Grants +1 to effective strength capacity")

        return {"analysis": analysis, "warnings": warnings}
    except (ImportError, ModuleNotFoundError):
        return {"analysis": [], "warnings": []}
    except Exception as e:
        return {"analysis": [], "warnings": []}


def get_warrior_record(warrior):
    """Get warrior record as wins-losses-kills."""
    wins = warrior.get('wins', 0)
    losses = warrior.get('losses', 0)
    kills = warrior.get('kills', 0)
    return f"{wins}-{losses}-{kills}"


def generate_html_character_sheet(warrior_data, team_name, manager_name):
    """Generate HTML character sheet for a warrior."""

    warrior = warrior_data
    warrior_name = warrior.get('name', 'Unknown')
    race_name = warrior.get('race', 'Human')
    gender = warrior.get('gender', 'Male')
    record = get_warrior_record(warrior)

    # Get basic stats
    height_in = warrior.get('height_in', 70)
    height_ft = height_in // 12
    height_inches = height_in % 12
    weight = warrior.get('weight_lbs', 150)
    hp = warrior.get('max_hp', 50)
    luck = warrior.get('luck', 10)
    recognition = warrior.get('recognition', 0)
    popularity = warrior.get('popularity', 0)

    # Get attributes and initial stats
    initial_stats = warrior.get('initial_stats', {})
    attributes = {
        'Strength': warrior.get('strength', 10),
        'Dexterity': warrior.get('dexterity', 10),
        'Constitution': warrior.get('constitution', 10),
        'Intelligence': warrior.get('intelligence', 10),
        'Presence': warrior.get('presence', 10),
        'Size': warrior.get('size', 10),
    }
    initial_attributes = {
        'Strength': initial_stats.get('strength', 10),
        'Dexterity': initial_stats.get('dexterity', 10),
        'Constitution': initial_stats.get('constitution', 10),
        'Intelligence': initial_stats.get('intelligence', 10),
        'Presence': initial_stats.get('presence', 10),
        'Size': initial_stats.get('size', 10),
    }

    # Get favorite weapon
    favorite_weapon = warrior.get('primary_weapon', 'Open Hand')

    # Get skills
    skills = warrior.get('skills', {})

    # Get injuries
    injuries = warrior.get('injuries', {})

    # Get race traits
    traits_dict = get_race_traits_html(race_name)
    bonuses = traits_dict.get("bonuses", [])
    penalties = traits_dict.get("penalties", [])

    # Build HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{team_name} - {warrior_name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Cinzel', 'Georgia', serif;
            background-color: #f5f5f5;
            padding: 20px;
            color: #333;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background-color: white;
            padding: 40px;
            border: 3px solid #8b7355;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            font-size: 32px;
            text-align: center;
            margin-bottom: 10px;
            color: #8B0000;
            letter-spacing: 2px;
        }}
        .header-line {{
            text-align: center;
            margin-bottom: 20px;
            font-size: 14px;
            color: #666;
        }}
        .header-info {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 15px;
        }}
        .info-block {{ padding: 10px 0; }}
        .info-label {{ font-weight: bold; margin-right: 10px; }}
        .section-title {{
            font-size: 18px;
            font-weight: bold;
            margin-top: 25px;
            margin-bottom: 15px;
            color: #000;
        }}
        .attributes-table {{
            margin-left: 20px;
            font-family: 'Georgia', serif;
            font-size: 16px;
            margin-bottom: 20px;
            margin-top: 15px;
        }}
        .attributes-row {{
            display: flex;
            margin-bottom: 2px;
        }}
        .attribute-name {{
            font-weight: bold;
            width: 15ch;
            text-align: left;
        }}
        .attribute-value {{
            font-weight: bold;
            color: #8b4513;
            width: 4ch;
            text-align: right;
        }}
        .attribute-original {{
            font-weight: bold;
            color: #8b4513;
            width: 4ch;
            text-align: right;
        }}
        .attribute-descs {{
            margin-left: 20px;
            list-style-type: none;
            padding: 0;
        }}
        .attribute-descs li {{
            margin-bottom: 4px;
            font-style: italic;
            color: #666;
        }}
        .skills-list, .injuries-list {{
            margin-left: 20px;
            list-style-type: none;
        }}
        .skills-list li, .injuries-list li {{
            margin-bottom: 8px;
            padding: 5px;
            background-color: #fafafa;
            border-left: 3px solid #8b7355;
            padding-left: 10px;
        }}
        .race-traits {{
            background-color: #fffef5;
            padding: 15px;
            border-left: 4px solid #8b7355;
            margin: 15px 0;
        }}
        .race-traits ul {{
            list-style-type: none;
            margin-left: 0;
        }}
        .race-traits li {{
            margin-bottom: 5px;
            padding-left: 0;
        }}
        .race-penalties {{
            background-color: #ffe6e6;
            padding: 15px;
            border-left: 4px solid #8b0000;
            margin: 15px 0;
        }}
        .race-penalties ul {{
            list-style-type: none;
            margin-left: 0;
        }}
        .race-penalties li {{
            margin-bottom: 5px;
            padding-left: 0;
            color: #8b0000;
            font-weight: bold;
        }}
        .weapon-warnings {{
            background-color: #ffe6e6;
            padding: 15px;
            border-left: 4px solid #8b0000;
            margin: 15px 0;
        }}
        .weapon-warnings p {{
            margin: 5px 0;
            color: #8b0000;
        }}
        .weapon-analysis {{
            margin-left: 20px;
            list-style-type: none;
            padding: 0;
        }}
        .weapon-analysis li {{
            margin-bottom: 6px;
            padding: 5px;
            background-color: #f0f8ff;
            border-left: 3px solid #4169e1;
            padding-left: 10px;
        }}
        .empty-section {{
            font-style: italic;
            color: #999;
        }}
        .generated-date {{
            text-align: center;
            font-size: 12px;
            color: #999;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
        }}
        @media print {{
            body {{ background-color: white; padding: 0; }}
            .container {{ box-shadow: none; border: 1px solid #ddd; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{warrior_name}</h1>
        <div class="header-line">Record: <strong>{record}</strong></div>

        <div class="header-info">
            <div class="info-block">
                <div><span class="info-label">Team:</span>{team_name}</div>
                <div><span class="info-label">Manager:</span>{manager_name}</div>
                <div><span class="info-label">Race/Gender:</span>{race_name} {gender}</div>
            </div>
            <div class="info-block">
                <div><span class="info-label">Height:</span>{height_ft}'{height_inches}"</div>
                <div><span class="info-label">Weight:</span>{weight} lbs.</div>
                <div><span class="info-label">Hit Points:</span>{hp}</div>
                <div><span class="info-label">Luck:</span>{luck}</div>
                <div><span class="info-label">Recognition:</span>{recognition}</div>
                <div><span class="info-label">Popularity:</span>{popularity}</div>
            </div>
        </div>

        <div class="section-title">ATTRIBUTES</div>
"""

    # Build attribute descriptions first
    html += '        <ul class="attribute-descs">\n'
    for attr_name, attr_value in attributes.items():
        desc = get_attribute_description(attr_name, attr_value)
        desc_with_name = f"{warrior_name} {desc}"
        html += f'            <li>{desc_with_name}</li>\n'
    html += '        </ul>\n'

    # Then build attributes table
    html += '        <div class="attributes-table">\n'
    for attr_name, attr_value in attributes.items():
        initial_value = initial_attributes.get(attr_name, attr_value)
        value_str = str(attr_value)
        original_str = f"({initial_value})" if initial_value != attr_value else ""
        html += f'            <div class="attributes-row">\n'
        html += f'                <div class="attribute-name">{attr_name}:</div>\n'
        html += f'                <div class="attribute-value">{value_str}</div>\n'
        html += f'                <div class="attribute-original">{original_str}</div>\n'
        html += f'            </div>\n'
    html += '        </div>\n'

    # Race traits and penalties
    if bonuses or penalties:
        html += f"""
        <div class="section-title">RACIAL TRAITS & BONUSES</div>
"""
        if bonuses:
            html += '        <div class="race-traits">\n'
            html += '            <ul>\n'
            for bonus in bonuses:
                html += f'                <li>{bonus}</li>\n'
            html += '            </ul>\n'
            html += '        </div>\n'

        if penalties:
            html += f"""        <div class="section-title">RACIAL PENALTIES</div>
"""
            html += '        <div class="race-penalties">\n'
            html += '            <ul>\n'
            for penalty in penalties:
                html += f'                <li>- {penalty}</li>\n'
            html += '            </ul>\n'
            html += '        </div>\n'

    # Favorite weapon and analysis
    html += f"""
        <div class="section-title">FAVORITE WEAPON</div>
        <div style="margin-left: 20px;">
            <strong>{favorite_weapon}</strong>
        </div>
"""

    # Get weapon analysis
    weapon_analysis = get_weapon_analysis(favorite_weapon, attributes.get('Strength', 10))
    if weapon_analysis["analysis"]:
        html += f"""
        <div class="section-title">WEAPON ANALYSIS</div>
"""
        if weapon_analysis["warnings"]:
            html += '        <div class="weapon-warnings">\n'
            for warning in weapon_analysis["warnings"]:
                html += f'            <p><strong>⚠️ {warning}</strong></p>\n'
            html += '        </div>\n'

        html += '        <ul class="weapon-analysis">\n'
        for item in weapon_analysis["analysis"]:
            html += f'            <li>{item}</li>\n'
        html += '        </ul>\n'

    # Skills
    html += f"""
        <div class="section-title">SKILLS</div>
"""
    if skills:
        html += '        <ul class="skills-list">\n'
        for skill_name, skill_level in sorted(skills.items()):
            if skill_level > 0:
                skill_desc = get_skill_description(skill_level)
                display_name = skill_name.replace('_', ' ').title()
                html += f'            <li><strong>{display_name}</strong>: {skill_desc}</li>\n'
        html += '        </ul>\n'
    else:
        html += '        <div class="empty-section">No skills trained</div>\n'

    # Injuries
    html += f"""
        <div class="section-title">INJURIES</div>
"""
    if injuries:
        html += '        <ul class="injuries-list">\n'
        for location, severity in sorted(injuries.items()):
            severity_desc = get_injury_description(severity)
            location_display = location.replace('_', ' ').title()
            html += f'            <li>Has a {severity_desc} wound to the {location_display}</li>\n'
        html += '        </ul>\n'
    else:
        html += '        <div class="empty-section">No injuries</div>\n'

    html += f"""
        <div class="generated-date">
            Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
    </div>
</body>
</html>
"""

    return html


def main():
    """Main function to generate character sheets for all warriors."""

    if not os.path.exists(TEAMS_DIR):
        print(f"Error: Teams directory not found at {TEAMS_DIR}")
        return

    print(f"Character Sheet Generator")
    print(f"=" * 60)
    print(f"Reading teams from: {TEAMS_DIR}")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    total_sheets = 0

    # Find all team files
    for team_file in sorted(os.listdir(TEAMS_DIR)):
        if not team_file.endswith('.json'):
            continue

        team_path = os.path.join(TEAMS_DIR, team_file)
        team_data = load_json_file(team_path)

        if not team_data:
            continue

        team_name = team_data.get('team_name', 'Unknown Team')
        manager_name = team_data.get('manager_name', 'Unknown Manager')
        warriors = team_data.get('warriors', [])

        print(f"Processing team: {team_name} (Manager: {manager_name})")
        print(f"  Warriors: {len(warriors)}")

        for warrior in warriors:
            warrior_name = warrior.get('name', 'Unknown')

            # Generate filename
            safe_team_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in team_name)
            safe_warrior_name = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in warrior_name)
            filename_base = f"{safe_team_name}_{safe_warrior_name}"
            html_filename = f"{filename_base}.html"
            html_filepath = os.path.join(OUTPUT_DIR, html_filename)

            # Generate HTML
            html_content = generate_html_character_sheet(warrior, team_name, manager_name)

            # Write HTML file
            try:
                with open(html_filepath, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                print(f"    [OK] {warrior_name}: {html_filename}")
                total_sheets += 1
            except Exception as e:
                print(f"    [ERR] {warrior_name}: Error writing HTML - {e}")

        print()

    print(f"=" * 60)
    print(f"Generated {total_sheets} character sheets")
    print(f"Output saved to: {OUTPUT_DIR}")
    print()
    print("Character sheets are in HTML format.")
    print("To generate PDF files:")
    print("  - Open HTML files in a web browser and print to PDF")
    print("  - Or install a PDF library (weasyprint, xhtml2pdf, reportlab)")

if __name__ == "__main__":
    main()
