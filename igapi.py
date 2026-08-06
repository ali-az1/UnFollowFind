"""Thin client for Instagram's private web API, authenticated with a saved browser session.

The browser is only needed once, to produce auth.json (see iglogin.py). After that
every list is pulled straight from the same JSON endpoints the web UI calls, which is
both far faster and exact -- no scrolling, no "Suggested for you" contamination.
"""

from __future__ import annotations

import gzip
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Callable, Iterator

AUTH = "auth.json"

# App id the instagram.com web client sends; without it the API answers with HTML.
WEB_APP_ID = "936619743392459"
BASE = "https://www.instagram.com"

# Cookies Instagram may rotate mid-session and that we want to keep.
_REFRESHABLE = {"csrftoken", "sessionid", "rur", "ig_did", "mid", "ds_user_id"}


class ApiError(RuntimeError):
    """The API answered with something we cannot use."""


class SessionExpired(ApiError):
    """auth.json is no longer accepted -- a new browser login is required."""


def _decode(response) -> Any:
    raw = response.read()
    encoding = (response.headers.get("Content-Encoding") or "").lower()
    if encoding == "gzip":
        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise ApiError("Instagram returned a non-JSON response (session likely stale)") from error


class InstagramAPI:
    def __init__(
        self,
        auth_path: str | Path = AUTH,
        delay: float = 0.7,
        timeout: int = 30,
        max_retries: int = 4,
    ) -> None:
        self.auth_path = Path(auth_path)
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries

        if not self.auth_path.exists():
            raise SessionExpired(f"{self.auth_path} not found -- run: python main.py --login")

        self._state = json.loads(self.auth_path.read_text(encoding="utf-8"))
        self.cookies = {c["name"]: c["value"] for c in self._state.get("cookies", [])}
        if not self.cookies.get("sessionid"):
            raise SessionExpired("auth.json has no sessionid -- run: python main.py --login")

        self.me_pk = str(self.cookies.get("ds_user_id") or "")
        self.me_username = self._username_from_storage()
        self._cookies_changed = False
        self._last_request = 0.0

    # ---------------------------------------------------------------- session

    def _username_from_storage(self) -> str | None:
        """Read the logged-in username out of the saved localStorage blob."""
        for origin in self._state.get("origins", []):
            for item in origin.get("localStorage", []):
                if item.get("name") != "one_tap_storage_version":
                    continue
                try:
                    accounts = json.loads(item["value"])
                except (json.JSONDecodeError, KeyError):
                    continue
                for info in accounts.values():
                    if info.get("username"):
                        return info["username"]
        return None

    def _headers(self, referer: str) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "X-IG-App-ID": WEB_APP_ID,
            "X-ASBD-ID": "129477",
            "X-IG-WWW-Claim": "0",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": self.cookies.get("csrftoken", ""),
            "Referer": referer,
            "Origin": BASE,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Connection": "keep-alive",
            "Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items()),
        }

    def _absorb_cookies(self, response) -> None:
        for header in response.headers.get_all("Set-Cookie") or []:
            name, _, rest = header.partition("=")
            name = name.strip()
            if name not in _REFRESHABLE:
                continue
            value = rest.split(";", 1)[0].strip()
            if value and value not in ('""', "deleted") and self.cookies.get(name) != value:
                self.cookies[name] = value
                self._cookies_changed = True

    def save_session(self) -> None:
        """Write refreshed cookies back to auth.json so the session lives longer."""
        if not self._cookies_changed:
            return
        for cookie in self._state.get("cookies", []):
            if cookie["name"] in self.cookies:
                cookie["value"] = self.cookies[cookie["name"]]
        self.auth_path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._cookies_changed = False

    # ---------------------------------------------------------------- request

    def _throttle(self) -> None:
        wait = self.delay + random.uniform(0, self.delay / 2) - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def get(self, path: str, params: dict[str, Any] | None = None, referer: str = BASE + "/") -> Any:
        url = f"{BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})

        for attempt in range(self.max_retries + 1):
            self._throttle()
            request = urllib.request.Request(url, headers=self._headers(referer))
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    self._last_request = time.monotonic()
                    self._absorb_cookies(response)
                    return _decode(response)
            except urllib.error.HTTPError as error:
                self._last_request = time.monotonic()
                if error.code in (401, 403):
                    raise SessionExpired(
                        f"Instagram rejected the saved session (HTTP {error.code}) -- "
                        "run: python main.py --login"
                    ) from error
                if error.code in (429, 500, 502, 503) and attempt < self.max_retries:
                    backoff = min(120, 15 * (2 ** attempt)) + random.uniform(0, 5)
                    print(f"  rate limited (HTTP {error.code}), waiting {backoff:.0f}s...")
                    time.sleep(backoff)
                    continue
                raise ApiError(f"HTTP {error.code} on {path}") from error
            except (urllib.error.URLError, TimeoutError) as error:
                if attempt < self.max_retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise ApiError(f"Network error on {path}: {error}") from error

        raise ApiError(f"Gave up on {path} after {self.max_retries + 1} attempts")

    # ------------------------------------------------------------------ users

    def user_info(self, pk: str) -> dict[str, Any]:
        payload = self.get(f"/api/v1/users/{pk}/info/")
        user = payload.get("user") if isinstance(payload, dict) else None
        if not isinstance(user, dict):
            raise ApiError(f"No profile returned for user id {pk}")
        return user

    def resolve(self, username: str | None) -> dict[str, Any]:
        """Return the profile for `username`, or for the logged-in account if None."""
        username = (username or "").strip().lstrip("@")

        if not username or (self.me_username and username.lower() == self.me_username.lower()):
            if not self.me_pk:
                raise ApiError("Could not determine your own user id from auth.json")
            return self.user_info(self.me_pk)

        # Search is far less rate-limited than the profile endpoint.
        payload = self.get(
            "/api/v1/web/search/topsearch/",
            {"context": "blended", "query": username, "count": 10},
        )
        for entry in payload.get("users", []) if isinstance(payload, dict) else []:
            user = entry.get("user", {})
            if str(user.get("username", "")).lower() == username.lower():
                return self.user_info(str(user["pk"]))

        raise ApiError(f"Instagram user @{username} was not found")

    # ------------------------------------------------------------ friendships

    def _pages(self, kind: str, pk: str, username: str) -> Iterator[list[dict[str, Any]]]:
        """Page through /friendships/{pk}/{followers|following}/ until exhausted."""
        referer = f"{BASE}/{username}/{kind}/"
        max_id: str | None = None
        seen_cursors: set[str] = set()

        while True:
            payload = self.get(
                f"/api/v1/friendships/{pk}/{kind}/",
                {"count": 50, "max_id": max_id},
                referer=referer,
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("users"), list):
                raise ApiError(f"Unexpected {kind} page for user {pk}")

            yield [
                {
                    "pk": str(user.get("pk") or user.get("id") or ""),
                    "username": user.get("username", ""),
                    "full_name": user.get("full_name", ""),
                    "is_private": bool(user.get("is_private")),
                    "is_verified": bool(user.get("is_verified")),
                }
                for user in payload["users"]
                if user.get("pk") or user.get("id")
            ]

            next_max_id = payload.get("next_max_id")
            if not next_max_id or not payload["users"]:
                return
            next_max_id = str(next_max_id)
            if next_max_id in seen_cursors:  # Instagram sometimes loops a cursor
                return
            seen_cursors.add(next_max_id)
            max_id = next_max_id

    def collect(
        self,
        kind: str,
        profile: dict[str, Any],
        passes: int = 2,
        on_progress: Callable[[int, int | None], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Pull a full follower/following list.

        Instagram's cursor pagination occasionally drops an entry when the list
        shifts underneath it, so if the result is short of the profile counter we
        sweep again and merge. Two passes are normally enough to converge, and the
        extra sweep only happens when something is actually missing.
        """
        pk, username = str(profile["pk"]), profile["username"]
        expected = profile.get("follower_count" if kind == "followers" else "following_count")
        merged: dict[str, dict[str, Any]] = {}

        for attempt in range(1, max(1, passes) + 1):
            for page in self._pages(kind, pk, username):
                for user in page:
                    merged.setdefault(user["pk"], user)
                if on_progress:
                    on_progress(len(merged), expected)
            if not expected or len(merged) >= expected or attempt >= passes:
                break
            print(f"\n  {kind}: {len(merged)}/{expected}, sweeping again to fill the gap...")

        return sorted(merged.values(), key=lambda u: (u["username"] or "").lower())

    def followers(self, profile: dict[str, Any], **kwargs) -> list[dict[str, Any]]:
        return self.collect("followers", profile, **kwargs)

    def following(self, profile: dict[str, Any], **kwargs) -> list[dict[str, Any]]:
        return self.collect("following", profile, **kwargs)
