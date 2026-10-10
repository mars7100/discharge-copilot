# 09: Hospital course by problem

**What to build:** A problem-normalization call maps the per-note `problem` labels onto one canonical problem list (so "CAP" and "community-acquired pneumonia" are one problem). The hospital course is drafted with one call per canonical problem, condensed to events that changed the stay, and shown grouped by problem. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 08

**Status:** resolved

- [x] Normalization returns a canonical list; every event maps to one problem
- [x] Hospital course drafted per problem, concurrently, and rendered with problem subheadings
- [x] Export renders hospital course grouped by problem
- [x] `live`: case_001 hospital course has pneumonia and hypertension groups

## Comments

- Resolved in `24a48c4`. Contract: `09-contract.md`. Live case_001 test passed (62 s for the whole test). Normalization failure falls back to raw labels and never fails the load; normalization warnings are recorded but not yet shown in the UI.
