#!/usr/bin/env python3
"""
Clear Python Cache Script
Run this in your project directory to clear all cached .pyc files
"""

import os
import shutil
import sys

def clear_pycache():
    """Remove all __pycache__ directories and .pyc files"""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    
    print(f"Clearing Python cache in: {project_dir}")
    print("-" * 60)
    
    removed_count = 0
    
    # Remove __pycache__ directories
    for root, dirs, files in os.walk(project_dir):
        if '__pycache__' in dirs:
            cache_path = os.path.join(root, '__pycache__')
            print(f"Removing: {cache_path}")
            try:
                shutil.rmtree(cache_path)
                removed_count += 1
            except Exception as e:
                print(f"  ERROR: Could not remove {cache_path}: {e}")
    
    # Remove any standalone .pyc files
    for root, dirs, files in os.walk(project_dir):
        for file in files:
            if file.endswith('.pyc'):
                pyc_path = os.path.join(root, file)
                print(f"Removing: {pyc_path}")
                try:
                    os.remove(pyc_path)
                    removed_count += 1
                except Exception as e:
                    print(f"  ERROR: Could not remove {pyc_path}: {e}")
    
    print("-" * 60)
    if removed_count > 0:
        print(f"✓ Successfully cleared {removed_count} cached file(s)/directory(ies)")
        print("\nNow:")
        print("1. Make sure your code changes are saved")
        print("2. Completely close and restart your application")
        print("3. Test the weapon descriptions in a fight")
    else:
        print("No cache files found to clear")
    
    return removed_count

if __name__ == "__main__":
    try:
        clear_pycache()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
