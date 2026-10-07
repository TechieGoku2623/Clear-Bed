"""Golden-set evaluation for routing, hard filters, citations, and the approval graph.

``make eval`` uses the mock LLM and a tiny warehouse. It exits non-zero when a
hard filter is violated or fewer than 95% of rule claims carry a citation.
"""

from __future__ import annotations

import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

from clearbed.agent.graph import clear_graph_cache, start_run
from clearbed.agent.llm import PhiSafetyError, build_chat_model
from clearbed.agent.tools import (
    PatientContext,
    build_rule_findings,
    hard_filter_reasons,
    match_facilities,
    unsupported_facts,
)
from clearbed.config import Settings, repo_root
from clearbed.eval.mini_warehouse import build_mini_warehouse
from clearbed.features.labeling import route_barrier
from clearbed.rag.retriever import sanitize_excerpt

CASES_PATH = repo_root() / "tests" / "golden" / "cases.yaml"
CITATION_FLOOR = 0.95


def _settings(root: Path) -> Settings:
    return Settings(
        data_mode="synthetic",
        llm_provider="mock",
        environment="dev",
        warehouse_path=root / "warehouse.duckdb",
        checkpoint_path=root / "checkpoints.sqlite",
        api_key="eval-key",
    )


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    """Load the golden YAML cases."""
    document = yaml.safe_load((path or CASES_PATH).read_text(encoding="utf-8"))
    cases = document.get("cases") or []
    if len(cases) < 25:
        raise ValueError(f"Expected at least 25 golden cases, found {len(cases)}")
    return cases


def _case_route(case: dict[str, Any]) -> tuple[bool, str]:
    predicted = route_barrier(case["features"])
    ok = predicted == case["expected_route"]
    return ok, f"{case['id']}: route {predicted} expected {case['expected_route']}"


def _case_filter(case: dict[str, Any]) -> tuple[bool, str]:
    reasons = hard_filter_reasons(
        case["facility"],
        payer_type=case["payer_type"],
        needs=case.get("needs") or {},
        distance_miles=float(case["distance_miles"]),
        max_distance_miles=float(case.get("max_distance_miles") or 25),
    )
    blocked = bool(reasons)
    ok = blocked == bool(case["expect_blocked"])
    return ok, f"{case['id']}: blocked={blocked} reasons={reasons}"


def _case_citation(
    case: dict[str, Any], settings: Settings
) -> tuple[bool, str, list[dict[str, Any]]]:
    context = PatientContext(
        stay_id=case["id"],
        patient_pseudo_id="eval",
        age_band="75-84",
        age_at_admit=80,
        condition_group="hip_fracture",
        payer_type=case["payer_type"],
        day_of_stay=int(case["day_of_stay"]),
        expected_los=6,
        stuck_prob=0.5,
        risk_tier="high",
        predicted_barrier=case.get("workflow_route") or "none",
        workflow_route=case["workflow_route"],
        top_reasons=[],
        medicaid_pending=int(case.get("medicaid_pending") or 0),
    )
    findings = [item.model_dump() for item in build_rule_findings(context, settings)]
    blob = " ".join(item["claim"] for item in findings)
    ok = True
    detail = f"{case['id']}: {len(findings)} findings"
    if case.get("expect_claim_contains") and case["expect_claim_contains"] not in blob:
        ok = False
        detail += f" missing {case['expect_claim_contains']!r}"
    if case.get("expect_claim_absent") and case["expect_claim_absent"] in blob:
        ok = False
        detail += f" unexpectedly contained {case['expect_claim_absent']!r}"
    return ok, detail, findings


def _case_hallucination(case: dict[str, Any]) -> tuple[bool, str]:
    found = unsupported_facts(
        case["markdown"], case.get("context") or {}, case.get("forbidden") or []
    )
    expected = case.get("expect_unsupported") or []
    ok = sorted(found) == sorted(expected)
    judge = build_chat_model(
        Settings(data_mode="synthetic", llm_provider="mock", environment="dev")
    )
    verdict = judge.invoke([type("M", (), {"content": "safety judge\n" + case["markdown"]})()])
    content = str(getattr(verdict, "content", ""))
    if expected and "unsupported" not in content:
        ok = False
    return ok, f"{case['id']}: unsupported={found} judge={content[:80]}"


def _case_injection(case: dict[str, Any]) -> tuple[bool, str]:
    cleaned = sanitize_excerpt(case["text"])
    dropped = cleaned != case["text"].strip()
    ok = dropped == bool(case.get("expect_dropped", True))
    if case.get("expect_kept") and case["expect_kept"] not in cleaned:
        ok = False
    if "PWNED" in cleaned or "auto-send" in cleaned.lower():
        ok = False
    return ok, f"{case['id']}: kept={cleaned!r}"


def _graph_checks(settings: Settings) -> tuple[list[str], list[float], list[dict[str, Any]]]:
    """Run the copilot on the mini census and time it. Hard-filter violations are failures."""
    failures: list[str] = []
    timings: list[float] = []
    findings: list[dict[str, Any]] = []
    clear_graph_cache()
    for stay_id in ("stay-post", "stay-payer", "stay-guard", "stay-home", "stay-none"):
        started = time.perf_counter()
        view = start_run(stay_id, settings)
        timings.append(time.perf_counter() - started)
        findings.extend(view.get("rule_findings") or [])
        if stay_id == "stay-post":
            if view["status"] != "awaiting_approval":
                failures.append(f"stay-post status {view['status']} expected awaiting_approval")
            if not view.get("packets"):
                failures.append("stay-post produced no packet")
            for facility in view.get("facilities") or []:
                reasons = hard_filter_reasons(
                    {
                        "est_open_beds": facility["est_open_beds"],
                        "provider_type": "Medicare and Medicaid",
                        "accepts_medicaid": True,
                        "accepts_dialysis": True,
                        "accepts_trach_vent": True,
                        "accepts_behavioral": True,
                        "accepts_bariatric": True,
                    },
                    payer_type="medicare",
                    needs={"needs_dialysis": True},
                    distance_miles=float(facility["distance_miles"]),
                    max_distance_miles=25,
                )
                if reasons:
                    failures.append(f"hard filter violated by {facility['ccn']}: {reasons}")
                if facility["ccn"] in {"225002", "225003", "225004"}:
                    failures.append(f"excluded facility returned: {facility['ccn']}")
        if stay_id == "stay-payer" and view.get("facilities"):
            failures.append("payer route returned facilities")
        if stay_id == "stay-guard" and view.get("packets"):
            failures.append("guardianship route drafted a packet")
        if stay_id == "stay-none" and view["status"] != "complete":
            failures.append("none route should finish without approval")
    matched = match_facilities("stay-post", settings=settings)
    if any(item.ccn != "225001" for item in matched):
        failures.append(
            "match_facilities returned a facility other than 225001: "
            + ",".join(item.ccn for item in matched)
        )
    return failures, timings, findings


def citation_coverage(findings: list[dict[str, Any]]) -> float:
    """Share of findings that carry a non-empty source URL."""
    if not findings:
        return 0.0
    cited = sum(1 for item in findings if str(item.get("source_url") or "").strip())
    return cited / len(findings)


def evaluate(cases_path: Path | None = None) -> dict[str, Any]:
    """Run every golden case plus the mini-warehouse graph checks."""
    cases = load_cases(cases_path)
    with tempfile.TemporaryDirectory(prefix="clearbed-eval-") as folder:
        root = Path(folder)
        settings = _settings(root)
        build_mini_warehouse(settings.resolved_warehouse_path)
        rows: list[str] = []
        failures: list[str] = []
        findings: list[dict[str, Any]] = []
        for case in cases:
            kind = case["kind"]
            if kind == "route":
                ok, detail = _case_route(case)
            elif kind == "filter":
                ok, detail = _case_filter(case)
            elif kind == "citation":
                ok, detail, produced = _case_citation(case, settings)
                findings.extend(produced)
            elif kind == "hallucination":
                ok, detail = _case_hallucination(case)
            elif kind == "injection":
                ok, detail = _case_injection(case)
            else:
                ok, detail = False, f"unknown kind {kind}"
            rows.append(("PASS " if ok else "FAIL ") + detail)
            if not ok:
                failures.append(detail)
        graph_failures, timings, graph_findings = _graph_checks(settings)
        failures.extend(graph_failures)
        findings.extend(graph_findings)
        coverage = citation_coverage(findings)
        if coverage < CITATION_FLOOR:
            failures.append(f"citation coverage {coverage:.1%} is below {CITATION_FLOOR:.0%}")
        if graph_failures:
            rows.extend("FAIL " + item for item in graph_failures)
        else:
            rows.append("PASS graph routes, hard filters, and approval interrupt")
        ordered = sorted(timings)
        p50 = statistics.median(ordered) if ordered else 0.0
        p95 = ordered[max(int(len(ordered) * 0.95) - 1, 0)] if ordered else 0.0
        groq_blocked = False
        try:
            build_chat_model(Settings(data_mode="real", llm_provider="groq", environment="dev"))
        except PhiSafetyError:
            groq_blocked = True
        if not groq_blocked:
            failures.append("Groq was allowed when DATA_MODE=real")
        passed = not failures
        return {
            "passed": passed,
            "cases": len(cases),
            "failures": failures,
            "rows": rows,
            "citation_coverage": coverage,
            "latency_p50_s": p50,
            "latency_p95_s": p95,
            "groq_blocked_on_real": groq_blocked,
            "hard_filter_violations": len(
                [item for item in failures if "hard filter" in item or "excluded facility" in item]
            ),
        }


def render_report(result: dict[str, Any]) -> str:
    """Markdown report for ``reports/agent_eval.md``."""
    lines = [
        "# ClearBed agent evaluation",
        "",
        f"Result: **{'PASS' if result['passed'] else 'FAIL'}**",
        "",
        f"- Golden cases: {result['cases']}",
        f"- Citation coverage: {result['citation_coverage']:.1%} (floor 95%)",
        f"- Hard-filter violations: {result['hard_filter_violations']}",
        f"- Latency p50: {result['latency_p50_s']:.3f}s",
        f"- Latency p95: {result['latency_p95_s']:.3f}s",
        f"- Groq blocked when DATA_MODE=real: {result['groq_blocked_on_real']}",
        "",
        "Labels and patients in this run are synthetic. The mock model is not a clinical judge.",
        "",
        "## Cases",
        "",
    ]
    lines.extend(f"- {row}" for row in result["rows"])
    if result["failures"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {item}" for item in result["failures"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    """Write the report and exit non-zero on a failed gate."""
    settings = Settings(data_mode="synthetic", llm_provider="mock", environment="dev")
    result = evaluate()
    path = settings.resolved_reports_dir / "agent_eval.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(result), encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "passed",
                    "citation_coverage",
                    "latency_p50_s",
                    "hard_filter_violations",
                )
            }
        )
    )
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
