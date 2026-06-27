# =============================================================================
# armor.py - BLOODSPIRE Armor & Helm Definitions
# =============================================================================
# Contains:
#   - Armor and helm dataclasses
#   - Strength-based carry capacity (shared with weapons.py logic)
#   - Dwarf rule: can equip one tier above what their STR allows
#   - Defense value approximations (APPROX: guide gives no explicit numbers)
#   - Dexterity fumble calculation (high DEX mitigates armor speed penalty)
# =============================================================================

from dataclasses import dataclass
from typing import List, Optional
from weapons import max_weapon_weight   # Reuse the same STR→capacity table


# ---------------------------------------------------------------------------
# ARMOR DATACLASS
# ---------------------------------------------------------------------------

@dataclass
class ArmorPiece:
    """
    Represents a single armor or helm option.

    name:          Display name as seen in fight headers.
    weight:        From the guide's armor table. Compared against STR capacity.
    defense_value: APPROX - not given in the guide. Represents damage reduction.
                   Scale: 0 (none) to 10 (Full Plate). Each point reduces
                   incoming damage by a small flat amount in combat.
                   Values chosen so that armor is meaningful but not invincible.
    is_helm:       True for helms, False for body armor.
    ap_vulnerable: True if this armor is extra-vulnerable to armor-piercing
                   weapons (Scale, Chain, Half-Plate, Full Plate).
                   The guide says AP weapons do MORE damage vs these types.
                   APPROX: ap_vulnerable armor has its defense_value halved
                   when struck by an AP weapon.
    dex_penalty:   APPROX - how much this armor slows a warrior down.
                   Subtracted from effective Dexterity for dodge/initiative
                   purposes (before racial and skill modifiers).
                   Range 0-5. Cloth=0, Full Plate=5.
    notes:         Flavor text from guide or derived analysis.
    """

    name          : str
    weight        : float
    defense_value : int
    is_helm       : bool
    ap_vulnerable : bool
    dex_penalty   : int
    notes         : str = ""

    def __str__(self) -> str:
        kind = "Helm" if self.is_helm else "Armor"
        ap_flag = " [AP-vuln]" if self.ap_vulnerable else ""
        return f"{self.name} ({kind}, wt:{self.weight}, def:{self.defense_value}){ap_flag}"


# ---------------------------------------------------------------------------
# ARMOR TABLE
# From the player's guide weight chart, verbatim.
# Defense values and dex penalties are APPROX (documented below).
#
# APPROX rationale for defense_value:
#   The guide makes clear armor matters but gives no numbers. We use a
#   linear-ish scale where each tier meaningfully reduces damage, but a
#   skilled warrior with a good weapon still gets through.
#   Full Plate (def 10) reduces each hit by ~8-10 points on a ~75-HP warrior,
#   meaning even the best armor won't make someone unkillable.
#
# APPROX rationale for dex_penalty:
#   Guide says: "Armor slows a warrior down and minimizes benefits of Dexterity."
#   Also: "a high Dexterity warrior can wear armor, be as speedy as his naturally
#   slower opponent, and have better protection to boot."
#   We model this as a flat DEX subtraction for dodge/initiative only,
#   not for attack or parry.
# ---------------------------------------------------------------------------

ARMOR_PIECES: dict[str, ArmorPiece] = {

    # ---- BODY ARMOR ----

    "Cloth": ArmorPiece(
        name="Cloth", weight=8.0, defense_value=1,
        is_helm=False, ap_vulnerable=False, dex_penalty=0,
        notes="Minimal protection. Starting armor for poor or fast warriors.",
    ),
    "Leather": ArmorPiece(
        name="Leather", weight=12.0, defense_value=2,
        is_helm=False, ap_vulnerable=False, dex_penalty=0,
        notes="Light and flexible. Small weapons hit through it easily.",
    ),
    "Cuir Boulli": ArmorPiece(
        name="Cuir Boulli", weight=17.0, defense_value=3,
        is_helm=False, ap_vulnerable=False, dex_penalty=0,
        notes="Hardened boiled leather. Popular mid-tier choice.",
    ),
    "Brigandine": ArmorPiece(
        name="Brigandine", weight=24.0, defense_value=4,
        is_helm=False, ap_vulnerable=False, dex_penalty=1,
        notes="Small metal plates sewn into leather. Solid defensive choice.",
    ),
    "Scale": ArmorPiece(
        name="Scale", weight=35.0, defense_value=5,
        is_helm=False, ap_vulnerable=True, dex_penalty=2,
        notes=(
            "Where AP weapons start to shine against the wearer. "
            "Noticeably slows the warrior."
        ),
    ),
    "Chain": ArmorPiece(
        name="Chain", weight=44.0, defense_value=6,
        is_helm=False, ap_vulnerable=True, dex_penalty=2,
        notes="Classic heavy armor. AP weapons can find the gaps.",
    ),
    "Half-Plate": ArmorPiece(
        name="Half-Plate", weight=63.0, defense_value=8,
        is_helm=False, ap_vulnerable=True, dex_penalty=3,
        notes="Excellent protection but significantly impairs mobility.",
    ),
    "Full Plate": ArmorPiece(
        name="Full Plate", weight=80.0, defense_value=10,
        is_helm=False, ap_vulnerable=True, dex_penalty=5,
        notes=(
            "Maximum protection. Only the strongest warriors can wear this "
            "without becoming sitting ducks."
        ),
    ),

    # ---- HELMS ----

    "Leather Cap": ArmorPiece(
        name="Leather Cap", weight=1.0, defense_value=1,
        is_helm=True, ap_vulnerable=False, dex_penalty=0,
        notes="Minimal head protection. Better than nothing.",
    ),
    "Steel Cap": ArmorPiece(
        name="Steel Cap", weight=3.0, defense_value=2,
        is_helm=True, ap_vulnerable=False, dex_penalty=0,
        notes="Light and practical. Most warriors' default choice.",
    ),
    "Helm": ArmorPiece(
        name="Helm", weight=5.0, defense_value=3,
        is_helm=True, ap_vulnerable=False, dex_penalty=1,
        notes="Full metal helmet with visor.",
    ),
    "Camail": ArmorPiece(
        name="Camail", weight=7.0, defense_value=4,
        is_helm=True, ap_vulnerable=False, dex_penalty=1,
        notes="Helm with chain skirt protecting neck and shoulders.",
    ),
    "Full Helm": ArmorPiece(
        name="Full Helm", weight=9.0, defense_value=5,
        is_helm=True, ap_vulnerable=True, dex_penalty=2,
        notes="Complete head enclosure. High defense; some peripheral vision lost.",
    ),
    "None": ArmorPiece(
        name="None", weight=0.0, defense_value=0,
        is_helm=False, ap_vulnerable=False, dex_penalty=0,
        notes="No armor equipped.",
    ),
}

# Ordered lists for display/selection (lightest to heaviest)
ARMOR_TIERS: List[str] = [
    "Cloth", "Leather", "Cuir Boulli", "Brigandine",
    "Scale", "Chain", "Half-Plate", "Full Plate",
]
HELM_TIERS: List[str] = [
    "Leather Cap", "Steel Cap", "Helm", "Camail", "Full Helm",
]


# ---------------------------------------------------------------------------
# LOOKUP HELPERS
# ---------------------------------------------------------------------------

def get_armor(name: str) -> ArmorPiece:
    """
    Retrieve an ArmorPiece by name (case-insensitive).
    Accepts 'None' or empty string to return the null armor piece.
    """
    if not name or name.lower() == "none":
        return ARMOR_PIECES["None"]
    for key, piece in ARMOR_PIECES.items():
        if key.lower() == name.lower():
            return piece
    valid = ", ".join(k for k in ARMOR_PIECES if k != "None")
    raise ValueError(f"Unknown armor/helm: '{name}'. Valid options: {valid}")


# ---------------------------------------------------------------------------
# STRENGTH REQUIREMENT LOGIC FOR ARMOR
# ---------------------------------------------------------------------------

# Armor uses the SAME carry-weight table as weapons.
# The guide doesn't specify a separate armor-strength table - the weight
# column serves double duty.  A warrior can equip armor whose weight ≤
# their maximum weapon carry weight.
#
# APPROX: The guide says armor is "cumulative" (body + helm combined weight).
# We check body and helm independently against the STR table; a warrior who
# can carry 5 lbs of weapon can also wear 5 lbs of armor.
# This matches the sample warrior Burly Bob (Brigandine ~24 lbs, STR 17 → cap 6
# on weapon scale) - but we're scaling armor weight in actual lbs, not the
# 0-9 weapon point scale.  So we need a separate lbs→capacity table.

# Direct Strength-to-Weight mapping to ensure every point of STR matters.
ARMOR_STR_CAPACITY: dict[int, float] = {
    3:  0.0,
    4:  10.0,
    5:  11.5,
    6:  13.0,
    7:  15.0,
    8:  18.0,
    9:  21.0,
    10: 23.5,
    11: 26.0,
    12: 29.0,
    13: 33.0,
    14: 38.0,
    15: 41.5,
    16: 45.0,
    17: 50.0,
    18: 56.0,
    19: 65.0,
    20: 68.5,
    21: 72.0,
    22: 76.0,
    23: 80.0,
    24: 84.0,
    25: 88.0,
}


def max_armor_weight(strength: int) -> float:
    """
    Return the maximum armor weight (in lbs) a warrior can comfortably wear
    based on their Strength.

    APPROX: Thresholds calibrated so that:
      - STR 17 (Burly Bob) can wear Brigandine (24 lbs) ✓
      - STR 9  (low warrior) tops out around Cuir Boulli (17 lbs) ✓
      - STR 22+ can wear Full Plate (80 lbs)
    """
    # Clamp strength between 3 and 25 for lookup
    effective_str = max(3, min(25, strength))
    return float(ARMOR_STR_CAPACITY.get(effective_str, 0.0))


def armor_penalty_factor(weight: float, strength: int, is_dwarf: bool = False, piece_is_helm: bool = False) -> float:
    """
    Calculate the under-strength armor penalty fraction (0.0 = no penalty, 1.0 = unusable).

    Dwarf rule: can equip one body armor tier above what their STR normally allows
    without penalty.
    """
    capacity = max_armor_weight(strength)

    # Check if within normal capacity
    if weight <= capacity:
        return 0.0

    # Dwarf racial bonus: effectively higher capacity for body armor tiers
    if is_dwarf and not piece_is_helm:
        # Find the highest tier allowed by normal capacity
        max_tier_idx = -1
        for i, tier_name in enumerate(ARMOR_TIERS):
            if ARMOR_PIECES[tier_name].weight <= capacity:
                max_tier_idx = i

        # If this piece is within one tier of the normal limit, no penalty
        target_tier_idx = min(len(ARMOR_TIERS)-1, max_tier_idx + 1)
        if weight <= ARMOR_PIECES[ARMOR_TIERS[target_tier_idx]].weight:
            return 0.0

    if capacity <= 0:
        return 1.0
    overage = weight - capacity
    return min(1.0, overage / capacity)


def can_wear_armor(
    armor_name: str,
    strength: int,
    is_dwarf: bool = False,
) -> tuple[bool, str]:
    """
    Check whether a warrior can wear a given armor piece.

    Dwarf rule (from player answers):
      Dwarves can equip one tier above what their STR normally allows.
      E.g. if STR allows Chain (44 lbs) as the max, a Dwarf can wear Half-Plate (63 lbs).

    Returns:
        (allowed: bool, reason: str)
    """
    piece = get_armor(armor_name)
    if piece.name == "None":
        return True, "No armor - always allowed."

    penalty = armor_penalty_factor(piece.weight, strength, is_dwarf, piece.is_helm)
    capacity = max_armor_weight(strength)

    if penalty == 0.0:
        if piece.weight <= capacity:
            return True, f"STR {strength} supports {piece.name} ({piece.weight} lbs ≤ {capacity} lbs)."
        else:
            return True, f"Dwarf racial bonus allows {piece.name} without penalty."

    if penalty < 1.0:
        # We allow equipping with a penalty warning
        return True, f"STR {strength} is under-strength for {piece.name} (Penalty: {int(penalty*100)}%)"

    return False, (
        f"STR {strength} cannot support {piece.name}. "
        f"Weight {piece.weight} lbs is too far beyond capacity {capacity} lbs."
    )


def effective_dex(base_dex: int, armor_name: str, helm_name: str) -> int:
    """
    Return effective Dexterity after armor and helm dex penalties are applied.
    Used by the combat engine for dodge and initiative calculations.
    Minimum effective DEX is 1 (can't be penalized below 1).
    """
    armor = get_armor(armor_name or "None")
    helm  = get_armor(helm_name  or "None")
    total_penalty = armor.dex_penalty + helm.dex_penalty
    return max(1, base_dex - total_penalty)


def total_defense_value(armor_name: str, helm_name: str) -> int:
    """
    Sum of armor + helm defense values.
    Used as input to the damage reduction calculation in combat.
    """
    armor = get_armor(armor_name or "None")
    helm  = get_armor(helm_name  or "None")
    return armor.defense_value + helm.defense_value


def is_ap_vulnerable(armor_name: str) -> bool:
    """True if the body armor is vulnerable to armor-piercing weapons."""
    armor = get_armor(armor_name or "None")
    return armor.ap_vulnerable


def armor_selection_menu() -> List[str]:
    """Return ordered list of body armor names for display in menus."""
    return ARMOR_TIERS[:]


def helm_selection_menu() -> List[str]:
    """Return ordered list of helm names for display in menus."""
    return HELM_TIERS[:]


# ---------------------------------------------------------------------------
# RACE-SPECIFIC ARMOR MODIFIERS
# ---------------------------------------------------------------------------

# Races that have natural armor (scales, hide, etc.).
# Adding a race here automatically enables natural-armor layering rules
# in get_effective_defense_for_race and get_effective_dex_for_race.
_NATURAL_ARMOR_RACES: frozenset = frozenset({"Lizardfolk"})


# Lizardfolk armor penalty table.
# Natural scales = Scale armor equivalent (defense 5). Cloth and Leather can
# be layered on top; anything heavier gives no additional protection but still
# imposes severe mobility penalties - these are NOT designed for scale-armored
# reptilian bodies.
#
# Columns: (dex_pen, dodge_parry_pct, initiative_pct, attack_pct)
#   dex_pen:         flat dexterity reduction (cloth/leather only; affects dodge + initiative dex component)
#   dodge_parry_pct: multiplier penalty on the computed dodge/parry roll total (cuir boulli+)
#   initiative_pct:  multiplier penalty on the computed initiative roll total (all armors)
#   attack_pct:      multiplier penalty on base APM before rounding (cuir boulli+)
_LIZARD_PENALTIES: dict[str, tuple] = {
    "None":        (0, 0.00, 0.00, 0.00),
    "Cloth":       (1, 0.00, 0.02, 0.00),
    "Leather":     (2, 0.00, 0.03, 0.00),
    "Cuir Boulli": (0, 0.05, 0.08, 0.05),
    "Brigandine":  (0, 0.10, 0.15, 0.00),
    "Scale":       (0, 0.15, 0.20, 0.10),
    "Chain":       (0, 0.20, 0.30, 0.15),
    "Half-Plate":  (0, 0.25, 0.35, 0.20),
    "Full Plate":  (0, 0.35, 0.45, 0.25),
}


def get_lizardfolk_armor_penalties(armor_name: str) -> dict:
    """Return all Lizardfolk-specific armor penalties for the given armor.

    Keys: dex_pen (int), dodge_parry_pct (float), initiative_pct (float), attack_pct (float)
    """
    row = _LIZARD_PENALTIES.get(armor_name or "None", _LIZARD_PENALTIES["None"])
    return {
        "dex_pen":         row[0],
        "dodge_parry_pct": row[1],
        "initiative_pct":  row[2],
        "attack_pct":      row[3],
    }


def get_effective_defense_for_race(
    armor_name: str,
    helm_name: str,
    race_name: str,
) -> int:
    """
    Get the total defense value, accounting for race-specific armor interactions.

    For Lizardfolk: natural scales (defense 5) + layering cap:
      - No armor: 5 (scales only)
      - Cloth:    6 (cloth over scales)
      - Leather:  7 (natural + leather = maximum useful layering)
      - Cuir Boulli and heavier: CAPPED at 7 - the armor provides no additional
        protection because it cannot conform to Lizardfolk scale geometry;
        they still suffer all the heavy-armor mobility penalties.
    Helm defense always stacks normally on top.

    For other races: normal calculation.
    """
    if race_name not in _NATURAL_ARMOR_RACES:
        return total_defense_value(armor_name, helm_name)

    helm = get_armor(helm_name or "None")
    helm_defense = helm.defense_value

    NATURAL_SCALES = 5  # inherent scale armor equivalent

    if not armor_name or armor_name == "None":
        body_defense = NATURAL_SCALES
    elif armor_name == "Cloth":
        body_defense = NATURAL_SCALES + 1   # = 6
    elif armor_name == "Leather":
        body_defense = NATURAL_SCALES + 2   # = 7
    else:
        # Cuir Boulli and heavier: no benefit beyond natural + leather
        body_defense = NATURAL_SCALES + 2   # = 7 cap

    return body_defense + helm_defense


def get_effective_dex_for_race(
    base_dex: int,
    armor_name: str,
    helm_name: str,
    race_name: str,
) -> int:
    """
    Get effective Dexterity after armor penalties, accounting for race-specific rules.

    For Lizardfolk: dex_pen applies only for cloth (-1) and leather (-2).
    Heavier armors use percentage-based roll penalties instead of dex reduction
    (see get_lizardfolk_armor_penalties); their dex_pen is 0 here.

    For other races: normal calculation.
    """
    if race_name not in _NATURAL_ARMOR_RACES:
        return effective_dex(base_dex, armor_name, helm_name)

    helm = get_armor(helm_name or "None")
    pens = get_lizardfolk_armor_penalties(armor_name or "None")
    total_penalty = pens["dex_pen"] + helm.dex_penalty
    return max(1, base_dex - total_penalty)


def get_armor_attack_rate_penalty_for_race(
    armor_name: str,
    race_name: str,
) -> float:
    """
    Legacy function - returns 0 for all races.
    Lizardfolk attack-rate penalties are now handled via get_lizardfolk_armor_penalties()
    and applied as a percentage multiplier in _calc_apm().
    """
    return 0.0
