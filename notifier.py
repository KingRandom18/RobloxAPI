#!/usr/bin/env python3
"""
Roblox -> Discord friend activity notifier (status board version).

Instead of posting a new message every time someone's status changes, this
keeps ONE Discord message and edits it in place whenever anything changes.
The message shows every tracked friend as a little box:

    `PlayerName`
    Online / Offline
    Game: N/A  (or the game name if they're playing one)

No Roblox login or cookie required -- uses Roblox's public presence API
only. A friend whose "who can see what I'm playing" privacy setting is
"Friends" (not "Everyone") will show as Online with Game: N/A, since Roblox
doesn't hand out that detail to an unauthenticated caller.

Setup:
    1. pip install -r requirements.txt
    2. Copy .env.example to .env and fill in DISCORD_WEBHOOK_URL and
       ROBLOX_USERNAMES.
    3. python notifier.py

State (which Discord message to edit, plus last known status per friend) is
kept in state.json next to this script, so restarting the script keeps
editing the same message instead of creating a new one.
"""

import json
import os
import time
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # .env is optional if you set real environment variables instead

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
ROBLOX_USERNAMES = [
    u.strip() for u in os.environ.get("ROBLOX_USERNAMES", "").split(",") if u.strip()
]
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))

STATE_FILE = Path(__file__).parent / "state.json"

USERNAME_LOOKUP_URL = "https://users.roblox.com/v1/usernames/users"
PRESENCE_URL = "https://presence.roblox.com/v1/presence/users"
GAMES_URL = "https://games.roblox.com/v1/games"

# userPresenceType values returned by the Roblox presence API
OFFLINE, ONLINE, INGAME, INSTUDIO = 0, 1, 2, 3

session = requests.Session()
session.headers.update({"Content-Type": "application/json"})


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def resolve_usernames(usernames):
    """username -> {id, username}, tolerant of a few not resolving."""
    if not usernames:
        return {}
    resp = session.post(
        USERNAME_LOOKUP_URL,
        json={"usernames": usernames, "excludeBannedUsers": True},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    found_names = {row["requestedUsername"] for row in data}
    missing = [u for u in usernames if u not in found_names]
    if missing:
        log(f"WARNING: could not resolve these Roblox usernames: {missing}")
    return {row["id"]: {"username": row["name"]} for row in data}


def get_presences(user_ids):
    if not user_ids:
        return {}
    resp = session.post(PRESENCE_URL, json={"userIds": user_ids}, timeout=15)
    resp.raise_for_status()
    presences = resp.json().get("userPresences", [])
    return {p["userId"]: p for p in presences}


_game_name_cache = {}


def get_game_name(universe_id):
    if not universe_id:
        return None
    if universe_id in _game_name_cache:
        return _game_name_cache[universe_id]
    try:
        resp = session.get(GAMES_URL, params={"universeIds": universe_id}, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        name = data[0]["name"] if data else None
    except requests.RequestException:
        name = None
    _game_name_cache[universe_id] = name
    return name


def describe_presence(presence):
    """Return (is_online: bool, game_text: str) for one presence record."""
    if presence is None:
        return False, "N/A"
    ptype = presence.get("userPresenceType", OFFLINE)
    if ptype == INGAME:
        name = get_game_name(presence.get("universeId"))
        return True, (name if name else "Hidden (privacy setting)")
    if ptype == INSTUDIO:
        return True, "Roblox Studio"
    if ptype == ONLINE:
        return True, "N/A"
    return False, "N/A"


def parse_webhook_url(url):
    # https://discord.com/api/webhooks/<id>/<token>
    parts = url.rstrip("/").split("/")
    return parts[-2], parts[-1]  # webhook_id, webhook_token


def build_board_embed(users, presences):
    fields = []
    online_count = 0
    for uid, info in users.items():
        username = info["username"]
        is_online, game_text = describe_presence(presences.get(uid))
        if is_online:
            online_count += 1
            status_line = "🟢 **Online**"
        else:
            status_line = "⚪ Offline"
        value = f"{status_line}\nGame: {game_text}"
        fields.append({"name": f"`{username}`", "value": value, "inline": True})

    embed = {
        "title": "🎮 Roblox Friend Activity",
        "description": f"{online_count} of {len(users)} tracked friend(s) online",
        "color": 0x00A2FF if online_count else 0x5A5A5A,
        "fields": fields,
        "footer": {"text": "Last updated"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return embed


def post_or_edit_board(embed, state):
    """Post the board message once, then edit that same message from then on."""
    webhook_id, webhook_token = parse_webhook_url(DISCORD_WEBHOOK_URL)
    message_id = state.get("_message_id")

    if message_id:
        edit_url = (
            f"https://discord.com/api/webhooks/{webhook_id}/{webhook_token}"
            f"/messages/{message_id}"
        )
        resp = session.patch(edit_url, json={"embeds": [embed]}, timeout=15)
        if resp.status_code == 404:
            log("Previous board message no longer exists -- posting a new one.")
            message_id = None
        elif resp.status_code >= 300:
            log(f"Failed to edit board message ({resp.status_code}): {resp.text}")
            return
        else:
            log("Board message updated.")
            return

    # No message yet (first run, or the old one was deleted) -- create it.
    post_url = f"{DISCORD_WEBHOOK_URL}?wait=true"
    resp = session.post(post_url, json={"embeds": [embed]}, timeout=15)
    if resp.status_code >= 300:
        log(f"Failed to post board message ({resp.status_code}): {resp.text}")
        return
    state["_message_id"] = resp.json()["id"]
    log(f"Posted new board message (id {state['_message_id']}).")


def board_signature(users, presences):
    """A cheap fingerprint of the board's visible content, to skip no-op edits."""
    parts = []
    for uid in users:
        is_online, game_text = describe_presence(presences.get(uid))
        parts.append(f"{uid}:{is_online}:{game_text}")
    return "|".join(parts)


def main():
    if not DISCORD_WEBHOOK_URL:
        log("ERROR: DISCORD_WEBHOOK_URL is not set. Set it in .env or your environment.")
        sys.exit(1)
    if not ROBLOX_USERNAMES:
        log("ERROR: ROBLOX_USERNAMES is empty. Set a comma-separated list in .env.")
        sys.exit(1)

    log(f"Resolving {len(ROBLOX_USERNAMES)} username(s): {ROBLOX_USERNAMES}")
    users = resolve_usernames(ROBLOX_USERNAMES)
    if not users:
        log("ERROR: none of the given usernames resolved to a Roblox account. Check spelling.")
        sys.exit(1)

    user_ids = list(users.keys())
    state = load_state()

    log(f"Tracking: {[u['username'] for u in users.values()]}")
    log(f"Polling every {POLL_INTERVAL_SECONDS}s. Press Ctrl+C to stop.")

    last_signature = state.get("_signature")

    while True:
        try:
            presences = get_presences(user_ids)
            signature = board_signature(users, presences)

            if signature != last_signature:
                embed = build_board_embed(users, presences)
                post_or_edit_board(embed, state)
                state["_signature"] = signature
                save_state(state)
                last_signature = signature
            else:
                log("No change since last check -- skipping Discord edit.")
        except requests.RequestException as e:
            log(f"Roblox API request failed, will retry next cycle: {e}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
