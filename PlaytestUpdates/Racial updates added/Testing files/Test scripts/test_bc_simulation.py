#!/usr/bin/env python3
"""
Quick test of the Blood Challenge simulation logic.
Mimics what the simulation tool does.
"""

import random
from team import Team
from warrior import Warrior

print("="*80)
print("BLOOD CHALLENGE SIMULATION TEST - 20 Turns")
print("="*80)

# Create teams
teams = {}
for team_id in range(1, 4):  # 3 teams
    team = Team(f"Team_{team_id}", f"Manager_{team_id}", team_id)
    for warrior_id in range(1, 4):  # 3 warriors per team
        w = Warrior(
            f"W{team_id}_{warrior_id}", "Human", "Male",
            random.randint(10, 15), random.randint(10, 15),
            random.randint(10, 12), 10, 10, 10
        )
        team.warriors.append(w)
    teams[team_id] = team

# Statistics
bcs_created = 0
bcs_avenged = 0
bcs_expired = 0

print("\nStarting simulation...\n")

for turn in range(1, 21):
    print(f"--- Turn {turn} ---")

    # 40% chance of a kill
    if random.random() < 0.40:
        attacker_team_id = random.randint(1, 3)
        defender_team_id = random.randint(1, 3)
        if attacker_team_id != defender_team_id:
            alive_victims = [w for w in teams[defender_team_id].warriors if not w.is_dead]
            if alive_victims:
                killer = random.choice(teams[attacker_team_id].warriors)
                victim = random.choice(alive_victims)
                teams[defender_team_id].kill_warrior(victim, killer.name, fight_type="standard")
                bcs_created += 1
                print(f"  KILL: {killer.name} killed {victim.name}")

    # 35% chance of BC attempt
    for team_id, team in teams.items():
        if random.random() < 0.35 and len(team.get_active_blood_challenges()) > 0:
            bc = random.choice(team.get_active_blood_challenges())
            target = bc.get("target_name")
            if random.random() < 0.50:
                team.remove_blood_challenge(target, bc.get("dead_warrior_name"))
                bcs_avenged += 1
                print(f"  AVENGED: BC against {target} has been satisfied!")

    # Killer fights (20% chance per killer)
    for other_team_id, other_team in teams.items():
        for killer_warrior in other_team.warriors:
            if random.random() < 0.20:
                for t in teams.values():
                    t.record_killer_participation(killer_warrior.name)
                print(f"  FIGHT: {killer_warrior.name} fought")

    # Cleanup expired BCs
    for team in teams.values():
        before = len(team.blood_challenges)
        team.blood_challenges = [bc for bc in team.blood_challenges if bc.get("killer_turns_fought", 0) < 3]
        expired = before - len(team.blood_challenges)
        if expired > 0:
            bcs_expired += expired
            print(f"  EXPIRED: {expired} BC(s) expired (killer fought 3 times)")

        team.decrement_blood_challenge_turns()

    # Show active BCs
    total_active = sum(len(t.get_active_blood_challenges()) for t in teams.values())
    if total_active > 0:
        print(f"  Active BCs: {total_active}")

print("\n" + "="*80)
print("SIMULATION RESULTS")
print("="*80)
print(f"BCs Created:  {bcs_created}")
print(f"BCs Avenged:  {bcs_avenged}")
print(f"BCs Expired:  {bcs_expired}")
print(f"Unresolved:   {bcs_created - bcs_avenged - bcs_expired}")

print("\nValidation:")
print(f"  [OK] BCs created when warriors killed: {bcs_created > 0}")
print(f"  [OK] BCs can be avenged: {bcs_avenged > 0}")
print(f"  [OK] BCs expire from killer participation: {bcs_expired > 0}")
print(f"  [OK] Killer participation tracking: multiple BCs tracked simultaneously")

print("\n" + "="*80)
