#!/usr/bin/env python3
"""
Blood Challenge Manual Sandbox - Interactive step-by-step BC testing.
Allows manual control of fights, sit-outs, and kills to verify BC counter behavior.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
from team import Team
from warrior import Warrior

class BCManualSandbox:
    def __init__(self, root):
        self.root = root
        self.root.title("Blood Challenge Manual Sandbox")
        self.root.geometry("1200x800")

        # Setup teams
        self.teams = {}
        self.setup_teams()

        # Current turn
        self.turn = 0

        # Create UI
        self.create_ui()

    def setup_teams(self):
        """Initialize teams with warriors."""
        for team_id in range(1, 4):  # 3 teams
            team = Team(f"Team {team_id}", f"Manager {team_id}", team_id)
            for warrior_id in range(1, 4):  # 3 warriors per team
                w = Warrior(
                    f"W{team_id}_{warrior_id}", "Human", "Male",
                    12, 12, 10, 10, 10, 10
                )
                team.warriors.append(w)
            self.teams[team_id] = team

    def create_ui(self):
        """Create the UI."""
        # Top: Turn counter
        top_frame = ttk.Frame(self.root)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(top_frame, text="Turn:", font=("Arial", 14, "bold")).pack(side=tk.LEFT)
        self.turn_label = ttk.Label(top_frame, text="0", font=("Arial", 14, "bold"), foreground="blue")
        self.turn_label.pack(side=tk.LEFT, padx=5)

        ttk.Button(top_frame, text="Reset", command=self.reset).pack(side=tk.RIGHT, padx=5)

        # Main content: Left (controls) + Right (status)
        content_frame = ttk.Frame(self.root)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Left: Controls
        left_frame = ttk.LabelFrame(content_frame, text="Actions", padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 5))

        # Killer selection
        ttk.Label(left_frame, text="Select Killer:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        self.killer_var = tk.StringVar()
        killer_options = [f"W{i}_{j}" for i in range(1, 4) for j in range(1, 4)]
        ttk.Combobox(left_frame, textvariable=self.killer_var, values=killer_options, state="readonly", width=15).pack(fill=tk.X, pady=(0, 10))

        # Victim selection
        ttk.Label(left_frame, text="Select Victim:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        self.victim_var = tk.StringVar()
        ttk.Combobox(left_frame, textvariable=self.victim_var, values=killer_options, state="readonly", width=15).pack(fill=tk.X, pady=(0, 10))

        ttk.Button(left_frame, text="KILL (Victim dies, BC created)", command=self.kill_warrior).pack(fill=tk.X, pady=5)

        ttk.Separator(left_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # Fighter selection
        ttk.Label(left_frame, text="Warriors who fight this turn:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        self.fighters = {}
        for team_id in range(1, 4):
            frame = ttk.LabelFrame(left_frame, text=f"Team {team_id}", padding=5)
            frame.pack(fill=tk.X, pady=5)
            for warrior_id in range(1, 4):
                name = f"W{team_id}_{warrior_id}"
                var = tk.BooleanVar(value=False)
                self.fighters[name] = var
                ttk.Checkbutton(frame, text=name, variable=var).pack(anchor=tk.W)

        ttk.Button(left_frame, text="Record Fights & Update BCs", command=self.record_fights).pack(fill=tk.X, pady=10)

        # Right: Status display
        right_frame = ttk.LabelFrame(content_frame, text="Blood Challenge Status", padding=10)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.status_text = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, font=("Courier", 9), height=40)
        self.status_text.pack(fill=tk.BOTH, expand=True)

        self.update_status()

    def kill_warrior(self):
        """Kill a warrior and create BC."""
        killer = self.killer_var.get()
        victim = self.victim_var.get()

        if not killer or not victim or killer == victim:
            self.status_text.insert(tk.END, "ERROR: Select different killer and victim\n")
            return

        # Parse team IDs
        killer_team = int(killer[1])
        victim_team = int(victim[1])

        if killer_team == victim_team:
            self.status_text.insert(tk.END, "ERROR: Killer and victim must be on different teams\n")
            return

        # Find and kill victim
        victim_obj = None
        for w in self.teams[victim_team].warriors:
            if w.name == victim:
                victim_obj = w
                break

        if not victim_obj or victim_obj.is_dead:
            self.status_text.insert(tk.END, f"ERROR: {victim} not found or already dead\n")
            return

        # Kill and create BC
        self.teams[victim_team].kill_warrior(victim_obj, killer)
        self.status_text.insert(tk.END, f"\n*** KILL: {killer} killed {victim} ***\n")
        self.status_text.insert(tk.END, f"    Blood Challenge created for {victim}'s team\n")
        self.update_status()

    def record_fights(self):
        """Record which warriors fought and update BC counters."""
        self.turn += 1
        self.turn_label.config(text=str(self.turn))

        fought = [name for name, var in self.fighters.items() if var.get()]

        self.status_text.insert(tk.END, f"\n--- TURN {self.turn} ---\n")

        if not fought:
            self.status_text.insert(tk.END, "No warriors fought this turn.\n")
        else:
            self.status_text.insert(tk.END, f"Warriors who fought: {', '.join(fought)}\n\n")

            # Record participation for all teams
            for name in fought:
                self.status_text.insert(tk.END, f"Processing {name}:\n")
                for team_id, team in self.teams.items():
                    before_bcs = len(team.blood_challenges)
                    team.record_killer_participation(name)
                    after_bcs = len(team.blood_challenges)

                    # Count how many BCs were updated
                    updated = 0
                    for bc in team.blood_challenges:
                        if bc.get("target_name") == name and bc.get("status") == "active":
                            updated += 1

                    if updated > 0:
                        self.status_text.insert(tk.END, f"  Team {team_id}: Updated {updated} BC(s) against {name}\n")
                self.status_text.insert(tk.END, "\n")

        # Cleanup expired BCs
        for team in self.teams.values():
            before = len(team.blood_challenges)
            team.blood_challenges = [
                bc for bc in team.blood_challenges
                if bc.get("killer_turns_fought", 0) < 3
            ]
            after = len(team.blood_challenges)
            if before > after:
                removed = before - after
                self.status_text.insert(tk.END, f"  [EXPIRED] {removed} BC(s) removed (killer reached 3 fights)\n")

        # Decrement
        for team in self.teams.values():
            team.decrement_blood_challenge_turns()

        # Uncheck all fighters for next turn
        for var in self.fighters.values():
            var.set(False)

        self.update_status()

    def update_status(self):
        """Update the status display."""
        self.status_text.delete(1.0, tk.END)

        self.status_text.insert(tk.END, "="*70 + "\n")
        self.status_text.insert(tk.END, f"BLOOD CHALLENGE STATUS - TURN {self.turn}\n")
        self.status_text.insert(tk.END, "="*70 + "\n\n")

        total_bcs = 0
        for team_id in range(1, 4):
            team = self.teams[team_id]
            active = team.get_active_blood_challenges()

            self.status_text.insert(tk.END, f"TEAM {team_id}:\n")
            self.status_text.insert(tk.END, f"  Active BCs: {len(active)}\n")

            if len(active) == 0:
                self.status_text.insert(tk.END, "    (none)\n")
            else:
                for bc in active:
                    dead = bc.get("dead_warrior_name")
                    target = bc.get("target_name")
                    fights = bc.get("killer_turns_fought", 0)
                    self.status_text.insert(tk.END, f"    >> {dead} needs to avenge by defeating {target}\n")
                    self.status_text.insert(tk.END, f"       Killer {target} has fought: [{fights}/3]\n")
                    total_bcs += 1

            self.status_text.insert(tk.END, f"  All BCs (including inactive): {len(team.blood_challenges)}\n")
            for bc in team.blood_challenges:
                if bc not in active:
                    dead = bc.get("dead_warrior_name")
                    target = bc.get("target_name")
                    fights = bc.get("killer_turns_fought", 0)
                    status = bc.get("status", "unknown")
                    self.status_text.insert(tk.END, f"    - {dead} -> {target} [INACTIVE] {fights}/3 ({status})\n")

            self.status_text.insert(tk.END, "\n")

        self.status_text.insert(tk.END, "-"*70 + "\n")
        self.status_text.insert(tk.END, f"TOTAL ACTIVE BCs: {total_bcs}\n\n")

        # Alive warriors
        self.status_text.insert(tk.END, "WARRIOR STATUS:\n")
        for team_id in range(1, 4):
            team = self.teams[team_id]
            alive = [w.name for w in team.warriors if not w.is_dead]
            dead = [w.name for w in team.warriors if w.is_dead]
            self.status_text.insert(tk.END, f"  Team {team_id}: Alive: {', '.join(alive) if alive else 'NONE'}")
            if dead:
                self.status_text.insert(tk.END, f" | Dead: {', '.join(dead)}")
            self.status_text.insert(tk.END, "\n")

        self.status_text.see(tk.END)

    def reset(self):
        """Reset everything."""
        self.turn = 0
        self.turn_label.config(text="0")
        self.setup_teams()
        for var in self.fighters.values():
            var.set(False)
        self.update_status()
        self.status_text.insert(tk.END, "\n*** SANDBOX RESET ***\n")

if __name__ == "__main__":
    root = tk.Tk()
    app = BCManualSandbox(root)
    root.mainloop()
