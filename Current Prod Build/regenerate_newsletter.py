#!/usr/bin/env python3
"""Regenerate newsletter for a specific turn with updated logic."""

import json
import os
import sys
from pathlib import Path

# Add the BPClone_Claude directory to the path
sys.path.insert(0, r"C:\BPClone_Claude")

from newsletter import generate_newsletter
from save import load_team, load_champion_state
import league_server
import json

LEAGUE_DIR = r"C:\BPClone_Claude\saves\league"

def _load_json(path, default=None):
    """Load JSON from file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default if default is not None else {}

def regenerate_newsletter(turn_num):
    """Regenerate the newsletter for a given turn."""
    # This is complex because newsletter generation expects fully structured objects
    # So instead, we'll use the existing league_server code path
    # by calling the process_turn function which will regenerate the newsletter

    print(f"Regenerating newsletter for Turn {turn_num}...")
    print("This requires re-running turn processing to properly reconstruct fight data.")
    print()
    print("To regenerate the newsletter, you can:")
    print(f"1. Go to http://localhost:8766 → Admin → Rerun Turn {turn_num}")
    print(f"2. Or run: python league_server.py --rerun-turn {turn_num}")
    print()
    print("The newsletter will be automatically regenerated with the fixed career records.")

    # Alternative: Try to directly call the turn processing
    try:
        # Import the turn processing function
        from league_server import process_turn, _load_config, _save_config

        cfg = _load_config()
        current_turn = cfg.get("current_turn", 0)

        if turn_num > current_turn:
            print(f"\nError: Cannot regenerate Turn {turn_num} (current turn is {current_turn})")
            return

        # Set rerun parameters
        cfg["rerun_turn"] = turn_num
        cfg["rerun_count"] = cfg.get("rerun_count", 0) + 1
        _save_config(cfg)

        print(f"\nAttempting to rerun Turn {turn_num}...")
        process_turn(turn_num)

        print(f"✓ Turn {turn_num} newsletter regenerated successfully!")

        # Display newsletter preview
        turn_dir = os.path.join(LEAGUE_DIR, f"turn_{int(turn_num):04d}")
        newsletter_path = os.path.join(turn_dir, "newsletter.txt")
        if os.path.exists(newsletter_path):
            with open(newsletter_path, 'r', encoding='utf-8') as f:
                content = f.read()
                print("\n" + "="*80)
                print("NEWSLETTER PREVIEW (TOP MANAGERS):")
                print("="*80)
                # Find and display the TOP MANAGERS section
                if "TOP MANAGERS" in content:
                    start = content.find("TOP MANAGERS")
                    end = content.find("\n\n", start + 200)
                    if end == -1:
                        end = start + 800
                    print(content[start:end])

    except Exception as e:
        print(f"Error during turn processing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    turn = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    regenerate_newsletter(turn)
