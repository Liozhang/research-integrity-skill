---
name: research-integrity
description: >
  网络/学术调研的全流程质量协议，保证调研结果的全面性、引用来源的真实性、结论的有效性。当用户要求调研、深度研究、文献综述、行业/竞品/技术/产品调研、查证某个说法或某条引用是否真实、或对既有报告的引用可信度提出质疑时使用。内置三条铁律（没读到正文不进参考文献、查不到的专有名词直接删、未找到必须留检索痕迹）、九阶段流水线、工具路由与升级路径、引用编号规范、检索日志模板，以及引用可达性自检脚本。
---

# Research Integrity — 调研质量与引用真实性保障

## Overview

ZCode 没有自动引文校验引擎，调研质量完全由流程保证。本 skill 把"全面、真实、有效"三性落成可执行的流水线、门禁与自检脚本。适用于任何需要联网取证并产出带引用报告的调研任务；也适用于复核既有报告的引用可信度。

## 铁律（最高优先级，违反任何一条即任务失败）

1. **没读到正文的来源，不进参考文献表。** 搜索摘要、标题、转述都不算；抓取被反爬/CAPTCHA/付费墙阻断时，降级为"搜索命中、正文待验证"，并尝试升级抓取通道。
2. **查不到的专有名词直接删，不猜、不补全。** 项目名、机构名、产品型号、卷期页码、DOI/PMID，检索不到就删除或标注待验证；模型记忆不等于检索结果。
3. **"未找到"必须留下检索痕迹。** 否定结论（"某领域研究为零"）同样要给证据：用了哪些检索词、哪些库、返回什么。无痕迹的否定视为编造。

## 三性保证框架

| 维度 | 典型失效模式 | 核心对策 | 过门禁条件 |
|---|---|---|---|
| **全面性** | 单一检索词、单一来源、语言偏见、只找支持性证据（确认偏误） | 查询矩阵（同义词/缩写/全称 × 中英 × MeSH 式主题词，每子问题 ≥5 组独立查询）；来源分层（学术库 + 厂商官方 + 监管 + 临床注册 + 中文源）；主动反向检索（反证、阴性结果、复现失败、质疑评论）；空白点显式登记 | 每个子结论 ≥2 个独立来源；"未找到"附检索痕迹 |
| **真实性** | 摘要冒充全文、记忆冒充检索、卷期页码编造、不存在的项目名混入、二手转述污染、反爬阻断后硬写 | 来源分级（一级=原始论文/官方/监管文件 > 二级=综述/新闻 > 三级=转述）；fetch-to-cite；可核验字段逐项核对（DOI/PMID/URL+访问日期）；专有名词存在性检索；结论三级标注 | 每条引用可点开；任何不确定字段标"待验证"，禁止补全 |
| **有效性** | 问题不聚焦、结论过宽、相关当因果、把 RUO 说成临床可用、忽视时效 | 问题拆解（先定义场景与适用边界再检索）；证据分级且样本量/效应量随行；时效与版本标注（数据年份、试剂盒/软件版本、共识版本）；适用范围声明；附检索日志保证可复现 | 结论带置信度 + 翻转条件；报告必含"已知局限/未覆盖"节 |

## 九阶段流水线

每阶段有过门条件，不过就退回上一阶段，不要带着疑点往下走。

```
① 定义问题      → 产出：子问题清单 + 每个子问题的判定标准（什么算答上来）
② 建查询矩阵    → 产出：检索词表（同义词/缩写/全称 × 中英 × 来源类型）
③ 并行检索      → 产出：候选来源列表（URL + 标题 + 来源类型 + 检索词编号）
④ 抓取正文      → 产出：已读正文清单 + 关键摘录；被阻断的进"待验证"队列
⑤ 交叉验证      → 产出：事实表（事实 | 来源编号 | 来源级别 | 一致性）；冲突显式列出，不强行调和
⑥ 证据分级编号  → 产出：引用表（编号 ↔ URL ↔ 访问日期 ↔ 来源级别）；结论标 [文献原文]/[检索命中未读全文]/[推断]
⑦ 撰写          → 产出：报告正文，每句关键结论可回溯到事实表行
⑧ 自检          → 产出：citation_audit.py 退出码 0/1 + 人审第二关"有效" + 字段核对
⑨ 交付          → 产出：报告 + 检索日志 + 已知局限/未覆盖清单
```

阶段③④的工具选择见 [references/tool-routing.md](references/tool-routing.md)；阶段⑨的交付物格式见 [references/report-template.md](references/report-template.md)。

## 工具路由要点

- 默认链路：`web-search-prime`（检索）→ `web-reader` / `WebFetch`（正文）。
- **元数据核验走权威 API，不走页面抓取**：PubMed/PMC 条目用 NCBI E-utilities（`esummary` + ID Converter，`citation_audit.py --pmid-api` 已内置）；有 DOI 的条目用 Crossref（`api.crossref.org/works/<DOI>`）。结构化、无反爬、可判定"该文献是否存在"。
- `web-reader` 被反爬阻断（CAPTCHA、登录墙、JS 渲染）时，按序升级：换镜像/开放获取版本 → PubMed/Europe PMC 条目页 → `browser-use:control-browser` 或 playwright-mcp 真实浏览器通道。升级仍失败才记"待验证"。
- 部分搜索/抓取类 skill 依赖本地网关服务签发 token（端口与端点见你环境中对应 skill 的说明），端口无监听时不可用，先用自检命令确认再用。
- 浏览器类通道（browser-agent / control-browser / playwright-mcp）的截图与视觉转述属三级证据，只能用于定位线索，不能直接作为引用。

## 引用纪律

1. **编号唯一且稳定**：正文引用编号与文末参考文献表严格一一对应，不跳号、不合并、不事后重排（代码强制：编号连续 + 无悬空引用 + 无孤引）。
2. **每个来源记录五元组**：`编号 | 标题 | URL | 访问日期 | 来源级别 | 验证状态`，缺一项即 FAIL。完整列格式见 [references/report-template.md](references/report-template.md)。
3. **三级标注**：`[文献原文]` 正文读过；`[检索命中未读全文]` 只有标题/摘要；`[推断]` 我的推理，不挂引用。
4. **可核验字段**：作者、年份、期刊、卷期页、DOI/PMID 逐项与检索结果核对；对不上就删字段，不要"合理化"。
5. **冲突不调和**：两个来源矛盾时并列呈现，说明差异可能原因（人群、方法、年份），不选一个当真理。
6. **来源独立性**：同一研究的新闻稿、机构通稿、二次转述只算一个来源；"≥2 独立来源"指互相独立的原始出处。

引用的两层保证（真实 ≠ 有效）、六步生命周期、失败处置表见 [references/citation-verification.md](references/citation-verification.md)。

## 交付前自检（确定性规则一律由代码强制）

**原则：凡是能用代码判定的，不许靠自觉。** 代码判不了的（正文是否真支持该句、证据是否冲突）才留给人审，且必须显式记录。

### 1) 报告级审计（默认入口）

```bash
# markdown / HTML 报告都可直接审（自动识别格式）
python scripts/citation_audit.py report.md  --pmid-api --doi-api
python scripts/citation_audit.py report.html --pmid-api --doi-api   # HTML：自动解析文献列表与正文上标
python scripts/citation_audit.py report.md --ledger citations.csv --pmid-api
python scripts/citation_audit.py report.md --no-network --json    # 离线结构审计 / 机读输出
```

退出码：`0`=PASS ｜ `1`=仅 WARN（需人工处置）｜ `2`=FAIL（不得交付）｜ `3`=输入错误。

**权威元数据核验（确定性高于抓页面，务必加）**：

- `--pmid-api`：URL 含 PMID、台账有 `PMID` 列、URL 是 PMC 文章（ID Converter 自动转换）、或有 DOI（esearch 反查 PMID）的条目，走 NCBI E-utilities `esummary`，核对标题/期刊/年份并**判定 PMID 是否真实存在**。
- `--doi-api`：其余含 DOI 的条目走 Crossref，核对标题/期刊/年份并**判定 DOI 是否存在**。
- 已核验条目不重复抓页面；非 PMID/DOI 条目才走页面抓取，被挡再按 tool-routing 升级。

代码强制的 **FAIL** 规则（任一不过即不得交付）：

- 存在参考文献小节（markdown `## 参考文献` + 管道表，或 HTML 含链接的 `<ol><li>` 列表）
- 编号从 1 连续、无重复
- 每条有 URL 且为 http(s)
- 访问日期是有效日历日期（拒绝 `2026-13-99`）且不晚于今天（HTML 模式取审计当天）
- 来源级别 ∈ {一级, 二级, 三级}（HTML 模式按来源类型启发式推测，需人工确认）
- 验证状态 ∈ {已读全文, 待验证}
- PMID/DOI 在权威库真实存在
- 标题与权威元数据/页面标题一致（归一化包含 / 词覆盖 ≥0.8 / Jaccard ≥0.6，防张冠李戴）
- URL 可达（403/429/503、反爬过渡页、DOI 重定向页归 BLOCKED，不判 FAIL）
- 正文无悬空引用：正文 `[n]`/`[n,m]`/`[n-m]` 编号 ⊆ 表中编号

代码标记的 **WARN**（同质项自动折叠成一行）：BLOCKED 条目、待验证条目、孤引（表里有而正文从未引用）、同一 URL 重复出现、年份/期刊与权威元数据不一致。

### 2) 快速 URL 清单核对

```bash
python scripts/check_citations.py citations.txt   # 每行 "URL" 或 "URL | 期望标题关键词"
```

### 3) 必须人审的（代码判不了，不许跳过）

- **第二关"有效"**：正文原句是否支持被引的那一句。流程、判定档位与论断台账见 [references/claim-verification.md](references/claim-verification.md)——**报告里每个具体数字都必须能在所引来源里找到原句**，摘要里没有的就取全文，取不到就删。
- 证据冲突的并列呈现、结论置信度与翻转条件
- 检索日志完整可复现、已知局限写清

**BLOCKED 的正确解读**：脚本用裸 HTTP 客户端访问，`BLOCKED` 只说明*这个通道*被挡，不等于来源无效——先按 tool-routing 的升级链换浏览器通道重试，仍失败才标"待验证"。反之 `OK` 也不等于内容支持结论，标题核对只防张冠李戴。

## 反模式清单（禁止）

- 用搜索摘要的措辞充当全文结论
- 把厂商宣传页、产品通稿当作独立第三方证据
- 凭模型记忆补全卷期页码、影响因子、作者机构
- 引用打不开的链接却不标注
- 单一来源支撑关键量化结论
- 二手转述不标"转述"
- 相关关系表述成因果关系
- 只检索支持预设结论的关键词（确认偏误）

## 配套资源

- [references/citation-verification.md](references/citation-verification.md) — 引用两层保证（真实≠有效）、六步生命周期、代码强制规则表、失败处置表
- [references/claim-verification.md](references/claim-verification.md) — 第二关论断核验：三步流程、判定档位、取证通道、论断台账、检查清单
- [references/tool-routing.md](references/tool-routing.md) — 工具通道能力/依赖状态/升级路径/反爬处置
- [references/report-template.md](references/report-template.md) — 报告结构、引用表列格式、检索日志、已知局限节模板
- [assets/search-log-template.csv](assets/search-log-template.csv) — 检索日志 CSV 模板
- [assets/citation-ledger-template.csv](assets/citation-ledger-template.csv) — 引用台账 CSV 模板（配 `citation_audit.py --ledger`）
- [assets/claim-ledger-template.csv](assets/claim-ledger-template.csv) — 论断台账 CSV 模板（第二关用）
- `scripts/citation_audit.py` — 报告级引用审计（markdown/HTML、结构+编号+悬空引用+PMID/DOI 权威核验+可达性+标题核对），退出码 0/1/2/3
- `scripts/check_citations.py` — 快速 URL 清单可达性与标题核对
- `scripts/citation_core.py` — 共享库（抓取、标题匹配、表格/HTML 解析、引用编号抽取、E-utilities/Crossref），被上述两个脚本引用
