# =============================================================================
# matchmaking.py — BLOODSPIRE Turn Matchmaking Engine
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
from save      import save_team, save_fight_log


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


# ---------------------------------------------------------------------------
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
    No special rookie bucket — graduated window applies from fight 0 onward.
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
    already_matched: set,          # team_id values already used this card
    global_used    : set = None,   # warrior names used across ALL cards this turn
) -> Optional[Tuple[Warrior, Team]]:
    """
    Find the best-matched opponent warrior from all available teams.

    Preference:
      1. Team whose average rating is closest to the player warrior.
      2. Pick the individual warrior on that team with the closest rating.
      3. Skip teams already matched this turn.
      4. Skip individual warriors already scheduled globally this turn.

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

    def _available_warriors(t):
        """Active warriors on this team not yet used globally."""
        return [w for w in t.active_warriors if w.name not in _used]

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
        return pool[0], best_team

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
        value — kill_warrior marks them is_dead, preventing further fights.
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
    src["race"] = "Monster"          # Race change — freezes record in run_fight
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
    # The original warrior is untouched up to this point — archive will
    # preserve their real stats and 34-2-16 record.
    player_team.kill_warrior(
        warrior,
        killed_by     = "The Monsters",
        killer_fights = 999,
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
    warrior_fight_map = {}  # {warrior_name: [(team_name, ScheduledFight), ...]}
    
    _NPC_TEAM_NAMES = {"The Monsters", "The Peasants"}
    
    for scheduled_fight in card:
        if not scheduled_fight.result:
            continue  # Skip unresolved fights
            
        player_warrior = scheduled_fight.player_warrior
        opponent = scheduled_fight.opponent
        player_team_name = scheduled_fight.player_team.team_name if hasattr(scheduled_fight.player_team, "team_name") else "?"
        opponent_team_name = scheduled_fight.opponent_team.team_name if hasattr(scheduled_fight.opponent_team, "team_name") else "?"
        
        # Record player warrior if on a user/AI team (not NPC)
        if player_team_name not in _NPC_TEAM_NAMES:
            key = player_warrior.name
            if key not in warrior_fight_map:
                warrior_fight_map[key] = []
            warrior_fight_map[key].append((player_team_name, scheduled_fight))
        
        # Record opponent if on a user/AI team (not NPC)
        if opponent_team_name not in _NPC_TEAM_NAMES:
            key = opponent.name
            if key not in warrior_fight_map:
                warrior_fight_map[key] = []
            warrior_fight_map[key].append((opponent_team_name, scheduled_fight))
    
    # Check for violations
    for warrior_name, fight_list in warrior_fight_map.items():
        if len(fight_list) > 1:
            # Multiple fights for a user/AI warrior — this is a violation
            team_name = fight_list[0][0]
            violations.append({
                "warrior": warrior_name,
                "team": team_name,
                "fight_count": len(fight_list),
                "fights": [f for _, f in fight_list],
            })
    
    return violations


def validate_team_fight_count(card: List[ScheduledFight], max_fights: int = 5) -> List[dict]:
    """
    Validate that user and AI teams have at most max_fights (default 5) per turn.
    
    Returns a list of violation dicts:
        {team: str, fight_count: int, max_allowed: int}
    """
    violations = []
    team_fight_count = {}  # {team_name: count}
    
    _NPC_TEAM_NAMES = {"The Monsters", "The Peasants"}
    
    for scheduled_fight in card:
        if not scheduled_fight.result:
            continue  # Skip unresolved fights
            
        player_team_name = scheduled_fight.player_team.team_name if hasattr(scheduled_fight.player_team, "team_name") else "?"
        opponent_team_name = scheduled_fight.opponent_team.team_name if hasattr(scheduled_fight.opponent_team, "team_name") else "?"
        
        # Count fights for player team
        if player_team_name not in _NPC_TEAM_NAMES:
            team_fight_count[player_team_name] = team_fight_count.get(player_team_name, 0) + 1
        
        # Count fights for opponent team
        if opponent_team_name not in _NPC_TEAM_NAMES:
            team_fight_count[opponent_team_name] = team_fight_count.get(opponent_team_name, 0) + 1
    
    # Check for violations
    for team_name, count in team_fight_count.items():
        if count > max_fights:
            violations.append({
                "team": team_name,
                "fight_count": count,
                "max_allowed": max_fights,
            })
    
    return violations


def build_fight_card(
    player_team    : Team,
    opponent_teams : List[Team],
    champion_state : dict = None,
    global_used    : set = None,    # shared set of warrior names used across ALL teams this turn
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
    Warriors from either side of a fight are added to it so no warrior fights
    more than once per turn regardless of how many player teams are processing.
    """
    if champion_state is None:
        champion_state = {}
    if global_used is None:
        global_used = set()

    current_champion = champion_state.get("name", "")
    card            : List[ScheduledFight]  = []
    matched_players : set = set()         # player warrior names already scheduled this card
    matched_teams   : set = set()         # opponent team IDs already used this card

    def _schedule(fight: ScheduledFight):
        """Add a fight to the card and mark both warriors as used globally."""
        card.append(fight)
        global_used.add(fight.player_warrior.name)
        if fight.fight_type not in ("monster", "peasant"):
            global_used.add(fight.opponent.name)

    # Hard rule: every warrior fights at most once per turn, so any warrior
    # already scheduled elsewhere (as someone else's opponent) is excluded
    # from this team's pw pool.  Since team size = 5, this also caps every
    # team at 5 fights/turn — a rule with no exceptions.
    active_players = [w for w in player_team.active_warriors
                      if w.name not in global_used]
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
            if challenger and (challenger.name in matched_players
                               or challenger.name in global_used):
                # Selected warrior already fighting this turn (here or elsewhere)
                challenger = None
        
        if challenger is None:
            # Allow any available warrior to carry the BC
            available = [w for w in active_players if w.name not in matched_players]
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
                    if w.name in global_used:
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
            matched_players.add(challenger.name)
            matched_teams.add(target_team.team_id)
            print(f"  BLOOD CHALLENGE: {challenger.name} vs {target_warrior.name} — ACCEPTED")
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
        if pw.name in matched_players:
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
        matched_players.add(pw.name)
        print(f"  MONSTER FIGHT: {pw.name} vs {monster.name}")
        # Clear the flag so it doesn't persist to next turn
        pw.want_monster_fight = False

    # ------------------------------------------------------------------
    # STEP 1c: RETIREMENTS (want_retire flag)
    # ------------------------------------------------------------------
    for pw in list(active_players):
        if pw.name in matched_players:
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
        matched_players.add(pw.name)   # retired warriors don't fight this turn

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
            for challenger_name, targets in player_team.challenges.items():
                if challenger_name in matched_players or challenger_name in global_used:
                    continue
                challenger = player_team.warrior_by_name(challenger_name)
                if challenger is None or not challenger.is_alive:
                    continue

                for target_name in targets:
                    if (target_name.lower() == current_champion.lower() or
                        target_name.lower() == champion_team.manager_name.lower() or
                        target_name.lower() == champion_team.team_name.lower()):
                        champ_challengers.append((challenger, challenger_name, target_name))
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
                    matched_players.add(chal_name)
                    matched_teams.add(champion_team.team_id)
                    if len(champ_challengers) > 1:
                        print(f"  *** CHAMPION CHALLENGE ACCEPTED: {chal_name} vs {current_champion} ***")
                        print(f"      ({len(champ_challengers)} warriors wanted the challenge; {chal_name} prevailed by presence/recognition)")
                    else:
                        print(f"  *** CHAMPION CHALLENGE ACCEPTED: {chal_name} challenges {current_champion} ***")
                else:
                    print(f"  Champion challenge {chal_name} → {current_champion} REFUSED (rare presence failure).")

    # ------------------------------------------------------------------
    # STEP 2b: REGULAR PLAYER-ISSUED CHALLENGES
    # ------------------------------------------------------------------
    for challenger_name, targets in player_team.challenges.items():
        if challenger_name in matched_players or challenger_name in global_used:
            continue
        challenger = player_team.warrior_by_name(challenger_name)
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
                    result = _find_opponent(challenger, [ot], matched_teams)
                    if result:
                        target_warrior, target_team = result
                        break

                for w in ot.active_warriors:
                    if target_name.lower() in w.name.lower():
                        if w.name in global_used:
                            print(f"  Challenge target '{w.name}' already fighting this turn. Skipping.")
                            break
                        if not _challenge_in_bracket(challenger.total_fights,
                                                     w.total_fights):
                            print(
                                f"  Challenge {challenger_name} → {w.name} "
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
                challenger_name,
                challenger_manager,
            ):
                print(f"  Challenge {challenger_name} → {target_warrior.name} AVOIDED by target!")
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
                matched_players.add(challenger_name)
                matched_teams.add(target_team.team_id)
                print(f"  Challenge accepted: {challenger_name} vs {target_warrior.name}")
                break
            else:
                print(
                    f"  Challenge {challenger_name} → {target_name} "
                    f"REFUSED (Presence check failed)."
                )

    # ------------------------------------------------------------------
    # STEP 3: MATCH REMAINING WARRIORS AGAINST OPPONENT TEAMS
    # ------------------------------------------------------------------
    remaining = [w for w in active_players if w.name not in matched_players]

    for player_warrior in remaining:
        result = _find_opponent(player_warrior, opponent_teams, matched_teams, global_used)
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
            matched_players.add(player_warrior.name)
            matched_teams.add(opp_team.team_id)

    # ------------------------------------------------------------------
    # STEP 4: FILL UNMATCHED WITH PEASANTS
    # ------------------------------------------------------------------
    still_unmatched = [w for w in active_players if w.name not in matched_players]

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
            matched_players.add(player_warrior.name)

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
    print(f"\n  === RUNNING TURN — {player_team.team_name} ===\n")
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
            challenger_name  = bout.challenger_name,
        )
        bout.result = result

        # Inject scout-attendance flavor text if any manager is watching either warrior
        try:
            from save import get_all_scouted_warriors, current_turn as _ct
            # Scouts are stored at (turn - 1) because increment_turn() runs before fights.
            scouted = get_all_scouted_warriors(_ct() - 1)
            attending = set()
            for warrior in (pw, ow):
                for mgr in scouted.get(warrior.name, []):
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
            from save import current_turn
            # Determine fight type: if opponent is champion, mark as 'champion'  
            fight_type_for_record = "champion" if (current_champion and ow.name == current_champion) else bout.fight_type
            pw.fight_history.append({
                "turn"           : current_turn(),
                "opponent_name"  : ow.name,
                "opponent_race"  : ow.race.name,
                "opponent_team"  : bout.opponent_team.team_name,
                "result"         : pw_result,
                "minutes"        : result.minutes_elapsed,
                "fight_id"       : fight_id,
                "warrior_slain"  : result.loser_died and result.loser is pw,
                "opponent_slain" : result.loser_died and (result.winner is not None)
                                   and result.winner.name == pw.name,
                "fight_type"     : fight_type_for_record,
            })

            # Also record this fight in the opponent warrior's history so
            # scouting reports can load the fight log via fight_id.
            if fight_id and bout.fight_type not in ("monster", "peasant"):
                ow_result = "loss" if pw_won else "win"
                # Determine fight type: if player_warrior is champion, mark as 'champion'
                fight_type_for_opp = "champion" if (current_champion and pw.name == current_champion) else bout.fight_type
                ow.fight_history.append({
                    "turn"           : current_turn(),
                    "opponent_name"  : pw.name,
                    "opponent_race"  : pw.race.name if hasattr(pw.race, "name") else str(pw.race),
                    "opponent_team"  : player_team.team_name,
                    "result"         : ow_result,
                    "minutes"        : result.minutes_elapsed,
                    "fight_id"       : fight_id,
                    "warrior_slain"  : result.loser_died and result.loser is ow,
                    "opponent_slain" : result.loser_died and result.loser is pw,
                    "fight_type"     : fight_type_for_opp,
                })

        # Handle player warrior death
        if result.loser_died and result.loser is pw:
            print(f"  *** {pw.name} has been SLAIN! Replacement incoming. ***")
            player_team.kill_warrior(
                pw,
                killed_by     = ow.name,
                killer_fights = ow.total_fights,
            )

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
                pass   # Peasants have no persistent team — nothing to update
            else:
                bout.opponent_team.kill_warrior(ow)

        # Handle blood challenge victory
        if bout.fight_type == "blood_challenge" and pw_won:
            # Player won the blood challenge — mark it as avenged
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

    # Save everything
    save_team(player_team)

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
    from save import write_turn_logs, save_newsletter, load_champion_state, save_champion_state, load_newsletter_voice
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

    # Generate newsletter — include opponent teams, exclude Monsters/Peasants
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
                "w"       : loser.wins, "l": loser.losses, "k": loser.kills,
                "killed_by": b.result.winner.name,
            })

    # Build full team list: player team + opponent teams (skip Monsters/Peasants)
    _NPC = {"The Monsters", "The Peasants"}
    print(f"  [nl_prep] {player_team.team_name} archived_warriors={len(getattr(player_team,'archived_warriors',[]))}")
    all_teams_for_nl = [player_team]
    for ot in opponent_teams:
        if ot.team_name not in _NPC:
            all_teams_for_nl.append(ot)

    champion_state = load_champion_state()

    # Detect if the reigning champion was defeated this turn.
    # The champion retains the title unless they actually lose a fight —
    # not fighting, or fighting a peasant, never costs them the title.
    _champ_beaten_by   = None
    _champ_beaten_team = None
    _cur_champ = champion_state.get("name", "")
    if _cur_champ:
        for _b in card:
            if not _b.result: continue
            _pw_won = _b.result.winner and _b.result.winner.name == _b.player_warrior.name
            _winner = _b.player_warrior if _pw_won else _b.opponent
            _loser  = _b.opponent       if _pw_won else _b.player_warrior
            _winner_team = (player_team.team_name if _pw_won
                            else _b.opponent_team.team_name)
            if _loser.name == _cur_champ:
                _champ_beaten_by   = _winner.name
                _champ_beaten_team = _winner_team
                break

    prev_champion_name = champion_state.get("name", "")
    champion_state, is_new_champion = _update_champion(
        all_teams_for_nl, champion_state, deaths_this_turn,
        champion_beaten_by=_champ_beaten_by,
        champion_beaten_team=_champ_beaten_team,
        prev_champion_name=prev_champion_name,
    )
    save_champion_state(champion_state)

    voice = load_newsletter_voice()
    newsletter_text = generate_newsletter(
        turn_num           = turn,
        card               = card,
        teams              = all_teams_for_nl,
        deaths             = deaths_this_turn,
        champion_state     = champion_state,
        voice              = voice,
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
        f"  TURN RESULTS — {player_team_name.upper()}",
        "=" * 62,
    ]
    wins = losses = draws = 0

    for bout in card:
        pw = bout.player_warrior
        r  = bout.result
        if r is None:
            lines.append(f"  {pw.name:<20} — No result")
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
