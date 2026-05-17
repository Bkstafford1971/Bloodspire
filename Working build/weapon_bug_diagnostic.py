#!/usr/bin/env python3
"""
Weapon Description Bug Diagnostic Tool
Run this to check if the fix is properly applied and working
"""

import os
import sys

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_narrative_fix():
    """Check if the narrative.py fix is applied"""
    print("=" * 70)
    print("CHECKING NARRATIVE.PY FIX")
    print("=" * 70)
    
    try:
        with open('narrative.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for the new code
        if 'main_weapon = getattr(w, \'primary_weapon\'' in content:
            print("✓ Fix IS applied in narrative.py source file")
            
            # Check for the old buggy code
            if 'hasattr(w, \'primary_weapon\')' in content:
                print("✗ WARNING: Old buggy code still present in file!")
                print("  You may have both old and new code - check the file manually")
                return False
            else:
                print("✓ Old buggy code removed")
                return True
        else:
            print("✗ Fix NOT applied - still has old code")
            print("  Please apply the fix from IMPROVED_backup_weapon_description.py")
            return False
            
    except FileNotFoundError:
        print("✗ ERROR: narrative.py not found in current directory")
        print("  Make sure you're running this from your project directory")
        return False
    except Exception as e:
        print(f"✗ ERROR: {e}")
        return False

def check_cache():
    """Check for cached .pyc files"""
    print("\n" + "=" * 70)
    print("CHECKING FOR CACHED FILES")
    print("=" * 70)
    
    cache_dir = '__pycache__'
    if os.path.exists(cache_dir):
        pyc_files = [f for f in os.listdir(cache_dir) if f.endswith('.pyc')]
        if pyc_files:
            print(f"⚠ WARNING: Found {len(pyc_files)} cached .pyc files")
            print("  Cached files may be preventing your fix from working!")
            print("\n  Cached files found:")
            for f in pyc_files[:5]:  # Show first 5
                print(f"    - {f}")
            if len(pyc_files) > 5:
                print(f"    ... and {len(pyc_files) - 5} more")
            print("\n  SOLUTION: Delete the __pycache__ folder and restart")
            return False
        else:
            print("✓ No .pyc files found in __pycache__")
            return True
    else:
        print("✓ No __pycache__ directory found (clean)")
        return True

def test_warrior_description():
    """Test warrior description generation"""
    print("\n" + "=" * 70)
    print("TESTING WARRIOR DESCRIPTION GENERATION")
    print("=" * 70)
    
    try:
        from warrior import Warrior
        from narrative import _warrior_report_block
        
        # Create test warrior
        print("\nCreating test warrior with weapons...")
        warrior = Warrior(
            name="Test Warrior",
            race_name="Human",
            gender="Male",
            strength=12,
            dexterity=11,
            constitution=13,
            intelligence=10,
            presence=9,
            size=12
        )
        
        # Set equipment
        warrior.armor = "Cuir Boulli"
        warrior.helm = "Steel Cap"
        warrior.primary_weapon = "Mace"
        warrior.secondary_weapon = "Open Hand"
        warrior.backup_weapon = "Mace"
        
        print(f"  Warrior created: {warrior.name}")
        print(f"  Primary weapon: {warrior.primary_weapon}")
        print(f"  Secondary weapon: {warrior.secondary_weapon}")
        print(f"  Backup weapon: {warrior.backup_weapon}")
        
        # Generate description
        print("\nGenerating description...")
        lines = _warrior_report_block(warrior)
        
        # Check for weapon lines
        weapon_lines = [l for l in lines if "fights using" in l.lower()]
        
        print(f"\n  Generated {len(lines)} total lines")
        print("\n  Description lines:")
        for i, line in enumerate(lines, 1):
            print(f"    {i}. {line}")
        
        if weapon_lines:
            print(f"\n✓ SUCCESS: Found {len(weapon_lines)} weapon description line(s)")
            return True
        else:
            print("\n✗ FAILURE: No weapon description lines found!")
            print("  This means the fix is NOT working properly")
            return False
            
    except Exception as e:
        import traceback
        print(f"\n✗ ERROR during test: {e}")
        traceback.print_exc()
        return False

def test_serialization():
    """Test warrior save/load cycle"""
    print("\n" + "=" * 70)
    print("TESTING SERIALIZATION (SAVE/LOAD)")
    print("=" * 70)
    
    try:
        from warrior import Warrior
        from narrative import _warrior_report_block
        
        # Create warrior
        print("\nCreating warrior...")
        w1 = Warrior(
            name="Serialize Test",
            race_name="Human",
            gender="Female",
            strength=10, dexterity=10, constitution=10,
            intelligence=10, presence=10, size=10
        )
        w1.primary_weapon = "Sword"
        w1.secondary_weapon = "Dagger"
        w1.backup_weapon = "Axe"
        
        print(f"  Original weapons: {w1.primary_weapon}, {w1.secondary_weapon}, {w1.backup_weapon}")
        
        # Serialize
        print("\nSerializing to dict...")
        data = w1.to_dict()
        print(f"  Saved primary: {data.get('primary_weapon')}")
        print(f"  Saved secondary: {data.get('secondary_weapon')}")
        print(f"  Saved backup: {data.get('backup_weapon')}")
        
        # Deserialize
        print("\nDeserializing from dict...")
        w2 = Warrior.from_dict(data)
        print(f"  Loaded primary: {w2.primary_weapon}")
        print(f"  Loaded secondary: {w2.secondary_weapon}")
        print(f"  Loaded backup: {w2.backup_weapon}")
        
        # Test description
        print("\nGenerating description for loaded warrior...")
        lines = _warrior_report_block(w2)
        weapon_lines = [l for l in lines if "fights using" in l.lower()]
        
        if weapon_lines:
            print("✓ SUCCESS: Loaded warrior has weapon descriptions")
            print(f"  Line: {weapon_lines[0]}")
            return True
        else:
            print("✗ FAILURE: Loaded warrior missing weapon descriptions!")
            print("  This is the auto-carry bug!")
            print("\n  All lines:")
            for line in lines:
                print(f"    - {line}")
            return False
            
    except Exception as e:
        import traceback
        print(f"\n✗ ERROR during serialization test: {e}")
        traceback.print_exc()
        return False

def main():
    print("\n" + "=" * 70)
    print("WEAPON DESCRIPTION BUG DIAGNOSTIC TOOL")
    print("=" * 70)
    print()
    
    results = []
    
    # Run all checks
    results.append(("narrative.py fix", check_narrative_fix()))
    results.append(("cache check", check_cache()))
    results.append(("warrior test", test_warrior_description()))
    results.append(("serialization test", test_serialization()))
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    all_passed = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("✓ ALL TESTS PASSED - Fix is working correctly!")
    else:
        print("✗ SOME TESTS FAILED")
        print("\nMost likely causes:")
        print("  1. Cache not cleared (__pycache__ folder)")
        print("  2. Application not fully restarted")
        print("  3. Fix not applied to correct narrative.py file")
        print("\nRecommended actions:")
        print("  1. Delete __pycache__ folder")
        print("  2. Completely close and restart application")
        print("  3. Run this diagnostic again")
    
    print("=" * 70)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
