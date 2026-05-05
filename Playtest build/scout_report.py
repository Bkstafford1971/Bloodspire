# =============================================================================
# scout_report.py — In-character scout report generator
# =============================================================================
# Produces a written field report based on observed warrior data.
# The scout does not know the warrior's true stats — they only see what a
# trained eye can infer from watching a single fight.
# =============================================================================
import random

# ---------------------------------------------------------------------------
# SCOUT IDENTITIES
# ---------------------------------------------------------------------------

_SCOUT_NAMES = [
    "Aldric Fenbourne",
    "Mira Coldtongue",
    "Gorst the Watcher",
    "Sable Rennwick",
    "Pell Ashford",
    "Dex Ironquill",
    "Bryndis Marsh",
    "Old Corwin",
    "Nessa Vane",
    "Thane Duskhollow",
]

_SCOUT_TITLES = [
    "Arena Scout",
    "Field Observer",
    "Pit Correspondent",
    "Hired Eyes",
    "Freelance Scout",
    "Stable Informant",
    "Arena Analyst",
]

# ---------------------------------------------------------------------------
# STYLE ASSESSMENTS — what a watching scout would infer from each style
# ---------------------------------------------------------------------------

_STYLE_DESCRIPTIONS = {
    "Total Kill":          ("aggressive and reckless, throwing everything into each attack with no thought for personal safety",
                            "has a dangerous berserker streak — fights to end things fast, never defensive"),
    "Wall of Steel":       ("relentlessly offensive, raining blows without pause",
                            "overwhelming volume of attacks — may tire, but keeps the opponent on the back foot"),
    "Lunge":               ("favours committed, reaching attacks that sacrifice position for reach",
                            "willing to overextend for the kill blow — watch for a counter"),
    "Bash":                ("heavy and brutal, seeking to power through defences with raw force",
                            "relying on strength over technique — punishing but predictable"),
    "Slash":               ("wide, sweeping attacks aimed at creating openings",
                            "prefers to control spacing and cut on the draw"),
    "Strike":              ("direct, efficient — picks moments carefully and commits to clean hits",
                            "sound fundamental technique, not flashy but effective"),
    "Engage & Withdraw":   ("mobile and evasive, drawing attacks and stepping out",
                            "fighting for positioning, frustrating opponents who need to close"),
    "Counterstrike":       ("patient, waiting for the opponent to open up before answering",
                            "looks to punish mistakes — dangerous when the opponent is aggressive"),
    "Decoy":               ("unpredictable movement designed to trick the opponent's eyes",
                            "using feints and misdirection to create the appearance of openings"),
    "Sure Strike":         ("deliberate and measured, choosing quality over quantity",
                            "fewer attacks but each one placed with care — reads the fight well"),
    "Calculated Attack":   ("methodical and tactical, managing the fight like a chess match",
                            "intelligent fighter — conserves energy and looks for efficient paths to victory"),
    "Opportunity Throw":   ("ranged or thrown weapons kept in reserve for the right moment",
                            "creating separation and capitalising on the opponent's advances"),
    "Martial Combat":      ("empty-hand and close-range grappling mixed with weapon work",
                            "comfortable at every range — dangerous inside reach"),
    "Parry":               ("technical defence first, attacking only from a position of safety",
                            "hard to hurt — will outlast aggressive opponents if given time"),
    "Defend":              ("fortress posture, absorbing everything and wearing the opponent down",
                            "almost entirely reactive — your warriors need patience and endurance to crack this"),
}

# ---------------------------------------------------------------------------
# AIM POINT OBSERVATIONS
# ---------------------------------------------------------------------------

_AIM_OBSERVATIONS = {
    "Head":          "concentrating attacks on the head — high-risk but potentially fight-ending",
    "Chest":         "targeting the body, seeking to sap endurance and wind",
    "Abdomen":       "aiming low, working the gut to slow and weaken",
    "Primary Arm":   "attacking the weapon arm — looking to disarm or cripple",
    "Secondary Arm": "working the off-arm — possibly looking to disable the shield",
    "Primary Leg":   "going for the lead leg — trying to hamper mobility",
    "Secondary Leg": "targeting the rear leg — unusual and potentially destabilising",
    "None":          "not committing to a fixed target — opportunistic placement",
}

# ---------------------------------------------------------------------------
# ACTIVITY LEVEL OBSERVATIONS
# ---------------------------------------------------------------------------

def _activity_desc(activity: int) -> str:
    if activity >= 9:
        return "extremely high — practically non-stop attack, burning energy fast"
    if activity >= 7:
        return "high — very active, keeping constant pressure on the opponent"
    if activity >= 5:
        return "moderate — balanced pace, not over-committing"
    if activity >= 3:
        return "low — deliberate and measured, picking moments"
    return "minimal — highly passive, fighting almost entirely on the counter"


# ---------------------------------------------------------------------------
# WEAPON ASSESSMENT
# ---------------------------------------------------------------------------

_WEAPON_NOTES = {
    "Great Axe":     "heavy two-handed axe — requires significant strength; powerful but slow on recovery",
    "Great Sword":   "two-handed sword — long reach, punishing swings; needs room to operate",
    "Battle Axe":    "single-handed axe — solid stopping power with decent speed",
    "War Flail":     "war flail — unpredictable arc, hard to parry; skilled handling needed",
    "Morningstar":   "morningstar — medium weight with solid impact; versatile all-round",
    "Short Sword":   "short sword — fast and precise; excellent in close quarters",
    "Boar Spear":    "boar spear — reach advantage; effective against advancing opponents",
    "Longsword":     "longsword — well-balanced reach and speed; adaptable",
    "Battle Flail":  "battle flail — awkward angles that confound standard defences",
    "Bastard Sword": "bastard sword — can be wielded one- or two-handed; flexible",
    "Broad Sword":   "broad sword — dependable middle-weight blade",
    "Scimitar":      "scimitar — curved blade favours slashing; quick draw",
    "Mace":          "mace — effective against armoured opponents; blunt force",
    "War Hammer":    "war hammer — devastating on armour; slow but crushing",
    "Great Pick":    "great pick — armour-piercing tip; punishing on connection",
    "Halberd":       "halberd — pole weapon with axe and hook; range and versatility",
    "Pole Axe":      "pole axe — heavy reach weapon; difficult to get inside",
    "Quarterstaff":  "quarterstaff — two-ended reach; uncommon but effective",
    "Dagger":        "dagger — very fast, close-range weapon; dangerous in a clinch",
    "Open Hand":     "fighting unarmed — either philosophical choice or desperation",
}


def _weapon_note(weapon: str) -> str:
    return _WEAPON_NOTES.get(weapon, f"{weapon} — observe carefully how they handle the draw and footwork")


# ---------------------------------------------------------------------------
# ARMOUR ASSESSMENT
# ---------------------------------------------------------------------------

_ARMOUR_NOTES = {
    "Full Plate":   "full plate armour — heavily protected; will absorb punishment but movement is restricted",
    "Chain":        "chain mail — good coverage without severe mobility cost; mid-tier protection",
    "Brigandine":   "brigandine — riveted plates over leather; solid balance of protection and movement",
    "Cuir Boulli":  "hardened leather — lighter protection; favours a mobile fighter",
    "Leather":      "soft leather — minimal protection; this warrior is betting on not being hit",
    "None":         "unarmoured — either supreme confidence in their defence, or a deliberate speed advantage",
}


def _armour_note(armour: str) -> str:
    return _ARMOUR_NOTES.get(armour, f"{armour} — standard protection")


# ---------------------------------------------------------------------------
# OUTCOME COMMENTARY
# ---------------------------------------------------------------------------

def _outcome_paragraph(result: str, opponent_name: str, opponent_race: str,
                        minutes: int, slew_opponent: bool, warrior_name: str) -> str:
    won = result == "win"
    if slew_opponent:
        lines = [
            f"{warrior_name} won decisively and {opponent_name} did not survive the bout.",
            f"The fight ended with {opponent_name} dead in the sand — {warrior_name} showed no hesitation at the kill.",
            f"{warrior_name} dispatched {opponent_name} permanently. The crowd reacted strongly.",
        ]
    elif won:
        if minutes <= 2:
            lines = [
                f"A convincing and rapid victory over {opponent_name} ({opponent_race}) in just {minutes} minute(s). The outcome was rarely in doubt.",
                f"{warrior_name} dominated {opponent_name} quickly. Short, sharp, and clinical.",
                f"Over in {minutes} minute(s). {opponent_name} had little answer for what was thrown at them.",
            ]
        elif minutes >= 8:
            lines = [
                f"A hard-fought win over {opponent_name} ({opponent_race}) after {minutes} gruelling minutes. Both fighters were tested.",
                f"Victory came, but it took {minutes} minutes and cost some wear. {opponent_name} was a credible opponent.",
                f"{warrior_name} edged {opponent_name} in a long, draining {minutes}-minute contest. Stamina will matter if this warrior fights often.",
            ]
        else:
            lines = [
                f"Solid win over {opponent_name} ({opponent_race}) in {minutes} minutes. No major surprises.",
                f"A competent performance against {opponent_name}. Won without too much drama in {minutes} minutes.",
                f"{warrior_name} handled {opponent_name} efficiently. {minutes} minutes, clean result.",
            ]
    else:
        if minutes <= 2:
            lines = [
                f"Lost to {opponent_name} ({opponent_race}) very quickly — {minutes} minute(s). Something went badly wrong early.",
                f"A fast and brutal defeat at the hands of {opponent_name}. {minutes} minutes is not long enough to show much.",
                f"Overwhelmed quickly by {opponent_name}. Short fight, bad result.",
            ]
        elif minutes >= 8:
            lines = [
                f"A losing effort against {opponent_name} ({opponent_race}), but the fight lasted {minutes} minutes — this warrior is hard to put down.",
                f"Went {minutes} minutes before falling to {opponent_name}. Not a disgrace — showed heart.",
                f"Lost, but made {opponent_name} work for it over {minutes} minutes. Resilience noted.",
            ]
        else:
            lines = [
                f"Defeated by {opponent_name} ({opponent_race}) in {minutes} minutes. A setback, but not a catastrophe.",
                f"Came up short against {opponent_name}. {minutes} minutes — fought but couldn't close.",
                f"Loss to {opponent_name}. {minutes} minutes of work for nothing. Worth reviewing what went wrong.",
            ]
    return random.choice(lines)


# ---------------------------------------------------------------------------
# THREAT ASSESSMENT
# ---------------------------------------------------------------------------

def _threat_assessment(w, won: bool, minutes: int, slew: bool) -> str:
    """
    Produce a short tactical advisory for the manager receiving this report.
    Deliberately vague — the scout infers, not measures.
    """
    rec = getattr(w, "recognition", 0)
    tf  = getattr(w, "total_fights", 0)

    threat_lines = []

    # Overall threat tier
    if rec >= 60 or (tf >= 20 and won and minutes <= 3):
        threat_lines.append("THREAT LEVEL: HIGH — do not underestimate this warrior. Recommend avoiding unless you have a specific counter-plan.")
    elif rec >= 30 or tf >= 10:
        threat_lines.append("THREAT LEVEL: MODERATE — a capable opponent. Approach with preparation.")
    else:
        threat_lines.append("THREAT LEVEL: LOW-MODERATE — still developing. A well-prepared warrior should have the edge.")

    # Style-specific advice
    strats = getattr(w, "strategies", [])
    if strats:
        s = strats[0]
        style = getattr(s, "style", "Strike")
        act   = getattr(s, "activity", 5)
        if style in ("Total Kill", "Wall of Steel", "Lunge", "Bash"):
            threat_lines.append("Advisory: This fighter is aggressive. A patient, defensive style with strong parry or dodge may blunt their attack.")
        elif style in ("Parry", "Defend", "Counterstrike"):
            threat_lines.append("Advisory: This fighter is reactive. Pressure and high activity may exhaust them — do not let them dictate the pace.")
        elif style in ("Engage & Withdraw", "Decoy"):
            threat_lines.append("Advisory: This fighter uses mobility. Warriors with strong initiative or reach weapons may deny their footwork.")
        if act >= 8:
            threat_lines.append("Note: Extremely high activity observed — they may tire in a long fight. Consider a durable, endurance-focused warrior.")
        elif act <= 2:
            threat_lines.append("Note: Very low activity — passive and reactive. High-pressure, mobile warriors could expose this.")

    # Weapon advisory
    weapon = getattr(w, "primary_weapon", "")
    if weapon in ("Great Axe", "Great Sword", "Halberd", "Pole Axe", "Maul"):
        threat_lines.append("Weapon note: Heavy two-handed reach weapon. Do not close slowly — either stay at range or burst inside fast.")
    elif weapon in ("Short Sword", "Dagger", "Cestus"):
        threat_lines.append("Weapon note: Short-range weapon. Fighters with reach advantage can keep this warrior at a disadvantage.")

    return "  ".join(threat_lines)


# ---------------------------------------------------------------------------
# MAIN GENERATOR
# ---------------------------------------------------------------------------

def _wattr(warrior, attr, default=None):
    """Safely read an attribute from a Warrior object or a plain dict."""
    if isinstance(warrior, dict):
        return warrior.get(attr, default)
    return getattr(warrior, attr, default)


def generate_scout_report(warrior, last_fight_entry: dict, team_name: str) -> str:
    """
    Generate a written in-character scout's field report for the given warrior.

    warrior          — Warrior object (or dict)
    last_fight_entry — fight_history entry dict (or None if no fights yet)
    team_name        — team name string
    """
    scout  = random.choice(_SCOUT_NAMES)
    title  = random.choice(_SCOUT_TITLES)
    wname  = _wattr(warrior, "name", "Unknown")
    _race  = _wattr(warrior, "race", "Unknown")
    race   = (_race.name if hasattr(_race, "name") else str(_race))
    gender = _wattr(warrior, "gender", "Unknown")
    tf     = _wattr(warrior, "total_fights", 0) or 0
    wins   = _wattr(warrior, "wins", 0) or 0
    losses = _wattr(warrior, "losses", 0) or 0
    kills  = _wattr(warrior, "kills", 0) or 0
    weapon = _wattr(warrior, "primary_weapon", "Unknown") or "Unknown"
    armor  = _wattr(warrior, "armor", "") or "None"
    strats = _wattr(warrior, "strategies", [])

    lines = []

    # ── Header ──────────────────────────────────────────────────────────────
    lines.append(f"SCOUT FIELD REPORT")
    lines.append(f"Subject: {wname}  |  {team_name}")
    lines.append(f"Filed by: {scout}, {title}")
    lines.append(f"Record at time of observation: {wins}-{losses}-{kills} ({tf} fights)")
    lines.append("")

    if not last_fight_entry:
        lines.append("OBSERVATION")
        lines.append("-" * 60)
        lines.append(f"I was sent to observe {wname} but this warrior has not yet fought.")
        lines.append("No tactical assessment is possible. Check back next turn.")
        return "\n".join(lines)

    opp_name  = last_fight_entry.get("opponent_name", "Unknown")
    opp_race  = last_fight_entry.get("opponent_race", "Unknown")
    result    = last_fight_entry.get("result", "loss")
    minutes   = last_fight_entry.get("minutes", 5)
    slew_opp  = last_fight_entry.get("opponent_slain", False)
    was_slain = last_fight_entry.get("warrior_slain", False)

    # ── Opening: the fight ──────────────────────────────────────────────────
    lines.append("FIGHT OBSERVED")
    lines.append("-" * 60)
    lines.append(_outcome_paragraph(result, opp_name, opp_race, minutes, slew_opp, wname))
    lines.append("")

    # ── Style assessment ────────────────────────────────────────────────────
    lines.append("FIGHTING STYLE ASSESSMENT")
    lines.append("-" * 60)

    if strats:
        s     = strats[0]
        style = getattr(s, "style", "Strike")
        act   = getattr(s, "activity", 5)
        aim   = getattr(s, "aim_point", "None")

        style_desc, style_note = _STYLE_DESCRIPTIONS.get(
            style, ("a style I could not immediately categorise", "unusual — worth watching again"))

        lines.append(f"Primary style observed: {style}")
        lines.append(f"  {wname} fought in a manner I would describe as {style_desc}.")
        lines.append(f"  My assessment: {style_note}.")
        lines.append("")
        lines.append(f"Activity level: {_activity_desc(act)}")
        lines.append(f"Targeting preference: {_AIM_OBSERVATIONS.get(aim, 'no clear pattern noted')}")
    else:
        lines.append(f"I was unable to pin down a clear pattern in {wname}'s approach.")
        lines.append("Either this warrior adapts to circumstances or my vantage point was poor.")
    lines.append("")

    # ── Weapon and armour notes ─────────────────────────────────────────────
    lines.append("EQUIPMENT NOTES")
    lines.append("-" * 60)
    lines.append(f"Primary weapon: {_weapon_note(weapon)}")
    lines.append(f"Armour: {_armour_note(armor)}")
    lines.append("")

    # ── Observed skills ─────────────────────────────────────────────────────
    skills = _wattr(warrior, "skills", {}) or {}
    notable_skills = [(sk, lvl) for sk, lvl in skills.items() if lvl >= 3]
    notable_skills.sort(key=lambda x: -x[1])

    if notable_skills:
        lines.append("SKILLS OBSERVED IN ACTION")
        lines.append("-" * 60)
        from warrior import SKILL_LEVEL_NAMES
        for sk, lvl in notable_skills[:4]:
            sk_display = sk.replace("_", " ").title()
            lvl_name   = SKILL_LEVEL_NAMES.get(lvl, f"Level {lvl}")
            _SKILL_CONTEXT = {
                "dodge":      "moves off the line smoothly — harder to hit than their armour suggests",
                "parry":      "technically sound deflections — not easy to land clean",
                "initiative": "gets into position quickly — don't let them set the pace",
                "lunge":      "commits to reaching attacks — watch the overextension",
                "feint":      "uses deceptive attacks to open guards — don't react to the first move",
                "brawl":      "comfortable in a clinch — keep this warrior at arm's length",
                "sweep":      "going for the legs — warriors with strong footing fare better",
                "charge":     "explosive forward movement — give ground early or risk being bowled over",
                "disarm":     "actively working to strip the weapon — keep the grip tight",
                "throw":      "may open with a ranged attack — close ground fast or maintain distance",
            }
            context = _SKILL_CONTEXT.get(sk, "competent enough to be worth noting")
            lines.append(f"  {sk_display} ({lvl_name}): {context}.")
        lines.append("")

    # ── Overall threat and recommendation ───────────────────────────────────
    lines.append("TACTICAL RECOMMENDATION")
    lines.append("-" * 60)
    won = result == "win"
    lines.append(_threat_assessment(warrior, won, minutes, slew_opp))
    lines.append("")

    # ── Closing remark ───────────────────────────────────────────────────────
    _closers = [
        f"That is my full account of {wname}. Use it wisely — or don't. I get paid either way.",
        f"Report complete. {wname} is worth taking seriously. I have seen worse and I have seen better.",
        f"I would not face {wname} unprepared. You now have more than most managers will bother to gather.",
        f"That is all I observed. If you need more detail, send me again next turn.",
        f"My work here is done. The rest is up to your warriors.",
    ]
    lines.append(f"— {scout}")
    lines.append(random.choice(_closers))

    return "\n".join(lines)
