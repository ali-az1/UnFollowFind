"""UnFollowFind -- who doesn't follow you back on Instagram.

Pulls the follower/following lists from Instagram's own JSON API using a saved
browser session, so a run takes seconds instead of minutes and the lists are exact
regardless of how many accounts are involved.

    python main.py                  analyse the logged-in account
    python main.py someone          analyse another (public) account
    python main.py --login          log in as a different account / refresh auth.json
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import store
from igapi import ApiError, InstagramAPI, SessionExpired

DESCRIPTION = "UnFollowFind -- who doesn't follow you back on Instagram."

if hasattr(sys.stdout, "reconfigure"):  # Persian/emoji names on a cp1252 console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("user", nargs="?", help="account to analyse (default: the logged-in one)")
    parser.add_argument("--user", dest="user_flag", metavar="NAME",
                        help="same as the positional argument, if you prefer a flag")
    parser.add_argument("--login", action="store_true",
                        help="open a browser to log in (use this to switch account)")
    parser.add_argument("--auth", default="auth.json",
                        help="session file to use -- give each account its own, "
                             "e.g. --auth work.json")
    parser.add_argument("--delay", type=float, default=0.7,
                        help="seconds between API calls (default: 0.7; raise if rate limited)")
    parser.add_argument("--passes", type=int, default=2,
                        help="max sweeps per list when Instagram returns an incomplete "
                             "page set (default: 2, 1 = fastest)")
    parser.add_argument("--compare", nargs="+", metavar="FILE", default=None,
                        help="compare against these files instead of the last snapshot: a "
                             "snapshot .json, or exported .xlsx lists "
                             "(e.g. --compare prefollowers.xlsx)")
    parser.add_argument("--no-xlsx", action="store_true", help="skip writing the .xlsx exports")
    parser.add_argument("--no-snapshot", action="store_true", help="do not record this run")
    parser.add_argument("--keep", type=int, default=30,
                        help="snapshots to keep per account (default: 30, 0 = keep all)")
    parser.add_argument("--limit", type=int, default=0,
                        help="only print the first N names per section (0 = all)")
    args = parser.parse_args()
    args.user = args.user or args.user_flag
    return args


def progress(label: str):
    def report(count: int, expected: int | None) -> None:
        total = f"/{expected}" if expected else ""
        print(f"\r  {label}: {count}{total}", end="", flush=True)
    return report


def show(title: str, users: list[dict], limit: int, key: str = "username") -> None:
    print(f"\n{title} ({len(users)})")
    if not users:
        print("  --")
        return
    shown = users[:limit] if limit else users
    for user in shown:
        name = f"@{user.get(key, '')}"
        extra = []
        if user.get("was"):
            extra.append(f"was @{user['was']}")
        if user.get("full_name"):
            extra.append(user["full_name"])
        if user.get("is_verified"):
            extra.append("verified")
        if user.get("is_private"):
            extra.append("private")
        print(f"  {name:<26} {' | '.join(extra)}".rstrip())
    if limit and len(users) > limit:
        print(f"  ... and {len(users) - limit} more")


def main() -> int:
    args = parse_args()

    if args.login or not Path(args.auth).exists():
        import iglogin
        try:
            iglogin.login(args.auth)
        except Exception as error:  # playwright raises a wide range of errors here
            print(f"Login failed: {error}", file=sys.stderr)
            return 1
        # falls through and analyses the account that just logged in

    started = time.monotonic()
    try:
        api = InstagramAPI(args.auth, delay=args.delay)
        profile = api.resolve(args.user)
        username = profile["username"]
        is_self = str(profile["pk"]) == api.me_pk

        if profile.get("is_private") and not is_self:
            print(f"@{username} is private -- its lists are not readable.", file=sys.stderr)
            return 1

        print(f"\n@{username} -- {profile.get('follower_count', '?')} followers, "
              f"{profile.get('following_count', '?')} following")

        following = api.following(profile, passes=args.passes, on_progress=progress("following"))
        print()
        followers = api.followers(profile, passes=args.passes, on_progress=progress("followers"))
        print()
        api.save_session()
    except SessionExpired as error:
        print(f"\n{error}", file=sys.stderr)
        return 2
    except ApiError as error:
        print(f"\nInstagram API error: {error}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - started

    # Completeness check against the profile counters -- flags a truncated pull.
    for label, pulled, expected in (
        ("following", len(following), profile.get("following_count")),
        ("followers", len(followers), profile.get("follower_count")),
    ):
        if expected and abs(pulled - expected) > max(3, expected * 0.02):
            print(f"  note: pulled {pulled} {label} but the profile reports {expected} "
                  f"(deleted/blocked accounts and rate limits can explain a gap)")

    follower_pks = {u["pk"] for u in followers}
    following_pks = {u["pk"] for u in following}
    whitelist = store.load_whitelist()

    not_following_back = sorted(
        (u for u in following
         if u["pk"] not in follower_pks and u["username"].lower() not in whitelist),
        key=lambda u: u["username"].lower(),
    )
    ignored = sum(1 for u in following
                  if u["pk"] not in follower_pks and u["username"].lower() in whitelist)
    fans = sorted((u for u in followers if u["pk"] not in following_pks),
                  key=lambda u: u["username"].lower())
    mutuals = follower_pks & following_pks

    print(f"\n{'=' * 60}")
    print(f"@{username}   {len(followers)} followers | {len(following)} following | "
          f"{len(mutuals)} mutual   ({elapsed:.1f}s)")
    print("=" * 60)

    show("Not following you back", not_following_back, args.limit)
    if ignored:
        print(f"  ({ignored} more hidden by whitelist.txt)")
    show("You don't follow back", fans, args.limit)

    # --- changes since the baseline -----------------------------------------
    if args.compare:
        try:
            baseline = store.load_baseline(args.compare)
        except (FileNotFoundError, OSError, ValueError) as error:
            print(f"\nCannot read baseline: {error}", file=sys.stderr)
            return 1
        heading = "Compared with " + ", ".join(baseline["sources"])
    else:
        snapshot = store.latest_snapshot(username)
        baseline = snapshot and {"followers": snapshot.get("followers"),
                                 "following": snapshot.get("following")}
        heading = f"Since {snapshot['taken_at']}" if snapshot else ""

    if baseline:
        print(f"\n{'-' * 60}\n{heading}\n{'-' * 60}")
        renamed: dict[str, dict] = {}
        approximate = False

        for label, baseline_list, current_list in (
            ("followers", baseline.get("followers"), followers),
            ("following", baseline.get("following"), following),
        ):
            if baseline_list is None:
                continue
            changes = store.diff(baseline_list, current_list)
            approximate = approximate or not changes["matched_by_id"]
            if label == "followers":
                show("New followers", changes["added"], args.limit)
                show("Lost followers (unfollowed you)", changes["removed"], args.limit)
            else:
                show("You started following", changes["added"], args.limit)
                show("You stopped following", changes["removed"], args.limit)
            renamed.update({u["pk"]: u for u in changes["renamed"]})

        if renamed:
            show("Changed username", list(renamed.values()), args.limit)
        if approximate:
            print("\n  note: the baseline has no account ids, so this comparison matches on "
                  "usernames -- anyone who changed their handle shows up as both lost and new.")
    else:
        print("\nNo previous snapshot for this account -- this run becomes the baseline.")

    if not args.no_snapshot:
        path = store.save_snapshot(username, followers, following)
        store.prune_snapshots(username, args.keep)
        print(f"\nSnapshot: {path}")

    if not args.no_xlsx:
        out = store.DATA_DIR
        store.save_xlsx(out / "followers.xlsx", followers, "followers")
        store.save_xlsx(out / "following.xlsx", following, "following")
        store.save_xlsx(out / "not_following_back.xlsx", not_following_back, "not_following_back")
        print(f"Exports: {out / 'followers.xlsx'}, {out / 'following.xlsx'}, "
              f"{out / 'not_following_back.xlsx'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
