#!/usr/bin/env python3
"""
tool_launcher.py - BLOODSPIRE Tool Launcher

Small GUI menu listing the project's standalone .bat tools. Click a button
to launch that tool in its own process; the launcher window stays open so
multiple tools can be started without relaunching this menu.
"""
import os
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# (Button label, .bat filename relative to BASE_DIR)
TOOLS = [
    ("Character Sheet Generator",   "generate_character_sheets.bat"),
    ("Simulation Tool",             "run_simulation_tool.bat"),
    ("Warrior Strategy Optimizer",  "run_strategy_optimizer.bat"),
    ("APM Calculator",              "start_apm_calculator.bat"),
    ("HP Calculator",               "start_hp_calculator.bat"),
    ("Matchup Simulator",           "start_matchup_simulator.bat"),
    ("Training Chance Calculator",  "start_training_chance_calculator.bat"),
    ("Combat Sandbox",              "combat sandbox.bat"),
    ("Fight Simulator",             "Fight Simulator.bat"),
]


def launch_tool(bat_filename: str):
    bat_path = os.path.join(BASE_DIR, bat_filename)
    if not os.path.exists(bat_path):
        messagebox.showerror("Tool Not Found", f"Could not find:\n{bat_path}")
        return
    try:
        # New console window per tool; detached so this launcher never blocks
        # or waits on the tool, and closing the launcher doesn't kill tools.
        # Launch the .bat directly (not via "cmd /c start") - wrapping it in
        # `start` spawns an extra outer console that outlives the tool and
        # doesn't close when the tool's window does.
        subprocess.Popen(
            ["cmd.exe", "/c", bat_path],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    except Exception as e:
        messagebox.showerror("Launch Failed", f"Could not start {bat_filename}:\n{e}")


def main():
    root = tk.Tk()
    root.title("BLOODSPIRE Tool Launcher")
    root.geometry("340x420")
    root.resizable(False, False)

    ttk.Label(root, text="BLOODSPIRE Tools", font=("Arial", 14, "bold")).pack(pady=(14, 4))
    ttk.Label(root, text="Select a tool to launch", foreground="#555").pack(pady=(0, 10))

    btn_frame = ttk.Frame(root)
    btn_frame.pack(fill=tk.BOTH, expand=True, padx=16)

    for label, bat_filename in TOOLS:
        ttk.Button(
            btn_frame, text=label, width=32,
            command=lambda f=bat_filename: launch_tool(f),
        ).pack(pady=4)

    root.mainloop()


if __name__ == "__main__":
    main()
