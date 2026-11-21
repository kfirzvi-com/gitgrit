---
title: "Pricing"
description: "GitGrit pricing: free for individuals, simple monthly plans for growing teams. Priced by projects and checks, never per developer."
hide:
  - toc
---

<div class="gg-uc-hero" markdown>

<p class="gg-uc-eyebrow">Pricing</p>

# Pay for repositories, not seats

Start free. Grow into a plan when your team does. **Every plan includes unlimited developers and unlimited standards.**

</div>

<div class="gg-pr-toggle" role="group" aria-label="Billing period">
  <button type="button" class="gg-pr-toggle__btn is-active" data-period="monthly" aria-pressed="true">Monthly</button>
  <button type="button" class="gg-pr-toggle__btn" data-period="annual" aria-pressed="false">Annual <span class="gg-pr-toggle__save">2 months free</span></button>
</div>

<div class="gg-pr-grid">

  <div class="gg-pr-card">
    <h3 class="gg-pr-card__name">Free</h3>
    <p class="gg-pr-card__for">For individuals trying GitGrit on their own repositories.</p>
    <p class="gg-pr-card__price"><span class="gg-pr-card__amount">$0</span><span class="gg-pr-card__per">forever</span></p>
    <p class="gg-pr-card__note">&nbsp;</p>
    <a href="https://app.gitgrit.dev" class="gg-pr-card__btn gg-pr-card__btn--ghost">Start free</a>
    <ul class="gg-pr-card__list">
      <li><strong>3</strong> projects</li>
      <li><strong>3,000</strong> checks / month</li>
      <li><strong>14 days</strong> of history</li>
      <li>Unlimited developers and standards</li>
      <li>Standard Marketplace</li>
      <li>Community support</li>
    </ul>
  </div>

  <div class="gg-pr-card gg-pr-card--featured">
    <p class="gg-pr-card__badge">Most popular</p>
    <h3 class="gg-pr-card__name">Team</h3>
    <p class="gg-pr-card__for">For small companies rolling out standards across repos.</p>
    <p class="gg-pr-card__price">
      <span class="gg-pr-card__amount" data-monthly="$79" data-annual="$66">$79</span><span class="gg-pr-card__per">/ month</span>
    </p>
    <p class="gg-pr-card__note" data-monthly="Billed monthly" data-annual="$790 billed yearly">Billed monthly</p>
    <a href="https://app.gitgrit.dev" class="gg-pr-card__btn">Start 14-day trial</a>
    <ul class="gg-pr-card__list">
      <li><strong>15</strong> projects</li>
      <li><strong>20,000</strong> checks / month</li>
      <li><strong>90 days</strong> of history</li>
      <li>Everything in Free</li>
      <li>Email support</li>
      <li>Data Processing Agreement</li>
    </ul>
  </div>

  <div class="gg-pr-card">
    <h3 class="gg-pr-card__name">Business</h3>
    <p class="gg-pr-card__for">For growing engineering orgs with many teams and services.</p>
    <p class="gg-pr-card__price">
      <span class="gg-pr-card__amount" data-monthly="$249" data-annual="$208">$249</span><span class="gg-pr-card__per">/ month</span>
    </p>
    <p class="gg-pr-card__note" data-monthly="Billed monthly" data-annual="$2,490 billed yearly">Billed monthly</p>
    <a href="https://app.gitgrit.dev" class="gg-pr-card__btn gg-pr-card__btn--ghost">Start 14-day trial</a>
    <ul class="gg-pr-card__list">
      <li><strong>50</strong> projects</li>
      <li><strong>100,000</strong> checks / month</li>
      <li><strong>12 months</strong> of history</li>
      <li>Everything in Team</li>
      <li>Priority support</li>
      <li>Annual invoicing</li>
    </ul>
  </div>

</div>

<div class="gg-pr-enterprise">
  <div class="gg-pr-enterprise__text">
    <h3 class="gg-pr-card__name">Enterprise</h3>
    <p>For large organisations. Limits, deployment and terms are shaped around you: cloud or <a href="../self-hosting/">self-hosted and air-gapped</a>, SSO, security reviews, SLAs and procurement.</p>
  </div>
  <a href="https://cal.com/gitgrit-demo/30min" data-cal-link="gitgrit-demo/30min" data-cal-namespace="30min" data-cal-config='{"layout":"month_view","useSlotsViewOnSmallScreen":"true"}' class="gg-pr-card__btn gg-pr-card__btn--ghost">Talk to us</a>
</div>

## FAQ

### What counts as a project?

A project is one repository (or one [artifact project](getting-started/artifact-projects.md)) that GitGrit checks. Archived projects don't count.

### What counts as a check?

One standard run against one commit. A push to a project with 10 standards attached is 10 checks. Pushes, pull requests, tags and manual runs all count the same way. You can see your usage any time in **Workspace settings → Usage**.

### Why not per developer?

Your standards apply to your code, not to how many people write it. Add your whole team, contractors and outsourced partners without watching a seat count.

### What happens when I reach a limit?

We email the workspace admins at 80%. At 100%, new checks pause until the next month starts or you upgrade. Nothing is deleted, and your existing results stay visible.

### Can I change plans later?

Yes. Upgrade or downgrade any time from your workspace settings. Upgrades apply right away.

<script>
  (function () {
    var buttons = document.querySelectorAll(".gg-pr-toggle__btn");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var period = btn.dataset.period;
        buttons.forEach(function (b) {
          var on = b === btn;
          b.classList.toggle("is-active", on);
          b.setAttribute("aria-pressed", on ? "true" : "false");
        });
        document.querySelectorAll("[data-" + period + "]").forEach(function (el) {
          el.textContent = el.dataset[period];
        });
      });
    });
  })();
</script>
