# =============================================================================
# weapons.py — BLOODSPIRE Weapon Definitions
# =============================================================================
# Contains:
#   - Full weapon table (44 weapons, matching the 44 weapon skills)
#   - Strength requirement lookup
#   - Under-strength penalty calculation (proportional attack rate + damage)
#   - Special weapon rules (armor-piercing, flail bypass, MC-compatible, etc.)
#   - Charge attack eligibility (spears only)
#   - Two-hand handling
# =============================================================================

from dataclasses import dataclass, field
from typing import Optional, List


# ---------------------------------------------------------------------------
# STRENGTH → MAX CARRY WEIGHT TABLE
# Directly from the player's guide.
# ---------------------------------------------------------------------------

STRENGTH_CARRY_TABLE = [
    (3,  3,  0.0),
    (4,  6,  1.0),
    (7,  8,  2.0),
    (9,  11, 3.0),
    (12, 13, 4.0),
    (14, 16, 5.0),
    (17, 18, 6.0),
    (19, 21, 7.0),
    (22, 23, 8.0),
    (24, 25, 9.0),
]


def max_weapon_weight(strength: int) -> float:
    """
    Return the maximum weapon weight a warrior can wield one-handed
    based on their Strength.  Two-handed weapons get a +1 weight allowance
    (applied at equip time, not here).
    """
    for lo, hi, capacity in STRENGTH_CARRY_TABLE:
        if lo <= strength <= hi:
            return capacity
    return 0.0


def strength_penalty(weapon_weight: float, strength: int, two_handed: bool = False) -> float:
    """
    Calculate the under-strength penalty fraction (0.0 = no penalty, 1.0 = unusable).

    APPROX: The guide says under-strength warriors suffer proportional
    attack-rate and damage penalties. We model this as:

        effective_capacity = max_weapon_weight(strength) + (1.0 if two_handed else 0.0)
        if weapon_weight <= effective_capacity: penalty = 0.0
        else:
            overage = weapon_weight - effective_capacity
            penalty = min(1.0, overage / effective_capacity)

    So a warrior who is exactly 1 weight point over capacity suffers a
    penalty equal to (1 / their capacity), never exceeding 100%.

    Returns a float 0.0–1.0.  Callers multiply attack rate and damage by
    (1.0 - penalty).
    """
    capacity = max_weapon_weight(strength) + (1.0 if two_handed else 0.0)
    if weapon_weight <= capacity:
        return 0.0
    if capacity <= 0:
        return 1.0
    overage = weapon_weight - capacity
    return min(1.0, overage / capacity)


# ---------------------------------------------------------------------------
# WEAPON CATEGORIES
# ---------------------------------------------------------------------------

SWORD_KNIFE    = "Sword/Knife"
AXE_PICK       = "Axe/Pick"
HAMMER_MACE    = "Hammer/Mace"
POLEARM_SPEAR  = "Polearm/Spear"
FLAIL          = "Flail"
STAVE          = "Stave"
SHIELD         = "Shield"
ODDBALL        = "Oddball"

ALL_CATEGORIES = [
    SWORD_KNIFE, AXE_PICK, HAMMER_MACE, POLEARM_SPEAR,
    FLAIL, STAVE, SHIELD, ODDBALL,
]


# ---------------------------------------------------------------------------
# WEAPON DATACLASS
# ---------------------------------------------------------------------------

@dataclass
class Weapon:
    """
    A single weapon available in BLOODSPIRE.

    skill_key:   Matches the key used in warrior.skills (snake_case).
    display:     Human-readable name as shown in fight narratives.
    weight:      From the weapon table. Compared against STR carry capacity.
    throwable:   Can be used with Opportunity Throw style.
    two_hand:    Designed for two hands (assign Open Hand to secondary).
                 Two-handed use grants +1 to effective STR carry capacity.
    category:    Weapon family. Determines narrative line pools and style bonuses.

    Special flags (all Boolean):
      armor_piercing   — Does extra damage vs Scale/Chain/Half-Plate/Plate.
                         Weapons: Stiletto, Scythe, Small Pick, Military Pick,
                                  Great Pick, Pick Axe.
      mc_compatible    — Can be used with Martial Combat style.
                         Weapons: Stiletto, Dagger, Knife, Quarterstaff,
                                  Net, Great Staff, Open Hand.
      flail_bypass     — Can wrap around shields and blocking weapons.
                         All Flails.
      charge_attack    — Gets the special spear charge attack based on Charge skill.
                         All Polearms/Spears except Cestus.
      can_disarm       — Has special disarm interaction. Net, Swordbreaker,
                         Scythe, Ball & Chain.
      can_sweep        — Has sweep interaction. Ball & Chain, all Flails.
      is_shield        — Is a shield (affects parry calculations differently).

    preferred_styles: Styles this weapon works especially well with.
                      Used by the AI strategy selector and narrative engine.
    weak_styles:      Styles this weapon actively works against.
    """

    skill_key       : str
    display         : str
    weight          : float
    throwable       : bool
    two_hand        : bool          # Designed for two hands
    category        : str

    # Special rules
    armor_piercing  : bool = False
    mc_compatible   : bool = False
    flail_bypass    : bool = False
    charge_attack   : bool = False
    can_disarm      : bool = False
    can_sweep       : bool = False
    is_shield       : bool = False

    # Style guidance (informational — used by AI and narrative engine)
    preferred_styles: List[str] = field(default_factory=list)
    weak_styles     : List[str] = field(default_factory=list)

    # Flavor notes from the player's guide (used to generate manager tips)
    notes           : str = ""

    @property
    def effective_one_hand_capacity_needed(self) -> float:
        """The strength capacity needed to wield this weapon one-handed."""
        return self.weight

    @property
    def effective_two_hand_capacity_needed(self) -> float:
        """The strength capacity needed to wield this weapon two-handed."""
        return max(0.0, self.weight - 1.0)

    def penalty_for(self, strength: int, two_handed: bool = False) -> float:
        """
        Shorthand: get the under-strength penalty for a given warrior STR.
        Returns 0.0–1.0 (0 = no penalty, 1 = completely ineffective).
        """
        return strength_penalty(self.weight, strength, two_handed)

    def can_wield(self, strength: int, two_handed: bool = False) -> bool:
        """
        True if the warrior can wield this weapon with no penalty.
        Does NOT block equipping — just indicates whether full effectiveness
        is available.
        """
        return self.penalty_for(strength, two_handed) == 0.0

    def __str__(self) -> str:
        flags = []
        if self.throwable:      flags.append("throw")
        if self.two_hand:       flags.append("2H")
        if self.armor_piercing: flags.append("AP")
        if self.flail_bypass:   flags.append("bypass")
        if self.charge_attack:  flags.append("charge")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        return f"{self.display} (wt:{self.weight}){flag_str}"


# ---------------------------------------------------------------------------
# SPECIAL OPEN HAND
# ---------------------------------------------------------------------------

OPEN_HAND = Weapon(
    skill_key        = "open_hand",
    display          = "Open Hand",
    weight           = 0.0,
    throwable        = False,
    two_hand         = False,
    category         = ODDBALL,
    mc_compatible    = True,
    notes            = (
        "Works surprisingly well in Strike and MC styles, but damage is "
        "anemic without high Brawl skill. Assign to secondary for two-handed use."
    ),
    preferred_styles = ["Strike", "Martial Combat"],
)


# ---------------------------------------------------------------------------
# ALL WEAPONS
# Full table — exactly 44 weapons matching the 44 weapon skills.
# Order mirrors the weapon table in the player's guide.
# ---------------------------------------------------------------------------

WEAPONS: dict[str, Weapon] = {

    # =========================================================================
    # SWORDS & KNIVES
    # =========================================================================

    "stiletto": Weapon(
        skill_key     = "stiletto",
        display       = "Stiletto",
        weight        = 1.0,
        throwable     = True,
        two_hand      = False,
        category      = SWORD_KNIFE,
        armor_piercing= True,
        mc_compatible = True,
        notes=(
            "Very high attack rate. Good for weak warriors against heavy armor. "
            "Ultimately does too little damage for high-level play. Halflings like it."
        ),
        preferred_styles=["Lunge", "Martial Combat", "Calculated Attack"],
        weak_styles   =["Bash", "Total Kill"],
    ),

    "knife": Weapon(
        skill_key     = "knife",
        display       = "Knife",
        weight        = 1.5,
        throwable     = True,
        two_hand      = False,
        category      = SWORD_KNIFE,
        mc_compatible = True,
        notes="Attack rate underwhelming for its size. Few warriors succeed with this.",
        preferred_styles=["Strike", "Lunge"],
    ),

    "dagger": Weapon(
        skill_key     = "dagger",
        display       = "Dagger",
        weight        = 2.0,
        throwable     = True,
        two_hand      = False,
        category      = SWORD_KNIFE,
        mc_compatible = True,
        notes=(
            "Very high attack rate. Good in the hands of Elves. Like all small "
            "weapons, insufficient damage at the high end."
        ),
        preferred_styles=["Lunge", "Wall of Steel", "Martial Combat"],
    ),

    "short_sword": Weapon(
        skill_key     = "short_sword",
        display       = "Short Sword",
        weight        = 3.0,
        throwable     = False,
        two_hand      = False,
        category      = SWORD_KNIFE,
        notes=(
            "One of the ultimate weapons. Effective with popular styles for almost "
            "any warrior. Dual Short Sword Elves in Wall of Steel remain top-tier. "
            "The 'Pocket Rocket' Halfling build with a single Short Sword is iconic."
        ),
        preferred_styles=["Wall of Steel", "Strike", "Lunge", "Counterstrike"],
    ),

    "epee": Weapon(
        skill_key     = "epee",
        display       = "Epee",
        weight        = 3.0,
        throwable     = False,
        two_hand      = False,
        category      = SWORD_KNIFE,
        can_disarm    = True,
        notes=(
            "Good attack rate. Decent at disarm. Same late-game damage problem "
            "as other light weapons. Effective in first 50 fights played right."
        ),
        preferred_styles=["Lunge", "Engage & Withdraw", "Sure Strike"],
        weak_styles   =["Bash", "Total Kill"],
    ),

    "scimitar": Weapon(
        skill_key     = "scimitar",
        display       = "Scimitar",
        weight        = 3.5,
        throwable     = False,
        two_hand      = False,
        category      = SWORD_KNIFE,
        notes=(
            "The natural weapon of the Elf. With proper Dexterity, attack rate "
            "is more than adequate. Damage in the mid range. Good all-around."
        ),
        preferred_styles=["Slash", "Lunge", "Wall of Steel"],
    ),

    "longsword": Weapon(
        skill_key     = "longsword",
        display       = "Long Sword",
        weight        = 3.2,
        throwable     = False,
        two_hand      = False,
        category      = SWORD_KNIFE,
        notes=(
            "Attack rate a little slower than expected. Damage low until skilled. "
            "Elves, Half-Elves, and Humans appear most effective."
        ),
        preferred_styles=["Strike", "Counterstrike", "Slash"],
    ),

    "broad_sword": Weapon(
        skill_key     = "broad_sword",
        display       = "Broad Sword",
        weight        = 3.8,
        throwable     = False,
        two_hand      = False,
        category      = SWORD_KNIFE,
        notes=(
            "Not bad, not great. Likes high Dexterity and Elves/Half-Elves. "
            "Needs a bit more than nominal Strength to fully utilize."
        ),
        preferred_styles=["Strike", "Slash", "Counterstrike"],
    ),

    "bastard_sword": Weapon(
        skill_key     = "bastard_sword",
        display       = "Bastard Sword",
        weight        = 4.8,
        throwable     = False,
        two_hand      = True,
        category      = SWORD_KNIFE,
        notes=(
            "High attack rate for a heavy weapon. Excellent with Slash. "
            "Lacks consistent high damage hits for its size. Half-Elves love it."
        ),
        preferred_styles=["Slash", "Strike", "Wall of Steel"],
    ),

    "great_sword": Weapon(
        skill_key     = "great_sword",
        display       = "Great Sword",
        weight        = 6.8,
        throwable     = False,
        two_hand      = True,
        category      = SWORD_KNIFE,
        notes=(
            "In the hands of Half-Orcs, incredible. Stat requirements are very "
            "high but well worth it."
        ),
        preferred_styles=["Slash", "Total Kill", "Bash"],
        weak_styles   =["Lunge", "Calculated Attack"],
    ),

    # =========================================================================
    # AXES & PICKS
    # =========================================================================

    "hatchet": Weapon(
        skill_key     = "hatchet",
        display       = "Hatchet",
        weight        = 1.8,
        throwable     = True,
        two_hand      = False,
        category      = AXE_PICK,
        notes="Light, fast, great early. Fails to deliver damage in later fights. Halflings like it.",
        preferred_styles=["Strike", "Wall of Steel", "Opportunity Throw"],
    ),

    "francisca": Weapon(
        skill_key     = "francisca",
        display       = "Fransisca",
        weight        = 2.5,
        throwable     = True,
        two_hand      = False,
        category      = AXE_PICK,
        notes="Consistently average for most. Dwarves can excel with it.",
        preferred_styles=["Strike", "Bash", "Opportunity Throw"],
    ),

    "battle_axe": Weapon(
        skill_key     = "battle_axe",
        display       = "Battle Axe",
        weight        = 4.5,
        throwable     = False,
        two_hand      = False,
        category      = AXE_PICK,
        notes=(
            "Decent damage but attack rate slightly too slow for top-tier. "
            "Good for Counterstrike users. Excellent for low-DEX, high-STR Dwarves."
        ),
        preferred_styles=["Counterstrike", "Bash", "Strike"],
        weak_styles   =["Wall of Steel"],
    ),

    "great_axe": Weapon(
        skill_key     = "great_axe",
        display       = "Great Axe",
        weight        = 6.0,
        throwable     = False,
        two_hand      = True,
        category      = AXE_PICK,
        notes=(
            "Like the Great Sword for Half-Orcs: can do staggering damage. "
            "Attack rate low due to size. Very high stat requirements."
        ),
        preferred_styles=["Bash", "Total Kill", "Slash"],
    ),

    "small_pick": Weapon(
        skill_key     = "small_pick",
        display       = "Small Pick",
        weight        = 2.8,
        throwable     = False,
        two_hand      = False,
        category      = AXE_PICK,
        armor_piercing= True,
        notes="Fast and effective early, starts becoming ineffective around fight 50. Humans and Halflings.",
        preferred_styles=["Lunge", "Calculated Attack", "Strike"],
    ),

    "military_pick": Weapon(
        skill_key     = "military_pick",
        display       = "Military Pick",
        weight        = 3.5,
        throwable     = False,
        two_hand      = False,
        category      = AXE_PICK,
        armor_piercing= True,
        notes=(
            "A Human favorite. Very effective in higher fights once opponents "
            "have graduated to Scale and above. Works in many popular styles."
        ),
        preferred_styles=["Calculated Attack", "Strike", "Lunge"],
    ),

    "pick_axe": Weapon(
        skill_key     = "pick_axe",
        display       = "Pick Axe",
        weight        = 4.8,
        throwable     = False,
        two_hand      = True,
        category      = AXE_PICK,
        armor_piercing= True,
        notes="New to the Pit. Insufficient data to characterize.",
        preferred_styles=["Bash", "Calculated Attack"],
    ),

    # =========================================================================
    # HAMMERS & MACES
    # =========================================================================

    "hammer": Weapon(
        skill_key     = "hammer",
        display       = "Hammer",
        weight        = 2.0,
        throwable     = True,
        two_hand      = False,
        category      = HAMMER_MACE,
        notes="Above-average damage and attack rate. Viability in late fights debated. Halflings and Humans.",
        preferred_styles=["Bash", "Strike", "Opportunity Throw"],
    ),

    "mace": Weapon(
        skill_key     = "mace",
        display       = "Mace",
        weight        = 3.0,
        throwable     = False,
        two_hand      = False,
        category      = HAMMER_MACE,
        notes="Terribly inconsistent. The Epee of the hammer family.",
        preferred_styles=["Bash", "Strike"],
    ),

    "morningstar": Weapon(
        skill_key     = "morningstar",
        display       = "Morningstar",
        weight        = 4.0,
        throwable     = False,
        two_hand      = False,
        category      = HAMMER_MACE,
        notes=(
            "One of the great weapons. Consistent high damage once minimums met. "
            "Effective for all races."
        ),
        preferred_styles=["Bash", "Strike", "Counterstrike"],
    ),

    "war_hammer": Weapon(
        skill_key     = "war_hammer",
        display       = "War Hammer",
        weight        = 4.5,
        throwable     = False,
        two_hand      = False,
        category      = HAMMER_MACE,
        notes=(
            "A Half-Orc favorite. Good weapon in the right hands. "
            "Requires 20+ Strength to truly 'sing'."
        ),
        preferred_styles=["Bash", "Total Kill", "Strike"],
    ),

    "maul": Weapon(
        skill_key     = "maul",
        display       = "Maul",
        weight        = 7.5,
        throwable     = False,
        two_hand      = True,
        category      = HAMMER_MACE,
        notes="Too slow to be effective; lacks the defenses to compensate. Requires very high Strength.",
        preferred_styles=["Total Kill", "Bash"],
        weak_styles   =["Wall of Steel", "Lunge"],
    ),

    "club": Weapon(
        skill_key     = "club",
        display       = "Club",
        weight        = 2.7,
        throwable     = False,
        two_hand      = False,
        category      = HAMMER_MACE,
        notes=(
            "A simple length of heavy wood, sometimes reinforced with metal bands. "
            "Brutal and straightforward. Favored by dirty fighters and beginners alike."
        ),
        preferred_styles=["Bash", "Strike"],
    ),

    # =========================================================================
    # POLEARMS & SPEARS
    # =========================================================================

    "short_spear": Weapon(
        skill_key     = "short_spear",
        display       = "Short Spear",
        weight        = 3.0,
        throwable     = True,
        two_hand      = False,
        category      = POLEARM_SPEAR,
        charge_attack = True,
        notes=(
            "Light and potent weapon. Effective in Lunge, Wall of "
            "Steel, and Strike. Can throw. Use with a shield. "
            "Great attack rate and average to above average damage. Favored by all races."
        ),
        preferred_styles=["Lunge", "Wall of Steel", "Strike", "Opportunity Throw"],
    ),

    "boar_spear": Weapon(
        skill_key     = "boar_spear",
        display       = "Boar Spear",
        weight        = 3.8,
        throwable     = True,
        two_hand      = False,
        category      = POLEARM_SPEAR,
        charge_attack = True,
        notes=(
            "Arguably the best weapon in the game. Effective in Lunge, Wall of "
            "Steel, and Strike. Can throw. Use with a shield. "
            "Great attack rate and damage. Favored by all races."
        ),
        preferred_styles=["Lunge", "Wall of Steel", "Strike", "Opportunity Throw"],
    ),

    "long_spear": Weapon(
        skill_key     = "long_spear",
        display       = "Long Spear",
        weight        = 4.2,
        throwable     = False,
        two_hand      = True,
        category      = POLEARM_SPEAR,
        charge_attack = True,
        notes=(
            "Good in Half-Elves and some Half-Orcs. Same advantages as Boar Spear "
            "with more damage kick. Excels at 7+ APM."
        ),
        preferred_styles=["Lunge", "Strike", "Wall of Steel"],
    ),

    "pole_axe": Weapon(
        skill_key     = "pole_axe",
        display       = "Pole Axe",
        weight        = 5.5,
        throwable     = False,
        two_hand      = True,
        category      = POLEARM_SPEAR,
        charge_attack = True,
        notes=(
            "A Half-Elf favorite that underperforms for other races. "
            "Half-Orcs have had decent success with it."
        ),
        preferred_styles=["Strike", "Lunge", "Wall of Steel"],
    ),

    "halberd": Weapon(
        skill_key     = "halberd",
        display       = "Halberd",
        weight        = 7.5,
        throwable     = False,
        two_hand      = True,
        category      = POLEARM_SPEAR,
        charge_attack = True,
        notes=(
            "Tough to use but certain Half-Orcs devastate with it. "
            "Requires very high Strength. Also known to work with Engage & Withdraw."
        ),
        preferred_styles=["Total Kill", "Engage & Withdraw"],
    ),

    # =========================================================================
    # FLAILS
    # =========================================================================

    "flail": Weapon(
        skill_key     = "flail",
        display       = "Flail",
        weight        = 2.6,
        throwable     = False,
        two_hand      = False,
        category      = FLAIL,
        flail_bypass  = True,
        can_sweep     = True,
        notes=(
            "Unique: most of its damage is based on SIZE not STR. "
            "Elves like Flails; most races do well."
        ),
        preferred_styles=["Strike", "Wall of Steel", "Bash"],
    ),

    "bladed_flail": Weapon(
        skill_key     = "bladed_flail",
        display       = "Bladed Flail",
        weight        = 4.0,
        throwable     = False,
        two_hand      = False,
        category      = FLAIL,
        flail_bypass  = True,
        can_sweep     = True,
        notes=(
            "Halflings and Half-Orcs love it. Great damage against light armor; "
            "huge drop-off against Scale+. Hard to use as a top-tier late weapon."
        ),
        preferred_styles=["Bash", "Strike", "Wall of Steel"],
    ),

    "war_flail": Weapon(
        skill_key     = "war_flail",
        display       = "War Flail",
        weight        = 5.0,
        throwable     = False,
        two_hand      = False,
        category      = FLAIL,
        flail_bypass  = True,
        can_sweep     = True,
        notes="One of the best weapons in the game, especially for Half-Orcs. Damage tuned down slightly from original legendary status.",
        preferred_styles=["Total Kill", "Bash", "Strike"],
    ),

    "battle_flail": Weapon(
        skill_key     = "battle_flail",
        display       = "Battle Flail",
        weight        = 6.5,
        throwable     = False,
        two_hand      = True,
        category      = FLAIL,
        flail_bypass  = True,
        can_sweep     = True,
        notes=(
            "Half-Elf favorite (extra attack with it). Attack rate too low vs "
            "damage rate compared to War Flail. Half-Orcs also succeed."
        ),
        preferred_styles=["Bash", "Total Kill"],
        weak_styles   =["Lunge", "Calculated Attack"],
    ),

    # =========================================================================
    # STAVES
    # =========================================================================

    "quarterstaff": Weapon(
        skill_key     = "quarterstaff",
        display       = "Quarterstaff",
        weight        = 3.0,
        throwable     = False,
        two_hand      = True,
        category      = STAVE,
        mc_compatible = True,
        notes=(
            "A Halfling favorite. Good with Martial Combat. "
            "Currently underwhelming in the Pit."
        ),
        preferred_styles=["Martial Combat", "Strike", "Parry"],
    ),

    "great_staff": Weapon(
        skill_key     = "great_staff",
        display       = "Great Staff",
        weight        = 5.5,
        throwable     = False,
        two_hand      = True,
        category      = STAVE,
        mc_compatible = True,
        notes="Larger, heavier Quarterstaff. Attack rate lower than expected; too slow for reliable parry.",
        preferred_styles=["Martial Combat", "Strike"],
    ),

    # =========================================================================
    # SHIELDS
    # =========================================================================

    "buckler": Weapon(
        skill_key     = "buckler",
        display       = "Buckler",
        weight        = 2.2,
        throwable     = False,
        two_hand      = False,
        category      = SHIELD,
        is_shield     = True,
        notes="Fairly weak shield. Not really worth using.",
        preferred_styles=["Counterstrike", "Parry", "Defend"],
    ),

    "target_shield": Weapon(
        skill_key     = "target_shield",
        display       = "Target Shield",
        weight        = 4.2,
        throwable     = False,
        two_hand      = False,
        category      = SHIELD,
        is_shield     = True,
        notes="Current sweet-spot shield for Dwarves.",
        preferred_styles=["Counterstrike", "Parry", "Defend", "Wall of Steel"],
    ),

    "tower_shield": Weapon(
        skill_key     = "tower_shield",
        display       = "Tower Shield",
        weight        = 5.5,
        throwable     = False,
        two_hand      = False,
        category      = SHIELD,
        is_shield     = True,
        notes="Once legendary, now tuned. Only shield that helps against very skilled warriors. Half-Orcs prefer it.",
        preferred_styles=["Counterstrike", "Parry", "Defend"],
    ),

    # =========================================================================
    # ODDBALLS
    # =========================================================================

    "cestus": Weapon(
        skill_key     = "cestus",
        display       = "Cestus",
        weight        = 1.0,
        throwable     = False,
        two_hand      = False,
        category      = ODDBALL,
        mc_compatible = True,
        notes=(
            "Outside MC, underwhelming. Some Half-Elf Martial Artists get "
            "incredible damage with it. Cannot hold another weapon in that hand."
        ),
        preferred_styles=["Martial Combat"],
    ),

    "trident": Weapon(
        skill_key     = "trident",
        display       = "Trident",
        weight        = 4.3,
        throwable     = False,
        two_hand      = False,       # Needs 2H unless warrior is very strong
        category      = ODDBALL,
        charge_attack = True,        # Three-pronged pole — classified with spears
        notes=(
            "Once much stronger. Gets good results for Dwarves and Half-Elves. "
            "No longer competitive with Boar Spear."
        ),
        preferred_styles=["Lunge", "Strike"],
    ),

    "net": Weapon(
        skill_key     = "net",
        display       = "Net",
        weight        = 2.5,
        throwable     = False,
        two_hand      = False,
        category      = ODDBALL,
        mc_compatible = True,
        can_disarm    = True,
        notes=(
            "Specialty weapon. Success with Dwarves. Throws frustrating entangle "
            "attacks. Works with Sure Strike and Wall of Steel. Hit and miss."
        ),
        preferred_styles=["Sure Strike", "Wall of Steel"],
    ),

    "scythe": Weapon(
        skill_key     = "scythe",
        display       = "Scythe",
        weight        = 3.5,
        throwable     = False,
        two_hand      = False,
        category      = ODDBALL,
        armor_piercing= True,
        can_disarm    = True,
        notes=(
            "Sings in Elf hands. Armor-piercing blade. Can use Slash effectively. "
            "Devastating for almost any warrior except Half-Orcs."
        ),
        preferred_styles=["Slash", "Calculated Attack", "Lunge"],
    ),

    "great_pick": Weapon(
        skill_key     = "great_pick",
        display       = "Great Pick",
        weight        = 7.5,
        throwable     = False,
        two_hand      = True,
        category      = ODDBALL,
        armor_piercing= True,
        notes=(
            "In the right Half-Orc or Dwarf hands: unstoppable killing machine. "
            "Against light armor (CB or leather) it's like hitting with a wiffle bat."
        ),
        preferred_styles=["Total Kill", "Bash", "Calculated Attack"],
    ),

    "javelin": Weapon(
        skill_key     = "javelin",
        display       = "Javelin",
        weight        = 2.5,
        throwable     = True,
        two_hand      = False,
        category      = ODDBALL,
        charge_attack = True,
        notes=(
            "Great below 50 fights. Has many Boar Spear benefits at a higher "
            "attack rate. Halflings and Elves both like it."
        ),
        preferred_styles=["Lunge", "Opportunity Throw", "Strike"],
    ),

    "ball_and_chain": Weapon(
        skill_key     = "ball_and_chain",
        display       = "Ball & Chain",
        weight        = 7.5,
        throwable     = False,
        two_hand      = True,
        category      = ODDBALL,
        flail_bypass  = True,
        can_disarm    = True,
        can_sweep     = True,
        notes=(
            "Very high damage rate but very low attack rate. "
            "Can finish a fight in 2 hits — if you survive the 10 they land first."
        ),
        preferred_styles=["Total Kill", "Bash"],
        weak_styles   =["Wall of Steel", "Lunge"],
    ),

    "bola": Weapon(
        skill_key     = "bola",
        display       = "Bola",
        weight        = 3.1,
        throwable     = True,
        two_hand      = False,
        category      = ODDBALL,
        notes=(
            "Weighted cords with heavy balls. Can be thrown to entangle legs and cause falls, "
            "or swung in melee like a crude flail. Deals only bludgeoning damage."
        ),
        preferred_styles=["Opportunity Throw", "Bash", "Strike"],
    ),

    "heavy_whip": Weapon(
        skill_key     = "heavy_whip",
        display       = "Heavy Barbed Whip",
        weight        = 2.1,
        throwable     = False,
        two_hand      = False,
        category      = ODDBALL,
        notes=(
            "A long, heavy whip with barbs or hooks. Can lash to slash or wrap around limbs "
            "to trip an opponent. Deals a mix of blunt and slashing damage."
        ),
        preferred_styles=["Slash", "Engage & Withdraw"],
    ),

    "swordbreaker": Weapon(
        skill_key     = "swordbreaker",
        display       = "Swordbreaker",
        weight        = 2.6,
        throwable     = False,
        two_hand      = False,
        category      = ODDBALL,
        can_disarm    = True,
        notes=(
            "Best in off-hand vs bladed weapons. Lack of bladed weapons in the "
            "Pit limits its value. Very effective if you know your opponent uses blades."
        ),
        preferred_styles=["Counterstrike", "Decoy"],
    ),

    "open_hand": OPEN_HAND,
}


# ---------------------------------------------------------------------------
# FAVORITE WEAPON FLAVOR LINES
# ---------------------------------------------------------------------------
# Narrative descriptions used when a warrior uses their favorite weapon
# in combat. One random line is selected per weapon per fight.
# Format: weapon_display_name -> list of flavor strings

FAVORITE_WEAPON_LINES = {
    # Swords & Knives
    "Stiletto": [
        "{name}'s stiletto darts forward like a striking serpent finding the tiniest gap in the armor. This is clearly {name}'s favored weapon.",
        "{name}'s stiletto slides toward its target with surgical precision hungry for a vital point. The crowd sees this is {name}'s weapon of choice.",
        "{name}'s thin stiletto flashes with deadly intent a needle seeking the perfect vein. None doubt this is {name}'s favorite blade.",
        "{name}'s stiletto moves with whispering speed almost too fast for the eye to follow. It is obvious the stiletto is {name}'s true love in the pit.",
        "A single perfect thrust. {name}'s stiletto feels alive in {name}'s hand eager to bite. This weapon was made for {name}.",
    ],
    "Knife": [
        "{name}'s knife flicks out with practiced ease a tool turned deadly in an instant. The arena knows this is {name}'s favored weapon.",
        "{name}'s knife delivers a quick vicious slash. It knows exactly where to cut deepest. This is clearly {name}'s weapon of choice.",
        "{name}'s small knife dances dangerously close looking for soft flesh. None can mistake how much {name} favors this blade.",
        "{name}'s knife strikes with the speed of a cornered rat sudden and mean. The crowd cheers {name}'s favorite weapon.",
        "{name}'s brutal little knife finds its way into the fight with ugly efficiency. This is the weapon {name} trusts above all others.",
    ],
    "Dagger": [
        "{name}'s dagger lunges forward hungry for the spaces between armor plates. This is unmistakably {name}'s favored weapon.",
        "{name}'s dagger delivers a precise thrusting strike. It feels perfectly balanced for murder in {name}'s grip. {name}'s favorite by far.",
        "{name}'s dagger flashes in a tight arc seeking the throat or the gap under the arm. The pit knows this is {name}'s chosen blade.",
        "With a fighter's instinct {name}'s dagger drives home short and vicious. This weapon is clearly {name}'s true favorite.",
        "{name}'s dagger moves like an extension of {name}'s hand cold sharp and personal. The crowd senses {name}'s deep bond with this dagger.",
    ],
    "Short Sword": [
        "{name}'s short sword cuts with economical grace never wasting a motion. This is clearly {name}'s favored weapon.",
        "{name}'s short sword delivers a clean controlled thrust. It feels right at home in {name}'s skilled hands. {name}'s weapon of choice.",
        "{name}'s short sword snaps forward quick and businesslike. The arena recognizes this as {name}'s favorite blade.",
        "Balanced and deadly {name}'s short sword finds its mark with professional efficiency. None doubt {name}'s bond with this sword.",
        "{name}'s short sword moves with the confidence of a weapon that has seen many fights at {name}'s side. This is {name}'s true favorite.",
    ],
    "Epee": [
        "{name}'s epee extends like a silver needle seeking a single perfect point. This is clearly {name}'s favored weapon.",
        "{name}'s epee delivers a lightning quick thrust. It dances on the edge of visibility. {name}'s weapon of choice.",
        "{name}'s slender epee probes for weakness with aristocratic precision. The pit knows this is {name}'s favorite.",
        "{name}'s epee flicks forward elegant and lethal in the same motion. This blade was made for {name}.",
        "A master's weapon. {name}'s epee moves with deceptive speed and deadly focus. {name}'s true favorite in the arena.",
    ],
    "Scimitar": [
        "{name}'s scimitar sweeps in a graceful deadly arc hungry for flesh. This is clearly {name}'s favored weapon.",
        "{name}'s curved scimitar sings as it cuts through the air promising pain. The crowd sees {name}'s favorite blade at work.",
        "A flashing draw cut from {name}'s scimitar beautiful and brutal. This is the weapon {name} loves most.",
        "{name}'s scimitar moves like liquid steel flowing into the perfect angle. {name}'s bond with this blade is obvious.",
        "With a desert warrior's flair {name}'s scimitar carves its path through the fight. {name}'s true favorite.",
    ],
    "Longsword": [
        "{name}'s longsword extends with measured power seeking to dominate the space. This is clearly {name}'s favored weapon.",
        "{name}'s longsword delivers a strong controlled cut. It demands respect and space. {name}'s weapon of choice.",
        "{name}'s longsword moves with the weight of authority behind every strike. The arena knows this is {name}'s favorite.",
        "Balanced and deadly {name}'s longsword finds its rhythm in skilled hands. This blade belongs to {name}.",
        "{name}'s longsword cuts with purpose a noble weapon in a brutal arena. {name}'s true favorite.",
    ],
    "Broad Sword": [
        "{name}'s broadsword swings with solid reliable force. This is clearly {name}'s favored weapon.",
        "{name}'s broadsword delivers a heavy practical cut no frills just results. {name}'s weapon of choice.",
        "{name}'s broadsword carries its message with straightforward power. The pit recognizes {name}'s favorite blade.",
        "Reliable and strong {name}'s broadsword does exactly what is asked of it. This is the weapon {name} trusts most.",
        "{name}'s broadsword hacks forward with the confidence of a well made tool. {name}'s true favorite in battle.",
    ],
    "Bastard Sword": [
        "{name}'s bastard sword moves with surprising speed for its size a hybrid of grace and power. This is clearly {name}'s favored weapon.",
        "Gripped in one or two hands {name}'s bastard sword strikes with flexible lethality. {name}'s weapon of choice.",
        "{name}'s bastard sword finds the perfect balance between reach and control. The crowd knows this is {name}'s favorite.",
        "A versatile weapon {name}'s bastard sword adapts to {name}'s needs in the moment. This blade was made for {name}.",
        "{name}'s bastard sword cuts with the weight of both precision and brute force. {name}'s true favorite.",
    ],
    "Great Sword": [
        "{name}'s great sword sweeps through the air like a falling tree terrifying in its arc. This is clearly {name}'s favored weapon.",
        "{name}'s great sword delivers a massive two handed cut. It demands space and respect. {name}'s weapon of choice.",
        "{name}'s great sword moves with unstoppable momentum once it begins its path. The pit knows this is {name}'s favorite.",
        "A weapon built for devastation {name}'s great sword cleaves everything in its path. This is the blade {name} loves most.",
        "{name}'s great sword roars as it descends promising to end the fight in a single blow. {name}'s true favorite.",
    ],
    # Axes & Picks
    "Hatchet": [
        "{name}'s hatchet flashes forward in a quick brutal chop. This is clearly {name}'s favored weapon.",
        "{name}'s hatchet bites deep when it lands. A small but vicious axe. {name}'s weapon of choice.",
        "{name}'s hatchet moves with surprising speed a woodsman's tool turned deadly. The arena sees {name}'s favorite.",
        "Short sharp and mean {name}'s hatchet finds its target with ugly efficiency. This is the weapon {name} trusts most.",
        "{name}'s hatchet hacks forward looking to split bone and armor alike. {name}'s true favorite in the pit.",
    ],
    "Fransisca": [
        "{name}'s fransisca spins through the air with deadly accuracy. This is clearly {name}'s favored weapon.",
        "{name}'s fransisca seeks flesh and bone with purpose. A throwing axe that belongs to {name}. {name}'s weapon of choice.",
        "{name}'s fransisca whistles as it flies a dwarf forged promise of pain. The crowd knows this is {name}'s favorite.",
        "With a warrior's practiced toss {name}'s fransisca seeks its mark. This axe was made for {name}.",
        "{name}'s fransisca cuts a deadly path spinning end over end toward its target. {name}'s true favorite.",
    ],
    "Battle Axe": [
        "{name}'s battle axe descends with crushing force hungry for armor and bone. This is clearly {name}'s favored weapon.",
        "{name}'s battle axe delivers a heavy two handed chop. It means business. {name}'s weapon of choice.",
        "{name}'s battle axe swings in a wide devastating arc. The pit recognizes this as {name}'s favorite.",
        "With dwarven strength behind it {name}'s battle axe splits the air. This is the axe {name} loves most.",
        "{name}'s battle axe hacks forward designed to cleave through shields and helms. {name}'s true favorite.",
    ],
    "Great Axe": [
        "{name}'s great axe comes down like the wrath of the mountains themselves. This is clearly {name}'s favored weapon.",
        "{name}'s great axe cleaves the air with terrifying power and reach. The pit knows this is the weapon {name} was born to wield.",
        "When {name}'s great axe swings lesser weapons seem like toys. {name}'s bond with this axe is obvious to all.",
        "{name}'s great axe moves with unstoppable momentum promising utter ruin. This is clearly {name}'s favorite.",
        "{name}'s great axe brings devastation with every strike. The crowd cheers {name}'s weapon of choice.",
    ],
    "Small Pick": [
        "{name}'s small pick darts forward seeking the weak points in armor. This is clearly {name}'s favored weapon.",
        "{name}'s small pick delivers a precise piercing strike. It is looking for a gap. {name}'s weapon of choice.",
        "{name}'s pick punches forward a needle of steel aimed at vulnerable joints. The arena sees {name}'s favorite.",
        "With surgical intent {name}'s small pick probes for a killing blow. This is the weapon {name} trusts most.",
        "{name}'s small pick strikes like an ice pick through snow sharp and sudden. {name}'s true favorite.",
    ],
    "Military Pick": [
        "{name}'s military pick drives forward with brutal armor piercing intent. This is clearly {name}'s favored weapon.",
        "{name}'s military pick seeks to punch through steel. A weapon made for war. {name}'s weapon of choice.",
        "{name}'s pick crashes forward designed to crack helms and split breastplates. The pit knows this is {name}'s favorite.",
        "With practiced efficiency {name}'s military pick finds its mark. This is the weapon {name} loves most.",
        "{name}'s military pick strikes with the cold certainty of a battlefield veteran. {name}'s true favorite.",
    ],
    "Pick Axe": [
        "{name}'s pick axe comes down with mining fury meant to break stone and bone alike. This is clearly {name}'s favored weapon.",
        "{name}'s pick axe brings the mountain's anger to the pit. A heavy two handed pick. {name}'s weapon of choice.",
        "{name}'s pick axe swings with devastating force looking to split anything in its path. The crowd sees {name}'s favorite.",
        "A brutal tool turned weapon {name}'s pick axe demands respect through violence. This is {name}'s true favorite.",
        "{name}'s pick axe crashes down a miner's rage given lethal purpose. {name}'s bond with this weapon is obvious.",
    ],
    # Hammers & Maces
    "Hammer": [
        "{name}'s hammer swings with straightforward bone crushing intent. This is clearly {name}'s favored weapon.",
        "{name}'s hammer does what hammers do best. A solid reliable strike. {name}'s weapon of choice.",
        "{name}'s hammer falls like judgment seeking to break what stands before it. The arena knows this is {name}'s favorite.",
        "With practiced swings {name}'s hammer seeks to pulp armor and flesh. This is the weapon {name} trusts most.",
        "{name}'s hammer delivers its message with blunt uncompromising force. {name}'s true favorite in the pit.",
    ],
    "Mace": [
        "{name}'s mace swings in a heavy punishing arc. This is clearly {name}'s favored weapon.",
        "Flanged and brutal {name}'s mace seeks to crush anything it touches. {name}'s weapon of choice.",
        "{name}'s mace falls with the weight of authority behind every blow. The pit recognizes {name}'s favorite.",
        "A weapon that speaks in broken bones. {name}'s mace does its work well. This is {name}'s true favorite.",
        "{name}'s mace crashes forward designed to end arguments permanently. {name}'s bond with this weapon is clear.",
    ],
    "Morning Star": [
        "{name}'s morning star whips through the air spikes hungry for blood. This is clearly {name}'s favored weapon.",
        "{name}'s morning star swings with deadly grace its spikes singing for flesh. The arena recognizes {name}'s favorite weapon instantly.",
        "{name}'s morning star promises agony with every rotation. None doubt this is the weapon {name} loves most in the pit.",
        "With expert control {name}'s morning star seeks the perfect striking angle. This is {name}'s true weapon of choice.",
        "{name}'s morning star descends like a falling star cruel and bright. The crowd roars for {name}'s favored weapon.",
    ],
    "War Hammer": [
        "{name}'s war hammer comes down with the force of a thunderclap. This is clearly {name}'s favored weapon.",
        "{name}'s war hammer means to end the fight. A weapon built for breaking armor. {name}'s weapon of choice.",
        "{name}'s war hammer swings with devastating concentrated power. The pit knows this is {name}'s favorite.",
        "With half orc strength behind it {name}'s war hammer becomes a siege engine. This is the weapon {name} loves most.",
        "{name}'s war hammer falls like divine judgment on the unworthy. {name}'s true favorite.",
    ],
    "Maul": [
        "{name}'s maul swings like a falling tree unstoppable and crushing. This is clearly {name}'s favored weapon.",
        "{name}'s maul cares nothing for finesse. A weapon of pure brute force. {name}'s weapon of choice.",
        "{name}'s maul descends with terrifying momentum seeking total destruction. The arena sees {name}'s favorite.",
        "When {name}'s maul moves lesser warriors step back instinctively. This is the weapon {name} trusts most.",
        "{name}'s maul brings the weight of the battlefield itself down on its target. {name}'s true favorite.",
    ],
    "Club": [
        "{name}'s club swings with simple brutal honesty. This is clearly {name}'s favored weapon.",
        "{name}'s club seeks to break what it hits. A crude but effective weapon. {name}'s weapon of choice.",
        "{name}'s club comes down with the force of raw unrefined violence. The arena recognizes {name}'s favorite.",
        "With straightforward intent {name}'s club delivers its message in broken bones. This is the weapon {name} loves most.",
        "{name}'s club moves like the first weapon humanity ever made simple and final. {name}'s true favorite.",
    ],
    # Polearms & Spears
    "Short Spear": [
        "{name}'s short spear lunges forward with precise deadly reach. This is clearly {name}'s favored weapon.",
        "{name}'s short spear finds its mark with ease. The arena sees how perfectly it suits {name} as {name}'s favorite.",
        "With confident thrusts {name}'s short spear tests defenses and seeks gaps. None doubt this is {name}'s chosen weapon.",
        "{name}'s short spear strikes true balanced and deadly in close quarters. This is {name}'s weapon of the heart.",
        "{name}'s short spear moves with the confidence of a weapon made for {name}. {name}'s true favorite in every fight.",
    ],
    "Boar Spear": [
        "{name}'s boar spear drives forward with the power of a charging beast. This is clearly {name}'s favored weapon.",
        "{name}'s boar spear means to impale and hold. A long brutal thrust. {name}'s weapon of choice.",
        "{name}'s boar spear lunges with hunting precision seeking vital organs. The pit knows this is {name}'s favorite.",
        "With practiced skill {name}'s boar spear finds the perfect angle for maximum damage. This is the weapon {name} loves most.",
        "{name}'s boar spear strikes like a predator's fang deep and final. {name}'s true favorite.",
    ],
    "Long Spear": [
        "{name}'s long spear extends with dangerous reach keeping the enemy at bay. This is clearly {name}'s favored weapon.",
        "{name}'s long spear commands the space. A disciplined powerful thrust. {name}'s weapon of choice.",
        "{name}'s long spear moves with calculated lethality probing for weakness. The arena recognizes {name}'s favorite.",
        "With superior range {name}'s long spear dictates the terms of the fight. This is {name}'s true favorite.",
        "{name}'s long spear strikes from a distance that lesser weapons cannot match. {name}'s bond with this spear is obvious.",
    ],
    "Pole Axe": [
        "{name}'s pole axe swings in a wide devastating arc axe head hungry for flesh. This is clearly {name}'s favored weapon.",
        "{name}'s pole axe combines reach and cleaving power. A versatile and brutal weapon. {name}'s weapon of choice.",
        "{name}'s pole axe comes down with the force of a woodsman's fury. The pit knows this is {name}'s favorite.",
        "With expert handling {name}'s pole axe finds the perfect moment to strike. This is the weapon {name} loves most.",
        "{name}'s pole axe moves like an extension of {name}'s rage. {name}'s true favorite.",
    ],
    "Halberd": [
        "{name}'s halberd descends with terrifying authority a weapon of war and execution. This is clearly {name}'s favored weapon.",
        "{name}'s halberd brings axe spike and hook to the fight. A complex and deadly tool. {name}'s weapon of choice.",
        "{name}'s halberd strikes with the weight of a battlefield veteran's experience. The arena sees {name}'s favorite.",
        "With practiced mastery {name}'s halberd finds the perfect angle for maximum carnage. This is {name}'s true favorite.",
        "{name}'s halberd moves like a reaper's scythe promising to end the fight decisively. {name}'s bond with this weapon is clear.",
    ],
    # Flails
    "Flail": [
        "{name}'s flail whips through the air in an unpredictable deadly arc. This is clearly {name}'s favored weapon.",
        "{name}'s flail defies easy defense. A chaotic and vicious weapon. {name}'s weapon of choice.",
        "{name}'s flail lashes out like a striking serpent seeking any opening. The pit knows this is {name}'s favorite.",
        "With expert timing {name}'s flail finds its way past guard and shield. This is the weapon {name} trusts most.",
        "{name}'s flail moves with a mind of its own hungry for contact. {name}'s true favorite.",
    ],
    "Bladed Flail": [
        "{name}'s bladed flail sings a cruel song as its edges cut through the air. This is clearly {name}'s favored weapon.",
        "{name}'s bladed flail leaves nothing untouched. A weapon of pain and blood. {name}'s weapon of choice.",
        "{name}'s bladed flail lashes forward its edges promising terrible wounds. The crowd sees {name}'s favorite.",
        "With vicious intent {name}'s bladed flail seeks to tear and rend. This is {name}'s true favorite.",
        "{name}'s bladed flail moves like a storm of razor edges beautiful and deadly. {name}'s bond with this weapon is obvious.",
    ],
    "War Flail": [
        "{name}'s war flail swings with devastating crushing force. This is clearly {name}'s favored weapon.",
        "{name}'s war flail means to end resistance. A brutal and heavy weapon. {name}'s weapon of choice.",
        "{name}'s war flail comes down like a falling building unstoppable once in motion. The pit knows this is {name}'s favorite.",
        "With half orc strength behind it {name}'s war flail becomes a siege engine. This is the weapon {name} loves most.",
        "{name}'s war flail moves with terrifying momentum promising broken bones and shattered shields. {name}'s true favorite.",
    ],
    "Battle Flail": [
        "{name}'s battle flail creates a whirlwind of steel and death. This is clearly {name}'s favored weapon.",
        "{name}'s battle flail defies prediction and defense. A monstrous weapon. {name}'s weapon of choice.",
        "{name}'s battle flail lashes out in every direction a storm of pain. The arena recognizes {name}'s favorite.",
        "With expert control {name}'s battle flail turns the air itself into a weapon. This is {name}'s true favorite.",
        "{name}'s battle flail moves like a living thing hungry for carnage. {name}'s bond with this flail is clear.",
    ],
    # Staves
    "Quarterstaff": [
        "{name}'s quarterstaff moves with fluid balanced precision. This is clearly {name}'s favored weapon.",
        "{name}'s quarterstaff strikes from both ends. A weapon of discipline and control. {name}'s weapon of choice.",
        "{name}'s quarterstaff dances through the air finding gaps in the defense. The pit knows this is {name}'s favorite.",
        "With practiced mastery {name}'s quarterstaff probes and strikes in perfect rhythm. This is the weapon {name} loves most.",
        "{name}'s quarterstaff moves like an extension of {name}'s will. {name}'s true favorite.",
    ],
    "Great Staff": [
        "{name}'s great staff swings with heavy sweeping power. This is clearly {name}'s favored weapon.",
        "{name}'s great staff demands space. A larger more imposing version of the quarterstaff. {name}'s weapon of choice.",
        "{name}'s great staff moves with deliberate crushing authority. The arena sees {name}'s favorite.",
        "With two handed strength {name}'s great staff becomes a battering ram of wood and will. This is {name}'s true favorite.",
        "{name}'s great staff strikes with the weight of ancient tradition behind it. {name}'s bond with this staff is obvious.",
    ],
    # Shields
    "Buckler": [
        "{name}'s buckler moves with quick defensive precision. This is clearly {name}'s favored weapon.",
        "{name}'s buckler darts to meet incoming blows. A small but nimble shield. {name}'s weapon of choice.",
        "{name}'s buckler snaps into position ready to deflect and counter. The pit knows this is {name}'s favorite.",
        "With practiced ease {name}'s buckler finds the perfect angle to turn the attack. This is the weapon {name} trusts most.",
        "{name}'s buckler moves like a second skin protecting and enabling at once. {name}'s true favorite.",
    ],
    "Target Shield": [
        "{name}'s target shield moves with solid reliable defense. This is clearly {name}'s favored weapon.",
        "{name}'s target shield catches blows with confidence. A well balanced shield. {name}'s weapon of choice.",
        "{name}'s target shield snaps forward absorbing impact and creating openings. The arena recognizes {name}'s favorite.",
        "With dwarven practicality {name}'s target shield does exactly what is needed. This is {name}'s true favorite.",
        "{name}'s target shield moves with the steady assurance of a proven defender. {name}'s bond with this shield is clear.",
    ],
    "Tower Shield": [
        "{name}'s tower shield moves like a moving wall imposing and unbreakable. This is clearly {name}'s favored weapon.",
        "{name}'s tower shield dares the enemy to strike. A massive barrier of steel. {name}'s weapon of choice.",
        "{name}'s tower shield advances with deliberate crushing presence. The pit knows this is {name}'s favorite.",
        "With half orc strength behind it {name}'s tower shield becomes an iron fortress. This is the weapon {name} loves most.",
        "{name}'s tower shield moves with the weight of certainty nothing will pass. {name}'s true favorite.",
    ],
    # Oddballs
    "Cestus": [
        "{name}'s cestus strikes with the fury of a bare fist given steel teeth. This is clearly {name}'s favored weapon.",
        "{name}'s cestus turns the hand into a mace. A brutal close range weapon. {name}'s weapon of choice.",
        "{name}'s cestus punches forward seeking to crush bone and pulp flesh. The arena sees {name}'s favorite.",
        "With martial precision {name}'s cestus finds the perfect striking surface. This is the weapon {name} trusts most.",
        "{name}'s cestus moves like an iron gauntlet given deadly purpose. {name}'s true favorite.",
    ],
    "Trident": [
        "{name}'s trident lunges forward with three deadly points seeking flesh. This is clearly {name}'s favored weapon.",
        "{name}'s trident strikes with fisher's precision. A weapon of the arena and the sea. {name}'s weapon of choice.",
        "{name}'s trident thrusts with the intent to pin and hold its prey. The pit knows this is {name}'s favorite.",
        "With practiced skill {name}'s trident finds the perfect angle for maximum damage. This is {name}'s true favorite.",
        "{name}'s trident moves like a predator's claw designed to impale and control. {name}'s bond with this trident is obvious.",
    ],
    "Net": [
        "{name}'s net whips through the air seeking to entangle and trap. This is clearly {name}'s favored weapon.",
        "{name}'s net dances with dangerous grace. A weapon of control and frustration. {name}'s weapon of choice.",
        "{name}'s net flies forward its weighted edges hungry for limbs and weapons. The crowd sees {name}'s favorite.",
        "With expert timing {name}'s net seeks to rob the opponent of mobility and options. This is the weapon {name} loves most.",
        "{name}'s net moves like a living thing looking to wrap and bind its target. {name}'s true favorite.",
    ],
    "Scythe": [
        "{name}'s scythe sweeps in a wide deadly arc promising harvest of flesh. This is clearly {name}'s favored weapon.",
        "{name}'s scythe reaps without mercy. A farmer's tool turned instrument of death. {name}'s weapon of choice.",
        "{name}'s scythe moves with graceful terrifying efficiency. The arena recognizes {name}'s favorite.",
        "With practiced sweeps {name}'s scythe seeks to open terrible wounds. This is {name}'s true favorite.",
        "{name}'s scythe cuts through the air like fate itself cold and inevitable. {name}'s bond with this scythe is clear.",
    ],
    "Great Pick": [
        "{name}'s great pick comes down like the mountain's own judgment. This is clearly {name}'s favored weapon.",
        "{name}'s great pick seeks to punch through anything. A weapon of pure penetration. {name}'s weapon of choice.",
        "{name}'s great pick strikes with the force of a siege engine. The pit knows this is {name}'s favorite.",
        "With devastating intent {name}'s great pick drives for the heart of the armor. This is the weapon {name} loves most.",
        "{name}'s great pick moves with unstoppable piercing purpose. {name}'s true favorite.",
    ],
    "Javelin": [
        "{name}'s javelin flies forward with hunting precision. This is clearly {name}'s favored weapon.",
        "{name}'s javelin cuts the air with deadly speed. A thrown spear seeking its mark. {name}'s weapon of choice.",
        "{name}'s javelin launches with the intent to impale and end the threat. The arena sees {name}'s favorite.",
        "With practiced form {name}'s javelin seeks a vital point from a distance. This is {name}'s true favorite.",
        "{name}'s javelin strikes like a bolt from the sky sudden and final. {name}'s bond with this javelin is obvious.",
    ],
    "Ball & Chain": [
        "{name}'s ball and chain swings in a heavy crushing arc. This is clearly {name}'s favored weapon.",
        "{name}'s ball and chain defies easy defense. A brutal and unpredictable weapon. {name}'s weapon of choice.",
        "{name}'s ball and chain comes down with devastating smashing force. The pit knows this is {name}'s favorite.",
        "With raw power {name}'s ball and chain seeks to break bone and spirit alike. This is the weapon {name} trusts most.",
        "{name}'s ball and chain moves like a falling anchor promising ruin on contact. {name}'s true favorite.",
    ],
    "Swordbreaker": [
        "{name}'s swordbreaker moves with the intent to catch and shatter steel. This is clearly {name}'s favored weapon.",
        "{name}'s swordbreaker waits for the perfect moment to trap a blade. A specialized weapon. {name}'s weapon of choice.",
        "{name}'s swordbreaker darts forward its notches hungry for enemy weapons. The crowd sees {name}'s favorite.",
        "With expert timing {name}'s swordbreaker seeks to disarm and destroy. This is {name}'s true favorite.",
        "{name}'s swordbreaker moves like a predator of other weapons waiting to bite. {name}'s bond with this weapon is clear.",
    ],
    "Bola": [
        "{name}'s bola whips through the air seeking to tangle and trip. This is clearly {name}'s favored weapon.",
        "{name}'s bola dances with dangerous intent. A weapon of control and frustration. {name}'s weapon of choice.",
        "{name}'s bola flies forward its weighted cords hungry for limbs. The pit knows this is {name}'s favorite.",
        "With practiced accuracy {name}'s bola seeks to rob the opponent of mobility. This is {name}'s true favorite.",
        "{name}'s bola moves like a living snare looking to wrap and bind its prey. {name}'s bond with this bola is obvious.",
    ],
    "Heavy Barbed Whip": [
        "{name}'s heavy barbed whip lashes out with cruel cutting intent. This is clearly {name}'s favored weapon.",
        "{name}'s barbed whip seeks to tear and yank. A weapon of pain and control. {name}'s weapon of choice.",
        "{name}'s heavy barbed whip cracks through the air promising agony on contact. The arena sees {name}'s favorite.",
        "With expert flicks {name}'s barbed whip finds exposed flesh and vulnerable limbs. This is the weapon {name} loves most.",
        "{name}'s barbed whip moves like a serpent with steel teeth hungry for blood. {name}'s true favorite.",
    ],
    "Open Hand": [
        "{name}'s open hand strikes with the precision of a martial artist. This is clearly {name}'s favored weapon.",
        "Empty handed but deadly. {name}'s open hand finds its target with practiced grace. {name}'s weapon of choice.",
        "{name}'s open hand moves with fluid controlled power. The pit knows this is {name}'s favorite.",
        "With disciplined focus {name}'s open hand seeks the perfect striking surface. This is {name}'s true favorite.",
        "{name}'s open hand strikes like a master's technique given lethal purpose. {name}'s bond with this style is obvious.",
    ],
}


# ---------------------------------------------------------------------------
# LOOKUP HELPERS
# ---------------------------------------------------------------------------

def get_weapon(name: str) -> Weapon:
    """
    Retrieve a Weapon by display name or skill_key (case-insensitive).
    Raises ValueError if not found.
    """
    # Try skill_key first
    key = name.lower().replace(" ", "_").replace("&", "and")
    if key in WEAPONS:
        return WEAPONS[key]

    # Try display name match
    for w in WEAPONS.values():
        if w.display.lower() == name.lower():
            return w

    valid = [w.display for w in WEAPONS.values()]
    raise ValueError(
        f"Unknown weapon: '{name}'.\n"
        f"Valid weapons: {', '.join(sorted(valid))}"
    )


def throwable_weapons() -> List[Weapon]:
    """Return all weapons that can be thrown."""
    return [w for w in WEAPONS.values() if w.throwable]


def mc_weapons() -> List[Weapon]:
    """Return all weapons compatible with Martial Combat style."""
    return [w for w in WEAPONS.values() if w.mc_compatible]


def armor_piercing_weapons() -> List[Weapon]:
    """Return all armor-piercing weapons (extra damage vs Scale+)."""
    return [w for w in WEAPONS.values() if w.armor_piercing]


def spear_weapons() -> List[Weapon]:
    """Return all weapons that can use the charge attack."""
    return [w for w in WEAPONS.values() if w.charge_attack]


def list_weapons_by_category(category: str) -> List[Weapon]:
    """Return all weapons in a given category."""
    return [w for w in WEAPONS.values() if w.category == category]


def weapons_for_style(style: str) -> List[Weapon]:
    """Return weapons that list a style as preferred."""
    return [w for w in WEAPONS.values() if style in w.preferred_styles]
