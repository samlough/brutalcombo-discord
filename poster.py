#!/usr/bin/env python3
"""Post new Brutal Combo stories to a Discord channel through a webhook.

No dependencies beyond the Python standard library.

    python3 poster.py              run forever, checking every few minutes
    python3 poster.py --once       check one time and exit (for cron/launchd)
    python3 poster.py --dry-run    print what would be posted, send nothing
    python3 poster.py --test       post the newest story once, to check the webhook

Settings come from environment variables or a .env file next to this script:

    DISCORD_WEBHOOK_URL   required (except with --dry-run)
    FEED_URL              default https://brutalcombo.com/feed.xml
    CHECK_MINUTES         default 5
    SKIP_CATEGORIES       optional, comma separated, e.g. "Rumor,Business"
"""

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
STATE_FILE = HERE / "seen.json"
USER_AGENT = "BrutalComboDiscordPoster/1.0"
MAX_SEEN = 1000
EMBED_COLOR = 0xE11D2E

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


def build_payload(item):
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
    return {"username": "Brutal Combo", "embeds": [embed]}


def post_to_discord(webhook_url, payload):
    data = json.dumps(payload).encode()
    for _ in range(5):
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=20):
                return
        except urllib.error.HTTPError as err:
            if err.code != 429:
                raise
            # Rate limited: Discord says how long to wait.
            try:
                wait = float(json.loads(err.read()).get("retry_after", 2))
            except Exception:
                wait = 2.0
            time.sleep(wait + 0.5)
    raise RuntimeError("Discord kept rate limiting; gave up on this post")


def load_seen():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None


def save_seen(seen):
    STATE_FILE.write_text(json.dumps(seen[-MAX_SEEN:], indent=0))


def log(message):
    print("[{}] {}".format(time.strftime("%Y-%m-%d %H:%M:%S"), message), flush=True)


def check(feed_url, webhook_url, skip, dry_run):
    items = fetch_items(feed_url)
    seen = load_seen()

    if seen is None:
        # First run: remember what is already published so the channel
        # isn't flooded with old stories. Only later stories get posted.
        if not dry_run:
            save_seen([item["id"] for item in reversed(items)])
        log("First run: noted {} existing stories, posting nothing.".format(len(items)))
        return

    known = set(seen)
    fresh = [item for item in reversed(items) if item["id"] not in known]  # oldest first
    for item in fresh:
        skipped = item["category"].lower() in skip
        if skipped:
            log("Skipped ({}): {}".format(item["category"], item["title"]))
        elif dry_run:
            log("Would post: [{}] {}".format(item["category"], item["title"]))
        else:
            post_to_discord(webhook_url, build_payload(item))
            log("Posted: {}".format(item["title"]))
            time.sleep(1)
        if dry_run:
            continue
        # Save after every story so a crash never causes a double post.
        seen.append(item["id"])
        save_seen(seen)
    if not fresh:
        log("Nothing new.")


def main():
    args = set(sys.argv[1:])
    unknown = args - {"--once", "--dry-run", "--test"}
    if unknown:
        sys.exit("Unknown option: {}\n{}".format(" ".join(sorted(unknown)), __doc__))

    load_env_file()
    feed_url = os.environ.get("FEED_URL", "https://brutalcombo.com/feed.xml")
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    minutes = float(os.environ.get("CHECK_MINUTES", "5"))
    skip = {c.strip().lower() for c in os.environ.get("SKIP_CATEGORIES", "").split(",") if c.strip()}
    dry_run = "--dry-run" in args

    if not webhook_url and not dry_run:
        sys.exit("DISCORD_WEBHOOK_URL is not set. Put it in {}".format(HERE / ".env"))

    if "--test" in args:
        newest = fetch_items(feed_url)[0]
        if dry_run:
            print(json.dumps(build_payload(newest), indent=2, ensure_ascii=False))
        else:
            post_to_discord(webhook_url, build_payload(newest))
            log("Test post sent: {}".format(newest["title"]))
        return

    while True:
        try:
            check(feed_url, webhook_url, skip, dry_run)
        except Exception as err:  # keep running through network hiccups
            log("Check failed: {}".format(err))
            if "--once" in args:
                sys.exit(1)
        if "--once" in args:
            return
        time.sleep(minutes * 60)


if __name__ == "__main__":
    main()
