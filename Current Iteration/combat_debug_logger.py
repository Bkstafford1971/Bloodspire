"""
combat_debug_logger.py  —  BLOODSPIRE Admin Combat Debug Logger

Produces a verbose, line-by-line record of every combat calculation for
league admin inspection.  Only active when a debug team is selected in
the admin panel; zero overhead otherwise.

Log files are written to:
    saves/admin_logs/turn_NNNN/fight_NNNNN_<warrior>_vs_<warrior>.txt
"""
import os
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Component-dict formatter
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_comps(comps: Optional[dict]) -> str:
    """Format a component dict as a sum string, skipping zeros and booleans."""
    if not comps:
        return "(no data)"
    parts = []
    for k, v in comps.items():
        if k.startswith("_"):
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and v == 0:
            continue
        if k == "d100":
            parts.append(f"d100[{v}]")
        elif isinstance(v, float):
            parts.append(f"{k}[{v:+.1f}]")
        elif isinstance(v, int):
            parts.append(f"{k}[{v:+d}]")
        else:
            parts.append(f"{k}[{v}]")
    return "  ".join(parts) if parts else "(all zero)"


# ─────────────────────────────────────────────────────────────────────────────
# Logger
# ─────────────────────────────────────────────────────────────────────────────

class CombatDebugLogger:
    """Accumulates verbose combat data and writes it to a plain-text file."""

    WIDTH = 78

    def __init__(self):
        self._lines: list = []
        # Set by the league server before the fight begins
        self.fight_id   : int = 0
        self.turn_num   : int = 0
        self.debug_team : str = ""

    # ── internal helpers ──────────────────────────────────────────────────────

    def _emit(self, line: str = ""):
        self._lines.append(line)

    def _hr(self, char: str = "="):
        self._emit(char * self.WIDTH)

    def _section(self, title: str):
        self._hr()
        self._emit(f"  {title}")
        self._hr()

    def _sub(self, label: str):
        pad = max(0, self.WIDTH - 6 - len(label))
        self._emit(f"\n  ─── {label} {'─' * pad}")

    # ── fight header ─────────────────────────────────────────────────────────

    def log_header(self, warrior_a, warrior_b,
                   team_a: str, team_b: str,
                   manager_a: str, manager_b: str):
        self._hr()
        self._emit("  BLOODSPIRE — ADMIN COMBAT LOG")
        self._emit(f"  Fight #{self.fight_id}   Turn: {self.turn_num}")
        self._emit(f"  Debug team: {self.debug_team}")
        self._emit(f"  {manager_a} / {team_a}   vs   {manager_b} / {team_b}")
        self._hr()
        self._emit("")
        self._warrior_block(warrior_a, "WARRIOR A")
        self._emit("")
        self._warrior_block(warrior_b, "WARRIOR B")
        self._emit("")

    def _warrior_block(self, w, label: str):
        self._emit(f"  {'─' * 36}")
        self._emit(f"  {label}: {w.name.upper()}")
        self._emit(f"  {'─' * 36}")
        self._emit(f"    Race: {w.race.name}  |  Gender: {w.gender}")
        self._emit(
            f"    STR:{w.strength}  DEX:{w.dexterity}  CON:{w.constitution}"
            f"  INT:{w.intelligence}  PRE:{w.presence}  SIZ:{w.size}"
        )
        self._emit(f"    Max HP: {w.max_hp}   Luck: {w.luck}")
        self._emit(f"    Armor: {w.armor or 'None'}   Helm: {w.helm or 'None'}")
        self._emit(
            f"    Primary: {w.primary_weapon}"
            f"   Secondary: {w.secondary_weapon or 'None'}"
        )
        if w.strategies:
            self._emit("    Strategies:")
            for i, s in enumerate(w.strategies, 1):
                cond = getattr(s, "condition", "Always")
                self._emit(
                    f"      [{i}] {cond}  →  {s.style}"
                    f" / Act:{s.activity} / Aim:{s.aim_point}"
                    f" / Def:{s.defense_point}"
                )
        sk_parts = [f"{k}:{v}" for k, v in sorted(w.skills.items()) if v > 0]
        if sk_parts:
            line = "    Skills: "
            for part in sk_parts:
                if len(line) + len(part) + 2 > self.WIDTH:
                    self._emit(line)
                    line = "             " + part + "  "
                else:
                    line += part + "  "
            if line.strip():
                self._emit(line)

    # ── minute ────────────────────────────────────────────────────────────────

    def log_minute_start(self, minute: int,
                         state_a, state_b,
                         apm_a: int, apm_b: int,
                         strat_a, strat_b):
        self._emit("")
        self._section(f"MINUTE {minute}")
        wa = state_a.warrior.name.upper()
        wb = state_b.warrior.name.upper()
        self._emit(f"  APM   — {wa}: {apm_a}   |   {wb}: {apm_b}")
        self._emit(
            f"  HP    — {wa}: {state_a.current_hp}/{state_a.warrior.max_hp}"
            f" ({100 * state_a.hp_pct:.0f}%)   |   "
            f"{wb}: {state_b.current_hp}/{state_b.warrior.max_hp}"
            f" ({100 * state_b.hp_pct:.0f}%)"
        )
        self._emit(
            f"  END   — {wa}: {state_a.endurance:.1f}"
            f"   |   {wb}: {state_b.endurance:.1f}"
        )
        self._emit(
            f"  STRAT — {wa}: [{strat_a.style} / Act:{strat_a.activity}]"
            f"   |   {wb}: [{strat_b.style} / Act:{strat_b.activity}]"
        )

    def log_minute_end(self, state_a, state_b,
                       old_end_a: float, old_end_b: float,
                       act_a: int, act_b: int,
                       strat_a, strat_b):
        from strategy import get_style_props
        wa = state_a.warrior.name.upper()
        wb = state_b.warrior.name.upper()
        props_a = get_style_props(strat_a.style)
        props_b = get_style_props(strat_b.style)
        burn_a = props_a.endurance_burn + (strat_a.activity - 5) * 0.3
        burn_b = props_b.endurance_burn + (strat_b.activity - 5) * 0.3
        self._emit("")
        self._emit(f"  ── END OF MINUTE ──")
        self._emit(
            f"    {wa}: {old_end_a:.1f} END"
            f" − ({burn_a:.2f} burn × {act_a} actions)"
            f" = {state_a.endurance:.1f}"
        )
        self._emit(
            f"    {wb}: {old_end_b:.1f} END"
            f" − ({burn_b:.2f} burn × {act_b} actions)"
            f" = {state_b.endurance:.1f}"
        )
        self._emit(
            f"    HP POOL — {wa}:"
            f" {state_a.current_hp}/{state_a.warrior.max_hp}"
            f" ({100 * state_a.hp_pct:.0f}%)"
        )
        self._emit(
            f"    HP POOL — {wb}:"
            f" {state_b.current_hp}/{state_b.warrior.max_hp}"
            f" ({100 * state_b.hp_pct:.0f}%)"
        )

    def log_strategy_switch(self, warrior_name: str, old_idx: int, new_idx: int):
        self._emit(
            f"  ▶ STRATEGY SWITCH — {warrior_name.upper()}:"
            f" [{old_idx}] → [{new_idx}]"
        )

    # ── action header + initiative ────────────────────────────────────────────

    def log_action_start(self,
                         action_num: int,
                         attacker_name: str, defender_name: str,
                         weapon: str, style: str, aim: str,
                         is_compatible: bool, penalty_factor: float,
                         ia: Optional[int], ia_comps: Optional[dict],
                         ib: Optional[int], ib_comps: Optional[dict]):
        self._sub(f"ACTION {action_num}")
        if ia is not None and ia_comps is not None:
            self._emit(f"  Initiative:")
            self._emit(f"    {attacker_name.upper():24s}: {_fmt_comps(ia_comps)} = {ia}")
            self._emit(f"    {defender_name.upper():24s}: {_fmt_comps(ib_comps)} = {ib}")
            self._emit(f"    ▶ {attacker_name.upper()} wins → ATTACKS")
        else:
            self._emit(
                f"  Initiative: {attacker_name.upper()} has uncontested action"
            )
        self._emit(
            f"  Attack: {attacker_name.upper()} → {defender_name.upper()}"
            f"   Weapon: {weapon}   Style: {style}   Aim: {aim}"
        )
        if not is_compatible:
            self._emit(
                f"  ⚠ Weapon/style INCOMPATIBLE"
                f" — penalty ×{penalty_factor:.2f}"
                f" (−{int((1.0 - penalty_factor) * 25)} to attack roll)"
            )

    # ── attack roll ───────────────────────────────────────────────────────────

    def log_attack_roll(self, attacker_name: str,
                        base_result: int, comps: dict,
                        style_adv: int, compat_pen: int,
                        final_result: int):
        self._emit(f"  Attack Roll ({attacker_name.upper()}):")
        self._emit(f"    {_fmt_comps(comps)}")
        self._emit(f"    Subtotal: {base_result}")
        if style_adv:
            self._emit(f"    + style advantage: {style_adv:+d}")
        if compat_pen:
            self._emit(f"    − compat penalty: −{compat_pen}")
        self._emit(f"    Final ATK: {final_result}")

    # ── defense roll ──────────────────────────────────────────────────────────

    def log_defense_roll(self, defender_name: str,
                         comps: dict, is_parry: bool,
                         parry_bonus: int, dodge_bonus: int,
                         base_result: int, decoy_pen: int,
                         final_result: int):
        mode = "PARRY" if is_parry else "DODGE"
        reason = (
            f"parry_bonus({parry_bonus}) ≥ dodge_bonus({dodge_bonus})"
            if is_parry else
            f"dodge_bonus({dodge_bonus}) > parry_bonus({parry_bonus})"
        )
        self._emit(f"  Defense Roll ({defender_name.upper()}, {mode} — {reason}):")
        display = {k: v for k, v in comps.items() if not k.startswith("_")}
        self._emit(f"    {_fmt_comps(display)}")
        self._emit(f"    Subtotal: {base_result + decoy_pen}")
        if decoy_pen:
            self._emit(f"    − Decoy feint penalty: −{decoy_pen}")
        self._emit(f"    Final DEF: {final_result}")

    # ── margin ────────────────────────────────────────────────────────────────

    def log_margin(self, atk: int, dfn: int, margin: int, outcome: str):
        self._emit(f"  Margin: {atk} − {dfn} = {margin}   ▶  {outcome}")

    # ── damage ────────────────────────────────────────────────────────────────

    def log_damage(self, attacker_name: str, defender_name: str,
                   margin: int, steps: dict,
                   sig_floor: Optional[int], ca_bonus: int,
                   net_damage: int):
        self._emit(f"  Damage ({attacker_name.upper()} → {defender_name.upper()}):")
        self._emit(f"    ── Ceiling breakdown ──")
        self._emit(
            f"      weapon base (wt × 2.5)       = {steps.get('weapon_base', 0):.2f}"
        )
        if steps.get("str_bonus", 0.0):
            self._emit(
                f"      STR bonus                    +{steps['str_bonus']:.2f}"
            )
        if steps.get("flail_size_bonus", 0.0):
            self._emit(
                f"      flail/size bonus             +{steps['flail_size_bonus']:.2f}"
            )
        mult = steps.get("two_hand_mult", 1.0)
        if mult != 1.0:
            self._emit(f"      two-hand multiplier          ×{mult:.2f}")
        rn = steps.get("race_net", 0.0)
        if rn:
            self._emit(f"      race damage net              {rn:+.2f}")
        sd = steps.get("style_damage", 0.0)
        if sd:
            self._emit(f"      style modifier               {sd:+.2f}")
        ac = steps.get("activity_contrib", 0.0)
        if ac:
            self._emit(f"      activity contrib             {ac:+.2f}")
        ws = steps.get("weapon_skill_contrib", 0.0)
        if ws:
            self._emit(f"      weapon skill ×0.8            +{ws:.2f}")
        lc = steps.get("luck_contrib", 0.0)
        if lc:
            self._emit(f"      luck ×0.15                   +{lc:.2f}")
        sp = steps.get("str_penalty_factor", 0.0)
        if sp:
            self._emit(
                f"      strength underweight pen     ×{1.0 - sp:.2f}"
                f" ({sp:.0%} penalty)"
            )
        hwm = steps.get("heavy_weapon_mult", 1.0)
        if hwm != 1.0:
            self._emit(f"      heavy weapon mult (race)     ×{hwm:.2f}")
        scp = steps.get("style_compat", 1.0)
        if scp != 1.0:
            self._emit(f"      style compat penalty         ×{scp:.2f}")
        for sk in ("cleave", "bash", "slash", "strike", "open_hand"):
            val = steps.get(f"{sk}_bonus", 0.0)
            if val:
                self._emit(f"      {sk} skill bonus               +{val:.2f}")
        if steps.get("cleave_master_mult"):
            self._emit(f"      cleave master (lv9)          ×1.25")
        if steps.get("open_hand_master_mult"):
            self._emit(f"      open-hand master (lv9)       ×1.20")
        if steps.get("brawl_master_mult"):
            self._emit(f"      brawl master (lv9)           ×1.10")
        self._emit(f"    Ceiling: {steps.get('ceiling', 0)}")
        frac = steps.get("fraction", 0.0)
        self._emit(
            f"    Fraction: max(0.10, min(1.0, {margin}/55.0)) = {frac:.3f}"
        )
        raw = steps.get("raw", 0)
        self._emit(
            f"    Raw: max(1, int({steps.get('ceiling', 0)} × {frac:.3f}))"
            f" = {raw}"
        )
        if steps.get("fav_bonus", 0):
            self._emit(f"    Favorite weapon +1 → raw = {raw + 1}")
        self._emit(
            f"    Armor: {steps.get('armor_name', '?')}"
            f"  base DEF: {steps.get('armor_def', 0)}"
        )
        if steps.get("armor_piercing"):
            self._emit(
                f"    Armor piercing: YES — DEF halved"
                f" → {steps.get('armor_after_ap', 0)}"
            )
        pbyp = steps.get("precision_bypass", 0.0)
        if pbyp > 0:
            self._emit(
                f"    CA precision bypass: {pbyp * 100:.0f}%"
                f" → final DEF: {steps.get('final_armor', 0)}"
            )
        raw_final = steps.get("raw_with_fav", raw)
        fa = steps.get("final_armor", 0)
        pre_mod = max(1, raw_final - fa)
        self._emit(f"    Net = max(1, {raw_final} − {fa}) = {pre_mod}")
        if sig_floor is not None and sig_floor > pre_mod:
            self._emit(
                f"    Signature hit floor (12% max HP = {sig_floor}):"
                f" net raised to {sig_floor}"
            )
        if ca_bonus:
            self._emit(f"    CA precision bonus: +{ca_bonus}")
        self._emit(f"  ▶ FINAL DAMAGE: {net_damage}")

    # ── HP pool ───────────────────────────────────────────────────────────────

    def log_hp_update(self, warrior_name: str,
                      prev_hp: int, damage: int, new_hp: int,
                      max_hp: int, source: str = "hit"):
        self._emit(f"  HP Pool ({warrior_name.upper()}):")
        self._emit(
            f"    Before : {prev_hp}/{max_hp}"
            f" ({100 * prev_hp / max(1, max_hp):.1f}%)"
        )
        self._emit(f"    {source:8s}: −{damage}")
        self._emit(
            f"    After  : {new_hp}/{max_hp}"
            f" ({100 * max(0, new_hp) / max(1, max_hp):.1f}%)"
        )

    def log_bleed(self, warrior_name: str,
                  wounds: int, bleed_dmg: int,
                  prev_hp: int, new_hp: int, max_hp: int):
        self._emit(
            f"  Bleed ({warrior_name.upper()})"
            f" — accumulated wounds: {wounds}"
            f",  bleed damage this round: {bleed_dmg}"
        )
        self._emit(
            f"    HP: {prev_hp}/{max_hp} → {new_hp}/{max_hp}"
        )

    # ── knockdown ─────────────────────────────────────────────────────────────

    def log_knockdown(self, warrior_name: str,
                      damage: int, max_hp: int,
                      category: str, chance: int,
                      roll: int, knocked: bool):
        self._emit(f"  Knockdown Check ({warrior_name.upper()}):")
        base = int((damage / max(1, max_hp)) * 80)
        cat_b = (10 if category in ("Hammer/Mace", "Flail")
                 else (5 if category == "Polearm/Spear" else 0))
        self._emit(
            f"    base = int({damage}/{max_hp} × 80) = {base}"
            f"   cat bonus [{category}]: +{cat_b}"
            f"   final: {chance}%"
        )
        self._emit(
            f"    Roll: {roll}  →  "
            f"{'▶ KNOCKDOWN' if knocked else 'no knockdown'}"
        )

    # ── perm injury ───────────────────────────────────────────────────────────

    def log_perm_injury(self, warrior_name: str,
                        damage: int, max_hp: int,
                        chance: int, roll: int, result):
        threshold = int(max_hp * 0.15)
        self._emit(f"  Perm Injury Check ({warrior_name.upper()}):")
        self._emit(
            f"    threshold = 15% of {max_hp} = {threshold}"
            f"   damage {damage}"
            f" {'≥' if damage >= threshold else '<'} threshold"
        )
        if damage < threshold:
            self._emit(f"    → Below threshold — no injury possible")
            return
        self._emit(
            f"    chance = max(5, min(80, int({damage}/{max_hp}×100) − 5))"
            f" = {chance}%"
        )
        self._emit(
            f"    Roll: {roll}  →  "
            f"{result if result else 'no injury'}"
        )

    # ── death check ───────────────────────────────────────────────────────────

    def log_death_check(self, warrior_name: str,
                        prev_hp: int, damage: int,
                        overshoot: int, death_chance: float,
                        died: bool):
        self._emit(f"  Death Check ({warrior_name.upper()}):")
        self._emit(
            f"    prev_hp: {prev_hp}   damage: {damage}"
            f"   new_hp: {prev_hp - damage}"
        )
        self._emit(f"    overshoot: {overshoot}")
        self._emit(
            f"    death_chance = min(50.0, 0.5 + {overshoot})"
            f" = {death_chance:.1f}%"
        )
        self._emit(
            f"    → "
            f"{'▶ WARRIOR DIES' if died else 'survives (concede system takes over)'}"
        )

    # ── concede ───────────────────────────────────────────────────────────────

    def log_concede(self, warrior_name: str,
                    d100: int, pre_bonus: int, luck_half: int,
                    total: int, threshold: int, granted: bool):
        self._emit(f"  Concede Attempt ({warrior_name.upper()}):")
        self._emit(
            f"    d100[{d100}] + PRE_bonus[{pre_bonus:+d}]"
            f" + luck//2[{luck_half}] = {total}"
        )
        self._emit(
            f"    threshold = max(40, 68 − (PRE // 3)) = {threshold}"
        )
        self._emit(
            f"    {total} {'≥' if granted else '<'} {threshold}"
            f"  →  "
            f"{'▶ CONCEDE GRANTED' if granted else 'mercy denied — fight continues'}"
        )

    # ── fight result ──────────────────────────────────────────────────────────

    def log_result(self, winner_name: str, loser_name: str,
                   loser_died: bool, minutes: int,
                   winner_hp_pct: float, loser_hp_pct: float):
        self._emit("")
        self._hr()
        self._emit("  FIGHT RESULT")
        self._hr()
        self._emit(
            f"  Winner : {winner_name.upper()}"
            f"  ({winner_hp_pct * 100:.1f}% HP remaining)"
        )
        self._emit(
            f"  Loser  : {loser_name.upper()}"
            f"  ({'SLAIN' if loser_died else 'survived'},"
            f" {loser_hp_pct * 100:.1f}% HP)"
        )
        self._emit(f"  Duration: {minutes} minute(s)")
        self._hr()

    def log_training(self, warrior_name: str, details: list) -> None:
        self._emit("")
        self._hr()
        self._emit(f"  TRAINING: {warrior_name.upper()}")
        self._hr()
        for d in details:
            sk      = d.get("skill", "?").replace("_", " ").title()
            roll    = d.get("roll", 0)
            chance  = d.get("chance", 0)
            success = d.get("success", False)
            msg     = d.get("msg", "")
            src     = d.get("source", "train")

            if src == "observed_trigger":
                self._emit(f"  INT observed learning: d100={roll} vs {chance}% — no trigger")
            elif src == "observed":
                tr = d.get("trigger_roll", 0)
                tc = d.get("trigger_chance", 0)
                outcome = "SUCCESS" if success else "FAIL"
                self._emit(
                    f"  [OBSERVED] {sk}: trigger d100={tr}/{tc}% passed  |  "
                    f"skill d100={roll} vs {chance}% — {outcome}"
                )
                if msg:
                    self._emit(f"    → {msg.lstrip('[OBSERVED] ')}")
            elif roll == 0 and chance == 0:
                # At-max or unknown-skill paths — no roll made
                if msg:
                    self._emit(f"  {sk}: {msg}")
            else:
                outcome = "SUCCESS" if success else "FAIL"
                self._emit(f"  {sk}: d100={roll} vs {chance}% — {outcome}")
                if msg:
                    self._emit(f"    → {msg}")

    # ── output ────────────────────────────────────────────────────────────────

    def get_text(self) -> str:
        return "\n".join(self._lines)

    def write_to_file(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.get_text())
            f.write("\n")
