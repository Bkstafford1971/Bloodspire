# =============================================================================
# ai_manager.py - Per-turn behavior for learning AI managers.
#
# This is the "acts like a human manager each turn" layer. It ties together the
# two lower modules:
#   - ai_names.py  : the manager/team/warrior names (voice that blends in)
#   - ai_brain.py  : the archetype/strategy knowledge + learning
#
# Responsibilities:
#   build_new_team()      - cold-start a full 5-warrior team from an identity.
#   take_turn()           - prep an existing team for the upcoming turn:
#                             * archive + replace dead/retired warriors (keep 5)
#                             * occasionally retire a long-serving veteran
#                             * issue challenges toward sensible opponents
#   learn_from_results()  - thin wrapper feeding a turn's results to the brain.
#
# Everything is deterministic given the caller's rng / seeds so a turn rerun
# reproduces the same roster and challenges. Naming uses a shared registry so
# no two warriors (across any team) ever collide -- pass one `namegen` built
# with a shared registry when preparing multiple managers in the same turn.
# =============================================================================

import random
from typing import List, Optional

from ai_brain import get_brain

RETIRE_MIN_FIGHTS = 50   # matches the game's retirement eligibility (warrior.py)
TEAM_SIZE = 5


# ---------------------------------------------------------------------------
# COLD START
# ---------------------------------------------------------------------------

def build_new_team(identity: dict, manager_id: str, team_id: int, *,
                   brain=None, rng: Optional[random.Random] = None,
                   namegen=None, tier: int = 2, arena: str = "normal") -> dict:
    """Create a brand-new AI team dict from a name identity.

    identity = {"manager_name","team_name","lens","motif"} (from ai_names).
    Returns a team dict shaped like the ones the league server injects.
    """
    brain = brain or get_brain()
    rng = rng or random.Random(f"{manager_id}::create")
    motif = identity.get("motif", "fantasy_compound")
    namegen = namegen or _default_namegen(f"{manager_id}::create::names")

    # Warrior names are stored ALL CAPS to match player-created warriors
    # (the server uppercases those at creation). Manager names keep their case.
    names = [n.upper() for n in namegen.warrior_names(motif, TEAM_SIZE)]
    archetypes = brain.suggest_team(manager_id, rng, size=TEAM_SIZE)

    warriors = []
    for i in range(TEAM_SIZE):
        gender = rng.choice(["Male", "Female"])
        w = brain.build_warrior(archetypes[i], names[i], gender, rng,
                                tier=tier, manager_id=manager_id, slot_index=i)
        warriors.append(w)

    return {
        "manager_id":   manager_id,
        "manager_name": identity["manager_name"],
        "team_name":    identity["team_name"].upper(),   # ALL CAPS like players' teams
        "team_id":      team_id,
        "warriors":     warriors,
        "lens":         identity.get("lens"),
        "motif":        motif,
        "tier":         tier,
        "auto_upload_enabled": True,
        "challenges":   {},
        "turn_history": [],
        "last_turn_ran": 0,
        "current_arena": arena,
    }


# ---------------------------------------------------------------------------
# PER-TURN PREP
# ---------------------------------------------------------------------------

def take_turn(team: dict, *, brain=None, rng: Optional[random.Random] = None,
              opponent_names: Optional[List[str]] = None, turn: int = 0,
              namegen=None) -> dict:
    """PRE-TURN prep of `team` (mutated in place and returned): make sure the
    roster is a full living 5 (safety), then issue challenges for this turn."""
    brain = brain or get_brain()
    mid = team.get("manager_id")
    rng = rng or random.Random(f"{mid}::turn::{turn}")
    pers = brain.get_personality(mid)
    namegen = namegen or _default_namegen(f"{mid}::turn::{turn}::names")

    _refill_roster(team, brain, rng, namegen, mid, turn)
    _set_challenges(team, brain, rng, pers, opponent_names, mid)

    team["auto_upload_enabled"] = True
    return team


def resolve_after_turn(team: dict, *, brain=None, rng: Optional[random.Random] = None,
                       namegen=None, turn: int = 0) -> dict:
    """POST-TURN cleanup: occasionally retire a veteran, then archive the fallen
    and refill their slots so the stored roster is always a battle-ready 5."""
    brain = brain or get_brain()
    mid = team.get("manager_id")
    rng = rng or random.Random(f"{mid}::resolve::{turn}")
    pers = brain.get_personality(mid)
    namegen = namegen or _default_namegen(f"{mid}::resolve::{turn}::names")

    _maybe_retire(team, pers, rng)
    _refill_roster(team, brain, rng, namegen, mid, turn)
    return team


def learn_from_results(ai_results: dict, brain=None):
    """Feed a turn's AI results into the learning engine (updates + persists)."""
    (brain or get_brain()).record_results(ai_results)


def retrofit_fatigue(team: dict) -> int:
    """Make sure every living warrior's strategy table has the fatigue rows
    (very-tired row first, cheap tired row). Idempotent. Returns warriors changed."""
    from ai_brain import ensure_fatigue_rows
    n = 0
    for w in team.get("warriors") or []:
        if _is_gone(w) or not w.get("strategies"):
            continue
        if ensure_fatigue_rows(w["strategies"]):
            n += 1
    return n


def adapt_to_exhaustion(team: dict, bouts: list) -> int:
    """A warrior that collapsed from exhaustion learns from it: add the
    very-tired conserve row, else drop the default activity one notch.
    Returns warriors adjusted."""
    from ai_brain import adapt_after_exhaustion
    collapsed = {b.get("warrior_name") for b in (bouts or [])
                 if isinstance(b, dict) and b.get("exhaustion_collapse")}
    n = 0
    for w in team.get("warriors") or []:
        if _is_gone(w) or w.get("name") not in collapsed or not w.get("strategies"):
            continue
        what = adapt_after_exhaustion(w["strategies"])
        if what:
            n += 1
            print(f"  [AI] {w.get('name')} collapsed from exhaustion: {what}")
    return n


# ---------------------------------------------------------------------------
# INTERNALS
# ---------------------------------------------------------------------------

def _default_namegen(seed):
    # load_existing=True keeps the generator safe on its own (won't reuse any
    # existing player/AI name). For multi-manager turns, callers should build one
    # shared-registry generator and pass it in so warriors are unique across teams.
    from ai_names import NameGenerator
    return NameGenerator(seed=seed, load_existing=True)


def _is_gone(w: dict) -> bool:
    return (not isinstance(w, dict)) or w.get("is_dead") or w.get("is_retired")


def _maybe_retire(team: dict, pers: dict, rng: random.Random):
    """Occasionally retire a veteran (>=50 fights). Cautious managers retire more
    readily; aggressive ones ride their veterans harder. Human-like churn."""
    chance = 0.12 + 0.20 * (1.0 - pers["aggression"])
    for w in team.get("warriors", []):
        if not isinstance(w, dict) or _is_gone(w):
            continue
        if w.get("total_fights", 0) >= RETIRE_MIN_FIGHTS and rng.random() < chance:
            w["want_retire"] = True


def _refill_roster(team: dict, brain, rng: random.Random, namegen,
                   mid: str, turn: int):
    """Archive dead/retired warriors and rebuild those slots so the team always
    fields a full, living roster of TEAM_SIZE."""
    motif = team.get("motif") or "fantasy_compound"
    tier = team.get("tier", 2)
    warriors = team.get("warriors", []) or []

    # map surviving warriors by slot; archive the fallen.
    survivors = {}
    archive = team.setdefault("archived_warriors", [])
    for w in warriors:
        if not isinstance(w, dict):
            continue
        _in_spire = (w.get("current_arena") or "normal") in ("elite", "veteran")
        if w.get("is_dead") or w.get("is_retired") or _in_spire:
            # A warrior promoted/transcended to the Elite/Soul Spire has left the
            # normal arena: archive him (the spire keeps its own copy) and refill
            # the slot, otherwise matchmaking skips the team for lacking 5 fighters.
            # preserve the cumulative record like real teams do
            w.setdefault("archived_killed_by", w.get("killed_by", "Unknown"))
            w.setdefault("archived_turns", w.get("turns_active", 0))
            archive.append(w)
            continue
        slot = w.get("slot_index")
        if slot is None:
            continue
        survivors[int(slot)] = w

    # Warriors in the Elite/Soul Spire are still alive in the league: never hand
    # their names to a newcomer (matching and challenges are name-based).
    for _a in archive:
        if isinstance(_a, dict) and _a.get("name") and (_a.get("current_arena") or "normal") in ("elite", "veteran"):
            namegen.reserve(_a["name"])

    new_roster = []
    for slot in range(TEAM_SIZE):
        if slot in survivors:
            survivors[slot]["slot_index"] = slot
            new_roster.append(survivors[slot])
            continue
        # build a replacement for the empty slot (ALL CAPS like players' warriors)
        name = namegen.warrior_names(motif, 1)[0].upper()
        arc = brain.choose_archetype(mid, rng)
        gender = rng.choice(["Male", "Female"])
        w = brain.build_warrior(arc, name, gender, rng, tier=tier,
                                manager_id=mid, slot_index=slot)
        new_roster.append(w)

    team["warriors"] = new_roster


def _set_challenges(team: dict, brain, rng: random.Random, pers: dict,
                    opponent_names: Optional[List[str]], mid: str):
    """Populate team['challenges'] = {slot: [target_name]} toward sensible foes.
    Aggressive managers challenge more and pick tougher targets; cautious ones
    challenge winnable foes. Matchmaking enforces tier/legality, so an
    over-ambitious challenge simply won't resolve -- it's never unsafe."""
    team["challenges"] = {}
    if not opponent_names:
        return

    own = {str(team.get("team_name", "")).lower(),
           str(team.get("manager_name", "")).lower()}
    own |= {str(w.get("name", "")).lower() for w in team.get("warriors", [])}
    cands = sorted({n for n in opponent_names if n and n.lower() not in own})
    if not cands:
        return

    # decide how many challenges to issue this turn (aggression-scaled)
    if rng.random() >= (0.25 + 0.55 * pers["aggression"]):
        return
    max_ch = 1 + (1 if pers["aggression"] > 0.6 and rng.random() < 0.5 else 0)

    def target_score(name: str) -> float:
        edge = brain.rate_opponent(mid, name)   # >0: we tend to beat them
        # aggressive managers chase the ones who beat them (bravado); cautious
        # managers pick foes they can handle.
        base = (-edge) if pers["aggression"] > 0.6 else edge
        return base + rng.uniform(-0.3, 0.3)

    ranked = sorted(cands, key=target_score, reverse=True)
    live = [w for w in team.get("warriors", []) if not _is_gone(w)]
    rng.shuffle(live)

    for i in range(min(max_ch, len(ranked), len(live))):
        slot = str(live[i].get("slot_index", i))
        team["challenges"].setdefault(slot, []).append(ranked[i])


# ---------------------------------------------------------------------------
# Manual smoke test:  python ai_manager.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    from ai_brain import AIBrain
    from ai_names import NameGenerator, make_registry, generate_roster

    brain = AIBrain(path=os.path.join("saves", "league", "_ai_mgr_test.json"))
    reg = make_registry()
    ident = generate_roster(1, seed=555)[0]
    mid, tid = "ai_00", 41

    namegen = NameGenerator(seed="roster::names", shared=reg, load_existing=False)
    team = build_new_team(ident, mid, tid, brain=brain,
                          rng=random.Random("create"), namegen=namegen)

    print(f"Manager: {team['manager_name']}   Team: {team['team_name']}  "
          f"[{team['lens']}/{team['motif']}]")
    print("Initial roster:")
    for w in team["warriors"]:
        print(f"  slot {w['slot_index']}: {w['name']:<22} {w['race']:<10} "
              f"HP={w['max_hp']:<4} {w['primary_weapon']}")

    # simulate: slot 2 died and slot 0 is a 50-fight veteran
    team["warriors"][2]["is_dead"] = True
    team["warriors"][0]["total_fights"] = 62

    opponents = ["People Who Stank", "Go On, Git!", "Crimson Legion", "The Wet Bandits"]
    take_turn(team, brain=brain, rng=random.Random("t42"),
              opponent_names=opponents, turn=42, namegen=namegen)

    print("\nAfter take_turn (dead slot 2 replaced, veteran maybe retiring):")
    for w in team["warriors"]:
        flags = []
        if w.get("want_retire"): flags.append("WANT_RETIRE")
        print(f"  slot {w['slot_index']}: {w['name']:<22} {w['race']:<10} "
              f"HP={w['max_hp']:<4} {' '.join(flags)}")
    print("archived:", [a['name'] for a in team.get('archived_warriors', [])])
    print("challenges issued:", team["challenges"])
    print("roster size:", len(team["warriors"]))
