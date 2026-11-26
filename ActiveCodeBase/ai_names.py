# =============================================================================
# ai_names.py - Procedural name generation for learning AI managers.
#
# Real Bloodspire players name things with a recognizable "voice":
#   - MANAGERS pick one persona style and stay consistent (fantasy-evocative,
#     an internet handle, or a character/catchphrase persona).
#   - TEAMS pick a "lens" (dark, absurdist/pun, high-fantasy, or straightforward
#     attitude) and name the team to match.
#   - WARRIORS on a team share a MOTIF (food puns, mythology, fantasy compounds,
#     gaming refs, etc.) regardless of the warrior's race.
#
# This module reproduces that voice so AI-generated names blend in with humans.
# Everything is driven by a seeded random.Random instance so that a given
# (manager, turn) always produces the same names -- important for turn reruns.
#
# Public API:
#   gen = NameGenerator(seed=..., used_names=<iterable of taken names>)
#   gen.manager_name()                 -> str
#   ident = gen.team_identity()        -> {"team_name","lens","motif"}
#   gen.warrior_names(motif, count=5)  -> [str, ...]
#   gen.reserve(name)                  -> mark a name as taken
#
# Convenience:
#   load_existing_names()  -> set of names already used by players/AI (dedupe)
#   make_registry()        -> shared taken-name set (scan save files once)
#   generate_roster(n)     -> full deduped roster in one pass (spawn a new roster)
#
# Guaranteeing GLOBAL uniqueness with per-manager seeding (turn reruns):
#   reg = make_registry()
#   for i, mgr in enumerate(ai_managers):
#       g = NameGenerator(seed=turn*1000 + i, shared=reg, load_existing=False)
#       new_names = g.warrior_names(mgr.motif, k)
#   Every generator shares `reg`, so no two warriors (across any team) collide,
#   while each manager keeps its own RNG for reproducible-on-rerun choices.
# =============================================================================

import os
import json
import random
from typing import Iterable, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# MANAGER PERSONA POOLS
# ---------------------------------------------------------------------------

# Family 1: fantasy-evocative -- "Adjective Noun" or a single arcane name.
_MGR_FANTASY_ADJ = [
    "Sanguine", "Grey", "Crimson", "Ashen", "Iron", "Silent", "Dread", "Pale",
    "Black", "Golden", "Shattered", "Hollow", "Eternal", "Fell", "Grim", "Wretched",
    "Vengeful", "Obsidian", "Bloodied", "Forsaken", "Wandering", "Nameless",
    "Twilight", "Storm", "Ember", "Frost", "Shadow", "Ruined",
]
_MGR_FANTASY_NOUN = [
    "Savior", "Phantom", "Warden", "Reaver", "Herald", "Butcher", "Sovereign",
    "Marauder", "Prophet", "Pilgrim", "Executioner", "Widow", "Baron", "Serpent",
    "Revenant", "Tyrant", "Harbinger", "Wolf", "Raven", "Warlord", "Scourge",
    "Gravedigger", "Inquisitor", "Vagrant", "Duelist",
]
_MGR_ARCANE = [
    "Ilneval", "Malakar", "Vorthax", "Grimwald", "Zaltaris", "Nyx", "Kael",
    "Draven", "Morrigath", "Sethis", "Varic", "Ossric", "Thal", "Zephyrine",
    "Corvane", "Skarn", "Vandred", "Lysander", "Torgal", "Nethys",
]

# Family 2: internet handles / gamertags.
_HANDLE_WORDS = [
    "Reaper", "Vandal", "Havoc", "Rogue", "Venom", "Wraith", "Blitz", "Chaos",
    "Rebel", "Karma", "Nomad", "Cipher", "Riot", "Static", "Fury", "Jinx",
    "Maverick", "Phantom", "Goblin", "Doom", "Slayer", "Ghost", "Toxic",
]
_HANDLE_PREFIX = ["", "", "", "Dr", "Mr", "Big", "Lil", "Old", "Mad", "Sir"]
_HANDLE_LEET = ["B4youwereborn", "2Legit2Quit", "N0Mercy", "GG_EZ", "1HitWonder",
                "xX_", "_TTV", "IRL", "AFK", "OG"]

# Family 3: character / catchphrase personas.
_PERSONA_FIRST = [
    "Cyrus", "Sleazy", "Duke", "Tank", "Boss", "Ace", "Rusty", "Vinnie",
    "Slick", "Diesel", "Chuck", "Gus", "Rex", "Moe", "Buck", "Sal",
]
_PERSONA_TAG = [
    "the Virus", "the Vandal", "the Menace", "the Machine", "the Merciless",
    "the Mad", "the Unhinged", "the Undefeated", "the Untamed", "the Terrible",
    "P. Martinee", "McGraw", "the Great", "the Bloody", "Da Butcher",
]
_PERSONA_SURNAME = [
    "Ironsides", "Blackwood", "Grimshaw", "Thorne", "Vane", "Kane", "Crowe",
    "Ashford", "Bane", "Marsh", "Dredge", "Holloway", "Ravenscar", "Grave",
]

# ---------------------------------------------------------------------------
# TEAM NAME POOLS (grouped by lens)
# ---------------------------------------------------------------------------

_TEAM_DARK = [
    "Crimson Legion", "Violence Has Arrived", "The Howl of War", "Last Command",
    "Eclipse", "Silent Rage", "The Burning Red", "Nothing Left Alive",
    "Endless Apocalypse", "The Bleeding Edge", "Wrath Incarnate", "Dead Man's Hand",
    "The Final Verdict", "Carrion Court", "Blood in the Sand", "The Reckoning",
    "Terminal Velocity", "Scorched Earth", "The Widowmakers", "No Survivors",
]
_TEAM_FANTASY = [
    "The Eternal Blades", "The Pantheon of Steel", "Orcland Raiders",
    "Riekland Reavers", "Spiritual Entities", "The Shadow Syndicate",
    "House of the Dying Sun", "The Iron Covenant", "Wardens of the Deep",
    "The Ashen Vanguard", "Stormcrow Company", "The Gilded Fangs",
    "Sons of the Broken Spire", "The Obsidian Order", "Thornhaven Guard",
    "The Emberwrought", "Knights of the Pale", "The Grave Wardens",
]
_TEAM_ABSURD = [
    "Dimwitted Bozos", "Human Beans", "Gladiator Sandwich", "Slap Punch Poke Kick",
    "Go On, Git!", "Reject Candy Hearts", "People Who Peaked", "Come Out and Play",
    "Just Say It", "Breaking Sad", "Soup for Brains", "7 Minute Abs",
    "Certified Bozos", "The Wet Bandits", "Room Temperature IQ", "Big Mad",
    "Skill Issue", "Two Left Feet", "Snack Attack", "Mostly Harmless",
]
_TEAM_ATTITUDE = [
    "On the Prowl", "Hard N' Heavy", "At Sea", "The Usual Suspects", "Bad Company",
    "No Chill", "Full Send", "Rough Trade", "The Long Odds", "Down to Business",
    "Hit and Run", "The Underdogs", "Cold Blooded", "Fair Warning", "Loose Cannons",
    "The Comeback", "House Money", "Bare Knuckle",
]

_TEAM_POOLS = {
    "dark": _TEAM_DARK,
    "fantasy": _TEAM_FANTASY,
    "absurd": _TEAM_ABSURD,
    "attitude": _TEAM_ATTITUDE,
}

# Which warrior motifs suit each team lens.
_LENS_MOTIFS = {
    "dark":      ["menacing_words", "undead", "fantasy_compound"],
    "fantasy":   ["fantasy_compound", "mythology", "fantasy_first"],
    "absurd":    ["food", "gaming", "expletive_lite", "silly"],
    "attitude":  ["historical", "fantasy_compound", "one_word"],
}

# ---------------------------------------------------------------------------
# WARRIOR MOTIF POOLS
# ---------------------------------------------------------------------------

_MOTIF_STATIC = {
    "mythology": [
        "Athena", "Ares", "Perseus", "Achilles", "Hector", "Odin", "Thor",
        "Loki", "Freya", "Tyr", "Anubis", "Horus", "Sekhmet", "Ra", "Osiris",
        "Zeus", "Hades", "Apollo", "Artemis", "Hercules", "Fenrir", "Valkyrie",
        "Cerberus", "Medusa", "Chronos", "Nemesis",
    ],
    "historical": [
        "Genghis Khan", "Alexander the Great", "Oda Nobunaga", "Ivan the Terrible",
        "Attila", "Hannibal", "Spartacus", "Leonidas", "Boudica", "Saladin",
        "Vlad Tepes", "Charlemagne", "Ragnar Lodbrok", "El Cid", "Tamerlane",
        "Sun Tzu", "Cyrus the Great", "Miyamoto Musashi",
    ],
    "food": [
        "Bread Cheese Bacon", "Croque Monsieur", "Bun Meat Cheese", "Sloppy Joe",
        "Hot Pocket", "Meat Lover", "Extra Mustard", "Double Patty", "Side of Fries",
        "The Pickle", "Ham on Rye", "Grilled Cheese", "Cold Cut Combo",
        "Beef Wellington", "Chili Dog", "Mystery Meat",
    ],
    "gaming": [
        "Mario", "Luigi", "Bowser", "Donkey Kong", "Link", "Zelda", "Kratos",
        "Master Chief", "Sub-Zero", "Scorpion", "Ryu", "Ken", "Pac-Man",
        "Sonic", "Kirby", "Samus", "Ganon", "Sephiroth", "Cloud", "Doomguy",
    ],
    "expletive_lite": [
        "Dang", "Shoot", "Frack", "Sonuva", "Fiddlesticks", "Aw Nuts", "Rats",
        "Good Grief", "For Pete's Sake", "Son of a Biscuit", "Cheese and Rice",
        "Dagnabbit", "Balderdash", "Fudge", "Great Scott", "Yikes",
    ],
    "silly": [
        "Sir Loin", "Ham Solo", "Chewbroccoli", "Moist von Lipwig", "Sofa King",
        "Ivana Wynn", "Buster Cherry", "Al Coholic", "Anita Bath", "Hugh Jass",
        "Ben Dover", "Seymour Butz", "Rusty Nails", "Crash Landon",
    ],
    "undead": [
        "Lich Lord", "Specter", "Phantasm", "Shade", "Wraith", "Revenant",
        "Bone Marrow", "Grave Chill", "Cold Hollow", "The Interred", "Pallor",
        "Ghoul", "Nightcrawler", "Deadweight", "Rigor", "Mortis", "Ashes",
    ],
    "menacing_words": [
        "Heresy", "Carnage", "Malice", "Ruin", "Dread", "Havoc", "Spite",
        "Vengeance", "Torment", "Sorrow", "Wrath", "Plague", "Bloodlust",
        "Requiem", "Cataclysm", "Onslaught", "Reckoning", "Slaughter",
    ],
    "one_word": [
        "Bruiser", "Crusher", "Slugger", "Mauler", "Basher", "Wrecker", "Grinder",
        "Hammer", "Anvil", "Boulder", "Tank", "Bulldog", "Ox", "Rhino", "Mule",
    ],
}

# fantasy_first: gendered first-name pools (kept modest; combos add breadth).
_FANTASY_FIRST_M = [
    "Aldric", "Dorian", "Kaedric", "Leoric", "Malachar", "Ragnar", "Soren",
    "Torben", "Varian", "Corvin", "Eldric", "Gareth", "Roderic", "Thane",
    "Bram", "Kelric", "Lorcan", "Morden", "Osric", "Ulric", "Valdris",
]
_FANTASY_FIRST_F = [
    "Elara", "Lyssara", "Nerissa", "Ravenna", "Selene", "Thessaly", "Morrigan",
    "Isolde", "Maelys", "Bilaria", "Tralia", "Kestrel", "Liriel", "Phaedra",
    "Vespera", "Sabine", "Ondine", "Calista", "Erevan", "Aelwen",
]

# fantasy_compound: first name + evocative surname (combinatorial -> thousands).
_COMPOUND_PREFIX = [
    "Iron", "Stone", "Bone", "Blood", "Storm", "Grim", "Ash", "Fire", "Frost",
    "Steel", "Shadow", "Dread", "War", "Death", "Black", "Red", "Night", "Doom",
    "Skull", "Thorn", "Wolf", "Raven", "Grave", "Hell", "Bane",
]
_COMPOUND_SUFFIX = [
    "crusher", "breaker", "shield", "bane", "forge", "fang", "born", "hammer",
    "reaver", "render", "maw", "hide", "scar", "heart", "fist", "stalker",
    "biter", "cleaver", "render", "grip", "helm", "gaze", "song", "wind",
]

# ---------------------------------------------------------------------------
# UNIQUENESS HELPER
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    """Normalization key for dedupe (case/space-insensitive)."""
    return " ".join(str(name).split()).casefold()


def _roman(n: int) -> str:
    vals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for val, sym in vals:
        while n >= val:
            out += sym
            n -= val
    return out or "I"


def load_existing_names() -> set:
    """Collect names already used by players and AI so generated names stay
    unique across the whole league. Best-effort: never raises."""
    used = set()
    # Player team files
    teams_dir = os.path.join(BASE_DIR, "saves", "teams")
    try:
        for fn in os.listdir(teams_dir):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(teams_dir, fn), "r", encoding="utf-8") as f:
                    td = json.load(f)
            except Exception:
                continue
            for key in ("team_name", "manager_name"):
                if td.get(key):
                    used.add(_norm(td[key]))
            for w in (td.get("warriors") or []):
                if isinstance(w, dict) and w.get("name"):
                    used.add(_norm(w["name"]))
    except Exception:
        pass
    # Managers registry
    try:
        with open(os.path.join(BASE_DIR, "saves", "league", "managers.json"),
                  "r", encoding="utf-8") as f:
            mgrs = json.load(f)
        for m in (mgrs.values() if isinstance(mgrs, dict) else mgrs):
            if isinstance(m, dict) and m.get("manager_name"):
                used.add(_norm(m["manager_name"]))
    except Exception:
        pass
    # Previously-generated AI rosters (so a later generation never reuses a
    # manager/team/warrior name we already handed to an AI in an earlier run).
    for ai_file in ("ai_teams.json", "ai_brain.json"):
        try:
            with open(os.path.join(BASE_DIR, "saves", "league", ai_file),
                      "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for td in (data.values() if isinstance(data, dict) else data):
            if not isinstance(td, dict):
                continue
            for key in ("team_name", "manager_name"):
                if td.get(key):
                    used.add(_norm(td[key]))
            for w in (td.get("warriors") or []):
                if isinstance(w, dict) and w.get("name"):
                    used.add(_norm(w["name"]))
            # Warriors living on in the Elite/Soul Spire are still in the league.
            for w in (td.get("archived_warriors") or []):
                if (isinstance(w, dict) and w.get("name")
                        and (w.get("current_arena") or "normal") in ("elite", "veteran")):
                    used.add(_norm(w["name"]))
    # --- Extra sources: every name a real player has EVER used, so an AI team,
    # manager or warrior can never copy one (even a dead/retired/archived one).
    saves = os.path.join(BASE_DIR, "saves")

    def _add_team(td):
        if not isinstance(td, dict):
            return
        for key in ("team_name", "manager_name"):
            if td.get(key):
                used.add(_norm(td[key]))
        for lst in ("warriors", "fallen_warriors", "archived_warriors"):
            for w in (td.get(lst) or []):
                if isinstance(w, dict) and w.get("name"):
                    used.add(_norm(w["name"]))
                elif isinstance(w, str) and w:
                    used.add(_norm(w))

    # Elite / Soul Spire team files
    for arena in ("elite", "veteran"):
        adir = os.path.join(saves, arena, "teams")
        try:
            for fn in os.listdir(adir):
                if fn.endswith(".json"):
                    try:
                        with open(os.path.join(adir, fn), "r", encoding="utf-8") as f:
                            _add_team(json.load(f))
                    except Exception:
                        pass
        except Exception:
            pass
    # Player team files (dead + archived warriors too)
    try:
        tdir = os.path.join(saves, "teams")
        for fn in os.listdir(tdir):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(tdir, fn), "r", encoding="utf-8") as f:
                        _add_team(json.load(f))
                except Exception:
                    pass
    except Exception:
        pass
    # Standings history (every team/manager/warrior that ever fought)
    for sp in (os.path.join(saves, "league", "standings.json"),
               os.path.join(saves, "elite", "standings.json"),
               os.path.join(saves, "veteran", "standings.json")):
        try:
            with open(sp, "r", encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            continue
        for sd in (st.values() if isinstance(st, dict) else []):
            if not isinstance(sd, dict):
                continue
            for key in ("team_name", "manager_name"):
                if sd.get(key):
                    used.add(_norm(sd[key]))
            ws = sd.get("warriors") or {}
            for w in (ws.values() if isinstance(ws, dict) else ws):
                if isinstance(w, dict) and w.get("name"):
                    used.add(_norm(w["name"]))
    # Graveyard legacy files: "GLADIATOR LEGACY: NAME" / "TEAM: NAME"
    try:
        gdir = os.path.join(saves, "graveyard")
        for fn in os.listdir(gdir):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(gdir, fn), "r", encoding="utf-8", errors="ignore") as f:
                    head = f.read(600)
            except Exception:
                continue
            for line in head.splitlines():
                line = line.strip()
                for tag in ("GLADIATOR LEGACY:", "TEAM:"):
                    if line.startswith(tag):
                        nm = line[len(tag):].strip()
                        if nm:
                            used.add(_norm(nm))
    except Exception:
        pass
    return used


def make_registry(used_names: Optional[Iterable[str]] = None) -> set:
    """Build a shared taken-name set (existing player + AI names, plus any extra
    `used_names`). Scan the save files ONCE, then hand the returned set to every
    NameGenerator you create for a turn via `shared=...`, load_existing=False.
    Names reserved by any generator become visible to all of them."""
    reg = load_existing_names()
    if used_names:
        for n in used_names:
            reg.add(_norm(n))
    return reg


# ---------------------------------------------------------------------------
# GENERATOR
# ---------------------------------------------------------------------------

class NameGenerator:
    """Seeded generator for manager, team, and warrior names.

    Pass a stable `seed` (e.g. hash of manager_id + turn) for reproducible
    output across turn reruns. `used_names` seeds the taken-name set so output
    never collides with existing players/AI.
    """

    def __init__(self, seed=None, used_names: Optional[Iterable[str]] = None,
                 load_existing: bool = True, shared: Optional[set] = None):
        self.rng = random.Random(seed)
        # `shared`, when given, is used BY REFERENCE. Pass the same registry set
        # to several per-manager generators in one turn and every name reserved
        # by any of them is instantly visible to the others -- so warrior names
        # stay globally unique even though each manager keeps its own RNG (and
        # therefore its own reproducible-on-rerun choices). Build the registry
        # once with make_registry() and pass load_existing=False to avoid
        # rescanning the save files for every manager.
        self._used = shared if shared is not None else set()
        # Safe by default: even if the caller forgets to pass used_names, we
        # still refuse to reuse any name already taken by a player or AI.
        if load_existing:
            self._used |= load_existing_names()   # in-place; keeps shared set
        if used_names:
            for n in used_names:
                self._used.add(_norm(n))

    # -- taken-name bookkeeping --------------------------------------------
    def reserve(self, name: str):
        self._used.add(_norm(name))

    def _is_free(self, name: str) -> bool:
        return _norm(name) not in self._used

    def _finalize(self, name: str, pool_for_suffix: Optional[List[str]] = None) -> str:
        """Reserve `name`; if taken, append a Roman-numeral suffix until free."""
        if self._is_free(name):
            self.reserve(name)
            return name
        n = 2
        while True:
            candidate = f"{name} {_roman(n)}"
            if self._is_free(candidate):
                self.reserve(candidate)
                return candidate
            n += 1

    def _draw(self, pool: List[str], tries: int = 12):
        """Random pick from pool preferring an unused entry."""
        for _ in range(tries):
            pick = self.rng.choice(pool)
            if self._is_free(pick):
                return pick
        return self.rng.choice(pool)  # give up; _finalize will suffix it

    def _unique(self, factory, max_tries: int = 30) -> str:
        """Call `factory()` until it yields an unused name, then reserve it.
        Retries produce a genuinely different name before we resort to a
        Roman-numeral suffix, so collisions never leak through."""
        name = None
        for _ in range(max_tries):
            name = factory()
            if self._is_free(name):
                self.reserve(name)
                return name
        # Pools exhausted for this style -> guarantee uniqueness via suffix.
        return self._finalize(name)

    # -- managers -----------------------------------------------------------
    def manager_name(self) -> str:
        return self._unique(self._make_manager)

    def _make_manager(self) -> str:
        family = self.rng.choices(
            ["fantasy", "handle", "persona"], weights=[0.45, 0.25, 0.30])[0]
        if family == "fantasy":
            if self.rng.random() < 0.35:
                return self.rng.choice(_MGR_ARCANE)
            return f"{self.rng.choice(_MGR_FANTASY_ADJ)} {self.rng.choice(_MGR_FANTASY_NOUN)}"
        if family == "handle":
            return self._make_handle()
        return self._make_persona()

    def _make_handle(self) -> str:
        r = self.rng.random()
        word = self.rng.choice(_HANDLE_WORDS)
        if r < 0.30:
            pre = self.rng.choice(_HANDLE_PREFIX)
            return f"{pre}{word}".strip() if pre else word
        if r < 0.55:
            return f"{word}{self.rng.randint(2, 99)}"
        if r < 0.75:
            return self.rng.choice(_HANDLE_LEET)
        # dashed punk style
        return f"-{word}-"

    def _make_persona(self) -> str:
        r = self.rng.random()
        if r < 0.45:
            return f"{self.rng.choice(_PERSONA_FIRST)} {self.rng.choice(_PERSONA_TAG)}"
        if r < 0.80:
            return f"{self.rng.choice(_PERSONA_FIRST)} {self.rng.choice(_PERSONA_SURNAME)}"
        return f"{self.rng.choice(_PERSONA_FIRST)} {self.rng.choice(_PERSONA_FIRST)}"

    # -- teams --------------------------------------------------------------
    def team_identity(self, lens: Optional[str] = None) -> dict:
        """Return {'team_name','lens','motif'} for a coherent team."""
        if lens is None:
            lens = self.rng.choices(
                ["dark", "fantasy", "absurd", "attitude"],
                weights=[0.30, 0.30, 0.25, 0.15])[0]
        team_name = self._unique(lambda: self._draw(_TEAM_POOLS[lens]))
        motif = self.rng.choice(_LENS_MOTIFS[lens])
        return {"team_name": team_name, "lens": lens, "motif": motif}

    # -- warriors -----------------------------------------------------------
    def warrior_names(self, motif: str, count: int = 5) -> List[str]:
        """Generate `count` warrior names sharing the given motif."""
        names = []
        for _ in range(count):
            names.append(self._unique(lambda: self._one_warrior(motif)))
        return names

    def _one_warrior(self, motif: str) -> str:
        if motif == "fantasy_compound":
            first_pool = _FANTASY_FIRST_M + _FANTASY_FIRST_F
            first = self.rng.choice(first_pool)
            surname = self.rng.choice(_COMPOUND_PREFIX) + self.rng.choice(_COMPOUND_SUFFIX)
            # Occasionally drop the first name for a pure epithet handle.
            if self.rng.random() < 0.20:
                return surname.capitalize()
            return f"{first} {surname.capitalize()}"
        if motif == "fantasy_first":
            return self._draw(_FANTASY_FIRST_M + _FANTASY_FIRST_F)
        pool = _MOTIF_STATIC.get(motif)
        if pool:
            return self._draw(pool)
        # Unknown motif -> safe fallback.
        return self._one_warrior("fantasy_compound")


# ---------------------------------------------------------------------------
# ROSTER HELPER
# ---------------------------------------------------------------------------

def generate_roster(count: int, seed=None,
                    used_names: Optional[Iterable[str]] = None) -> List[dict]:
    """Generate a full AI roster in ONE shared pass so every manager, team, and
    warrior name is guaranteed unique -- both against each other and against all
    existing player/AI names. This is the safe way to name the roster: it avoids
    the cross-instance collision that happens if each manager is named by its own
    separately-seeded generator.

    Returns a list of dicts: {manager_name, team_name, lens, motif, warriors}.
    """
    gen = NameGenerator(seed=seed, used_names=used_names)
    roster = []
    for _ in range(count):
        mgr = gen.manager_name()
        ident = gen.team_identity()
        warriors = gen.warrior_names(ident["motif"], 5)
        roster.append({
            "manager_name": mgr,
            "team_name": ident["team_name"],
            "lens": ident["lens"],
            "motif": ident["motif"],
            "warriors": warriors,
        })
    return roster


# ---------------------------------------------------------------------------
# Manual smoke test:  python ai_names.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    existing = load_existing_names()
    print(f"[dedupe] {len(existing)} existing names loaded\n")
    gen = NameGenerator(seed=1234, used_names=existing)
    for i in range(8):
        mgr = gen.manager_name()
        ident = gen.team_identity()
        warriors = gen.warrior_names(ident["motif"], 5)
        print(f"Manager: {mgr}")
        print(f"  Team: {ident['team_name']}  [{ident['lens']} / motif={ident['motif']}]")
        print(f"  Warriors: {', '.join(warriors)}")
        print()
