# 10: Dedupe

**What to build:** After sections join, one dedupe call looks at all claims and returns only the IDs of duplicates to drop. The drop list's item type is an enum of the existing claim IDs built at runtime, so the model cannot return an unknown ID. Code drops them, but refuses any drop that would remove the last claim carrying a clinician resolution. The UI reports how many claims were removed. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] Output schema restricts drop IDs to existing claim IDs (verified with a live call)
- [ ] Listed claims are removed; resolution-carrying last claim is never removed
- [ ] Dedupe-applied event streams with the count
- [ ] Draft output is otherwise unchanged
