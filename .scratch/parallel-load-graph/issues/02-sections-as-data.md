# 02: Prefactor: sections defined as data

**What to build:** Discharge summary sections are declared once as data (ID, title, purpose for the prompt, required/optional), following the municipal-document-ai template pattern, and both drafting and export read that declaration. New optional section IDs are added: key tests and interventions, discharge diagnoses, discharge medications, procedures, patient instructions, pending items. Required: reason for admission, hospital course, condition at discharge, follow-up. Output for current cases is unchanged. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] One section declaration drives draft prompt section list and export order/titles
- [ ] Claim schema accepts the new optional section IDs
- [ ] Required sections with no claims still export as "Not documented in the supplied notes."; optional sections with no claims are omitted
- [ ] Existing tests pass
