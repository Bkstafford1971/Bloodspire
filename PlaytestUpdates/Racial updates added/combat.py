# =============================================================================
# combat.py, BLOODSPIRE Combat Engine v2
# =============================================================================
# CORE MECHANICS:
#   All rolls: d100 (1-100).
#   Every warrior has a permanent luck factor (1-30) added to every roll.
#
# INITIATIVE (per-action within each minute):
#   Before each action slot, both warriors roll initiative.
#   d100 + DEX_bonus + initiative_skill + luck + style_mod + activity_mod.
#   Higher roll = attacker for that slot.
#
# ATTACK vs DEFENSE:
#   Attacker: d100 + DEX + weapon_skill*5 + luck + style_mod
#   Defender: d100 + (STR/DEX) + parry/dodge_skill*4 + weapon_skill*3 + luck
#   margin = attack_roll - defense_roll
#     margin <= 0:     miss / parry / dodge
#     margin  1-9:     graze (3 HP, no other effects)
#     margin >= 10:    hit (damage = ceiling * (margin/80))
#
# DAMAGE (HYBRID):
#   Ceiling  = f(STR, weapon weight, race, skills, style, luck)
#   Fraction = min(1.0, margin / 80.0)
#   Net      = max(1, int(ceiling * fraction) - armor)
#
# CONCEDE SYSTEM:
#   Triggered at <=25% HP. d100 + PRE_bonus + luck//2 vs threshold.
#   Presence determines how often the Pitmaster grants mercy.
#   Monster fights: no concede, always to the death.
#
# DEATH CHECK:
#   overshoot = max(0, -new_hp)
#   death_chance = 0.5% + overshoot% (capped 50%)
#
# NO DRAWS: 30-minute limit -> judge awards decision to higher HP% warrior.
# =============================================================================

from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

from combat_debug_logger import CombatDebugLogger

from warrior  import Warrior, Strategy, ATTRIBUTES
from strategy import (
    FighterState, evaluate_triggers, get_style_advantage,
    get_style_props, AGGRESSIVE_STYLES as _AGGRESSIVE_STYLES,
)

# Gnome tactician_edge — opponents using these styles trigger the bonus/penalty.
_TACTICIAN_FAVORED    = frozenset({
    "Total Kill", "Wall of Steel", "Lunge", "Bash", "Slash", "Strike", "Martial Combat",
})
_TACTICIAN_DISFAVORED = frozenset({
    "Parry", "Defend", "Sure Strike", "Calculated Attack", "Counterstrike", "Engage & Withdraw",
})
from weapons  import get_weapon, strength_penalty, OPEN_HAND, Weapon, get_effective_strength_for_weapons, min_str_for_weight
from armor    import (
    effective_dex, total_defense_value, is_ap_vulnerable,
    get_effective_dex_for_race, get_effective_defense_for_race,
    armor_penalty_factor, get_armor,
    get_lizardfolk_armor_penalties,
    ARMOR_PIECES,
)
import narrative as N


# =============================================================================
# FEATURE FLAGS & GLOBALS
# =============================================================================

# Global flags: control debug/test visibility of hidden mechanics
# These can be toggled via the admin panel for testing purposes
SHOW_FAVORITE_WEAPON = False  # Show favorite weapon flavor text in fight narratives
SHOW_LUCK_FACTOR = False      # Show lucky rolls in fight narratives
SHOW_MAX_HP = False           # Show warrior max HP at fight start

# Finesse precision bypass tuning knobs
# These are used to compute how much armor a finesse hit can bypass based
# on attacker Dexterity, Intelligence, and weapon skill. These defaults
# reflect the conservative tuning validated by simulation.
FINESSE_DEX_MULT = 0.035
FINESSE_INT_MULT = 0.015
FINESSE_SKILL_MULT = 0.015
FINESSE_BYPASS_CAP = 0.45

def set_show_favorite_weapon(enabled: bool):
    """Update the feature flag for showing favorite weapon flavor text."""
    global SHOW_FAVORITE_WEAPON
    SHOW_FAVORITE_WEAPON = enabled

def set_show_luck_factor(enabled: bool):
    """Update the feature flag for showing luck factor rolls."""
    global SHOW_LUCK_FACTOR
    SHOW_LUCK_FACTOR = enabled

def set_show_max_hp(enabled: bool):
    """Update the feature flag for showing max HP."""
    global SHOW_MAX_HP
    SHOW_MAX_HP = enabled


# ---------------------------------------------------------------------------
# WEAPON CATEGORIZATION FOR NEW SKILLS
# ---------------------------------------------------------------------------

CLEAVE_WEAPONS = {
    "great_sword", "halberd", "great_axe", "battle_axe", "pole_axe",
    "bastard_sword", "scimitar", "scythe", "pick_axe"
}

BASH_WEAPONS = {
    "ball_and_chain", "club", "great_pick", "military_pick", "great_staff",
    "great_sword", "halberd", "hammer", "mace", "maul", "morningstar",
    "quarterstaff", "target_shield", "tower_shield", "war_hammer"
}

SLASH_WEAPONS = {
    "short_sword", "longsword", "broad_sword", "bastard_sword", "battle_axe",
    "great_axe", "hatchet", "francisca", "dagger", "epee", "knife",
    "scimitar", "scythe", "swordbreaker"
}

OPEN_HAND_WEAPONS = {
    "open_hand"
}

FINESSE_WEAPONS = {
    "stiletto", "knife", "dagger", "short_sword", "epee", "scimitar",
    "hatchet", "francisca", "hammer", "short_spear", "flail",
    "cestus", "javelin", "swordbreaker", "bola"
}

VERSATILE_WEAPONS = {
    "bastard_sword", "short_spear", "boar_spear", "javelin",
    "military_pick", "club", "trident"
}

# Weapons that use finesse/precision damage calculation (small weapon skill bonus)
FINESSE_DAMAGE_WEAPONS = {
    "stiletto", "cestus", "knife", "dagger", "epee"
}


def _is_cleave_weapon(weapon_key: str) -> bool:
    """Check if weapon qualifies for Cleave skill bonuses."""
    return weapon_key in CLEAVE_WEAPONS


def _is_bash_weapon(weapon_key: str) -> bool:
    """Check if weapon qualifies for Bash skill bonuses."""
    return weapon_key in BASH_WEAPONS


def _is_slash_weapon(weapon_key: str) -> bool:
    """Check if weapon qualifies for Slash skill bonuses."""
    return weapon_key in SLASH_WEAPONS


def _is_open_hand_weapon(weapon_key: str) -> bool:
    """Check if weapon qualifies for Open Hand skill bonuses."""
    return weapon_key in OPEN_HAND_WEAPONS


def _is_finesse_weapon(weapon_key: str) -> bool:
    """Check if weapon qualifies as a finesse weapon for dual-wielding bonuses."""
    return weapon_key in FINESSE_WEAPONS


def _is_versatile_two_handed(weapon_key: str, attacker: "Warrior") -> bool:
    """Check if weapon is versatile and being used two-handed (secondary=Open Hand)."""
    if weapon_key not in VERSATILE_WEAPONS:
        return False
    # Versatile weapons get 1.15x bonus when secondary is Open Hand (two-handed use)
    return attacker.secondary_weapon == "Open Hand"


def _is_elf_dual_wielding_finesse(attacker: Warrior) -> bool:
    """Check if an Elf is wielding two finesse weapons (dual-wielding)."""
    if attacker.race.name != "Elf":
        return False
    if not attacker.race.modifiers.dual_weapon_bonus:
        return False

    # Both primary and secondary must be weapons (not shields or Open Hand)
    if not attacker.primary_weapon or not attacker.secondary_weapon:
        return False

    # Both must be finesse weapons
    primary_key = attacker.primary_weapon.lower().replace(" ", "_").replace("&", "and")
    secondary_key = attacker.secondary_weapon.lower().replace(" ", "_").replace("&", "and")

    if not _is_finesse_weapon(primary_key):
        return False
    if not _is_finesse_weapon(secondary_key):
        return False

    # Neither can be a shield
    try:
        primary_wpn = get_weapon(attacker.primary_weapon)
        secondary_wpn = get_weapon(attacker.secondary_weapon)
        if primary_wpn.is_shield or secondary_wpn.is_shield:
            return False
    except ValueError:
        return False

    return True


def _calculate_elf_extra_attack_chance(attacker: Warrior, defender: Warrior = None) -> int:
    """
    Calculate the percentage chance (0-100) for an Elf extra attack from dual-wielding.
    Base 7%, up to 20% based on secondary weapon skill level.
    Adjusted by skill differential: +/- 2.5% per skill point difference.
    """
    if not _is_elf_dual_wielding_finesse(attacker):
        return 0

    secondary_key = attacker.secondary_weapon.lower().replace(" ", "_").replace("&", "and")
    secondary_skill = attacker.skills.get(secondary_key, 0)

    # Scale from 7% (skill 0) to 20% (skill 9)
    # 7% + (20% - 7%) * (skill / 9) = 7 + 1.44... * skill
    base_chance = 7
    max_chance = 20
    chance_per_level = (max_chance - base_chance) / 9.0

    chance = base_chance + (secondary_skill * chance_per_level)

    # Apply skill differential modifier if defender is provided
    if defender:
        primary_key = defender.primary_weapon.lower().replace(" ", "_").replace("&", "and")
        defender_skill = defender.skills.get(primary_key, 0)
        differential_modifier = _calculate_skill_differential_modifier(secondary_skill, defender_skill)
        chance *= (1.0 + differential_modifier)

    return int(max(base_chance, min(max_chance, chance)))


def _has_martial_combat_bonus(warrior: Warrior) -> bool:
    """Check if warrior has martial_combat_bonus from their race."""
    return warrior.race.modifiers.martial_combat_bonus


def _is_using_martial_combat(warrior: Warrior) -> bool:
    """Check if warrior is currently fighting unarmed (Open Hand)."""
    return warrior.primary_weapon == "Open Hand"


def _is_claw_attack(warrior: Warrior) -> bool:
    """Check if warrior has claws and is using Open Hand (for flavor text)."""
    return warrior.primary_weapon == "Open Hand" and warrior.race.name in ("Lizardfolk", "Tabaxi")


def _get_martial_attack_type(warrior: Warrior, defender_name: str) -> str:
    """
    Determine the type of martial attack (claw, kick, tail) for Lizardfolk/Tabaxi.
    Uses defender name for deterministic selection so all narrative lines match.
    Returns: "claw", "kick", "tail", or None
    """
    if warrior.primary_weapon != "Open Hand":
        return None

    if warrior.race.name == "Lizardfolk":
        attack_types = ["claw", "kick", "tail"]
        return attack_types[sum(ord(c) for c in defender_name) % len(attack_types)]
    elif warrior.race.name == "Tabaxi":
        attack_types = ["claw", "kick"]
        return attack_types[sum(ord(c) for c in defender_name) % len(attack_types)]

    return None


def _calculate_martial_combat_extra_attack_chance(attacker: Warrior, defender: Warrior = None) -> int:
    """
    Calculate the percentage chance for a Halfling/Lizardfolk extra attack from martial combat.
    Halflings: 5% base → 12% at skill level 9
    Lizardfolk: 4% base → 10% at skill level 9
    Adjusted by skill differential: +/- 2.5% per skill point difference.
    """
    if not _has_martial_combat_bonus(attacker) or not _is_using_martial_combat(attacker):
        return 0

    open_hand_skill = attacker.skills.get("open_hand", 0)

    if attacker.race.name == "Halfling":
        base_chance = 5
        max_chance = 12
    elif attacker.race.name == "Lizardfolk":
        base_chance = 4
        max_chance = 10
    else:
        return 0

    chance_per_level = (max_chance - base_chance) / 9.0
    chance = base_chance + (open_hand_skill * chance_per_level)

    # Apply skill differential modifier if defender is provided
    if defender:
        primary_key = defender.primary_weapon.lower().replace(" ", "_").replace("&", "and")
        defender_skill = defender.skills.get(primary_key, 0)
        differential_modifier = _calculate_skill_differential_modifier(open_hand_skill, defender_skill)
        chance *= (1.0 + differential_modifier)

    return int(max(base_chance, min(max_chance, chance)))


def _can_trigger_tabaxi_frenzy(attacker: Warrior, state: _CState) -> bool:
    """Check if Tabaxi can trigger frenzy (race check, not yet used, has ability)."""
    if attacker.race.name != "Tabaxi":
        return False
    if not attacker.race.modifiers.frenzy_ability:
        return False
    if state.frenzy_used:
        return False
    return True


def _is_at_frenzy_threshold(state: _CState) -> bool:
    """Check if warrior is at or below 30% HP threshold."""
    max_hp = state.warrior.max_hp
    threshold_hp = int(max_hp * 0.30)
    return state.current_hp <= threshold_hp


def _calculate_skill_differential_modifier(attacker_skill: int, defender_skill: int) -> float:
    """
    Calculate percentage modifier based on skill differential.
    For every 1 point advantage: +2.5%
    For every 1 point disadvantage: -2.5%
    Returns modifier as decimal (e.g., 0.05 for +5%, -0.05 for -5%)
    """
    skill_diff = attacker_skill - defender_skill
    modifier = (skill_diff * 2.5) / 100.0
    return modifier


def _get_elf_dual_wield_damage_bonus(attacker: Warrior) -> int:
    """
    Get Elf dual-wielding damage bonus based on secondary weapon skill.
    Scales from +3 (skill 0) to +7 (skill 9)
    """
    if not _is_elf_dual_wielding_finesse(attacker):
        return 0
    secondary_key = attacker.secondary_weapon.lower().replace(" ", "_").replace("&", "and")
    secondary_skill = attacker.skills.get(secondary_key, 0)
    # Scale from 3 to 7: base 3 + (4 * skill/9)
    bonus = 3 + int((4.0 * secondary_skill) / 9.0)
    return bonus


def _get_elf_dual_wield_parry_bonus(attacker: Warrior) -> int:
    """
    Get Elf dual-wielding parry bonus based on secondary weapon skill.
    Scales from +10 (skill 0) to +20 (skill 9)
    """
    if not _is_elf_dual_wielding_finesse(attacker):
        return 0
    secondary_key = attacker.secondary_weapon.lower().replace(" ", "_").replace("&", "and")
    secondary_skill = attacker.skills.get(secondary_key, 0)
    # Scale from 10 to 20: base 10 + (10 * skill/9)
    bonus = 10 + int((10.0 * secondary_skill) / 9.0)
    return bonus


def _get_lizardfolk_natural_weapon_bonus(attacker: Warrior) -> int:
    """
    Get Lizardfolk natural weapon damage bonus based on Open Hand skill.
    Scales from +2 (skill 0) to +5 (skill 9)
    """
    if attacker.race.name != "Lizardfolk" or not _is_using_martial_combat(attacker):
        return 0
    open_hand_skill = attacker.skills.get("open_hand", 0)
    # Scale from 2 to 5: base 2 + (3 * skill/9)
    bonus = 2 + int((3.0 * open_hand_skill) / 9.0)
    return bonus


def _get_martial_combat_accuracy_bonus(attacker: Warrior) -> int:
    """
    Get martial combat accuracy bonus based on Open Hand skill.
    Scales from +2 (skill 0) to +6 (skill 9)
    """
    if not _has_martial_combat_bonus(attacker) or not _is_using_martial_combat(attacker):
        return 0
    open_hand_skill = attacker.skills.get("open_hand", 0)
    # Scale from 2 to 6: base 2 + (4 * skill/9)
    bonus = 2 + int((4.0 * open_hand_skill) / 9.0)
    return bonus


def _get_martial_combat_parry_bonus(attacker: Warrior) -> int:
    """
    Get martial combat parry bonus based on Open Hand skill.
    Scales from +4 (skill 0) to +8 (skill 9)
    """
    if not _has_martial_combat_bonus(attacker) or not _is_using_martial_combat(attacker):
        return 0
    open_hand_skill = attacker.skills.get("open_hand", 0)
    # Scale from 4 to 8: base 4 + (4 * skill/9)
    bonus = 4 + int((4.0 * open_hand_skill) / 9.0)
    return bonus


def _gnome_cs_line(defender_name: str, attacker_name: str) -> str:
    """Flavor line for a Gnome counterstrike_mastery riposte."""
    return random.choice([
        f"{defender_name.upper()} reads the attack perfectly and snaps a precise counter!",
        f"Turning the blade aside, {defender_name.upper()} drives a surgical riposte at {attacker_name.upper()}!",
        f"{defender_name.upper()} barely deflects the blow and then exploits the gap with expert precision!",
        f"The parry flows into a seamless counter as {defender_name.upper()} punishes the overextension!",
        f"{defender_name.upper()} uses {attacker_name.upper()}'s own momentum against them with a swift riposte!",
    ])


def _get_tabaxi_frenzy_damage_bonus(attacker: Warrior) -> int:
    """
    Get Tabaxi frenzy damage bonus based on primary weapon skill.
    Scales from +3 (skill 0) to +6 (skill 9)
    """
    wpn_key = attacker.primary_weapon.lower().replace(" ", "_").replace("&", "and")
    wpn_skill = attacker.skills.get(wpn_key, 0)
    # Scale from 3 to 6: base 3 + (3 * skill/9)
    bonus = 3 + int((3.0 * wpn_skill) / 9.0)
    return bonus


def _calculate_tabaxi_frenzy_trigger_chance(attacker: Warrior, defender: Warrior = None) -> int:
    """
    Calculate the percentage chance (0-100) for Tabaxi frenzy to trigger.
    Base 25%, scaled by primary weapon skill.
    Adjusted by skill differential: +/- 2.5% per skill point difference.
    """
    wpn_key = attacker.primary_weapon.lower().replace(" ", "_").replace("&", "and")
    wpn_skill = attacker.skills.get(wpn_key, 0)

    chance = 35

    # Apply skill differential modifier if defender is provided
    if defender:
        primary_key = defender.primary_weapon.lower().replace(" ", "_").replace("&", "and")
        defender_skill = defender.skills.get(primary_key, 0)
        differential_modifier = _calculate_skill_differential_modifier(wpn_skill, defender_skill)
        chance *= (1.0 + differential_modifier)

    return int(max(10, min(40, chance)))  # Clamp between 10% and 40%


def _get_defender_primary_defense_skill(defender: Warrior, defender_style: Strategy) -> tuple[int, str]:
    """
    Get defender's primary defense skill based on their style preference.
    Returns (skill_level, defense_type) where defense_type is 'parry' or 'dodge'
    """
    props = get_style_props(defender_style.style)
    uses_parry = props.parry_bonus >= props.dodge_bonus

    if uses_parry:
        return defender.skills.get("parry", 0), "parry"
    else:
        return defender.skills.get("dodge", 0), "dodge"


def _check_weapon_style_compatibility(weapon_name: str, style: str) -> tuple[bool, float]:
    """
    Check if a weapon and fighting style are compatible.
    Returns (is_compatible, penalty_factor).
    
    penalty_factor ranges from 1.0 (no penalty) to 0.6 (severe mismatch).
    This is used to reduce both damage and attack accuracy for awkward combos.
    """
    try:
        weapon = get_weapon(weapon_name)
    except ValueError:
        # Unknown weapon, assume compatible
        return True, 1.0
    
    # Check if the style is in the weapon's weak_styles list
    if style in weapon.weak_styles:
        # Severe incompatibility (e.g., Bash with Stiletto)
        return False, 0.60

    # A style the weapon was designed for overrides all generic category rules
    if style in weapon.preferred_styles:
        return True, 1.0

    # Check broader incompatibilities based on weapon category and style
    # These are thematic mismatches that aren't explicitly in weak_styles
    
    # Light weapons (weight < 2.5) with Bash (Shields are exempt)
    if weapon.weight < 2.5 and style == "Bash" and not weapon.is_shield:
        return False, 0.70
    
    # Heavier weapons (weight >= 4.0) with Lunge/Calculated Attack
    if weapon.weight >= 4.0 and style in ("Lunge", "Calculated Attack"):
        return False, 0.70
    
    # Two-handed weapons with Wall of Steel (too slow for rapid flurry)
    if weapon.two_hand and style == "Wall of Steel":
        return False, 0.75
    
    # Throwable-only checks (Net)
    if weapon.can_disarm and not weapon.throwable and style == "Opportunity Throw":
        return False, 0.80
    
    # All checks passed
    return True, 1.0


# ---------------------------------------------------------------------------
# FIGHT RESULT
# ---------------------------------------------------------------------------

@dataclass
class FightResult:
    """Summary of a completed fight. No draws exist."""
    winner          : Optional[Warrior]
    loser           : Optional[Warrior]
    loser_died      : bool
    minutes_elapsed : int
    narrative       : str
    training_results: dict  = field(default_factory=dict)
    # Per-fighter combat metrics, used by update_recognition v2
    winner_hp_pct    : float = 1.0   # winner's HP fraction at fight end
    loser_hp_pct     : float = 0.0   # loser's HP fraction at fight end
    winner_knockdowns: int   = 0     # knockdowns delivered by winner
    loser_knockdowns : int   = 0     # knockdowns delivered by loser
    winner_near_kills: int   = 0     # times winner reduced opponent below 20% HP
    loser_near_kills : int   = 0     # times loser reduced opponent below 20% HP
    exhaustion_end   : bool  = False # fight ended because a warrior's endurance hit 0
    winner_end_pct   : float = 1.0   # winner's endurance fraction at fight end
    loser_end_pct    : float = 0.0   # loser's endurance fraction at fight end


# ---------------------------------------------------------------------------
# COMBAT STATE
# ---------------------------------------------------------------------------

@dataclass
class _CState:
    """Mutable in-fight state for one warrior."""
    warrior            : Warrior
    current_hp         : int
    endurance          : float
    is_on_ground       : bool    = False
    active_strat_idx   : int     = 1
    active_strategy    : Strategy = None
    consecutive_ground : int     = 0
    is_weapon_dropped  : bool    = False
    dropped_weapon_name: str     = ""
    concede_attempts   : int     = 0
    hp_at_last_concede : int     = 9999
    knockdowns_dealt   : int     = 0   # knockdowns inflicted on opponent
    near_kills_dealt   : int     = 0   # times this warrior reduced opponent below 20% HP
    used_favorite_weapon_this_fight : bool = False  # Tracks if favorite weapon flavor already shown
    bleeding_wounds    : int     = 0   # Cumulative bleeding damage (tracked each round)
    triggered_injuries : dict    = field(default_factory=dict) # {location: level}
    phase2_entered     : bool    = False  # True once warrior has crossed the 25% endurance threshold
    frenzy_used        : bool    = False  # Tabaxi: frenzy ability has been used this fight
    armor_penalty      : float   = 0.0    # fraction 0.0-1.0 from over-weight armor
    perm_injuries_this_fight: int = 0    # cap at 2 per fight to prevent injury avalanche
    thrown_pool        : list    = field(default_factory=list)  # Goblin scavenger: weapons thrown this fight
    scavenger_scan_next: bool    = True   # Goblin scavenger: alternates scan(True)/roll(False)

    def to_fighter_state(self) -> FighterState:
        return FighterState(
            warrior             = self.warrior,
            current_hp          = self.current_hp,
            max_hp              = self.warrior.max_hp,
            endurance           = self.endurance,
            is_on_ground        = self.is_on_ground,
            active_strategy_idx = self.active_strat_idx,
            active_strategy     = self.active_strategy,
        )

    @property
    def hp_pct(self) -> float:
        return self.current_hp / max(1, self.warrior.max_hp)

    @property
    def wants_to_concede(self) -> bool:
        """True when at <=25% HP and HP has dropped since last concede attempt."""
        if self.current_hp <= 0:
            return True
        if self.hp_pct > 0.25:
            return False
        return self.current_hp < self.hp_at_last_concede


def _apply_bleeding_damage(state: "_CState") -> int:
    """Apply accumulated bleeding damage to the warrior."""
    if state.bleeding_wounds <= 0:
        return 0
    # Bleeding damage increases slightly as it accumulates
    damage = int(state.bleeding_wounds * 0.5)
    return max(1, damage)


# ---------------------------------------------------------------------------
# CORE ROLL FUNCTIONS
# ---------------------------------------------------------------------------

def _d100() -> int:
    return random.randint(1, 100)


def _initiative_roll(warrior: Warrior, strategy: Strategy, state: _CState) -> int:
    """d100 + DEX_bonus + initiative_skill*3 + luck + style_mod + activity_mod"""
    roll = _d100()
    dex = get_effective_dex_for_race(
        warrior.dexterity,
        warrior.armor or "None",
        warrior.helm or "None",
        warrior.race.name)
    dex_bonus    = max(-10, min(10, (dex - 10) * 2))
    # Skill scaling: higher initiative skill is more impactful
    init_val     = warrior.skills.get("initiative", 0)
    skill_bonus  = init_val * 4 if init_val >= 5 else init_val * 3

    luck_bonus   = warrior.luck
    race_init_bonus = warrior.race.modifiers.initiative_bonus
    props        = get_style_props(strategy.style)
    style_mod    = int(props.apm_modifier * 4)
    activity_mod = (strategy.activity - 5) * 2
    _phase2    = state.warrior.max_endurance * 0.25
    endurance_pen = int(max(0, (_phase2 - state.endurance) / max(1.0, _phase2) * 12)) if state.endurance < _phase2 else 0

    # Injury Penalties
    injury_pen = 0
    if "head" in state.triggered_injuries:
        injury_pen += state.triggered_injuries["head"] * 5
    if "primary_leg" in state.triggered_injuries or "secondary_leg" in state.triggered_injuries:
        injury_pen += 10

    if state.is_on_ground:
        return max(1, roll // 2)

    total = max(1, roll + dex_bonus + skill_bonus + luck_bonus + race_init_bonus
                + style_mod + activity_mod - endurance_pen - injury_pen)

    # Overencumbrance penalty to Initiative
    if state.armor_penalty > 0:
        total = int(total * (1.0 - state.armor_penalty))

    if warrior.race.name == "Lizardfolk":
        init_pct = get_lizardfolk_armor_penalties(warrior.armor or "None")["initiative_pct"]
        if init_pct > 0:
            total = max(1, int(total * (1.0 - init_pct)))
    return total


def _weapon_size_class(weapon_name: str) -> int:
    """0 = small (weight ≤ 2.5), 1 = medium (≤ 5.0), 2 = large (> 5.0)."""
    try:
        w = get_weapon(weapon_name)
        if w.weight <= 2.5:
            return 0
        elif w.weight <= 5.0:
            return 1
        else:
            return 2
    except ValueError:
        return 1


def _attack_roll(attacker: Warrior, strategy: Strategy, state: _CState, foe_style: str = "") -> int:
    """d100 + DEX + weapon_skill*5 + luck + style_mod + feint + lunge bonuses + favorite_weapon bonus"""
    roll  = _d100()
    dex   = get_effective_dex_for_race(attacker.dexterity, attacker.armor or "None", attacker.helm or "None", attacker.race.name)
    dex_b = max(-8, min(8, (dex - 10)))

    wpn_key   = attacker.primary_weapon.lower().replace(" ", "_").replace("&", "and")
    wpn_skill = attacker.skills.get(wpn_key, 0)
    wpn_b     = wpn_skill * 5

    luck_b    = attacker.luck
    props     = get_style_props(strategy.style)
    style_b   = int(props.apm_modifier * 3)
    feint_b   = attacker.skills.get("feint", 0) * 2
    lunge_b   = attacker.skills.get("lunge", 0) * 3 if strategy.style == "Lunge" else 0
    _phase2   = state.warrior.max_endurance * 0.25
    end_pen   = 15 if state.endurance < _phase2 and strategy.style in _AGGRESSIVE_STYLES else 0
    hp0_pen   = 30 if state.current_hp <= 0 else 0

    # Favorite weapon bonus: +5 to hit when using favorite weapon
    fav_bonus = 0
    if attacker.favorite_weapon and attacker.primary_weapon == attacker.favorite_weapon:
        fav_bonus = 5

    # Martial Combat bonus: scales +2 to +6 accuracy based on skill
    martial_bonus = 0
    if _has_martial_combat_bonus(attacker) and _is_using_martial_combat(attacker):
        martial_bonus = _get_martial_combat_accuracy_bonus(attacker)

    # Thrown mastery bonus: +10 to hit on Opportunity Throw (Goblin racial)
    thrown_mastery_b = 0
    if strategy.style == "Opportunity Throw" and attacker.race.modifiers.thrown_mastery:
        thrown_mastery_b = 10

    # Tactician's edge: +8 vs aggressive opponents, -6 vs methodical ones (Gnome racial)
    tactician_b = 0
    if attacker.race.modifiers.tactician_edge and foe_style:
        if foe_style in _TACTICIAN_FAVORED:
            tactician_b = 8
        elif foe_style in _TACTICIAN_DISFAVORED:
            tactician_b = -6

    # Injury Penalties
    injury_pen = 0
    if "head" in state.triggered_injuries:
        injury_pen += state.triggered_injuries["head"] * 4
    if "primary_arm" in state.triggered_injuries:
        injury_pen += state.triggered_injuries["primary_arm"] * 3
    if state.is_weapon_dropped:
        injury_pen += 20 # Fighting unarmed unexpectedly is hard

    # Ground penalty: attacking from the floor is desperate and inaccurate
    ground_pen = 25 if state.is_on_ground else 0

    # Heavy weapon penalty for Goblins & Tabaxi
    heavy_pen = 0
    if attacker.race.modifiers.heavy_weapon_penalty:
        try:
            weapon = get_weapon(attacker.primary_weapon)
            two_handed = (attacker.secondary_weapon == "Open Hand" and weapon.two_hand)
            is_heavy = weapon.weight >= 4.0 or (weapon.two_hand and two_handed)
            if is_heavy and not (attacker.race.modifiers.spear_exception and weapon.category == "Polearm/Spear"):
                heavy_pen = 10  # -10 accuracy penalty equiv
        except ValueError:
            pass

    total = roll + dex_b + wpn_b + luck_b + style_b + feint_b + lunge_b \
               - end_pen - hp0_pen + fav_bonus + martial_bonus + thrown_mastery_b \
               + tactician_b - injury_pen - ground_pen - heavy_pen

    if attacker.race.name == "Lizardfolk":
        atk_pct = get_lizardfolk_armor_penalties(attacker.armor or "None")["dodge_parry_pct"]
        if atk_pct > 0:
            total = int(total * (1.0 - atk_pct))

    if state.armor_penalty > 0:
        total = int(total * (1.0 - state.armor_penalty))

    return max(1, total)


def _defense_roll(
    defender  : Warrior,
    strategy  : Strategy,
    state     : _CState,
    attacker  : Warrior,
    aim_point : str,
    atk_style : str,
    is_parry  : bool = True,
) -> int:
    """
    Parry: d100 + STR_bonus + parry_skill*4 + weapon_skill*3 + luck + style + activity
    Dodge: d100 + DEX_bonus + dodge_skill*4 + weapon_skill*2 + luck + style + size_bonus
    Weapon skill helps both: knowing your weapon improves both blocking and evasion.
    """
    roll      = _d100()
    luck_b    = defender.luck
    props     = get_style_props(strategy.style)
    wpn_key   = defender.primary_weapon.lower().replace(" ", "_").replace("&", "and")
    wpn_skill = defender.skills.get(wpn_key, 0)

    # DEX training bonus: each trained DEX point adds to defense rolls
    # +2.5 per point for dodge (rounded), +2 per point for parry.
    dex_trained = defender.attribute_gains.get("dexterity", 0)

    if is_parry:
        str_b    = max(-5, min(5, (defender.strength - 10) // 2))
        skill_b  = defender.skills.get("parry", 0) * 4
        wpn_b    = wpn_skill * 3
        style_b  = props.parry_bonus * 3
        act_mod  = (5 - strategy.activity) * 2
        dex_train_parry = int(dex_trained * 2)   # +2 per trained DEX point
        race_parry_bonus = defender.race.modifiers.parry_bonus * 3  # Apply race parry bonus
        total    = roll + str_b + skill_b + wpn_b + style_b + act_mod + luck_b + dex_train_parry + race_parry_bonus
    else:
        dex      = get_effective_dex_for_race(defender.dexterity, defender.armor or "None", defender.helm or "None", defender.race.name)
        dex_b    = max(-8, min(8, (dex - 10)))
        skill_b  = defender.skills.get("dodge", 0) * 4
        wpn_b    = wpn_skill * 2
        style_b  = props.dodge_bonus * 2
        act_mod  = (strategy.activity - 5) * 2
        size_diff= attacker.size - defender.size
        size_b   = 5 if size_diff >= 3 else (-5 if size_diff <= -3 else 0)

        dex_train_dodge = int(dex_trained * 2.5) # +2.5 per trained DEX point
        race_dodge_bonus = defender.race.modifiers.dodge_bonus * 2  # Apply race dodge bonus

        # Acrobatics skill bonus to dodge
        acrobatics_level = defender.skills.get("acrobatics", 0)
        acrobatics_b = acrobatics_level * 2 if acrobatics_level > 0 else 0

        total    = roll + dex_b + skill_b + wpn_b + style_b + act_mod + size_b + luck_b + dex_train_dodge + race_dodge_bonus + acrobatics_b

        # Heavy weapon dodge penalty for Goblins & Tabaxi
        if defender.race.modifiers.heavy_weapon_penalty:
            try:
                weapon = get_weapon(defender.primary_weapon)
                two_handed = (defender.secondary_weapon == "Open Hand" and weapon.two_hand)
                is_heavy = weapon.weight >= 4.0 or (weapon.two_hand and two_handed)
                if is_heavy and not (defender.race.modifiers.spear_exception and weapon.category == "Polearm/Spear"):
                    total -= 10  # -1 dodge penalty equiv
            except ValueError:
                pass

    # Elf dual-wielding parry bonus: scales +10 to +20 based on skill
    if is_parry and _is_elf_dual_wielding_finesse(defender):
        elf_bonus = _get_elf_dual_wield_parry_bonus(defender)
        if elf_bonus > 0:
            total += elf_bonus

    # Martial Combat bonus: scales +4 to +8 parry/dodge based on skill
    if _has_martial_combat_bonus(defender) and _is_using_martial_combat(defender):
        mc_bonus = _get_martial_combat_parry_bonus(defender)
        if mc_bonus > 0:
            total += mc_bonus

    # Decoy baits the defender into committing to the guarded spot, so the
    # defense_point bonus is cancelled when the attacker is using Decoy.
    if (strategy.defense_point != "None"
            and strategy.defense_point == aim_point
            and atk_style != "Decoy"):
        total += 15

    try:
        sec_w = get_weapon(defender.secondary_weapon or "Open Hand")
        if sec_w.is_shield:
            total += 10 if defender.race.modifiers.shield_bonus else 5
    except ValueError:
        pass

    if props.total_kill_mode:
        return max(1, roll // 3)

    _phase2 = state.warrior.max_endurance * 0.25
    if state.endurance < _phase2 and strategy.style in _AGGRESSIVE_STYLES:
        total -= 15
    if state.is_on_ground:
        total -= 25
    if state.current_hp <= 0:
        total -= 30

    # Injury Penalties
    if "head" in state.triggered_injuries:
        total -= state.triggered_injuries["head"] * 4
    if not is_parry and ("primary_leg" in state.triggered_injuries or "secondary_leg" in state.triggered_injuries):
        total -= 15
    if is_parry and "primary_arm" in state.triggered_injuries:
        total -= state.triggered_injuries["primary_arm"] * 3

    if defender.race.name == "Lizardfolk":
        dp_pct = get_lizardfolk_armor_penalties(defender.armor or "None")["dodge_parry_pct"]
        if dp_pct > 0:
            total = int(total * (1.0 - dp_pct))

    # Overencumbrance penalty applies to final defensive effort (Parry and Dodge)
    if state.armor_penalty > 0:
        total = int(total * (1.0 - state.armor_penalty))

    # Tactician's edge: +5 defense vs aggressive attackers, -4 vs methodical (Gnome racial)
    if defender.race.modifiers.tactician_edge and atk_style:
        if atk_style in _TACTICIAN_FAVORED:
            total += 5
        elif atk_style in _TACTICIAN_DISFAVORED:
            total -= 4

    return max(1, total)


# ---------------------------------------------------------------------------
# DECOY FEINT
# ---------------------------------------------------------------------------
# Defender-penalty when a Decoy feint lands on the defender this action.
DECOY_FEINT_PENALTY = 20


def _attempt_feint(attacker: Warrior, defender: Warrior, def_style: str) -> bool:
    """
    Decoy pre-attack misdirection roll.

    Chance = 25 + feint_skill*5 + DEX_bonus + luck//3, capped at 85%.
    Counterstrike defenders have a strong chance to read the feint and
    negate it entirely (their whole style is waiting for the tell).
    """
    if def_style == "Counterstrike":
        read_chance = 55 + defender.skills.get("parry", 0) * 3
        if random.randint(1, 100) <= read_chance:
            return False

    feint_skill = attacker.skills.get("feint", 0)
    dex_bonus   = max(0, (attacker.dexterity - 10) // 2)
    chance      = 25 + feint_skill * 5 + dex_bonus + attacker.luck // 3
    chance      = min(85, chance)
    return random.randint(1, 100) <= chance


# ---------------------------------------------------------------------------
# CALCULATED ATTACK PRECISION
# ---------------------------------------------------------------------------
# When a Calculated Attack strike lands a precision roll, the attacker
# threads the blow through a seam in the defender's guard or armor.
CA_PRECISION_DAMAGE_BONUS = 3      # flat damage bonus on precision hits
CA_PRECISION_ARMOR_BYPASS = 0.60   # fraction of armor DV ignored on precision hits
CA_PROBE_EMIT_CHANCE      = 25     # % chance to flavor a failed CA probe on a miss


def _attempt_precision_strike(
    attacker : Warrior,
    defender : Warrior,
    weapon   : "Weapon",
    def_style: str,
) -> bool:
    """
    Pre-attack precision roll for Calculated Attack.

    Big/clunky weapons cannot finesse a seam. The style still delivers its
    baseline +2 damage modifier on every hit, but no precision bonus fires.

    Chance = 20 + weapon_skill*3 + DEX_bonus + luck/3
             - max(def_parry, def_dodge)*4
             - weight-class penalty
             - small buffer for actively defensive styles
    Clamped to [0, 75].
    """
    # Weight gate: very heavy weapons cannot precision-strike at all
    if weapon.weight >= 6.0:
        return False
    if "Calculated Attack" in (weapon.weak_styles or []):
        return False

    wpn_skill = attacker.skills.get(weapon.skill_key, 0)
    dex_bonus = max(0, (attacker.dexterity - 10) // 2)
    chance    = 20 + wpn_skill * 3 + dex_bonus + attacker.luck // 3

    # Heavier weapons erode precision chance. Calibrated so the "precise"
    # weapon tier (< 3.5 wt - stilettos, daggers, short swords, epees) takes
    # no penalty, mid-weight weapons take a small bite, and anything near
    # great-weapon weight is penalized severely.
    if weapon.weight >= 4.5:
        chance -= 25
    elif weapon.weight >= 3.5:
        chance -= 10

    # Defender's best of parry/dodge is the primary counter
    best_def_skill = max(
        defender.skills.get("parry", 0),
        defender.skills.get("dodge", 0),
    )
    chance -= best_def_skill * 4

    # Actively defensive styles get a small additional buffer - they aren't
    # guaranteed to shut down the probe, but they're harder to finesse
    if def_style in ("Parry", "Defend", "Wall of Steel", "Counterstrike"):
        chance -= 5

    chance = max(0, min(75, chance))
    return random.randint(1, 100) <= chance


# ---------------------------------------------------------------------------
# STRENGTH DAMAGE BONUS
# ---------------------------------------------------------------------------

def _str_damage_bonus(weapon: Weapon, attacker: Warrior, two_handed: bool = False,
                      eff_str_override: int = None) -> float:
    """Bonus damage multiplier from having strength above the weapon's minimum requirement.

    Open Hand (natural weapon, req STR 3): 5% per point above 3, capped at 100%.
    Small weapons  (weight ≤ 3.9 lbs):    5% per point above req, capped at  40%.
    Medium weapons (weight 4.0–5.9 lbs):  3% per point above req, capped at  25%.
    Heavy weapons  (weight ≥ 6.0 lbs):    no bonus.

    eff_str_override: pass a pre-capped effective STR (used for Opportunity Throw
    to enforce the STR-14 throw-damage ceiling).

    Returns a float 0.0–1.0 that callers add to 1.0 before multiplying raw damage.
    """
    weight = weapon.weight
    req_str = min_str_for_weight(weight, two_handed)
    eff_str = eff_str_override if eff_str_override is not None \
              else get_effective_strength_for_weapons(attacker)
    pts_above = max(0, eff_str - req_str)

    if _is_open_hand_weapon(weapon.skill_key):
        return min(1.00, pts_above * 0.05)
    if weight <= 3.9:
        return min(0.40, pts_above * 0.05)
    if weight <= 5.9:
        return min(0.25, pts_above * 0.03)
    return 0.0


def _ot_eff_str(attacker: Warrior) -> int:
    """Effective STR for Opportunity Throw damage, capped at base STR 14.
    STR above 14 adds no throw damage — further gains come from skill only.
    """
    eff = get_effective_strength_for_weapons(attacker)
    if attacker.strength > 14:
        eff -= (attacker.strength - 14)   # remove excess above cap
    return max(0, eff)


# ---------------------------------------------------------------------------
# DAMAGE (HYBRID)
# ---------------------------------------------------------------------------

def _calc_damage_hybrid(
    attacker        : Warrior,
    atk_strategy    : Strategy,
    weapon_name     : str,
    defender        : Warrior,
    margin          : int,
    precision_bypass: float = 0.0,
    style_compat_penalty: float = 1.0,
) -> Tuple[int, str]:
    """
    Simple damage system: baseline damage scaled by stats/skills, margin-based range,
    1.15x multiplier for versatile two-handed weapons, percentage-based armor reduction.
    """
    try:
        weapon = get_weapon(weapon_name)
    except ValueError:
        weapon = OPEN_HAND

    wpn_key = weapon_name.lower().replace(" ", "_").replace("&", "and")
    two_handed = (attacker.secondary_weapon == "Open Hand" and weapon.two_hand)
    wpn_skill = attacker.skills.get(wpn_key, 0)

    # Opportunity Throw: strength contributes less to thrown damage than to melee.
    # Technique and timing matter more than raw muscle when releasing a weapon.
    # Rules for OT damage:
    #   1. STR contribution is halved (technique > muscle for throws).
    #   2. STR above base 14 adds NO additional throw damage — further gains
    #      require skill training in throw/weapon (and even then are minimal).
    _is_ot = (atk_strategy.style == "Opportunity Throw")

    # Simple stat and skill scaling: STR bonus + weapon skill bonus
    _str_for_ot  = min(attacker.strength, 14) if _is_ot else attacker.strength
    str_bonus    = (_str_for_ot - 10) * (0.5 if _is_ot else 1.0)
    skill_bonus  = wpn_skill * 1.0
    bonus        = max(-10, str_bonus + skill_bonus)

    # Generic dual-wielding bonus
    dual_wield_bonus = 0
    if attacker.secondary_weapon != "Open Hand":
        try:
            secondary_wpn_obj = get_weapon(attacker.secondary_weapon)
            primary_wpn_obj = get_weapon(attacker.primary_weapon)
            if not secondary_wpn_obj.is_shield and not primary_wpn_obj.is_shield:
                dual_wield_bonus = 2 # Small flat bonus for dual-wielding non-finesse
        except ValueError:
            pass

    base_ceiling = weapon.damage_top + bonus + dual_wield_bonus
    base_floor = weapon.damage_base + max(0, (bonus + dual_wield_bonus) * 0.3)

    # Calculate raw damage based on margin (0 = floor, high margin = ceiling)
    fraction = max(0.0, min(1.00, margin / 55.0))
    raw = max(1, int(base_floor + (base_ceiling - base_floor) * fraction))

    # Versatile weapon two-handed bonus: 1.15x damage multiplier
    if _is_versatile_two_handed(wpn_key, attacker):
        raw = int(raw * 1.15)

    # Strength-above-minimum bonus.
    # OT: use STR-14-capped effective STR, then halve the result.
    if _is_ot:
        _eff_str_ot    = _ot_eff_str(attacker)
        str_bonus_mult = _str_damage_bonus(weapon, attacker, two_handed,
                                           eff_str_override=_eff_str_ot) * 0.5
        weight_pen     = strength_penalty(weapon.weight, _eff_str_ot, two_handed) * 0.5
    else:
        effective_str  = get_effective_strength_for_weapons(attacker)
        str_bonus_mult = _str_damage_bonus(weapon, attacker, two_handed)
        weight_pen     = strength_penalty(weapon.weight, effective_str, two_handed)

    if str_bonus_mult > 0.0:
        raw = int(raw * (1.0 + str_bonus_mult))
    if weight_pen > 0:
        raw = int(raw * (1.0 - weight_pen))

    # Finesse weapon precision bonus (parity with verbose path)
    if wpn_key in FINESSE_DAMAGE_WEAPONS and margin >= 10:
        raw += wpn_skill

    # Favorite weapon damage bonus: +1 raw damage
    if attacker.favorite_weapon and weapon_name == attacker.favorite_weapon:
        raw += 1

    # Lizardfolk natural weapon bonus: +2 to +5 for Open Hand style
    if attacker.race.modifiers.natural_weapon_bonus:
        natural_bonus = _get_lizardfolk_natural_weapon_bonus(attacker)
        raw += natural_bonus

    # Calculate armor reduction
    armor_nm = defender.armor or "None"
    helm_nm = defender.helm or "None"
    defense = get_effective_defense_for_race(armor_nm, helm_nm, defender.race.name)

    # Armor-piercing weapons reduce defense effectiveness
    if weapon.armor_piercing and is_ap_vulnerable(armor_nm):
        defense = max(0, defense // 2)

    # Calculated Attack precision hits thread a seam in the armor, bypassing
    # a fraction of the defender's defense value for this strike only.
    # Allow finesse (small, high-DEX/intelligence) builds to gain a small
    # precision bypass based on Dexterity, Intelligence, and weapon skill.
    finesse_bypass = 0.0
    try:
        if wpn_key in FINESSE_DAMAGE_WEAPONS:
            finesse_bypass = min(FINESSE_BYPASS_CAP, max(0.0,
                (attacker.dexterity - 12) * FINESSE_DEX_MULT +
                max(0, attacker.intelligence - 10) * FINESSE_INT_MULT +
                (wpn_skill * FINESSE_SKILL_MULT)
            ))
    except Exception:
        finesse_bypass = 0.0

    total_bypass = min(1.0, precision_bypass + finesse_bypass)
    if total_bypass > 0.0:
        defense = max(0, int(defense * (1.0 - total_bypass)))

    # Apply percentage-based armor reduction (4% per defense point, capped at 76%)
    armor_reduction = min(0.76, defense * 0.04)
    final_damage = int(raw * (1.0 - armor_reduction))

    return max(1, final_damage), weapon.category


# ---------------------------------------------------------------------------
# VERBOSE ROLL FUNCTIONS  (used only when debug_logger is active)
# Each function mirrors its normal counterpart exactly but also returns a
# components dict so the admin log can show the full calculation breakdown.
# ---------------------------------------------------------------------------

def _initiative_roll_verbose(warrior: "Warrior", strategy: "Strategy", state: "_CState"):
    roll         = _d100()
    dex = get_effective_dex_for_race(
        warrior.dexterity,
        warrior.armor or "None",
        warrior.helm or "None",
        warrior.race.name)
    dex_bonus    = max(-10, min(10, (dex - 10) * 2))
    skill_bonus  = warrior.skills.get("initiative", 0) * 3
    luck_bonus   = warrior.luck
    race_init    = warrior.race.modifiers.initiative_bonus
    props        = get_style_props(strategy.style)
    style_mod    = int(props.apm_modifier * 4)
    activity_mod = (strategy.activity - 5) * 2
    _phase2  = state.warrior.max_endurance * 0.25
    end_pen  = int(max(0, (_phase2 - state.endurance) / max(1.0, _phase2) * 12)) if state.endurance < _phase2 else 0
    if state.is_on_ground:
        result = max(1, roll // 2)
        return result, {"d100": roll, "on_ground_halved": "(÷2)"}
    result = max(1, roll + dex_bonus + skill_bonus + luck_bonus + race_init + style_mod + activity_mod - end_pen)
    comps = {
        "d100": roll,
        "dex_bonus": dex_bonus,
        "init_skill_x3": skill_bonus,
        "luck": luck_bonus,
        "race_init": race_init,
        "style_mod": style_mod,
        "activity_mod": activity_mod,
        "end_pen": -end_pen if end_pen else 0,
    }

    if state.armor_penalty > 0:
        result = int(result * (1.0 - state.armor_penalty))
        comps["overencumbrance_pen"] = -int(state.armor_penalty * 100)

    if warrior.race.name == "Lizardfolk":
        init_pct = get_lizardfolk_armor_penalties(warrior.armor or "None")["initiative_pct"]
        if init_pct > 0:
            result = max(1, int(result * (1.0 - init_pct)))
            comps["lizard_armor_init_pct"] = -int(init_pct * 100)
    return result, comps


def _attack_roll_verbose(attacker: "Warrior", strategy: "Strategy", state: "_CState", foe_style: str = ""):
    roll    = _d100()
    dex = get_effective_dex_for_race(
        attacker.dexterity,
        attacker.armor or "None",
        attacker.helm or "None",
        attacker.race.name)
    dex_b   = max(-8, min(8, (dex - 10)))
    wpn_key = attacker.primary_weapon.lower().replace(" ", "_").replace("&", "and")
    wpn_sk  = attacker.skills.get(wpn_key, 0)
    wpn_b   = wpn_sk * 5
    luck_b  = attacker.luck
    props   = get_style_props(strategy.style)
    style_b = int(props.apm_modifier * 3)
    feint_b = attacker.skills.get("feint", 0) * 2
    lunge_b = attacker.skills.get("lunge", 0) * 3 if strategy.style == "Lunge" else 0
    _phase2 = state.warrior.max_endurance * 0.25
    end_pen = 15 if state.endurance < _phase2 and strategy.style in _AGGRESSIVE_STYLES else 0
    hp0_pen = 30 if state.current_hp <= 0 else 0
    fav_b   = 5 if (attacker.favorite_weapon and attacker.primary_weapon == attacker.favorite_weapon) else 0
    martial_b = 0
    if _has_martial_combat_bonus(attacker) and _is_using_martial_combat(attacker):
        martial_b = _get_martial_combat_accuracy_bonus(attacker)
    thrown_b = 10 if (strategy.style == "Opportunity Throw" and attacker.race.modifiers.thrown_mastery) else 0
    tactician_b = 0
    if attacker.race.modifiers.tactician_edge and foe_style:
        if foe_style in _TACTICIAN_FAVORED:    tactician_b =  8
        elif foe_style in _TACTICIAN_DISFAVORED: tactician_b = -6
    ground_pen = 25 if state.is_on_ground else 0

    # Heavy weapon penalty for Goblins & Tabaxi
    heavy_pen = 0
    if attacker.race.modifiers.heavy_weapon_penalty:
        try:
            weapon = get_weapon(attacker.primary_weapon)
            two_handed = (attacker.secondary_weapon == "Open Hand" and weapon.two_hand)
            is_heavy = weapon.weight >= 4.0 or (weapon.two_hand and two_handed)
            if is_heavy and not (attacker.race.modifiers.spear_exception and weapon.category == "Polearm/Spear"):
                heavy_pen = 10  # -10 accuracy penalty equiv
        except ValueError:
            pass

    result  = roll + dex_b + wpn_b + luck_b + style_b + feint_b + lunge_b - end_pen - hp0_pen + fav_b + martial_b + thrown_b + tactician_b - ground_pen - heavy_pen
    comps = {
        "d100": roll,
        "dex_bonus": dex_b,
        f"wpn_skill(lv{wpn_sk})x5": wpn_b,
        "luck": luck_b,
        "style_mod": style_b,
        "feint": feint_b,
        "lunge": lunge_b,
        "fav_bonus": fav_b,
        "martial_combat": martial_b,
        "thrown_mastery": thrown_b,
        "tactician_edge": tactician_b,
        "ground_pen": -ground_pen if ground_pen else 0,
        "end_pen": -end_pen if end_pen else 0,
        "hp0_pen": -hp0_pen if hp0_pen else 0,
        "heavy_weapon_pen": -heavy_pen if heavy_pen else 0,
    }

    if attacker.race.name == "Lizardfolk":
        atk_pct = get_lizardfolk_armor_penalties(attacker.armor or "None")["dodge_parry_pct"]
        if atk_pct > 0:
            result = int(result * (1.0 - atk_pct))
            comps["lizard_armor_atk_pct"] = -int(atk_pct * 100)

    if state.armor_penalty > 0:
        result = int(result * (1.0 - state.armor_penalty))
        comps["overencumbrance_pen"] = -int(state.armor_penalty * 100)
    result = max(1, result)
    return result, comps


def _defense_roll_verbose(
    defender: "Warrior", strategy: "Strategy", state: "_CState",
    attacker: "Warrior", aim_point: str, atk_style: str, is_parry: bool = True,
):
    roll      = _d100()
    luck_b    = defender.luck
    props     = get_style_props(strategy.style)
    wpn_key   = defender.primary_weapon.lower().replace(" ", "_").replace("&", "and")
    wpn_skill = defender.skills.get(wpn_key, 0)
    dex_trained = defender.attribute_gains.get("dexterity", 0)
    comps = {"d100": roll, "luck": luck_b}

    if is_parry:
        str_b         = max(-5, min(5, (defender.strength - 10) // 2))
        skill_b       = defender.skills.get("parry", 0) * 4
        wpn_b         = wpn_skill * 3
        style_b       = props.parry_bonus * 3
        act_mod       = (5 - strategy.activity) * 2
        dex_train     = int(dex_trained * 2)
        race_parry    = defender.race.modifiers.parry_bonus * 3
        total         = roll + str_b + skill_b + wpn_b + style_b + act_mod + luck_b + dex_train + race_parry
        comps.update({
            "str_bonus": str_b,
            f"parry_skill(lv{defender.skills.get('parry',0)})x4": skill_b,
            f"wpn_skill(lv{wpn_skill})x3": wpn_b,
            "style_parry": style_b,
            "activity_mod": act_mod,
            "dex_trained_x2": dex_train,
            "race_parry_x3": race_parry,
        })
    else:
        dex      = get_effective_dex_for_race(defender.dexterity, defender.armor or "None", defender.helm or "None", defender.race.name)
        dex_b    = max(-8, min(8, (dex - 10)))
        skill_b  = defender.skills.get("dodge", 0) * 4
        wpn_b    = wpn_skill * 2
        style_b  = props.dodge_bonus * 2
        act_mod  = (strategy.activity - 5) * 2
        size_diff= attacker.size - defender.size
        size_b   = 5 if size_diff >= 3 else (-5 if size_diff <= -3 else 0)

        dex_train= int(dex_trained * 2.5)
        race_dg  = defender.race.modifiers.dodge_bonus * 2
        acro_lv  = defender.skills.get("acrobatics", 0)
        acro_b   = acro_lv * 2 if acro_lv > 0 else 0
        total    = roll + dex_b + skill_b + wpn_b + style_b + act_mod + size_b + luck_b + dex_train + race_dg + acro_b

        heavy_pen = 0
        if defender.race.modifiers.heavy_weapon_penalty:
            try:
                _w = get_weapon(defender.primary_weapon)
                _2h = (defender.secondary_weapon == "Open Hand" and _w.two_hand)
                if (_w.weight >= 4.0 or (_w.two_hand and _2h)) and not (defender.race.modifiers.spear_exception and _w.category == "Polearm/Spear"):
                    total -= 10
                    heavy_pen = -10
            except ValueError:
                pass
        comps.update({
            "dex_bonus": dex_b,
            f"dodge_skill(lv{defender.skills.get('dodge',0)})x4": skill_b,
            f"wpn_skill(lv{wpn_skill})x2": wpn_b,
            "style_dodge": style_b,
            "activity_mod": act_mod,
            "size_diff": size_b,
            "dex_trained_x2.5": dex_train,
            "race_dodge_x2": race_dg,
            "acrobatics_x2": acro_b if acro_b else 0,
            "heavy_wpn_pen": heavy_pen if heavy_pen else 0,
        })

    elf_dual_bonus = 0
    if is_parry and _is_elf_dual_wielding_finesse(defender):
        elf_dual_bonus = _get_elf_dual_wield_parry_bonus(defender)
        if elf_dual_bonus > 0:
            total += elf_dual_bonus
    if elf_dual_bonus:
        comps["elf_dual_wielding_parry"] = elf_dual_bonus

    martial_bonus = 0
    if _has_martial_combat_bonus(defender) and _is_using_martial_combat(defender):
        martial_bonus = _get_martial_combat_parry_bonus(defender)
        if martial_bonus > 0:
            total += martial_bonus
    if martial_bonus:
        comps["martial_combat"] = martial_bonus

    def_pt_bonus = 0
    if strategy.defense_point != "None" and strategy.defense_point == aim_point and atk_style != "Decoy":
        total += 15
        def_pt_bonus = 15
    comps["def_point_bonus"] = def_pt_bonus

    shield_b = 0
    try:
        sec_w = get_weapon(defender.secondary_weapon or "Open Hand")
        if sec_w.is_shield:
            shield_b = 10 if defender.race.modifiers.shield_bonus else 5
            total += shield_b
    except ValueError:
        pass
    if shield_b:
        comps["shield_bonus"] = shield_b

    if props.total_kill_mode:
        total = max(1, roll // 3)
        comps["total_kill_mode_override"] = True
        return total, comps

    _phase2 = state.warrior.max_endurance * 0.25
    end_pen = 15 if state.endurance < _phase2 and strategy.style in _AGGRESSIVE_STYLES else 0
    if end_pen:
        total -= end_pen
    if state.is_on_ground:
        total -= 25
        comps["ground_pen"] = -25
    if state.current_hp <= 0:
        total -= 30
        comps["hp0_pen"] = -30
    if end_pen:
        comps["end_pen"] = -end_pen

    if defender.race.name == "Lizardfolk":
        dp_pct = get_lizardfolk_armor_penalties(defender.armor or "None")["dodge_parry_pct"]
        if dp_pct > 0:
            total = int(total * (1.0 - dp_pct))
            comps["lizard_armor_dp_pct"] = -int(dp_pct * 100)

    # Overencumbrance penalty applies to final defensive effort
    if state.armor_penalty > 0:
        total = int(total * (1.0 - state.armor_penalty))
        comps["overencumbrance_pen"] = -int(state.armor_penalty * 100)

    return max(1, total), comps


def _calc_damage_verbose(
    attacker, atk_strategy, weapon_name: str, defender,
    margin: int, precision_bypass: float = 0.0, style_compat_penalty: float = 1.0,
):
    """Mirrors _calc_damage_hybrid but also returns a steps dict for the debug log."""
    try:
        weapon = get_weapon(weapon_name)
    except ValueError:
        weapon = OPEN_HAND

    two_handed = (attacker.secondary_weapon == "Open Hand" and weapon.two_hand)
    wpn_key = weapon_name.lower().replace(" ", "_").replace("&", "and")
    is_small   = wpn_key in FINESSE_DAMAGE_WEAPONS
    wpn_skill = attacker.skills.get(wpn_key, 0)
    steps: dict = {}

    # Generic dual-wielding bonus
    dual_wield_bonus = 0
    if attacker.secondary_weapon != "Open Hand":
        try:
            secondary_wpn_obj = get_weapon(attacker.secondary_weapon)
            primary_wpn_obj = get_weapon(attacker.primary_weapon)
            if not secondary_wpn_obj.is_shield and not primary_wpn_obj.is_shield:
                dual_wield_bonus = 2
        except ValueError:
            pass

    # Mirror _calc_damage_hybrid exactly (OT: halved + STR 14 cap)
    _is_ot       = (atk_strategy.style == "Opportunity Throw")
    _str_for_ot  = min(attacker.strength, 14) if _is_ot else attacker.strength
    str_bonus    = (_str_for_ot - 10) * (0.5 if _is_ot else 1.0)
    skill_bonus = wpn_skill * 1.0
    bonus = max(-10, str_bonus + skill_bonus)

    base_ceiling = weapon.damage_top + bonus + dual_wield_bonus
    base_floor = weapon.damage_base + max(0, (bonus + dual_wield_bonus) * 0.3)

    steps["damage_base"] = weapon.damage_base
    steps["damage_top"] = weapon.damage_top
    steps["str_bonus"] = str_bonus
    steps["ot_str_scale"] = "0.5x (throw)" if _is_ot else "1.0x (melee)"
    steps["skill_bonus"] = skill_bonus
    steps["bonus"] = bonus
    steps["dual_wield_bonus"] = dual_wield_bonus
    steps["base_floor"] = round(base_floor, 2)
    steps["base_ceiling"] = round(base_ceiling, 2)

    fraction = max(0.0, min(1.00, margin / 55.0))
    raw = max(1, int(base_floor + (base_ceiling - base_floor) * fraction))
    steps["fraction"] = round(fraction, 3)

    # Versatile weapon two-handed bonus: 1.15x damage multiplier
    if _is_versatile_two_handed(wpn_key, attacker):
        raw = int(raw * 1.15)
        steps["two_hand_mult"] = 1.15
    else:
        steps["two_hand_mult"] = 1.0

    # Strength-above-minimum bonus (OT: capped at STR 14, then halved)
    if _is_ot:
        _eff_str_ot   = _ot_eff_str(attacker)
        str_dmg_bonus = _str_damage_bonus(weapon, attacker, two_handed,
                                          eff_str_override=_eff_str_ot) * 0.5
        str_pen       = strength_penalty(weapon.weight, _eff_str_ot, two_handed) * 0.5
        steps["ot_eff_str_capped"] = _eff_str_ot
    else:
        effective_str = get_effective_strength_for_weapons(attacker)
        str_dmg_bonus = _str_damage_bonus(weapon, attacker, two_handed)
        str_pen       = strength_penalty(weapon.weight, effective_str, two_handed)

    if str_dmg_bonus > 0.0:
        raw = int(raw * (1.0 + str_dmg_bonus))
        steps["str_above_req_bonus"] = round(str_dmg_bonus, 3)
    if str_pen > 0:
        raw = int(raw * (1.0 - str_pen))
        steps["str_penalty_factor"] = round(str_pen, 3)

    # Finesse weapon precision bonus
    prec_b = 0
    if is_small and margin >= 10:
        raw += wpn_skill
        prec_b = wpn_skill
    steps["prec_bonus"] = prec_b

    # Favorite weapon damage bonus
    fav_b = 0
    if attacker.favorite_weapon and weapon_name == attacker.favorite_weapon:
        raw += 1
        fav_b = 1
    steps["fav_bonus"] = fav_b

    # Lizardfolk natural weapon bonus: +2 to +5 for Open Hand style
    nat_b = 0
    if attacker.race.modifiers.natural_weapon_bonus:
        nat_b = _get_lizardfolk_natural_weapon_bonus(attacker)
        raw += nat_b
    steps["natural_weapon_bonus"] = nat_b

    steps["raw"] = raw - fav_b - prec_b - nat_b
    steps["raw_with_fav"] = raw

    # Armor calculation (percentage-based, mirroring _calc_damage_hybrid)
    armor_nm  = defender.armor or "None"
    helm_nm   = defender.helm  or "None"
    defense   = get_effective_defense_for_race(armor_nm, helm_nm, defender.race.name)
    armor_def = defense

    ap = False
    if weapon.armor_piercing and is_ap_vulnerable(armor_nm):
        defense = max(0, defense // 2)
        ap = True

    armor_after_ap = defense

    finesse_bypass = 0.0
    try:
        if is_small:
            finesse_bypass = min(FINESSE_BYPASS_CAP, max(0.0,
                (attacker.dexterity - 12) * FINESSE_DEX_MULT +
                max(0, attacker.intelligence - 10) * FINESSE_INT_MULT +
                (wpn_skill * FINESSE_SKILL_MULT)
            ))
    except Exception:
        finesse_bypass = 0.0

    total_bypass = min(1.0, precision_bypass + finesse_bypass)
    if total_bypass > 0.0:
        steps["finesse_precision_bypass"] = round(finesse_bypass, 3)
        steps["total_precision_bypass"] = round(total_bypass, 3)
        defense = max(0, int(defense * (1.0 - total_bypass)))

    armor_reduction = min(0.76, defense * 0.04)
    final_damage = max(1, int(raw * (1.0 - armor_reduction)))

    steps.update({
        "armor_name": armor_nm,
        "armor_def": armor_def,
        "armor_piercing": ap,
        "armor_after_ap": armor_after_ap,
        "precision_bypass": precision_bypass,
        "final_armor": defense,
        "armor_reduction": round(armor_reduction, 3),
        "net_pre_mods": final_damage,
    })
    return final_damage, weapon.category, steps


def _concede_check_verbose(warrior: "Warrior", state: "_CState", is_monster_fight: bool = False):
    if is_monster_fight:
        return False, {"monster_fight": True, "d100": 0, "PRE_bonus": 0, "luck_half": 0, "total": 0, "threshold": 0}
    roll      = _d100()
    presence  = warrior.presence
    pre_b     = max(-6, min(10, presence - 10))
    luck_half = warrior.luck // 2
    total     = roll + pre_b + luck_half
    threshold = max(40, 68 - (presence // 3))
    granted   = total >= threshold
    return granted, {
        "d100": roll, "PRE_bonus": pre_b, "luck_half": luck_half,
        "total": total, "threshold": threshold,
    }


def _death_check_verbose(prev_hp: int, damage: int):
    new_hp    = prev_hp - damage
    if new_hp > 0:
        return False, {"new_hp": new_hp, "overshoot": 0, "death_chance": 0.0}
    overshoot    = abs(min(new_hp, 0))
    death_chance = min(50.0, 0.5 + float(overshoot))
    died         = random.random() * 100 < death_chance
    return died, {"new_hp": new_hp, "overshoot": overshoot, "death_chance": death_chance}


def _check_knockdown_verbose(warrior: "Warrior", state: "_CState", damage: int, cat: str):
    if state.is_on_ground:
        return False, 0, 0
    chance = int((damage / max(1, warrior.max_hp)) * 12)
    if cat in ("Hammer/Mace", "Flail"):
        chance += 5
    if cat == "Polearm/Spear":
        chance += 3
    chance -= max(0, (warrior.size - 12)) * 2
    if warrior.race.modifiers.acrobatic_advantage:
        chance = chance // 2  # 50% knockdown resistance for Tabaxi
    final  = max(1, chance)
    roll   = random.randint(1, 100)
    return roll <= final, final, roll


def _check_perm_injury_verbose(warrior: "Warrior", damage: int, aim_point: str):
    threshold = int(warrior.max_hp * 0.30)
    if damage < warrior.max_hp * 0.30:
        return None, threshold, 0, 0
    chance = max(5, min(80, int((damage / warrior.max_hp) * 100) - 20))
    if warrior.race.modifiers.fewer_perms:
        chance = int(chance * 0.80)
    roll = random.randint(1, 100)
    if roll > chance:
        return None, threshold, chance, roll
    if aim_point and aim_point != "None":
        loc_map = {
            "Head": "head", "Chest": "chest", "Abdomen": "abdomen",
            "Primary Arm": "primary_arm", "Secondary Arm": "secondary_arm",
            "Primary Leg": "primary_leg", "Secondary Leg": "secondary_leg",
        }
        location = loc_map.get(aim_point, random.choice(_BODY_LOCATION_POOL))
    else:
        location = random.choice(_BODY_LOCATION_POOL)
    pct    = damage / warrior.max_hp
    levels = 3 if pct > 0.65 else (2 if pct > 0.45 else 1)
    return (location, levels), threshold, chance, roll


# ---------------------------------------------------------------------------
# PERM INJURY
# ---------------------------------------------------------------------------

# Used when no aim point is set (generic "body" strike) - head and legs excluded
# since the narrative already describes the hit as targeting the torso/midsection.
_BODY_LOCATION_POOL = [
    "chest", "chest", "chest", "abdomen", "abdomen",
    "primary_arm", "secondary_arm",
]


def _check_perm_injury(
    warrior   : Warrior,
    damage    : int,
    aim_point : str,
) -> Optional[Tuple[str, int]]:
    if damage < warrior.max_hp * 0.30:
        return None
    chance = max(5, min(80, int((damage / warrior.max_hp) * 100) - 20))
    if warrior.race.modifiers.fewer_perms:
        chance = int(chance * 0.80)
    if random.randint(1, 100) > chance:
        return None
    if aim_point and aim_point != "None":
        # Map targeting to actual injury locations
        loc_map = {
            "Head":"head","Chest":"chest","Abdomen":"abdomen",
            "Primary Arm":"primary_arm","Secondary Arm":"secondary_arm",
            "Primary Leg":"primary_leg","Secondary Leg":"secondary_leg",
        }
        location = loc_map.get(aim_point, random.choice(_BODY_LOCATION_POOL))
    else:
        # No aim point - generic body strike, restrict to torso/arm locations
        location = random.choice(_BODY_LOCATION_POOL)
    pct    = damage / warrior.max_hp
    levels = 3 if pct > 0.65 else (2 if pct > 0.45 else 1)
    return location, levels


def _check_injury_flare_up(warrior: Warrior, state: _CState, damage: int, aim_point: str) -> Optional[str]:
    """Check if taking damage to an existing injury causes it to flare up."""
    if damage < warrior.max_hp * 0.10: # Must be a decent blow
        return None
        
    loc_map = {
            "Head":"head","Chest":"chest","Abdomen":"abdomen",
            "Primary Arm":"primary_arm","Secondary Arm":"secondary_arm",
            "Primary Leg":"primary_leg","Secondary Leg":"secondary_leg",
        }
    
    target_loc = loc_map.get(aim_point, "none")
    if target_loc == "none": return None
    
    lvl = warrior.injuries.get(target_loc)
    if lvl <= 0: return None
    
    # Chance to flare up: 15% per level of injury
    chance = lvl * 15
    if random.randint(1, 100) <= chance:
        state.triggered_injuries[target_loc] = lvl
        return target_loc
    return None


# ---------------------------------------------------------------------------
# FAVORITE WEAPON FLAVOR
# ---------------------------------------------------------------------------

def _get_favorite_weapon_flavor(warrior: Warrior, weapon_name: str, state: _CState) -> Optional[str]:
    """
    Generate a narrative line for using a favorite weapon.
    Returns None if weapon is not favorite, already used this fight, no flavor line exists,
    or if the SHOW_FAVORITE_WEAPON feature flag is disabled.
    Modifies state to mark that favorite was used.
    """
    if not warrior.favorite_weapon or weapon_name != warrior.favorite_weapon:
        return None
    if state.used_favorite_weapon_this_fight:
        return None
    
    # Mark that we've already used the favorite weapon flavor this fight
    state.used_favorite_weapon_this_fight = True
    
    # Import here to avoid circular imports
    from weapons import FAVORITE_WEAPON_LINES
    
    # Get the flavor lines for this weapon
    lines = FAVORITE_WEAPON_LINES.get(weapon_name)
    if not lines:
        return None
    
    # Select a random flavor line and format with warrior name
    line = random.choice(lines)
    return line.format(name=warrior.name.upper())


# ---------------------------------------------------------------------------
# KNOCKDOWN
# ---------------------------------------------------------------------------

def _check_entangle(warrior: Warrior, state: _CState, weapon: Weapon, was_thrown: bool) -> Tuple[bool, Optional[str]]:
    """
    Check if a bola or heavy whip entangles the opponent's legs, causing them to trip.
    Returns (entangled, narrative_line).
    """
    if state.is_on_ground:
        return False, None
    
    if weapon.skill_key == "bola":
        if was_thrown:
            # Bola thrown: 70% chance to entangle and trip
            if random.randint(1, 100) <= 70:
                msg = f"The bola wraps around {warrior.name.upper()}'s legs and trips them to the ground!"
                return True, msg
        else:
            # Bola swung in melee: 35% chance to entangle
            if random.randint(1, 100) <= 35:
                msg = f"The swinging bola tangles {warrior.name.upper()}'s legs!"
                return True, msg
    
    elif weapon.skill_key == "heavy_whip":
        # Heavy whip: good chance to entangle on successful hit
        # Lower chance in melee than thrown, but it's never thrown
        if random.randint(1, 100) <= 50:
            msg = f"The barbed whip wraps around {warrior.name.upper()}'s legs, dragging them to the ground!"
            return True, msg
    
    return False, None


def _check_knockdown(warrior: Warrior, state: _CState, damage: int, cat: str) -> bool:
    if state.is_on_ground:
        return False
    chance  = int((damage / max(1, warrior.max_hp)) * 30)
    if cat in ("Hammer/Mace","Flail"):  chance += 5
    if cat == "Polearm/Spear":          chance += 3
    chance -= max(0, (warrior.size - 12)) * 2
    if warrior.race.modifiers.acrobatic_advantage:
        chance = chance // 2  # 50% knockdown resistance for Tabaxi
    return random.randint(1, 100) <= max(1, chance)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# DEATH CHECK
# ---------------------------------------------------------------------------

def _death_check(prev_hp: int, damage: int) -> bool:
    """
    Death probability on reaching 0 HP:
      base 0.5%, +1% per HP of overshoot, cap 50%.
    """
    new_hp    = prev_hp - damage
    if new_hp > 0:
        return False
    overshoot = abs(min(new_hp, 0))
    return random.random() * 100 < min(50.0, 0.5 + float(overshoot))


# ---------------------------------------------------------------------------
# CONCEDE CHECK
# ---------------------------------------------------------------------------

def _concede_check(warrior: Warrior, state: _CState, is_monster_fight: bool = False) -> bool:
    """
    d100 + PRE_bonus + luck//2 vs threshold (max(40, 68 - PRE//3)).
    High Presence = lower threshold = easier to get mercy.
    Effective mercy rate ~40-55% when triggered; overall fight death ~2.5-3%.
    """
    if is_monster_fight:
        return False
    roll      = _d100()
    presence  = warrior.presence
    pre_b     = max(-6, min(10, presence - 10))
    total     = roll + pre_b + warrior.luck // 2
    threshold = max(40, 68 - (presence // 3))
    return total >= threshold


# ---------------------------------------------------------------------------
# ENDURANCE
# ---------------------------------------------------------------------------

def _update_endurance(
    state: _CState, strategy: Strategy, foe: _CState, apm: int = 5, minute: int = 1
) -> Tuple[List[str], float]:
    lines   = []
    warrior = state.warrior
    props   = get_style_props(strategy.style)

    # Weapon weight (game scale 0–7.5)
    try:
        wpn_wt = get_weapon(warrior.primary_weapon).weight
    except Exception:
        wpn_wt = 0.0

    # Armor and helm contribution via defense value (0–10 / 0–5)
    armor_def = ARMOR_PIECES.get(warrior.armor or "None", ARMOR_PIECES["None"]).defense_value
    helm_def  = ARMOR_PIECES.get(warrior.helm  or "None", ARMOR_PIECES["None"]).defense_value

    # Mitigators: DEX −1% per 2 pts over 10; INT −1.5% per 2 pts over 10
    dex_mit = max(0, (warrior.dexterity    - 10) // 2) * 0.01
    int_mit = max(0, (warrior.intelligence - 10) // 2) * 0.015
    mit     = min(0.50, dex_mit + int_mit)

    # Action-centric burn logic:
    # Use the base endurance_burn defined in strategy.py (e.g. 1.0 for Parry, 10.0 for Total Kill)
    base_burn = props.endurance_burn
    
    # Activity multiplier: act 1 = 60%, act 5 = 100%, act 9 = 140% of base burn
    act_mult = 0.5 + (strategy.activity * 0.1)
    
    # Gear weight tax: added per action. Reduced slightly to prevent gear from 
    # completely drowning out style-based costs.
    gear_tax = (wpn_wt * 0.12) + ((armor_def + helm_def) * 0.08)
    
    # Mastery bonus: weapon mastery reduces friction
    wpn_key        = warrior.primary_weapon.lower().replace(" ", "_").replace("&", "and")
    wpn_skill_lv   = warrior.skills.get(wpn_key, 0)
    mastery_reduction = wpn_skill_lv * 0.05 # up to 45% reduction of gear tax

    burn = (base_burn * act_mult) + (gear_tax * (1.0 - mastery_reduction))
    burn *= (1.0 - mit)

    # Overencumbrance burn penalty
    if state.armor_penalty > 0:
        burn *= (1.0 + state.armor_penalty)

    # Phase II feedback spiral: already exhausted → reserves drain 25% faster
    phase2 = warrior.max_endurance * 0.25
    if state.endurance < phase2:
        burn *= 1.25

    # Acrobatics efficiency for Lunge / Engage & Withdraw.
    # Without acrobatics training these mobile styles cost an extra 10% per action;
    # each acrobatics level shaves 1% off that penalty (Level 9 → only 1% extra).
    if strategy.style in ("Engage & Withdraw", "Lunge"):
        acro_lv = warrior.skills.get("acrobatics", 0)
        burn += max(1, 10 - acro_lv) * 0.01

    # Per-minute passive drain: cumulative fatigue past minute 5
    # +0.5 per minute over 5, spread across actions (÷ apm)
    if minute > 5:
        passive_pm = (minute - 5) * 0.5
        burn += passive_pm / max(1, apm)

    old_endurance   = state.endurance
    state.endurance = max(0.0, state.endurance - burn)

    # Phase II transition narrative - fires exactly once per fight per warrior.
    if not state.phase2_entered and old_endurance > phase2 >= state.endurance:
        state.phase2_entered = True
        w = warrior
        if strategy.style in _AGGRESSIVE_STYLES:
            lines.append(
                f"{w.name.upper()} is EXHAUSTED - pushing on sheer aggression, "
                f"{w.gender_subject} attack form is starting to crumble!"
            )
        else:
            lines.append(
                f"{w.name.upper()} finds a SECOND WIND - fatigue narrows "
                f"{w.gender_possessive} focus into cold, efficient precision!"
            )

    # Anxiously-awaits drain on foe
    if props.anxiously_awaits and strategy.activity < 6:
        foe.endurance = max(0.0, foe.endurance - (6 - strategy.activity) * 0.5)
        if random.random() < 0.20:
            ln = N.anxious_line(warrior.name, foe.warrior.name)
            if ln:
                lines.append(ln)

    # Intimidation drain on foe
    if props.intimidate and strategy.activity >= 5:
        drain = (strategy.activity - 4) * 1.0
        foe.endurance = max(0.0, foe.endurance - drain)
        ln = N.intimidate_line(warrior.name, foe.warrior.name)
        if ln:
            lines.append(ln)

    # Fatigue narrative (proportional thresholds)
    phase2 = warrior.max_endurance * 0.25
    _is_aggressive = strategy.style in _AGGRESSIVE_STYLES
    if state.endurance < phase2 and random.random() < 0.40:
        lines.append(N.fatigue_line(warrior.name, warrior.gender, True, _is_aggressive))
    elif state.endurance < warrior.max_endurance * 0.50 and random.random() < 0.20:
        lines.append(N.fatigue_line(warrior.name, warrior.gender, False))

    return lines, burn


# ---------------------------------------------------------------------------
# APM
# ---------------------------------------------------------------------------

def _calc_apm(warrior: Warrior, strategy: Strategy, state: _CState) -> int:
    dex = get_effective_dex_for_race(
        warrior.dexterity,
        warrior.armor or "None",
        warrior.helm or "None",
        warrior.race.name)
    wpn  = warrior.primary_weapon.lower().replace(" ", "_").replace("&", "and")
    base = 3.0
    base += max(0.0, (dex - 10)) * 0.20
    base += max(0.0, (warrior.intelligence - 10)) * 0.10
    base += strategy.activity * 0.25
    base += warrior.skills.get(wpn, 0) * 0.20
    r    = warrior.race.modifiers
    base += r.attack_rate_bonus * 0.25 - r.attack_rate_penalty * 0.25
    base += get_style_props(strategy.style).apm_modifier

    # Lizardfolk heavy armor attack rate penalty (percentage-based)
    if warrior.race.name == "Lizardfolk":
        attack_pct = get_lizardfolk_armor_penalties(warrior.armor or "None")["attack_pct"]
        if attack_pct > 0:
            base *= (1.0 - attack_pct)

    # Heavy weapon penalty for Goblins & Tabaxi
    if r.heavy_weapon_penalty:
        try:
            weapon = get_weapon(warrior.primary_weapon)
            
            # Apply under-strength weight penalty to APM (skip for Tabaxi with spears)
            effective_str = get_effective_strength_for_weapons(warrior)
            two_handed_use = (warrior.secondary_weapon == "Open Hand" and weapon.two_hand)
            if not (r.spear_exception and weapon.category == "Polearm/Spear"):
                weight_penalty = strength_penalty(weapon.weight, effective_str, two_handed_use)
                if weight_penalty > 0:
                    base *= (1.0 - weight_penalty)

            two_handed = (warrior.secondary_weapon == "Open Hand" and weapon.two_hand)

            # Check if weapon is heavy (weight 4.0+) or two-handed
            is_heavy = weapon.weight >= 4.0 or (weapon.two_hand and two_handed)

            # Tabaxi get an exception for spears
            if is_heavy and not (r.spear_exception and weapon.category == "Polearm/Spear"):
                base -= 3 * 0.25  # -3 attack rate penalty equiv
        except ValueError:
            pass

    _phase2 = warrior.max_endurance * 0.25
    if state.endurance < _phase2:
        base -= (_phase2 - state.endurance) / max(1.0, _phase2) * 1.5
    if state.is_on_ground:
        base *= 0.5

    # Under-strength armor penalty to APM
    if state.armor_penalty > 0:
        base *= (1.0 - state.armor_penalty)

    # Warrior APM calculated, now combine with weapon APM
    warrior_apm = max(1, min(10, int(round(base))))

    # Get weapon APM and combine using minimum
    try:
        weapon = get_weapon(warrior.primary_weapon)
        weapon_apm = weapon.apm
        # Final APM is the minimum of warrior and weapon APM
        final_apm = min(warrior_apm, weapon_apm)
        return final_apm
    except ValueError:
        # If weapon not found, just return warrior APM
        return warrior_apm


# ---------------------------------------------------------------------------
# REFEREE INTERVENTION NARRATIVE POOLS
# ---------------------------------------------------------------------------

_REF_STONE_EVENTS = [
    ("The Ref hurls a large rock at {n}",
     "The rock connects with {n}'s temple, {n} staggers, eyes glazed."),
    ("The Ref scoops up a fist-sized stone and flings it at {n}",
     "It cracks hard against {n}'s ribs. {n} doubles over with a grunt."),
    ("The Ref hurls a jagged chunk of stone at {n}",
     "It opens a gash above {n}'s eye, {n} blinks through the blood, vision blurring."),
    ("The Ref seizes a heavy stone and hurls it at {n}",
     "The stone thuds into {n}'s chest. {n} gasps, the air driven from their lungs."),
    ("The Ref flings a sharp-edged rock at {n}",
     "It catches {n} across the shoulder, {n} winces and nearly drops their guard."),
    ("The Ref grabs a handful of gravel and hurls it straight at {n}'s face",
     "{n} recoils, blinded for a moment, eyes streaming."),
    ("The Ref hurls a stone at the back of {n}'s head",
     "{n} lurches forward, stumbling to keep their footing."),
    ("The Ref snatches up a loose cobble and sends it spinning at {n}",
     "It clips {n} across the jaw. {n} spits blood and shakes their head."),
]

_REF_WEAPON_EVENTS = [
    ("The Ref snatches up a length of chain and lashes it hard across {n}'s back",
     "{n} arches in agony, a ragged cry escaping them."),
    ("The Ref grabs a discarded wooden staff and drives it into {n}'s ribs",
     "The crack of wood on bone rings out, {n} bends double, wheezing."),
    ("The Ref seizes a blunted club and crashes it across {n}'s shoulders",
     "{n} staggers forward, knees buckling under the blow."),
    ("The Ref picks up a short iron rod and swings it hard into {n}'s thigh",
     "{n} stumbles badly, leg trembling, nearly losing their footing."),
    ("The Ref grabs a training sword and slaps the flat of it hard across {n}'s back",
     "The smack echoes across the pit, {n} flinches and lurches forward."),
]

_REF_FOLLOWUP_EVENTS = [
    ("Still unsatisfied, the Ref hurls another stone at {n}",
     "It clips {n} across the ear. {n} is visibly shaken."),
    ("The Ref shouts at {n} to fight, then flings a second stone",
     "The stone drives into {n}'s ribs. The crowd jeers."),
    ("The Ref storms forward and drives the butt of a spear into {n}'s back",
     "{n} pitches forward with a cry, barely keeping their feet."),
    ("Furious with {n}'s passivity, the Ref heaves another stone",
     "It strikes {n} hard in the kidney. {n} nearly goes down."),
    ("The crowd howls as the Ref hurls a second stone at {n}",
     "It catches {n} glancing across the jaw. {n} spits blood and staggers."),
]


# ---------------------------------------------------------------------------
# COMBAT ENGINE
# ---------------------------------------------------------------------------

class CombatEngine:

    def __init__(
        self,
        warrior_a       : Warrior,
        warrior_b       : Warrior,
        team_a_name     : str  = "Team A",
        team_b_name     : str  = "Team B",
        manager_a_name  : str  = "Manager A",
        manager_b_name  : str  = "Manager B",
        pos_a           : int  = 1,
        pos_b           : int  = 1,
        is_monster_fight: bool = False,
        challenger_name : str  = None,
        fight_type      : str  = "standard",
        debug_logger    : Optional[CombatDebugLogger] = None,
    ):
        self.warrior_a        = warrior_a
        self.warrior_b        = warrior_b
        self.team_a_name      = team_a_name
        self.team_b_name      = team_b_name
        self.manager_a_name   = manager_a_name
        self.manager_b_name   = manager_b_name
        self.pos_a            = pos_a
        self.pos_b            = pos_b
        self.is_monster_fight = is_monster_fight
        self.challenger_name  = challenger_name
        self.fight_type       = fight_type
        self.debug_logger     = debug_logger

        self.state_a = _CState(warrior=warrior_a, current_hp=warrior_a.max_hp, endurance=float(warrior_a.max_endurance))
        self.state_b = _CState(warrior=warrior_b, current_hp=warrior_b.max_hp, endurance=float(warrior_b.max_endurance))

        # Calculate overencumbrance penalties
        for st in (self.state_a, self.state_b):
            is_dw = st.warrior.race.name == "Dwarf"
            # Body armor check
            p_body = armor_penalty_factor(get_armor(st.warrior.armor).weight, st.warrior.strength, is_dw, False)
            # Helm check
            p_helm = armor_penalty_factor(get_armor(st.warrior.helm).weight, st.warrior.strength, is_dw, True)
            # Take the worst penalty
            st.armor_penalty = max(p_body, p_helm)

        if warrior_a.strategies:
            self.state_a.active_strategy  = warrior_a.strategies[-1]
            self.state_a.active_strat_idx = len(warrior_a.strategies)
        if warrior_b.strategies:
            self.state_b.active_strategy  = warrior_b.strategies[-1]
            self.state_b.active_strat_idx = len(warrior_b.strategies)

        self._lines: List[str] = []
        self._prev_attacks_a: int = 0
        self._prev_attacks_b: int = 0
        self._used_adv_phrases: set = set()
        self._last_adv_tier: str = "even"
        self._last_adv_winner: str = ""
        self._debug_action_counter: int = 0

    # =========================================================================
    # STRATEGY RE-EVALUATION (MID-MINUTE)
    # =========================================================================

    def _check_and_switch_strategies(self, as_: _CState, ds_: _CState, minute: int):
        # Check attacker's strategy
        fs_a = as_.to_fighter_state()
        fs_b = ds_.to_fighter_state() # Foe state for attacker
        new_strat_a, new_idx_a = evaluate_triggers(as_.warrior.strategies, fs_a, fs_b, minute)
        if new_idx_a != as_.active_strat_idx:
            self._emit(N.strategy_switch_line(as_.warrior.name, new_idx_a))
            if self.debug_logger:
                self.debug_logger.log_strategy_switch(as_.warrior.name, as_.active_strat_idx, new_idx_a)
            as_.active_strategy = new_strat_a
            as_.active_strat_idx = new_idx_a

        # Check defender's strategy
        fs_b_for_def = ds_.to_fighter_state()
        fs_a_for_def = as_.to_fighter_state() # Foe state for defender
        new_strat_b, new_idx_b = evaluate_triggers(ds_.warrior.strategies, fs_b_for_def, fs_a_for_def, minute)
        if new_idx_b != ds_.active_strat_idx:
            self._emit(N.strategy_switch_line(ds_.warrior.name, new_idx_b))
            if self.debug_logger:
                self.debug_logger.log_strategy_switch(ds_.warrior.name, ds_.active_strat_idx, new_idx_b)
            ds_.active_strategy = new_strat_b
            ds_.active_strat_idx = new_idx_b

    def _check_defender_strategy_only(self, ds_: _CState, as_: _CState, minute: int):
        """
        Check only the defender's strategy after they take damage.
        The attacker's strategy should not be re-evaluated when they deal damage,
        only when they themselves take damage.
        """
        # Check defender's strategy
        fs_defender = ds_.to_fighter_state()
        fs_attacker = as_.to_fighter_state()  # Foe state for defender
        new_strat, new_idx = evaluate_triggers(ds_.warrior.strategies, fs_defender, fs_attacker, minute)
        if new_idx != ds_.active_strat_idx:
            self._emit(N.strategy_switch_line(ds_.warrior.name, new_idx))
            if self.debug_logger:
                self.debug_logger.log_strategy_switch(ds_.warrior.name, ds_.active_strat_idx, new_idx)
            ds_.active_strategy = new_strat
            ds_.active_strat_idx = new_idx

    # =========================================================================
    # MAIN LOOP
    # =========================================================================

    def resolve_fight(self) -> FightResult:
        if self.debug_logger:
            self.debug_logger.log_header(
                self.warrior_a, self.warrior_b,
                self.team_a_name, self.team_b_name,
                self.manager_a_name, self.manager_b_name,
            )

        self._lines.append(N.build_fight_header(
            self.warrior_a, self.warrior_b,
            self.team_a_name, self.team_b_name,
            self.manager_a_name, self.manager_b_name,
            self.pos_a, self.pos_b,
            challenger_name=self.challenger_name,
        ))
        self._lines.append("")

        # Challenge flavor line - shown under the header but before action starts
        challenge_line = N.get_challenge_flavor_line(
            self.warrior_a.name, self.warrior_b.name,
            self.challenger_name, self.fight_type
        )
        if challenge_line:
            self._emit(challenge_line)
            self._emit("")

        minute = 0
        result = None
        # PRE hesitation check: high-presence warrior may cause opponent to lose minute 1
        self._apply_presence_hesitation()
        while True:
            minute += 1
            # Referee intervention: occasional from minute 9 (not every minute).
            # Fires ~40% of the time so it's an event, not the fight's engine.
            if minute >= 9 and random.random() < 0.40:
                self._throw_stones(minute)
            result  = self._run_minute(minute)
            if result:
                break
            # 30-minute limit: judge awards decision, but NOT in monster fights,
            # which must always end in death (no time limit, no mercy).
            if minute >= 30 and not self.is_monster_fight:
                pct_a   = self.state_a.current_hp / max(1, self.warrior_a.max_hp)
                pct_b   = self.state_b.current_hp / max(1, self.warrior_b.max_hp)
                win_w   = self.warrior_a if pct_a >= pct_b else self.warrior_b
                los_w   = self.warrior_b if pct_a >= pct_b else self.warrior_a
                self._emit("")
                self._emit(f"The Blood Master calls time, {win_w.name.upper()} wins on judges' decision!")
                result = self._make_result(win_w, los_w, False, minute)
                break
            # Safety valve for monster fights: after 60 minutes the monster
            # finishes it, a player warrior cannot outlast a monster forever.
            if minute >= 60 and self.is_monster_fight:
                # Monster wins; player warrior dies from exhaustion
                dw = self.state_a.warrior  # player is always warrior_a
                kw = self.state_b.warrior
                dw.is_dead = True
                self._emit("")
                self._emit(f"{dw.name.upper()} collapses from sheer exhaustion, the monster is relentless!")
                self._emit(N.death_line(dw.name, dw.gender))
                self._emit(""); self._emit(N.victory_line(kw.name, dw.name))
                result = self._make_result(kw, dw, True, minute, exhaustion_end=True)
                break

        training = {}
        self._emit("")   # blank line between fight outcome and training block
        for w, opp, is_opp, pos_key in [
            (self.warrior_a, self.warrior_b, False, "warrior_a"),
            (self.warrior_b, self.warrior_a, True,  "warrior_b"),
        ]:
            # Dead warriors do not train, they're carried out on a shield.
            # NPC opponents (peasants, monsters) have no persistent stats and
            # never train - skip their line entirely.
            # Deliberately leave the key ABSENT (not set to []) so that
            # _make_mirror_narrative can distinguish "died, no line emitted"
            # from "alive but trained in nothing, 'nothing' line emitted".
            if result.loser_died and result.loser is w:
                continue
            if is_opp and self.fight_type in ("peasant", "monster"):
                continue
            if self.debug_logger:
                res, _detail = self._apply_training_verbose(w, opponent=opp)
                self.debug_logger.log_training(w.name, _detail)
            else:
                res = self._apply_training(w, opponent=opp)
            # Key by position ("warrior_a"/"warrior_b") to avoid collision when
            # both fighters share the same name.  Callers that need the training
            # list for warrior_a (always the player warrior) use "warrior_a".
            training[pos_key] = res
            self._emit(N.training_summary(w.name, res, is_opponent=is_opp))

        result.training_results = training
        result.narrative        = "\n".join(self._lines)

        if self.debug_logger and result.winner and result.loser:
            self.debug_logger.log_result(
                result.winner.name, result.loser.name,
                result.loser_died, result.minutes_elapsed,
                result.winner_hp_pct, result.loser_hp_pct,
            )
        return result

    # =========================================================================
    # SINGLE MINUTE
    # =========================================================================

    # =========================================================================
    # RESULT BUILDER
    # =========================================================================

    def _make_result(self, winner: Warrior, loser: Warrior,
                     loser_died: bool, minutes_elapsed: int,
                     exhaustion_end: bool = False) -> FightResult:
        """Build a FightResult populated with per-fighter combat metrics."""
        if winner is self.warrior_a:
            ws, ls = self.state_a, self.state_b
        else:
            ws, ls = self.state_b, self.state_a
        return FightResult(
            winner=winner,
            loser=loser,
            loser_died=loser_died,
            minutes_elapsed=minutes_elapsed,
            narrative="\n".join(self._lines),
            winner_hp_pct=max(0.0, ws.current_hp / max(1, winner.max_hp)),
            loser_hp_pct=max(0.0, ls.current_hp / max(1, loser.max_hp)),
            winner_knockdowns=ws.knockdowns_dealt,
            loser_knockdowns=ls.knockdowns_dealt,
            winner_near_kills=ws.near_kills_dealt,
            loser_near_kills=ls.near_kills_dealt,
            exhaustion_end=exhaustion_end,
            winner_end_pct=max(0.0, ws.endurance / max(1, winner.max_endurance)),
            loser_end_pct=max(0.0, ls.endurance / max(1, loser.max_endurance)),
        )

    # =========================================================================
    # MINUTE ADVANTAGE
    # =========================================================================

    _END_BRINK_THRESHOLD = 0.25   # fraction of max_endurance; below this = potential exhaustion brink

    def _calc_minute_advantage(self) -> tuple:
        """
        Returns (tier, winner_name, loser_name) describing the current fight state.

        tier is one of: "even", "slight", "clear", "dominating", "brink", "brink_exhaustion"
        winner_name / loser_name are empty strings when tier == "even".
        """
        hp_a = self.state_a.current_hp
        hp_b = self.state_b.current_hp
        end_a = self.state_a.endurance
        end_b = self.state_b.endurance

        total_hp = max(1, hp_a + hp_b)
        hp_ratio = hp_a / total_hp   # 0–1; > 0.5 means warrior_a leads

        # Small endurance nudge (max ±0.08 shift on the score), normalized by max_endurance
        max_end_a = max(1, self.state_a.warrior.max_endurance)
        max_end_b = max(1, self.state_b.warrior.max_endurance)
        end_adj = (end_a / max_end_a - end_b / max_end_b) * 0.08
        score = hp_ratio + end_adj
        score = max(0.0, min(1.0, score))

        if score >= 0.5:
            winner, loser = self.warrior_a, self.warrior_b
            winner_state, loser_state = self.state_a, self.state_b
            magnitude = score
        else:
            winner, loser = self.warrior_b, self.warrior_a
            winner_state, loser_state = self.state_b, self.state_a
            magnitude = 1.0 - score

        # Endurance brink override: loser is too gassed to continue effectively
        # Only fires when the loser isn't already winning (magnitude < 0.55 means
        # the HP difference alone wouldn't call it in the winner's favour clearly)
        loser_end = loser_state.endurance
        loser_phase2 = loser_state.warrior.max_endurance * self._END_BRINK_THRESHOLD
        if loser_end <= loser_phase2 and magnitude < 0.80:
            return ("brink_exhaustion", winner.name, loser.name)

        # Map magnitude → tier using the user-specified confidence bands
        if magnitude < 0.56:
            return ("even", "", "")
        elif magnitude < 0.66:
            return ("slight", winner.name, loser.name)
        elif magnitude < 0.81:
            return ("clear", winner.name, loser.name)
        elif magnitude < 0.95:
            return ("dominating", winner.name, loser.name)
        else:
            return ("brink", winner.name, loser.name)

    def _execute_tabaxi_frenzy(self, fst: _CState, ost: _CState,
                               fstrat: Strategy, ostrat: Strategy,
                               minute: int) -> Optional[FightResult]:
        """Execute the Tabaxi frenzy burst - 3 rapid attacks with escalating defense penalties."""
        fst.frenzy_used = True
        att = fst.warrior
        dfr = ost.warrior

        self._emit(N.tabaxi_frenzy_intro_line(att.name, att.gender))

        defense_penalties = [0, 15, 30]
        _pre_frenzy = ost.current_hp

        try:
            _frenzy_wpn = get_weapon(att.primary_weapon)
            _frenzy_cat = _frenzy_wpn.category
        except ValueError:
            _frenzy_wpn = OPEN_HAND
            _frenzy_cat = "Oddball"

        for attack_num in range(3):
            def_penalty = defense_penalties[attack_num]

            # Per-attack setup line — shows each of the 3 strikes distinctly
            self._emit(N.tabaxi_frenzy_strike_line(att.name, attack_num))

            self._emit(N.attack_line(
                att.name, dfr.name, att.primary_weapon, _frenzy_cat,
                fstrat.style, fstrat.aim_point, att.gender, attacker_race=att.race.name,
            ))

            atk = _attack_roll(att, fstrat, fst)
            dfn = _defense_roll(dfr, ostrat, ost, att, fstrat.aim_point, fstrat.style,
                                is_parry=(dfr.primary_weapon != "Open Hand"))
            dfn = max(1, dfn - def_penalty)
            margin = atk - dfn

            if margin <= 0:
                self._emit(N.miss_line(att.name, att.primary_weapon))
            elif margin < 10:
                self._emit(f"   {att.name.upper()}'s strike barely grazes {dfr.name.upper()}!")
                ost.current_hp -= 3
                self._check_defender_strategy_only(ost, fst, minute)
            else:
                for ln in N.hit_line(
                    att.name, dfr.name, att.primary_weapon, _frenzy_cat,
                    fstrat.aim_point, "normal", attacker_race=att.race.name, style=fstrat.style,
                ):
                    self._emit(ln)

                dmg, _ = _calc_damage_hybrid(att, fstrat, att.primary_weapon, dfr, margin)
                dmg += _get_tabaxi_frenzy_damage_bonus(att)

                # Tabaxi frenzy uses Open Hand, determine if claw or kick
                attack_type = _get_martial_attack_type(att, dfr.name)
                is_claw = attack_type == "claw"
                self._emit(N.damage_line(dmg, dfr.max_hp, _frenzy_cat, is_claw_attack=is_claw))
                _pre_frenzy = ost.current_hp
                ost.current_hp -= dmg

                if self.debug_logger:
                    self.debug_logger.log_hp_update(dfr.name, _pre_frenzy, dmg, ost.current_hp, dfr.max_hp, "frenzy")
                self._check_defender_strategy_only(ost, fst, minute)

            if ost.current_hp <= 0:
                return self._handle_zero_hp(
                    ost, fst,
                    _pre_frenzy if margin >= 10 else ost.current_hp + 1,
                    dmg if margin >= 10 else 1,
                    minute,
                )

        return None

    def _run_minute(self, minute: int) -> Optional[FightResult]:
        self._emit(f"\nMINUTE {minute}")
        if minute == 1:
            self._emit(random.choice(N.FIGHT_OPENERS))
            for st in (self.state_a, self.state_b):
                if st.armor_penalty >= 0.10:
                    self._emit(N.overencumbered_prefight_line(st.warrior.name, st.warrior.gender))
        else:
            tier, winner_name, loser_name = self._calc_minute_advantage()
            adv_line = N.minute_status_line(
                winner_name, loser_name,
                tier, self._last_adv_tier, self._last_adv_winner,
                self._used_adv_phrases,
            )
            self._emit(adv_line)
            self._emit("")
            self._last_adv_tier = tier
            self._last_adv_winner = winner_name
            if random.random() < 0.15:
                self._emit(N.crowd_line(self.warrior_a.race.name, self.warrior_b.race.name))

        fs_a = self.state_a.to_fighter_state()
        fs_b = self.state_b.to_fighter_state()
        strat_a, idx_a = evaluate_triggers(self.warrior_a.strategies, fs_a, fs_b, minute)
        strat_b, idx_b = evaluate_triggers(self.warrior_b.strategies, fs_b, fs_a, minute)

        if idx_a != self.state_a.active_strat_idx:
            self._emit(N.strategy_switch_line(self.warrior_a.name, idx_a))
            if self.debug_logger:
                self.debug_logger.log_strategy_switch(self.warrior_a.name, self.state_a.active_strat_idx, idx_a)
        if idx_b != self.state_b.active_strat_idx:
            self._emit(N.strategy_switch_line(self.warrior_b.name, idx_b))
            if self.debug_logger:
                self.debug_logger.log_strategy_switch(self.warrior_b.name, self.state_b.active_strat_idx, idx_b)
        self.state_a.active_strategy  = strat_a;  self.state_a.active_strat_idx = idx_a
        self.state_b.active_strategy  = strat_b;  self.state_b.active_strat_idx = idx_b

        # Overencumbrance flavor
        for st in (self.state_a, self.state_b):
            if st.armor_penalty >= 0.10 and random.random() < 0.25:
                self._emit(N.overencumbered_line(st.warrior.name, st.warrior.gender))

        # --- Recovery and Ground Logic ---
        # Apply injury recovery for both warriors at the start of the minute
        self._apply_injury_recovery(self.state_a)
        self._apply_injury_recovery(self.state_b)

        for st in (self.state_a, self.state_b): # Only ground logic remains in this loop
            if st.is_weapon_dropped and not st.is_on_ground:
                # Spending an action to pick up weapon happens during the action phase,
                # but we handle the state check here.
                pass
            # Ground recovery is handled per-action inside _resolve_action so that
            # getting up costs an action rather than being free at minute start.

        apm_a = _calc_apm(self.warrior_a, strat_a, self.state_a)
        apm_b = _calc_apm(self.warrior_b, strat_b, self.state_b)

        if self.debug_logger:
            self._debug_action_counter = 0
            self.debug_logger.log_minute_start(
                minute, self.state_a, self.state_b,
                apm_a, apm_b, strat_a, strat_b,
            )

        rem_a = apm_a;  rem_b = apm_b
        act_a = act_b = crowd = 0
        old_end_a = self.state_a.endurance
        old_end_b = self.state_b.endurance

        while rem_a > 0 or rem_b > 0:
            end = self._check_fatal_injury()
            if end:
                return end

            crowd += 1
            if crowd >= 5 and random.random() < 0.35:
                self._emit(N.crowd_line(self.warrior_a.race.name, self.warrior_b.race.name))
                crowd = 0

            _dbg_init = None
            if rem_a > 0 and rem_b > 0:
                if self.debug_logger:
                    ia, ia_comps = _initiative_roll_verbose(self.warrior_a, strat_a, self.state_a)
                    ib, ib_comps = _initiative_roll_verbose(self.warrior_b, strat_b, self.state_b)
                else:
                    ia = _initiative_roll(self.warrior_a, strat_a, self.state_a)
                    ib = _initiative_roll(self.warrior_b, strat_b, self.state_b)
                    ia_comps = ib_comps = None
                if ia >= ib:
                    as_, ds_ = self.state_a, self.state_b
                    ax, dx   = strat_a, strat_b
                    rem_a -= 1;  act_a += 1
                    if self.debug_logger:
                        self._debug_action_counter += 1
                        _dbg_init = (self._debug_action_counter, ia, ia_comps, ib, ib_comps)
                else:
                    as_, ds_ = self.state_b, self.state_a
                    ax, dx   = strat_b, strat_a
                    rem_b -= 1;  act_b += 1
                    if self.debug_logger:
                        self._debug_action_counter += 1
                        _dbg_init = (self._debug_action_counter, ib, ib_comps, ia, ia_comps)
            elif rem_a > 0:
                as_, ds_, ax, dx = self.state_a, self.state_b, strat_a, strat_b
                rem_a -= 1;  act_a += 1
                if self.debug_logger:
                    self._debug_action_counter += 1
                    _dbg_init = (self._debug_action_counter, None, None, None, None)
            else:
                as_, ds_, ax, dx = self.state_b, self.state_a, strat_b, strat_a
                rem_b -= 1;  act_b += 1
                if self.debug_logger:
                    self._debug_action_counter += 1
                    _dbg_init = (self._debug_action_counter, None, None, None, None)

            # --- Req 4: Weapon Retrieval Logic ---
            # If weapon is dropped, the warrior MUST use an action to pick it up or draw backup
            if as_.is_weapon_dropped:
                as_.is_weapon_dropped = False
                if as_.warrior.backup_weapon and as_.warrior.backup_weapon != "Open Hand":
                    old_wpn = as_.warrior.primary_weapon
                    as_.warrior.primary_weapon = as_.warrior.backup_weapon
                    as_.warrior.backup_weapon = None
                    self._emit(f"{as_.warrior.name.upper()} draws {as_.warrior.gender_possessive} backup {as_.warrior.primary_weapon.lower()}!")
                elif as_.dropped_weapon_name:
                    self._emit(f"{as_.warrior.name.upper()} lunges to the sand and retrieves {as_.warrior.gender_possessive} {as_.dropped_weapon_name.lower()}!")
                    as_.warrior.primary_weapon = as_.dropped_weapon_name
                    as_.dropped_weapon_name = ""
                else:
                    # Nothing to retrieve, just spend the action adjusting
                    self._emit(f"{as_.warrior.name.upper()} adjusts {as_.warrior.gender_possessive} stance, ready to fight unarmed!")
                
                # Retrieving counts as the action for this slot
                continue

            # --- TABAXI FRENZY ABILITY ---
            # Checked every action slot for both warriors so a mid-minute threshold
            # crossing is caught on the very next slot, regardless of who won initiative
            # or whether the Tabaxi has action slots remaining.
            _frenzy_end = None
            _frenzy_triggered = False
            for fst, ost, fstrat, ostrat in (
                (as_, ds_, ax, dx),
                (ds_, as_, dx, ax),
            ):
                if not (_can_trigger_tabaxi_frenzy(fst.warrior, fst) and _is_at_frenzy_threshold(fst)):
                    continue
                frenzy_chance = _calculate_tabaxi_frenzy_trigger_chance(fst.warrior, ost.warrior)
                frenzy_roll   = random.randint(1, 100)
                frenzy_fired  = frenzy_roll <= frenzy_chance
                if self.debug_logger:
                    self.debug_logger.log_tabaxi_frenzy_check(
                        fst.warrior.name, fst.current_hp, fst.warrior.max_hp,
                        frenzy_chance, frenzy_roll, frenzy_fired,
                    )
                if frenzy_fired:
                    _frenzy_triggered = True
                    _frenzy_end = self._execute_tabaxi_frenzy(fst, ost, fstrat, ostrat, minute)
                else:
                    self._emit(N.tabaxi_frenzy_resist_line(fst.warrior.name))
                break  # only one frenzy check per slot
            if _frenzy_end:
                return _frenzy_end
            if _frenzy_triggered:
                continue  # frenzy consumed this action slot; skip normal attack

            r = self._resolve_action(as_, ds_, ax, dx, minute, _dbg_init,
                                     apm_as=(apm_a if as_ is self.state_a else apm_b))
            if r:
                return r

            # Re-sync strategy references: mid-action events (throws, weapon drops,
            # knockdowns) call _check_and_switch_strategies which updates active_strategy
            # on the state, but strat_a/strat_b are local and don't see those changes.
            # Refreshing here ensures the next action in this minute uses the correct strategy.
            strat_a = self.state_a.active_strategy
            strat_b = self.state_b.active_strategy

            for cst, ost in [(self.state_a, self.state_b), (self.state_b, self.state_a)]:
                if cst.wants_to_concede:
                    cst.hp_at_last_concede = cst.current_hp
                    r = self._attempt_concede(cst, ost, minute)
                    if r:
                        return r

        if self.debug_logger:
            self.debug_logger.log_minute_end(
                self.state_a, self.state_b,
                old_end_a, old_end_b,
                act_a, act_b, strat_a, strat_b,
            )

        self._prev_attacks_a = act_a
        self._prev_attacks_b = act_b
        return None

    # =========================================================================
    # WEAPON MANAGEMENT FOR OPPORTUNITY THROW
    # =========================================================================

    def _handle_opportunity_throw_loss(self, warrior: Warrior, state: _CState) -> Optional[str]:
        """
        When Opportunity Throw style lands a hit, the thrown weapon is lost.
        Replace primary weapon with backup (if same type), then secondary, else Open Hand.
        Return narrative message if weapon was lost, or None if still using same weapon.
        """
        current_primary = warrior.primary_weapon
        
        # Determine if weapon is throwable (not already Open Hand, and has weight)
        try:
            wpn_obj = get_weapon(current_primary)
            if wpn_obj.skill_key == "empty_hand":  # Open Hand has no weight
                return None
        except ValueError:
            return None

        # Goblin scavenger: track every thrown weapon for potential recovery
        if warrior.race.modifiers.scavenger:
            state.thrown_pool.append(current_primary)
        
        # Check if backup exists and is same weapon type as primary
        if warrior.backup_weapon and warrior.backup_weapon == current_primary:
            # Promote backup to primary, clear the old primary slot
            warrior.primary_weapon = warrior.backup_weapon
            warrior.backup_weapon = None
            return f"{warrior.name.upper()} draws {warrior.gender_possessive} backup {current_primary.lower()}!"

        # No matching backup, try secondary weapon
        if warrior.secondary_weapon != "Open Hand":
            old_secondary = warrior.secondary_weapon
            warrior.primary_weapon = warrior.secondary_weapon
            warrior.secondary_weapon = "Open Hand"
            return f"{warrior.name.upper()} switches to {warrior.gender_possessive} {old_secondary.lower()}!"
        
        # Fall back to Open Hand
        warrior.primary_weapon = "Open Hand"
        return f"{warrior.name.upper()} has no more throwables and resorts to martial combat!"

    # =========================================================================
    # GOBLIN SCAVENGER
    # =========================================================================

    def _try_goblin_scavenge(self, as_: _CState, ds_: _CState, minute: int) -> bool:
        """
        Goblin racial scavenger check.  Fires at the top of each action when the
        Goblin is in a weapon-related strategy (not OT itself).

        Alternates between a scan turn (flavor only, normal attack continues) and
        a roll turn (attempt to retrieve a throwable).  On a successful roll the
        retrieved weapon is thrown immediately as a bonus action (-8 attack) and
        the weapon is added to the thrown_pool — never kept in hand permanently.

        Returns True when the normal attack should be suppressed (retrieval fired).
        Returns False when the normal attack should proceed as usual.
        """
        att = as_.warrior

        if not att.race.modifiers.scavenger:
            return False
        if not as_.active_strategy:
            return False
        # Only when NOT currently throwing (scavenge is for when OT isn't active)
        if as_.active_strategy.style == "Opportunity Throw":
            return False
        # Only when the reason for being off OT is weapon-related, not health/fatigue
        trigger_lower = as_.active_strategy.trigger.lower()
        if not any(kw in trigger_lower for kw in ("weapon", "weaponless", "throwable")):
            return False

        # Alternate scan / roll turns
        as_.scavenger_scan_next = not as_.scavenger_scan_next
        if as_.scavenger_scan_next:
            # Scan turn: brief flavor, normal attack continues
            self._emit(random.choice([
                f"   {att.name.upper()}'s eyes sweep the arena floor between exchanges!",
                f"   Between strikes, {att.name.upper()} scans the sand for a discarded weapon!",
                f"   {att.name.upper()} glances across the pit, always watching for something useful!",
            ]))
            return False

        # ── Roll turn ────────────────────────────────────────────────────────
        base_chance = 0.55 + (att.luck - 15) * 0.01   # 41% – 70% by luck
        if random.random() > base_chance:
            # Miss: occasional flavor (30% to avoid spam)
            if random.random() < 0.30:
                self._emit(f"   {att.name.upper()} lunges for a discarded blade but pulls back; the angle is wrong!")
            return False

        # ── Success: determine weapon ─────────────────────────────────────────
        _TIER2 = ["Stiletto", "Knife", "Dagger", "Hatchet", "Bola"]
        tier1 = list(as_.thrown_pool)   # own previously-thrown weapons

        if tier1 and random.random() < 0.70:
            wpn_name = random.choice(tier1)
            as_.thrown_pool.remove(wpn_name)   # remove one copy
            self._emit(random.choice([
                f"   {att.name.upper()} darts to the sand and snatches up {att.gender_possessive} {wpn_name.lower()}!",
                f"   With a sharp eye, {att.name.upper()} reclaims {att.gender_possessive} thrown {wpn_name.lower()} from the arena floor!",
                f"   {att.name.upper()} skids to the dirt and comes up with {att.gender_possessive} {wpn_name.lower()}, back in business!",
            ]))
        elif tier1:
            # Had own weapons but RNG picked tier 2
            wpn_name = random.choice(_TIER2)
            self._emit(random.choice([
                f"   A gleam of metal catches {att.name.upper()}'s eye as {att.gender_subject} snatches a {wpn_name.lower()} from the sand!",
                f"   {att.name.upper()} spots a stray {wpn_name.lower()} near the wall and grabs it in one fluid motion!",
            ]))
        else:
            # No own weapons: smaller chance to find arena debris
            if random.random() > 0.30:
                if random.random() < 0.30:
                    self._emit(f"   {att.name.upper()} scans the floor desperately; nothing useful within reach!")
                return False
            wpn_name = random.choice(_TIER2)
            self._emit(random.choice([
                f"   {att.name.upper()} spots a {wpn_name.lower()} half-buried in the sand; the arena always provides!",
                f"   A forgotten {wpn_name.lower()} in the dirt catches {att.name.upper()}'s eye and {att.gender_subject} darts in and grabs it!",
            ]))

        # ── Bonus throw: grab-and-hurl in one motion ─────────────────────────
        # Action is consumed by retrieval; the bonus throw is the payoff.
        # The weapon is temporarily equipped, thrown at -8 accuracy, then
        # added to thrown_pool (never kept in hand).
        saved_primary = att.primary_weapon
        att.primary_weapon = wpn_name

        strat_ot = Strategy(
            trigger       = "Scavenger bonus throw",
            style         = "Opportunity Throw",
            activity      = as_.active_strategy.activity,
            aim_point     = as_.active_strategy.aim_point,
            defense_point = as_.active_strategy.defense_point,
        )

        self._emit(random.choice([
            f"   In the same motion, {att.name.upper()} hurls the {wpn_name.lower()} with deadly intent!",
            f"   Without breaking stride, {att.name.upper()} sends the {wpn_name.lower()} flying across the pit!",
            f"   The grab becomes a throw in one explosive burst of movement!",
        ]))

        atk = _attack_roll(att, strat_ot, as_) - 8   # hurried throw penalty
        dfs = _defense_roll(ds_.warrior, ds_.active_strategy, ds_,
                            att, aim_point=strat_ot.aim_point,
                            atk_style="Opportunity Throw", is_parry=False)

        if atk > dfs:
            margin = atk - dfs
            dmg, cat = _calc_damage_hybrid(att, strat_ot, wpn_name, ds_.warrior, margin)
            if att.race.modifiers.thrown_mastery:
                dmg += 4
            # Only use claw descriptions if this is an Open Hand throw (unlikely but possible)
            attack_type = _get_martial_attack_type(att, ds_.warrior.name)
            is_claw = attack_type == "claw"
            self._emit(N.damage_line(dmg, ds_.warrior.max_hp, cat, is_claw_attack=is_claw))
            prev_hp        = ds_.current_hp
            ds_.current_hp -= dmg
            result = self._handle_zero_hp(ds_, as_, prev_hp, dmg, minute)
            if result:
                att.primary_weapon = saved_primary
                return True   # fight ended
        else:
            self._emit(random.choice([
                f"   The hurried throw flies wide and {ds_.warrior.name.upper()} barely flinches!",
                f"   The desperate hurl lacks accuracy as {ds_.warrior.name.upper()} sidesteps!",
            ]))

        # Weapon goes into pool — never back into permanent inventory
        as_.thrown_pool.append(wpn_name)
        att.primary_weapon = saved_primary

        # Strategy re-evaluates naturally next action — no forced switch
        return True   # normal attack suppressed; bonus throw was the action

    # =========================================================================
    # ACTION
    # =========================================================================

    def _resolve_action(self, as_: _CState, ds_: _CState, ax: Strategy, dx: Strategy, minute: int, _dbg_init=None, apm_as: int = 5) -> Optional[FightResult]:
        att = as_.warrior;  dfr = ds_.warrior
        wpn = att.primary_weapon;  aim = ax.aim_point

        # ── Ground Recovery: Attacker on ground ────────────────────────────
        # The warrior acting has WON the initiative. If they're on the ground,
        # they get a good chance to get up (60-80% base). Success consumes
        # the action (no attack). Failure emits a struggle line and continues
        # the attack at a heavy penalty (already baked into _attack_roll).
        if as_.is_on_ground:
            brawl_lv = att.skills.get("brawl", 0)
            acro_lv = att.skills.get("acrobatics", 0)
            # Won initiative: high recovery chance
            recovery_chance = max(60 + brawl_lv * 6, min(85, acro_lv * 15) if acro_lv > 0 else 0)
            if att.race.modifiers.acrobatic_advantage:
                recovery_chance = min(95, recovery_chance + 15)
            if random.randint(1, 100) <= recovery_chance:
                # Success: got up
                as_.is_on_ground = False
                as_.consecutive_ground = 0
                if att.race.modifiers.acrobatic_advantage:
                    self._emit(f"{att.name.upper()} springs lightly to their feet with feline agility!")
                elif acro_lv > 0 and min(85, acro_lv * 15) > 60 + brawl_lv * 6:
                    self._emit(f"{att.name.upper()} quickly rolls back to their feet with acrobatic precision!")
                else:
                    self._emit(f"{att.name.upper()} pushes off the ground and rises to their feet!")
                self._check_and_switch_strategies(as_, ds_, minute)
                return None  # action consumed by getting up; no attack
            else:
                # Failure: still on ground, but trying
                self._emit(N.ground_struggle_line(att.name, att.gender))

        # If a warrior is on Opportunity Throw strategy but their current weapon is
        # not throwable (e.g. Open Hand after running out of throwables), override
        # the style to a sensible melee fallback for this action only.  This prevents
        # "hurls his open hand at..." narrative when the fighter has nothing left to throw.
        if ax.style == "Opportunity Throw":
            try:
                _wpn_check = get_weapon(wpn)
                if not _wpn_check.throwable:
                    import copy as _copy
                    ax = _copy.copy(ax)
                    ax.style = "Martial Combat" if wpn == "Open Hand" else "Strike"
            except ValueError:
                import copy as _copy
                ax = _copy.copy(ax)
                ax.style = "Strike"

        # Goblin scavenger: attempt to retrieve a throwable weapon.
        # Fires before the normal attack; returns True if action was consumed.
        if as_.warrior.race.modifiers.scavenger:
            scav_result = self._try_goblin_scavenge(as_, ds_, minute)
            if scav_result:
                return None   # bonus throw already handled; advance to next action

        # Opportunity Throw: consume the weapon before the attack (weapon is gone regardless
        # of outcome — it's in the air). Defer the swap narrative until after the attack
        # line so the sequence reads: "throws → [draws next weapon] → result", not
        # "[draws next weapon] → throws → result".
        _weapon_thrown_away = False
        _weapon_loss_msg    = None
        if ax.style == "Opportunity Throw":
            try:
                wpn_obj = get_weapon(wpn)
                if wpn_obj.skill_key != "empty_hand":  # Only consume if throwable
                    _weapon_thrown_away = True
                    _weapon_loss_msg = self._handle_opportunity_throw_loss(att, as_)
            except ValueError:
                pass  # Invalid weapon, continue without loss

        # Check weapon/style compatibility
        is_compatible, penalty_factor = _check_weapon_style_compatibility(wpn, ax.style)

        # Use appropriate intent line (normal or awkward)
        _weak_attack_intent = not is_compatible  # awkward flavor was used - suppress "barely" on parry
        if is_compatible:
            intent = N.style_intent_line(att.name, dfr.name, ax.style, wpn, att.gender)
        else:
            intent = N.awkward_style_intent_line(att.name, dfr.name, ax.style, wpn, att.gender)

        if intent:
            self._emit(intent)

        try:    weapon = get_weapon(wpn);  cat = weapon.category
        except: weapon = OPEN_HAND;        cat = "Oddball"

        # Suppress the generic attack_line when an awkward intent already described the attempt;
        # the two lines together are redundant and the second often contradicts the first.
        if not _weak_attack_intent:
            self._emit(N.attack_line(att.name, dfr.name, wpn, cat, ax.style, aim, att.gender, attacker_race=att.race.name))

        # Defense reaction line, defender's posture before the result is known
        # Lower probability for awkward attacks - the setup already signals struggle,
        # so adding a crisp defensive read makes hits feel even more contradictory.
        _defense_intent_emitted = False
        _defense_intent_is_parry = False
        if random.random() < (0.20 if _weak_attack_intent else 0.55):
            props_dx = get_style_props(dx.style)
            _uses_parry = props_dx.parry_bonus >= props_dx.dodge_bonus
            # Disarmed warriors can only dodge, never parry
            if dfr.primary_weapon == "Open Hand":
                _uses_parry = False
            self._emit(N.defense_intent_line(dfr.name, dfr.gender, _uses_parry))
            _defense_intent_emitted = True
            _defense_intent_is_parry = _uses_parry

        # Favorite weapon flavor, fires on first attack with this weapon, win or lose
        fav_flavor = _get_favorite_weapon_flavor(att, wpn, as_)
        if fav_flavor:
            self._emit(fav_flavor)

        # --- Update attacker's endurance for this action ---
        # This needs to happen before strategy re-evaluation for fatigue triggers
        _end_lines, _self_burn = _update_endurance(as_, ax, ds_, apm_as, minute)
        for ln in _end_lines:
            self._emit(ln)
        if self.debug_logger:
            self.debug_logger.log_action_burn(as_.warrior.name, ax.style, _self_burn)

        # Re-evaluate both warriors' strategies after endurance update (fatigue triggers)
        self._check_and_switch_strategies(as_, ds_, minute)

        # --- Phase III: endurance collapse ---
        if as_.endurance <= 0:
            self._emit(f"{att.name.upper()} collapses to the sand, utterly exhausted - unable to fight on!")
            self._emit(N.victory_line(dfr.name, att.name))
            return self._make_result(dfr, att, False, minute, exhaustion_end=True)

        # --- ATTACK ROLL ---
        _style_adv = get_style_advantage(ax.style, dx.style) * 6
        _compat_pen = int((1.0 - penalty_factor) * 25) if not is_compatible else 0
        if self.debug_logger:
            _atk_base, _atk_comps = _attack_roll_verbose(att, ax, as_, foe_style=dx.style)
            atk_r = _atk_base + _style_adv - _compat_pen
        else:
            atk_r = _attack_roll(att, ax, as_, foe_style=dx.style)
            atk_r += _style_adv
            if not is_compatible:
                atk_r = int(atk_r - _compat_pen)
            _atk_base = atk_r; _atk_comps = None

        # --- DECOY FEINT (pre-attack misdirection) ---
        decoy_feint_landed = False
        if ax.style == "Decoy":
            if _attempt_feint(att, dfr, dx.style):
                decoy_feint_landed = True
                self._emit(N.decoy_feint_line(att.name, dfr.name))
            elif dx.style == "Counterstrike":
                self._emit(N.decoy_feint_read_line(att.name, dfr.name))

        # --- CALCULATED ATTACK PRECISION ---
        ca_precision_landed = False
        if ax.style == "Calculated Attack":
            ca_precision_landed = _attempt_precision_strike(att, dfr, weapon, dx.style)

        # --- DEFENSE ROLL ---
        props_d = get_style_props(dx.style)
        use_p   = props_d.parry_bonus >= props_d.dodge_bonus
        # Disarmed warriors can only dodge, never parry
        if dfr.primary_weapon == "Open Hand":
            use_p = False
        _decoy_pen_applied = DECOY_FEINT_PENALTY if decoy_feint_landed else 0
        if self.debug_logger:
            _def_base, _def_comps = _defense_roll_verbose(dfr, dx, ds_, att, aim, ax.style, is_parry=use_p)
            def_r = max(1, _def_base - _decoy_pen_applied) if decoy_feint_landed else _def_base
        else:
            def_r = _defense_roll(dfr, dx, ds_, att, aim, ax.style, is_parry=use_p)
            if decoy_feint_landed:
                def_r = max(1, def_r - DECOY_FEINT_PENALTY)
            _def_base = def_r; _def_comps = None

        margin = atk_r - def_r

        # --- LIZARDFOLK HEAVY ARMOR FLAVOR ---
        # Defensive: fires when the Lizardfolk's defense failed AND the armor
        # penalty was the deciding factor (without it they would have succeeded).
        if (margin > 0
                and dfr.race.name == "Lizardfolk"
                and dfr.armor in N._LIZARD_HEAVY_ARMORS
                and random.random() < 0.40):
            _lz_dp = get_lizardfolk_armor_penalties(dfr.armor or "None")["dodge_parry_pct"]
            if _lz_dp > 0:
                _def_without_armor = def_r / (1.0 - _lz_dp)
                if atk_r - _def_without_armor <= 0:
                    _lz_ln = N.lizard_armor_line(dfr.name, dfr.armor, defensive=True)
                    if _lz_ln:
                        self._emit(_lz_ln)

        # Offensive: fires when the Lizardfolk is the attacker, their attack
        # missed (margin <= 0), and they're wearing armor with an attack penalty.
        if (margin <= 0
                and att.race.name == "Lizardfolk"
                and att.armor in N._LIZARD_HEAVY_ARMORS
                and random.random() < 0.30):
            _lz_atk_pct = get_lizardfolk_armor_penalties(att.armor or "None")["attack_pct"]
            if _lz_atk_pct > 0:
                _lz_ln = N.lizard_armor_line(att.name, att.armor, defensive=False)
                if _lz_ln:
                    self._emit(_lz_ln)

        # --- CRITICAL FORTUNE DICE ---
        # One per action; determine whether a critical opportunity opens.
        _crit_atk_fortune = random.randint(1, 100)
        _crit_def_fortune = random.randint(1, 100)

        # --- DEBUG: log action header + rolls + margin ---
        if self.debug_logger:
            _an = _dbg_init[0] if _dbg_init else self._debug_action_counter
            _ia     = _dbg_init[1] if _dbg_init else None
            _ia_c   = _dbg_init[2] if _dbg_init else None
            _ib     = _dbg_init[3] if _dbg_init else None
            _ib_c   = _dbg_init[4] if _dbg_init else None
            self.debug_logger.log_action_start(
                _an, att.name, dfr.name, wpn, ax.style, aim,
                is_compatible, penalty_factor,
                _ia, _ia_c, _ib, _ib_c,
            )
            self.debug_logger.log_attack_roll(
                att.name, _atk_base, _atk_comps, _style_adv, _compat_pen, atk_r,
            )
            self.debug_logger.log_defense_roll(
                dfr.name, _def_comps, use_p,
                props_d.parry_bonus, props_d.dodge_bonus,
                _def_base, _decoy_pen_applied, def_r,
            )
            if margin <= 0:
                _outcome = ("MISS" if margin == 0
                            else ("PARRY" if use_p else "DODGE") + f" (margin {margin})")
            elif margin < 10:
                _outcome = f"GRAZE (margin {margin}, 3 HP)"
            else:
                _outcome = f"HIT (margin {margin})"
            self.debug_logger.log_margin(atk_r, def_r, margin, _outcome)

        if margin <= 0:
            # Critical defense: fortune roll ≥ 95 on defense side → skill contest
            _crit_def = False
            if _crit_def_fortune >= 95 and margin < 0:
                _def_skill_lv = dfr.skills.get("parry" if use_p else "dodge", 0)
                if random.randint(1, 100) + dfr.luck + _def_skill_lv * 2 >= 85:
                    _crit_def = True
                    if use_p:
                        self._emit(N.critical_parry_line(dfr.name, att.name))
                    else:
                        self._emit(N.critical_dodge_line(dfr.name, att.name))

            # Calculated Attack probe flavor - occasional line when a CA
            # probe fails to find a gap in the defender's guard.
            if (ax.style == "Calculated Attack" and not ca_precision_landed
                    and random.randint(1, 100) <= CA_PROBE_EMIT_CHANCE):
                self._emit(N.calculated_probe_line(att.name, dfr.name))
            if margin == 0:
                self._emit(N.miss_line(att.name, wpn))
            elif margin <= -30:
                if use_p:
                    barely = (-margin < 20) and not _weak_attack_intent
                    if not _crit_def:
                        self._emit(N.parry_line(dfr.name, barely=barely, defense_point_active=(dx.defense_point == aim)))
                    
                    # --- CLEAVE/BASH PARRY PENETRATION ---
                    wpn_key_std = wpn.lower().replace(" ", "_").replace("&", "and")
                    cleave_level = att.skills.get("cleave", 0) if _is_cleave_weapon(wpn_key_std) else 0
                    bash_level = att.skills.get("bash", 0) if _is_bash_weapon(wpn_key_std) else 0
                    penetration_level = max(cleave_level, bash_level)
                    
                    if penetration_level > 0:
                        penetrate_chance = penetration_level * 5  # 5% × level
                        if random.randint(1, 100) <= penetrate_chance:
                            # Parry penetrated! Apply base damage only
                            try:
                                weapon = get_weapon(wpn)
                                base_dmg = int(weapon.weight * 2.0)  # Raw weapon weight damage, no modifiers
                                ds_.current_hp -= base_dmg
                                _is_bash = bash_level >= cleave_level
                                _aim_flavor = {
                                    "head":  "skull",
                                    "chest": "chest",
                                    "legs":  "legs",
                                    "arms":  "arms",
                                    "gut":   "gut",
                                }.get(aim, "body") if aim else "body"
                                if _is_bash:
                                    _pen_line = (
                                        f"The powerful strike bashes through the parry, "
                                        f"crushing into {dfr.name.capitalize()}'s {_aim_flavor}!"
                                    )
                                else:
                                    _pen_line = (
                                        f"The powerful strike cleaves through the parry, "
                                        f"splitting into {dfr.name.capitalize()}'s {_aim_flavor}!"
                                    )
                                self._emit(_pen_line)
                                self._check_defender_strategy_only(ds_, as_, minute)  # victim reacts to HP drop
                                self._check_defender_strategy_only(as_, ds_, minute)  # attacker reacts to foe HP
                                return None
                            except ValueError:
                                pass
                    
                    # --- RIPOSTE / COUNTERSTRIKE MASTERY ---
                    riposte_level   = dfr.skills.get("riposte", 0)
                    _gnome_mastery  = dfr.race.modifiers.counterstrike_mastery
                    _cleave_reduce  = max(0, (cleave_level - 2) * 15) if cleave_level >= 3 else 0

                    if not ds_.is_on_ground:
                        if _gnome_mastery:
                            # Gnome mastery fires FIRST as an extra chance on a strong parry.
                            # 15% base (no skill required), +4% per riposte level, +6% CS style.
                            # If mastery doesn't fire, the standard paths below still run —
                            # mastery is an addition, not a replacement.
                            _cs_chance = 15 + (riposte_level * 4)
                            if dx.style == "Counterstrike":
                                _cs_chance = min(65, _cs_chance + 6)
                            _cs_chance = max(5, _cs_chance - _cleave_reduce)
                            if random.randint(1, 100) <= _cs_chance:
                                self._emit(_gnome_cs_line(dfr.name, att.name))
                                if _weapon_loss_msg: self._emit(_weapon_loss_msg)
                                return self._counterstrike(ds_, as_, dx, ax, minute)

                        # Standard riposte skill path (all races)
                        if riposte_level > 0:
                            _rip_chance = max(5, 40 + (riposte_level * 5) - _cleave_reduce)
                            if random.randint(1, 100) <= _rip_chance:
                                self._emit(N.counterstrike_line(dfr.name, att.name))
                                if _weapon_loss_msg: self._emit(_weapon_loss_msg)
                                return self._counterstrike(ds_, as_, dx, ax, minute)

                        # Counterstrike style path (all races)
                        if dx.style == "Counterstrike":
                            if random.randint(1, 100) <= 30 + dfr.skills.get("parry", 0) * 5:
                                self._emit(N.counterstrike_line(dfr.name, att.name))
                                if _weapon_loss_msg: self._emit(_weapon_loss_msg)
                                return self._counterstrike(ds_, as_, dx, ax, minute)
                else:
                    if not _crit_def:
                        self._emit(N.dodge_line(dfr.name))
            else:
                # Weak parry (margin -1 to -29) or weak dodge
                if use_p:
                    if not _crit_def:
                        self._emit(N.parry_line(dfr.name, barely=not _weak_attack_intent, defense_point_active=(dx.defense_point == aim)))

                    # Gnome counterstrike mastery: weak parries open a small window.
                    # 5% base + 2% per riposte level. No style bonus — weak parries
                    # are barely openings; only practice (riposte skill) improves them.
                    if dfr.race.modifiers.counterstrike_mastery and not ds_.is_on_ground:
                        _riposte_lv  = dfr.skills.get("riposte", 0)
                        _weak_chance = 4 + (_riposte_lv * 2)
                        if random.randint(1, 100) <= _weak_chance:
                            self._emit(_gnome_cs_line(dfr.name, att.name))
                            if _weapon_loss_msg: self._emit(_weapon_loss_msg)
                            return self._counterstrike(ds_, as_, dx, ax, minute)
                else:
                    if not _crit_def:
                        self._emit(N.dodge_line(dfr.name))

            # --- Req 4: Heavy Parry Disarm Check ---
            # If it was a parry and the attack subtotal was huge, might drop weapon.
            # Cestus and Open Hand fighters cannot be disarmed - emit numbness instead.
            if use_p and atk_r > (dfr.strength * 4):
                # Reduced base chance (8%) + disarm skill bonus (2% per level)
                disarm_chance = 8 + (att.skills.get("disarm", 0) * 2)
                if random.randint(1, 100) <= disarm_chance:
                    _unarmed = dfr.primary_weapon.lower() in ("open hand", "cestus")
                    if _unarmed:
                        self._emit(N.unarmed_impact_lines(dfr.name, dfr.gender))
                    else:
                        ds_.is_weapon_dropped = True
                        ds_.dropped_weapon_name = dfr.primary_weapon
                        dfr.primary_weapon = "Open Hand"
                        self._emit(N.weapon_drop_lines(dfr.name, ds_.dropped_weapon_name, dfr.gender, is_forceful=True))
                        self._check_defender_strategy_only(ds_, as_, minute)  # disarmed warrior reacts
                        self._check_defender_strategy_only(as_, ds_, minute)  # attacker: "your foe is weaponless"

            # --- CRITICAL DEFENSE SECONDARY EFFECTS ---
            if _crit_def:
                if use_p:
                    _unarmed_att = att.primary_weapon.lower() in ("open hand", "cestus")
                    if not _unarmed_att and not as_.is_weapon_dropped:
                        _crit_sec_roll = random.random()
                        if _crit_sec_roll < 0.04:
                            # Disarm: 4%
                            self._emit(N.critical_disarm_line(dfr.name, att.name, att.primary_weapon))
                            as_.is_weapon_dropped = True
                            as_.dropped_weapon_name = att.primary_weapon
                            att.primary_weapon = "Open Hand"
                            self._check_and_switch_strategies(as_, ds_, minute)
                        elif _crit_sec_roll < 0.055:
                            # Weapon break: 1.5% - only when defender's weapon ≥ attacker's size
                            def_wpn = dfr.secondary_weapon or dfr.primary_weapon
                            if _weapon_size_class(def_wpn) >= _weapon_size_class(att.primary_weapon):
                                self._emit(N.critical_break_line(dfr.name, att.name, att.primary_weapon))
                                as_.is_weapon_dropped = True
                                as_.dropped_weapon_name = att.primary_weapon
                                att.primary_weapon = "Open Hand"
                                self._check_and_switch_strategies(as_, ds_, minute)
                else:
                    # Critical dodge: double counterstrike at 1.5%
                    if random.random() < 0.015:
                        self._emit(N.critical_double_counter_line(dfr.name, att.name))
                        result = self._counterstrike(ds_, as_, dx, ax, minute)
                        if result:
                            return result
                        result = self._counterstrike(ds_, as_, dx, ax, minute)
                        if result:
                            return result

            # Weapon swap message: after the miss/parry/dodge result is clear
            if _weapon_loss_msg:
                self._emit(_weapon_loss_msg)

            # Primary missed/was parried - Elf may still find an opening with the off-hand
            return self._try_elf_extra_attack(as_, ds_, ax, dx, minute)

        if margin < 10:
            self._emit(f"{att.name.upper()}'s blow barely grazes {dfr.name.upper()}!")
            prev_hp_graze = ds_.current_hp
            ds_.current_hp -= 3
            if self.debug_logger:
                self.debug_logger.log_hp_update(dfr.name, prev_hp_graze, 3, ds_.current_hp, dfr.max_hp, "graze")
            self._check_defender_strategy_only(ds_, as_, minute)
            if _weapon_loss_msg:
                self._emit(_weapon_loss_msg)
            # Graze - Elf may still follow with the off-hand
            return self._try_elf_extra_attack(as_, ds_, ax, dx, minute)

        precision = "precise" if margin >= 50 else ("barely" if margin < 20 else "normal")

        # --- CRITICAL / SIGNATURE HIT ---
        wpn_key_sig   = wpn.lower().replace(" ", "_").replace("&", "and")
        wpn_skill_lvl = att.skills.get(wpn_key_sig, 0)
        sig = None
        if wpn_skill_lvl >= 5 and random.random() < 0.25 and not ca_precision_landed:
            sig = N.signature_line(att.name, wpn)

        # Critical hit: fortune roll ≥ 95 on attack → skill contest
        _crit_hit = False
        if _crit_atk_fortune >= 95 and not ca_precision_landed:
            if random.randint(1, 100) + att.luck + wpn_skill_lvl * 2 >= 85:
                _crit_hit = True

        # When a defense intent was shown but the attack still lands, bridge the gap
        # so the narrative doesn't jump from "raises guard" directly to the hit.
        if _defense_intent_emitted:
            self._emit(N.defense_fail_line(dfr.name, dfr.gender, _defense_intent_is_parry))

        if _crit_hit:
            _dmg_type = N.get_damage_type(wpn_key_sig)
            self._emit(N.critical_hit_line(att.name, att.gender, dfr.name, wpn, _dmg_type))
        elif ca_precision_landed:
            self._emit(N.calculated_precision_line(att.name, dfr.name, wpn, aim, att.gender))
        elif sig:
            self._emit(sig)
        else:
            for ln in N.hit_line(att.name, dfr.name, wpn, cat, aim, precision, attacker_race=att.race.name, style=ax.style):
                self._emit(ln)

        _pbypass = CA_PRECISION_ARMOR_BYPASS if (_crit_hit or ca_precision_landed) else 0.0
        if self.debug_logger:
            dmg, wcats, _dmg_steps = _calc_damage_verbose(
                att, ax, wpn, dfr, margin,
                precision_bypass=_pbypass, style_compat_penalty=penalty_factor,
            )
        else:
            dmg, wcats = _calc_damage_hybrid(
                att, ax, wpn, dfr, margin,
                precision_bypass=_pbypass, style_compat_penalty=penalty_factor,
            )
            _dmg_steps = None

        _sig_floor = int(dfr.max_hp * 0.12) if (sig and not _crit_hit) else None
        if _crit_hit:
            # Critical hit: 2× base damage, minimum 15% of defender's max HP
            _crit_floor = max(15, int(dfr.max_hp * 0.15))
            dmg = max(_crit_floor, dmg * 2)
        elif sig:
            dmg = max(dmg, int(dfr.max_hp * 0.12))
        _ca_bonus = CA_PRECISION_DAMAGE_BONUS if ca_precision_landed else 0
        if ca_precision_landed:
            dmg += _ca_bonus

        # Thrown mastery damage bonus: +4 on Opportunity Throw hits (Goblin racial)
        if ax.style == "Opportunity Throw" and att.race.modifiers.thrown_mastery:
            dmg += 4

        # Determine if this is a claw attack (vs kick or tail which are crushing)
        attack_type = _get_martial_attack_type(att, dfr.name)
        is_claw = attack_type == "claw"
        self._emit(N.damage_line(dmg, dfr.max_hp, cat, is_claw_attack=is_claw))

        # Weapon swap message: after damage lands, attacker draws their next weapon
        if _weapon_loss_msg:
            self._emit(_weapon_loss_msg)

        if self.debug_logger:
            self.debug_logger.log_damage(
                att.name, dfr.name, margin, _dmg_steps,
                _sig_floor, _ca_bonus, dmg,
            )
            self.debug_logger.log_hit_severity(dfr.name, dmg, dfr.max_hp)

        prev_hp        = ds_.current_hp
        ds_.current_hp -= dmg

        if self.debug_logger:
            self.debug_logger.log_hp_update(dfr.name, prev_hp, dmg, ds_.current_hp, dfr.max_hp)

        # Critical hit endurance shock: the impact disrupts the receiver's reserves
        if _crit_hit:
            ds_.endurance = max(0.0, ds_.endurance - ds_.warrior.max_endurance * 0.15)

        # --- Bleeding Wounds (slash skill) ---
        wpn_key_std = wpn.lower().replace(" ", "_").replace("&", "and")
        if _is_slash_weapon(wpn_key_std):
            slash_level = att.skills.get("slash", 0)
            if slash_level > 0:
                bleed_chance = slash_level * 5
                if random.randint(1, 100) <= bleed_chance:
                    ds_.bleeding_wounds += 1
        
        # --- Bleeding Damage ---
        if ds_.bleeding_wounds > 0 and random.randint(1, 100) <= 40:
            bleed_dmg = _apply_bleeding_damage(ds_)
            if bleed_dmg > 0:
                _pre_bleed_hp = ds_.current_hp
                ds_.current_hp -= bleed_dmg
                self._emit(f"   {dfr.name.upper()} bleeds for {bleed_dmg} damage!")
                if self.debug_logger:
                    self.debug_logger.log_bleed(
                        dfr.name, ds_.bleeding_wounds, bleed_dmg,
                        _pre_bleed_hp, ds_.current_hp, dfr.max_hp,
                    )
        
        self._check_defender_strategy_only(ds_, as_, minute)  # defender reacts to own HP drop
        self._check_defender_strategy_only(as_, ds_, minute)  # attacker reacts to updated foe HP

        # Low-HP status commentary
        hp_pct = ds_.current_hp / max(1, dfr.max_hp)
        if ds_.current_hp > 0:
            status_ln = N.low_hp_line(dfr.name, dfr.gender, hp_pct)
            if status_ln:
                self._emit(status_ln)
                
        # --- Req 2: Existing Injury Flare-up Check ---
        flare_loc = _check_injury_flare_up(dfr, ds_, dmg, aim)
        if flare_loc:
            for ln in N.injury_flare_up_lines(dfr.name, flare_loc, dfr.gender):
                self._emit(ln)
            
            # --- Req 4: Arm Injury Fumble ---
            # Cestus is strapped to the hand and cannot be fumbled loose.
            if flare_loc == "primary_arm" and dfr.primary_weapon.lower() not in ("open hand", "cestus"):
                # Level 5+ injury has scaling fumble chance on flare up
                # Lvl 5: 15%, Lvl 9: 35% (approx 5% per level above 4)
                fumble_lvl = dfr.injuries.get("primary_arm")
                if fumble_lvl >= 5:
                    fumble_chance = 10 + (fumble_lvl - 4) * 5
                    if random.randint(1, 100) <= fumble_chance:
                        ds_.is_weapon_dropped = True
                        ds_.dropped_weapon_name = dfr.primary_weapon
                        dfr.primary_weapon = "Open Hand"
                        self._emit(N.weapon_drop_lines(dfr.name, ds_.dropped_weapon_name, dfr.gender, is_fumble=True))
                        self._check_defender_strategy_only(ds_, as_, minute)  # fumbled warrior reacts
                        self._check_defender_strategy_only(as_, ds_, minute)  # attacker: "your foe is weaponless"

        # Near-kill tracking
        nk_threshold = int(dfr.max_hp * 0.20)
        if prev_hp > nk_threshold >= ds_.current_hp:
            as_.near_kills_dealt += 1

        # Entangle/trip (Bola, Heavy Whip)
        was_thrown = ax.style == "Opportunity Throw"
        try:
            weapon = get_weapon(wpn)
            entangled, entangle_msg = _check_entangle(dfr, ds_, weapon, was_thrown)
            if entangled and entangle_msg:
                self._emit(entangle_msg)
                ds_.is_on_ground = True
                as_.knockdowns_dealt += 1
                fall_dmg = random.randint(1, 3)
                _pre_fall = ds_.current_hp
                ds_.current_hp -= fall_dmg
                self._emit(f"{dfr.name.upper()} hits the ground hard!")
                if self.debug_logger:
                    self.debug_logger.log_hp_update(
                        dfr.name, _pre_fall, fall_dmg, ds_.current_hp, dfr.max_hp, "entangle fall"
                    )
                self._check_defender_strategy_only(ds_, as_, minute)  # defender now on ground
                self._check_defender_strategy_only(as_, ds_, minute)  # attacker: "your foe is on the ground"
        except ValueError:
            pass

        # Knockdown
        if self.debug_logger:
            _kd, _kd_chance, _kd_roll = _check_knockdown_verbose(dfr, ds_, dmg, wcats)
            self.debug_logger.log_knockdown(dfr.name, dmg, dfr.max_hp, wcats, _kd_chance, _kd_roll, _kd)
        else:
            _kd = _check_knockdown(dfr, ds_, dmg, wcats)
        if _kd:
            self._emit(N.knockdown_line(dfr.name, dfr.gender))
            ds_.is_on_ground = True
            as_.knockdowns_dealt += 1
            self._check_and_switch_strategies(as_, ds_, minute)

        # Perm injury
        if self.debug_logger:
            _perm_result, _perm_thresh, _perm_chance, _perm_roll = _check_perm_injury_verbose(dfr, dmg, aim)
            _perm_label = f"{_perm_result[0]} ({_perm_result[1]} level(s))" if _perm_result else None
            self.debug_logger.log_perm_injury(dfr.name, dmg, dfr.max_hp, _perm_chance, _perm_roll, _perm_label)
            perm = _perm_result
        else:
            perm = _check_perm_injury(dfr, dmg, aim)

        if perm and ds_.perm_injuries_this_fight < 2:
            loc, lvls = perm
            ds_.perm_injuries_this_fight += 1
            fatal = dfr.injuries.add(loc, lvls)
            for ln in N.perm_injury_lines(dfr.name, loc, lvls, dfr.gender):
                self._emit(ln)
            if fatal:
                self._emit(N.death_line(dfr.name, dfr.gender))
                self._emit(N.race_kill_line(att.name, att.race.name, att.gender))
                self._emit("")
                self._emit(N.victory_line(att.name, dfr.name))
                return self._make_result(att, dfr, True, minute)

        if ds_.current_hp <= 0:
            return self._handle_zero_hp(ds_, as_, prev_hp, dmg, minute)

        # --- ELF EXTRA ATTACK FROM DUAL-WIELDING ---
        end = self._try_elf_extra_attack(as_, ds_, ax, dx, minute)
        if end:
            return end

        # --- MARTIAL COMBAT EXTRA ATTACK (Halfling/Lizardfolk) ---
        # After a normal attack, Halfling/Lizardfolk may get an extra unarmed strike
        mc_extra_chance = _calculate_martial_combat_extra_attack_chance(att, dfr)
        if mc_extra_chance > 0 and random.randint(1, 100) <= mc_extra_chance:
            # Extra attack triggers - use Open Hand
            try:
                mc_weapon = get_weapon("Open Hand")
                mc_cat = mc_weapon.category
            except ValueError:
                mc_weapon = OPEN_HAND
                mc_cat = "Oddball"

            # Emit narrative for the extra attack
            if att.race.name == "Halfling":
                self._emit(N.halfling_martial_strike_line(att.name, dfr.name, att.gender))
            elif att.race.name == "Lizardfolk":
                self._emit(N.lizardfolk_martial_strike_line(att.name, dfr.name, att.gender))

            # Roll attack with Open Hand (slightly reduced accuracy)
            mc_atk = _attack_roll(att, ax, as_) - 15  # Smaller penalty than off-hand weapons
            mc_def = _defense_roll(dfr, dx, ds_, att, ax.aim_point, ax.style, is_parry=(dfr.primary_weapon != "Open Hand"))
            mc_margin = mc_atk - mc_def

            if mc_margin > 0:
                if mc_margin < 10:
                    # Graze
                    self._emit(f"{att.name.upper()}'s follow-up strike barely grazes {dfr.name.upper()}!")
                    ds_.current_hp -= 3
                    self._check_defender_strategy_only(ds_, as_, minute)
                else:
                    # Hit with Open Hand
                    mc_dmg, _ = _calc_damage_hybrid(att, ax, "Open Hand", dfr, mc_margin)
                    # Determine if claw or kick for damage description
                    attack_type = _get_martial_attack_type(att, dfr.name)
                    is_claw = attack_type == "claw"
                    self._emit(N.damage_line(mc_dmg, dfr.max_hp, mc_cat, is_claw_attack=is_claw))
                    _pre_mc = ds_.current_hp
                    ds_.current_hp -= mc_dmg
                    if self.debug_logger:
                        self.debug_logger.log_hp_update(dfr.name, _pre_mc, mc_dmg, ds_.current_hp, dfr.max_hp, "martial_extra")
                    self._check_defender_strategy_only(ds_, as_, minute)
            else:
                # Extra attack misses
                self._emit(N.miss_line(att.name, "Open Hand"))

            # Check if defender dies from extra attack
            if ds_.current_hp <= 0:
                return self._handle_zero_hp(ds_, as_, _pre_mc if mc_margin >= 10 else ds_.current_hp + 1, mc_dmg if mc_margin >= 10 else 1, minute)

        # ── Ground Recovery: Defender on ground (lost this action) ──────────
        # The defender lost the initiative for this action. If they're on the
        # ground, they get a MUCH lower chance to recover (15-25%) because they
        # were just attacked or couldn't get an action off. They'll try again
        # when they win the next initiative roll.
        if ds_.is_on_ground:
            brawl_lv = dfr.skills.get("brawl", 0)
            acro_lv = dfr.skills.get("acrobatics", 0)
            # Lost initiative: low recovery chance (being attacked/missed action)
            recovery_chance = max(15 + brawl_lv * 3, min(40, acro_lv * 8) if acro_lv > 0 else 0)
            if random.randint(1, 100) <= recovery_chance:
                # Success: got up despite the barrage
                ds_.is_on_ground = False
                ds_.consecutive_ground = 0
                self._emit(f"{dfr.name.upper()} fights through the onslaught and regains their footing!")
            else:
                # Failure: still struggling
                self._emit(N.ground_struggle_line(dfr.name, dfr.gender))

        return None

    def _try_elf_extra_attack(self, as_: _CState, ds_: _CState,
                              ax: Strategy, dx: Strategy,
                              minute: int) -> Optional[FightResult]:
        """
        Attempt the Elf dual-wield off-hand attack.  Fires regardless of whether
        the primary attack hit, missed, or grazed - the Elf plans the off-hand
        strike independently as a racial ability, not as a reward for landing.
        Returns a FightResult if the extra attack kills the defender, else None.
        """
        att = as_.warrior;  dfr = ds_.warrior
        elf_extra_chance = _calculate_elf_extra_attack_chance(att, dfr)
        if elf_extra_chance <= 0 or random.randint(1, 100) > elf_extra_chance:
            return None

        secondary_wpn = att.secondary_weapon
        try:
            sec_weapon = get_weapon(secondary_wpn)
            sec_cat = sec_weapon.category
        except ValueError:
            sec_weapon = OPEN_HAND
            sec_cat = "Oddball"

        same_weapon = att.primary_weapon.lower() == secondary_wpn.lower()
        self._emit(N.elf_dual_strike_line(att.name, dfr.name, secondary_wpn, att.gender,
                                          off_hand=same_weapon))

        _, penalty_sec = _check_weapon_style_compatibility(secondary_wpn, ax.style)
        sec_atk = _attack_roll(att, ax, as_) - 20
        sec_def = _defense_roll(dfr, dx, ds_, att, ax.aim_point, ax.style,
                                is_parry=(dfr.primary_weapon != "Open Hand"))
        sec_margin = sec_atk - sec_def

        _pre_extra = ds_.current_hp
        sec_dmg = 0
        if sec_margin <= 0:
            self._emit(N.miss_line(att.name, secondary_wpn))
        elif sec_margin < 10:
            self._emit(f"{att.name.upper()}'s follow-up blow barely grazes {dfr.name.upper()}!")
            ds_.current_hp -= 1
            self._check_defender_strategy_only(ds_, as_, minute)
        else:
            sec_dmg, _ = _calc_damage_hybrid(att, ax, secondary_wpn, dfr, sec_margin,
                                             style_compat_penalty=penalty_sec)
            # Determine if claw attack (for secondary weapon Open Hand only)
            attack_type = _get_martial_attack_type(att, dfr.name)
            is_claw = attack_type == "claw"
            self._emit(N.damage_line(sec_dmg, dfr.max_hp, sec_cat, is_claw_attack=is_claw))
            _pre_extra = ds_.current_hp
            ds_.current_hp -= sec_dmg
            if self.debug_logger:
                self.debug_logger.log_hp_update(dfr.name, _pre_extra, sec_dmg,
                                                ds_.current_hp, dfr.max_hp, "elf extra")
            self._check_defender_strategy_only(ds_, as_, minute)
            self._check_defender_strategy_only(ds_, as_, minute)

        if ds_.current_hp <= 0:
            return self._handle_zero_hp(
                ds_, as_,
                _pre_extra if sec_margin >= 10 else ds_.current_hp + 1,
                sec_dmg if sec_margin >= 10 else 1,
                minute,
            )
        return None

    # =========================================================================
    # COUNTERSTRIKE
    # =========================================================================

    def _counterstrike(self, as_: _CState, ds_: _CState, ax: Strategy, dx: Strategy, minute: int) -> Optional[FightResult]:
        att = as_.warrior;  dfr = ds_.warrior;  wpn = att.primary_weapon
        
        # Check weapon/style compatibility for counterstrike
        is_compatible, penalty_factor = _check_weapon_style_compatibility(wpn, ax.style)
        
        try:    cat = get_weapon(wpn).category
        except: cat = "Oddball"
        for ln in N.hit_line(att.name, dfr.name, wpn, cat, ax.aim_point, "precise", attacker_race=att.race.name):
            self._emit(ln)
        # Gnome counterstrike mastery: higher margin (50 vs 40) — more decisive hit.
        _cs_margin = 50 if att.race.modifiers.counterstrike_mastery else 40
        dmg, _ = _calc_damage_hybrid(att, ax, wpn, dfr, _cs_margin, style_compat_penalty=penalty_factor)
        # Determine if claw attack (for counterstrike with Open Hand only)
        attack_type = _get_martial_attack_type(att, dfr.name)
        is_claw = attack_type == "claw"
        self._emit(N.damage_line(dmg, dfr.max_hp, cat, is_claw_attack=is_claw))
        prev       = ds_.current_hp
        ds_.current_hp -= dmg

        # Near-kill tracking for counterstrike damage
        nk_threshold = int(dfr.max_hp * 0.20)
        if prev > nk_threshold >= ds_.current_hp:
            as_.near_kills_dealt += 1

        self._check_defender_strategy_only(ds_, as_, minute)

        if ds_.current_hp <= 0:
            return self._handle_zero_hp(ds_, as_, prev, dmg, minute)
        return None

    # =========================================================================
    # ZERO HP
    # =========================================================================

    def _handle_zero_hp(self, dying: _CState, killer: _CState, prev: int, dmg: int, minute: int) -> Optional[FightResult]:
        dw = dying.warrior;  kw = killer.warrior
        if self.is_monster_fight:
            dw.is_dead = True
            self._emit(f"{dw.name.upper()} collapses, the monster shows no mercy!")
            self._emit(N.death_line(dw.name, dw.gender))
            self._emit(N.race_kill_line(kw.name, kw.race.name, kw.gender))
            self._emit(""); self._emit(N.victory_line(kw.name, dw.name))
            return self._make_result(kw, dw, True, minute)
        if self.debug_logger:
            died, _dc = _death_check_verbose(prev, dmg)
            _overshoot    = _dc.get("overshoot", 0)
            _death_chance = _dc.get("death_chance", 0.0)
            self.debug_logger.log_death_check(dw.name, prev, dmg, _overshoot, _death_chance, died)
        else:
            died = _death_check(prev, dmg)
        if died:
            dw.is_dead = True
            self._emit(N.death_line(dw.name, dw.gender))
            self._emit(N.race_kill_line(kw.name, kw.race.name, kw.gender))
            self._emit(""); self._emit(N.victory_line(kw.name, dw.name))
            return self._make_result(kw, dw, True, minute)
        # Survived: concede system takes over via wants_to_concede
        return None

    # =========================================================================
    # CONCEDE
    # =========================================================================

    def _attempt_concede(self, dying: _CState, killer: _CState, minute: int) -> Optional[FightResult]:
        dw = dying.warrior;  kw = killer.warrior
        self._emit(N.appeal_line(dw.name))
        dying.concede_attempts += 1
        if self.debug_logger:
            granted, _cc = _concede_check_verbose(dw, dying, self.is_monster_fight)
            self.debug_logger.log_concede(
                dw.name,
                _cc.get("d100", 0), _cc.get("PRE_bonus", 0),
                _cc.get("luck_half", 0), _cc.get("total", 0),
                _cc.get("threshold", 0), granted,
            )
        else:
            granted = _concede_check(dw, dying, self.is_monster_fight)
        self._emit(N.mercy_result_line(dw.name, granted))
        if granted:
            self._emit(""); self._emit(N.victory_line(kw.name, dw.name))
            return self._make_result(kw, dw, False, minute)
        return None

    # =========================================================================
    # FATAL INJURY CHECK
    # =========================================================================

    def _check_fatal_injury(self, minute: int = 0) -> Optional[FightResult]:
        for d, k in [(self.state_a, self.state_b), (self.state_b, self.state_a)]:
            if d.warrior.injuries.is_fatal():
                if self.debug_logger:
                    self.debug_logger.log_fatal_injury_end(d.warrior.name, d.warrior.injuries.active_injuries())

                return self._make_result(k.warrior, d.warrior, True, minute)
        return None

    # =========================================================================
    # INJURY RECOVERY (PER-MINUTE)
    # =========================================================================

    def _apply_injury_recovery(self, state: _CState):
        """Apply injury recovery at the start of each minute."""
        if state.triggered_injuries:
            to_remove = []
            for loc, lvl in state.triggered_injuries.items():
                chance = state.warrior.intelligence + state.warrior.constitution - (lvl * 2)
                if random.randint(1, 100) <= max(10, chance):
                    to_remove.append(loc)
            for loc in to_remove:
                del state.triggered_injuries[loc]
                self._emit(f"{state.warrior.name.upper()} shakes off the pain of the {loc.replace('_',' ')} injury!")

    # =========================================================================
    # TRAINING
    # =========================================================================

    def _apply_training(self, w: Warrior, opponent: Optional[Warrior] = None) -> List[str]:
        """
        Apply training. If w is alive and has INT >= 15, there is a chance
        they pick up a 4th bonus skill observed from the opponent's combat style.
        """
        w.reset_training_session()  # Reset message tracking for this training turn
        res = []
        for sk in w.trains[:3]:
            msg = w.train_skill(sk)
            if msg:  # Only add non-empty messages
                res.append(msg)

        # INT 4th train: learn a skill from opponent
        # Chance = max(3, (intelligence - 14) * 4%), triggered when INT >= 15
        if opponent and w.intelligence >= 15:
            bonus_chance = max(3, (w.intelligence - 14) * 4)
            if random.randint(1, 100) <= bonus_chance:
                # Derive what skills the opponent actually used this fight
                candidate_skills = []
                opp_strats = opponent.strategies or []
                for s in opp_strats:
                    if s.style in ("Parry", "Counterstrike"):
                        candidate_skills.append("parry")
                    if s.style in ("Strike", "Bash", "Total Kill", "Counterstrike"):
                        candidate_skills.append("initiative")
                    if s.style in ("Dodge",):
                        candidate_skills.append("dodge")
                # Always include weapon skill and basic skills as observables
                opp_wpn = (opponent.primary_weapon or "Short Sword").lower().replace(" ","_").replace("&","and")
                candidate_skills += [opp_wpn, "dodge", "parry", "initiative", "feint"]
                # Pick one and attempt training (will show "already mastered" if at max)
                random.shuffle(candidate_skills)
                for sk in candidate_skills:
                    sk_key = sk.lower().replace(" ","_")
                    if sk_key in w.skills:
                        bonus_result = w.train_skill(sk_key)
                        # Only show successful trainings with [OBSERVED] tag (must contain "trained:")
                        # Skip "no progress" messages and empty strings
                        if bonus_result and "trained:" in bonus_result.lower():
                            res.append(f"[OBSERVED] {bonus_result}")
                        break

        w.recalculate_derived()
        return res

    def _apply_training_verbose(self, w: Warrior, opponent: Optional[Warrior] = None):
        """Verbose version of _apply_training; returns (result_strings, detail_dicts)."""
        w.reset_training_session()
        res    = []
        detail = []

        for sk in w.trains[:3]:
            msg, roll, chance = w.train_skill(sk, verbose=True)
            if msg:
                res.append(msg)
            detail.append({
                "skill":   sk,
                "roll":    roll,
                "chance":  chance,
                "success": roll > 0 and roll <= chance,
                "msg":     msg,
                "source":  "train",
            })

        # INT 4th train: chance to learn a skill from opponent
        if opponent and w.intelligence >= 15:
            bonus_chance  = max(3, (w.intelligence - 14) * 4)
            trigger_roll  = random.randint(1, 100)
            if trigger_roll <= bonus_chance:
                candidate_skills = []
                for s in (opponent.strategies or []):
                    if s.style in ("Parry", "Counterstrike"):
                        candidate_skills.append("parry")
                    if s.style in ("Strike", "Bash", "Total Kill", "Counterstrike"):
                        candidate_skills.append("initiative")
                    if s.style in ("Dodge",):
                        candidate_skills.append("dodge")
                opp_wpn = (opponent.primary_weapon or "Short Sword").lower().replace(" ", "_").replace("&", "and")
                candidate_skills += [opp_wpn, "dodge", "parry", "initiative", "feint"]
                random.shuffle(candidate_skills)
                for sk in candidate_skills:
                    sk_key = sk.lower().replace(" ", "_")
                    if sk_key in w.skills:
                        msg, roll, chance = w.train_skill(sk_key, verbose=True)
                        success = roll > 0 and roll <= chance
                        # Only show [OBSERVED] for successful trainings
                        if msg and success:
                            res.append(f"[OBSERVED] {msg}")
                        detail.append({
                            "skill":         sk_key,
                            "roll":          roll,
                            "chance":        chance,
                            "success":       success,
                            "msg":           f"[OBSERVED] {msg}" if msg and success else "",
                            "source":        "observed",
                            "trigger_roll":  trigger_roll,
                            "trigger_chance": bonus_chance,
                        })
                        break
            else:
                detail.append({
                    "skill":   "observed_learning",
                    "roll":    trigger_roll,
                    "chance":  bonus_chance,
                    "success": False,
                    "msg":     "",
                    "source":  "observed_trigger",
                })

        w.recalculate_derived()
        return res, detail

    def _apply_presence_hesitation(self):
        """
        If warrior_a has high Presence, warrior_b may hesitate at the start
        of the fight (and vice versa). The hesitation skips their first action.
        Presence 14 = 0%, 16 = 6%, 18 = 12%, 20 = 18%, 25 = 33%
        """
        for attacker_state, defender_state in [
            (self.state_a, self.state_b),
            (self.state_b, self.state_a),
        ]:
            chance = attacker_state.warrior.presence_hesitate_chance
            if chance > 0 and random.randint(1, 100) <= chance:
                defender_state.endurance = max(0.0, defender_state.endurance - 15)
                self._emit(
                    f"{attacker_state.warrior.name.upper()}'s commanding presence "
                    f"makes {defender_state.warrior.name.upper()} hesitate!"
                )
        # NOTE: Do not re-evaluate strategies at minute 0. All strategy evaluations,
        # including initial ones triggered by presence hesitation, must occur inside
        # _run_minute() so they appear within the minute block, not in the reserved
        # challenge-flavor space between the strategy table and "MINUTE 1".
        # The minute 1 evaluation will catch any initial switches.

    def _throw_stones(self, minute: int):
        """
        From minute 7 onward the referee intervenes to pressure whichever warrior
        is doing the least to end the fight, not necessarily the one losing.

        Activity score per warrior (higher = more aggressive / more likely to end it):
          + attacks made last minute  (primary driver)
          + HP advantage fraction     (winning = less urgent to act)
          - defensive style penalty   (Parry/Defend styles are passive)
          - high-HP-pct penalty       (winning comfortably and still stalling)

        The warrior with the LOWER activity score gets targeted.
        Tiebreak: the one with higher HP% (the one with less urgency to fight).

        - Damage: (minute - 6) * 2, but the Ref never kills, floor at 1 HP.
        - Follow-up throw if the target attacked ≤1 times last minute (~55% chance).
        """
        if self.is_monster_fight:
            return

        pct_a = self.state_a.current_hp / max(1, self.warrior_a.max_hp)
        pct_b = self.state_b.current_hp / max(1, self.warrior_b.max_hp)

        # Defensive styles that the Ref frowns on
        _passive_styles = {"Parry", "Defend"}

        def _activity_score(attacks: int, hp_pct: float, style: str) -> float:
            score = attacks                                  # raw attacks last minute
            score -= 1.5 if style in _passive_styles else 0 # passive style penalty
            score -= max(0.0, (hp_pct - 0.60)) * 3         # penalty for sitting on a big lead
            return score

        score_a = _activity_score(
            self._prev_attacks_a, pct_a,
            self.state_a.active_strategy.style if self.state_a.active_strategy else "Strike",
        )
        score_b = _activity_score(
            self._prev_attacks_b, pct_b,
            self.state_b.active_strategy.style if self.state_b.active_strategy else "Strike",
        )

        if score_a < score_b:
            target_state = self.state_a
        elif score_b < score_a:
            target_state = self.state_b
        else:
            # True tie: go after whoever has the bigger HP cushion (less urgency)
            target_state = self.state_a if pct_a >= pct_b else self.state_b

        dmg = (minute - 6) * 2
        n = target_state.warrior.name.upper()

        # Primary intervention, 20% chance the Ref grabs a weapon instead of a stone
        if random.random() < 0.20:
            action, effect = random.choice(_REF_WEAPON_EVENTS)
        else:
            action, effect = random.choice(_REF_STONE_EVENTS)

        target_state.current_hp = max(1, target_state.current_hp - dmg)
        self._emit("")
        self._emit(action.format(n=n))
        self._emit(effect.format(n=n))
        self._check_and_switch_strategies(self.state_a, self.state_b, minute)

        # Follow-up if the target was passive last minute (≤1 attacks)
        target_attacks = (
            self._prev_attacks_a if target_state is self.state_a
            else self._prev_attacks_b
        )
        if target_attacks <= 1 and random.random() < 0.30:
            action2, effect2 = random.choice(_REF_FOLLOWUP_EVENTS)
            target_state.current_hp = max(1, target_state.current_hp - dmg)
            self._emit(action2.format(n=n))
            self._emit(effect2.format(n=n))
            self._check_and_switch_strategies(self.state_a, self.state_b, minute)

    def _emit(self, line: str):
        self._lines.append(line)


# ---------------------------------------------------------------------------
# CONVENIENCE
# ---------------------------------------------------------------------------

def run_fight(
    warrior_a       : Warrior,
    warrior_b       : Warrior,
    team_a_name     : str  = "Team A",
    team_b_name     : str  = "Team B",
    manager_a_name  : str  = "Manager A",
    manager_b_name  : str  = "Manager B",
    is_monster_fight: bool = False,
    fight_type      : str  = "standard",
    challenger_name : str  = None,
    debug_logger    : Optional[CombatDebugLogger] = None,
    pos_a           : int  = 1,
    pos_b           : int  = 1,
) -> FightResult:
    engine = CombatEngine(
        warrior_a, warrior_b,
        team_a_name, team_b_name,
        manager_a_name, manager_b_name,
        is_monster_fight=is_monster_fight,
        challenger_name=challenger_name,
        debug_logger=debug_logger,
    )
    result = engine.resolve_fight()
    if result.winner and result.loser:
        # Only update records for player-team warriors.
        # Monsters: always show 0-0-0.  Peasants: same, they are arena fodder.
        npc_races = {"Monster", "Peasant"}
        if result.winner.race.name not in npc_races:
            result.winner.record_result("win", killed_opponent=result.loser_died)
        if result.loser.race.name not in npc_races:
            result.loser.record_result("loss")
    return result
