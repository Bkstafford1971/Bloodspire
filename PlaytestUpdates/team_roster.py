"""
team_roster.py — Generate the team roster HTML report.

Groups all player teams by manager, sorted alphabetically.
Called from arena_stats._generate() so it's included in the GitHub push.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

# ── Public interface ───────────────────────────────────────────────────────────

def generate_team_roster_html(uploads: dict, team_map: dict, turn_num: int) -> str:
    """Build and return the team_roster.html content string.

    uploads  : raw upload dict (for manager IDs and fallen_warriors)
    team_map : post-fight Team objects keyed by upload key (for live records)
    """
    return _build_html(uploads, team_map, turn_num)


def write_team_roster(html: str, output_dir: str) -> None:
    """Write team_roster.html to output_dir and push to GitHub Pages."""
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "team_roster.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Team roster report written -> {out_path}")
    try:
        from github_push import push_to_github_pages
        push_to_github_pages({"team_roster.html": html})
    except Exception as _gh_err:
        print(f"  WARNING: team_roster GitHub push failed: {_gh_err}")


# ── Data processing ────────────────────────────────────────────────────────────

def _team_record(team_data: dict):
    """Sum W-L-K across current warriors + fallen warriors for all-time record."""
    tw = tl = tk = 0
    for w in (team_data.get("warriors") or []):
        if w:
            tw += w.get("wins",   0)
            tl += w.get("losses", 0)
            tk += w.get("kills",  0)
    for fw in (team_data.get("fallen_warriors") or []):
        if isinstance(fw, dict):
            tw += fw.get("wins",   0)
            tl += fw.get("losses", 0)
            tk += fw.get("kills",  0)
    return tw, tl, tk


def _warrior_record(w_obj) -> tuple:
    """Extract W-L-K from a Warrior object (post-fight) or raw dict (fallback)."""
    if hasattr(w_obj, "wins"):
        return w_obj.wins, w_obj.losses, w_obj.kills
    return w_obj.get("wins", 0), w_obj.get("losses", 0), w_obj.get("kills", 0)


def _build_html(uploads: dict, team_map: dict, turn_num: int) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Filter to player teams ───────────────────────────────────────────────
    player_uploads = {mid: d for mid, d in uploads.items() if not mid.startswith("ai_")}

    # ── Group by real manager_id, keeping the upload key for team_map lookup ─
    by_manager: Dict[str, List[tuple]] = defaultdict(list)  # real_mid -> [(upload_key, upload)]
    manager_names: Dict[str, str]      = {}

    for upload_key, d in player_uploads.items():
        real_mid = str(d.get("manager_id", ""))
        by_manager[real_mid].append((upload_key, d))
        manager_names[real_mid] = d.get("manager_name", real_mid)

    sorted_mgr_ids = sorted(
        by_manager.keys(),
        key=lambda m: int(m) if str(m).isdigit() else float("inf")
    )

    # ── Build roster HTML ────────────────────────────────────────────────────
    roster_blocks = ""
    for mgr_id in sorted_mgr_ids:
        mgr_name = manager_names[mgr_id]
        teams    = sorted(by_manager[mgr_id],
                          key=lambda t: t[1].get("team", {}).get("team_id", 0))

        team_blocks = ""
        for upload_key, upload in teams:
            upload_team = upload.get("team") or {}
            team_name   = upload_team.get("team_name", "?")
            team_id     = upload_team.get("team_id",   "?")
            last_turn   = upload_team.get("last_turn_ran") or "—"

            # Use post-fight Team object from team_map when available
            team_obj  = team_map.get(upload_key)

            if team_obj is not None:
                # Post-fight warriors (includes dead from this turn)
                raw_warriors = team_obj.warriors or []
                # Add archived warriors (those replaced in previous turns with their final stats)
                archived = team_obj.archived_warriors or []
                tw = tl = tk = 0
                for w in raw_warriors:
                    if w:
                        ww, wl, wk = _warrior_record(w)
                        tw += ww; tl += wl; tk += wk
                for aw in archived:
                    if isinstance(aw, dict):
                        tw += aw.get("wins", 0)
                        tl += aw.get("losses", 0)
                        tk += aw.get("kills", 0)
            else:
                # Fallback: read from upload data (pre-fight)
                raw_warriors = upload_team.get("warriors") or []
                tw, tl, tk   = _team_record(upload_team)

            warrior_rows = ""
            for i, w in enumerate(raw_warriors):
                if not w:
                    continue
                if hasattr(w, "name"):
                    # Warrior object
                    name   = w.name
                    race   = w.race.name if hasattr(w.race, "name") else str(w.race)
                    gender = w.gender
                    ww, wl, wk = _warrior_record(w)
                    slot   = (w.slot_index if w.slot_index is not None else i) + 1
                    dead   = w.is_dead
                else:
                    # Raw dict fallback
                    name   = w.get("name",   "?")
                    race   = w.get("race",   "?")
                    gender = w.get("gender", "?")
                    ww, wl, wk = _warrior_record(w)
                    slot   = (w.get("slot_index") if w.get("slot_index") is not None else i) + 1
                    dead   = w.get("is_dead", False)

                dead_tag = '<span class="dead-flag">Dead</span>' if dead else ""
                warrior_rows += f"""
          <div class="w-row{'  w-dead' if dead else ''}">
            <span class="w-name">{name}</span>
            <span class="w-race">{race}</span>
            <span class="w-gender">{gender}</span>
            <span class="w-record">{ww}-{wl}-{wk}</span>
            <span class="w-slot">{slot}</span>
            {dead_tag}
          </div>"""

            team_blocks += f"""
        <div class="team-block">
          <div class="team-row">
            <span class="t-name">{team_name} ({team_id})</span>
            <span class="t-record">{tw}-{tl}-{tk}</span>
            <span class="t-spacer"></span>
            <span class="t-turn">Last Ran Turn {last_turn}</span>
          </div>
          {warrior_rows}
        </div>"""

        roster_blocks += f"""
      <div class="mgr-block">
        <div class="mgr-row">Manager: {mgr_name.upper()} ({mgr_id})</div>
        {team_blocks}
      </div>"""

    return _render_page(roster_blocks, turn_num, timestamp)


# ── HTML template ──────────────────────────────────────────────────────────────

def _render_page(roster_blocks: str, turn_num: int, timestamp: str) -> str:
    css = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
        background: #000; color: #fff;
        font-family: 'Courier New', Courier, monospace;
        font-size: 13px;
    }
    /* ── Header ── */
    .site-header {
        background: #000;
        border-bottom: 2px solid #880000;
        padding: 18px 32px 14px;
    }
    .site-name {
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 2.2em; font-weight: bold;
        color: #cc0000; letter-spacing: 2px;
        text-shadow: 0 0 12px #880000;
    }
    .site-subtitle { color: #888; font-size: 0.78em; letter-spacing: 2px; }

    /* ── Content ── */
    .content { padding: 28px 32px 60px; }
    h1 {
        font-family: Georgia, 'Times New Roman', serif;
        color: #fff; font-size: 1.5em;
        text-align: center; letter-spacing: 1px;
        margin-bottom: 4px;
    }
    .meta { color: #555; font-size: 0.80em; text-align: center; margin-bottom: 28px; }

    /* ── Manager block ── */
    .mgr-block { margin-bottom: 28px; }
    .mgr-row {
        color: #cc0000; font-weight: bold;
        font-size: 1.05em; margin-bottom: 6px;
        border-bottom: 1px solid #2a0000;
        padding-bottom: 3px;
    }

    /* ── Team block ── */
    .team-block { margin-left: 16px; margin-bottom: 14px; }
    .team-row {
        display: flex; align-items: center;
        background: #0d0000;
        padding: 4px 10px;
        margin-bottom: 2px;
        border-left: 3px solid #660000;
    }
    .t-name   { flex: 0 0 260px; color: #cc6600; font-weight: bold; }
    .t-record { flex: 0 0 110px; color: #dddddd; }
    .t-spacer { flex: 1; }
    .t-turn   { flex: 0 0 auto; color: #666; font-size: 0.9em; white-space: nowrap; }

    /* ── Warrior rows ── */
    .w-row {
        display: flex; align-items: center;
        padding: 2px 10px 2px 28px;
        border-left: 1px solid #1a1a1a;
        margin-bottom: 1px;
    }
    .w-row:nth-child(odd)  { background: #080808; }
    .w-row:nth-child(even) { background: #050505; }
    .w-dead { opacity: 0.55; }

    .w-name   { flex: 0 0 210px; color: #dddddd; }
    .w-race   { flex: 0 0 110px; color: #aaaaaa; }
    .w-gender { flex: 0 0 80px;  color: #aaaaaa; }
    .w-record { flex: 0 0 100px; color: #cccccc; }
    .w-slot   { flex: 0 0 36px;  color: #555; text-align: right; }
    .dead-flag { flex: 0 0 auto; margin-left: 12px; color: #cc0000; font-weight: bold; font-size: 0.9em; }

    /* ── Footer ── */
    .footer {
        border-top: 1px solid #1a0000; padding: 12px 32px;
        color: #444; font-size: 0.75em;
    }
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bloodspire -- Team Rosters Turn {turn_num}</title>
  <style>{css}</style>
</head>
<body>
  <div class="site-header">
    <div class="site-name">BLOODSPIRE</div>
    <div class="site-subtitle">THE AGONY AMPHITHEATRE</div>
  </div>
  <div class="content">
    <h1>Team Rosters</h1>
    <div class="meta">Turn {turn_num} &nbsp;|&nbsp; Generated: {timestamp}</div>
    {roster_blocks}
  </div>
  <div class="footer">
    All records shown are cumulative (current warriors + fallen warriors).
    Dead warriors are shown at reduced opacity.
  </div>
</body>
</html>
"""
