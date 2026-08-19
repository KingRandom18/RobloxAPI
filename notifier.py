#!/usr/bin/env python3
"""
Roblox -> Discord friend activity notifier.

Polls the public (no-login) Roblox presence API for a list of usernames you
specify, and posts a message to a Discord webhook whenever one of them comes
online / starts playing a game.

No Roblox account credentials are used anywhere in this script. Because of
that, friends whose privacy setting for "who can see what I'm playing" is set
to "Friends" (rather than "Everyone") will only show up as generic
"online" with no game name -- Roblox simply doesn't return that detail to an
unauthenticated caller. Friends set to "Everyone" will show full game info.

Setup:
    1. pip install -r requirements.txt
    2. Copy .env.example to .env and fill in DISCORD_WEBHOOK_URL and
       ROBLOX_USERNAMES.
    3. python notifier.py

State is kept in state.json next to this script so that restarting the
script does not re-fire alerts for friends who were already online.
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
NOTIFY_ON_ONLINE_NOT_JUST_INGAME = os.environ.get(
    "NOTIFY_ON_ONLINE_NOT_JUST_INGAME", "true"
).lower() in ("1", "true", "yes")

STATE_FILE = Path(__file__).parent / "state.json"

USERNAME_LOOKUP_URL = "https://users.roblox.com/v1/usernames/users"
PRESENCE_URL = "https://presence.roblox.com/v1/presence/users"
GAMES_URL = "https://games.roblox.com/v1/games"
AVATAR_URL = "https://thumbnails.roblox.com/v1/users/avatar-headshot"

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
    """username -> userId, tolerant of a few not resolving."""
    if not usernames:
        return {}
    resp = session.post(
        USERNAME_LOOKUP_URL,
        json={"usernames": usernames, "excludeBannedUsers": True},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    found = {row["requestedUsername"]: row for row in data}
    missing = [u for u in usernames if u not in found]
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


def get_avatar_url(user_id):
    try:
        resp = session.get(
            AVATAR_URL,
            params={
                "userIds": user_id,
                "size": "150x150",
                "format": "Png",
                "isCircular": "false",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return data[0]["imageUrl"] if data else None
    except requests.RequestException:
        return None


def presence_label(presence):
    ptype = presence.get("userPresenceType", OFFLINE)
    if ptype == INGAME:
        universe_id = presence.get("universeId")
        game_name = get_game_name(universe_id)
        return ("in_game", game_name)
    if ptype == INSTUDIO:
        return ("in_studio", None)
    if ptype == ONLINE:
        return ("online", None)
    return ("offline", None)


def send_discord_alert(username, user_id, status, game_name):
    if not DISCORD_WEBHOOK_URL:
        log("DISCORD_WEBHOOK_URL is not set -- skipping Discord post.")
        return

    if status == "in_game" and game_name:
        title = f"{username} started playing {game_name}"
        description = f"[View profile](https://www.roblox.com/users/{user_id}/profile)"
    elif status == "in_game":
        title = f"{username} is in a game"
        description = (
            "Game name unavailable (their privacy setting hides it from "
            "non-friends).\n"
            f"[View profile](https://www.roblox.com/users/{user_id}/profile)"
        )
    elif status == "in_studio":
        title = f"{username} is in Roblox Studio"
        description = f"[View profile](https://www.roblox.com/users/{user_id}/profile)"
    else:
        title = f"{username} just came online"
        description = f"[View profile](https://www.roblox.com/users/{user_id}/profile)"

    avatar_url = get_avatar_url(user_id)
    embed = {
        "title": title,
        "description": description,
        "color": 0x00A2FF,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if avatar_url:
        embed["thumbnail"] = {"url": avatar_url}

    payload = {"embeds": [embed]}
    try:
        resp = session.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        if resp.status_code >= 300:
            log(f"Discord webhook returned {resp.status_code}: {resp.text}")
        else:
            log(f"Alert sent: {title}")
    except requests.RequestException as e:
        log(f"Failed to post to Discord: {e}")


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
    state = load_state()  # user_id (str) -> last status string

    log(f"Tracking: {[u['username'] for u in users.values()]}")
    log(f"Polling every {POLL_INTERVAL_SECONDS}s. Press Ctrl+C to stop.")

    while True:
        try:
            presences = get_presences(user_ids)
            for uid in user_ids:
                presence = presences.get(uid)
                if presence is None:
                    continue
                username = users[uid]["username"]
                status, game_name = presence_label(presence)
                prev_status = state.get(str(uid), "offline")

                went_online = prev_status == "offline" and status != "offline"
                changed_game = (
                    status == "in_game"
                    and prev_status == "in_game"
                    and state.get(f"{uid}_game") != game_name
                )

                should_alert = status == "in_game" and (went_online or changed_game)
                if not should_alert and NOTIFY_ON_ONLINE_NOT_JUST_INGAME:
                    should_alert = went_online and status in ("online", "in_studio")

                if should_alert:
                    send_discord_alert(username, uid, status, game_name)

                state[str(uid)] = status
                if status == "in_game":
                    state[f"{uid}_game"] = game_name

            save_state(state)
        except requests.RequestException as e:
            log(f"Roblox API request failed, will retry next cycle: {e}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
