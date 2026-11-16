#!/usr/bin/env python3
"""check_citations.py — 快速引用可达性与标题核对（research-integrity skill）。

薄封装：网络逻辑在 citation_core.py。报告级审计（表格合规、编号连续、
悬空引用、孤引）请用 citation_audit.py。

输入文件格式（.txt，UTF-8）：
    # 注释行与空行忽略
    https://example.com/paper
    https://pubmed.ncbi.nlm.nih.gov/33740956/ | In-silico performance
  "|" 后面是期望标题关键词（大小写不敏感的子串/词集合匹配）。

用法：
    python check_citations.py citations.txt [--timeout 20] [--concurrency 8] [--json]

退出码：0 = 全部通过；1 = 存在不可达/标题不符/被阻断的条目；2 = 输入错误。
仅依赖 Python 标准库。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from citation_core import STATUS_TEXT, check_url  # noqa: E402


def parse_citations(path: str) -> list[tuple[str, str | None]]:
    """读取引用文件，返回 [(url, expected_substring|None), ...]"""
    items: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            url, _, expected = line.partition("|")
            url = url.strip()
            expected = expected.strip() or None
            if not url.lower().startswith(("http://", "https://")):
                print(f"[warn] 第 {lineno} 行不是合法 URL，已跳过: {url}", file=sys.stderr)
                continue
            if url in seen:
                print(f"[warn] 第 {lineno} 行 URL 重复，已跳过: {url}", file=sys.stderr)
                continue
            seen.add(url)
            items.append((url, expected))
    return items


def render(rows: list[dict]) -> str:
    width = max([len(r["url"]) for r in rows] + [10])
    lines = []
    for r in rows:
        title = r["title"][:70] or "-"
        line = f"[{STATUS_TEXT[r['result']]:<11}] {r['url']:<{width}}  {title}"
        if r["detail"]:
            line += f"  ({r['detail']})"
        lines.append(line)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["result"]] = counts.get(r["result"], 0) + 1
    lines.append("")
    lines.append(
        "汇总: 共 {total} 条 | OK {ok} | MISMATCH {mm} | BLOCKED {bl} | UNREACHABLE {un}".format(
            total=len(rows),
            ok=counts.get("ok", 0),
            mm=counts.get("mismatch", 0),
            bl=counts.get("blocked", 0),
            un=counts.get("unreachable", 0),
        )
    )
    lines.append(
        "结论: "
        + ("全部通过" if counts.keys() <= {"ok"} else "存在问题条目，按铁律处置（标待验证/删除/升级通道）")
    )
    lines.append("提示: BLOCKED 仅说明本通道被挡，先按 tool-routing 升级浏览器通道再判「待验证」。")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="快速引用可达性与标题核对")
    parser.add_argument("citations", help="引用文件：每行一个 URL，可用 ' | ' 追加期望标题关键词")
    parser.add_argument("--timeout", type=float, default=15.0, help="单条超时秒数（默认 15）")
    parser.add_argument("--concurrency", type=int, default=5, help="并发数（默认 5）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出明细")
    args = parser.parse_args()

    try:
        items = parse_citations(args.citations)
    except OSError as exc:
        print(f"[error] 无法读取输入文件: {exc}", file=sys.stderr)
        return 2
    if not items:
        print("[error] 输入文件中没有有效 URL", file=sys.stderr)
        return 2

    rows: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = [pool.submit(check_url, url, exp, args.timeout) for url, exp in items]
        for fut in concurrent.futures.as_completed(futures):
            rows.append(fut.result())
    rows.sort(key=lambda r: r["url"])

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(render(rows))

    return 0 if all(r["result"] == "ok" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
