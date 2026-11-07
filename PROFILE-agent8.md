# agent8 host profile for the agent template format v0.2

The [format](SPEC.md) says what a template and a copy *are*. This profile says what **agent8**
does with them: hosting, launch, trust, the vault and the files it composes. Another host can
implement the format with a different profile. Nothing here is needed to write a template.

Decisions behind it (agent8 repo): template plus own layer, where templates live, the company
vault, vault items are objects, vault placeholders, helper capabilities and compatibility,
autonomy first, one account per agent (all 2026-11-06).

## 1. Format support

- The helper reports the formats it reads in its capability list
  (`"template-install": {…, "spec": ["0.2"]}`, helper compatibility decision, 2026-11-06). A
  template whose major it doesn't read is refused before anything is written, and the app shows
  *"This server's agent8 needs updating to install this template"* with the Update button. A
  newer minor installs; the keys the helper doesn't know are listed on the import screen.
- The board stores `format` with each template version, so the app can warn before an import
  is even sent to a server whose helper is too old. Making a template (T-142) stamps the lowest
  format that covers what it uses.

## 2. Sources and hosting

- `extends` sources agent8 writes: `agent8:<workspace-slug>/<template-name>@<version>` for
  versions it hosts, the GitHub URL for imports from GitHub.
- Every version is immutable: a manifest row in `agent_template_versions` (with `format`,
  `sha256`, the source commit if any) and an archive in the private bucket `agent-templates`,
  in parts of at most 40 MB, fetched through signed links valid for one import.
- Imports from a git link are fetched as GitHub's tarball of one commit (other hosts: by the
  recipient's helper), checked with the same rules as `tools/validate.py`, and stored as an
  agent8 version that records the commit.

## 3. Install

1. The app shows the preview: name, description, author, licence, verified badge, what it
   contains (instructions, skills, MCP servers, hooks, scripts it found), the vault items it
   declares, the setup questions and the requirements.
2. Setup answers are collected in the app; missing vault items are offered to add.
3. The helper writes the folder of SPEC §9.4:
   - `.agent8/template/<version>/` owned by **root** and not writable when the agent has its
     own Linux account (`a8-<name>`); `chmod a-w` on the shared `agent8` account (which the
     agent could undo — the app says so);
   - the mirrored template files as read-only copies (never symlinks), seeds, the own layer,
     the copy's `agent.yaml`, `.agent8/instance.yaml`;
   - each `repos` entry, cloned with the person's own GitHub connection or the server's git
     access; a private repo the person can't read stops the install with a plain message;
   - the host-owned files (§5 below).
4. The board records `user_agents.template_version_id`.

## 4. Trust (autonomy first)

- Imports are **trust-based**, like installing an app: no forced "ask first" mode, no extras
  held back, no sandbox by default. The agent runs with the same permission recipe as the
  owner's other agents (bypass by default).
- The protections that stay on: no secret is ever written into a template or a share link; a
  template never carries data; secret file targets stay inside the agent's folder; every vault
  read is logged.
- Real isolation is the agent's own Linux account (opt-in, M24); a sealed mode may come later.

## 5. Composed files: agent8's entries

agent8 adds, after the template and the own layer (SPEC §6):
- `.mcp.json`: the `agent8` MCP server (vault tools, channels, AgentCom), always present.
- `.claude/settings.json`: the permission recipe of the agent (bypass by default) and agent8's
  own hooks, if any. Entries the template declares stay.
- `.codex/config.toml`: the same `agent8` MCP server; every `${NAME}` of a server becomes its
  `env_vars` list, since Codex doesn't expand placeholders.
- Before each rebuild, the helper compares the files with what it last wrote. A server added to
  `.mcp.json` (for example by `claude mcp add --scope project`) moves to `mcp.local.json`; other
  edits are listed on the agent's page ("changed by hand, will be rebuilt").

## 6. Vault

- **Scope.** An agent installed from **another author's** template (share link or marketplace)
  can read only the vault items its template and its own `agent.yaml` declare. The import
  screen shows the list with a switch "give it the whole vault"; nobody is prompted. Copies of
  your own templates read the whole workspace vault. A take-down of a version cuts its copies
  off.
- **Placeholders.** `{{vault:Item name.field}}` written anywhere in the template or by the agent is
  swapped by agent8 (network relay, agent8 tools, browser, or local hand-off with masked output),
  only towards the item's allowed destinations, and logged (vault placeholders decision). The
  template's `secrets` list is what such an agent may name when its vault scope is `declared`.
- **`env`.** At launch the helper fetches each declared `env` value through `vault_fetch`,
  writes them to a file readable only by the agent's account, the launch reads it and deletes
  it. Never through the command line or `tmux -e` (both show in the process list).
- **`files`.** Rendered at launch from the template file, written `0600` (owner-only) at the
  declared path inside the agent's folder, refreshed when the item changes, removed when the
  item is revoked. With `agent_writes: true` the helper writes it only if it is missing or the
  item changed since; when the agent rewrites it (a refreshed token), the helper saves it back
  as a new version of the item if agents may update that item (items an agent created), and
  otherwise shows "needs saving to the vault" on the agent's page.
- **Plain `env`.** `{{folder}}` and `{{answer:…}}` filled in at launch, same file as the secret
  variables.
- Missing required items: the agent still starts; the app shows *"needs Google"* on its row
  and the instance record says `status: missing`.

## 7. Update

- *"A new version is available"* on the agent's page. The app shows the change in plain words
  (SPEC §10), asks any new setup question and offers new vault items.
- The helper installs beside, regenerates, restarts the agent when it is idle (same quiet-moment
  rule as the helper's own updates) and keeps the previous version for a one-tap rollback.
- A file edited by hand under `.agent8/template/` is reported in the Files tab ("from
  template, read-only") and lost at the next switch.

## 8. Making a template

Not part of the format (it produces a template): on a copy, never on the live agent; anything
unsure left out; the author reviews every file; personal details become setup questions;
secrets found become declared vault items; folder names count as content. The data list of the
new template is generated from what was left out, with anchored patterns.

How agent8 does it (helper 1.55, T-142):
- Every file is read and copied as the agent's own Linux account, into a draft in that account's
  `~/.cache/agent8/template-drafts/`; the agent's folder is never written. A folder that is the
  account's home, the whole server or an installed copy can't be a template; a codebase gets
  nothing ticked ("pick by hand").
- `.mcp.json` and `.claude/settings.json` are regenerated, failing closed: agent8's own entries
  out, every env and header value turned into `${NAME}`, anything that might be a key (a known
  shape, a long value given to a secret-sounding name, a random-looking word) left out.
  `CLAUDE.md` is the import line; `AGENTS.md` is built from the agent's instructions.
- An optional pass lets Claude, as the agent's account and with edits allowed only in the draft,
  turn personal details into setup questions; the author sees the diff.
- At publishing, every byte kept is scanned again; a key blocks. The archive is a gzip'd tar
  (deterministic: sorted, times and owners zeroed) of `agent.yaml` plus the kept files at their
  template paths, cut into parts of 40 MB; parts go up with the server's own sign-in through the
  `templates` edge function.

## 9. Launch

How an agent is started (the command, `claude` or `codex`, flags, tmux session) stays in the
agent's recipe on the board, as for every agent8 agent. The template only says which harnesses
it works with (`requires.harnesses`); the first one is the default choice in the app.
