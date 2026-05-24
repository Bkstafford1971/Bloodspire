# =============================================================================
# scout_report.py - In-character scout report generator
# =============================================================================
# Each manager has a permanent scout with a personality type.
# The core facts are the same across reports, but the voice differs per scout.
# Soft assessments (style, activity, aim, skills) carry an error rate -
# the scout can be wrong, and the report never signals the uncertainty.
# =============================================================================
import random

# ---------------------------------------------------------------------------
# PERSONA DEFINITIONS
# ---------------------------------------------------------------------------

# 4 scout personality types. Each has distinct names, titles, prose voice,
# and error rates on soft assessments.

PERSONA_TYPES = ("veteran", "academic", "street", "rookie")

_PERSONA_NAMES = {
    "veteran":  ["Old Corwin", "Aldric Fenbourne", "Gorst the Watcher",
                 "Thane Duskhollow", "Sable Rennwick", "Maren Coldthorn"],
    "academic": ["Dex Ironquill", "Nessa Vane", "Bryndis Marsh",
                 "Hadwin Callowell", "Petra Ashwick", "Silas Dunmore"],
    "street":   ["Mira Coldtongue", "Spit Brecken", "Rat Voss",
                 "Brix Nails", "Dagger Moll", "Two-Cups Fenwick"],
    "rookie":   ["Pip Ashford", "Tam Wrenley", "Corbet Hale",
                 "Senna Misk", "Rue Gravel", "Jem Bassett"],
}

_PERSONA_TITLES = {
    "veteran":  ["Senior Arena Scout", "Field Observer (Ret.)", "Pit Assessor",
                 "Veteran Field Scout"],
    "academic": ["Intelligence Analyst", "Tactical Assessor", "Pit Correspondent",
                 "Arena Research Division"],
    "street":   ["Freelance Eyes", "Hired Informant", "Pit Watcher",
                 "Stable Informant"],
    "rookie":   ["Junior Scout", "Field Trainee", "Scout's Apprentice",
                 "Probationary Observer"],
}

_PERSONA_HEADER = {
    "veteran":  "FIELD REPORT",
    "academic": "INTELLIGENCE ASSESSMENT",
    "street":   "WORD FROM THE PIT",
    "rookie":   "SCOUTING REPORT",
}

# Error rates: probability that each soft field is reported incorrectly.
_ERROR_RATES = {
    "veteran":  {"style": 0.10, "activity": 0.12, "aim": 0.10, "skills": 0.18},
    "academic": {"style": 0.10, "activity": 0.10, "aim": 0.08, "skills": 0.15},
    "street":   {"style": 0.22, "activity": 0.26, "aim": 0.20, "skills": 0.32},
    "rookie":   {"style": 0.28, "activity": 0.32, "aim": 0.26, "skills": 0.38},
}

def random_persona_name(persona_type: str) -> str:
    return random.choice(_PERSONA_NAMES.get(persona_type, _PERSONA_NAMES["veteran"]))


# ---------------------------------------------------------------------------
# STYLE DATA
# ---------------------------------------------------------------------------

# Core style descriptions - used by all personas (they observe the same thing,
# just describe it differently).
_STYLE_DESCRIPTIONS = {
    "Total Kill":          ("aggressive and reckless, throwing everything into each attack with no thought for personal safety",
                            "dangerous berserker streak - fights to end things fast, never defensive"),
    "Wall of Steel":       ("relentlessly offensive, raining blows without pause",
                            "overwhelming volume of attacks - may tire, but keeps the opponent on the back foot"),
    "Lunge":               ("committed, reaching attacks that sacrifice position for reach",
                            "willing to overextend for the kill blow - watch for a counter"),
    "Bash":                ("heavy and brutal, seeking to power through defences with raw force",
                            "relying on strength over technique - punishing but predictable"),
    "Slash":               ("wide, sweeping attacks aimed at creating openings",
                            "prefers to control spacing and cut on the draw"),
    "Strike":              ("direct, efficient - picks moments carefully and commits to clean hits",
                            "sound fundamental technique, not flashy but effective"),
    "Engage & Withdraw":   ("mobile and evasive, drawing attacks and stepping out",
                            "fighting for positioning, frustrating opponents who need to close"),
    "Counterstrike":       ("patient, waiting for the opponent to open up before answering",
                            "looks to punish mistakes - dangerous when the opponent is aggressive"),
    "Decoy":               ("unpredictable movement designed to trick the opponent's eyes",
                            "using feints and misdirection to create the appearance of openings"),
    "Sure Strike":         ("deliberate and measured, choosing quality over quantity",
                            "fewer attacks but each one placed with care - reads the fight well"),
    "Calculated Attack":   ("methodical and tactical, managing the fight like a chess match",
                            "intelligent fighter - conserves energy and looks for efficient paths to victory"),
    "Opportunity Throw":   ("ranged or thrown weapons kept in reserve for the right moment",
                            "creating separation and capitalising on the opponent's advances"),
    "Martial Combat":      ("empty-hand and close-range grappling mixed with weapon work",
                            "comfortable at every range - dangerous inside reach"),
    "Parry":               ("technical defence first, attacking only from a position of safety",
                            "hard to hurt - will outlast aggressive opponents if given time"),
    "Defend":              ("fortress posture, absorbing everything and wearing the opponent down",
                            "almost entirely reactive - your warriors need patience and endurance to crack this"),
}

# Which styles a scout might misidentify as which. Similar styles confused together.
_STYLE_MISREADS = {
    "Total Kill":        ["Wall of Steel", "Bash", "Lunge"],
    "Wall of Steel":     ["Total Kill", "Bash", "Lunge"],
    "Lunge":             ["Strike", "Total Kill", "Bash"],
    "Bash":              ["Total Kill", "Wall of Steel", "Lunge"],
    "Slash":             ["Strike", "Lunge", "Engage & Withdraw"],
    "Strike":            ["Slash", "Sure Strike", "Calculated Attack"],
    "Engage & Withdraw": ["Decoy", "Counterstrike", "Strike"],
    "Counterstrike":     ["Parry", "Defend", "Engage & Withdraw"],
    "Decoy":             ["Engage & Withdraw", "Counterstrike", "Strike"],
    "Sure Strike":       ["Strike", "Calculated Attack", "Counterstrike"],
    "Calculated Attack": ["Sure Strike", "Counterstrike", "Strike"],
    "Opportunity Throw": ["Engage & Withdraw", "Strike", "Sure Strike"],
    "Martial Combat":    ["Strike", "Bash", "Lunge"],
    "Parry":             ["Defend", "Counterstrike", "Wall of Steel"],
    "Defend":            ["Parry", "Counterstrike", "Wall of Steel"],
}

_ALL_AIM_POINTS = [
    "Head", "Chest", "Abdomen", "Primary Arm",
    "Secondary Arm", "Primary Leg", "Secondary Leg", "None",
]

_AIM_OBSERVATIONS = {
    "Head":          "concentrating attacks on the head - high-risk but potentially fight-ending",
    "Chest":         "targeting the body, seeking to sap endurance and wind",
    "Abdomen":       "aiming low, working the gut to slow and weaken",
    "Primary Arm":   "attacking the weapon arm - looking to disarm or cripple",
    "Secondary Arm": "working the off-arm - possibly looking to disable the shield",
    "Primary Leg":   "going for the lead leg - trying to hamper mobility",
    "Secondary Leg": "targeting the rear leg - unusual and potentially destabilising",
    "None":          "not committing to a fixed target - opportunistic placement",
}

_WEAPON_NOTES = {
    "Great Axe":     "heavy two-handed axe - requires significant strength; powerful but slow on recovery",
    "Great Sword":   "two-handed sword - long reach, punishing swings; needs room to operate",
    "Battle Axe":    "single-handed axe - solid stopping power with decent speed",
    "War Flail":     "war flail - unpredictable arc, hard to parry; skilled handling needed",
    "Morningstar":   "morningstar - medium weight with solid impact; versatile all-round",
    "Short Sword":   "short sword - fast and precise; excellent in close quarters",
    "Boar Spear":    "boar spear - reach advantage; effective against advancing opponents",
    "Longsword":     "longsword - well-balanced reach and speed; adaptable",
    "Battle Flail":  "battle flail - awkward angles that confound standard defences",
    "Bastard Sword": "bastard sword - can be wielded one- or two-handed; flexible",
    "Broad Sword":   "broad sword - dependable middle-weight blade",
    "Scimitar":      "scimitar - curved blade favours slashing; quick draw",
    "Mace":          "mace - effective against armoured opponents; blunt force",
    "War Hammer":    "war hammer - devastating on armour; slow but crushing",
    "Great Pick":    "great pick - armour-piercing tip; punishing on connection",
    "Halberd":       "halberd - pole weapon with axe and hook; range and versatility",
    "Pole Axe":      "pole axe - heavy reach weapon; difficult to get inside",
    "Quarterstaff":  "quarterstaff - two-ended reach; uncommon but effective",
    "Dagger":        "dagger - very fast, close-range weapon; dangerous in a clinch",
    "Open Hand":     "fighting unarmed - either philosophical choice or desperation",
}

_ARMOUR_NOTES = {
    "Full Plate":  "full plate armour - heavily protected; will absorb punishment but movement is restricted",
    "Chain":       "chain mail - good coverage without severe mobility cost; mid-tier protection",
    "Brigandine":  "brigandine - riveted plates over leather; solid balance of protection and movement",
    "Cuir Boulli": "hardened leather - lighter protection; favours a mobile fighter",
    "Leather":     "soft leather - minimal protection; this warrior is betting on not being hit",
    "None":        "unarmoured - either supreme confidence in their defence, or a deliberate speed advantage",
}

_SKILL_CONTEXT = {
    "dodge":      "moves off the line smoothly - harder to hit than their armour suggests",
    "parry":      "technically sound deflections - not easy to land clean",
    "initiative": "gets into position quickly - don't let them set the pace",
    "lunge":      "commits to reaching attacks - watch the overextension",
    "feint":      "uses deceptive attacks to open guards - don't react to the first move",
    "brawl":      "comfortable in a clinch - keep this warrior at arm's length",
    "sweep":      "going for the legs - warriors with strong footing fare better",
    "charge":     "explosive forward movement - give ground early or risk being bowled over",
    "disarm":     "actively working to strip the weapon - keep the grip tight",
    "throw":      "may open with a ranged attack - close ground fast or maintain distance",
}


# ---------------------------------------------------------------------------
# ERROR INJECTION
# ---------------------------------------------------------------------------

def _apply_style_error(style: str, error_rate: float) -> str:
    if random.random() < error_rate:
        alts = _STYLE_MISREADS.get(style, [])
        if alts:
            return random.choice(alts)
    return style


def _apply_activity_error(activity: int, error_rate: float) -> int:
    if random.random() < error_rate:
        offset = random.choice([-2, -1, 1, 2])
        return max(1, min(10, activity + offset))
    return activity


def _apply_aim_error(aim: str, error_rate: float) -> str:
    if random.random() < error_rate:
        alts = [a for a in _ALL_AIM_POINTS if a != aim]
        return random.choice(alts)
    return aim


def _apply_skills_error(notable_skills: list, all_skills: dict, error_rate: float) -> list:
    """
    Potentially corrupt the skill list:
    - Each skill has a chance to have its level reported off by 1
    - One skill may be swapped out for a different one the warrior also has
    """
    result = []
    for sk, lvl in notable_skills:
        if random.random() < error_rate:
            # Report level wrong by 1
            wrong_lvl = max(1, min(9, lvl + random.choice([-1, 1])))
            result.append((sk, wrong_lvl))
        else:
            result.append((sk, lvl))

    # Chance to swap one entry for a completely different skill
    if result and random.random() < error_rate:
        swap_idx = random.randrange(len(result))
        # Find a skill not already in the list that the warrior has at level 1-2
        reported_names = {sk for sk, _ in result}
        swap_candidates = [(sk, lvl) for sk, lvl in all_skills.items()
                           if sk not in reported_names and 1 <= lvl <= 2]
        if swap_candidates:
            result[swap_idx] = random.choice(swap_candidates)

    return result


# ---------------------------------------------------------------------------
# ACTIVITY LEVEL DESCRIPTIONS - per persona
# ---------------------------------------------------------------------------

def _activity_desc(activity: int, persona: str) -> str:
    if persona == "veteran":
        if activity >= 9: return "extremely high - practically non-stop; burning through their reserves fast"
        if activity >= 7: return "high - constant pressure, not giving the opponent room to breathe"
        if activity >= 5: return "moderate - balanced, not over-committing"
        if activity >= 3: return "low - deliberate, picking moments"
        return "minimal - almost entirely counter-fighting"

    elif persona == "academic":
        if activity >= 9: return "extreme (9-10 range) - unsustainable output rate; endurance will be the limiting factor"
        if activity >= 7: return "elevated (7-8 range) - consistent offensive pressure throughout the bout"
        if activity >= 5: return "moderate (5-6 range) - measured engagement cadence"
        if activity >= 3: return "reduced (3-4 range) - controlled tempo, selective engagement"
        return "minimal (1-2 range) - almost entirely reactive posture"

    elif persona == "street":
        if activity >= 9: return "through the roof - this one never stops swinging, burns out or wins fast"
        if activity >= 7: return "busy, very busy - keeping the other fighter on the back foot the whole time"
        if activity >= 5: return "steady - not going crazy, not sitting back either"
        if activity >= 3: return "slow burn - waits for the right moment"
        return "barely moving - practically daring the other fighter to come to them"

    else:  # rookie
        if activity >= 9: return "incredibly high! This warrior attacked almost constantly the whole fight!"
        if activity >= 7: return "really high - lots of attacking, very aggressive"
        if activity >= 5: return "moderate - a mix of attacking and waiting"
        if activity >= 3: return "fairly low - not attacking much"
        return "very low - I honestly wasn't sure they were awake at some points"


# ---------------------------------------------------------------------------
# OUTCOME PARAGRAPHS - per persona
# ---------------------------------------------------------------------------

def _outcome_paragraph(result: str, opp_name: str, opp_race: str,
                        minutes: int, slew_opp: bool, wname: str, persona: str) -> str:
    won = result == "win"

    if persona == "veteran":
        if slew_opp:
            return random.choice([
                f"{wname} put {opp_name} down for good. No hesitation at the end. That counts for something.",
                f"Decisive. {opp_name} is dead and {wname} walked out. Nothing more to say.",
                f"Fought {opp_name} and finished them. The crowd remembered it. So did I.",
            ])
        elif won:
            if minutes <= 2:
                return random.choice([
                    f"Quick work. {wname} dealt with {opp_name} in {minutes} minute(s) and barely raised a sweat.",
                    f"Over fast. {opp_name} didn't have an answer for what was thrown at them. {minutes} minute(s).",
                    f"Clean and efficient. {minutes} minute(s) against {opp_name}. Minimal fuss.",
                ])
            elif minutes >= 8:
                return random.choice([
                    f"Long fight. {minutes} minutes against {opp_name} ({opp_race}). Won, but it cost something.",
                    f"Took {minutes} minutes to get past {opp_name}. This warrior knows how to endure.",
                    f"Hard {minutes}-minute grind against {opp_name}. Victory, but not without wear.",
                ])
            else:
                return random.choice([
                    f"Solid win over {opp_name} ({opp_race}) in {minutes} minutes. Nothing unexpected.",
                    f"Handled {opp_name} in {minutes} minutes. Competent, no dramatics.",
                    f"{wname} beat {opp_name}. {minutes} minutes. Job done.",
                ])
        else:
            if minutes <= 2:
                return random.choice([
                    f"Bad day. Gone in {minutes} minute(s) against {opp_name}. Not much to work with here.",
                    f"Lost fast. {opp_name} was on them before they found their footing. {minutes} minute(s).",
                    f"Short and ugly. {opp_name} finished it in {minutes} minute(s).",
                ])
            elif minutes >= 8:
                return random.choice([
                    f"Lost to {opp_name} but lasted {minutes} minutes. This one doesn't fold easy.",
                    f"Went {minutes} minutes with {opp_name} ({opp_race}) before going down. Worth something.",
                    f"Defeat, but a long one. {minutes} minutes against {opp_name}. Resilience noted.",
                ])
            else:
                return random.choice([
                    f"Lost to {opp_name} ({opp_race}) in {minutes} minutes. A setback.",
                    f"{minutes} minutes and a loss. {opp_name} had the edge on the day.",
                    f"Came up short against {opp_name}. {minutes} minutes.",
                ])

    elif persona == "academic":
        if slew_opp:
            return random.choice([
                f"Subject achieved a terminal outcome against {opp_name}. The opposing warrior did not survive the engagement. Subject demonstrated no hesitation in applying lethal pressure.",
                f"Engagement concluded with the death of {opp_name} ({opp_race}). Subject's capacity to escalate at the decisive moment is confirmed and should be weighed accordingly.",
                f"Subject terminated the bout decisively. {opp_name} was killed. This represents a significant data point regarding the subject's lethality profile.",
            ])
        elif won:
            if minutes <= 2:
                return random.choice([
                    f"Subject achieved a rapid victory over {opp_name} ({opp_race}), concluding the engagement in {minutes} minute(s). The brevity suggests either significant capability advantage or opponent vulnerability.",
                    f"Outcome: victory in {minutes} minute(s) against {opp_name}. Efficiency of this level warrants attention when projecting performance against higher-tier opposition.",
                    f"Bout concluded in {minutes} minute(s) with subject victorious. {opp_name} offered minimal resistance. Subject's threat ceiling remains to be established.",
                ])
            elif minutes >= 8:
                return random.choice([
                    f"Subject prevailed after {minutes} minutes against {opp_name} ({opp_race}). The extended duration suggests this warrior's endurance characteristics are as relevant as their offensive output.",
                    f"Victory achieved at {minutes} minutes. The prolonged engagement with {opp_name} provides useful data on the subject's durability and sustained performance.",
                    f"A {minutes}-minute contest against {opp_name}, resulting in a win. Note the duration - conditioning and endurance are factors to assess in future projections.",
                ])
            else:
                return random.choice([
                    f"Subject defeated {opp_name} ({opp_race}) in {minutes} minutes. Performance was consistent with observed capability. No significant anomalies noted.",
                    f"Victory in {minutes} minutes against {opp_name}. A competent result. Subject performed within expected parameters.",
                    f"Outcome: win versus {opp_name} in {minutes} minutes. Standard performance, no material deviations from established patterns.",
                ])
        else:
            if minutes <= 2:
                return random.choice([
                    f"Subject was defeated by {opp_name} ({opp_race}) in {minutes} minute(s). The rapid conclusion limits the data available for this assessment.",
                    f"Loss in {minutes} minute(s) to {opp_name}. Insufficient engagement time to draw meaningful tactical conclusions. Further observation recommended.",
                    f"Outcome: defeat in {minutes} minute(s) against {opp_name}. The speed of resolution may indicate a specific vulnerability or an exceptionally capable opponent.",
                ])
            elif minutes >= 8:
                return random.choice([
                    f"Subject was defeated by {opp_name} ({opp_race}) after {minutes} minutes of engagement. The extended duration demonstrates durability despite the adverse outcome.",
                    f"A {minutes}-minute loss to {opp_name}. Subject's capacity to sustain engagement under pressure is confirmed. The outcome should not be weighted as a definitive capability indicator.",
                    f"Loss after {minutes} minutes versus {opp_name}. Subject demonstrated resilience. Assess the specific conditions that led to defeat rather than dismissing outright.",
                ])
            else:
                return random.choice([
                    f"Subject lost to {opp_name} ({opp_race}) in {minutes} minutes. Performance fell short of winning threshold. Root cause analysis is advisable.",
                    f"Defeat in {minutes} minutes against {opp_name}. A moderate-duration loss. This does not rule out future competitive performance.",
                    f"Outcome: loss versus {opp_name} in {minutes} minutes. Noted. Further engagements will clarify whether this reflects a pattern or an isolated result.",
                ])

    elif persona == "street":
        if slew_opp:
            return random.choice([
                f"{wname} didn't just beat {opp_name} - sent them home feet first. Blood's still on the sand from what I saw.",
                f"Watched {opp_name} go down and not get back up. {wname} made sure of it. Crowd went mad.",
                f"Messy finish. {opp_name}'s dead, {wname}'s walking, that's all there is to it.",
            ])
        elif won:
            if minutes <= 2:
                return random.choice([
                    f"Quick and nasty. {wname} had {opp_name} sorted in {minutes} minute(s). Blink and you missed the best of it.",
                    f"Done in {minutes} minute(s). {opp_name} barely had time to get their feet under them.",
                    f"I've seen street fights that lasted longer. {wname} put {opp_name} away fast - {minutes} minute(s). Not pretty but it worked.",
                ])
            elif minutes >= 8:
                return random.choice([
                    f"Long haul. Went {minutes} minutes before {wname} finally got it done against {opp_name}. Both of them looked ragged at the end.",
                    f"{minutes} minutes of back-and-forth with {opp_name}. {wname} got there in the end but it wasn't a walk.",
                    f"Could've gone either way for a while there. {minutes} minutes against {opp_name} ({opp_race}), and {wname} took it.",
                ])
            else:
                return random.choice([
                    f"Solid enough. {wname} beat {opp_name} in {minutes} minutes. No big surprises.",
                    f"Got the job done in {minutes} minutes. {opp_name} tried but {wname} had their number.",
                    f"Won against {opp_name}. {minutes} minutes, nothing too dramatic. I've seen better, I've seen worse.",
                ])
        else:
            if minutes <= 2:
                return random.choice([
                    f"Over before it started, practically. {opp_name} took {wname} apart in {minutes} minute(s). Harsh.",
                    f"Short and not sweet. {wname} caught a bad one off {opp_name} and that was it. {minutes} minute(s).",
                    f"I nearly missed it. {minutes} minute(s), then {wname}'s on the dirt. {opp_name} was something else that day.",
                ])
            elif minutes >= 8:
                return random.choice([
                    f"Went {minutes} minutes with {opp_name} ({opp_race}) before going under. At least they didn't fold quick.",
                    f"Lost to {opp_name} but made them earn it. {minutes} minutes of hard work for nothing, but the guts were there.",
                    f"{minutes} minutes and {wname} still came up short against {opp_name}. Rough. Not a quitter though.",
                ])
            else:
                return random.choice([
                    f"{wname} lost to {opp_name} in {minutes} minutes. Just one of those days, maybe.",
                    f"Got beat by {opp_name}. {minutes} minutes. Happens to everyone.",
                    f"Came second against {opp_name}. {minutes} minutes. Not the result anyone wanted.",
                ])

    else:  # rookie
        if slew_opp:
            return random.choice([
                f"Oh wow. I wasn't expecting that ending. {wname} actually killed {opp_name}! The crowd was incredible.",
                f"I had to look away near the end, honestly. {opp_name} didn't make it. {wname} just didn't stop.",
                f"So {opp_name} is dead. That's... I mean {wname} won, obviously, but I'm still processing what I saw.",
            ])
        elif won:
            if minutes <= 2:
                return random.choice([
                    f"That was so fast! {wname} beat {opp_name} in just {minutes} minute(s). I almost didn't get my notes down in time.",
                    f"Wow, only {minutes} minute(s)! {opp_name} didn't really get a chance to do much.",
                    f"{wname} made that look easy! Won against {opp_name} in {minutes} minute(s). Really impressive!",
                ])
            elif minutes >= 8:
                return random.choice([
                    f"That was a really long fight - {minutes} minutes! But {wname} won in the end against {opp_name}. Really inspiring to watch.",
                    f"I was biting my nails by the end but {wname} did it! Beat {opp_name} ({opp_race}) after {minutes} whole minutes.",
                    f"It went on for {minutes} minutes and I wasn't sure how it would end, but {wname} pulled through against {opp_name}.",
                ])
            else:
                return random.choice([
                    f"Great result! {wname} beat {opp_name} in {minutes} minutes. I thought they did really well.",
                    f"Win! {wname} versus {opp_name}, {minutes} minutes, victory. Pretty good!",
                    f"I'm glad to report a win against {opp_name} in {minutes} minutes. {wname} seemed really in control.",
                ])
        else:
            if minutes <= 2:
                return random.choice([
                    f"Um, it didn't go well. {opp_name} beat {wname} really quickly - only {minutes} minute(s). It was hard to watch.",
                    f"So... {wname} lost in {minutes} minute(s). That's not very long. It happened so fast I'm not sure I caught everything.",
                    f"Bad result unfortunately. {opp_name} won in {minutes} minute(s). I'll try to give you as much as I observed.",
                ])
            elif minutes >= 8:
                return random.choice([
                    f"{wname} lost but they really tried! {minutes} whole minutes against {opp_name} ({opp_race}). They never gave up.",
                    f"It didn't end the way we wanted but {wname} fought for {minutes} minutes which I think shows a lot of heart.",
                    f"Loss after {minutes} minutes against {opp_name}. I thought there were moments where it could have gone differently.",
                ])
            else:
                return random.choice([
                    f"Unfortunately {wname} lost to {opp_name} in {minutes} minutes. I'll note everything I can to help.",
                    f"Didn't win this one. {opp_name} got the better of {wname} in {minutes} minutes. I'm sorry to report it.",
                    f"A loss against {opp_name} in {minutes} minutes. I hope my notes are still useful.",
                ])


# ---------------------------------------------------------------------------
# STYLE SECTION FRAMING - per persona
# ---------------------------------------------------------------------------

def _style_intro(wname: str, style: str, style_desc: str, style_note: str,
                 was_wrong: bool, persona: str) -> list:
    """Return lines for the style assessment paragraph."""
    lines = []
    if persona == "veteran":
        lines.append(f"Style observed: {style}")
        lines.append(f"  {wname} fights in a manner I'd call {style_desc}.")
        lines.append(f"  Assessment: {style_note}.")
    elif persona == "academic":
        lines.append(f"Primary combat methodology: {style}")
        lines.append(f"  Subject demonstrated a pattern consistent with {style_desc}.")
        lines.append(f"  Tactical implication: {style_note}.")
    elif persona == "street":
        lines.append(f"What I saw: {style}")
        lines.append(f"  {wname}'s got a way of fighting that I'd put down as {style_desc}.")
        lines.append(f"  Take note: {style_note}.")
    else:  # rookie
        lines.append(f"Fighting style: {style}")
        lines.append(f"  I think {wname} fights in a way I'd describe as {style_desc}.")
        lines.append(f"  What I took from it: {style_note}.")
    return lines


def _aim_line(aim: str, persona: str) -> str:
    obs = _AIM_OBSERVATIONS.get(aim, "no clear targeting pattern noted")
    if persona == "veteran":
        return f"Target preference: {obs}"
    elif persona == "academic":
        return f"Targeting data: Subject was {obs}"
    elif persona == "street":
        return f"Where they're aiming: {obs}"
    else:
        return f"Targeting: {obs}"


def _activity_line(activity: int, persona: str) -> str:
    desc = _activity_desc(activity, persona)
    if persona == "veteran":
        return f"Activity level: {desc}"
    elif persona == "academic":
        return f"Engagement rate: {desc}"
    elif persona == "street":
        return f"How busy they were: {desc}"
    else:
        return f"Activity level: {desc}"


# ---------------------------------------------------------------------------
# EQUIPMENT - per persona framing
# ---------------------------------------------------------------------------

def _equipment_lines(weapon: str, armor: str, persona: str) -> list:
    wnote = _WEAPON_NOTES.get(weapon, f"{weapon} - observe carefully how they handle the draw and footwork")
    anote = _ARMOUR_NOTES.get(armor, f"{armor} - standard protection")
    if persona == "veteran":
        return [f"Weapon: {wnote}", f"Armour: {anote}"]
    elif persona == "academic":
        return [f"Primary weapon (confirmed): {wnote}", f"Protective equipment: {anote}"]
    elif persona == "street":
        return [f"What they're carrying: {wnote}", f"What's covering them: {anote}"]
    else:
        return [f"Primary weapon: {wnote}", f"Armor: {anote}"]


# ---------------------------------------------------------------------------
# SKILLS SECTION - per persona framing
# ---------------------------------------------------------------------------

def _skills_lines(notable_skills: list, wname: str, persona: str) -> list:
    if not notable_skills:
        return []
    from warrior import SKILL_LEVEL_NAMES
    lines = []
    for sk, lvl in notable_skills[:4]:
        sk_display = sk.replace("_", " ").title()
        lvl_name   = SKILL_LEVEL_NAMES.get(lvl, f"Level {lvl}")
        context    = _SKILL_CONTEXT.get(sk, "competent enough to be worth noting")
        if persona == "veteran":
            lines.append(f"  {sk_display} ({lvl_name}): {context}.")
        elif persona == "academic":
            lines.append(f"  {sk_display} - proficiency level: {lvl_name}. Note: {context}.")
        elif persona == "street":
            lines.append(f"  {sk_display} ({lvl_name}) - {context}.")
        else:
            lines.append(f"  {sk_display}: I'd say {lvl_name}. {context}.")
    return lines


# ---------------------------------------------------------------------------
# THREAT ASSESSMENT - per persona
# ---------------------------------------------------------------------------

def _threat_assessment(warrior, won: bool, minutes: int, slew: bool,
                        style: str, act: int, persona: str) -> str:
    rec = getattr(warrior, "recognition", 0) if not isinstance(warrior, dict) else warrior.get("recognition", 0)
    tf  = getattr(warrior, "total_fights", 0) if not isinstance(warrior, dict) else warrior.get("total_fights", 0)

    # Tier determination (same logic, different words)
    if rec >= 60 or (tf >= 20 and won and minutes <= 3):
        tier = "high"
    elif rec >= 30 or tf >= 10:
        tier = "moderate"
    else:
        tier = "low"

    parts = []

    if persona == "veteran":
        if tier == "high":
            parts.append("THREAT LEVEL: HIGH - do not underestimate this warrior. Have a counter-plan or don't send them.")
        elif tier == "moderate":
            parts.append("THREAT LEVEL: MODERATE - capable opponent. Go in prepared.")
        else:
            parts.append("THREAT LEVEL: LOW-MODERATE - still developing. A prepared warrior should have the edge.")
        if style in ("Total Kill", "Wall of Steel", "Lunge", "Bash"):
            parts.append("Advisory: Aggressive type. Patient defence with solid parry or dodge will blunt this.")
        elif style in ("Parry", "Defend", "Counterstrike"):
            parts.append("Advisory: Reactive fighter. High pressure may grind them down - don't let them dictate pace.")
        elif style in ("Engage & Withdraw", "Decoy"):
            parts.append("Advisory: Uses footwork. Initiative or reach weapons can deny their movement game.")
        if act >= 8:
            parts.append("Note: Very high activity - may tire in a long fight. A durable warrior could outlast them.")
        elif act <= 2:
            parts.append("Note: Passive style. High-pressure fighters can exploit the lack of initiative.")

    elif persona == "academic":
        if tier == "high":
            parts.append("THREAT LEVEL: HIGH - statistical and observational data indicate significant capability. Recommend targeted counter-strategy before engagement.")
        elif tier == "moderate":
            parts.append("THREAT LEVEL: MODERATE - subject presents credible risk. Preparation and style-matching are advisable.")
        else:
            parts.append("THREAT LEVEL: LOW-MODERATE - subject is still in development phase. A well-matched opponent should hold the advantage.")
        if style in ("Total Kill", "Wall of Steel", "Lunge", "Bash"):
            parts.append("Advisory: Subject operates in the aggressive style cluster. Defensive-oriented response strategies (parry, counterstrike, dodge) are statistically favourable.")
        elif style in ("Parry", "Defend", "Counterstrike"):
            parts.append("Advisory: Subject is in the reactive cluster. Sustained offensive pressure with high activity rates is the recommended approach.")
        elif style in ("Engage & Withdraw", "Decoy"):
            parts.append("Advisory: Subject employs mobility-based tactics. Reach weapons or high initiative ratings will limit their effectiveness.")
        if act >= 8:
            parts.append("Note: Engagement rate is very high. Prolonged fights may favour the opponent if subject's endurance is limited.")
        elif act <= 2:
            parts.append("Note: Low engagement rate recorded. High-pressure, mobile opponents may expose the passivity.")

    elif persona == "street":
        if tier == "high":
            parts.append("THREAT LEVEL: HIGH - I'd think twice about sending anyone against this one without a plan. You've been warned.")
        elif tier == "moderate":
            parts.append("THREAT LEVEL: MODERATE - not a walkover. Go in sharp or it'll cost you.")
        else:
            parts.append("THREAT LEVEL: LOW-MODERATE - green enough that a good fighter should manage. Don't get lazy about it though.")
        if style in ("Total Kill", "Wall of Steel", "Lunge", "Bash"):
            parts.append("Take note: All-out aggressor. Your best bet is a patient type who can take a hit and wait for the opening.")
        elif style in ("Parry", "Defend", "Counterstrike"):
            parts.append("Take note: Sits back and waits. Keep the pressure on and don't give them the counter they're fishing for.")
        elif style in ("Engage & Withdraw", "Decoy"):
            parts.append("Take note: Plays the movement game. Someone with reach or fast footwork can shut that down.")
        if act >= 8:
            parts.append("Worth knowing: Goes at it hard the whole time. If your fighter can eat the early storm, they may run out of gas.")
        elif act <= 2:
            parts.append("Worth knowing: Barely throws a punch unless forced. Aggressive, mobile fighters could have a field day.")

    else:  # rookie
        if tier == "high":
            parts.append("THREAT LEVEL: HIGH - I really think this one is dangerous. Please be careful who you send against them!")
        elif tier == "moderate":
            parts.append("THREAT LEVEL: MODERATE - I think they're pretty capable. Worth preparing for.")
        else:
            parts.append("THREAT LEVEL: LOW-MODERATE - they're still fairly new. I think a well-prepared warrior could win.")
        if style in ("Total Kill", "Wall of Steel", "Lunge", "Bash"):
            parts.append("My suggestion: They attack a lot. Maybe someone with good defence who can wait for mistakes?")
        elif style in ("Parry", "Defend", "Counterstrike"):
            parts.append("My suggestion: They mostly wait for the other fighter to attack. I think keeping up the pressure might work.")
        elif style in ("Engage & Withdraw", "Decoy"):
            parts.append("My suggestion: They move around a lot. Maybe a warrior who can keep up with them or has long reach?")
        if act >= 8:
            parts.append("Something I noticed: They attacked constantly! They might get tired if the fight goes long.")
        elif act <= 2:
            parts.append("Something I noticed: They barely attacked at all. Is that normal? I thought aggressive fighters might do well here.")

    weapon = (warrior.get("primary_weapon") if isinstance(warrior, dict)
              else getattr(warrior, "primary_weapon", ""))
    if weapon in ("Great Axe", "Great Sword", "Halberd", "Pole Axe"):
        if persona == "veteran":
            parts.append("Weapon note: Heavy two-handed reach. Get inside fast or stay out entirely.")
        elif persona == "academic":
            parts.append("Weapon note: Two-handed reach weapon. Tactical options: maintain distance, or burst inside the arc.")
        elif persona == "street":
            parts.append("Weapon note: Big slow weapon with reach. Get in close or stay way back, nothing in between.")
        else:
            parts.append("Weapon note: They have a really big weapon! I think you need to get close really fast or stay far away.")
    elif weapon in ("Short Sword", "Dagger"):
        if persona == "veteran":
            parts.append("Weapon note: Short-range. Give them a reach problem.")
        elif persona == "academic":
            parts.append("Weapon note: Close-range weapon. Fighters with reach advantage can maintain effective distance.")
        elif persona == "street":
            parts.append("Weapon note: Short blade - nasty in close but not much good at range. Don't let them get in your pocket.")
        else:
            parts.append("Weapon note: They use a short weapon, so maybe a warrior with a longer weapon has an advantage?")

    return "  ".join(parts)


# ---------------------------------------------------------------------------
# CLOSING REMARKS - per persona
# ---------------------------------------------------------------------------

def _closing_remark(wname: str, scout_name: str, persona: str) -> list:
    if persona == "veteran":
        return [
            f"- {scout_name}",
            random.choice([
                f"That is my full account of {wname}. Use it wisely.",
                f"Report complete. I have seen worse and I have seen better.",
                f"That is all I observed. Send me again next turn if you need more.",
                f"My work here is done. The rest is on your warriors.",
            ])
        ]
    elif persona == "academic":
        return [
            f"- {scout_name}",
            random.choice([
                f"Assessment complete. All observations are subject to the inherent limitations of single-bout analysis.",
                f"This report represents observations from one engagement. Longitudinal data would improve confidence intervals.",
                f"Report filed. Recommend cross-referencing with any available historical performance data.",
                f"Analytical summary complete. Further observation recommended to establish reliable performance baselines.",
            ])
        ]
    elif persona == "street":
        return [
            f"- {scout_name}",
            random.choice([
                f"That's my read on {wname}. Do what you like with it - I got paid already.",
                f"Make of it what you will. I've told you what I saw.",
                f"That's the word from the pit. Use it before someone else does.",
                f"Don't say I never brought you anything. I've seen what I've seen.",
            ])
        ]
    else:  # rookie
        return [
            f"- {scout_name}",
            random.choice([
                f"I hope this report is helpful! I tried my best to observe everything carefully.",
                f"Let me know if you need me to watch them again - I'll pay even closer attention next time!",
                f"I really tried to get everything down. I hope it's useful for your planning.",
                f"This was my best effort. I'm still learning but I think I caught the important parts!",
            ])
        ]


# ---------------------------------------------------------------------------
# UNFOUGHT WARRIOR MESSAGE - per persona
# ---------------------------------------------------------------------------

def _no_fight_message(wname: str, persona: str) -> str:
    if persona == "veteran":
        return (f"Sent to observe {wname}. They have not yet fought. "
                f"No assessment is possible. Check back next turn.")
    elif persona == "academic":
        return (f"Subject: {wname}. No engagement data available for the current period. "
                f"Tactical assessment cannot be completed without combat observation. "
                f"Recommend re-tasking this scout next turn.")
    elif persona == "street":
        return (f"I went, I watched, {wname} never set foot in the pit. "
                f"Can't tell you what I didn't see. Next turn, maybe they'll actually fight.")
    else:
        return (f"I was so ready to observe {wname} but they didn't fight this turn! "
                f"I'm sorry I don't have more to share. I'll watch them next turn if you'd like.")


# ---------------------------------------------------------------------------
# UTILITY
# ---------------------------------------------------------------------------

def _wattr(warrior, attr, default=None):
    if isinstance(warrior, dict):
        return warrior.get(attr, default)
    return getattr(warrior, attr, default)


# ---------------------------------------------------------------------------
# MAIN GENERATOR
# ---------------------------------------------------------------------------

def generate_scout_report(warrior, last_fight_entry: dict, team_name: str,
                           scout_name: str = None, scout_type: str = "veteran") -> str:
    """
    Generate a written in-character scout field report.

    warrior          - Warrior object or dict
    last_fight_entry - fight_history entry dict, or None if no fights yet
    team_name        - team name string
    scout_name       - the manager's assigned scout's name
    scout_type       - persona type: "veteran", "academic", "street", or "rookie"
    """
    persona = scout_type if scout_type in PERSONA_TYPES else "veteran"
    if not scout_name:
        scout_name = random_persona_name(persona)
    title = random.choice(_PERSONA_TITLES.get(persona, _PERSONA_TITLES["veteran"]))
    header_label = _PERSONA_HEADER[persona]

    wname  = _wattr(warrior, "name", "Unknown")
    _race  = _wattr(warrior, "race", "Unknown")
    race   = (_race.name if hasattr(_race, "name") else str(_race))
    tf     = _wattr(warrior, "total_fights", 0) or 0
    wins   = _wattr(warrior, "wins", 0) or 0
    losses = _wattr(warrior, "losses", 0) or 0
    kills  = _wattr(warrior, "kills", 0) or 0
    weapon = _wattr(warrior, "primary_weapon", "Open Hand") or "Open Hand"
    armor  = _wattr(warrior, "armor", "") or "None"
    strats = _wattr(warrior, "strategies", [])

    err = _ERROR_RATES[persona]
    lines = []

    # Header
    lines.append(header_label)
    lines.append(f"Subject: {wname}  |  {team_name}")
    lines.append(f"Filed by: {scout_name}, {title}")
    lines.append(f"Record at time of observation: {wins}-{losses}-{kills} ({tf} fights)")
    lines.append("")

    if not last_fight_entry:
        lines.append("OBSERVATION")
        lines.append("-" * 60)
        lines.append(_no_fight_message(wname, persona))
        return "\n".join(lines)

    opp_name  = last_fight_entry.get("opponent_name", "Unknown")
    opp_race  = last_fight_entry.get("opponent_race", "Unknown")
    result    = last_fight_entry.get("result", "loss")
    minutes   = last_fight_entry.get("minutes", 5)
    slew_opp  = last_fight_entry.get("opponent_slain", False)

    # Fight observed
    lines.append("FIGHT OBSERVED")
    lines.append("-" * 60)
    lines.append(_outcome_paragraph(result, opp_name, opp_race, minutes, slew_opp, wname, persona))
    lines.append("")

    # Style assessment (with possible error injection)
    lines.append("FIGHTING STYLE ASSESSMENT")
    lines.append("-" * 60)

    if strats:
        s = strats[0]
        true_style = getattr(s, "style", "Strike") if not isinstance(s, dict) else s.get("style", "Strike")
        true_act   = getattr(s, "activity", 5)     if not isinstance(s, dict) else s.get("activity", 5)
        true_aim   = getattr(s, "aim_point", "None") if not isinstance(s, dict) else s.get("aim_point", "None")

        # Apply errors to soft assessments
        obs_style = _apply_style_error(true_style, err["style"])
        obs_act   = _apply_activity_error(true_act, err["activity"])
        obs_aim   = _apply_aim_error(true_aim, err["aim"])

        style_desc, style_note = _STYLE_DESCRIPTIONS.get(
            obs_style, ("a style I could not immediately categorise", "unusual - worth watching again"))

        lines.extend(_style_intro(wname, obs_style, style_desc, style_note,
                                   obs_style != true_style, persona))
        lines.append("")
        lines.append(_activity_line(obs_act, persona))
        lines.append(_aim_line(obs_aim, persona))
    else:
        if persona == "veteran":
            lines.append(f"Could not pin down a clear pattern in {wname}'s approach.")
            lines.append("Either this warrior adapts to circumstances or my vantage point was poor.")
        elif persona == "academic":
            lines.append(f"Insufficient data to characterise {wname}'s primary methodology.")
            lines.append("No dominant strategy pattern was identifiable from this observation.")
        elif persona == "street":
            lines.append(f"Honestly? Hard to read. {wname} didn't show a clear hand.")
            lines.append("Either they're mixing it up or I need a better spot next time.")
        else:
            lines.append(f"I wasn't sure what to make of {wname}'s fighting style!")
            lines.append("It seemed hard to pin down. I'll try to figure it out better next time.")
    lines.append("")

    # Equipment (hard facts - always accurate)
    lines.append("EQUIPMENT NOTES")
    lines.append("-" * 60)
    lines.extend(_equipment_lines(weapon, armor, persona))
    lines.append("")

    # Skills (with possible error injection)
    all_skills     = _wattr(warrior, "skills", {}) or {}
    notable_skills = [(sk, lvl) for sk, lvl in all_skills.items() if lvl >= 3]
    notable_skills.sort(key=lambda x: -x[1])

    if notable_skills:
        obs_skills = _apply_skills_error(notable_skills, all_skills, err["skills"])
        skill_lines = _skills_lines(obs_skills, wname, persona)
        if skill_lines:
            if persona == "veteran":
                lines.append("SKILLS OBSERVED IN ACTION")
            elif persona == "academic":
                lines.append("OBSERVED COMPETENCIES")
            elif persona == "street":
                lines.append("WHAT THEY'RE GOOD AT")
            else:
                lines.append("SKILLS I NOTICED")
            lines.append("-" * 60)
            lines.extend(skill_lines)
            lines.append("")

    # Threat assessment
    lines.append("TACTICAL RECOMMENDATION")
    lines.append("-" * 60)
    won = result == "win"
    obs_style_for_threat = obs_style if strats else "Strike"
    obs_act_for_threat   = obs_act  if strats else 5
    lines.append(_threat_assessment(warrior, won, minutes, slew_opp,
                                     obs_style_for_threat, obs_act_for_threat, persona))
    lines.append("")

    # Closing
    lines.extend(_closing_remark(wname, scout_name, persona))

    return "\n".join(lines)
