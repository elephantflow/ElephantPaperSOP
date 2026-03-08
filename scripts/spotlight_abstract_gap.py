#!/usr/bin/env python3
"""Generate paper drafts from spotlight abstracts and compare against original papers."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = None  # type: ignore


PLACEHOLDER_RE = re.compile(r"<([^>]+)>")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")

PROBLEM_KWS = (
    "challenge",
    "difficult",
    "hard",
    "limitation",
    "limited",
    "problem",
    "bottleneck",
    "expensive",
)
METHOD_KWS = ("we propose", "we present", "introduce", "design", "framework", "method")
RESULT_KWS = ("outperform", "improve", "achieve", "state-of-the-art", "sota", "show", "results")
IMPACT_KWS = ("enables", "benefit", "applicable", "application", "real-world", "deploy")

SECTION_FIELDS = {
    "introduction": "full_intro_template",
    "method": "method_template",
    "experiments": "experiments_template",
    "conclusion": "conclusion_template",
}


@dataclass
class SpotlightPaper:
    path: Path
    title: str
    abstract: str
    original_text: str


@dataclass
class TemplateBundle:
    path: str
    template_id: str
    name: str
    data: Dict[str, object]


def _clean_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = text.replace("-\n", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_sentences(text: str) -> List[str]:
    text = _clean_text(text)
    if not text:
        return []
    parts = [p.strip() for p in SENTENCE_RE.split(text) if p.strip()]
    if len(parts) == 1 and len(parts[0]) > 300:
        chunks = re.split(r"\.\s+", parts[0])
        return [c.strip() + ("." if c and not c.endswith(".") else "") for c in chunks if c.strip()]
    return parts


def _read_pdf_text(pdf_path: Path, max_pages: int = 6) -> str:
    if PdfReader is None:
        raise RuntimeError("pypdf is required but not available.")
    reader = PdfReader(str(pdf_path))
    texts: List[str] = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            break
        texts.append(page.extract_text() or "")
    return "\n".join(texts)


def _extract_abstract_from_text(text: str) -> str:
    norm = text.replace("\r", "\n")
    norm = re.sub(r"[ \t]+", " ", norm)
    pattern = re.compile(
        r"(?:^|\n)\s*abstract\s*[\n:]\s*(.+?)(?=\n\s*(?:1[\.\s]|i[\.\s]|introduction|keywords)\b)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(norm)
    if m:
        return _clean_text(m.group(1))

    idx = norm.lower().find("abstract")
    if idx >= 0:
        tail = norm[idx + len("abstract") : idx + len("abstract") + 2400]
        cuts = [
            x for x in [
                tail.lower().find("\nintroduction"),
                tail.lower().find(" 1 introduction"),
                tail.lower().find(" keywords"),
            ]
            if x > 0
        ]
        if cuts:
            tail = tail[: min(cuts)]
        return _clean_text(tail)
    return ""


def _extract_body_from_text(text: str) -> str:
    norm = text.replace("\r", "\n")
    lower = norm.lower()

    start_candidates = []
    for kw in ["\n1 introduction", "\nintroduction", "\n1. introduction", "\ni introduction"]:
        pos = lower.find(kw)
        if pos >= 0:
            start_candidates.append(pos)
    start = min(start_candidates) if start_candidates else 0

    end_candidates = []
    for kw in ["\nreferences", "\nacknowledg", "\nappendix"]:
        pos = lower.find(kw, start + 200)
        if pos >= 0:
            end_candidates.append(pos)
    end = min(end_candidates) if end_candidates else len(norm)

    body = norm[start:end]
    body = re.sub(r"\bfigure\s*\d+[^.]*\.", " ", body, flags=re.IGNORECASE)
    body = re.sub(r"\btable\s*\d+[^.]*\.", " ", body, flags=re.IGNORECASE)
    body = re.sub(r"\s+", " ", body)
    return _clean_text(body)


def extract_paper_from_pdf(pdf_path: Path) -> SpotlightPaper:
    text = _read_pdf_text(pdf_path, max_pages=6)
    abstract = _extract_abstract_from_text(text)
    body = _extract_body_from_text(text)
    if not abstract:
        abstract = " ".join(_split_sentences(text)[:8])
    if not body:
        body = " ".join(_split_sentences(text)[:40])
    return SpotlightPaper(path=pdf_path, title=pdf_path.stem, abstract=abstract, original_text=body)


def classify_sentences(sentences: Sequence[str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {"problem": [], "method": [], "result": [], "impact": [], "other": []}
    for s in sentences:
        lower = s.lower()
        if any(k in lower for k in PROBLEM_KWS):
            out["problem"].append(s)
        elif any(k in lower for k in METHOD_KWS):
            out["method"].append(s)
        elif any(k in lower for k in RESULT_KWS):
            out["result"].append(s)
        elif any(k in lower for k in IMPACT_KWS):
            out["impact"].append(s)
        else:
            out["other"].append(s)
    return out


def load_best_template(templates_dir: Path) -> TemplateBundle:
    files = sorted(p for p in templates_dir.rglob("*.json") if p.is_file())
    best: TemplateBundle | None = None
    best_score = -1

    for p in files:
        try:
            obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        intro = obj.get("full_intro_template", [])
        method = obj.get("method_template", [])
        exps = obj.get("experiments_template", [])
        score = len(intro) + len(method) + len(exps)
        if score > best_score:
            best_score = score
            best = TemplateBundle(
                path=str(p),
                template_id=str(obj.get("id", p.stem)),
                name=str(obj.get("name", obj.get("id", p.stem))),
                data=obj,
            )

    if best is None:
        raise SystemExit("[ERROR] No valid JSON templates found.")
    return best


def _pick_signal(cls: Dict[str, List[str]], key: str, fallback_idx: int = 0) -> str:
    if cls[key]:
        return cls[key][0]
    other = cls["other"]
    if other and fallback_idx < len(other):
        return other[fallback_idx]
    return ""


def _expand_line(line: str, repl: Dict[str, str], default_text: str) -> str:
    def _repl(m: re.Match[str]) -> str:
        key = m.group(1).strip().lower()
        for rk, rv in repl.items():
            if rk in key and rv:
                return rv
        return default_text

    out = PLACEHOLDER_RE.sub(_repl, line)
    out = re.sub(r"\b[AEMPC]\d+\s*:\s*", "", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def generate_paper_draft_from_abstract(template: TemplateBundle, abstract: str) -> str:
    sents = _split_sentences(abstract)
    cls = classify_sentences(sents)
    problem = _pick_signal(cls, "problem", 0)
    method = _pick_signal(cls, "method", 1)
    result = _pick_signal(cls, "result", 2)
    impact = _pick_signal(cls, "impact", 3)
    numeric = next((s for s in sents if re.search(r"\b\d", s)), result)

    default_text = abstract[:180] + ("..." if len(abstract) > 180 else "")
    repl = {
        "problem": problem,
        "challenge": problem,
        "task": problem,
        "method": method,
        "approach": method,
        "module": method,
        "result": result,
        "finding": result,
        "evidence": numeric,
        "metric": numeric,
        "impact": impact or result,
        "application": impact or result,
    }

    sections: List[str] = []
    for sec_name, field in SECTION_FIELDS.items():
        raw_lines = template.data.get(field, [])
        lines = [str(x) for x in raw_lines] if isinstance(raw_lines, list) else ([str(raw_lines)] if raw_lines else [])
        if not lines:
            continue
        expanded = [_expand_line(line, repl, default_text) for line in lines[:6]]
        expanded = [e for e in expanded if e]
        if not expanded:
            continue
        sec_text = " ".join(expanded)
        sections.append(f"{sec_name.upper()}: {sec_text}")

    if not sections:
        return abstract
    return "\n\n".join(sections)


def _sentence_stats(text: str) -> Tuple[int, float]:
    sents = _split_sentences(text)
    if not sents:
        return 0, 0.0
    avg_words = sum(len(s.split()) for s in sents) / len(sents)
    return len(sents), avg_words


def _has_numeric_evidence(text: str) -> bool:
    return bool(re.search(r"\b\d+(\.\d+)?(%|x|fps|ms|m|k|b)?\b", text.lower()))


def _token_set(text: str) -> set[str]:
    return {w.lower() for w in WORD_RE.findall(text) if len(w) >= 4}


def _detect_sections(text: str) -> Dict[str, bool]:
    lower = text.lower()
    return {
        "introduction": "introduction" in lower,
        "method": "method" in lower,
        "experiments": "experiment" in lower,
        "conclusion": "conclusion" in lower,
    }


def compare_draft_to_original(original: str, generated: str) -> Dict[str, object]:
    o_count, o_avg = _sentence_stats(original)
    g_count, g_avg = _sentence_stats(generated)

    o_tokens = _token_set(original)
    g_tokens = _token_set(generated)
    overlap = len(o_tokens & g_tokens)
    union = len(o_tokens | g_tokens) if (o_tokens or g_tokens) else 1
    jaccard = overlap / union

    o_sections = _detect_sections(original)
    g_sections = _detect_sections(generated)
    missing_sections = [k for k, v in o_sections.items() if v and not g_sections.get(k, False)]

    gaps: List[str] = []
    if abs(o_count - g_count) >= 10:
        gaps.append(f"篇幅差距较大：原文 {o_count} 句，生成稿 {g_count} 句。")
    if abs(o_avg - g_avg) > 7:
        gaps.append(f"句长风格偏移明显：原文均值 {o_avg:.1f} 词，生成稿 {g_avg:.1f} 词。")
    if jaccard < 0.10:
        gaps.append(f"术语重合度较低（Jaccard={jaccard:.2f}），模板稿与原文论述词汇差异大。")
    if missing_sections:
        gaps.append(f"缺少与原文对应的章节信号：{', '.join(missing_sections)}。")
    if _has_numeric_evidence(original) and not _has_numeric_evidence(generated):
        gaps.append("生成稿缺少数字证据表达（指标、提升幅度或开销）。")
    if not gaps:
        gaps.append("结构接近原文，但仍需人工细化术语准确性与论断边界。")

    return {
        "original_sentence_count": o_count,
        "generated_sentence_count": g_count,
        "original_avg_words": round(o_avg, 2),
        "generated_avg_words": round(g_avg, 2),
        "token_jaccard": round(jaccard, 3),
        "numeric_evidence_original": _has_numeric_evidence(original),
        "numeric_evidence_generated": _has_numeric_evidence(generated),
        "missing_sections": missing_sections,
        "gaps": gaps,
    }


def build_sop_feedback(comparisons: Sequence[Dict[str, object]]) -> Dict[str, object]:
    summary = {
        "large_length_gap": 0,
        "low_term_overlap": 0,
        "missing_section_signals": 0,
        "missing_numeric_evidence": 0,
    }

    for c in comparisons:
        txt = " ".join(str(x) for x in c.get("gaps", [])) if isinstance(c.get("gaps"), list) else ""
        if "篇幅差距较大" in txt:
            summary["large_length_gap"] += 1
        if "术语重合度较低" in txt:
            summary["low_term_overlap"] += 1
        if "缺少与原文对应的章节信号" in txt:
            summary["missing_section_signals"] += 1
        if "缺少数字证据" in txt:
            summary["missing_numeric_evidence"] += 1

    targets: List[Dict[str, str]] = []
    if summary["low_term_overlap"] >= 2:
        targets.append(
            {
                "section": "introduction/method",
                "needed_signal": "术语与任务定义更贴近顶会论文写法",
                "paper_selection_hint": "按子领域补充术语密集论文，提炼术语表和固定表达",
            }
        )
    if summary["missing_section_signals"] >= 2:
        targets.append(
            {
                "section": "method/experiments/conclusion",
                "needed_signal": "从 abstract 扩展到全文的章节过渡模板",
                "paper_selection_hint": "优先采样章节结构清晰且标题规范的论文",
            }
        )
    if summary["missing_numeric_evidence"] >= 2:
        targets.append(
            {
                "section": "experiments",
                "needed_signal": "结果段必须含数字提升与代价信息",
                "paper_selection_hint": "加入摘要与实验段都含量化对比的论文",
            }
        )
    if summary["large_length_gap"] >= 2:
        targets.append(
            {
                "section": "all",
                "needed_signal": "从短摘要到长正文的展开策略",
                "paper_selection_hint": "采样长引言/短引言两类论文，分桶构建展开模板",
            }
        )

    if not targets:
        targets.append(
            {
                "section": "all",
                "needed_signal": "继续扩展模板覆盖度",
                "paper_selection_hint": "每轮新增10篇，覆盖至少4个子方向",
            }
        )

    return {
        "summary": summary,
        "next_batch_size_hint": 10,
        "exploration_targets": targets,
    }


def build_markdown(
    papers: Sequence[SpotlightPaper],
    template: TemplateBundle,
    generated: Sequence[str],
    comparisons: Sequence[Dict[str, object]],
    sop_feedback: Dict[str, object],
) -> str:
    lines: List[str] = []
    lines.append("# ElephantReviewer Spotlight Paper-Draft Gap Report")
    lines.append("")
    lines.append(f"- 模板来源：`{template.path}`")
    lines.append(f"- 使用模板：`{template.template_id}` · {template.name}")
    lines.append(f"- 对比论文数：{len(papers)}")
    lines.append("")

    for i, (paper, gen, cmp_obj) in enumerate(zip(papers, generated, comparisons), start=1):
        lines.append(f"## {i}) {paper.title}")
        lines.append(f"- 文件：`{paper.path}`")
        lines.append("- 输入 abstract（摘录）：")
        lines.append("")
        lines.append(_clean_text(paper.abstract)[:800])
        lines.append("")
        lines.append("- 生成的论文原文草稿（基于模板展开）：")
        lines.append("")
        lines.append(gen)
        lines.append("")
        lines.append("- 与原文正文差距：")
        for gap in cmp_obj.get("gaps", []):  # type: ignore[arg-type]
            lines.append(f"  - {gap}")
        lines.append("")

    lines.append("## 给 ElephantPaperSOP 的反馈意见")
    lines.append("")
    lines.append(f"- 建议下一轮 batch 大小：`{sop_feedback.get('next_batch_size_hint', 10)}`")
    for item in sop_feedback.get("exploration_targets", []):  # type: ignore[assignment]
        if not isinstance(item, dict):
            continue
        lines.append(
            "- "
            + f"[{item.get('section', 'unknown')}] "
            + f"{item.get('needed_signal', '')}；"
            + f"采样建议：{item.get('paper_selection_hint', '')}"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Read spotlight abstracts, generate paper drafts from templates, and compare with original papers."
    )
    p.add_argument("--templates-dir", required=True, help="Local template directory (e.g., data/v1/templates).")
    p.add_argument("--spotlight-dir", required=True, help="Directory containing spotlight paper PDFs.")
    p.add_argument("--output", required=True, help="Markdown report output path.")
    p.add_argument("--feedback-json", help="Optional JSON output for SOP feedback.")
    p.add_argument("--max-papers", type=int, default=5, help="Maximum number of papers to process (default: 5).")
    p.add_argument(
        "--paper-list-json",
        help="Optional JSON file containing an ordered list of PDF paths to process in this run.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    templates_dir = Path(args.templates_dir).expanduser().resolve()
    spotlight_dir = Path(args.spotlight_dir).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    feedback_json = Path(args.feedback_json).expanduser().resolve() if args.feedback_json else None

    if not templates_dir.exists():
        raise SystemExit(f"[ERROR] Templates directory not found: {templates_dir}")
    if not spotlight_dir.exists():
        raise SystemExit(f"[ERROR] Spotlight directory not found: {spotlight_dir}")

    template = load_best_template(templates_dir)

    if args.paper_list_json:
        paper_list_path = Path(args.paper_list_json).expanduser().resolve()
        if not paper_list_path.exists():
            raise SystemExit(f"[ERROR] paper list json not found: {paper_list_path}")
        payload = json.loads(paper_list_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise SystemExit("[ERROR] --paper-list-json must be a JSON list of file paths.")
        pdfs = [Path(x).expanduser().resolve() for x in payload]
        pdfs = [p for p in pdfs if p.is_file() and p.suffix.lower() == ".pdf"]
        if args.max_papers > 0:
            pdfs = pdfs[: args.max_papers]
    else:
        pdfs = sorted([p for p in spotlight_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"])[: args.max_papers]
    if not pdfs:
        raise SystemExit("[ERROR] No PDF files found in spotlight directory.")

    papers = [extract_paper_from_pdf(p) for p in pdfs]

    generated: List[str] = []
    comparisons: List[Dict[str, object]] = []
    for paper in papers:
        draft = generate_paper_draft_from_abstract(template, paper.abstract)
        generated.append(draft)
        comparisons.append(compare_draft_to_original(paper.original_text, draft))

    sop_feedback = build_sop_feedback(comparisons)
    report = build_markdown(papers, template, generated, comparisons, sop_feedback)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"[OK] Wrote spotlight gap report to: {output}")

    if feedback_json:
        payload = {
            "template_source": template.path,
            "template_id": template.template_id,
            "papers": [str(p.path) for p in papers],
            "comparisons": comparisons,
            "sop_feedback": sop_feedback,
        }
        feedback_json.parent.mkdir(parents=True, exist_ok=True)
        feedback_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] Wrote SOP feedback JSON to: {feedback_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
