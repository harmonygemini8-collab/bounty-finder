# bounty-finder — 开发者指南（中文版）

> 本文是面向开发者的架构/贡献文档。英文版见 [DEVELOPERS.md](DEVELOPERS.md);
> 使用说明见 [README.md](README.md)。

`bounty-finder` 是一个**只读**的命令行工具:发现 GitHub(以及尽力而为的
Algora)上的开放赏金 issue,进行排序,并在深度模式下对每个 issue 给出
`RECOMMEND`(推荐)/ `WATCH`(观望)/ `AVOID`(避免)的结论,附带书面理由和红旗提示。
它**绝不**评论、抢单(claim)、认领(assign)或提交 PR。判断和与维护者的沟通,
始终由使用者本人完成。

---

## 1. 快速上手(开发环境)

```bash
git clone https://github.com/harmonygemini8-collab/bounty-finder.git
cd bounty-finder
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # 运行时依赖 + pytest + ruff

# GitHub 鉴权(能大幅提高搜索速率上限)。二选一:
export GITHUB_TOKEN=ghp_xxx     # 经典或细粒度 PAT,只读权限即可
# ……或者用 GitHub CLI:
gh auth login                   # 之后命令可用 GH_TOKEN=$(gh auth token)

# 冒烟测试
GH_TOKEN=$(gh auth token) bounty-finder --curated --min-stars 500 --deep 5
```

环境要求:Python >= 3.9,仅一个依赖(`requests`)。程序入口是
`bounty_finder.cli:main`(在 `pyproject.toml` 的 `[project.scripts]` 中声明)。

### 测试与 lint(每次提交前必跑)

```bash
ruff check .
pytest -q
```

两者都必须全绿。CI 等价于就跑这两条命令。

---

## 2. 仓库结构

```
bounty_finder/
  cli.py            # argparse 命令行 + main() 编排(“接线”层)
  models.py         # Bounty 数据类(贯穿全流程的共享记录)
  parsing.py        # 金额解析:"$1.5k"、"1,340 USD" -> float;best_amount()
  scoring.py        # 快速的第一遍排序(ScoreWeights / ScoreConfig / rank)
  analysis.py       # DeepAnalyzer:逐 issue 出结论(真正的“大脑”)
  report.py         # 渲染器:console / markdown / json(普通版 + 深度版)
  seeds.py          # CURATED_ORGS + CURATED_LABELS(高 star 项目种子库)
  sources/
    github.py       # GitHubSource:REST 搜索 + 富化(主数据源)
    algora.py       # AlgoraSource:尽力而为,失败时降级为空
tests/              # pytest 单元测试(纯函数、不触网,数据源被 fake 掉)
```

### 数据流

```
发现 ──► 过滤 ──► 排序(快) ──► [深度分析] ──► 过滤/排序 ──► 渲染
```

1. **发现** — `GitHubSource.search()`(通用标签)或 `.search_orgs()`(`--curated`)。
   可选 `+ AlgoraSource`。
2. **过滤** — `--min-stars`、`--max-age-days`、`--min-amount`。
3. **排序** — `scoring.rank()` 给出一个廉价的第一遍分数。
4. **深度**(`--deep N`) — `analysis.analyze_many()` 对前 N 个抓取仓库数据、
   完整评论区和 issue 时间线,为每个 issue 产出一个 `Analysis`。此结果会**取代**
   普通排序,作为最终候选清单。
5. **过滤/排序** — `--max-attempts`、`--sort fresh`。
6. **渲染** — `report.*` 输出为 console/markdown/json。

---

## 3. 数据模型 —— `Bounty`(`models.py`)

贯穿整个流程的核心记录。关键字段:

| 字段 | 含义 |
|------|------|
| `source` | `"github"` / `"algora"` |
| `repo`、`number`、`title`、`url` | issue 标识 |
| `amount_usd` | 解析出的赏金(未知为 0;深度模式会从评论区回填) |
| `labels`、`language`、`stars` | 仓库/issue 元数据 |
| `assignees`、`linked_pr_count` | 竞争线索(廉价那一遍) |
| `created_at`、`updated_at` | 时间戳;`age_days` 由其派生 |
| `body`、`comments`、`reactions` | issue 正文/互动度 |
| `score`、`score_breakdown` | 由 `scoring.rank()` 填充 |

只有当一个新信号需要跨模块传递时,才往这里加字段;保持它是个普通 dataclass。

---

## 4. 排序 vs. 深度分析 —— 两件不同的事

### `scoring.py`(快速、启发式）
一个加权 0–100 的排序键,完全基于已有数据计算,**不产生额外 API 调用**。
默认 `ScoreWeights`:reward `0.40`、tractability `0.25`、competition `0.20`、
activity `0.10`、stack `0.05`。命令行可用 `--w-reward` 等覆盖。这只是第一遍,
用来决定*哪些* issue 值得做后续昂贵的深度分析。

### `analysis.py`(慢、决定性)
`DeepAnalyzer.analyze()` 产出带**结论**和理由的 `Analysis`。四个子分(各 0..1):

| 子分 | 衡量什么 |
|------|----------|
| `legitimacy`(真实性) | 是否挂托管平台链接(Algora/BountyHub/Polar/IssueHunt/Gitpay/Boss.dev)、star、仓库年龄、是否归档/fork、“刷量农场”名称启发式 |
| `openness`(开放度) | assignee、已合并/开放/**已关闭**的关联 PR、抢单评论、Algora attempt 表人数 |
| `finishability`(可完成度) | 标签(good-first-issue vs epic/rfc)、有无验收标准/复现步骤、正文长度 → `effort` 工作量档位 |
| `maintainer`(维护者) | 仓库最近推送时间、维护者/协作者是否在该 issue 里发言 |

**结论规则(硬性覆盖优先):**
- 存在**已合并**的关联 PR ⇒ `AVOID`(已被做完);
- `legitimacy < 0.4` ⇒ `AVOID`(骗局/农场);
- `openness < 0.3` ⇒ `AVOID`(拥挤/已被占);
- 否则综合 `worth_score` 高、且 legit+openness 达标 ⇒ `RECOMMEND`,其余 ⇒ `WATCH`。

**竞争检测是最微妙的一环。** 托管赏金(尤其 Algora)会吸引大量人抢,天真的检查会
严重低估竞争。因此 `analysis.py`:
- 把 `/attempt`、`/claim` 斜杠命令当作抢单(`_CLAIM_RE`);
- 解析 **Algora 的 attempt 表** —— 一条机器人评论里列了很多 `🟢 @user` 行
  (`_ATTEMPT_ROW_RE`);
- 把**已关闭但未合并**的尝试 PR 统计为“赏金坟场”红旗(很多人试过、无人成功
  → 极难被合并)。

`Analysis.attempts` 就是 `--max-attempts` 所用的竞争人数。

---

## 5. 数据源

### `sources/github.py` —— 主数据源
对 GitHub REST API 的薄封装。所有调用都是 GET(只读)。
- `search()` / `search_orgs()` —— 按赏金标签搜索 issue;当命令行用 `--sort fresh`
  时 `sort` 为 `"created"`,否则为 `"updated"`。
- `_repo_meta()` / `repo_stats()` —— 语言 + star、推送时间、是否归档。
- `issue_comments()` —— 完整评论列表(用于金额回填 + 竞争检测)。
- `linked_prs()` —— 遍历 issue **时间线**中被交叉引用的 PR,记录
  `{number, state, merged, author}`。
- 过滤噪音仓库(`bug-bounty`、`bugbounty`、`security-disclosure`)。

鉴权:从环境变量读 `GITHUB_TOKEN` / `GH_TOKEN`。**绝不打印 token。**

### `sources/algora.py` —— 尽力而为
Algora 没有稳定的公开赏金 API;这里请求一个未文档化的 tRPC 端点,任何错误都
**降级为空列表**。绝不能让它把整个运行搞挂。

BountyHub 没有可用 API(直接探测会被 Cloudflare 403),所以我们只在 GitHub issue
文本里检测它的链接/机器人评论。

---

## 6. Curated 精选发现(`seeds.py`)

`--curated` 把发现范围限定到 `CURATED_ORGS` —— 一批成熟、高 star、已知会通过
Algora/Polar 付款的开源项目 —— 并用 `CURATED_LABELS`(各种 💎/💰/💵 “Bounty”
标签 + `Algora: Up for grabs`)搜索。这样能避开天真 `label:bounty` 搜索里占多数的
低 star “刷量农场”仓库。要新增项目,把它的 **GitHub org/user 登录名**(不是 URL,
且不要带非登录名一部分的点号)追加到 `CURATED_ORGS`。

---

## 7. 扩展配方

- **在结论里加新信号:** 给 `Analysis` 加字段,在相应的
  `_legitimacy/_openness/_finishability/_maintainer` 方法里计算,追加到
  `reasons`/`red_flags`,并在 `tests/test_analysis.py` 里用被 fake 的
  `GitHubSource`(见 `FakeGH`)覆盖测试。测试不触网。
- **加新的命令行过滤:** 在 `build_parser()` 里加 `argparse` 参数,在 `main()`
  的正确流程阶段应用它(廉价字段在排序前,基于 attempt 的在深度分析后),并在
  `README.md` 里补文档。
- **加新的金额格式:** 扩展 `parsing.py` 里的正则,并在 `tests/test_parsing.py`
  加一个用例。
- **加新的输出字段:** 同步更新 `report.py` 里三个渲染器(console/markdown/json),
  保持各格式一致。

---

## 8. 约定与红线

- **永远只读。** 不对 GitHub 做任何写操作。不评论、不抢单、不认领、不发 PR ——
  现在不,“只是测试一下”也不。
- **别只看标签。** 有 `bounty` 标签 ≠ 有钱。推荐之前必须要有托管平台证据 + 开放度 +
  活跃的维护者。
- 各模块单一职责;共享状态走 `Bounty`/`Analysis`,不要用全局变量。
- Ruff 配置在 `pyproject.toml`(行宽 100,规则集 `E,F,I,W,B,UP,DTZ`)。使用带时区的
  datetime(`datetime.now(timezone.utc)`),不要用 `utcnow()`。
- 密钥绝不打印、绝不提交。

---

## 9. 自动化(可选)

真正能赚钱的窄门是**刚发布、还没人抢**的赏金,而它们往往一天之内就被抢光。
可以用 Devin Automation 每隔几小时跑一次扫描,把符合条件的结果推送到 Slack:

```bash
bounty-finder --curated --sort fresh --max-attempts 1 --deep 30
bounty-finder --min-stars 50 --min-amount 30 --sort fresh --max-attempts 1 --max-fetch 100 --deep 30
```

它只负责上报;抢单和与维护者确认思路,仍由人来做。
