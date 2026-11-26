"""
github_push.py — Push generated HTML reports to GitHub Pages.

Uses the GitHub REST API (no git installation required).
Config is read from github_pages.json in the same directory as this script.
Called from arena_stats.py after each turn — silent on failure.
"""

from __future__ import annotations

import os
import json
import base64
import urllib.request
import urllib.error
from typing import Dict, Optional

_CONFIG_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "github_pages.json")
_SERVER_CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves", "league", "config.json")
_API_BASE       = "https://api.github.com"


def _push_enabled() -> bool:
    """Return False when the admin has disabled GitHub pushes for testing."""
    try:
        with open(_SERVER_CFG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return bool(cfg.get("github_push_enabled", True))
    except Exception:
        return True  # default to enabled if config unreadable


def _load_config() -> dict:
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _request(method: str, url: str, token: str, body: Optional[dict] = None) -> dict:
    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github.v3+json",
        "Content-Type":  "application/json",
        "User-Agent":    "Bloodspire-Server/1.0",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req  = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}")


def _get_sha(token: str, owner: str, repo: str, path: str, branch: str) -> Optional[str]:
    """Return the blob SHA of an existing file, or None if the file doesn't exist yet."""
    url = f"{_API_BASE}/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    try:
        return _request("GET", url, token).get("sha")
    except RuntimeError as e:
        if "HTTP 404" in str(e):
            return None
        raise


def push_to_github_pages(files: Dict[str, str]) -> None:
    """
    Push one or more HTML files to the GitHub Pages repo.

    files : { path_in_repo -> html_content_string }
             e.g. {"arena_stats.html": "<html>...</html>"}

    Reads owner / repo / token / branch from github_pages.json.
    Skips silently if the config file is missing or incomplete.
    Logs each success / failure to stdout without raising.
    """
    if not _push_enabled():
        print("  GitHub Pages: push disabled — enable in admin panel to resume.")
        return

    cfg    = _load_config()
    token  = cfg.get("token",  "")
    owner  = cfg.get("owner",  "")
    repo   = cfg.get("repo",   "")
    branch = cfg.get("branch", "main")

    if not all([token, owner, repo]):
        print("  GitHub Pages: skipped — github_pages.json not configured or incomplete.")
        return

    pushed = 0
    for path, content in files.items():
        try:
            sha = _get_sha(token, owner, repo, path, branch)
            body: dict = {
                "message": f"Bloodspire server: update {path}",
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch":  branch,
            }
            if sha:
                body["sha"] = sha   # required when updating an existing file
            url = f"{_API_BASE}/repos/{owner}/{repo}/contents/{path}"
            _request("PUT", url, token, body)
            pushed += 1
            print(f"  GitHub Pages: pushed {path}")
        except Exception as e:
            print(f"  GitHub Pages: failed to push {path}: {e}")

    if pushed:
        print(f"  GitHub Pages: {pushed}/{len(files)} file(s) updated.")
