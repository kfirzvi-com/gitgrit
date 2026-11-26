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
    /analytics:\s*\n\s*provider:\s*custom\s*\n\s*host:\s*(\S+)\s*\n\s*key:\s*(\S+)\s*\n\s*api_host:\s*(\S+)\s*\n\s*consent_version:\s*"([^"]+)"/,
  );
  assert.ok(match, "extra.analytics host, key, api_host and consent_version were not found in site/mkdocs.yml");
  return { host: match[1], key: match[2], apiHost: match[3], consentVersion: match[4] };
}

function render(script, { host, key, apiHost, consentVersion }) {
  const rendered = script
    .replaceAll("{{ config.extra.analytics.host }}", host)
    .replaceAll("{{ config.extra.analytics.key }}", key)
    .replaceAll("{{ config.extra.analytics.api_host }}", apiHost)
    .replaceAll("{{ config.extra.analytics.consent_version }}", consentVersion);
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

  removeAttribute(name) {
    this.attrs.delete(name);
  }

  get dataset() {
    const data = {};
    for (const [name, value] of this.attrs) {
      if (name.startsWith("data-")) {
        data[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
      }
    }
    return data;
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

// tag, .class and [attr] parts, compounded: a[href], .a.b[data-x], [data-plan]
function matchesOne(el, selector) {
  const match = /^([A-Za-z][\w-]*)?((?:\.[\w-]+)*)((?:\[[A-Za-z][\w-]*\])*)$/.exec(selector);
  if (!match || !selector) throw new Error(`unsupported selector ${selector}`);
  if (match[1] && el.tagName !== match[1].toUpperCase()) return false;
  for (const cls of match[2].split(".").filter(Boolean)) {
    if (!el.classes.has(cls)) return false;
  }
  for (const attr of match[3].match(/[\w-]+/g) ?? []) {
    if (!el.attrs.has(attr)) return false;
  }
  return true;
}

function find(node, selector) {
  if (node instanceof El && matches(node, selector)) return node;
  for (const child of node.childNodes) {
    const hit = find(child, selector);
    if (hit) return hit;
  }
  return null;
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

// localStorage that only lets the consent record through, plus removal of
// PostHog's own keys (purge).
const POSTHOG_KEYS = (key) => [`ph_${key}_posthog`, `ph_${key}_posthog__flags`, `__ph_opt_in_out_${key}`];
function consentStorage(initial) {
  const data = new Map(initial === undefined ? [] : [["gg_consent", JSON.stringify(initial)]]);
  const writes = [];
  const removed = [];
  return {
    writes,
    removed,
    removeItem(key) {
      assert.ok(POSTHOG_KEYS(config.key).includes(key), `localStorage.removeItem(${key})`);
      removed.push(key);
      data.delete(key);
    },
    get record() {
      return data.has("gg_consent") ? JSON.parse(data.get("gg_consent")) : null;
    },
    getItem(key) {
      assert.equal(key, "gg_consent", `localStorage.getItem(${key})`);
      return data.has(key) ? data.get(key) : null;
    },
    setItem(key, value) {
      assert.equal(key, "gg_consent", `localStorage.setItem(${key})`);
      writes.push(key);
      data.set(key, String(value));
    },
  };
}

// A valid "accepted" record: PostHog loads on page load.
function accepted() {
  return consentStorage({ v: config.consentVersion, choice: "accepted", at: Date.now() });
}

// storage: a consentStorage, a bomb, or undefined (production: accepted; elsewhere: bomb).
// cookie: what document.cookie reads; writes are recorded, and must expire a PostHog cookie.
function boot(script, loc, setup, storage, cookie) {
  if (storage === undefined) storage = loc.hostname === "gitgrit.dev" ? accepted() : bomb("localStorage");
  const cookieWrites = [];
  const listeners = [];
  const html = new El("html");
  const body = new El("body");
  html.append(body);
  body.append(new El("script"));
  if (setup) setup(body);

  const document = {
    documentElement: html,
    body,
    createElement(tag) {
      return new El(tag);
    },
    getElementsByTagName(tag) {
      return collect(html, String(tag).toUpperCase());
    },
    readyState: "complete",
    querySelector(selector) {
      return find(html, selector);
    },
    getElementById() {
      return null;
    },
    addEventListener(type, fn, capture) {
      listeners.push({ type, fn, capture });
    },
  };
  Object.defineProperty(document, "cookie", {
    configurable: true,
    get() {
      if (cookie === undefined) throw new Error("document.cookie was read");
      return cookie;
    },
    set(value) {
      assert.match(value, new RegExp(`^ph_${config.key}_posthog(_cpm)?=; Max-Age=0; path=/; SameSite=Lax$`));
      cookieWrites.push(value);
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
    localStorage: storage,
    sessionStorage: bomb("sessionStorage"),
    Date,
    JSON,
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox, { filename: "custom.html" });
  assert.equal(typeof sandbox.__md_analytics, "function");
  sandbox.__md_analytics();
  return { sandbox, listeners, location, body, cookieWrites };
}

function fire(listeners, target) {
  const click = listeners.filter((listener) => listener.type === "click" && listener.capture === true);
  assert.equal(click.length, 1);
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
  assert.equal(options.api_host, "https://e.gitgrit.dev");
  assert.equal(options.ui_host, "https://eu.posthog.com");
  assert.equal(options.defaults, "2026-08-30");
  assert.equal(options.cross_subdomain_cookie, false);
  assert.equal(options.enable_heatmaps, true);
  assert.equal(options.session_recording.maskAllInputs, true);
  assert.equal(typeof options.before_send, "function");
  assert.deepEqual(
    Object.keys(options).sort(),
    ["api_host", "before_send", "cross_subdomain_cookie", "defaults", "enable_heatmaps", "session_recording", "ui_host"],
  );
  assert.equal(options.cookieless_mode, undefined, "no tracking of any kind before consent");
  assert.equal(options.disable_session_recording, undefined);
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
  assert.equal(loaded.src, "https://e.gitgrit.dev/static/array.js");

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

test("loader stub, consent-gated init, and storage limits stay intact", () => {
  const stub = sourceScript.split("\n").find((line) => line.includes("!function(t,e)"));
  assert.ok(stub);
  assert.equal(
    createHash("sha256").update(`${stub}\n`).digest("hex"),
    LOADER_STUB_SHA256,
  );
  assert.equal(sourceScript.split("!function(t,e)").length, 2);
  assert.equal([...sourceScript.matchAll(/\{\{ config\.extra\.analytics\.host \}\}/g)].length, 2);
  assert.equal([...sourceScript.matchAll(/\{\{ config\.extra\.analytics\.key \}\}/g)].length, 3);
  assert.equal([...sourceScript.matchAll(/\{\{ config\.extra\.analytics\.api_host \}\}/g)].length, 1);
  assert.equal([...sourceScript.matchAll(/\{\{ config\.extra\.analytics\.consent_version \}\}/g)].length, 1);
  assert.doesNotMatch(sourceScript, /cookieless_mode|opt_out_capturing_by_default/);
  assert.match(sourceScript, /maskAllInputs: true/);
  // Our own storage: the consent record, and removing PostHog's keys.
  assert.deepEqual(
    [...sourceScript.matchAll(/localStorage\.(\w+)\(([^,)]*)/g)].map((m) => `${m[1]}(${m[2]})`),
    ["getItem(KEY)", "removeItem(name)", "setItem(KEY)"],
  );
  assert.match(sourceScript, /var KEY = "gg_consent";/);
  // The only cookie we write is an expiry for PostHog's.
  assert.deepEqual(
    [...sourceScript.matchAll(/document\.cookie = (.+);$/gm)].map((m) => m[1]),
    ['name + "=; Max-Age=0; path=/; SameSite=Lax"'],
  );
  assert.doesNotMatch(sourceScript, /sessionStorage|identify\(/);
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

test("pricing page: CTA clicks carry plan, period and currency; toggles are captured", () => {
  const els = {};
  const page = boot(
    render(sourceScript, config),
    { hostname: "gitgrit.dev", pathname: "/pricing/", href: "https://gitgrit.dev/pricing/" },
    (body) => {
      const article = body.append(new El("article"));
      article.setAttribute("class", "md-content");
      const toggles = article.append(new El("div"));
      els.annual = toggles.append(new El("button"));
      els.annual.setAttribute("class", "gg-pr-toggle__btn is-active");
      els.annual.setAttribute("data-period", "annual");
      els.monthly = toggles.append(new El("button"));
      els.monthly.setAttribute("class", "gg-pr-toggle__btn");
      els.monthly.setAttribute("data-period", "monthly");
      els.eur = toggles.append(new El("button"));
      els.eur.setAttribute("class", "gg-pr-toggle__btn is-active");
      els.eur.setAttribute("data-currency", "eur");
      const grid = article.append(new El("div"));
      grid.setAttribute("class", "gg-pr-grid");
      const team = grid.append(new El("div"));
      team.setAttribute("data-plan", "team");
      els.trial = link(team, "https://app.gitgrit.dev", "Start 14-day trial");
      els.docs = link(article, "/getting-started/quickstart/", "Quick Start");
    },
  );
  // No IntersectionObserver in the sandbox: the CTA listener plus the toggle listener.
  const clicks = page.listeners.filter((l) => l.type === "click");
  assert.equal(clicks.length, 2);
  const clickAll = (target) => clicks.forEach((l) => l.fn({ target }));

  clickAll(els.trial);
  clickAll(els.docs);
  clickAll(els.monthly);
  // JSON round trip: objects from the vm context have that context's prototypes.
  const events = JSON.parse(JSON.stringify(captured(page.sandbox).map(([, name, props]) => [name, props])));
  assert.deepEqual(events, [
    ["app_clicked", {
      page_path: "/pricing/",
      cta_label: "Start 14-day trial",
      cta_href: "https://app.gitgrit.dev/",
      cta_location: "pricing_plan",
      plan: "team",
      billing_period: "annual",
      currency: "eur",
    }],
    ["get_started_clicked", {
      page_path: "/pricing/",
      cta_label: "Quick Start",
      cta_href: "https://gitgrit.dev/getting-started/quickstart/",
      cta_location: "content",
      billing_period: "annual",
      currency: "eur",
    }],
    ["pricing_period_toggled", { period: "monthly", currency: "eur" }],
  ]);
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
    assert.doesNotMatch(script, /@praktical\.dev|sessionStorage/);
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

// ── Consent banner ──────────────────────────────────────────────────────

function withBanner(body) {
  const banner = new El("div");
  banner.setAttribute("class", "gg-consent");
  banner.setAttribute("hidden", "");
  const reject = new El("button");
  reject.setAttribute("data-gg-consent", "reject");
  const accept = new El("button");
  accept.setAttribute("data-gg-consent", "accept");
  banner.append(reject);
  banner.append(accept);
  const settingsItem = new El("li");
  settingsItem.setAttribute("data-gg-consent-open", "");
  settingsItem.setAttribute("hidden", "");
  const settings = new El("button");
  settings.setAttribute("data-gg-consent", "open");
  settingsItem.append(settings);
  body.append(banner);
  body.append(settingsItem);
}

function consentPage(stored, cookie = "") {
  const storage = consentStorage(stored);
  const page = boot(render(sourceScript, config), productionPage, withBanner, storage, cookie);
  const banner = find(page.body, ".gg-consent");
  const settingsItem = find(page.body, "[data-gg-consent-open]");
  const button = (action) =>
    banner.childNodes.find((b) => b.getAttribute("data-gg-consent") === action) ??
    settingsItem.childNodes[0];
  const click = (target) => {
    const consent = page.listeners.filter((l) => l.type === "click" && !l.capture);
    assert.equal(consent.length, 1);
    consent[0].fn({ target });
  };
  const calls = (name) => [...(page.sandbox.posthog ?? [])].filter((e) => Array.isArray(e) && e[0] === name);
  return { page, storage, banner, settingsItem, button, click, calls };
}

const DAY = 24 * 60 * 60 * 1000;

test("consent: no choice yet shows the banner and loads nothing", () => {
  const c = consentPage();
  assert.equal(c.banner.getAttribute("hidden"), null);
  assert.equal(c.settingsItem.getAttribute("hidden"), null, "Cookie settings is shown in production");
  assert.equal(c.page.sandbox.posthog, undefined, "PostHog must not load before consent");
  assert.equal(collect(c.page.body, "SCRIPT").some((n) => n.src), false, "no script fetched");
  assert.deepEqual(c.storage.writes, []);
  assert.equal(c.page.listeners.filter((l) => l.capture === true).length, 0, "no tracking listener");
});

test("consent: Accept stores the choice, loads PostHog, opts in, and starts tracking", () => {
  const c = consentPage();
  c.click(c.button("accept"));
  assert.equal(c.storage.record.choice, "accepted");
  assert.equal(c.storage.record.v, config.consentVersion);
  assert.equal(typeof c.storage.record.at, "number");
  assert.ok(c.page.sandbox.posthog, "PostHog loads on Accept");
  assert.equal(c.page.sandbox.posthog._i.length, 1);
  assert.equal(c.calls("opt_in_capturing").length, 1);
  assert.equal(c.banner.getAttribute("hidden"), "");
  assert.equal(c.page.listeners.filter((l) => l.capture === true).length, 1, "tracking listener registered");
});

test("consent: Reject stores the choice, loads nothing, and clears PostHog's storage", () => {
  const c = consentPage(undefined, `ph_${config.key}_posthog=x; other=1`);
  c.click(c.button("reject"));
  assert.equal(c.storage.record.choice, "rejected");
  assert.equal(c.page.sandbox.posthog, undefined);
  assert.equal(c.banner.getAttribute("hidden"), "");
  assert.deepEqual(c.storage.removed.slice(-3), POSTHOG_KEYS(config.key));
  assert.equal(c.page.cookieWrites.length >= 2, true, "both PostHog cookies expired");
});

test("consent: withdrawing after Accept opts out and purges", () => {
  const c = consentPage({ v: config.consentVersion, choice: "accepted", at: Date.now() }, `ph_${config.key}_posthog=x`);
  assert.ok(c.page.sandbox.posthog, "a valid Accept loads PostHog on page load");
  assert.equal(c.banner.getAttribute("hidden"), "");
  assert.deepEqual(c.page.cookieWrites, [], "nothing purged while consent holds");
  c.click(c.settingsItem.childNodes[0]);
  assert.equal(c.banner.getAttribute("hidden"), null);
  c.click(c.button("reject"));
  assert.equal(c.calls("opt_out_capturing").length, 1);
  assert.equal(c.storage.record.choice, "rejected");
  assert.deepEqual(c.storage.removed, POSTHOG_KEYS(config.key));
  assert.equal(c.page.cookieWrites.length, 2);
});

test("consent: expired or older notices ask again, load nothing, and purge", () => {
  const now = Date.now();
  for (const stored of [
    { v: config.consentVersion, choice: "accepted", at: now - 366 * DAY },
    { v: "2000-01-01", choice: "accepted", at: now },
    { v: config.consentVersion, choice: "maybe", at: now },
  ]) {
    const c = consentPage(stored, `ph_${config.key}_posthog=old`);
    assert.equal(c.banner.getAttribute("hidden"), null, JSON.stringify(stored));
    assert.equal(c.page.sandbox.posthog, undefined);
    assert.equal(c.page.cookieWrites.length, 2, "the old PostHog cookies are expired");
    assert.deepEqual(c.storage.removed, POSTHOG_KEYS(config.key));
  }
  const rejected = consentPage({ v: config.consentVersion, choice: "rejected", at: now }, "");
  assert.equal(rejected.banner.getAttribute("hidden"), "");
  assert.equal(rejected.page.sandbox.posthog, undefined);
  assert.deepEqual(rejected.page.cookieWrites, [], "no PostHog cookie, nothing to expire");
});

test("consent banner markup: equal buttons, notice link, footer settings", () => {
  const consent = read(path.join(root, "site/overrides/partials/consent.html"));
  assert.match(consent, /<div class="gg-consent"[^>]*\bhidden>/);
  const buttons = [...consent.matchAll(/<button type="button" class="([^"]+)" data-gg-consent="(\w+)">/g)];
  assert.deepEqual(buttons.map((m) => m[2]), ["reject", "accept"]);
  assert.equal(new Set(buttons.map((m) => m[1])).size, 1, "Accept and Reject must look the same");
  assert.match(consent, /legal\/cookies\//);

  const footer = read(footerPath);
  assert.match(footer, /<li data-gg-consent-open hidden><button type="button" class="gg-footer__link-btn" data-gg-consent="open">Cookie settings<\/button><\/li>/);
  assert.match(footer, /\{% include "partials\/consent\.html" %\}/);
});

test("staging and local never show the banner or touch storage", () => {
  for (const hostname of ["127.0.0.1", "staging.gitgrit.dev", "www.gitgrit.dev"]) {
    // localStorage is the bomb here: any access would throw.
    const page = boot(render(sourceScript, config), { hostname, href: `https://${hostname}/` }, withBanner);
    assert.equal(find(page.body, ".gg-consent").getAttribute("hidden"), "");
    assert.equal(find(page.body, "[data-gg-consent-open]").getAttribute("hidden"), "");
  }
});
