#!/usr/bin/env python3
"""Post new Brutal Combo stories to Discord.

No dependencies beyond the Python standard library.

    python3 poster.py              run forever, checking every few minutes
    python3 poster.py --once       check one time and exit (for cron/GitHub Actions)
    python3 poster.py --dry-run    print what would be posted, send nothing
    python3 poster.py --test       post the newest story once, to check the setup

Stories can go to two kinds of places, and you can use either or both:

  * Bot: every server the bot has been added to, in the channel named
    CHANNEL_NAME. Set DISCORD_BOT_TOKEN.
  * Webhook: one fixed channel. Set DISCORD_WEBHOOK_URL.

Settings come from environment variables or a .env file next to this script:

    DISCORD_BOT_TOKEN     bot token from the Discord Developer Portal
    DISCORD_WEBHOOK_URL   webhook URL of a single channel
    CHANNEL_NAME          channel the bot posts in, default "brutal-combo"
    FEED_URL              default https://brutalcombo.com/feed.xml
    CHECK_MINUTES         default 5
    SKIP_CATEGORIES       optional, comma separated, e.g. "Rumor,Business"
"""

import hashlib
import hmac
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEEN_FILE = HERE / "seen.json"
SERVERS_FILE = HERE / "servers.json"
DISCORD_API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://brutalcombo.com, 2.0)"
MAX_SEEN = 1000
EMBED_COLOR = 0xE11D2E
TEXT_CHANNEL_TYPES = (0, 5)  # normal text channels and announcement channels

CATEGORY_EMOJI = {
    "Release": "🚀",
    "Patch": "🛠️",
    "Rumor": "👀",
    "Announcement": "📣",
    "Trailer": "🎬",
    "Showcase": "🎪",
    "Business": "💼",
    "Feature": "📰",
    "Platform": "🎮",
    "Release Date": "📅",
}


def log(message):
    print("[{}] {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), message), flush=True)


def load_env_file():
    path = HERE / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


# ---------------------------------------------------------------- the feed


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def fetch_items(feed_url):
    """Return feed items, newest first, as a list of dicts."""
    root = ET.fromstring(http_get(feed_url))
    items = []
    for node in root.iter("item"):
        link = (node.findtext("link") or "").strip()
        items.append(
            {
                "id": (node.findtext("guid") or link).strip(),
                "title": (node.findtext("title") or "").strip(),
                "link": link,
                "summary": (node.findtext("description") or "").strip(),
                "category": (node.findtext("category") or "").strip(),
                "date": (node.findtext("pubDate") or "").strip(),
            }
        )
    return items


def find_image(article_url):
    """Pull the article's share image from its og:image tag, if it has one."""
    try:
        page = http_get(article_url).decode("utf-8", "replace")
    except Exception:
        return None
    for tag in re.findall(r"<meta[^>]+>", page):
        if re.search(r"""property=["']og:image["']""", tag):
            found = re.search(r"""content=["']([^"']+)["']""", tag)
            if found:
                return html.unescape(found.group(1))
    return None


def build_embed(item):
    embed = {
        "title": item["title"][:256],
        "url": item["link"],
        "description": item["summary"][:2000],
        "color": EMBED_COLOR,
    }
    if item["category"]:
        emoji = CATEGORY_EMOJI.get(item["category"], "🎮")
        embed["footer"] = {"text": "{} {}".format(emoji, item["category"])}
    try:
        when = parsedate_to_datetime(item["date"]).astimezone(timezone.utc)
        embed["timestamp"] = when.isoformat()
    except Exception:
        pass
    image = find_image(item["link"])
    if image:
        embed["image"] = {"url": image}
    return embed


def welcome_embed(channel_name):
    return {
        "title": "✅ Brutal Combo is connected",
        "description": (
            "New gaming stories from [Brutal Combo](https://brutalcombo.com/) will be "
            "posted in #{} as they are published. Here is the latest one."
        ).format(channel_name),
        "color": EMBED_COLOR,
    }


# ---------------------------------------------------------------- Discord


def discord_request(method, url, payload=None, token=None):
    """Call Discord, waiting and retrying when it says we are going too fast."""
    headers = {"User-Agent": USER_AGENT}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bot " + token
    for _ in range(5):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as err:
            if err.code != 429:
                raise
            try:
                wait = float(json.loads(err.read()).get("retry_after", 2))
            except Exception:
                wait = 2.0
            time.sleep(min(wait, 60) + 0.5)
    raise RuntimeError("Discord kept rate limiting; gave up on this request")


def send_webhook(webhook_url, embeds):
    discord_request("POST", webhook_url, {"username": "Brutal Combo", "embeds": embeds})


def send_channel(token, channel_id, embeds):
    discord_request(
        "POST", "{}/channels/{}/messages".format(DISCORD_API, channel_id), {"embeds": embeds}, token
    )


def list_server_ids(token):
    """IDs of every server the bot has been added to."""
    ids, after = [], None
    while True:
        url = DISCORD_API + "/users/@me/guilds?limit=200"
        if after:
            url += "&after=" + after
        batch = discord_request("GET", url, token=token) or []
        ids.extend(guild["id"] for guild in batch)
        if len(batch) < 200:
            return ids
        after = batch[-1]["id"]


def find_channel(token, server_id, channel_name):
    """ID of the server's channel with the agreed name, or None.

    Discord only lists channels the bot is allowed to see, so a private
    channel counts only once the bot has been given access to it.
    """
    try:
        channels = discord_request(
            "GET", "{}/guilds/{}/channels".format(DISCORD_API, server_id), token=token
        )
    except urllib.error.HTTPError:
        return None
    for channel in channels or []:
        if channel.get("type") in TEXT_CHANNEL_TYPES and channel.get("name", "").lower() == channel_name:
            return channel["id"]
    return None


def server_key(token, server_id):
    """A scrambled stand-in for a server ID.

    servers.json is public when this runs from a public repository, so it
    stores these instead of real server IDs. They can't be reversed without
    the bot token. If the token is ever reset, every server simply gets the
    welcome message once more.
    """
    return hmac.new(token.encode(), server_id.encode(), hashlib.sha256).hexdigest()[:32]


# ---------------------------------------------------------------- state


def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(seen[-MAX_SEEN:], indent=0))


def save_servers(keys):
    SERVERS_FILE.write_text(json.dumps(sorted(keys), indent=0))


# ---------------------------------------------------------------- the check


def welcome_new_servers(settings, server_ids, newest, dry_run):
    """Greet servers that just got their channel. Returns (ready, just_welcomed).

    `ready` holds the IDs of servers that have been greeted, now or earlier.
    """
    token, channel_name = settings["token"], settings["channel"]
    known = set(load_json(SERVERS_FILE, []))
    ready, just_welcomed, waiting, failed = [], {}, 0, 0
    embeds = None
    for server_id in server_ids:
        if server_key(token, server_id) in known:
            ready.append(server_id)
            continue
        channel_id = find_channel(token, server_id, channel_name)
        if not channel_id:
            waiting += 1
            continue
        if dry_run:
            just_welcomed[server_id] = channel_id
            continue
        try:
            if embeds is None:
                embeds = [welcome_embed(channel_name)] + ([build_embed(newest)] if newest else [])
            send_channel(token, channel_id, embeds)
        except urllib.error.HTTPError:
            failed += 1  # most often: the bot can't send in that channel yet
            continue
        just_welcomed[server_id] = channel_id
        ready.append(server_id)

    if not dry_run:
        save_servers(server_key(token, server_id) for server_id in ready)
    if just_welcomed:
        log("{} {} new server(s).".format("Would welcome" if dry_run else "Welcomed", len(just_welcomed)))
    if waiting:
        log("{} server(s) have no #{} channel the bot can see yet.".format(waiting, channel_name))
    if failed:
        log("{} server(s) have the channel but the bot couldn't post in it.".format(failed))
    return ready, just_welcomed


def check(settings, dry_run):
    token, webhook_url = settings["token"], settings["webhook"]
    items = fetch_items(settings["feed"])
    seen = load_json(SEEN_FILE, None)

    ready, just_welcomed = [], {}
    if token:
        server_ids = list_server_ids(token)
        newest = items[0] if items else None
        ready, just_welcomed = welcome_new_servers(settings, server_ids, newest, dry_run)
        log("Bot is in {} server(s); {} set up.".format(len(server_ids), len(ready)))

    if seen is None:
        # First run: remember what is already published so no channel is
        # flooded with old stories. Only later stories get posted.
        if not dry_run:
            save_seen([item["id"] for item in reversed(items)])
        log("First run: noted {} existing stories, posting nothing.".format(len(items)))
        return

    known = set(seen)
    fresh = [item for item in reversed(items) if item["id"] not in known]  # oldest first
    if not fresh:
        log("Nothing new.")
        return

    # Servers greeted in this run already got the newest story with the greeting.
    targets = [server_id for server_id in ready if server_id not in just_welcomed]
    channels = {}
    if token and not dry_run and any(item["category"].lower() not in settings["skip"] for item in fresh):
        for server_id in targets:
            channel_id = find_channel(token, server_id, settings["channel"])
            if channel_id:
                channels[server_id] = channel_id

    attempts = failures = 0
    for item in fresh:
        if item["category"].lower() in settings["skip"]:
            log("Skipped ({}): {}".format(item["category"], item["title"]))
        elif dry_run:
            log("Would post: [{}] {}".format(item["category"], item["title"]))
        else:
            embeds = [build_embed(item)]
            sent = failed = 0
            if webhook_url:
                try:
                    send_webhook(webhook_url, embeds)
                    sent += 1
                except Exception:
                    failed += 1
            for channel_id in channels.values():
                try:
                    send_channel(token, channel_id, embeds)
                    sent += 1
                except Exception:
                    failed += 1
                time.sleep(0.3)
            attempts += sent + failed
            failures += failed
            log("Posted to {} place(s), {} failed: {}".format(sent, failed, item["title"]))
        if dry_run:
            continue
        # Save after every story so a crash never causes a double post.
        seen.append(item["id"])
        save_seen(seen)

    if attempts and failures == attempts:
        raise RuntimeError("every post failed; check the bot token and webhook URL")


def send_test(settings, dry_run):
    newest = fetch_items(settings["feed"])[0]
    embeds = [build_embed(newest)]
    if dry_run:
        print(json.dumps({"embeds": embeds}, indent=2, ensure_ascii=False))
    elif settings["webhook"]:
        send_webhook(settings["webhook"], embeds)
        log("Test post sent to the webhook channel: {}".format(newest["title"]))
    else:
        token, sent = settings["token"], 0
        for server_id in list_server_ids(token):
            channel_id = find_channel(token, server_id, settings["channel"])
            if channel_id:
                send_channel(token, channel_id, embeds)
                sent += 1
        log("Test post sent to {} server(s): {}".format(sent, newest["title"]))


def main():
    args = set(sys.argv[1:])
    unknown = args - {"--once", "--dry-run", "--test"}
    if unknown:
        sys.exit("Unknown option: {}\n{}".format(" ".join(sorted(unknown)), __doc__))

    load_env_file()
    env = os.environ.get
    settings = {
        "feed": env("FEED_URL") or "https://brutalcombo.com/feed.xml",
        "webhook": (env("DISCORD_WEBHOOK_URL") or "").strip(),
        "token": (env("DISCORD_BOT_TOKEN") or "").strip(),
        "channel": (env("CHANNEL_NAME") or "brutal-combo").strip().lstrip("#").lower(),
        "skip": {c.strip().lower() for c in (env("SKIP_CATEGORIES") or "").split(",") if c.strip()},
    }
    minutes = float(env("CHECK_MINUTES") or "5")
    dry_run = "--dry-run" in args

    if not settings["webhook"] and not settings["token"] and not dry_run:
        sys.exit(
            "Nowhere to post. Set DISCORD_BOT_TOKEN or DISCORD_WEBHOOK_URL in {}".format(HERE / ".env")
        )

    if "--test" in args:
        send_test(settings, dry_run)
        return

    while True:
        try:
            check(settings, dry_run)
        except Exception as err:  # keep running through network hiccups
            log("Check failed: {}".format(err))
            if "--once" in args:
                sys.exit(1)
        if "--once" in args:
            return
        time.sleep(minutes * 60)


if __name__ == "__main__":
    main()
