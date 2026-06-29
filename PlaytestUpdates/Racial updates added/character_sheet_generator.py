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
            3: "Is pathetically weak", 6: "Is quite weak", 9: "Is below average in strength",
            12: "Has average strength", 15: "Is of muscular strength", 18: "Is very strong",
            21: "Is extremely powerful"
        },
        "dexterity": {
            3: "Has clumsy movements", 6: "Has slow movements", 9: "Has below average reflexes",
            12: "Has average reflexes", 15: "Has quick movements", 18: "Has very quick reflexes",
            21: "Has lightning reflexes"
        },
        "constitution": {
            3: "Is quite sickly", 6: "Has poor health", 9: "Has below average constitution",
            12: "Has an average constitution", 15: "Has a healthy constitution", 18: "Is very hardy",
            21: "Is extremely tough"
        },
        "intelligence": {
            3: "Is quite dim-witted", 6: "Is below average in intelligence", 9: "Is somewhat simple",
            12: "Is of average intelligence", 15: "Is fairly bright", 18: "Is very intelligent",
            21: "Is a genius"
        },
        "presence": {
            3: "Is barely noticed", 6: "Is easily overlooked", 9: "Has a forgettable presence",
            12: "Has an average presence", 15: "Has a commanding presence", 18: "Is very charismatic",
            21: "Is extremely charismatic"
        },
        "size": {
            3: "Is very frail", 6: "Is a small frame", 9: "Has a wiry frame",
            12: "Has an average frame", 15: "Has a sturdy frame", 18: "Is quite large",
            21: "Is enormous"
        }
    }

    key = stat_name.lower()
    if key in descriptions:
        # Find closest match
        values = sorted(descriptions[key].keys())
        closest = min(values, key=lambda x: abs(x - stat_value))
        return descriptions[key][closest]
    return ""


def get_skill_description(skill_level):
    """Get description for skill level."""
    descriptions = {
        0: "No training",
        1: "Has Some Skill (1)",
        2: "Has Some Skill (2)",
        3: "Has Good Skill (3)",
        4: "Has Good Skill (4)",
        5: "Has Excellent Skill (5)",
        6: "Has Excellent Skill (6)",
        7: "Has Master Level Skill (7)",
        8: "Has Master Level Skill (8)",
        9: "Has Expert Master Skill (9)"
    }
    return descriptions.get(skill_level, f"Has Skill ({skill_level})")


def get_injury_description(severity):
    """Get description for injury severity."""
    descriptions = {
        1: "Annoying (1)",
        2: "Minor (2)",
        3: "Moderate (3)",
        4: "Troublesome (4)",
        5: "Serious (5)",
        6: "Grievous (6)"
    }
    return descriptions.get(severity, f"Level {severity}")


def get_race_traits_html(race_name):
    """Get comprehensive racial traits as HTML list items."""
    try:
        from races import get_race
        race = get_race(race_name)
        if not race:
            return ""

        mods = race.modifiers
        traits = []

        # Stat bonuses/penalties
        if mods.hp_bonus != 0:
            traits.append(f"HP Bonus: {mods.hp_bonus:+d}")
        if mods.damage_bonus != 0:
            traits.append(f"Damage Bonus: {mods.damage_bonus:+d}")
        if mods.damage_penalty != 0:
            traits.append(f"Damage Penalty: {mods.damage_penalty:+d}")
        if mods.strength_penalty != 0:
            traits.append(f"Strength Penalty: {mods.strength_penalty:+d}")

        # Combat modifiers
        if mods.attack_rate_bonus != 0:
            traits.append(f"Attack Rate Bonus: {mods.attack_rate_bonus:+d}")
        if mods.attack_rate_penalty != 0:
            traits.append(f"Attack Rate Penalty: {mods.attack_rate_penalty:+d}")
        if mods.initiative_bonus != 0:
            traits.append(f"Initiative Bonus: {mods.initiative_bonus:+d}")
        if mods.dodge_bonus != 0:
            traits.append(f"Dodge Bonus: {mods.dodge_bonus:+d}")
        if mods.dodge_penalty != 0:
            traits.append(f"Dodge Penalty: {mods.dodge_penalty:+d}")
        if mods.parry_bonus != 0:
            traits.append(f"Parry Bonus: {mods.parry_bonus:+d}")
        if mods.parry_penalty != 0:
            traits.append(f"Parry Penalty: {mods.parry_penalty:+d}")

        # Special abilities
        if mods.armor_capacity_bonus:
            traits.append("Armor Capacity Bonus: Can wear heavier armor")
        if mods.shield_bonus:
            traits.append("Shield Bonus: Extra protection with shields")
        if mods.dual_weapon_bonus:
            traits.append("Dual Weapon Bonus: Enhanced dual-wield attacks")
        if mods.martial_combat_bonus:
            traits.append("Martial Combat Bonus: Extra effectiveness in hand-to-hand")
        if mods.trains_stats_faster:
            traits.append("Fast Training: Attributes improve more quickly")
        if mods.fewer_perms:
            traits.append("Injury Resistance: Lower chance of permanent injuries")
        if mods.bigger_weapons_bonus:
            traits.append("Bigger Weapons: Can wield heavier weapons more easily")
        if mods.thrown_mastery:
            traits.append("Thrown Mastery: Bonus to throwing attacks")
        if mods.scavenger:
            traits.append("Scavenger: Can pick up dropped weapons during combat")
        if mods.heavy_weapon_penalty:
            traits.append("Light Weapons Preference: Heavy weapons incur penalties")
        if mods.counterstrike_mastery:
            traits.append("Counterstrike Mastery: Strong ripostes after successful parries")
        if mods.tactician_edge:
            traits.append("Tactician's Edge: Better vs aggressive foes, worse vs methodical")
        if mods.natural_armor:
            traits.append("Natural Armor: Scales provide innate armor protection")
        if mods.natural_weapon_bonus:
            traits.append("Natural Weapons: Bonus damage with claws and natural attacks")
        if mods.acrobatic_advantage:
            traits.append("Acrobatic Advantage: Highly resistant to knockdowns")
        if mods.frenzy_ability:
            traits.append("Frenzy: Once per fight, gain +3 attack rate burst (3-4 actions)")
        if mods.spear_exception:
            traits.append("Spear Mastery: Spears exempt from heavy weapon penalties")

        # Preferred/weak weapons
        if mods.preferred_weapons:
            weapons_str = ", ".join(mods.preferred_weapons[:5])
            if len(mods.preferred_weapons) > 5:
                weapons_str += f", +{len(mods.preferred_weapons) - 5} more"
            traits.append(f"Preferred Weapons: {weapons_str}")
        if mods.weak_weapons:
            weapons_str = ", ".join(mods.weak_weapons[:3])
            traits.append(f"Weak Against: {weapons_str}")

        # Opponent matchups
        if mods.favored_opponents:
            traits.append(f"Favored Matchups: {mods.favored_opponents}")
        if mods.disfavored_opponents:
            traits.append(f"Difficult Matchups: {mods.disfavored_opponents}")

        return traits
    except Exception as e:
        print(f"Warning: Could not load race info for {race_name}: {e}")
        return []


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
    traits_list = get_race_traits_html(race_name)
    race_traits = ""
    if traits_list:
        race_traits = "\n".join([f"<li>{trait}</li>" for trait in traits_list])

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
            color: #000;
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
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #8b7355;
        }}
        .info-block {{ padding: 10px 0; }}
        .info-label {{ font-weight: bold; margin-right: 10px; }}
        .section-title {{
            font-size: 18px;
            font-weight: bold;
            margin-top: 25px;
            margin-bottom: 15px;
            border-bottom: 1px solid #8b7355;
            padding-bottom: 5px;
            color: #000;
        }}
        .attribute-row {{
            display: grid;
            grid-template-columns: 150px 60px 1fr;
            gap: 20px;
            margin-bottom: 10px;
            padding: 8px;
            background-color: #fafafa;
            border-radius: 3px;
        }}
        .attribute-name {{ font-weight: bold; }}
        .attribute-value {{
            text-align: center;
            font-weight: bold;
            color: #8b4513;
            font-size: 16px;
        }}
        .attribute-desc {{ font-style: italic; color: #666; }}
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

    for attr_name, attr_value in attributes.items():
        initial_value = initial_attributes.get(attr_name, attr_value)
        desc = get_attribute_description(attr_name, attr_value)
        # Show current (initial) format
        if initial_value != attr_value:
            value_display = f"{attr_value} ({initial_value})"
        else:
            value_display = str(attr_value)
        html += f"""        <div class="attribute-row">
            <div class="attribute-name">{attr_name}</div>
            <div class="attribute-value">{value_display}</div>
            <div class="attribute-desc">{desc}</div>
        </div>
"""

    # Race traits
    if race_traits:
        html += f"""
        <div class="section-title">RACIAL TRAITS & BONUSES</div>
        <div class="race-traits">
            <ul>
{race_traits}
            </ul>
        </div>
"""

    # Favorite weapon
    html += f"""
        <div class="section-title">FAVORITE WEAPON</div>
        <div style="margin-left: 20px;">
            <strong>{favorite_weapon}</strong>
        </div>
"""

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
