"""
Training Log Manager - Captures and persists training attempt details per turn.

Creates one training log file per manager per turn in the logs/ directory.
Each file contains all training attempts for that manager's warriors.
Previous turn's logs are cleared when new turn starts.
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional

LOGS_DIR = r"C:\BPClone_Claude\logs"

def _ensure_logs_dir():
    """Create logs directory if it doesn't exist."""
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)


def clear_turn_logs(turn_num: int):
    """
    Delete all training log files from the previous turn.
    Called at the start of a new turn to clean up old logs.
    """
    _ensure_logs_dir()

    prev_turn = turn_num - 1
    if prev_turn <= 0:
        return

    # Find and delete all files matching turn_[prev_turn]_*.txt
    for file in Path(LOGS_DIR).glob(f"turn_{prev_turn:04d}_*.txt"):
        try:
            file.unlink()
            print(f"[TRAINING LOG] Deleted previous turn log: {file.name}")
        except Exception as e:
            print(f"[TRAINING LOG] Warning: Could not delete {file.name}: {e}")


def log_warrior_training(
    turn_num: int,
    warrior_name: str,
    manager_name: str,
    team_name: str,
    team_id: int,
    training_details: List[dict]
):
    """
    Log a warrior's training attempts for this turn.

    Args:
        turn_num: Current turn number
        warrior_name: Name of the warrior
        manager_name: Name of the manager
        team_name: Name of the team
        team_id: ID of the team
        training_details: List of dicts from _apply_training_verbose, each containing:
            - skill: skill name
            - roll: d100 roll (1-100), or 0 if error
            - chance: success threshold (%)
            - success: boolean
            - msg: training message
            - source: "train" or "observed"
            - (optional) trigger_roll, trigger_chance for observed learning
    """
    if not training_details:
        return

    _ensure_logs_dir()

    # Create filename per manager
    manager_filename = f"turn_{turn_num:04d}_{manager_name.replace(' ', '_')}_training.txt"
    log_path = Path(LOGS_DIR) / manager_filename

    # Format the training entry for this warrior
    lines = []
    lines.append(f"TRAINING: {warrior_name}")
    lines.append("=" * 80)

    for detail in training_details:
        skill = detail.get("skill", "?")
        roll = detail.get("roll", 0)
        chance = detail.get("chance", 0)
        success = detail.get("success", False)
        msg = detail.get("msg", "")
        source = detail.get("source", "train")

        # Format: "Skill: d100=ROLL vs CHANCE% - SUCCESS/FAIL"
        result_text = "SUCCESS" if success else "FAIL"

        if source == "observed":
            # Observed learning has a trigger roll
            trigger_roll = detail.get("trigger_roll", 0)
            trigger_chance = detail.get("trigger_chance", 0)
            lines.append(f"  [OBSERVED] {skill}: d100={trigger_roll} vs {trigger_chance}% trigger - {'TRIGGERED' if success else 'NOT TRIGGERED'}")
            if success and roll > 0:
                lines.append(f"    Learned: d100={roll} vs {chance}% - SUCCESS")
                if msg:
                    lines.append(f"    → {msg}")
        else:
            # Regular training attempt
            if roll == 0:
                # Error case - unknown skill
                lines.append(f"  {skill}: ERROR - Unknown skill or attribute")
                if msg:
                    lines.append(f"    → {msg}")
            else:
                # Normal roll
                lines.append(f"  {skill}: d100={roll} vs {chance}% - {result_text}")
                if msg:
                    lines.append(f"    → {msg}")

    lines.append("")  # Blank line between warriors

    # Append to the manager's file
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"[TRAINING LOG] Logged {warrior_name} training to {manager_filename}")
    except Exception as e:
        print(f"[TRAINING LOG] Error writing training log for {warrior_name}: {e}")


def write_manager_header(turn_num: int, manager_name: str, team_id: int = 0):
    """
    Write the manager header at the start of the file (called once per manager per turn).

    Args:
        turn_num: Current turn number
        manager_name: Manager name
        team_id: Primary team ID (if available)
    """
    _ensure_logs_dir()

    manager_filename = f"turn_{turn_num:04d}_{manager_name.replace(' ', '_')}_training.txt"
    log_path = Path(LOGS_DIR) / manager_filename

    # Only write header if file doesn't exist yet
    if not log_path.exists():
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"MANAGER: {manager_name}\n")
                f.write(f"TURN: {turn_num}\n")
                f.write("=" * 80 + "\n\n")
        except Exception as e:
            print(f"[TRAINING LOG] Error creating training log for {manager_name}: {e}")


def get_training_log_path(turn_num: int, manager_name: str) -> str:
    """Get the path to a manager's training log file."""
    manager_filename = f"turn_{turn_num:04d}_{manager_name.replace(' ', '_')}_training.txt"
    return str(Path(LOGS_DIR) / manager_filename)
