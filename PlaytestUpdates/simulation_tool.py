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
        self.perm_injury_events = []  # {name, damage_pct, chance, qualified, rolled_injury, location, levels}
        self.knockdown_events   = []  # {name, damage_pct, category, chance, roll, knocked}
        self.action_burns: dict = {}  # {style: [self-burn per action]}
        self.severity_counts: dict = {"Light": 0, "Medium": 0, "Heavy": 0}
        self.severity_damage: dict = {"Light": 0, "Medium": 0, "Heavy": 0}

    def log_action_burn(self, _warrior_name: str, style: str, burn: float) -> None:
        self.action_burns.setdefault(style, []).append(burn)

    def log_hit_severity(self, _defender_name: str, damage: int, max_hp: int) -> None:
        pct = damage / max(1, max_hp)
        if pct < 0.19:
            tier = "Light"
        elif pct < 0.34:
            tier = "Medium"
        else:
            tier = "Heavy"
        self.severity_counts[tier] += 1
        self.severity_damage[tier] += damage

    def log_knockdown(self, warrior_name: str, damage: int, max_hp: int,
                      category: str, chance: int, roll: int, knocked: bool):
        self.knockdown_events.append({
            'name':       warrior_name,
            'damage_pct': round(damage / max(1, max_hp) * 100, 1),
            'category':   category,
            'chance':     chance,
            'roll':       roll,
            'knocked':    knocked,
        })

    def log_perm_injury(self, warrior_name: str, damage: int, max_hp: int,
                        chance: int, roll: int, result):  # noqa: ARG002 roll unused here
        location = levels = None
        if result:
            try:
                parts = result.split(" (")
                location = parts[0]
                levels = int(parts[1].split(" ")[0])
            except Exception:
                location = "unknown"
                levels = 1
        self.perm_injury_events.append({
            'name': warrior_name,
            'damage_pct': round(damage / max(1, max_hp) * 100, 1),
            'chance': chance,
            'roll': roll,
            'qualified': chance > 0,
            'rolled_injury': result is not None,
            'location': location,
            'levels': levels,
        })

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
            "Permanent Injury Analysis",
            "Knockdown Analysis",
            "Damage Severity Distribution",
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
        elif mode == "Permanent Injury Analysis":
            self._sim_perm_injury(teams)
        elif mode == "Knockdown Analysis":
            self._sim_knockdown(teams)
        elif mode == "Damage Severity Distribution":
            self._sim_damage_severity(teams)
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
        p2_times = []
        p3_times = []
        style_base_burns = {}
        style_self_burn  = {}  # {style: [self-burn per action]} — from _update_endurance only
        style_total_burn = {}  # {style: [total drain per action]} — includes external sources

        for bout in card:
            w1, w2 = copy.deepcopy(bout.player_warrior), copy.deepcopy(bout.opponent)
            logger = SimDataLogger()
            res = C.run_fight(w1, w2, debug_logger=logger)

            if res.exhaustion_end:
                fights_ended_exhaustion += 1
                p3_times.append(res.minutes_elapsed)

            for name, stats in logger.exhaustion_stats.items():
                if stats['p2']: p2_times.append(stats['p2'])
                if stats['p3']: p3_times.append(stats['p3'])

            # Self-burn: clean per-action values logged by _update_endurance
            for style, burns in logger.action_burns.items():
                style_self_burn.setdefault(style, []).extend(burns)
                if style not in style_base_burns:
                    style_base_burns[style] = S.get_style_props(style).endurance_burn

            # Total burn: minute-delta metric (includes anxiously_awaits / intimidate drain)
            for min_idx, name, end, _, _ in logger.endurance_history:
                prev_recs = [h for h in logger.endurance_history if h[1] == name and h[0] == min_idx - 1]
                if prev_recs:
                    _, _, p_end, p_apm, p_style = prev_recs[0]
                    style_total_burn.setdefault(p_style, []).append((p_end - end) / max(1, p_apm))
                    if p_style not in style_base_burns:
                        style_base_burns[p_style] = S.get_style_props(p_style).endurance_burn

        # Build Report
        lines = ["\nENDURANCE & EXHAUSTION ANALYSIS", "=" * 80]
        lines.append("COLUMN LEGEND:")
        lines.append(f"{'  SELF BURN':<14}: Endurance spent by this warrior's own actions (gear + style + activity).")
        lines.append(f"{'  TOTAL BURN':<14}: SELF BURN + external drain (anxiously_awaits, intimidate from opponent).")
        lines.append(f"{'  BASE BURN':<14}: Raw style cost from strategy.py (the tuning target).")
        lines.append(f"{'  OVERHEAD':<14}: SELF BURN minus BASE BURN (gear/activity overhead on top of base).")
        lines.append("-" * 80)

        lines.append(f"Total Fights: {len(card)}")
        lines.append(f"Exhaustion Collapses: {fights_ended_exhaustion} ({fights_ended_exhaustion/max(1,len(card))*100:.1f}%)")
        lines.append(f"Average Minute for Phase II (25%): {sum(p2_times)/max(1,len(p2_times)):.1f}")
        lines.append(f"Average Minute for Phase III (Collapse): {sum(p3_times)/max(1,len(p3_times)):.1f}" if p3_times else "Average Minute for Phase III (Collapse): N/A")
        lines.append("\nBURN RATE BY STYLE (Avg Endurance per Action)")
        lines.append("-" * 80)
        lines.append(f"{'STYLE':<20} | {'SELF BURN':>10} | {'TOTAL BURN':>10} | {'BASE BURN':>10} | {'OVERHEAD'}")
        lines.append("-" * 80)

        all_styles = sorted(set(list(style_self_burn.keys()) + list(style_total_burn.keys())))
        for style in all_styles:
            self_burns  = style_self_burn.get(style, [])
            total_burns = style_total_burn.get(style, [])
            base_burn   = style_base_burns.get(style, 0.0)
            avg_self  = sum(self_burns)  / max(1, len(self_burns))  if self_burns  else 0.0
            avg_total = sum(total_burns) / max(1, len(total_burns)) if total_burns else 0.0
            overhead  = avg_self - base_burn
            overhead_str = f"({overhead:+.2f})"
            lines.append(
                f"{style:<20} | {avg_self:>10.2f} | {avg_total:>10.2f} | {base_burn:>10.2f} | {overhead_str}"
            )

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
    # SIM 4: PERMANENT INJURY ANALYSIS
    # -----------------------------------------------------------------------
    def _sim_perm_injury(self, teams):
        ITERATIONS = 30
        card = MM.build_global_fight_card(teams, [], champion_state={})
        if not card:
            self.text_area.insert(tk.END, "No fights to simulate.\n")
            return

        self.text_area.insert(tk.END, f"Running {ITERATIONS} iterations × {len(card)} bouts...\n")
        self.root.update()

        total_fights = 0
        total_hits_checked = 0
        total_qualified = 0   # hits meeting 20% HP threshold
        total_rolled = 0      # dice said "injury"
        total_applied = 0     # after 2-event-per-warrior cap
        cap_triggered = 0     # fights where cap actually fired

        fights_rolled   = {0: 0, 1: 0, 2: 0, "3+": 0}
        fights_applied  = {0: 0, 1: 0, 2: 0}

        loc_stats   = {}   # {location: {'count': N, 'total_levels': X}}
        level_dist  = {}   # {level_int: count}

        LOCS = ['head', 'chest', 'abdomen', 'primary_arm', 'secondary_arm',
                'primary_leg', 'secondary_leg']

        for _ in range(ITERATIONS):
            for bout in card:
                w1 = copy.deepcopy(bout.player_warrior)
                w2 = copy.deepcopy(bout.opponent)
                logger = SimDataLogger()
                C.run_fight(w1, w2, debug_logger=logger)
                total_fights += 1

                events = logger.perm_injury_events
                total_hits_checked += len(events)
                total_qualified    += sum(1 for e in events if e['qualified'])

                w1_rolled = sum(1 for e in events if e['name'] == w1.name and e['rolled_injury'])
                w2_rolled = sum(1 for e in events if e['name'] == w2.name and e['rolled_injury'])
                fight_rolled   = w1_rolled + w2_rolled
                fight_applied  = min(w1_rolled, 2) + min(w2_rolled, 2)

                total_rolled  += fight_rolled
                total_applied += fight_applied

                if w1_rolled > 2 or w2_rolled > 2:
                    cap_triggered += 1

                bucket = fight_rolled if fight_rolled <= 2 else "3+"
                fights_rolled[bucket] = fights_rolled.get(bucket, 0) + 1

                applied_bucket = min(fight_applied, 2)
                fights_applied[applied_bucket] = fights_applied.get(applied_bucket, 0) + 1

                for e in events:
                    if not e['rolled_injury']:
                        continue
                    loc = e['location'] or 'unknown'
                    lvl = e['levels'] or 1
                    if loc not in loc_stats:
                        loc_stats[loc] = {'count': 0, 'total_levels': 0}
                    loc_stats[loc]['count'] += 1
                    loc_stats[loc]['total_levels'] += lvl
                    level_dist[lvl] = level_dist.get(lvl, 0) + 1

        tf = max(1, total_fights)
        tq = max(1, total_qualified)
        tr = max(1, total_rolled)

        lines = [
            f"\nPERMANENT INJURY ANALYSIS  "
            f"({ITERATIONS} iterations × {len(card)} bouts = {total_fights} total fights)",
            "=" * 70,
            "",
            "WHAT THIS REPORT MEASURES",
            "-" * 70,
            "  This sim runs every fight on the current turn card 30 times and tracks how",
            "  permanent injuries are generated, capped, and distributed.",
            "",
            "  SECTION GUIDE:",
            "  HIT QUALIFICATION   — Of all successful hits, how many are hard enough to",
            "                        even roll for a perm injury (>25% of max HP).  Shows",
            "                        the roll success rate and how many survive the cap.",
            "",
            "  ROLLED PER FIGHT    — How many times per fight the injury dice said YES",
            "                        (before the 2-event-per-warrior cap is enforced).",
            "                        '3+ events' = fights where the cap actually fired.",
            "",
            "  APPLIED PER FIGHT   — Injuries that actually stuck after the cap.  Max 2",
            "                        per warrior per fight, so max 4 per bout total.",
            "                        Avg per fight here is your primary balance number —",
            "                        target is roughly 0.3 to 0.8 for a healthy turn.",
            "",
            "  LEVEL DISTRIBUTION  — When an injury is rolled, it lands at level 1 (minor),",
            "                        level 2 (serious), or level 3 (severe).  Level is set",
            "                        by how big the hit was relative to max HP:",
            "                          25–45% HP dealt  → Level 1  (Minor)",
            "                          >45% HP dealt    → Level 2  (Serious)",
            "                          >65% HP dealt    → Level 3  (Severe)",
            "                        Levels stack across fights on the same location.",
            "                        Level 9 on any location is fatal.",
            "",
            "  LOCATION BREAKDOWN  — Which body parts are taking injuries and how bad.",
            "                        'Events' counts individual injury rolls; 'Avg Level'",
            "                        is the average level per event (not cumulative).",
            "                        Head injuries are most dangerous (they stack fast).",
            "",
            "=" * 70,
            "",
            "HIT QUALIFICATION",
            "-" * 70,
            f"  {'Total hits checked:':<40} {total_hits_checked:>8,}",
            f"  {'Hits meeting 25% HP threshold:':<40} {total_qualified:>8,}"
            f"  ({total_qualified / max(1, total_hits_checked) * 100:.1f}%)",
            f"  {'Of those — dice rolled an injury:':<40} {total_rolled:>8,}"
            f"  ({total_rolled / tq * 100:.1f}% of qualified)",
            f"  {'Applied after 2-event-per-warrior cap:':<40} {total_applied:>8,}"
            f"  ({total_applied / tr * 100:.1f}% of rolled)",
            "",
            "ROLLED INJURIES PER FIGHT  (dice successes, before cap)",
            "-" * 70,
            f"  {'0 events':<30} {fights_rolled[0]:>6}  ({fights_rolled[0] / tf * 100:.1f}%)",
            f"  {'1 event':<30} {fights_rolled[1]:>6}  ({fights_rolled[1] / tf * 100:.1f}%)",
            f"  {'2 events':<30} {fights_rolled[2]:>6}  ({fights_rolled[2] / tf * 100:.1f}%)",
            f"  {'3+ events  (cap fired on these)':<30} {fights_rolled['3+']:>6}"
            f"  ({fights_rolled['3+'] / tf * 100:.1f}%)",
            f"  {'Avg per fight:':<30} {total_rolled / tf:>8.2f}",
            "",
            "APPLIED INJURIES PER FIGHT  (after cap — max 2 per warrior)",
            "-" * 70,
            f"  {'0 applied  (clean fight)':<30} {fights_applied[0]:>6}  ({fights_applied[0] / tf * 100:.1f}%)",
            f"  {'1 applied':<30} {fights_applied[1]:>6}  ({fights_applied[1] / tf * 100:.1f}%)",
            f"  {'2+ applied':<30} {fights_applied[2]:>6}  ({fights_applied[2] / tf * 100:.1f}%)",
            f"  {'Avg per fight:':<30} {total_applied / tf:>8.2f}",
            f"  {'Cap triggered in:':<30} {cap_triggered:>6} fights  ({cap_triggered / tf * 100:.1f}%)",
            "",
        ]

        if level_dist:
            total_lvl = sum(level_dist.values())
            lines += [
                "INJURY LEVEL DISTRIBUTION  (from all rolled events)",
                "-" * 70,
            ]
            labels = {1: "Level 1  (Minor)", 2: "Level 2  (Serious)", 3: "Level 3  (Severe)"}
            for lvl in sorted(level_dist):
                lbl = labels.get(lvl, f"Level {lvl}")
                cnt = level_dist[lvl]
                lines.append(f"  {lbl:<30} {cnt:>6}  ({cnt / total_lvl * 100:.1f}%)")
            lines.append("")

        if loc_stats:
            lines += [
                "INJURY LOCATION BREAKDOWN  (rolled events by location)",
                "-" * 70,
                f"  {'LOCATION':<22} {'EVENTS':>8}  {'AVG LEVEL':>10}",
                "-" * 70,
            ]
            for loc in LOCS:
                if loc in loc_stats:
                    d = loc_stats[loc]
                    avg = d['total_levels'] / max(1, d['count'])
                    lines.append(
                        f"  {loc.replace('_', ' ').title():<22} {d['count']:>8}  {avg:>10.1f}"
                    )
            for loc in sorted(loc_stats):
                if loc not in LOCS:
                    d = loc_stats[loc]
                    avg = d['total_levels'] / max(1, d['count'])
                    lines.append(
                        f"  {loc.replace('_', ' ').title():<22} {d['count']:>8}  {avg:>10.1f}"
                    )

        self.report_content = "\n".join(lines)
        self.text_area.insert(tk.END, self.report_content)

    # -----------------------------------------------------------------------
    # SIM 5: KNOCKDOWN ANALYSIS
    # -----------------------------------------------------------------------
    def _sim_knockdown(self, teams):
        ITERATIONS = 30
        card = MM.build_global_fight_card(teams, [], champion_state={})
        if not card:
            self.text_area.insert(tk.END, "No fights to simulate.\n")
            return

        self.text_area.insert(tk.END, f"Running {ITERATIONS} iterations × {len(card)} bouts...\n")
        self.root.update()

        total_fights   = 0
        total_checks   = 0
        total_knocked  = 0

        fights_dist    = {0: 0, 1: 0, 2: 0, "3+": 0}

        # Per weapon category: {cat: {checks, knocked, total_chance, total_dmg_pct}}
        cat_stats = {}

        # Raw roll data for hit vs miss comparison
        knocked_rolls   = []   # roll values when KD fired
        knocked_chances = []   # chance values when KD fired
        missed_rolls    = []   # roll values when KD missed
        missed_chances  = []   # chance values when KD missed

        # Damage % buckets when a KD actually fires
        dmg_buckets = {"<15%": 0, "15-25%": 0, "25-40%": 0, "40-60%": 0, ">60%": 0}

        for _ in range(ITERATIONS):
            for bout in card:
                w1 = copy.deepcopy(bout.player_warrior)
                w2 = copy.deepcopy(bout.opponent)
                logger = SimDataLogger()
                C.run_fight(w1, w2, debug_logger=logger)
                total_fights += 1

                events   = logger.knockdown_events
                fight_kd = sum(1 for e in events if e['knocked'])

                total_checks  += len(events)
                total_knocked += fight_kd

                bucket = fight_kd if fight_kd <= 2 else "3+"
                fights_dist[bucket] = fights_dist.get(bucket, 0) + 1

                for e in events:
                    cat = e['category'] or "Other"
                    if cat not in cat_stats:
                        cat_stats[cat] = {'checks': 0, 'knocked': 0,
                                          'total_chance': 0, 'total_dmg_pct': 0.0}
                    cs = cat_stats[cat]
                    cs['checks']      += 1
                    cs['total_chance'] += e['chance']
                    cs['total_dmg_pct'] += e['damage_pct']
                    if e['knocked']:
                        cs['knocked'] += 1
                        knocked_rolls.append(e['roll'])
                        knocked_chances.append(e['chance'])
                        dpct = e['damage_pct']
                        if dpct < 15:
                            dmg_buckets["<15%"] += 1
                        elif dpct < 25:
                            dmg_buckets["15-25%"] += 1
                        elif dpct < 40:
                            dmg_buckets["25-40%"] += 1
                        elif dpct < 60:
                            dmg_buckets["40-60%"] += 1
                        else:
                            dmg_buckets[">60%"] += 1
                    else:
                        missed_rolls.append(e['roll'])
                        missed_chances.append(e['chance'])

        tf  = max(1, total_fights)
        tc  = max(1, total_checks)
        tkd = max(1, total_knocked)

        lines = [
            f"\nKNOCKDOWN ANALYSIS  "
            f"({ITERATIONS} iterations × {len(card)} bouts = {total_fights} total fights)",
            "=" * 70,
            "",
            "WHAT THIS REPORT MEASURES",
            "-" * 70,
            "  Every successful hit triggers a knockdown check. This report tracks how",
            "  often that check succeeds and what drives it.",
            "",
            "  SECTION GUIDE:",
            "  OVERVIEW            — Top-line knockdown rate across all fights.",
            "                        'Avg per fight' is your primary balance number.",
            "                        Target is roughly 0-1 per fight for most matchups.",
            "",
            "  KDs PER FIGHT       — Distribution of how many knockdowns occur per bout.",
            "                        '3+' fights are the ones players notice as excessive.",
            "",
            "  BY WEAPON CATEGORY  — Which weapon types knock down most often.",
            "                        'Rate' is knockdowns as % of all checks for that",
            "                        category.  'Avg Chance' is the mean dice threshold",
            "                        rolled against — higher = more dangerous per hit.",
            "",
            "  ROLL COMPARISON     — Avg roll and avg chance for hits that knocked down",
            "                        vs hits that didn't.  If 'KD avg chance' is close",
            "                        to 'Miss avg chance', knockdowns are luck-driven.",
            "                        A big gap means weapon/damage type matters more.",
            "",
            "  DAMAGE AT KD        — How hard were the hits that actually caused a",
            "                        knockdown?  Mostly >25% HP means the mechanic is",
            "                        working as intended (only big hits knock warriors",
            "                        down).  Many <15% entries = too hair-trigger.",
            "",
            "=" * 70,
            "",
            "OVERVIEW",
            "-" * 70,
            f"  {'Total fights:':<35} {total_fights:>8,}",
            f"  {'Total knockdown checks (all hits):':<35} {total_checks:>8,}",
            f"  {'Knockdowns that fired:':<35} {total_knocked:>8,}"
            f"  ({total_knocked / tc * 100:.1f}% of checks)",
            f"  {'Avg knockdowns per fight:':<35} {total_knocked / tf:>8.2f}",
            "",
            "KNOCKDOWNS PER FIGHT",
            "-" * 70,
            f"  {'0 knockdowns:':<30} {fights_dist[0]:>6}  ({fights_dist[0] / tf * 100:.1f}%)",
            f"  {'1 knockdown:':<30} {fights_dist[1]:>6}  ({fights_dist[1] / tf * 100:.1f}%)",
            f"  {'2 knockdowns:':<30} {fights_dist[2]:>6}  ({fights_dist[2] / tf * 100:.1f}%)",
            f"  {'3+ knockdowns:':<30} {fights_dist['3+']:>6}  ({fights_dist['3+'] / tf * 100:.1f}%)",
            "",
            "BY WEAPON CATEGORY",
            "-" * 70,
            f"  {'CATEGORY':<22} {'CHECKS':>7}  {'KDs':>5}  {'RATE':>7}  {'AVG CHANCE':>10}  {'AVG HIT %':>9}",
            "-" * 70,
        ]

        for cat, cs in sorted(cat_stats.items(), key=lambda x: x[1]['knocked'], reverse=True):
            rate     = cs['knocked'] / max(1, cs['checks']) * 100
            avg_ch   = cs['total_chance'] / max(1, cs['checks'])
            avg_dpct = cs['total_dmg_pct'] / max(1, cs['checks'])
            lines.append(
                f"  {cat:<22} {cs['checks']:>7}  {cs['knocked']:>5}  "
                f"{rate:>6.1f}%  {avg_ch:>10.1f}  {avg_dpct:>8.1f}%"
            )

        kd_avg_roll   = sum(knocked_rolls)   / tkd
        kd_avg_chance = sum(knocked_chances) / tkd
        ms_avg_roll   = sum(missed_rolls)    / max(1, len(missed_rolls))
        ms_avg_chance = sum(missed_chances)  / max(1, len(missed_chances))

        lines += [
            "",
            "ROLL COMPARISON  (KD fired vs missed)",
            "-" * 70,
            f"  {'':22} {'AVG ROLL':>10}  {'AVG CHANCE':>10}",
            f"  {'Knockdown fired:':<22} {kd_avg_roll:>10.1f}  {kd_avg_chance:>10.1f}",
            f"  {'Knockdown missed:':<22} {ms_avg_roll:>10.1f}  {ms_avg_chance:>10.1f}",
            "",
            "DAMAGE % AT KNOCKDOWN  (how big was the hit that knocked them down?)",
            "-" * 70,
        ]

        total_kd_hits = sum(dmg_buckets.values())
        for band, cnt in dmg_buckets.items():
            pct = cnt / max(1, total_kd_hits) * 100
            lines.append(f"  {band:<12} {cnt:>6} knockdowns  ({pct:.1f}%)")

        self.report_content = "\n".join(lines)
        self.text_area.insert(tk.END, self.report_content)

    # -----------------------------------------------------------------------
    # SIM 6: DAMAGE SEVERITY DISTRIBUTION
    # -----------------------------------------------------------------------
    def _sim_damage_severity(self, teams):
        ITERATIONS = 30
        card = MM.build_global_fight_card(teams, [], champion_state={})

        totals   = {"Light": 0, "Medium": 0, "Heavy": 0}
        damage   = {"Light": 0, "Medium": 0, "Heavy": 0}
        fights   = 0

        for bout in card:
            for _ in range(ITERATIONS):
                w1 = copy.deepcopy(bout.player_warrior)
                w2 = copy.deepcopy(bout.opponent)
                logger = SimDataLogger()
                C.run_fight(w1, w2, debug_logger=logger)
                for tier in ("Light", "Medium", "Heavy"):
                    totals[tier] += logger.severity_counts[tier]
                    damage[tier] += logger.severity_damage[tier]
                fights += 1

        total_hits = sum(totals.values())

        lines = ["\nDAMAGE SEVERITY DISTRIBUTION", "=" * 60]
        lines.append("COLUMN LEGEND:")
        lines.append(f"{'  TIER':<12}: Narrative tier based on damage as % of defender max HP.")
        lines.append(f"{'  THRESHOLD':<12}: Light <19% | Medium 19-33% | Heavy >=34%.")
        lines.append(f"{'  COUNT':<12}: Total hits in this tier across all fights.")
        lines.append(f"{'  % OF HITS':<12}: Share of all damaging hits.")
        lines.append(f"{'  AVG DMG':<12}: Average damage dealt per hit in this tier.")
        lines.append(f"{'  AVG/FIGHT':<12}: Average hits in this tier per fight.")
        lines.append("-" * 60)
        lines.append(f"Total Fights Simulated : {fights}")
        lines.append(f"Total Damaging Hits    : {total_hits}")
        lines.append("-" * 60)
        lines.append(f"{'TIER':<10} | {'COUNT':>7} | {'% HITS':>8} | {'AVG DMG':>8} | {'AVG/FIGHT':>10}")
        lines.append("-" * 60)

        for tier in ("Light", "Medium", "Heavy"):
            cnt      = totals[tier]
            pct      = cnt / max(1, total_hits) * 100
            avg_dmg  = damage[tier] / max(1, cnt)
            avg_pfgt = cnt / max(1, fights)
            lines.append(f"{tier:<10} | {cnt:>7} | {pct:>7.1f}% | {avg_dmg:>8.1f} | {avg_pfgt:>10.1f}")

        lines.append("-" * 60)
        if total_hits:
            lines.append(f"{'TOTAL':<10} | {total_hits:>7} | {'100.0%':>8} | "
                         f"{sum(damage.values())/total_hits:>8.1f} | "
                         f"{total_hits/max(1,fights):>10.1f}")

        self.report_content = "\n".join(lines)
        self.text_area.insert(tk.END, self.report_content)

    # -----------------------------------------------------------------------
    # SIM 7: FULL TURN DRY-RUN
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
