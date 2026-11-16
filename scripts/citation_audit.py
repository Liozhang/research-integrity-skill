#!/usr/bin/env python3
"""citation_audit.py — 报告级引用审计（research-integrity skill 第⑧步）。

把引用纪律里"能用代码确定性判定"的规则全部执行一遍：

  FAIL（退出码 2，任一不过即不得交付）
    - 无「参考文献」小节或表为空
    - 编号重复 / 不连续 / 非数字 / 不是从 1 开始
    - URL 缺失或不是 http(s)
    - 访问日期缺失、格式非 YYYY-MM-DD、或晚于今天
    - 来源级别不在一级/二级/三级
    - 验证状态不是 已读全文/待验证
    - URL 不可达（unreachable）
    - 页面标题与表中标题不符（mismatch，防张冠李戴）
    - 正文悬空引用：正文引了表中不存在的编号

  WARN（退出码 1，需人工处置后才可交付）
    - BLOCKED：403/CAPTCHA，仅说明本通道被挡，须升级浏览器通道重判
    - 待验证条目：不得作为关键结论的主证据
    - 孤引：表中编号从未在正文被引用
    - 同一 URL 在表中重复出现

用法：
    python citation_audit.py report.md
    python citation_audit.py report.md --ledger citations.csv   # 表格在单独 CSV 时
    python citation_audit.py report.md --no-network             # 只做结构审计
    python citation_audit.py report.md --timeout 20 --json

退出码：0 = PASS；1 = 仅 WARN；2 = 存在 FAIL；3 = 输入/解析错误。
仅依赖 Python 标准库。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from citation_core import (  # noqa: E402
    LEVELS,
    STATUSES,
    STATUS_TEXT,
    body_without_references,
    check_url,
    crossref_works,
    extract_doi,
    extract_intext_numbers,
    extract_pmc,
    extract_pmid,
    doi_to_pmid,
    load_csv_ledger,
    load_html_report,
    load_ledger,
    looks_like_html,
    pmc_to_pmid,
    pubmed_esummary,
    title_matches,
    today_str,
    valid_date,
)


def structural_checks(rows: list[dict]) -> tuple[list[str], list[str]]:
    """不依赖网络的表格结构检查。返回 (fails, warns)。"""
    fails: list[str] = []
    warns: list[str] = []

    numbers: list[int] = []
    seen_urls: dict[str, int] = {}
    for idx, row in enumerate(rows, 1):
        no_raw = (row.get("no") or "").strip()
        if not no_raw.isdigit():
            fails.append(f"第 {idx} 行编号缺失或非数字: {no_raw!r}")
            numbers.append(idx)
        else:
            numbers.append(int(no_raw))

        url = (row.get("url") or "").strip()
        if not url:
            fails.append(f"编号 {no_raw or idx}：URL 缺失")
        elif not url.lower().startswith(("http://", "https://")):
            fails.append(f"编号 {no_raw or idx}：URL 不是 http(s) 链接: {url}")
        if url:
            seen_urls[url] = seen_urls.get(url, 0) + 1

        accessed = (row.get("accessed") or "").strip()
        if not accessed:
            fails.append(f"编号 {no_raw or idx}：访问日期缺失")
        elif not valid_date(accessed):
            fails.append(f"编号 {no_raw or idx}：访问日期不是有效日期(YYYY-MM-DD): {accessed}")
        elif accessed > today_str():
            fails.append(f"编号 {no_raw or idx}：访问日期晚于今天({today_str()}): {accessed}")

        level = (row.get("level") or "").strip()
        if level and level not in LEVELS:
            fails.append(f"编号 {no_raw or idx}：来源级别必须是 {'/'.join(LEVELS)}: {level}")
        elif not level:
            warns.append(f"编号 {no_raw or idx}：来源级别为空，建议补「一级/二级/三级」")

        status = (row.get("status") or "").strip()
        if not status:
            fails.append(f"编号 {no_raw or idx}：验证状态缺失")
        elif status not in STATUSES:
            fails.append(f"编号 {no_raw or idx}：验证状态必须是 {'/'.join(STATUSES)}: {status}")
        elif status == "待验证":
            warns.append(f"编号 {no_raw or idx}：待验证条目，不得作为关键结论的主证据")

        if not (row.get("title") or "").strip():
            warns.append(f"编号 {no_raw or idx}：标题为空，无法做标题核对")

    if numbers != list(range(1, len(numbers) + 1)):
        dup = sorted({n for n in numbers if numbers.count(n) > 1})
        if dup:
            fails.append(f"编号重复: {dup}")
        else:
            fails.append(f"编号必须从 1 连续编到 {len(numbers)}，实际为: {numbers}")

    for url, count in seen_urls.items():
        if count > 1:
            warns.append(f"同一 URL 在表中出现 {count} 次（同一来源只算一个独立来源）: {url}")

    return fails, warns


def network_checks(rows: list[dict], timeout: float, concurrency: int,
                   skip_indices: set[int] | None = None) -> tuple[list[str], list[str], list[dict]]:
    fails: list[str] = []
    warns: list[str] = []
    details: list[dict] = []
    skip_indices = skip_indices or set()

    targets = [
        (i, r) for i, r in enumerate(rows)
        if i not in skip_indices
        and (r.get("url") or "").lower().startswith(("http://", "https://"))
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {
            pool.submit(check_url, r["url"].strip(), (r.get("title") or "").strip() or None, timeout): (i, r)
            for i, r in targets
        }
        for fut in concurrent.futures.as_completed(futures):
            i, row = futures[fut]
            info = fut.result()
            details.append(info)
            no = (row.get("no") or "?").strip()
            if info["result"] == "unreachable":
                fails.append(f"编号 {no}：URL 不可达（{info['detail']}）{info['url']}")
            elif info["result"] == "mismatch":
                fails.append(f"编号 {no}：{info['detail']} {info['url']}")
            elif info["result"] == "blocked":
                warns.append(f"编号 {no}：本通道被挡（{info['detail']}），升级浏览器通道后重判 {info['url']}")
    details.sort(key=lambda d: d["url"])
    return fails, warns, details


def collapse_warns(warns: list[str]) -> list[str]:
    """把同质 WARN 折叠成一行（编号列表+计数），避免 20 条"待验证"刷屏。"""
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for w in warns:
        key = re.sub(r"编号 \d+", "编号 N", w)
        key = key.split("：", 1)[0] + "：" + (key.split("：", 1)[1][:14] if "：" in key else "")
        if key not in groups:
            order.append(key)
        groups.setdefault(key, []).append(w)
    out: list[str] = []
    for key in order:
        items = groups[key]
        if len(items) <= 2:
            out.extend(items)
            continue
        nos = []
        for w in items:
            m = re.search(r"编号 (\d+)", w)
            if m:
                nos.append(m.group(1))
        out.append(f"{re.sub(r'编号 \\d+', '编号 N', items[0])}  ……共 {len(items)} 条（编号 {','.join(nos)}）")
    return out


def doi_api_checks(rows: list[dict]) -> tuple[list[str], list[str], list[dict], set[int]]:
    """用 Crossref 权威元数据校验含 DOI 的条目（会议摘要/出版社页无 PMID 时用）。"""
    fails: list[str] = []
    warns: list[str] = []
    details: list[dict] = []
    verified_rows: set[int] = set()
    pairs: list[tuple[int, dict, str]] = []
    for idx, row in enumerate(rows):
        if (row.get("pmid") or "").strip() or extract_pmid(row.get("url", "")):
            continue  # PMID 条目交给 --pmid-api
        doi = (row.get("doi") or "").strip() or extract_doi(row.get("url", ""))
        if doi:
            pairs.append((idx, row, doi))
    if not pairs:
        return fails, warns, details, verified_rows
    try:
        meta = crossref_works([d for _, _, d in pairs])
    except Exception as exc:
        warns.append(f"Crossref API 调用失败（{type(exc).__name__}: {exc}），DOI 条目退回页面抓取核验")
        return fails, warns, details, verified_rows
    for idx, row, doi in pairs:
        no = (row.get("no") or "?").strip()
        m = meta.get(doi, {})
        if not m.get("exists"):
            fails.append(f"编号 {no}：DOI {doi} 在 Crossref 不存在 —— 该引用可能为编造")
            details.append({"no": no, "doi": doi, "result": "not-exists", "detail": "DOI 不存在"})
            verified_rows.add(idx)
            continue
        expected = (row.get("title") or "").strip()
        ok, ratio = title_matches(expected, m.get("title", ""))
        entry = {"no": no, "doi": doi, "result": "ok", "detail": "", "title": m.get("title", ""),
                 "journal": m.get("journal", ""), "year": m.get("year", ""), "type": m.get("type", "")}
        if not ok:
            entry["result"] = "mismatch"
            entry["detail"] = f"标题不符(重合度 {ratio})，Crossref 标题: {m.get('title','')[:80]}"
            fails.append(f"编号 {no}：{entry['detail']}")
        year = (row.get("year") or "").strip()
        if year and m.get("year") and str(year) != str(m.get("year")):
            warns.append(f"编号 {no}：年份不符（表内 {year}，Crossref {m.get('year')}）")
        details.append(entry)
        verified_rows.add(idx)
    return fails, warns, details, verified_rows


def pubmed_api_checks(rows: list[dict]) -> tuple[list[str], list[str], list[dict], set[int]]:
    """用 NCBI E-utilities 权威元数据校验含 PMID 的条目（确定性强于抓页面）。

    返回 (fails, warns, details, 已核验行下标集合)。details 供报告展示。
    """
    fails: list[str] = []
    warns: list[str] = []
    details: list[dict] = []
    verified_rows: set[int] = set()

    pairs: list[tuple[int, dict, str]] = []
    pmc_pending: list[str] = []
    doi_pending: list[str] = []
    for idx, row in enumerate(rows):
        pmid = (row.get("pmid") or "").strip() or extract_pmid(row.get("url", ""))
        if pmid and pmid.isdigit():
            pairs.append((idx, row, pmid))
            continue
        pmc = extract_pmc(row.get("url", ""))
        if pmc:
            pmc_pending.append(pmc)
            continue
        doi = (row.get("doi") or "").strip() or extract_doi(row.get("url", ""))
        if doi:
            doi_pending.append(doi)
    # PMC -> PMID 转换后并入
    if pmc_pending:
        try:
            conv = pmc_to_pmid(sorted(set(pmc_pending)))
        except Exception as exc:
            warns.append(f"PMC->PMID 转换失败（{type(exc).__name__}: {exc}），PMC 条目退回页面抓取核验")
            conv = {}
        for idx, row in enumerate(rows):
            pmc = extract_pmc(row.get("url", ""))
            if pmc and pmc in conv:
                pairs.append((idx, row, conv[pmc]))
    # DOI -> PMID 反查（HTML 报告/无 PMID 列的台账）
    if doi_pending:
        try:
            conv2 = doi_to_pmid(sorted(set(doi_pending)))
        except Exception as exc:
            warns.append(f"DOI→PMID 反查失败（{type(exc).__name__}: {exc}），这些条目退回页面抓取核验")
            conv2 = {}
        for idx, row in enumerate(rows):
            doi = (row.get("doi") or "").strip() or extract_doi(row.get("url", ""))
            if doi and doi in conv2:
                pairs.append((idx, row, conv2[doi]))
    if not pairs:
        return fails, warns, details, verified_rows

    try:
        meta = pubmed_esummary([p for _, _, p in pairs])
    except Exception as exc:
        warns.append(f"PubMed API 调用失败（{type(exc).__name__}: {exc}），PMID 条目退回页面抓取核验")
        return fails, warns, details, verified_rows

    for idx, row, pmid in pairs:
        no = (row.get("no") or "?").strip()
        m = meta.get(pmid, {})
        if not m.get("exists"):
            fails.append(f"编号 {no}：PMID {pmid} 在 PubMed 不存在 —— 该引用可能为编造或 PMID 有误")
            details.append({"no": no, "pmid": pmid, "result": "not-exists", "detail": "PMID 不存在"})
            verified_rows.add(idx)  # 已用权威渠道判定，无需再抓页面
            continue

        expected = (row.get("title") or "").strip()
        ok, ratio = title_matches(expected, m.get("title", ""))
        year = (row.get("year") or "").strip()
        journal = (row.get("journal") or "").strip()

        entry = {"no": no, "pmid": pmid, "result": "ok", "detail": "",
                 "title": m.get("title", ""), "journal": m.get("fulljournalname", ""),
                 "pubdate": m.get("pubdate", ""), "volume": m.get("volume", ""),
                 "issue": m.get("issue", ""), "pages": m.get("pages", ""), "doi": m.get("doi", ""),
                 "notes": []}
        if not ok:
            entry["result"] = "mismatch"
            entry["detail"] = f"标题不符(重合度 {ratio})，PubMed 标题: {m.get('title','')[:80]}"
            fails.append(f"编号 {no}：{entry['detail']}")
        if year and year not in (m.get("pubdate") or ""):
            entry["notes"].append(f"年份不符：表内 {year} vs PubMed {m.get('pubdate')}")
            warns.append(f"编号 {no}：年份不符（表内 {year}，PubMed {m.get('pubdate')}）")
        if journal:
            from citation_core import normalize_text
            jn = normalize_text(journal)
            meta_j = normalize_text(f"{m.get('fulljournalname','')} {m.get('source','')}")
            if jn and jn not in meta_j and meta_j not in jn:
                entry["notes"].append(f"期刊名不一致：表内 {journal} vs {m.get('fulljournalname','')}")
                warns.append(f"编号 {no}：期刊名不一致（表内 {journal}，PubMed {m.get('fulljournalname','')}）")
        details.append(entry)
        verified_rows.add(idx)
    return fails, warns, details, verified_rows


def citation_cross_check(rows: list[dict], md_text: str) -> tuple[list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []
    table_numbers = set()
    for row in rows:
        no = (row.get("no") or "").strip()
        if no.isdigit():
            table_numbers.add(int(no))

    body = body_without_references(md_text)
    intext = extract_intext_numbers(body)
    dangling = sorted(intext - table_numbers)
    if dangling:
        fails.append(f"正文悬空引用（正文引了、表里没有）: {dangling}")
    orphan = sorted(table_numbers - intext)
    if orphan:
        warns.append(f"孤引（表里有、正文从未引用）: {orphan}")
    return fails, warns


def render(rows: list[dict], details: list[dict], fails: list[str], warns: list[str],
           api_details: list[dict] | None = None,
           doi_details: list[dict] | None = None) -> str:
    api_details = api_details or []
    doi_details = doi_details or []
    out: list[str] = []
    out.append("== 引用审计 ==")
    out.append(f"条目数: {len(rows)}")
    if api_details:
        out.append("")
        out.append("-- PubMed 权威元数据核验（E-utilities）--")
        for d in api_details:
            if d["result"] == "not-exists":
                out.append(f"[NOT-EXISTS  ] 编号 {d['no']} PMID {d['pmid']} —— PubMed 中不存在")
                continue
            flag = "OK        " if d["result"] == "ok" else "MISMATCH  "
            out.append(f"[{flag}] 编号 {d['no']} PMID {d['pmid']}")
            out.append(f"            标题: {d['title'][:78]}")
            out.append(f"            {d['journal']} {d['pubdate']} vol {d['volume']}({d['issue']}):{d['pages']}"
                       + (f" | doi {d['doi']}" if d.get("doi") else ""))
            for note in d.get("notes", []):
                out.append(f"            注意: {note}")
            if d["detail"]:
                out.append(f"            {d['detail']}")
    if doi_details:
        out.append("")
        out.append("-- Crossref 权威元数据核验 --")
        for d in doi_details:
            if d["result"] == "not-exists":
                out.append(f"[NOT-EXISTS  ] 编号 {d['no']} DOI {d['doi']} —— Crossref 中不存在")
                continue
            flag = "OK        " if d["result"] == "ok" else "MISMATCH  "
            out.append(f"[{flag}] 编号 {d['no']} DOI {d['doi']}")
            out.append(f"            标题: {d['title'][:78]}")
            out.append(f"            {d['journal']} {d.get('year')} | type {d.get('type','')}")
            if d["detail"]:
                out.append(f"            {d['detail']}")
    if details:
        out.append("")
        out.append("-- 网络核查（页面抓取）--")
        for d in details:
            title = d["title"][:70] or "-"
            line = f"[{STATUS_TEXT[d['result']]:<11}] {d['url']}  {title}"
            if d["detail"]:
                line += f"  ({d['detail']})"
            out.append(line)
    if fails:
        out.append("")
        out.append("-- FAIL（必须修复后才能交付）--")
        out.extend(f"  x {f}" for f in fails)
    if warns:
        out.append("")
        out.append("-- WARN（需人工处置，同质项已折叠）--")
        out.extend(f"  ! {w}" for w in collapse_warns(warns))
    out.append("")
    verdict = "FAIL" if fails else ("WARN" if warns else "PASS")
    out.append(f"结论: {verdict}  (FAIL {len(fails)} / WARN {len(warns)})")
    if fails:
        out.append("铁律提醒: PMID/DOI 不存在或标题不符 → 换正确文献或删除，禁止凭记忆补全字段。")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="报告级引用审计")
    parser.add_argument("report", help="报告 markdown 文件")
    parser.add_argument("--ledger", help="引用表 CSV（表格不在报告内时使用；默认跳过正文交叉核对）")
    parser.add_argument("--cross-check", action="store_true",
                        help="配合 --ledger 使用：也做正文引用编号与 CSV 的交叉核对")
    parser.add_argument("--no-network", action="store_true",
                        help="跳过页面抓取核验（--pmid-api 的 API 核验仍会执行）")
    parser.add_argument("--pmid-api", action="store_true",
                        help="用 NCBI E-utilities 权威元数据校验含 PMID 的条目（确定性高于抓页面）")
    parser.add_argument("--doi-api", action="store_true",
                        help="用 Crossref 权威元数据校验含 DOI 的条目（会议摘要/出版社页无 PMID 时用）")
    parser.add_argument("--timeout", type=float, default=15.0, help="单条超时秒数（默认 15）")
    parser.add_argument("--concurrency", type=int, default=5, help="并发数（默认 5）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args()

    try:
        md_text = Path(args.report).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[error] 无法读取报告: {exc}", file=sys.stderr)
        return 3

    html_mode = looks_like_html(md_text) or args.report.lower().endswith((".html", ".htm"))

    if args.ledger:
        try:
            rows = load_csv_ledger(args.ledger)
        except OSError as exc:
            print(f"[error] 无法读取引用表: {exc}", file=sys.stderr)
            return 3
        if not rows:
            print("[error] 引用表 CSV 中没有有效行", file=sys.stderr)
            return 3
    elif html_mode:
        rows, html_body = load_html_report(md_text)
        if not rows:
            print("[error] HTML 报告中找不到含链接的参考文献列表（<ol><li>…</li></ol>）", file=sys.stderr)
            return 3
        md_text = html_body  # 供 --cross-check 抽取正文引用编号
    else:
        found, rows, _ = load_ledger(md_text)
        if not found:
            print("[error] 报告中找不到「## 参考文献」小节（HTML 报告请直接传 .html）", file=sys.stderr)
            return 3
        if not rows:
            print("[error] 「参考文献」小节中没有解析到表格（需要带表头的 markdown 管道表）", file=sys.stderr)
            return 3

    fails, warns = structural_checks(rows)
    if (not args.ledger) or args.cross_check:
        cfails, cwarns = citation_cross_check(rows, md_text)
        fails.extend(cfails)
        warns.extend(cwarns)

    details: list[dict] = []
    api_details: list[dict] = []
    doi_details: list[dict] = []
    verified_rows: set[int] = set()
    if args.pmid_api:
        pfails, pwarns, api_details, verified_rows = pubmed_api_checks(rows)
        fails.extend(pfails)
        warns.extend(pwarns)
    if args.doi_api:
        dfails, dwarns, doi_details, dverified = doi_api_checks(rows)
        fails.extend(dfails)
        warns.extend(dwarns)
        verified_rows |= dverified
    if not args.no_network:
        nfails, nwarns, details = network_checks(rows, args.timeout, args.concurrency,
                                                 skip_indices=verified_rows)
        fails.extend(nfails)
        warns.extend(nwarns)

    if args.json:
        print(json.dumps({
            "report": args.report,
            "entries": len(rows),
            "pubmed_api": api_details,
            "crossref_api": doi_details,
            "network": details,
            "fails": fails,
            "warns": warns,
            "verdict": "FAIL" if fails else ("WARN" if warns else "PASS"),
        }, ensure_ascii=False, indent=2))
    else:
        print(render(rows, details, fails, warns, api_details, doi_details))

    return 2 if fails else (1 if warns else 0)


if __name__ == "__main__":
    sys.exit(main())
