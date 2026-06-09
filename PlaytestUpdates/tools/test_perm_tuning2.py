"""
Second pass: find config that lands ~20-25% of fights with a perm injury.
"""

import sys
sys.path.insert(0, r'c:\BPClone_Claude')

import random
from collections import Counter
import combat as _combat_module
from warrior import Warrior, Strategy
from combat import _BODY_LOCATION_POOL

_ORIG_CHECK = _combat_module._check_perm_injury


def make_patched_check(threshold_pct, subtract, max_chance):
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
    w.primary_weapon = wpn; w.armor = armor; w.helm = helm
    w.skills[wskill]       = random.randint(3, 6)
    w.skills["parry"]      = random.randint(1, 4)
    w.skills["dodge"]      = random.randint(0, 3)
    w.skills["initiative"] = random.randint(0, 3)
    w.strategies = [Strategy(trigger="Always", style=style, activity=random.randint(5, 8),
                             aim_point="Chest", defense_point="Chest")]
    return w


def count_perms(narrative):
    return sum(1 for ln in narrative.split('\n')
               if ln.strip().startswith('***') and ln.strip().endswith('***') and len(ln.strip()) > 6)


def run_batch(threshold_pct, subtract, max_chance, n=500, seed=99):
    random.seed(seed)
    _combat_module._check_perm_injury = make_patched_check(threshold_pct, subtract, max_chance)
    from combat import run_fight
    total = 0; with_perm = 0; dist = Counter()
    for _ in range(n):
        wa = make_warrior(random.choice(ARCHETYPES))
        wb = make_warrior(random.choice(ARCHETYPES))
        c = count_perms(run_fight(wa, wb).narrative)
        total += c; dist[c] += 1
        if c > 0: with_perm += 1
    _combat_module._check_perm_injury = _ORIG_CHECK
    return {"avg": total/n, "pct_any": with_perm/n*100, "dist": dist}


CONFIGS = [
    # label,                              threshold,  subtract,  max_chance
    ("D (prev best): 25% / sub 20",        0.25,       20,        65),
    ("Opt F: thresh 30% / sub 25",         0.30,       25,        60),
    ("Opt G: thresh 30% / sub 30",         0.30,       30,        60),
    ("Opt H: thresh 35% / sub 25",         0.35,       25,        60),
    ("Opt I: thresh 35% / sub 30",         0.35,       30,        55),
    ("Opt J: thresh 40% / sub 30",         0.40,       30,        55),
]


def main():
    N = 500
    print(f"Targeting ~20-25% of fights with a perm injury\n")
    print(f"{'Config':<38}  {'Avg/fight':>9}  {'Avg/warrior':>11}  {'%>=1 perm':>10}  {'0':>4}{'1':>4}{'2':>4}{'3+':>4}")
    print("-" * 90)
    for label, thresh, sub, mx in CONFIGS:
        s = run_batch(thresh, sub, mx, N)
        d = s["dist"]
        print(f"{label:<38}  {s['avg']:>9.2f}  {s['avg']/2:>11.2f}  "
              f"{s['pct_any']:>9.1f}%  "
              f"{d[0]:>4}{d[1]:>4}{d[2]:>4}{sum(v for k,v in d.items() if k>=3):>4}")
    print()
    print("Target zone: 20-25% perm rate, avg ~0.22-0.28 per fight")


if __name__ == "__main__":
    main()
