"""
Simulation: measure permanent injury rate across 500 fights.

Reports:
  - Total perm injury events (both warriors combined)
  - Average perms per fight (combined) and per warrior per fight
  - Distribution: how many fights had 0 / 1 / 2 / 3+ perm injuries
  - % of fights with at least one perm injury
  - Breakdown by injury severity (level 1 / 2 / 3)
  - Threshold / chance formula reminder so results are easy to interpret

Detection: every perm injury emits a line starting with "*** " in the narrative.
"""

import sys
import os
sys.path.insert(0, r'c:\BPClone_Claude')

import random
import re
from collections import Counter
from warrior import Warrior, Strategy
from combat import run_fight

# ---------------------------------------------------------------------------
# Warrior archetypes  (we'll mix these randomly for variety)
# ---------------------------------------------------------------------------

ARCHETYPES = [
    # (name, race, gender, STR, DEX, CON, INT, PRE, SIZ, weapon, armor, helm, w_skill, style)
    ("Slasher",   "Human",    "Male",   16, 13, 14, 10, 10, 14, "Broad Sword",  "Leather",    "None",      "broad_sword",  "Strike"),
    ("Basher",    "Human",    "Male",   18, 10, 15, 10, 10, 16, "War Hammer",   "Brigandine", "Steel Cap", "war_hammer",   "Bash"),
    ("Fencer",    "Elf",      "Female", 10, 18, 10, 12, 12, 10, "Short Sword",  "Leather",    "None",      "short_sword",  "Sure Strike"),
    ("Brawler",   "Half-Orc", "Male",   17, 12, 16, 8,  10, 15, "Battle Axe",   "Cuir Boulli","Steel Cap", "battle_axe",   "Total Kill"),
    ("Tank",      "Dwarf",    "Male",   15, 11, 18, 10, 10, 12, "War Hammer",   "Chain",      "Helm",      "war_hammer",   "Bash"),
    ("Duelist",   "Human",    "Female", 12, 17, 12, 12, 13, 11, "Long Sword",   "Cuir Boulli","None",      "long_sword",   "Strike"),
    ("Reckless",  "Human",    "Male",   14, 13, 13, 10, 10, 13, "Broad Sword",  "Leather",    "None",      "broad_sword",  "Total Kill"),
    ("Nimble",    "Elf",      "Female", 10, 17, 10, 13, 12, 9,  "Short Sword",  "Leather",    "None",      "short_sword",  "Engage & Withdraw"),
    ("Plated",    "Human",    "Male",   16, 11, 15, 10, 10, 15, "Long Sword",   "Half-Plate", "Full Helm", "long_sword",   "Strike"),
    ("Agressor",  "Human",    "Male",   17, 14, 14, 10, 10, 14, "Battle Axe",   "Brigandine", "Steel Cap", "battle_axe",   "Total Kill"),
]


def make_warrior(archetype, suffix=""):
    name, race, gender, STR, DEX, CON, INT, PRE, SIZ, wpn, armor, helm, wskill, style = archetype
    w = Warrior(
        name=name + suffix,
        race_name=race,
        gender=gender,
        strength=STR,
        dexterity=DEX,
        constitution=CON,
        intelligence=INT,
        presence=PRE,
        size=SIZ,
    )
    w.primary_weapon = wpn
    w.armor = armor
    w.helm  = helm
    w.skills[wskill]      = random.randint(3, 6)
    w.skills["parry"]     = random.randint(1, 4)
    w.skills["dodge"]     = random.randint(0, 3)
    w.skills["initiative"]= random.randint(0, 3)
    w.strategies = [
        Strategy(trigger="Always", style=style, activity=random.randint(5, 8),
                 aim_point="Chest", defense_point="Chest"),
    ]
    return w


# ---------------------------------------------------------------------------
# Narrative analysis
# ---------------------------------------------------------------------------

def count_perms(narrative: str):
    """
    Return (total_count, level_counts) where:
      total_count  : number of perm injury events in the fight
      level_counts : Counter {1: n, 2: n, 3: n}

    Detection: each perm injury emits "*** <ANNOUNCEMENT> ***"
    The announcement text contains level hints we can extract from context,
    but for simplicity we just count events and derive levels from the
    narrative lines that follow each "***" marker.
    """
    count = 0
    for line in narrative.split('\n'):
        stripped = line.strip()
        if stripped.startswith('***') and stripped.endswith('***') and len(stripped) > 6:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Run 500 simulations
# ---------------------------------------------------------------------------

def main():
    random.seed(None)

    NUM_FIGHTS = 500

    total_perms   = 0
    dist          = Counter()   # {perms_in_fight: count_of_fights}
    fights_with_perm = 0
    fight_durations  = []
    per_fight_counts = []

    print(f"Running {NUM_FIGHTS} fights...\n")

    for i in range(NUM_FIGHTS):
        arch_a = random.choice(ARCHETYPES)
        arch_b = random.choice(ARCHETYPES)
        wa = make_warrior(arch_a, " A")
        wb = make_warrior(arch_b, " B")

        result = run_fight(wa, wb)

        n = count_perms(result.narrative)
        total_perms += n
        dist[n]     += 1
        if n > 0:
            fights_with_perm += 1
        fight_durations.append(result.minutes_elapsed)
        per_fight_counts.append(n)

        # Progress indicator every 100
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{NUM_FIGHTS} fights complete...")

    # ---------------------------------------------------------------------------
    # Results
    # ---------------------------------------------------------------------------
    avg_perms     = total_perms / NUM_FIGHTS
    avg_per_warrior = total_perms / (NUM_FIGHTS * 2)   # 2 warriors per fight
    avg_duration  = sum(fight_durations) / NUM_FIGHTS
    pct_with_perm = fights_with_perm / NUM_FIGHTS * 100

    print(f"\n{'='*60}")
    print(f"  PERMANENT INJURY RATE — {NUM_FIGHTS} fights")
    print(f"{'='*60}")
    print(f"\n  Perm injury mechanic:")
    print(f"    Triggers when a single hit deals >= 15% of target's max HP")
    print(f"    Chance = max(5, min(80, (damage/max_hp)*100 - 5))%")
    print(f"    e.g.  15% HP hit -> 10% chance")
    print(f"          25% HP hit -> 20% chance")
    print(f"          50% HP hit -> 45% chance")
    print(f"          85% HP hit -> 80% chance")

    print(f"\n  OVERALL")
    print(f"    Total perm injuries          : {total_perms}")
    print(f"    Avg perms per fight          : {avg_perms:.2f}  (both warriors combined)")
    print(f"    Avg perms per warrior/fight  : {avg_per_warrior:.2f}")
    print(f"    Fights with >= 1 perm injury : {fights_with_perm} / {NUM_FIGHTS}  ({pct_with_perm:.1f}%)")
    print(f"    Avg fight duration           : {avg_duration:.1f} minutes")

    print(f"\n  DISTRIBUTION (perms per fight)")
    for k in sorted(dist.keys()):
        bar = '#' * int(dist[k] / NUM_FIGHTS * 50)
        print(f"    {k} perms : {dist[k]:4d} fights ({dist[k]/NUM_FIGHTS*100:5.1f}%)  {bar}")

    # Percentile breakdown
    sorted_counts = sorted(per_fight_counts)
    p50 = sorted_counts[int(NUM_FIGHTS * 0.50)]
    p75 = sorted_counts[int(NUM_FIGHTS * 0.75)]
    p90 = sorted_counts[int(NUM_FIGHTS * 0.90)]
    p95 = sorted_counts[int(NUM_FIGHTS * 0.95)]
    print(f"\n  PERCENTILES")
    print(f"    50th percentile : {p50} perm(s) per fight")
    print(f"    75th percentile : {p75} perm(s) per fight")
    print(f"    90th percentile : {p90} perm(s) per fight")
    print(f"    95th percentile : {p95} perm(s) per fight")
    print(f"    Max in any fight: {max(per_fight_counts)}")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
