#!/usr/bin/env python3
"""
Generate checksum files for rebuilt team JSON files.
Uses SHA256 of sorted JSON data, same as file_protection.py.
"""

import json
import hashlib
import os
import stat

TEAMS_DIR = r"C:\BPClone_Claude\saves\teams"

TEAMS_TO_UPDATE = [
    "team_0055.json",
    "team_0056.json",
    "team_0059.json",
    "team_0063.json",
    "team_0071.json",
]

def calculate_checksum(data):
    """Calculate SHA256 checksum of JSON data with sorted keys."""
    json_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(json_str.encode()).hexdigest()

def make_file_readonly(filepath):
    """Set file to read-only."""
    try:
        if os.name == 'nt':
            os.chmod(filepath, stat.S_IREAD)
        else:
            os.chmod(filepath, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        print(f"  Set read-only: {os.path.basename(filepath)}")
    except Exception as e:
        print(f"  WARNING: Could not set read-only: {e}")

def make_file_writable(filepath):
    """Make file writable."""
    try:
        if os.name == 'nt':
            os.chmod(filepath, stat.S_IWRITE)
        else:
            os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    except Exception as e:
        print(f"  WARNING: Could not make writable: {e}")

def generate_checksum(json_filename):
    """Generate checksum for a team JSON file."""
    json_path = os.path.join(TEAMS_DIR, json_filename)
    checksum_path = json_path.replace('.json', '.checksum')
    
    print(f"\nProcessing: {json_filename}")
    
    # Read the JSON file
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ERROR reading {json_path}: {e}")
        return False
    
    # Calculate checksum
    checksum = calculate_checksum(data)
    print(f"  Checksum: {checksum}")
    
    # Write checksum file
    try:
        # Make writable if it exists
        if os.path.exists(checksum_path):
            make_file_writable(checksum_path)
        
        with open(checksum_path, 'w', encoding='utf-8') as f:
            f.write(checksum)
        
        print(f"  Written: {checksum_path}")
        
        # Set checksum file to read-only
        make_file_readonly(checksum_path)
        
        return True
    except Exception as e:
        print(f"  ERROR writing checksum: {e}")
        return False

def main():
    print("\n" + "="*60)
    print("GENERATING CHECKSUMS FOR TEAM FILES")
    print("="*60)
    
    success_count = 0
    for filename in TEAMS_TO_UPDATE:
        if generate_checksum(filename):
            success_count += 1
    
    print(f"\n{'='*60}")
    print(f"SUMMARY: {success_count}/{len(TEAMS_TO_UPDATE)} checksums generated")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
