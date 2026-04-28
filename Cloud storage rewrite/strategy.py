# =============================================================================
# strategy.py — BLOODSPIRE Strategy & Trigger Evaluation
# =============================================================================
# Evaluates the trigger list for a warrior each minute and returns the
# active Strategy. Implements all trigger conditions from the guide.
#
# Guide rule: "the program reads the triggers from top to bottom, so you want
# to be strategic in what order you use certain triggers."
# First matching trigger wins. If nothing matches above the default, the last
# strategy (typically trigger "Always") is used.
# =============================================================================

from dataclasses import dataclass
from typing import Optional, List
from warrior import Warrior, Strategy
from weapons import get_weapon


# ---------------------------------------------------------------------------
# FIGHTER STATE — combat snapshot passed to the trigger evaluator each minute
# ---------------------------------------------------------------------------

@dataclass
class FighterState:
    """
    Snapshot of one warrior's in-fight status at the start of a minute.
    Passed to the trigger evaluator and to the narrative engine.
    """
    warrior         : Warrior
    current_hp      : int
    max_hp          : int
    endurance       : float      # 0.0 – 100.0
    is_on_ground    : bool
    active_strategy_idx : int    # 1-indexed display number of the current strategy
    active_strategy : Strategy

    @property
    def hp_lost(self) -> int:
        return max(0, self.max_hp - self.current_hp)

    @property
    def hp_lost_pct(self) -> float:
        """Fraction of max HP that has been lost (0.0–1.0)."""
        if self.max_hp <= 0:
            return 0.0
        return self.hp_lost / self.max_hp

    @property
    def is_very_tired(self) -> bool:
        return self.endurance <= 20.0

    @property
    def is_somewhat_tired(self) -> bool:
        return self.endurance <= 40.0

    @property
    def is_slightly_tired(self) -> bool:
        return self.endurance <= 60.0

    # Legacy alias kept for backwards compatibility with old saves
    @property
    def is_tired(self) -> bool:
        return self.is_somewhat_tired

    @property
    def is_dying(self) -> bool:
        return self.current_hp <= 0

    def damage_category(self) -> str:
        """
        Classify how much damage the warrior has taken.
        APPROX thresholds derived from guide sample fight context.
        """
        pct = self.hp_lost_pct
        if pct < 0.10:
            return "none"
        elif pct < 0.30:
            return "slight"
        elif pct < 0.60:
            return "medium"
        else:
            return "heavy"


# ---------------------------------------------------------------------------
# TRIGGER HELPERS
# ---------------------------------------------------------------------------

_HEAVY_ARMOR  = {"Chain", "Half-Plate", "Full Plate"}
_MEDIUM_ARMOR = {"Cuir Boulli", "Brigandine", "Scale"}


def _armor_category(armor_name: str) -> str:
    """Return 'heavy', 'medium', or 'light' for the given armor name."""
    if armor_name in _HEAVY_ARMOR:
        return "heavy"
    if armor_name in _MEDIUM_ARMOR:
        return "medium"
    return "light"


def _weapon_count(warrior: Warrior) -> int:
    """Count non-Open-Hand weapon slots the warrior currently carries."""
    count = 0
    for wpn in (warrior.primary_weapon, warrior.secondary_weapon, warrior.backup_weapon):
        if wpn and wpn != "Open Hand":
            count += 1
    return count


def _throwable_count(warrior: Warrior) -> int:
    """Count throwable weapons currently carried by the warrior."""
    count = 0
    for wpn_name in (warrior.primary_weapon, warrior.secondary_weapon, warrior.backup_weapon):
        if not wpn_name or wpn_name == "Open Hand":
            continue
        try:
            if get_weapon(wpn_name).throwable:
                count += 1
        except ValueError:
            pass
    return count


# ---------------------------------------------------------------------------
# TRIGGER CONDITION CHECKER
# ---------------------------------------------------------------------------

def _check_trigger(
    trigger  : str,
    self_state: FighterState,
    foe_state : FighterState,
    minute    : int,
) -> bool:
    """
    Return True if the given trigger condition is currently satisfied.
    """
    t = trigger.strip()

    # Never-match sentinels
    if t in ("None", ""):
        return False

    # Always-match
    if t in ("Always", "Always (Default Loop)"):
        return True

    # --- Minute triggers ---
    if t.startswith("Minute"):
        try:
            return minute == int(t.split()[-1])
        except (ValueError, IndexError):
            return False

    # --- Self fatigue ---
    if t == "You are very tired":
        return self_state.is_very_tired
    if t == "You are somewhat tired":
        return self_state.is_somewhat_tired
    if t == "You are slightly tired":
        return self_state.is_slightly_tired
    if t == "You are tired":                       # legacy alias
        return self_state.is_somewhat_tired

    # --- Foe fatigue ---
    if t == "Your foe is very tired":
        return foe_state.is_very_tired
    if t == "Your foe is somewhat tired":
        return foe_state.is_somewhat_tired
    if t == "Your foe is slightly tired":
        return foe_state.is_slightly_tired
    if t == "Your foe is tired":                   # legacy alias
        return foe_state.is_somewhat_tired

    # --- Self damage taken ---
    if t == "You have taken heavy damage":
        return self_state.damage_category() == "heavy"
    if t == "You have taken medium damage":
        return self_state.damage_category() == "medium"
    if t == "You have taken slight damage":
        return self_state.damage_category() == "slight"
    if t == "You have taken light damage":         # legacy alias
        return self_state.damage_category() == "slight"

    # --- Foe damage taken ---
    if t == "Your foe has taken heavy damage":
        return foe_state.damage_category() == "heavy"
    if t == "Your foe has taken medium damage":
        return foe_state.damage_category() == "medium"
    if t == "Your foe has taken slight damage":
        return foe_state.damage_category() == "slight"
    if t == "Your foe has taken light damage":     # legacy alias
        return foe_state.damage_category() == "slight"

    # --- Ground state ---
    if t == "You are on the ground":
        return self_state.is_on_ground
    if t == "Your foe is on the ground":
        return foe_state.is_on_ground

    # --- Weapon state ---
    if t == "You are weaponless":
        return self_state.warrior.primary_weapon == "Open Hand" and _weapon_count(self_state.warrior) == 0
    if t == "Your foe is weaponless":
        return foe_state.warrior.primary_weapon == "Open Hand" and _weapon_count(foe_state.warrior) == 0

    if t == "You have no throwable weapons":
        return _throwable_count(self_state.warrior) == 0
    if t == "You have at least one throwable weapon":
        return _throwable_count(self_state.warrior) >= 1
    if t == "You have exactly one throwable weapon":
        return _throwable_count(self_state.warrior) == 1

    if t == "You have exactly one weapon":
        return _weapon_count(self_state.warrior) == 1
    if t == "You have exactly 2 weapons":
        return _weapon_count(self_state.warrior) == 2
    if t == "You have more than 2 weapons":
        return _weapon_count(self_state.warrior) > 2

    # --- Foe armor category ---
    foe_armor = foe_state.warrior.armor or "None"
    if t == "Your foe is wearing light armor":
        return _armor_category(foe_armor) == "light"
    if t == "Your foe is wearing medium armor":
        return _armor_category(foe_armor) == "medium"
    if t == "Your foe is wearing heavy armor":
        return _armor_category(foe_armor) == "heavy"

    # --- Challenge triggers (tracked externally; always False until implemented) ---
    if t in (
        "You challenged your foe", "Your foe challenged you",
        "You blood challenged your foe", "Your foe blood challenged you",
    ):
        return False

    # Unknown trigger — never matches (fail safe)
    return False


def evaluate_triggers(
    strategies : List[Strategy],
    self_state : FighterState,
    foe_state  : FighterState,
    minute     : int,
) -> tuple[Strategy, int]:
    """
    Evaluate a warrior's strategy list from top to bottom.
    Returns (matching_strategy, 1-indexed_position).

    Guide rule: first match wins. The last strategy typically has trigger
    "Always" as a catch-all default.
    """
    for i, strat in enumerate(strategies):
        if _check_trigger(strat.trigger, self_state, foe_state, minute):
            return strat, i + 1

    # Safety fallback — return the last strategy (should always have "Always")
    return strategies[-1], len(strategies)


# ---------------------------------------------------------------------------
# STYLE COMBAT MECHANICS TABLES
# ---------------------------------------------------------------------------
# All numeric values below are APPROX.  The guide is deliberately vague
# about which styles counter which; the specific numbers here are calibrated
# so that style choice matters but no single style is unbeatable.
#
# STYLE_COUNTER_MATRIX[atk_style][def_style] = advantage modifier
#   Positive = attacker benefits (harder to defend, more damage)
#   Negative = defender benefits (easier to defend, less damage gets through)
#   Range: -3 to +3
# ---------------------------------------------------------------------------

STYLE_COUNTER_MATRIX: dict[str, dict[str, int]] = {
    "Total Kill": {
        "Wall of Steel": -1,  # Wall handles the aggression okay
        "Lunge":         -1,  # Lunge can dodge out of the frenzy
        "Counterstrike": -2,  # CS exploits reckless attacks
        "Parry":         -2,  # Parry was built for this
        "Defend":        -1,
        "Strike":         1,  # Strike doesn't handle the ferocity
        "Slash":          1,
        "Bash":           1,
        "Calculated Attack": -1,
    },
    "Wall of Steel": {
        "Lunge":         -2,  # Guide: Lunge "counters WoS incredibly well"
        "Counterstrike": -2,  # Guide: WoS is "very vulnerable to one popular style"
        "Strike":         1,  # WoS dominates Strike
        "Bash":          -1,  # Bash can push through
        "Parry":         -1,
        "Defend":        -1,
        "Slash":          1,
        "Calculated Attack": 1,
    },
    "Lunge": {
        "Wall of Steel":  2,  # Guide: "counters 2 of the most popular styles incredibly"
        "Bash":           2,  # Second style Lunge counters incredibly
        "Parry":         -1,  # Parry holds up to Lunge
        "Sure Strike":   -1,
        "Slash":         -1,
        "Counterstrike":  1,  # Lunge can negate CS parries
    },
    "Bash": {
        "Lunge":         -2,  # Guide: "countered by two very popular styles"
        "Wall of Steel": -2,  # Second style that counters Bash
        "Strike":         1,  # Guide: "counters Strike moderately well"
        "Engage & Withdraw": 2,  # Guide: "counters E&W to devastating effect"
        "Parry":         -1,
        "Defend":         1,
        "Counterstrike":  1,
    },
    "Slash": {
        "Parry":         -1,
        "Wall of Steel": -1,
        "Strike":        -1,
        "Counterstrike": -1,
        "Calculated Attack": -1,
    },
    "Strike": {
        "Wall of Steel": -1,  # Guide: "easily countered by several popular styles"
        "Lunge":         -1,
        "Bash":          -1,
        "Counterstrike":  1,  # Guide: "can counter CS"
        "Parry":          1,
        "Defend":         1,
        "Calculated Attack": 1,  # Guide: "can counter Calc Attack"
    },
    "Engage & Withdraw": {
        "Bash":          -2,  # Guide: "countered by one of the most popular styles"
        "Total Kill":    -1,
        "Martial Combat": 2,  # Guide: "counters specialty style to devastating effect"
        "Parry":          1,
        "Defend":         1,
        "Slash":          1,
        "Sure Strike":    1,
    },
    "Counterstrike": {
        "Wall of Steel":  2,  # Guide: "does well against popular styles"
        "Strike":         2,
        "Lunge":          1,
        "Total Kill":    -1,  # TK bypasses CS defensive setup
        "Parry":         -1,
        "Slash":          1,
        "Bash":           1,
    },
    "Decoy": {
        "Lunge":         -1,
        "Wall of Steel": -1,  # Guide: "performs poorly against most popular styles"
        "Strike":        -1,
        "Bash":          -1,
        "Counterstrike": -2,  # CS has specific tools vs Decoy
        "Parry":          2,  # Guide: "negates protect area save chance"
    },
    "Sure Strike": {
        "Calculated Attack": -1,  # CA somehow counters SS
        "Total Kill":     -1,
        "Wall of Steel":  -1,
        "Parry":           1,
        "Defend":          1,
        "Counterstrike":   1,
    },
    "Calculated Attack": {
        "Total Kill":    -2,  # Guide: "countered by another popular style"
        "Wall of Steel":  1,  # Guide: "counters one of the most popular styles"
        "Strike":        -1,
        "Parry":          2,
        "Defend":         2,
        "Lunge":          1,
    },
    "Opportunity Throw": {
        # Specialty — mostly neutral, relies on thrown weapon damage
    },
    "Martial Combat": {
        "Engage & Withdraw": -2,  # E&W specifically counters MC
        "Counterstrike":  1,  # Guide: "counters specialty style in early game"
        "Decoy":         -1,
        "Wall of Steel": -1,
        "Total Kill":    -1,
    },
    "Parry": {
        "Total Kill":     1,  # Guide: "counters or is neutral to almost all popular"
        "Wall of Steel":  1,
        "Slash":          1,
        "Bash":           1,
        "Strike":        -1,
        "Sure Strike":   -1,
        "Calculated Attack": -2,
        "Defend":         0,
    },
    "Defend": {
        "Total Kill":     1,
        "Bash":           1,
        "Slash":          1,
        "Strike":        -1,
        "Wall of Steel": -2,  # Guide: "counter to Defend appears particularly bad"
        "Sure Strike":   -1,
        "Calculated Attack": -1,
    },
}


def get_style_advantage(atk_style: str, def_style: str) -> int:
    """
    Return the style matchup modifier for attacker vs defender.
    Positive = attacker has style advantage.
    Negative = defender has style advantage.
    """
    return STYLE_COUNTER_MATRIX.get(atk_style, {}).get(def_style, 0)


# ---------------------------------------------------------------------------
# STYLE COMBAT PROPERTIES
# ---------------------------------------------------------------------------
# Per-style modifiers for combat calculations.
# All values APPROX — calibrated against guide descriptions.

@dataclass
class StyleProperties:
    """Combat modifiers for a given fighting style."""
    apm_modifier    : float  # Modifier to actions per minute
    damage_modifier : float  # Flat modifier to damage dealt
    parry_bonus     : int    # Bonus to parry rolls (can be negative)
    dodge_bonus     : int    # Bonus to dodge rolls
    endurance_burn  : float  # Endurance spent per action (negative = gain)
    intimidate      : bool   # Chance to scare opponent
    anxiously_awaits: bool   # Drains foe endurance when used
    total_kill_mode : bool   # Ignores defenses, nearly no parry/dodge
    notes           : str    = ""


STYLE_PROPERTIES: dict[str, StyleProperties] = {
    # Endurance burn philosophy:
    #   Every style costs something — no style gains endurance in combat.
    #   Aggressive styles burn fast (8-10/action). Defensive styles break even
    #   or cost a little (1-2/action). This ensures fights resolve within ~5-6
    #   minutes without the ref becoming the primary deciding factor.
    "Total Kill": StyleProperties(
        apm_modifier=1.5, damage_modifier=5.0,
        parry_bonus=-8, dodge_bonus=-8,
        endurance_burn=10.0, intimidate=True,
        anxiously_awaits=False, total_kill_mode=True,
        notes="Berserk. High damage, nearly no defense. Burns out fast.",
    ),
    "Wall of Steel": StyleProperties(
        apm_modifier=1.5, damage_modifier=-2.0,
        parry_bonus=3, dodge_bonus=0,
        endurance_burn=9.0, intimidate=True,
        anxiously_awaits=False, total_kill_mode=False,
        notes="High attack rate, damage penalty, very high endurance cost.",
    ),
    "Lunge": StyleProperties(
        apm_modifier=0.5, damage_modifier=-1.0,
        parry_bonus=0, dodge_bonus=4,
        endurance_burn=6.0, intimidate=False,
        anxiously_awaits=False, total_kill_mode=False,
        notes="Good dodge bonus. Rhythm bursts. Moderate endurance cost.",
    ),
    "Bash": StyleProperties(
        apm_modifier=-0.5, damage_modifier=3.0,
        parry_bonus=-1, dodge_bonus=-2,
        endurance_burn=7.0, intimidate=False,
        anxiously_awaits=False, total_kill_mode=False,
        notes="Good damage. Poor defense. High endurance cost.",
    ),
    "Slash": StyleProperties(
        apm_modifier=-1.5, damage_modifier=4.0,
        parry_bonus=-2, dodge_bonus=-3,
        endurance_burn=5.0, intimidate=False,
        anxiously_awaits=False, total_kill_mode=False,
        notes="Special slash hits. Slow, poor defense.",
    ),
    "Strike": StyleProperties(
        apm_modifier=0.0, damage_modifier=0.0,
        parry_bonus=0, dodge_bonus=0,
        endurance_burn=2.0,               # Low cost but no longer free
        intimidate=False,
        anxiously_awaits=True, total_kill_mode=False,
        notes="Average in all things. Low but real endurance cost.",
    ),
    "Engage & Withdraw": StyleProperties(
        apm_modifier=-0.3, damage_modifier=-1.0,
        parry_bonus=0, dodge_bonus=5,
        endurance_burn=2.0,               # Low cost — hit and run is tiring but efficient
        intimidate=False,
        anxiously_awaits=True, total_kill_mode=False,
        notes="Very high dodge. Low endurance cost.",
    ),
    "Counterstrike": StyleProperties(
        apm_modifier=-1.5, damage_modifier=2.0,
        parry_bonus=2, dodge_bonus=0,
        endurance_burn=3.5, intimidate=False,
        anxiously_awaits=True, total_kill_mode=False,
        notes="Low native APM; counters provide extra attacks.",
    ),
    "Decoy": StyleProperties(
        apm_modifier=-0.5, damage_modifier=1.0,
        parry_bonus=3, dodge_bonus=-1,
        endurance_burn=5.0, intimidate=False,
        anxiously_awaits=False, total_kill_mode=False,
        notes="Negates defense point. Can block parry.",
    ),
    "Sure Strike": StyleProperties(
        apm_modifier=-1.0, damage_modifier=0.0,
        parry_bonus=0, dodge_bonus=0,
        endurance_burn=1.5,               # Slow and deliberate — efficient but not free
        intimidate=False,
        anxiously_awaits=True, total_kill_mode=False,
        notes="Highest hit %. Slow. Low endurance cost.",
    ),
    "Calculated Attack": StyleProperties(
        apm_modifier=-1.0, damage_modifier=2.0,
        parry_bonus=0, dodge_bonus=0,
        endurance_burn=1.5,               # Methodical — low cost
        intimidate=False,
        anxiously_awaits=True, total_kill_mode=False,
        notes="Hits critical locations. Slow. Low endurance cost.",
    ),
    "Opportunity Throw": StyleProperties(
        apm_modifier=0.0, damage_modifier=0.0,
        parry_bonus=0, dodge_bonus=0,
        endurance_burn=3.0, intimidate=False,
        anxiously_awaits=False, total_kill_mode=False,
        notes="Uses thrown weapons. Switches style after throws exhausted.",
    ),
    "Martial Combat": StyleProperties(
        apm_modifier=0.3, damage_modifier=-2.0,
        parry_bonus=1, dodge_bonus=2,
        endurance_burn=4.0, intimidate=False,
        anxiously_awaits=False, total_kill_mode=False,
        notes="Special brawl attacks. Kick, punch, sweep.",
    ),
    "Parry": StyleProperties(
        apm_modifier=-2.5, damage_modifier=-4.0,
        parry_bonus=6, dodge_bonus=2,
        endurance_burn=1.0,               # Near-passive — breaks even in a quiet fight
        intimidate=False,
        anxiously_awaits=False, total_kill_mode=False,
        notes="Purely defensive. Very low endurance cost.",
    ),
    "Defend": StyleProperties(
        apm_modifier=-2.0, damage_modifier=-3.0,
        parry_bonus=4, dodge_bonus=2,
        endurance_burn=1.0,               # Slightly cheaper than Parry's old -2
        intimidate=False,
        anxiously_awaits=True, total_kill_mode=False,
        notes="Slightly more active than Parry. Still very defensive.",
    ),
}


def get_style_props(style_name: str) -> StyleProperties:
    """Return StyleProperties for a given style name, defaulting to Strike."""
    return STYLE_PROPERTIES.get(style_name, STYLE_PROPERTIES["Strike"])


# ---------------------------------------------------------------------------
# STYLE-SKILL SYNERGY MAP
# ---------------------------------------------------------------------------
# Lists the skills most important to each style.  As a warrior trains these
# skills, the natural flaws of the style are gradually reduced.
# Used by the training advisor and post-fight skill suggestions.

STYLE_SKILL_SYNERGY: dict[str, list[str]] = {
    "Counterstrike":      ["Parry", "Initiative", "Feint", "Riposte"],
    "Decoy":              ["Feint", "Parry", "Acrobatics", "Riposte"],
    "Lunge":              ["Lunge", "Initiative", "Dodge", "Charge"],
    "Wall of Steel":      ["Initiative", "Parry", "Dodge", "Feint", "Riposte", "Strike"],
    "Martial Combat":     ["Brawl", "Sweep", "Dodge", "Acrobatics", "Charge"],
    "Bash":               ["Charge", "Bash", "Strike"],
    "Sure Strike":        ["Feint", "Riposte", "Strike"],
    "Engage & Withdraw":  ["Dodge", "Lunge", "Acrobatics", "Charge", "Riposte"],
    "Defend":             ["Disarm", "Sweep", "Acrobatics"],
    "Slash":              ["Slash", "Cleave", "Strike"],
    "Parry":              ["Parry", "Riposte", "Disarm"],
    "Opportunity Throw":  ["Throw", "Initiative", "Feint"],
    "Calculated Attack":  ["Initiative", "Slash", "Strike", "Feint", "Riposte"],
    "Strike":             ["Strike", "Initiative", "Bash", "Cleave", "Charge"],
}
