#!/usr/bin/env python3
"""
Opportunity Throw Testing Tool
Tests Opportunity Throw mechanics with customizable triggers, styles, and weapons.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from warrior import Warrior, TRIGGERS, FIGHTING_STYLES, AIM_DEFENSE_POINTS, Strategy
from weapons import get_weapon, Weapon, WEAPONS
from save import load_all_teams
from combat import run_fight
from copy import deepcopy
import json
from datetime import datetime

# Get all available weapons
def get_all_weapons():
    """Get list of all weapon display names."""
    weapons_list = ["Open Hand"]

    try:
        # WEAPONS is a dict {skill_key: Weapon object}
        for skill_key, weapon_obj in WEAPONS.items():
            if hasattr(weapon_obj, 'display'):
                weapons_list.append(weapon_obj.display)
    except Exception as e:
        print(f"Error loading weapons: {e}")

    return sorted(list(set(weapons_list)))

class OpportunityThrowTester:
    def __init__(self, root):
        self.root = root
        self.root.title("Opportunity Throw Testing Tool")
        self.root.geometry("1400x900")

        self.all_weapons = get_all_weapons()
        self.all_warriors = self._load_warriors()
        self.warrior_names = [w.name for w in self.all_warriors]

        # Create UI
        self._create_ui()

    def _load_warriors(self):
        """Load all available warriors from teams."""
        try:
            teams = load_all_teams()
            warriors = []
            for team in teams:
                team_warriors = getattr(team, 'warriors', [])
                if isinstance(team_warriors, dict):
                    # Warriors are stored as dict {warrior_id: warrior_object}
                    for warrior in team_warriors.values():
                        if warrior and hasattr(warrior, 'name'):
                            warriors.append(warrior)
                else:
                    # Warriors are stored as list
                    for warrior in team_warriors:
                        if warrior and hasattr(warrior, 'name'):
                            warriors.append(warrior)
            return warriors
        except Exception as e:
            print(f"Error loading warriors: {e}")
            return []

    def _create_ui(self):
        """Create the UI layout."""
        # Main frames
        left_frame = ttk.Frame(self.root)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=10, pady=10)

        right_frame = ttk.Frame(self.root)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # ═══ LEFT PANEL: CONFIGURATION ═══
        config_label = ttk.Label(left_frame, text="Configuration", font=("Arial", 12, "bold"))
        config_label.pack()

        # Attacker selection
        ttk.Label(left_frame, text="Attacker:").pack()
        self.attacker_var = tk.StringVar(value=self.warrior_names[0] if self.warrior_names else "")
        attacker_combo = ttk.Combobox(left_frame, textvariable=self.attacker_var,
                                       values=self.warrior_names, state="readonly", width=20)
        attacker_combo.pack()

        # Opponent selection
        ttk.Label(left_frame, text="Opponent:").pack(pady=(10, 0))
        self.opponent_var = tk.StringVar(value=self.warrior_names[1] if len(self.warrior_names) > 1 else "")
        opponent_combo = ttk.Combobox(left_frame, textvariable=self.opponent_var,
                                       values=self.warrior_names, state="readonly", width=20)
        opponent_combo.pack()

        # Weapons section
        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(left_frame, text="Weapons", font=("Arial", 11, "bold")).pack()

        # Primary weapon
        ttk.Label(left_frame, text="Primary Weapon:").pack()
        self.primary_var = tk.StringVar(value="Open Hand")
        primary_combo = ttk.Combobox(left_frame, textvariable=self.primary_var,
                                     values=self.all_weapons, state="readonly", width=20)
        primary_combo.pack()

        # Secondary weapon
        ttk.Label(left_frame, text="Secondary Weapon:").pack(pady=(10, 0))
        self.secondary_var = tk.StringVar(value="Open Hand")
        secondary_combo = ttk.Combobox(left_frame, textvariable=self.secondary_var,
                                       values=self.all_weapons, state="readonly", width=20)
        secondary_combo.pack()

        # Backup weapon
        ttk.Label(left_frame, text="Backup Weapon:").pack(pady=(10, 0))
        self.backup_var = tk.StringVar(value="Open Hand")
        backup_combo = ttk.Combobox(left_frame, textvariable=self.backup_var,
                                    values=self.all_weapons, state="readonly", width=20)
        backup_combo.pack()

        # Strategies section
        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(left_frame, text="Strategies", font=("Arial", 11, "bold")).pack()

        self.strategy_frames = []
        for i in range(3):
            self._add_strategy_frame(left_frame, i)

        # Add more strategies button
        add_btn = ttk.Button(left_frame, text="+ Add Strategy", command=self._add_more_strategies)
        add_btn.pack(pady=5)

        # Test button
        test_btn = ttk.Button(left_frame, text="RUN TEST FIGHT", command=self._run_test)
        test_btn.pack(pady=20, fill=tk.X)

        # ═══ RIGHT PANEL: OUTPUT ═══
        output_label = ttk.Label(right_frame, text="Fight Output", font=("Arial", 12, "bold"))
        output_label.pack()

        self.output_text = scrolledtext.ScrolledText(right_frame, width=90, height=50,
                                                      font=("Courier", 9))
        self.output_text.pack(fill=tk.BOTH, expand=True)

    def _add_strategy_frame(self, parent, index):
        """Add a strategy configuration frame."""
        frame = ttk.LabelFrame(parent, text=f"Strategy {index+1}", padding=5)
        frame.pack(fill=tk.X, pady=5)

        # Trigger
        ttk.Label(frame, text="Trigger:").grid(row=0, column=0, sticky=tk.W)
        trigger_var = tk.StringVar(value=TRIGGERS[0] if TRIGGERS else "")
        trigger_combo = ttk.Combobox(frame, textvariable=trigger_var,
                                     values=TRIGGERS, state="readonly", width=25)
        trigger_combo.grid(row=0, column=1, padx=5)

        # Fighting Style
        ttk.Label(frame, text="Style:").grid(row=1, column=0, sticky=tk.W)
        style_var = tk.StringVar(value=FIGHTING_STYLES[0] if FIGHTING_STYLES else "")
        style_combo = ttk.Combobox(frame, textvariable=style_var,
                                   values=FIGHTING_STYLES, state="readonly", width=25)
        style_combo.grid(row=1, column=1, padx=5)

        # Aim Point
        ttk.Label(frame, text="Aim Point:").grid(row=2, column=0, sticky=tk.W)
        aim_var = tk.StringVar(value=AIM_DEFENSE_POINTS[0] if AIM_DEFENSE_POINTS else "")
        aim_combo = ttk.Combobox(frame, textvariable=aim_var,
                                 values=AIM_DEFENSE_POINTS, state="readonly", width=25)
        aim_combo.grid(row=2, column=1, padx=5)

        self.strategy_frames.append({
            'frame': frame,
            'trigger': trigger_var,
            'style': style_var,
            'aim': aim_var
        })

    def _add_more_strategies(self):
        """Add more strategy frames dynamically."""
        if len(self.strategy_frames) < 6:
            parent = self.strategy_frames[0]['frame'].master
            self._add_strategy_frame(parent, len(self.strategy_frames))
            self.root.update()

    def _get_warrior_by_name(self, name):
        """Get warrior object by name."""
        for w in self.all_warriors:
            if w.name == name:
                return w
        return None

    def _run_test(self):
        """Run the test fight."""
        attacker_name = self.attacker_var.get()
        opponent_name = self.opponent_var.get()

        if not attacker_name or not opponent_name:
            messagebox.showerror("Error", "Please select both attacker and opponent")
            return

        attacker = self._get_warrior_by_name(attacker_name)
        opponent = self._get_warrior_by_name(opponent_name)

        if not attacker or not opponent:
            messagebox.showerror("Error", "Could not load warriors")
            return

        # Clone warriors to avoid modifying originals
        attacker = deepcopy(attacker)
        opponent = deepcopy(opponent)

        # Set weapons
        attacker.primary_weapon = self.primary_var.get()
        attacker.secondary_weapon = self.secondary_var.get()
        attacker.backup_weapon = self.backup_var.get()

        # Set strategies
        attacker.strategies = []
        for i, strat_data in enumerate(self.strategy_frames):
            s = Strategy(
                trigger=strat_data['trigger'].get(),
                style=strat_data['style'].get(),
                activity=5,
                aim_point=strat_data['aim'].get(),
                defense_point="Chest"
            )
            attacker.strategies.append(s)

        # Run fight
        self.output_text.delete(1.0, tk.END)
        output = f"═" * 80 + "\n"
        output += f"{attacker.name.upper()} ({attacker.wins}-{attacker.losses}-{attacker.kills})"
        output += " " * 20
        output += f"vs" + " " * 20
        output += f"{opponent.name.upper()} ({opponent.wins}-{opponent.losses}-{opponent.kills})\n"
        output += f"═" * 80 + "\n\n"

        # Weapon info
        output += f"{attacker.name.upper()} Configuration:\n"
        output += f"  Primary: {attacker.primary_weapon}\n"
        output += f"  Secondary: {attacker.secondary_weapon}\n"
        output += f"  Backup: {attacker.backup_weapon}\n\n"

        # Strategies
        output += f"Strategies:\n"
        for i, strat in enumerate(attacker.strategies, 1):
            output += f"  {i}. Trigger: {strat.trigger}\n"
            output += f"     Style: {strat.style} | Aim: {strat.aim_point}\n"
        output += "\n"

        # Weapon info
        output += "Weapon Details:\n"
        try:
            primary_wpn = get_weapon(attacker.primary_weapon)
            output += f"  Primary ({attacker.primary_weapon}): Throwable={primary_wpn.throwable}, "
            output += f"Weight={primary_wpn.weight}, Damage={primary_wpn.damage_base}-{primary_wpn.damage_top}\n"
        except:
            output += f"  Primary ({attacker.primary_weapon}): [Invalid weapon]\n"

        try:
            secondary_wpn = get_weapon(attacker.secondary_weapon)
            output += f"  Secondary ({attacker.secondary_weapon}): Throwable={secondary_wpn.throwable}, "
            output += f"Weight={secondary_wpn.weight}, Damage={secondary_wpn.damage_base}-{secondary_wpn.damage_top}\n"
        except:
            output += f"  Secondary ({attacker.secondary_weapon}): [Invalid weapon]\n"

        try:
            if attacker.backup_weapon:
                backup_wpn = get_weapon(attacker.backup_weapon)
                output += f"  Backup ({attacker.backup_weapon}): Throwable={backup_wpn.throwable}, "
                output += f"Weight={backup_wpn.weight}, Damage={backup_wpn.damage_base}-{backup_wpn.damage_top}\n"
        except:
            if attacker.backup_weapon:
                output += f"  Backup ({attacker.backup_weapon}): [Invalid weapon]\n"

        output += "\n" + "═" * 80 + "\n"
        output += "FIGHT SIMULATION:\n"
        output += "═" * 80 + "\n\n"

        # Simulate Opportunity Throw logic
        output += "\nOPPORTUNITY THROW LOGIC ANALYSIS:\n"
        output += "─" * 80 + "\n\n"

        # Check which strategies are Opportunity Throw
        for i, strat in enumerate(attacker.strategies, 1):
            if strat.style == "Opportunity Throw":
                output += f"Strategy {i}: OPPORTUNITY THROW detected\n"
                output += f"  Trigger: {strat.trigger}\n\n"

                # Simulate weapon selection logic
                primary = attacker.primary_weapon
                secondary = attacker.secondary_weapon
                backup = attacker.backup_weapon

                try:
                    primary_wpn = get_weapon(primary)
                    primary_throwable = primary_wpn.throwable and primary_wpn.skill_key != "empty_hand"
                except:
                    primary_throwable = False
                    primary_wpn = None

                output += f"  Primary Weapon: {primary}\n"
                if primary_wpn:
                    output += f"    - Throwable: {primary_throwable}\n"
                    output += f"    - Skill Key: {primary_wpn.skill_key}\n"
                else:
                    output += f"    - [INVALID WEAPON]\n"

                # Check secondary
                if primary_throwable:
                    output += f"\n  ✓ PRIMARY IS THROWABLE - Will throw {primary}\n"
                else:
                    output += f"\n  ✗ PRIMARY IS NOT THROWABLE - Checking secondary...\n\n"

                    try:
                        secondary_wpn = get_weapon(secondary)
                        secondary_throwable = secondary_wpn.throwable and secondary_wpn.skill_key != "empty_hand"
                    except:
                        secondary_throwable = False
                        secondary_wpn = None

                    output += f"  Secondary Weapon: {secondary}\n"
                    if secondary_wpn:
                        output += f"    - Throwable: {secondary_throwable}\n"
                        output += f"    - Skill Key: {secondary_wpn.skill_key}\n"
                    else:
                        output += f"    - [INVALID WEAPON]\n"

                    if secondary_throwable:
                        output += f"\n  ✓ SECONDARY IS THROWABLE - Will throw {secondary}\n"
                    else:
                        output += f"\n  ✗ SECONDARY IS NOT THROWABLE - Checking backup...\n\n"

                        try:
                            backup_wpn = get_weapon(backup)
                            backup_throwable = backup_wpn.throwable and backup_wpn.skill_key != "empty_hand"
                        except:
                            backup_throwable = False
                            backup_wpn = None

                        output += f"  Backup Weapon: {backup}\n"
                        if backup_wpn:
                            output += f"    - Throwable: {backup_throwable}\n"
                            output += f"    - Skill Key: {backup_wpn.skill_key}\n"
                        else:
                            output += f"    - [INVALID WEAPON]\n"

                        if backup_throwable:
                            output += f"\n  ✓ BACKUP IS THROWABLE - Will throw {backup}\n"
                        else:
                            output += f"\n  ✗ NO THROWABLE WEAPONS AVAILABLE - Style will override to Martial Combat\n"

                output += "\n" + "─" * 80 + "\n\n"

        output += "\n" + "═" * 80 + "\n"
        output += f"TEST SUMMARY:\n"
        output += f"═" * 80 + "\n"
        output += f"  Attacker: {attacker.name}\n"
        output += f"  Weapons: Primary={attacker.primary_weapon}, Secondary={attacker.secondary_weapon}, Backup={attacker.backup_weapon}\n"
        output += f"  Strategies: {len(attacker.strategies)}\n"
        opportunity_throws = sum(1 for s in attacker.strategies if s.style == "Opportunity Throw")
        output += f"  Opportunity Throw strategies: {opportunity_throws}\n"
        output += f"═" * 80 + "\n\n"

        # Run actual fight
        output += "SIMULATED FIGHT:\n"
        output += "═" * 80 + "\n\n"
        try:
            result = run_fight(attacker, opponent,
                              team_a_name=attacker.team_name if hasattr(attacker, 'team_name') else "Test Team A",
                              team_b_name=opponent.team_name if hasattr(opponent, 'team_name') else "Test Team B",
                              manager_a_name="Test Manager",
                              manager_b_name="Test Manager")
            if result.narrative:
                output += result.narrative
            output += "\n" + "═" * 80 + "\n"
            output += f"FIGHT RESULT:\n"
            output += f"  Winner: {result.winner.name if result.winner else 'N/A'}\n"
            output += f"  Loser: {result.loser.name if result.loser else 'N/A'}\n"
            output += f"  Duration: {result.minutes_elapsed} minute(s)\n"
            output += f"  Opponent Died: {result.loser_died}\n"
        except Exception as e:
            output += f"Fight Error: {str(e)}\n"
            import traceback
            output += traceback.format_exc()

        output += f"═" * 80 + "\n"

        self.output_text.insert(tk.END, output)

def main():
    root = tk.Tk()
    app = OpportunityThrowTester(root)
    root.mainloop()

if __name__ == "__main__":
    main()
