"""
test_tabaxi_frenzy.py
Runs a series of fights between a low-HP Tabaxi and a hard-hitting opponent.
The Tabaxi's small HP pool means they will hit the 30% frenzy threshold in
most fights, exercising the frenzy check (and the new resist/log code).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from warrior import Warrior, Strategy
from combat  import run_fight
from combat_debug_logger import CombatDebugLogger

# ── Tabaxi warrior — low CON/size to keep max_hp small ──────────────────────
def make_tabaxi():
    w = Warrior(
        name="Shadowclaw",
        race_name="Tabaxi",
        gender="Male",
        strength=12,
        dexterity=16,
        constitution=8,   # low — gives a small HP pool
        intelligence=10,
        presence=10,
        size=8,           # small frame, fewer HP
    )
    w.primary_weapon = "Short Sword"
    w.skills["short_sword"] = 4
    w.skills["dodge"]       = 3
    w.skills["initiative"]  = 2
    w.strategies = [
        Strategy(trigger="Always", style="Strike", activity=6,
                 aim_point="Chest", defense_point="Chest"),
    ]
    return w


# ── Tough Human opponent — high STR, heavy weapon ───────────────────────────
def make_opponent():
    w = Warrior(
        name="Ironmund",
        race_name="Human",
        gender="Male",
        strength=17,
        dexterity=12,
        constitution=14,
        intelligence=10,
        presence=10,
        size=16,
    )
    w.primary_weapon = "War Hammer"
    w.skills["war_hammer"] = 5
    w.skills["parry"]      = 2
    w.strategies = [
        Strategy(trigger="Always", style="Bash", activity=5,
                 aim_point="Chest", defense_point="Chest"),
    ]
    return w


# ── Run fights ───────────────────────────────────────────────────────────────
RUNS = 10
frenzy_triggered = 0
frenzy_checked   = 0
resist_seen      = 0

for i in range(1, RUNS + 1):
    tabaxi   = make_tabaxi()
    opponent = make_opponent()

    log = CombatDebugLogger()
    log.fight_id   = i
    log.turn_num   = 1
    log.debug_team = "Test"

    result = run_fight(
        tabaxi, opponent,
        team_a_name="Test Stable",
        team_b_name="Ironmund's Crew",
        manager_a_name="Tester",
        manager_b_name="AI",
        debug_logger=log,
    )

    winner = result.winner.name if result.winner else "draw"
    loser  = result.loser.name  if result.loser  else "?"
    died   = " (SLAIN)" if result.loser_died else ""

    # Count frenzy events from the narrative
    narrative = result.narrative or ""
    triggered_this = any(
        line in narrative for line in [
            "primal fury", "impossible speed", "Instinct takes over",
            "Survival instinct", "natural predator instincts",
            "ablaze with feline rage", "creature possessed", "cornered hunter",
        ]
    )
    resist_this = any(
        kw in narrative for kw in [
            "surge passes", "gutters out", "falter", "tremor of frenzy", "killing rush"
        ]
    )

    if triggered_this:
        frenzy_triggered += 1
    if resist_this:
        resist_seen += 1

    # Count debug-log check lines
    log_text = "\n".join(log._lines)
    checks_this = log_text.count("Tabaxi Frenzy Check")
    frenzy_checked += checks_this

    print(f"\n{'='*60}")
    print(f"Fight {i:2d}: {winner} defeats {loser}{died}  ({result.minutes_elapsed} min)")
    print(f"         Tabaxi max_hp={tabaxi.max_hp}  "
          f"frenzy checks in log={checks_this}  "
          f"triggered={'YES' if triggered_this else 'no'}  "
          f"resist_line={'YES' if resist_this else 'no'}")

    # Print a window of the narrative around any frenzy event
    lines = narrative.splitlines()
    frenzy_keywords = ["frenzy", "primal fury", "surge passes", "gutters out",
                       "falter", "tremor", "killing rush", "impossible speed",
                       "Instinct takes over", "Survival instinct",
                       "ablaze with feline rage", "creature possessed", "cornered hunter"]
    printed_idxs = set()
    for idx, line in enumerate(lines):
        if any(kw.lower() in line.lower() for kw in frenzy_keywords):
            for j in range(max(0, idx-2), min(len(lines), idx+3)):
                if j not in printed_idxs:
                    print(f"  | {lines[j]}")
                    printed_idxs.add(j)

print(f"\n{'='*60}")
print(f"SUMMARY over {RUNS} fights:")
print(f"  Frenzy threshold reached (checks logged) : {frenzy_checked} times")
print(f"  Frenzy triggered (narrative intro seen)  : {frenzy_triggered} fights")
print(f"  Frenzy resisted (resist line seen)       : {resist_seen} fights")
print(f"  Tabaxi max_hp (fixed): {make_tabaxi().max_hp}")
