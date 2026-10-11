#!/usr/bin/env python3
"""Rename RTL files to match VERILOG_SOURCES from harness src/.env.

Example:
    python3 scripts/rename_rtl_from_env_sources.py gpt-4o-mini-6

This scans:
    <model_dir>/<datapoint>/harness/<issue>/src/.env
    <model_dir>/<datapoint>/harness/<issue>/rtl/

For each issue, it derives the expected RTL filename from VERILOG_SOURCES and
renames a best candidate file in rtl/ when safe to do so.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VALID_RTL_SUFFIXES = {".sv", ".v"}


def parse_simple_env(env_path: Path) -> Dict[str, str]:
    """Parse KEY=VALUE lines from an .env file."""
    values: Dict[str, str] = {}

    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
            value = value[1:-1]

        values[key] = value

    return values


def expected_name_from_env(env_values: Dict[str, str]) -> Tuple[Optional[str], str]:
    """Return expected RTL filename from VERILOG_SOURCES.

    Returns:
        (expected_name, reason_if_missing_or_ambiguous)
    """
    verilog_sources = (env_values.get("VERILOG_SOURCES") or "").strip()
    if not verilog_sources:
        return None, "missing VERILOG_SOURCES"

    toplevel = (env_values.get("TOPLEVEL") or "").strip()
    expected_names: List[str] = []

    for token in verilog_sources.split():
        token = token.strip()
        if not token:
            continue

        token_name = Path(token).name
        if not token_name:
            continue

        if "*" in token_name:
            token_suffix = Path(token_name).suffix
            if toplevel and token_suffix in VALID_RTL_SUFFIXES:
                expected_names.append(f"{toplevel}{token_suffix}")
            continue

        if Path(token_name).suffix in VALID_RTL_SUFFIXES:
            expected_names.append(token_name)

    # Keep order but deduplicate
    deduped: List[str] = []
    for item in expected_names:
        if item not in deduped:
            deduped.append(item)

    if not deduped:
        return None, "no usable RTL target in VERILOG_SOURCES"
    if len(deduped) > 1:
        return None, f"multiple RTL targets in VERILOG_SOURCES: {', '.join(deduped)}"

    return deduped[0], ""


def pick_candidate_for_rename(rtl_dir: Path, expected_name: str, toplevel: str) -> Tuple[Optional[Path], str]:
    """Select an existing RTL file that can be safely renamed."""
    existing = sorted(
        [p for p in rtl_dir.iterdir() if p.is_file() and p.suffix in VALID_RTL_SUFFIXES],
        key=lambda p: p.name,
    )

    if not existing:
        return None, "rtl folder has no .sv/.v files"

    # If exact target already exists, no rename needed.
    target_path = rtl_dir / expected_name
    if target_path.exists():
        return target_path, "already matches expected name"

    expected_stem = Path(expected_name).stem

    # Prefer file with stem matching TOPLEVEL.
    if toplevel:
        for file_path in existing:
            if file_path.stem == toplevel:
                return file_path, "matched candidate by TOPLEVEL"

    # Otherwise prefer file with same stem as expected and wrong extension.
    for file_path in existing:
        if file_path.stem == expected_stem:
            return file_path, "matched candidate by expected stem"

    if len(existing) == 1:
        return existing[0], "single RTL file in folder"

    names = ", ".join(p.name for p in existing)
    return None, f"ambiguous RTL files: {names}"


def process_issue(issue_dir: Path, model_root: Path, dry_run: bool) -> Tuple[str, str]:
    """Process one harness issue directory."""
    env_path = issue_dir / "src" / ".env"
    rtl_dir = issue_dir / "rtl"

    rel_issue = issue_dir.relative_to(model_root)

    if not env_path.exists():
        return "SKIP", f"{rel_issue}: missing src/.env"
    if not rtl_dir.exists() or not rtl_dir.is_dir():
        return "SKIP", f"{rel_issue}: missing rtl directory"

    env_values = parse_simple_env(env_path)
    expected_name, reason = expected_name_from_env(env_values)
    if expected_name is None:
        return "SKIP", f"{rel_issue}: {reason}"

    toplevel = (env_values.get("TOPLEVEL") or "").strip()
    candidate, pick_reason = pick_candidate_for_rename(rtl_dir, expected_name, toplevel)
    if candidate is None:
        return "SKIP", f"{rel_issue}: {pick_reason}"

    target_path = rtl_dir / expected_name

    # Candidate equals target means already aligned.
    if candidate.resolve() == target_path.resolve():
        return "MATCH", f"{rel_issue}: already aligned ({expected_name})"

    if target_path.exists():
        return "SKIP", f"{rel_issue}: target already exists ({expected_name})"

    if dry_run:
        return "RENAME", f"{rel_issue}: WOULD_RENAME {candidate.name} -> {expected_name} ({pick_reason})"

    candidate.rename(target_path)
    return "RENAME", f"{rel_issue}: RENAMED {candidate.name} -> {expected_name} ({pick_reason})"


def collect_issue_dirs(model_root: Path) -> List[Path]:
    """Collect all harness/<issue> directories under a model directory."""
    issue_dirs: List[Path] = []

    for datapoint_dir in sorted(model_root.iterdir()):
        if not datapoint_dir.is_dir():
            continue

        harness_dir = datapoint_dir / "harness"
        if not harness_dir.is_dir():
            continue

        for issue_dir in sorted(harness_dir.iterdir()):
            if issue_dir.is_dir():
                issue_dirs.append(issue_dir)

    return issue_dirs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rename harness RTL files to match VERILOG_SOURCES in src/.env"
    )
    parser.add_argument(
        "model_dir",
        help="Model directory to scan (example: gpt-4o-mini-6)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned renames without changing files",
    )
    args = parser.parse_args()

    model_root = Path(args.model_dir).resolve()
    if not model_root.exists() or not model_root.is_dir():
        print(f"Invalid model directory: {model_root}")
        return 1

    issue_dirs = collect_issue_dirs(model_root)
    if not issue_dirs:
        print(f"No harness issue directories found under {model_root}")
        return 0

    counts = {"RENAME": 0, "MATCH": 0, "SKIP": 0}
    skipped_messages: List[str] = []

    for issue_dir in issue_dirs:
        status, message = process_issue(issue_dir, model_root, args.dry_run)
        counts[status] += 1
        print(f"[{status}] {message}")
        if status == "SKIP":
            skipped_messages.append(message)

    print(
        "Done. "
        f"renamed={counts['RENAME']} "
        f"matched={counts['MATCH']} "
        f"skipped={counts['SKIP']} "
        f"total_issues={len(issue_dirs)}"
    )

    if skipped_messages:
        print("\nSkipped issues:")
        for item in skipped_messages:
            print(f"- {item}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
