"""One-time browser login that produces auth.json for igapi.py.

You log in yourself in the window that opens (this survives 2FA, captchas and
checkpoints, which scripted form-filling does not). The script just waits until a
real session cookie exists and then saves the browser state.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

LOGIN_TIMEOUT = 300  # seconds to complete the login in the browser


def login(auth_path: str | Path = "auth.json", timeout: int = LOGIN_TIMEOUT) -> Path:
    from playwright.sync_api import sync_playwright  # imported lazily: only needed here

    auth_path = Path(auth_path)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = context.new_page()
        page.goto("https://www.instagram.com/accounts/login/")

        print("\n  A browser window is open. Log in to Instagram there.")
        print("  Finish any 2FA / captcha steps -- this script waits for the session.\n")

        deadline = time.time() + timeout
        while time.time() < deadline:
            cookies = {c["name"]: c["value"] for c in context.cookies()}
            if cookies.get("sessionid") and cookies.get("ds_user_id"):
                time.sleep(3)  # let localStorage settle so the username is stored too
                context.storage_state(path=str(auth_path))
                browser.close()
                print(f"  Session saved to {auth_path}")
                return auth_path
            time.sleep(2)

        browser.close()

    raise TimeoutError(f"No Instagram session appeared within {timeout}s -- login not completed")


def session_username(auth_path: str | Path = "auth.json") -> str | None:
    """Best-effort read of the logged-in username out of a saved state file."""
    auth_path = Path(auth_path)
    if not auth_path.exists():
        return None
    state = json.loads(auth_path.read_text(encoding="utf-8"))
    for origin in state.get("origins", []):
        for item in origin.get("localStorage", []):
            if item.get("name") == "one_tap_storage_version":
                try:
                    for info in json.loads(item["value"]).values():
                        if info.get("username"):
                            return info["username"]
                except (json.JSONDecodeError, KeyError):
                    pass
    return None


if __name__ == "__main__":
    login()
