"""
PMO async/blocking-call audit.

This is a static report tool. It reads pmo_bot.py, flags blocking patterns,
and writes prioritized findings. It does not change trading behavior.

Standalone:
    python pmo_async_audit.py pmo_bot.py
    python pmo_async_audit.py pmo_bot.py --json-output pmo_reports/pmo_async_order_submission_audit.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


BLOCKING_PATTERNS: Sequence[Tuple[str, str, str, str]] = (
    (r"\brequests\.get\s*\(", "HIGH", "Blocking HTTP GET", "Use aiohttp or run requests in a ThreadPoolExecutor."),
    (r"\brequests\.post\s*\(", "HIGH", "Blocking HTTP POST", "Use aiohttp or run requests in a ThreadPoolExecutor."),
    (r"\brequests\.(put|delete|patch)\s*\(", "HIGH", "Blocking HTTP write request", "Use aiohttp or isolate the call from order-critical paths."),
    (r"\btime\.sleep\s*\(", "HIGH", "Blocking sleep", "Use asyncio.sleep in async code or isolate sleep inside a background worker."),
    (r"\.join\s*\(\s*\)", "MEDIUM", "Thread join may block", "Use futures, callback completion, or asyncio.gather where appropriate."),
    (r"\bsubprocess\.(run|call|check_output|Popen)\s*\(", "MEDIUM", "Blocking subprocess call", "Use async subprocess APIs or keep it out of hot paths."),
    (r"\bsqlite3\.connect\s*\(", "MEDIUM", "Synchronous SQLite connection", "Keep DB work off order submission path; consider a worker queue."),
    (r"\bpd\.read_csv\s*\(", "LOW", "Blocking pandas CSV read", "Cache or pre-load heavy CSVs outside frequent polling paths."),
    (r"\bopen\s*\(", "LOW", "Synchronous file I/O", "Keep file writes off order submission path or use a background writer."),
)

HOT_PATH_KEYWORDS = (
    "submit_order",
    "place_order",
    "execute_order",
    "send_order",
    "alpaca_order",
    "paper_order",
    "submit_paper",
    "order_execution",
    "execution",
    "executor",
    "trailing_stop",
    "stop_loss",
    "take_profit",
    "close_position",
    "tradingview_webhook",
    "tv_alert",
    "signal_handler",
)


def _is_hot_function(name: str) -> bool:
    lower = name.lower()
    return any(keyword in lower for keyword in HOT_PATH_KEYWORDS)


def scan_file(path: str | os.PathLike[str]) -> Dict[str, Any]:
    file_path = Path(path)
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    findings: List[Dict[str, Any]] = []
    current_function = "module_level"
    current_function_start = 1
    current_is_async = False
    current_hot_path = False

    for index, line in enumerate(lines, start=1):
        def_match = re.match(r"\s*(async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        if def_match:
            current_function = def_match.group(2)
            current_function_start = index
            current_is_async = bool(def_match.group(1))
            current_hot_path = _is_hot_function(current_function)

        for pattern, severity, description, fix in BLOCKING_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                findings.append(
                    {
                        "line": index,
                        "function": current_function,
                        "function_start": current_function_start,
                        "severity": severity,
                        "description": description,
                        "fix": fix,
                        "hot_path": current_hot_path,
                        "async_function": current_is_async,
                        "code": line.strip()[:220],
                    }
                )

    severity_counts = {
        "HIGH": sum(1 for finding in findings if finding["severity"] == "HIGH"),
        "MEDIUM": sum(1 for finding in findings if finding["severity"] == "MEDIUM"),
        "LOW": sum(1 for finding in findings if finding["severity"] == "LOW"),
    }
    hot_path_findings = [finding for finding in findings if finding["hot_path"]]
    critical = [finding for finding in hot_path_findings if finding["severity"] == "HIGH"]

    return {
        "ok": True,
        "source": "pmo_async_audit",
        "file": str(file_path),
        "file_name": file_path.name,
        "total_lines": len(lines),
        "findings_total": len(findings),
        "severity_counts": severity_counts,
        "hot_path_findings": len(hot_path_findings),
        "critical_hot_path_findings": len(critical),
        "findings": findings,
        "top_recommendations": build_recommendations(findings),
    }


def build_recommendations(findings: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    findings = list(findings)
    recommendations: List[Dict[str, str]] = []
    if any(f["hot_path"] and f["severity"] == "HIGH" and "HTTP" in f["description"] for f in findings):
        recommendations.append(
            {
                "priority": "P0",
                "title": "Isolate order-submission HTTP calls",
                "action": "Wrap Alpaca order POST/close calls in a ThreadPoolExecutor before attempting a full async refactor.",
            }
        )
    if any(f["hot_path"] and "sleep" in f["description"].lower() for f in findings):
        recommendations.append(
            {
                "priority": "P1",
                "title": "Remove blocking sleep from order-critical loops",
                "action": "Move sleeps to scheduler/background loops and keep scoring/execution routes responsive.",
            }
        )
    if any("CSV" in f["description"] or "file I/O" in f["description"] for f in findings):
        recommendations.append(
            {
                "priority": "P2",
                "title": "Move journal writes off the hot path",
                "action": "Use a background writer queue for CSV/report writes after order submission decisions are complete.",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "priority": "INFO",
                "title": "No urgent async refactor found",
                "action": "Keep monitoring order latency and only refactor blocking calls that appear in measured bottlenecks.",
            }
        )
    return recommendations


def print_report(report: Dict[str, Any], max_rows: int = 80) -> None:
    print("PMO ASYNC ORDER SUBMISSION AUDIT")
    print("=" * 72)
    print(f"File: {report['file_name']} | Lines: {report['total_lines']}")
    print(
        "Findings: {total} | HIGH {high} | MEDIUM {medium} | LOW {low} | hot path {hot}".format(
            total=report["findings_total"],
            high=report["severity_counts"]["HIGH"],
            medium=report["severity_counts"]["MEDIUM"],
            low=report["severity_counts"]["LOW"],
            hot=report["hot_path_findings"],
        )
    )
    print(f"Critical hot-path findings: {report['critical_hot_path_findings']}")
    print()

    print("TOP RECOMMENDATIONS")
    print("-" * 72)
    for rec in report["top_recommendations"]:
        print(f"{rec['priority']} - {rec['title']}")
        print(f"     {rec['action']}")
    print()

    findings = sorted(
        report["findings"],
        key=lambda item: (
            0 if item["hot_path"] and item["severity"] == "HIGH" else 1 if item["hot_path"] else 2,
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(item["severity"], 9),
            item["line"],
        ),
    )
    print("PRIORITIZED FINDINGS")
    print("-" * 72)
    for finding in findings[:max_rows]:
        marker = "HOT" if finding["hot_path"] else "COLD"
        print(f"{finding['severity']:6s} {marker:4s} line {finding['line']:>6} in {finding['function']}()")
        print(f"       {finding['description']}: {finding['code']}")
        print(f"       Fix: {finding['fix']}")
    if len(findings) > max_rows:
        print(f"... {len(findings) - max_rows} more findings omitted from text report. JSON has the full list.")


def main() -> int:
    parser = argparse.ArgumentParser(description="PMO async/blocking-call audit")
    parser.add_argument("python_file", help="Path to pmo_bot.py")
    parser.add_argument("--json-output", default="", help="Optional path for full JSON output")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    parser.add_argument("--max-rows", type=int, default=80, help="Max findings in text output")
    args = parser.parse_args()

    report = scan_file(args.python_file)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report, max_rows=args.max_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
