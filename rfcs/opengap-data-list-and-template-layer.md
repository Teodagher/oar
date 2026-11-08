# RFC: Extension keys, a data list, and pinned read-only parents for gitagent manifests

> **Draft, not submitted.** Written for `open-gitagent/opengap` (`spec/rfcs/`), following the
> shape of its `identity.md` RFC. Submission is ticket T-167 in the agent8 repo and waits for
> Teo's go.

| Field | Value |
|---|---|
| RFC | template-layer |
| Status | Draft |
| Author | Teo Dagher (agent8) |
| Targets spec | v0.1.x (all additions optional) |
| Issue | to be opened |
| Reference impl | OAR (Open Agent Recipe) v0.2, its validator and the `oar` command line (MIT), link to be added once published |

## 1. Motivation

gitagent's promise is "clone a repo, get an agent". Two things get in the way once an agent is
shared with other people and keeps improving:

1. **Data travels with the definition.** `memory/` lives in the repo. When someone shares an
   agent they have used, its memory (client names, conversations, raw sources) goes with it.
   When the author fixes a skill, a user cannot take the fix without the author's memory.
2. **There is no update path for a customised copy.** `extends` lets a child agent build on a
   parent, but it names an unpinned git URL, and nothing says what the child may change or
   how it receives the parent's next version. In practice people fork, edit the parent's files
   and lose updates; tools that try a three-way merge break exactly the files agents edit
   (instructions they rewrite, config files the runtime writes).

A third, smaller issue blocks anyone who wants to build on the manifest:

3. **No room for extensions.** `agent-yaml.schema.json` sets `additionalProperties: false`, so
   any extra key fails `opengap validate`, and `metadata` only takes scalar values.

## 2. Proposal

Three optional additions. A manifest that uses none of them is unchanged.

### 2.1 Extension keys

Allow top-level keys matching `^x-` (the OpenAPI convention), ignored by tools that don't know
them:

```json
"patternProperties": { "^x-": {} }
```

Tools MUST NOT fail validation because of an `x-` key and MUST preserve it when they rewrite a
manifest.

### 2.2 `data`: what never travels

An optional list of path patterns that belong to a *running* agent, never to its definition:

```yaml
data:
  - /memory/
  - /knowledge/clients/
  - "**/*.log"
```

- Each item is one gitignore pattern, **anchored** (starts with `/` or `**/`), with no comment
  and no surrounding spaces, so it can be written verbatim into a `.gitignore` and read the same
  way by every tool. Gitignore semantics apply (last match wins; a file inside an excluded
  directory can't be re-included).
- A **published** agent MUST NOT contain files matching `data`, except under `seed/`, which holds
  starting content copied once into a new copy (an empty `memory/MEMORY.md`, for example).
- Exporters and `opengap export` MUST NOT include data paths.
- When `data` is absent, tools SHOULD assume `/memory/` and `/.gitagent/` (today's defaults).

### 2.3 Pinned, read-only parents: the "template + own layer" model

Allow `extends` to pin an exact version, and define what a child may change:

```yaml
extends: https://github.com/org/base-agent@1.4.0
```

- `<source>@<version>`: split on the last `@`; `<version>` is an exact semver that resolves to
  the git tag `v<version>` (or `<version>`). Without `@`, today's behaviour is unchanged.
- The parent at that version is installed **read-only** (for example under `.gitagent/deps/`).
  The child never edits it.
- The child's own changes live in its **own layer**, in files the parent doesn't ship:
  an identity file, a local instructions file, its own `skills/` (which already shadow the
  parent's on a name clash, per §15) and its own manifest.
- **Updating** means changing the pinned version and rebuilding the generated files
  (instructions, tool config). There is no merge. Rolling back means pinning the old version.
- Files that a runtime writes (Claude Code's `.mcp.json` and `.claude/settings.json`, Codex's
  config) are **generated** from parent + child + runtime entries and never shipped for merging.

This matches how plugins already behave in Claude Code (installed read-only, updated as a whole,
user values kept separately) and makes `extends` usable for the most common case: "I use
someone's agent, customised, and I want their improvements."

### 2.4 `SOUL.md` optional when `AGENTS.md` exists

Many existing agent repos have an `AGENTS.md` and no `SOUL.md`. We suggest validation rule 2
read: *"contain `SOUL.md` or `AGENTS.md` with at least one non-empty paragraph."* This lets the
large number of AGENTS.md-based repos be valid gitagent repos with one added file.

## 3. Example

A memory agent as a template (`teo-memory-agent`), and one person's copy of it:

```yaml
# template: agent.yaml
spec_version: "0.1.0"
name: teo-memory-agent
version: 0.2.0
description: An agent with durable memory.
license: MIT
data:
  - /memory/
  - /logs/
```

```yaml
# copy: agent.yaml
name: sams-memory-agent
version: 0.0.1
description: Sam's memory agent
extends: https://github.com/Teodagher/teo-agent-boilerplate@0.2.0
data:
  - /drafts/          # unioned with the parent's list; a child can't remove a parent pattern
```

The copy's folder holds the parent at 0.2.0 read-only, its own `identity.md`, `LOCAL.md` and
`skills/`, its `memory/` (seeded once from the parent's `seed/memory/`), and generated
`AGENTS.md`/`CLAUDE.md` that import the parent's instructions and then the own layer. When the
author publishes 0.3.0, Sam's copy switches to it; `memory/` and the own layer are untouched.

## 4. Compatibility

- All additions are optional. Existing manifests validate unchanged once `^x-` keys are allowed.
- `memory/` stays where it is; `data` only says it must not be published.
- `extends` without `@` keeps today's meaning.

## 5. Alternatives considered

- **A separate data file (`.agentdata`, gitignore syntax).** One more file, and in practice
  people write `pattern  # comment`, which gitignore reads as part of the pattern. Inside the
  manifest the list is structured and comments live in YAML.
- **Three-way merge of parent updates (Copier-style).** Tested on a real memory agent: it
  conflicts in exactly the files agents and runtimes write. Read-only parent plus own layer
  avoids conflicts by construction.
- **Using `metadata` for extensions.** Its values must be scalars.

## 6. Open questions

1. Should `data` patterns also be honoured by `opengap install` for `dependencies`?
2. Where should a runtime keep the pinned parent: `.gitagent/deps/<name>@<version>/` or a host
   folder?
3. Should the RFC also standardise setup questions and declared secrets (agent8 keeps them in
   its `x-agent8` block today), or leave those to extensions?
