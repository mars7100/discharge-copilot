"""Validated events -> cited discharge-summary Draft, one LLM call per template section (spec §7.3, §7.4)."""
from typing import Literal

from pydantic import BaseModel, create_model

from core import llm
from core.models import TEMPLATE, ClinicalEvent, Draft, Resolution, SourceSpan, SummaryClaim

SYSTEM = """You draft a discharge summary for a synthetic hospitalization from extracted, documented events.
- Use only the supplied events. No general medical knowledge, no rationale or detail the events do not state.
- One documented fact per claim, one or two short sentences. Hospital course claims in chronological order.
- evidence_span_ids: copy span IDs exactly from the evidence of the events the claim is based on.
- You draft one section only. Include only the facts that belong in it; if the events state nothing for it, set documented to false and return no claims.
- Resolved facts (lines starting with a D ID) are clinician-provided: state each as written, cite its spans, and put its ID in clinician_clarification_ids. Never mention the superseded values as unresolved.
- claim_id any placeholder; clinician_clarification_ids empty except for resolved facts; support_status "unverified"."""
TIMEOUT = 35


class SectionResult(BaseModel):
    documented: bool
    claims: list[SummaryClaim]


class SummaryError(Exception):
    pass


def check_claims(claims: list[SummaryClaim], spans: dict[str, SourceSpan]) -> tuple[list[SummaryClaim], list[str]]:
    """Keep only cited span IDs that exist; drop claims left with none."""
    valid, errors = [], []
    for c in claims:
        ids = [s for s in c.evidence_span_ids if s in spans]
        errors += [f"{c.claim_id}: unknown span_id {s}" for s in c.evidence_span_ids if s not in spans]
        if ids:
            valid.append(c.model_copy(update={"evidence_span_ids": ids}))
        else:
            errors.append(f"{c.claim_id}: no valid evidence, claim excluded")
    return valid, errors


def draft_section(section_id: str, events: list[ClinicalEvent], spans: dict[str, SourceSpan],
                  resolutions: list[Resolution] = (), problem: str | None = None) -> dict:
    """One section's (hospital_course: one problem's) {documented, claims (placeholder IDs), warnings}. Retries once on errors or exceptions."""
    purpose = next(s["purpose"] for s in TEMPLATE if s["section_id"] == section_id)
    lines = [f"{e.event_id} | {e.date_or_hospital_day} | {e.category} | {e.statement} | "
             f"spans: {', '.join(r.span_id for r in e.evidence)}" for e in events]
    lines += [f"{r.conflict_id} | RESOLVED (clinician-provided) | {r.text} | spans: {', '.join(q.span_id for q in r.quotes)}"
              for r in resolutions]
    scope = (f"Problem: {problem}\nClaims cover only this problem and only events that changed the course of the stay, in chronological order.\n"
             if problem else "")
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Section: {section_id} ({purpose}). Every claim's section is {section_id}.\n{scope}"
                                            "Events:\n" + "\n".join(lines)}]
    known = {r.conflict_id for r in resolutions}
    result, claims, errors = None, [], []
    for attempt in range(2):
        try:
            result = llm.parse(SectionResult, messages, TIMEOUT)
        except Exception as e:
            if not attempt:
                continue
            raise SummaryError(f"{section_id}: LLM call failed: {e}") from e
        if not result.documented:
            return {"documented": False, "claims": [], "warnings": []}
        claims, errors = check_claims(result.claims, spans)
        errors += [f"{c.claim_id}: section {c.section}, expected {section_id}, claim excluded" for c in claims if c.section != section_id]
        claims = [c for c in claims if c.section == section_id]
        errors += [f"{c.claim_id}: unknown clinician_clarification_id {i}, removed" for c in claims
                   for i in c.clinician_clarification_ids if i not in known]
        claims = [c.model_copy(update={"clinician_clarification_ids": [i for i in c.clinician_clarification_ids if i in known],
                                       "problem": problem}) for c in claims]
        if not errors:
            break
        if not attempt:
            messages = messages + [{"role": "assistant", "content": result.model_dump_json()},
                                   {"role": "user", "content": "Validation errors:\n" + "\n".join(errors) + "\nReturn a corrected full result."}]
    if result.claims and not claims:
        raise SummaryError(f"{section_id}: no valid claims: " + "; ".join(errors))
    warnings = [f"{section_id}: {e}" for e in errors]
    if not result.claims:
        warnings.append(f"{section_id}: documented but no claims")
    return {"documented": True, "claims": claims, "warnings": warnings}


def assemble(recs: list[dict], resolutions: list[Resolution], problems: list[str],
             conflict_problem: dict[str, str]) -> tuple[Draft, list[str]]:
    """Joins section records in template order (hospital_course: problem order): numbers claims, adds resolution quotes,
    states uncarried resolutions in their problem's group."""
    by_key = {(r["section_id"], r["problem"]): r for r in recs}
    keys = [(s["section_id"], p) for s in TEMPLATE for p in (problems if s["section_id"] == "hospital_course" else [None])
            if (s["section_id"], p) in by_key]
    claims = {k: list(by_key[k]["claims"]) for k in keys}
    warnings = [w for k in keys for w in by_key[k]["warnings"]]
    for r in resolutions:
        if not any(r.conflict_id in c.clinician_clarification_ids for cs in claims.values() for c in cs):
            warnings.append(f"{r.conflict_id}: resolution not carried by any claim, added to hospital_course")
            claims[("hospital_course", conflict_problem[r.conflict_id])].append(SummaryClaim(
                claim_id="x", section="hospital_course", text=r.text, support_status="needs_review", problem=conflict_problem[r.conflict_id],
                evidence_span_ids=list(dict.fromkeys(q.span_id for q in r.quotes)), clinician_clarification_ids=[r.conflict_id]))
    by_id = {r.conflict_id: r for r in resolutions}
    out = []
    for c in (c for cs in claims.values() for c in cs):
        quoted = [q.span_id for i in c.clinician_clarification_ids for q in by_id[i].quotes]
        out.append(c.model_copy(update={"claim_id": f"C{len(out) + 1:02d}",
                                        "evidence_span_ids": list(dict.fromkeys(c.evidence_span_ids + quoted)),
                                        "support_status": "needs_review" if quoted else "unverified"}))
    return Draft(claims=out), warnings


DEDUPE_SYSTEM = """You remove duplicate claims from a discharge summary draft. Each line is: claim_id | section | problem | text.
- Return in drop_claim_ids only the IDs of claims to drop because another claim states the same fact. An empty list is a valid answer.
- Of each duplicate group, keep the claim in the section where the fact belongs best: a discharge medication stays in discharge_medications, a test result stays in key_events.
- Never drop claims that are related but say different things."""


def dedupe(draft: Draft) -> tuple[Draft, list[SummaryClaim], list[str]]:
    """Drops claims the model flags as repeats (guarded), renumbers C01.. -> (draft, removed claims, warnings). Never raises."""
    claims = draft.claims
    if len(claims) < 2:
        return draft, [], []
    ids = tuple(c.claim_id for c in claims)
    schema = create_model("DedupeResult", drop_claim_ids=(list[Literal[ids]], ...))
    lines = [f"{c.claim_id} | {c.section} | {c.problem or ''} | {c.text}" for c in claims]
    messages = [{"role": "system", "content": DEDUPE_SYSTEM}, {"role": "user", "content": "Claims:\n" + "\n".join(lines)}]
    for attempt in range(2):
        try:
            drops = llm.parse(schema, messages, TIMEOUT).drop_claim_ids
            break
        except Exception as e:
            if attempt:
                return draft, [], [f"dedupe: failed, all claims kept: {e}"]
    left, warnings = {c.claim_id: c for c in claims}, []
    for i in dict.fromkeys(d for d in drops if d in left):
        c = left[i]
        others = [o for k, o in left.items() if k != i]
        lone = next((r for r in c.clinician_clarification_ids if not any(r in o.clinician_clarification_ids for o in others)), None)
        if lone:
            warnings.append(f"dedupe: {i} ({c.text}) kept, last claim carrying resolution {lone}")
        elif not any((o.section, o.problem) == (c.section, c.problem) for o in others):
            warnings.append(f"dedupe: {i} ({c.text}) kept, last claim in its section or problem group")
        else:
            del left[i]
    removed = [c for c in claims if c.claim_id not in left]
    kept = [c.model_copy(update={"claim_id": f"C{n:02d}"}) for n, c in enumerate(left.values(), 1)]
    return draft.model_copy(update={"claims": kept}), removed, warnings
