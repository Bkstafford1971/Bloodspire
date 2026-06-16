#!/usr/bin/env python3
# =============================================================================
# game_balance_simulator.py — Standalone Admin Testing Tool
# =============================================================================
import os
import sys
import json
import random
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# Ensure we can import from the parent directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from warrior import Warrior
from team import Team
from combat import run_fight
from combat_debug_logger import CombatDebugLogger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEAGUE_DIR = os.path.join(os.path.dirname(BASE_DIR), "saves", "league")
REPORTS_DIR = os.path.join(os.path.dirname(BASE_DIR), "saves", "admin_logs", "simulations")

class BalanceSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Agony Amphitheatre — Balance Simulator (ADMIN ONLY)")
        self.root.geometry("600x500")
        
        self.setup_ui()
        os.makedirs(REPORTS_DIR, exist_ok=True)

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Balance Simulation Tool", font=("Arial", 16, "bold")).pack(pady=10)
        ttk.Label(main_frame, text="Run test fights using actual player upload data.", font=("Arial", 10)).pack(pady=5)

        # Turn Selection
        turn_frame = ttk.LabelFrame(main_frame, text="Data Source", padding="10")
        turn_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(turn_frame, text="Select Turn Folder:").pack(side=tk.LEFT, padx=5)
        self.turn_var = tk.StringVar()
        self.turn_combo = ttk.Combobox(turn_frame, textvariable=self.turn_var)
        self.turn_combo.pack(side=tk.LEFT, padx=5)
        self.refresh_turns()

        # Fight Count
        cfg_frame = ttk.LabelFrame(main_frame, text="Configuration", padding="10")
        cfg_frame.pack(fill=tk.X, pady=10)
        ttk.Label(cfg_frame, text="Number of Fights:").pack(side=tk.LEFT, padx=5)
        self.fight_count = ttk.Spinbox(cfg_frame, from_=1, to=500, width=5)
        self.fight_count.set(50)
        self.fight_count.pack(side=tk.LEFT, padx=5)

        # Output/Status
        self.status_text = scrolledtext.ScrolledText(main_frame, height=10, state='disabled', font=("Consolas", 9))
        self.status_text.pack(fill=tk.BOTH, expand=True, pady=10)

        # Run Button
        self.run_btn = ttk.Button(main_frame, text="RUN SIMULATION", command=self.run_sim)
        self.run_btn.pack(pady=10)

    def log(self, message):
        self.status_text.config(state='normal')
        self.status_text.insert(tk.END, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {message}\n")
        self.status_text.see(tk.END)
        self.status_text.config(state='disabled')
        self.root.update()

    def refresh_turns(self):
        if not os.path.exists(LEAGUE_DIR):
            return
        turns = [d for d in os.listdir(LEAGUE_DIR) if d.startswith("turn_") and os.path.isdir(os.path.join(LEAGUE_DIR, d))]
        self.turn_combo['values'] = sorted(turns, reverse=True)
        if turns:
            self.turn_combo.current(0)

    def load_warriors(self, turn_folder):
        path = os.path.join(LEAGUE_DIR, turn_folder)
        warrior_pool = []
        
        self.log(f"Scanning {turn_folder} for uploads...")
        for fn in os.listdir(path):
            if fn.startswith("upload_") and fn.endswith(".json"):
                try:
                    with open(os.path.join(path, fn), 'r') as f:
                        data = json.load(f)
                        team_data = data.get('team', {})
                        team_name = team_data.get('team_name', 'Unknown Team')
                        mgr_name = data.get('manager_name', 'Unknown Manager')
                        
                        for w_dict in team_data.get('warriors', []):
                            if w_dict and not w_dict.get('is_dead'):
                                w = Warrior.from_dict(w_dict)
                                # Store meta-data for the report
                                w._sim_team = team_name
                                w._sim_mgr = mgr_name
                                warrior_pool.append(w)
                except:
                    continue
        
        return warrior_pool

    def run_sim(self):
        turn = self.turn_var.get()
        if not turn:
            messagebox.showerror("Error", "Please select a turn folder.")
            return

        num_fights = int(self.fight_count.get())
        warrior_pool = self.load_warriors(turn)

        if len(warrior_pool) < 2:
            messagebox.showerror("Error", "Not enough warriors in this turn to simulate a fight.")
            return

        self.run_btn.config(state='disabled')
        self.log(f"Starting simulation of {num_fights} fights...")
        
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append(f"ADMIN BALANCE SIMULATION REPORT - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"Source Data: {turn}")
        report_lines.append(f"Fights Simulated: {num_fights}")
        report_lines.append("=" * 80 + "\n")

        kills = 0
        exhaustion_ends = 0

        for i in range(num_fights):
            # Selection
            w1 = random.choice(warrior_pool)
            w2 = random.choice([w for w in warrior_pool if w is not w1])

            # Fresh stats for sim (don't injure the source objects)
            w1_sim = Warrior.from_dict(w1.to_dict())
            w2_sim = Warrior.from_dict(w2.to_dict())
            w1_sim._sim_team = w1._sim_team
            w2_sim._sim_team = w2._sim_team

            self.log(f"Fight {i+1}: {w1_sim.name} vs {w2_sim.name}")

            # Use existing detailed debugger
            dbg = CombatDebugLogger()
            dbg.fight_id = i + 1
            dbg.turn_num = 999
            dbg.debug_team = "SIMULATION"

            result = run_fight(
                w1_sim, w2_sim,
                team_a_name=w1_sim._sim_team,
                team_b_name=w2_sim._sim_team,
                debug_logger=dbg
            )

            if result.loser_died:
                kills += 1
            if result.exhaustion_end:
                exhaustion_ends += 1
                self.log(
                    f"  >> EXHAUSTION END: {result.loser.name} ran dry "
                    f"(end {result.loser_end_pct*100:.0f}%) — "
                    f"{result.winner.name} wins at {result.minutes_elapsed}m "
                    f"(end {result.winner_end_pct*100:.0f}%)"
                )

            # Record Combat
            report_lines.append(f"--- SIMULATED BOUT #{i+1} ---")
            report_lines.append(f"MATCHUP: {w1_sim.name} ({w1_sim.race.name}) vs {w2_sim.name} ({w2_sim.race.name})")
            report_lines.append(f"W1 GEAR: {w1_sim.primary_weapon} / {w1_sim.armor}")
            report_lines.append(f"W2 GEAR: {w2_sim.primary_weapon} / {w2_sim.armor}")
            end_tag = " [EXHAUSTION]" if result.exhaustion_end else ""
            report_lines.append(f"RESULT: {result.winner.name} def. {result.loser.name} in {result.minutes_elapsed}m{end_tag}")
            report_lines.append(
                f"ENDURANCE AT END: {result.winner.name} {result.winner_end_pct*100:.0f}% / "
                f"{result.loser.name} {result.loser_end_pct*100:.0f}%"
            )
            report_lines.append("-" * 40)
            report_lines.append(dbg.get_text())
            report_lines.append("-" * 40)
            
            # Simulate Training
            report_lines.append(f"TRAINING RESULTS for {w1_sim.name}:")
            if not w1_sim.trains:
                report_lines.append("   No training queued.")
            else:
                for skill in w1_sim.trains[:3]:
                    msg, roll, chance = w1_sim.train_skill(skill, verbose=True)
                    status = "SUCCESS" if roll <= chance else "FAILED"
                    report_lines.append(f"   [{status}] {skill}: Rolled {roll} vs {chance}% -> {msg}")
            
            report_lines.append("\n" + "=" * 60 + "\n")

        # Final Totals
        summary = [
            "SIMULATION SUMMARY",
            "-" * 20,
            f"Total Fights:     {num_fights}",
            f"Total Kills:      {kills} ({(kills/num_fights)*100:.1f}%)",
            f"Exhaustion Ends:  {exhaustion_ends} ({(exhaustion_ends/num_fights)*100:.1f}%)",
            "-" * 20
        ]
        report_lines = summary + ["\n"] + report_lines

        # Save Report
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(REPORTS_DIR, f"sim_report_{timestamp}.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))

        self.log(f"Simulation Complete. Report saved to: {report_path}")
        messagebox.showinfo(
            "Sim Complete",
            f"Simulation finished.\n\nReport: {os.path.basename(report_path)}\n\n"
            f"Kills: {kills}  |  Exhaustion Ends: {exhaustion_ends} ({(exhaustion_ends/num_fights)*100:.1f}%)"
        )
        self.run_btn.config(state='normal')

if __name__ == "__main__":
    root = tk.Tk()
    app = BalanceSimulator(root)
    root.mainloop()