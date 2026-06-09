#!/usr/bin/env python3
# =============================================================================
# file_update_api.py - Programmatic API for File Updates
# =============================================================================
# Use this module if you want to integrate file updates into your Python code.
#
# Example usage:
#   from file_update_api import FileManager
#
#   fm = FileManager()
#   fm.update_team_name(80, "New Team Name")
#   fm.update_manager_name(80, "New Manager")
#   fm.update_warrior_field(80, 0, "popularity", 50)
# =============================================================================

import json
import os
from typing import Optional, Dict, Any, Tuple
from file_protection import make_file_writable, make_file_readonly, save_checksum

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVES_DIR = os.path.join(BASE_DIR, "saves")
TEAMS_DIR = os.path.join(SAVES_DIR, "teams")


class FileManager:
    """High-level API for safely updating protected save files."""

    def __init__(self, base_dir: str = BASE_DIR):
        """Initialize the FileManager."""
        self.base_dir = base_dir
        self.saves_dir = os.path.join(base_dir, "saves")
        self.teams_dir = os.path.join(self.saves_dir, "teams")

    def _get_team_path(self, team_id: int) -> str:
        """Get the path to a team's JSON file."""
        return os.path.join(self.teams_dir, f"team_{team_id:04d}.json")

    def _load_team(self, team_id: int) -> Tuple[Dict[Any, Any], str]:
        """Load a team's data. Returns (data, filepath) or raises on error."""
        filepath = self._get_team_path(team_id)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Team {team_id:04d} not found at {filepath}")

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data, filepath
        except json.JSONDecodeError as e:
            raise ValueError(f"Team file corrupted: {e}")

    def _save_team(self, data: Dict[Any, Any], filepath: str) -> None:
        """Save team data with proper checksum."""
        try:
            make_file_writable(filepath)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            save_checksum(filepath, data)
            make_file_readonly(filepath)
        except Exception as e:
            raise IOError(f"Failed to save team: {e}")

    # ───────────────────────────────────────────────────────────────────────
    # TEAM-LEVEL UPDATES
    # ───────────────────────────────────────────────────────────────────────

    def update_team_name(self, team_id: int, new_name: str) -> bool:
        """Update a team's name."""
        data, filepath = self._load_team(team_id)
        data['team_name'] = new_name
        self._save_team(data, filepath)
        return True

    def update_manager_name(self, team_id: int, new_name: str) -> bool:
        """Update a team's manager name."""
        data, filepath = self._load_team(team_id)
        data['manager_name'] = new_name
        self._save_team(data, filepath)
        return True

    def update_team_field(self, team_id: int, field: str, value: Any) -> bool:
        """Update any field in a team's top-level data."""
        data, filepath = self._load_team(team_id)
        data[field] = value
        self._save_team(data, filepath)
        return True

    def get_team_info(self, team_id: int) -> Dict[str, Any]:
        """Get basic team info (name, manager, warrior count)."""
        data, _ = self._load_team(team_id)
        return {
            'team_id': team_id,
            'team_name': data.get('team_name', 'Unknown'),
            'manager_name': data.get('manager_name', 'Unknown'),
            'warrior_count': len([w for w in data.get('warriors', []) if w]),
        }

    # ───────────────────────────────────────────────────────────────────────
    # WARRIOR-LEVEL UPDATES
    # ───────────────────────────────────────────────────────────────────────

    def get_warrior(self, team_id: int, warrior_index: int) -> Dict[str, Any]:
        """Get a warrior's data by index."""
        data, _ = self._load_team(team_id)

        if 'warriors' not in data:
            raise ValueError("Team has no warriors array")

        if warrior_index >= len(data['warriors']):
            raise IndexError(f"Warrior index {warrior_index} out of range")

        warrior = data['warriors'][warrior_index]
        if warrior is None:
            raise ValueError(f"Warrior at index {warrior_index} is None")

        return warrior

    def update_warrior_field(self, team_id: int, warrior_index: int, field: str, value: Any) -> bool:
        """Update a specific field in a warrior."""
        data, filepath = self._load_team(team_id)

        if 'warriors' not in data:
            raise ValueError("Team has no warriors array")

        if warrior_index >= len(data['warriors']):
            raise IndexError(f"Warrior index {warrior_index} out of range")

        warrior = data['warriors'][warrior_index]
        if warrior is None:
            raise ValueError(f"Warrior at index {warrior_index} is None")

        warrior[field] = value
        self._save_team(data, filepath)
        return True

    def update_warrior_name(self, team_id: int, warrior_index: int, new_name: str) -> bool:
        """Convenience method to update a warrior's name."""
        return self.update_warrior_field(team_id, warrior_index, 'name', new_name)

    def update_warrior_stats(self, team_id: int, warrior_index: int, **kwargs) -> bool:
        """Update multiple warrior fields at once.

        Example:
            fm.update_warrior_stats(80, 0, wins=10, losses=2, kills=3, popularity=50)
        """
        data, filepath = self._load_team(team_id)

        if 'warriors' not in data:
            raise ValueError("Team has no warriors array")

        if warrior_index >= len(data['warriors']):
            raise IndexError(f"Warrior index {warrior_index} out of range")

        warrior = data['warriors'][warrior_index]
        if warrior is None:
            raise ValueError(f"Warrior at index {warrior_index} is None")

        for field, value in kwargs.items():
            warrior[field] = value

        self._save_team(data, filepath)
        return True

    def list_warriors(self, team_id: int) -> list:
        """Get summary of all warriors in a team."""
        data, _ = self._load_team(team_id)
        warriors = []

        for idx, warrior in enumerate(data.get('warriors', [])):
            if warrior is None:
                warriors.append({'index': idx, 'name': '[EMPTY]', 'status': 'empty'})
            else:
                status = 'dead' if warrior.get('is_dead', False) else 'active'
                warriors.append({
                    'index': idx,
                    'name': warrior.get('name', 'Unknown'),
                    'status': status,
                })

        return warriors

    # ───────────────────────────────────────────────────────────────────────
    # BULK OPERATIONS
    # ───────────────────────────────────────────────────────────────────────

    def repair_team(self, team_id: int) -> bool:
        """Reload and resave a team to repair its checksum."""
        data, filepath = self._load_team(team_id)
        self._save_team(data, filepath)
        return True

    def list_all_teams(self) -> list:
        """Get info about all saved teams."""
        teams = []

        if not os.path.isdir(self.teams_dir):
            return teams

        for filename in sorted(os.listdir(self.teams_dir)):
            if filename.startswith("team_") and filename.endswith(".json"):
                try:
                    team_id = int(filename[5:9])
                    info = self.get_team_info(team_id)
                    teams.append(info)
                except (ValueError, FileNotFoundError):
                    pass

        return teams


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE FUNCTIONS (module-level API)
# ─────────────────────────────────────────────────────────────────────────────

_default_manager = None


def _get_manager() -> FileManager:
    """Get the default FileManager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = FileManager()
    return _default_manager


def update_team_name(team_id: int, new_name: str) -> bool:
    """Update a team's name."""
    return _get_manager().update_team_name(team_id, new_name)


def update_manager_name(team_id: int, new_name: str) -> bool:
    """Update a team's manager name."""
    return _get_manager().update_manager_name(team_id, new_name)


def update_warrior_field(team_id: int, warrior_index: int, field: str, value: Any) -> bool:
    """Update a warrior's field."""
    return _get_manager().update_warrior_field(team_id, warrior_index, field, value)


def update_warrior_name(team_id: int, warrior_index: int, new_name: str) -> bool:
    """Update a warrior's name."""
    return _get_manager().update_warrior_name(team_id, warrior_index, new_name)


def update_warrior_stats(team_id: int, warrior_index: int, **kwargs) -> bool:
    """Update multiple warrior fields."""
    return _get_manager().update_warrior_stats(team_id, warrior_index, **kwargs)


def get_team_info(team_id: int) -> Dict[str, Any]:
    """Get team info."""
    return _get_manager().get_team_info(team_id)


def get_warrior(team_id: int, warrior_index: int) -> Dict[str, Any]:
    """Get warrior data."""
    return _get_manager().get_warrior(team_id, warrior_index)


def list_warriors(team_id: int) -> list:
    """List all warriors in a team."""
    return _get_manager().list_warriors(team_id)


def list_all_teams() -> list:
    """List all teams."""
    return _get_manager().list_all_teams()


def repair_team(team_id: int) -> bool:
    """Repair a team's checksum."""
    return _get_manager().repair_team(team_id)


if __name__ == '__main__':
    # Example usage
    fm = FileManager()

    print("All teams:")
    for team in fm.list_all_teams():
        print(f"  Team {team['team_id']:04d}: {team['team_name']} (Manager: {team['manager_name']}, Warriors: {team['warrior_count']})")

    print("\nTeam 80 warriors:")
    for w in fm.list_warriors(80):
        print(f"  [{w['index']}] {w['name']} ({w['status']})")
