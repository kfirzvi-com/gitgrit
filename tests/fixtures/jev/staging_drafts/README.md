# Staging LLM drafts for the Jev map eval

Three LLM-only maps of `gitgrit-demo-messy-monorepo` produced on staging on 2026-09-30
(GitGrit Testing workspace, Gemini 3.5 Flash Lite, `eval_topology --save-json`), with sibling
refs rewritten to `{repo}` so `FakeTopologyInference` can replay them against any project.
`cassetteN.json` holds the real Jev answers for draft N. Replay the comparison offline:

    manage.py eval_topology <messy project id> --local-path ../gitgrit-demo-messy-monorepo \
        --golden <golden.json> --fixture tests/fixtures/jev/staging_drafts/draft1.json --jev off
    manage.py eval_topology ... --fixture tests/fixtures/jev/staging_drafts/draft1.json \
        --jev on --replay-jev tests/fixtures/jev/staging_drafts/cassette1.json
