#!/usr/bin/env python3
# =============================================================================
# simulation_tool.py - BLOODSPIRE Simulation & Analytics Tool
# =============================================================================
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import json
import os
import random
import copy
import datetime
from typing import List, Dict, Any

# Import game modules
import team as T
import warrior as W
import matchmaking as MM
import combat as C
import strategy as S
from armor import ARMOR_TIERS, HELM_TIERS
import armor as A_MOD
from warrior import TRIGGERS, FIGHTING_STYLES, AIM_DEFENSE_POINTS
from weapons import WEAPONS
import weapons as WPN_MOD
from combat_debug_logger import CombatDebugLogger

# ---------------------------------------------------------------------------
# STRUCTURED DATA LOGGER
# ---------------------------------------------------------------------------

class SimDataLogger(CombatDebugLogger):
    """Subclass of CombatDebugLogger that captures structured data for analytics."""
    def __init__(self):
        super().__init__()
        self.damage_events = []
        self.endurance_history = [] # (minute, name, endurance, apm, style)
        self.exhaustion_stats = {} # name: {p2_min: int, p3_min: int}
        self.finesse_triggers = 0
        self.signature_triggers = 0

    def log_damage(self, attacker_name: str, defender_name: str, margin: int, steps: dict, 
                   sig_floor: int, ca_bonus: int, net_damage: int):
        # We capture the weapon from the ceiling breakdown or context
        self.damage_events.append({
            'attacker': attacker_name,
            'net': net_damage,
            'margin': margin,
            'soak': steps.get('armor_def', 0) - steps.get('final_armor', 0),
            'precision_bypass': steps.get('total_precision_bypass', 0.0),
            'is_signature': sig_floor is not None and sig_floor > steps.get('net_pre_mods', 0)
        })

    def log_minute_start(self, minute, state_a, state_b, apm_a, apm_b, strat_a, strat_b):
        for st, apm, strat in [(state_a, apm_a, strat_a), (state_b, apm_b, strat_b)]:
            name = st.warrior.name
            self.endurance_history.append((minute, name, st.endurance, apm, strat.style))
            
            if name not in self.exhaustion_stats:
                self.exhaustion_stats[name] = {'p2': None, 'p3': None}
            
            p2_thresh = st.warrior.max_endurance * 0.25
            if st.endurance <= p2_thresh and self.exhaustion_stats[name]['p2'] is None:
                self.exhaustion_stats[name]['p2'] = minute
            if st.endurance <= 0 and self.exhaustion_stats[name]['p3'] is None:
                self.exhaustion_stats[name]['p3'] = minute

# ---------------------------------------------------------------------------
# MAIN TOOL UI
# ---------------------------------------------------------------------------

class BloodspireSimTool:
    def __init__(self, root):
        self.root = root
        self.root.title("Bloodspire Arena Simulation & Analytics")
        self.root.geometry("1100x800")
        
        self.warrior_pool = [] # List of (Warrior, Team)
        self.uploads_folder = tk.StringVar(value=os.path.join(os.getcwd(), "saves", "league", "turn_0001"))
        self.sim_type = tk.StringVar(value="Weapon Damage Analysis")
        self.report_content = ""

        # 1v1 Setup Variables
        self.w1_base = tk.StringVar()
        self.w1_armor = tk.StringVar(value="Cloth")
        self.w1_helm = tk.StringVar(value="None")
        self.w1_primary = tk.StringVar(value="Short Sword")
        self.w1_secondary = tk.StringVar(value="Open Hand")
        self.w1_backup = tk.StringVar(value="None")
        self.w1_trigger = tk.StringVar(value="Always")
        self.w1_style = tk.StringVar(value="Strike")
        self.w1_activity = tk.IntVar(value=5)
        self.w1_aim = tk.StringVar(value="None")
        self.w1_def = tk.StringVar(value="Chest")

        self.w2_base = tk.StringVar()
        self.w2_armor = tk.StringVar(value="Cloth")
        self.w2_helm = tk.StringVar(value="None")
        self.w2_primary = tk.StringVar(value="Short Sword")
        self.w2_secondary = tk.StringVar(value="Open Hand")
        self.w2_backup = tk.StringVar(value="None")
        self.w2_trigger = tk.StringVar(value="Always")
        self.w2_style = tk.StringVar(value="Strike")
        self.w2_activity = tk.IntVar(value=5)
        self.w2_aim = tk.StringVar(value="None")
        self.w2_def = tk.StringVar(value="Chest")
        
        self._build_ui()

    def _build_ui(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # TAB 1: GLOBAL SIMS
        global_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(global_tab, text="Global Analytics")

        # Config Area
        config_frame = ttk.LabelFrame(global_tab, text="Simulation Config", padding="10")
        config_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(config_frame, text="Uploads Folder:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(config_frame, textvariable=self.uploads_folder, width=80).grid(row=0, column=1, padx=5)
        ttk.Button(config_frame, text="Browse & Load", command=self._browse_folder).grid(row=0, column=2)

        ttk.Label(config_frame, text="Simulation Mode:").grid(row=1, column=0, sticky=tk.W, pady=10)
        modes = [
            "Weapon Damage Analysis",
            "Endurance & Exhaustion Analysis",
            "Encumbrance & Penalty Analysis",
            "Full Turn Dry-Run",
        ]
        self.mode_combo = ttk.Combobox(config_frame, textvariable=self.sim_type, values=modes, state="readonly", width=35)
        self.mode_combo.grid(row=1, column=1, sticky=tk.W, padx=5)
        ttk.Button(config_frame, text="START GLOBAL SIM", command=self._run_sim).grid(row=1, column=2)

        # TAB 2: 1v1 MATCHUP
        matchup_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(matchup_tab, text="1 v 1 Custom Matchup")

        # Matchup Grid
        m_grid = ttk.Frame(matchup_tab)
        m_grid.pack(fill=tk.X)

        wpn_list = sorted([w.display for w in WEAPONS.values()])
        arm_list = ARMOR_TIERS + ["None"]
        hlm_list = HELM_TIERS + ["None"]

        def create_w_config(parent, title, var_prefix):
            frame = ttk.LabelFrame(parent, text=title, padding="10")
            
            # Warrior Selection
            ttk.Label(frame, text="Base Warrior:").grid(row=0, column=0, sticky=tk.W)
            combo = ttk.Combobox(frame, textvariable=getattr(self, f"{var_prefix}_base"), state="readonly", width=40)
            combo.grid(row=0, column=1, sticky=tk.W, pady=2)
            setattr(self, f"{var_prefix}_combo", combo)

            # Gear
            ttk.Label(frame, text="Armor:").grid(row=1, column=0, sticky=tk.W)
            ttk.Combobox(frame, textvariable=getattr(self, f"{var_prefix}_armor"), values=arm_list, state="readonly").grid(row=1, column=1, sticky=tk.W)

            ttk.Label(frame, text="Helm:").grid(row=2, column=0, sticky=tk.W)
            ttk.Combobox(frame, textvariable=getattr(self, f"{var_prefix}_helm"), values=hlm_list, state="readonly").grid(row=2, column=1, sticky=tk.W)

            ttk.Label(frame, text="Primary:").grid(row=3, column=0, sticky=tk.W)
            ttk.Combobox(frame, textvariable=getattr(self, f"{var_prefix}_primary"), values=wpn_list, state="readonly").grid(row=3, column=1, sticky=tk.W)

            ttk.Label(frame, text="Secondary:").grid(row=4, column=0, sticky=tk.W)
            ttk.Combobox(frame, textvariable=getattr(self, f"{var_prefix}_secondary"), values=wpn_list, state="readonly").grid(row=4, column=1, sticky=tk.W)

            ttk.Label(frame, text="Backup:").grid(row=5, column=0, sticky=tk.W)
            ttk.Combobox(frame, textvariable=getattr(self, f"{var_prefix}_backup"), values=["None"] + wpn_list, state="readonly").grid(row=5, column=1, sticky=tk.W)

            # Strategy
            ttk.Separator(frame, orient=tk.HORIZONTAL).grid(row=6, column=0, columnspan=2, sticky="ew", pady=10)

            ttk.Label(frame, text="Trigger:").grid(row=7, column=0, sticky=tk.W)
            ttk.Combobox(frame, textvariable=getattr(self, f"{var_prefix}_trigger"), values=TRIGGERS, state="readonly").grid(row=7, column=1, sticky=tk.W)

            ttk.Label(frame, text="Style:").grid(row=8, column=0, sticky=tk.W)
            ttk.Combobox(frame, textvariable=getattr(self, f"{var_prefix}_style"), values=FIGHTING_STYLES, state="readonly").grid(row=8, column=1, sticky=tk.W)

            ttk.Label(frame, text="Activity:").grid(row=9, column=0, sticky=tk.W)
            ttk.Combobox(frame, textvariable=getattr(self, f"{var_prefix}_activity"), values=list(range(10)), state="readonly").grid(row=9, column=1, sticky=tk.W)

            ttk.Label(frame, text="Aim Pt:").grid(row=10, column=0, sticky=tk.W)
            ttk.Combobox(frame, textvariable=getattr(self, f"{var_prefix}_aim"), values=AIM_DEFENSE_POINTS, state="readonly").grid(row=10, column=1, sticky=tk.W)

            ttk.Label(frame, text="Def Pt:").grid(row=11, column=0, sticky=tk.W)
            ttk.Combobox(frame, textvariable=getattr(self, f"{var_prefix}_def"), values=AIM_DEFENSE_POINTS, state="readonly").grid(row=11, column=1, sticky=tk.W)
            
            return frame

        create_w_config(m_grid, "Warrior 1 (Attacker Context)", "w1").grid(row=0, column=0, padx=10, sticky=tk.NSEW)
        create_w_config(m_grid, "Warrior 2 (Opponent Context)", "w2").grid(row=0, column=1, padx=10, sticky=tk.NSEW)

        ttk.Button(matchup_tab, text="RUN 1 v 1 SIMULATION", command=self._sim_1v1_matchup).pack(pady=10)

        # Shared Output Area (at the bottom)
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Output Area
        self.text_area = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, font=("Consolas", 10))
        self.text_area.pack(fill=tk.BOTH, expand=True)

        # Action Bar
        btn_frame = ttk.Frame(main_frame, padding="5")
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Clear Window", command=lambda: self.text_area.delete(1.0, tk.END)).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Download Report (.txt)", command=self._export_report).pack(side=tk.RIGHT)

        # Load initial pool
        self._refresh_warrior_pool()

    def _browse_folder(self):
        path = filedialog.askdirectory()
        if path: 
            self.uploads_folder.set(path)
            self._refresh_warrior_pool()

    def _refresh_warrior_pool(self):
        teams = self._get_warriors_from_uploads()
        self.warrior_pool = []
        names = []
        for team in teams:
            for w_obj in team.active_warriors:
                self.warrior_pool.append((w_obj, team))
                names.append(f"{w_obj.name} ({team.manager_name}) [{w_obj.race.name}]")
        
        self.w1_combo['values'] = names
        self.w2_combo['values'] = names

    def _get_warriors_from_uploads(self) -> List[T.Team]:
        path = self.uploads_folder.get()
        if not os.path.exists(path): return []
        
        teams = []
        for fn in os.listdir(path):
            if fn.startswith("upload_") and fn.endswith(".json"):
                try:
                    with open(os.path.join(path, fn), 'r') as f:
                        data = json.load(f)
                        team = T.Team.from_dict(data["team"])
                        team.manager_name = data["manager_name"]
                        teams.append(team)
                except Exception as e:
                    self.text_area.insert(tk.END, f"Error loading {fn}: {e}\n")
        return teams

    def _run_sim(self):
        teams = self._get_warriors_from_uploads()
        if not teams:
            self.text_area.insert(tk.END, "No valid upload files found.\n")
            return

        mode = self.sim_type.get()
        self.text_area.delete(1.0, tk.END)
        self.text_area.insert(tk.END, f"--- Starting {mode} ---\n")
        self.text_area.insert(tk.END, f"Processing {len(teams)} teams...\n")
        self.root.update()

        if mode == "Weapon Damage Analysis":
            self._sim_weapon_lethality(teams)
        elif mode == "Endurance & Exhaustion Analysis":
            self._sim_endurance_burn(teams)
        elif mode == "Encumbrance & Penalty Analysis":
            self._sim_encumbrance_audit(teams)
        elif mode == "Full Turn Dry-Run":
            self._sim_full_dry_run(teams)

    # -----------------------------------------------------------------------
    # SIM 1: WEAPON DAMAGE
    # -----------------------------------------------------------------------
    def _sim_weapon_lethality(self, teams):
        card = MM.build_global_fight_card(teams, [], champion_state={})
        weapon_stats = {} # {wpn_name: {total_dmg, hits, actions, soak, bypass_total, sig_hits}}
        total_meta_dmg = 0
        total_meta_hits = 0
        
        iterations = 50 # Run every bout 50 times for stable averages
        for bout in card:
            for _ in range(iterations):
                w1 = copy.deepcopy(bout.player_warrior)
                w2 = copy.deepcopy(bout.opponent)
                logger = SimDataLogger()
                engine = C.CombatEngine(w1, w2, debug_logger=logger)
                engine.resolve_fight()
                
                for event in logger.damage_events:
                    # Determine which side of the bout the attacker is on to get the weapon
                    wpn_name = w1.primary_weapon if event['attacker'] == w1.name else w2.primary_weapon
                    if wpn_name not in weapon_stats:
                        weapon_stats[wpn_name] = {'dmg': 0, 'hits': 0, 'soak': 0, 'bypass': 0.0, 'sig': 0}
                    
                    s = weapon_stats[wpn_name]
                    s['dmg'] += event['net']
                    s['hits'] += 1
                    s['soak'] += event['soak']
                    s['bypass'] += event['precision_bypass']
                    if event['is_signature']: s['sig'] += 1
                    total_meta_dmg += event['net']
                    total_meta_hits += 1

        # Build Report
        lines = [f"\nWEAPON DAMAGE ANALYSIS (Averaged over {iterations} iterations per bout)", "="*90]
        
        # Add Legend Section
        lines.append("COLUMN LEGEND:")
        lines.append(f"{'  AVG DMG':<12}: Average net damage dealt per successful hit (after armor).")
        lines.append(f"{'  AVG SOAK':<12}: Average damage points 'soaked' (blocked) by the defender's armor.")
        lines.append(f"{'  FINESSE %':<12}: % of hits where Dex/Int 'Precision Bypass' helped ignore armor.")
        lines.append(f"{'  SIG RATE':<12}: % of hits where a high-skill 'Signature' damage floor was triggered.")
        lines.append("-" * 90)

        lines.append(f"{'WEAPON':<20} | {'AVG DMG':>8} | {'AVG SOAK':>8} | {'FINESSE %':>10} | {'SIG RATE':>10}")
        lines.append("-" * 90)
        
        sorted_wpns = sorted(weapon_stats.items(), key=lambda x: x[1]['dmg']/max(1, x[1]['hits']), reverse=True)
        for name, data in sorted_wpns:
            avg_dmg = data['dmg'] / max(1, data['hits'])
            avg_soak = data['soak'] / max(1, data['hits'])
            finesse = (data['bypass'] / max(1, data['hits'])) * 100
            sig_rate = (data['sig'] / max(1, data['hits'])) * 100
            lines.append(f"{name:<20} | {avg_dmg:>8.1f} | {avg_soak:>8.1f} | {finesse:>9.1f}% | {sig_rate:>9.1f}%")

        # Balance Suggestions
        if total_meta_hits > 0:
            meta_avg = total_meta_dmg / total_meta_hits
            lines.append(f"\nBALANCE SUGGESTIONS (Meta Avg DMG: {meta_avg:.1f})")
            lines.append("-" * 90)
            
            op_threshold = meta_avg * 1.25
            up_threshold = meta_avg * 0.75
            
            suggestions_found = False
            for name, data in sorted_wpns:
                avg_dmg = data['dmg'] / max(1, data['hits'])
                avg_soak = data['soak'] / max(1, data['hits'])
                finesse_val = (data['bypass'] / max(1, data['hits'])) * 100
                
                try:
                    wpn = WPN.get_weapon(name)
                    is_heavy = wpn.weight >= 5.0
                    is_light = wpn.weight < 2.5
                except:
                    is_heavy = is_light = False

                if avg_dmg > op_threshold:
                    lines.append(f"[!] POTENTIAL OP: {name} ({avg_dmg:.1f} dmg)")
                    if is_heavy:
                        lines.append(f"    -> Heavy weapon scaling (Weight/STR) might be tuned too aggressively.")
                    elif is_light:
                        lines.append(f"    -> Light weapon finesse scaling or base damage might be tuned too high.")
                    suggestions_found = True
                elif avg_dmg < up_threshold:
                    lines.append(f"[?] POTENTIAL UP: {name} ({avg_dmg:.1f} dmg)")
                    if is_heavy:
                        lines.append(f"    -> Consider increasing Strength scaling or base weight-damage multiplier.")
                    elif is_light:
                        if finesse_val < 15:
                            lines.append(f"    -> Low Finesse impact ({finesse_val:.1f}%). Consider boosting Dex/Int bypass influence.")
                        else:
                            lines.append(f"    -> Finesse is working, but base damage or skill bonuses may be too low.")
                    suggestions_found = True
                
                # Check for "Armor Stalled" weapons
                if avg_soak > avg_dmg * 1.5:
                    lines.append(f"[*] ARMOR STALLED: {name} is losing massive damage to soak ({avg_soak:.1f} soak vs {avg_dmg:.1f} dmg).")
                    lines.append(f"    -> Consider adding Armor Piercing flag or increasing precision bypass influence.")
                    suggestions_found = True
            
            if not suggestions_found:
                lines.append("No major weapon outliers detected. Balance looks stable.")
            
        self.report_content = "\n".join(lines)
        self.text_area.insert(tk.END, self.report_content)

    # -----------------------------------------------------------------------
    # SIM 5: 1 v 1 MATCHUP (Sandbox)
    # -----------------------------------------------------------------------
    def _sim_1v1_matchup(self):
        idx1 = self.w1_combo.current()
        idx2 = self.w2_combo.current()

        if idx1 < 0 or idx2 < 0:
            messagebox.showwarning("Incomplete Selection", "Please select both warriors from the dropdowns.")
            return

        self.text_area.delete(1.0, tk.END)
        self.text_area.insert(tk.END, "--- Initializing 1v1 Custom Matchup ---\n\n")

        # Setup Warriors
        def setup_sim_warrior(idx, prefix):
            orig_w, orig_t = self.warrior_pool[idx]
            w = copy.deepcopy(orig_w)
            # Gear Overrides
            w.armor = getattr(self, f"{prefix}_armor").get()
            w.helm = getattr(self, f"{prefix}_helm").get()
            w.primary_weapon = getattr(self, f"{prefix}_primary").get()
            w.secondary_weapon = getattr(self, f"{prefix}_secondary").get()
            
            bak = getattr(self, f"{prefix}_backup").get()
            w.backup_weapon = None if bak == "None" else bak

            # Strategy Override (1 trigger as requested)
            w.strategies = [W.Strategy(
                trigger=getattr(self, f"{prefix}_trigger").get(),
                style=getattr(self, f"{prefix}_style").get(),
                activity=getattr(self, f"{prefix}_activity").get(),
                aim_point=getattr(self, f"{prefix}_aim").get(),
                defense_point=getattr(self, f"{prefix}_def").get()
            )]
            return w, orig_t.manager_name, orig_t.team_name

        sw1, m1, t1 = setup_sim_warrior(idx1, "w1")
        sw2, m2, t2 = setup_sim_warrior(idx2, "w2")

        res = C.run_fight(
            sw1, sw2, team_a_name=t1, team_b_name=t2,
            manager_a_name=m1, manager_b_name=m2
        )

        self.report_content = res.narrative
        self.text_area.insert(tk.END, self.report_content)

    # -----------------------------------------------------------------------
    # SIM 2: ENDURANCE & EXHAUSTION
    # -----------------------------------------------------------------------
    def _sim_endurance_burn(self, teams):
        card = MM.build_global_fight_card(teams, [], champion_state={})
        fights_ended_exhaustion = 0
        p2_times = [] # Minutes until phase 2
        p3_times = [] # Minutes until collapse
        style_base_burns = {} # {style: base_endurance_burn from strategy.py}
        style_burn = {} # {style: [burn_per_action]}

        for bout in card:
            w1, w2 = copy.deepcopy(bout.player_warrior), copy.deepcopy(bout.opponent)
            logger = SimDataLogger()
            res = C.run_fight(w1, w2, debug_logger=logger)
            
            if res.exhaustion_end: 
                fights_ended_exhaustion += 1
                # Capture the collapse minute from the final result if logger missed it
                p3_times.append(res.minutes_elapsed)
            
            for name, stats in logger.exhaustion_stats.items():
                if stats['p2']: p2_times.append(stats['p2'])
                if stats['p3']: p3_times.append(stats['p3'])
            
            for min_idx, name, end, apm, current_style in logger.endurance_history:
                # Find previous minute to calculate delta spent DURING that minute
                prev_recs = [h for h in logger.endurance_history if h[1] == name and h[0] == min_idx - 1]
                if prev_recs:
                    p_min, p_name, p_end, p_apm, p_style = prev_recs[0]
                    if p_style not in style_burn: style_burn[p_style] = []
                    # Attribute the drain between T and T+1 to the style used during T
                    style_burn[p_style].append((p_end - end) / max(1, p_apm))
                    
                    if p_style not in style_base_burns:
                        style_base_burns[p_style] = S.get_style_props(p_style).endurance_burn

        # Build Report
        lines = ["\nENDURANCE & EXHAUSTION ANALYSIS", "="*70]
        lines.append("COLUMN LEGEND:")
        lines.append(f"{'  AVG BURN':<12}: Total endurance lost per action (Base + Gear Tax + Activity).")
        lines.append(f"{'  BASE BURN':<12}: The intended raw cost of the style from strategy.py.")
        lines.append(f"{'  DISCREPANCY':<12}: Difference between observed and base (mostly gear/penalty overhead).")
        lines.append("-" * 70)

        lines.append(f"Total Fights: {len(card)}")
        lines.append(f"Exhaustion Collapses: {fights_ended_exhaustion} ({fights_ended_exhaustion/max(1,len(card))*100:.1f}%)")
        lines.append(f"Average Minute for Phase II (25%): {sum(p2_times)/max(1,len(p2_times)):.1f}")
        lines.append(f"Average Minute for Phase III (Collapse): {sum(p3_times)/max(1,len(p3_times)):.1f}" if p3_times else "Average Minute for Phase III (Collapse): N/A")
        lines.append("\nBURN RATE BY STYLE (Avg Endurance per Action) - Expected vs Observed")
        lines.append("-" * 70)
        
        lines.append(f"{'STYLE':<20} | {'AVG BURN':>10} | {'BASE BURN':>10} | {'DISCREPANCY'}")
        lines.append("-" * 70)
        
        for style, burns in style_burn.items():
            avg_burn = sum(burns) / max(1, len(burns))
            base_burn = style_base_burns.get(style, 0.0)
            discrepancy = ""
            if abs(avg_burn - base_burn) > 0.1: # Flag if difference is significant
                diff = avg_burn - base_burn
                discrepancy = f"({diff:+.2f} vs base)"
                if avg_burn == 0 and base_burn > 0: discrepancy = "(ERROR: Expected burn, got 0)"
                # Only flag as HIGH if the overhead is more than 5.0 pts above base
                elif diff > 5.0: discrepancy = "(HIGH! Check for overencumbrance)"
                elif avg_burn < base_burn / 2: discrepancy = "(LOW! Check combat logic)"
            lines.append(f"{style:<20} | {avg_burn:>10.2f} | {base_burn:>10.2f} | {discrepancy}")

        self.report_content = "\n".join(lines)
        self.text_area.insert(tk.END, self.report_content)

    # -----------------------------------------------------------------------
    # SIM 3: ENCUMBRANCE AUDIT (Enhanced)
    # -----------------------------------------------------------------------
    def _sim_encumbrance_audit(self, teams):
        lines = ["\nENCUMBRANCE & PENALTY AUDIT", "="*125]
        
        # --- COLUMN LEGEND ---
        lines.append("\nCOLUMN LEGEND:")
        lines.append(f"{'  WARRIOR':<12}: Name of the warrior.")
        lines.append(f"{'  RACE':<12}: The warrior's race.")
        lines.append(f"{'  STR':<12}: The warrior's raw Strength score.")
        lines.append(f"{'  ARMOR':<12}: Main body armor equipped.")
        lines.append(f"{'  PEN %':<12}: Overall encumbrance penalty percentage (0-100%). This is a multiplicative penalty applied to final rolls.")
        lines.append(f"{'  EFF DEX':<12}: Warrior's effective Dexterity after flat armor/helm penalties.")
        lines.append(f"{'  EFF APM':<12}: Warrior's effective Actions Per Minute (APM) after all penalties.")
        lines.append(f"{'  SYNERGY/TAX':<12}: Notes on specific penalties or style interactions.")
        lines.append("-" * 125)
        
        lines.append(f"{'WARRIOR':<20} | {'RACE':<12} | {'STR':>4} | {'ARMOR':<15} | {'PEN %':>6} | {'EFF DEX':>7} | {'EFF APM':>7} | {'SYNERGY/TAX'}")
        lines.append("-" * 125)
        
        red_zone = []
        advice_list = []
        for team in teams:
            for w in team.active_warriors:
                is_dw = w.race.name == "Dwarf"
                p_body = A.armor_penalty_factor(A.get_armor(w.armor).weight, w.strength, is_dw, False)
                p_helm = A.armor_penalty_factor(A.get_armor(w.helm).weight, w.strength, is_dw, True)
                str_penalty = max(p_body, p_helm)
                
                l_pens = A.get_lizardfolk_armor_penalties(w.armor or "None") if w.race.name == "Lizardfolk" else {"dodge_parry_pct": 0.0}
                l_roll_pen = l_pens["dodge_parry_pct"]
                penalty = 1.0 - ((1.0 - str_penalty) * (1.0 - l_roll_pen))
                
                # Base vs Effective
                base_dex = w.dexterity
                eff_dex = A.get_effective_dex_for_race(w.dexterity, w.armor or "None", w.helm or "None", w.race.name)
                
                # Identify the 'Always' baseline strategy for analysis (the 'D' slot)
                strat = w.strategies[-1] # Fallback to last strategy if 'Always' not found
                for s in w.strategies:
                    if s.trigger in ("Always", "Always (Default Loop)"):
                        strat = s
                        break

                sim_state = C._CState(w, w.max_hp, float(w.max_endurance))
                sim_state.armor_penalty = str_penalty
                base_apm = C._calc_apm(w, strat, sim_state)
                
                # Synergy notes
                props = S.get_style_props(strat.style)
                synergy = ""
                if penalty > 0:
                    synergy = "PENALIZED"
                    if l_roll_pen > 0:
                        synergy += " | PHYSIOLOGICAL"
                    if str_penalty > 0:
                        synergy += " | STR OVERAGE"
                    
                    if strat.activity >= 8:
                        synergy += " | HIGH TAX: Activity lvl " + str(strat.activity)
                
                line = f"{w.name:<20} | {w.race.name:<12} | {w.strength:>4} | {w.armor or 'None':<15} | {penalty*100:>5.1f}% | {eff_dex:>7} | {base_apm:>7} | {synergy}"
                lines.append(line)
                if penalty >= 0.20: red_zone.append(w.name)

        if red_zone:
            lines.append("\nRED ZONE WARRIORS (>20% Penalty):")
            lines.append(", ".join(red_zone))

        if advice_list:
            lines.append("\nSTRATEGIC ADVICE")
            lines.append("-" * 100)
            for adv in advice_list:
                lines.append(adv)

        self.report_content = "\n".join(lines)
        self.text_area.insert(tk.END, self.report_content)

    # -----------------------------------------------------------------------
    # SIM 4: FULL TURN DRY-RUN
    # -----------------------------------------------------------------------
    def _sim_full_dry_run(self, teams):
        lines = ["\nFULL TURN DRY-RUN REPORT (Comprehensive Simulation)", "="*120]
        
        # Matchmaking run
        card = MM.build_global_fight_card(teams, [], champion_state={})
        
        # Validation checks
        warrior_counts = {} # name: count
        for bout in card:
            # Use team_id + name to prevent false leaks from common fodder names (e.g., 'DEAD')
            w1 = bout.player_warrior
            k1 = (bout.player_team.team_id, w1.name)
            warrior_counts[k1] = warrior_counts.get(k1, 0) + 1
            
            if bout.fight_type not in ("monster", "peasant"):
                w2 = bout.opponent
                k2 = (bout.opponent_team.team_id, w2.name)
                warrior_counts[k2] = warrior_counts.get(k2, 0) + 1
        
        leaks = [f"Team {k[0]}: {k[1]} ({c} fights)" for k, c in warrior_counts.items() if c > 1]
        skipped = []
        for team in teams:
            for w in team.active_warriors:
                if (int(team.team_id), w.name) not in warrior_counts:
                    skipped.append({"name": w.name, "team": team.team_name, "tid": team.team_id})

        # Validation Summary Table
        lines.append("\nVALIDATION AUDIT")
        lines.append("-" * 45)
        lines.append(f"{'METRIC':<30} | {'VALUE':>10}")
        lines.append("-" * 45)
        lines.append(f"{'Bouts Scheduled':<30} | {len(card):>10}")
        lines.append(f"{'Unique Warriors Participating':<30} | {len(warrior_counts):>10}")
        lines.append(f"{'Matchmaking Leaks (2+ fights)':<30} | {len(leaks):>10}")
        lines.append(f"{'Warriors Skipped (0 fights)':<30} | {len(skipped):>10}")
        lines.append("-" * 45)

        if leaks:
            lines.append("\nMATCHMAKING LEAKS DETECTED")
            lines.append("-" * 60)
            for l in leaks:
                lines.append(f"  ! {l}")

        if skipped:
            lines.append("\nWARRIORS SKIPPED (Eligible but not matched)")
            lines.append("-" * 60)
            lines.append(f"{'WARRIOR':<25} | {'TEAM (ID)':<35}")
            lines.append("-" * 60)
            for s in skipped:
                lines.append(f"{s['name']:<25} | {s['team']:<28} ({s['tid']})")

        lines.append("-" * 120)

        # Result tracking containers
        mgr_stats = {} # manager_name: {team_name: {w, l, k}}
        bouts_log = [] # List of formatted strings
        race_pairs = {} # (raceA, raceB) -> {a_wins, b_wins, draws, total}

        deaths = 0
        for bout in card:
            # Memory run (deep copy to avoid mutating the source warriors)
            w1, w2 = copy.deepcopy(bout.player_warrior), copy.deepcopy(bout.opponent)
            res = C.run_fight(w1, w2)
            
            p_won = res.winner and res.winner.name == w1.name
            o_won = res.winner and res.winner.name == w2.name
            is_draw = res.winner is None

            if res.loser_died: 
                deaths += 1

            # --- Manager Records ---
            def update_stats(team, won, killed):
                m = team.manager_name
                t = team.team_name
                if m not in mgr_stats: mgr_stats[m] = {}
                if t not in mgr_stats[m]: mgr_stats[m][t] = {'w': 0, 'l': 0, 'k': 0}
                if won: mgr_stats[m][t]['w'] += 1
                else: mgr_stats[m][t]['l'] += 1
                if killed: mgr_stats[m][t]['k'] += 1

            if bout.player_team.team_id >= 0:
                update_stats(bout.player_team, p_won, p_won and res.loser_died)
            if bout.opponent_team.team_id >= 0:
                update_stats(bout.opponent_team, o_won, o_won and res.loser_died)

            # --- Matchup Detail ---
            res_label = "WIN" if p_won else ("LOSS" if o_won else "DRAW")
            w1_info = f"{w1.name} ({w1.race.name})"
            w2_info = f"{w2.name} ({w2.race.name})"
            log_line = f"{w1_info:<33} vs {w2_info:<33} | {res_label:<4} | {res.minutes_elapsed:>2}m"
            if res.loser_died:
                log_line += " (SLAIN)" if not p_won else " (KILLED)"
            bouts_log.append(log_line)

            # --- Race Dynamics ---
            r1, r2 = w1.race.name, w2.race.name
            pair = tuple(sorted([r1, r2]))
            if pair not in race_pairs:
                race_pairs[pair] = {'total': 0, 'r1_wins': 0, 'r2_wins': 0, 'kills': 0, 'r1_name': pair[0], 'r2_name': pair[1]}
            rp = race_pairs[pair]
            rp['total'] += 1
            if res.loser_died:
                rp['kills'] += 1
            if not is_draw:
                if res.winner.race.name == rp['r1_name']: rp['r1_wins'] += 1
                else: rp['r2_wins'] += 1

        # Build Final Sections
        lines.append("\nMANAGER PERFORMANCE (Projected Turn Records)")
        lines.append("-" * 120)
        lines.append(f"{'MANAGER':<25} | {'TEAM':<25} | {'W-L-K':>10} | {'WIN %'}")
        lines.append("-" * 120)
        
        for m_name, t_map in sorted(mgr_stats.items()):
            for t_name, s in t_map.items():
                total = s['w'] + s['l']
                win_pct = (s['w'] / total * 100) if total > 0 else 0
                lines.append(f"{m_name:<25} | {t_name:<25} | {s['w']:>2}-{s['l']:>2}-{s['k']:>2} | {win_pct:>5.1f}%")

        lines.append("\nMATCHUP RESULTS")
        lines.append("-" * 120)
        lines.append(f"{'WARRIOR 1':<33}    {'WARRIOR 2':<33} | {'RES':<4} | {'DUR'}")
        lines.append("-" * 120)
        lines.extend(bouts_log)

        lines.append("\nRACE VS RACE DYNAMICS")
        lines.append("-" * 120)
        lines.append(f"{'PAIRING':<35} | {'W1 WIN %':>10} | {'W2 WIN %':>10} | {'KILLS':>6} | {'SAMPLE'}")
        lines.append("-" * 120)
        
        for pair, data in sorted(race_pairs.items(), key=lambda x: x[1]['total'], reverse=True):
            r1_p = (data['r1_wins'] / data['total'] * 100)
            r2_p = (data['r2_wins'] / data['total'] * 100)
            pair_label = f"{data['r1_name']} vs {data['r2_name']}"
            lines.append(f"{pair_label:<35} | {r1_p:>9.1f}% | {r2_p:>9.1f}% | {data['kills']:>6} | {data['total']:>6}")

        lines.append("\nPROJECTED TOTALS")
        lines.append("-" * 40)
        lines.append(f"Expected Slaughters: {deaths}")
        lines.append(f"PvP Ratio: {sum(1 for b in card if b.fight_type != 'peasant')}/{len(card)}")

        self.report_content = "\n".join(lines)
        self.text_area.insert(tk.END, self.report_content)

    def _export_report(self):
        if not self.report_content:
            self.text_area.insert(tk.END, "\n\nNo report content to export yet. Run a simulation first.")
            return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"sim_report_{ts}.txt"

        # Use asksaveasfilename to let the user choose where to save
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=filename,
            title="Save Simulation Report",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )

        if file_path: # Check if the user didn't cancel the dialog
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.report_content)
                self.text_area.insert(tk.END, f"\n\nReport successfully exported to {file_path}")
            except Exception as e:
                self.text_area.insert(tk.END, f"\n\nError exporting report: {e}")
        else:
            self.text_area.insert(tk.END, "\n\nReport export cancelled.")

if __name__ == "__main__":
    root = tk.Tk()
    app = BloodspireSimTool(root)
    root.mainloop()
