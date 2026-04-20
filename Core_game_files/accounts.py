# =============================================================================
# accounts.py — BLOODSPIRE Account Management
# =============================================================================
# Stores manager accounts in saves/accounts.json.
# Each account tracks: id, manager_name, email, password (hashed), team_ids
# Maximum 5 teams per manager (25 warriors total).
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
LEAGUE_CONFIG_FILE = os.path.join(BASE_DIR, "league_config.json")
MAX_TEAMS     = 5


# ---------------------------------------------------------------------------
# INTERNAL HELPERS
# ---------------------------------------------------------------------------

def _load() -> dict:
    os.makedirs(os.path.dirname(ACCOUNTS_FILE), exist_ok=True)
    if not os.path.exists(ACCOUNTS_FILE):
        return {"accounts": []}
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"accounts": []}
    accounts = data.get("accounts", [])
    # Wipe on legacy int-id schema: old builds assigned sequential ints starting
    # at 1, so every fresh install's first user got id=1 and collided with every
    # other install. Server-assigned string IDs are the new source of truth.
    if any(not isinstance(a.get("id"), str) for a in accounts):
        accounts = []
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump({"accounts": accounts}, f, indent=2)
    return {"accounts": accounts}


def _save(data: dict):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump({"accounts": data.get("accounts", [])}, f, indent=2)


def _hash_password(password: str, salt: str = None):
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return h, salt


def _load_league_config() -> dict:
    """Load league configuration from league_config.json."""
    try:
        with open(LEAGUE_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"league_server_url": "http://localhost:8766"}


def _register_with_league_server(manager_name: str, password: str) -> dict:
    """
    Register a new manager with the league server. The server assigns a unique
    manager_id (hex string) — returning it is what makes local ID collisions
    impossible. Connection failures are errors, not warnings: we refuse to
    create a local account without a server-assigned ID.
    Returns {"success": True, "manager_id": "..."} or {"success": False, "error": "..."}.
    """
    config = _load_league_config()
    server_url = config.get("league_server_url", "").strip()

    if not server_url:
        return {"success": False,
                "error": "No league server configured in league_config.json. "
                         "Account creation requires a league server."}

    try:
        url = f"{server_url.rstrip('/')}/api/register"
        payload = json.dumps({"manager_name": manager_name,
                              "password": password}).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
        if result.get("success") and result.get("manager_id"):
            return {"success": True, "manager_id": str(result["manager_id"])}
        return {"success": False,
                "error": result.get("error", "League server rejected registration.")}

    except urllib.error.HTTPError as e:
        return {"success": False, "error": f"League server error: HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"success": False,
                "error": f"Could not reach league server at {server_url}: {e.reason}. "
                         f"Account creation requires the league server to be online."}
    except Exception as e:
        return {"success": False,
                "error": f"Could not reach league server at {server_url}: {e}. "
                         f"Account creation requires the league server to be online."}


def _public(acc: dict) -> dict:
    """Return account without sensitive fields."""
    return {
        "id"          : acc["id"],
        "manager_name": acc["manager_name"],
        "email"       : acc["email"],
        "team_ids"    : acc["team_ids"],
    }


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def create_account(manager_name: str, email: str, password: str) -> dict:
    """
    Register a new manager account. Requires the league server to be reachable —
    the server assigns the unique manager_id we then store locally. No server,
    no account (this prevents the old bug where every install's first user got id=1).
    Returns {success, id, manager_name, team_ids} or {success, error}.
    """
    if not manager_name.strip():
        return {"success": False, "error": "Manager name cannot be blank."}
    if len(password) < 4:
        return {"success": False, "error": "Password must be at least 4 characters."}

    server_result = _register_with_league_server(manager_name.strip(), password)
    if not server_result.get("success"):
        return {"success": False,
                "error": server_result.get("error", "League server registration failed.")}
    server_mid = server_result["manager_id"]

    data = _load()
    pw_hash, salt = _hash_password(password)

    # Server already validated name+password, so a local record with the same
    # name is a re-link, not a conflict: update its id and refresh credentials
    # while keeping team_ids and any other state intact.
    existing = next(
        (a for a in data["accounts"]
         if a["manager_name"].lower() == manager_name.strip().lower()),
        None,
    )
    if existing:
        existing["id"]           = server_mid
        existing["manager_name"] = manager_name.strip().upper()
        existing["email"]        = email.strip() or existing.get("email", "")
        existing["pw_hash"]      = pw_hash
        existing["salt"]         = salt
        _save(data)
        return {
            "success"      : True,
            "id"           : server_mid,
            "manager_name" : existing["manager_name"],
            "team_ids"     : existing.get("team_ids", []),
        }

    # No local record by name — check for id collision against a different
    # account before creating a new one.
    if any(acc["id"] == server_mid for acc in data["accounts"]):
        return {"success": False,
                "error": "Server assigned an id that already exists locally. "
                         "Try again or contact the league admin."}

    new_acc = {
        "id"          : server_mid,
        "manager_name": manager_name.strip().upper(),
        "email"       : email.strip(),
        "pw_hash"     : pw_hash,
        "salt"        : salt,
        "team_ids"    : [],
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
    """
    Authenticate a manager.
    Returns {success, id, manager_name, team_ids} or {success, error}.
    """
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
                    "team_ids"     : acc["team_ids"],
                    "run_next_turn": acc.get("run_next_turn", {}),
                }
    return {"success": False, "error": "Invalid manager name or password."}


def get_account(manager_id: str) -> Optional[dict]:
    """Return public account data by ID, or None."""
    data = _load()
    for acc in data["accounts"]:
        if acc["id"] == manager_id:
            return _public(acc)
    return None


def get_manager_for_team(team_id: int) -> Optional[str]:
    """Return the manager_id that owns team_id, or None."""
    data = _load()
    for acc in data["accounts"]:
        if team_id in acc.get("team_ids", []):
            return acc["id"]
    return None


def add_team(manager_id: str, team_id: int) -> tuple:
    """
    Associate a team_id with a manager account.
    Returns (success: bool, error_message: str).
    """
    data = _load()
    for acc in data["accounts"]:
        if acc["id"] == manager_id:
            if len(acc["team_ids"]) >= MAX_TEAMS:
                return False, f"Maximum {MAX_TEAMS} teams per manager."
            if team_id not in acc["team_ids"]:
                acc["team_ids"].append(team_id)
                _save(data)
            return True, ""
    return False, "Account not found."


def replace_team(manager_id: str, old_team_id: int, new_team_id: int) -> tuple:
    """
    Swap old_team_id for new_team_id in a manager's team list.
    Preserves slot order. Returns (success, error).
    """
    data = _load()
    for acc in data["accounts"]:
        if acc["id"] == manager_id:
            if old_team_id not in acc["team_ids"]:
                return False, "Team not found in this account."
            idx = acc["team_ids"].index(old_team_id)
            acc["team_ids"][idx] = new_team_id
            # Copy run_next_turn state if present
            rnt = acc.get("run_next_turn", {})
            rnt.pop(str(old_team_id), None)
            acc["run_next_turn"] = rnt
            _save(data)
            return True, ""
    return False, "Account not found."


def remove_team(manager_id: str, team_id: int) -> tuple:
    """
    Remove a team_id from a manager's account (does NOT delete the team file).
    Returns (success, error).
    """
    data = _load()
    for acc in data["accounts"]:
        if acc["id"] == manager_id:
            if team_id not in acc["team_ids"]:
                return False, "Team not found in this account."
            acc["team_ids"].remove(team_id)
            acc.get("run_next_turn", {}).pop(str(team_id), None)
            _save(data)
            return True, ""
    return False, "Account not found."


def set_run_next_turn(manager_id: str, team_id: int, value: bool) -> tuple:
    """
    Set the run_next_turn flag for a specific team. Returns (success, error).
    """
    data = _load()
    for acc in data["accounts"]:
        if acc["id"] == manager_id:
            if "run_next_turn" not in acc:
                acc["run_next_turn"] = {}
            acc["run_next_turn"][str(team_id)] = value
            _save(data)
            return True, ""
    return False, "Account not found."


def get_run_next_turn(manager_id: str, team_id: int) -> bool:
    """Return the run_next_turn flag for a team (default True)."""
    data = _load()
    for acc in data["accounts"]:
        if acc["id"] == manager_id:
            return acc.get("run_next_turn", {}).get(str(team_id), True)
    return True


def get_teams_to_run(manager_id: str, team_ids: list) -> list:
    """Return the subset of team_ids whose run_next_turn flag is True."""
    data = _load()
    for acc in data["accounts"]:
        if acc["id"] == manager_id:
            rnt = acc.get("run_next_turn", {})
            return [tid for tid in team_ids if rnt.get(str(tid), True)]
    return list(team_ids)
