#!/usr/bin/env python3
"""Quick test of template file operations"""
import os
import json
from pathlib import Path

# Test template file creation and reading
test_dir = Path(r"C:\BPClone_Claude\saves\strategy_templates")
test_dir.mkdir(parents=True, exist_ok=True)

# Create a test template
test_template = {
    "name": "Test Warrior Elf",
    "armor": "Leather Armor",
    "helm": "Leather Cap",
    "primary_weapon": "Short Sword",
    "secondary_weapon": "Dagger",
    "backup_weapon": "None",
    "strategies": [
        {
            "trigger": "You have taken heavy damage",
            "style": "Defend",
            "activity": 2,
            "aim_point": "None",
            "defense_point": "Chest"
        },
        {
            "trigger": "Always (Default Loop)",
            "style": "Slash",
            "activity": 7,
            "aim_point": "Chest",
            "defense_point": "None"
        }
    ]
}

# Write template
template_file = test_dir / "Test Warrior Elf.json"
with open(template_file, 'w') as f:
    json.dump(test_template, f, indent=2)
print(f"✅ Template saved to {template_file}")

# Read template back
with open(template_file, 'r') as f:
    loaded = json.load(f)
print(f"✅ Template loaded successfully")

# Verify structure
assert loaded["name"] == "Test Warrior Elf", "Name mismatch"
assert loaded["armor"] == "Leather Armor", "Armor mismatch"
assert len(loaded["strategies"]) == 2, "Strategies count mismatch"
print(f"✅ Template structure verified")

# List templates
templates = [f[:-5] for f in os.listdir(test_dir) if f.endswith('.json')]
print(f"✅ Found {len(templates)} template(s): {templates}")

print("\n✅ All file operations working correctly!")
