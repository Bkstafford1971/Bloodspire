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
#     margin  1-9:     graze (1 HP, no other effects)
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

import random
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

from warrior  import Warrior, Strategy, ATTRIBUTES
from strategy import (
    FighterState, evaluate_triggers, get_style_advantage,
    get_style_props,
)
from weapons  import get_weapon, strength_penalty, OPEN_HAND, Weapon
from armor    import (
    effective_dex, total_defense_value, is_ap_vulnerable,
    get_effective_dex_for_race, get_effective_defense_for_race,
    get_armor_attack_rate_penalty_for_race,
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
    
    # Check broader incompatibilities based on weapon category and style
    # These are thematic mismatches that aren't explicitly in weak_styles
    
    # Light weapons (weight < 2.5) with Bash/Total Kill
    if weapon.weight < 2.5 and style in ("Bash", "Total Kill"):
        return False, 0.70
    
    # Heavier weapons (weight >= 4.0) with Lunge/Calculated Attack
    if weapon.weight >= 4.0 and style in ("Lunge", "Calculated Attack"):
        return False, 0.70
    
    # Small weapons with Total Kill
    if weapon.weight < 2.0 and style == "Total Kill":
        return False, 0.65
    
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
    concede_attempts   : int     = 0
    hp_at_last_concede : int     = 9999
    knockdowns_dealt   : int     = 0   # knockdowns inflicted on opponent
    near_kills_dealt   : int     = 0   # times this warrior reduced opponent below 20% HP
    used_favorite_weapon_this_fight : bool = False  # Tracks if favorite weapon flavor already shown
    bleeding_wounds    : int     = 0   # Cumulative bleeding damage (tracked each round)

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
    dex  = get_effective_dex_for_race(warrior.dexterity, warrior.armor or "None", warrior.helm or "None", warrior.race.name)
    dex_bonus    = max(-10, min(10, (dex - 10) * 2))
    skill_bonus  = warrior.skills.get("initiative", 0) * 3
    luck_bonus   = warrior.luck
    race_init_bonus = warrior.race.modifiers.initiative_bonus
    props        = get_style_props(strategy.style)
    style_mod    = int(props.apm_modifier * 4)
    activity_mod = (strategy.activity - 5) * 2
    endurance_pen= int(max(0, (40 - state.endurance) * 0.3)) if state.endurance < 40 else 0
    if state.is_on_ground:
        return max(1, roll // 2)
    return max(1, roll + dex_bonus + skill_bonus + luck_bonus + race_init_bonus
               + style_mod + activity_mod - endurance_pen)


def _attack_roll(attacker: Warrior, strategy: Strategy, state: _CState) -> int:
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
    end_pen   = int(max(0, (30 - state.endurance) * 0.5)) if state.endurance < 30 else 0
    hp0_pen   = 30 if state.current_hp <= 0 else 0
    
    # Favorite weapon bonus: +5 to hit when using favorite weapon
    fav_bonus = 0
    if attacker.favorite_weapon and attacker.primary_weapon == attacker.favorite_weapon:
        fav_bonus = 5

    return max(1, roll + dex_b + wpn_b + luck_b + style_b + feint_b + lunge_b
               - end_pen - hp0_pen + fav_bonus)


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

    if state.endurance < 30:
        total -= int((30 - state.endurance) * 0.4)
    if state.is_on_ground:
        total -= 25
    if state.current_hp <= 0:
        total -= 30

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
    # weapon tier (< 3.5 wt — stilettos, daggers, short swords, epees) takes
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

    # Actively defensive styles get a small additional buffer — they aren't
    # guaranteed to shut down the probe, but they're harder to finesse
    if def_style in ("Parry", "Defend", "Wall of Steel", "Counterstrike"):
        chance -= 5

    chance = max(0, min(75, chance))
    return random.randint(1, 100) <= chance


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
    Ceiling = stats + weapon + race + skill + luck + specialized skill bonuses.
    Fraction = min(1.0, margin / 80.0)
    Net = max(1, ceiling * fraction - armor)
    
    style_compat_penalty: multiplier for weapon/style incompatibility (1.0 = no penalty)
    """
    try:
        weapon = get_weapon(weapon_name)
    except ValueError:
        weapon = OPEN_HAND

    two_handed = (attacker.secondary_weapon == "Open Hand" and weapon.two_hand)

    base  = weapon.weight * 2.5
    base += max(0.0, (attacker.strength - 10)) * 0.6
    if weapon.flail_bypass or weapon.category == "Flail":
        base += max(0.0, (attacker.size - 12)) * 0.4
    if two_handed or weapon.two_hand:
        base *= 1.15
    r_mod  = attacker.race.modifiers
    base  += r_mod.damage_bonus - r_mod.damage_penalty
    props  = get_style_props(atk_strategy.style)
    base  += props.damage_modifier
    base  += (5 - atk_strategy.activity) * 0.3
    wpn_key = weapon_name.lower().replace(" ", "_").replace("&", "and")
    base  += attacker.skills.get(wpn_key, 0) * 0.8
    base  += attacker.luck * 0.15
    base  *= (1.0 - strength_penalty(weapon.weight, attacker.strength, two_handed))
    
    # Heavy weapon penalty for Goblins & Tabaxi
    if r_mod.heavy_weapon_penalty:
        is_heavy = weapon.weight >= 4.0 or (weapon.two_hand and two_handed)
        if is_heavy and not (r_mod.spear_exception and weapon.category == "Polearm/Spear"):
            base *= 0.8  # -2 damage penalty equiv (20% reduction)
    
    # Apply weapon/style incompatibility penalty
    base *= style_compat_penalty
    
    # --- NEW SKILL BONUSES ---
    wpn_key_std = weapon_name.lower().replace(" ", "_").replace("&", "and")
    
    # Cleave skill bonus (+2 per level, +25% multiplier at master level 9 for cleave weapons)
    if _is_cleave_weapon(wpn_key_std):
        cleave_level = attacker.skills.get("cleave", 0)
        if cleave_level > 0:
            base += cleave_level * 2.0  # +2 damage per level
            if cleave_level == 9:
                base *= 1.25  # +25% bonus at master level
            # Reduce bonus if defender has high dodge (10% reduction per dodge point above 5)
            defender_dodge = defender.skills.get("dodge", 0)
            if defender_dodge > 5:
                dodge_reduction = (defender_dodge - 5) * 0.10
                base *= max(0.5, 1.0 - dodge_reduction)  # Cap at 50% of bonus remaining
    
    # Bash skill bonus (+2 per level, for bash weapons)
    if _is_bash_weapon(wpn_key_std):
        bash_level = attacker.skills.get("bash", 0)
        if bash_level > 0:
            base += bash_level * 2.0  # +2 damage per level
            # Bash also loses effectiveness against high dodge
            defender_dodge = defender.skills.get("dodge", 0)
            if defender_dodge > 5:
                dodge_reduction = (defender_dodge - 5) * 0.10
                base *= max(0.5, 1.0 - dodge_reduction)
    
    # Slash skill bonus (improves with weapon skill, adds bleeding chance)
    if _is_slash_weapon(wpn_key_std):
        slash_level = attacker.skills.get("slash", 0)
        if slash_level > 0:
            base += slash_level * 1.0  # +1 damage per level
            # Slash is less effective against heavy armor or parry skill
            if defender.armor and defender.armor not in ["None", "Leather", "Studded Leather", "Boiled Leather"]:
                base *= 0.85  # -15% vs heavy armor
            defender_parry = defender.skills.get("parry", 0)
            if defender_parry >= 5:
                base *= max(0.8, 1.0 - (defender_parry - 4) * 0.05)
    
    # Strike skill bonus (baseline, works with all weapons but no specialization)
    strike_level = attacker.skills.get("strike", 0)
    if strike_level > 0:
        base += strike_level * 0.8  # +0.8 damage per level (less than specialized skills)
    
    # Open Hand / Martial Combat skill bonus
    # Martial artists get substantial damage bonuses from Open Hand skill, enhanced by Brawl
    if _is_open_hand_weapon(wpn_key_std):
        open_hand_level = attacker.skills.get("open_hand", 0)
        if open_hand_level > 0:
            # Base bonus: +2.0 per level (same as Cleave/Bash for consistency)
            base += open_hand_level * 2.0
            # Master level (9) gets +20% damage multiplier for consistent fighting
            if open_hand_level == 9:
                base *= 1.20
            # Brawl skill provides an additional bonus (+0.5 per level, capped at how much it exists)
            brawl_level = attacker.skills.get("brawl", 0)
            if brawl_level > 0:
                base += brawl_level * 0.5  # +0.5 damage per brawl level
                # Master level Brawl (9) gives additional +10% multiplier for bone-deep power
                if brawl_level == 9:
                    base *= 1.10
    
    ceiling = max(3, int(base))

    fraction = max(0.10, min(1.00, margin / 55.0))
    raw      = max(1, int(ceiling * fraction))
    
    # Favorite weapon bonus: +1 damage when using favorite weapon
    if attacker.favorite_weapon and weapon_name == attacker.favorite_weapon:
        raw += 1

    armor_nm = defender.armor or "None"
    helm_nm  = defender.helm  or "None"
    defense  = get_effective_defense_for_race(armor_nm, helm_nm, defender.race.name)
    if weapon.armor_piercing and is_ap_vulnerable(armor_nm):
        defense = max(0, defense // 2)

    # Calculated Attack precision hits thread a seam in the armor, bypassing
    # a fraction of the defender's defense value for this strike only.
    if precision_bypass > 0.0:
        defense = max(0, int(defense * (1.0 - precision_bypass)))

    return max(1, raw - defense), weapon.category


# ---------------------------------------------------------------------------
# PERM INJURY
# ---------------------------------------------------------------------------

_LOCATION_POOL = [
    "head", "chest", "chest", "abdomen",
    "primary_arm", "secondary_arm",
    "primary_leg", "secondary_leg",
]


def _check_perm_injury(
    warrior   : Warrior,
    damage    : int,
    aim_point : str,
) -> Optional[Tuple[str, int]]:
    if damage < warrior.max_hp * 0.15:
        return None
    chance = max(5, min(80, int((damage / warrior.max_hp) * 100) - 5))
    if warrior.race.modifiers.fewer_perms:
        chance = int(chance * 0.85)
    if random.randint(1, 100) > chance:
        return None
    if aim_point and aim_point != "None":
        loc_map = {
            "Head":"head","Chest":"chest","Abdomen":"abdomen",
            "Primary Arm":"primary_arm","Secondary Arm":"secondary_arm",
            "Primary Leg":"primary_leg","Secondary Leg":"secondary_leg",
        }
        location = loc_map.get(aim_point, random.choice(_LOCATION_POOL))
    else:
        location = random.choice(_LOCATION_POOL)
    pct    = damage / warrior.max_hp
    levels = 3 if pct > 0.50 else (2 if pct > 0.35 else 1)
    return location, levels


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
    chance  = int((damage / max(1, warrior.max_hp)) * 80)
    if cat in ("Hammer/Mace","Flail"):  chance += 10
    if cat == "Polearm/Spear":          chance += 5
    chance -= max(0, (warrior.size - 12)) * 2
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
    state: _CState, strategy: Strategy, actions: int, foe: _CState
) -> List[str]:
    lines  = []
    props  = get_style_props(strategy.style)
    burn   = props.endurance_burn + (strategy.activity - 5) * 0.3
    
    # --- ACROBATICS ENDURANCE COST SCALING ---
    # Acrobatics is more tiring at lower levels, more efficient at higher levels
    # Level 1: 9% extra, Level 2: 8%, Level 5: 5%, Level 9: 1%
    acrobatics_level = state.warrior.skills.get("acrobatics", 0)
    if acrobatics_level > 0 and strategy.style in ["Engage & Withdraw", "Lunge"]:
        # Cost: 10% - (acrobatics_level * 1%)
        acro_endurance_cost = max(1, 10 - acrobatics_level)
        burn += acro_endurance_cost * 0.01  # Convert % to decimal
    
    state.endurance = max(0.0, min(100.0, state.endurance - burn * actions))
    if props.anxiously_awaits and strategy.activity < 6:
        foe.endurance = max(0.0, foe.endurance - (6 - strategy.activity) * 0.5)
        if random.random() < 0.20:
            ln = N.anxious_line(state.warrior.name, foe.warrior.name)
            if ln:
                lines.append(ln)
    if props.intimidate and strategy.activity >= 5:
        drain = (strategy.activity - 4) * 1.0   # 1.0 per activity level above 4 (max 5.0 at activity 9)
        foe.endurance = max(0.0, foe.endurance - drain)
        ln = N.intimidate_line(state.warrior.name, foe.warrior.name)
        if ln:
            lines.append(ln)
    if state.endurance <= 20 and random.random() < 0.40:
        lines.append(N.fatigue_line(state.warrior.name, state.warrior.gender, True))
    elif state.endurance <= 40 and random.random() < 0.20:
        lines.append(N.fatigue_line(state.warrior.name, state.warrior.gender, False))
    return lines


# ---------------------------------------------------------------------------
# APM
# ---------------------------------------------------------------------------

def _calc_apm(warrior: Warrior, strategy: Strategy, state: _CState) -> int:
    dex  = get_effective_dex_for_race(warrior.dexterity, warrior.armor or "None", warrior.helm or "None", warrior.race.name)
    wpn  = warrior.primary_weapon.lower().replace(" ", "_").replace("&", "and")
    base = 3.0
    base += max(0.0, (dex - 10)) * 0.20
    base += max(0.0, (warrior.intelligence - 10)) * 0.10
    base += strategy.activity * 0.25
    base += warrior.skills.get(wpn, 0) * 0.20
    r    = warrior.race.modifiers
    base += r.attack_rate_bonus * 0.25 - r.attack_rate_penalty * 0.25
    base += get_style_props(strategy.style).apm_modifier
    
    # Lizardfolk armor attack rate penalties
    armor_apm_penalty = get_armor_attack_rate_penalty_for_race(warrior.armor or "None", warrior.race.name)
    base -= armor_apm_penalty * 0.25
    
    # Heavy weapon penalty for Goblins & Tabaxi
    if r.heavy_weapon_penalty:
        try:
            weapon = get_weapon(warrior.primary_weapon)
            two_handed = (warrior.secondary_weapon == "Open Hand" and weapon.two_hand)
            
            # Check if weapon is heavy (weight 4.0+) or two-handed
            is_heavy = weapon.weight >= 4.0 or (weapon.two_hand and two_handed)
            
            # Tabaxi get an exception for spears
            if is_heavy and not (r.spear_exception and weapon.category == "Polearm/Spear"):
                base -= 3 * 0.25  # -3 attack rate penalty equiv
        except ValueError:
            pass
    
    if state.endurance < 40:
        base -= (40 - state.endurance) / 40 * 1.5
    if state.is_on_ground:
        base *= 0.5
    return max(1, min(10, int(round(base))))


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

        self.state_a = _CState(warrior=warrior_a, current_hp=warrior_a.max_hp, endurance=100.0)
        self.state_b = _CState(warrior=warrior_b, current_hp=warrior_b.max_hp, endurance=100.0)

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

    # =========================================================================
    # MAIN LOOP
    # =========================================================================

    def resolve_fight(self) -> FightResult:
        self._lines.append(N.build_fight_header(
            self.warrior_a, self.warrior_b,
            self.team_a_name, self.team_b_name,
            self.manager_a_name, self.manager_b_name,
            self.pos_a, self.pos_b,
            challenger_name=self.challenger_name,
        ))
        self._lines.append("")

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
                result = self._make_result(kw, dw, True, minute)
                break

        training = {}
        self._emit("")   # blank line between fight outcome and training block
        for w, opp, is_opp, pos_key in [
            (self.warrior_a, self.warrior_b, False, "warrior_a"),
            (self.warrior_b, self.warrior_a, True,  "warrior_b"),
        ]:
            # Dead warriors do not train, they're carried out on a shield
            if result.loser_died and result.loser is w:
                training[pos_key] = []
                continue
            res = self._apply_training(w, opponent=opp)
            # Key by position ("warrior_a"/"warrior_b") to avoid collision when
            # both fighters share the same name.  Callers that need the training
            # list for warrior_a (always the player warrior) use "warrior_a".
            training[pos_key] = res
            if res:
                self._emit(N.training_summary(w.name, res, is_opponent=is_opp))

        result.training_results = training
        result.narrative        = "\n".join(self._lines)
        return result

    # =========================================================================
    # SINGLE MINUTE
    # =========================================================================

    # =========================================================================
    # RESULT BUILDER
    # =========================================================================

    def _make_result(self, winner: Warrior, loser: Warrior,
                     loser_died: bool, minutes_elapsed: int) -> FightResult:
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
        )

    # =========================================================================
    # MINUTE ADVANTAGE
    # =========================================================================

    _END_BRINK_THRESHOLD = 15.0   # endurance below this = potential exhaustion brink

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

        # Small endurance nudge (max ±0.08 shift on the score)
        end_adj = (end_a - end_b) / 100.0 * 0.08
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
        if loser_end <= self._END_BRINK_THRESHOLD and magnitude < 0.80:
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

    def _run_minute(self, minute: int) -> Optional[FightResult]:
        self._emit(f"\nMINUTE {minute}")
        if minute == 1:
            self._emit(random.choice(N.FIGHT_OPENERS))
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
        if idx_b != self.state_b.active_strat_idx:
            self._emit(N.strategy_switch_line(self.warrior_b.name, idx_b))
        self.state_a.active_strategy  = strat_a;  self.state_a.active_strat_idx = idx_a
        self.state_b.active_strategy  = strat_b;  self.state_b.active_strat_idx = idx_b

        for st in (self.state_a, self.state_b):
            if st.is_on_ground:
                st.consecutive_ground += 1
                # Brawl recovery: 40% + 8% per brawl level
                brawl_recovery = 40 + st.warrior.skills.get("brawl", 0) * 8
                # Acrobatics recovery: 20% per level, capped at 85%
                acrobatics_level = st.warrior.skills.get("acrobatics", 0)
                acrobatics_recovery = min(85, acrobatics_level * 20) if acrobatics_level > 0 else 0
                # Use best recovery option available
                recovery_chance = max(brawl_recovery, acrobatics_recovery)
                
                if random.randint(1, 100) <= recovery_chance:
                    st.is_on_ground       = False
                    st.consecutive_ground = 0
                    recovery_method = "acrobatics" if acrobatics_recovery > brawl_recovery else "brawl"
                    if recovery_method == "acrobatics":
                        self._emit(f"{st.warrior.name.upper()} somersaults back to their feet with acrobatic grace!")
                    else:
                        self._emit(N.getup_line(st.warrior.name, st.warrior.gender))

        apm_a = _calc_apm(self.warrior_a, strat_a, self.state_a)
        apm_b = _calc_apm(self.warrior_b, strat_b, self.state_b)
        rem_a = apm_a;  rem_b = apm_b
        act_a = act_b = crowd = 0

        while rem_a > 0 or rem_b > 0:
            end = self._check_fatal_injury()
            if end:
                return end

            crowd += 1
            if crowd >= 5 and random.random() < 0.35:
                self._emit(N.crowd_line(self.warrior_a.race.name, self.warrior_b.race.name))
                crowd = 0

            if rem_a > 0 and rem_b > 0:
                ia = _initiative_roll(self.warrior_a, strat_a, self.state_a)
                ib = _initiative_roll(self.warrior_b, strat_b, self.state_b)
                if ia >= ib:
                    as_, ds_ = self.state_a, self.state_b
                    ax, dx   = strat_a, strat_b
                    rem_a -= 1;  act_a += 1
                else:
                    as_, ds_ = self.state_b, self.state_a
                    ax, dx   = strat_b, strat_a
                    rem_b -= 1;  act_b += 1
            elif rem_a > 0:
                as_, ds_, ax, dx = self.state_a, self.state_b, strat_a, strat_b
                rem_a -= 1;  act_a += 1
            else:
                as_, ds_, ax, dx = self.state_b, self.state_a, strat_b, strat_a
                rem_b -= 1;  act_b += 1

            r = self._resolve_action(as_, ds_, ax, dx, minute)
            if r:
                return r

            for cst, ost in [(self.state_a, self.state_b), (self.state_b, self.state_a)]:
                if cst.wants_to_concede:
                    cst.hp_at_last_concede = cst.current_hp
                    r = self._attempt_concede(cst, ost, minute)
                    if r:
                        return r

        for ln in _update_endurance(self.state_a, strat_a, act_a, self.state_b):
            self._emit(ln)
        for ln in _update_endurance(self.state_b, strat_b, act_b, self.state_a):
            self._emit(ln)
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
        
        # Check if backup exists and is same weapon type as primary
        if warrior.backup_weapon and warrior.backup_weapon == current_primary:
            # Promote backup to primary
            warrior.primary_weapon = warrior.backup_weapon
            warrior.backup_weapon = None
            return f"{warrior.name.upper()} pulls {warrior.name.lower()}'s backup {current_primary.lower()}!"
        
        # No matching backup, try secondary weapon
        if warrior.secondary_weapon != "Open Hand":
            warrior.primary_weapon = warrior.secondary_weapon
            return f"{warrior.name.upper()} switches to {warrior.name.lower()}'s {warrior.secondary_weapon.lower()}!"
        
        # Fall back to Open Hand
        warrior.primary_weapon = "Open Hand"
        return f"{warrior.name.upper()} has no more throwables and resorts to martial combat!"

    # =========================================================================
    # ACTION
    # =========================================================================

    def _resolve_action(self, as_: _CState, ds_: _CState, ax: Strategy, dx: Strategy, minute: int) -> Optional[FightResult]:
        att = as_.warrior;  dfr = ds_.warrior
        wpn = att.primary_weapon;  aim = ax.aim_point

        # Check weapon/style compatibility
        is_compatible, penalty_factor = _check_weapon_style_compatibility(wpn, ax.style)
        
        # Use appropriate intent line (normal or awkward)
        if is_compatible:
            intent = N.style_intent_line(att.name, dfr.name, ax.style, wpn, att.gender)
        else:
            intent = N.awkward_style_intent_line(att.name, dfr.name, ax.style, wpn, att.gender)
        
        if intent:
            self._emit(intent)

        try:    weapon = get_weapon(wpn);  cat = weapon.category
        except: weapon = OPEN_HAND;        cat = "Oddball"

        self._emit(N.attack_line(att.name, dfr.name, wpn, cat, ax.style, aim, att.gender, attacker_race=att.race.name))

        # Defense reaction line, defender's posture before the result is known
        if random.random() < 0.55:
            props_dx = get_style_props(dx.style)
            _uses_parry = props_dx.parry_bonus >= props_dx.dodge_bonus
            self._emit(N.defense_intent_line(dfr.name, dfr.gender, _uses_parry))

        # Favorite weapon flavor, fires on first attack with this weapon, win or lose
        fav_flavor = _get_favorite_weapon_flavor(att, wpn, as_)
        if fav_flavor:
            self._emit(fav_flavor)

        atk_r = _attack_roll(att, ax, as_)
        atk_r += get_style_advantage(ax.style, dx.style) * 6
        
        # Apply weapon/style incompatibility penalty to attack roll
        if not is_compatible:
            atk_r = int(atk_r - (1.0 - penalty_factor) * 25)  # -25 points * penalty severity

        # --- DECOY FEINT (pre-attack misdirection) ---
        # A successful feint pulls the defender's guard off the real strike,
        # imposing a flat penalty on their defense roll for this action.
        decoy_feint_landed = False
        if ax.style == "Decoy":
            if _attempt_feint(att, dfr, dx.style):
                decoy_feint_landed = True
                self._emit(N.decoy_feint_line(att.name, dfr.name))
            elif dx.style == "Counterstrike":
                self._emit(N.decoy_feint_read_line(att.name, dfr.name))

        # --- CALCULATED ATTACK PRECISION (pre-attack weak-point targeting) ---
        # On success, the attacker threads the strike through a seam in the
        # defender's armor — partial armor bypass and a small damage bonus
        # apply. Big clunky weapons cannot precision-strike at all.
        ca_precision_landed = False
        if ax.style == "Calculated Attack":
            ca_precision_landed = _attempt_precision_strike(att, dfr, weapon, dx.style)

        props_d = get_style_props(dx.style)
        use_p   = props_d.parry_bonus >= props_d.dodge_bonus
        def_r   = _defense_roll(dfr, dx, ds_, att, aim, ax.style, is_parry=use_p)
        if decoy_feint_landed:
            def_r = max(1, def_r - DECOY_FEINT_PENALTY)
        margin  = atk_r - def_r

        if margin <= 0:
            # Calculated Attack probe flavor — occasional line when a CA
            # probe fails to find a gap in the defender's guard.
            if (ax.style == "Calculated Attack" and not ca_precision_landed
                    and random.randint(1, 100) <= CA_PROBE_EMIT_CHANCE):
                self._emit(N.calculated_probe_line(att.name, dfr.name))
            if margin == 0:
                self._emit(N.miss_line(att.name, wpn))
            elif margin <= -30:
                if use_p:
                    barely = (-margin < 20)
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
                                return None
                            except ValueError:
                                pass
                    
                    # --- RIPOSTE COUNTER-ATTACK ---
                    riposte_level = dfr.skills.get("riposte", 0)
                    if riposte_level > 0 and not ds_.is_on_ground:
                        # Base 40% + 5% per level, reduced if attacker has high cleave
                        riposte_chance = 40 + (riposte_level * 5)
                        
                        if cleave_level >= 3:
                            cleave_advantage = (cleave_level - 2) * 15  # 15% reduction per cleave level above 2
                            riposte_chance = max(5, riposte_chance - cleave_advantage)
                        
                        if random.randint(1, 100) <= riposte_chance:
                            self._emit(N.counterstrike_line(dfr.name, att.name))
                            return self._counterstrike(ds_, as_, dx, ax, minute)
                    
                    if dx.style == "Counterstrike" and not ds_.is_on_ground:
                        if random.randint(1, 100) <= 30 + dfr.skills.get("parry", 0) * 5:
                            self._emit(N.counterstrike_line(dfr.name, att.name))
                            return self._counterstrike(ds_, as_, dx, ax, minute)
                else:
                    self._emit(N.dodge_line(dfr.name))
            else:
                if use_p:
                    self._emit(N.parry_line(dfr.name, barely=True, defense_point_active=(dx.defense_point == aim)))
                else:
                    self._emit(N.dodge_line(dfr.name))
            return None

        if margin < 10:
            self._emit(f"{att.name.upper()}'s blow barely grazes {dfr.name.upper()}!")
            ds_.current_hp -= 1
            return None

        precision = "precise" if margin >= 50 else ("barely" if margin < 20 else "normal")

        # --- CRITICAL / SIGNATURE HIT ---
        # Fires when weapon skill >= 5 and 25% chance rolls true.
        # Replaces the normal hit_line with a weapon-specific signature line.
        # Damage is floored at medium (12% of max HP) when the signature fires.
        # CA precision hits take priority over signature hits for this strike.
        wpn_key_sig  = wpn.lower().replace(" ", "_").replace("&", "and")
        wpn_skill_lvl = att.skills.get(wpn_key_sig, 0)
        sig = None
        if wpn_skill_lvl >= 5 and random.random() < 0.25 and not ca_precision_landed:
            sig = N.signature_line(att.name, wpn)

        if ca_precision_landed:
            self._emit(N.calculated_precision_line(att.name, dfr.name, wpn, aim))
        elif sig:
            self._emit(sig)
        else:
            for ln in N.hit_line(att.name, dfr.name, wpn, cat, aim, precision, attacker_race=att.race.name):
                self._emit(ln)

        dmg, wcats = _calc_damage_hybrid(
            att, ax, wpn, dfr, margin,
            precision_bypass=(CA_PRECISION_ARMOR_BYPASS if ca_precision_landed else 0.0),
            style_compat_penalty=penalty_factor,
        )
        if sig:
            dmg = max(dmg, int(dfr.max_hp * 0.12))  # floor at minimum medium damage
        if ca_precision_landed:
            dmg += CA_PRECISION_DAMAGE_BONUS
        self._emit(N.damage_line(dmg, dfr.max_hp, cat))

        prev_hp        = ds_.current_hp
        ds_.current_hp -= dmg

        # --- Apply Bleeding Wounds from Slash skill---
        wpn_key_std = wpn.lower().replace(" ", "_").replace("&", "and")
        if _is_slash_weapon(wpn_key_std):
            slash_level = att.skills.get("slash", 0)
            if slash_level > 0:
                # 5% chance per slash level to cause bleeding
                bleed_chance = slash_level * 5
                if random.randint(1, 100) <= bleed_chance:
                    # Add bleeding wound to accumulator (silent, hidden from player)
                    ds_.bleeding_wounds += 1

        # --- Apply Bleeding Damage each round (silent, hidden from player) ---
        if ds_.bleeding_wounds > 0 and random.randint(1, 100) <= 40:
            bleed_dmg = _apply_bleeding_damage(ds_)
            if bleed_dmg > 0:
                ds_.current_hp -= bleed_dmg

        # Low-HP status commentary
        hp_pct = ds_.current_hp / max(1, dfr.max_hp)
        if ds_.current_hp > 0:
            status_ln = N.low_hp_line(dfr.name, dfr.gender, hp_pct)
            if status_ln:
                self._emit(status_ln)

        # Near-kill tracking: attacker reduced defender through the 20% HP threshold
        nk_threshold = int(dfr.max_hp * 0.20)
        if prev_hp > nk_threshold >= ds_.current_hp:
            as_.near_kills_dealt += 1

        # Handle Opportunity Throw weapon loss
        if ax.style == "Opportunity Throw":
            weapon_loss_msg = self._handle_opportunity_throw_loss(att, as_)
            if weapon_loss_msg:
                self._emit(weapon_loss_msg)

        # Check for entangle/trip effects (Bola, Heavy Whip)
        was_thrown = ax.style == "Opportunity Throw"
        try:
            weapon = get_weapon(wpn)
            entangled, entangle_msg = _check_entangle(dfr, ds_, weapon, was_thrown)
            if entangled and entangle_msg:
                self._emit(entangle_msg)
                ds_.is_on_ground = True
                as_.knockdowns_dealt += 1
                # Extra fall damage from the entangle (1-3 HP depending on impact)
                fall_dmg = random.randint(1, 3)
                ds_.current_hp -= fall_dmg
                self._emit(f"{dfr.name.upper()} hits the ground hard!")
        except ValueError:
            pass

        if _check_knockdown(dfr, ds_, dmg, wcats):
            self._emit(N.knockdown_line(dfr.name, dfr.gender))
            ds_.is_on_ground = True
            as_.knockdowns_dealt += 1

        perm = _check_perm_injury(dfr, dmg, aim)
        if perm:
            loc, lvls = perm
            fatal     = dfr.injuries.add(loc, lvls)
            for ln in N.perm_injury_lines(dfr.name, loc, lvls, dfr.gender):
                self._emit(ln)
            if fatal:
                self._emit(N.death_line(dfr.name, dfr.gender))
                self._emit("")
                self._emit(N.victory_line(att.name, dfr.name))
                return self._make_result(att, dfr, True, minute)

        if ds_.current_hp <= 0:
            return self._handle_zero_hp(ds_, as_, prev_hp, dmg, minute)
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
        dmg, _ = _calc_damage_hybrid(att, ax, wpn, dfr, 40, style_compat_penalty=penalty_factor)
        self._emit(N.damage_line(dmg, dfr.max_hp, cat))
        prev       = ds_.current_hp
        ds_.current_hp -= dmg

        # Near-kill tracking for counterstrike damage
        nk_threshold = int(dfr.max_hp * 0.20)
        if prev > nk_threshold >= ds_.current_hp:
            as_.near_kills_dealt += 1

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
            self._emit(""); self._emit(N.victory_line(kw.name, dw.name))
            return self._make_result(kw, dw, True, minute)
        if _death_check(prev, dmg):
            dw.is_dead = True
            self._emit(N.death_line(dw.name, dw.gender))
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
        granted = _concede_check(dw, dying, self.is_monster_fight)
        self._emit(N.mercy_result_line(dw.name, granted))
        if granted:
            self._emit(""); self._emit(N.victory_line(kw.name, dw.name))
            return self._make_result(kw, dw, False, minute)
        return None

    # =========================================================================
    # FATAL INJURY CHECK
    # =========================================================================

    def _check_fatal_injury(self) -> Optional[FightResult]:
        for d, k in [(self.state_a, self.state_b), (self.state_b, self.state_a)]:
            if d.warrior.injuries.is_fatal():
                return self._make_result(k.warrior, d.warrior, True, 0)
        return None

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
                        # Show success, or mastery message. Skip empty strings (shown_max_messages duplicate)
                        if bonus_result:
                            res.append(f"[OBSERVED] {bonus_result}")
                        break

        w.recalculate_derived()
        return res

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
    challenger_name : str  = None,
) -> FightResult:
    engine = CombatEngine(
        warrior_a, warrior_b,
        team_a_name, team_b_name,
        manager_a_name, manager_b_name,
        is_monster_fight=is_monster_fight,
        challenger_name=challenger_name,
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
