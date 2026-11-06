# teo-memory-agent (example template)

A Claude Code agent with durable memory: it interviews its owner on first launch, then works
session after session, keeping what it learns in `memory/` without bloating its context.

This folder is the worked example of the [agent template format v0.2](../../SPEC.md), modelled on
[`Teodagher/teo-agent-boilerplate`](https://github.com/Teodagher/teo-agent-boilerplate). What
changed compared with that repo:

| Boilerplate today | Here | Why |
|---|---|---|
| Identity written into `CLAUDE.md` and `agent.json` by onboarding | `identity.md`, seeded from `seed/identity.md` | the template's instructions are never edited, so updates never collide |
| `CLAUDE.md` holds the manual | `AGENTS.md` holds it; `CLAUDE.md` = `@AGENTS.md` + own layer | Codex, Cursor and others read AGENTS.md |
| Self-improvement edits the manual | improvements go to `LOCAL.md` and own skills in `skills/` | the copy's own layer survives every update |
| `memory/` starting files committed | `seed/memory/…`, `/memory/` in the data list | memory is the owner's data, never shipped |
| No manifest, no licence | `agent.yaml`, `LICENSE` (MIT) | versioned and legally reusable |

## Run it

- **With agent8:** import it. agent8 asks the setup questions, seeds `memory/` and `identity.md`,
  and keeps this template read-only beside the copy's own layer.
- **By hand:** copy the folder, copy the contents of `seed/` to the root, run `claude`. The
  onboarding skill fills in `identity.md`.

Check it with `python3 ../../tools/validate.py template .`
