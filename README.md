# Brutal Combo Discord poster

Get new stories from [Brutal Combo](https://brutalcombo.com/) posted to a channel in your Discord server, automatically and for free.

Each story appears as a card with the headline, a short summary, the story image, its category (Release, Patch, Rumor and so on) and a link to the full article.

There is no bot to invite and nothing to install. You make your own copy of this repository, and GitHub runs it for you on a schedule.

## What you need

- A free [GitHub](https://github.com/) account.
- A Discord server where you are allowed to manage webhooks (server owners and admins are).

## Set it up

It takes about five minutes.

### 1. Make a webhook in Discord

1. In Discord, hover over the channel you want stories in and click the gear icon (**Edit Channel**).
2. Go to **Integrations → Webhooks → New Webhook**.
3. Click **Copy Webhook URL**.

Keep that URL private. Anyone who has it can post to your channel.

### 2. Copy this repository

Click **Fork** at the top of this page, then **Create fork**. Leave it public: GitHub runs scheduled jobs for free on public repositories.

### 3. Add your webhook to your copy

1. In your fork, go to **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. Name it `DISCORD_WEBHOOK_URL`, paste the webhook URL as the secret, and click **Add secret**.

The URL is stored encrypted. It never appears in the code or in the logs.

### 4. Switch it on

GitHub turns scheduled jobs off in a new fork until you allow them.

1. Open the **Actions** tab of your fork and click the button to enable workflows.
2. In the list on the left, click **Post new stories**. If you see a notice that the scheduled workflow is disabled, click **Enable workflow**.

### 5. Check it works

Still in the **Actions** tab, click **Send test post → Run workflow → Run workflow**. Within a minute the newest story should appear in your channel.

That's it. New stories now post on their own.

## How often it checks

The schedule asks GitHub to check every 5 minutes. GitHub's free scheduler often runs late, so expect a story to appear roughly 5 to 20 minutes after it is published.

## Options

**Skip some categories.** In **Settings → Secrets and variables → Actions**, open the **Variables** tab and add a variable named `SKIP_CATEGORIES`, for example `Rumor,Business`. The categories are Announcement, Business, Feature, Patch, Platform, Release, Release Date, Rumor, Showcase and Trailer.

**Post to more than one channel.** Make one fork per channel, each with its own webhook.

**Change the look.** The name and avatar on each post come from the webhook. Edit them in Discord under **Integrations → Webhooks**.

## Turning it off

In the **Actions** tab, click **Post new stories**, open the **⋯** menu and choose **Disable workflow**. Or delete the webhook in Discord, or delete your fork.

## Good to know

- **A run failed.** GitHub emails you when a run fails. The usual cause is a missing or mistyped `DISCORD_WEBHOOK_URL` secret, or a webhook that was deleted in Discord.
- **It stopped after a long quiet spell.** GitHub pauses schedules on public repositories that see no activity for 60 days. Re-enable it from the **Actions** tab.
- **Lots of commits called "Update posted stories".** That is expected. The list of stories already posted is kept in `seen.json`, so nothing is posted twice.

## How it works

`poster.py` is a single Python script with no dependencies. Every run it reads the site's [RSS feed](https://brutalcombo.com/feed.xml), posts any story that is not in `seen.json` through the Discord webhook, and adds it to `seen.json`. The two files in `.github/workflows` tell GitHub when to run it.

To run it on your own computer instead, copy `.env.example` to `.env`, put your webhook URL in it, and use:

```
python3 poster.py --dry-run --once   # show what would be posted, send nothing
python3 poster.py --test             # post the newest story once
python3 poster.py                    # keep running and check every 5 minutes
```
