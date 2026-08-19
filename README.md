# Roblox -> Discord friend activity notifier

Watches a list of Roblox usernames and posts to a Discord webhook whenever
one of them comes online / starts playing a game. No Roblox login or cookie
required — it only uses Roblox's public presence API, so there's zero risk
to your Roblox account. The tradeoff: for a friend whose privacy setting for
"who can see what I'm playing" is set to "Friends" rather than "Everyone",
you'll only get a generic "online" alert with no game name, since Roblox
doesn't hand that detail to an unauthenticated caller.

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
4. Optionally adjust `POLL_INTERVAL_SECONDS` (default 60) and
   `NOTIFY_ON_ONLINE_NOT_JUST_INGAME`.

## 3. Run it

```bash
pip install -r requirements.txt
python notifier.py
```

Leave it running. It checks every `POLL_INTERVAL_SECONDS` and only fires an
alert on a *transition* (offline -> online/in-game, or switching games) —
it won't spam you every cycle while someone stays online. Progress/state is
saved to `state.json` next to the script, so restarting it won't re-fire
alerts for people who were already online.

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
