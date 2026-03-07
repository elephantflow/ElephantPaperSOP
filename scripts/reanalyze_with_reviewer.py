#!/usr/bin/env python3
import base64
import gzip
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data/v1/index.json"
PAPERS_DIR = ROOT / "data/v1/papers"
TPL_DIR = ROOT / "data/v1/templates/intro"

SECTION_ORDER = ["introduction", "related_work", "method", "experiments", "conclusion"]

DOMAIN_RULES = {
    "3d_vision": ["3d", "gaussian", "splat", "nerf", "mesh", "point cloud", "occupancy", "slam", "reconstruction"],
    "seg_track": ["segmentation", "tracking", "detection", "instance", "object", "optical flow"],
    "vlm_multimodal": ["multimodal", "vision-language", "llm", "vqa", "grounding", "retrieval", "caption"],
    "benchmark_task": ["benchmark", "dataset", "task", "protocol", "evaluation", "curate"],
    "medical_imaging": ["medical", "pathology", "histology", "clinical", "tumor", "biopsy"],
    "efficiency_system": ["efficient", "fast", "mobile", "latency", "memory", "compression", "real-time"],
}

STRATEGY_RULES = {
    "theory_formalization": ["theorem", "formal", "bound", "optimal", "proof", "assumption"],
    "tradeoff_bridge": ["trade-off", "tradeoff", "balance", "while", "without sacrificing", "jointly"],
    "pipeline_reframing": ["two-stage", "pipeline", "decompose", "stage", "module", "diagnosis"],
    "task_benchmark_definition": ["we define", "new task", "benchmark", "dataset", "protocol"],
    "efficiency_first": ["efficient", "lightweight", "fast", "speed", "memory"],
}

REWRITE_HINT = {
    "introduction": "该句适合放在引言核心论证位，可用于‘背景-缺口-方法’叙事衔接。",
    "method": "该句适合放在方法总览或模块说明段，便于交代机制与作用链路。",
    "experiments": "该句适合放在实验主结果段，强调设置、对比对象与可验证增益。",
    "conclusion": "该句适合放在结论段，概括贡献边界并引出后续工作。",
}

PATTERN_POOL = {
    "introduction": [
        "Despite progress in <field>, <problem> remains unresolved under <hard condition>, motivating <our idea>.",
        "Prior methods rely on <assumption>, but fail when <failure mode>; we therefore introduce <method>.",
    ],
    "method": [
        "Our framework contains <module A>, <module B>, and <module C>, where <core module> explicitly models <relation>.",
        "We reformulate <original problem> into <new view>, enabling <benefit> while keeping <constraint> manageable.",
    ],
    "experiments": [
        "Under matched training/inference budgets, our approach improves <metric> by <margin> over <strong baseline>.",
        "Ablation shows removing <component> causes <drop>, confirming its role in <target behavior>.",
    ],
    "conclusion": [
        "We show <method> improves <target> under <setting>, while failure analysis highlights limits on <scenario>.",
        "Future work should relax <assumption> and extend to <new regime>.",
    ],
}

TEMPLATES = [
    {
        "id": "TPL-3D-A",
        "name": "3D Vision · Decomposition Variant",
        "domain": "3d_vision",
        "variant": "A",
        "narrative_strategy": "pipeline_reframing",
        "best_for": ["3D reconstruction", "3D generation", "Gaussian Splatting"],
        "full_intro_template": [
            "P1 Context: <3D task> is critical for <application>, but real scenes contain <occlusion / pose variation / sparse views>.",
            "P2 Failure diagnosis: Existing <global or monolithic> methods accumulate errors because <coupled subproblem> is solved at once.",
            "P3 Reframing: We decompose the problem into <stage-1> and <stage-2>, reducing global ambiguity into local verifiable steps.",
            "P4 Method core: Our design introduces <module> to model <geometry/consistency>, and <refinement module> to correct residual mismatch.",
            "P5 Evidence promise: Under matched budgets, we target gains on <metric1/metric2> and analyze per-stage error propagation.",
            "P6 Limitation hint: We also report failure cases under <extreme sparsity / topology change>.",
            "P7 Contributions: (i) decomposition, (ii) mechanism, (iii) empirical validation with ablation and diagnostics."
        ],
        "abstract_template": [
            "A1: State 3D problem and deployment constraint.",
            "A2: Identify one precise bottleneck and why prior work fails.",
            "A3: Introduce decomposition and key mechanism.",
            "A4: Report matched-budget improvement and one limitation boundary."
        ],
        "method_template": [
            "M1: Define each stage input/output and invariants.",
            "M2: Explain core module and why it reduces ambiguity.",
            "M3: Provide complexity and memory cost delta."
        ],
        "experiments_template": [
            "E1: Report strong baselines under matched budgets.",
            "E2: Include stage-wise error propagation analysis.",
            "E3: Include failure taxonomy and representative counter-example."
        ],
    },
    {
        "id": "TPL-3D-B",
        "name": "3D Vision · Efficiency-Accuracy Variant",
        "domain": "3d_vision",
        "variant": "B",
        "narrative_strategy": "tradeoff_bridge",
        "best_for": ["real-time 3D", "mobile or low-memory setting"],
        "full_intro_template": [
            "P1 Context: <task> must satisfy both <quality objective> and <runtime/memory objective> in <deployment>.",
            "P2 Operational tradeoff: We define A=<quality metric> and B=<resource metric>, and require joint reporting on the same benchmark.",
            "P3 Gap: Prior methods improve A by increasing B, or reduce B with significant A degradation.",
            "P4 Bridge idea: We propose <framework> to preserve <critical representation> while controlling <compute path>.",
            "P5 Verifiable claim: Under <dataset/regime>, A improves by <margin> while B drops by <margin> against strongest baseline.",
            "P6 Robustness note: We report variance (mean±std) and unstable cases under <hard subset>.",
            "P7 Contributions with evidence binding."
        ],
        "abstract_template": [
            "A1: Define A/B metrics explicitly.",
            "A2: Present bridge mechanism.",
            "A3: Give A and B deltas vs strongest baseline.",
            "A4: Add confidence interval and limitation."
        ],
    },
    {
        "id": "TPL-SEG-A",
        "name": "Segmentation/Tracking · Failure-Taxonomy Variant",
        "domain": "seg_track",
        "variant": "A",
        "narrative_strategy": "pipeline_reframing",
        "best_for": ["segmentation", "tracking", "detection"],
        "full_intro_template": [
            "P1 Task value and realistic disturbances.",
            "P2 Failure taxonomy: <geometry ambiguity>, <long-tail occlusion>, <temporal inconsistency>.",
            "P3 Why current pipelines fail per failure mode.",
            "P4 Our pipeline and module assignment per failure mode.",
            "P5 Delta against strongest baseline under matched budget.",
            "P6 Failure-case analysis and boundary conditions.",
            "P7 Contribution-evidence list."
        ],
    },
    {
        "id": "TPL-SEG-B",
        "name": "Segmentation/Tracking · End-to-End Variant",
        "domain": "seg_track",
        "variant": "B",
        "narrative_strategy": "efficiency_first",
        "best_for": ["end-to-end perception systems"],
        "full_intro_template": [
            "P1 Introduce end-to-end requirement in production pipeline.",
            "P2 Explain why multi-stage heuristics hurt stability/latency.",
            "P3 Present unified model with explicit failure monitoring head.",
            "P4 Show computational profile and convergence behavior.",
            "P5 Report matched-budget gains and seed variance.",
            "P6 Discuss non-dominant scenarios where decomposition may still win.",
            "P7 Evidence-bound contributions."
        ],
    },
    {
        "id": "TPL-VLM-A",
        "name": "VLM/MMLM · Tradeoff-Grounded Variant",
        "domain": "vlm_multimodal",
        "variant": "A",
        "narrative_strategy": "tradeoff_bridge",
        "best_for": ["multimodal grounding", "retrieval", "reasoning"],
        "full_intro_template": [
            "P1 Context: strong capability but unstable grounding.",
            "P2 Define tradeoff metrics A/B (e.g., grounding F1 vs hallucination rate).",
            "P3 Diagnose why prior alignment objectives cannot optimize A and B jointly.",
            "P4 Introduce <training-free/fine-tuned/hybrid> bridge framework.",
            "P5 Provide operational delta vs strongest baseline with matched token budget.",
            "P6 Include failure cases under long-context / multi-hop settings.",
            "P7 Contributions with evidence hooks."
        ],
    },
    {
        "id": "TPL-VLM-B",
        "name": "VLM/MMLM · Benchmark-Protocol Variant",
        "domain": "vlm_multimodal",
        "variant": "B",
        "narrative_strategy": "task_benchmark_definition",
        "best_for": ["new multimodal tasks and benchmarks"],
        "full_intro_template": [
            "P1 Motivation from concrete failure cases and user-side need.",
            "P2 Task definition with formal input-output contract.",
            "P3 Dataset curation and split-leakage checks.",
            "P4 Baseline protocol disclosure (budget, seeds, script version).",
            "P5 Findings and gaps for future methods.",
            "P6 Longevity design: versioning and extension plan."
        ],
    },
    {
        "id": "TPL-BENCH-A",
        "name": "Task/Benchmark · Data-Governance Variant",
        "domain": "benchmark_task",
        "variant": "A",
        "narrative_strategy": "task_benchmark_definition",
        "best_for": ["new task", "new benchmark", "dataset papers"],
        "full_intro_template": [
            "P1 User-side pain point with measurable evidence.",
            "P2 Task and evaluation target formalization.",
            "P3 Data governance: dedup, license, leakage, ethics.",
            "P4 Baseline protocol and reproducibility checklist.",
            "P5 Benchmark findings and strongest baseline gap.",
            "P6 Future benchmark longevity strategy."
        ],
    },
    {
        "id": "TPL-BENCH-B",
        "name": "Task/Benchmark · Protocol-Driven Variant",
        "domain": "benchmark_task",
        "variant": "B",
        "narrative_strategy": "theory_formalization",
        "best_for": ["evaluation protocol design"],
        "full_intro_template": [
            "P1 Explain why existing proxy metrics are insufficient.",
            "P2 Define protocol objectives and falsifiable criteria.",
            "P3 Construct benchmark with stress-test subsets.",
            "P4 Report baseline variance and confidence intervals.",
            "P5 Discuss protocol limitations and extension points."
        ],
    },
    {
        "id": "TPL-MED-A",
        "name": "Medical CV · Evidence-Risk Balanced Variant",
        "domain": "medical_imaging",
        "variant": "A",
        "narrative_strategy": "tradeoff_bridge",
        "best_for": ["pathology", "medical segmentation/classification"],
        "full_intro_template": [
            "P1 Clinical significance and deployment risk.",
            "P2 Data heterogeneity and domain-shift challenge.",
            "P3 Method that balances predictive gain and reliability evidence.",
            "P4 Report matched-budget gains with uncertainty estimates.",
            "P5 Explicit failure cases and clinical non-applicability boundaries.",
            "P6 Contribution-evidence list with reproducibility constraints."
        ],
    },
    {
        "id": "TPL-TH-A",
        "name": "Theory/Optimization · Condition-Result-Regime Variant",
        "domain": "efficiency_system",
        "variant": "A",
        "narrative_strategy": "theory_formalization",
        "best_for": ["theory-backed system design", "efficiency analysis"],
        "full_intro_template": [
            "P1 Problem setup with concrete operational constraints.",
            "P2 Formalization and assumptions A1-A3.",
            "P3 Main result in condition-result-regime form.",
            "P4 Delta vs strongest baseline and complexity disclosure.",
            "P5 Theory-to-practice alignment and lower-bound/barrier note.",
            "P6 Limitation and failure-case commitment."
        ],
    },
]


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def decompress_blob(blob: str) -> str:
    raw = gzip.decompress(base64.b64decode(blob.encode("ascii")))
    return raw.decode("utf-8", "ignore")


def compress_text(text: str):
    raw = text.encode("utf-8", "ignore")
    gz = gzip.compress(raw, compresslevel=9)
    return {
        "encoding": "gzip+base64",
        "raw_chars": len(text),
        "raw_bytes": len(raw),
        "compressed_bytes": len(gz),
        "compression_ratio": round((len(gz) / len(raw)), 4) if raw else 0,
        "sha256": __import__("hashlib").sha256(raw).hexdigest(),
        "blob": base64.b64encode(gz).decode("ascii"),
    }


def clean_text(t: str) -> str:
    t = t.replace("\xa0", " ").replace("\u00ad", "")
    t = re.sub(r"-\n", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = t.encode("utf-8", "ignore").decode("utf-8", "ignore")
    return t.strip()


def parse_pdf(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return clean_text("\n".join((pg.extract_text() or "") for pg in reader.pages))


def find_sections(text: str):
    low = text.lower()
    hits = []
    inline_patterns = [
        ("introduction", r"\b1\s*[\.)]?\s*introduction\b"),
        ("related_work", r"\b2\s*[\.)]?\s*(?:related work|background|preliminaries)\b"),
        ("method", r"\b(?:2|3)\s*[\.)]?\s*(?:method|methodology|approach)\b"),
        ("experiments", r"\b(?:3|4|5)\s*[\.)]?\s*(?:experiments|evaluation|experimental setup)\b"),
        ("conclusion", r"\b(?:5|6|7)\s*[\.)]?\s*conclusions?\b"),
    ]
    for sec, pat in inline_patterns:
        for m in re.finditer(pat, low):
            hits.append((sec, m.start()))

    # Fallback to line-based headings if inline numbering is absent
    if not hits:
        heading_patterns = [
            ("introduction", r"(?im)^\s*(?:\d+(?:\.\d+)*)?\s*introduction\s*$"),
            ("related_work", r"(?im)^\s*(?:\d+(?:\.\d+)*)?\s*(related work|background|preliminaries)\s*$"),
            ("method", r"(?im)^\s*(?:\d+(?:\.\d+)*)?\s*(method|methodology|approach)\s*$"),
            ("experiments", r"(?im)^\s*(?:\d+(?:\.\d+)*)?\s*(experiments|evaluation|experimental setup)\s*$"),
            ("conclusion", r"(?im)^\s*(?:\d+(?:\.\d+)*)?\s*conclusions?\s*$"),
        ]
        for sec, pat in heading_patterns:
            for m in re.finditer(pat, text):
                hits.append((sec, m.start()))

    hits = sorted(hits, key=lambda x: x[1])
    sections = {k: {"status": "pending", "chars": 0, "text": ""} for k in SECTION_ORDER}
    if not hits:
        chunk = text[:12000]
        sections["introduction"] = {"status": "fallback", "chars": len(chunk), "text": chunk}
        return sections

    # Keep first valid occurrence in canonical progression order
    compact = []
    last_pos = -1
    for sec in SECTION_ORDER:
        cand = [p for s, p in hits if s == sec and p > last_pos]
        if cand:
            pos = min(cand)
            compact.append((sec, pos))
            last_pos = pos

    for i, (sec, start) in enumerate(compact):
        end = compact[i + 1][1] if i + 1 < len(compact) else len(text)
        chunk = text[start:end].strip()
        chunk = re.split(r"(?im)^\s*references\s*$", chunk)[0].strip()
        if len(chunk) < 120:
            continue
        sections[sec] = {"status": "ready", "chars": len(chunk), "text": chunk[:22000]}

    if sections["introduction"]["status"] == "pending":
        chunk = text[:12000]
        sections["introduction"] = {"status": "fallback", "chars": len(chunk), "text": chunk}

    return sections


def split_sentences(txt: str):
    txt = re.sub(r"\s+", " ", txt)
    sents = re.split(r"(?<=[\.!?])\s+(?=[A-Z0-9])", txt)
    out = []
    for s in sents:
        s = s.strip()
        if len(s) < 95 or len(s) > 380:
            continue
        if s.lower().startswith(("figure", "table", "copyright", "arxiv", "http")):
            continue
        if " et al" in s and len(s.split()) < 12:
            continue
        alpha = sum(ch.isalpha() for ch in s)
        digit = sum(ch.isdigit() for ch in s)
        if alpha < 40 or (digit > 0 and digit / max(len(s), 1) > 0.18):
            continue
        if any(tok in s.lower() for tok in ["equation", "algorithm", "appendix", "acknowledgement"]):
            continue
        out.append(s)
    return out


def pick_highlights(section: str, text: str, k: int):
    sents = split_sentences(text)
    cues = {
        "introduction": ["however", "challenge", "existing", "we propose", "in this paper", "motivated"],
        "method": ["we propose", "module", "architecture", "framework", "optimize", "objective"],
        "experiments": ["benchmark", "outperform", "ablation", "results", "improves", "matched"],
        "conclusion": ["in conclusion", "we show", "future work", "limitation", "boundary"],
    }.get(section, [])

    def score(s: str):
        low = s.lower()
        return sum(2 for c in cues if c in low) + min(len(s), 260) / 260

    ranked = sorted(sents, key=score, reverse=True)
    res = []
    used = set()
    patterns = PATTERN_POOL.get(section, ["<pattern>"])
    for s in ranked:
        norm = re.sub(r"[^a-z0-9]+", "", s.lower())[:60]
        if norm in used:
            continue
        used.add(norm)
        res.append(
            {
                "text": s,
                "rewrite_zh": REWRITE_HINT.get(section, "该句可复用。"),
                "reusable_pattern": patterns[len(res) % len(patterns)],
            }
        )
        if len(res) >= k:
            break
    return res


def classify_domain(title: str, intro: str):
    text = (title + " " + intro[:2400]).lower()
    scores = {d: 0 for d in DOMAIN_RULES}
    for d, kws in DOMAIN_RULES.items():
        for kw in kws:
            if kw in text:
                scores[d] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "efficiency_system"


def classify_strategy(title: str, intro: str):
    text = (title + " " + intro[:3200]).lower()
    scores = {s: 0 for s in STRATEGY_RULES}
    for s, kws in STRATEGY_RULES.items():
        for kw in kws:
            if kw in text:
                scores[s] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "pipeline_reframing"


def templates_for(domain: str, strategy: str):
    exact = [t["id"] for t in TEMPLATES if t["domain"] == domain and t["narrative_strategy"] == strategy]
    domain_pool = [t["id"] for t in TEMPLATES if t["domain"] == domain]
    if exact:
        primary = exact[0]
        candidates = [primary] + [x for x in domain_pool if x != primary]
    elif domain_pool:
        primary = domain_pool[0]
        candidates = domain_pool[:]
    else:
        primary = "TPL-TH-A"
        candidates = ["TPL-TH-A"]
    if len(candidates) == 1:
        alt = [t["id"] for t in TEMPLATES if t["id"] != primary][:2]
        candidates.extend(alt)
    return primary, candidates[:3]


def role_mapping(intro_text: str):
    sents = split_sentences(intro_text)
    if not sents:
        return []

    def pick(predicate, fallback_idx):
        for s in sents:
            if predicate(s.lower()):
                return s[:220]
        return sents[min(fallback_idx, len(sents) - 1)][:220]

    return [
        {"template_paragraph": "P1 背景与任务价值", "paper_evidence": pick(lambda x: "task" in x or "application" in x or "important" in x, 0)},
        {"template_paragraph": "P2 现有方法缺口", "paper_evidence": pick(lambda x: "however" in x or "limited" in x or "challenge" in x, 1)},
        {"template_paragraph": "P3 方法主线", "paper_evidence": pick(lambda x: "we propose" in x or "our" in x, 2)},
        {"template_paragraph": "P4 可证伪承诺", "paper_evidence": "Claim is falsifiable via matched-budget comparison and ablation sensitivity."},
        {"template_paragraph": "P5 失败案例边界", "paper_evidence": "Boundary conditions should be tested on hard subsets and failure taxonomy."},
    ]


def narrative_flow(intro_text: str):
    low = intro_text.lower()
    flow = ["context"]
    if any(k in low for k in ["however", "challenge", "limited"]):
        flow.append("gap")
    if any(k in low for k in ["we propose", "our method", "framework"]):
        flow.append("method")
    if any(k in low for k in ["experiment", "benchmark", "outperform"]):
        flow.append("evidence")
    flow.append("limitations")
    return flow


def write_templates():
    TPL_DIR.mkdir(parents=True, exist_ok=True)
    ids = []
    for t in TEMPLATES:
        body = {
            "schema_version": "template.intro.v2",
            "id": t["id"],
            "name": t["name"],
            "domain": t["domain"],
            "variant": t["variant"],
            "narrative_strategy": t["narrative_strategy"],
            "best_for": t.get("best_for", []),
            "reorderable": True,
            "core_blocks": ["context", "gap", "idea", "evidence", "contribution"],
            "optional_blocks": ["theory_practice_alignment", "failure_taxonomy", "limitation_hint", "resource_cost_disclosure"],
            "full_intro_template": t["full_intro_template"],
            "abstract_template": t.get("abstract_template", []),
            "method_template": t.get("method_template", []),
            "experiments_template": t.get("experiments_template", []),
            "falsifiable_claims": [
                "If <core mechanism> is removed, performance on <hard subset> should drop by at least <delta>.",
                "Under matched compute budget, <our method> should outperform <strong baseline> on <metric>."
            ],
            "delta_vs_strongest_baseline": "Compared with <strong baseline>, we add <new mechanism> and gain <delta> under matched budget.",
            "limitations_or_failure_cases": "We analyze failure cases under <scenario> and discuss why the method is not dominant there.",
            "contribution_schema": [
                "Contribution: <type=theory|method|benchmark|analysis|system> | Evidence: <Theorem/Table/Ablation/Open-source>",
                "Contribution: <type> | Evidence: <verifiable artifact>"
            ],
            "failure_modes": ["geometry ambiguity", "long-tail occlusion", "temporal inconsistency", "domain shift"],
            "operational_definition": {
                "A": "primary quality metric on benchmark",
                "B": "resource or reliability metric reported jointly"
            },
            "phrase_alternatives": {
                "However": ["Nevertheless", "Yet", "Despite these advances"],
                "We propose": ["We introduce", "We present", "We develop"],
                "In summary": ["Overall", "Taken together", "In closing"]
            },
            "updated_at": now_iso(),
        }
        (TPL_DIR / f"{t['id']}.json").write_text(json.dumps(body, ensure_ascii=False, indent=2))
        ids.append(t["id"])

    return ids


def update_paper_record(meta):
    path = ROOT / meta["path"]
    rec = json.loads(path.read_text())

    title = rec.get("paper", {}).get("title", meta["title"])
    full = ""
    if rec.get("content", {}).get("fulltext", {}).get("blob"):
        try:
            full = decompress_blob(rec["content"]["fulltext"]["blob"])
        except Exception:
            full = ""

    if not full:
        pdf_uri = rec.get("paper", {}).get("pdf") or meta.get("pdf", "")
        pdf_path = Path(str(pdf_uri).replace("local://", ""))
        if pdf_path.exists():
            full = parse_pdf(pdf_path)
        else:
            full = rec.get("content", {}).get("sections", {}).get("introduction", {}).get("text", "")

    full = clean_text(full)
    sections = find_sections(full)

    domain = classify_domain(title, sections["introduction"]["text"])
    strategy = classify_strategy(title, sections["introduction"]["text"])
    primary, candidates = templates_for(domain, strategy)

    intro_h = pick_highlights("introduction", sections["introduction"]["text"], 4)
    method_h = pick_highlights("method", sections["method"]["text"], 3) if sections["method"]["status"] != "pending" else []
    exp_h = pick_highlights("experiments", sections["experiments"]["text"], 3) if sections["experiments"]["status"] != "pending" else []
    conc_h = pick_highlights("conclusion", sections["conclusion"]["text"], 2) if sections["conclusion"]["status"] != "pending" else []

    rec["paper"]["template_id"] = primary
    rec["paper"]["template_candidates"] = candidates
    rec["paper"]["domain"] = domain
    rec["paper"]["narrative_strategy"] = strategy

    rec.setdefault("content", {})["fulltext"] = compress_text(full)
    rec["content"]["sections"] = sections
    rec["content"].setdefault("extraction", {})["updated_at"] = now_iso()
    rec["content"]["extraction"].setdefault("status", "ok")

    rec.setdefault("analysis", {})
    rec["analysis"]["introduction"] = {
        "status": "ready",
        "highlights": intro_h,
        "template_mapping": role_mapping(sections["introduction"]["text"]),
        "narrative_flow": narrative_flow(sections["introduction"]["text"]),
        "falsifiable_claims": [
            "Matched-budget comparison must show gain on at least one primary metric.",
            "Removing key module should degrade hard-subset performance."
        ],
        "delta_vs_strongest_baseline": "Specify strongest baseline and exact mechanism-level delta.",
        "limitations_or_failure_cases": "Report at least one failure taxonomy category where method underperforms.",
    }
    rec["analysis"]["method"] = {
        "status": "ready" if method_h else "pending",
        "highlights": method_h,
        "template_mapping": [],
    }
    rec["analysis"]["experiments"] = {
        "status": "ready" if exp_h else "pending",
        "highlights": exp_h,
        "template_mapping": [],
    }
    rec["analysis"]["conclusion"] = {
        "status": "ready" if conc_h else "pending",
        "highlights": conc_h,
        "template_mapping": [],
    }
    rec["analysis"]["related_work"] = rec["analysis"].get("related_work", {"status": "pending", "highlights": [], "template_mapping": []})

    rec.setdefault("history", {})["updated_at"] = now_iso()
    rec["history"]["batch_id"] = "cvpr2025-local-050-reviewer-v2"

    path.write_text(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
    return {
        "id": rec["paper"]["id"],
        "title": rec["paper"]["title"],
        "template_id": primary,
        "template_candidates": candidates,
        "status": rec["paper"].get("status", "ready"),
        "path": str(path.relative_to(ROOT)),
        "pdf": rec["paper"].get("pdf", ""),
        "domain": domain,
        "narrative_strategy": strategy,
    }


def main():
    idx = json.loads(INDEX_PATH.read_text())
    template_ids = write_templates()

    updated = []
    domain_counter = Counter()
    strategy_counter = Counter()
    for meta in idx.get("papers", []):
        out = update_paper_record(meta)
        updated.append(out)
        domain_counter[out["domain"]] += 1
        strategy_counter[out["narrative_strategy"]] += 1

    new_index = {
        "schema_version": "index.v1",
        "version": "v1.2.0",
        "updated_at": now_iso(),
        "focus": "multi-section+reviewer-guided",
        "sections_supported": SECTION_ORDER,
        "paper_count": len(updated),
        "template_count": len(template_ids),
        "paths": {
            "papers_dir": "data/v1/papers",
            "templates_intro_dir": "data/v1/templates/intro"
        },
        "templates": template_ids,
        "papers": updated,
        "stats": {
            "domain_distribution": dict(domain_counter),
            "strategy_distribution": dict(strategy_counter)
        }
    }
    INDEX_PATH.write_text(json.dumps(new_index, ensure_ascii=False, indent=2))

    report = {
        "updated_at": now_iso(),
        "paper_count": len(updated),
        "template_count": len(template_ids),
        "domain_distribution": dict(domain_counter),
        "strategy_distribution": dict(strategy_counter),
    }
    out = ROOT / "data/v1/template-summary.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"updated papers: {len(updated)}")
    print(f"templates: {len(template_ids)}")


if __name__ == "__main__":
    main()
