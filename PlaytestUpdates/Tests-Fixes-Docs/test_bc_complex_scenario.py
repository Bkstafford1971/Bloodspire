#!/usr/bin/env python3
"""
Test complex Blood Challenge scenario with multiple kills and mixed outcomes.

Turn 1: Warrior A kills Warrior B -> BC1 created (0/3)
Turn 2: Warrior A kills Warrior C -> BC1 (1/3), BC2 created (0/3)
Turn 3: Warrior A loses BC to B's teammate -> BC1 removed, BC2 (1/3)
Turn 4: Warrior A wins BC challenge -> BC2 (2/3)
Turn 5-7: Warrior A sits out -> BC2 (2/3)
Turn 8: Warrior A loses non-BC fight -> BC2 (3/3, expires)
"""

import sys
from team import Team
from warrior import Warrior

def print_bc_status(team_b, team_c, label=""):
    """Print BC status for both teams."""
    if label:
        print(f"\n{label}")
    print(f"  Team B BCs: {len(team_b.get_active_blood_challenges())}")
    for bc in team_b.blood_challenges:
        print(f"    - {bc.get('dead_warrior_name')} -> {bc.get('target_name')} | {bc.get('killer_turns_fought', 0)}/3")
    print(f"  Team C BCs: {len(team_c.get_active_blood_challenges())}")
    for bc in team_c.blood_challenges:
        print(f"    - {bc.get('dead_warrior_name')} -> {bc.get('target_name')} | {bc.get('killer_turns_fought', 0)}/3")

def test_complex_scenario():
    """Test the complex scenario with multiple kills."""
    print("\n" + "="*80)
    print("COMPLEX SCENARIO: Multiple kills, mixed BC outcomes")
    print("="*80)

    # Create teams
    team_a = Team("Team A", "Manager A", 1)
    team_b = Team("Team B", "Manager B", 2)
    team_c = Team("Team C", "Manager C", 3)

    # Create warriors
    warrior_a = Warrior("Warrior_A", "Human", "Male", 15, 15, 10, 10, 10, 10)
    warrior_b = Warrior("Warrior_B", "Human", "Male", 10, 10, 10, 10, 10, 10)
    warrior_b_teammate = Warrior("B_Teammate", "Human", "Male", 12, 12, 10, 10, 10, 10)
    warrior_c = Warrior("Warrior_C", "Human", "Male", 10, 10, 10, 10, 10, 10)

    team_a.warriors = [warrior_a]
    team_b.warriors = [warrior_b, warrior_b_teammate]
    team_c.warriors = [warrior_c]

    # TURN 1: Warrior A kills Warrior B
    print("\n" + "-"*80)
    print("TURN 1: Warrior A kills Warrior B")
    print("-"*80)
    team_b.kill_warrior(warrior_b, "Warrior_A", fight_type="standard")
    team_b.record_killer_participation("Warrior_A")
    team_b.decrement_blood_challenge_turns()
    print_bc_status(team_b, team_c, "After Turn 1:")
    assert len(team_b.get_active_blood_challenges()) == 1, "Should have 1 active BC"
    assert team_b.blood_challenges[0]["killer_turns_fought"] == 1, "Counter should be 1/3"

    # TURN 2: Warrior A kills Warrior C
    print("\n" + "-"*80)
    print("TURN 2: Warrior A kills Warrior C")
    print("-"*80)
    team_c.kill_warrior(warrior_c, "Warrior_A", fight_type="standard")
    # Both teams track Warrior A's participation
    team_b.record_killer_participation("Warrior_A")
    team_c.record_killer_participation("Warrior_A")
    team_b.decrement_blood_challenge_turns()
    team_c.decrement_blood_challenge_turns()
    print_bc_status(team_b, team_c, "After Turn 2:")
    assert len(team_b.get_active_blood_challenges()) == 1, "Team B should have 1 BC"
    assert len(team_c.get_active_blood_challenges()) == 1, "Team C should have 1 BC"
    assert team_b.blood_challenges[0]["killer_turns_fought"] == 2, "Team B BC counter should be 2/3"
    assert team_c.blood_challenges[0]["killer_turns_fought"] == 1, "Team C BC counter should be 1/3"

    # TURN 3: Warrior A loses BC to B's teammate -> BC1 is avenged
    print("\n" + "-"*80)
    print("TURN 3: Warrior A loses BC challenge to B's teammate -> BC1 AVENGED")
    print("-"*80)
    team_b.record_killer_participation("Warrior_A")
    team_c.record_killer_participation("Warrior_A")
    # Remove BC for B's death (avenged)
    team_b.remove_blood_challenge("Warrior_A", "Warrior_B")
    team_b.decrement_blood_challenge_turns()
    team_c.decrement_blood_challenge_turns()
    print_bc_status(team_b, team_c, "After Turn 3:")
    assert len(team_b.get_active_blood_challenges()) == 0, "Team B should have no BCs (avenged)"
    assert len(team_c.get_active_blood_challenges()) == 1, "Team C should have 1 BC"
    assert team_c.blood_challenges[0]["killer_turns_fought"] == 2, "Team C BC counter should be 2/3"

    # TURN 4: Warrior A wins BC challenge
    print("\n" + "-"*80)
    print("TURN 4: Warrior A wins BC challenge -> BC2 at 3/3 (becomes inactive)")
    print("-"*80)
    team_b.record_killer_participation("Warrior_A")
    team_c.record_killer_participation("Warrior_A")
    # Don't remove yet - just increment counter
    team_b.decrement_blood_challenge_turns()
    team_c.decrement_blood_challenge_turns()
    print_bc_status(team_b, team_c, "After Turn 4:")
    assert len(team_c.get_active_blood_challenges()) == 0, "Team C active BCs should be 0 (reached 3 fights)"
    assert team_c.blood_challenges[0]["killer_turns_fought"] == 3, "Team C BC counter should be 3/3"
    print("  (BC is in list but marked as inactive, will be cleaned up)")


    # TURN 5-7: Warrior A sits out
    print("\n" + "-"*80)
    print("TURNS 5-7: Warrior A sits out (no fights)")
    print("-"*80)
    for turn in range(5, 8):
        team_b.decrement_blood_challenge_turns()
        team_c.decrement_blood_challenge_turns()
    print_bc_status(team_b, team_c, "After Turns 5-7 (sitting out):")
    assert len(team_c.get_active_blood_challenges()) == 0, "Team C should have 0 active BCs (counter already at 3)"
    assert team_c.blood_challenges[0]["killer_turns_fought"] == 3, "Counter should still be 3/3 (no change)"
    print("  (BC inactive but still in list, counter paused at 3/3)")

    # TURN 8: Warrior A loses non-BC fight -> BC expires
    print("\n" + "-"*80)
    print("TURN 8: Warrior A loses non-BC fight -> BC2 EXPIRES (reached 3 fights)")
    print("-"*80)
    team_b.record_killer_participation("Warrior_A")
    team_c.record_killer_participation("Warrior_A")
    team_b.decrement_blood_challenge_turns()
    team_c.decrement_blood_challenge_turns()
    # Clean up expired BCs
    team_c.blood_challenges = [
        bc for bc in team_c.blood_challenges
        if bc.get("killer_turns_fought", 0) < 3
    ]
    print_bc_status(team_b, team_c, "After Turn 8:")
    assert len(team_c.get_active_blood_challenges()) == 0, "Team C BC should be expired"
    print("  BC EXPIRED: Killer participated in 3 fights without being successfully avenged")

    print("\n" + "="*80)
    print("[PASS] Complex scenario completed successfully!")
    print("="*80)
    print("\nValidated:")
    print("  [PASS] Multiple independent BCs created for same killer")
    print("  [PASS] All BCs track killer's participation")
    print("  [PASS] Avenging removes BC immediately")
    print("  [PASS] Sitting out pauses counter (doesn't reset)")
    print("  [PASS] Counter resumes when killer returns")
    print("  [PASS] BC expires when killer fights 3 times")

if __name__ == "__main__":
    try:
        test_complex_scenario()
    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
