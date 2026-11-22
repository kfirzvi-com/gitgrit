/**
 * The three comparison pages (OpenSSF Scorecard, Cortex, Backstage scorecards).
 *
 * Builds the docs site once, then checks each page:
 *   - is linked from the Compare column in the footer
 *   - is listed in sitemap.xml
 *   - has a title and a meta description
 *   - has valid FAQPage JSON-LD (and no price/offers schema)
 *   - gives every competitor cell in the comparison table an external link
 *     on an official host
 *   - does not describe GitGrit as free
 *
 *   node --test site/tests/compare_pages.test.mjs
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const footerPath = path.join(root, "site/overrides/partials/footer.html");
const buildDir = path.join(root, "site/build");

const PAGES = [
  {
    slug: "gitgrit-vs-openssf-scorecard",
    nav: "GitGrit vs OpenSSF Scorecard",
    opener: "OpenSSF Scorecard measures the security health of open-source projects",
  },
  {
    slug: "gitgrit-vs-cortex",
    nav: "GitGrit vs Cortex",
    opener: "Cortex scores services in a developer portal you set up and maintain",
  },
  {
    slug: "gitgrit-vs-backstage-scorecards",
    nav: "GitGrit vs Backstage scorecards",
    opener: "Backstage scorecards need a Backstage portal, plugins and a team to run them",
  },
];

// Competitor facts may only link to the vendor's own docs, pricing, or GitHub.
const OFFICIAL_HOSTS = new Set([
  "github.com",
  "scorecard.dev",
  "api.scorecard.dev",
  "docs.cortex.io",
  "www.cortex.io",
  "cortex.io",
  "backstage.io",
  "www.backstage.io",
  "backstage.spotify.com",
  "openssf.org",
  "www.openssf.org",
]);

function read(file) {
  return readFileSync(file, "utf8");
}

function unescapeHtml(value) {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

function strip(html) {
  return unescapeHtml(html.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();
}

function markdownPath(slug) {
  return path.join(root, "site/docs/compare", `${slug}.md`);
}

function pageHtmlPath(slug) {
  return path.join(buildDir, "compare", slug, "index.html");
}

let built = false;

function buildSite() {
  if (built) return;
  for (const page of PAGES) {
    assert.ok(existsSync(markdownPath(page.slug)), `${page.slug}.md is missing`);
  }
  const result = spawnSync(
    "uv",
    ["run", "--project", "site", "mkdocs", "build", "-f", "site/mkdocs.yml", "-d", buildDir],
    {
      cwd: root,
      encoding: "utf8",
      timeout: 600_000,
      env: {
        ...process.env,
        PATH: `${process.env.HOME}/.local/bin:${process.env.PATH}`,
      },
    },
  );
  assert.equal(
    result.status,
    0,
    `mkdocs build failed\n${result.stdout || ""}\n${result.stderr || ""}\n${result.error || ""}`,
  );
  built = true;
}

function sitemapText() {
  const xml = path.join(buildDir, "sitemap.xml");
  const gz = path.join(buildDir, "sitemap.xml.gz");
  if (existsSync(xml)) return read(xml);
  if (existsSync(gz)) return gunzipSync(readFileSync(gz)).toString("utf8");
  assert.fail(`no sitemap.xml or sitemap.xml.gz in ${buildDir}`);
}

function article(html) {
  const match = html.match(/<article[\s\S]*?<\/article>/);
  assert.ok(match, "page has no <article>");
  return match[0];
}

function metaDescription(html) {
  const tag = [...html.matchAll(/<meta\s[^>]*>/g)]
    .map((match) => match[0])
    .find((item) => /name="description"/.test(item));
  assert.ok(tag, "meta description missing");
  const content = tag.match(/content="([^"]*)"/);
  assert.ok(content, "meta description has no content");
  return unescapeHtml(content[1]).trim();
}

function faqEntities(html) {
  const scripts = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)];
  assert.ok(scripts.length > 0, "no JSON-LD script");
  const parsed = scripts.map((match) => JSON.parse(match[1]));
  for (const data of parsed) {
    const blob = JSON.stringify(data);
    assert.equal(blob.includes('"price"'), false, "JSON-LD must not include a price");
    assert.equal(blob.includes('"offers"'), false, "JSON-LD must not include offers");
    assert.equal(blob.includes("Offer"), false, "JSON-LD must not include an Offer type");
  }
  const faq = parsed.find((data) => data["@type"] === "FAQPage");
  assert.ok(faq, "FAQPage JSON-LD missing");
  assert.equal(faq["@context"], "https://schema.org");
  assert.ok(Array.isArray(faq.mainEntity) && faq.mainEntity.length >= 3, "FAQ needs at least 3 questions");
  for (const question of faq.mainEntity) {
    assert.equal(question["@type"], "Question");
    assert.equal(typeof question.name, "string");
    assert.ok(question.name.trim().length > 0, "FAQ question is empty");
    assert.equal(question.acceptedAnswer?.["@type"], "Answer");
    assert.equal(typeof question.acceptedAnswer.text, "string");
    assert.ok(question.acceptedAnswer.text.trim().length > 0, `FAQ answer empty for ${question.name}`);
  }
  return faq.mainEntity;
}

function comparisonRows(html) {
  const tables = [...html.matchAll(/<table[\s\S]*?<\/table>/g)].map((match) => match[0]);
  for (const table of tables) {
    const rows = [...table.matchAll(/<tr[\s\S]*?<\/tr>/g)].map((match) => match[0]);
    if (rows.length < 2) continue;
    const header = [...rows[0].matchAll(/<t[hd][^>]*>([\s\S]*?)<\/t[hd]>/g)].map((match) => strip(match[1]));
    const gitgritAt = header.findIndex((cell) => /^gitgrit$/i.test(cell));
    if (gitgritAt < 1) continue;
    const body = rows.slice(1).map((row) =>
      [...row.matchAll(/<t[hd][^>]*>([\s\S]*?)<\/t[hd]>/g)].map((match) => match[1]),
    );
    return { header, gitgritAt, body };
  }
  assert.fail("comparison table with a GitGrit column was not found");
}

function officialLinks(cellHtml) {
  const hrefs = [...cellHtml.matchAll(/<a\s[^>]*href="([^"]+)"/g)].map((match) => unescapeHtml(match[1]));
  const official = [];
  for (const href of hrefs) {
    let url;
    try {
      url = new URL(href);
    } catch {
      continue;
    }
    if (url.protocol !== "https:" && url.protocol !== "http:") continue;
    if (!OFFICIAL_HOSTS.has(url.hostname)) continue;
    if (url.hostname === "github.com" && /^\/kfirzvi/i.test(url.pathname)) continue;
    official.push(href);
  }
  return official;
}

function assertNotCalledFree(text, where) {
  const mentionsGitGrit = /\bgitgrit\b/i.test(text);
  if (!mentionsGitGrit) return;
  assert.equal(
    /\bfree\b/i.test(text),
    false,
    `${where} mentions GitGrit and "free" together: ${text.slice(0, 280)}`,
  );
  assert.equal(
    /\b(no charge|zero[- ]cost|costs nothing|priced at\s*\$0)\b/i.test(text),
    false,
    `${where} implies GitGrit has no price: ${text.slice(0, 280)}`,
  );
}

test("compare nav lists the three pages", () => {
  const footer = read(footerPath);
  const column = footer.match(/<h6>Compare<\/h6>[\s\S]*?<\/ul>/);
  assert.ok(column, "footer has no Compare column");
  for (const page of PAGES) {
    assert.match(column[0], new RegExp(`compare/${page.slug}/`));
    assert.match(column[0], new RegExp(page.nav.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

function compareNavLinks(html) {
  const footer = html.match(/<footer[\s\S]*?<\/footer>/);
  assert.ok(footer, "built page has no footer");
  const column = footer[0].match(/<h6>Compare<\/h6>[\s\S]*?<\/ul>/);
  assert.ok(column, "built footer has no Compare column");
  return [...column[0].matchAll(/<a\s[^>]*href="([^"]+)"[^>]*>([^<]*)</g)].map((match) => ({
    href: unescapeHtml(match[1]),
    text: unescapeHtml(match[2]).trim(),
  }));
}

test("built compare pages", () => {
  buildSite();
  const sitemap = sitemapText();
  const nav = compareNavLinks(read(path.join(buildDir, "index.html")));
  for (const page of PAGES) {
    const link = nav.find((item) => item.href.includes(`${page.slug}/`) && item.text === page.nav);
    assert.ok(link, `built Compare nav is missing ${page.nav}; saw ${JSON.stringify(nav)}`);

    const htmlPath = pageHtmlPath(page.slug);
    assert.ok(existsSync(htmlPath), `${page.slug} did not build`);
    const html = read(htmlPath);
    const title = unescapeHtml((html.match(/<title>([^<]*)<\/title>/) || [])[1] || "").trim();
    assert.ok(title.length > 0, `${page.slug} title is empty`);
    assert.match(title, new RegExp(page.nav.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    const description = metaDescription(html);
    assert.ok(description.length >= 40, `${page.slug} meta description is too short`);

    assert.match(sitemap, new RegExp(`https://gitgrit.dev/compare/${page.slug}/`));
    assert.ok(
      compareNavLinks(html).some((item) => item.text === page.nav),
      `${page.slug} footer Compare column drops ${page.nav}`,
    );

    const body = article(html);
    assert.doesNotMatch(body, /kfirzvi/i);
    assert.doesNotMatch(read(markdownPath(page.slug)), /kfirzvi/i);
    assert.match(strip(body), new RegExp(page.opener.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));

    const blocks = [
      ...body.matchAll(/<(p|li|td|th|h1|h2|h3)(\s[^>]*)?>([\s\S]*?)<\/\1>/g),
    ].map((match) => strip(match[3]));
    for (const block of blocks) assertNotCalledFree(block, `${page.slug} copy`);

    const entities = faqEntities(html);
    for (const question of entities) {
      assertNotCalledFree(question.name, `${page.slug} FAQ question`);
      assertNotCalledFree(question.acceptedAnswer.text, `${page.slug} FAQ "${question.name}"`);
    }

    const { gitgritAt, body: rows } = comparisonRows(html);
    assert.ok(rows.length >= 4, `${page.slug} comparison table is too short`);
    for (const row of rows) {
      const competitor = row[gitgritAt - 1] || "";
      const links = officialLinks(competitor);
      assert.ok(
        links.length > 0,
        `${page.slug} competitor cell has no official link: ${strip(competitor).slice(0, 180)}`,
      );
    }
  }
});
