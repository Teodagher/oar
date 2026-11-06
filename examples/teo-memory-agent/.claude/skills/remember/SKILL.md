---
name: remember
description: "Write new information into memory. Use whenever something new arrives: a fact, decision or preference the owner states, a pasted message or document, a file, a tool result, a promise you made, feedback or a correction. Triggers: 'remember', 'note that', 'from now on', 'add to memory'."
---

# Remember

Every new piece of information is a source: keep it verbatim in `memory/raw/`, then update the
pages it changes. Format: `.claude/rules/memory-writing.md`.

1. **File the source** (skip chit-chat; when unsure, keep it). Redact secrets first.
   `python3 tools/memory.py file --text - --date <when said> --kind chat --slug <short-name>`
   with the text on stdin, or `file <path> …` for a file.
2. **Update the pages**: find each page the source touches (index, then
   `grep -ril "<name>" memory/wiki`); create missing ones with `memory.py new <type> "Title"`.
   Edit the synthesis with targeted deltas and append an evidence line citing the raw file.
3. **Open loops** go in `memory/now.md`. Owner feedback becomes a `lesson` page.
4. `python3 tools/memory.py log remember "<what>"`, then `index`.
