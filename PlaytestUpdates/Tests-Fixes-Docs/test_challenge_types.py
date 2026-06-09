#!/usr/bin/env python3
"""
Test explicit challenge type narratives.
Validates that each challenge type is unmistakably clear.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from narrative import (
    _CHALLENGE_FLAVOR_NORMAL,
    _CHALLENGE_FLAVOR_BLOOD,
    _CHALLENGE_FLAVOR_MONSTER,
    _CHALLENGE_FLAVOR_CHAMPION,
    get_challenge_flavor_line
)

print("\n" + "="*80)
print("CHALLENGE TYPE NARRATIVE VALIDATION")
print("="*80)

def validate_pool(pool_name, pool, required_keyword):
    """Check if all narratives in a pool contain the required keyword."""
    print(f"\n{pool_name}:")
    print(f"  Required keyword(s): {required_keyword}")
    print(f"  Lines:")

    all_valid = True
    for line in pool:
        # Format with dummy names to see full narrative
        formatted = line.format(n1="ATTACKER", n2="DEFENDER")

        # Check for keyword (case-insensitive)
        if isinstance(required_keyword, list):
            has_keyword = any(kw.lower() in formatted.lower() for kw in required_keyword)
        else:
            has_keyword = required_keyword.lower() in formatted.lower()

        status = "[OK]" if has_keyword else "[FAIL]"
        print(f"    {status} {formatted}")

        if not has_keyword:
            all_valid = False

    return all_valid

# Validate each pool
results = {
    "Normal Challenge": validate_pool(
        "NORMAL CHALLENGE POOL",
        _CHALLENGE_FLAVOR_NORMAL,
        "Challenge"
    ),
    "Blood Challenge": validate_pool(
        "BLOOD CHALLENGE POOL",
        _CHALLENGE_FLAVOR_BLOOD,
        "Blood Challenge"
    ),
    "Monster Challenge": validate_pool(
        "MONSTER CHALLENGE POOL",
        _CHALLENGE_FLAVOR_MONSTER,
        ["Monster", "Monster Challenge"]
    ),
    "Champion/Title Challenge": validate_pool(
        "CHAMPION/TITLE CHALLENGE POOL",
        _CHALLENGE_FLAVOR_CHAMPION,
        ["Title", "Title Challenge"]
    ),
}

print("\n" + "="*80)
print("LIVE NARRATIVE GENERATION TEST")
print("="*80)

test_cases = [
    ("challenge", "WARRIOR A", "WARRIOR B", "WARRIOR A"),
    ("blood_challenge", "WARRIOR A", "WARRIOR B", "WARRIOR A"),
    ("monster", "WARRIOR A", "BEAST", None),
    ("champion", "CHALLENGER", "CHAMPION", "CHALLENGER"),
]

for fight_type, w1, w2, challenger in test_cases:
    line = get_challenge_flavor_line(w1, w2, challenger, fight_type)
    print(f"\n{fight_type.upper().replace('_', ' ')} Fight:")
    print(f"  {line}")

print("\n" + "="*80)
print("VALIDATION SUMMARY")
print("="*80)

all_pass = all(results.values())
for challenge_type, passed in results.items():
    status = "PASS" if passed else "FAIL"
    print(f"  {challenge_type}: {status}")

print("\n" + "="*80)
if all_pass:
    print("SUCCESS: All challenge types are unmistakably explicit!")
else:
    print("FAILURE: Some challenge types are not explicit enough!")
print("="*80 + "\n")
