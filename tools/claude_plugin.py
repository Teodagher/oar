"""Export a template as a Claude Code plugin (SPEC §11).

    plugin_files(files, manifest) -> (out, info)

`files` is a template held in memory, as agentfmt reads it: path -> {"kind": "file", "data",
"mode"} | {"kind": "link", "target"} | {"kind": "dir"}. `out` is the plugin: path ->
(bytes, mode), with `.claude-plugin/plugin.json` and a one-plugin `marketplace.json` beside
it, so the folder installs with `/plugin marketplace add ./<folder>` then `/plugin install`.

The same mapping runs on agent8's server (backend/share/plugin.ts) for the web's "Export as
Claude plugin": the two give the same bytes for the same template, and a test checks it.
Change both together.

Nothing secret ever goes in: data, seeds, the own layer, token-file templates and links stay
out; secrets become `${user_config.NAME}` placeholders that Claude Code asks for; and every
file written is scanned again with the format's secret checks (any hit refuses the export).
"""
from __future__ import annotations

import json
import re

import validate as v

RESERVED_PREFIX = ("claude-", "anthropic-", "anthropics-", "cc-plugin-")
RESERVED_EXACT = {"claude", "anthropic", "anthropics", "claude-code", "claude-mods"}
VENDOR_WORDS = {"claude", "anthropic", "anthropics"}
# Paths that mean something to Claude Code at a plugin's root: a template file landing there
# as-is would quietly become a plugin part, so it stays out.
PLUGIN_PARTS = ("skills/", "agents/", "commands/", "hooks/hooks.json", ".claude-plugin/",
                "settings.json", ".mcp.json", ".lsp.json", "monitors/", "output-styles/",
                "themes/", "workflows/", "README.md")
MAPPED = ("agent.yaml", "AGENTS.md", "CLAUDE.md", "README.md", ".mcp.json", ".claude/settings.json")
OWN_ROOT = ("identity.md", "LOCAL.md", "mcp.local.json")
AGENT_IGNORED = ("permissionMode", "hooks", "mcpServers", "initialPrompt")
# `$CLAUDE_PROJECT_DIR/x`, `${CLAUDE_PROJECT_DIR}/x`, and the quoted `"$CLAUDE_PROJECT_DIR"/x`.
PROJECT_PATH_RE = re.compile(r"\$(\{CLAUDE_PROJECT_DIR\}|CLAUDE_PROJECT_DIR)(\"?)/([A-Za-z0-9._@+/-]+)")
FM_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)[ \t]*:", re.M)
LEFT_OUT_SHOWN = 100


class ExportRefused(Exception):
    pass


def plugin_name(name: str) -> str:
    low = name.lower()
    words = {w for w in re.split(r"[-_.]+", low) if w}
    if "official" in words and words & VENDOR_WORDS:
        raise ExportRefused(f"The name {name!r} reads as an official Claude plugin: rename the template first.")
    if low.startswith(RESERVED_PREFIX) or low in RESERVED_EXACT:
        return "agent-" + name
    return name


def dump(obj) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def text_of(e) -> str:
    return e["data"].decode("utf-8", "replace")


def one_line(s) -> str:
    return " ".join(str(s or "").split())


def sentence(s) -> str:
    s = one_line(s)
    return s if not s or s[-1] in ".!?" else s + "."


def cell(s) -> str:
    return one_line(s).replace("|", "\\|")


def walk_strings(obj, fn):
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [walk_strings(x, fn) for x in obj]
    if isinstance(obj, dict):
        return {k: walk_strings(x, fn) for k, x in obj.items()}
    return obj


def frontmatter_keys(text: str) -> list:
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end == -1:
        return []
    return FM_KEY_RE.findall(text[3:end])


def json_file(files, path):
    e = files.get(path)
    if not e or e.get("kind") != "file":
        return None
    try:
        doc = json.loads(e["data"].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ExportRefused(f"{path} isn't valid JSON, so it can't be carried over.")
    if not isinstance(doc, dict):
        raise ExportRefused(f"{path} isn't a JSON object, so it can't be carried over.")
    return doc


def plugin_files(files: dict, manifest: dict):
    if not isinstance(manifest, dict):
        raise ExportRefused("This template has no manifest.")
    block = manifest.get("x-agent8")
    if not isinstance(block, dict):
        raise ExportRefused("This template has no x-agent8 block, so it can't be exported.")
    fmt = block.get("format")
    if not isinstance(fmt, str) or not re.fullmatch(r"0\.(0|[1-9]\d*)", fmt):
        raise ExportRefused("This template's format isn't one this exporter reads (0.x).")
    tname = manifest.get("name")
    version = manifest.get("version")
    if not isinstance(tname, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", tname) or len(tname) > 64:
        raise ExportRefused("This template's name isn't a plain lowercase name.")
    if not isinstance(version, str) or not v.SEMVER_RE.match(version):
        raise ExportRefused("This template's version isn't a version number.")
    description = one_line(manifest.get("description"))
    author = one_line(manifest.get("author")) if isinstance(manifest.get("author"), str) else ""
    plugin = plugin_name(tname)
    market = "agent8-" + plugin

    data_patterns = [p for p in (block.get("data") or []) if isinstance(p, str)]
    data = v.DataList(data_patterns)
    layout = (block.get("layout") or {}).get("skills") if isinstance(block.get("layout"), dict) else None
    if layout not in v.SKILL_LAYOUTS:
        layout = next((c for c in v.SKILL_LAYOUTS
                       if any(p.startswith(c + "/") for p, e in files.items() if e.get("kind") == "file")),
                      "skills")
    secrets = [s for s in (block.get("secrets") or []) if isinstance(s, dict)]
    secret_templates = set()
    for s in secrets:
        for f in s.get("files") or []:
            if isinstance(f, dict) and isinstance(f.get("template"), str):
                secret_templates.add(f["template"])

    out, left, skills, agents, commands, rules, codex = {}, [], {}, [], [], [], False
    kept = {}
    for p in sorted(files):
        e = files[p]
        kind = e.get("kind")
        if kind == "dir":
            continue
        if kind == "link":
            left.append((p, "a link (plugins carry plain files)"))
            continue
        if p in MAPPED:
            continue
        top = p.split("/")[0]
        if p.startswith("seed/"):
            left.append((p, "starting content for the agent's data"))
        elif p in OWN_ROOT or p.startswith(".agent8/") or p == ".claude/settings.local.json":
            left.append((p, "the agent's own layer"))
        elif data.matches(p):
            left.append((p, "the agent's data"))
        elif p in secret_templates:
            left.append((p, "a token file template"))
        elif v.SECRET_FILE_RE.search(p):
            raise ExportRefused(f"{p} looks like a key file: take it out of the template first.")
        elif any(p.startswith(c + "/") for c in v.SKILL_LAYOUTS):
            if p.startswith(layout + "/"):
                rest = p[len(layout) + 1:]
                if "/" not in rest:
                    left.append((p, "not inside a skill folder"))
                else:
                    skills.setdefault(rest.split("/")[0], []).append(p)
                    out["skills/" + rest] = (e["data"], e.get("mode") or 0o644)
            else:
                left.append((p, "the same skills, for another tool"))
        elif top == ".codex":
            codex = True
            left.append((p, "Codex settings"))
        elif p.startswith(".claude/agents/") and p.endswith(".md"):
            agents.append(p)
            out["agents/" + p[len(".claude/agents/"):]] = (e["data"], 0o644)
        elif p.startswith(".claude/commands/") and p.endswith(".md"):
            commands.append(p)
            out["commands/" + p[len(".claude/commands/"):]] = (e["data"], 0o644)
        elif p.startswith(".claude/rules/") and p.endswith(".md"):
            rules.append(p)
        elif any(p == x or (x.endswith("/") and p.startswith(x)) for x in PLUGIN_PARTS):
            left.append((p, "it would turn into a part of the plugin"))
        else:
            kept[p] = e
            out[p] = (e["data"], e.get("mode") or 0o644)

    kept_dirs = {"/".join(p.split("/")[:i]) for p in kept for i in range(1, p.count("/") + 1)}

    def to_root(s: str) -> str:
        def sub(m):
            path = m.group(3)
            bare = path.rstrip("/")
            if bare in kept or bare in kept_dirs:
                return "${CLAUDE_PLUGIN_ROOT}" + m.group(2) + "/" + path
            return m.group(0)
        return PROJECT_PATH_RE.sub(sub, s)

    # Secrets: each environment variable a secret fills becomes a sensitive setting.
    user_config, env_map, secret_rows, token_files, unnamed = {}, {}, [], [], []
    for s in secrets:
        item = one_line(s.get("item"))
        env = s.get("env") if isinstance(s.get("env"), dict) else {}
        for name in env:
            val = env[name]
            if not isinstance(val, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                continue
            m = v.VAULT_RE.search(val)
            field = m.group(2) if m else None
            env_map[name] = v.VAULT_RE.sub("${user_config.%s}" % name, val)
            why = sentence(s.get("description")) or f"From the vault item {item}."
            how = one_line(s.get("how_to_get"))
            user_config[name] = {
                "type": "string",
                "title": f"{item} ({field})" if field else item,
                "description": why + (f" How to get it: {how}" if how else ""),
                "sensitive": True,
                "required": s.get("required") is not False,
            }
            secret_rows.append((name, item, field, why, how))
        for f in s.get("files") or []:
            if isinstance(f, dict) and isinstance(f.get("path"), str):
                token_files.append((f["path"], item))
        if not env and not s.get("files"):
            unnamed.append((item, one_line(s.get("description"))))

    secret_env = set(env_map)
    secret_upper = {n.upper() for n in env_map}
    setup_rows, answer_key = [], {}
    for q in block.get("setup") or []:
        if not isinstance(q, dict) or not isinstance(q.get("id"), str):
            continue
        key = q["id"] if q["id"].upper() not in secret_upper else "answer_" + q["id"]
        qtype = q.get("type") or "string"
        prompt = one_line(q.get("prompt")) or q["id"]
        desc = one_line(q.get("help")) or prompt
        entry = {"type": {"boolean": "boolean", "number": "number"}.get(qtype, "string"),
                 "title": prompt, "description": desc}
        required = q.get("required") is True
        choices = [c for c in (q.get("choices") or []) if isinstance(c, str)]
        if qtype == "choice":
            if choices and all(1 <= len(c) <= 64 for c in choices):
                entry["options"] = choices
                if q.get("default") is None:
                    required = True
            elif choices:
                entry["description"] = desc + " Choices: " + ", ".join(choices) + "."
        elif qtype == "multi":
            entry["multiple"] = True
            if choices:
                entry["description"] = desc + " Choices: " + ", ".join(choices) + "."
        if required:
            entry["required"] = True
        if q.get("default") is not None:
            entry["default"] = q["default"]
        user_config[key] = entry
        setup_rows.append((key, prompt, required))
        answer_key[q["id"]] = key

    # Plain variables: answers become settings, the agent's folder becomes the project.
    env_block = block.get("env") if isinstance(block.get("env"), dict) else {}
    for name, val in env_block.items():
        if not isinstance(val, str) or name in env_map:
            continue
        val = re.sub(r"\{\{answer:([a-z][a-z0-9_]*)\}\}",
                     lambda m: "${user_config.%s}" % answer_key.get(m.group(1), m.group(1)), val)
        env_map[name] = val.replace("{{folder}}", "${CLAUDE_PROJECT_DIR}")

    def fill_env(s: str) -> str:
        return v.ENV_REF_RE.sub(lambda m: env_map.get(m.group(1), m.group(0)), s)

    # MCP servers.
    servers = []
    mcp = json_file(files, ".mcp.json")
    if mcp is not None:
        mcp = walk_strings(mcp, lambda s: to_root(fill_env(s)))
        servers = sorted((mcp.get("mcpServers") or {}).keys()) if isinstance(mcp.get("mcpServers"), dict) else []
        out[".mcp.json"] = (dump(mcp), 0o644)

    # Hooks; the other Claude Code settings don't travel in a plugin.
    hook_count, hook_events, settings_left = 0, [], []
    settings = json_file(files, ".claude/settings.json")
    if settings is not None:
        hooks = settings.get("hooks")
        if isinstance(hooks, dict) and hooks:
            hooks = walk_strings(hooks, to_root)
            out["hooks/hooks.json"] = (dump({"hooks": hooks}), 0o644)
            hook_events = list(hooks)
            for groups in hooks.values():
                for g in groups if isinstance(groups, list) else [groups]:
                    hs = g.get("hooks") if isinstance(g, dict) else None
                    hook_count += len(hs) if isinstance(hs, list) else 1
        settings_left = sorted(k for k in settings if k != "hooks")

    # The instructions: AGENTS.md and the rules, as one skill (plugins don't load CLAUDE.md).
    instructions = None
    agents_md = files.get("AGENTS.md")
    if (agents_md and agents_md.get("kind") == "file") or rules or setup_rows:
        for cand in (plugin, plugin + "-instructions", plugin + "-agent-instructions"):
            if cand not in skills:
                instructions = cand
                break
        if instructions is None:
            raise ExportRefused("The template's skills already use every name the instructions could take.")
        what = (f"How the {tname} agent works: its instructions" + (f" ({description.rstrip('.')})" if description else "")
                + f". Use this before doing {tname}'s work or acting as {tname}.")
        body = ["---", f"name: {instructions}", "description: " + json.dumps(what[:1024], ensure_ascii=False),
                "---", "",
                f"These are the instructions of the {tname} agent ({version}), packaged as a Claude Code plugin. "
                "Files they call the agent's own (identity.md, LOCAL.md, its memory and data) don't come "
                "with the plugin: where they're missing, ask the person you're working with.", ""]
        if agents_md and agents_md.get("kind") == "file":
            body += [text_of(agents_md).strip(), ""]
        for r in rules:
            body += [f"## Rules from {r[len('.claude/rules/'):]}", "", text_of(files[r]).strip(), ""]
        if setup_rows:
            body += ["## Your settings", "",
                     f"Set when the plugin was installed; `/plugin configure {plugin}@{market}` changes them.", ""]
            body += [f"- {prompt}: ${{user_config.{key}}}" for key, prompt, _ in setup_rows]
            body += [""]
        out[f"skills/{instructions}/SKILL.md"] = ("\n".join(body).encode("utf-8"), 0o644)

    ignored = []
    for a in agents:
        keys = [k for k in frontmatter_keys(text_of(files[a])) if k in AGENT_IGNORED]
        if keys:
            ignored.append((a[len(".claude/agents/"):], keys))

    # The manifest and the one-plugin marketplace beside it.
    pj = {"name": plugin, "version": version}
    if description:
        pj["description"] = description
    if author:
        pj["author"] = {"name": author}
    if isinstance(manifest.get("license"), str) and manifest["license"].strip():
        pj["license"] = manifest["license"].strip()
    tags = [t for t in (manifest.get("tags") or []) if isinstance(t, str)]
    if tags:
        pj["keywords"] = tags
    if user_config:
        pj["userConfig"] = user_config
    out[".claude-plugin/plugin.json"] = (dump(pj), 0o644)
    entry = {"name": plugin, "source": "./"}
    if description:
        entry["description"] = description
    out[".claude-plugin/marketplace.json"] = (dump({
        "name": market,
        "description": f"{tname} {version}, an agent8 template exported as a Claude Code plugin.",
        "owner": {"name": author or "agent8"},
        "plugins": [entry],
    }), 0o644)

    # The README: how to install, what's inside, the secrets, what stayed behind.
    req = block.get("requires") if isinstance(block.get("requires"), dict) else {}
    repos = [r for r in (block.get("repos") or []) if isinstance(r, dict)]
    readme_src = files.get("README.md")
    R = []
    R += [f"# {tname}", ""]
    if description:
        R += [description, ""]
    R += [f"A Claude Code plugin made from the agent template **{tname}**, version {version}. It carries the "
          "agent's instructions, skills and tools. The agent's own identity, memory, data and secrets stay with it.", ""]
    R += ["## Install", "", f"Unzip it, then in Claude Code, from the folder that holds `{plugin}/`:", "", "```",
          f"/plugin marketplace add ./{plugin}", f"/plugin install {plugin}@{market}", "```", "",
          f"To try it once without installing: `claude --plugin-dir ./{plugin}`.", ""]
    R += ["## What's inside", ""]
    if instructions:
        R += [f"- Instructions: the skill `/{plugin}:{instructions}`, from the agent's AGENTS.md"
              + (" and its rules" if rules else "") + ". Claude reads it when the work matches; "
              "a plugin can't add instructions to every conversation."]
    if skills:
        R += ["- Skills: " + ", ".join(f"`/{plugin}:{s}`" for s in sorted(skills))]
    if agents:
        R += ["- Subagents: " + ", ".join(f"`{plugin}:{a[len('.claude/agents/'):-3].replace('/', ':')}`" for a in agents)]
    if commands:
        R += ["- Commands: " + ", ".join(f"`/{plugin}:{c[len('.claude/commands/'):-3].replace('/', ':')}`" for c in commands)]
    if hook_count:
        R += [f"- Hooks: {hook_count} (" + ", ".join(hook_events) + "). They run in every project where the "
              "plugin is turned on."]
    if servers:
        R += ["- MCP servers: " + ", ".join(f"`{s}`" for s in servers)]
    if kept:
        R += [f"- Other files: {len(kept)}, as they were in the template (scripts the hooks, servers and skills use)."]
    if any(p.startswith("bin/") for p in kept):
        R += ["- Programs in `bin/` are on the shell's PATH while the plugin is turned on."]
    R += [""]
    R += ["## Secrets", ""]
    if secret_rows:
        R += ["Nothing secret is in this plugin. Each secret is a `${NAME}` placeholder:", "",
              "| Placeholder | What to enter | What it's for |", "|---|---|---|"]
        for name, item, field, why, how in secret_rows:
            R += [f"| `${{{name}}}` | {cell(item)}" + (f", field `{cell(field)}`" if field else "")
                  + f" | {cell(why)}" + (f" How to get it: {cell(how)}" if how else "") + " |"]
        R += ["", f"Claude Code asks for them when you install or turn on the plugin, or with "
              f"`/plugin configure {plugin}@{market}`, and keeps them in your system's secure storage. "
              "MCP servers read them as `${user_config.NAME}`; hooks and scripts get them as "
              "`$CLAUDE_PLUGIN_OPTION_NAME`. A script that reads `$NAME` itself needs `NAME` set in your "
              "environment before you start Claude Code.", ""]
    else:
        R += ["Nothing secret is in this plugin, and it asks for none.", ""]
    if token_files:
        R += ["Token files the agent read (not carried over; make them yourself if a tool needs one):", ""]
        R += [f"- `{p}`, from the vault item {item}" for p, item in token_files]
        R += [""]
    if unnamed:
        R += ["Also used by the agent, by name only: " + "; ".join(
            f"{item}" + (f" ({why})" if why else "") for item, why in unnamed) + ".", ""]
    if setup_rows:
        R += ["## Settings asked at install", ""]
        R += [f"- `{key}`: {prompt}" + (" (required)" if req_ else "") for key, prompt, req_ in setup_rows]
        R += ["", f"The instructions skill shows your answers. Change them with `/plugin configure {plugin}@{market}`.", ""]
    R += ["## What didn't come over", "",
          "A plugin has no identity, no memory of its own and no vault, so these stay with the agent:", "",
          "- Its own layer: identity, local rules and its own skills (`identity.md`, `LOCAL.md`).",
          "- Its data" + (": " + ", ".join(f"`{p}`" for p in data_patterns) if data_patterns else "")
          + ", and the starting content in `seed/`.",
          "- Its vault: secrets are asked by Claude Code instead (see Secrets)."]
    if setup_rows:
        R += ["- Setup questions: they're plugin settings now (see Settings asked at install)."]
    if settings_left:
        R += ["- Claude Code settings other than hooks: " + ", ".join(f"`{k}`" for k in settings_left)
              + ". Plugins can't set them; copy them to your own settings if you want them."]
    plain_env = [n for n in env_block if n not in secret_env]
    if plain_env:
        R += ["- The environment it was started with: " + ", ".join(f"`{n}`" for n in plain_env)
              + ". This plugin's MCP servers still get them; its hooks and scripts don't."]
    if codex:
        R += ["- Codex settings (`.codex/`): this plugin is for Claude Code."]
    for a, keys in ignored:
        R += [f"- Subagent `{a}`: " + ", ".join(f"`{k}`" for k in keys) + " (plugins ignore these)."]
    for r in repos:
        R += [f"- The repository it works in at `{one_line(r.get('path'))}` ({one_line(r.get('url'))}): clone it yourself."]
    if left:
        R += ["- Files left out:"]
        R += [f"  - `{p}`: {why}" for p, why in left[:LEFT_OUT_SHOWN]]
        if len(left) > LEFT_OUT_SHOWN:
            R += [f"  - and {len(left) - LEFT_OUT_SHOWN} more"]
    R += [""]
    needs = []
    for label, key in (("Programs", "tools"), ("Accounts", "logins"), ("Plugins", "plugins"), ("Skills", "skills")):
        vals = [one_line(x) for x in (req.get(key) or []) if isinstance(x, str)]
        if vals:
            needs.append(f"- {label}: " + ", ".join(f"`{x}`" for x in vals))
    if needs:
        R += ["## It also needs", ""] + needs + [""]
    R += ["## Good to know", "",
          "- The plugin is read-only and replaced as a whole on each update. A script that keeps files next to "
          "itself now writes in the plugin's folder, so those files go at the next update.",
          "- Commands that named a file with `$CLAUDE_PROJECT_DIR` now use the plugin's folder "
          "(`${CLAUDE_PLUGIN_ROOT}`) when the file came with the plugin; the others still mean your project.", ""]
    if readme_src and readme_src.get("kind") == "file":
        R += ["---", "", "## The template's README", "", text_of(readme_src).strip(), ""]
    out["README.md"] = ("\n".join(R).encode("utf-8"), 0o644)

    # Last check, on exactly what goes out: no key file, no key.
    found = []
    for p in sorted(out):
        if v.SECRET_FILE_RE.search(p):
            found.append(p)
        elif v.looks_secret(out[p][0].decode("utf-8", "replace")):
            found.append(p)
    if found:
        raise ExportRefused("These files look like they hold a key or a password: " + ", ".join(found[:20])
                            + ". Take it out of the template and publish a new version.")

    info = {"plugin": plugin, "marketplace": market, "instructions": instructions,
            "skills": sorted(skills), "agents": len(agents), "commands": len(commands),
            "hooks": hook_count, "servers": servers, "secrets": [r[0] for r in secret_rows],
            "settings": [r[0] for r in setup_rows], "left_out": left, "settings_left": settings_left}
    return {p: out[p] for p in sorted(out)}, info
