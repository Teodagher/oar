---
paths:
  - "memory/**"
  - "templates/**"
---

# Memory writing rules

`python3 tools/memory.py lint` enforces the structure; the Stop hook blocks a turn on lint errors.

## Pages
- Create with `python3 tools/memory.py new <type> "Title"`. The file name is the slug of the title
  and is unique across the wiki; link pages as `[[slug]]` (or `[[slug|label]]`).
- Types: `person`, `org`, `topic`, `decision` → `memory/wiki/entities/`; `procedure`, `lesson` →
  `memory/wiki/howto/`. `topic` is the general bucket: projects, accounts, subjects, products.
- Frontmatter, one `key: value` per line: `title`, `type`, `aliases: [..]` (every other name the
  thing goes by, so it's found again), `summary` (one line; the index shows it every session),
  `updated` (bump on every edit). Optional: `status`, `supersedes`, `superseded_by`, `merged_into`.
- **Synthesis** = everything above `## Evidence log`: what is true now. Edit it with targeted deltas
  (the sentences that changed), never a full rewrite. Mark your own conclusions `> [!inference]`.
- **`## Evidence log`** = the last section, append-only, oldest first. Never edit or delete a line:

  `- YYYY-MM-DD · fact — [[source]]`

  - date: when the fact became true or was said, not when you wrote it.
  - source: the raw file `[[raw/2026-02-10_chat_invoices.md]]` (extension optional) or a page `[[slug]]`.
  - A changed fact: `- YYYY-MM-DD · SUPERSEDES: old value · new value — [[source]]`.
  - Optional tag after the date: `stated`, `documented`, `observed`, `decided` or `inferred`.
- Every claim in the synthesis traces to an evidence line.

## Choices per fact
1. **Find the page** (index, `grep -ril "<name>" memory/wiki`). Exists → update it, add new aliases.
   Doesn't → `memory.py new`.
2. **Compare**: new, more detail, contradicts (SUPERSEDES; the newest dated source wins), or nothing.
   Two sources conflict and neither is clearly newer → note both in the synthesis and ask the owner.
3. **Never delete a page.** Duplicate → merge into one, keep the other as a stub with
   `merged_into: <slug>`. Obsolete → say so in the synthesis.
4. **Decisions are never rewritten.** A change of mind is a new decision with `supersedes: <old>`;
   the old one gets `status: superseded` and `superseded_by: <new>`.

## now.md
Three sections, edited in place: **Focus** (what you're doing), **Waiting on** (who/what, since
when), **Next** (queued). One line per loop, `due: YYYY-MM-DD` when dated. Done → delete the line and
`memory.py log done "..."`. Durable facts learned along the way go to wiki pages, not here.

## Secrets
Memory may be committed to the owner's git repository, raw files included. Never put a password, token, key or bank detail
anywhere in memory or in a reply: redact it to "[credential removed]" before filing text, ask the
owner before filing a file that contains one, and write "credential present in source" in pages.
