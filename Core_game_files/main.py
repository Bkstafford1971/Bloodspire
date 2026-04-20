#!/usr/bin/env python3
# =============================================================================
# main.py — BLOODSPIRE Main Menu & Game Loop
# =============================================================================
# Entry point. Run with:  python main.py
#
# Main Menu:
#   1. View team roster
#   2. Set up a warrior (armor, weapons, strategies, training)
#   3. Quick-Run turn (fight with current setup)
#   4. Full setup + run turn
#   5. View last fight log
#   6. View opponent teams
#   7. Quit
# =============================================================================

import os
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from warrior      import (
    Warrior, Strategy, create_warrior_interactive,
    generate_base_stats, ATTRIBUTES, FIGHTING_STYLES,
    AIM_DEFENSE_POINTS, ALL_SKILLS, NON_WEAPON_SKILLS, WEAPON_SKILLS,
    TRIGGERS,
)
from team         import Team, TEAM_SIZE
from ai           import assign_ai_gear, assign_ai_strategies, assign_ai_training
from matchmaking  import run_turn, turn_summary, ScheduledFight
from save         import (
    save_team, load_team, load_all_teams, list_saved_teams,
    list_fight_logs, load_fight_log, print_save_status,
    load_champion_state, save_champion_state,
    next_team_id,
)
from weapons      import WEAPONS, get_weapon
from armor        import (
    armor_selection_menu, helm_selection_menu, get_armor, can_wear_armor,
)
from ai_league_teams import get_or_create_ai_teams


# ---------------------------------------------------------------------------
# TERMINAL HELPERS
# ---------------------------------------------------------------------------

def clear():
    os.system("cls" if os.name == "nt" else "clear")


def pause(msg: str = "\n  Press ENTER to continue..."):
    input(msg)


def header(title: str, width: int = 62):
    print()
    print("=" * width)
    print(f"  {title.upper()}")
    print("=" * width)


def thin(width: int = 62):
    print("  " + "-" * (width - 2))


def prompt(msg: str) -> str:
    return input(f"  {msg}").strip()


def choose(
    options : list,
    label   : str = "Choice",
    allow_back: bool = True,
) -> int:
    """
    Display a numbered menu and return the 0-based index of the chosen option.
    Returns -1 if the user goes back (enters 0 or 'b').
    """
    for i, opt in enumerate(options, 1):
        print(f"    {i}.  {opt}")
    if allow_back:
        print(f"    0.  Back")
    while True:
        raw = prompt(f"{label}: ")
        if allow_back and raw in ("0", "b", ""):
            return -1
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return idx
        except ValueError:
            pass
        print("    Please enter a valid number.")


# ---------------------------------------------------------------------------
# GAME STATE
# ---------------------------------------------------------------------------

class GameState:
    """Holds the active player team and opponent pool for the session."""

    def __init__(self):
        self.player_team    : Team = None
        self.opponent_teams : list = []
        self.last_card      : list = []   # last turn's fight card

    def is_ready(self) -> bool:
        return self.player_team is not None


# ---------------------------------------------------------------------------
# TEAM SELECTION / CREATION
# ---------------------------------------------------------------------------

def select_or_create_team(gs: GameState):
    """Let the player pick an existing team or create a new one."""
    while True:
        header("Team Selection")
        saved = list_saved_teams()

        options = []
        if saved:
            options.append("Load an existing team")
        options.append("Create a new team")
        options.append("Quit")

        idx = choose(options, allow_back=False)

        if options[idx] == "Load an existing team":
            _load_existing_team(gs)
            if gs.player_team:
                return

        elif options[idx] == "Create a new team":
            _create_new_team(gs)
            if gs.player_team:
                return

        elif options[idx] == "Quit":
            print("\n  Farewell from the BLOODSPIRE.\n")
            sys.exit(0)


def _load_existing_team(gs: GameState):
    """Show saved teams and let player pick one."""
    saved = list_saved_teams()
    if not saved:
        print("  No saved teams found.")
        pause()
        return

    header("Load Team")
    options = [f"[{s['team_id']:04d}] {s['team_name']}  (Manager: {s['manager_name']})"
               for s in saved]
    idx = choose(options)
    if idx < 0:
        return
    team_id = saved[idx]["team_id"]
    try:
        gs.player_team = load_team(team_id)
        print(f"\n  Loaded team: {gs.player_team.team_name}")
        pause()
    except Exception as e:
        print(f"  ERROR: {e}")
        pause()


def _create_new_team(gs: GameState):
    """Interactive new team creation — name the team and create 5 warriors."""
    header("Create New Team")

    manager_name = prompt("Manager name: ")
    if not manager_name:
        return
    team_name = prompt("Team name: ")
    if not team_name:
        return

    team = Team(team_name=team_name, manager_name=manager_name)

    print(f"\n  Now create your 5 warriors.")
    print(f"  Each warrior gets {16} points to distribute (max 7 per attribute).\n")

    for slot in range(1, TEAM_SIZE + 1):
        print(f"\n  --- WARRIOR {slot} of {TEAM_SIZE} ---")
        while True:
            w = create_warrior_interactive(generate_base_stats())
            if w:
                team.add_warrior(w)
                break
            retry = prompt("Try again? (y/n): ").lower()
            if retry != "y":
                # Auto-fill remaining slots with AI
                print("  Filling remaining slots with AI warriors...")
                team.fill_roster_with_ai()
                break
        if team.is_full:
            break

    if not team.is_full:
        team.fill_roster_with_ai()

    # Assign starter gear and strategies to each warrior
    print("\n  Assigning starter gear and strategies...")
    for w in team.warriors:
        if w:
            assign_ai_gear(w, tier=1)
            assign_ai_strategies(w, tier=1)
            assign_ai_training(w, tier=1)

    team.team_id = next_team_id()
    save_team(team)
    gs.player_team = team
    print(f"\n  Team '{team_name}' created and saved!")
    pause()


# ---------------------------------------------------------------------------
# MAIN MENU
# ---------------------------------------------------------------------------

MAIN_MENU_OPTIONS = [
    "View team roster",
    "Set up a warrior  (gear / strategies / training)",
    "Quick-run turn    (fight with current setup)",
    "Full turn         (setup + run)",
    "View last fight log",
    "View opponent teams",
    "Save status",
    "Switch / load team",
    "Quit",
]


def main_menu(gs: GameState):
    while True:
        clear()
        header(f"BLOODSPIRE  —  {gs.player_team.team_name}  ({gs.player_team.manager_name})")
        idx = choose(MAIN_MENU_OPTIONS, "Action", allow_back=False)

        if MAIN_MENU_OPTIONS[idx] == "View team roster":
            _view_roster(gs)

        elif MAIN_MENU_OPTIONS[idx] == "Set up a warrior  (gear / strategies / training)":
            _setup_warrior_menu(gs)

        elif MAIN_MENU_OPTIONS[idx] == "Quick-run turn    (fight with current setup)":
            _run_turn(gs, setup_first=False)

        elif MAIN_MENU_OPTIONS[idx] == "Full turn         (setup + run)":
            _run_turn(gs, setup_first=True)

        elif MAIN_MENU_OPTIONS[idx] == "View last fight log":
            _view_last_fight(gs)

        elif MAIN_MENU_OPTIONS[idx] == "View opponent teams":
            _view_opponents(gs)

        elif MAIN_MENU_OPTIONS[idx] == "Save status":
            print_save_status()
            pause()

        elif MAIN_MENU_OPTIONS[idx] == "Switch / load team":
            select_or_create_team(gs)

        elif MAIN_MENU_OPTIONS[idx] == "Quit":
            save_team(gs.player_team)
            print("\n  Your team has been saved. Farewell from the BLOODSPIRE.\n")
            sys.exit(0)


# ---------------------------------------------------------------------------
# ROSTER VIEW
# ---------------------------------------------------------------------------

def _view_roster(gs: GameState):
    header("Team Roster")
    print(gs.player_team.roster_summary())
    thin()
    idx = choose(
        [f"View details: {w.name}" for w in gs.player_team.warriors if w],
        "View warrior",
    )
    if idx >= 0:
        active = [w for w in gs.player_team.warriors if w]
        print("\n" + active[idx].stat_block())
        pause()


# ---------------------------------------------------------------------------
# WARRIOR SETUP MENU
# ---------------------------------------------------------------------------

def _setup_warrior_menu(gs: GameState):
    """Select a warrior then set up their gear, strategies, and training."""
    header("Warrior Setup")
    active = [w for w in gs.player_team.warriors if w]
    if not active:
        print("  No active warriors.")
        pause()
        return

    idx = choose([f"{w.name} ({w.race.name} {w.gender})" for w in active], "Select warrior")
    if idx < 0:
        return
    warrior = active[idx]

    while True:
        header(f"Setup: {warrior.name}")
        sub_options = [
            "Assign armor & helm",
            "Assign weapons",
            "Edit strategies",
            "Set training queue",
            "View current setup",
            "Done",
        ]
        sub_idx = choose(sub_options, "Option")
        if sub_idx < 0 or sub_options[sub_idx] == "Done":
            break
        elif sub_options[sub_idx] == "Assign armor & helm":
            _assign_armor(warrior)
        elif sub_options[sub_idx] == "Assign weapons":
            _assign_weapons(warrior)
        elif sub_options[sub_idx] == "Edit strategies":
            _edit_strategies(warrior)
        elif sub_options[sub_idx] == "Set training queue":
            _set_training(warrior)
        elif sub_options[sub_idx] == "View current setup":
            print("\n" + warrior.stat_block())
            pause()

    save_team(gs.player_team)
    print(f"  {warrior.name}'s setup saved.")
    pause()


def _assign_armor(warrior: Warrior):
    """Interactive armor and helm assignment."""
    header(f"Armor — {warrior.name}  (STR {warrior.strength})")
    is_dw = warrior.race.name == "Dwarf"

    print("  BODY ARMOR:")
    armor_opts = armor_selection_menu()
    valid_armor = []
    for a in armor_opts:
        allowed, msg = can_wear_armor(a, warrior.strength, is_dw)
        mark = "✓" if allowed else "✗"
        print(f"    [{mark}] {a:<16} — {msg}")
        if allowed:
            valid_armor.append(a)
    valid_armor.append("None")

    idx = choose(valid_armor, "Choose armor")
    if idx >= 0:
        warrior.armor = None if valid_armor[idx] == "None" else valid_armor[idx]

    print("\n  HELM:")
    helm_opts = helm_selection_menu()
    idx2 = choose(helm_opts + ["None"], "Choose helm")
    if idx2 >= 0:
        choices = helm_opts + ["None"]
        warrior.helm = None if choices[idx2] == "None" else choices[idx2]


def _assign_weapons(warrior: Warrior):
    """Interactive weapon assignment — primary, secondary, backup."""
    header(f"Weapons — {warrior.name}  (STR {warrior.strength})")

    # Group weapons by category for display
    from weapons import ALL_CATEGORIES, list_weapons_by_category
    for slot_name in ("Primary", "Secondary", "Backup"):
        print(f"\n  {slot_name.upper()} WEAPON:")
        print(f"  (Current: {getattr(warrior, slot_name.lower() + '_weapon', 'Open Hand')})")

        # Show all weapons with penalty indicators
        all_weapon_names = [w.display for w in WEAPONS.values()]
        all_weapon_names.sort()
        display_rows = []
        for wn in all_weapon_names:
            try:
                w  = get_weapon(wn)
                pen = w.penalty_for(warrior.strength, w.two_hand)
                if pen == 0:
                    flag = "  "
                elif pen < 0.3:
                    flag = "~"   # Slight penalty
                else:
                    flag = "!"   # Heavy penalty
                display_rows.append(f"{flag} {wn:<22} wt:{w.weight:<5} {w.category}")
            except ValueError:
                continue
        display_rows.append("  Open Hand")

        idx = choose(display_rows, f"{slot_name} weapon")
        if idx < 0:
            continue
        chosen = display_rows[idx].strip().lstrip("~! ").split("  ")[0].strip()
        attr = {"Primary":"primary_weapon","Secondary":"secondary_weapon","Backup":"backup_weapon"}[slot_name]
        setattr(warrior, attr, chosen if chosen != "Open Hand" else "Open Hand")
        print(f"  {slot_name} weapon set to: {chosen}")


def _edit_strategies(warrior: Warrior):
    """Interactive strategy editor."""
    header(f"Strategies — {warrior.name}")

    while True:
        print("\n  Current strategies:")
        thin()
        print(f"  {'#':<4} {'Trigger':<32} {'Style':<18} Act  Aim              Def")
        thin()
        for i, s in enumerate(warrior.strategies, 1):
            print(s.display(str(i)))
        print()

        options = (
            [f"Edit strategy {i+1}" for i in range(len(warrior.strategies))]
            + ["Add new strategy", "Remove last strategy", "Done"]
        )
        idx = choose(options, "Option")
        if idx < 0 or options[idx] == "Done":
            break
        elif options[idx] == "Add new strategy":
            if len(warrior.strategies) >= 6:
                print("  Maximum 6 strategies allowed.")
                pause()
            else:
                s = _build_strategy()
                if s:
                    warrior.strategies.append(s)
        elif options[idx] == "Remove last strategy":
            if len(warrior.strategies) > 1:
                warrior.strategies.pop()
            else:
                print("  Must keep at least 1 strategy.")
                pause()
        else:
            # Edit an existing strategy
            strat_idx = int(options[idx].split()[-1]) - 1
            updated = _build_strategy(existing=warrior.strategies[strat_idx])
            if updated:
                warrior.strategies[strat_idx] = updated


def _build_strategy(existing: Strategy = None) -> Strategy:
    """Interactively build or edit one strategy row."""
    header("Edit Strategy")

    if existing:
        print(f"  Current: {existing.display('?')}\n")

    # Trigger
    print("  TRIGGERS:")
    t_idx = choose(TRIGGERS, "Trigger", allow_back=True)
    if t_idx < 0:
        return None
    trigger = TRIGGERS[t_idx]

    # Style
    print("\n  FIGHTING STYLES:")
    s_idx = choose(FIGHTING_STYLES, "Style")
    if s_idx < 0:
        return None
    style = FIGHTING_STYLES[s_idx]

    # Activity
    while True:
        raw = prompt("Activity level (0-9): ")
        try:
            act = int(raw)
            if 0 <= act <= 9:
                break
        except ValueError:
            pass
        print("  Enter 0-9.")

    # Aim point
    print("\n  AIM POINTS:")
    a_idx = choose(AIM_DEFENSE_POINTS, "Aim point")
    aim = AIM_DEFENSE_POINTS[a_idx] if a_idx >= 0 else "None"

    # Defense point
    print("\n  DEFENSE POINTS:")
    d_idx = choose(AIM_DEFENSE_POINTS, "Defense point")
    defense = AIM_DEFENSE_POINTS[d_idx] if d_idx >= 0 else "Chest"

    return Strategy(
        trigger      = trigger,
        style        = style,
        activity     = act,
        aim_point    = aim,
        defense_point= defense,
    )


def _set_training(warrior: Warrior):
    """Set up to 3 training targets."""
    header(f"Training — {warrior.name}")
    print(f"  Current queue: {warrior.trains or '(empty)'}")
    print(f"  Intelligence: {warrior.intelligence}  (higher INT = faster skill learning)")
    print(f"  Constitution: {warrior.constitution}  (higher CON = better stat training)\n")
    print("  Choose up to 3 training slots (attributes or skills).")
    print("  Note: SIZE cannot be trained.\n")

    # Build a menu of all trainable options
    options = (
        [f"ATTRIBUTE: {a.capitalize()}" for a in ATTRIBUTES if a != "size"]
        + [f"NON-WEAPON: {s.replace('_',' ').title()}" for s in NON_WEAPON_SKILLS]
        + [f"WEAPON: {s.replace('_',' ').title()}" for s in WEAPON_SKILLS]
    )

    warrior.trains = []
    for slot in range(1, 4):
        print(f"\n  Slot {slot}:")
        idx = choose(options, f"Train slot {slot}")
        if idx < 0:
            break
        chosen = options[idx].split(": ", 1)[1].lower().replace(" ", "_")
        warrior.trains.append(chosen)
        print(f"  Slot {slot} → {chosen.replace('_',' ').title()}")

    print(f"\n  Training queue: {warrior.trains}")
    pause()


# ---------------------------------------------------------------------------
# RUN TURN
# ---------------------------------------------------------------------------

def _run_turn(gs: GameState, setup_first: bool = False):
    """Run one turn — optionally let player set up all warriors first."""
    header("Run Turn")

    if setup_first:
        print("  Setting up each warrior before the turn...")
        active = [w for w in gs.player_team.warriors if w]
        for w in active:
            ans = prompt(f"  Set up {w.name}? (y/n): ").lower()
            if ans == "y":
                # Abbreviated inline setup
                _assign_armor(w)
                _assign_weapons(w)
                _edit_strategies(w)
                _set_training(w)
        save_team(gs.player_team)

    print("\n  Preparing opponents...")
    gs.opponent_teams = _load_opponent_teams(gs.player_team.team_id)

    print(f"  {len(gs.opponent_teams)} opponent teams in the pool.")
    print(f"  Scheduling {len(gs.player_team.active_warriors)} fights...\n")

    champion_state = load_champion_state()

    card = run_turn(gs.player_team, gs.opponent_teams, verbose=True, champion_state=champion_state)
    gs.last_card = card

    # Print summary
    print(turn_summary(card, gs.player_team.team_name))

    # Offer to view individual fight narratives
    print()
    for i, bout in enumerate(card, 1):
        if bout.result:
            ans = prompt(
                f"  View full narrative for bout {i}: "
                f"{bout.player_warrior.name} vs {bout.opponent.name}? (y/n): "
            ).lower()
            if ans == "y":
                print("\n" + bout.result.narrative)
                pause()

    pause("\n  Turn complete. Press ENTER...")


# ---------------------------------------------------------------------------
# VIEW LAST FIGHT LOG
# ---------------------------------------------------------------------------

def _view_last_fight(gs: GameState):
    header("Fight Logs")
    logs = list_fight_logs()
    if not logs:
        print("  No fight logs saved yet.")
        pause()
        return

    options = [f"Fight #{l['fight_id']}  —  {l['filename']}" for l in logs[-10:]]
    idx = choose(options, "Choose log")
    if idx < 0:
        return
    fight_id = logs[-(10 - idx)]["fight_id"]
    try:
        text = load_fight_log(fight_id)
        print("\n" + text)
    except FileNotFoundError as e:
        print(f"  {e}")
    pause()


# ---------------------------------------------------------------------------
# VIEW OPPONENT TEAMS
# ---------------------------------------------------------------------------

def _load_opponent_teams(exclude_team_id: int) -> list:
    """Load all opponent teams: AI league teams + other saved teams."""
    opponents = []
    ai_team_ids = set()
    try:
        ai_teams = get_or_create_ai_teams()
        for at in ai_teams:
            try:
                t = Team.from_dict(at)
                if t.active_warriors:
                    opponents.append(t)
                    ai_team_ids.add(t.team_id)
            except Exception:
                pass
    except Exception:
        pass
    for t in load_all_teams():
        if t.team_id != exclude_team_id and t.team_id not in ai_team_ids:
            opponents.append(t)
    return opponents


def _view_opponents(gs: GameState):
    header("Opponent Teams")
    if not gs.opponent_teams:
        gs.opponent_teams = _load_opponent_teams(
            gs.player_team.team_id if gs.player_team else 0
        )
    if not gs.opponent_teams:
        print("  No opponent teams available.")
        pause()
        return
    lines = ["  OPPONENT TEAMS", "  " + "=" * 50]
    for t in gs.opponent_teams:
        active = len(t.active_warriors)
        lines.append(
            f"  [{t.team_id:04d}] {t.manager_name:<22} "
            f"'{t.team_name}'  ({active} active)"
        )
    print("\n".join(lines))
    pause()


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

def main():
    clear()
    print()
    print("  " + "=" * 58)
    print("  " + " " * 15 + "WELCOME TO THE BLOODSPIRE")
    print("  " + " " * 12 + "A GAME OF GLADIATORIAL COMBAT")
    print("  " + "=" * 58)
    print()
    print("  'Through your training and guidance, create the most")
    print("   powerful and fearsome warriors the Pit has ever seen.'")
    print()

    gs = GameState()

    # Opponent teams are loaded on demand when running a turn or viewing

    # Team selection
    select_or_create_team(gs)

    # Main loop
    main_menu(gs)


if __name__ == "__main__":
    main()
