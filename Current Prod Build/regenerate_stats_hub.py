#!/usr/bin/env python3
"""
Regenerate stats_hub.html and all stat pages.
"""

import os
import sys
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from arena_stats import (
    _render_hub_html,
    _load_standings_data,
    _generate_top_teams_page,
    _generate_top_warriors_page,
    _generate_top_warriors_by_kills_page,
    _generate_top_warriors_by_losses_page,
    _generate_top_popularity_page,
    _generate_race_distribution_page as _gen_race_dist
)

def load_config():
    cfg_path = os.path.join(BASE_DIR, "saves", "league", "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"ERROR loading config: {e}")
        return {}

def main():
    print("Regenerating stats hub and stat pages...")

    # Load config
    cfg = load_config()
    current_turn = cfg.get("current_turn", 1)
    # Data is from the previous turn, so display that turn number
    display_turn = max(1, current_turn - 1)
    print(f"  Current turn: {current_turn}, displaying data from turn: {display_turn}")

    # Load standings
    standings = _load_standings_data()

    # Reports directory
    reports_dir = os.path.join(BASE_DIR, "saves", "league", "reports")
    os.makedirs(reports_dir, exist_ok=True)

    # Generate all pages
    print("  Generating pages...")
    pages = {
        "stats_hub.html": _render_hub_html(display_turn),
        "top_teams.html": _generate_top_teams_page(standings, display_turn),
        "top_warriors_wins.html": _generate_top_warriors_page(standings, "wins", "Top 10 Warriors by Wins", display_turn),
        "top_warriors_kills.html": _generate_top_warriors_by_kills_page(standings, display_turn),
        "top_warriors_losses.html": _generate_top_warriors_by_losses_page(standings, display_turn),
        "top_warriors_popularity.html": _generate_top_popularity_page(standings, display_turn),
        "race_distribution.html": _gen_race_dist(standings, display_turn),
    }

    # Write all pages
    for filename, html in pages.items():
        fpath = os.path.join(reports_dir, filename)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"    Written {filename}")

    # Push to GitHub
    try:
        from github_push import push_to_github_pages
        push_to_github_pages(pages)
        print("  Pushed to GitHub Pages")
    except Exception as e:
        print(f"  Warning: GitHub push failed: {e}")

    print("\n[OK] All stat pages regenerated successfully!")

if __name__ == "__main__":
    main()
