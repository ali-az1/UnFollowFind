# UnFollowFind

Find out who doesn't follow you back on Instagram — and what changed since last time.

The tool talks to the same JSON endpoints instagram.com itself uses, authenticated with a
browser session you create once. No scrolling, no HTML parsing, no size limit: a ~160-account
profile takes about 15 seconds, and accounts with thousands of followers work the same way.

## Install

```bash
git clone https://github.com/ali-az1/UnFollowFind.git
cd UnFollowFind

python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

pip install -r Requirements.txt
playwright install chromium     # only needed for the one-time login
```

## Use

```bash
python main.py --login          # opens a browser: log in yourself, session is saved to auth.json
python main.py                  # analyse the logged-in account
python main.py someone          # analyse any public account
```

The first run without `auth.json` starts the login automatically. The saved session lasts for
weeks; when it stops working the tool tells you to run `--login` again.

**Which account is analysed** is the first argument (`python main.py someone`, or `--user someone`
if you prefer a flag). With no argument it uses whoever is logged in.

**Which account you're logged in as** is whatever is in `auth.json`. `--login` opens a fresh,
logged-out browser window, so log in there as the account you want and the file is replaced. To
keep several accounts side by side, give each its own session file:

```bash
python main.py --login --auth auth-work.json   # log in as the other account
python main.py --auth auth-work.json           # use it from then on
```

Name extra session files `auth-*.json` — `.gitignore` already covers that pattern, and these
files are live logins.

In PyCharm these go in **Run → Edit Configurations… → Parameters**.

### Options

| flag | meaning |
| --- | --- |
| `--compare FILE…` | compare against these files instead of the last snapshot (see below) |
| `--passes N` | max sweeps per list when Instagram hands back an incomplete page set (default 2, `1` = fastest) |
| `--delay S` | seconds between API calls (default 0.7 — raise it if you get rate limited) |
| `--limit N` | print only the first N names per section |
| `--keep N` | snapshots to keep per account (default 30, `0` = keep all) |
| `--no-xlsx`, `--no-snapshot` | skip the exports / skip recording this run |
| `--auth PATH` | use a different session file |

## What you get

```
@you   68 followers | 91 following | 64 mutual   (14.9s)

Not following you back (7)          accounts you follow that don't follow you
You don't follow back (4)           accounts that follow you but you don't follow

Since 2026-08-06T20:33:52+00:00     appears from the second run onwards
New followers / Lost followers
You started following / You stopped following
Changed username                    same account, new handle
```

Plus `data/followers.xlsx`, `data/following.xlsx`, `data/not_following_back.xlsx`
(username, full name, id, private, verified).

### whitelist.txt

```bash
cp whitelist.example.txt whitelist.txt
```

Accounts listed there are hidden from "Not following you back" — brands, news pages, anyone you
follow on purpose. One username per line, `#` starts a comment. They're still counted, and the
report tells you how many were hidden. The file is git-ignored, so your list stays local.

### Snapshots

Every run writes `data/snapshots/<user>-<timestamp>.json` and diffs against the previous one.
Comparison is done on numeric account ids, not usernames, so someone changing their handle shows
up as *Changed username* instead of a fake lost-follower/new-follower pair.

### Comparing against an older list

`--compare` swaps in any other baseline — a specific snapshot, or old exported sheets:

```bash
python main.py --compare prefollowers.xlsx              # who left since that file
python main.py --compare followers.xlsx following.xlsx  # both sides
python main.py --compare data/snapshots/you-20260802-165307.json
```

A file's role comes from its name: anything containing *following* is treated as a following
list, everything else as followers. Single-column, username-only sheets from older versions work
too — the report then matches on handles and says so, because without account ids a rename is
indistinguishable from someone leaving and someone new arriving.

## How it works

| file | role |
| --- | --- |
| `igapi.py` | API client: cookie session, retry/backoff, pagination, completeness passes |
| `iglogin.py` | one-time Playwright login that produces `auth.json` |
| `store.py` | whitelist, xlsx export, snapshots, id-based diffing |
| `main.py` | CLI and report |

Instagram's cursor pagination sometimes skips an entry when the list shifts mid-pull. Each list
is therefore checked against the profile's own follower/following counter, and swept again and
merged if it came back short — that's what `--passes` controls. If a gap remains after the last
pass (deleted or blocked accounts can cause one), the run says so instead of quietly reporting a
wrong list.

## Notes

- `auth.json` is a live login for your account. It's in `.gitignore` — keep it that way.
- This uses a private API. Keep `--delay` sane and don't run it in a loop; hammering it is how
  accounts get rate limited or flagged.
- Private accounts other than your own can't be read.
