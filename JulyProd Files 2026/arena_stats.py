"""
arena_stats.py — Generate the arena statistics HTML report.

Called once at the end of each turn run via league_server._run_turn().
Any exception is caught and logged; the turn is never interrupted.

Reads from the raw `uploads` dict (pre-fight warrior state) so that:
  - Manager count reflects unique human managers, not team count.
  - Gladiator count includes warriors who died this turn (they were active).
"""

from __future__ import annotations

import os
from collections import defaultdict, Counter
from datetime import datetime
from typing import Dict, List, Optional

# ── Canonical orderings ────────────────────────────────────────────────────────

PLAYABLE_RACES = [
    "Human", "Half-Orc", "Halfling", "Dwarf",
    "Half-Elf", "Elf", "Goblin", "Gnome",
    "Lizardfolk", "Tabaxi",
]

BODY_ARMOR_ORDER = [
    "None", "Cloth", "Leather", "Cuir Boulli", "Brigandine",
    "Scale", "Chain", "Half-Plate", "Full Plate",
]

HELM_ORDER = [
    "None", "Leather Cap", "Steel Cap", "Helm", "Camail", "Full Helm",
]

WEAPON_ORDER = [
    "Stiletto", "Knife", "Dagger", "Short Sword", "Epee", "Scimitar",
    "Long Sword", "Broad Sword", "Bastard Sword", "Great Sword",
    "Hatchet", "Fransisca", "Battle Axe", "Great Axe",
    "Small Pick", "Military Pick", "Pick Axe",
    "Hammer", "Mace", "Morningstar", "War Hammer", "Maul", "Club",
    "Short Spear", "Boar Spear", "Long Spear", "Pole Axe", "Halberd",
    "Flail", "Bladed Flail", "War Flail", "Battle Flail",
    "Quarterstaff", "Great Staff",
    "Buckler", "Target Shield", "Tower Shield",
    "Cestus", "Trident", "Net", "Scythe", "Great Pick", "Javelin",
    "Ball & Chain", "Bola", "Heavy Barbed Whip", "Swordbreaker",
    "Open Hand",
]

# ── Public entry point ─────────────────────────────────────────────────────────

def generate_arena_stats(uploads: dict, team_map: dict, turn_num: int, output_dir: str) -> None:
    """
    Generate arena_stats.html in output_dir.

    uploads   : raw uploads dict (pre-fight warrior state)
    team_map  : post-fight Team objects keyed by upload key
    turn_num  : current turn number
    output_dir: directory to write arena_stats.html into

    Silent on failure — logs to stdout but never raises.
    """
    try:
        _generate(uploads, team_map, turn_num, output_dir)
    except Exception as e:
        import traceback
        print(f"  WARNING: arena_stats report failed: {e}")
        traceback.print_exc()


# ── Internal implementation ────────────────────────────────────────────────────

def _record() -> Dict:
    return {"w": 0, "l": 0, "k": 0}


def _generate(uploads: dict, team_map: dict, turn_num: int, output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)

    # ── Filter to player uploads only (AI keys start with "ai_") ───────────
    player_uploads = {mid: d for mid, d in uploads.items() if not mid.startswith("ai_")}

    # Unique human managers by their real manager_id field (not the upload key,
    # which is "{manager_id}_team{team_id}" for managers with multiple teams).
    manager_count = len({
        d.get("manager_id") for d in player_uploads.values()
        if d.get("manager_id")
    })
    team_count = len(player_uploads)

    # ── Collect pre-fight warriors from upload data (raw dicts) ─────────────
    # Using uploads rather than post-fight team state means warriors who died
    # this turn are included in the count and stats (they were active entrants).
    warriors: List[dict] = []
    for upload in player_uploads.values():
        team_data = upload.get("team") or {}
        for w in (team_data.get("warriors") or []):
            # Skip None slots and warriors already dead before this turn
            if w and not w.get("is_dead"):
                warriors.append(w)

    total = len(warriors)

    # ── Per-race buckets ─────────────────────────────────────────────────────
    by_race: Dict[str, List[dict]] = {r: [] for r in PLAYABLE_RACES}
    for w in warriors:
        race_name = w.get("race", "")
        if race_name in by_race:
            by_race[race_name].append(w)

    # ── Table 1 data: race × gender ──────────────────────────────────────────
    race_gender: Dict[str, Dict] = {}
    for race, ws in by_race.items():
        male   = sum(1 for w in ws if w.get("gender") == "Male")
        female = len(ws) - male
        race_gender[race] = {"Male": male, "Female": female, "Total": len(ws)}

    # ── Table 2 data: body armor × helm cross-tab ────────────────────────────
    armor_helm: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for w in warriors:
        body = w.get("armor") or "None"
        helm = w.get("helm")  or "None"
        armor_helm[body][helm] += 1

    # ── Table 3 data: weapon primary / secondary / backup ────────────────────
    wpn_primary   = Counter(w.get("primary_weapon")   for w in warriors if w.get("primary_weapon"))
    wpn_secondary = Counter(w.get("secondary_weapon") for w in warriors if w.get("secondary_weapon"))
    wpn_backup    = Counter(w.get("backup_weapon")    for w in warriors if w.get("backup_weapon"))

    # ── Table 4 data: most popular weapon & style per race ───────────────────
    race_wpn:   Dict[str, Counter] = {r: Counter() for r in PLAYABLE_RACES}
    race_style: Dict[str, Counter] = {r: Counter() for r in PLAYABLE_RACES}
    for race, ws in by_race.items():
        for w in ws:
            wpn = w.get("primary_weapon")
            if wpn:
                race_wpn[race][wpn] += 1
            style = _always_style(w)
            if style:
                race_style[race][style] += 1

    # ── Turn & career W-L-K records by race and gender ──────────────────────
    # Turn delta = post-fight minus pre-fight for each warrior this turn.
    # Career     = post-fight current warriors + all fallen/replaced warriors.
    turn_race:    Dict[str, Dict] = {r: _record() for r in PLAYABLE_RACES}
    career_race:  Dict[str, Dict] = {r: _record() for r in PLAYABLE_RACES}
    turn_gender:  Dict[str, Dict] = {"Male": _record(), "Female": _record()}
    career_gender: Dict[str, Dict] = {"Male": _record(), "Female": _record()}

    for upload_key, upload in player_uploads.items():
        upload_team  = upload.get("team") or {}
        team_obj     = team_map.get(upload_key)
        pre_warriors = upload_team.get("warriors") or []
        post_warriors = list(team_obj.warriors) if team_obj else []

        for i, pre_w in enumerate(pre_warriors):
            if not pre_w:
                continue
            race   = pre_w.get("race",   "")
            gender = pre_w.get("gender", "")

            # Pre-fight record (from upload)
            pre_w_val = pre_w.get("wins",   0)
            pre_l_val = pre_w.get("losses", 0)
            pre_k_val = pre_w.get("kills",  0)

            # Post-fight record (from team_map Warrior object)
            if team_obj and i < len(post_warriors) and post_warriors[i]:
                pw = post_warriors[i]
                post_w_val = pw.wins
                post_l_val = pw.losses
                post_k_val = pw.kills
            else:
                post_w_val, post_l_val, post_k_val = pre_w_val, pre_l_val, pre_k_val

            dw = post_w_val - pre_w_val
            dl = post_l_val - pre_l_val
            dk = post_k_val - pre_k_val

            # Turn totals
            if race in turn_race:
                turn_race[race]["w"] += dw
                turn_race[race]["l"] += dl
                turn_race[race]["k"] += dk
            if gender in turn_gender:
                turn_gender[gender]["w"] += dw
                turn_gender[gender]["l"] += dl
                turn_gender[gender]["k"] += dk

            # Career totals — post-fight current warriors
            if race in career_race:
                career_race[race]["w"] += post_w_val
                career_race[race]["l"] += post_l_val
                career_race[race]["k"] += post_k_val
            if gender in career_gender:
                career_gender[gender]["w"] += post_w_val
                career_gender[gender]["l"] += post_l_val
                career_gender[gender]["k"] += post_k_val

        # Career totals — fallen/replaced warriors (full career already baked in)
        for fw in (upload_team.get("fallen_warriors") or []):
            if not isinstance(fw, dict):
                continue
            race   = fw.get("race",   "")
            gender = fw.get("gender", "")
            fw_w   = fw.get("wins",   0)
            fw_l   = fw.get("losses", 0)
            fw_k   = fw.get("kills",  0)
            if race in career_race:
                career_race[race]["w"] += fw_w
                career_race[race]["l"] += fw_l
                career_race[race]["k"] += fw_k
            if gender in career_gender:
                career_gender[gender]["w"] += fw_w
                career_gender[gender]["l"] += fw_l
                career_gender[gender]["k"] += fw_k

    html = _render_html(
        turn_num      = turn_num,
        manager_count = manager_count,
        team_count    = team_count,
        total         = total,
        race_gender   = race_gender,
        armor_helm    = armor_helm,
        wpn_primary   = wpn_primary,
        wpn_secondary = wpn_secondary,
        wpn_backup    = wpn_backup,
        race_wpn      = race_wpn,
        race_style    = race_style,
        turn_race     = turn_race,
        career_race   = career_race,
        turn_gender   = turn_gender,
        career_gender = career_gender,
    )

    out_path = os.path.join(output_dir, "arena_stats.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Arena stats report written: {out_path}")

    # ── Push arena stats + hub + stat pages to GitHub Pages ──────────────────────────────
    try:
        from github_push import push_to_github_pages

        # Load standings for stat pages
        standings = _load_standings_data()

        hub_html = _render_hub_html(turn_num)
        top_teams_html = _generate_top_teams_page(standings, turn_num)
        top_wins_html = _generate_top_warriors_page(standings, "wins", "Top 10 Warriors by Wins", turn_num)
        top_kills_html = _generate_top_warriors_by_kills_page(standings, turn_num)
        top_losses_html = _generate_top_warriors_page(standings, "losses", "Top 10 Warriors by Losses", turn_num)
        top_popularity_html = _generate_top_popularity_page(standings, turn_num)
        race_dist_html = _generate_race_distribution_page(standings, turn_num)

        push_to_github_pages({
            "arena_stats.html": html,
            "stats_hub.html": hub_html,
            "top_teams.html": top_teams_html,
            "top_warriors_wins.html": top_wins_html,
            "top_warriors_kills.html": top_kills_html,
            "top_warriors_losses.html": top_losses_html,
            "top_warriors_popularity.html": top_popularity_html,
            "race_distribution.html": race_dist_html,
        })
    except Exception as _gh_err:
        import traceback
        print(f"  WARNING: GitHub Pages push failed: {_gh_err}")
        traceback.print_exc()


def _always_style(warrior: dict) -> Optional[str]:
    """Style of the first 'Always (Default Loop)' strategy row, or None."""
    for strat in (warrior.get("strategies") or []):
        if isinstance(strat, dict) and str(strat.get("trigger", "")).startswith("Always"):
            return strat.get("style")
    return None


def _pct(count: int, total: int) -> str:
    if total == 0 or count == 0:
        return "0.00%"
    return f"{count / total * 100:.2f}%"


def _top(counter: Counter) -> str:
    """Most common value(s); ties joined with ' / ' in alphabetical order."""
    if not counter:
        return "—"
    max_count = counter.most_common(1)[0][1]
    winners = sorted(k for k, v in counter.items() if v == max_count)
    return " / ".join(winners)


def _cell(count: int, total: int) -> str:
    if count == 0:
        return '<td class="zero">0&nbsp;(0.00%)</td>'
    return f"<td>{count}&nbsp;({_pct(count, total)})</td>"


# ── HTML renderer ──────────────────────────────────────────────────────────────

def _render_html(
    turn_num, manager_count, team_count, total,
    race_gender, armor_helm,
    wpn_primary, wpn_secondary, wpn_backup,
    race_wpn, race_style,
    turn_race, career_race,
    turn_gender, career_gender,
) -> str:

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    css = """
    * { box-sizing: border-box; }
    body {
        font-family: 'Courier New', Courier, monospace;
        background: #000000; color: #ffffff;
        margin: 0; font-size: 13px;
    }
    /* ── Page header ── */
    .site-header {
        background: #000;
        border-bottom: 2px solid #880000;
        padding: 18px 32px 14px;
        margin-bottom: 30px;
    }
    .site-name {
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 2.2em; font-weight: bold;
        color: #cc0000;
        letter-spacing: 2px;
        text-shadow: 0 0 12px #880000;
        margin: 0 0 4px;
    }
    .site-subtitle {
        color: #999; font-size: 0.8em; letter-spacing: 1px;
    }
    /* ── Content area ── */
    .content { padding: 0 32px 40px; }
    h1  {
        font-family: Georgia, 'Times New Roman', serif;
        color: #ffffff; font-size: 1.6em;
        text-align: center; margin: 0 0 4px;
        letter-spacing: 1px;
    }
    .meta { color: #666; font-size: 0.80em; text-align: center; margin-bottom: 24px; }
    .summary { margin-bottom: 28px; line-height: 1.9; color: #ffffff; }
    .summary strong { color: #cc0000; }
    h2  {
        color: #cc0000; font-size: 1.0em;
        border-bottom: 1px solid #440000;
        padding-bottom: 3px; margin: 32px 0 10px;
        letter-spacing: 1px; text-transform: uppercase;
    }
    table { border-collapse: collapse; margin-bottom: 8px; }
    th   { background: #111; color: #cc0000; padding: 5px 14px;
           text-align: right; border: 1px solid #330000; white-space: nowrap; }
    th.lbl { text-align: left; min-width: 140px; }
    td   { padding: 3px 14px; border: 1px solid #1a1a1a;
           text-align: right; white-space: nowrap; color: #dddddd; }
    td.lbl   { text-align: left; color: #ff4444; }
    td.plain { text-align: left; color: #dddddd; }
    .zero { color: #333333; }
    tr.tot td { border-top: 2px solid #550000; font-weight: bold;
                background: #0d0000; color: #ffffff; }
    tr.tot td.lbl { color: #ff4444; }
    tr:nth-child(odd)  { background: #080808; }
    tr:nth-child(even) { background: #050505; }
    /* ── Side-by-side table layout ── */
    .tables-row { display: flex; flex-wrap: wrap; gap: 32px; align-items: flex-start; margin-bottom: 8px; }
    .tables-row h2 { margin-top: 0; }
    .tbl-block { flex: 0 0 auto; }
    """

    # ── Table 1: Race × Gender ───────────────────────────────────────────────
    male_tot = female_tot = 0
    rows1 = ""
    for race in PLAYABLE_RACES:
        d = race_gender[race]
        male_tot   += d["Male"]
        female_tot += d["Female"]
        rows1 += (
            f'<tr><td class="lbl">{race}</td>'
            f'{_cell(d["Male"], total)}'
            f'{_cell(d["Female"], total)}'
            f'{_cell(d["Total"], total)}</tr>\n'
        )
    rows1 += (
        '<tr class="tot"><td class="lbl">TOTAL</td>'
        f'{_cell(male_tot, total)}'
        f'{_cell(female_tot, total)}'
        f'{_cell(male_tot + female_tot, total)}</tr>\n'
    )

    table1 = f"""
<h2>Race Distribution</h2>
<table>
  <tr>
    <th class="lbl">Race</th>
    <th>Male</th><th>Female</th><th>TOTAL</th>
  </tr>
  {rows1}
</table>"""

    # ── Table 2: Armor × Helm cross-tab ─────────────────────────────────────
    helm_header = '<tr><th class="lbl">Body \\ Head</th>'
    for h in HELM_ORDER:
        helm_header += f"<th>{h}</th>"
    helm_header += "<th>TOTAL</th></tr>\n"

    col_totals: Dict[str, int] = defaultdict(int)
    grand2 = 0
    rows2 = ""
    for body in BODY_ARMOR_ORDER:
        row_total = 0
        rows2 += f'<tr><td class="lbl">{body}</td>'
        for helm in HELM_ORDER:
            count = armor_helm[body][helm]
            row_total        += count
            col_totals[helm] += count
            rows2 += _cell(count, total)
        grand2 += row_total
        rows2 += f"{_cell(row_total, total)}</tr>\n"

    tot_row2 = '<tr class="tot"><td class="lbl">TOTAL</td>'
    for helm in HELM_ORDER:
        tot_row2 += _cell(col_totals[helm], total)
    tot_row2 += f"{_cell(grand2, total)}</tr>\n"

    table2 = f"""
<h2>Armor × Helm Combinations</h2>
<table>
  {helm_header}
  {rows2}
  {tot_row2}
</table>"""

    # ── Table 3: Weapon usage ────────────────────────────────────────────────
    rows3 = ""
    for wpn in WEAPON_ORDER:
        p = wpn_primary.get(wpn, 0)
        s = wpn_secondary.get(wpn, 0)
        b = wpn_backup.get(wpn, 0)
        if p == 0 and s == 0 and b == 0:
            continue
        rows3 += (
            f'<tr><td class="lbl">{wpn}</td>'
            f'{_cell(p, total)}'
            f'{_cell(s, total)}'
            f'{_cell(b, total)}</tr>\n'
        )

    table3 = f"""
<h2>Weapon Usage</h2>
<table>
  <tr>
    <th class="lbl">Weapon</th>
    <th>Primary</th><th>Secondary</th><th>Backup</th>
  </tr>
  {rows3}
</table>"""

    # ── Table 4: Most popular weapon & style per race ────────────────────────
    rows4 = ""
    for race in PLAYABLE_RACES:
        top_wpn   = _top(race_wpn[race])
        top_style = _top(race_style[race])
        rows4 += (
            f'<tr><td class="lbl">{race}</td>'
            f'<td class="plain">{top_wpn}</td>'
            f'<td class="plain">{top_style}</td></tr>\n'
        )

    table4 = f"""
<h2>Most Popular Weapon &amp; Fighting Style by Race</h2>
<table>
  <tr>
    <th class="lbl">Race</th>
    <th style="text-align:left; min-width:200px">Most Popular Primary Weapon</th>
    <th style="text-align:left; min-width:200px">Most Popular Fighting Style</th>
  </tr>
  {rows4}
</table>"""

    # ── Tables 5–8: record rows with Total Fights and Win% ──────────────────
    def _winpct(w, l):
        fights = w + l
        if fights == 0:
            return '<td class="zero">—</td>'
        return f"<td>{w / fights * 100:.1f}%</td>"

    def _rec_row(label, d):
        fights = d["w"] + d["l"]
        return (f'<tr><td class="lbl">{label}</td>'
                f'<td>{d["w"]}</td><td>{d["l"]}</td><td>{d["k"]}</td>'
                f'<td>{fights}</td>{_winpct(d["w"], d["l"])}</tr>\n')

    rec_header = '<tr><th class="lbl">Race</th><th>W</th><th>L</th><th>K</th><th>Total</th><th>Win%</th></tr>\n'
    gen_header = '<tr><th class="lbl">Gender</th><th>W</th><th>L</th><th>K</th><th>Total</th><th>Win%</th></tr>\n'

    # ── Table 5: This Turn's Race Record ────────────────────────────────────
    rows5 = ""
    for race in PLAYABLE_RACES:
        rows5 += _rec_row(race, turn_race[race])

    table5 = f"""
<h2>This Turn's Race Record</h2>
<table>
  {rec_header}
  {rows5}
</table>"""

    # ── Table 6: Career Race Record ──────────────────────────────────────────
    rows6 = ""
    for race in PLAYABLE_RACES:
        rows6 += _rec_row(race, career_race[race])

    table6 = f"""
<h2>Career Race Record</h2>
<table>
  {rec_header}
  {rows6}
</table>"""

    # ── Table 7: This Turn's Gender Record ──────────────────────────────────
    rows7 = ""
    for gender in ("Male", "Female"):
        rows7 += _rec_row(gender, turn_gender[gender])

    table7 = f"""
<h2>This Turn's Gender Record</h2>
<table>
  {gen_header}
  {rows7}
</table>"""

    # ── Table 8: Career Gender Record ────────────────────────────────────────
    rows8 = ""
    for gender in ("Male", "Female"):
        rows8 += _rec_row(gender, career_gender[gender])

    table8 = f"""
<h2>Career Gender Record</h2>
<table>
  {gen_header}
  {rows8}
</table>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bloodspire Arena — Arena Statistics Turn {turn_num}</title>
  <style>{css}</style>
</head>
<body>
  <div class="site-header">
    <div class="site-name">BLOODSPIRE ARENA</div>
    <div class="site-subtitle">THE AGONY AMPHITHEATRE</div>
  </div>
  <div class="content">
    <h1>Arena Statistics</h1>
    <div class="meta">Turn {turn_num} &nbsp;|&nbsp; Generated: {timestamp}</div>
    <div class="summary">
      <strong>{manager_count}</strong> active managers<br>
      <strong>{team_count}</strong> active teams<br>
      <strong>{total}</strong> active gladiators
    </div>
    <div class="tables-row">
      <div class="tbl-block">{table1}</div>
      <div class="tbl-block">{table5}</div>
      <div class="tbl-block">{table6}</div>
    </div>
    <div class="tables-row">
      <div class="tbl-block">{table7}</div>
      <div class="tbl-block">{table8}</div>
    </div>
    {table2}
    {table3}
    {table4}
  </div>
</body>
</html>
"""


# ── Hub landing page ───────────────────────────────────────────────────────────

def _load_standings_data():
    """Load standings.json data for stats."""
    try:
        import json
        league_dir = os.path.join(os.path.dirname(__file__), "saves", "league")
        standings_path = os.path.join(league_dir, "standings.json")
        with open(standings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {}


def _get_top_teams(standings, limit=10):
    """Get top teams by win percentage from most recent turn results.

    Returns tuple of (teams_list, most_recent_turn_with_results)
    """
    import re
    import json

    # Load most recent results to get accurate records including fallen warriors
    results = {}
    most_recent_turn = 0
    league_dir = os.path.join(os.path.dirname(__file__), "saves", "league")

    for turn in range(9999, -1, -1):
        turn_dir = os.path.join(league_dir, f"turn_{turn:04d}")
        if not os.path.exists(turn_dir):
            continue

        try:
            for fname in os.listdir(turn_dir):
                if fname.startswith("result_") and fname.endswith(".json"):
                    match = re.search(r'result_(\d+)_team(\d+)', fname)
                    if not match:
                        continue

                    mgr_id = int(match.group(1))
                    team_id = int(match.group(2))

                    fpath = os.path.join(turn_dir, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            key = f"{mgr_id}_team{team_id}"
                            if key not in results:
                                results[key] = (data, turn)
                    except Exception:
                        pass
        except Exception:
            pass

        if results:
            # Get the turn from the first result found
            most_recent_turn = next(iter(results.values()))[1]
            break  # Found most recent turn with results

    # Build teams list with records from results
    teams = []
    seen_teams = set()  # Track unique teams to avoid duplicates

    for team_key, team_data in standings.items():
        team_name = team_data.get("team_name", "?")
        team_id = team_data.get("team_id", "?")
        manager = team_data.get("manager_name", "?")

        # Skip invalid teams (missing names or AI teams without proper names)
        if team_name == "?" or not team_name:
            continue

        # Try to get records from most recent results
        w = l = k = 0
        found_in_results = False

        for upload_key, (result_data, result_turn) in results.items():
            if str(team_id) in upload_key:
                # Sum from turn_history for accurate cumulative record
                turn_history = result_data.get("team", {}).get("turn_history", [])
                for turn_entry in turn_history:
                    w += turn_entry.get("w", 0)
                    l += turn_entry.get("l", 0)
                    k += turn_entry.get("k", 0)
                found_in_results = True
                break

        # Fallback to standings if not in results
        if not found_in_results:
            for warrior in team_data.get("warriors", {}).values():
                w += warrior.get("wins", 0)
                l += warrior.get("losses", 0)
                k += warrior.get("kills", 0)

        total = w + l
        pct = (w / total * 100) if total > 0 else 0

        # Create unique key to avoid duplicates (manager + record)
        unique_key = (manager, w, l, k)
        if unique_key not in seen_teams:
            teams.append({"name": team_name, "id": team_id, "manager": manager, "w": w, "l": l, "k": k, "pct": pct})
            seen_teams.add(unique_key)

    teams.sort(key=lambda x: (-x["pct"], -x["w"]))
    return teams[:limit], most_recent_turn


def _extract_warrior_data_from_newsletter(newsletter_path):
    """Extract warrior recognition scores and team names from newsletter file."""
    recognition = {}
    warrior_teams = {}
    try:
        with open(newsletter_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        in_warrior_section = False
        for line in lines:
            line = line.rstrip()

            # Detect section headers
            if "NAME" in line and "W" in line and "L" in line and "K" in line and "REC" in line:
                in_warrior_section = True
                continue
            elif in_warrior_section and line.startswith("="):
                continue
            elif in_warrior_section and not line.strip():
                # Blank line ends the section; "-" prefixed lines are non-fighting warriors (kept)
                in_warrior_section = False
                continue

            if in_warrior_section and line.strip():
                # Parse warrior line: NAME W L K REC TEAM(ID)
                # Lines may start with "- " for warriors who didn't fight this turn — strip it.
                parse_line = line.lstrip()
                if parse_line.startswith("- "):
                    parse_line = parse_line[2:].lstrip()

                parts = parse_line.split()

                if len(parts) >= 6:  # At least: NAME, W, L, K, REC, TEAM_WORD, (ID)
                    try:
                        # Find 4 consecutive numbers (W L K REC)
                        stats_start_idx = -1
                        for i in range(len(parts) - 1):
                            if i + 3 < len(parts):
                                try:
                                    int(parts[i])
                                    int(parts[i + 1])
                                    int(parts[i + 2])
                                    int(parts[i + 3])
                                    # Next part must not be a number (should be team name)
                                    try:
                                        int(parts[i + 4])
                                        continue  # Too many consecutive numbers
                                    except ValueError:
                                        stats_start_idx = i
                                        break
                                except ValueError:
                                    pass

                        if stats_start_idx > 0:
                            rec_val = int(parts[stats_start_idx + 3])
                            warrior_name = " ".join(parts[:stats_start_idx]).strip()

                            # Find team ID (has parentheses)
                            team_id_idx = -1
                            for i in range(len(parts) - 1, -1, -1):
                                if "(" in parts[i]:
                                    team_id_idx = i
                                    break

                            team_str = ""
                            if team_id_idx > stats_start_idx + 4:
                                team_str = " ".join(parts[stats_start_idx + 4:team_id_idx]).strip()

                            if warrior_name:
                                recognition[warrior_name] = rec_val
                                if team_str:
                                    warrior_teams[warrior_name] = team_str
                    except (ValueError, IndexError):
                        pass
    except Exception as e:
        pass

    return recognition, warrior_teams


def _get_top_warriors(standings, stat_field, limit=10):
    """Get top warriors by a specific stat (wins, losses, kills).

    For ties in the stat_field, break ties by recognition ranking (from newsletter).
    Return results sorted by recognition ranking within the top limit.
    """
    import json
    import os

    # Get current turn from config
    league_dir = os.path.join(os.path.dirname(__file__), "saves", "league")
    current_turn = 1
    try:
        config_path = os.path.join(league_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            current_turn = config.get("current_turn", 1)
    except Exception:
        pass

    # Load recognition scores and team names from most recent newsletter
    recognition_scores = {}
    newsletter_warrior_teams = {}
    try:
        # Find the most recent newsletter that exists
        newsletter_path = None
        for turn in range(current_turn, 0, -1):
            candidate = os.path.join(league_dir, f"turn_{int(turn):04d}", "newsletter.txt")
            if os.path.exists(candidate):
                newsletter_path = candidate
                break

        if newsletter_path:
            recognition_scores, newsletter_warrior_teams = _extract_warrior_data_from_newsletter(newsletter_path)
    except Exception:
        pass

    # Load managers data
    managers = {}
    try:
        managers_path = os.path.join(league_dir, "managers.json")
        with open(managers_path, "r", encoding="utf-8") as f:
            managers_data = json.load(f)
            for mgr_id, mgr_info in managers_data.items():
                managers[mgr_id] = mgr_info.get("manager_name", f"Manager {mgr_id}")
    except Exception:
        pass

    # Build warriors list with recognition ranking
    # Use dict to deduplicate by warrior name, keeping the one with most wins
    warriors_dict = {}
    for team_key, team_data in standings.items():
        team_name = team_data.get("team_name", "?")
        manager_name = team_data.get("manager_name", "?")

        for warrior_id, warrior_data in team_data.get("warriors", {}).items():
            name = warrior_data.get("name", "?")
            if name == "?":
                continue  # Skip unnamed warriors

            w = warrior_data.get("wins", 0)
            l = warrior_data.get("losses", 0)
            k = warrior_data.get("kills", 0)

            # Get recognition score from newsletter (default 0)
            recognition = recognition_scores.get(name, 0)

            # Use team name from newsletter if available, otherwise from standings
            display_team = newsletter_warrior_teams.get(name, team_name)

            entry = {
                "name": name, "team": display_team, "wins": w, "losses": l, "kills": k,
                "recognition": recognition, "manager": manager_name
            }

            # Keep only the warrior entry with the most wins (or best record)
            if name not in warriors_dict or w > warriors_dict[name]["wins"]:
                warriors_dict[name] = entry

    # Exclude warriors not in the current newsletter (recognition == 0 means died a prior turn)
    warriors = [w for w in warriors_dict.values() if w["recognition"] > 0]

    warriors.sort(key=lambda x: (-x[stat_field], -x["wins"], -x["recognition"]))

    top_warriors = warriors[:limit]

    return top_warriors


def _get_top_warriors_by_kills(standings, limit=10):
    """Get top warriors by kills (primary), then wins, then recognition."""
    import json
    import os
    import re

    # Get current turn from config
    league_dir = os.path.join(os.path.dirname(__file__), "saves", "league")
    current_turn = 1
    try:
        config_path = os.path.join(league_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            current_turn = config.get("current_turn", 1)
    except Exception:
        pass

    # Load recognition scores and team names from most recent newsletter
    recognition_scores = {}
    newsletter_warrior_teams = {}
    try:
        # Find the most recent newsletter that exists
        newsletter_path = None
        for turn in range(current_turn, 0, -1):
            candidate = os.path.join(league_dir, f"turn_{int(turn):04d}", "newsletter.txt")
            if os.path.exists(candidate):
                newsletter_path = candidate
                break

        if newsletter_path:
            recognition_scores, newsletter_warrior_teams = _extract_warrior_data_from_newsletter(newsletter_path)
    except Exception:
        pass

    # Load managers data
    managers = {}
    try:
        managers_path = os.path.join(league_dir, "managers.json")
        with open(managers_path, "r", encoding="utf-8") as f:
            managers_data = json.load(f)
            for mgr_id, mgr_info in managers_data.items():
                managers[mgr_id] = mgr_info.get("manager_name", f"Manager {mgr_id}")
    except Exception:
        pass

    # Build warrior records from standings (using the entry with most fights as most current)
    # Use dict to deduplicate by warrior name, keeping the entry with most fights
    # Also track entries with proper team names for fallback
    warrior_records = {}
    warrior_teams = {}
    warrior_managers = {}
    for team_key, team_data in standings.items():
        team_name = team_data.get("team_name", "?")
        manager_name = team_data.get("manager_name", "?")

        for warrior_id, warrior_data in team_data.get("warriors", {}).items():
            name = warrior_data.get("name", "?")
            if name == "?" or not name:
                continue

            w = warrior_data.get("wins", 0)
            l = warrior_data.get("losses", 0)
            k = warrior_data.get("kills", 0)
            fights = warrior_data.get("fights", 0)

            entry = {
                "wins": w,
                "losses": l,
                "kills": k,
                "fights": fights
            }

            # Keep the entry with the most fights (most recent/current data)
            if name not in warrior_records or fights > warrior_records[name]["fights"]:
                warrior_records[name] = entry

            # Track best team name for this warrior
            if team_name != "?" and (name not in warrior_teams or fights > warrior_teams[name].get("fights", 0)):
                warrior_teams[name] = {"team": team_name, "fights": fights}

            # Track manager for this warrior
            if name not in warrior_managers or fights > warrior_managers[name].get("fights", 0):
                warrior_managers[name] = {"manager": manager_name, "fights": fights}

    # Build warriors list from records
    warriors = []
    for warrior_name, records in warrior_records.items():
        if warrior_name == "?" or not warrior_name:
            continue

        recognition = recognition_scores.get(warrior_name, 0)
        # Prefer newsletter team, then tracked team with valid name, then fallback
        if warrior_name in newsletter_warrior_teams:
            display_team = newsletter_warrior_teams[warrior_name]
        elif warrior_name in warrior_teams:
            display_team = warrior_teams[warrior_name]["team"]
        else:
            display_team = "?"

        manager_display = warrior_managers.get(warrior_name, {}).get("manager", "?")

        entry = {
            "name": warrior_name,
            "team": display_team,
            "wins": records.get("wins", 0),
            "losses": records.get("losses", 0),
            "kills": records.get("kills", 0),
            "recognition": recognition,
            "manager": manager_display
        }
        warriors.append(entry)

    # Exclude warriors not in the current newsletter (recognition == 0 means died a prior turn)
    warriors = [w for w in warriors if w["recognition"] > 0]

    warriors.sort(key=lambda x: (-x["kills"], -x["wins"], -x["recognition"]))

    top_warriors = warriors[:limit]

    return top_warriors


def _get_top_warriors_by_popularity(standings, limit=10):
    """Get top warriors by popularity."""
    warriors = []
    for team_key, team_data in standings.items():
        team_name = team_data.get("team_name", "?")
        for warrior_id, warrior_data in team_data.get("warriors", {}).items():
            name = warrior_data.get("name", "?")
            pop = warrior_data.get("popularity", 0)
            warriors.append({"name": name, "team": team_name, "popularity": pop})

    warriors.sort(key=lambda x: -x["popularity"])
    return warriors[:limit]


def _get_top_warriors_by_race(standings, limit=10):
    """Get race distribution."""
    races = {}
    for team_key, team_data in standings.items():
        for warrior_id, warrior_data in team_data.get("warriors", {}).items():
            race = warrior_data.get("race", "Unknown")
            if race not in races:
                races[race] = 0
            races[race] += 1

    race_list = [{"race": race, "count": count} for race, count in races.items()]
    race_list.sort(key=lambda x: -x["count"])
    return race_list[:limit]


def _render_hub_html(turn_num: int) -> str:
    """
    Generate the stats_hub.html landing page with statistics.
    Styled to match the Bloodspire aesthetic.
    """
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")


    css = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
        background: #000; color: #fff;
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 14px; line-height: 1.6;
    }
    /* ── Header ── */
    .site-header {
        background: #000;
        border-bottom: 2px solid #880000;
        padding: 20px 40px 16px;
    }
    .site-name {
        font-family: 'Metal Mania', cursive;
        font-size: 3.2em; letter-spacing: 3px; text-transform: uppercase;
        background: linear-gradient(to bottom, #3a0000 0%, #8b1a1a 40%, #a31616 60%, #2a0000 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        display: inline-block;
        filter: drop-shadow(2px 4px 6px rgba(0,0,0,0.8));
        margin: 0;
    }
    .site-subtitle {
        font-family: 'Cinzel', serif;
        color: #888; font-size: 0.82em; letter-spacing: 2px;
        text-transform: uppercase; margin-top: 4px;
    }
    /* ── Main layout ── */
    .main { display: flex; gap: 0; }
    .content {
        padding: 36px 40px 60px;
        flex: 1;
    }
    /* ── Page title ── */
    .page-title {
        font-size: 1.8em; font-weight: bold; color: #fff;
        margin-bottom: 4px; letter-spacing: 1px;
    }
    .page-intro {
        color: #999; font-size: 0.85em; margin-bottom: 36px;
        font-family: 'Courier New', Courier, monospace;
    }
    /* ── Report sections ── */
    .section { margin-bottom: 36px; }
    .section-title {
        font-size: 1.3em; font-weight: bold; color: #cc0000;
        margin-bottom: 6px;
    }
    .section-desc {
        color: #ccc; margin-bottom: 10px;
        font-family: 'Courier New', Courier, monospace;
        font-size: 0.88em;
    }
    .report-links { list-style: none; padding-left: 20px; }
    .report-links li { margin-bottom: 8px; }
    .report-links a {
        color: #ffcc00; text-decoration: none;
        font-family: 'Cinzel', serif;
        font-size: 1.05em; font-weight: bold;
        letter-spacing: 0.5px;
    }
    .report-links a:hover { color: #ffe566; text-decoration: underline; }
    .report-links a::before { content: ">> "; color: #884400; }
    /* ── Footer ── */
    .footer {
        border-top: 1px solid #220000;
        padding: 14px 40px;
        color: #444; font-size: 0.75em;
        font-family: 'Courier New', Courier, monospace;
    }
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bloodspire Arena — Arena Facts</title>
  <link href="https://fonts.googleapis.com/css2?family=Metal+Mania&family=Cinzel:wght@400;700&family=Open+Sans:wght@300;400&display=swap" rel="stylesheet">
  <style>{css}</style>
</head>
<body>
  <div class="site-header">
    <div class="site-name">BLOODSPIRE ARENA</div>
    <div class="site-subtitle">The Agony Amphitheatre</div>
  </div>

  <div class="main">
    <div class="content">

      <div class="page-title">Arena Facts</div>
      <div class="page-intro">
        Turn {turn_num} &nbsp;|&nbsp; Updated: {timestamp}
      </div>

      <div class="section">
        <div class="section-title">Arena Demographics &amp; Statistics</div>
        <div class="section-desc">
          The numbers that define the Agony Amphitheatre. Current race
          distribution, armor and helm combinations, weapon preferences,
          and the fighting styles favored by each race — all at a glance.
        </div>
        <ul class="report-links">
          <li><a href="arena_stats.html">Arena Statistics</a></li>
        </ul>
      </div>

      <div class="section">
        <div class="section-title">Team Rosters</div>
        <div class="section-desc">
          Every active team in the Agony Amphitheatre, grouped by manager.
          Full rosters with warrior records, race, gender, and slot position.
          Dead warriors are noted where they still occupy a team slot.
        </div>
        <ul class="report-links">
          <li><a href="team_roster.html">Team Rosters</a></li>
        </ul>
      </div>

      <div class="section">
        <div class="section-title">Top Warriors &amp; Teams</div>
        <div class="section-desc">
          Rankings and statistics for top teams and individual warriors.
          Wins, kills, losses, popularity, and racial composition.
        </div>
        <ul class="report-links">
          <li><a href="top_teams.html">Top 10 Teams</a></li>
          <li><a href="top_warriors_wins.html">Top 10 Warriors by Wins</a></li>
          <li><a href="top_warriors_kills.html">Top 10 Warriors by Kills</a></li>
          <li><a href="top_warriors_losses.html">Top 10 Warriors by Losses</a></li>
          <li><a href="top_warriors_popularity.html">Top 10 Warriors by Popularity</a></li>
          <li><a href="race_distribution.html">Race Distribution</a></li>
        </ul>
      </div>

    </div>
  </div>

  <div class="footer">
    All data reflects active gladiators as of Turn {turn_num}.
    Reports are overwritten each turn with current data.
  </div>
</body>
</html>
"""


def _render_stat_page(title: str, headers: list, rows: list, turn_num: int, dead_rows: list = None) -> str:
    """Generate a generic stat page with a table."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    header_html = "".join(f'<th style="text-align: left; padding: 8px; color: #ffcc00; border-bottom: 1px solid #440000;">{h}</th>' for h in headers)

    row_html = ""
    for i, row in enumerate(rows):
        is_dead = dead_rows is not None and i < len(dead_rows) and dead_rows[i]
        row_style = ' style="opacity:0.65; color:#888;"' if is_dead else ''
        cells = "".join(f'<td style="padding: 6px; border-bottom: 1px solid #220000;">{cell}</td>' for cell in row)
        row_html += f"<tr{row_style}>{cells}</tr>"

    css = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
        background: #000; color: #fff;
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 14px; line-height: 1.6;
    }
    .site-header {
        background: #000;
        border-bottom: 2px solid #880000;
        padding: 20px 40px 16px;
    }
    .site-name {
        font-family: 'Metal Mania', cursive;
        font-size: 3.2em; letter-spacing: 3px; text-transform: uppercase;
        background: linear-gradient(to bottom, #3a0000 0%, #8b1a1a 40%, #a31616 60%, #2a0000 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        display: inline-block;
        filter: drop-shadow(2px 4px 6px rgba(0,0,0,0.8));
    }
    .content {
        padding: 36px 40px 60px;
        max-width: 900px;
        margin: 0 auto;
    }
    .page-title {
        font-size: 1.8em; font-weight: bold; color: #fff;
        margin-bottom: 12px; letter-spacing: 1px;
    }
    .page-intro {
        color: #999; font-size: 0.85em; margin-bottom: 24px;
        font-family: 'Courier New', Courier, monospace;
    }
    .back-link {
        color: #ffcc00; text-decoration: none; margin-bottom: 20px; display: inline-block;
    }
    .back-link:hover { text-decoration: underline; }
    table {
        width: 100%; border-collapse: collapse;
        font-family: 'Courier New', monospace; font-size: 0.9em;
    }
    .footer {
        border-top: 1px solid #220000;
        padding: 14px 40px;
        color: #444; font-size: 0.75em;
        font-family: 'Courier New', Courier, monospace;
        text-align: center;
        margin-top: 40px;
    }
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bloodspire Arena — {title}</title>
  <link href="https://fonts.googleapis.com/css2?family=Metal+Mania&family=Cinzel:wght@400;700&display=swap" rel="stylesheet">
  <style>{css}</style>
</head>
<body>
  <div class="site-header">
    <div class="site-name">BLOODSPIRE ARENA</div>
  </div>
  <div class="content">
    <a class="back-link" href="stats_hub.html">&lt;&lt; Back to Stats Hub</a>
    <div class="page-title">{title}</div>
    <div class="page-intro">Turn {turn_num} | Updated: {timestamp}</div>
    <table>
      <tr>{header_html}</tr>
      {row_html}
    </table>
  </div>
  <div class="footer">All data as of Turn {turn_num}</div>
</body>
</html>
"""


def _generate_top_teams_page(standings: dict, turn_num: int) -> str:
    """Generate top teams page using data from most recent completed turn."""
    teams, results_turn = _get_top_teams(standings)
    headers = ["Team", "Manager", "W", "L", "K", "%"]
    rows = [[f"{t['name']}", t['manager'], str(t['w']), str(t['l']), str(t['k']), f"{t['pct']:.1f}%"] for t in teams]
    # Use the turn from results, not the current turn
    return _render_stat_page("Top 10 Teams", headers, rows, results_turn if results_turn > 0 else turn_num)


def _generate_top_warriors_page(standings: dict, stat_field: str, title: str, turn_num: int) -> str:
    """Generate top warriors page sorted by wins, then recognition."""
    warriors = _get_top_warriors(standings, stat_field)
    headers = ["Warrior", "Team", "Record", "Recognition", "Manager"]
    rows = []
    for w in warriors:
        rows.append([w['name'], w['team'], f"{w['wins']}-{w['losses']}-{w['kills']}", str(w.get('recognition', 0)), w.get('manager', '?')])
    return _render_stat_page(title, headers, rows, turn_num)


def _generate_top_warriors_by_kills_page(standings: dict, turn_num: int) -> str:
    """Generate top warriors by kills page sorted by kills, then wins, then recognition."""
    warriors = _get_top_warriors_by_kills(standings)
    headers = ["Warrior", "Team", "Record", "Recognition", "Manager"]
    rows = []
    for w in warriors:
        rows.append([w['name'], w['team'], f"{w['wins']}-{w['losses']}-{w['kills']}", str(w.get('recognition', 0)), w.get('manager', '?')])
    return _render_stat_page("Top 10 Warriors by Kills", headers, rows, turn_num)


def _get_top_warriors_by_losses(standings, limit=10):
    """Get top warriors by losses (primary), then wins, then recognition."""
    import json
    import os

    # Get current turn from config
    league_dir = os.path.join(os.path.dirname(__file__), "saves", "league")
    current_turn = 1
    try:
        config_path = os.path.join(league_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            current_turn = config.get("current_turn", 1)
    except Exception:
        pass

    # Load recognition scores and team names from most recent newsletter
    recognition_scores = {}
    newsletter_warrior_teams = {}
    try:
        # Find the most recent newsletter that exists
        newsletter_path = None
        for turn in range(current_turn, 0, -1):
            candidate = os.path.join(league_dir, f"turn_{int(turn):04d}", "newsletter.txt")
            if os.path.exists(candidate):
                newsletter_path = candidate
                break

        if newsletter_path:
            recognition_scores, newsletter_warrior_teams = _extract_warrior_data_from_newsletter(newsletter_path)
    except Exception:
        pass

    # Load managers data
    managers = {}
    try:
        managers_path = os.path.join(league_dir, "managers.json")
        with open(managers_path, "r", encoding="utf-8") as f:
            managers_data = json.load(f)
            for mgr_id, mgr_info in managers_data.items():
                managers[mgr_id] = mgr_info.get("manager_name", f"Manager {mgr_id}")
    except Exception:
        pass

    # Build warrior records from standings (using the entry with most fights as most current)
    # Use dict to deduplicate by warrior name, keeping the entry with most fights
    # Also track entries with proper team names for fallback
    warrior_records = {}
    warrior_teams = {}
    warrior_managers = {}
    for team_key, team_data in standings.items():
        team_name = team_data.get("team_name", "?")
        manager_name = team_data.get("manager_name", "?")

        for warrior_id, warrior_data in team_data.get("warriors", {}).items():
            name = warrior_data.get("name", "?")
            if name == "?" or not name:
                continue

            w = warrior_data.get("wins", 0)
            l = warrior_data.get("losses", 0)
            k = warrior_data.get("kills", 0)
            fights = warrior_data.get("fights", 0)

            entry = {
                "wins": w,
                "losses": l,
                "kills": k,
                "fights": fights
            }

            # Keep the entry with the most fights (most recent/current data)
            if name not in warrior_records or fights > warrior_records[name]["fights"]:
                warrior_records[name] = entry

            # Track best team name for this warrior
            if team_name != "?" and (name not in warrior_teams or fights > warrior_teams[name].get("fights", 0)):
                warrior_teams[name] = {"team": team_name, "fights": fights}

            # Track manager for this warrior
            if name not in warrior_managers or fights > warrior_managers[name].get("fights", 0):
                warrior_managers[name] = {"manager": manager_name, "fights": fights}

    # Build warriors list from records
    warriors = []
    for warrior_name, records in warrior_records.items():
        if warrior_name == "?" or not warrior_name:
            continue

        recognition = recognition_scores.get(warrior_name, 0)
        # Prefer newsletter team, then tracked team with valid name, then fallback
        if warrior_name in newsletter_warrior_teams:
            display_team = newsletter_warrior_teams[warrior_name]
        elif warrior_name in warrior_teams:
            display_team = warrior_teams[warrior_name]["team"]
        else:
            display_team = "?"

        manager_display = warrior_managers.get(warrior_name, {}).get("manager", "?")

        entry = {
            "name": warrior_name,
            "team": display_team,
            "wins": records.get("wins", 0),
            "losses": records.get("losses", 0),
            "kills": records.get("kills", 0),
            "recognition": recognition,
            "manager": manager_display
        }
        warriors.append(entry)

    # Exclude warriors not in the current newsletter (recognition == 0 means died a prior turn)
    warriors = [w for w in warriors if w["recognition"] > 0]

    warriors.sort(key=lambda x: (-x["losses"], -x["wins"], -x["recognition"]))

    top_warriors = warriors[:limit]

    return top_warriors


def _generate_top_warriors_by_losses_page(standings: dict, turn_num: int) -> str:
    """Generate top warriors by losses page sorted by losses, then wins, then recognition."""
    warriors = _get_top_warriors_by_losses(standings)
    headers = ["Warrior", "Team", "Record", "Recognition", "Manager"]
    rows = []
    for w in warriors:
        rows.append([w['name'], w['team'], f"{w['wins']}-{w['losses']}-{w['kills']}", str(w.get('recognition', 0)), w.get('manager', '?')])
    return _render_stat_page("Top 10 Warriors by Losses", headers, rows, turn_num)


def _generate_race_distribution_page(standings: dict, turn_num: int) -> str:
    """Generate warriors by race page with top 10 per race sorted by recognition."""
    import json
    import os

    # Get current turn from config
    league_dir = os.path.join(os.path.dirname(__file__), "saves", "league")
    current_turn = 1
    try:
        config_path = os.path.join(league_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            current_turn = config.get("current_turn", 1)
    except Exception:
        pass

    # Load recognition scores from most recent newsletter (go back further to find one)
    recognition_scores = {}
    try:
        newsletter_path = None
        for turn in range(current_turn + 5, 0, -1):  # Look back further
            candidate = os.path.join(league_dir, f"turn_{int(turn):04d}", "newsletter.txt")
            if os.path.exists(candidate):
                newsletter_path = candidate
                break

        if newsletter_path:
            recognition_scores, _ = _extract_warrior_data_from_newsletter(newsletter_path)
    except Exception:
        pass

    # Load managers data
    managers = {}
    try:
        managers_path = os.path.join(league_dir, "managers.json")
        with open(managers_path, "r", encoding="utf-8") as f:
            managers_data = json.load(f)
            for mgr_id, mgr_info in managers_data.items():
                managers[mgr_id] = mgr_info.get("manager_name", f"Manager {mgr_id}")
    except Exception:
        pass

    # Build warrior records grouped by race (from result files for accurate race data)
    warriors_by_race = {}
    for race in PLAYABLE_RACES:
        warriors_by_race[race] = []

    # Collect warrior data with race and stats from result files
    warriors_with_race = {}
    for turn in range(current_turn, 0, -1):
        turn_dir = os.path.join(league_dir, f"turn_{int(turn):04d}")
        if not os.path.exists(turn_dir):
            continue

        try:
            result_files = [f for f in os.listdir(turn_dir) if f.startswith("result_") and f.endswith(".json")]
        except Exception:
            continue

        for result_file in result_files:
            try:
                with open(os.path.join(turn_dir, result_file), "r", encoding="utf-8") as f:
                    result_data = json.load(f)
                    team_data = result_data.get("team", {})
                    team_name = team_data.get("team_name", "?")
                    team_id = team_data.get("team_id", "?")
                    turn_history = result_data.get("turn_history", {})

                    # Extract manager ID from result filename
                    parts = result_file.replace("result_", "").replace(".json", "").split("_")
                    manager_id = parts[0] if parts else "?"
                    manager_name = managers.get(manager_id, f"Manager {manager_id}")

                    for warrior in team_data.get("warriors", []):
                        name = warrior.get("name", "?")
                        if name == "?" or not name:
                            continue

                        race = warrior.get("race", "?")
                        gender = warrior.get("gender", "?")

                        # Get cumulative stats from warrior object in result file
                        w = warrior.get("wins", 0)
                        l = warrior.get("losses", 0)
                        k = warrior.get("kills", 0)
                        fights = w + l  # Calculate fights from wins + losses

                        recognition = recognition_scores.get(name, 0)

                        entry = {
                            "name": name,
                            "race": race,
                            "gender": gender,
                            "wins": w,
                            "losses": l,
                            "kills": k,
                            "recognition": recognition,
                            "team_name": team_name,
                            "team_id": team_id,
                            "manager_name": manager_name,
                            "manager_id": manager_id,
                            "fights": fights
                        }

                        # Keep entry with most fights (most complete record)
                        if name not in warriors_with_race or fights > warriors_with_race[name]["fights"]:
                            warriors_with_race[name] = entry
            except Exception:
                pass

    # Group into races
    for warrior_name, warrior_entry in warriors_with_race.items():
        race = warrior_entry["race"]
        if race in warriors_by_race:
            warriors_by_race[race].append(warrior_entry)

    # Sort each race by recognition (descending) and take top 10
    for race in warriors_by_race:
        warriors_by_race[race].sort(key=lambda x: (-x["recognition"], -x["wins"]))
        warriors_by_race[race] = warriors_by_race[race][:10]

    # Generate HTML
    html_parts = []
    html_parts.append(_render_page_header(f"Warriors by Race as of turn {turn_num}"))

    # Plural mapping for races
    race_plural = {
        "Human": "Humans",
        "Half-Orc": "Half-Orcs",
        "Halfling": "Halflings",
        "Dwarf": "Dwarves",
        "Half-Elf": "Half-Elves",
        "Elf": "Elves",
        "Goblin": "Goblins",
        "Gnome": "Gnomes",
        "Lizardfolk": "Lizardfolk",
        "Tabaxi": "Tabaxi",
    }

    for race in PLAYABLE_RACES:
        if not warriors_by_race[race]:
            continue

        race_name_plural = race_plural.get(race, f"{race}s")
        html_parts.append(f"<h2>Top 10 {race_name_plural} by Ranking</h2>")
        html_parts.append("<table style=\"width: 100%; border-collapse: collapse; font-family: 'Courier New', monospace; font-size: 0.85em; margin-bottom: 40px;\">")
        html_parts.append("<tr style=\"background-color: #1a1a1a; border-bottom: 2px solid #440000;\">")
        html_parts.append("<th style=\"text-align: left; padding: 8px; color: #ffcc00;\">Warrior Name</th>")
        html_parts.append("<th style=\"text-align: center; padding: 8px; color: #ffcc00; width: 40px;\">Win</th>")
        html_parts.append("<th style=\"text-align: center; padding: 8px; color: #ffcc00; width: 40px;\">Loss</th>")
        html_parts.append("<th style=\"text-align: center; padding: 8px; color: #ffcc00; width: 40px;\">Kill</th>")
        html_parts.append("<th style=\"text-align: center; padding: 8px; color: #ffcc00; width: 50px;\">Ranked</th>")
        html_parts.append("<th style=\"text-align: left; padding: 8px; color: #ffcc00;\">Team Name (Team#)</th>")
        html_parts.append("<th style=\"text-align: left; padding: 8px; color: #ffcc00;\">Manager Name (Manager#)</th>")
        html_parts.append("</tr>")

        for warrior in warriors_by_race[race]:
            # Grey out entire row for dead warriors (recognition = 0)
            row_style = "color: #666;" if warrior['recognition'] == 0 else ""
            html_parts.append(f"<tr style=\"border-bottom: 1px solid #220000; {row_style}\">")
            html_parts.append(f"<td style=\"padding: 6px;\">{warrior['name']}</td>")
            html_parts.append(f"<td style=\"padding: 6px; text-align: center;\">{warrior['wins']}</td>")
            html_parts.append(f"<td style=\"padding: 6px; text-align: center;\">{warrior['losses']}</td>")
            html_parts.append(f"<td style=\"padding: 6px; text-align: center;\">{warrior['kills']}</td>")
            html_parts.append(f"<td style=\"padding: 6px; text-align: center;\">{warrior['recognition']}</td>")
            html_parts.append(f"<td style=\"padding: 6px;\">{warrior['team_name']} ({warrior['team_id']})</td>")
            html_parts.append(f"<td style=\"padding: 6px;\">{warrior['manager_name']} ({warrior['manager_id']})</td>")
            html_parts.append("</tr>")

        html_parts.append("</table>")

    html_parts.append(_render_page_footer(turn_num))

    return "\n".join(html_parts)


def _render_page_header(title: str) -> str:
    """Render the HTML page header."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bloodspire Arena — {title}</title>
  <link href="https://fonts.googleapis.com/css2?family=Metal+Mania&family=Cinzel:wght@400;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
        background: #000; color: #fff;
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 14px; line-height: 1.6;
    }}
    .site-header {{
        background: #000;
        border-bottom: 2px solid #880000;
        padding: 20px 40px 16px;
    }}
    .site-name {{
        font-family: 'Metal Mania', cursive;
        font-size: 3.2em; letter-spacing: 3px; text-transform: uppercase;
        background: linear-gradient(to bottom, #3a0000 0%, #8b1a1a 40%, #a31616 60%, #2a0000 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        display: inline-block;
        filter: drop-shadow(2px 4px 6px rgba(0,0,0,0.8));
    }}
    .content {{
        padding: 36px 40px 60px;
        max-width: 100%;
    }}
    .page-title {{
        font-size: 1.8em; font-weight: bold; color: #fff;
        margin-bottom: 12px; letter-spacing: 1px;
    }}
    .page-intro {{
        color: #999; font-size: 0.85em; margin-bottom: 24px;
        font-family: 'Courier New', Courier, monospace;
    }}
    .back-link {{
        color: #ffcc00; text-decoration: none; margin-bottom: 20px; display: inline-block;
    }}
    .back-link:hover {{ text-decoration: underline; }}
    h2 {{
        color: #fff; font-size: 1.3em; margin-top: 40px; margin-bottom: 16px;
        letter-spacing: 1px;
    }}
    .footer {{
        border-top: 1px solid #220000;
        padding: 14px 40px;
        color: #444; font-size: 0.75em;
        font-family: 'Courier New', Courier, monospace;
        text-align: center;
        margin-top: 40px;
    }}
  </style>
</head>
<body>
  <div class="site-header">
    <div class="site-name">BLOODSPIRE ARENA</div>
  </div>
  <div class="content">
    <a class="back-link" href="stats_hub.html">&lt;&lt; Back to Stats Hub</a>
    <div class="page-title">{title}</div>
    <div class="page-intro">Updated: {timestamp}</div>
"""


def _render_page_footer(turn_num: int) -> str:
    """Render the HTML page footer."""
    return f"""
  </div>
  <div class="footer">All data as of Turn {turn_num}</div>
</body>
</html>
"""


def _generate_top_popularity_page(standings: dict, turn_num: int) -> str:
    """Generate top popularity page."""
    warriors = _get_top_warriors_by_popularity(standings)
    headers = ["Warrior", "Team", "Popularity"]
    rows = [[w['name'], w['team'], str(w['popularity'])] for w in warriors]
    return _render_stat_page("Top 10 Warriors by Popularity", headers, rows, turn_num)


