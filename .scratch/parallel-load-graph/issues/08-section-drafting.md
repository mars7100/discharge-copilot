# 08: Section-by-section drafting

**What to build:** After resolution, each section from the section declaration is drafted in its own model call, all at once. Each call returns structured output with a `documented` decision and its claims; code drops optional sections that are not documented (and warns on documented-but-empty). Claims are numbered C01… in section order after the join. Sections stream into the UI as they finish, and the draft is visible early while editing stays locked until done. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 02, 07

**Status:** resolved

- [x] One draft call per section, run concurrently
- [x] Optional sections with `documented: false` are omitted; required ones show "Not documented in the supplied notes."
- [x] Section-drafted / section-omitted events stream and render
- [x] Claim citations validated as before; numbering stable in section order
- [x] `live`: case_001 draft includes discharge diagnoses and follow-up, cites passages, and keeps the clinician resolution

## Comments

- Resolved in `1bd415b`. Contract: `08-contract.md`. Live case_001 test passed (39 s for the whole test, including extraction). A section whose retry throws fails the load, per the contract decision.
