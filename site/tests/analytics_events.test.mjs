/**
 * Behaviour of the docs-site PostHog snippet.
 *
 * Runs the partial itself (Node's vm plus a tiny DOM). Nothing here is loaded
 * by MkDocs, and the snippet is not modified to export helpers.
 *
 *   node --test site/tests/analytics_events.test.mjs
 *
 * After a docs build, the same checks run against the rendered homepage:
 *
 *   REQUIRE_BUILT_HTML=1 node --test site/tests/analytics_events.test.mjs
 *
 * With `mkdocs serve` already up, also prove the host gate holds in a browser:
 *
 *   REQUIRE_SERVE_CHECK=1 DOCS_URL=http://127.0.0.1:8765 node --test site/tests/analytics_events.test.mjs
 */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const partialPath = path.join(root, "site/overrides/partials/integrations/analytics/custom.html");
const homePath = path.join(root, "site/overrides/home.html");
const footerPath = path.join(root, "site/overrides/partials/footer.html");
const mkdocsPath = path.join(root, "site/mkdocs.yml");
const builtHome = path.join(root, "site/build/index.html");
const builtQuickstart = path.join(root, "site/build/getting-started/quickstart/index.html");

// The PostHog loader stub, hashed with its trailing newline. Keep the line
// in custom.html byte-for-byte; this fails if it is reformatted.
const LOADER_STUB_SHA256 = "4d17ad9065cf6d9d3af9cdce8fe03ee8803ba1b55a410077b9a53d29207c42da";

const ADDRESS = "kfir@praktical.dev";

function read(file) {
  return readFileSync(file, "utf8");
}

function extractScript(html) {
  const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((match) => match[1]);
  const script = blocks.find((block) => block.includes("posthog.init"));
  assert.ok(script, "analytics <script> containing posthog.init was not found");
  return script;
}

function analyticsConfig() {
  const yml = read(mkdocsPath);
  const match = yml.match(
    /analytics:\s*\n\s*provider:\s*custom\s*\n\s*host:\s*(\S+)\s*\n\s*key:\s*(\S+)/,
  );
  assert.ok(match, "extra.analytics host and key were not found in site/mkdocs.yml");
  return { host: match[1], key: match[2] };
}

function render(script, { host, key }) {
  const rendered = script
    .replaceAll("{{ config.extra.analytics.host }}", host)
    .replaceAll("{{ config.extra.analytics.key }}", key);
  assert.equal(rendered.includes("{{"), false, "unrendered Jinja left in the analytics script");
  return rendered;
}

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.attrs = new Map();
    this.classes = new Set();
    this.childNodes = [];
    this.parentNode = null;
    this._text = "";
  }

  setAttribute(name, value) {
    this.attrs.set(name, String(value));
    if (name === "class") {
      this.classes = new Set(String(value).split(/\s+/).filter(Boolean));
    }
  }

  getAttribute(name) {
    return this.attrs.has(name) ? this.attrs.get(name) : null;
  }

  append(child) {
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }

  insertBefore(node, ref) {
    node.parentNode = this;
    const index = this.childNodes.indexOf(ref);
    if (index === -1) this.childNodes.push(node);
    else this.childNodes.splice(index, 0, node);
  }

  get textContent() {
    if (this.childNodes.length) {
      return this.childNodes.map((child) => child.textContent ?? "").join("");
    }
    return this._text;
  }

  set textContent(value) {
    this._text = String(value);
    this.childNodes = [];
  }

  closest(selector) {
    for (let node = this; node; node = node.parentNode) {
      if (node instanceof El && matches(node, selector)) return node;
    }
    return null;
  }
}

function matches(el, selector) {
  return selector.split(",").some((part) => matchesOne(el, part.trim()));
}

function matchesOne(el, selector) {
  if (selector.startsWith(".")) return el.classes.has(selector.slice(1));
  const match = /^([A-Za-z][\w-]*)(?:\[([A-Za-z][\w-]*)\])?$/.exec(selector);
  if (!match) throw new Error(`unsupported selector ${selector}`);
  if (el.tagName !== match[1].toUpperCase()) return false;
  if (match[2] && !el.attrs.has(match[2])) return false;
  return true;
}

function collect(node, tag, out = []) {
  if (node.tagName === tag) out.push(node);
  for (const child of node.childNodes) collect(child, tag, out);
  return out;
}

function bomb(name) {
  return new Proxy(
    {},
    {
      get() {
        throw new Error(`${name} was read`);
      },
      set() {
        throw new Error(`${name} was written`);
      },
    },
  );
}

function boot(script, loc) {
  const listeners = [];
  const html = new El("html");
  const body = new El("body");
  html.append(body);
  body.append(new El("script"));

  const document = {
    documentElement: html,
    body,
    createElement(tag) {
      return new El(tag);
    },
    getElementsByTagName(tag) {
      return collect(html, String(tag).toUpperCase());
    },
    addEventListener(type, fn, capture) {
      listeners.push({ type, fn, capture });
    },
  };
  Object.defineProperty(document, "cookie", {
    configurable: true,
    get() {
      throw new Error("document.cookie was read");
    },
    set() {
      throw new Error("document.cookie was written");
    },
  });

  const location = {
    hostname: loc.hostname,
    pathname: loc.pathname ?? "/",
    search: loc.search ?? "",
    href: loc.href,
  };
  const sandbox = {
    document,
    location,
    URL,
    URLSearchParams,
    console,
    localStorage: bomb("localStorage"),
    sessionStorage: bomb("sessionStorage"),
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox, { filename: "custom.html" });
  assert.equal(typeof sandbox.__md_analytics, "function");
  sandbox.__md_analytics();
  return { sandbox, listeners, location, body };
}

function fire(listeners, target) {
  const click = listeners.filter((listener) => listener.type === "click");
  assert.equal(click.length, 1);
  assert.equal(click[0].capture, true);
  click[0].fn({ target });
}

function captured(sandbox) {
  const posthog = sandbox.posthog;
  if (!posthog) return [];
  return [...posthog].filter((entry) => Array.isArray(entry) && entry[0] === "capture");
}

function link(parent, href, text) {
  const anchor = new El("a");
  anchor.setAttribute("href", href);
  if (text instanceof El) anchor.append(text);
  else anchor.textContent = text;
  parent.append(anchor);
  return anchor;
}

function span(text) {
  const node = new El("span");
  node.textContent = text;
  return node;
}

const productionPage = {
  hostname: "gitgrit.dev",
  pathname: "/",
  search: "?utm_source=spec4test&utm_medium=qa&utm_campaign=docs&utm_term=standards&utm_content=hero&ref=ignore",
  href: "https://gitgrit.dev/?utm_source=spec4test&utm_medium=qa&utm_campaign=docs&utm_term=standards&utm_content=hero&ref=ignore",
};

function assertSnippet(script, { key }) {
  for (const hostname of ["127.0.0.1", "localhost", "www.gitgrit.dev", "staging.gitgrit.dev"]) {
    const blocked = boot(script, {
      hostname,
      href: `http://${hostname}/`,
    });
    assert.equal(blocked.listeners.length, 0, `${hostname} should not register a listener`);
    assert.equal(blocked.sandbox.posthog, undefined, `${hostname} should not load PostHog`);
  }

  const page = boot(script, productionPage);
  const posthog = page.sandbox.posthog;
  assert.ok(posthog, "production hostname should install the PostHog stub");
  const queued = posthog._i;
  assert.equal(queued.length, 1);
  const [initKey, options, name] = queued[0];
  assert.equal(initKey, key);
  assert.equal(name, "posthog");
  assert.equal(options.api_host, "https://eu.i.posthog.com");
  assert.equal(options.defaults, "2026-08-30");
  assert.equal(options.cookieless_mode, "always");
  assert.equal(options.disable_session_recording, true);
  assert.equal(typeof options.before_send, "function");
  assert.deepEqual(
    Object.keys(options).sort(),
    ["api_host", "before_send", "cookieless_mode", "defaults", "disable_session_recording"],
  );
  assert.equal(options.autocapture, undefined);

  const event = { event: "$pageview", properties: { distinct_id: "daily-hash" } };
  assert.equal(options.before_send(event), event);
  for (const hostname of ["127.0.0.1", "localhost", "www.gitgrit.dev", "staging.gitgrit.dev"]) {
    page.location.hostname = hostname;
    assert.equal(options.before_send(event), null, `before_send should drop ${hostname}`);
  }
  page.location.hostname = "gitgrit.dev";
  assert.equal(options.before_send(event), event);

  const loaded = collect(page.body, "SCRIPT").find((node) => node.src);
  assert.equal(loaded.src, "https://eu-assets.i.posthog.com/static/array.js");

  const header = new El("header");
  const main = new El("main");
  const hero = new El("section");
  hero.setAttribute("class", "gg-hero");
  const article = new El("article");
  article.setAttribute("class", "md-content");
  const footer = new El("footer");
  const other = new El("div");
  main.append(hero);
  main.append(article);
  page.body.append(header);
  page.body.append(main);
  page.body.append(footer);
  page.body.append(other);

  const letsTalk = link(hero, `mailto:${ADDRESS}?subject=GitGrit`, "Let's talk");
  const getStarted = link(hero, "getting-started/quickstart/", "Get started →");
  const signIn = link(footer, "https://app.gitgrit.dev", "Sign in");
  const github = link(footer, "https://github.com/kfirzvi-com/gitgrit", "GitHub");
  const docs = link(header, "/getting-started/quickstart/", "Docs");
  const security = link(
    footer,
    "https://github.com/kfirzvi-com/gitgrit/blob/main/SECURITY.md",
    "Security",
  );

  fire(page.listeners, letsTalk);
  fire(page.listeners, getStarted);
  fire(page.listeners, signIn);

  const events = captured(page.sandbox);
  assert.equal(events.length, 3);
  const [contact, started, app] = events.map((entry) => ({
    name: entry[1],
    props: entry[2],
    options: entry[3],
  }));

  assert.equal(contact.name, "contact_clicked");
  assert.equal(contact.props.page_path, "/");
  assert.equal(contact.props.cta_label, "Let's talk");
  assert.equal(contact.props.cta_href, "mailto:?subject=GitGrit");
  assert.equal(contact.props.cta_href.includes("@"), false);
  assert.equal(contact.props.cta_href.includes(ADDRESS), false);
  assert.equal(contact.props.cta_location, "hero");
  assert.equal(contact.props.utm_source, "spec4test");
  assert.equal(contact.props.utm_medium, "qa");
  assert.equal(contact.props.utm_campaign, "docs");
  assert.equal(contact.props.utm_term, "standards");
  assert.equal(contact.props.utm_content, "hero");
  assert.equal("ref" in contact.props, false);
  // The options object is created inside the snippet's vm, so compare fields.
  assert.deepEqual(Object.keys(contact.options), ["transport"]);
  assert.equal(contact.options.transport, "sendBeacon");

  assert.equal(started.name, "get_started_clicked");
  assert.equal(started.props.cta_label, "Get started →");
  assert.equal(started.props.cta_location, "hero");
  assert.equal(started.props.cta_href, "https://gitgrit.dev/getting-started/quickstart/");
  assert.equal(started.props.page_path, "/");
  assert.equal(started.props.utm_source, "spec4test");

  assert.equal(app.name, "app_clicked");
  assert.equal(app.props.cta_label, "Sign in");
  assert.equal(app.props.cta_location, "footer");
  assert.equal(app.props.cta_href, "https://app.gitgrit.dev/");
  assert.equal(app.options.transport, "sendBeacon");

  fire(page.listeners, github);
  fire(page.listeners, security);
  fire(page.listeners, docs);
  const more = captured(page.sandbox).slice(3);
  assert.deepEqual(
    more.map((entry) => [entry[1], entry[2].cta_location, entry[2].cta_href, entry[2].cta_label]),
    [
      ["github_clicked", "footer", "https://github.com/kfirzvi-com/gitgrit", "GitHub"],
      [
        "github_clicked",
        "footer",
        "https://github.com/kfirzvi-com/gitgrit/blob/main/SECURITY.md",
        "Security",
      ],
      ["get_started_clicked", "header", "https://gitgrit.dev/getting-started/quickstart/", "Docs"],
    ],
  );

  const encoded = link(
    article,
    `mailto:${ADDRESS}?subject=GitGrit%3A%20end-of-life%20runtimes&body=reply%20to%20${encodeURIComponent(ADDRESS)}`,
    "  Let's\n   talk  ",
  );
  fire(page.listeners, encoded);
  const redacted = captured(page.sandbox).at(-1);
  assert.equal(redacted[1], "contact_clicked");
  assert.equal(redacted[2].cta_href, "mailto:?subject=GitGrit: end-of-life runtimes");
  assert.equal(redacted[2].cta_href.includes("@"), false);
  assert.equal(redacted[2].cta_href.includes("praktical"), false);
  assert.equal(redacted[2].cta_label, "Let's talk");
  assert.equal(redacted[2].cta_location, "content");

  const bare = link(article, `mailto:${ADDRESS}`, span(ADDRESS));
  fire(page.listeners, bare.childNodes[0]);
  const bareEvent = captured(page.sandbox).at(-1);
  assert.equal(bareEvent[1], "contact_clicked");
  assert.equal(bareEvent[2].cta_href, "mailto:");
  assert.equal(bareEvent[2].cta_href.includes("@"), false);
  assert.equal(bareEvent[2].cta_label, ADDRESS);
  assert.equal(bareEvent[2].cta_location, "content");

  const appDeep = link(
    article,
    "https://app.gitgrit.dev/projects/1/?tab=standards#runs",
    "Open project",
  );
  fire(page.listeners, appDeep);
  assert.equal(captured(page.sandbox).at(-1)[2].cta_href, "https://app.gitgrit.dev/projects/1/");

  const demoHeader = link(header, "https://cal.com/gitgrit-demo/30min", "Book a demo");
  const demoHero = link(hero, "https://cal.com/gitgrit-demo/30min?month=2026-12", "Book a demo");
  fire(page.listeners, demoHeader);
  fire(page.listeners, demoHero);
  assert.deepEqual(
    captured(page.sandbox).slice(-2).map((entry) => [entry[1], entry[2].cta_location, entry[2].cta_href, entry[2].cta_label]),
    [
      ["demo_clicked", "header", "https://cal.com/gitgrit-demo/30min", "Book a demo"],
      ["demo_clicked", "hero", "https://cal.com/gitgrit-demo/30min", "Book a demo"],
    ],
  );

  const ignored = [
    ["https://github.com/kfirzvi-com/other", "Other repo"],
    ["https://example.com/kfirzvi-com/gitgrit", "Mirror"],
    ["https://app.gitgrit.dev.evil.example/", "Lookalike"],
    ["https://cal.com/someone-else/30min", "Other booking page"],
    ["https://cal.com.evil.example/gitgrit-demo/30min", "Booking lookalike"],
    ["https://staging.gitgrit.dev/getting-started/quickstart/", "Staging quickstart"],
    ["/getting-started/quickstart/install/", "Deeper quickstart"],
    ["/features/analytics/", "Analytics"],
    ["javascript:void(0)", "Script"],
    ["http://[", "Broken"],
  ];
  const before = captured(page.sandbox).length;
  for (const [href, text] of ignored) {
    fire(page.listeners, link(other, href, text));
  }
  fire(page.listeners, { closest: undefined });
  fire(page.listeners, null);
  assert.equal(captured(page.sandbox).length, before);

  const noSlash = link(article, "/getting-started/quickstart", "Quick Start");
  page.location.pathname = "/legal/cookies/";
  fire(page.listeners, noSlash);
  const quick = captured(page.sandbox).at(-1);
  assert.equal(quick[1], "get_started_clicked");
  assert.equal(quick[2].page_path, "/legal/cookies/");
  assert.equal(quick[2].cta_href, "https://gitgrit.dev/getting-started/quickstart");
  assert.equal(quick[2].cta_location, "content");

  const padded = link(hero, `mailto:${ADDRESS}?subject=GitGrit`, `  ${"y".repeat(100)}  `);
  fire(page.listeners, padded);
  const label = captured(page.sandbox).at(-1)[2].cta_label;
  assert.equal(label, "y".repeat(80));
  assert.equal(label.includes(" "), false);

  const headerHero = new El("div");
  headerHero.setAttribute("class", "gg-hero");
  header.append(headerHero);
  const nested = link(headerHero, "https://app.gitgrit.dev/login", "Sign in");
  fire(page.listeners, nested);
  assert.equal(captured(page.sandbox).at(-1)[2].cta_location, "header");

  const plain = boot(script, {
    hostname: "gitgrit.dev",
    pathname: "/use-cases/",
    search: "",
    href: "https://gitgrit.dev/use-cases/",
  });
  const content = new El("article");
  plain.body.append(content);
  fire(plain.listeners, link(content, "https://app.gitgrit.dev", "  Sign   in \n"));
  const plainEvent = captured(plain.sandbox)[0];
  assert.equal(plainEvent[2].cta_label, "Sign in");
  assert.equal(plainEvent[2].page_path, "/use-cases/");
  for (const keyName of ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"]) {
    assert.equal(Object.hasOwn(plainEvent[2], keyName), false);
  }

  const partialUtm = boot(script, {
    hostname: "gitgrit.dev",
    pathname: "/",
    search: "?utm_source=&utm_medium=qa",
    href: "https://gitgrit.dev/?utm_source=&utm_medium=qa",
  });
  const box = new El("div");
  partialUtm.body.append(box);
  fire(partialUtm.listeners, link(box, "https://github.com/kfirzvi-com/gitgrit/", "GitHub"));
  const utmProps = captured(partialUtm.sandbox)[0][2];
  assert.equal(utmProps.cta_location, "other");
  assert.equal(utmProps.cta_href, "https://github.com/kfirzvi-com/gitgrit/");
  assert.equal(Object.hasOwn(utmProps, "utm_source"), false);
  assert.equal(utmProps.utm_medium, "qa");
}

const partial = read(partialPath);
const sourceScript = extractScript(partial);
const config = analyticsConfig();

test("loader stub, cookieless init, and storage ban stay intact", () => {
  const stub = sourceScript.split("\n").find((line) => line.includes("!function(t,e)"));
  assert.ok(stub);
  assert.equal(
    createHash("sha256").update(`${stub}\n`).digest("hex"),
    LOADER_STUB_SHA256,
  );
  assert.equal(sourceScript.split("!function(t,e)").length, 2);
  assert.equal([...sourceScript.matchAll(/\{\{ config\.extra\.analytics\.host \}\}/g)].length, 2);
  assert.equal([...sourceScript.matchAll(/\{\{ config\.extra\.analytics\.key \}\}/g)].length, 1);
  assert.match(sourceScript, /cookieless_mode: "always"/);
  assert.match(sourceScript, /disable_session_recording: true/);
  assert.doesNotMatch(sourceScript, /localStorage|sessionStorage|document\.cookie|\.cookie\b|identify\(/);
  assert.doesNotMatch(sourceScript, /autocapture:\s*false/);
  assert.equal(config.host, "gitgrit.dev");
});

test("navigation.instant stays off and .gg-hero wraps the homepage CTAs", () => {
  const yml = read(mkdocsPath);
  assert.doesNotMatch(yml, /^\s*-\s*navigation\.instant\b/m);

  const home = read(homePath);
  const hero = home.match(/<section class="gg-hero">[\s\S]*?<\/section>/);
  assert.ok(hero, "homepage hero wrapper is <section class=\"gg-hero\">");
  assert.match(hero[0], /href="https:\/\/cal\.com\/gitgrit-demo\/30min" data-cal-link="gitgrit-demo\/30min"/);
  assert.match(hero[0], /Book a demo/);
  assert.match(hero[0], /href="https:\/\/app\.gitgrit\.dev" class="gg-btn gg-btn--ghost">Get started/);
  assert.match(hero[0], /Get started/);

  const footer = read(footerPath);
  assert.match(footer, /<footer class="md-footer">/);
  assert.match(footer, /<a href="https:\/\/app\.gitgrit\.dev">Sign in<\/a>/);
  assert.match(footer, /<a href="https:\/\/github\.com\/kfirzvi-com\/gitgrit"/);
});

test("classify, where, and mailto redaction on the rendered snippet", () => {
  assertSnippet(render(sourceScript, config), config);
});

test("built HTML renders the production host and the same snippet", (t) => {
  if (!existsSync(builtHome) || !existsSync(builtQuickstart)) {
    if (process.env.REQUIRE_BUILT_HTML) {
      assert.fail(`missing built docs under site/build (looked for ${builtHome})`);
    }
    t.skip("build the site first: uv run --project site mkdocs build -f site/mkdocs.yml -d build");
    return;
  }

  for (const file of [builtHome, builtQuickstart]) {
    const html = read(file);
    const script = extractScript(html);
    assert.match(script, /location\.hostname !== "gitgrit\.dev"/);
    assert.match(script, /location\.hostname === "gitgrit\.dev"/);
    assert.match(script, new RegExp(config.key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    assert.doesNotMatch(script, /\{\{|config\.extra\.analytics/);
    assert.doesNotMatch(script, /@praktical\.dev|localStorage|sessionStorage/);
    assert.match(html, /<section class="gg-hero">|Sign in|Quick Start/);
    if (file === builtHome) {
      assert.match(html, /<section class="gg-hero">[\s\S]*Book a demo[\s\S]*Get started/);
      assert.match(html, /href="https:\/\/cal\.com\/gitgrit-demo\/30min"/);
      assert.match(html, /href="https:\/\/app\.gitgrit\.dev"/);
      assertSnippet(script, config);
    } else {
      assert.equal(script, extractScript(read(builtHome)));
    }
  }
});

test("mkdocs serve on 127.0.0.1 does not contact PostHog", async (t) => {
  if (process.env.REQUIRE_SERVE_CHECK !== "1") {
    t.skip("set REQUIRE_SERVE_CHECK=1 and DOCS_URL to a running mkdocs serve");
    return;
  }
  const docsUrl = process.env.DOCS_URL || "http://127.0.0.1:8765";
  const response = await fetch(docsUrl);
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /location\.hostname !== "gitgrit\.dev"/);
  assert.match(html, /"undefined"!=typeof __md_analytics&&__md_analytics\(\)/);

  const requests = await browse(docsUrl);
  const posthog = requests.filter((url) => /posthog\.com/i.test(url));
  assert.deepEqual(posthog, [], `unexpected PostHog requests:\n${posthog.join("\n")}`);
  assert.equal(requests.some((url) => url.startsWith(docsUrl)), true);
});

async function browse(docsUrl) {
  const port = 9229;
  const userData = mkdtempSync(path.join(tmpdir(), "gg-docs-chrome-"));
  const chrome = spawn(
    "google-chrome",
    [
      "--headless=new",
      "--disable-gpu",
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--no-first-run",
      "--no-default-browser-check",
      `--user-data-dir=${userData}`,
      `--remote-debugging-port=${port}`,
      "about:blank",
    ],
    { stdio: "ignore" },
  );

  try {
    const version = await waitJson(`http://127.0.0.1:${port}/json/version`);
    const browser = new WebSocket(version.webSocketDebuggerUrl);
    await opened(browser);
    const browserCdp = cdp(browser);
    const { targetId } = await browserCdp.send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await browserCdp.send("Target.attachToTarget", { targetId, flatten: true });
    // Flattened sessions deliver events on the browser socket with sessionId.
    const requests = [];
    const waiters = new Map();
    let nextId = 0;
    let loadFired = null;
    let fetchError = null;
    const loadDone = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("page load timed out")), 20000);
      loadFired = () => {
        clearTimeout(timer);
        resolve();
      };
    });
    browser.addEventListener("message", (ev) => {
      const message = JSON.parse(ev.data);
      if (message.sessionId !== sessionId) return;
      if (message.id && waiters.has(message.id)) {
        waiters.get(message.id)(message);
        waiters.delete(message.id);
        return;
      }
      if (message.method === "Network.requestWillBeSent") {
        requests.push(message.params.request.url);
      }
      if (message.method === "Fetch.requestPaused") {
        handlePaused(message.params).catch((error) => {
          fetchError = error;
        });
      }
      if (message.method === "Page.loadEventFired") loadFired();
    });
    function send(method, params = {}) {
      const id = ++nextId;
      return new Promise((resolve, reject) => {
        waiters.set(id, (message) => {
          if (message.error) reject(new Error(`${method}: ${JSON.stringify(message.error)}`));
          else resolve(message.result);
        });
        browser.send(JSON.stringify({ id, sessionId, method, params }));
      });
    }

    // Function declarations don't go through a window setter, so count the
    // call by inserting one statement at the top of __md_analytics. This is
    // the served page only; the snippet in the repo is unchanged.
    async function handlePaused(params) {
      const requestId = params.requestId;
      try {
        if (params.resourceType !== "Document") {
          await send("Fetch.continueRequest", { requestId });
          return;
        }
        const response = await send("Fetch.getResponseBody", { requestId });
        const text = response.base64Encoded
          ? Buffer.from(response.body, "base64").toString("utf8")
          : response.body;
        const needle = "function __md_analytics() {";
        if (!text.includes(needle)) {
          await send("Fetch.continueRequest", { requestId });
          return;
        }
        const body = text.replace(
          needle,
          `${needle}window.__mdAnalyticsCalled=(window.__mdAnalyticsCalled||0)+1;`,
        );
        const headers = (params.responseHeaders || []).filter(
          (header) => !["content-encoding", "content-length"].includes(header.name.toLowerCase()),
        );
        await send("Fetch.fulfillRequest", {
          requestId,
          responseCode: params.responseStatusCode || 200,
          responseHeaders: headers,
          body: Buffer.from(body).toString("base64"),
        });
      } catch (error) {
        await send("Fetch.continueRequest", { requestId }).catch(() => {});
        throw error;
      }
    }

    await send("Network.enable");
    await send("Page.enable");
    await send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Response" }] });
    await send("Page.navigate", { url: docsUrl });
    await loadDone;
    if (fetchError) throw fetchError;

    const result = await send("Runtime.evaluate", {
      expression: `(() => {
        document.querySelectorAll("a[href]").forEach((a) => {
          a.addEventListener("click", (event) => event.preventDefault(), true);
        });
        const hero = document.querySelector(".gg-hero");
        const talk = [...hero.querySelectorAll("a")].find((a) => a.textContent.includes("Book a demo"));
        const start = [...hero.querySelectorAll("a")].find((a) => a.textContent.includes("Get started"));
        const signIn = [...document.querySelectorAll("footer a")].find((a) => a.textContent.trim() === "Sign in");
        talk.click();
        start.click();
        signIn.click();
        return {
          called: window.__mdAnalyticsCalled === 1,
          hostname: location.hostname,
          posthog: typeof window.posthog,
          labels: [talk.textContent.trim(), start.textContent.trim(), signIn.textContent.trim()],
        };
      })()`,
      returnByValue: true,
    });
    assert.equal(result.exceptionDetails, undefined);
    assert.deepEqual(result.result.value, {
      called: true,
      hostname: "127.0.0.1",
      posthog: "undefined",
      labels: ["Book a demo", "Get started →", "Sign in"],
    });
    await new Promise((resolve) => setTimeout(resolve, 500));
    return requests;
  } finally {
    chrome.kill("SIGKILL");
  }
}

function cdp(ws) {
  let nextId = 0;
  const waiters = new Map();
  ws.addEventListener("message", (ev) => {
    const message = JSON.parse(ev.data);
    if (message.sessionId) return;
    if (message.id && waiters.has(message.id)) {
      waiters.get(message.id)(message);
      waiters.delete(message.id);
    }
  });
  return {
    send(method, params = {}) {
      const id = ++nextId;
      return new Promise((resolve, reject) => {
        waiters.set(id, (message) => {
          if (message.error) reject(new Error(`${method}: ${JSON.stringify(message.error)}`));
          else resolve(message.result);
        });
        ws.send(JSON.stringify({ id, method, params }));
      });
    },
  };
}

function opened(ws) {
  return new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
}

async function waitJson(url) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < 10000) {
    try {
      const response = await fetch(url);
      if (response.ok) return response.json();
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw lastError || new Error(`timed out waiting for ${url}`);
}
