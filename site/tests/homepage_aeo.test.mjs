/**
 * Built-site checks for /llms.txt, the homepage definition and FAQ, and
 * homepage JSON-LD. Requires a docs build:
 *
 *   uv run --project site mkdocs build -f site/mkdocs.yml -d build
 *   node --test site/tests/homepage_aeo.test.mjs
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const buildDir = path.join(root, "site/build");

const SENTENCE =
  "GitGrit is an open-source engineering standards platform: it turns your standards into code, checks every GitHub and GitLab repo on every push, and grades each one from A+ to F.";

const FAQ = [
  [
    "What is GitGrit?",
    "GitGrit is an open-source engineering standards platform. You write each standard as short, readable code (or pick ready-made packs), and GitGrit checks every GitHub and GitLab repository against them on every push, pull request and tag. Each repository gets a grade from A+ to F, with the exact reason when something fails.",
  ],
  [
    "How is GitGrit different from an AI code reviewer like CodeRabbit?",
    "An AI reviewer comments on one pull request at a time. GitGrit checks the whole repository against the same standards everywhere, including repositories nobody is changing, and shows every repository's grade on one screen. Many teams use both.",
  ],
  [
    "How is GitGrit different from Port, OpsLevel or Backstage scorecards?",
    "Developer portals grade services in a catalog you first have to build and maintain. GitGrit works straight from your repositories: connect GitHub or GitLab, pick standards, and see grades in minutes. Each check is code, so it gives the same answer every time.",
  ],
  [
    "Can AI coding agents use GitGrit?",
    "Yes. Agents read the same standards through GitGrit, and every change, human or AI, is checked against them.",
  ],
  [
    "Is GitGrit open source? Can I self-host it?",
    "Yes. GitGrit is MIT-licensed and can be self-hosted, including air-gapped.",
  ],
];

const LLMS_TXT = `# GitGrit

> GitGrit is an open-source (MIT) engineering standards platform. It turns your engineering standards into code, checks every GitHub and GitLab repository on every push, pull request and tag, and grades each repository from A+ to F with the exact reason when something fails. It can be self-hosted, including air-gapped.

GitGrit is not an AI code reviewer. AI reviewers such as CodeRabbit comment on one pull request at a time. GitGrit checks the whole repository against the same standards everywhere, including repositories nobody is changing, and shows every repository's grade on one screen.

## Start here
- [Quick Start](https://gitgrit.dev/getting-started/quickstart/): connect GitHub or GitLab, install a standards pack, see your first grade in about 10 minutes
- [Writing Standards](https://gitgrit.dev/getting-started/standards/): standards are short Python functions, or an LLM check when a rule needs judgment
- [Standard Marketplace](https://gitgrit.dev/features/marketplace/): ready-made packs (Repository Hygiene, Documentation Standards, Git Hygiene, Security Essentials, Agentic Standards, Node.js, Python, Docker)
- [Adding Projects](https://gitgrit.dev/getting-started/projects/): connect a platform, add repositories, how the A+ to F grade is calculated
- [Command Line](https://gitgrit.dev/getting-started/cli/): the \`gitgrit\` CLI, and a CI gate with \`gitgrit check --wait\`
- [Self-hosting](https://gitgrit.dev/self-hosting/)

## Features
- [Dashboard](https://gitgrit.dev/features/dashboard/): workspace health, warning lights, the projects that need you, AI usage
- [Search & Bulk Edit](https://gitgrit.dev/features/search/): GitHub-style filters (health:failed lifecycle:production), sort, group, bulk edit
- [Stacks & the Stack Map](https://gitgrit.dev/features/stacks/): group projects into systems; an AI-built map of services, dependencies and infrastructure
- [AI Standards & Budgets](https://gitgrit.dev/features/ai/): bring your own model (Anthropic, OpenAI, Bedrock, Vertex, Ollama…), LLM standards, per-model token budgets
- [Notifications](https://gitgrit.dev/features/notifications/): who is told when standards fail, a project fails, a connection breaks or a budget runs low
- [Usage](https://gitgrit.dev/features/usage/): executions and sandbox run time per month, trigger and project
- [REST API & Tokens](https://gitgrit.dev/api/rest/): every endpoint, personal and workspace tokens

## Use cases
- [Enforce engineering standards on every commit](https://gitgrit.dev/use-cases/enforce-engineering-standards/)
- [AI coding standards](https://gitgrit.dev/use-cases/ai-coding-standards/)
- [Engineering governance](https://gitgrit.dev/use-cases/engineering-governance/)
- [Engineering visibility](https://gitgrit.dev/use-cases/engineering-visibility/)

## Compare
- [GitGrit vs CodeRabbit](https://gitgrit.dev/compare/gitgrit-vs-coderabbit/)
- [GitGrit vs Port](https://gitgrit.dev/compare/gitgrit-vs-port/)
- [GitGrit vs OpsLevel](https://gitgrit.dev/compare/gitgrit-vs-opslevel/)
- [GitGrit vs Pandorian](https://gitgrit.dev/compare/gitgrit-vs-pandorian/)
- [GitGrit vs Baz](https://gitgrit.dev/compare/gitgrit-vs-baz/)

## Optional
- Source code is MIT-licensed. The repository is linked from the site footer.
- [What's New](https://gitgrit.dev/whats-new/)
`;

const FAQ_PLAIN = FAQ.map(([question, answer]) => `### ${question}\n\n${answer}`).join("\n\n");

const LLMS_FULL_TXT = `# GitGrit

> GitGrit is an open-source (MIT) engineering standards platform. It turns your engineering standards into code, checks every GitHub and GitLab repository on every push, pull request and tag, and grades each repository from A+ to F with the exact reason when something fails. It can be self-hosted, including air-gapped.

GitGrit is not an AI code reviewer. AI reviewers such as CodeRabbit comment on one pull request at a time. GitGrit checks the whole repository against the same standards everywhere, including repositories nobody is changing, and shows every repository's grade on one screen.

## FAQ

${FAQ_PLAIN}

## Start here
- [Quick Start](https://gitgrit.dev/getting-started/quickstart/): connect GitHub or GitLab, install a standards pack, see your first grade in about 10 minutes
- [Writing Standards](https://gitgrit.dev/getting-started/standards/): standards are short Python functions, or an LLM check when a rule needs judgment
- [Standard Marketplace](https://gitgrit.dev/features/marketplace/): ready-made packs (Repository Hygiene, Documentation Standards, Git Hygiene, Security Essentials, Agentic Standards, Node.js, Python, Docker)
- [Adding Projects](https://gitgrit.dev/getting-started/projects/): connect a platform, add repositories, how the A+ to F grade is calculated
- [Command Line](https://gitgrit.dev/getting-started/cli/): the \`gitgrit\` CLI, and a CI gate with \`gitgrit check --wait\`
- [Self-hosting](https://gitgrit.dev/self-hosting/)

## Features
- [Dashboard](https://gitgrit.dev/features/dashboard/): workspace health, warning lights, the projects that need you, AI usage
- [Search & Bulk Edit](https://gitgrit.dev/features/search/): GitHub-style filters (health:failed lifecycle:production), sort, group, bulk edit
- [Stacks & the Stack Map](https://gitgrit.dev/features/stacks/): group projects into systems; an AI-built map of services, dependencies and infrastructure
- [AI Standards & Budgets](https://gitgrit.dev/features/ai/): bring your own model (Anthropic, OpenAI, Bedrock, Vertex, Ollama…), LLM standards, per-model token budgets
- [Notifications](https://gitgrit.dev/features/notifications/): who is told when standards fail, a project fails, a connection breaks or a budget runs low
- [Usage](https://gitgrit.dev/features/usage/): executions and sandbox run time per month, trigger and project
- [REST API & Tokens](https://gitgrit.dev/api/rest/): every endpoint, personal and workspace tokens

## Use cases
- [Enforce engineering standards on every commit](https://gitgrit.dev/use-cases/enforce-engineering-standards/)
- [AI coding standards](https://gitgrit.dev/use-cases/ai-coding-standards/)
- [Engineering governance](https://gitgrit.dev/use-cases/engineering-governance/)
- [Engineering visibility](https://gitgrit.dev/use-cases/engineering-visibility/)

## Compare
- [GitGrit vs CodeRabbit](https://gitgrit.dev/compare/gitgrit-vs-coderabbit/)
- [GitGrit vs Port](https://gitgrit.dev/compare/gitgrit-vs-port/)
- [GitGrit vs OpsLevel](https://gitgrit.dev/compare/gitgrit-vs-opslevel/)
- [GitGrit vs Pandorian](https://gitgrit.dev/compare/gitgrit-vs-pandorian/)
- [GitGrit vs Baz](https://gitgrit.dev/compare/gitgrit-vs-baz/)

## Optional
- Source code is MIT-licensed. The repository is linked from the site footer.
- [What's New](https://gitgrit.dev/whats-new/)
`;

const ROBOTS_TXT = `User-agent: *
Allow: /

# AI assistants and AI search are welcome
User-agent: GPTBot
User-agent: OAI-SearchBot
User-agent: ClaudeBot
User-agent: PerplexityBot
User-agent: Google-Extended
User-agent: CCBot
Allow: /

Sitemap: https://gitgrit.dev/sitemap.xml
`;

const PAGE_TITLE = "GitGrit: Engineering Standards as Code for Every Repo";
const PAGE_DESCRIPTION =
  "Turn your engineering standards into running code. GitGrit checks every GitHub and GitLab repo on every push and grades each one from A+ to F.";

const BANNED_KEYS = new Set(["offers", "price", "pricecurrency", "isaccessibleforfree"]);

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function read(file) {
  assert.equal(existsSync(file), true, `missing ${file}`);
  const info = statSync(file);
  assert.equal(info.isFile(), true, `${file} should be a file at the site root`);
  return readFileSync(file, "utf8");
}

function textOf(html) {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function assertNoFreeClaim(label, value) {
  assert.equal(
    /\bfree\b/i.test(value),
    false,
    `${label} must not call GitGrit free:\n${value.match(/.{0,80}\bfree\b.{0,80}/i)?.[0] ?? value.slice(0, 180)}`,
  );
  assert.equal(/isAccessibleForFree/i.test(value), false, `${label} must not set isAccessibleForFree`);
  assert.equal(/\bno charge\b|\bno cost\b|\bgratis\b|\$0\b/i.test(value), false, `${label} implies a free product`);
}

function walkSchema(node, at, problems) {
  if (Array.isArray(node)) {
    node.forEach((item, index) => walkSchema(item, `${at}[${index}]`, problems));
    return;
  }
  if (!node || typeof node !== "object") {
    if (typeof node === "string") assertNoFreeClaim(at, node);
    if (typeof node === "number") assert.notEqual(node, 0, `${at} must not be a zero price`);
    return;
  }
  for (const [key, value] of Object.entries(node)) {
    if (BANNED_KEYS.has(key.toLowerCase())) problems.push(`${at}.${key}`);
    walkSchema(value, `${at}.${key}`, problems);
  }
}

function schemaNodes(html) {
  const scripts = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)];
  assert.ok(scripts.length > 0, "homepage has no JSON-LD");
  const nodes = [];
  for (const match of scripts) {
    const parsed = JSON.parse(match[1]);
    assert.equal(parsed["@context"], "https://schema.org");
    const graph = parsed["@graph"] ?? [parsed];
    assert.ok(Array.isArray(graph));
    nodes.push(...graph);
  }
  return { scripts, nodes };
}

function requireBuild() {
  const home = path.join(buildDir, "index.html");
  assert.equal(
    existsSync(home),
    true,
    "build the site first: uv run --project site mkdocs build -f site/mkdocs.yml -d build",
  );
}

test("built site serves llms.txt and llms-full.txt at the root", () => {
  requireBuild();
  const llms = read(path.join(buildDir, "llms.txt"));
  const full = read(path.join(buildDir, "llms-full.txt"));
  assert.equal(llms, LLMS_TXT);
  assert.equal(full, LLMS_FULL_TXT);
  assert.equal(existsSync(path.join(buildDir, "llms.txt", "index.html")), false);
  assertNoFreeClaim("llms.txt", llms);
  assertNoFreeClaim("llms-full.txt", full);
  assert.doesNotMatch(llms, /kfirzvi/i);
  assert.doesNotMatch(full, /kfirzvi/i);
});

test("built robots.txt explicitly allows AI crawlers", () => {
  requireBuild();
  const robots = read(path.join(buildDir, "robots.txt"));
  assert.equal(robots, ROBOTS_TXT);
  assertNoFreeClaim("robots.txt", robots);
});

test("homepage keeps its title and meta description", () => {
  requireBuild();
  const html = read(path.join(buildDir, "index.html"));
  assert.match(html, new RegExp(`<title>${escapeRegExp(PAGE_TITLE)}</title>`));
  const description = [...html.matchAll(/<meta\b[^>]*>/g)]
    .map((match) => match[0])
    .find((tag) => /\bname="description"/.test(tag));
  assert.ok(description, "meta description missing");
  assert.match(description, new RegExp(`content="${escapeRegExp(PAGE_DESCRIPTION)}"`));
});

test("homepage shows the definition and FAQ, with matching FAQPage schema", () => {
  requireBuild();
  const html = read(path.join(buildDir, "index.html"));

  const definition = html.match(/<p class="gg-def">([\s\S]*?)<\/p>/);
  assert.ok(definition, "visible definition sentence missing");
  assert.equal(textOf(definition[1]), SENTENCE);
  assert.equal([...html.matchAll(new RegExp(SENTENCE.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g"))].length, 1);

  const faq = html.match(/<section class="gg-sec gg-faq[\s\S]*?<\/section>/);
  assert.ok(faq, "visible FAQ section missing");
  const visible = [...faq[0].matchAll(/<summary><h3>([\s\S]*?)<\/h3><\/summary>\s*<p>([\s\S]*?)<\/p>/g)].map((match) => [
    textOf(match[1]),
    textOf(match[2]),
  ]);
  assert.deepEqual(visible, FAQ);

  const { scripts, nodes } = schemaNodes(html);
  const faqPage = nodes.find((node) => node["@type"] === "FAQPage");
  assert.ok(faqPage, "FAQPage JSON-LD missing");
  const entities = faqPage.mainEntity;
  assert.equal(entities.length, FAQ.length);
  entities.forEach((entity, index) => {
    assert.equal(entity["@type"], "Question");
    assert.equal(entity.name, FAQ[index][0]);
    assert.equal(entity.acceptedAnswer["@type"], "Answer");
    assert.equal(entity.acceptedAnswer.text, FAQ[index][1]);
    assert.equal(entity.name, visible[index][0]);
    assert.equal(entity.acceptedAnswer.text, visible[index][1]);
  });

  const json = scripts.map((match) => match[1]).join("\n");
  assertNoFreeClaim("homepage definition", definition[1]);
  assertNoFreeClaim("homepage FAQ", faq[0]);
  assertNoFreeClaim("homepage JSON-LD", json);
  assert.doesNotMatch(`${definition[1]}\n${faq[0]}\n${json}`, /kfirzvi/i);

  assert.match(html, /@media \(max-width: 800px\) \{\s*\.gg-def \{/);
  assert.match(html, /@media \(max-width: 600px\) \{\s*\.gg-faq__item \{/);
});

test("homepage JSON-LD describes Praktical and GitGrit without an offer", () => {
  requireBuild();
  const html = read(path.join(buildDir, "index.html"));
  const { nodes } = schemaNodes(html);
  const problems = [];
  for (const node of nodes) walkSchema(node, node["@type"] ?? "node", problems);
  assert.deepEqual(problems, []);

  const org = nodes.find((node) => node["@type"] === "Organization");
  const app = nodes.find((node) => node["@type"] === "SoftwareApplication");
  assert.ok(org, "Organization JSON-LD missing");
  assert.ok(app, "SoftwareApplication JSON-LD missing");
  assert.equal(org["@id"], "https://praktical.dev/#organization");
  assert.equal(org.name, "Praktical");
  assert.equal(org.url, "https://praktical.dev/");
  assert.equal(org.logo, "https://praktical.dev/logo.png");
  assert.equal(app.name, "GitGrit");
  assert.equal(app.url, "https://gitgrit.dev/");
  assert.equal(app.applicationCategory, "DeveloperApplication");
  assert.equal(app.operatingSystem, "Web, self-hosted (Linux)");
  assert.equal(app.license, "https://opensource.org/licenses/MIT");
  assert.equal(
    app.description,
    "Open-source engineering standards platform. Turns engineering standards into code, checks every GitHub and GitLab repository on every push, and grades each repository from A+ to F.",
  );
  assert.deepEqual(app.publisher, { "@id": "https://praktical.dev/#organization" });
  assert.equal(Object.hasOwn(app, "offers"), false);
  assert.equal(Object.hasOwn(app, "isAccessibleForFree"), false);
});

test("compare pages keep FAQPage schema and gain no offer", () => {
  requireBuild();
  const html = read(path.join(buildDir, "compare/gitgrit-vs-coderabbit/index.html"));
  const { nodes } = schemaNodes(html);
  const faqPage = nodes.find((node) => node["@type"] === "FAQPage");
  assert.ok(faqPage, "compare FAQPage JSON-LD missing");
  assert.equal(faqPage.mainEntity[0].name, "Is GitGrit a CodeRabbit alternative?");
  const problems = [];
  for (const node of nodes) walkSchema(node, node["@type"] ?? "node", problems);
  assert.deepEqual(problems, []);
});
