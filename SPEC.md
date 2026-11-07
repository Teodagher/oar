# Open agent template format — v0.2 (draft)

*Working title. No name has been chosen for the format yet; the decisions say "its name can
wait". The extension block is called `x-agent8` because agent8 is the first host; nothing else
in the format depends on agent8.*

Status: **draft v0.2**, 2026-11-06, revised once after a review against six of Teo's real
agents (ticket T-146). Replaces the copy-and-merge draft v0.1 ("Forkable",
`raw/portable-agents/2026-11-06-agent-protocol-spec-v0.1-draft.md`). The key words MUST, SHOULD and MAY are used as in RFC 2119.

## 0. In one paragraph

A **template** is an ordinary folder (often a git repo) holding everything needed to *become* an
AI agent — instructions, skills, MCP servers, settings, setup questions, the names of the
secrets it needs — and **none of the data** of a running agent. A **copy** (an installed agent)
keeps the template as a **read-only** copy of one exact version and writes everything of its
own — identity, local rules, its own skills and settings — to **its own layer** next to it.
Updating a copy means **switching to another template version**; nothing is ever merged. The
format invents almost nothing: the manifest is an [OpenGAP / GitAgent](https://github.com/open-gitagent/opengap)
`agent.yaml`, instructions are [AGENTS.md](https://agents.md), skills are
[Agent Skills](https://agentskills.io), MCP servers use the shared `mcpServers` JSON shape, and
a template can be exported as a [Claude Code plugin](https://code.claude.com/docs/en/plugins-reference).
It adds one namespaced block, `x-agent8`, for what those formats leave out: the **data list**,
**setup questions**, **secrets by vault item name**, **requirements** and a **format version**.

Host policy — who may install what, how an agent is launched, what is trusted, how secrets are
stored — is **not** part of the format. Each host documents it in a *profile*; agent8's is
[`PROFILE-agent8.md`](PROFILE-agent8.md).

---

## 1. What is reused, exactly

| Existing format | What this spec takes | What it does not take |
|---|---|---|
| **OpenGAP `agent.yaml`** (spec v0.1.0, schema `agent-yaml.schema.json`) | The file name and its required fields `name` (`^[a-z][a-z0-9-]*$`), `version` (semver), `description`; the recommended `spec_version`; optional `author`, `license`, `tags`, `metadata`. **`extends`**, whose meaning ("this agent builds on that one; child skills shadow parent skills on a name clash; memory is not inherited") is exactly the copy/template relation. | `SOUL.md` as a requirement, a committed `memory/`, `compliance`, `model`, `runtime`. They stay allowed (OpenGAP keys are passed through untouched) but mean nothing here. |
| **AGENTS.md** | The template's main instructions, as-is. | — |
| **Agent Skills** (`SKILL.md` folders, frontmatter `name` + `description`) | Skills, as-is. Placement in each tool's folder: `.agents/skills/` (the shared location; Codex reads it) and `.claude/skills/` (Claude Code). | — |
| **`mcpServers` JSON** (Claude Code `.mcp.json`, Cursor, plugin `.mcp.json`) | MCP declarations, with `${NAME}` environment placeholders. | Shipping the file as the live config (§6). |
| **Claude Code settings** (`.claude/settings.json`: hooks, permissions) | As a *declaration* inside the template. | Shipping it as the live file (§6). |
| **Claude Code plugins** (`.claude-plugin/plugin.json`) | Export target (§11). The plugin model (read-only installed copy, updated as a whole, `userConfig` for values) is the same idea as template + own layer. | Using a plugin as the whole agent: a plugin has no identity, data boundary, setup questions or own layer. |

The OpenGAP RFC that proposes the missing pieces upstream is in [`rfcs/`](rfcs/).

---

## 2. The template

### 2.1 Layout

```
my-agent/
├── agent.yaml            REQUIRED  OpenGAP manifest + `x-agent8` block (§3)
├── AGENTS.md             REQUIRED  main instructions (§4)
├── CLAUDE.md             MAY       if present, `@AGENTS.md` (+ `@identity.md`, `@LOCAL.md`)
├── skills/               MAY       Agent Skills, one folder per skill (§5). Location set by
│   └── <name>/SKILL.md             `x-agent8.layout.skills`: `skills`, `.agents/skills` or
│                                   `.claude/skills`; if unset, the first of these that exists
├── .mcp.json             MAY       MCP servers the template declares (§6)
├── .claude/settings.json MAY       Claude Code settings the template declares (§6)
├── .codex/config.toml    MAY       Codex settings the template declares (§6)
├── seed/                 MAY       starting content for data paths (§7.3)
├── tools/ scripts/ …     MAY       code the agent or its hooks run
├── README.md             SHOULD    shown on an import page
└── LICENSE               SHOULD    without one nobody may legally reuse the template
```

### 2.2 Rules

1. **No data.** No file outside `seed/` may match the data list (§7).
2. **No secrets.** No secret values anywhere: no `.env`, no keys, no tokens. Secrets are named
   (§8), never shipped.
3. **No own-layer names at the root.** A template MUST NOT contain `identity.md`, `LOCAL.md`,
   `mcp.local.json` or `.agent8/` at its root: those belong to copies (§9). It seeds
   `identity.md` and `LOCAL.md` from `seed/` instead.
4. **Self-contained.** Symlinks are relative and stay inside the template; no absolute paths
   in declarations, hooks or MCP `command`/`args` (use `$CLAUDE_PROJECT_DIR`); no git
   submodules and no nested `.git` folders in v0.2 (another repo the agent needs is declared
   in `repos`, §3.5).
5. **No `extends` in a template** in v0.2. A template that builds on another is flattened when
   it is published (the host records the parent in its own metadata). `extends` is how a *copy*
   points at its template (§9.2).
6. **Works on its own.** A template SHOULD still run when cloned and opened directly (GitHub
   "Use this template", then `claude` or `codex` in the folder). That is why `.claude/skills`,
   `.mcp.json` and `.claude/settings.json` are allowed in it.

---

## 3. The manifest: `agent.yaml`

YAML. The top level is an OpenGAP manifest. Everything this spec adds sits in **one** key,
`x-agent8`.

```yaml
spec_version: "0.1.0"              # OpenGAP version this file also follows (recommended)
name: teo-memory-agent             # OpenGAP: ^[a-z][a-z0-9-]*$
version: 0.2.0                     # OpenGAP: semver. Releases are git tags v0.2.0
description: A Claude Code agent with durable memory.
author: Teo Dagher
license: MIT

x-agent8:
  format: "0.2"                    # REQUIRED. This spec's version (§3.2)
  layout:
    skills: .claude/skills         # where the skills are (unset: first of skills, .agents/skills, .claude/skills)
  data:                            # REQUIRED. What never travels (§7)
    - /memory/
    - /logs/
  setup:                           # asked once at install (§3.3)
    - id: owner_name
      prompt: Your name (the agent's owner)
      type: string
      required: true
  secrets:                         # vault item names (§8)
    - item: Google
      description: Google account the agent reads mail from
      fields: [refresh_token]
      env:
        GOOGLE_REFRESH_TOKEN: "{{vault:Google.refresh_token}}"
  env:                             # plain variables, no secrets (§3.6)
    OWNER_NAME: "{{answer:owner_name}}"
  repos:                           # other repos cloned once, owned by the copy (§3.5)
    - path: memory/shared-brain
      url: https://github.com/example/shared-brain
  requires:                        # what must exist before it can run (§3.4)
    harnesses:
      - name: claude-code
      - name: codex
        support: partial
        note: the Claude Code hooks are not translated to Codex, so memory rules are advice only
    tools: ["git", "python3>=3.9"]
    logins: [claude]
```

### 3.1 The `x-agent8` key

- OpenGAP's published schema sets `additionalProperties: false`, so today `opengap validate`
  rejects any extra top-level key. The RFC in [`rfcs/`](rfcs/) asks OpenGAP to accept keys
  matching `^x-` (the OpenAPI convention). Tools that read `agent.yaml` without strict
  validation already ignore it.
- `metadata` cannot carry the block: OpenGAP restricts its values to strings, numbers and
  booleans.

### 3.2 `format` — the format version

`format` is `"<major>.<minor>"` and names the version of *this* spec (`"0.2"` here). It is
independent of the template's own `version` and of OpenGAP's top-level `spec_version` (which
is why it isn't called `spec_version`). Write it quoted: unquoted, YAML reads `0.2` as a number.

- **A new minor is additive**: it only adds optional keys. A host that reads `M.N` reads every
  `M.x`. Keys it doesn't know (from a newer minor) are **ignored and listed** to the person
  ("this template also uses: …, which this server's agent8 doesn't know yet"); they never
  stop an install.
- **A new major is breaking**: a host MUST refuse a major it doesn't read, **before** writing
  anything, with a plain message, e.g. *"This server's agent8 needs updating to install this
  template (it needs format 2.0)."*
- An author (or the host that publishes a template) stamps the **lowest** format that covers
  what the template uses, so it stays installable on older hosts.

The instance record (§9.3) carries the same field, with the same rule.

### 3.3 `setup` — setup questions

Asked once, at install. Answers are **never secret** (a secret is a vault item, §8) and stay in
the copy's instance record (§9.3). They never go back to the template.

| Field | Type | Notes |
|---|---|---|
| `id` | string, `^[a-z][a-z0-9_]*$` | unique |
| `prompt` | string | the question, in plain words |
| `type` | `string` · `text` · `choice` · `multi` · `boolean` · `number` | |
| `choices` | list of strings | required for `choice` and `multi` |
| `required` | boolean | default `false` |
| `default` | matches `type` | |
| `help` | string | optional explanation |

Templates are copied byte for byte (no templating). Answers reach the agent three ways: the
agent reads them in `.agent8/instance.yaml`; **seed files** (§7.3) may contain
`{{answer:<id>}}`, replaced once when the seed is copied (seeds belong to the copy, so this
never conflicts with an update); and `env` (§3.6) may pass an answer as an environment
variable.

### 3.4 `requires`

Facts, not policy. All lists are optional.

| Field | Meaning |
|---|---|
| `harnesses` | Agent programs it works with: `{name, support?: full\|partial, note?}`. Known names: `claude-code`, `codex`, `cursor`, `gemini-cli`. The first one is the author's main target. |
| `tools` | Commands that must be on the server, optionally with a minimum version: `"python3>=3.9"`. |
| `logins` | Accounts the person must be signed in to (`claude`, `github`, …). |
| `plugins` | Claude Code plugins it needs, as `name@marketplace`. |
| `skills` | Agent Skills installed outside the template, as `owner/repo` or a URL. |

### 3.5 `repos` — other repositories the agent works in

Many agents work *in* a codebase or a shared knowledge repo they edit (a product repo, a
company "brain"). That repo is not the template: it is cloned once at install, then belongs to
the copy like data.

```yaml
repos:
  - path: brain                                   # inside the agent's folder
    url: https://github.com/example/company-brain
    ref: main                                     # optional branch, tag or commit
    required: true                                # default true
```

- `path` follows the rules of secret file targets (§8.3): relative, inside the folder, not on
  a template, own-layer or host-owned path. It MUST match the data list.
- The host clones it at install if the path is missing, with the person's own access (a
  private repo needs their login), and never touches it again: updates and rollbacks leave it
  alone, and it never leaves the copy.
- An agent whose *own folder* is the codebase it edits is not a template: split it into a
  template (instructions, skills, tools) and a `repos` entry for the codebase.

### 3.6 `env` — plain environment variables

```yaml
env:
  COLIN_CONFIG_DIR: "{{folder}}/.secrets"
  REPORT_LANGUAGE: "{{answer:language}}"
  LOG_LEVEL: info
```

Values are text with optional `{{answer:<id>}}` and `{{folder}}` (the copy's absolute path).
No secret here: secrets go in `secrets[].env`. Both kinds are given to the agent at launch and
may be used as `${NAME}` in `.mcp.json`.

---

## 4. Instructions: AGENTS.md

- The template's `AGENTS.md` is its main instructions, in the AGENTS.md format.
- It MUST NOT tell the agent to edit itself. It SHOULD say, in its own words: *"Your identity
  is in `identity.md`. Your own rules and improvements go in `LOCAL.md` and your own skills in
  `skills/`. Never edit the template files; they are replaced on every update."*
- If the template ships `CLAUDE.md`, its first line is `@AGENTS.md`, optionally followed by
  `@identity.md` and `@LOCAL.md` (Claude Code skips an import whose file is missing), and
  nothing else. Anything Claude-only goes in skills or `.claude/` files, not in `CLAUDE.md`.
- In a copy, the root `AGENTS.md` and `CLAUDE.md` are generated by the host (§6). Tools other
  than Claude Code have no import syntax, so the generated `AGENTS.md` contains the own layer's
  text, not a pointer to it.

## 5. Skills: Agent Skills

- Each skill is a folder with a `SKILL.md` whose frontmatter `name` equals the folder name and
  has a `description`.
- The template keeps them in the folder named by `x-agent8.layout.skills` (if unset: the first
  of `skills`, `.agents/skills`, `.claude/skills` that exists).
- In a copy, the host **copies** the union of the template's skills and the copy's own skills
  into **both** `.claude/skills/` and `.agents/skills/`. **A copy's own skill wins** over a
  template skill with the same name (as OpenGAP's `extends` does for skills).

## 6. Host-owned files

These files in a copy's folder are **written by the host**, at install, at every update and
whenever the own layer changes. They are never shipped to be merged, never edited by hand
(edits are lost) and never contributed back:

| File | Built from |
|---|---|
| `AGENTS.md` | the template's `AGENTS.md`, then the text of `identity.md`, then of `LOCAL.md`, each under a heading; rebuilt at every launch |
| `CLAUDE.md` | `@.agent8/template/<version>/AGENTS.md`, `@identity.md`, `@LOCAL.md` (one import per line, so Claude reads the own layer live) |
| `.claude/skills/`, `.agents/skills/` | template skills ∪ own skills, own wins |
| `.mcp.json` | template `.mcp.json` ∪ own `mcp.local.json` ∪ host entries |
| `.claude/settings.json` | template `.claude/settings.json` ∪ host entries (the copy's own settings stay in `.claude/settings.local.json`, see below) |
| `.codex/config.toml` | template `.codex/config.toml` ∪ own `mcp.local.json` servers ∪ host entries. Codex doesn't expand `${NAME}`: each server's `${NAME}` values become its `env_vars` pass-through list |

**Composition, not merging.** Every composed file is rebuilt from its sources, in order
*template → own layer → host*, with one rule for every key:
- objects merge key by key, all the way down (so `mcpServers`, `env`, `enabledPlugins` and
  hook events keep every source's entries);
- arrays concatenate in source order, exact duplicates dropped (permission lists, the hook
  handlers of an event);
- anything else: the later source wins.
There is no text merge and no conflict: the same sources always give the same file.

Claude Code already merges `.claude/settings.local.json` over `.claude/settings.json` by itself,
so the copy's own Claude settings live in `.claude/settings.local.json`, which the host never
touches. The host composes `.claude/settings.json` from the template and its own entries only.

What the host adds is its own business (the agent8 entries are in the profile).

**Changes made at run time.** Agents and tools do write into these files (`claude mcp add
--scope project` writes `.mcp.json`; a hook may rebuild `.agents/skills`). Before rebuilding, a
host MUST compare each file with what it last wrote and carry changes into the own layer where
there is a place for them (a new MCP server goes to `mcp.local.json`, a new skill folder to
`skills/`) and tell the owner about the rest, never silently drop them.

---

## 7. Data

### 7.1 The data list

`x-agent8.data` lists everything that belongs to a running agent and **never** to the
template: memory, wiki content, client files, conversations, logs, generated output. It is a
YAML list; each item is **one gitignore pattern** with these restrictions, so it can be written
verbatim into a `.gitignore` and read the same way by every tool:

- **Anchored.** Each pattern starts with `/` (relative to the agent's folder) or with `**/`
  (any depth, on purpose). `memory/` alone is refused: in gitignore it matches at any depth.
- **One pattern, nothing else.** No comments, no trailing spaces, no blank items. Comments go
  in YAML (`# …` on its own line).
- `*`, `**`, `?`, `[…]` and a trailing `/` (directories only) mean what they mean in gitignore.
- `!` negation is allowed, with gitignore's rule that a file inside an excluded directory can't
  be re-included: write `/notes/**` then `!/notes/README.md`, not `/notes/` then the negation.

What it means:
- **Template:** no file outside `seed/` may match (§2.2).
- **Install and update:** data paths are created from `seed/` and never changed or deleted by an
  update or a rollback.
- **Leaving the copy** (export, publish a new template from it): data paths never leave,
  whatever the copy's own git repo tracks.
- A copy MAY add patterns to the data list in its own `agent.yaml` (§9.2). It can never remove
  the template's patterns: the lists are unioned.
- When in doubt, it's data. Folder names count as content (`clients/acme/` is data even empty).

### 7.2 Four kinds of path in a copy

| Kind | Which paths | On update / rollback | Can leave the copy? |
|---|---|---|---|
| **Template** | `.agent8/template/<version>/` and the files mirrored from it (§9.4) | replaced by the new version | it *is* the shareable part |
| **Host-owned** | the composed files (§6) | rebuilt | never (rebuilt from sources) |
| **Own layer** | §9.1 | kept, never touched | only on purpose: when the owner publishes a new template from the copy, the host offers own skills and `LOCAL.md` rules for review, file by file |
| **Data** | the data list, `repos` paths, secret file targets, and **anything else** the agent creates | kept, never touched | never |

So a file the agent creates outside the own layer (`tools/x.py`, `notes/`) is the copy's,
like data. If a new template version adds a path where the copy already has such a file, the
host MUST refuse the switch and say which path collides, rather than overwrite it.

### 7.3 `seed/`

`seed/` mirrors the agent's folder: `seed/memory/now.md` becomes `memory/now.md`. A seed file is
copied only if the target is missing, at install **and at every version switch** (so a folder
added in a new version appears in existing copies); once copied it belongs to the copy.
Every seed path MUST match the data list or be an own-layer file (`identity.md`, `LOCAL.md`,
`mcp.local.json`).
Seeds MUST NOT contain real data. `{{answer:<id>}}` in a seed is replaced with that setup answer
when it is copied.

---

## 8. Secrets

### 8.1 Declared by vault item name

A template names the secrets it needs; it never holds one. A name is a **vault item** in the
host's vault: an item is a name plus what it stores (one value, named fields, or a JSON
document).

| Field | Notes |
|---|---|
| `item` | the vault item name: letters, digits, spaces, `_` and `-`, at most 64 characters, starting and ending with a letter, digit, `_` or `-` (`Company card` is fine; no dot, so `Item.field` reads one way); unique in the list |
| `description` | why the agent needs it, shown on an import page |
| `fields` | optional list of the fields it uses (`[secret_key]`) |
| `required` | default `true` |
| `how_to_get` | optional URL or sentence |
| `env` | optional map `ENV_NAME: "{{vault:…}}"`, given to the agent at launch: exactly one placeholder, optionally after `Bearer ` or `Basic ` (`"Bearer {{vault:Api.token}}"` works); nothing else, so no value can sit beside it |
| `files` | optional list of files written into the agent's folder from a template file (§8.3) |

Declaring an item says "this agent may need it". It is also what a host can use to narrow
what an agent may read (agent8 does so for another author's template, see the profile).

### 8.2 Placeholders

One syntax, the vault's own:

```
{{vault:Item name}}          the whole item (a JSON object; a single value as a string)
{{vault:Item name.field}}    one field
```

A template MAY use placeholders **anywhere** (instructions, skills, `.mcp.json` headers, scripts,
secret file templates, `env` values): how and where the real value is swapped in is the host's
job (agent8's placeholder engine swaps it only towards the item's allowed destinations, see the
profile). The format's one rule: **every item a template names MUST be declared in `secrets`**,
and a `field`, if the item lists `fields`, MUST be one of them. That list is what an import page
shows and what a host may limit the agent to.

`.mcp.json` may also use the standard `${NAME}` form, which Claude Code and others expand from
the environment. Every `${NAME}` in the template's `.mcp.json` MUST be declared, by a secret's
`env` or by `env` (§3.6), or be one of `CLAUDE_PROJECT_DIR`, `CLAUDE_PLUGIN_ROOT`, `HOME`. A
`${NAME}` that carries a secret MUST NOT appear in `command` or `args`: once expanded it shows
in the process list.

### 8.3 File targets

Some tools read a token file. A secret may declare:

```yaml
files:
  - path: .secrets/google-token.json        # where the file is written
    template: secret-templates/google-token.json   # template file with {{vault:…}} in it
```

- `path` MUST be relative and normalised (no `./`, no `..`, no `~`, no leading `/`), and MUST
  NOT be under `.agent8/` or `.git/`, nor a template, own-layer or host-owned path. **A secret
  target can never write outside the agent's folder** or over a file that changes what the
  agent runs. A tool that wants `~/.config/x/token.json` is pointed at the folder instead
  (an option, or `env`, §3.6).
- `template` MUST be a file in the template.
- The host writes the file readable only by the agent. It is data (§7.2).
- `agent_writes: true` says the agent itself rewrites the file (an OAuth token it refreshes,
  or obtains in a first-run sign-in). The host then writes it only when it is missing or the
  vault item has changed since, and SHOULD save the agent's version back to the vault (the
  profile says how).

---

## 9. The copy

### 9.1 The own layer

| File | Holds | Written by |
|---|---|---|
| `identity.md` | who this copy is: name, owner, mission, the owner's hard rules | seeded, then onboarding / the agent |
| `LOCAL.md` | the copy's own instructions and improvements | the agent and its owner |
| `skills/<name>/SKILL.md` | the copy's own skills (win over template skills) | the agent |
| `mcp.local.json` | the copy's own MCP servers | the agent or the host's app |
| `.claude/settings.local.json` | the copy's own Claude Code settings | Claude Code, the agent |
| `agent.yaml` | the copy's own manifest (§9.2) | the host at install; the owner may rename |

The template's skills stay under `.agent8/template/<version>/` and do not collide with the
copy's own `skills/`. A copy MAY be a git repository of its own (the owner's choice); the format
never requires it.

### 9.2 The copy's `agent.yaml`

A copy's manifest is shaped as an OpenGAP agent that `extends` its template. Pinning an exact
version with `@` is this spec's addition (OpenGAP's `extends` is an unpinned git URL or path;
the RFC proposes the pin), and the copy does not edit its parent's files as OpenGAP children
may (§10 replaces OpenGAP's merge rules with the layer model):

```yaml
name: sams-memory-agent
version: 0.0.1
description: Sam's memory agent
extends: https://github.com/Teodagher/teo-agent-boilerplate@0.2.0
x-agent8:
  format: "0.2"
  data:
    - /exports/          # the copy may add data patterns; it can't remove the template's
```

`extends` is `<source>@<version>`:
- `<version>` is an **exact** semver (no ranges): the copy points at one immutable version.
- `<source>` is a git URL (`https://…`, `git@host:owner/repo`), `github:owner/repo`, or a
  host scheme (agent8 uses `agent8:<workspace>/<template>`, see the profile).
- The string is split on its **last** `@`.

The copy's `x-agent8` block may add `data` patterns, `secrets` and `requires`; it never changes
`setup` (answers are in the instance record).

### 9.3 The instance record: `.agent8/instance.yaml`

Written by the host at install, updated at every update and rollback. Never contains a secret
value.

```yaml
format: "0.2"
template:
  source: https://github.com/Teodagher/teo-agent-boilerplate
  version: 0.2.0
  digest: sha256:9f2c…               # of the installed template files
  commit: 0eb0f71c…                  # optional: the git commit it came from
  id: 3b1d…                          # optional: the host's id for this version
previous:                            # optional: what a rollback returns to
  version: 0.1.0
  digest: sha256:41aa…
installed_at: 2026-11-06T15:00:00Z
updated_at: 2026-11-06T15:00:00Z
answers:
  owner_name: Sam
secrets:                             # status only, never values
  - item: Google
    status: present                  # present | missing
```

`template.source` and `template.version` MUST equal the copy's `extends`. Answers to questions
the current version doesn't ask are kept (they come back after a rollback). `digest` is the
sha256 of the sorted lines `<path>\0<sha256 of the file>\n` for every file of the template
version (a symlink hashes as `link:<target>`), so anyone can recompute it and a host can tell
when the read-only copy was edited by hand.

### 9.4 Folder of a copy

```
sams-memory-agent/
├── .agent8/
│   ├── instance.yaml                 instance record
│   └── template/0.2.0/               the template, read-only, byte for byte
├── agent.yaml                        own layer: extends …@0.2.0
├── identity.md  LOCAL.md  skills/  mcp.local.json  .claude/settings.local.json   own layer
├── memory/ …                         data, seeded once
├── AGENTS.md  CLAUDE.md  .claude/skills/  .agents/skills/
└── .mcp.json  .claude/settings.json  .codex/config.toml                  host-owned
```

**Every other template file is mirrored** at its own relative path in the copy's folder, as a
read-only **copy** (not a symlink: scripts that find their folder with `Path(__file__).resolve()`
must land in the copy, not in `.agent8/`): `tools/memory.py`, `templates/…`, `.claude/rules/…`. So hooks written as `$CLAUDE_PROJECT_DIR/tools/memory.py`
keep working, exactly as when the template is opened directly. Not mirrored: the files the
host composes (§6), the template's skills folder (its skills are placed per §5), the template's `agent.yaml` (the copy has its own) and `seed/`. Mirrored
paths are host-owned: the agent changes behaviour through its own layer, not by editing them.
A mirrored path that collides with a data or own-layer path is an error in the template.

---

## 10. Update and rollback

1. The host fetches the new version and installs it **beside** the old one, under
   `.agent8/template/<new>/`.
2. It refuses the switch if a new template path collides with a file of the copy (§7.2), and
   shows what changed in plain words (files, instructions, skills, MCP servers, hooks, setup
   questions, secrets), asking any **new** setup question.
3. It replaces the mirrored files, copies missing seeds (§7.3), regenerates the host-owned
   files, rewrites `extends` and the instance record (the old version goes to `previous`) and
   restarts the agent when it is idle.
4. **Rollback** is the same switch in reverse. Data and the own layer are never touched by
   either.

There is no three-way merge. An edit made by hand inside `.agent8/template/` is lost at the
next switch; a host SHOULD warn about it.

## 11. Claude Code plugin export

A template can be packaged as a [Claude Code plugin](https://code.claude.com/docs/en/plugins-reference),
for people who want its capabilities in an agent they already have. The export is one folder
holding the plugin and a one-plugin marketplace beside it (`.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json`, the entry's `source` being `"./"`), so it installs with
`/plugin marketplace add ./<folder>` then `/plugin install <name>@agent8-<name>`.
[`tools/agentfmt.py plugin`](tools/agentfmt.py) is the reference (`tools/claude_plugin.py`).

| Template | Plugin |
|---|---|
| `name`, `version`, `description`, `author`, `license`, `tags` | `.claude-plugin/plugin.json` `name`, `version`, `description`, `author: {name}`, `license`, `keywords`. A name Claude Code reserves (`claude-…`, `anthropic-…`, `claude`…) gets `agent-` in front |
| skills (the `layout` folder) | `skills/<name>/`, whole folders |
| `AGENTS.md`, then each `.claude/rules/*.md` | one skill named after the plugin (`<name>-instructions` if a skill has that name): plugins don't load a `CLAUDE.md` or rules. It ends with the setup answers as `${user_config.<id>}` |
| `.claude/agents/**/*.md` | `agents/**` as-is (plugins ignore `permissionMode`, `hooks`, `mcpServers`, `initialPrompt` there; the README lists them) |
| `.claude/commands/**/*.md` | `commands/**` |
| `.claude/settings.json` `hooks` | `hooks/hooks.json` (`{"hooks": …}`) |
| `.mcp.json` | `.mcp.json`; `${NAME}` filled from `env` and secrets as below |
| secrets: each `env` variable | a `userConfig` entry keyed by the variable's name, `sensitive: true`, `required` as declared; `${NAME}` becomes the env value with `{{vault:…}}` replaced by `${user_config.NAME}` (so `Bearer ${user_config.NAME}`) |
| non-secret setup questions | `userConfig` entries keyed by `id` (`answer_<id>` if it clashes with a secret): `string`/`text` → `string`; `number`, `boolean` as-is; `choice` → `options` (required when there's no default); `multi` → `string` with `multiple: true` |
| plain `env` | inlined where `.mcp.json` uses it: `{{answer:<id>}}` → `${user_config.<id>}`, `{{folder}}` → `${CLAUDE_PROJECT_DIR}` |
| `$CLAUDE_PROJECT_DIR/<path>`, `${CLAUDE_PROJECT_DIR}/<path>`, `"$CLAUDE_PROJECT_DIR"/<path>` in hooks and MCP servers | `${CLAUDE_PLUGIN_ROOT}/<path>` when the path came with the plugin; otherwise unchanged (it still means the project) |
| other files (`tools/`, `.claude/hooks/`, `LICENSE`…) | copied as-is, modes kept |
| `README.md` | a generated README (install, what's inside, secrets as `${NAME}`, what stayed behind), the template's own README at the end |

**Not exported:** `agent.yaml`, `CLAUDE.md`; the data list and `seed/`; the own layer
(`identity.md`, `LOCAL.md`, `mcp.local.json`, `.agent8/`, `.claude/settings.local.json`); token
file templates (`secrets[].files[].template`); links; the skills mirrored for another tool;
`.codex/`; Claude Code settings other than hooks (permissions, `env`, `statusLine`…, which
plugins can't set); and any template file that would land on a path that means something at a
plugin's root (`skills/`, `agents/`, `commands/`, `hooks/hooks.json`, `settings.json`,
`.claude-plugin/`, `monitors/`, `themes/`…). Secret file targets, `repos` and `requires` are
listed in the README for the person to provide.

**Never secrets.** The export refuses a template holding a file that looks like a key file,
and scans every byte it writes with the format's secret checks (§8): any hit refuses the whole
export, never a partial plugin.

The plugin is read-only and updated as a whole, like a template version.

## 12. Reading OpenGAP repos without the block

A host SHOULD import an OpenGAP repo that has no `x-agent8` block, as an unverified template.
The reference reading is `tools/importer.py` (`agentfmt import` and `agentfmt install` use it);
agent8 reads the same way, and a test holds the two to the same result.

- **`extends`:** the parent is fetched and flattened with OpenGAP's own rules (§15 of its
  spec): manifests deep-merged with the child winning, the child's `SOUL.md` replacing the
  parent's, `RULES.md` parent then child, `skills/` and `tools/` united with the child's entry
  winning by name; `memory/` and the parent's other files are not inherited. At most three
  levels; GitHub repositories only for now. An `extends` that isn't followed is said.
- **Instructions:** `SOUL.md`, `RULES.md`, `DUTIES.md`, then `AGENTS.md` and `CLAUDE.md`'s own
  words, concatenated in that order, then sections written from the rest: `compliance` as
  rules in words, `knowledge/` (what `knowledge/index.yaml` says to read first, then the
  others), `tools/*.yaml` as scripts the agent runs itself, sub-agents (`agents` and
  `agents/`), `workflows/`, and where to keep memory.
- **Data:** `/memory/` and `/.gitagent/` (the original agent's) are left out; `/knowledge/`
  is data too, but its files are the agent's reference documents, so they are shipped as
  seeds (`seed/knowledge/…`): every copy starts with them and owns them. Plus the usual
  data folders and files of keys.
- **Skills:** `skills/` (or `.agents/skills`, `.claude/skills`). `tools/`, `hooks/`,
  `workflows/`, `agents/`, `config/` are kept as files.
- **`mcp_servers`** becomes `.mcp.json` (unless the repo has one); a server with a variable or
  an absolute path on its command line is left out. Each `${NAME}` of `.mcp.json` and each
  key-like name in `.env.example` is declared as a secret (`required: false`) given at launch.
- `setup` is empty; the author can add the block later.
- Kept in `agent.yaml` but not acted on, and said so on import: `model`, `runtime`,
  `hooks/hooks.yaml`, `dependencies`, `delegation`, `a2a`, `registries`, `config/`,
  `compliance` (written as rules, not enforced), `tools/` (not registered as tools).
- Refused: no `SOUL.md`, `RULES.md`, `AGENTS.md` or `CLAUDE.md`; a key in `agent.yaml`.

## 13. Conformance

A **template** conforms when: `agent.yaml` validates against
[`schema/manifest.schema.json`](schema/manifest.schema.json); `AGENTS.md` exists; every rule of
§2.2, §7 and §8 holds; every skill folder has a valid `SKILL.md`. A **copy** conforms when its
`agent.yaml` has a valid `extends`, `.agent8/instance.yaml` validates against
[`schema/instance.schema.json`](schema/instance.schema.json) and matches `extends`, the template
version is present under `.agent8/template/<version>/`, and every required setup question has
an answer. [`tools/validate.py`](tools/validate.py) checks both.

## 14. Changes from v0.1

- Copier-style three-way merge, pull and contribute → read-only template + own layer, update
  = switch version.
- Own manifest `forkable.yaml` → OpenGAP `agent.yaml` + `x-agent8`.
- `.agentdata` gitignore file (whose trailing `#` comments were invalid gitignore) → anchored
  patterns inside the manifest.
- Secrets with targets anywhere (`~/.config/…`) → vault item names, `{{vault:Item.field}}`
  placeholders, file targets inside the agent's folder only.
- `providers/<id>/` extras copied into live folders → host-owned files composed by the host.
- `code`, `permissions` and trust rules → out of the format, into host profiles.
- Added: the format version rule, the own layer, the instance record by version, plugin export.

## 15. Open questions

1. **Name.** The format has no name yet; the public repo needs one (Teo).
2. **Sidecar file.** Until OpenGAP accepts `x-` keys, should the block also be allowed in a
   separate `agent.x-agent8.yaml`, so strict `opengap validate` passes?
3. **`SOUL.md`.** OpenGAP requires it. Ship a one-line `SOUL.md` pointing at `AGENTS.md`, or
   ask OpenGAP to make it optional when `AGENTS.md` exists (the RFC asks)?
4. **`knowledge/` as data.** Reference documents are often part of a template. The ticket says
   data; a template author may want to keep some (`!/knowledge/…` works today).
5. **Codex.** Codex has no local-override file like `settings.local.json`; the own layer needs
   a name for it (`.codex/config.local.toml`?). Codex hooks (`.codex/hooks.json`) and agents
   (`.codex/agents/`) are mirrored as template files for now; whether they should be composed
   like `.claude/settings.json` is open.
6. **Multi-agent templates** (a team in one repo, OpenGAP `agents/`): out of scope for v0.2.
7. **Signing** versions (Sigstore, signed tags) before a public marketplace.
8. **Launch recipe.** The adopted decision lists "how it starts" in the template; this draft keeps
   the launch command in the host's recipe (profile §9). Some agents need flags (for example
   channels loaded at start); should `requires.harnesses` carry extra launch arguments?
9. **Plugins from other marketplaces.** `requires.plugins` names `name@marketplace` but not where
   the marketplace lives; plugin-managed secrets outside the folder can't be declared.
