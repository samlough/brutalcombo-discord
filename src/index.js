// Brutal Combo for Discord: the Cloudflare Worker.
//
//   /           a page with the Add to Discord button
//   /install    sends the visitor to Discord to pick a server and channel
//   /callback   where Discord sends them back; connects the channel
//
// A timer also runs the Worker every two minutes to post new stories.
// The logic lives in core.js.

import * as core from "./core.js";

const deps = {
  fetch: (url, options) => fetch(url, options),
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
};

const STATE_COOKIE = "bc_state";

function htmlResponse(html, status, extraHeaders) {
  return new Response(html, {
    status: status || 200,
    headers: Object.assign(
      {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
      },
      extraHeaders || {}
    ),
  });
}

function readCookie(request, name) {
  const header = request.headers.get("Cookie") || "";
  for (const part of header.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return rest.join("=");
  }
  return null;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", { status: 405 });
    }

    if (url.pathname === "/") {
      return htmlResponse(core.landingPage());
    }

    if (url.pathname === "/install") {
      // The random value comes back from Discord and must match the cookie,
      // which proves the visitor started the setup here themselves.
      const state = crypto.randomUUID();
      return new Response(null, {
        status: 302,
        headers: {
          Location: core.authorizeUrl(env, url.origin, state),
          "Set-Cookie": `${STATE_COOKIE}=${state}; Max-Age=900; Path=/; HttpOnly; Secure; SameSite=Lax`,
          "Cache-Control": "no-store",
        },
      });
    }

    if (url.pathname === "/callback") {
      const result = await core.handleCallback(
        {
          code: url.searchParams.get("code"),
          state: url.searchParams.get("state"),
          error: url.searchParams.get("error"),
          cookieState: readCookie(request, STATE_COOKIE),
          origin: url.origin,
        },
        env,
        deps
      );
      return htmlResponse(core.resultPage(result), result.status, {
        "Set-Cookie": `${STATE_COOKIE}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax`,
      });
    }

    return new Response("Not found", { status: 404 });
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil(
      core.runTick(env, deps).then(
        (summary) => console.log(summary),
        (err) => console.error("Run failed: " + (err && err.message))
      )
    );
  },
};
