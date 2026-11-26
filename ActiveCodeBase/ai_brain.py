# =============================================================================
# ai_brain.py - Learning engine for AI-controlled managers.
#
# This is the "understands the game and learns from mistakes" layer. It does
# four things:
#
#   1. ARCHETYPES  - a library of coherent, mechanically-sound build recipes
#      (race + stat emphasis + gear class + strategy package + training focus).
#
#   2. HEURISTIC EVALUATOR - a first-principles estimate of how good a build is
#      (HP from CON/STR/SIZE, DEX for initiative/accuracy, STR for damage, ...).
#      This gives every archetype a sensible COLD-START prior so brand-new AIs
#      field competent warriors before any results exist.
#
#   3. BANDIT SELECTION - a UCB-style chooser that blends the cold-start prior
#      with observed win rates. Early on the prior dominates; as fights accrue
#      the real results take over. That is the "learning": builds/strategies that
#      keep dying lose weight, ones that keep winning gain it.
#
#   4. CREDIT ASSIGNMENT - after a turn, parse each AI warrior's bouts and push
#      the outcomes back onto the archetype/strategy that produced them, plus a
#      per-manager memory of who beat/lost to whom (for challenge targeting).
#
# All randomness is driven by a caller-supplied random.Random so a turn rerun
# reproduces the same decisions. Knowledge persists to saves/league/ai_brain.json.
#
# The brain EMITS warrior dicts (Warrior.to_dict form) that the team builder in
# ai_league_teams.py drops straight into a team. It does NOT own naming (that is
# ai_names.py) or team assembly.
# =============================================================================

import os
import json
import math
import random
from typing import Dict, List, Optional

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
BRAIN_FILE = os.path.join(BASE_DIR, "saves", "league", "ai_brain.json")

# ---------------------------------------------------------------------------
# WEAPON CLASSES  (name pools; actual choice filters by what the warrior can
# wield via ai._best_wieldable_weapon, so under-strength picks fall back safely)
# ---------------------------------------------------------------------------

_WEAPON_CLASS = {
    "heavy":   ["Great Axe", "Great Sword", "War Flail", "War Hammer", "Great Pick", "Battle Axe"],
    "medium":  ["Morningstar", "Battle Axe", "Military Pick", "Long Sword", "Boar Spear", "Short Sword"],
    "light":   ["Short Sword", "Scimitar", "Hatchet", "Dagger", "Stiletto"],
    "finesse": ["Scimitar", "Short Sword", "Long Sword", "Scythe", "Dagger"],
    "thrown":  ["Javelin", "Hatchet", "Short Sword", "Dagger"],
}
_SECONDARY_CLASS = {
    "shield":   ["Target Shield", "Buckler", "Tower Shield", "Open Hand"],
    "buckler":  ["Buckler", "Target Shield", "Open Hand"],
    "offhand":  ["Short Sword", "Dagger", "Hatchet", "Open Hand"],
    "none":     ["Open Hand"],
}

# ---------------------------------------------------------------------------
# ARCHETYPE LIBRARY
# Each recipe: races (candidate list), stat_weights (rollup emphasis),
# weapon_class, secondary_class, armor (preferred; steps down if unwearable),
# style_package (drives strategies), train (focus pool), role (heuristic tag).
# ---------------------------------------------------------------------------

def _w(**kw):
    """Fill a full 6-stat weight dict, defaulting unspecified stats to 1."""
    base = {"strength": 1, "dexterity": 1, "constitution": 1,
            "intelligence": 1, "presence": 1, "size": 1}
    base.update(kw)
    return base

ARCHETYPES: Dict[str, dict] = {
    "orc_berserker": dict(
        races=["Half-Orc", "Human"], stat_weights=_w(strength=5, size=4, constitution=3),
        weapon_class="heavy", secondary_class="none", armor="Leather",
        style_package="berserker", train=["strength", "constitution", "initiative"], role="brute"),
    "orc_bruiser": dict(
        races=["Half-Orc", "Human", "Lizardfolk"], stat_weights=_w(strength=5, constitution=4, size=2),
        weapon_class="heavy", secondary_class="none", armor="Brigandine",
        style_package="aggressive", train=["strength", "constitution", "parry"], role="brute"),
    "human_allrounder": dict(
        races=["Human", "Half-Elf"], stat_weights=_w(strength=3, constitution=3, dexterity=3, presence=2),
        weapon_class="medium", secondary_class="buckler", armor="Chain",
        style_package="balanced", train=["strength", "dexterity", "dodge"], role="balanced"),
    "human_duelist": dict(
        races=["Human", "Half-Elf"], stat_weights=_w(dexterity=4, strength=3, constitution=3),
        weapon_class="medium", secondary_class="offhand", armor="Cuir Boulli",
        style_package="tactical", train=["dexterity", "parry", "initiative"], role="duelist"),
    "dwarf_wall": dict(
        races=["Dwarf"], stat_weights=_w(constitution=5, strength=3, size=2),
        weapon_class="medium", secondary_class="shield", armor="Full Plate",
        style_package="defensive", train=["constitution", "parry", "dodge"], role="tank"),
    "dwarf_counter": dict(
        races=["Dwarf", "Gnome"], stat_weights=_w(constitution=4, dexterity=3, strength=2),
        weapon_class="medium", secondary_class="shield", armor="Half-Plate",
        style_package="tactical", train=["parry", "constitution", "dexterity"], role="tank"),
    "elf_fencer": dict(
        races=["Elf", "Half-Elf"], stat_weights=_w(dexterity=5, constitution=3, presence=2),
        weapon_class="finesse", secondary_class="offhand", armor="Cuir Boulli",
        style_package="skirmisher", train=["dexterity", "dodge", "initiative"], role="duelist"),
    "elf_dualist": dict(
        races=["Elf"], stat_weights=_w(dexterity=5, constitution=2, presence=3),
        weapon_class="light", secondary_class="offhand", armor="Leather",
        style_package="aggressive", train=["dexterity", "initiative", "dodge"], role="duelist"),
    "halfling_skirmisher": dict(
        races=["Halfling", "Tabaxi"], stat_weights=_w(dexterity=5, constitution=3, strength=1),
        weapon_class="light", secondary_class="buckler", armor="Leather",
        style_package="skirmisher", train=["dodge", "dexterity", "initiative"], role="skirmisher"),
    "goblin_thrower": dict(
        races=["Goblin", "Halfling"], stat_weights=_w(dexterity=5, constitution=3, presence=1),
        weapon_class="thrown", secondary_class="offhand", armor="Leather",
        style_package="skirmisher", train=["throw", "dexterity", "dodge"], role="skirmisher"),
    "halfelf_bigblade": dict(
        races=["Half-Elf", "Human"], stat_weights=_w(strength=4, dexterity=3, constitution=3),
        weapon_class="heavy", secondary_class="none", armor="Scale",
        style_package="aggressive", train=["strength", "dexterity", "parry"], role="brute"),
    "gnome_tactician": dict(
        races=["Gnome", "Human"], stat_weights=_w(intelligence=4, dexterity=3, constitution=3),
        weapon_class="medium", secondary_class="shield", armor="Chain",
        style_package="tactical", train=["intelligence", "parry", "feint"], role="duelist"),
    "lizardfolk_brute": dict(
        races=["Lizardfolk", "Half-Orc"], stat_weights=_w(strength=4, constitution=4, size=2),
        weapon_class="medium", secondary_class="none", armor="Brigandine",
        style_package="balanced", train=["strength", "constitution", "dodge"], role="brute"),
    "tabaxi_acrobat": dict(
        races=["Tabaxi", "Elf"], stat_weights=_w(dexterity=5, constitution=3, presence=2),
        weapon_class="light", secondary_class="offhand", armor="Cuir Boulli",
        style_package="skirmisher", train=["dodge", "dexterity", "initiative"], role="skirmisher"),
}
# attach the key onto each recipe for convenience
for _k, _v in ARCHETYPES.items():
    _v["key"] = _k

# ---------------------------------------------------------------------------
# STRATEGY PACKAGES  -> list of Strategy row dicts (trigger/style/activity/aim/def)
# Coherent multi-row tables: react to damage, exploit a downed foe, conserve
# when tired, plus an "Always" default. Kept valid against strategy.py names.
# ---------------------------------------------------------------------------

def _strat(trigger, style, activity, aim="None", defense="None"):
    return {"trigger": trigger, "style": style, "activity": activity,
            "aim_point": aim, "defense_point": defense}

# ---------------------------------------------------------------------------
# FATIGUE HANDLING
# Endurance hitting 0 ends a fight as a loss and endurance never regenerates, so
# a warrior has to conserve BEFORE the pool is empty. Triggers are read top-down
# and the first true one wins: the "very tired" row must be the FIRST row, since
# below the damage rows a hurt and exhausted warrior would never reach it.
# ---------------------------------------------------------------------------

_VERY_TIRED_TRIGGER = "You are very tired"
_TIRED_TRIGGERS     = ("You are tired", "You are somewhat tired")
_DEFAULT_TRIGGERS   = ("Always", "Always (Default Loop)")
_CHEAP_STYLES       = ("Parry", "Defend", "Counterstrike", "Sure Strike", "Calculated Attack")
_CONSERVE_ACTIVITY  = 2     # activity of the very-tired row
_TIRED_ACTIVITY_MAX = 3     # ceiling for the existing "You are tired" row
ALWAYS_ACTIVITY_FLOOR = 3   # the learning step never lowers the default row below this


def _conserve_style(rows: List[dict]) -> str:
    """Cheapest sensible style: stay with Parry for a Parry/Defend build, else Counterstrike."""
    for r in rows:
        if (r.get("trigger") or "").strip() in _DEFAULT_TRIGGERS:
            return "Parry" if r.get("style") in ("Parry", "Defend") else "Counterstrike"
    return "Counterstrike"


def ensure_fatigue_rows(rows: List[dict]) -> bool:
    """Make a strategy table (list of row dicts, edited in place) conserve endurance.
    1. An existing "You are tired" row becomes a cheap style at activity <= 3.
    2. "You are very tired" -> cheap style at low activity, as the FIRST row.
    Idempotent. Returns True if anything changed."""
    changed = False
    for r in rows:
        if (r.get("trigger") or "").strip() in _TIRED_TRIGGERS:
            if r.get("style") not in _CHEAP_STYLES:
                r["style"] = "Counterstrike"
                changed = True
            if int(r.get("activity", 5)) > _TIRED_ACTIVITY_MAX:
                r["activity"] = _TIRED_ACTIVITY_MAX
                changed = True
    idx = next((i for i, r in enumerate(rows)
                if (r.get("trigger") or "").strip() == _VERY_TIRED_TRIGGER), None)
    if idx is None:
        rows.insert(0, _strat(_VERY_TIRED_TRIGGER, _conserve_style(rows),
                              _CONSERVE_ACTIVITY, "None", "Chest"))
        changed = True
    elif idx != 0:
        rows.insert(0, rows.pop(idx))
        changed = True
    return changed


def adapt_after_exhaustion(rows: List[dict]) -> str:
    """Learning step for a warrior who just collapsed from exhaustion (edits rows in place).
    First the structural fix (very-tired row on top, cheap tired row). If the table
    already has it, the default row's activity drops by 1, never below
    ALWAYS_ACTIVITY_FLOOR. Returns a short description, or "" if nothing could change."""
    if ensure_fatigue_rows(rows):
        return "added a very-tired conserve row at the top"
    for r in rows:
        if (r.get("trigger") or "").strip() in _DEFAULT_TRIGGERS:
            act = int(r.get("activity", 5))
            if act > ALWAYS_ACTIVITY_FLOOR:
                r["activity"] = act - 1
                return f"lowered the default activity to {act - 1}"
            break
    return ""


def _package(name: str, rng: random.Random) -> List[dict]:
    """Strategy table for a package, always with the fatigue rows in place."""
    rows = _package_base(name, rng)
    ensure_fatigue_rows(rows)
    return rows


def _package_base(name: str, rng: random.Random) -> List[dict]:
    aim = rng.choice(["Head", "Chest"])
    if name == "berserker":
        return [
            _strat("Your foe is on the ground", "Total Kill", 9, "Head"),
            _strat("You have taken heavy damage", "Wall of Steel", 6, "None", "Chest"),
            _strat("Always", "Total Kill", 9, aim, "None"),
        ]
    if name == "aggressive":
        return [
            _strat("Your foe is on the ground", "Bash", 9, "Head"),
            _strat("You have taken heavy damage", "Parry", 4, "None", "Chest"),
            _strat("You are tired", "Strike", 4, "None", "Chest"),
            _strat("Always", "Strike", 7, aim, "Chest"),
        ]
    if name == "balanced":
        return [
            _strat("Your foe is on the ground", "Strike", 8, "Head"),
            _strat("You have taken heavy damage", "Parry", 4, "None", "Chest"),
            _strat("You are tired", "Counterstrike", 4, "None", "Chest"),
            _strat("Always", "Counterstrike", 5, aim, "Chest"),
        ]
    if name == "defensive":
        return [
            _strat("Your foe is on the ground", "Bash", 7, "Head"),
            _strat("Your foe has taken heavy damage", "Strike", 7, "Head"),
            _strat("You are tired", "Parry", 3, "None", "Chest"),
            _strat("Always", "Parry", 3, "Chest", "Chest"),
        ]
    if name == "tactical":
        return [
            _strat("Your foe is on the ground", "Calculated Attack", 8, "Head"),
            _strat("You have taken heavy damage", "Defend", 3, "None", "Chest"),
            _strat("Your foe is very tired", "Lunge", 7, "Chest"),
            _strat("Always", "Counterstrike", 5, aim, "Chest"),
        ]
    if name == "skirmisher":
        return [
            _strat("Your foe is on the ground", "Lunge", 8, "Head"),
            _strat("You have taken heavy damage", "Engage & Withdraw", 5, "None", "Chest"),
            _strat("You are tired", "Engage & Withdraw", 4, "None", "Chest"),
            _strat("Always", "Lunge", 6, aim, "Chest"),
        ]
    # fallback
    return [_strat("Always", "Strike", 6, aim, "Chest")]


# ===========================================================================
# THE BRAIN
# ===========================================================================

# Quick-win tuning knobs
DECAY_PER_TURN     = 0.95    # old results fade fast so recent form drives choices (half-life ~14 turns)
FAILING_MIN_FIGHTS = 20      # decayed fight count needed before an archetype can be shelved
FAILING_SCORE      = 0.38    # observed score below this = shelved
SHELVED_REPROBE    = 0.05    # chance a pick ignores the shelf (so balance changes get noticed)
RECENT_FIGHTS_CAP  = 600
PEASANT_WEIGHT     = 0.3     # fights vs peasants teach less than fights vs real opposition
GEAR_PRIOR_STRENGTH = 8.0    # fights a gear choice needs before its own record outweighs the league-wide one
GEAR_EXPLORE       = 0.08    # bonus scale for rarely-tried gear choices
GEAR_TEMPERATURE   = 0.04    # sampling softness among gear choices (lower = greedier)
STAT_VARIANTS = {            # "base" = the archetype's recipe; others nudge one stat's emphasis
    "base": {}, "str+": {"strength": 2}, "dex+": {"dexterity": 2},
    "con+": {"constitution": 2}, "size+": {"size": 2},
}
TRAIN_VARIANTS = ("base", "wpn", "parry", "dodge", "initiative")   # what replaces the recipe's last training pick
ALL_PACKAGES = ("aggressive", "tactical", "balanced", "skirmisher", "defensive")
ADAPT_MIN_FIGHTS   = 8       # a warrior needs this many fights before the manager reconsiders his build
ADAPT_COOLDOWN     = 6       # fights between two changes to the same warrior
ADAPT_LOSING_BELOW = 0.45    # only warriors winning less than this are reworked
ADAPT_MARGIN       = 0.05    # a replacement must look at least this much better (win rate)
ADAPT_MIN_EVIDENCE = 10      # fights of evidence a replacement needs
GEAR_HOME_BONUS    = 0.05    # head start for the archetype's intended (first-listed) choice


class AIBrain:
    def __init__(self, path: str = BRAIN_FILE):
        self.path = path
        self.kb = {
            "version": 1,
            "archetypes": {},   # key -> counters
            "strategies": {},   # package -> counters
            "managers": {},     # mid -> {personality}
            "builds": {},       # warrior_id -> {archetype, stratpack, manager_id}
            "matchups": {},     # mid -> {opponent_name -> {w,l,k,d}}
            "diagnostics": {},  # "group:key" -> aggregated fight-cause stats (see _record_diag)
            "matchups_shared": {},  # opponent_name -> {w,l,k,d} pooled across ALL managers
            "adaptations": [],  # log of mid-career build changes made by managers
            "recent_fights": [],  # bounded log of per-fight diagnostics (raw material for later phases)
        }
        self.load()
        if not self.kb.get("matchups_shared") and self.kb.get("matchups"):
            sh = self.kb["matchups_shared"] = {}
            for mm in self.kb["matchups"].values():
                for opp, r in mm.items():
                    t = sh.setdefault(opp, {"w": 0, "l": 0, "k": 0, "d": 0})
                    for k in t:
                        t[k] += r.get(k, 0)

    # -- persistence --------------------------------------------------------
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in self.kb:
                    if k in data:
                        self.kb[k] = data[k]
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.kb, f, indent=2, default=str)
        except Exception as e:
            print(f"  [AI-BRAIN] could not save: {e}")

    # -- counters -----------------------------------------------------------
    @staticmethod
    def _blank():
        return {"fights": 0, "wins": 0, "losses": 0, "kills": 0, "deaths": 0, "minutes": 0, "exhausted": 0}

    @staticmethod
    def _namekey(name) -> str:
        # Warrior names are globally unique and stable for the warrior's life, so
        # they are a reliable build-map key -- unlike warrior_id, which stays None
        # until the server saves the team. Casefolded so bout/roster case differences
        # never break the lookup.
        return " ".join(str(name or "").split()).casefold()

    def _arch(self, key: str) -> dict:
        return self.kb["archetypes"].setdefault(key, self._blank())

    def _pack(self, name: str) -> dict:
        return self.kb["strategies"].setdefault(name, self._blank())

    # -- personality --------------------------------------------------------
    def get_personality(self, mid: str) -> dict:
        p = self.kb["managers"].get(str(mid))
        if p and "personality" in p:
            return p["personality"]
        r = random.Random("pers::" + str(mid))
        all_races = sorted({rc for a in ARCHETYPES.values() for rc in a["races"]})
        keys = list(ARCHETYPES.keys())
        pers = {
            "aggression":   round(r.uniform(0.2, 0.9), 2),
            "exploration":  round(r.uniform(0.10, 0.45), 2),
            "learning_rate": round(r.uniform(0.3, 0.8), 2),
            "favored_races": r.sample(all_races, k=r.randint(1, 3)),
            "favored_archetypes": r.sample(keys, k=r.randint(2, 4)),
        }
        self.kb["managers"].setdefault(str(mid), {})["personality"] = pers
        return pers

    # -- heuristic evaluator (cold-start prior) -----------------------------
    def _heuristic_prior(self, archetype: dict) -> float:
        """Rough 0..1 competence estimate of an archetype from first principles,
        using the ideal stat spread the recipe aims for. Rewards a solid HP/
        offense/mobility balance and punishes glass profiles."""
        weights = archetype["stat_weights"]
        total_w = sum(weights.values()) or 1
        # project the 16 rollup points by weight onto a nominal base of ~9 each
        proj = {k: 9 + 16 * (v / total_w) for k, v in weights.items()}
        hp   = proj["constitution"] * 2.5 + proj["strength"] + proj["size"]
        off  = proj["strength"] + 0.5 * proj["dexterity"]
        mob  = proj["dexterity"]
        endo = proj["constitution"] * 0.6 + proj["strength"] * 0.2
        # normalize each lever to ~0..1 against generous ceilings
        s_hp  = min(1.0, hp  / 90.0)
        s_off = min(1.0, off / 26.0)
        s_mob = min(1.0, mob / 22.0)
        s_end = min(1.0, endo / 18.0)
        score = 0.34 * s_hp + 0.28 * s_off + 0.24 * s_mob + 0.14 * s_end
        # penalize truly fragile builds (very low CON projection)
        if proj["constitution"] < 11:
            score *= 0.85
        return max(0.0, min(1.0, score))

    def evaluate_build(self, stats: dict, race_name: str = "") -> float:
        """Public: score a concrete stat block (post-rollup) 0..1. Used to sanity
        -check / compare finished warriors."""
        hp   = stats.get("constitution", 3) * 2.5 + stats.get("strength", 3) + stats.get("size", 3)
        off  = stats.get("strength", 3) + 0.5 * stats.get("dexterity", 3)
        mob  = stats.get("dexterity", 3)
        s_hp, s_off, s_mob = min(1, hp / 90.0), min(1, off / 26.0), min(1, mob / 22.0)
        return max(0.0, min(1.0, 0.4 * s_hp + 0.32 * s_off + 0.28 * s_mob))

    # -- bandit selection ---------------------------------------------------
    def _archetype_score(self, a: dict, pers: dict, total_fights: int) -> float:
        st = self._arch(a["key"])
        n  = st["fights"]
        win_rate  = (st["wins"] + 1) / (n + 2)          # Laplace-smoothed
        death_rate = st["deaths"] / (n + 1)
        prior = self._heuristic_prior(a)
        # confidence in observed data grows with sample size
        # learning_rate (0.3-0.8): higher = trusts results sooner (K 4..9 fights)
        conf = n / (n + 2.0 + 10.0 * (1.0 - pers.get("learning_rate", 0.5)))
        observed = win_rate - 0.5 * death_rate
        # Exploration bonus (UCB-style) -- deliberately modest so a proven winner
        # is not perpetually out-ranked by untried builds; it still lifts unseen
        # archetypes enough to get sampled early.
        explore = 0.35 * pers["exploration"] * math.sqrt(math.log(total_fights + 2) / (n + 1))
        # Personality is a cold-start taste only: it fades as evidence builds, so a
        # manager's pet archetype cannot override what the results say.
        fade  = (1.0 - conf) + 0.1
        bias  = 0.15 * fade if a["key"] in pers.get("favored_archetypes", []) else 0.0
        rbias = 0.05 * fade if any(r in pers.get("favored_races", []) for r in a["races"]) else 0.0
        return conf * observed + (1 - conf) * prior + explore + bias + rbias

    def choose_gear(self, group: str, arch_key: str, cands: list, rng: random.Random,
                    explore: float = 0.3) -> str:
        """Pick one of `cands` (in preference order) for an archetype using what
        fights have shown. group is 'aw' (weapon) or 'ar' (armor). Each choice's
        record for THIS archetype is shrunk toward that item's league-wide
        record, plus a small bonus for choices rarely tried."""
        if len(cands) == 1:
            return cands[0]
        diag = self.kb["diagnostics"]
        wide = {"aw": "weapon:", "ar": "armor:", "ap": "pack:"}.get(group)
        total = sum((diag.get("%s:%s|%s" % (group, arch_key, c)) or {"n": 0})["n"] for c in cands)
        scores = []
        a_all = diag.get("all") or {"n": 0, "wins": 0}
        base = (a_all["wins"] / a_all["n"]) if a_all["n"] >= 30 else 0.45
        for i, c in enumerate(cands):
            g_all = (diag.get(wide + c) if wide else None) or {"n": 0, "wins": 0}
            prior = (g_all["wins"] + 10.0 * base) / (g_all["n"] + 10.0)
            g = diag.get("%s:%s|%s" % (group, arch_key, c)) or {"n": 0, "wins": 0}
            n = g["n"]
            est = (g["wins"] + GEAR_PRIOR_STRENGTH * prior) / (n + GEAR_PRIOR_STRENGTH)
            bonus = GEAR_EXPLORE * math.sqrt(math.log(total + 2.0) / (n + 1.0)) * (0.5 + explore)
            order = GEAR_HOME_BONUS if i == 0 else 0.0      # cold start = today's preference
            scores.append(est + bonus + order)
        top = max(scores)
        weights = [math.exp((sc - top) / GEAR_TEMPERATURE) for sc in scores]
        return rng.choices(cands, weights=weights, k=1)[0]

    # -- mid-career adaptation ----------------------------------------------
    def _estimate(self, group: str, arch_key: str, choice: str):
        """(smoothed win rate, evidence count) of one option for an archetype."""
        diag = self.kb["diagnostics"]
        wide = {"aw": "weapon:", "ar": "armor:", "ap": "pack:"}.get(group)
        a_all = diag.get("all") or {"n": 0, "wins": 0}
        base = (a_all["wins"] / a_all["n"]) if a_all["n"] >= 30 else 0.45
        g_all = (diag.get(wide + choice) if wide else None) or {"n": 0, "wins": 0}
        prior = (g_all["wins"] + 10.0 * base) / (g_all["n"] + 10.0)
        g = diag.get("%s:%s|%s" % (group, arch_key, choice)) or {"n": 0, "wins": 0}
        n = g["n"]
        return (g["wins"] + GEAR_PRIOR_STRENGTH * prior) / (n + GEAR_PRIOR_STRENGTH), n

    def adapt_team(self, team: dict, rng: random.Random, turn: int = 0) -> list:
        """Let a manager rework LOSING living warriors using what the results show:
        a different armor tier, strategy package or training focus. Weapons are never
        swapped (the warrior's trained weapon skill would be wasted). At most one
        change per warrior per ADAPT_COOLDOWN fights. Returns descriptions of changes."""
        from armor import ARMOR_TIERS, can_wear_armor
        mid = team.get("manager_id")
        pers = self.get_personality(mid)
        changes = []
        for w in team.get("warriors") or []:
            if not isinstance(w, dict) or w.get("is_dead") or w.get("is_retired"):
                continue
            build = self.kb["builds"].get(self._namekey(w.get("name")))
            fights = int(w.get("total_fights", 0) or 0)
            wins, losses = int(w.get("wins", 0) or 0), int(w.get("losses", 0) or 0)
            if not build or fights < ADAPT_MIN_FIGHTS or (wins + losses) == 0:
                continue
            if wins / (wins + losses) >= ADAPT_LOSING_BELOW:
                continue
            if fights - int(build.get("adapted_at", -99)) < ADAPT_COOLDOWN:
                continue
            if rng.random() > 0.35 + 0.5 * pers.get("learning_rate", 0.5):
                continue                                  # slower managers reconsider less often
            arch = build["archetype"]
            options = []

            # 1. strategy package
            cur_pack = build.get("stratpack")
            cur_est, _ = self._estimate("ap", arch, cur_pack)
            for pk in ALL_PACKAGES + ("berserker",):
                if pk == cur_pack:
                    continue
                est, n = self._estimate("ap", arch, pk)
                if n >= ADAPT_MIN_EVIDENCE and est - cur_est >= ADAPT_MARGIN:
                    options.append((est - cur_est, "pack", pk, "package %s -> %s (%.0f%% vs %.0f%%, %d fights)" % (
                        cur_pack, pk, 100 * est, 100 * cur_est, n)))

            # 2. armor (neighbouring tiers the warrior can wear)
            order = list(ARMOR_TIERS)
            cur_arm = w.get("armor")
            if cur_arm in order:
                ci = order.index(cur_arm)
                cur_est, _ = self._estimate("ar", arch, cur_arm)
                is_dw = (w.get("race") == "Dwarf")
                for j in (ci - 1, ci + 1):
                    if 0 <= j < len(order) and can_wear_armor(order[j], w.get("strength", 10), is_dw)[0]:
                        est, n = self._estimate("ar", arch, order[j])
                        if n >= ADAPT_MIN_EVIDENCE and est - cur_est >= ADAPT_MARGIN:
                            options.append((est - cur_est, "armor", order[j], "armor %s -> %s (%.0f%% vs %.0f%%, %d fights)" % (
                                cur_arm, order[j], 100 * est, 100 * cur_est, n)))

            # 3. training focus (replace the last pick)
            cur_tr = build.get("train", "base")
            cur_est, _ = self._estimate("tr", arch, cur_tr)
            for tv in TRAIN_VARIANTS:
                if tv == cur_tr:
                    continue
                est, n = self._estimate("tr", arch, tv)
                if n >= ADAPT_MIN_EVIDENCE and est - cur_est >= ADAPT_MARGIN:
                    options.append((est - cur_est, "train", tv, "training %s -> %s (%.0f%% vs %.0f%%, %d fights)" % (
                        cur_tr, tv, 100 * est, 100 * cur_est, n)))

            if not options:
                continue
            options.sort(key=lambda o: -o[0])
            _, kind, val, text = options[0]
            if kind == "pack":
                w["strategies"] = _package(val, rng)
                build["stratpack"] = val
            elif kind == "armor":
                w["armor"] = val
            elif kind == "train":
                new = _weapon_skill_key(w.get("primary_weapon")) if val == "wpn" else (None if val == "base" else val)
                tr = list(w.get("trains") or [])
                if new and new not in tr and len(tr) >= 1:
                    tr = tr[:2] + [new] if len(tr) >= 3 else tr + [new]
                    w["trains"] = tr
                    build["train"] = val
                else:
                    continue
            build["adapted_at"] = fights
            msg = "%s (%s, %d-%d): %s" % (w.get("name"), arch, wins, losses, text)
            changes.append(msg)
            log = self.kb.setdefault("adaptations", [])
            log.append({"turn": turn, "mid": str(mid), "text": msg})
            if len(log) > 200:
                del log[:len(log) - 200]
        return changes

    def _is_failing(self, key: str) -> bool:
        """Enough evidence (after decay) and a clearly losing record."""
        st = self._arch(key)
        n = st["fights"]
        if n < FAILING_MIN_FIGHTS:
            return False
        return ((st["wins"] + 1) / (n + 2)) - 0.5 * (st["deaths"] / (n + 1)) < FAILING_SCORE

    def choose_archetype(self, mid: str, rng: random.Random,
                         pool: Optional[List[dict]] = None) -> dict:
        pers = self.get_personality(mid)
        cands = pool or list(ARCHETYPES.values())
        if rng.random() >= SHELVED_REPROBE:
            kept = [a for a in cands if not self._is_failing(a["key"])]
            if kept:
                cands = kept
        total = sum(self._arch(a["key"])["fights"] for a in cands)
        scored = sorted(cands, key=lambda a: self._archetype_score(a, pers, total), reverse=True)
        # Weighted pick among the top handful: the best is favored but variety
        # remains, so managers don't all converge on one identical build.
        top = scored[: min(4, len(scored))]
        weights = []
        for i, a in enumerate(top):
            s = self._archetype_score(a, pers, total)
            weights.append(max(0.01, s) * (0.6 ** i))   # decay by rank
        return rng.choices(top, weights=weights, k=1)[0]

    def suggest_team(self, mid: str, rng: random.Random, size: int = 5) -> List[dict]:
        """A coherent 5-build team. Managers reuse builds they trust, so some
        repetition is fine and human-like; we nudge toward >=2 distinct roles."""
        picks = [self.choose_archetype(mid, rng) for _ in range(size)]
        if len({p["key"] for p in picks}) == 1 and len(ARCHETYPES) > 1:
            # avoid a monoculture: swap one slot for a different top pick
            alt = self.choose_archetype(mid, rng,
                    pool=[a for a in ARCHETYPES.values() if a["key"] != picks[0]["key"]])
            picks[rng.randrange(size)] = alt
        return picks

    def choose_strategy_package(self, mid: str, archetype: dict,
                                rng: random.Random) -> str:
        """Native package is the starting point; every other package is a
        candidate too, and what actually wins for THIS archetype takes over."""
        native = archetype["style_package"]
        pers = self.get_personality(mid)
        cands = [native] + [p for p in ALL_PACKAGES if p != native]
        return self.choose_gear("ap", archetype["key"], cands, rng, pers["exploration"])

    def choose_stat_variant(self, mid: str, archetype: dict, rng: random.Random) -> str:
        """Small experiments on stat emphasis: the recipe, or the recipe with
        one stat weighted up. Results decide which variant an archetype keeps."""
        pers = self.get_personality(mid)
        cands = ["base"] + [v for v in STAT_VARIANTS if v != "base"]
        return self.choose_gear("sv", archetype["key"], cands, rng, pers["exploration"])

    # -- warrior construction ----------------------------------------------
    def build_warrior(self, archetype: dict, name: str, gender: str,
                      rng: random.Random, tier: int = 2,
                      manager_id: Optional[str] = None,
                      slot_index: Optional[int] = None) -> dict:
        """Materialize a valid Warrior.to_dict() from an archetype recipe."""
        from warrior import Warrior, Strategy, list_playable_races
        valid = set(list_playable_races())
        race = next((r for r in archetype["races"] if r in valid), None) or "Human"

        variant = "base"
        weights = archetype["stat_weights"]
        if manager_id is not None:
            variant = self.choose_stat_variant(manager_id, archetype, rng)
            if variant != "base":
                weights = dict(weights)
                for stat, add in STAT_VARIANTS[variant].items():
                    weights[stat] = weights.get(stat, 1) + add
        base  = _base_stats(rng)
        final = _weighted_rollup(base, weights, rng)
        w = Warrior(name=name, race_name=race, gender=gender, **final)
        w.luck = rng.randint(1, 30)

        # gear (validated wieldability / wearability)
        _assign_gear(w, archetype, tier,
                     brain=self if manager_id is not None else None, rng=rng,
                     explore=(self.get_personality(manager_id)["exploration"] if manager_id is not None else 0.3))

        # strategy package (possibly steered by the manager's learning)
        pack = self.choose_strategy_package(manager_id, archetype, rng) if manager_id else archetype["style_package"]
        w.strategies = [Strategy.from_dict(s) for s in _package(pack, rng)]

        # training focus
        pool = list(archetype.get("train", ["strength"]))
        w.trains = rng.sample(pool, k=min(3, len(pool)))
        train_var = "base"
        if manager_id is not None:
            pers_t = self.get_personality(manager_id)
            train_var = self.choose_gear("tr", archetype["key"], list(TRAIN_VARIANTS), rng, pers_t["exploration"])
            if train_var != "base":
                new = w.primary_weapon and _weapon_skill_key(w.primary_weapon) if train_var == "wpn" else train_var
                if new and new not in w.trains:
                    w.trains = list(w.trains)[:2] + [new] if len(w.trains) >= 3 else list(w.trains) + [new]
                else:
                    train_var = "base"

        d = w.to_dict()
        if slot_index is not None:
            d["slot_index"] = slot_index

        # Auto-generate taunts for AI warriors based on personality
        if manager_id is not None:
            pers = self.get_personality(manager_id)
            d["taunts_jeers"] = self._generate_ai_taunts(pers, archetype, rng)
            self.record_build(name, archetype["key"], pack, manager_id, variant, train_var)

        return d

    def _generate_ai_taunts(self, personality: dict, archetype: dict, rng: random.Random) -> dict:
        """Generate 1-2 personality-themed taunts for an AI warrior, using actual strategy triggers."""
        taunt_pools = {
            "aggressive": [
                "I will crush you!",
                "Feel my wrath!",
                "You won't last long!",
                "Fall before me!",
                "Come at me!",
                "This ends now!",
            ],
            "tactical": [
                "Interesting approach.",
                "I anticipated that.",
                "Your strategy is flawed.",
                "Let's see what you've got.",
                "Predictable.",
                "Time to adjust.",
            ],
            "cautious": [
                "Let's be careful here.",
                "Stay sharp.",
                "One step at a time.",
                "Steady now.",
                "Play it smart.",
                "No recklessness.",
            ],
            "balanced": [
                "Here we go!",
                "Show me your skill!",
                "This is it!",
                "May the best warrior win!",
                "On guard!",
                "Let's dance!",
            ],
        }

        # Pick 2 minute-based triggers for taunts (e.g. "Minute 1" and one other)
        taunt_triggers = ["Minute 1", rng.choice(["Minute 2", "Minute 3", "Minute 5"])]
        taunts = {}

        for trigger in taunt_triggers:
            if rng.random() < 0.6:  # 60% chance to generate a taunt per trigger
                pers_type = personality.get("personality_type", "balanced")
                pool = taunt_pools.get(pers_type, taunt_pools["balanced"])
                taunts[trigger] = rng.choice(pool)

        return taunts

    def record_build(self, warrior_name, archetype_key, stratpack, manager_id, variant="base", train="base"):
        key = self._namekey(warrior_name)
        if not key:
            return
        self.kb["builds"][key] = {
            "archetype": archetype_key, "stratpack": stratpack,
            "manager_id": str(manager_id), "name": warrior_name, "variant": variant, "train": train,
        }

    # -- credit assignment --------------------------------------------------
    def record_results(self, ai_results: Dict[str, dict], save: bool = True):
        """Feed a turn's AI result dicts back into the knowledge base. Each is
        the per-manager result: {manager_name, team:{warriors:[...]}, bouts:[...]}
        keyed by manager_id. Learns per-archetype/strategy and per-opponent."""
        if ai_results:
            self._decay()
        for mid, res in (ai_results or {}).items():
            if not isinstance(res, dict):
                continue
            team = res.get("team") or {}
            warriors = team.get("warriors") or []

            mm = self.kb["matchups"].setdefault(str(mid), {})
            for bout in (res.get("bouts") or []):
                if not isinstance(bout, dict):
                    continue
                wname = bout.get("warrior_name")
                build = self.kb["builds"].get(self._namekey(wname))
                result = (bout.get("result") or "").upper()
                won  = result == "WIN" or bout.get("opponent_slain")
                lost = result == "LOSS"
                slain = bool(bout.get("warrior_slain"))
                killed = bool(bout.get("opponent_slain"))
                mins = int(bout.get("minutes") or 0)
                exhausted = bool(bout.get("exhaustion_collapse"))

                wt = PEASANT_WEIGHT if (bout.get("fight_type") == "peasant") else 1.0
                if build:
                    for counters in (self._arch(build["archetype"]), self._pack(build["stratpack"])):
                        counters["fights"] += wt
                        counters["wins"]   += wt if won else 0
                        counters["losses"] += wt if lost else 0
                        counters["kills"]  += wt if killed else 0
                        counters["deaths"] += wt if slain else 0
                        counters["minutes"] += mins * wt
                        counters["exhausted"] = counters.get("exhausted", 0) + (wt if exhausted else 0)

                if bout.get("diag"):
                    self._record_diag(build, bout["diag"], mid, wt)

                # opponent memory (for later challenge targeting)
                opp = bout.get("opponent_name")
                if opp:
                    rec = mm.setdefault(opp, {"w": 0, "l": 0, "k": 0, "d": 0})
                    rec["w"] += 1 if won else 0
                    rec["l"] += 1 if lost else 0
                    rec["k"] += 1 if killed else 0
                    rec["d"] += 1 if slain else 0
                    sh = self.kb["matchups_shared"].setdefault(opp, {"w": 0, "l": 0, "k": 0, "d": 0})
                    sh["w"] += 1 if won else 0
                    sh["l"] += 1 if lost else 0
                    sh["k"] += 1 if killed else 0
                    sh["d"] += 1 if slain else 0

            # prune build entries for warriors that died (they won't fight again)
            for wdict in warriors:
                if isinstance(wdict, dict) and wdict.get("is_dead"):
                    self.kb["builds"].pop(self._namekey(wdict.get("name")), None)

        if save:
            self.save()

    # -- decay + fight-cause diagnostics ------------------------------------
    def _decay(self):
        """Fade old evidence so the model follows the current game, not history."""
        for table in (self.kb["archetypes"], self.kb["strategies"], self.kb["diagnostics"]):
            for rec in table.values():
                for k, v in list(rec.items()):
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        rec[k] = round(v * DECAY_PER_TURN, 4)
                    elif isinstance(v, dict):
                        for k2, v2 in list(v.items()):
                            if isinstance(v2, (int, float)):
                                v[k2] = round(v2 * DECAY_PER_TURN, 4)

    @staticmethod
    def _blank_diag():
        return {"n": 0, "wins": 0, "hp_margin": 0.0, "end_margin": 0.0, "kd_diff": 0.0,
                "nk_diff": 0.0, "minutes": 0.0,
                "loss_by": {"death": 0, "exhaustion": 0, "decision": 0},
                "win_by": {"death": 0, "exhaustion": 0, "decision": 0}}

    def _record_diag(self, build, d: dict, mid, wt: float = 1.0):
        """Aggregate WHY fights went the way they did, per build feature."""
        me, opp = d.get("me") or {}, d.get("opp") or {}
        keys = []
        if build:
            keys += ["arch:" + build["archetype"], "pack:" + build["stratpack"],
                     "arch_vs_oppweapon:%s|%s" % (build["archetype"], opp.get("weapon"))]
        if build:
            keys += ["ap:%s|%s" % (build["archetype"], build["stratpack"]),
                     "sv:%s|%s" % (build["archetype"], build.get("variant", "base")),
                     "tr:%s|%s" % (build["archetype"], build.get("train", "base")),
                     "aw:%s|%s" % (build["archetype"], me.get("weapon")),
                     "ar:%s|%s" % (build["archetype"], me.get("armor"))]
        keys += ["weapon:%s" % me.get("weapon"), "armor:%s" % me.get("armor"),
                 "helm:%s" % me.get("helm"), "vs_weapon:%s" % opp.get("weapon"),
                 "vs_armor:%s" % opp.get("armor"), "all"]
        won = bool(d.get("won"))
        ended = d.get("ended_by", "decision")
        side = "win_by" if won else "loss_by"
        for k in keys:
            g = self.kb["diagnostics"].setdefault(k, self._blank_diag())
            g["n"] += wt
            g["wins"] += wt if won else 0
            g["hp_margin"] += wt * (d.get("my_hp_end", 0) - d.get("opp_hp_end", 0))
            g["end_margin"] += wt * (d.get("my_end_end", 0) - d.get("opp_end_end", 0))
            g["kd_diff"] += wt * (d.get("my_knockdowns", 0) - d.get("opp_knockdowns", 0))
            g["nk_diff"] += wt * (d.get("my_near_kills", 0) - d.get("opp_near_kills", 0))
            g["minutes"] += wt * d.get("minutes", 0)
            g[side][ended] = g[side].get(ended, 0) + wt
        log = self.kb["recent_fights"]
        log.append({"mid": str(mid), "arch": (build or {}).get("archetype"),
                    "pack": (build or {}).get("stratpack"), **d})
        if len(log) > RECENT_FIGHTS_CAP:
            del log[:len(log) - RECENT_FIGHTS_CAP]

    def learning_report(self, min_n: float = 8.0) -> str:
        """Human-readable summary of what the AI has learned (admin use)."""
        out = []

        def table(title, prefix):
            rows = [(k[len(prefix):], g) for k, g in self.kb["diagnostics"].items()
                    if k.startswith(prefix) and g["n"] >= min_n]
            rows.sort(key=lambda t: -t[1]["wins"] / t[1]["n"])
            out.append(title)
            out.append("  %-26s %6s %6s %7s %7s %6s  losses: death/exh/decision" %
                       ("", "n", "win%", "hpMrg", "endMrg", "kd"))
            for k, g in rows:
                lb = g["loss_by"]
                out.append("  %-26s %6.0f %6.1f %7.2f %7.2f %6.2f  %.0f/%.0f/%.0f" % (
                    str(k)[:26], g["n"], 100 * g["wins"] / g["n"], g["hp_margin"] / g["n"],
                    g["end_margin"] / g["n"], g["kd_diff"] / g["n"],
                    lb.get("death", 0), lb.get("exhaustion", 0), lb.get("decision", 0)))
            out.append("")

        a = self.kb["diagnostics"].get("all")
        if a and a["n"]:
            out.append("Overall: %.0f fights (decayed), win %.1f%%, avg HP margin %.2f, avg endurance margin %.2f" % (
                a["n"], 100 * a["wins"] / a["n"], a["hp_margin"] / a["n"], a["end_margin"] / a["n"]))
            out.append("")
        table("BY ARCHETYPE", "arch:")
        table("BY STRATEGY PACKAGE", "pack:")
        table("BY MY WEAPON", "weapon:")
        table("BY MY ARMOR", "armor:")
        table("BY OPPONENT WEAPON (how we do against it)", "vs_weapon:")
        table("STRATEGY PACKAGE PER ARCHETYPE (archetype|package)", "ap:")
        table("STAT EMPHASIS EXPERIMENTS (archetype|variant)", "sv:")
        table("TRAINING FOCUS EXPERIMENTS (archetype|last pick)", "tr:")
        table("WEAPON CHOICE PER ARCHETYPE (archetype|weapon)", "aw:")
        table("ARMOR CHOICE PER ARCHETYPE (archetype|armor)", "ar:")
        ad = self.kb.get("adaptations") or []
        out.append("RECENT MID-CAREER ADJUSTMENTS (%d logged)" % len(ad))
        for a in ad[-15:]:
            out.append("  turn %s %s: %s" % (a.get("turn"), a.get("mid"), a.get("text")))
        out.append("")
        shelved = [k for k in self.kb["archetypes"] if self._is_failing(k)]
        out.append("Shelved archetypes (failing, re-probed %d%% of picks): %s" % (
            int(SHELVED_REPROBE * 100), ", ".join(shelved) or "none"))
        return "\n".join(out)

    # -- challenge targeting helper ----------------------------------------
    def rate_opponent(self, mid: str, opponent_name: str) -> float:
        """>0 means we tend to beat them (good challenge target), <0 means they
        tend to beat us. 0 if unknown."""
        own = self.kb["matchups"].get(str(mid), {}).get(opponent_name) or {}
        sh  = self.kb.get("matchups_shared", {}).get(opponent_name) or {}
        # own experience counts fully; the whole league's experience counts a third
        w = own.get("w", 0) + 0.33 * sh.get("w", 0)
        l = own.get("l", 0) + 0.33 * sh.get("l", 0)
        if w + l <= 0:
            return 0.0
        return (w - l) / (w + l)


# ---------------------------------------------------------------------------
# BUILD PRIMITIVES  (deterministic; driven by the passed rng)
# ---------------------------------------------------------------------------

def _base_stats(rng: random.Random) -> Dict[str, int]:
    """Deterministic version of warrior.generate_base_stats using our rng."""
    from warrior import ATTRIBUTES
    try:
        from warrior import BASE_STAT_TOTAL, BASE_STAT_MIN, BASE_STAT_MAX
    except Exception:
        BASE_STAT_TOTAL, BASE_STAT_MIN, BASE_STAT_MAX = 55, 3, 21
    stats = {a: BASE_STAT_MIN for a in ATTRIBUTES}
    remaining = BASE_STAT_TOTAL - BASE_STAT_MIN * len(ATTRIBUTES)
    while remaining > 0:
        avail = [a for a in ATTRIBUTES if stats[a] < BASE_STAT_MAX]
        if not avail:
            break
        stats[rng.choice(avail)] += 1
        remaining -= 1
    return stats


def _weighted_rollup(base: Dict[str, int], stat_weights: Dict[str, int],
                     rng: random.Random) -> Dict[str, int]:
    """Distribute the 16 rollup points by archetype weight, honoring the per-stat
    and total caps via warrior.max_addable / validate_additions."""
    from warrior import ATTRIBUTES, ROLLUP_POINTS, max_addable, validate_additions
    weights = {a: max(0.0, float(stat_weights.get(a, 1))) for a in ATTRIBUTES}
    additions = {a: 0 for a in ATTRIBUTES}
    remaining = ROLLUP_POINTS
    while remaining > 0:
        avail = [a for a in ATTRIBUTES if additions[a] < max_addable(base, a)]
        if not avail:
            break
        wts = [weights.get(a, 0.0) or 0.0001 for a in avail]
        chosen = rng.choices(avail, weights=wts, k=1)[0]
        additions[chosen] += 1
        remaining -= 1
    return validate_additions(base, additions)


def _weapon_skill_key(weapon_name: str):
    try:
        from weapons import get_weapon
        return get_weapon(weapon_name).skill_key
    except Exception:
        return None


def _wieldable_candidates(warrior, prefs):
    """All weapons in prefs the warrior can wield (same 30% penalty rule as
    ai._best_wieldable_weapon), in preference order."""
    from weapons import strength_penalty, get_effective_strength_for_weapons, get_weapon
    eff = get_effective_strength_for_weapons(warrior)
    out = []
    for n in prefs:
        try:
            w = get_weapon(n)
            if strength_penalty(w.weight, eff, w.two_hand) < 0.30:
                out.append(n)
        except ValueError:
            continue
    return out


def _assign_gear(warrior, archetype: dict, tier: int, brain=None, rng=None, explore: float = 0.3):
    """Pick wieldable weapons and wearable armor for the warrior from the
    archetype's gear classes, falling back safely when under-strength."""
    from ai import _best_wieldable_weapon
    from weapons import get_weapon
    from armor import ARMOR_TIERS, HELM_TIERS, can_wear_armor

    is_dw = (warrior.race.name == "Dwarf")

    wprefs = _WEAPON_CLASS.get(archetype["weapon_class"], _WEAPON_CLASS["medium"])
    primary = _best_wieldable_weapon(warrior, wprefs)
    if brain is not None and rng is not None:
        cands = _wieldable_candidates(warrior, wprefs)
        if cands:
            primary = brain.choose_gear("aw", archetype["key"], cands, rng, explore)
    warrior.primary_weapon = primary

    sec_prefs = _SECONDARY_CLASS.get(archetype.get("secondary_class", "none"), ["Open Hand"])
    secondary = _best_wieldable_weapon(warrior, sec_prefs, allow_open_hand=True)
    try:
        if get_weapon(primary).two_hand:
            secondary = "Open Hand"
    except Exception:
        pass
    warrior.secondary_weapon = secondary
    warrior.backup_weapon = "Open Hand"

    # armor: try the archetype's preferred tier, else step down until wearable
    pref = archetype.get("armor", "Leather")
    order = list(ARMOR_TIERS)
    start = order.index(pref) if pref in order else min(tier, len(order) - 1)
    chosen = None
    for i in range(start, -1, -1):
        allowed, _ = can_wear_armor(order[i], warrior.strength, is_dw)
        if allowed:
            chosen = order[i]
            break
    if brain is not None and rng is not None and chosen in order:
        # learned choice among the preferred tier and its wearable neighbours
        ci = order.index(chosen)
        acands = [order[j] for j in (ci, ci - 1, ci + 1)
                  if 0 <= j < len(order) and can_wear_armor(order[j], warrior.strength, is_dw)[0]]
        if len(acands) > 1:
            chosen = brain.choose_gear("ar", archetype["key"], acands, rng, explore)
    warrior.armor = chosen or "Cloth"
    warrior.helm = HELM_TIERS[min(tier - 1, len(HELM_TIERS) - 1)]


# ---------------------------------------------------------------------------
# module-level convenience singleton
# ---------------------------------------------------------------------------

_BRAIN: Optional[AIBrain] = None

def get_brain() -> AIBrain:
    global _BRAIN
    if _BRAIN is None:
        _BRAIN = AIBrain()
    return _BRAIN


# ---------------------------------------------------------------------------
# Manual smoke test:  python ai_brain.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    brain = AIBrain(path=os.path.join(BASE_DIR, "saves", "league", "_ai_brain_test.json"))
    rng = random.Random(2024)
    mid = "ai_00"
    print("personality:", brain.get_personality(mid))
    print("\ncold-start archetype priors (sorted):")
    for a in sorted(ARCHETYPES.values(), key=lambda x: brain._heuristic_prior(x), reverse=True):
        print(f"  {a['key']:<20} prior={brain._heuristic_prior(a):.3f}  ({a['role']})")

    print("\nbuilding a suggested team:")
    team_warriors = []
    for i, arc in enumerate(brain.suggest_team(mid, rng)):
        d = brain.build_warrior(arc, f"Test{i}", "Male", rng, tier=2, manager_id=mid, slot_index=i)
        team_warriors.append(d)
        stats = {k: d[k] for k in ("strength", "dexterity", "constitution", "intelligence", "presence", "size")}
        print(f"  slot {i}: {arc['key']:<18} {d['race']:<10} HP={d['max_hp']:<4} "
              f"wpn={d['primary_weapon']:<14} armor={d['armor']:<12} "
              f"eval={brain.evaluate_build(stats):.2f}")

    # simulate a turn of results to prove learning updates
    bouts = []
    for i, d in enumerate(team_warriors):
        bouts.append({
            "warrior_name": d["name"], "opponent_name": f"Foe{i}",
            "result": "WIN" if i % 2 == 0 else "LOSS", "minutes": 2 + i,
            "opponent_slain": i == 0, "warrior_slain": i == 3,
        })
    team_warriors[3]["is_dead"] = True   # slot 3 was slain this turn
    fake = {mid: {"manager_name": "Tester",
                  "team": {"warriors": team_warriors}, "bouts": bouts}}
    before_builds = len(brain.kb["builds"])
    print("\narchetype counters BEFORE:",
          {k: v['fights'] for k, v in brain.kb["archetypes"].items() if v['fights']})
    brain.record_results(fake, save=False)
    after = {}
    for k, v in brain.kb["archetypes"].items():
        if v["fights"]:
            after[k] = "{}W-{}L-{}D/{}f".format(v["wins"], v["losses"], v["deaths"], v["fights"])
    print("archetype counters AFTER: ", after)
    print("opponent memory:", brain.kb["matchups"].get(mid))
    print("builds: {} -> {} after death-prune (slain slot 3 removed)".format(
        before_builds, len(brain.kb["builds"])))
