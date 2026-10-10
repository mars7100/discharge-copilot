# 13: Model-proposed corrections

**What to build:** The correction flow gets a real proposer. The clinician states what is wrong with a claim (for example, "dose was 10 mg from Day 3"). One model call rewrites that claim using only the clinician's statement and the claim's cited passages. The clinician then accepts or rejects the proposed text. Today the clinician types both the statement and the corrected text, then accepts their own text, so the propose/accept step has no second party. Spec story 40.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] Proposing takes a claim and a statement only; the corrected text comes from one model call
- [ ] Accept/reject behave as before (accept applies the text, links the clarification, resets approval)
- [ ] Model failure or an unchanged proposal is reported and creates no pending correction
- [ ] Frontend: statement input only, then before/after review with Accept/Reject
- [ ] `live`: a case_001 correction proposal changes the claim text and reflects the statement
