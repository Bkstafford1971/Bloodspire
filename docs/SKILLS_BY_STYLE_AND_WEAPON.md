# Bloodspire: Which Skills Work Best With Which Styles and Weapons

Date: 2026-10-24
Source: written from the current combat code (`combat.py`, `strategy.py`, `weapons.py`), not from older guides. The weapon table at the end was generated from the code's own weapon lists. Percentages and bonuses are the values in the code today; if balance changes, this guide needs the same update.

---

## 1. Two things that decide almost everything

**A. How a style defends.** Each style defends with either Parry or Dodge, and the matching skill is the one that counts.

| Defends by | Styles |
|---|---|
| **Dodge** | Lunge, Engage & Withdraw, Martial Combat |
| **Parry** | Every other style: Total Kill*, Bash, Strike, Slash, Wall of Steel, Decoy, Opportunity Throw, Counterstrike, Sure Strike, Calculated Attack, Parry, Defend |

A fighter with no weapon in hand (unarmed, or disarmed mid-fight) always dodges.
\*Total Kill replaces defense with a roll divided by three, so Parry, Dodge and Riposte do nothing for a Total Kill fighter while that style is active.

Skills that only fire off a parry (Riposte, Disarm's trigger, Counterstrike's counters) do nothing for the three dodge styles.

**B. Many skills only work with certain weapons or in certain styles.** Training them in the wrong place wastes training sessions. Section 2 lists the conditions.

---

## 2. The 16 non-weapon skills: what they do and where they work

| Skill | What it does | Works in | Works with |
|---|---|---|---|
| **Dodge** | +4 per level on the dodge roll | Any dodge defense (Lunge, Engage & Withdraw, Martial Combat, unarmed or disarmed) | Any weapon |
| **Parry** | +4 per level on the parry roll. Also drives Counterstrike's counter chance (30% + 5% per level) and its chance to read a Decoy feint | Any parry defense | Any weapon |
| **Initiative** | Wins turn order (x3 per level, x4 from level 5) | Every style | Any weapon |
| **Feint** | +2 per level on every attack. Also powers Decoy's pre-attack feint (25% + 5% per level + DEX bonus, max 85%) | Every style (bigger in Decoy) | Any weapon |
| **Lunge** | +3 per level on attacks | **Lunge style only** | The +3 applies with any weapon, but it only makes sense with light thrusting blades and spears (Dagger, Short Sword, Epee, Spears, Javelin). Not worth it with blunt weapons, shields or axes, and weapons of 4.0 lbs or more take a style penalty (except spears and a few others that list Lunge as preferred) |
| **Charge** | +3 per level on attacks and +1/3 damage per level. Against spear-charge weapons it also lowers the defender's parry by 1 per level | Every style | Thrusting blades and spears (Sword/Knife and Polearm/Spear families), shields, and unarmed Martial Combat |
| **Acrobatics** | Dodge +2 per level (Tabaxi +3). Faster recovery from the ground. Removes the extra endurance burn of Lunge and Engage & Withdraw | Dodge styles get all three benefits; every style gets ground recovery | Any weapon |
| **Riposte** | After a strong parry, a counterattack chance of 40% + 5% per level | Parry styles only | Any weapon |
| **Slash** | 5% per level chance for each hit to cause a bleeding wound | Every style | Slash weapons only |
| **Cleave** | 5% per level chance to break through a parry; each break splinters the defender's guard (-3 parry on later parries, up to 4 stacks). Also cuts the defender's riposte chance | Every style | Cleave weapons only |
| **Bash** | 5% per level chance to break through a parry (and +15% of that in Bash style); each break also drains endurance (1% per level) and may knock the defender down (2% per level) | Every style (best in Bash) | Bash weapons only |
| **Disarm** | When a hard attack is parried, 3% + 3% per level (+ weapon bonus) chance to knock the weapon out of the defender's hand | Every style, but only against defenders who parry and don't guard the aimed spot | Any weapon; bonus from Swordbreaker (+10 vs one-handed blades under 5.0 lbs), Epee, Net, Scythe, Heavy Whip, Ball & Chain (+5) |
| **Brawl** | Faster recovery from the ground (any style). In Martial Combat unarmed or with a Martial weapon: +1 per level on attacks and +0.35 per level on damage | Martial Combat for the attack and damage bonus | Open Hand, plus Stiletto, Knife, Dagger, Quarterstaff, Great Staff, Cestus, Net |
| **Strike** | Ignores 4% per level of the target's armor (36% at level 9) | Every style | Strike weapons only (see section 4) |
| **Sweep** | A landed hit may knock the target down: 3% per level with sweeping weapons, 4% per level in Martial Combat. Reduced by target size above 12, halved against Tabaxi | Every style with a sweeping weapon; Martial Combat for the 4% | Spears, Trident, Javelin, Flails, Ball & Chain, Quarterstaff, Great Staff; Martial weapons in Martial Combat |
| **Throw** | +3 per level on attacks and +0.5 per level on damage | **Opportunity Throw only** | Throwable weapons |

Weapon skills (Long Sword, Spear and so on) apply to attack, damage, parry and dodge for whatever weapon you hold, in every style.

---

## 3. Best skills for each style

"Core" means train these first. "Useful" is worth it with the right weapon. "Skip" means the skill does nothing in that style.

### Aggressive styles

**Total Kill** (extreme initiative, no defense while active)
- Core: Initiative, Feint, Charge (if using a thrust weapon, shield or fists).
- Useful: Strike with a piercing weapon (it showed some of the largest gains against Full Plate tanks in earlier tests), Cleave or Bash with a heavy weapon, Slash.
- Caution: with a Military Pick against a Brigandine shield user, Total Kill won only 43% (Calculated Attack won 83%). Giving up all defense is a real cost.
- Skip: Parry, Dodge, Riposte. Ground recovery (Acrobatics, Brawl) still helps.

**Bash** (damage, poor defense)
- Core: Bash skill, Initiative (the style is slow), Parry.
- Useful: Charge when using a shield (Target and Tower Shields are Bash weapons), Sweep with flails or staves, Strike with the Military Pick or Great Pick.
- Skip: Lunge, Slash (unless the weapon is a slash weapon).

**Martial Combat** (fists or Martial weapons; defends by dodge)
- Core: Brawl, Sweep (4% per level here), Dodge, Acrobatics.
- Useful: Charge (adds to unarmed attacks), Initiative, the Open Hand skill itself, or the skill of your Martial weapon.
- Skip: Parry and Riposte (Martial Combat dodges). Strike matters only with a Strike weapon (Stiletto, Dagger).
- Weapons: Open Hand, or Stiletto, Knife, Dagger, Quarterstaff, Great Staff, Cestus, Net while in this style.

**Lunge** (burst attacks, defends by dodge)
- Best weapons: light thrusting blades and spears (Dagger, Short Sword, Epee, Short/Boar/Long Spear, Javelin, Trident). Not recommended for blunt weapons (Club, Mace, Hammer), shields or axes. A Military Pick test showed Lunge was no better than Strike.
- Core: Lunge, Dodge, Acrobatics (removes the style's extra endurance cost), Initiative.
- Useful: Charge with a thrust weapon, Strike with a piercing weapon.
- Skip: Parry and Riposte (this style dodges). Avoid heavy weapons: 4.0 lbs or more take a style penalty.

**Strike (the style)** (average at everything, drains the foe's endurance)
- Core: weapon skill, Parry, Initiative.
- Useful: the Strike skill with a Strike weapon, Charge with a thrust weapon, Riposte, Feint, Cleave or Bash with a heavy weapon.
- This style is not tied to the Strike skill. The skill works in every style.

**Slash** (+8 flat damage on every hit, slow, weak defense)
- Core: Slash skill with a slash weapon (bleeding), Initiative (to offset -6), Parry.
- Useful: Cleave with Scimitar, Battle Axe, Great Axe, Bastard Sword or Scythe.
- Note: the Great Sword gets the style's +8 damage, but it is not a slash weapon, so the Slash skill's bleeding does not apply to it.

### Mid-tier styles

**Wall of Steel** (fast initiative, good parry)
- Core: Initiative, Parry, Riposte.
- Useful: Feint, Strike or Charge with spears and light swords, Disarm.
- Skip: Dodge as a main skill (the style parries). Lunge does nothing here.

**Engage & Withdraw** (very high dodge)
- Core: Dodge, Acrobatics (extra bonus for Tabaxi), Initiative.
- Useful: Charge with a thrust weapon, Strike with a piercing weapon.
- Skip: Riposte and Parry (the style dodges), Lunge (works only in the Lunge style).

**Decoy** (feint first, then attack)
- Core: Feint, Parry, Riposte.
- Useful: Initiative, weapon skill. Beware Counterstrike opponents, who read feints (55% + 3% per Parry level).
- Skip: Lunge.

**Opportunity Throw** (thrown weapons)
- Core: Throw, the thrown weapon's skill, Initiative.
- Useful: Feint, Strike with a thrown spear or javelin.
- Throwable weapons: Stiletto, Knife, Dagger, Hatchet, Hand Axe, Hammer, Short Spear, Boar Spear, Javelin, Bola.

### Counter and passive styles

**Counterstrike** (slow, counters on strong parries)
- Core: Parry (counter chance 30% + 5% per level), Riposte (a second, separate 40% + 5% per level chance), Initiative to offset the -6.
- Useful: Feint. Opponents with Cleave reduce your riposte chance.
- Skip: Dodge, Lunge.

**Sure Strike** (highest hit chance, +15 on attacks, slow)
- Core: weapon skill, Parry, Initiative.
- Useful: Feint, Riposte, Strike.

**Calculated Attack** (precision hits through armor, slow)
- Core: weapon skill and Dexterity (they set the precision chance). Light weapons only: under 3.5 lbs is best, 6.0 lbs or more cannot precision-strike.
- Useful: Strike with a piercing weapon, Initiative. The opponent's best Parry or Dodge lowers your precision chance, so it works poorly against skilled defenders.

**Parry** (purely defensive, slowest initiative)
- Core: Parry, Riposte, Initiative (to offset -10).
- Useful: Disarm only on your own attacks, a shield (Counterstrike, Parry and Defend all prefer one).
- Skip: Dodge, Lunge, Charge.

**Defend** (defensive, extra parry with a shield)
- Core: Parry, a shield, Riposte, Acrobatics (ground recovery).
- Skip: Dodge as a main skill, Lunge.

---

## 4. Best skills for each weapon

Reading the table: **x** means the skill works with that weapon. Charge means the +3 per level attack bonus; spear-charge weapons also drop the defender's parry and get the opening charge (+8 attack, +2 per Charge level, once per fight). Throw means the weapon can be thrown (Opportunity Throw). Martial means the weapon works with Martial Combat.

| Weapon | Wt | Strike | Cleave | Bash | Slash | Sweep | Charge | Disarm | Throw | Martial | Special |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Stiletto | 1.0 | x |  |  |  |  | x |  | x | x | armor-piercing |
| Knife | 1.5 |  |  |  | x |  | x |  | x | x |  |
| Dagger | 2.0 | x |  |  | x |  | x |  | x | x |  |
| Short Sword | 3.0 |  |  |  | x |  | x |  |  |  |  |
| Epee | 3.0 | x |  |  | x |  | x | +5 |  |  |  |
| Scimitar | 3.5 |  | x |  | x |  | x |  |  |  |  |
| Long Sword | 3.2 |  |  |  | x |  | x |  |  |  |  |
| Broad Sword | 3.8 |  |  |  | x |  | x |  |  |  |  |
| Bastard Sword | 4.8 |  | x |  | x |  | x |  |  |  | 2H |
| Great Sword | 6.8 |  | x | x |  |  | x |  |  |  | 2H |
| Hatchet | 1.8 |  |  |  | x |  |  |  | x |  |  |
| Hand Axe | 2.5 |  |  |  | x |  |  |  | x |  |  |
| Battle Axe | 4.5 |  | x |  | x |  |  |  |  |  |  |
| Great Axe | 6.0 |  | x |  | x |  |  |  |  |  | 2H |
| Small Pick | 2.8 | x |  |  |  |  |  |  |  |  | armor-piercing |
| Military Pick | 3.5 | x |  | x |  |  |  |  |  |  | armor-piercing |
| Pick Axe | 4.8 | x | x |  |  |  |  |  |  |  | armor-piercing, 2H |
| Hammer | 2.0 |  |  | x |  |  |  |  | x |  |  |
| Mace | 3.8 |  |  | x |  |  |  |  |  |  |  |
| Morningstar | 4.0 |  |  | x |  |  |  |  |  |  |  |
| War Hammer | 4.5 |  |  | x |  |  |  |  |  |  |  |
| Maul | 7.5 |  |  | x |  |  |  |  |  |  | 2H |
| Club | 2.7 |  |  | x |  |  |  |  |  |  |  |
| Short Spear | 3.0 | x |  |  |  | x | x |  | x |  | spear charge |
| Boar Spear | 3.8 | x |  |  |  | x | x |  | x |  | spear charge |
| Long Spear | 4.2 | x |  |  |  | x | x |  |  |  | spear charge, 2H |
| Pole Axe | 5.5 |  | x |  |  |  | x |  |  |  | spear charge, 2H |
| Halberd | 7.5 |  | x | x |  |  | x |  |  |  | spear charge, 2H |
| Flail | 2.6 |  |  | x |  | x |  |  |  |  | flail wrap |
| Bladed Flail | 4.0 |  |  | x |  | x |  |  |  |  | flail wrap |
| War Flail | 5.0 |  |  | x |  | x |  |  |  |  | flail wrap |
| Battle Flail | 6.5 |  |  | x |  | x |  |  |  |  | flail wrap, 2H |
| Quarterstaff | 3.0 |  |  | x |  | x |  |  |  | x | 2H |
| Great Staff | 5.5 |  |  | x |  | x |  |  |  | x | 2H |
| Buckler | 2.2 |  |  |  |  |  | x |  |  |  | shield |
| Target Shield | 4.2 |  |  | x |  |  | x |  |  |  | shield |
| Tower Shield | 5.5 |  |  | x |  |  | x |  |  |  | shield |
| Cestus | 1.0 |  |  |  |  |  |  |  |  | x |  |
| Trident | 4.3 | x |  |  |  | x |  |  |  |  | spear charge |
| Net | 2.5 |  |  |  |  |  |  | +5 |  | x | entangle |
| Scythe | 3.5 |  | x |  | x |  |  | +5 |  |  | armor-piercing |
| Great Pick | 7.5 | x |  | x |  |  |  |  |  |  | armor-piercing, 2H |
| Javelin | 2.5 | x |  |  |  | x | x |  | x |  | spear charge |
| Ball & Chain | 7.5 |  |  | x |  | x |  | +5 |  |  | flail wrap, 2H |
| Bola | 3.1 |  |  |  |  |  |  |  | x |  | entangle |
| Heavy Barbed Whip | 2.5 |  |  |  |  |  |  | +5 |  |  | entangle |
| Swordbreaker | 2.6 |  |  |  | x |  |  | +10 |  |  |  |

Open Hand (fists): works with Martial Combat, Brawl, Charge (unarmed), Sweep (in Martial Combat).

### Quick guide by weapon family

| Family | Best skills | Why |
|---|---|---|
| **Light blades** (Stiletto, Knife, Dagger, Short Sword, Epee) | Feint, Initiative, Charge, Strike (Stiletto, Dagger, Epee), Slash (all but Stiletto) | Fast, light, and thrusting. The Stiletto is armor-piercing; the Epee adds a Disarm bonus. Stiletto, Knife and Dagger also work in Martial Combat. |
| **Swords** (Long, Broad) | Charge, Slash, Parry, Riposte | Thrusting for Charge, slashing for bleeds, and balanced enough to parry well. |
| **Heavy blades** (Scimitar, Bastard Sword, Great Sword) | Cleave (all three), Slash (Scimitar, Bastard Sword), Bash (Great Sword), Charge | Cleave breaks parries. The Great Sword is in both the Cleave and Bash lists, so it uses whichever skill is higher. |
| **Small axes** (Hatchet, Hand Axe) | Slash, Throw, Initiative | Light slash weapons that can be thrown. |
| **Large axes** (Battle Axe, Great Axe) | Cleave, Slash | Both are Cleave and slash weapons. |
| **Picks** (Small Pick, Military Pick, Pick Axe, Great Pick) | Strike, then Initiative | All are armor-piercing weapons and Strike weapons, so Strike stacks with the weapon's own piercing. The Military Pick and Great Pick also take Bash, the Pick Axe takes Cleave. Tested with the Military Pick against a Brigandine shield user: Calculated Attack and Engage & Withdraw won about 83%, Strike, Lunge and Wall of Steel about 77-78%, Bash 51% and Total Kill 43%. Lunge is no better than Strike for a pick, so Lunge training is wasted on it. |
| **Hammers and maces** (Hammer, Mace, Morningstar, War Hammer, Maul, Club) | Bash | The Bash style and Bash skill both fit. |
| **Spears** (Short, Boar, Long, Javelin, Trident) | Charge, Strike, Sweep, Initiative | Everything lines up: Charge adds attack, damage and a parry penalty, plus the opening charge. Strike pierces armor, Sweep knocks people down. Short Spear, Boar Spear and Javelin can also be thrown. |
| **Polearms** (Pole Axe, Halberd) | Cleave (Bash too for the Halberd), Charge | Heavy hitters with spear-charge bonuses. They do not sweep. |
| **Flails** (Flail, Bladed, War, Battle, Ball & Chain) | Bash, Sweep | All are Bash and sweeping weapons, and they ignore shield bonuses and make parries harder against them. |
| **Staves** (Quarterstaff, Great Staff) | Bash, Sweep, Brawl (in Martial Combat) | Bash weapons that sweep, and they work in Martial Combat. |
| **Shields** (Buckler, Target, Tower) | Charge, Bash (Target and Tower), Parry | Charge boosts shield bashes and rushes. The Tower and Target Shields are Bash weapons. |
| **Net** | Net skill, Disarm, Sweep and Brawl in Martial Combat | Entangles legs on a hit (5% + 2% per Net level). In Martial Combat it also gets Brawl and the 4% Sweep. |
| **Heavy Whip** | Heavy Whip skill, Disarm | Entangles on a hit: 30% + 4% per skill level. |
| **Bola** | Throw, Bola skill | Thrown, 70% chance to entangle and trip. |
| **Scythe** | Cleave, Slash, Disarm | Armor-piercing and a Cleave and slash weapon. |
| **Swordbreaker** | Disarm, Parry, Slash | Also a slash weapon. Strong when your opponent uses a one-handed blade under 5.0 lbs (+10 Disarm, even in the off-hand). No bonus against Bastard Swords, Great Swords, axes, blunt weapons or fists. |
| **Cestus** | Brawl, Sweep, Charge (unarmed) in Martial Combat | A Martial weapon that cannot be disarmed. |
| **Open Hand** | Brawl, Sweep, Charge, Acrobatics | The Martial Combat baseline. Strength adds up to +100% damage, a far higher ceiling than any real weapon. |

---

## 5. Quick builds that line up

| Build idea | Style | Weapon | Key skills |
|---|---|---|---|
| Armor breaker | Calculated Attack or Engage & Withdraw (Strike also works) | Military Pick, Small Pick, Epee | Strike, Initiative, Feint, weapon skill |
| Spear fighter | Lunge, Wall of Steel or Strike | Boar Spear, Long Spear | Charge, Strike, Sweep, Initiative |
| Parry wall | Parry, Defend or Counterstrike | Long Sword or Short Sword + shield | Parry, Riposte, Initiative |
| Karate | Martial Combat | Open Hand, Cestus, Dagger | Brawl, Sweep, Dodge, Acrobatics |
| Hit and run | Engage & Withdraw | Short Spear, Epee | Dodge, Acrobatics, Charge |
| Parry breaker | Bash or Slash | Great Axe, Halberd, Maul | Cleave or Bash, Initiative |
| Shield breaker | Bash or Total Kill | War Flail, Battle Flail | Bash, Sweep, Initiative |
| Trickster | Decoy | Short Sword, Dagger | Feint, Parry, Riposte |
| Thrower | Opportunity Throw | Javelin, Hand Axe | Throw, Initiative, Feint |
| Weapon stealer | Wall of Steel or Parry | Epee + Swordbreaker off-hand | Disarm, Parry, Initiative |

---

## 6. Things worth knowing

- **Attack rate does not vary by weapon.** Every fighter gets 10 actions per minute. A weapon's speed in its description is old; speed comes from Initiative.
- **Heavy armor and low Strength:** armor above what your Strength can carry cuts initiative, attack and defense rolls and raises endurance burn. See the armor capacity table in `armor.py`.
- **Spears are strong right now.** At Charge 5, a Long Spear wins about 62% against a Parry 7 fighter and about 83% against an equal Long Sword fighter. If balance changes, this guide changes too.
- **Weapons in two skill lists:** Great Sword and Halberd are in both Cleave and Bash; a fighter uses whichever skill is higher. The Military Pick is both a Strike weapon and a Bash weapon, and the Pick Axe is both Strike and Cleave.
- **Charge and the Trident:** the Trident gets the spear-charge parry penalty and opening charge, but not the +3 per level Charge attack bonus, because it is in the Oddball weapon family. Pole Axe and Halberd get both.
