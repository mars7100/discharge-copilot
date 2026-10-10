# 12: Route events to the sections they belong to

**What to build:** Each non-hospital-course section call gets only the events relevant to it, instead of every event. This reduces claims repeated across sections at the source. The live case_001 draft has about 80 claims before dedupe; one run removed 19. Fewer claims make drafting and dedupe faster: dedupe is the slowest single call (24–27 s, run after all drafting). It also gives ticket 11's redraft a real "affected sections" set, since today every non-hospital-course section is redrafted when any event is added. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** None

**Status:** needs-triage

Open design questions:
- **How events map to sections.** Options:
  - a code mapping from event `category`, which is cheap but a hard-coded guess that can starve sections;
  - adding a `sections` field to extraction output, which makes extraction responsible for deciding;
  - one routing call after merge, which adds latency but keeps the mapping out of extraction.
- **Unmapped events.** Whether an event no section claims is sent everywhere, or only to `key_events`.
- **Resolutions.** Whether they keep going to every section, or are routed the same way as events.
- **Measurement.** The claim count before dedupe and the load time on case_001, measured before and after.

- [ ] Each non-hospital-course section call receives only its routed events (plus the agreed resolutions)
- [ ] Ticket 11 redraft touches only sections whose routed input changed
- [ ] `live`: case_001 pre-dedupe claim count and load time recorded before/after; draft still has diagnoses, follow-up, problem groups and the D01 resolution
