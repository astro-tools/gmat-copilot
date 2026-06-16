# Contributing

Thanks for your interest in gmat-copilot.

## Getting set up

The project uses [uv](https://docs.astral.sh/uv/). From a clone:

```bash
uv sync --all-groups
```

That installs the package, the dev tools, and the docs tools. No GMAT install and no model
credential are needed to develop or run the test suite — generation, lint validation, and the
recorded eval path are all GMAT-free and model-free.

To exercise a provider locally, add its extra and set the credential in your environment:

```bash
uv sync --all-groups --extra anthropic   # then export ANTHROPIC_API_KEY
```

## Local checks before pushing

CI runs exactly these — run them locally first:

```bash
uv run ruff check              # lint
uv run ruff format --check     # formatting (this is part of the lint gate in CI)
uv run mypy                    # types (strict)
uv run pytest                  # tests
```

The deterministic recorded-provider eval-smoke runs under `pytest -m eval_smoke`; it makes no model
calls. To build the docs site locally: `uv run mkdocs serve`.

## Branches and PRs

- Branch from `main`; name branches with a type prefix (`feat/`, `fix/`, `chore/`, `docs/`).
- Keep commits small and logically scoped, with short imperative subjects.
- PRs are squash-merged. Reference the issue a PR closes with `Closes #N` in the body so it
  auto-closes on merge.

## Scope

Generation and validation stay GMAT-free; the optional GMAT dry-run lives behind the `[gmat]` extra.
Keep the base install light — provider SDKs and the GMAT stack are extras, never base dependencies.

## Questions

For usage questions or ideas, open a thread in the
[org discussions](https://github.com/orgs/astro-tools/discussions) rather than an issue.
