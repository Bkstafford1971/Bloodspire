# =============================================================================
# newsletter.py - THE AGONY AMPHITHEATRE Newsletter Generator
# =============================================================================
import random, datetime, json, os
from typing import List, Optional

ARENA_NAME  = "The Agony Amphitheatre"
ARENA_ID    = 1
_NPC_TEAM_NAMES = {"The Monsters", "The Peasants"}
_NPC_RACES      = {"Monster", "Peasant"}

TIER_CHAMPION  = "CHAMPION"
TIER_ELITES    = "ELITES"
TIER_VETERANS  = "VETERANS"
TIER_ADEPTS    = "ADEPTS"
TIER_INITIATES = "INITIATES"
TIER_ROOKIES   = "ROOKIES"
TIER_RECRUITS  = "RECRUITS"


NAME_LIMIT = 30
LEAGUE_DATA_DIR = r"C:\BPClone_Claude\saves\league"

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
    """Assign a warrior to a tier based on recognition rating (0-99).

    Champion: determined externally (is_champion flag)
    Elite:    67 - 99
    Veteran:  57 - 66
    Adept:    34 - 56
    Initiate: 24 - 33
    Rookie:   0  - 23
    Recruit:  <= 5 fights
    """
    if is_champion: return TIER_CHAMPION
    fights = getattr(w, "total_fights", 0)
    rec    = getattr(w, "recognition", 0)
    if fights <= 5: return TIER_RECRUITS
    if rec >= 67:   return TIER_ELITES
    if rec >= 57:   return TIER_VETERANS
    if rec >= 34:   return TIER_ADEPTS
    if rec >= 24:   return TIER_INITIATES
    if rec >= 0:    return TIER_ROOKIES
    return TIER_RECRUITS


def _update_champion(teams, champion_state: dict, deaths_this_turn: list,
                     champion_beaten_by: str = None, champion_beaten_by_wid: int = None,
                     champion_beaten_team: str = None, champion_beaten_team_id: int = 0,
                     prev_champion_name: str = None,
                     card = None) -> tuple:
    """
    Update the champion state based on battle outcomes and warrior recognition.
    
    Champion Rules:
    1. If champion is beaten in combat, defeater becomes new champion immediately
    2. If no current champion exists, award to warrior with HIGHEST recognition
       - If there's a tie for highest, leave spot VACANT
    3. If current champion exists but didn't fight this turn:
       - Award to warrior with highest recognition (if no tie)
       - If there's a tie, spot becomes vacant
    4. If current champion fought, they keep the title (unless beaten)
    
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
            ow = bout.get("opponent_warrior") if isinstance(bout, dict) else getattr(bout, "opponent_warrior", None)
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
                     "source": "beat_champion"}
        is_new = (champion_beaten_by != prev_champ)
        return new_state, is_new
    
    current_champ = champion_state.get("name", "")
    current_champ_tid = champion_state.get("team_id", 0)
    
    # Check if current champion is dead
    if current_champ and (current_champ_tid, current_champ) in dead_keys:
        current_champ = ""
    
    # Check if current champion fought this turn
    champion_fought = False
    if current_champ:
        # Primary check: match by (team_id, name)
        champion_fought = (current_champ_tid, current_champ) in warriors_who_fought
        # Fallback check: if team_id was 0 (not saved), check by name only
        if not champion_fought and current_champ_tid == 0:
            champion_fought = any(name == current_champ for tid, name in warriors_who_fought)
    
    # RULE 4: If champion exists and fought this turn, they keep the title
    if current_champ and champion_fought:
        is_new = (current_champ != prev_champ)
        return champion_state, is_new
    
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
            if (w_tid, wobj.name) in dead_keys: continue
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
        # THERE IS A TIE - Leave spot vacant
        # Only return empty state if this represents a change from having a champion
        is_new = (prev_champ != "")
        return {}, is_new
    
    # NO TIE - Award championship to the warrior with highest recognition
    champ_w, champ_t, champ_tid = all_warriors[0]
    new_state = {"name": champ_w.name, "warrior_id": getattr(champ_w, "warrior_id", None),
                 "team_name": champ_t, "team_id": champ_tid, "source": "recognition"}
    is_new = (champ_w.name != prev_champ)
    return new_state, is_new


def _get_warriors(w):
    if hasattr(w,"name"): return w
    from warrior import Warrior
    try:    return Warrior.from_dict(w)
    except: return None


def _is_npc_team(team) -> bool:
    name = team.team_name if hasattr(team,"team_name") else team.get("team_name","")
    return name in _NPC_TEAM_NAMES


def _fmt_date() -> str:
    return datetime.date.today().strftime("%m/%d/%Y")


# ---------------------------------------------------------------------------
# HEADER
# ---------------------------------------------------------------------------

def _header(turn_num: int, processed_date: str = None) -> str:
    return (f"Date: {processed_date or _fmt_date()}\n"
            f"{ARENA_NAME} ({ARENA_ID})\n"
            f"Turn - {turn_num}")


# ---------------------------------------------------------------------------
# TEAM STANDINGS
# ---------------------------------------------------------------------------

def _team_career_record(team) -> tuple:
    """
    Return cumulative (wins, losses, kills) for ALL warriors who have ever
    fought for this team: active warriors + dead-awaiting-replacement +
    archived (confirmed-replaced) warriors.
    """
    tw = tl = tk = 0
    tname = team.team_name if hasattr(team, "team_name") else team.get("team_name", "?")
    # Active + dead-awaiting-replacement - still in the warriors list
    wlist = team.warriors if hasattr(team,"warriors") else team.get("warriors",[])
    for w in wlist:
        if not w: continue
        tw += getattr(w,"wins",0)   if hasattr(w,"wins")   else w.get("wins",0)
        tl += getattr(w,"losses",0) if hasattr(w,"losses") else w.get("losses",0)
        tk += getattr(w,"kills",0)  if hasattr(w,"kills")  else w.get("kills",0)
    active_tw, active_tl, active_tk = tw, tl, tk
    # Archived warriors (replaced after death / retirement)
    archived = (getattr(team,"archived_warriors",[])
                if hasattr(team,"archived_warriors")
                else team.get("archived_warriors",[]))
    for aw in archived:
        if not aw: continue
        tw += aw.get("wins",0)   if isinstance(aw,dict) else getattr(aw,"wins",0)
        tl += aw.get("losses",0) if isinstance(aw,dict) else getattr(aw,"losses",0)
        tk += aw.get("kills",0)  if isinstance(aw,dict) else getattr(aw,"kills",0)
    print(f"  [career_record] {tname}: active={active_tw}-{active_tl}-{active_tk} "
          f"archived={len(archived)} total={tw}-{tl}-{tk}")
    return tw, tl, tk


def _team_standings(teams, turn_num: int, card: list = None) -> str:
    # ANSI styling codes for "Blood Red" and Bold
    B_RED = "\033[1;31m"
    RESET = "\033[0m"

    # Identify teams that participated in this turn from the card
    teams_that_fought = set()
    if card:
        for bout in card:
            if not bout.result: continue
            pt = bout.player_team
            ot = bout.opponent_team
            ptname = pt.team_name if hasattr(pt, "team_name") else pt.get("team_name", "?")
            otname = ot.team_name if hasattr(ot, "team_name") else ot.get("team_name", "?")
            if ptname not in _NPC_TEAM_NAMES: teams_that_fought.add(ptname)
            if otname not in _NPC_TEAM_NAMES: teams_that_fought.add(otname)

    rows = []
    for team in teams:
        if _is_npc_team(team): continue
        name = team.team_name if hasattr(team,"team_name") else team.get("team_name","?")
        tid  = team.team_id   if hasattr(team,"team_id")   else team.get("team_id",0)
        mgr  = team.manager_name if hasattr(team,"manager_name") else team.get("manager_name","?")
        hist = getattr(team,"turn_history",[]) if hasattr(team,"turn_history") else team.get("turn_history",[])
        # Cumulative career record (all warriors ever on this team)
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
                     "l5w":l5w,"l5l":l5l,"l5k":l5k,"l5pct":l5pct,"fought":name in teams_that_fought})
    
    rows.sort(key=lambda r:(-r["pct"],-(r["w"])))
    # Sort Last 5 by Win % then Kills
    rows_l5=sorted(rows,key=lambda r:(-r["l5pct"], -r["l5k"]))

    # Layout: 79 visible chars per section + 3 char separator = 161 total visible.
    # ANSI codes in name strings add 11 raw chars (invisible), so name field is 66 raw / 55 visible.
    SEP = "="*161
    # Title row: "The Top Teams" left, section labels centered over their columns
    left_title  = f"{'The Top Teams':<15}{'CAREER STANDINGS':^64}"  # 79 chars
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

    tiers={t:[] for t in [TIER_CHAMPION,TIER_ELITES,TIER_VETERANS,TIER_ADEPTS,
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
            rname=wobj.race.name if hasattr(wobj.race,"name") else "Human"
            if rname in _NPC_RACES: continue
            # Don't show replacement warriors until they've competed at least once
            if getattr(wobj,"total_fights",0) == 0: continue

            w_wid = getattr(wobj, "warrior_id", None)
            if champ_wid and w_wid:
                is_champ = (champ_wid == w_wid)
            else:
                is_champ = (wobj.name == champ_name and tid == champ_tid)
            tier = _warrior_tier(wobj, is_champ)
            # Mark warriors that didn't fight this turn with a "-" prefix (but keep them visible)
            warrior_display_name = wobj.name if (tid, wobj.name) in warriors_that_fought else f"- {wobj.name}"
            tiers[tier].append({"name":wobj.name,"display_name":warrior_display_name,"team":tname,"tid":tid,
                "w":wobj.wins,"l":wobj.losses,"k":wobj.kills,
                "rec":getattr(wobj,"recognition",0),"fought":(tid,wobj.name) in warriors_that_fought
            })
    SEP = "="*80
    # Fixed columns: name(30) + W(4) + L(4) + K(4) + Rec(4) + team
    COL_HDR = f"{'NAME':<30}{'W':>4}{'L':>4}{'K':>4}  {'REC':>3}  TEAM"
    sections=[]
    for tier in [TIER_CHAMPION,TIER_ELITES,TIER_VETERANS,TIER_ADEPTS,TIER_INITIATES,TIER_ROOKIES,TIER_RECRUITS]:
        wlist=tiers[tier]
        if not wlist and tier==TIER_CHAMPION:
            sections.append(f"\n{tier}\n{COL_HDR}\n{SEP}\n  (vacant this turn)"); continue
        if not wlist: continue
        wlist.sort(key=lambda x:(-x["rec"],-(x["w"]/max(1,x["w"]+x["l"]))))
        lines=[f"\n{tier}\n{COL_HDR}",SEP]
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
    sep="="*95
    lines=["\nTHE DEAD",
           f"{'NAME':<30}{'W':>4}{'L':>4}{'K':>4}  {'TEAM':<30}{'SLAIN BY':<30}{'TURN':>5}",sep]
    for d in deaths:
        name = _trunc(d['name'])
        team = _trunc(d.get('team','?'))
        slain = _trunc(d.get('killed_by','?'))
        lines.append(f"{name:<30}{d.get('w',0):>4}{d.get('l',0):>4}{d.get('k',0):>4}"
                     f"  {team:<30}{slain:<30}{turn_num:>5}")
    return "\n".join(lines)


def _fights_section(card, champion_state: dict = None) -> str:
    sep="="*85
    lines=["\nLAST TURN'S FIGHTS",sep]

    champ_name = (champion_state or {}).get("name", "")
    champ_tid  = (champion_state or {}).get("team_id", 0)
    champ_wid  = (champion_state or {}).get("warrior_id")

    def _is_champion_warrior(warrior_obj, team_obj) -> bool:
        if not champ_name:
            return False
        wid = getattr(warrior_obj, "warrior_id", None)
        if champ_wid and wid and champ_wid == wid:
            return True
        # Fallback for warriors or champion states that predate warrior_id
        tid = getattr(team_obj, "team_id", 0)
        return warrior_obj.name == champ_name and tid == champ_tid

    def _effective_type(bout):
        ft = getattr(bout, "fight_type", "standard")
        if ft == "monster":
            return "monster"
        pw = getattr(bout, "player_warrior", None)
        ow = getattr(bout, "opponent", None)
        pt = getattr(bout, "player_team", None)
        ot = getattr(bout, "opponent_team", None)
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
        if not bout.result:
            continue
        pw = bout.player_warrior
        ow = bout.opponent
        r = bout.result
        # Use warrior_id when available so same-name fighters on different teams dedup correctly
        pw_key = getattr(pw, "warrior_id", None) or pw.name
        ow_key = getattr(ow, "warrior_id", None) or ow.name
        pair = frozenset([pw_key, ow_key])
        if pair in seen_pairs:
            continue
        if id(bout) in seen_fights:
            continue
        seen_pairs.add(pair)
        seen_fights.add(id(bout))

        eff_type = _effective_type(bout)
        pw_won = r.winner and r.winner.name == pw.name
        winner = pw if pw_won else ow
        loser  = ow if pw_won else pw
        mins   = r.minutes_elapsed
        wname  = _trunc(winner.name)
        lname  = _trunc(loser.name)
        style  = _fight_style_word(mins)

        if eff_type == "champion":
            # Title fight - call out the championship explicitly
            if r.loser_died:
                line = (f"★ CHAMPION'S TITLE FIGHT ★  {wname} has slain {lname} to claim the"
                        f" Champion's Title in a {mins} minute {style} battle!")
            elif winner.name == champ_name:
                verb = random.choice(["defended the title against", "turned back the challenge of",
                                      "retained the championship over", "proved superior to"])
                line = (f"★ CHAMPION'S TITLE FIGHT ★  {wname} {verb} {lname}"
                        f" in a {mins} minute {style} fight.")
            else:
                verb = random.choice(["seized the championship from", "dethroned",
                                      "claimed the title from", "unseated champion"])
                line = (f"★ CHAMPION'S TITLE FIGHT ★  {wname} {verb} {lname}"
                        f" in a {mins} minute {style} fight!")
        elif eff_type in ("challenge", "blood_challenge"):
            label = "Blood Challenge" if eff_type == "blood_challenge" else "Challenge"
            if r.loser_died:
                line = f"{wname} savagely slew {lname} in a {mins} minute {style} {label} fight."
            else:
                verb = random.choice(["bested","defeated","outlasted","overcame","vanquished"])
                line = f"{wname} {verb} {lname} in a {mins} minute {style} {label} fight."
        else:
            # monster / standard / peasant - no type label for standard/peasant
            ftype_str = " monster" if eff_type == "monster" else ""
            if r.loser_died:
                line = (f"{wname} slew {lname} in a {mins} minute {style}{ftype_str} fight."
                        if pw_won else
                        f"{lname} was slain by {wname} in a {mins} minute {style}{ftype_str} fight.")
            else:
                verb = random.choice(["bested","defeated","outlasted","overcame","vanquished"])
                line = f"{wname} {verb} {lname} in a {mins} minute {style}{ftype_str} fight."
        lines.append(line)
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
    
    lines = ["\n" + "="*75, "TRANSFORMATION: ASCENSION TO MONSTERDOM"]
    lines.append("="*75)
    
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
    lines=["\n                      BATTLE REPORT\n",
           f"    {'MOST POPULAR RACE':<25}  {'RECORD DURING THE LAST 10 TURNS':>38}",sep,
           f"{'|RACE':<16}{'FIGHTS':>8}  {'RACE':<18}{'W':>5} - {'L':>4} - {'K':>4}  {'PERCENT':>7}|",sep]
    for race in races:
        tw=rw[race]; tl=rl[race]; tk=rk[race]; pct=int(tw/max(1,tw+tl)*100)
        lines.append(f"|{race:<16}{rf[race]:>8}  {race:<18}{tw:>5} - {tl:>4} - {tk:>4}  {pct:>6}%|")
    lines.append(sep)
    if top:
        lines.append("\n\n                      TOP WARRIOR by RACE\n")
        lines.append(f"{'RACE':<14}{'WARRIOR':<32}{'W':>4}{'L':>4}{'K':>3}  TEAM NAME"); lines.append(sep)
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
]

_BLK_META_WARRIOR = [
    "{warrior} drew more challenges than anyone else this turn, a mix of opportunity seeking and poor judgment by would-be rivals.  Attention like that rarely ends quietly.",
    "Schedules don't lie, and this turn {warrior} attracted the most challenge traffic in {arena}.  Whether rivals see an opportunity or underestimate the danger remains to be answered.",
    "Several challengers tested {warrior} this turn with varying degrees of confidence.  The results told the story the records already suggested.",
    "As the turn progressed, the challenges aimed at {warrior} felt less strategic and more desperate.  In {arena}, that kind of urgency often exposes more weakness than courage.",
    "{warrior} became a focal point this turn, drawing repeated challenges from hopeful rivals.  Popularity in this arena is rarely comfortable.",
]

_BLK_META_TEAM = [
    "Managers were noticeably reluctant to schedule fights against {team} this turn.  Avoidance like that doesn't come from reputation alone; it comes from recent memory.  Smart managers learn quickly in {arena}.",
    "Whenever {team} appeared on the board, opponents suddenly developed scheduling conflicts.  Fear dresses itself as caution in many ways, and this turn wore it openly.",
    "Schedules don't lie, and this turn revealed growing hesitation around {team}.  Challenges that once came freely are now reconsidered, delayed, or quietly withdrawn.  Reputation is finally catching up.",
    "Once the first manager avoided {team}, others followed.  Fear spreads efficiently under the guise of scheduling logic.",
    "Beneath the noise of the arena, careful managers adjusted pairings with intent.  Not all victories this turn required combat.  {team} benefited from the arithmetic.",
]


_BLK_CHAMP_NEW = [
    "The crowds were amazed this turn, as {champion} of {champ_team} dethroned the reigning Champion in a fight that will be talked about for turns to come.  A new name atop the throne.",
    "{champion} of {champ_team} has done what countless rivals only dreamed of: claimed the Championship in direct combat.  The arena has a new ruler, and the pretenders must recalculate.",
    "Stop the histories and note the date: {champion} of {champ_team} is the new Champion of {arena}.  The old order ends.  The new one has precisely one member.",
]

_BLK_CHAMP_INCUMBENT = [
    "{champion} of {champ_team} defended the throne this turn by simple absence of defeat.  Holding the title invites endless scrutiny, yet few step forward to challenge it.",
    "Still undefeated, {champion} of {champ_team} remains the Champion.  Another turn passes, and the pretenders are no closer to dislodging the title.",
    "The arena is defined by presence, and {champion} of {champ_team} continues to provide it.  The Championship throne remains occupied, another turn's triumph for the incumbent.",
    "While others plotted advancement, {champion} of {champ_team} simply endured.  The Championship waits for challengers bold enough to contest it.",
    "{champion} of {champ_team} holds the throne without fanfare.  In {arena}, consistency on the title is worth more than any grand gesture.",
]

_BLK_CHAMP_VACANT = [
    "The Championship throne remains empty this turn.  No warrior has yet met the criteria to claim it.  Every manager with ambition should be watching their most recognised fighter closely.",
    "No Champion walks the arena floor this turn.  The vacancy is an open invitation, and somewhere in {arena}, someone is already planning to answer it.",
    "The title sits unclaimed in {arena}, which means every warrior with enough recognition and enough nerve has cause to press forward.  The throne waits.",
]

_BLK_CHAMP_RECOGNITION = [
    "The Championship does not always change hands through combat.  This turn, the ledger made its own decision: {champion} of {champ_team} carries the highest recognition in {arena}, and with it, the title.  The mathematics require no ceremony.",
    "No fight was needed.  The standings spoke clearly enough.  {champion} of {champ_team} holds more recognition than any other warrior in {arena} and now holds the Championship to match.  The title follows the record.",
    "{champion} of {champ_team} did not take the title from anyone.  The title came to them.  With the highest recognition score on the roster, the Championship has found its rightful occupant by right of standing.",
    "The Championship throne has a new occupant by recognition: {champion} of {champ_team}.  No duel, no drama.  Simply the reward for being the best-regarded warrior in {arena}.  The arena's verdict is rarely delivered so quietly.",
    "When no one earns the title by force, the records decide.  {champion} of {champ_team} sits atop those records this turn, and the Championship follows.  Whether they can hold it in combat is a question for future turns.",
]

_BLK_DEATH = [
    "{warrior} will not be appearing on future schedules.  Slain by {killer} this turn, their career ends at {record}.  {arena} makes no distinction between early exits and late ones.  Only between active and gone.",
    "{warrior} was cut down by {killer} this turn and will not return.  The record reads {record}.  Final.  {arena} moves on as it always does, without ceremony.",
    "The career of {warrior} has come to its end.  {killer} finished what the record was already suggesting.  A {record} showing at the close, and a vacant slot on the {team} roster.",
    "{killer} made it permanent this turn.  {warrior} is no longer on any schedule, no longer a factor in any planning.  Record: {record}.",
    "{warrior} entered the arena this turn and did not leave it in the usual way.  {killer} delivered the verdict, and {arena} accepted it without argument.  Career record: {record}.",
    "The stands quieted when {warrior} fell to {killer}, if only for a moment.  Then the next fight was called, and the arena continued.  It always does.  Final record: {record}.",
    "Short or long, every career in {arena} ends the same way.  {warrior}'s ended this turn, at the hands of {killer}.  The record says {record}.  The rest is silence.",
    "Gone.  {warrior} of {team}, career record {record}, was put down by {killer} this turn and will not return to any schedule.  Another name moves from the active ledger to the permanent one.",
    "{warrior} is dead.  {killer} handled the business of it, and now {team} has a vacancy and a memory.  Not always in that order, but always in that combination.",
    "Nobody told {warrior} it was going to end this turn.  {killer} understood what was happening before the crowd did.  Final record: {record}.",
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
    "There's a name to write down: {warrior} of {team}.  After running through {opponent} this turn, they've climbed to {points} recognition and show no signs of slowing.",
    "The crowd got what they wanted when {warrior} stepped out and made quick work of {opponent}.  Now at {points} recognition, this fighter is becoming a problem for opponents at this level.",
    "No debate after {warrior} of {team} handled {opponent} this turn.  Sitting at {points} recognition, this one is simple math and bad news for whoever faces them next.",
    "Quietly and efficiently, {warrior} of {team} put {opponent} down and climbed to {points} recognition.  The quiet ones are always the ones you didn't adjust for in time.",
    "Someone's going to challenge {warrior} of {team} soon and discover they've made a bad decision.  After handling {opponent} this turn and reaching {points} recognition, the gap between reputation and reality has officially closed.",
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
    "The standings now officially reflect what the fight already told us: {warrior} was not ready for {opponent} this turn.  The gap between tiers is rarely as polite as the schedule implies.",
]

_BLK_CHALLENGE_WIN = [
    "I just want to tip my hat to {warrior}, who took on {opponent} from a lower spot in the rankings and came out ahead.  The smart money wasn't on it.  The smart money was wrong.",
    "Congratulations are in order for {warrior}, who overcame both {opponent} and the recognition gap between them.  That kind of result earns more than points.  It earns a reputation.",
    "Not everyone challenges up and survives to tell it.  {warrior} did, putting {opponent} down in a result that surprised most of {arena}.  Well earned.",
    "They said {warrior} was overmatched against {opponent}.  {warrior} apparently didn't hear that part.  The result speaks clearly enough.",
    "Challenging up is brave.  Winning is better.  {warrior} managed both this turn against {opponent}, and the recognition that followed was entirely deserved.",
]

_BLK_CHALLENGE_LOSS = [
    "{warrior} had better have a very good reason for challenging down against {opponent} and still coming away with a loss.  I thought {warrior} showed great skill and promise when they were absolutely flattened.  All right, I slept through it.  Big deal.",
    "Challenging down is supposed to be the safe play.  Someone should tell {warrior} that, since they managed to lose to {opponent} anyway.  That requires a special kind of effort.",
    "The most charitable reading of {warrior}'s challenge against {opponent} is that they underestimated the competition.  The least charitable reading is also probably correct.",
    "I've seen bad challenges before, but {warrior} going after {opponent}, a lower-ranked opponent, and still losing is a special kind of expensive.  The recognition gap made it look safe.  It wasn't.",
    "Some lessons cost coin.  Some cost pride.  {warrior}'s loss to {opponent} in what should have been a comfortable challenge cost both.  Thoroughly.",
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
]

_BLK_SECOND_TEAM = [
    "Worth keeping an eye on as well: {team}, whose {record} turn has them quietly positioned better than their current standing suggests.  Not the story of the turn, but perhaps the beginning of one.",
    "{team} didn't top the board, but their {record} showing this turn was more instructive than the standings give credit for.  Fights are often decided before they begin, and {team} is winning that preparation battle.",
    "While the top and bottom of the standings absorb attention, {team} turned in a {record} showing that deserves a mention.  Consistency in the middle is how teams eventually reach the top, or stop pretending they won't.",
    "The {record} posted by {team} this turn is the kind of result that makes observers revise their estimates.  Neither the best nor the worst showing, but one that suggested more than it confirmed.",
    "In a turn with bigger headlines elsewhere, {team} quietly posted a {record} record that says something about their direction.  {arena} tends to reward the teams that don't need the biggest story to keep moving forward.",
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
]


def _pick_block(pool: list, used: set, ctx: dict) -> str:
    """Pick an unused block from pool, format it with ctx, mark raw template as used."""
    available = [b for b in pool if b not in used]
    if not available:
        available = list(pool)
    template = random.choice(available)
    used.add(template)
    return template.format(**ctx)


def _block_commentary(card, teams, deaths, turn_num: int, champion_state: dict, is_new_champion: bool = False) -> str:
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

    # Base context - always keep every key present so format() never raises
    ctx = dict(
        arena=arena, venue=venue, byline=byline,
        turn=turn_num, next_turn=turn_num + 1,
        team="", team2="", record="", killer="",
        rank_change="", warrior="", opponent="",
        points="", champion=_trunc(champ).upper() if champ else "",
        champ_team=_trunc(champ_t).upper() if champ_t else "",
    )

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
        p1.append(_pick_block(_BLK_CHAMP_RECOGNITION, used, ctx))
    elif champ and not is_new_champion:
        ctx["champion"]   = _trunc(champ).upper()
        ctx["champ_team"] = _trunc(champ_t).upper()
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
        p3.append(_pick_block(_BLK_WARRIOR_RISER, used, ctx))

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
        p3.append(_pick_block(_BLK_WARRIOR_FALLER, used, ctx))

    # If we have a third notable winner and no good loser story, spotlight them
    if len(notable_losers) < 1 and len(winners_list) > 2:
        w2 = winners_list[2]
        ctx["warrior"]  = _trunc(w2["warrior"]).upper()
        ctx["team"]     = _trunc(w2["team"]).upper()
        ctx["opponent"] = _trunc(w2["opponent"]).upper()
        ctx["points"]   = str(w2["recs"])
        p3.append(_pick_block(_BLK_WARRIOR_HI, used, ctx))

    if p3:
        paragraphs.append("  ".join(p3))

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
        p4.append(_pick_block(_BLK_CHALLENGE_WIN, used, ctx))

    if down_losses:
        worst = sorted(down_losses, key=lambda x: -x["abs_diff"])[0]
        ctx["warrior"]  = _trunc(worst["challenger"]).upper()
        ctx["team"]     = _trunc(worst["challenger_team"]).upper()
        ctx["opponent"] = _trunc(worst["challenged"]).upper()
        ctx["points"]   = str(worst["abs_diff"])
        p4.append(_pick_block(_BLK_CHALLENGE_LOSS, used, ctx))

    # Streak warrior spotlight
    if streak_warriors:
        sw = streak_warriors[0]
        ctx["warrior"] = _trunc(sw["warrior"]).upper()
        ctx["team"]    = _trunc(sw["team"]).upper()
        p4.append(_pick_block(_BLK_STREAK, used, ctx))

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
        p6.append(_pick_block(_BLK_META_WARRIOR, used, ctx))

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
            p7.append(_pick_block(_BLK_DEATH, used, ctx))

    p7.append(_pick_block(_BLK_PHILOSOPHICAL, used, ctx))

    paragraphs.append("  ".join(p7))

    # ==================================================================
    # PARAGRAPH 8 - OUTRO / SIGN-OFF
    # ==================================================================
    paragraphs.append(_pick_block(_BLK_OUTRO, used, ctx))

    article = "\n\n".join(paragraphs)
    return "\n\nArena Happenings\n\n" + article

# ---------------------------------------------------------------------------
# TOP MANAGERS SECTION
# ---------------------------------------------------------------------------

def _top_managers(card, teams, turn_num) -> str:
    """
    Generate manager standings sorted by win percentage (best to worst).
    Presents current-turn and career records side by side.
    Career records are calculated from actual turn result files (1..turn_num).
    """
    # Load complete standings data from JSON for team info (but not for career records)
    standings_data = _load_standings_data()

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

    # First pass: calculate career records from actual turn result files
    # This ensures career totals are accurate and divisible by 5
    from pathlib import Path
    import os as _os

    for t in range(1, turn_num + 1):
        turn_dir = Path(_os.path.join(LEAGUE_DATA_DIR, f"turn_{t:04d}"))
        if not turn_dir.exists():
            continue

        result_files = list(turn_dir.glob("result_*.json"))
        result_files = [f for f in result_files if f.name.endswith(".json") and ".checksum" not in f.name]

        for result_file in result_files:
            try:
                result_data = _load_json(str(result_file), {})
                if not result_data:
                    continue

                mgr_name = result_data.get("manager_name", "?").strip()
                if mgr_name == "?" or mgr_name in _NPC_TEAM_NAMES:
                    continue

                if mgr_name not in manager_records:
                    manager_records[mgr_name] = {"w": 0, "l": 0, "k": 0,
                                                "cw": 0, "cl": 0, "ck": 0}

                # Add career record from this turn's result
                for bout in result_data.get("bouts", []):
                    if bout.get("result") == "WIN":
                        manager_records[mgr_name]["cw"] += 1
                        if bout.get("opponent_slain"):
                            manager_records[mgr_name]["ck"] += 1
                    elif bout.get("result") == "LOSS":
                        manager_records[mgr_name]["cl"] += 1
            except Exception as e:
                pass  # Skip files that can't be loaded

    # Second pass: calculate THIS TURN records from the card (only participating teams)
    for team in teams:
        if _is_npc_team(team): continue

        mgr_name = getattr(team, "manager_name", None) or team.get("manager_name", "?")
        if mgr_name == "?":
            continue

        if mgr_name not in manager_records:
            manager_records[mgr_name] = {"w": 0, "l": 0, "k": 0,
                                        "cw": 0, "cl": 0, "ck": 0}

        # Calculate this team's record for the turn
        tname = getattr(team, "team_name", None) or team.get("team_name", "?")
        for bout in unique_bouts:
            pt = bout.player_team
            ot = bout.opponent_team
            ptname = getattr(pt, "team_name", None) or pt.get("team_name", "?")
            otname = getattr(ot, "team_name", None) or ot.get("team_name", "?")
            pw_won = bout.result.winner and bout.result.winner.name == bout.player_warrior.name

            if ptname == tname:
                if pw_won:
                    manager_records[mgr_name]["w"] += 1
                    if bout.result.loser_died:
                        manager_records[mgr_name]["k"] += 1
                else:
                    manager_records[mgr_name]["l"] += 1
            elif otname == tname:
                if not pw_won:
                    manager_records[mgr_name]["w"] += 1
                    if bout.result.loser_died:
                        manager_records[mgr_name]["k"] += 1
                else:
                    manager_records[mgr_name]["l"] += 1

    # Calculate win percentages and sort
    manager_list = []
    for mgr_name, rec in manager_records.items():
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
    SEP = "=" * 140
    left_hdr = f"{'  MANAGER':<35}{'W':>4}{'L':>4}{'K':>4}{'%':>7}{'TOTAL':>6}"
    right_hdr = left_hdr
    HDR = left_hdr + gap + right_hdr

    lines = [f"\n{left_title:<61}{gap}{right_title}", HDR, SEP]

    for mgr_turn, mgr_career in zip(manager_list_turn, manager_list_career):
        left_data = (f" {mgr_turn['name']:<34}{mgr_turn['w']:>4}{mgr_turn['l']:>4}{mgr_turn['k']:>4}"
                     f"{mgr_turn['pct']:>6.1f}%{mgr_turn['total']:>6}")
        right_data = (f" {mgr_career['name']:<34}{mgr_career['cw']:>4}{mgr_career['cl']:>4}{mgr_career['ck']:>4}"
                      f"{mgr_career['cpct']:>6.1f}%{mgr_career['ctotal']:>6}")
        lines.append(left_data + gap + right_data)

    lines.append(SEP)
    result = "\n".join(lines)
    return result


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------

def generate_newsletter(turn_num, card, teams, deaths, champion_state,
                        processed_date=None, is_new_champion=False) -> str:
    sections = [_header(turn_num, processed_date)]
    sections.append(_team_standings(teams, turn_num, card))
    sections.append("\n\n" + _top_managers(card, teams, turn_num))
    sections.append("\n\n" + _block_commentary(card, teams, deaths, turn_num, champion_state, is_new_champion))
    sections.append("\n\n" + _warrior_tiers(teams, champion_state, card, turn_num))
    
    # Add monster kills section if there are any
    monster_kills = _monster_kills_section(card)
    if monster_kills:
        sections.append("\n\n" + monster_kills)
    
    sections.append("\n\n" + _fights_section(card, champion_state))
    dead = _dead_section(deaths, turn_num)
    if dead: sections.append("\n\n" + dead)
    sections.append("\n\n" + _race_report(teams))
    return "\n".join(sections)

