# About this example

What `teo-memory-agent` (the boilerplate at v0.2.0) looks like once installed for Sam (SPEC §9). Kept here:

- `.agent8/instance.yaml`: the instance record (answers, never secret values);
- `.agent8/template/0.2.0`: the read-only template. In this repo it is a symlink to
  `../teo-memory-agent` so the example isn't duplicated; a host stores a real copy;
- `agent.yaml`: the copy's own manifest, `extends: …@0.2.0`;
- the own layer: `identity.md` (seeded, with Sam's setup answers filled in), `LOCAL.md`;
- data: `memory/`, seeded once from the template's `seed/`;
- `CLAUDE.md`, one of the host-owned files: it imports the template's instructions, then the own layer.

Left out because the host regenerates them on every install and update: `AGENTS.md`,
`.claude/skills/`, `.agents/skills/`, `.claude/settings.json`, `.mcp.json` and the mirrored
template files (`tools/`, `templates/`, `.claude/rules/`), which the host writes as read-only
copies.

Check it with `python3 ../../tools/validate.py instance .`
