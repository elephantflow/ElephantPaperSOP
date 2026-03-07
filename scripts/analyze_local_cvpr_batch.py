#!/usr/bin/env python3
import argparse
import base64
import gzip
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
V1_DIR = ROOT / "data/v1"
PAPERS_DIR = V1_DIR / "papers"
TEMPLATES_DIR = V1_DIR / "templates/intro"

SECTION_ORDER = ["introduction", "related_work", "method", "experiments", "conclusion"]

SECTION_CUES = {
    "introduction": ["however", "challenge", "recent", "we propose", "in this paper", "motivate"],
    "method": ["we propose", "framework", "module", "architecture", "design", "optimize"],
    "experiments": ["experiment", "benchmark", "results", "ablation", "compare", "outperform"],
    "conclusion": ["in conclusion", "we summarize", "future work", "limitations"],
}


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u00ad", "")
    text = re.sub(r"-\n", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.encode("utf-8", "ignore").decode("utf-8", "ignore")
    return text.strip()


def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:52]


def extract_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return clean_text("\n".join((p.extract_text() or "") for p in reader.pages))


def heading_hits(text: str):
    patterns = [
        ("introduction", r"\b(?:\d+\s*[\.)]\s*)?introduction\b"),
        ("related_work", r"\b(?:\d+\s*[\.)]\s*)?(?:related work|background|preliminaries)\b"),
        ("method", r"\b(?:\d+\s*[\.)]\s*)?(?:method|methodology|approach)\b"),
        ("experiments", r"\b(?:\d+\s*[\.)]\s*)?(?:experiments|experimental setup|evaluation)\b"),
        ("conclusion", r"\b(?:\d+\s*[\.)]\s*)?conclusions?\b"),
    ]
    low = text.lower()
    hits = []
    for sec, pat in patterns:
        m = re.search(pat, low)
        if m:
            hits.append((sec, m.start()))
    return sorted(hits, key=lambda x: x[1])


def split_sections(text: str):
    hits = heading_hits(text)
    sections = {k: {"status": "pending", "chars": 0, "text": ""} for k in SECTION_ORDER}
    if not hits:
        sections["introduction"] = {"status": "fallback", "chars": min(len(text), 14000), "text": text[:14000]}
        return sections

    for i, (sec, start) in enumerate(hits):
        end = hits[i + 1][1] if i + 1 < len(hits) else len(text)
        chunk = text[start:end].strip()
        if sec in sections and len(chunk) > 120:
            sections[sec] = {"status": "ready", "chars": len(chunk), "text": chunk[:22000]}

    if sections["introduction"]["status"] == "pending":
        sections["introduction"] = {"status": "fallback", "chars": min(len(text), 12000), "text": text[:12000]}
    return sections


def split_sentences(text: str):
    text = re.sub(r"\s+", " ", text)
    arr = re.split(r"(?<=[\.!?])\s+(?=[A-Z0-9])", text)
    return [x.strip() for x in arr if len(x.strip()) >= 70]


def highlight_for(section: str, text: str, k: int = 4):
    sents = split_sentences(text)
    cues = SECTION_CUES.get(section, [])

    def score(s):
        low = s.lower()
        cue_score = sum(1 for c in cues if c in low)
        length_score = min(len(s), 280) / 280
        return cue_score * 2 + length_score

    ranked = sorted(sents, key=score, reverse=True)
    picked = []
    for s in ranked:
        if len(picked) >= k:
            break
        if any(abs(len(s) - len(p["text"])) < 8 and s[:35] == p["text"][:35] for p in picked):
            continue
        picked.append(
            {
                "text": s,
                "rewrite_zh": f"该句可用于{section}段落，表达完整，适合迁移改写。",
                "reusable_pattern": reusable_pattern(section),
            }
        )
    return picked


def reusable_pattern(section: str):
    if section == "introduction":
        return "In <field>, <problem> remains challenging due to <bottleneck>. To address this gap, we propose <method idea>."
    if section == "method":
        return "Our method consists of <module A>, <module B>, and <module C>, where <core module> models <key relation>."
    if section == "experiments":
        return "On <benchmark>, our method achieves <metric>, outperforming <baseline> by <margin>, with ablations validating <component>."
    if section == "conclusion":
        return "In conclusion, we present <method>, demonstrate <result>, and leave <future direction> for follow-up work."
    return "<sentence pattern>"


def pick_template(title: str):
    t = title.lower()
    if any(k in t for k in ["benchmark", "dataset", "task", "open-vocabulary"]):
        return "T4-task-benchmark-definition"
    if any(k in t for k in ["trade", "balance", "efficient", "fast", "mobile"]):
        return "T2-tradeoff-bridge"
    if any(k in t for k in ["transformer", "pipeline", "diffusion", "splat", "sam", "segmentation", "tracking", "depth", "3d"]):
        return "T3-pipeline-reframing"
    return "T1-gap-formalization"


def compress_text(text: str):
    raw = text.encode("utf-8")
    gz = gzip.compress(raw, compresslevel=9)
    return {
        "encoding": "gzip+base64",
        "raw_chars": len(text),
        "raw_bytes": len(raw),
        "compressed_bytes": len(gz),
        "compression_ratio": round((len(gz) / len(raw)), 4) if raw else 0,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "blob": base64.b64encode(gz).decode("ascii"),
    }


def build_record(pid: str, title: str, pdf: Path, batch_id: str):
    full = extract_pdf_text(pdf)
    sections = split_sections(full)

    intro_map = [
        {"template_paragraph": "P1 背景与任务价值", "paper_evidence": "引入任务背景和应用动机。"},
        {"template_paragraph": "P2 现有方法缺口", "paper_evidence": "指出主流方法在关键场景下的不足。"},
        {"template_paragraph": "P3 方法与贡献", "paper_evidence": "概述本文方法主线与核心贡献。"},
    ]

    analysis = {
        "introduction": {
            "status": "ready",
            "highlights": highlight_for("introduction", sections["introduction"]["text"], k=4),
            "template_mapping": intro_map,
            "narrative_flow": ["background", "gap", "method_and_contribution"],
        },
        "method": {
            "status": "ready" if sections["method"]["status"] != "pending" else "pending",
            "highlights": highlight_for("method", sections["method"]["text"], k=3)
            if sections["method"]["status"] != "pending"
            else [],
            "template_mapping": [],
        },
        "experiments": {
            "status": "ready" if sections["experiments"]["status"] != "pending" else "pending",
            "highlights": highlight_for("experiments", sections["experiments"]["text"], k=3)
            if sections["experiments"]["status"] != "pending"
            else [],
            "template_mapping": [],
        },
        "conclusion": {
            "status": "ready" if sections["conclusion"]["status"] != "pending" else "pending",
            "highlights": highlight_for("conclusion", sections["conclusion"]["text"], k=2)
            if sections["conclusion"]["status"] != "pending"
            else [],
            "template_mapping": [],
        },
        "related_work": {"status": "pending", "highlights": [], "template_mapping": []},
    }

    tpl = pick_template(title)
    rec = {
        "schema_version": "paper.v1",
        "paper": {
            "id": pid,
            "title": title,
            "pdf": f"local://{pdf}",
            "template_id": tpl,
            "status": "ready",
            "source": {"batch_from": "local-cvpr2025", "focus": "multi-section"},
        },
        "content": {
            "fulltext": compress_text(full),
            "sections": sections,
            "extraction": {
                "status": "ok",
                "engine": "pypdf",
                "pages": len(PdfReader(str(pdf)).pages),
                "error": "",
                "updated_at": now_iso(),
            },
        },
        "analysis": analysis,
        "history": {"created_at": now_iso(), "updated_at": now_iso(), "batch_id": batch_id},
    }
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--batch-size", type=int, default=50)
    ap.add_argument("--batch-id", default="cvpr2025-local-050")
    args = ap.parse_args()

    pdf_dir = Path(args.pdf_dir)
    pdfs = sorted([p for p in pdf_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"], key=lambda x: x.name.lower())
    if len(pdfs) < args.batch_size:
        raise SystemExit(f"not enough pdfs: {len(pdfs)} < {args.batch_size}")

    PAPERS_DIR.mkdir(parents=True, exist_ok=True)

    papers_meta = []
    failures = []
    i = 0
    rank = 0
    for pdf in pdfs:
        if len(papers_meta) >= args.batch_size:
            break
        rank += 1
        title = pdf.stem.strip()
        pid = f"cvpr2025-{rank:03d}-{slugify(title)}"
        try:
            rec = build_record(pid, title, pdf, args.batch_id)
            out = PAPERS_DIR / f"{pid}.json"
            out.write_text(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            papers_meta.append(
                {
                    "id": pid,
                    "title": title,
                    "template_id": rec["paper"]["template_id"],
                    "status": "ready",
                    "path": str(out.relative_to(ROOT)),
                    "pdf": rec["paper"]["pdf"],
                }
            )
            i += 1
            print(f"[{i}/{args.batch_size}] {pid}")
        except Exception as e:
            failures.append({"pdf": str(pdf), "error": str(e)})
            print(f"[skip] {pdf.name} :: {e}")

    if len(papers_meta) < args.batch_size:
        raise SystemExit(f"only {len(papers_meta)} papers processed successfully; failures={len(failures)}")

    templates = sorted([p.stem for p in TEMPLATES_DIR.glob("*.json")])
    index = {
        "schema_version": "index.v1",
        "version": "v1.1.0",
        "updated_at": now_iso(),
        "focus": "multi-section",
        "sections_supported": SECTION_ORDER,
        "paper_count": len(papers_meta),
        "template_count": len(templates),
        "paths": {"papers_dir": "data/v1/papers", "templates_intro_dir": "data/v1/templates/intro"},
        "templates": templates,
        "papers": papers_meta,
    }
    (V1_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2))
    print(f"done: {len(papers_meta)} papers, failures: {len(failures)}")


if __name__ == "__main__":
    main()
