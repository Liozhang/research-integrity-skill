# research-integrity

网络/学术调研的质量与引用真实性协议（Agent Skill）——把"防止 AI 编造引用"
从自觉变成流程与代码强制。适用于 ZCode、Claude Code 等支持 Agent Skills
约定（`SKILL.md` + 目录结构）的运行环境。

背景：Agent 环境没有自动引文校验引擎，调研质量完全由流程保证。本技能把
调研的"全面、真实、有效"三性落成可执行的流水线、门禁与自检脚本，适用于
任何需要联网取证并产出带引用报告的任务，也适用于复核既有报告的引用可信度。

## 三条铁律（违反任何一条即任务失败）

1. **没读到正文的来源，不进参考文献表。** 搜索摘要、标题、转述都不算；
   抓取被反爬/CAPTCHA/付费墙阻断时，降级为"搜索命中、正文待验证"，并
   尝试升级抓取通道。
2. **查不到的专有名词直接删，不猜、不补全。** 项目名、机构名、产品型号、
   卷期页码、DOI/PMID，检索不到就删除或标注待验证；模型记忆不等于检索结果。
3. **"未找到"必须留下检索痕迹。** 否定结论（"某领域研究为零"）同样要给
   证据：用了哪些检索词、哪些库、返回什么。无痕迹的否定视为编造。

## 九阶段流水线

```
① 定义问题 → ② 建查询矩阵 → ③ 并行检索 → ④ 抓取正文 → ⑤ 交叉验证
→ ⑥ 证据分级编号 → ⑦ 撰写 → ⑧ 自检 → ⑨ 交付
└─ 每阶段有过门条件，不过就退回上一阶段，不带着疑点往下走 ─┘
```

## 引用纪律

- 编号唯一且稳定，正文引用与文末文献表严格一一对应
- 每个来源记录五元组：编号 | 标题 | URL | 访问日期 | 来源级别 | 验证状态
- 三级标注：`[文献原文]` / `[检索命中未读全文]` / `[推断]`
- 冲突不调和：两个来源矛盾时并列呈现，不选一个当真理
- 元数据核验走权威 API（PubMed E-utilities / Crossref），不走页面抓取

## 审计脚本

```bash
# 报告级审计（markdown / HTML 均可，自动识别格式）
python scripts/citation_audit.py report.md  --pmid-api --doi-api
python scripts/citation_audit.py report.html --pmid-api --doi-api
python scripts/citation_audit.py report.md --ledger citations.csv --no-network --json

# 快速 URL 清单核对
python scripts/check_citations.py citations.txt
```

退出码：`0` 通过 | `1` 仅警告（需人工处置）| `2` FAIL（不得交付）| `3` 输入错误。

代码强制项：文献节存在、编号连续、URL 合法、访问日期有效、来源级别与验证
状态合法、PMID/DOI 在权威库真实存在、标题与权威元数据一致（防张冠李戴）、
URL 可达性（403/反爬归 BLOCKED 不判 FAIL）、正文无悬空引用。
代码判不了的（正文是否支持该句、证据冲突）留人工第二关，见
`references/claim-verification.md`。

## 安装

```bash
# 克隆目标目录名须保持 research-integrity，与技能 name 一致
git clone https://github.com/Liozhang/research-integrity-skill.git ~/.agents/skills/research-integrity
```

## 仓库结构

```
research-integrity/
├── SKILL.md                        # 主文件：铁律 + 三性框架 + 九阶段 + 引用纪律
├── README.md / LICENSE（MIT）
├── references/
│   ├── tool-routing.md             # 通道类别、权威 API 表、升级链、反爬处置
│   ├── citation-verification.md    # 引用两层保证、六步生命周期、失败处置
│   ├── claim-verification.md       # 第二关论断核验：流程、判定档位、台账
│   └── report-template.md          # 报告结构、引用表列格式、检索日志模板
├── scripts/
│   ├── citation_audit.py           # 报告级引用审计（含 PMID/DOI 权威核验）
│   ├── check_citations.py          # 快速 URL 清单核对
│   └── citation_core.py            # 共享库（抓取/标题匹配/解析/权威 API）
└── assets/                         # 检索日志 / 引用台账 / 论断台账 CSV 模板
```

## 状态说明

铁律、流水线与两个审计脚本经真实调研报告产线实测（曾核出并删除文献中不
存在的项目名、拦下摘要冒充全文的引用）；`references/tool-routing.md` 中的
通道能力因环境而异，表中状态为示例快照，用前先跑自检命令。

## 许可证

[MIT](LICENSE)
