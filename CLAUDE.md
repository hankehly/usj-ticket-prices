## Communication
- Speak in simple, plain English whenever possible. Lead with non-technical framing (motivation, what changed, what success looks like) and keep math, code paths, and implementation detail in lower sections or appendices.
- Decision rules belong in tables with concrete numerical thresholds, not prose.

## Git conventions
- Unless told otherwise, make the code changes for a PR in a separate git worktree under `.claude/worktrees/` (gitignored), not in the main checkout, which stays on `main` for other work.
- Branches follow [Conventional Branch](https://conventionalbranch.org/)
- Commits follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)

## Agent skills

### Issue tracker

Issues live in GitHub Issues for hankehly/usj-ticket-prices, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles use their default label names. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
