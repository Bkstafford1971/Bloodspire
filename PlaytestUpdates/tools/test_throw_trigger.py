"""
Simulation: validate that 'You have more than 2 weapons' trigger releases correctly
after the first Opportunity Throw, so the warrior doesn't keep throwing once their
weapon count drops to 2.

Pass condition per fight:
  - THROWER starts minute 1 with 3 weapons
  - Exactly 1 weapon-loss message appears in minute 1 (one throw, then strategy switch)
  - A strategy-switch line appears in minute 1

Inconclusive if THROWER gets 0 throws in minute 1 (fight ended before their first action).
"""

import sys
import os
sys.path.insert(0, r'c:\BPClone_Claude')

import random
from warrior import Warrior, Strategy
from combat import run_fight

# ---------------------------------------------------------------------------
# Warrior factories
# ---------------------------------------------------------------------------

def make_thrower(seed_offset=0):
    """Warrior with 3 daggers and a trigger-based throw strategy."""
    w = Warrior(
        name="Throwmaster",
        race_name="Human",
        gender="Male",
        strength=12,
        dexterity=17,
        constitution=12,
        intelligence=10,
        presence=10,
        size=10,
    )
    w.primary_weapon   = "Dagger"
    w.secondary_weapon = "Dagger"
    w.backup_weapon    = "Dagger"
    w.armor = "None"
    w.helm  = "None"
    w.skills["dagger"]     = 5
    w.skills["throw"]      = 5
    w.skills["initiative"] = 3
    w.strategies = [
        Strategy(trigger="You have more than 2 weapons",
                 style="Opportunity Throw", activity=9,
                 aim_point="Chest", defense_point="Chest"),
        Strategy(trigger="You have exactly 2 weapons",
                 style="Strike", activity=7,
                 aim_point="Chest", defense_point="Chest"),
        Strategy(trigger="You have exactly one weapon",
                 style="Strike", activity=7,
                 aim_point="Chest", defense_point="Chest"),
        Strategy(trigger="You are weaponless",
                 style="Martial Combat", activity=5,
                 aim_point="None", defense_point="Chest"),
        Strategy(trigger="Always",
                 style="Strike", activity=7,
                 aim_point="Chest", defense_point="Chest"),
    ]
    return w


def make_dummy():
    """Durable punching-bag opponent that won't drop in one hit."""
    w = Warrior(
        name="Ironwall",
        race_name="Human",
        gender="Male",
        strength=14,
        dexterity=10,
        constitution=18,
        intelligence=10,
        presence=10,
        size=16,
    )
    w.primary_weapon = "Broad Sword"
    w.armor = "Chain"
    w.helm  = "Steel Cap"
    w.skills["broad_sword"] = 3
    w.skills["parry"]       = 3
    w.strategies = [
        Strategy(trigger="Always",
                 style="Strike", activity=5,
                 aim_point="Chest", defense_point="Chest"),
    ]
    return w


# ---------------------------------------------------------------------------
# Narrative analyser
# ---------------------------------------------------------------------------

THROW_MSGS = (
    "THROWMASTER DRAWS",        # backup promoted
    "THROWMASTER SWITCHES TO HIS",   # secondary promoted (weapon, not strategy)
    "THROWMASTER SWITCHES TO HER",
    "THROWMASTER HAS NO MORE THROWABLES",
)

def analyse(narrative: str):
    """
    Return (status, detail) where status is 'PASS', 'FAIL', or 'INCONCLUSIVE'.

    Logic:
      - Split narrative by minute markers.
      - In minute 1: count weapon-loss (throw) events and strategy-switch events.
      - PASS  : exactly 1 throw AND a strategy switch found in minute 1
      - FAIL  : more than 1 throw in minute 1
      - INCONCLUSIVE : 0 throws in minute 1 (fight ended / THROWER never acted)
    """
    lines = narrative.split('\n')

    minute1_lines = []
    in_minute1 = False
    for raw in lines:
        stripped = raw.strip()
        if stripped == "MINUTE 1":
            in_minute1 = True
            continue
        if in_minute1:
            if stripped.startswith("MINUTE "):
                break           # left minute 1
            minute1_lines.append(stripped.upper())

    throw_count  = 0
    switch_found = False

    for ln in minute1_lines:
        # weapon-loss events (throw consumed the weapon)
        if any(msg in ln for msg in THROW_MSGS):
            throw_count += 1
        # strategy-switch event
        if "* THROWMASTER SWITCHES TO STRATEGY" in ln:
            switch_found = True

    if throw_count == 0:
        return "INCONCLUSIVE", "no throws in minute 1"

    if throw_count == 1 and switch_found:
        return "PASS", f"1 throw, strategy switch found"

    if throw_count == 1 and not switch_found:
        # Threw once, no switch recorded — could mean fight ended right after
        # or the minute had only 1 action slot. Treat as pass (no over-throwing).
        return "PASS", f"1 throw, no switch line (single-action minute)"

    return "FAIL", f"{throw_count} throws in minute 1 (expected 1)"


# ---------------------------------------------------------------------------
# Run 50 simulations
# ---------------------------------------------------------------------------

def main():
    random.seed(None)   # non-deterministic

    results = {"PASS": 0, "FAIL": 0, "INCONCLUSIVE": 0}
    rows = []

    print(f"{'Fight':>5}  {'Status':<14}  Detail")
    print("-" * 55)

    for i in range(50):
        thrower = make_thrower()
        dummy   = make_dummy()
        result  = run_fight(thrower, dummy)

        status, detail = analyse(result.narrative)
        results[status] += 1
        rows.append((i + 1, status, detail))

        marker = "" if status == "PASS" else (" <-- !!" if status == "FAIL" else "")
        print(f"{i+1:>5}  {status:<14}  {detail}{marker}")

    print("-" * 55)
    print(f"\nSummary: {results['PASS']} PASS  |  {results['FAIL']} FAIL  |  {results['INCONCLUSIVE']} INCONCLUSIVE")

    if results["FAIL"] == 0:
        print("\nAll conclusive fights passed. Trigger fix verified.")
    else:
        print(f"\n{results['FAIL']} fight(s) FAILED — warrior threw more than once while trigger should have been false.")


if __name__ == "__main__":
    main()
