# bounty-finder — Developer Guide

> 中文版见 [DEVELOPERS.zh-CN.md](DEVELOPERS.zh-CN.md)。

Internal/architecture docs for people hacking on `bounty-finder`. For usage,
see [README.md](README.md).

`bounty-finder` is a **read-only** CLI that discovers open GitHub (and,
best-effort, Algora) bounty issues, ranks them, and — in deep mode — returns a
`RECOMMEND` / `WATCH` / `AVOID` verdict per issue with written reasons and red
flags. It never comments, claims, assigns, or opens PRs. Human judgement and
maintainer communication stay with the user.

---

## 1. Quick start (dev)

```bash
git clone https://github.com/harmonygemini8-collab/bounty-finder.git
cd bounty-finder
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # runtime + pytest + ruff

# GitHub auth (raises the search rate limit a lot). Either:
export GITHUB_TOKEN=ghp_xxx     # a classic/fine-grained PAT, read-only is enough
# ...or rely on the GitHub CLI:
gh auth login                   # then commands can use GH_TOKEN=$(gh auth token)

# Smoke test
GH_TOKEN=$(gh auth token) bounty-finder --curated --min-stars 500 --deep 5
```

Requirements: Python >= 3.9, one dependency (`requests`). Entry point is
`bounty_finder.cli:main` (declared in `pyproject.toml` under
`[project.scripts]`).

### Tests & lint (run before every commit)

```bash
ruff check .
pytest -q
```

Both must be green. CI parity is just these two commands.

---

## 2. Repository layout

```
bounty_finder/
  cli.py            # argparse CLI + main() orchestration (the "wiring")
  models.py         # Bounty dataclass (the shared data record)
  parsing.py        # money parsing: "$1.5k", "1,340 USD" -> float; best_amount()
  scoring.py        # fast first-pass ranking (ScoreWeights / ScoreConfig / rank)
  analysis.py       # DeepAnalyzer: per-issue verdicts (the real brain)
  report.py         # renderers: console / markdown / json (plain + deep)
  seeds.py          # CURATED_ORGS + CURATED_LABELS (high-star project seed list)
  sources/
    github.py       # GitHubSource: REST search + enrichment (primary source)
    algora.py       # AlgoraSource: best-effort, degrades to empty
tests/              # pytest unit tests (pure, no network — sources are faked)
```

### Data flow

```
discover ──► filter ──► rank (fast) ──► [deep analyze] ──► filter/sort ──► render
```

1. **discover** — `GitHubSource.search()` (generic labels) or
   `.search_orgs()` (`--curated`). Optionally `+ AlgoraSource`.
2. **filter** — `--min-stars`, `--max-age-days`, `--min-amount`.
3. **rank** — `scoring.rank()` gives a cheap first-pass score.
4. **deep** (`--deep N`) — `analysis.analyze_many()` fetches repo stats, full
   comments, and the issue timeline for the top N, producing an `Analysis` per
   issue. This supersedes the plain ranking as the shortlist.
5. **filter/sort** — `--max-attempts`, `--sort fresh`.
6. **render** — `report.*` turns results into console/markdown/json.

---

## 3. The data model — `Bounty` (`models.py`)

Central record passed through the whole pipeline. Key fields:

| field | meaning |
|-------|---------|
| `source` | `"github"` / `"algora"` |
| `repo`, `number`, `title`, `url` | issue identity |
| `amount_usd` | parsed bounty (0 if unknown; deep mode backfills from comments) |
| `labels`, `language`, `stars` | repo/issue metadata |
| `assignees`, `linked_pr_count` | competition hints (cheap pass) |
| `created_at`, `updated_at` | timestamps; `age_days` is derived |
| `body`, `comments`, `reactions` | issue content/engagement |
| `score`, `score_breakdown` | filled by `scoring.rank()` |

Only add fields here when a new signal must travel across modules; keep it a
plain dataclass.

---

## 4. Scoring vs. deep analysis — two different things

### `scoring.py` (fast, heuristic)
A weighted 0–100 sort key computed from data already in hand — **no extra API
calls**. Default `ScoreWeights`: reward `0.40`, tractability `0.25`,
competition `0.20`, activity `0.10`, stack `0.05`. Override on the CLI with
`--w-reward` etc. This is only a first pass to decide *which* issues are worth
the expensive deep look.

### `analysis.py` (slow, decisive)
`DeepAnalyzer.analyze()` produces an `Analysis` with a **verdict** and reasons.
Four sub-scores (each 0..1):

| sub-score | what it weighs |
|-----------|----------------|
| `legitimacy` | escrow platform link (Algora/BountyHub/Polar/IssueHunt/Gitpay/Boss.dev), stars, repo age, archived/fork, "bounty-farm" name heuristic |
| `openness` | assignees, merged/open/**closed** linked PRs, claim comments, Algora attempt table headcount |
| `finishability` | labels (good-first-issue vs epic/rfc), acceptance criteria / repro steps, body length → `effort` bucket |
| `maintainer` | repo push recency, whether a maintainer/collaborator posts in the thread |

**Verdict rules (hard overrides first):**
- a **merged** linked PR ⇒ `AVOID` (already solved);
- `legitimacy < 0.4` ⇒ `AVOID` (scam/farm);
- `openness < 0.3` ⇒ `AVOID` (crowded/taken);
- otherwise high combined `worth_score` with adequate legit+openness ⇒
  `RECOMMEND`, else `WATCH`.

**Competition detection is the subtle part.** Escrow bounties (esp. Algora)
attract crowds, and a naive check under-counts them. `analysis.py` therefore:
- treats `/attempt` and `/claim` slash-commands as claims (`_CLAIM_RE`);
- parses the **Algora attempts table** — one bot comment lists many
  `🟢 @user` rows (`_ATTEMPT_ROW_RE`);
- counts **closed-without-merge** attempt PRs as a "graveyard" red flag
  (many tried, none landed → hard to get merged).

`Analysis.attempts` is the competition headcount used by `--max-attempts`.

---

## 5. Sources

### `sources/github.py` — primary
Thin wrapper over the GitHub REST API. All calls are GETs (read-only).
- `search()` / `search_orgs()` — issue search over bounty labels; `sort`
  is `"created"` when the CLI asks for `--sort fresh`, else `"updated"`.
- `_repo_meta()` / `repo_stats()` — language + stars, push recency, archived.
- `issue_comments()` — full comment list (for amount backfill + competition).
- `linked_prs()` — walks the issue **timeline** for cross-referenced PRs and
  records `{number, state, merged, author}`.
- Filters out noise repos (`bug-bounty`, `bugbounty`, `security-disclosure`).

Auth: reads `GITHUB_TOKEN` / `GH_TOKEN` from the env. Never log the token.

### `sources/algora.py` — best-effort
Algora exposes no stable public bounty API; this hits an undocumented tRPC
endpoint and **degrades to an empty list** on any error. Never let it fail the
run.

BountyHub has no usable API (Cloudflare 403 on direct probing), so we only
detect its links/bot comments inside GitHub issue text.

---

## 6. Curated discovery (`seeds.py`)

`--curated` scopes discovery to `CURATED_ORGS` — established, high-star OSS
projects known to pay via Algora/Polar — searched with `CURATED_LABELS`
(the various 💎/💰/💵 "Bounty" labels + `Algora: Up for grabs`). This avoids the
low-star "bounty farm" repos that dominate a naive `label:bounty` search. To
add a project, append its **GitHub org/user login** (not a URL, no dots that
aren't part of the login) to `CURATED_ORGS`.

---

## 7. Adding things — recipes

- **New signal in the verdict:** add a field to `Analysis`, compute it inside
  the relevant `_legitimacy/_openness/_finishability/_maintainer` method, append
  to `reasons`/`red_flags`, and cover it in `tests/test_analysis.py` with a
  faked `GitHubSource` (see `FakeGH`). No network in tests.
- **New CLI filter:** add the `argparse` flag in `build_parser()`, apply it in
  `main()` at the right pipeline stage (pre-rank for cheap fields, post-deep for
  attempt-based ones), and document it in `README.md`.
- **New money format:** extend the regexes in `parsing.py` and add a case to
  `tests/test_parsing.py`.
- **New output field:** update all three renderers in `report.py`
  (console/markdown/json) so formats stay consistent.

---

## 8. Conventions & guardrails

- **Read-only, always.** No write calls to GitHub. No commenting, claiming,
  assigning, or PR creation — not now, not "just for testing".
- **Don't trust a label.** A `bounty` label ≠ money. Require escrow-platform
  evidence + openness + a responsive maintainer before recommending.
- Keep modules single-purpose; push shared state through `Bounty`/`Analysis`,
  not globals.
- Ruff config lives in `pyproject.toml` (line length 100, rulesets
  `E,F,I,W,B,UP,DTZ`). Use timezone-aware datetimes (`datetime.now(timezone.utc)`),
  never `utcnow()`.
- Secrets never get printed or committed.

---

## 9. Automation (optional)

The winnable niche is **fresh, uncontested** bounties, which vanish within a
day. A Devin Automation runs the scanner every few hours and pushes qualifying
finds to Slack:

```bash
bounty-finder --curated --sort fresh --max-attempts 1 --deep 30
bounty-finder --min-stars 50 --min-amount 30 --sort fresh --max-attempts 1 --max-fetch 100 --deep 30
```

It only reports; a human still claims and confirms the approach with the
maintainer.
