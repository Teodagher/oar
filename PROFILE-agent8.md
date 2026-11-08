# agent8 host profile for OAR (Open Agent Recipe) v0.2

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

How agent8 does it (helper 1.56, T-143):
- Nothing from the template runs, and nothing is installed from a package manager, before the
  owner presses **Trust and start**. Plugins are listed, never installed.
- The server reads the version from the board (`template_download_info`, its own sign-in only),
  refuses a format major it doesn't read before writing anything, downloads the parts through
  the signed links and checks each part's sha256 and the archive's against the board.
- The archive is unpacked in memory: no `..`, no absolute path, no link that leaves the template,
  no link under a link, no hard link, device or `.git`. Files are written as the agent's account
  into a new, empty folder, every folder opened without following a link, every file created new.
- Other repositories are cloned first (git only: no submodules, no local or `ext::` transports,
  https or ssh addresses without credentials). A required one that fails stops the install and
  the folder is emptied again.
- The agent starts with the app's recipe (the first harness the template names, bypass by
  default), the template's plain `env` in front of the command. Then `template_install_bind`
  records the version, writes the declared names and the scope into the agent's vault settings
  and binds the declared `env` names to vault items that exist.

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

How agent8 does it (helper 1.58, T-144):
- The person starts a switch on the board (`template_update_begin`): an update only goes to a
  higher version number (semver; a version published later with a lower number is never an
  update), a rollback only to the version the agent ran just before. The version must be of the
  same template and one the person may use (their workspace, the live share link the agent came
  from, or a version the agent already ran).
- The server reads the switch from the board (`template_download_info`: the agent, its old version
  and the old manifest), downloads the new version with the install's checks, and, as the agent's
  account, shows everything that would change: every template file with its whole diff (hidden
  characters shown as `⟨U+…⟩`, nothing masked, long diffs paged in full on request), what happens
  in the folder (files replaced or removed, host files rebuilt, skills, missing seeds, new
  repositories, `extends`), hand edits of the read-only copy and of the host files, and any path
  that would land on the copy's own files (the switch is refused). A fingerprint of all of it is
  sent back with **Trust and update**; anything different at that moment refuses the switch.
- The "before" side is the board's archive of the version the agent runs now, never the agent's own
  copy (which is only compared, as a hand edit). Answers are kept only for questions that version
  asks.
- The old files are moved aside into `.agent8/previous/<when>_<from>_to_<to>/` (the last five
  switches are kept). A journal there puts the folder back on any failure, and at the next look if
  the process died halfway. The new version is written beside the old one; the two most recent versions
  stay. The own layer and data are never written; MCP servers added to `.mcp.json` at run time are
  kept in the rebuilt file. The recipe's plain `env` follows the new version unless its owner
  changed the command. The agent restarts at its next idle moment.
- Auto-update is off by default per agent. When its owner turns it on, the server asks the board
  every 30 minutes; a version with a new required question or a new vault name, hand edits or a
  colliding path waits for a person.

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
