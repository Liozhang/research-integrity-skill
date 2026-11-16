# 工具路由与升级路径

> 实测环境：ZCode 桌面版（Windows），2026-11-03 复核。端口/token 状态会变，用前先测。

## 通道总表

| 通道 | 能力 | 依赖 | 状态（2026-11-03） | 证据级别 |
|---|---|---|---|---|
| `web-search-prime`（MCP） | 网页搜索，返回真实 URL/标题/摘要 | config.json 已注册 | 可用（实测返回 9 条真实结果） | 检索入口 |
| `web-reader`（MCP） | 抓取页面正文 | 同上 | 可用；Elsevier/ScienceDirect 返 CAPTCHA | 读到正文=可引用 |
| `zread`（MCP） | GitHub 仓库/issue/文档原文 | 同上 | 可用 | 一级（代码/官方文档） |
| `WebFetch`（内置） | 抓 URL 转 markdown 并回答 | 无 | 可用；localhost/无点号主机名会失败 | 同上 |
| `aminer-data-search`（skill） | AMiner 28 API：论文/学者/机构/期刊/专利、引用链 | open.aminer.cn token | 按环境配置 | 一级（学术库） |
| 本地网关依赖类 skill（搜索/正文抓取/结构化深研/搜图/浏览器采集，名称因环境而异） | 同上各类能力 | 本地网关签发 token（端口与端点见本地 skill 说明） | 端口无监听 → 不可用 | 同 MCP 层 |
| 真实浏览器通道（`browser-use:control-browser`、`playwright-mcp` 等） | 读渲染后页面、本地 HTTP、截图、表单采集 | 各宿主的浏览器插件/MCP 配置 | 按环境自检 | 截图=三级，正文抽取=二级 |
| 文档检索类 MCP（如 Microsoft Learn 文档） | 官方文档检索 | 各宿主 MCP 配置 | 按环境自检 | 一级（官方文档） |

## 权威元数据 API（引用核验的确定性通道）

比页面抓取更可靠：结构化返回、无反爬、能判定"文献是否存在"。`citation_audit.py --pmid-api` 已内置前三项。

| API | 用途 | 备注 |
|---|---|---|
| `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&retmode=json&id=<pmids>` | PMID → 精确标题/期刊/日期/卷期页/作者/DOI | PMID 不存在时返回 error，可直接判定编造 |
| `https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids=PMCxxx&format=json` | PMC ID → PMID | 台账里放 PMC 链接也能走权威核验 |
| `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=...` | 按标题/作者/DOI 反查 PMID | 用于给"查不到的专有名词"做存在性检索 |
| `https://api.crossref.org/works/<DOI>` | DOI → 标题/期刊/年份 | 出版社页 403 时的替代核验 |
| `https://api.crossref.org/works?query.bibliographic=<题>` | 按题检索 DOI | 只有标题没有 DOI 时用 |

裸 HTTP 抓 PubMed 会被限流（HTTP 203 + 标题只剩站点名），脚本已识别为 BLOCKED；**核验优先级：权威 API > 页面抓取 > 浏览器通道**。

## 选路决策树

```
需要检索 → web-search-prime（默认）
         └─ 学术论文优先：aminer-data-search（有 token 时）或直接搜 PubMed/期刊官网
需要读正文 → web-reader（默认）
         └─ 被反爬/JS 渲染阻断 → 升级链：
            ① 换开放获取镜像 / PubMed / Europe PMC 条目页
            ② publisher 官方 PDF 或 preprint 服务器
            ③ browser-use:control-browser 或 playwright-mcp 真实浏览器
            ④ 仍失败 → 记"待验证"，禁止凭摘要补全
需要代码/官方文档 → zread（GitHub）、microsoftdocs/mcp（MS 文档）
需要图片素材 → 搜图类通道（本地网关依赖的 skill 在线时）
```

## 反爬与阻断处置

| 现象 | 判定 | 处置 |
|---|---|---|
| 返回 CAPTCHA / "请完成验证" | 正文未取到 | 换通道（决策树③）；不得引用该次抓取内容 |
| 只返回导航/页脚无正文 | JS 渲染 | 用浏览器类通道 |
| 403/登录墙 | 无权限 | 找开放获取版本；否则标"待验证" |
| 搜索有结果但打不开 | 链接失效 | 记录原始 URL + 检索快照，标"待验证" |

## 使用前自检命令

```bash
# 本地网关依赖的 skill：按你环境说明探测端口（示例）
curl -s -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1:<端口>/get_token   # 000 = 不可用
mcporter list   # 或你宿主的 MCP 列表命令，确认浏览器/文档类 MCP 是否 healthy
```

## 证据级别定义

- **一级**：原始论文、官方/监管文件、代码仓库原文、临床试验注册信息 —— 可作为结论主证据。
- **二级**：综述、权威媒体、厂商官方页面（仅能证明"厂商声称"，不能证明"事实如此"）。
- **三级**：搜索摘要、二手转述、截图视觉描述、AI 生成摘要 —— 只能定位线索，不得作为引用。
