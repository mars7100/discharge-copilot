# 10: Dedupe

**What to build:** After sections join, one dedupe call looks at all claims and returns only the IDs of duplicates to drop. The drop list's item type is an enum of the existing claim IDs built at runtime, so the model cannot return an unknown ID. Code drops them, but refuses any drop that would remove the last claim carrying a clinician resolution. The UI reports how many claims were removed. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 08

**Status:** resolved

- [x] Output schema restricts drop IDs to existing claim IDs (verified with a live call)
- [x] Listed claims are removed; resolution-carrying last claim is never removed
- [x] Dedupe-applied event streams with the count
- [x] Draft output is otherwise unchanged

## Comments

- Resolved in `e4192f8`. Contract: `10-contract.md`. Live: the enum drop-list schema is accepted by the API and returns only existing claim IDs; the case_001 load after dedupe keeps diagnoses, follow-up, pneumonia/hypertension groups and the D01 resolution (79 s for both live tests). Added beyond the ticket: a section guard that never empties a section or problem group.
