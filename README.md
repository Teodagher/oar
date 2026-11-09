# OAR — Open Agent Recipe (v0.2 draft)

Public repository: <https://github.com/Teodagher/oar>. Releases are tags (`v0.2.0` is this draft).

**OAR** is an open format for sharing AI agents. A shared agent (the recipe, or *template*) is
a **read-only template** plus the copy's **own layer**; updating means switching template
versions, never merging. Built on OpenGAP `agent.yaml`, AGENTS.md, Agent
Skills and Claude Code plugins.

| File | What it is |
|---|---|
| [`SPEC.md`](SPEC.md) | the format |
| [`PROFILE-agent8.md`](PROFILE-agent8.md) | what agent8, the first host, does with it (hosting, trust, vault, launch) |
| [`schema/`](schema/) | JSON Schemas for `agent.yaml` and `.agent8/instance.yaml` |
| [`examples/`](examples/) | `teo-memory-agent` (modelled on Teo's boilerplate), `invoice-chaser` (secrets, MCP), `installed-copy` |
| [`tools/validate.py`](tools/validate.py) | validator: `python3 tools/validate.py template <dir>` or `instance <dir>` |
| [`tools/oar.py`](tools/oar.py) | reference command line `oar`: `check`, `new`, `install`, `import`, `update`, `plugin` (below) |
| [`tools/importer.py`](tools/importer.py) | reference reading of OpenGAP repos without the block and plain AGENTS.md repos (SPEC §12) |
| [`rfcs/`](rfcs/) | draft RFC for OpenGAP (not submitted) |

Tests: `python3 -m unittest discover -s tools` (needs PyYAML, jsonschema and git; with Node 22
next to agent8's code, `test_importer.py` also checks agent8 reads OpenGAP repos the same way).

## The reference command line

`tools/oar.py` (the `oar` command) makes the format usable without any host. It needs Python
3.9+, git, PyYAML and jsonschema, and nothing else. It was called `agentfmt` before the format
was named; `tools/agentfmt.py` is kept as an alias, so old scripts keep working.

```sh
oar new my-agent --author "Sam"             # a new template that already passes check
oar check my-agent                          # what git would commit: required fields, declared
                                            # paths exist, no data, no secret files or values,
                                            # undeclared executables listed
oar install https://github.com/sam/my-agent sams-agent --answer owner_name=Sam
                                            # the latest release tag (or --version 1.2.0):
                                            # template read-only under .agent8/template/<version>/,
                                            # the copy's own layer beside it, data seeded once
oar update sams-agent --dry-run             # what switching to the latest version would change
oar update sams-agent --to 1.1.0            # switch version, up or back; never a merge
oar import https://github.com/sam/opengap-agent my-template
                                            # an OpenGAP repo without the x-agent8 block (or a
                                            # plain AGENTS.md repo) written out as a template
                                            # (SPEC §12), with what wasn't carried over; install
                                            # reads such repos the same way
oar plugin https://github.com/sam/my-agent --zip my-agent.zip
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
- run: pip install pyyaml jsonschema && python3 path/to/oar.py check .
```

OAR is MIT-licensed ([`LICENSE`](LICENSE)). Its first host is [agent8](https://www.agent8.sh),
where this draft started; the extension block is named `x-agent8` for that
reason, and nothing else in the format depends on agent8.
