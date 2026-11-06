#!/usr/bin/env python3
"""Agent memory bookkeeping. Stdlib only; paths resolve from the repo root.

  memory.py new <person|org|topic|decision|lesson|procedure> "Title" [--slug s]
  memory.py file <path> | --text "<text>|-"  --date YYYY-MM-DD --kind <kind> --slug <slug>
  memory.py log <op> "title"
  memory.py index | lint [--hook] | status
  memory.py commit "message"   # commit only the own layer and memory, if git keeps them
  memory.py guard        # PreToolUse hook: memory/raw/ and the installed template are read-only

Every command except guard first copies missing starting files from seed/ (identity.md,
LOCAL.md, memory/...), so a fresh "Use this template" copy works with no setup step. In a copy
installed by a host (agent8), seed/ is read from the template under .agent8/template/<version>/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEM = ROOT / "memory"
WIKI, RAW = MEM / "wiki", MEM / "raw"
INDEX, LOG, NOW = MEM / "index.md", MEM / "log.md", MEM / "now.md"
IDENTITY, OWN_SKILLS, HOST = ROOT / "identity.md", ROOT / "skills", ROOT / ".agent8"
# The copy's own files and data that `commit` may save. Never the template's files.
OWN_PATHS = ("identity.md", "LOCAL.md", "skills", "mcp.local.json", "memory")
# type -> (folder, template, index heading). Order = index order.
TYPES = {
    "lesson": ("howto", "lesson", "Lessons (owner feedback: apply these)"),
    "procedure": ("howto", "procedure", "Procedures"),
    "person": ("entities", "entity", "People"),
    "org": ("entities", "entity", "Organizations"),
    "topic": ("entities", "entity", "Topics"),
    "decision": ("entities", "entity", "Decisions"),
}
KINDS = {"chat", "email", "notes", "transcript", "doc", "sheet", "export", "contract", "image", "audio", "other"}
LOG_OPS = {"setup", "remember", "recall", "tidy", "decision", "done", "lint"}
MARKER = "_TODO:"  # onboarding placeholders in identity.md
MAX_LINES, MAX_CHARS = 200, 10_000  # Claude Code caps SessionStart hook output

DATE = r"\d{4}-\d{2}-\d{2}"
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
CODE_RE = re.compile(r"```.*?```|`[^`\n]*`|<!--.*?-->", re.S)
EVIDENCE_RE = re.compile(rf"^- {DATE} · .+ — \[\[[^\]]+\]\]\s*$")
DUE_RE = re.compile(r"due:\s*(\S+)")


def today() -> str:
    return dt.date.today().isoformat()


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()[:60].rstrip("-") or "untitled"


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


class Page:
    def __init__(self, path: Path):
        self.path, self.stem = path, path.stem
        text = read(path)
        self.meta, self.body = {}, text
        if text.startswith("---\n") and (end := text.find("\n---", 4)) != -1:
            for line in text[4:end].splitlines():
                k, sep, v = line.partition(":")
                if sep:
                    self.meta[k.strip()] = v.strip()
            self.body = text[end + 4:]
        clean = CODE_RE.sub("", self.body)
        self.links = sorted({l.strip() for l in LINK_RE.findall(clean)})
        parts = re.split(r"^## Evidence log[ \t]*$", clean, maxsplit=1, flags=re.M)
        self.evidence = None if len(parts) < 2 else [l.rstrip() for l in parts[1].splitlines() if l.strip()]

    def get(self, k: str) -> str:
        return self.meta.get(k, "")


def pages() -> list[Page]:
    return [Page(p) for p in sorted(WIKI.rglob("*.md"))]


def onboarded() -> bool:
    return IDENTITY.is_file() and MARKER not in read(IDENTITY)


def identity() -> dict:
    """The `- **Key:** value` lines of identity.md, keys lowercased."""
    return {k.strip().lower(): v.strip() for k, v in re.findall(r"^- \*\*(.+?):\*\*[ \t]*(.*)$", read(IDENTITY), re.M)}


# ------------------------------------------------------------------ seeds and own skills

def _instance() -> str:
    return read(HOST / "instance.yaml")


def seed_dir() -> Path | None:
    if (ROOT / "seed").is_dir():  # the template itself, or a "Use this template" copy
        return ROOT / "seed"
    m = re.search(r"^template:[ \t]*\n(?:[ \t]+.*\n)*?[ \t]+version:[ \t]*[\"']?([^\"'\s]+)", _instance(), re.M)
    if m and (d := HOST / "template" / m.group(1) / "seed").is_dir():  # a copy installed by a host
        return d
    return None


def answers() -> dict:
    """Setup answers from .agent8/instance.yaml (simple `  id: value` lines under `answers:`)."""
    m = re.search(r"^answers:[ \t]*\n((?:[ \t]+.*\n?)*)", _instance(), re.M)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        k, sep, v = line.strip().partition(":")
        if sep and re.fullmatch(r"[a-z][a-z0-9_]*", k) and v.strip():
            out[k] = v.strip().strip("\"'")
    return out


def ensure_seeds() -> list[str]:
    """Copy every seed file whose target is missing; never overwrite. Returns what was created."""
    src = seed_dir()
    if src is None:
        return []
    ans, made = answers(), []
    for f in sorted(src.rglob("*")):
        rel = f.relative_to(src)
        dest = ROOT / rel
        if not f.is_file() or dest.exists() or dest.is_symlink():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copyfile(f, dest)
        else:
            text = re.sub(r"\{\{answer:([a-z][a-z0-9_]*)\}\}", lambda m: ans.get(m.group(1)) or f"{MARKER} {m.group(1)}", text)
            dest.write_text(text, encoding="utf-8")
        made.append(str(rel))
    for d in (RAW, WIKI):
        d.mkdir(parents=True, exist_ok=True)
    return made


def link_own_skills() -> list[str]:
    """Without a host, make the copy's own skills (skills/<name>/) visible to Claude Code by
    linking them into .claude/skills/ (.agents/skills links there too). A host such as agent8
    composes those folders itself, so this does nothing in an installed copy."""
    if HOST.exists():
        return []
    notes, live = [], ROOT / ".claude" / "skills"
    if live.is_dir():
        for link in live.iterdir():  # links to own skills that were removed
            if link.is_symlink() and not link.exists() and os.readlink(link).startswith("../../skills/"):
                link.unlink()
    if not OWN_SKILLS.is_dir():
        return notes
    live.mkdir(parents=True, exist_ok=True)
    for d in sorted(p for p in OWN_SKILLS.iterdir() if (p / "SKILL.md").is_file()):
        link = live / d.name
        if link.is_symlink() and os.readlink(link) == f"../../skills/{d.name}":
            continue
        if link.exists() or link.is_symlink():
            notes.append(f"skills/{d.name} has the name of a template skill; the template's is used here: rename yours")
            continue
        try:
            link.symlink_to(f"../../skills/{d.name}", target_is_directory=True)
        except OSError as e:
            notes.append(f"could not link skills/{d.name} into .claude/skills ({e})")
            continue
        exclude = ROOT / ".git" / "info" / "exclude"  # keep the link out of git, locally
        if exclude.parent.is_dir() and f"/.claude/skills/{d.name}" not in read(exclude).splitlines():
            with exclude.open("a", encoding="utf-8") as fh:
                fh.write(f"/.claude/skills/{d.name}\n")
        notes.append(f"skills/{d.name} is now available to Claude Code (from the next session)")
    return notes


# ------------------------------------------------------------------ commands

def cmd_new(a) -> None:
    if a.type not in TYPES:
        die(f"type must be one of: {', '.join(TYPES)}")
    folder, template, _ = TYPES[a.type]
    slug = slugify(a.slug or a.title)
    if any(p.stem == slug for p in pages()):
        die(f"a page named {slug} already exists: update it, or pass --slug")
    text = read(ROOT / "templates" / f"{template}.md")
    for k, v in {"title": a.title, "type": a.type, "today": today()}.items():
        text = text.replace("{{" + k + "}}", v)
    if a.type == "decision":
        text = text.replace("\nupdated:", "\nstatus: active\nupdated:", 1)
    path = WIKI / folder / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(path.relative_to(ROOT))


def cmd_file(a) -> None:
    if not re.fullmatch(DATE, a.date):
        die("--date must be YYYY-MM-DD (the event's date)")
    if a.kind not in KINDS:
        die(f"--kind must be one of: {', '.join(sorted(KINDS))}")
    if (a.path is None) == (a.text is None):
        die("give either a file path or --text")
    src = Path(a.path).resolve() if a.path else None
    if src and not src.is_file():
        die(f"no such file: {a.path}")
    dest = RAW / f"{a.date}_{a.kind}_{slugify(a.slug)}{src.suffix.lower() if src else '.md'}"
    if dest.exists():
        die(f"{dest.name} already exists; raw files are never overwritten (pick another --slug)")
    if src:
        shutil.copy2(src, dest)  # the original is left where it was
    else:
        dest.write_text(sys.stdin.read() if a.text == "-" else a.text, encoding="utf-8")
    print(f"memory/raw/{dest.name}  (cite as [[raw/{dest.name}]])")


def append_log(op: str, title: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"- {dt.datetime.now():%Y-%m-%d %H:%M} · {op} · {' '.join(title.split())}\n")


def cmd_log(a) -> None:
    if a.op not in LOG_OPS:
        die(f"op must be one of: {', '.join(sorted(LOG_OPS))}")
    append_log(a.op, a.title)


def build_index(ps: list[Page]) -> str:
    L = ["# Memory index", "", "<!-- Generated by `python3 tools/memory.py index`. Do not edit. -->", ""]
    for type_, (_, _, heading) in TYPES.items():
        group = [p for p in ps if p.get("type") == type_]
        if group:
            L += [f"## {heading}", ""]
            for p in group:
                tag = (f" (merged into [[{p.get('merged_into')}]])" if p.get("merged_into")
                       else " (superseded)" if p.get("status") == "superseded" else "")
                L.append(f"- [[{p.stem}]]{tag} — {p.get('summary') or p.get('title')}")
            L.append("")
    if len(L) == 4:
        L += ["_Nothing remembered yet._", ""]
    return "\n".join(L).rstrip() + "\n"


def cmd_index(a=None) -> None:
    new = build_index(pages())
    if new != read(INDEX):
        INDEX.parent.mkdir(parents=True, exist_ok=True)
        INDEX.write_text(new, encoding="utf-8")
    if a is not None:
        print(f"memory/index.md: {new.count(chr(10))} lines")


def overdue() -> list[str]:
    return [l.strip() for l in read(NOW).splitlines()
            if (m := DUE_RE.search(l)) and re.fullmatch(DATE, m.group(1)) and m.group(1) < today()]


def lint() -> tuple[list[str], list[str]]:
    E, W = [], []
    ps = pages()
    names = {p.stem for p in ps}
    files = list(RAW.iterdir()) if RAW.is_dir() else []
    raws = {f.name for f in files} | {f.stem for f in files}
    seen: dict[str, Path] = {}
    for p in ps:
        where = str(p.path.relative_to(ROOT))
        if p.stem in seen:
            E.append(f"{where}: same name as {seen[p.stem].relative_to(ROOT)}; names are unique across the wiki")
        seen[p.stem] = p.path
        for k in ("title", "type", "updated"):
            if not p.get(k):
                E.append(f"{where}: missing frontmatter `{k}`")
        t = p.get("type")
        if t not in TYPES:
            E.append(f"{where}: type must be one of {', '.join(TYPES)}")
        elif p.path.parent != WIKI / TYPES[t][0]:
            E.append(f"{where}: a {t} page belongs in memory/wiki/{TYPES[t][0]}/")
        if p.get("updated") and not re.fullmatch(DATE, p.get("updated")):
            E.append(f"{where}: `updated` must be YYYY-MM-DD")
        if p.get("status") and p.get("status") not in ("active", "superseded"):
            E.append(f"{where}: status must be active or superseded")
        for k in ("supersedes", "superseded_by", "merged_into"):
            if p.get(k) and p.get(k) not in names:
                E.append(f"{where}: `{k}: {p.get(k)}` is not a page")
        if not p.get("summary") and not p.get("merged_into"):
            W.append(f"{where}: empty summary (the index shows the title instead)")
        for link in p.links:
            ok = link[4:] in raws if link.startswith("raw/") else link in names
            if not ok:
                E.append(f"{where}: broken link [[{link}]] (pages: [[slug]], sources: [[raw/<file>]])")
        if p.evidence is None:
            E.append(f"{where}: missing `## Evidence log` (last section)")
        for line in p.evidence or []:
            if line.startswith("## "):
                E.append(f"{where}: `{line}` comes after the evidence log, which must be the last section")
            elif not EVIDENCE_RE.match(line):
                E.append(f"{where}: bad evidence line, want `- YYYY-MM-DD · fact — [[source]]`: {line[:80]}")
    now = read(NOW)
    for h in ("## Focus", "## Waiting on", "## Next"):
        if not re.search(rf"^{h}\s*$", now, re.M):
            E.append(f"memory/now.md: missing `{h}` section")
    for m in DUE_RE.finditer(CODE_RE.sub("", now)):
        if not re.fullmatch(DATE, m.group(1)):
            E.append(f"memory/now.md: `due: {m.group(1)}` must be YYYY-MM-DD")
    W += [f"memory/now.md: overdue: {l}" for l in overdue()]
    if read(INDEX) != build_index(ps):
        E.append("memory/index.md is stale: run `python3 tools/memory.py index`")
    return E, W


def cmd_lint(a) -> None:
    if a.hook:  # Stop hook: rebuild the index, block once on errors, never loop
        try:
            payload = json.load(sys.stdin)
        except ValueError:
            payload = {}
        cmd_index()
        errors, _ = lint()
        if errors and payload.get("stop_hook_active"):
            print(f"memory lint: {len(errors)} error(s) left after a Stop block:\n" + "\n".join(errors), file=sys.stderr)
            append_log("lint", f"{len(errors)} error(s) left unfixed after Stop block; first: {errors[0]}")
        elif errors:
            reason = "Memory lint failed; fix before finishing:\n" + "\n".join(f"  - {e}" for e in errors)
            print(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(0)
    errors, warnings = lint()
    for tag, items in (("error", errors), ("warning", warnings)):
        for i in items:
            print(f"{tag}: {i}")
    if not onboarded():
        print("info: not onboarded yet (identity.md is missing or holds _TODO: lines)")
    print(f"lint: {len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1 if errors else 0)


def cmd_status(a) -> None:
    if not onboarded():
        out = ["## NOT ONBOARDED: run the onboarding skill before any other work (the owner can say "
               "\"onboard me\"), unless the owner says they are working on the template itself."]
    else:
        c = identity()
        out = [f"## {c.get('name')}, {c.get('role')} · serves {c.get('serves')} · owner "
               f"{c.get('owner')} · {c.get('timezone')} · today {today()}"]
    out += [f"NOTE: {n}" for n in getattr(a, "notes", [])]
    out += [f"OVERDUE: {l}" for l in overdue()]
    log = [l for l in read(LOG).splitlines() if l.startswith("- ")][-3:]
    out += ["", "## Recent log", *(log or ["_empty_"]), "", *read(NOW).splitlines(), "", *read(INDEX).splitlines()]
    text, cut = "\n".join(out), False
    if len(out) > MAX_LINES:
        text, cut = "\n".join(out[:MAX_LINES]), True
    if len(text) > MAX_CHARS:
        text, cut = text[:text.rfind("\n", 0, MAX_CHARS - 100)], True
    print(text + ("\n... truncated: read memory/index.md for the rest." if cut else ""))


WRITE_RE = re.compile(r"""\b(rm|mv|cp|tee|truncate|touch|chmod|ln|dd|install|rsync)\b|sed\s+(-\w*\s+)*-i|>>?\s*["']?[^\s"']*memory/raw|\bgit\s+(rm|mv|checkout|restore)\b""")


def cmd_guard(a) -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)
    ti, raw, tmpl = data.get("tool_input") or {}, RAW.resolve(), (HOST / "template").resolve()
    blocked = None
    if data.get("tool_name") == "Bash":
        for seg in re.split(r"&&|\|\||;|\||\n", ti.get("command", "")):
            if "memory/raw" in seg and WRITE_RE.search(seg) and "tools/memory.py" not in seg:
                blocked = "raw"
            elif ".agent8/template" in seg and (WRITE_RE.search(seg) or re.search(r">>?\s*\S*\.agent8/template", seg)):
                blocked = "template"
    elif target := ti.get("file_path") or ti.get("notebook_path"):
        p = Path(target)
        p = (p if p.is_absolute() else Path(data.get("cwd") or ROOT) / p).resolve()
        blocked = "raw" if p.is_relative_to(raw) else "template" if p.is_relative_to(tmpl) else None
    if blocked == "raw":
        print("memory/raw/ is immutable: never write, move or delete there. File sources with "
              "`python3 tools/memory.py file`; record corrections in the wiki.", file=sys.stderr)
        sys.exit(2)
    if blocked == "template":
        print(".agent8/template/ is the installed template, read-only: change how you work in "
              "LOCAL.md or skills/ instead (AGENTS.md §6).", file=sys.stderr)
        sys.exit(2)


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def cmd_commit(a) -> None:
    """Commit the own layer and memory, by explicit path, never `git add -A`: template files and
    anything else in the folder are left alone. Does nothing when this folder is not the top of
    a git repository, or when the owner keeps these paths out of git (.gitignore,
    .git/info/exclude)."""
    try:
        top = git("rev-parse", "--show-toplevel")
    except FileNotFoundError:
        print("git is not installed: nothing committed")
        return
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != ROOT:
        print("this folder is not a git repository of its own: nothing committed")
        return
    keep = [p for p in OWN_PATHS if (ROOT / p).exists() and git("check-ignore", "-q", p).returncode != 0]
    if not keep:
        print("your own files and memory are kept out of git here: nothing committed")
        return
    if (r := git("add", "-A", "--", *keep)).returncode != 0:
        die(f"git add failed: {r.stderr.strip()}")
    if git("diff", "--cached", "--quiet", "--", *keep).returncode == 0:
        print("nothing new to commit")
        return
    if (r := git("commit", "-q", "-m", a.message, "--", *keep)).returncode != 0:
        die(f"git commit failed: {(r.stderr or r.stdout).strip()}")
    print(f"committed: {', '.join(keep)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new"); s.add_argument("type"); s.add_argument("title"); s.add_argument("--slug")
    s.set_defaults(fn=cmd_new)
    s = sub.add_parser("file"); s.add_argument("path", nargs="?"); s.add_argument("--text")
    for k in ("--date", "--kind", "--slug"):
        s.add_argument(k, required=True)
    s.set_defaults(fn=cmd_file)
    s = sub.add_parser("log"); s.add_argument("op"); s.add_argument("title"); s.set_defaults(fn=cmd_log)
    s = sub.add_parser("lint"); s.add_argument("--hook", action="store_true"); s.set_defaults(fn=cmd_lint)
    s = sub.add_parser("commit"); s.add_argument("message"); s.set_defaults(fn=cmd_commit)
    for name, fn in (("index", cmd_index), ("status", cmd_status), ("guard", cmd_guard)):
        sub.add_parser(name).set_defaults(fn=fn)
    a = ap.parse_args()
    if a.cmd != "guard":  # guard runs before every tool call: keep it read-only and fast
        made = ensure_seeds()
        a.notes = ([f"created from seed/: {', '.join(made)}"] if made else []) + link_own_skills()
    a.fn(a)


if __name__ == "__main__":
    main()
