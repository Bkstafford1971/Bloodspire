# =============================================================================
# matchmaking.py - THE AGONY AMPHITHEATRE Turn Matchmaking Engine
# =============================================================================
# Builds the list of fights for a turn:
#   1. Resolve blood challenges (highest priority).
#   2. Resolve player-issued challenges (Presence-weighted).
#   3. Match unmatched player warriors against opponent teams.
#   4. Fill any remaining unmatched slots with scaled peasants.
#
# Returns a list of ScheduledFight objects ready for CombatEngine.
# =============================================================================

import random
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict

from warrior   import Warrior
from team      import Team, create_peasant_team, create_monster_team
from combat    import run_fight, FightResult
from save      import save_team, save_fight_log, load_all_teams


# ---------------------------------------------------------------------------
# SCHEDULED FIGHT DATACLASS
# ---------------------------------------------------------------------------

@dataclass
class ScheduledFight:
    """One fight bout scheduled for the current turn."""
    player_warrior  : Warrior
    opponent        : Warrior
    player_team     : Team
    opponent_team   : Team
    opponent_manager: str       # Display name for the narrative header
    fight_type      : str       # "challenge", "standard", "peasant", "blood_challenge"
    result          : Optional[FightResult] = None
    fight_id        : Optional[int]         = None
    challenger_name : Optional[str]         = None  # warrior name of who initiated the challenge
    _metadata       : dict                  = field(default_factory=dict)


# ---------------------------------------------------------------------------
def _is_same_manager(team1, team2) -> bool:
    """Check if two teams belong to the same manager to avoid internal fights."""
    return (team1.manager_name == team2.manager_name and team1.manager_name != "The Arena")


def build_global_fight_card(
    player_teams: List[Team],
    opponent_teams: List[Team],
    champion_state: dict = None,
) -> List[ScheduledFight]:
    """
    Build a fight card by matching all warriors from a single global pool.
    Ensures every warrior fights exactly once per turn.
    """
    if champion_state is None:
        champion_state = {}

    card = []
    master_pool = []

    # STEP 1: Combine all teams into a single unique list
    all_teams_map = {t.team_id: t for t in player_teams + opponent_teams}
    unique_teams = list(all_teams_map.values())

    for t in unique_teams:
        for w in t.active_warriors:
            if w:
                master_pool.append({'warrior': w, 'team': t, 'matched': False})

    def _get_unmatched() -> List[dict]:
        return [e for e in master_pool if not e['matched']]

    def _add_fight(e1: dict, e2: dict, ftype: str, challenger: str = None):
        fight = ScheduledFight(
            player_warrior=e1['warrior'], opponent=e2['warrior'],
            player_team=e1['team'], opponent_team=e2['team'],
            opponent_manager=e2['team'].manager_name,
            fight_type=ftype, challenger_name=challenger,
        )
        card.append(fight)
        e1['matched'] = True
        e2['matched'] = True
        # DEBUG: Log fight addition
        if ftype in ["blood_challenge", "challenge", "standard"]:
            if e1['team'].manager_name in ["D-man", "Sleazee P Martinee", "B4youwereborn"]:
                print(f"    [ADD_FIGHT] {ftype}: {e1['warrior'].name} vs {e2['warrior'].name} (card now has {len(card)} fights)")

    # STEP 2: MONSTER CHALLENGES
    monster_team = None
    for entry in _get_unmatched():
        if getattr(entry['warrior'], 'want_monster_fight', False):
            if monster_team is None: monster_team = create_monster_team()
            monster = random.choice(monster_team.active_warriors)
            m_entry = {'warrior': monster, 'team': monster_team, 'matched': False}
            _add_fight(entry, m_entry, "monster")
            entry['warrior'].want_monster_fight = False

    # STEP 3: BLOOD CHALLENGES
    # CRITICAL: Only process blood challenges where the manager has explicitly selected a challenger warrior
    # Blood challenges are user-initiated vengeance, not automatic
    unmatched = _get_unmatched()
    random.shuffle(unmatched)

    # Build a map of warriors for quick lookup
    warrior_to_entry = {}
    for entry in unmatched:
        warrior_to_entry[entry['warrior'].name.lower()] = entry

    for entry in list(unmatched):
        if entry['matched']: continue
        for bc in entry['team'].blood_challenges:
            # Must have: active status, turns remaining, AND manager-selected challenger
            if not (bc.get("status") == "active" and bc.get("turns_remaining", 0) > 0
                    and bc.get("challenger_name")):
                continue  # Skip if manager hasn't selected a challenger

            # Get the selected challenger warrior
            challenger_name = bc.get("challenger_name", "").lower()
            challenger = warrior_to_entry.get(challenger_name)

            # Verify challenger is from this team and unmatched
            if not challenger or challenger['team'].team_id != entry['team'].team_id or challenger['matched']:
                continue

            # Now find the target (killer) to avenge
            target_name = bc.get("target_name", "").lower()
            target = warrior_to_entry.get(target_name)

            if target and not target['matched'] and not _is_same_manager(entry['team'], target['team']):
                if _challenge_succeeds(challenger['warrior'].presence, target['warrior'].presence, is_blood_challenge=True):
                    _add_fight(challenger, target, "blood_challenge", challenger['warrior'].name)
                    break

    # STEP 4: CHAMPION CHALLENGES
    current_champion = champion_state.get("name", "")
    if current_champion:
        unmatched = _get_unmatched()
        champ_e = next((e for e in master_pool if e['warrior'].name.lower() == current_champion.lower()), None)
        if champ_e and not champ_e['matched']:
            challengers = []
            for entry in unmatched:
                if entry['matched']: continue
                targets = entry['team'].challenges.get(entry['warrior'].slot_index, [])
                if any(t.lower() == current_champion.lower() or t.lower() == champ_e['team'].team_name.lower() for t in targets):
                    challengers.append(entry)
            if challengers:
                challengers.sort(key=lambda e: (-e['warrior'].presence, -getattr(e['warrior'], 'recognition', 0)))
                if _challenge_succeeds(challengers[0]['warrior'].presence, champ_e['warrior'].presence, is_champion_challenge=True):
                    _add_fight(challengers[0], champ_e, "challenge", challengers[0]['warrior'].name)

    # STEP 5: REGULAR CHALLENGES
    unmatched = _get_unmatched()
    random.shuffle(unmatched)
    for entry in list(unmatched):
        if entry['matched']: continue
        targets = entry['team'].challenges.get(entry['warrior'].slot_index, [])
        for target_name in targets:
            target = next((e for e in unmatched if not e['matched']
                           and (target_name.lower() in e['warrior'].name.lower() or
                                target_name.lower() in e['team'].team_name.lower() or
                                target_name.lower() in e['team'].manager_name.lower())
                           and not _is_same_manager(entry['team'], e['team'])), None)
            if target and not _attempt_avoid_challenge(target['warrior'], target['team'], entry['warrior'].name, entry['team'].manager_name):
                if _challenge_in_bracket(entry['warrior'].total_fights, target['warrior'].total_fights):
                    if _challenge_succeeds(entry['warrior'].presence, target['warrior'].presence):
                        _add_fight(entry, target, "challenge", entry['warrior'].name)
                        break

    # STEP 6: RANDOM P-vs-P MATCHMAKING
    unmatched = _get_unmatched()
    print(f"  [DEBUG_PVP] Starting P-vs-P with {len(unmatched)} unmatched warriors")
    # Count unmatched by manager
    unmatched_by_mgr = {}
    for e in unmatched:
        mgr = e['team'].manager_name
        unmatched_by_mgr[mgr] = unmatched_by_mgr.get(mgr, 0) + 1
    print(f"  [DEBUG_PVP] Unmatched warriors by manager:")
    for mgr in sorted(unmatched_by_mgr.keys()):
        print(f"    {mgr}: {unmatched_by_mgr[mgr]} warriors")
    random.shuffle(unmatched)
    fights_added_in_pvp = 0
    warriors_with_no_match = []
    for idx, entry in enumerate(list(unmatched)):
        if entry['matched']:
            if idx == 0 or unmatched[idx-1]['matched'] == False:
                pass  # Expected, skip matched warriors
            continue
        eligible = [e for e in unmatched if not e['matched']
                    and not _is_same_manager(entry['team'], e['team'])
                    and _in_bracket(entry['warrior'].total_fights, e['warrior'].total_fights)]
        if eligible:
            self_rating = _warrior_rating(entry['warrior'])
            eligible.sort(key=lambda e: abs(_warrior_rating(e['warrior']) - self_rating))
            _add_fight(entry, eligible[0], "standard")
            fights_added_in_pvp += 1
            # Both warriors are now marked as matched by _add_fight()
        else:
            # Warrior found no eligible opponent - should NOT be marked as matched!
            warriors_with_no_match.append(entry)
            if entry['warrior'].name == "KYLE":
                print(f"  [DEBUG_PVP] KYLE found NO eligible opponents (matched={entry['matched']})")
    print(f"  [DEBUG_PVP] P-vs-P added {fights_added_in_pvp} fights")
    if warriors_with_no_match:
        print(f"  [DEBUG_PVP] WARNING: {len(warriors_with_no_match)} warriors had no eligible opponents!")
        for entry in warriors_with_no_match[:5]:
            matched_state = entry['matched']
            print(f"    - {entry['warrior'].name} ({entry['team'].manager_name}) - matched={matched_state}")

    # DEBUG: Check immediately after P-vs-P loop
    print(f"  [DEBUG_PVP] Immediately after loop: {len([e for e in master_pool if e['matched']])} matched warriors")

    # Check if these warriors are somehow getting marked as matched INSIDE the loop
    for entry in warriors_with_no_match:
        all_matched = [e for e in master_pool if e['warrior'].name == entry['warrior'].name]
        if all_matched:
            print(f"  [DEBUG_PVP] Check on {entry['warrior'].name}: matched={all_matched[0]['matched']}")

    print(f"  [DEBUG_PVP] After P-vs-P matchmaking: {len(card)} total fights on card")

    # STEP 7: PEASANTS FOR REMAINING
    unmatched_remaining = _get_unmatched()
    print(f"  [DEBUG_PEASANTS] Found {len(unmatched_remaining)} unmatched warriors for peasants step")
    if unmatched_remaining:
        print(f"  [DEBUG_PEASANTS] Assigning peasant fights:")
        for entry in unmatched_remaining[:10]:
            print(f"    - {entry['warrior'].name} ({entry['team'].team_name}, manager: {entry['team'].manager_name})")
        for entry in unmatched_remaining:
            p_team = create_peasant_team(target_fight_count=entry['warrior'].total_fights)
            p_warrior = random.choice(p_team.active_warriors)
            card.append(ScheduledFight(
                player_warrior=entry['warrior'], opponent=p_warrior,
                player_team=entry['team'], opponent_team=p_team,
                opponent_manager="The Arena", fight_type="peasant",
            ))
            entry['matched'] = True
        print(f"  [DEBUG_PEASANTS] Added {len(unmatched_remaining)} peasant fights, card now has {len(card)} total")
    else:
        print(f"  [DEBUG] PROBLEM: All warriors matched but card only has {len(card)} fights!")

    return card
# WARRIOR STRENGTH RATING (for matchmaking)
# ---------------------------------------------------------------------------

def _warrior_rating(warrior: Warrior) -> float:
    """
    Numeric rating for matchmaking purposes.
    APPROX: weighted sum of stats + fight experience + skill total.
    """
    stat_score = (
        warrior.strength     * 1.5 +
        warrior.dexterity    * 1.5 +
        warrior.constitution * 1.2 +
        warrior.intelligence * 0.8 +
        warrior.presence     * 0.5 +
        warrior.size         * 1.0
    )
    experience_bonus = warrior.total_fights * 0.3
    skill_bonus      = sum(warrior.skills.values()) * 0.2
    return stat_score + experience_bonus + skill_bonus


# ---------------------------------------------------------------------------
# EXPERIENCE BRACKET HELPERS
# ---------------------------------------------------------------------------

ROOKIE_THRESHOLD = 5      # used only by challenge bully-prevention
BRACKET_UPPER    = 1.30   # can face someone with up to 30% MORE fights
BRACKET_LOWER    = 0.90   # can face someone with as few as 90% of own fights (10% less)
CHALLENGE_FLOOR  = 0.90   # cannot challenge someone with <90% of own fights

def _in_bracket(player_fights: int, opponent_fights: int) -> bool:
    """
    Return True if the opponent's fight count falls within the player's
    experience bracket.  Uses the same formula as the challenge range UI:
      lower = floor(fights × 0.90)
      upper = floor(fights × 1.30)
    A 0-fight warrior only matches other 0-fight warriors (0×1.30 = 0).
    A 1-fight warrior matches 0–1 fights, 5-fight matches 4–6, etc.
    No special rookie bucket - graduated window applies from fight 0 onward.
    """
    lower = int(player_fights * BRACKET_LOWER)
    upper = int(player_fights * BRACKET_UPPER)
    return lower <= opponent_fights <= upper


def _challenge_in_bracket(challenger_fights: int, target_fights: int) -> bool:
    """
    Challenges ignore the upper bracket limit (warriors can punch up freely),
    but bully-prevention applies: cannot challenge someone with fewer than
    90% of the challenger's fights.
    Blood challenges skip this check entirely.
    """
    if challenger_fights <= ROOKIE_THRESHOLD:
        return True   # rookies can challenge anyone
    floor = int(challenger_fights * CHALLENGE_FLOOR)
    return target_fights >= floor


def _team_avg_rating(team: Team) -> float:
    active = team.active_warriors
    if not active:
        return 0.0
    return sum(_warrior_rating(w) for w in active) / len(active)


# ---------------------------------------------------------------------------
# PRESENCE-BASED CHALLENGE RESOLUTION
# ---------------------------------------------------------------------------

def _challenge_succeeds(
    challenger_presence: int,
    target_presence    : int,
    is_blood_challenge : bool = False,
    is_champion_challenge: bool = False,
) -> bool:
    """
    Determine if a challenge goes through.
    Guide formula: base_chance + (PRE - opp_PRE) percent.
    Blood challenges have +20% bonus chance.
    Champion challenges have +25% bonus chance (almost guaranteed to succeed).

    APPROX base chance: 75% (increased for easier challenge acceptance).
    """
    # Champion challenges have very high success rate
    if is_champion_challenge:
        base   = 100   # Nearly guaranteed, but level adjustment still applies
        adj    = challenger_presence - target_presence
        chance = max(5, min(95, base + adj))
        return random.randint(1, 100) <= chance
    
    base   = 85 if is_blood_challenge else 75
    adj    = challenger_presence - target_presence
    chance = max(5, min(95, base + adj))
    return random.randint(1, 100) <= chance


# ---------------------------------------------------------------------------
# AVOIDANCE SYSTEM
# ---------------------------------------------------------------------------

def _attempt_avoid_challenge(
    target_warrior: Warrior,
    target_team: Team,
    challenger_name: str,
    challenger_manager: str,
) -> bool:
    """
    Check if target warrior or team can avoid the challenge.
    Returns True if challenge is avoided (blocked), False if it proceeds.
    
    Priority:
      1. Warrior-specific avoidance: 60-70% success rate
      2. Manager-level avoidance: 25-30% success rate
    """
    # Check warrior-specific avoidance (60-70% success)
    if target_warrior.is_avoiding_warrior(challenger_name):
        avoid_chance = random.randint(60, 70)
        roll = random.randint(1, 100)
        if roll <= avoid_chance:
            return True  # Challenge avoided
    
    # Check manager-level avoidance (25-30% success)
    if target_team.is_avoiding_manager(challenger_manager):
        avoid_chance = random.randint(25, 30)
        roll = random.randint(1, 100)
        if roll <= avoid_chance:
            return True  # Challenge avoided
    
    return False  # Challenge proceeds


# ---------------------------------------------------------------------------
# FIND BEST OPPONENT FOR A PLAYER WARRIOR
# ---------------------------------------------------------------------------

def _find_opponent(
    player_warrior : Warrior,
    opponent_teams : List[Team],
    already_matched: set,                      # team_id values already used this card
    global_used    : set = None,               # (team_id, name) used across ALL cards this turn
    matched_opponent_warriors: set = None,     # (team_id, name) matched in this card
) -> Optional[Tuple[Warrior, Team]]:
    """
    Find the best-matched opponent warrior from all available teams.

    Preference:
      1. Team whose average rating is closest to the player warrior.
      2. Pick the individual warrior on that team with the closest rating.
      3. Skip teams already matched this turn.
      4. Skip individual warriors already scheduled globally this turn.
      5. Skip individual warriors already matched in this card.

    Bracket enforcement (same formula as challenge range UI):
      - All warriors: lower = floor(fights * 0.90), upper = floor(fights * 1.30).
      - A 0-fight warrior only matches other 0-fight warriors; a 1-fight warrior
        matches 0-1 fights; a 5-fight warrior matches 4-6 fights, etc.
      - No bracket relaxation: if no in-bracket opponent exists, returns None and
        the warrior falls through to a correctly-scaled peasant fight (Step 4).
    """
    player_rating = _warrior_rating(player_warrior)
    player_fights = player_warrior.total_fights
    _used = global_used or set()
    _matched_opponents = matched_opponent_warriors or set()

    bracket_lower = int(player_fights * BRACKET_LOWER)
    bracket_upper = int(player_fights * BRACKET_UPPER)

    def _available_warriors(t):
        """Active warriors on this team not yet used globally and not already matched in this card."""
        # A warrior is available for standard matching ONLY if they aren't already 
        # booked AND haven't expressed intent to be an attacker (monsters/retire) 
        # or issued their own challenges. We use tuples to prevent name collisions.
        return [w for w in t.active_warriors 
                if (t.team_id, w.slot_index) not in _used 
                and (t.team_id, w.slot_index) not in _matched_opponents
                and not getattr(w, 'want_monster_fight', False)
                and not getattr(w, 'want_retire', False)
                and not (hasattr(t, 'challenges') and w.slot_index in t.challenges and t.challenges[w.slot_index])]

    candidates = [
        t for t in opponent_teams
        if t.team_id not in already_matched
        and any(_in_bracket(player_fights, w.total_fights)
                for w in _available_warriors(t))
    ]

    if not candidates:
        return None

    # Sort by closeness of team average rating (using only available warriors)
    candidates.sort(key=lambda t: abs(
        sum(_warrior_rating(w) for w in _available_warriors(t)) /
        max(1, len(_available_warriors(t)))
        - player_rating
    ))

    for best_team in candidates:
        avail = _available_warriors(best_team)
        if not avail:
            continue
        in_bracket = [w for w in avail
                      if _in_bracket(player_warrior.total_fights, w.total_fights)]
        pool = in_bracket or avail
        pool.sort(key=lambda w: abs(_warrior_rating(w) - player_rating))
        selected = pool[0]
        return selected, best_team

    return None


# ---------------------------------------------------------------------------
# MAIN MATCHMAKING FUNCTION
# ---------------------------------------------------------------------------

def _absorb_into_monsters(
    warrior      : Warrior,
    player_team  : Team,
    slain_monster: Warrior,
    monster_team : Team,
):
    """
    A player warrior who kills a monster is absorbed into The Monsters,
    replacing the slain monster on the persisted monster roster.

    Player-side effects:
      - Warrior's record (already updated by run_fight) is frozen at its current
        value - kill_warrior marks them is_dead, preventing further fights.
      - Original warrior stats/skills/record are preserved on the player team
        for archiving (we build a SEPARATE monster clone; the original is not
        mutated before kill_warrior is called).
      - Replacement slot opens via the normal kill_warrior flow.

    Monster-side effects:
      - A monster-ified clone of the warrior (same name, boosted stats, expert
        monster skills, aggressive strategies, race="Monster", 0-0-0 record)
        is placed into the slain monster's slot on the monster team.
      - The monster team is saved to saves/monster_team.json so the new roster
        persists across turns.

    Spec: roughly 0.5% chance of this happening per monster fight.
    """
    from warrior import STAT_MAX, Strategy, Warrior
    from save    import save_monster_team
    import random as _r

    # ---- Build the monster-ified clone (does NOT mutate the original) ----
    src = warrior.to_dict()
    src["race"] = "Monster"          # Race change - freezes record in run_fight
    src["wins"] = 0                  # Monsters always display 0-0-0
    src["losses"] = 0
    src["kills"] = 0
    src["total_fights"] = 0
    src["is_dead"] = False
    src["killed_by"] = ""
    src["fight_history"] = []
    src["want_monster_fight"] = False
    src["want_retire"] = False

    # Boost every stat toward monster territory
    boosts = {
        "strength"    : _r.randint(3, 6),
        "dexterity"   : _r.randint(2, 4),
        "constitution": _r.randint(3, 6),
        "intelligence": _r.randint(1, 3),
        "presence"    : _r.randint(2, 4),
        "size"        : _r.randint(2, 5),
    }
    for attr, boost in boosts.items():
        src[attr] = min(STAT_MAX, src.get(attr, 0) + boost)

    # Give expert monster skills on top of whatever they already knew
    skills = dict(src.get("skills", {}))
    skills["parry"]      = max(skills.get("parry",      0), 7)
    skills["dodge"]      = max(skills.get("dodge",      0), 6)
    skills["initiative"] = max(skills.get("initiative", 0), 7)
    src["skills"] = skills

    # Aggressive monster strategies (same template as hardcoded monsters)
    src["strategies"] = [
        Strategy(trigger="You have taken heavy damage", style="Total Kill",
                 activity=9, aim_point="Head",  defense_point="None").to_dict(),
        Strategy(trigger="Your foe is on the ground",  style="Total Kill",
                 activity=9, aim_point="Head",  defense_point="None").to_dict(),
        Strategy(trigger="Always",                     style="Strike",
                 activity=8, aim_point="Chest", defense_point="Chest").to_dict(),
    ]

    monster_clone = Warrior.from_dict(src)
    monster_clone.recalculate_derived()

    # ---- Replace the slain monster's slot on the monster team ----
    slot_idx = monster_team.warrior_index(slain_monster.name)
    if slot_idx == -1:
        # Defensive: if we somehow can't find the slain monster, append.
        monster_team.warriors.append(monster_clone)
        slot_idx = len(monster_team.warriors) - 1
    else:
        monster_team.warriors[slot_idx] = monster_clone

    save_monster_team(monster_team)
    print(f"  >>> {monster_clone.name} takes the place of {slain_monster.name} "
          f"on the Monster roster (slot {slot_idx}).")

    # ---- Open replacement slot on the player team ----
    # The original warrior is untouched up to this point - archive will
    # preserve their real stats and 34-2-16 record.
    player_team.kill_warrior(
        warrior,
        killed_by     = "The Monsters",
        killer_fights = 999,
        fight_type    = "monster",   # ascension - no blood challenge against monsters
    )


# ---------------------------------------------------------------------------
# FIGHT FREQUENCY VALIDATION
# ---------------------------------------------------------------------------

def validate_warrior_fight_frequency(card: List[ScheduledFight]) -> List[dict]:
    """
    Validate that warriors on user and AI teams fight at most once per turn.

    Returns a list of violation dicts:
        {warrior: str, team: str, fight_count: int, fights: List[ScheduledFight]}

    Monsters and Peasants are allowed multiple fights (exception to the rule).
    """
    violations = []
    warrior_fight_map = {}  # {warrior_name: [(team_id, ScheduledFight), ...]}

    def is_npc_team(team_id):
        return team_id < 0

    for scheduled_fight in card:
        if not scheduled_fight.result:
            continue  # Skip unresolved fights

        player_warrior = scheduled_fight.player_warrior
        opponent = scheduled_fight.opponent
        # Use team_id as unique identifier, not team_name (handles duplicate team names)
        player_team_id = scheduled_fight.player_team.team_id if hasattr(scheduled_fight.player_team, "team_id") else 0
        opponent_team_id = scheduled_fight.opponent_team.team_id if hasattr(scheduled_fight.opponent_team, "team_id") else 0

        # Record player warrior if on a user/AI team (not NPC)
        if not is_npc_team(player_team_id):
            key = (player_team_id, player_warrior.slot_index)
            if key not in warrior_fight_map:
                warrior_fight_map[key] = []
            warrior_fight_map[key].append((player_team_id, scheduled_fight, player_warrior.name))

        # Record opponent if on a user/AI team (not NPC)
        if not is_npc_team(opponent_team_id):
            opponent_slot = opponent.slot_index if hasattr(opponent, "slot_index") else None
            if opponent_slot is not None:
                key = (opponent_team_id, opponent_slot)
                if key not in warrior_fight_map:
                    warrior_fight_map[key] = []
                warrior_fight_map[key].append((opponent_team_id, scheduled_fight, opponent.name))

    # Check for violations
    for key, fight_list in warrior_fight_map.items():
        if len(fight_list) > 1:
            # Multiple fights for a user/AI warrior - this is a violation
            team_id, _ = key
            warrior_name = fight_list[0][2]
            violations.append({
                "warrior": warrior_name,
                "team": f"team_id={team_id}", # team_id is now part of the key
                "fight_count": len(fight_list),
                "fights": [f for _, f, _ in fight_list],
            })

    return violations


def validate_team_fight_count(card: List[ScheduledFight], max_fights: int = 5) -> List[dict]:
    """
    Validate that user and AI teams have at most max_fights (default 5) per turn.

    Returns a list of violation dicts:
        {team: str, fight_count: int, max_allowed: int}
    """
    violations = []
    team_fight_count = {}  # Use team_id as key, not team_name (handles duplicate team names)

    def is_npc_team(team_id):
        return team_id < 0

    for scheduled_fight in card:
        if not scheduled_fight.result:
            continue  # Skip unresolved fights

        # Use team_id as unique identifier, not team_name (handles duplicate team names)
        player_team_id = scheduled_fight.player_team.team_id if hasattr(scheduled_fight.player_team, "team_id") else 0
        opponent_team_id = scheduled_fight.opponent_team.team_id if hasattr(scheduled_fight.opponent_team, "team_id") else 0

        # Count fights for player team
        if not is_npc_team(player_team_id):
            team_fight_count[player_team_id] = team_fight_count.get(player_team_id, 0) + 1

        # Count fights for opponent team
        if not is_npc_team(opponent_team_id):
            team_fight_count[opponent_team_id] = team_fight_count.get(opponent_team_id, 0) + 1

    # Check for violations
    for team_id, count in team_fight_count.items():
        if count > max_fights:
            violations.append({
                "team": f"team_id={team_id}",
                "fight_count": count,
                "max_allowed": max_fights,
            })

    return violations


def build_fight_card(
    player_team    : Team,
    opponent_teams : List[Team],
    champion_state : dict = None,
    global_used    : set = None,                          # shared set of warrior names used across ALL teams this turn
    global_matched_opponent_warriors: set = None,         # shared set of opponent warriors matched across ALL teams
) -> List[ScheduledFight]:
    """
    Build the complete fight card for the current turn.
    Returns a list of ScheduledFight objects.

    Steps:
      1. Monster challenges
      2. Blood challenges
      3. Champion / regular challenges
      4. Match remaining warriors against opponent teams
      5. Fill unmatched slots with peasants

    global_used is a mutable set shared across all team card builds in a turn.
    Warriors from either side of a fight are added to it as (team_id, name) tuples 
    so no warrior fights more than once per turn regardless of how many player 
    teams are processing.

    global_matched_opponent_warriors is a mutable set shared across all team card builds.
    Opponent warriors matched in any team's card are added to it as (team_id, name)
    tuples to prevent the same opponent warrior from being matched multiple times
    across different teams' cards.
    """
    if champion_state is None:
        champion_state = {}
    if global_used is None:
        global_used = set()
    if global_matched_opponent_warriors is None:
        global_matched_opponent_warriors = set()

    current_champion = champion_state.get("name", "")
    card            : List[ScheduledFight]  = []
    matched_players : set = set()         # player warrior names already scheduled this card
    matched_teams   : set = set()         # opponent team IDs already used this card

    def _schedule(fight: ScheduledFight):
        """Add a fight to the card and mark the player warrior as used globally."""
        card.append(fight)
        global_used.add((fight.player_team.team_id, fight.player_warrior.slot_index))
        global_matched_opponent_warriors.add((fight.opponent_team.team_id, fight.opponent.slot_index))  # Track opponent globally
        # Opponents are NOT added to global_used here.
        # Adding them caused opponent warriors to be excluded from active_players
        # when their own team's card was built in the same pre-pass, resulting in
        # entire teams getting 0 fights. Player-vs-player conflicts are resolved
        # by the P-vs-P dedup pass in league_server._run_turn(); AI opponent
        # duplicates are resolved by the AI dedup pass there.

    # Hard rule: every warrior fights at most once per turn, so any warrior
    # already scheduled elsewhere (as someone else's pw) is excluded from
    # this team's pw pool.  Since team size = 5, this also caps every
    # team at 5 fights/turn - a rule with no exceptions.
    active_players = [w for w in player_team.active_warriors 
                      if (player_team.team_id, w.slot_index) not in global_used]
    if not active_players:
        print("  No active warriors to schedule.")
        return card

    # ------------------------------------------------------------------
    # STEP 1: BLOOD CHALLENGES
    # ------------------------------------------------------------------
    for bc in list(player_team.blood_challenges):
        # Skip if not active or expired (turns_remaining <= 0)
        if bc.get("status") != "active" or bc.get("turns_remaining", 0) <= 0:
            continue
        
        bc_target_name = bc.get("target_name", "")
        bc_dead_name = bc.get("dead_warrior_name", "")
        
        # Find the challenger on the player's team
        challenger = None
        if bc.get("challenger_name"):
            # Manager has selected a specific warrior
            challenger = player_team.warrior_by_name(bc["challenger_name"])
            if challenger and (challenger.slot_index in matched_players
                               or (player_team.team_id, challenger.slot_index) in global_used):
                # Selected warrior already fighting this turn (here or elsewhere)
                challenger = None
        
        if challenger is None:
            # Allow any available warrior to carry the BC
            available = [w for w in active_players if w.slot_index not in matched_players]
            if not available:
                continue
            challenger = random.choice(available)

        # Find the target in the opponent pool
        player_mgr = getattr(player_team, "manager_name", "")
        target_warrior = None
        target_team    = None
        for ot in opponent_teams:
            if ot.manager_name == player_mgr:
                continue
            for w in ot.active_warriors:
                if w.name.lower() == (bc_target_name or "").lower():
                    if (ot.team_id, w.slot_index) in global_used:
                        print(f"  Blood challenge target '{w.name}' already fighting this turn. Skipping.")
                        break
                    target_warrior = w
                    target_team    = ot
                    break
            if target_warrior:
                break

        if target_warrior is None:
            print(f"  Blood challenge target '{bc_target_name}' not found or already matched. Skipping.")
            continue

        succeeds = _challenge_succeeds(
            challenger.presence,
            target_warrior.presence,
            is_blood_challenge=True,
        )
        if succeeds:
            _schedule(ScheduledFight(
                player_warrior   = challenger,
                opponent         = target_warrior,
                player_team      = player_team,
                opponent_team    = target_team,
                opponent_manager = target_team.manager_name,
                fight_type       = "blood_challenge",
                challenger_name  = challenger.name,
            ))
            card[-1]._blood_challenge_info = {
                "target_name": bc_target_name,
                "dead_warrior_name": bc_dead_name,
            }
            matched_players.add(challenger.slot_index)
            matched_teams.add(target_team.team_id)
            print(f"  BLOOD CHALLENGE: {challenger.name} vs {target_warrior.name} - ACCEPTED")
            print(f"    (Avenging {bc_dead_name} against {bc_target_name}; {bc.get('turns_remaining')} turn(s) remaining)")
        else:
            print(
                f"  Blood challenge {challenger.name} → {bc_target_name} "
                f"was REFUSED (Presence check failed)."
            )

    # ------------------------------------------------------------------
    # STEP 1b: MONSTER FIGHTS (want_monster_fight flag set by manager)
    # ------------------------------------------------------------------
    monster_team = None   # lazy-created once if needed
    for pw in list(active_players):
        if pw.slot_index in matched_players:
            continue
        if not pw.want_monster_fight:
            continue
        if monster_team is None:
            monster_team = create_monster_team()
        import random as _rnd
        monster = _rnd.choice(monster_team.active_warriors)
        _schedule(ScheduledFight(
            player_warrior   = pw,
            opponent         = monster,
            player_team      = player_team,
            opponent_team    = monster_team,
            opponent_manager = "The Arena",
            fight_type       = "monster",
        ))
        matched_players.add(pw.slot_index)
        print(f"  MONSTER FIGHT: {pw.name} vs {monster.name}")
        # Clear the flag so it doesn't persist to next turn
        pw.want_monster_fight = False

    # ------------------------------------------------------------------
    # STEP 1c: RETIREMENTS (want_retire flag)
    # ------------------------------------------------------------------
    for pw in list(active_players):
        if pw.slot_index in matched_players:
            continue
        if not pw.want_retire:
            continue
        if not pw.can_retire:
            print(f"  RETIRE REJECTED: {pw.name} only has {pw.total_fights} fights (need 100).")
            pw.want_retire = False
            continue
        replacement = player_team.retire_warrior(pw)
        if replacement:
            print(f"  RETIREMENT: {pw.name} retires. {replacement.name} joins the team.")
        pw.want_retire = False
        matched_players.add(pw.slot_index)   # retired warriors don't fight this turn

    # ------------------------------------------------------------------
    # STEP 2a: CHAMPION CHALLENGES (highest non-blood priority)
    # If current champion exists, collect all challengers and pick one
    # ------------------------------------------------------------------
    if current_champion:
        champion_warrior = None
        champion_team    = None

        # Find the champion in the opponent pool
        for ot in opponent_teams:
            for w in ot.active_warriors:
                if w.name.lower() == current_champion.lower():
                    champion_warrior = w
                    champion_team    = ot
                    break
            if champion_warrior:
                break

        if champion_warrior and champion_team:
            champ_challengers = []
            for slot_idx, targets in player_team.challenges.items():
                if slot_idx in matched_players or (player_team.team_id, slot_idx) in global_used:
                    continue
                challenger = player_team.warriors[slot_idx] if slot_idx < len(player_team.warriors) else None
                if challenger is None or not challenger.is_alive:
                    continue

                for target_name in targets:
                    if (target_name.lower() == current_champion.lower() or
                        target_name.lower() == champion_team.manager_name.lower() or
                        target_name.lower() == champion_team.team_name.lower()):
                        champ_challengers.append((challenger, slot_idx, target_name))
                        break

            if champ_challengers:
                def _challenger_priority(entry):
                    challenger, _, _ = entry
                    presence = challenger.presence
                    recognition = getattr(challenger, "recognition", 0)
                    win_ratio = challenger.wins / max(1, challenger.total_fights)
                    return (-presence, -recognition, -win_ratio)

                champ_challengers.sort(key=_challenger_priority)
                challenger, chal_name, target_name = champ_challengers[0]

                succeeds = _challenge_succeeds(
                    challenger.presence,
                    champion_warrior.presence,
                    is_blood_challenge=False,
                    is_champion_challenge=True,
                )
                if succeeds:
                    _schedule(ScheduledFight(
                        player_warrior   = challenger,
                        opponent         = champion_warrior,
                        player_team      = player_team,
                        opponent_team    = champion_team,
                        opponent_manager = champion_team.manager_name,
                        fight_type       = "challenge",
                        challenger_name  = challenger.name,
                    ))
                    matched_players.add(challenger.slot_index)
                    matched_teams.add(champion_team.team_id)
                    if len(champ_challengers) > 1:
                        print(f"  *** CHAMPION CHALLENGE ACCEPTED: {challenger.name} vs {current_champion} ***")
                        print(f"      ({len(champ_challengers)} warriors wanted the challenge; {challenger.name} prevailed by presence/recognition)")
                    else:
                        print(f"  *** CHAMPION CHALLENGE ACCEPTED: {challenger.name} challenges {current_champion} ***")
                else:
                    print(f"  Champion challenge {challenger.name} → {current_champion} REFUSED (rare presence failure).")

    # ------------------------------------------------------------------
    # STEP 2b: REGULAR PLAYER-ISSUED CHALLENGES
    # ------------------------------------------------------------------
    for slot_idx, targets in player_team.challenges.items():
        if slot_idx in matched_players or (player_team.team_id, slot_idx) in global_used:
            continue
        challenger = player_team.warriors[slot_idx] if slot_idx < len(player_team.warriors) else None
        if challenger is None or not challenger.is_alive:
            continue

        for target_name in targets:
            # Skip if this is a champion challenge (already handled in STEP 2a)
            if current_champion and (
                target_name.lower() == current_champion.lower()
            ):
                continue
            
            # Try to find target in opponent pool
            player_mgr     = getattr(player_team, "manager_name", "")
            target_warrior = None
            target_team    = None

            for ot in opponent_teams:
                if ot.team_id in matched_teams:
                    continue
                if ot.manager_name == player_mgr:
                    continue
                # Match against manager name, team name, or warrior name
                if (target_name.lower() in ot.manager_name.lower()
                        or target_name.lower() in ot.team_name.lower()):
                    result = _find_opponent(challenger, [ot], matched_teams, global_used, global_matched_opponent_warriors)
                    if result:
                        target_warrior, target_team = result
                        break

                for w in ot.active_warriors:
                    if target_name.lower() in w.name.lower():
                        if (ot.team_id, w.slot_index) in global_used:
                            print(f"  Challenge target '{w.name}' already fighting this turn. Skipping.")
                            break
                        if not _challenge_in_bracket(challenger.total_fights,
                                                     w.total_fights):
                            print(
                                f"  Challenge {challenger.name} → {w.name} "
                                f"REJECTED: target has too little experience "
                                f"({w.total_fights} fights vs "
                                f"{challenger.total_fights} needed)."
                            )
                            target_warrior = None
                            break
                        target_warrior = w
                        target_team    = ot
                        break
                if target_warrior:
                    break

            if target_warrior is None:
                print(f"  Challenge target '{target_name}' not found or already matched.")
                continue

            challenger_manager = player_team.manager_name
            if _attempt_avoid_challenge(
                target_warrior,
                target_team,
                challenger.name,
                challenger_manager,
            ):
                print(f"  Challenge {challenger.name} → {target_warrior.name} AVOIDED by target!")
                continue

            succeeds = _challenge_succeeds(
                challenger.presence,
                target_warrior.presence,
                is_blood_challenge=False,
                is_champion_challenge=False,
            )
            if succeeds:
                _schedule(ScheduledFight(
                    player_warrior   = challenger,
                    opponent         = target_warrior,
                    player_team      = player_team,
                    opponent_team    = target_team,
                    opponent_manager = target_team.manager_name,
                    fight_type       = "challenge",
                    challenger_name  = challenger.name,
                ))
                matched_players.add(slot_idx)
                matched_teams.add(target_team.team_id)
                print(f"  Challenge accepted: {challenger.name} vs {target_warrior.name}")
                break
            else:
                print(
                    f"  Challenge {challenger_name} → {target_name} "
                    f"REFUSED (Presence check failed)."
                )

    # ------------------------------------------------------------------
    # STEP 3: MATCH REMAINING WARRIORS AGAINST OPPONENT TEAMS
    # ------------------------------------------------------------------
    remaining = [w for w in active_players if w.slot_index not in matched_players]

    for player_warrior in remaining:
        # For standard matching, don't restrict by matched_teams.
        # This allows multiple warriors to fight the same opponent team,
        # ensuring we maximize warrior-vs-warrior matches (peasants are fallback only).
        result = _find_opponent(player_warrior, opponent_teams, set(), global_used, global_matched_opponent_warriors)
        if result:
            opponent, opp_team = result
            _schedule(ScheduledFight(
                player_warrior   = player_warrior,
                opponent         = opponent,
                player_team      = player_team,
                opponent_team    = opp_team,
                opponent_manager = opp_team.manager_name,
                fight_type       = "standard",
            ))
            matched_players.add(player_warrior.slot_index)
            # Don't add to matched_teams for standard matches - allow multiple warriors
            # to fight the same opponent team. Only challenges (exclusive) use matched_teams.

    # ------------------------------------------------------------------
    # STEP 4: FILL UNMATCHED WITH PEASANTS
    # ------------------------------------------------------------------
    still_unmatched = [w for w in active_players if w.slot_index not in matched_players]

    if still_unmatched:
        for player_warrior in still_unmatched:
            # Scale peasants to each individual warrior's fight count so that
            # a rookie always faces rookie-level opponents.
            peasant_team = create_peasant_team(
                target_fight_count=player_warrior.total_fights
            )
            peasants = peasant_team.active_warriors
            peasant = random.choice(peasants)

            _schedule(ScheduledFight(
                player_warrior   = player_warrior,
                opponent         = peasant,
                player_team      = player_team,
                opponent_team    = peasant_team,
                opponent_manager = "The Arena",
                fight_type       = "peasant",
            ))
            matched_players.add(player_warrior.slot_index)

    print(f"\n  Fight card: {len(card)} bout(s) scheduled.")
    return card


# ---------------------------------------------------------------------------
# EXECUTE THE FIGHT CARD
# ---------------------------------------------------------------------------

def run_turn(
    player_team    : Team,
    opponent_teams : List[Team],
    verbose        : bool = True,
    champion_state : dict = None,
    global_used    : set  = None,   # shared warrior-name set across all teams this turn
) -> List[ScheduledFight]:
    """Build and execute all fights for one turn.
    Returns the completed ScheduledFight list with results attached.
    Saves fight logs, updates records.

    global_used is mutated in-place as fights are scheduled so callers
    running multiple teams can share it to prevent warriors fighting twice.
    """
    if champion_state is None:
        champion_state = {}
    if global_used is None:
        global_used = set()
    current_champion = champion_state.get("name", "")
    print(f"\n  === RUNNING TURN - {player_team.team_name} ===\n")
    print(f"  [run_turn start] archived_warriors={len(getattr(player_team,'archived_warriors',[]))}")

    card = build_fight_card(player_team, opponent_teams,
                            champion_state=champion_state,
                            global_used=global_used)

    for i, bout in enumerate(card, 1):
        pw = bout.player_warrior
        ow = bout.opponent
        print(f"\n  [{i}/{len(card)}] {pw.name} ({player_team.team_name}) "
              f"vs {ow.name} ({bout.opponent_team.team_name}) [{bout.fight_type}]")
        print("  " + "-" * 60)

        result = run_fight(
            pw, ow,
            team_a_name      = player_team.team_name,
            team_b_name      = bout.opponent_team.team_name,
            manager_a_name   = player_team.manager_name,
            manager_b_name   = bout.opponent_manager,
            is_monster_fight = (bout.fight_type == "monster"),
            fight_type       = bout.fight_type,
            challenger_name  = bout.challenger_name,
        )
        bout.result = result

        # Inject scout-attendance flavor text if any manager is watching either warrior
        try:
            from save import get_all_scouted_warriors, current_turn as _ct
            # Scouts are stored at (turn - 1) because increment_turn() runs before fights.
            scouted = get_all_scouted_warriors(_ct() - 1)
            attending = set()
            for tid, name in [(player_team.team_id, pw.name), (bout.opponent_team.team_id, ow.name)]:
                for mgr in scouted.get((tid, name), []):
                    attending.add(mgr)
            if attending:
                mgr_list = ", ".join(sorted(attending))
                scout_line = (
                    f"\n[A scout from {mgr_list}'s stable is in attendance, "
                    f"watching the proceedings with a keen eye.]\n"
                )
                result = result.__class__(
                    winner          = result.winner,
                    loser           = result.loser,
                    loser_died      = result.loser_died,
                    minutes_elapsed = result.minutes_elapsed,
                    narrative       = scout_line + result.narrative,
                    training_results= result.training_results,
                )
                bout.result = result
        except Exception:
            pass

        # Save fight log and capture fight_id for history
        fight_id = None
        try:
            log_path, fight_id = save_fight_log(
                result.narrative,
                player_team.team_name,
                bout.opponent_team.team_name,
            )
            bout.fight_id = fight_id
            if verbose:
                print(f"  Fight log saved: {log_path}")
        except IOError as e:
            print(f"  WARNING: Could not save fight log: {e}")

        # Record this fight in the player warrior's history and update popularity
        if result:
            pw_won    = result.winner and result.winner.name == pw.name
            pw_result = "win" if pw_won else "loss"
            pw.update_popularity(won=pw_won)
            pw.update_recognition(
                won=pw_won,
                killed_opponent=result.loser_died and pw_won,
                self_hp_pct=result.winner_hp_pct if pw_won else result.loser_hp_pct,
                opp_hp_pct=result.loser_hp_pct if pw_won else result.winner_hp_pct,
                self_knockdowns=result.winner_knockdowns if pw_won else result.loser_knockdowns,
                opp_knockdowns=result.loser_knockdowns if pw_won else result.winner_knockdowns,
                self_near_kills=result.winner_near_kills if pw_won else result.loser_near_kills,
                opp_near_kills=result.loser_near_kills if pw_won else result.winner_near_kills,
                minutes_elapsed=result.minutes_elapsed,
                max_minutes=60 if getattr(bout, "is_monster_fight", False) else 30,
                opponent_total_fights=ow.total_fights,
            )
            # Update wins/losses/kills/total_fights for both warriors
            pw.record_result(pw_result, killed_opponent=result.loser_died and pw_won)
            ow.record_result("loss" if pw_won else "win", killed_opponent=result.loser_died and not pw_won)
            print(f"  [DEBUG] {pw.name}: {pw.wins}-{pw.losses}-{pw.kills} after record_result")
            print(f"  [DEBUG] {ow.name}: {ow.wins}-{ow.losses}-{ow.kills} after record_result")

            from save import current_turn
            # Determine fight type: if opponent is champion, mark as 'champion'
            fight_type_for_record = "champion" if (current_champion and ow.name == current_champion) else bout.fight_type
            pw.fight_history.append({
                "turn"                 : current_turn(),
                "opponent_name"        : ow.name,
                "opponent_race"        : ow.race.name,
                "opponent_team"        : bout.opponent_team.team_name,
                "opponent_manager_name": getattr(bout.opponent_team, "manager_name", "") or '',
                "result"               : pw_result,
                "minutes"              : result.minutes_elapsed,
                "fight_id"             : fight_id,
                "warrior_slain"        : result.loser_died and result.loser is pw,
                "opponent_slain"       : result.loser_died and (result.winner is not None)
                                          and result.winner.name == pw.name,
                "fight_type"           : fight_type_for_record,
            })

            # Also record this fight in the opponent warrior's history so
            # scouting reports can load the fight log via fight_id.
            if fight_id and bout.fight_type not in ("monster", "peasant"):
                ow_result = "loss" if pw_won else "win"
                # Determine fight type: if player_warrior is champion, mark as 'champion'
                fight_type_for_opp = "champion" if (current_champion and pw.name == current_champion) else bout.fight_type
                ow.fight_history.append({
                    "turn"                 : current_turn(),
                    "opponent_name"        : pw.name,
                    "opponent_race"        : pw.race.name if hasattr(pw.race, "name") else str(pw.race),
                    "opponent_team"        : player_team.team_name,
                    "opponent_manager_name": getattr(player_team, "manager_name", "") or '',
                    "result"               : ow_result,
                    "minutes"              : result.minutes_elapsed,
                    "fight_id"             : fight_id,
                    "warrior_slain"        : result.loser_died and result.loser is ow,
                    "opponent_slain"       : result.loser_died and result.loser is pw,
                    "fight_type"           : fight_type_for_opp,
                })

        # Handle player warrior death
        if result.loser_died and result.loser is pw:
            print(f"  *** {pw.name} has been SLAIN! Replacement incoming. ***")
            player_team.kill_warrior(
                pw,
                killed_by     = ow.name,
                killer_fights = ow.total_fights,
                fight_type    = fight_type_for_record,
            )
            try:
                from save import archive_warrior_history
                archive_warrior_history(player_team.team_name, pw)
                print(f"  Graveyard file written for {pw.name}.")
            except Exception as _ge:
                print(f"  WARNING: Could not write graveyard file for {pw.name}: {_ge}")

        # Handle opponent death
        if result.loser_died and result.loser is ow:
            if bout.fight_type == "monster":
                # The rarest event: player warrior slays a monster.
                # The warrior is absorbed into The Monsters with boosted stats,
                # replacing the slain monster on the persisted roster.
                pw.monster_kills = getattr(pw, 'monster_kills', 0) + 1
                pw.ascended_to_monster = True
                _absorb_into_monsters(pw, player_team, ow, bout.opponent_team)
                print(f"  !!! {pw.name} has SLAIN a monster and joins The Monsters! !!!")
                print(f"  >>> A replacement slot is now available on {player_team.team_name}")
            elif bout.fight_type == "peasant":
                pass   # Peasants have no persistent team - nothing to update
            else:
                bout.opponent_team.kill_warrior(ow, killed_by=pw.name,
                                                killer_fights=pw.total_fights,
                                                fight_type=bout.fight_type)

        # Handle blood challenge victory
        if bout.fight_type == "blood_challenge" and pw_won:
            # Player won the blood challenge - mark it as avenged
            bc_info = getattr(bout, "_blood_challenge_info", {})
            if bc_info:
                target_name = bc_info.get("target_name")
                dead_warrior_name = bc_info.get("dead_warrior_name")
                if player_team.mark_blood_challenge_avenged(target_name, dead_warrior_name):
                    print(f"  !!! BLOOD CHALLENGE AVENGED: {pw.name} has avenged {dead_warrior_name}! !!!")

        if verbose:
            if result.winner:
                outcome = "WON" if result.winner is pw else "LOST"
                print(f"  Result: {pw.name} {outcome} in {result.minutes_elapsed} minute(s)")
            else:
                print(f"  Result: DRAW after {result.minutes_elapsed} minute(s)")

    # Clear regular challenges
    player_team.clear_challenges()
    
    # Decrement blood challenge turns and clean up expired ones
    player_team.decrement_blood_challenge_turns()
    # Remove expired blood challenges (turns_remaining == 0 and not avenged)
    player_team.blood_challenges = [
        bc for bc in player_team.blood_challenges 
        if not (bc.get("turns_remaining", 0) <= 0 and bc.get("status") == "active")
    ]

    # Increment turns_active for every living warrior on the team
    for w in player_team.active_warriors:
        w.turns_active = getattr(w, 'turns_active', 0) + 1

    from save import current_turn
    turn = current_turn()

    # Update last_turn_ran for the team
    player_team.last_turn_ran = turn

    # Save the player team
    save_team(player_team)

    # Update opponent teams that fought this turn so they remain eligible for
    # newsletter retention when they later miss a turn or two.
    opponent_results = {}
    for b in card:
        if not b.opponent_team:
            continue
        if b.opponent_team.team_name in {"The Monsters", "The Peasants"}:
            continue
        ot = b.opponent_team
        key = (getattr(ot, 'team_id', 0), id(ot))
        if key not in opponent_results:
            opponent_results[key] = {"team": ot, "w": 0, "l": 0, "k": 0}
        if not b.result:
            continue
        pw_won = b.result.winner and b.result.winner.name == b.player_warrior.name
        if pw_won:
            opponent_results[key]["l"] += 1
        else:
            opponent_results[key]["w"] += 1
            if b.result.loser_died:
                opponent_results[key]["k"] += 1

    saved_opponent_teams = set()
    for result in opponent_results.values():
        ot = result["team"]
        ot.turn_history.append({"turn": turn,
                                "w": result["w"],
                                "l": result["l"],
                                "k": result["k"]})
        ot.last_turn_ran = turn
        save_team(ot)
        saved_opponent_teams.add(getattr(ot, 'team_id', 0))

    # Save any other opponent teams that were present but had no result object,
    # or that were not included in the result summary above.
    for b in card:
        if b.opponent_team and b.opponent_team.team_name not in {"The Monsters", "The Peasants"}:
            tid = getattr(b.opponent_team, 'team_id', 0)
            if tid not in saved_opponent_teams:
                save_team(b.opponent_team)
                saved_opponent_teams.add(tid)

    # VALIDATION: Check for fight frequency violations
    warrior_violations = validate_warrior_fight_frequency(card)
    team_violations = validate_team_fight_count(card, max_fights=5)
    
    if warrior_violations:
        print(f"\n  WARNING: Found {len(warrior_violations)} warrior(s) fighting more than once per turn:")
        for v in warrior_violations:
            print(f"    - {v['warrior']} ({v['team']}): {v['fight_count']} fights (expected max 1)")
    
    if team_violations:
        print(f"\n  WARNING: Found {len(team_violations)} team(s) with more than 5 fights:")
        for v in team_violations:
            print(f"    - {v['team']}: {v['fight_count']} fights (expected max {v['max_allowed']})")

    # Write turn logs (HTML + plain text matchmaking log)
    from save import write_turn_logs, save_newsletter, load_champion_state, save_champion_state
    turn = current_turn()
    write_turn_logs(turn, card, player_team.team_name)

    # Update team turn_history for last-5-turns newsletter column
    turn_w = sum(1 for b in card if b.result and b.result.winner
                 and b.result.winner.name == b.player_warrior.name)
    turn_l = len(card) - turn_w
    turn_k = sum(1 for b in card if b.result and b.result.loser_died
                 and b.result.winner and b.result.winner.name == b.player_warrior.name)
    player_team.turn_history.append({"turn": turn, "w": turn_w, "l": turn_l, "k": turn_k})
    save_team(player_team)

    # Generate newsletter - include opponent teams, exclude Monsters/Peasants
    from newsletter import generate_newsletter, _update_champion
    import datetime as _dt
    processed_date = _dt.date.today().strftime("%m/%d/%Y")

    deaths_this_turn = []
    for b in card:
        if b.result and b.result.loser_died:
            loser = b.result.loser
            # Determine which team the loser belongs to
            if loser is b.player_warrior:
                loser_team = b.player_team
            else:
                loser_team = b.opponent_team

            deaths_this_turn.append({
                "name"    : loser.name,
                "team"    : loser_team.team_name,
                "team_id" : loser_team.team_id,
                "w"       : loser.wins, "l": loser.losses, "k": loser.kills,
                "killed_by": b.result.winner.name,
            })
            print(f"  [DEATH] {loser.name} ({loser_team.team_name}): {loser.wins}-{loser.losses}-{loser.kills}")

    # Build full team list: player team + opponent teams + recently active saved teams.
    _NPC = {"The Monsters", "The Peasants"}
    print(f"  [nl_prep] {player_team.team_name} archived_warriors={len(getattr(player_team,'archived_warriors',[]))}")
    all_teams_for_nl = [player_team]
    team_ids = {getattr(player_team, 'team_id', 0)}
    for ot in opponent_teams:
        if ot.team_name not in _NPC:
            all_teams_for_nl.append(ot)
            team_ids.add(getattr(ot, 'team_id', 0))

    # Keep recently active saved teams for up to 3 turns of inactivity.
    try:
        for saved_team in load_all_teams():
            saved_id = getattr(saved_team, 'team_id', 0)
            if saved_id in team_ids:
                continue
            if saved_team.team_name in _NPC:
                continue

            last_run = getattr(saved_team, 'last_turn_ran', 0)
            if last_run > 0 and last_run >= turn - 3:
                all_teams_for_nl.append(saved_team)
                team_ids.add(saved_id)
                continue

            hist = getattr(saved_team, 'turn_history', [])
            if not hist:
                continue
            last_turn = max((entry.get('turn', 0) for entry in hist), default=0)
            if last_turn >= turn - 3:
                all_teams_for_nl.append(saved_team)
                team_ids.add(saved_id)
    except Exception:
        pass

    champion_state = load_champion_state()

    # Detect if the reigning champion was defeated this turn.
    # The champion retains the title unless they actually lose a fight -
    # not fighting, or fighting a peasant, never costs them the title.
    _champ_beaten_by   = None
    _champ_beaten_team = None
    _champ_beaten_team_id = 0
    _cur_champ = champion_state.get("name", "")
    if _cur_champ:
        for _b in card:
            if not _b.result: continue
            _pw_won = _b.result.winner and _b.result.winner.name == _b.player_warrior.name
            _winner = _b.player_warrior if _pw_won else _b.opponent
            _loser  = _b.opponent       if _pw_won else _b.player_warrior
            _winner_team = (player_team.team_name if _pw_won
                            else _b.opponent_team.team_name)
            _winner_team_id = (player_team.team_id if _pw_won
                               else _b.opponent_team.team_id)
            if _loser.name == _cur_champ:
                _champ_beaten_by   = _winner.name
                _champ_beaten_team = _winner_team
                _champ_beaten_team_id = _winner_team_id
                break

    prev_champion_name = champion_state.get("name", "")
    champion_state, is_new_champion = _update_champion(
        all_teams_for_nl, champion_state, deaths_this_turn,
        champion_beaten_by=_champ_beaten_by,
        champion_beaten_team=_champ_beaten_team,
        champion_beaten_team_id=_champ_beaten_team_id,
        prev_champion_name=prev_champion_name,
        card=card  # Add this line - pass the card data
    )
    save_champion_state(champion_state)

    newsletter_text = generate_newsletter(
        turn_num           = turn,
        card               = card,
        teams              = all_teams_for_nl,
        deaths             = deaths_this_turn,
        champion_state     = champion_state,
        processed_date     = processed_date,
        is_new_champion    = is_new_champion,
    )
    save_newsletter(turn, newsletter_text)

    print(f"\n  Turn complete. {len(card)} fight(s) resolved.")
    return card


# ---------------------------------------------------------------------------
# TURN SUMMARY
# ---------------------------------------------------------------------------

def turn_summary(card: List[ScheduledFight], player_team_name: str) -> str:
    """Return a human-readable summary of fight results."""
    lines = [
        "",
        "=" * 62,
        f"  TURN RESULTS - {player_team_name.upper()}",
        "=" * 62,
    ]
    wins = losses = draws = 0

    for bout in card:
        pw = bout.player_warrior
        r  = bout.result
        if r is None:
            lines.append(f"  {pw.name:<20} - No result")
            continue

        if r.winner is pw:
            outcome = "WIN "
            wins   += 1
        elif r.winner is None:
            outcome = "DRAW"
            draws  += 1
        else:
            outcome = "LOSS"
            losses += 1

        died_note = " (SLAIN)" if (r.loser_died and r.loser is pw) else ""
        kill_note = " (KILLED OPPONENT)" if (r.loser_died and r.winner is pw) else ""

        opp_type = f"[{bout.fight_type}]"
        lines.append(
            f"  {pw.name:<20} {outcome}  vs {bout.opponent.name:<20} "
            f"{opp_type:<18}{died_note}{kill_note}"
        )

    lines += [
        "  " + "-" * 60,
        f"  Wins: {wins}   Losses: {losses}   Draws: {draws}",
        "=" * 62,
    ]
    return "\n".join(lines)
