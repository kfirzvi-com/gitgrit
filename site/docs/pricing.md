---
title: "Pricing"
description: "GitGrit pricing: free for individuals, simple monthly plans for growing teams. Priced by projects and standard executions, never per developer."
hide:
  - toc
---

<div class="gg-uc-hero" markdown>

<p class="gg-uc-eyebrow">Pricing</p>

# Pay for projects, not seats

Start free. Grow into a plan when your team does. **Every plan includes unlimited developers and unlimited standards.**

</div>

<div class="gg-pr-toggles">
  <div class="gg-pr-toggle" role="group" aria-label="Billing period">
    <button type="button" class="gg-pr-toggle__btn is-active" data-period="monthly" aria-pressed="true">Monthly</button>
    <button type="button" class="gg-pr-toggle__btn" data-period="annual" aria-pressed="false">Annual <span class="gg-pr-toggle__save">2 months free</span></button>
  </div>
  <div class="gg-pr-toggle" role="group" aria-label="Currency">
    <button type="button" class="gg-pr-toggle__btn is-active" data-currency="usd" aria-pressed="true">USD $</button>
    <button type="button" class="gg-pr-toggle__btn" data-currency="eur" aria-pressed="false">EUR €</button>
  </div>
</div>

<div class="gg-pr-grid">

  <div class="gg-pr-card" data-plan="free">
    <h3 class="gg-pr-card__name">Free</h3>
    <p class="gg-pr-card__for">For individuals trying GitGrit on their own projects.</p>
    <p class="gg-pr-card__price"><span class="gg-pr-card__amount" data-price="free">$0</span><span class="gg-pr-card__per">forever</span></p>
    <p class="gg-pr-card__note">&nbsp;</p>
    <a href="https://app.gitgrit.dev" class="gg-pr-card__btn gg-pr-card__btn--ghost">Start free</a>
    <ul class="gg-pr-card__list">
      <li><strong>3</strong> projects</li>
      <li><strong>3,000</strong> standard executions / mo</li>
      <li><strong>14 days</strong> of history</li>
      <li>Unlimited developers and standards</li>
      <li>Standard Marketplace</li>
      <li>Community support</li>
    </ul>
  </div>

  <div class="gg-pr-card gg-pr-card--featured" data-plan="team">
    <p class="gg-pr-card__badge">Most popular</p>
    <h3 class="gg-pr-card__name">Team</h3>
    <p class="gg-pr-card__for">For small companies rolling out standards across repos.</p>
    <p class="gg-pr-card__price">
      <span class="gg-pr-card__amount" data-price="team">$79</span><span class="gg-pr-card__per">/ month</span>
    </p>
    <p class="gg-pr-card__note" data-price-note="team">Billed monthly</p>
    <a href="https://app.gitgrit.dev" class="gg-pr-card__btn">Start 14-day trial</a>
    <ul class="gg-pr-card__list">
      <li><strong>15</strong> projects</li>
      <li><strong>20,000</strong> standard executions / mo</li>
      <li><strong>90 days</strong> of history</li>
      <li>Everything in Free</li>
      <li>Email support</li>
      <li>Data Processing Agreement</li>
    </ul>
  </div>

  <div class="gg-pr-card" data-plan="business">
    <h3 class="gg-pr-card__name">Business</h3>
    <p class="gg-pr-card__for">For growing engineering orgs with many teams and services.</p>
    <p class="gg-pr-card__price">
      <span class="gg-pr-card__amount" data-price="business">$249</span><span class="gg-pr-card__per">/ month</span>
    </p>
    <p class="gg-pr-card__note" data-price-note="business">Billed monthly</p>
    <a href="https://app.gitgrit.dev" class="gg-pr-card__btn gg-pr-card__btn--ghost">Start 14-day trial</a>
    <ul class="gg-pr-card__list">
      <li><strong>50</strong> projects</li>
      <li><strong>100,000</strong> standard executions / mo</li>
      <li><strong>12 months</strong> of history</li>
      <li>Everything in Team</li>
      <li>Priority support</li>
      <li>Annual invoicing</li>
    </ul>
  </div>

</div>

<div class="gg-pr-enterprise" data-plan="enterprise">
  <div class="gg-pr-enterprise__text">
    <h3 class="gg-pr-card__name">Enterprise</h3>
    <p>For large organisations. Limits, deployment and terms are shaped around you: cloud or <a href="../self-hosting/">self-hosted and air-gapped</a>, SSO, security reviews, SLAs and procurement.</p>
  </div>
  <a href="https://cal.com/gitgrit-demo/30min" data-cal-link="gitgrit-demo/30min" data-cal-namespace="30min" data-cal-config='{"layout":"month_view","useSlotsViewOnSmallScreen":"true"}' class="gg-pr-card__btn gg-pr-card__btn--ghost">Talk to us</a>
</div>

<section class="gg-faq" aria-labelledby="faq">
<div class="gg-faq__header">
  <h2 id="faq"><span class="lite">Common</span> questions</h2>
</div>
<div class="gg-faq__list">
  <details class="gg-faq__item">
    <summary><h3>What counts as a project?</h3></summary>
    <p>A project is one repository, one directory of a <a href="../getting-started/monorepos/">monorepo</a> added as its own project, or one <a href="../getting-started/artifact-projects/">artifact project</a> that GitGrit checks. A monorepo with a web app and two services added separately is three projects. Archived projects don't count.</p>
  </details>
  <details class="gg-faq__item">
    <summary><h3>What counts as a standard execution?</h3></summary>
    <p>One standard run against one commit. A push to a project with 10 standards attached is 10 executions. Pushes, pull requests, tags and manual runs all count the same way. In a monorepo, a push only runs the projects whose directories it changed. You can see your usage any time in <strong>Workspace settings → Usage</strong>.</p>
  </details>
  <details class="gg-faq__item">
    <summary><h3>Why not per developer?</h3></summary>
    <p>Your standards apply to your code, not to how many people write it. Add your whole team, contractors and outsourced partners without watching a seat count.</p>
  </details>
  <details class="gg-faq__item">
    <summary><h3>What happens when I reach a limit?</h3></summary>
    <p>We email the workspace admins at 80%. At 100%, new executions pause until the next month starts or you upgrade. Nothing is deleted, and your existing results stay visible.</p>
  </details>
  <details class="gg-faq__item">
    <summary><h3>Which currency am I billed in?</h3></summary>
    <p>US dollars or euros, whichever you choose at checkout. Euro prices are set in euros, not converted at the daily rate.</p>
  </details>
  <details class="gg-faq__item">
    <summary><h3>Can I change plans later?</h3></summary>
    <p>Yes. Upgrade or downgrade any time from your workspace settings. Upgrades apply right away.</p>
  </details>
</div>
</section>

<script>
  (function () {
    // List prices per currency: monthly, and yearly (2 months free).
    var PRICES = {
      usd: { symbol: "$", free: [0, 0], team: [79, 790], business: [249, 2490] },
      eur: { symbol: "€", free: [0, 0], team: [75, 750], business: [229, 2290] },
    };
    // Visitors in a European time zone start on euros. Nothing is stored.
    var tz = "";
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) {}
    var state = { period: "monthly", currency: tz.indexOf("Europe/") === 0 ? "eur" : "usd" };

    function money(symbol, n) {
      return symbol + n.toLocaleString("en-US");
    }

    function render() {
      var p = PRICES[state.currency];
      document.querySelectorAll("[data-price]").forEach(function (el) {
        var plan = p[el.dataset.price];
        var amount = state.period === "annual" ? Math.round(plan[1] / 12) : plan[0];
        el.textContent = money(p.symbol, amount);
      });
      document.querySelectorAll("[data-price-note]").forEach(function (el) {
        var plan = p[el.dataset.priceNote];
        el.textContent = state.period === "annual" ? money(p.symbol, plan[1]) + " billed yearly" : "Billed monthly";
      });
      document.querySelectorAll(".gg-pr-toggle__btn").forEach(function (b) {
        var on = b.dataset.period ? b.dataset.period === state.period : b.dataset.currency === state.currency;
        b.classList.toggle("is-active", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }

    document.querySelectorAll(".gg-pr-toggle__btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (btn.dataset.period) state.period = btn.dataset.period;
        if (btn.dataset.currency) state.currency = btn.dataset.currency;
        render();
      });
    });
    render();
  })();
</script>
