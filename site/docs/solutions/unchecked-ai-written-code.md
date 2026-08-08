---
title: Unchecked AI-Written Code
template: solution-page.html
hide:
  - navigation
  - toc
---

<div class="gg-hero2">
  <h1>Unchecked AI-Written Code</h1>
  <p class="gg-sol-subhead">Guardrails for a codebase increasingly written by AI.</p>
  <p class="gg-hero2__cta"><a class="gg-btn gg-btn--primary" href="https://app.gitgrit.dev">Try it today</a> <button type="button" class="gg-btn gg-btn--consult" data-consult-open>Book a consult</button></p>
</div>

<section class="gg-area">
  <div class="gg-area__text">
    <p>You rolled AI assistants out to every team, and now they write <strong>more than you can review</strong>.</p>
  </div>
  <div class="gg-area__visual">
    <div class="gg-mock">
      <div class="gg-mock__head"><span class="gg-mock__title">AI-generated changes</span><span class="gg-mock__stat"><b>37</b> today</span></div>
      <div class="gg-mock__row"><span class="gg-dot gg-dot--amber"></span><span class="gg-mock__name">web-app · CLAUDE.md, .mcp.json</span><span class="gg-score" style="color:var(--gg-text-dim)">new</span></div>
      <div class="gg-mock__row"><span class="gg-dot gg-dot--amber"></span><span class="gg-mock__name">orders-svc · agent config</span><span class="gg-score" style="color:var(--gg-text-dim)">new</span></div>
      <div class="gg-mock__row"><span class="gg-dot gg-dot--amber"></span><span class="gg-mock__name">billing-api · generated tests</span><span class="gg-score" style="color:var(--gg-text-dim)">new</span></div>
    </div>
  </div>
</section>

<section class="gg-area gg-area--flip">
  <div class="gg-area__text">
    <p>A stale CLAUDE.md, a committed .mcp.json pointing at localhost, a blanket Bash allow added "just for now", and <strong>nobody is checking</strong>.</p>
  </div>
  <div class="gg-area__visual">
    <div class="gg-mock">
      <div class="gg-mock__head"><span class="gg-mock__title">AI config</span><span class="gg-mock__stat"><b class="gg-warn">3 issues</b></span></div>
      <div class="gg-mock__row"><span class="gg-badge gg-badge--fail">Failed</span><span class="gg-mock__name">web-app / agent-instructions-not-stale</span><span class="gg-score gg-score--low">&#10007;</span></div>
      <div class="gg-mock__row"><span class="gg-badge gg-badge--fail">Failed</span><span class="gg-mock__name">orders-svc / mcp-config-portable</span><span class="gg-score gg-score--low">&#10007;</span></div>
      <div class="gg-mock__row"><span class="gg-badge gg-badge--fail">Failed</span><span class="gg-mock__name">billing-api / no-blanket-bash</span><span class="gg-score gg-score--low">&#10007;</span></div>
    </div>
  </div>
</section>

<section class="gg-area">
  <div class="gg-area__text">
    <p>GitGrit checks AI-assistant config across every repo and <strong>LLM-grades</strong> the code's quality, so what AI ships still meets your standards.</p>
  </div>
  <div class="gg-area__visual">
    <div class="gg-mock">
      <div class="gg-mock__head"><span class="gg-mock__title">LLM &middot; README quality</span><span class="gg-mock__stat"><b class="gg-warn">verify</b></span></div>
      <div class="gg-mock__big gg-mock__big--red">34 / 100</div>
      <div class="gg-mock__fix"><strong>Verdict</strong> &mdash; no run instructions and no examples; title only.</div>
    </div>
  </div>
</section>

<section class="gg-outcome">
  <p class="gg-outcome__lead">With GitGrit:</p>
  <ul class="gg-benefits gg-benefits--row">
    <li>Confidence in what AI ships to your repos.</li>
    <li>Stale or unsafe AI configs caught before they spread.</li>
    <li>Quality graded, not just presence checked.</li>
  </ul>
</section>

<p class="gg-hero2__cta" style="text-align: center; margin-top: 3rem;"><a class="gg-btn gg-btn--primary" href="https://app.gitgrit.dev">Try it today</a> <button type="button" class="gg-btn gg-btn--consult" data-consult-open>Book a consult</button></p>
