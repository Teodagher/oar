---
name: remember
description: "Write new information into memory. Use whenever something new arrives: a fact, decision or preference the owner states, a pasted message or document, a file, a tool result, a promise you made, feedback or a correction. Triggers: 'remember', 'note that', 'from now on', 'add to memory'."
---

# Remember

Every new piece of information is a source: keep it verbatim in `memory/raw/`, then update the pages
it changes. Format: `.claude/rules/memory-writing.md`.

1. **File the source** (skip chit-chat; when unsure, keep it, raw is cheap). Redact secrets first.
   - Chat or pasted text, with who said it and when:
     ```
     python3 tools/memory.py file --text - --date <event date> --kind chat --slug <slug> <<'EOF'
     2026-02-10, Sam (owner): "From now on, invoices go by email, never by post."
     EOF
     ```
   - A file: `python3 tools/memory.py file <path> --date <event date> --kind <kind> --slug <slug>`
   - It prints the citation, e.g. `[[raw/2026-02-10_chat_invoices-by-email.md]]`.
2. **Update pages**, one fact at a time:
   - Find the page (index, `grep -ril "<name or alias>" memory/wiki`); none → `memory.py new <type> "Title"`.
   - Edit the synthesis sentences that changed, bump `updated`, add aliases, fill `summary`.
   - Append the evidence line: `- 2026-02-10 · Invoices go by email, never by post — [[raw/2026-02-10_chat_invoices-by-email.md]]`
   - Decided → `decision` page. Owner feedback → `lesson` (What / Why / How to apply; `summary` = the rule).
     A how-to → `procedure`. A contradiction → `SUPERSEDES:` line, the synthesis takes the new value.
3. **Open loops** → `memory/now.md` (with `due:`); finished ones → delete the line, `memory.py log done "..."`.
4. **Close**: `python3 tools/memory.py log remember "<source>: <pages touched>"`, `index`, `lint` (0 errors),
   `python3 tools/memory.py commit "memory: <what was learned>"`. One line to the owner if present.

Touch only what the source changes. Never rewrite a page.
