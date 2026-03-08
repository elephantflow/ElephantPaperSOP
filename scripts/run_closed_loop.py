#!/usr/bin/env python3
"""Run ElephantPaperSOP + ElephantReviewer as a one-click closed loop."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-click closed loop: optional SOP step, then template review."
    )
    parser.add_argument(
        "--sop-cmd",
        help=(
            "Optional command to run ElephantPaperSOP generation step first. "
            "Example: 'python3 scripts/build_v1.py --batch 10'"
        ),
    )
    parser.add_argument(
        "--sop-workdir",
        default=".",
        help="Working directory for --sop-cmd (default: current directory).",
    )
    parser.add_argument(
        "--python",
        default="python3",
        help="Python executable used to run ElephantReviewer (default: python3).",
    )

    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--templates-local-dir",
        help="Local template directory for ElephantReviewer.",
    )
    src.add_argument(
        "--github-owner",
        help="GitHub owner/org for ElephantReviewer source.",
    )
    parser.add_argument("--github-repo", help="GitHub repo name.")
    parser.add_argument(
        "--github-path",
        default="data/v1/templates",
        help="Path inside GitHub repo (default: data/v1/templates).",
    )
    parser.add_argument(
        "--github-ref", default="main", help="Git ref for GitHub mode (default: main)."
    )

    parser.add_argument(
        "--reviewer-script",
        help="Path to ElephantReviewer script. Default resolves from workspace layout.",
    )
    parser.add_argument(
        "--output",
        help="Output report path. Default: ./reviewer_reports/elephantreviewer_<timestamp>.md",
    )
    parser.add_argument(
        "--spotlight-dir",
        help=(
            "Optional spotlight PDF directory. If set, run abstract gap analysis "
            "before ElephantReviewer."
        ),
    )
    parser.add_argument(
        "--spotlight-script",
        help="Path to spotlight gap analyzer script. Default resolves from workspace layout.",
    )
    parser.add_argument(
        "--spotlight-output",
        help="Spotlight markdown report path. Default: ./reviewer_reports/spotlight_gap_<timestamp>.md",
    )
    parser.add_argument(
        "--spotlight-feedback-json",
        help="Optional spotlight SOP-feedback JSON output path.",
    )
    parser.add_argument(
        "--spotlight-max-papers",
        type=int,
        default=5,
        help="Max spotlight papers to process (default: 5).",
    )
    parser.add_argument(
        "--spotlight-select-mode",
        choices=["head", "incremental"],
        default="head",
        help=(
            "Paper selection mode for spotlight-dir: "
            "'head' uses first N sorted PDFs; "
            "'incremental' selects N unseen PDFs each run."
        ),
    )
    parser.add_argument(
        "--spotlight-state-file",
        help=(
            "State file path for incremental spotlight selection. "
            "Default: ./reviewer_reports/.spotlight_state.json"
        ),
    )
    parser.add_argument(
        "--spotlight-reset-state",
        action="store_true",
        help="Reset spotlight incremental state before selecting papers.",
    )
    parser.add_argument(
        "--fail-on-p0",
        action="store_true",
        help="Return non-zero exit code when P0 items are found.",
    )
    return parser.parse_args()


def default_reviewer_script() -> Path:
    this = Path(__file__).resolve()
    return this.parents[2] / "elephantreviewer" / "scripts" / "review_templates.py"


def default_output_path() -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.cwd() / "reviewer_reports" / f"elephantreviewer_{ts}.md"


def default_spotlight_script() -> Path:
    this = Path(__file__).resolve()
    return this.parents[2] / "elephantreviewer" / "scripts" / "spotlight_abstract_gap.py"


def default_spotlight_output_path() -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.cwd() / "reviewer_reports" / f"spotlight_gap_{ts}.md"


def default_spotlight_state_path() -> Path:
    return Path.cwd() / "reviewer_reports" / ".spotlight_state.json"


def run_cmd(cmd: list[str], *, cwd: str | None = None) -> None:
    proc = subprocess.run(cmd, cwd=cwd, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def count_priorities(report_text: str) -> tuple[int, int, int]:
    p0 = len(re.findall(r"优先级：`P0`", report_text))
    p1 = len(re.findall(r"优先级：`P1`", report_text))
    p2 = len(re.findall(r"优先级：`P2`", report_text))
    return p0, p1, p2


def select_spotlight_papers(
    spotlight_dir: str,
    max_papers: int,
    mode: str,
    state_file: Path,
    reset_state: bool,
) -> list[Path]:
    pdfs = sorted(
        [p.resolve() for p in Path(spotlight_dir).expanduser().resolve().iterdir() if p.is_file() and p.suffix.lower() == ".pdf"],
        key=lambda p: p.name.lower(),
    )
    if max_papers <= 0:
        raise ValueError("--spotlight-max-papers must be > 0.")
    if not pdfs:
        raise ValueError("No PDF files found in spotlight directory.")

    if mode == "head":
        return pdfs[:max_papers]

    if reset_state and state_file.exists():
        state_file.unlink()

    state: dict[str, object] = {"seen": []}
    if state_file.exists():
        try:
            loaded = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = loaded
        except json.JSONDecodeError:
            state = {"seen": []}
    seen = {str(x) for x in state.get("seen", []) if isinstance(x, str)}
    unseen = [p for p in pdfs if str(p) not in seen]

    if len(unseen) < max_papers:
        raise ValueError(
            f"Not enough unseen PDFs for incremental selection: need {max_papers}, got {len(unseen)}. "
            "Add new papers or use --spotlight-reset-state."
        )

    chosen = unseen[:max_papers]
    new_seen = list(seen | {str(p) for p in chosen})
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"seen": sorted(new_seen)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return chosen


def main() -> int:
    args = parse_args()

    if args.github_owner and not args.github_repo:
        print("[ERROR] --github-owner requires --github-repo.", file=sys.stderr)
        return 2

    step_total = 3 if args.spotlight_dir else 2

    if args.sop_cmd:
        print(f"[STEP 1/{step_total}] Running SOP command in {Path(args.sop_workdir).resolve()}")
        subprocess.run(args.sop_cmd, cwd=args.sop_workdir, shell=True, check=True)
    else:
        print(f"[STEP 1/{step_total}] Skip SOP command (no --sop-cmd provided).")

    if args.spotlight_dir:
        if not args.templates_local_dir:
            print(
                "[ERROR] --spotlight-dir requires --templates-local-dir (local templates must be available).",
                file=sys.stderr,
            )
            return 2
        spotlight_script = (
            Path(args.spotlight_script).expanduser().resolve()
            if args.spotlight_script
            else default_spotlight_script()
        )
        if not spotlight_script.exists():
            print(f"[ERROR] Spotlight script not found: {spotlight_script}", file=sys.stderr)
            return 2
        spotlight_output = (
            Path(args.spotlight_output).expanduser().resolve()
            if args.spotlight_output
            else default_spotlight_output_path()
        )
        spotlight_output.parent.mkdir(parents=True, exist_ok=True)
        spotlight_state_file = (
            Path(args.spotlight_state_file).expanduser().resolve()
            if args.spotlight_state_file
            else default_spotlight_state_path()
        )

        step_idx = 2
        print(f"[STEP {step_idx}/{step_total}] Running spotlight abstract gap analysis...")
        selected_papers = select_spotlight_papers(
            spotlight_dir=args.spotlight_dir,
            max_papers=args.spotlight_max_papers,
            mode=args.spotlight_select_mode,
            state_file=spotlight_state_file,
            reset_state=args.spotlight_reset_state,
        )
        print(
            f"[INFO] Spotlight selection mode={args.spotlight_select_mode}, "
            f"picked={len(selected_papers)} papers"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
            tf.write(json.dumps([str(p) for p in selected_papers], ensure_ascii=False, indent=2))
            paper_list_json = tf.name
        spotlight_cmd = [
            args.python,
            str(spotlight_script),
            "--templates-dir",
            args.templates_local_dir,
            "--spotlight-dir",
            args.spotlight_dir,
            "--output",
            str(spotlight_output),
            "--max-papers",
            str(args.spotlight_max_papers),
            "--paper-list-json",
            paper_list_json,
        ]
        if args.spotlight_feedback_json:
            spotlight_cmd.extend(["--feedback-json", args.spotlight_feedback_json])
        try:
            run_cmd(spotlight_cmd)
        finally:
            Path(paper_list_json).unlink(missing_ok=True)
        print(f"[DONE] Spotlight report: {spotlight_output}")
        if args.spotlight_feedback_json:
            print(f"[DONE] SOP feedback JSON: {Path(args.spotlight_feedback_json).expanduser().resolve()}")

    reviewer_script = (
        Path(args.reviewer_script).expanduser().resolve()
        if args.reviewer_script
        else default_reviewer_script()
    )
    if not reviewer_script.exists():
        print(f"[ERROR] Reviewer script not found: {reviewer_script}", file=sys.stderr)
        return 2

    out = Path(args.output).expanduser().resolve() if args.output else default_output_path()
    out.parent.mkdir(parents=True, exist_ok=True)

    review_cmd = [args.python, str(reviewer_script)]
    if args.templates_local_dir:
        review_cmd.extend(["--local-dir", args.templates_local_dir])
    else:
        review_cmd.extend(
            [
                "--github-owner",
                args.github_owner,
                "--github-repo",
                args.github_repo,
                "--path",
                args.github_path,
                "--ref",
                args.github_ref,
            ]
        )
    review_cmd.extend(["--output", str(out)])

    print(f"[STEP {step_total}/{step_total}] Running ElephantReviewer...")
    run_cmd(review_cmd)

    text = out.read_text(encoding="utf-8", errors="replace")
    p0, p1, p2 = count_priorities(text)
    print(f"[DONE] Report: {out}")
    print(f"[DONE] Priorities: P0={p0}, P1={p1}, P2={p2}")

    if args.fail_on_p0 and p0 > 0:
        print("[FAIL] P0 issues found and --fail-on-p0 is enabled.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
