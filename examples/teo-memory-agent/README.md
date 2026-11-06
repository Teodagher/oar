# teo-memory-agent (example template)

A Claude Code agent with durable memory: it interviews its owner on first launch, then works
session after session, keeping what it learns in `memory/` without bloating its context.

This folder is the worked example of the [agent template format v0.2](../../SPEC.md): a copy of
[`Teodagher/teo-agent-boilerplate`](https://github.com/Teodagher/teo-agent-boilerplate) at tag
`v0.2.0` (commit `56fcd2b`), the real conversion done in ticket T-147. Only this README differs
from the repo's own. What changed compared with the boilerplate before v0.2.0:

| Before v0.2.0 | v0.2.0 (this folder) | Why |
|---|---|---|
| Identity written into `CLAUDE.md` and `agent.json` by onboarding | `identity.md`, seeded from `seed/identity.md` | the template's instructions are never edited, so updates never collide |
| `CLAUDE.md` holds the manual | `AGENTS.md` holds it; `CLAUDE.md` = `@AGENTS.md` + own layer | Codex, Cursor and others read AGENTS.md |
| Self-improvement edits the manual | improvements go to `LOCAL.md` and own skills in `skills/` | the copy's own layer survives every update |
| Onboarding ends with `git add -A` | `memory.py commit` saves only the own layer and memory, by explicit path | template files and stray edits never get committed by the agent |
| `memory/` starting files committed | `seed/memory/…`, `/memory/` in the data list; `memory.py` copies missing seeds itself | memory is the owner's data, never shipped |
| Skills only in `.claude/skills/` | `.agents/skills` links to it | Codex reads `.agents/skills` |
| No manifest, no licence | `agent.yaml`, `LICENSE` (MIT) | versioned and legally reusable |

## Run it

- **With agent8:** import it. agent8 asks the setup questions, seeds `memory/` and `identity.md`,
  and keeps this template read-only beside the copy's own layer.
- **By hand:** GitHub's "Use this template" (or copy the folder), then `claude`. The first
  `tools/memory.py status` (the SessionStart hook) copies `seed/` to the root; the onboarding
  skill fills in `identity.md`.

Check it with `python3 ../../tools/validate.py template .`
