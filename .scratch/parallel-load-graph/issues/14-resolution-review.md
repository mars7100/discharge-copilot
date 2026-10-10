# 14: Resolution review

**What to build:** Submitting the "Resolve conflicts" panel no longer resumes the load. It opens a review summary, one row per conflict: the description, what the resident chose (the picked quote with its passage marker, or the typed clarification), and the resolution text exactly as the app will store it. **Edit** returns to the panel with the answers still filled in. **Start drafting** resumes the load as submitting does today. The review is client-side only; the API and graph are unchanged. Builds on 07.

**Blocked by:** None

**Status:** resolved

- [x] Submitting the panel shows the review summary; no request is sent and nothing is drafted
- [x] Each row shows the description, the choice, and the stored text (`"{description}: {quote}"` for a pick, the trimmed clarification otherwise)
- [x] Edit returns to the panel with every answer kept
- [x] Start drafting posts the resolutions and streams to done; a failure keeps the summary and shows the error
- [x] Editing stays locked until done

## Comments

- Resolved in 7a2ac20. Contract: `14-contract.md`. Client-side only; no API or graph change, so no live test.
- Review fixes (user decision): Edit is disabled while Start drafting is in flight; the panel no longer shows a Start drafting error after Edit.
- Deferred review findings:
  - The summary repeats the quote lookup `storedText` already does (−1 line).
  - `starting` could fold into `running`, which would also disable Load during the POST and close the 07 load-vs-resolve race.
