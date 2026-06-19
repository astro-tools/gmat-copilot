---
title: gmat-copilot leaderboard
emoji: 🛰️
colorFrom: indigo
colorTo: blue
sdk: static
app_file: index.html
pinned: false
license: mit
---

# gmat-copilot leaderboard

A static board ranking `provider:model`s on the
[gmat-copilot](https://github.com/astro-tools/gmat-copilot) evaluation suite.

The board **ranks on a never-committed held-out set** (the headline); the committed public set is
shown alongside as the reproducibility anchor. A large `public − held-out` gap is the overfit tell.

It renders the published `leaderboard.json` and runs no model: the board carries **aggregates only**
(per-tier pass-rates, the close-the-loop figures, usage, and a run block), so no prompt, intent, or
judge verdict can leak through it. Scoring lives in the project's gated CI; this Space is presentation
only.

- **Repository:** <https://github.com/astro-tools/gmat-copilot>
- **Docs:** <https://astro-tools.github.io/gmat-copilot/leaderboard/>
- **Submit an entry:** <https://astro-tools.github.io/gmat-copilot/leaderboard/#submit-an-entry>

This Space is rebuilt from the published board by the project's leaderboard refresh workflow. Do not
edit it by hand.
