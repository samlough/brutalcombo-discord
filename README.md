# Brutal Combo Discord poster

Posts new stories from [Brutal Combo](https://brutalcombo.com/) to a Discord channel.

A GitHub Actions workflow runs `poster.py` every few minutes. The script reads the site's RSS feed, posts any story it hasn't seen before through a Discord webhook, and records it in `seen.json` so it is never posted twice.

## Setup

1. In Discord: **Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL**.
2. In this repository: **Settings → Secrets and variables → Actions → New repository secret**, named `DISCORD_WEBHOOK_URL`, with the webhook URL as its value.
3. The workflow starts on its own. The first run only records the stories that already exist; later runs post new ones.

To skip some categories, add a repository **variable** named `SKIP_CATEGORIES`, for example `Rumor,Business`.

## Running it by hand

```
python3 poster.py --dry-run --once   # show what would be posted
python3 poster.py --test             # post the newest story once
```

For local runs, copy `.env.example` to `.env` and put the webhook URL there.
