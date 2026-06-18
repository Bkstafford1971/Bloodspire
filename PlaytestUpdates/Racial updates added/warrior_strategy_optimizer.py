#!/usr/bin/env python3
# =============================================================================
# warrior_strategy_optimizer.py - Warrior Strategy Optimization Tool
# =============================================================================
# Tkinter GUI for analyzing warriors and recommending optimal strategies
# based on attributes, skills, race, and equipment.
# Enhanced with:
# - Style bonuses display
# - Turn snapshot selection
# - Weapon recommendations
# =============================================================================

import tkinter as tk
from tkinter import ttk, filedialog
import os
import json
from typing import List, Dict, Optional, Tuple
import math
import re

from warrior import Warrior, Strategy, ALL_SKILLS
from team import Team
from races import get_race, list_playable_races
from weapons import get_weapon, WEAPONS
from armor import ARMOR_PIECES
from strategy import AGGRESSIVE_STYLES, TACTICAL_STYLES


# ---------------------------------------------------------------------------
# STRATEGY RECOMMENDATION ENGINE
# ---------------------------------------------------------------------------

class StrategyOptimizer:
    """Analyzes warrior and recommends optimal strategies."""

    def __init__(self, warrior: Warrior):
        self.warrior = warrior
        self.race = warrior.race

    def get_attribute_scores(self) -> Dict[str, float]:
        """Score attributes 0-100."""
        w = self.warrior

        def norm_score(val: int) -> float:
            if val <= 6:
                return 0.0
            elif val <= 12:
                return (val - 6) * 6.67
            elif val <= 18:
                return 40 + (val - 12) * 6.67
            else:
                return 80 + (val - 18) * 7.5

        return {
            "STR": norm_score(w.strength),
            "DEX": norm_score(w.dexterity),
            "CON": norm_score(w.constitution),
            "INT": norm_score(w.intelligence),
            "PRE": norm_score(w.presence),
            "SIZ": norm_score(w.size),
        }

    def get_dominant_attribute(self) -> tuple:
        """Return (attribute_name, score)."""
        scores = self.get_attribute_scores()
        return max(scores.items(), key=lambda x: x[1])

    def recommend_default_style(self) -> tuple:
        """Recommend default fighting style. Returns (style, reason)."""
        w = self.warrior

        if w.strength >= 15 and w.dexterity <= 12:
            return ("Total Kill", "High STR, low DEX → raw power")
        elif w.strength >= 14:
            return ("Wall of Steel", "Strong STR → reliable defense")
        elif w.dexterity >= 15 and w.strength <= 12:
            return ("Parry", "High DEX, low STR → defense-focused")
        elif w.dexterity >= 14:
            return ("Calculated Attack", "Good DEX → precision strikes")
        elif w.intelligence >= 14:
            return ("Sure Strike", "High INT → strategic")
        elif w.presence >= 14:
            return ("Engage & Withdraw", "High PRE → tactical")
        elif w.constitution >= 14:
            return ("Defend", "Good CON → tank style")
        else:
            return ("Strike", "Balanced approach")

    def recommend_activity(self) -> tuple:
        """Recommend activity level 0-9. Returns (activity, reason)."""
        w = self.warrior
        base = min(9, max(0, (w.dexterity - 6) // 2))

        if w.constitution >= 15:
            activity = min(9, base + 1)
            reason = f"DEX-based {base} + CON bonus"
        elif w.constitution <= 8:
            activity = max(0, base - 1)
            reason = f"DEX-based {base} - CON penalty"
        else:
            activity = base
            reason = f"DEX-based (CON neutral)"

        return (activity, reason)

    def get_style_bonuses(self, style: str) -> Dict[str, str]:
        """Return bonuses for a given fighting style."""
        w = self.warrior
        bonuses = {}

        # AGGRESSIVE STYLES
        if style == "Total Kill":
            bonuses["Damage"] = "+3"
            bonuses["Attack Rate"] = "+2"
            bonuses["Defense"] = "-1"
            bonuses["Best for"] = "High STR"

        elif style == "Wall of Steel":
            bonuses["Damage"] = "+2"
            bonuses["Parry"] = "+1"
            bonuses["Attack Rate"] = "+1"
            bonuses["Best for"] = "STR + DEX"

        elif style == "Lunge":
            bonuses["Damage"] = "+1"
            bonuses["Attack Rate"] = "+3"
            bonuses["Initiative"] = "+2"
            bonuses["Best for"] = "High DEX"

        elif style == "Bash":
            bonuses["Damage"] = "+2"
            bonuses["Knockdown"] = "+2"
            bonuses["Defense"] = "-1"
            bonuses["Best for"] = "High STR"

        elif style == "Slash":
            bonuses["Damage"] = "+2"
            bonuses["Attack Rate"] = "+1"
            bonuses["Best for"] = "STR + DEX"

        elif style == "Strike":
            bonuses["Damage"] = "+1"
            bonuses["Attack Rate"] = "+1"
            bonuses["Accuracy"] = "+1"
            bonuses["Best for"] = "Balanced"

        elif style == "Martial Combat":
            bonuses["Damage"] = "+2"
            bonuses["Attack Rate"] = "+1"
            bonuses["Unarmed Bonus"] = "Yes"
            bonuses["Best for"] = "Martial skill training"

        # TACTICAL STYLES
        elif style == "Parry":
            bonuses["Parry"] = "+3"
            bonuses["Dodge"] = "+1"
            bonuses["Damage"] = "-1"
            bonuses["Best for"] = "High DEX"

        elif style == "Defend":
            bonuses["Parry"] = "+2"
            bonuses["Armor Effectiveness"] = "+1"
            bonuses["Damage"] = "-2"
            bonuses["Best for"] = "High CON"

        elif style == "Sure Strike":
            bonuses["Accuracy"] = "+2"
            bonuses["Damage"] = "+1"
            bonuses["Attack Rate"] = "0"
            bonuses["Best for"] = "High INT"

        elif style == "Calculated Attack":
            bonuses["Damage"] = "+1"
            bonuses["Accuracy"] = "+2"
            bonuses["Initiative"] = "+1"
            bonuses["Best for"] = "High INT + DEX"

        elif style == "Counterstrike":
            bonuses["Parry"] = "+2"
            bonuses["Riposte Chance"] = "+2"
            bonuses["Damage (counter)"] = "+2"
            bonuses["Best for"] = "Defensive fighter"

        elif style == "Engage & Withdraw":
            bonuses["Initiative"] = "+2"
            bonuses["Dodge"] = "+1"
            bonuses["Damage"] = "-1"
            bonuses["Best for"] = "High PRE + DEX"

        elif style == "Decoy":
            bonuses["Dodge"] = "+2"
            bonuses["Initiative"] = "+1"
            bonuses["Damage"] = "0"
            bonuses["Best for"] = "High DEX, hit & run"

        elif style == "Opportunity Throw":
            bonuses["Thrown Damage"] = "+2"
            bonuses["Attack Rate"] = "+1"
            bonuses["Requires"] = "Throwable weapons"
            bonuses["Best for"] = "Ranged attacks"

        return bonuses

    def recommend_weapons(self) -> List[Tuple[str, str]]:
        """Recommend weapons based on warrior attributes and skills."""
        w = self.warrior
        recommendations = []

        # Weapon skill levels
        skill_levels = {skill.replace("_", " ").title(): level for skill, level in w.skills.items() if level > 0}

        # Heavy weapons (STR >= 14)
        if w.strength >= 14:
            recommendations.append(("Two-Handed Sword", "High STR → heavy weapon damage"))
            recommendations.append(("Great Axe", "High STR → massive damage"))

        # Medium weapons (STR >= 12)
        if w.strength >= 12:
            recommendations.append(("War Flail", "Good STR → control"))
            recommendations.append(("Longsword", "Balanced STR/DEX → versatile"))

        # Fast weapons (DEX >= 14)
        if w.dexterity >= 14:
            recommendations.append(("Rapier", "High DEX → precision"))
            recommendations.append(("Dual Daggers", "High DEX → fast attacks"))

        # Light/finesse (DEX >= 12)
        if w.dexterity >= 12:
            recommendations.append(("Short Sword", "Good DEX → quick strikes"))
            recommendations.append(("Scimitar", "Good DEX → slashing"))

        # Ranged (if training thrown)
        if "Opportunity Throw" in skill_levels:
            level = skill_levels["Opportunity Throw"]
            if level >= 5:
                recommendations.append(("Throwing Knife", f"Throw skill {level}/9"))

        # Spear/Pike (versatile)
        if w.strength >= 13 and w.dexterity >= 12:
            recommendations.append(("Spear", "Balanced → charge attacks"))

        # Martial (no weapon)
        if "Martial Combat" in skill_levels:
            level = skill_levels["Martial Combat"]
            recommendations.append(("Open Hand", f"Martial skill {level}/9"))

        # Default if no match
        if not recommendations:
            recommendations.append(("Short Sword", "Balanced default"))
            recommendations.append(("Open Hand", "Unarmed fallback"))

        return recommendations

    def recommend_strategies(self) -> List[Dict]:
        """Generate strategy recommendations for all triggers."""
        w = self.warrior
        default_style, _ = self.recommend_default_style()
        default_activity, _ = self.recommend_activity()

        strategies = []

        # 1. Always (default)
        strategies.append({
            "trigger": "Always (default loop)",
            "style": default_style,
            "activity": default_activity,
            "reason": f"Default: {default_style} at activity {default_activity}",
            "bonuses": self.get_style_bonuses(default_style),
        })

        # 2. Very tired
        if w.dexterity >= 13:
            tired_style = "Parry"
        elif w.constitution >= 13:
            tired_style = "Defend"
        else:
            tired_style = "Sure Strike"

        tired_activity = max(1, default_activity - 2)
        strategies.append({
            "trigger": "You are very tired",
            "style": tired_style,
            "activity": tired_activity,
            "reason": f"Conserve endurance: {tired_style}, reduce activity",
            "bonuses": self.get_style_bonuses(tired_style),
        })

        # 3. Heavy damage
        if w.constitution >= 14:
            damage_style = "Defend"
            damage_activity = default_activity
        elif w.dexterity >= 14:
            damage_style = "Parry"
            damage_activity = default_activity + 1
        else:
            damage_style = "Total Kill"
            damage_activity = min(9, default_activity + 1)

        strategies.append({
            "trigger": "You have taken heavy damage",
            "style": damage_style,
            "activity": damage_activity,
            "reason": f"Change momentum: {damage_style}",
            "bonuses": self.get_style_bonuses(damage_style),
        })

        # 4. Foe very tired
        if w.strength >= 14:
            foe_style = "Total Kill"
        elif w.dexterity >= 14:
            foe_style = "Lunge"
        else:
            foe_style = "Strike"

        foe_activity = min(9, default_activity + 2)
        strategies.append({
            "trigger": "Your foe is very tired",
            "style": foe_style,
            "activity": foe_activity,
            "reason": f"Press advantage: {foe_style}, high activity",
            "bonuses": self.get_style_bonuses(foe_style),
        })

        # 5. Foe heavy damage
        if w.dexterity >= 14:
            foe_dmg_style = "Calculated Attack"
        else:
            foe_dmg_style = default_style

        strategies.append({
            "trigger": "Your foe has taken heavy damage",
            "style": foe_dmg_style,
            "activity": default_activity,
            "reason": f"Finish carefully: {foe_dmg_style}",
            "bonuses": self.get_style_bonuses(foe_dmg_style),
        })

        return strategies


# ---------------------------------------------------------------------------
# TKINTER GUI
# ---------------------------------------------------------------------------

class WarriorStrategyOptimizer:
    def __init__(self, root):
        self.root = root
        self.root.title("Warrior Strategy Optimizer")
        self.root.geometry("1400x900")

        self.warrior_pool: List[Warrior] = []
        self.selected_warrior: Optional[Warrior] = None
        self.optimizer: Optional[StrategyOptimizer] = None
        self.turn_snapshots: Dict[str, List[Warrior]] = {}  # turn_name -> warriors
        self.current_turn: Optional[str] = None
        self.base_folder: str = os.path.join(os.getcwd(), "saves")  # Default to saves folder

        # Initialize UI first
        self.build_ui()

        # Then load turns from default folder
        self.root.after(100, self.load_turn_snapshots)

    def build_ui(self):
        """Build the tkinter UI."""

        # --- HEADER SECTION ---
        header_frame = ttk.Frame(self.root)
        header_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        ttk.Label(header_frame, text="Arena Data Source (load real warriors from save files)",
                 font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=5)

        # --- FOLDER SELECTION SECTION ---
        folder_frame = ttk.Frame(self.root)
        folder_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        ttk.Label(folder_frame, text="Save Folder:").pack(side=tk.LEFT, padx=5)
        self.folder_var = tk.StringVar(value=self.base_folder)
        ttk.Entry(folder_frame, textvariable=self.folder_var, width=60).pack(
            side=tk.LEFT, padx=5, fill=tk.X, expand=True
        )
        ttk.Button(folder_frame, text="Browse", command=self.browse_folder).pack(
            side=tk.LEFT, padx=5
        )

        # --- TURN SNAPSHOT SECTION ---
        turn_frame = ttk.Frame(self.root)
        turn_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        ttk.Label(turn_frame, text="Turn Snapshot:").pack(side=tk.LEFT, padx=5)
        self.turn_var = tk.StringVar()
        self.turn_combo = ttk.Combobox(
            turn_frame, textvariable=self.turn_var, width=25, state="readonly"
        )
        self.turn_combo.pack(side=tk.LEFT, padx=5)

        ttk.Button(turn_frame, text="Load Arena Warriors", command=self.load_turn_warriors).pack(
            side=tk.LEFT, padx=5
        )

        # --- WARRIOR SELECTION SECTION ---
        warrior_frame = ttk.Frame(self.root)
        warrior_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        ttk.Label(warrior_frame, text="Select Warrior:").pack(side=tk.LEFT, padx=5)
        self.warrior_var = tk.StringVar()
        self.warrior_combo = ttk.Combobox(
            warrior_frame, textvariable=self.warrior_var, width=50, state="readonly"
        )
        self.warrior_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.warrior_combo.bind("<<ComboboxSelected>>", lambda e: self.on_warrior_selected())

        ttk.Button(warrior_frame, text="Analyze", command=self.analyze_warrior).pack(
            side=tk.LEFT, padx=5
        )

        # --- STATUS LABEL ---
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN).pack(
            side=tk.BOTTOM, fill=tk.X
        )

        # --- MAIN CONTENT: Paned window ---
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # --- LEFT PANEL: Warrior Info ---
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=1)

        ttk.Label(left_frame, text="Warrior Analysis", font=("Arial", 12, "bold")).pack(
            anchor=tk.W, pady=5
        )

        # Scrolled text for warrior info
        self.info_text = tk.Text(left_frame, width=40, height=30, wrap=tk.WORD)
        info_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.info_text.yview)
        self.info_text.config(yscrollcommand=info_scroll.set)

        self.info_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        info_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # --- RIGHT PANEL: Strategy Recommendations ---
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        ttk.Label(
            right_frame, text="Recommended Strategies", font=("Arial", 12, "bold")
        ).pack(anchor=tk.W, pady=5)

        # Scrolled frame for strategies
        canvas = tk.Canvas(right_frame)
        scrollbar = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        self.strategies_frame = scrollable_frame

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def browse_folder(self):
        """Open folder browser to select teams folder."""
        folder = filedialog.askdirectory(
            title="Select Teams Folder",
            initialdir=self.base_folder
        )
        if folder:
            self.base_folder = folder
            self.folder_var.set(folder)
            self.load_turn_snapshots()
            self.status_var.set(f"Selected folder: {os.path.basename(folder)}")

    def load_turn_snapshots(self):
        """Load turn snapshots from saves/league/turn_* folders."""
        league_dir = os.path.join(self.base_folder, "league")

        print(f"\n=== load_turn_snapshots ===")
        print(f"League dir: {league_dir}")
        print(f"Exists: {os.path.exists(league_dir)}")

        if not os.path.exists(league_dir):
            self.turn_combo["values"] = []
            self.status_var.set("No league folder found")
            return

        self.turn_snapshots.clear()
        turn_options = []

        league_items = sorted(os.listdir(league_dir))
        print(f"Items: {[x for x in league_items if x.startswith('turn_')]}")

        for item in league_items:
            item_path = os.path.join(league_dir, item)
            if not os.path.isdir(item_path):
                continue

            if item.startswith("turn_"):
                print(f"\nTurn: {item}")
                warriors = []
                upload_files = [f for f in os.listdir(item_path) if f.startswith("upload_") and f.endswith(".json")]
                print(f"  Files: {len(upload_files)}")

                first_error = True
                for file in upload_files:
                    try:
                        with open(os.path.join(item_path, file)) as f:
                            team_data = json.load(f)
                        # Warriors are nested in team_data["team"]["warriors"]
                        w_list = team_data.get("team", {}).get("warriors", [])
                        print(f"    {file}: {len(w_list)} warriors")
                        for w_dict in w_list:
                            if w_dict:
                                try:
                                    w = Warrior.from_dict(w_dict)
                                    if w:
                                        warriors.append(w)
                                except Exception as e:
                                    if first_error:
                                        print(f"      FIRST ERROR: {type(e).__name__}: {str(e)[:100]}")
                                        first_error = False
                    except Exception as e:
                        if first_error:
                            print(f"      FILE ERROR: {type(e).__name__}: {str(e)[:100]}")
                            first_error = False

                print(f"  Warriors: {len(warriors)}")
                if warriors:
                    self.turn_snapshots[item] = warriors
                    turn_options.append(item)

        print(f"Turn options: {turn_options}\n")
        self.turn_combo["values"] = sorted(turn_options)

        if turn_options:
            self.turn_var.set(sorted(turn_options)[0])
            self.status_var.set(f"Found {len(turn_options)} turns")
        else:
            self.status_var.set("No warriors found")

    def load_turn_warriors(self):
        """Load warriors from selected turn snapshot."""
        turn = self.turn_var.get()

        if not turn:
            self.status_var.set("Please select a turn first")
            return

        if turn in self.turn_snapshots:
            # Load from turn snapshot
            self.warrior_pool = self.turn_snapshots[turn]
            self.status_var.set(f"Loaded {turn} ({len(self.warrior_pool)} warriors)")
        else:
            self.status_var.set("Turn not found")
            return

        # Populate warrior combo
        if self.warrior_pool:
            warrior_names = [
                f"{w.name} ({w.race.name}) - {w.wins}W-{w.losses}L" for w in self.warrior_pool
            ]
            self.warrior_combo["values"] = warrior_names
        else:
            self.status_var.set(f"No warriors found in {turn}")

    def load_warriors(self):
        """Load all warriors from active arena rosters (current/latest turn)."""
        saves_dir = "saves/league"

        if not os.path.exists(saves_dir):
            self.info_text.insert(tk.END, "No saves/league directory found.")
            return

        # Look for turn directories (current league battles)
        for turn_dir in sorted(os.listdir(saves_dir)):
            turn_path = os.path.join(saves_dir, turn_dir)
            if not os.path.isdir(turn_path):
                continue

            # Load uploaded teams
            for file in os.listdir(turn_path):
                if file.endswith(".json") and file.startswith("team_"):
                    try:
                        with open(os.path.join(turn_path, file)) as f:
                            team_data = json.load(f)
                        team = Team.from_dict(team_data)
                        self.warrior_pool.extend(team.warriors)
                    except Exception as e:
                        print(f"Error loading {file}: {e}")

        # Populate combobox
        if self.warrior_pool:
            warrior_names = [
                f"{w.name} ({w.race.name}) - {w.wins}W-{w.losses}L" for w in self.warrior_pool
            ]
            self.warrior_combo["values"] = warrior_names

    def on_warrior_selected(self):
        """Handle warrior selection."""
        selection = self.warrior_combo.current()
        if 0 <= selection < len(self.warrior_pool):
            self.selected_warrior = self.warrior_pool[selection]
            self.analyze_warrior()

    def analyze_warrior(self):
        """Analyze selected warrior and display results."""
        if not self.selected_warrior:
            return

        self.optimizer = StrategyOptimizer(self.selected_warrior)
        w = self.selected_warrior

        # --- Update info panel ---
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)

        info = f"""
{'='*45}
WARRIOR ANALYSIS
{'='*45}

NAME: {w.name}
RACE: {w.race.name}
RECORD: {w.wins}W - {w.losses}L - {w.kills}K

ATTRIBUTES:
"""
        self.info_text.insert(tk.END, info)

        scores = self.optimizer.get_attribute_scores()
        for attr, val in w.__dict__.items():
            if attr in ["strength", "dexterity", "constitution", "intelligence", "presence", "size"]:
                score = scores[attr[:3].upper()]
                bar = "█" * int(score / 10) + "░" * (10 - int(score / 10))
                self.info_text.insert(
                    tk.END,
                    f"  {attr.capitalize():<14}: {val:2d}  [{bar}] {score:.0f}\n",
                )

        dom_attr, dom_score = self.optimizer.get_dominant_attribute()
        self.info_text.insert(tk.END, f"\nDOMINANT: {dom_attr} ({dom_score:.0f})\n")

        self.info_text.insert(
            tk.END,
            f"""
HP: {w.max_hp}
ENDURANCE: {w.max_endurance:.1f}

EQUIPMENT:
  Armor:    {w.armor or 'None'}
  Helm:     {w.helm or 'None'}
  Primary:  {w.primary_weapon}
  Secondary: {w.secondary_weapon}
  Backup:   {w.backup_weapon or 'None'}

SKILLS:
""",
        )

        trained = {skill: level for skill, level in w.skills.items() if level > 0}
        if trained:
            for skill, level in sorted(trained.items(), key=lambda x: -x[1]):
                self.info_text.insert(tk.END, f"  {skill:<20}: {level}/9\n")
        else:
            self.info_text.insert(tk.END, "  (None trained)\n")

        # WEAPON RECOMMENDATIONS
        self.info_text.insert(tk.END, f"\nWEAPON RECOMMENDATIONS:\n")
        weapons = self.optimizer.recommend_weapons()
        for weapon, reason in weapons:
            self.info_text.insert(tk.END, f"  • {weapon:<20}: {reason}\n")

        self.info_text.config(state=tk.DISABLED)

        # --- Update strategies panel ---
        for widget in self.strategies_frame.winfo_children():
            widget.destroy()

        strategies = self.optimizer.recommend_strategies()

        for strat in strategies:
            self.create_strategy_card(strat)

    def create_strategy_card(self, strat: Dict):
        """Create a strategy recommendation card."""
        frame = ttk.LabelFrame(
            self.strategies_frame,
            text=strat["trigger"],
            padding=10,
        )
        frame.pack(fill=tk.X, pady=5, padx=5)

        # Style
        style_frame = ttk.Frame(frame)
        style_frame.pack(fill=tk.X, pady=3)
        ttk.Label(style_frame, text="Style:", font=("Arial", 10, "bold")).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(
            style_frame,
            text=strat["style"],
            font=("Arial", 10, "bold"),
            foreground="blue",
        ).pack(side=tk.LEFT, padx=5)

        # Activity
        activity_frame = ttk.Frame(frame)
        activity_frame.pack(fill=tk.X, pady=3)
        ttk.Label(activity_frame, text="Activity:", font=("Arial", 10, "bold")).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(
            activity_frame,
            text=f"{strat['activity']}/9",
            font=("Arial", 10),
            foreground="green",
        ).pack(side=tk.LEFT, padx=5)

        # Reason
        reason_frame = ttk.Frame(frame)
        reason_frame.pack(fill=tk.X, pady=3)
        ttk.Label(reason_frame, text="Reason:", font=("Arial", 10, "bold")).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(reason_frame, text=strat["reason"], font=("Arial", 9), wraplength=300).pack(
            side=tk.LEFT, padx=5, fill=tk.X, expand=True
        )

        # STYLE BONUSES
        if "bonuses" in strat and strat["bonuses"]:
            bonus_frame = ttk.LabelFrame(frame, text="Style Bonuses", padding=5)
            bonus_frame.pack(fill=tk.X, pady=5)

            bonuses = strat["bonuses"]
            bonus_text = ""
            for key, value in bonuses.items():
                bonus_text += f"  {key}: {value}  |  "
            bonus_text = bonus_text.rstrip("  |  ")

            ttk.Label(bonus_frame, text=bonus_text, font=("Arial", 9), wraplength=400).pack(
                anchor=tk.W, padx=5
            )


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    root = tk.Tk()
    app = WarriorStrategyOptimizer(root)
    root.mainloop()
