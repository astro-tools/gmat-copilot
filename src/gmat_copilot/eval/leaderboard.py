"""The per-model leaderboard engine: a ranked board over the eval suite (decision D16).

Where :mod:`gmat_copilot.eval.runner` scores **one** ``provider:model`` into an
:class:`~gmat_copilot.eval.runner.EvalReport`, this sweeps a set of explicit ``provider:model``\\ s
through the **same shipped recorded scorer** (no new scoring math) and assembles a ranked
``leaderboard.json``. Two roles for the eval set decide the ranking:

- the committed **public** prompt set is the reproducibility *anchor* — its number reproduces
  byte-for-byte offline from the recorded bundle (decision D7), pinned by the bundle's content hash;
- a never-committed **held-out** set is the *headline* — the board ranks on it, so overfitting the
  public prompts buys no rank. A large ``public - held_out`` gap is the overfit tell.

The board carries **aggregates only** (per-tier pass-rates, the close-the-loop figures, usage, and a
run block); no prompt text, intent, or judge verdict ever reaches it, so a held-out gold cannot leak
through the published JSON (:func:`assert_aggregate_only`). Held-out scoring runs only in gated CI
against a private store; offline and in per-merge CI the held-out is *pending* and the public anchor
stands alone.

The engine is pure and injection-driven: ``generated_at`` and ``tool_version`` are passed in (never
read from the clock), so a built board is byte-deterministic and testable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..providers import ProviderError
from .judge import JUDGE_MODEL
from .lift import LiftReport, run_recorded_lift
from .runner import EvalReport, run_recorded

__all__ = [
    "Aggregate",
    "BoardRow",
    "CloseTheLoop",
    "LeaderboardError",
    "RunMeta",
    "assert_aggregate_only",
    "assert_no_leak",
    "build_from_config",
    "build_leaderboard",
    "bundle_sha16",
    "dumps",
    "score_entry",
    "summarize",
]

#: The files a recorded static bundle (public or held-out) is made of — hashed, in this order, to
#: pin the result (decision D7). The close-the-loop bundle adds its own files, hashed separately.
STATIC_BUNDLE_FILES = ("prompts.json", "completions.json", "judge.json")

#: What a held-out cell says before gated CI has scored it against the never-committed set.
HELD_OUT_PENDING = "pending: scored in gated CI against the never-committed held-out set"

#: The only keys an aggregate cell may carry. Anything else would risk leaking a per-prompt gold
#: (a request, an intent, a verdict) into the published board, which
#: :func:`assert_aggregate_only` rejects. ``status`` is the pending-held-out marker.
_AGGREGATE_KEYS = frozenset({"pass_rate", "by_tier", "n_prompts", "status"})


class LeaderboardError(Exception):
    """A board failed an integrity check (a leak, or a non-reproducing row)."""


def _round(value: float) -> float:
    """Round to 3 places — the board's published precision (keeps JSON byte-stable across runs)."""
    return round(value, 3)


@dataclass(frozen=True, slots=True)
class Aggregate:
    """An aggregate-only score for one prompt set: the headline rate plus its per-tier breakdown."""

    pass_rate: float
    by_tier: dict[str, float]
    n_prompts: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass_rate": self.pass_rate,
            "by_tier": dict(self.by_tier),
            "n_prompts": self.n_prompts,
        }


@dataclass(frozen=True, slots=True)
class CloseTheLoop:
    """The v0.2 close-the-loop figures for a model (decisions D12, D13), as a board cell."""

    repair_lift: float
    base_runnable: float
    repaired_runnable: float
    dry_run_agreement: dict[str, float | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "repair_lift": self.repair_lift,
            "base_runnable": self.base_runnable,
            "repaired_runnable": self.repaired_runnable,
            "dry_run_agreement": dict(self.dry_run_agreement),
        }


@dataclass(frozen=True, slots=True)
class RunMeta:
    """The reproducibility block pinning how a row was produced (decision D16)."""

    tool_version: str
    judge_model: str
    n_votes: int
    recorded_bundle_sha16: str
    verified: bool
    submitted_by: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_version": self.tool_version,
            "judge_model": self.judge_model,
            "n_votes": self.n_votes,
            "recorded_bundle_sha16": self.recorded_bundle_sha16,
            "verified": self.verified,
            "submitted_by": self.submitted_by,
        }


@dataclass(frozen=True, slots=True)
class BoardRow:
    """One ``provider:model`` entry: public anchor, held-out headline, and close-the-loop cell."""

    provider: str
    model: str
    kind: str
    public: Aggregate
    held_out: Aggregate | None
    close_the_loop: CloseTheLoop | None
    usage: dict[str, int]
    run: RunMeta

    @property
    def overfit_gap(self) -> float | None:
        """``public - held_out`` — the overfit tell; ``None`` until the held-out has been scored."""
        if self.held_out is None:
            return None
        return _round(self.public.pass_rate - self.held_out.pass_rate)

    def to_dict(self, *, rank: int) -> dict[str, Any]:
        held_out = (
            self.held_out.to_dict()
            if self.held_out is not None
            else {"pass_rate": None, "status": HELD_OUT_PENDING}
        )
        return {
            "rank": rank,
            "provider": self.provider,
            "model": self.model,
            "kind": self.kind,
            "public": self.public.to_dict(),
            "held_out": held_out,
            "overfit_gap": self.overfit_gap,
            "close_the_loop": self.close_the_loop.to_dict() if self.close_the_loop else None,
            "usage": dict(self.usage),
            "run": self.run.to_dict(),
        }


def summarize(report: EvalReport) -> Aggregate:
    """The aggregate-only view of an eval report — the only thing a board row carries from it."""
    return Aggregate(
        pass_rate=_round(report.pass_rate),
        by_tier={tier: _round(rate) for tier, rate in sorted(report.pass_rate_by_tier.items())},
        n_prompts=len(report.outcomes),
    )


def close_the_loop_from_lift(report: LiftReport) -> CloseTheLoop:
    """Fold a :class:`LiftReport` into the board's close-the-loop cell (decisions D12, D13)."""
    return CloseTheLoop(
        repair_lift=_round(report.lift),
        base_runnable=_round(report.base_runnable),
        repaired_runnable=_round(report.repaired_runnable),
        dry_run_agreement={
            tier: (_round(value) if value is not None else None)
            for tier, value in sorted(report.dry_run_agreement_by_tier.items())
        },
    )


def bundle_sha16(bundle: Path, names: Sequence[str] = STATIC_BUNDLE_FILES) -> str:
    """The 16-hex content hash over *names* in *bundle* — pins a recorded result (decision D7)."""
    digest = hashlib.sha256()
    for name in names:
        digest.update((bundle / name).read_bytes())
    return digest.hexdigest()[:16]


def _key_model(key: str) -> str:
    """The ``model`` from a recorded ``provider:model:digest`` key (the model may hold a ``/``)."""
    provider_model = key.rsplit(":", 1)[0]  # drop the trailing :digest
    _, _, model = provider_model.partition(":")
    return model


def recorded_usage(bundle: Path, *, model: str, n_votes: int) -> dict[str, int]:
    """Sum *model*'s recorded generation usage in *bundle*, plus the implied judge-call count.

    Judge usage is not recorded, so ``judge_calls`` is derived as generations times the vote count —
    the free-tier transparency the board publishes (decision D16), not a measured token total.
    """
    completions: dict[str, Any] = json.loads((bundle / "completions.json").read_text("utf-8"))
    totals: dict[str, int] = {}
    generations = 0
    for key, entry in completions.items():
        if _key_model(key) != model:
            continue
        generations += 1
        for field, value in (entry.get("usage") or {}).items():
            if isinstance(value, int):
                totals[field] = totals.get(field, 0) + value
    return {"generation_calls": generations, "judge_calls": generations * n_votes, **totals}


def score_entry(
    model: str,
    *,
    public_bundle: str | Path,
    tool_version: str,
    held_out_bundle: str | Path | None = None,
    lift_bundle: str | Path | None = None,
    provider: str = "recorded",
    kind: str = "seed",
    n_votes: int = 3,
    judge_model: str = JUDGE_MODEL,
    submitted_by: str = "seed",
    verified: bool = True,
) -> BoardRow:
    """Score one ``provider:model`` into a :class:`BoardRow` through the shipped recorded scorer.

    The **public** number comes from replaying *public_bundle* (deterministic, quota-free, D7); the
    **held-out** number, when *held_out_bundle* is given, from replaying it the same way (gated CI
    only — the bundle is never committed); the **close-the-loop** cell, when *lift_bundle* is given,
    from the recorded lift replay. ``run_recorded`` raises :class:`ProviderError` if *model* is
    missing from a bundle — the caller decides whether to skip the seed or fail.
    """
    public_dir = Path(public_bundle)
    public = summarize(run_recorded(public_dir, model=model))
    held_out = (
        summarize(run_recorded(Path(held_out_bundle), model=model))
        if held_out_bundle is not None
        else None
    )
    close_the_loop = (
        close_the_loop_from_lift(run_recorded_lift(Path(lift_bundle)))
        if lift_bundle is not None
        else None
    )
    run = RunMeta(
        tool_version=tool_version,
        judge_model=judge_model,
        n_votes=n_votes,
        recorded_bundle_sha16=bundle_sha16(public_dir),
        verified=verified,
        submitted_by=submitted_by,
    )
    return BoardRow(
        provider=provider,
        model=model,
        kind=kind,
        public=public,
        held_out=held_out,
        close_the_loop=close_the_loop,
        usage=recorded_usage(public_dir, model=model, n_votes=n_votes),
        run=run,
    )


def _sort_key(row: BoardRow) -> tuple[int, float, str]:
    """Rank by held-out pass-rate descending (the headline); a pending held-out sorts last."""
    rate = row.held_out.pass_rate if row.held_out is not None else None
    return (0 if rate is not None else 1, -(rate or 0.0), row.model)


def build_leaderboard(
    rows: Iterable[BoardRow],
    *,
    eval_protocol_version: str,
    generated_at: str,
    judge_model: str,
    public_set: dict[str, Any],
    held_out_set: dict[str, Any],
) -> dict[str, Any]:
    """Assemble a ranked ``leaderboard.json`` payload — ranked on the held-out headline (D16).

    *generated_at* is injected (never read from the clock) so the payload is byte-deterministic. The
    public anchor is shown alongside the headline; a pending held-out sorts last.
    """
    ranked = sorted(rows, key=_sort_key)
    return {
        "eval_protocol_version": eval_protocol_version,
        "generated_at": generated_at,
        "judge_model": judge_model,
        "ranking": "held_out.pass_rate desc - the headline; public shown alongside as the anchor",
        "public_set": dict(public_set),
        "held_out_set": dict(held_out_set),
        "entries": [row.to_dict(rank=rank) for rank, row in enumerate(ranked, start=1)],
    }


def dumps(board: dict[str, Any]) -> str:
    """Canonical board bytes: sorted-key, 2-space JSON with a trailing newline (stable diffs)."""
    return json.dumps(board, indent=2, sort_keys=True) + "\n"


def assert_aggregate_only(board: dict[str, Any]) -> None:
    """Raise :class:`LeaderboardError` if a row's public/held-out cell carries a non-aggregate key.

    The firewall the published board must satisfy (decision D16): a board carries pass-rates and
    metadata only, never a prompt, an intent, or a judge verdict — so a held-out gold cannot leak
    through it. A row exposing an unexpected key in an aggregate cell is rejected.
    """
    for row in board.get("entries", []):
        for cell_name in ("public", "held_out"):
            cell = row.get(cell_name, {})
            unexpected = set(cell) - _AGGREGATE_KEYS
            if unexpected:
                raise LeaderboardError(
                    f"row {row.get('model')!r} {cell_name} cell exposes non-aggregate keys "
                    f"{sorted(unexpected)} — the board must be aggregate-only"
                )


def assert_no_leak(serialized: str, secrets: Iterable[str]) -> None:
    """Raise if any held-out *secret* string appears in the serialized board (a hard leak check)."""
    for secret in secrets:
        if secret and secret in serialized:
            raise LeaderboardError("a held-out gold leaked into the published board")


def build_from_config(
    config: dict[str, Any],
    *,
    root: Path,
    generated_at: str,
    tool_version: str,
    held_out_root: Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Build a board from a *seeds* config, resolving bundle paths under *root*.

    Returns the board payload and a list of human-readable notes for seeds that were skipped (their
    public bundle was absent or did not carry the model — e.g. a live-only seed run offline). A seed
    is scored against its held-out bundle only when *held_out_root* is given and that bundle exists,
    so offline and in per-merge CI every held-out cell is pending. Held-out golds are never
    committed: the held-out bundles live under *held_out_root* (a gitignored cache fetched in gated
    CI), never in the repo tree.
    """
    notes: list[str] = []
    rows: list[BoardRow] = []
    for seed in config.get("seeds", []):
        model = seed["model"]
        public_dir = root / seed["public_bundle"]
        if not (public_dir / "completions.json").exists():
            notes.append(f"skip {model}: no recorded public bundle at {seed['public_bundle']}")
            continue
        lift_bundle = root / seed["lift_bundle"] if seed.get("lift_bundle") else None
        held_out_bundle = None
        if held_out_root is not None and seed.get("held_out_bundle"):
            candidate = held_out_root / seed["held_out_bundle"]
            if (candidate / "completions.json").exists():
                held_out_bundle = candidate
        try:
            rows.append(
                score_entry(
                    model,
                    public_bundle=public_dir,
                    tool_version=tool_version,
                    held_out_bundle=held_out_bundle,
                    lift_bundle=lift_bundle,
                    provider=seed.get("provider", "recorded"),
                    kind=seed.get("kind", "seed"),
                    n_votes=int(config.get("n_votes", 3)),
                    judge_model=config.get("judge_model", JUDGE_MODEL),
                    submitted_by=seed.get("submitted_by", "seed"),
                )
            )
        except ProviderError as exc:
            notes.append(f"skip {model}: {exc}")
    board = build_leaderboard(
        rows,
        eval_protocol_version=str(config.get("eval_protocol_version", "1")),
        generated_at=generated_at,
        judge_model=config.get("judge_model", JUDGE_MODEL),
        public_set=config.get("public_set", {}),
        held_out_set=config.get("held_out_set", {}),
    )
    return board, notes
