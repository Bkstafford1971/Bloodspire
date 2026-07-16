#!/usr/bin/env python3
"""
BLOODSPIRE Warrior HP Calculator
Simple GUI to calculate warrior HP based on race and attributes.
"""

import tkinter as tk
from tkinter import ttk
import math

# HP bonus for each playable race
RACES = {
    "Human": 0,
    "Half-Orc": 6,
    "Halfling": -2,
    "Dwarf": 8,
    "Half-Elf": 0,
    "Elf": -2,
    "Goblin": -3,
    "Gnome": 5,
    "Lizardfolk": 6,
    "Tabaxi": -2,
}

STAT_RANGE = list(range(3, 26))  # 3-25


def calculate_hp(strength, constitution, size, race_bonus):
    """Calculate HP using formula: ceil(CON * 2.5 + STR + SIZ) + racial_bonus"""
    base_hp = math.ceil(constitution * 2.5 + strength + size)
    return base_hp + race_bonus


def update_hp(*args):
    """Update HP display when any value changes"""
    try:
        strength = int(strength_var.get())
        constitution = int(constitution_var.get())
        size = int(size_var.get())
        race = race_var.get()

        if not (3 <= strength <= 25 and 3 <= constitution <= 25 and 3 <= size <= 25):
            hp_value.config(text="--")
            return

        if race not in RACES:
            hp_value.config(text="--")
            return

        race_bonus = RACES[race]
        hp = calculate_hp(strength, constitution, size, race_bonus)
        hp_value.config(text=str(hp))
    except (ValueError, KeyError):
        hp_value.config(text="--")


# Create main window
root = tk.Tk()
root.title("BLOODSPIRE HP Calculator")
root.geometry("320x280")
root.resizable(False, False)

# Configure style
style = ttk.Style()
style.theme_use('clam')

# Main frame
main_frame = ttk.Frame(root, padding="15")
main_frame.pack(fill=tk.BOTH, expand=True)

# Race dropdown
ttk.Label(main_frame, text="Race:", font=("Arial", 10)).grid(row=0, column=0, sticky="w", pady=5)
race_var = tk.StringVar(value="Human")
race_dropdown = ttk.Combobox(main_frame, textvariable=race_var, values=list(RACES.keys()),
                              state="readonly", width=25)
race_dropdown.grid(row=0, column=1, sticky="ew", pady=5)

# Strength field
ttk.Label(main_frame, text="Strength:", font=("Arial", 10)).grid(row=1, column=0, sticky="w", pady=5)
strength_var = tk.StringVar(value="12")
strength_spinbox = ttk.Spinbox(main_frame, from_=3, to=25, textvariable=strength_var, width=25)
strength_spinbox.grid(row=1, column=1, sticky="ew", pady=5)

# Constitution field
ttk.Label(main_frame, text="Constitution:", font=("Arial", 10)).grid(row=2, column=0, sticky="w", pady=5)
constitution_var = tk.StringVar(value="12")
constitution_spinbox = ttk.Spinbox(main_frame, from_=3, to=25, textvariable=constitution_var, width=25)
constitution_spinbox.grid(row=2, column=1, sticky="ew", pady=5)

# Size field
ttk.Label(main_frame, text="Size:", font=("Arial", 10)).grid(row=3, column=0, sticky="w", pady=5)
size_var = tk.StringVar(value="12")
size_spinbox = ttk.Spinbox(main_frame, from_=3, to=25, textvariable=size_var, width=25)
size_spinbox.grid(row=3, column=1, sticky="ew", pady=5)

# Register trace callbacks for real-time updates
strength_var.trace_add("write", update_hp)
constitution_var.trace_add("write", update_hp)
size_var.trace_add("write", update_hp)
race_var.trace_add("write", update_hp)

# HP Display
hp_frame = ttk.LabelFrame(main_frame, text="Max HP", padding="10")
hp_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=15)

hp_value = tk.Label(hp_frame, text="39", font=("Arial", 32, "bold"), fg="#2E7D32")
hp_value.pack(expand=True)

# Configure grid weights for responsive layout
main_frame.columnconfigure(1, weight=1)

# Initial calculation
update_hp()

root.mainloop()
