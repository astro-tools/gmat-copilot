// Renders the published leaderboard.json. No build step, no dependencies, no model: this is the
// static front end of the leaderboard Space. The board is produced by the maintainer's gated CI and
// carries aggregates only, so nothing here can leak a held-out gold.
"use strict";

// The Space is published with leaderboard.json alongside this file; when previewing the committed
// template locally (from leaderboard/space/), fall back to the board one directory up.
const BOARD_SOURCES = ["./leaderboard.json", "../leaderboard.json"];

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of children || []) {
    node.append(child);
  }
  return node;
}

function pct(rate) {
  return rate === null || rate === undefined ? "—" : (rate * 100).toFixed(1) + "%";
}

function gap(value) {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : "";
  return sign + (value * 100).toFixed(1) + "%";
}

function byTier(cell) {
  if (!cell || !cell.by_tier) return "";
  return Object.entries(cell.by_tier)
    .map(([tier, rate]) => `${tier} ${pct(rate)}`)
    .join("  ·  ");
}

function dl(pairs) {
  const node = el("dl", { class: "detail-grid" });
  for (const [term, value] of pairs) {
    if (value === null || value === undefined || value === "") continue;
    node.append(el("dt", { text: term }), el("dd", { text: String(value) }));
  }
  return node;
}

function dryRunAgreement(ctl) {
  if (!ctl || !ctl.dry_run_agreement) return "";
  return Object.entries(ctl.dry_run_agreement)
    .map(([tier, rate]) => `${tier} ${rate === null ? "—" : pct(rate)}`)
    .join("  ·  ");
}

function detailPanel(entry) {
  const run = entry.run || {};
  const usage = entry.usage || {};
  const ctl = entry.close_the_loop;
  const heldOut = entry.held_out || {};

  const sections = [];

  sections.push(
    el("div", { class: "detail-block" }, [
      el("h4", { text: "Per-tier pass-rate" }),
      dl([
        ["Held-out", heldOut.pass_rate === null || heldOut.pass_rate === undefined
          ? (heldOut.status || "pending")
          : byTier(heldOut)],
        ["Public", byTier(entry.public)],
      ]),
    ])
  );

  if (ctl) {
    sections.push(
      el("div", { class: "detail-block" }, [
        el("h4", { text: "Close the loop" }),
        dl([
          ["Repair lift", pct(ctl.repair_lift)],
          ["Base runnable", pct(ctl.base_runnable)],
          ["Repaired runnable", pct(ctl.repaired_runnable)],
          ["Dry-run agreement", dryRunAgreement(ctl)],
        ]),
      ])
    );
  }

  sections.push(
    el("div", { class: "detail-block" }, [
      el("h4", { text: "Usage" }),
      dl([
        ["Generation calls", usage.generation_calls],
        ["Judge calls", usage.judge_calls],
        ["Prompt tokens", usage.prompt_tokens],
        ["Completion tokens", usage.completion_tokens],
        ["Total tokens", usage.total_tokens],
      ]),
    ])
  );

  sections.push(
    el("div", { class: "detail-block" }, [
      el("h4", { text: "Run" }),
      dl([
        ["Tool version", run.tool_version],
        ["Judge model", run.judge_model],
        ["Votes", run.n_votes],
        ["Bundle sha16", run.recorded_bundle_sha16],
        ["Verified", run.verified === undefined ? undefined : String(run.verified)],
        ["Submitted by", run.submitted_by],
      ]),
    ])
  );

  return el("td", { class: "detail-cell", colspan: "7" }, [el("div", { class: "detail" }, sections)]);
}

function renderRows(entries) {
  const tbody = document.getElementById("rows");
  tbody.replaceChildren();
  for (const entry of entries) {
    const heldRate = entry.held_out ? entry.held_out.pass_rate : null;
    const pending = heldRate === null || heldRate === undefined;

    const heldCell = el("td", { class: "num headline" }, [el("span", { text: pct(heldRate) })]);
    if (pending) {
      heldCell.replaceChildren(el("span", { class: "pending", text: "pending" }));
    }

    const modelCell = el("td", {}, [
      el("span", { class: "model", text: entry.model }),
      el("span", { class: "provider", text: entry.provider }),
    ]);

    const row = el("tr", { class: "entry", tabindex: "0", role: "button", "aria-expanded": "false" }, [
      el("td", { class: "num rank", text: String(entry.rank) }),
      modelCell,
      heldCell,
      el("td", { class: "num", text: pct(entry.public ? entry.public.pass_rate : null) }),
      el("td", { class: "num", text: gap(entry.overfit_gap) }),
      el("td", { class: "num", text: entry.close_the_loop ? pct(entry.close_the_loop.repair_lift) : "—" }),
      el("td", { class: "kind", text: entry.kind || "" }),
    ]);

    const detailRow = el("tr", { class: "detail-row", hidden: "" }, [detailPanel(entry)]);

    const toggle = () => {
      const open = detailRow.hasAttribute("hidden");
      if (open) detailRow.removeAttribute("hidden");
      else detailRow.setAttribute("hidden", "");
      row.setAttribute("aria-expanded", String(open));
    };
    row.addEventListener("click", toggle);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle();
      }
    });

    tbody.append(row, detailRow);
  }
}

function renderMeta(board) {
  const meta = document.getElementById("meta");
  const publicSet = board.public_set || {};
  const heldOutSet = board.held_out_set || {};
  meta.replaceChildren(
    dl([
      ["Eval protocol", board.eval_protocol_version],
      ["Generated", board.generated_at],
      ["Judge model", board.judge_model],
      ["Public set", `${publicSet.n_prompts ?? "?"} prompts · committed · reproduces offline`],
      [
        "Held-out set",
        `${heldOutSet.n_prompts ?? "?"} prompts · never committed · ${
          heldOutSet.store || "private store, scored in gated CI"
        }`,
      ],
    ])
  );
  meta.hidden = false;
}

async function loadBoard() {
  let board = null;
  let lastError = null;
  for (const source of BOARD_SOURCES) {
    try {
      const response = await fetch(source, { cache: "no-store" });
      if (!response.ok) {
        lastError = new Error(`${source}: HTTP ${response.status}`);
        continue;
      }
      board = await response.json();
      break;
    } catch (error) {
      lastError = error;
    }
  }

  const status = document.getElementById("status");
  if (!board) {
    status.textContent =
      "Could not load leaderboard.json. The board is published alongside this page by gated CI." +
      (lastError ? ` (${lastError.message})` : "");
    status.classList.add("error");
    return;
  }

  renderMeta(board);
  renderRows(board.entries || []);
  status.hidden = true;
  document.getElementById("board").hidden = false;
}

loadBoard();
