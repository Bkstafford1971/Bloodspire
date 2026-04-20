# =============================================================================
# races.py — BLOODSPIRE Race Definitions
# =============================================================================
# Contains all 10 playable races and 2 NPC races with their modifiers.
#
# DESIGN PHILOSOPHY (Zero-Sum):
#   - Median warrior (all stats = 12) is true baseline
#   - Every bonus has a proportional penalty
#   - Luck (1-30) is universal and naturally amplifies strengths/weaknesses
#   - No "super race" — all are viable but require different playstyles
# =============================================================================

from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# RACIAL MODIFIER DATACLASS
# ---------------------------------------------------------------------------

@dataclass
class RacialModifiers:
    """
    Numeric combat modifiers applied to a warrior based on race.
    These are applied at combat time, not baked into base stats,
    so the raw stat values always reflect the warrior's true attributes.
    """

    # --- Hit Points ---
    hp_bonus: int = 0           # Flat bonus/penalty to max HP

    # --- Damage ---
    damage_bonus: int = 0       # Flat bonus to damage dealt per hit
    damage_penalty: int = 0     # Flat penalty to damage dealt per hit

    # --- Attack Rate & Initiative ---
    # Stored as a modifier to "actions per minute" on a 0-100 internal scale.
    # APPROX: Each point ≈ roughly 0.1 attacks/minute at base dex.
    attack_rate_bonus: int = 0
    attack_rate_penalty: int = 0
    initiative_bonus: int = 0   # Bonus to initiative rolls (new)
    
    # --- Attributes ---
    strength_penalty: int = 0   # Flat penalty to STR (for races that are physically weak)

    # --- Defense ---
    dodge_bonus: int = 0
    dodge_penalty: int = 0
    parry_bonus: int = 0
    parry_penalty: int = 0

    # --- Special Flags (True/False abilities) ---
    armor_capacity_bonus: bool = False   # Dwarf: can carry heavier armor than STR alone allows
    shield_bonus: bool = False           # Dwarf: extra bonus when a shield is equipped
    dual_weapon_bonus: bool = False      # Elf: bonus when both hands hold weapons
    martial_combat_bonus: bool = False   # Halfling: extra MC effectiveness
    trains_stats_faster: bool = False    # Human: attributes improve more easily
    fewer_perms: bool = False            # Human: lower permanent injury chance
    bigger_weapons_bonus: bool = False   # Half-Elf: counts as 1 STR higher for weapon weight reqs
    
    # --- New Race Abilities ---
    thrown_mastery: bool = False         # Goblin: +2 bonus to Opportunity Throw, throwables 1 weight lighter
    scavenger: bool = False              # Goblin: high chance to notice and pick up dropped weapons
    heavy_weapon_penalty: bool = False   # Goblin & Tabaxi: suffer penalties for weight 4.0+ or two-handed
    counterstrike_mastery: bool = False  # Gnome: strong bonus on successful parries + ripostes
    tactician_edge: bool = False         # Gnome: better vs aggressive opponents, worse vs methodical
    natural_armor: bool = False          # Lizardfolk: scales = Scale armor protection, layering rules
    natural_weapon_bonus: bool = False   # Lizardfolk: +3 damage with Martial Combat / claws / tail
    acrobatic_advantage: bool = False    # Tabaxi: high resist to knockdowns, acrobatic maneuvers on good rolls
    frenzy_ability: bool = False         # Tabaxi: +3 attack rate burst once per fight for 3-4 actions
    spear_exception: bool = False        # Tabaxi: spears exempt from heavy weapon penalty

    # --- Flavor / Soft Mechanics ---
    preferred_weapons: List[str] = field(default_factory=list)
    weak_weapons: List[str] = field(default_factory=list)
    favored_opponents: str = ""
    disfavored_opponents: str = ""


# ---------------------------------------------------------------------------
# RACE DATACLASS
# ---------------------------------------------------------------------------

@dataclass
class Race:
    """Defines a single race in BLOODSPIRE."""

    name: str
    is_playable: bool
    description: str
    modifiers: RacialModifiers

    # Physical baselines at average SIZE (12-13), male.
    # Female gets ~97% height, ~90% weight (guide mentions cosmetic differences).
    base_height_in: int    # inches
    base_weight_lbs: int   # pounds

    # Favored/weak enemy races — deliberately None here so discovery is gameplay.
    # The guide says: "discovering this is part of the fun for a new player."
    favored_enemy_race: Optional[str] = None
    weak_against_race: Optional[str] = None


# ---------------------------------------------------------------------------
# ALL RACE DEFINITIONS
# ---------------------------------------------------------------------------

RACES: dict[str, Race] = {

    # =========================================================================
    "Human": Race(
        name="Human",
        is_playable=True,
        description=(
            "The adaptable everyman. No extreme strengths or weaknesses, "
            "but supremely adaptable. Humans train attributes more easily "
            "and suffer fewer permanent injuries."
        ),
        base_height_in=67,    # 5'7" male SIZE-12 midpoint (range 5'2"–6'4")
        base_weight_lbs=165,
        modifiers=RacialModifiers(
            trains_stats_faster=True,   # +20% training speed
            fewer_perms=True,           # -20% permanent injury chance
            preferred_weapons=[],
            favored_opponents="All races — Humans fight well against everyone.",
            disfavored_opponents="None in particular.",
        ),
    ),

    # =========================================================================
    "Half-Orc": Race(
        name="Half-Orc",
        is_playable=True,
        description=(
            "Pure brute force. Devastating damage and high durability, "
            "but slow, clumsy, and easy to outmaneuver."
        ),
        base_height_in=75,    # 6'3" male SIZE-12 midpoint (range 5'5"–7'6")
        base_weight_lbs=259,
        modifiers=RacialModifiers(
            damage_bonus=8,              # Massive offensive payoff
            hp_bonus=6,                  # Very tough
            attack_rate_penalty=4,       # Slow swings
            initiative_bonus=-3,         # Slow to act
            dodge_penalty=3,
            parry_penalty=3,
            preferred_weapons=[
                "War Flail", "Great Axe", "Great Sword", "War Hammer",
                "Battle Flail", "Halberd", "Great Pick", "Tower Shield",
            ],
            favored_opponents="Very small opponents.",
            disfavored_opponents="Quick warriors with thrusting weapons and good dodge.",
        ),
    ),

    # =========================================================================
    "Halfling": Race(
        name="Halfling",
        is_playable=True,
        description=(
            "Infuriatingly hard to hit. Extremely fast and mobile, "
            "but extremely fragile with very light damage output."
        ),
        base_height_in=46,    # 3'10" male SIZE-12 midpoint (range 3'1"–5'1")
        base_weight_lbs=49,
        modifiers=RacialModifiers(
            dodge_bonus=7,               # Hardest to hit in the game
            attack_rate_bonus=4,         # Very fast
            martial_combat_bonus=True,
            damage_penalty=6,            # Biggest damage penalty in game
            parry_penalty=3,
            hp_bonus=-6,                 # Extremely fragile
            preferred_weapons=[
                "Short Sword", "Stiletto", "Hatchet", "Quarterstaff",
                "Javelin", "Bladed Flail", "Hammer",
            ],
            weak_weapons=[
                "Maul", "Great Axe", "Great Sword", "Halberd",
                "Battle Flail", "Ball & Chain",
            ],
            favored_opponents="Most opponents — Halflings are balanced offensively and defensively.",
            disfavored_opponents="Warriors who specifically fight small opponents well (e.g. Dwarves).",
        ),
    ),

    # =========================================================================
    "Dwarf": Race(
        name="Dwarf",
        is_playable=True,
        description=(
            "The ultimate tank. Absorbs massive punishment and parries "
            "masterfully, but very slow and poor at dodging."
        ),
        base_height_in=50,    # 4'2" male SIZE-12 midpoint (range 3'6"–5'2")
        base_weight_lbs=195,  # Dense — notably heavier than height implies
        modifiers=RacialModifiers(
            hp_bonus=12,                 # Highest HP in game
            damage_bonus=3,
            parry_bonus=6,               # Master parriers
            armor_capacity_bonus=True,
            shield_bonus=True,
            attack_rate_penalty=3,
            dodge_penalty=4,             # Very poor dodge
            preferred_weapons=[
                "Battle Axe", "Fransisca", "Great Axe", "Morningstar",
                "War Hammer", "Boar Spear", "Target Shield", "Net", "Trident",
            ],
            weak_weapons=["Halberd", "Pole Axe"],
            favored_opponents="Very small and very large opponents — Dwarves have something to prove against both.",
            disfavored_opponents="Mid-sized opponents with average stats.",
        ),
    ),

    # =========================================================================
    "Half-Elf": Race(
        name="Half-Elf",
        is_playable=True,
        description=(
            "Versatile and capable. Slight edge in weapon handling "
            "with no major weaknesses or strengths."
        ),
        base_height_in=64,    # 5'4" male SIZE-12 midpoint (range 5'0"–6'0")
        base_weight_lbs=144,
        modifiers=RacialModifiers(
            bigger_weapons_bonus=True,   # Can use slightly heavier weapons
            attack_rate_bonus=1,
            dodge_bonus=2,
            damage_bonus=1,              # Mild all-rounder bonuses
            preferred_weapons=[
                "Pole Axe", "Bastard Sword", "Long Sword", "Scimitar",
                "Battle Flail", "Scythe", "Javelin", "Broadsword",
            ],
            weak_weapons=[],
            favored_opponents="Average, mid-tier opponents.",
            disfavored_opponents=(
                "Warriors who can take and dish out a lot of damage — "
                "Half-Elves share this weakness with most non-tanks."
            ),
        ),
    ),

    # =========================================================================
    "Elf": Race(
        name="Elf",
        is_playable=True,
        description=(
            "Elusive speed demons. Masters of dual-wielding and evasion, "
            "but extremely fragile."
        ),
        base_height_in=62,    # 5'2" male SIZE-12 midpoint (range 4'8"–5'11")
        base_weight_lbs=129,
        modifiers=RacialModifiers(
            dodge_bonus=5,
            attack_rate_bonus=5,
            dual_weapon_bonus=True,
            hp_bonus=-7,                 # Most fragile race
            damage_penalty=2,
            preferred_weapons=[
                "Dagger", "Short Sword", "Scimitar", "Scythe", "Flail",
                "Javelin", "Stiletto", "Epee",
            ],
            favored_opponents="Light and medium opponents — small, fast weapons struggle vs heavy armor.",
            disfavored_opponents="Large, powerful opponents who can't be taken out with small weapons.",
        ),
    ),

    # =========================================================================
    "Goblin": Race(
        name="Goblin",
        is_playable=True,
        description=(
            "Tiny dirty fighters. Extremely fast and tricky with thrown weapons, "
            "but very weak and fragile."
        ),
        base_height_in=42,    # 3'6" male — tiny
        base_weight_lbs=48,
        modifiers=RacialModifiers(
            attack_rate_bonus=5,
            initiative_bonus=5,
            dodge_bonus=4,
            damage_penalty=6,
            hp_bonus=-7,
            strength_penalty=4,
            thrown_mastery=True,
            scavenger=True,
            heavy_weapon_penalty=True,
            preferred_weapons=[
                "Dagger", "Stiletto", "Short Sword", "Hatchet", "Javelin",
                "Throwing Knife", "Blowgun", "Shortbow",
            ],
            weak_weapons=[
                "Great Axe", "Great Sword", "Halberd", "Battle Flail",
                "Great Pick", "War Flail", "Morning Star", "Maul",
            ],
            favored_opponents="Slow, heavily armored opponents — Goblins can dart in and out.",
            disfavored_opponents="Other fast, evasive opponents. One solid hit usually ends them.",
        ),
    ),

    # =========================================================================
    "Gnome": Race(
        name="Gnome",
        is_playable=True,
        description=(
            "Small, surprisingly tough tacticians. Excel at counterstrikes "
            "and turning aggression against opponents."
        ),
        base_height_in=40,    # 3'4" male — smallest playable race
        base_weight_lbs=85,
        modifiers=RacialModifiers(
            hp_bonus=6,
            trains_stats_faster=True,
            parry_bonus=5,
            counterstrike_mastery=True,
            tactician_edge=True,
            damage_penalty=3,
            attack_rate_penalty=2,
            preferred_weapons=[
                "Short Sword", "Long Sword", "Epee", "Bastard Sword",
                "Hammer", "Mace", "Morningstar", "War Hammer",
            ],
            weak_weapons=[
                "Great Axe", "Battle Axe", "Halberd", "Great Pick",
                "Boar Spear", "Pole Axe", "Pike",
            ],
            favored_opponents="Aggressive warriors with high activity styles — Gnomes punish overcommitment.",
            disfavored_opponents="Methodical, patient fighters with low activity and careful tactics.",
        ),
    ),

    # =========================================================================
    "Lizardfolk": Race(
        name="Lizardfolk",
        is_playable=True,
        description=(
            "Savage reptilian predators. Tough, relentless, with natural "
            "armor and weapons, but cold-blooded and slower to accelerate."
        ),
        base_height_in=72,    # 6'0" male — larger than humans, muscular
        base_weight_lbs=240,  # Muscular / dense
        modifiers=RacialModifiers(
            hp_bonus=9,
            natural_weapon_bonus=True,   # +3 with Martial Combat / claws
            martial_combat_bonus=True,
            natural_armor=True,
            dodge_bonus=2,
            attack_rate_penalty=3,       # Cold-blooded = slower start
            preferred_weapons=[
                "Open Hand", "Dagger", "Stiletto", "Short Sword", "Hatchet",
                "Hammer", "Mace", "Quarterstaff",
            ],
            weak_weapons=[
                "Epee", "Rapier", "Long Sword",  # Not suited to their heavy fighting style
            ],
            favored_opponents="Most opponents — Lizardfolk are well-rounded tanks.",
            disfavored_opponents="None in particular, but heavy armor restricts their natural strengths.",
        ),
    ),

    # =========================================================================
    "Tabaxi": Race(
        name="Tabaxi",
        is_playable=True,
        description=(
            "Lightning-quick acrobatic felines. Best evasion in the game, "
            "but fragile and tire quickly in long fights."
        ),
        base_height_in=58,    # 4'10" male — slightly shorter than average human with feline build
        base_weight_lbs=115,  # Light and lean
        modifiers=RacialModifiers(
            dodge_bonus=7,               # Best pure evasion
            initiative_bonus=5,
            acrobatic_advantage=True,
            frenzy_ability=True,
            hp_bonus=-7,
            strength_penalty=3,
            heavy_weapon_penalty=True,
            preferred_weapons=[
                "Dagger", "Short Sword", "Scimitar", "Epee", "Stiletto",
                "Hatchet", "Javelin", "Scythe", "Spear",
            ],
            weak_weapons=[
                "Great Axe", "Great Sword", "Halberd", "Maul", "Battle Flail",
                "War Flail", "Ball & Chain", "Great Pick",
            ],
            favored_opponents="Most opponents — Tabaxi are hard to hit and difficult to pin down.",
            disfavored_opponents="Heavy hitters and endurance grinders (Dwarf, Lizardfolk, Half-Orc).",
        ),
    ),

    # =========================================================================
    # NPC RACES — Not player-selectable
    # =========================================================================

    "Monster": Race(
        name="Monster",
        is_playable=False,
        description=(
            "Hideous creatures controlled by the game. Fighting a Monster is "
            "essentially a death sentence. Less than a dozen warriors in Pit history "
            "have survived — those few were absorbed into the Monster team."
        ),
        base_height_in=90,    # Enormous — can reach 9'+ at max SIZE
        base_weight_lbs=405,
        modifiers=RacialModifiers(
            # Monsters are intentionally overpowered — these are large fixed bonuses.
            hp_bonus=50,
            damage_bonus=10,
            attack_rate_bonus=5,
            parry_bonus=3,
            dodge_bonus=3,
        ),
    ),

    "Peasant": Race(
        name="Peasant",
        is_playable=False,
        description=(
            "Arena fillers. Peasants are scaled dynamically to the warrior they face "
            "by the matchmaking system. Named individuals: Klud the Bell-Ringer, "
            "Sally Strumpet, Peter the Poet, Fiona Fishwife, Beggar Barleycorn, "
            "Stu the Gravedigger, Gypsy Jezebel, Perceval the Prophet, "
            "Madman Muttermuck, Roger the Shrubber. Never truly eliminated."
        ),
        base_height_in=67,    # Human proportions
        base_weight_lbs=165,
        modifiers=RacialModifiers(),  # All zeros — Peasants are scaled in matchmaking
    ),
}


# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def get_race(name: str) -> Race:
    """
    Retrieve a Race by name (case-insensitive).
    Raises ValueError if the name is not found.
    """
    for key, race in RACES.items():
        if key.lower() == name.lower():
            return race
    valid = ", ".join(RACES.keys())
    raise ValueError(f"Unknown race: '{name}'. Valid options: {valid}")


def list_playable_races() -> List[str]:
    """Return names of all player-selectable races."""
    return [name for name, race in RACES.items() if race.is_playable]


def list_all_races() -> List[str]:
    """Return names of all races including NPC races."""
    return list(RACES.keys())