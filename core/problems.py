"""Raw per-note problem labels -> one canonical problem list; every event and conflict gets exactly one problem (ticket 09)."""
from pydantic import BaseModel

from core import llm
from core.models import ClinicalEvent, ConflictItem

SYSTEM = """You merge problem labels from synthetic hospital notes into one canonical problem list.
- Group labels that name the same clinical problem (e.g. "CAP" and "community-acquired pneumonia") under one short canonical name.
- For each problem list the raw labels it covers, exactly as given, and the IDs of the documentation conflicts (D01...) that concern it.
- Use only the supplied labels and conflicts. Map each label and each conflict at most once."""
TIMEOUT = 35
OTHER = "Other"


class Problem(BaseModel):
    name: str
    labels: list[str]
    conflict_ids: list[str]


class ProblemList(BaseModel):
    problems: list[Problem]


def normalize(events: list[ClinicalEvent], conflicts: list[ConflictItem]) -> tuple[list[ClinicalEvent], list[str], dict[str, str], list[str]]:
    """Returns (events with canonical problems, problem order, conflict_id -> problem, warnings). Never raises."""
    labels = list(dict.fromkeys(e.problem for e in events if e.problem))
    ids = [c.conflict_id for c in conflicts]
    label_to, conflict_to, warnings = {}, {}, []
    if labels or conflicts:
        lines = [f"Label: {label}" for label in labels] + [
            f"{c.conflict_id} | {c.description} | " + " / ".join(q.quote for q in c.quotes) for c in conflicts]
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}]
        for attempt in range(2):
            try:
                result = llm.parse(ProblemList, messages, TIMEOUT)
            except Exception as e:
                if attempt:
                    warnings.append(f"problem normalization failed ({e}); using raw labels")
                continue
            for p in result.problems:
                for key, known, target in [(k, labels, label_to) for k in p.labels] + [(k, ids, conflict_to) for k in p.conflict_ids]:
                    if key not in known or not p.name.strip():
                        continue  # unknown labels and IDs, and blank names, are ignored
                    if key in target:
                        warnings.append(f"problem normalization: {key} mapped twice, kept {target[key]}")
                    else:
                        target[key] = p.name
            warnings += [f"problem normalization: label {x} unmapped, kept as its own problem" for x in labels if x not in label_to]
            warnings += [f"problem normalization: conflict {x} unmapped, assigned to {OTHER}" for x in ids if x not in conflict_to]
            break
    label_to = {x: label_to.get(x, x) for x in labels}  # unmapped (or failed call): the label itself
    conflict_to = {x: conflict_to.get(x, OTHER) for x in ids}
    events = [e.model_copy(update={"problem": label_to.get(e.problem, OTHER) if e.problem else OTHER}) for e in events]
    order = list(dict.fromkeys(e.problem for e in events if e.problem != OTHER))
    order += [p for p in dict.fromkeys(conflict_to[i] for i in ids) if p not in order and p != OTHER]  # resolution-only problems, conflict-ID order
    return events, order + [OTHER], conflict_to, warnings
