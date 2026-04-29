# =============================================================================
# ai.py — BLOODSPIRE AI Helpers
# =============================================================================
# Provides gear, strategy, and training assignment for AI-managed warriors.
# =============================================================================

import random
from typing import List, Dict

from warrior  import Warrior, Strategy, ATTRIBUTES
from weapons  import get_weapon
from armor    import ARMOR_TIERS, HELM_TIERS, can_wear_armor


# ---------------------------------------------------------------------------
# RACE → PREFERRED WEAPON (for AI gear assignment)
# Derived from weapon guide notes and race descriptions.
# ---------------------------------------------------------------------------

RACE_WEAPON_PREFS: Dict[str, List[str]] = {
    "Human"   : ["Short Sword", "Military Pick", "Morningstar", "Boar Spear", "War Hammer"],
    "Half-Orc": ["War Flail", "Great Axe", "Great Sword", "War Hammer", "Great Pick"],
    "Halfling": ["Short Sword", "Hatchet", "Stiletto", "Javelin", "Bladed Flail"],
    "Dwarf"   : ["Battle Axe", "Morningstar", "War Hammer", "Boar Spear", "Target Shield"],
    "Half-Elf": ["Pole Axe", "Bastard Sword", "Battle Flail", "Long Sword", "Scythe"],
    "Elf"     : ["Short Sword", "Scimitar", "Scythe", "Dagger", "Javelin"],
    "Peasant" : ["Short Sword", "Boar Spear", "War Flail", "Morningstar"],
}

RACE_SECONDARY_PREFS: Dict[str, List[str]] = {
    "Human"   : ["Buckler", "Target Shield", "Open Hand"],
    "Half-Orc": ["Open Hand", "Tower Shield", "War Flail"],
    "Halfling": ["Buckler", "Open Hand", "Stiletto"],
    "Dwarf"   : ["Target Shield", "Tower Shield", "Buckler"],
    "Half-Elf": ["Open Hand", "Buckler"],
    "Elf"     : ["Open Hand", "Short Sword", "Dagger"],
    "Peasant" : ["Open Hand", "Buckler"],
}

# Race → best styles
RACE_STYLE_PREFS: Dict[str, List[str]] = {
    "Human"   : ["Strike", "Counterstrike", "Calculated Attack", "Sure Strike"],
    "Half-Orc": ["Total Kill", "Bash", "Strike", "Wall of Steel"],
    "Halfling": ["Lunge", "Engage & Withdraw", "Wall of Steel", "Martial Combat"],
    "Dwarf"   : ["Counterstrike", "Bash", "Parry", "Wall of Steel"],
    "Half-Elf": ["Slash", "Strike", "Lunge", "Wall of Steel"],
    "Elf"     : ["Wall of Steel", "Lunge", "Engage & Withdraw", "Slash"],
    "Peasant" : ["Strike", "Total Kill"],
}


# ---------------------------------------------------------------------------
# AI GEAR ASSIGNMENT
# ---------------------------------------------------------------------------

def assign_ai_gear(warrior: Warrior, tier: int = 1):
    """
    Equip an AI warrior with appropriate gear for their race and stats.
    tier 1 = new warrior (light gear)
    tier 5 = veteran (heavy gear)
    """
    race  = warrior.race.name
    is_dw = (race == "Dwarf")

    # --- Primary weapon ---
    prefs = RACE_WEAPON_PREFS.get(race, RACE_WEAPON_PREFS["Human"])
    primary = _best_wieldable_weapon(warrior, prefs)
    warrior.primary_weapon = primary

    # --- Secondary weapon ---
    sec_prefs = RACE_SECONDARY_PREFS.get(race, ["Open Hand"])
    secondary = _best_wieldable_weapon(warrior, sec_prefs, allow_open_hand=True)
    # If primary is two-handed, secondary must be open hand
    try:
        pw = get_weapon(primary)
        if pw.two_hand:
            secondary = "Open Hand"
    except ValueError:
        pass
    warrior.secondary_weapon = secondary

    # --- Armor (scale with tier) ---
    tier_idx     = min(tier - 1, len(ARMOR_TIERS) - 1)
    armor_choice = None
    for i in range(tier_idx, -1, -1):
        candidate = ARMOR_TIERS[i]
        allowed, _ = can_wear_armor(candidate, warrior.strength, is_dw)
        if allowed:
            armor_choice = candidate
            break
    warrior.armor = armor_choice or "Cloth"

    # --- Helm ---
    helm_tier_idx = min(tier - 1, len(HELM_TIERS) - 1)
    warrior.helm  = HELM_TIERS[helm_tier_idx]


def _best_wieldable_weapon(
    warrior: Warrior,
    prefs: List[str],
    allow_open_hand: bool = False,
) -> str:
    """
    From a preference list, return the first weapon the warrior can wield
    without a full penalty. Falls back to Open Hand.
    """
    from weapons import max_weapon_weight, strength_penalty
    for wpn_name in prefs:
        try:
            w = get_weapon(wpn_name)
            pen = strength_penalty(w.weight, warrior.strength, w.two_hand)
            if pen < 0.30:   # Allow up to 30% penalty — still functional
                return wpn_name
        except ValueError:
            continue
    return "Open Hand"


# ---------------------------------------------------------------------------
# AI STRATEGY ASSIGNMENT
# ---------------------------------------------------------------------------

def assign_ai_strategies(warrior: Warrior, tier: int = 1):
    """
    Assign a sensible strategy set based on race, weapon, and tier.
    Lower tier = simpler (fewer strategies).
    Higher tier = more complex (up to 6 strategies with nuanced triggers).
    """
    race     = warrior.race.name
    styles   = RACE_STYLE_PREFS.get(race, ["Strike", "Counterstrike"])
    main_style  = styles[0]
    backup_style= styles[1] if len(styles) > 1 else "Parry"

    strategies = []

    if tier >= 3:
        # Add a heavy damage trigger
        strategies.append(Strategy(
            trigger       = "You have taken heavy damage",
            style         = "Parry",
            activity      = 3,
            aim_point     = "None",
            defense_point = "Chest",
        ))

    if tier >= 2:
        # Add a foe-on-ground trigger
        strategies.append(Strategy(
            trigger       = "Your foe is on the ground",
            style         = main_style,
            activity      = min(9, 6 + tier),
            aim_point     = "Head",
            defense_point = "None",
        ))

    if tier >= 4:
        # Add a tired trigger
        strategies.append(Strategy(
            trigger       = "You are tired",
            style         = backup_style,
            activity      = 4,
            aim_point     = "None",
            defense_point = "Chest",
        ))

    # Always-on default strategy
    # Activity: lower tiers are less aggressive
    base_activity = min(9, 4 + tier)
    strategies.append(Strategy(
        trigger       = "Always",
        style         = main_style,
        activity      = base_activity,
        aim_point     = random.choice(["Head", "Chest", "None"]),
        defense_point = "Chest",
    ))

    warrior.strategies = strategies


# ---------------------------------------------------------------------------
# AI TRAINING SELECTION
# ---------------------------------------------------------------------------

def assign_ai_training(warrior: Warrior, tier: int = 1):
    """
    Choose up to 3 training targets for this warrior.
    Higher tier warriors invest in advanced skills.
    """
    race       = warrior.race.name
    weapon_key = warrior.primary_weapon.lower().replace(" ", "_").replace("&","and")
    trains     = []

    if tier == 1:
        # Beginners: train their primary weapon + constitution
        trains = [weapon_key, "constitution", weapon_key]
    elif tier == 2:
        trains = [weapon_key, weapon_key, "dodge"]
    elif tier == 3:
        trains = [weapon_key, "parry", "initiative"]
    elif tier == 4:
        trains = [weapon_key, "dodge", "parry"]
    else:
        # Veteran: advanced skills
        skill_pool = ["dodge", "parry", "initiative", "lunge", "feint", weapon_key]
        trains     = random.sample(skill_pool, min(3, len(skill_pool)))

    warrior.trains = trains[:3]
