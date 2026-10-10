// Reads app.config.json, checks the EduSignal web app URL is real and reachable,
// then writes capacitor.config.json and www/config.js. Run before every `cap sync`.
import { readFileSync, writeFileSync } from "node:fs";

const root = new URL("..", import.meta.url);
const cfg = JSON.parse(readFileSync(new URL("app.config.json", root), "utf8"));

function fail(msg) {
  console.error(`\n[configure] ${msg}\n`);
  process.exit(1);
}

if (!cfg.appUrl) fail('Set "appUrl" in app.config.json to your deployed Streamlit link, e.g. https://<name>.streamlit.app');

let url;
try {
  url = new URL(cfg.appUrl);
} catch {
  fail(`"${cfg.appUrl}" is not a valid URL.`);
}
if (url.protocol !== "https:") fail("appUrl must start with https://");

// Reachability check (Streamlit Cloud answers with the app or a redirect to its sign-in/wake-up page).
if (!process.argv.includes("--offline")) {
  try {
    const res = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(20000) });
    if (res.status >= 400) fail(`${url.href} answered HTTP ${res.status}. Check the link.`);
    console.log(`[configure] ${url.href} reachable (HTTP ${res.status}).`);
  } catch (e) {
    fail(`Could not reach ${url.href}: ${e.message}. Use --offline to skip this check.`);
  }
}

const capConfig = {
  appId: cfg.appId,
  appName: cfg.appName,
  webDir: "www",
  server: {
    url: url.href,
    // Streamlit Community Cloud routes through share.streamlit.io for sign-in and wake-up.
    allowNavigation: [url.hostname, "*.streamlit.app", "share.streamlit.io", "*.streamlit.io"],
    errorPath: "error.html",
  },
  android: { allowMixedContent: false },
  ios: { contentInset: "automatic" },
};

writeFileSync(new URL("capacitor.config.json", root), JSON.stringify(capConfig, null, 2) + "\n");

// The local pages carry the URL inline: Capacitor serves error.html without its sibling files.
const attr = url.href.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
for (const page of ["www/error.html", "www/index.html"]) {
  const file = new URL(page, root);
  const html = readFileSync(file, "utf8");
  const next = html.replace(/<meta name="edusignal-url" content="[^"]*">/, `<meta name="edusignal-url" content="${attr}">`);
  if (next === html && !html.includes(`content="${attr}"`)) fail(`${page} has no <meta name="edusignal-url"> tag.`);
  writeFileSync(file, next);
}
console.log("[configure] wrote capacitor.config.json, www/error.html and www/index.html");
