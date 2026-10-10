# 13: Model-proposed corrections

**What to build:** The correction flow gets a real proposer. The clinician states what is wrong with a claim (for example, "dose was 10 mg from Day 3"). One model call rewrites that claim using only the clinician's statement and the claim's cited passages. The clinician then accepts or rejects the proposed text. Today the clinician types both the statement and the corrected text, then accepts their own text, so the propose/accept step has no second party. Spec story 40.

**Blocked by:** None

**Status:** resolved

- [x] Proposing takes a claim and a statement only; the corrected text comes from one model call
- [x] Accept/reject behave as before (accept applies the text, links the clarification, resets approval)
- [x] Model failure or an unchanged proposal is reported and creates no pending correction
- [x] Frontend: statement input only, then before/after review with Accept/Reject
- [x] `live`: a case_001 correction proposal changes the claim text and reflects the statement

## Comments

- Resolved in bcaa3d7. Contract: `13-contract.md`. Live case_001 follow-up correction test passed.
