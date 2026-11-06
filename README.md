# Open agent template format (v0.2 draft)

A shared agent is a **read-only template** plus the copy's **own layer**; updating means
switching template versions, never merging. Built on OpenGAP `agent.yaml`, AGENTS.md, Agent
Skills and Claude Code plugins.

| File | What it is |
|---|---|
| [`SPEC.md`](SPEC.md) | the format |
| [`PROFILE-agent8.md`](PROFILE-agent8.md) | what agent8, the first host, does with it (hosting, trust, vault, launch) |
| [`schema/`](schema/) | JSON Schemas for `agent.yaml` and `.agent8/instance.yaml` |
| [`examples/`](examples/) | `teo-memory-agent` (modelled on Teo's boilerplate), `invoice-chaser` (secrets, MCP), `installed-copy` |
| [`tools/validate.py`](tools/validate.py) | validator: `python3 tools/validate.py template <dir>` or `instance <dir>` |
| [`rfcs/`](rfcs/) | draft RFC for OpenGAP (not submitted) |

Tests: `python3 -m unittest discover -s tools` (needs PyYAML and jsonschema).

Ticket T-146 in the agent8 backlog tracks this draft. It moves to its own public repo (MIT)
once it has a name.
