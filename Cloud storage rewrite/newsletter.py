# =============================================================================
# newsletter.py — BLOODSPIRE Arena Newsletter Generator
# =============================================================================
import random, datetime
from typing import List, Optional

ARENA_NAME  = "Bloodspire Arena"
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
                     champion_beaten_by: str = None, champion_beaten_team: str = None,
                     prev_champion_name: str = None) -> tuple:
    """
    Update the champion state based on battle outcomes and warrior recognition.
    
    Returns:
        (champion_state_dict, is_new_champion) where is_new_champion is True if the
        current champion name differs from prev_champion_name.
    """
    dead_names = {d["name"] for d in deaths_this_turn}
    prev_champ = prev_champion_name or champion_state.get("name", "")
    
    # A warrior who beat the current champion claims the title immediately.
    if champion_beaten_by:
        new_state = {"name": champion_beaten_by, "team_name": champion_beaten_team or "Unknown",
                     "source": "beat_champion"}
        is_new = (champion_beaten_by != prev_champ)
        return new_state, is_new
    
    current_champ = champion_state.get("name", "")
    if current_champ and current_champ in dead_names:
        current_champ = ""
    if current_champ:
        # Champion still alive and not beaten — check if incumbent or first time
        is_new = (current_champ != prev_champ)
        return champion_state, is_new
    
    # No champion — find the warrior with the highest recognition score.
    all_warriors = []
    for team in teams:
        tname = team.team_name if hasattr(team,"team_name") else team.get("team_name","?")
        if tname in _NPC_TEAM_NAMES: continue
        wlist = team.warriors if hasattr(team,"warriors") else team.get("warriors",[])
        for w in wlist:
            if not w: continue
            if hasattr(w,"name"): wobj=w
            else:
                from warrior import Warrior
                try:    wobj=Warrior.from_dict(w)
                except: continue
            if getattr(wobj,"is_dead",False): continue
            if wobj.name in dead_names: continue
            all_warriors.append((wobj, tname))
    if not all_warriors: return {}, False
    
    # Sort by recognition (primary) then win percentage (tiebreak).
    all_warriors.sort(key=lambda x: (-getattr(x[0],"recognition",0),
                                      -(x[0].wins/max(1,x[0].total_fights)),
                                      x[0].name, x[1]))
    best_rec = getattr(all_warriors[0][0], "recognition", 0)
    tied     = [x for x in all_warriors if getattr(x[0],"recognition",0) == best_rec]
    if len(tied) > 1:
        best_pct = tied[0][0].wins / max(1, tied[0][0].total_fights)
        still    = [x for x in tied
                    if abs(x[0].wins/max(1,x[0].total_fights) - best_pct) < 0.001]
        if len(still) > 1:
            # Final tiebreak: alphabetical by name then team — deterministic, never a tie
            still.sort(key=lambda x: (x[0].name, x[1]))
    champ_w, champ_t = all_warriors[0]
    new_state = {"name": champ_w.name, "team_name": champ_t, "source": "recognition"}
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
    # Active + dead-awaiting-replacement — still in the warriors list
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


def _team_standings(teams, turn_num: int) -> str:
    rows = []
    for team in teams:
        if _is_npc_team(team): continue
        name = team.team_name if hasattr(team,"team_name") else team.get("team_name","?")
        tid  = team.team_id   if hasattr(team,"team_id")   else team.get("team_id",0)
        hist = getattr(team,"turn_history",[]) if hasattr(team,"turn_history") else team.get("turn_history",[])
        # Cumulative career record (all warriors ever on this team)
        tw, tl, tk = _team_career_record(team)
        tf=tw+tl; pct=(tw/tf*100) if tf else 0.0
        last5=hist[-5:] if hist else []
        l5w=sum(h.get("w",0) for h in last5)
        l5l=sum(h.get("l",0) for h in last5)
        l5k=sum(h.get("k",0) for h in last5)
        rows.append({"name":name,"id":tid,"w":tw,"l":tl,"k":tk,"pct":pct,
                     "l5w":l5w,"l5l":l5l,"l5k":l5k})
    rows.sort(key=lambda r:(-r["pct"],-(r["w"])))
    rows_l5=sorted(rows,key=lambda r:(-(r["l5w"]+r["l5k"]),r["l5l"]))

    # Fixed column widths — total line ~100 chars
    # Career side: rank(5) + name(28) + W(4) + L(4) + K(4) + %(7) = 52
    # Last5 side:  rank(5) + name(28) + W(4) + L(4) + K(4) = 45
    SEP = "="*100
    HDR = (f"{'#':<5}{'CAREER STANDINGS':<28}{'W':>4}{'L':>4}{'K':>4}{'%':>7}"
           f"   {'#':<5}{'LAST 5 TURNS':<28}{'W':>4}{'L':>4}{'K':>4}")
    lines=["\nThe Top Teams\n", HDR, SEP]
    for i,(r,r5) in enumerate(zip(rows,rows_l5),1):
        # Truncate name+id to exactly 28 chars
        cname  = f" {r['name'][:22]} ({r['id']})"[:28]
        c5name = f" {r5['name'][:22]} ({r5['id']})"[:28]
        career = f"{i:<5}{cname:<28}{r['w']:>4}{r['l']:>4}{r['k']:>4}{r['pct']:>6.1f}%"
        last5s = f"   {i:<5}{c5name:<28}{r5['l5w']:>4}{r5['l5l']:>4}{r5['l5k']:>4}"
        lines.append(career + last5s)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# WARRIOR TIERS
# ---------------------------------------------------------------------------

def _warrior_tiers(teams, champion_state: dict) -> str:
    champ_name=champion_state.get("name","")
    tiers={t:[] for t in [TIER_CHAMPION,TIER_ELITES,TIER_VETERANS,TIER_ADEPTS,
                           TIER_INITIATES,TIER_ROOKIES,TIER_RECRUITS]}
    for team in teams:
        if _is_npc_team(team): continue
        tname=team.team_name if hasattr(team,"team_name") else team.get("team_name","?")
        tid  =team.team_id   if hasattr(team,"team_id")   else team.get("team_id",0)
        wlist=team.warriors  if hasattr(team,"warriors")  else team.get("warriors",[])
        for w in wlist:
            if not w: continue
            wobj=_get_warriors(w)
            if not wobj: continue
            if getattr(wobj,"is_dead",False): continue
            rname=wobj.race.name if hasattr(wobj.race,"name") else "Human"
            if rname in _NPC_RACES: continue
            # Don't show replacement warriors until they've competed at least once
            if getattr(wobj,"total_fights",0) == 0: continue
            tiers[_warrior_tier(wobj,wobj.name==champ_name)].append({
                "name":wobj.name,"team":tname,"tid":tid,
                "w":wobj.wins,"l":wobj.losses,"k":wobj.kills,
                "rec":getattr(wobj,"recognition",0),
            })
    SEP = "="*70
    # Fixed columns: name(22) + W(4) + L(4) + K(4) + Rec(4) + team
    COL_HDR = f"{'NAME':<22}{'W':>4}{'L':>4}{'K':>4}  {'REC':>3}  TEAM"
    sections=[]
    for tier in [TIER_CHAMPION,TIER_ELITES,TIER_VETERANS,TIER_ADEPTS,TIER_INITIATES,TIER_ROOKIES,TIER_RECRUITS]:
        wlist=tiers[tier]
        if not wlist and tier==TIER_CHAMPION:
            sections.append(f"\n{tier}\n{COL_HDR}\n{SEP}\n  (vacant this turn)"); continue
        if not wlist: continue
        wlist.sort(key=lambda x:(-x["rec"],-(x["w"]/max(1,x["w"]+x["l"]))))
        lines=[f"\n{tier}\n{COL_HDR}",SEP]
        for wd in wlist:
            tm=f"{wd['team'][:22]} ({wd['tid']})"
            lines.append(f"{wd['name'][:22]:<22}{wd['w']:>4}{wd['l']:>4}{wd['k']:>4}"
                         f"  {wd['rec']:>3}  {tm}")
        sections.append("\n".join(lines))
    return "\n".join(sections)+"\n'-' denotes a warrior who did not fight this turn."


# ---------------------------------------------------------------------------
# DEAD / FIGHTS / RACE REPORT
# ---------------------------------------------------------------------------

def _dead_section(deaths: list, turn_num: int) -> str:
    if not deaths: return ""
    sep="="*87
    lines=["\nTHE DEAD",
           f"{'NAME':<22}{'W':>4}{'L':>4}{'K':>4}  {'TEAM':<24}{'SLAIN BY':<22}{'TURN':>5}",sep]
    for d in deaths:
        name = d['name'][:22]
        team = d.get('team','?')[:24]
        slain = d.get('killed_by','?')[:22]
        lines.append(f"{name:<22}{d.get('w',0):>4}{d.get('l',0):>4}{d.get('k',0):>4}"
                     f"  {team:<24}{slain:<22}{turn_num:>5}")
    return "\n".join(lines)


def _fights_section(card) -> str:
    sep="="*75
    lines=["\nLAST TURN'S FIGHTS",sep]
    # Organize by fight type: monster, blood_challenge, challenge, rivalry, peasant
    _order = {"monster":0, "blood_challenge":1, "challenge":2, "rivalry":3, "peasant":4}
    sorted_card = sorted(card, key=lambda b: _order.get(getattr(b,"fight_type","rivalry"), 3))

    # Deduplicate: collapse A-vs-B and B-vs-A to one line.
    seen_pairs = set()
    for bout in sorted_card:
        pw=bout.player_warrior; ow=bout.opponent; r=bout.result
        if not r: continue
        pair = frozenset([pw.name, ow.name])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        pw_won=r.winner and r.winner.name==pw.name
        winner=pw if pw_won else ow; loser=ow if pw_won else pw
        mins=r.minutes_elapsed
        if bout.fight_type == "champion":
            ftype = "Champions Title"
        elif bout.fight_type in ("standard", "rivalry", "peasant", "monster"):
            ftype = ""
        else:
            ftype = bout.fight_type.replace("_"," ")
        style=_fight_style_word(mins)
        
        # Determine action verb based on challenge type
        if bout.fight_type in ["challenge", "blood_challenge"]:
            # For challenge fights, always list challenger first
            challenger = bout.challenger_name
            if challenger == winner.name:
                # Challenger won
                if r.loser_died:
                    line = f"{winner.name} savagely slew {loser.name} in a {mins} minute {style} Challenge fight."
                else:
                    verb = random.choice(["bested","defeated","outlasted","overcame","vanquished"])
                    line = f"{winner.name} {verb} {loser.name} in a {mins} minute {style} Challenge fight."
            else:
                # Challenger lost
                if r.loser_died:
                    line = f"{winner.name} savagely slew {loser.name} in a {mins} minute {style} Challenge fight."
                else:
                    verb = random.choice(["bested","defeated","outlasted","overcame","vanquished"])
                    line = f"{winner.name} {verb} {loser.name} in a {mins} minute {style} Challenge fight."
        else:
            # Regular fight
            ftype_str = f" {ftype}" if ftype else ""
            if r.loser_died:
                line=(f"{winner.name} slew {loser.name} in a {mins} minute {style}{ftype_str} fight."
                      if pw_won else
                      f"{loser.name} was slain by {winner.name} in a {mins} minute {style}{ftype_str} fight.")
            else:
                verb=random.choice(["bested","defeated","outlasted","overcame","vanquished"])
                line=f"{winner.name} {verb} {loser.name} in a {mins} minute {style}{ftype_str} fight."
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
        line = (f">>> {slayer['warrior']} (Team: {slayer['team']}) {message}\n"
                f"    Slew the monster {slayer['monster']} {time_str}.\n"
                f"    A replacement warrior slot is now available on {slayer['team']}.")
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
        lines.append(f"{'RACE':<14}{'WARRIOR':<26}{'W':>4}{'L':>4}{'K':>3}  TEAM NAME"); lines.append(sep)
        for race in races:
            if race in top:
                td=top[race]
                lines.append(f"{race:<14}{td['warrior']:<26}{td['w']:>4}{td['l']:>4}{td['k']:>3}"
                              f"  {td['team']} ({td['tid']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ARENA HAPPENINGS — modular narrative block libraries
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
    "Dax Ironquill, Bloodspire Gazette",
    "Mira Coldtongue, The Blood Ledger",
    "Horst Veyne, Pit Press Weekly",
    "Snide Clemens, Arena Correspondent",
    "Alarond the Scribe",
    "The Unknown Spymaster",
    "Olaf Modeen, Retired Correspondent",
    "Bryndis Coldquill, Arena Correspondent",
    "Magistra Pellwood, Official Chronicle",
    "Aldric Fenworth, Bloodspire Gazette",
]

_BLK_INTRO = [
    "Another turn has passed in {arena}, and the dust still hangs heavy where blades met bone.  Victories were earned, pride was lost, and more than one plan failed the moment steel left its scabbard.  As always, the arena cared little for intent — only outcomes.",
    "If hope walked into {arena} this turn, it didn't leave intact.  Managers talked big, warriors listened poorly, and the standings now tell the truth no one wanted to hear.  Let's go over who impressed — and who shouldn't bother pretending.",
    "Hear me now!  {arena} thundered beneath the weight of ambition this turn, and the ambitious were sorted from the foolish with ruthless clarity.  Songs will exaggerate what happened here — but not by much.",
    "I heard three versions of this turn at {venue}, and every one got louder with each drink.  Somewhere between the boasting and the lies is what really happened in {arena}.  Lucky for you, I paid attention.",
    "The turn began like any other and ended exactly as it had to in {arena}.  Some rose, some fell, and fate collected its due without apology.  Let's read the damage.",
    "{arena} doesn't announce when it's about to teach someone a lesson.  It just waits for confidence to turn into error.  This turn was no exception.",
    "Another turn came and went in {arena}, leaving the standings rearranged and several reputations in urgent need of explanation.  Tradition holds firm.",
    "Managers entered this turn with plans.  Warriors entered with steel.  Only one of those things survived contact with reality in {arena}.",
    "{arena} woke hungry this turn, and it was fed without restraint.  What follows are the names of those who satisfied it — and those who regretted trying.",
    "I have seen many turns in many places, and {arena} remains uniquely honest.  It rewards preparation, punishes pride, and forgets quickly.",
]

_BLK_TEAM_PERF = [
    "{team} walked into the turn with questions and walked out with answers.  Their {record} showing pushed them {rank_change} in the standings, built on decisions that held up under pressure.  Others noticed — and adjusted accordingly.",
    "For {team}, the turn was uneven but instructive.  A {record} doesn't tell the whole story, but it does explain the current position in the rankings.  Progress was made, even if confidence was shaken.",
    "{team} somehow turned a {record} into upward movement, which says more about the competition than the performance.  The standings reward survival as much as excellence, and this turn favored the merely adequate.",
    "Nothing came easily for {team} this turn, and most things went wrong.  Their {record} reflected hesitant choices and punishment delivered on schedule.  Lessons were taught — whether anyone learned them remains to be seen.",
    "{team} didn't dominate this turn, but they endured it.  Their {record} reflects hard choices made under pressure, and the standings rewarded resolve over spectacle.  In {arena}, that distinction matters more often than most admit.",
    "{team} avoided spectacle and focused on execution this turn.  The resulting {record} pushed them {rank_change}, a reminder that consistency still matters here.",
    "The standings record {team}'s {record}, but it's the confidence that followed which concerns rival managers.  Momentum, once earned, is difficult to interrupt.",
    "{team} will likely cite matchups, luck, or scheduling after their {record} this turn.  The rankings, unfortunately, only record outcomes.",
    "It wasn't pretty, but {team} emerged intact with a {record} showing.  In {arena}, survival buys time — and time buys improvement.",
    "Something changed for {team} this turn.  Whether the {record} marks the beginning of a rise or a brief correction remains to be seen.",
]

_BLK_WARRIOR_HI = [
    "{warrior} left little to debate after facing {opponent}.  The fight was decisive, the outcome clearer by the moment, and {points} recognition to their name.  That performance will linger in memory longer than the scars.",
    "Confidence led {warrior} into the arena this turn against {opponent}, and confidence alone proved insufficient.  The loss stung, both in pride and standing, but harsh lessons tend to last longer than easy wins.",
    "Preparation paid off when {warrior} stepped into the arena this turn.  Against {opponent}, patience and timing proved more dangerous than brute force, earning quiet respect from those paying attention.",
    "{warrior} showed courage in facing {opponent}, which would have mattered more if judgment had joined the effort.  The crowd was entertained.  The records were not forgiving.",
    "Victory rarely announces itself loudly in {arena}.  {warrior} overcame {opponent} through patience and timing, not force, earning recognition through discipline rather than drama.  Few noticed at first — but many will remember.",
    "{warrior} entered the arena with a plan and left without an argument.  {opponent} never found footing, and the result was entirely predictable from the opening exchange.",
    "{warrior} underestimated {opponent}, a mistake corrected decisively before the crowd grew bored.  In {arena}, assumptions are expensive.",
    "The fight wasn't clean, fast, or elegant — but {warrior} endured.  Against {opponent}, persistence carried the day and the record followed.",
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
    "Managers were noticeably reluctant to schedule fights against {team} this turn.  Avoidance like that doesn't come from reputation alone — it comes from recent memory.  Smart managers learn quickly in {arena}.",
    "Whenever {team} appeared on the board, opponents suddenly developed scheduling conflicts.  Fear dresses itself as caution in many ways, and this turn wore it openly.",
    "Schedules don't lie, and this turn revealed growing hesitation around {team}.  Challenges that once came freely are now reconsidered, delayed, or quietly withdrawn.  Reputation is finally catching up.",
    "Once the first manager avoided {team}, others followed.  Fear spreads efficiently under the guise of scheduling logic.",
    "Beneath the noise of the arena, careful managers adjusted pairings with intent.  Not all victories this turn required combat.  {team} benefited from the arithmetic.",
]

_BLK_CHAMP_HOLDS = [
    "{champion} remains atop {arena}, not through spectacle, but through consistency.  Another turn passed without a successful challenge, reinforcing a reign built on reliability rather than luck.",
    "The Champion survived the turn, which technically counts as success in this arena.  Whether {champion} inspired fear or simply benefited from unconvincing challengers is open for debate.",
    "Holding the top spot is harder than taking it, and {champion} demonstrated why.  The throne remains occupied, and challengers are running out of excuses.",
    "Sitting atop the rankings does not grant {champion} comfort, only scrutiny.  Every move is watched, every opponent motivated.  Another turn passes, and still the crown remains where it is.",
    "There was no grand announcement this turn — only confirmation.  {champion} continues to define the top rank through presence alone, forcing challengers to measure themselves before they ever step forward.",
    "Holding the top rank invites constant scrutiny, and {champion} of {champ_team} endured it again.  Another turn passed without displacement, tightening their grip on the title.",
    "Whether through fear or miscalculation, no challenger succeeded against {champion}.  The throne remains occupied, and increasingly familiar.",
    "Every schedule change and whispered plan still points toward {champion}.  Until someone succeeds, intention remains irrelevant.",
    "{champion} didn't dazzle this turn — they didn't need to.  Authority in {arena} is measured by outcomes, not applause.",
    "The arena grows restless under consistency, but {champion} continues to deliver it.  Resentment does little to move standings.",
]

_BLK_CHAMP_NEW = [
    "The crowds were amazed this turn, as {champion} of {champ_team} dethroned the reigning Champion in a fight that will be talked about for turns to come.  A new name atop the throne.",
    "{champion} of {champ_team} has done what countless rivals only dreamed — claimed the Championship in direct combat.  The arena has a new ruler, and the pretenders must recalculate.",
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

_BLK_DEATH = [
    "The Dark Arena claimed {warrior} this turn.  The fight ended as so many do — suddenly, decisively, and without ceremony.  In {arena}, remembrance is brief, but final.",
    "{warrior} will not return from the Dark Arena.  The schedule moved on quickly, as it always does.  The arena has no patience for nostalgia.",
    "Records like {record} eventually make demands.  {warrior} answered them in the Dark Arena, where explanations are no longer required.",
    "{warrior} entered the Dark Arena carrying more hope than history justified.  The outcome was swift, and the lesson permanent.  {arena} does not negotiate with potential.",
    "News of {warrior}'s end traveled quickly, then stopped mattering.  In the arena, loss is acknowledged briefly and replaced immediately.  The next fight always comes.",
    "{warrior}'s name was struck from future schedules this turn.  In {arena}, removal is swift and rarely discussed afterward.",
    "The Dark Arena offered no correction, only conclusion, for {warrior}.  The record tells the rest.  Career ended at {record}.",
    "The crowd quieted when {warrior} fell, if only briefly.  Then the next fight was announced, and {arena} moved on.",
    "For every rise in the standings, someone pays elsewhere.  This turn, {warrior} covered that cost.  Career record: {record}.",
    "{arena} has no room for regret.  {warrior} is gone, and the turn proceeds as scheduled.",
]

_BLK_OUTRO = [
    "The ink dries, the crowds thin, and {arena} waits for the next mistake.  Until then, I carry these accounts onward.  — {byline}",
    "That's the turn as it happened, not as it was advertised.  Anyone unhappy with the outcome is welcome to try again — results permitting.  — {byline}",
    "I'll be at {venue} if anyone wants to argue about it.  Bring coin, or don't bother.  — {byline}",
    "The turn is done.  The consequences remain.  — {byline}",
    "The turn is complete, the outcomes recorded, and the excuses already forming.  Whatever comes next, {arena} will be ready.  — {byline}",
    "The turn closes.  The implications remain.  Until Turn {next_turn} — {byline}",
    "{arena} will remember this turn longer than some warriors will.  — {byline}",
    "I've written worse turns, but not many.  See you in Turn {next_turn}.  — {byline}",
    "I'll raise a glass to the survivors.  The rest are beyond complaint.  Until next time — {byline}",
    "Until the brackets change again, this is what happened.  — {byline}",
]

# ---------------------------------------------------------------------------
# ADDITIONAL NARRATIVE POOLS — weave into the spy-report body
# ---------------------------------------------------------------------------

_BLK_WARRIOR_RISER = [
    "Hey everybody, keep your eye on {warrior} of {team} — after dispatching {opponent} this turn, this fighter sits at {points} recognition and is moving fast.  Rival managers are adjusting their schedules accordingly.",
    "Watch out for {warrior} of {team}, who turned {opponent} into a stepping stone this turn and climbed to {points} recognition doing it.  That performance won't be forgotten by the bookmakers.",
    "Word travels fast in {arena}, and right now it's all about {warrior} of {team}.  They made {opponent} look thoroughly outmatched and now sit at {points} recognition.  The kind of turn that changes how rivals plan.",
    "The stands were buzzing after {warrior} of {team} finished with {opponent}.  Efficient, controlled, and effective — {points} recognition now, and the number is still climbing.",
    "If you weren't watching {warrior} of {team} before, you should have been.  They dismantled {opponent} this turn and now carry {points} recognition.  Rival managers are circling this name with a worried quill.",
    "There's a name to write down: {warrior} of {team}.  After running through {opponent} this turn, they've climbed to {points} recognition and show no signs of slowing.",
    "The crowd got what they wanted when {warrior} stepped out and made quick work of {opponent}.  Now at {points} recognition, this fighter is becoming a problem for opponents at this level.",
    "No debate after {warrior} of {team} handled {opponent} this turn.  Sitting at {points} recognition, this one is simple math — and bad news for whoever faces them next.",
    "Quietly and efficiently, {warrior} of {team} put {opponent} down and climbed to {points} recognition.  The quiet ones are always the ones you didn't adjust for in time.",
    "Someone's going to challenge {warrior} of {team} soon and discover they've made a bad decision.  After handling {opponent} this turn and reaching {points} recognition, the gap between reputation and reality has officially closed.",
]

_BLK_WARRIOR_FALLER = [
    "And tumbling down the standings was {warrior}, who ran headlong into {opponent} and paid the price.  The records are unforgiving in {arena}, and right now they're not forgiving {warrior}.",
    "Falling like a fighter who forgot to block — {warrior} dropped a costly bout against {opponent} this turn.  Painful, and the standings will confirm it.",
    "Not every story has a happy ending, and {warrior}'s this turn doesn't even have a satisfying middle.  {opponent} handed them a loss that will linger longer than the bruises.",
    "{opponent} made a point at {warrior}'s expense this turn, and the point was well received by the crowd.  Less so by {warrior}'s team manager, one suspects.",
    "The {arena} crowd can be cruel, and when {warrior} fell to {opponent} this turn, the response was not sympathetic.  A loss at this stage carries consequences.",
    "On the wrong end of the highlights this turn was {warrior}, who had no answer for {opponent}.  The records now reflect what the crowd already knew.",
    "{warrior} left the arena considerably less confident than they entered it, courtesy of {opponent}.  That kind of adjustment tends to be educational — eventually.",
    "Somewhere between planning and execution, {warrior}'s turn fell apart against {opponent}.  It happens.  In {arena}, it tends to happen loudly.",
    "It wasn't {warrior}'s turn.  Or their fight.  Or their afternoon.  {opponent} took care of all of that efficiently and without apparent difficulty.",
    "The standings now officially reflect what the fight already told us: {warrior} was not ready for {opponent} this turn.  The gap between tiers is rarely as polite as the schedule implies.",
]

_BLK_CHALLENGE_WIN = [
    "I just want to tip my hat to {warrior}, who took on {opponent} from a lower spot in the rankings and came out ahead.  The smart money wasn't on it.  The smart money was wrong.",
    "Congratulations are in order for {warrior}, who overcame both {opponent} and the recognition gap between them.  That kind of result earns more than points — it earns a reputation.",
    "Not everyone challenges up and survives to tell it.  {warrior} did, putting {opponent} down in a result that surprised most of {arena}.  Well earned.",
    "They said {warrior} was overmatched against {opponent}.  {warrior} apparently didn't hear that part.  The result speaks clearly enough.",
    "Challenging up is brave.  Winning is better.  {warrior} managed both this turn against {opponent}, and the recognition that followed was entirely deserved.",
]

_BLK_CHALLENGE_LOSS = [
    "{warrior} had better have a very good reason for challenging down against {opponent} and still coming away with a loss.  I thought {warrior} showed great skill and promise when they were absolutely flattened.  All right, I slept through it.  Big deal.",
    "Challenging down is supposed to be the safe play.  Someone should tell {warrior} that, since they managed to lose to {opponent} anyway.  That requires a special kind of effort.",
    "The most charitable reading of {warrior}'s challenge against {opponent} is that they underestimated the competition.  The least charitable reading is also probably correct.",
    "I've seen bad challenges before, but {warrior} going after {opponent} — a lower-ranked opponent — and losing is a special kind of expensive.  The recognition gap made it look safe.  It wasn't.",
    "Some lessons cost coin.  Some cost pride.  {warrior}'s loss to {opponent} in what should have been a comfortable challenge cost both.  Thoroughly.",
]

_BLK_DIG_DEEPER = [
    "     Let's dig a little deeper into what's been going on in {arena} this turn.",
    "     Now let me tell you what the standings board won't.",
    "     Scratch the surface of this turn and the interesting parts start showing.",
    "     The official results tell one story.  Here's the version worth knowing.",
    "     There's always more to a turn than the final records.  Let's have a look.",
    "     You want the real story?  Here it is.",
    "     Beyond the numbers, there are names worth discussing in {arena}.",
    "     Pull up a chair — there's more to unpack from this turn in {arena}.",
    "     The ledger tells you who won.  I'll tell you what it means.",
    "     Now that we've got the scores, let's talk about what's actually happening in {arena}.",
]

_BLK_WORST_TEAM = [
    "A stormcloud is brewing over the {team} guildhouse.  A {record} showing is the kind of result that makes managers nervous and fighters start questioning their contracts.",
    "Meanwhile, {team} had a turn they'd rather forget — {record} is the sort of record that generates uncomfortable conversations in the team quarters.",
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
    "Being a spy is great — other people die and you spend the rest of the day drinking to their memory.  Better tanked than dead.  Ask not the elves for counsel, for they will say both yes and no.  Silly buggers.",
    "I've been doing this long enough to know that the best fights are the ones that prove me wrong.  This turn had a few of those.  I've already started forgetting them.",
    "They pay me to write this down.  Some turns I feel guilty about taking the coin.  This was not one of those turns.  {arena} delivered.",
    "A warrior's lot is filled with strife, revenge, and killing.  Some fighters don't accept this.  The best do.  The ones who argue about it never last long enough to change the subject.",
    "I was once told that the key to wisdom is knowing what you don't know.  I don't know how some of these managers keep their jobs.  There you have it.",
    "Remember: in {arena}, even a bad turn teaches something.  Whether anyone learns it is a different question entirely.",
    "Every turn ends the same way — with the stands emptying and the managers arguing about what went wrong.  It's the most honest part of the whole enterprise.",
    "Time for my medication.  Or another drink.  In this profession, the distinction rarely matters.",
    "All work and no play makes for a dull career.  All play and no training makes for a short one.  Somewhere in the middle is the winning formula.  Most warriors are still looking for it.",
    "Someone once asked me if I ever feel bad writing about losses.  I told them no.  They stopped asking me things after that, which I consider a personal victory.",
]

_BLK_KILL_HIGHLIGHT = [
    "{warrior} of {team} didn't just win this turn — they finished {opponent} permanently.  A kill is the arena's most definitive verdict, and {warrior} delivered it without ambiguity.  The other managers are adjusting their calculations accordingly.",
    "When {warrior} of {team} and {opponent} met this turn, only one of them left on their own terms.  Kills generate a particular kind of attention in {arena}, and {warrior} now has more of it than they may have wanted.",
    "The arena went quieter than usual when {warrior} of {team} finished {opponent} for good.  Then it got loud.  It always does.  In {arena}, kills are remembered long after wins are forgotten.",
    "Not all victories are created equal.  {warrior} of {team} collected the kind this turn that removes {opponent} from the schedule permanently.  The standing are adjusted.  The opponent's are not.",
    "Managers who have been casual about scheduling against {warrior} of {team} should revise their casualness.  After what was done to {opponent}, the risk calculation has changed considerably.",
    "A kill is a statement in {arena}.  {warrior} of {team} made one this turn.  {opponent} will not be contesting it, attending future turns, or offering a different interpretation.  The matter is settled.",
    "The most decisive result of the turn belonged to {warrior} of {team}.  {opponent} will not dispute it from where they are now.  The Dark Arena does not offer second opinions.",
    "They say {arena} forgets quickly.  That may be true — but it records everything first.  {warrior} of {team} has a kill on their ledger now, and that particular entry does not fade.",
    "Some fights end.  Some careers end.  When {warrior} of {team} met {opponent} this turn, it was the latter.  The crowd understood the distinction.  The bookmakers adjusted their lines before the body was cold.",
    "Word spreads fast after a kill, and the word this turn involves {warrior} of {team} and the permanent absence of {opponent}.  Recognition follows performance in {arena}, and nothing performs quite like finality.",
]

_BLK_BLOODY_TURN = [
    "This was not a gentle turn at {arena}.  Multiple careers ended today, and the atmosphere in the aftermath reflected that.  The business continues regardless, but some turns leave a mark on the crowd.",
    "The stands emptied more quietly than usual after this turn.  Multiple kills have a way of doing that.  {arena} earned its name today.",
    "I've covered bloodier turns, but not many in recent memory.  When the final accounting came in, the kill count was high enough that even the regulars took notice.  Some turns are reminders of what this place actually is.",
    "A reminder from {arena}: this is not sport.  Multiple deaths in a single turn communicate that clearly enough.  The survivors continue.  The others have concluded their participation permanently.",
    "Some turns are for standings.  Some are for lesson-learning.  This one was for the record books.  Multiple kills in a single turn is the arena's way of ensuring no one mistakes enthusiasm for preparation.",
]

_BLK_STREAK = [
    "While others debate matchups and massage their schedules, {warrior} of {team} has simply kept winning.  Sustained success in {arena} attracts attention, and that attention is no longer politely ignoring this fighter.",
    "{warrior} of {team} continues building something that is becoming difficult to dismiss.  Turn after turn, the wins accumulate.  The streak is long enough now that rival managers are no longer pretending not to notice.",
    "At some point a winning run stops being fortunate and starts being a pattern.  {warrior} of {team} has crossed that line, and the managers scheduling around them have already drawn the conclusion.",
    "Sustained winning is harder than one great performance, and {warrior} of {team} is proving it.  The streak puts this fighter in a different category of concern for anyone at this tier.",
    "The easiest prediction in {arena} right now involves {warrior} of {team} and an aggressive challenge appearing on the schedule soon.  Sustained success invites attention.  The streak has crossed a threshold.",
    "When a warrior keeps winning, {arena} eventually takes formal notice.  {warrior} of {team} is at that point.  The bookmakers have updated their lines.  The cautious managers have updated their schedules.",
    "{warrior} of {team} has a streak worth watching — and worth worrying about if you're the manager who has to face them next.  Momentum in {arena} is real, and this fighter has it.",
    "Not everyone survives long enough to build a streak in {arena}.  {warrior} of {team} is building one, and the length of it has become a topic of conversation in corners where scheduling decisions are made.",
]

_BLK_STANDINGS_LOOK = [
    "Step back from the individual results for a moment and look at what the standings are actually saying.  The distance between top and bottom is growing, and the middle tier is where all the meaningful maneuvering is still happening.",
    "The standings after this turn tell a story for anyone reading carefully.  Some managers are building toward something.  Others are surviving.  Both approaches produce a result — though not always the intended one.",
    "Standings in {arena} don't lie, but they do oversimplify.  Behind the records are patterns: managers adjusting, warriors peaking, and momentum that the numbers alone can't fully capture.  Worth watching.",
    "The scoreboard shows wins and losses.  What it doesn't show is which teams are trending in the right direction and which are sliding despite a respectable record.  In {arena}, direction matters as much as position.",
    "Every manager in {arena} is reading the same standings and drawing different conclusions.  That's the nature of this place.  The ones who read it correctly tend to keep doing so.  The ones who don't have an explanation ready.",
    "After this turn, the standings have sorted themselves into a picture that will define scheduling decisions for what comes next.  Some fighters are becoming commodities.  Others are becoming problems.  The ledger knows the difference.",
    "If you look at the trend lines rather than just this turn's results, {arena} is quietly separating into tiers that won't shift easily.  Managers in the top half have reason for optimism.  The rest have reason for urgency.",
    "It's worth remembering that every fight this turn had context — recognition gaps, grudges, avoidance patterns — that the final W-L record doesn't capture.  The standings are accurate.  They are also incomplete.",
]

_BLK_SECOND_TEAM = [
    "Worth keeping an eye on as well: {team}, whose {record} turn has them quietly positioned better than their current standing suggests.  Not the story of the turn, but perhaps the beginning of one.",
    "{team} didn't top the board, but their {record} showing this turn was more instructive than the standings give credit for.  Fights are often decided before they begin, and {team} is winning that preparation battle.",
    "While the top and bottom of the standings absorb attention, {team} turned in a {record} showing that deserves a mention.  Consistency in the middle is how teams eventually reach the top — or stop pretending they won't.",
    "The {record} posted by {team} this turn is the kind of result that makes observers revise their estimates.  Neither the best nor the worst showing, but one that suggested more than it confirmed.",
    "In a turn with bigger headlines elsewhere, {team} quietly posted a {record} record that says something about their direction.  {arena} tends to reward the teams that don't need the biggest story to keep moving forward.",
]

_BLK_MULTIPLE_DEATHS = [
    "The Dark Arena had a busy turn.  Multiple warriors will not be appearing on future schedules — their careers concluded, their records final.  {arena} moves on without ceremony, as it always does.",
    "More than one manager left this turn with a vacancy to fill.  The Dark Arena was active today, and the rosters that entered the turn are not the same ones that will prepare for the next one.",
    "When a turn produces multiple deaths, {arena} has a habit of becoming very quiet for a short time and then very loud.  Today followed that pattern exactly.  The scheduling implications are immediate.",
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
    by the reporter's voice — not as disconnected standalone paragraphs.

    Structure:
      Para 1 — Intro + champion headline + best team + worst team
      Para 2 — Warrior risers, fallers, notable challenge results
      Para 3 — Transition ("dig deeper") + avoidance/challenge meta
                + champion defends (if no title change this turn)
      Para 4 — Deaths (if any) + philosophical aside
      Para 5 — Outro / sign-off
    """
    arena  = ARENA_NAME.upper()
    venue  = "Bloodspire"
    byline = random.choice(_BLK_BYLINES)
    random.seed()
    used   = set()   # shared across ALL _pick_block calls — no repeats in one report

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
            print(f"  WARNING: {tname} has {total_fights} total fights ({rec['w']}-{rec['l']}) — exceeds max 5 for a turn")

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
        if wtname not in _NPC_TEAM_NAMES:
            winners_list.append({"warrior": winner.name, "team": wtname,
                                  "opponent": loser.name,
                                  "recs": getattr(winner, "recognition", 0),
                                  "is_kill": bout.result.loser_died})
        if ltname not in _NPC_TEAM_NAMES:
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

    most_challenged_warrior = max(challenge_counts.items(), key=lambda x: x[1])[0] if challenge_counts else None
    most_targeted_team      = max(targeted_counts.items(),  key=lambda x: x[1])[0] if targeted_counts else None
    if most_targeted_team in _NPC_TEAM_NAMES: most_targeted_team = None

    # Kill highlights (winners who scored a kill this turn)
    kill_highlights = [w for w in winners_list if w["is_kill"]]
    kill_count      = len(kill_highlights)

    # Streak warriors — 3+ consecutive wins, player teams only
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

    # Middle teams — between best and worst for secondary team coverage
    middle_teams = sorted_teams[1:-1] if len(sorted_teams) > 2 else []

    # Champion data
    champ     = champion_state.get("name", "")
    champ_t   = champion_state.get("team_name", "")
    champ_src = champion_state.get("source", "")

    # Base context — always keep every key present so format() never raises
    ctx = dict(
        arena=arena, venue=venue, byline=byline,
        turn=turn_num, next_turn=turn_num + 1,
        team="", team2="", record="",
        rank_change="", warrior="", opponent="",
        points="", champion=champ.upper() if champ else "",
        champ_team=champ_t.upper() if champ_t else "",
    )

    paragraphs = []

    # ==================================================================
    # PARAGRAPH 1 — INTRO + CHAMPION HEADLINE
    # Champion news (new or vacant) follows the intro as the biggest story.
    # ==================================================================
    p1 = []

    p1.append(_pick_block(_BLK_INTRO, used, ctx))

    # Champion — new champ is the biggest news; lead with it right after intro
    if champ and is_new_champion:
        ctx["champion"]   = champ.upper()
        ctx["champ_team"] = champ_t.upper()
        p1.append(_pick_block(_BLK_CHAMP_NEW, used, ctx))
    elif champ and not is_new_champion:
        ctx["champion"]   = champ.upper()
        ctx["champ_team"] = champ_t.upper()
        p1.append(_pick_block(_BLK_CHAMP_INCUMBENT, used, ctx))
    elif not champ:
        p1.append(_pick_block(_BLK_CHAMP_VACANT, used, ctx))

    paragraphs.append("  ".join(p1))

    # ==================================================================
    # PARAGRAPH 2 — TEAM PERFORMANCES + STANDINGS PERSPECTIVE
    # Best team, worst team, a middle-pack note, and a broader standings look.
    # ==================================================================
    p2 = []

    if best_name and best_rec:
        ctx["team"]        = best_name.upper()
        ctx["record"]      = f"{best_rec['w']}-{best_rec['l']}-{best_rec['k']}"
        ctx["rank_change"] = ("advancing in the standings" if best_rec["w"] > best_rec["l"]
                              else "holding steady" if best_rec["w"] == best_rec["l"]
                              else "sliding in the standings")
        p2.append(_pick_block(_BLK_TEAM_PERF, used, ctx))

    # Worst team (if genuinely different and had a losing record)
    if worst_name and worst_rec and worst_name != best_name and worst_rec["l"] > worst_rec["w"]:
        ctx["team"]   = worst_name.upper()
        ctx["record"] = f"{worst_rec['w']}-{worst_rec['l']}-{worst_rec['k']}"
        p2.append(_pick_block(_BLK_WORST_TEAM, used, ctx))

    # Second notable team from the middle of the pack
    if middle_teams:
        mt_name, mt_rec = random.choice(middle_teams)
        if mt_name not in _NPC_TEAM_NAMES:
            ctx["team"]   = mt_name.upper()
            ctx["record"] = f"{mt_rec['w']}-{mt_rec['l']}-{mt_rec['k']}"
            p2.append(_pick_block(_BLK_SECOND_TEAM, used, ctx))

    # Broader standings perspective
    p2.append(_pick_block(_BLK_STANDINGS_LOOK, used, ctx))

    if p2:
        paragraphs.append("  ".join(p2))

    # ==================================================================
    # PARAGRAPH 3 — WARRIOR HIGHLIGHTS: RISERS AND FALLERS
    # Cover top 2 winners and top 2 notable losers.
    # ==================================================================
    p3 = []

    # Top two winner spotlights
    for w_data in winners_list[:2]:
        ctx["warrior"]  = w_data["warrior"].upper()
        ctx["team"]     = w_data["team"].upper()
        ctx["opponent"] = w_data["opponent"].upper()
        ctx["points"]   = str(w_data["recs"])
        p3.append(_pick_block(_BLK_WARRIOR_RISER, used, ctx))

    # Up to two notable losers (skip killed warriors — they get their own paragraph)
    used_warriors = {w["warrior"] for w in winners_list[:2]}
    notable_losers = [x for x in losers_list
                      if not x["is_kill"] and x["recs"] > 10
                      and x["warrior"] not in used_warriors]
    for l_data in notable_losers[:2]:
        ctx["warrior"]  = l_data["warrior"].upper()
        ctx["team"]     = l_data["team"].upper()
        ctx["opponent"] = l_data["opponent"].upper()
        ctx["points"]   = str(l_data["recs"])
        p3.append(_pick_block(_BLK_WARRIOR_FALLER, used, ctx))

    # If we have a third notable winner and no good loser story, spotlight them
    if len(notable_losers) < 1 and len(winners_list) > 2:
        w2 = winners_list[2]
        ctx["warrior"]  = w2["warrior"].upper()
        ctx["team"]     = w2["team"].upper()
        ctx["opponent"] = w2["opponent"].upper()
        ctx["points"]   = str(w2["recs"])
        p3.append(_pick_block(_BLK_WARRIOR_HI, used, ctx))

    if p3:
        paragraphs.append("  ".join(p3))

    # ==================================================================
    # PARAGRAPH 4 — CHALLENGE DRAMA + STREAK WARRIORS
    # Notable challenge results and any warriors on extended winning runs.
    # ==================================================================
    p4 = []

    up_wins     = [c for c in challenge_results if c["challenger_won"]  and c["rec_diff"] < 0]
    down_losses = [c for c in challenge_results if not c["challenger_won"] and c["rec_diff"] > 0]

    # Up to two notable challenge results
    if up_wins:
        best = sorted(up_wins, key=lambda x: -x["abs_diff"])[0]
        ctx["warrior"]  = best["challenger"].upper()
        ctx["team"]     = best["challenger_team"].upper()
        ctx["opponent"] = best["challenged"].upper()
        ctx["points"]   = str(best["abs_diff"])
        p4.append(_pick_block(_BLK_CHALLENGE_WIN, used, ctx))

    if down_losses:
        worst = sorted(down_losses, key=lambda x: -x["abs_diff"])[0]
        ctx["warrior"]  = worst["challenger"].upper()
        ctx["team"]     = worst["challenger_team"].upper()
        ctx["opponent"] = worst["challenged"].upper()
        ctx["points"]   = str(worst["abs_diff"])
        p4.append(_pick_block(_BLK_CHALLENGE_LOSS, used, ctx))

    # Streak warrior spotlight
    if streak_warriors:
        sw = streak_warriors[0]
        ctx["warrior"] = sw["warrior"].upper()
        ctx["team"]    = sw["team"].upper()
        p4.append(_pick_block(_BLK_STREAK, used, ctx))

    if p4:
        paragraphs.append("  ".join(p4))

    # ==================================================================
    # PARAGRAPH 5 — KILL HIGHLIGHTS (only if kills occurred this turn)
    # Covers the kills from the killer's perspective; deaths get their own
    # paragraph later from the slain warrior's perspective.
    # ==================================================================
    if kill_highlights:
        p5 = []
        if kill_count >= 2:
            p5.append(_pick_block(_BLK_BLOODY_TURN, used, ctx))
        for kh in kill_highlights[:2]:
            ctx["warrior"]  = kh["warrior"].upper()
            ctx["team"]     = kh["team"].upper()
            ctx["opponent"] = kh["opponent"].upper()
            ctx["points"]   = str(kh["recs"])
            p5.append(_pick_block(_BLK_KILL_HIGHLIGHT, used, ctx))
        paragraphs.append("  ".join(p5))

    # ==================================================================
    # PARAGRAPH 6 — DIG DEEPER: META, AVOIDANCE, MOST CHALLENGED WARRIOR
    # Opens with a transition, weaves in meta observations and champion defense.
    # ==================================================================
    p6 = [_pick_block(_BLK_DIG_DEEPER, used, ctx)]

    if most_targeted_team:
        ctx["team"] = most_targeted_team.upper()
        p6.append(_pick_block(_BLK_META_TEAM, used, ctx))

    if most_challenged_warrior:
        ctx["warrior"] = most_challenged_warrior.upper()
        for bout in unique_bouts:
            if bout.opponent.name == most_challenged_warrior:
                ot = bout.opponent_team
                ctx["team"] = (ot.team_name if hasattr(ot, "team_name") else ot.get("team_name", "?")).upper()
                break
        p6.append(_pick_block(_BLK_META_WARRIOR, used, ctx))

    # Champion holds their title (if no title change in para 1)
    if champ and champ_src != "beat_champion":
        ctx["champion"]   = champ.upper()
        ctx["champ_team"] = champ_t.upper() if champ_t else "?"
        p6.append(_pick_block(_BLK_CHAMP_HOLDS, used, ctx))

    if len(p6) > 1:
        paragraphs.append("  ".join(p6))

    # ==================================================================
    # PARAGRAPH 7 — DEATHS + PHILOSOPHICAL ASIDE
    # Each death gets its own line; multiple deaths get a framing note first.
    # ==================================================================
    p7 = []

    if deaths:
        if len(deaths) >= 3:
            p7.append(_pick_block(_BLK_MULTIPLE_DEATHS, used, ctx))
        for d in deaths:
            ctx["warrior"] = d["name"].upper()
            ctx["team"]    = d.get("team", "?").upper()
            ctx["record"]  = f"{d.get('w', 0)}-{d.get('l', 0)}-{d.get('k', 0)}"
            p7.append(_pick_block(_BLK_DEATH, used, ctx))

    p7.append(_pick_block(_BLK_PHILOSOPHICAL, used, ctx))

    paragraphs.append("  ".join(p7))

    # ==================================================================
    # PARAGRAPH 8 — OUTRO / SIGN-OFF
    # ==================================================================
    paragraphs.append(_pick_block(_BLK_OUTRO, used, ctx))

    article = "\n\n".join(paragraphs)
    return "\n\nArena Happenings\n\n" + article





# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------

def generate_newsletter(turn_num, card, teams, deaths, champion_state,
                        voice="snide", processed_date=None, is_new_champion=False) -> str:
    sections = [_header(turn_num, processed_date)]
    sections.append(_team_standings(teams, turn_num))
    sections.append("\n\n" + _block_commentary(card, teams, deaths, turn_num, champion_state, is_new_champion))
    sections.append("\n\n" + _warrior_tiers(teams, champion_state))
    
    # Add monster kills section if there are any
    monster_kills = _monster_kills_section(card)
    if monster_kills:
        sections.append("\n\n" + monster_kills)
    
    sections.append("\n\n" + _fights_section(card))
    dead = _dead_section(deaths, turn_num)
    if dead: sections.append("\n\n" + dead)
    sections.append("\n\n" + _race_report(teams))
    return "\n".join(sections)

