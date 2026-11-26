"""
TEST ARENA backfill of saves/champion_history.json (main-arena Champion per turn).

Same job as backfill_champion_history.py, but for the test instance:
  * NO manually typed turns - every turn comes from the saved newsletters
  * champion = the CHAMPION block of each saved newsletter,
               saves/league/newsletters/turn_NNN.txt
  * manager names = looked up from the team files (managers never trade teams);
    if a team file is gone, a recursive search of the saves folder is tried, then
    the optional MANAGER_OVERRIDES table below

Safe to re-run. It never overwrites a turn already in the history file (entries
written by the live server carry a warrior_id and are authoritative), and it
only writes with --write.

    python backfill_champion_history_TEST_ARENA.py            # preview only
    python backfill_champion_history_TEST_ARENA.py --write    # save the history file

Copy this file, save.py and newsletter.py/league_server.py changes to the test
instance first; run the script from the test instance's folder.
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import save  # noqa: E402  (league data paths + protected save helpers)

NEWSLETTER_DIR = os.path.join(save.SAVES_DIR, "league", "newsletters")

# Optional: team_id -> manager name, for teams whose files no longer exist.
# Example:  MANAGER_OVERRIDES = {67: "Some Manager"}
MANAGER_OVERRIDES = {}

CHAMP_ROW = re.compile(r"^(.+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.+?)\s+\((\d+)\)\s*$")
HEADER = re.compile(r"\x1b\[1;31;98mCHAMPION\x1b\[0m|^CHAMPION\s*$")


def champion_from_newsletter(path):
    """Return (name, team_id, team_name) for the CHAMPION block, or None if vacant."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    for i, line in enumerate(lines):
        if not HEADER.search(line.strip()):
            continue
        for row in lines[i + 1:i + 6]:
            s = row.strip()
            if not s or s.startswith("NAME") or set(s) <= {"="}:
                continue
            m = CHAMP_ROW.match(s)
            if not m:
                return None            # e.g. "(vacant this turn)"
            return m.group(1).strip(), int(m.group(7)), m.group(6).strip()
        return None
    return None


_mgr_cache = {}


def _read_manager(fp):
    try:
        with open(fp, encoding="utf-8") as f:
            return (json.load(f).get("manager_name") or "").strip()
    except Exception:
        return ""


def manager_for_team(team_id):
    if team_id in _mgr_cache:
        return _mgr_cache[team_id]
    name = ""
    for pat in (f"teams/team_{team_id:04d}.json",
                f"elite/teams/team_{team_id:04d}.json",
                f"veteran/teams/team_{team_id:04d}.json"):
        fp = os.path.join(save.SAVES_DIR, pat)
        if os.path.exists(fp):
            name = _read_manager(fp)
            if name:
                break
    if not name:                       # fallback: any copy anywhere under saves/
        target = f"team_{team_id:04d}.json"
        for root, _dirs, files in os.walk(save.SAVES_DIR):
            if target in files:
                name = _read_manager(os.path.join(root, target))
                if name:
                    break
    if not name:
        name = MANAGER_OVERRIDES.get(team_id, "")
    _mgr_cache[team_id] = name
    return name


def main():
    write = "--write" in sys.argv
    history = save.load_champion_history(strict=True)
    found = {}
    vacant = []
    skipped = []
    for fp in sorted(glob.glob(os.path.join(NEWSLETTER_DIR, "turn_*.txt"))):
        base = os.path.basename(fp)
        m = re.fullmatch(r"turn_(\d+)\.txt", base)
        if not m:
            skipped.append(base)       # "turn_006 - Copy.txt", "turn_005(OLD).txt"
            continue
        turn = int(m.group(1))
        champ = champion_from_newsletter(fp)
        if champ:
            found[turn] = champ
        else:
            vacant.append(turn)

    added, kept, no_mgr = 0, 0, []
    for turn in sorted(found):
        name, tid, team_name = found[turn]
        if turn in history:
            kept += 1
            continue
        mgr = manager_for_team(tid)
        if not mgr:
            no_mgr.append((turn, name, tid))
        history[turn] = {"name": name, "warrior_id": None, "team_id": tid,
                         "team_name": team_name, "manager_name": mgr}
        added += 1

    all_turns = sorted(set(found) | set(vacant))
    missing = []
    if all_turns:
        missing = [t for t in range(all_turns[0], all_turns[-1] + 1) if t not in all_turns]

    print(f"newsletters read: {len(all_turns)} (turns {all_turns[0] if all_turns else '-'}"
          f" to {all_turns[-1] if all_turns else '-'})")
    print(f"turns with a champion: {len(found)}   vacant (no champion): {vacant}")
    if missing:
        print(f"NOTE - no newsletter file for turns: {missing}")
    if skipped:
        print(f"ignored non-standard files: {skipped}")
    print(f"to add: {added}   already in history (kept): {kept}")
    if no_mgr:
        print("WARNING - no manager found for (add to MANAGER_OVERRIDES):", no_mgr)
    if write:
        save.save_champion_history(history)
        print(f"WROTE {save.CHAMPION_HISTORY_FILE}  ({len(history)} turns)")
    else:
        print("preview only - run again with --write to save")


if __name__ == "__main__":
    main()
