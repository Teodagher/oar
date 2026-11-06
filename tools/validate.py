#!/usr/bin/env python3
"""Validator for the open agent template format v0.2 (see ../SPEC.md).

Usage:
  validate.py template <dir>     check a template folder (a repo, before publishing)
  validate.py instance <dir>     check an installed copy (agent.yaml + .agent8/)
  validate.py digest <dir>       print the sha256 digest of a template folder (SPEC §9.3)

Exit codes: 0 valid (warnings allowed), 1 invalid, 2 usage or unreadable,
3 the format is newer than this validator understands (SPEC §3.2).

Needs PyYAML and jsonschema (pip install pyyaml jsonschema).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
    import jsonschema
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(f"validate.py needs PyYAML and jsonschema: {exc}\n")
    sys.exit(2)

SUPPORTED_FORMAT = (0, 2)  # reads every 0.x; a newer minor's unknown keys are ignored and listed
HERE = Path(__file__).resolve().parent
SCHEMA_DIR = HERE.parent / "schema"

OWN_LAYER_ROOT = {"identity.md", "LOCAL.md", "mcp.local.json", "agent.yaml"}
OWN_LAYER_PATHS = OWN_LAYER_ROOT | {".claude/settings.local.json"}
OWN_LAYER_DIRS = {"skills"}
SKILL_LAYOUTS = ("skills", ".agents/skills", ".claude/skills")
HOST_OWNED = {"AGENTS.md", "CLAUDE.md", ".mcp.json", ".claude/settings.json", ".codex/config.toml"}
HOST_OWNED_DIRS = {".claude/skills", ".agents/skills", ".agent8"}
MCP_BUILTIN_VARS = {"CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT", "HOME"}
OPENGAP_DEFAULT_DATA = ["/memory/", "/knowledge/", "/.gitagent/"]
CLAUDE_MD_ALLOWED = {"@AGENTS.md", "@identity.md", "@LOCAL.md"}

ITEM_NAME = r"[A-Za-z0-9_-](?:[A-Za-z0-9 _-]{0,62}[A-Za-z0-9_-])?"
VAULT_RE = re.compile(r"\{\{vault:(" + ITEM_NAME + r")(?:\.([A-Za-z0-9_-]+))?\}\}")
KNOWN_BLOCK_KEYS = {"format", "layout", "data", "setup", "secrets", "env", "repos", "requires"}
VAULT_LOOSE_RE = re.compile(r"\{\{\s*vault:[^}]*\}\}")
# A secret env value: exactly one placeholder, with at most a "Bearer " or
# "Basic " prefix. Anything more could carry a value next to it.
SECRET_ENV_RE = re.compile(r"(?:(?:Bearer|Basic) )?" + VAULT_RE.pattern)
ANSWER_RE = re.compile(r"\{\{answer:([a-z][a-z0-9_]*)\}\}")
ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}")
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")

SECRET_FILE_RE = re.compile(r"(^|/)(\.env(\.(?!example$|sample$)[^/]+)?|id_rsa[^/]*|id_ed25519[^/]*|[^/]+\.pem|[^/]+\.p12|[^/]+\.key)$")
SECRET_CONTENT_RES = [
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"),
    re.compile(r"\bsk_live_[0-9A-Za-z]{16,}"),
    re.compile(r"\bsk-ant-[0-9A-Za-z_-]{20,}"),
    re.compile(r"\bsk-proj-[0-9A-Za-z_-]{20,}"),
    re.compile(r"\bghp_[0-9A-Za-z]{30,}"),
    re.compile(r"\bgithub_pat_[0-9A-Za-z_]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\bsk-[0-9A-Za-z]{32,}"),
]


class FormatTooNew(Exception):
    pass


class FormatTooOld(Exception):
    pass


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def info(self, msg: str) -> None:
        self.infos.append(msg)

    def merge(self, other: "Report", prefix: str) -> None:
        self.errors += [prefix + m for m in other.errors]
        self.warnings += [prefix + m for m in other.warnings]
        self.infos += [prefix + m for m in other.infos]

    def print(self, out=None) -> None:
        out = out or sys.stdout
        for m in self.errors:
            print(f"error: {m}", file=out)
        for m in self.warnings:
            print(f"warning: {m}", file=out)
        for m in self.infos:
            print(f"info: {m}", file=out)


# ---------------------------------------------------------------- data patterns

class DataList:
    """Anchored gitignore patterns with gitignore semantics (SPEC §7.1).

    As in gitignore, the last matching pattern wins, and a path inside an excluded
    directory stays excluded even if a later `!` pattern names it.
    """

    def __init__(self, patterns: list[str]):
        self.rules = []
        for p in patterns:
            neg = p.startswith("!")
            body = p[1:] if neg else p
            dir_only = body.endswith("/")
            body = body.rstrip("/")
            if body.startswith("/"):
                body = body[1:]
            self.rules.append((neg, dir_only, re.compile(_glob_to_regex(body))))

    def _verdict(self, path: str, is_dir: bool):
        result = None
        for neg, dir_only, rx in self.rules:
            if dir_only and not is_dir:
                continue
            if rx.fullmatch(path):
                result = not neg
        return result

    def matches(self, path: str, is_dir: bool = False) -> bool:
        parts = path.split("/")
        for i in range(1, len(parts)):
            if self._verdict("/".join(parts[:i]), True):
                return True
        return bool(self._verdict(path, is_dir))


def _glob_to_regex(glob: str) -> str:
    out, i, n = [], 0, len(glob)
    while i < n:
        c = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("/**", i) and i + 3 == n:
            out.append("/.*")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = glob.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
                i += 1
            else:
                inner = glob[i + 1:j]
                if inner.startswith("!"):
                    inner = "^" + inner[1:]
                out.append("[" + inner.replace("\\", "\\\\") + "]")
                i = j + 1
        elif c == "\\" and i + 1 < n:
            out.append(re.escape(glob[i + 1]))
            i += 2
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def _list_unknown_keys(block: dict, rep: Report, where: str) -> None:
    unknown = sorted(k for k in block if k not in KNOWN_BLOCK_KEYS)
    if unknown:
        rep.info(f"{where} also uses {', '.join(unknown)}, unknown to format "
                 f"{SUPPORTED_FORMAT[0]}.{SUPPORTED_FORMAT[1]}; ignored (from a newer minor format?)")


def check_data_patterns(patterns: list, rep: Report, where: str = "x-agent8.data") -> None:
    for p in patterns:
        if not isinstance(p, str) or not p:
            rep.error(f"{where}: empty or non-text pattern {p!r}")
            continue
        if p != p.strip():
            rep.error(f"{where}: pattern {p!r} has spaces at an end (gitignore would keep them)")
        if re.search(r"\s#", p) or p.lstrip("!").startswith("#"):
            rep.error(f"{where}: pattern {p!r} contains a comment; put comments on their own YAML line")
        body = p[1:] if p.startswith("!") else p
        if not (body.startswith("/") or body.startswith("**/")):
            rep.error(f"{where}: pattern {p!r} is not anchored; start it with / (this folder) or **/ (any depth)")


# ---------------------------------------------------------------- helpers

class _Loader(yaml.SafeLoader):
    """SafeLoader that keeps timestamps as text, so they validate as JSON strings."""


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(path: Path, rep: Report):
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.load(fh, Loader=_Loader)
    except FileNotFoundError:
        rep.error(f"{path.name} is missing")
    except yaml.YAMLError as exc:
        rep.error(f"{path.name} is not valid YAML: {exc}")
    return None


def schema(name: str) -> dict:
    with open(SCHEMA_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


def schema_check(doc, schema_name: str, rep: Report, label: str) -> None:
    validator = jsonschema.Draft202012Validator(schema(schema_name))
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "(top)"
        rep.error(f"{label} {loc}: {err.message}")


def check_format(value, label: str) -> None:
    """Raise FormatTooNew for a format this validator must refuse (SPEC §3.2)."""
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+", value):
        return  # the schema reports the bad shape
    major, minor = (int(x) for x in value.split("."))
    smaj, smin = SUPPORTED_FORMAT
    if major > smaj:
        raise FormatTooNew(
            f"{label} needs format {value} (a new major); this validator reads {smaj}.x. "
            "Update it and try again."
        )
    if major < smaj:
        raise FormatTooOld(f"{label} uses format {value}; this validator reads {smaj}.x only.")


def parse_extends(value: str):
    if not isinstance(value, str) or "@" not in value:
        return None
    source, _, version = value.rpartition("@")
    if not source or not SEMVER_RE.fullmatch(version):
        return None
    return source, version


def walk(root: Path, rep: Report):
    """Yield (relpath, is_dir) for every entry; report symlinks that escape."""
    root_real = os.path.realpath(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
        if rel_dir == "" and ".git" in dirnames:
            dirnames.remove(".git")
        dirnames.sort()
        for name in list(dirnames) + sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if os.path.islink(full):
                target = os.path.realpath(full)
                if not (target == root_real or target.startswith(root_real + os.sep)):
                    rep.error(f"{rel}: symlink points outside the folder")
                    if name in dirnames:
                        dirnames.remove(name)
                    continue
                if os.path.isabs(os.readlink(full)):
                    rep.error(f"{rel}: symlink is absolute; make it relative so the folder can move")
            if name == ".git" and rel_dir != "":
                rep.error(f"{rel}: a nested git repository; declare it in x-agent8.repos instead")
                if name in dirnames:
                    dirnames.remove(name)
                continue
            if name == ".gitmodules" and rel_dir == "":
                rep.error(".gitmodules: git submodules are not allowed in v0.2")
            yield rel, name in dirnames


def read_text(path: Path):
    try:
        if path.stat().st_size > 1_000_000:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8000]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def looks_secret(text: str) -> bool:
    return any(rx.search(text) for rx in SECRET_CONTENT_RES)


def template_digest(root: Path) -> str:
    """sha256 over sorted lines `<relpath>\\0<sha256 of content>\\n` of every file
    (symlinks: `link:<target>` instead of content), `.git/` excluded."""
    lines = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if os.path.realpath(dirpath) == os.path.realpath(root) and ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if os.path.islink(full):
                h = hashlib.sha256(("link:" + os.readlink(full)).encode()).hexdigest()
            else:
                with open(full, "rb") as fh:
                    h = hashlib.sha256(fh.read()).hexdigest()
            lines.append(f"{rel}\0{h}\n")
    return "sha256:" + hashlib.sha256("".join(sorted(lines)).encode()).hexdigest()


def frontmatter(text: str):
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def safe_rel(path: str) -> bool:
    """Relative, normalised, inside the folder: no ./, .., ~, leading /, backslash or empty part."""
    if not path or path.startswith(("/", "~")) or "\\" in path:
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def protected_target(p: str):
    """Why a path inside the folder can't be written by the host for a template, or None."""
    first = p.split("/")[0]
    if first in (".agent8", ".git"):
        return f"under {first}/"
    if p in HOST_OWNED or any(p == d or p.startswith(d + "/") for d in HOST_OWNED_DIRS):
        return "a host-owned path"
    if p in OWN_LAYER_PATHS or any(p == d or p.startswith(d + "/") for d in OWN_LAYER_DIRS):
        return "an own-layer path"
    return None


def skills_layout(root: Path, block: dict) -> str:
    layout = (block.get("layout") or {}).get("skills")
    if layout:
        return layout
    for cand in SKILL_LAYOUTS:
        if (root / cand).is_dir():
            return cand
    return "skills"


# ---------------------------------------------------------------- template

def validate_template(root: Path) -> Report:
    rep = Report()
    root = Path(root)
    if not root.is_dir():
        rep.error(f"{root} is not a folder")
        return rep
    manifest = load_yaml(root / "agent.yaml", rep)
    if not isinstance(manifest, dict):
        if manifest is not None:
            rep.error("agent.yaml must be a mapping")
        return rep

    block = manifest.get("x-agent8")
    if block is None:
        return _validate_plain_opengap(root, manifest, rep)
    if isinstance(block, dict):
        check_format(block.get("format"), "this template")
        _list_unknown_keys(block, rep, "x-agent8")
    schema_check(manifest, "manifest.schema.json", rep, "agent.yaml")
    if not isinstance(block, dict):
        return rep

    if "extends" in manifest:
        rep.error("agent.yaml: a template cannot use `extends` in v0.2; flatten it when publishing (SPEC §2.2)")

    data_patterns = block.get("data") or []
    check_data_patterns(data_patterns, rep)
    secrets = block.get("secrets") or []
    setup = block.get("setup") or []
    layout = skills_layout(root, block)

    secret_targets = set()
    for s in secrets:
        for f in (s.get("files") or []) if isinstance(s, dict) else []:
            if isinstance(f, dict) and isinstance(f.get("path"), str):
                secret_targets.add(f["path"].strip("/"))
    data = DataList([p for p in data_patterns if isinstance(p, str)])
    _check_repos(block.get("repos") or [], data, rep)
    _check_env(block.get("env") or {}, setup if isinstance(setup, list) else [], rep)

    entries = list(walk(root, rep))
    files = [r for r, d in entries if not d]
    dirs = {r for r, d in entries if d}

    # required files
    if not (root / "AGENTS.md").is_file():
        rep.error("AGENTS.md is missing (the template's main instructions)")
    if not (root / "LICENSE").exists() and not any(f.upper().startswith("LICENSE") for f in files if "/" not in f):
        rep.warn("no LICENSE: nobody may legally reuse this template")
    if not (root / "README.md").is_file():
        rep.warn("no README.md: an import page will have nothing to show")

    # CLAUDE.md
    claude_md = root / "CLAUDE.md"
    if claude_md.is_file():
        lines = [ln.strip() for ln in (read_text(claude_md) or "").splitlines() if ln.strip()]
        if not lines or lines[0] != "@AGENTS.md" or any(ln not in CLAUDE_MD_ALLOWED for ln in lines):
            rep.error("CLAUDE.md must be `@AGENTS.md` (optionally followed by `@identity.md`, `@LOCAL.md`); put the instructions in AGENTS.md")

    # own-layer names at the root
    for name in ("identity.md", "LOCAL.md", "mcp.local.json"):
        if (root / name).exists():
            rep.error(f"{name}: belongs to a copy's own layer; seed it from seed/{name} instead")
    if (root / ".agent8").exists():
        rep.error(".agent8/: belongs to an installed copy, not a template")
    if (root / ".claude/settings.local.json").exists():
        rep.error(".claude/settings.local.json: personal settings, never part of a template")
    if layout != "skills" and "skills" in dirs:
        rep.error("skills/: collides with the copy's own skills folder; move these skills to the folder set in x-agent8.layout.skills")
    for d in (".claude/skills", ".agents/skills"):
        if d != layout and d in dirs and not os.path.islink(root / d):
            rep.warn(f"{d}/: ignored, the host regenerates it from {layout}/ (make it a symlink to {layout} or remove it)")

    # data, secrets, seeds
    for rel in files:
        if rel.startswith("seed/"):
            continue
        if data.matches(rel):
            rep.error(f"{rel}: matches the data list; data never ships in a template (move a starting version to seed/{rel})")
        if rel in secret_targets:
            rep.error(f"{rel}: is a secret file target; the host writes it, the template must not ship it")
        _check_absolute_in_text(root, rel, rep)
        if SECRET_FILE_RE.search(rel):
            rep.error(f"{rel}: looks like a secret file; templates name secrets, they never hold them")
            continue
        text = read_text(root / rel)
        if text and looks_secret(text):
            rep.error(f"{rel}: contains what looks like a secret value")
    for d in sorted(dirs):
        if not d.startswith("seed/") and d != "seed" and data.matches(d, True):
            rep.error(f"{d}/: matches the data list; folder names count as content, ship it under seed/{d}/")

    question_ids = [q.get("id") for q in setup if isinstance(q, dict)]
    _check_setup(setup, rep)
    for rel in files:
        if not rel.startswith("seed/"):
            continue
        target = rel[len("seed/"):]
        if not (target in OWN_LAYER_ROOT - {"agent.yaml"} or data.matches(target)):
            rep.error(f"{rel}: seeds {target}, which is not in the data list or the own layer; it would never be updated")
        text = read_text(root / rel)
        if text:
            for qid in ANSWER_RE.findall(text):
                if qid not in question_ids:
                    rep.error(f"{rel}: {{{{answer:{qid}}}}} names no setup question")
            if looks_secret(text):
                rep.error(f"{rel}: contains what looks like a secret value")

    secret_env = _check_secrets(root, secrets, rep)
    env_names = secret_env | set((block.get("env") or {}).keys())
    _check_mcp(root, env_names, rep, secret_env)
    _check_skills(root, layout, rep)
    _check_vault_mentions(root, files, secrets, rep)
    _list_code(root, files, rep)
    return rep


def _check_setup(setup: list, rep: Report) -> None:
    seen = set()
    for q in setup:
        if not isinstance(q, dict):
            continue
        qid = q.get("id")
        if qid in seen:
            rep.error(f"setup: question id {qid!r} is used twice")
        seen.add(qid)
        if q.get("type") in ("choice", "multi") and "default" in q and q.get("choices"):
            default = q["default"]
            values = default if isinstance(default, list) else [default]
            for v in values:
                if v not in q["choices"]:
                    rep.error(f"setup {qid}: default {v!r} is not one of the choices")


def _check_secrets(root: Path, secrets: list, rep: Report) -> set:
    items = {}
    env_names = set()
    for s in secrets:
        if not isinstance(s, dict) or not isinstance(s.get("item"), str):
            continue
        if s["item"] in items:
            rep.error(f"secrets: item {s['item']!r} is declared twice")
        items[s["item"]] = s
    for s in items.values():
        for name, value in (s.get("env") or {}).items():
            if name in env_names:
                rep.error(f"secrets: env {name} is set by two secrets")
            env_names.add(name)
            _check_placeholders(str(value), items, rep, f"secrets {s['item']} env {name}")
            if not VAULT_RE.search(str(value)):
                rep.error(f"secrets {s['item']} env {name}: has no {{{{vault:…}}}} placeholder; plain values go in x-agent8.env")
            elif not SECRET_ENV_RE.fullmatch(str(value)):
                rep.error(f"secrets {s['item']} env {name}: must be exactly one {{{{vault:…}}}} placeholder, optionally after \"Bearer \" or \"Basic \"")
        for f in s.get("files") or []:
            if not isinstance(f, dict):
                continue
            path, tmpl = f.get("path"), f.get("template")
            if isinstance(path, str):
                if not safe_rel(path):
                    rep.error(f"secrets {s['item']}: file target {path!r} must stay inside the agent's folder (relative and normalised: no ./, .., ~ or leading /)")
                elif (why := protected_target(path)) or (root / path).exists():
                    rep.error(f"secrets {s['item']}: file target {path!r} is {why or 'a file of the template'}; secret files may not replace it")
            if isinstance(tmpl, str):
                if not safe_rel(tmpl) or not (root / tmpl).is_file():
                    rep.error(f"secrets {s['item']}: template file {tmpl!r} is not in the template")
                else:
                    _check_placeholders(read_text(root / tmpl) or "", items, rep, tmpl)
    return env_names


def _check_placeholders(text: str, items: dict, rep: Report, where: str) -> None:
    for m in VAULT_LOOSE_RE.finditer(text):
        strict = VAULT_RE.fullmatch(m.group(0))
        if not strict:
            rep.error(f"{where}: malformed placeholder {m.group(0)!r}; use {{{{vault:Item}}}} or {{{{vault:Item.field}}}}")
            continue
        item, fld = strict.group(1), strict.group(2)
        if item not in items:
            rep.error(f"{where}: {m.group(0)} names an undeclared vault item {item!r}")
        elif fld and items[item].get("fields") and fld not in items[item]["fields"]:
            rep.error(f"{where}: {m.group(0)} uses field {fld!r}, not in the item's declared fields")


def _check_mcp(root: Path, env_names: set, rep: Report, secret_env: set = frozenset()) -> None:
    path = root / ".mcp.json"
    if not path.is_file():
        return
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        rep.error(f".mcp.json is not valid JSON: {exc}")
        return
    servers = doc.get("mcpServers") if isinstance(doc, dict) else None
    if not isinstance(servers, dict):
        rep.error(".mcp.json: expected an object with `mcpServers`")
        return
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        for key in ("command", "args"):
            vals = cfg.get(key) if isinstance(cfg.get(key), list) else [cfg.get(key, "")]
            if any(isinstance(x, str) and x.startswith(("/", "~")) for x in vals):
                rep.error(f".mcp.json {name}.{key}: absolute path; use ${{CLAUDE_PROJECT_DIR}} so the agent can live anywhere")
            raw = json.dumps(cfg.get(key, ""))
            if any(v in secret_env for v in ENV_REF_RE.findall(raw)):
                rep.error(f".mcp.json {name}.{key}: a secret's ${{NAME}} must not appear in {key} (it shows in the process list); use env or headers")
        raw = json.dumps(cfg)
        for var in ENV_REF_RE.findall(raw):
            if var not in env_names and var not in MCP_BUILTIN_VARS:
                rep.error(f".mcp.json {name}: ${{{var}}} is not an env name declared by any secret")
        if looks_secret(raw):
            rep.error(f".mcp.json {name}: contains what looks like a secret value")


def _check_repos(repos: list, data: DataList, rep: Report) -> None:
    seen = set()
    for r in repos:
        if not isinstance(r, dict) or not isinstance(r.get("path"), str):
            continue
        path = r["path"]
        if path in seen:
            rep.error(f"repos: {path!r} is listed twice")
        seen.add(path)
        if not safe_rel(path):
            rep.error(f"repos {path!r}: must stay inside the agent's folder (relative and normalised)")
        elif why := protected_target(path):
            rep.error(f"repos {path!r}: is {why}")
        elif not data.matches(path, is_dir=True):
            rep.error(f"repos {path!r}: must match the data list (a cloned repo belongs to the copy)")


def _check_env(env: dict, setup: list, rep: Report) -> None:
    ids = {q.get("id") for q in setup if isinstance(q, dict)}
    for name, value in env.items():
        text = str(value)
        if VAULT_LOOSE_RE.search(text):
            rep.error(f"env {name}: secrets go in secrets[].env, not in env")
        for qid in ANSWER_RE.findall(text):
            if qid not in ids:
                rep.error(f"env {name}: {{{{answer:{qid}}}}} names no setup question")
        for ph in re.findall(r"\{\{([^}]*)\}\}", text):
            if ph != "folder" and not ph.startswith("answer:"):
                rep.error(f"env {name}: unknown placeholder {{{{{ph}}}}}")
        if looks_secret(text):
            rep.error(f"env {name}: looks like a secret value")


def _check_absolute_in_text(root: Path, rel: str, rep: Report) -> None:
    if rel != ".claude/settings.json":
        return
    try:
        hooks = json.loads((root / rel).read_text(encoding="utf-8")).get("hooks") or {}
    except (ValueError, OSError, AttributeError):
        return
    for event, groups in hooks.items():
        for g in groups or []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                cmd = str(h.get("command", "")) + " " + " ".join(map(str, h.get("args", []) or []))
                if re.search(r"(^|\s|[\"'])(/(home|root|Users|srv|opt)/|~/)", cmd):
                    rep.error(f"{rel} hook {event}: absolute path in {cmd.strip()!r}; use $CLAUDE_PROJECT_DIR")


def _check_skills(root: Path, layout: str, rep: Report) -> None:
    sdir = root / layout
    if not sdir.is_dir():
        return
    for child in sorted(sdir.iterdir()):
        if not child.is_dir():
            continue
        md = child / "SKILL.md"
        if not md.is_file():
            rep.error(f"{layout}/{child.name}: no SKILL.md")
            continue
        fm = frontmatter(read_text(md) or "")
        if fm is None:
            rep.error(f"{layout}/{child.name}/SKILL.md: missing YAML frontmatter")
            continue
        name = fm.get("name")
        if name != child.name:
            rep.error(f"{layout}/{child.name}/SKILL.md: frontmatter name {name!r} must equal the folder name")
        elif not SKILL_NAME_RE.fullmatch(name) or len(name) > 64:
            rep.error(f"{layout}/{child.name}: skill names are lowercase words joined by single hyphens, at most 64 characters")
        if not isinstance(fm.get("description"), str) or not fm["description"].strip():
            rep.error(f"{layout}/{child.name}/SKILL.md: frontmatter needs a description")


def _check_vault_mentions(root: Path, files: list, secrets: list, rep: Report) -> None:
    """Placeholders may appear anywhere (vault placeholders decision); each item must be declared."""
    items = {s["item"]: s for s in secrets if isinstance(s, dict) and isinstance(s.get("item"), str)}
    tmpl_files = {f.get("template") for s in items.values() for f in (s.get("files") or []) if isinstance(f, dict)}
    for rel in files:
        if rel in tmpl_files or rel == "agent.yaml":
            continue  # checked with their secret
        text = read_text(root / rel)
        if text and VAULT_LOOSE_RE.search(text):
            _check_placeholders(text, items, rep, rel)


def _list_code(root: Path, files: list, rep: Report) -> None:
    runs = []
    settings = root / ".claude/settings.json"
    if settings.is_file():
        try:
            hooks = json.loads(settings.read_text(encoding="utf-8")).get("hooks") or {}
            for event, groups in hooks.items():
                for g in groups or []:
                    for h in g.get("hooks", []):
                        if h.get("type") == "command":
                            runs.append(f"hook {event}: {h.get('command')}")
        except (ValueError, AttributeError):
            rep.error(".claude/settings.json is not valid JSON")
    mcp = root / ".mcp.json"
    if mcp.is_file():
        try:
            for name, cfg in (json.loads(mcp.read_text(encoding="utf-8")).get("mcpServers") or {}).items():
                if isinstance(cfg, dict) and cfg.get("command"):
                    runs.append(f"MCP server {name}: {cfg['command']}")
        except ValueError:
            pass
    for rel in files:
        if os.access(root / rel, os.X_OK) and not os.path.islink(root / rel):
            runs.append(f"executable: {rel}")
    for r in runs:
        rep.info(f"runs code: {r}")


def _validate_plain_opengap(root: Path, manifest: dict, rep: Report) -> Report:
    rep.warn("no x-agent8 block: read as a plain OpenGAP repo (SPEC §12), unverified")
    for key, rx in (("name", r"^[a-z][a-z0-9-]*$"), ("version", SEMVER_RE.pattern), ("description", r".+")):
        if not isinstance(manifest.get(key), str) or not re.fullmatch(rx, manifest[key]):
            rep.error(f"agent.yaml: OpenGAP requires a valid `{key}`")
    instr = [n for n in ("SOUL.md", "RULES.md", "AGENTS.md") if (root / n).is_file()]
    if not instr:
        rep.error("no SOUL.md, RULES.md or AGENTS.md: nothing to use as instructions")
    else:
        rep.info("instructions: " + " + ".join(instr))
    rep.info("data (stripped on import): " + ", ".join(OPENGAP_DEFAULT_DATA))
    if manifest.get("extends"):
        rep.info(f"extends {manifest['extends']}: the parent is flattened on import")
    for rel, _ in walk(root, rep):
        if SECRET_FILE_RE.search(rel):
            rep.error(f"{rel}: looks like a secret file")
    return rep


# ---------------------------------------------------------------- instance

def validate_instance(root: Path) -> Report:
    rep = Report()
    root = Path(root)
    record = load_yaml(root / ".agent8/instance.yaml", rep)
    manifest = load_yaml(root / "agent.yaml", rep)
    if isinstance(record, dict):
        check_format(record.get("format"), "this copy's instance record")
    if isinstance(manifest, dict) and isinstance(manifest.get("x-agent8"), dict):
        check_format(manifest["x-agent8"].get("format"), "this copy's agent.yaml")
    if not isinstance(record, dict) or not isinstance(manifest, dict):
        return rep

    known = {"format", "template", "previous", "installed_at", "updated_at", "answers", "secrets"}
    extra = sorted(k for k in record if k not in known)
    if extra:
        rep.info(f".agent8/instance.yaml also has {', '.join(extra)}; ignored (from a newer minor format?)")
        record = {k: val for k, val in record.items() if k in known}
    if isinstance(manifest.get("x-agent8"), dict):
        _list_unknown_keys(manifest["x-agent8"], rep, "agent.yaml x-agent8")
    schema_check(record, "instance.schema.json", rep, ".agent8/instance.yaml")
    schema_check(manifest, "manifest.schema.json", rep, "agent.yaml")
    ext = parse_extends(manifest.get("extends"))
    if ext is None:
        rep.error("agent.yaml: a copy needs `extends: <source>@<exact version>`")
        return rep
    source, version = ext
    tpl = record.get("template") or {}
    if tpl.get("source") != source or tpl.get("version") != version:
        rep.error(f"instance record says {tpl.get('source')}@{tpl.get('version')}, agent.yaml extends {source}@{version}")

    own = manifest.get("x-agent8") or {}
    for key in ("setup", "layout"):
        if key in own:
            rep.error(f"agent.yaml: a copy cannot change `{key}` (answers live in the instance record)")
    if "data" in own:
        check_data_patterns(own["data"], rep, "agent.yaml x-agent8.data")

    tdir = root / ".agent8/template" / version
    if not tdir.is_dir():
        rep.error(f".agent8/template/{version}/ is missing")
        return rep
    sub = validate_template(tdir)
    rep.merge(sub, f"template {version}: ")
    tman = load_yaml(tdir / "agent.yaml", Report()) or {}
    if tman.get("version") != version:
        rep.error(f"template folder {version} holds version {tman.get('version')!r}")
    if isinstance(tpl.get("digest"), str) and tpl["digest"] != template_digest(tdir):
        rep.warn(f".agent8/template/{version}/ changed since install (digest differs); hand edits are lost at the next update")

    tblock = tman.get("x-agent8") or {}
    questions = {q["id"]: q for q in tblock.get("setup") or [] if isinstance(q, dict) and "id" in q}
    answers = record.get("answers") or {}
    for qid, ans in answers.items():
        q = questions.get(qid)
        if q is None:
            rep.info(f"answer {qid!r} is kept for a version that asks it (none in {version})")
            continue
        if not _answer_fits(q, ans):
            rep.error(f"answer {qid!r} does not fit a {q.get('type')} question")
    for qid, q in questions.items():
        if q.get("required") and qid not in answers:
            rep.error(f"required setup question {qid!r} has no answer")

    declared = {s["item"] for blk in (tblock, own) for s in blk.get("secrets") or [] if isinstance(s, dict) and "item" in s}
    for s in record.get("secrets") or []:
        if isinstance(s, dict) and s.get("item") not in declared:
            rep.error(f"instance record lists secret {s.get('item')!r}, which neither the template nor the copy declares")
    raw = read_text(root / ".agent8/instance.yaml") or ""
    if looks_secret(raw):
        rep.error(".agent8/instance.yaml contains what looks like a secret value; it must only say present or missing")
    for name in ("identity.md", "LOCAL.md"):
        if not (root / name).is_file():
            rep.warn(f"{name} is missing from the own layer")
    return rep


def _answer_fits(q: dict, ans) -> bool:
    t = q.get("type")
    if t in ("string", "text"):
        return isinstance(ans, str)
    if t == "choice":
        return isinstance(ans, str) and ans in (q.get("choices") or [])
    if t == "multi":
        return isinstance(ans, list) and all(a in (q.get("choices") or []) for a in ans)
    if t == "boolean":
        return isinstance(ans, bool)
    if t == "number":
        return isinstance(ans, (int, float)) and not isinstance(ans, bool)
    return False


# ---------------------------------------------------------------- CLI

def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("template", "instance", "digest"):
        sys.stderr.write(__doc__)
        return 2
    target = Path(argv[2])
    if not target.is_dir():
        sys.stderr.write(f"{target} is not a folder\n")
        return 2
    if argv[1] == "digest":
        print(template_digest(target))
        return 0
    try:
        rep = validate_template(target) if argv[1] == "template" else validate_instance(target)
    except FormatTooNew as exc:
        print(f"error: {exc}")
        return 3
    except FormatTooOld as exc:
        print(f"error: {exc}")
        return 1
    rep.print()
    if rep.errors:
        print(f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
        return 1
    print(f"valid {argv[1]} ({len(rep.warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
