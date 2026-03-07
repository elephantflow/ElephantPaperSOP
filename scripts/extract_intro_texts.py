#!/usr/bin/env python3
import json
import re
import time
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data/intro/index.json"
# Local-only cache (intentionally excluded from git)
PDF_DIR = ROOT / ".local_cache/pdf"
TEXT_DIR = ROOT / ".local_cache/text"
META_DIR = ROOT / ".local_cache/meta"
MANIFEST = META_DIR / "manifest.json"

TEXT_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)

manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"papers": {}}
index = json.loads(INDEX_PATH.read_text())


def clean_text(t: str) -> str:
    t = t.replace("\xa0", " ")
    t = re.sub(r"-\n", "", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t


def extract_intro(full_text: str) -> str:
    txt = clean_text(full_text)
    low = txt.lower()
    start = None
    for pat in [r"\n\s*1\s+introduction\b", r"\n\s*introduction\b"]:
        m = re.search(pat, low)
        if m:
            start = m.start()
            break
    if start is None:
        return txt[:14000]

    after = low[start + 20:]
    m2 = re.search(r"\n\s*(2|related work|background|method|approach|preliminaries)\b", after)
    end = start + 20 + m2.start() if m2 else min(len(txt), start + 16000)
    return txt[start:end]


for p in index["papers"]:
    pid = p["id"]
    pdf_path = PDF_DIR / f"{pid}.pdf"
    text_path = TEXT_DIR / f"{pid}.txt"

    rec = manifest["papers"].get(pid, {})
    if not pdf_path.exists():
        rec["text_status"] = "missing_pdf"
        manifest["papers"][pid] = rec
        continue

    try:
        reader = PdfReader(str(pdf_path))
        blocks = []
        for page in reader.pages[:10]:
            blocks.append(page.extract_text() or "")
        intro = extract_intro("\n".join(blocks))
        text_path.write_text(intro)

        rec["text_status"] = "ok"
        rec["intro_text"] = str(text_path.relative_to(ROOT))
        rec["intro_chars"] = len(intro)
        rec["text_updated_at"] = int(time.time())
        manifest["papers"][pid] = rec
    except Exception as e:
        rec["text_status"] = "failed"
        rec["text_error"] = str(e)
        rec["text_updated_at"] = int(time.time())
        manifest["papers"][pid] = rec

manifest["updated_at"] = int(time.time())
MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
print("intro text extraction done")
