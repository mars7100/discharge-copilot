# 14: Resolution review

**What to build:** Submitting the "Resolve conflicts" panel no longer resumes the load. It opens a review summary, one row per conflict: the description, what the resident chose (the picked quote with its passage marker, or the typed clarification), and the resolution text exactly as the app will store it. **Edit** returns to the panel with the answers still filled in. **Start drafting** resumes the load as submitting does today. The review is client-side only; the API and graph are unchanged. Builds on 07.

**Blocked by:** None

**Status:** open

- [ ] Submitting the panel shows the review summary; no request is sent and nothing is drafted
- [ ] Each row shows the description, the choice, and the stored text (`"{description}: {quote}"` for a pick, the trimmed clarification otherwise)
- [ ] Edit returns to the panel with every answer kept
- [ ] Start drafting posts the resolutions and streams to done; a failure keeps the summary and shows the error
- [ ] Editing stays locked until done
