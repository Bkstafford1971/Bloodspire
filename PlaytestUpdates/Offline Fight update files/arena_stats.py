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

def generate_arena_stats(uploads: dict, turn_num: int, output_dir: str) -> None:
    """
    Generate arena_stats.html in output_dir.

    uploads   : the raw uploads dict from league_server._run_turn()
                { upload_key -> upload_data_dict }
    turn_num  : current turn number
    output_dir: directory to write arena_stats.html into

    Silent on failure — logs to stdout but never raises.
    """
    try:
        _generate(uploads, turn_num, output_dir)
    except Exception as e:
        import traceback
        print(f"  WARNING: arena_stats report failed: {e}")
        traceback.print_exc()


# ── Internal implementation ────────────────────────────────────────────────────

def _generate(uploads: dict, turn_num: int, output_dir: str) -> None:
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
    )

    out_path = os.path.join(output_dir, "arena_stats.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Arena stats report written → {out_path}")

    # ── Push arena stats + hub to GitHub Pages ──────────────────────────────
    try:
        from github_push import push_to_github_pages
        hub_html = _render_hub_html(turn_num)
        push_to_github_pages({
            "arena_stats.html": html,
            "stats_hub.html":   hub_html,
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

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bloodspire — Arena Statistics Turn {turn_num}</title>
  <style>{css}</style>
</head>
<body>
  <div class="site-header">
    <div class="site-name">BLOODSPIRE</div>
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
    {table1}
    {table2}
    {table3}
    {table4}
  </div>
</body>
</html>
"""


# ── Hub landing page ───────────────────────────────────────────────────────────

def _render_hub_html(turn_num: int) -> str:
    """
    Generate the stats_hub.html landing page that links to all reports.
    Styled to match the Bloodspire aesthetic.
    Add new reports here as they are created.
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
        font-size: 2.4em; font-weight: bold; color: #cc0000;
        letter-spacing: 3px;
        text-shadow: 0 0 14px #880000;
    }
    .site-subtitle {
        color: #888; font-size: 0.78em; letter-spacing: 2px;
        text-transform: uppercase; margin-top: 2px;
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
    .report-links li { margin-bottom: 4px; }
    .report-links a {
        color: #cc6600; text-decoration: none;
        font-family: 'Courier New', Courier, monospace;
        font-size: 0.9em;
    }
    .report-links a:hover { color: #ff8800; text-decoration: underline; }
    .report-links a::before { content: "→  "; color: #660000; }
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
  <title>Bloodspire — Arena Facts</title>
  <style>{css}</style>
</head>
<body>
  <div class="site-header">
    <div class="site-name">BLOODSPIRE</div>
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

      <!-- Add new report sections here as they are created -->

    </div>
  </div>

  <div class="footer">
    All data reflects active gladiators as of Turn {turn_num}.
    Reports are overwritten each turn with current data.
  </div>
</body>
</html>
"""
