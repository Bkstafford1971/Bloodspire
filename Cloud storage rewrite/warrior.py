# =============================================================================
# warrior.py — BLOODSPIRE Warrior Class
# =============================================================================
# Defines the Warrior dataclass along with:
#   - 6 core attributes and their flavor descriptions
#   - HP formula and physical measurements
#   - Permanent injury tracking (7 locations, 10 levels)
#   - Strategy system (up to 6 triggers)
#   - Skill tracking (10 non-weapon + 44 weapon skills)
#   - Roll-up system (interactive + AI)
#   - JSON serialization for saves
# =============================================================================

import random
import json
from typing import List, Optional, Dict
from races import Race, get_race, list_playable_races


# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

ROLLUP_POINTS       = 16   # Total points distributed during warrior creation
ROLLUP_MAX_PER_STAT = 7    # Hard cap: no single stat can receive more than this
STAT_MIN            = 3    # Absolute floor for any attribute
STAT_MAX            = 25   # Absolute ceiling (theoretical; hard to reach in practice)
MAX_FIGHTS          = 100  # Retirement eligibility threshold

# Canonical attribute order (used everywhere for consistency)
ATTRIBUTES = [
    "strength", "dexterity", "constitution",
    "intelligence", "presence", "size"
]


# ---------------------------------------------------------------------------
# STAT DESCRIPTION TABLES
# ---------------------------------------------------------------------------
# Each table maps (low, high) ranges to display strings.
# These appear in the fight header comparison block.
# Source: directly from the player's guide.

STRENGTH_DESCRIPTIONS = {
    (3,  3):  "Jelly-fish like",
    (4,  6):  "Is of feeble strength",
    (7,  8):  "Is of weak strength",
    (9,  11): "Is of ordinary strength",
    (12, 13): "Is of sturdy strength",
    (14, 16): "Is of muscular strength",
    (17, 18): "Is of formidable strength",
    (19, 21): "Is of powerful strength",
    (22, 23): "Mighty strength",
    (24, 25): "Beastly strength",
}

DEXTERITY_DESCRIPTIONS = {
    (3,  3):  "Has inert movements",
    (4,  6):  "Has sluggish movements",
    (7,  8):  "Has slow movements",
    (9,  11): "Has stable movements",
    (12, 13): "Has quick movements",
    (14, 16): "Has agile movements",
    (17, 18): "Has nimble movements",
    (19, 21): "Has swift movements",
    (22, 23): "Has blur-like movements",
    (24, 25): "Has lightning quick movements",
}

CONSTITUTION_DESCRIPTIONS = {
    (3,  3):  "Flimsy constitution",
    (4,  6):  "Has a puny constitution",
    (7,  8):  "Has a frail constitution",
    (9,  11): "Has a delicate constitution",
    (12, 13): "Has a healthy constitution",
    (14, 16): "Has a tough constitution",
    (17, 18): "Has a brawny constitution",
    (19, 21): "Has a resilient constitution",
    (22, 23): "Has a rugged constitution",
    (24, 25): "Has iron-like constitution",
}

INTELLIGENCE_DESCRIPTIONS = {
    (3,  3):  "Dumb as a bedpost",
    (4,  6):  "Sometimes forgets to breathe",
    (7,  8):  "Is just plain dumb",
    (9,  11): "Depends on muscle over mind",
    (12, 13): "Has average intelligence",
    (14, 16): "Is fairly bright",
    (17, 18): "Is a quick thinker",
    (19, 21): "Is a gifted strategist",
    (22, 23): "Possesses great intellect",
    (24, 25): "Is a genius",
}

# PRESENCE has no description table in the guide — custom table created.
# APPROX: Scaled to feel thematically appropriate based on guide descriptions.
PRESENCE_DESCRIPTIONS = {
    (3,  3):  "Has no presence whatsoever",
    (4,  6):  "Is easily overlooked",
    (7,  8):  "Makes little impression",
    (9,  11): "Is somewhat noticed",
    (12, 13): "Commands some attention",
    (14, 16): "Has a notable presence",
    (17, 18): "Is quite impressive",
    (19, 21): "Commands great respect",
    (22, 23): "Is supremely commanding",
    (24, 25): "Is a legendary figure",
}

SIZE_DESCRIPTIONS = {
    (3,  3):  "Is grossly thin",
    (4,  6):  "Could blow away in the wind",
    (7,  8):  "Has a slight build",
    (9,  11): "Has a wiry frame",
    (12, 13): "Is of average build",
    (14, 16): "Is somewhat large",
    (17, 18): "Has a large frame",
    (19, 21): "Is a huge and imposing figure",
    (22, 23): "Is built like a gorilla",
    (24, 25): "Is bigger than a barn",
}

STAT_DESCRIPTION_TABLES = {
    "strength":     STRENGTH_DESCRIPTIONS,
    "dexterity":    DEXTERITY_DESCRIPTIONS,
    "constitution": CONSTITUTION_DESCRIPTIONS,
    "intelligence": INTELLIGENCE_DESCRIPTIONS,
    "presence":     PRESENCE_DESCRIPTIONS,
    "size":         SIZE_DESCRIPTIONS,
}


def get_stat_description(stat_name: str, value: int) -> str:
    """
    Return the flavor description string for a given stat at a given value.
    Falls back gracefully if stat_name is unrecognized.
    """
    table = STAT_DESCRIPTION_TABLES.get(stat_name.lower())
    if not table:
        return f"{stat_name}: {value}"
    for (lo, hi), description in table.items():
        if lo <= value <= hi:
            return description
    return f"{stat_name}: {value}"  # Out-of-range fallback


def compare_stats(val_a: int, val_b: int) -> str:
    """
    Return a directional arrow comparing two warriors' stats.

    Guide rule: "equal if the stat is within 2 of each other.
    If it's 3 or more, it gives the advantage arrow to the higher."

    Returns:
        "   " — effectively equal (within 2)
        "<--" — A has the advantage
        "-->" — B has the advantage
    """
    diff = val_a - val_b
    if abs(diff) <= 2:
        return "   "
    elif diff > 2:
        return "<--"
    else:
        return "-->"


# ---------------------------------------------------------------------------
# PERMANENT INJURY SYSTEM
# ---------------------------------------------------------------------------

INJURY_LOCATIONS = [
    "head", "chest", "abdomen",
    "primary_arm", "secondary_arm",
    "primary_leg", "secondary_leg"
]

INJURY_DESCRIPTIONS = {
    0: "None",
    1: "Annoying",
    2: "Bothersome",
    3: "Irritating",
    4: "Troublesome",
    5: "Painful",
    6: "Dreadful",
    7: "Incapacitating",
    8: "Devastating",
    9: "Fatal",   # Level 9 = warrior is slain
}


class PermanentInjuries:
    """
    Tracks the permanent injury level for each of the 7 body locations.
    Level 0 = no injury. Level 9 = fatal.
    """

    def __init__(self):
        self.head         = 0
        self.chest        = 0
        self.abdomen      = 0
        self.primary_arm  = 0
        self.secondary_arm= 0
        self.primary_leg  = 0
        self.secondary_leg= 0

    def get(self, location: str) -> int:
        """Return the injury level for a location."""
        return getattr(self, location, 0)

    def add(self, location: str, levels: int = 1) -> bool:
        """
        Add injury levels to a location.
        Returns True if the warrior has been slain (any location reaches 9).
        """
        if location not in INJURY_LOCATIONS:
            raise ValueError(f"Invalid injury location: '{location}'")
        current  = self.get(location)
        new_level = min(9, current + levels)
        setattr(self, location, new_level)
        return new_level >= 9  # True = warrior is dead

    def is_fatal(self) -> bool:
        """True if any location has reached level 9."""
        return any(self.get(loc) >= 9 for loc in INJURY_LOCATIONS)

    def active_injuries(self) -> List[tuple]:
        """Return list of (location, level) for all locations with level > 0."""
        return [
            (loc, self.get(loc))
            for loc in INJURY_LOCATIONS
            if self.get(loc) > 0
        ]

    def summary(self) -> str:
        """Formatted multi-line injury summary."""
        active = self.active_injuries()
        if not active:
            return "  No permanent injuries."
        lines = []
        for loc, level in active:
            desc = INJURY_DESCRIPTIONS[level]
            display = loc.replace("_", " ").title()
            lines.append(f"  {display:<16} Level {level} — {desc}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {loc: self.get(loc) for loc in INJURY_LOCATIONS}

    def from_dict(self, data: dict):
        for loc in INJURY_LOCATIONS:
            setattr(self, loc, data.get(loc, 0))


# ---------------------------------------------------------------------------
# STRATEGY SYSTEM
# ---------------------------------------------------------------------------

# All valid trigger conditions (read top-to-bottom during a fight).
# Guide: "the program reads triggers from top to bottom, so order matters."
TRIGGERS = [
    "None",
    "Minute 1",  "Minute 2",  "Minute 3",  "Minute 4",  "Minute 5",
    "Minute 6",  "Minute 7",  "Minute 8",  "Minute 9",  "Minute 10",
    "You are very tired",            "Your foe is very tired",
    "You are somewhat tired",        "Your foe is somewhat tired",
    "You are slightly tired",        "Your foe is slightly tired",
    "You have taken heavy damage",   "Your foe has taken heavy damage",
    "You have taken medium damage",  "Your foe has taken medium damage",
    "You have taken slight damage",  "Your foe has taken slight damage",
    "You challenged your foe",       "Your foe challenged you",
    "You blood challenged your foe", "Your foe blood challenged you",
    "You are on the ground",         "Your foe is on the ground",
    "You are weaponless",            "Your foe is weaponless",
    "You have no throwable weapons",
    "You have at least one throwable weapon",
    "You have exactly one throwable weapon",
    "You have exactly one weapon",
    "You have exactly 2 weapons",
    "You have more than 2 weapons",
    "Your foe is wearing light armor",
    "Your foe is wearing medium armor",
    "Your foe is wearing heavy armor",
    "Always (Default Loop)",
]

# All 15 fighting styles (exactly as listed in the guide).
FIGHTING_STYLES = [
    "Total Kill",
    "Wall of Steel",
    "Lunge",
    "Bash",
    "Slash",
    "Strike",
    "Engage & Withdraw",
    "Counterstrike",
    "Decoy",
    "Sure Strike",
    "Calculated Attack",
    "Opportunity Throw",
    "Martial Combat",
    "Parry",
    "Defend",
]

# Aiming and defense point locations.
AIM_DEFENSE_POINTS = [
    "None",
    "Head",
    "Chest",
    "Abdomen",
    "Primary Arm",
    "Secondary Arm",
    "Primary Leg",
    "Secondary Leg",
]


class Strategy:
    """
    One row in a warrior's strategy table.
    A warrior may have up to 6 of these, read top-to-bottom each minute.
    """

    def __init__(
        self,
        trigger: str   = "Always",
        style: str     = "Strike",
        activity: int  = 5,
        aim_point: str = "None",
        defense_point: str = "Chest",
    ):
        self.trigger       = trigger
        self.style         = style
        self.activity      = max(0, min(9, activity))  # Clamp 0-9
        self.aim_point     = aim_point
        self.defense_point = defense_point

    def to_dict(self) -> dict:
        return {
            "trigger":       self.trigger,
            "style":         self.style,
            "activity":      self.activity,
            "aim_point":     self.aim_point,
            "defense_point": self.defense_point,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Strategy":
        return cls(
            trigger      = data.get("trigger",       "Always"),
            style        = data.get("style",         "Strike"),
            activity     = data.get("activity",      5),
            aim_point    = data.get("aim_point",     "None"),
            defense_point= data.get("defense_point", "Chest"),
        )

    def display(self, index: str) -> str:
        """Format one strategy row for display."""
        return (
            f"  {index:<3} | {self.trigger:<32} | {self.style:<18} "
            f"| Act:{self.activity} | Aim:{self.aim_point:<14} | Def:{self.defense_point}"
        )


# ---------------------------------------------------------------------------
# SKILL SYSTEM
# ---------------------------------------------------------------------------

NON_WEAPON_SKILLS = [
    "dodge", "parry", "throw", "charge", "lunge",
    "disarm", "initiative", "feint", "brawl", "sweep",
    "cleave", "bash", "acrobatics", "riposte", "slash", "strike",
]

# 45 weapon skills — one per weapon in the game.
WEAPON_SKILLS = [
    "stiletto", "cestus", "knife", "dagger", "javelin", "hatchet",
    "short_sword", "epee", "hammer", "net", "small_pick", "buckler",
    "swordbreaker", "longsword", "scythe", "flail", "francisca", "mace",
    "short_spear", "boar_spear", "quarterstaff", "trident", "military_pick", "scimitar",
    "broad_sword", "morningstar", "war_hammer", "target_shield",
    "bladed_flail", "war_flail", "bastard_sword", "pick_axe", "long_spear",
    "tower_shield", "battle_axe", "battle_flail", "great_staff", "pole_axe",
    "great_sword", "ball_and_chain", "great_axe", "maul", "great_pick",
    "halberd", "open_hand",
]

ALL_SKILLS = NON_WEAPON_SKILLS + WEAPON_SKILLS

SKILL_LEVEL_NAMES = {
    0: "No Skill",
    1: "Novice",
    2: "Some Skill",
    3: "Skilled",
    4: "Good Skill",
    5: "Very Skilled",
    6: "Excellent Skill",
    7: "Expert Skill",
    8: "Incredible Skill",
    9: "Master Skill",
}


# ---------------------------------------------------------------------------
# WARRIOR CLASS
# ---------------------------------------------------------------------------

class Warrior:
    """
    Represents a single gladiator in BLOODSPIRE.

    Design notes:
      - Racial modifiers are NOT baked into base stats. They are stored in
        self.race.modifiers and applied at combat time. This keeps stats clean.
      - SIZE cannot be trained (per guide). Enforced in train_skill().
      - HP formula: 2*SIZE + (CON*1.5) + 0.5*STR, capped at 100, + racial bonus.
    """

    def __init__(
        self,
        name:         str,
        race_name:    str,
        gender:       str,   # "Male" or "Female"
        strength:     int,
        dexterity:    int,
        constitution: int,
        intelligence: int,
        presence:     int,
        size:         int,
    ):
        # --- Identity ---
        self.name   = name
        self.race   = get_race(race_name)
        self.gender = gender

        # --- Core Attributes ---
        self.strength     = strength
        self.dexterity    = dexterity
        self.constitution = constitution
        self.intelligence = intelligence
        self.presence     = presence
        self.size         = size

        # --- Derived Stats (calculated at init and recalculated after training) ---
        self.max_hp           = self._calc_max_hp()
        self.current_hp       = self.max_hp      # Reset each fight
        self.current_endurance= 100              # 0-100 scale; reset each fight

        # --- Fight Record (W-L-K: Wins, Losses, Kills) ---
        # A "Kill" is a win where the opponent died in the fight.
        self.wins        = 0
        self.losses      = 0
        self.kills       = 0   # How many opponents this warrior has slain
        self.monster_kills = 0 # How many monsters this warrior has slain
        self.total_fights= 0   # Retirement unlocks at MAX_FIGHTS (100)

        # --- Equipment ---
        self.armor           : Optional[str] = None         # e.g. "Brigandine"
        self.helm            : Optional[str] = None         # e.g. "Steel Cap"
        self.primary_weapon  : str           = "Open Hand"
        self.secondary_weapon: str           = "Open Hand"
        self.backup_weapon   : Optional[str] = None

        # --- Strategies (1-6 entries + implicit "Always" fallback) ---
        self.strategies: List[Strategy] = [
            Strategy(
                trigger      ="Always",
                style        ="Strike",
                activity     =5,
                aim_point    ="None",
                defense_point="Chest",
            )
        ]

        # --- Training Queue (up to 3 trains per turn) ---
        # Each entry is a skill or attribute name.
        # e.g. ["constitution", "war_flail", "dodge"]
        self.trains: List[str] = []

        # --- Skills (all start at 0; train up to 9) ---
        self.skills: Dict[str, int] = {skill: 0 for skill in ALL_SKILLS}

        # --- Permanent Injuries ---
        self.injuries = PermanentInjuries()

        # --- Blood Cry (≤50 chars, screamed at a trigger moment) ---
        self.blood_cry: str = ""

        # --- Initial stats at creation (never changes — used for "current (initial)" display) ---
        self.initial_stats: Optional[Dict[str, int]] = None

        # --- Fight history (persisted; shown in Fights tab) ---
        # Each entry: {turn, opponent_name, opponent_race, result, minutes, fight_id,
        #              warrior_slain, opponent_slain}
        self.fight_history: List[dict] = []

        # --- Per-attribute gain counter (tracks how many successful increases
        #     have been made per attribute; governs early vs late training tier) ---
        self.attribute_gains: dict = {
            "strength":0,"dexterity":0,"constitution":0,"intelligence":0,"presence":0
        }

        # --- Luck (1-30, permanent, assigned at creation, adds to every roll) ---
        # A warrior's luck never changes. Lucky warriors (25-30) punch above their stats.
        # Unlucky warriors (1-5) may underperform despite good attributes.
        self.luck: int = 0   # Set by factory functions after creation

        # --- Popularity (0-100 flavor stat) ---
        self.popularity: int = 0

        # --- Recognition (0+ rating, determines class ranking tier) ---
        self.recognition: int = 0

        # --- Win/loss streak (+ve = win streak, -ve = loss streak, 0 = neutral) ---
        self.streak: int = 0

        # --- Turns active (incremented each time a turn is run for this team) ---
        self.turns_active: int = 0

        # --- Fight-option flags (set by manager each turn, cleared after processing) ---
        self.want_monster_fight: bool = False   # opt-in for Monster bout this turn
        self.want_retire:        bool = False   # request retirement (requires 100+ fights)

        # --- Avoidance System (max 2 slots each) ---
        self.avoid_warriors: List[str] = []

        # --- Death state ---
        self.is_dead: bool = False   # True once slain; slot awaits player replacement
        self.ascended_to_monster: bool = False  # True if warrior was absorbed into The Monsters
        self.killed_by: str = ""     # Name of the warrior/monster that slew this one

        # --- Favorite Weapon (hidden at creation, revealed only in combat) ---
        # Assigned based on race + stats + random element. Never changes once set.
        self.favorite_weapon: str = ""  # e.g. "War Flail", "Stiletto", etc.

        # --- Physical Measurements ---
        self.height_in, self.weight_lbs = self._calc_measurements()
        # Extra pounds gained through attribute training (STR/CON gains)
        self.training_weight_bonus: int = 0

        # --- Training Session Message Tracking ---
        # Tracks which "already maxed" messages have been shown this training turn
        # to avoid repeating them if the warrior trains the same skill multiple times
        self.shown_max_messages: set = set()

    # =========================================================================
    # DERIVED STAT CALCULATIONS
    # =========================================================================

    def _calc_max_hp(self) -> int:
        """
        HP Formula (from guide):
            Base HP = 2*SIZE + (CON * 1.5) + (STR * 0.5)
            Cap at 100.
            Add racial HP bonus (can be negative for Elves).
        """
        base = (2 * self.size) + (self.constitution * 1.5) + (self.strength * 0.5)
        racial_bonus = self.race.modifiers.hp_bonus
        total = int(base + racial_bonus)
        return max(1, min(total, 100))   # Always at least 1 HP; never more than 100

    def _calc_measurements(self) -> tuple:
        """
        Derive height (inches) and weight (lbs) from race + SIZE + gender.

        HEIGHT:
          Each race has a male height range (min at SIZE 3, max at SIZE 25).
          SIZE is mapped linearly across that range.
          Females use 95% of the male range endpoints (both min and max shift
          down proportionally), so the full male/female SIZE spread is preserved.

        WEIGHT:
          Derived from height using a race-specific body-density factor
          (lbs = height_in^2 * density).  Dwarves have a much higher density
          than other races — heavier by proportion as specified.
          Females use 92% of the male density factor.

        Gender is purely cosmetic — no combat modifiers result from this.

        Height ranges (male SIZE 3 → SIZE 25):
          Halfling : 3'01" → 5'01"
          Elf      : 4'08" → 5'11"
          Half-Elf : 5'00" → 6'00"
          Human    : 5'02" → 6'04"
          Dwarf    : 3'06" → 5'02"  (heaviest by proportion)
          Half-Orc : 5'05" → 7'06"
        """
        # --- Height range table (inches, male) ---
        # Keys match race names; (min_in, max_in) at SIZE 3 and SIZE 25.
        HEIGHT_RANGES = {
            "Halfling" : (37, 61),
            "Elf"      : (56, 71),
            "Half-Elf" : (60, 72),
            "Human"    : (62, 76),
            "Dwarf"    : (42, 62),
            "Half-Orc" : (65, 90),
            # NPC races use Human proportions as fallback
            "Monster"  : (72, 108),   # Enormous
            "Peasant"  : (62, 76),
        }

        # --- Weight density table (lbs = height_in^2 * factor, male) ---
        # Dwarves are proportionally much denser/heavier than other races.
        DENSITY = {
            "Halfling" : 0.0434,   # Calibrated: 4'3"/51" = ~113 lbs
            "Elf"      : 0.0338,
            "Half-Elf" : 0.0354,
            "Human"    : 0.0368,
            "Dwarf"    : 0.0780,   # Notably heavier by proportion
            "Half-Orc" : 0.0462,
            "Monster"  : 0.0420,
            "Peasant"  : 0.0368,
        }

        race_name = self.race.name
        mn_m, mx_m = HEIGHT_RANGES.get(race_name, (62, 76))

        # Female endpoints are 95% of male (smaller but same proportional spread)
        if self.gender == "Female":
            mn = int(mn_m * 0.95)
            mx = int(mx_m * 0.95)
        else:
            mn, mx = mn_m, mx_m

        # Linear interpolation: SIZE 3 = min, SIZE 25 = max
        size_t  = max(0.0, min(1.0, (self.size - 3) / 22))
        height  = int(mn + size_t * (mx - mn))

        # Weight from height using density factor
        density = DENSITY.get(race_name, 0.0368)
        if self.gender == "Female":
            density *= 0.92   # Slightly lighter frame
        weight = max(30, int(height ** 2 * density))
        # Add any weight gained through attribute training
        weight += getattr(self, "training_weight_bonus", 0)

        return height, weight

    def recalculate_derived(self):
        """
        Recalculate HP and measurements after stats change (e.g. after training).
        Call this after any attribute change.
        Note: current_hp is NOT reset here — only max_hp changes.
        """
        old_max    = self.max_hp
        self.max_hp = self._calc_max_hp()

        # If max HP increased, current HP scales up proportionally
        # APPROX: Training gives a small HP boost to current as well as max.
        if self.max_hp > old_max:
            self.current_hp = min(self.current_hp + (self.max_hp - old_max), self.max_hp)

        self.height_in, self.weight_lbs = self._calc_measurements()

    # =========================================================================
    # STAT ACCESS
    # =========================================================================

    def get_attr(self, attr_name: str) -> int:
        """Get an attribute value by name (case-insensitive)."""
        return getattr(self, attr_name.lower(), 0)

    def set_attr(self, attr_name: str, value: int):
        """Set an attribute value, clamped to STAT_MIN/STAT_MAX."""
        attr = attr_name.lower()
        if attr in ATTRIBUTES:
            setattr(self, attr, max(STAT_MIN, min(STAT_MAX, value)))
            self.recalculate_derived()

    def stat_desc(self, attr_name: str) -> str:
        """Return the flavor description string for a stat."""
        return get_stat_description(attr_name, self.get_attr(attr_name))

    # =========================================================================
    # FIGHT RECORD
    # =========================================================================

    @property
    def record_str(self) -> str:
        """Format: Wins-Losses-Kills. There are no draws."""
        return f"{self.wins}-{self.losses}-{self.kills}"

    def record_result(self, result: str, killed_opponent: bool = False):
        """
        Record a fight result: 'win' or 'loss'. No draws exist.
        Pass killed_opponent=True when the winning warrior slew their foe —
        this increments both wins and kills.
        """
        result = result.lower().strip()
        if result == "win":
            self.wins += 1
            if killed_opponent:
                self.kills += 1
            self.streak = max(0, self.streak) + 1   # extend win streak
        elif result == "loss":
            self.losses += 1
            self.streak = min(0, self.streak) - 1   # extend loss streak
        else:
            raise ValueError(f"Invalid result: '{result}'. Use 'win' or 'loss'.")
        self.total_fights += 1

    def recalculate_streak(self) -> None:
        """
        Recalculate the current streak from fight_history.
        Positive = current win streak, negative = current loss streak, 0 = no streak.
        Call this after loading a warrior from downloaded data to ensure streak is accurate.
        
        Note: fight_history is stored with oldest fights first (index 0), newest fights last.
        We count consecutive results of the same type as the most recent fight (at the end).
        """
        if not self.fight_history:
            self.streak = 0
            return
        
        # Get the most recent fight result type (at the end of the list)
        most_recent_result = self.fight_history[-1].get("result", "").lower()
        if most_recent_result not in ("win", "loss"):
            self.streak = 0
            return
        
        # Count consecutive results of the same type from the most recent fight backwards
        streak = 0
        for entry in reversed(self.fight_history):
            result = entry.get("result", "").lower()
            if result == most_recent_result:
                streak += 1
            else:
                break  # Stop at the first different result
        
        # Make streak positive for wins, negative for losses
        if most_recent_result == "loss":
            streak = -streak
        self.streak = streak

    @property
    def can_retire(self) -> bool:
        """Retirement becomes available at 100 fights."""
        return self.total_fights >= MAX_FIGHTS

    @property
    def presence_hesitate_chance(self) -> int:
        """
        Chance (1-100) that this warrior's commanding presence causes an opponent
        to hesitate at the start of a fight, losing a full minute of initiative.
        Formula: max(0, (presence - 14) * 3)
        PRE 14 = 0%, PRE 16 = 6%, PRE 18 = 12%, PRE 20 = 18%, PRE 25 = 33%
        """
        return max(0, (self.presence - 14) * 3)

    @property
    def is_alive(self) -> bool:
        """False if permanently killed (is_dead flag or a level-9 injury)."""
        return not self.is_dead and not self.injuries.is_fatal()

    # =========================================================================
    # AVOIDANCE SYSTEM
    # =========================================================================

    def add_avoid_warrior(self, warrior_name: str) -> bool:
        """Add a warrior to this warrior's avoid list (max 2). Returns True if added."""
        if len(self.avoid_warriors) >= 2:
            return False
        if warrior_name.lower() in [w.lower() for w in self.avoid_warriors]:
            return False
        self.avoid_warriors.append(warrior_name)
        return True

    def remove_avoid_warrior(self, warrior_name: str) -> bool:
        """Remove a warrior from this warrior's avoid list. Returns True if found and removed."""
        for i, w in enumerate(self.avoid_warriors):
            if w.lower() == warrior_name.lower():
                self.avoid_warriors.pop(i)
                return True
        return False

    def is_avoiding_warrior(self, challenger_name: str) -> bool:
        """Check if this warrior is avoiding a specific challenger (by name)."""
        return any(w.lower() == challenger_name.lower() for w in self.avoid_warriors)

    # =========================================================================
    # SKILL SYSTEM
    # =========================================================================

    def skill_level(self, skill: str) -> int:
        """Return numeric skill level (0-9) for a skill."""
        return self.skills.get(skill.lower().replace(" ", "_"), 0)

    def skill_name(self, skill: str) -> str:
        """Return display name (e.g. 'Expert Skill') for a skill."""
        return SKILL_LEVEL_NAMES.get(self.skill_level(skill), "Unknown")

    def reset_training_session(self) -> None:
        """
        Reset training session tracking.
        Call this at the start of each training turn to clear the log of
        which max-level messages have already been shown this turn.
        """
        self.shown_max_messages = set()

    def train_skill(self, skill: str) -> str:
        """
        Apply one training session to a skill or attribute.
        Returns a human-readable result message (success OR no-progress).
        Training is NOT automatic — success depends on the warrior's stats.

        GRADUATED LEARNING CURVE — two-factor formula:
          1. Base chance from governing stat (INT for skills, CON for attributes):
               stat  3-8  -> 38%    stat  9-14 -> 65%
               stat 15-20 -> 82%    stat 21-25 -> 94%
          2. Difficulty multiplier from current level / gains so far:
               0-3 : x1.00   4-5 : x0.65   6-7 : x0.40   8+ : x0.25
          3. Mastery bonus (level/gains >= 8, stat >= 15): +(stat-14)*1.5
          4. Racial bonus (Humans & Gnomes): +7 to chance after multiply, capped 94.
             Applies to BOTH skill and attribute training.
          Final chance clamped 5%-96%.

        SKILL training (weapon skills + non-weapon skills):
          Governed by Intelligence. gains = current skill level (0-based).

        ATTRIBUTE training (STR / DEX / CON / INT / PRE, not SIZE):
          Governed by Constitution. Gains tracked in self.attribute_gains.
        """
        key = skill.lower().replace(" ", "_")

        # Shared helper: base chance from stat band
        def _base_chance(stat: int) -> int:
            if stat <= 8:   return 38
            if stat <= 14:  return 65
            if stat <= 20:  return 82
            return 94

        # Shared helper: difficulty multiplier from gains
        def _multiplier(gains: int) -> float:
            if gains < 4:  return 1.00
            if gains < 6:  return 0.65
            if gains < 8:  return 0.40
            return 0.25

        # --- Attribute training ---
        if key in ATTRIBUTES:
            if key == "size":
                return "SIZE cannot be trained — it is fixed at warrior creation."

            current_val = self.get_attr(key)
            if current_val >= STAT_MAX:
                # Only show max-level message once per training turn
                if key in self.shown_max_messages:
                    return ""  # Already shown this message this turn
                
                self.shown_max_messages.add(key)
                
                # Attribute-specific max-level messages
                if key == "strength":
                    return f"{self.name} is as strong as they will ever be."
                elif key == "dexterity":
                    return f"{self.name} is as nimble and agile as humanly possible."
                elif key == "constitution":
                    return f"{self.name} is as tough and durable as anyone can get."
                elif key == "intelligence":
                    return f"{self.name} is as intelligent as they can possibly be."
                elif key == "presence":
                    return f"{self.name} has achieved maximum influence and presence."
                else:
                    return f"{key.capitalize()} is already at maximum ({STAT_MAX})."

            gains = self.attribute_gains.get(key, 0)
            stat  = self.constitution

            chance = int(_base_chance(stat) * _multiplier(gains))

            # Mastery bonus: high CON still helps at the very top tier
            if gains >= 8 and stat >= 15:
                chance += int((stat - 14) * 1.5)

            # Racial bonus (Humans & Gnomes) — applies to attributes
            if self.race.modifiers.trains_stats_faster:
                chance = min(94, chance + 7)

            chance = max(5, min(96, chance))

            if random.randint(1, 100) > chance:
                tier_label = (
                    "mastery tier" if gains >= 8 else
                    "late tier"    if gains >= 6 else
                    "mid tier"     if gains >= 4 else
                    f"CON {stat}"
                )
                return (
                    f"{skill.capitalize()} training: no progress this session "
                    f"({tier_label}, {chance}% chance)."
                )

            new_val = min(STAT_MAX, current_val + 1)
            # --- Attribute-specific side effects ---
            if key == "strength":
                # +2-3 lbs per STR point gained
                wt = random.randint(2, 3)
                self.training_weight_bonus = getattr(self, "training_weight_bonus", 0) + wt
            elif key == "constitution":
                # +5-7 lbs per CON point gained; HP recalc handled by recalculate_derived
                wt = random.randint(5, 7)
                self.training_weight_bonus = getattr(self, "training_weight_bonus", 0) + wt

            self.set_attr(key, new_val)
            self.attribute_gains[key] = gains + 1
            tier_note = " [mastery]" if gains >= 8 else (" [late]" if gains >= 6 else "")
            # DEX bonus (+2.5% dodge, +2% parry) and INT bonus (4th train) are applied
            # in combat.py — they are derived live from the current stat value.
            # Presence hesitation chance is also derived live.

            return (
                f"{skill.capitalize()} trained: {current_val} → {new_val}"
                f"{tier_note} ({chance}% chance)"
            )

        # --- Skill training ---
        elif key in ALL_SKILLS:
            current_level = self.skills.get(key, 0)
            if current_level >= 9:
                # Only show max-level message once per training turn
                if key in self.shown_max_messages:
                    return ""  # Already shown this message this turn
                
                self.shown_max_messages.add(key)
                skill_name = skill.replace('_', ' ').title()
                return f"{self.name} is already mastered in {skill_name}."

            gains = current_level          # skill level == number of increases so far
            stat  = self.intelligence

            chance = int(_base_chance(stat) * _multiplier(gains))

            # Mastery bonus: high INT still helps at the very top tier
            if gains >= 8 and stat >= 15:
                chance += int((stat - 14) * 1.5)

            # Racial bonus (Humans & Gnomes) — now applies to skills too
            if self.race.modifiers.trains_stats_faster:
                chance = min(94, chance + 7)

            chance = max(5, min(96, chance))

            if random.randint(1, 100) > chance:
                return (
                    f"{skill.replace('_',' ').title()} training: no progress this session "
                    f"(INT {stat}, level {current_level}, {chance}% chance)."
                )

            self.skills[key] = current_level + 1
            new_name = SKILL_LEVEL_NAMES[self.skills[key]]
            return (
                f"{skill.replace('_',' ').title()} trained: "
                f"Level {current_level} → Level {self.skills[key]} ({new_name}, {chance}% chance)"
            )
        else:
            return f"Unknown skill or attribute: '{skill}'"

    # =========================================================================
    # RECOGNITION
    # =========================================================================

    def update_recognition(
        self,
        won: bool,
        killed_opponent: bool = False,
        self_hp_pct: float = 1.0,
        opp_hp_pct: float = 0.0,
        self_knockdowns: int = 0,
        opp_knockdowns: int = 0,
        self_near_kills: int = 0,
        opp_near_kills: int = 0,
        minutes_elapsed: int = 5,
        max_minutes: int = 30,
        opponent_total_fights: int = 0,
    ) -> None:
        """
        Update recognition rating after a fight (formula v3).

        Win path:
            Total = Base + Underdog Bonus + Dominance Bonus
                         + Popularity Bonus + Luck Bonus
            Points clamped 1–15 per fight.  Lifetime total capped at 99.

        Loss path:
            Total = Base Loss – Underdog Opponent Penalty – Dominated Penalty
                         + Bravery Credit + Popularity Bonus + Luck Bonus
            Points clamped -10–3 per fight.
            Lifetime total floored at total_fights (wins + losses).

        self_* / opp_* args should reflect THIS warrior's perspective
        (i.e. pass self's hp_pct, self's knockdowns, etc.).
        record_result() must already have run so total_fights is current.
        """
        # ------------------------------------------------------------------
        # Experience (pre-fight counts — record_result already incremented)
        # ------------------------------------------------------------------
        self_exp = max(1, self.total_fights - 1)
        opp_exp  = max(1, opponent_total_fights - 1)

        duration_pct = minutes_elapsed / max(1, max_minutes)

        # ------------------------------------------------------------------
        # 1. Base Points
        # ------------------------------------------------------------------
        if won:
            base = 5 if killed_opponent else 3
        else:
            base = -3  # losses now cost recognition

        # ------------------------------------------------------------------
        # 2. Underdog Bonus (win) / Underdog Opponent Penalty (loss)
        # ------------------------------------------------------------------
        underdog_bonus = 0
        if won:
            # Beat a more experienced opponent — bonus
            if opp_exp > self_exp:
                pct_more = (opp_exp - self_exp) / self_exp * 100
                if pct_more >= 25:   underdog_bonus = 3
                elif pct_more >= 15: underdog_bonus = 2
                else:                underdog_bonus = 1
        else:
            # Lost to a LESS experienced opponent — crowd turns on you
            if self_exp > opp_exp:
                pct_less = (self_exp - opp_exp) / self_exp * 100
                if pct_less >= 50:   underdog_bonus = -4  # massive upset
                elif pct_less >= 25: underdog_bonus = -3
                elif pct_less >= 15: underdog_bonus = -2
                else:                underdog_bonus = -1

        # ------------------------------------------------------------------
        # 3. Dominance Bonus (wins) / Dominated Penalty (losses)
        # ------------------------------------------------------------------
        dominance_bonus = 0
        if won:
            dominance_score = (self_hp_pct * 50                      # 0–50: health remaining
                               + (1.0 - duration_pct) * 30           # 0–30: shorter = more dominant
                               + min(20, self_knockdowns * 10))       # 0–20: knockdowns dealt
            dominance_score = min(100.0, dominance_score)
            if dominance_score >= 75:   dominance_bonus = 3
            elif dominance_score >= 50: dominance_bonus = 2
            elif dominance_score >= 25: dominance_bonus = 1
        else:
            # How thoroughly did the opponent manhandle us?
            dominated_score = (opp_hp_pct * 50                       # 0–50: opponent's health left
                               + (1.0 - duration_pct) * 30           # 0–30: shorter = more one-sided
                               + min(20, opp_knockdowns * 10))        # 0–20: knockdowns we absorbed
            dominated_score = min(100.0, dominated_score)
            if dominated_score >= 75:   dominance_bonus = -3  # totally manhandled
            elif dominated_score >= 50: dominance_bonus = -2
            elif dominated_score >= 25: dominance_bonus = -1

        # ------------------------------------------------------------------
        # 4. Bravery Credit (losses only — partial mitigation for going down
        #    swinging; formerly "Flashy Loss Bonus")
        # ------------------------------------------------------------------
        bravery_credit = 0
        if not won:
            if self_near_kills >= 2:    bravery_credit += 2
            elif self_near_kills == 1:  bravery_credit += 1
            if duration_pct >= 0.80:    bravery_credit += 1   # went the distance

        # ------------------------------------------------------------------
        # 5. Popularity Bonus (all outcomes — crowd remembers fan favourites)
        # ------------------------------------------------------------------
        popularity_bonus = max(0, (self.popularity - 30) // 20)
        # pop 50 → +1, pop 70 → +2, pop 90 → +3

        # ------------------------------------------------------------------
        # 6. Luck Bonus (probabilistic — lucky warriors occasionally shine)
        # ------------------------------------------------------------------
        luck_bonus = 0
        luck_threshold = 15
        if self.luck > luck_threshold:
            chance = (self.luck - luck_threshold) / (30 - luck_threshold)
            if random.random() < chance:
                luck_bonus = 1

        # ------------------------------------------------------------------
        # Final tally
        # ------------------------------------------------------------------
        points = base + underdog_bonus + dominance_bonus + bravery_credit + popularity_bonus + luck_bonus
        if won:
            points = max(1, min(15, points))
        else:
            points = max(-10, min(3, points))

        # Floor: recognition can never drop below total_fights (wins + losses)
        floor = self.total_fights
        self.recognition = max(floor, min(99, self.recognition + points))

    # =========================================================================
    # POPULARITY
    # =========================================================================

    def update_popularity(self, won: bool = True):
        """
        Recalculate popularity after a fight.
        APPROX:
          win   → +3 base, +1 per kill streak length (max +5), +PRE bonus, +acrobatics bonus
          loss  → -2 base, -1 per loss streak length (max -5), -PRE penalty
          PRE modifier: (presence - 10) * 0.2 (crowd loves charismatic fighters)
          Acrobatics bonus: +2% per acrobatics level (max +18% at level 9)
        Clamped 1-100.
        """
        pre_mod = int((self.presence - 10) * 0.2)
        acrobatics_level = self.skills.get("acrobatics", 0)
        acrobatics_bonus = int(acrobatics_level * 0.2) if acrobatics_level > 0 else 0  # +2% per level (as integer add to popularity)
        
        if won:
            streak_bonus = min(5, max(0, self.streak))
            delta = 3 + streak_bonus + pre_mod + acrobatics_bonus
        else:
            streak_penalty = min(5, max(0, -self.streak))
            delta = -2 - streak_penalty + pre_mod
        self.popularity = max(1, min(100, self.popularity + delta))

    # =========================================================================
    # DISPLAY
    # =========================================================================

    def stat_block(self) -> str:
        """
        Full warrior stat sheet in the style of the original game's fight header.
        Includes stats, gear, injuries, strategies, and skills summary.
        """
        h_ft = self.height_in // 12
        h_in = self.height_in % 12

        separator = "  " + "=" * 60
        thin_sep  = "  " + "-" * 60

        lines = [
            separator,
            f"  WARRIOR:        {self.name.upper()}",
            f"  RECORD:         {self.record_str}  ({self.total_fights} fights)",
            f"  RACE / GENDER:  {self.race.name} {self.gender}",
            f"  POPULARITY:     {self.popularity}",
            thin_sep,
            f"  {'ATTRIBUTE':<16} {'VAL':>3}   DESCRIPTION",
            thin_sep,
        ]

        for attr in ATTRIBUTES:
            val  = self.get_attr(attr)
            desc = self.stat_desc(attr)
            lines.append(f"  {attr.capitalize():<16} {val:>3}   {desc}")

        lines += [
            thin_sep,
            f"  Max HP:         {self.max_hp}",
            f"  Height:         {h_ft}'{h_in}\"",
            f"  Weight:         {self.weight_lbs} lbs",
            thin_sep,
            f"  Armor:          {self.armor  or 'None'}",
            f"  Helm:           {self.helm   or 'None'}",
            f"  Primary:        {self.primary_weapon}",
            f"  Secondary:      {self.secondary_weapon}",
            f"  Backup:         {self.backup_weapon or 'None'}",
            thin_sep,
            "  STRATEGIES:",
            f"  {'#':<4} {'Trigger':<32} {'Style':<18} Act  Aim              Def",
            thin_sep,
        ]

        for i, strat in enumerate(self.strategies, 1):
            lines.append(
                f"  {i:<4} {strat.trigger:<32} {strat.style:<18} "
                f"{strat.activity:<5}{strat.aim_point:<17}{strat.defense_point}"
            )
        lines.append(
            f"  {'D':<4} Always used if no trigger matches above."
        )

        lines += [thin_sep, "  TRAINING QUEUE:"]
        if self.trains:
            for i, t in enumerate(self.trains, 1):
                lines.append(f"    {i}. {t.replace('_',' ').title()}")
        else:
            lines.append("    (none assigned)")

        lines += [thin_sep, "  PERMANENT INJURIES:"]
        lines.append(self.injuries.summary())

        # Skills summary — only show trained ones
        trained = [(s, lvl) for s, lvl in self.skills.items() if lvl > 0]
        if trained:
            lines += [thin_sep, "  SKILLS:"]
            for sk, lvl in sorted(trained, key=lambda x: -x[1]):
                lines.append(
                    f"    {sk.replace('_',' ').title():<20} {SKILL_LEVEL_NAMES[lvl]}"
                )

        lines.append(separator)
        return "\n".join(lines)

    def fight_header(self) -> dict:
        """
        Return a dictionary of values for the fight header comparison block.
        Used by the narrative engine to build the side-by-side display.
        """
        return {
            "name":        self.name.upper(),
            "record":      self.record_str,
            "race_gender": f"{self.race.name.upper()} {self.gender.upper()}",
            "popularity":  self.popularity,
            "height_in":   self.height_in,
            "weight_lbs":  self.weight_lbs,
            "armor":       self.armor  or "NONE",
            "helm":        self.helm   or "NONE",
            "main_weapon": self.primary_weapon.upper(),
            "off_weapon":  self.secondary_weapon.upper(),
            "spare":       (self.backup_weapon or "NONE").upper(),
            "str_desc":    self.stat_desc("strength"),
            "dex_desc":    self.stat_desc("dexterity"),
            "con_desc":    self.stat_desc("constitution"),
            "int_desc":    self.stat_desc("intelligence"),
            "size_desc":   self.stat_desc("size"),
        }

    # =========================================================================
    # SERIALIZATION
    # =========================================================================

    _INJURY_DISPLAY = {
        1: "annoying",   2: "bothersome",    3: "irritating",
        4: "troublesome", 5: "painful",      6: "dreadful",
        7: "incapacitating", 8: "devastating", 9: "fatal",
    }
    _INJURY_LOCS = ["head", "chest", "abdomen", "primary_arm",
                    "secondary_arm", "primary_leg", "secondary_leg"]

    def _build_injuries_text(self) -> list:
        """Return a formatted list of active injuries for UI display."""
        lines = []
        for loc in self._INJURY_LOCS:
            level = self.injuries.get(loc)
            if level > 0:
                display_loc  = loc.replace("_", " ").title()
                desc = self._INJURY_DISPLAY.get(level, f"level {level}")
                article = "an" if desc[0] in "aeiou" else "a"
                lines.append(f"Has {article} {desc} ({level}) injury to the {display_loc}")
        return lines

    def to_dict(self) -> dict:
        """Serialize the warrior to a JSON-compatible dictionary."""
        # Build formatted skills list for UI display
        _skill_templates = {
            1: "Has novice skill ({n}) in {s}",
            2: "Has some skill ({n}) in {s}",
            3: "Is skilled ({n}) in {s}",
            4: "Has good skill ({n}) in {s}",
            5: "Has very good skill ({n}) in {s}",
            6: "Has excellent skill ({n}) in {s}",
            7: "Is an expert ({n}) in {s}",
            8: "Has incredible skill ({n}) in {s}",
            9: "Is a master ({n}) in {s}",
        }
        skills_text = [
            _skill_templates.get(level, "Has skill level {n} in {s}").format(
                n=level, s=skill_name.replace("_", " ").title()
            )
            for skill_name, level in sorted(self.skills.items())
            if level > 0
        ]
        return {
            "name":            self.name,
            "race":            self.race.name,
            "gender":          self.gender,
            "strength":        self.strength,
            "dexterity":       self.dexterity,
            "constitution":    self.constitution,
            "intelligence":    self.intelligence,
            "presence":        self.presence,
            "size":            self.size,
            "max_hp":          self.max_hp,
            "height_in":       self.height_in,
            "weight_lbs":      self.weight_lbs,
            "wins":            self.wins,
            "losses":          self.losses,
            "kills":           self.kills,
            "monster_kills":   self.monster_kills,
            "total_fights":    self.total_fights,
            "armor":           self.armor,
            "helm":            self.helm,
            "primary_weapon":  self.primary_weapon,
            "secondary_weapon":self.secondary_weapon,
            "backup_weapon":   self.backup_weapon,
            "skills":          self.skills,
            "skills_text":     skills_text,
            "injuries":        self.injuries.to_dict(),
            "injuries_text":   self._build_injuries_text(),
            "strategies": [s.to_dict() for s in self.strategies],
            "trains":          self.trains,
            "blood_cry":       self.blood_cry,
            "luck":            self.luck,
            "attribute_gains":  self.attribute_gains,
            "popularity":      self.popularity,
            "recognition":     self.recognition,
            "streak":          self.streak,
            "turns_active":    self.turns_active,
            "want_monster_fight": self.want_monster_fight,
            "want_retire":     self.want_retire,
            "avoid_warriors":  self.avoid_warriors,
            "is_dead":         self.is_dead,
            "ascended_to_monster": self.ascended_to_monster,
            "training_weight_bonus": self.training_weight_bonus,
            "killed_by":       self.killed_by,
            "initial_stats":   self.initial_stats,
            "fight_history":   self.fight_history,
            "favorite_weapon": self.favorite_weapon,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Warrior":
        """Deserialize a Warrior from a saved dictionary."""
        w = cls(
            name         = data["name"],
            race_name    = data["race"],
            gender       = data["gender"],
            strength     = data["strength"],
            dexterity    = data["dexterity"],
            constitution = data["constitution"],
            intelligence = data["intelligence"],
            presence     = data["presence"],
            size         = data["size"],
        )
        w.wins         = data.get("wins",         0)
        w.losses       = data.get("losses",       0)
        w.kills        = data.get("kills",  data.get("draws", 0))  # migrate old saves
        w.monster_kills = data.get("monster_kills", 0)
        w.total_fights = data.get("total_fights", 0)

        w.armor            = data.get("armor")
        w.helm             = data.get("helm")
        w.primary_weapon   = data.get("primary_weapon",   "Open Hand")
        w.secondary_weapon = data.get("secondary_weapon", "Open Hand")
        w.backup_weapon    = data.get("backup_weapon")

        # Ensure all skills are present, initializing missing ones to 0
        w.skills = {skill: 0 for skill in ALL_SKILLS}
        if "skills" in data and isinstance(data["skills"], dict):
            w.skills.update(data["skills"])
        w.blood_cry    = data.get("blood_cry",  "")
        w.luck         = data.get("luck", random.randint(1, 30))  # retroactively assign if missing
        w.attribute_gains = data.get("attribute_gains", {"strength":0,"dexterity":0,"constitution":0,"intelligence":0,"presence":0})
        w.popularity   = data.get("popularity", 0)
        w.recognition  = data.get("recognition", 0)
        w.streak            = data.get("streak", 0)
        w.turns_active      = data.get("turns_active", 0)
        w.want_monster_fight= data.get("want_monster_fight", False)
        w.want_retire       = data.get("want_retire", False)
        w.avoid_warriors    = data.get("avoid_warriors", [])
        w.is_dead           = data.get("is_dead", False)
        w.ascended_to_monster = data.get("ascended_to_monster", False)
        w.training_weight_bonus = data.get("training_weight_bonus", 0)
        w.killed_by         = data.get("killed_by", "")
        w.ascended_to_monster = data.get("ascended_to_monster", False)
        w.initial_stats  = data.get("initial_stats")
        # Backfill for warriors saved before initial_stats was tracked.
        # Using current values as the baseline means past gains won't show the
        # parenthetical, but any NEW training increase will display "16 (15)".
        if w.initial_stats is None:
            w.initial_stats = {attr: getattr(w, attr) for attr in ATTRIBUTES}
        w.fight_history  = data.get("fight_history", [])
        w.trains     = data.get("trains",     [])
        w.favorite_weapon = data.get("favorite_weapon", "")
        if not w.favorite_weapon:
            assign_favorite_weapon(w)

        # Load injuries
        inj_data = data.get("injuries", {})
        w.injuries.from_dict(inj_data)

        # Load strategies
        strat_data = data.get("strategies", [])
        if strat_data:
            w.strategies = [Strategy.from_dict(s) for s in strat_data]

        # Recalculate all derived values
        w.max_hp = w._calc_max_hp()
        w.current_hp = w.max_hp
        w.height_in, w.weight_lbs = w._calc_measurements()
        
        # Recalculate streak from fight_history to ensure it's accurate
        # (especially important when loading downloaded league data)
        w.recalculate_streak()

        return w


# =============================================================================
# FAVORITE WEAPON ASSIGNMENT
# =============================================================================

def assign_favorite_weapon(warrior: "Warrior") -> None:
    """
    Assign a favorite weapon to a warrior based on their race and stats.
    This is called after warrior creation and never changes.
    
    Rules:
      - Tabaxi: light/fast weapons (Dagger, Short Sword, Scimitar, Hatchet, Javelin, 
                Stiletto, Bola, Heavy Barbed Whip)
      - Half-Orc: big damage weapons (War Flail, Great Axe, Great Sword, War Hammer, 
                  Great Pick, Battle Flail, Maul)
      - Dwarf: axes, hammers, spears, shields (Battle Axe, War Hammer, Boar Spear, 
               Long Spear, Target Shield, Halberd)
      - Elf: small/fast blades, thrown weapons (Dagger, Short Sword, Stiletto, Javelin, 
             Epee, Scimitar)
      - Halfling: small/light weapons, martial-friendly (Dagger, Short Sword, Hatchet, 
                  Buckler, Open Hand, Knife)
      - Human: broad balanced weapons (Short Sword, Military Pick, Morning Star, 
               Boar Spear, War Hammer)
      - Goblin: light/dirty fighting (Dagger, Short Sword, Hatchet, Javelin, Bola)
      - Gnome: swords & hammers (Short Sword, Longsword, Hammer, War Hammer, Mace)
      - Lizardfolk: martial + light/medium (Short Spear, Long Spear, Trident, War Hammer, 
                    Battle Axe, Martial Combat via Open Hand)
      
    STR/DEX bias: Heavy weapons favor high STR, light weapons favor high DEX.
    """
    race_name = warrior.race.name
    str_val = warrior.strength
    dex_val = warrior.dexterity
    
    # Define weapon pools per race
    RACE_WEAPONS = {
        "Tabaxi": ["Dagger", "Short Sword", "Scimitar", "Hatchet", "Javelin", 
                   "Stiletto", "Bola", "Heavy Barbed Whip"],
        "Half-Orc": ["War Flail", "Great Axe", "Great Sword", "War Hammer", 
                     "Great Pick", "Battle Flail", "Maul"],
        "Dwarf": ["Battle Axe", "War Hammer", "Boar Spear", "Long Spear", 
                  "Target Shield", "Halberd"],
        "Elf": ["Dagger", "Short Sword", "Stiletto", "Javelin", "Epee", "Scimitar"],
        "Halfling": ["Dagger", "Short Sword", "Hatchet", "Buckler", "Open Hand", "Knife"],
        "Human": ["Short Sword", "Military Pick", "Morning Star", "Boar Spear", "War Hammer"],
        "Goblin": ["Dagger", "Short Sword", "Hatchet", "Javelin", "Bola"],
        "Gnome": ["Short Sword", "Longsword", "Hammer", "War Hammer", "Mace"],
        "Lizardfolk": ["Short Spear", "Long Spear", "Trident", "War Hammer", 
                       "Battle Axe", "Open Hand"],
    }
    
    # Get weapons for this race (fallback to Human if race not defined)
    available_weapons = RACE_WEAPONS.get(race_name, RACE_WEAPONS["Human"])
    
    # Apply STR/DEX weighting to weapon selection
    # For simplicity: warriors with high STR get favorite from heavier options,
    # high DEX get favorite from lighter options
    weighted_choices = []
    
    for weapon_name in available_weapons:
        weight = 1
        
        # Light weapons favor DEX
        light_weapons = {"Dagger", "Stiletto", "Knife", "Short Sword", "Javelin", 
                        "Epee", "Hatchet", "Buckler", "Bola", "Open Hand"}
        if weapon_name in light_weapons:
            dex_bonus = max(0, dex_val - 12) * 0.1  # DEX 12→1.0x, DEX 18→1.6x
            weight = 1 + dex_bonus
        
        # Heavy weapons favor STR
        heavy_weapons = {"Maul", "Great Axe", "War Flail", "Great Sword", "Great Pick",
                        "Battle Flail", "War Hammer", "Long Spear", "Halberd"}
        if weapon_name in heavy_weapons:
            str_bonus = max(0, str_val - 12) * 0.1  # STR 12→1.0x, STR 18→1.6x
            weight = 1 + str_bonus
        
        weighted_choices.append((weapon_name, weight))
    
    # Select one weapon using weighted random
    if weighted_choices:
        weapons, weights = zip(*weighted_choices)
        favorite = random.choices(weapons, weights=weights, k=1)[0]
        warrior.favorite_weapon = favorite
    else:
        # Fallback (shouldn't happen)
        warrior.favorite_weapon = "Open Hand"


# =============================================================================
# WARRIOR ROLL-UP (CREATION) SYSTEM
# =============================================================================

# Base stat generation constants.
BASE_STAT_MIN   = 3    # No single base stat can be below this
BASE_STAT_MAX   = 21   # No single base stat can be above this
BASE_STAT_TOTAL = 55   # All six base stats must sum to exactly this


def generate_base_stats() -> Dict[str, int]:
    """
    Generate 6 base stats that sum to exactly BASE_STAT_TOTAL (55),
    with each individual stat in the range [BASE_STAT_MIN, BASE_STAT_MAX] (3-21).

    Algorithm:
      1. Assign every stat its floor (3), consuming 18 of the 55 points.
      2. Distribute the remaining 37 points one at a time, randomly,
         skipping any stat that has already reached its ceiling (21).
      3. A light shuffle swaps small amounts between pairs of stats
         so the result is not always front-loaded toward the first attributes.

    Guarantees: sum == 55, every value in [3, 21], genuine variety.
    """
    remaining = BASE_STAT_TOTAL - BASE_STAT_MIN * len(ATTRIBUTES)  # = 37

    stats = {attr: BASE_STAT_MIN for attr in ATTRIBUTES}

    while remaining > 0:
        available = [a for a in ATTRIBUTES if stats[a] < BASE_STAT_MAX]
        if not available:
            break
        chosen = random.choice(available)
        stats[chosen] += 1
        remaining -= 1

    # Light shuffle: randomly redistribute small amounts between pairs
    # so early attributes are not consistently higher than late ones.
    attrs = list(ATTRIBUTES)
    for _ in range(12):
        a, b = random.sample(attrs, 2)
        shift    = random.randint(1, 3)
        can_take = stats[a] - BASE_STAT_MIN
        can_give = BASE_STAT_MAX - stats[b]
        actual   = min(shift, can_take, can_give)
        if actual > 0:
            stats[a] -= actual
            stats[b] += actual

    return stats


def max_addable(base_stats: Dict[str, int], attr: str) -> int:
    """
    Return the maximum points a player may add to a single attribute.

    Rules (both must be satisfied simultaneously):
      - Hard cap per stat:    ROLLUP_MAX_PER_STAT (7)
      - Hard ceiling per stat: STAT_MAX (25) — adding more would push the
        final value over 25, which is not allowed.

    Example: base Strength = 20 → max addable = min(7, 25-20) = 5.
    """
    return min(ROLLUP_MAX_PER_STAT, STAT_MAX - base_stats.get(attr, STAT_MIN))


def validate_additions(base_stats: Dict[str, int], additions: Dict[str, int]) -> Dict[str, int]:
    """
    Validate a point-allocation dictionary and return the final stats.

    Rules enforced:
      1. Total added = exactly ROLLUP_POINTS (16).
      2. No individual addition is negative.
      3. Each stat's addition <= max_addable(base, attr):
           = min(7, 25 - base_stat)
         This means a high base stat (e.g. 20) limits how many points
         can be added to it (max 5 in that case), even though the global
         per-stat cap is 7.

    Raises ValueError with a clear message on any violation.
    """
    total_added = sum(additions.values())
    if total_added != ROLLUP_POINTS:
        raise ValueError(
            f"Must spend exactly {ROLLUP_POINTS} points. You spent {total_added}."
        )

    for attr, pts in additions.items():
        if pts < 0:
            raise ValueError(f"Cannot add negative points to '{attr}'.")
        cap = max_addable(base_stats, attr)
        if pts > cap:
            base = base_stats.get(attr, STAT_MIN)
            raise ValueError(
                f"Cannot add {pts} to {attr.capitalize()} "
                f"(base {base} + {pts} = {base + pts}, exceeds max of {STAT_MAX}). "
                f"Max addable: {cap}."
            )

    return {
        attr: max(STAT_MIN, min(STAT_MAX, base_stats.get(attr, STAT_MIN) + additions.get(attr, 0)))
        for attr in ATTRIBUTES
    }


def ai_rollup(base_stats: Dict[str, int], race_name: str) -> Dict[str, int]:
    """
    Distribute 16 rollup points for an AI warrior, weighted by race preference.

    APPROX: Each race has a preferred stat profile based on the guide's descriptions.
    Points are placed one at a time using weighted random selection, stopping when
    the 7-per-stat cap or the 16-total cap is reached.
    """

    # Stat weight tables per race — higher weight = more likely to invest here.
    # Derived from guide descriptions of each race's strengths.
    RACE_WEIGHTS = {
        "Human": {
            "strength": 2, "dexterity": 2, "constitution": 3,
            "intelligence": 2, "presence": 2, "size": 2,
        },
        "Half-Orc": {
            "strength": 4, "dexterity": 1, "constitution": 2,
            "intelligence": 1, "presence": 1, "size": 4,
        },
        "Halfling": {
            "strength": 1, "dexterity": 5, "constitution": 2,
            "intelligence": 2, "presence": 2, "size": 1,
        },
        "Dwarf": {
            "strength": 3, "dexterity": 2, "constitution": 4,
            "intelligence": 1, "presence": 1, "size": 2,
        },
        "Half-Elf": {
            "strength": 2, "dexterity": 3, "constitution": 2,
            "intelligence": 2, "presence": 2, "size": 2,
        },
        "Elf": {
            "strength": 1, "dexterity": 5, "constitution": 2,
            "intelligence": 2, "presence": 2, "size": 1,
        },
    }

    weights   = RACE_WEIGHTS.get(race_name, {attr: 2 for attr in ATTRIBUTES})
    additions = {attr: 0 for attr in ATTRIBUTES}
    remaining = ROLLUP_POINTS

    while remaining > 0:
        # Only consider stats that haven't hit their effective cap.
        # Cap = min(ROLLUP_MAX_PER_STAT, STAT_MAX - base) so we never
        # push a stat over 25 even if the base started high.
        available = [
            a for a in ATTRIBUTES
            if additions[a] < max_addable(base_stats, a)
        ]
        if not available:
            break
        stat_weights = [weights.get(a, 1) for a in available]
        chosen = random.choices(available, weights=stat_weights, k=1)[0]
        additions[chosen] += 1
        remaining -= 1

    return validate_additions(base_stats, additions)


def create_warrior_interactive(base_stats: Dict[str, int] = None) -> Optional["Warrior"]:
    """
    Interactive CLI roll-up flow for a human player.
    Guides the player through naming, race, gender, and point allocation.
    Returns a fully created Warrior, or None if the player cancels.
    """
    if base_stats is None:
        base_stats = generate_base_stats()

    print("\n" + "=" * 60)
    print("  NEW WARRIOR ROLL-UP")
    print("=" * 60)
    print(f"\n  Pre-generated base stats (randomly rolled):")
    print(f"  {'Attribute':<16} {'Base':>4}")
    print(f"  {'-'*22}")
    for attr in ATTRIBUTES:
        print(f"  {attr.capitalize():<16} {base_stats[attr]:>4}")
    print(
        f"\n  You have {ROLLUP_POINTS} points to add (max {ROLLUP_MAX_PER_STAT} per attribute)."
    )

    # --- Name ---
    name = input("\n  Warrior name: ").strip()
    if not name:
        print("  No name given — cancelling.")
        return None

    # --- Race ---
    playable = list_playable_races()
    print(f"\n  Playable races: {', '.join(playable)}")
    race_name = ""
    while race_name not in playable:
        raw = input("  Choose race: ").strip()
        # Case-insensitive match
        match = next((r for r in playable if r.lower() == raw.lower()), None)
        if match:
            race_name = match
        else:
            print(f"  Not a valid race. Options: {', '.join(playable)}")

    # --- Gender ---
    gender = ""
    while gender not in ("Male", "Female"):
        raw = input("  Gender (Male / Female): ").strip().title()
        if raw in ("Male", "Female"):
            gender = raw
        else:
            print("  Please enter 'Male' or 'Female'.")

    # --- Point Distribution ---
    additions   = {attr: 0 for attr in ATTRIBUTES}
    points_left = ROLLUP_POINTS

    print(f"\n  Distribute {ROLLUP_POINTS} points.")
    print(f"  Rules: max {ROLLUP_MAX_PER_STAT} per stat AND final value cannot exceed {STAT_MAX}.")
    print(f"  The 'Max add' column shows the real limit for each stat given its base value.\n")
    print(f"  {'Attribute':<16} {'Base':>4}  {'Max add':>7}  {'Final will be'}")
    print(f"  {'-'*50}")
    for attr in ATTRIBUTES:
        cap   = max_addable(base_stats, attr)
        final = base_stats[attr]   # will update as player adds
        print(f"  {attr.capitalize():<16} {base_stats[attr]:>4}  {cap:>7}")
    print()

    for attr in ATTRIBUTES:
        cap = max_addable(base_stats, attr)
        while True:
            try:
                p = (
                    f"    {attr.capitalize():<16} "
                    f"(base {base_stats[attr]:>2}, max add {cap}, "
                    f"{points_left} pts left): "
                )
                val = int(input(p))
                if val < 0:
                    print("    Cannot add negative points.")
                elif val > cap:
                    print(
                        f"    Cannot add {val} — base is {base_stats[attr]}, "
                        f"so max addable is {cap} (would exceed {STAT_MAX})."
                    )
                elif val > points_left:
                    print(f"    Only {points_left} points remaining.")
                else:
                    additions[attr] = val
                    points_left -= val
                    final = base_stats[attr] + val
                    print(f"    → {attr.capitalize()} will be {final}")
                    break
            except ValueError:
                print("    Please enter a whole number.")

    # Auto-spend any leftover points — player chose to leave some unspent.
    # Distribute to attributes with the most remaining headroom first.
    if points_left > 0:
        print(f"\n  {points_left} unspent point(s) — auto-distributing to highest-headroom stats...")
        sortable = sorted(ATTRIBUTES, key=lambda a: max_addable(base_stats, a) - additions[a], reverse=True)
        for attr in sortable:
            if points_left <= 0:
                break
            headroom = max_addable(base_stats, attr) - additions[attr]
            add = min(points_left, headroom)
            if add > 0:
                additions[attr] += add
                points_left    -= add
                print(f"    Auto-added {add} to {attr.capitalize()}")

    # --- Validate & Create ---
    try:
        final_stats = validate_additions(base_stats, additions)
    except ValueError as e:
        print(f"\n  ERROR: {e}")
        return None

    warrior = Warrior(
        name=name, race_name=race_name, gender=gender, **final_stats
    )
    warrior.luck = random.randint(1, 30)
    assign_favorite_weapon(warrior)

    print("\n" + warrior.stat_block())
    print(f"  Luck factor: {warrior.luck}/30")
    print("\n  Warrior created successfully!")
    return warrior


def create_warrior_ai(
    race_name: Optional[str] = None,
    name: Optional[str]      = None,
    gender: Optional[str]    = None,
) -> Warrior:
    """
    Create a fully formed AI warrior with procedurally generated stats.
    Used for rival managers, replacement warriors, and scaled peasants.
    """
    if race_name is None:
        race_name = random.choice(list_playable_races())

    if name is None:
        name = f"Fighter_{random.randint(1000, 9999)}"

    if gender is None:
        gender = random.choice(["Male", "Female"])

    base  = generate_base_stats()
    final = ai_rollup(base, race_name)

    w = Warrior(name=name, race_name=race_name, gender=gender, **final)
    w.luck = random.randint(1, 30)
    assign_favorite_weapon(w)
    return w
