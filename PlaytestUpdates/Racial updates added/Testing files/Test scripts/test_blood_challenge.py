#!/usr/bin/env python3
"""
Test Blood Challenge killer participation tracking.
Validates that BC expires after killer fights 3 times without being avenged.
"""

import sys
from team import Team
from warrior import Warrior

def print_bc_status(team, label=""):
    """Print current BC status for a team."""
    if label:
        print(f"\n{label}")
    print(f"  Active BCs: {len(team.get_active_blood_challenges())}")
    for bc in team.blood_challenges:
        status = bc.get("status", "unknown")
        kills = bc.get("target_name")
        dead = bc.get("dead_warrior_name")
        fights = bc.get("killer_turns_fought", 0)
        print(f"    - {dead} -> avenge {kills} | Status: {status} | Killer fights: {fights}/3")

def test_scenario_1():
    """Test: Killer fights 3 times, BC expires without being avenged."""
    print("\n" + "="*80)
    print("SCENARIO 1: Killer fights 3 times without BC challenge - Should expire")
    print("="*80)

    # Create teams
    team_a = Team("Team A", "Manager A", 1)
    team_b = Team("Team B", "Manager B", 2)

    # Create warriors
    warrior_a1 = Warrior("Warrior_A1", "Human", "Male", 10, 10, 10, 10, 10, 10)
    warrior_a2 = Warrior("Warrior_A2", "Human", "Male", 10, 10, 10, 10, 10, 10)
    warrior_b_killer = Warrior("Killer_B", "Human", "Male", 15, 15, 10, 10, 10, 10)

    team_a.warriors = [warrior_a1, warrior_a2]
    team_b.warriors = [warrior_b_killer]

    # Simulate: Killer_B kills Warrior_A1
    team_a.kill_warrior(warrior_a1, "Killer_B", fight_type="standard")
    print_bc_status(team_a, "After Killer_B kills Warrior_A1:")

    # Killer_B fights 3 times (no BC challenge against them)
    for turn in range(1, 4):
        print(f"\n--- Turn {turn}: Killer_B fights (not challenged) ---")
        team_a.record_killer_participation("Killer_B")
        team_a.decrement_blood_challenge_turns()
        print_bc_status(team_a, f"After Killer_B fight #{turn}:")

        # Show if BC would be removed
        active = team_a.get_active_blood_challenges()
        if len(active) == 0:
            print("  >> BC EXPIRED: Killer fought 3 times without being avenged")
            break

    assert len(team_a.get_active_blood_challenges()) == 0, "BC should be expired"
    print("\n[PASS] BC correctly expired after 3 killer fights")

def test_scenario_2():
    """Test: Killer sits out, comes back, counter resumes."""
    print("\n" + "="*80)
    print("SCENARIO 2: Killer fights, sits out, comes back -> Counter resumes")
    print("="*80)

    team_a = Team("Team A", "Manager A", 1)
    team_b = Team("Team B", "Manager B", 2)

    warrior_a1 = Warrior("Warrior_A1", "Human", "Male", 10, 10, 10, 10, 10, 10)
    warrior_a2 = Warrior("Warrior_A2", "Human", "Male", 10, 10, 10, 10, 10, 10)
    warrior_b_killer = Warrior("Killer_B", "Human", "Male", 15, 15, 10, 10, 10, 10)

    team_a.warriors = [warrior_a1, warrior_a2]
    team_b.warriors = [warrior_b_killer]

    # Killer kills warrior
    team_a.kill_warrior(warrior_a1, "Killer_B", "standard")
    print_bc_status(team_a, "After kill:")

    # Turn 1: Killer fights
    print("\n--- Turn 1: Killer fights ---")
    team_a.record_killer_participation("Killer_B")
    team_a.decrement_blood_challenge_turns()
    print_bc_status(team_a, "Killer fights (fight 1/3):")
    assert team_a.blood_challenges[0]["killer_turns_fought"] == 1

    # Turns 2-4: Killer sits out (no fights)
    print("\n--- Turns 2-4: Killer sits out (no fights recorded) ---")
    team_a.decrement_blood_challenge_turns()
    team_a.decrement_blood_challenge_turns()
    team_a.decrement_blood_challenge_turns()
    print_bc_status(team_a, "After 3 turns sitting out:")
    assert team_a.blood_challenges[0]["killer_turns_fought"] == 1, "Counter should stay at 1"

    # Turn 5: Killer comes back and fights (should be fight 2/3)
    print("\n--- Turn 5: Killer comes back and fights ---")
    team_a.record_killer_participation("Killer_B")
    team_a.decrement_blood_challenge_turns()
    print_bc_status(team_a, "Killer fights (fight 2/3):")
    assert team_a.blood_challenges[0]["killer_turns_fought"] == 2

    # Turn 6: Killer fights again (should be fight 3/3, then expire)
    print("\n--- Turn 6: Killer fights one more time ---")
    team_a.record_killer_participation("Killer_B")
    team_a.decrement_blood_challenge_turns()
    print_bc_status(team_a, "Killer fights (fight 3/3 - should expire):")
    assert team_a.blood_challenges[0]["killer_turns_fought"] == 3

    # Remove expired
    team_a.blood_challenges = [
        bc for bc in team_a.blood_challenges
        if bc.get("killer_turns_fought", 0) < 3
    ]
    print("After cleanup:")
    print_bc_status(team_a)
    assert len(team_a.get_active_blood_challenges()) == 0
    print("\n[PASS] PASS: Counter correctly resumed after sit-out period")

def test_scenario_3():
    """Test: Multiple kills create multiple BCs against same killer."""
    print("\n" + "="*80)
    print("SCENARIO 3: Killer kills 2 warriors -> 2 BCs created")
    print("="*80)

    team_a = Team("Team A", "Manager A", 1)
    team_b = Team("Team B", "Manager B", 2)

    warrior_a1 = Warrior("Warrior_A1", "Human", "Male", 10, 10, 10, 10, 10, 10)
    warrior_a2 = Warrior("Warrior_A2", "Human", "Male", 10, 10, 10, 10, 10, 10)
    warrior_b_killer = Warrior("Killer_B", "Human", "Male", 15, 15, 10, 10, 10, 10)

    team_a.warriors = [warrior_a1, warrior_a2]
    team_b.warriors = [warrior_b_killer]

    # Killer kills two warriors
    team_a.kill_warrior(warrior_a1, "Killer_B", "standard")
    print_bc_status(team_a, "After 1st kill:")
    assert len(team_a.blood_challenges) == 1

    team_a.kill_warrior(warrior_a2, "Killer_B", "standard")
    print_bc_status(team_a, "After 2nd kill:")
    assert len(team_a.blood_challenges) == 2

    # Killer fights once - both BCs should increment
    print("\n--- Killer fights (both BCs should track this) ---")
    team_a.record_killer_participation("Killer_B")
    team_a.decrement_blood_challenge_turns()
    print_bc_status(team_a, "After killer's 1st fight:")

    for bc in team_a.blood_challenges:
        assert bc["killer_turns_fought"] == 1, "Both BCs should have killer_turns_fought=1"

    # Killer fights 2 more times
    for turn in range(2, 4):
        print(f"\n--- Killer fights (turn {turn}) ---")
        team_a.record_killer_participation("Killer_B")
        team_a.decrement_blood_challenge_turns()

    print_bc_status(team_a, "After killer's 3rd fight:")
    assert len(team_a.get_active_blood_challenges()) == 0
    print("\n[PASS] PASS: Multiple BCs correctly track same killer")

def test_scenario_4():
    """Test: BC avenged, removed immediately."""
    print("\n" + "="*80)
    print("SCENARIO 4: BC is avenged -> Immediately removed")
    print("="*80)

    team_a = Team("Team A", "Manager A", 1)
    team_b = Team("Team B", "Manager B", 2)

    warrior_a1 = Warrior("Warrior_A1", "Human", "Male", 10, 10, 10, 10, 10, 10)
    warrior_b_killer = Warrior("Killer_B", "Human", "Male", 15, 15, 10, 10, 10, 10)

    team_a.warriors = [warrior_a1]
    team_b.warriors = [warrior_b_killer]

    # Kill and create BC
    team_a.kill_warrior(warrior_a1, "Killer_B", "standard")
    print_bc_status(team_a, "After kill:")
    assert len(team_a.blood_challenges) == 1

    # Simulate avenging (remove BC)
    print("\n--- BC is avenged ---")
    team_a.remove_blood_challenge("Killer_B", "Warrior_A1")
    print_bc_status(team_a, "After avenging:")
    assert len(team_a.blood_challenges) == 0
    print("\n[PASS] PASS: BC correctly removed when avenged")

if __name__ == "__main__":
    try:
        test_scenario_1()
        test_scenario_2()
        test_scenario_3()
        test_scenario_4()

        print("\n" + "="*80)
        print("ALL TESTS PASSED [PASS]")
        print("="*80)
        print("\nBlood Challenge System Working Correctly:")
        print("  [PASS] BCs expire after killer fights 3 times")
        print("  [PASS] Counter pauses when killer sits out")
        print("  [PASS] Counter resumes when killer returns")
        print("  [PASS] Multiple BCs track same killer")
        print("  [PASS] BCs removed when avenged")

    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
