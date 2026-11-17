// Brutal Combo for Discord: all of the logic.
//
// Nothing in this file touches the Cloudflare runtime directly. Storage
// (`env.STATE`, a KV namespace) and the outside world (`deps.fetch`,
// `deps.sleep`) are passed in, which keeps it easy to test.
//
// What is stored:
//   seen               JSON list of story IDs that have been handled
//   job                the story currently being delivered, if any
//   hook:<channel id>  one entry per connected channel; the webhook ID and
//                      token live in the entry's metadata

const DISCORD_API = "https://discord.com/api/v10";
const USER_AGENT = "DiscordBot (https://brutalcombo.com, 3.0)";
const DEFAULT_FEED = "https://brutalcombo.com/feed.xml";
const DEFAULT_NAME = "Brutal Combo";
const DEFAULT_AVATAR = "https://brutalcombo.com/icon.png";
const EMBED_COLOR = 0xe11d2e;
const MAX_SEEN = 1000;
const MAX_RETRIES = 3;
const JOB_MAX_AGE_MS = 60 * 60 * 1000;

// Cloudflare's free plan allows 50 outgoing requests per run. A run also
// fetches the feed and a story page, so stay well under that.
export const POSTS_PER_RUN = 35;

const CATEGORY_EMOJI = {
  Release: "🚀",
  Patch: "🛠️",
  Rumor: "👀",
  Announcement: "📣",
  Trailer: "🎬",
  Showcase: "🎪",
  Business: "💼",
  Feature: "📰",
  Platform: "🎮",
  "Release Date": "📅",
};

// ---------------------------------------------------------------- the feed

export function decodeEntities(text) {
  return text
    .replace(/&#x([0-9a-f]+);/gi, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)))
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function tagText(block, name) {
  const found = block.match(new RegExp("<" + name + "(?:\\s[^>]*)?>([\\s\\S]*?)</" + name + ">"));
  if (!found) return "";
  const raw = found[1].trim();
  const cdata = raw.match(/^<!\[CDATA\[([\s\S]*)\]\]>$/);
  return cdata ? cdata[1].trim() : decodeEntities(raw);
}

/** Feed items, newest first. */
export function parseFeed(xml) {
  const items = [];
  const blocks = xml.match(/<item[\s>][\s\S]*?<\/item>/g) || [];
  for (const block of blocks) {
    const link = tagText(block, "link");
    items.push({
      id: tagText(block, "guid") || link,
      title: tagText(block, "title"),
      link,
      summary: tagText(block, "description"),
      category: tagText(block, "category"),
      date: tagText(block, "pubDate"),
    });
  }
  return items.filter((item) => item.id && item.link);
}

/** The page's share image, from its og:image tag. */
export function findImage(html) {
  const tags = html.slice(0, 60000).match(/<meta[^>]+>/g) || [];
  for (const tag of tags) {
    if (/property=["']og:image["']/.test(tag)) {
      const found = tag.match(/content=["']([^"']+)["']/);
      if (found) return decodeEntities(found[1]);
    }
  }
  return null;
}

export function buildEmbed(item, image) {
  const embed = {
    title: item.title.slice(0, 256),
    url: item.link,
    description: item.summary.slice(0, 2000),
    color: EMBED_COLOR,
  };
  if (item.category) {
    embed.footer = { text: (CATEGORY_EMOJI[item.category] || "🎮") + " " + item.category };
  }
  const when = new Date(item.date);
  if (!isNaN(when.getTime())) embed.timestamp = when.toISOString();
  if (image) embed.image = { url: image };
  return embed;
}

export function welcomeEmbed() {
  return {
    title: "✅ Brutal Combo is connected",
    description:
      "New gaming stories from [Brutal Combo](https://brutalcombo.com/) will be posted in " +
      "this channel as they are published. Here is the latest one.",
    color: EMBED_COLOR,
  };
}

async function getText(deps, url) {
  const response = await deps.fetch(url, { headers: { "User-Agent": USER_AGENT } });
  if (!response.ok) throw new Error("GET " + url + " returned " + response.status);
  return response.text();
}

async function fetchFeed(env, deps) {
  return parseFeed(await getText(deps, env.FEED_URL || DEFAULT_FEED));
}

async function embedFor(item, deps) {
  let image = null;
  try {
    image = findImage(await getText(deps, item.link));
  } catch (err) {
    // A story without its picture is still worth posting.
  }
  return buildEmbed(item, image);
}

// ---------------------------------------------------------------- Discord

/**
 * Posts to one connected channel. The name and picture are sent with every
 * message, so each post shows the Brutal Combo name and logo no matter how
 * the webhook itself is set up in Discord.
 * Returns "ok", "gone" (the webhook was deleted), "retry" or "bad".
 */
export async function postToHook(env, deps, hook, embeds) {
  let response;
  try {
    response = await deps.fetch(DISCORD_API + "/webhooks/" + hook.id + "/" + hook.token, {
      method: "POST",
      headers: { "Content-Type": "application/json", "User-Agent": USER_AGENT },
      body: JSON.stringify({
        username: env.POST_NAME || DEFAULT_NAME,
        avatar_url: env.POST_AVATAR_URL || DEFAULT_AVATAR,
        embeds,
      }),
    });
  } catch (err) {
    return "retry";
  }
  if (response.ok) return "ok";
  if (response.status === 404 || response.status === 401) return "gone";
  if (response.status === 429 || response.status >= 500) return "retry";
  return "bad";
}

const BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

export function toBase64(bytes) {
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i];
    const b = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const c = i + 2 < bytes.length ? bytes[i + 2] : 0;
    out += BASE64[a >> 2] + BASE64[((a & 3) << 4) | (b >> 4)];
    out += i + 1 < bytes.length ? BASE64[((b & 15) << 2) | (c >> 6)] : "=";
    out += i + 2 < bytes.length ? BASE64[c & 63] : "=";
  }
  return out;
}

/**
 * Gives a newly connected webhook the Brutal Combo name and logo, so it also
 * looks right in the server's Integrations settings. Posts carry the name and
 * logo themselves, so nothing breaks if this fails.
 */
async function brandHook(env, deps, hook) {
  try {
    const image = await deps.fetch(env.POST_AVATAR_URL || DEFAULT_AVATAR, {
      headers: { "User-Agent": USER_AGENT },
    });
    if (!image.ok) return false;
    const type = ((image.headers && image.headers.get("content-type")) || "image/png").split(";")[0];
    const bytes = new Uint8Array(await image.arrayBuffer());
    const response = await deps.fetch(DISCORD_API + "/webhooks/" + hook.id + "/" + hook.token, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "User-Agent": USER_AGENT },
      body: JSON.stringify({
        name: env.POST_NAME || DEFAULT_NAME,
        avatar: "data:" + type + ";base64," + toBase64(bytes),
      }),
    });
    return response.ok;
  } catch (err) {
    return false;
  }
}

// ---------------------------------------------------------------- storage

async function saveJob(env, deps, job) {
  // KV allows one write per second to a key, and a quick run can finish
  // within a second of creating the job. Try again once if that happens.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      if (job) await env.STATE.put("job", JSON.stringify(job));
      else await env.STATE.delete("job");
      return;
    } catch (err) {
      if (attempt === 1) throw err;
      await deps.sleep(1200);
    }
  }
}

// ---------------------------------------------------------------- the timed run

/**
 * One timed run. Starts delivering the oldest unposted story, or carries on
 * with a delivery that an earlier run could not finish. Returns a one-line
 * summary for the log. Nothing that identifies a server is logged.
 */
export async function runTick(env, deps) {
  const now = Date.now();
  let job = await env.STATE.get("job", "json");
  if (job && now - job.started > JOB_MAX_AGE_MS) job = null;

  if (!job) {
    const items = await fetchFeed(env, deps);
    if (!items.length) return "The feed is empty.";

    const seen = await env.STATE.get("seen", "json");
    if (!seen) {
      // First run: note what is already published so no channel is flooded
      // with old stories. Only later stories get posted.
      await env.STATE.put("seen", JSON.stringify(items.map((item) => item.id).reverse()));
      return "First run: noted " + items.length + " existing stories, posting nothing.";
    }

    const known = new Set(seen);
    const fresh = items.filter((item) => !known.has(item.id));
    if (!fresh.length) return "Nothing new.";

    const item = fresh[fresh.length - 1]; // the oldest unposted story
    job = {
      title: item.title,
      embeds: [await embedFor(item, deps)],
      cursor: null,
      listed: false,
      retry: [],
      started: now,
    };
    // Mark it handled before posting, so a failed run can never post it twice.
    seen.push(item.id);
    await env.STATE.put("seen", JSON.stringify(seen.slice(-MAX_SEEN)));
    await env.STATE.put("job", JSON.stringify(job));
  }

  let budget = POSTS_PER_RUN;
  let sent = 0;
  let removed = 0;
  const retryNext = [];

  const deliver = async (key, hook, tries) => {
    budget--;
    const result = await postToHook(env, deps, hook, job.embeds);
    if (result === "ok") sent++;
    else if (result === "gone") {
      await env.STATE.delete(key);
      removed++;
    } else if (result === "retry" && tries < MAX_RETRIES) {
      retryNext.push({ key, tries: tries + 1 });
    }
  };

  // Channels that failed last time go first.
  for (const entry of job.retry) {
    if (budget <= 0) {
      retryNext.push(entry);
      continue;
    }
    const stored = await env.STATE.getWithMetadata(entry.key);
    if (stored && stored.metadata) await deliver(entry.key, stored.metadata, entry.tries);
  }

  // Then the next batch of channels that have not had this story yet.
  if (!job.listed && budget > 0) {
    const options = { prefix: "hook:", limit: budget };
    if (job.cursor) options.cursor = job.cursor;
    const page = await env.STATE.list(options);
    for (const key of page.keys) {
      if (key.metadata) await deliver(key.name, key.metadata, 0);
    }
    if (page.list_complete) job.listed = true;
    else job.cursor = page.cursor;
  }

  job.retry = retryNext;
  const finished = job.listed && !job.retry.length;
  await saveJob(env, deps, finished ? null : job);

  return (
    (finished ? "Posted" : "Posting") +
    ' "' + job.title + '": ' + sent + " sent, " + removed + " removed, " +
    retryNext.length + " to retry" + (finished ? "." : "; more channels next run.")
  );
}

// ---------------------------------------------------------------- adding a channel

/** The Discord page where someone picks a server and channel. */
export function authorizeUrl(env, origin, state) {
  return (
    "https://discord.com/oauth2/authorize?response_type=code" +
    "&client_id=" + encodeURIComponent(env.DISCORD_CLIENT_ID) +
    "&scope=webhook.incoming" +
    "&state=" + encodeURIComponent(state) +
    "&redirect_uri=" + encodeURIComponent(origin + "/callback")
  );
}

/**
 * Discord sends people here after they pick a channel. Swaps the one-time
 * code for the channel's webhook, stores it and posts a welcome message.
 * Returns { status, title, message, retry } for the page to show.
 */
export async function handleCallback(request, env, deps) {
  if (request.error) {
    return {
      status: 200,
      title: "Nothing was added",
      message: "You cancelled, so Brutal Combo was not connected to any channel.",
      retry: true,
    };
  }
  if (!request.code || !request.state || request.state !== request.cookieState) {
    return {
      status: 400,
      title: "That link has expired",
      message: "Please start again from the Add to Discord button.",
      retry: true,
    };
  }
  if (!env.DISCORD_CLIENT_ID || !env.DISCORD_CLIENT_SECRET) {
    return {
      status: 500,
      title: "Setup isn't finished",
      message: "The site owner still needs to finish configuring this. Please try again later.",
    };
  }

  const form = {
    client_id: env.DISCORD_CLIENT_ID,
    client_secret: env.DISCORD_CLIENT_SECRET,
    grant_type: "authorization_code",
    code: request.code,
    redirect_uri: request.origin + "/callback",
  };
  const body = Object.keys(form)
    .map((key) => encodeURIComponent(key) + "=" + encodeURIComponent(form[key]))
    .join("&");

  let hook = null;
  try {
    const response = await deps.fetch(DISCORD_API + "/oauth2/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT },
      body,
    });
    if (response.ok) hook = (await response.json()).webhook;
  } catch (err) {
    hook = null;
  }
  if (!hook || !hook.id || !hook.token || !hook.channel_id) {
    return {
      status: 502,
      title: "Discord didn't finish the setup",
      message: "Nothing was added. Please try again from the Add to Discord button.",
      retry: true,
    };
  }

  // If this channel was connected before, drop the older webhook so each
  // story is posted once, not twice.
  const key = "hook:" + hook.channel_id;
  const previous = await env.STATE.getWithMetadata(key);
  if (previous && previous.metadata && previous.metadata.id !== hook.id) {
    try {
      await deps.fetch(
        DISCORD_API + "/webhooks/" + previous.metadata.id + "/" + previous.metadata.token,
        { method: "DELETE", headers: { "User-Agent": USER_AGENT } }
      );
    } catch (err) {
      // Not worth failing over; the old webhook may already be gone.
    }
  }
  await env.STATE.put(key, "", { metadata: { id: hook.id, token: hook.token } });
  await brandHook(env, deps, hook);

  const embeds = [welcomeEmbed()];
  try {
    const items = await fetchFeed(env, deps);
    if (items.length) embeds.push(await embedFor(items[0], deps));
  } catch (err) {
    // The welcome message still goes out without a sample story.
  }
  const result = await postToHook(env, deps, hook, embeds);

  return {
    status: 200,
    title: "You're all set",
    message:
      result === "ok"
        ? "Brutal Combo is connected. Check the channel you picked: a welcome message is waiting there, and new stories will follow on their own."
        : "Brutal Combo is connected. New stories will appear in the channel you picked.",
  };
}

// ---------------------------------------------------------------- pages

function page(title, bodyHtml) {
  return (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' +
    "<title>" + title + " · Brutal Combo for Discord</title><style>" +
    "body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;" +
    "background:#0f0f12;color:#f2f2f3;font:17px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}" +
    "main{max-width:30rem;padding:2rem 1.25rem;text-align:center}" +
    "h1{font-size:1.9rem;line-height:1.2;margin:0 0 .75rem}p{margin:.6rem 0;color:#c9c9cf}" +
    "a.button{display:inline-block;margin-top:1.25rem;padding:.8rem 1.5rem;border-radius:.5rem;" +
    "background:#5865f2;color:#fff;font-weight:600;text-decoration:none}" +
    "a.button:hover{background:#4752c4}small{display:block;margin-top:1.5rem;color:#8a8a93}" +
    "small a{color:#c9c9cf}</style></head><body><main>" + bodyHtml + "</main></body></html>"
  );
}

export function landingPage() {
  return page(
    "Add to Discord",
    "<h1>Brutal Combo for Discord</h1>" +
      "<p>Get new gaming stories from Brutal Combo posted in your server, automatically and for free.</p>" +
      "<p>Click the button, pick your server and the channel you want, and you're done.</p>" +
      '<a class="button" href="/install">Add to Discord</a>' +
      '<small>News from <a href="https://brutalcombo.com/">brutalcombo.com</a></small>'
  );
}

export function resultPage(result) {
  return page(
    result.title,
    "<h1>" + result.title + "</h1><p>" + result.message + "</p>" +
      (result.retry ? '<a class="button" href="/install">Add to Discord</a>' : "") +
      (result.status === 200 && !result.retry ? "<small>You can close this tab.</small>" : "")
  );
}
