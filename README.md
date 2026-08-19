# Roblox -> Discord friend activity notifier

Watches a list of Roblox usernames and keeps a single Discord message
up to date with everyone's status — no Roblox login or cookie required, it
only uses Roblox's public presence API, so there's zero risk to your Roblox
account. The tradeoff: for a friend whose privacy setting for "who can see
what I'm playing" is set to "Friends" rather than "Everyone", you'll see
them as Online but with `Game: N/A`, since Roblox doesn't hand that detail
to an unauthenticated caller.

Rather than spamming the channel with a new message every time someone's
status changes, the bot posts **one** message and edits it in place
whenever anything changes. It looks like this:

```
🎮 Roblox Friend Activity
2 of 3 tracked friend(s) online

`PlayerOne`          `PlayerTwo`          `PlayerThree`
🟢 Online             🟢 Online             ⚪ Offline
Game: Obby Simulator  Game: N/A             Game: N/A
```

Each friend gets their own little box (a Discord embed field), with their
username in a code block, their Online/Offline status, and the game they're
playing if that's visible.

## 1. Create the Discord webhook

1. Open Discord, go to the server and channel you want alerts posted in.
2. Server Settings -> Integrations -> Webhooks -> **New Webhook**.
3. Name it (e.g. "Roblox Alerts"), pick the channel, click **Copy Webhook
   URL**. That URL is the only Discord-side setup needed.

## 2. Configure the script

1. `cp .env.example .env`
2. Paste your webhook URL into `DISCORD_WEBHOOK_URL`.
3. Set `ROBLOX_USERNAMES` to a comma-separated list of the exact Roblox
   usernames you want to watch (not display names — the actual @username).
4. Optionally adjust `POLL_INTERVAL_SECONDS` (default 60).

## 3. Run it

```bash
pip install -r requirements.txt
python notifier.py
```

Leave it running. It checks every `POLL_INTERVAL_SECONDS` and only touches
Discord when something on the board actually changed — it edits the same
message in place rather than posting a new one each time. The message ID
and last-known status are saved to `state.json` next to the script, so
restarting the script keeps editing the same message instead of creating a
new one each time.

## 4. Run it 24/7 on a free cloud host (so it works even when your PC is off)

The simplest option is **Railway** (railway.app):

1. Push this folder to a new GitHub repo (or use Railway's "Deploy from
   local" CLI).
2. In Railway: **New Project -> Deploy from GitHub repo**, pick the repo.
3. In the service's **Variables** tab, add `DISCORD_WEBHOOK_URL` and
   `ROBLOX_USERNAMES` (and any other .env values) as environment variables —
   do **not** commit your real `.env` file to GitHub.
4. Set the **Start Command** to `python notifier.py`.
5. Deploy. Railway keeps it running continuously; free trial credit covers a
   small always-on script like this comfortably for casual use.

Alternatives: Render.com ("Background Worker" service type works the same
way), or a small VPS/Raspberry Pi with `pm2` or a systemd service if you'd
rather self-host.

## Notes / limitations

- Roblox's presence API is undocumented-but-stable and used by many public
  tools; it can change or rate-limit without notice. If it stops working,
  that's the most likely cause.
- Username changes: if a tracked friend changes their Roblox username, update
  `ROBLOX_USERNAMES` accordingly — the script resolves usernames to their
  underlying account ID once at startup.
- This intentionally never asks for or stores your Roblox password or
  `.ROBLOSECURITY` cookie.
