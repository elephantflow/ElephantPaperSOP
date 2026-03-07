#!/usr/bin/env python3
import base64
import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
OLD_INDEX = ROOT / "data/intro/index.json"
OLD_PAPERS_DIR = ROOT / "data/intro/papers"
OLD_TEMPLATES_DIR = ROOT / "data/intro/templates"

NEW_ROOT = ROOT / "data/v1"
NEW_PAPERS_DIR = NEW_ROOT / "papers"
NEW_TEMPLATES_DIR = NEW_ROOT / "templates/intro"


@dataclass
class SectionSpan:
    name: str
    start: int
    end: int


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = text.replace("\u00ad", "")
    text = re.sub(r"-\n", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def extract_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    blocks = []
    for page in reader.pages:
        blocks.append(page.extract_text() or "")
    return clean_text("\n".join(blocks))


def normalize_heading(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def find_heading_positions(text: str):
    positions = []
    heading_re = re.compile(
        r"(?im)^\s*(?:\d+(?:\.\d+)*)?\s*(introduction|related work|background|preliminar(?:y|ies)|method(?:ology)?|approach|experiment(?:s|al setup)?|evaluation|conclusion(?:s)?)\s*$"
    )
    for m in heading_re.finditer(text):
        heading = normalize_heading(m.group(1))
        positions.append((heading, m.start()))
    return sorted(positions, key=lambda x: x[1])


def map_heading_to_section(heading: str) -> str:
    if "introduction" in heading:
        return "introduction"
    if "related work" in heading or "background" in heading or "preliminar" in heading:
        return "related_work"
    if "method" in heading or "approach" in heading:
        return "method"
    if "experiment" in heading or "evaluation" in heading:
        return "experiments"
    if "conclusion" in heading:
        return "conclusion"
    return "other"


def split_sections(text: str):
    positions = find_heading_positions(text)
    if not positions:
        low = text.lower()
        inline_patterns = [
            ("introduction", r"\b(?:\d+\s*[\.\)]\s*)?introduction\b"),
            ("related_work", r"\b(?:\d+\s*[\.\)]\s*)?(?:related work|background|preliminaries)\b"),
            ("method", r"\b(?:\d+\s*[\.\)]\s*)?(?:method|methodology|approach)\b"),
            ("experiments", r"\b(?:\d+\s*[\.\)]\s*)?(?:experiments|experimental setup|evaluation)\b"),
            ("conclusion", r"\b(?:\d+\s*[\.\)]\s*)?conclusions?\b"),
        ]
        inline_hits = []
        for name, pat in inline_patterns:
            m = re.search(pat, low)
            if m:
                inline_hits.append((name, m.start()))
        inline_hits = sorted(inline_hits, key=lambda x: x[1])
        if inline_hits:
            positions = [(name, pos) for name, pos in inline_hits]
        else:
            return {
                "introduction": {"status": "pending", "chars": 0, "text": ""},
                "related_work": {"status": "pending", "chars": 0, "text": ""},
                "method": {"status": "pending", "chars": 0, "text": ""},
                "experiments": {"status": "pending", "chars": 0, "text": ""},
                "conclusion": {"status": "pending", "chars": 0, "text": ""},
            }

    spans = []
    for i, (heading, start) in enumerate(positions):
        end = positions[i + 1][1] if i + 1 < len(positions) else len(text)
        section = map_heading_to_section(heading) if heading in {
            "introduction",
            "related work",
            "background",
            "preliminary",
            "preliminaries",
            "method",
            "methodology",
            "approach",
            "experiments",
            "experimental setup",
            "evaluation",
            "conclusion",
            "conclusions",
        } else heading
        if section == "other":
            continue
        spans.append(SectionSpan(name=section, start=start, end=end))

    merged = {}
    for sp in spans:
        if sp.name not in merged:
            merged[sp.name] = sp
    section_data = {}
    for name in ["introduction", "related_work", "method", "experiments", "conclusion"]:
        if name in merged:
            chunk = text[merged[name].start:merged[name].end].strip()
            section_data[name] = {
                "status": "ready",
                "chars": len(chunk),
                "text": chunk[:20000],
            }
        else:
            section_data[name] = {
                "status": "pending",
                "chars": 0,
                "text": "",
            }
    return section_data


def compress_text(text: str):
    raw = text.encode("utf-8")
    zipped = gzip.compress(raw, compresslevel=9)
    b64 = base64.b64encode(zipped).decode("ascii")
    return {
        "encoding": "gzip+base64",
        "raw_chars": len(text),
        "raw_bytes": len(raw),
        "compressed_bytes": len(zipped),
        "compression_ratio": round(len(zipped) / len(raw), 4) if raw else 0,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "blob": b64,
    }


def load_old_detail(pid: str):
    p = OLD_PAPERS_DIR / f"{pid}.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def safe_local_pdf(pdf_uri: str):
    if not pdf_uri:
        return None
    if pdf_uri.startswith("local://"):
        path = pdf_uri.replace("local://", "", 1)
        return Path(path)
    return None


def migrate():
    NEW_PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    NEW_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    old_index = json.loads(OLD_INDEX.read_text())
    migrated_papers = []

    for item in old_index.get("papers", []):
        pid = item["id"]
        detail = load_old_detail(pid)
        pdf_path = safe_local_pdf(item.get("pdf", ""))

        fulltext = ""
        extraction = {"status": "missing", "engine": "pypdf", "pages": 0, "error": ""}
        sections = {
            "introduction": {"status": "pending", "chars": 0, "text": ""},
            "related_work": {"status": "pending", "chars": 0, "text": ""},
            "method": {"status": "pending", "chars": 0, "text": ""},
            "experiments": {"status": "pending", "chars": 0, "text": ""},
            "conclusion": {"status": "pending", "chars": 0, "text": ""},
        }

        if pdf_path and pdf_path.exists():
            try:
                reader = PdfReader(str(pdf_path))
                extraction["pages"] = len(reader.pages)
                fulltext = clean_text("\n".join((pg.extract_text() or "") for pg in reader.pages))
                extraction["status"] = "ok"
                sections = split_sections(fulltext)
            except Exception as e:
                extraction["status"] = "failed"
                extraction["error"] = str(e)

        if sections["introduction"]["status"] != "ready":
            intro_from_detail = "\n".join([h.get("text", "") for h in detail.get("intro_highlights", [])]).strip()
            if intro_from_detail:
                sections["introduction"] = {
                    "status": "fallback_from_highlights",
                    "chars": len(intro_from_detail),
                    "text": intro_from_detail,
                }

        paper_json = {
            "schema_version": "paper.v1",
            "paper": {
                "id": pid,
                "title": item.get("title", ""),
                "pdf": item.get("pdf", ""),
                "template_id": item.get("template_id", ""),
                "status": item.get("status", "pending"),
                "source": {
                    "batch_from": old_index.get("version", "v0"),
                    "focus": old_index.get("focus", "Introduction"),
                },
            },
            "content": {
                "fulltext": compress_text(fulltext) if fulltext else {
                    "encoding": "gzip+base64",
                    "raw_chars": 0,
                    "raw_bytes": 0,
                    "compressed_bytes": 0,
                    "compression_ratio": 0,
                    "sha256": "",
                    "blob": "",
                },
                "sections": sections,
                "extraction": {
                    **extraction,
                    "updated_at": now_iso(),
                },
            },
            "analysis": {
                "introduction": {
                    "status": "ready" if detail.get("intro_highlights") else "pending",
                    "highlights": detail.get("intro_highlights", []),
                    "template_mapping": detail.get("architecture_mapping", []),
                    "narrative_flow": [
                        "background_and_task_value",
                        "prior_gap_or_failure_mode",
                        "proposed_idea_and_contributions",
                    ],
                },
                "related_work": {"status": "pending", "notes": "reserved for future batches"},
                "method": {"status": "pending", "notes": "reserved for future batches"},
                "experiments": {"status": "pending", "notes": "reserved for future batches"},
                "conclusion": {"status": "pending", "notes": "reserved for future batches"},
            },
            "history": {
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "batch_id": "cvpr2025-local-001",
            },
        }

        out = NEW_PAPERS_DIR / f"{pid}.json"
        out.write_text(json.dumps(paper_json, ensure_ascii=False, separators=(",", ":")))

        migrated_papers.append({
            "id": pid,
            "title": item.get("title", ""),
            "template_id": item.get("template_id", ""),
            "status": item.get("status", "pending"),
            "path": str(out.relative_to(ROOT)),
            "pdf": item.get("pdf", ""),
        })

    for tfile in sorted(OLD_TEMPLATES_DIR.glob("*.json")):
        tpl = json.loads(tfile.read_text())
        tpl.setdefault("schema_version", "template.intro.v1")
        tpl.setdefault("paragraph_roles", [
            "context_and_significance",
            "problem_definition",
            "prior_gap",
            "core_idea",
            "main_results",
            "validation_scope",
            "contribution_summary",
        ])
        (NEW_TEMPLATES_DIR / tfile.name).write_text(json.dumps(tpl, ensure_ascii=False, separators=(",", ":")))

    index_v1 = {
        "schema_version": "index.v1",
        "version": "v1.0.0",
        "updated_at": now_iso(),
        "focus": "Introduction",
        "sections_supported": ["introduction", "related_work", "method", "experiments", "conclusion"],
        "paper_count": len(migrated_papers),
        "template_count": len(old_index.get("templates", [])),
        "paths": {
            "papers_dir": "data/v1/papers",
            "templates_intro_dir": "data/v1/templates/intro",
        },
        "templates": old_index.get("templates", []),
        "papers": migrated_papers,
    }
    (NEW_ROOT / "index.json").write_text(json.dumps(index_v1, ensure_ascii=False, indent=2))

    print(f"migrated papers: {len(migrated_papers)}")


if __name__ == "__main__":
    migrate()
