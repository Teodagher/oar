"""Reading a repository that isn't a template yet: an OpenGAP repo without the block, or a
plain AGENTS.md / CLAUDE.md repo (SPEC §12).

This is the reference reading. agent8 does the same in its `templates` function
(`backend/templates/gitimport.ts`, `convert`), and `test_importer.py` runs both on the same
repositories and wants the same result: change one, change the other.

Pure: no network, no disk. `files` is {path: {"kind": "file", "data": bytes, "mode": int} |
{"kind": "link", "target": str} | {"kind": "dir"}}, already checked for unsafe paths (oar's
check_entries). `parse_yaml` reads YAML text (it may raise). An OpenGAP `extends` is followed by
the caller, which passes the parents it fetched (direct parent first).
"""
from __future__ import annotations

import datetime as _dt
import json
import re

import validate as v

FORMAT = "0.2"
EXTENDS_DEPTH = 3
NAME_RE = re.compile(r"^[a-z][a-z0-9-]*\Z")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?\Z")
TAG_RE = re.compile(r"^v?((0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?)\Z")
OWN_ROOT = ("identity.md", "LOCAL.md", "mcp.local.json")
SKILL_LAYOUTS = ("skills", ".agents/skills", ".claude/skills")

# Folders and files that hold the original agent's data, not the template: left out and
# written into the data list (knowledge/ is seeded instead, see convert).
GUESSED_DATA = [
    "/memory/", "/knowledge/", "/.gitagent/", "/logs/", "/log/", "/data/", "/output/", "/outputs/",
    "/exports/", "/inbox/", "/notes/", "/journal/", "/conversations/", "/transcripts/", "/sessions/",
    "/state/", "/tmp/", "/cache/", "/.cache/", "/clients/", "/uploads/", "/downloads/", "/raw/", "/wiki/",
    "/.env", "/.env.*", "**/*.log", "**/*.sqlite", "**/*.sqlite3", "**/*.db",
]
ENV_OK = re.compile(r"(^|/)\.env\.(example|sample|template)\Z")
SECRET_FILE_SRC = (
    "(^|/)(\\.env(\\.(?!example$|sample$|template$)[^/]+)?|id_rsa[^/]*|id_ed25519[^/]*|id_ecdsa[^/]*"
    "|[^/]+\\.pem|[^/]+\\.p12|[^/]+\\.pfx|[^/]+\\.key|\\.netrc|\\.npmrc|\\.pypirc|credentials(\\.json)?"
    "|\\.credentials\\.json|[^/]*token[^/]*\\.json|service[-_]account[^/]*\\.json|\\.git-credentials"
    "|client_secret[^/]*\\.json|\\.pgpass|\\.claude\\.json|[^/]+\\.jks|[^/]+\\.keystore|[^/]+\\.kdbx"
    "|\\.(bash|zsh|python|node_repl|psql|mysql)_history|auth\\.json|secrets?\\.(ya?ml|json|toml)"
    "|\\.kube/config|\\.docker/config\\.json)$"
)
# `$` in JavaScript (no m flag) is the very end; Python's also matches before a final newline.
SECRET_FILE_RE = re.compile(SECRET_FILE_SRC.replace("$", r"\Z"))
SECRET_DIRS = (".ssh", ".gnupg", ".aws", ".kube", ".docker", ".azure", ".config/gh", ".config/gcloud",
               ".password-store", ".secrets", "secrets")
SECRET_SRCS = [
    r"-----BEGIN (RSA |EC |OPENSSH |DSA |ENCRYPTED |)PRIVATE KEY-----",
    r"\bsk_live_[0-9A-Za-z]{16,}", r"\bsk-ant-[0-9A-Za-z_-]{20,}", r"\bsk-proj-[0-9A-Za-z_-]{20,}",
    r"\bghp_[0-9A-Za-z]{30,}", r"\bgithub_pat_[0-9A-Za-z_]{30,}", r"\bAKIA[0-9A-Z]{16}\b",
    r"\bxox[abprs]-[0-9A-Za-z-]{10,}", r"\bAIza[0-9A-Za-z_-]{35}\b", r"\bsk-[0-9A-Za-z]{32,}",
    r"\bgh[osu]_[0-9A-Za-z]{30,}", r"\brk_live_[0-9A-Za-z]{16,}",
    r"\beyJ[0-9A-Za-z_-]{10,}\.eyJ[0-9A-Za-z_-]{10,}\.[0-9A-Za-z_-]{10,}",
    r"-----BEGIN PGP PRIVATE KEY BLOCK-----", r"\bsk-(?:or-v1|svcacct|admin)-[0-9A-Za-z_-]{20,}",
    r"\b[sr]k_test_[0-9A-Za-z]{16,}", r"\bglpat-[0-9A-Za-z_-]{20,}", r"\bnpm_[0-9A-Za-z]{36}\b",
    r"\bhf_[0-9A-Za-z]{30,}", r"\bGOCSPX-[0-9A-Za-z_-]{20,}", r"\bya29\.[0-9A-Za-z_-]{20,}",
    r"\bxapp-[0-9A-Za-z-]{20,}", r"\bSG\.[0-9A-Za-z_-]{16,}\.[0-9A-Za-z_-]{16,}", r"\bASIA[0-9A-Z]{16}\b",
]
SECRET_RES = [re.compile(s, re.ASCII) for s in SECRET_SRCS]   # \b as JavaScript reads it

ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}")
MCP_BUILTIN = frozenset(("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT", "HOME"))
SECRETISH_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|^PAT_|_PAT$)")
ENV_LINE_RE = re.compile(r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=")
ENV_EXAMPLES = (".env.example", ".env.sample", ".env.template")
MCP_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}\Z")
RUNTIME_RE = re.compile(r"^[A-Za-z0-9._+-]{1,30}\Z")
SECRETS_MAX = 30
FILE_LIMIT = 20 * 1024 * 1024
LINKS_MAX = 500
LINK_STEPS = 20000

# JavaScript's whitespace (String.prototype.trim, \s).
_WS = "\t\n\x0b\x0c\r              " \
      "    　﻿"
_S = "[" + _WS + "]"


class Refused(Exception):
    """The repository can't be imported; the message says why in plain words."""


# ------------------------------------------------------------ JavaScript's string rules

def _u16(s: str) -> int:
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def _slice(s: str, n: int) -> str:
    """s.slice(0, n), counted in UTF-16 units like JavaScript."""
    if len(s) <= n // 2:
        return s
    return s.encode("utf-16-le", "surrogatepass")[:2 * n].decode("utf-16-le", "surrogatepass")


def _trim(s: str) -> str:
    return s.strip(_WS)


def _enc(s: str) -> bytes:
    """TextEncoder: a lone surrogate becomes U+FFFD."""
    return s.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace").encode("utf-8")


def _dec(b: bytes) -> str:
    """TextDecoder: invalid bytes become U+FFFD, a leading byte-order mark goes."""
    return b.decode("utf-8-sig", "replace")


def _key(s: str):
    """JavaScript's default sort order (UTF-16 code units)."""
    return s.encode("utf-16-be", "surrogatepass")


def _sorted(xs):
    return sorted(xs, key=_key)


def clip(s: str, n: int = 120) -> str:
    t = re.sub(r"[\x00-\x1f\x7f]", "?", s)
    return _slice(t, n) + "…" if _u16(t) > n else t


def _json(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _plain(v):
    """JSON.parse(JSON.stringify(v)): dates become text, as JavaScript writes them."""
    def default(x):
        if isinstance(x, _dt.datetime):
            return x.isoformat()
        if isinstance(x, _dt.date):
            return x.isoformat() + "T00:00:00.000Z"
        return str(x)
    return json.loads(json.dumps(v, default=default, ensure_ascii=False))


def is_obj(v) -> bool:
    return isinstance(v, dict)


def one_line(v, n: int) -> str:
    if not isinstance(v, str):
        return ""
    return clip(re.sub(r"^[ \t\r\n]+|[ \t\r\n]+$", "", re.sub(r"[ \t\r\n]+", " ", v)), n)


def num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        if v.is_integer() and abs(v) < 1e21:
            return str(int(v))
        return repr(v)
    return str(v)


def scalar(v) -> str:
    if isinstance(v, str):
        return one_line(v, 100)
    if isinstance(v, bool):
        return "true" if v else "false"
    n = num(v)
    return n if n is not None else clip(_json(v), 100)


def strs(v, n: int) -> list:
    if not isinstance(v, list):
        return []
    return [x for x in (one_line(x, n) for x in v if isinstance(x, str)) if x]


def text(e):
    return _dec(e["data"]) if e and e.get("kind") == "file" else None


# ------------------------------------------------------------ paths, links, secrets

def rel_ok(p) -> bool:
    if not isinstance(p, str) or not p or _u16(p) > 1024 or p.startswith(("/", "~")):
        return False
    if "\\" in p or re.search(r"[\x00-\x1f\x7f]", p):
        return False
    return all(c not in ("", ".", "..") for c in p.split("/"))


def link_resolver(files: dict):
    memo, budget = {}, [LINK_STEPS]

    def resolve(name, depth):
        seen = memo.get(name)
        if seen is False:
            raise Refused(f"{clip(name)} is a link that goes round in circles.")
        if seen:
            return seen
        if depth > 20:
            raise Refused(f"{clip(name)} is a link agent8 won't follow.")
        memo[name] = False
        target = files[name]["target"]
        if not target or target.startswith("/") or "\\" in target or "\0" in target or len(_enc(target)) > 100:
            raise Refused(f"{clip(name)} is a link out of the repository.")
        parts = name.split("/")[:-1]
        for c in target.split("/"):
            budget[0] -= 1
            if budget[0] < 0:
                raise Refused("This repository's links are too tangled to check.")
            if c in ("", "."):
                continue
            if c == "..":
                if not parts:
                    raise Refused(f"{clip(name)} is a link out of the repository.")
                parts.pop()
                continue
            parts.append(c)
            here = "/".join(parts)
            if (files.get(here) or {}).get("kind") == "link":
                parts = resolve(here, depth + 1).split("/")
        dest = "/".join(parts)
        if not dest or (files.get(dest) or {}).get("kind") not in ("file", "dir"):
            raise Refused(f"{clip(name)} is a link to something that isn't in the repository.")
        memo[name] = dest
        return dest

    return lambda name: resolve(name, 0)


def check_links(files: dict) -> dict:
    links = [n for n, e in files.items() if e.get("kind") == "link"]
    if len(links) > LINKS_MAX:
        raise Refused("This repository has too many links.")
    res = link_resolver(files)
    return {n: res(n) for n in _sorted(links)}


def looks_secret(data: bytes) -> bool:
    if len(data) > 2 * 1024 * 1024:
        return False
    t = _dec(data)
    return any(rx.search(t) for rx in SECRET_RES)


def is_secret_file(rel: str) -> bool:
    if ENV_OK.search(rel):
        return False
    if SECRET_FILE_RE.search(rel):
        return True
    return any(rel == d or rel.startswith(d + "/") for d in SECRET_DIRS)


# ------------------------------------------------------------ what the preview says

def slug(s: str) -> str:
    out = re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", re.sub(r"\.git\Z", "", s.lower())))
    if not re.match(r"^[a-z]", out):
        out = "agent-" + out
    return re.sub(r"-+\Z", "", _slice(re.sub(r"-+\Z", "", out), 56)) or "imported-agent"


def licence_of(files: dict):
    name = next((k for k in _sorted(files) if re.match(r"^(LICENSE|LICENCE|COPYING)(\.(md|txt))?\Z", k, re.I)), None)
    t = _slice(text(files.get(name)) or "", 4000) if name else ""
    if not t:
        return None
    rules = [
        (r"MIT License|Permission is hereby granted, free of charge", re.I, "MIT"),
        (r"Apache License,?\s+Version 2\.0", re.I, "Apache-2.0"),
        (r"GNU AFFERO GENERAL PUBLIC LICENSE", re.I, "AGPL-3.0"),
        (r"GNU LESSER GENERAL PUBLIC LICENSE", re.I, "LGPL-3.0"),
        (r"GNU GENERAL PUBLIC LICENSE\s+Version 3", re.I, "GPL-3.0"),
        (r"GNU GENERAL PUBLIC LICENSE\s+Version 2", re.I, "GPL-2.0"),
        (r"Mozilla Public License,?\s+(v\.|version)\s*2\.0", re.I, "MPL-2.0"),
        (r"BSD 3-Clause|Redistribution and use in source and binary forms.*Neither the name", re.I | re.S, "BSD-3-Clause"),
        (r"BSD 2-Clause|Redistribution and use in source and binary forms", re.I, "BSD-2-Clause"),
        (r"This is free and unencumbered software released into the public domain", re.I, "Unlicense"),
        (r"ISC License|Permission to use, copy, modify, and/or distribute", re.I, "ISC"),
    ]
    for rx, flags, spdx in rules:
        if re.search(rx.replace(r"\s", _S), t, flags):
            return spdx
    return "see LICENSE"


def readme_line(files: dict):
    name = next((k for k in _sorted(files) if re.match(r"^README(\.(md|markdown|txt|rst))?\Z", k, re.I)), None)
    t = text(files.get(name)) if name else None
    if not t:
        return None
    for p in re.split(r"\n" + _S + r"*\n", t.replace("\r", "")):
        s = _trim(p)
        if not s or s.startswith("#") or re.match(r"^(\[!\[|!\[|<)", s) or re.match(r"^[-=]{3,}\Z", s):
            continue
        plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
        plain = _trim(re.sub(_S + "+", " ", re.sub(r"[`*_>#]", "", plain)))
        if _u16(plain) >= 8:
            return _slice(plain, 297) + "…" if _u16(plain) > 300 else plain
    return None


def skill_layout(files: dict, wanted=None):
    if isinstance(wanted, str) and wanted in SKILL_LAYOUTS:
        return wanted
    return next((c for c in SKILL_LAYOUTS if (files.get(c) or {}).get("kind") == "dir"), None)


def skill_names(files: dict, layout) -> list:
    if not layout:
        return []
    out = set()
    for p in files:
        if p.startswith(layout + "/") and p.endswith("/SKILL.md"):
            rest = p[len(layout) + 1:].split("/")
            if len(rest) == 2:
                out.add(_slice(rest[0], 64))
    return _sorted(out)[:100]


# ------------------------------------------------------------ OpenGAP: extends

def deep_merge(parent, child):
    """Child fields override the parent's; objects are merged key by key (OpenGAP §15)."""
    if not is_obj(parent) or not is_obj(child):
        return child
    out = dict(parent)
    for k, x in child.items():
        out[k] = deep_merge(parent[k], x) if k in parent else x
    return out


def manifest_of(files: dict, parse_yaml):
    e = files.get("agent.yaml") or files.get("agent.yml")
    if not e or e.get("kind") != "file":
        return None
    try:
        val = parse_yaml(_dec(e["data"]))
    except Exception:  # noqa: BLE001 - any reader's error means "not readable"
        return None
    return _plain(val) if is_obj(val) else None


def extends_of(files: dict, parse_yaml):
    man = manifest_of(files, parse_yaml)
    if not man or "x-agent8" in man or man.get("extends") is None:
        return None
    return man["extends"] if isinstance(man["extends"], str) else _json(man["extends"])


GITHUB_RE = re.compile(r"^https://github\.com/([A-Za-z0-9](?:-?[A-Za-z0-9]){0,38})/([A-Za-z0-9._-]{1,100})\Z")


def extends_github(url: str):
    u = re.sub(r"\.git\Z", "", re.sub(r"/+\Z", "", _trim(url)))
    m = GITHUB_RE.match(u)
    if not m or m.group(2).endswith(".git") or m.group(2) in (".", ".."):
        return None
    return {"owner": m.group(1), "repo": m.group(2), "url": f"https://github.com/{m.group(1)}/{m.group(2)}"}


def _merge_one(child: dict, child_man: dict, parent: dict, parent_man: dict):
    files = dict(child)
    base = {k: x for k, x in parent_man.items() if k not in ("extends", "x-agent8")}
    man = deep_merge(base, child_man)
    man.pop("extends", None)
    ps = parent.get("SOUL.md")
    if ps and ps["kind"] == "file" and "SOUL.md" not in child:
        files["SOUL.md"] = ps
    pr, cr = parent.get("RULES.md"), child.get("RULES.md")
    if pr and pr["kind"] == "file":
        if cr and cr["kind"] == "file":
            files["RULES.md"] = {"kind": "file", "data": _enc(_dec(pr["data"]) + "\n\n" + _dec(cr["data"])), "mode": 0o644}
        elif not cr:
            files["RULES.md"] = pr
    for d in ("skills", "tools"):
        k = (files.get(d) or {}).get("kind")
        if k and k != "dir":
            continue
        for p in _sorted(parent):
            if not p.startswith(d + "/"):
                continue
            top = "/".join(p.split("/")[:2])
            if top in child:
                continue
            if d not in files:
                files[d] = {"kind": "dir"}
            files[p] = parent[p]
    return files, man


def flatten_extends(child: dict, child_man: dict, parents: list, parse_yaml):
    """The child flattened onto its chain of parents ({url, commit, files}, direct parent first)."""
    acc = None
    for par in reversed(parents):
        pm = manifest_of(par["files"], parse_yaml) or {}
        acc = _merge_one(par["files"], pm, acc[0], acc[1]) if acc else (dict(par["files"]), pm)
    return _merge_one(child, child_man, acc[0], acc[1]) if acc else (child, child_man)


# ------------------------------------------------------------ OpenGAP: the other fields, in words

def compliance_section(c):
    if not is_obj(c):
        return None
    lines = []
    if isinstance(c.get("risk_tier"), str):
        lines.append(f"Risk tier: {one_line(c['risk_tier'], 30).upper()}")
    fw = strs(c.get("frameworks"), 40)
    if fw:
        lines.append(f"Frameworks: {', '.join(fw)}")
    sup = c["supervision"] if is_obj(c.get("supervision")) else {}
    if sup.get("human_in_the_loop") == "always":
        lines.append("- Every decision needs a person's approval before it is carried out.")
    if sup.get("human_in_the_loop") == "conditional":
        lines.append("- Some decisions need a person's approval: ask before anything risky.")
    trig = sup.get("escalation_triggers")
    if isinstance(trig, list) and trig:
        lines.append("- Hand over to a person when:")
        for t in trig[:20]:
            if is_obj(t):
                for k, x in t.items():
                    lines.append(f"  - {one_line(k, 60)}: {scalar(x)}")
            else:
                lines.append(f"  - {scalar(t)}")
    comm = c["communications"] if is_obj(c.get("communications")) else {}
    if comm.get("fair_balanced") is True:
        lines.append("- Everything you write must be fair and balanced (FINRA 2210).")
    if comm.get("no_misleading") is True:
        lines.append("- Never make misleading, exaggerated or promissory statements.")
    dg = c["data_governance"] if is_obj(c.get("data_governance")) else {}
    if dg.get("pii_handling") == "redact":
        lines.append("- Redact all personal information from what you write.")
    if dg.get("pii_handling") == "prohibit":
        lines.append("- Don't process any personal information.")
    rk = c["recordkeeping"] if is_obj(c.get("recordkeeping")) else {}
    if rk.get("audit_logging") is True:
        lines.append("- Everything you do is logged for audit.")
    sod = c["segregation_of_duties"] if is_obj(c.get("segregation_of_duties")) else None
    if sod is not None:
        lines.append("- Segregation of duties applies:")
        if is_obj(sod.get("assignments")):
            for a, r in list(sod["assignments"].items())[:30]:
                lines.append(f"  - {one_line(a, 60)} holds {', '.join(strs(r, 40))}")
        for pair in (sod["conflicts"][:30] if isinstance(sod.get("conflicts"), list) else []):
            ab = strs(pair, 40)
            if len(ab) >= 2 and ab[0] and ab[1]:
                lines.append(f"  - no single agent may hold both {ab[0]} and {ab[1]}")
        for h in (sod["handoffs"][:30] if isinstance(sod.get("handoffs"), list) else []):
            if is_obj(h) and isinstance(h.get("action"), str):
                lines.append(f"  - {one_line(h['action'], 80)} must pass through {' → '.join(strs(h.get('required_roles'), 40))}")
    fg = c["financial_governance"] if is_obj(c.get("financial_governance")) else None
    if fg is not None and fg.get("enabled") is True:
        lines.append("- Spending limits apply:")
        sp = fg["spending"] if is_obj(fg.get("spending")) else {}
        ap = fg["approval"] if is_obj(fg.get("approval")) else {}
        if num(sp.get("max_per_transaction_cents")):
            lines.append(f"  - at most {num(sp['max_per_transaction_cents'])} cents per transaction")
        if num(sp.get("max_monthly_cents")):
            lines.append(f"  - at most {num(sp['max_monthly_cents'])} cents a month")
        if num(ap.get("require_above_cents")):
            lines.append(f"  - a person approves anything above {num(ap['require_above_cents'])} cents")
    return "## Compliance\n\n" + "\n".join(lines) if lines else None


def _yaml_or_none(parse_yaml, data: bytes):
    try:
        return parse_yaml(_dec(data))
    except Exception:  # noqa: BLE001
        return None


def knowledge_section(knowledge: dict, parse_yaml):
    docs = []
    idx = knowledge.get("knowledge/index.yaml") or knowledge.get("knowledge/index.yml")
    if idx and idx["kind"] == "file":
        y = _yaml_or_none(parse_yaml, idx["data"])
        lst = []
        if is_obj(y):
            lst = y["documents"] if isinstance(y.get("documents"), list) else \
                y["entries"] if isinstance(y.get("entries"), list) else []
        for d in lst:
            if not is_obj(d) or not isinstance(d.get("path"), str):
                continue
            p = re.sub(r"^\./", "", d["path"])
            if not rel_ok(p) or (knowledge.get("knowledge/" + p) or {}).get("kind") != "file":
                continue
            docs.append({"p": p, "desc": one_line(d.get("description"), 150), "always": d.get("always_load") is True})
    if not docs:
        docs = [{"p": p, "desc": "", "always": False} for p in _sorted(
            p[len("knowledge/"):] for p, e in knowledge.items()
            if e["kind"] == "file" and not re.match(r"^knowledge/index\.ya?ml\Z", p))]
    docs = docs[:50]
    if not docs:
        return None
    lines = ["## Knowledge", "", "Your reference documents are in knowledge/. They are yours: keep them up to date and add to them."]
    first = [d for d in docs if d["always"]]
    rest = [d for d in docs if not d["always"]]
    if first:
        lines += ["", "Read these at the start of every session:"] + [f"- knowledge/{d['p']}" for d in first]
    if rest:
        lines += ["", "The others, when they help:" if first else "Read them when they help:"]
        lines += [f"- knowledge/{d['p']}" + (": " + d["desc"] if d["desc"] else "") for d in rest]
    return "\n".join(lines)


def tools_section(files: dict, parse_yaml):
    defs = _sorted(p for p in files if re.match(r"^tools/[^/]+\.ya?ml\Z", p) and files[p]["kind"] == "file")[:50]
    if not defs:
        return None
    lines = ["## Tools", "", "Your tools are scripts in tools/ (each one's inputs are described in its .yaml file); run them yourself:"]
    for p in defs:
        y = _yaml_or_none(parse_yaml, files[p]["data"])
        t = y if is_obj(y) else {}
        name = one_line(t.get("name"), 64) or re.sub(r"\.ya?ml\Z", "", p[6:])
        desc = one_line(t.get("description"), 200)
        impl = t["implementation"] if is_obj(t.get("implementation")) else {}
        run = ""
        if isinstance(impl.get("path"), str):
            ip = re.sub(r"^\./", "", impl["path"])
            if rel_ok(ip) and (files.get("tools/" + ip) or {}).get("kind") == "file":
                rt = impl["runtime"] + " " if isinstance(impl.get("runtime"), str) and RUNTIME_RE.match(impl["runtime"]) else ""
                run = f" Run: `{rt}tools/{ip}`"
        lines.append(f"- {name}" + (": " + desc if desc else "") + run)
    return "\n".join(lines)


def sub_agents_section(files: dict, man: dict, parse_yaml):
    items, seen = [], set()
    if is_obj(man.get("agents")):
        for n, cfg in list(man["agents"].items())[:30]:
            c = cfg if is_obj(cfg) else {}
            desc = one_line(c.get("description"), 150)
            where = re.sub(r"^\./", "", c["path"]) if isinstance(c.get("path"), str) and rel_ok(re.sub(r"^\./", "", c["path"])) else ""
            items.append(f"- {one_line(n, 64)}" + (": " + desc if desc else "") + (f" ({where})" if where else ""))
            seen.add(n)
    for p in _sorted(p for p in files if re.match(r"^agents/[^/]+\Z", p)):
        if len(items) >= 30:
            break
        e = files[p]
        base = re.sub(r"\.md\Z", "", p[7:])
        if base in seen:
            continue
        if e["kind"] == "dir":
            ay = files.get(p + "/agent.yaml")
            if not ay or ay["kind"] != "file":
                continue
            y = _yaml_or_none(parse_yaml, ay["data"])
            desc = one_line(y.get("description"), 150) if is_obj(y) else ""
        elif e["kind"] == "file" and p.endswith(".md"):
            fm = re.match(r"^---\r?\n([\s\S]*?)\r?\n---", _dec(e["data"]))
            # JavaScript's /^description:[ \t]*(.+)$/m: lines end at \n, \r, U+2028 and U+2029.
            d = re.search(r"(?:^|(?<=[\n\r  ]))description:[ \t]*([^\n\r  ]+)(?=[\n\r  ]|\Z)",
                          fm.group(1)) if fm else None
            desc = one_line(re.sub(r"^[\"']|[\"'][ \t\r]*\Z", "", d.group(1)), 150) if d else ""
        else:
            continue
        items.append(f"- {one_line(base, 64)}" + (": " + desc if desc else "") + f" ({p})")
        seen.add(base)
    if not items:
        return None
    return "\n".join(["## Sub-agents", "", "Helpers are defined in agents/: take on their role, or hand them work when "
                      "your agent program can run sub-agents:"] + items)


def workflows_section(files: dict):
    w = [p[10:] for p in _sorted(p for p in files if re.match(r"^workflows/[^/]+\.(ya?ml|md)\Z", p)
                                 and files[p]["kind"] == "file")[:30]]
    return f"## Workflows\n\nStep-by-step procedures are in workflows/: {', '.join(w)}." if w else None


def mcp_from_manifest(ms, unmapped: list):
    if not is_obj(ms):
        return None
    out = {}

    def str_map(x):
        return x if is_obj(x) and all(isinstance(y, str) for y in x.values()) else None

    for n, cfg in list(ms.items())[:50]:
        name = one_line(n, 64)
        if not MCP_NAME_RE.match(n) or not is_obj(cfg):
            unmapped.append(f"MCP server {name}: not readable, not carried over")
            continue
        e = {}
        if isinstance(cfg.get("command"), str):
            e["command"] = cfg["command"]
            if isinstance(cfg.get("args"), list) and all(isinstance(x, str) for x in cfg["args"]):
                e["args"] = cfg["args"]
        elif isinstance(cfg.get("url"), str):
            e["url"] = cfg["url"]
            if str_map(cfg.get("headers")) is not None:
                e["headers"] = cfg["headers"]
        else:
            unmapped.append(f"MCP server {name}: no command or url, not carried over")
            continue
        if str_map(cfg.get("env")) is not None:
            e["env"] = cfg["env"]
        argv = [x for x in [e.get("command")] + list(e.get("args") or []) if isinstance(x, str)]
        if any("${" in x for x in argv):
            unmapped.append(f"MCP server {name}: a variable on its command line would show in the server's process "
                            "list, not carried over")
            continue
        if any(x.startswith(("/", "~")) for x in argv):
            unmapped.append(f"MCP server {name}: an absolute path on its command line, not carried over")
            continue
        out[n] = e
    return out or None


def guessed_secrets(files: dict, repo: dict) -> list:
    found, on_cmd = {}, set()
    servers = {}
    try:
        doc = json.loads(text(files.get(".mcp.json")) or "null")
        if is_obj(doc) and is_obj(doc.get("mcpServers")):
            servers = doc["mcpServers"]
    except ValueError:
        servers = {}
    for cfg in servers.values():
        if is_obj(cfg):
            on_cmd.update(ENV_REF_RE.findall(_json([cfg.get("command", ""), cfg.get("args", "")])))

    def add(n, why):
        if len(n) <= 64 and n not in MCP_BUILTIN and n not in on_cmd and n not in found and len(found) < SECRETS_MAX:
            found[n] = why

    for n, cfg in servers.items():
        if is_obj(cfg):
            for m in ENV_REF_RE.findall(_json(cfg)):
                add(m, f"Used by the MCP server {one_line(n, 64)}.")
    for f in ENV_EXAMPLES:
        t = text(repo.get(f))
        if t is None:
            continue
        for line in t.split("\n"):
            m = ENV_LINE_RE.match(line)
            if m and SECRETISH_RE.search(m.group(1).upper()):
                add(m.group(1), f"Listed in {f}.")
        break
    return [{"item": n, "description": why, "required": False, "env": {n: "{{vault:%s}}" % n}} for n, why in found.items()]


def unmapped_of(man: dict, files: dict) -> list:
    out = []
    if "model" in man:
        m = man["model"]
        pref = m if isinstance(m, str) else m.get("preferred") if is_obj(m) else None
        out.append("model" + (f" (prefers {one_line(pref, 60)})" if isinstance(pref, str) else "")
                   + ": agent8 starts it with the agent program's own model")
    if "runtime" in man:
        out.append("runtime (turns, timeout, temperature): not applied")
    if any((files.get(p) or {}).get("kind") == "file" for p in ("hooks/hooks.yaml", "hooks/hooks.yml")):
        out.append("hooks/hooks.yaml: OpenGAP's lifecycle hooks aren't wired in; their scripts are kept in hooks/")
    deps = man.get("dependencies")
    if isinstance(deps, list) and deps:
        names = [x for x in (one_line(d.get("name"), 40) if is_obj(d) else "" for d in deps) if x][:10]
        out.append("dependencies" + (f" ({', '.join(names)})" if names else "") + ": the agents it mounts aren't imported")
    if "delegation" in man:
        out.append("delegation: not applied; the sub-agents are described in the instructions")
    if "a2a" in man:
        out.append("a2a: not used")
    if "registries" in man:
        out.append("registries: skills aren't installed from registries")
    if (files.get("config") or {}).get("kind") == "dir":
        out.append("config/: environment overrides aren't applied")
    if "compliance" in man:
        out.append("compliance: written into the instructions as rules; agent8 doesn't enforce them")
    if any(re.match(r"^tools/[^/]+\.ya?ml\Z", p) for p in files):
        out.append("tools/: not registered as tools; the instructions say how to run their scripts")
    return out


# ------------------------------------------------------------ the conversion

def convert(input_files: dict, src: dict, parse_yaml, parents=None, extends_stop=None) -> dict:
    """An OpenGAP repo without the block, or a plain repo, as a template (SPEC §12).

    src: {url, repo, owner, commit, ref}. Returns {kind, manifest, files, version, info}.
    Raises Refused in words. A repo with an x-agent8 block is a template already."""
    files = dict(input_files)
    left_out, notes = [], []

    def drop(p, why):
        for k in list(files):
            if k == p or k.startswith(p + "/"):
                del files[k]
        if len(left_out) < 200:
            left_out.append({"path": p, "why": why})

    ref = src.get("ref")
    tm = TAG_RE.match(ref) if isinstance(ref, str) else None
    tag_version = tm.group(1) if tm else None

    man = None
    yml = files.get("agent.yaml") or files.get("agent.yml")
    if "agent.yml" in files and "agent.yaml" not in files:
        files["agent.yaml"] = files.pop("agent.yml")
    if yml:
        if yml["kind"] != "file":
            raise Refused("agent.yaml isn't a plain file.")
        try:
            parsed = parse_yaml(_dec(yml["data"]))
        except Exception:  # noqa: BLE001
            raise Refused("agent.yaml can't be read as YAML.")
        if not is_obj(parsed):
            raise Refused("agent.yaml must be a mapping.")
        man = _plain(parsed)
    if man is not None and "x-agent8" in man:
        raise Refused("This repository is a template already (agent.yaml has an x-agent8 block).")
    kind = "opengap" if man is not None else "plain"

    unmapped, extends_info = [], []
    if kind == "opengap" and man.get("extends") is not None:
        parents = parents or []
        if parents:
            files, man = flatten_extends(files, man, parents, parse_yaml)
            files = dict(files)
            extends_info = [{"url": p["url"], "commit": p["commit"]} for p in parents]
            notes.append("It extends " + ", which extends ".join(f"{clip(p['url'], 100)} ({p['commit'][:7]})" for p in parents)
                         + ": agent8 merged in their soul, rules, skills and tools the way OpenGAP does.")
        stop = extends_stop if extends_stop else (None if parents else {
            "url": man["extends"] if isinstance(man["extends"], str) else _json(man["extends"]), "why": "not fetched"})
        if stop:
            unmapped.append(f"extends {clip(stop['url'], 100)}: not followed ({stop['why']})")
        man.pop("extends", None)
    name = man["name"] if kind == "opengap" and isinstance(man.get("name"), str) and NAME_RE.match(man["name"]) \
        and _u16(man["name"]) <= 56 else slug(src["repo"])
    own_version = man["version"] if kind == "opengap" and isinstance(man.get("version"), str) \
        and SEMVER_RE.match(man["version"]) else None
    version = tag_version or own_version
    ay = files.get("agent.yaml")
    if ay and ay["kind"] == "file" and looks_secret(ay["data"]):
        raise Refused("agent.yaml holds what looks like a key: agent8 won't import it.")

    for p in (".agent8", ".claude/settings.local.json", ".gitmodules"):
        if p in files:
            drop(p, "git submodules aren't imported" if p == ".gitmodules" else "belongs to a running agent")
    for p in OWN_ROOT:
        if p in files:
            drop(p, "the original agent's own layer")
    had_memory = (files.get("memory") or {}).get("kind") == "dir"
    knowledge = {}
    if (files.get("knowledge") or {}).get("kind") == "dir":
        for p in list(files):
            if p.startswith("knowledge/"):
                knowledge[p] = files.pop(p)
        files.pop("knowledge", None)
    dl = v.DataList(GUESSED_DATA)
    for p in _sorted(files):
        if p not in files:
            continue
        if dl.matches(p, files[p]["kind"] == "dir"):
            drop(p, "data of the original agent")
    for p in _sorted(files):
        e = files.get(p)
        if not e:
            continue
        if (e["kind"] != "dir" and is_secret_file(p)) or p in SECRET_DIRS:
            drop(p, "looks like it holds keys")
        elif e["kind"] == "file" and looks_secret(e["data"]):
            drop(p, "holds what looks like a key")
    for p in _sorted(knowledge):
        e = knowledge.get(p)
        if not e:
            continue
        bad = "looks like it holds keys" if e["kind"] != "dir" and is_secret_file(p) else \
            "holds what looks like a key" if e["kind"] == "file" and looks_secret(e["data"]) else None
        if bad:
            for k in list(knowledge):
                if k == p or k.startswith(p + "/"):
                    del knowledge[k]
            if len(left_out) < 200:
                left_out.append({"path": p, "why": bad})
    if "seed" in files:
        drop("seed", "a seed folder only counts in an agent8 template")
    kept = sum(1 for e in knowledge.values() if e["kind"] == "file")
    if kept:
        files["seed"] = {"kind": "dir"}
        files["seed/knowledge"] = {"kind": "dir"}
        for p, e in knowledge.items():
            files["seed/" + p] = e
        notes.append(f"knowledge/ ({kept} file{'' if kept == 1 else 's'}) is the agent's reference documents: "
                     "every new agent starts with its own copy and can add to it.")

    parts = []

    def add(p, title):
        t = text(files.get(p))
        if t and _trim(t):
            parts.append((f"## {title}\n\n" if title else "") + _trim(t))

    if kind == "opengap":
        add("SOUL.md", "Soul")
        add("RULES.md", "Rules")
        add("DUTIES.md", "Duties")
    add("AGENTS.md", "Agent" if parts else None)
    claude = text(files.get("CLAUDE.md"))
    if claude:
        rx = re.compile(r"^" + _S + r"*@(\./)?(AGENTS|identity|LOCAL)\.md" + _S + r"*\Z", re.I)
        kept_text = _trim("\n".join(line for line in claude.split("\n") if not rx.match(line)))
        if kept_text:
            parts.append(f"## From CLAUDE.md\n\n{kept_text}" if parts else kept_text)
    if not parts:
        raise Refused("This OpenGAP agent has no SOUL.md, RULES.md, AGENTS.md or CLAUDE.md to import."
                      if kind == "opengap" else
                      "This repository has no agent.yaml, AGENTS.md or CLAUDE.md, so it isn't an agent agent8 can import.")
    if kind == "opengap":
        sections = [compliance_section(man.get("compliance")), knowledge_section(knowledge, parse_yaml),
                    tools_section(files, parse_yaml), sub_agents_section(files, man, parse_yaml), workflows_section(files),
                    "## Memory\n\nKeep what you learn across sessions in memory/MEMORY.md (short: about 200 lines). "
                    "memory/ is this agent's own: it isn't part of the template." if had_memory else None]
    else:
        sections = [knowledge_section(knowledge, parse_yaml)]
    parts += [s for s in sections if s]
    if "AGENTS.md" in files and files["AGENTS.md"]["kind"] != "file":
        drop("AGENTS.md", "not a plain file")
    files["AGENTS.md"] = {"kind": "file", "data": _enc("\n\n".join(parts) + "\n"), "mode": 0o644}
    files["CLAUDE.md"] = {"kind": "file", "data": b"@AGENTS.md\n@identity.md\n@LOCAL.md\n", "mode": 0o644}

    if kind == "opengap":
        unmapped += unmapped_of(man, files)
        ms = man.get("mcp_servers")
        if is_obj(ms) and ms:
            if ".mcp.json" in files:
                unmapped.append("mcp_servers: the repository's own .mcp.json was used instead")
            else:
                servers = mcp_from_manifest(ms, unmapped)
                if servers:
                    files[".mcp.json"] = {"kind": "file", "mode": 0o644, "data": _enc(
                        json.dumps({"mcpServers": servers}, indent=2, ensure_ascii=False) + "\n")}

    layout = skill_layout(files)
    if layout and layout != "skills" and "skills" in files:
        drop("skills", "collides with the copy's own skills")
    for _ in range(20):
        dropped = False
        for p in _sorted(files):
            e = files.get(p)
            if not e or e["kind"] != "link":
                continue
            try:
                link_resolver(files)(p)
                ok = True
            except Refused:
                ok = False
            if not ok:
                drop(p, "a link to something left out")
                dropped = True
        if not dropped:
            break
    check_links(files)

    m = man or {}
    description = _slice(_trim(m["description"]), 300) if isinstance(m.get("description"), str) and _trim(m["description"]) \
        else readme_line(files)
    licence = _slice(_trim(m["license"]), 64) if isinstance(m.get("license"), str) and _trim(m["license"]) \
        else licence_of(files)
    author = _slice(_trim(m["author"]), 100) if isinstance(m.get("author"), str) and _trim(m["author"]) \
        else src.get("owner")
    x = {"format": FORMAT, "data": list(GUESSED_DATA)}
    if layout:
        x["layout"] = {"skills": layout}
    secrets = guessed_secrets(files, input_files)
    if secrets:
        x["secrets"] = secrets
    x["requires"] = {"harnesses": [{"name": "claude-code"}]}
    out = {}
    if kind == "opengap":
        out = {k: val for k, val in man.items() if k not in ("extends", "x-agent8")}
    out["name"] = name
    if version:
        out["version"] = version
    if description:
        out["description"] = description
    if author:
        out["author"] = author
    if licence:
        out["license"] = licence
    out["x-agent8"] = x
    if kind == "plain":
        notes.append("No manifest: agent8 imported the instructions and skills and left out what looked like data.")
    info = info_of(kind, src, out, files, layout, left_out, notes)
    info["unmapped"] = unmapped[:50]
    info["extends"] = extends_info
    return {"kind": kind, "manifest": out, "files": files, "version": version, "info": info}


def info_of(kind, src, man, files, layout, left_out, notes) -> dict:
    b = man.get("x-agent8") or {}

    def s(val, n):
        return _slice(val, n) if isinstance(val, str) else None

    return {
        "kind": kind,
        "manifest": kind == "spec",
        "source": {"url": src.get("url"), "commit": src.get("commit"), "ref": src.get("ref")},
        "name": s(man.get("name"), 64),
        "description": s(man.get("description"), 300),
        "author": s(man.get("author"), 100),
        "license": s(man.get("license"), 64),
        "skills": skill_names(files, layout),
        "setup": len(b["setup"]) if isinstance(b.get("setup"), list) else 0,
        "secrets": [i for i in (s(x.get("item"), 64) if is_obj(x) else None for x in b["secrets"]) if i][:50]
        if isinstance(b.get("secrets"), list) else [],
        "files": sum(1 for e in files.values() if e["kind"] == "file"),
        "left_out": left_out,
        "notes": notes,
    }
