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
| [`tools/agentfmt.py`](tools/agentfmt.py) | reference command line: `check`, `new`, `install`, `update`, `plugin` (below) |
| [`rfcs/`](rfcs/) | draft RFC for OpenGAP (not submitted) |

Tests: `python3 -m unittest discover -s tools` (needs PyYAML, jsonschema and git).

## The reference command line

`tools/agentfmt.py` makes the format usable without any host. It needs Python 3.9+, git,
PyYAML and jsonschema, and nothing else. `agentfmt` is a placeholder name until the format has
one (one constant, `TOOL`, at the top of the file).

```sh
agentfmt new my-agent --author "Sam"        # a new template that already passes check
agentfmt check my-agent                     # what git would commit: required fields, declared
                                            # paths exist, no data, no secret files or values,
                                            # undeclared executables listed
agentfmt install https://github.com/sam/my-agent sams-agent --answer owner_name=Sam
                                            # the latest release tag (or --version 1.2.0):
                                            # template read-only under .agent8/template/<version>/,
                                            # the copy's own layer beside it, data seeded once
agentfmt update sams-agent --dry-run        # what switching to the latest version would change
agentfmt update sams-agent --to 1.1.0       # switch version, up or back; never a merge
agentfmt plugin https://github.com/sam/my-agent --zip my-agent.zip
                                            # the same template as a Claude Code plugin (with a
                                            # one-plugin marketplace): /plugin marketplace add,
                                            # then /plugin install; never its data or secrets
```

Releases are git tags `vX.Y.Z` whose `agent.yaml` has the same `version`. `install` and `update`
refuse, before writing anything, a template whose format major is newer than the tool reads,
paths with `..`, absolute paths, `.git` folders, links that leave the folder, and invalid
templates. `update` also refuses to write over the copy's own files, its data or its cloned
repositories, saves hand-edited template files under `.agent8/previous/`, and keeps MCP servers
added at run time. It doesn't start the agent: it prints the environment variables to start it
with (secrets stay with the person; the tool has no vault). Exit codes: 0 done, 1 invalid or
refused, 2 usage, 3 format too new.

In a template's own CI:

```yaml
- run: pip install pyyaml jsonschema && python3 path/to/agentfmt.py check .
```

Ticket T-146 in the agent8 backlog tracks this draft. It moves to its own public repo (MIT)
once it has a name.
