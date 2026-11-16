#!/usr/bin/env python3
"""citation_core.py — 引用核查共享库（research-integrity skill）。

只做"能用代码确定性判定"的事：URL 可达性、页面标题核对、引用表结构合规、
编号连续性、正文悬空引用、孤引检测、字段完整性。判断性问题（结论是否被正文
支持、证据是否冲突）不在此列，由 SKILL.md 的流程与人审负责。
"""

from __future__ import annotations

import csv
import datetime
import re
import urllib.error
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# 反爬/拦截特征（标题或正文片段，小写比较）
BLOCK_MARKERS = (
    "captcha",
    "just a moment",
    "are you a robot",
    "not a bot",
    "checking your browser",
    "verify you are human",
    "access denied",
    "cloudflare",
    "请完成验证",
    "安全验证",
    "人机验证",
    "访问受限",
)

TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# PubMed 等站点对裸客户端返回的过渡页（HTTP 203 + 站点名标题），不是目标页面
INTERSTITIAL_HOSTS = ("pubmed.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov")

# 已知过渡页标题（DOI 重定向页、CDN 占位页等）
INTERSTITIAL_TITLES = ("redirecting", "moved permanently", "document moved", "just a moment...")


def _looks_like_interstitial(url: str, title: str) -> bool:
    """标题只剩站点名/重定向占位时判定为过渡页，不是目标页面。"""
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    norm = normalize_text(title)
    if norm in INTERSTITIAL_TITLES:
        return True
    return norm == normalize_text(host) or (
        title.strip() == "" and host in INTERSTITIAL_HOSTS
    )

# 允许的来源级别 / 验证状态（与 references/report-template.md 一致）
LEVELS = ("一级", "二级", "三级")
STATUSES = ("已读全文", "待验证")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_date(s: str) -> bool:
    """严格校验 YYYY-MM-DD 且是真实日历日期（拒绝 2026-13-99 之类）。"""
    s = (s or "").strip()
    if not DATE_RE.match(s):
        return False
    try:
        datetime.date.fromisoformat(s)
    except ValueError:
        return False
    return True

COLUMN_ALIASES = {
    "编号": "no", "序号": "no", "no": "no", "id": "no",
    "标题": "title", "title": "title", "文献": "title",
    "url": "url", "链接": "url", "网址": "url",
    "访问日期": "accessed", "日期": "accessed", "accessed": "accessed",
    "级别": "level", "来源级别": "level", "level": "level",
    "验证状态": "status", "状态": "status", "status": "status",
    "pmid": "pmid", "PMID": "pmid",
    "作者": "authors", "authors": "authors",
    "年份": "year", "year": "year",
    "期刊": "journal", "来源": "journal", "journal": "journal",
}

STATUS_TEXT = {
    "ok": "OK",
    "mismatch": "MISMATCH",
    "blocked": "BLOCKED",
    "unreachable": "UNREACHABLE",
}


# ---------------------------------------------------------------- 网络层

def decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch(url: str, timeout: float) -> dict:
    """GET 一个 URL，返回 {url,status_code,title,final_url,result,detail}。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(400_000)
            status = getattr(resp, "status", None) or resp.getcode()
            final_url = resp.geturl()
    except urllib.error.HTTPError as exc:
        return {
            "url": url, "status_code": exc.code, "title": "", "final_url": url,
            "result": "blocked" if exc.code in (401, 403, 429, 503) else "unreachable",
            "detail": f"HTTP {exc.code}",
        }
    except Exception as exc:  # 超时、DNS、连接拒绝等
        return {
            "url": url, "status_code": None, "title": "", "final_url": url,
            "result": "unreachable", "detail": f"{type(exc).__name__}: {exc}",
        }

    text = decode_bytes(body)
    match = TITLE_RE.search(body)
    title = re.sub(r"\s+", " ", decode_bytes(match.group(1)).strip()) if match else ""
    lowered = (title + " " + text[:5000]).lower()
    if any(marker in lowered for marker in BLOCK_MARKERS):
        return {"url": url, "status_code": status, "title": title, "final_url": final_url,
                "result": "blocked", "detail": "命中反爬/验证特征"}
    if _looks_like_interstitial(final_url or url, title):
        return {"url": url, "status_code": status, "title": title, "final_url": final_url,
                "result": "blocked", "detail": "疑似反爬过渡页（标题仅为站点名）"}
    return {"url": url, "status_code": status, "title": title, "final_url": final_url,
            "result": "ok", "detail": ""}


# ---------------------------------------------------------------- 权威元数据 API

def extract_pmid(url: str) -> str | None:
    """从 URL 中提取 PubMed PMID。"""
    m = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", url or "")
    return m.group(1) if m else None


def extract_doi(url: str) -> str | None:
    """从 URL 中提取 DOI（doi.org/10.xxxx/... 或出版社页路径中的 10.xxxx/...）。"""
    m = re.search(r"doi\.org/(10\.\d{4,9}/\S+)", url or "")
    if m:
        return m.group(1).rstrip(".)],;")
    m = re.search(r"/(10\.\d{4,9}/[^/?#]+)", url or "")
    return m.group(1).rstrip(".)],;") if m else None


def crossref_works(dois: list[str], timeout: float = 30.0) -> dict[str, dict]:
    """Crossref：DOI -> 标题/期刊/年份（结构化、无反爬）。"""
    import json
    import urllib.parse

    out: dict[str, dict] = {}
    for doi in dois:
        url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
        req = urllib.request.Request(url, headers={"User-Agent": "research-integrity/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                m = json.loads(resp.read().decode("utf-8", "replace"))["message"]
        except Exception:
            out[doi] = {"exists": False}
            continue
        out[doi] = {
            "exists": True,
            "title": (m.get("title") or [""])[0],
            "journal": (m.get("container-title") or [""])[0],
            "year": (m.get("issued", {}).get("date-parts") or [[None]])[0][0],
            "volume": m.get("volume", ""), "issue": m.get("issue", ""), "page": m.get("page", ""),
            "type": m.get("type", ""),
        }
    return out


def extract_pmc(url: str) -> str | None:
    """从 URL 中提取 PMC ID。"""
    m = re.search(r"pmc\.ncbi\.nlm\.nih\.gov/articles/(PMC\d+)", url or "", re.IGNORECASE)
    return m.group(1).upper() if m else None


def pmc_to_pmid(pmc_ids: list[str], timeout: float = 30.0) -> dict[str, str]:
    """NCBI ID Converter：PMCxxxx -> PMID。"""
    import json

    if not pmc_ids:
        return {}
    url = ("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids="
           + ",".join(pmc_ids) + "&format=json&tool=research-integrity")
    req = urllib.request.Request(url, headers={"User-Agent": "research-integrity/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    out: dict[str, str] = {}
    for rec in data.get("records", []):
        if rec.get("pmcid") and rec.get("pmid"):
            out[rec["pmcid"].upper()] = str(rec["pmid"])
    return out


def doi_to_pmid(dois: list[str], timeout: float = 30.0) -> dict[str, str]:
    """用 esearch 把 DOI 反查为 PMID（HTML/CSV 台账没给 PMID 时用）。"""
    import json
    import urllib.parse

    out: dict[str, str] = {}
    for doi in dois:
        q = urllib.parse.quote(doi + "[doi]")
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmode=json&term={q}"
        req = urllib.request.Request(url, headers={"User-Agent": "research-integrity/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ids = json.loads(resp.read().decode("utf-8", "replace"))["esearchresult"].get("idlist", [])
        except Exception:
            continue
        if ids:
            out[doi] = ids[0]
    return out


def pubmed_esummary(pmids: list[str], timeout: float = 30.0) -> dict[str, dict]:
    """NCBI E-utilities esummary：PMID -> 精确元数据（标题/期刊/日期/卷期页/作者/DOI）。

    这是比抓页面更确定的核验路径：结构化、无反爬、可判定 PMID 是否存在。
    """
    import json

    if not pmids:
        return {}
    url = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
           f"?db=pubmed&retmode=json&id={','.join(pmids)}")
    req = urllib.request.Request(url, headers={"User-Agent": "research-integrity/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    result = data.get("result", {})
    out: dict[str, dict] = {}
    for pid in pmids:
        rec = result.get(pid) or {}
        if not rec or "error" in rec:
            out[pid] = {"exists": False}
            continue
        dois = [a["value"] for a in rec.get("articleids", []) if a.get("idtype") == "doi"]
        out[pid] = {
            "exists": True,
            "title": rec.get("title", ""),
            "journal": rec.get("source", ""),
            "fulljournal": rec.get("fulljournalname", ""),
            "pubdate": rec.get("pubdate", ""),
            "volume": rec.get("volume", ""),
            "issue": rec.get("issue", ""),
            "pages": rec.get("pages", ""),
            "authors": ", ".join(a["name"] for a in rec.get("authors", [])[:3]),
            "doi": dois[0] if dois else "",
        }
    return out


def normalize_text(s: str) -> str:
    """标题归一化：小写、去空白与常见标点，便于容忍站点后缀与截断。"""
    s = (s or "").lower()
    s = re.sub(r"[|｜\-–—_/\\:,;.()\[\]{}<>\"'`]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def title_matches(expected: str, actual: str) -> tuple[bool, float]:
    """期望标题 vs 页面标题。

    通过条件（任一）：归一化后双向包含；期望标题的词被页面标题覆盖率 >= 0.8
    （容忍表中标题缩写/站点后缀）；词集合 Jaccard >= 0.6。
    """
    exp, act = normalize_text(expected), normalize_text(actual)
    if not exp or not act:
        return (False, 0.0)
    if exp in act or act in exp:
        return (True, 1.0)
    exp_words, act_words = set(exp.split()), set(act.split())
    if not exp_words or not act_words:
        return (False, 0.0)
    inter = len(exp_words & act_words)
    recall = inter / len(exp_words)
    jaccard = inter / len(exp_words | act_words)
    ratio = max(recall, jaccard)
    return (recall >= 0.8 or jaccard >= 0.6, round(ratio, 3))


def check_url(url: str, expected_title: str | None, timeout: float) -> dict:
    info = fetch(url, timeout)
    info["expected"] = expected_title or ""
    info["title_match"] = None
    if info["result"] == "ok" and expected_title:
        ok, ratio = title_matches(expected_title, info["title"])
        info["title_match"] = ok
        if not ok:
            info["result"] = "mismatch"
            info["detail"] = f"标题不符(重合度 {ratio})，页面标题: {info['title'][:80]}"
    return info


# ---------------------------------------------------------------- 解析层

def parse_markdown_table(lines: list[str]) -> list[dict]:
    """把管道表解析为 dict 列表；列名经 COLUMN_ALIASES 归一。无表头返回 []。"""
    rows = [ln.strip() for ln in lines if ln.strip().startswith("|")]
    if len(rows) < 2:
        return []
    header = [c.strip() for c in rows[0].strip("|").split("|")]
    keys = [COLUMN_ALIASES.get(h.strip().lower(), None) for h in header]
    if not any(keys):
        return []
    out: list[dict] = []
    for line in rows[1:]:
        if re.fullmatch(r"\|[\s:\-\|]+\|", line):  # 分隔行
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        row = {}
        for idx, key in enumerate(keys):
            if key and idx < len(cells):
                row[key] = cells[idx]
        if any(row.get(k) for k in ("url", "title", "no")):
            out.append(row)
    return out


def find_reference_section(md_text: str) -> tuple[bool, str]:
    """定位参考文献小节，返回 (是否找到, 该小节文本)。"""
    lines = md_text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^#{1,6}\s*(参考文献|References)\s*$", ln.strip(), re.IGNORECASE):
            start = i
            break
    if start is None:
        return (False, "")
    body = []
    for ln in lines[start + 1:]:
        if re.match(r"^#{1,6}\s+\S", ln.strip()):  # 下一个标题，小节结束
            break
        body.append(ln)
    return (True, "\n".join(body))


def load_ledger(md_text: str) -> tuple[bool, list[dict], list[str]]:
    """从报告 markdown 中取参考文献表。返回 (找到?, 行, 该小节所有行)。"""
    found, section = find_reference_section(md_text)
    if not found:
        return (False, [], [])
    lines = section.splitlines()
    return (True, parse_markdown_table(lines), lines)


def load_csv_ledger(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = []
        for raw in reader:
            row = {}
            for k, v in raw.items():
                if k is None:
                    continue
                key = COLUMN_ALIASES.get(str(k).strip().lower())
                if key:
                    row[key] = (v or "").strip()
            if row.get("url") or row.get("title"):
                rows.append(row)
        return rows


INTEXT_RE = re.compile(r"\[(\d+(?:\s*[,\-–]\s*\d+)*)\]")


def extract_intext_numbers(text: str) -> set[int]:
    """抽取正文中的 [n] / [n,m] / [n-m] 引用编号。"""
    numbers: set[int] = set()
    for group in INTEXT_RE.findall(text):
        for part in re.split(r"\s*,\s*", group):
            part = part.strip()
            if not part:
                continue
            if re.fullmatch(r"\d+\s*[\-–]\s*\d+", part):
                a, b = re.split(r"[\-–]", part)
                lo, hi = int(a), int(b)
                if lo <= hi and hi - lo < 200:  # 防御误匹配
                    numbers.update(range(lo, hi + 1))
            elif part.isdigit():
                numbers.add(int(part))
    return numbers


def body_without_references(md_text: str) -> str:
    """去掉参考文献小节后的正文（用于悬空引用检测，避免把表内编号当正文引用）。"""
    lines = md_text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^#{1,6}\s*(参考文献|References)\s*$", ln.strip(), re.IGNORECASE):
            start = i
            break
    if start is None:
        return md_text
    return "\n".join(lines[:start])


# ---------------------------------------------------------------- HTML 报告支持

def looks_like_html(text: str) -> bool:
    head = (text or "")[:2000].lstrip().lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<body" in head


def _html_ref_section(text: str) -> str:
    """截取参考文献小节（从含"参考文献/References"的标题到下一个标题）。"""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if re.search(r"<h[1-6][^>]*>.*?(参考文献|References)", ln, re.IGNORECASE) or \
           re.match(r"^#{1,6}\s*(参考文献|References)\s*$", ln.strip(), re.IGNORECASE):
            start = i
            break
    if start is None:
        return ""
    out = []
    for ln in lines[start + 1:]:
        if re.search(r"<h[1-6][^>]*>", ln) or re.match(r"^#{1,6}\s+\S", ln.strip()):
            break
        out.append(ln)
    return "\n".join(out)


def _html_li_to_row(idx: int, item: str) -> dict:
    urls = re.findall(r'href="([^"]+)"', item)
    jm = re.search(r"<em>(.*?)</em>", item, re.S)
    journal = html_unescape(re.sub(r"<[^>]+>", "", jm.group(1))).strip() if jm else ""
    before = item.split("<em>")[0]
    before = re.sub(r"<span[^>]*>.*?</span>", " ", before, flags=re.S)
    before = re.sub(r"<a[^>]*>.*?</a>", " ", before, flags=re.S)
    before = html_unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", before))).strip()
    parts = [p.strip() for p in before.split(". ") if p.strip()]
    authors = parts[0] if parts else ""
    title = ". ".join(parts[1:]) if len(parts) > 1 else ""
    after = item.split("</em>", 1)[1] if "</em>" in item else ""
    ym = re.search(r"(19|20)\d{2}", html_unescape(re.sub(r"<[^>]+>", " ", after)))
    return {"no": str(idx), "title": title, "authors": authors,
            "year": ym.group(0) if ym else "", "journal": journal,
            "url": urls[0] if urls else "", "accessed": today_str(),
            "level": guess_level(urls[0] if urls else "", title),
            "status": "待验证"}


def guess_level(url: str, title: str = "") -> str:
    """按来源类型推测证据级别（启发式，需人工确认）。

    一级：期刊/PubMed/PMC/官方；二级：预印本服务器、会议摘要、厂商与媒体页；三级：其余。
    """
    u = (url or "").lower()
    t = (title or "").lower()
    if any(k in u for k in ("medrxiv", "biorxiv", "researchsquare", "ssrn", "arxiv")):
        return "二级"
    if "会议摘要" in t or "abstract" in t and "doi.org/10.1016/j.ajt" in u:
        return "二级"
    if any(k in u for k in ("pubmed", "pmc.ncbi", "doi.org/10.", "ncbi.nlm.nih.gov")):
        return "一级"
    return "一级"


def html_unescape(s: str) -> str:
    import html as _html
    return _html.unescape(s)


def load_html_report(text: str) -> tuple[list[dict], str]:
    """解析 HTML 报告，返回 (参考文献行, 去掉文献节后的正文纯文本)。"""
    section = _html_ref_section(text)
    rows: list[dict] = []
    if section:
        for i, item in enumerate(re.findall(r"<li>(.*?)</li>", section, re.S), 1):
            if re.search(r'href="([^"]+)"', item):
                rows.append(_html_li_to_row(i, item))
    body = text
    idx = None
    for i, ln in enumerate(text.splitlines()):
        if re.search(r"<h[1-6][^>]*>.*?(参考文献|References)", ln, re.IGNORECASE):
            idx = i
            break
    if idx is not None:
        body = "\n".join(text.splitlines()[:idx])
    body = html_unescape(re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", " ", body)))
    return rows, body


def today_str() -> str:
    return datetime.date.today().isoformat()
