# =============================================================================
# team.py — BLOODSPIRE Team Class
# =============================================================================
# A team always has exactly 5 warriors.
# When a warrior dies or retires, a replacement slot opens immediately.
# Handles team fights, blood challenges, and manager-level data.
# =============================================================================

from __future__ import annotations
import random
from typing import List, Optional, Dict
from warrior import Warrior, create_warrior_ai
from races  import list_playable_races

TEAM_SIZE = 5   # Guide: "Each team always consists of five individual warriors."


class Team:
    """
    Represents one manager's team of five warriors.

    Key rules enforced here:
      - Roster is always exactly TEAM_SIZE (5) warriors.
      - Dead warriors are replaced immediately with fresh beginners.
      - Warriors who have fought 100 fights may be retired (same as death for now).
      - Up to 3 challenges may be issued per warrior per turn.
      - Blood challenges are available from any team member when a teammate
        is killed (killer must have 5+ fights).
    """

    def __init__(self, team_name: str, manager_name: str, team_id: int = 0):
        self.team_name    : str            = team_name
        self.manager_name : str            = manager_name
        self.team_id      : int            = team_id

        # Active roster — always TEAM_SIZE entries.
        # Slots hold Warrior objects; None means "pending replacement".
        self.warriors: List[Optional[Warrior]] = []

        # Record of warriors who have died or retired (for blood challenge tracking).
        self.fallen_warriors: List[dict] = []
        # Each entry: {"warrior_name": str, "killed_by": str, "killer_fights": int}

        # Blood challenges outstanding: list of dict with blood challenge info
        # Each entry: {
        #   "dead_warrior_name": str,  (the warrior who was killed)
        #   "target_name": str,  (the killer's name)
        #   "challenger_name": Optional[str],  (selected warrior to carry challenge, None = any can carry)
        #   "turns_remaining": int,  (3, 2, 1, then expires)
        #   "status": str,  ("active" or "avenged")
        # }
        self.blood_challenges: List[dict] = []

        # Avoidance system: manager-level avoidances (max 2 slots)
        # Contains manager names to avoid challenges from any warrior on that manager's team (25-30% success)
        self.avoid_managers: List[str] = []

        # Pending challenges: {warrior_name: [challenge_target, ...]}
        self.challenges: Dict[str, List[str]] = {}

        # Archived warriors — dead warriors stored as stat snapshots after replacement
        self.archived_warriors: List[dict] = []

        # Pending replacement rollup bases: {slot_idx: base_stats_dict}
        self.pending_replacements: Dict[int, dict] = {}

        # Rolling turn history for last-5-turns newsletter column
        # Each entry: {"turn": int, "w": int, "l": int, "k": int}
        self.turn_history: List[dict] = []

    # =========================================================================
    # ROSTER MANAGEMENT
    # =========================================================================

    def add_warrior(self, warrior: Warrior) -> bool:
        """
        Add a warrior to the team.
        Returns True if added, False if the team is already full.
        """
        if len(self.warriors) < TEAM_SIZE:
            self.warriors.append(warrior)
            return True
        # Fill a None slot if one exists
        for i, slot in enumerate(self.warriors):
            if slot is None:
                self.warriors[i] = warrior
                return True
        return False   # Team is full

    def fill_roster_with_ai(self):
        """
        Auto-fill any empty or None slots with AI-generated warriors.
        Called during initial team creation and after replacement.
        """
        races = list_playable_races()
        while len(self.warriors) < TEAM_SIZE:
            race   = random.choice(races)
            gender = random.choice(["Male", "Female"])
            w = create_warrior_ai(race_name=race, gender=gender)
            self.warriors.append(w)

        # Replace any None slots too
        for i, slot in enumerate(self.warriors):
            if slot is None:
                race   = random.choice(races)
                gender = random.choice(["Male", "Female"])
                self.warriors[i] = create_warrior_ai(race_name=race, gender=gender)

    def warrior_by_name(self, name: str) -> Optional[Warrior]:
        """Return a warrior by name (case-insensitive), or None."""
        for w in self.warriors:
            if w and w.name.lower() == name.lower():
                return w
        return None

    def warrior_index(self, name: str) -> int:
        """Return roster index for a warrior by name, or -1."""
        for i, w in enumerate(self.warriors):
            if w and w.name.lower() == name.lower():
                return i
        return -1

    @property
    def active_warriors(self) -> List[Warrior]:
        """Return living warriors only — excludes None slots and is_dead warriors."""
        return [w for w in self.warriors if w is not None
                and w.is_alive and not getattr(w, "is_dead", False)]

    @property
    def is_full(self) -> bool:
        return (
            len(self.warriors) == TEAM_SIZE
            and all(w is not None for w in self.warriors)
        )

    # =========================================================================
    # DEATH & REPLACEMENT
    # =========================================================================

    def kill_warrior(
        self,
        warrior: Warrior,
        killed_by: str = "Unknown",
        killer_fights: int = 0,
    ) -> int:
        """
        Mark a warrior as dead but keep them in their roster slot until the
        player creates a replacement via the Replacement tab in the GUI.
        Returns the slot index.

        The warrior stays in self.warriors[idx] with is_dead=True so they
        appear in the tree with a skull icon. The Replacement tab activates,
        letting the player roll up and name a new warrior. Once the player
        saves the replacement, confirm_replacement() archives the dead warrior
        and places the new one in the slot.
        """
        idx = self.warrior_index(warrior.name)
        if idx == -1:
            raise ValueError(f"Warrior '{warrior.name}' not found on team '{self.team_name}'.")

        warrior.is_dead   = True
        warrior.killed_by = killed_by

        self.fallen_warriors.append({
            "warrior_name" : warrior.name,
            "killed_by"    : killed_by,
            "killer_fights": killer_fights,
            "slot_idx"     : idx,
        })

        if killer_fights >= 5:
            self.blood_challenges.append({
                "dead_warrior_name": warrior.name,
                "target_name": killed_by,
                "challenger_name": None,  # Manager can select later
                "turns_remaining": 3,
                "status": "active",
            })
            print(
                f"  *** BLOOD CHALLENGE available against '{killed_by}' "
                f"for the death of {warrior.name}! ***"
            )

        print(f"  {warrior.name} has fallen. Replacement slot open at position {idx}.")
        return idx

    def confirm_replacement(self, slot_idx: int, new_warrior: Warrior) -> bool:
        """
        Called when the player finishes building a replacement warrior.
        Archives the dead warrior as a frozen snapshot, then places the new
        warrior in the slot. Returns True on success.
        """
        if slot_idx < 0 or slot_idx >= len(self.warriors):
            return False
        dead = self.warriors[slot_idx]
        if dead is None or not getattr(dead, "is_dead", False):
            return False

        # Snapshot the dead warrior for the archives tab
        snapshot = dead.to_dict()
        snapshot["archived_killed_by"] = dead.killed_by
        snapshot["archived_turns"]     = getattr(dead, "turns_active", 0)
        
        # Add formatted injuries text for display
        snapshot["injuries_text"] = []
        if snapshot.get("injuries"):
            injury_data = snapshot["injuries"]
            # Map injury level to description
            INJURY_DESCRIPTIONS = {
                0: "none", 1: "minor wound", 2: "bleeding wound", 
                3: "serious wound", 4: "deep wound", 5: "grave wound",
                6: "critical wound", 7: "mortal wound", 8: "near-fatal", 9: "fatal"
            }
            INJURY_LOCATIONS = [
                "head", "chest", "abdomen", "primary_arm", 
                "secondary_arm", "primary_leg", "secondary_leg"
            ]
            for loc in INJURY_LOCATIONS:
                level = injury_data.get(loc, 0)
                if level > 0:
                    display_loc = loc.replace("_", " ").title()
                    display_level = INJURY_DESCRIPTIONS.get(level, f"Level {level}")
                    snapshot["injuries_text"].append(f"{display_loc}: {display_level}")
        
        # Add formatted skills text for display (archived: show numeric level)
        snapshot["skills_text"] = []
        if snapshot.get("skills"):
            skills_data = snapshot["skills"]
            for skill_name, level in sorted(skills_data.items()):
                if level > 0:
                    display_name = skill_name.replace("_", " ").title()
                    snapshot["skills_text"].append(f"{display_name}: {level}")
        
        self.archived_warriors.append(snapshot)

        # Place the replacement
        self.warriors[slot_idx] = new_warrior
        if slot_idx in self.pending_replacements:
            del self.pending_replacements[slot_idx]

        print(f"  {dead.name} archived. {new_warrior.name} joins as replacement.")
        return True

    def retire_warrior(self, warrior: Warrior) -> Optional[Warrior]:
        """
        Retire a warrior who has reached 100 fights.
        Returns the replacement, or None if the warrior is not eligible.
        """
        if not warrior.can_retire:
            print(
                f"  {warrior.name} is not eligible for retirement "
                f"({warrior.total_fights} fights; need {100})."
            )
            return None

        idx = self.warrior_index(warrior.name)
        if idx == -1:
            raise ValueError(f"Warrior '{warrior.name}' not found on this team.")

        print(
            f"  {warrior.name} retires after {warrior.total_fights} fights "
            f"({warrior.record_str}). Immortalized in Shady Pines!"
        )

        # Replacement (same as death, per guide)
        replacement = create_warrior_ai()
        replacement.name = f"Rookie_{warrior.name[:4]}_{random.randint(10,99)}"
        self.warriors[idx] = replacement
        return replacement

    # =========================================================================
    # CHALLENGES
    # =========================================================================

    def add_challenge(self, challenger_name: str, target: str):
        """
        Add a challenge for a warrior (up to 3 per warrior per turn).
        target is a manager name, team name, or individual warrior name.
        """
        if challenger_name not in self.challenges:
            self.challenges[challenger_name] = []
        existing = self.challenges[challenger_name]
        if len(existing) >= 3:
            print(f"  {challenger_name} already has 3 challenges queued.")
            return
        existing.append(target)
        print(f"  Challenge added: {challenger_name} → {target}")

    def clear_challenges(self):
        """Clear all pending challenges (called after each turn is processed)."""
        self.challenges.clear()

    # =========================================================================
    # BLOOD CHALLENGE MANAGEMENT
    # =========================================================================

    def get_active_blood_challenges(self) -> list:
        """
        Return list of blood challenges that are still active.
        Active = status is 'active' AND turns_remaining > 0.
        """
        return [bc for bc in self.blood_challenges 
                if bc.get("status") == "active" and bc.get("turns_remaining", 0) > 0]

    def set_blood_challenge_challenger(self, target_name: str, warrior_name: str) -> bool:
        """
        Select a specific warrior to carry out a blood challenge.
        target_name: the killer's name (identifies which blood challenge)
        warrior_name: the warrior from this team selected to carry out the challenge
        Returns True if successful, False otherwise.
        """
        for bc in self.blood_challenges:
            if bc.get("target_name") == target_name and bc.get("status") == "active":
                # Verify the warrior exists on this team
                if not self.warrior_by_name(warrior_name):
                    return False
                bc["challenger_name"] = warrior_name
                return True
        return False

    def mark_blood_challenge_avenged(self, target_name: str, dead_warrior_name: str) -> bool:
        """
        Mark a blood challenge as avenged when the opponent is defeated.
        target_name: the killer's name
        dead_warrior_name: the original victim's name
        Returns True if found and marked, False otherwise.
        """
        for bc in self.blood_challenges:
            if (bc.get("target_name") == target_name and 
                bc.get("dead_warrior_name") == dead_warrior_name and
                bc.get("status") == "active"):
                bc["status"] = "avenged"
                return True
        return False

    def decrement_blood_challenge_turns(self):
        """
        Decrement turns_remaining for all active blood challenges.
        Called at end of each turn to expire challenges that hit 0 turns.
        """
        for bc in self.blood_challenges:
            if bc.get("status") == "active" and bc.get("turns_remaining", 0) > 0:
                bc["turns_remaining"] -= 1

    # =========================================================================
    # MANAGER AVOIDANCE MANAGEMENT
    # =========================================================================

    def add_avoid_manager(self, manager_name: str) -> bool:
        """
        Add a manager to this team's avoid list (max 2).
        Returns True if added, False if list is full or manager already in list.
        """
        if len(self.avoid_managers) >= 2:
            return False
        if manager_name.lower() in [m.lower() for m in self.avoid_managers]:
            return False
        self.avoid_managers.append(manager_name)
        return True

    def remove_avoid_manager(self, manager_name: str) -> bool:
        """Remove a manager from this team's avoid list. Returns True if found and removed."""
        for i, m in enumerate(self.avoid_managers):
            if m.lower() == manager_name.lower():
                self.avoid_managers.pop(i)
                return True
        return False

    def is_avoiding_manager(self, challenger_manager: str) -> bool:
        """Check if this team is avoiding a specific manager (by name)."""
        return any(m.lower() == challenger_manager.lower() for m in self.avoid_managers)

    # =========================================================================
    # DISPLAY
    # =========================================================================

    def roster_summary(self) -> str:
        """One-line roster overview for the main menu."""
        separator = "=" * 62
        thin      = "-" * 62
        lines = [
            separator,
            f"  TEAM:     {self.team_name.upper()}",
            f"  MANAGER:  {self.manager_name.upper()}   (ID: {self.team_id})",
            thin,
            f"  {'#':<3} {'Name':<18} {'Race':<10} {'Record':<10} {'HP':>4}  {'Injuries'}",
            thin,
        ]
        for i, w in enumerate(self.warriors, 1):
            if w is None:
                lines.append(f"  {i:<3} [VACANT SLOT]")
            else:
                inj_count = len(w.injuries.active_injuries())
                inj_str   = f"{inj_count} perm(s)" if inj_count else "None"
                lines.append(
                    f"  {i:<3} {w.name:<18} {w.race.name:<10} "
                    f"{w.record_str:<10} {w.max_hp:>4}  {inj_str}"
                )
        lines.append(separator)
        return "\n".join(lines)

    def full_roster(self) -> str:
        """Full stat blocks for every warrior on the team."""
        blocks = [self.roster_summary()]
        for w in self.warriors:
            if w:
                blocks.append("\n" + w.stat_block())
        return "\n".join(blocks)

    # =========================================================================
    # SERIALIZATION
    # =========================================================================

    def to_dict(self) -> dict:
        return {
            "team_name"           : self.team_name,
            "manager_name"        : self.manager_name,
            "team_id"             : self.team_id,
            "warriors"            : [w.to_dict() if w else None for w in self.warriors],
            "fallen_warriors"     : self.fallen_warriors,
            "blood_challenges"    : self.blood_challenges,
            "avoid_managers"      : self.avoid_managers,
            "challenges"          : self.challenges,
            "archived_warriors"   : self.archived_warriors,
            "pending_replacements": {str(k): v for k, v in self.pending_replacements.items()},
            "turn_history"         : self.turn_history[-20:],  # keep last 20 turns
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Team":
        team = cls(
            team_name    = data["team_name"],
            manager_name = data["manager_name"],
            team_id      = data.get("team_id", 0),
        )
        raw_warriors = data.get("warriors", [])
        team.warriors = [
            Warrior.from_dict(w) if w is not None else None
            for w in raw_warriors
        ]
        team.fallen_warriors     = data.get("fallen_warriors", [])
        
        # Handle blood_challenges — migrate from old tuple format to new dict format
        raw_bcs = data.get("blood_challenges", [])
        team.blood_challenges = []
        for bc in raw_bcs:
            if isinstance(bc, dict):
                # Already in new format
                team.blood_challenges.append(bc)
            else:
                # Old tuple format (challenger_name, target_name) — convert to new format
                team.blood_challenges.append({
                    "dead_warrior_name": "Unknown",
                    "target_name": bc[1] if len(bc) > 1 else "",
                    "challenger_name": bc[0] if len(bc) > 0 else None,
                    "turns_remaining": 3,
                    "status": "active",
                })
        
        team.avoid_managers      = data.get("avoid_managers", [])
        team.challenges          = data.get("challenges", {})
        team.archived_warriors   = data.get("archived_warriors", [])
        team.pending_replacements= {int(k): v for k, v in data.get("pending_replacements", {}).items()}
        team.turn_history        = data.get("turn_history", [])
        return team


# ---------------------------------------------------------------------------
# FACTORY: CREATE A FULL AI TEAM
# ---------------------------------------------------------------------------

def create_ai_team(
    team_name    : Optional[str] = None,
    manager_name : Optional[str] = None,
    team_id      : int           = 0,
) -> Team:
    """
    Generate a full AI-controlled team with 5 random warriors.
    Used for rival managers, the Peasant team, and the Monster team.
    """
    if team_name    is None:
        team_name    = f"Team_{random.randint(100, 999)}"
    if manager_name is None:
        manager_name = f"Manager_{random.randint(10, 99)}"

    team = Team(team_name=team_name, manager_name=manager_name, team_id=team_id)
    team.fill_roster_with_ai()
    return team


# ---------------------------------------------------------------------------
# NAMED PEASANT TEAM
# 10 named NPCs ordered from most difficult (1) to least difficult (10).
# Players should win roughly 70-75% of the time against a matching peasant.
# Stats are fixed per character for consistency; the matchmaker selects
# the appropriate tier(s) based on the player warrior's fight count.
# Names are original — deliberately distinct from any copyrighted sources.
# ---------------------------------------------------------------------------

# Each entry: (name, gender, STR, DEX, CON, INT, PRE, SIZ, armor, weapon)
# Tier 1 = hardest, Tier 10 = easiest.
# Peasant stats bumped slightly from v1 — they should present a real threat
# but still be clearly beatable. Target: player wins ~65-70% (was 70-75%).
# Each stat raised by 2-3 points across the board.
PEASANT_ROSTER = [
    # Tier 1 — Crom the Bell-Keeper: big and mean, likes to bash
    ("Crom the Bell-Keeper",  "Male",   19, 15, 17, 11, 10, 17, "Brigandine",  "Morningstar"),
    # Tier 2 — Bawdy Nell: fast and sneaky, dagger in the ribs
    ("Bawdy Nell",            "Female", 14, 18, 14, 14, 12, 11, "Cuir Boulli", "Short Sword"),
    # Tier 3 — Vernon the Versifier: surprisingly capable with a spear
    ("Vernon the Versifier",  "Male",   15, 16, 15, 13, 11, 13, "Leather",     "Boar Spear"),
    # Tier 4 — Hilda the Fishmonger: tough as old boots
    ("Hilda the Fishmonger",  "Female", 16, 13, 17, 11, 10, 14, "Brigandine",  "War Flail"),
    # Tier 5 — Grub the Coinless: desperate fighter, nothing to lose
    ("Grub the Coinless",     "Male",   14, 14, 14, 11,  9, 13, "Leather",     "Battle Axe"),
    # Tier 6 — Mort the Ditch-Digger: slow but surprisingly durable
    ("Mort the Ditch-Digger", "Male",   15, 12, 15, 10,  9, 15, "Cloth",       "Morningstar"),
    # Tier 7 — Wandering Wanda: slippery and hard to pin down
    ("Wandering Wanda",       "Female", 12, 16, 13, 13, 10, 11, "Leather",     "Flail"),
    # Tier 8 — Oswald the Soothsayer: more prophet than fighter
    ("Oswald the Soothsayer", "Male",   12, 13, 13, 13, 12, 12, "Cloth",       "Short Sword"),
    # Tier 9 — Crackers McGee: unpredictable but fragile
    ("Crackers McGee",        "Male",   11, 14, 12, 11,  9, 10, "Cloth",       "Hatchet"),
    # Tier 10 — Wilbur the Weed-Puller: not totally helpless now
    ("Wilbur the Weed-Puller","Male",   10, 11, 11, 10,  8, 10, "Cloth",       "Short Sword"),
]

# Variance range applied to peasant stats so each fight feels slightly different.
_PEASANT_VARIANCE = 2   # ±2 on each stat


def _make_peasant(tier_index: int) -> Warrior:
    """
    Build a single Warrior from PEASANT_ROSTER at the given index (0-based).
    Applies small random variance so repeated fights feel different.
    """
    from warrior import STAT_MIN, STAT_MAX
    name, gender, STR, DEX, CON, INT, PRE, SIZ, armor, weapon = PEASANT_ROSTER[tier_index]
    v = _PEASANT_VARIANCE

    def jitter(base: int) -> int:
        return max(STAT_MIN, min(STAT_MAX, base + random.randint(-v, v)))

    w = Warrior(
        name         = name,
        race_name    = "Peasant",
        gender       = gender,
        strength     = jitter(STR),
        dexterity    = jitter(DEX),
        constitution = jitter(CON),
        intelligence = jitter(INT),
        presence     = jitter(PRE),
        size         = jitter(SIZ),
    )
    w.armor          = armor
    w.primary_weapon = weapon

    # Add a simple strategy so they actually fight back
    from warrior import Strategy
    w.strategies = [Strategy(trigger="Always", style="Strike", activity=5,
                              aim_point="Chest", defense_point="Chest")]
    return w


def create_peasant_team(target_fight_count: int = 0) -> Team:
    """
    Create a Peasant team of 5, selecting tier-appropriate NPCs based on
    the player warrior's fight count.

    Fight count mapping:
      0-10  fights → use tiers 6-10 (easiest tier)
      11-30 fights → use tiers 4-8
      31-60 fights → use tiers 2-6
      61+   fights → use tiers 1-5 (hardest tier)

    Players should win roughly 70-75% of the time against appropriate tiers.
    """
    if   target_fight_count <= 10: tier_range = (5, 9)   # indices 5-9 = tiers 6-10
    elif target_fight_count <= 30: tier_range = (3, 7)   # indices 3-7 = tiers 4-8
    elif target_fight_count <= 60: tier_range = (1, 5)   # indices 1-5 = tiers 2-6
    else:                           tier_range = (0, 4)  # indices 0-4 = tiers 1-5

    team = Team(
        team_name    = "The Peasants",
        manager_name = "The Arena",
        team_id      = 0,
    )

    # Pick TEAM_SIZE peasants from the eligible tier range (no repeats if possible)
    available = list(range(tier_range[0], tier_range[1] + 1))
    if len(available) < TEAM_SIZE:
        available = available * (TEAM_SIZE // len(available) + 1)
    indices = random.sample(available, TEAM_SIZE)

    for idx in indices:
        team.add_warrior(_make_peasant(idx))

    return team


def get_peasant_by_name(name: str) -> Optional[Warrior]:
    """Return a fresh peasant warrior by name (case-insensitive)."""
    for i, row in enumerate(PEASANT_ROSTER):
        if row[0].lower() == name.lower():
            return _make_peasant(i)
    return None


# ---------------------------------------------------------------------------
# MONSTER DEFINITIONS
# Each monster has its own personality, gear, and skill set.
# Player wins ~0.5% of the time. If a player warrior kills a monster,
# that warrior joins the Monster team (handled in matchmaking).
# ---------------------------------------------------------------------------

# (name, gender, STR, DEX, CON, INT, PRE, SIZ, armor, helm, primary, secondary,
#  flavour_style, kill_skill, kill_skill_level)
MONSTER_ROSTER = [
    # The Iron Colossus — unstoppable armored juggernaut
    ("The Iron Colossus",  "Male",   25, 18, 25, 10, 20, 25,
     "Full Plate", "Full Helm", "Maul",      "Tower Shield", "Bash",    "parry",      8),
    # Dread Reaver — shadow-fast assassin, impossible to hit
    ("Dread Reaver",       "Male",   20, 25, 20, 18, 22, 17,
     "Chain",     "Camail",    "Scythe",     "Open Hand",    "Lunge",   "dodge",      8),
    # The Pit Tyrant — arena veteran with every dirty trick known
    ("The Pit Tyrant",     "Male",   22, 22, 23, 20, 22, 20,
     "Half-Plate","Full Helm", "War Flail",  "Open Hand",    "Total Kill","initiative",9),
    # Stonehide Brute — near-unkillable regenerating monstrosity
    ("Stonehide Brute",    "Male",   24, 17, 25, 10, 18, 25,
     "Full Plate","Full Helm", "Great Pick", "Open Hand",    "Bash",    "constitution",0),
    # The Doomwyrm — ancient beast, all limbs are weapons
    ("The Doomwyrm",       "Male",   23, 23, 24, 14, 21, 24,
     "Full Plate","Full Helm", "Halberd",    "Open Hand",    "Wall of Steel","lunge",  7),
]


def _make_monster(roster_index: int) -> Warrior:
    """Build a fully skilled monster warrior from the roster."""
    from warrior import Strategy, SKILL_LEVEL_NAMES
    row = MONSTER_ROSTER[roster_index]
    name, gender, STR, DEX, CON, INT, PRE, SIZ = row[:8]
    armor, helm, primary, secondary, style, kill_skill, kill_level = row[8:]

    w = Warrior(
        name         = name,
        race_name    = "Monster",
        gender       = gender,
        strength     = STR,
        dexterity    = DEX,
        constitution = CON,
        intelligence = INT,
        presence     = PRE,
        size         = SIZ,
    )
    w.armor            = armor
    w.helm             = helm
    w.primary_weapon   = primary
    w.secondary_weapon = secondary

    # All monsters have expert-level skills in key areas
    for skill in ["parry","dodge","initiative","lunge","feint","brawl","sweep","charge"]:
        w.skills[skill] = 7   # Expert

    # Their signature weapon at master level
    wpn_key = primary.lower().replace(" ","_").replace("&","and")
    w.skills[wpn_key] = 9   # Master

    # Extra signature skill
    if kill_skill and kill_level > 0:
        w.skills[kill_skill] = kill_level

    # Aggressive strategy — they always press the attack
    w.strategies = [
        Strategy(trigger="You have taken heavy damage", style="Total Kill",
                 activity=9, aim_point="Head",  defense_point="None"),
        Strategy(trigger="Your foe is on the ground",  style="Total Kill",
                 activity=9, aim_point="Head",  defense_point="None"),
        Strategy(trigger="Always",                     style=style,
                 activity=8, aim_point="Chest", defense_point="Chest"),
    ]
    return w


def create_monster_team() -> Team:
    """
    Create the full Monster team of 5.
    Fights against monsters are always to the death — no mercy.
    Player wins approximately 0.5% of the time.
    If a player warrior defeats a monster, they join The Monsters.

    If saves/monster_team.json exists (i.e. a player warrior has previously
    been absorbed), load the persisted roster. Otherwise build from the
    hardcoded MONSTER_ROSTER. Delete the file to reset to the default roster.
    """
    # Late import to avoid save.py <-> team.py circular dependency at module load
    from save import load_monster_team
    persisted = load_monster_team()
    if persisted is not None:
        return persisted

    team = Team(
        team_name    = "The Monsters",
        manager_name = "The Arena",
        team_id      = -1,
    )
    for i in range(len(MONSTER_ROSTER)):
        team.add_warrior(_make_monster(i))
    return team


def get_monster_by_name(name: str) -> Optional[Warrior]:
    """Return a fresh monster warrior by name (case-insensitive)."""
    for i, row in enumerate(MONSTER_ROSTER):
        if row[0].lower() == name.lower():
            return _make_monster(i)
    return None
