# =============================================================================
# newsletter.py - THE AGONY AMPHITHEATRE Newsletter Generator
# =============================================================================
import random, datetime, json, os, re
from typing import List, Optional

ARENA_NAME  = "The Agony Amphitheatre"
ARENA_ID    = 1
_NPC_TEAM_NAMES = {"The Monsters", "The Peasants"}
_NPC_RACES      = {"Monster", "Peasant"}

# ANSI styling used for section headers throughout the newsletter.
# Codes 98/99/998/999 are private markers (not real ANSI colors) the client
# uses to pick a font-size, without affecting the same bold-red code used
# inline for manager names in the standings tables.
HDR_RED    = "\033[1;31;99m"   # bold red, +~15% size  - fight sub-headers (Monster Fights, etc.)
HDR_RED_LG = "\033[1;31;98m"   # bold red, +6px size   - main section headers
HDR_BOLD   = "\033[1;99m"      # bold only, +~15% size - Top Teams / Top Managers headers
HDR_TITLE  = "\033[1;999m"     # bold, centered, large - masthead title (arena name)
HDR_SUBTITLE = "\033[1;998m"   # bold, centered, medium - masthead subtitle (turn number)
HDR_RESET  = "\033[0m"

TIER_CHAMPION  = "CHAMPION"
TIER_ELITES    = "ELITES"
TIER_EXPERTS   = "EXPERTS"
TIER_VETERANS  = "VETERANS"
TIER_ADEPTS    = "ADEPTS"
TIER_INITIATES = "INITIATES"
TIER_ROOKIES   = "ROOKIES"
TIER_RECRUITS  = "RECRUITS"


NAME_LIMIT = 30
LEAGUE_DATA_DIR = r"C:\BPClone_Claude\saves\league"

class _BoutWrapper:
    """Wrapper to handle both dict and object bout formats uniformly"""
    def __init__(self, bout):
        self._bout = bout
        self._is_dict = isinstance(bout, dict)

    def __getattr__(self, name):
        if name.startswith('_'):
            return object.__getattribute__(self, name)
        if self._is_dict:
            val = self._bout.get(name)
            # If the value is a dict or object, wrap it too
            if isinstance(val, (dict, object)) and not isinstance(val, (str, int, float, bool, type(None))):
                return _BoutWrapper(val) if isinstance(val, dict) else val
            return val
        val = getattr(self._bout, name, None)
        return val

    def get(self, name, default=None):
        if self._is_dict:
            return self._bout.get(name, default)
        return getattr(self._bout, name, default)

def _load_standings_data() -> dict:
    """Load complete standings data from standings.json"""
    standings_path = os.path.join(LEAGUE_DATA_DIR, "standings.json")
    if os.path.exists(standings_path):
        try:
            with open(standings_path, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def _load_managers_data() -> dict:
    """Load complete managers data from managers.json"""
    managers_path = os.path.join(LEAGUE_DATA_DIR, "managers.json")
    if os.path.exists(managers_path):
        try:
            with open(managers_path, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def _trunc(name: str, n: int = NAME_LIMIT) -> str:
    return str(name)[:n]


def _warrior_tier(w, is_champion: bool) -> str:
    """Assign a warrior to a tier based on recognition rating (0-100).

    Champion: determined externally (is_champion flag)
    Elites:   87 - 100   (flat scoring: ~29+ wins equivalent)
    Experts:  71 - 86   (flat scoring: ~23+ wins equivalent)
    Veterans: 56 - 70   (flat scoring: ~18+ wins equivalent)
    Adepts:   41 - 55
    Initiates: 26 - 40
    Rookies:  13 - 25
    Recruits: 0  - 12
    """
    if is_champion: return TIER_CHAMPION
    rec = getattr(w, "recognition", 0)
    if rec >= 87:   return TIER_ELITES
    if rec >= 71:   return TIER_EXPERTS
    if rec >= 56:   return TIER_VETERANS
    if rec >= 41:   return TIER_ADEPTS
    if rec >= 26:   return TIER_INITIATES
    if rec >= 13:   return TIER_ROOKIES
    return TIER_RECRUITS


def _apply_tiebreakers(candidates: list) -> Optional[tuple]:
    """
    Apply tie-breaker chain to resolve champion selection when multiple warriors
    are tied at the highest recognition level.

    Tie-breaker order:
    1. Most Kills
    2. Most Wins
    3. Fewest Losses (ascending)
    4. Highest Popularity
    5. Alphabetical by Name (final guarantee of single result)

    Args:
        candidates: list of (warrior_obj, team_name, team_id) tuples, all tied at same recognition

    Returns:
        (warrior_obj, team_name, team_id) of the champion, or None if no candidates
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Tie-breaker 1: Most Kills
    best_kills = max(getattr(c[0], 'kills', 0) for c in candidates)
    candidates = [c for c in candidates if getattr(c[0], 'kills', 0) == best_kills]
    if len(candidates) == 1:
        print(f"[DEBUG TIEBREAK] Resolved by kills: {candidates[0][0].name} with {best_kills} kills")
        return candidates[0]

    # Tie-breaker 2: Most Wins
    best_wins = max(getattr(c[0], 'wins', 0) for c in candidates)
    candidates = [c for c in candidates if getattr(c[0], 'wins', 0) == best_wins]
    if len(candidates) == 1:
        print(f"[DEBUG TIEBREAK] Resolved by wins: {candidates[0][0].name} with {best_wins} wins")
        return candidates[0]

    # Tie-breaker 3: Fewest Losses (ascending order)
    best_losses = min(getattr(c[0], 'losses', 0) for c in candidates)
    candidates = [c for c in candidates if getattr(c[0], 'losses', 0) == best_losses]
    if len(candidates) == 1:
        print(f"[DEBUG TIEBREAK] Resolved by losses: {candidates[0][0].name} with {best_losses} losses")
        return candidates[0]

    # Tie-breaker 4: Highest Popularity
    best_pop = max(getattr(c[0], 'popularity', 0) for c in candidates)
    candidates = [c for c in candidates if getattr(c[0], 'popularity', 0) == best_pop]
    if len(candidates) == 1:
        print(f"[DEBUG TIEBREAK] Resolved by popularity: {candidates[0][0].name} with {best_pop} popularity")
        return candidates[0]

    # Tie-breaker 5: Alphabetical by Name (final guarantee)
    candidates.sort(key=lambda c: c[0].name)
    print(f"[DEBUG TIEBREAK] Resolved by name: {candidates[0][0].name} (alphabetical)")
    return candidates[0]


def _update_champion(teams, champion_state: dict, deaths_this_turn: list,
                     champion_beaten_by: str = None, champion_beaten_by_wid: int = None,
                     champion_beaten_team: str = None, champion_beaten_team_id: int = 0,
                     prev_champion_name: str = None,
                     card = None, ineligible_name: str = None) -> tuple:
    """
    Update the champion state based on battle outcomes and warrior recognition.

    Champion Rules:
    1. If champion is beaten in combat, defeater becomes new champion immediately
    2. If no current champion exists, award to warrior with HIGHEST recognition
       - If tie for highest, apply tie-breaker cascade (kills → wins → losses → popularity → name)
    3. If current champion exists but didn't fight this turn:
       - Award to warrior with highest recognition
       - If tie for highest, apply tie-breaker cascade
    4. If current champion fought, they keep the title (unless beaten)

    Tie-Breaker Cascade (Rules 2/3 only when warriors tied at highest recognition):
    1. Most Kills
    2. Most Wins
    3. Fewest Losses
    4. Highest Popularity
    5. Alphabetical by Name (guarantees single result)

    ineligible_name: if set and it matches the sitting champion, the Gladiatorial
    Commission has stripped their title this turn - Rule 4 is skipped entirely
    and they are excluded from the recognition-leader scan (Rules 2/3), so they
    cannot simply re-claim the vacated title on the spot.

    Returns:
        (champion_state_dict, is_new_champion) where is_new_champion is True if the
        current champion name differs from prev_champion_name.
    """
    dead_keys = {(d.get("team_id", 0), d["name"]) for d in deaths_this_turn}
    prev_champ = prev_champion_name or champion_state.get("name", "")
    
    # Build set of warriors who fought this turn (from card)
    warriors_who_fought = set()
    if card:
        for bout in card:
            if not bout:
                continue
            # Get player warrior info (handle both dict and object formats)
            pw = bout.get("player_warrior") if isinstance(bout, dict) else getattr(bout, "player_warrior", None)
            ow = (bout.get("opponent_warrior") or bout.get("opponent")) if isinstance(bout, dict) else (getattr(bout, "opponent_warrior", None) or getattr(bout, "opponent", None))
            pt = bout.get("player_team") if isinstance(bout, dict) else getattr(bout, "player_team", None)
            ot = bout.get("opponent_team") if isinstance(bout, dict) else getattr(bout, "opponent_team", None)
            
            if pw:
                pw_name = pw.name if hasattr(pw, "name") else (pw.get("name", "") if isinstance(pw, dict) else "")
                pt_id = pt.team_id if (pt and hasattr(pt, "team_id")) else (pt.get("team_id", 0) if (pt and isinstance(pt, dict)) else 0)
                if pw_name:
                    warriors_who_fought.add((pt_id, pw_name))

            if ow:
                ow_name = ow.name if hasattr(ow, "name") else (ow.get("name", "") if isinstance(ow, dict) else "")
                ot_id = ot.team_id if (ot and hasattr(ot, "team_id")) else (ot.get("team_id", 0) if (ot and isinstance(ot, dict)) else 0)
                if ow_name:
                    warriors_who_fought.add((ot_id, ow_name))
    
    # RULE 1: A warrior who beat the current champion claims the title immediately.
    if champion_beaten_by:
        new_state = {"name": champion_beaten_by, "warrior_id": champion_beaten_by_wid,
                     "team_name": champion_beaten_team or "Unknown",
                     "team_id": champion_beaten_team_id,
                     "source": "defeated_champion"}
        is_new = (champion_beaten_by != prev_champ)
        print(f"[DEBUG CHAMPION] RULE 1: {champion_beaten_by} defeated champion and claims title")
        return new_state, is_new
    
    current_champ = champion_state.get("name", "")
    current_champ_tid = champion_state.get("team_id", 0)

    # Gladiatorial Commission title-strip override: force the sitting champion
    # out of contention entirely, regardless of their current recognition.
    stripped_by_commission = bool(
        ineligible_name and current_champ and current_champ.lower() == ineligible_name.lower()
    )
    if stripped_by_commission:
        current_champ = ""

    # Check if current champion is dead
    if current_champ and (current_champ_tid, current_champ) in dead_keys:
        current_champ = ""

    # Check if current champion was promoted to an immortal arena this turn.
    # If so, they vacate the title (champions can only hold the crown in normal arena).
    if current_champ and (current_champ_tid, current_champ) not in dead_keys:
        for team in teams:
            tname = team.team_name if hasattr(team,"team_name") else team.get("team_name","")
            if tname in _NPC_TEAM_NAMES: continue
            wlist = team.warriors if hasattr(team,"warriors") else team.get("warriors",[])
            for w in wlist:
                if not w: continue
                wname = w.name if hasattr(w,"name") else w.get("name","")
                w_tid = team.team_id if hasattr(team,"team_id") else team.get("team_id",0)
                if wname == current_champ and w_tid == current_champ_tid:
                    arena = getattr(w,"current_arena","normal") if hasattr(w,"current_arena") else w.get("current_arena","normal")
                    if arena != "normal":
                        print(f"[DEBUG CHAMPION] Champion {current_champ} promoted to {arena} arena - title vacated")
                        current_champ = ""
                    break

    # Check if current champion fought this turn
    champion_fought = False
    if current_champ:
        champion_fought = (current_champ_tid, current_champ) in warriors_who_fought

        # If tuple lookup fails, try fallback: search by name only
        # This handles cases where team_id might be mismatched in the bout object
        if not champion_fought:
            for t_id, w_name in warriors_who_fought:
                if w_name.lower() == current_champ.lower():
                    champion_fought = True
                    print(f"[DEBUG CHAMPION] FALLBACK: Found {current_champ} by name (tuple lookup failed)")
                    print(f"[DEBUG CHAMPION] Tuple had team_id={t_id}, champion has team_id={current_champ_tid}")
                    break

        if not champion_fought:
            print(f"\n[DEBUG CHAMPION] Current champion {current_champ} (tid={current_champ_tid}) NOT found in warriors_who_fought")
            print(f"[DEBUG CHAMPION] warriors_who_fought set contains: {warriors_who_fought}")
        else:
            print(f"\n[DEBUG CHAMPION] Current champion {current_champ} (tid={current_champ_tid}) FOUND in warriors_who_fought")

    # Also check if champion was a winner in any bout (handles peasant/NPC fights)
    champion_won = False
    if current_champ and card and not champion_fought:
        print(f"[DEBUG CHAMPION] Checking if {current_champ} won any bouts...")
        for bout in card:
            if not bout:
                continue
            # Check if champion was the winner
            winner = bout.get("result", {}).get("winner") if isinstance(bout, dict) else getattr(bout, "result", {}).winner if hasattr(bout, "result") else None
            if winner:
                winner_name = winner.name if hasattr(winner, "name") else (winner.get("name") if isinstance(winner, dict) else "")
                if winner_name == current_champ:
                    print(f"[DEBUG CHAMPION] Found {current_champ} as winner in a bout!")
                    champion_won = True
                    champion_fought = True
                    break

    # RULE 4: If champion exists and fought (and won or at least participated), they keep the title
    if current_champ and champion_fought:
        print(f"[DEBUG CHAMPION] RULE 4: Champion {current_champ} fought and retains title")
        # Update the source to indicate retention, not original coronation
        champion_state["source"] = "retained"

        # IMPORTANT: Update the warrior_id to the current value in case it changed
        # This prevents stale warrior_id from blocking newsletter display
        for team in teams:
            wlist = team.warriors if hasattr(team,"warriors") else team.get("warriors",[])
            for w in wlist:
                if not w: continue
                wname = w.name if hasattr(w,"name") else w.get("name","")
                if wname == current_champ:
                    w_tid = team.team_id if hasattr(team,"team_id") else team.get("team_id",0)
                    if w_tid == current_champ_tid:
                        # Found the current champion warrior - update warrior_id
                        current_wid = getattr(w, "warrior_id", None) if hasattr(w, "warrior_id") else w.get("warrior_id") if isinstance(w, dict) else None
                        if current_wid:
                            champion_state["warrior_id"] = current_wid
                            print(f"[DEBUG CHAMPION] Updated warrior_id from {champion_state.get('warrior_id')} to {current_wid}")

        is_new = (current_champ != prev_champ)
        return champion_state, is_new
    elif current_champ:
        print(f"[DEBUG CHAMPION] Champion {current_champ} did NOT fight - will evaluate for replacement")
    
    # RULES 2 & 3: No champion OR champion didn't fight - find warrior with highest recognition
    # Find all eligible warriors
    all_warriors = []
    for team in teams:
        tname = team.team_name if hasattr(team,"team_name") else team.get("team_name","?")
        if tname in _NPC_TEAM_NAMES: continue
        wlist = team.warriors if hasattr(team,"warriors") else team.get("warriors",[])
        for w in wlist:
            if not w: continue
            w_tid = team.team_id if hasattr(team,"team_id") else team.get("team_id", 0)
            if hasattr(w,"name"): wobj=w
            else:
                from warrior import Warrior
                try:    wobj=Warrior.from_dict(w)
                except: continue
            if getattr(wobj,"is_dead",False): continue
            if getattr(wobj,"current_arena","normal") != "normal": continue
            if (w_tid, wobj.name) in dead_keys: continue
            if ineligible_name and wobj.name.lower() == ineligible_name.lower(): continue
            # A warrior who did not fight this turn can never be (or become) champion.
            if card and warriors_who_fought and (w_tid, wobj.name) not in warriors_who_fought:
                continue
            # Champion who didn't fight this turn loses the title and cannot retain
            # it via the recognition scan -- they must defend or give it up.
            if current_champ and not champion_fought:
                if wobj.name.lower() == current_champ.lower() and w_tid == current_champ_tid:
                    print(f"[DEBUG CHAMPION] RULE 3: excluding non-fighting champion "
                          f"{wobj.name} from recognition scan")
                    continue
            all_warriors.append((wobj, tname, w_tid))

    if not all_warriors:
        return {}, False

    # Sort by recognition only
    all_warriors.sort(key=lambda x: (-getattr(x[0],"recognition",0), x[0].name, x[2]))

    # Get the highest recognition score
    best_rec = getattr(all_warriors[0][0], "recognition", 0)

    # Check if there's a tie for highest recognition
    tied = [x for x in all_warriors if getattr(x[0],"recognition",0) == best_rec]

    if len(tied) > 1:
        # MULTIPLE WARRIORS TIED AT HIGHEST RECOGNITION - Apply tie-breaker chain
        print(f"[DEBUG CHAMPION] {len(tied)} warriors tied at recognition {best_rec} - applying tie-breakers")
        result = _apply_tiebreakers(tied)
        if result:
            champ_w, champ_t, champ_tid = result
            new_state = {"name": champ_w.name, "warrior_id": getattr(champ_w, "warrior_id", None),
                         "team_name": champ_t, "team_id": champ_tid, "source": "recognition_tiebreak"}
            is_new = (champ_w.name != prev_champ)
            print(f"[DEBUG CHAMPION] Tie-breaker awarded champion: {champ_w.name} (kills={getattr(champ_w,'kills',0)}, wins={getattr(champ_w,'wins',0)}, losses={getattr(champ_w,'losses',0)})")
            return new_state, is_new
        else:
            # Should never happen with our tie-breaker chain, but handle gracefully
            is_new = (prev_champ != "")
            return {}, is_new

    # NO TIE - Award championship to the warrior with highest recognition
    champ_w, champ_t, champ_tid = tied[0]
    new_state = {"name": champ_w.name, "warrior_id": getattr(champ_w, "warrior_id", None),
                 "team_name": champ_t, "team_id": champ_tid, "source": "recognition"}
    is_new = (champ_w.name != prev_champ)
    if is_new:
        print(f"[DEBUG CHAMPION] New champion {champ_w.name} awarded by recognition")
    return new_state, is_new


def _arena_champion_sort_key(w) -> tuple:
    """Single source of truth for immortal-arena champion ordering.
    Recognition, then kills, wins, fewer losses, popularity, name."""
    return (
        -(getattr(w, "recognition", 0) or 0),
        -(getattr(w, "kills", 0) or 0),
        -(getattr(w, "wins", 0) or 0),
        getattr(w, "losses", 0) or 0,
        -(getattr(w, "popularity", 0) or 0),
        (getattr(w, "name", "") or "").lower(),
    )


def _update_arena_champion(teams: list, arena: str, prev_state: dict = None, card=None) -> tuple:
    """
    Update the champion of an immortal arena (Elite Spire, Soul Spire) using the
    same rules as the regular arena: beaten champion loses the title to the
    victor; a champion who fights and isn't beaten keeps it; otherwise the
    recognition leader wins it (tie-breakers: kills → wins → losses →
    popularity → name).

    Returns: (new_champion_state_dict, is_new_champion)
    """
    # Find all warriors in this arena
    arena_warriors = []
    _seen_names = set()
    for team in teams:
        tname = team.team_name if hasattr(team, "team_name") else team.get("team_name", "?")
        wlist = list(team.warriors if hasattr(team, "warriors") else team.get("warriors", []))
        # Immortal-arena fighters live in archived_warriors (outside the 5-slot cap)
        wlist += list((getattr(team, "archived_warriors", None) if hasattr(team, "archived_warriors")
                       else team.get("archived_warriors", [])) or [])

        for w in wlist:
            if not w:
                continue
            if hasattr(w, "name"):
                wobj = w
            else:
                from warrior import Warrior
                try:
                    wobj = Warrior.from_dict(w)
                except:
                    continue

            # Only warriors in this arena
            if getattr(wobj, "current_arena", "normal") != arena:
                continue
            if getattr(wobj, "is_dead", False):
                continue
            if wobj.name in _seen_names:
                continue
            _seen_names.add(wobj.name)

            tid = team.team_id if hasattr(team, "team_id") else team.get("team_id", 0)
            arena_warriors.append({
                "warrior": wobj,
                "team_id": tid,
                "team_name": tname,
                "recognition": getattr(wobj, "recognition", 0),
                "kills": getattr(wobj, "kills", 0),
                "wins": getattr(wobj, "wins", 0),
                "losses": getattr(wobj, "losses", 0),
                "popularity": getattr(wobj, "popularity", 0),
            })

    if not arena_warriors:
        return {}, False

    def _entry(name):
        return next((a for a in arena_warriors if a["warrior"].name == name), None)

    def _state(entry, source):
        return {
            "name": entry["warrior"].name,
            "warrior_id": getattr(entry["warrior"], "warrior_id", 0),
            "team_id": entry["team_id"],
            "team_name": entry["team_name"],
            "recognition": entry["recognition"],
            "source": source,
        }

    prev_name = (prev_state or {}).get("name", "")
    champ_entry = _entry(prev_name) if prev_name else None

    # Same rules as the regular arena (_update_champion):
    # Rule 1 - a champion beaten in combat hands the title to whoever beat them.
    # Rule 4 - a champion who fought and was not beaten keeps the title.
    # Rules 2/3 - otherwise the recognition leader takes it (non-fighting
    #             champions are excluded; they must defend or give it up).
    champ_fought = False
    for bout in (card or []):
        res = getattr(bout, "result", None)
        if not res:
            continue
        names = (getattr(bout.player_warrior, "name", ""), getattr(bout.opponent, "name", ""))
        if prev_name not in names:
            continue
        champ_fought = True
        winner = getattr(res, "winner", None)
        wname = getattr(winner, "name", "") if winner else ""
        if wname and wname != prev_name:
            beaten_by = _entry(wname)
            if beaten_by:
                return _state(beaten_by, "defeated_champion"), True
    if champ_entry and champ_fought:
        return _state(champ_entry, "retained"), False

    # Only warriors who fought this turn may take the title.
    _fought_names = set()
    for bout in (card or []):
        if not getattr(bout, "result", None):
            continue
        _fought_names.add(getattr(bout.player_warrior, "name", ""))
        _fought_names.add(getattr(bout.opponent, "name", ""))
    _fought_names.discard("")
    _eligible = [a for a in arena_warriors if a["warrior"].name in _fought_names] if _fought_names else arena_warriors
    pool = [a for a in _eligible if a["warrior"].name != prev_name] if prev_name else _eligible
    if not pool:
        pool = _eligible or arena_warriors
    pool.sort(key=lambda x: _arena_champion_sort_key(x["warrior"]))
    leader = pool[0]
    return _state(leader, "recognition"), leader["warrior"].name != prev_name


def _get_warriors(w):
    if hasattr(w,"name"): return w
    from warrior import Warrior
    try:    return Warrior.from_dict(w)
    except: return None


def _is_npc_team(team) -> bool:
    name = team.team_name if hasattr(team,"team_name") else team.get("team_name","")
    return name in _NPC_TEAM_NAMES

def _is_ai_team(team) -> bool:
    """Detect an AI-managed team by its manager_id 'ai_' prefix.

    NOTE: AI managers are intentionally shown in the newsletter (Top Managers,
    etc.) exactly like human players, so this is deliberately NOT used to exclude
    them any more. Retained only as an accurate helper. The old team_id>=9000
    heuristic is obsolete -- AI teams now use real, player-like team IDs."""
    mid = getattr(team, "manager_id", None)
    if mid is None and isinstance(team, dict):
        mid = team.get("manager_id")
    if mid and str(mid).startswith("ai_"):
        return True
    tid = getattr(team, "team_id", None)
    if tid is None and isinstance(team, dict):
        tid = team.get("team_id")
    return tid is not None and tid >= 9000


def _fmt_date() -> str:
    return datetime.date.today().strftime("%m/%d/%Y")


# ---------------------------------------------------------------------------
# HEADER
# ---------------------------------------------------------------------------

def _header(turn_num: int, processed_date: str = None) -> str:
    # No "\n" between the title and subtitle spans: both render as CSS
    # display:block on the client, which already forces its own line break -
    # adding a literal newline too would double the gap between them.
    return (f"Date: {processed_date or _fmt_date()}\n"
            f"{HDR_TITLE}{ARENA_NAME.upper()} ({ARENA_ID}){HDR_RESET}"
            f"{HDR_SUBTITLE}Turn - {turn_num}{HDR_RESET}")


# ---------------------------------------------------------------------------
# TEAM STANDINGS
# ---------------------------------------------------------------------------

def _team_career_record(team) -> tuple:
    """
    Return cumulative (wins, losses, kills) for ALL warriors who have ever
    fought for this team: active warriors + dead-awaiting-replacement +
    archived (confirmed-replaced) warriors. Deduplicated by warrior_id to avoid
    counting the same warrior multiple times.
    """
    tw = tl = tk = 0
    tname = team.team_name if hasattr(team, "team_name") else team.get("team_name", "?")
    seen_warrior_ids = set()

    # Active + dead-awaiting-replacement - still in the warriors list
    wlist = team.warriors if hasattr(team,"warriors") else team.get("warriors",[])
    for w in wlist:
        if not w: continue
        wid = getattr(w,"warrior_id",None) if hasattr(w,"warrior_id") else w.get("warrior_id",None)
        if wid: seen_warrior_ids.add(wid)
        tw += getattr(w,"wins",0)   if hasattr(w,"wins")   else w.get("wins",0)
        tl += getattr(w,"losses",0) if hasattr(w,"losses") else w.get("losses",0)
        tk += getattr(w,"kills",0)  if hasattr(w,"kills")  else w.get("kills",0)
    active_tw, active_tl, active_tk = tw, tl, tk

    # Archived warriors (replaced after death / retirement)
    # Deduplicate by warrior_id to avoid counting same warrior multiple times
    archived = (getattr(team,"archived_warriors",[])
                if hasattr(team,"archived_warriors")
                else team.get("archived_warriors",[]))
    archived_count = 0
    for aw in archived:
        if not aw: continue
        wid = aw.get("warrior_id",None) if isinstance(aw,dict) else getattr(aw,"warrior_id",None)
        # Skip if we've already counted this warrior (in active or previously in archived)
        if wid and wid in seen_warrior_ids:
            continue
        if wid:
            seen_warrior_ids.add(wid)
            archived_count += 1
        tw += aw.get("wins",0)   if isinstance(aw,dict) else getattr(aw,"wins",0)
        tl += aw.get("losses",0) if isinstance(aw,dict) else getattr(aw,"losses",0)
        tk += aw.get("kills",0)  if isinstance(aw,dict) else getattr(aw,"kills",0)
    print(f"  [career_record] {tname}: active={active_tw}-{active_tl}-{active_tk} "
          f"archived={archived_count} total={tw}-{tl}-{tk}")
    return tw, tl, tk


_NL_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_TEAM_RECORDS_FILE = os.path.join(_NL_BASE_DIR, "team_records.json")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# "<pos> <name> (<manager>) (<team id>)  W  L  K  pct%" - the career half of a standings row
_CAREER_ROW_RE = re.compile(
    r"^\s*\d+\s+.*?\((-?\d+)\)\s+(\d+)\s+(\d+)\s+(\d+)\s+\d+(?:\.\d+)?%")


def _team_careers_from_newsletter(turn: int) -> dict:
    """Parse {team_id: (w, l, k)} from a published newsletter's CAREER STANDINGS block."""
    path = os.path.join(_NL_BASE_DIR, "saves", "league", f"turn_{turn:04d}", "newsletter.txt")
    if not os.path.exists(path):
        return {}
    out = {}
    in_block = False
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = _ANSI_RE.sub("", raw.rstrip("\n"))
            if not in_block:
                in_block = "CAREER STANDINGS" in line
                continue
            if line.startswith("(-) denotes"):
                break
            m = _CAREER_ROW_RE.match(line)
            if m:
                out.setdefault(int(m.group(1)), (int(m.group(2)), int(m.group(3)), int(m.group(4))))
    return out


_MGR_STATS_RE = re.compile(r"(\d+)\s+(\d+)\s+(\d+)\s+-?\d+(?:\.\d+)?%\s+(\d+)")


def _manager_careers_from_newsletter(turn: int) -> dict:
    """Parse {manager_name: (cw, cl, ck)} from a newsletter's 'Top Managers Career' column."""
    path = os.path.join(_NL_BASE_DIR, "saves", "league", f"turn_{turn:04d}", "newsletter.txt")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = [_ANSI_RE.sub("", l.rstrip("\n")) for l in f]
    start = next((i for i, l in enumerate(lines) if "The Top Managers Career" in l), None)
    if start is None:
        return {}
    out = {}
    for line in lines[start + 1:]:
        if line.startswith("=") or "MANAGER" in line:
            if out:
                break
            continue
        if not line.strip():
            break
        stats = list(_MGR_STATS_RE.finditer(line))
        if len(stats) < 2:
            continue
        name = line[stats[0].end():stats[1].start()].strip()
        cw, cl, ck = (int(stats[1].group(i)) for i in (1, 2, 3))
        if name:
            out.setdefault(name, (cw, cl, ck))
    return out


def _previous_manager_careers(turn_num: int, names: set) -> dict:
    """
    Most recent published career record for each manager before turn_num, as
    {name: (cw, cl, ck)}. The newsletter is the source of truth (it may be
    hand-corrected); manager_records.json fills in turns/managers it lacks.
    """
    found = {}
    saved = {}
    path = os.path.join(_NL_BASE_DIR, "manager_records.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception as e:
            print(f"  WARNING: could not read manager_records.json: {e}")
    for t in range(turn_num - 1, 0, -1):
        if len(found) == len(names):
            break
        from_nl = _manager_careers_from_newsletter(t)
        from_json = saved.get(str(t), {})
        for n in names:
            if n in found:
                continue
            if n in from_nl:
                found[n] = from_nl[n]
            elif n in from_json:
                r = from_json[n]
                found[n] = (r.get("cw", 0), r.get("cl", 0), r.get("ck", 0))
    return found


def _load_team_records() -> dict:
    if not os.path.exists(_TEAM_RECORDS_FILE):
        return {}
    try:
        with open(_TEAM_RECORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  WARNING: could not read team_records.json: {e}")
        return {}


def _previous_team_careers(turn_num: int, team_ids: set) -> dict:
    """
    Most recent published career record for each team before turn_num, as
    {team_id: (w, l, k)}. The newsletter is the source of truth (records may be
    hand-corrected there); team_records.json is the fallback for a turn whose
    newsletter is missing or doesn't list the team.
    """
    found = {}
    saved = _load_team_records()
    for t in range(turn_num - 1, 0, -1):
        if len(found) == len(team_ids):
            break
        from_nl = _team_careers_from_newsletter(t)
        from_json = saved.get(str(t), {})
        for tid in team_ids:
            if tid in found:
                continue
            if tid in from_nl:
                found[tid] = from_nl[tid]
            elif str(tid) in from_json:
                r = from_json[str(tid)]
                found[tid] = (r.get("cw", 0), r.get("cl", 0), r.get("ck", 0))
    return found


def _save_team_records(turn_num: int, rows: list):
    records = _load_team_records()
    turn_recs = records.setdefault(str(turn_num), {})
    for r in rows:
        turn_recs[str(r["id"])] = {"team_name": r["name"], "manager": r["mgr"],
                                   "cw": r["w"], "cl": r["l"], "ck": r["k"],
                                   "w": r["tw"], "l": r["tl"], "k": r["tk"]}
    try:
        with open(_TEAM_RECORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
    except Exception as e:
        print(f"  ERROR saving team_records.json: {e}")


def _team_standings(teams, turn_num: int, card: list = None) -> str:
    # ANSI styling codes for "Blood Red" and Bold
    B_RED = "\033[1;31m"
    RESET = "\033[0m"

    # Identify teams that participated in this turn from the card
    teams_that_fought = set()
    if card:
        for bout in card:
            # Handle both dict and object formats
            bout_result = bout.get("result") if isinstance(bout, dict) else getattr(bout, "result", None)
            if not bout_result: continue

            # Get teams - handle both formats
            if isinstance(bout, dict):
                pt = bout.get("player_team", {})
                ot = bout.get("opponent_team", {})
            else:
                pt = getattr(bout, "player_team", {})
                ot = getattr(bout, "opponent_team", {})

            # Get team name - handle all types
            if isinstance(pt, dict):
                ptname = pt.get("team_name", "?")
            elif isinstance(pt, str):
                ptname = pt
            else:
                ptname = getattr(pt, "team_name", "?")

            if isinstance(ot, dict):
                otname = ot.get("team_name", "?")
            elif isinstance(ot, str):
                otname = ot
            else:
                otname = getattr(ot, "team_name", "?")
            if ptname not in _NPC_TEAM_NAMES: teams_that_fought.add(ptname)
            if otname not in _NPC_TEAM_NAMES: teams_that_fought.add(otname)

    rows = []
    # Track which (manager, team_name) pairs we've seen to skip replaced teams
    team_key_seen = {}

    _ids = set()
    for team in teams:
        if _is_npc_team(team): continue
        try:
            _ids.add(int(team.team_id if hasattr(team, "team_id") else team.get("team_id", 0)))
        except (TypeError, ValueError):
            pass
    prev_careers = _previous_team_careers(turn_num, _ids)

    for team in teams:
        if _is_npc_team(team): continue
        name = team.team_name if hasattr(team,"team_name") else team.get("team_name","?")
        tid  = team.team_id   if hasattr(team,"team_id")   else team.get("team_id",0)
        mgr  = team.manager_name if hasattr(team,"manager_name") else team.get("manager_name","?")

        # Skip replaced teams: if we've already seen this (manager, team_name) pair,
        # skip the older/less-active version (keep the one with more recent turn_history)
        team_key = (mgr, name)
        if team_key in team_key_seen:
            prev_team, prev_last_turn = team_key_seen[team_key]
            hist = getattr(team,"turn_history",[]) if hasattr(team,"turn_history") else team.get("turn_history",[])
            curr_last_turn = max((entry.get("turn", 0) for entry in hist), default=0) if hist else 0
            if curr_last_turn <= prev_last_turn:
                # Current team is older or same age, skip it
                continue
            else:
                # Current team is newer, keep it and skip the previous one
                # (but we've already added the previous one to rows, so we need to remove it)
                rows = [r for r in rows if not (r["mgr"] == mgr and r["name"] == name)]

        hist = getattr(team,"turn_history",[]) if hasattr(team,"turn_history") else team.get("turn_history",[])
        last_turn = max((entry.get("turn", 0) for entry in hist), default=0) if hist else 0
        team_key_seen[team_key] = (team, last_turn)
        # Career = last published career record + this turn. Only a team with no
        # prior record anywhere falls back to summing its warriors.
        this_turn = next((h for h in reversed(hist) if h.get("turn") == turn_num), {})
        ttw, ttl, ttk = this_turn.get("w", 0), this_turn.get("l", 0), this_turn.get("k", 0)
        prev = prev_careers.get(int(tid)) if str(tid).lstrip("-").isdigit() else None
        if prev is not None:
            tw, tl, tk = prev[0] + ttw, prev[1] + ttl, prev[2] + ttk
        else:
            tw, tl, tk = _team_career_record(team)
        tf=tw+tl; pct=(tw/tf*100) if tf else 0.0
        last5=hist[-5:] if hist else []
        l5w=sum(h.get("w",0) for h in last5)
        l5l=sum(h.get("l",0) for h in last5)
        l5k=sum(h.get("k",0) for h in last5)
        l5tf=l5w+l5l; l5pct=(l5w/l5tf*100) if l5tf else 0.0
        # Mark teams that didn't fight this turn with a "-" prefix (but keep them visible)
        display_name = name if name in teams_that_fought else f"- {name}"
        rows.append({"name":name,"display_name":display_name,"id":tid,"mgr":mgr,"w":tw,"l":tl,"k":tk,"pct":pct,
                     "tw":ttw,"tl":ttl,"tk":ttk,
                     "l5w":l5w,"l5l":l5l,"l5k":l5k,"l5pct":l5pct,"fought":name in teams_that_fought})
    
    _save_team_records(turn_num, rows)
    rows.sort(key=lambda r:(-r["pct"],-(r["w"])))
    # Sort Last 5 by Win % then Kills
    rows_l5=sorted(rows,key=lambda r:(-r["l5pct"], -r["l5k"]))

    # Layout: 79 visible chars per section + 3 char separator = 161 total visible.
    # ANSI codes in name strings add 11 raw chars (invisible), so name field is 66 raw / 55 visible.
    SEP = "="*161
    # Title row: "The Top Teams" left, section labels centered over their columns
    left_title  = f"{HDR_BOLD}{'The Top Teams':<15}{HDR_RESET}{'CAREER STANDINGS':^64}"  # 79 chars
    right_title = f"{'LAST 5 TURNS':^79}"                            # 79 chars
    TITLE_ROW   = left_title + "   " + right_title
    # Column header row: name area = 55 visible chars (Team Name left, (MANAGER)(TEAM #) right)
    NAME_HDR = f"{'Team Name':<37}{'(MANAGER) (TEAM #)':>18}"  # 37+18 = 55 chars
    HDR = (f"{'POS':<5}{NAME_HDR}{'W':>4}{'L':>4}{'K':>4}{'%':>7}"
           f"   {'POS':<5}{NAME_HDR}{'W':>4}{'L':>4}{'K':>4}{'%':>7}")
    lines=[f"\n{TITLE_ROW}\n", HDR, SEP]
    
    for i,(r,r5) in enumerate(zip(rows,rows_l5),1):
        # Construct styled name strings with display_name (includes "-" prefix if inactive)
        # Format: Team Name (Manager) (ID) or - Team Name (Manager) (ID)
        cname  = f" {_trunc(r['display_name'])} ({B_RED}{_trunc(r['mgr'])}{RESET}) ({r['id']})"
        c5name = f" {_trunc(r5['display_name'])} ({B_RED}{_trunc(r5['mgr'])}{RESET}) ({r5['id']})"

        # Pad manually to 55 visible chars (ANSI codes are 11 chars total)
        cname_str  = f"{cname:<66}"
        c5name_str = f"{c5name:<66}"

        career = f"{i:<5}{cname_str}{r['w']:>4}{r['l']:>4}{r['k']:>4}{r['pct']:>6.1f}%"
        last5s = f"   {i:<5}{c5name_str}{r5['l5w']:>4}{r5['l5l']:>4}{r5['l5k']:>4}{r5['l5pct']:>6.1f}%"
        lines.append(career + last5s)
    lines.append("\n(-) denotes a team that did not fight this turn")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# WARRIOR TIERS
# ---------------------------------------------------------------------------

def _warrior_tiers(teams, champion_state: dict, card: list = None, turn_num: int = 0) -> str:
    champ_name = champion_state.get("name","")
    champ_tid  = champion_state.get("team_id", 0)
    champ_wid  = champion_state.get("warrior_id")

    print(f"\n[DEBUG TIERS] _warrior_tiers called with champion_state: {champion_state}")
    print(f"[DEBUG TIERS] Looking for: champ_name={champ_name}, champ_tid={champ_tid}, champ_wid={champ_wid}")

    # Identify warriors that participated in this turn from the card
    warriors_that_fought = set()
    if card:
        for bout in card:
            if not bout.result: continue
            pw = bout.player_warrior
            ow = bout.opponent
            pt = bout.player_team
            ot = bout.opponent_team
            ptid = pt.team_id if hasattr(pt, "team_id") else pt.get("team_id", 0)
            otid = ot.team_id if hasattr(ot, "team_id") else ot.get("team_id", 0)
            warriors_that_fought.add((ptid, pw.name))
            warriors_that_fought.add((otid, ow.name))

    tiers={t:[] for t in [TIER_CHAMPION,TIER_ELITES,TIER_EXPERTS,TIER_VETERANS,TIER_ADEPTS,
                           TIER_INITIATES,TIER_ROOKIES,TIER_RECRUITS]}
    for team in teams:
        if _is_npc_team(team): continue

        # Requirement: Remove team from newsletter after 3 turns of inactivity
        # But keep teams visible until that point with a "-" prefix
        last_run = getattr(team, "last_turn_ran", 0)
        if turn_num > 0 and last_run > 0 and (turn_num - last_run) > 3:
            continue

        tname=team.team_name if hasattr(team,"team_name") else team.get("team_name","?")
        tid  =team.team_id   if hasattr(team,"team_id")   else team.get("team_id",0)
        wlist=team.warriors  if hasattr(team,"warriors")  else team.get("warriors",[])
        for wobj in wlist:
            if not wobj: continue
            if getattr(wobj,"is_dead",False): continue
            if getattr(wobj,"current_arena","normal") != "normal": continue
            rname=wobj.race.name if hasattr(wobj.race,"name") else "Human"
            if rname in _NPC_RACES: continue
            # Don't show replacement warriors until they've competed at least once
            if getattr(wobj,"total_fights",0) == 0: continue

            w_wid = getattr(wobj, "warrior_id", None)
            if champ_wid and w_wid:
                is_champ = (champ_wid == w_wid)
                if is_champ:
                    print(f"[DEBUG TIERS] FOUND CHAMPION: {wobj.name} by warrior_id match ({champ_wid})")
            else:
                is_champ = (wobj.name == champ_name and tid == champ_tid)
                if is_champ:
                    print(f"[DEBUG TIERS] FOUND CHAMPION: {wobj.name} by name+team_id match")
            tier = _warrior_tier(wobj, is_champ)
            # Mark warriors that didn't fight this turn with a "-" prefix (but keep them visible)
            warrior_display_name = wobj.name if (tid, wobj.name) in warriors_that_fought else f"- {wobj.name}"
            # Use champion's team from champion_state, not from roster
            display_tname = champion_state.get("team_name", tname) if is_champ else tname
            display_tid = champion_state.get("team_id", tid) if is_champ else tid
            tiers[tier].append({"name":wobj.name,"display_name":warrior_display_name,"team":display_tname,"tid":display_tid,
                "w":wobj.wins,"l":wobj.losses,"k":wobj.kills,
                "rec":getattr(wobj,"recognition",0),"fought":(tid,wobj.name) in warriors_that_fought
            })
    SEP = "="*80
    # Fixed columns: name(30) + W(4) + L(4) + K(4) + Rec(4) + team
    COL_HDR = f"{'NAME':<30}{'W':>4}{'L':>4}{'K':>4}  {'REC':>3}  TEAM"
    sections=[]
    for tier in [TIER_CHAMPION,TIER_ELITES,TIER_EXPERTS,TIER_VETERANS,TIER_ADEPTS,TIER_INITIATES,TIER_ROOKIES,TIER_RECRUITS]:
        wlist=tiers[tier]
        if not wlist and tier==TIER_CHAMPION:
            print(f"[DEBUG TIERS] CHAMPION tier is empty! champion_state was: {champion_state}")
            sections.append(f"\n{HDR_RED_LG}{tier}{HDR_RESET}\n{COL_HDR}\n{SEP}\n  (vacant this turn)"); continue
        if not wlist: continue
        wlist.sort(key=lambda x:(-x["rec"],-(x["w"]/max(1,x["w"]+x["l"]))))
        lines=[f"\n{HDR_RED_LG}{tier}{HDR_RESET}\n{COL_HDR}",SEP]
        for wd in wlist:
            tm=f"{_trunc(wd['team'])} ({wd['tid']})"
            display_name = wd.get('display_name', wd['name'])
            lines.append(f"{_trunc(display_name):<30}{wd['w']:>4}{wd['l']:>4}{wd['k']:>4}"
                         f"  {wd['rec']:>3}  {tm}")
        sections.append("\n".join(lines))
    sections.append("\n(-) denotes a warrior that did not fight this turn")
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# DEAD / FIGHTS / RACE REPORT
# ---------------------------------------------------------------------------

def _dead_section(deaths: list, turn_num: int) -> str:
    if not deaths: return ""
    sep="="*109
    lines=[f"\n{HDR_RED_LG}THE DEAD{HDR_RESET}",
           f"{'NAME':<30}{'W':>4}{'L':>4}{'K':>4}  {'TEAM':<30}{'SLAIN BY':<30}{'TURN':>5}",sep]
    for d in deaths:
        name = _trunc(d['name'])
        team = _trunc(d.get('team','?'))
        slain = _trunc(d.get('killed_by','?'))
        lines.append(f"{name:<30}{d.get('w',0):>4}{d.get('l',0):>4}{d.get('k',0):>4}"
                     f"  {team:<30}{slain:<30}{turn_num:>5}")
    return "\n".join(lines)


def _promotions_section(promotions: list) -> str:
    if not promotions: return ""
    sep = "=" * 138
    _disp = {"elite": "The Elite Spire", "veteran": "THE SOUL SPIRE"}
    lines = [f"\n{HDR_RED_LG}ASCENDED TO ELITE SPIRE{HDR_RESET}",
             f"{'NAME':<30}{'RECORD':<16}{'TEAM':<28}   {'MANAGER':<25}{'DESTINATION':<20}", sep]
    for p in promotions:
        record = p.get('record','')
        # Format record as "W - L - K" with right-aligned numbers
        if 'W' in record and 'L' in record and 'K' in record:
            # Extract just the numbers: "21W/11L/4K" -> "21 -  11 -  4" (right-aligned)
            import re
            matches = re.findall(r'(\d+)', record)
            if len(matches) >= 3:
                record = f"{int(matches[0]):>2} - {int(matches[1]):>2} - {int(matches[2]):>2}"
        lines.append(
            f"{_trunc(p.get('warrior_name','?')):<30}"
            f"{record:<16}"
            f"{_trunc(p.get('team_name','?')):<28}"
            f"   {_trunc(p.get('manager_name','?')):<25}"
            f"{_disp.get(p.get('to_arena',''),'The Elite Spire'):<20}"
        )
    return "\n".join(lines)


def _promotion_pending_section(pending: list) -> str:
    if not pending: return ""
    sep = "=" * 138
    lines = [f"\n{HDR_RED_LG}WARRIORS SUMMONED TO IMMORTALITY{HDR_RESET}",
             f"{'NAME':<30}{'RECORD':<16}{'TEAM':<28}   {'MANAGER':<25}{'STATUS':<20}", sep]
    for p in pending:
        name = p.get("name", p.get("warrior_name", "?"))
        team = p.get("team", p.get("team_name", "?"))
        manager = p.get("manager", "?")
        record = p.get('record','')
        # Format record as "W - L - K" with right-aligned numbers
        if 'W' in record and 'L' in record and 'K' in record:
            # Extract just the numbers: "21W/11L/4K" -> "21 -  11 -  4" (right-aligned)
            import re
            matches = re.findall(r'(\d+)', record)
            if len(matches) >= 3:
                record = f"{int(matches[0]):>2} - {int(matches[1]):>2} - {int(matches[2]):>2}"
        lines.append(
            f"{_trunc(name):<30}"
            f"{record:<16}"
            f"{_trunc(team):<28}"
            f"   {_trunc(manager):<25}"
            f"{'Ascending':<20}"
        )
    lines.append(sep)
    lines.append("These warriors have earned their place in THE ELITE SPIRE. They will fight one")
    lines.append("final bout under the immortality shield before ascending, as they cannot be")
    lines.append("permanently slain before their ascension.")
    return "\n".join(lines)


def _transcendence_section(transcendences: list) -> str:
    if not transcendences: return ""
    sep = "=" * 138
    lines = [f"\n{HDR_RED_LG}SOULS SUMMONED TO THE SOUL SPIRE{HDR_RESET}",
             f"{'NAME':<30}{'RECORD':<16}{'TEAM':<28}   {'MANAGER':<25}{'WIN RATE':>10}", sep]
    for t in transcendences:
        record = t.get('record','')
        # Format record as "W - L - K" with right-aligned numbers
        if 'W' in record and 'L' in record and 'K' in record:
            # Extract just the numbers: "21W/11L/4K" -> "21 -  11 -  4" (right-aligned)
            import re
            matches = re.findall(r'(\d+)', record)
            if len(matches) >= 3:
                record = f"{int(matches[0]):>2} - {int(matches[1]):>2} - {int(matches[2]):>2}"
        wr_str = f"{t.get('win_rate', 0) * 100:.1f}%"
        lines.append(
            f"{_trunc(t.get('warrior_name','?')):<30}"
            f"{record:<16}"
            f"{_trunc(t.get('team_name','?')):<28}"
            f"   {_trunc(t.get('manager_name','?')):<25}"
            f"{wr_str:>10}"
        )
    return "\n".join(lines)


def _retired_section(retirements: list) -> str:
    if not retirements: return ""
    sep="="*109
    lines=["\nRETIRED THIS TURN",
           f"{'NAME':<30}{'W':>4}{'L':>4}{'K':>4}  {'TEAM':<30}{'MANAGER':<30}",sep]
    for r in retirements:
        name = _trunc(r['name'])
        team = _trunc(r.get('team','?'))
        mgr = _trunc(r.get('manager','?'))
        lines.append(f"{name:<30}{r.get('w',0):>4}{r.get('l',0):>4}{r.get('k',0):>4}"
                     f"  {team:<30}{mgr:<30}")
    return "\n".join(lines)


def _fights_section(card, champion_state: Optional[dict] = None,
                   prev_champion_state: Optional[dict] = None) -> str:
    sep="="*85
    lines=[f"\n{HDR_RED_LG}LAST TURN'S FIGHTS{HDR_RESET}",sep]

    # Fight lines are grouped into these sub-sections and emitted with headers below.
    categorized = {"monster": [], "champion": [], "blood_challenge": [], "challenge": [], "standard": [], "peasant": []}

    champ_name = (champion_state or {}).get("name", "")
    champ_tid  = (champion_state or {}).get("team_id", 0)
    champ_wid  = (champion_state or {}).get("warrior_id")

    def _get_attr(obj, attr, default=None):
        """Safely get attribute from dict or object"""
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    def _is_champion_warrior(warrior_obj, team_obj) -> bool:
        if not champ_name:
            return False
        wid = _get_attr(warrior_obj, "warrior_id")
        if champ_wid and wid and champ_wid == wid:
            return True
        # Fallback for warriors or champion states that predate warrior_id
        tid = _get_attr(team_obj, "team_id", 0)
        wname = _get_attr(warrior_obj, "name", "")
        return wname == champ_name and tid == champ_tid

    def _effective_type(bout):
        ft = _get_attr(bout, "fight_type", "standard")
        if ft == "monster":
            return "monster"
        pw = _get_attr(bout, "player_warrior")
        ow = _get_attr(bout, "opponent")
        pt = _get_attr(bout, "player_team")
        ot = _get_attr(bout, "opponent_team")
        if (pw and _is_champion_warrior(pw, pt)) or (ow and _is_champion_warrior(ow, ot)):
            return "champion"
        if ft == "blood_challenge":
            return "blood_challenge"
        if ft == "challenge":
            return "challenge"
        if ft == "peasant":
            return "peasant"
        return "standard"

    # Sort order: monster → champion → blood_challenge → challenge → standard/PvP → peasant
    _order = {"monster": 0, "champion": 1, "blood_challenge": 2,
              "challenge": 3, "standard": 4, "peasant": 5}
    sorted_card = sorted(card, key=lambda b: _order.get(_effective_type(b), 4))

    seen_pairs = set()
    seen_fights = set()
    for bout in sorted_card:
        bout_result = _get_attr(bout, "result")
        if not bout_result:
            continue
        pw = _get_attr(bout, "player_warrior")
        ow = _get_attr(bout, "opponent")
        r = bout_result
        # Use warrior_id when available so same-name fighters on different teams dedup correctly
        pw_key = _get_attr(pw, "warrior_id") or _get_attr(pw, "name")
        ow_key = _get_attr(ow, "warrior_id") or _get_attr(ow, "name")
        pair = frozenset([pw_key, ow_key])
        if pair in seen_pairs:
            continue
        if id(bout) in seen_fights:
            continue
        seen_pairs.add(pair)
        seen_fights.add(id(bout))

        eff_type = _effective_type(bout)
        r_winner = _get_attr(r, "winner")
        pw_won = r_winner and _get_attr(r_winner, "name") == _get_attr(pw, "name")
        winner = pw if pw_won else ow
        loser  = ow if pw_won else pw
        mins   = _get_attr(r, "minutes_elapsed", 0)
        wname  = _trunc(_get_attr(winner, "name", "Unknown"))
        lname  = _trunc(_get_attr(loser, "name", "Unknown"))
        style  = _fight_style_word(mins)

        # Get original fight type for proper descriptors
        ft = _get_attr(bout, "fight_type", "standard")

        if eff_type == "champion":
            # Title fight - determine fight type descriptor
            if ft == "challenge":
                fight_descriptor = "Challenge Title fight"
            elif ft == "blood_challenge":
                fight_descriptor = "Blood Challenge Title bout"
            elif ft == "monster":
                fight_descriptor = "Monster Title fight"
            else:  # standard random matchup
                fight_descriptor = "Title fight"

            # Determine if loser WAS the champion before the fight
            loser_team = _get_attr(bout, "opponent_team") if pw_won else _get_attr(bout, "player_team")
            loser_wid = _get_attr(loser, "warrior_id")
            loser_was_champ = (
                (champ_wid and loser_wid and champ_wid == loser_wid) or
                (not champ_wid and _get_attr(loser, "name") == champ_name and _get_attr(loser_team, "team_id", 0) == champ_tid)
            )

            if _get_attr(r, "loser_died"):
                # Check if winner was already champion before this fight
                winner_wid = _get_attr(winner, "warrior_id")
                prev_champ_name = prev_champion_state.get("name", "") if prev_champion_state else ""
                prev_champ_wid = prev_champion_state.get("warrior_id") if prev_champion_state else None
                winner_was_prev_champ = (
                    (prev_champ_wid and winner_wid and prev_champ_wid == winner_wid) or
                    (not prev_champ_wid and prev_champ_name and _get_attr(winner, "name") == prev_champ_name)
                )

                if winner_was_prev_champ:
                    # Champion retained title by killing opponent
                    line = (f"★ CHAMPION'S TITLE FIGHT ★  {wname} has slain {lname} to retain the"
                            f" Champion's Title in a {mins} minute {style} {fight_descriptor}!")
                else:
                    # New champion claimed title by killing opponent
                    line = (f"★ CHAMPION'S TITLE FIGHT ★  {wname} has slain {lname} to claim the"
                            f" Champion's Title in a {mins} minute {style} {fight_descriptor}!")
            elif loser_was_champ:
                # Loser was the champion, so winner TOOK the title
                verb = random.choice(["seized the championship from", "dethroned",
                                      "claimed the title from", "unseated champion"])
                line = (f"★ CHAMPION'S TITLE FIGHT ★  {wname} {verb} {lname}"
                        f" in a {mins} minute {style} {fight_descriptor}!")
            else:
                # Check if winner is the newly-crowned champion (via recognition, not by defeating the previous champion)
                winner_wid = _get_attr(winner, "warrior_id")
                winner_is_current_champ = (
                    (champ_wid and winner_wid and champ_wid == winner_wid) or
                    (not champ_wid and champ_name and _get_attr(winner, "name") == champ_name)
                )

                # Check if winner was NOT the champion at the start of the turn
                prev_champ_name = prev_champion_state.get("name", "") if prev_champion_state else ""
                prev_champ_wid = prev_champion_state.get("warrior_id") if prev_champion_state else None
                winner_was_prev_champ = (
                    (prev_champ_wid and winner_wid and prev_champ_wid == winner_wid) or
                    (not prev_champ_wid and prev_champ_name and _get_attr(winner, "name") == prev_champ_name)
                )

                if winner_is_current_champ and not winner_was_prev_champ:
                    # Winner just became champion via recognition - they're claiming their first title
                    verb = random.choice(["claimed the title against", "took the championship from"])
                    line = (f"★ CHAMPION'S TITLE FIGHT ★  {wname} {verb} {lname}"
                            f" in a {mins} minute {style} {fight_descriptor}!")
                else:
                    # Winner was already champion, so they DEFENDED the title.
                    # "turned back the challenge of" only when it really was a challenge.
                    _defend_verbs = ["defended the title against", "retained the championship over",
                                     "proved superior to"]
                    if ft in ("challenge", "blood_challenge"):
                        _defend_verbs.append("turned back the challenge of")
                    verb = random.choice(_defend_verbs)
                    line = (f"★ CHAMPION'S TITLE FIGHT ★  {wname} {verb} {lname}"
                            f" in a {mins} minute {style} {fight_descriptor}.")
        else:
            # Non-champion fights - determine fight descriptor
            if ft == "challenge":
                fight_descriptor = "Challenge fight"
            elif ft == "blood_challenge":
                fight_descriptor = "Blood Challenge bout"
            elif ft == "monster":
                fight_descriptor = "Monster fight"
            else:  # standard random matchup or peasant
                fight_descriptor = "fight"

            if r.loser_died:
                verb = _death_verb(mins, r.winner_hp_pct)
                line = f"{wname} {verb} {lname} in a {mins} minute {style} {fight_descriptor}."
            else:
                verb = _fight_outcome_verb(mins, r.winner_hp_pct)
                line = f"{wname} {verb} {lname} in a {mins} minute {style} {fight_descriptor}."

        if eff_type == "champion":
            category = "champion"
        elif eff_type == "blood_challenge":
            category = "blood_challenge"
        elif eff_type == "challenge":
            category = "challenge"
        elif eff_type == "peasant":
            category = "peasant"
        elif eff_type == "monster":
            category = "monster"
        else:
            category = "standard"

        if category == "standard":
            # Store (sort_key, line) so we can rank by highest warrior recognition
            rec_w = _get_attr(winner, "recognition", 0) or 0
            rec_l = _get_attr(loser,  "recognition", 0) or 0
            categorized["standard"].append((max(rec_w, rec_l), line))
        else:
            categorized[category].append(line)

    section_labels = [
        ("monster", "MONSTER FIGHTS"),
        ("champion", "CHAMPION FIGHT"),
        ("blood_challenge", "BLOOD CHALLENGE FIGHTS"),
        ("challenge", "CHALLENGE FIGHTS"),
        ("standard", "RANDOM MATCHUPS"),
        ("peasant", "PEASANT FIGHTS"),
    ]
    first_subsection = True
    for key, label in section_labels:
        entries = categorized[key]
        if not entries:
            continue
        if not first_subsection:
            lines.append("")
        first_subsection = False
        lines.append(f"{HDR_RED}{label}{HDR_RESET}")
        lines.append(sep)
        if key == "standard":
            # Highest-recognition warrior in each fight rises to the top
            lines.extend(ln for _, ln in sorted(entries, key=lambda t: t[0], reverse=True))
        else:
            lines.extend(entries)
    return "\n".join(lines)


def _monster_kills_section(card) -> str:
    """Generate a special section for warriors who slew monsters and ascended."""
    monster_slayers = []
    
    for bout in card:
        if not bout.result:
            continue
        # Check if this was a monster fight where the player warrior won and killed
        if (bout.fight_type == "monster" and 
            bout.result.loser_died and 
            bout.result.winner and 
            bout.result.winner.name == bout.player_warrior.name):
            monster_slayers.append({
                "warrior": bout.player_warrior.name,
                "team": bout.player_team.team_name,
                "monster": bout.opponent.name,
                "minutes": bout.result.minutes_elapsed,
            })
    
    if not monster_slayers:
        return ""

    lines = [f"\n{HDR_RED_LG}ASCENSION TO MONSTERDOM{HDR_RESET}"]
    
    slayer_messages = [
        "has transcended mortality and become one of The Monsters themselves!",
        "has proven their worth and earned a place among the supernatural denizens of the Arena!",
        "has shed their humanity and ascended to a new form of existence as a Monster!",
        "has defeated their ultimate opponent and claimed a new life among the creatures of darkness!",
        "has undergone a miraculous transformation, joining the ranks of The Monsters eternal!",
    ]
    
    for slayer in monster_slayers:
        if slayer["minutes"] == 1:
            time_str = "in a swift 1-minute clash"
        elif slayer["minutes"] <= 3:
            time_str = f"in just {slayer['minutes']} minutes"
        elif slayer["minutes"] >= 8:
            time_str = f"in a grueling {slayer['minutes']}-minute battle"
        else:
            time_str = f"in a {slayer['minutes']}-minute encounter"
        
        message = random.choice(slayer_messages)
        line = (f">>> {_trunc(slayer['warrior'])} (Team: {_trunc(slayer['team'])}) {message}\n"
                f"    Slew the monster {_trunc(slayer['monster'])} {time_str}.\n"
                f"    A replacement warrior slot is now available on {_trunc(slayer['team'])}.")
        lines.append(line)
    
    return "\n".join(lines)


def _fight_style_word(mins):
    if mins<=1: return random.choice(["swift","crushing","decisive","one-sided"])
    if mins<=3: return random.choice(["competent","solid","clean"])
    if mins>=8: return random.choice(["grueling","brutal","drawn-out","action-packed"])
    return random.choice(["spirited","hard-fought","contested"])


def _fight_outcome_verb(mins, winner_hp_pct=1.0):
    """
    Return victory verb based on fight duration AND dominance.
    winner_hp_pct: winner's remaining HP (1.0 = unscathed, 0.5 = half health, etc.)
    """
    # Classify dominance: how much health the winner retained
    if winner_hp_pct >= 0.85:
        dominance = "dominant"
    elif winner_hp_pct >= 0.65:
        dominance = "solid"
    else:
        dominance = "close"

    if mins <= 2:
        # Quick fights - verb selection depends on how badly the winner was hit
        if dominance == "dominant":
            return random.choice([
                "demolished", "vanquished", "overpowered", "decimated",
                "crushed", "obliterated"
            ])
        elif dominance == "solid":
            return random.choice([
                "handily defeated", "soundly defeated", "bested", "outclassed",
                "firmly defeated"
            ])
        else:
            return random.choice([
                "narrowly defeated", "barely defeated", "slimly defeated",
                "edged out", "eked out a win against"
            ])
    elif mins <= 3:
        # Moderate duration
        if dominance == "dominant":
            return random.choice([
                "dominated", "overpowered", "overwhelmed", "subdued", "mastered"
            ])
        elif dominance == "solid":
            return random.choice([
                "bested", "defeated", "overcame", "vanquished", "outwitted"
            ])
        else:
            return random.choice([
                "squeaked past", "narrowly overcame", "barely defeated"
            ])
    else:  # 4+ minutes - true endurance fights
        if dominance == "dominant":
            return random.choice([
                "dominated the endurance battle against", "thoroughly ground down",
                "exhausted", "relentlessly wore down"
            ])
        elif dominance == "solid":
            return random.choice([
                "outlasted", "ground down", "exhausted", "wore down", "prevailed over"
            ])
        else:
            return random.choice([
                "narrowly outlasted", "barely outlasted", "just outlasted"
            ])


def _death_verb(mins, winner_hp_pct=1.0):
    """Return kill verb based on fight duration and how dominant the winner was."""
    if winner_hp_pct >= 0.85:
        dominance = "dominant"
    elif winner_hp_pct >= 0.60:
        dominance = "solid"
    else:
        dominance = "close"

    if mins <= 2:
        if dominance == "dominant":
            return random.choice([
                "executed", "viciously butchered", "assassinated", "eviscerated",
                "cut down", "swiftly dispatched"
            ])
        elif dominance == "solid":
            return random.choice([
                "slew", "assassinated", "slaughtered", "killed",
                "savagely slew"
            ])
        else:
            return random.choice([
                "slew", "killed", "mutilated", "murdered"
            ])
    elif mins <= 5:
        if dominance == "dominant":
            return random.choice([
                "savagely slew", "slaughtered", "butchered", "executed",
                "viciously butchered"
            ])
        elif dominance == "solid":
            return random.choice([
                "slew", "slaughtered", "killed", "butchered", "savagely slew"
            ])
        else:
            return random.choice([
                "finally slew", "slew", "killed", "mutilated"
            ])
    else:  # long, grinding fight
        if dominance == "dominant":
            return random.choice([
                "slaughtered", "butchered", "mutilated", "finally butchered",
                "ground down and slew"
            ])
        elif dominance == "solid":
            return random.choice([
                "slaughtered", "finally slew", "wore down and slew", "butchered"
            ])
        else:
            return random.choice([
                "finally slew", "barely slew", "mutilated", "slew"
            ])


def _race_report(teams) -> str:
    from collections import defaultdict
    rf=defaultdict(int); rw=defaultdict(int); rl=defaultdict(int); rk=defaultdict(int)
    top={}
    for team in teams:
        if _is_npc_team(team): continue
        tname=team.team_name if hasattr(team,"team_name") else team.get("team_name","?")
        tid  =team.team_id   if hasattr(team,"team_id")   else team.get("team_id",0)
        for w in (team.warriors if hasattr(team,"warriors") else team.get("warriors",[])):
            if not w: continue
            wobj=_get_warriors(w)
            if not wobj: continue
            rname=wobj.race.name if hasattr(wobj.race,"name") else "Human"
            if rname in _NPC_RACES: continue
            rf[rname]+=wobj.total_fights
            rw[rname]+=wobj.wins; rl[rname]+=wobj.losses; rk[rname]+=wobj.kills
            score=wobj.wins*3+wobj.kills*2-wobj.losses
            if rname not in top or score>top[rname]["score"]:
                top[rname]={"warrior":wobj.name,"w":wobj.wins,"l":wobj.losses,
                             "k":wobj.kills,"team":tname,"tid":tid,"score":score}
    races=sorted(rf.keys(),key=lambda r:-rf[r])
    sep="="*75
    lines=[f"\n                      {HDR_RED_LG}BATTLE REPORT{HDR_RESET}\n",
           f"{'MOST POPULAR RACE':<25}  {'RECORD DURING THE LAST 10 TURNS':>38}",sep,
           f"{'|RACE':<16}{'FIGHTS':>8}  {'RACE':<18}{'W':>5} - {'L':>4} - {'K':>4}  {'PERCENT':>7}|",sep]
    for race in races:
        tw=rw[race]; tl=rl[race]; tk=rk[race]; pct=int(tw/max(1,tw+tl)*100)
        lines.append(f"|{race:<16}{rf[race]:>8}  {race:<18}{tw:>5} - {tl:>4} - {tk:>4}  {pct:>6}%|")
    lines.append(sep)
    if top:
        lines.append(f"\n\n                      {HDR_RED_LG}TOP WARRIOR by RACE{HDR_RESET}\n")
        lines.append(f"{'RACE':<14}{'WARRIOR':<30}{'W':>4}{'L':>4}{'K':>3}  TEAM NAME"); lines.append(sep)
        for race in races:
            if race in top:
                td=top[race]
                lines.append(f"{race:<14}{_trunc(td['warrior']):<30}{td['w']:>4}{td['l']:>4}{td['k']:>3}"
                              f"  {_trunc(td['team'])} ({td['tid']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ARENA HAPPENINGS - modular narrative block libraries
# ---------------------------------------------------------------------------
# Each pool holds 10 variant templates.  Variables available in every block:
#   {arena}       Full arena name, uppercase  (BLOODSPIRE ARENA)
#   {venue}       Short venue name            (Bloodspire)
#   {byline}      Reporter name
#   {turn}        Current turn number
#   {next_turn}   Next turn number
#   {team}        Primary team name, uppercase
#   {team2}       Secondary team name, uppercase
#   {record}      W-L-K string for the turn
#   {rank_change} Descriptive movement phrase
#   {warrior}     Warrior name, uppercase
#   {opponent}    Opponent name, uppercase
#   {points}      Warrior's current recognition score
#   {champion}    Champion name, uppercase
#   {champ_team}  Champion's team name, uppercase

_BLK_BYLINES = [
    "Dax Ironquill, Agony Gazette",
    "Mira Coldtongue, The Blood Ledger",
    "Horst Veyne, Pit Press Weekly",
    "Snide Clemens, Arena Correspondent",
    "Alarond the Scribe",
    "The Unknown Spymaster",
    "Olaf Modeen, Retired Correspondent",
    "Bryndis Coldquill, Arena Correspondent",
    "Magistra Pellwood, Official Chronicle",
    "Aldric Fenworth, Agony Gazette",
    "Kess Thorne, The Daily Report",
    "Valter Grim, Dispatch Correspondent",
    "Nore Blackson, Arena Press",
    "Tessa Wynter, Truth and Record",
    "Mordak the Keen-Eyed, Scribe",
    "Lyssa Vex, Record Keeper",
    "Garrett Stonewell, Public Chronicle",
    "Sylvain Darkwood, Accounts of War",
    "Camilla Frost, The Arena Voice",
    "Toren Sharpquill, Correspondent",
]

_BLK_INTRO = [
    "Another turn has passed in {arena}, and the dust still hangs heavy where blades met bone.  Victories were earned, pride was lost, and more than one plan failed the moment steel left its scabbard.  As always, the arena cared little for intent.  Only outcomes.",
    "If hope walked into {arena} this turn, it didn't leave intact.  Managers talked big, warriors listened poorly, and the standings now tell the truth no one wanted to hear.  Let's go over who impressed and who shouldn't bother pretending.",
    "Hear me now!  {arena} thundered beneath the weight of ambition this turn, and the ambitious were sorted from the foolish with ruthless clarity.  Songs will exaggerate what happened here, but not by much.",
    "I heard three versions of this turn at {venue}, and every one got louder with each drink.  Somewhere between the boasting and the lies is what really happened in {arena}.  Lucky for you, I paid attention.",
    "The turn began like any other and ended exactly as it had to in {arena}.  Some rose, some fell, and fate collected its due without apology.  Let's read the damage.",
    "{arena} doesn't announce when it's about to teach someone a lesson.  It just waits for confidence to turn into error.  This turn was no exception.",
    "Another turn came and went in {arena}, leaving the standings rearranged and several reputations in urgent need of explanation.  Tradition holds firm.",
    "Managers entered this turn with plans.  Warriors entered with steel.  Only one of those things survived contact with reality in {arena}.",
    "{arena} woke hungry this turn, and it was fed without restraint.  What follows are the names of those who satisfied it, and those who regretted trying.",
    "I have seen many turns in many places, and {arena} remains uniquely honest.  It rewards preparation, punishes pride, and forgets quickly.",
    "The {arena} was alive with activity this turn, as it always is when warriors gather to test themselves against one another.",
    "In a place as relentless as the {arena}, a single turn contains multitudes. Victories and defeats, hopes and despairs, all compressed into one span of combat.",
    "The narrative of the {arena} continues to write itself, turn after turn, fight after fight, and this week's chapter is no exception.",
    "The sand of the {arena} tells many stories, and this turn it told all of them at once.",
    "Warriors came to the {arena} with ambitions this turn.  Not all of them left with the same ambitions intact.",
    "The {arena} is never quiet for long, and this turn proved no exception to that rule.",
    "The {arena} waits for no one and shows mercy to no one, and this turn demonstrated both truths with clarity.",
    "Another turn in the endless cycle of the {arena}, another chance for warriors to make their mark or fade into obscurity.",
    "The {arena} demands constant attention, and this turn has no shortage of stories worth examining.",
    "What unfolds in the {arena} shapes the city, the standings, and the futures of everyone who dares to fight in it.",
]

_BLK_TEAM_PERF = [
    "{team} walked into the turn with questions and walked out with answers.  Their {record} showing pushed them {rank_change} in the standings, built on decisions that held up under pressure.  Others noticed and adjusted accordingly.",
    "{team} arrived at this turn with a target and left having hit it.  A {record} performance has them {rank_change}, and the confidence that follows a clean week of results is worth more than the record alone suggests.",
    "{team} converted what the schedule offered into a {record} showing and movement in the standings.  That kind of execution rate is what separates the prepared from the hopeful in {arena}.",
    "{team} took what the schedule offered this turn and returned a {record} showing for it.  That conversion rate explains the {rank_change} in the standings.  {arena} rewards teams that read the bracket and respond properly.",
    "The {record} turn from {team} quietly set a pace worth paying attention to.  Not every strong performance generates noise, but the standings hear it clearly enough.",
    "{team} avoided spectacle and focused on execution this turn.  The resulting {record} pushed them {rank_change}, a reminder that consistency still matters here.",
    "The standings record {team}'s {record}, but it's the confidence that followed which concerns rival managers.  Momentum, once earned, is difficult to interrupt.",
    "{team} closed this turn with a {record} result that moved them {rank_change}.  Preparation showed.  Rivals who scheduled around them may want to revise that decision before the next bracket.",
    "A {record} turn for {team} and movement in the standings.  Not every performance needs to be memorable to be effective.  In {arena}, outcomes do the talking that style cannot always manage.",
    "Something changed for {team} this turn.  Whether the {record} marks the beginning of a sustained rise or an early signal remains to be seen, but the standings took notice.",
    "{team}'s {record} turn this week demonstrates that consistency pays off.  Moving {rank_change}, they are building something that looks sustainable.",
    "The {record} performance from {team} has pushed them {rank_change}, and the improvements are visible across the roster, not just in isolated warriors.",
    "{team} is {rank_change} this turn with a {record} showing that suggests they have found a winning formula.  Whether they can sustain it remains to be seen.",
    "A {record} turn for {team} moves them {rank_change} and puts them in conversation with teams that were previously considered their superiors.",
    "{team}'s {record} result this turn has them climbing {rank_change}.  The trajectory matters more than the single turn, and the trajectory looks positive.",
    "The momentum building for {team} is visible in their {record} showing and their {rank_change} movement.  This is the kind of progress that compounds.",
    "{team} turned in work this turn that justified their {record} record and pushed them {rank_change}.  For every warrior on that roster, execution mattered.",
    "{team} is now {rank_change} after a {record} performance that suggests they are hitting their stride.",
    "The {record} result for {team} this turn positions them {rank_change} and demonstrates that they are more than a one-off success.",
    "What {team} accomplished this turn, a {record} showing, earned them {rank_change} movement and validation that their approach is working.",
]

_BLK_WARRIOR_HI = [
    "{warrior} left little to debate after facing {opponent}.  The fight was decisive, the outcome clearer by the moment, and {points} recognition to their name.  That performance will linger in memory longer than the scars.",
    "There was nothing wrong with {warrior}'s approach against {opponent} this turn.  The execution was clean, the timing was right, and the result was inevitable.  {arena} noticed, whether it announced it or not.",
    "Preparation paid off when {warrior} stepped into the arena this turn.  Against {opponent}, patience and timing proved more dangerous than brute force, earning quiet respect from those paying attention.",
    "The fight between {warrior} and {opponent} ended the way the records suggested it would, but the manner of it raised a few eyebrows.  {warrior} made it look easy.  Sometimes the most honest statement the arena makes is exactly that.",
    "Victory rarely announces itself loudly in {arena}.  {warrior} overcame {opponent} through patience and timing, not force, earning recognition through discipline rather than drama.  Few noticed at first, but many will remember.",
    "{warrior} entered the arena with a plan and left without an argument.  {opponent} never found footing, and the result was entirely predictable from the opening exchange.",
    "{warrior} underestimated {opponent}, a mistake corrected decisively before the crowd grew bored.  In {arena}, assumptions are expensive.",
    "The fight wasn't clean, fast, or elegant, but {warrior} endured.  Against {opponent}, persistence carried the day and the record followed.",
    "{opponent} learned more than they expected when facing {warrior} this turn.  Some lessons cost pride; others cost position.",
    "Word spreads quickly after performances like {warrior} delivered this turn.  {arena} takes note, and so do managers with memory.  {points} recognition and rising.",
    "{warrior} produced a masterclass in controlled, effective combat against {opponent}.  The kind of performance that earns lasting recognition and respect.",
    "Against {opponent}, {warrior} displayed the kind of technical precision that separates masters from merely competent warriors.  {Points} recognition well earned.",
    "{warrior} moved through {opponent} with the efficiency of someone who knows exactly what {he} is doing.  The result was never in doubt.",
    "The performance {warrior} delivered this turn was the kind that reminds {arena} why some warriors rise and others plateau.  {Opponent} had no answer for {warrior}'s skill.",
    "{warrior} proved {himself} decisively against {opponent}.  The manner of victory suggested preparation that far exceeded {opponent}'s preparation.",
    "There was beauty in the brutality of {warrior}'s victory over {opponent}.  Controlled, purposeful, and absolutely dominant.",
    "{warrior} made {opponent} look like they were fighting in a different tier.  The gap in skill was that pronounced.",
    "Against {opponent}, {warrior} displayed every quality that makes {him} dangerous. Skill, timing, and an apparent calm in the chaos of combat.",
    "{warrior}'s handling of {opponent} this turn will be studied by warriors looking to understand what mastery looks like.",
    "The performance {warrior} delivered was a statement. {points} recognition earned, and a clear declaration that {he} is among the most dangerous warriors in {arena}.",
]

_BLK_META_WARRIOR = [
    "{warrior} drew more challenges than anyone else this turn, a mix of opportunity seeking and poor judgment by would-be rivals.  Attention like that rarely ends quietly.",
    "Schedules don't lie, and this turn {warrior} attracted the most challenge traffic in {arena}.  Whether rivals see an opportunity or underestimate the danger remains to be answered.",
    "Several challengers tested {warrior} this turn with varying degrees of confidence.  The results told the story the records already suggested.",
    "As the turn progressed, the challenges aimed at {warrior} felt less strategic and more desperate.  In {arena}, that kind of urgency often exposes more weakness than courage.",
    "{warrior} became a focal point this turn, drawing repeated challenges from hopeful rivals.  Popularity in this arena is rarely comfortable.",
    "{warrior} continues to sharpen {his} edge.  Where {he} once fought reactively, {he} now fights with clear intent, and the results speak for themselves.",
    "Observers have noticed {warrior} making deliberate choices in recent turns.  {His} evolution as a fighter is becoming impossible to ignore.",
    "{warrior} is building something. Each fight seems part of a larger strategy, and it is working.",
    "The rise of {warrior} is not accidental.  {His} training decisions and tactical awareness are setting {him} apart from {his} peers.",
    "{warrior} seems to understand something about {his} fighting style that others do not.  It shows in every turn.",
    "{warrior} is adapting faster than most warriors adapt.  The record shows growth, but the potential shows far more.",
    "There is a confidence to {warrior} that was not visible in earlier turns.  It translates directly into improved results.",
    "{warrior} is making {his} mark.  The whispers around {arena} are growing louder.  This one is going somewhere.",
    "It is becoming clear that {warrior} is more than a competent fighter.  {He} is a strategist, learning {his} strengths with each bout.",
    "{warrior} carries an intensity that few can match.  {His} recent performances have earned more attention than {his} record alone would suggest.",
    "{warrior} is playing at a level that seems to be improving every turn.  Whatever {he} is doing in training is working.",
    "The development of {warrior} over recent turns has not gone unnoticed.  {His} approach is becoming more refined, more dangerous.",
    "{warrior} seems to be hitting {his} stride.  Each turn brings fresh evidence of {his} upward trajectory.",
    "{warrior} is building a reputation beyond mere records.  {His} name is becoming one that other managers watch carefully.",
    "There is something relentless about {warrior}'s advancement.  {His} focus and execution suggest {he} has a clear vision for where {he} wants to go.",
]

_BLK_META_TEAM = [
    "Managers were noticeably reluctant to schedule fights against {team} this turn.  Avoidance like that doesn't come from reputation alone; it comes from recent memory.  Smart managers learn quickly in {arena}.",
    "Whenever {team} appeared on the board, opponents suddenly developed scheduling conflicts.  Fear dresses itself as caution in many ways, and this turn wore it openly.",
    "Schedules don't lie, and this turn revealed growing hesitation around {team}.  Challenges that once came freely are now reconsidered, delayed, or quietly withdrawn.  Reputation is finally catching up.",
    "Once the first manager avoided {team}, others followed.  Fear spreads efficiently under the guise of scheduling logic.",
    "Beneath the noise of the arena, careful managers adjusted pairings with intent.  Not all victories this turn required combat.  {team} benefited from the arithmetic.",
    "Schedules reveal strategy, and {team}'s schedule this turn was a carefully crafted response to market conditions.  Clear thinking and clearer goals.",
    "{team} is building momentum with every turn.  The way the roster has been handled suggests leadership has a clear plan.",
    "There is a pattern to {team}'s decisions this turn that speaks to organized thinking.  Not luck, but strategy.",
    "{team} is taking calculated risks on the schedule.  So far, they are paying off.",
    "The competitive positioning of {team} continues to tighten.  Leadership is making smart calls about which fights to accept and which to decline.",
    "{team}'s management is not flashy, but it is effective.  Quiet competence is often the most dangerous kind.",
    "Observers are noticing how {team} manages {their} roster.  Careful placement, deliberate matchups, a clear sense of direction.",
    "{team} is not relying on chance.  Each placement seems designed, each fight scheduled with purpose.",
    "The discipline of {team}'s approach is becoming more evident with each turn.  This is not improvisation. This is planning.",
    "{team} is building warriors and building momentum simultaneously.  The investment in development is showing returns.",
    "How {team} schedules fights tells you everything about how {they} think.  This turn, {they} were thinking clearly.",
    "{team} is managing for long-term success while competing for short-term results.  That balance is harder to strike than it looks.",
    "The reputation {team} is building is not accidental.  Every scheduling decision seems to reinforce a larger strategy.",
    "{team}'s approach to team composition and fight selection suggests leadership with experience and vision.",
    "There is a quiet confidence to {team}'s management this turn.  The record suggests it is not misplaced.",
]


_BLK_CHAMP_NEW = [
    "The crowds were amazed this turn, as {champion} of {champ_team} dethroned the reigning Champion in a fight that will be talked about for turns to come.  A new name atop the throne.",
    "{champion} of {champ_team} has done what countless rivals only dreamed of, claiming the Championship in direct combat.  The arena has a new ruler, and the pretenders must recalculate.",
    "Stop the histories and note the date. {champion} of {champ_team} is the new Champion of {arena}.  The old order ends.  The new one has precisely one member.",
    "History rewrites itself in moments. {champion} of {champ_team} has defeated {prev_champion} and claimed the throne.",
    "The throne has changed hands tonight. {champion} of {champ_team} has taken the Championship from {prev_champion} in spectacular fashion.",
    "The crowds erupted as {champion} of {champ_team} seized the Championship from {prev_champion} in a bout that will echo through the arena.",
    "{champion} of {champ_team} did what countless rivals attempted and failed, dethroning {prev_champion} and claiming the title for themselves.",
    "The changing of the guard is complete. {champion} of {champ_team} has vanquished {prev_champion} and claimed the throne.",
    "In a stunning upset, {champion} of {champ_team} knocked {prev_champion} from the throne and claimed the title themselves.",
    "The Championship was not gifted. {champion} of {champ_team} earned it by defeating {prev_champion} in direct combat.",
    "The old order falls away. {prev_champion} is no longer the Champion. {champion} of {champ_team} stands atop the arena now.",
    "What the crowds feared has come to pass. {prev_champion} is dethroned. {champion} of {champ_team} is the new Champion.",
    "A coronation of sorts occurred this turn. {champion} of {champ_team} became the new Champion by vanquishing {prev_champion}.",
    "The throne was not undefeated, and {prev_champion} has learned that hard lesson. {champion} of {champ_team} is the new Champion.",
    "Years of anticipation end tonight. {champion} of {champ_team} is finally the Champion, having defeated {prev_champion} in combat.",
    "The transition is official. {prev_champion}'s reign has ended, and {champion} of {champ_team} claims the throne.",
    "Against all odds and despite {prev_champion}'s dominance, {champion} of {champ_team} has seized the Championship.",
    "{prev_champion} held the crown, but all crowns can be taken. {champion} of {champ_team} now rules the arena.",
    "The new Champion stands where the old one fell. {champion} of {champ_team} has defeated {prev_champion} and claimed their destiny.",
    "{champion} of {champ_team} has done the impossible, dethroning {prev_champion} and claiming the Championship for themselves.",
]

_BLK_CHAMP_INCUMBENT = [
    "{champion} of {champ_team} defended the throne this turn by simple absence of defeat.  Holding the title invites endless scrutiny, yet few step forward to challenge it.",
    "Still undefeated, {champion} of {champ_team} remains the Champion.  Another turn passes, and the pretenders are no closer to dislodging the title.",
    "The arena is defined by presence, and {champion} of {champ_team} continues to provide it.  The Championship throne remains occupied, another turn's triumph for the incumbent.",
    "While others plotted advancement, {champion} of {champ_team} simply endured.  The Championship waits for challengers bold enough to contest it.",
    "{champion} of {champ_team} holds the throne without fanfare.  In {arena}, consistency on the title is worth more than any grand gesture.",
    "{champion} of {champ_team} held the crown again this turn by defeating {opponent}.  The Championship stays with the right warrior.",
    "The reigning Champion proved why they wear the crown. {champion} of {champ_team} overcame {opponent} and remains untouched.",
    "{champion} of {champ_team} faced {opponent} this turn and answered decisively.  The throne remains secure on the right shoulders.",
    "Another challenger, another defeat. {opponent} tested {champion} of {champ_team}'s throne and found it unshakeable.",
    "{champion} of {champ_team} remains the Champion after besting {opponent}.  The title shows no signs of changing hands.",
    "The Championship continues under {champion} of {champ_team}'s rule, who saw off {opponent}'s challenge with ease.",
    "{opponent} stepped forward to challenge the throne and {champion} of {champ_team} reminded {opponent} why that was a mistake.",
    "The crown sits secure on {champion} of {champ_team}'s head, proven once more by the defeat of {opponent}.",
    "{champion} of {champ_team} held off {opponent} this turn and in doing so, defended the Championship once more.  The title remains theirs.",
    "Another challenger falls before the throne.  {champion} of {champ_team} prevailed over {opponent} and proves the Championship's true holder.",
    "The Championship is held by the right warrior.  {champion} of {champ_team} faced {opponent} and retained the title with authority.",
    "{champion} of {champ_team} faced down {opponent} and the result was never in doubt.  The throne belongs to the strong.",
    "As {opponent} learned this turn, challenging {champion} of {champ_team} is a lesson in futility.  The throne remains secure.",
    "{champion} of {champ_team} overcame {opponent} this turn and continues to hold the Championship.  No one is ready to take it.",
    "The Champion's grip remains firm.  {champion} of {champ_team} bested {opponent} this turn and showed once more why they wear the crown.",
]

_BLK_CHAMP_VACANT = [
    "The Championship throne remains empty this turn.  No warrior has yet met the criteria to claim it.  Every manager with ambition should be watching their most recognised fighter closely.",
    "No Champion walks the arena floor this turn.  The vacancy is an open invitation, and somewhere in {arena}, someone is already planning to answer it.",
    "The title sits unclaimed in {arena}, which means every warrior with enough recognition and enough nerve has cause to press forward.  The throne waits.",
    "The throne sits vacant this turn, waiting for a warrior bold enough or skilled enough to claim it. Every ambitious fighter in {arena} is watching.",
    "Without a Champion, the arena holds its breath. The title is there for the taking, and the contenders circle like wolves around prey.",
    "No one wears the crown today. The Championship is unclaimed, and every manager with a strong warrior is calculating their odds.",
    "The Championship is without a holder this turn. An open position of power awaits the warrior with the recognition to claim it.",
    "A vacancy at the top of the standings. The throne awaits a warrior with enough reputation and skill to occupy it.",
    "The arena has no master this turn. Somewhere in the crowd, ambitious fighters are sizing each other up, wondering if this is their moment.",
    "The Champion's seat remains empty. The opportunity is there for any warrior with the standing to challenge for the title.",
    "No crown sits atop any warrior's head this turn. The path to the Championship is wide open for those with the recognition to walk it.",
    "The throne is vacant and waiting. What ambitious warrior will step forward to claim what no one currently holds?",
    "Without a sitting Champion, the arena feels different this turn. The title is there, unclaimed, waiting for the right warrior.",
    "A Champion-less arena is a curious thing. The power and prestige of the title remain, but no warrior has yet claimed them.",
    "The Championship title goes unclaimed this turn. Every fighter with sufficient standing is watching and wondering if destiny is calling.",
    "No one has yet reached the pinnacle of recognition needed to wear the crown. The throne sits vacant, a throne waiting to be filled.",
    "In the absence of a Champion, the arena feels like it's holding its breath. The title is there for the warrior bold enough to reach for it.",
    "The throne is empty, and the opportunity is immense. Which warrior will rise above the rest and claim the vacant Championship?",
    "No Champion rules {arena} this turn. The position stands open, and the competition to fill it will be fierce.",
    "The Championship remains in abeyance. The title is waiting for a warrior with the reputation and resolve to claim it.",
]

_BLK_CHAMP_RECOGNITION = [
    "The Championship does not always change hands through combat.  This turn, the ledger made its own ruling. {champion} of {champ_team} carries the highest recognition in {arena}, and with it, the title.  The mathematics require no ceremony.",
    "No fight was needed.  The standings spoke clearly enough.  {champion} of {champ_team} holds more recognition than any other warrior in {arena} and now holds the Championship to match.  The title follows the record.",
    "{champion} of {champ_team} did not take the title from anyone.  The title came to them.  With the highest recognition score on the roster, the Championship has found its rightful occupant by right of standing.",
    "The Championship throne has a new occupant by recognition. {champion} of {champ_team}.  No duel, no drama.  Simply the reward for being the best-regarded warrior in {arena}.  The arena's verdict is rarely delivered so quietly.",
    "When no one earns the title by force, the records decide.  {champion} of {champ_team} sits atop those records this turn, and the Championship follows.  Whether they can hold it in combat is a question for future turns.",
    "The standings speak louder than steel.  {champion} of {champ_team} has climbed higher than any warrior in the arena and claims the Championship by virtue of reputation alone.",
    "{champion} of {champ_team} needed no victory in the ring to claim the crown. The record was enough.  The highest recognition in {arena} has earned the highest title.",
    "A coronation without combat.  {champion} of {champ_team} ascends to the Championship on the strength of their standing alone.",
    "The ledger has spoken and the result is clear. {champion} of {champ_team} carries the most recognition in {arena} and with it, the Championship.",
    "{champion} of {champ_team} claims the title not through force but through consistent excellence.  The standings affirm what the arena already knew.",
    "No blade needed to change this crown.  {champion} of {champ_team}'s reputation has grown so great that the Championship follows naturally.",
    "{champion} of {champ_team} rises to the Championship by the only measure that truly counts. The respect and recognition of all who have watched them fight.",
    "The title changes hands not in battle but in the records.  {champion} of {champ_team} has earned the highest recognition and with it, the crown.",
    "{champion} of {champ_team} did not need to defeat anyone to become Champion. The weight of their accomplishments was enough.",
    "When the records are tallied and the standings are clear, {champion} of {champ_team} sits at the top.  The Championship follows that truth.",
    "{champion} of {champ_team} ascends through excellence, not through conflict.  The recognition {he} has earned has granted {him} the title.",
    "The Championship is not always claimed in blood.  {champion} of {champ_team}'s recognition has made {him} the obvious choice for the crown.",
    "By right of reputation, {champion} of {champ_team} claims the Championship.  The arena's regard has settled the matter without a trial by combat.",
    "{champion} of {champ_team} earns the crown not by defeating another, but by standing highest in the eyes of {arena}.",
    "The throne seeks the worthy, and {champion} of {champ_team}'s recognition marks {him} as the most worthy warrior in the arena.",
]

_BLK_DEATH = [
    "{warrior} will not be appearing on future schedules.  Slain by {killer} this turn, their career ends at {record}.  {arena} makes no distinction between early exits and late ones.  Only between active and gone.",
    "{warrior} was cut down by {killer} this turn and will not return.  The record reads {record}.  Final.  {arena} moves on as it always does, without ceremony.",
    "The career of {warrior} has come to its end.  {killer} finished what the record was already suggesting.  A {record} showing at the close, and a vacant slot on the {team} roster.",
    "{killer} made it permanent this turn.  {warrior} is no longer on any schedule, no longer a factor in any planning.  A career record of {record}.",
    "{warrior} entered the arena this turn and did not leave it in the usual way.  {killer} delivered the verdict, and {arena} accepted it without argument.  Career record stands at {record}.",
    "The stands quieted when {warrior} fell to {killer}, if only for a moment.  Then the next fight was called, and the arena continued.  It always does.  Final record stands at {record}.",
    "Short or long, every career in {arena} ends the same way.  {warrior}'s ended this turn, at the hands of {killer}.  The record says {record}.  The rest is silence.",
    "Gone.  {warrior} of {team}, career record {record}, was put down by {killer} this turn and will not return to any schedule.  Another name moves from the active ledger to the permanent one.",
    "{warrior} is dead.  {killer} handled the business of it, and now {team} has a vacancy and a memory.  Not always in that order, but always in that combination.",
    "Nobody told {warrior} it was going to end this turn.  {killer} understood what was happening before the crowd did.  Final record stands at {record}.",
    "{warrior}'s time in the arena is finished.  {killer} delivered the final blow, and now {warrior} is part of {arena}'s history rather than its present.  A career record of {record}.",
    "The mortality of {warrior} became very real when {killer} crossed swords with {him} this turn.  The arena does not forgive, and it did not forgive this time.",
    "{warrior} came to the arena seeking glory or coin or both.  What {he} received instead was {killer}'s blade and a permanent exit.  A career record of {record}.",
    "Death came to {warrior} this turn in the form of {killer}.  It is the kind of end that the arena reserves for those who step through its gates.",
    "{killer} wrote the final chapter of {warrior}'s story today.  It was not the ending anyone writes hoping for, but it is the one {warrior} received.  Final record stands at {record}.",
    "The lights dimmed for {warrior} when {killer} struck.  They will not brighten again.  The arena has claimed another.",
    "{warrior} fought {killer} and lost in the way that matters most in the arena.  There is no recovery from this kind of loss.",
    "By {killer}'s hand, {warrior} passes from the living to the remembered.  The arena continues its work.  Final record stands at {record}.",
    "{warrior} was cut down in {his} prime or {his} decline, depending on which record you trust.  Either way, {killer} ensured the debate is now academic.",
    "Another warrior added to the {arena}'s toll.  {killer} and {warrior} met, and only {killer} left.  That is how the arena settles its accounts.",
]

_BLK_SPIRE_INTRO = [
    "Before this report closes, a word about the Elite Spire, {arena}'s higher tier, where the truly dangerous are sent to test one another without the mercy of easy opponents.",
    "The shadow of the Elite Spire fell across {arena} this turn, as it does whenever warriors reach the threshold that separates the accomplished from the elite.",
    "Not every story from {arena} this turn involves a loss.  Some of the news concerns ascension, which is a different kind of leaving, one that the warriors in question have earned.",
    "The Elite Spire scouts were watching {arena} again this turn, as they always are when the records start reaching uncomfortable heights.",
    "There is a door that opens only for warriors who have proven themselves beyond reasonable argument.  This turn, that door received notice.",
    "While the dust settled over the results, word quietly spread through {venue} that the Elite Spire had taken interest in events on the regular circuit.",
    "Elsewhere in the {arena}, beyond the results and the standings, there is the matter of the Elite Spire, and who among this turn's combatants has drawn its attention.",
    "I have one more item for this report, and it concerns the kind of recognition that goes beyond standings points.  The Elite Spire does not send invitations lightly.",
    "The Elite Spire does not announce itself loudly.  But those who watch carefully saw the signs this turn. Records reaching the thresholds, managers receiving discreet correspondence.",
    "Beyond the ordinary business of wins and losses, this turn carried news of a different kind.  The Elite Spire had opinions about {arena}'s current roster.",
    "This turn's fighting settled more than just standings.  For at least one warrior, it settled the question of whether they belong in a different league entirely.",
    "There is a tier above {arena}.  Fewer fights, stronger opponents, and no margin for anything but excellence.  It had its eye on this turn.",
]

_BLK_SPIRE_INVITED = [
    "{warrior} of {team} has received the invitation that every warrior in {arena} trains toward and most never see.  The Elite Spire's scouts reviewed the record, {record}, and found no argument against extending the offer.  One more fight on this circuit, and then the Spire awaits.",
    "The record stands at {record} and the Spire has made its position clear. {warrior} belongs in a different competition.  {manager} has been notified.  The warrior will fight once more in {arena} before the door closes behind them.",
    "Word from the Elite Spire reached {manager}'s camp this turn.  {warrior} has qualified.  A {record} career on this circuit has earned an invitation that only the most disciplined fighters receive.  The next fight will be the last one at this level.",
    "Whispers confirmed by the morning post. {warrior} of {team} has been summoned to the Elite Spire.  The invitation followed a career record of {record}, numbers that left the Spire's selection committee without a counterargument.  {manager} will need to find a replacement slot.",
    "{warrior}'s {record} record was always going to attract attention from above.  This turn, that attention arrived in official form.  The Elite Spire has extended its invitation, and {warrior} will fight one final bout here before ascending.",
    "The Elite Spire does not explain itself, but the selection makes sense.  {warrior} of {team} has posted {record} across their career on this circuit, and the Spire rewards exactly that kind of consistency.  {manager} received the summons this turn.",
    "An invitation to the Elite Spire is not a question. It is a conclusion.  {warrior}'s {record} career record answered every question the Spire needed answered.  One more fight under normal conditions, and then the harder work begins.",
    "{warrior} earned this.  A {record} record with {team} is not the product of fortune.  It is the product of preparation, execution, and whatever particular stubbornness drives fighters to keep improving.  The Elite Spire noticed.  The invitation is official.",
    "{manager}'s {warrior} received confirmation this turn that the Elite Spire has been watching.  The {record} career record was apparently sufficient to end the deliberation.  One final bout here, then a very different caliber of opponent awaits.",
    "The scouts do not show their hand until the record makes the case for them.  {warrior}'s {record} made that case this turn without ambiguity.  The invitation has been extended.  {team} loses a warrior when this is over.",
    "Not everyone who fights in {arena} gets noticed by the Elite Spire.  {warrior} got noticed.  The {record} record convinced the scouts, and the invitation followed.  {manager} has one more turn of preparation before the ascent.",
    "The Elite Spire keeps its own ledger, and {warrior}'s name has appeared at the top of it.  A {record} career in {arena} has earned exactly this outcome.  The invitation stands.  The ascent is coming.",
]

_BLK_SPIRE_DEPARTED = [
    "{warrior} has gone.  The {record} career record goes with them, along with whatever understanding of this circuit they accumulated turn by turn.  {team} has a gap in the roster.  The Elite Spire has a new arrival.",
    "The last entry in {warrior}'s normal-circuit record is written.  {record} across their career here, and now they step through the door that the Elite Spire holds open for exactly this kind of fighter.  {manager} will adjust.  The Spire will not.",
    "{manager}'s {warrior} fought their final bout under normal conditions this turn.  A career record of {record} carried them to this moment, and the Elite Spire accepted delivery.  The empty slot on {team}'s roster is a mark of achievement, which is a strange kind of honor.",
    "The crowd at {venue} may not have known it was watching {warrior}'s last fight on this circuit.  The record, {record}, confirms it was.  The Elite Spire made it official.  One level of competition closes; another opens.",
    "It is worth noting for the record that {warrior} of {team} has concluded their time at this tier.  The final tally reads {record}.  The Elite Spire has accepted them without negotiation, which is the only way the Spire operates.",
    "{warrior} is no longer on the schedule for {arena}.  The Elite Spire absorbed them this turn, following a career that ended at {record}.  {manager} trained them to this point.  The Spire will take it from here.",
    "Career ended at {record}.  Arena changed.  {warrior} of {team} completes their time on the normal circuit and begins something considerably more difficult.  The Elite Spire does not ease new arrivals in gently.",
    "The fighters who reach the Elite Spire do not come back down.  {warrior}'s {record} career in {arena} is over.  What begins in the Spire is a different accounting entirely.  {manager} produced a warrior worthy of it.",
    "The final normal-circuit record for {warrior} stands at {record}.  The fight was the last one.  The Spire received them.  {team} now has a vacancy where a very capable warrior used to be.",
    "Some departures are losses.  This one is promotion.  {warrior} leaves {arena} at {record} and enters the Elite Spire, where the competition is precisely as unforgiving as the name implies.  {manager} has seen them off.",
    "{warrior}'s last appearance on the normal-arena schedule has come and gone.  The final career record stands at {record}.  The Elite Spire collected another one, and the {team} roster is the leaner for it.",
    "There is no ceremony at the Spire's gate.  {warrior} qualified, fought their last bout here, and ascended.  The record, {record}, will not be updated again at this level.  {manager} sends them forward.",
]

_BLK_OUTRO = [
    "The ink dries, the crowds thin, and {arena} waits for the next mistake.  Until then, I carry these accounts onward.  - {byline}",
    "That's the turn as it happened, not as it was advertised.  Anyone unhappy with the outcome is welcome to try again, results permitting.  - {byline}",
    "I'll be at {venue} if anyone wants to argue about it.  Bring coin, or don't bother.  - {byline}",
    "The turn is done.  The consequences remain.  - {byline}",
    "The turn is complete, the outcomes recorded, and the excuses already forming.  Whatever comes next, {arena} will be ready.  - {byline}",
    "The turn closes.  The implications remain.  Until Turn {next_turn} - {byline}",
    "{arena} will remember this turn longer than some warriors will.  - {byline}",
    "I've written worse turns, but not many.  See you in Turn {next_turn}.  - {byline}",
    "I'll raise a glass to the survivors.  The rest are beyond complaint.  Until next time - {byline}",
    "Until the brackets change again, this is what happened.  - {byline}",
    "That sums it up for this turn.  {arena} has spoken through steel and strategy, and the message is encoded in the standings.  - {byline}",
    "The chapter closes here.  The next one opens with the same uncertainty that always precedes it.  - {byline}",
    "What {arena} has rendered this turn cannot be undone.  The standings are written.  The records are kept.  The future awaits.  - {byline}",
    "The implications of this turn will echo through scheduling decisions for weeks to come.  That is how {arena} works.  - {byline}",
    "What {arena} has rendered this turn cannot be undone.  The standings are written.  The records are kept.  - {byline}",
    "The turn has run its course.  What matters now is how the managers respond and how the warriors adapt.  - {byline}",
    "The standings tell the story that the crowd could not quite articulate.  Read them carefully.  They rarely lie.  - {byline}",
    "Until the next turn brings fresh competition and fresh outcomes, that is what the {arena} delivered this week.  - {byline}",
    "The records stand as witnesses to what transpired.  Some will be satisfied with those records.  Others will spend the off-turn plotting.  - {byline}",
    "That is the turn.  The implications ripple outward from here, reshaping strategies and challenging assumptions.  - {byline}",
]

# ---------------------------------------------------------------------------
# ELITE SPIRE NARRATIVE POOLS
# ---------------------------------------------------------------------------

_BLK_ELITE_BYLINES = [
    "Vesper Crane, The Summit Dispatch",
    "Orryn Ashvale, Chronicle of the Ascended",
    "Mirelle Stonequill, The Spire Record",
    "Thalric Voss, The High Register",
    "Corwin Evenmere, Voices From the Summit",
    "Isolde Ravenmere, The Immortal Gazette",
    "Aldrik Fenmoor, Upper Circuit Correspondent",
    "Nessa Blackthorn, The Unbroken Chronicle",
]

_BLK_ELITE_OPENING = [
    "Good people of {arena}, come in from the noise and dust and find yourselves a seat.  Turn {turn} is behind us, and I am pleased to report that everyone who entered the Spire also managed to leave it breathing.",
    "Settle in, friends of {venue}.  The turn is done, the sand has been raked, and we have much to discuss about what passed between these walls.",
    "Turn {turn} in {arena} is complete, and what a piece of work it was.  Pour something strong and let me walk you through it.",
    "The gates of {arena} have closed on another fine turn.  Those of you who missed it have my sympathy; those of you who attended have my admiration for your constitution.",
    "Welcome back to {venue}, where the fights are serious, the warriors are seasoned, and the seats are considerably harder than the competition.  Turn {turn} is done.",
    "Come find your chair, good people.  {arena} has given us a turn worth talking about, and I intend to give it the commentary it deserves.",
    "Another turn in {arena}, another chapter written in the careers of warriors who have seen too much to be easily impressed.  Turn {turn} did not disappoint.",
    "The Spire has spoken, as it does every turn, in the language of iron and will.  Here is what it said on turn {turn}.",
    "For those of you who have not been paying attention, {arena} continued its tradition of providing the finest combat this circuit has to offer.  Turn {turn} was no exception.",
    "Let the record show that turn {turn} in {arena} was eventful, occasionally brutal, and entirely worth the price of admission.  I was there.  Here is my account.",
    "Good people of {arena}, I have seen a great many things in my years at this circuit.  Turn {turn} gave me a few more to add to the list.",
    "There is a particular quality to the silence in {arena} just before the first fight of the turn.  Turn {turn} did not waste that silence.",
    "Pull your chair close.  The fires in {venue} are burning low, and I have a full turn's worth of news that deserves your attention.",
    "Some turns in {arena} are forgettable.  Turn {turn} was not among them.  Take a seat and I will explain why.",
    "The sands of {arena} saw serious business on turn {turn}.  Warriors who have been here long enough to know better still managed to surprise me.",
    "By my count, {arena} has been running for some time, and it has rarely disappointed.  Turn {turn} kept the standard admirably high.",
    "Those who travel to see {arena} often remark that the fighters here carry themselves differently.  Turn {turn} reminded me why that reputation is earned.",
    "I will spare you the preamble.  Turn {turn} in {arena} was worth watching, and I intend to tell you everything about it.",
    "The dust has settled on turn {turn} at {arena}.  For the warriors who fought and the crowds who watched, I present the account as I saw it.",
    "Turn {turn}.  {arena}.  The usual suspects, the unusual outcomes, and a few moments that will linger in the memory longer than the participants might prefer.",
    "If you missed turn {turn} in {arena}, I am sorry to say you missed something.  I will do my best to reconstruct it for you here.",
    "Here we are again, good people of {venue}.  Turn {turn} is complete and the warriors have retired to whatever it is seasoned fighters do when the fighting is done.",
]

_BLK_ELITE_OPENING_DEATH = [
    "Good people of {arena}, find your seats and a moment of quiet.  Turn {turn} gave us competition of the highest order, though not everyone who walked onto the sand walked back off of it, at least not immediately.",
    "Come in from the cold, friends of {venue}.  Turn {turn} is behind us, and I must report that death paid a visit, as it occasionally does even here.  The gods are already at work returning what was taken.",
    "The gates of {arena} have closed on turn {turn}.  The sand knows the truth of what happened here, and I intend to share it with you faithfully.  Some of it is not light reading.",
    "Settle in, good people.  Turn {turn} in {arena} was eventful in ways that go beyond mere sporting spectacle.  The Spire claimed someone today, though those who know this place understand that claiming is not quite the same as keeping.",
    "I have been reporting from {arena} for longer than I care to admit, and I still find myself pausing before writing this particular kind of newsletter.  Turn {turn} reminded me why.  Death came calling, briefly.",
    "The Spire is unforgiving.  Turn {turn} was a demonstration of exactly that.  Find your chair; I will explain what happened, and why the fallen will be back before you know it.",
    "Not every turn in {arena} ends with everyone standing.  Turn {turn} was a reminder that the fights here are not for decoration.  It is also a reminder that the compact of this place ensures no absence is permanent.",
    "Pour something before you read further.  Turn {turn} in {arena} was the kind of turn that requires it.  Someone died.  The gods are already inconvenienced on their behalf.",
    "I will not pretend that turn {turn} was anything other than what it was.  {arena} asked a great deal of its warriors today, and at least one gave everything, temporarily.",
    "Turn {turn} at {arena}.  The record will show what happened.  What the record cannot fully convey is that death, when it visits the Spire, has the decency to return what it borrows.",
    "Every warrior in {arena} knows the stakes.  Turn {turn} served as a reminder that they are not theoretical, even if the compact here softens what would elsewhere be permanent.",
    "Blood was spilled this turn in {arena}.  Warriors fell and did not rise from the sand under their own power.  The gods will see to their return, as they always have.  But the fall itself was real.",
]

_BLK_ELITE_CHAMP_NEW = [
    "The throne of {arena} belongs to a new occupant.  {champion} ended {prev_champion}'s reign this turn, and the Spire has a new face looking out from the seat of honor.",
    "Stop the record and note the turn. {champion} is the new Champion of {arena}.  {prev_champion} held the title for longer than most, but that tenure is now concluded.",
    "It was a championship fight and at the end of it, {champion} stood over {prev_champion} and accepted what {he} had been working toward.  {arena} has a new Champion.",
    "{prev_champion} has been dethroned.  {champion} did it convincingly enough that the crowd understood what had happened before the final call was made.",
    "The sand in {arena} has absorbed a title change.  {champion} defeated {prev_champion} and is now the Champion of this circuit.  The seat of honor has a new occupant.",
    "I was not certain who would take the championship this turn.  {champion} cleared up my uncertainty by defeating {prev_champion} and claiming what is now rightfully {his}.",
    "{champion} came to {arena} with one goal and accomplished it.  New Champion.  New record.  New chapter for the Spire.",
    "The crowd in {arena} wanted a fight.  {champion} gave them something better, a championship.  The title has changed hands.",
    "I have watched {champion} work toward this turn for some time.  The work is complete.  We have ourselves a new Champion.",
    "There is no gentle way to say it. {prev_champion} lost the title this turn.  {champion} took it, and there was little room for argument.",
    "{champion} is your new Champion of {arena}.  {prev_champion} will have a turn to reflect on what went wrong.  The title will not be waiting when the challenge comes again.",
    "The Spire reshuffles itself on a turn like this one.  {champion} has beaten {prev_champion} and taken the Championship.  The standings shift.  The record books are updated.",
    "Every champion ends eventually.  {prev_champion}'s reign ended at the hands of {champion}, in front of everyone who came to watch.  I have seen few cleaner title changes.",
    "Write this down.  {champion} is the new Champion of {arena} as of turn {turn}.  {prev_champion} knows how it happened.  The rest of us watched it happen.",
    "The record of {prev_champion} will still be read with respect.  {champion} simply added a loss to the end of it and stepped into the title that had been waiting.",
    "The throne is occupied by someone new.  {champion} put {prev_champion} down and moved into the seat of honor.  The Spire watches.  The circuit adjusts.",
    "{champion} took the title this turn, defeating {prev_champion}.  There are an awful lot of ambitious fighters who have been standing beneath that throne and looking upward.  Today, one of them reached it.",
    "If {prev_champion} would like to understand what happened, I would suggest reviewing the performance of {champion}, who is now the Champion of {arena} and apparently has been ready for this for quite some time.",
    "The champion's seat is warm with a new presence.  {champion} earned it by dispatching {prev_champion} in a fight that settled the question cleanly.",
    "{champion} has been building toward this.  Turn after turn, the record accumulated.  This turn, it culminated in a championship.",
    "The fight between {champion} and {prev_champion} ended only one way once it began.  {champion} is our new Champion, and {he} looks comfortable in the position.",
    "{champion} of {champ_team} took the title from {prev_champion} this turn.  {arena} has watched this career develop.  Now it watches a champion.",
]

_BLK_ELITE_CHAMP_INCUMBENT = [
    "{champion} of {champ_team} remains our Champion after {opponent} came calling for the throne.  The challenger gave it a respectable try, but {champion} put the matter to rest and settled {himself} right back into that seat of honor.  At {wins} victories, I suspect {he} has learned a thing or two about making {himself} difficult to move.",
    "The throne belongs to {champion} of {champ_team} for at least another turn.  {opponent} arrived with ambitions and departed with a loss.  At {wins} wins and counting, {champion} is showing no particular signs of relinquishing anything.",
    "{champion} of {champ_team} was tested this turn, and {he} passed.  {opponent} pushed the matter before {champion} brought things to a close.  The throne remains occupied, the record grows longer.",
    "There will not be a new champion today.  {champion} of {champ_team} saw to that, turning back {opponent} and making it look like the kind of thing {he} does without particular effort.  {wins} wins says {he} does.",
    "{opponent} came with a plan for taking the {arena} title.  {champion} of {champ_team} came with {wins} victories worth of experience in not allowing that to happen.  {champion} demonstrated the point clearly enough.",
    "The championship record now reads {wins} wins and counting, as {champion} of {champ_team} turned away {opponent}.  Some challengers leave the Spire surprised; {opponent} should not be among them.  The evidence was always there.",
    "{champion} of {champ_team} defended without particular drama, putting {opponent} away.  {wins} victories.  The seat of honor remains warm.",
    "Another turn, another successful defense.  {champion} of {champ_team} handled {opponent} and {wins} career wins suggest the throne is unlikely to change hands on any given afternoon through mere ambition alone.",
    "{opponent} gave {champion} of {champ_team} something to think about, though not for very long.  {champion} brought the situation under control and added another line to a record that stands at {wins} wins.",
    "The measure of a champion is what {he} does when properly tested.  {champion} of {champ_team} was properly tested by {opponent}, and {he} answered.  The record grows.  The throne holds.",
    "I have seen a fair number of fighters try to take that title from {champion} of {champ_team}.  The results have been consistent.  This turn, {opponent} was the latest to discover that consistency.",
    "{champion} of {champ_team} was challenged this turn, as champions always eventually are.  {opponent} arrived with fine intentions and a fighting record.  {champion} arrived with {wins} wins and more experience.  The experience showed.",
    "Turn {turn} produced no new champion.  {champion} of {champ_team} saw to that personally, finishing {opponent} and returning to the comfortable certainty of {wins} career victories.",
    "There are fighters in {arena} who study {champion} of {champ_team} the way scholars study difficult texts.  {opponent} studied well enough to push the matter.  Not quite well enough to take the title.",
    "{opponent} and {champion} of {champ_team} met this turn to determine who was better.  The answer was the same as it has been for {wins} fights. It was {champion}.",
    "The throne of {arena} has not moved.  {champion} of {champ_team} saw to that, dispatching {opponent}.  Challengers will keep arriving.  They always do.  At {wins} wins, {champion} appears to have made peace with that fact.",
    "What can I tell you about {champion} of {champ_team} that {his} record does not already say?  This turn {he} defeated {opponent}.  The total now stands at {wins} wins.  The throne remains occupied by the appropriate person.",
    "{champion} of {champ_team} did not linger over {opponent}.  The championship was retained, and {wins} wins went into the permanent record.  This is what sustained excellence looks like.",
    "I would tell you to watch the championship closely, but {champion} of {champ_team} rarely gives you time.  {opponent} received ample attention before discovering that {wins} wins is not an accident.",
    "The best challengers make the champion earn it.  {opponent} made {champion} of {champ_team} earn it.  At the end of that effort, {champion} had earned it.",
    "{champion} of {champ_team} has held that title for enough turns that some of the newer warriors here may have forgotten it was ever contested.  {opponent} reminded everyone that it was, then {champion} reminded everyone that it is not.",
    "Some champions hold the title through luck and circumstance.  {champion} of {champ_team}, standing at {wins} wins after turning away {opponent}, is not one of them.",
]

_BLK_ELITE_CHAMP_VACANT = [
    "The throne of {arena} remains empty this turn, as it has a way of doing when no warrior has yet pressed their claim to the satisfaction of the circuit.  This is temporary.  It always is.",
    "No champion was crowned in {arena} this turn.  The seat of honor waits, as it is perfectly willing to do, for a warrior capable of filling it.",
    "{arena} has no Champion at present.  The absence is notable and, I expect, temporary.  There are fighters here with the ambition to change that.",
    "The championship of {arena} is unclaimed.  This is the kind of situation that tends to resolve itself, often suddenly and at the expense of someone unprepared.",
    "Without a Champion to defend or a throne to challenge for, {arena} this turn was a matter of settling records and building toward the future.  The throne awaits.",
    "I can report that {arena} has no standing Champion as of turn {turn}.  I expect that state of affairs will not last.  It rarely does.",
    "The seat of honor in {arena} sits empty.  For now.  Judging by the ambitions on display this turn, that vacancy is unlikely to remain.",
    "No championship fights, no throne changes, no new ruler of {arena}.  Just very good fighters doing very serious work while the title waits for the right moment.",
    "The championship of {arena} is a question with no current answer.  Turn {turn} produced candidates, not yet champions.",
    "In the absence of a Champion, {arena} this turn was about the work of getting there.  Several fighters made compelling arguments for their own candidacy.",
    "The throne is empty and the circuit watches closely.  {arena} has never been short of warriors who believe they deserve to fill that vacancy.  Some of them are beginning to make the case.",
    "No Champion in {arena}.  Just a great deal of earnest ambition and the kind of fighting that suggests one will be crowned before long.",
]

_BLK_ELITE_DOMINANT = [
    "{warrior} made remarkably short work of {opponent}, and I imagine the poor soul is still wondering exactly what happened during that one very unpleasant exchange.",
    "{warrior} gave {opponent} very little time to express an opinion about the outcome, settling the matter efficiently and moving on with the calm of someone who had better things to do.",
    "I have seen fast fights.  {warrior} defeating {opponent} was among the faster ones.  {opponent} may have had a strategy.  There was not enough time to observe it.",
    "{warrior} took apart {opponent} with the efficiency of someone who found the entire exercise straightforward.  The crowd barely had time to settle before it was over.",
    "If {opponent} had a plan for defeating {warrior} of {team}, the opening minutes were not enough time to execute it.  {warrior} did not leave much room for planning.",
    "{warrior} swept through {opponent} so thoroughly that the final call surprised only those who had not been watching carefully.  Which was, mercifully, few.",
    "{opponent} entered the fight against {warrior} of {team} with a record.  {warrior} treated that record as an interesting piece of historical information rather than a deterrent.",
    "The fight between {warrior} and {opponent} was, strictly speaking, a fight.  In practice it was a demonstration, with {warrior} doing the demonstrating and {opponent} serving as a useful prop.",
    "{warrior} of {team} gave {opponent} an education in why some fighters are harder to beat than others.  The tuition was paid in full and quickly.",
    "{warrior} had little trouble with {opponent}.  Observers hoping for a prolonged affair were disappointed.  Observers appreciating decisive action were satisfied.",
    "Some fights are events.  {warrior} over {opponent} was more of a delivery, efficient, purposeful, and concluded before I had properly arranged my notes.",
    "{warrior} of {team} left no room for {opponent} to find a footing.  The fight was brief, decisive, and added another line to {warrior}'s record without adding any drama to speak of.",
    "The crowd leaned forward when {warrior} and {opponent} met.  They were still leaning when it ended, which was quite soon.  {warrior} did not require audience engagement to do the work.",
    "{warrior} handled {opponent} in the manner of someone handling a straightforward task.  Competently, without ceremony.",
    "If {opponent} left the sands with a lesson, it was probably this. {warrior} of {team} is faster than expected and more patient than {he} appears.  The combination is effective.",
    "{warrior} of {team} made {opponent} disappear in a way that left the crowd slightly bewildered by how complete the performance had been.",
    "There is a particular kind of defeat that arrives before the loser fully understands it is happening.  {opponent} experienced that kind this turn, courtesy of {warrior}.",
    "{warrior} ended things with {opponent} so quickly that several nearby spectators missed it entirely.  Those who did not witness it were spared a complicated explanation.",
    "I would not characterize the fight between {warrior} and {opponent} as competitive.  I would characterize it as informative.  {warrior} provided the information.  {opponent} received it.",
    "The match between {warrior} and {opponent} was over before I finished writing down both names.  I have since written them down completely and stand by my account.",
    "{opponent} discovered this turn that {warrior} of {team} does not require much time.  The record reflects this.",
    "{warrior} of {team} gave {opponent} the kind of afternoon that tends to prompt a serious reassessment of one's training regime.",
]

_BLK_ELITE_COMPELLING = [
    "{warrior} and {opponent} spent {minutes} minutes trying to settle their differences before {warrior} finally prevailed.  The crowd did not sit quietly for any of it.",
    "The fight between {warrior} and {opponent} lasted {minutes} minutes and earned every one of them.  {warrior} won, but not without being made to work for it.",
    "{warrior} of {team} edged {opponent} in a close affair that could easily have gone the other way.  I have replayed the final moments in my head several times and remain uncertain about the margin.",
    "Those who prefer their fights to resolve quickly were disappointed by {warrior} against {opponent}.  Those who came to see something memorable were not.  The {minutes} minutes were not wasted.",
    "{minutes} minutes between {warrior} and {opponent}, and when it was over, both fighters had given the crowd something worth keeping in memory.  {warrior} won.  {opponent} made winning difficult.",
    "The finest fights are the ones where both warriors make everyone watching remember why they came to {arena} in the first place.  {warrior} and {opponent} delivered that this turn.",
    "{warrior} prevailed over {opponent} after {minutes} minutes, but prevailed is perhaps too simple a word for what happened out there.  Both fighters asked and answered questions.  {warrior} answered more of them.",
    "If you needed evidence that {warrior} of {team} belongs in {arena}, the extended fight against {opponent} provided it.  Winning was one thing.  How {he} did it was another.",
    "{warrior} and {opponent} did not hurry.  They took {minutes} minutes, gave the crowd what they came to see, and then {warrior} found a way to end it.  This is what good fighting looks like.",
    "I have seen shorter fights and I have seen longer ones.  I am not certain I have seen one recently that held the crowd's attention as effectively as {warrior} against {opponent} over {minutes} minutes.",
    "The fight that {warrior} and {opponent} had this turn required patience from both fighters and everyone watching.  After {minutes} minutes, {warrior} provided the conclusion.  It was earned.",
    "{warrior} defeating {opponent} in {minutes} minutes was the kind of result that looks straightforward in the record and was anything but on the sand.  Several people around me stopped breathing during the later portions.",
    "You will not find a more contested fight in the records for turn {turn} than {warrior} against {opponent}.  What you will find is a winner in {warrior} and a loser who gave the winner a genuine problem to solve.",
    "{opponent} may have lost to {warrior} of {team}, but the crowd certainly appreciated the effort.  {minutes} minutes of fighting at that level is not something any of us take for granted.",
    "There were moments in the {warrior}-{opponent} fight where I was not certain who would prevail.  After {minutes} minutes, {warrior} answered the question.  {opponent} had made it a genuine question.",
    "{warrior} and {opponent} gave everyone in {arena} their money's worth.  {minutes} minutes is a long time to sustain that level of intensity.  Both fighters managed it.  Only one of them won.",
    "A long fight in {arena} draws a particular kind of attention from the crowd.  The fight between {warrior} and {opponent} drew exactly that.  {warrior} was the last one standing, and the crowd felt the distance between that outcome and a different one.",
    "{warrior} took {minutes} minutes to put {opponent} away, and every minute was worth watching.  This is the kind of performance that justifies the Spire's reputation.",
    "The margin between {warrior} and {opponent} after {minutes} minutes was narrower than the final record will suggest.  {warrior} won.  {opponent} made sure that winning was not simple.",
    "{warrior} of {team} survived a lengthy examination from {opponent} and came through with the victory.  Endure may be more accurate than prevail.  {He} endured well.",
    "If {opponent} is remembered for anything from turn {turn}, it should be for making {warrior} of {team} take {minutes} full minutes to finish the job.  The Spire applauds effort as well as results.",
    "{minutes} minutes.  That is how long {warrior} and {opponent} debated the matter before {warrior} put it to rest.  For the entirety of those minutes, nobody watching knew with certainty who would be right.",
]

_BLK_ELITE_UPSET = [
    "{warrior} continues to make {himself} difficult to ignore.  {opponent} entered their fight with considerably more experience and a fine record, but {warrior} refused to be impressed and handed {him} a loss.",
    "There will be veterans in {arena} who study what {warrior} did to {opponent} this turn.  {opponent} had more fights, more wins, and more time on these sands.  {warrior} had the result.",
    "{warrior} of {team} does not appear to have received the message that {opponent} was the more experienced fighter.  This is either ignorance or confidence.  The outcome suggests the latter.",
    "{warrior} is making a considerable nuisance of {himself}.  {opponent} arrived with the longer record.  The record has since been amended.",
    "I would tell those who lost this turn not to brood over it, though warriors have never been particularly good at taking that advice.  A bad afternoon is only permanent if you insist on carrying it into the next one.",
    "{warrior} handed {opponent} a loss and I suspect {opponent} did not see it coming with the speed that it arrived.  This is the hazard of underestimating the newer arrivals in {arena}.",
    "{warrior} is establishing {himself} as a fighter to be taken seriously before most people have taken {him} seriously.",
    "{opponent} has been fighting in {arena} long enough to have opinions about younger challengers.  {warrior} gave {him} some new ones.  They are the kind that require updating one's assumptions.",
    "Watch {warrior} of {team}.  The record is still being built, but the foundation is impressive, and the willingness to fight anyone in the building tends to produce long careers in this circuit.",
    "{warrior} over {opponent} was the upset of the turn, if not the most surprising thing I have ever written.  The talent was visible.  The timing was just earlier than anticipated.",
    "Some fighters arrive in {arena} already knowing they belong.  {warrior} of {team} is one of those fighters.  {opponent} has been here long enough to have had better afternoons.",
    "The veterans of {arena} will occasionally insist that experience is the decisive factor.  {warrior} over {opponent} this turn was a counterargument worth examining.",
    "{warrior} of {team} defeated {opponent} this turn in the kind of fight that adds quietly to a reputation.  No one expected it.  {warrior} seemed to.",
    "I do not know what {warrior} of {team} told {himself} before the fight with {opponent}.  Whatever it was, it worked.",
    "{opponent} has faced harder opponents.  {opponent} has faced fighters with worse records and no particular promise.  This turn, {opponent} faced {warrior} of {team} and discovered that the promise was better than the record suggested.",
    "{warrior} of {team} asked a question of {opponent} this turn, and {opponent} did not have a satisfying answer.",
    "The names in {arena} that everyone already knows are not always the names doing the most interesting work.  {warrior} of {team} is making a case for attention.",
    "{warrior} over {opponent}.  I have written more dramatic sentences.  I have not always written sentences that told more about the future of {arena} than this one does.",
    "There are a certain number of fights each turn that change what I believe about the Spire's future.  {warrior} defeating {opponent} was one of them.",
    "{opponent} has a record that commands respect.  {warrior} of {team} respected the record all the way through the fight before adding a loss to the end of it.",
    "The arena has a way of humbling everyone eventually, which is precisely why no one should become too proud when fortune happens to smile.  Ask {opponent} about turn {turn}.",
    "{warrior} of {team} is one of those fighters who refuses to acknowledge that there is a hierarchy until {he} has personally tested it.  {opponent} was this turn's test.  The results were instructive.",
]

_BLK_ELITE_STANDINGS = [
    "The larger picture remains interesting as well.  {team} sits atop the standings, with {team2} close enough behind to keep things from becoming comfortable for anyone.",
    "{team} leads {arena} with the kind of margin that looks significant from a distance and somewhat less significant from where {team2} is standing.",
    "In the team standings, {team} retains the top position.  This is a fact I expect to continue reporting until some other team makes it incorrect, and several of them appear interested in doing so.",
    "{team} atop the standings.  {team2} in pursuit.  The Spire has seen this configuration before.  It tends to resolve itself in dramatic fashion eventually.",
    "The standings in {arena} have {team} leading, {team2} watching closely, and everyone else calculating distances.  It is a familiar arrangement that is never as stable as it appears.",
    "{team} at the top.  {team2} close behind.  Watching carefully and saying nothing, everyone else with ambitions they have not yet declared.",
    "{team} leads the circuit.  {team2} is the reason they cannot relax about it.  The remainder of the field is the reason {team2} cannot relax either.",
    "The broad view of {arena} this turn has {team} in front, {team2} pressing, and a field that shows enough variety to make the coming turns genuinely uncertain.",
    "In the standings, {team} remains ahead.  This is the kind of sentence that sounds like good news and is, while also being the kind of sentence that has a way of changing.",
    "The team records across {arena} this turn tell a consistent story with a few notable exceptions.  {team} leads.  {team2} follows.  The exceptions are working on closing the distance.",
    "Standing at the top of {arena} is {team}, which is where they have been long enough to make it look comfortable.  {team2} would like to change their view of that comfort.",
    "The circuit stands like this. {team} holds the advantage.  {team2} is close enough to matter.  The remaining teams are having various degrees of the turn they deserved.",
    "{team} at the top is not a surprise.  What might be a surprise is how closely {team2} is watching, and how much closer they have gotten in recent turns.",
    "I will tell you what the standings say and what they do not say.  They say {team} leads and {team2} follows.  They do not say for how much longer.",
    "For those tracking the broader competition, {team} leads, {team2} is positioned to be interesting, and the field has not yet given up, which is encouraging for the sport.",
    "The comfortable position in {arena}'s standings belongs to {team}.  Comfort is, of course, a relative term in a place where everyone is trying to take what someone else has.",
    "The standings in {arena} have {team} first, {team2} second, everyone else calculating.  The turn-over-turn change is the interesting part.",
    "Head to toe in {arena}, {team} at the summit, {team2} on the slope, and the field scattered below in configurations that will shift again before I finish this report.",
    "The current order in {arena} has {team} leading.  {team2} has opinions about this and has been expressing them through their fight record.  The opinions are gaining traction.",
    "From the top of the standings to the bottom, {arena} is producing the kind of competition that makes this circuit worth following.  {team} is currently at the top.  {team2} finds this temporary.",
    "The team with the best view of {arena} right now is {team}, though {team2} is close enough to have nearly the same view, and neither of them is entirely comfortable with that arrangement.",
    "{team} leads the standings in {arena}.  I expect this is news to no one who has been paying attention, and I expect the current margin will be different again within a turn or two.",
]

_BLK_ELITE_CLOSING = [
    "Until next time, tend your bruises, sharpen what needs sharpening, and try not to pick fights in the tavern that you would be embarrassed to have recorded in this newsletter.  And {champion}, do enjoy the throne while you have it.  There are an awful lot of ambitious people standing beneath it and looking upward.",
    "The Spire does not forgive complacency, and it does not reward self-pity.  It simply waits, and then it opens the doors again.  I will be here when they do.  - {byline}",
    "That is turn {turn} at {arena}.  I will see you next time, assuming the circuit cooperates and the fighters do not do anything I cannot report with my professional reputation intact.",
    "The sands have been raked, the record has been updated, and {arena} is already thinking about turn {next_turn}.  I recommend you do the same.  - {byline}",
    "Tend to what needs tending.  The Spire will be here when you return.  So, regrettably, will I.  - {byline}",
    "To those who won this turn, well done, though the Spire has a way of adjusting outcomes it considers premature.  To those who lost, the record is not finished.  - {byline}",
    "I will say this about {venue}: it does not forgive, it does not forget, and it does not give trophies for trying.  It does, however, keep accurate records.  I should know.  - {byline}",
    "Until turn {next_turn}, good people of {arena}.  May your training be productive, your weapons remain sharp, and your instincts prove better than whatever plan the other fighter had.  - {byline}",
    "The chronicle of {arena} is never quite finished, but this turn's chapter is.  I remain, as always, at my post.  - {byline}",
    "Good night, good people of {venue}.  The records are current, the fights have been noted, and {arena} is already looking forward with that particular expression it has when it knows something the rest of us do not.  - {byline}",
    "That is the news from {arena}.  It was not all pleasant news, but it was accurate news, which I have always found more valuable.  - {byline}",
    "To the winners this turn: enjoy it.  To the losers: the sand has been raked over.  Start again.  - {byline}",
    "Every turn in {arena} is both an ending and a beginning.  Turn {turn} has ended.  The beginning of turn {next_turn} is already underway in training rooms and sleep-deprived minds across this circuit.  - {byline}",
    "The chronicle of {venue} continues.  I will be here for the next chapter.  Whether you are here to read it is, of course, up to you.  - {byline}",
    "Some records are made to be broken.  Some reputations are made to be tested.  {arena} provides the occasions for both.  Turn {next_turn} will offer more of each.  - {byline}",
    "Until next we meet at {venue}. Fight well, plan carefully, and remember that everyone else in {arena} is doing exactly the same thing and hoping you are not.  - {byline}",
    "I conclude, as I always do, with the observation that {arena} is a more interesting place than it has any right to be.  This is not a complaint.  - {byline}",
    "The Spire stands.  The record grows.  I remain your correspondent.  - {byline}",
    "What more can be said about a place like {arena}?  A great deal, as it turns out.  But it will have to wait until turn {next_turn}.  - {byline}",
    "That will do for turn {turn}.  The fighters are resting, or should be.  I am writing, which is what I do.  See you next time.  - {byline}",
    "My report is complete.  {arena}'s story is not.  That is the nature of the Spire, it keeps moving, turn after turn, with or without our attention.  I prefer to give it attention.  - {byline}",
    "Until the next turn opens the gates of {arena} again. Take care of yourselves, take better care of your weapons, and do not mistake the silence between turns for calm.  It never is.  - {byline}",
]

# ---------------------------------------------------------------------------
# SOUL SPIRE (VETERAN ARENA) NARRATIVE POOLS
# ---------------------------------------------------------------------------

_BLK_VET_BYLINES = [
    "Varek Duskhollow, The Soul's Record",
    "Maren Ghostveil, Chronicle of the Departed",
    "Solen Ashwick, From the Realm Beyond",
    "Dara Wraithstone, The Undying Record",
    "Theron Pallmere, Voices of the Fallen",
    "Caelan Spireveil, The Soul Spire Dispatch",
    "Lyria Duskvane, Scribe of the Afterworld",
    "Ossian Coldreach, The Departed Chronicle",
]

_BLK_VET_OPENING = [
    "Welcome back to {arena}, where the already-dead prove they still have something left worth proving.",
    "Another turn in the realm beyond, where warriors who have already crossed over discover that dying once was apparently not enough.",
    "Good souls of {arena}, settle in.  Turn {turn} has concluded, and no one has managed to die twice today, a modest accomplishment for a place like this.",
    "{arena} does not ask whether you deserve to be here.  It already knows the answer.  It just wants to see what you do about it.",
    "Turn {turn} at {arena}.  The souls have fought, the record has been updated, and the realm beyond has rendered its judgment.",
    "Somewhere between life and whatever comes next, there is {arena}.  Turn {turn} has reminded everyone why the souls here have not moved on.",
    "Death, it turns out, is not the end.  {arena} is what comes after the end, and turn {turn} was proof that what comes after can still draw blood.",
    "The gates of {arena} do not open for just anyone.  You have to die first.  Turn {turn} tested whether those assembled had anything worth testing.",
    "Not everyone walks away from {arena}.  Technically, no one here walked away from anywhere.  But the fights go on, and turn {turn} was no exception.",
    "The souls of {arena} have fought before they arrived here and have kept fighting since.  Turn {turn} was another chapter in that long and restless story.",
    "I have been chronicling {arena} long enough to stop being surprised by anything that happens here.  Turn {turn} tested that resolve.",
    "The realm beyond remembers every warrior who arrives.  Turn {turn} gave it a few more memories worth keeping.",
    "Warriors come to {arena} through one door and cannot leave through any other.  What happens between arrival and departure is turn {turn}.",
    "Death was supposed to be the finish line.  The warriors of {arena} discovered it was only the beginning.  Turn {turn} continued the argument.",
    "A quieter turn at {arena} today, if quiet can even be applied to a place where the dead come to fight.  No permanent departures.  The realm is satisfied, for now.",
    "{arena} has been here longer than any of the warriors who fight in it.  It will be here long after they move on.  Turn {turn} was another small contribution to a very long record.",
    "Every warrior in {arena} earned their place here the hard way.  Turn {turn} asked them to earn it again.",
    "Welcome to {arena}, where the currency is blood, the stakes are pride, and the participants have already settled the matter of mortality.  Turn {turn} is concluded.",
    "The souls fight on.  They always have.  Turn {turn} at {arena} was more of the same, which is not a complaint.",
    "Here in {arena}, the results matter precisely because the warriors have already lost everything else.  Turn {turn} showed they have not lost the will.",
    "Another turn, another reckoning.  {arena} does not ask its warriors if they are ready.  It never has.",
    "The dead do not rest in {arena}.  They compete.  Turn {turn} confirmed this.",
]

_BLK_VET_CHAMP_NEW = [
    "A new name atop {arena}.  {champion} of {champ_team} has taken the title from {prev_champion}, which required effort of the kind that the soul realm tends to remember.",
    "The throne of {arena} has a new occupant.  {champion} of {champ_team} put the matter of succession to rest against {prev_champion}.",
    "{prev_champion} held the title for as long as {prev_champion} could.  {champion} of {champ_team} decided this turn that long enough was long enough.",
    "Among the dead, the question of who reigns is still very much alive.  {champion} of {champ_team} answered it this turn.",
    "It takes something to become champion of {arena}.  It takes more to take the title from someone who already holds it.  {champion} of {champ_team} had enough of both.",
    "The record at {arena} has been updated.  {champion} of {champ_team} is at the top of it.  {prev_champion} is not.",
    "The soul realm has crowned a new champion. {champion} of {champ_team}.  The Soul Keeper has noted it.  {prev_champion} has certainly noted it.",
    "{prev_champion} learned this turn what many warriors in {arena} eventually learn. The title is borrowed, not owned.  {champion} of {champ_team} collected on that understanding.",
    "If you were watching closely, you could see the moment the title changed hands.  {champion} of {champ_team} saw it clearly enough.  {prev_champion} felt it.",
    "New champion at {arena}.  {champion} of {champ_team}.  The soul realm adjusts to this information with the equanimity it applies to all things.",
    "In the realm of the dead, even titles die and are reborn.  {prev_champion}'s reign ended this turn.  {champion} of {champ_team}'s has begun.",
    "The warriors of {arena} have a new standard to measure themselves against.  It is called {champion}, and it represents {champ_team}.",
    "{champion} of {champ_team} arrived at {arena} carrying a record and a reputation.  Both have grown considerably after this turn.",
    "There is no ceremony at the gate of {arena}.  The title simply passes.  {champion} of {champ_team} holds it now.  {prev_champion} will want it back.",
    "Among all the results from turn {turn}, the one that will be discussed longest is {champion} of {champ_team} defeating {prev_champion} for the championship of {arena}.",
    "{prev_champion} gave {champion} of {champ_team} every reason to doubt.  {champion} declined to do so.",
    "The soul realm has changed its champion.  I have recorded it, as I record everything here.  {champion} of {champ_team} has the title.  What {he} does with it will be the story from here.",
    "Champions of {arena} are not remembered for holding the title.  They are remembered for what they did with it.  {champion} of {champ_team} has just begun that story.",
    "Some moments in {arena} belong to the warriors.  Some belong to the realm itself.  {champion} of {champ_team} taking the title from {prev_champion} belonged to both.",
    "The throne of {arena} is never empty for long.  {champion} of {champ_team} has made sure of that.",
    "{prev_champion} fought well enough to have held the title for as long as {prev_champion} did.  {champion} of {champ_team} fought better.",
    "The soul realm keeps its records carefully.  The newest entry names {champion} of {champ_team} as champion of {arena}.",
]

_BLK_VET_CHAMP_INCUMBENT = [
    "{champion} of {champ_team} holds.  This should surprise no one who has watched {him} fight, but the soul realm produces surprises at irregular intervals.",
    "The champion of {arena} remains {champion} of {champ_team}.  {opponent} came calling.  The answer was no.",
    "At {wins} victories, {champion} of {champ_team} has built something in {arena} that resists the usual forces of entropy.  {opponent} was the latest to test that resistance.",
    "{opponent} brought a real challenge to {champion} of {champ_team} this turn.  {champion} acknowledged the effort by winning anyway.",
    "The soul realm has seen challengers before.  {champion} of {champ_team} has seen more of them than most.  {opponent} joins the list.",
    "Every turn someone in {arena} believes they can end {champion} of {champ_team}'s reign.  Every turn, {champion} of {champ_team} provides the answer personally.",
    "{champion} of {champ_team}.  Still champion.  Still {champ_team}.  Still not interested in losing.",
    "The title of champion of {arena} is, according to the record, the exclusive property of {champion} of {champ_team}.  {opponent} inquired about it this turn.  {champion} was not selling.",
    "A {wins}-win record and a championship.  {champion} of {champ_team} has assembled a collection in {arena} that {opponent} could not dismantle in a single turn.",
    "{champion} of {champ_team} is not the loudest warrior in {arena}.  {He} is the most persistent, which in the soul realm is worth considerably more.",
    "What makes a champion in the realm of the dead?  The same thing that makes one anywhere else. A refusal to lose when it counts most.  {champion} of {champ_team} demonstrated this again.",
    "{opponent} arrived with a plan.  {champion} of {champ_team} arrived with {wins} reasons the plan would not work.  One of them was sufficient.",
    "The Soul Keeper has watched {champion} of {champ_team} fight many times.  They are no longer surprised by the outcome.  That is the highest form of reputation.",
    "In the soul realm, reputations are built over many turns and many tests.  {champion} of {champ_team}'s reputation survived another one.",
    "{champion} of {champ_team} holds the championship of {arena} the way the most tenacious souls hold things. Tightly, and without apology.",
    "I have watched many challengers approach {champion} of {champ_team}.  I have watched all of them leave without the title.",
    "Turn {turn} added another line to {champion}'s record at {arena}.  The lines accumulate.  {opponent} contributed to the latest one.",
    "The soul realm offers no guarantees.  {champion} of {champ_team} does not need them.",
    "There are warriors in {arena} who believe the championship is within reach.  {opponent} believed it this turn.  {champion} of {champ_team} provided a careful correction.",
    "{champion} of {champ_team} has made defending the title look routine.  {opponent} was another reminder that routine and easy are not the same thing.",
    "The champion fights, and the realm records it.  {champion} of {champ_team} has given the realm much to record.",
    "At {wins} victories, {champion} of {champ_team} is either the hardest warrior in {arena} to beat or the most determined.  In {arena}, the difference does not matter.",
]

_BLK_VET_CHAMP_VACANT = [
    "The championship of {arena} sits unclaimed.  The soul realm is patient.  Someone will fill the vacancy.  Someone always does.",
    "No champion in {arena} this turn.  The throne is empty, which in the realm beyond carries a particular weight.",
    "The title of champion of {arena} is, at the moment, unoccupied.  This will not last.  The soul realm does not leave things empty for long.",
    "In the absence of a named champion, {arena} continues.  The fights go on.  The record grows.  The title waits.",
    "Even without a champion, {arena} is not without purpose.  Every warrior here is building toward something.  The throne merely confirms who has built the most.",
    "The realm beyond has no champion at the moment.  I have recorded this fact with the same attention I give all facts, which is considerable.",
    "Someone in {arena} will be champion before long.  Turn {turn} has not yet produced the name, but the competition for the right to be that name is ongoing.",
    "An empty championship is an invitation.  {arena} has issued it.  The warriors here are reading it carefully.",
    "The soul realm keeps its own counsel on most things.  On the matter of the vacant championship, it is simply waiting to see who answers.",
    "Without a champion, {arena} is a question without an answer.  The answers are being competed for.  Turn {turn} moved some of the candidates closer.",
    "The championship of {arena} belongs to no one right now.  This is a temporary condition.  Everything in {arena} is temporary, even the permanent things.",
    "I have seen {arena} without a champion before.  I have also seen what happens when one finally emerges.  The waiting, it turns out, is part of the story.",
]

_BLK_VET_DOMINANT = [
    "{warrior} handled {opponent} with the efficiency of a soul who has had a great deal of practice at this sort of thing.",
    "The fight between {warrior} and {opponent} lasted {minutes} minute.  {opponent} will have time to reflect on the brevity.",
    "{warrior} of {team} made {opponent} look like someone who was not quite ready for {arena}.  The soul realm will give {opponent} time to get ready.",
    "Some fights in {arena} are examinations.  {warrior} over {opponent} was more of a reminder, of what this place is and who belongs here.",
    "{opponent} lasted {minutes} minute against {warrior}.  In the soul realm, a minute is a long time to wish you were somewhere else.",
    "{warrior} did not give {opponent} much to work with.  {opponent} did not make much of what little there was.",
    "The realm beyond has seen faster fights than {warrior} over {opponent}.  Not many, but some.  The record stands regardless.",
    "{warrior} of {team} settled the matter of {opponent} in {minutes} minute.  Settled is the precise word. There was nothing left unsettled at the end.",
    "I have described many decisive fights in {arena}.  {warrior} over {opponent} belongs in the same sentence as most of them.",
    "{warrior} came, fought {opponent}, and won.  The entire sequence took {minutes} minute.  The soul realm has noted it and moved on.",
    "If {opponent} came to {arena} with questions about {warrior}, turn {turn} answered all of them.  The answers were unfavorable.",
    "Among the quick outcomes this turn, {warrior} defeating {opponent} in {minutes} minute stands out for its completeness.",
    "The dead fight on in {arena}.  Some of them fight better than others.  {warrior} and {opponent} clarified which category each belongs to.",
    "{warrior} of {team} was the first to move and the last to need to.  {opponent} learned the distance between those two things.",
    "There are warriors in {arena} who are still finding their footing in the soul realm.  {warrior} is not among them.  {opponent} may still be.",
    "{warrior} over {opponent}.  {minutes} minute.  The soul realm has recorded faster.  It has also recorded worse.",
    "Quick fights in {arena} are not unusual.  {warrior} over {opponent} was quicker than most and more complete than several.",
    "The record at {arena} is full of fights like {warrior} over {opponent}, short, decisive, and contributing to the longer story of who belongs here.",
    "{warrior} of {team} told {opponent} everything worth knowing about fighting in {arena}.  {warrior} told it with actions rather than words, over {minutes} minute.",
    "{opponent} is not the first warrior in {arena} to discover that experience in the soul realm counts for more than it appears to.  {warrior} has a great deal of it.",
    "Fast fights are part of {arena}'s character.  {warrior} over {opponent} was among the faster ones this turn, which is saying something given the company.",
    "The soul realm does not add commentary to its results.  It leaves that to me.  {warrior} over {opponent}. Decisive, brief, and noted.",
]

_BLK_VET_COMPELLING = [
    "{warrior} and {opponent} gave {arena} {minutes} minutes of the kind of fighting that reminds everyone why the soul realm keeps its warriors here.",
    "The dead are stubborn.  {warrior} and {opponent} proved this over {minutes} minutes before {warrior} finally proved it slightly more.",
    "{warrior} prevailed over {opponent} in {minutes} minutes, though prevailed may be too simple a word for what actually happened out there.",
    "Some fights in {arena} end.  Others conclude.  {warrior} over {opponent} after {minutes} minutes was the latter.",
    "The soul realm witnessed something worth witnessing this turn. {warrior} and {opponent} going {minutes} minutes before {warrior} found the answer.",
    "{warrior} and {opponent} spent {minutes} minutes answering questions neither of them had asked before the fight.  {warrior} answered more of them.",
    "If {opponent} is remembered for anything from turn {turn}, it should be for making {warrior} of {team} take {minutes} full minutes to close the argument.",
    "In {arena}, long fights carry their own meaning.  {warrior} and {opponent} produced one, {minutes} minutes of it, and {warrior} was the one still standing.",
    "The crowd at {arena} came for fights.  {warrior} and {opponent} gave them a fight, which is a more specific and valuable thing.  {minutes} minutes.  {warrior} standing.",
    "{minutes} minutes in {arena} is a long time to remain in question.  {warrior} and {opponent} remained in question for all of them, and then {warrior} resolved it.",
    "Close fights in the soul realm carry more weight than close fights elsewhere.  Everyone here knows what it costs to lose.  {warrior} and {opponent} knew it too.",
    "{warrior} of {team} edged {opponent} in a contest that {minutes} minutes could not resolve cleanly, but {warrior} resolved it anyway.",
    "The soul realm does not forget fights like {warrior} over {opponent}.  {minutes} minutes, both warriors at their best, one outcome.  The record reflects it.",
    "After {minutes} minutes, {warrior} defeated {opponent} in the kind of fight that {arena} was built to produce.  Both warriors contributed.  Only one won.",
    "I have watched many fights in {arena}.  {warrior} and {opponent} over {minutes} minutes belongs among the ones worth watching twice.",
    "{warrior} and {opponent} made {minutes} minutes feel like the right amount of time.  Neither wasted any of it.  {warrior} used it marginally better.",
    "The longer the fight, the more you learn about the fighters.  {warrior} and {opponent} fought long enough for the soul realm to learn quite a lot.",
    "{opponent} made every minute of those {minutes} minutes difficult for {warrior} of {team}.  {warrior} made the last one more difficult for {opponent}.",
    "Not all of {arena}'s stories are told quickly.  {warrior} and {opponent} told theirs over {minutes} minutes, and the ending was worth the time.",
    "{warrior} of {team} won.  {opponent} made sure winning took {minutes} minutes.  In {arena}, making someone take {minutes} minutes to beat you is its own kind of statement.",
    "{minutes} minutes.  That is what {warrior} and {opponent} required to settle the matter.  The soul realm observed it without comment, as it does.  I am less restrained.",
    "The difference between {warrior} and {opponent} after {minutes} minutes was narrower than the final record will suggest.  {warrior} won.  {opponent} made {warrior} earn it.",
]

_BLK_VET_UPSET = [
    "The soul realm does not honor records the way the living do.  {warrior} reminded everyone of this by defeating {opponent}, who had more wins and presumably more certainty.",
    "{opponent} arrived at turn {turn} with a stronger record than {warrior}.  {warrior} arrived with the fight itself, which proved sufficient.",
    "In {arena}, the past is carried differently than it is elsewhere.  {warrior} proved this by defeating {opponent} despite what the record suggested.",
    "Records in {arena} are evidence, not prophecy.  {warrior} of {team} knew the difference this turn.  {opponent} is learning it.",
    "The soul realm has a way of humbling what the record builds up.  {opponent} had the better record.  {warrior} had the better turn.",
    "There are no guarantees in {arena}.  {opponent}'s record suggested one.  {warrior} declined to honor the suggestion.",
    "{warrior} was not supposed to win this turn.  The record said so clearly.  {warrior} is not a careful reader of records.",
    "The outcome between {warrior} and {opponent} will be filed under upsets in {arena}'s record.  The record does not explain how.  I will offer one. {warrior} was simply better today.",
    "Victories like {warrior}'s over {opponent} are why the soul realm keeps its ledger carefully.  The expected and the actual diverge here more often than they should.",
    "{opponent} had more experience and a stronger record.  {warrior} had the result.  In {arena}, the result is the only number that changes.",
    "The soul realm makes no promises about outcomes.  {warrior} of {team} reminded {opponent} of this directly.",
    "I noted {opponent}'s record before the fight.  I noted {warrior}'s outcome after it.  The distance between the two is what the soul realm calls a turn.",
    "{warrior} of {team} has added a significant line to {his} record this turn, a victory over {opponent} that the numbers before the fight did not predict.",
    "In the realm beyond, warriors have already surrendered more than a record.  {warrior} used that freedom to defeat {opponent} without being weighed down by expectation.",
    "The result reads {warrior} over {opponent}.  The record of wins before the fight pointed the other direction.  {arena} has reconciled the contradiction.  {warrior} benefited.",
    "{opponent} is not the first warrior in {arena} to discover that records are not armor.  {warrior} made the discovery vivid.",
    "Upsets in {arena} carry a particular resonance.  The warriors here have already surprised death once.  A surprising result feels appropriate.",
    "{warrior} has earned a different kind of respect in {arena} after this turn, the kind that comes from defeating someone who, by the numbers, should not have been defeated.",
    "The soul realm has no favorites.  {opponent} may have believed otherwise.  {warrior} provided a correction.",
    "Some fights in {arena} end where they were expected to end.  {warrior} over {opponent} was not among them.  The soul realm noted the deviation with its usual calm.",
    "{warrior} of {team} used turn {turn} to demonstrate that the fight matters more than the record of fights.  {opponent} will be reviewing both.",
    "What {warrior} did to {opponent} this turn will be discussed in {arena} for some time.  The record said one thing.  The fight said another.  The soul realm keeps both.",
]

_BLK_VET_STANDINGS = [
    "The standings in {arena} have {team} in front.  The soul realm neither confirms nor denies whether this is where {team} belongs.  The record does.",
    "{team} holds the advantage at {arena}.  {team2} is close enough to maintain ambitions.  The rest of the field is making calculations.",
    "In {arena}, the standings reflect more than wins.  They reflect which souls have best adapted to the realm beyond.  {team} has adapted well.",
    "The table at {arena} shows {team} at the top.  The soul realm has no opinion about this.  I, however, have several.",
    "{team} leads the field at {arena}.  How long that remains true is the question that makes turn {next_turn} worth watching.",
    "The standings at {arena} favor {team} this turn.  {team2} is watching closely, as it should be.",
    "Among all the information the soul realm keeps, the current standings may be the most contested.  {team} leads.  Not everyone agrees with the arrangement.",
    "The record at {arena} shows {team} ahead.  The souls competing here do not always read the record.  {team2} certainly has.",
    "{team} sits at the top of the standings in {arena}.  The position was earned.  Whether it will be kept is a matter for future turns.",
    "The soul realm has no preference for who leads at {arena}.  The standings simply reflect what has happened.  {team} has made more of what has happened than anyone else.",
    "At {arena}, the standings carry weight, perhaps more than anywhere else, because the warriors here have already surrendered everything lighter.  {team} carries the most.",
    "The top of the standings at {arena} belongs to {team}.  {team2} is positioned to argue the point.",
    "In the realm beyond, the accounting is very accurate.  The standings show it. {team} leads, {team2} follows, and the competition between them is very much alive, which is more than can be said for the warriors involved.",
    "{team} above {team2} in the standings.  The soul realm does not explain why.  The record of fights does, turn by turn.",
    "The standings at {arena} are a portrait of persistence.  {team} is currently the most persistent.",
    "The upper portion of {arena}'s standings belongs to {team}.  The lower portion is more complicated.  This is usually how it goes.",
    "The souls of {arena} compete for standing in the realm beyond.  {team} currently has more of it than anyone else.",
    "{team} leads at {arena}.  Turn {next_turn} will ask whether that lead holds.  {team2} will be among those doing the asking.",
    "The dead keep careful records.  The standings at {arena} reflect them. {team} at the top, {team2} in pursuit, and the rest trying to close the gap.",
    "Among everything recorded about {arena}, the standings tell the clearest story.  {team} is writing the best chapter at the moment.",
    "The realm beyond grades on results, not intention.  {team}'s results have placed them at the top of {arena}'s standings.  The intention of {team2} is to change that.",
    "The standings at {arena} are, as always, both a summary and a challenge.  {team} has received the summary.  {team2} has accepted the challenge.",
]

_BLK_VET_CLOSING = [
    "Until turn {next_turn}, souls of {arena}.  The realm beyond is already preparing what comes next.  I recommend you do the same.  - {byline}",
    "That concludes the record of turn {turn} at {arena}.  The gates remain open.  The fights continue.  I will be here when they do.  - {byline}",
    "The soul realm is patient.  It has waited this long for all of you, and it will wait for turn {next_turn}.  Train accordingly.  - {byline}",
    "The chronicle of {arena} continues.  I am its keeper, for whatever that is worth in the realm beyond.  I will see you at turn {next_turn}.  - {byline}",
    "The dead fight on.  They always have.  They always will.  Turn {turn} is concluded.  Turn {next_turn} is already waiting.  - {byline}",
    "Until the gates of {arena} open again. Tend to what can be tended, sharpen what can be sharpened, and remember that in the soul realm there are no excuses, only records.  - {byline}",
    "I have recorded everything worth recording about turn {turn}.  The soul realm has filed it.  I will see you at turn {next_turn} with the same attention to detail and the same deep ambivalence about what I observe.  - {byline}",
    "Turn {turn} is history.  In {arena}, history is the only currency that does not depreciate.  Spend turn {next_turn} adding to it.  - {byline}",
    "The realm beyond makes no promises about what comes next.  But it has never failed to produce a turn {next_turn}.  I will be there.  - {byline}",
    "Good night, souls of {arena}.  The fighting is done for now.  The thinking about the next fight has already begun.  That is the nature of this place.  - {byline}",
    "Every soul in {arena} arrived through one door.  The record of what they do here is mine to keep.  Turn {turn} has been kept.  - {byline}",
    "The soul realm does not offer rest.  It offers turns.  Turn {turn} is over.  Turn {next_turn} is the offer.  - {byline}",
    "The chronicle of {arena} does not pause between turns.  It waits, which is different.  I wait with it.  Until turn {next_turn}.  - {byline}",
    "Some would say it is strange to report on a place like {arena}.  I would say it is the most honest reporting there is.  The dead compete without pretense.  I write it down.  - {byline}",
    "Turn {turn} at {arena}. Concluded, recorded, filed.  The soul realm has moved on.  The warriors should too.  - {byline}",
    "To those who won this turn, the realm has noted it.  To those who lost, the realm has noted that too.  It notes everything.  So do I.  - {byline}",
    "The gates of {arena} have closed on turn {turn}.  They will open for turn {next_turn}.  This is the cycle.  You know the cycle.  - {byline}",
    "I will not pretend that {arena} is a comforting place to spend eternity.  But it is an honest one.  Turn {turn} was proof of that.  - {byline}",
    "The soul realm asks one thing of its warriors, that they keep fighting.  Turn {turn} confirmed that they are.  So it continues.  - {byline}",
    "That is the record of turn {turn} from the realm beyond.  The realm sends its regards, which in this context means it will see you at turn {next_turn}.  - {byline}",
    "Until next time, souls of {arena}.  What was tested this turn will be tested differently at turn {next_turn}.  Prepare accordingly.  - {byline}",
    "The chronicle ends here, for now.  {arena} does not end.  Neither do its warriors.  That is the point of this place.  - {byline}",
]

# ---------------------------------------------------------------------------
# ADDITIONAL NARRATIVE POOLS - weave into the spy-report body
# ---------------------------------------------------------------------------

_BLK_WARRIOR_RISER = [
    "Hey everybody, keep your eye on {warrior} of {team}.  After dispatching {opponent} this turn, this fighter sits at {points} recognition and is moving fast.  Rival managers are adjusting their schedules accordingly.",
    "Watch out for {warrior} of {team}, who turned {opponent} into a stepping stone this turn and climbed to {points} recognition doing it.  That performance won't be forgotten by the bookmakers.",
    "Word travels fast in {arena}, and right now it's all about {warrior} of {team}.  They made {opponent} look thoroughly outmatched and now sit at {points} recognition.  The kind of turn that changes how rivals plan.",
    "The stands were buzzing after {warrior} of {team} finished with {opponent}.  Efficient, controlled, and effective.  {points} recognition now, and the number is still climbing.",
    "If you weren't watching {warrior} of {team} before, you should have been.  They dismantled {opponent} this turn and now carry {points} recognition.  Rival managers are circling this name with a worried quill.",
    "There's a name to write down. {warrior} of {team}.  After running through {opponent} this turn, they've climbed to {points} recognition and show no signs of slowing.",
    "The crowd got what they wanted when {warrior} stepped out and made quick work of {opponent}.  Now at {points} recognition, this fighter is becoming a problem for opponents at this level.",
    "No debate after {warrior} of {team} handled {opponent} this turn.  Sitting at {points} recognition, this one is simple math and bad news for whoever faces them next.",
    "Quietly and efficiently, {warrior} of {team} put {opponent} down and climbed to {points} recognition.  The quiet ones are always the ones you didn't adjust for in time.",
    "Someone's going to challenge {warrior} of {team} soon and discover they've made a bad decision.  After handling {opponent} this turn and reaching {points} recognition, the gap between reputation and reality has officially closed.",
    "{warrior} is collecting victories and recognition with equal consistency.  The rise in the standings reflects preparation that appears to have no end in sight.",
    "The trajectory of {warrior}'s career is pointing upward, and nothing is changing that direction.  {Points} recognition this turn keeps the momentum rolling.",
    "{warrior} has found a gear that most warriors never locate.  The consistent rise in standing and recognition suggests {he} is here to stay at the top.",
    "What {warrior} is building through sustained performance is a reputation that will outlast individual turns.  The {points} recognition earned this turn is just the latest evidence.",
    "{warrior}'s climb through the standings has attracted admirers and rivals in equal measure.  Both groups are watching to see how far this one goes.",
    "The numbers tell {warrior}'s story: rising standing, accumulating recognition, building reputation.  The trend is undeniable and shows no signs of reversing.",
    "{warrior} is in the midst of an ascent that reflects both skill and determination.  The {points} recognition to {his} name this turn validates both.",
    "Few warriors manage to rise this steadily without hitting a plateau.  {warrior} has yet to find one, and {his} {points} recognition this turn suggests the climb continues.",
    "The rise of {warrior} is the kind of story that {arena} loves. A warrior who earns everything through consistent performance and unmistakable skill.",
    "{warrior}'s standing in {arena} continues to improve, turn after turn, with {points} recognition this turn adding to a growing list of achievements.",
]

_BLK_WARRIOR_FALLER = [
    "And tumbling down the standings was {warrior}, who ran headlong into {opponent} and paid the price.  The records are unforgiving in {arena}, and right now they're not forgiving {warrior}.",
    "Like a fighter who forgot to block, {warrior} dropped a costly bout against {opponent} this turn.  Painful, and the standings will confirm it.",
    "Not every story has a happy ending, and {warrior}'s this turn doesn't even have a satisfying middle.  {opponent} handed them a loss that will linger longer than the bruises.",
    "{opponent} made a point at {warrior}'s expense this turn, and the point was well received by the crowd.  Less so by {warrior}'s team manager, one suspects.",
    "The {arena} crowd can be cruel, and when {warrior} fell to {opponent} this turn, the response was not sympathetic.  A loss at this stage carries consequences.",
    "On the wrong end of the highlights this turn was {warrior}, who had no answer for {opponent}.  The records now reflect what the crowd already knew.",
    "{warrior} left the arena considerably less confident than they entered it, courtesy of {opponent}.  That kind of adjustment tends to be educational, eventually.",
    "Somewhere between planning and execution, {warrior}'s turn fell apart against {opponent}.  It happens.  In {arena}, it tends to happen loudly.",
    "It wasn't {warrior}'s turn.  Or their fight.  Or their afternoon.  {opponent} took care of all of that efficiently and without apparent difficulty.",
    "The standings now officially reflect what the fight already told us. {warrior} was not ready for {opponent} this turn.  The gap between tiers is rarely as polite as the schedule implies.",
    "{warrior}'s slide through the standings shows no sign of stopping.  What was once a promising trajectory has become a concerning downward trend.",
    "The losses have added up for {warrior}, and the recognition count reflects it.  The question now is whether this is a temporary slump or the beginning of the end.",
    "{warrior} is facing the kind of losing streak that defines careers, not always ending them, but reshaping them fundamentally.",
    "The recognition {warrior} has lost over recent turns is the visible symptom of a deeper problem.  {His} standing continues to fall.",
    "Once a name to watch, {warrior} is now a name to worry about, especially if you manage {him}.  The fall in recognition is steep and accelerating.",
    "{warrior}'s recent record is a far cry from what the arena expected when {his} career was climbing.  The descent has been swift.",
    "The margin between where {warrior} was and where {warrior} is now keeps growing.  Each turn seems to take another notch of standing away.",
    "{warrior} is in the kind of hole where digging out becomes harder with each additional loss.  The recognition numbers reflect that reality.",
    "Comebacks are possible, but {warrior} will need to move quickly.  The rate of decline suggests that every turn matters now.",
    "The story of {warrior}'s fall is becoming harder to reverse with each passing turn.  Recognition continues to slip away.",
]

_BLK_BULLY_SHAMED = [
    "{warrior}'s decision to Blood Challenge someone so clearly outmatched didn't go over well with the crowd. Whispers of cowardice followed them out of the arena.",
    "There was little glory in beating an opponent who never stood a chance, and the fans made sure {warrior} knew it. The jeers followed them long after the final blow.",
    "Some wins cost more than they're worth. {warrior}'s lopsided Blood Challenge against {opponent} did more damage to their standing than any wound could have.",
    "The arena has a long memory for this sort of thing. {warrior} won the fight against {opponent}, but lost something harder to win back: the crowd's respect.",
    "Word of {warrior}'s mismatched Blood Challenge spread fast through {team}'s ranks and beyond. No one called it a fair fight, and no one called {warrior} brave for it.",
    "{warrior} picked a fight they couldn't lose, and the crowd made sure they knew exactly what that said about them.",
    "It takes a certain kind of gladiator to hunt down someone so clearly beneath them. {warrior} found that out the hard way when the boos started before the bout even ended.",
    "{warrior} thought {he} could bully {opponent} without consequences. The Commission proved {him} wrong in the most public way possible.",
    "Official rebuke is a heavy thing to carry in {arena}. {warrior} now carries it after {his} display against {opponent}.",
    "The Commission does not intervene lightly. When they stepped forward to condemn {warrior}'s actions against {opponent}, everyone took notice.",
    "{warrior}'s treatment of {opponent} was indefensible. The Commission said so explicitly, and now it is recorded for all {arena} to see.",
    "There is shame and then there is official shame. {warrior} now understands the difference after the Commission's public censure.",
    "{warrior} sought to dominate {opponent}, but instead found {himself} dominated by the weight of official disapproval.",
    "The Commission's judgment against {warrior} for {his} conduct toward {opponent} is final. {His} reputation carries that judgment now.",
    "{warrior} will not easily escape the stigma of the Commission's rebuke. The record is permanent, and {his} name is tied to it.",
    "What {warrior} did to {opponent} crossed from sport into something uglier. The Commission saw it clearly and said so without hesitation.",
    "{warrior}'s moment of dominance over {opponent} will be forever bracketed by official censure and public shame.",
    "The Commission sent a message with {its} rebuke of {warrior}. The message was clear. {this} is not who we are.",
    "{warrior} will carry the weight of that public condemnation for a long time. It is meant to.",
    "When the institutions of {arena} turn their judgment against you, it is time to reconsider {your} choices. {warrior} is learning that now.",
]

_BLK_UNDERDOG_INSPIRED = [
    "{warrior} had every reason to decline that Blood Challenge. {opponent} was leagues ahead on paper. They stepped up anyway, and the crowd couldn't stop talking about it.",
    "Nobody expected much from {warrior}'s Blood Challenge against {opponent}. What they got instead was one of the more talked-about bouts of the week.",
    "It's not about winning or losing. Sometimes it's about showing up. {warrior} showed up against a fighter twice their standing, and the arena took notice.",
    "{warrior}'s stock had never been higher, and it had nothing to do with a win. Taking that Blood Challenge against {opponent} took nerve most gladiators don't have.",
    "The odds were never in {warrior}'s favor against {opponent}, and somehow, that was exactly why the crowd couldn't stop talking about them.",
    "{team}'s {warrior} didn't need to win to make an impression. Just showing up against {opponent} was enough to earn the arena's respect.",
    "Every warrior watching {warrior}'s upset victory just got reminded why they keep fighting. The impossible is not quite as impossible as it looks.",
    "{warrior} has become a symbol this turn, proof that the record does not define the warrior.",
    "The story of {warrior} is spreading through {arena} faster than rumors usually travel. Underdog victories have a way of doing that.",
    "There is something magnetic about a warrior who defies expectations. {warrior} just provided the whole arena with a masterclass in how it is done.",
    "{warrior} gave warriors with nothing to lose a reason to believe they might win everything. That is a powerful gift.",
    "The crowd will remember {warrior}'s performance this turn. So will every warrior lower in the standings.",
    "{warrior}'s victory is the kind that transcends mere points and records. It is the kind that changes how warriors see themselves.",
    "When a warrior like {warrior} succeeds against the odds, {his} teammates take notice. {His} rivals take notice. The entire landscape shifts, just a little.",
    "{warrior} has become someone to watch, not because of {his} record, but because of {his} refusal to accept what that record says about {him}.",
    "The potential awakened by {warrior}'s upset is immeasurable. Belief is contagious, and {warrior} just spread an epidemic of it.",
    "{warrior} proved this turn that being underestimated can be an advantage if you refuse to accept the label.",
    "Stories like {warrior}'s do not come from the rankings. They come from something deeper, a refusal to accept limits.",
    "{warrior}'s journey from overlooked to impossible to remember is exactly what keeps {arena} compelling.",
    "When underdog becomes victor, the entire arena takes a breath and reconsiders. {warrior} just forced that reconsideration.",
]

_BLK_CHAMP_STRIPPED_DECISION = [
    "Due to the nature of {warrior}'s disgraceful acts of cowardice in the persecution of lesser-known gladiators, the Gladiatorial Commission revoked {warrior}'s title.",
    "Citing a pattern of conduct unbecoming a champion, the Gladiatorial Commission formally stripped {warrior} of the championship.",
    "In an unprecedented move, the Gladiatorial Commission voted to remove {warrior} from the championship, citing repeated abuse of the Blood Challenge against clearly outmatched opponents.",
    "The Gladiatorial Commission stripped {warrior} of the championship, ruling that their conduct in the arena no longer reflected the standard expected of a champion.",
    "By unanimous decision, the Gladiatorial Commission revoked {warrior}'s title, condemning their repeated targeting of lesser gladiators as unworthy of the crown.",
    "The Gladiatorial Commission announced the removal of {warrior} from the championship, following mounting complaints over their conduct in recent Blood Challenges.",
    "{champion}'s tenure as titleholder came to an abrupt end courtesy of the Commission. No fight, no loss in combat. Just an official judgment that {he} no longer qualified.",
    "The Commission's decision to strip {champion} of the Championship carries the weight of institutional authority. {His} reign is over, regardless of {his} record in combat.",
    "{champion} can no longer claim the title. The Commission saw something in {his} conduct or circumstances that made continued possession of the crown impossible.",
    "It is a different kind of fall when the throne is taken by bureaucratic verdict rather than by a rival's blade. {champion} now knows both kinds of displacement.",
    "The Commission does not often act so decisively, but when it does, there is no appeal. {champion} learned that this turn.",
    "{champion}'s reign was ended not by an opponent but by an institution. The result is the same. {He} is no longer Champion.",
    "Official judgment moves faster than most people expect. {champion} learned that when the Commission stripped {him} of the Championship.",
    "The grounds for the Commission's action may vary, but the result is always certain. {champion} is no longer the titleholder.",
    "There is a finality to Commission decisions that exceeds even the finality of combat. {champion} is now learning that.",
    "{champion} sits outside the title picture this turn, removed not by defeat but by official decree.",
    "The path to the Championship just changed. {champion} was removed from {his} place at the top through Commission action.",
    "When the Commission speaks on a matter of Championship, the arena listens and obeys. {champion} no longer holds the title as a result.",
    "{champion} was deemed unsuitable by forces larger than any single warrior. {His} Championship is now history.",
    "The title that once belonged to {champion} is now being contested by other warriors. {He} was stripped of it by official action, a form of loss with no honor in defeat.",
]

_BLK_CHAMP_STRIPPED_QUOTE = [
    "\"The Commission will not stand for this kind of cowardice from its combatants,\" said one member, speaking on condition of anonymity.",
    "\"A champion is supposed to represent the best of us. This was not that,\" one Commission official remarked.",
    "\"There's a difference between vengeance and cruelty. We drew that line today,\" said a Commission source.",
    "\"No one earns a crown by hunting down the weak. We won't pretend otherwise,\" one member stated plainly.",
    "\"The title means something. It's our job to make sure it stays that way,\" a Commission representative said.",
    "\"We've heard the crowd, and frankly, we agree with them,\" one official admitted.",
    "\"A champion holds the highest standard,\" one Commission member said. \"When that standard is violated, the consequence is clear.\"",
    "\"This decision was not made lightly,\" said the Commission's public statement. \"It reflects a consensus that the championship cannot continue under these circumstances.\"",
    "\"The conduct we reviewed was inconsistent with what we require of our champions,\" an official commented, declining further elaboration.",
    "\"We act when the arena itself demands it,\" one Commission source noted. \"Today, the arena's judgment and ours aligned.\"",
    "\"The championship represents something sacred to this arena,\" a Commission representative explained. \"It cannot be held by someone who disrespects that sacred trust.\"",
    "\"Some patterns of conduct cannot be overlooked or forgiven,\" said one official, referring to the documented evidence presented to the Commission.",
    "\"If we allow this, what does the championship become?\" asked one member during the deliberations, a question that apparently swayed the final vote.",
    "\"The integrity of the title is what matters most,\" the Commission announced. \"Everything else is secondary to that.\"",
    "\"We do not make decisions about individuals lightly,\" an official said, \"but the championship is bigger than any one warrior.\"",
    "\"This reflects the will of the Commission,\" stated a spokesperson. \"It is both unanimous and final.\"",
    "\"The standards exist for a reason,\" one member remarked. \"When someone violates them so egregiously, action is required.\"",
    "\"We look at the totality of conduct, not just isolated incidents,\" explained an official when pressed on the decision.",
    "\"The championship is a trust, not a prize to be hoarded,\" said one Commission representative. \"When that trust is broken, the crown must be reclaimed.\"",
    "\"Future champions will see this decision and understand what is expected of them,\" predicted one Commission official, suggesting the action was partly pedagogical.",
]

_BLK_CHALLENGE_WIN = [
    "I just want to tip my hat to {warrior}, who took on {opponent} from a lower spot in the rankings and came out ahead.  The smart money wasn't on it.  The smart money was wrong.",
    "Congratulations are in order for {warrior}, who overcame both {opponent} and the recognition gap between them.  That kind of result earns more than points.  It earns a reputation.",
    "Not everyone challenges up and survives to tell it.  {warrior} did, putting {opponent} down in a result that surprised most of {arena}.  Well earned.",
    "They said {warrior} was overmatched against {opponent}.  {warrior} apparently didn't hear that part.  The result speaks clearly enough.",
    "Challenging up is brave.  Winning is better.  {warrior} managed both this turn against {opponent}, and the recognition that followed was entirely deserved.",
    "{warrior} answered {opponent}'s call with finality.  Whatever narrative {opponent} was building got rewritten in the sand of the arena floor.",
    "{opponent} approached this turn with clear intent, to test {warrior}.  Intent is not the same as ability.  {warrior} made that difference plain.",
    "The confrontation between {warrior} and {opponent} resolved itself this turn, and not in the way {opponent} had anticipated.",
    "{warrior} did not flinch when {opponent} demanded a trial.  The trial proceeded, and the result was beyond dispute.",
    "{opponent} brought a challenge; {warrior} brought a victory.  The exchange, though brief, settled matters with authority.",
    "Some rivalries fade naturally over time.  Others end abruptly on the arena floor.  {warrior} and {opponent}'s ended this turn, decisively and without question.",
    "{opponent} had the courage to face {warrior} head-on.  Courage, it turned out, was not quite enough.",
    "The pairing of {warrior} and {opponent} was not random. It was the culmination of turns of tension.  Turns of tension can only end in resolution.  Today it did.",
    "{warrior}'s victory over {opponent} carries particular weight because {opponent} came prepared and still fell short.",
    "{opponent} gave {warrior} everything available to give.  {warrior} answered with something more.",
    "When rivals meet and only one walks away with victory, the verdict is final.  {warrior} has that verdict.",
    "{opponent} challenged {warrior} knowing the risks.  The risks, as it turned out, were real.",
    "The contest between {warrior} and {opponent} was fierce, but it had only one true outcome.  {warrior} saw it through to its end.",
    "{warrior} proved {himself} the better warrior when it mattered most, when {opponent} was watching.",
    "{opponent} wanted to prove something against {warrior}.  Instead, {warrior} proved something about {opponent}.",
]

_BLK_CHALLENGE_LOSS = [
    "{warrior} had better have a very good reason for challenging down against {opponent} and still coming away with a loss.  I thought {warrior} showed great skill and promise when they were absolutely flattened.  All right, I slept through it.  Big deal.",
    "Challenging down is supposed to be the safe play.  Someone should tell {warrior} that, since they managed to lose to {opponent} anyway.  That requires a special kind of effort.",
    "The most charitable reading of {warrior}'s challenge against {opponent} is that they underestimated the competition.  The least charitable reading is also probably correct.",
    "I've seen bad challenges before, but {warrior} going after {opponent}, a lower-ranked opponent, and still losing is a special kind of expensive.  The recognition gap made it look safe.  It wasn't.",
    "Some lessons cost coin.  Some cost pride.  {warrior}'s loss to {opponent} in what should have been a comfortable challenge cost both.  Thoroughly.",
    "{warrior} brought a challenge to {opponent} expecting a different outcome.  {opponent} had other plans and executed them flawlessly.",
    "It is not hard to understand why {warrior} wanted to face {opponent}. Ambition is always understandable.  Success, however, proved more elusive.",
    "{opponent} was ready when {warrior} came calling this turn.  More than ready.  Prepared.",
    "{warrior}'s attempt to prove something against {opponent} backfired spectacularly.  {Opponent} proved something instead, and did it thoroughly.",
    "The matchup between {warrior} and {opponent} was supposed to be competitive.  It was not.  {Opponent} made that clear early and often.",
    "{warrior} stepped up to challenge {opponent} with high hopes.  Hope and reality parted ways quickly.",
    "You have to respect {warrior}'s willingness to test {opponent}.  You also have to acknowledge the gap that {opponent} revealed.",
    "{opponent} was not in the mood for {warrior}'s challenge and made that sentiment very clear on the arena floor.",
    "{warrior} came ready for battle.  {Opponent} came ready for war.  The difference was immediately apparent.",
    "Challenging {opponent} showed either courage or poor judgment on {warrior}'s part.  The result suggests the latter.",
    "{opponent} answered {warrior}'s challenge with an emphatic statement.  The conversation, from {opponent}'s perspective, was over early.",
    "{warrior} had the courage to face {opponent}.  Courage alone was not enough to secure victory.",
    "The contest between {warrior} and {opponent} unfolded in {opponent}'s favor from start to finish.  No heroics, no comeback.  Just domination.",
    "{warrior} thought {he} was ready for {opponent}.  {Opponent} proved otherwise with convincing finality.",
    "When {opponent} stepped into the arena with {warrior}, the outcome seemed predetermined.  It was.  {Opponent} controlled every moment.",
]

_BLK_DIG_DEEPER = [
    "Let's dig a little deeper into what's been going on in {arena} this turn.",
    "Now let me tell you what the standings board won't.",
    "Scratch the surface of this turn and the interesting parts start showing.",
    "The official results tell one story.  Here's the version worth knowing.",
    "There's always more to a turn than the final records.  Let's have a look.",
    "You want the real story?  Here it is.",
    "Beyond the numbers, there are names worth discussing in {arena}.",
    "Pull up a chair.  There's more to unpack from this turn in {arena}.",
    "The ledger tells you who won.  I'll tell you what it means.",
    "Now that we've got the scores, let's talk about what's actually happening in {arena}.",
    "The standings suggest one story, but the actual performance data suggests another.  Worth investigating which one is true.",
    "There are patterns in how certain managers schedule that reward careful study.  Understanding those patterns is half the battle.",
    "Every warrior has a breaking point.  The question is whether we're seeing theirs or just a bad turn.",
    "The real story is often hidden beneath the surface.  Looking deeper at {team}'s decisions reveals what the standings alone cannot.",
    "Worth examining closely: whether {warrior}'s recent performance trends represent skill development or statistical noise.",
    "The schedules tell stories that the records alone cannot capture.  For those paying attention, those stories are invaluable.",
    "Behind every surprising result is usually a logical explanation.  Finding that explanation is the work of serious students of {arena}.",
    "What appears random often has patterns if you look long enough.  The managers who see those patterns are the ones who prosper.",
    "The gap between what managers say they are doing and what they are actually doing is often quite large.  Watch closely.",
    "Statistical variance or genuine shift?  That is the question that determines whether this turn matters next season.",
]

_BLK_WORST_TEAM = [
    "A stormcloud is brewing over the {team} guildhouse.  A {record} showing is the kind of result that makes managers nervous and fighters start questioning their contracts.",
    "Meanwhile, {team} had a turn they'd rather forget.  A {record} is the sort of record that generates uncomfortable conversations in the team quarters.",
    "Not everyone came out of this turn smiling.  {team} posted a {record} showing that the standings will remember even if the warriors prefer not to.",
    "The {record} outing from {team} will be discussed quietly, in corners, by people who are worried.  That kind of record doesn't just disappear.",
    "Someone in the {team} camp needs to have a serious talk.  A {record} turn like that has consequences, and the standings are already keeping score.",
    "Rumor has it that any more turns like this one's {record} may send the {team} roster toward some difficult decisions.  The arena is not a forgiving accountant.",
    "Hard to put a bright face on a {record} turn.  {team} will try anyway, but the standings don't grade on effort.",
    "If {team} was hoping this turn would turn things around, the {record} result suggests otherwise.  Hope and execution remain on separate schedules.",
    "{team} limped out of this turn with a {record} showing that raised more questions than it answered.  Answers are expected before the next turn.",
    "Let's just say {team}'s {record} this turn is the kind of performance that motivates rival managers to schedule challenges.  Weakness, real or perceived, gets noticed fast in {arena}.",
]

_BLK_PHILOSOPHICAL = [
    "Being a spy is great.  Other people die and you spend the rest of the day drinking to their memory.  Better tanked than dead.  Ask not the elves for counsel, for they will say both yes and no.  Silly buggers.",
    "I've been doing this long enough to know that the best fights are the ones that prove me wrong.  This turn had a few of those.  I've already started forgetting them.",
    "They pay me to write this down.  Some turns I feel guilty about taking the coin.  This was not one of those turns.  {arena} delivered.",
    "A warrior's lot is filled with strife, revenge, and killing.  Some fighters don't accept this.  The best do.  The ones who argue about it never last long enough to change the subject.",
    "I was once told that the key to wisdom is knowing what you don't know.  I don't know how some of these managers keep their jobs.  There you have it.",
    "Remember: in {arena}, even a bad turn teaches something.  Whether anyone learns it is a different question entirely.",
    "Every turn ends the same way, with the stands emptying and the managers arguing about what went wrong.  It's the most honest part of the whole enterprise.",
    "Time for my medication.  Or another drink.  In this profession, the distinction rarely matters.",
    "All work and no play makes for a dull career.  All play and no training makes for a short one.  Somewhere in the middle is the winning formula.  Most warriors are still looking for it.",
    "Someone once asked me if I ever feel bad writing about losses.  I told them no.  They stopped asking me things after that, which I consider a personal victory.",
    "Ambition is the fuel that drives warriors into the arena.  Whether it also drives them out alive is a question only time answers.",
    "The arena teaches hard lessons to those foolish enough to step into it.  Some warriors learn.  Others just accumulate scars.",
    "In the end, the record is all that matters.  Not the hopes that preceded the fights, but the results that followed them.",
    "Every warrior believes they are the exception.  The arena proves, with perfect regularity, that they are not.",
    "Courage and foolishness are separated by only the slimmest of margins.  In the arena, that margin is usually measured in blood.",
    "The strongest warriors are not always the ones with the biggest muscles.  Sometimes they are simply the ones who refused to accept defeat as inevitable.",
    "What the arena takes, it does not return.  Warriors learn this early or they learn it late, but they all learn it eventually.",
    "Fate is what happens when preparation meets opportunity.  In the arena, the unprepared call it fate.  The prepared call it victory.",
    "The arena is honest in a way that the rest of the world rarely manages.  That honesty is brutal, but it is real.",
    "Every warrior enters the arena thinking they understand what they are walking into.  Almost none of them do, at first.",
]


_BLK_STREAK = [
    "While others debate matchups and massage their schedules, {warrior} of {team} has simply kept winning.  Sustained success in {arena} attracts attention, and that attention is no longer politely ignoring this fighter.",
    "{warrior} of {team} continues building something that is becoming difficult to dismiss.  Turn after turn, the wins accumulate.  The streak is long enough now that rival managers are no longer pretending not to notice.",
    "At some point a winning run stops being fortunate and starts being a pattern.  {warrior} of {team} has crossed that line, and the managers scheduling around them have already drawn the conclusion.",
    "Sustained winning is harder than one great performance, and {warrior} of {team} is proving it.  The streak puts this fighter in a different category of concern for anyone at this tier.",
    "The easiest prediction in {arena} right now involves {warrior} of {team} and an aggressive challenge appearing on the schedule soon.  Sustained success invites attention.  The streak has crossed a threshold.",
    "When a warrior keeps winning, {arena} eventually takes formal notice.  {warrior} of {team} is at that point.  The bookmakers have updated their lines.  The cautious managers have updated their schedules.",
    "{warrior} of {team} has a streak worth watching, and worth worrying about if you're the manager who has to face them next.  Momentum in {arena} is real, and this fighter has it.",
    "Not everyone survives long enough to build a streak in {arena}.  {warrior} of {team} is building one, and the length of it has become a topic of conversation in corners where scheduling decisions are made.",
    "The streak continues to grow for {warrior}.  {Streak} consecutive victories is the kind of run that changes how people see a warrior.",
    "{warrior} has won {streak} in a row, a milestone that few warriors in {arena} reach or maintain for long.",
    "When a warrior gets hot, the rest of {arena} tends to notice.  {warrior}'s {streak}-win streak has certainly earned the attention it deserves.",
    "{warrior}'s losing streak has reached {streak} consecutive defeats.  The pattern is now undeniable, and {his} teammates must be concerned.",
    "Success breeds confidence, and {warrior} is riding high on {streak} straight victories.  The question is whether {he} can keep it going.",
    "A {streak}-game losing streak is the kind of thing that tests a warrior's mental resolve.  {warrior} will need to find {his} form quickly.",
    "{warrior}'s hot streak of {streak} victories puts {him} among the most dangerous warriors in {arena} right now.",
    "The losses for {warrior} have now reached {streak} consecutive.  Each loss makes the next one harder to recover from.",
    "When {warrior} wins, the margin tends to be clear.  {He}'s now done it {streak} times in a row, establishing a pattern of dominance.",
    "Streaks are fascinating things. They define a moment in a warrior's career.  For {warrior}, the {streak}-loss streak is defining {his} moment right now.",
    "{warrior}'s recent form has been exceptional, with {streak} consecutive victories in the toughest arena in the world.",
    "No one would have predicted this level of struggle for {warrior}.  Yet here {he} is, caught in {streak} consecutive losses.",
]

_BLK_STANDINGS_LOOK = [
    "Step back from the individual results for a moment and look at what the standings are actually saying.  The distance between top and bottom is growing, and the middle tier is where all the meaningful maneuvering is still happening.",
    "The standings after this turn tell a story for anyone reading carefully.  Some managers are building toward something.  Others are surviving.  Both approaches produce a result, though not always the intended one.",
    "Standings in {arena} don't lie, but they do oversimplify.  Behind the records are patterns: managers adjusting, warriors peaking, and momentum that the numbers alone can't fully capture.  Worth watching.",
    "The scoreboard shows wins and losses.  What it doesn't show is which teams are trending in the right direction and which are sliding despite a respectable record.  In {arena}, direction matters as much as position.",
    "Every manager in {arena} is reading the same standings and drawing different conclusions.  That's the nature of this place.  The ones who read it correctly tend to keep doing so.  The ones who don't have an explanation ready.",
    "After this turn, the standings have sorted themselves into a picture that will define scheduling decisions for what comes next.  Some fighters are becoming commodities.  Others are becoming problems.  The ledger knows the difference.",
    "If you look at the trend lines rather than just this turn's results, {arena} is quietly separating into tiers that won't shift easily.  Managers in the top half have reason for optimism.  The rest have reason for urgency.",
    "It's worth remembering that every fight this turn had context: recognition gaps, grudges, avoidance patterns that the final W-L record doesn't capture.  The standings are accurate.  They are also incomplete.",
    "The standings shifted this turn in ways both predictable and strange.  The predictable moves will be forgotten by next week.  The strange ones will echo for months.",
    "Each position in the standings represents a choice, a series of fights accepted or declined, won or lost.  This turn's standings reflect those choices accumulated.",
    "The standing are only a summary.  The real story is in the gaps, the warriors climbing faster than expected and those falling further.",
    "A warrior can spend years building a standing, and seasons can change it in moments.  The standings this turn reflect both kinds of warriors.",
    "The recognition scores that drive the standings are unforgiving.  A single decision can ripple across multiple turns, reshaping where a warrior sits.",
    "Looking at the standings is like looking at a still photograph of a battle in progress.  It captures a moment but not the momentum.",
    "The standings have shifted enough this turn to make the next few weeks of scheduling a puzzle for every manager in {arena}.",
    "Careful students of the standings watch not just movement but the rate of movement.  This turn, several warriors accelerated or decelerated notably.",
    "The standings are the product of individual choice cascading across the arena.  This turn's results reflect thousands of small decisions crystallized into positions.",
    "Some warriors climb the standings steadily.  Others leap suddenly.  This turn brought examples of both, and the implications will play out for weeks.",
    "The standings represent the arena's collective judgment on warrior capability.  This turn, that judgment shifted for several warriors in ways that surprised even {arena}'s most careful observers.",
    "Each entry in the standings tells a story about a warrior's choices, abilities, and fortune.  This turn, several of those stories took unexpected turns.",
]

_BLK_SECOND_TEAM = [
    "Worth keeping an eye on as well is {team}, whose {record} turn has them quietly positioned better than their current standing suggests.  Not the story of the turn, but perhaps the beginning of one.",
    "{team} didn't top the board, but their {record} showing this turn was more instructive than the standings give credit for.  Fights are often decided before they begin, and {team} is winning that preparation battle.",
    "While the top and bottom of the standings absorb attention, {team} turned in a {record} showing that deserves a mention.  Consistency in the middle is how teams eventually reach the top, or stop pretending they won't.",
    "The {record} posted by {team} this turn is the kind of result that makes observers revise their estimates.  Neither the best nor the worst showing, but one that suggested more than it confirmed.",
    "In a turn with bigger headlines elsewhere, {team} quietly posted a {record} record that says something about their direction.  {arena} tends to reward the teams that don't need the biggest story to keep moving forward.",
    "{team} is not making headlines, but they are making progress.  A {record} turn like this one is exactly how dark horses build their case.",
    "Attention has been elsewhere this turn, but {team}'s {record} showing deserves its own footnote.  Consistency wins in {arena} eventually.",
    "{team} turned in a solid {record} turn without fanfare.  That is the kind of performance that builds foundations rather than celebrates summits.",
    "The quiet victory belongs to {team}, whose {record} turn positions them better than most observers realize.",
    "{team} is the kind of team that builds value without demanding attention.  This turn's {record} result is a perfect example of that approach.",
    "While others chase headlines, {team} chases victories.  Their {record} turn this week suggests the strategy is working.",
    "{team}'s {record} showing this turn is a gentle reminder that not all progress comes with celebration.",
    "Careful observers are noticing {team}'s consistency.  A {record} turn like this adds another data point to a growing narrative.",
    "{team} is content to excel without the spotlight.  This turn's {record} result is proof they do not need validation to perform.",
    "The understated performance from {team} this turn, a {record} showing, may prove more valuable than any number of flashy victories.",
    "{team} continues to build momentum in the shadows.  A {record} turn keeps them on the upward trajectory where they belong.",
    "Not every strong performance needs to make the headlines.  {team}'s {record} turn this week is exactly what steady progress looks like.",
    "{team} has learned the art of performing well without demanding recognition.  This turn's {record} result is a masterclass in that approach.",
    "The story of {team} is not one of dramatic rises and falls. It is one of sustained, quiet excellence.  This {record} turn fits that pattern perfectly.",
    "{team} remains focused on what matters, consistent, solid performance.  Their {record} turn this week demonstrates that focus is paying dividends.",
]

_BLK_MULTIPLE_DEATHS = [
    "The kill count this turn was high enough to change the atmosphere in {arena}.  More than a few managers will be filling vacancies before the next turn.  The arena moves on without ceremony, as it always does.",
    "Multiple careers ended this turn.  The rosters that entered {arena} are not the same ones that will prepare for the next.  Some names will not be appearing on future schedules.",
    "When a turn produces this many deaths, {arena} has a habit of becoming very quiet for a short time and then very loud.  Today followed that pattern exactly.  The scheduling implications are immediate.",
    "More than one manager walked out of this turn with a vacancy to fill and a story they'd rather not retell.  {arena} earned its name today.",
    "This was not a gentle turn at {arena}.  Multiple careers ended today, and the atmosphere in the aftermath reflected that.  The business continues regardless, but some turns leave a mark on the crowd.",
    "The stands emptied more quietly than usual after this turn.  Multiple kills have a way of doing that.  {arena} earned its name today.",
    "A reminder from {arena}: this is not sport.  Multiple deaths in a single turn communicate that clearly enough.  The survivors continue.  The others have concluded their participation permanently.",
    "Some turns are for standings.  Some are for lesson-learning.  This one was for the record books.  Multiple kills in a single turn is the arena's way of ensuring no one mistakes enthusiasm for preparation.",
    "The turn brought more than one funeral to the families of {arena}'s warriors.  That is the kind of turn that echoes longer than most.",
    "When several warriors fall in the same turn, the arena's rhythm changes.  Everyone takes a breath and remembers what they are really watching.",
    "The death toll this turn exceeds what most turns produce.  It is a sobering reminder that the arena does not discriminate in its cruelty.",
    "Multiple warriors crossed the line from living to dead this turn.  The next turn will have empty spaces on the schedule that were not expected.",
    "Some turns are just heavier than others.  This is one of them.  The casualty count makes that clear.",
    "The arena demanded a higher price this turn than it usually does.  Several warriors paid that price, and they will not be coming back.",
    "Deaths cluster sometimes in {arena}, not by design, but by the accidents of scheduling and chance.  This turn was one of those clustering turns.",
    "When the death column of the ledger grows longer, it changes the calculus of everything.  Warriors think twice.  Managers reconsider.  The crowd feels heavier.",
    "The multiple deaths this turn are the kind of thing that shapes narratives for the whole season.  They will be remembered far longer than victories.",
    "The turn brought an unusual toll in lives lost.  That is the price of the arena, and this turn paid more than most.",
    "Turns like this one, turns with high death tolls, tend to refocus everything on what really matters in {arena}.  For a while after, warriors think more carefully about accepting challenges.",
    "The arena took several warriors this turn.  That level of loss reshapes how everyone views what happens here.",
]


def _pick_block(pool: list, used: set, ctx: dict) -> str:
    """Pick an unused block from pool, format it with ctx, mark raw template as used."""
    available = [b for b in pool if b not in used]
    if not available:
        available = list(pool)
    template = random.choice(available)
    used.add(template)
    # Safe defaults for keys that may be missing from ctx -- pronouns, title-case
    # variants, and neutral fallbacks. ctx values always win via the update below.
    safe = {
        'he': 'he', 'He': 'He',
        'his': 'his', 'His': 'His',
        'him': 'him', 'Him': 'Him',
        'himself': 'himself', 'Himself': 'Himself',
        'she': 'she', 'She': 'She',
        'her': 'her', 'Her': 'Her',
        'herself': 'herself', 'Herself': 'Herself',
        'they': 'they', 'their': 'their',
        'its': 'its', 'this': 'this', 'your': 'your',
        # Title-case variants of data fields templates sometimes capitalise mid-sentence
        'Opponent': ctx.get('opponent', ''),
        'Points': ctx.get('points', ''),
        'Streak': str(ctx.get('streak', '')),
    }
    safe.update(ctx)
    return template.format(**safe)


def _block_commentary(card, teams, deaths, turn_num: int, champion_state: dict, is_new_champion: bool = False,
                       bully_events: list = None, prev_champion_state: dict = None,
                       promotions: list = None, promotion_pending: list = None) -> str:
    """
    Generate a flowing spy-report style narrative for Arena Happenings.
    Pool blocks are used as sentence-level building pieces woven together
    by the reporter's voice - not as disconnected standalone paragraphs.

    Structure:
      Para 1 - Intro + champion headline + best team + worst team
      Para 2 - Warrior risers, fallers, notable challenge results
      Para 3 - Transition ("dig deeper") + avoidance/challenge meta
                + champion defends (if no title change this turn)
      Para 4 - Deaths (if any) + philosophical aside
      Para 5 - Outro / sign-off
    """
    arena  = ARENA_NAME.upper()
    venue  = "The Agony"
    byline = random.choice(_BLK_BYLINES)
    random.seed()
    used   = set()   # shared across ALL _pick_block calls - no repeats in one report

    # ------------------------------------------------------------------
    # DATA EXTRACTION
    # ------------------------------------------------------------------

    # Deduplicate fight pairs (card may list each bout from both teams' POV)
    seen_pairs   = set()
    unique_bouts = []
    for bout in card:
        if not bout.result: continue
        pair = frozenset([bout.player_warrior.name, bout.opponent.name])
        if pair in seen_pairs: continue
        seen_pairs.add(pair)
        unique_bouts.append(bout)

    # Team records this turn
    team_records = {}
    for team in teams:
        if _is_npc_team(team): continue
        tname = team.team_name if hasattr(team, "team_name") else team.get("team_name", "?")
        w = l = k = 0
        for bout in unique_bouts:
            pt = bout.player_team
            ot = bout.opponent_team
            ptname = pt.team_name if hasattr(pt, "team_name") else pt.get("team_name", "?")
            otname = ot.team_name if hasattr(ot, "team_name") else ot.get("team_name", "?")
            pw_won = bout.result.winner and bout.result.winner.name == bout.player_warrior.name
            if ptname == tname:
                if pw_won: w += 1; k += (1 if bout.result.loser_died else 0)
                else: l += 1
            elif otname == tname:
                if not pw_won: w += 1; k += (1 if bout.result.loser_died else 0)
                else: l += 1
        team_records[tname] = {"w": w, "l": l, "k": k}

    # AUDIT: Validate team records don't exceed 5 fights per team per turn
    # (each team can have at most 5 active warriors, each fights once max)
    for tname, rec in team_records.items():
        total_fights = rec["w"] + rec["l"]
        if total_fights > 5:
            print(f"  WARNING: {tname} has {total_fights} total fights ({rec['w']}-{rec['l']}) - exceeds max 5 for a turn")

    sorted_teams = sorted(team_records.items(), key=lambda x: (-x[1]["w"], x[1]["l"]))
    best_name,  best_rec  = sorted_teams[0]  if sorted_teams else (None, None)
    worst_name, worst_rec = sorted_teams[-1] if sorted_teams else (None, None)

    # Per-fight warrior data  (winners and notable losers)
    winners_list  = []  # dicts: warrior, team, opponent, recs, is_kill
    losers_list   = []  # same
    for bout in unique_bouts:
        pw     = bout.player_warrior
        op     = bout.opponent
        pw_won = bout.result.winner and bout.result.winner.name == pw.name
        winner, loser   = (pw, op) if pw_won else (op, pw)
        w_team, l_team  = (bout.player_team, bout.opponent_team) if pw_won else (bout.opponent_team, bout.player_team)
        wtname = w_team.team_name if hasattr(w_team, "team_name") else w_team.get("team_name", "?")
        ltname = l_team.team_name if hasattr(l_team, "team_name") else l_team.get("team_name", "?")
        # Only spotlight PvP fights - peasant/monster opponents make for poor narrative
        is_pvp = wtname not in _NPC_TEAM_NAMES and ltname not in _NPC_TEAM_NAMES
        if wtname not in _NPC_TEAM_NAMES and is_pvp:
            winners_list.append({"warrior": winner.name, "team": wtname,
                                  "opponent": loser.name,
                                  "recs": getattr(winner, "recognition", 0),
                                  "is_kill": bout.result.loser_died})
        if ltname not in _NPC_TEAM_NAMES and is_pvp:
            losers_list.append({"warrior": loser.name, "team": ltname,
                                 "opponent": winner.name,
                                 "recs": getattr(loser, "recognition", 0),
                                 "is_kill": bout.result.loser_died})
    winners_list.sort(key=lambda x: -x["recs"])
    # Notable losers = fighters with something to lose (higher recognition)
    losers_list.sort(key=lambda x: -x["recs"])

    # Challenge data
    challenge_results = []   # notable challenge bouts (challenging up win, challenging down loss)
    challenge_counts  = {}   # {warrior_name: times challenged}
    targeted_counts   = {}   # {team_name: times challenged against}

    for bout in unique_bouts:
        if bout.fight_type not in ["challenge", "blood_challenge"]: continue
        pw     = bout.player_warrior
        op     = bout.opponent
        pw_won = bout.result.winner and bout.result.winner.name == pw.name
        pt     = bout.player_team
        ot     = bout.opponent_team
        ptname = pt.team_name if hasattr(pt, "team_name") else pt.get("team_name", "?")
        otname = ot.team_name if hasattr(ot, "team_name") else ot.get("team_name", "?")
        pw_rec = getattr(pw, "recognition", 0)
        op_rec = getattr(op, "recognition", 0)
        # rec_diff > 0 means challenger has MORE recognition (challenging down)
        rec_diff = pw_rec - op_rec
        challenge_results.append({
            "challenger": pw.name, "challenger_team": ptname,
            "challenged": op.name, "challenged_team": otname,
            "challenger_won": pw_won, "rec_diff": rec_diff,
            "abs_diff": abs(rec_diff), "is_kill": bout.result.loser_died,
        })
        challenge_counts[op.name] = challenge_counts.get(op.name, 0) + 1
        targeted_counts[otname]   = targeted_counts.get(otname, 0) + 1

    # Meta-warrior: only call out if challenged 2+ times (1 challenge is not notable)
    most_challenged_warrior = None
    if challenge_counts:
        top_warrior, top_count = max(challenge_counts.items(), key=lambda x: x[1])
        if top_count >= 2:
            most_challenged_warrior = top_warrior

    # Meta-team avoidance: a player team that fought this turn but received NO challenge attempts
    # (The "avoidance" narrative only makes sense if rivals genuinely bypassed them)
    teams_that_fought_nl = set()
    for bout in unique_bouts:
        pt = bout.player_team
        ot = bout.opponent_team
        ptn = pt.team_name if hasattr(pt, "team_name") else pt.get("team_name", "?")
        otn = ot.team_name if hasattr(ot, "team_name") else ot.get("team_name", "?")
        if ptn not in _NPC_TEAM_NAMES: teams_that_fought_nl.add(ptn)
        if otn not in _NPC_TEAM_NAMES: teams_that_fought_nl.add(otn)
    challenged_teams = set(targeted_counts.keys())
    avoided_teams = [t for t in teams_that_fought_nl
                     if t not in challenged_teams and t not in _NPC_TEAM_NAMES]
    most_avoided_team = random.choice(avoided_teams) if avoided_teams else None

    # Kill highlights (winners who scored a kill this turn)
    # Streak warriors - 3+ consecutive wins, player teams only
    seen_streak  = set()
    streak_warriors = []
    for bout in unique_bouts:
        pw     = bout.player_warrior
        pt     = bout.player_team
        ptname = pt.team_name if hasattr(pt, "team_name") else pt.get("team_name", "?")
        if ptname in _NPC_TEAM_NAMES: continue
        streak = getattr(pw, "streak", 0)
        if streak and streak >= 3 and pw.name not in seen_streak:
            seen_streak.add(pw.name)
            streak_warriors.append({"warrior": pw.name, "team": ptname, "streak": streak})
    streak_warriors.sort(key=lambda x: -x["streak"])

    # Middle teams - between best and worst for secondary team coverage
    middle_teams = sorted_teams[1:-1] if len(sorted_teams) > 2 else []

    # Champion data
    champ     = champion_state.get("name", "")
    champ_t   = champion_state.get("team_name", "")
    champ_src = champion_state.get("source", "")

    # Extract previous champion if available
    prev_champ = prev_champion_state.get("name", "") if prev_champion_state else ""

    # Base context - always keep every key present so format() never raises
    ctx = dict(
        arena=arena, venue=venue, byline=byline,
        turn=turn_num, next_turn=turn_num + 1,
        team="", team2="", record="", killer="",
        rank_change="", warrior="", opponent="",
        points="", champion=_trunc(champ).upper() if champ else "",
        champ_team=_trunc(champ_t).upper() if champ_t else "",
        prev_champion=_trunc(prev_champ).upper() if prev_champ else "",
    )

    # Gender lookup so {he}/{his}/{him} follow the warrior being written about.
    # Without this every template defaulted to male pronouns.
    _gmap = {}
    def _note_gender(obj):
        if obj is None:
            return
        nm = obj.get("name") if isinstance(obj, dict) else getattr(obj, "name", None)
        gd = obj.get("gender") if isinstance(obj, dict) else getattr(obj, "gender", None)
        if nm and gd:
            _gmap[str(nm).lower()] = gd
    for _b in unique_bouts:
        _note_gender(getattr(_b, "player_warrior", None))
        _note_gender(getattr(_b, "opponent", None))
    for _t in (teams or []):
        for _key in ("warriors", "archived_warriors"):
            _lst = (getattr(_t, _key, None) if not isinstance(_t, dict) else _t.get(_key)) or []
            for _w in _lst:
                _note_gender(_w)

    def _pick_for(pool, name):
        """Pick a block whose {he}/{his}/{him} refer to `name`. If the warrior's
        gender is unknown, use only templates that need no pronoun."""
        g = _gmap.get(str(name or "").lower(), "")
        if g[:1].lower() in ("m", "f"):
            _set_elite_pronouns(ctx, g)
            return _pick_block(pool, used, ctx)
        plain = [t for t in pool if not _PRONOUN_RE.search(t)]
        return _pick_block(plain or pool, used, ctx)

    paragraphs = []

    # ==================================================================
    # PARAGRAPH 1 - INTRO + CHAMPION HEADLINE
    # Champion news (new or vacant) follows the intro as the biggest story.
    # ==================================================================
    p1 = []

    p1.append(_pick_block(_BLK_INTRO, used, ctx))

    # Champion - new champ is the biggest news; lead with it right after intro
    if champ and is_new_champion and champ_src == "beat_champion":
        ctx["champion"]   = _trunc(champ).upper()
        ctx["champ_team"] = _trunc(champ_t).upper()
        p1.append(_pick_block(_BLK_CHAMP_NEW, used, ctx))
    elif champ and is_new_champion and champ_src == "recognition":
        ctx["champion"]   = _trunc(champ).upper()
        ctx["champ_team"] = _trunc(champ_t).upper()
        p1.append(_pick_for(_BLK_CHAMP_RECOGNITION, champ))
    elif champ and not is_new_champion:
        ctx["champion"]   = _trunc(champ).upper()
        ctx["champ_team"] = _trunc(champ_t).upper()
        # Extract opponent if the champion fought this turn
        for w_data in winners_list:
            if w_data["warrior"].lower() == champ.lower():
                ctx["opponent"] = _trunc(w_data["opponent"]).upper()
                break
        p1.append(_pick_block(_BLK_CHAMP_INCUMBENT, used, ctx))
    elif not champ:
        p1.append(_pick_block(_BLK_CHAMP_VACANT, used, ctx))

    paragraphs.append("  ".join(p1))

    # ==================================================================
    # PARAGRAPH 2 - TEAM PERFORMANCES + STANDINGS PERSPECTIVE
    # Best team, worst team, a middle-pack note, and a broader standings look.
    # ==================================================================
    p2 = []

    if best_name and best_rec:
        ctx["team"]        = _trunc(best_name).upper()
        ctx["record"]      = f"{best_rec['w']}-{best_rec['l']}-{best_rec['k']}"
        ctx["rank_change"] = ("advancing in the standings" if best_rec["w"] > best_rec["l"]
                              else "holding steady" if best_rec["w"] == best_rec["l"]
                              else "sliding in the standings")
        p2.append(_pick_block(_BLK_TEAM_PERF, used, ctx))

    # Worst team (if genuinely different and had a losing record)
    if worst_name and worst_rec and worst_name != best_name and worst_rec["l"] > worst_rec["w"]:
        ctx["team"]   = _trunc(worst_name).upper()
        ctx["record"] = f"{worst_rec['w']}-{worst_rec['l']}-{worst_rec['k']}"
        p2.append(_pick_block(_BLK_WORST_TEAM, used, ctx))

    # Second notable team from the middle of the pack
    if middle_teams:
        mt_name, mt_rec = random.choice(middle_teams)
        if mt_name not in _NPC_TEAM_NAMES:
            ctx["team"]   = _trunc(mt_name).upper()
            ctx["record"] = f"{mt_rec['w']}-{mt_rec['l']}-{mt_rec['k']}"
            p2.append(_pick_block(_BLK_SECOND_TEAM, used, ctx))

    # Broader standings perspective
    p2.append(_pick_block(_BLK_STANDINGS_LOOK, used, ctx))

    if p2:
        paragraphs.append("  ".join(p2))

    # ==================================================================
    # PARAGRAPH 3 - WARRIOR HIGHLIGHTS: RISERS AND FALLERS
    # Cover top 2 winners and top 2 notable losers.
    # ==================================================================
    p3 = []

    # Top two winner spotlights
    for w_data in winners_list[:2]:
        ctx["warrior"]  = _trunc(w_data["warrior"]).upper()
        ctx["team"]     = _trunc(w_data["team"]).upper()
        ctx["opponent"] = _trunc(w_data["opponent"]).upper()
        ctx["points"]   = str(w_data["recs"])
        p3.append(_pick_for(_BLK_WARRIOR_RISER, w_data["warrior"]))

    # Up to two notable losers (skip killed warriors - they get their own paragraph)
    used_warriors = {w["warrior"] for w in winners_list[:2]}
    notable_losers = [x for x in losers_list
                      if not x["is_kill"] and x["recs"] > 10
                      and x["warrior"] not in used_warriors]
    for l_data in notable_losers[:2]:
        ctx["warrior"]  = _trunc(l_data["warrior"]).upper()
        ctx["team"]     = _trunc(l_data["team"]).upper()
        ctx["opponent"] = _trunc(l_data["opponent"]).upper()
        ctx["points"]   = str(l_data["recs"])
        p3.append(_pick_for(_BLK_WARRIOR_FALLER, l_data["warrior"]))

    # If we have a third notable winner and no good loser story, spotlight them
    if len(notable_losers) < 1 and len(winners_list) > 2:
        w2 = winners_list[2]
        ctx["warrior"]  = _trunc(w2["warrior"]).upper()
        ctx["team"]     = _trunc(w2["team"]).upper()
        ctx["opponent"] = _trunc(w2["opponent"]).upper()
        ctx["points"]   = str(w2["recs"])
        p3.append(_pick_for(_BLK_WARRIOR_HI, w2["warrior"]))

    if p3:
        paragraphs.append("  ".join(p3))

    # ==================================================================
    # PARAGRAPH 3B - BLOOD CHALLENGE BULLYING / UNDERDOG / COMMISSION
    # ==================================================================
    p3b = []
    for ev in (bully_events or []):
        ctx["warrior"]  = _trunc(ev["warrior"]).upper()
        ctx["team"]     = _trunc(ev["team"]).upper()
        ctx["opponent"] = _trunc(ev["opponent"]).upper()
        if ev["kind"] == "bully_shamed":
            p3b.append(_pick_for(_BLK_BULLY_SHAMED, ev["warrior"]))
        elif ev["kind"] == "underdog_inspired":
            p3b.append(_pick_for(_BLK_UNDERDOG_INSPIRED, ev["warrior"]))

        if ev.get("stripped"):
            # The stripped champion is ev["warrior"]; ctx["champion"] holds whoever
            # holds the title *now*, so point {champion} at the stripped warrior.
            _kept_champion = ctx["champion"]
            ctx["champion"] = _trunc(ev["warrior"]).upper()
            p3b.append(_pick_for(_BLK_CHAMP_STRIPPED_DECISION, ev["warrior"]))
            ctx["champion"] = _kept_champion
            p3b.append(_pick_block(_BLK_CHAMP_STRIPPED_QUOTE, used, ctx))
            new_champ_name = champion_state.get("name", "") if champion_state else ""
            if new_champ_name:
                p3b.append(
                    f"The championship now falls to {_trunc(new_champ_name).upper()}, "
                    "based on their recognized popularity with the masses."
                )
            else:
                p3b.append("With no clear successor to claim the crown, the championship remains vacant for now.")

    if p3b:
        paragraphs.append("  ".join(p3b))

    # ==================================================================
    # PARAGRAPH 4 - CHALLENGE DRAMA + STREAK WARRIORS
    # Notable challenge results and any warriors on extended winning runs.
    # ==================================================================
    p4 = []

    up_wins     = [c for c in challenge_results if c["challenger_won"]  and c["rec_diff"] < 0]
    down_losses = [c for c in challenge_results if not c["challenger_won"] and c["rec_diff"] > 0]

    # Up to two notable challenge results
    if up_wins:
        best = sorted(up_wins, key=lambda x: -x["abs_diff"])[0]
        ctx["warrior"]  = _trunc(best["challenger"]).upper()
        ctx["team"]     = _trunc(best["challenger_team"]).upper()
        ctx["opponent"] = _trunc(best["challenged"]).upper()
        ctx["points"]   = str(best["abs_diff"])
        p4.append(_pick_for(_BLK_CHALLENGE_WIN, best["challenger"]))

    if down_losses:
        worst = sorted(down_losses, key=lambda x: -x["abs_diff"])[0]
        ctx["warrior"]  = _trunc(worst["challenger"]).upper()
        ctx["team"]     = _trunc(worst["challenger_team"]).upper()
        ctx["opponent"] = _trunc(worst["challenged"]).upper()
        ctx["points"]   = str(worst["abs_diff"])
        p4.append(_pick_for(_BLK_CHALLENGE_LOSS, worst["challenger"]))

    # Streak warrior spotlight
    if streak_warriors:
        sw = streak_warriors[0]
        ctx["warrior"] = _trunc(sw["warrior"]).upper()
        ctx["team"]    = _trunc(sw["team"]).upper()
        ctx["streak"]  = str(sw["streak"])
        p4.append(_pick_for(_BLK_STREAK, sw["warrior"]))

    if p4:
        paragraphs.append("  ".join(p4))

    # ==================================================================
    # PARAGRAPH 5 - DIG DEEPER: META, AVOIDANCE, MOST CHALLENGED WARRIOR
    # Only emitted when there is genuine meta content to report.
    # Champion coverage is handled in Para 1; no repeat here.
    # ==================================================================
    p6 = [_pick_block(_BLK_DIG_DEEPER, used, ctx)]

    if most_avoided_team:
        ctx["team"] = _trunc(most_avoided_team).upper()
        p6.append(_pick_block(_BLK_META_TEAM, used, ctx))

    if most_challenged_warrior:
        ctx["warrior"] = _trunc(most_challenged_warrior).upper()
        for bout in unique_bouts:
            if bout.opponent.name == most_challenged_warrior:
                ot = bout.opponent_team
                ctx["team"] = _trunc(ot.team_name if hasattr(ot, "team_name") else ot.get("team_name", "?")).upper()
                break
        p6.append(_pick_for(_BLK_META_WARRIOR, most_challenged_warrior))

    if len(p6) > 1:
        paragraphs.append("  ".join(p6))

    # ==================================================================
    # PARAGRAPH 7 - DEATHS + PHILOSOPHICAL ASIDE
    # Each death gets its own line; multiple deaths get a framing note first.
    # ==================================================================
    p7 = []

    if deaths:
        # When multiple warriors fell, open with a framing note, then spotlight at most 3.
        # Prioritise experienced warriors (most total fights); randomise among ties.
        if len(deaths) >= 2:
            p7.append(_pick_block(_BLK_MULTIPLE_DEATHS, used, ctx))
        spotlight = sorted(
            deaths,
            key=lambda d: (-(d.get("w", 0) + d.get("l", 0) + d.get("k", 0)), random.random())
        )[:3]
        for d in spotlight:
            ctx["warrior"] = _trunc(d["name"]).upper()
            ctx["team"]    = _trunc(d.get("team", "?")).upper()
            ctx["record"]  = f"{d.get('w', 0)}-{d.get('l', 0)}-{d.get('k', 0)}"
            ctx["killer"]  = _trunc(d.get("killed_by", "a foe")).upper()
            p7.append(_pick_for(_BLK_DEATH, d["name"]))

    p7.append(_pick_block(_BLK_PHILOSOPHICAL, used, ctx))

    paragraphs.append("  ".join(p7))

    # ==================================================================
    # PARAGRAPH 7.5 - ELITE SPIRE PROMOTIONS (invited + departed)
    # ==================================================================
    _invited  = [p for p in (promotion_pending or []) if p]
    _departed = [p for p in (promotions       or []) if p and p.get("to_arena") == "elite"]

    if _invited or _departed:
        p_spire = []
        p_spire.append(_pick_block(_BLK_SPIRE_INTRO, used, ctx))

        # Spotlight up to 2 newly-invited warriors
        for inv in _invited[:2]:
            ctx["warrior"] = _trunc(inv.get("name", inv.get("warrior_name", "?"))).upper()
            ctx["team"]    = _trunc(inv.get("team", inv.get("team_name", "?"))).upper()
            ctx["manager"] = inv.get("manager", inv.get("manager_name", "?"))
            ctx["record"]  = inv.get("record", "")
            p_spire.append(_pick_block(_BLK_SPIRE_INVITED, used, ctx))

        # Spotlight up to 2 warriors who actually departed this turn
        for dep in _departed[:2]:
            ctx["warrior"] = _trunc(dep.get("warrior_name", dep.get("name", "?"))).upper()
            ctx["team"]    = _trunc(dep.get("team_name",    dep.get("team",  "?"))).upper()
            ctx["manager"] = dep.get("manager_name", dep.get("manager", "?"))
            ctx["record"]  = dep.get("record", "")
            p_spire.append(_pick_block(_BLK_SPIRE_DEPARTED, used, ctx))

        paragraphs.append("  ".join(p_spire))

    # ==================================================================
    # PARAGRAPH 8 - OUTRO / SIGN-OFF
    # ==================================================================
    paragraphs.append(_pick_block(_BLK_OUTRO, used, ctx))

    article = "\n\n".join(paragraphs)
    return f"\n\n{HDR_RED_LG}Arena Happenings{HDR_RESET}\n\n" + article


# ---------------------------------------------------------------------------
# ELITE SPIRE - HISTORY-DRIVEN NARRATIVE (rivalries, streaks, deaths, arrivals)
# Facts come from each warrior's fight_history (arena == "elite" entries).
# ---------------------------------------------------------------------------

_ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
             6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth"}


def _ordinal(n: int) -> str:
    return _ORDINALS.get(n, f"{n}th")


def _elite_hist(w_obj, arena: str = "elite") -> list:
    """The warrior's fight_history entries fought in the given immortal arena."""
    return [f for f in (getattr(w_obj, "fight_history", None) or [])
            if isinstance(f, dict) and f.get("arena") == arena]


def _elite_meetings(w_obj, opp_name: str, before_turn: int, arena: str = "elite") -> list:
    """Results ('win'/'loss') of w_obj against opp_name in earlier turns of this arena."""
    return [f.get("result") for f in _elite_hist(w_obj, arena)
            if f.get("opponent_name") == opp_name and (f.get("turn") or 0) < before_turn]


def _elite_deaths(w_obj, arena: str = "elite") -> int:
    return sum(1 for f in _elite_hist(w_obj, arena) if f.get("warrior_slain"))


def _elite_kills(w_obj, arena: str = "elite") -> int:
    return sum(1 for f in _elite_hist(w_obj, arena) if f.get("is_kill"))


def _elite_streak(w_obj, arena: str = "elite") -> int:
    n = 0
    for f in reversed(_elite_hist(w_obj, arena)):
        if f.get("result") == "win":
            n += 1
        else:
            break
    return n


def _new_arrival_info(w_obj, turn_num: int, arena: str = "elite"):
    """(mortal_wins, mortal_losses, first_result, first_opponent) if this is the
    warrior's first turn in this immortal arena, else None."""
    eh = _elite_hist(w_obj, arena)
    if not eh or any((f.get("turn") or 0) != turn_num for f in eh):
        return None
    mortal = [f for f in (getattr(w_obj, "fight_history", None) or [])
              if isinstance(f, dict) and f.get("arena") != arena]
    mw = sum(1 for f in mortal if f.get("result") == "win")
    ml = sum(1 for f in mortal if f.get("result") == "loss")
    if not mortal:
        mw, ml = getattr(w_obj, "wins", 0) or 0, getattr(w_obj, "losses", 0) or 0
    return mw, ml, eh[-1].get("result"), eh[-1].get("opponent_name", "")


_BLK_ELITE_REMATCH_AVENGED = [
    "{warrior} had a score to settle with {opponent}.  The last meeting went the other way.  This one did not.",
    "The earlier fight between {warrior} and {opponent} was lost by {warrior}, and {warrior} did not forget it.  This turn the account was balanced.",
    "Some fighters carry a loss for a long time.  {warrior} carried the one {opponent} handed over for exactly as long as it took to meet {opponent} again.",
    "{opponent} won the first meeting.  {warrior} won the one that mattered more, the rematch.",
    "There was history between {warrior} and {opponent} before this turn, and {warrior} was on the wrong side of it.  The ledger now reads differently.",
    "Revenge is a poor reason to fight and an excellent reason to win.  {warrior} proved it against {opponent} this turn.",
    "{warrior} asked for another chance at {opponent}, and received one.  The result did not require a second request.",
]

_BLK_ELITE_REMATCH_REPEAT = [
    "{opponent} wanted a second look at {warrior}.  The second look produced the same result as the first.",
    "These two have met before, and {warrior} won then, too.  {opponent} came back with a plan.  The plan did not survive contact with {warrior}.",
    "{warrior} defeated {opponent} again.  At this point the pairing is starting to look less like a rivalry and more like a habit.",
    "{opponent} had every reason to expect a different outcome the {nth} time around against {warrior}.  The sand disagreed.",
    "The crowd knew how the last meeting of {warrior} and {opponent} ended.  The {nth} meeting ended the same way, and nobody in the stands seemed surprised.",
    "Familiarity is supposed to favour the loser of an earlier fight.  {opponent} found, once again, that it favours {warrior}.",
]

_BLK_ELITE_RIVALRY_SERIES = [
    "That makes {n} meetings between {warrior} and {opponent} in the Spire, and {warrior} now leads the series {a} to {b}.",
    "The {nth} fight between these two, and {warrior} now stands {a} to {b} over {opponent}.  The series is not finished, but it is leaning.",
    "{warrior} against {opponent}, {nth} time.  The tally in this feud now reads {a}-{b} in {warrior}'s favour.",
    "If anyone is keeping a ledger of {warrior} and {opponent}, and in this circuit someone always is, the count after {n} fights is {a} to {b}.",
]

_BLK_ELITE_STREAK = [
    "{warrior} has now won {streak} straight in the Spire.  The stretch is starting to attract attention it did not ask for.",
    "{streak} consecutive wins for {warrior}.  The rest of the circuit has begun looking at the schedule with some concern.",
    "{warrior} of {team} extended the winning streak to {streak}.  The question is no longer whether it will end, but who will end it.",
    "Count the wins and the number is {streak}.  {warrior} has not lost in the Spire since the streak began, and no one seems able to arrange it.",
    "A streak of {streak} is a rare thing in {arena}.  {warrior} is currently living through one.",
]

_BLK_ELITE_FALLEN_COUNT = [
    "{opponent} has now fallen {deaths} times in the Spire.  Every time, {opponent} came back and kept fighting.  Most would call that stubbornness.",
    "This was the {nth_death} death on {opponent}'s record in {arena}.  The record also notes, without comment, that {opponent} is still here.",
    "{deaths} deaths, and {opponent} remains on the card.  The Spire does not ask whether that is courage or habit.",
    "The tally of {opponent}'s deaths in the Spire now stands at {deaths}.  No one has found a number that stops {opponent} from showing up.",
]

_BLK_ELITE_KILLER_COUNT = [
    "That makes {kills} kills for {warrior} in the Spire.  The Spire gives the fallen back, but it does not make the work any less deliberate.",
    "{warrior} has now killed {kills} times in {arena}.  Opponents are beginning to notice.",
    "Kill number {kills} in the Spire for {warrior}.  The crowd noticed before the bell stopped ringing.",
]

_BLK_ELITE_NEW_ARRIVAL = [
    "New to the Spire this turn is {warrior} of {team}, who arrives from the mortal arena with a record of {mortal_record}.  {arrival_result}",
    "Welcome, {warrior}.  {team}'s newest ascendant came up with a mortal record of {mortal_record} and wasted no time in the Spire.  {arrival_result}",
    "{warrior} of {team} has crossed over.  The mortal ledger closes at {mortal_record}, and a new one opens here.  {arrival_result}",
    "The Spire has a new name on its roster.  {warrior} of {team} was called up with {mortal_record} behind them.  {arrival_result}",
    "From the mortal sands to the Spire: {warrior} of {team}, {mortal_record} in the old arena and starting over here.  {arrival_result}",
]

_BLK_ELITE_DEATH = [
    "{warrior} of {team} killed {opponent} this turn.  In most places that sentence ends the story.  Here, it begins a different one.",
    "{opponent} fell to {warrior}, and fell for good, as far as the sand was concerned.  The Spire has other plans, but the fight itself was no less final for it.",
    "I do not enjoy reporting a death, even here.  {warrior} ended {opponent}'s bout permanently in every way that mattered to those watching.",
    "The most talked-about moment of the turn was {warrior} over {opponent}.  The kill was clean, the crowd was silent, and nobody mistook it for a formality.",
    "{opponent} did not walk off the sand under {his} own power.  {warrior} saw to that.  The gods keep their own schedule, and it is not one the fallen get to see.",
    "Death visited the Spire through {warrior} of {team}, and {opponent} was the one who answered the door.  The crowd took a moment before it remembered how to cheer.",
    "A kill, plain and simple.  {warrior} did it, {opponent} suffered it, and the sand drank the evidence.  Whatever follows belongs to the gods.",
    "{warrior} dropped {opponent} for the last time that afternoon.  The fall was real.  What the Spire does with it afterward is not for the crowd to see.",
    "Not every fight in {arena} ends with a handshake.  {warrior} of {team} ended this one with {opponent} on the sand and nothing left to argue about.",
    "{opponent} went down to {warrior} and did not get back up.  A hush, a nod from the Blood Master, and the matter was closed.  For now.",
    "The Spire claims its due, now and then.  This turn it claimed {opponent}, by way of {warrior}.  The compact will have its say, as it always does, but only after the fact.",
    "Let the record show that {warrior} of {team} killed {opponent} in turn {turn}.  The record will also show a great deal of silence in the stands afterward.",
]

_BLK_ELITE_LORE = [
    "Every ascended fighter remembers the shield bout, the last fight under mortal rules, the one the gods allow to be survived or not.  After that comes the Call, and after the Call, the Spire.  Nothing about it has ever been gentle.",
    "The Compact is simple to state and hard to live with: the Spire may take a fighter's life, but it may not keep it.  It is why the stakes here are as high as they are and as strange.",
    "Ask any warrior in the Spire what the Call felt like and you will get a different answer each time.  The only thing they agree on is that there was no refusing it.",
    "The gods do not attend every fight.  They do not need to.  The Spire is theirs, and its sand remembers everything that is spilled on it.",
    "There is an old saying among the ascended: in the mortal arena you fight to survive, and in the Spire you fight to be remembered.  The second is harder.",
    "The Blood Master does not take sides in the Spire.  The Blood Master takes notes, and the gods read them.",
    "The Spire has no walls that matter.  What holds the fighters in is the Compact, and the Compact was never written down by anyone who could be argued with.",
    "Some say the Spire is a reward.  Some say it is a sentence.  The honest answer is that it is both, and that the difference depends entirely on whether you won last turn.",
    "It is said the first fighter to be called to the Spire asked the gods what they wanted in return.  The gods are said to have laughed.  They have been collecting ever since.",
    "No one remembers who first called the Spire's arena the summit.  Everyone who has fought there remembers that it is exactly as far from the bottom as it sounds.",
]

# One short aside per columnist - a distinct voice for each byline.
# Placeholders: {champion}, {fights}, {kills}, {arena}, {turn}
_BLK_ELITE_VOICES = {
    "Vesper Crane": [
        "I have been told the turn went well.  I have been told this by people who profit from the turn going well.  Draw your own conclusions.",
        "A good turn, as these things go, and I say that with the tepid enthusiasm the occasion deserves.",
        "{fights} bouts, {kills} of them fatal, and a crowd that cheered for all of them.  I will let you decide what that says about us.",
        "Applaud the winners if you must.  I will wait to see whether they still deserve it by the end of next turn.",
    ],
    "Orryn Ashvale": [
        "In my years of keeping the chronicle of {arena}, I have seen turns like this one perhaps a dozen times.  Each time, the one who looked inevitable was not.",
        "The records suggest that {champion} is in good company.  The records also suggest that every name before it is gone from the top.",
        "I set down turn {turn} in the chronicle with the usual care.  History has a way of rewarding the careful recorder.",
        "To the young ones who read this: remember today's names.  They will be asked about at some point, I assure you.",
    ],
    "Mirelle Stonequill": [
        "By the numbers: {fights} bouts this turn, {kills} kills.  The raw count tells less than the shape of it, which is what I am here for.",
        "A turn of {fights} fights offers only a small sample, but small samples have sunk large reputations before.",
        "The data on {champion} remains thin, which is the only reason anyone still doubts it.",
        "If you want the real story of turn {turn}, ignore the headlines and read the margins.  The margins are where the numbers live.",
    ],
    "Thalric Voss": [
        "There is a beauty in a good fight that no record can capture, and turn {turn} had several.  I wish I could bottle them.",
        "To watch {champion} work is to understand why anyone bothers with this at all.  That is not a small thing.",
        "The crowd knew.  They always know.  Something in the air of {arena} told them this turn would be remembered.",
        "I have long believed the Spire is at its best when it hurts to watch.  This turn I believed it again.",
    ],
    "Corwin Evenmere": [
        "I do not pretend to understand the gods' business, but I notice they take an interest in {champion}.  Interpret that however you like.",
        "Faith in the Spire is a funny thing.  Faith in the Compact is stranger still.  I keep both, and neither makes the work easier.",
        "If the gods are watching turn {turn}, I hope they enjoyed it.  I certainly was not asked for my opinion beforehand.",
        "A reminder that what returns from the sand is not always what went onto it.  The Compact is generous, not perfect.",
    ],
    "Isolde Ravenmere": [
        "I hear things in the corridors, and what I hear is that the managers are already scheming.  I will name no names.  Not yet.",
        "The word going round the Spire is that the next few turns will be interesting.  Interesting people are saying it.",
        "{champion} is going to hear a great deal of company in the weeks ahead.  Some of it will be friendly.",
        "Rumour has it that not everyone at {arena} is as pleased with the standings as they pretend.  I know a few who are not.",
    ],
    "Aldrik Fenmoor": [
        "Plain and simple: {champion} is the fighter to beat, and the rest of the card knows it.  Turn {turn} did nothing to change that.",
        "Short version: good fights, a few good upsets, and a card that will look different next turn.  That is how it should be.",
        "Bottom line from the desk: {fights} fights, one champion, and plenty of reasons to keep watching.",
        "I will keep this brief.  Winners won, losers will try again, and the Spire does not care which is which.",
    ],
    "Nessa Blackthorn": [
        "The Spire does not weep for the fallen.  I do, a little, and then I go back to work, because the record will not write itself.",
        "{kills} of the turn's fights ended in death.  The Compact softens the blow.  It does not soften the sound.",
        "I remember the names of the ones who fell, even when the gods hand them back.  Someone ought to.",
        "Turn {turn} is done.  The sand has been raked.  The stains are the part it cannot reach.",
    ],
}


_PRONOUN_RE = re.compile(r"\{(he|He|him|Him|his|His|himself|Himself|she|She|her|Her|herself|Herself)\}")


def _set_elite_pronouns(ctx: dict, gender: str) -> None:
    """Set he/him/his/himself pronouns in ctx based on warrior gender."""
    if (gender or "").lower().startswith("f"):
        ctx.update(he="she", He="She", his="her", His="Her",
                   him="her", Him="Her", himself="herself", Himself="Herself")
    else:
        ctx.update(he="he", He="He", his="his", His="His",
                   him="him", Him="Him", himself="himself", Himself="Himself")


def _block_commentary_elite(
    card, teams, turn_num: int,
    arena_name: str = "THE ELITE SPIRE",
    arena_warriors=None,
    prev_champion_name: str = None,
    champion_name: str = None,
) -> str:
    """
    Generate narrative Arena Happenings prose for immortal arenas.

    card           - list of fight objects (BoutWrapper or SimpleNamespace)
    teams          - list of Team objects (unused directly, kept for signature parity)
    turn_num       - current turn number
    arena_name     - display name, e.g. "THE ELITE SPIRE"
    arena_warriors - list of (warrior_obj, team_obj) for champion + upset detection
    """
    venue  = "The Spire" if "ELITE" in arena_name.upper() else "The Grounds"
    byline = random.choice(_BLK_ELITE_BYLINES)
    used   = set()

    # ── Deduplicate: card may list each bout from both teams' POV ─────────────
    seen_ids   = set()
    unique_bouts = []
    for bout in card:
        fid = getattr(bout, "fight_id", None)
        if fid is not None:
            if fid in seen_ids:
                continue
            seen_ids.add(fid)
        else:
            pw = getattr(bout.player_warrior, "name", "?")
            op = getattr(bout.opponent,       "name", "?")
            pair = tuple(sorted([pw, op]))
            if pair in seen_ids:
                continue
            seen_ids.add(pair)
        if bout.result:
            unique_bouts.append(bout)

    # ── Warrior win-count lookup (for upset detection) ─────────────────────────
    # Lifetime wins (all arenas) - career record is what makes an upset an upset.
    w_wins = {}
    _genders = {}
    if arena_warriors:
        for w_obj, _ in arena_warriors:
            w_wins[w_obj.name] = getattr(w_obj, "wins", 0) or 0
            _genders[w_obj.name] = getattr(w_obj, "gender", "Male") or "Male"

    def _gender_of(name):
        return _genders.get(name, "Male")

    # ── Team records for this turn ────────────────────────────────────────────
    team_turn = {}
    for bout in unique_bouts:
        if not (bout.result and bout.result.winner):
            continue
        wname   = getattr(bout.result.winner,  "name", "")
        pw_name = getattr(bout.player_warrior, "name", "")
        pw_team = (getattr(bout.player_team,   "team_name", None)
                   or getattr(bout.player_team, "manager_name", "?"))
        op_team = (getattr(bout.opponent_team, "team_name", None)
                   or getattr(bout.opponent_team, "manager_name", "?"))
        pw_won  = (wname == pw_name)
        w_team  = pw_team if pw_won else op_team
        l_team  = op_team if pw_won else pw_team
        team_turn.setdefault(w_team, {"w": 0, "l": 0})["w"] += 1
        team_turn.setdefault(l_team, {"w": 0, "l": 0})["l"] += 1

    # ── Dynamic fight duration classification ─────────────────────────────────
    # Compare each fight against the turn's own distribution rather than fixed
    # thresholds. Short = at/below median; Long = above median (top outliers).
    durations   = sorted(b.result.minutes_elapsed for b in unique_bouts if b.result)
    median_dur  = durations[len(durations) // 2] if durations else 3
    short_bouts = sorted(
        [b for b in unique_bouts if b.result and b.result.minutes_elapsed <= median_dur],
        key=lambda b: b.result.minutes_elapsed,
    )
    long_bouts  = sorted(
        [b for b in unique_bouts if b.result and b.result.minutes_elapsed > median_dur],
        key=lambda b: b.result.minutes_elapsed, reverse=True,
    )

    # ── Deaths this turn ──────────────────────────────────────────────────────
    death_bouts = [b for b in unique_bouts if getattr(b.result, "loser_died", False)]

    # ── Champion detection (highest recognition among arena warriors) ──────────
    champion_w, champion_t = None, None
    if arena_warriors:
        best = sorted(arena_warriors, key=lambda x: _arena_champion_sort_key(x[0]))
        if champion_name:
            # The champion is whoever the arena's champion rules crowned this turn
            best = [b for b in best if b[0].name == champion_name] or best
        if best:
            champion_w, champion_t = best[0]

    # ── Context dict ──────────────────────────────────────────────────────────
    ctx = dict(
        arena=arena_name, venue=venue, byline=byline,
        turn=turn_num, next_turn=turn_num + 1,
        warrior="", opponent="", Opponent="",
        team="", team2="",
        champion="", champ_team="", prev_champion="",
        wins="", duration="", minutes="", record="",
        points="", streak="", killer="", killer_team="", rank_change="",
        he="he", He="He", his="his", His="His",
        him="him", Him="Him", himself="himself", Himself="Himself",
        she="she", She="She", her="her", Her="Her",
        herself="herself", Herself="Herself",
        they="they", their="their", them="them",
    )

    paragraphs = []

    # ── PARA 1: Opening ───────────────────────────────────────────────────────
    pool = _BLK_ELITE_OPENING_DEATH if death_bouts else _BLK_ELITE_OPENING
    paragraphs.append(_pick_block(pool, used, ctx))

    # ── PARA 2: Champion ──────────────────────────────────────────────────────
    if champion_w:
        ctx["champion"]   = _trunc(champion_w.name).upper()
        ctx["champ_team"] = _trunc(
            getattr(champion_t, "team_name", None) or str(champion_t)
        ).upper()
        ctx["wins"] = str(getattr(champion_w, "wins", "?"))
        _set_elite_pronouns(ctx, getattr(champion_w, "gender", "Male") or "Male")

        # Look for a fight involving the champion this turn
        champ_fight = next(
            (b for b in unique_bouts
             if b.result and champion_w.name in (
                 getattr(b.player_warrior, "name", ""),
                 getattr(b.opponent,       "name", ""),
             )),
            None,
        )

        if champ_fight:
            c_won = (getattr(champ_fight.result.winner, "name", "") == champion_w.name)
            pw_name = getattr(champ_fight.player_warrior, "name", "")
            if pw_name == champion_w.name:
                other_name = getattr(champ_fight.opponent, "name", "?")
            else:
                other_name = pw_name
            ctx["opponent"] = _trunc(other_name).upper()
            ctx["duration"] = _fight_style_word(champ_fight.result.minutes_elapsed)
            ctx["minutes"]  = str(champ_fight.result.minutes_elapsed)

            # A "new champion" story only when the saved title-holder actually changed
            if prev_champion_name and prev_champion_name != champion_w.name:
                ctx["prev_champion"] = _trunc(prev_champion_name).upper()
                pool = _BLK_ELITE_CHAMP_NEW
            else:
                pool = _BLK_ELITE_CHAMP_INCUMBENT
        else:
            if prev_champion_name and prev_champion_name != champion_w.name:
                ctx["prev_champion"] = _trunc(prev_champion_name).upper()
                pool = _BLK_ELITE_CHAMP_NEW
            else:
                pool = _BLK_ELITE_CHAMP_INCUMBENT
    else:
        pool = _BLK_ELITE_CHAMP_VACANT

    paragraphs.append(_pick_block(pool, used, ctx))

    # ── PARA 3: Short / dominant fights ──────────────────────────────────────
    def _get_winner_loser_team(bout):
        wname   = getattr(bout.result.winner,  "name", "?") if bout.result.winner else "?"
        pw_name = getattr(bout.player_warrior, "name", "")
        loser   = bout.opponent if pw_name == wname else bout.player_warrior
        pw_team = (getattr(bout.player_team,   "team_name", None)
                   or getattr(bout.player_team, "manager_name", "?"))
        op_team = (getattr(bout.opponent_team, "team_name", None)
                   or getattr(bout.opponent_team, "manager_name", "?"))
        w_team  = pw_team if pw_name == wname else op_team
        return wname, getattr(loser, "name", "?"), w_team

    sentences = []
    for bout in short_bouts[:4]:
        if not (bout.result and bout.result.winner):
            continue
        wname, lname, w_team = _get_winner_loser_team(bout)
        ctx["warrior"]  = _trunc(wname).upper()
        ctx["opponent"] = _trunc(lname).upper()
        ctx["Opponent"] = ctx["opponent"]
        ctx["team"]     = _trunc(w_team).upper()
        ctx["duration"] = _fight_style_word(bout.result.minutes_elapsed)
        ctx["minutes"]  = str(bout.result.minutes_elapsed)
        _set_elite_pronouns(ctx, _gender_of(wname))
        sentences.append(_pick_block(_BLK_ELITE_DOMINANT, used, ctx))
    if sentences:
        paragraphs.append("  ".join(sentences))

    # ── PARA 4: Long / compelling fights ─────────────────────────────────────
    sentences = []
    for bout in long_bouts[:3]:
        if not (bout.result and bout.result.winner):
            continue
        wname, lname, w_team = _get_winner_loser_team(bout)
        ctx["warrior"]  = _trunc(wname).upper()
        ctx["opponent"] = _trunc(lname).upper()
        ctx["Opponent"] = ctx["opponent"]
        ctx["team"]     = _trunc(w_team).upper()
        ctx["duration"] = _fight_style_word(bout.result.minutes_elapsed)
        ctx["minutes"]  = str(bout.result.minutes_elapsed)
        _set_elite_pronouns(ctx, _gender_of(wname))
        sentences.append(_pick_block(_BLK_ELITE_COMPELLING, used, ctx))
    if sentences:
        paragraphs.append("  ".join(sentences))

    # ── PARA 5: Upsets ────────────────────────────────────────────────────────
    upset_bouts = [
        b for b in unique_bouts
        if b.result and b.result.winner
        and w_wins.get(getattr(b.result.winner, "name", ""), 0)
           < w_wins.get(
               getattr(b.opponent if getattr(b.player_warrior, "name", "") == getattr(b.result.winner, "name", "") else b.player_warrior, "name", ""),
               0,
           )
    ]
    sentences = []
    for bout in upset_bouts[:3]:
        wname, lname, w_team = _get_winner_loser_team(bout)
        ctx["warrior"]  = _trunc(wname).upper()
        ctx["opponent"] = _trunc(lname).upper()
        ctx["Opponent"] = ctx["opponent"]
        ctx["team"]     = _trunc(w_team).upper()
        ctx["duration"] = _fight_style_word(bout.result.minutes_elapsed)
        ctx["minutes"]  = str(bout.result.minutes_elapsed)
        # {he}/{himself} refer to the winner; {him} refers to the beaten opponent
        _set_elite_pronouns(ctx, _gender_of(wname))
        _lose_f = _gender_of(lname).lower().startswith("f")
        ctx["him"], ctx["Him"] = ("her", "Her") if _lose_f else ("him", "Him")
        sentences.append(_pick_block(_BLK_ELITE_UPSET, used, ctx))
    if sentences:
        paragraphs.append("  ".join(sentences))

    # ── PARA 5b: Old scores - rematches and series, from fight history ───────
    _wobj = {w.name: w for w, _ in (arena_warriors or [])}

    def _ctx_bout(wname, lname, w_team):
        ctx["warrior"]  = _trunc(wname).upper()
        ctx["opponent"] = _trunc(lname).upper()
        ctx["Opponent"] = ctx["opponent"]
        ctx["team"]     = _trunc(w_team).upper()

    rivalry = []
    for bout in unique_bouts:
        if not (bout.result and bout.result.winner):
            continue
        wname, lname, w_team = _get_winner_loser_team(bout)
        wo = _wobj.get(wname)
        prior = _elite_meetings(wo, lname, turn_num) if wo is not None else []
        if prior:
            rivalry.append((len(prior), wname, lname, w_team, prior))
    rivalry.sort(key=lambda r: -r[0])
    sentences = []
    for n_prior, wname, lname, w_team, prior in rivalry[:2]:
        _ctx_bout(wname, lname, w_team)
        meetings = n_prior + 1
        ctx.update(n=str(meetings), nth=_ordinal(meetings),
                   a=str(prior.count("win") + 1), b=str(prior.count("loss")))
        text = _pick_block(
            _BLK_ELITE_REMATCH_AVENGED if prior[-1] == "loss" else _BLK_ELITE_REMATCH_REPEAT,
            used, ctx)
        if meetings >= 3:
            text += "  " + _pick_block(_BLK_ELITE_RIVALRY_SERIES, used, ctx)
        sentences.append(text)
    if sentences:
        paragraphs.append("  ".join(sentences))

    # ── PARA 5c: Streaks ──────────────────────────────────────────────────────
    streaks, seen_streak = [], set()
    for bout in unique_bouts:
        if not (bout.result and bout.result.winner):
            continue
        wname, lname, w_team = _get_winner_loser_team(bout)
        wo = _wobj.get(wname)
        st = _elite_streak(wo) if wo is not None else 0
        if st >= 3 and wname not in seen_streak:
            seen_streak.add(wname)
            streaks.append((st, wname, lname, w_team))
    sentences = []
    for st, wname, lname, w_team in sorted(streaks, reverse=True)[:2]:
        _ctx_bout(wname, lname, w_team)
        ctx["streak"] = str(st)
        sentences.append(_pick_block(_BLK_ELITE_STREAK, used, ctx))
    if sentences:
        paragraphs.append("  ".join(sentences))

    # ── PARA 5d: New arrivals ─────────────────────────────────────────────────
    sentences, seen_arr = [], set()
    for bout in unique_bouts:
        for side, side_team in ((bout.player_warrior, bout.player_team),
                                (bout.opponent,       bout.opponent_team)):
            nm = getattr(side, "name", "")
            wo = _wobj.get(nm)
            if wo is None or nm in seen_arr:
                continue
            info = _new_arrival_info(wo, turn_num)
            if not info:
                continue
            seen_arr.add(nm)
            mw, ml, first_res, first_opp = info
            if first_res == "win":
                res_txt = f"The opening bout went to {_trunc(nm).upper()}, over {_trunc(first_opp).upper()}."
            else:
                res_txt = f"The opening bout went to {_trunc(first_opp).upper()}, who beat {_trunc(nm).upper()}."
            ctx.update(
                warrior=_trunc(nm).upper(),
                team=_trunc(getattr(side_team, "team_name", None) or "?").upper(),
                mortal_record=f"{mw}-{ml}", arrival_result=res_txt,
            )
            sentences.append(_pick_block(_BLK_ELITE_NEW_ARRIVAL, used, ctx))
    if sentences:
        paragraphs.append("  ".join(sentences[:3]))

    # ── PARA 6: Deaths ────────────────────────────────────────────────────────
    if death_bouts:
        sentences = []
        for bout in death_bouts[:3]:
            wname, lname, w_team = _get_winner_loser_team(bout)
            _ctx_bout(wname, lname, w_team)
            # Death templates use {his}/{he} for the fallen warrior ({opponent})
            _set_elite_pronouns(ctx, _gender_of(lname))
            text = _pick_block(_BLK_ELITE_DEATH, used, ctx)
            lo, wo = _wobj.get(lname), _wobj.get(wname)
            deaths = _elite_deaths(lo) if lo is not None else 0
            kills = _elite_kills(wo) if wo is not None else 0
            if deaths >= 2:
                ctx.update(deaths=str(deaths), nth_death=_ordinal(deaths))
                text += "  " + _pick_block(_BLK_ELITE_FALLEN_COUNT, used, ctx)
            elif kills >= 3:
                ctx["kills"] = str(kills)
                text += "  " + _pick_block(_BLK_ELITE_KILLER_COUNT, used, ctx)
            sentences.append(text)
        paragraphs.append("  ".join(sentences))

    # ── PARA 6b: Columnist's aside - each byline has its own voice ───────────
    voice_lines = [l for l in _BLK_ELITE_VOICES.get(byline.split(",")[0].strip(), [])
                   if champion_w or "{champion}" not in l]
    if voice_lines:
        ctx.update(fights=str(len(unique_bouts)), kills=str(len(death_bouts)))
        paragraphs.append(_pick_block(voice_lines, used, ctx))

    # ── PARA 7: Team standings ────────────────────────────────────────────────
    if team_turn:
        by_wins = sorted(team_turn.items(), key=lambda x: (-x[1]["w"], x[1]["l"]))
        ctx["team"]  = _trunc(by_wins[0][0]).upper()
        ctx["team2"] = _trunc(by_wins[1][0]).upper() if len(by_wins) > 1 else ctx["team"]
        paragraphs.append(_pick_block(_BLK_ELITE_STANDINGS, used, ctx))

    # ── PARA 7b: Occasional lore interlude ────────────────────────────────────
    if random.random() < 0.30:
        paragraphs.append(_pick_block(_BLK_ELITE_LORE, used, ctx))

    # ── PARA 8: Closing ───────────────────────────────────────────────────────
    if champion_w:
        ctx["champion"]   = _trunc(champion_w.name).upper()
        ctx["champ_team"] = _trunc(
            getattr(champion_t, "team_name", None) or str(champion_t)
        ).upper()
    paragraphs.append(_pick_block(_BLK_ELITE_CLOSING, used, ctx))

    article = "\n\n".join(p for p in paragraphs if p.strip())
    return f"\n\n{HDR_RED_LG}Arena Happenings{HDR_RESET}\n\n" + article


# ---------------------------------------------------------------------------
# SOUL SPIRE - HISTORY-DRIVEN NARRATIVE POOLS
# (rematch/streak pools are shared with the Elite Spire; these cover the parts
#  where the Soul Spire's voice differs: the curse and the Soul Keeper, not gods.)
# ---------------------------------------------------------------------------

_BLK_VET_DEATH = [
    "{warrior} of {team} killed {opponent} this turn.  In the soul realm that sentence carries a strange weight.  {opponent} was already dead once.",
    "{opponent} has died again.  In most places I would leave it there.  Here the curse takes over, and the Soul Keeper has the matter in hand.",
    "The particular irony of {arena} produced another entry this turn.  {opponent}, already dead, was killed again by {warrior}.  The realm took it in stride.",
    "Dying a second time is not what it was the first.  {opponent} found that out courtesy of {warrior}, and the curse is already doing its work.",
    "{warrior} of {team} put {opponent} down for good, as far as the sand was concerned.  The Soul Keeper will have other opinions by the next turn.",
    "There are two kinds of dying in {arena}.  The first kind brought the warriors here.  The second kind, which {opponent} just experienced at the hands of {warrior}, is temporary.",
    "The realm claimed {opponent} this turn, by way of {warrior} of {team}.  It will let {opponent} go again in time.  It always does.",
    "I have witnessed many things at {arena}.  A soul dying twice is among the more philosophically interesting.  {opponent} has now seen that philosophy at close range.",
    "{opponent} arrived at {arena} already dead.  This turn {warrior} of {team} made {opponent} dead again, and the curse sorted out the rest.",
    "The death of a soul at {arena} is noteworthy not because it is unusual but because of what it costs.  {opponent} lost not just the fight but the rest of the turn.  {warrior} saw to that.",
    "{warrior} killed {opponent}.  In the soul realm, killing someone who is already dead takes a particular effort.  {warrior} made it, and the Soul Keeper made a note.",
    "Death visited {arena} twice for {opponent}, once long ago on arrival and once just now at the hands of {warrior} of {team}.  The realm has already opened the gate again.",
]

_BLK_VET_OPENING_DEATH = [
    "Turn {turn} at {arena} has produced the particular irony of the soul realm: warriors who are already dead, dying again.  The curse is handling it.",
    "Welcome to {arena}, where dying once was apparently not enough.  Turn {turn} has proved it can happen a second time.",
    "The souls of {arena} know death intimately.  Turn {turn} sent one of them through it again, which the realm treats as a minor matter.",
    "Death visited {arena} this turn, which it does with some regularity despite the fact that everyone here is already dead.",
    "There is a particular kind of irony that lives in {arena}.  The already-dead can be killed.  Turn {turn} demonstrated this with its customary lack of ceremony.",
    "Not all of the souls in {arena} completed turn {turn} on their feet.  Some completed it considerably lower than that.  The realm is already sorting it out.",
    "Turn {turn} at {arena} ends with the Soul Keeper busy.  Souls that have already crossed once are crossing again, and the accounting is considerable.",
    "Even here, in the realm beyond, death finds an audience.  Turn {turn} gave it one.",
    "The warriors of {arena} fight with everything they have because they have already given everything else.  Turn {turn} asked a few of them to give what was left.",
    "I will note, as I always do, that dying twice is considered remarkable in most places.  In {arena}, it is a line in the record.",
    "Turn {turn} has reminded everyone that {arena} is not a safe place for the dead, which is either a comfort or a warning depending on your perspective.",
    "The realm beyond is busier than usual after turn {turn}.  It will settle.  It always does.",
]

_BLK_VET_FALLEN_COUNT = [
    "{opponent} has now died {deaths} times in {arena}.  Every time, the curse sent {opponent} back, and every time {opponent} walked out onto the sand again.",
    "This was the {nth_death} death on {opponent}'s record here.  The record also notes, without comment, that {opponent} is still fighting.",
    "{deaths} deaths, and {opponent} remains on the card.  The realm does not ask whether that is courage or habit.",
    "The tally of {opponent}'s deaths in {arena} now stands at {deaths}.  No one has found a number that keeps {opponent} down.",
]

_BLK_VET_KILLER_COUNT = [
    "That makes {kills} kills for {warrior} in {arena}.  The dead are used to it, though they do not enjoy the attention.",
    "{warrior} has now killed {kills} times here.  The realm keeps count even when the fallen do not.",
    "Kill number {kills} in {arena} for {warrior}.  The curse returned the others.  It does not make the work any lighter.",
]

_BLK_VET_NEW_ARRIVAL = [
    "New to the soul realm this turn is {warrior} of {team}, who crossed over from the mortal arena with a record of {mortal_record}.  {arrival_result}",
    "Welcome to {arena}, {warrior}.  {team}'s newest soul came across with {mortal_record} behind them.  {arrival_result}",
    "{warrior} of {team} has crossed the veil.  The mortal ledger closes at {mortal_record}, and a new one opens here.  {arrival_result}",
    "The realm has a new name on its roster.  {warrior} of {team} carries {mortal_record} from the old arena.  {arrival_result}",
    "From the living sands to the soul realm: {warrior} of {team}, {mortal_record} before the crossing and starting over now.  {arrival_result}",
]

_BLK_VET_LORE = [
    "Every soul in {arena} remembers the crossing.  It was not gentle, and it was not optional.",
    "The curse of the Spire is simple to state and hard to live with: the dead may be killed, and the dead come back.  Nobody here has ever gotten used to it.",
    "The Soul Keeper does not take sides.  The Soul Keeper keeps the ledger, and the ledger keeps everyone.",
    "Ask a warrior in {arena} what the veil feels like and you will get a different answer each time.  The one thing they agree on is that it is thinner here than anywhere.",
    "The ghost-lights over the sand are said to be the ones who did not make it back.  The crowd has stopped looking up at them.",
    "Some say the Spire is a second chance.  Some say it is a sentence served twice.  The honest answer depends on whether you won last turn.",
    "There is an old saying among the dead: the first death is a surprise, the second is a lesson, and the third is a habit.  The ledger of {arena} suggests it is not only a saying.",
    "The Soul Spire does not keep time the way the living do.  Turns pass.  The dead remember all of them.",
    "The ones who retire from the mortal arena do not retire so much as relocate.  {arena} is where they relocate to.",
    "No one remembers who first called the soul realm's arena a spire.  Everyone who has fought there remembers that going up is the hard part.",
]

# One short aside per columnist - a distinct voice for each Soul Spire byline.
_BLK_VET_VOICES = {
    "Varek Duskhollow": [
        "The Soul's Record is accurate to a fault, which is why I record {fights} bouts and not a word more than they contain.",
        "Turn {turn} gave the realm {fights} fights.  I wrote down every one.  Some of them will be the subject of arguments in the corridors for a long time.",
        "{champion} holds the title.  The record does not say how long.  The record is cautious about promises.",
        "A fair turn.  I am told that counts as praise where I come from.",
    ],
    "Maren Ghostveil": [
        "The dead are tired of being surprised, and still turn {turn} found a way to surprise them.",
        "I have spoken to the ones who fell this turn.  They are not talkative, but they are the only honest witnesses I have.",
        "{champion} is the name on the lips of the corridors.  Whether that is admiration or warning, I will let you decide.",
        "The realm hums when something changes.  It hummed on turn {turn}.",
    ],
    "Solen Ashwick": [
        "From where I stand, the realm beyond looks very much like the realm before, only quieter and with worse lighting.",
        "{fights} bouts, {kills} of them fatal, and not a single spectator in the stands who looked surprised.  The dead are a hard crowd to impress.",
        "The champion's seat is never as comfortable as it looks.  {champion} would likely agree.",
        "Turn {turn} was long.  The turns here are always long.  This one was worth it.",
    ],
    "Dara Wraithstone": [
        "The Undying Record notes that nothing here is truly undying, only unfinished.  The distinction matters to those who live by it.",
        "I count {kills} deaths on the ledger for turn {turn}.  The curse will return them.  It will not return the afternoon.",
        "{champion} wears the crown the way the dead wear everything: lightly, and with a certain fatigue.",
        "If you are looking for mercy in {arena}, you are in the wrong realm.  If you are looking for a good fight, welcome.",
    ],
    "Theron Pallmere": [
        "The voices of the fallen are quieter this turn, which is how I know it was a hard one.",
        "I speak for the ones who cannot, and this turn there were {kills} of them.  The curse will give them back.  They will remember.",
        "A word for the champion, {champion}: the voices are listening.",
        "Turn {turn} was loud in the way that only the dead can be loud, which is to say, in memory.",
    ],
    "Caelan Spireveil": [
        "The Soul Spire Dispatch has one rule: be there when it happens.  I was there for all {fights} fights of turn {turn}.",
        "Straight from the sand: a long turn, a stubborn champion in {champion}, and a card that looks different every time I read it.",
        "I have no theory about the curse.  I have a notebook, and the notebook says {kills} died this turn.",
        "If something happens in {arena}, the Dispatch will tell you.  This turn, a lot did.",
    ],
    "Lyria Duskvane": [
        "A scribe of the afterworld learns early that every ending is a draft.  Turn {turn} is simply the latest.",
        "The champion {champion} has been written into the margins of three separate chapters.  The fourth is underway.",
        "I note, for the record that will outlast us all, that {fights} fights took place and not one of them was dull.",
        "My ink has not run dry in {arena}.  It rarely does.",
    ],
    "Ossian Coldreach": [
        "The Departed Chronicle keeps track of those who left.  Turn {turn} added {kills} names, temporarily.",
        "A cold turn.  They are all cold in {arena}.  Some are colder than others.",
        "{champion} stands first on the list.  The Chronicle notes that the list is not a promise.",
        "The realm owes the fallen nothing, and pays it in full anyway.",
    ],
}


def _block_commentary_veteran(
    card, teams, turn_num: int,
    arena_name: str = "THE SOUL SPIRE",
    arena_warriors=None,
    prev_champion_name: str = None,
    champion_name: str = None,
) -> str:
    """Generate narrative Arena Happenings prose for The Soul Spire (veteran arena)."""
    venue  = "The Soul Spire"
    byline = random.choice(_BLK_VET_BYLINES)
    used   = set()

    # ── Deduplicate bouts ────────────────────────────────────────────────────
    seen_ids   = set()
    unique_bouts = []
    for bout in card:
        fid = getattr(bout, "fight_id", None)
        if fid is not None:
            if fid in seen_ids:
                continue
            seen_ids.add(fid)
        else:
            pw = getattr(bout.player_warrior, "name", "?")
            op = getattr(bout.opponent,       "name", "?")
            pair = tuple(sorted([pw, op]))
            if pair in seen_ids:
                continue
            seen_ids.add(pair)
        if bout.result:
            unique_bouts.append(bout)

    # ── Win-count lookup ─────────────────────────────────────────────────────
    w_wins = {}
    _genders = {}
    if arena_warriors:
        for w_obj, _ in arena_warriors:
            w_wins[w_obj.name] = getattr(w_obj, "wins", 0) or 0
            _genders[w_obj.name] = getattr(w_obj, "gender", "Male") or "Male"

    def _gender_of(name):
        return _genders.get(name, "Male")

    # ── Team records this turn ────────────────────────────────────────────────
    team_turn = {}
    for bout in unique_bouts:
        if not (bout.result and bout.result.winner):
            continue
        wname   = getattr(bout.result.winner,  "name", "")
        pw_name = getattr(bout.player_warrior, "name", "")
        pw_team = (getattr(bout.player_team,   "team_name", None)
                   or getattr(bout.player_team, "manager_name", "?"))
        op_team = (getattr(bout.opponent_team, "team_name", None)
                   or getattr(bout.opponent_team, "manager_name", "?"))
        pw_won  = (wname == pw_name)
        w_team  = pw_team if pw_won else op_team
        l_team  = op_team if pw_won else pw_team
        team_turn.setdefault(w_team, {"w": 0, "l": 0})["w"] += 1
        team_turn.setdefault(l_team, {"w": 0, "l": 0})["l"] += 1

    # ── Dynamic duration classification ──────────────────────────────────────
    durations   = sorted(b.result.minutes_elapsed for b in unique_bouts if b.result)
    median_dur  = durations[len(durations) // 2] if durations else 3
    short_bouts = sorted(
        [b for b in unique_bouts if b.result and b.result.minutes_elapsed <= median_dur],
        key=lambda b: b.result.minutes_elapsed,
    )
    long_bouts  = sorted(
        [b for b in unique_bouts if b.result and b.result.minutes_elapsed > median_dur],
        key=lambda b: b.result.minutes_elapsed, reverse=True,
    )

    # ── Deaths ────────────────────────────────────────────────────────────────
    death_bouts = [b for b in unique_bouts if getattr(b.result, "loser_died", False)]

    # ── Champion detection ────────────────────────────────────────────────────
    champion_w, champion_t = None, None
    if arena_warriors:
        best = sorted(arena_warriors, key=lambda x: _arena_champion_sort_key(x[0]))
        if champion_name:
            best = [b for b in best if b[0].name == champion_name] or best
        if best:
            champion_w, champion_t = best[0]

    # ── Context dict ─────────────────────────────────────────────────────────
    ctx = dict(
        arena=arena_name, venue=venue, byline=byline,
        turn=turn_num, next_turn=turn_num + 1,
        warrior="", opponent="", Opponent="",
        team="", team2="",
        champion="", champ_team="", prev_champion="",
        wins="", duration="", minutes="", record="",
        he="he", He="He", his="his", His="His",
        him="him", Him="Him", himself="himself", Himself="Himself",
    )

    paragraphs = []

    # Para 1: Opening
    pool = _BLK_VET_OPENING_DEATH if death_bouts else _BLK_VET_OPENING
    paragraphs.append(_pick_block(pool, used, ctx))

    # Para 2: Champion
    if champion_w:
        ctx["champion"]   = _trunc(champion_w.name).upper()
        ctx["champ_team"] = _trunc(
            getattr(champion_t, "team_name", None) or str(champion_t)
        ).upper()
        ctx["wins"] = str(getattr(champion_w, "wins", "?"))
        _set_elite_pronouns(ctx, getattr(champion_w, "gender", "Male") or "Male")

        champ_fight = next(
            (b for b in unique_bouts
             if b.result and champion_w.name in (
                 getattr(b.player_warrior, "name", ""),
                 getattr(b.opponent,       "name", ""),
             )),
            None,
        )
        if champ_fight:
            c_won   = (getattr(champ_fight.result.winner, "name", "") == champion_w.name)
            pw_name = getattr(champ_fight.player_warrior, "name", "")
            other   = getattr(champ_fight.opponent, "name", "?") if pw_name == champion_w.name else pw_name
            ctx["opponent"] = _trunc(other).upper()
            ctx["minutes"]  = str(champ_fight.result.minutes_elapsed)
            if prev_champion_name and prev_champion_name != champion_w.name:
                ctx["prev_champion"] = _trunc(prev_champion_name).upper()
                pool = _BLK_VET_CHAMP_NEW
            else:
                pool = _BLK_VET_CHAMP_INCUMBENT
        else:
            if prev_champion_name and prev_champion_name != champion_w.name:
                ctx["prev_champion"] = _trunc(prev_champion_name).upper()
                pool = _BLK_VET_CHAMP_NEW
            else:
                pool = _BLK_VET_CHAMP_INCUMBENT
    else:
        pool = _BLK_VET_CHAMP_VACANT

    paragraphs.append(_pick_block(pool, used, ctx))

    # Para 3: Short / dominant fights
    def _wl_team(bout):
        wname   = getattr(bout.result.winner, "name", "?") if bout.result.winner else "?"
        pw_name = getattr(bout.player_warrior, "name", "")
        loser   = bout.opponent if pw_name == wname else bout.player_warrior
        pw_team = (getattr(bout.player_team,   "team_name", None)
                   or getattr(bout.player_team, "manager_name", "?"))
        op_team = (getattr(bout.opponent_team, "team_name", None)
                   or getattr(bout.opponent_team, "manager_name", "?"))
        w_team  = pw_team if pw_name == wname else op_team
        return wname, getattr(loser, "name", "?"), w_team

    sentences = []
    for bout in short_bouts[:4]:
        if not (bout.result and bout.result.winner):
            continue
        wname, lname, w_team = _wl_team(bout)
        ctx.update(warrior=_trunc(wname).upper(), opponent=_trunc(lname).upper(),
                   team=_trunc(w_team).upper(), minutes=str(bout.result.minutes_elapsed),
                   duration=_fight_style_word(bout.result.minutes_elapsed))
        ctx["Opponent"] = ctx["opponent"]
        _set_elite_pronouns(ctx, _gender_of(wname))
        sentences.append(_pick_block(_BLK_VET_DOMINANT, used, ctx))
    if sentences:
        paragraphs.append("  ".join(sentences))

    # Para 4: Long / compelling fights
    sentences = []
    for bout in long_bouts[:3]:
        if not (bout.result and bout.result.winner):
            continue
        wname, lname, w_team = _wl_team(bout)
        ctx.update(warrior=_trunc(wname).upper(), opponent=_trunc(lname).upper(),
                   team=_trunc(w_team).upper(), minutes=str(bout.result.minutes_elapsed),
                   duration=_fight_style_word(bout.result.minutes_elapsed))
        ctx["Opponent"] = ctx["opponent"]
        _set_elite_pronouns(ctx, _gender_of(wname))
        sentences.append(_pick_block(_BLK_VET_COMPELLING, used, ctx))
    if sentences:
        paragraphs.append("  ".join(sentences))

    # Para 5: Upsets
    upset_bouts = [
        b for b in unique_bouts
        if b.result and b.result.winner
        and w_wins.get(getattr(b.result.winner, "name", ""), 0)
           < w_wins.get(
               getattr(b.opponent if getattr(b.player_warrior, "name", "") == getattr(b.result.winner, "name", "") else b.player_warrior, "name", ""),
               0,
           )
    ]
    sentences = []
    for bout in upset_bouts[:3]:
        wname, lname, w_team = _wl_team(bout)
        ctx.update(warrior=_trunc(wname).upper(), opponent=_trunc(lname).upper(),
                   team=_trunc(w_team).upper(), minutes=str(bout.result.minutes_elapsed),
                   duration=_fight_style_word(bout.result.minutes_elapsed))
        ctx["Opponent"] = ctx["opponent"]
        _set_elite_pronouns(ctx, _gender_of(wname))
        _lose_f = _gender_of(lname).lower().startswith("f")
        ctx["him"], ctx["Him"] = ("her", "Her") if _lose_f else ("him", "Him")
        sentences.append(_pick_block(_BLK_VET_UPSET, used, ctx))
    if sentences:
        paragraphs.append("  ".join(sentences))

    # Para 5b: Old scores - rematches and series, from fight history
    _wobj = {w.name: w for w, _ in (arena_warriors or [])}

    def _ctx_bout(wname, lname, w_team):
        ctx.update(warrior=_trunc(wname).upper(), opponent=_trunc(lname).upper(),
                   team=_trunc(w_team).upper())
        ctx["Opponent"] = ctx["opponent"]

    rivalry = []
    for bout in unique_bouts:
        if not (bout.result and bout.result.winner):
            continue
        wname, lname, w_team = _wl_team(bout)
        wo = _wobj.get(wname)
        prior = _elite_meetings(wo, lname, turn_num, "veteran") if wo is not None else []
        if prior:
            rivalry.append((len(prior), wname, lname, w_team, prior))
    rivalry.sort(key=lambda r: -r[0])
    sentences = []
    for n_prior, wname, lname, w_team, prior in rivalry[:2]:
        _ctx_bout(wname, lname, w_team)
        _set_elite_pronouns(ctx, _gender_of(wname))
        meetings = n_prior + 1
        ctx.update(n=str(meetings), nth=_ordinal(meetings),
                   a=str(prior.count("win") + 1), b=str(prior.count("loss")))
        text = _pick_block(
            _BLK_ELITE_REMATCH_AVENGED if prior[-1] == "loss" else _BLK_ELITE_REMATCH_REPEAT,
            used, ctx)
        if meetings >= 3:
            text += "  " + _pick_block(_BLK_ELITE_RIVALRY_SERIES, used, ctx)
        sentences.append(text)
    if sentences:
        paragraphs.append("  ".join(sentences))

    # Para 5c: Streaks
    streaks, seen_streak = [], set()
    for bout in unique_bouts:
        if not (bout.result and bout.result.winner):
            continue
        wname, lname, w_team = _wl_team(bout)
        wo = _wobj.get(wname)
        st = _elite_streak(wo, "veteran") if wo is not None else 0
        if st >= 3 and wname not in seen_streak:
            seen_streak.add(wname)
            streaks.append((st, wname, lname, w_team))
    sentences = []
    for st, wname, lname, w_team in sorted(streaks, reverse=True)[:2]:
        _ctx_bout(wname, lname, w_team)
        ctx["streak"] = str(st)
        sentences.append(_pick_block(_BLK_ELITE_STREAK, used, ctx))
    if sentences:
        paragraphs.append("  ".join(sentences))

    # Para 5d: New arrivals
    sentences, seen_arr = [], set()
    for bout in unique_bouts:
        for side, side_team in ((bout.player_warrior, bout.player_team),
                                (bout.opponent,       bout.opponent_team)):
            nm = getattr(side, "name", "")
            wo = _wobj.get(nm)
            if wo is None or nm in seen_arr:
                continue
            info = _new_arrival_info(wo, turn_num, "veteran")
            if not info:
                continue
            seen_arr.add(nm)
            mw, ml, first_res, first_opp = info
            if first_res == "win":
                res_txt = f"The opening bout went to {_trunc(nm).upper()}, over {_trunc(first_opp).upper()}."
            else:
                res_txt = f"The opening bout went to {_trunc(first_opp).upper()}, who beat {_trunc(nm).upper()}."
            ctx.update(
                warrior=_trunc(nm).upper(),
                team=_trunc(getattr(side_team, "team_name", None) or "?").upper(),
                mortal_record=f"{mw}-{ml}", arrival_result=res_txt,
            )
            sentences.append(_pick_block(_BLK_VET_NEW_ARRIVAL, used, ctx))
    if sentences:
        paragraphs.append("  ".join(sentences[:3]))

    # Para 6: Deaths
    if death_bouts:
        sentences = []
        for bout in death_bouts[:3]:
            wname, lname, w_team = _wl_team(bout)
            _ctx_bout(wname, lname, w_team)
            _set_elite_pronouns(ctx, _gender_of(wname))  # {his} = the killer
            text = _pick_block(_BLK_VET_DEATH, used, ctx)
            lo, wo = _wobj.get(lname), _wobj.get(wname)
            deaths = _elite_deaths(lo, "veteran") if lo is not None else 0
            kills = _elite_kills(wo, "veteran") if wo is not None else 0
            if deaths >= 2:
                ctx.update(deaths=str(deaths), nth_death=_ordinal(deaths))
                text += "  " + _pick_block(_BLK_VET_FALLEN_COUNT, used, ctx)
            elif kills >= 3:
                ctx["kills"] = str(kills)
                text += "  " + _pick_block(_BLK_VET_KILLER_COUNT, used, ctx)
            sentences.append(text)
        paragraphs.append("  ".join(sentences))

    # Para 6b: Columnist's aside - each byline has its own voice
    voice_lines = [l for l in _BLK_VET_VOICES.get(byline.split(",")[0].strip(), [])
                   if champion_w or "{champion}" not in l]
    if voice_lines:
        if champion_w:
            ctx["champion"] = _trunc(champion_w.name).upper()
        ctx.update(fights=str(len(unique_bouts)), kills=str(len(death_bouts)))
        paragraphs.append(_pick_block(voice_lines, used, ctx))

    # Para 7: Standings
    if team_turn:
        by_wins = sorted(team_turn.items(), key=lambda x: (-x[1]["w"], x[1]["l"]))
        ctx["team"]  = _trunc(by_wins[0][0]).upper()
        ctx["team2"] = _trunc(by_wins[1][0]).upper() if len(by_wins) > 1 else ctx["team"]
        paragraphs.append(_pick_block(_BLK_VET_STANDINGS, used, ctx))

    # Para 7b: Occasional lore interlude
    if random.random() < 0.30:
        paragraphs.append(_pick_block(_BLK_VET_LORE, used, ctx))

    # Para 8: Closing
    if champion_w:
        ctx["champion"]   = _trunc(champion_w.name).upper()
        ctx["champ_team"] = _trunc(
            getattr(champion_t, "team_name", None) or str(champion_t)
        ).upper()
    paragraphs.append(_pick_block(_BLK_VET_CLOSING, used, ctx))

    article = "\n\n".join(p for p in paragraphs if p.strip())
    return f"\n\n{HDR_RED_LG}Arena Happenings{HDR_RESET}\n\n" + article


# ---------------------------------------------------------------------------
# TOP MANAGERS SECTION
# ---------------------------------------------------------------------------

def _manager_recently_active(mgr_name, teams, turn_num) -> bool:
    """
    Check if a manager should be included in the newsletter.
    They are included if:
    1. None of their teams have played within the last 3 turns, OR
    2. They are a new manager (last_turn_ran == 0 AND they have fights this turn)

    Uses each team's own last_turn_ran (the same recency source
    _team_standings/_warrior_tiers already rely on) rather than scanning
    manager_records.json for a consecutive-miss streak. That file-based
    approach broke down whenever the ledger had a gap (e.g. turns that
    were never persisted for other reasons) - it would then count every
    missing turn in the gap as a "miss" and permanently hide an actively-
    playing manager, since the scan never finds a turn it can point to
    as "not missed" beyond the gap.
    """
    for team in teams:
        if _is_npc_team(team):
            continue
        tmgr = getattr(team, "manager_name", None) if hasattr(team, "manager_name") else team.get("manager_name", "?")
        if tmgr != mgr_name:
            continue
        last_run = getattr(team, "last_turn_ran", 0) if hasattr(team, "last_turn_ran") else team.get("last_turn_ran", 0)

        # Include if they've played within last 3 turns (established manager)
        if last_run and last_run >= turn_num - 3:
            return True

        # Include if they're new (last_turn_ran == 0) and they have fights this turn
        if last_run == 0:
            # Check if this team has turn_history entry for current turn (means they fought)
            hist = getattr(team, "turn_history", None)
            if hist is None:
                hist = team.get("turn_history", []) if isinstance(team, dict) else []
            for entry in hist:
                if entry.get("turn") == turn_num:
                    # New team with fights this turn - include them
                    return True
    return False


def _validate_manager_records_before_save(turn_num, manager_records):
    """
    Validate manager records before they are used in the newsletter or saved.
    This is critical - ensures the newsletter text matches the saved data.

    Raises an exception if validation fails (preventing both newsletter generation and save).
    """
    import os
    import json

    errors = []

    # Load previous turn's data to verify accumulation
    try:
        prev_records = {
            name: {"cw": c[0], "cl": c[1], "ck": c[2]}
            for name, c in _previous_manager_careers(turn_num, set(manager_records)).items()
        }

        # Validate each manager's records
        for mgr_name, rec in manager_records.items():
            this_w = rec.get("w", 0)
            this_l = rec.get("l", 0)
            this_k = rec.get("k", 0)
            career_w = rec.get("cw", 0)
            career_l = rec.get("cl", 0)
            career_k = rec.get("ck", 0)

            # Check 1: Career must be >= this turn (career is cumulative)
            if career_w < this_w or career_l < this_l or career_k < this_k:
                errors.append(
                    f"{mgr_name}: Career {career_w}-{career_l}-{career_k} < This Turn {this_w}-{this_l}-{this_k} (INVALID)"
                )

            # Check 2: Verify accumulation from previous turn
            if turn_num > 1 and mgr_name in prev_records:
                prev_rec = prev_records[mgr_name]
                prev_cw = prev_rec.get("cw", 0)
                prev_cl = prev_rec.get("cl", 0)
                prev_ck = prev_rec.get("ck", 0)

                expected_cw = prev_cw + this_w
                expected_cl = prev_cl + this_l
                expected_ck = prev_ck + this_k

                if career_w != expected_cw or career_l != expected_cl or career_k != expected_ck:
                    errors.append(
                        f"{mgr_name}: Accumulation failed - "
                        f"Prev {prev_cw}-{prev_cl}-{prev_ck} + This {this_w}-{this_l}-{this_k} "
                        f"= Expected {expected_cw}-{expected_cl}-{expected_ck} "
                        f"but got {career_w}-{career_l}-{career_k}"
                    )

    except Exception as e:
        errors.append(f"Exception during validation: {e}")

    if errors:
        error_text = "\n  ".join(errors)
        raise Exception(f"Manager records validation FAILED:\n  {error_text}")


def _save_manager_records(turn_num, manager_records):
    """
    Save manager records for this turn to manager_records.json.
    Records include career (cw, cl, ck) and this turn (w, l, k).

    IMPORTANT: _top_managers already calculates the final career totals.
    This function just saves them as-is; no additional accumulation needed.
    """
    import os
    import json

    try:
        league_dir = os.path.dirname(os.path.abspath(__file__))
        manager_records_file = os.path.join(league_dir, "manager_records.json")

        # Load existing records or create new
        all_records = {}
        if os.path.exists(manager_records_file):
            with open(manager_records_file, "r", encoding="utf-8") as f:
                all_records = json.load(f)

        # Store this turn's records as-is (career totals already calculated by _top_managers)
        all_records[str(turn_num)] = {}

        # CRITICAL: Validate all records before saving
        validation_errors = []

        for mgr_name, rec in manager_records.items():
            this_turn_w = rec.get("w", 0)
            this_turn_l = rec.get("l", 0)
            this_turn_k = rec.get("k", 0)
            career_w = rec.get("cw", 0)
            career_l = rec.get("cl", 0)
            career_k = rec.get("ck", 0)

            # VALIDATION 1: Career totals must be >= this turn's results
            # (career is cumulative, so it should never be less than current turn)
            if career_w < this_turn_w or career_l < this_turn_l or career_k < this_turn_k:
                msg = f"CRITICAL: {mgr_name} Turn {turn_num} - career < this turn!"
                msg += f"\n  This turn: {this_turn_w}-{this_turn_l}-{this_turn_k}"
                msg += f"\n  Career: {career_w}-{career_l}-{career_k}"
                validation_errors.append(msg)
                print(msg)

            # VALIDATION 2: If previous turn exists, verify accumulation
            prev_turn_key = str(turn_num - 1)
            if prev_turn_key in all_records and mgr_name in all_records[prev_turn_key]:
                prev_rec = all_records[prev_turn_key][mgr_name]
                prev_career_w = prev_rec.get("cw", 0)
                prev_career_l = prev_rec.get("cl", 0)
                prev_career_k = prev_rec.get("ck", 0)

                expected_w = prev_career_w + this_turn_w
                expected_l = prev_career_l + this_turn_l
                expected_k = prev_career_k + this_turn_k

                if career_w != expected_w or career_l != expected_l or career_k != expected_k:
                    msg = f"CRITICAL: {mgr_name} Turn {turn_num} - accumulation mismatch!"
                    msg += f"\n  Prev Career: {prev_career_w}-{prev_career_l}-{prev_career_k}"
                    msg += f"\n  This Turn: {this_turn_w}-{this_turn_l}-{this_turn_k}"
                    msg += f"\n  Expected: {expected_w}-{expected_l}-{expected_k}"
                    msg += f"\n  Actual: {career_w}-{career_l}-{career_k}"
                    validation_errors.append(msg)
                    print(msg)

            all_records[str(turn_num)][mgr_name] = {
                "w": this_turn_w,
                "l": this_turn_l,
                "k": this_turn_k,
                "cw": career_w,
                "cl": career_l,
                "ck": career_k
            }

        # If there are validation errors, log them but still save
        # (Newsletter already generated, and we need the records for next turn's calculation)
        if validation_errors:
            print("\n" + "="*80)
            print("WARNING: Manager records validation found issues (see above)")
            print("="*80)
            print("Records will be saved anyway - you can review and fix with validate_manager_records.py")

        # Write back
        with open(manager_records_file, "w", encoding="utf-8") as f:
            json.dump(all_records, f, indent=2)

        print(f"INFO: Saved manager records for turn {turn_num}")
    except Exception as e:
        print(f"ERROR: Failed to save manager records: {e}")
        import traceback
        traceback.print_exc()

def _top_managers(card, teams, turn_num, return_records=False):
    """
    Generate manager standings sorted by win percentage (best to worst).
    Presents current-turn and career records side by side.
    Career records are loaded from previous turn's saved records, then current turn is added.

    If return_records=True, returns (text, manager_records) tuple.
    Otherwise returns just the text string.
    """

    # Deduplicate by object identity - each ScheduledFight is a unique physical fight.
    # Name-pair deduplication is wrong here: the same two warriors can legitimately
    # fight more than once across turns in the career card.
    seen_fights = set()
    unique_bouts = []
    for bout in card:
        if not bout.result:
            continue
        if id(bout) in seen_fights:
            continue
        seen_fights.add(id(bout))
        unique_bouts.append(bout)

    # Group teams by manager and calculate records
    manager_records = {}

    # First pass: Load career records from previous turn's saved records
    # This is the authoritative source - previous turn's career record + current turn's record = new career record
    import os
    import json
    from pathlib import Path

    prev_turn_num = turn_num - 1
    try:
        league_dir = os.path.dirname(os.path.abspath(__file__))
        manager_records_file = os.path.join(league_dir, "manager_records.json")

        if os.path.exists(manager_records_file):
            with open(manager_records_file, "r", encoding="utf-8") as f:
                saved_records = json.load(f)
                # Use records from previous turn as the new career baseline.
                # The previous turn's "cw", "cl", "ck" ARE the career totals.
                # Current turn's "w", "l", "k" will be added to calculate new career totals.
                if str(prev_turn_num) in saved_records:
                    for mgr_name, rec in saved_records[str(prev_turn_num)].items():
                        cw = rec.get("cw", 0)
                        cl = rec.get("cl", 0)
                        ck = rec.get("ck", 0)

                        # VALIDATION: Check if career baseline looks reasonable
                        # If career totals are 0 for a manager who fought previous turn, something is wrong
                        prev_w = rec.get("w", 0)
                        if prev_w > 0 and cw == 0:
                            print(f"WARNING: {mgr_name} fought in Turn {prev_turn_num} (w={prev_w}) but career total is 0!")
                            print(f"  This suggests career data wasn't loaded correctly last turn")

                        # Career baseline = previous turn's career totals
                        manager_records[mgr_name] = {
                            "cw": cw,
                            "cl": cl,
                            "ck": ck,
                            "w": 0,    # Current turn's record (will be calculated below)
                            "l": 0,
                            "k": 0
                        }

        # Initialize any managers not yet in records
        for team in teams:
            if _is_npc_team(team):
                continue
            mgr_name = getattr(team, "manager_name", None) or team.get("manager_name", "?")
            if mgr_name != "?" and mgr_name not in _NPC_TEAM_NAMES:
                if mgr_name not in manager_records:
                    manager_records[mgr_name] = {"w": 0, "l": 0, "k": 0, "cw": 0, "cl": 0, "ck": 0}
    except Exception as e:
        # Fallback: initialize empty records for all managers
        for team in teams:
            if _is_npc_team(team):
                continue
            mgr_name = getattr(team, "manager_name", None) or team.get("manager_name", "?")
            if mgr_name != "?" and mgr_name not in _NPC_TEAM_NAMES:
                if mgr_name not in manager_records:
                    manager_records[mgr_name] = {"w": 0, "l": 0, "k": 0, "cw": 0, "cl": 0, "ck": 0}

    # The published newsletter overrides the saved baseline: career = last
    # published career + this turn (records may be hand-corrected there).
    for mgr_name, (pcw, pcl, pck) in _previous_manager_careers(turn_num, set(manager_records)).items():
        rec = manager_records[mgr_name]
        if (rec["cw"], rec["cl"], rec["ck"]) != (pcw, pcl, pck):
            print(f"  [CAREER BASELINE] {mgr_name}: using published {pcw}-{pcl}-{pck} "
                  f"(manager_records.json had {rec['cw']}-{rec['cl']}-{rec['ck']})")
        rec["cw"], rec["cl"], rec["ck"] = pcw, pcl, pck

    # Second pass: calculate THIS TURN records from teams' turn_history
    # This is more reliable than trying to aggregate from the card
    for team in teams:
        if _is_npc_team(team):
            continue

        mgr = getattr(team, "manager_name", None) or team.get("manager_name", "?")
        if mgr == "?" or mgr in _NPC_TEAM_NAMES:
            continue

        # Initialize manager if not already present
        if mgr not in manager_records:
            manager_records[mgr] = {"w": 0, "l": 0, "k": 0, "cw": 0, "cl": 0, "ck": 0}

        # Get this team's turn history
        hist = getattr(team, "turn_history", None)
        if hist is None:
            hist = team.get("turn_history", []) if isinstance(team, dict) else []

        # Find the entry for the current turn (explicitly check turn number)
        turn_entry = None
        if hist and len(hist) > 0:
            # Search backwards to find entry for current turn
            for entry in reversed(hist):
                if entry.get("turn") == turn_num:
                    turn_entry = entry
                    break

        if turn_entry:
            w = turn_entry.get("w", 0)
            l = turn_entry.get("l", 0)
            k = turn_entry.get("k", 0)

            # Add to this manager's totals
            manager_records[mgr]["w"] += w
            manager_records[mgr]["l"] += l
            manager_records[mgr]["k"] += k

            team_name = getattr(team, 'team_name', '?') or team.get('team_name', '?')
            print(f"  [TURN CALC] {mgr} team {team_name}: +{w}w +{l}l +{k}k")
        else:
            # Missing data for this turn - could indicate a processing issue
            team_name = getattr(team, 'team_name', '?') or team.get('team_name', '?')
            print(f"  [TURN CALC WARNING] {mgr} team {team_name}: NO TURN {turn_num} DATA in turn_history")

    # Calculate win percentages and sort
    # IMPORTANT: At this point, rec["cw/cl/ck"] are the PREVIOUS turn's career totals.
    # We need to add this turn's results (rec["w/l/k"]) to get the NEW career totals.
    print(f"\n[DEBUG] Accumulating career totals for Turn {turn_num}:")
    for mgr_name, rec in manager_records.items():
        old_cw = rec["cw"]
        old_cl = rec["cl"]
        old_ck = rec["ck"]

        rec["cw"] += rec["w"]  # New career wins = old career wins + this turn's wins
        rec["cl"] += rec["l"]  # New career losses = old career losses + this turn's losses
        rec["ck"] += rec["k"]  # New career kills = old career kills + this turn's kills

        print(f"  {mgr_name:<35} This Turn: {rec['w']:3d}-{rec['l']:3d}-{rec['k']:3d} | Baseline: {old_cw:3d}-{old_cl:3d}-{old_ck:3d} | New Career: {rec['cw']:3d}-{rec['cl']:3d}-{rec['ck']:3d}")

    manager_list = []
    for mgr_name, rec in manager_records.items():
        # Skip managers whose teams haven't played within the last 3 turns
        if not _manager_recently_active(mgr_name, teams, turn_num):
            continue

        total_fights = rec["w"] + rec["l"]
        win_pct = (rec["w"] / total_fights * 100) if total_fights > 0 else 0
        career_total = rec["cw"] + rec["cl"]
        career_pct = (rec["cw"] / career_total * 100) if career_total > 0 else 0
        manager_list.append({
            "name": mgr_name,
            "w": rec["w"],
            "l": rec["l"],
            "k": rec["k"],
            "pct": win_pct,
            "total": total_fights,
            "cw": rec["cw"],
            "cl": rec["cl"],
            "ck": rec["ck"],
            "cpct": career_pct,
            "ctotal": career_total,
        })

    # Sort for this turn (by win %, then wins)
    manager_list_turn = sorted(manager_list, key=lambda x: (-x["pct"], -x["w"]))
    # Sort for career (by career win %, then career wins)
    manager_list_career = sorted(manager_list, key=lambda x: (-x["cpct"], -x["cw"]))

    # Format output
    gap = " " * 20
    left_title = f"The Top Managers This Turn ({turn_num})"
    right_title = "The Top Managers Career"
    # Column widths leave at least two spaces between 4-digit W/L/K totals (career wins reach 1000+)
    # so the numbers never run together (e.g. 779 + 1011 must not read as 7791011).
    NAME_W, W_W, L_W, K_W, PCT_W, TOT_W = 34, 6, 6, 5, 7, 6
    PANEL_W = 1 + NAME_W + W_W + L_W + K_W + PCT_W + TOT_W
    SEP = "=" * (PANEL_W * 2 + len(gap))
    left_hdr = f"{'  MANAGER':<{1 + NAME_W}}{'W':>{W_W}}{'L':>{L_W}}{'K':>{K_W}}{'%':>{PCT_W}}{'TOTAL':>{TOT_W}}"
    right_hdr = left_hdr
    HDR = left_hdr + gap + right_hdr

    lines = [f"\n{HDR_BOLD}{left_title:<{PANEL_W + 1}}{HDR_RESET}{gap}{HDR_BOLD}{right_title}{HDR_RESET}", HDR, SEP]

    max_rows = max(len(manager_list_turn), len(manager_list_career))
    for i in range(max_rows):
        left_data = ""
        if i < len(manager_list_turn):
            mgr = manager_list_turn[i]
            left_data = (f" {mgr['name'][:NAME_W - 1]:<{NAME_W}}{mgr['w']:>{W_W}}{mgr['l']:>{L_W}}{mgr['k']:>{K_W}}"
                        f"{mgr['pct']:>{PCT_W - 1}.1f}%{mgr['total']:>{TOT_W}}")
        else:
            left_data = " " * PANEL_W  # Empty row on left side

        right_data = ""
        if i < len(manager_list_career):
            mgr = manager_list_career[i]
            right_data = (f" {mgr['name'][:NAME_W - 1]:<{NAME_W}}{mgr['cw']:>{W_W}}{mgr['cl']:>{L_W}}{mgr['ck']:>{K_W}}"
                         f"{mgr['cpct']:>{PCT_W - 1}.1f}%{mgr['ctotal']:>{TOT_W}}")

        lines.append(left_data + gap + right_data)

    lines.append(SEP)
    result = "\n".join(lines)

    if return_records:
        # Return both text and the final manager records (career + current turn)
        return result, manager_records
    return result


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------

def _turn_ranges(turns) -> List[str]:
    """[26,27,28,29,30,36] -> ['26-30', '36']  (single turns have no dash)."""
    turns = sorted(set(turns))
    parts, i = [], 0
    while i < len(turns):
        j = i
        while j + 1 < len(turns) and turns[j + 1] == turns[j] + 1:
            j += 1
        parts.append(str(turns[i]) if i == j else f"{turns[i]}-{turns[j]}")
        i = j + 1
    return parts


def _champion_history_section(turn_num, champion_state=None) -> str:
    """Bottom-of-newsletter table of every warrior who has held the main-arena
    title, with total turns as Champion (not just consecutive) and the turns.
    Rows are sorted by total turns as Champion, most first (ties: earlier first
    title). The reigning Champion is marked with *. Returns "" when there is
    no history yet."""
    try:
        from save import load_champion_history
        history = load_champion_history()
    except Exception:
        return ""
    # Only turns up to the one being written, so re-running an old turn is consistent.
    history = {t: e for t, e in history.items() if t <= turn_num and (e or {}).get("name")}
    if not history:
        return ""

    def _key(e):
        return ((e.get("name") or "").strip().upper(), e.get("team_id"))

    people = {}
    for t in sorted(history):
        e = history[t]
        rec = people.setdefault(_key(e), {"name": e["name"].strip(), "manager": "", "turns": []})
        rec["turns"].append(t)
        if e.get("manager_name"):
            rec["manager"] = e["manager_name"]
    reigning = _key(history[turn_num]) if turn_num in history else None
    # Longest-reigning first (most total turns); ties go to whoever first took the title earlier.
    rows = sorted(people.items(), key=lambda kv: (-len(kv[1]["turns"]), kv[1]["turns"][0]))

    sep = "=" * 80
    name_w, mgr_w, tot_w = 25, 20, 5
    turns_col = name_w + mgr_w + tot_w + 2
    lines = [f"\n                      {HDR_RED_LG}CHAMPION HISTORY{HDR_RESET}\n",
             f"{'CHAMPION':<{name_w}}{'MANAGER':<{mgr_w}}{'TOTAL':>{tot_w}}  TURNS AS CHAMPION",
             sep]
    for key, rec in rows:
        label = _trunc(rec["name"], name_w - 2) + ("*" if key == reigning else "")
        # Wrap the turn list on ", " boundaries so a long career stays inside 80 columns.
        wrap_w = 80 - turns_col
        chunks, cur = [], ""
        for part in _turn_ranges(rec["turns"]):
            nxt = part if not cur else cur + ", " + part
            if cur and len(nxt) > wrap_w:
                chunks.append(cur + ",")
                cur = part
            else:
                cur = nxt
        chunks.append(cur)
        lines.append(f"{label:<{name_w}}{_trunc(rec['manager'], mgr_w - 2):<{mgr_w}}"
                     f"{len(rec['turns']):>{tot_w}}  {chunks[0]}")
        for extra in chunks[1:]:
            lines.append(" " * turns_col + extra)
    lines.append(sep)
    if reigning is not None:
        lines.append("* reigning Champion")
    return "\n".join(lines)


def generate_newsletter(turn_num, card, teams, deaths, champion_state,
                        processed_date=None, is_new_champion=False, champion_state_before=None,
                        prev_champion_state=None, bully_events=None, retirements=None,
                        promotions=None, transcendences=None, promotion_pending=None) -> str:
    # Wrap all bouts to handle both dict and object formats uniformly
    wrapped_card = [_BoutWrapper(bout) for bout in card] if card else []
    if retirements is None:
        retirements = []
    if promotions is None:
        promotions = []
    if transcendences is None:
        transcendences = []
    if promotion_pending is None:
        promotion_pending = []

    sections = [_header(turn_num, processed_date)]
    sections.append(_team_standings(teams, turn_num, wrapped_card))

    # Get manager standings and save records
    result = _top_managers(wrapped_card, teams, turn_num, return_records=True)
    print(f"DEBUG: _top_managers returned type {type(result)}, is tuple: {isinstance(result, tuple)}")
    if isinstance(result, tuple):
        managers_text, manager_records = result

        # ALWAYS append the newsletter text - newsletter generation is critical
        sections.append("\n\n" + managers_text)

        # Validate and save the records (but don't let validation errors prevent newsletter generation)
        validation_passed = True
        try:
            print(f"\nDEBUG: Validating manager records...")
            _validate_manager_records_before_save(turn_num, manager_records)
            print(f"DEBUG: Manager records validation PASSED")
        except Exception as e:
            validation_passed = False
            print(f"\nWARNING: Manager records validation FAILED: {e}")
            print(f"WARNING: Newsletter was generated anyway, but you must fix the data!")
            import traceback
            traceback.print_exc()

        # Save the records (validation may have failed, but we save anyway)
        try:
            _save_manager_records(turn_num, manager_records)
            print(f"DEBUG: Successfully saved manager records for turn {turn_num}")
        except Exception as e:
            print(f"ERROR saving manager records: {e}")
            import traceback
            traceback.print_exc()

        if not validation_passed:
            print(f"\n{'='*80}")
            print(f"ATTENTION: Manager records validation failed for Turn {turn_num}")
            print(f"{'='*80}")
            print(f"The newsletter was generated (see above), but the manager_records.json")
            print(f"may have incorrect data. Review the warnings above and use:")
            print(f"  python validate_manager_records.py")
            print(f"to check the file, then manually correct any issues.")

    else:
        # Backwards compatibility: old code path returned just text
        sections.append("\n\n" + result)
        print("DEBUG: _top_managers returned text only (not tuple)")

    _happenings = _block_commentary(wrapped_card, teams, deaths, turn_num, champion_state, is_new_champion,
                                    bully_events=bully_events, prev_champion_state=prev_champion_state,
                                    promotions=promotions, promotion_pending=promotion_pending)
    from ai_happenings import rewrite_happenings
    sections.append("\n\n" + rewrite_happenings(_happenings, ARENA_NAME, turn_num))
    sections.append("\n\n" + _warrior_tiers(teams, champion_state, wrapped_card, turn_num))

    # Add monster kills section if there are any
    monster_kills = _monster_kills_section(wrapped_card)
    if monster_kills:
        sections.append("\n\n" + monster_kills)

    sections.append("\n\n" + _fights_section(wrapped_card, champion_state, prev_champion_state))
    dead = _dead_section(deaths, turn_num)
    if dead: sections.append("\n\n" + dead)
    retired = _retired_section(retirements)
    if retired: sections.append("\n\n" + retired)
    promoted = _promotions_section(promotions)
    if promoted: sections.append("\n\n" + promoted)
    pending_promo = _promotion_pending_section(promotion_pending)
    if pending_promo: sections.append("\n\n" + pending_promo)
    transcended = _transcendence_section(transcendences)
    if transcended: sections.append("\n\n" + transcended)
    sections.append("\n\n" + _race_report(teams))
    champ_history = _champion_history_section(turn_num, champion_state)
    if champ_history:
        sections.append("\n\n" + champ_history)
    return "\n".join(sections)

