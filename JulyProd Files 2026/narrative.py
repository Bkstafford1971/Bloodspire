# =============================================================================
# narrative.py, THE AGONY AMPHITHEATRE Narrative Text Engine
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


def _article(word: str) -> str:
    """Return 'an' if word starts with a vowel sound, otherwise 'a'."""
    return "an" if word and word[0].upper() in "AEIOU" else "a"


# ---------------------------------------------------------------------------
# POPULARITY DESCRIPTIONS
# ---------------------------------------------------------------------------

POPULARITY_DESCRIPTIONS = [
    (0,  10, "LARGELY UNKNOWN"),
    (11, 20, "GENERALLY DISLIKED"),
    (21, 30, "MOSTLY IGNORED"),
    (31, 40, "HAS A FEW FANS"),
    (41, 50, "KNOWN TO THE CROWD"),
    (51, 60, "POPULAR WITH THE KIDS"),
    (61, 70, "WELL LIKED"),
    (71, 80, "A FAN FAVORITE"),
    (81, 90, "HAS HORDES OF ADORING FANS"),
    (91, 100, "A LEGENDARY HERO"),
]


def popularity_desc(score: int) -> str:
    for lo, hi, desc in POPULARITY_DESCRIPTIONS:
        if lo <= score <= hi:
            return desc
    return "KNOWN TO THE CROWD"


# =============================================================================
# IMPROVED _backup_weapon_description function
# Replace lines 50-143 in narrative.py with this improved version
# =============================================================================

def _backup_weapon_description(weapon_name: str, gender: str) -> str:
    """
    Generate a thematic, location-specific description of a backup weapon.
    Returns a string (without period) describing where/how it's carried.
    
    Logic prioritizes realism:
    - Small blades (daggers, knives) → hip, waist, belt
    - Medium swords → hip or side
    - Large swords → back
    - Maces, hammers, clubs → belt or back
    - Axes → belt loop or back
    - Polearms/spears → back or planted at side
    - Shields → arm, shoulder, or back
    """
    pronoun = "his" if gender == "Male" else "her"
    weapon_lower = weapon_name.lower()
    
    try:
        weapon = get_weapon(weapon_name)
    except ValueError:
        # Fallback for unknown weapons
        return f"has a spare {weapon_name.upper()} strapped to {pronoun} side"
    
    wpn_display = weapon.display.upper()
    weight = weapon.weight
    is_two_hand = weapon.two_hand
    is_shield = weapon.is_shield
    is_throwable = weapon.throwable
    category = weapon.category
    
    # Helper to check if weapon name contains keyword
    def contains(keyword):
        return keyword in weapon_lower
    
    # Shield-specific descriptions
    if is_shield:
        shield_desc = [
            f"has {_article(wpn_display)} {wpn_display} buckled to {pronoun} arm",
            f"carries {_article(wpn_display)} {wpn_display} slung on {pronoun} shoulder",
            f"has {_article(wpn_display)} {wpn_display} strapped across {pronoun} back",
        ]
        return random.choice(shield_desc)
    
    # Small daggers and knives - ALWAYS at hip/waist/belt, NEVER on back
    if contains("dagger") or contains("knife") or contains("stiletto"):
        small_blade_desc = [
            f"has {_article(wpn_display)} {wpn_display} sheathed at {pronoun} hip",
            f"carries {_article(wpn_display)} {wpn_display} tucked into {pronoun} belt",
            f"has {_article(wpn_display)} {wpn_display} at {pronoun} waist",
        ]
        return random.choice(small_blade_desc)
    
    # Polearms and spears - carried upright or across back
    if category == "Polearm/Spear" or contains("spear") or contains("pike") or contains("lance"):
        polearm_desc = [
            f"has {_article(wpn_display)} {wpn_display} strapped to {pronoun} back",
            f"carries {_article(wpn_display)} {wpn_display} planted at {pronoun} side",
            f"has {_article(wpn_display)} {wpn_display} leaning against {pronoun} shoulder",
        ]
        return random.choice(polearm_desc)
    
    # Short swords and medium blades - hip or side, not back
    if contains("short") and contains("sword"):
        short_sword_desc = [
            f"has {_article(wpn_display)} {wpn_display} sheathed at {pronoun} hip",
            f"wears {_article(wpn_display)} {wpn_display} at {pronoun} side",
            f"carries {_article(wpn_display)} {wpn_display} on {pronoun} hip",
        ]
        return random.choice(short_sword_desc)
    
    # Large two-handed swords - must be on back
    if is_two_hand and contains("sword"):
        large_sword_desc = [
            f"has {_article(wpn_display)} {wpn_display} strapped across {pronoun} back",
            f"wears {_article(wpn_display)} {wpn_display} slung across {pronoun} back",
            f"carries {_article(wpn_display)} {wpn_display} lashed to {pronoun} back",
        ]
        return random.choice(large_sword_desc)
    
    # Medium swords (long sword, broad sword, bastard sword) - hip or back
    if contains("sword"):
        if weight >= 4.0:  # Heavier swords more likely on back
            medium_sword_desc = [
                f"has {_article(wpn_display)} {wpn_display} strapped across {pronoun} back",
                f"wears {_article(wpn_display)} {wpn_display} slung at {pronoun} side",
            ]
        else:  # Lighter swords at hip
            medium_sword_desc = [
                f"has {_article(wpn_display)} {wpn_display} sheathed at {pronoun} hip",
                f"wears {_article(wpn_display)} {wpn_display} at {pronoun} side",
            ]
        return random.choice(medium_sword_desc)
    
    # Maces, hammers, clubs - belt loop or back
    if contains("mace") or contains("hammer") or contains("club") or contains("flail"):
        blunt_desc = [
            f"has {_article(wpn_display)} {wpn_display} hanging from {pronoun} belt",
            f"carries {_article(wpn_display)} {wpn_display} looped at {pronoun} hip",
            f"has {_article(wpn_display)} {wpn_display} strapped to {pronoun} back",
        ]
        return random.choice(blunt_desc)
    
    # Axes - belt loop for smaller, back for larger
    if contains("axe"):
        if weight >= 4.0 or is_two_hand:  # Large axes on back
            axe_desc = [
                f"has {_article(wpn_display)} {wpn_display} strapped across {pronoun} back",
                f"carries {_article(wpn_display)} {wpn_display} slung over {pronoun} shoulder",
            ]
        else:  # Smaller axes at belt
            axe_desc = [
                f"has {_article(wpn_display)} {wpn_display} hanging from {pronoun} belt",
                f"carries {_article(wpn_display)} {wpn_display} looped at {pronoun} hip",
                f"has {_article(wpn_display)} {wpn_display} tucked in {pronoun} belt",
            ]
        return random.choice(axe_desc)
    
    # Two-handed weapons (catch-all) - strapped/slung across back
    if is_two_hand:
        heavy_desc = [
            f"has {_article(wpn_display)} {wpn_display} strapped to {pronoun} back",
            f"carries {_article(wpn_display)} {wpn_display} slung across {pronoun} back",
            f"wears {_article(wpn_display)} {wpn_display} lashed to {pronoun} back",
        ]
        return random.choice(heavy_desc)
    
    # Throwable weapons - quiver, bundle, or bandolier
    if is_throwable:
        throw_desc = [
            f"has {_article(wpn_display)} {wpn_display} at {pronoun} side",
            f"carries {_article(wpn_display)} {wpn_display} secured at {pronoun} hip",
            f"has {_article(wpn_display)} {wpn_display} tucked in {pronoun} belt",
        ]
        return random.choice(throw_desc)
    
    # Default for medium one-handed weapons - prefer hip/side over back
    if weight < 3.5:  # Lighter weapons at hip
        default_desc = [
            f"has {_article(wpn_display)} {wpn_display} sheathed at {pronoun} hip",
            f"carries {_article(wpn_display)} {wpn_display} at {pronoun} side",
            f"wears {_article(wpn_display)} {wpn_display} on {pronoun} hip",
        ]
    else:  # Heavier one-handed weapons on back or shoulder
        default_desc = [
            f"has {_article(wpn_display)} {wpn_display} strapped to {pronoun} back",
            f"carries {_article(wpn_display)} {wpn_display} over {pronoun} shoulder",
            f"has {_article(wpn_display)} {wpn_display} slung across {pronoun} back",
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


# =============================================================================
# EXTRA DEFENSIVE VERSION of _warrior_report_block function
# This version has additional debug output and defensive checks
# Replace lines 162-207 in narrative.py with this version
# =============================================================================

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
    lines.append(f"{w.name.upper()} {popularity_desc(w.popularity).title()}. (pop. {w.popularity})")

    # Safely handle armor and helm (convert to string if not already)
    armor_val = w.armor
    helm_val  = w.helm
    _has_natural_armor = (
        hasattr(w, "race")
        and hasattr(w.race, "modifiers")
        and w.race.modifiers.natural_armor
    )

    if armor_val:
        armor_val = str(armor_val).strip()

    _no_armor = not armor_val or armor_val.lower() == "none"

    # Determine pronoun for Lizardfolk armor descriptions
    pronoun = "his" if (hasattr(w, "gender") and w.gender == "Male") else "her"

    if _has_natural_armor:
        if _no_armor:
            # Scales only - equivalent to Scale armor protection
            armor_part = "in NATURAL SCALE ARMOR"
        elif armor_val.lower() in ("cloth", "leather"):
            # Cloth/Leather layers over scales and adds a small bonus
            armor_part = f"in {armor_val.upper()} over {pronoun} natural scales"
        else:
            # Armor over scales: armor-type-specific flavor that implies restriction without being explicit
            armor_lower = armor_val.lower()
            if armor_lower == "cuir boulli":
                armor_part = f"in {armor_val.upper()}, rigid leather restricting {pronoun} natural flexibility"
            elif armor_lower == "brigandine":
                armor_part = f"in {armor_val.upper()}, plates catching awkwardly over {pronoun} natural scales"
            elif armor_lower == "scale":
                armor_part = f"in {armor_val.upper()}, layered awkwardly over {pronoun} natural plating"
            elif armor_lower == "chain":
                armor_part = f"in {armor_val.upper()}, links that snag between {pronoun} scales"
            else:
                # Half-Plate, Full Plate, and any others
                armor_part = f"in {armor_val.upper()}, rigid plates constraining {pronoun} natural mobility"
    else:
        armor_part = f"in {armor_val.upper()}" if not _no_armor else "unarmored"

    if helm_val:
        helm_val = str(helm_val).strip()
        helm_part = f"and will wear a {helm_val.upper()}" if helm_val and helm_val.lower() != "none" else "and wears no helm"
    else:
        helm_part = "and wears no helm"

    lines.append(f"{w.name.upper()} enters the arena {armor_part} {helm_part}.")

    # CRITICAL: Get weapon attributes with multiple fallback levels
    # This ensures weapons are ALWAYS retrieved, even from dictionaries or corrupted objects

    # Method 1: Try as object attribute
    main_weapon = None
    off_weapon = None
    bak_weapon = None

    try:
        # Try getattr first (best for objects)
        main_weapon = getattr(w, 'primary_weapon', None)
        off_weapon = getattr(w, 'secondary_weapon', None)
        bak_weapon = getattr(w, 'backup_weapon', None)
    except:
        pass

    # Method 2: If warrior is a dict-like object, try dict access
    if main_weapon is None and hasattr(w, '__getitem__'):
        try:
            main_weapon = w.get('primary_weapon') if hasattr(w, 'get') else w['primary_weapon']
        except:
            pass

    if off_weapon is None and hasattr(w, '__getitem__'):
        try:
            off_weapon = w.get('secondary_weapon') if hasattr(w, 'get') else w['secondary_weapon']
        except:
            pass

    # Convert weapons to strings BEFORE checking/applying defaults
    if main_weapon is not None:
        main_weapon = str(main_weapon).strip()
    if off_weapon is not None:
        off_weapon = str(off_weapon).strip()
    if bak_weapon is not None:
        bak_weapon = str(bak_weapon).strip()

    # Apply defaults for None or empty strings
    if not main_weapon or main_weapon.lower() in ("", "none"):
        main_weapon = "Open Hand"
    if not off_weapon or off_weapon.lower() in ("", "none"):
        off_weapon = "Open Hand"

    # Convert to uppercase for display
    main = main_weapon.upper()
    off = off_weapon.upper()

    # Normalize backup weapon: handle null, empty string, "None", "Open Hand", etc
    if bak_weapon and bak_weapon.lower() not in ("none", "", "open hand"):
        bak = bak_weapon
    else:
        bak = None

    # ALWAYS add weapon description line - this should NEVER be skipped
    if off and off != "OPEN HAND":
        lines.append(f"{w.name.upper()} fights using {_article(main)} {main} with an off-hand {off}.")
    else:
        lines.append(f"{w.name.upper()} fights using {_article(main)} {main}.")

    # Show backup weapon if it exists and is not "None" or "Open Hand"
    if bak:
        try:
            backup_desc = _backup_weapon_description(bak, w.gender)
            # Convert description to lowercase, then keep weapon name in ALL CAPS for client bolding
            backup_desc_lower = backup_desc.lower()
            bak_upper = bak.upper()
            backup_desc_final = backup_desc_lower.replace(bak_upper.lower(), bak_upper)
            lines.append(f"{w.name.upper()} {backup_desc_final}.")
        except Exception:
            lines.append(f"{w.name.upper()} carries a spare {bak.upper()} as backup.")

    return lines


def _strategy_table(w: Warrior, strats=None) -> list:
    """Return the strategy table lines for the player warrior.

    strats: the actual strategy list being used in this fight (challenge or
            regular). Falls back to w.strategies when not provided.
    """
    strategies = strats if strats is not None else w.strategies
    if not strategies:
        return []
    hdr = f"{'TRIGGER':<42}{'FIGHTING STYLE':<20}{'LEVEL':>5}  {'AIMING POINT':<16}{'DEFENSE POINT'}"
    sep = "-" * len(hdr)
    lines = ["", hdr, sep]
    for i, s in enumerate(strategies, 1):
        is_default = (not s.trigger) or s.trigger.lower().startswith("always")
        trig = "D: Always (Default Loop)" if is_default else f"{i}: {s.trigger}"
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
    strats_a=None,
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

    def _hdr(left: str, sep: str, right: str) -> str:
        """Two-column header line: left left-aligned, sep fixed-width center, right right-aligned."""
        sep_with_spaces = f"   {sep}   "
        sides = LINE_WIDTH - len(sep_with_spaces)
        lw = sides // 2
        rw = sides - lw
        return f"{left:<{lw}}{sep_with_spaces}{right:>{rw}}"

    lines = [SEP]

    # Matchup title - warrior names on top, record below
    lines.append(_hdr(
        f"{warrior_a.name.upper()}",
        "vs",
        f"{warrior_b.name.upper()}",
    ))

    # Record line (separate, larger in client CSS)
    lines.append(_hdr(
        f"{warrior_a.record_str}",
        "vs",
        f"{warrior_b.record_str}",
    ))

    # Team and Manager separated to individual lines
    lines.append(_hdr(
        f"TEAM: {team_a_name.upper()}",
        "vs",
        f"TEAM: {team_b_name.upper()}",
    ))
    lines.append(_hdr(
        f"MANAGER: {manager_a_name.upper()}",
        "vs",
        f"MANAGER: {manager_b_name.upper()}",
    ))

    lines.append(_hdr(
        f"{warrior_a.race.name} {warrior_a.gender}",
        "vs",
        f"{warrior_b.race.name} {warrior_b.gender}",
    ))
    lines.append(SEP)
    lines.append("")

    # Player warrior prose
    lines.extend(_warrior_report_block(warrior_a))
    lines.append("")

    # Opponent warrior prose
    lines.extend(_warrior_report_block(warrior_b))
    lines.append("")

    # Player strategy table — use the actual strategies for this fight
    # (challenge strategies when challenge mode is active, otherwise regular)
    lines.extend(_strategy_table(warrior_a, strats_a))

    lines.append("")
    lines.append(SEP)
    return "\n".join(lines)


_CHALLENGE_FLAVOR_NORMAL = [
    "{n1} issues a Challenge to {n2}!!",
    "{n1} challenges {n2} in an affair of honor!",
    "{n1} has called out {n2} for this Challenge bout!",
    "{n1} steps forward to challenge {n2}!",
    "{n1} has issued a Challenge to {n2} this turn!",
    "{n1} presents a Challenge to {n2}!",
]

_CHALLENGE_FLAVOR_BLOOD = [
    "{n1} seeks blood vengeance against {n2} in a Blood Challenge!!",
    "{n1} has declared a Blood Challenge against {n2}!!",
    "{n1} issues a Blood Challenge to {n2}!",
    "{n1} demands a price in blood from {n2} - a Blood Challenge!!",
    "The air turns cold as {n1} declares a Blood Challenge against {n2}!!",
    "{n1} swears a Blood Challenge vendetta against {n2} this turn!",
]

_CHALLENGE_FLAVOR_MONSTER = [
    "{n1} dares to challenge the Monster {n2}!!",
    "{n1} steps forward to face the Monster {n2} in Challenge!!",
    "{n1} steps into the pit to challenge the Monster {n2}!!",
    "{n1} seeks glory by challenging the Monster {n2}!!",
    "{n1} will attempt to survive a challenge against the Monster {n2}!!",
    "{n1} issues a Monster Challenge to {n2}!!",
]

_CHALLENGE_FLAVOR_CHAMPION = [
    "{n1} challenges {n2} for the Title!!",
    "{n1} steps forward to challenge for the Title against {n2}!!",
    "This is a Title Challenge: {n1} seeks to dethrone champion {n2}!!",
    "{n1} issues a Title Challenge to the champion {n2}!!",
    "{n1} will attempt to claim the Title from {n2}!!",
    "{n1} steps into the arena for a Title Challenge against {n2}!!",
]

def get_challenge_flavor_line(w1_name: str, w2_name: str, challenger_name: Optional[str], fight_type: str) -> Optional[str]:
    """Return a randomly selected challenge flavor line if appropriate."""
    if not challenger_name and fight_type not in ("monster", "champion"):
        return None

    # Identify challenger and challenged (robust case-insensitive check)
    c_name_norm = challenger_name.strip().upper() if challenger_name else ""
    w1_name_norm = w1_name.strip().upper()
    w2_name_norm = w2_name.strip().upper()

    if c_name_norm == w1_name_norm:
        n1, n2 = w1_name_norm, w2_name_norm
    elif c_name_norm == w2_name_norm:
        n1, n2 = w2_name_norm, w1_name_norm
    else:
        # Default for monster/champion fights or if names don't match (fallback)
        n1, n2 = w1_name_norm, w2_name_norm

    if fight_type == "blood_challenge":
        pool = _CHALLENGE_FLAVOR_BLOOD
    elif fight_type == "monster":
        pool = _CHALLENGE_FLAVOR_MONSTER
    elif fight_type == "champion":
        pool = _CHALLENGE_FLAVOR_CHAMPION
    else:
        pool = _CHALLENGE_FLAVOR_NORMAL

    return random.choice(pool).format(n1=n1, n2=n2)

def presence_hesitation_line(attacker_name: str, defender_name: str) -> str:
    """Return the narrative line for a successful presence-based hesitation."""
    return f"{attacker_name.upper()}'s commanding presence makes {defender_name.upper()} hesitate!"


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
    "An eerie silence settles over the AGONY AMPHITHEATRE",
    "The torches flicker as a cold wind sweeps through the arena",
    "The Blood Master raises his fist, the fight begins!",
]

FIGHT_ENGAGEMENT_LINES = [
    "Weapons gleam as the warriors circle the pit",
    "The crowd leans forward as steel meets steel in greeting",
    "Sand crunches beneath their feet as they close",
    "A low growl of anticipation rolls through the stands",
    "The first feint cuts through the air, testing distance",
    "Breath clouds form as the fighters lock eyes",
    "The opening stance is taken, nerves stretched tight",
    "Iron clangs as guards are tested and positions set",
    "The rhythm of combat begins to establish itself",
    "Muscles coil as the opening gambit approaches",
]

RACE_KILL_POOLS = {
    "Half-Orc": [
        "{name} snorts in triumph, a thick string of bloody saliva trailing from {his} lower tusks.",
        "{name} lets out a primal, guttural roar that vibrates through the arena floor.",
        "{name} beats {his} chest with blood-stained hands, howling at the screaming crowd.",
        "{name} stares down at the corpse, a slow, predatory grin spreading across {his} heavy features.",
        "{name} wipes {his} weapon on the fallen warrior's clothing with a grunt of disdain.",
        "{name} looms over the body, {his} breath coming in heavy, jagged snorts of victory.",
        "{name} kicks a spray of sand over the remains, a simple gesture of orcish finality.",
        "{name} raises {his} blood-slicked weapon high, a deafening war-cry erupting from {his} throat.",
        "{name} stands motionless over the kill, the scent of fresh blood igniting a dark fire in {his} eyes.",
        "{name} spits on the dirt beside the corpse, satisfied with the carnage.",
    ],
    "Elf": [
        "{name} lowers {his} weapon with fluid grace, offering a silent, cold nod to the fallen.",
        "{name} stands perfectly still, the only sign of the kill a subtle, chilling smile.",
        "{name} sheathes {his} blade in a blur of motion, looking already bored with the victory.",
        "{name} murmurs a short, melodic phrase in Elvish, a sharp contrast to the surrounding violence.",
        "{name} steps delicately over the body, {his} movements as precise as the strike that ended it.",
        "{name} gazes upon the corpse with a detached, clinical interest before turning away.",
        "{name} flickers {his} weapon to clear the blood, the motion so swift it's almost invisible.",
        "{name} stands like a statue over the remains, {his} eyes reflecting the setting sun with unsettling calm.",
        "{name} adjusts {his} stance with effortless elegance, the kill merely a footnote in {his} afternoon.",
        "{name} offers a mocking, graceful bow to the cheering stands, a predator's charm on full display.",
    ],
    "Dwarf": [
        "{name} plants {his} feet firmly and grunts, the weight of the kill settling deep in {his} bones.",
        "{name} spits a thick glob of phlegm onto the sand, a stolid mark of Dwarven triumph.",
        "{name} hefts {his} weapon onto {his} shoulder, a grim, satisfied nod offered to the body.",
        "{name} mutters a gruff word of respect to the mountain, the kill a debt paid in full.",
        "{name} stands like a mountain over the fallen, {his} beard matted with the dust of the pit.",
        "{name} kicks the corpse's weapon aside with a heavy boot, a final act of dismissal.",
        "{name} lets out a low, booming laugh that sounds like stones grinding together.",
        "{name} wipes a bead of sweat from {his} brow with a bloodied glove, the job finished.",
        "{name} stares at the body for a long moment, {his} features an unreadable mask of iron.",
        "{name} thumps a fist against {his} armor, the resonant clang signaling the end of the bout.",
    ],
    "Human": [
        "{name} raises a blood-streaked hand to the crowd, soaking in the roar of the arena.",
        "{name} stands over the fallen opponent, chest heaving, a look of grim determination on {his} face.",
        "{name} offers a salute with {his} weapon to the Blood Master, the kill dedicated to the Pit.",
        "{name} stares at {his} blood-stained hands for a heartbeat before looking back at the stands.",
        "{name} lets out a weary but triumphant shout, the adrenaline of the kill still surging.",
        "{name} looks down at the corpse with a mix of pity and pride, the reality of the amphitheatre setting in.",
        "{name} wipes {his} brow, a sharp, victory-drunk grin splitting {his} face.",
        "{name} stands tall among the sawdust and blood, a common man made legendary by the kill.",
        "{name} offers a simple, respectful nod to the fallen before turning to acknowledge the fans.",
        "{name} screams a name to the heavens, a personal victory won in the blood of the sands.",
    ],
    "Halfling": [
        "{name} darts a quick, mischievous look at the crowd before offering a cheeky wink.",
        "{name} stands over the much larger opponent, a look of feigned surprise on {his} youthful face.",
        "{name} wipes {his} blade with a flourish, the kill handled with more style than seems strictly necessary.",
        "{name} hops over the corpse with a nimble skip, already looking for the next excitement.",
        "{name} lets out a high-pitched, mocking cheer that carries clearly over the roar of the fans.",
        "{name} strikes a dramatic pose over the body, {his} small frame casting a long shadow on the sand.",
        "{name} chuckles to {himself}, a light-hearted sound in the midst of the carnage.",
        "{name} offers a playful, exaggerated bow to the Blood Master, the kill a show for the people.",
        "{name} stands with hands on hips, looking down at the remains with a satisfied, cocky grin.",
        "{name} takes a quick, mocking victory lap around the body before settling into a confident stance.",
    ],
    "Gnome": [
        "{name} adjusts a piece of gear with clinical detachment, the kill just another data point.",
        "{name} offers a thin, calculating smile to the fallen, the tactical puzzle solved.",
        "{name} mutters a string of complex observations to {himself}, ignoring the cheering crowd.",
        "{name} stands over the body with an analytical gaze, noting the exact efficiency of the strike.",
        "{name} performs a quick, precise flourish with {his} weapon, a mechanical celebration of form.",
        "{name} looks at the Blood Master with a questioning tilt of the head, as if seeking a score.",
        "{name} offers a small, polite nod to the remains, a tactician's professional courtesy.",
        "{name} checks {his} weapon for wear, the kill a secondary concern to the maintenance of {his} tools.",
        "{name} stands perfectly poised, {his} sharp eyes darting between the corpse and the stands.",
        "{name} gives a short, sharp laugh, the sound of a clever trap snapping shut.",
    ],
    "Goblin": [
        "{name} cackles with high-pitched glee, poking at the corpse with the tip of {his} weapon.",
        "{name} spits on the fallen, a mean-spirited hiss escaping {his} jagged teeth.",
        "{name} does a frantic, jerky dance of victory around the body, hissing at the crowd.",
        "{name} stares at the remains with wide, hungry eyes, a predator's joy in {his} gaze.",
        "{name} lets out a screeching victory cry that sounds like metal scraping on stone.",
        "{name} wipes {his} nose with a bloodied sleeve, looking down at the kill with cruel satisfaction.",
        "{name} mocks the fallen's final moments with a series of ugly, exaggerated gestures.",
        "{name} stands over the kill, {his} frame trembling with the feverish energy of the pit.",
        "{name} snarls at a nearby guard, the kill having stoked a feral fire in {his} blood.",
        "{name} kicks a handful of dirt into the face of the dead, a final, petty act of goblin triumph.",
    ],
    "Lizardfolk": [
        "{name} tastes the air with a flickering tongue, the scent of fresh blood thick and satisfying.",
        "{name} lets out a low, vibrating hiss that seems to come from the very depths of {his} chest.",
        "{name} stands over the kill with cold, unblinking eyes, a primal predator in {his} element.",
        "{name} sweeps {his} tail across the sand with a heavy thud, a rhythmic celebration of the kill.",
        "{name} stares at the corpse with a detached, reptilian hunger before turning to the stands.",
        "{name} opens {his} maw in a silent, terrifying display of teeth and victory.",
        "{name} stands perfectly still, {his} scales shimmering with the heat and blood of the arena.",
        "{name} offers a slow, deliberate blink to the Blood Master, the kill a simple fact of nature.",
        "{name} wipes a clawed hand across the sand, a cold and ancient ritual of the hunt.",
        "{name} lets out a sound that is half-roar and half-hiss, the voice of the swamp in the heart of the pit.",
    ],
    "Tabaxi": [
        "{name} licks a blood-spattered paw with feline poise, the kill handled with casual elegance.",
        "{name} stands over the remains, tail twitching in a rhythmic, satisfied pattern.",
        "{name} offers a wide, toothy grin to the crowd, {his} eyes narrowed with predatory delight.",
        "{name} stretches {his} lithe frame over the body, a graceful display of feline triumph.",
        "{name} lets out a sharp, bird-like chirp of victory that echoes through the silence of the stands.",
        "{name} moves around the kill with a series of fluid, dancing steps, light and dangerous.",
        "{name} gazes down at the fallen with a mix of curiosity and intense, feline pride.",
        "{name} performs a quick, acrobatic flip over the corpse, a flashy end to a lethal bout.",
        "{name} stands with {his} fur ruffled by the wind, the scent of the kill an intoxicating prize.",
        "{name} purrs: a low, unsettling rumble that carries surprisingly far in the quieted arena.",
    ],
    "Half-Elf": [
        "{name} stands with a conflicted but proud bearing, the duality of {his} blood clear in victory.",
        "{name} offers a disciplined salute to the stands, the kill a hard-won prize.",
        "{name} stares at the fallen with a look of somber respect before sheathing {his} weapon.",
        "{name} lets out a strong, clear shout of triumph that rings with both human passion and elven clarity.",
        "{name} stands tall over the remains, {his} features an elegant mask of warrior's pride.",
        "{name} wipes {his} blade with a methodical grace, the task completed with professional focus.",
        "{name} offers a slight, knowing smile to the crowd, the kill a validation of {his} hybrid path.",
        "{name} moves with a balance of power and agility that mocks the stillness of the dead.",
        "{name} looks at the Blood Master with a steady, confident gaze, a survivor's entitlement.",
        "{name} stands motionless for a heartbeat, the silence of the kill a moment of pure reflection.",
    ],
    "Monster": [
        "{name} lets out a deafening, bone-chilling roar that shakes the very foundations of the pit.",
        "{name} looms over the mangled remains, its eyes glowing with a malevolent, inhuman hunger.",
        "A terrifying, wet gurgle erupts from {name}'s throat as it stares down at its prize.",
        "{name} beats the ground with massive, blood-stained limbs, a primal display of raw power.",
        "{name} stands over the kill, a dark, pulsing shadow that seems to swallow the arena's light.",
        "The beast snarls at the crowd, its features twisted into a mask of pure, unadulterated rage.",
        "{name} pokes at the remains with a monstrous claw, a detached and terrible curiosity in its gaze.",
        "{name} lets out a high-pitched, unnatural shriek that sends a wave of cold through the stands.",
        "{name} looms over the body, its breath coming in hot, sulfurous clouds of victory.",
        "{name} remains perfectly still over the kill, a silent sentinel of the arena's darkest depths.",
    ],
    "Peasant": [
        "{name} stands over the fallen warrior with wide, disbelief-filled eyes, {his} weapon trembling in {his} hand.",
        "{name} lets out a ragged, desperate cheer, more relief than triumph in {his} voice.",
        "{name} stares at the body as if unable to comprehend that {he} is the one still standing.",
        "{name} offers a shaky, terrified salute to the crowd, the kill an accidental miracle.",
        "{name} wipes {his} face with a grimy sleeve, a frantic, victory-drunk laugh escaping {him}.",
        "{name} stands motionless, the scent of blood making {his} knees buckle with delayed shock.",
        "{name} looks at the Blood Master with a pleading gaze, as if asking for permission to leave.",
        "{name} does a small, clumsy dance of joy, a commoner's celebration of an impossible win.",
        "{name} spits a mouthful of dust and blood, a weary and surprised victor of the pit.",
        "{name} stands tall for the first time in {his} life, the kill having transformed {him} into something more.",
    ],
}


# ---------------------------------------------------------------------------
# STRATEGY SWITCH LINE
# ---------------------------------------------------------------------------

def strategy_switch_line(warrior_name: str, strat_idx: int) -> str:
    return f" * {warrior_name.upper()} switches to strategy {strat_idx}"


# ---------------------------------------------------------------------------
# OVERENCUMBRANCE FLAVOR LINES
# Fires ~25% chance each minute when armor_penalty >= 0.10.
# ---------------------------------------------------------------------------

_OVERENCUMBERED_LINES = [
    "{warrior} labors under the weight of {his} armor, breath already ragged.",
    "{warrior}'s movements are sluggish, dragged down by more iron than {his} frame can carry.",
    "Sweat pours down {warrior}'s face as {he} fights the drag of over-heavy armor.",
    "{warrior} staggers slightly under the bulk of gear that exceeds {his} strength.",
    "Every step is costing {warrior} something extra, the over-heavy armor grinding on {his} body.",
    "{warrior} planted that armor on a body not built to carry it, and it shows.",
    "The armor straps creak against {warrior}'s frame as {he} grinds to keep pace.",
    "{warrior} is burning down faster than expected, the armor wearing on {him}.",
    "{warrior} presses forward, but the weight of that armor is a tax on every move.",
    "{warrior} is working twice as hard just to move in that gear.",
    "That armor on {warrior} is too much for {his} strength, and the crowd can see it.",
    "The toll of wearing armor beyond {his} strength is plain in {warrior}'s labored movement.",
]

_OVERENCUMBERED_PREFIGHT_LINES = [
    "{warrior} enters the arena already straining under armor that exceeds {his} strength.",
    "The crowd murmurs as {warrior} takes the field. That armor is clearly beyond {his} frame.",
    "{warrior} steps onto the sand in gear too heavy for {his} build. It will cost {him}.",
    "Before a single blow is thrown, {warrior}'s over-heavy armor is already working against {him}.",
    "{warrior} is burdened from the moment {he} sets foot on the sand, carrying armor far too heavy for {his} strength.",
    "It is plain to the crowd that {warrior}'s armor exceeds {his} strength. {he} will pay for that choice.",
    "{warrior} marches out bearing armor {his} body was not built to carry.",
    "The arena master eyes {warrior}'s kit, noting that the heavy iron exceeds {his} strength before the fight has even begun.",
    "{warrior} is already fighting the weight of {his} armor before the first blow is struck.",
    "That armor looks impressive on {warrior}, but it is heavier than {his} frame can handle.",
]


def overencumbered_prefight_line(warrior_name: str, gender: str) -> str:
    his = "his" if gender == "Male" else "her"
    he  = "He"  if gender == "Male" else "She"
    him = "him" if gender == "Male" else "her"
    template = random.choice(_OVERENCUMBERED_PREFIGHT_LINES)
    return template.format(
        warrior=warrior_name.upper(),
        his=his,
        he=he,
        him=him,
    )


def overencumbered_line(warrior_name: str, gender: str) -> str:
    his = "his" if gender == "Male" else "her"
    he  = "he"  if gender == "Male" else "she"
    him = "him" if gender == "Male" else "her"
    template = random.choice(_OVERENCUMBERED_LINES)
    return template.format(
        warrior=warrior_name.upper(),
        his=his,
        he=he,
        him=him,
    )


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
        "{name} unleashes a terrifying, bloodthirsty roar and storms forward",
        "{name} abandons all pretense of defense, hunting only for a slaughter",
        "{name} swings with murderous intent, completely blinded by battle-fury",
        "{name} presses a chaotic, savage assault meant to completely butcher {foe}",
        "{name} storms the line, bringing down a desperate, bone-crushing strike",
        "{name} drives forward like a madman, looking to hack {foe} to pieces",
    ],
    "Wall of Steel": [
        "{name} relentlessly presses forward with {his} {weapon}",
        "{name} creates a whirling wall of steel",
        "{name} attacks in a flurry of blows",
        "{name} hammers away with tireless, rhythmic persistence",
        "{name} drives an unyielding tempest of iron at {foe}",
        "{name} maintains an absolute, suffocating pressure",
        "{name} unleashes a ceaseless, crushing barrage of strikes",
        "{name} locks down the defensive line, advancing grimly",
        "{name} dictates the rhythm of combat with a relentless cadence",
    ],
    "Lunge": [
        "{name} darts forward, looking for an opening",
        "{name} probes for a weakness in {foe}'s defense",
        "{name} moves with quick, precise footwork",
        "{name} circles {foe}, reading the moment to commit",
        "{name} violently explodes forward from a crouch",
        "{name} extends {his} reach to its absolute limit, striking hard",
        "{name} drives a sudden, piercing line of attack",
        "{name} shifts weight instantly to launch a low, flashing strike",
        "{name} closes the distance with a committed thrust",
        "{name} throws a cunning feint before committing to a hard stab",
        "{name} lunges cleanly through a sudden gap in the guard",
    ],
    "Bash": [
        "{name} winds up for a crushing blow",
        "{name} drives forward with brute force",
        "{name} attempts to batter through {foe}'s defenses",
        "{name} puts the entirety of {his} weight behind a punishing smash",
        "{name} looks to break bone and shatter iron with a heavy impact",
        "{name} rears back to deliver a concussive, grounding assault",
        "{name} targets {foe}'s vitals with a slow, devastating wind-up",
    ],
    "Slash": [
        "{name} draws back for a sweeping slash",
        "{name} lines up for a powerful drawing cut",
        "{name} seeks to open a telling wound",
        "{name} unleashes a wide, flashing arc of steel toward {foe}",
        "{name} carves a wicked path through the air with {his} {weapon}",
        "{name} slices forward in a deadly, fluid motion designed to draw blood",
        "{name} pivots sharply to deliver a vicious, tearing slash",
    ],
    "Strike": [
        "{name} tries to hit the mighty {foe}",
        "{name} sizes up {foe} carefully",
        "{name} directs an attack toward {foe}",
        "{name} steps threateningly close to the {adj} {foe}",
        "{name} tests the distance, launching a sudden attack at {foe}",
        "{name} squares {his} shoulders and lashes out at the {adj} opponent",
        "{name} finds an opening and instantly drives {his} {weapon} forward",
        "{name} advances with a calculated, standard offensive against the {adj} {foe}",
    ],
    "Engage & Withdraw": [
        "{name} probes for weakness, then retreats to reposition",
        "{name} feints left, striking before pulling back",
        "{name} dances in close, lashing out before withdrawing",
        "{name} steps in with a sharp blow before springing backward out of danger",
        "{name} tests the line with a quick strike, then instantly glides out of range",
        "{name} plays a dangerous game of distance, striking before pulling back",
        "{name} slips inside the guard, striking quickly before retreating to safety",
    ],
    "Counterstrike": [
        "{name} waits patiently for {foe} to make a mistake",
        "{name} holds ground, watching {foe} like a hawk",
        "{name} anxiously awaits {foe}'s next move",
        "{name} anchors {his} weight, coiled like a spring to exploit the slightest slip",
        "{name} tracks the arc of {foe}'s stance, biding time for a fatal mistake",
        "{name} lets {foe} dictate the tempo, preparing to violently reverse the momentum",
        "{name} keeps a perfectly still guard, baiting the attack to execute a sharp riposte",
    ],
    "Decoy": [
        "{name} engages {foe}'s weapon with {his} off-hand",
        "{name} feints to draw {foe}'s attention",
        "{name} draws {foe} into an elaborate trap",
        "{name} purposely exposes a glaring opening to mask a lethal incoming strike",
        "{name} drops {his} guard for a split second, daring {foe} to rush forward",
        "{name} throws a loud, distracting blow to mask the true path of {his} {weapon}",
        "{name} misdirects with a sudden shift in posture, blinding {foe} to the real danger",
    ],
    "Sure Strike": [
        "{name} waits for the right moment, then commits fully",
        "{name} carefully prepares a deliberate strike",
        "{name} takes aim at {foe} with methodical precision",
        "{name} narrows {his} focus, blocking out the roaring crowd to ensure a perfect hit",
        "{name} aligns {his} posture to guarantee the oncoming blow finds its mark",
        "{name} measures the distance perfectly before committing to a flawless execution",
        "{name} refuses to waste motion, locking onto a definitive weakness in the defense",
    ],
    "Calculated Attack": [
        "{name} ruthlessly seeks wreckage with {his} {weapon}",
        "{name} calculates the perfect attack angle",
        "{name} studies {foe}'s armor for weak points",
        "{name} analyzes the gaps in the iron plate to maximize the impending trauma",
        "{name} maps out a lethal trajectory across the sand with cold, analytical focus",
        "{name} deliberately exploits a minor flaw in {foe}'s footwork to setup a devastating wound",
        "{name} weighs the risk of the engagement, choosing a path of maximum destruction",
    ],
    "Opportunity Throw": [
        "{name} hefts {his} {weapon} for a throw",
        "{name} lines up a ranged attack",
        "{name} spots a momentary lapse in distance and cocks {his} arm back to launch",
        "{name} balances the weight of {his} {weapon}, preparing to send it flying through the air",
        "{name} readies a lethal projectile strike as the gap between the fighters widens",
        "{name} prepares to release a flying assault that will catch {foe} completely off guard",
        "{name} measures the distance for a desperate, high-stakes ranged throw",
    ],
    "Martial Combat": [
        "{name} drops into a fighting crouch",
        "{name} circles {foe} with fluid martial grace",
        "{name} prepares to unleash a flurry of strikes",
        "{name} shifts seamlessly between combat stances, executing flawless form",
        "{name} channels disciplined training, moving with the cold efficiency of a veteran",
        "{name} balances weight perfectly on the balls of {his} feet, ready for a complex sequence",
        "{name} controls the space with expert positioning, establishing absolute command of the sand",
    ],
    "Parry": [
        "{name} raises {his} {weapon} defensively",
        "{name} holds ground, focused entirely on defense",
        "{name} sets an iron guard, tracking the trajectory of the incoming threat",
        "{name} angles {his} blade to catch and deflect the next strike with minimal effort",
        "{name} mirrors {foe}'s weapon movements, preparing a crisp deflection",
        "{name} readies a tight, defensive redirection to turn the momentum of the fight",
        "{name} anchors {his} posture, waiting to cross steel and turn the blow aside",
    ],
    "Defend": [
        "{name} keeps {his} guard high",
        "{name} circles warily, waiting for an opening",
        "{name} tucks {his} chin and locks down {his} defensive perimeter",
        "{name} refuses to overextend, maintaining an unbreakable protective posture",
        "{name} yields ground deliberately, monitoring the distance with absolute caution",
        "{name} hunkers down behind a wall of steel, offering {foe} zero easy targets",
        "{name} watches the opponent's shoulders, entirely prepared to absorb or evade the coming assault",
    ],
}

# ---------------------------------------------------------------------------
# ARMOR-SPECIFIC INTENT LINES
# Override generic intent lines based on opponent's armor type.
# Maps: style -> armor_type -> narratives
# Armor categories:
#   "plate"   = Full Plate, Half-Plate, Brigandine (metal plating)
#   "chain"   = Chain, Scale (interlocking links/rings)
#   "leather" = Leather, Cuir Boulli (soft/hardened leather, no plates)
#   "none"    = No armor or unarmored
# ---------------------------------------------------------------------------

ARMOR_SPECIFIC_INTENT_POOLS: dict[str, dict[str, list[str]]] = {
    "Bash": {
        "plate": [
            "{name} looks to bash through the metal plating with brutal force",
            "{name} targets the seams between the armor plates",
            "{name} winds up to shatter the iron protection",
        ],
        "chain": [
            "{name} winds up to pummel the chain links into submission",
            "{name} looks to break bone beneath the metal mesh",
        ],
        "leather": [
            "{name} looks to cave in the leather and crack ribs",
            "{name} winds up to shatter bone beneath the hardened leather",
        ],
        "none": [
            "{name} looks to break bone and shatter resolve",
            "{name} winds up for a crushing blow to bare flesh",
        ],
    },
    "Sure Strike": {
        "plate": [
            "{name} takes aim at the gaps between the armor plates",
            "{name} narrows focus on the seams of the metal protection",
        ],
        "chain": [
            "{name} measures the spacing of the chain links for maximum penetration",
            "{name} takes aim at the openings in the mesh",
        ],
        "leather": [
            "{name} studies the seams and weak points in the leather",
            "{name} measures weak points in the hardened hide",
        ],
        "none": [
            "{name} measures the distance for a precise strike to bare skin",
            "{name} zeroes in on a vital, unprotected target",
        ],
    },
    "Calculated Attack": {
        "plate": [
            "{name} analyzes the gaps between the metal plates with surgical precision",
            "{name} maps out the seams in the armor for maximum lethality",
            "{name} studies the weak points where the plating overlaps",
        ],
        "chain": [
            "{name} calculates the spacing of the chain links to find an opening",
            "{name} analyzes gaps in the metal mesh for the perfect strike",
            "{name} studies the pattern of the links to find maximum vulnerability",
        ],
        "leather": [
            "{name} analyzes the seams in the leather to maximize impending trauma",
            "{name} studies the weak points where the hardened leather begins to crack",
            "{name} calculates a strike against the toughest hide",
        ],
        "none": [
            "{name} analyzes the bare, vulnerable target with cold precision",
            "{name} calculates the perfect strike against unprotected flesh",
            "{name} studies the vital points with surgical focus",
        ],
    },
}

def _get_armor_category(armor_name: Optional[str]) -> str:
    """Categorize armor type for narrative selection."""
    if not armor_name:
        return "none"

    armor_lower = armor_name.lower()

    # Plate-based armor
    if any(x in armor_lower for x in ["plate", "brigandine"]):
        return "plate"

    # Chain-based armor
    if any(x in armor_lower for x in ["chain", "scale"]):
        return "chain"

    # Leather-based armor
    if any(x in armor_lower for x in ["leather", "cuir"]):
        return "leather"

    # Default to none
    return "none"

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
    foe_armor    : Optional[str] = None,
) -> Optional[str]:
    """
    Return a style intent line (or None, ~60% skip chance).
    Uses armor-specific narratives when available for the style.
    """
    if random.random() < 0.30:
        return None

    # Try to get armor-specific pool first
    if foe_armor and style in ARMOR_SPECIFIC_INTENT_POOLS:
        armor_category = _get_armor_category(foe_armor)
        armor_pools = ARMOR_SPECIFIC_INTENT_POOLS[style]
        if armor_category in armor_pools:
            pool = armor_pools[armor_category]
        else:
            # Fall back to generic pool if armor category not found
            pool = STYLE_INTENT_POOLS.get(style, STYLE_INTENT_POOLS["Strike"])
    else:
        # Use generic pool if no armor specified or style not in armor-specific pools
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
# Note: "claws" (plural) needs plural verbs; "leg/tail" (singular) needs singular verbs
LIZARDFOLK_ATTACK_VERBS: dict[str, list[str]] = {
    "claw"  : ["rake", "slash", "tear", "rend"],
    "kick"  : ["kicks", "stomps", "drives a powerful kick", "lashes out with a kick"],
    "tail"  : ["sweeps", "lashes", "swings", "whips"],
}

# Tabaxi-specific attack verbs when using Open Hand/Martial Combat
# Features claw rakes and powerful kicks
# Note: "claws" (plural) needs plural verbs; "leg" (singular) needs singular verbs
TABAXI_ATTACK_VERBS: dict[str, list[str]] = {
    "claw"  : ["rake", "slash", "tear", "rend"],
    "kick"  : ["kicks", "stomps", "drives a powerful kick", "lashes out with a kick"],
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
    "Counterstrike"    : ["strikes carefully at", "prepares a measured blow at",
                          "waits for an opening and attacks"],
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
    is_favorite_weapon: bool = False,  # Include "beloved" if this is their favorite weapon
) -> str:
    """Generate the attack declaration line. Lizardfolk with Open Hand get special claw/tail/kick verbs."""
    loc_pool = AIM_POINT_LABELS.get(aim_point, AIM_POINT_LABELS["None"])
    location = random.choice(loc_pool)
    pronoun  = "his" if attacker_gender == "Male" else "her"

    # Lizardfolk with Open Hand use special descriptors (claws, kicks, tail)
    if attacker_race == "Lizardfolk" and weapon_name == "Open Hand":
        attack_types = ["claw", "kick", "tail"]
        # Use defender name to seed the choice so attack/hit/damage lines are consistent
        attack_type = attack_types[sum(ord(c) for c in defender_name) % len(attack_types)]

        verb_pool = LIZARDFOLK_ATTACK_VERBS.get(attack_type, LIZARDFOLK_ATTACK_VERBS["claw"])
        verb = random.choice(verb_pool)

        # Format with proper weapon descriptor in the sentence (no pronoun prefix)
        weapon_descriptors = {
            "claw": "claws",
            "kick": "leg",
            "tail": "tail",
        }
        weapon_desc = weapon_descriptors.get(attack_type, "claws")

        return (
            f"{attacker_name.upper()}'s {weapon_desc} {verb} at {defender_name.upper()}'s {location}!"
        )

    # Tabaxi with Open Hand use special descriptors (claws and kicks)
    if attacker_race == "Tabaxi" and weapon_name == "Open Hand":
        attack_types = ["claw", "kick"]
        # Use defender name to seed the choice so attack/hit/damage lines are consistent
        attack_type = attack_types[sum(ord(c) for c in defender_name) % len(attack_types)]

        verb_pool = TABAXI_ATTACK_VERBS.get(attack_type, TABAXI_ATTACK_VERBS["claw"])
        verb = random.choice(verb_pool)

        # Format with proper weapon descriptor in the sentence (no pronoun prefix)
        weapon_descriptors = {
            "claw": "claws",
            "kick": "leg",
        }
        weapon_desc = weapon_descriptors.get(attack_type, "claws")

        return (
            f"{attacker_name.upper()}'s {weapon_desc} {verb} at {defender_name.upper()}'s {location}!"
        )

    # Opportunity Throw uses a throw-specific sentence structure
    if style == "Opportunity Throw":
        throw_verb = random.choice(["hurls", "flings", "launches", "sends", "pitches"])
        wpn_desc = weapon_name.lower()
        if is_favorite_weapon:
            wpn_desc = f"beloved {wpn_desc}"
        return (
            f"{attacker_name.upper()} {throw_verb} {pronoun} {wpn_desc} "
            f"at {defender_name.upper()}'s {location}!"
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

THROW_HIT_VERBS: list[str] = [
    "slams into", "buries itself in", "embeds in", "pierces",
    "strikes home on", "drives through", "punches into",
]

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

# Tabaxi-specific hit verbs when using claws or feet in martial combat
TABAXI_HIT_VERBS: dict[str, list[str]] = {
    "claw"  : ["rakes across", "shreds", "tears into", "slashes across", "rends"],
    "kick"  : ["crashes into", "smashes into", "crushes into", "drives into"],
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
    style         : str = None,       # For Opportunity Throw special handling
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
        # Use defender name to seed the choice to match attack_line
        attack_type = attack_types[sum(ord(c) for c in defender_name) % len(attack_types)]

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
    # Tabaxi with Open Hand use special claw/kick descriptions
    elif attacker_race == "Tabaxi" and weapon_name == "Open Hand":
        attack_types = ["claw", "kick"]
        # Use defender name to seed the choice to match attack_line
        attack_type = attack_types[sum(ord(c) for c in defender_name) % len(attack_types)]

        verb_pool = TABAXI_HIT_VERBS.get(attack_type, TABAXI_HIT_VERBS["claw"])
        verb = random.choice(verb_pool)
        target_pool = HIT_TARGETS.get(aim_point, HIT_TARGETS["None"])
        target = random.choice(target_pool)

        # Create attack type descriptor
        attack_desc = {
            "claw": "claws",
            "kick": "powerful kick",
        }.get(attack_type, "claws")

        lines.append(
            f"{attacker_name.upper()}'s {attack_desc} "
            f"{verb} {defender_name.upper()}'s {target}!"
        )
    else:
        target_pool = HIT_TARGETS.get(aim_point, HIT_TARGETS["None"])
        target = random.choice(target_pool)
        if weapon_name.lower() == "bola":
            # Bola hits with swinging weighted balls - flail-style, never "embeds" or "pierces"
            verb = random.choice(["crashes into", "slams into", "smashes into", "wraps around and strikes"])
        elif style == "Opportunity Throw":
            verb = random.choice(THROW_HIT_VERBS)
        else:
            verb_pool = HIT_VERBS.get(weapon_category, HIT_VERBS["Oddball"])
            verb = random.choice(verb_pool)
        lines.append(
            f"{attacker_name.upper()}'s {weapon_name.lower()} "
            f"{verb} {defender_name.upper()}'s {target}!"
        )
    return lines


def injury_flare_up_lines(warrior_name: str, location: str, gender: str) -> list[str]:
    """Lines for when an existing injury is aggravated by a fresh blow."""
    pronoun = "his" if gender == "Male" else "her"
    loc_name = location.replace("_", " ")
    
    pools = [
        f"{warrior_name.upper()} winces as the old {loc_name} wound flares with blinding pain!",
        f"A fresh blow catches the scarred flesh of {warrior_name.upper()}'s {loc_name}!",
        f"The impact aggravates {warrior_name.upper()}'s existing {loc_name} injury!!",
        f"{warrior_name.upper()} staggers as the previous {loc_name} wound begins to throb and bleed anew!",
    ]
    
    secondary = {
        "head": f"{warrior_name.upper()}'s vision clouds from the agony!",
        "primary_arm": f"{warrior_name.upper()}'s weapon arm goes numb and trembles!",
        "primary_leg": f"{warrior_name.upper()} limps heavily, {pronoun} leg nearly giving way!",
        "secondary_leg": f"{warrior_name.upper()} struggles to keep {pronoun} balance as the leg wound flares!",
    }
    
    return [random.choice(pools), secondary.get(location, "The pain is debilitating!")]


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


def damage_line(damage: int, max_hp: int, weapon_category: str = "Oddball",
                is_claw_attack: bool = False) -> str:
    """
    Return a damage description line based on damage severity and weapon type.

    Args:
        damage: Damage dealt
        max_hp: Target's max HP
        weapon_category: Weapon category (Oddball, Sword/Knife, etc.)
        is_claw_attack: True if this is a claw rake/slash (for Lizardfolk/Tabaxi)
    """
    pct = damage / max(1, max_hp)
    if   pct < 0.19: severity = "Light"
    elif pct < 0.34: severity = "Medium"
    else:            severity = "Heavy"

    # For Lizardfolk/Tabaxi claw attacks, use Slashing descriptions instead of Generic/Bludgeoning
    if is_claw_attack and weapon_category == "Oddball":
        dmg_type = "Slashing"
    else:
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

THROW_MISS_LINES = [
    "{attacker}'s {weapon} sails wide of the mark!",
    "The thrown {weapon} arcs well clear of its target!",
    "{attacker}'s aim is off, the {weapon} flies harmlessly past!",
    "The {weapon} tumbles end-over-end, but clears {attacker_foe} entirely!",
    "{attacker}'s throw is wide, the {weapon} clattering across the sand!",
    "The {weapon} whistles past, finding nothing but air!",
]


def miss_line(attacker_name: str, weapon_name: str) -> str:
    template = random.choice(MISS_LINES)
    return template.format(
        attacker=attacker_name.upper(),
        weapon  =weapon_name.lower(),
    )


def throw_miss_line(attacker_name: str, weapon_name: str, defender_name: str) -> str:
    template = random.choice(THROW_MISS_LINES)
    return template.format(
        attacker     =attacker_name.upper(),
        weapon       =weapon_name.lower(),
        attacker_foe =defender_name.upper(),
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
    "{defender} had that area covered, the defense holds!",
    "{defender}'s focus there pays off, turning the strike aside!",
    "That spot was well protected, {defender} deflects cleanly!",
    "{defender}'s guard on that area proves its worth!",
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
# DEFENSE FAIL LINES (fired when a defense intent was shown but the hit lands)
# These bridge the gap between "defender prepares" and "attack connects".
# ---------------------------------------------------------------------------

DEFENSE_FAIL_PARRY = [
    "But the guard comes a fraction too late!",
    "The timing is wrong, leaving the parry just off target!",
    "{defender}'s guard is overwhelmed!",
    "But {defender} commits to the wrong angle!",
    "{defender}'s guard is forced aside!",
    "The attack finds a gap in the defense!",
    "But the parry is off by a crucial margin!",
    "{defender} reads the attack wrong!",
    "The defense is overpowered!",
    "The guard holds for a moment, then gives way!",
]

DEFENSE_FAIL_DODGE = [
    "But the dodge isn't quite enough!",
    "{defender} can't move fast enough!",
    "The escape route closes too quickly!",
    "{defender} is a half-step too slow!",
    "The attack angle was unexpected!",
    "{defender} is caught mid-step!",
    "There is nowhere to go!",
    "{defender} commits to the wrong direction!",
]


def defense_fail_line(defender_name: str, gender: str, uses_parry: bool) -> str:
    pool = DEFENSE_FAIL_PARRY if uses_parry else DEFENSE_FAIL_DODGE
    return random.choice(pool).format(defender=defender_name.upper())


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
    "{warrior} is one solid hit away from the Monster Bouts!",
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
    "{attacker} sells the feint. {foe} lunges to block a blow that isn't coming!",
    "{attacker} dips a shoulder and {foe} bites on the bluff!",
]

DECOY_FEINT_READ_LINES = [
    "{foe} reads the feint and holds position, unshaken!",
    "{foe} anticipates the trick, and the ruse falls flat!",
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
# Fires when a Calculated Attack strike lands a precision hit -the attacker
# threads the blow through a seam in the defender's guard or armor. Lines
# are keyed by target body location so the narrative calls out the weak
# point being exploited.

CALCULATED_PRECISION_LINES = {
    "head": [
        "{attacker} spots the gap beside {foe}'s guard and drives {his} {weapon} home!",
        "{attacker} threads {his} {weapon} past {foe}'s defenses, straight for the temple!",
        "With cold precision, {attacker} finds a vulnerable opening near {foe}'s eyes!",
        "{attacker}'s {weapon} slips past {foe}'s high guard into the jawline!",
        "{attacker} guides {his} {weapon} directly through a vulnerability in {foe}'s upper defenses!",
        "{attacker} targets the exposed skin right along the edge of {foe}'s neckline!",
        "{attacker} slips a calculated strike just underneath the lower edge of {foe}'s chin!",
    ],
    "chest": [
        "{attacker} slips {his} {weapon} past the main defenses, finding {foe}'s rib line!",
        "{attacker} spots a seam in {foe}'s defensive posture and strikes!",
        "{attacker}'s {weapon} threads a vital gap in {foe}'s upper torso coverage!",
        "{attacker} drives {his} {weapon} through the open space just beneath {foe}'s armpit!",
        "{attacker} exploits a momentary opening in the stance right over {foe}'s collarbone!",
        "{attacker} targets a tiny opening where {foe}'s forward defenses part!",
        "{attacker} centers {his} weight and threads {his} {weapon} straight past the flank of {foe}'s chest!",
    ],
    "gut": [
        "{attacker} drives {his} {weapon} up under {foe}'s ribs!",
        "{attacker} finds the soft opening at {foe}'s belt line!",
        "{attacker}'s {weapon} threads the gap beneath {foe}'s midsection defenses!",
        "{attacker} picks the join at {foe}'s waist and strikes clean!",
        "{attacker} guides the attack straight through a lapse in the center of {foe}'s stance!",
        "{attacker} finds a vulnerable fold right at the center of {foe}'s torso!",
        "{attacker} bypasses the main protective posture to strike {foe}'s exposed abdomen!",
    ],
    "arms": [
        "{attacker} picks the gap at {foe}'s shoulder joint!",
        "{attacker}'s {weapon} finds the inside of {foe}'s elbow!",
        "{attacker} slips the strike past {foe}'s extended forearm!",
        "{attacker}'s measured thrust lands in the opening beside {foe}'s bicep!",
        "{attacker} finds the unshielded inner side of {foe}'s forearm!",
        "{attacker} snakes {his} {weapon} through the opening where {foe}'s shoulder drops!",
        "{attacker} spots an exposed patch near {foe}'s wrist and strikes!",
    ],
    "legs": [
        "{attacker} drives {his} {weapon} behind {foe}'s knee!",
        "{attacker} finds the gap just above {foe}'s lower leg!",
        "{attacker}'s strike threads the opening at {foe}'s thigh!",
        "{attacker} picks the joint right at {foe}'s knee!",
        "{attacker} places a perfect hit right into the unprotected back of {foe}'s thigh!",
        "{attacker} slips {his} {weapon} through a narrow opening near {foe}'s hip!",
        "{attacker} catches a vulnerable gap just along the boundary of {foe}'s lower leg!",
    ],
}

CALCULATED_PROBE_LINES = [
    "{attacker} probes methodically for an opening, but {foe}'s guard holds!",
    "{attacker} studies {foe}'s defense, waiting for a seam that never comes!",
    "{attacker} measures a strike and thinks better of it. {foe} is simply too disciplined!",
    "{attacker}'s calculating eye finds no gap in {foe}'s guard this pass!",
    "{attacker} circles, searching for a weakness, but {foe} stays tight!",
]


def calculated_precision_line(
    attacker_name: str, foe_name: str, weapon_name: str, aim_point: str, attacker_gender: str = "Male"
) -> str:
    """
    Narrative line for a landed Calculated Attack precision hit.
    Falls back to the chest pool if the aim point isn't keyed.
    """
    his = "his" if attacker_gender == "Male" else "her"
    key  = (aim_point or "chest").lower()
    pool = CALCULATED_PRECISION_LINES.get(key, CALCULATED_PRECISION_LINES["chest"])
    return random.choice(pool).format(
        attacker=attacker_name.upper(),
        foe=foe_name.upper(),
        weapon=weapon_name.lower(),
        his=his
    )


def calculated_probe_line(attacker_name: str, foe_name: str) -> str:
    return random.choice(CALCULATED_PROBE_LINES).format(
        attacker=attacker_name.upper(), foe=foe_name.upper()
    )


# ---------------------------------------------------------------------------
# GROUND / KNOCKDOWN LINES
# ---------------------------------------------------------------------------

KNOCKDOWN_LINES = [
    "{warrior} crashes violently onto the arena floor!",
    "{warrior} goes crashing heavily to the ground!",
    "{warrior} is knocked completely off {his} feet!",
    "{warrior} stumbles and falls hard to the sand!",
    "{warrior} loses {his} footing and slams against the arena floor!",
    "{warrior} is violently upended and sent eating sand!",
    "{warrior} loses {his} footing and slams hard against the sand!",
    "{warrior} collapses like a felled oak under the impact!",
    "{warrior} is driven down hard onto the arena floor!",
    "{warrior} buckles under the force and hits the ground with a heavy thud!",
    "{warrior} is sent reeling before collapsing into the bloodied sands!",
]

GET_UP_LINES = [
    "{warrior} scrambles back to {his} feet.",
    "{warrior} gets up, shaken but ready.",
    "{warrior} staggers upright.",
    "{warrior} rises from the sand, spitting blood.",
    "{warrior} pushes up from the sand, ready for more!",
    "{warrior} hauls {his} battered body off the arena floor!",
    "{warrior} forces {his} way back to a standing guard!",
    "{warrior} rises defiantly from the bloodied sands!",
    "{warrior} claws {his} way back up from the ground!",
]

GROUND_STRUGGLE_LINES = [
    "{warrior} tries to rise but cannot find {his} footing!",
    "{warrior} scrambles in the sand, unable to regain {his} feet!",
    "{warrior} claws at the sand but stays down!",
    "{warrior} fights to stand, but {his} legs won't cooperate!",
    "{warrior} thrashes on the arena floor but cannot get back up!",
    "{warrior} struggles to push away from the ground, pinned by an unrelenting assault!",
    "{warrior} slips on the bloodied sands, failing to lift {his} weight!",
    "{warrior} desperately tries to haul {his} body up but collapses back down!",
    "{warrior} writhes on the arena floor, unable to find an opening to rise!",
]

GROUND_ATTACK_LINES = [
    "{warrior} lashes out desperately from the ground!",
    "{warrior} strikes upward from {his} knees!",
    "{warrior} swings wildly from the sand!",
    "{warrior} attacks from a losing position!",
    "{warrior} thrusts an attack upward from the arena floor!",
    "{warrior} launches a sudden counter strike from the sands!",
    "{warrior} retaliates fiercely while still trapped on the ground!",
    "{warrior} drives a low blow forward from the sand!",
    "{warrior} snaps a desperate strike up from the arena floor!",
]


def knockdown_line(warrior_name: str, gender: str) -> str:
    pronoun = "his" if gender == "Male" else "her"
    template = random.choice(KNOCKDOWN_LINES)
    return template.format(warrior=warrior_name.upper(), his=pronoun)


def getup_line(warrior_name: str, gender: str) -> str:
    pronoun = "his" if gender == "Male" else "her"
    template = random.choice(GET_UP_LINES)
    return template.format(warrior=warrior_name.upper(), his=pronoun)


def ground_struggle_line(warrior_name: str, gender: str) -> str:
    """Failed recovery attempt - warrior tries to get up but can't."""
    pronoun = "his" if gender == "Male" else "her"
    return random.choice(GROUND_STRUGGLE_LINES).format(
        warrior=warrior_name.upper(), his=pronoun)


def ground_attack_line(warrior_name: str, gender: str) -> str:
    """Warrior attacks from the ground after failing to rise."""
    pronoun = "his" if gender == "Male" else "her"
    return random.choice(GROUND_ATTACK_LINES).format(
        warrior=warrior_name.upper(), his=pronoun)


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
        "{w}'s leg seizes up with blinding pain, every step a desperate struggle!!",
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


def injury_flare_up_lines(warrior_name: str, location: str, gender: str) -> list[str]:
    """Lines for when an existing injury is aggravated by a fresh blow."""
    pronoun = "his" if gender == "Male" else "her"
    loc_name = location.replace("_", " ")
    
    pools = [
        f"{warrior_name.upper()} winces as the old {loc_name} wound flares with blinding pain!",
        f"A fresh blow catches the scarred flesh of {warrior_name.upper()}'s {loc_name}!",
        f"The impact aggravates {warrior_name.upper()}'s existing {loc_name} injury!!",
        f"{warrior_name.upper()} staggers as the previous {loc_name} wound begins to throb and bleed anew!",
    ]
    
    secondary = {
        "head": f"{warrior_name.upper()}'s vision clouds from the agony!",
        "primary_arm": f"{warrior_name.upper()}'s weapon arm goes numb and trembles!",
        "primary_leg": f"{warrior_name.upper()} limps heavily, {pronoun} leg nearly giving way!",
        "secondary_leg": f"{warrior_name.upper()} struggles to keep {pronoun} balance as the leg wound flares!",
    }
    
    return [random.choice(pools), secondary.get(location, "The pain is debilitating!")]


def weapon_drop_lines(warrior_name: str, weapon_name: str, gender: str, is_fumble: bool = False, is_forceful: bool = False) -> str:
    """Narrative lines for when a warrior drops their weapon (fumble or disarm)."""
    pronoun = "his" if gender == "Male" else "her"   # possessive
    obj_pro = "him" if gender == "Male" else "her"   # object
    sub_pro = "he"  if gender == "Male" else "she"   # subject
    wpn = weapon_name.lower()
    n = warrior_name.upper()

    if is_fumble:
        pools = [
            f"The sudden surge of pain causes {n} to drop {pronoun} {wpn}!",
            f"{n}'s grip fails as {pronoun} arm spasms, sending the {wpn} to the sand!",
            f"Agony wracks {n}'s arm and the {wpn} slips from {pronoun} numb fingers!",
            f"A sharp intake of breath, and {n} fumbles the {wpn}, unable to maintain {pronoun} hold!",
            f"The wound takes its toll. {n}'s {wpn} tumbles free from {pronoun} failing grip!",
            f"{n}'s fingers betray {obj_pro} as the pain overwhelms, and the {wpn} hits the dirt!",
            f"The injury flares at the worst moment and {n} cannot hold the {wpn}!",
            f"{n} clenches {pronoun} teeth but the {wpn} falls regardless, {pronoun} arm refusing to obey!",
            f"Pain shoots through {n}'s arm, and the {wpn} clatters to the sand before {sub_pro} can stop it!",
            f"The arm gives out. {n}'s {wpn} drops to the arena floor with a dull thud!",
        ]
    elif is_forceful:
        pools = [
            f"The force of the blow wrenches the {wpn} from {n}'s hands! It clatters to the sand!",
            f"The impact is too much: {n}'s {wpn} is ripped away by the sheer power of the strike!",
            f"A bone-jarring blow jars the {wpn} loose from {n}'s grasp!",
            f"The brutal weight of the attack hammers the {wpn} from {n}'s numbed fingers!",
            f"The sheer violence of the blow sends the {wpn} spinning from {n}'s grip!",
            f"A thunderous strike rattles {n}'s arms, sending the {wpn} flying to the sand!",
            f"The impact travels straight up {n}'s arms and the {wpn} is torn free!",
            f"Strength against strength: {n} loses. The {wpn} is ripped away and crashes to the ground!",
            f"The {wpn} is blasted clean from {n}'s hands by the ferocity of the blow!",
            f"{n} staggers from the impact, and the {wpn} clatters across the arena floor!",
        ]
    else:
        pools = [
            f"{n} loses {pronoun} grip and the {wpn} falls to the ground!",
            f"The {wpn} slips from {n}'s hands and hits the sand with a heavy thud!",
            f"In the chaos, {n} drops {pronoun} {wpn}!",
            f"A clumsy moment. {n}'s {wpn} tumbles free to the arena floor!",
            f"The {wpn} slips from sweat-slicked fingers and crashes to the sand!",
            f"{n} can't maintain {pronoun} grip, and the {wpn} clatters away!",
            f"Footing lost, focus lost: {n}'s {wpn} lands in the dirt!",
            f"The {wpn} tears loose and skids across the sand!",
        ]
    return "   " + random.choice(pools)


def unarmed_impact_lines(warrior_name: str, gender: str) -> str:
    """Lines for a heavy blow landing on an unarmed fighter (Open Hand or Cestus). No disarm possible."""
    pronoun = "his" if gender == "Male" else "her"
    n = warrior_name.upper()
    pools = [
        f"The thunderous blow sends a wave of numbness through {n}'s arm!",
        f"The force hammers into {n}'s guard, leaving {pronoun} arm momentarily leaden!",
        f"{n}'s arm goes numb from the sheer impact, {pronoun} fists still clenched!",
        f"The brutal strike jars {n}'s arm savagely!",
        f"The blow rattles {n}'s guard -{pronoun} knuckles absorb the brunt and hold!",
        f"{n} reels from the impact, {pronoun} arm tingling with bone-deep force!",
        f"The impact staggers {n}, {pronoun} arm dead with numbness for a heartbeat!",
        f"A savage blow leaves {n}'s arm briefly numb!",
    ]
    return "   " + random.choice(pools)


# ---------------------------------------------------------------------------
# FATIGUE / ENDURANCE LINES
# ---------------------------------------------------------------------------

FATIGUE_LINES = [
    "{warrior}'s desire to win may not be enough",
    "{warrior} is visibly tiring",
    "{warrior} slows noticeably",
    "{warrior}'s movements are heavy with exhaustion",
]

EXHAUSTED_LINES = [
    "{warrior} is fighting with pure will power!",
    "{warrior} staggers forward on empty reserves!",
    "{warrior} can barely lift {his} weapon!",
    "{warrior} is running on fumes!",
]

SECOND_WIND_LINES = [
    "{warrior} breathes through the pain, letting technique carry {him}",
    "{warrior} strips away the noise as every motion becomes deliberate and nothing is wasted.",
    "{warrior} slows {his} breathing, drawing on hard-won discipline",
    "{warrior} narrows to pure fundamentals as the body screams to stop",
]

ENDURANCE_DRAIN_LINES = [
    "{warrior} drains the fight out of {foe}",
    "{warrior}'s patient style wears on {foe}",
    "{warrior}'s relentless pressure tires {foe}",
]


def fatigue_line(warrior_name: str, gender: str, very_tired: bool = False,
                 is_aggressive: bool = True) -> str:
    pronoun_his = "his" if gender == "Male" else "her"
    pronoun_him = "him" if gender == "Male" else "her"
    if very_tired:
        pool = EXHAUSTED_LINES if is_aggressive else SECOND_WIND_LINES
    else:
        pool = FATIGUE_LINES
    return random.choice(pool).format(
        warrior=warrior_name.upper(), his=pronoun_his, him=pronoun_him
    )


# ---------------------------------------------------------------------------
# CRITICAL HIT / CRITICAL DEFENSE NARRATIVE
# ---------------------------------------------------------------------------

_WEAPON_DAMAGE_TYPES: dict[str, str] = {
    # Piercing
    "stiletto": "piercing", "knife": "piercing", "dagger": "piercing",
    "epee": "piercing", "short_spear": "piercing", "boar_spear": "piercing",
    "long_spear": "piercing", "trident": "piercing", "javelin": "piercing",
    "small_pick": "piercing", "military_pick": "piercing", "pick_axe": "piercing",
    "great_pick": "piercing",
    # Slashing
    "short_sword": "slashing", "scimitar": "slashing", "longsword": "slashing",
    "broad_sword": "slashing", "bastard_sword": "slashing", "great_sword": "slashing",
    "hatchet": "slashing", "francisca": "slashing", "battle_axe": "slashing",
    "great_axe": "slashing", "pole_axe": "slashing", "halberd": "slashing",
    "scythe": "slashing", "bladed_flail": "slashing", "heavy_whip": "slashing",
    "swordbreaker": "slashing",
    # Crushing
    "hammer": "crushing", "mace": "crushing", "morningstar": "crushing",
    "war_hammer": "crushing", "maul": "crushing", "club": "crushing",
    "quarterstaff": "crushing", "great_staff": "crushing",
    "flail": "crushing", "war_flail": "crushing", "battle_flail": "crushing",
    "ball_and_chain": "crushing", "cestus": "crushing", "open_hand": "crushing",
    "buckler": "crushing", "target_shield": "crushing", "tower_shield": "crushing",
    "net": "crushing", "bola": "crushing",
}


def get_damage_type(weapon_skill_key: str) -> str:
    """Return 'slashing', 'piercing', or 'crushing' for a weapon skill key."""
    return _WEAPON_DAMAGE_TYPES.get(weapon_skill_key.lower(), "crushing")


CRITICAL_HIT_SLASHING = [
    "{attacker}'s {weapon} catches an opening in {defender}'s guard and drives through, opening a deep cut that changes the fight instantly.",
    "With a fluid change of angle, {attacker} pulls the blade across {defender}'s torso in a precise draw cut that opens a wound that won't close easily.",
    "{attacker} finds the gap between {defender}'s armor plates and commits fully as the edge bites deep past leather, cloth, and flesh.",
    "The attack looks ordinary until the final moment, when {attacker} hooks the blade and opens a jagged line across {defender}'s ribs.",
    "{attacker} lands a controlled slash at the exact juncture of armor and skin, opening the kind of cut that changes the math of a fight.",
    "{attacker}'s {weapon} describes a clean arc and catches {defender} exactly wrong, landing a blow driven home with everything behind it.",
    "{attacker} reads the stance perfectly and strikes into the step, the blade finding the crease at {defender}'s side with ugly precision.",
]

CRITICAL_HIT_PIERCING = [
    "{attacker}'s {weapon} threads through {defender}'s defense with a patience that looks almost gentle, suddenly burying itself somewhere vital.",
    "A blindingly fast thrust from {attacker} catches {defender} in transition, the point driving home before the defense can close.",
    "{attacker} turns the weapon at the last instant, threading the point past iron and bone to find something soft and critical inside {defender}'s guard.",
    "{attacker}'s attack looks like a probe until it isn't, and {his_her} {weapon} sinks to striking depth before {defender} can react.",
    "{attacker} waits for the gap, driving the point through a vital junction with mechanical precision.",
    "One perfectly timed thrust from {attacker} catches {defender} at the worst possible moment, the point driving home into a critical area.",
    "{attacker} moves the weapon on a line that looks impossible until it arrives, threading through the guard to find the soft tissue beyond.",
]

CRITICAL_HIT_CRUSHING = [
    "{attacker}'s {weapon} arrives with the force of total commitment, causing {defender}'s attempt to block to fail completely as the blow lands with structural finality.",
    "The strike from {attacker} arrives at a spot {defender}'s defense simply didn't cover, carrying momentum enough that the impact reverberates across the pit.",
    "{attacker} strikes from an angle {defender}'s guard can't absorb, landing flush to a collective wince from the crowd.",
    "An overhead from {attacker} crashes through {defender}'s raised guard with enough force to make {defender}'s knees shake",
    "{attacker}'s {weapon} finds {defender} fully extended and off-balance, the crushing impact landing at the worst possible moment.",
    "The blow is textbook in its execution: {attacker} drops the weapon into a gap {defender} couldn't close in time, and it lands with bone-rattling finality.",
    "{attacker}'s {weapon} hammers into {defender} with full commitment, shattering both guard and grit under the sheer weight of the strike.",
]

CRITICAL_HIT_LINES: dict[str, list[str]] = {
    "slashing": CRITICAL_HIT_SLASHING,
    "piercing": CRITICAL_HIT_PIERCING,
    "crushing": CRITICAL_HIT_CRUSHING,
}

CRITICAL_PARRY_LINES = [
    "{defender} catches {attacker}'s strike at the perfect angle and redirects it completely. The precise parry draws an immediate murmur from the crowd.",
    "With something approaching artistry, {defender} meets the blow dead-center, folding it harmlessly aside with textbook form under the worst conditions.",
    "{defender} deflects the incoming strike with effortless grace, turning a moment of pure desperation into a showcase of perfect muscle memory..",
    "The parry from {defender} is unhurried and exact, catching the incoming blow and neutralizing it with minimal effort.",
    "{defender} reads {attacker}'s angle a breath early, setting up a counter that rings out sharp and clean as the attack finds nothing.",
    "{defender} turns the blow aside with a contemptuous parry, already poised for the next step.",
]

CRITICAL_DODGE_LINES = [
    "{defender} is no longer where the blow lands, an effortless movement where timing is everything.",
    "The attack passes through space that {defender} vacated a half-second earlier, the move so clean the crowd takes a moment to register it.",
    "{defender} smoothly steps off the line of attack without a hint of panic, letting the blow sail harmlessly past.",
    "An impossible read: {defender} begins moving before {attacker}'s commitment is visible, leaving the attack with nothing to find.",
    "{defender} slips the blow with unhurried economy that looks like instinct and takes years to learn.",
    "Not a dodge so much as an erasure -{defender} is simply not where {attacker} aimed, and there's nothing lucky about it.",
]

CRITICAL_DISARM_LINES = [
    "The parry catches {attacker}'s {weapon} at exactly the wrong angle. {defender} twists on contact, and the weapon wrenches free, spinning into the sand!",
    "{defender} redirects the blow and seizes the leverage immediately, a sharp rotation sending {attacker}'s {weapon} tumbling from the grip, and the crowd erupts!",
    "The parry traps the blade and {defender} presses home. {attacker}'s {weapon} flies free with a sound like a broken lock, and the pit falls momentarily silent.",
]

CRITICAL_BREAK_LINES = [
    "{attacker}'s {weapon} meets a perfectly braced parry and something in the metal gives. A crack, then another, and the weapon fails completely.",
    "The {weapon} shatters against {defender}'s guard with a deafening crack that silences the crowd, sending sharp fragments raining down onto the sand.",
    "The flawless parry shatters {attacker}'s {weapon} entirely, shocking the crowd into a brief silence before a massive roar breaks out.",
]

CRITICAL_DOUBLE_COUNTER_LINES = [
    "{defender} flows out of the dodge directly into the attack. Two strikes, no pause, moving like water downhill.",
    "{defender} slips the blow and drives inside the guard, answering instantly with a fluid double-strike.",
    "Slipping the blow opens something and {defender} takes it immediately, one motion into another, two swift strikes before the window closes.",
]


def critical_hit_line(attacker_name: str, attacker_gender: str,
                      defender_name: str, weapon_name: str,
                      damage_type: str) -> str:
    his     = "his"     if attacker_gender == "Male" else "her"
    his_her = his
    he      = "he"      if attacker_gender == "Male" else "she"
    him     = "him"     if attacker_gender == "Male" else "her"
    himself = "himself" if attacker_gender == "Male" else "herself"
    pool = CRITICAL_HIT_LINES.get(damage_type, CRITICAL_HIT_CRUSHING)
    return random.choice(pool).format(
        attacker=attacker_name.upper(), defender=defender_name.upper(),
        weapon=weapon_name, his=his, his_her=his_her, he=he, him=him, himself=himself,
    )


def critical_parry_line(defender_name: str, attacker_name: str) -> str:
    return random.choice(CRITICAL_PARRY_LINES).format(
        defender=defender_name.upper(), attacker=attacker_name.upper(),
    )


def critical_dodge_line(defender_name: str, attacker_name: str) -> str:
    return random.choice(CRITICAL_DODGE_LINES).format(
        defender=defender_name.upper(), attacker=attacker_name.upper(),
    )


def critical_disarm_line(defender_name: str, attacker_name: str, weapon_name: str) -> str:
    return random.choice(CRITICAL_DISARM_LINES).format(
        defender=defender_name.upper(), attacker=attacker_name.upper(),
        weapon=weapon_name,
    )


def critical_break_line(defender_name: str, attacker_name: str, weapon_name: str) -> str:
    return random.choice(CRITICAL_BREAK_LINES).format(
        defender=defender_name.upper(), attacker=attacker_name.upper(),
        weapon=weapon_name,
    )


def critical_double_counter_line(defender_name: str, attacker_name: str) -> str:
    return random.choice(CRITICAL_DOUBLE_COUNTER_LINES).format(
        defender=defender_name.upper(), attacker=attacker_name.upper(),
    )


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
    "{warrior} has perished in the AGONY AMPHITHEATRE!!!",
    "{warrior} breathes {his} last on the arena floor!!!",
    "{warrior} is dead. The crowd erupts!!!",
    "{warrior} falls, never to rise again!!!",
    "Blood stains the sand as {warrior} is broken and destroyed before the roaring crowd!!!",
    "A brutal end! {warrior} is slaughtered where {he} stands, sending the stands into a frenzy!!!",
    "With a final, sickening impact, {warrior} falls still, never to leave the pit alive!!!",
    "{warrior} meets a gruesome demise, leaving nothing but a crimson ruin on the arena floor!!!",
    "{warrior} collapses hard into the dirt, a mangled and lifeless ruin as the crowd goes wild!!!",
    "A final, devastating strike tears through {warrior}, who crashes down and moves no more!!!",
    "The sickening crunch of shattered bone marks the end of {warrior}, dead before {he} hits the sand!!!",
    "{warrior} is utterly butchered in a flash of cold steel, painting the pit with a final splash of red!!!",
    "With a violent gasp, {warrior} is broken apart by the lethal blow and drops like stone into the dust!!!",
    "The savage attack tears the remaining life from {warrior}, leaving a bloody, motionless shell on the floor!!!",
    "A horrific finishing blow splits {warrior}'s guard and ends {his} life in a sudden, crimson spray!!!",
    "{warrior} takes a catastrophic impact directly to the vitals and slumps to the earth, entirely spent and destroyed!!!",
]

ELF_DUAL_STRIKE_LINES = [
    "{attacker} draws upon {his} inherent Elvish heritage and brings {his} {secondary} across in a lightning quick follow-up!",
    "{attacker}'s grace becomes evident as {secondary_subject} flashes forth with supernatural speed!",
    "With movements too quick to follow, {attacker} spins and launches {his} {secondary} at {defender}!",
    "{attacker}'s {secondary} whips around in a blur of motion, targeting {defender} once more!",
    "The Elf's natural dexterity shines as {secondary_subject} darts forward with deadly speed!",
    "{attacker} pivots fluidly and swings {his} {secondary} in a rapid follow-up!",
    "In a display of dual-blade mastery, {attacker} brings {his} {secondary} around for another attack!",
    "{attacker}'s {secondary} glints in the light as {subject} presses the advantage with uncanny speed!",
    "Moving with elvish fluidity, {attacker} spots an opening and {secondary_subject} lunges forward!",
]

HALFLING_MARTIAL_STRIKE_LINES = [
    "{attacker} darts in with a flurry of rapid strikes, exploiting openings with preternatural quickness!",
    "In a blur of motion, {attacker} weaves and launches another attack, fists moving faster than the eye can follow!",
    "{attacker} presses the advantage with a barrage of nimble punches and kicks!",
    "Quick as lightning, {attacker} spots an opening and throws another strike at {defender}!",
    "{attacker} flows from one strike to another, a whirlwind of precise martial technique!",
    "With halfling speed and grace, {attacker} unleashes a follow-up strike before {defender} can react!",
    "{attacker} dances around {defender} and drives another fist forward with deadly intent!",
    "In a display of halfling martial prowess, {attacker} chains strikes together with fluid precision!",
]

LIZARDFOLK_MARTIAL_STRIKE_LINES = [
    "{attacker} lashes out with primal fury, launching a second devastating strike at {defender}!",
    "Instinct takes over as {attacker} follows with a vicious counterattack, tail whipping around!",
    "{attacker}'s natural reflexes drive another ferocious strike, pure power behind it!",
    "Driven by inhuman speed, {attacker} unleashes another blow before {defender} can recover!",
    "{attacker} roars and presses forward, claws slashing toward {defender} in a relentless assault!",
    "With the grace of a natural predator, {attacker} surges forward again, movements efficient and deadly!",
    "{attacker} demonstrates the lethal martial prowess of the Lizardfolk, striking in quick succession!",
    "Battle instinct guides {attacker} as {subject_pronoun} unleashes another ferocious attack!",
]

TABAXI_FRENZY_INTRO_LINES = [
    "Backed into a corner, {attacker} unleashes primal fury in a savage assault!",
    "{attacker} moves with impossible speed, claws flashing in a desperate barrage!",
    "Instinct takes over, and {attacker} becomes a whirlwind of claws and desperation!",
    "{attacker}'s survival instinct awakens as {he} lashes out with ferocious precision!",
    "{attacker}'s natural predator instincts ignite, driving a vicious flurry of strikes!",
    "Eyes ablaze with feline rage, {attacker} unleashes a devastating combination!",
    "{attacker} moves like a creature possessed, delivering a blur of attacks!",
    "Like a cornered hunter striking back, {attacker} bursts forward in a frenzied assault!",
]

# Per-attack lines within the frenzy burst - one emitted before each of the 3 strikes.
# Conveys escalating speed/pressure; keyed by attack_num (0, 1, 2).
TABAXI_FRENZY_STRIKE_LINES = {
    0: [
        "{attacker} explodes forward with the first strike!",
        "{attacker} launches the opening blow!",
        "{attacker} drives in with a lightning-fast first attack!",
        "{attacker} opens with a savage burst!",
    ],
    1: [
        "Before the opponent can recover, {attacker} strikes again!",
        "{attacker} follows immediately with a second assault!",
        "With dizzying speed, {attacker} launches straight into another attack!",
        "{attacker} presses without pause, the second blow already in motion!",
    ],
    2: [
        "{attacker} completes the barrage with a final desperate strike!",
        "With a third and final blow, {attacker} throws everything into the attack!",
        "{attacker} hammers home the last attack of the frenzy!",
        "The frenzy peaks as {attacker} throws everything into one last strike!",
    ],
}

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
    his     = "his"     if gender == "Male" else "her"
    he      = "he"      if gender == "Male" else "she"
    him     = "him"     if gender == "Male" else "her"
    himself = "himself" if gender == "Male" else "herself"
    return random.choice(DEATH_LINES).format(
        warrior=warrior_name.upper(), his=his, he=he, him=him, himself=himself
    )


def race_kill_line(killer_name: str, race_name: str, gender: str) -> str:
    """Return a race-specific narrative line for a kill."""
    pool = RACE_KILL_POOLS.get(race_name, RACE_KILL_POOLS["Human"])
    template = random.choice(pool)
    his = "his" if gender == "Male" else "her"
    he = "he" if gender == "Male" else "she"
    him = "him" if gender == "Male" else "her"
    himself = "himself" if gender == "Male" else "herself"

    return template.format(
        name=killer_name.upper(),
        his=his, he=he, him=him, himself=himself
    )


def victory_line(winner_name: str, loser_name: str) -> str:
    return random.choice(VICTORY_LINES).format(
        winner=winner_name.upper(), loser=loser_name.upper()
    )


def elf_dual_strike_line(attacker_name: str, defender_name: str, secondary_weapon: str,
                         gender: str, off_hand: bool = False) -> str:
    """Generate narrative for an Elf's extra attack from dual-wielding.
    off_hand=True prefixes the weapon name with 'off-hand' so same-weapon pairings
    (e.g. short sword + short sword) are clearly distinguishable in the narrative.
    """
    pronoun = "his" if gender == "Male" else "her"
    subject = "he" if gender == "Male" else "she"
    label = f"off-hand {secondary_weapon.lower()}" if off_hand else secondary_weapon.lower()
    weapon_as_subject = f"{pronoun} {label}" if off_hand else label
    secondary_subject = f"{subject} swiftly" if random.random() < 0.5 else weapon_as_subject

    return random.choice(ELF_DUAL_STRIKE_LINES).format(
        attacker=attacker_name.upper(),
        defender=defender_name.upper(),
        his=pronoun,
        secondary=label,
        subject=subject,
        secondary_subject=secondary_subject,
    )


def halfling_martial_strike_line(attacker_name: str, defender_name: str, gender: str) -> str:
    """Generate narrative for a Halfling's extra martial combat attack."""
    pronoun = "his" if gender == "Male" else "her"
    return random.choice(HALFLING_MARTIAL_STRIKE_LINES).format(
        attacker=attacker_name.upper(),
        defender=defender_name.upper(),
        his=pronoun,
    )


def lizardfolk_martial_strike_line(attacker_name: str, defender_name: str, gender: str) -> str:
    """Generate narrative for a Lizardfolk's extra martial combat attack."""
    pronoun = "his" if gender == "Male" else "her"
    subject_pronoun = "he" if gender == "Male" else "she"
    return random.choice(LIZARDFOLK_MARTIAL_STRIKE_LINES).format(
        attacker=attacker_name.upper(),
        defender=defender_name.upper(),
        his=pronoun,
        subject_pronoun=subject_pronoun,
    )


TABAXI_FRENZY_RESIST_LINES = [
    "{attacker} strains at the edge of frenzy, but the surge passes without breaking loose.",
    "The primal fire flickers in {attacker}'s eyes, then gutters out.",
    "{attacker} feels the instinct surge and falter. The moment slips away.",
    "A tremor of frenzy moves through {attacker}, but discipline holds it in check.",
    "{attacker} tenses, on the brink. The killing rush does not come.",
]


def tabaxi_frenzy_intro_line(attacker_name: str, gender: str = "Male") -> str:
    """Generate narrative for the opening of a Tabaxi frenzy ability."""
    he = "he" if gender == "Male" else "she"
    return random.choice(TABAXI_FRENZY_INTRO_LINES).format(
        attacker=attacker_name.upper(),
        he=he,
    )


def tabaxi_frenzy_strike_line(attacker_name: str, attack_num: int) -> str:
    """Generate the per-attack setup line for one of the 3 frenzy strikes (attack_num 0/1/2)."""
    pool = TABAXI_FRENZY_STRIKE_LINES.get(attack_num, TABAXI_FRENZY_STRIKE_LINES[2])
    return random.choice(pool).format(attacker=attacker_name.upper())


def tabaxi_frenzy_resist_line(attacker_name: str) -> str:
    """Generate narrative for a failed Tabaxi frenzy trigger roll."""
    return random.choice(TABAXI_FRENZY_RESIST_LINES).format(
        attacker=attacker_name.upper(),
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
# LIZARDFOLK HEAVY ARMOR PENALTY FLAVOR
# ---------------------------------------------------------------------------

_LIZARD_ARMOR_LINES: dict[str, dict[str, list[str]]] = {
    "Cuir Boulli": {
        "defensive": [
            "{warrior}'s scales bunch under the hardened leather, slowing their parry just enough to matter.",
            "The stiff cuirass limits {warrior}'s reach and that dodge came a half-step late.",
            "{warrior}'s reflexes are there. The armor just isn't letting them use them.",
        ],
        "offensive": [
            "{warrior} struggles to rotate into the strike fully, the boiled leather binding at the shoulder.",
            "The armor fights {warrior}'s natural movement and their attack carries less snap than it should.",
            "The boiled leather binds at the elbow, costing {warrior} the follow-through on that swing.",
        ],
    },
    "Brigandine": {
        "defensive": [
            "The brigandine's bulk costs {warrior} a clean parry. Their arm couldn't extend in time.",
            "{warrior} telegraphs the dodge; the added weight is eating into their reaction speed.",
            "That parry was a half-measure. {warrior} couldn't square up fast enough in the heavy coat.",
        ],
        "offensive": [
            "The coat slows {warrior}'s weapon recovery and they're resetting a beat slower than their opponent.",
            "{warrior} can't get their body fully behind the attack; the brigandine is killing their rotation.",
            "{warrior}'s swing arrives a beat late; the brigandine has killed the timing.",
        ],
    },
    "Scale": {
        "defensive": [
            "{warrior} pulls a dodge that would have worked in lighter gear. In scale, it's not enough.",
            "The weight is showing and {warrior}'s parries are reactive now rather than decisive.",
            "The scale hauberk robs {warrior} of the half-step they needed to get clear.",
        ],
        "offensive": [
            "The scale hauberk is dragging {warrior}'s attack rate down. They simply can't move their arms freely.",
            "{warrior}'s counterattack comes in slow; the scale is grinding against their natural movement.",
            "The armor is robbing {warrior} of the speed their body is built for.",
        ],
    },
    "Chain": {
        "defensive": [
            "{warrior} throws a parry but can't commit; the chainmail is dragging the arm back.",
            "The dodge is there in instinct. The mail ensures it doesn't happen in time.",
            "{warrior} tries to slip the strike. The mail kills it before the footwork can.",
        ],
        "offensive": [
            "{warrior}'s attack rate has dropped noticeably under the chain's weight.",
            "The chain restricts {warrior}'s follow-through; the blow lands but without real force behind it.",
            "{warrior}'s strike telegraphs badly; the chain has robbed the movement of its deception.",
        ],
    },
    "Half-Plate": {
        "defensive": [
            "{warrior} can barely raise a parry in time. The plate is winning the fight against their arms.",
            "The half-plate has stripped out most of {warrior}'s evasion and they're eating hits they'd normally walk away from.",
            "Any attempt to dodge is mostly ceremonial at this point; the armor has other ideas.",
        ],
        "offensive": [
            "{warrior}'s attack comes in high and stiff. The plate is dictating the angle, not {warrior}.",
            "{warrior}'s attack rhythm has slowed to a crawl under the half-plate.",
            "The half-plate has reduced {warrior}'s swing to a predictable arc; there's no surprise left in it.",
        ],
    },
    "Full Plate": {
        "defensive": [
            "{warrior} is barely parrying at all. The plate has locked their arms into a narrow range of motion.",
            "The dodge attempt was almost impressive given the circumstances. It did not work.",
            "The full plate has left {warrior} with nothing meaningful on defense; they are simply absorbing damage now.",
        ],
        "offensive": [
            "{warrior} swings from the shoulder because the plate won't let them use the wrist and the attack telegraphs badly.",
            "{warrior}'s attack is late. The armor is running this fight, not them.",
            "The full plate has turned {warrior}'s strikes into slow, obvious arcs that any alert fighter can read.",
        ],
    },
}

_LIZARD_HEAVY_ARMORS = {"Cuir Boulli", "Brigandine", "Scale", "Chain", "Half-Plate", "Full Plate"}


def lizard_armor_line(warrior_name: str, armor_name: str, defensive: bool = True) -> Optional[str]:
    """Return a Lizardfolk heavy-armor flavor line. defensive=True for parry/dodge failures, False for attack failures."""
    tier = _LIZARD_ARMOR_LINES.get(armor_name)
    if not tier:
        return None
    pool = tier["defensive"] if defensive else tier["offensive"]
    return random.choice(pool).format(warrior=warrior_name.upper())

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

    if observed and not is_opponent:
        # Only show observed skills to the warrior's own manager
        for obs_skill in observed:
            lines.append(
                f"{warrior_name.upper()} observed and learned a {obs_skill} skill"
                f" from their opponent"
            )

    return "\n".join(lines)
