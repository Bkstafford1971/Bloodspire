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
import re
from typing import Optional
from warrior import Warrior, compare_stats
from weapons import get_weapon

LINE_WIDTH = 76   # Total width of fight output


def _safe_format(template: str, **kwargs) -> str:
    """Safely format a template string, providing defaults for missing pronouns."""
    # Provide safe defaults for all pronouns
    defaults = {
        'his': 'his',
        'her': 'her',
        'he': 'he',
        'she': 'she',
        'him': 'him',
        'himself': 'himself',
        'herself': 'herself',
    }
    # Merge provided kwargs with defaults, with kwargs taking precedence
    format_args = {**defaults, **kwargs}
    return template.format(**format_args)


def _article(word: str) -> str:
    """Return 'an' if word starts with a vowel sound, otherwise 'a'."""
    return "an" if word and word[0].upper() in "AEIOU" else "a"


# ---------------------------------------------------------------------------
# ANTI-REPETITION LINE PICKER
# ---------------------------------------------------------------------------
# Flavor pools (miss, parry, dodge, hit announcements, etc.) are drawn from
# with plain _pool_choice() dozens of times per fight. With no memory of
# recent picks, the same line can and does show up repeatedly - sometimes
# back to back - which reads as robotic even with 20+ item pools.
#
# _pool_choice() keeps a small per-pool "recently used" ring, keyed by the
# id() of the pool list itself (so no pool needs a name/key threaded through
# every call site). It avoids re-serving the last few picks from a pool
# unless the pool is too small to support that, in which case it falls back
# to plain random choice for that pool.
#
# reset_narrative_history() clears this state and must be called once per
# fight (from Fight.__init__ in combat.py) so variety resets between fights
# instead of a long tournament run slowly starving every pool.

_RECENT_PICKS: dict[int, list[int]] = {}
_RECENT_HISTORY_SIZE = 3  # how many past picks per pool to avoid repeating


def reset_narrative_history() -> None:
    """Clear anti-repetition tracking. Call once at the start of each fight."""
    _RECENT_PICKS.clear()


def _pool_choice(pool: list):
    """Like random.choice(pool), but avoids repeating the last few picks
    from this exact pool when the pool is large enough to allow it."""
    n = len(pool)
    if n <= _RECENT_HISTORY_SIZE:
        # Pool too small to meaningfully avoid repeats - just pick.
        return random.choice(pool)

    key = id(pool)
    recent = _RECENT_PICKS.get(key, [])
    choices = [i for i in range(n) if i not in recent]
    if not choices:
        # Shouldn't happen given the size guard above, but stay safe.
        choices = list(range(n))

    idx = random.choice(choices)

    recent.append(idx)
    if len(recent) > _RECENT_HISTORY_SIZE:
        recent.pop(0)
    _RECENT_PICKS[key] = recent

    return pool[idx]


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
        return _pool_choice(shield_desc)
    
    # Small daggers and knives - ALWAYS at hip/waist/belt, NEVER on back
    if contains("dagger") or contains("knife") or contains("stiletto"):
        small_blade_desc = [
            f"has {_article(wpn_display)} {wpn_display} sheathed at {pronoun} hip",
            f"carries {_article(wpn_display)} {wpn_display} tucked into {pronoun} belt",
            f"has {_article(wpn_display)} {wpn_display} at {pronoun} waist",
        ]
        return _pool_choice(small_blade_desc)
    
    # Polearms and spears - carried upright or across back
    if category == "Polearm/Spear" or contains("spear") or contains("pike") or contains("lance"):
        polearm_desc = [
            f"has {_article(wpn_display)} {wpn_display} strapped to {pronoun} back",
            f"carries {_article(wpn_display)} {wpn_display} planted at {pronoun} side",
            f"has {_article(wpn_display)} {wpn_display} leaning against {pronoun} shoulder",
        ]
        return _pool_choice(polearm_desc)
    
    # Short swords and medium blades - hip or side, not back
    if contains("short") and contains("sword"):
        short_sword_desc = [
            f"has {_article(wpn_display)} {wpn_display} sheathed at {pronoun} hip",
            f"wears {_article(wpn_display)} {wpn_display} at {pronoun} side",
            f"carries {_article(wpn_display)} {wpn_display} on {pronoun} hip",
        ]
        return _pool_choice(short_sword_desc)
    
    # Large two-handed swords - must be on back
    if is_two_hand and contains("sword"):
        large_sword_desc = [
            f"has {_article(wpn_display)} {wpn_display} strapped across {pronoun} back",
            f"wears {_article(wpn_display)} {wpn_display} slung across {pronoun} back",
            f"carries {_article(wpn_display)} {wpn_display} lashed to {pronoun} back",
        ]
        return _pool_choice(large_sword_desc)
    
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
        return _pool_choice(medium_sword_desc)
    
    # Maces, hammers, clubs - belt loop or back
    if contains("mace") or contains("hammer") or contains("club") or contains("flail"):
        blunt_desc = [
            f"has {_article(wpn_display)} {wpn_display} hanging from {pronoun} belt",
            f"carries {_article(wpn_display)} {wpn_display} looped at {pronoun} hip",
            f"has {_article(wpn_display)} {wpn_display} strapped to {pronoun} back",
        ]
        return _pool_choice(blunt_desc)
    
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
        return _pool_choice(axe_desc)
    
    # Two-handed weapons (catch-all) - strapped/slung across back
    if is_two_hand:
        heavy_desc = [
            f"has {_article(wpn_display)} {wpn_display} strapped to {pronoun} back",
            f"carries {_article(wpn_display)} {wpn_display} slung across {pronoun} back",
            f"wears {_article(wpn_display)} {wpn_display} lashed to {pronoun} back",
        ]
        return _pool_choice(heavy_desc)
    
    # Throwable weapons - quiver, bundle, or bandolier
    if is_throwable:
        throw_desc = [
            f"has {_article(wpn_display)} {wpn_display} at {pronoun} side",
            f"carries {_article(wpn_display)} {wpn_display} secured at {pronoun} hip",
            f"has {_article(wpn_display)} {wpn_display} tucked in {pronoun} belt",
        ]
        return _pool_choice(throw_desc)
    
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
    return _pool_choice(default_desc)

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


def _strategy_table(w: Warrior, strats=None, is_challenge_strat: bool = False) -> list:
    """Return the strategy table lines for the player warrior.

    strats: the actual strategy list being used in this fight (challenge or
            regular). Falls back to w.strategies when not provided.
    is_challenge_strat: True when challenge_strategies are being used (vs regular).
    """
    strategies = strats if strats is not None else w.strategies
    if not strategies:
        return []
    strat_label = " (CHALLENGE STRATEGY)" if is_challenge_strat else ""
    hdr = f"{'TRIGGER':<42}{'FIGHTING STYLE':<20}{'LEVEL':>5}  {'AIMING POINT':<16}{'DEFENSE POINT'}"
    sep = "-" * len(hdr)
    lines = ["", f"STRATEGY TABLE{strat_label}", hdr, sep]
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

    # Player strategy table, use the actual strategies for this fight
    # (challenge strategies when challenge mode is active, otherwise regular).
    # Detect which set is in use by comparing identity to warrior_a.strategies.
    _using_challenge_strats = (
        strats_a is not None and
        strats_a is not warrior_a.strategies and
        bool(getattr(warrior_a, 'challenge_strategies', None)) and
        strats_a is getattr(warrior_a, 'challenge_strategies', None)
    )
    lines.extend(_strategy_table(warrior_a, strats_a, is_challenge_strat=_using_challenge_strats))

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
    "{n1} demands a price in blood from {n2}. A Blood Challenge!!",
    "The air turns cold as {n1} declares a Blood Challenge against {n2}!!",
    "{n1} swears a Blood Challenge vendetta against {n2} this turn!",
]

_CHALLENGE_FLAVOR_BLOOD_BULLY = [
    "{n1} declares a Blood Challenge against {n2}, and the crowd doesn't hide its disgust at the mismatch.",
    "{n1} sets their sights on {n2} for a Blood Challenge, and a chorus of boos rains down at the sight of it.",
    "{n1} singles out {n2} for a Blood Challenge, an opponent they could've beaten with one hand tied behind their back. The stands are not impressed.",
    "{n1} calls out {n2} for a Blood Challenge, and the crowd hisses. Some victories aren't worth the shame that comes with them.",
    "{n1} targets {n2} with a Blood Challenge, and a wave of jeers washes over the arena. This isn't vengeance, it's a slaughter waiting to happen.",
    "{n1} hunts down {n2} for a Blood Challenge, and murmurs of contempt ripple through the crowd at such an uneven match.",
    "{n1} picks {n2} for a Blood Challenge, and somewhere in the stands, someone starts a slow, mocking clap.",
    "{n1} goes after {n2} in a Blood Challenge, and the crowd grows cold. There's no glory in this kind of vengeance.",
]

_CHALLENGE_FLAVOR_BLOOD_UNDERDOG = [
    "{n1} steps up to declare a Blood Challenge against {n2}, hopelessly outmatched, and the crowd roars in support anyway.",
    "{n1} throws down a Blood Challenge against {n2}, a fighter far stronger on paper. The arena erupts, because everyone loves an underdog.",
    "{n1} dares to challenge {n2} to a Blood Challenge, and the crowd is already chanting their name before the first blow is struck.",
    "{n1} answers the call and challenges {n2}, a far more dangerous foe, to a Blood Challenge, and the stands come alive. Heart over odds, and the crowd can't get enough.",
    "{n1} musters the courage to challenge the clearly superior {n2} to a Blood Challenge, and the arena rises to its feet in respect.",
    "{n1} declares a Blood Challenge against {n2}, odds be damned, and the crowd is behind them every step of the way.",
    "{n1} takes the leap and challenges {n2}, a fighter well beyond their standing, to a Blood Challenge. Whatever happens next, the crowd already calls them brave.",
    "{n1} declares a Blood Challenge against {n2}. Few expect them to survive it, but fewer still will forget the courage it took to accept it.",
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
    "A Title Challenge! {n1} steps up to dethrone champion {n2}!!",
    "{n1} issues a Title Challenge to the champion {n2}!!",
    "{n1} will attempt to claim the Title from {n2}!!",
    "{n1} steps into the arena for a Title Challenge against {n2}!!",
]

def get_challenge_flavor_line(w1_name: str, w2_name: str, challenger_name: Optional[str], fight_type: str,
                               bully_zone: Optional[str] = None) -> Optional[str]:
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
        if bully_zone in ("mismatch", "severe"):
            pool = _CHALLENGE_FLAVOR_BLOOD_BULLY
        elif bully_zone == "underdog":
            pool = _CHALLENGE_FLAVOR_BLOOD_UNDERDOG
        else:
            pool = _CHALLENGE_FLAVOR_BLOOD
    elif fight_type == "monster":
        pool = _CHALLENGE_FLAVOR_MONSTER
    elif fight_type == "champion":
        pool = _CHALLENGE_FLAVOR_CHAMPION
    else:
        pool = _CHALLENGE_FLAVOR_NORMAL

    return _pool_choice(pool).format(n1=n1, n2=n2)


_SCOUT_FLAVOR_SINGLE = [
    "There is a scout from {mgr}'s stable in attendance today.",
    "{mgr} has sent a scout to watch today's duel.",
    "A scout representing {mgr} has taken a seat in the stands.",
    "Word has it {mgr} has an eye on this match, watching from the crowd.",
    "{mgr}'s scout has arrived to observe today's bout.",
    "A representative from {mgr}'s camp is here to take notes on this fight.",
    "{mgr} has quietly dispatched a scout to size up today's combatants.",
    "One of {mgr}'s scouts is watching closely from the stands.",
    "A scout in {mgr}'s colors can be seen observing the arena today.",
    "{mgr} wanted eyes on this fight, and a scout has been sent to provide them.",
    "{mgr}'s representative sits silently, documenting every move.",
    "A keen-eyed scout from {mgr}'s organization watches intently.",
    "{mgr} didn't come themselves, but their watcher is here.",
    "A scout in {mgr}'s employ meticulously observes the arena floor.",
    "{mgr} has a vested interest in today's outcome, judging by the scout watching.",
    "One of {mgr}'s trusted scouts takes careful note of the action.",
    "{mgr}'s intelligence network has another pair of eyes on the arena today.",
    "A scout sent by {mgr} sits forward, missing nothing.",
    "{mgr} is studying today's match through their representative.",
    "A single scout representing {mgr}'s interests watches with calculated attention.",
]

_SCOUT_FLAVOR_MULTI = [
    "There are several scouts in attendance for this match today.",
    "More than one set of watchful eyes has turned out for today's bout.",
    "Word of this match has drawn a handful of scouts to the stands.",
    "Several rival camps have sent scouts to observe today's fighters.",
    "The stands hold more than a few interested observers today.",
    "This fight has attracted the attention of multiple scouting parties.",
    "A cluster of scouts can be seen taking notes from the crowd.",
    "Today's bout has no shortage of watchful strangers in attendance.",
    "Several scouts have turned out, each keeping their reasons to themselves.",
    "More than one manager has an interest in how this fight unfolds, and their scouts are here to see it.",
    "The arena draws many eyes today, numerous scouts watch from the stands.",
    "This match has become the subject of competitive intelligence gathering.",
    "Scouts from multiple organizations have come to assess today's combatants.",
    "The crowd includes more professional observers than casual spectators today.",
    "Word of this fight has reached enough managers to fill a section with scouts.",
    "Several rival operations have dispatched representatives to observe the action.",
    "The interest in today's bout has brought scouts from across the city.",
    "A notable crowd of watchers, each with their own agenda, monitors the fight.",
    "Today's match has drawn enough scouts to suggest something significant is at stake.",
    "Multiple competing interests have sent representatives to take measure of these warriors.",
]

def get_scout_flavor_line(scout_names: list) -> Optional[str]:
    """
    Return a randomly selected scout-attendance flavor line, or None if no
    one is scouting this fight.

    Exactly 1 scout: names the scouting manager. 2+ scouts (whether from
    the same manager watching both combatants, or different managers):
    generic line, no names - deliberately never reveals which combatant
    is the actual target.
    """
    if not scout_names:
        return None
    if len(scout_names) == 1:
        return _pool_choice(_SCOUT_FLAVOR_SINGLE).format(mgr=scout_names[0])
    return _pool_choice(_SCOUT_FLAVOR_MULTI)

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
    "The arena trembles with anticipation as the combatants enter!",
    "A deathly hush falls over the crowd as the warriors approach!",
    "The smell of blood and destiny fills the amphitheatre!",
    "Lightning crackles in the distance as the pit awaits its sacrifice!",
    "The crowd's bloodlust is palpable as the fighters take their positions!",
    "The sand shifts beneath the warriors' feet, eager for what comes next!",
    "An electric tension fills the arena as the moment arrives!",
    "The torches flare brighter as the combatants prepare for war!",
    "Time seems to slow as the fighters lock eyes across the pit!",
    "The roar of the crowd fades to an ominous silence!",
    "A cold wind sweeps through the amphitheatre, carrying the scent of battle!",
    "The arena itself seems to hold its breath before the onslaught!",
    "Destiny settles over the pit like a heavy cloak!",
    "The stage is set for glory, or oblivion!",
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
    "The warriors circle each other, seeking advantage!",
    "Weapons are raised as the distance closes between the fighters!",
    "The first tentative movements probe for weakness!",
    "Both warriors move with the precision of trained killers!",
    "The pit falls silent as the dance of death begins!",
    "Footwork and positioning are everything in these opening seconds!",
    "Steel glints as the fighters take their opening stances!",
    "The crowd holds its breath as combat is moments away!",
    "Neither warrior gives ground, both seeking the perfect angle!",
    "Tension builds as the fighters draw ever closer!",
    "The opening moments will set the tone for everything that follows!",
    "Both warriors are completely focused, reading every movement!",
    "The air crackles with the promise of violence!",
    "This is the moment before fury is unleashed!",
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
        "{name}'s nostrils flare as {he} inhales the copper scent of victory.",
        "{name} flexes massive, blood-slicked muscles, a monument to brutish conquest.",
        "{name} wipes viscera from {his} tusks with cold satisfaction.",
        "{name} plants {his} weapon into the sand, claiming this ground as conquered.",
        "{name} lets out a series of guttural, rolling laughs that echo through the amphitheatre.",
        "{name} stands astride the corpse, {his} breathing slowly returning to normal.",
        "{name}'s eyes glow with a feral, barely-contained bloodlust in the aftermath.",
        "{name} drags the back of {his} hand across {his} mouth, savoring the moment.",
        "{name} beats {his} fists together in a rhythmic, thunderous celebration.",
        "{name} tilts {his} head back and releases a howl of pure, primal triumph.",
        "{name} circles the body once, territory marked and secured by combat.",
        "{name}'s powerful frame shudders with the aftershock of violence and victory.",
        "{name} sniffs the air, the predator in {him} fully awakened and satisfied.",
        "{name} wrenches {his} weapon free, a meaty, definitive sound.",
        "{name} stands immovable over the kill, a monument to orcish strength.",
        "{name} grunts a low, satisfied sound that speaks of conquest and dominance.",
        "{name} drives a heavy boot into the corpse, a final act of brutal disrespect to the fallen.",
    ],
    "Elf": [
        "{name} lowers {his} weapon with fluid grace, offering a silent, cold nod to the fallen.",
        "{name} stands perfectly still, the only sign of the kill a subtle, chilling smile.",
        "{name} lowers {his} weapon in a blur of motion, looking already bored with the victory.",
        "{name} murmurs a short, melodic phrase in Elvish, a sharp contrast to the surrounding violence.",
        "{name} steps delicately over the body, {his} movements as precise as the strike that ended it.",
        "{name} gazes upon the corpse with a detached, clinical interest before turning away.",
        "{name} flickers {his} weapon to clear the blood, the motion so swift it's almost invisible.",
        "{name} stands like a statue over the remains, {his} eyes reflecting the setting sun with unsettling calm.",
        "{name} adjusts {his} stance with effortless elegance, the kill merely a footnote in {his} afternoon.",
        "{name} offers a mocking, graceful bow to the cheering stands, a predator's charm on full display.",
        "{name} surveys the corpse with the detached air of a master craftsman admiring finished work.",
        "{name}'s elegant posture never wavers, even in victory's most violent moments.",
        "{name} offers a subtle, knowing smile that carries centuries of accumulated skill.",
        "{name}'s weapon catches the light one final time before being lowered with precision.",
        "{name} stands with an air of inevitability, as though this outcome was preordained.",
        "{name}'s breathing remains perfectly controlled, {his} composure unshaken by the kill.",
        "{name} gazes at the fallen with an expression of mild disappointment at their inadequacy.",
        "{name} moves with such grace that even the violence seems refined and purposeful.",
        "{name}'s eyes are already drifting away from the corpse, boredom setting in.",
        "{name} adjusts {his} hair with one hand while the other still grips {his} weapon.",
        "{name} hums a soft, melodic tune from {his} ancient homeland, indifferent to the carnage.",
        "{name}'s elegant frame is unmarred by the struggle, a perfect predator after the hunt.",
        "{name} regards the body with the same cold interest one might give a fallen leaf.",
        "{name} performs a languid stretch, {his} muscles loose and ready for another round.",
        "{name}'s features remain serene, untouched by the savage reality of the arena.",
        "{name} accepts the crowd's applause with a slight, regal incline of {his} head.",
        "{name} steps on the corpse's weapon with deliberate slowness, grinding it into the sand.",
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
        "{name}'s stocky frame stands firm over the kill, rooted like mountain stone.",
        "{name} lets out a deep, satisfied belly laugh that echoes through the arena.",
        "{name} examines {his} weapon for damage with the keen eye of a master craftsman.",
        "{name} nods with the grim satisfaction of a job well done, dwarf-fashion.",
        "{name}'s beard, matted with blood and sweat, shakes with the force of {his} pride.",
        "{name} plants {his} weapon firmly in the sand beside the body, claiming the ground.",
        "{name} takes a long, deep breath, the smell of the kill settling into {his} bones.",
        "{name} stands with the unshakeable confidence of one who has faced worse and won.",
        "{name}'s weathered features break into a grim, satisfied smile of victory.",
        "{name} flexes {his} solid, powerful arms, the muscles of a lifetime of labor.",
        "{name} spits into the sand with the finality of a dwarf's judgment.",
        "{name} offers a grudging, respectful nod to the body. Debt paid in full.",
        "{name}'s eyes are bright with the primal joy of a warrior proven worthy.",
        "{name} settles {his} weight with the stability of a dwarf in {his} element.",
        "{name} lets out a long, satisfied sigh that speaks of honor upheld.",
        "{name}'s powerful hands release the grip on {his} weapon with absolute control.",
        "{name} drags the corpse across the sand with contemptuous ease, clearing the arena.",
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
        "{name}'s chest heaves with the raw adrenaline of mortal combat won.",
        "{name} stands with the quiet pride of one who has proven something to themselves.",
        "{name} looks to the crowd, seeing in their faces the reflection of {his} triumph.",
        "{name}'s hands tremble slightly from the intensity of the kill, but {his} resolve is absolute.",
        "{name} offers a silent prayer to whatever gods {he} believes in, gratitude for survival.",
        "{name} wipes blood from {his} face with the back of a shaking hand, reality setting in.",
        "{name} stands tall, knowing that this moment will define {him} in the eyes of the arena.",
        "{name}'s breathing slowly steadies, the warrior's calm returning after the storm of battle.",
        "{name} releases the tension from {his} body one muscle group at a time, methodical and controlled.",
        "{name} gazes at the corpse with the weight of a human life taken upon {his} shoulders.",
        "{name}'s heart begins to slow from its frantic pace, the kill complete and undeniable.",
        "{name} offers a nod to the fallen, a warrior's acknowledgment of a worthy opponent.",
        "{name} stands as a living monument to human resilience and martial prowess.",
        "{name}'s spirit feels both lifted and burdened by the finality of the kill.",
        "{name} takes in a long, shuddering breath, the arena suddenly very quiet.",
        "{name} raises {his} weapon high, accepting the roar of the crowd as {his} due.",
        "{name} kicks the corpse's armor aside with disgust, reclaiming the blood-soaked sand.",
    ],
    "Halfling": [
        "{name} darts a quick, mischievous look at the crowd before offering a cheeky wink.",
        "{name} stands over the much larger opponent, a look of feigned surprise on {his} youthful face.",
        "{name} wipes {his} weapon with a flourish, the kill handled with more style than seems strictly necessary.",
        "{name} hops over the corpse with a nimble skip, already looking for the next excitement.",
        "{name} lets out a high-pitched, mocking cheer that carries clearly over the roar of the fans.",
        "{name} strikes a dramatic pose over the body, {his} small frame casting a long shadow on the sand.",
        "{name} chuckles to {himself}, a light-hearted sound in the midst of the carnage.",
        "{name} offers a playful, exaggerated bow to the Blood Master, the kill a show for the people.",
        "{name} stands with hands on hips, looking down at the remains with a satisfied, cocky grin.",
        "{name} takes a quick, mocking victory lap around the body before settling into a confident stance.",
        "{name}'s small frame bounces with infectious joy at the victory.",
        "{name} does a quick, celebratory hop over the corpse, utterly carefree.",
        "{name}'s youthful grin is wider than {his} entire face, pure delight radiating outward.",
        "{name} claps {his} own hands together in a gesture of self-congratulation.",
        "{name} strikes an exaggerated heroic pose, one foot planted on the body.",
        "{name}'s laughter rings out high and clear, the sound of genuine amusement.",
        "{name} performs a little spin, {his} small form a blur of satisfaction.",
        "{name} offers a theatrical wave to the crowd, as if this outcome was never in doubt.",
        "{name} grins at the corpse as though sharing a private joke with the fallen.",
        "{name}'s nimble feet dance a quick pattern around the body, light and playful.",
        "{name} pumps {his} small fist in the air with unbridled enthusiasm.",
        "{name}'s eyes sparkle with the mischief of one who has just pulled off an impossible feat.",
        "{name} struts around the arena with the swagger of someone half again {his} size.",
        "{name}'s cheeky grin promises that {he} enjoyed every second of the fight.",
        "{name} gives the corpse a playful nudge with one small boot, still grinning.",
        "{name}'s entire body seems to vibrate with barely-contained jubilation.",
        "{name} deliberately stomps on the corpse's weapon, shattering it into pieces with satisfying crunches.",
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
        "{name} adjusts {his} gear with methodical precision, already analyzing the next engagement.",
        "{name} makes precise notes mentally, cataloging the exact technique that led to success.",
        "{name} offers a slight, calculating nod to the corpse. A problem solved efficiently.",
        "{name}'s analytical gaze sweeps over the body, measuring force vectors and impact angles.",
        "{name} mutters a series of technical observations, the tactical implications clear only to {him}.",
        "{name} performs a small, precise flourish with {his} weapon, form perfected through thousands of repetitions.",
        "{name}'s clever eyes dart between the corpse and the stands, assessing crowd reaction.",
        "{name} adjusts {his} stance with the precision of a craftsman fine-tuning an instrument.",
        "{name} offers a polite but distant nod, already moving mentally to the next problem.",
        "{name}'s expression shows satisfaction not with the kill, but with the efficiency achieved.",
        "{name} checks {his} equipment for wear with the care of one who values maintenance.",
        "{name} taps {his} weapon thoughtfully, considering what worked and what could be optimized.",
        "{name}'s small frame radiates the calm satisfaction of intellectual superiority proven in combat.",
        "{name} stands with the composed bearing of one for whom victory was merely inevitable.",
        "{name}'s precise movements suggest this outcome was calculated and controlled from the start.",
        "{name} offers a clinical assessment to the Blood Master, as if presenting research findings.",
        "{name} deliberately steps on the corpse's face, utterly indifferent to the violation of dignity.",
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
        "{name} cackles with unhinged glee, {his} entire body trembling with dark delight.",
        "{name}'s wide eyes reflect the corpse below, pupils dilated with malicious joy.",
        "{name} hisses and spits repeatedly, a rhythm of vicious triumph.",
        "{name} does a jerky, frantic dance that barely resembles any known celebration.",
        "{name}'s yellowed teeth flash in a predatory grin of savage satisfaction.",
        "{name} lets out a series of high-pitched shrieks that speak to primal hunger and conquest.",
        "{name} circles the body with twitching, manic energy barely contained in {his} frame.",
        "{name}'s claws flex and release repeatedly, caught in a cycle of violent excitement.",
        "{name} chatters incomprehensibly, the words too fast and too cruel to parse.",
        "{name}'s laughter sounds like breaking glass and rusted metal scraping together.",
        "{name} stares at the corpse with an intensity that borders on obsession.",
        "{name}'s whole body shudders with the aftershocks of battle-frenzy and bloodlust.",
        "{name} lets out a sound somewhere between a laugh and a shriek of pure malice.",
        "{name}'s darting eyes never leave the corpse, cataloging every detail of death.",
        "{name}'s breathing comes in short, sharp gasps of barely-contained excitement.",
        "{name} performs a series of exaggerated, mocking gestures over the fallen warrior.",
        "{name} spits directly into the corpse's mouth, a final act of goblin depravity.",
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
        "{name} tastes the air repeatedly, savoring the copper-and-salt flavor of the kill.",
        "{name}'s scales shimmer with a sickly iridescence, reflecting the triumph.",
        "{name}'s tail sweeps in powerful, satisfied arcs across the sand.",
        "{name} stands with the cold certitude of a predator who has just fed.",
        "{name}'s tongue flickers in and out, processing the chemical signature of violence.",
        "{name}'s eyes, ancient and unblinking, show no emotion beyond primal satisfaction.",
        "{name} hisses a long, rasping sound that speaks of territorial dominance.",
        "{name}'s claws dig into the sand repeatedly, an unconscious display of conquest.",
        "{name} stands motionless, every scale perfect, every muscle coiled and ready.",
        "{name}'s breathing settles into a rhythmic, reptilian pattern of completion.",
        "{name} makes a series of clicking, hissing sounds that echo through the arena.",
        "{name}'s body language screams of a predator satisfied with the hunt.",
        "{name} regards the corpse with the same detached interest as a crocodile studies its prey.",
        "{name}'s scales darken slightly, a color shift that reflects the intensity of {his} nature.",
        "{name} performs a slow, deliberate circuit around the body, claiming the territory.",
        "{name} opens {his} maw wide in a silent, terrifying display of satisfaction.",
        "{name} wrenches the corpse's head from its shoulders with savage strength, holding the grisly trophy aloft for all to witness.",
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
        "{name} purrs, a low, unsettling rumble that carries surprisingly far in the quieted arena.",
        "{name}'s whiskers tremble with the pure joy of the hunt brought to completion.",
        "{name} prowls around the body with feline grace, utterly satisfied with the kill.",
        "{name}'s eyes glow with an amber fire that speaks of primal feline pride.",
        "{name} makes a deep, rumbling purr that carries unsettling contentment.",
        "{name}'s claws extend and retract in rhythm with {his} satisfied breaths.",
        "{name} stretches languidly over the corpse, a cat indulging in a perfect moment.",
        "{name}'s fur bristles and smooths in waves, reflecting {his} emotional satisfaction.",
        "{name} pounces lightly on the corpse once more, purely for the joy of it.",
        "{name} grooms {his} blood-spattered fur with casual, deliberate licks.",
        "{name}'s tail swishes in hypnotic patterns, the dance of a sated predator.",
        "{name} lets out a series of chirping, trilling sounds of pure feline victory.",
        "{name} circles the body with the lithe grace of a dancer across the arena floor.",
        "{name}'s ears swivel and twitch with the contentment of a successful hunt.",
        "{name} makes a distinctive mrrrow sound, part laugh and part threat.",
        "{name} rolls across the sand beside the corpse, utterly pleased with {himself}.",
        "{name} stands and shakes, sending a spray of sand and blood into the air.",
        "{name} crouches over the corpse and tears a strip of flesh away, devouring it with savage delight.",
    ],
    "Half-Elf": [
        "{name} stands with a conflicted but proud bearing, the duality of {his} blood clear in victory.",
        "{name} offers a disciplined salute to the stands, the kill a hard-won prize.",
        "{name} stares at the fallen with a look of somber respect before sheathing {his} weapon.",
        "{name} lets out a strong, clear shout of triumph that rings with both human passion and elven clarity.",
        "{name} stands tall over the remains, {his} features an elegant mask of warrior's pride.",
        "{name} wipes {his} weapon with a methodical grace, the task completed with professional focus.",
        "{name} offers a slight, knowing smile to the crowd, the kill a validation of {his} hybrid path.",
        "{name} moves with a balance of power and agility that mocks the stillness of the dead.",
        "{name} looks at the Blood Master with a steady, confident gaze, a survivor's entitlement.",
        "{name} stands motionless for a heartbeat, the silence of the kill a moment of pure reflection.",
        "{name} stands with the poise of both human warrior and elven warrior, perfect balance achieved.",
        "{name}'s expression shows both the human fire of triumph and elven calm certainty.",
        "{name} offers a nod to the fallen that carries both respect and cold victory.",
        "{name}'s dual heritage shines through in a kill executed with perfect efficiency.",
        "{name} wipes {his} weapon with the grace of an elf and the satisfaction of a human.",
        "{name} stands tall, {his} hybrid nature proving superior to both parent races.",
        "{name}'s breathing carries the emotional weight of a human mixed with elven discipline.",
        "{name} gazes at the corpse with eyes that hold both passion and detachment.",
        "{name} offers a salute that blends human military bearing with elven elegance.",
        "{name} stands over the kill with the quiet confidence of one who belongs everywhere.",
        "{name} releases a breath that seems to carry the pride of two worlds.",
        "{name}'s posture is both relaxed like an elf and ready like a human warrior.",
        "{name} offers a subtle smile that carries the wisdom of long-lived grace and immediate human triumph.",
        "{name}'s hybrid strength is displayed in the casual power of the victory.",
        "{name} stands as living proof that two worlds can create something superior.",
        "{name} looks between the crowd and the corpse with perfect, practiced calm.",
        "{name} drives a boot heel through the corpse's ribs with calculated, deliberate cruelty.",
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
        "A terrifying sound erupts from {name}'s throat, something between a roar and a scream.",
        "{name}'s body seems to swell with dark satisfaction, barely contained power radiating outward.",
        "{name} looms larger than should be possible, the corpse looking tiny beneath {his} shadow.",
        "The very air around {name} grows cold, thick with the presence of something inhuman.",
        "{name}'s eyes flash with an unnatural light that speaks of malevolent joy.",
        "An acrid smell rolls off {name}, the reek of something ancient and utterly wrong.",
        "{name} stands over the kill with the posture of something that has forgotten mercy exists.",
        "The ground seems to tremble slightly with {name}'s satisfied stillness.",
        "{name}'s breath comes in hot, sulfurous waves that wilt the grass around {his} feet.",
        "Something about {name}'s victory feels profoundly unnatural, wrong in ways that defy description.",
        "{name} moves with a fluidity that violates the laws of how bodies should bend.",
        "A low, subsonic vibration emanates from {name}, felt more than heard.",
        "{name}'s form seems to shift in the light, never quite stable or real.",
        "The crowd feels the wrongness of {name}'s presence, an instinctive dread settling in.",
        "{name} stands as a monument to all that is dark and forbidden in the arena.",
        "An unnatural silence falls over the arena, as though the world itself recoils from {name}.",
        "{name} tears into the corpse with inhuman savagery, feasting on the fresh kill with bestial hunger.",
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
        "{name} stares down at the corpse in utter disbelief that {he} is still standing.",
        "{name}'s entire body shakes with the aftershock of adrenaline and pure survival instinct.",
        "{name} looks around frantically, as if expecting someone to wake {him} from this dream.",
        "{name}'s hands are still trembling as {he} slowly lowers {his} weapon.",
        "{name} breathes heavily, gasping for air as the reality of the kill slowly settles in.",
        "{name} offers a silent prayer of thanksgiving that {he} lived to see this moment.",
        "{name} wipes sweat and blood from {his} face, bewildered by {his} own victory.",
        "{name} stands on shaky legs, the weight of what {he} has done pressing down.",
        "{name}'s voice cracks as {he} lets out a weak, disbelieving laugh.",
        "{name} feels the crushing weight of a life taken settle on {his} shoulders.",
        "{name} looks to the crowd, seeking validation that this impossible thing really happened.",
        "{name}'s knees buckle slightly before {he} forces {himself} to stand tall.",
        "{name} makes the sign of the sacred over the corpse, seeking forgiveness for the kill.",
        "{name} stares at {his} own hands as though they belong to a stranger.",
        "{name}'s breath comes in ragged gasps, the shock of victory not yet wearing off.",
        "{name} feels fundamentally changed by this moment, no longer a common person.",
        "{name} spits on the corpse with newfound contempt, no longer afraid of the dead.",
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
    "{warrior} gasps for air, the armor's weight compounding exhaustion.",
    "The armor is taking a visible toll on {warrior}'s endurance.",
    "{warrior} moves like {he} is wading through sand, slowed by {his} own gear.",
    "The combination of armor and fatigue is grinding {warrior} down.",
    "{warrior}'s shoulders sag under the relentless burden of heavy iron.",
    "{warrior} is waging two wars at once, struggling against both {his} foe and {his} own armor.",
    "The weight redistributes with each step, and {warrior} compensates painfully.",
    "{warrior} is past the point of fighting efficiently, the armor dominates every motion.",
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
    "{warrior} staggers entering the arena, already fighting {his} own gear.",
    "The weight of {warrior}'s armor is apparent before the bout even begins.",
    "{warrior} looks weighted down as {he} takes position on the sand.",
    "An astute observer can already see the burden {warrior} is carrying.",
    "{warrior} moves heavily through the arena entrance, armor dragging {him} down.",
    "The crowd notices immediately. {warrior} is over-matched by {his} own equipment.",
    "{warrior} settles into place, and the strain of the armor is evident.",
    "Even in preparation, {warrior} shows signs of struggling with {his} heavy kit.",
    "{warrior}'s movements are already labored under the excessive weight {he} carries.",
    "The armor choice is questionable. {warrior} is clearly not built for what {he}'s wearing.",
]


def overencumbered_prefight_line(warrior_name: str, gender: str) -> str:
    his = "his" if gender == "Male" else "her"
    he  = "He"  if gender == "Male" else "She"
    him = "him" if gender == "Male" else "her"
    template = _pool_choice(_OVERENCUMBERED_PREFIGHT_LINES)
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
    template = _pool_choice(_OVERENCUMBERED_LINES)
    return template.format(
        warrior=warrior_name.upper(),
        his=his,
        he=he,
        him=him,
    )


# ---------------------------------------------------------------------------
# WEAPON STRAIN LINES
# For weapons too heavy for the wielder's STR, or two-handers swung one-handed.
# Pre-fight line in minute 1, plus an occasional line in place of the style intent line.
# Shared by every weapon: use {weapon} only, no weapon-type words.
# ---------------------------------------------------------------------------

_WEAPON_STRAIN_PREFIGHT_LINES = [
    "{warrior} is too weak for that {weapon}!",
    "The {weapon} will break {warrior}!",
    "{warrior} drags a {weapon} {he} has no right to carry!",
    "The crowd laughs. {warrior} cannot lift that {weapon}!",
    "The {weapon} is far beyond {warrior}!",
]

_WEAPON_STRAIN_ONEHANDED_PREFIGHT_LINES = [
    "{warrior} wields a two-handed {weapon} in one hand!",
    "One hand is a fool's grip on that {weapon}!",
    "{warrior} butchers the grip on a {weapon} made for two hands!",
    "The crowd sees {warrior} misuse a two-handed {weapon}!",
    "{warrior} holds a {weapon} wrong!",
    "That {weapon} demands two hands, and {warrior} offers one!",
    "{warrior} has no business swinging a {weapon} with one hand!",
]

WEAPON_STRAIN_MILD = [
    "{name} grunts and heaves {his} {weapon} around!",
    "{name} fights the dead weight of {his} {weapon}!",
    "{name} hauls {his} {weapon} forward with effort!",
    "{name} gasps under the weight of {his} {weapon}!",
    "{name} drags {his} {weapon} through the motion!",
    "{name} wrestles {his} {weapon} into line!",
]

WEAPON_STRAIN_SEVERE = [
    "{name} flails {his} {weapon} pathetically!",
    "{name} can barely hold {his} {weapon} up!",
    "{name} is dragged along by {his} {weapon}!",
    "{name} has no strength for {his} {weapon}!",
    "{name} reels under {his} {weapon}!",
    "{name} loses {his} {weapon} to its own weight!",
]

WEAPON_STRAIN_ONEHANDED = [
    "{name} has no leverage with {his} {weapon}!",
    "{name} cannot hold {his} {weapon} steady!",
    "{name} jerks {his} {weapon} around like a fool!",
    "{name} swings {his} {weapon} wildly off balance!",
    "{name} lacks the grip to control {his} {weapon}!",
    "{name} wastes the power of {his} {weapon}!",
    "{name} cannot drive {his} {weapon} with one hand!",
    "{name} flings {his} {weapon} about with no control!",
    "{name} fights {his} {weapon} with the wrong grip!",
    "{name} mangles the swing with one hand!",
    "The weight of {his} {weapon} tears at {name}'s grip!",
]


def _strain_fmt(template: str, name: str, gender: str, weapon_name: str) -> str:
    his = "his" if gender == "Male" else "her"
    he  = "he"  if gender == "Male" else "she"
    him = "him" if gender == "Male" else "her"
    return template.format(name=name.upper(), warrior=name.upper(), weapon=weapon_name.lower(),
                           his=his, he=he, him=him)


def weapon_strain_prefight_line(warrior_name: str, gender: str, weapon_name: str, kind: str) -> str:
    """kind: 'heavy' (under-strength) or 'awkward' (two-hander held one-handed)."""
    pool = _WEAPON_STRAIN_ONEHANDED_PREFIGHT_LINES if kind == "awkward" else _WEAPON_STRAIN_PREFIGHT_LINES
    return _strain_fmt(_pool_choice(pool), warrior_name, gender, weapon_name)


def weapon_strain_line(warrior_name: str, gender: str, weapon_name: str, kind: str, severity: str) -> str:
    """Swing-time line. kind: 'heavy' or 'awkward'; severity: 'mild' or 'severe' (heavy only)."""
    if kind == "awkward":
        pool = WEAPON_STRAIN_ONEHANDED
    else:
        pool = WEAPON_STRAIN_SEVERE if severity == "severe" else WEAPON_STRAIN_MILD
    return _strain_fmt(_pool_choice(pool), warrior_name, gender, weapon_name)


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
        "{name} hurls {himself} forward in a maelstrom of violence",
        "{name} tears through the arena like an unleashed beast",
        "{name} roars and unleashes a ferocious barrage",
        "{name} presses the assault with unrelenting savagery",
        "{name} drives forward with murderous fury burning in {his} eyes",
        "{name} abandons all restraint, hunting for the kill",
        "{name} erupts into a violent, relentless onslaught",
        "{name} swings with the fury of a battle-possessed warrior",
        "{name} charges headlong into a furious assault",
        "{name} unleashes a devastating, all-consuming attack",
        "{name} storms forward with bloodlust driving every motion",
        "{name} hurls {his} weapon forward with savage purpose",
        "{name} presses a brutal, unforgiving assault",
        "{name} launches into a frenzied, devastating barrage",
        "{name} drives forward with cold, lethal determination",
        "{name} floods the arena with a wave of primal violence",
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
        "{name} maintains an unending tide of steel",
        "{name} unleashes a relentless storm of blows",
        "{name} presses forward in an unyielding wave",
        "{name} hammers away with merciless, rhythmic fury",
        "{name} drives an endless tempest of strikes",
        "{name} maintains a suffocating barrage of attacks",
        "{name} unleashes a torrential assault without mercy",
        "{name} presses the assault with iron discipline",
        "{name} creates an overwhelming tide of violence",
        "{name} hammers forward with ceaseless brutality",
        "{name} dictates the pace with a crushing storm of blows",
        "{name} maintains relentless, crushing pressure",
        "{name} drives an unrelenting wall of steel forward",
        "{name} presses an unceasing barrage of strikes",
        "{name} unleashes a never-ending tide of violence",
        "{name} hammers away with terrible, relentless cadence",
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
        "{name} explodes forward with sudden, piercing speed",
        "{name} darts in with a committed thrust",
        "{name} closes the distance in a violent burst",
        "{name} springs forward with {his} weapon extended",
        "{name} lunges with explosive, focused precision",
        "{name} shifts weight and drives a sudden thrust",
        "{name} darts through the gap with lethal speed",
        "{name} surges forward with a piercing lunge",
        "{name} launches {his} body in a controlled explosion",
        "{name} thrusts with sudden, violent precision",
        "{name} closes distance with an explosive burst",
        "{name} springs in with a cunning, piercing strike",
        "{name} darts forward with a flashing, committed thrust",
        "{name} lunges decisively through the opening",
        "{name} charges in with a violent, extended thrust",
        "{name} explodes forward with piercing purpose",
    ],
    "Bash": [
        "{name} winds up for a crushing blow",
        "{name} drives forward with brute force",
        "{name} attempts to batter through {foe}'s defenses",
        "{name} puts the entirety of {his} weight behind a punishing smash",
        "{name} looks to break bone and shatter iron with a heavy impact",
        "{name} rears back to deliver a concussive, grounding assault",
        "{name} targets {foe}'s vitals with a slow, devastating wind-up",
        "{name} winds up with the full weight of {his} body",
        "{name} prepares a devastating, bone-shattering blow",
        "{name} rears back to drive through with brutal force",
        "{name} plants {his} feet and winds up for a bone-crushing strike",
        "{name} prepares to smash through with raw power",
        "{name} winds up with murderous, crushing intent",
        "{name} braces to unleash a bone-jarring assault",
        "{name} readies a concussive blow meant to devastate",
        "{name} winds up to batter through defenses with force",
        "{name} prepares a sledgehammer swing of terrible weight",
        "{name} gathers {his} strength for a pulverizing strike",
        "{name} winds up with brutal, focused power",
        "{name} rears back to deliver a crushing, body-weight blow",
        "{name} prepares to drive {his} weapon through with force",
        "{name} winds up with the intent to shatter bone",
        "{name} braces to unleash a bone-breaking assault",
    ],
    "Slash": [
        "{name} draws back for a sweeping slash",
        "{name} lines up for a powerful drawing cut",
        "{name} seeks to open a telling wound",
        "{name} unleashes a wide, flashing arc of steel toward {foe}",
        "{name} carves a wicked path through the air with {his} {weapon}",
        "{name} slices forward in a deadly, fluid motion designed to draw blood",
        "{name} pivots sharply to deliver a vicious, tearing slash",
        "{name} draws back to unleash a vicious, sweeping arc",
        "{name} winds up to carve a deadly path",
        "{name} prepares a wide, tearing slash",
        "{name} lines up to slice through with fluid motion",
        "{name} draws back to unleash a wicked cutting stroke",
        "{name} readies {his} {weapon} for a slashing arc",
        "{name} pivots to deliver a vicious, carving slash",
        "{name} winds up to open a telling wound",
        "{name} prepares a wide, flashing cut",
        "{name} draws back for a vicious, tearing motion",
        "{name} readies {his} weapon for a deadly arc",
        "{name} prepares to carve a wicked path forward",
        "{name} winds up to slash with violent, fluid grace",
        "{name} lines up for a sweeping, wounding cut",
        "{name} draws back to unleash a deadly, slicing arc",
        "{name} pivots sharply to deliver a vicious, carving blow",
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
        "{name} sizes up {foe} and prepares to strike",
        "{name} tests the distance and launches the attack",
        "{name} finds the opening and drives forward",
        "{name} steps in and readies a solid blow",
        "{name} squares {his} shoulders and prepares to lash out",
        "{name} advances and lines up the strike",
        "{name} sizes {foe} up and looks for the angle",
        "{name} measures {foe} and readies the assault",
        "{name} finds {his} moment and strikes",
        "{name} steps close and prepares the assault",
        "{name} readies a direct, calculated strike",
        "{name} advances with clear intent to hit",
        "{name} sizes up the opening carefully",
        "{name} launches a sudden, solid attack",
        "{name} steps in and prepares to drive forward",
        "{name} finds the gap and readies the strike",
    ],
    "Engage & Withdraw": [
        "{name} probes for weakness, then retreats to reposition",
        "{name} feints left, striking before pulling back",
        "{name} dances in close, lashing out before withdrawing",
        "{name} steps in with a sharp blow before springing backward out of danger",
        "{name} tests the line with a quick strike, then instantly glides out of range",
        "{name} plays a dangerous game of distance, striking before pulling back",
        "{name} slips inside the guard, striking quickly before retreating to safety",
        "{name} darts in to probe the defenses before withdrawing",
        "{name} prepares a quick strike and swift retreat",
        "{name} positions {himself} for a lightning-fast engagement",
        "{name} readies a darting thrust before falling back",
        "{name} prepares to test {foe}'s guard with a quick strike",
        "{name} braces to strike swiftly and disengage",
        "{name} readies a probing jab and rapid withdrawal",
        "{name} prepares to dart in and out of range",
        "{name} positions {himself} for hit-and-run tactics",
        "{name} readies a quick, penetrating strike before retreat",
        "{name} prepares for a sharp probe of the defense",
        "{name} braces to engage quickly then fall back",
        "{name} readies for a rapid strike and pullback",
        "{name} prepares a probing offensive before regrouping",
        "{name} positions {himself} for swift, tactical strikes",
        "{name} readies to dart in, strike, and withdraw",
    ],
    "Counterstrike": [
        "{name} waits patiently for {foe} to make a mistake",
        "{name} holds ground, watching {foe} like a hawk",
        "{name} anxiously awaits {foe}'s next move",
        "{name} anchors {his} weight, coiled like a spring to exploit the slightest slip",
        "{name} tracks the arc of {foe}'s stance, biding time for a fatal mistake",
        "{name} lets {foe} dictate the tempo, preparing to violently reverse the momentum",
        "{name} keeps a perfectly still guard, baiting the attack to execute a sharp riposte",
        "{name} stands motionless, watching for any opening",
        "{name} settles into a still guard, waiting for the mistake",
        "{name} coils {his} weight, ready to pounce on weakness",
        "{name} watches intently, waiting for {foe} to overextend",
        "{name} keeps a perfect guard, tracking {foe}'s every move",
        "{name} bides {his} time, preparing to reverse the tide",
        "{name} holds {his} ground like a coiled snake",
        "{name} waits with predatory patience for the opening",
        "{name} tracks {foe}'s stance, ready to capitalize instantly",
        "{name} settles into stillness, baiting {foe} forward",
        "{name} anchors {himself}, coiled and ready to explode",
        "{name} watches with the focus of a hunting predator",
        "{name} bides time with perfect stillness and focus",
        "{name} waits poised for the moment to reverse momentum",
        "{name} holds ground perfectly still, baiting the aggression",
        "{name} coils like a spring, ready to strike the opening",
    ],
    "Decoy": [
        "{name} feints at {foe}'s guard",
        "{name} feints to draw {foe}'s attention",
        "{name} draws {foe} into an elaborate trap",
        "{name} purposely exposes a glaring opening to mask a lethal incoming strike",
        "{name} drops {his} guard for a split second, daring {foe} to rush forward",
        "{name} throws a loud, distracting blow to mask the true attack",
        "{name} misdirects with a sudden shift in posture, blinding {foe} to the real danger",
        "{name} feints left to mask the real attack",
        "{name} prepares an elaborate feint and trap",
        "{name} readies a loud, distracting strike",
        "{name} plans to expose a false opening",
        "{name} prepares to draw {foe} in the wrong direction",
        "{name} feints to bait {foe} into overcommitting",
        "{name} readies a clever trap with false openings",
        "{name} prepares to distract with one blow while striking with another",
        "{name} plans to misdirect {foe}'s attention",
        "{name} readies a feint designed to bait aggression",
        "{name} prepares an elaborate ruse of false weakness",
        "{name} feints to draw {foe} out of position",
        "{name} readies a loud strike to mask the true danger",
        "{name} prepares to trap {foe} with a clever feint",
        "{name} plans to blind {foe} to the real attack",
        "{name} readies a feint to set up the real strike",
    ],
    "Sure Strike": [
        "{name} waits for the right moment, then commits fully",
        "{name} carefully prepares a deliberate strike",
        "{name} takes aim at {foe} with methodical precision",
        "{name} narrows {his} focus, blocking out the roaring crowd to ensure a perfect hit",
        "{name} aligns {his} posture to guarantee the oncoming blow finds its mark",
        "{name} measures the distance perfectly before committing to a flawless execution",
        "{name} refuses to waste motion, locking onto a definitive weakness in the defense",
        "{name} takes careful aim at a definitive weakness",
        "{name} narrows {his} focus to ensure a perfect strike",
        "{name} aligns {his} entire frame for maximum precision",
        "{name} measures {foe}'s defenses with meticulous care",
        "{name} refuses to commit until the moment is absolutely right",
        "{name} locks onto the weakness and prepares the perfect blow",
        "{name} blocks out all distractions, focusing only on the strike",
        "{name} waits with methodical patience for the perfect opening",
        "{name} measures the distance with absolute precision",
        "{name} aligns posture and weapon for a flawless strike",
        "{name} takes deliberate aim at {foe}'s weakness",
        "{name} narrows focus to eliminate all doubt",
        "{name} prepares with meticulous, deliberate care",
        "{name} commits to a strike designed to find its mark",
        "{name} measures every movement with surgical precision",
        "{name} waits for perfect alignment before the strike",
    ],
    "Calculated Attack": [
        "{name} ruthlessly seeks wreckage with {his} {weapon}",
        "{name} calculates the perfect attack angle",
        "{name} studies {foe}'s armor for weak points",
        "{name} analyzes the gaps in {foe}'s protection to maximize the impending trauma",
        "{name} maps out a lethal trajectory across the sand with cold, analytical focus",
        "{name} deliberately exploits a minor flaw in {foe}'s footwork to setup a devastating wound",
        "{name} weighs the risk of the engagement, choosing a path of maximum destruction",
        "{name} analyzes {foe}'s stance for critical weaknesses",
        "{name} calculates the trajectory for maximum impact",
        "{name} studies the armor's gaps with cold precision",
        "{name} maps out the perfect strike with ruthless calculation",
        "{name} seeks to exploit {foe}'s footwork with deliberate intent",
        "{name} weighs angles and impact with analytical focus",
        "{name} analyzes {foe}'s defenses to find the breaking point",
        "{name} calculates a path of maximum trauma",
        "{name} studies every gap in {foe}'s protection",
        "{name} maps a lethal strike with calculated precision",
        "{name} ruthlessly exploits a flaw in {foe}'s posture",
        "{name} analyzes the perfect moment for maximum destruction",
        "{name} calculates the blow with cold, brutal focus",
        "{name} studies {foe} for exploitable weaknesses",
        "{name} maps out a devastating trajectory with ruthless intent",
        "{name} ruthlessly calculates the path of greatest harm",
    ],
    "Opportunity Throw": [
        "{name} hefts {his} {weapon} for a throw",
        "{name} lines up a ranged attack",
        "{name} spots a momentary lapse in distance and cocks {his} arm back to launch",
        "{name} balances the weight of {his} {weapon}, preparing to send it flying through the air",
        "{name} readies a lethal projectile strike as the gap between the fighters widens",
        "{name} prepares to release a flying assault that will catch {foe} completely off guard",
        "{name} measures the distance for a desperate, high-stakes ranged throw",
        "{name} spots the opening and readies a ranged assault",
        "{name} hefts {his} weapon as the gap widens",
        "{name} readies a lethal throw as distance increases",
        "{name} cocks {his} arm, launching a ranged strike",
        "{name} balances the throw and spots {foe}'s vulnerability",
        "{name} measures the expanding distance for a perfect throw",
        "{name} prepares a flying strike that will catch {foe} unaware",
        "{name} lines up a devastating ranged assault",
        "{name} hefts the weapon and launches a desperate throw",
        "{name} spots the moment and readies the projectile",
        "{name} cocks {his} arm for a high-stakes ranged attack",
        "{name} measures distance and prepares to launch",
        "{name} readies a lethal throw as opportunity opens",
        "{name} balances {his} weapon for a flying strike",
        "{name} spots the lapse and readies the throw",
        "{name} prepares a ranged assault designed to catch {foe} off guard",
    ],
    "Martial Combat": [
        "{name} drops into a fighting crouch",
        "{name} circles {foe} with fluid martial grace",
        "{name} prepares to unleash a flurry of strikes",
        "{name} shifts seamlessly between combat stances, executing flawless form",
        "{name} channels disciplined training, moving with the cold efficiency of a veteran",
        "{name} balances weight perfectly on the balls of {his} feet, ready for a complex sequence",
        "{name} controls the space with expert positioning, establishing absolute command of the sand",
        "{name} circles with fluid, trained precision",
        "{name} shifts seamlessly into attack position",
        "{name} drops low and readies a complex combination",
        "{name} moves with the grace of disciplined training",
        "{name} balances perfectly, controlling the space",
        "{name} circles with expert martial skill",
        "{name} shifts between stances with seamless fluidity",
        "{name} prepares a flurry of strikes with trained precision",
        "{name} moves with cold, efficient veteran skill",
        "{name} positions {himself} with absolute command of the sand",
        "{name} drops into position and readies the offense",
        "{name} circles {foe} with tactical grace",
        "{name} shifts weight and prepares a complex sequence",
        "{name} channels training into fluid, deadly movement",
        "{name} balances and positions for maximum control",
        "{name} moves with seamless martial efficiency",
    ],
    "Parry": [
        "{name} raises {his} {weapon} defensively",
        "{name} holds ground, focused entirely on defense",
        "{name} sets an iron guard, tracking the trajectory of the incoming threat",
        "{name} angles {his} {weapon} to catch and deflect the next strike with minimal effort",
        "{name} mirrors {foe}'s weapon movements, preparing a crisp deflection",
        "{name} readies a tight, defensive redirection to turn the momentum of the fight",
        "{name} anchors {his} posture, waiting to cross steel and turn the blow aside",
        "{name} raises {his} guard and tracks the incoming strike",
        "{name} sets an iron defense, ready to deflect",
        "{name} angles {his} weapon to catch the blow cleanly",
        "{name} readies to mirror {foe}'s attack with precise deflection",
        "{name} prepares a tight parry to turn the momentum",
        "{name} holds ground with focused, disciplined defense",
        "{name} anchors {himself} and prepares to cross steel",
        "{name} tracks {foe}'s weapon with unwavering focus",
        "{name} angles {his} {weapon} with minimal wasted motion",
        "{name} readies a crisp deflection of the incoming threat",
        "{name} prepares to turn the blow aside with precision",
        "{name} sets {his} guard and waits to intercept",
        "{name} readies a tight redirection of momentum",
        "{name} prepares to cross steel and parry cleanly",
        "{name} tracks the trajectory and prepares to deflect",
        "{name} holds ground, mirroring {foe}'s movements defensively",
    ],
    "Defend": [
        "{name} keeps {his} guard high",
        "{name} circles warily, waiting for an opening",
        "{name} tucks {his} chin and locks down {his} defensive perimeter",
        "{name} refuses to overextend, maintaining an unbreakable protective posture",
        "{name} yields ground deliberately, monitoring the distance with absolute caution",
        "{name} hunkers down behind a wall of steel, offering {foe} zero easy targets",
        "{name} watches the opponent's shoulders, entirely prepared to absorb or evade the coming assault",
        "{name} keeps {his} guard high and circles warily",
        "{name} tucks {his} chin, locking down {his} defenses",
        "{name} refuses to overextend, maintaining {his} protective posture",
        "{name} yields ground and monitors the distance carefully",
        "{name} hunkers down, offering {foe} no easy targets",
        "{name} watches {foe}'s shoulders, ready to absorb or evade",
        "{name} circles carefully behind a wall of steel",
        "{name} maintains an unbreakable protective stance",
        "{name} monitors the distance with absolute caution",
        "{name} locks down {his} defensive perimeter",
        "{name} refuses to give ground carelessly",
        "{name} keeps {his} guard raised and ready",
        "{name} hunkers down with defensive resolve",
        "{name} circles warily, watching for openings",
        "{name} yields ground deliberately and carefully",
        "{name} maintains a fortress-like defensive posture",
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
        "scale": [
            "{name} winds up to shatter the overlapping scales",
            "{name} looks to crack bone through the layered scale armor",
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
        "scale": [
            "{name} measures the spacing between the overlapping scales",
            "{name} takes aim at the gaps where the scales overlap",
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
        "scale": [
            "{name} calculates the spacing between overlapping scales for maximum penetration",
            "{name} analyzes the gaps where the scales interlock for the perfect opening",
            "{name} studies the scale pattern to find maximum vulnerability",
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
    if "chain" in armor_lower:
        return "chain"

    # Scale-based armor
    if "scale" in armor_lower:
        return "scale"

    # Leather-based armor
    if any(x in armor_lower for x in ["leather", "cuir"]):
        return "leather"

    # Default to none
    return "none"

# OPEN HAND STYLE INTENT LINES
# Used instead of STYLE_INTENT_POOLS when the attacker is unarmed. Keyed by style,
# then by swing type from combat._get_martial_attack_type ("claw"/"kick"/"tail");
# "fists" is the fallback for races without natural weapons.
OPEN_HAND_STYLE_INTENT_POOLS: dict[str, dict[str, list[str]]] = {
    "Wall of Steel": {
        "fists": [
            "{name} hammers {foe} with relentless blows",
            "{name} pounds away at {foe} without pause",
            "{name} presses {foe} with ceaseless punches",
            "{name} smothers {foe} in a flurry of strikes",
            "{name} drives forward, fists never still",
            "{name} maintains suffocating pressure on {foe}",
            "{name} batters {foe} with a ceaseless barrage",
            "{name} throws punch after punch at {foe}",
            "{name} swarms {foe} with relentless fists",
            "{name} grinds forward, fists pumping",
            "{name} rains blows down on {foe}",
            "{name} pummels {foe} without mercy",
            "{name} crowds {foe} with a storm of punches",
        ],
        "claw": [
            "{name} rakes at {foe} without pause",
            "{name} tears at {foe} in a ceaseless flurry",
            "{name} slashes at {foe} with relentless claws",
            "{name} drives forward, claws never still",
            "{name} gives {foe} no room, claws raking",
            "{name} presses {foe} with a storm of swipes",
            "{name} shreds at {foe} with ceaseless swipes",
            "{name} lashes out with claw after claw",
            "{name} savages {foe} in a blur of claws",
            "{name} rakes {foe} with merciless speed",
            "{name} flays at {foe} without mercy",
            "{name} swipes at {foe} in a relentless frenzy",
            "{name} claws forward, slashing without rest",
        ],
        "kick": [
            "{name} hammers {foe} with relentless kicks",
            "{name} drives a ceaseless volley of kicks at {foe}",
            "{name} kicks without pause",
            "{name} pounds {foe} with driving kicks",
            "{name} advances behind a barrage of kicks",
            "{name} presses {foe} with kick after kick",
            "{name} batters {foe} with ceaseless kicks",
            "{name} unleashes a relentless flurry of kicks",
            "{name} stamps forward, kicks landing like hammers",
            "{name} lashes out with kick after punishing kick",
            "{name} swarms {foe} with a storm of kicks",
            "{name} drives {foe} back with heavy kicks",
            "{name} hammers away with merciless kicks",
            "{name} kicks at {foe} with brutal rhythm",
        ],
        "tail": [
            "{name} whips {his} tail at {foe} without pause",
            "{name} hammers {foe} with relentless tail strikes",
            "{name} drives a ceaseless storm of tail lashes",
            "{name} presses forward, tail lashing",
            "{name} sweeps {his} tail at {foe} in a ceaseless barrage",
            "{name} pounds {foe} with a barrage of tail blows",
            "{name} lashes {foe} with a thrashing tail",
            "{name} swings {his} tail like a club",
            "{name} batters {foe} with merciless tail strikes",
            "{name} drives {his} tail into {foe} without pause",
            "{name} thrashes forward, tail whipping",
            "{name} unleashes a relentless flurry of tail blows",
            "{name} cracks {his} tail at {foe} with brutal rhythm",
            "{name} presses {foe} with ceaseless tail lashes",
        ],
    },
    "Slash": {
        "fists": [
            "{name} draws back for a sweeping hook",
            "{name} winds up a wide, swinging blow at {foe}",
            "{name} swings a looping fist across the line",
            "{name} lines up a wide, whipping backhand",
            "{name} pivots sharply into a sweeping strike",
            "{name} arcs a heavy fist toward {foe}",
        ],
        "claw": [
            "{name} draws back for a sweeping rake",
            "{name} lines up a wide, tearing swipe",
            "{name} sweeps a clawed hand toward {foe}",
            "{name} pivots sharply for a vicious, raking arc",
            "{name} readies claws for a long, tearing slash",
            "{name} swings claws wide at {foe}",
        ],
        "kick": [
            "{name} draws back for a sweeping roundhouse",
            "{name} lines up a wide, arcing kick",
            "{name} pivots sharply into a whipping kick",
            "{name} swings a leg in a long, hard arc",
            "{name} sets {his} weight for a sweeping kick",
            "{name} loads a wide, driving kick",
        ],
        "tail": [
            "{name} draws {his} tail back for a sweeping lash",
            "{name} coils {his} tail for a wide, whipping arc",
            "{name} pivots sharply, tail swinging wide",
            "{name} lines up a long, lashing sweep",
            "{name} cocks {his} tail for a vicious arc",
            "{name} whips {his} tail around in a wide arc",
        ],
    },
    "Lunge": {
        "fists": [
            "{name} darts forward behind a straight punch",
            "{name} explodes in with a long, driving punch",
            "{name} closes the distance in a violent burst",
            "{name} extends {his} reach to its limit, striking hard",
            "{name} drives a sudden, straight blow at {foe}",
            "{name} surges in with a committed punch",
        ],
        "claw": [
            "{name} darts forward, claws extended",
            "{name} springs in with claws leading",
            "{name} closes the distance, claws reaching",
            "{name} drives {his} claws at {foe} in a sudden surge",
            "{name} lunges, claws spread for the kill",
            "{name} extends {his} reach, claws first",
        ],
        "kick": [
            "{name} darts forward behind a driving kick",
            "{name} explodes in with a straight, thrusting kick",
            "{name} launches {himself} forward, foot leading",
            "{name} closes the distance with a sudden front kick",
            "{name} drives a long, straight kick at {foe}",
            "{name} surges in with a committed kick",
        ],
        "tail": [
            "{name} darts forward, tail snapping out",
            "{name} drives {his} tail at {foe} in a sudden surge",
            "{name} closes the distance, tail lashing straight",
            "{name} explodes forward behind a spearing tail strike",
            "{name} snaps {his} tail out in a long, reaching strike",
            "{name} surges in, tail leading",
        ],
    },
    "Parry": {
        "fists": [
            "{name} raises {his} guard defensively",
            "{name} holds ground, focused entirely on defense",
            "{name} tracks the incoming strike with unwavering focus",
            "{name} readies a tight redirection to turn {foe}'s blow aside",
            "{name} sets {his} guard and waits to intercept",
            "{name} anchors {his} posture, ready to knock the attack away",
            "{name} watches {foe}'s every movement, ready to deflect",
            "{name} prepares to turn the blow aside with minimal motion",
            "{name} mirrors {foe}'s movements, preparing a crisp deflection",
            "{name} sets {his} guard and tracks the trajectory",
        ],
    },
}

# Shared-pool lines containing these are skipped for unarmed attackers when the style
# has no dedicated Open Hand pool (weapon names, steel/iron imagery, thrusts and stabs).
_OPEN_HAND_EXCLUDE_TOKENS = ("weapon", "steel", "iron", "blade", "thrust", "stab", "hack", "riposte", "jab")

# Awkward lines for unarmed attackers (Open Hand is only incompatible with Bash).
OPEN_HAND_AWKWARD_INTENT_POOLS: dict[str, list[str]] = {
    "Bash": [
        "{name} awkwardly tries to bash with nothing to bash with",
        "{name} struggles to put real weight behind a bash",
        "{name} clumsily winds up a weightless bash",
        "{name} futilely tries to smash through",
        "{name} fumbles a bash with nothing in hand",
        "{name} swings for a bash with no mass behind it",
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
    foe_armor    : Optional[str] = None,
    attack_type  : Optional[str] = None,
) -> Optional[str]:
    """
    Return a style intent line (or None, ~60% skip chance).
    Uses open-hand narratives for unarmed attackers (attack_type: claw/kick/tail),
    otherwise armor-specific narratives when available for the style.
    """
    if random.random() < 0.30:
        return None

    # Unarmed attackers get their own pools; weapon pools mention steel, iron, etc.
    if weapon_name == "Open Hand" and style in OPEN_HAND_STYLE_INTENT_POOLS:
        oh_pools = OPEN_HAND_STYLE_INTENT_POOLS[style]
        pool = oh_pools.get(attack_type or "fists", oh_pools["fists"])
    # Try to get armor-specific pool first
    elif style in ARMOR_SPECIFIC_INTENT_POOLS:
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

    if weapon_name == "Open Hand" and style not in OPEN_HAND_STYLE_INTENT_POOLS:
        pool = [l for l in pool if not any(t in l.lower() for t in _OPEN_HAND_EXCLUDE_TOKENS)] or pool

    template = _pool_choice(pool)
    pronoun  = "his" if gender == "Male" else "her"
    reflexive= "himself" if gender == "Male" else "herself"
    adj      = _pool_choice(WARRIOR_ADJ_POOL)

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
    if weapon_name == "Open Hand" and style in OPEN_HAND_AWKWARD_INTENT_POOLS:
        pool = OPEN_HAND_AWKWARD_INTENT_POOLS[style]
    else:
        pool = AWKWARD_STYLE_INTENT_POOLS.get(style, None)
    if pool is None:
        # Fallback to normal line if no awkward pool exists for this style
        return style_intent_line(warrior_name, foe_name, style, weapon_name, gender)
    
    template = _pool_choice(pool)
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
    "Primary Arm"   : ["weapon arm", "primary arm", "dominant arm"],
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
    attack_type    : str = None,      # Pre-chosen claw/kick/tail for this swing, so this
                                       # line agrees with hit_line()/damage_line() for the
                                       # same attack. Falls back to a fresh random pick if
                                       # not supplied (caller didn't need cross-line sync).
) -> str:
    """Generate the attack declaration line. Lizardfolk with Open Hand get special claw/tail/kick verbs."""
    weapon_category = _refine_category(weapon_category, weapon_name)
    loc_pool = AIM_POINT_LABELS.get(aim_point, AIM_POINT_LABELS["None"])
    location = _pool_choice(loc_pool)
    pronoun  = "his" if attacker_gender == "Male" else "her"

    # Lizardfolk with Open Hand use special descriptors (claws, kicks, tail)
    if attacker_race == "Lizardfolk" and weapon_name == "Open Hand":
        chosen_type = attack_type or random.choice(["claw", "kick", "tail"])

        verb_pool = LIZARDFOLK_ATTACK_VERBS.get(chosen_type, LIZARDFOLK_ATTACK_VERBS["claw"])
        verb = _pool_choice(verb_pool)

        # Format with proper weapon descriptor in the sentence (no pronoun prefix)
        weapon_descriptors = {
            "claw": "claws",
            "kick": "leg",
            "tail": "tail",
        }
        weapon_desc = weapon_descriptors.get(chosen_type, "claws")

        return (
            f"{attacker_name.upper()}'s {weapon_desc} {verb} at {defender_name.upper()}'s {location}!"
        )

    # Tabaxi with Open Hand use special descriptors (claws and kicks)
    if attacker_race == "Tabaxi" and weapon_name == "Open Hand":
        chosen_type = attack_type or random.choice(["claw", "kick"])

        verb_pool = TABAXI_ATTACK_VERBS.get(chosen_type, TABAXI_ATTACK_VERBS["claw"])
        verb = _pool_choice(verb_pool)

        # Format with proper weapon descriptor in the sentence (no pronoun prefix)
        weapon_descriptors = {
            "claw": "claws",
            "kick": "leg",
        }
        weapon_desc = weapon_descriptors.get(chosen_type, "claws")

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
        verb = _pool_choice(STYLE_ATTACK_PREFIX[style])
        return (
            f"{attacker_name.upper()} {verb} {defender_name.upper()}'s "
            f"{location} with {pronoun} {weapon_name.lower()}"
        )
    else:
        # Category verb variant, weapon mentioned at the end
        cat_verbs = ATTACK_VERBS.get(weapon_category, ATTACK_VERBS["Oddball"])
        verb = _pool_choice(cat_verbs)
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
    "tail"  : ["whips across", "coils around", "sweeps across", "crashes into"],
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
    "Primary Arm"  : ["weapon arm", "dominant arm", "armor on the arm"],
    "Secondary Arm": ["shield arm", "off arm", "forearm armor"],
    "Primary Leg"  : ["primary leg", "lead leg", "thigh"],
    "Secondary Leg": ["rear leg", "trailing leg"],
    "None"    : ["armor", "body", "torso"],
}

# Announcement pools keyed by hit precision (precise: margin 50+, barely: margin
# under 20, normal: everything between). Lines announce how the hit got through.
HIT_ANNOUNCEMENTS: dict[str, list[str]] = {
    "precise": [
        "{attacker}'s strike lands exactly where aimed!",
        "{attacker} strikes without hesitation!",
        "{attacker} hits {defender} with ruthless accuracy!",
        "{defender} has no answer for it!",
        "{defender} never sees it coming!",
        "{attacker} drives the {weapon} home with deadly aim!",
        "{attacker} hits {defender} clean!",
        "{attacker} breaks straight through {defender}'s guard!",
        "{attacker}'s {weapon} finds its target dead on!",
        "{attacker} wastes no motion!",
        "{defender}'s guard is torn open!",
        "{attacker} hits with cold precision!",
        "{attacker} punishes {defender} without mercy!",
        "The {weapon} lands with deadly accuracy!",
        "{attacker} drives straight through {defender}'s defense!",
        "{defender} cannot stop it!",
    ],
    "barely": [
        "{attacker} wrenches the {weapon} past {defender}'s guard!",
        "{attacker} tears through a thin gap in {defender}'s defense!",
        "{defender}'s guard buckles just enough!",
        "{attacker} jams the {weapon} through the gap!",
        "{attacker} forces the {weapon} through {defender}'s failing guard!",
        "{attacker} rips through the little room {defender} leaves!",
        "{defender} stops most of the blow!",
        "{attacker} slides the hit through {defender}'s defense!",
        "{attacker} muscles a path through {defender}'s guard!",
        "{attacker} drives the {weapon} through a sliver of opening!",
        "{defender}'s guard gives just enough ground!",
        "{attacker} shoves the hit home at the last instant!",
        "The {weapon} punches through the gap {defender} nearly closed!",
        "{attacker} bulls the {weapon} through {defender}'s crumbling guard!",
        "{defender} is a half-step too slow to stop the {weapon}!",
        "{attacker} gets the {weapon} through by brute force!",
    ],
    "normal": [
        "{attacker} finds the opening!",
        "{attacker} drives the {weapon} past {defender}'s guard!",
        "{attacker} breaks through {defender}'s defense!",
        "The {weapon} punches through {defender}'s guard!",
        "{attacker} bulls through {defender}'s defense!",
        "{attacker} gets a lucky opening!",
        "{attacker} punishes the gap in {defender}'s defense!",
        "{defender} cannot stop the {weapon}!",
        "{attacker} forces the {weapon} through!",
        "{defender} pays for the opening!",
        "{attacker} rips the {weapon} through {defender}'s guard!",
        "{attacker} slams the {weapon} past {defender}'s guard!",
        "{attacker} attacks with savage intent!",
        "{defender}'s guard fails!",
        "{attacker} slips the {weapon} through {defender}'s defense!",
        "The blow connects!",
    ],
}


def hit_line(
    attacker_name : str,
    defender_name : str,
    weapon_name   : str,
    weapon_category: str,
    aim_point     : str,
    attacker_gender: str = "Male",    # For pronoun handling
    hit_precision : str = "normal",  # "precise", "normal", "barely"
    attacker_race : str = None,       # For Lizardfolk special handling
    style         : str = None,       # For Opportunity Throw special handling
    is_counterstrike: bool = False,   # True when this is a counterattack
    attack_type    : str = None,      # Pre-chosen claw/kick/tail for this swing, so this
                                       # line agrees with attack_line()/damage_line() for the
                                       # same attack. Falls back to a fresh random pick if
                                       # not supplied (caller didn't need cross-line sync).
) -> list[str]:
    """
    Return 1-2 lines describing a successful hit.
    hit_precision affects whether an announcement line precedes the hit
    and which announcement pool it is drawn from.
    If attacker is Lizardfolk using Open Hand, use claw/tail/kick descriptions.
    is_counterstrike makes it clear this is a counterattack weapon strike.
    """
    weapon_category = _refine_category(weapon_category, weapon_name)
    lines = []

    # Setup pronouns for formatting
    his_pronoun = "his" if attacker_gender == "Male" else "her"

    # Announce the hit if it was a precise, barely-made blow, or a counterstrike
    if is_counterstrike or hit_precision == "precise" or random.random() < 0.25:
        if is_counterstrike:
            # For counterstrikes, explicitly indicate the counterattack
            ann = f"{attacker_name.upper()} counters with a swift strike using their {weapon_name.lower()}!"
        else:
            ann = _pool_choice(HIT_ANNOUNCEMENTS.get(hit_precision, HIT_ANNOUNCEMENTS["normal"])).format(
                attacker=attacker_name.upper(),
                defender=defender_name.upper(),
                weapon  =weapon_name.lower(),
                his=his_pronoun,
            )
        lines.append(ann)

    # Lizardfolk with Open Hand use special claw/tail/kick descriptions
    if attacker_race == "Lizardfolk" and weapon_name == "Open Hand":
        chosen_type = attack_type or random.choice(["claw", "kick", "tail"])

        verb_pool = LIZARDFOLK_HIT_VERBS.get(chosen_type, LIZARDFOLK_HIT_VERBS["claw"])
        verb = _pool_choice(verb_pool)
        target_pool = HIT_TARGETS.get(aim_point, HIT_TARGETS["None"])
        target = _pool_choice(target_pool)

        # Create attack type descriptor
        attack_desc = {
            "claw": "claws",
            "kick": "powerful kick",
            "tail": "lashing tail",
        }.get(chosen_type, "claws")

        lines.append(
            f"{attacker_name.upper()}'s {attack_desc} "
            f"{verb} {defender_name.upper()}'s {target}!"
        )
    # Tabaxi with Open Hand use special claw/kick descriptions
    elif attacker_race == "Tabaxi" and weapon_name == "Open Hand":
        chosen_type = attack_type or random.choice(["claw", "kick"])

        verb_pool = TABAXI_HIT_VERBS.get(chosen_type, TABAXI_HIT_VERBS["claw"])
        verb = _pool_choice(verb_pool)
        target_pool = HIT_TARGETS.get(aim_point, HIT_TARGETS["None"])
        target = _pool_choice(target_pool)

        # Create attack type descriptor
        attack_desc = {
            "claw": "claws",
            "kick": "powerful kick",
        }.get(chosen_type, "claws")

        lines.append(
            f"{attacker_name.upper()}'s {attack_desc} "
            f"{verb} {defender_name.upper()}'s {target}!"
        )
    else:
        target_pool = HIT_TARGETS.get(aim_point, HIT_TARGETS["None"])
        target = _pool_choice(target_pool)
        if weapon_name.lower() == "bola":
            # Bola hits with swinging weighted balls - flail-style, never "embeds" or "pierces"
            verb = random.choice(["crashes into", "slams into", "smashes into", "wraps around and strikes"])
        elif style == "Opportunity Throw":
            verb = _pool_choice(THROW_HIT_VERBS)
        else:
            verb_pool = HIT_VERBS.get(weapon_category, HIT_VERBS["Oddball"])
            verb = _pool_choice(verb_pool)
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
    
    return [_pool_choice(pools), secondary.get(location, "The pain is debilitating!")]


# ---------------------------------------------------------------------------
# DAMAGE DESCRIPTION LINES
# ---------------------------------------------------------------------------

DAMAGE_LINES: dict[str, dict[str, list[str]]] = {
    "Slashing": {
        "Heavy": [
            "   The blade carves a horrific canyon through the flesh!",
            "   The cut flays the flesh open!",
            "   Blood sheets from a terrible gash!",
            "   The edge cleaves deep through the muscle!",
            "   A ghastly wound gapes wide!",
            "   The steel shears through the sinew!",
            "   A massive slash tears the flesh apart!",
            "   Blood sprays from the opened flesh!",
            "   The blade hews a ragged chasm!",
            "   A devastating cut lays the body open!",
            "   The edge slices through to the bone!",
            "   Blood erupts from the deep slash!",
            "   A terrible flap of skin is laid open!",
            "   The blade opens a gaping, ragged wound!",
            "   Crimson fountains from the cut!",
            "   The slash nearly parts the flesh in two!",
            "   A ruinous cut is torn through the body!",
            "   The steel leaves a wound that will not close!",
            "   A cut so deep it lays the bone bare!",
            "   A horrific slash opens the flesh to the air!",
        ],
        "Medium": [
            "   A deep gash is carved into the flesh!",
            "   The blade opens a long, bleeding wound!",
            "   Blood pours from a deep cut!",
            "   The edge cuts deep into the muscle!",
            "   A long laceration is laid open!",
            "   The steel slices a deep channel!",
            "   The slash tears a wide, bleeding gash!",
            "   A deep cut runs red!",
            "   The blade bites deep into the flesh!",
            "   Blood streams from the open wound!",
            "   A heavy slash opens the flesh wide!",
            "   The edge carves a deep furrow!",
            "   A wide gash is torn open!",
            "   The blade leaves a deep, ragged cut!",
            "   Crimson pours from the slash!",
            "   A long cut is opened to the muscle!",
            "   The slash rips deep into the flesh!",
            "   A deep wound gapes open!",
        ],
        "Graze": [
            "   The blade glances away!",
            "   The slash is barely felt!",
            "   The slash lands at a poor angle!",
            "   The cut is hardly noticed!",
            "   The edge dulls against the skin!",
            "   A pale line is all the edge leaves!",
            "   The blade rides across the skin!",
            "   A weak slash goes almost unnoticed!",
            "   The edge lacks the force to cut!",
            "   The slash is merely an annoyance!",
            "   The blade drags harmlessly across the skin!",
            "   A flat-edged slash lands!",
            "   The cut is no deeper than a thread!",
            "   The blade slips off the skin!",
            "   The slash lands with little force!",
            "   The edge leaves hardly a mark!",
        ],
        "Superficial": [
            "   A thin scratch is drawn across the skin!",
            "   The blade skims the surface!",
            "   A hairline cut beads with red!",
            "   The edge scrapes the skin!",
            "   A faint red line is left behind!",
            "   The steel barely breaks the skin!",
            "   A small nick is cut into the flesh!",
            "   The blade grazes the surface!",
            "   A shallow scratch weeps a few drops!",
            "   The edge leaves a trace of red!",
            "   A surface cut is scored in the skin!",
            "   The blade kisses the flesh!",
            "   A fine line of blood is drawn!",
            "   The edge catches the skin!",
            "   A small cut beads red!",
            "   The blade leaves a slight mark!",
        ],
        "Light": [
            "   A gash is opened in the flesh!",
            "   The blade parts the skin!",
            "   Blood runs from a fresh cut!",
            "   A clean slash is laid across the flesh!",
            "   The edge bites into the skin!",
            "   A bleeding cut is carved open!",
            "   The steel opens a short gash!",
            "   Crimson trails from the open cut!",
            "   The blade carves a shallow gash!",
            "   A stinging slash opens the flesh!",
            "   The edge cuts a clean line through the skin!",
            "   A narrow gash weeps blood!",
            "   The blade splits the skin!",
            "   A shallow gash is torn in the flesh!",
            "   The slash leaves a ragged cut!",
            "   A red seam is opened in the flesh!",
        ],
    },
    "Piercing": {
        "Heavy": [
            "   The point drives through the flesh with terrible force!",
            "   The weapon punches clean through!",
            "   A horrific hole is torn through the body!",
            "   The point finds something vital!",
            "   Blood gushes from the deep puncture!",
            "   The thrust impales the target!",
            "   A gaping wound is left where the weapon withdraws!",
            "   The weapon skewers the body!",
            "   Blood erupts from the stab!",
            "   The point tears a ragged channel through the flesh!",
            "   The thrust runs the target through!",
            "   A terrible puncture wound pours blood!",
            "   The point sinks in with a sickening wet crunch!",
            "   The steel bores a ghastly hole!",
            "   The weapon is torn free from a gushing wound!",
            "   The thrust drives in with bone-splitting force!",
            "   The point drives deep enough to grate on bone!",
            "   A ruinous hole is opened in the body!",
            "   The stab leaves a wound that gushes!",
            "   The steel punches through with horrific ease!",
        ],
        "Medium": [
            "   The point drives deep into the flesh!",
            "   A deep puncture wound is opened!",
            "   Blood pours from the stab wound!",
            "   The steel sinks in deep!",
            "   A deep hole is punched into the flesh!",
            "   The thrust drives a bleeding channel!",
            "   The point plunges into the muscle!",
            "   Blood streams from the puncture!",
            "   A deep stab wound runs red!",
            "   The tip bores deep into the flesh!",
            "   The thrust punches a ragged hole!",
            "   A wide puncture is torn open!",
            "   The point sinks deep with a wet sound!",
            "   Crimson pours from the stab!",
            "   The weapon is driven deep into the flesh!",
            "   A deep wound is punched into the body!",
            "   The point drives in with real force!",
            "   The thrust leaves a weeping hole!",
        ],
        "Graze": [
            "   The point glances away!",
            "   The tip skids off the skin!",
            "   The thrust lands at a poor angle!",
            "   The thrust is hardly noticed!",
            "   The thrust lacks the force to pierce!",
            "   The tip leaves hardly a dimple!",
            "   The point barely touches the flesh!",
            "   A weak thrust goes almost unnoticed!",
            "   The thrust is merely an annoyance!",
            "   The point jabs the skin!",
            "   The tip taps the skin!",
            "   The thrust glances off with little force!",
            "   The point fails to find purchase!",
            "   The thrust dies against the skin!",
            "   A feeble stab lands!",
            "   The tip leaves only a red dot!",
        ],
        "Superficial": [
            "   The point scratches the skin!",
            "   A pinprick of red wells up!",
            "   The tip barely breaks the surface!",
            "   A tiny puncture is left behind!",
            "   The point grazes the flesh!",
            "   A small prick beads with blood!",
            "   The tip nicks the skin!",
            "   A shallow prick is left in the flesh!",
            "   The point skids across the surface!",
            "   A few drops of blood well from the puncture!",
            "   The tip leaves a pinhole of red!",
            "   A slight puncture marks the skin!",
            "   The point snags the skin!",
            "   A faint stab mark is left behind!",
            "   The tip pricks a drop of blood!",
            "   The thrust scrapes the surface!",
        ],
        "Light": [
            "   The point punches into the flesh!",
            "   A puncture wound is opened!",
            "   Blood runs from a fresh puncture!",
            "   The tip sinks into the flesh!",
            "   A narrow wound is driven into the flesh!",
            "   A bleeding hole is punched in the skin!",
            "   The thrust opens a shallow wound!",
            "   The steel pierces the flesh!",
            "   A stab wound weeps blood!",
            "   The point drives a short way in!",
            "   A neat puncture is left bleeding!",
            "   The tip opens a small, bleeding hole!",
            "   A shallow stab wound is opened!",
            "   Crimson wells from the stab!",
            "   The thrust leaves a bleeding puncture!",
            "   The point bites into the flesh!",
        ],
    },
    "Bludgeoning": {
        "Heavy": [
            "   The blow lands with bone-shattering force!",
            "   A sickening crunch echoes as bone breaks!",
            "   The impact caves in the flesh!",
            "   Bone gives way with a horrible crack!",
            "   A devastating smash pulps the flesh!",
            "   The hit lands like a falling anvil!",
            "   The target is smashed backward by the force!",
            "   The blow turns the flesh to bloody ruin!",
            "   The impact rattles the whole skeleton!",
            "   A terrible crunch echoes across the arena!",
            "   The weapon smashes through with unstoppable weight!",
            "   Bone splinters under the blow!",
            "   The strike shatters bone with a wet crack!",
            "   The impact leaves the target broken!",
            "   A catastrophic blow lands!",
            "   The blow pulverizes the flesh!",
            "   The target is hurled backwards from the impact!",
            "   Something gives way with a sickening snap!",
            "   Blood bursts from the mangled flesh!",
            "   The blow lands with a sound like splitting timber!",
        ],
        "Medium": [
            "   The blow lands with a heavy crunch!",
            "   A deep bruise blackens the flesh!",
            "   The blow knocks the wind out!",
            "   The weapon crashes into the body!",
            "   Something cracks under the blow!",
            "   The strike staggers the target!",
            "   A crushing blow is struck!",
            "   The impact splits the skin open!",
            "   The blow pulps the flesh!",
            "   A heavy thud echoes across the arena!",
            "   The weapon drives into the body with punishing weight!",
            "   Flesh is crushed under the blow!",
            "   A sickening thud is heard!",
            "   The impact swells the flesh black!",
            "   The blow sends the target reeling!",
            "   The blow hammers the body!",
            "   The impact bursts the skin open!",
            "   A brutal blow crunches home!",
        ],
        "Graze": [
            "   The blow lands with little force!",
            "   A weak thump lands on the flesh!",
            "   The weapon taps the body!",
            "   The strike is merely an annoyance!",
            "   The blow lands at an ineffective angle!",
            "   The weapon bounces off the body!",
            "   A glancing tap lands!",
            "   The impact is barely felt!",
            "   The strike has no weight behind it!",
            "   A feeble blow lands!",
            "   The weapon brushes the body!",
            "   The blow glances away!",
            "   A soft knock lands on the flesh!",
            "   The strike lacks any real power!",
            "   The strike is hardly noticed!",
            "   The impact is hardly worth the swing!",
        ],
        "Superficial": [
            "   A dull thump lands on the flesh!",
            "   The blow leaves a faint bruise!",
            "   The weapon glances off the body!",
            "   A slight bruise begins to show!",
            "   The impact stings the flesh!",
            "   The blow barely lands!",
            "   A soft thud echoes!",
            "   The strike jostles the body!",
            "   A red mark is left by the blow!",
            "   The weapon clips the flesh!",
            "   A glancing thump lands!",
            "   The blow thuds against the body!",
            "   A small welt rises on the flesh!",
            "   A brief, dull impact lands!",
            "   The weapon scuffs the skin!",
            "   A mild ache follows the blow!",
        ],
        "Light": [
            "   A heavy bruise forms!",
            "   The blow thuds home with real weight!",
            "   A solid thump lands on the flesh!",
            "   The weapon batters the flesh!",
            "   A dark bruise spreads under the skin!",
            "   The impact rocks the body!",
            "   The blow leaves the flesh swollen!",
            "   A hard blow lands!",
            "   The weapon hammers the flesh!",
            "   A deep ache follows the thud!",
            "   The strike raises a dark welt!",
            "   The impact jars the body!",
            "   The impact splits the skin!",
            "   The weapon thuds into the body!",
            "   A deep mark is left by the blow!",
            "   The blow lands with a meaty thud!",
        ],
    },
    "Cleaving": {
        "Heavy": [
            "   The chop cleaves deep through the flesh!",
            "   The edge hews a horrific wound!",
            "   A massive chop splits the body open!",
            "   Bone breaks under the cleaving edge!",
            "   The blow hacks a ragged canyon through the flesh!",
            "   Blood sheets from the hacked wound!",
            "   The edge bites through to the bone!",
            "   A devastating chop tears the flesh away!",
            "   The chop splits the flesh with one terrible stroke!",
            "   The blow hews through the bone!",
            "   A ghastly wound is chopped open!",
            "   The edge cleaves a gaping chasm!",
            "   Blood erupts from the chopped wound!",
            "   The chop nearly splits the body!",
            "   A terrible cleave lays the flesh open!",
            "   The edge tears a ruinous wound!",
            "   The blow hacks deep into the bone!",
            "   The chop leaves a ragged, gushing wound!",
            "   The cleaving edge rips through the flesh!",
            "   A massive wound is hacked open!",
        ],
        "Medium": [
            "   A deep gash is hacked open!",
            "   The edge bites deep into the flesh!",
            "   Blood pours from the hacked wound!",
            "   The chop tears a wide wound!",
            "   A heavy chop splits the flesh!",
            "   The edge chops a deep channel!",
            "   A ragged wound is hacked deep!",
            "   The blow hacks into the muscle!",
            "   Crimson streams from the chop!",
            "   The chop opens a long, ugly wound!",
            "   A brutal chop bites deep!",
            "   The edge cleaves a bleeding furrow!",
            "   The blow hacks the flesh open!",
            "   A deep, ragged cut is chopped open!",
            "   The chop lands with a wet crunch!",
            "   Blood runs freely from the cleaving wound!",
            "   The edge tears deep into the flesh!",
            "   A wide wound is hacked open!",
        ],
        "Graze": [
            "   The chop glances away!",
            "   The chop is hardly noticed!",
            "   The blow lands at a poor angle!",
            "   A weak chop goes almost unnoticed!",
            "   The chop is merely an annoyance!",
            "   The edge bounces off the skin!",
            "   The chop lacks the force to bite!",
            "   The blow lands flat!",
            "   The edge nudges the skin!",
            "   A feeble hack lands!",
            "   The chop drags across the skin!",
            "   The blow lands with little force!",
            "   The edge fails to bite!",
            "   A clumsy chop glances off!",
            "   The chop thuds against the skin!",
            "   The chop leaves hardly a mark!",
        ],
        "Superficial": [
            "   A scraping chop skims the skin!",
            "   The edge glances off the flesh!",
            "   A rough nick is chipped in the skin!",
            "   The chop barely bites!",
            "   A ragged scratch is left behind!",
            "   The edge scuffs the flesh!",
            "   A small notch is scored in the skin!",
            "   The blow skids off the surface!",
            "   A crude scrape is left by the chop!",
            "   The edge clips the skin!",
            "   A shallow chop leaves a ragged mark!",
            "   The blow catches a sliver of skin!",
            "   A glancing hack scrapes the surface!",
            "   The chop leaves a rough red scrape!",
            "   The edge bites the surface!",
            "   A few drops of blood well from the nick!",
        ],
        "Light": [
            "   A ragged gash is hacked open!",
            "   The edge chops into the flesh!",
            "   A crude wound is hacked in the skin!",
            "   The chop tears the skin open!",
            "   Blood runs from the hacked wound!",
            "   The blow hacks a shallow gash!",
            "   A rough cut is chopped into the flesh!",
            "   The edge bites into the flesh!",
            "   A messy gash is left by the chop!",
            "   The chop splits the skin!",
            "   A ragged wound weeps blood!",
            "   The blow chops a short, ugly gash!",
            "   The cleaving edge opens the flesh!",
            "   A hacked gash bleeds freely!",
            "   The chop lays a ragged cut in the flesh!",
            "   A rough wound is torn open!",
        ],
    },
    "Generic": {
        "Heavy": [
            "   A horrific wound is torn open!",
            "   The blow lands with devastating force!",
            "   Blood erupts from the wound!",
            "   The strike tears deep into the flesh!",
            "   A terrible wound is left by the attack!",
            "   The hit lands with bone-breaking force!",
            "   Blood sprays from the impact!",
            "   A ghastly injury is opened!",
            "   The weapon opens the flesh to the bone!",
            "   The blow leaves a gaping wound!",
            "   Blood pours freely from the ruined flesh!",
            "   The attack tears a massive wound!",
            "   The strike nearly folds the target in half!",
            "   A ruinous wound is carved into the body!",
            "   The hit lands with overwhelming force!",
            "   The weapon leaves the flesh in tatters!",
            "   A gushing wound is left behind!",
            "   The strike savagely tears open the flesh!",
            "   Blood fountains from the wound!",
            "   A devastating blow lands!",
        ],
        "Medium": [
            "   A deep wound is opened!",
            "   The blow tears the flesh open!",
            "   Blood pours from the wound!",
            "   The strike bites deep into the flesh!",
            "   A serious wound is left by the attack!",
            "   The hit opens a bleeding wound!",
            "   Crimson streams from the injury!",
            "   The weapon cuts deep!",
            "   A deep, ragged wound is torn open!",
            "   The strike lands with punishing force!",
            "   The blow opens a wide wound!",
            "   Blood runs freely from the wound!",
            "   A deep wound gapes from the attack!",
            "   The weapon drives deep into the flesh!",
            "   A painful, bleeding wound is left behind!",
            "   The strike rocks the target!",
            "   The hit leaves the flesh torn!",
            "   A heavy blow opens the flesh!",
        ],
        "Graze": [
            "   The blow lands with little force!",
            "   The strike glances away!",
            "   The attack is merely an annoyance!",
            "   The blow lands at an ineffective angle!",
            "   The hit stings for a moment!",
            "   A weak blow goes almost unnoticed!",
            "   The strike leaves hardly a mark!",
            "   The attack lacks the force to wound!",
            "   The weapon barely touches the target!",
            "   A feeble strike lands!",
            "   The strike is hardly worth the effort!",
            "   The hit has no bite to it!",
            "   The blow is barely noticed!",
            "   The attack is scarcely felt!",
            "   A harmless blow lands!",
            "   The strike fails to wound!",
        ],
        "Superficial": [
            "   A slight wound results!",
            "   The blow scratches the skin!",
            "   The strike barely marks the flesh!",
            "   A faint mark is left behind!",
            "   The attack grazes the surface!",
            "   A few drops of blood are drawn!",
            "   The hit scrapes the skin!",
            "   A small scrape results!",
            "   The strike glances off the flesh!",
            "   A trace of red marks the skin!",
            "   The blow leaves a slight mark!",
            "   The weapon nicks the surface!",
            "   A shallow scratch is left by the attack!",
            "   The strike skims the skin!",
            "   A tiny wound is opened!",
            "   The attack barely draws blood!",
        ],
        "Light": [
            "   A wound is opened!",
            "   The blow opens the flesh!",
            "   A bleeding wound is left by the attack!",
            "   The strike splits the skin!",
            "   Blood runs from the fresh wound!",
            "   The hit leaves a bleeding gash!",
            "   The weapon opens a shallow wound!",
            "   A noticeable wound is left behind!",
            "   The strike tears the skin!",
            "   A shallow wound weeps red!",
            "   The blow leaves its mark in red!",
            "   A bleeding mark is left by the hit!",
            "   The attack draws a steady trickle of blood!",
            "   A rough wound is opened in the flesh!",
            "   A stinging wound is left behind!",
            "   The weapon bites into the flesh!",
        ],
    },
    "Unarmed": {
        "Heavy": [
            "   The strike tears a horrific wound!",
            "   Flesh is ripped open by the blow!",
            "   Blood erupts from the torn flesh!",
            "   The target reels from a devastating strike!",
            "   The attack tears deep into the flesh!",
            "   A ghastly wound is torn open!",
            "   Bone cracks under the strike!",
            "   The blow lands with terrible force!",
            "   Blood sprays from the ragged wound!",
            "   The strike leaves the flesh in ribbons!",
            "   A massive blow staggers the target!",
            "   The attack rips the skin away!",
            "   Deep furrows are torn into the body!",
            "   The impact drives the target back!",
            "   The strike tears a wide, ragged wound!",
            "   Blood streams from the ruined flesh!",
            "   The blow lands with bone-breaking force!",
            "   A terrible strike leaves the target broken!",
            "   The attack rends the flesh!",
            "   The strike lands like a falling boulder!",
        ],
        "Medium": [
            "   The strike tears the flesh open!",
            "   Blood pours from the torn flesh!",
            "   A heavy blow lands hard!",
            "   The attack rips a deep wound!",
            "   The target staggers from the blow!",
            "   A hard strike splits the skin open!",
            "   Blood streams from the wound!",
            "   The strike leaves deep furrows!",
            "   The blow drives the breath out!",
            "   A brutal strike lands!",
            "   The strike sends the target reeling!",
            "   The strike opens a bleeding wound!",
            "   The attack tears a long wound!",
            "   The impact leaves a deep bruise!",
            "   A punishing strike lands!",
            "   The blow tears the skin open!",
            "   Crimson runs from the torn flesh!",
            "   The strike lands with crushing force!",
        ],
        "Graze": [
            "   The blow lands with little force!",
            "   The strike glances away!",
            "   The attack is merely an annoyance!",
            "   The blow lands at a poor angle!",
            "   A weak strike goes almost unnoticed!",
            "   The hit is barely noticed!",
            "   The strike has no weight behind it!",
            "   A feeble blow lands!",
            "   The attack jostles the body!",
            "   The strike brushes the body!",
            "   The blow stings for a moment!",
            "   A glancing hit leaves no mark!",
            "   The blow slides off the target!",
            "   The strike is hardly worth the swing!",
            "   The attack is scarcely felt!",
            "   A harmless hit lands!",
        ],
        "Superficial": [
            "   The blow scuffs the skin!",
            "   A faint red mark is left behind!",
            "   The strike barely marks the flesh!",
            "   The attack scrapes the surface!",
            "   A slight bruise begins to show!",
            "   The blow glances off the body!",
            "   A shallow scrape is left by the strike!",
            "   The strike stings the flesh!",
            "   A trace of blood marks the skin!",
            "   The hit lands without much weight!",
            "   A glancing blow scratches the skin!",
            "   The attack leaves a red welt!",
            "   The blow barely breaks the skin!",
            "   A small scrape results!",
            "   The strike skims the flesh!",
            "   A mild bruise forms!",
        ],
        "Light": [
            "   The blow splits the skin!",
            "   A hard strike tears the skin!",
            "   The blow bruises the flesh!",
            "   A hard strike leaves a dark bruise!",
            "   The strike leaves shallow furrows!",
            "   The attack bloodies the target!",
            "   A hard strike leaves the skin torn!",
            "   The blow lands with real weight!",
            "   A bleeding scrape is torn in the skin!",
            "   The strike draws blood!",
            "   The blow rattles the body!",
            "   A hard hit bruises the flesh beneath!",
            "   The strike rips the skin!",
            "   A stinging blow leaves the skin raw!",
            "   The hit lands hard enough to bruise!",
            "   Blood wells where the strike lands!",
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
    "Stave":          "Bludgeoning",
    "Oddball":        "Generic",
}

# ---------------------------------------------------------------------------
# SOUL SPIRE (undead) DAMAGE LINES
# ---------------------------------------------------------------------------
# In the Soul Spire the combatants are the reanimated dead, so wounds read very
# differently - no fresh blood or pain, but rotted flesh, dried gore, grave-dust
# and exposed bone. Keyed by severity only (weapon type doesn't matter much when
# the "flesh" is already a corpse's). Used by damage_line(undead=True).
SOUL_SPIRE_DAMAGE_LINES: dict[str, dict[str, list[str]]] = {
    "Slashing": {
        "Heavy": [
            "   The blade opens the carcass wide, spilling congealed gore that no longer flows!",
            "   Dried sinew snaps under the edge and the limb hangs by threads, yet the dead thing fights on!",
            "   Half the shoulder is sheared away, exposing the dry workings of the joint!",
            "   The edge carves through decayed muscle and bares grey bone beneath!",
        ],
        "Medium": [
            "   The edge gouges out a strip of decayed flesh that sloughs away wetly!",
            "   Rotten muscle parts under the blade, weeping thin black fluid!",
            "   The cut opens the corpse-flesh, releasing a dry, graveyard reek!",
            "   Desiccated skin splits wide, baring the grey muscle beneath!",
        ],
        "Light": [
            "   The edge splits the dried flesh, and a trickle of black ichor seeps out!",
            "   A flap of decayed skin peels back from the cut!",
            "   The slash leaves a gash that weeps dark, sluggish rot!",
            "   A sliver of rotted tissue is shaved away by the edge!",
        ],
        "Superficial": [
            "   The edge flakes away a crust of dried, blackened flesh!",
            "   A shallow furrow is scratched into the leathery, dead skin!",
            "   Only a thin curl of rotted skin is shaved away!",
            "   The slash disturbs the rot but does little more!",
        ],
        "Graze": [
            "   The edge barely scuffs the dead, leathery hide!",
            "   The blade skims the corpse-flesh, leaving only a pale scratch!",
            "   A few flakes of dried flesh drift loose and settle on the sand!",
            "   The dead thing does not so much as flinch at the glancing cut!",
        ],
    },
    "Cleaving": {
        "Heavy": [
            "   The heavy edge chops through rotted muscle and bone, and the limb nearly falls away!",
            "   A great slab of decayed flesh is hacked away, baring grey bone beneath!",
            "   The cleaving blow splits the corpse open, spilling congealed gore that no longer flows!",
            "   Dried sinew snaps and the limb hangs by threads, yet the dead thing fights on!",
        ],
        "Medium": [
            "   The weapon chops a deep gouge from the decayed flesh, which sloughs away wetly!",
            "   Rotten muscle parts under the heavy edge, weeping thin black fluid!",
            "   The chop tears open the corpse-flesh, releasing a dry, graveyard reek!",
            "   A clot of dead, blackened gore is hacked free by the blow!",
        ],
        "Light": [
            "   The edge bites the dried flesh, and a trickle of black ichor seeps out!",
            "   A flap of decayed skin is chopped loose from the wound!",
            "   The blow leaves a rough gash that weeps dark, sluggish rot!",
            "   A sliver of rotted tissue is hacked away!",
        ],
        "Superficial": [
            "   The edge flakes away a crust of dried, blackened flesh!",
            "   A shallow notch is chopped into the leathery, dead skin!",
            "   Only a thin curl of rotted skin is shaved away!",
            "   The glancing chop disturbs the rot but does little more!",
        ],
        "Graze": [
            "   The edge barely scuffs the dead, leathery hide!",
            "   A few flakes of dried flesh drift loose and settle on the sand!",
            "   The weapon glances off bone with a dull, hollow clack!",
            "   The dead thing does not so much as flinch at the glancing blow!",
        ],
    },
    "Piercing": {
        "Heavy": [
            "   The point punches clean through rotted meat and out the other side, loosing a puff of grave-dust!",
            "   The thrust sinks deep into the carcass, and black ichor oozes thickly from the hole!",
            "   The point drives through dried sinew and pins the dead thing where it stands!",
            "   A deep puncture opens in the corpse, though no blood follows the weapon out!",
        ],
        "Medium": [
            "   The point sinks into decayed flesh and withdraws trailing thin black fluid!",
            "   The thrust finds rotten muscle and leaves a ragged hole weeping dark rot!",
            "   A puncture opens in the corpse-flesh, releasing a dry, graveyard reek!",
            "   The point bites into desiccated meat with a sickening crunch!",
        ],
        "Light": [
            "   The point pricks the dried flesh, and a trickle of black ichor seeps out!",
            "   A small puncture opens in the decayed skin and weeps dark rot!",
            "   The thrust leaves a narrow hole in the dead meat!",
            "   The point slips into withered flesh, puffing loose a little grave-dust!",
        ],
        "Superficial": [
            "   The point scratches a shallow pit into the leathery, dead skin!",
            "   The thrust barely breaks the crust of dried, blackened flesh!",
            "   A small dimple of rot marks where the point landed!",
            "   The point disturbs the rot but does little more!",
        ],
        "Graze": [
            "   The point skids across the dead, leathery hide!",
            "   The thrust glances off bone with a dull, hollow clack!",
            "   The point scrapes the corpse-flesh, leaving only a pale scratch!",
            "   The dead thing does not so much as flinch at the glancing thrust!",
        ],
    },
    "Bludgeoning": {
        "Heavy": [
            "   The blow caves in rotted muscle, and black ichor oozes thickly from the ruin!",
            "   The strike shatters the corpse's ribs, loosing a puff of grave-dust!",
            "   Bone cracks and splinters, but no cry of pain comes from the dead jaws!",
            "   The impact bursts long-dead flesh apart in a spray of dust and blackened rot!",
        ],
        "Medium": [
            "   The blow caves in a patch of rot, and old gore crumbles away!",
            "   Desiccated flesh is crushed flat, weeping thin black fluid!",
            "   The impact splits the corpse-flesh, releasing a dry, graveyard reek!",
            "   Brittle bone gives way with a sickening crunch, though the dead thing feels nothing!",
        ],
        "Light": [
            "   The blow dents the dried flesh, and a trickle of black ichor seeps out!",
            "   Decayed skin splits over a crushed patch of meat!",
            "   The strike leaves a dark bruise of rot where it lands!",
            "   Withered flesh is mashed flat, puffing loose a little grave-dust!",
        ],
        "Superficial": [
            "   The blow flakes away a crust of dried, blackened flesh!",
            "   A shallow dent is pressed into the leathery, dead skin!",
            "   The strike scuffs the corpse-flesh, loosing a wisp of dust!",
            "   The impact disturbs the rot but does little more!",
        ],
        "Graze": [
            "   The blow barely scuffs the dead, leathery hide!",
            "   A few flakes of dried flesh drift loose and settle on the sand!",
            "   The strike glances off bone with a dull, hollow clack!",
            "   The dead thing does not so much as flinch at the glancing blow!",
        ],
    },
    "Generic": {
        "Heavy": [
            "   A great slab of decayed flesh is torn away, baring grey bone beneath!",
            "   The blow ruins rotted muscle, and black ichor oozes thickly from the wreck!",
            "   A fist-sized chunk of putrid meat is ripped loose and falls to the sand!",
            "   Bone cracks and splinters, but no cry of pain comes from the dead jaws!",
        ],
        "Medium": [
            "   Rotten muscle gives way under the blow, weeping thin black fluid!",
            "   A clot of dead, blackened gore is knocked free by the impact!",
            "   Desiccated skin splits wide, baring the grey muscle beneath!",
            "   Sinew and withered flesh give way, though the dead thing feels nothing!",
        ],
        "Light": [
            "   The strike splits the dried flesh, and a trickle of black ichor seeps out!",
            "   A flap of decayed skin peels back from the wound!",
            "   The blow leaves a mark that weeps dark, sluggish rot!",
            "   Withered flesh tears, puffing loose a little grave-dust!",
        ],
        "Superficial": [
            "   The blow flakes away a crust of dried, blackened flesh!",
            "   A shallow mark is scratched into the leathery, dead skin!",
            "   The strike scuffs the corpse-flesh, loosing a wisp of dust!",
            "   The hit marks the grey hide but barely parts it!",
        ],
        "Graze": [
            "   The blow barely scuffs the dead, leathery hide!",
            "   A few flakes of dried flesh drift loose and settle on the sand!",
            "   The strike glances off bone with a dull, hollow clack!",
            "   The dead thing does not so much as flinch at the glancing hit!",
        ],
    },
}
SOUL_SPIRE_DAMAGE_LINES["Unarmed"] = SOUL_SPIRE_DAMAGE_LINES["Bludgeoning"]

# Soul Spire counterpart to the living bleed tick. The dead do not bleed - their
# open wounds fester and slough. {name} is filled in. Never shows a damage number.
SOUL_SPIRE_BLEED_LINES: list[str] = [
    "   {name}'s open wounds weep black ichor!",
    "   Rot spreads through {name}'s torn flesh!",
    "   {name}'s ragged wounds slough away rotten meat!",
    "   Grave-rot festers in {name}'s gashes!",
    "   Dark ichor drains from {name}'s ruptured flesh!",
    "   {name}'s decay deepens around the open wound!",
    "   Withered flesh crumbles from {name}'s wounds!",
]


def _refine_category(weapon_category: str, weapon_name: Optional[str]) -> str:
    """Pick the narrative category that really matches the weapon in hand.

    Weapon categories are broad (a dagger is "Sword/Knife", a pick is "Axe/Pick",
    a halberd is "Polearm/Spear"), so the wording is corrected from the weapon
    itself: thrusting weapons read as piercing, bladed polearms as axes, and
    staves as blunt.
    """
    if not weapon_name:
        return weapon_category
    key = re.sub(r"[^a-z]+", "_", weapon_name.lower()).strip("_")
    kind = _WEAPON_DAMAGE_TYPES.get(key)
    if kind is None:
        return weapon_category
    if kind == "piercing" and weapon_category in ("Sword/Knife", "Axe/Pick", "Polearm/Spear"):
        return "Polearm/Spear"
    if kind == "slashing" and weapon_category == "Polearm/Spear":
        return "Axe/Pick"
    if kind == "crushing" and weapon_category == "Stave":
        return "Hammer/Mace"
    return weapon_category


def damage_line(damage: int, max_hp: int, weapon_category: str = "Oddball",
                is_claw_attack: bool = False, attack_type: Optional[str] = None,
                undead: bool = False, weapon_name: Optional[str] = None) -> str:
    """
    Return a damage description line based on damage severity and weapon type.

    Args:
        damage: Damage dealt
        max_hp: Target's max HP (used for context, not severity calculation)
        weapon_category: Weapon category (Oddball, Sword/Knife, etc.)
        is_claw_attack: Deprecated; use attack_type instead
        attack_type: Type of unarmed attack ("claw", "kick", "tail", or None for weapon attacks)
        undead: True for Soul Spire fights; swaps the living-flesh/blood wound
                description for a decayed-corpse one (see SOUL_SPIRE_DAMAGE_LINES).
    """
    if   damage <= 3:  severity = "Graze"
    elif damage <= 9:  severity = "Superficial"
    elif damage <= 18: severity = "Light"
    elif damage <= 33: severity = "Medium"
    else:             severity = "Heavy"

    weapon_category = _refine_category(weapon_category, weapon_name)

    # For Open Hand attacks, use Unarmed descriptions based on attack type
    if weapon_category == "Oddball" and (attack_type or is_claw_attack):
        dmg_type = "Unarmed"
    else:
        dmg_type = _WEAPON_DAMAGE_TYPE.get(weapon_category, "Generic")

    # Soul Spire combatants are reanimated dead - corpse-themed wound lines that
    # still match the kind of weapon (edge, point or blunt).
    if undead:
        return _pool_choice(SOUL_SPIRE_DAMAGE_LINES.get(dmg_type, SOUL_SPIRE_DAMAGE_LINES["Generic"])[severity])

    pool = DAMAGE_LINES[dmg_type][severity]
    return _pool_choice(pool)


_LIVING_BLEED_LINES: list[str] = [
    "   Blood runs from the open wound!",
    "   {name} bleeds from the open wound!",
    "   Blood streams from {name}'s wound!",
    "   {name}'s wound weeps red!",
    "   Crimson trails down {name}!",
    "   Blood drips from {name}'s cut!",
    "   {name} leaves a trail of blood!",
    "   The open wound bleeds freely!",
    "   Blood seeps from {name}'s wound!",
    "   {name}'s wound runs red!",
    "   Blood spills from the cut!",
    "   {name} bleeds steadily!",
    "   Blood pours from {name}'s wound!",
    "   Blood patters onto the sand!",
    "   Blood darkens the sand beneath {name}!",
    "   {name}'s wound will not close!",
    "   Blood wells from the open wound!",
    "   A red stream flows from {name}'s wound!",
    "   Blood slicks {name}'s skin!",
    "   The wound spills blood onto the sand!",
    "   {name}'s blood marks the sand!",
    "   Blood trickles from the cut!",
    "   {name} bleeds from the slash!",
    "   Blood runs thick from {name}'s wound!",
    "   Blood leaks from {name}'s wound!",
    "   Crimson spills from the wound!",
    "   Blood streaks {name}'s skin!",
    "   Blood spatters from {name}'s wound!",
    "   {name}'s wound drips red!",
    "   Blood oozes from the cut!",
]


def bleed_tick_line(name: str, dmg: int, undead: bool = False) -> str:
    """
    One bleeding-damage tick line. Living warriors simply bleed; Soul Spire
    (undead) combatants fester and slough rotten flesh instead. Never shows the
    damage amount (we do not surface damage numbers to the player).
    """
    pool = SOUL_SPIRE_BLEED_LINES if undead else _LIVING_BLEED_LINES
    return _pool_choice(pool).format(name=name.upper())


# ---------------------------------------------------------------------------
# CROWD GORE LINES
# ---------------------------------------------------------------------------
# Crowd reactions to big hits, shown after the wound line. {n1} is the attacker,
# {n2} the defender. Living arenas only: the dead in the Soul Spire do not bleed.
CROWD_GORE_LINES: dict[str, list[str]] = {
    "Heavy": [
        "A fine spray of blood arcs over the front rows!",
        "Gore splatters the rail!",
        "A warm red mist drifts into the crowd!",
        "A crimson spatter strikes the arena wall!",
        "Blood rains down on the crowd!",
        "A sheet of gore sprays the front row!",
        "The nearest spectators are drenched in red!",
        "A spectator wipes warm blood from their face!",
        "Blood splashes across the stands!",
        "A spray of crimson arcs over the arena wall!",
        "The nearest seats are spattered with gore!",
        "Gore flecks the cheering crowd!",
        "A thick spatter of blood hits the barrier!",
        "The crowd roars as blood flies!",
    ],
    "Devastating": [
        "A torrent of blood sprays the front rows!",
        "Gore splatters the first row!",
        "A geyser of blood erupts over the rail!",
        "The crowd is painted red!",
        "Blood sprays across the stands like rain!",
        "A thick spatter drenches the nearest seats!",
        "A wave of crimson washes over the arena wall!",
        "The crowd shrieks in delight!",
        "Blood spews into the crowd!",
        "A torrent of gore sweeps the lower stands!",
        "The crowd erupts at the sight!",
        "A ribbon of blood arcs into the stands!",
        "Spectators recoil from the spray!",
        "The front row is soaked in blood!",
    ],
    "Killing": [
        "Silence falls over the arena as {n2} hits the ground!",
        "A jet of blood arcs over the front rows!",
        "{n2} collapses in a spreading pool of blood!",
        "{n2} lies twitching in a growing pool of gore!",
        "The crowd surges toward the rail!",
        "{n2}'s body hits the ground with a wet thud!",
        "A fine mist drifts into the stands!",
        "Blood spills over the arena wall into the crowd!",
        "Cheers erupt from the stands!",
        "{n1} stands over the fallen {n2}!",
        "The crowd howls with delight!",
        "The front row is showered in red!",
        "A hush falls before the crowd roars!",
        "{n2}'s blood spreads across the sand!",
    ],
}


def crowd_gore_line(kind: str, attacker_name: str, defender_name: str) -> str:
    """
    One crowd-reaction line for a big hit. kind is "Heavy", "Devastating" or "Killing".
    Returns the line with the same 3-space indent as the wound lines.
    """
    return "   " + _pool_choice(CROWD_GORE_LINES[kind]).format(n1=attacker_name, n2=defender_name)


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
        "{name} strikes with {his} stiletto's lethal point!",
        "{name}'s stiletto finds its target with deadly accuracy!",
        "{name} executes a precise thrust with {his} stiletto!",
        "With practiced grace {name} drives {his} stiletto deep!",
        "{name} slips past the guard and strikes with {his} stiletto!",
        "{name}'s stiletto sinks in as {he} exploits a weakness!",
        "{name} thrusts {his} stiletto with cold intent!",
        "The point of {name}'s stiletto seeks a vital area!",
        "{name} moves with {his} stiletto in a blur of steel!",
        "{name}'s stiletto punctures deeply under {his} expert hand!",
        "{name} delivers a killing strike with {his} stiletto!",
        "{name}'s stiletto flashes and finds blood!",
        "{name} works {his} stiletto with surgical skill!",
        "With fluid motion {name} drives {his} stiletto true!",
        "{name}'s stiletto proves why precision kills!",
        "{name} pierces defenses and reaches deep with {his} stiletto!",
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
        "{name} closes with {his} knife raised!",
        "{name}'s knife flashes in a deadly arc!",
        "{name} works {his} knife with brutal efficiency!",
        "In a flurry {name} strikes with {his} knife repeatedly!",
        "{name}'s knife finds openings that others miss!",
        "{name} drives {his} knife deep with savage intent!",
        "With each move {name}'s knife seeks vital flesh!",
        "{name} plunges {his} knife without hesitation!",
        "{name}'s knife dances through the defense!",
        "{name} twists {his} knife with vicious force!",
        "The knife in {name}'s hand becomes a blur!",
        "{name} slashes with {his} knife again and again!",
        "{name}'s knife finds and exploits every opening!",
        "{name} drives {his} knife upward with lethal aim!",
        "{name} works {his} knife into vulnerable areas!",
        "{name}'s knife strikes fast and draws blood!",
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
        "{name} lunges with {his} dagger extended!",
        "{name}'s dagger moves with fluid grace!",
        "{name} spins and drives {his} dagger true!",
        "{name}'s dagger sings as it finds its mark!",
        "{name} steps close and thrusts {his} dagger deep!",
        "In controlled bursts {name} strikes with {his} dagger!",
        "{name} uses {his} dagger to cut through defense!",
        "{name}'s dagger flashes at the perfect moment!",
        "{name} drives {his} dagger home with precision!",
        "{name} makes {his} dagger dance with masterful control!",
        "{name}'s dagger finds the weakness and exploits it!",
        "{name} delivers repeated strikes with {his} dagger!",
        "{name} twists {his} dagger with deadly skill!",
        "With {his} dagger raised {name} presses forward!",
        "{name}'s dagger punctures deeply and cleanly!",
        "{name} wields {his} dagger with expert technique!",
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
        "{name} lunges with {his} short sword extended!",
        "{name}'s short sword moves with fluid grace!",
        "{name} spins and drives {his} short sword true!",
        "{name}'s short sword sings as it finds its mark!",
        "{name} steps close and thrusts {his} short sword deep!",
        "In controlled bursts {name} strikes with {his} short sword!",
        "{name} uses {his} short sword to cut through defense!",
        "{name}'s short sword flashes at the perfect moment!",
        "{name} drives {his} short sword home with precision!",
        "{name} makes {his} short sword dance with masterful control!",
        "{name}'s short sword finds the weakness and exploits it!",
        "{name} delivers repeated strikes with {his} short sword!",
        "{name} twists {his} short sword with deadly skill!",
        "With {his} short sword raised {name} presses forward!",
        "{name}'s short sword punctures deeply and cleanly!",
        "{name} wields {his} short sword with expert technique!",
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
        "{name} extends {his} epee with perfect precision!",
        "{name}'s epee finds the gap with lightning speed!",
        "{name} probes with {his} epee for the opening!",
        "{name}'s epee flashes forward with lethal grace!",
        "{name} flicks {his} epee in a deadly strike!",
        "With elegant control {name} drives {his} epee home!",
        "{name}'s epee dances as {he} attacks!",
        "{name} makes {his} epee strike with surgical focus!",
        "{name} exploits every weakness with {his} epee!",
        "{name}'s slender epee finds its mark with precision!",
        "{name} thrusts {his} epee with aristocratic skill!",
        "{name}'s epee moves too fast to follow!",
        "{name} uses {his} epee to dissect the defense!",
        "The point of {name}'s epee is unstoppable!",
        "{name} draws blood with {his} epee with perfect form!",
        "{name}'s epee proves that finesse beats strength!",
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
        "{name} leaps and slashes with {his} scimitar!",
        "{name}'s scimitar arcs in a deadly crescent!",
        "{name} draws {his} scimitar in a flowing motion!",
        "With grace {name} carves with {his} scimitar!",
        "{name}'s curved blade flashes with lethal elegance!",
        "{name} spins and slashes with {his} scimitar!",
        "{name}'s scimitar sings through the air!",
        "{name} uses {his} scimitar to open a vicious wound!",
        "{name} delivers a savage strike with {his} scimitar!",
        "{name} brings {his} scimitar down in a powerful arc!",
        "{name}'s scimitar moves with fluid, flowing grace!",
        "{name} whirls {his} scimitar in a deadly dance!",
        "{name} slashes with {his} scimitar in a sweeping arc!",
        "{name}'s scimitar finds its path with precision!",
        "{name} wields {his} scimitar with devastating elegance!",
        "{name}'s curved blade cuts through steel and flesh alike!",
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
        "{name} steps forward with {his} longsword raised!",
        "{name}'s longsword flashes in a powerful arc!",
        "{name} swings {his} longsword with clean precision!",
        "With measured power {name} wields {his} longsword!",
        "{name} uses {his} longsword to cut through defense!",
        "{name}'s longsword strikes true with expert timing!",
        "{name} drives {his} longsword forward with lethal intent!",
        "{name} makes {his} longsword sing with a disciplined strike!",
        "{name} delivers a masterful thrust with {his} longsword!",
        "{name}'s longsword finds its mark with precision!",
        "{name} hefts {his} longsword and attacks with authority!",
        "{name}'s longsword moves with controlled power!",
        "{name} thrusts {his} longsword deep and true!",
        "{name} wields {his} longsword with commanding skill!",
        "{name}'s longsword exploits every opening!",
        "{name} brings {his} longsword down with disciplined force!",
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
        "{name} hefts {his} broadsword and strikes hard!",
        "{name} delivers a heavy cut with {his} broadsword!",
        "{name} carries {his} broadsword with straightforward power!",
        "{name}'s broadsword does exactly what is needed!",
        "{name}'s broadsword hacks forward with confidence!",
        "With practiced swings {name} makes {his} broadsword bite deep!",
        "{name}'s broadsword strikes with crushing weight!",
        "{name} brings {his} broadsword down with no wasted motion!",
        "{name} uses {his} broadsword to powerful effect!",
        "{name} drives {his} broadsword home with brutal force!",
        "{name}'s reliable broadsword finds its mark!",
        "{name} wields {his} broadsword with straightforward efficiency!",
        "{name} hacks with {his} broadsword like a woodsman's tool!",
        "{name}'s broadsword is honest and devastating!",
        "{name} makes {his} broadsword work with practical skill!",
        "{name}'s broadsword proves that strength and simplicity win!",
    ],
    "Bastard Sword": [
        "{name} grips the bastard sword and cleaves downward with power!",
        "The bastard sword descends like judgment as {name} strikes!",
        "{name} swings the bastard sword in a devastating overhead blow!",
        "With expert control {name} delivers a crushing strike with the bastard sword!",
        "{name} uses the bastard sword to cut a wide, brutal path!",
        "The bastard sword flashes as {name} attacks with both speed and power!",
        "{name} drives the bastard sword home with tremendous force!",
        "In a powerful two-handed strike {name} makes the bastard sword sing!",
        "{name} adapts grip and delivers a flexible, lethal blow!",
        "The bastard sword finds the perfect balance of reach and power in {name}'s hands!",
        "{name} raises {his} bastard sword high!",
        "{name}'s bastard sword descends with devastating force!",
        "{name} swings {his} bastard sword in a powerful overhead blow!",
        "With expert control {name} wields {his} bastard sword!",
        "{name} uses {his} bastard sword to cut a brutal path!",
        "{name}'s bastard sword flashes with speed and power!",
        "{name} drives {his} bastard sword home with tremendous force!",
        "{name} makes {his} bastard sword sing with a powerful strike!",
        "{name} adapts {his} grip and delivers a lethal blow!",
        "{name}'s bastard sword finds perfect balance in {his} hands!",
        "{name} hefts {his} bastard sword and attacks with authority!",
        "{name}'s bastard sword moves with controlled power!",
        "{name} wields {his} bastard sword with devastating skill!",
        "{name} strikes with {his} bastard sword like a judgment!",
        "{name}'s bastard sword crushes through all defense!",
        "{name} brings {his} bastard sword down with overwhelming force!",
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
        "{name} hefts {his} great sword high!",
        "The massive blade of {name}'s great sword sweeps through the air!",
        "{name} roars and drives {his} great sword forward!",
        "{name}'s great sword cleaves with unstoppable momentum!",
        "{name} swings {his} great sword in a devastating arc!",
        "With raw power {name} brings {his} great sword crashing down!",
        "{name}'s great sword strikes with the force of a falling tree!",
        "{name} delivers a mighty blow with {his} great sword!",
        "The enormous blade of {name}'s great sword moves like thunder!",
        "{name} unleashes {his} great sword's full devastating potential!",
        "{name} wields {his} great sword with overwhelming power!",
        "{name}'s great sword cuts a devastating path!",
        "{name} raises {his} great sword and attacks with fury!",
        "{name}'s great sword finds its mark with crushing force!",
        "{name} brings {his} great sword down like judgment!",
        "{name}'s great sword proves why it is legendary!",
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
        "{name} flashes {his} hatchet forward with brutal speed!",
        "{name}'s hatchet bites deep with savage force!",
        "{name} hacks with {his} hatchet in a deadly flurry!",
        "{name}'s hatchet is sharp and finds its target!",
        "{name} wields {his} hatchet with deadly accuracy!",
        "The hatchet in {name}'s hand moves with surprising speed!",
        "{name} delivers a vicious chop with {his} hatchet!",
        "{name}'s hatchet is turned lethal in {his} grip!",
        "{name} uses {his} hatchet to split flesh and bone!",
        "{name}'s hatchet flashes as {he} presses the attack!",
        "{name} raises {his} hatchet and strikes hard!",
        "{name}'s hatchet cuts a path through the defense!",
        "{name} swings {his} hatchet with practiced violence!",
        "{name}'s hatchet finds every opening!",
        "{name} brings {his} hatchet down with cruel precision!",
        "{name}'s hatchet proves why it is feared!",
    ],
    "Hand Axe": [
        "{name} spins the hand axe through the air with deadly accuracy!",
        "The hand axe whistles as it flies toward its target!",
        "{name} hurls the hand axe with practiced precision!",
        "A battle-forged promise of pain, {name} throws the hand axe true!",
        "{name} delivers a spinning throw with the hand axe!",
        "The hand axe cuts a deadly path end over end!",
        "{name} makes the hand axe seek flesh and bone!",
        "With a warrior's toss {name} sends the hand axe flying!",
        "The hand axe returns to {name}'s hand after a perfect throw!",
        "{name} unleashes the hand axe with expert timing!",
        "{name} brings {his} hand axe down with brutal force!",
        "{name}'s hand axe hacks through the defense!",
        "{name} swings {his} hand axe in a deadly arc!",
        "{name}'s hand axe finds flesh with savage precision!",
        "{name} chops with {his} hand axe with practiced violence!",
        "{name} wields {his} hand axe in close combat!",
        "{name}'s hand axe bites deep with lethal force!",
        "{name} strikes with {his} hand axe with brutal efficiency!",
        "{name} uses {his} hand axe to devastating effect!",
        "{name}'s hand axe cuts a brutal path through defense!",
        "{name} brings {his} hand axe around in a sweeping strike!",
        "{name}'s hand axe opens a wound with cruel precision!",
        "{name} hacks with {his} hand axe again and again!",
        "{name} wields {his} hand axe with savage strength!",
        "{name}'s hand axe proves deadly in close quarters!",
        "{name} brings {his} hand axe down with overwhelming force!",
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
        "{name} raises {his} battle axe high!",
        "{name}'s battle axe descends with bone-splitting power!",
        "{name} brings {his} battle axe down with savage force!",
        "{name}'s axe bites deep with a brutal chop!",
        "{name} hacks with {his} battle axe in a deadly flurry!",
        "{name}'s battle axe cleaves through the defense!",
        "{name} swings {his} battle axe with practiced efficiency!",
        "{name}'s heavy axe crashes down with crushing intent!",
        "{name} delivers a powerful overhead chop with {his} battle axe!",
        "{name}'s battle axe finds its mark with overwhelming strength!",
        "{name} hefts {his} battle axe and strikes with authority!",
        "{name}'s battle axe opens a devastating wound!",
        "{name} brings {his} battle axe around with terrible force!",
        "{name}'s battle axe crushes through all opposition!",
        "{name} wields {his} battle axe with brutal mastery!",
        "{name}'s battle axe proves why it is legendary in combat!",
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
        "{name} hefts {his} great axe with both hands!",
        "The massive axe of {name} cleaves through the air!",
        "{name} swings {his} great axe with the power of giants!",
        "{name}'s great axe crashes down with bone-crushing force!",
        "{name} drives {his} great axe forward with overwhelming power!",
        "{name}'s great axe descends like a hammer of judgment!",
        "{name} brings {his} great axe down with devastating force!",
        "{name}'s great axe finds its mark with unstoppable momentum!",
        "{name} wields {his} great axe with lethal intent!",
        "The massive weapon in {name}'s hands proves its worth!",
        "{name} raises {his} great axe and attacks with fury!",
        "{name}'s great axe cuts a devastating path!",
        "{name} swings {his} great axe with overwhelming strength!",
        "{name}'s great axe opens a wound of terrible proportions!",
        "{name} brings {his} great axe around with terrible power!",
        "{name}'s great axe proves why it is feared across the land!",
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
        "{name} drives {his} small pick with surgical precision!",
        "{name}'s small pick punches through armor!",
        "{name} slams {his} pick forward with lethal intent!",
        "{name}'s small pick seeks vital gaps in the defense!",
        "{name} strikes with {his} small pick with brutal efficiency!",
        "{name}'s small pick finds weak points!",
        "{name} uses {his} small pick to devastating effect!",
        "{name}'s small pick bites deep with cruel force!",
        "{name} thrusts {his} small pick with expert aim!",
        "{name}'s small pick opens a wound with precision!",
        "{name} brings {his} small pick down with savage force!",
        "{name}'s small pick proves deadly in skilled hands!",
        "{name} wields {his} small pick with practiced violence!",
        "{name}'s small pick finds its mark with accuracy!",
        "{name} strikes with {his} small pick again and again!",
        "{name}'s small pick cuts through all defense!",
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
        "{name} drives {his} military pick forward with brutal force!",
        "{name}'s military pick seeks to punch through steel!",
        "{name} crashes {his} pick forward with armor-cracking intent!",
        "{name}'s military pick is designed to pierce all defense!",
        "{name} wields {his} military pick with savage precision!",
        "{name}'s military pick finds weak points in armor!",
        "{name} uses {his} military pick to devastating effect!",
        "{name}'s military pick bites deep with cruel force!",
        "{name} thrusts {his} military pick with expert aim!",
        "{name}'s military pick opens a wound through armor!",
        "{name} brings {his} military pick down with overwhelming force!",
        "{name}'s military pick proves deadly against all defense!",
        "{name} wields {his} military pick with brutal efficiency!",
        "{name}'s military pick finds its mark with armor-piercing power!",
        "{name} strikes with {his} military pick with lethal precision!",
        "{name}'s military pick proves why it is a tool of war!",
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
        "{name} brings {his} pick axe down with brutal force!",
        "{name}'s pick axe swings with devastating power!",
        "{name} crashes {his} pick axe downward with splitting force!",
        "{name}'s pick axe is designed to break anything!",
        "{name} wields {his} pick axe with savage efficiency!",
        "{name}'s pick axe finds and exploits weakness!",
        "{name} uses {his} pick axe to devastating effect!",
        "{name}'s pick axe bites deep with cruel force!",
        "{name} brings {his} pick axe around with lethal precision!",
        "{name}'s pick axe opens a wound with brutal power!",
        "{name} raises {his} pick axe high and strikes!",
        "{name}'s pick axe cuts a devastating path!",
        "{name} swings {his} pick axe with overwhelming strength!",
        "{name}'s pick axe proves deadly in {his} hands!",
        "{name} brings {his} pick axe down with terrible force!",
        "{name}'s pick axe proves why miners fear its power!",
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
        "{name} swings {his} hammer with bone-crushing force!",
        "{name}'s hammer lands with straightforward power!",
        "{name} brings {his} hammer down with solid intent!",
        "{name}'s hammer proves that simplicity is deadly!",
        "{name} wields {his} hammer with reliable force!",
        "{name}'s hammer finds its mark with crushing power!",
        "{name} uses {his} hammer to devastating effect!",
        "{name}'s hammer bites deep with brutal force!",
        "{name} brings {his} hammer around with lethal precision!",
        "{name}'s hammer opens a wound with crushing weight!",
        "{name} hefts {his} hammer and strikes hard!",
        "{name}'s hammer cuts a devastating path!",
        "{name} swings {his} hammer with overwhelming strength!",
        "{name}'s hammer proves deadly in {his} hands!",
        "{name} brings {his} hammer down with terrible force!",
        "{name}'s hammer proves why it is the tool of warriors!",
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
        "{name} swings {his} mace in a heavy, punishing arc!",
        "{name}'s mace is flanged and brutal!",
        "{name} brings {his} mace down with authority!",
        "{name}'s mace seeks to crush all opposition!",
        "{name} wields {his} mace with savage force!",
        "{name}'s mace finds its mark with devastating power!",
        "{name} uses {his} mace to devastating effect!",
        "{name}'s mace bites deep with cruel force!",
        "{name} brings {his} mace around with lethal precision!",
        "{name}'s mace opens a wound with crushing weight!",
        "{name} hefts {his} mace and strikes with authority!",
        "{name}'s mace cuts a devastating path!",
        "{name} swings {his} mace with overwhelming strength!",
        "{name}'s mace proves deadly in {his} hands!",
        "{name} brings {his} mace down with terrible force!",
        "{name}'s mace proves why it is a weapon of authority!",
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
        "{name} whips {his} morningstar in a deadly arc!",
        "The spiked ball of {name}'s morningstar swings with brutal force!",
        "{name} brings {his} morningstar down with crushing intent!",
        "{name}'s morningstar moves with spiked menace!",
        "{name} brings {his} morningstar down with authority!",
        "{name}'s morningstar seeks to crush all opposition!",
        "{name} wields {his} morningstar with savage force!",
        "{name}'s morningstar swings with devastating power!",
        "{name} uses {his} morningstar with lethal technique!",
        "{name}'s morningstar moves with cruel precision!",
        "{name} swings {his} morningstar in a spinning arc!",
        "{name}'s morningstar cuts a dangerous path!",
        "{name} brings {his} morningstar around with lethal force!",
        "{name}'s morningstar proves dangerous in {his} hands!",
        "{name} brings {his} morningstar down with terrible force!",
        "{name}'s morningstar demonstrates why spikes are feared!",
    ],
    "War Hammer": [
        "{name} brings the war hammer down with earth-shaking power!",
        "The war hammer strikes with the force of a thunderclap!",
        "{name} swings the war hammer with devastating, concentrated force!",
        "The heavy hammer crashes down with bone-crushing intent!",
        "With giant like strength behind it {name} makes the war hammer a siege engine!",
        "The war hammer falls like divine judgment!",
        "{name} delivers a crushing blow with the war hammer!",
        "The war hammer means to end the fight decisively!",
        "{name} brings the war hammer crashing down with tremendous power!",
        "A weapon built for breaking armor, {name} wields it masterfully!",
        "{name} hefts {his} war hammer high!",
        "{name}'s war hammer strikes with thunderous power!",
        "{name} swings {his} war hammer with devastating force!",
        "{name}'s war hammer is a weapon of war and authority!",
        "{name} brings {his} war hammer down with commanding force!",
        "{name}'s war hammer seeks to crush all opposition!",
        "{name} wields {his} war hammer with savage force!",
        "{name}'s war hammer swings with overwhelming power!",
        "{name} uses {his} war hammer with lethal technique!",
        "{name}'s war hammer moves with brutal precision!",
        "{name} hefts {his} war hammer and strikes with authority!",
        "{name}'s war hammer cuts a devastating path!",
        "{name} brings {his} war hammer around with lethal force!",
        "{name}'s war hammer proves formidable in {his} hands!",
        "{name} brings {his} war hammer down with terrible force!",
        "{name}'s war hammer demonstrates why it is a tool of conquest!",
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
        "{name} hefts {his} maul with both hands!",
        "{name}'s maul descends with terrible force!",
        "{name} brings {his} maul down with crushing power!",
        "{name}'s maul is massive and deadly!",
        "{name} brings {his} maul down with commanding force!",
        "{name}'s maul seeks to crush all opposition!",
        "{name} wields {his} maul with savage force!",
        "{name}'s maul swings with overwhelming power!",
        "{name} uses {his} maul with lethal technique!",
        "{name}'s maul moves with brutal precision!",
        "{name} raises {his} maul high and strikes!",
        "{name}'s maul cuts a devastating path!",
        "{name} brings {his} maul around with lethal force!",
        "{name}'s maul proves formidable in {his} hands!",
        "{name} brings {his} maul down with terrible force!",
        "{name}'s maul demonstrates crushing power!",
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
        "{name} hefts {his} club and strikes!",
        "{name}'s club seeks to break and crush!",
        "{name} brings {his} club down with raw violence!",
        "{name}'s club is simple but deadly!",
        "{name} brings {his} club down with commanding force!",
        "{name}'s club seeks to crush all opposition!",
        "{name} wields {his} club with savage force!",
        "{name}'s club swings with overwhelming power!",
        "{name} uses {his} club with lethal technique!",
        "{name}'s club moves with brutal precision!",
        "{name} raises {his} club high and strikes!",
        "{name}'s club cuts a devastating path!",
        "{name} brings {his} club around with lethal force!",
        "{name}'s club proves effective in {his} hands!",
        "{name} brings {his} club down with terrible force!",
        "{name}'s club proves why simplicity is devastating!",
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
        "{name} lunges forward with {his} short spear!",
        "{name}'s short spear thrusts with lethal precision!",
        "{name} thrusts {his} short spear with deadly force!",
        "{name}'s short spear seeks vital areas!",
        "{name} drives {his} short spear forward with commanding force!",
        "{name}'s short spear seeks to pierce all opposition!",
        "{name} wields {his} short spear with savage force!",
        "{name}'s short spear moves with lethal power!",
        "{name} uses {his} short spear with expert technique!",
        "{name}'s short spear strikes with brutal precision!",
        "{name} raises {his} short spear and thrusts!",
        "{name}'s short spear finds the opening with deadly aim!",
        "{name} drives {his} short spear forward with lethal force!",
        "{name}'s short spear proves deadly in {his} hands!",
        "{name} thrusts {his} short spear with terrible force!",
        "{name}'s short spear demonstrates why it is a warrior's tool!",
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
        "{name} braces {his} boar spear with both hands!",
        "{name}'s boar spear impales with savage force!",
        "{name} lunges forward with {his} boar spear!",
        "{name}'s boar spear thrusts with lethal intent!",
        "{name} drives {his} boar spear forward with commanding force!",
        "{name}'s boar spear seeks to pierce all opposition!",
        "{name} wields {his} boar spear with savage force!",
        "{name}'s boar spear moves with lethal power!",
        "{name} uses {his} boar spear with expert technique!",
        "{name}'s boar spear strikes with brutal precision!",
        "{name} raises {his} boar spear and thrusts!",
        "{name}'s boar spear finds the opening with deadly aim!",
        "{name} drives {his} boar spear forward with lethal force!",
        "{name}'s boar spear proves deadly in {his} hands!",
        "{name} thrusts {his} boar spear with terrible force!",
        "{name}'s boar spear demonstrates why it is a hunter's tool!",
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
        "{name} extends {his} long spear with deadly reach!",
        "{name}'s long spear punches forward with lethal precision!",
        "{name} thrusts {his} long spear with commanding force!",
        "{name}'s long spear seeks vital areas from distance!",
        "{name} drives {his} long spear forward with deadly intent!",
        "{name}'s long spear seeks to pierce all opposition!",
        "{name} wields {his} long spear with expert force!",
        "{name}'s long spear moves with lethal power!",
        "{name} uses {his} long spear with masterful technique!",
        "{name}'s long spear strikes with brutal precision!",
        "{name} raises {his} long spear and thrusts!",
        "{name}'s long spear finds the opening with deadly aim!",
        "{name} drives {his} long spear forward with devastating force!",
        "{name}'s long spear proves deadly in {his} hands!",
        "{name} thrusts {his} long spear with terrible force!",
        "{name}'s long spear demonstrates superior reach and power!",
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
        "{name} swings {his} pole axe in a wide arc!",
        "{name}'s pole axe combines reach and cleaving power!",
        "{name} brings {his} pole axe down with devastating force!",
        "{name}'s pole axe is a weapon of war and authority!",
        "{name} brings {his} pole axe down with commanding force!",
        "{name}'s pole axe seeks to crush all opposition!",
        "{name} wields {his} pole axe with savage force!",
        "{name}'s pole axe swings with overwhelming power!",
        "{name} uses {his} pole axe with expert technique!",
        "{name}'s pole axe strikes with brutal precision!",
        "{name} raises {his} pole axe and attacks!",
        "{name}'s pole axe cuts a devastating path!",
        "{name} brings {his} pole axe around with lethal force!",
        "{name}'s pole axe proves formidable in {his} hands!",
        "{name} brings {his} pole axe down with terrible force!",
        "{name}'s pole axe demonstrates why it is a tool of conquest!",
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
        "{name} swings {his} halberd in a wide arc!",
        "{name}'s halberd combines axe, spike, and hook!",
        "{name} brings {his} halberd down with devastating versatility!",
        "{name}'s halberd is a weapon of complete dominance!",
        "{name} brings {his} halberd down with commanding force!",
        "{name}'s halberd seeks to crush all opposition!",
        "{name} wields {his} halberd with savage force!",
        "{name}'s halberd swings with overwhelming power!",
        "{name} uses {his} halberd with expert technique!",
        "{name}'s halberd strikes with brutal precision!",
        "{name} raises {his} halberd and attacks!",
        "{name}'s halberd cuts a devastating path!",
        "{name} brings {his} halberd around with lethal force!",
        "{name}'s halberd proves formidable in {his} hands!",
        "{name} brings {his} halberd down with terrible force!",
        "{name}'s halberd demonstrates complete battlefield mastery!",
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
        "{name} whirls {his} flail in a deadly arc!",
        "{name}'s flail swings with unpredictable power!",
        "{name} brings {his} flail down with crushing force!",
        "{name}'s flail is a weapon of chaos and destruction!",
        "{name} brings {his} flail down with commanding force!",
        "{name}'s flail seeks to crush all opposition!",
        "{name} wields {his} flail with savage force!",
        "{name}'s flail swings with overwhelming power!",
        "{name} uses {his} flail with expert technique!",
        "{name}'s flail strikes with brutal precision!",
        "{name} raises {his} flail and attacks!",
        "{name}'s flail cuts a devastating path!",
        "{name} brings {his} flail around with lethal force!",
        "{name}'s flail proves formidable in {his} hands!",
        "{name} brings {his} flail down with terrible force!",
        "{name}'s flail demonstrates why unpredictability is deadly!",
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
        "{name} whips {his} bladed flail in a storm of edges!",
        "{name}'s bladed flail sings with cruel razor edges!",
        "{name} delivers a vicious strike with {his} bladed flail!",
        "{name}'s bladed flail is a weapon of elegant destruction!",
        "{name} brings {his} bladed flail down with commanding force!",
        "{name}'s bladed flail seeks to shred all opposition!",
        "{name} wields {his} bladed flail with savage grace!",
        "{name}'s bladed flail swings with cutting power!",
        "{name} uses {his} bladed flail with expert technique!",
        "{name}'s bladed flail strikes with brutal precision!",
        "{name} raises {his} bladed flail and attacks!",
        "{name}'s bladed flail cuts a devastating path!",
        "{name} brings {his} bladed flail around with lethal force!",
        "{name}'s bladed flail proves formidable in {his} hands!",
        "{name} brings {his} bladed flail down with terrible force!",
        "{name}'s bladed flail demonstrates why edges are deadly!",
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
        "{name} swings {his} war flail with crushing force!",
        "{name}'s war flail crashes down with bone-breaking power!",
        "{name} delivers a devastating blow with {his} war flail!",
        "{name}'s war flail is a weapon of overwhelming force!",
        "{name} brings {his} war flail down with commanding force!",
        "{name}'s war flail seeks to crush all opposition!",
        "{name} wields {his} war flail with savage force!",
        "{name}'s war flail swings with overwhelming power!",
        "{name} uses {his} war flail with expert technique!",
        "{name}'s war flail strikes with brutal precision!",
        "{name} raises {his} war flail and attacks!",
        "{name}'s war flail cuts a devastating path!",
        "{name} brings {his} war flail around with lethal force!",
        "{name}'s war flail proves formidable in {his} hands!",
        "{name} brings {his} war flail down with terrible force!",
        "{name}'s war flail demonstrates why weight is power!",
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
        "{name} creates a whirlwind with {his} battle flail!",
        "{name}'s battle flail defies prediction and defense!",
        "{name} lashes out in every direction with {his} battle flail!",
        "{name}'s battle flail is a weapon of total mayhem!",
        "{name} brings {his} battle flail down with commanding force!",
        "{name}'s battle flail seeks to overwhelm all opposition!",
        "{name} wields {his} battle flail with savage power!",
        "{name}'s battle flail swings with overwhelming force!",
        "{name} uses {his} battle flail with expert mastery!",
        "{name}'s battle flail strikes with brutal unpredictability!",
        "{name} raises {his} battle flail and unleashes chaos!",
        "{name}'s battle flail cuts a devastating swath!",
        "{name} brings {his} battle flail around with lethal force!",
        "{name}'s battle flail proves unstoppable in {his} hands!",
        "{name} brings {his} battle flail down with terrible force!",
        "{name}'s battle flail demonstrates why chaos is deadly!",
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
        "{name} moves {his} quarterstaff with fluid precision!",
        "{name}'s quarterstaff strikes with balanced power!",
        "{name} brings {his} quarterstaff down with decisive force!",
        "{name}'s quarterstaff is a weapon of technique and control!",
        "{name} brings {his} quarterstaff down with commanding force!",
        "{name}'s quarterstaff seeks to overwhelm all opposition!",
        "{name} wields {his} quarterstaff with practiced grace!",
        "{name}'s quarterstaff swings with flowing power!",
        "{name} uses {his} quarterstaff with expert technique!",
        "{name}'s quarterstaff strikes with precise force!",
        "{name} raises {his} quarterstaff and attacks!",
        "{name}'s quarterstaff cuts a deceptive path!",
        "{name} brings {his} quarterstaff around with lethal force!",
        "{name}'s quarterstaff proves formidable in {his} hands!",
        "{name} brings {his} quarterstaff down with terrible force!",
        "{name}'s quarterstaff demonstrates why balance is power!",
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
        "{name} swings {his} great staff with heavy power!",
        "{name}'s great staff demands space with every strike!",
        "{name} brings {his} great staff down with crushing authority!",
        "{name}'s great staff is a weapon of overwhelming force!",
        "{name} brings {his} great staff down with commanding force!",
        "{name}'s great staff seeks to crush all opposition!",
        "{name} wields {his} great staff with savage power!",
        "{name}'s great staff swings with devastating reach!",
        "{name} uses {his} great staff with expert technique!",
        "{name}'s great staff strikes with brutal force!",
        "{name} raises {his} great staff and attacks!",
        "{name}'s great staff cuts a devastating path!",
        "{name} brings {his} great staff around with lethal force!",
        "{name}'s great staff proves formidable in {his} hands!",
        "{name} brings {his} great staff down with terrible force!",
        "{name}'s great staff demonstrates why length is power!",
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
        "{name} slams {his} buckler forward with sharp force!",
        "{name}'s buckler strikes with punishing precision!",
        "{name} brings {his} buckler down with decisive impact!",
        "{name}'s buckler is a weapon of skilled defense!",
        "{name} brings {his} buckler down with commanding force!",
        "{name}'s buckler seeks to overwhelm close opposition!",
        "{name} wields {his} buckler with practiced aggression!",
        "{name}'s buckler swings with surprising power!",
        "{name} uses {his} buckler with expert technique!",
        "{name}'s buckler strikes with brutal precision!",
        "{name} raises {his} buckler and attacks!",
        "{name}'s buckler cuts a sharp path!",
        "{name} brings {his} buckler around with lethal force!",
        "{name}'s buckler proves effective in {his} hands!",
        "{name} brings {his} buckler down with terrible force!",
        "{name}'s buckler demonstrates why shields can attack!",
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
        "{name} drives {his} target shield forward with terrible force!",
        "{name}'s target shield proves a formidable weapon!",
        "{name} uses {his} target shield to strike with conviction!",
        "{name}'s target shield swings with commanding power!",
        "{name} brings {his} target shield around with brutal force!",
        "{name}'s target shield strikes with punishing impact!",
        "{name} wields {his} target shield like a master!",
        "{name}'s target shield demonstrates aggressive technique!",
        "{name} raises {his} target shield and attacks with skill!",
        "{name}'s target shield cuts a powerful path!",
        "{name} drives {his} target shield forward with skill!",
        "{name}'s target shield moves with practiced aggression!",
        "{name} swings {his} target shield with expert force!",
        "{name}'s target shield proves effective in close combat!",
        "{name} brings {his} target shield down with sharp force!",
        "{name}'s target shield is a weapon of precise strikes!",
    ],
    "Tower Shield": [
        "{name} charges like a moving iron wall with the tower shield!",
        "The massive tower shield crashes into the opponent with crushing weight!",
        "{name} advances with the tower shield's deliberate, imposing presence!",
        "With titan like strength {name} turns the tower shield into an unstoppable force!",
        "The tower shield dares the enemy to strike as {name} attacks!",
        "{name} slams the tower shield forward with earth-shaking power!",
        "A massive barrier of steel, {name} wields it as a weapon!",
        "The tower shield moves with the weight of certainty!",
        "{name} delivers a crushing bash with the tower shield!",
        "The tower shield becomes an iron fortress in {name}'s hands!",
        "{name} swings {his} massive tower shield with devastating power!",
        "{name}'s tower shield moves like an unstoppable wall!",
        "{name} brings {his} tower shield down with crushing force!",
        "{name}'s tower shield delivers a blow of terrible consequence!",
        "{name} wields {his} tower shield with commanding strength!",
        "{name}'s tower shield strikes with overwhelming impact!",
        "{name} uses {his} tower shield as both shield and battering ram!",
        "{name}'s tower shield demonstrates why size matters in combat!",
        "{name} raises {his} tower shield and attacks with power!",
        "{name}'s tower shield proves unstoppable in close quarters!",
        "{name} brings {his} tower shield around with terrible force!",
        "{name}'s tower shield cuts a wide path of destruction!",
        "{name} wields {his} tower shield with practiced ferocity!",
        "{name}'s tower shield moves with surprising agility for its mass!",
        "{name} drives {his} tower shield forward with lethal intent!",
        "{name}'s tower shield is a weapon of total domination!",
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
        "{name} drives {his} cestus forward with brutal striking force!",
        "{name}'s cestus becomes an extension of pure combat fury!",
        "{name} brings {his} cestus down with devastating power!",
        "{name}'s cestus speaks in the language of violence!",
        "{name} wields {his} cestus like a master of hand-to-hand warfare!",
        "{name}'s cestus strikes with the force of a sledgehammer!",
        "{name} uses {his} cestus to deliver a crushing blow!",
        "{name}'s cestus proves that fists are weapons too!",
        "{name} raises {his} cestus and attacks with ferocity!",
        "{name}'s cestus cuts a path of destruction!",
        "{name} brings {his} cestus up with terrible force!",
        "{name}'s cestus demonstrates devastating striking technique!",
        "{name} drives {his} cestus forward with calculated fury!",
        "{name}'s cestus proves effective in the most brutal exchanges!",
        "{name} swings {his} cestus with practiced aggression!",
        "{name}'s cestus is an instrument of close-range devastation!",
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
        "{name} thrusts {his} trident forward with terrible force!",
        "{name}'s trident seeks to pierce and rake with violent intent!",
        "{name} brings {his} trident up with sharp striking motions!",
        "{name}'s trident proves devastating at close range!",
        "{name} wields {his} trident like a master of the three-pronged way!",
        "{name}'s trident strikes with the force of all three tines!",
        "{name} uses {his} trident to deliver a vicious attack!",
        "{name}'s trident is a weapon of brutal efficiency!",
        "{name} raises {his} trident and attacks with purpose!",
        "{name}'s trident cuts a path of bloodshed!",
        "{name} brings {his} trident around with lethal precision!",
        "{name}'s trident demonstrates why three points are better than one!",
        "{name} drives {his} trident forward with calculated violence!",
        "{name}'s trident proves formidable in {his} hands!",
        "{name} thrusts {his} trident forward with expert technique!",
        "{name}'s trident is an instrument of terrible destruction!",
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
        "{name} casts {his} barbed net forward with vicious intent!",
        "{name}'s net seeks to entangle and wound with cruel precision!",
        "{name} brings {his} net around with cutting force!",
        "{name}'s net becomes a weapon of entanglement and pain!",
        "{name} wields {his} net to constrain and damage!",
        "{name}'s hooked net strikes with brutal effectiveness!",
        "{name} uses {his} net as a tool of terrible ingenuity!",
        "{name}'s net demonstrates the art of intelligent fighting!",
        "{name} raises {his} net and attacks with savage force!",
        "{name}'s net cuts a path of entanglement!",
        "{name} brings {his} net forward with calculated violence!",
        "{name}'s net proves devastatingly effective in {his} hands!",
        "{name} weaves {his} net with practiced, dangerous intent!",
        "{name}'s net is a weapon of both constraint and cutting strikes!",
        "{name} casts {his} barbed net with expert precision!",
        "{name}'s net is an instrument of clever and brutal warfare!",
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
        "{name} swings {his} scythe with a terrible, sweeping arc!",
        "{name}'s scythe becomes an instrument of harvesting death!",
        "{name} brings {his} scythe around with curved, slashing force!",
        "{name}'s scythe proves devastating in wide, brutal strokes!",
        "{name} wields {his} scythe like a master of the deadly harvest!",
        "{name}'s scythe strikes with the force of an unstoppable arc!",
        "{name} uses {his} scythe to deliver a sweeping, vicious attack!",
        "{name}'s scythe demonstrates why curved blades are so effective!",
        "{name} raises {his} scythe and attacks with farming fury!",
        "{name}'s scythe cuts a terrible path of destruction!",
        "{name} brings {his} scythe around with lethal precision!",
        "{name}'s scythe proves formidable in {his} hands!",
        "{name} sweeps {his} scythe forward with practiced violence!",
        "{name}'s scythe moves with surprising grace for such a large weapon!",
        "{name} drives {his} scythe forward with terrible intent!",
        "{name}'s scythe is an instrument of both grace and carnage!",
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
        "{name} swings {his} great pick with devastating piercing force!",
        "{name}'s great pick seeks to puncture and crush with terrible intent!",
        "{name} brings {his} great pick down with crushing, pointed force!",
        "{name}'s great pick proves devastating against any armor!",
        "{name} wields {his} great pick like a master of penetrating combat!",
        "{name}'s great pick strikes with the force of a focused blow!",
        "{name} uses {his} great pick to deliver a vicious, piercing attack!",
        "{name}'s great pick demonstrates why concentration matters in warfare!",
        "{name} raises {his} great pick and attacks with terrible purpose!",
        "{name}'s great pick cuts a focused path of destruction!",
        "{name} brings {his} great pick around with lethal precision!",
        "{name}'s great pick proves formidable in {his} hands!",
        "{name} drives {his} great pick forward with calculated fury!",
        "{name}'s great pick moves with surprising grace for such a heavy weapon!",
        "{name} swings {his} great pick forward with expert technique!",
        "{name}'s great pick is an instrument of armor-piercing devastation!",
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
        "{name} strikes {his} javelin forward with terrible, piercing force!",
        "{name}'s javelin seeks blood with expert technique!",
        "{name} brings {his} javelin to bear with deadly precision!",
        "{name}'s javelin proves devastating in {his} hands!",
        "{name} wields {his} javelin like a master of polearm combat!",
        "{name}'s javelin strikes with the force of a focused thrust!",
        "{name} uses {his} javelin to deliver a vicious, piercing attack!",
        "{name}'s javelin demonstrates why spear-weapons are formidable!",
        "{name} raises {his} javelin and attacks with savage purpose!",
        "{name}'s javelin cuts a path of bloodshed!",
        "{name} brings {his} javelin forward with calculated violence!",
        "{name}'s javelin proves effective in {his} hands!",
        "{name} drives {his} javelin forward with expert technique!",
        "{name}'s javelin moves with the grace of a skilled warrior!",
        "{name} wields {his} javelin with the force of trained skill!",
        "{name}'s javelin is an instrument of piercing devastation!",
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
        "{name} swings {his} ball and chain with terrible, crushing force!",
        "{name}'s ball and chain becomes an instrument of brutal devastation!",
        "{name} brings {his} ball and chain around with overwhelming power!",
        "{name}'s ball and chain proves devastating in any engagement!",
        "{name} wields {his} ball and chain like a master of heavy weapons!",
        "{name}'s ball and chain strikes with the force of a falling hammer!",
        "{name} uses {his} ball and chain to deliver a vicious, crushing attack!",
        "{name}'s ball and chain demonstrates why weight matters in warfare!",
        "{name} raises {his} ball and chain and attacks with terrible purpose!",
        "{name}'s ball and chain cuts a path of destruction!",
        "{name} brings {his} ball and chain forward with calculated violence!",
        "{name}'s ball and chain proves formidable in {his} hands!",
        "{name} swings {his} ball and chain with practiced, lethal intent!",
        "{name}'s ball and chain moves with surprising grace for its mass!",
        "{name} drives {his} ball and chain forward with expert technique!",
        "{name}'s ball and chain is an instrument of overwhelming force!",
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
        "{name} spins {his} bola with vicious, binding intent!",
        "{name}'s bola seeks to entangle and wound with terrible force!",
        "{name} brings {his} bola around in a deadly arc!",
        "{name}'s bola proves devastating in close combat!",
        "{name} wields {his} bola like a master of weighted weapons!",
        "{name}'s bola strikes with the force of all its binding weight!",
        "{name} uses {his} bola to deliver a brutal, wrapping attack!",
        "{name}'s bola demonstrates the art of controlled chaos!",
        "{name} raises {his} bola and attacks with savage precision!",
        "{name}'s bola cuts a path of entanglement and pain!",
        "{name} brings {his} bola forward with calculated violence!",
        "{name}'s bola proves formidable in {his} hands!",
        "{name} spins {his} bola forward with practiced, dangerous intent!",
        "{name}'s bola moves with the grace of a skilled warrior!",
        "{name} wields {his} bola with expert technique!",
        "{name}'s bola is an instrument of weight and deadly accuracy!",
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
        "{name} lashes {his} whip forward with terrible, barbed force!",
        "{name}'s whip seeks to cut and wound with vicious intent!",
        "{name} cracks {his} whip around with crackling aggression!",
        "{name}'s whip proves devastating with its barbed edges!",
        "{name} wields {his} whip like a master of flexible warfare!",
        "{name}'s whip strikes with the force of a lashing barb!",
        "{name} uses {his} whip to deliver a brutal, cutting attack!",
        "{name}'s whip demonstrates why flexible weapons are so effective!",
        "{name} raises {his} whip and attacks with terrible purpose!",
        "{name}'s whip cuts a path of bleeding wounds!",
        "{name} lashes {his} whip forward with calculated violence!",
        "{name}'s whip proves formidable in {his} hands!",
        "{name} cracks {his} whip with practiced, dangerous intent!",
        "{name}'s whip moves with the grace of a skilled warrior!",
        "{name} wields {his} whip with expert technique and force!",
        "{name}'s whip is an instrument of tearing devastation!",
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
        "{name} brings {his} swordbreaker forward with terrible, catching force!",
        "{name}'s swordbreaker seeks to trap and destroy with vicious intent!",
        "{name} moves {his} swordbreaker with defensive, striking precision!",
        "{name}'s swordbreaker proves devastating against any blade!",
        "{name} wields {his} swordbreaker like a master of defensive combat!",
        "{name}'s swordbreaker strikes with the force of a catching parry!",
        "{name} uses {his} swordbreaker to deliver a brutal, trapping attack!",
        "{name}'s swordbreaker demonstrates the art of turning defense to offense!",
        "{name} raises {his} swordbreaker and attacks with terrible purpose!",
        "{name}'s swordbreaker cuts a path of defensive dominance!",
        "{name} brings {his} swordbreaker forward with calculated violence!",
        "{name}'s swordbreaker proves formidable in {his} hands!",
        "{name} moves {his} swordbreaker with practiced, dangerous intent!",
        "{name}'s swordbreaker catches blows and transforms them to attacks!",
        "{name} wields {his} swordbreaker with expert technique!",
        "{name}'s swordbreaker is an instrument of defensive devastation!",
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
        "{name} strikes {his} open hand forward with terrible martial force!",
        "{name}'s trained fists seek to devastate with pure technique!",
        "{name} brings {his} open hand down with sharp striking precision!",
        "{name}'s martial training proves devastating in close combat!",
        "{name} wields {his} open hand like a master of unarmed warfare!",
        "{name}'s fists strike with the force of disciplined training!",
        "{name} uses {his} open hand to deliver a brutal, focused attack!",
        "{name}'s martial arts demonstrate why discipline creates power!",
        "{name} raises {his} open hand and attacks with terrible purpose!",
        "{name}'s fists cut a path of striking technique!",
        "{name} brings {his} open hand forward with calculated violence!",
        "{name}'s open hand proves formidable in {his} hands!",
        "{name} strikes {his} open hand with practiced, dangerous precision!",
        "{name}'s fists move with the grace of a trained warrior!",
        "{name} wields {his} open hand with expert technique!",
        "{name}'s open hand is an instrument of pure martial devastation!",
    ],
    "Open Hand:claw": [
        "{name} strikes with raking claws in a blur of martial precision!",
        "{name} unleashes a devastating series of clawed strikes!",
        "Empty handed but deadly, {name}'s claws flow through a lethal combination!",
        "With disciplined focus {name} finds the perfect angle for {his} claws!",
        "{name} delivers a masterful clawed blow with perfect technique!",
        "{name}'s claws move with fluid, controlled power!",
        "{name} strikes like a martial artist's technique given lethal purpose!",
        "A blur of motion, {name} makes {his} claws devastating!",
        "{name} flows through a deadly clawed sequence!",
        "With bared claws {name} proves skill can overcome steel!",
        "{name} rakes {his} claws forward with terrible martial force!",
        "{name}'s trained claws seek to devastate with pure technique!",
        "{name} brings {his} claws down with sharp striking precision!",
        "{name}'s martial training proves devastating in close combat!",
        "{name} wields {his} claws like a master of unarmed warfare!",
        "{name}'s claws strike with the force of disciplined training!",
        "{name} uses {his} claws to deliver a brutal, focused attack!",
        "{name}'s martial arts demonstrate why discipline creates power!",
        "{name} raises {his} claws and attacks with terrible purpose!",
        "{name}'s claws cut a path of striking technique!",
        "{name} brings {his} claws forward with calculated violence!",
        "{name}'s claws prove formidable in {his} hands!",
        "{name} rakes {his} claws with practiced, dangerous precision!",
        "{name}'s claws move with the grace of a trained warrior!",
        "{name} wields {his} claws with expert technique!",
        "{name}'s claws are an instrument of pure martial devastation!",
    ],
    "Open Hand:kick": [
        "{name} strikes with a devastating kick in a blur of martial precision!",
        "{name} unleashes a devastating series of kicks!",
        "Empty handed but deadly, {name} flows through a lethal kicking combination!",
        "With disciplined focus {name} finds the perfect striking surface for {his} kick!",
        "{name} delivers a masterful kick with perfect technique!",
        "{name}'s leg moves with fluid, controlled power!",
        "{name} strikes like a martial artist's technique given lethal purpose!",
        "A blur of motion, {name} makes {his} kick devastating!",
        "{name} flows through a deadly kicking sequence!",
        "With disciplined footwork {name} proves skill can overcome steel!",
        "{name} drives {his} kick forward with terrible martial force!",
        "{name}'s trained leg seeks to devastate with pure technique!",
        "{name} brings {his} kick down with sharp striking precision!",
        "{name}'s martial training proves devastating in close combat!",
        "{name} wields {his} kick like a master of unarmed warfare!",
        "{name}'s leg strikes with the force of disciplined training!",
        "{name} uses {his} kick to deliver a brutal, focused attack!",
        "{name}'s martial arts demonstrate why discipline creates power!",
        "{name} raises {his} leg and attacks with terrible purpose!",
        "{name}'s kick cuts a path of striking technique!",
        "{name} drives {his} kick forward with calculated violence!",
        "{name}'s kick proves formidable in {his} hands!",
        "{name} strikes {his} kick with practiced, dangerous precision!",
        "{name}'s leg moves with the grace of a trained warrior!",
        "{name} wields {his} kick with expert technique!",
        "{name}'s kick is an instrument of pure martial devastation!",
    ],
    "Open Hand:tail": [
        "{name} strikes with {his} tail in a blur of martial precision!",
        "{name} unleashes a devastating series of tail strikes!",
        "Empty handed but deadly, {name}'s tail flows through a lethal combination!",
        "With disciplined focus {name} finds the perfect angle for {his} tail!",
        "{name} delivers a masterful tail strike with perfect technique!",
        "{name}'s tail moves with fluid, controlled power!",
        "{name} strikes like a martial artist's technique given lethal purpose!",
        "A blur of motion, {name} makes {his} tail devastating!",
        "{name} flows through a deadly tail-driven sequence!",
        "With a lashing tail {name} proves skill can overcome steel!",
        "{name} whips {his} tail forward with terrible martial force!",
        "{name}'s trained tail seeks to devastate with pure technique!",
        "{name} brings {his} tail down with sharp striking precision!",
        "{name}'s martial training proves devastating in close combat!",
        "{name} wields {his} tail like a master of unarmed warfare!",
        "{name}'s tail strikes with the force of disciplined training!",
        "{name} uses {his} tail to deliver a brutal, focused attack!",
        "{name}'s martial arts demonstrate why discipline creates power!",
        "{name} raises {his} tail and attacks with terrible purpose!",
        "{name}'s tail cuts a path of striking technique!",
        "{name} brings {his} tail forward with calculated violence!",
        "{name}'s tail proves formidable in {his} hands!",
        "{name} strikes {his} tail with practiced, dangerous precision!",
        "{name}'s tail moves with the grace of a trained warrior!",
        "{name} wields {his} tail with expert technique!",
        "{name}'s tail is an instrument of pure martial devastation!",
    ],
}


def signature_line(attacker_name: str, weapon_name: str, gender: str = "Male", attack_type: Optional[str] = None) -> Optional[str]:
    """
    Return a signature flavor line for a critical hit, or None if no pool exists
    for this weapon. Caller is responsible for the skill >= 5 and chance checks.

    attack_type: for Open Hand attackers, the pre-chosen "claw"/"kick"/"tail" swing
    type (see _get_martial_attack_type) so this line agrees with the attack/hit
    lines describing the same swing. Ignored for weapon attacks.
    """
    pool = None
    if weapon_name == "Open Hand" and attack_type:
        pool = SIGNATURE_LINES.get(f"Open Hand:{attack_type}")
    if pool is None:
        pool = SIGNATURE_LINES.get(weapon_name)
    if not pool:
        return None
    pronoun = "his" if gender == "Male" else "her"
    he_pronoun = "he" if gender == "Male" else "she"
    return _pool_choice(pool).format(name=attacker_name.upper(), his=pronoun, he=he_pronoun)


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
    "{attacker} swings and hits nothing",
    "{attacker}'s {weapon} passes through empty space",
    "{attacker} cannot find the range",
    "{attacker}'s attack overshoots",
    "{attacker} misjudges and misses",
    "The {weapon} finds no target",
    "{attacker} is caught off balance",
    "{attacker}'s timing is poor",
    "{attacker} reaches but falls short",
    "{attacker}'s {weapon} whistles past",
    "{attacker} flails and misses",
    "{attacker}'s strike goes astray",
    "{attacker} lunges for nothing",
    "The attack connects with nothing",
    "{attacker} overextends and misses",
    "{attacker}'s {weapon} cuts empty air",
    "{attacker} swipes but connects with nothing",
    "{attacker} grasps at thin air",
]

THROW_MISS_LINES = [
    "{attacker}'s {weapon} sails wide of the mark!",
    "The thrown {weapon} arcs well clear of its target!",
    "{attacker}'s aim is off, the {weapon} flies harmlessly past!",
    "The {weapon} tumbles end-over-end, but clears {attacker_foe} entirely!",
    "{attacker}'s throw is wide, the {weapon} clattering across the sand!",
    "The {weapon} whistles past, finding nothing but air!",
    "The {weapon} arcs high and overshoots!",
    "{attacker}'s throw is short of the mark!",
    "The {weapon} falls well shy of {attacker_foe}!",
    "{attacker} releases the {weapon} at the wrong moment!",
    "The thrown {weapon} drifts harmlessly wide!",
    "{attacker_foe} watches the {weapon} sail past!",
    "The {weapon} clatters down short of its target!",
    "{attacker}'s {weapon} tumbles past without connecting!",
    "The throw is misjudged, the {weapon} spinning off course!",
    "The {weapon} glances off the arena floor far from {attacker_foe}!",
    "{attacker} miscalculates the distance entirely!",
    "The {weapon} whistles through empty space!",
    "{attacker}'s aim falters, the {weapon} flies wide!",
    "The thrown {weapon} clears the target by a wide margin!",
    "{attacker_foe} easily sidesteps as the {weapon} misses!",
    "The {weapon} passes well clear of its intended target!",
    "{attacker}'s throw is off, the {weapon} missing entirely!",
    "The {weapon} sails overhead and beyond!",
]


def miss_line(attacker_name: str, weapon_name: str) -> str:
    template = _pool_choice(MISS_LINES)
    return template.format(
        attacker=attacker_name.upper(),
        weapon  =weapon_name.lower(),
    )


def throw_miss_line(attacker_name: str, weapon_name: str, defender_name: str) -> str:
    template = _pool_choice(THROW_MISS_LINES)
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
    "{defender} has a simple plan. Don't get hit!",
    "{defender} sees it coming and meets it with perfect form!",
    "{defender} reads the attack and shuts it down!",
    "{defender}'s timing is impeccable, the parry textbook perfect!",
    "{defender} stands firm and blocks the strike!",
    "{defender} deflects with practiced ease!",
    "{defender}'s defense is absolute, the attack goes nowhere!",
    "{defender} counters with a clean parry!",
    "{defender} anticipates and blocks the strike entirely!",
    "{defender}'s guard is unshakable!",
    "{defender} turns the weapon aside without breaking stride!",
    "{defender} meets the blow head-on and stands firm!",
    "{defender} flows with the attack and neutralizes it!",
    "{defender} reads {attacker}'s intent and acts accordingly!",
    "{defender}'s skill shines through in a flawless parry!",
    "{defender} catches the weapon smoothly and diverts it!",
    "{defender}'s defense holds against the assault!",
    "{defender} is composed and in complete control!",
    "{defender} makes it look easy, turning the strike aside!",
]

PARRY_LINES_BARELY = [
    "{defender} barely gets the parry off!",
    "{defender} makes a desperate last-moment parry!",
    "{defender} just manages to deflect the blow!",
    "{defender} throws up a last-second parry!",
    "{defender} barely avoids disaster!",
    "{defender} gets the weapon up just in time!",
    "{defender}'s parry is desperate but effective!",
    "{defender} scrambles and blocks at the last moment!",
    "{defender} desperately throws up {his} weapon in an awkward parry!",
    "{defender} catches the blow by the slimmest margin!",
    "{defender} makes a panicked parry that somehow works!",
    "{defender}'s defense is frantic but holds!",
    "{defender} reacts in the nick of time!",
    "{defender} deflects with barely a moment to spare!",
    "Fortune smiles as {defender} gets a parry off!",
    "{defender} is forced to improvise, and it pays off!",
    "{defender} barely interposes the weapon!",
    "The parry from {defender} is sloppy but sufficient!",
    "{defender} throws up anything to block the blow!",
    "{defender}'s defense is ragged but prevents the hit!",
    "{defender} gets lucky and catches the strike!",
    "{defender} parries awkwardly but successfully!",
    "{defender} nearly fails but manages to defend!",
    "{defender} is in trouble, but the parry holds!",
    "{defender} pulls off a desperate, last-ditch parry!",
]

DEFENSE_POINT_LINES = [
    "{defender} had that area covered, the defense holds!",
    "{defender}'s focus there pays off, turning the strike aside!",
    "That spot was well protected, {defender} deflects cleanly!",
    "{defender}'s guard on that area proves its worth!",
    "{defender} had anticipated this exact strike!",
    "The defense point {defender} established pays dividends!",
    "{defender} was prepared for exactly this attack!",
    "That carefully guarded area turns the blow aside!",
    "{defender}'s defensive positioning proves decisive!",
    "The strike finds a wall where {defender} expected it!",
    "{defender} had this opening already covered!",
    "Years of experience show as {defender} deflects precisely!",
    "The defense {defender} prepared holds firm against the assault!",
    "{defender}'s watchful guard catches the attack perfectly!",
    "The strike hits {defender}'s strongest point and fails!",
    "{defender} knew this angle was coming and was ready!",
    "The weapon finds only {defender}'s prepared defense!",
    "{defender}'s focus on that spot saves the day!",
    "The position {defender} held pays off instantly!",
    "{defender}'s defense has no weakness at that point!",
    "The strike meets {defender}'s absolute readiness!",
    "{defender} had reinforced the defense at exactly the right place!",
    "The attack crumbles against {defender}'s prepared guard!",
    "{defender} demonstrates why the defense point was essential!",
]


def parry_line(defender_name: str, defender_gender: str = "Male", attacker_name: str = "", barely: bool = False, defense_point_active: bool = False) -> str:
    pronoun = "his" if defender_gender == "Male" else "her"
    if defense_point_active and random.random() < 0.5:
        return _pool_choice(DEFENSE_POINT_LINES).format(defender=defender_name.upper(), his=pronoun, attacker=attacker_name.upper() if attacker_name else "")
    if barely:
        return _pool_choice(PARRY_LINES_BARELY).format(defender=defender_name.upper(), his=pronoun, attacker=attacker_name.upper() if attacker_name else "")
    return _pool_choice(PARRY_LINES_SUCCESS).format(defender=defender_name.upper(), his=pronoun, attacker=attacker_name.upper() if attacker_name else "")


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
    "{defender} flows out of the way with grace!",
    "{defender} rolls aside from the incoming strike!",
    "{defender} slips past the attack effortlessly!",
    "{defender} leaps clear of the danger!",
    "{defender} pivots and avoids the blow!",
    "{defender} vanishes from the weapon's path!",
    "{defender} spins away from the strike!",
    "{defender} glides out of harm's way!",
    "{defender} bobs and weaves past the attack!",
    "{defender} shifts weight and dodges cleanly!",
    "{defender} backpedals out of range!",
    "{defender} dances away from the weapon!",
    "{defender} uses footwork to evade completely!",
    "{defender} takes a quick step aside!",
    "{defender} is already moving before the blow lands!",
    "{defender} reads the attack and is gone!",
    "{defender} sidesteps with perfect timing!",
    "{defender} weaves past with minimal effort!",
    "{defender} moves with the grace of a cat!",
]


def dodge_line(defender_name: str, gender: str = "Male") -> str:
    pronoun = "his" if gender == "Male" else "her"
    return _pool_choice(DODGE_LINES).format(defender=defender_name.upper(), his=pronoun)


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
    "{defender} plants {his} feet firmly, ready to meet the blow!",
    "{defender} settles into a perfect defensive stance!",
    "{defender} braces for impact, every muscle tensed!",
    "{defender} raises {his} weapon to intercept the strike!",
    "{defender} focuses completely on the incoming attack!",
    "{defender} prepares a rock-solid parry!",
    "{defender} takes a deep breath and readies the defense!",
    "{defender}'s stance is perfect for catching the blow!",
    "{defender} watches like a hawk for the attack!",
    "{defender} is coiled and ready to deflect!",
    "{defender} commits fully to a solid defensive posture!",
    "{defender} settles {his} guard and waits for contact!",
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
    "{defender} is light on {his} feet, ready to move!",
    "{defender}'s stance suggests {he} plans to evade!",
    "{defender} shifts into a mobile, evasive position!",
    "{defender} bounces slightly, preparing for movement!",
    "{defender}'s body language screams readiness to dodge!",
    "{defender} keeps {his} weight balanced and ready to flee!",
    "{defender} is ready to slip the strike before it arrives!",
    "{defender} is poised to move in any direction instantly!",
    "{defender} settles into a stance built for evasion!",
    "{defender} is clearly ready to get out of the way!",
    "{defender}'s footwork suggests a dodge is coming!",
    "{defender} breathes deeply, ready for quick movement!",
]


def defense_intent_line(defender_name: str, gender: str, uses_parry: bool) -> str:
    his = "his" if gender == "Male" else "her"
    he = "he" if gender == "Male" else "she"
    pool = DEFENSE_INTENT_PARRY if uses_parry else DEFENSE_INTENT_DODGE
    return _pool_choice(pool).format(defender=defender_name.upper(), his=his, he=he)


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
    "But {defender}'s weapon is forced down!",
    "The parry shatters under the weight of the blow!",
    "{defender}'s guard fails at the crucial instant!",
    "The weapon slips through {defender}'s guard!",
    "{defender} can't hold the line!",
    "The attack is simply too strong to stop!",
    "{defender}'s defense crumbles at the last second!",
    "The blow finds its way past the parry!",
    "But {defender}'s guard is not quite solid enough!",
    "The impact knocks {defender}'s weapon aside!",
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
    "But {defender}'s timing is just off!",
    "The weapon tracks {defender}'s movement perfectly!",
    "{defender} overcommits and can't recover!",
    "The footwork fails {defender} at the critical moment!",
    "{defender} miscalculates the weapon's speed!",
    "The dodge leaves {defender} vulnerable!",
    "{defender} shifts the wrong way!",
    "The attack comes too fast to evade!",
    "But {defender}'s balance betrays {him}!",
    "The weapon adjusts and {defender} can't!",
    "{defender} finds no safe space to move to!",
    "The slip is incomplete and the strike catches {defender}!",
]


def defense_fail_line(defender_name: str, gender: str, uses_parry: bool) -> str:
    pronoun = "his" if gender == "Male" else "her"
    him_pronoun = "him" if gender == "Male" else "her"
    pool = DEFENSE_FAIL_PARRY if uses_parry else DEFENSE_FAIL_DODGE
    return _pool_choice(pool).format(defender=defender_name.upper(), his=pronoun, him=him_pronoun)


# ---------------------------------------------------------------------------
# LOW HP STATUS COMMENTARY
# ---------------------------------------------------------------------------

_LOW_HP_TIER1 = [   # 30–50% HP remaining
    "{warrior} is showing signs of the punishment received!",
    "{warrior} is taking this fight on the chin!",
    "The damage is starting to add up for {warrior}!",
    "{warrior} is breathing harder now!",
    "{warrior} looks like {he} could use a moment to collect {himself}!",
    "{warrior} is cut up and bleeding from multiple wounds!",
    "{warrior} moves more cautiously now, favoring {his} injuries!",
    "The accumulated damage is wearing {warrior} down!",
    "{warrior}'s movements have slowed noticeably!",
    "{warrior} is limping, {his} body crying out in protest!",
    "Each breath seems to cost {warrior} something now!",
    "{warrior} is struggling against the mounting fatigue!",
    "{warrior}'s guard is becoming ragged from the punishment!",
    "Blood drips steadily from {warrior}'s wounds!",
    "{warrior} can feel every hit {he} has taken in this bout!",
    "{warrior} is visibly hurt but still dangerous!",
    "{warrior}'s breathing is labored, the damage catching up!",
    "{warrior} moves with pain evident in every step!",
    "The crowd can see {warrior} is badly hurt!",
    "{warrior} is fighting through serious injury now!",
    "{warrior} staggers slightly between exchanges!",
    "{warrior} is bleeding and battered but refuses to quit!",
]

_LOW_HP_TIER2 = [   # 15–30% HP remaining
    "{warrior} is in serious trouble!",
    "{warrior} is covered in blood, and not all of it is the opponent's!",
    "The crowd senses {warrior} is running out of options!",
    "{warrior} is surviving on determination alone at this point!",
    "{warrior} is desperately wounded and still fighting!",
    "{warrior} looks deathly pale!",
    "{warrior} is barely holding {himself} together at this point!",
    "{warrior} is clinging to consciousness by a thread!",
    "Every movement is agony for {warrior} now!",
    "{warrior} is running on pure adrenaline!",
    "{warrior}'s vision must be swimming from blood loss!",
    "{warrior} is only moments away from collapse!",
    "{warrior} looks like {he} might fall at any second!",
    "The punishment {warrior} has endured is almost beyond belief!",
    "{warrior} is making desperate, wild swings!",
    "{warrior} cannot last much longer at this rate!",
    "{warrior} is stumbling with each step!",
    "Death stares {warrior} in the face now!",
    "{warrior} is held up by determination alone!",
    "{warrior} is in the most precarious position imaginable!",
    "{warrior} looks like a walking corpse still fighting!",
]

_LOW_HP_TIER3 = [   # below 15% HP remaining
    "{warrior} would make a corpse envious!",
    "{warrior} is drenched in blood!",
    "{warrior} is barely standing, sheer will is all that remains!",
    "The end is near for {warrior}!",
    "{warrior} staggers but somehow refuses to fall!",
    "{warrior} is one solid hit away from the Monster Bouts!",
    "{warrior} is barely conscious, held upright by pure instinct!",
    "{warrior} is at death's doorstep, one final blow away from the end!",
    "{warrior}'s body is a shattered ruin of what it once was!",
    "{warrior} is more corpse than warrior at this point!",
    "Every heartbeat seems like a miracle for {warrior}!",
    "{warrior} is operating on fumes and fading will!",
    "{warrior} looks like {he} will simply collapse any moment!",
    "The arena holds its breath, {warrior} might not take another step!",
    "{warrior} is fighting a losing battle against {his} own body!",
    "{warrior} is barely recognizable under the blood and wounds!",
    "{warrior} is teetering on the edge of oblivion!",
    "{warrior}'s last reserves of strength are nearly exhausted!",
    "{warrior} moves like a shadow of {himself}, barely there!",
    "It's a miracle {warrior} is still standing!",
    "{warrior} is held together by sheer stubborn will alone!",
    "{warrior} is a vision of horror, barely alive and fading fast!",
]


def low_hp_line(warrior_name: str, gender: str, hp_pct: float) -> Optional[str]:
    """Return a low-HP status line, or None if HP is above threshold / random skip."""
    pronoun  = "he" if gender == "Male" else "she"
    his_pronoun = "his" if gender == "Male" else "her"
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
    return _pool_choice(pool).format(
        warrior=warrior_name.upper(), he=pronoun, his=his_pronoun, himself=reflexive
    )


# ---------------------------------------------------------------------------
# COUNTERSTRIKE LINE (special attack after a successful parry)
# ---------------------------------------------------------------------------

COUNTERSTRIKE_LINES = [
    "{attacker} seizes the opening and launches a counter-attack!",
    "{attacker} turns the parry into an immediate counter!",
    "{attacker}'s counter-strike catches {foe} completely off-guard!",
    "{attacker} makes {foe} pay for the reckless attack!",
    "{attacker} capitalizes on the opening with a vicious counter-attack!",
    "{attacker} doesn't hesitate, turning the defense into a devastating strike!",
    "{attacker} pounces on the moment with immediate, brutal retaliation!",
    "{attacker} converts the parry into a counter that catches {foe} flat-footed!",
    "{attacker} pivots smoothly and drives a counter-strike home!",
    "{attacker} seizes the advantage with a lightning-fast counter!",
    "{attacker} turns the tables, striking before {foe} can recover!",
    "{attacker} responds to the parry with a counter-strike of {his} own!",
    "{attacker} explodes forward with a follow-up that {foe} never saw coming!",
    "{attacker}'s counter-strike comes with the force of pure opportunity!",
    "{attacker} leverages the parry into a perfect opening for attack!",
    "{attacker} wastes no time, unleashing a counter at full commitment!",
    "{attacker} reads the parry and attacks into the gap immediately!",
    "{attacker} transforms defense into offense with practiced efficiency!",
    "{attacker} delivers a counter that tests {foe}'s remaining composure!",
    "{attacker}'s counter-attack arrives before {foe} can set up a defense!",
    "{attacker} strikes with all {his} force, punishing {foe}'s defensive stance!",
    "{attacker} launches into a counter-strike that carries full momentum!",
]


def counterstrike_line(attacker_name: str, attacker_gender: str, foe_name: str) -> str:
    pronoun = "his" if attacker_gender == "Male" else "her"
    return _pool_choice(COUNTERSTRIKE_LINES).format(
        attacker=attacker_name.upper(), foe=foe_name.upper(), his=pronoun
    )


def counterstrike_evaded_line(attacker_name: str, attacker_gender: str, foe_name: str) -> str:
    """Narrative line for when a counterstrike attempt is evaded/dodged."""
    pronoun = "his" if attacker_gender == "Male" else "her"
    lines = [
        "{attacker}'s riposte attempt is evaded!",
        "{attacker}'s counter is sidestepped!",
        "{foe} rolls aside from {attacker}'s riposte!",
        "{attacker}'s counterstrike misses. {foe} was already moving!",
        "{foe} slips away from {attacker}'s riposte attempt!",
        "{attacker}'s counter attempt fails to connect!",
        "{foe} dances out of range of {attacker}'s riposte!",
    ]
    return _pool_choice(lines).format(
        attacker=attacker_name.upper(), foe=foe_name.upper(), his=pronoun
    )


def counterstrike_parried_line(attacker_name: str, attacker_gender: str, foe_name: str) -> str:
    """Narrative line for when a counterstrike attempt is parried."""
    pronoun = "his" if attacker_gender == "Male" else "her"
    lines = [
        "{attacker}'s riposte is parried!",
        "{foe} catches {attacker}'s counter and turns it aside!",
        "{attacker}'s counterstrike is blocked cleanly!",
        "{foe} reads {attacker}'s riposte and shuts it down!",
        "{attacker}'s counter is deflected!",
        "{foe} parries {attacker}'s riposte with skill!",
    ]
    return _pool_choice(lines).format(
        attacker=attacker_name.upper(), foe=foe_name.upper(), his=pronoun
    )


def counterstrike_missed_line(attacker_name: str, attacker_gender: str, foe_name: str) -> str:
    """Narrative line for when a counterstrike attempt completely misses."""
    pronoun = "his" if attacker_gender == "Male" else "her"
    lines = [
        "{attacker}'s counterstrike misses!",
        "{attacker}'s riposte goes wide!",
        "{foe} pulls away and {attacker}'s counter finds only air!",
        "{attacker}'s counter attempt fails to connect!",
    ]
    return _pool_choice(lines).format(
        attacker=attacker_name.upper(), foe=foe_name.upper(), his=pronoun
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
    "{attacker} feints one way, strikes another, and {foe} commits to the wrong defense!",
    "{attacker}'s deception is perfect, {foe} moves to block the false strike!",
    "{attacker} draws {foe}'s guard high with a shoulder fake!",
    "{attacker} reads {foe}'s instincts and exploits them with a clever ruse!",
    "{attacker}'s misdirection leaves {foe} exposed and off-balance!",
    "{attacker} uses a brilliant feint to move {foe}'s guard out of position!",
    "{attacker} tricks {foe} into overcommitting to a false threat!",
    "{attacker}'s subtle movement sends {foe} in the wrong direction!",
    "{attacker} exploits {foe}'s reflex with a perfectly-timed feint!",
    "{attacker}'s deception creates the opening {he} needs!",
    "{attacker} sets up the real attack with a convincing fake!",
    "{attacker} uses his understanding of {foe} to set a perfect trap!",
    "{attacker} feints brilliantly and {foe} takes the bait!",
    "{attacker}'s misdirection is expert-level, {foe} doesn't stand a chance!",
    "{attacker} reads {foe} like a book and uses deception to strike true!",
    "{attacker}'s feint is so convincing that {foe} can't react in time!",
]

DECOY_FEINT_READ_LINES = [
    "{foe} reads the feint and holds position, unshaken!",
    "{foe} anticipates the trick, and the ruse falls flat!",
    "{foe} sees through {attacker}'s misdirection!",
    "{foe} isn't fooled by the misdirection and holds fast!",
    "{foe} reads through the deception and maintains position!",
    "{foe} sees the trap and refuses to take the bait!",
    "{foe} anticipates the true strike and doesn't fall for the feint!",
    "{foe}'s experience protects {him} from the ruse!",
    "{foe} keeps {his} guard where it needs to be!",
    "{foe} doesn't commit to the fake and stays ready!",
    "{foe} recognizes the misdirection and adapts instantly!",
    "{foe} is too clever to fall for such a simple trick!",
    "{foe}'s discipline keeps {him} from reacting to the feint!",
    "{foe} sees right through {attacker}'s deception!",
    "{foe} refuses to move {his} guard where the feint suggests!",
    "{foe}'s focus is unshakeable, the ruse fails completely!",
    "{foe} doesn't bite on the bait, staying perfectly positioned!",
    "{foe} reads {attacker}'s intent and remains unmoved!",
    "{foe}'s superior awareness defeats the misdirection!",
    "{foe} stands firm, ignoring the false threat entirely!",
    "{foe}'s instincts are too good for such tricks!",
    "{foe} calls the bluff and maintains the perfect defense!",
]


def decoy_feint_line(attacker_name: str, foe_name: str, attacker_gender: str = "Male") -> str:
    he = "he" if attacker_gender == "Male" else "she"
    return _pool_choice(DECOY_FEINT_SUCCESS_LINES).format(
        attacker=attacker_name.upper(), foe=foe_name.upper(), he=he,
    )


def decoy_feint_read_line(attacker_name: str, foe_name: str, foe_gender: str = "Male") -> str:
    pronoun = "his" if foe_gender == "Male" else "her"
    him_pronoun = "him" if foe_gender == "Male" else "her"
    return _pool_choice(DECOY_FEINT_READ_LINES).format(
        attacker=attacker_name.upper(), foe=foe_name.upper(), his=pronoun, him=him_pronoun
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
    "{attacker} carefully measures the distance but the opening closes!",
    "{attacker} tries a calculated strike that {foe} shuts down!",
    "{attacker}'s methodical approach yields no opening this moment!",
    "{attacker} looks for the gap but {foe}'s defense is absolute!",
    "{attacker} takes {his} time setting up, but the opportunity passes!",
    "{attacker} calculates the angles but finds {foe} well-prepared!",
    "{attacker} probes with precision but hits nothing but steel!",
    "{attacker}'s patient searching finds only a solid wall of defense!",
    "{attacker} seeks the weakness but {foe} has none to exploit!",
    "{attacker} plans the strike carefully but {foe} doesn't cooperate!",
    "{attacker} focuses intently but the exact opening never materializes!",
    "{attacker} studies {foe}'s movements with cold calculation, then withdraws without striking!",
    "{attacker}'s analytical gaze finds {foe} too well-balanced to assault!",
    "{attacker} waits for the perfect moment, but it slips away!",
    "{attacker} dissects {foe}'s stance, finding no clear advantage!",
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
    return _pool_choice(pool).format(
        attacker=attacker_name.upper(),
        foe=foe_name.upper(),
        weapon=weapon_name.lower(),
        his=his
    )


def calculated_probe_line(attacker_name: str, attacker_gender: str, foe_name: str) -> str:
    pronoun = "his" if attacker_gender == "Male" else "her"
    return _pool_choice(CALCULATED_PROBE_LINES).format(
        attacker=attacker_name.upper(), foe=foe_name.upper(), his=pronoun
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
    "{warrior} is brutally slammed to the ground with terrifying force!",
    "{warrior} crashes down hard, the impact driving the air from {his} lungs!",
    "{warrior} is thrown violently to the arena floor in a cloud of dust!",
    "{warrior} tumbles hard across the sand, unable to control the descent!",
    "{warrior} is sent sprawling with a bone-jarring impact!",
    "{warrior} hits the ground so hard the arena floor shakes!",
    "{warrior} is knocked completely off-balance and crashes down!",
    "{warrior} slams into the sand with crushing, awful force!",
    "{warrior} is dropped to the arena floor like a sack of grain!",
    "{warrior} plummets to the ground in a violent tangle of limbs!",
    "{warrior} takes a horrific fall, the impact echoing through the stands!",
    "{warrior} is sent crashing down with an impact that rattles teeth!",
    "{warrior} collapses to the arena floor under an overwhelming assault!",
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
    "{warrior} pushes up from the ground with grim determination!",
    "{warrior} staggers to {his} feet, refusing to stay down!",
    "{warrior} hauls {himself} upright, shaking off the impact!",
    "{warrior} claws {his} way back to standing, bloodied but unbroken!",
    "{warrior} rises from the sand with {his} resolve intact!",
    "{warrior} gets up slowly, every muscle screaming in protest!",
    "{warrior} forces {himself} vertical, jaw clenched with defiance!",
    "{warrior} climbs back to {his} feet with hard-won determination!",
    "{warrior} shakes the dust from {his} shoulders and stands again!",
    "{warrior} staggers upright, chest heaving with ragged breaths!",
    "{warrior} gets back to {his} feet, eyes blazing with renewed intensity!",
    "{warrior} rises defiantly, the arena's roar fueling {his} return!",
    "{warrior} pushes up from the bloodied sand with stubborn pride!",
    "{warrior} gets up, battered but far from finished!",
    "{warrior} hauls {his} body vertical, ready for whatever comes next!",
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
    "{warrior} thrashes helplessly as the assault continues relentlessly!",
    "{warrior} struggles in the sand but cannot break free!",
    "{warrior} fights desperately to regain {his} footing, but the pressure won't let up!",
    "{warrior} gasps for air as {he} claws at the sand, still pinned down!",
    "{warrior} tries with all {his} might to stand, but {his} opponent gives no quarter!",
    "{warrior} writhes on the bloodied arena floor, desperately seeking an escape!",
    "{warrior} pushes against the onslaught but cannot find the strength to rise!",
    "{warrior} struggles to find purchase on the slick, blood-soaked sand!",
    "{warrior} kicks out from the ground in a futile bid to create distance!",
    "{warrior} fights to get up but is driven down again by the assault!",
    "{warrior} frantically scrambles but the relentless barrage keeps {him} grounded!",
    "{warrior} tries to push up, gasping and bleeding into the sand!",
    "{warrior} struggles against {his} opponent's overwhelming pressure!",
    "{warrior} thrashes but cannot escape the continuing onslaught!",
    "{warrior} claws desperately at the ground, unable to regain {his} feet!",
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
    "{warrior} launches an upward strike from the ground with surprising force!",
    "{warrior} throws a vicious blow from {his} back!",
    "{warrior} strikes out desperately, refusing to go down without a fight!",
    "{warrior} hurls a wild haymaker from the arena floor!",
    "{warrior} connects with a low, hard strike from the sands!",
    "{warrior} kicks upward in a last-ditch offensive effort!",
    "{warrior} slams an elbow strike from {his} grounded position!",
    "{warrior} thrusts a counter-strike from the bloodied sands!",
    "{warrior} snaps out a quick strike while scrambling for position!",
    "{warrior} throws a desperate punch from the ground in defiance!",
    "{warrior} launches a grappling counter from {his} back!",
    "{warrior} strikes with {his} legs, still refusing to yield!",
    "{warrior} delivers a brutal strike from a desperate, ground-based position!",
    "{warrior} attacks upward with raw desperation and remaining strength!",
    "{warrior} throws a wild strike from the sand, making {his} presence felt!",
]


def knockdown_line(warrior_name: str, gender: str) -> str:
    pronoun = "his" if gender == "Male" else "her"
    template = _pool_choice(KNOCKDOWN_LINES)
    return template.format(warrior=warrior_name.upper(), his=pronoun)


def getup_line(warrior_name: str, gender: str) -> str:
    pronoun = "his" if gender == "Male" else "her"
    template = _pool_choice(GET_UP_LINES)
    return template.format(warrior=warrior_name.upper(), his=pronoun)


def ground_struggle_line(warrior_name: str, gender: str) -> str:
    """Failed recovery attempt - warrior tries to get up but can't."""
    pronoun = "his" if gender == "Male" else "her"
    him_pronoun = "him" if gender == "Male" else "her"
    he_pronoun = "he" if gender == "Male" else "she"
    return _pool_choice(GROUND_STRUGGLE_LINES).format(
        warrior=warrior_name.upper(), his=pronoun, him=him_pronoun, he=he_pronoun)


def ground_attack_line(warrior_name: str, gender: str) -> str:
    """Warrior attacks from the ground after failing to rise."""
    pronoun = "his" if gender == "Male" else "her"
    return _pool_choice(GROUND_ATTACK_LINES).format(
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
        return _pool_choice(pool.get(key, [f"{warrior_name.upper()} is gravely wounded!!!"])).format(
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
    
    return [_pool_choice(pools), secondary.get(location, "The pain is debilitating!")]


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
            f"The power behind the blow is simply too much. {n}'s {wpn} is torn clean from the grip!",
            f"A bone-jarring blow jars the {wpn} loose from {n}'s grasp!",
            f"The brutal weight of the attack hammers the {wpn} from {n}'s numbed fingers!",
            f"The sheer violence of the blow sends the {wpn} spinning from {n}'s grip!",
            f"A thunderous strike rattles {n}'s arms, sending the {wpn} flying to the sand!",
            f"The impact travels straight up {n}'s arms and the {wpn} is torn free!",
            f"Strength against strength, and {n} is outmatched. The {wpn} is ripped away and crashes to the ground!",
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
            f"Footing lost, focus lost. {n}'s {wpn} lands in the dirt!",
            f"The {wpn} tears loose and skids across the sand!",
        ]
    return "   " + _pool_choice(pools)


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
    return "   " + _pool_choice(pools)


# ---------------------------------------------------------------------------
# FATIGUE / ENDURANCE LINES
# ---------------------------------------------------------------------------

FATIGUE_LINES = [
    "{warrior}'s desire to win may not be enough",
    "{warrior} is visibly tiring",
    "{warrior} slows noticeably",
    "{warrior}'s movements are heavy with exhaustion",
    "{warrior}'s breath comes harder now",
    "{warrior}'s movements are becoming sluggish",
    "{warrior} feels the weight of the fight accumulating",
    "{warrior}'s body is screaming for rest",
    "{warrior} is operating on diminishing energy",
    "{warrior}'s attacks lack their earlier snap",
    "{warrior} staggers slightly between exchanges",
    "{warrior}'s pace is slowing with each breath",
    "Fatigue is beginning to work against {warrior}",
    "{warrior}'s recovery time is lengthening noticeably",
    "{warrior} shakes out cramping arms",
    "{warrior}'s movements show the strain of the battle",
    "{warrior} takes a moment to steady {himself}",
    "{warrior}'s endurance is being tested",
    "{warrior} breathes heavily, fighting through discomfort",
    "{warrior}'s reactions are becoming delayed",
]

EXHAUSTED_LINES = [
    "{warrior} is fighting with pure will power!",
    "{warrior} staggers forward on empty reserves!",
    "{warrior} can barely lift {his} weapon!",
    "{warrior} is running on fumes!",
    "{warrior} is on the absolute edge of collapse!",
    "{warrior} moves like a marionette on strings!",
    "{warrior} can barely stay conscious!",
    "{warrior} is barely functional!",
    "{warrior}'s eyes are unfocused and distant!",
    "{warrior} swings on autopilot alone!",
    "{warrior} is operating on instinct alone!",
    "{warrior} is one moment away from breaking!",
    "{warrior}'s breathing is ragged and desperate!",
    "{warrior} looks ready to fall at any second!",
    "{warrior} is hollow, just a shell continuing forward!",
    "{warrior} moves through sheer stubborn refusal to yield!",
    "{warrior} is past human endurance!",
    "{warrior} is fighting against {his} own failing body!",
    "{warrior}'s movements are mechanical and desperate!",
    "{warrior} is at the absolute limit of what a body can endure!",
]

SECOND_WIND_LINES = [
    "{warrior} breathes through the pain, letting technique carry {him}",
    "{warrior} strips away the noise as every motion becomes deliberate and nothing is wasted.",
    "{warrior} slows {his} breathing, drawing on hard-won discipline",
    "{warrior} narrows to pure fundamentals as the body screams to stop",
    "{warrior} finds something deep inside and pushes forward renewed!",
    "{warrior}'s will hardens as {his} body finds fresh reserves!",
    "{warrior} draws on hidden strength, moving with fresh purpose!",
    "{warrior} refuses to yield, finding clarity in exhaustion!",
    "A fire rekindled in {warrior}'s eyes as {he} presses on!",
    "{warrior}'s second wind carries {him} beyond the breaking point!",
    "{warrior} finds {his} rhythm again despite the fatigue!",
    "{warrior} channels pain into precision, moving with renewed intensity!",
    "{warrior} breaks through the wall of exhaustion with sheer determination!",
    "{warrior} seems to draw strength from the very edge of defeat!",
    "{warrior} straightens up, moving with the focus of a killer!",
    "{warrior} stops fighting {his} body and surrenders to the moment!",
    "{warrior} finds {his} center and moves with crystalline clarity!",
    "{warrior}'s second wind is more dangerous than {his} first!",
    "{warrior} doesn't slow; {he} shifts to a higher gear!",
    "{warrior} transcends exhaustion through sheer mental fortitude!",
]

ENDURANCE_DRAIN_LINES = [
    "{warrior} drains the fight out of {foe}",
    "{warrior}'s patient style wears on {foe}",
    "{warrior}'s relentless pressure tires {foe}",
    "{warrior}'s steady pace is grinding {foe} down",
    "Every moment of the fight costs {foe} dearly",
    "{warrior} is methodically exhausting {foe}'s stamina",
    "{foe} can feel {his} energy slipping away with each exchange",
    "{warrior} is an anchor of persistent pressure on {foe}",
    "The clock and {warrior} are both working against {foe} now",
    "{warrior}'s refusal to relent is bleeding {foe} dry",
    "{foe} is losing ground to {warrior}'s endurance",
    "{warrior} outlasts {foe} through sheer tested will",
    "The effort required to face {warrior} is consuming {foe}",
    "{warrior} fights like {he} has all the time in the world",
    "{foe} struggles as {warrior} shows no signs of fatigue",
    "{warrior}'s calm, persistent assault wears on {foe}'s resolve",
    "{foe} cannot match {warrior}'s inexhaustible reserves",
    "With each passing moment, the advantage swings further to {warrior}",
    "{warrior}'s stamina is a weapon {foe} simply cannot overcome",
    "{foe} is drowning in the tide of {warrior}'s relentless pace",
]


def fatigue_line(warrior_name: str, gender: str, very_tired: bool = False,
                 is_aggressive: bool = True) -> str:
    pronoun_his = "his" if gender == "Male" else "her"
    pronoun_him = "him" if gender == "Male" else "her"
    pronoun_he  = "he"  if gender == "Male" else "she"
    pronoun_himself = "himself" if gender == "Male" else "herself"
    if very_tired:
        pool = EXHAUSTED_LINES if is_aggressive else SECOND_WIND_LINES
    else:
        pool = FATIGUE_LINES
    return _pool_choice(pool).format(
        warrior=warrior_name.upper(), his=pronoun_his, him=pronoun_him,
        he=pronoun_he, himself=pronoun_himself,
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
    "short_sword": "slashing", "scimitar": "slashing", "long_sword": "slashing",
    "broad_sword": "slashing", "bastard_sword": "slashing", "great_sword": "slashing",
    "hatchet": "slashing", "francisca": "slashing", "battle_axe": "slashing",
    "great_axe": "slashing", "pole_axe": "slashing", "halberd": "slashing",
    "scythe": "slashing", "bladed_flail": "slashing", "heavy_whip": "slashing",
    "swordbreaker": "slashing", "net": "slashing",
    # Crushing
    "hammer": "crushing", "mace": "crushing", "morningstar": "crushing",
    "war_hammer": "crushing", "maul": "crushing", "club": "crushing",
    "quarterstaff": "crushing", "great_staff": "crushing",
    "flail": "crushing", "war_flail": "crushing", "battle_flail": "crushing",
    "ball_and_chain": "crushing", "cestus": "crushing", "open_hand": "crushing",
    "buckler": "crushing", "target_shield": "crushing", "tower_shield": "crushing",
    "bola": "crushing",
}


def get_damage_type(weapon_skill_key: str) -> str:
    """Return 'slashing', 'piercing', or 'crushing' for a weapon skill key."""
    return _WEAPON_DAMAGE_TYPES.get(weapon_skill_key.lower(), "crushing")


CRITICAL_HIT_SLASHING = [
    "{attacker} finds the opening in {defender}'s guard!",
    "{attacker}'s {weapon} finds an unguarded line!",
    "{attacker} reads {defender}'s guard, striking where it fails!",
    "The edge of {attacker}'s {weapon} finds the gap {defender} couldn't cover!",
    "{attacker} commits fully to the stroke!",
    "{attacker} catches {defender} in transition with a perfectly timed stroke!",
    "{attacker}'s {weapon} sweeps in at the worst moment for {defender}!",
    "{attacker} cuts down {defender}'s guard!",
    "{attacker}'s stroke arrives exactly where {defender}'s guard is not!",
    "{attacker} strikes into {defender}'s step!",
    "{attacker} waits for the gap, then strikes!",
    "{attacker}'s {weapon} cuts through {defender}'s defense!",
    "{attacker} drives the stroke home with everything behind it!",
    "{defender}'s guard is a half-beat late!",
    "{attacker}'s {weapon} finds {defender} exactly wrong-footed!",
    "{attacker} swings through the gap in {defender}'s defense!",
    "{attacker}'s timing is perfect!",
    "The stroke from {attacker} lands with total commitment!",
    "{attacker} punishes the slip in {defender}'s guard!",
    "{attacker} tears into the hole in {defender}'s defense!",
    "{attacker}'s {weapon} rips through the opening in {defender}'s guard!",
    "{attacker} hacks through {defender}'s defense with vicious force!",
    "{attacker} swings hard into the gap!",
    "{attacker}'s {weapon} tears past {defender}'s guard!",
    "{attacker} lashes out with ruthless speed, catching {defender} flat-footed!",
]

CRITICAL_HIT_PIERCING = [
    "{attacker}'s {weapon} threads through {defender}'s defense!",
    "A blindingly fast thrust from {attacker} catches {defender} in transition!",
    "{attacker} turns the point at the last instant!",
    "{attacker} waits for the gap, then drives the point home!",
    "One perfectly timed thrust from {attacker} catches {defender} at the worst moment!",
    "{attacker} moves the point on a line {defender} cannot see!",
    "The point of {attacker}'s {weapon} arrives where no defense exists!",
    "{attacker}'s thrust slips past {defender}'s guard!",
    "{attacker} finds the gap with the point!",
    "The point finds {defender} before the defense can close!",
    "{attacker} lunges with ruthless timing!",
    "A hard, deadly thrust from {attacker} finds its mark!",
    "{attacker}'s {weapon} punches through {defender}'s guard!",
    "{attacker} commits to a thrust that nothing can stop!",
    "{attacker} reads {defender}'s movement, striking true!",
    "{attacker}'s point arrives a half-beat before the guard!",
    "{attacker} drives the point through the opening!",
    "The thrust from {attacker} lands with total commitment!",
    "{attacker} exploits the smallest opening!",
    "{attacker}'s {weapon} strikes with deadly intent!",
    "{attacker}'s {weapon} lashes through {defender}'s defense!",
    "{attacker} stabs hard into the gap!",
    "{attacker} drives the point in with vicious force!",
    "The point of {attacker}'s {weapon} rips past {defender}'s guard!",
    "{attacker} lunges in hard, catching {defender} off guard!",
]

CRITICAL_HIT_CRUSHING = [
    "{attacker}'s {weapon} arrives with total commitment!",
    "The strike from {attacker} lands where {defender}'s defense doesn't reach!",
    "{attacker} strikes from an angle {defender}'s guard cannot absorb!",
    "{attacker}'s {weapon} finds {defender} off balance!",
    "{attacker} drops the blow into a gap {defender} cannot close!",
    "{attacker}'s blow lands with bone-rattling weight!",
    "{attacker} puts everything behind the blow!",
    "The blow from {attacker} breaks through {defender}'s guard!",
    "{attacker}'s timing catches {defender} at the worst moment!",
    "The impact of {attacker}'s strike echoes across the arena!",
    "{attacker} commits fully to the blow!",
    "{defender}'s defense is a half-beat too slow!",
    "{attacker}'s {weapon} lands flush!",
    "{attacker} drives the blow through the opening!",
    "{defender}'s guard cannot withstand {attacker}'s blow!",
    "{attacker} catches {defender} fully extended!",
    "{attacker}'s strike lands with terrible weight!",
    "The crowd winces as {attacker}'s blow lands flush!",
    "{attacker}'s {weapon} lands with unstoppable force!",
    "{attacker} delivers the blow {defender} never saw coming!",
    "{attacker}'s {weapon} slams through {defender}'s guard!",
    "{attacker} puts all {his} weight behind the blow!",
    "{attacker} hammers the blow home with brutal force!",
    "{attacker} crashes through {defender}'s defense!",
    "{attacker} swings with savage intent!",
]

CRITICAL_HIT_LINES: dict[str, list[str]] = {
    "slashing": CRITICAL_HIT_SLASHING,
    "piercing": CRITICAL_HIT_PIERCING,
    "crushing": CRITICAL_HIT_CRUSHING,
}

# ---------------------------------------------------------------------------
# PARRY PENETRATION (Cleave / Bash skill breaks through a parry)
# {name} = defender (capitalised), {loc} = body part hit
# ---------------------------------------------------------------------------

PARRY_CLEAVE_LINES = [
    "   The powerful strike cleaves through the parry, splitting into {name}'s {loc}!",
    "   The heavy edge carves straight through {name}'s parry and bites into the {loc}!",
    "   {name}'s parry is hewn aside as the blow chops into the {loc}!",
    "   The blow rips through the guard and sinks into {name}'s {loc}!",
    "   Nothing {name} raises can stop the chop, which crashes into the {loc}!",
    "   The parry is cut apart and the weapon hews into {name}'s {loc}!",
    "   The strike drives through {name}'s defense and cleaves into the {loc}!",
    "   {name}'s block is chopped to pieces, and the edge finds the {loc}!",
]

PARRY_BASH_LINES = [
    "   The powerful strike bashes through the parry, crushing into {name}'s {loc}!",
    "   The crushing blow batters {name}'s parry aside and slams into the {loc}!",
    "   {name}'s guard is smashed open as the weapon hammers into the {loc}!",
    "   The blow bulls straight through the parry and crashes into {name}'s {loc}!",
    "   Nothing {name} raises can stop the impact, which pounds into the {loc}!",
    "   The parry is battered down and the weapon thuds into {name}'s {loc}!",
    "   The strike overwhelms {name}'s defense and caves in the {loc}!",
    "   {name}'s block is hammered flat, and the blow lands on the {loc}!",
]

PARRY_GUARD_SPLIT_LINES = [
    "   {name}'s guard is split apart by the blow and will not hold as well again!",
    "   {name}'s defense is left ragged and weakened by the force of it!",
    "   The blow leaves {name}'s guard hanging in pieces!",
    "   {name}'s weapon arm rings from the impact, and the next parry will be harder!",
    "   {name}'s guard is badly shaken and slow to come back up!",
    "   Something gives in {name}'s defense, and it will not be as solid again!",
]

PARRY_BASH_WIND_LINES = [
    "   The blow knocks the wind out of {name}!",
    "   {name} gasps as the air is driven from the lungs!",
    "   {name} doubles over, breath gone!",
    "   The impact leaves {name} struggling to draw a breath!",
    "   {name} reels, winded by the crushing force!",
    "   A grunt escapes {name} as the breath is forced out!",
]


def parry_penetration_line(kind: str, defender_name: str, loc: str) -> str:
    """kind: 'cleave', 'bash', 'guard' (guard splintered) or 'wind' (bash winds the defender)."""
    pool = {"cleave": PARRY_CLEAVE_LINES, "bash": PARRY_BASH_LINES,
            "guard": PARRY_GUARD_SPLIT_LINES, "wind": PARRY_BASH_WIND_LINES}[kind]
    return _pool_choice(pool).format(name=defender_name.title(), loc=loc)


CRITICAL_PARRY_LINES = [
    "{defender} catches {attacker}'s strike at the perfect angle and redirects it completely. The precise parry draws an immediate murmur from the crowd.",
    "With something approaching artistry, {defender} meets the blow dead-center, folding it harmlessly aside with textbook form under the worst conditions.",
    "{defender} deflects the incoming strike with effortless grace, turning a moment of pure desperation into a showcase of perfect muscle memory..",
    "The parry from {defender} is unhurried and exact, catching the incoming blow and neutralizing it with minimal effort.",
    "{defender} reads {attacker}'s angle a breath early, setting up a counter that rings out sharp and clean as the attack finds nothing.",
    "{defender} turns the blow aside with a contemptuous parry, already poised for the next step.",
    "{defender} reads the attack like a book and parries with textbook precision!",
    "{defender}'s parry is executed with such grace it barely seems an effort!",
    "{defender} catches the blow at the perfect angle, neutralizing all force!",
    "{defender} deflects the strike with a confidence that silences the crowd momentarily!",
    "{defender}'s parry is a masterclass in timing and positioning!",
    "{defender} meets the attack head-on and turns it aside with controlled power!",
    "{defender} executes a parry so clean it draws appreciative murmurs!",
    "{defender} anticipates the strike and is already in perfect position!",
    "{defender}'s defensive brilliance is on full display!",
    "{defender} catches and redirects the blow with minimal effort!",
    "{defender} parries with the confidence of a veteran warrior!",
    "{defender}'s parry is quick, sharp, and absolutely precise!",
    "{defender} neutralizes the threat with a parry of supreme technique!",
    "{defender} reads the angle perfectly and meets it with an expert parry!",
    "{defender} executes a parry that looks almost casual in its competence!",
    "{defender}'s response is immediate and perfectly calibrated!",
]

CRITICAL_DODGE_LINES = [
    "{defender} is no longer where the blow lands, an effortless movement where timing is everything.",
    "The attack passes through space that {defender} vacated a half-second earlier, the move so clean the crowd takes a moment to register it.",
    "{defender} smoothly steps off the line of attack without a hint of panic, letting the blow sail harmlessly past.",
    "An impossible read. {defender} begins moving before {attacker}'s commitment is visible, leaving the attack with nothing to find.",
    "{defender} slips the blow with unhurried economy that looks like instinct and takes years to learn.",
    "Not a dodge so much as an erasure. {defender} is simply not where {attacker} aimed, and there's nothing lucky about it.",
    "{defender} glides effortlessly out of the strike's path!",
    "{defender}'s footwork is absolutely flawless, the blow missing by inches!",
    "{defender} anticipates and moves before the attack even commits!",
    "{defender} flows like water around the incoming strike!",
    "{defender}'s dodge is executed with perfect economy of motion!",
    "{defender} slips the blow with the instincts of a master!",
    "{defender} is exactly where safety is, the attack finding nothing!",
    "{defender}'s positioning makes the strike pass harmlessly by!",
    "{defender} moves with such grace that the crowd holds its breath!",
    "{defender} reads the attack and is gone before it arrives!",
    "{defender}'s evasion is a study in perfect reflexes!",
    "{defender} sidesteps with minimal movement, pure efficiency!",
    "{defender} avoids the strike with the skill of years of training!",
    "{defender}'s dodge creates the opening {he} needs!",
    "{defender} evades with such confidence it looks rehearsed!",
    "{defender} moves just enough, turning the miss into an advantage!",
]

CRITICAL_DISARM_LINES = [
    "The parry catches {attacker}'s {weapon} at exactly the wrong angle. {defender} twists on contact, and the weapon wrenches free, spinning into the sand!",
    "{defender} redirects the blow and seizes the leverage immediately, a sharp rotation sending {attacker}'s {weapon} tumbling from the grip, and the crowd erupts!",
    "The parry traps the weapon and {defender} presses home. {attacker}'s {weapon} flies free with a sound like a broken lock, and the pit falls momentarily silent.",
    "The parry is perfect, and {attacker}'s {weapon} goes tumbling from {his} grip!",
    "{defender}'s expert parry torques {attacker}'s {weapon} right out of {his} hand!",
    "{attacker} loses {his} grip as {defender} wrenches the {weapon} free!",
    "The {weapon} spins away as {defender}'s parry disarms {attacker} completely!",
    "{defender}'s counter-parry sends {attacker}'s {weapon} flying into the sand!",
    "{attacker} is left empty-handed as {defender} claims the {weapon}!",
    "A brilliant disarm! {attacker}'s {weapon} flies free and {defender} seizes control!",
    "{attacker} staggers back weaponless as the {weapon} clatters across the pit!",
    "{defender}'s parry is so perfectly executed that the {weapon} wrenches free!",
    "The {weapon} goes spinning away as {attacker} realizes {he}'s been disarmed!",
    "{defender} reads the strike and redirects it into a flawless disarm!",
    "{attacker}'s {weapon} tumbles through the air, lost to {defender}'s superior technique!",
    "A perfectly-timed parry leaves {attacker} staring at empty hands!",
    "{defender} uses the parry to torque and disarm {attacker} in one fluid motion!",
    "The {weapon} is wrenched free as {defender}'s parry becomes a disarm!",
    "{attacker} loses {his} {weapon} to a parry of absolute perfection!",
    "{defender}'s skillful parry transforms into a devastating disarm!",
    "The {weapon} escapes {attacker}'s grip as {defender}'s technique proves superior!",
    "{attacker} is left defenseless as {defender} seizes the {weapon}!",
]

CRITICAL_BREAK_LINES = [
    "{attacker}'s {weapon} meets a perfectly braced parry and something in the metal gives. A crack, then another, and the weapon fails completely.",
    "The {weapon} shatters against {defender}'s guard with a deafening crack that silences the crowd, sending sharp fragments raining down onto the sand.",
    "The flawless parry shatters {attacker}'s {weapon} entirely, shocking the crowd into a brief silence before a massive roar breaks out.",
    "{attacker}'s {weapon} shatters against {defender}'s perfect parry!",
    "The {weapon} breaks under the force of {defender}'s expert defense!",
    "{attacker} watches in horror as {his} {weapon} splinters and fails!",
    "A crack rings out as {attacker}'s {weapon} breaks completely!",
    "The {weapon} cannot withstand {defender}'s parry and shatters into pieces!",
    "{defender}'s flawless parry breaks {attacker}'s {weapon} in two!",
    "The {weapon} snaps under the perfect counter-parry!",
    "{attacker} is left holding a broken stub as the {weapon} fails completely!",
    "A loud crack! {attacker}'s {weapon} breaks and falls to the sand!",
    "{defender}'s parry is so perfect that {attacker}'s {weapon} cannot survive it!",
    "The {weapon} fragments under the force of {defender}'s technique!",
    "A spectacular failure! {attacker}'s {weapon} shatters into useless pieces!",
    "{attacker}'s {weapon} breaks from the impact of {defender}'s superior parry!",
    "The {weapon} crumbles as {defender}'s defense proves unbeatable!",
    "{attacker} staggers back holding a broken {weapon}!",
    "{defender}'s expert parry breaks the {weapon} and changes everything!",
    "The {weapon} explodes into fragments as {defender}'s parry holds!",
    "{attacker}'s {weapon} shatters spectacularly, leaving {him} defenseless!",
    "A catastrophic weapon failure! {attacker}'s {weapon} is destroyed by {defender}'s parry!",
]

CRITICAL_DOUBLE_COUNTER_LINES = [
    "{defender} flows out of the dodge directly into the attack. Two strikes, no pause, moving like water downhill.",
    "{defender} slips the blow and drives inside the guard, answering instantly with a fluid double-strike.",
    "Slipping the blow opens something and {defender} takes it immediately, one motion into another, two swift strikes before the window closes.",
    "{defender} flows into the counterattack with flawless precision, striking twice before {attacker} can reset!",
    "{defender} slips the blow and responds with a devastating two-strike combination!",
    "{defender} evades and immediately launches a dual assault, the second strike already in motion!",
    "Dodge becomes attack as {defender} counters with a rapid barrage of two strikes!",
    "{defender} reads the attack perfectly and answers with twin blows that connect seamlessly!",
    "The slip opens everything and {defender} takes it, attacking twice in one fluid motion!",
    "{defender} sidesteps and drives a twin counter that flows like water downhill!",
    "In one continuous motion, {defender} avoids and unleashes a back-to-back double strike!",
    "{defender} moves out of the way and pivots into a two-strike retaliation!",
    "The dodge leaves {attacker} exposed and {defender} presses home with a relentless double attack!",
    "{defender} reads the opening and doesn't hesitate, two strikes in rapid succession!",
    "Evading the blow puts {defender} in perfect position for a crushing two-strike counter!",
    "{defender}'s counterattack is a blur, two strikes flowing from one moment of perfect defense!",
    "The dodge is just the opening {defender} needs for a devastating two-strike barrage!",
    "{defender} slips clear and responds with a perfectly-timed dual counter, both strikes landing!",
    "In a moment of perfect synchronization, {defender} evades and attacks twice without pause!",
    "{defender} flows from defense into a two-strike offense that catches {attacker} completely off guard!",
    "The miss is {defender}'s opportunity and {he} takes it, two swift counterattacks in succession!",
    "{defender} sidesteps with precision and unleashes a twin strike combination that's brutal in its efficiency!",
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
    return _pool_choice(pool).format(
        attacker=attacker_name.upper(), defender=defender_name.upper(),
        weapon=weapon_name, his=his, his_her=his_her, he=he, him=him, himself=himself,
    )


def critical_parry_line(defender_name: str, attacker_name: str) -> str:
    return _pool_choice(CRITICAL_PARRY_LINES).format(
        defender=defender_name.upper(), attacker=attacker_name.upper(),
    )


def critical_dodge_line(defender_name: str, attacker_name: str, defender_gender: str = "Male") -> str:
    he = "he" if defender_gender == "Male" else "she"
    return _pool_choice(CRITICAL_DODGE_LINES).format(
        defender=defender_name.upper(), attacker=attacker_name.upper(), he=he,
    )


def critical_disarm_line(defender_name: str, attacker_name: str, weapon_name: str, attacker_gender: str = "Male") -> str:
    his = "his" if attacker_gender == "Male" else "her"
    he  = "he"  if attacker_gender == "Male" else "she"
    return _pool_choice(CRITICAL_DISARM_LINES).format(
        defender=defender_name.upper(), attacker=attacker_name.upper(),
        weapon=weapon_name, his=his, he=he,
    )


# Martial Combat (unarmed) disarms. The martial fighter is the one with the bare hands.
# {attacker} = the martial fighter, {defender} = the armed warrior who loses the weapon.
MARTIAL_DISARM_LINES = [
    "{attacker} snaps a bare-handed strike into {defender}'s wrist, and the {weapon} is wrenched out of the grip!",
    "A hard chop from {attacker}'s open hand knocks the {weapon} clean from {defender}'s fingers!",
    "{attacker} steps inside and drives a palm into {defender}'s forearm, and the {weapon} goes skidding across the sand!",
    "The martial strike hammers {defender}'s hand, and the {weapon} tumbles from the numbed grip!",
    "{attacker} traps {defender}'s weapon arm with an open hand and tears the {weapon} free!",
    "A brutal open-handed blow to the elbow sends the {weapon} spinning away from {defender}!",
    "{defender} grips the {weapon} too late. {attacker}'s bare hand strikes first and the weapon is gone!",
    "Empty hands, sharp timing. {attacker} disarms {defender} with a single martial strike!",
]

# Martial Combat as the defence: the unarmed fighter's counter knocks the attacker's weapon away.
# {defender} = the martial fighter, {attacker} = the warrior who loses the weapon.
MARTIAL_CRITICAL_DISARM_LINES = [
    "{defender} meets the attack with an open palm and drives it into {attacker}'s wrist. The {weapon} flies free!",
    "The strike is caught bare-handed, and {defender} twists {attacker}'s arm until the {weapon} is torn away!",
    "{defender}'s open-hand counter cracks against {attacker}'s knuckles, and the {weapon} clatters into the sand!",
    "{attacker} swings, {defender} steps inside, and a martial chop tears the {weapon} from {his} grip!",
    "A perfect bare-handed block turns into a strike, and {attacker}'s {weapon} goes spinning off the arena floor!",
    "{defender} ignores the weapon entirely and breaks {attacker}'s grip with a palm strike. The {weapon} is gone!",
]


def martial_disarm_line(attacker_name: str, defender_name: str, weapon_name: str) -> str:
    """Martial Combat strike disarming an armed defender."""
    return "   " + _pool_choice(MARTIAL_DISARM_LINES).format(
        attacker=attacker_name.upper(), defender=defender_name.upper(), weapon=weapon_name.lower())


def martial_critical_disarm_line(defender_name: str, attacker_name: str, weapon_name: str,
                                 attacker_gender: str = "Male") -> str:
    """Martial Combat defence knocking the attacker's weapon away."""
    his = "his" if attacker_gender == "Male" else "her"
    return "   " + _pool_choice(MARTIAL_CRITICAL_DISARM_LINES).format(
        defender=defender_name.upper(), attacker=attacker_name.upper(), weapon=weapon_name.lower(), his=his)


def critical_break_line(defender_name: str, attacker_name: str, weapon_name: str, attacker_gender: str = "Male") -> str:
    his = "his" if attacker_gender == "Male" else "her"
    him = "him" if attacker_gender == "Male" else "her"
    return _pool_choice(CRITICAL_BREAK_LINES).format(
        defender=defender_name.upper(), attacker=attacker_name.upper(),
        weapon=weapon_name, his=his, him=him,
    )


def critical_double_counter_line(defender_name: str, attacker_name: str, defender_gender: str = "Male") -> str:
    he = "he" if defender_gender == "Male" else "she"
    return _pool_choice(CRITICAL_DOUBLE_COUNTER_LINES).format(
        defender=defender_name.upper(), attacker=attacker_name.upper(), he=he,
    )


# ---------------------------------------------------------------------------
# SURRENDER / MERCY LINES
# ---------------------------------------------------------------------------

APPEAL_LINES = [
    "{warrior} appeals to the Blood Master for mercy!",
    "{warrior} raises a hand in surrender!",
    "{warrior} calls out for quarter!",
    "{warrior} can fight no more and begs for mercy!",
    "{warrior} appeals desperately to the Blood Master!",
    "{warrior} raises a hand, calling for mercy in a strained voice!",
    "{warrior} cries out for quarter, though the outcome is uncertain!",
    "{warrior} makes one last plea for mercy to the referee!",
    "{warrior} looks to the Blood Master with a desperate appeal!",
    "{warrior} gasps out a request for mercy, uncertain of the response!",
    "{warrior} raises a hand in supplication to the arena master!",
    "{warrior} calls for mercy while still gripping {his} weapon!",
    "{warrior} makes a final appeal, knowing it might fall on deaf ears!",
    "{warrior} begs for quarter, eyes fixed on the Blood Master!",
    "{warrior} appeals to the arena, uncertain what the crowd will demand!",
    "{warrior} makes a desperate bid for the ref's intervention!",
    "{warrior} cries out for mercy, bracing for rejection!",
    "{warrior} appeals to be spared, but the crowd's roar continues!",
    "{warrior} makes a bold appeal to the Blood Master!",
    "{warrior} calls for mercy while the crowd screams for more!",
    "{warrior} appeals to {his} opponent to yield, or to the ref to stop it!",
    "{warrior} makes a desperate plea that fate will grant mercy!",
]

MERCY_GRANTED = [
    "The ref saves the pitiable {warrior}!",
    "The Blood Master shows mercy, {warrior} lives to fight another day!",
    "{warrior} is spared by the grace of the Blood Master!",
    "The crowd screams for blood, but the ref steps in!",
    "Mercy is granted, the fight is over!",
    "The Blood Master raises a hand, granting the appeal!",
    "Mercy is shown! The crowd boos, but the fight ends!",
    "{warrior} is spared by the Blood Master's intervention!",
    "The ref steps in and calls an end to the bout!",
    "The Blood Master declares the fight over, mercy granted!",
    "Against the crowd's wishes, the Blood Master grants mercy!",
    "The referee halts the fight, showing compassion!",
    "{warrior} is saved by the Blood Master's decision!",
    "The crowd roars in protest, but mercy prevails!",
    "The Blood Master allows {warrior} to leave alive!",
    "Surprisingly, the ref grants the appeal and ends it!",
    "The fight is over, the Blood Master shows restraint!",
    "{warrior} lives another day by the Blood Master's grace!",
    "The ref intercedes and the fight is called!",
    "The Blood Master's mercy saves {warrior} from certain death!",
    "Against all odds, the appeal succeeds!",
    "The referee shows mercy and halts the onslaught!",
]

MERCY_DENIED = [
    "The Blood Master shows no mercy today!",
    "The crowd screams for blood, mercy is denied!",
    "{warrior} must fight on, or die trying!",
    "No quarter is given!",
    "The Blood Master shakes {his} head, no mercy today!",
    "The crowd roars for blood and the Blood Master obliges!",
    "{warrior} must continue, mercy is denied!",
    "The ref turns away, the fight goes on!",
    "No quarter is given, the battle continues!",
    "The Blood Master demands the fight continue!",
    "Mercy is refused, the arena demands more!",
    "The crowd's bloodlust wins, the fight rages on!",
    "The Blood Master denies the appeal with a cold gesture!",
    "No respite as the Blood Master orders them to fight!",
    "The ref refuses to intervene, this must be decided!",
    "Mercy is not an option in this arena!",
    "The Blood Master's expression hardens, fight on!",
    "The crowd's roar drowns out any plea for mercy!",
    "The Blood Master will not be moved, the fight continues!",
    "No mercy shall be granted this day!",
    "The ref stands firm, the battle must go on!",
    "The arena has spoken through the Blood Master, no mercy!",
]

# ---------------------------------------------------------------------------
# SOUL SPIRE SURRENDER / RESPITE LINES
# ---------------------------------------------------------------------------
# In the Soul Spire the combatants are the bound dead, so surrender is not a plea
# to live - they cannot truly die here, and will rise again regardless. A yield
# is a plea to the Soul Keeper to END the bout and spare further torment; a grant
# calls the fight, a denial means the dead fight on. Never implies "leaving alive".
SOUL_SPIRE_APPEAL_LINES = [
    "{warrior} can fight no more and appeals to the Soul Keeper for respite!",
    "{warrior} raises a ruined hand, yielding to the Soul Keeper!",
    "{warrior} sinks to the sand and begs the Soul Keeper to end it!",
    "{warrior} signals surrender, pleading for the bout to be called!",
    "{warrior} looks to the Soul Keeper with hollow eyes, begging for an end!",
    "{warrior} can take no more and calls out for the Keeper's judgment!",
    "{warrior} lifts a trembling hand, appealing to the Soul Keeper to stop this!",
    "{warrior} yields, hoping the Soul Keeper will show some restraint!",
    "{warrior} gasps out a plea for respite to the keeper of the dead!",
    "{warrior} bows their broken form before the Soul Keeper, surrendering!",
    "{warrior} pleads for the torment to cease, eyes fixed on the Soul Keeper!",
    "{warrior} throws down their guard and appeals to be released from the bout!",
]

SOUL_SPIRE_MERCY_GRANTED = [
    "The Soul Keeper calls an end to the bout!",
    "The Soul Keeper grants respite; the fight is over!",
    "The Soul Keeper lowers a hand, and the torment ceases!",
    "{warrior} is spared further ruin as the Soul Keeper ends it!",
    "The Soul Keeper stays the killing blow; this bout is done!",
    "The Soul Keeper releases {warrior} from the fight!",
    "The dead crowd falls silent as the Soul Keeper calls the bout!",
    "The Soul Keeper judges the fight finished, and the sand goes still!",
    "{warrior}'s plea is heard; the Soul Keeper ends the contest!",
    "The Soul Keeper grants a reprieve from the torment, for now!",
    "The Soul Keeper waves the combatants apart; it is finished!",
    "The Soul Keeper spares {warrior} the final indignity and calls the bout!",
    "The Soul Keeper's gaze settles on {warrior}, and the fight simply ends!",
    "A cold stillness spreads as the Soul Keeper decrees the bout over!",
    "The Soul Keeper closes its fist, and the combat is severed mid-blow!",
    "The Soul Keeper deems {warrior} has suffered enough; the bout is called!",
    "The ghost-lights dim as the Soul Keeper ends the contest!",
    "The Soul Keeper inclines its head, and the torment is lifted from {warrior}!",
    "A single gesture from the Soul Keeper, and the dead lower their weapons!",
    "The Soul Keeper pronounces the bout finished; the Spire goes quiet!",
    "The Soul Keeper draws {warrior} back from the brink and calls it done!",
    "The Soul Keeper silences the fray with a slow, deliberate motion!",
    "The Soul Keeper has seen enough; {warrior} is granted an end to the ordeal!",
    "The Soul Keeper parts the combatants like smoke; the fight is over!",
    "The Soul Keeper's judgment falls, and {warrior} is released from the torment!",
    "The grave-wind stills as the Soul Keeper declares the bout at an end!",
]

SOUL_SPIRE_MERCY_DENIED = [
    "The Soul Keeper is unmoved; the dead fight on!",
    "There is no respite here; the Soul Keeper denies the appeal!",
    "The Soul Keeper shakes its head slowly; the torment continues!",
    "The dead know no mercy; the bout rages on!",
    "The Soul Keeper demands the fight continue!",
    "{warrior} is given no reprieve; the curse is not yet satisfied!",
    "The Soul Keeper turns away, and the dead crowd howls for more!",
    "No end is granted; {warrior} must fight on!",
    "The Soul Keeper's judgment is cold; there is no stopping this!",
    "The Spire demands more suffering; the appeal is refused!",
    "The Soul Keeper will not call it; the fight goes on!",
    "Respite is denied; the dead are not finished with {warrior}!",
]

# Blood-challenge bullying: crowd interference thrown at a warrior fighting
# far beneath their standing, spoiling the action they were mid-committing to.
# Used only when the roll penalty actually changed the outcome (see effective
# param on crowd_interference_line below).
CROWD_INTERFERENCE_BULLY = [
    "A hurled bottle clips {warrior}, spoiling the motion!",
    "Something thrown from the stands catches {warrior} off guard!",
    "The crowd pelts {warrior} with debris, breaking their concentration!",
    "A rotten piece of fruit splatters against {warrior}, throwing off the timing!",
    "Jeers turn to thrown objects as {warrior} is struck from the stands!",
]

# Same trigger, but the penalty didn't end up changing the outcome this
# action - the narrative shouldn't claim an effect that didn't materialize.
CROWD_INTERFERENCE_BULLY_SHRUGGED_OFF = [
    "A hurled bottle clips {warrior}, but it isn't enough to throw them off!",
    "Something thrown from the stands catches {warrior} off guard, but they shake it off!",
    "The crowd pelts {warrior} with debris, though it barely registers!",
    "A rotten piece of fruit splatters against {warrior}, who doesn't so much as flinch!",
    "Jeers turn to thrown objects as {warrior} is struck from the stands, but presses on regardless!",
]

# Blood-challenge underdog: the crowd's support lifts the outmatched
# challenger at just the right moment. Used only when the roll bonus
# actually changed the outcome this action.
CROWD_INTERFERENCE_UNDERDOG = [
    "The crowd's roar seems to steel {warrior}'s nerve at just the right moment!",
    "Spurred on by the chanting crowd, {warrior} finds something extra!",
    "The arena is behind {warrior} completely, and it shows!",
    "Fueled by the crowd's support, {warrior} presses on with renewed heart!",
    "The stands erupt for {warrior}, who seems to draw strength from it!",
]

# Same trigger, but the bonus wasn't enough to change the outcome this action.
CROWD_INTERFERENCE_UNDERDOG_FELL_SHORT = [
    "The crowd roars for {warrior}, but the support isn't enough this time!",
    "Spurred on by the chanting crowd, {warrior} gives everything, but it isn't enough!",
    "The arena is behind {warrior} completely, but heart alone can't close the gap this time!",
    "Fueled by the crowd's support, {warrior} presses on, though it doesn't pay off this time!",
    "The stands erupt for {warrior}, whose effort falls just short despite it!",
]


def crowd_interference_line(warrior_name: str, zone: str, effective: bool = True) -> str:
    """zone is 'bully' (penalty, jeering) or 'underdog' (bonus, cheering).
    effective indicates whether the roll modifier actually changed this
    action's outcome (a miss for a bully, a hit for an underdog) - when it
    didn't, a different pool is used so the line doesn't claim an effect
    that didn't happen."""
    if zone == "bully":
        pool = CROWD_INTERFERENCE_BULLY if effective else CROWD_INTERFERENCE_BULLY_SHRUGGED_OFF
    else:
        pool = CROWD_INTERFERENCE_UNDERDOG if effective else CROWD_INTERFERENCE_UNDERDOG_FELL_SHORT
    return _pool_choice(pool).format(warrior=warrior_name.upper())

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
    "{warrior} is struck down in a final, merciless killing blow, the crowd screaming for more!!!",
    "{warrior} collapses in a spray of blood, the light fading from {his} eyes as {he} falls!!!",
    "The fatal blow lands with finality as {warrior} crashes to the sand, lifeless and still!!!",
    "{warrior} is torn asunder by the relentless assault, leaving only a broken form in the pit!!!",
    "A shattering final strike brings {warrior} down, {his} body going limp as death claims another victim!!!",
    "{warrior} staggers once more before the killing blow lands, ending everything in a moment of terrible clarity!!!",
    "The arena claims yet another soul as {warrior} expires upon the bloodied sands amid frenzied cheering!!!",
    "{warrior} breathes no more. The amphitheatre erupts in primal, savage celebration of the kill!!!",
    "{warrior} makes one final, desperate plea to the gods before falling into darkness eternal!!!",
    "The killing stroke finds its mark with terrible precision, and {warrior} is no more!!!",
    "{warrior} drops to the sand with a hollow thud, all will to fight extinguished in an instant!!!",
    "A torrent of blood marks the end as {warrior} is cut down where {he} stands!!!",
    "{warrior} tries once more to rise but finds no strength left, collapsing into final defeat!!!",
    "The crowd's roar becomes a dirge as {warrior} falls, never to answer the call again!!!",
    "{warrior} is undone by a strike of such brutality that {his} body goes slack and still!!!",
    "In the silence that follows the final blow, {warrior} lies motionless on the crimson-stained sand!!!",
    "The amphitheatre's blood-lust is satiated as {warrior} is extinguished in the most violent fashion!!!",
]

ELF_DUAL_STRIKE_LINES = [
    "{attacker} draws upon {his} inherent Elvish heritage and brings {his} {secondary} across in a lightning quick follow-up!",
    "{attacker}'s grace becomes evident as {secondary_subject} flashes forth with supernatural speed!",
    "With movements too quick to follow, {attacker} spins and launches {his} {secondary} at {defender}!",
    "{attacker}'s {secondary} whips around in a blur of motion, targeting {defender} once more!",
    "The Elf's natural dexterity shines as {secondary_subject} darts forward with deadly speed!",
    "{attacker} pivots fluidly and swings {his} {secondary} in a rapid follow-up!",
    "In a display of dual-weapon mastery, {attacker} brings {his} {secondary} around for another attack!",
    "{attacker}'s {secondary} glints in the light as {subject} presses the advantage with uncanny speed!",
    "Moving with elvish fluidity, {attacker} spots an opening and {secondary_subject} lunges forward!",
    "In a blur of dual-weapon mastery, {attacker}'s off-hand weapon drives in without hesitation!",
    "Without hesitation, {attacker}'s off-hand weapon capitalizes on the opening!",
    "{attacker} chains the strikes together with effortless elegance!",
    "{attacker}'s {secondary} follows the first blow in seamless succession!",
    "With elvish precision, {attacker} brings the {secondary} to bear instantly!",
    "{attacker} transitions between weapons with supernatural smoothness!",
    "The {secondary} swings around in a continuation of pure grace!",
    "{attacker}'s weapons dance in deadly harmony!",
    "Before {defender} can react, {attacker}'s {secondary} is already in motion!",
    "{attacker} demonstrates the deadly efficiency of dual-wield mastery!",
    "The follow-up strike arrives from an unexpected angle!",
    "{attacker} weaves both weapons together in a fluid assault!",
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
    "{attacker} pivots and launches another quick strike before {defender} can recover!",
    "Moving with practiced speed, {attacker} finds another opening to exploit!",
    "{attacker}'s nimble footwork sets up a rapid follow-up attack!",
    "In the blink of an eye, {attacker} delivers another precise strike!",
    "{attacker} bounces back and drives another blow forward with momentum!",
    "The halfling's natural agility allows {attacker} to press the assault relentlessly!",
    "{attacker} weaves through {defender}'s defenses and strikes again!",
    "With incredible speed, {attacker} chains another martial technique into the exchange!",
    "{attacker} uses {his} diminutive size to slip in another attack!",
    "The successive strikes come so fast {defender} barely has time to react!",
    "{attacker} demonstrates why halflings are feared in martial combat!",
    "{attacker} continues the relentless barrage with another precisely-placed strike!",
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
    "{attacker} strikes with reptilian precision, launching another devastating attack!",
    "The Lizardfolk's natural weapons flash as {attacker} presses the advantage!",
    "{attacker} hisses and delivers another ferocious strike without hesitation!",
    "Guided by predatory instinct, {attacker} unleashes another powerful blow!",
    "{attacker}'s claws rake forward in a follow-up assault of savage intensity!",
    "The Lizardfolk's inborn martial instincts drive another relentless attack!",
    "{attacker} moves with cold efficiency, striking again before {defender} can recover!",
    "Another strike erupts from {attacker} with primal, animalistic power!",
    "{attacker}'s natural reflexes trigger an instant follow-up assault!",
    "With serpentine speed, {attacker} launches another assault at {defender}!",
    "{attacker} channels {his} bestial nature into another devastating strike!",
    "The Lizardfolk's dual nature as predator and warrior shows in the successive attacks!",
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
    "{attacker}'s ears flatten against {his} head as fury overtakes {him}!",
    "With a primal shriek, {attacker} explodes into a maelstrom of claws!",
    "{attacker}'s pupils dilate as the killing instinct takes hold!",
    "The Tabaxi's composure shatters, replaced by raw ferocity!",
    "{attacker} transforms in an instant, becoming pure violence incarnate!",
    "Channeling the spirit of the hunt, {attacker} launches into a relentless barrage!",
    "{attacker} hisses and unleashes a combination too fast to follow!",
    "Desperation ignites {attacker}'s inner beast, unleashing a savage storm!",
    "With feral grace, {attacker} becomes a blur of strikes and fury!",
    "{attacker}'s natural instincts override all reason as {he} attacks with abandon!",
    "The arena erupts as {attacker} enters a state of absolute combat fury!",
    "{attacker} answers the call of {his} bestial nature with a devastating assault!",
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
    "{winner} stands tall as the crowd erupts in deafening acclaim!",
    "Victory is {winner}'s! The arena shakes with the roar of the crowd!",
    "{winner} is declared champion as the stands explode with fervor!",
    "The Blood Master hoists {winner}'s arm high, the victor of the day!",
    "{winner} has proven {himself} the superior warrior this day!",
    "In a display of martial prowess, {winner} emerges victorious!",
    "{winner} is bathed in the adulation of the crowd, triumphant and supreme!",
    "The crowd surges to its feet for {winner}, whose victory is absolute!",
    "{winner} stands over the fallen, the undisputed victor of the pit!",
    "Pandemonium erupts as {winner} is declared the winner of this brutal affair!",
    "{winner}'s arm is raised to thunderous applause, a worthy victor!",
    "The amphitheatre recognizes {winner} as the superior combatant!",
    "{winner} has claimed victory in spectacular fashion!",
    "Against all odds, {winner} emerges as the champion of this day!",
    "{winner} proves why {he} is a force to be reckoned with in the arena!",
    "The crowd chants {winner}'s name as {he} stands victorious!",
    "{winner} has dominated the competition and earned {his} rightful victory!",
    "With {his} hand raised in triumph, {winner} accepts the accolades of the arena!",
    "{winner} is crowned victor as the arena trembles with jubilation!",
    "The Blood Master declares {winner} the winner, supreme in combat!",
    "{winner} claims victory and the eternal glory of the Agony Amphitheatre!",
    "Resounding cheers wash over {winner}, the undisputed master of this day!",
    "{winner} has carved {his} name into legend with this victory!",
    "The crowd's roar becomes deafening as {winner} stands as the victor!",
    "{winner} emerges from the carnage victorious, {his} dominance undeniable!",
]


def appeal_line(warrior_name: str, gender: str = "Male", undead: bool = False) -> str:
    pronoun = "his" if gender == "Male" else "her"
    pool = SOUL_SPIRE_APPEAL_LINES if undead else APPEAL_LINES
    return _pool_choice(pool).format(warrior=warrior_name.upper(), his=pronoun)


def mercy_result_line(warrior_name: str, granted: bool, warrior_gender: str = "Male",
                      undead: bool = False) -> str:
    pronoun = "his" if warrior_gender == "Male" else "her"
    if undead:
        pool = SOUL_SPIRE_MERCY_GRANTED if granted else SOUL_SPIRE_MERCY_DENIED
    else:
        pool = MERCY_GRANTED if granted else MERCY_DENIED
    return _pool_choice(pool).format(warrior=warrior_name.upper(), his=pronoun)


def death_line(warrior_name: str, gender: str) -> str:
    his     = "his"     if gender == "Male" else "her"
    he      = "he"      if gender == "Male" else "she"
    him     = "him"     if gender == "Male" else "her"
    himself = "himself" if gender == "Male" else "herself"
    return _pool_choice(DEATH_LINES).format(
        warrior=warrior_name.upper(), his=his, he=he, him=him, himself=himself
    )


def race_kill_line(killer_name: str, race_name: str, gender: str) -> str:
    """Return a race-specific narrative line for a kill."""
    pool = RACE_KILL_POOLS.get(race_name, RACE_KILL_POOLS["Human"])
    template = _pool_choice(pool)
    his = "his" if gender == "Male" else "her"
    he = "he" if gender == "Male" else "she"
    him = "him" if gender == "Male" else "her"
    himself = "himself" if gender == "Male" else "herself"

    return template.format(
        name=killer_name.upper(),
        his=his, he=he, him=him, himself=himself
    )


def victory_line(winner_name: str, loser_name: str, winner_gender: str = "Male") -> str:
    pronoun = "his" if winner_gender == "Male" else "her"
    he_pronoun = "he" if winner_gender == "Male" else "she"
    himself = "himself" if winner_gender == "Male" else "herself"
    return _pool_choice(VICTORY_LINES).format(
        winner=winner_name.upper(), loser=loser_name.upper(), his=pronoun, he=he_pronoun, himself=himself
    )


# ---------------------------------------------------------------------------
# RESURRECTION NARRATIVE (Elite Spire / Veteran's Keep)
# ---------------------------------------------------------------------------

RESURRECTION_LINES = [
    "{warrior} falls, but the arena's dark magic will not let {him} stay down.",
    "The crowd gasps as {warrior} crumples... then the ancient wards pulse, and {he} stirs.",
    "{warrior} is defeated, yet the immortal compact holds and {his} wounds begin to close.",
    "A sickly glow envelops {warrior} as {he} collapses. Death reaches out... and withdraws.",
    "{warrior} drops to the sand, vanquished. The arena hums, and {his} broken form is whole again.",
    "The life drains from {warrior}'s eyes, then surges back. This place does not accept the fallen.",
    "{warrior} is brought low. Yet in this sanctified arena, no warrior truly dies.",
    "Defeated, {warrior} lies still. The immortal blood-pact raises {him} once more.",
    "The ancient rite claims {warrior}'s defeat but not {his} life. {He} will rise to fight again.",
    "{warrior} cannot hold. {He} falls, and the eternal compact of this arena saves {him}.",
]


def resurrection_line(warrior_name: str, gender: str) -> str:
    """Return a narrative line for an auto-resurrection in an immortal arena."""
    his = "his" if gender == "Male" else "her"
    he  = "he"  if gender == "Male" else "she"
    him = "him" if gender == "Male" else "her"
    return _pool_choice(RESURRECTION_LINES).format(
        warrior=warrior_name.upper(), his=his, he=he, him=him,
        He="He" if gender == "Male" else "She",
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

    return _pool_choice(ELF_DUAL_STRIKE_LINES).format(
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
    return _pool_choice(HALFLING_MARTIAL_STRIKE_LINES).format(
        attacker=attacker_name.upper(),
        defender=defender_name.upper(),
        his=pronoun,
    )


def lizardfolk_martial_strike_line(attacker_name: str, defender_name: str, gender: str) -> str:
    """Generate narrative for a Lizardfolk's extra martial combat attack."""
    pronoun = "his" if gender == "Male" else "her"
    subject_pronoun = "he" if gender == "Male" else "she"
    return _pool_choice(LIZARDFOLK_MARTIAL_STRIKE_LINES).format(
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
    "{attacker} fights down the surge of bloodlust with iron will.",
    "The beast within stirs but {attacker} refuses to yield to it.",
    "{attacker}'s eyes flash with hunger before {he} reasserts control.",
    "For a moment, {attacker} is lost to instinct, then {he} finds {himself} again.",
    "{attacker} breathes through the feral urge and masters it.",
    "The predator snarls but the warrior holds the reins.",
    "{attacker}'s muscles tense for the killing strike, then relax as reason returns.",
    "Instinct claws at {attacker}'s consciousness but cannot break through.",
    "{attacker} swallows the frenzy down, maintaining precarious composure.",
    "The wildness threatens to consume {attacker}, but {he} steps back from the edge.",
    "{attacker}'s claws extend reflexively, then retract as {he} regains focus.",
    "A moment of pure savagery flashes across {attacker}'s face before {he} quells it.",
    "{attacker} grapples with {his} nature and wins, barely.",
    "The hunger for blood pulses through {attacker} but does not overcome {him}.",
    "{attacker} hovers on the precipice of frenzy, then pulls back.",
]


def tabaxi_frenzy_intro_line(attacker_name: str, gender: str = "Male") -> str:
    """Generate narrative for the opening of a Tabaxi frenzy ability."""
    he = "he" if gender == "Male" else "she"
    his = "his" if gender == "Male" else "her"
    return _pool_choice(TABAXI_FRENZY_INTRO_LINES).format(
        attacker=attacker_name.upper(),
        he=he,
        his=his,
        him="him" if gender == "Male" else "her",
    )


def tabaxi_frenzy_strike_line(attacker_name: str, attack_num: int) -> str:
    """Generate the per-attack setup line for one of the 3 frenzy strikes (attack_num 0/1/2)."""
    pool = TABAXI_FRENZY_STRIKE_LINES.get(attack_num, TABAXI_FRENZY_STRIKE_LINES[2])
    return _pool_choice(pool).format(attacker=attacker_name.upper())


def tabaxi_frenzy_resist_line(attacker_name: str, gender: str = "Male") -> str:
    """Generate narrative for a failed Tabaxi frenzy trigger roll."""
    he = "he" if gender == "Male" else "she"
    his = "his" if gender == "Male" else "her"
    himself = "himself" if gender == "Male" else "herself"
    return _pool_choice(TABAXI_FRENZY_RESIST_LINES).format(
        attacker=attacker_name.upper(),
        he=he,
        his=his,
        him="him" if gender == "Male" else "her",
        himself=himself,
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
    "A section of the crowd erupts in unified chanting!",
    "Vendors cry out their wares despite the chaos!",
    "A child climbs onto a guardian's shoulders for a better view!",
    "Bets are placed frantically as the action intensifies!",
    "The crowd's roar swells to a deafening crescendo!",
    "Someone throws flowers into the pit!",
    "A guard struggles to maintain order in the rowdy stands!",
    "A group of merchants argue loudly over the odds!",
    "The sand beneath the pit is kicked up by stamping feet in the stands!",
    "Someone in the crowd faints from the excitement!",
    "A wealthy patron signals to place a massive wager!",
    "The smell of roasted meat mingles with blood and dust!",
    "Vendors run out of ale, causing disappointed groans!",
    "A section of the crowd begins to chant the warrior's name!",
    "Spectators throw their hats in the air in excitement!",
    "A woman shields her face but keeps watching intently!",
    "The crowd's excitement reaches such a fever pitch the ground itself seems to shake!",
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
    "This is a clash of equals, each perfectly matched to the other.",
    "The warriors circle each other, testing but not committing fully.",
    "The balance is precarious; one mistake could tip the scales.",
    "Both combatants are executing their strategies flawlessly.",
    "It remains unclear who has the edge at this critical juncture.",
    "The crowd senses the tension; anyone could claim victory.",
    "Neither fighter has shown a weakness the other can exploit.",
    "The pace is intense but controlled, neither gaining ground.",
    "This is the essence of true combat, two experts at an impasse.",
    "The fight hangs in perfect balance, waiting for the next opening.",
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
    "{winner} is seizing key moments in the exchange.",
    "{winner}'s superior positioning is beginning to show.",
    "The tide is turning slowly, but decisively, toward {winner}.",
    "{winner} is landing more meaningful blows than before.",
    "{winner}'s strategy is starting to work against {loser}.",
    "The gap is widening, though {loser} remains dangerous.",
    "{winner} has found a rhythm that {loser} is struggling to match.",
    "The early signs suggest {winner} is pulling away.",
    "{winner} is dictating the pace more with each exchange.",
    "A perceptible shift in momentum favors {winner} now.",
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
    "{winner} is imposing {his} will on {loser} with every action.",
    "{loser} is struggling to find any opening or respite against {winner}'s relentless assault.",
    "{winner} has systematically dismantled {loser}'s strategy.",
    "The gap between the two warriors is now undeniable. {winner} is firmly in control.",
    "{winner} is executing a masterclass in combat while {loser} falls further behind.",
    "{loser}'s defenses are cracking under {winner}'s relentless pressure.",
    "{winner} is landing strikes almost at will, leaving {loser} reeling.",
    "The fight is rapidly becoming one-sided in {winner}'s favor.",
    "{winner}'s dominance is now complete in this exchange.",
    "{loser} finds {himself} on the back foot with no answer to {winner}'s superior technique.",
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
    "{winner} is utterly devastating {loser} in every exchange.",
    "{loser} is being torn apart by {winner}'s onslaught.",
    "{winner} is an unstoppable force crushing everything in {his} path.",
    "{loser} is barely staying on {his} feet under the barrage.",
    "The fight has become a masterclass in one-sided domination.",
    "{winner} is punishing {loser} for every mistake with ruthless efficiency.",
    "{loser}'s spirit is being broken by {winner}'s relentless assault.",
    "{winner} is toying with {loser}, demonstrating complete superiority.",
    "The crowd watches in awe as {winner} utterly controls the arena.",
    "{loser} has no answer to {winner}'s overwhelming techniques.",
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
    "{loser} is one mistake away from catastrophe.",
    "The crowd holds its breath, sensing the end is near.",
    "{loser}'s defenses are on the edge of collapse.",
    "{winner} is circling, waiting for {loser} to falter.",
    "{loser} is fighting on instinct alone now.",
    "The finish could come at any moment.",
    "{loser} is barely conscious, swaying on unstable legs.",
    "{winner} is poised to deliver the finishing blow.",
    "{loser} cannot take much more of this punishment.",
    "The sand beneath {loser} seems to crumble with each step.",
    "{loser}'s eyes are glazed, {his} movements becoming mechanical.",
    "One more exchange and this could be over.",
    "{loser} is a shadow of themselves, barely functional.",
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
    "The tide turns. {winner} seizes the upper hand after a close exchange.",
    "{winner} suddenly finds the opening and surges forward!",
    "{loser}'s dominance crumbles as {winner} makes {his} move!",
    "{winner} explodes from defense into a counteroffensive assault!",
    "The tables turn dramatically in {winner}'s favor!",
    "{winner} seizes control from the brink of defeat!",
    "{loser} falters for just a moment, and {winner} strikes!",
    "{winner} unleashes {his} response with brutal precision!",
    "The balance shifts violently toward {winner}!",
    "{winner} catches {loser} at exactly the wrong moment!",
    "Fortune changes hands as {winner} presses the advantage!",
    "{winner} transforms from survival to dominance in a heartbeat!",
    "{loser}'s momentum fails as {winner} surges back!",
    "{winner} breaks {loser}'s rhythm with a perfect read!",
    "The fight suddenly belongs to {winner} again!",
    "{winner} claws back from the edge with a powerful counter!",
    "{loser} is caught unprepared as {winner} shifts into high gear!",
]


def minute_status_line(
    winner_name: str,
    loser_name: str,
    tier: str,
    prev_tier: str,
    prev_winner: str,
    used: set,
    winner_gender: str = "Male",
    loser_gender: str = "Male",
) -> str:
    """
    Return a fight-status line for the start of a minute.

    tier / prev_tier: one of "even", "slight", "clear", "dominating", "brink", "brink_exhaustion"
    winner_name / loser_name: the leading fighter (empty strings when tier == "even")
    prev_winner: the name of the winner last minute (empty string if none)
    used: mutable set of already-used lines this fight (updated in-place)
    winner_gender / loser_gender: gender for pronouns
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

    line = _pool_choice(available)
    used.add(line)

    winner_his = "his" if winner_gender == "Male" else "her"
    loser_his = "his" if loser_gender == "Male" else "her"
    loser_himself = "himself" if loser_gender == "Male" else "herself"

    return line.format(winner=winner_name.upper(), loser=loser_name.upper(),
                      his=winner_his, loser_his=loser_his, himself=loser_himself)


def crowd_line(warrior_a_race: str = "", warrior_b_race: str = "") -> str:
    """Return a random crowd flavor line, occasionally race-specific."""
    if random.random() < 0.2:
        # Try a race taunt for one of the warriors
        race = random.choice([warrior_a_race, warrior_b_race])
        if race in RACE_TAUNTS:
            return _pool_choice(RACE_TAUNTS[race])
    return _pool_choice(CROWD_LINES)


# ---------------------------------------------------------------------------
# "ANXIOUSLY AWAITS" LINE (endurance drain effect, certain styles)
# ---------------------------------------------------------------------------

ANXIOUS_LINES = [
    "{warrior} circles {foe}, draining the will to fight",
    "{warrior} waits patiently, {foe}'s energy bleeds away",
    "{warrior} keeps pressure on {foe} without committing",
    "{warrior} stalks {foe}, watching for a sign of weakness",
    "{warrior} maintains distance, letting time work in {his} favor",
    "{foe} grows restless under {warrior}'s patient gaze",
    "{warrior} is content to wait; {foe} will crack first",
    "{warrior} moves in measured steps, never committing",
    "{foe} feels {warrior}'s invisible weight pressing down",
    "{warrior} matches {foe}'s pace, neither pushing nor retreating",
    "{warrior} is a still predator, watching and waiting",
    "{foe} finds no opening in {warrior}'s defensive posture",
    "{warrior} seems to be playing for time itself",
    "{warrior} shows no urgency, content to let {foe} tire",
    "{foe} chafes at {warrior}'s refusal to engage fully",
    "{warrior} keeps {foe} at bay through sheer positioning",
    "The pressure builds silently as {warrior} refuses to break",
    "{warrior}'s patience is a slow knife to {foe}'s confidence",
    "{warrior} moves with the flow, never against it",
    "{foe} strains against an invisible wall of {warrior}'s creation",
]


def anxious_line(warrior_name: str, warrior_gender: str, foe_name: str) -> Optional[str]:
    """Only fires for styles with anxiously_awaits=True, ~20% chance."""
    if random.random() < 0.20:
        pronoun = "his" if warrior_gender == "Male" else "her"
        t = _pool_choice(ANXIOUS_LINES)
        return t.format(warrior=warrior_name.upper(), foe=foe_name.upper(), his=pronoun)
    return None


INTIMIDATE_LINES = [
    "{warrior}'s relentless assault is beginning to rattle {foe}!",
    "{foe} flinches under the ferocity of {warrior}'s onslaught!",
    "The sheer savagery of {warrior}'s assault wears on {foe}'s nerves!",
    "{warrior} presses forward with terrifying aggression, {foe} backs away!",
    "The crowd roars as {warrior}'s ferocity visibly shakes {foe}!",
    "{foe} struggles to keep composure under {warrior}'s relentless pressure!",
    "{warrior}'s wild fury is taking a psychological toll on {foe}!",
    "{warrior}'s overwhelming onslaught is rattling {foe}'s confidence!",
    "{foe} is visibly unnerved by {warrior}'s relentless pace!",
    "The psychological weight of {warrior}'s assault bears down on {foe}!",
    "{warrior} is breaking {foe}'s will with sheer force of presence!",
    "{foe} feels the pressure mounting as {warrior} continues the barrage!",
    "The raw intensity of {warrior}'s assault is wearing {foe} down mentally!",
    "{warrior}'s dominant aggression is making {foe} doubt themselves!",
    "{foe} gasps for breath as {warrior}'s assault seems relentless!",
    "The ferocity of {warrior}'s attacks is visibly affecting {foe}'s composure!",
    "{warrior} is grinding {foe} down through sheer overwhelming presence!",
    "{foe} is losing ground both physically and psychologically to {warrior}!",
    "The relentless nature of {warrior}'s assault is demoralizing {foe}!",
    "{warrior}'s inexorable advance is crushing {foe}'s morale!",
]


def intimidate_line(warrior_name: str, foe_name: str) -> Optional[str]:
    """Only fires for styles with intimidate=True at high activity, ~25% chance."""
    if random.random() < 0.25:
        t = _pool_choice(INTIMIDATE_LINES)
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
    return _pool_choice(pool).format(warrior=warrior_name.upper())

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


# ---------------------------------------------------------------------------
# ELITE SPIRE PROMOTION ANNOUNCEMENTS
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# BLEEDING DAMAGE DESCRIPTIONS
# ---------------------------------------------------------------------------
# Character-reaction focused descriptions that imply bleeding severity
# without showing damage numbers. Organized by severity level.

_BLEEDING_MINOR = [
    "{defender}'s eyes narrow as blood trickles from the wound.",
    "The warrior grimaces, watching blood seep from the cut.",
    "{defender}'s breath catches as blood begins to flow.",
    "{defender} watches blood begin to pool at the wound site.",
    "The warrior's jaw tightens as blood starts to drip from the opening.",
    "{defender} glances down at the bleeding cut with mild concern.",
]

_BLEEDING_MODERATE = [
    "{defender}'s expression darkens as blood flows steadily from the wound.",
    "The warrior curses softly, watching blood flow freely from the injury.",
    "{defender} grimaces, feeling the steady pulse of bleeding.",
    "{defender}'s hand instinctively moves toward the bleeding wound.",
    "The warrior's breathing quickens as blood stains armor and skin.",
    "{defender} staggers slightly, troubled by the persistent bleeding.",
]

_BLEEDING_SEVERE = [
    "{defender} staggers from the torrent of blood pouring from the wound.",
    "The warrior's face pales as blood pours heavily from the opening.",
    "{defender} drops to one knee, shocked by the heavy bleeding.",
    "The warrior gasps, struggling to stem the flow of blood.",
    "{defender} stumbles, blood cascading down from the severe wound.",
    "Eyes wide with alarm, {defender} watches blood pour from the injury.",
]


def bleeding_line(defender_name: str, damage: int) -> str:
    """
    Select and format a bleeding description based on damage severity.
    Minor: 1-2 damage, Moderate: 3-5, Severe: 6+
    """
    if damage <= 2:
        pool = _BLEEDING_MINOR
    elif damage <= 5:
        pool = _BLEEDING_MODERATE
    else:
        pool = _BLEEDING_SEVERE

    template = _pool_choice(pool)
    return _safe_format(template, defender=defender_name.upper())


# Message pools for warrior promotions to Elite Spire
_ELITE_SHIELD_MESSAGES = [
    "\n{NAME} has just fought their final bout as a mortal warrior. History will mark this moment as the end of one chapter and the beginning of another. The Elite Spire calls them now to something greater.",
    "\nThe fight is over. {NAME} has crossed the threshold. The gates of the Elite Spire stand open now, ready to welcome its newest immortal warrior.",
    "\nIt's done. {NAME} fought their last under mortal sun and prevailed. The Elite Spire has claimed them now. They ascend.",
    "\nEveryone in the stands watched what they came to see. {NAME} has just fought their final bout as a common warrior. The Elite Spire awaits their ascension.",
    "\nThat was it. The last time {NAME} would fight on these sands as a mortal. Now they leave for the Elite Spire, where legends are made among legends.",
    "\n{NAME} fought to earn their place in the Elite Spire, and today they proved they belong there. The gates open now. They ascend.",
    "\nThe whispers through the crowd have turned to certainty. {NAME} has just fought for the last time as a regular warrior. Now they rise to the Elite Spire.",
    "\n{NAME} carried the weight of this moment into the sand, and they've emerged transformed. The Elite Spire has claimed its newest ascendant. They ascend now.",
    "\nThis was the one that mattered most, and {NAME} delivered. They've just closed the door on their mortal career. The Elite Spire opens before them now.",
    "\n{NAME} answered the call of the Elite Spire long ago. They've just fought their final bout as a mortal. Now they take their place among the immortals.",
]

_ELITE_CALL_MESSAGES = [
    "\nIt's official. {NAME} has done what thousands never will. The Elite Spire has issued its call. One more bout remains before they walk through its gates.",
    "\n{NAME} proved it today. The Elite Spire was watching, and now they're calling. Just one more victory on mortal ground, then immortality awaits.",
    "\nThe Elite Spire doesn't call often. When it does, the arena takes notice. Today it called for {NAME}. One final bout stands between them and legend.",
    "\n{NAME} crossed the line. They've earned their shot at the Spire. One more fight on these sands, and then they ascend beyond mortal competition.",
    "\nThere's a name being whispered through the Elite Spire's halls. {NAME}. Their record demands attention. One more bout to prove they belong up there.",
    "\nWhat {NAME} did today changed their life. The Elite Spire took notice. One more victory here, and they leave as an immortal.",
    "\n{NAME} has been invited to greatness. The Elite Spire extends its call, and {NAME} answers. One final test on mortal ground awaits before ascension.",
    "\nThe Spire never makes mistakes. {NAME} is proof. They've earned the call. One last bout beneath these stars before they rise to something greater.",
    "\nNews travels fast in the arena. {NAME} has qualified for the Elite Spire. Just one more fight to go. After that, nothing will be the same.",
    "\n{NAME} forced the Elite Spire's hand with their performance today. The invitation is official. One more bout, and they're gone to immortality.",
]

def elite_spire_shield_line(warrior_name: str) -> str:
    """
    Appended to the fight narrative when a warrior fights their final mortal
    bout under the immortality shield (pending_promotion already set from last turn).
    Selects randomly from a pool of promotion messages to make each feel unique.
    """
    name = warrior_name.upper()
    message = _pool_choice(_ELITE_SHIELD_MESSAGES)
    return message.format(NAME=name)


def elite_spire_call_line(warrior_name: str) -> str:
    """
    Appended to the fight narrative when a warrior earns Elite Spire eligibility
    THIS turn (newly_eligible -- pending_promotion just set).
    Selects randomly from a pool of promotion messages to make each feel unique.
    """
    name = warrior_name.upper()
    message = _pool_choice(_ELITE_CALL_MESSAGES)
    return message.format(NAME=name)


# ─────────────────────────────────────────────────────────────────
# ELITE SPIRE & SOUL SPIRE NARRATIVE LINES
# ─────────────────────────────────────────────────────────────────

_ELITE_SPIRE_INTROS = [
    "The crowd erupts as the gates of the Elite Spire rise, revealing the finest warriors the realm has produced!",
    "A trumpet fanfare echoes through the Elite Spire as nobles settle into their private viewing balconies.",
    "The Spire Herald announces the combatants, champions both, to the roar of the elite!",
    "Gold and silk drape the pit as two masters enter the Elite Spire arena.",
    "The elite audience rises as the warriors step forth. This is a battle among the realm's greatest.",
    "Banners unfurl above the center stage. The crowd knows both these warriors' names.",
    "The distinguished crowd leans forward as the fighters enter. Anticipation hangs thick in the air.",
    "Spotlights sweep the Spire as the combatants take their marks. The audience erupts in recognition and respect.",
    "A hush falls over the Elite Spire as the warriors make their entrance. All eyes follow them.",
    "The herald raises their voice: two warriors of renown step forth to prove their worth!",
    "Cheers and applause fill the Elite Spire as the fighters take their places. This is where champions are tested.",
    "Both warriors stride into the arena with absolute confidence. The crowd can feel the presence of skill.",
    "The Elder Guard nods in respect as the combatants approach. Few warriors earn such recognition.",
    "Murmurs of approval ripple through the crowd as the fighters appear. Both have reputations to defend.",
    "The Spire itself seems to brighten as the warriors enter. Everyone knows they are witnessing excellence.",
    "The orchestra strikes a triumphant chord as the combatants take the stage. This is the Elite Spire.",
    "High above, the judges observe as the fighters enter. They watch every move with keen interest.",
    "The warriors look out over the crowd gathered to witness this bout. This is what victory looks like.",
]

_ELITE_SPIRE_FIGHT_LINES = [
    "{name} executes a flawless {style}.",
    "{name}'s technique is worthy of the Elite Spire's reputation.",
    "{name} fights with the discipline of the elite!",
    "The nobles appreciate {name}'s masterful display.",
    "{name} demonstrates why they belong in this arena.",
    "The crowd recognizes {name}'s superior skill on display.",
    "{name} moves with the grace of a true master.",
    "That is the kind of move that separates the elite from the rest.",
    "{name} flows through the {style} as if born to it.",
    "Every action from {name} shows years of refined training.",
    "The audience appreciates the artistry in {name}'s fighting.",
    "{name} reminds everyone why they are here in the Elite Spire.",
    "Precision and power combine in {name}'s every move.",
    "{name} showcases the difference between good and great.",
    "The judges nod in approval at {name}'s form.",
    "This is the level of combat the Elite Spire demands.",
    "{name} settles into the {style} with confidence.",
    "Quality shines through in every action from {name}.",
]

_SOUL_SPIRE_INTROS = [
    "The veil between worlds grows thin as two warriors cross into the Soul Spire, where the dead do not rest.",
    "Shadows coalesce as the combatants enter the realm of the fallen. The spirits watch with hunger.",
    "A death knell echoes through the Soul Spire. Two fighters take the stage among the cursed.",
    "The souls of the slain gather close as two warriors step into their domain. Blood calls to blood.",
    "The air turns cold and fetid. The combatants walk among the dead, where victory is the only escape.",
    "The warriors enter and the whispers begin. The dead recognize their own kind.",
    "Frost spreads across the ground as the fighters appear. The crowd of spirits stirs.",
    "The veil shudders as two warriors cross over. This place knows only suffering and combat.",
    "The combatants step into the arena and the dead fall silent, watching. Always watching.",
    "A chill runs through everything as the warriors take their places. Death holds no mercy here.",
    "The spirits press close as the fighters enter. They have waited for this moment.",
    "Two warriors walk into a place where death means nothing. Here, only strength matters.",
    "Shadowy forms encircle the arena as the combatants appear. This is a realm of torment.",
    "The very ground groans as the warriors step forward. Welcome to the Soul Spire.",
    "The fighters breathe in the fetid air of this cursed place. They know what awaits.",
    "The spirits shriek with excitement as two warriors enter their domain. More to test.",
    "Darkness swallows the combatants as they descend into the Soul Spire. There is no light here.",
    "The warriors look into the crowd of dead faces. This is their destiny now.",
    "The fighters enter and the dead reach out with grasping hands. The hunger is palpable.",
    "A grave wind howls as two warriors take the stage. Welcome to the place between life and death.",
]

_SOUL_SPIRE_RESURRECTION_LINES = [
    "The life drains from {name}'s body. But the Soul Spire's curse demands more. When dawn breaks, {name} will rise again, bound for another turn of combat.",
    "{name} lies broken on the cursed ground, the fight over. Yet death holds no finality here. The Spire will reform {name} for the battles yet to come.",
    "In this place between worlds, {name}'s death is not an ending. The Spire's grasp pulls them back, binding them for another dawn.",
    "The spirits whisper {name}'s name as the fallen warrior is claimed. But the Spire will not keep them. They will return to fight again.",
    "{name} breathes their last. And yet the veil parts. The Spire sends them back, forged anew for the next trial.",
    "This is not the end for {name}. The Soul Spire does not allow escape through death.",
    "{name} falls, but the dead are not finished with them. When night ends, they will rise.",
    "The grasping hands pull {name} back from the brink. They are bound to this place now.",
    "{name} sees nothing but darkness, yet they know they will see the Spire again.",
    "The whispers promise {name} will return. Death is only a momentary reprieve.",
    "The ground claims {name}, but only for tonight. The Spire demands more combat.",
    "A voice speaks to {name}'s departing soul. Return. There is more blood to spill.",
    "{name} is dragged back from oblivion by unseen forces. The curse is not finished.",
    "Tomorrow {name} will walk these cursed grounds once more. The Spire is patient.",
    "The dead gather around {name}'s fallen form. They welcome another to their ranks.",
    "{name} will know the torment of resurrection. Again and again, fight after fight.",
    "There is no peace for {name} in this place. Only the endless cycle of combat.",
    "The next dawn will bring {name} back to consciousness, ready to fight once more.",
    "{name} is made immortal through the Spire's curse. Death will not grant escape.",
    "The spirits laugh as {name} falls. They know what comes next for this warrior.",
]

_SOUL_SPIRE_CLOSING_LINES = [
    "A cold wind carries the echoes of the battle across the Soul Spire.",
    "The ghost-lights fade as the bout concludes. The spirits return to their eternal vigil.",
    "The soul-touched crowd settles, and silence once again claims the Spire.",
    "The aftermath of violence hangs in the fetid air. Another day passes in this cursed place.",
    "The crowd of spirits dissipates slowly, already anticipating the next trial.",
    "Darkness reclaims the arena. The show is over for now.",
    "The weight of death settles back upon the Spire. Life holds no power here.",
    "The ground is stained with the memory of combat. The Spire waits for more.",
    "Time moves differently here. Moments stretch into eternities of suffering.",
    "The battle is done, but the torment of the Soul Spire never truly ends.",
    "Night falls eternally in this place. The Spire knows no dawn.",
    "The spirits drift away, satisfied for now. But hunger still burns in their chests.",
    "Silence returns, broken only by the whisper of wind through dead leaves.",
    "The Spire remembers every blow, every fall, every moment of agony.",
    "This is the cycle that never breaks. Fight, fall, rise, fight again.",
    "The air clears slightly. But the curse lingers, waiting for the next combat.",
    "Another day passes in the Soul Spire. How many more will follow?",
]


def elite_spire_intro(warrior_name: str) -> str:
    """Return an Elite Spire fight intro line."""
    message = _pool_choice(_ELITE_SPIRE_INTROS)
    return message.format(name=warrior_name.upper())


def elite_spire_fight_line(warrior_name: str, style: str = "maneuver") -> str:
    """Return an Elite Spire fight description."""
    message = _pool_choice(_ELITE_SPIRE_FIGHT_LINES)
    return message.format(name=warrior_name.upper(), style=style)


def soul_spire_intro(warrior_name: str) -> str:
    """Return a Soul Spire fight intro line."""
    message = _pool_choice(_SOUL_SPIRE_INTROS)
    return message.format(name=warrior_name.upper())


_ELITE_SPIRE_RESURRECTION_LINES = [
    "The Blood Master lifts a hand and the sand falls silent. {name} lies still, but the gods have not finished with this one. A light older than the Spire gathers, and {name} is returned to the living.",
    "Death comes for {name}, and the gods intervene. They have invested too much in this fighter to let the story end here. {name} will rise.",
    "The gods look down upon the fallen {name} and, as they always do in this place, decline to let the matter rest. Breath returns. {name} lives.",
    "{name} is dead. The gods are inconvenienced. A word is spoken in a tongue no mortal has learned, and the wound is simply no longer there.",
    "The Spire's patrons watch {name} fall and weigh the loss. It is a short deliberation. {name} is restored, and the gods return to their wine.",
    "A hush falls over the crowd as {name} goes still. Then the divine hand moves across the sand, and {name} draws breath. The gods have decided the Spire needs this fighter yet.",
    "The Blood Master kneels beside {name}, finds nothing, and steps back. The gods do not need a pulse. {name} rises as if from a long sleep.",
    "{name} has been killed, and the killing is real. So is what follows. The gods reach down, and the Spire gives {name} back.",
    "Heaven is not done with {name}. The fall is witnessed, the death is recorded, and the gods undo it with the casual ease of those who have done it a thousand times.",
    "No mortal bargain was struck here, no price named. The gods simply take {name} from death's hands, and death is in no position to object.",
    "The light that comes for {name} is warm, golden and entirely indifferent to the verdict of the sand. {name} is whole before the crowd has finished gasping.",
    "{name} is carried to the edge of the sand, and the gods take it from there. By the time the fighters are announced for the next bout, {name} is breathing.",
    "The gods remember every name that has fought in the Spire, and they are not yet ready to forget {name}. The divine seal is broken, the wound closes, and the fighter stirs.",
    "A bell sounds from somewhere above the Spire. The crowd knows what it means. {name} is returned, and the gods have made their opinion of death clear once more.",
    "Death takes {name}, and the gods take {name} back. This is the Spire's covenant, and it holds.",
    "The Blood Master bows toward the heavens and steps aside. The gods have heard enough. {name} lives, the wounds of the bout forgotten by the flesh that bore them.",
    "It is a strange thing to watch the gods work. One moment {name} lies broken on the sand, and the next the sand has nothing to show for it. The Spire does not lose its own.",
    "The crowd has seen this before and still it silences them. {name} is gone, and then {name} is not. The gods have ruled that the fight is over but the fighter is not.",
    "Somewhere beyond the walls, a god laughs. {name} takes a deep breath on the sand where the fight ended, and the Spire's covenant is kept again.",
    "{name} falls. The gods, who prize a good fighter above a good ending, set the clock back. The Spire exhales.",
]


def elite_spire_resurrection_line(warrior_name: str) -> str:
    """Return a divine resurrection line for the Elite Spire (the gods revive the fallen)."""
    message = _pool_choice(_ELITE_SPIRE_RESURRECTION_LINES)
    return message.format(name=warrior_name.upper())


def soul_spire_resurrection_line(warrior_name: str) -> str:
    """Return a Soul Spire resurrection line (when a warrior is revived)."""
    message = _pool_choice(_SOUL_SPIRE_RESURRECTION_LINES)
    return message.format(name=warrior_name.upper())


# Soul Spire -> Elite Spire ascension (a second life, body restored).
# House rule: no colons in narrative lines.
_SOUL_TO_ELITE_ASCENSION_LINES = [
    "The gods have watched {name} bleed, fall, and rise again, and they deem {name} worthy of a second life. The gates of the Elite Spire swing open.",
    "Let it be known across the realm of souls that {name} has endured what broke lesser spirits. The heavens mend every wound, restore every scar to unbroken flesh, and set {name} among the Elite.",
    "A hush falls over the Soul Spire as the gods reach down for {name}. Shattered bones knit whole, open wounds close, and every scar fades from their flesh. The trials are over, and the gods are done testing this one.",
    "Death could not hold {name}, and now the gods themselves have taken notice. They name {name} chosen and carry them to the Elite Spire to live again.",
    "Divine fire washes over {name}, burning away every scar and every ache the arena ever carved. They are made whole, and they are made new. The Elite Spire awaits.",
    "The ancient powers have weighed {name}'s deeds in blood and in victory, and they find no flaw worth keeping. Their body is remade, strong and unmarked, and {name} takes a place among the Elite.",
    "The bells of the dead ring for {name}, but this time they ring in triumph. The Soul Spire releases {name} into the Elite Spire, reborn and unbroken.",
    "{name} walked through the fire of the Soul Spire and did not burn. Now the gods breathe life into every weary limb and raise {name}, restored in body and in spirit, to the Elite Spire.",
    "It is written in the stones of the Spire that one soul in a hundred will be seen. The gods have seen {name}, and {name} is raised to the Elite Spire.",
    "The Soul Spire gave {name} a second chance, and they turned it into legend. The gods grant a third gift, a body renewed and free of every wound, and a place in the Elite Spire.",
    "Thunder rolls through the halls of the dead. The gods call {name} by name, no longer a wandering soul but a warrior reborn. The Elite Spire is yours.",
    "They were forgotten by the living and tested by the dead. Now the gods proclaim that {name} has proven worthy. Flesh is restored, strength is returned, and the Elite Spire welcomes its newest immortal.",
    "The spirits of the Soul Spire fall silent and bow their heads as {name} ascends. Every wound fades from their flesh, and the gods declare a second life well earned.",
    "Through every trial of the Soul Spire, {name} refused to stay down. The gods take notice, strip away every scar and every weakness, and lift {name} into the light of the Elite Spire.",
    "No soul climbs from the Soul Spire without the gods' blessing, and {name} has won it with blood and courage. A body made whole and a name made eternal now belong to the Elite Spire.",
]

# Soul Spire final death (death limit reached, taken to the land of the dead).
# Lines 4 and 6 assume exactly one resurrection (max_deaths == 2).
_SOUL_SPIRE_FINAL_DEATH_LINES = [
    "Given a second chance to redeem their soul, {name} failed to impress the gods and is cast into the afterlife for good. There will be no third return.",
    "The gods have looked upon {name} a final time and turned away. The gates of the land of the dead close, and they will not open again.",
    "A second death, and this one is final. {name} has squandered the mercy of the heavens and is claimed by the dead for all eternity.",
    "The Soul Spire gave {name} one chance to rise. {name} fell instead. The gods are silent, and the silence is the verdict.",
    "Mercy has a limit, and {name} has reached it. The soul is taken from the Spire, the name is struck from the rolls, and the dead keep what is theirs.",
    "{name} was called back from the dark once and could not hold the light. The dark takes them again, this time without end.",
    "The gods do not forgive twice. {name}'s soul is dragged beyond the Spire into the land of the dead, never to return.",
    "Let the realm mourn or forget as it chooses. {name} has fallen for the second time, and the gods have closed the book on their story.",
    "The torches of the Soul Spire gutter and die as {name} falls once more. No flame will be lit to call them back. They belong to the afterlife now.",
    "Twice death has come for {name}, and twice is enough. The gods withdraw their favor, and {name} walks the road of the dead forever.",
    "They begged the heavens for another chance, and the heavens answered once. {name} wasted it, and the afterlife claims a soul that will not be given back.",
    "The final toll rings from the Soul Spire. {name} is gone from the arena and gone from the world. The gods have judged, and the dead have a new companion.",
    "The second life that the gods so generously gave {name} ends in the dust of the Soul Spire. The afterlife opens its arms, and this time it will not let go.",
    "{name} stood before the gods a second time and was found wanting. The soul departs the Spire in silence, and the land of the dead takes its due.",
    "There is no third dawn for {name}. The Soul Spire falls quiet, the gods look away, and a warrior's story ends where all stories must end.",
]


def soul_to_elite_ascension_line(warrior_name: str) -> str:
    """Return a Soul Spire -> Elite Spire ascension line."""
    message = _pool_choice(_SOUL_TO_ELITE_ASCENSION_LINES)
    return message.format(name=warrior_name.upper())


def soul_spire_final_death_line(warrior_name: str) -> str:
    """Return a Soul Spire final-death line (death limit reached)."""
    message = _pool_choice(_SOUL_SPIRE_FINAL_DEATH_LINES)
    return message.format(name=warrior_name.upper())


def soul_spire_closing(warrior_name: str = None) -> str:
    """Return a Soul Spire fight closing line."""
    return _pool_choice(_SOUL_SPIRE_CLOSING_LINES)


def get_arena_flavor_line(warrior_name: str, arena: str = "normal") -> str:
    """
    Get a flavor line for the arena, displayed after strategy table and before minute 1.
    The line is neutral/atmospheric and does not name either combatant, so warrior_name
    is unused (kept for call-site compatibility). Returns None for the normal arena.
    """
    if arena == "elite":
        return elite_spire_intro(warrior_name)
    elif arena == "veteran":
        return soul_spire_intro(warrior_name)
    return None
