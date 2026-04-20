# =============================================================================
# narrative.py, BLOODSPIRE Narrative Text Engine
# =============================================================================
# Generates all fight text: the side-by-side header, blow-by-blow lines,
# perm injury announcements, surrender/mercy text, crowd flavor, and the
# post-fight training summary.
#
# Design: templates for structure, pools for flavor.
# Each pool has 10-15 variants so fights feel different but recognizable.
# =============================================================================

import random
from typing import Optional
from warrior import Warrior, compare_stats
from weapons import get_weapon

LINE_WIDTH = 76   # Total width of fight output


# ---------------------------------------------------------------------------
# POPULARITY DESCRIPTIONS
# ---------------------------------------------------------------------------

POPULARITY_DESCRIPTIONS = [
    (0,  10, "WIDELY REVILED"),
    (11, 20, "BOOED REGULARLY"),
    (21, 30, "GENERALLY DISLIKED"),
    (31, 40, "MOSTLY IGNORED"),
    (41, 50, "KNOWN TO THE CROWD"),
    (51, 60, "POPULAR WITH THE KIDS"),
    (61, 70, "WELL LIKED"),
    (71, 80, "A FAN FAVORITE"),
    (81, 90, "HAS HORDES OF ADORING FANS"),
    (91, 100, "A LEGENDARY HERO OF THE PIT"),
]


def popularity_desc(score: int) -> str:
    for lo, hi, desc in POPULARITY_DESCRIPTIONS:
        if lo <= score <= hi:
            return desc
    return "KNOWN TO THE CROWD"


def _backup_weapon_description(weapon_name: str, gender: str) -> str:
    """
    Generate a thematic, location-specific description of a backup weapon.
    Returns a string (without period) describing where/how it's carried.
    """
    pronoun = "his" if gender == "Male" else "her"
    weapon_lower = weapon_name.lower().replace(" ", "_").replace("&", "and")
    
    try:
        weapon = get_weapon(weapon_name)
    except ValueError:
        # Fallback for unknown weapons
        return f"has a spare {weapon_name.upper()} strapped to {pronoun} side"
    
    wpn_display = weapon.display.upper()
    is_light = weapon.weight < 2.5
    is_small = weapon.weight < 2.0
    is_heavy = weapon.weight >= 5.0
    is_two_hand = weapon.two_hand
    is_shield = weapon.is_shield
    is_throwable = weapon.throwable
    is_polearm = weapon.category == "Polearm/Spear"
    
    # Shield-specific descriptions
    if is_shield:
        shield_desc = [
            f"has a {wpn_display} buckled to {pronoun} arm",
            f"carries a {wpn_display} on {pronoun} shoulder",
            f"has a {wpn_display} strapped across {pronoun} back",
        ]
        return random.choice(shield_desc)
    
    # Small daggers/knives - thrust into waistband
    if is_small and weapon_lower in ("dagger", "knife", "stiletto"):
        small_desc = [
            f"has a {wpn_display} thrust into {pronoun} waistband",
            f"carries a {wpn_display} tucked into {pronoun} belt",
            f"has a {wpn_display} sheathed at {pronoun} hip",
        ]
        return random.choice(small_desc)
    
    # Polearms and spears - carried upright or across back
    if is_polearm:
        polearm_desc = [
            f"has a {wpn_display} strapped to {pronoun} back",
            f"carries a {wpn_display} planted at {pronoun} side",
            f"wears a {wpn_display} across {pronoun} back",
        ]
        return random.choice(polearm_desc)
    
    # Light one-handed weapons - various options
    if is_light and not is_two_hand:
        light_desc = [
            f"has a {wpn_display} slung across {pronoun} back",
            f"carries a {wpn_display} strapped to {pronoun} hip",
            f"has a {wpn_display} sheathed at {pronoun} side",
            f"wears a {wpn_display} across {pronoun} back",
        ]
        return random.choice(light_desc)
    
    # Two-handed weapons - strapped/slung across back
    if is_two_hand:
        heavy_desc = [
            f"has a {wpn_display} strapped to {pronoun} back",
            f"carries a {wpn_display} slung across {pronoun} back",
            f"wears a {wpn_display} lashed to {pronoun} back",
        ]
        return random.choice(heavy_desc)
    
    # Heavy one-handed weapons - shoulder or back
    if is_heavy:
        heavy_1h_desc = [
            f"has a {wpn_display} resting on {pronoun} shoulder",
            f"carries a {wpn_display} strapped to {pronoun} back",
            f"wears a {wpn_display} across {pronoun} back",
        ]
        return random.choice(heavy_1h_desc)
    
    # Other throwable weapons (axes, etc) - quiver, bundle, or bandolier
    if is_throwable and weapon_lower not in ("dagger", "knife", "stiletto"):
        throw_desc = [
            f"has a {wpn_display} bundled and strapped to {pronoun} back",
            f"carries a {wpn_display} across {pronoun} shoulder",
            f"has a {wpn_display} at {pronoun} side",
        ]
        return random.choice(throw_desc)
    
    # Default for medium weapons
    default_desc = [
        f"has a {wpn_display} strapped to {pronoun} side",
        f"carries a {wpn_display} sheathed at {pronoun} hip",
        f"wears a {wpn_display} across {pronoun} back",
    ]
    return random.choice(default_desc)


# ---------------------------------------------------------------------------
# FIGHT HEADER
# ---------------------------------------------------------------------------

def _center_col(text: str, width: int) -> str:
    return text.center(width)


def _right_col(text: str, width: int) -> str:
    return text.rjust(width)


def _left_col(text: str, width: int) -> str:
    return text.ljust(width)


def _warrior_report_block(w: Warrior) -> list:
    """
    Return prose description lines for one warrior: height, weight,
    popularity, armor, helm, and weapons. No strategy table.
    """
    h_ft = w.height_in // 12
    h_in = w.height_in % 12
    pronoun = "his" if w.gender == "Male" else "her"

    lines = []
    lines.append(f"{w.name.upper()} is {h_ft}'{h_in}\"")
    lines.append(f"{w.name.upper()} weighs {w.weight_lbs} lbs.")
    lines.append(f"{w.name.upper()} {popularity_desc(w.popularity).title()}.")

    armor_part = f"in {w.armor.upper()}" if w.armor else "unarmored"
    helm_part  = f"and will wear a {w.helm.upper()}" if w.helm else "and wears no helm"
    lines.append(f"{w.name.upper()} enters the arena {armor_part} {helm_part}.")

    main = w.primary_weapon.upper() if w.primary_weapon else "OPEN HAND"
    off  = w.secondary_weapon.upper() if w.secondary_weapon else None
    bak  = w.backup_weapon if w.backup_weapon else None

    if off and off.upper() != "OPEN HAND":
        lines.append(f"{w.name.upper()} fights using a {main} with an off-hand {off}.")
    else:
        lines.append(f"{w.name.upper()} fights using a {main}.")

    if bak and bak.upper() != "OPEN HAND":
        backup_desc = _backup_weapon_description(bak, w.gender)
        lines.append(f"{w.name.upper()} {backup_desc}.")

    return lines


def _strategy_table(w: Warrior) -> list:
    """Return the strategy table lines for the player warrior."""
    if not w.strategies:
        return []
    hdr = f"{'TRIGGER':<42}{'FIGHTING STYLE':<20}{'LEVEL':>5}  {'AIMING POINT':<16}{'DEFENSE POINT'}"
    sep = "-" * len(hdr)
    lines = ["", hdr, sep]
    for i, s in enumerate(w.strategies, 1):
        is_default = (not s.trigger) or s.trigger.lower() == "always"
        trig = "D: Always" if is_default else f"{i}: {s.trigger}"
        aim  = s.aim_point    if s.aim_point    else "None"
        dfe  = s.defense_point if s.defense_point else "None"
        sty  = s.style        if s.style        else "None"
        lines.append(f"{trig:<42}{sty:<20}{s.activity:>5}  {aim:<16}{dfe}")
    return lines


def build_fight_header(
    warrior_a : Warrior,
    warrior_b : Warrior,
    team_a_name   : str,
    team_b_name   : str,
    manager_a_name: str,
    manager_b_name: str,
    pos_a: int = 1,
    pos_b: int = 1,
    challenger_name: str = None,
) -> str:
    """
    Generate the fight header in report/narrative style.
    Layout:
      - Matchup / team / race header
      - Warrior A (player) prose block
      - Warrior B (opponent) prose block
      - Warrior A strategy table only (opponent strategies are hidden)
    
    If challenger_name is provided:
      - Line will show "Challenges" or "is Challenged by" based on who initiated
    """
    SEP = "=" * LINE_WIDTH

    lines = [SEP]

    # Matchup title
    left  = f"{warrior_a.name.upper()} ({warrior_a.record_str})"
    right = f"{warrior_b.name.upper()} ({warrior_b.record_str})"
    
    # Determine middle text based on challenge type
    if challenger_name:
        if challenger_name == warrior_a.name:
            middle_text = "Challenges"
        elif challenger_name == warrior_b.name:
            middle_text = "is Challenged by"
        else:
            middle_text = "vs"  # fallback if challenger doesn't match either warrior
    else:
        middle_text = "vs"
    
    lines.append(f"{left}   {middle_text}   {right}")
    lines.append(f"{team_a_name.upper()} ({manager_a_name.upper()})"
                 + "   vs   " +
                 f"{team_b_name.upper()} ({manager_b_name.upper()})")
    lines.append(f"{warrior_a.race.name} {warrior_a.gender}"
                 + "   vs   " +
                 f"{warrior_b.race.name} {warrior_b.gender}")
    lines.append(SEP)
    lines.append("")

    # Player warrior prose
    lines.extend(_warrior_report_block(warrior_a))
    lines.append("")

    # Opponent warrior prose
    lines.extend(_warrior_report_block(warrior_b))
    lines.append("")

    # Player strategy table only
    lines.extend(_strategy_table(warrior_a))

    lines.append("")
    lines.append(SEP)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# FIGHT OPENER LINES (first line of minute 1)
# ---------------------------------------------------------------------------

FIGHT_OPENERS = [
    "Dark clouds bode ill for the battle",
    "The crowd roars its bloodthirsty approval",
    "A hush falls over the arena",
    "The smell of blood and sawdust fills the air",
    "Thunder rumbles ominously in the distance",
    "The afternoon sun beats down on the bloodstained sand",
    "The crowd jeers as the combatants approach each other",
    "An eerie silence settles over the BLOODSPIRE",
    "The torches flicker as a cold wind sweeps through the arena",
    "The Blood Master raises his fist, the fight begins!",
]


# ---------------------------------------------------------------------------
# STRATEGY SWITCH LINE
# ---------------------------------------------------------------------------

def strategy_switch_line(warrior_name: str, strat_idx: int) -> str:
    return f" * {warrior_name.upper()} switches to strategy {strat_idx}"


# ---------------------------------------------------------------------------
# STYLE INTENT LINES
# Appear before an attack (roughly 40% of the time).
# Template: "{name} {intent_phrase} with {pronoun} {weapon}"
# ---------------------------------------------------------------------------

STYLE_INTENT_POOLS: dict[str, list[str]] = {
    "Total Kill": [
        "{name} rampages onward, {weapon} starved for bloodshed",
        "{name} charges forward in a wild frenzy",
        "{name} drives suddenly forward, {weapon} whistling through the air",
        "{name} attacks in a berserker rage",
        "{name} hurls {himself} forward with reckless abandon",
    ],
    "Wall of Steel": [
        "{name} relentlessly presses forward with {his} {weapon}",
        "{name} creates a whirling wall of steel",
        "{name} attacks in a flurry of blows",
        "{name} hammers away with machine-like persistence",
    ],
    "Lunge": [
        "{name} darts forward, looking for an opening",
        "{name} probes for a weakness in {foe}'s defense",
        "{name} moves with quick, precise footwork",
        "{name} circles {foe}, waiting for the perfect moment",
    ],
    "Bash": [
        "{name} winds up for a crushing blow",
        "{name} drives forward with brute force",
        "{name} attempts to batter through {foe}'s defenses",
    ],
    "Slash": [
        "{name} draws back for a sweeping slash",
        "{name} lines up for a powerful drawing cut",
        "{name} seeks to open a telling wound",
    ],
    "Strike": [
        "{name} tries to hit the mighty {foe}",
        "{name} sizes up {foe} carefully",
        "{name} directs an attack toward {foe}",
        "{name} steps threateningly close to the {adj} {foe}",
    ],
    "Engage & Withdraw": [
        "{name} probes and retreats, looking for an opening",
        "{name} feints left and prepares to strike",
        "{name} dances away from {foe}'s reach",
    ],
    "Counterstrike": [
        "{name} waits patiently for {foe} to make a mistake",
        "{name} holds ground, watching {foe} like a hawk",
        "{name} anxiously awaits {foe}'s next move",
    ],
    "Decoy": [
        "{name} engages {foe}'s weapon with {his} off-hand",
        "{name} feints to draw {foe}'s attention",
        "{name} draws {foe} into an elaborate trap",
    ],
    "Sure Strike": [
        "{name} waits for absolutely the right moment",
        "{name} carefully prepares a deliberate strike",
        "{name} takes aim at {foe} with methodical precision",
    ],
    "Calculated Attack": [
        "{name} ruthlessly seeks wreckage with {his} {weapon}",
        "{name} calculates the perfect attack angle",
        "{name} studies {foe}'s armor for weak points",
    ],
    "Opportunity Throw": [
        "{name} hefts {his} {weapon} for a throw",
        "{name} lines up a ranged attack",
    ],
    "Martial Combat": [
        "{name} drops into a fighting crouch",
        "{name} circles {foe} with fluid martial grace",
        "{name} prepares to unleash a flurry of strikes",
    ],
    "Parry": [
        "{name} raises {his} {weapon} defensively",
        "{name} holds ground, focused entirely on defense",
    ],
    "Defend": [
        "{name} keeps {his} guard high",
        "{name} circles warily, waiting for an opening",
    ],
}

# AWKWARD STYLE INTENT LINES
# Used when a weapon and fighting style are incompatible.
# These replace the normal style intent lines for that attack.
AWKWARD_STYLE_INTENT_POOLS: dict[str, list[str]] = {
    "Bash": [
        "{name} awkwardly attempts to bash with {his} {weapon}",
        "{name} struggles to use {his} {weapon} as a bludgeon",
        "{name} clumsily tries to bash with {his} dainty {weapon}",
        "{name} futilely attempts to smash with {his} {weapon}",
    ],
    "Slash": [
        "{name} awkwardly attempts to slash with {his} {weapon}",
        "{name} fumbles trying to slash with {his} {weapon}",
        "{name} awkwardly draws {his} {weapon} for a clumsy slash",
        "{name} tries unsuccessfully to slash with {his} stubby {weapon}",
    ],
    "Cleave": [
        "{name} struggles to cleave with {his} {weapon}",
        "{name} awkwardly attempts a clumsy cleaving motion",
        "{name} tries unsuccessfully to split through with {his} {weapon}",
    ],
    "Wall of Steel": [
        "{name} awkwardly flails {his} {weapon} in rapid-fire attempts",
        "{name} fumbles through a poorly-executed flurry with {his} {weapon}",
        "{name} clumsily hammers away with {his} {weapon}",
    ],
    "Total Kill": [
        "{name} rages forward clumsily with {his} {weapon}",
        "{name} charges in a clumsy fury with {his} {weapon}",
        "{name} desperately thrashes about with {his} {weapon}",
    ],
    "Lunge": [
        "{name} attempts an awkward, ineffective lunge with {his} {weapon}",
        "{name} stumbles forward with {his} {weapon}",
        "{name} fumbles a pathetic lunge attempt",
    ],
}

# Adjectives used in strike intent lines (matching the guide "stable", "mighty", etc.)
WARRIOR_ADJ_POOL = [
    "formidable", "powerful", "mighty", "relentless", "fierce",
    "dangerous", "capable", "tenacious", "stalwart", "fearsome",
]


def style_intent_line(
    warrior_name : str,
    foe_name     : str,
    style        : str,
    weapon_name  : str,
    gender       : str,
) -> Optional[str]:
    """
    Return a style intent line (or None, ~60% skip chance).
    """
    if random.random() < 0.30:
        return None

    pool = STYLE_INTENT_POOLS.get(style, STYLE_INTENT_POOLS["Strike"])
    template = random.choice(pool)
    pronoun  = "his" if gender == "Male" else "her"
    reflexive= "himself" if gender == "Male" else "herself"
    adj      = random.choice(WARRIOR_ADJ_POOL)

    line = template.format(
        name    = warrior_name.upper(),
        foe     = foe_name.upper(),
        weapon  = weapon_name.lower(),
        his     = pronoun,
        himself = reflexive,
        adj     = adj,
    )
    return line


def awkward_style_intent_line(
    warrior_name : str,
    foe_name     : str,
    style        : str,
    weapon_name  : str,
    gender       : str,
) -> Optional[str]:
    """
    Return an awkward style intent line for incompatible weapon/style combos.
    Always returns a line (no skip chance, unlike normal intent lines).
    """
    pool = AWKWARD_STYLE_INTENT_POOLS.get(style, None)
    if pool is None:
        # Fallback to normal line if no awkward pool exists for this style
        return style_intent_line(warrior_name, foe_name, style, weapon_name, gender)
    
    template = random.choice(pool)
    pronoun  = "his" if gender == "Male" else "her"

    line = template.format(
        name    = warrior_name.upper(),
        foe     = foe_name.upper(),
        weapon  = weapon_name.lower(),
        his     = pronoun,
    )
    return line


# ---------------------------------------------------------------------------
# ATTACK LINES
# Format: "{attacker} tries to {verb} {defender}'s {location}"
# ---------------------------------------------------------------------------

# Aim-point display names
AIM_POINT_LABELS = {
    "Head"          : ["head", "skull", "helm", "throat", "face"],
    "Chest"         : ["chest", "rib cage", "torso", "sternum", "breast"],
    "Abdomen"       : ["abdomen", "midsection", "gut", "belly", "flank"],
    "Primary Arm"   : ["weapon arm", "primary arm", "sword arm"],
    "Secondary Arm" : ["shield arm", "secondary arm", "off arm", "left forearm"],
    "Primary Leg"   : ["primary leg", "lead leg", "front leg", "main leg"],
    "Secondary Leg" : ["trailing leg", "rear leg", "secondary leg"],
    "None"          : ["body", "midsection", "torso"],   # generic when no aim point
}

# Attack verbs by weapon category, third-person singular, complete phrases
ATTACK_VERBS: dict[str, list[str]] = {
    "Sword/Knife"  : ["slashes at", "cuts at", "hacks at", "slices at",
                      "drives a blow toward", "thrusts at"],
    "Axe/Pick"     : ["chops at", "hacks at", "cleaves at", "swings at"],
    "Hammer/Mace"  : ["bashes at", "smashes at", "bludgeons", "hammers at", "pounds at"],
    "Polearm/Spear": ["thrusts at", "drives a blow toward", "jabs at", "lunges at"],
    "Flail"        : ["lashes out at", "whips at", "flails at", "swings at"],
    "Stave"        : ["strikes at", "thrusts at", "jabs at", "swings at"],
    "Shield"       : ["bashes at", "slams into", "smashes at"],
    "Oddball"      : ["strikes at", "swings at", "lashes out at"],
}

# Lizardfolk-specific attack verbs when using Open Hand/Martial Combat
# Features claw rakes, tail sweeps, and powerful kicks
LIZARDFOLK_ATTACK_VERBS: dict[str, list[str]] = {
    "claw"  : ["rakes at", "slashes at with claws", "tears at", "rends at with razor claws"],
    "kick"  : ["kicks at", "stomps toward", "drives a powerful kick at", "lashes out with a kick toward"],
    "tail"  : ["sweeps at with tail", "lashes at with tail", "swings tail at", "brings tail around toward"],
}

# Extra style-flavored attack verbs, third-person singular
STYLE_ATTACK_PREFIX: dict[str, list[str]] = {
    "Total Kill"       : ["tries to demolish", "savagely attacks", "hacks away at",
                          "makes an explosive assault on"],
    "Bash"             : ["tries to bash", "pounds at", "hammers away at"],
    "Slash"            : ["tries to slash", "draws a cut at", "rakes at"],
    "Lunge"            : ["lunges at", "makes a quick thrust at", "darts in at"],
    "Calculated Attack": ["executes a downward strike at", "makes a precise attack on",
                          "aims a calculated blow at"],
    "Sure Strike"      : ["carefully aims at", "takes a measured swing at"],
    "Counterstrike"    : ["counters with a blow at", "retaliates against",
                          "fires back at"],
    "Wall of Steel"    : ["attacks relentlessly at", "relentlessly targets"],
}


def attack_line(
    attacker_name  : str,
    defender_name  : str,
    weapon_name    : str,
    weapon_category: str,
    style          : str,
    aim_point      : str,
    attacker_gender: str = "Male",
    attacker_race  : str = None,      # For Lizardfolk special handling
) -> str:
    """Generate the attack declaration line. Lizardfolk with Open Hand get special claw/tail/kick verbs."""
    loc_pool = AIM_POINT_LABELS.get(aim_point, AIM_POINT_LABELS["None"])
    location = random.choice(loc_pool)
    pronoun  = "his" if attacker_gender == "Male" else "her"

    # Lizardfolk with Open Hand use special descriptors
    if attacker_race == "Lizardfolk" and weapon_name == "Open Hand":
        attack_types = ["claw", "kick", "tail"]
        attack_type = random.choice(attack_types)
        
        verb_pool = LIZARDFOLK_ATTACK_VERBS.get(attack_type, LIZARDFOLK_ATTACK_VERBS["claw"])
        verb = random.choice(verb_pool)
        
        # Return without weapon mention since it's natural weapons
        return (
            f"{attacker_name.upper()} {verb} {defender_name.upper()}'s {location}!"
        )

    # Style-flavored variant, always ends with weapon reference
    if style in STYLE_ATTACK_PREFIX and random.random() < 0.5:
        verb = random.choice(STYLE_ATTACK_PREFIX[style])
        return (
            f"{attacker_name.upper()} {verb} {defender_name.upper()}'s "
            f"{location} with {pronoun} {weapon_name.lower()}"
        )
    else:
        # Category verb variant, weapon mentioned at the end
        cat_verbs = ATTACK_VERBS.get(weapon_category, ATTACK_VERBS["Oddball"])
        verb = random.choice(cat_verbs)
        return (
            f"{attacker_name.upper()} {verb} "
            f"{defender_name.upper()}'s {location} with {pronoun} {weapon_name.lower()}"
        )


# ---------------------------------------------------------------------------
# HIT VERB LINES (weapon makes contact)
# Format: "{attacker}'s {weapon} {hit_verb} {defender}'s {hit_location}!"
# ---------------------------------------------------------------------------

HIT_VERBS: dict[str, list[str]] = {
    "Sword/Knife"  : ["bites into", "slices into", "cuts into", "finds"],
    "Axe/Pick"     : ["bites into", "chops into", "cleaves into", "punches into"],
    "Hammer/Mace"  : ["crashes into", "slams into", "smashes into", "crunches into"],
    "Polearm/Spear": ["drives into", "punches into", "thrusts into", "buries itself in"],
    "Flail"        : ["lashes into", "wraps around and cracks into", "crashes into",
                      "whips into"],
    "Stave"        : ["cracks into", "strikes", "slams into"],
    "Shield"       : ["slams into", "crashes into", "bashes into"],
    "Oddball"      : ["punches into", "cracks into", "finds", "hits"],
}

# Lizardfolk-specific hit verbs when using claws, tail, or feet in martial combat
LIZARDFOLK_HIT_VERBS: dict[str, list[str]] = {
    "claw"  : ["rakes across", "shreds", "tears into", "slashes across", "rends"],
    "kick"  : ["crashes into", "smashes into", "crushes into", "drives into"],
    "tail"  : ["whips across", "lashes into", "sweeps across", "crashes into"],
}

HIT_TARGETS = {
    "Head"    : ["headgear", "helm", "skull", "head", "temple"],
    "Chest"   : ["chest armor", "ribs", "breastplate", "torso", "chest"],
    "Abdomen" : ["midsection", "gut", "belly armor", "flank"],
    "Primary Arm"  : ["weapon arm", "sword arm", "armor on the arm"],
    "Secondary Arm": ["shield arm", "off arm", "forearm armor"],
    "Primary Leg"  : ["primary leg", "lead leg", "thigh"],
    "Secondary Leg": ["rear leg", "trailing leg"],
    "None"    : ["armor", "body", "torso"],
}

HIT_ANNOUNCEMENTS = [
    "{attacker}'s accuracy is rewarded!",
    "{attacker} finds the opening!",
    "The blow connects!",
    "{attacker} gets past {defender}'s guard!",
    "{attacker} barely gets past {defender}'s defenses!",
    "The {weapon} finds its mark!",
]


def hit_line(
    attacker_name : str,
    defender_name : str,
    weapon_name   : str,
    weapon_category: str,
    aim_point     : str,
    hit_precision : str = "normal",  # "precise", "normal", "barely"
    attacker_race : str = None,       # For Lizardfolk special handling
) -> list[str]:
    """
    Return 1-2 lines describing a successful hit.
    hit_precision affects whether an announcement line precedes the hit.
    If attacker is Lizardfolk using Open Hand, use claw/tail/kick descriptions.
    """
    lines = []

    # Announce the hit if it was a precise or barely-made blow
    if hit_precision == "precise" or random.random() < 0.25:
        ann = random.choice(HIT_ANNOUNCEMENTS).format(
            attacker=attacker_name.upper(),
            defender=defender_name.upper(),
            weapon  =weapon_name.lower(),
        )
        lines.append(ann)

    # Lizardfolk with Open Hand use special claw/tail/kick descriptions
    if attacker_race == "Lizardfolk" and weapon_name == "Open Hand":
        attack_types = ["claw", "kick", "tail"]
        attack_type = random.choice(attack_types)

        verb_pool = LIZARDFOLK_HIT_VERBS.get(attack_type, LIZARDFOLK_HIT_VERBS["claw"])
        verb = random.choice(verb_pool)
        target_pool = HIT_TARGETS.get(aim_point, HIT_TARGETS["None"])
        target = random.choice(target_pool)

        # Create attack type descriptor
        attack_desc = {
            "claw": "claws",
            "kick": "powerful kick",
            "tail": "lashing tail",
        }.get(attack_type, "claws")
        
        lines.append(
            f"{attacker_name.upper()}'s {attack_desc} "
            f"{verb} {defender_name.upper()}'s {target}!"
        )
    else:
        # Standard weapon-based hit description
        verb_pool = HIT_VERBS.get(weapon_category, HIT_VERBS["Oddball"])
        verb = random.choice(verb_pool)
        target_pool = HIT_TARGETS.get(aim_point, HIT_TARGETS["None"])
        target = random.choice(target_pool)
        lines.append(
            f"{attacker_name.upper()}'s {weapon_name.lower()} "
            f"{verb} {defender_name.upper()}'s {target}!"
        )
    return lines


# ---------------------------------------------------------------------------
# DAMAGE DESCRIPTION LINES
# ---------------------------------------------------------------------------

DAMAGE_LINES: dict[str, dict[str, list[str]]] = {
    "Slashing": {
        "Heavy": [
            "   The blade carves a horrific canyon through flesh and muscle!",
            "   A terrible slash opens wide, spilling blood in sheets!",
            "   The edge shears through meat with savage force!",
            "   A gruesome flap of skin and muscle is laid open!",
            "   The strike slices deep, nearly severing the limb!",
            "   Blood erupts as the blade cuts a vital channel!",
            "   The slash leaves a ragged, gaping wound!",
            "   Flesh parts violently beneath the keen edge!",
            "   A horrific cut is torn across the warrior's torso!",
            "   The blade bites deep and opens the body!",
            "   A savage slash nearly takes the warrior's arm!",
            "   The strike opens a long, ghastly wound!",
            "   Blood sprays wildly from the deep slash!",
            "   The edge cleaves through muscle and sinew!",
            "   A brutal cut lays the warrior's side open!",
        ],
        "Medium": [
            "   The blade opens a deep, bleeding gash!",
            "   A clean slash draws a heavy flow of blood!",
            "   The weapon cuts a painful channel through flesh!",
            "   A long, weeping laceration is left behind!",
            "   The strike slices through skin and muscle!",
            "   Blood runs freely from the fresh cut!",
            "   The blade leaves a wide, angry wound!",
            "   A solid slash opens across the warrior's body!",
            "   The edge bites deep and draws crimson!",
            "   A painful cut is carved into the target!",
        ],
        "Light": [
            "   The blade merely kisses the skin!",
            "   A shallow cut appears along the surface!",
            "   The weapon skims across and draws a thin line!",
            "   Only a superficial slash is left behind!",
            "   The strike glances off, leaving a minor score!",
            "   A light cut wells up with a few drops of blood!",
            "   The edge scrapes across the skin!",
            "   A thin red line marks where the blade passed!",
            "   The slash is more sting than true damage!",
            "   Blood beads along a shallow graze!",
        ],
    },
    "Piercing": {
        "Heavy": [
            "   The point drives deep into the body with brutal force!",
            "   The weapon punches through flesh and out the other side!",
            "   A horrific puncture wound is torn through the warrior!",
            "   The strike impales the target with savage power!",
            "   The point sinks in and finds something vital!",
            "   A gaping hole is left where the weapon withdrew!",
            "   The thrust punches straight through armor and meat!",
            "   The warrior is skewered by the powerful strike!",
            "   Blood gushes from the deep puncture!",
            "   The point drives in with bone-cracking force!",
        ],
        "Medium": [
            "   The point sinks deep and draws a heavy flow!",
            "   A clean puncture wound is left behind!",
            "   The weapon drives in and comes out red!",
            "   Blood wells up from the deep stab!",
            "   The thrust punches through muscle and out again!",
            "   A painful hole is torn into the warrior's body!",
            "   The point finds meat and draws freely!",
            "   A solid stab opens a bleeding channel!",
            "   Blood flows steadily from the puncture!",
            "   The weapon sinks in and leaves a deep wound!",
        ],
        "Light": [
            "   The point merely pricks the skin!",
            "   A shallow puncture appears!",
            "   The weapon skims in and draws a thin bead of blood!",
            "   Only a minor stab wound is left behind!",
            "   The thrust glances off, leaving a small hole!",
            "   A light prick wells up with a few drops!",
            "   The point barely breaks the surface!",
            "   A superficial stab mark appears!",
            "   The weapon nicks the flesh and withdraws!",
            "   Blood beads from a shallow puncture!",
        ],
    },
    "Bludgeoning": {
        "Heavy": [
            "   The blow lands with bone-shattering force!",
            "   A sickening crunch echoes as bone breaks!",
            "   The strike caves in flesh and crushes what lies beneath!",
            "   The impact rattles the warrior's entire skeleton!",
            "   A devastating smash pulps muscle and bone!",
            "   The hit lands like a falling anvil!",
            "   Bone gives way with a horrible crack!",
            "   The warrior is smashed backward by the brutal force!",
            "   The blow turns the target area into a bloody ruin!",
            "   A crushing impact echoes across the arena!",
        ],
        "Medium": [
            "   The strike lands with heavy, punishing force!",
            "   A solid crunch is heard as the blow connects!",
            "   The hit drives the air from the warrior's lungs!",
            "   The weapon smashes into flesh with satisfying weight!",
            "   A painful bruise forms beneath the skin!",
            "   The blow rocks the warrior back on their heels!",
            "   The strike connects with meaty impact!",
            "   A heavy thud echoes as the weapon lands!",
            "   The hit leaves a deep, angry bruise!",
            "   The warrior staggers from the solid impact!",
        ],
        "Light": [
            "   The blow lands lightly, more sting than damage!",
            "   A dull thud is all that results!",
            "   The strike barely connects with force!",
            "   The hit is more jarring than damaging!",
            "   The weapon smacks against the body with little effect!",
            "   A light impact rocks the warrior slightly!",
            "   The blow stings but does little real harm!",
            "   The strike connects with minimal force!",
            "   A weak smack is all the warrior feels!",
            "   The hit lands with little more than a slap!",
        ],
    },
    "Cleaving": {
        "Heavy": [
            "   The strike cleaves through bone and muscle with terrifying force!",
            "   The blow splits the warrior wide open in a horrific wound!",
            "   The attack hacks deep into flesh, nearly severing the limb!",
            "   The weapon tears a gruesome channel through the body!",
            "   The strike cleaves violently through meat and bone!",
            "   A devastating chop lays the warrior's side open!",
            "   The blow cuts through the target with savage power!",
            "   The strike splits flesh and bone in a single brutal motion!",
            "   The weapon cleaves a massive, gaping wound!",
            "   The attack hacks through the warrior with bone-splitting force!",
            "   A horrific cleave nearly takes the limb!",
            "   The blow tears a ragged canyon through the body!",
            "   The strike cleaves with unstoppable momentum!",
            "   The weapon splits the warrior open with brutal efficiency!",
            "   A terrible cleaving wound is torn into the target!",
        ],
        "Medium": [
            "   The strike cleaves a deep, bleeding wound!",
            "   The blow hacks into flesh with solid force!",
            "   The attack cuts a wide, painful channel!",
            "   The weapon cleaves through muscle and draws heavy blood!",
            "   A powerful chop opens a long, weeping gash!",
            "   The strike cleaves deeply into the warrior!",
            "   The blow hacks a painful wound into the body!",
            "   The attack cleaves through skin and meat!",
            "   The weapon cuts a deep, angry furrow!",
            "   The strike cleaves with punishing weight!",
        ],
        "Light": [
            "   The strike merely grazes with a cleaving edge!",
            "   The blow skims across and leaves a shallow chop!",
            "   The attack nicks the warrior lightly!",
            "   The weapon glances off in a minor cleave!",
            "   A light chop scrapes across the surface!",
            "   The strike barely breaks the skin with its edge!",
            "   The blow lands as little more than a cleaving nick!",
            "   The attack skims across and draws a thin line!",
            "   The weapon kisses the flesh with a shallow chop!",
            "   The strike leaves only a superficial cleave!",
        ],
    },
    "Generic": {
        "Heavy": [
            "   The strike lands with devastating force!",
            "   A horrific wound is torn open by the blow!",
            "   The attack hits with bone-crushing power!",
            "   Blood erupts violently from the impact!",
            "   The blow caves in flesh and crushes what lies beneath!",
            "   A terrible wound is left in the wake of the strike!",
            "   The hit lands with savage, punishing force!",
            "   Blood sprays wildly as the blow connects!",
            "   The strike nearly folds the warrior in half!",
            "   A gruesome wound is carved into the body!",
        ],
        "Medium": [
            "   The strike lands with solid, painful force!",
            "   A deep wound is opened by the blow!",
            "   The attack connects heavily and draws blood!",
            "   The hit rocks the warrior back on their heels!",
            "   A painful wound is left in the wake of the strike!",
            "   Blood flows steadily from the fresh injury!",
            "   The blow lands with satisfying weight!",
            "   The strike opens a bleeding channel!",
            "   The attack hits hard enough to stagger!",
            "   A solid wound is carved into the warrior!",
        ],
        "Light": [
            "   The strike barely breaks the skin!",
            "   The blow glances off and draws a thin line!",
            "   The attack skims across the surface!",
            "   Only a superficial wound is left behind!",
            "   The hit stings more than it harms!",
            "   Blood beads up along a minor graze!",
            "   The strike lands lightly and is shrugged off!",
            "   A shallow cut appears on the skin!",
            "   The blow merely kisses the flesh!",
            "   The attack draws only a few drops of blood!",
        ],
    },
}

# Map weapon categories to damage types
_WEAPON_DAMAGE_TYPE: dict[str, str] = {
    "Sword/Knife":    "Slashing",
    "Axe/Pick":       "Cleaving",
    "Hammer/Mace":    "Bludgeoning",
    "Polearm/Spear":  "Piercing",
    "Flail":          "Bludgeoning",
    "Shield":         "Bludgeoning",
    "Oddball":        "Generic",
}


def damage_line(damage: int, max_hp: int, weapon_category: str = "Oddball") -> str:
    """Return a damage description line based on damage severity and weapon type."""
    pct = damage / max(1, max_hp)
    if   pct < 0.12: severity = "Light"
    elif pct < 0.30: severity = "Medium"
    else:            severity = "Heavy"

    dmg_type = _WEAPON_DAMAGE_TYPE.get(weapon_category, "Generic")
    pool = DAMAGE_LINES[dmg_type][severity]
    return random.choice(pool)


# ---------------------------------------------------------------------------
# SIGNATURE FLAVOR LINES
# ---------------------------------------------------------------------------
# Trigger when warrior has weapon skill >= 5 and lands a critical hit (25% chance).
# When triggered, damage is floored at medium (12% of max HP) minimum.
# Keys are weapon display names. Returns None for any weapon not listed.

SIGNATURE_LINES: dict[str, list[str]] = {

    # ====================== SWORDS & KNIVES ======================
    "Stiletto": [
        "{name} darts in like a striking viper, driving the stiletto deep with surgical precision!",
        "With blinding speed {name} buries the stiletto to the hilt in a vital gap!",
        "{name} twists the stiletto viciously, opening a hidden and deadly wound!",
        "The stiletto flashes in {name}'s hand as it seeks a fatal opening!",
        "{name} leaps forward, stiletto plunging with surgical cruelty!",
        "In a blur of motion {name} strikes with the stiletto again and again!",
        "{name} drives the stiletto home with cold, calculated intent!",
        "The stiletto finds its mark as {name} exploits a momentary weakness!",
        "{name} slips the stiletto past defenses and sinks it deep!",
        "With expert precision {name} delivers a killing thrust with the stiletto!",
    ],
    "Knife": [
        "{name} closes the distance and drives the knife home with brutal efficiency!",
        "In a deadly flurry {name} stabs repeatedly with the knife!",
        "{name} slashes and thrusts with the knife in a whirlwind of steel!",
        "The knife flashes as {name} strikes from an unexpected angle!",
        "{name} plunges the knife deep, seeking to end the fight quickly!",
        "With practiced savagery {name} works the knife into vulnerable flesh!",
        "The knife finds its mark as {name} exploits every opening!",
        "{name} drives the knife upward with lethal intent!",
        "A blur of steel, {name} strikes fast and hard with the knife!",
        "{name} twists the knife viciously after driving it home!",
    ],
    "Dagger": [
        "{name} lunges with perfect form, dagger thrusting true and deep!",
        "With fluid grace {name} cuts and thrusts with the dagger!",
        "{name} spins and drives the dagger into the opening with deadly accuracy!",
        "The dagger sings in {name}'s hand as it finds flesh and bone!",
        "{name} steps in close and delivers a powerful thrust with the dagger!",
        "In a controlled burst {name} strikes repeatedly with the dagger!",
        "{name} uses the dagger to devastating effect, cutting through defenses!",
        "The dagger flashes as {name} exploits a momentary gap!",
        "{name} drives the dagger home with expert precision!",
        "With masterful technique {name} makes the dagger dance!",
    ],
    "Short Sword": [
        "{name} lunges with perfect form, short sword thrusting true and deep!",
        "With fluid grace {name} cuts and thrusts with the short sword!",
        "{name} spins and drives the short sword into the opening with deadly accuracy!",
        "The short sword sings in {name}'s hand as it finds flesh and bone!",
        "{name} steps in close and delivers a powerful thrust with the short sword!",
        "In a controlled burst {name} strikes repeatedly with the short sword!",
        "{name} uses the short sword to devastating effect, cutting through defenses!",
        "The short sword flashes as {name} exploits a momentary gap!",
        "{name} drives the short sword home with expert precision!",
        "With masterful technique {name} makes the short sword dance!",
    ],
    "Epee": [
        "{name} extends the epee like a silver needle seeking a single perfect point!",
        "With lightning speed {name} delivers a precise epee thrust!",
        "{name} probes with the epee, finding the tiniest gap in the defenses!",
        "The epee flashes forward with aristocratic precision and lethal intent!",
        "{name} flicks the epee in a lightning-quick strike!",
        "With elegant control {name} drives the epee home!",
        "The epee dances on the edge of visibility as {name} attacks!",
        "A master's touch, {name} makes the epee strike with deadly focus!",
        "{name} uses the epee to exploit a momentary weakness with perfect form!",
        "The slender epee finds its mark as {name} strikes with surgical grace!",
    ],
    "Scimitar": [
        "{name} leaps into the air, scimitar slicing with unnerving cruelty!",
        "The scimitar arcs through the air as {name} delivers a devastating cut!",
        "{name} draws the scimitar in a wide, deadly crescent of steel!",
        "With fluid, flowing grace {name} carves a brutal path with the scimitar!",
        "The curved blade flashes as {name} strikes with lethal elegance!",
        "{name} spins and slashes with the scimitar in a whirlwind of death!",
        "The scimitar sings through the air as {name} attacks with precision!",
        "{name} uses the scimitar to open a vicious, sweeping wound!",
        "In a blur of motion {name} delivers a savage scimitar strike!",
        "{name} brings the scimitar down in a powerful, arcing slash!",
    ],
    "Long Sword": [
        "{name} steps forward and drives the longsword home with commanding authority!",
        "The longsword flashes as {name} delivers a powerful, controlled thrust!",
        "{name} swings the longsword in a clean, deadly arc!",
        "With measured power {name} plunges the longsword deep into the foe!",
        "{name} uses the longsword to devastating effect, cutting through defenses!",
        "The longsword strikes true as {name} exploits a momentary weakness!",
        "{name} drives the longsword forward with both hands and lethal intent!",
        "In a disciplined strike {name} makes the longsword sing!",
        "{name} steps in and delivers a masterful thrust with the longsword!",
        "The longsword finds its mark as {name} attacks with precision!",
    ],
    "Broad Sword": [
        "{name} swings the broadsword with solid, reliable force!",
        "{name} delivers a heavy practical cut, no frills, just devastating results!",
        "{name} carries the broadsword's message with straightforward power!",
        "Reliable and strong, {name}'s broadsword does exactly what is asked of it!",
        "{name}'s broadsword hacks forward with the confidence of a well-made tool!",
        "With practiced swings {name} makes the broadsword bite deep!",
        "The broadsword strikes with honest, crushing weight!",
        "A no-nonsense blow, {name} brings the broadsword down hard!",
        "{name} uses the broadsword to powerful effect in close quarters!",
        "{name} drives the broadsword home with brutal efficiency!",
    ],
    "Bastard Sword": [
        "{name} grips the bastard sword with both hands and cleaves downward with power!",
        "The bastard sword descends like judgment as {name} strikes!",
        "{name} swings the bastard sword in a devastating overhead blow!",
        "With expert control {name} delivers a crushing strike with the bastard sword!",
        "{name} uses the bastard sword to cut a wide, brutal path!",
        "The bastard sword flashes as {name} attacks with both speed and power!",
        "{name} drives the bastard sword home with tremendous force!",
        "In a powerful two-handed strike {name} makes the bastard sword sing!",
        "{name} adapts grip and delivers a flexible, lethal blow!",
        "The bastard sword finds the perfect balance of reach and power in {name}'s hands!",
    ],
    "Great Sword": [
        "{name} hefts the great sword and brings it down with terrifying force!",
        "The massive blade sweeps through the air as {name} attacks!",
        "{name} roars and drives the great sword forward with both hands!",
        "The great sword cleaves through the air with unstoppable momentum!",
        "{name} swings the great sword in a devastating, sweeping arc!",
        "With raw power {name} brings the great sword crashing down!",
        "The great sword strikes with the force of a falling tree!",
        "{name} delivers a mighty two-handed blow with the great sword!",
        "The enormous blade moves like thunder in {name}'s grip!",
        "{name} unleashes the great sword's full devastating potential!",
    ],

    # ====================== AXES & PICKS ======================
    "Hatchet": [
        "{name} flashes the hatchet forward in a quick, brutal chop!",
        "The hatchet bites deep as {name} strikes with savage speed!",
        "{name} hacks with the hatchet in a flurry of deadly strikes!",
        "Short, sharp, and mean, {name} makes the hatchet find its target!",
        "{name} throws the hatchet with deadly accuracy at close range!",
        "The hatchet moves with surprising speed in {name}'s hand!",
        "{name} delivers a vicious chop with the hatchet!",
        "A woodsman's tool turned lethal, {name} strikes true!",
        "{name} uses the hatchet to split bone and armor alike!",
        "The hatchet flashes as {name} presses the attack!",
    ],
    "Fransisca": [
        "{name} spins the fransisca through the air with deadly accuracy!",
        "The fransisca whistles as it flies toward its target!",
        "{name} hurls the fransisca with practiced precision!",
        "A dwarf-forged promise of pain, {name} throws the fransisca true!",
        "{name} delivers a spinning throw with the fransisca!",
        "The fransisca cuts a deadly path end over end!",
        "{name} makes the fransisca seek flesh and bone!",
        "With a warrior's toss {name} sends the fransisca flying!",
        "The fransisca returns to {name}'s hand after a perfect throw!",
        "{name} unleashes the fransisca with expert timing!",
    ],
    "Battle Axe": [
        "{name} swings the battle axe in a wide, crushing arc!",
        "The battle axe descends with bone-splitting power as {name} attacks!",
        "{name} brings the battle axe down with savage force!",
        "The axe bites deep as {name} delivers a brutal chop!",
        "{name} hacks with the battle axe in a flurry of deadly strikes!",
        "The battle axe cleaves through defenses as {name} presses forward!",
        "{name} swings the battle axe with practiced, deadly efficiency!",
        "The heavy axe crashes down with crushing intent!",
        "{name} delivers a powerful overhead chop with the battle axe!",
        "The battle axe finds its mark with dwarven strength behind it!",
    ],
    "Great Axe": [
        "{name} raises the great axe high and brings it down like thunder!",
        "The massive axe cleaves through the air with devastating force!",
        "{name} roars and swings the great axe in a terrifying arc!",
        "The great axe descends with unstoppable, bone-shattering power!",
        "{name} delivers a mighty two-handed chop with the great axe!",
        "The great axe hacks through flesh and bone with savage fury!",
        "{name} brings the great axe crashing down with earth-shaking force!",
        "The massive blade cleaves a horrific wound as {name} attacks!",
        "The great axe moves with unstoppable momentum in {name}'s hands!",
        "{name} unleashes the full wrath of the great axe!",
    ],
    "Small Pick": [
        "{name} drives the small pick deep with surgical cruelty!",
        "The small pick punches through armor as {name} strikes with precision!",
        "{name} slams the pick forward, seeking a vital gap!",
        "The pick bites deep as {name} exploits a weakness!",
        "{name} drives the small pick home with cold, calculated force!",
        "The small pick strikes with armor-piercing intent!",
        "{name} probes for a killing blow with the small pick!",
        "A needle of steel, {name} makes the small pick find its mark!",
        "{name} delivers a precise, vicious strike with the small pick!",
        "The small pick darts forward seeking vulnerable joints!",
    ],
    "Military Pick": [
        "{name} drives the military pick forward with brutal armor-piercing intent!",
        "The military pick seeks to punch through steel as {name} strikes!",
        "{name} crashes the pick forward, designed to crack helms and split breastplates!",
        "With practiced efficiency {name} finds its mark with the military pick!",
        "The military pick strikes with the cold certainty of a battlefield veteran!",
        "{name} exploits a gap and drives the military pick deep!",
        "The pick punches through defenses as {name} attacks!",
        "A weapon made for war, {name} makes the military pick sing!",
        "{name} delivers a devastating piercing blow with the military pick!",
        "The military pick bites deep into heavy armor!",
    ],
    "Pick Axe": [
        "{name} brings the pick axe down with mining fury meant to break stone and bone!",
        "The pick axe swings with devastating force as {name} attacks!",
        "{name} crashes the pick axe downward, looking to split anything in its path!",
        "A brutal tool turned weapon, {name} wields the pick axe with lethal purpose!",
        "The pick axe comes down with the mountain's anger behind it!",
        "{name} delivers a two-handed strike with the pick axe!",
        "The heavy pick axe demands respect through violence!",
        "{name} makes the pick axe crash down with crushing power!",
        "The pick axe strikes like a miner's rage given lethal form!",
        "{name} exploits the pick axe's weight for maximum damage!",
    ],

    # ====================== HAMMERS & MACES ======================
    "Hammer": [
        "{name} swings the hammer with straightforward bone-crushing intent!",
        "The hammer falls like judgment as {name} strikes!",
        "{name} delivers a solid, reliable strike with the hammer!",
        "With practiced swings {name} makes the hammer pulp armor and flesh!",
        "The hammer strikes with blunt, uncompromising force!",
        "{name} brings the hammer down with crushing weight!",
        "A straightforward blow, {name} makes the hammer connect hard!",
        "The hammer seeks to break what stands before it!",
        "{name} uses the hammer to devastating effect in close combat!",
        "The hammer crashes down with honest, brutal power!",
    ],
    "Mace": [
        "{name} swings the mace in a heavy, punishing arc!",
        "Flanged and brutal, {name}'s mace seeks to crush anything it touches!",
        "The mace falls with the weight of authority behind every blow!",
        "A weapon that speaks in broken bones, {name} wields the mace well!",
        "{name} delivers a crushing strike with the mace!",
        "The mace crashes forward, designed to end arguments permanently!",
        "{name} makes the mace connect with punishing force!",
        "The mace swings with straightforward, brutal honesty!",
        "{name} brings the mace down hard on the target!",
        "With solid intent {name} makes the mace do its work!",
    ],
    "Morningstar": [
        "{name} whips the morningstar in a deadly, spinning arc!",
        "The spiked ball crashes into the target with brutal force as {name} attacks!",
        "{name} swings the morningstar with crushing intent!",
        "The morningstar descends like a falling star of pain!",
        "With expert control {name} makes the morningstar seek the perfect angle!",
        "The morningstar promises agony with every rotation!",
        "{name} delivers a devastating blow with the morningstar!",
        "The spiked morningstar sings for flesh as {name} strikes!",
        "A cruel and bright weapon, {name} wields the morningstar with grace!",
        "{name} unleashes the morningstar in a whirlwind of spikes!",
    ],
    "War Hammer": [
        "{name} brings the war hammer down with earth-shaking power!",
        "The war hammer strikes with the force of a thunderclap!",
        "{name} swings the war hammer with devastating, concentrated force!",
        "The heavy hammer crashes down with bone-crushing intent!",
        "With half-orc strength behind it {name} makes the war hammer a siege engine!",
        "The war hammer falls like divine judgment!",
        "{name} delivers a crushing blow with the war hammer!",
        "The war hammer means to end the fight decisively!",
        "{name} brings the war hammer crashing down with tremendous power!",
        "A weapon built for breaking armor, {name} wields it masterfully!",
    ],
    "Maul": [
        "{name} hefts the maul and smashes it down with terrifying strength!",
        "The massive maul descends like doom itself!",
        "{name} brings the maul crashing down with unstoppable force!",
        "The maul cares nothing for finesse, {name} wields pure brute force!",
        "The maul swings like a falling tree, crushing everything in its path!",
        "{name} delivers a devastating two-handed smash with the maul!",
        "The maul moves with terrifying momentum as {name} attacks!",
        "When the maul moves, lesser warriors step back instinctively!",
        "{name} unleashes the full weight of the maul!",
        "The maul brings the battlefield's own weight down on its target!",
    ],
    "Club": [
        "{name} swings the club with simple, brutal honesty!",
        "The club seeks to break what it hits as {name} strikes!",
        "{name} brings the club down with raw, unrefined violence!",
        "A crude but effective weapon, {name} makes the club connect hard!",
        "The club moves like the first weapon humanity ever made, simple and final!",
        "{name} delivers a straightforward, crushing blow with the club!",
        "With honest intent {name} makes the club do its work!",
        "The club crashes forward, promising broken bones!",
        "{name} wields the club with dirty-fighter efficiency!",
        "The club strikes with brutal, no-nonsense power!",
    ],

    # ====================== POLEARMS & SPEARS ======================
    "Short Spear": [
        "{name} lunges forward, short spear thrusting with lethal precision!",
        "The short spear drives deep as {name} strikes with deadly reach!",
        "{name} tests defenses and finds gaps with the short spear!",
        "With confident thrusts {name} makes the short spear strike true!",
        "The short spear finds its mark with ease in {name}'s hands!",
        "{name} delivers a powerful, balanced thrust with the short spear!",
        "The short spear moves with the confidence of a favored weapon!",
        "A quick, potent strike, {name} makes the short spear bite deep!",
        "{name} exploits the short spear's speed and reach!",
        "The short spear lunges like a predator's fang!",
    ],
    "Boar Spear": [
        "{name} braces and drives the boar spear home with both hands!",
        "The boar spear impales the target with savage force as {name} attacks!",
        "{name} lunges forward, boar spear thrusting with lethal intent!",
        "The boar spear means to impale and hold, {name} strikes true!",
        "{name} finds the perfect angle for maximum damage with the boar spear!",
        "The boar spear strikes like a predator's fang, deep and final!",
        "{name} delivers a hunting-precision thrust with the boar spear!",
        "With practiced skill {name} makes the boar spear devastating!",
        "The boar spear drives forward with the power of a charging beast!",
        "{name} uses the boar spear to dictate the flow of battle!",
    ],
    "Long Spear": [
        "{name} extends the long spear and thrusts with deadly reach!",
        "The long spear punches forward like a striking serpent!",
        "{name} commands the space with the long spear's superior range!",
        "With calculated lethality {name} probes for weakness with the long spear!",
        "The long spear dictates the terms of the fight as {name} attacks!",
        "{name} delivers a disciplined, powerful thrust with the long spear!",
        "The long spear strikes from a distance lesser weapons cannot match!",
        "{name} makes the long spear find its mark with precision!",
        "A long, dangerous thrust, {name} exploits the spear's reach!",
        "The long spear moves with superior range and control!",
    ],
    "Pole Axe": [
        "{name} swings the pole axe in a wide, devastating arc!",
        "The pole axe combines reach and cleaving power as {name} strikes!",
        "{name} brings the pole axe down with the force of a woodsman's fury!",
        "With expert handling {name} finds the perfect moment for the pole axe!",
        "The pole axe moves like an extension of {name}'s rage!",
        "{name} delivers a versatile, brutal strike with the pole axe!",
        "The pole axe cleaves through the air with terrifying authority!",
        "A complex weapon, {name} wields the pole axe masterfully!",
        "{name} makes the pole axe find flesh with devastating effect!",
        "The pole axe swings in a wide arc of death!",
    ],
    "Halberd": [
        "{name} swings the halberd in a wide, sweeping arc of death!",
        "The halberd descends with axe, spike, and hook all at once!",
        "{name} brings the halberd down with devastating versatility!",
        "A weapon of war and execution, {name} wields the halberd with authority!",
        "With practiced mastery {name} finds the perfect angle with the halberd!",
        "The halberd strikes with the weight of a battlefield veteran's experience!",
        "{name} unleashes the halberd's full potential in a single blow!",
        "The halberd moves like a reaper's tool promising to end the fight!",
        "{name} delivers a complex, deadly strike with the halberd!",
        "The halberd brings multiple deadly edges to bear as {name} attacks!",
    ],

    # ====================== FLAILS ======================
    "Flail": [
        "{name} whirls the flail in a deadly, unpredictable arc!",
        "The flail lashes out like a striking serpent as {name} attacks!",
        "{name} swings the flail with expert, chaotic precision!",
        "The flail defies easy defense, {name} makes it find its mark!",
        "With expert timing {name} sends the flail past guard and shield!",
        "The flail moves with a mind of its own, hungry for contact!",
        "{name} delivers a vicious, wrapping strike with the flail!",
        "The flail lashes forward seeking any opening!",
        "A chaotic and vicious weapon, {name} wields it masterfully!",
        "{name} makes the flail dance in a deadly pattern!",
    ],
    "Bladed Flail": [
        "{name} whips the bladed flail in a storm of razor edges!",
        "The bladed flail sings a cruel song as its edges cut through the air!",
        "{name} delivers a vicious strike with the bladed flail!",
        "The bladed flail leaves nothing untouched as {name} attacks!",
        "With vicious intent {name} makes the bladed flail tear and rend!",
        "The bladed flail moves like a storm of razor edges!",
        "{name} unleashes the bladed flail in a whirlwind of pain!",
        "The cruel edges of the bladed flail promise terrible wounds!",
        "A weapon of pain and blood, {name} wields it with deadly grace!",
        "{name} makes the bladed flail lash forward with terrifying effect!",
    ],
    "War Flail": [
        "{name} swings the war flail with crushing, unstoppable force!",
        "The heavy war flail crashes down with bone-breaking power!",
        "{name} delivers a devastating blow with the war flail!",
        "The war flail comes down like a falling building!",
        "With raw power {name} makes the war flail a siege engine!",
        "The war flail moves with terrifying momentum as {name} attacks!",
        "A brutal and heavy weapon, {name} wields it masterfully!",
        "The war flail promises broken bones and shattered shields!",
        "{name} unleashes the war flail with earth-shaking force!",
        "The war flail strikes with devastating crushing intent!",
    ],
    "Battle Flail": [
        "{name} creates a whirlwind of steel and death with the battle flail!",
        "The battle flail defies prediction and defense as {name} strikes!",
        "{name} lashes out in every direction with the battle flail!",
        "With expert control {name} turns the air itself into a weapon!",
        "The battle flail moves like a living thing hungry for carnage!",
        "{name} delivers a monstrous strike with the battle flail!",
        "A storm of pain, {name} wields the battle flail with precision!",
        "The battle flail swings in a chaotic, deadly pattern!",
        "{name} makes the battle flail crash down with overwhelming force!",
        "The battle flail creates chaos and destruction as {name} attacks!",
    ],

    # ====================== STAVES ======================
    "Quarterstaff": [
        "{name} moves the quarterstaff with fluid, balanced precision!",
        "The quarterstaff strikes from both ends as {name} attacks!",
        "{name} makes the quarterstaff dance through the air!",
        "With practiced mastery {name} probes and strikes in perfect rhythm!",
        "The quarterstaff moves like an extension of {name}'s will!",
        "{name} delivers a disciplined strike with the quarterstaff!",
        "A weapon of control and discipline, {name} wields it beautifully!",
        "The quarterstaff finds gaps in the defense with ease!",
        "{name} uses the quarterstaff to devastating effect in close combat!",
        "The quarterstaff flows through a deadly combination!",
    ],
    "Great Staff": [
        "{name} swings the great staff with heavy, sweeping power!",
        "The great staff demands space as {name} attacks!",
        "{name} brings the great staff down with deliberate crushing authority!",
        "With two-handed strength {name} turns the great staff into a battering ram!",
        "The great staff moves with the weight of ancient tradition!",
        "{name} delivers a powerful sweeping strike with the great staff!",
        "The larger staff crashes down with impressive force!",
        "{name} makes the great staff connect with heavy authority!",
        "A more imposing weapon, {name} wields the great staff masterfully!",
        "The great staff strikes with deliberate, crushing power!",
    ],

    # ====================== SHIELDS ======================
    "Buckler": [
        "{name} darts forward and slams the buckler into the foe with force!",
        "The buckler strikes with surprising, compact power as {name} attacks!",
        "{name} snaps the buckler into position for a quick, vicious strike!",
        "With practiced ease {name} makes the buckler find the perfect angle!",
        "The buckler moves like a second skin, protecting and striking at once!",
        "{name} delivers a compact, powerful blow with the buckler!",
        "A nimble shield, {name} turns the buckler into an offensive weapon!",
        "The buckler darts to meet the enemy with surprising force!",
        "{name} uses the buckler to create an opening and strike!",
        "The buckler snaps forward in a quick, aggressive bash!",
    ],
    "Target Shield": [
        "{name} charges with the target shield, slamming it forward with solid force!",
        "The target shield catches blows and creates openings as {name} attacks!",
        "{name} makes the target shield absorb impact and strike back!",
        "With dwarven practicality {name} wields the target shield aggressively!",
        "The target shield moves with steady, reliable power!",
        "{name} delivers a confident bash with the target shield!",
        "A well-balanced shield, {name} turns it into a weapon!",
        "The target shield snaps forward with crushing presence!",
        "{name} uses the target shield to dictate the pace of the fight!",
        "The target shield strikes with solid, dependable force!",
    ],
    "Tower Shield": [
        "{name} charges like a moving iron wall with the tower shield!",
        "The massive tower shield crashes into the opponent with crushing weight!",
        "{name} advances with the tower shield's deliberate, imposing presence!",
        "With half-orc strength {name} turns the tower shield into an unstoppable force!",
        "The tower shield dares the enemy to strike as {name} attacks!",
        "{name} slams the tower shield forward with earth-shaking power!",
        "A massive barrier of steel, {name} wields it as a weapon!",
        "The tower shield moves with the weight of certainty!",
        "{name} delivers a crushing bash with the tower shield!",
        "The tower shield becomes an iron fortress in {name}'s hands!",
    ],

    # ====================== ODDBALLS ======================
    "Cestus": [
        "{name} strikes with the cestus, turning the hand into a steel-toothed mace!",
        "The cestus punches forward seeking to crush bone and pulp flesh!",
        "With martial precision {name} makes the cestus find the perfect striking surface!",
        "The cestus moves like an iron gauntlet given deadly purpose!",
        "{name} delivers a brutal close-range strike with the cestus!",
        "A bare fist given steel teeth, {name} wields the cestus with fury!",
        "{name} unleashes a devastating series of cestus punches!",
        "The cestus strikes with the fury of a reinforced fist!",
        "{name} makes the cestus connect with crushing power!",
        "The cestus turns every punch into a lethal blow!",
    ],
    "Trident": [
        "{name} lunges forward, trident thrusting with three deadly points!",
        "The trident strikes with fisher's precision as {name} attacks!",
        "{name} drives the trident deep, seeking to pin and hold its prey!",
        "With practiced skill {name} finds the perfect angle with the trident!",
        "The trident moves like a predator's claw designed to impale!",
        "{name} delivers a powerful, multi-point thrust with the trident!",
        "The trident lunges with lethal intent in {name}'s hands!",
        "A weapon of the arena and the sea, {name} wields the trident masterfully!",
        "{name} makes the trident find vital flesh with ease!",
        "The trident thrusts forward with dangerous, three-pronged reach!",
    ],
    "Net": [
        "{name} casts the net with expert timing, seeking to entangle and trap!",
        "The net whips through the air as {name} attacks!",
        "{name} makes the net dance with dangerous grace!",
        "With expert timing {name} robs the opponent of mobility with the net!",
        "The net flies forward, its weighted edges hungry for limbs!",
        "{name} delivers a frustrating, entangling strike with the net!",
        "The net moves like a living snare looking to bind its prey!",
        "A weapon of control, {name} wields the net with precision!",
        "{name} casts the net to create chaos and openings!",
        "The net wraps around the target as {name} presses the advantage!",
    ],
    "Scythe": [
        "{name} sweeps the scythe in a wide, deadly arc promising harvest of flesh!",
        "The scythe reaps without mercy as {name} attacks!",
        "{name} makes the scythe move with graceful, terrifying efficiency!",
        "A farmer's tool turned instrument of death, {name} wields the scythe beautifully!",
        "The scythe cuts through the air like fate itself!",
        "{name} delivers a vicious, sweeping strike with the scythe!",
        "With practiced sweeps {name} opens terrible wounds with the scythe!",
        "The scythe moves with cold, inevitable purpose!",
        "{name} makes the scythe sing as it reaps its grim harvest!",
        "The scythe sweeps forward with devastating grace!",
    ],
    "Great Pick": [
        "{name} slams the great pick downward with crushing force!",
        "The great pick drives deep, piercing armor and bone alike!",
        "{name} brings the great pick down with devastating power!",
        "The massive pick punches through defenses with brutal efficiency!",
        "With unstoppable piercing purpose {name} wields the great pick!",
        "The great pick strikes like a siege engine as {name} attacks!",
        "{name} delivers a mighty overhead strike with the great pick!",
        "The great pick seeks to punch through anything in its path!",
        "A weapon of pure penetration, {name} makes it unstoppable!",
        "The great pick crashes down with mountain-shattering force!",
    ],
    "Javelin": [
        "{name} launches the javelin with hunting precision!",
        "The javelin cuts the air with deadly speed as {name} throws!",
        "{name} hurls the javelin with the intent to impale and end the threat!",
        "With practiced form {name} makes the javelin seek a vital point!",
        "The javelin strikes like a bolt from the sky, sudden and final!",
        "{name} delivers a powerful thrown strike with the javelin!",
        "The javelin flies true in {name}'s expert hands!",
        "A thrown spear seeking its mark, {name} makes it lethal!",
        "{name} exploits the javelin's speed and accuracy!",
        "The javelin launches with deadly intent and perfect form!",
    ],
    "Ball & Chain": [
        "{name} swings the ball and chain in a heavy, crushing arc!",
        "The ball and chain defies easy defense as {name} attacks!",
        "{name} brings the ball and chain down with devastating smashing force!",
        "With raw power {name} makes the ball and chain break bone and spirit!",
        "The ball and chain moves like a falling anchor promising ruin!",
        "{name} delivers a brutal, unpredictable strike with the ball and chain!",
        "The heavy chain whips forward with crushing intent!",
        "A weapon that can finish a fight in moments, {name} wields it dangerously!",
        "The ball and chain crashes down with terrifying momentum!",
        "{name} unleashes the ball and chain with overwhelming force!",
    ],
    "Bola": [
        "{name} whips the bola through the air seeking to tangle and trip!",
        "The bola dances with dangerous intent as {name} attacks!",
        "{name} sends the bola flying, its weighted cords hungry for limbs!",
        "With practiced accuracy {name} robs the opponent of mobility with the bola!",
        "The bola moves like a living snare looking to wrap and bind!",
        "{name} delivers an entangling strike with expert timing!",
        "The bola whips forward seeking to cause a fall!",
        "A weapon of control and frustration, {name} wields the bola masterfully!",
        "{name} makes the bola wrap around the target's legs!",
        "The bola flies with deadly accuracy in {name}'s hands!",
    ],
    "Heavy Barbed Whip": [
        "{name} lashes out with the heavy barbed whip, cruel cutting intent clear!",
        "The barbed whip seeks to tear and yank as {name} strikes!",
        "{name} cracks the heavy barbed whip through the air promising agony!",
        "With expert flicks {name} finds exposed flesh with the barbed whip!",
        "The barbed whip moves like a serpent with steel teeth!",
        "{name} delivers a vicious, lashing strike with the heavy barbed whip!",
        "The whip wraps and cuts in the same motion!",
        "A weapon of pain and control, {name} wields the barbed whip with precision!",
        "{name} makes the heavy barbed whip crack with lethal effect!",
        "The barbed whip lashes forward seeking vulnerable limbs!",
    ],
    "Swordbreaker": [
        "{name} moves the swordbreaker with the intent to catch and shatter steel!",
        "The swordbreaker waits for the perfect moment to trap a blade as {name} attacks!",
        "{name} darts the swordbreaker forward, its notches hungry for enemy weapons!",
        "With expert timing {name} seeks to disarm and destroy with the swordbreaker!",
        "The swordbreaker moves like a predator of other weapons!",
        "{name} delivers a specialized, disruptive strike with the swordbreaker!",
        "The swordbreaker snaps forward seeking to trap and break!",
        "A specialized weapon, {name} wields the swordbreaker with deadly intent!",
        "{name} makes the swordbreaker bite into an incoming blade!",
        "The swordbreaker waits patiently then strikes with perfect timing!",
    ],
    "Open Hand": [
        "{name} strikes with open hand in a blur of martial precision!",
        "{name} unleashes a devastating series of unarmed strikes!",
        "Empty handed but deadly, {name} flows through a lethal combination!",
        "With disciplined focus {name} finds the perfect striking surface!",
        "{name} delivers a masterful unarmed blow with perfect technique!",
        "The open hand moves with fluid, controlled power!",
        "{name} strikes like a martial artist's technique given lethal purpose!",
        "A blur of motion, {name} makes open hand devastating!",
        "{name} flows through a deadly unarmed sequence!",
        "With empty hands {name} proves skill can overcome steel!",
    ],
}


def signature_line(attacker_name: str, weapon_name: str) -> Optional[str]:
    """
    Return a signature flavor line for a critical hit, or None if no pool exists
    for this weapon. Caller is responsible for the skill >= 5 and chance checks.
    """
    pool = SIGNATURE_LINES.get(weapon_name)
    if not pool:
        return None
    return random.choice(pool).format(name=attacker_name.upper())


# ---------------------------------------------------------------------------
# MISS LINES
# ---------------------------------------------------------------------------

MISS_LINES = [
    "{attacker} misses wildly",
    "{attacker}'s {weapon} cuts only air",
    "{attacker} fails to connect",
    "{attacker} swings and misses badly",
    "{attacker}'s attack goes wide",
    "{attacker} whiffs completely",
    "{attacker}'s aim is off, the blow finds nothing",
]


def miss_line(attacker_name: str, weapon_name: str) -> str:
    template = random.choice(MISS_LINES)
    return template.format(
        attacker=attacker_name.upper(),
        weapon  =weapon_name.lower(),
    )


# ---------------------------------------------------------------------------
# PARRY LINES
# ---------------------------------------------------------------------------

PARRY_LINES_SUCCESS = [
    "{defender} is ready for the strike, and deftly parries it!",
    "{defender} makes an extraordinary effort, and parries the strike!",
    "{defender}'s defenses are particularly strong!",
    "{defender} turns the blow aside with skill!",
    "{defender} catches the weapon and deflects it cleanly!",
    "{defender}'s guard holds firm!",
    "{defender} has a plan: don't get hit!",
]

PARRY_LINES_BARELY = [
    "{defender} barely gets the parry off!",
    "{defender} makes a desperate last-moment parry!",
    "{defender} just manages to deflect the blow!",
]

DEFENSE_POINT_LINES = [
    "{defender} is paying special attention to not being hit there!",
    "{defender}'s plan is not to get hit!",
    "{defender} has that area well covered!",
]


def parry_line(defender_name: str, barely: bool = False, defense_point_active: bool = False) -> str:
    if defense_point_active and random.random() < 0.5:
        return random.choice(DEFENSE_POINT_LINES).format(defender=defender_name.upper())
    if barely:
        return random.choice(PARRY_LINES_BARELY).format(defender=defender_name.upper())
    return random.choice(PARRY_LINES_SUCCESS).format(defender=defender_name.upper())


# ---------------------------------------------------------------------------
# DODGE LINES
# ---------------------------------------------------------------------------

DODGE_LINES = [
    "{defender} sidesteps the attack nimbly!",
    "{defender} twists out of the way!",
    "{defender} cartwheels away from the strike!",
    "{defender} ducks under the blow!",
    "{defender} moves just enough to avoid the hit!",
    "{defender} is not where the weapon expects!",
]


def dodge_line(defender_name: str) -> str:
    return random.choice(DODGE_LINES).format(defender=defender_name.upper())


# ---------------------------------------------------------------------------
# DEFENSE INTENT LINES (defender's reaction shown before result is known)
# ---------------------------------------------------------------------------

DEFENSE_INTENT_PARRY = [
    "{defender} braces to meet the attack!",
    "{defender} raises {his} guard against the incoming blow!",
    "{defender} is ready for {his} opponent's move!",
    "{defender} eyes the incoming strike carefully!",
    "{defender} sets {his} feet and prepares to deflect!",
    "{defender} shifts weight, preparing to parry!",
    "{defender} tightens {his} grip and watches for the opening!",
    "{defender} reads the attack and reacts!",
    "{defender} commits to a solid defense!",
    "{defender} is eagerly defending!",
]

DEFENSE_INTENT_DODGE = [
    "{defender} is already moving!",
    "{defender} looks to slip the blow!",
    "{defender} watches for the angle of attack!",
    "{defender} plans to avoid being where the weapon lands!",
    "{defender} shifts {his} weight to dodge!",
    "{defender} keeps {his} feet light and ready!",
    "{defender}'s footwork is anticipating trouble!",
    "{defender} stays mobile, looking for the escape!",
    "{defender} isn't planning to stand still for this!",
    "{defender}'s plan is not to get hit!",
]


def defense_intent_line(defender_name: str, gender: str, uses_parry: bool) -> str:
    pronoun = "his" if gender == "Male" else "her"
    pool = DEFENSE_INTENT_PARRY if uses_parry else DEFENSE_INTENT_DODGE
    return random.choice(pool).format(defender=defender_name.upper(), his=pronoun)


# ---------------------------------------------------------------------------
# LOW HP STATUS COMMENTARY
# ---------------------------------------------------------------------------

_LOW_HP_TIER1 = [   # 30–50% HP remaining
    "{warrior} is showing signs of the punishment received!",
    "{warrior} is taking this fight on the chin!",
    "The damage is starting to add up for {warrior}!",
    "{warrior} is breathing harder now!",
    "{warrior} looks like {he} could use a moment to collect {himself}!",
]

_LOW_HP_TIER2 = [   # 15–30% HP remaining
    "{warrior} is in serious trouble!",
    "{warrior} is covered in blood, and not all of it is the opponent's!",
    "The crowd senses {warrior} is running out of options!",
    "{warrior} is surviving on determination alone at this point!",
    "{warrior} is desperately wounded and still fighting!",
    "{warrior} looks deathly pale!",
]

_LOW_HP_TIER3 = [   # below 15% HP remaining
    "{warrior} would make a corpse envious!",
    "{warrior} is drenched in blood!",
    "{warrior} is barely standing, sheer will is all that remains!",
    "The end is near for {warrior}!",
    "{warrior} staggers but somehow refuses to fall!",
    "{warrior} is one solid hit away from the Dark Arena!",
]


def low_hp_line(warrior_name: str, gender: str, hp_pct: float) -> Optional[str]:
    """Return a low-HP status line, or None if HP is above threshold / random skip."""
    pronoun  = "he" if gender == "Male" else "she"
    reflexive = "himself" if gender == "Male" else "herself"
    if hp_pct >= 0.50:
        return None
    if hp_pct >= 0.30:
        if random.random() > 0.30:   # fire ~30% of the time in this range
            return None
        pool = _LOW_HP_TIER1
    elif hp_pct >= 0.15:
        if random.random() > 0.50:
            return None
        pool = _LOW_HP_TIER2
    else:
        if random.random() > 0.70:
            return None
        pool = _LOW_HP_TIER3
    return random.choice(pool).format(
        warrior=warrior_name.upper(), he=pronoun, himself=reflexive
    )


# ---------------------------------------------------------------------------
# COUNTERSTRIKE LINE (special attack after a successful parry)
# ---------------------------------------------------------------------------

COUNTERSTRIKE_LINES = [
    "{attacker} seizes the opening and launches a counter-attack!",
    "{attacker} turns the parry into an immediate counter!",
    "{attacker}'s counter-strike catches {foe} completely off-guard!",
    "{attacker} makes {foe} pay for the reckless attack!",
]


def counterstrike_line(attacker_name: str, foe_name: str) -> str:
    return random.choice(COUNTERSTRIKE_LINES).format(
        attacker=attacker_name.upper(), foe=foe_name.upper()
    )


# ---------------------------------------------------------------------------
# DECOY FEINT LINES
# ---------------------------------------------------------------------------
# Fires when a Decoy-style attacker successfully baits the defender with
# a feint, drawing their guard off the real line of the strike.

DECOY_FEINT_SUCCESS_LINES = [
    "{attacker} fakes high and strikes low, drawing {foe}'s guard astray!",
    "{attacker}'s misdirection pulls {foe}'s attention the wrong way!",
    "{attacker} feigns an attack to one flank, baiting {foe} to commit!",
    "{attacker}'s ruse opens a seam in {foe}'s defense!",
    "{attacker} sells the feint — {foe} lunges to block a blow that isn't coming!",
    "{attacker} dips a shoulder and {foe} bites on the bluff!",
]

DECOY_FEINT_READ_LINES = [
    "{foe} reads the feint and holds position, unshaken!",
    "{foe} isn't fooled — the ruse falls flat!",
    "{foe} sees through {attacker}'s misdirection!",
]


def decoy_feint_line(attacker_name: str, foe_name: str) -> str:
    return random.choice(DECOY_FEINT_SUCCESS_LINES).format(
        attacker=attacker_name.upper(), foe=foe_name.upper()
    )


def decoy_feint_read_line(attacker_name: str, foe_name: str) -> str:
    return random.choice(DECOY_FEINT_READ_LINES).format(
        attacker=attacker_name.upper(), foe=foe_name.upper()
    )


# ---------------------------------------------------------------------------
# CALCULATED ATTACK LINES
# ---------------------------------------------------------------------------
# Fires when a Calculated Attack strike lands a precision hit — the attacker
# threads the blow through a seam in the defender's guard or armor. Lines
# are keyed by target body location so the narrative calls out the weak
# point being exploited.

CALCULATED_PRECISION_LINES = {
    "head": [
        "{attacker} spots the gap beside {foe}'s helm and drives the {weapon} home!",
        "{attacker} threads the {weapon} past {foe}'s guard, straight for the temple!",
        "With cold precision, {attacker} finds the seam at {foe}'s visor!",
        "{attacker}'s {weapon} slips past {foe}'s helm into the jawline!",
    ],
    "chest": [
        "{attacker} slips the {weapon} between plates, finding {foe}'s rib line!",
        "{attacker} spots the seam at {foe}'s breastplate and strikes!",
        "{attacker}'s {weapon} threads the gap in {foe}'s cuirass!",
        "{attacker} drives the {weapon} through the armpit gap of {foe}'s armor!",
    ],
    "gut": [
        "{attacker} drives the {weapon} up under {foe}'s ribs!",
        "{attacker} finds the soft seam at {foe}'s belt line!",
        "{attacker}'s {weapon} threads the gap beneath {foe}'s cuirass!",
        "{attacker} picks the join at {foe}'s waist and strikes clean!",
    ],
    "arms": [
        "{attacker} picks the gap at {foe}'s shoulder joint!",
        "{attacker}'s {weapon} finds the inside of {foe}'s elbow!",
        "{attacker} slips the strike past {foe}'s vambrace!",
        "{attacker}'s measured thrust lands in the gap at {foe}'s bicep!",
    ],
    "legs": [
        "{attacker} drives the {weapon} behind {foe}'s knee!",
        "{attacker} finds the gap above {foe}'s greave!",
        "{attacker}'s strike threads the seam at {foe}'s thigh!",
        "{attacker} picks the joint behind {foe}'s knee-cop!",
    ],
}

CALCULATED_PROBE_LINES = [
    "{attacker} probes methodically for an opening, but {foe}'s guard holds!",
    "{attacker} studies {foe}'s defense, waiting for a seam that never comes!",
    "{attacker} measures a strike and thinks better of it — {foe} is too disciplined!",
    "{attacker}'s calculating eye finds no gap in {foe}'s guard this pass!",
    "{attacker} circles, searching for a weakness, but {foe} stays tight!",
]


def calculated_precision_line(
    attacker_name: str, foe_name: str, weapon_name: str, aim_point: str
) -> str:
    """
    Narrative line for a landed Calculated Attack precision hit.
    Falls back to the chest pool if the aim point isn't keyed.
    """
    key  = (aim_point or "chest").lower()
    pool = CALCULATED_PRECISION_LINES.get(key, CALCULATED_PRECISION_LINES["chest"])
    return random.choice(pool).format(
        attacker=attacker_name.upper(),
        foe=foe_name.upper(),
        weapon=weapon_name.lower(),
    )


def calculated_probe_line(attacker_name: str, foe_name: str) -> str:
    return random.choice(CALCULATED_PROBE_LINES).format(
        attacker=attacker_name.upper(), foe=foe_name.upper()
    )


# ---------------------------------------------------------------------------
# GROUND / KNOCKDOWN LINES
# ---------------------------------------------------------------------------

KNOCKDOWN_LINES = [
    "{warrior} plummets downward with great speed!!",
    "{warrior} goes crashing to the ground!",
    "{warrior} is knocked off {his} feet!",
    "{warrior} stumbles and falls heavily!",
    "{warrior} crashes to the arena floor!",
]

GET_UP_LINES = [
    "{warrior} scrambles back to {his} feet",
    "{warrior} gets up, shaken but ready",
    "{warrior} staggers upright",
    "{warrior} rises from the dust, spitting blood",
]


def knockdown_line(warrior_name: str, gender: str) -> str:
    pronoun = "his" if gender == "Male" else "her"
    template = random.choice(KNOCKDOWN_LINES)
    return template.format(warrior=warrior_name.upper(), his=pronoun)


def getup_line(warrior_name: str, gender: str) -> str:
    pronoun = "his" if gender == "Male" else "her"
    template = random.choice(GET_UP_LINES)
    return template.format(warrior=warrior_name.upper(), his=pronoun)


# ---------------------------------------------------------------------------
# PERMANENT INJURY LINES
# ---------------------------------------------------------------------------

PERM_ANNOUNCEMENTS: dict[str, list[str]] = {
    "head"         : ["{w} has been permanently injured in the head!!!",
                      "{w}'s skull takes a terrible wound!!!"],
    "chest"        : ["{w} has been permanently injured in the chest!!!",
                      "{w}'s chest is grievously wounded!!!"],
    "abdomen"      : ["{w} has been permanently injured in the abdomen!!!",
                      "{w} takes a gut wound that won't heal!!!"],
    "primary_arm"  : ["{w} has been permanently injured in the weapon arm!!!",
                      "{w}'s sword arm is badly damaged!!!"],
    "secondary_arm": ["{w} has been permanently injured in the shield arm!!!"],
    "primary_leg"  : ["{w} has been permanently injured in the primary leg!!!",
                      "{w}'s main leg is shattered!!!"],
    "secondary_leg": ["{w} has been permanently injured in the secondary leg!!!"],
}

PERM_BLEEDING_LINES: dict[str, list[str]] = {
    "head"         : ["{w}'s head is bleeding badly!",     "{w}'s skull wound weeps blood!"],
    "chest"        : ["{w}'s chest wound bleeds freely!",  "{w} clutches at {his} chest!"],
    "abdomen"      : ["{w}'s belly wound is seeping!",     "{w} doubles over in pain!"],
    "primary_arm"  : ["{w}'s weapon arm is bleeding!",     "{w}'s arm trembles with pain!"],
    "secondary_arm": ["{w}'s off-arm bleeds steadily!"],
    "primary_leg"  : ["{w}'s main leg is bleeding!",       "{w}'s leg buckles!"],
    "secondary_leg": ["{w}'s leg is bleeding!"],
}

PERM_PAIN_LINES: dict[str, list[str]] = {
    "head"         : [
        "{w}'s vision swims from the head wound!!",
        "{w} staggers, seeing double from the blow to {his} head!!",
    ],
    "chest"        : [
        "{w} gasps for air, ribs grinding painfully!!",
        "{w}'s breathing becomes labored!!",
    ],
    "abdomen"      : [
        "{w} bends double, clutching {his} ruined gut!!",
        "{w} spits blood from the gut wound!!",
    ],
    "primary_arm"  : [
        "{w}'s weapon arm spasms in agony!!",
        "{w} nearly drops {his} weapon from the pain!!",
    ],
    "secondary_arm": [
        "{w}'s shield arm goes partially numb!!",
    ],
    "primary_leg"  : [
        "{w}'s leg spasms in pain, causing {him} to roll around in the dirt, wracked with extreme pain!!",
        "{w}'s leg gives way completely!!",
    ],
    "secondary_leg": [
        "{w}'s rear leg buckles violently!!",
    ],
}


def perm_injury_lines(warrior_name: str, location: str, level: int, gender: str) -> list[str]:
    """Return 3 lines for a permanent injury event."""
    pronoun  = "his"  if gender == "Male" else "her"
    him_her  = "him"  if gender == "Male" else "her"

    def fmt(pool: dict, key: str) -> str:
        return random.choice(pool.get(key, [f"{warrior_name.upper()} is gravely wounded!!!"])).format(
            w=warrior_name.upper(), his=pronoun, him=him_her
        )

    announcement = fmt(PERM_ANNOUNCEMENTS, location)
    lines = [
        f"*** {announcement} ***",   # bold-style marker for perm injury
        fmt(PERM_BLEEDING_LINES, location),
        fmt(PERM_PAIN_LINES,     location),
    ]
    return lines


# ---------------------------------------------------------------------------
# FATIGUE / ENDURANCE LINES
# ---------------------------------------------------------------------------

FATIGUE_LINES = [
    "{warrior}'s desire to win may not be enough",
    "{warrior} is visibly tiring",
    "{warrior} slows noticeably",
    "{warrior}'s movements are heavy with exhaustion",
]

VERY_TIRED_LINES = [
    "{warrior} is fighting with pure will power!",
    "{warrior} staggers forward on empty reserves!",
    "{warrior} can barely lift {his} weapon!",
    "{warrior} is running on fumes!",
]

ENDURANCE_DRAIN_LINES = [
    "{warrior} drains the fight out of {foe}",
    "{warrior}'s patient style wears on {foe}",
    "{warrior}'s relentless pressure tires {foe}",
]


def fatigue_line(warrior_name: str, gender: str, very_tired: bool = False) -> str:
    pronoun = "his" if gender == "Male" else "her"
    pool = VERY_TIRED_LINES if very_tired else FATIGUE_LINES
    return random.choice(pool).format(warrior=warrior_name.upper(), his=pronoun)


# ---------------------------------------------------------------------------
# SURRENDER / MERCY LINES
# ---------------------------------------------------------------------------

APPEAL_LINES = [
    "{warrior} appeals to the Blood Master for mercy!",
    "{warrior} raises a hand in surrender!",
    "{warrior} calls out for quarter!",
    "{warrior} can fight no more and begs for mercy!",
]

MERCY_GRANTED = [
    "The ref saves the pitiable {warrior}!",
    "The Blood Master shows mercy, {warrior} lives to fight another day!",
    "{warrior} is spared by the grace of the Blood Master!",
    "The crowd screams for blood, but the ref steps in!",
    "Mercy is granted, the fight is over!",
]

MERCY_DENIED = [
    "The Blood Master shows no mercy today!",
    "The crowd screams for blood, mercy is denied!",
    "{warrior} must fight on, or die trying!",
    "No quarter is given!",
]

DEATH_LINES = [
    "{warrior} has perished in the BLOODSPIRE!!!",
    "{warrior} breathes {his} last on the arena floor!!!",
    "{warrior} is dead. The crowd erupts!!!",
    "{warrior} falls, never to rise again!!!",
]

VICTORY_LINES = [
    "{winner} has won this affair of honor!",
    "{winner} stands victorious over the fallen {loser}!",
    "{winner} is declared the winner!",
    "The Blood Master raises {winner}'s arm in victory!",
    "{winner} roars in triumph over the defeated {loser}!",
]


def appeal_line(warrior_name: str) -> str:
    return random.choice(APPEAL_LINES).format(warrior=warrior_name.upper())


def mercy_result_line(warrior_name: str, granted: bool) -> str:
    pool = MERCY_GRANTED if granted else MERCY_DENIED
    return random.choice(pool).format(warrior=warrior_name.upper())


def death_line(warrior_name: str, gender: str) -> str:
    pronoun = "his" if gender == "Male" else "her"
    return random.choice(DEATH_LINES).format(warrior=warrior_name.upper(), his=pronoun)


def victory_line(winner_name: str, loser_name: str) -> str:
    return random.choice(VICTORY_LINES).format(
        winner=winner_name.upper(), loser=loser_name.upper()
    )


# ---------------------------------------------------------------------------
# CROWD FLAVOR LINES (random interjections between actions)
# These fire roughly once every 4-6 actions.
# ---------------------------------------------------------------------------

CROWD_LINES = [
    "The drummer loses control and tosses a drumstick away",
    "Arena guards hold back rioting fans!",
    "A spectator calls out, 'Give him what he deserves!'",
    "The crowd chants for blood!",
    "Someone in the upper rows throws a piece of bread",
    "A vendor drops his tray with a tremendous crash",
    "The crowd surges forward against the barriers!",
    "Whistles and jeers rain down from the stands!",
    "A dog runs loose in the upper tier!",
    "The pit bell rings early, it must be a mistake",
    "Three drunks in the cheap seats start a brawl",
    "The announcer's voice cracks with excitement",
    "A nobleman covers his eyes, then peeks through his fingers",
    "Children in the stands look away, then look back",
    "The smell of blood whips the crowd into a frenzy",
    "Half the crowd rises to their feet in anticipation!",
    "Money changes hands rapidly in the betting stands",
    "The torchbearers scramble to keep up with the action",
]

RACE_TAUNTS = {
    "Half-Orc" : [
        "A spectator calls out, 'Hey half-orc!  Grind me a pound!'",
        "Someone yells, 'Get a bath, you monster!'",
        "A child throws a cabbage at the Half-Orc",
    ],
    "Halfling" : [
        "A guard has to move to see around the Halfling",
        "The crowd strains to see the small warrior",
        "Someone yells, 'Watch out, there's a rat loose in the pit!'",
    ],
    "Dwarf"    : [
        "A drunk yells, 'Which one is the Dwarf?', looking at the right one",
        "Someone throws coins at the Dwarf, a tradition, apparently",
    ],
    "Elf"      : [
        "The Elf fans in the crowd begin an unsettling melodic chant",
        "Someone boos the Elf, then sits very still hoping no one noticed",
    ],
}


# ---------------------------------------------------------------------------
# MINUTE STATUS LINE  (who is winning at each minute boundary)
# ---------------------------------------------------------------------------

_ADVAN_EVEN = [
    "Both warriors appear evenly matched, with neither willing to give ground.",
    "The fight remains dead even, neither combatant claiming a clear edge.",
    "At this point, the contest could still go either way.",
    "Neither warrior has managed to separate themselves from the other.",
    "The crowd watches closely as the fight remains finely balanced.",
    "So far, there is little to distinguish the two in this tightly contested battle.",
    "The momentum swings back and forth, with no clear leader emerging.",
    "Both gladiators continue to test each other, still searching for an opening.",
    "Despite several close calls, neither warrior has seized control.",
    "The margin between victory and defeat remains razor-thin.",
]

_ADVAN_EVEN_CONT = [   # used when tier unchanged from last minute
    "The fight remains stubbornly even, with neither warrior conceding ground.",
    "Nothing has changed, both combatants continue on level footing.",
    "The balance holds; neither fighter has found the breakthrough they need.",
]

_ADVAN_SLIGHT = [
    "{winner} appears to have a slight advantage.",
    "{winner} is beginning to edge ahead in the exchange.",
    "{winner} has started to gain the upper hand, though the fight remains close.",
    "Momentum seems to be slowly shifting toward {winner}.",
    "{winner} looks marginally sharper at this stage of the fight.",
    "While still competitive, {winner} seems just a step ahead.",
    "{winner} is finding more success, but the outcome is far from decided.",
    "The balance tips ever so slightly in favor of {winner}.",
    "It's a narrow lead, but {winner} may be starting to pull ahead.",
    "Small advantages are beginning to stack up for {winner}.",
]

_ADVAN_SLIGHT_CONT = [
    "{winner} continues to hold a narrow advantage.",
    "The slight edge remains with {winner}, though little has changed.",
    "{winner} maintains the lead, but nothing is decided yet.",
]

_ADVAN_CLEAR = [
    "{winner} is winning the fight.",
    "At this point, {winner} has seized control of the contest.",
    "{winner} now holds a clear advantage over their opponent.",
    "The fight has begun to tilt decisively in {winner}'s favor.",
    "{winner} is firmly in control of the action.",
    "It's becoming evident that {winner} has the upper hand.",
    "{winner} is dictating the pace and flow of the fight.",
    "The tide has clearly turned in favor of {winner}.",
    "The crowd responds as {winner} takes command of the fight.",
    "The advantage is unmistakable now, and it belongs to {winner}.",
]

_ADVAN_CLEAR_CONT = [
    "{winner} remains in control, pressing their advantage.",
    "The situation is unchanged, {winner} continues to dictate the fight.",
    "{winner} holds firm command of the contest.",
]

_ADVAN_DOMINATING = [
    "{winner} is dominating the fight.",
    "This has become a one-sided affair in favor of {winner}.",
    "{winner} is completely overwhelming their opponent.",
    "The gap between the two warriors is widening rapidly.",
    "{winner} is imposing their will with authority.",
    "This fight is slipping badly away from {loser}.",
    "{winner} is in full command, leaving little room for resistance.",
    "The contest has turned brutal, with {winner} firmly on top.",
    "Only a dramatic reversal could save {loser} now.",
    "{winner} is dismantling their opponent piece by piece.",
]

_ADVAN_DOMINATING_CONT = [
    "{winner} shows no sign of relenting, the onslaught continues.",
    "{loser} remains unable to slow {winner}'s dominance.",
    "{winner} stays firmly in control with no answer from {loser}.",
]

_ADVAN_BRINK = [
    "{loser} appears to be on the verge of defeat.",
    "This fight looks moments away from being decided.",
    "{winner} smells blood and presses the advantage.",
    "It's hard to see how {loser} survives much longer at this pace.",
    "Unless something changes quickly, this fight is all but over.",
    "{loser} is hanging on by sheer will alone.",
    "The end may be near as {winner} continues their assault.",
]

_ADVAN_BRINK_EXHAUSTION = [
    "{loser} is running on empty, their body is beginning to betray them.",
    "The effort has taken a severe toll on {loser}; they can barely keep pace.",
    "{loser} is visibly fading, their endurance all but spent.",
    "Exhaustion is closing in on {loser}, and {winner} senses the opening.",
    "{loser}'s legs are heavy, their arms slower, they cannot keep this up much longer.",
]

_ADVAN_SWING_TO = [
    "The fight has taken a surprising turn, with {winner} now pressing the advantage.",
    "After earlier struggles, {winner} has clawed their way back into control.",
    "A shift in momentum, {winner} has suddenly taken charge.",
    "The tide turns: {winner} seizes the upper hand after a close exchange.",
]


def minute_status_line(
    winner_name: str,
    loser_name: str,
    tier: str,
    prev_tier: str,
    prev_winner: str,
    used: set,
) -> str:
    """
    Return a fight-status line for the start of a minute.

    tier / prev_tier: one of "even", "slight", "clear", "dominating", "brink", "brink_exhaustion"
    winner_name / loser_name: the leading fighter (empty strings when tier == "even")
    prev_winner: the name of the winner last minute (empty string if none)
    used: mutable set of already-used lines this fight (updated in-place)
    """
    # Detect momentum swing: tier changed OR same tier but winner flipped
    swung = (tier != "even" and prev_tier != "even" and
             tier == prev_tier and prev_winner and prev_winner != winner_name)

    if swung:
        pool = _ADVAN_SWING_TO
    elif tier == prev_tier:
        # Unchanged, use softer continuation lines
        cont_map = {
            "even":            _ADVAN_EVEN_CONT,
            "slight":          _ADVAN_SLIGHT_CONT,
            "clear":           _ADVAN_CLEAR_CONT,
            "dominating":      _ADVAN_DOMINATING_CONT,
            "brink":           _ADVAN_BRINK,
            "brink_exhaustion": _ADVAN_BRINK_EXHAUSTION,
        }
        pool = cont_map.get(tier, _ADVAN_EVEN_CONT)
    else:
        main_map = {
            "even":            _ADVAN_EVEN,
            "slight":          _ADVAN_SLIGHT,
            "clear":           _ADVAN_CLEAR,
            "dominating":      _ADVAN_DOMINATING,
            "brink":           _ADVAN_BRINK,
            "brink_exhaustion": _ADVAN_BRINK_EXHAUSTION,
        }
        pool = main_map.get(tier, _ADVAN_EVEN)

    # Pick a line not used yet this fight; fall back to full pool if exhausted
    available = [l for l in pool if l not in used]
    if not available:
        available = list(pool)

    line = random.choice(available)
    used.add(line)

    return line.format(winner=winner_name.upper(), loser=loser_name.upper())


def crowd_line(warrior_a_race: str = "", warrior_b_race: str = "") -> str:
    """Return a random crowd flavor line, occasionally race-specific."""
    if random.random() < 0.2:
        # Try a race taunt for one of the warriors
        race = random.choice([warrior_a_race, warrior_b_race])
        if race in RACE_TAUNTS:
            return random.choice(RACE_TAUNTS[race])
    return random.choice(CROWD_LINES)


# ---------------------------------------------------------------------------
# "ANXIOUSLY AWAITS" LINE (endurance drain effect, certain styles)
# ---------------------------------------------------------------------------

ANXIOUS_LINES = [
    "{warrior} circles {foe}, draining the will to fight",
    "{warrior} waits patiently, {foe}'s energy bleeds away",
    "{warrior} keeps pressure on {foe} without committing",
]


def anxious_line(warrior_name: str, foe_name: str) -> Optional[str]:
    """Only fires for styles with anxiously_awaits=True, ~20% chance."""
    if random.random() < 0.20:
        t = random.choice(ANXIOUS_LINES)
        return t.format(warrior=warrior_name.upper(), foe=foe_name.upper())
    return None


INTIMIDATE_LINES = [
    "{warrior}'s relentless assault is beginning to rattle {foe}!",
    "{foe} flinches under the ferocity of {warrior}'s onslaught!",
    "The sheer savagery of {warrior}'s assault wears on {foe}'s nerves!",
    "{warrior} presses forward with terrifying aggression, {foe} backs away!",
    "The crowd roars as {warrior}'s ferocity visibly shakes {foe}!",
    "{foe} struggles to keep composure under {warrior}'s relentless pressure!",
    "{warrior}'s wild fury is taking a psychological toll on {foe}!",
]


def intimidate_line(warrior_name: str, foe_name: str) -> Optional[str]:
    """Only fires for styles with intimidate=True at high activity, ~25% chance."""
    if random.random() < 0.25:
        t = random.choice(INTIMIDATE_LINES)
        return t.format(warrior=warrior_name.upper(), foe=foe_name.upper())
    return None


# ---------------------------------------------------------------------------
# POST-FIGHT TRAINING SUMMARY
# ---------------------------------------------------------------------------

_BASE_STATS = {"strength", "dexterity", "constitution", "intelligence", "presence", "size"}


def training_summary(warrior_name: str, results: list[str], is_opponent: bool = False) -> str:
    """
    Post-fight training summary.
      successes:  "<n> has trained in X and Y"
      none:       "<n> has trained in nothing"
      observed 4th train: appended as separate line

    is_opponent: When True, hide the specific skill/stat names, show "Skill" or
    "Stat" instead.  The one exception is the observed/learned bonus, which always
    names the actual skill (that is the whole point of the intelligence report).
    """
    if not results:
        return f"{warrior_name.upper()} has trained in nothing"

    trained  = []
    observed = []
    for r in results:
        if r.startswith("[OBSERVED]") and "trained:" in r:
            skill_name = r.split("[OBSERVED]")[1].split(" trained:")[0].strip().title()
            observed.append(skill_name)
        elif "trained:" in r:
            skill_name = r.split(" trained:")[0].strip()
            if is_opponent:
                trained.append("Stat" if skill_name.lower() in _BASE_STATS else "Skill")
            else:
                trained.append(skill_name.title())

    lines = []
    if trained:
        lines.append(f"{warrior_name.upper()} has trained in {' and '.join(trained)}")
    else:
        lines.append(f"{warrior_name.upper()} has trained in nothing")

    if observed:
        # Always reveal the actual skill, this is the scouting intelligence payoff
        for obs_skill in observed:
            lines.append(
                f"{warrior_name.upper()} observed and learned a {obs_skill} skill"
                f" from their opponent"
            )

    return "\n".join(lines)

