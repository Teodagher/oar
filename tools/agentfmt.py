#!/usr/bin/env python3
"""Reference command line for the open agent template format (see ../SPEC.md).

  agentfmt check [DIR]                       check a template (or an installed copy)
  agentfmt new DIR [--name N] [--description D] [--author A]
                                             start a new template that already passes check
  agentfmt install SOURCE [DEST] [--version V] [--answer id=value]... [--yes]
                                             install a template as a new agent: the template
                                             read-only, plus the copy's own layer
  agentfmt update [DIR] [--to V] [--answer id=value]... [--dry-run] [--yes]
                                             switch an installed copy to another version
                                             (up or back); never a merge

SOURCE is a git URL (https://, ssh://, git@host:owner/repo, file://), `github:owner/repo`,
or a local folder. Versions are git tags `vX.Y.Z` (or `X.Y.Z`); without one, the highest
release tag is used.

Exit codes: 0 done (warnings allowed), 1 invalid or refused, 2 usage or unreadable,
3 the format is newer than this tool reads (SPEC §3.2).

Works on its own: Python 3.9+, git, PyYAML and jsonschema. Nothing here depends on any host.
The format has no public name yet: the tool's name is the one constant TOOL below.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import stat as statmod
import subprocess
import sys
import tempfile
import unicodedata
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate as v  # noqa: E402  (the format's rules live in one place)

TOOL = "agentfmt"           # placeholder name: rename here once the format has one
TOOL_VERSION = "0.1.0"
FORMAT = "0.2"              # the format this tool writes
READS = {0: 2}              # format major -> highest minor read fully
KNOWN_X = frozenset(v.KNOWN_BLOCK_KEYS)
BLOCK = "x-agent8"          # the format's extension key (SPEC §3.1), not this tool's name

COMPOSED = frozenset(("AGENTS.md", "CLAUDE.md", ".mcp.json", ".claude/settings.json",
                      ".codex/config.toml", "agent.yaml"))
HOST_FILES = ("AGENTS.md", "CLAUDE.md", ".mcp.json", ".claude/settings.json", ".codex/config.toml")
OWN_ROOT = frozenset(("identity.md", "LOCAL.md", "mcp.local.json"))
SKILL_LAYOUTS = ("skills", ".agents/skills", ".claude/skills")
SKILL_TARGETS = (".claude/skills", ".agents/skills")
FILES_MAX = 5000
FILE_MAX = 20 * 1024 * 1024
TOTAL_MAX = 300 * 1024 * 1024
LINKS_MAX = 500
LINK_STEPS = 20000
REF_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/-]{0,199}\Z")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?\Z")
REPO_URL_RE = re.compile(
    r"^(?:https://[A-Za-z0-9.-]+(?::\d{1,5})?/[^\s@]+"
    r"|ssh://git@[A-Za-z0-9.-]+(?::\d{1,5})?/[^\s@]+"
    r"|git@[A-Za-z0-9.-]+:[A-Za-z0-9][^\s@:]*)$")
TAG_RE = re.compile(r"^v?((0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?)$")
SEMVER_RE = re.compile(v.SEMVER_RE.pattern.rstrip("$") + r"\Z")

IDENTITY_DEFAULT = ("# Identity\n\nYou are {name}, an agent installed from the template {template} "
                    "{version}.\n\nWrite who you are, who you work for and your owner's hard rules "
                    "here. This file is yours: template updates never touch it.\n")
LOCAL_DEFAULT = ("# Local rules\n\nYour own rules and improvements go here, and your own skills in "
                 "skills/. Never edit the template's files (.agent8/template/ and the copies of "
                 "them in this folder): they are replaced at every update.\n")


class Refused(Exception):
    """A plain-words reason to stop before (or instead of) writing anything."""


class TooNew(Refused):
    pass


# ---------------------------------------------------------------- shared safety checks

def rel_ok(p) -> bool:
    """A path this tool will write inside an agent's folder: relative, normalised,
    no `..`, no backslash, no control character."""
    if not isinstance(p, str) or not p or len(p) > 1024 or p.startswith(("/", "~")):
        return False
    if "\\" in p or any(ord(c) < 32 or ord(c) == 127 for c in p):
        return False
    return all(part not in ("", ".", "..") for part in p.split("/"))


def check_links(entries: dict) -> dict:
    """Every link resolved through the other links, from where it sits: refused when
    one leaves the folder, dangles, or goes round in circles. Returns link -> destination."""
    memo, budget = {}, [LINK_STEPS]

    def resolve(name, depth):
        if name in memo:
            if memo[name] is False:
                raise Refused(f"{name} is a link that goes round in circles.")
            return memo[name]
        if depth > 20:
            raise Refused(f"{name} is a link this tool won't follow.")
        memo[name] = False
        parts = name.split("/")[:-1]
        for c in entries[name]["target"].split("/"):
            budget[0] -= 1
            if budget[0] < 0:
                raise Refused("This template's links are too tangled to check.")
            if c in ("", "."):
                continue
            if c == "..":
                if not parts:
                    raise Refused(f"{name} is a link out of the folder.")
                parts.pop()
                continue
            parts.append(c)
            here = "/".join(parts)
            if entries.get(here, {}).get("kind") == "link":
                parts = resolve(here, depth + 1).split("/")
        dest = "/".join(parts)
        if not dest or entries.get(dest, {}).get("kind") not in ("file", "dir"):
            raise Refused(f"{name} is a link to something that isn't in the template.")
        memo[name] = dest
        return dest

    return {n: resolve(n, 0) for n in sorted(entries) if entries[n].get("kind") == "link"}


def check_entries(files: dict) -> dict:
    """The safety checks every template's files go through before anything is written
    (the same as agent8's installer): no `..`, no absolute path, no `.git`, no link out,
    nothing under a file, sizes bounded. Adds the folders implied by the paths."""
    if len(files) > FILES_MAX:
        raise Refused("This template has too many files.")
    total = 0
    for name, e in files.items():
        if not rel_ok(name):
            raise Refused(f"The template holds a path this tool won't write: {name[:200]!r}.")
        if ".git" in name.split("/"):
            raise Refused(f"The template holds a .git folder ({name}).")
        kind = e.get("kind")
        if kind == "link":
            target = e.get("target") or ""
            if not target or target.startswith("/") or "\\" in target or "\0" in target:
                raise Refused(f"{name} is a link out of the template.")
            dest = os.path.normpath(os.path.join(os.path.dirname(name), target))
            if dest in (".", "..") or dest.startswith(("../", "/")):
                raise Refused(f"{name} is a link out of the template.")
        elif kind == "file":
            size = len(e["data"])
            if size > FILE_MAX:
                raise Refused(f"{name} is too big.")
            total += size
            if total > TOTAL_MAX:
                raise Refused("This template is too big once unpacked.")
        elif kind != "dir":
            raise Refused(f"{name} isn't a plain file, folder or link.")
    for name in list(files):
        parts = name.split("/")
        for i in range(1, len(parts)):
            up = "/".join(parts[:i])
            if files.get(up, {}).get("kind") in ("file", "link"):
                raise Refused(f"{name} sits under {up}, which isn't a folder.")
            files.setdefault(up, {"kind": "dir"})
    if sum(1 for e in files.values() if e["kind"] == "link") > LINKS_MAX:
        raise Refused("This template has too many links.")
    check_links(files)
    return files


def format_check(manifest, what="install this template") -> dict:
    """SPEC §3.2: a newer major is refused before anything is written; a newer minor
    installs and lists the keys this tool skips."""
    block = manifest.get(BLOCK) if isinstance(manifest, dict) else None
    if not isinstance(block, dict):
        raise Refused(f"This template has no {BLOCK} block, so {TOOL} can't {what}.")
    fmt = block.get("format")
    m = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)", fmt if isinstance(fmt, str) else "")
    if not m:
        raise Refused("This template doesn't say which format it follows (x-agent8.format).")
    major, minor = int(m.group(1)), int(m.group(2))
    if major not in READS:
        if major > max(READS):
            raise TooNew(f"{TOOL} needs updating to {what} (it needs format {fmt}; "
                         f"this {TOOL} reads {', '.join(f'{k}.x' for k in sorted(READS))}).")
        raise Refused(f"This template's format ({fmt}) is older than {TOOL} reads.")
    return {"format": fmt, "newer": minor > READS[major],
            "skipped": sorted(k for k in block if k not in KNOWN_X)}


# ---------------------------------------------------------------- small helpers

def sha256(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def files_digest(files: dict) -> str:
    """SPEC §9.3 (same as validate.template_digest, on files held in memory)."""
    lines = []
    for p, e in files.items():
        if e["kind"] == "file":
            lines.append(f"{p}\0{sha256(e['data'])}\n")
        elif e["kind"] == "link":
            lines.append(f"{p}\0{sha256(('link:' + e['target']).encode())}\n")
    return "sha256:" + sha256("".join(sorted(lines)).encode())


def yaml_scalar(x) -> str:
    if x is None:
        return "null"
    if x is True:
        return "true"
    if x is False:
        return "false"
    if isinstance(x, (int, float)):
        return json.dumps(x)
    return json.dumps(str(x), ensure_ascii=False)


def to_yaml(obj, indent=0) -> list:
    """YAML for plain data, strings double-quoted (YAML reads them as JSON strings):
    the same output as agent8's writer, so both write the same files."""
    pad = "  " * indent
    lines = []
    if isinstance(obj, dict):
        for k, val in obj.items():
            key = k if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", k) else json.dumps(k, ensure_ascii=False)
            if isinstance(val, (dict, list)) and val:
                lines.append(f"{pad}{key}:")
                lines.extend(to_yaml(val, indent + 1))
            elif isinstance(val, (dict, list)):
                lines.append(f"{pad}{key}: {'{}' if isinstance(val, dict) else '[]'}")
            else:
                lines.append(f"{pad}{key}: {yaml_scalar(val)}")
    elif isinstance(obj, list):
        for val in obj:
            if isinstance(val, (dict, list)) and val:
                sub = to_yaml(val, indent + 1)
                inner = "  " * (indent + 1)
                first = sub[0][len(inner):] if sub[0].startswith(inner) else sub[0].lstrip()
                if isinstance(val, list):
                    lines.append(f"{pad}-")
                    lines.extend(sub)
                else:
                    lines.append(f"{pad}- {first}")
                    lines.extend(sub[1:])
            else:
                lines.append(f"{pad}- " + (yaml_scalar(val) if not isinstance(val, (dict, list))
                                           else ("{}" if isinstance(val, dict) else "[]")))
    return lines


def read_yaml_text(text: str, what: str):
    try:
        return v.yaml.load(text, Loader=v._Loader)
    except v.yaml.YAMLError as exc:
        raise Refused(f"{what} is not valid YAML: {exc}")


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"^[^a-z]+", "", s)[:64].rstrip("-")
    return s or "agent"


def file_entry(text, mode=0o644) -> dict:
    return {"kind": "file", "data": text.encode("utf-8") if isinstance(text, str) else text, "mode": mode}


def now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def semver_key(ver: str):
    m = SEMVER_RE.match(ver)
    major, minor, patch = (int(m.group(i)) for i in (1, 2, 3))
    pre = m.group(4)
    if not pre:
        return (major, minor, patch, 1, ())
    ids = tuple((0, int(x), "") if x.isdigit() else (1, 0, x) for x in pre[1:].split("."))
    return (major, minor, patch, 0, ids)


def compose(*sources):
    """SPEC §6: objects merge key by key, arrays concatenate without exact duplicates,
    anything else: the later source wins."""
    out = None
    for s in sources:
        if s is None:
            continue
        if isinstance(out, dict) and isinstance(s, dict):
            merged = dict(out)
            for k, val in s.items():
                merged[k] = compose(merged.get(k), val) if k in merged else compose(val)
            out = merged
        elif isinstance(out, list) and isinstance(s, list):
            merged = list(out)
            seen = [json.dumps(x, sort_keys=True) for x in merged]
            for x in s:
                key = json.dumps(x, sort_keys=True)
                if key not in seen:
                    merged.append(x)
                    seen.append(key)
            out = merged
        elif isinstance(s, dict):
            out = compose({}, s) if s else {}
        elif isinstance(s, list):
            out = list(s)
        else:
            out = s
    return out


def json_of(entry, what):
    if not entry or entry.get("kind") != "file":
        return None
    try:
        data = json.loads(entry["data"].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Refused(f"The template's {what} isn't valid JSON.")
    if not isinstance(data, dict):
        raise Refused(f"The template's {what} isn't a JSON object.")
    return data


# ---------------------------------------------------------------- setup answers

def check_answers(setup, answers, strict=True) -> dict:
    """The answers that fit their questions, defaults filled in. Strict: a required
    question without an answer, or an answer that doesn't fit, is refused."""
    answers = answers if isinstance(answers, dict) else {}
    out = {}
    for q in setup or []:
        if not isinstance(q, dict) or not isinstance(q.get("id"), str):
            continue
        qid, kind = q["id"], q.get("type") or "string"
        label = str(q.get("prompt") or qid)[:200]
        a = answers.get(qid, q.get("default"))
        if a is None or a == "" or a == []:
            if q.get("required") and strict:
                raise Refused(f"Answer “{label}” first (--answer {qid}=…).")
            continue
        choices = [c for c in q.get("choices") or [] if isinstance(c, str)]
        if kind in ("string", "text"):
            ok = isinstance(a, str) and len(a) <= 4000
        elif kind == "choice":
            ok = isinstance(a, str) and a in choices
        elif kind == "multi":
            ok = isinstance(a, list) and all(isinstance(x, str) and x in choices for x in a)
        elif kind == "boolean":
            ok = isinstance(a, bool)
        elif kind == "number":
            ok = isinstance(a, (int, float)) and not isinstance(a, bool) and a == a and abs(a) < 1e15
        else:
            ok = False
        if not ok:
            if strict:
                raise Refused(f"The answer to “{label}” doesn't fit the question.")
            continue
        if v.looks_secret(json.dumps(a)):
            raise Refused(f"The answer to “{label}” looks like a key or a password. Secrets are "
                          "never setup answers.")
        out[qid] = a
    return out


def parse_answer(setup, raw: str):
    """`id=value` from the command line, typed by its question."""
    if "=" not in raw:
        raise Refused(f"--answer {raw!r}: write it as id=value.")
    qid, text = raw.split("=", 1)
    q = next((q for q in setup or [] if isinstance(q, dict) and q.get("id") == qid), None)
    kind = (q or {}).get("type") or "string"
    if kind == "boolean":
        low = text.strip().lower()
        if low not in ("true", "false", "yes", "no", "1", "0"):
            raise Refused(f"--answer {qid}: answer yes or no.")
        return qid, low in ("true", "yes", "1")
    if kind == "number":
        try:
            return qid, float(text) if any(c in text for c in ".eE") else int(text)
        except ValueError:
            raise Refused(f"--answer {qid}: a number, please.")
    if kind == "multi":
        return qid, [x.strip() for x in text.split(",") if x.strip()]
    return qid, text


def answer_text(a) -> str:
    if isinstance(a, bool):
        return "true" if a else "false"
    if isinstance(a, list):
        return ", ".join(a)
    return str(a)


def fill_answers(text: str, answers: dict) -> str:
    return v.ANSWER_RE.sub(lambda m: answer_text(answers[m.group(1)]) if m.group(1) in answers else "", text)


# ---------------------------------------------------------------- reading a template

def git(args, cwd=None, data=None, check=True) -> bytes:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", LANG="C.UTF-8")
    argv = ["git", "-c", "protocol.ext.allow=never", "-c", "core.hooksPath=/dev/null"] + list(args)
    try:
        p = subprocess.run(argv, cwd=cwd, input=data, capture_output=True, env=env, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused(f"git didn't run: {exc}")
    if check and p.returncode != 0:
        last = (p.stderr.decode("utf-8", "replace").strip().splitlines() or ["git said no"])[-1]
        raise Refused(f"git: {last[:300]}")
    return p.stdout


def source_url(source: str) -> str:
    """What git clones for a SOURCE given on the command line."""
    m = re.fullmatch(r"github:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", source)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}.git"
    return source


def source_name(source: str) -> str:
    """What `extends` records: a URL as given, a local folder as a file:// URL."""
    if re.match(r"^(https?|ssh|file|git)://|^git@|^github:", source):
        return source
    return "file://" + urllib.parse.quote(os.path.abspath(source))


def local_dir(source: str):
    """The folder a SOURCE names on this machine, or None."""
    if source.startswith("file://"):
        source = urllib.parse.unquote(source[len("file://"):])
    return source if os.path.isdir(source) else None


def read_folder(root: str) -> dict:
    """A plain folder (not a git repository), read without following links."""
    files, count = {}, 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        if rel_dir == "" and ".git" in dirnames:
            dirnames.remove(".git")
        for name in sorted(dirnames) + sorted(filenames):
            count += 1
            if count > FILES_MAX * 3:
                raise Refused("This template has too many files.")
            full = os.path.join(dirpath, name)
            rel = f"{rel_dir}/{name}" if rel_dir else name
            st = os.lstat(full)
            if statmod.S_ISLNK(st.st_mode):
                files[rel] = {"kind": "link", "target": os.readlink(full)}
                if name in dirnames:
                    dirnames.remove(name)
            elif statmod.S_ISDIR(st.st_mode):
                files[rel] = {"kind": "dir"}
            elif statmod.S_ISREG(st.st_mode):
                if st.st_size > FILE_MAX:
                    raise Refused(f"{rel} is too big.")
                with open(full, "rb") as fh:
                    files[rel] = {"kind": "file", "data": fh.read(),
                                  "mode": 0o755 if st.st_mode & 0o111 else 0o644}
            else:
                raise Refused(f"{rel} isn't a plain file, folder or link.")
    return files


class Source:
    """A template's source: a git repository (cloned once, read by tag) or a plain folder."""

    def __init__(self, source: str):
        self.given = source
        self.name = source_name(source)
        self.tmp = None
        self.repo = None
        here = local_dir(source)
        if here and not os.path.exists(os.path.join(here, ".git")):
            self.folder = here
            return
        self.folder = None
        self.tmp = tempfile.mkdtemp(prefix=f"{TOOL}-")
        self.repo = os.path.join(self.tmp, "repo")
        url = here or source_url(source)
        if url.startswith("-"):
            raise Refused(f"{source!r} isn't a git address.")
        git(["clone", "--quiet", "--no-checkout", "--no-recurse-submodules", "--", url, self.repo])

    def close(self):
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def tags(self) -> dict:
        """version -> tag, for every tag that is a semver (with or without a `v`)."""
        out = {}
        for tag in git(["tag", "-l"], cwd=self.repo).decode("utf-8", "replace").split():
            m = TAG_RE.match(tag)
            if m and (m.group(1) not in out or tag.startswith("v")):
                out[m.group(1)] = tag
        return out

    def latest(self) -> str | None:
        if self.folder:
            return None
        versions = list(self.tags())
        final = [x for x in versions if "-" not in x.split("+")[0]]
        pool = final or versions
        return max(pool, key=semver_key) if pool else None

    def files_at(self, version: str | None):
        """(files, version, commit) of one version. Without a version: the latest
        release tag, or the latest commit when the repository has no tags."""
        if self.folder:
            files = check_entries(read_folder(self.folder))
            ver = manifest_of(files).get("version")
            if version and version != ver:
                raise Refused(f"{self.given} is a plain folder holding version {ver}; "
                              f"it has no version {version}.")
            return files, ver, None
        tags = self.tags()
        if version:
            if version not in tags:
                raise Refused(f"{self.given} has no version {version} (no tag v{version}).")
            ref = tags[version]
        else:
            version = self.latest()
            ref = tags[version] if version else "HEAD"
        commit = git(["rev-parse", "--verify", "--quiet", ref + "^{commit}"],
                     cwd=self.repo).decode().strip()
        files = check_entries(self._tree(commit))
        man_ver = manifest_of(files).get("version")
        if version and man_ver != version:
            raise Refused(f"Tag {ref} holds version {man_ver!r} in its agent.yaml, not {version}.")
        return files, man_ver, commit

    def _tree(self, commit: str) -> dict:
        out = git(["ls-tree", "-r", "-z", "--full-tree", commit], cwd=self.repo)
        items = []
        for rec in out.split(b"\0"):
            if not rec:
                continue
            head, _, path = rec.partition(b"\t")
            mode, kind, obj = head.decode().split()
            name = path.decode("utf-8", "surrogateescape")
            if kind == "commit" or mode == "160000":
                raise Refused(f"{name} is a git submodule; templates can't hold one (declare it in repos).")
            if kind != "blob":
                raise Refused(f"{name} isn't a plain file, folder or link.")
            items.append((name, mode, obj))
        if len(items) > FILES_MAX:
            raise Refused("This template has too many files.")
        blobs = self._blobs([obj for _, _, obj in items])
        files = {}
        for name, mode, obj in items:
            data = blobs[obj]
            if mode == "120000":
                files[name] = {"kind": "link", "target": data.decode("utf-8", "surrogateescape")}
            else:
                files[name] = {"kind": "file", "data": data, "mode": 0o755 if mode == "100755" else 0o644}
        return files

    def _blobs(self, objs: list) -> dict:
        want = sorted(set(objs))
        if not want:
            return {}
        sizes = git(["cat-file", "--batch-check"], cwd=self.repo, data=("\n".join(want) + "\n").encode())
        total = 0
        for line in sizes.decode().splitlines():
            parts = line.split()
            if len(parts) != 3:
                raise Refused("The template's repository is damaged.")
            if int(parts[2]) > FILE_MAX:
                raise Refused("A file in this template is too big.")
            total += int(parts[2])
        if total > TOTAL_MAX:
            raise Refused("This template is too big once unpacked.")
        out = git(["cat-file", "--batch"], cwd=self.repo, data=("\n".join(want) + "\n").encode())
        blobs, at = {}, 0
        for obj in want:
            nl = out.index(b"\n", at)
            sha, _kind, size = out[at:nl].decode().split()
            size = int(size)
            blobs[sha] = out[nl + 1:nl + 1 + size]
            at = nl + 1 + size + 1
        return blobs


def manifest_of(files: dict) -> dict:
    e = files.get("agent.yaml")
    if not e or e.get("kind") != "file":
        raise Refused("This template has no agent.yaml.")
    man = read_yaml_text(e["data"].decode("utf-8", "replace"), "agent.yaml")
    if not isinstance(man, dict):
        raise Refused("agent.yaml must be a mapping.")
    return man


def materialise(files: dict, root: str) -> None:
    """Write already-checked files into an empty scratch folder (for the validator)."""
    for rel in sorted(files, key=lambda r: (r.count("/"), r)):
        e = files[rel]
        p = os.path.join(root, rel)
        if e["kind"] == "dir":
            os.makedirs(p, exist_ok=True)
        elif e["kind"] == "link":
            os.makedirs(os.path.dirname(p), exist_ok=True)
            os.symlink(e["target"], p)
        else:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(e["data"])
            os.chmod(p, e.get("mode") or 0o644)


def validate_files(files: dict) -> v.Report:
    with tempfile.TemporaryDirectory(prefix=f"{TOOL}-check-") as tmp:
        materialise(files, tmp)
        return v.validate_template(Path(tmp))


# ---------------------------------------------------------------- the install plan

def install_plan(man, files, answers, agent_name, now, folder, source, commit=None,
                 own_skills=None, own_layer=None, runtime_mcp=None, strict=True) -> dict:
    """Everything an install writes, as path -> entry with a `layer` (template,
    mirror, seed, own, host). Pure: the same inputs give the same plan, byte for byte.
    Mirrors agent8's installer, without agent8's own entries."""
    block = man.get(BLOCK) if isinstance(man.get(BLOCK), dict) else {}
    answers = check_answers(block.get("setup"), answers, strict)
    version = man.get("version")
    if not isinstance(version, str) or not SEMVER_RE.match(version):
        raise Refused("agent.yaml has no exact version (semver).")
    if files.get("AGENTS.md", {}).get("kind") != "file":
        raise Refused("This template has no AGENTS.md.")
    for p in sorted(OWN_ROOT):
        if p in files:
            raise Refused(f"{p} belongs to a copy, not to a template.")
    if ".agent8" in files:
        raise Refused(".agent8/ belongs to a copy, not to a template.")
    data_patterns = block.get("data") if isinstance(block.get("data"), list) else []
    data = v.DataList([p for p in data_patterns if isinstance(p, str) and p.strip()])
    layout = (block.get("layout") or {}).get("skills") if isinstance(block.get("layout"), dict) else None
    if layout not in SKILL_LAYOUTS:
        layout = next((c for c in SKILL_LAYOUTS if files.get(c, {}).get("kind") == "dir"), None)
    tpre = f".agent8/template/{version}/"
    out = {}

    def put(rel, entry, layer):
        if not rel_ok(rel):
            raise Refused(f"{TOOL} won't write {rel[:200]!r}.")
        if rel in out:
            raise Refused(f"{rel} would be written twice: the template has two files for it.")
        e = {k: val for k, val in entry.items() if k in ("kind", "data", "mode", "target")}
        e["layer"] = layer
        out[rel] = e

    for p in sorted(files):
        put(tpre + p, files[p], "template")

    seeds, notes = {}, []
    own_skills = dict(own_skills or {})
    for p in sorted(files):
        e = files[p]
        if not p.startswith("seed/") or e["kind"] == "dir":
            continue
        t = p[len("seed/"):]
        if e["kind"] == "link":
            notes.append(f"seed/{t} is a link; left out.")
            continue
        if t.split("/")[0] in (".agent8", ".git", "skills") or t in COMPOSED \
                or t == ".claude/settings.local.json":
            raise Refused(f"seed/{t} would write over a file the installer owns.")
        if t not in OWN_ROOT and not data.matches(t):
            raise Refused(f"seed/{t} isn't a data path or one of the copy's own files.")
        body = e["data"]
        try:
            body = fill_answers(body.decode("utf-8"), answers).encode("utf-8")
        except UnicodeDecodeError:
            pass
        seeds[t] = {"kind": "file", "data": body, "mode": e["mode"]}

    for p in sorted(files):
        e = files[p]
        if e["kind"] == "dir" or p in COMPOSED or p.startswith("seed/"):
            continue
        if layout and p.startswith(layout + "/"):
            continue
        if any(p.startswith(t + "/") for t in SKILL_TARGETS):
            continue
        if p.split("/")[0] == "skills":
            raise Refused("The template's skills/ folder collides with the copy's own skills.")
        if p == ".claude/settings.local.json":
            raise Refused(f"{p} belongs to a copy, not to a template.")
        if data.matches(p):
            raise Refused(f"{p} is both a template file and data.")
        put(p, e, "mirror")
    for t in sorted(seeds):
        put(t, seeds[t], "seed")

    names = {"name": agent_name, "template": man.get("name"), "version": version}
    own_layer = own_layer or {}
    identity = seeds.get("identity.md")
    if own_layer.get("identity.md") is not None:
        identity = file_entry(own_layer["identity.md"])
    if not identity:
        identity = file_entry(IDENTITY_DEFAULT.format(**names))
        put("identity.md", identity, "own")
    local = seeds.get("LOCAL.md")
    if own_layer.get("LOCAL.md") is not None:
        local = file_entry(own_layer["LOCAL.md"])
    if not local:
        local = file_entry(LOCAL_DEFAULT)
        put("LOCAL.md", local, "own")
    put("skills", {"kind": "dir"}, "own")
    copy_man = {"name": slug(agent_name), "version": "0.0.1",
                "description": f"{agent_name}, installed from {names['template']} {version}",
                "extends": f"{source}@{version}", BLOCK: {"format": FORMAT}}
    put("agent.yaml", file_entry("# agent.yaml — this copy's own manifest: it extends its template at one "
                                 "exact version.\n" + "\n".join(to_yaml(copy_man)) + "\n"), "own")

    tskills = {}
    if layout:
        for p in sorted(files):
            if p.startswith(layout + "/") and files[p]["kind"] != "dir":
                rest = p[len(layout) + 1:]
                if "/" in rest:
                    name, sub = rest.split("/", 1)
                    tskills.setdefault(name, {})[sub] = files[p]
    for target in SKILL_TARGETS:
        for name in sorted(set(tskills) | set(own_skills)):
            src = own_skills.get(name) or tskills[name]
            for sub in sorted(src):
                put(f"{target}/{name}/{sub}", src[sub], "host")

    tagents = files["AGENTS.md"]["data"].decode("utf-8", "replace")
    put("AGENTS.md", file_entry(
        f"<!-- Written by {TOOL} from the template, identity.md and LOCAL.md. Edits here are lost: "
        "change identity.md or LOCAL.md instead. -->\n\n" + tagents.rstrip("\n")
        + "\n\n## Identity\n\n" + identity["data"].decode("utf-8", "replace").rstrip("\n")
        + "\n\n## Local rules\n\n" + local["data"].decode("utf-8", "replace").rstrip("\n") + "\n"), "host")
    put("CLAUDE.md", file_entry(f"@{tpre}AGENTS.md\n@identity.md\n@LOCAL.md\n"), "host")
    tmcp = json_of(files.get(".mcp.json"), ".mcp.json") or {}
    omcp_src = seeds.get("mcp.local.json")
    if own_layer.get("mcp.local.json") is not None:
        omcp_src = file_entry(own_layer["mcp.local.json"])
    try:
        omcp = json_of(omcp_src, "mcp.local.json") or {}
    except Refused:
        if own_layer.get("mcp.local.json") is None:
            raise
        omcp = {}                         # the copy's own file never blocks an update
    if runtime_mcp:
        omcp = compose(omcp, {"mcpServers": runtime_mcp})
    mcp = compose(tmcp, omcp) or {}
    if mcp:
        put(".mcp.json", file_entry(json.dumps(mcp, indent=2, sort_keys=True) + "\n"), "host")
    tset = json_of(files.get(".claude/settings.json"), ".claude/settings.json") or {}
    if tset:
        put(".claude/settings.json", file_entry(json.dumps(tset, indent=2, sort_keys=True) + "\n"), "host")
    if files.get(".codex/config.toml", {}).get("kind") == "file":
        put(".codex/config.toml", files[".codex/config.toml"], "host")

    secrets = []
    for s in block.get("secrets") or []:
        if isinstance(s, dict) and isinstance(s.get("item"), str) and s["item"] not in [x["item"] for x in secrets]:
            secrets.append({"item": s["item"], "status": "missing"})
    digest = files_digest(files)
    tref = {"source": source, "version": version, "digest": digest}
    if commit and COMMIT_RE.match(commit):
        tref["commit"] = commit
    record = {"format": FORMAT, "template": tref, "installed_at": now, "updated_at": now, "answers": answers}
    if secrets:
        record["secrets"] = secrets
    put(".agent8/instance.yaml", file_entry(
        "# .agent8/instance.yaml — written by the installer. Never holds a secret value.\n"
        + "\n".join(to_yaml(record)) + "\n"), "host")

    env = {}
    raw_env = block.get("env") if isinstance(block.get("env"), dict) else {}
    for k in sorted(raw_env):
        val = raw_env[k]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)) or not isinstance(val, (str, int, float, bool)):
            raise Refused(f"The template's env has an entry {TOOL} can't use: {str(k)[:64]}.")
        val = fill_answers(str(val), answers).replace("{{folder}}", folder)
        if v.VAULT_LOOSE_RE.search(val) or v.looks_secret(val):
            raise Refused(f"The template's env {k} holds a secret; secrets are vault names.")
        env[k] = val

    repos = []
    for r in block.get("repos") or []:
        if not isinstance(r, dict):
            continue
        path, url, ref = r.get("path"), r.get("url"), r.get("ref")
        path = path.strip("/") if isinstance(path, str) else path
        if not rel_ok(path) or path.split("/")[0] in (".agent8", ".git"):
            raise Refused(f"A repository's folder isn't a path {TOOL} will write: {str(path)[:100]!r}.")
        if not data.matches(path, True):
            raise Refused(f"Repository {path} must be a data path of the template.")
        if any(x["path"] == path or x["path"].startswith(path + "/") or path.startswith(x["path"] + "/")
               for x in repos):
            raise Refused(f"Repository {path} sits inside another repository.")
        if any(w == path or w.startswith(path + "/") or path.startswith(w + "/") for w, e in out.items()
               if e["layer"] != "seed"):
            raise Refused(f"Repository {path} collides with the template's files.")
        if not isinstance(url, str) or not REPO_URL_RE.match(url):
            raise Refused(f"Repository {path} has an address {TOOL} won't clone (https or ssh only).")
        if ref is not None and (not isinstance(ref, str) or not REF_RE.match(ref) or ".." in ref):
            raise Refused(f"Repository {path} names a branch {TOOL} can't read.")
        repos.append({"path": path, "url": url, "ref": ref, "required": r.get("required") is not False})

    final = dict(out)
    for rel in list(out):
        bits = rel.split("/")
        for i in range(1, len(bits)):
            final.setdefault("/".join(bits[:i]), {"kind": "dir"})
    check_links(final)
    return {"writes": out, "version": version, "digest": digest, "source": source, "env": env,
            "repos": repos, "secrets": secrets, "notes": notes, "layout": layout, "answers": answers,
            "data": data, "record": record, "tskills": sorted(tskills)}


# ---------------------------------------------------------------- writing, never through a link

def _walk(base_fd: int, rel: str, make=True):
    """(parent fd, leaf) for rel under base_fd, every folder opened without following
    a link. The caller closes the fd."""
    parts = rel.split("/")
    fd = os.dup(base_fd)
    try:
        for part in parts[:-1]:
            if make:
                try:
                    os.mkdir(part, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
    except OSError:
        os.close(fd)
        raise Refused(f"{rel}: a folder on the way is missing or is a link.")
    return fd, parts[-1]


def write_entry(base_fd: int, rel: str, e: dict, only_if_missing=False) -> bool:
    pfd, leaf = _walk(base_fd, rel)
    try:
        if e["kind"] == "dir":
            try:
                os.mkdir(leaf, 0o755, dir_fd=pfd)
            except FileExistsError:
                st = os.stat(leaf, dir_fd=pfd, follow_symlinks=False)
                if not statmod.S_ISDIR(st.st_mode):
                    raise Refused(f"{rel} is in the way.")
            return True
        if e["kind"] == "link":
            try:
                os.symlink(e["target"], leaf, dir_fd=pfd)
            except FileExistsError:
                if only_if_missing:
                    return False
                raise Refused(f"{rel} is already there.")
            return True
        try:
            fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         e.get("mode") or 0o644, dir_fd=pfd)
        except FileExistsError:
            if only_if_missing:
                return False
            raise Refused(f"{rel} is already there.")
        try:
            view = memoryview(e["data"])
            while view:
                view = view[os.write(fd, view):]
            os.fchmod(fd, e.get("mode") or 0o644)
        finally:
            os.close(fd)
        return True
    finally:
        os.close(pfd)


def lock(base_fd: int, rel: str, mode_dir=None) -> None:
    """Read-only: a file a-w, or a folder to `mode_dir`. Links have no mode."""
    pfd, leaf = _walk(base_fd, rel, make=False)
    try:
        st = os.stat(leaf, dir_fd=pfd, follow_symlinks=False)
        if statmod.S_ISLNK(st.st_mode):
            return
        if statmod.S_ISDIR(st.st_mode):
            if mode_dir is not None:
                os.chmod(leaf, mode_dir, dir_fd=pfd)
            return
        os.chmod(leaf, (st.st_mode & 0o777) & ~0o222, dir_fd=pfd)
    finally:
        os.close(pfd)


def lstat_rel(base_fd: int, rel: str):
    """os.lstat of rel, or None when missing; "link-above" when a folder on the way is a link."""
    parts = rel.split("/")
    fd = os.dup(base_fd)
    try:
        for part in parts[:-1]:
            try:
                st = os.stat(part, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return None
            if statmod.S_ISLNK(st.st_mode):
                return "link-above"
            if not statmod.S_ISDIR(st.st_mode):
                return None
            nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
        try:
            return os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
    finally:
        os.close(fd)


def disk_entry(base_fd: int, rel: str):
    st = lstat_rel(base_fd, rel)
    if st is None or st == "link-above":
        return None
    if statmod.S_ISDIR(st.st_mode):
        return {"kind": "dir"}
    pfd, leaf = _walk(base_fd, rel, make=False)
    try:
        if statmod.S_ISLNK(st.st_mode):
            return {"kind": "link", "target": os.readlink(leaf, dir_fd=pfd)}
        if not statmod.S_ISREG(st.st_mode) or st.st_size > FILE_MAX:
            return {"kind": "other"}
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=pfd)
        with os.fdopen(fd, "rb") as fh:
            return {"kind": "file", "data": fh.read(), "mode": 0o755 if st.st_mode & 0o111 else 0o644}
    finally:
        os.close(pfd)


def same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    if a.get("kind") != b.get("kind"):
        return False
    if a["kind"] == "file":
        return a.get("data") == b.get("data")
    if a["kind"] == "link":
        return a.get("target") == b.get("target")
    return True


def make_writable(path: str) -> None:
    """Give back write access below path (folders and files, never through a link)."""
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            if not os.path.islink(p):
                try:
                    os.chmod(p, (os.lstat(p).st_mode & 0o777) | 0o200)
                except OSError:
                    pass
    if os.path.isdir(path) and not os.path.islink(path):
        os.chmod(path, (os.lstat(path).st_mode & 0o777) | 0o700)


def remove_tree(path: str) -> None:
    if os.path.lexists(path):
        if os.path.isdir(path) and not os.path.islink(path):
            make_writable(path)
            shutil.rmtree(path)
        else:
            os.unlink(path)


def clone_repos(folder: str, repos: list) -> list:
    """Each `repos` entry cloned once: git only, no submodules, no local or ext transports."""
    done = []
    for r in repos:
        dest = os.path.join(folder, r["path"])
        if os.path.lexists(dest):
            done.append({"path": r["path"], "ok": True, "kept": True})
            continue
        if "/" in r["path"]:
            base = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                pfd, _ = _walk(base, r["path"])
                os.close(pfd)
            finally:
                os.close(base)
        argv = ["-c", "protocol.file.allow=never", "clone", "--quiet", "--no-recurse-submodules"]
        if r.get("ref") and not COMMIT_RE.match(r["ref"]):
            argv += ["--branch", r["ref"]]
        argv += ["--", r["url"], r["path"]]
        why = None
        try:
            git(argv, cwd=folder)
            if r.get("ref") and COMMIT_RE.match(r["ref"]):
                git(["-C", dest, "checkout", "--quiet", "--detach", r["ref"]], cwd=folder)
        except Refused as exc:
            why = str(exc)
        if why and r.get("required", True):
            raise Refused(f"Couldn't clone {r['url']} into {r['path']}: {why}")
        done.append({"path": r["path"], "ok": not why, "why": why})
    return done


# ---------------------------------------------------------------- what a template runs

def runs_code(files: dict, layout) -> list:
    """Hooks, MCP servers and executables, in plain lines; an executable no hook and
    no MCP server names is called out as undeclared."""
    lines, said = [], ""
    settings = json_of(files.get(".claude/settings.json"), ".claude/settings.json") or {}
    for event, groups in (settings.get("hooks") or {}).items() if isinstance(settings.get("hooks"), dict) else []:
        for g in groups or []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                if isinstance(h, dict) and h.get("type") == "command":
                    lines.append(f"hook {event}: {h.get('command')}")
                    said += " " + json.dumps(h)
    mcp = json_of(files.get(".mcp.json"), ".mcp.json") or {}
    for name, cfg in (mcp.get("mcpServers") or {}).items() if isinstance(mcp.get("mcpServers"), dict) else []:
        if isinstance(cfg, dict) and cfg.get("command"):
            lines.append(f"MCP server {name}: {cfg['command']} {' '.join(map(str, cfg.get('args') or []))}".rstrip())
            said += " " + json.dumps(cfg)
    # Instructions that tell the agent to run a script declare it too.
    for p, e in files.items():
        if e["kind"] == "file" and (p == "AGENTS.md" or (layout and p.startswith(layout + "/")
                                                         and p.endswith(".md"))):
            said += " " + e["data"].decode("utf-8", "replace")
    for p in sorted(files):
        e = files[p]
        if e["kind"] != "file" or p.startswith("seed/"):
            continue
        if not (e.get("mode", 0) & 0o111 or e["data"][:2] == b"#!"):
            continue
        in_skill = layout and p.startswith(layout + "/")
        if p in said or in_skill:
            lines.append(f"executable: {p}")
        else:
            lines.append(f"executable: {p} (undeclared: no hook, MCP server, skill or AGENTS.md names it)")
    return lines


# ---------------------------------------------------------------- commands

def out(msg="", err=False):
    print(msg, file=sys.stderr if err else sys.stdout)


def confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise Refused("Add --yes to go ahead without a question (nothing was written).")
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def ask_missing(setup, answers: dict, only=None) -> dict:
    """Asks the required questions still unanswered, when someone is at the keyboard."""
    answers = dict(answers)
    for q in setup or []:
        if not isinstance(q, dict) or not isinstance(q.get("id"), str):
            continue
        qid = q["id"]
        if only is not None and qid not in only:
            continue
        if qid in answers or not q.get("required") or q.get("default") not in (None, "", []):
            continue
        if not sys.stdin.isatty():
            continue
        hint = f" ({', '.join(q.get('choices') or [])})" if q.get("choices") else ""
        try:
            raw = input(f"{q.get('prompt') or qid}{hint}: ")
        except EOFError:
            continue
        if raw.strip():
            k, val = parse_answer(setup, f"{qid}={raw.strip()}")
            answers[k] = val
    return answers


def collect_answers(setup, args) -> dict:
    answers = {}
    if getattr(args, "answers", None):
        try:
            doc = read_yaml_text(Path(args.answers).read_text(encoding="utf-8"), args.answers)
        except OSError as exc:
            raise Refused(f"Can't read {args.answers}: {exc}")
        if not isinstance(doc, dict):
            raise Refused(f"{args.answers} must map question ids to answers.")
        answers.update(doc)
    for raw in getattr(args, "answer", None) or []:
        k, val = parse_answer(setup, raw)
        answers[k] = val
    return answers


def print_report(rep: v.Report) -> None:
    rep.print()


def git_listed(root: Path):
    """The files `git add -A` would commit (tracked + untracked not ignored), or None
    when root isn't the top of a git repository."""
    try:
        top = git(["rev-parse", "--show-toplevel"], cwd=str(root)).decode().strip()
    except Refused:
        return None
    if os.path.realpath(top) != os.path.realpath(root):
        return None
    raw = git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=str(root))
    return sorted({p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p})


def copy_listed(root: Path, listed: list, dest: str) -> None:
    for rel in listed:
        src = os.path.join(root, rel)
        if not os.path.lexists(src):
            continue  # deleted but still tracked: it won't be in the next commit either
        tgt = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(tgt), exist_ok=True)
        if os.path.islink(src):
            os.symlink(os.readlink(src), tgt)
        elif os.path.isfile(src):
            shutil.copy2(src, tgt)


def check_layout(root: Path, rep: v.Report) -> None:
    """Declared paths exist (what validate.py doesn't already check)."""
    man = v.load_yaml(root / "agent.yaml", v.Report())
    block = man.get(BLOCK) if isinstance(man, dict) else None
    if not isinstance(block, dict):
        return
    layout = (block.get("layout") or {}).get("skills") if isinstance(block.get("layout"), dict) else None
    if isinstance(layout, str) and not (root / layout).is_dir():
        rep.error(f"x-agent8.layout.skills names {layout}/, which isn't in the template")


def cmd_check(args) -> int:
    root = Path(args.dir)
    if not root.is_dir():
        out(f"{root} is not a folder", err=True)
        return 2
    try:
        if (root / ".agent8" / "instance.yaml").is_file():
            rep = v.validate_instance(root)
            kind = "installed copy"
        else:
            kind = "template"
            listed = None if args.all_files else git_listed(root)
            if listed is not None:
                with tempfile.TemporaryDirectory(prefix=f"{TOOL}-check-") as tmp:
                    copy_listed(root, listed, tmp)
                    rep = v.validate_template(Path(tmp))
                    check_layout(Path(tmp), rep)
                    files = read_folder(tmp)
                rep.info(f"checked the {len(listed)} file(s) git would commit (ignored files left out; "
                         "--all-files checks the whole folder)")
            else:
                rep = v.validate_template(root)
                check_layout(root, rep)
                files = read_folder(str(root))
            block = (manifest_of(files).get(BLOCK) or {}) if "agent.yaml" in files else {}
            layout = (block.get("layout") or {}).get("skills") if isinstance(block, dict) and \
                isinstance(block.get("layout"), dict) else None
            try:
                code = runs_code(files, layout)
            except Refused:
                code = []
            rep.infos = [m for m in rep.infos if not m.startswith("runs code:")]
            for line in code:
                if "(undeclared" in line:
                    rep.warn(line)
                else:
                    rep.info("runs code: " + line)
    except v.FormatTooNew as exc:
        out(f"error: {exc}")
        return 3
    except v.FormatTooOld as exc:
        out(f"error: {exc}")
        return 1
    except Refused as exc:
        out(f"error: {exc}")
        return 1
    print_report(rep)
    if rep.errors:
        out(f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
        return 1
    out(f"valid {kind} ({len(rep.warnings)} warning(s))")
    return 0


MIT = """MIT License

Copyright (c) {year} {author}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def scaffold_files(name: str, description: str, author: str | None) -> dict:
    man = {"spec_version": "0.1.0", "name": name, "version": "0.1.0", "description": description}
    if author:
        man["author"] = author
    man["license"] = "MIT"
    man[BLOCK] = {"format": FORMAT, "layout": {"skills": ".claude/skills"},
                  "data": ["/memory/", "/logs/"],
                  "setup": [{"id": "owner_name", "prompt": "Your name (the agent's owner)",
                             "type": "string", "required": True}],
                  "requires": {"harnesses": [{"name": "claude-code"}, {"name": "codex"}]}}
    title = name.replace("-", " ").capitalize()
    return {
        "agent.yaml": "# agent.yaml — the template's manifest (OpenGAP + the x-agent8 block).\n"
                      + "\n".join(to_yaml(man)) + "\n",
        "AGENTS.md": f"# {title}\n\n{description}\n\n## Your files\n\nYour identity is in `identity.md`. "
                     "Your own rules and improvements go in `LOCAL.md` and your own skills in `skills/`. "
                     "Never edit the template files; they are replaced on every update.\n\n"
                     "Write what you learn in `memory/`: it is yours and never leaves this folder.\n",
        "CLAUDE.md": "@AGENTS.md\n@identity.md\n@LOCAL.md\n",
        "README.md": f"# {title}\n\n{description}\n\nAn agent template in the open agent template format "
                     f"(v{FORMAT}). Check it with `{TOOL} check`, install it with "
                     f"`{TOOL} install <this repo's git URL>`.\n",
        "LICENSE": MIT.format(year=_dt.date.today().year, author=author or "the authors"),
        ".gitignore": "# The data list of agent.yaml: never committed.\n/memory/\n/logs/\n",
        "seed/identity.md": "# Identity\n\nYou work for {{answer:owner_name}}. Write who you are, "
                            "who you work for and your owner's hard rules here.\n",
        "seed/LOCAL.md": "# Local rules\n\nYour own rules and improvements go here.\n",
        "seed/memory/README.md": "# Memory\n\nWhat you learn goes here, one file per topic.\n",
        ".claude/skills/remember/SKILL.md": "---\nname: remember\ndescription: Save something worth "
                                            "keeping to memory/ so it is there next time.\n---\n\n"
                                            "Write it to `memory/<topic>.md`, short and dated.\n",
    }


def cmd_new(args) -> int:
    dest = Path(args.dir)
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        out(f"error: {dest} already has files in it; pick an empty or new folder.")
        return 1
    name = args.name or slug(dest.resolve().name)
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or len(name) > 64:
        out("error: --name must be lowercase letters, digits and hyphens, starting with a letter.")
        return 2
    description = args.description or f"The {name} agent."
    for rel, text in scaffold_files(name, description, args.author).items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    out(f"Created the template {name} in {dest}.")
    out(f"Next: edit AGENTS.md, then `{TOOL} check {dest}`, commit, and tag a release v0.1.0.")
    return 0


def plain_list(title: str, items) -> None:
    items = list(items)
    if items:
        out(f"{title}:")
        for x in items:
            out(f"  - {x}")


def cmd_install(args) -> int:
    dest = os.path.abspath(args.dest or slug(re.sub(r"(\.git)?/*$", "", args.source).rsplit("/", 1)[-1]
                                             .rsplit(":", 1)[-1]))
    if os.path.lexists(dest) and (not os.path.isdir(dest) or os.path.islink(dest) or os.listdir(dest)):
        raise Refused(f"{dest} already has files in it. Pick another folder.")
    with Source(args.source) as src:
        files, version, commit = src.files_at(args.version)
        man = manifest_of(files)
        fmt = format_check(man)          # before anything is written
        rep = validate_files(files)
        if rep.errors:
            print_report(rep)
            raise Refused(f"This template isn't valid ({len(rep.errors)} error(s)); {TOOL} won't install it.")
        block = man.get(BLOCK) or {}
        setup = block.get("setup") or []
        answers = ask_missing(setup, collect_answers(setup, args))
        agent_name = args.name or os.path.basename(dest)
        plan = install_plan(man, files, answers, agent_name, args.now or now_utc(), dest,
                            src.name, commit)
        out(f"{man.get('name')} {version} from {src.name}")
        if fmt["skipped"]:
            out(f"This template also uses {', '.join(fmt['skipped'])}, which this {TOOL} doesn't know yet; "
                "they are skipped.")
        layout = plan["layout"]
        plain_list("It runs code", runs_code(files, layout))
        plain_list("It needs these secrets (give them as environment variables when you start it)",
                   [f"{s['item']}: " + ", ".join(sorted(n for x in block.get("secrets") or []
                                                        if isinstance(x, dict) and x.get("item") == s["item"]
                                                        for n in (x.get("env") or {}))) for s in plan["secrets"]])
        plain_list("It will clone", [f"{r['url']} into {r['path']}" for r in plan["repos"]])
        req = block.get("requires") if isinstance(block.get("requires"), dict) else {}
        plain_list("It needs", [f"{k}: {', '.join(x.get('name', '') if isinstance(x, dict) else str(x) for x in req[k])}"
                                for k in ("harnesses", "tools", "logins", "plugins", "skills")
                                if isinstance(req.get(k), list) and req[k]])
        for w in rep.warnings:
            out(f"warning: {w}")
        if not confirm(f"Install it into {dest}?", args.yes):
            out("Nothing was written.")
            return 1
        made = not os.path.exists(dest)
        os.makedirs(dest, exist_ok=True)
        fd = os.open(dest, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if os.listdir(fd):
                raise Refused(f"{dest} already has files in it. Pick another folder.")
            try:
                clone_repos(dest, plan["repos"])
                writes = plan["writes"]
                for rel in sorted(writes):
                    write_entry(fd, rel, writes[rel], only_if_missing=writes[rel]["layer"] == "seed")
                for rel in sorted(writes, key=lambda r: (-r.count("/"), r)):
                    if writes[rel]["layer"] in ("mirror", "template") and writes[rel]["kind"] != "dir":
                        lock(fd, rel)
                lock(fd, f".agent8/template/{version}", mode_dir=0o555)
            except BaseException:
                for name in os.listdir(dest):
                    remove_tree(os.path.join(dest, name))
                if made:
                    os.rmdir(dest)
                raise
        finally:
            os.close(fd)
    out(f"Installed {man.get('name')} {version} as {agent_name} in {dest}.")
    out("The template is read-only under .agent8/template/; the copy's own layer is identity.md, "
        "LOCAL.md, skills/ and mcp.local.json.")
    plain_list("Start it with these environment variables", [f"{k}={val}" for k, val in plan["env"].items()])
    for n in plan["notes"]:
        out(f"note: {n}")
    return 0


def read_copy(folder: str):
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    rec_e = disk_entry(fd, ".agent8/instance.yaml")
    man_e = disk_entry(fd, "agent.yaml")
    if not rec_e or rec_e["kind"] != "file":
        os.close(fd)
        raise Refused(f"{folder} has no .agent8/instance.yaml: it wasn't installed from a template.")
    if not man_e or man_e["kind"] != "file":
        os.close(fd)
        raise Refused(f"{folder} has no agent.yaml of its own.")
    rec = read_yaml_text(rec_e["data"].decode("utf-8", "replace"), ".agent8/instance.yaml")
    man_text = man_e["data"].decode("utf-8", "replace")
    man = read_yaml_text(man_text, "agent.yaml")
    if not isinstance(rec, dict) or not isinstance(rec.get("template"), dict) or not isinstance(man, dict):
        os.close(fd)
        raise Refused("This copy's instance record or agent.yaml can't be read.")
    return fd, rec, man, man_text


def read_dir(folder: str, fd: int, rel: str):
    """read_folder of a real folder inside the copy (never through a link), or None."""
    st = lstat_rel(fd, rel)
    if st in (None, "link-above") or not statmod.S_ISDIR(st.st_mode):
        return None
    return read_folder(os.path.join(folder, rel))


def own_state(folder: str, fd: int):
    own_layer = {}
    for name in ("identity.md", "LOCAL.md", "mcp.local.json"):
        e = disk_entry(fd, name)
        own_layer[name] = e["data"] if e and e.get("kind") == "file" else None
    own_skills = {}
    tree = read_dir(folder, fd, "skills") or {}
    if tree:
        for p, e in tree.items():
            if e["kind"] != "dir" and "/" in p:
                name, sub = p.split("/", 1)
                own_skills.setdefault(name, {})[sub] = e
    return own_layer, own_skills


def mcp_servers(entry):
    try:
        d = json.loads(entry["data"].decode("utf-8")) if entry and entry.get("kind") == "file" else {}
    except (ValueError, UnicodeDecodeError):
        return None
    s = d.get("mcpServers") if isinstance(d, dict) else None
    return s if isinstance(s, dict) else {}


def update_compute(folder, fd, rec, man, man_text, src, to, get_answers, now):
    """Everything a switch does, computed before anything is written."""
    tref = rec["template"]
    old_ver = tref.get("version")
    if not isinstance(old_ver, str) or not SEMVER_RE.match(old_ver):
        raise Refused("This copy's instance record doesn't say which version it runs.")
    format_check({BLOCK: {"format": rec.get("format")}}, "update this agent")
    for d in (".agent8", ".agent8/template"):
        st = lstat_rel(fd, d)
        if st in (None, "link-above") or not statmod.S_ISDIR(st.st_mode):
            raise Refused(f"{d} isn't a real folder in this copy; {TOOL} won't switch it.")
    ext = v.parse_extends(man.get("extends"))
    if not ext or ext != (tref.get("source"), old_ver):
        raise Refused("agent.yaml's extends and .agent8/instance.yaml disagree; fix them first.")
    old_line = [ln for ln in man_text.split("\n") if re.match(r"^extends\s*:", ln)]
    if len(old_line) != 1:
        raise Refused("agent.yaml's extends line can't be found.")

    new_ver = to or src.latest()
    if not new_ver:
        raise Refused(f"{src.given} has no release tags (vX.Y.Z) to switch to.")
    if new_ver == old_ver:
        raise Refused(f"This agent already runs {old_ver}.")
    new_files, new_ver, new_commit = src.files_at(new_ver)
    new_man = manifest_of(new_files)
    fmt = format_check(new_man, f"switch to {new_ver}")      # before anything is written
    rep = validate_files(new_files)
    if rep.errors:
        print_report(rep)
        raise Refused(f"Version {new_ver} isn't a valid template; {TOOL} won't switch to it.")
    extra_answers = get_answers((new_man.get(BLOCK) or {}).get("setup") or [])

    # The version it runs now: the source's, or the copy's own if that one matches the record.
    try:
        on_disk = read_dir(folder, fd, f".agent8/template/{old_ver}")
        on_disk = check_entries(on_disk) if on_disk is not None else None
    except Refused:
        on_disk = None
    old_files = None
    notes = []
    if on_disk is not None and files_digest(on_disk) == tref.get("digest"):
        old_files = on_disk
    else:
        try:
            cand, _, _ = src.files_at(old_ver)
            if files_digest(cand) == tref.get("digest") or on_disk is None:
                old_files = cand
        except Refused:
            pass
        if old_files is None:
            old_files = on_disk
        if on_disk is not None:
            notes.append(f".agent8/template/{old_ver}/ was edited by hand; those edits go with the switch.")
    if old_files is None:
        raise Refused(f"Version {old_ver} can't be found, in the copy or at {src.given}.")
    old_man = manifest_of(old_files)

    own_layer, own_skills = own_state(folder, fd)
    old_setup = (old_man.get(BLOCK) or {}).get("setup") or []
    new_setup = (new_man.get(BLOCK) or {}).get("setup") or []
    rec_answers = rec.get("answers") if isinstance(rec.get("answers"), dict) else {}
    new_ids = {q.get("id") for q in new_setup if isinstance(q, dict)}
    answers_all = dict(rec_answers)
    answers_all.update({k: val for k, val in extra_answers.items() if k in new_ids or k in rec_answers})
    answers_all = ask_missing(new_setup, answers_all)
    new_answers = check_answers(new_setup, answers_all)    # refuses a required question unanswered
    old_answers = check_answers(old_setup, answers_all, strict=False)
    old_ids = {q.get("id") for q in old_setup if isinstance(q, dict)}
    asks = [q.get("id") for q in new_setup if isinstance(q, dict) and q.get("id") not in old_ids]

    agent_name = man.get("name") or "agent"
    disk_mcp = mcp_servers(disk_entry(fd, ".mcp.json"))
    pure_old = _plan_lenient(old_man, old_files, old_answers, agent_name, now, folder, tref["source"],
                             own_skills, own_layer, None)
    old_mcp = mcp_servers(pure_old["writes"].get(".mcp.json")) or {}
    runtime_mcp = {k: val for k, val in (disk_mcp or {}).items() if k not in old_mcp}
    old_plan = _plan_lenient(old_man, old_files, old_answers, agent_name, now, folder, tref["source"],
                             own_skills, own_layer, runtime_mcp)
    new_plan = install_plan(new_man, new_files, new_answers, agent_name, now, folder, tref["source"],
                            new_commit, own_skills=own_skills, own_layer=own_layer, runtime_mcp=runtime_mcp)
    ow, nw = old_plan["writes"], new_plan["writes"]

    def folder_part(w):
        return {r: e for r, e in w.items() if e["layer"] in ("mirror", "host") and r != ".agent8/instance.yaml"}
    old_f, new_f = folder_part(ow), folder_part(nw)

    def skill_dirs(w):
        return sorted({"/".join(r.split("/")[:3]) for r in w if any(r.startswith(t + "/") for t in SKILL_TARGETS)})
    sd_old, sd_new = skill_dirs(old_f), skill_dirs(new_f)

    def in_skill(r, dirs):
        return any(r.startswith(d + "/") for d in dirs)

    # Hand edits: backed up before they are replaced or removed.
    hand = []
    for rel, e in sorted(old_f.items()):
        if e["kind"] == "dir" or in_skill(rel, sd_old):
            continue
        disk = disk_entry(fd, rel)
        want = pure_old["writes"].get(rel, e) if rel in HOST_FILES else e
        if rel == "AGENTS.md" and disk and disk.get("kind") == "file" and want.get("kind") == "file":
            head = want["data"].split(b"\n\n## Identity\n\n", 1)[0]
            if disk["data"].startswith(head + b"\n\n## Identity\n\n"):
                continue
        if rel == ".mcp.json" and disk and disk.get("kind") == "file":
            d_s, w_s = mcp_servers(disk), mcp_servers(want) or {}
            if d_s is not None and all(d_s.get(k) == val for k, val in w_s.items()):
                continue
        if disk is not None and not same(disk, want):
            hand.append(rel)
    for d in sd_old:
        want = {r[len(d) + 1:]: e for r, e in old_f.items() if r.startswith(d + "/") and e["kind"] != "dir"}
        have = read_dir(folder, fd, d) or {}
        for sub, e in have.items():
            if e["kind"] != "dir" and not same(e, want.get(sub)):
                hand.append(f"{d}/{sub}")

    # Collisions: a new path where the copy already has something of its own.
    known = set(old_f) | {r for r, e in ow.items() if e["layer"] == "template"}
    collisions = []
    for rel in sorted(new_f):
        if rel in known or in_skill(rel, sd_old):
            continue
        bits = rel.split("/")
        for i in range(1, len(bits) + 1):
            sub = "/".join(bits[:i])
            st = lstat_rel(fd, sub)
            if st is None:
                break
            if st == "link-above":
                collisions.append(sub)
                break
            if i == len(bits) or not statmod.S_ISDIR(st.st_mode):
                if sub not in known:
                    collisions.append(sub)
                break
    for d in sd_new:
        if d not in sd_old and lstat_rel(fd, d) is not None:
            collisions.append(d)
    datas = [old_plan["data"], new_plan["data"]]
    repo_paths = sorted({r["path"] for r in old_plan["repos"] + new_plan["repos"]})
    removed = sorted(r for r, e in old_f.items() if r not in new_f and e["kind"] != "dir"
                     and not in_skill(r, sd_old) and not new_plan["data"].matches(r))
    kept_as_data = sorted(r for r, e in old_f.items() if r not in new_f and e["kind"] != "dir"
                          and not in_skill(r, sd_old) and new_plan["data"].matches(r))
    for rel in sorted(set(removed) | set(r for r in new_f) | set(sd_old)):
        first = rel.split("/")[0]
        bad = rel in OWN_ROOT or rel in ("agent.yaml", ".claude/settings.local.json") or first in ("skills", ".git") \
            or first == ".agent8" or any(d.matches(rel) for d in datas) \
            or any(rel == r or rel.startswith(r + "/") for r in repo_paths)
        if bad:
            collisions.append(rel)
    collisions = sorted(set(collisions))

    seeds = sorted(r for r, e in nw.items() if e["layer"] == "seed" and lstat_rel(fd, r) is None)
    repos = [r for r in new_plan["repos"] if lstat_rel(fd, r["path"]) is None]
    changed = sorted(p for p in set(old_files) | set(new_files)
                     if not same(old_files.get(p), new_files.get(p))
                     and not (old_files.get(p, {}).get("kind") == "dir" or new_files.get(p, {}).get("kind") == "dir"))
    return {"old_ver": old_ver, "new_ver": new_ver, "old_files": old_files, "new_files": new_files,
            "old_man": old_man, "new_man": new_man, "old_plan": old_plan, "new_plan": new_plan,
            "old_f": old_f, "new_f": new_f, "sd_old": sd_old, "sd_new": sd_new, "hand": sorted(set(hand)),
            "collisions": collisions, "removed": removed, "kept_as_data": kept_as_data, "seeds": seeds,
            "repos": repos, "changed": changed, "asks": asks, "answers": answers_all, "fmt": fmt,
            "commit": new_commit, "notes": notes, "warnings": rep.warnings, "extends_line": old_line[0]}


def _plan_lenient(man, files, answers, agent_name, now, folder, source, own_skills, own_layer, runtime_mcp):
    try:
        return install_plan(man, files, answers, agent_name, now, folder, source, own_skills=own_skills,
                            own_layer=own_layer, runtime_mcp=runtime_mcp, strict=False)
    except Refused as exc:
        raise Refused(f"{TOOL} can't rebuild this agent's current version from its files ({exc}).")


def describe_switch(c) -> None:
    old_s = (c["old_man"].get(BLOCK) or {}).get("secrets") or []
    new_s = (c["new_man"].get(BLOCK) or {}).get("secrets") or []
    names = lambda xs: {x.get("item") for x in xs if isinstance(x, dict)}  # noqa: E731
    out(f"Switch from {c['old_ver']} to {c['new_ver']}:")
    out(f"  template files changed: {len(c['changed'])}")
    for p in c["changed"][:50]:
        out(f"    {p}")
    plain_list("New skills", sorted(set(c["new_plan"]["tskills"]) - set(c["old_plan"]["tskills"])))
    plain_list("Skills removed", sorted(set(c["old_plan"]["tskills"]) - set(c["new_plan"]["tskills"])))
    plain_list("New setup questions", c["asks"])
    plain_list("New secrets", sorted(x for x in names(new_s) - names(old_s) if x))
    plain_list("New repositories to clone", [r["path"] for r in c["repos"]])
    plain_list("Starting files added (only where missing)", c["seeds"])
    plain_list("Files no longer in the template, kept as the agent's data", c["kept_as_data"])
    plain_list("Edited by hand, saved under .agent8/previous/ before the switch", c["hand"])
    plain_list("It runs code", runs_code(c["new_files"], c["new_plan"]["layout"]))
    for n in c["notes"]:
        out(f"note: {n}")
    for w in c["warnings"]:
        out(f"warning: {w}")


def update_apply(folder, fd, c, now, rec, man_text) -> None:
    old_ver, new_ver = c["old_ver"], c["new_ver"]
    nw = c["new_plan"]["writes"]
    # 1. The new version beside the old one.
    tdir = f".agent8/template/{new_ver}"
    if lstat_rel(fd, tdir) is not None:
        remove_tree(os.path.join(folder, tdir))
    for rel in sorted(r for r, e in nw.items() if e["layer"] == "template"):
        write_entry(fd, rel, nw[rel])
    for rel in sorted((r for r, e in nw.items() if e["layer"] == "template" and e["kind"] != "dir"),
                      key=lambda r: (-r.count("/"), r)):
        lock(fd, rel)
    lock(fd, tdir, mode_dir=0o555)
    # 2. Hand edits saved, then the old mirrored and host files taken away.
    stamp = re.sub(r"[^0-9A-Za-z]", "", now)
    backup = f".agent8/previous/{old_ver}-to-{new_ver}-{stamp}"
    for rel in c["hand"]:
        e = disk_entry(fd, rel)
        if e and e["kind"] in ("file", "link"):
            write_entry(fd, f"{backup}/{rel}", e)
    gone = [r for r, e in c["old_f"].items() if e["kind"] != "dir" and not any(
        r.startswith(d + "/") for d in c["sd_old"]) and r not in c["kept_as_data"]]
    for rel in sorted(gone):
        if lstat_rel(fd, rel) not in (None, "link-above"):
            pfd, leaf = _walk(fd, rel, make=False)
            try:
                os.unlink(leaf, dir_fd=pfd)
            finally:
                os.close(pfd)
    for d in c["sd_old"]:
        if lstat_rel(fd, d) not in (None, "link-above"):
            remove_tree(os.path.join(folder, d))
    for rel in c["kept_as_data"]:
        if lstat_rel(fd, rel) not in (None, "link-above"):
            pfd, leaf = _walk(fd, rel, make=False)
            try:
                st = os.stat(leaf, dir_fd=pfd, follow_symlinks=False)
                if not statmod.S_ISLNK(st.st_mode):
                    os.chmod(leaf, (st.st_mode & 0o777) | 0o200, dir_fd=pfd)
            finally:
                os.close(pfd)
    # Folders the old version made that are now empty.
    dirs = sorted({"/".join(r.split("/")[:i]) for r in gone for i in range(1, r.count("/") + 1)},
                  key=lambda r: -r.count("/"))
    for d in dirs:
        if d.split("/")[0] in (".agent8", "skills") or any(r.startswith(d + "/") for r in nw):
            continue
        try:
            os.rmdir(os.path.join(folder, d))
        except OSError:
            pass
    # 3. The new version's files, seeds where missing, repositories.
    for rel in sorted(c["new_f"]):
        write_entry(fd, rel, nw[rel])
    for rel in sorted((r for r, e in nw.items() if e["layer"] == "mirror" and e["kind"] != "dir"),
                      key=lambda r: (-r.count("/"), r)):
        lock(fd, rel)
    for rel in c["seeds"]:
        write_entry(fd, rel, nw[rel], only_if_missing=True)
    clone_repos(folder, c["repos"])
    # 4. extends and the instance record.
    src = rec["template"]["source"]
    new_line = "extends: " + json.dumps(f"{src}@{new_ver}", ensure_ascii=False)
    text = "\n".join(new_line if ln == c["extends_line"] else ln for ln in man_text.split("\n"))
    replace_file(fd, "agent.yaml", text.encode("utf-8"))
    record = dict(c["new_plan"]["record"])
    record["previous"] = {"version": old_ver, "digest": rec["template"].get("digest")}
    record["installed_at"] = rec.get("installed_at") or now
    record["updated_at"] = now
    record["answers"] = {k: val for k, val in c["answers"].items()
                         if isinstance(k, str) and re.fullmatch(r"[a-z][a-z0-9_]*", k)
                         and not v.looks_secret(json.dumps(val))}
    ordered = {k: record[k] for k in ("format", "template", "previous", "installed_at", "updated_at",
                                       "answers", "secrets") if k in record}
    replace_file(fd, ".agent8/instance.yaml", ("# .agent8/instance.yaml — written by the installer. Never "
                                               "holds a secret value.\n" + "\n".join(to_yaml(ordered)) + "\n")
                 .encode("utf-8"))
    # 5. Only the new version and the one before it are kept.
    tfd = os.open(".agent8/template", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        names = os.listdir(tfd)
    finally:
        os.close(tfd)
    for name in names:
        if name not in (new_ver, old_ver):
            remove_tree(os.path.join(folder, ".agent8/template", name))


def replace_file(fd: int, rel: str, data: bytes) -> None:
    pfd, leaf = _walk(fd, rel, make=False)
    try:
        tmp = f".{leaf}.{os.getpid()}.tmp"
        nfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=pfd)
        try:
            os.write(nfd, data)
        finally:
            os.close(nfd)
        os.replace(tmp, leaf, src_dir_fd=pfd, dst_dir_fd=pfd)
    finally:
        os.close(pfd)


def cmd_update(args) -> int:
    folder = os.path.abspath(args.dir)
    now = args.now or now_utc()
    fd, rec, man, man_text = read_copy(folder)
    try:
        source = rec["template"].get("source")
        if not isinstance(source, str) or not source:
            raise Refused("This copy's instance record doesn't say where its template comes from.")
        with Source(source) as src:
            c = update_compute(folder, fd, rec, man, man_text, src, args.to,
                               lambda setup: collect_answers(setup, args), now)
            describe_switch(c)
            if c["collisions"]:
                plain_list("These paths are the agent's own and the new version would write there; "
                           "nothing was changed", c["collisions"])
                return 1
            if args.dry_run:
                out("Dry run: nothing was changed.")
                return 0
            if not confirm(f"Switch to {c['new_ver']}?", args.yes):
                out("Nothing was changed.")
                return 1
            update_apply(folder, fd, c, now, rec, man_text)
    finally:
        os.close(fd)
    out(f"Now on {c['new_ver']} (was {c['old_ver']}). The own layer and the data were not touched; "
        f"`{TOOL} update --to {c['old_ver']}` goes back.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog=TOOL, description="Reference tool for the open agent template "
                                f"format (reads format {', '.join(f'{k}.x' for k in READS)}).")
    p.add_argument("--version", action="version", version=f"{TOOL} {TOOL_VERSION} (format {FORMAT})")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check a template, or an installed copy")
    c.add_argument("dir", nargs="?", default=".")
    c.add_argument("--all-files", action="store_true",
                   help="check every file in the folder, not only what git would commit")
    n = sub.add_parser("new", help="start a new template")
    n.add_argument("dir")
    n.add_argument("--name")
    n.add_argument("--description")
    n.add_argument("--author")
    i = sub.add_parser("install", help="install a template as a new agent")
    i.add_argument("source")
    i.add_argument("dest", nargs="?")
    i.add_argument("--version", dest="version", help="exact version (default: the latest release tag)")
    i.add_argument("--name", help="the agent's name (default: the folder's)")
    i.add_argument("--answer", action="append", metavar="ID=VALUE")
    i.add_argument("--answers", metavar="FILE", help="YAML file of answers")
    i.add_argument("--yes", action="store_true", help="don't ask before writing")
    i.add_argument("--now", help=argparse.SUPPRESS)
    u = sub.add_parser("update", help="switch an installed copy to another version")
    u.add_argument("dir", nargs="?", default=".")
    u.add_argument("--to", help="exact version, higher or lower (default: the latest release tag)")
    u.add_argument("--answer", action="append", metavar="ID=VALUE")
    u.add_argument("--answers", metavar="FILE")
    u.add_argument("--dry-run", action="store_true", help="say what would change, change nothing")
    u.add_argument("--yes", action="store_true")
    u.add_argument("--now", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    try:
        if args.cmd == "check":
            return cmd_check(args)
        if args.cmd == "new":
            return cmd_new(args)
        if args.cmd == "install":
            if args.version and not SEMVER_RE.match(args.version):
                raise Refused("--version must be an exact version, like 1.2.0.")
            return cmd_install(args)
        if args.to and not SEMVER_RE.match(args.to):
            raise Refused("--to must be an exact version, like 1.2.0.")
        return cmd_update(args)
    except TooNew as exc:
        out(f"error: {exc}")
        return 3
    except Refused as exc:
        out(f"error: {exc}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
