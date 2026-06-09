"""
Tune permanent injury rate by testing several (threshold, subtract) combinations.
Current values: threshold=0.15, subtract=5
Option 4: raise threshold AND lower base chance.

For each config, runs 500 fights and reports the key numbers.
"""

import sys
import os
sys.path.insert(0, r'c:\BPClone_Claude')

import random
from collections import Counter
from warrior import Warrior, Strategy
from combat import _check_perm_injury   # we'll monkey-patch this

# ---------------------------------------------------------------------------
# Same archetypes as the baseline sim
# ---------------------------------------------------------------------------

ARCHETYPES = [
    ("Slasher",  "Human",    "Male",   16, 13, 14, 10, 10, 14, "Broad Sword",  "Leather",    "None",      "broad_sword",  "Strike"),
    ("Basher",   "Human",    "Male",   18, 10, 15, 10, 10, 16, "War Hammer",   "Brigandine", "Steel Cap", "war_hammer",   "Bash"),
    ("Fencer",   "Elf",      "Female", 10, 18, 10, 12, 12, 10, "Short Sword",  "Leather",    "None",      "short_sword",  "Sure Strike"),
    ("Brawler",  "Half-Orc", "Male",   17, 12, 16, 8,  10, 15, "Battle Axe",   "Cuir Boulli","Steel Cap", "battle_axe",   "Total Kill"),
    ("Tank",     "Dwarf",    "Male",   15, 11, 18, 10, 10, 12, "War Hammer",   "Chain",      "Helm",      "war_hammer",   "Bash"),
    ("Duelist",  "Human",    "Female", 12, 17, 12, 12, 13, 11, "Long Sword",   "Cuir Boulli","None",      "long_sword",   "Strike"),
    ("Reckless", "Human",    "Male",   14, 13, 13, 10, 10, 13, "Broad Sword",  "Leather",    "None",      "broad_sword",  "Total Kill"),
    ("Nimble",   "Elf",      "Female", 10, 17, 10, 13, 12, 9,  "Short Sword",  "Leather",    "None",      "short_sword",  "Engage & Withdraw"),
    ("Plated",   "Human",    "Male",   16, 11, 15, 10, 10, 15, "Long Sword",   "Half-Plate", "Full Helm", "long_sword",   "Strike"),
    ("Agressor", "Human",    "Male",   17, 14, 14, 10, 10, 14, "Battle Axe",   "Brigandine", "Steel Cap", "battle_axe",   "Total Kill"),
]


def make_warrior(archetype):
    name, race, gender, STR, DEX, CON, INT, PRE, SIZ, wpn, armor, helm, wskill, style = archetype
    w = Warrior(name=name, race_name=race, gender=gender,
                strength=STR, dexterity=DEX, constitution=CON,
                intelligence=INT, presence=PRE, size=SIZ)
    w.primary_weapon = wpn
    w.armor = armor
    w.helm  = helm
    w.skills[wskill]       = random.randint(3, 6)
    w.skills["parry"]      = random.randint(1, 4)
    w.skills["dodge"]      = random.randint(0, 3)
    w.skills["initiative"] = random.randint(0, 3)
    w.strategies = [
        Strategy(trigger="Always", style=style, activity=random.randint(5, 8),
                 aim_point="Chest", defense_point="Chest"),
    ]
    return w


def count_perms(narrative):
    count = 0
    for line in narrative.split('\n'):
        s = line.strip()
        if s.startswith('***') and s.endswith('***') and len(s) > 6:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Monkey-patchable perm check
# ---------------------------------------------------------------------------

import combat as _combat_module
import warrior as _warrior_module

_ORIG_CHECK = _combat_module._check_perm_injury   # save original


def make_patched_check(threshold_pct, subtract, max_chance=70):
    """Return a replacement _check_perm_injury using the given tuning values."""
    from combat import _BODY_LOCATION_POOL
    import random as _r

    def _patched(warrior, damage, aim_point):
        if damage < warrior.max_hp * threshold_pct:
            return None
        chance = max(5, min(max_chance, int((damage / warrior.max_hp) * 100) - subtract))
        if warrior.race.modifiers.fewer_perms:
            chance = int(chance * 0.85)
        if _r.randint(1, 100) > chance:
            return None
        if aim_point and aim_point != "None":
            loc_map = {
                "Head": "head", "Chest": "chest", "Abdomen": "abdomen",
                "Primary Arm": "primary_arm", "Secondary Arm": "secondary_arm",
                "Primary Leg": "primary_leg", "Secondary Leg": "secondary_leg",
            }
            location = loc_map.get(aim_point, _r.choice(_BODY_LOCATION_POOL))
        else:
            location = _r.choice(_BODY_LOCATION_POOL)
        pct    = damage / warrior.max_hp
        levels = 3 if pct > 0.50 else (2 if pct > 0.35 else 1)
        return location, levels

    return _patched


def run_batch(threshold_pct, subtract, max_chance=70, n=500, seed=42):
    """Patch the perm check, run n fights, return stats dict."""
    random.seed(seed)
    _combat_module._check_perm_injury = make_patched_check(threshold_pct, subtract, max_chance)

    from combat import run_fight

    total = 0
    with_perm = 0
    dist = Counter()

    for _ in range(n):
        wa = make_warrior(random.choice(ARCHETYPES))
        wb = make_warrior(random.choice(ARCHETYPES))
        result = run_fight(wa, wb)
        c = count_perms(result.narrative)
        total   += c
        dist[c] += 1
        if c > 0:
            with_perm += 1

    # restore
    _combat_module._check_perm_injury = _ORIG_CHECK

    return {
        "total":      total,
        "avg":        total / n,
        "pct_any":    with_perm / n * 100,
        "dist":       dist,
        "n":          n,
    }


# ---------------------------------------------------------------------------
# Configs to test  (threshold_pct, subtract, max_chance)
# Label describes the change from baseline
# ---------------------------------------------------------------------------

CONFIGS = [
    # label,                           threshold,  subtract,  max_chance
    ("BASELINE  (current)",             0.15,       5,         80),
    ("Opt A: thresh 20% / sub 10",      0.20,      10,         75),
    ("Opt B: thresh 20% / sub 15",      0.20,      15,         70),
    ("Opt C: thresh 25% / sub 15",      0.25,      15,         70),
    ("Opt D: thresh 25% / sub 20",      0.25,      20,         65),
    ("Opt E: thresh 30% / sub 20",      0.30,      20,         65),
]


def main():
    N = 500
    print(f"Testing {len(CONFIGS)} configurations, {N} fights each (same seed per config)\n")
    print(f"{'Config':<38}  {'Avg/fight':>9}  {'Avg/warrior':>11}  {'%>=1 perm':>10}  {'0':>4}{'1':>4}{'2':>4}{'3+':>4}")
    print("-" * 90)

    for label, thresh, sub, mx in CONFIGS:
        stats = run_batch(thresh, sub, mx, n=N, seed=99)
        d = stats["dist"]
        three_plus = sum(v for k, v in d.items() if k >= 3)
        print(f"{label:<38}  {stats['avg']:>9.2f}  {stats['avg']/2:>11.2f}  "
              f"{stats['pct_any']:>9.1f}%  "
              f"{d[0]:>4}{d[1]:>4}{d[2]:>4}{three_plus:>4}")

    print()
    print("Recommended target: ~25-35% of fights with a perm, ~0.30-0.45 avg per fight")


if __name__ == "__main__":
    main()
