---
name: tidy
description: "Maintain memory. Use when the owner asks to tidy, clean or review memory, when lint warnings pile up, or about weekly during active use."
---

# Tidy

Keep memory accurate and easy to navigate. Never delete a page or an evidence line, never touch
`memory/raw/`.

1. `python3 tools/memory.py lint`: fix every error, read the warnings.
2. **now.md**: overdue or stale lines: do, re-date, move to Waiting on, or ask the owner.
3. **Duplicates**: merge into one page, keep the other as a stub with `merged_into: <slug>`.
4. `python3 tools/memory.py index`, then `log tidy "<what changed>"`.
