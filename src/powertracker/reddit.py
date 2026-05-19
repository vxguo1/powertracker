"""Reddit search client with OAuth + unauthenticated fallback.

Reddit blocks unauthenticated requests from cloud-provider IPs
(GitHub Actions runners included), so the daily refresh returns 0 posts
without OAuth. Authenticated OAuth requests are allowed at 100 QPM from
any IP. Until Reddit approves our Data Access Request we run manual
pulls from a residential IP, which still works against the legacy
`www.reddit.com/search.json` endpoint.

Logic:
  - If all four OAuth credentials are present (env vars or keys-folder
    files), use OAuth via `oauth.reddit.com`.
  - Otherwise fall back to unauthenticated `www.reddit.com/search.json`.
    This path 403s on cloud IPs but works from a developer machine.

To set up OAuth once Reddit approves the app:
  1. Visit https://www.reddit.com/prefs/apps and create a script-type
     app. The "personal use script" string is the client_id; the
     secret field is the client_secret. Username/password are the
     credentials of the Reddit account that owns the app.
  2. Provide credentials via either env vars
     (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME,
     REDDIT_PASSWORD) or files under
     C:\\Users\\PC\\OneDrive\\keys\\:
       reddit_powertracker_clientid.txt
       reddit_powertracker_clientsecret.txt
       reddit_powertracker_username.txt
       reddit_powertracker_password.txt
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KEYS_DIR = Path(r"C:\Users\PC\OneDrive\keys")
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH_SEARCH_URL = "https://oauth.reddit.com/search"
UNAUTH_SEARCH_URL = "https://www.reddit.com/search.json"
UNAUTH_UA = "powertracker/0.2 (+https://powertracker.io; manual residential pull)"

_CRED_FIELDS = [
    ("REDDIT_CLIENT_ID", "reddit_powertracker_clientid.txt"),
    ("REDDIT_CLIENT_SECRET", "reddit_powertracker_clientsecret.txt"),
    ("REDDIT_USERNAME", "reddit_powertracker_username.txt"),
    ("REDDIT_PASSWORD", "reddit_powertracker_password.txt"),
]

_TOKEN_CACHE: dict[str, str] = {}


def _resolve_cred(env_var: str, fallback_filename: str) -> str | None:
    v = os.environ.get(env_var)
    if v:
        return v.strip()
    p = KEYS_DIR / fallback_filename
    if p.exists():
        first = p.read_text(encoding="utf-8").splitlines()[0].strip()
        return first or None
    return None


def _load_credentials() -> tuple[str, str, str, str] | None:
    """Return all four creds if every one is present, else None."""
    resolved = [_resolve_cred(env, fname) for env, fname in _CRED_FIELDS]
    if all(resolved):
        return tuple(resolved)  # type: ignore[return-value]
    return None


def _get_token() -> tuple[str, str] | None:
    """Return (bearer_token, user_agent) when OAuth is configured, else None."""
    if "token" in _TOKEN_CACHE:
        return _TOKEN_CACHE["token"], _TOKEN_CACHE["ua"]
    creds = _load_credentials()
    if creds is None:
        return None
    client_id, client_secret, username, password = creds
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode({
        "grant_type": "password",
        "username": username,
        "password": password,
    }).encode()
    ua = f"powertracker/0.2 (+https://powertracker.io; by /u/{username})"
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": ua,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    token = payload.get("access_token")
    if not token:
        raise RuntimeError(f"Reddit token response missing access_token: {payload}")
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["ua"] = ua
    return token, ua


def _search_oauth(query: str, t: str, limit: int, sort: str,
                  token: str, ua: str) -> list[dict]:
    qs = urllib.parse.urlencode({
        "q": query, "t": t, "limit": limit, "sort": sort, "raw_json": 1,
    })
    req = urllib.request.Request(
        f"{OAUTH_SEARCH_URL}?{qs}",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": ua,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"  ! {query}: HTTP {e.code}")
        return []
    return [c["data"] for c in data.get("data", {}).get("children", [])]


def _search_unauth(query: str, t: str, limit: int, sort: str) -> list[dict]:
    qs = urllib.parse.urlencode({"q": query, "t": t, "limit": limit, "sort": sort})
    req = urllib.request.Request(
        f"{UNAUTH_SEARCH_URL}?{qs}",
        headers={"User-Agent": UNAUTH_UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"  ! {query}: HTTP {e.code} (unauth)")
        return []
    return [c["data"] for c in data.get("data", {}).get("children", [])]


def search(query: str, t: str = "month", limit: int = 100,
           sort: str = "new") -> list[dict]:
    """Reddit search using OAuth if configured, else unauthenticated.

    Returns the list of post `data` dicts. Schema is identical for both
    paths so callers don't need to know which one was taken.
    """
    token_pair = _get_token()
    if token_pair is not None:
        return _search_oauth(query, t, limit, sort, *token_pair)
    return _search_unauth(query, t, limit, sort)
