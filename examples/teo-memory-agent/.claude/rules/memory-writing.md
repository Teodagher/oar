---
paths:
  - "memory/**"
  - "templates/**"
---

# Memory writing rules

`python3 tools/memory.py lint` enforces the structure; the Stop hook blocks a turn on lint errors.

## Pages
- Create with `python3 tools/memory.py new <type> "Title"`. The file name is the slug of the title;
  link pages as `[[slug]]`.
- Types: `person`, `org`, `topic`, `decision` go to `memory/wiki/entities/`; `procedure`, `lesson`
  go to `memory/wiki/howto/`.
- Frontmatter: `title`, `type`, `aliases: [..]`, `summary` (one line, shown in the index),
  `updated` (bump on every edit).
- **Synthesis** = everything above `## Evidence log`: what is true now, edited with targeted deltas.
- **`## Evidence log`** = the last section, append-only, oldest first:
  `- YYYY-MM-DD · fact — [[source]]`.

## now.md
Three sections: **Focus**, **Waiting on**, **Next**. One line per loop, `due: YYYY-MM-DD` when
dated. Done: delete the line and `memory.py log done "..."`.

## Secrets
Never put a password, token, key or bank detail in memory or in a reply: write
"[credential removed]" before filing text.
