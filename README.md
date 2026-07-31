# bounty-finder

A **read-only** assistant that discovers open bounty-bearing GitHub issues,
scores them by expected value for a bounty hunter, and prints a ranked
shortlist you can act on.

> **This tool does not comment, claim, assign, or open pull requests.**
> It only reads public data. Claiming a bounty and talking to maintainers is
> something you do yourself, as a real person — mass-automating those steps
> gets accounts banned and PRs rejected, and it is *not* how bounties actually
> pay out. The money comes from genuinely solving a well-scoped issue.

## Why

Bounty boards are noisy. The highest-dollar issues (e.g. a decade-old
"WearOS support" mega-feature) are usually the *worst* use of your time:
huge scope, many competitors, low odds of a payout. This tool surfaces issues
that are actually **finishable and winnable** by weighing reward against
tractability, competition, freshness, and how well the repo matches your stack.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

`requests` is the only runtime dependency.

## Authentication

Uses a GitHub token for a usable rate limit. It is picked up automatically from
`GITHUB_TOKEN` / `GH_TOKEN`, or from the `gh` CLI (`gh auth token`) if you have
[`gh`](https://cli.github.com/) logged in. Without a token you are limited to
GitHub's low unauthenticated search rate.

## Usage

```bash
# Curated crawl: only high-star OSS projects that actually pay, deep-analyzed
bounty-finder --curated --min-stars 500 --deep 15 --format markdown -o report.md

# Top 15 bounties across GitHub, refined for the top 10
bounty-finder

# Only Python bounties worth >= $100, as a markdown report
bounty-finder --lang Python --min-amount 100 --format markdown -o shortlist.md

# Bias toward small, finishable tasks and away from crowded ones
bounty-finder --w-tractability 0.4 --w-competition 0.3 --w-reward 0.2

# Restrict with raw GitHub search qualifiers
bounty-finder --qualifiers "language:Go -label:wontfix created:>2025-01-01"
```

Run `bounty-finder --help` for all flags.

### Output

`console` (default), `markdown`, or `json` via `--format`. The competition
column flags issues as `open` / `busy` / `HOT (crowded)` based on assignees,
linked PRs, and comment volume.

### Deep analysis (`--deep N`)

The plain ranking is a fast first pass. `--deep N` then investigates the top
`N` candidates and returns a **verdict** — `RECOMMEND` / `WATCH` / `AVOID` —
with written reasons and red flags, so you know *why* an issue is (or isn't)
worth your time:

```bash
# Deep-analyze the top 8 bounties over $100
bounty-finder --min-amount 100 --deep 8 --format markdown -o report.md

# Deep-dive a specific repo's bounties
bounty-finder --qualifiers "repo:microg/GmsCore" --deep 5
```

For each issue it fetches repo stats, the full comment thread, and the issue
timeline, then judges four things:

| Signal | What it checks |
|--------|----------------|
| **legitimacy** | escrow platform link (Algora/BountyHub/Polar/…), repo stars/age, archived/fork, "bounty-farm" repo detection |
| **openness** | assignees, **merged** linked PRs (already solved), open competing PRs, people who publicly claimed it |
| **finishability** | labels (good-first-issue vs epic), presence of acceptance criteria, body length |
| **maintainer** | repo push recency, whether a maintainer is participating in the thread |

A merged linked PR or failing legitimacy forces `AVOID`. In practice, most
issues carrying a generic `bounty` label turn out to be `AVOID` (farms,
already-solved, or swarmed) — which is exactly why this step matters.

## How scoring works

Each issue gets a 0–100 score combining five normalized components with
configurable weights (`--w-*`):

| Component | Meaning | Default weight |
|-----------|---------|---------------:|
| reward | bounty size (log-scaled, capped) | 0.40 |
| tractability | finishable? (labels + body length) | 0.25 |
| competition | is anyone already on it? | 0.20 |
| activity | recently active? | 0.10 |
| stack | matches `--lang`? | 0.05 |

See `bounty_finder/scoring.py` for the exact formulas.

## Curated high-star discovery (`--curated`)

A naive `label:bounty` search is dominated by low-star "bounty farms".
`--curated` instead scopes discovery to a seed list of established, high-star
OSS projects known to pay bounties through Algora/Polar (cal.com, coolify,
twenty, activepieces, highlight, microG, …; see `bounty_finder/seeds.py`).
Combine with `--min-stars N` to drop anything below a popularity threshold and
`--deep` to get verdicts. This is the recommended way to find issues actually
worth your time.

## Data sources

- **GitHub** (primary, reliable): REST search API over bounty labels, plus
  amount refinement from BountyHub/Algora bot comments and a linked-PR
  competition probe for the shortlist.
- **Algora** (best-effort, optional via `--algora-org`): Algora has no stable
  public bounty API, so this source degrades gracefully to empty when the
  undocumented endpoint changes.

## Ethics

This is a decision aid. Use it to find issues worth your time, then engage
honestly: read the issue, confirm the approach with the maintainer, and only
claim what you will actually deliver.

## Development

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```
