# Brutal Combo for Discord

Get new gaming stories from [Brutal Combo](https://brutalcombo.com/) posted in your Discord server, automatically and for free.

[![Add to Discord](https://img.shields.io/badge/Add%20to%20Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/oauth2/authorize?client_id=1572135220398923826&scope=bot&permissions=19456)

## Set it up in two steps

You need to be an owner or admin of the server. No account to create, nothing to install.

**1. Add the bot.** Click **[Add to Discord](https://discord.com/oauth2/authorize?client_id=1572135220398923826&scope=bot&permissions=19456)**, pick your server, and click **Authorize**.

**2. Make a channel named `brutal-combo`.** In your server, click the **+** next to "Text Channels", type `brutal-combo` as the name, and click **Create Channel**.

That's it. Within about 20 minutes the bot posts a "Brutal Combo is connected" message in that channel, along with the latest story. After that, every new story shows up there on its own.

## What the posts look like

Each story is a card with the headline, a short summary, the story image, its category (Release, Patch, Rumor and so on) and a link to the full article. Stories usually appear 5 to 20 minutes after they are published.

## If nothing shows up

Give it 30 minutes first. Then check these, in order:

- **The channel name is exactly `brutal-combo`.** Lowercase, with the dash, no extra words.
- **The bot can see the channel.** If the channel is private, open **Edit Channel → Permissions** and add the **Brutal Combo** bot.
- **The bot is allowed to post.** In the channel's permissions, the bot needs **View Channel**, **Send Messages** and **Embed Links**. The Add to Discord link asks for exactly these three and nothing else.

Fix any of these and the welcome message arrives on the next check. You don't need to add the bot again.

## Questions

**Can I use a different channel name?** Not yet. The bot looks for a channel named `brutal-combo`.

**Can I move or rename the channel later?** Move it anywhere you like. If you rename it, the posts stop until a channel named `brutal-combo` exists again.

**What can the bot see?** It can't read your messages. It only posts stories. It has no access to members, DMs or other channels' content.

**How do I remove it?** Kick the **Brutal Combo** bot from your server, or delete the channel to pause it.

**Does it cost anything?** No.

---

## For the curious: how it works

Everything runs from this repository. There is no server behind it.

- `poster.py` is one Python script with no dependencies. It reads the site's [RSS feed](https://brutalcombo.com/feed.xml) and posts any story it hasn't posted before.
- GitHub Actions runs the script every few minutes (see `.github/workflows`).
- `seen.json` records which stories have been posted, so nothing is posted twice. `servers.json` records which servers have had their welcome message, as scrambled values rather than real server IDs.

### Run your own copy

You only need this if you want your own bot or a different news feed.

1. Fork this repository and keep the fork public.
2. In your fork, go to **Settings → Secrets and variables → Actions** and add one or both secrets:
   - `DISCORD_BOT_TOKEN`: the token of a bot you create in the [Discord Developer Portal](https://discord.com/developers/applications). It posts in every server the bot is added to.
   - `DISCORD_WEBHOOK_URL`: a webhook URL from **Edit Channel → Integrations → Webhooks**. It posts in that one channel.
3. Open the **Actions** tab, enable workflows, and enable the **Post new stories** schedule.

Optional repository variables: `CHANNEL_NAME` (default `brutal-combo`) and `SKIP_CATEGORIES` (for example `Rumor,Business`). To use a different feed, change the default feed address near the bottom of `poster.py`.

To run it on your own computer, copy `.env.example` to `.env`, fill it in, and use:

```
python3 poster.py --dry-run --once   # show what would be posted, send nothing
python3 poster.py --test             # post the newest story once
python3 poster.py                    # keep running and check every 5 minutes
```
