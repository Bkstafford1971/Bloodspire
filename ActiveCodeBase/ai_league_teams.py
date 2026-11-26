# =============================================================================
# ai_league_teams.py - Procedural, self-learning AI league teams.
#
# This replaces the old hardcoded 16-manager roster. AI managers are now:
#   - procedurally named (ai_names.py) so they blend in with human players,
#   - built from a learning knowledge base (ai_brain.py) that adapts over time,
#   - driven each turn by human-like behavior (ai_manager.py): they field a full
#     living roster, replace the fallen, retire veterans, and issue challenges.
#
# The public contract the league server relies on is unchanged:
#   get_or_create_ai_teams() -> [team dict, ...]   (called at turn start)
#   evolve_ai_teams(teams, results) -> [team dict] (called after the turn)
#   load_ai_teams() / save_ai_teams()
#
# Manager IDs keep the internal "ai_" prefix so every existing is-this-AI check
# (mid.startswith("ai_")) keeps working; concealment from players comes from the
# procedural names + real team IDs, not from changing the id scheme.
# =============================================================================

import os
import json
import re
import random
from typing import List

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
AI_TEAMS_FILE = os.path.join(BASE_DIR, "saves", "league", "ai_teams.json")
CONFIG_FILE   = os.path.join(BASE_DIR, "saves", "league", "config.json")
STANDINGS_FILE = os.path.join(BASE_DIR, "saves", "league", "standings.json")

AI_MANAGER_COUNT     = 16      # default number of AI managers (config: ai_manager_count)
AI_MANAGER_MIN       = 1
AI_MANAGER_MAX       = 20
AI_TEAMS_PER_MANAGER = (2, 3)  # each AI manager runs this many teams (5 is the hard cap)
AI_MAX_TEAMS         = 5
ROSTER_SEED          = 8675309 # stable base seed -> reproducible roster/reruns


def get_ai_manager_count() -> int:
    """Configured number of AI managers, clamped to 1-20 (default 16)."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            n = int(json.load(f).get("ai_manager_count", AI_MANAGER_COUNT))
    except Exception:
        n = AI_MANAGER_COUNT
    return max(AI_MANAGER_MIN, min(AI_MANAGER_MAX, n))


def _slot_of(t: dict) -> int:
    """Which AI manager (0-based) a team belongs to. Teams from before multi-team
    support have no ai_slot, but their id is ai_NN so NN is the slot."""
    if isinstance(t.get("ai_slot"), int):
        return t["ai_slot"]
    m = re.match(r"ai_(\d+)", str(t.get("manager_id", "")))
    return int(m.group(1)) if m else 0


def _teams_for_slot(slot: int) -> int:
    lo, hi = AI_TEAMS_PER_MANAGER
    n = random.Random(f"{ROSTER_SEED}::teamcount::{slot}").randint(lo, hi)
    return max(1, min(AI_MAX_TEAMS, n))


# ---------------------------------------------------------------------------
# PERSISTENCE
# ---------------------------------------------------------------------------

def _ensure_dir():
    os.makedirs(os.path.dirname(AI_TEAMS_FILE), exist_ok=True)


def _load_all() -> List[dict]:
    """Every stored AI team, including managers beyond the configured count."""
    if not os.path.exists(AI_TEAMS_FILE):
        return []
    try:
        with open(AI_TEAMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    for t in data:
        if isinstance(t, dict) and not isinstance(t.get("ai_slot"), int):
            t["ai_slot"] = _slot_of(t)
    return data


def save_ai_teams(teams: List[dict], replace_all: bool = False):
    """Save `teams`. Stored teams of managers currently switched off (beyond the
    configured count) are kept untouched so raising the count later restores them."""
    _ensure_dir()
    out = list(teams)
    if not replace_all:
        have = {t.get("manager_id") for t in teams}
        out += [t for t in _load_all() if t.get("manager_id") not in have]
    with open(AI_TEAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)


def load_ai_teams() -> List[dict]:
    """The AI teams that are active (belong to one of the first N managers)."""
    count = get_ai_manager_count()
    return [t for t in _load_all() if _slot_of(t) < count]


def inactive_ai_ids() -> set:
    """Internal ids of stored AI teams that are switched off by the count setting."""
    count = get_ai_manager_count()
    return {t.get("manager_id") for t in _load_all() if _slot_of(t) >= count}


# ---------------------------------------------------------------------------
# CONTEXT HELPERS
# ---------------------------------------------------------------------------

def _current_turn() -> int:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return int(json.load(f).get("current_turn", 0))
    except Exception:
        return 0


def _opponent_pool(teams: List[dict]) -> List[str]:
    """Names an AI could plausibly challenge this turn: every manager in the
    standings plus the AI team names. take_turn() filters out each team's own
    names, and matchmaking enforces tier legality, so this can be broad."""
    pool = set()
    try:
        with open(STANDINGS_FILE, "r", encoding="utf-8") as f:
            st = json.load(f)
        for _mid, sd in (st.items() if isinstance(st, dict) else []):
            if isinstance(sd, dict) and sd.get("manager_name"):
                pool.add(sd["manager_name"])
    except Exception:
        pass
    for t in teams:
        if t.get("team_name"):
            pool.add(t["team_name"])
    return sorted(pool)


def _is_legacy(teams: List[dict]) -> bool:
    """True if the stored roster is the old hardcoded system (no motif marker,
    or the tell-tale 9000+ team IDs). Triggers a one-time regeneration."""
    for t in teams:
        if not isinstance(t, dict):
            return True
        if "motif" not in t:
            return True
        tid = t.get("team_id")
        if isinstance(tid, int) and tid >= 9000:
            return True
    return False


# ---------------------------------------------------------------------------
# ROSTER CREATION
# ---------------------------------------------------------------------------

def _extend_roster(teams: List[dict], count: int) -> List[dict]:
    """Create any missing AI managers (slots 0..count-1) and top each manager up to
    its 2-3 teams. Names are drawn through ONE shared registry so nothing collides
    with players, existing AI, or each other. Team IDs come from the real allocator
    so they look like players'. Extra teams reuse their manager's name."""
    import ai_manager
    from ai_brain import get_brain
    from ai_names import NameGenerator, make_registry
    from save import next_team_id

    brain = get_brain()

    extra = []
    for t in teams:
        extra += [t.get("manager_name"), t.get("team_name")]
        extra += [w.get("name") for w in (t.get("warriors") or []) if isinstance(w, dict)]
    reg = make_registry(used_names=[x for x in extra if x])
    ng = NameGenerator(seed=f"roster::{ROSTER_SEED}", shared=reg, load_existing=False)

    for slot in range(count):
        group = [t for t in teams if _slot_of(t) == slot]
        want = _teams_for_slot(slot)
        if len(group) >= want:
            continue
        mgr_name = group[0]["manager_name"] if group else ng.manager_name()
        used_ids = {t.get("manager_id") for t in group}
        for k in range(AI_MAX_TEAMS):
            if len(group) >= want:
                break
            mid = f"ai_{slot:02d}" if k == 0 else f"ai_{slot:02d}t{k}"
            if mid in used_ids:
                continue
            ident = {"manager_name": mgr_name, **ng.team_identity()}
            tid = next_team_id()
            rng = random.Random(f"{mid}::create::{ROSTER_SEED}")
            team = ai_manager.build_new_team(ident, mid, tid, brain=brain, rng=rng, namegen=ng)
            team["ai_slot"] = slot
            teams.append(team)
            group.append(team)
            used_ids.add(mid)
            print(f"  [AI] Created {mgr_name} / {ident['team_name']} "
                  f"(team {tid}, {ident['lens']}/{ident['motif']})")
    teams.sort(key=lambda t: (_slot_of(t), str(t.get("manager_id"))))
    return teams


# ---------------------------------------------------------------------------
# PUBLIC: turn-start
# ---------------------------------------------------------------------------

def get_or_create_ai_teams() -> List[dict]:
    """Return the AI roster ready for the upcoming turn: living 5-warrior teams
    with this turn's challenges set. Creates/migrates the roster as needed."""
    import ai_manager
    from ai_brain import get_brain
    from ai_names import NameGenerator, make_registry

    count = get_ai_manager_count()
    all_teams = _load_all()
    if all_teams and _is_legacy(all_teams):
        print("  [AI] Legacy AI roster detected - regenerating procedural learning roster.")
        all_teams = []
    before = len(all_teams)
    all_teams = _extend_roster(all_teams, count)
    if len(all_teams) != before or not os.path.exists(AI_TEAMS_FILE):
        save_ai_teams(all_teams, replace_all=True)

    teams = [t for t in all_teams if _slot_of(t) < count]   # active managers only

    turn = _current_turn()
    opponents = _opponent_pool(teams)
    brain = get_brain()
    reg = make_registry()
    ng = NameGenerator(seed=f"turn::{turn}", shared=reg, load_existing=False)

    for t in teams:
        ai_manager.retrofit_fatigue(t)   # one-time for older rosters; no-op afterwards
        rng = random.Random(f"{t.get('manager_id')}::turn::{turn}")
        # A manager never challenges their own other teams.
        sibling_teams = {str(s.get("team_name", "")).lower() for s in teams
                         if _slot_of(s) == _slot_of(t)}
        opp = [n for n in opponents if n.lower() not in sibling_teams]
        ai_manager.take_turn(t, brain=brain, rng=rng,
                             opponent_names=opp, turn=turn, namegen=ng)

    save_ai_teams(all_teams, replace_all=True)
    return teams


# ---------------------------------------------------------------------------
# PUBLIC: post-turn (records, learning, deaths, training)
# ---------------------------------------------------------------------------

def _train_survivors(team: dict):
    """Apply each surviving warrior's training queue (genuine skill progression),
    mirroring the old evolve behavior."""
    from warrior import Warrior
    out = []
    for wd in team.get("warriors", []):
        if not isinstance(wd, dict) or wd.get("is_dead") or wd.get("is_retired"):
            out.append(wd)
            continue
        try:
            w = Warrior.from_dict(wd)
            w.reset_training_session()
            for sk in (w.trains or [])[:3]:
                try:
                    w.train_skill(sk)
                except Exception:
                    pass
            w.recalculate_derived()
            d = w.to_dict()
            d["slot_index"] = wd.get("slot_index")
            out.append(d)
        except Exception:
            out.append(wd)
    team["warriors"] = out


def _append_turn_history(team: dict, res: dict, turn: int):
    bouts = res.get("bouts", []) or []
    if not bouts:
        return
    w_count = sum(1 for b in bouts if b.get("result", "") == "WIN")
    l_count = sum(1 for b in bouts if b.get("result", "") == "LOSS")
    k_count = sum(1 for b in bouts if b.get("opponent_slain"))
    # Drop any stale entry for this turn (e.g. from a rerun) then record.
    hist = team.setdefault("turn_history", [])
    hist[:] = [e for e in hist if e.get("turn") != turn]
    hist.append({"turn": turn, "w": w_count, "l": l_count, "k": k_count})


def evolve_ai_teams(teams: List[dict], turn_results: dict, turn_num: int = None) -> List[dict]:
    """After each turn:
      1. Feed results to the learning brain (archetype/strategy win rates, memory).
      2. Adopt the post-fight warrior snapshot (records, injuries, deaths).
      3. Train survivors.
      4. Retire veterans, archive the fallen, refill to a living 5.
      5. Update participation + turn history.
    """
    import ai_manager
    from ai_brain import get_brain
    from ai_names import NameGenerator, make_registry

    brain = get_brain()
    ai_manager.learn_from_results(turn_results, brain=brain)   # learn + persist brain

    reg = make_registry()
    ng = NameGenerator(seed=f"evolve::{ROSTER_SEED}", shared=reg, load_existing=False)

    for team in teams:
        mid = team.get("manager_id")
        res = turn_results.get(mid, {}) or {}
        # Prefer the authoritative turn number passed by the server. The in-memory
        # AI result dict does not reliably carry "turn", so relying on it left
        # last_turn_ran=0 and turn_history turn=0, which hid AI from the newsletter.
        turn = turn_num if turn_num is not None else (res.get("turn") or team.get("last_turn_ran", 0))

        # 2. adopt post-fight snapshot when present
        result_team = res.get("team") or {}
        if result_team.get("warriors"):
            team["warriors"] = result_team["warriors"]

        # 2b. learn from exhaustion collapses, then make sure the fatigue rows exist
        ai_manager.adapt_to_exhaustion(team, res.get("bouts"))
        ai_manager.retrofit_fatigue(team)

        # 2c. losing warriors get reworked from what the league-wide results show
        try:
            for msg in brain.adapt_team(team, random.Random(f"{mid}::adapt::{turn}"), turn):
                print(f"  [AI] adjusted {msg}")
        except Exception as _e:
            print(f"  [AI] adaptation skipped for {mid}: {_e}")

        # 3. train survivors
        _train_survivors(team)

        # 4. retire / archive / refill to a battle-ready living 5
        rng = random.Random(f"{mid}::evolve::{turn}")
        ai_manager.resolve_after_turn(team, brain=brain, rng=rng, namegen=ng, turn=turn)

        # 5. records
        team["last_turn_ran"] = turn
        _append_turn_history(team, res, turn)

    brain.save()   # persist build changes made by mid-career adaptation
    save_ai_teams(teams)
    return teams


# ---------------------------------------------------------------------------
# Manual smoke test:  python ai_league_teams.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # NOTE: this consumes real team IDs via next_team_id(); run against a test copy.
    teams = get_or_create_ai_teams()
    print(f"\nAI roster: {len(teams)} teams\n" + "=" * 60)
    for t in teams[:5]:
        print(f"{t['manager_name']:<20} | {t['team_name']:<24} "
              f"| team {t['team_id']} | {t.get('lens')}/{t.get('motif')}")
        for w in t["warriors"]:
            print(f"      {w['name']:<22} {w['race']:<10} HP={w['max_hp']}")
        if t.get("challenges"):
            print(f"      challenges: {t['challenges']}")
    print("..." if len(teams) > 5 else "")
