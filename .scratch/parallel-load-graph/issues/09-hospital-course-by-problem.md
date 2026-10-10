# 09: Hospital course by problem

**What to build:** A problem-normalization call maps the per-note `problem` labels onto one canonical problem list (so "CAP" and "community-acquired pneumonia" are one problem). The hospital course is drafted with one call per canonical problem, condensed to events that changed the stay, and shown grouped by problem. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] Normalization returns a canonical list; every event maps to one problem
- [ ] Hospital course drafted per problem, concurrently, and rendered with problem subheadings
- [ ] Export renders hospital course grouped by problem
- [ ] `live`: case_001 hospital course has pneumonia and hypertension groups
