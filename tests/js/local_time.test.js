// Run with: node --test tests/js/
// Loads app/static/app/local-time.js into a vm with a tiny fake DOM.
// Each zone runs in a child process, because TZ must be set before Node starts.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { execFileSync } = require("node:child_process");

const SRC = path.join(__dirname, "../../app/static/app/local-time.js");

function el(attrs, opts) {
  opts = opts || {};
  const e = {
    attrs: attrs || {}, parent: opts.parent || null, textContent: "x", title: "",
    getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; },
    get dataset() {
      const d = {};
      for (const k in this.attrs) if (k.startsWith("data-"))
        d[k.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = this.attrs[k];
      return d;
    },
    matches(sel) { return sel.slice(1, -1) in this.attrs; },
    closest(sel) {
      for (let n = this; n; n = n.parent) if (n.matches(sel)) return n;
      return null;
    },
    querySelectorAll() { return []; },
  };
  return e;
}

function load(cookie, elements) {
  const listeners = {};
  const writes = [];
  const document = {
    _cookie: cookie || "",
    get cookie() { return this._cookie; },
    set cookie(v) { writes.push(v); },
    addEventListener(n, f) { listeners[n] = f; },
    querySelectorAll(sel) {
      const key = sel.slice(1, -1);
      return elements.filter((e) => key in e.attrs);
    },
  };
  vm.runInNewContext(fs.readFileSync(SRC, "utf8"), { document, Intl, Date, Object, Array, isNaN });
  return { document, listeners, writes };
}

function scenario() {
  const wrap = el({ "data-time-format": "time" });
  const iso = "2026-10-20T11:00:00+00:00";
  const t = {
    time: el({ datetime: iso, "data-local-time": "", "data-time-format": "time" }),
    inherited: el({ datetime: iso, "data-local-time": "" }, { parent: wrap }),
    date: el({ datetime: "2026-10-20T23:30:00+00:00", "data-local-time": "", "data-time-format": "date" }),
    log: el({ datetime: "2026-10-20T11:00:01.489+00:00", "data-local-time": "", "data-time-format": "log" }),
    full: el({ datetime: iso, "data-local-time": "", "data-time-format": "full" }),
    dflt: el({ datetime: iso, "data-local-time": "" }),
    bad: el({ datetime: "not a date", "data-local-time": "" }),
    title: el({ "data-local-title": iso }),
    badTitle: el({ "data-local-title": "nope" }),
  };
  const { document, listeners, writes } = load("", Object.values(t));
  listeners.DOMContentLoaded();
  const out = {};
  for (const k in t) out[k] = t[k].textContent;
  out.title = t.title.title;
  out.badTitle = t.badTitle.title;
  // htmx swap: a root that is itself a time element
  const swapped = el({ datetime: iso, "data-local-time": "", "data-time-format": "time" });
  listeners["htmx:load"]({ detail: { elt: swapped } });
  out.swapped = swapped.textContent;
  out.writes = writes;
  return out;
}

if (process.argv[2] === "child") {
  console.log(JSON.stringify(scenario()));
  return;
}

function run(tz) {
  const o = execFileSync(process.execPath, [__filename, "child"], {
    env: Object.assign({}, process.env, { TZ: tz, LC_ALL: "en_GB.UTF-8", LANG: "en_GB.UTF-8" }),
  });
  return JSON.parse(o.toString());
}

test("shows 13:00 in Madrid and 14:00 in Jerusalem (UTC 11:00)", () => {
  const m = run("Europe/Madrid"), j = run("Asia/Jerusalem");
  assert.match(m.time, /13:00/);
  assert.match(j.time, /14:00/);
  assert.match(m.swapped, /13:00/);
  assert.match(j.swapped, /14:00/);
});

test("format comes from own or ancestor data-time-format", () => {
  const r = run("Europe/Madrid");
  assert.match(r.time, /^13:00$/);
  assert.match(r.inherited, /^13:00$/);           // from ancestor
  assert.strictEqual(r.date, "21 Oct 2026");
  assert.match(r.log, /13:00:01\.489/);
  assert.match(r.log, /GMT\+2|CEST/);
  assert.match(r.full, /2026/);
  assert.match(r.full, /13:00/);
  assert.match(r.full, /GMT\+2|CEST/);
  assert.match(r.dflt, /13:00/);
  assert.match(r.dflt, /Oct/);
});

test("date format uses the viewer zone (23:30Z is the next day in Madrid)", () => {
  assert.match(run("Europe/Madrid").date, /21/);
  assert.match(run("UTC").date, /20/);
});

test("data-local-title sets the title; invalid dates are left alone", () => {
  const r = run("Asia/Jerusalem");
  assert.match(r.title, /14:00/);
  assert.match(r.title, /GMT\+3|IDT/);
  assert.strictEqual(r.bad, "x");
  assert.strictEqual(r.badTitle, "");
});

test("sets no cookie", () => {
  assert.strictEqual(run("Europe/Madrid").writes.length, 0);
});
