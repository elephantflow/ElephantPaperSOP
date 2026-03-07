#!/usr/bin/env python3
import json
import re
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
TPL_DIR = ROOT / "data/v1/templates/intro"
INDEX = ROOT / "data/v1/index.json"

BLOCK_PURPOSE = {
    1: "Context and practical motivation",
    2: "Gap or failure diagnosis",
    3: "Problem setup and core claim",
    4: "Method framing and mechanism",
    5: "Evidence and matched-budget comparison",
    6: "Limitation / boundary / failure case",
    7: "Contribution-evidence binding summary",
    8: "Extension and future direction",
}

FORBIDDEN = [
    "state-of-the-art performance",
    "the first work that",
    "robust in all scenarios",
    "consistently superior without exception",
]

ANTI_PATTERNS = [
    {
        "bad": "We achieve SOTA on all benchmarks.",
        "better": "Under matched training/inference budgets, we outperform strong baselines on <metric> over <subset>."
    },
    {
        "bad": "This is the first work to study <task>.",
        "better": "To the best of our knowledge, this is one of the first unified treatments under <assumptions>."
    },
    {
        "bad": "Our method is robust.",
        "better": "We quantify robustness on <stress test> and report failure cases on <hard subset>."
    }
]

DOMAIN_APPEND = {
    "3d_vision": {
        "must": ["failure taxonomy (geometry/occlusion/temporal)", "stage-wise error propagation note"],
        "cost": ["latency", "GPU memory", "FLOPs"],
    },
    "seg_track": {
        "must": ["failure mode breakdown by category", "matched-budget baseline comparison"],
        "cost": ["fps", "latency", "memory"],
    },
    "vlm_multimodal": {
        "must": ["operational definition of A/B tradeoff", "hallucination-related boundary"],
        "cost": ["token cost", "latency", "GPU memory"],
    },
    "benchmark_task": {
        "must": ["data governance (dedup/leakage/license)", "baseline protocol disclosure"],
        "cost": ["annotation cost", "evaluation runtime"],
    },
    "medical_imaging": {
        "must": ["clinical risk boundary", "shift/uncertainty statement"],
        "cost": ["inference latency", "memory", "annotation burden"],
    },
    "efficiency_system": {
        "must": ["condition-result-regime tuple", "theory-practice alignment"],
        "cost": ["compute complexity", "memory", "runtime"],
    },
}


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def placeholders(s: str):
    return re.findall(r"<([^>]+)>", s)


def sanitize_lines(lines):
    out = []
    for line in lines:
        line = line.replace("state-of-the-art performance", "performance stronger than matched strong baselines")
        line = line.replace("first work", "one of the first unified treatments")
        out.append(line)
    return out


def paragraph_cards(full_intro, domain):
    cards = []
    append = DOMAIN_APPEND.get(domain, {"must": [], "cost": ["latency"]})
    for i, para in enumerate(full_intro, start=1):
        slots = placeholders(para)
        cards.append({
            "id": f"P{i}",
            "purpose": BLOCK_PURPOSE.get(i, "Supporting block"),
            "template": para,
            "must_include": [
                "one falsifiable claim",
                "one explicit boundary condition",
                "one evidence pointer (table/theorem/ablation)",
                *append["must"],
            ],
            "forbidden_claims": FORBIDDEN,
            "evidence_hook": "Link this paragraph to a concrete artifact: Table/Figure/Theorem/Ablation.",
            "slot_examples": slots,
            "anti_pattern_examples": ANTI_PATTERNS,
        })
    return cards


def fill_if_empty(arr, fallback):
    return arr if isinstance(arr, list) and arr else fallback


def main():
    files = sorted(TPL_DIR.glob("*.json"))
    for fp in files:
        d = json.loads(fp.read_text())
        domain = d.get("domain", "efficiency_system")
        full_intro = sanitize_lines(d.get("full_intro_template", []))

        d["schema_version"] = "template.intro.v3"
        d["updated_at"] = now_iso()
        d["reorderable"] = True
        d["core_blocks"] = d.get("core_blocks") or ["context", "gap", "idea", "evidence", "contribution"]
        d["optional_blocks"] = d.get("optional_blocks") or ["limitation_hint", "resource_cost_disclosure", "failure_taxonomy"]
        d["full_intro_template"] = full_intro

        d["abstract_template"] = fill_if_empty(
            d.get("abstract_template"),
            [
                "A1: Define task and deployment setting with one measurable constraint.",
                "A2: State precise gap and why prior work fails in that regime.",
                "A3: Present method/protocol and strongest baseline delta under matched budget.",
                "A4: Add uncertainty (mean±std/significance) and one limitation boundary.",
            ],
        )
        d["method_template"] = fill_if_empty(
            d.get("method_template"),
            [
                "M1: Define input-output contract and module decomposition.",
                "M2: Explain core mechanism and expected causal effect on target metric.",
                "M3: Provide complexity/memory/runtime cost against strongest baseline.",
            ],
        )
        d["experiments_template"] = fill_if_empty(
            d.get("experiments_template"),
            [
                "E1: Report matched-budget baselines and protocol details (seeds, scripts, hardware).",
                "E2: Report mean±std or confidence intervals and significance where applicable.",
                "E3: Provide failure taxonomy and at least one counter-example scenario.",
            ],
        )

        d["paragraph_cards"] = paragraph_cards(full_intro, domain)
        d["statistical_reliability_requirements"] = [
            "Report mean±std over >=3 random seeds when stochastic training is used.",
            "State whether significance testing was performed and which test was used.",
        ]
        d["cost_disclosure_requirements"] = [
            f"Report at least one cost metric from: {', '.join(DOMAIN_APPEND.get(domain, {'cost':['latency']})['cost'])}.",
            "Compare cost under matched hardware/batch settings.",
        ]
        d["reorder_profiles"] = [
            {
                "id": "standard",
                "description": "context -> gap -> idea -> evidence -> limitation -> contributions",
                "blocks": ["context", "gap", "idea", "evidence", "limitation_hint", "contribution"],
            },
            {
                "id": "evidence_first",
                "description": "context -> evidence -> gap -> idea -> limitation -> contributions",
                "blocks": ["context", "evidence", "gap", "idea", "limitation_hint", "contribution"],
            },
            {
                "id": "benchmark_first",
                "description": "context -> protocol -> gap -> idea -> evidence -> contributions",
                "blocks": ["context", "resource_cost_disclosure", "gap", "idea", "evidence", "contribution"],
            },
        ]

        d["falsifiable_claims"] = [
            "If <core module> is removed, performance on <hard subset> should decrease by >= <delta>.",
            "Under matched training/inference budget, <our method> should outperform <strong baseline> on <metric>.",
        ]
        d["delta_vs_strongest_baseline"] = "Compared with <strong baseline>, we add <mechanism> and obtain <delta> under matched budget and protocol."
        d["limitations_or_failure_cases"] = "We explicitly analyze failure cases under <scenario> and report why the method is not dominant there."
        d["contribution_schema"] = [
            "Contribution: <type=theory|method|benchmark|analysis|system> | Evidence: <Theorem/Table/Ablation/Open-source>",
            "Contribution: <type> | Evidence: <verifiable artifact> | Risk/Boundary: <where it may fail>",
        ]

        fp.write_text(json.dumps(d, ensure_ascii=False, indent=2))

    idx = json.loads(INDEX.read_text())
    idx["version"] = "v1.3.0"
    idx["focus"] = "multi-section+reviewer-guided+template-v3"
    idx["updated_at"] = now_iso()
    INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=2))
    print(f"upgraded templates: {len(files)}")


if __name__ == "__main__":
    main()
