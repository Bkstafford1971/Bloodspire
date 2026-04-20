# =============================================================================
# file_protection.py — File Integrity Protection System
# =============================================================================
# Prevents players from manually editing save files by:
#   1. Creating checksums for all JSON files
#   2. Setting files to read-only
#   3. Verifying checksums when loading (detects tampering)
# =============================================================================

import json
import os
import stat
import hashlib
from typing import Dict, Any

# ---------------------------------------------------------------------------
# CHECKSUM MANAGEMENT
# ---------------------------------------------------------------------------

def _get_checksum_filepath(json_filepath: str) -> str:
    """Return the path where the checksum file should be stored."""
    return json_filepath.replace('.json', '.checksum')


def calculate_checksum(data: Dict[Any, Any]) -> str:
    """
    Calculate SHA256 checksum of JSON data.
    Uses sorted keys for consistent checksums across saves.
    """
    json_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(json_str.encode()).hexdigest()


def save_checksum(json_filepath: str, data: Dict[Any, Any]):
    """Calculate and save checksum for a JSON file."""
    checksum = calculate_checksum(data)
    checksum_filepath = _get_checksum_filepath(json_filepath)
    try:
        with open(checksum_filepath, 'w', encoding='utf-8') as f:
            f.write(checksum)
        # Make checksum file read-only too
        make_file_readonly(checksum_filepath)
    except IOError as e:
        print(f"  WARNING: Could not save checksum for {os.path.basename(json_filepath)}: {e}")


def verify_checksum(json_filepath: str, data: Dict[Any, Any]) -> bool:
    """
    Verify that loaded data matches its checksum.
    Returns True if valid, False if tampered or checksum missing.
    """
    checksum_filepath = _get_checksum_filepath(json_filepath)
    
    # If no checksum file exists, assume it's an old save (allow it)
    if not os.path.exists(checksum_filepath):
        return True
    
    try:
        with open(checksum_filepath, 'r', encoding='utf-8') as f:
            stored_checksum = f.read().strip()
        
        current_checksum = calculate_checksum(data)
        return stored_checksum == current_checksum
    except IOError as e:
        print(f"  WARNING: Could not read checksum for {os.path.basename(json_filepath)}: {e}")
        return False


# ---------------------------------------------------------------------------
# FILE PERMISSIONS
# ---------------------------------------------------------------------------

def make_file_readonly(filepath: str):
    """Set file to read-only on Windows/Linux/Mac."""
    try:
        # Remove write permissions, keep read
        current_permissions = stat.S_IMODE(os.stat(filepath).st_mode)
        # R + R + R (user, group, other) = 0o444
        os.chmod(filepath, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except (OSError, IOError) as e:
        print(f"  WARNING: Could not set {os.path.basename(filepath)} to read-only: {e}")


def make_file_writable(filepath: str):
    """Temporarily make file writable (for game updates only)."""
    try:
        # R+W + R + R (user, group, other)
        os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    except (OSError, IOError) as e:
        print(f"  WARNING: Could not make {os.path.basename(filepath)} writable: {e}")


# ---------------------------------------------------------------------------
# PROTECTION WRAPPERS
# ---------------------------------------------------------------------------

def save_json_protected(filepath: str, data: Dict[Any, Any]):
    """
    Save JSON data with checksum protection and read-only flag.
    
    Args:
        filepath: Path to save JSON file
        data: Dictionary to save as JSON
        
    Raises:
        IOError: If file cannot be written
    """
    # First, make file writable in case it's an old save being updated
    if os.path.exists(filepath):
        make_file_writable(filepath)
    
    # Write the JSON
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    
    # Save checksum
    save_checksum(filepath, data)
    
    # Set to read-only
    make_file_readonly(filepath)


def load_json_protected(filepath: str) -> Dict[Any, Any]:
    """
    Load JSON data and verify integrity.
    
    Args:
        filepath: Path to JSON file to load
        
    Returns:
        Dictionary with loaded data
        
    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If JSON is corrupted or file was tampered with
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Corrupted JSON in {os.path.basename(filepath)}: {e}")
    
    # Verify checksum if it exists
    if not verify_checksum(filepath, data):
        filename = os.path.basename(filepath)
        raise ValueError(
            f"SECURITY: File '{filename}' was tampered with! "
            f"The checksum does not match. This save cannot be loaded. "
            f"Do not manually edit save files."
        )
    
    return data


# ---------------------------------------------------------------------------
# LEGACY MIGRATION
# ---------------------------------------------------------------------------

def protect_existing_file(filepath: str):
    """
    Protect an existing unprotected file.
    Used when migrating old saves to the new protection system.
    """
    if not os.path.exists(filepath):
        return
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Save checksum and set read-only
        save_checksum(filepath, data)
        make_file_readonly(filepath)
    except Exception as e:
        print(f"  WARNING: Could not protect existing file {os.path.basename(filepath)}: {e}")
