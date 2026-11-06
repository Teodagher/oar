---
name: recall
description: "Answer from memory. Use before acting on anything that involves a person, organization, topic or past decision, and whenever asked 'what do we know about X', 'what did we decide', 'when', 'who', 'did I tell you', 'remind me'."
---

# Recall

Read as little as needed, in this order:

1. **Index** (`memory/index.md`, its head is already in context): match titles and summaries.
2. **Search** if needed: `grep -ril "<name|alias|keyword>" memory/wiki`; `grep -rl` in `memory/raw` last.
3. **Pages**: the synthesis is the current truth, the evidence log says when and from where. Follow
   `[[links]]` one hop when relevant. Merged stubs point to the real page; superseded decisions are history.
4. **Raw** only to verify a quote, a number or a contradiction.

Answer citing pages ("Invoices go by email ([[sam]], since 2026-02-10)"). Say what memory doesn't know
instead of guessing, and offer to find out.

If the answer took real digging or the owner corrected you, `remember` it (a synthesis on a `topic`, or a
`lesson`) so next time it's one lookup.
