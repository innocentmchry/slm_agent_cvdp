#!/usr/bin/env python3
"""Recover RTL files from agent report logs.

For each reports/<issue>_agent.txt file, this script extracts the code block from the
highest-numbered EXTRACTED CODE iteration and writes it into harness/<issue>/rtl.
Existing RTL files are replaced.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List, Optional, Tuple

SEPARATOR_PATTERN = r"=+"
EXTRACTED_BLOCK_RE = re.compile(
    rf"{SEPARATOR_PATTERN}\n"
    r"EXTRACTED CODE \(Iteration (\d+)\):\n"
    rf"{SEPARATOR_PATTERN}\n"
    r"(.*?)"
    rf"\n{SEPARATOR_PATTERN}\n",
    re.DOTALL,
)
MODULE_NAME_RE = re.compile(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_]*)")


def parse_latest_extracted_code(log_text: str) -> Optional[Tuple[int, str]]:
    matches = EXTRACTED_BLOCK_RE.findall(log_text)
    if not matches:
        return None

    best_iter = -1
    best_code = ""
    for iteration_str, code in matches:
        iteration = int(iteration_str)
        if iteration >= best_iter:
            best_iter = iteration
            best_code = code

    return best_iter, best_code.rstrip() + "\n"


def choose_target_rtl_file(rtl_dir: Path, code: str) -> Path:
    rtl_files: List[Path] = sorted(
        [*rtl_dir.glob("*.sv"), *rtl_dir.glob("*.v")], key=lambda p: p.name
    )

    module_match = MODULE_NAME_RE.search(code)
    module_name = module_match.group(1) if module_match else None

    if rtl_files:
        if module_name:
            for path in rtl_files:
                if path.stem == module_name:
                    return path
        if len(rtl_files) == 1:
            return rtl_files[0]
        return rtl_files[0]

    if module_name:
        return rtl_dir / f"{module_name}.sv"

    return rtl_dir / "recovered_from_agent_log.sv"


def process_report(report_file: Path, root: Path, dry_run: bool) -> Tuple[bool, str]:
    issue_str = report_file.stem.replace("_agent", "")
    if not issue_str.isdigit():
        return False, f"SKIP {report_file}: cannot infer numeric issue id"

    issue_id = int(issue_str)
    datapoint_dir = report_file.parent.parent
    harness_rtl_dir = datapoint_dir / "harness" / str(issue_id) / "rtl"

    if not harness_rtl_dir.exists():
        return False, f"SKIP {report_file}: missing rtl directory {harness_rtl_dir}"

    log_text = report_file.read_text(encoding="utf-8", errors="ignore")
    latest = parse_latest_extracted_code(log_text)
    if latest is None:
        return False, f"SKIP {report_file}: no EXTRACTED CODE block found"

    iteration, code = latest
    target_file = choose_target_rtl_file(harness_rtl_dir, code)

    if not dry_run:
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(code, encoding="utf-8")

    rel_report = report_file.relative_to(root)
    rel_target = target_file.relative_to(root)
    action = "WOULD_REPLACE" if dry_run else "REPLACED"
    return True, f"{action} {rel_target} from {rel_report} (iteration {iteration})"


def collect_reports(model_dir: Path) -> List[Path]:
    """
    Collect report files using expected layout:
    <model_dir>/<datapoint>/reports/<issue>_agent.txt
    """
    report_files: List[Path] = []

    for child in sorted(model_dir.iterdir()):
        if not child.is_dir():
            continue
        reports_dir = child / "reports"
        if not reports_dir.is_dir():
            continue
        report_files.extend(sorted(reports_dir.glob("*_agent.txt")))

    return report_files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover RTL from agent logs for one model directory"
    )
    parser.add_argument(
        "directory",
        help="Model directory to process (e.g. gpt-4o-mini-6)",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Deprecated alias for directory; kept for backward compatibility",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print replacements without writing files",
    )
    args = parser.parse_args()

    target_dir = args.directory if args.directory is not None else args.root

    root = Path(target_dir).resolve()
    if not root.exists() or not root.is_dir():
        print(f"Invalid directory: {root}")
        return 1

    report_files = collect_reports(root)

    if not report_files:
        print(f"No report files found under {root}")
        return 0

    replaced = 0
    skipped = 0

    for report_file in report_files:
        ok, message = process_report(report_file, root, args.dry_run)
        print(message)
        if ok:
            replaced += 1
        else:
            skipped += 1

    print(
        f"Done. recovered={replaced} skipped={skipped} total_reports={len(report_files)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
