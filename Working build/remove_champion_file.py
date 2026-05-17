#!/usr/bin/env python3
"""
Manual Champion File Removal Script
Run this if champion.json isn't being removed during arena resets
"""

import os
import sys

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from save import CHAMPION_FILE, make_file_writable
    
    def remove_champion_file():
        """Remove the champion.json file"""
        if os.path.exists(CHAMPION_FILE):
            try:
                print(f"Found champion file at: {CHAMPION_FILE}")
                make_file_writable(CHAMPION_FILE)
                os.remove(CHAMPION_FILE)
                print("✓ Successfully removed champion.json")
                return True
            except Exception as e:
                print(f"✗ ERROR: Could not remove champion.json: {e}")
                print(f"  You may need to manually delete: {CHAMPION_FILE}")
                return False
        else:
            print(f"No champion file found at: {CHAMPION_FILE}")
            print("✓ Nothing to remove")
            return True
    
    if __name__ == "__main__":
        print("=" * 60)
        print("CHAMPION FILE REMOVAL TOOL")
        print("=" * 60)
        success = remove_champion_file()
        print("=" * 60)
        sys.exit(0 if success else 1)
        
except ImportError as e:
    print(f"ERROR: Could not import save module: {e}")
    print("Make sure you're running this from your project directory")
    sys.exit(1)
