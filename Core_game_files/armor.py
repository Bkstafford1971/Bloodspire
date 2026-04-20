# =============================================================================
# armor.py — BLOODSPIRE Armor & Helm Definitions
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
    defense_value: APPROX — not given in the guide. Represents damage reduction.
                   Scale: 0 (none) to 10 (Full Plate). Each point reduces
                   incoming damage by a small flat amount in combat.
                   Values chosen so that armor is meaningful but not invincible.
    is_helm:       True for helms, False for body armor.
    ap_vulnerable: True if this armor is extra-vulnerable to armor-piercing
                   weapons (Scale, Chain, Half-Plate, Full Plate).
                   The guide says AP weapons do MORE damage vs these types.
                   APPROX: ap_vulnerable armor has its defense_value halved
                   when struck by an AP weapon.
    dex_penalty:   APPROX — how much this armor slows a warrior down.
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
        is_helm=False, ap_vulnerable=False, dex_penalty=1,
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
# The guide doesn't specify a separate armor-strength table — the weight
# column serves double duty.  A warrior can equip armor whose weight ≤
# their maximum weapon carry weight.
#
# APPROX: The guide says armor is "cumulative" (body + helm combined weight).
# We check body and helm independently against the STR table; a warrior who
# can carry 5 lbs of weapon can also wear 5 lbs of armor.
# This matches the sample warrior Burly Bob (Brigandine ~24 lbs, STR 17 → cap 6
# on weapon scale) — but we're scaling armor weight in actual lbs, not the
# 0-9 weapon point scale.  So we need a separate lbs→capacity table.

ARMOR_STR_TABLE = [
    # (str_lo, str_hi, max_armor_lbs)
    (3,  3,   0),
    (4,  6,  10),
    (7,  8,  14),
    (9,  11, 20),
    (12, 13, 27),
    (14, 16, 38),
    (17, 18, 50),
    (19, 21, 65),
    (22, 23, 72),
    (24, 25, 85),
]


def max_armor_weight(strength: int) -> float:
    """
    Return the maximum armor weight (in lbs) a warrior can comfortably wear
    based on their Strength.

    APPROX: Thresholds calibrated so that:
      - STR 17 (Burly Bob) can wear Brigandine (24 lbs) ✓
      - STR 9  (low warrior) tops out around Cuir Boulli (17 lbs) ✓
      - STR 22+ can wear Full Plate (80 lbs)
    """
    for lo, hi, capacity in ARMOR_STR_TABLE:
        if lo <= strength <= hi:
            return float(capacity)
    return 0.0


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
        return True, "No armor — always allowed."

    capacity = max_armor_weight(strength)
    piece_is_helm = piece.is_helm

    # Helms use their own simpler check — they're light enough that STR
    # is rarely the limiting factor. Full Helm (9 lbs) is accessible to STR 4+.
    # APPROX: Treat helm weight as equivalent to armor weight for capacity check.

    if piece.weight <= capacity:
        return True, f"STR {strength} supports {piece.name} ({piece.weight} lbs ≤ {capacity} lbs)."

    # Dwarf tier-up rule for body armor only
    if is_dwarf and not piece_is_helm:
        tiers = ARMOR_TIERS
        if piece.name in tiers:
            piece_idx  = tiers.index(piece.name)
            # Find the highest tier this warrior's STR normally allows
            max_tier_idx = -1
            for i, tier_name in enumerate(tiers):
                t = ARMOR_PIECES[tier_name]
                if t.weight <= capacity:
                    max_tier_idx = i
            # Dwarf can go ONE tier above their normal maximum
            if piece_idx <= max_tier_idx + 1:
                return True, (
                    f"Dwarf racial bonus allows one tier above STR limit. "
                    f"Equipping {piece.name}."
                )

    return False, (
        f"STR {strength} supports up to {capacity} lbs of armor. "
        f"{piece.name} weighs {piece.weight} lbs."
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

def get_effective_defense_for_race(
    armor_name: str,
    helm_name: str,
    race_name: str,
) -> int:
    """
    Get the total defense value, accounting for race-specific armor interactions.
    
    For Lizardfolk: natural scales (Scale armor equiv) + layering rules:
      - Cloth: no change, just normal defense
      - Leather: effective = Chain (6), but Lizardfolk only takes normal penalties
      - Cuir Boulli: effective = Half-Plate (8), but Lizardfolk only takes moderate penalties
      - Brigandine+: normal heavy armor with escalating penalties
    
    For other races: normal calculation.
    """
    if race_name != "Lizardfolk":
        return total_defense_value(armor_name, helm_name)
    
    # Lizardfolk with natural scales (equivalent to Scale armor: defense 5)
    armor = get_armor(armor_name or "None")
    helm  = get_armor(helm_name  or "None")
    
    base_defense = 5  # Scales = Scale armor equivalent
    helm_defense = helm.defense_value
    
    # Armor layering for Lizardfolk
    if armor_name in ("None", "Cloth"):
        # Cloth is just normal clothing, no bonus to scales defense
        armor_bonus = 0
    elif armor_name == "Leather":
        # Leather layered on scales = Chain equivalent (def 6)
        armor_bonus = 6 - base_defense  # +1 to scales
    elif armor_name == "Cuir Boulli":
        # Cuir Boulli on scales = Half-Plate equivalent (def 8)
        armor_bonus = 8 - base_defense  # +3 to scales
    else:
        # Brigandine and heavier: standard calculation on top of scales
        armor_bonus = armor.defense_value
    
    return base_defense + armor_bonus + helm_defense


def get_effective_dex_for_race(
    base_dex: int,
    armor_name: str,
    helm_name: str,
    race_name: str,
) -> int:
    """
    Get effective Dexterity after armor penalties, accounting for race-specific rules.
    
    For Lizardfolk: reduced DEX penalties for lighter armor:
      - Cloth: no penalty (from scales naturally)
      - Leather: -1 Dodge, -1 Initiative (lighter than Chain's -2)
      - Cuir Boulli: -2 Dodge, -2 Initiative (lighter than Half-Plate's -3)
      - Brigandine+: escalating penalties
    
    For other races: normal calculation.
    """
    if race_name != "Lizardfolk":
        return effective_dex(base_dex, armor_name, helm_name)
    
    armor = get_armor(armor_name or "None")
    helm  = get_armor(helm_name  or "None")
    
    # Lizardfolk start with no penalty (scales are native)
    armor_penalty = 0
    
    if armor_name in ("None", "Cloth"):
        armor_penalty = 0
    elif armor_name == "Leather":
        armor_penalty = 1  # Lighter than normal armor
    elif armor_name == "Cuir Boulli":
        armor_penalty = 2  # Moderate penalty (still lighter than Half-Plate's 3)
    else:
        # Brigandine and heavier: normal penalties
        armor_penalty = armor.dex_penalty
    
    helm_penalty = helm.dex_penalty
    total_penalty = armor_penalty + helm_penalty
    return max(1, base_dex - total_penalty)


def get_armor_attack_rate_penalty_for_race(
    armor_name: str,
    race_name: str,
) -> float:
    """
    Get the attack rate penalty for armor, accounting for race-specific rules.
    
    For Lizardfolk: reduced penalties for lighter armor:
      - Cloth: 0
      - Leather: -0.5 (lighter than Chain's -1.5)
      - Cuir Boulli: -1.5 (lighter than Half-Plate's -2.5)
      - Brigandine+: escalating penalties
    
    For other races: 0 (handled separately in combat.py)
    """
    if race_name != "Lizardfolk":
        return 0.0
    
    if armor_name in ("None", "Cloth"):
        return 0.0
    elif armor_name == "Leather":
        return 0.5
    elif armor_name == "Cuir Boulli":
        return 1.5
    elif armor_name == "Brigandine":
        return 2.5
    elif armor_name == "Scale":
        return 3.5
    elif armor_name == "Chain":
        return 4.0
    elif armor_name == "Half-Plate":
        return 5.5
    else:  # Full Plate
        return 6.5
    
    return 0.0
