#!/usr/bin/env python3
import json
import hashlib
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data/intro/index.json"
# Local-only cache (intentionally excluded from git)
PDF_DIR = ROOT / ".local_cache/pdf"
META_DIR = ROOT / ".local_cache/meta"
MANIFEST = META_DIR / "manifest.json"

PDF_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)
manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"updated_at": None, "papers": {}}
index = json.loads(INDEX_PATH.read_text())

for p in index["papers"]:
    pid = p["id"]
    url = p.get("pdf")
    if not url:
        continue
    target = PDF_DIR / f"{pid}.pdf"
    rec = manifest["papers"].get(pid, {})
    if target.exists() and target.stat().st_size > 100000 and rec.get("status") == "ok":
        continue
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=25) as r:
            data = r.read()
        target.write_bytes(data)
        manifest["papers"][pid] = {
            "status": "ok",
            "pdf": str(target.relative_to(ROOT)),
            "pdf_url": url,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "fetched_at": int(time.time())
        }
    except Exception as e:
        manifest["papers"][pid] = {
            "status": "failed",
            "pdf_url": url,
            "error": str(e),
            "fetched_at": int(time.time())
        }

manifest["updated_at"] = int(time.time())
MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
print("manifest updated")
