"""
One-off script: regenerate the warrior stat pages from the current
standings.json + turn 9 newsletter, then push to GitHub Pages.
Run from the BPClone_Claude directory:  python regen_stats.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from arena_stats import (
    _load_standings_data,
    _render_hub_html,
    _generate_top_teams_page,
    _generate_top_warriors_page,
    _generate_top_warriors_by_kills_page,
    _generate_top_warriors_by_losses_page,
    _generate_top_popularity_page,
    _generate_race_distribution_page,
)
from github_push import push_to_github_pages
import json

# Determine current turn
league_dir = os.path.join(os.path.dirname(__file__), "saves", "league")
config_path = os.path.join(league_dir, "config.json")
with open(config_path) as f:
    turn_num = json.load(f).get("current_turn", 9) - 1

print(f"Regenerating stat pages for turn {turn_num}...")

standings = _load_standings_data()
if not standings:
    print("ERROR: Could not load standings.json")
    sys.exit(1)

pages = {
    "stats_hub.html":               _render_hub_html(turn_num),
    "top_teams.html":               _generate_top_teams_page(standings, turn_num),
    "top_warriors_wins.html":       _generate_top_warriors_page(standings, "wins",   "Top 10 Warriors by Wins",   turn_num),
    "top_warriors_kills.html":      _generate_top_warriors_by_kills_page(standings, turn_num),
    "top_warriors_losses.html":     _generate_top_warriors_by_losses_page(standings, turn_num),
    "top_warriors_popularity.html": _generate_top_popularity_page(standings, turn_num),
    "race_distribution.html":       _generate_race_distribution_page(standings, turn_num),
}

print(f"Pushing {len(pages)} pages to GitHub Pages...")
push_to_github_pages(pages)
print("Done.")
