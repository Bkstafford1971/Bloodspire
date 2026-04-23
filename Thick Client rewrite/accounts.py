# =============================================================================
# accounts.py — BLOODSPIRE Account Management
# =============================================================================
# Stores manager accounts in saves/accounts.json.
# This version automatically registers with the server at creation.
# IDs are numerical (e.g., 20, 21, 22) and assigned by the league server.
# =============================================================================

import json
import os
import hashlib
import secrets
import urllib.request
import urllib.error
from typing import Optional

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_FILE = os.path.join(BASE_DIR, "saves", "accounts.json")
# Your specific league server URL
DEFAULT_SERVER_URL = "http://100.114.138.61:8766"
MAX_TEAMS     = 5

# ---------------------------------------------------------------------------
# INTERNAL HELPERS
# ---------------------------------------------------------------------------

def _load() -> dict:
    """Loads the local account database. Creates it if missing."""
    os.makedirs(os.path.dirname(ACCOUNTS_FILE), exist_ok=True)
    if not os.path.exists(ACCOUNTS_FILE):
        return {"accounts": []}
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict) or "accounts" not in data:
                return {"accounts": []}
            return data
    except Exception:
        return {"accounts": []}


def _save(data: dict):
    """Saves the current state of accounts to the local JSON file."""
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _hash_password(password: str, salt: str = None):
    """Secures passwords using SHA-256 hashing."""
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return h, salt


def _register_with_league_server(manager_name: str, password: str) -> dict:
    """
    Communicates with the server to register the account and get a numerical ID.
    This happens automatically when 'Create Account' is clicked.
    """
    try:
        url = f"{DEFAULT_SERVER_URL.rstrip('/')}/api/register"
        payload = json.dumps({
            "manager_name": manager_name,
            "password": password
        }).encode("utf-8")
        
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        # 10 second timeout to prevent the UI from freezing indefinitely
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
        
        if result.get("success") and result.get("manager_id") is not None:
            return {"success": True, "manager_id": result["manager_id"]}
            
        return {"success": False, "error": result.get("error", "Server rejected registration.")}

    except urllib.error.URLError:
        return {"success": False, 
                "error": f"Cannot reach server at {DEFAULT_SERVER_URL}. Check your internet connection."}
    except Exception as e:
        return {"success": False, "error": f"Registration error: {str(e)}"}


def _public(acc: dict) -> dict:
    """Filters out passwords/salts when passing data to the UI."""
    return {
        "id"          : acc["id"],
        "manager_name": acc["manager_name"],
        "email"       : acc.get("email", ""),
        "team_ids"    : acc.get("team_ids", []),
    }


# ---------------------------------------------------------------------------
# PUBLIC API (Functions called by the main Game UI)
# ---------------------------------------------------------------------------

def create_account(manager_name: str, email: str, password: str) -> dict:
    """
    Registers a new manager. It checks the server for name availability,
    obtains the numerical ID, and saves the account locally.
    """
    name_clean = manager_name.strip()
    if not name_clean:
        return {"success": False, "error": "Manager name cannot be blank."}
    if len(password) < 4:
        return {"success": False, "error": "Password must be at least 4 characters."}

    # Step 1: Automatic Server Registration
    server_result = _register_with_league_server(name_clean, password)
    if not server_result.get("success"):
        return {"success": False, "error": server_result.get("error")}
    
    server_mid = server_result["manager_id"]
    data = _load()
    pw_hash, salt = _hash_password(password)

    # Step 2: Check for existing local entry (update if name matches)
    existing = next(
        (a for a in data["accounts"] if a["manager_name"].lower() == name_clean.lower()),
        None
    )

    if existing:
        existing["id"]           = server_mid
        existing["pw_hash"]      = pw_hash
        existing["salt"]         = salt
        existing["email"]        = email.strip()
        _save(data)
        return {
            "success": True,
            "id": server_mid,
            "manager_name": existing["manager_name"],
            "team_ids": existing.get("team_ids", [])
        }

    # Step 3: Create and Save the New Local Record
    new_acc = {
        "id"          : server_mid,
        "manager_name": name_clean.upper(),
        "email"       : email.strip(),
        "pw_hash"     : pw_hash,
        "salt"        : salt,
        "team_ids"    : [],
        "run_next_turn": {}
    }
    
    data["accounts"].append(new_acc)
    _save(data)

    return {
        "success"      : True,
        "id"           : server_mid,
        "manager_name" : new_acc["manager_name"],
        "team_ids"     : [],
    }


def login(manager_name: str, password: str) -> dict:
    """Logs the user in by checking the local encrypted password."""
    data = _load()
    for acc in data["accounts"]:
        if acc["manager_name"].lower() == manager_name.strip().lower():
            h, _ = _hash_password(password, acc["salt"])
            if h == acc["pw_hash"]:
                return {
                    "success"      : True,
                    "id"           : acc["id"],
                    "manager_name" : acc["manager_name"],
                    "email"        : acc.get("email", ""),
                    "team_ids"     : acc.get("team_ids", []),
                    "run_next_turn": acc.get("run_next_turn", {}),
                }
    return {"success": False, "error": "Invalid manager name or password."}


def get_account(manager_id) -> Optional[dict]:
    """Retrieves account info using the ID."""
    data = _load()
    for acc in data["accounts"]:
        if str(acc["id"]) == str(manager_id):
            return _public(acc)
    return None


def get_manager_for_team(team_id: int) -> Optional[str]:
    """Finds which manager owns a specific team."""
    data = _load()
    for acc in data["accounts"]:
        if team_id in acc.get("team_ids", []):
            return acc["id"]
    return None


def add_team(manager_id, team_id: int) -> tuple:
    """Links a new team to a manager's account."""
    data = _load()
    for acc in data["accounts"]:
        if str(acc["id"]) == str(manager_id):
            if len(acc.get("team_ids", [])) >= MAX_TEAMS:
                return False, f"Maximum {MAX_TEAMS} teams per manager."
            if team_id not in acc["team_ids"]:
                acc["team_ids"].append(team_id)
                _save(data)
            return True, ""
    return False, "Account not found."


def replace_team(manager_id, old_team_id: int, new_team_id: int) -> tuple:
    """Swaps an old team ID for a new one (useful for team renaming/rebuilding)."""
    data = _load()
    for acc in data["accounts"]:
        if str(acc["id"]) == str(manager_id):
            if old_team_id not in acc["team_ids"]:
                return False, "Team not found in this account."
            idx = acc["team_ids"].index(old_team_id)
            acc["team_ids"][idx] = new_team_id
            rnt = acc.get("run_next_turn", {})
            rnt.pop(str(old_team_id), None)
            acc["run_next_turn"] = rnt
            _save(data)
            return True, ""
    return False, "Account not found."


def remove_team(manager_id, team_id: int) -> tuple:
    """Unlinks a team from the manager account."""
    data = _load()
    for acc in data["accounts"]:
        if str(acc["id"]) == str(manager_id):
            if team_id not in acc["team_ids"]:
                return False, "Team not found in this account."
            acc["team_ids"].remove(team_id)
            acc.get("run_next_turn", {}).pop(str(team_id), None)
            _save(data)
            return True, ""
    return False, "Account not found."


def set_run_next_turn(manager_id, team_id: int, value: bool) -> tuple:
    """Toggles whether a team should be processed in the next simulation turn."""
    data = _load()
    for acc in data["accounts"]:
        if str(acc["id"]) == str(manager_id):
            if "run_next_turn" not in acc:
                acc["run_next_turn"] = {}
            acc["run_next_turn"][str(team_id)] = value
            _save(data)
            return True, ""
    return False, "Account not found."


def get_run_next_turn(manager_id, team_id: int) -> bool:
    """Checks if a team is set to run the next turn."""
    data = _load()
    for acc in data["accounts"]:
        if str(acc["id"]) == str(manager_id):
            return acc.get("run_next_turn", {}).get(str(team_id), True)
    return True


def get_teams_to_run(manager_id, team_ids: list) -> list:
    """Returns a list of team IDs that have the 'run' flag enabled."""
    data = _load()
    for acc in data["accounts"]:
        if str(acc["id"]) == str(manager_id):
            rnt = acc.get("run_next_turn", {})
            return [tid for tid in team_ids if rnt.get(str(tid), True)]
    return list(team_ids)