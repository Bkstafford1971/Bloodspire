#!/usr/bin/env python3
"""
combat_sandbox.py — Head-to-head combat testing sandbox.

Load real warriors from saves, override their weapons / skills / strategies,
and run repeated fights to test weapon viability and race/build interactions.

Run with:  python tools/combat_sandbox.py
"""

import sys
import os
import random
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from bloodspire.core.warrior import Warrior, Strategy, FIGHTING_STYLES, TRIGGERS, AIM_DEFENSE_POINTS
from bloodspire.core.weapons import WEAPONS, get_weapon
from bloodspire.core.armor import ARMOR_PIECES
from bloodspire.core.races import get_race, list_playable_races
from bloodspire.combat.engine import run_fight
from bloodspire.persistence.storage import load_all_teams
from bloodspire.combat import narrative as _N

# ─────────────────────────────────────────────────────────────────────────────
# SCOUT ATTENDANCE LINE CHECKING
# ─────────────────────────────────────────────────────────────────────────────

def _expected_scout_lines(scout_names: list) -> list:
    """All possible rendered scout-attendance lines for this scout list.

    Mirrors narrative's single-vs-multi logic for scout flavor text.
    Returns list of expected lines that should appear in the narrative.
    """
    if not scout_names:
        return []
    if len(scout_names) == 1:
        # Single scout: try to find the flavor template
        try:
            return [t.format(mgr=scout_names[0]) for t in getattr(_N, '_SCOUT_FLAVOR_SINGLE', [])]
        except Exception:
            return [f"scout from {scout_names[0]}'s stable is in attendance"]
    # Multi-scout: generic line without names
    try:
        return list(getattr(_N, '_SCOUT_FLAVOR_MULTI', []))
    except Exception:
        return ["scouts are in attendance"]

# ─────────────────────────────────────────────────────────────────────────────
# DATA SETUP
# ─────────────────────────────────────────────────────────────────────────────

# Core non-weapon skills always shown in the skill editor
CORE_SKILLS = [
    "parry", "dodge", "initiative", "lunge", "feint",
    "slash", "charge", "strike", "sweep", "throw", "brawl", "disarm",
    "cleave", "bash", "acrobatics", "riposte",
]

WEAPON_DISPLAY_NAMES = sorted(
    w.display for w in WEAPONS.values() if w.skill_key != "open_hand"
) + ["Open Hand"]

ARMOR_NAMES   = [k for k in ARMOR_PIECES if "Cap" not in k and "Helm" not in k
                 and k not in ("Camail", "Full Helm", "None")]
HELM_NAMES    = [k for k in ARMOR_PIECES if k not in ARMOR_NAMES] + ["None"]
RACE_NAMES    = sorted(list_playable_races())
ALL_STYLES    = FIGHTING_STYLES
ALL_TRIGGERS  = TRIGGERS
ALL_AIM       = AIM_DEFENSE_POINTS


def _load_all_warriors():
    """Load every living warrior from all team saves, return sorted list."""
    try:
        teams = load_all_teams()
    except Exception:
        return []
    warriors = []
    for team in teams:
        pool = team.warriors.values() if isinstance(team.warriors, dict) else team.warriors
        for w in pool:
            if w and hasattr(w, "name") and not getattr(w, "is_dead", False):
                warriors.append(w)
    warriors.sort(key=lambda w: w.name)
    return warriors


def _weapon_skill_key(display_name: str) -> str:
    """Convert display name to the skill key combat uses (snake_case of display)."""
    return display_name.lower().replace(" ", "_").replace("&", "and").replace("'", "")


# ─────────────────────────────────────────────────────────────────────────────
# FIGHTER PANEL
# ─────────────────────────────────────────────────────────────────────────────

class FighterPanel(ttk.LabelFrame):
    """One fighter's configuration — left or right side of the sandbox."""

    def __init__(self, parent, label: str, all_warriors: list, **kwargs):
        super().__init__(parent, text=label, padding=8, **kwargs)
        self._all_warriors = all_warriors
        self._warrior_map  = {w.name: w for w in all_warriors}
        self._skill_vars   = {}   # skill_name -> IntVar
        self._strat_vars   = []   # list of dicts per strategy row

        self._build()

    # ── BUILD UI ─────────────────────────────────────────────────────────────

    def _build(self):
        # ── Warrior selector ──────────────────────────────────────────────
        sel_frame = ttk.Frame(self)
        sel_frame.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(sel_frame, text="Warrior:").pack(side=tk.LEFT)
        self._warrior_var = tk.StringVar()
        names = [w.name for w in self._all_warriors]
        self._warrior_cb = ttk.Combobox(sel_frame, textvariable=self._warrior_var,
                                         values=names, state="readonly", width=28)
        self._warrior_cb.pack(side=tk.LEFT, padx=4)
        self._warrior_cb.bind("<<ComboboxSelected>>", self._on_warrior_selected)

        self._info_var = tk.StringVar(value="(no warrior loaded)")
        ttk.Label(sel_frame, textvariable=self._info_var, foreground="#555").pack(side=tk.LEFT, padx=6)

        # ── Gear overrides ────────────────────────────────────────────────
        gear_frame = ttk.LabelFrame(self, text="Gear Overrides", padding=6)
        gear_frame.pack(fill=tk.X, pady=4)

        for row_label, attr, options, width in [
            ("Primary Weapon:",   "_primary_var",   WEAPON_DISPLAY_NAMES, 26),
            ("Secondary Weapon:", "_secondary_var",  ["Open Hand"] + WEAPON_DISPLAY_NAMES, 26),
            ("Armor:",            "_armor_var",      ARMOR_NAMES,          18),
            ("Helm:",             "_helm_var",       HELM_NAMES,           18),
        ]:
            r = ttk.Frame(gear_frame)
            r.pack(fill=tk.X, pady=1)
            ttk.Label(r, text=row_label, width=18, anchor="e").pack(side=tk.LEFT)
            var = tk.StringVar()
            setattr(self, attr, var)
            cb = ttk.Combobox(r, textvariable=var, values=options, state="readonly", width=width)
            cb.pack(side=tk.LEFT, padx=4)

        # Bind primary weapon change so weapon skill label updates
        self._primary_var.trace_add("write", self._on_weapon_changed)

        # Race override
        r = ttk.Frame(gear_frame)
        r.pack(fill=tk.X, pady=1)
        ttk.Label(r, text="Race:", width=18, anchor="e").pack(side=tk.LEFT)
        self._race_var = tk.StringVar()
        ttk.Combobox(r, textvariable=self._race_var, values=RACE_NAMES,
                     state="readonly", width=14).pack(side=tk.LEFT, padx=4)
        ttk.Label(r, text="(changes HP & racial traits)", foreground="#888",
                  font=("Arial", 8)).pack(side=tk.LEFT)

        # ── Strategies ───────────────────────────────────────────────────
        strat_frame = ttk.LabelFrame(self, text="Strategies (up to 6)", padding=6)
        strat_frame.pack(fill=tk.X, pady=4)

        hdr = ttk.Frame(strat_frame)
        hdr.pack(fill=tk.X)
        for col, w in [("Trigger", 16), ("Style", 20), ("Act", 4), ("Aim Point", 14)]:
            ttk.Label(hdr, text=col, width=w, anchor="w",
                      font=("Arial", 8, "bold")).pack(side=tk.LEFT, padx=2)

        self._strat_vars = []
        for _ in range(6):
            row = ttk.Frame(strat_frame)
            row.pack(fill=tk.X, pady=1)
            tv = tk.StringVar(value="None")
            sv = tk.StringVar(value="Strike")
            av = tk.IntVar(value=5)
            aiv = tk.StringVar(value="Chest")
            ttk.Combobox(row, textvariable=tv, values=ALL_TRIGGERS,
                         state="readonly", width=14).pack(side=tk.LEFT, padx=2)
            ttk.Combobox(row, textvariable=sv, values=ALL_STYLES,
                         state="readonly", width=18).pack(side=tk.LEFT, padx=2)
            ttk.Spinbox(row, from_=1, to=10, textvariable=av, width=3).pack(side=tk.LEFT, padx=2)
            ttk.Combobox(row, textvariable=aiv, values=ALL_AIM,
                         state="readonly", width=12).pack(side=tk.LEFT, padx=2)
            self._strat_vars.append({"trigger": tv, "style": sv, "activity": av, "aim": aiv})

        # ── Skills ───────────────────────────────────────────────────────
        skill_outer = ttk.LabelFrame(self, text="Skill Overrides  (0 = use warrior's real value)", padding=6)
        skill_outer.pack(fill=tk.BOTH, expand=True, pady=4)

        # Weapon skill row (label changes with weapon selection)
        self._wpn_skill_label = tk.StringVar(value="Weapon Skill:")
        wpn_row = ttk.Frame(skill_outer)
        wpn_row.pack(fill=tk.X, pady=1)
        ttk.Label(wpn_row, textvariable=self._wpn_skill_label, width=20, anchor="e",
                  font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        self._wpn_skill_var = tk.IntVar(value=0)
        ttk.Spinbox(wpn_row, from_=0, to=9, textvariable=self._wpn_skill_var,
                    width=3).pack(side=tk.LEFT, padx=4)
        ttk.Label(wpn_row, text="(0 = warrior's actual value)", foreground="#888",
                  font=("Arial", 8)).pack(side=tk.LEFT)

        # Core non-weapon skills in a 2-column grid
        grid = ttk.Frame(skill_outer)
        grid.pack(fill=tk.X, pady=2)
        self._skill_vars = {}
        for i, skill in enumerate(CORE_SKILLS):
            col = i % 2
            row_n = i // 2
            ttk.Label(grid, text=f"{skill}:", width=12, anchor="e").grid(
                row=row_n, column=col * 2, sticky="e", padx=(4, 0))
            var = tk.IntVar(value=0)
            self._skill_vars[skill] = var
            ttk.Spinbox(grid, from_=0, to=9, textvariable=var,
                        width=3).grid(row=row_n, column=col * 2 + 1, padx=(2, 8))

        # Reset button
        ttk.Button(skill_outer, text="Reset skills to warrior's actual values",
                   command=self._reset_skills).pack(anchor="w", pady=(4, 0))

    # ── EVENTS ───────────────────────────────────────────────────────────────

    def _on_warrior_selected(self, _event=None):
        name = self._warrior_var.get()
        w = self._warrior_map.get(name)
        if not w:
            return
        race_name = w.race.name if hasattr(w.race, "name") else str(w.race)
        self._info_var.set(
            f"{race_name}  |  {w.wins}W-{w.losses}L  |  HP {w.max_hp}  |  {w.primary_weapon}"
        )
        # Populate gear
        self._primary_var.set(w.primary_weapon)
        self._secondary_var.set(w.secondary_weapon or "Open Hand")
        self._armor_var.set(w.armor or "Leather")
        self._helm_var.set(w.helm or "None")
        self._race_var.set(race_name)

        # Populate strategies
        strats = w.strategies if hasattr(w, "strategies") and w.strategies else []
        for i, sv in enumerate(self._strat_vars):
            if i < len(strats):
                s = strats[i]
                sv["trigger"].set(getattr(s, "trigger", "None"))
                sv["style"].set(getattr(s, "style", "Strike"))
                sv["activity"].set(getattr(s, "activity", 5))
                sv["aim"].set(getattr(s, "aim_point", "Chest"))
            else:
                sv["trigger"].set("None")
                sv["style"].set("Strike")
                sv["activity"].set(5)
                sv["aim"].set("Chest")

        self._reset_skills()

    def _on_weapon_changed(self, *_args):
        wpn_display = self._primary_var.get()
        try:
            wpn = get_weapon(wpn_display)
            label = f"{wpn.display} Skill:"
        except Exception:
            label = "Weapon Skill:"
        self._wpn_skill_label.set(label)

    def _reset_skills(self):
        """Populate skill spinboxes from the currently selected warrior's real values."""
        name = self._warrior_var.get()
        w = self._warrior_map.get(name)
        if not w:
            for var in self._skill_vars.values():
                var.set(0)
            self._wpn_skill_var.set(0)
            return
        for skill, var in self._skill_vars.items():
            var.set(w.skills.get(skill, 0))
        # Weapon skill: use skill_key derived from selected weapon, fallback to primary_weapon
        wpn_display = self._primary_var.get() or w.primary_weapon
        try:
            wpn_obj = get_weapon(wpn_display)
            val = w.skills.get(wpn_obj.skill_key, 0)
        except Exception:
            val = 0
        self._wpn_skill_var.set(val)

    # ── BUILD WARRIOR ─────────────────────────────────────────────────────────

    def build_warrior(self) -> Warrior:
        """
        Return a deep copy of the selected warrior with all overrides applied.
        Raises ValueError if no warrior is selected.
        """
        name = self._warrior_var.get()
        if not name:
            raise ValueError("No warrior selected")
        w = deepcopy(self._warrior_map[name])

        # Gear overrides
        primary_display = self._primary_var.get()
        w.primary_weapon   = primary_display
        w.secondary_weapon = self._secondary_var.get()
        w.armor            = self._armor_var.get()
        w.helm             = self._helm_var.get()

        # Race override (recompute HP if changed)
        race_name = self._race_var.get()
        if race_name and race_name != w.race.name:
            w.race = get_race(race_name)
            # Recompute max_hp using the new race modifier
            base_hp = w.constitution * 3 + w.size
            hp_mod  = getattr(w.race.modifiers, "hp_modifier", 0) if hasattr(w.race, "modifiers") else 0
            w.max_hp = max(1, base_hp + hp_mod)

        # Strategies — use rows where trigger is not "None" or where style differs from default
        strats = []
        for sv in self._strat_vars:
            trigger = sv["trigger"].get()
            style   = sv["style"].get()
            act     = sv["activity"].get()
            aim     = sv["aim"].get()
            strats.append(Strategy(
                trigger=trigger, style=style, activity=act,
                aim_point=aim, defense_point="Chest",
            ))
        w.strategies = strats

        # Skill overrides — only apply non-zero values (0 means "keep warrior's real value")
        for skill, var in self._skill_vars.items():
            val = var.get()
            if val > 0:
                w.skills[skill] = val

        # Weapon skill override
        wpn_skill_val = self._wpn_skill_var.get()
        if wpn_skill_val > 0:
            # Apply under both the skill_key and the display-name key (in case combat uses either)
            try:
                wpn_obj = get_weapon(primary_display)
                w.skills[wpn_obj.skill_key] = wpn_skill_val
            except Exception:
                pass
            display_key = _weapon_skill_key(primary_display)
            w.skills[display_key] = wpn_skill_val

        return w


# ─────────────────────────────────────────────────────────────────────────────
# RESULTS PANEL
# ─────────────────────────────────────────────────────────────────────────────

class ResultsPanel(ttk.LabelFrame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, text="Results", padding=8, **kwargs)
        self._build()

    def _build(self):
        # Summary stats row
        self._summary_var = tk.StringVar(value="Run a fight to see results.")
        ttk.Label(self, textvariable=self._summary_var, font=("Consolas", 10),
                  justify="left").pack(anchor="w", pady=(0, 4))

        # Event counts
        self._events_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._events_var, font=("Consolas", 9),
                  foreground="#335", justify="left").pack(anchor="w", pady=(0, 4))

        # Scout attendance line check
        self._scout_status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._scout_status_var, font=("Consolas", 9, "bold"),
                  foreground="#060", justify="left").pack(anchor="w", pady=(0, 4))

        # Narrative (last fight)
        ttk.Label(self, text="Last fight narrative:", font=("Arial", 9, "bold")).pack(anchor="w")
        self._narrative = scrolledtext.ScrolledText(self, height=22, font=("Consolas", 8),
                                                     wrap=tk.WORD, state="disabled")
        self._narrative.pack(fill=tk.BOTH, expand=True)

    def update(self, stats: dict, narrative: str):
        fa = stats["name_a"]
        fb = stats["name_b"]
        n  = stats["fights"]
        wa = stats["wins_a"]
        wb = stats["wins_b"]
        avg_min   = stats["total_min"] / n if n else 0
        avg_hp_w  = stats["winner_hp_sum"] / n if n else 0
        kills     = stats["kills"]

        self._summary_var.set(
            f"Fights: {n}   |   "
            f"{fa}: {wa} wins ({wa/n*100:.0f}%)   "
            f"{fb}: {wb} wins ({wb/n*100:.0f}%)   "
            f"|   Avg duration: {avg_min:.1f} min   "
            f"|   Deaths: {kills} ({kills/n*100:.0f}%)"
            f"   |   Avg winner HP remaining: {avg_hp_w:.0f}%"
        )

        ev = stats["events"]
        parts = []
        for key, label in [("trips","Trips"), ("wraps","Arm-wraps"), ("bleeds","Bleeds"),
                            ("disarms","Disarms"), ("knockdowns","Knockdowns")]:
            if ev.get(key, 0):
                parts.append(f"{label}: {ev[key]} ({ev[key]/n:.1f}/fight)")
        self._events_var.set("Events: " + ("  |  ".join(parts) if parts else "none recorded"))

        # Scout attendance check
        scout_names = stats.get("scout_names", [])
        if scout_names:
            seen = stats.get("scout_line_seen", False)
            status = "✓ SEEN (last fight)" if seen else "✗ NOT SEEN - check narrative below"
            mode = "single-scout line expected" if len(scout_names) == 1 else "multi-scout line expected (no names)"
            self._scout_status_var.set(
                f"Scout check ({', '.join(scout_names)} - {mode}): {status}"
            )
        else:
            self._scout_status_var.set("Scout check: no manager entered - scout line not tested")

        self._narrative.config(state="normal")
        self._narrative.delete("1.0", tk.END)
        self._narrative.insert(tk.END, narrative or "(no narrative)")
        self._narrative.config(state="disabled")
        self._narrative.see("1.0")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────────────────────────────────────

class CombatSandbox:
    def __init__(self, root):
        self.root = root
        self.root.title("Combat Sandbox — Head-to-Head Weapon & Warrior Testing")
        self.root.geometry("1600x950")
        self.root.minsize(1200, 700)

        self._all_warriors = _load_all_warriors()
        if not self._all_warriors:
            messagebox.showerror("No Warriors", "Could not load any warriors from saves.")
            root.destroy()
            return

        self._last_narrative = ""
        self._build()

    def _build(self):
        # ── Title ─────────────────────────────────────────────────────────
        title_frame = ttk.Frame(self.root)
        title_frame.pack(fill=tk.X, padx=10, pady=(6, 2))
        ttk.Label(title_frame,
                  text=f"Combat Sandbox  ({len(self._all_warriors)} warriors loaded)",
                  font=("Arial", 13, "bold")).pack(side=tk.LEFT)
        ttk.Label(title_frame,
                  text="Select two warriors, adjust gear & skills, then run fights.",
                  font=("Arial", 10), foreground="#555").pack(side=tk.LEFT, padx=12)

        # ── Fight controls toolbar (always visible, fixed above the panes) ──
        ctrl_frame = ttk.Frame(self.root, relief="ridge", borderwidth=1)
        ctrl_frame.pack(fill=tk.X, padx=10, pady=(0, 4))

        ttk.Label(ctrl_frame, text="Run:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=4)
        for n in [1, 5, 10, 25, 50, 100]:
            ttk.Button(ctrl_frame, text=f"{n} fight{'s' if n > 1 else ''}",
                       command=lambda n=n: self._run(n),
                       width=10).pack(side=tk.LEFT, padx=3, pady=4)

        ttk.Separator(ctrl_frame, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=4)

        self._seed_var = tk.IntVar(value=0)
        ttk.Label(ctrl_frame, text="RNG seed (0=random):").pack(side=tk.LEFT)
        ttk.Spinbox(ctrl_frame, from_=0, to=99999, textvariable=self._seed_var,
                    width=7).pack(side=tk.LEFT, padx=4)

        ttk.Separator(ctrl_frame, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=4)

        ttk.Label(ctrl_frame, text="Scouted by (comma-separated managers, blank = none):").pack(side=tk.LEFT)
        self._scout_var = tk.StringVar(value="")
        ttk.Entry(ctrl_frame, textvariable=self._scout_var, width=32).pack(side=tk.LEFT, padx=4)

        self._status_var = tk.StringVar(value="")
        ttk.Label(ctrl_frame, textvariable=self._status_var,
                  foreground="#226", font=("Arial", 9)).pack(side=tk.LEFT, padx=10)

        # ── Vertical pane: fighters on top, results on bottom ─────────────
        vpane = tk.PanedWindow(self.root, orient=tk.VERTICAL,
                               sashwidth=6, sashrelief=tk.RAISED,
                               sashpad=2, background="#cccccc")
        vpane.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        # Top pane holds both fighter panels
        top_pane = ttk.Frame(vpane)
        vpane.add(top_pane, minsize=200, stretch="never")

        # ── Main columns ──────────────────────────────────────────────────
        col_frame = ttk.Frame(top_pane)
        col_frame.pack(fill=tk.BOTH, expand=True)

        self._panel_a = FighterPanel(col_frame, "Fighter A", self._all_warriors)
        self._panel_a.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        self._panel_b = FighterPanel(col_frame, "Fighter B", self._all_warriors)
        self._panel_b.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))

        # ── Results (bottom pane — drag the sash up to expand) ────────────
        self._results = ResultsPanel(vpane)
        vpane.add(self._results, minsize=120, stretch="always")

    # ── FIGHT RUNNER ──────────────────────────────────────────────────────────

    def _run(self, n_fights: int):
        try:
            wa = self._panel_a.build_warrior()
            wb = self._panel_b.build_warrior()
        except ValueError as e:
            messagebox.showerror("Configuration Error", str(e))
            return

        seed = self._seed_var.get()
        if seed:
            random.seed(seed)

        scout_names = [s.strip() for s in self._scout_var.get().split(",") if s.strip()]
        stats = {
            "name_a": wa.name, "name_b": wb.name,
            "fights": n_fights, "wins_a": 0, "wins_b": 0,
            "total_min": 0, "kills": 0, "winner_hp_sum": 0.0,
            "events": {"trips": 0, "wraps": 0, "bleeds": 0, "disarms": 0, "knockdowns": 0},
            "scout_names": scout_names, "scout_line_seen": False,
        }
        last_narrative = ""

        for i in range(n_fights):
            self._status_var.set(f"Running fight {i+1}/{n_fights}…")
            self.root.update_idletasks()

            a = deepcopy(wa)
            b = deepcopy(wb)
            scouting_info = {"scouts": scout_names} if scout_names else None
            try:
                result = run_fight(
                    a, b,
                    team_a_name=getattr(a, "team_name", "Fighter A"),
                    team_b_name=getattr(b, "team_name", "Fighter B"),
                    manager_a_name="Sandbox",
                    manager_b_name="Sandbox",
                    scouting_info=scouting_info,
                )
            except Exception as ex:
                messagebox.showerror("Fight Error", f"Fight {i+1} crashed:\n{ex}")
                break

            stats["total_min"] += result.minutes_elapsed or 0
            if result.loser_died:
                stats["kills"] += 1
            if result.winner:
                stats["wins_a" if result.winner.name == wa.name else "wins_b"] += 1
                hp_pct = result.winner_hp_pct * 100
                stats["winner_hp_sum"] += hp_pct

            n = (result.narrative or "").lower()
            ev = stats["events"]
            ev["trips"]      += n.count("wraps around") + n.count("tangles") + n.count("drags them to the ground")
            ev["wraps"]      += n.count("rakes across")
            ev["bleeds"]     += n.count("bleeding")
            ev["disarms"]    += n.count("weapon clatters") + n.count("disarmed") + n.count("weapon falls")
            ev["knockdowns"] += n.count("knocked to the ground") + n.count("hits the ground hard")

            # Check for scout attendance line
            if scouting_info:
                expected = _expected_scout_lines(scouting_info["scouts"])
                if any(line.lower() in n for line in expected):
                    stats["scout_line_seen"] = True

            last_narrative = result.narrative or ""

        self._status_var.set(f"Done. ({n_fights} fights)")
        self._results.update(stats, last_narrative)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    CombatSandbox(root)
    root.mainloop()


if __name__ == "__main__":
    main()
