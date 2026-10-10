# 02: Prefactor: sections defined as data

**What to build:** Discharge summary sections are declared once as data (ID, title, purpose for the prompt, required/optional), following the municipal-document-ai template pattern, and both drafting and export read that declaration. New optional section IDs are added: key tests and interventions, discharge diagnoses, discharge medications, procedures, patient instructions, pending items. Required: reason for admission, hospital course, condition at discharge, follow-up. Output for current cases is unchanged. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] One section declaration drives draft prompt section list and export order/titles
- [x] Claim schema accepts the new optional section IDs
- [x] Required sections with no claims still export as "Not documented in the supplied notes."; optional sections with no claims are omitted
- [x] Existing tests pass

## Comments

- Resolved in `5de2384`. Declaration in `core/template.json` (municipal-document-ai shape: `section_id`, `title`, `purpose`, `optional`). `key_events` keeps its ID and title and serves as the key tests and interventions section. Order: reason for admission, discharge diagnoses, hospital course, procedures, key events, condition at discharge, discharge medications, patient instructions, follow-up, pending items. Omitting empty optional sections is the one accepted output change. The Streamlit app and read-section lookup still list all sections until 05.
