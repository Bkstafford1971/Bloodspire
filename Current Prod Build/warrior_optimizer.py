#!/usr/bin/env python
r"""
warrior_optimizer.py — Bloodspire Replacement Warrior Optimizer

A standalone Tkinter tool to help managers create optimized replacement warriors
from rollup stats (base 6 attributes). Two modes:
  - Auto: Searches all races + point allocations, simulates top 5, returns best.
  - Manual: User allocates points; tool finds best race + gear + strategies (top 3).

Run with: python c:\BPClone_Claude\warrior_optimizer.py
"""

from __future__ import annotations

import sys
import copy
import math
from os.path import dirname, abspath
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

# Add project root to import path for headless execution
sys.path.insert(0, dirname(abspath(__file__)))

import tkinter as tk
from tkinter import ttk
import threading

# ── Project imports (read-only) ────────────────────────────────────────────

from races import get_race, RACES
from warrior import Warrior, Strategy, ATTRIBUTES, ROLLUP_POINTS, ROLLUP_MAX_PER_STAT
from weapons import get_weapon, WEAPONS, strength_penalty
from armor import ARMOR_PIECES, ARMOR_STR_CAPACITY, armor_penalty_factor
from combat import run_fight

# ── Section 1: Constants ───────────────────────────────────────────────────

PLAYABLE_RACES = [
    "Half-Orc", "Dwarf", "Elf", "Goblin", "Gnome",
    "Halfling", "Lizardfolk", "Tabaxi", "Half-Elf", "Human"
]

ATTRS = ["STR", "DEX", "CON", "INT", "PRE", "SIZ"]

ARCHETYPE_CONFIGS = {
    "HeavyTank": {"race": "Dwarf", "stats": {"STR": 18, "DEX": 9, "CON": 17, "INT": 10, "PRE": 9, "SIZ": 11},
                  "weapon_names": ["Warhammer"], "armor_name": "Chain", "strat_trigger": "Counterstrike", "strat_act": 4},
    "GlassCannon": {"race": "Elf", "stats": {"STR": 10, "DEX": 18, "CON": 10, "INT": 14, "PRE": 13, "SIZ": 8},
                    "weapon_names": ["Rapier"], "armor_name": "Leather", "strat_trigger": "Wall of Steel", "strat_act": 6},
    "SpeedFighter": {"race": "Halfling", "stats": {"STR": 10, "DEX": 19, "CON": 12, "INT": 11, "PRE": 10, "SIZ": 6},
                     "weapon_names": ["Shortsword"], "armor_name": "Cuir Boulli", "strat_trigger": "Lunge", "strat_act": 6},
    "Bruiser": {"race": "Half-Orc", "stats": {"STR": 18, "DEX": 11, "CON": 16, "INT": 8, "PRE": 9, "SIZ": 14},
                "weapon_names": ["Warhammer"], "armor_name": "Scale", "strat_trigger": "Bash", "strat_act": 6},
    "DefWall": {"race": "Gnome", "stats": {"STR": 11, "DEX": 13, "CON": 15, "INT": 13, "PRE": 12, "SIZ": 7},
                "weapon_names": ["Shortsword"], "armor_name": "Scale", "strat_trigger": "Parry", "strat_act": 3},
    "Evader": {"race": "Halfling", "stats": {"STR": 9, "DEX": 18, "CON": 13, "INT": 12, "PRE": 11, "SIZ": 6},
               "weapon_names": ["Shortsword"], "armor_name": "Leather", "strat_trigger": "Engage & Withdraw", "strat_act": 4},
    "Counterstrike": {"race": "Gnome", "stats": {"STR": 12, "DEX": 15, "CON": 14, "INT": 13, "PRE": 11, "SIZ": 7},
                      "weapon_names": ["Shortsword"], "armor_name": "Brigandine", "strat_trigger": "Counterstrike", "strat_act": 4},
    "AverageJoe": {"race": "Human", "stats": {"STR": 12, "DEX": 12, "CON": 12, "INT": 12, "PRE": 12, "SIZ": 12},
                   "weapon_names": ["Shortsword"], "armor_name": "Brigandine", "strat_trigger": "Strike", "strat_act": 5},
}

RACE_STRAT_TEMPLATES = {
    "Half-Orc": [
        ("You have taken medium damage", "Bash", 6),
        ("Your foe has taken heavy damage", "Bash", 7),
        ("Your foe is on the ground", "Total Kill", 7),
    ],
    "Dwarf": [
        ("You have taken medium damage", "Counterstrike", 4),
        ("Your foe has taken heavy damage", "Parry", 3),
        ("You are on the ground", "Defend", 5),
    ],
    "Elf": [
        ("You have taken slight damage", "Engage & Withdraw", 4),
        ("Your foe has taken medium damage", "Lunge", 6),
        ("You are slightly tired", "Slash", 5),
    ],
    "Goblin": [
        ("You have taken medium damage", "Lunge", 6),
        ("You have at least one throwable weapon", "Opportunity Throw", 6),
        ("Your foe is on the ground", "Lunge", 7),
    ],
    "Gnome": [
        ("You have taken slight damage", "Parry", 4),
        ("Your foe is on the ground", "Counterstrike", 5),
        ("You are weaponless", "Defend", 3),
    ],
    "Halfling": [
        ("You have taken slight damage", "Engage & Withdraw", 4),
        ("Your foe has taken medium damage", "Lunge", 7),
        ("You have exactly one weapon", "Decoy", 5),
    ],
    "Lizardfolk": [
        ("You have taken medium damage", "Martial Combat", 6),
        ("Your foe has taken heavy damage", "Counterstrike", 5),
        ("You are on the ground", "Defend", 4),
    ],
    "Tabaxi": [
        ("You have taken slight damage", "Lunge", 7),
        ("Your foe has taken medium damage", "Lunge", 7),
        ("Minute 5", "Bash", 6),
    ],
    "Half-Elf": [
        ("You have taken medium damage", "Slash", 6),
        ("Your foe has taken medium damage", "Lunge", 6),
        ("You are slightly tired", "Strike", 5),
    ],
    "Human": [
        ("You have taken medium damage", "Strike", 5),
        ("Your foe has taken heavy damage", "Bash", 6),
        ("Your foe is on the ground", "Total Kill", 7),
    ],
}

RACE_DEFAULT_STYLES = {
    "Half-Orc": ("Bash", 7),
    "Dwarf": ("Counterstrike", 4),
    "Elf": ("Engage & Withdraw", 4),
    "Goblin": ("Lunge", 5),
    "Gnome": ("Counterstrike", 4),
    "Halfling": ("Engage & Withdraw", 4),
    "Lizardfolk": ("Martial Combat", 5),
    "Tabaxi": ("Lunge", 5),
    "Half-Elf": ("Slash", 6),
    "Human": ("Strike", 5),
}

# ── Section 2: Data classes ────────────────────────────────────────────────

@dataclass
class OptResult:
    race_name: str
    stats: Dict[str, int]
    primary_weapon: str
    secondary_weapon: str
    backup_weapon: Optional[str]
    armor_name: str
    helm_name: str
    strategies: List[Tuple[str, str, int]]
    win_rate: float
    score: float


# ── Section 3: Heuristic Scorer ────────────────────────────────────────────

def get_synergy_bonus(race_name: str, stats: Dict[str, int]) -> float:
    """Calculate synergy bonus (5% weight) based on race-stat alignment."""
    bonus = 0.0
    race_obj = get_race(race_name)

    if not race_obj:
        return bonus

    m = race_obj.modifiers
    if m.dual_weapon_bonus and stats["DEX"] >= 16:
        bonus += 5.0
    if m.dodge_bonus > 0 and stats["DEX"] >= 14:
        bonus += 3.0
    if m.damage_bonus > 0 and stats["STR"] >= 16:
        bonus += 3.0

    return min(bonus, 10.0)


def score_build(race_name: str, stats: Dict[str, int]) -> float:
    """Score a build using heuristic weights. Returns 0–100."""
    race_obj = get_race(race_name)
    if not race_obj:
        return 0.0

    m = race_obj.modifiers

    # HP score (40%)
    hp_base = math.ceil(stats["SIZ"] + stats["STR"] + stats["CON"] * 2.5)
    hp_score = min((hp_base + m.hp_bonus) / 100.0, 1.0) * 40.0

    # Damage score (25%)
    eff_str = stats["STR"] - m.strength_penalty
    damage_score = min((eff_str + m.damage_bonus) / 20.0, 1.0) * 25.0

    # Defense score (20%)
    eff_dex = stats["DEX"]
    armor_penalty = 1.0
    defense_score = min((eff_dex + m.dodge_bonus - armor_penalty) / 20.0, 1.0) * 20.0

    # Tempo score (10%)
    tempo = stats["DEX"] + m.initiative_bonus
    tempo_score = min(tempo / 20.0, 1.0) * 10.0

    # Synergy (5%)
    synergy_score = get_synergy_bonus(race_name, stats)

    # Race-stat alignment penalty: penalize builds that misalign with race design
    alignment_penalty = 0.0

    # CRITICAL: Penalize extremely weak stats (< 5 is unviable in combat)
    for stat_name, stat_val in stats.items():
        if stat_val < 5:
            alignment_penalty += 15.0  # Heavy penalty for nearly unplayable stats
        elif stat_val < 7:
            alignment_penalty += 8.0   # Moderate penalty for very weak stats

    # Strength-based races (Half-Orc, Dwarf) need STR
    if race_name in ["Half-Orc", "Dwarf"] and stats["STR"] < 13:
        alignment_penalty += 10.0

    # Dexterity-based races (Elf, Halfling, Tabaxi, Goblin) need DEX
    if race_name in ["Elf", "Halfling", "Tabaxi", "Goblin"] and stats["DEX"] < 13:
        alignment_penalty += 8.0

    # Penalize extreme stat imbalance (e.g., DEX=21, STR=12 for strength race)
    if race_name in ["Half-Orc", "Dwarf"]:
        str_dex_gap = stats["DEX"] - stats["STR"]
        if str_dex_gap > 6:
            alignment_penalty += min(5.0, str_dex_gap - 6)

    # Con-based races (Dwarf, Lizardfolk) benefit from high CON
    if race_name in ["Dwarf", "Lizardfolk"] and stats["CON"] < 13:
        alignment_penalty += 5.0

    final_score = max(0.0, hp_score + damage_score + defense_score + tempo_score + synergy_score - alignment_penalty)
    return final_score


# ── Section 4: Equipment Selector ──────────────────────────────────────────

def select_weapons(race_name: str, stats: Dict[str, int]) -> Tuple[str, str, Optional[str]]:
    """Select primary, secondary, and backup weapons for a race+stats combo."""
    race_obj = get_race(race_name)
    if not race_obj:
        return "Shortsword", "Open Hand", None

    m = race_obj.modifiers
    eff_str = stats["STR"] - m.strength_penalty
    preferred = m.preferred_weapons

    # Primary: highest damage from preferred (prefer no penalty, accept small penalty)
    primary = "Shortsword"
    best_score = -999
    for wname in preferred:
        try:
            w = get_weapon(wname)
            if w and hasattr(w, "damage_top"):
                pen = strength_penalty(eff_str, w.weight)
                # Score: damage minus penalty. Prefer no-penalty, but accept small penalties
                score = w.damage_top - (pen * 2)
                if score > best_score:
                    primary = wname
                    best_score = score
        except:
            pass

    # Exclude Goblin/Tabaxi heavy weapons
    exclude_weight = 4.0
    exclude_two_hand = race_name in ["Goblin", "Tabaxi"]

    # Secondary
    secondary = "Open Hand"
    if m.dual_weapon_bonus and stats["DEX"] >= 14:
        for wname in preferred:
            try:
                w = get_weapon(wname)
                if w and wname != primary:
                    if hasattr(w, "finesse") and w.finesse:
                        secondary = wname
                        break
            except:
                pass
    elif race_name == "Dwarf" and eff_str >= 15:
        try:
            shield = get_weapon("Target Shield")
            if shield:
                secondary = "Target Shield"
        except:
            pass
    elif race_name == "Goblin":
        for wname in ["Dagger", "Knife"]:
            try:
                w = get_weapon(wname)
                if w:
                    secondary = wname
                    break
            except:
                pass

    if secondary == "Open Hand":
        for wname in preferred:
            if wname != primary:
                try:
                    w = get_weapon(wname)
                    if w:
                        if exclude_two_hand and getattr(w, "two_hand", False):
                            continue
                        if exclude_weight and getattr(w, "weight", 0) >= exclude_weight:
                            continue
                        secondary = wname
                        break
                except:
                    pass

    # Backup: best throwable
    backup = None
    for wname in ["Dagger", "Knife", "Hatchet"]:
        try:
            w = get_weapon(wname)
            if w and hasattr(w, "range") and w.range and eff_str >= getattr(w, "strength_needed", 0):
                backup = wname
                break
        except:
            pass

    return primary, secondary, backup


def select_armor(race_name: str, stats: Dict[str, int]) -> Tuple[str, str]:
    """Select body armor and helm for a race+stats combo."""
    race_obj = get_race(race_name)
    if not race_obj:
        return "Leather", "Steel Cap"

    m = race_obj.modifiers
    eff_str = stats["STR"] - m.strength_penalty

    # Body armor: heaviest within STR capacity
    armor_list = ["Plate", "Chain", "Scale", "Brigandine", "Cuir Boulli", "Leather"]
    if race_name == "Dwarf":
        armor_list.insert(0, "Plate")

    selected_armor = "Leather"
    for aname in armor_list:
        a = ARMOR_PIECES.get(aname)
        if a:
            needed_str = ARMOR_STR_CAPACITY.get(aname, 0)
            if race_name == "Lizardfolk" and aname != "Leather":
                continue
            if race_name == "Dwarf":
                needed_str = max(0, needed_str - 1)
            if eff_str >= needed_str:
                selected_armor = aname
                break

    # Helm
    helm = "Steel Cap"
    if eff_str >= 5:
        helm = "Helm"

    return selected_armor, helm


# ── Section 5: Strategy Builder ────────────────────────────────────────────

def build_strategies(race_name: str, stats: Dict[str, int], primary_weapon: str = None) -> List[Tuple[str, str, int]]:
    """Build 6-slot strategy table using actual game triggers and race templates."""
    strategies = []

    # Slot 1: Fatigue trigger (progressive tiredness based on HP)
    hp_approx = math.ceil(stats["SIZ"] + stats["STR"] + stats["CON"] * 2.5)
    if hp_approx >= 70:
        fatigue_trigger = "You are very tired"
        fatigue_style = "Parry"
        fatigue_act = 3
    elif hp_approx >= 60:
        fatigue_trigger = "You are somewhat tired"
        fatigue_style = "Counterstrike"
        fatigue_act = 4
    else:
        fatigue_trigger = "You are slightly tired"
        fatigue_style = "Defend"
        fatigue_act = 4

    strategies.append((fatigue_trigger, fatigue_style, fatigue_act))

    # Slot 2: Damage taken trigger
    strategies.append(("You have taken heavy damage", "Counterstrike", 4))

    # Slots 3-5: Race-specific templates (unique triggers, no repeats)
    templates = RACE_STRAT_TEMPLATES.get(race_name, [])
    for i in range(3):
        if i < len(templates):
            trigger, style, act = templates[i]
            strategies.append((trigger, style, act))
        else:
            # Fallback: use unique actual triggers
            fallback_triggers = [
                ("Your foe is weaponless", "Bash", 6),
                ("You have exactly one weapon", "Strike", 5),
                ("Minute 3", "Slash", 5),
            ]
            if i < len(fallback_triggers):
                strategies.append(fallback_triggers[i])

    # Slot 6: Default always
    default_style, default_act = RACE_DEFAULT_STYLES.get(race_name, ("Strike", 5))
    strategies.append(("Always (Default Loop)", default_style, default_act))

    return strategies


# ── Section 6: Point Allocator ────────────────────────────────────────────

def enumerate_allocations(base_stats: Dict[str, int]) -> List[Dict[str, int]]:
    """
    Recursively enumerate all valid 16-point allocations from base stats.
    Each final stat must be 3–25. Returns list of allocation dicts.
    """
    results = []
    remaining = 16

    def recurse(idx: int, current: Dict[str, int], left: int) -> None:
        if idx == 6:
            if left == 0:
                results.append(copy.copy(current))
            return

        attr = ATTRS[idx]
        base = base_stats[attr]

        lo = max(0, left - sum(min(7, 25 - base_stats[a]) for a in ATTRS[idx+1:]))
        hi = min(7, left, 25 - base)

        for add in range(lo, hi + 1):
            current[attr] = base + add
            recurse(idx + 1, current, left - add)

    recurse(0, {}, remaining)
    return results


# ── Section 7: Simulator ───────────────────────────────────────────────────

def generate_random_opponent_pool(count: int = 40) -> List[Warrior]:
    """Generate diverse random warriors to test against."""
    import random
    opponents = []

    for i in range(count):
        race_name = random.choice(PLAYABLE_RACES)
        race_obj = get_race(race_name)
        if not race_obj:
            continue

        stats = {
            "STR": random.randint(8, 18),
            "DEX": random.randint(8, 18),
            "CON": random.randint(8, 18),
            "INT": random.randint(8, 16),
            "PRE": random.randint(8, 16),
            "SIZ": random.randint(6, 16),
        }

        warrior = Warrior(
            name=f"Rnd_{i}_{race_name}",
            race_name=race_name,
            gender=random.choice(["M", "F"]),
            strength=stats["STR"],
            dexterity=stats["DEX"],
            constitution=stats["CON"],
            intelligence=stats["INT"],
            presence=stats["PRE"],
            size=stats["SIZ"],
        )
        warrior.luck = random.randint(10, 16)

        try:
            primary, secondary, backup = select_weapons(race_name, stats)
            if primary != "Open Hand":
                warrior.primary_weapon = primary
            if secondary != "Open Hand":
                warrior.secondary_weapon = secondary
            if backup:
                warrior.backup_weapon = backup

            armor_name, helm_name = select_armor(race_name, stats)
            warrior.armor = armor_name
            warrior.helm = helm_name

            strats = build_strategies(race_name, stats)
            warrior.strategies = [Strategy(trigger=t, style=s, activity=a) for t, s, a in strats]

            opponents.append(warrior)
        except:
            pass

    return opponents


def simulate_candidate(warrior: Warrior, opponents: List[Warrior], n: int = 100) -> float:
    """
    Simulate candidate vs opponent pool n times each. Return win rate (0–1).
    Uses deepcopy to avoid mutation.
    """
    total_fights = 0
    total_wins = 0

    for opponent in opponents:
        for _ in range(n):
            c_copy = copy.deepcopy(warrior)
            o_copy = copy.deepcopy(opponent)
            result = run_fight(c_copy, o_copy)
            if result and result.winner and result.winner.name == c_copy.name:
                total_wins += 1
            total_fights += 1

    return total_wins / max(1, total_fights)


def build_archetype_warrior(config: dict) -> Warrior:
    """Build a single archetype warrior from config."""
    race_name = config["race"]
    race_obj = get_race(race_name)
    if not race_obj:
        return None

    stats = config["stats"]
    warrior = Warrior(
        name=race_name + "Archetype",
        race_name=race_name,
        gender="M",
        strength=stats["STR"],
        dexterity=stats["DEX"],
        constitution=stats["CON"],
        intelligence=stats["INT"],
        presence=stats["PRE"],
        size=stats["SIZ"],
    )

    warrior.luck = 15

    weapons = config.get("weapon_names", [])
    for i, wname in enumerate(weapons):
        try:
            w = get_weapon(wname)
            if w:
                if i == 0:
                    warrior.primary_weapon = wname
                elif i == 1:
                    warrior.secondary_weapon = wname
                elif i == 2:
                    warrior.backup_weapon = wname
        except:
            pass

    aname = config.get("armor_name", "Leather")
    warrior.armor = aname

    hname = "Helm" if "Helm" in ARMOR_PIECES else "Steel Cap"
    warrior.helm = hname

    trigger = config.get("strat_trigger", "Strike")
    act = config.get("strat_act", 5)
    strat = Strategy(trigger=trigger, style=trigger, activity=act)
    warrior.strategies = [strat]

    return warrior


# ── Section 8: Orchestrators ──────────────────────────────────────────────

def run_auto_mode(base_stats: Dict[str, int], progress_callback=None) -> Optional[OptResult]:
    """
    Auto mode: search all races + allocations, simulate top candidates,
    return single best result >= 55% win rate.
    """
    if sum(base_stats.values()) != 55:
        return None

    allocations = enumerate_allocations(base_stats)
    opponents = generate_random_opponent_pool(15)
    candidates = []

    # Score all allocations per race, keep top 5 per race
    for race_idx, race_name in enumerate(PLAYABLE_RACES):
        race_obj = get_race(race_name)
        if not race_obj:
            continue

        race_allocations = []
        for alloc in allocations:
            score = score_build(race_name, alloc)
            race_allocations.append((score, alloc))

        race_allocations.sort(reverse=True, key=lambda x: x[0])
        for score, alloc in race_allocations[:5]:  # Top 5 per race
            candidates.append((race_name, alloc, score))

        if progress_callback:
            progress_callback(int((race_idx / len(PLAYABLE_RACES)) * 30))

    # Simulate top candidates
    best_result = None
    best_win_rate = 0.0

    for cand_idx, (race_name, final_stats, heuristic_score) in enumerate(candidates):
        primary, secondary, backup = select_weapons(race_name, final_stats)
        armor_name, helm_name = select_armor(race_name, final_stats)
        strategies = build_strategies(race_name, final_stats)

        warrior = Warrior(
            name=f"Auto_{race_name}",
            race_name=race_name,
            gender="M",
            strength=final_stats["STR"],
            dexterity=final_stats["DEX"],
            constitution=final_stats["CON"],
            intelligence=final_stats["INT"],
            presence=final_stats["PRE"],
            size=final_stats["SIZ"],
        )
        warrior.luck = 15
        if primary != "Open Hand":
            try:
                warrior.primary_weapon = primary
            except:
                pass
        if secondary != "Open Hand":
            try:
                warrior.secondary_weapon = secondary
            except:
                pass
        if backup:
            try:
                warrior.backup_weapon = backup
            except:
                pass

        warrior.armor = armor_name
        warrior.helm = helm_name

        strats = []
        for trigger, style, act in strategies:
            s = Strategy(trigger=trigger, style=style, activity=act)
            strats.append(s)
        warrior.strategies = strats

        win_rate = simulate_candidate(warrior, opponents, n=20)

        if win_rate >= 0.45 and win_rate > best_win_rate:
            best_win_rate = win_rate
            best_result = OptResult(
                race_name=race_name,
                stats=final_stats,
                primary_weapon=primary,
                secondary_weapon=secondary,
                backup_weapon=backup,
                armor_name=armor_name,
                helm_name=helm_name,
                strategies=strategies,
                win_rate=win_rate,
                score=heuristic_score,
            )

        if progress_callback:
            progress_callback(30 + int((cand_idx / len(candidates)) * 70))

    return best_result


def run_manual_mode(final_stats: Dict[str, int], progress_callback=None) -> List[OptResult]:
    """
    Manual mode: user allocates; simulate all races and return top 3 by actual win rate >= 55%.
    (Heuristic score ignored; ranked purely by combat simulation results.)
    """
    if not all(3 <= final_stats.get(a, 0) <= 25 for a in ATTRS):
        return []

    results = []
    opponents = generate_random_opponent_pool(15)

    for race_idx, race_name in enumerate(PLAYABLE_RACES):
        race_obj = get_race(race_name)
        if not race_obj:
            continue

        primary, secondary, backup = select_weapons(race_name, final_stats)
        armor_name, helm_name = select_armor(race_name, final_stats)
        strategies = build_strategies(race_name, final_stats)

        warrior = Warrior(
            name=f"Manual_{race_name}",
            race_name=race_name,
            gender="M",
            strength=final_stats["STR"],
            dexterity=final_stats["DEX"],
            constitution=final_stats["CON"],
            intelligence=final_stats["INT"],
            presence=final_stats["PRE"],
            size=final_stats["SIZ"],
        )
        warrior.luck = 15
        if primary != "Open Hand":
            try:
                w = get_weapon(primary)
                if w:
                    warrior.primary_weapon = primary
            except:
                pass
        if secondary != "Open Hand":
            try:
                w = get_weapon(secondary)
                if w:
                    warrior.secondary_weapon = secondary
            except:
                pass
        if backup:
            try:
                w = get_weapon(backup)
                if w:
                    warrior.backup_weapon = backup
            except:
                pass

        warrior.armor = armor_name
        warrior.helm = helm_name

        strats = []
        for trigger, style, act in strategies:
            s = Strategy(trigger=trigger, style=style, activity=act)
            strats.append(s)
        warrior.strategies = strats

        win_rate = simulate_candidate(warrior, opponents, n=20)

        if win_rate >= 0.45:
            results.append(OptResult(
                race_name=race_name,
                stats=final_stats,
                primary_weapon=primary,
                secondary_weapon=secondary,
                backup_weapon=backup,
                armor_name=armor_name,
                helm_name=helm_name,
                strategies=strategies,
                win_rate=win_rate,
                score=win_rate * 100.0,
            ))

        if progress_callback:
            progress_callback(int((race_idx / len(PLAYABLE_RACES)) * 100))

    results.sort(key=lambda r: r.win_rate, reverse=True)
    return results[:3]


# ── Section 9: Tkinter UI ──────────────────────────────────────────────────

class WarriorOptimizerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Bloodspire Warrior Optimizer")
        self.root.geometry("600x700")

        self.mode = tk.StringVar(value="auto")
        self.stat_vars = {attr: tk.IntVar(value=9) for attr in ATTRS}
        self.results = []
        self.running = False

        self._build_ui()

    def _build_ui(self) -> None:
        # Header
        header = ttk.Frame(self.root)
        header.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)
        ttk.Label(header, text="Bloodspire Warrior Optimizer", font=("Arial", 14, "bold")).pack()

        # Mode selection
        mode_frame = ttk.LabelFrame(self.root, text="Mode", padding=10)
        mode_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        ttk.Radiobutton(mode_frame, text="Auto (search all races)", variable=self.mode, value="auto").pack(anchor=tk.W)
        ttk.Radiobutton(mode_frame, text="Manual (you allocate points)", variable=self.mode, value="manual").pack(anchor=tk.W)

        # Stats input
        stats_frame = ttk.LabelFrame(self.root, text="Base Stats (Pre-Allocation)", padding=10)
        stats_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        for i, attr in enumerate(ATTRS):
            if i % 3 == 0:
                row = ttk.Frame(stats_frame)
                row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"{attr}:").pack(side=tk.LEFT, padx=5)
            spinbox = ttk.Spinbox(row, from_=3, to=25, textvariable=self.stat_vars[attr], width=4)
            spinbox.pack(side=tk.LEFT, padx=5)
            # Bind to update points remaining
            self.stat_vars[attr].trace_add("write", self._update_points_remaining)

        # Points remaining / allocation input
        self.points_label = ttk.Label(self.root, text="Points remaining: 16", font=("Arial", 10))
        self.points_label.pack(side=tk.TOP, pady=5)

        # Optimize button
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
        self.optimize_btn = ttk.Button(btn_frame, text="Optimize!", command=self._on_optimize)
        self.optimize_btn.pack(side=tk.LEFT, padx=5)

        # Progress bar
        self.progress = ttk.Progressbar(self.root, length=400, mode="determinate")
        self.progress.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        # Results text area
        self.results_text = tk.Text(self.root, height=35, width=70, wrap=tk.WORD, font=("Courier", 9))
        self.results_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)

        scroll = ttk.Scrollbar(self.root, command=self.results_text.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.results_text.config(yscrollcommand=scroll.set)

    def _update_points_remaining(self, *args) -> None:
        """Update the points remaining label as user adjusts stats."""
        mode = self.mode.get()
        total = sum(self.stat_vars[attr].get() for attr in ATTRS)

        if mode == "auto":
            # Auto mode: base stats should sum to 55, then add up to 16 points to allocate
            base_sum = total
            points_used = base_sum - 54  # How many of the 16 have been used
            points_left = 16 - max(0, points_used)

            if base_sum == 55:
                status = "OK - Base stats locked"
            elif base_sum < 55:
                status = f"Need {55 - base_sum} more points"
            else:
                status = f"TOO HIGH (max 71: 55 base + 16 to allocate)"

            remaining_text = f"{status} | Sum: {base_sum}/55 base | Can allocate: {points_left}/16"
        else:  # manual
            # Manual mode: each stat 3-25, total allocation capped at 16
            # So final sum should be 55-71 (55 base + up to 16 points)
            base_sum = total
            max_sum = 71  # 55 base + 16 points max
            allocation = max(0, base_sum - 55)

            if base_sum > max_sum:
                status = f"TOO HIGH (max 71: 55+16)"
                color_status = "error"
            elif allocation > 16:
                status = f"Over allocation ({allocation}/16)"
                color_status = "warning"
            else:
                status = f"Valid"
                color_status = "ok"

            remaining_text = f"{status} | Sum: {base_sum}/71 | Allocated: {allocation}/16"

        self.points_label.config(text=remaining_text)

    def _on_optimize(self) -> None:
        if self.running:
            return

        self.running = True
        self.optimize_btn.config(state=tk.DISABLED)
        self.progress.config(value=0)

        thread = threading.Thread(target=self._run_optimization, daemon=True)
        thread.start()

    def _run_optimization(self) -> None:
        try:
            mode = self.mode.get()
            stats = {attr: self.stat_vars[attr].get() for attr in ATTRS}

            if mode == "auto":
                self._optimize_auto(stats)
            else:
                self._optimize_manual(stats)
        except Exception as e:
            self.results_text.delete(1.0, tk.END)
            self.results_text.insert(tk.END, f"Error: {e}")
        finally:
            self.running = False
            self.root.after(0, lambda: self.optimize_btn.config(state=tk.NORMAL))

    def _optimize_auto(self, stats: Dict[str, int]) -> None:
        self.root.after(0, lambda: self.results_text.delete(1.0, tk.END))
        self.root.after(0, lambda: self.results_text.insert(tk.END, "Searching races and testing allocations...\n(This may take a minute)\n"))

        def progress_cb(value):
            self.root.after(0, lambda: self.progress.config(value=value))

        result = run_auto_mode(stats, progress_callback=progress_cb)

        if result is None:
            self.root.after(0, lambda: self.results_text.delete(1.0, tk.END))
            self.root.after(0, lambda: self.results_text.insert(tk.END, "No viable builds found. Try different base stats. Try different base stats."))
            return

        self.root.after(0, lambda: self._display_result(result))
        self.root.after(0, lambda: self.progress.config(value=100))

    def _optimize_manual(self, stats: Dict[str, int]) -> None:
        self.root.after(0, lambda: self.results_text.delete(1.0, tk.END))
        self.root.after(0, lambda: self.results_text.insert(tk.END, "Testing all races...\n(This may take a minute)\n"))

        def progress_cb(value):
            self.root.after(0, lambda: self.progress.config(value=value))

        results = run_manual_mode(stats, progress_callback=progress_cb)

        if not results:
            self.root.after(0, lambda: self.results_text.delete(1.0, tk.END))
            self.root.after(0, lambda: self.results_text.insert(tk.END, "No races found with viable builds (45%+ win rate) for those stats. Try adjusting your point allocation."))
            return

        output = ""
        for i, result in enumerate(results, 1):
            output += self._format_result(result, rank=i)
            output += "\n" + ("=" * 70) + "\n\n"

        self.root.after(0, lambda: self.results_text.delete(1.0, tk.END))
        self.root.after(0, lambda: self.results_text.insert(tk.END, output))
        self.root.after(0, lambda: self.progress.config(value=100))

    def _display_result(self, result: OptResult) -> None:
        output = self._format_result(result)
        self.results_text.delete(1.0, tk.END)
        self.results_text.insert(tk.END, output)

    def _format_result(self, result: OptResult, rank: Optional[int] = None) -> str:
        rank_str = f"Rank #{rank} — " if rank else ""
        output = f"""{rank_str}Race: {result.race_name}
Win Rate: {result.win_rate * 100:.1f}%
Score: {result.score:.1f}

Stats: STR{result.stats['STR']} DEX{result.stats['DEX']} CON{result.stats['CON']} INT{result.stats['INT']} PRE{result.stats['PRE']} SIZ{result.stats['SIZ']}

Weapons:
  Primary: {result.primary_weapon}
  Secondary: {result.secondary_weapon}
  Backup: {result.backup_weapon or 'None'}

Armor: {result.armor_name}
Helm: {result.helm_name}

Strategies:
"""
        for i, (trigger, action, activity) in enumerate(result.strategies, 1):
            output += f"  {i}. [{trigger}] → {action} (Act:{activity})\n"

        return output


# ── Section 10: Main ────────────────────────────────────────────────────────

def main() -> None:
    root = tk.Tk()
    app = WarriorOptimizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
