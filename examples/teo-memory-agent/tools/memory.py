#!/usr/bin/env python3
"""Memory bookkeeping for the example agent. Stdlib only; paths resolve from the agent's folder.

  memory.py new <person|org|topic|decision|lesson|procedure> "Title"
  memory.py file <path> | --text "<text>|-"  --date YYYY-MM-DD --kind <kind> --slug <slug>
  memory.py log <op> "title"
  memory.py index | lint [--hook] | status
  memory.py guard        # PreToolUse hook: memory/raw/ and the template are read-only

This is a compact stand-in for the boilerplate's tools/memory.py. Changed for format 0.2:
"onboarded" is read from identity.md (the own layer), not from CLAUDE.md / agent.json.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parent.parent)
MEM = ROOT / "memory"
WIKI, RAW = MEM / "wiki", MEM / "raw"
INDEX, LOG, NOW = MEM / "index.md", MEM / "log.md", MEM / "now.md"
IDENTITY = ROOT / "identity.md"
TYPES = {
    "lesson": ("howto", "lesson", "Lessons (owner feedback: apply these)"),
    "procedure": ("howto", "procedure", "Procedures"),
    "person": ("entities", "entity", "People"),
    "org": ("entities", "entity", "Organizations"),
    "topic": ("entities", "entity", "Topics"),
    "decision": ("entities", "entity", "Decisions"),
}
MARKER = "_TODO:"
EVIDENCE_RE = re.compile(r"^- \d{4}-\d{2}-\d{2} · .+ — \[\[[^\]]+\]\]\s*$")


def today() -> str:
    return dt.date.today().isoformat()


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()[:60] or "untitled"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def meta(text: str) -> dict:
    out = {}
    if text.startswith("---\n") and (end := text.find("\n---", 4)) != -1:
        for line in text[4:end].splitlines():
            k, sep, v = line.partition(":")
            if sep:
                out[k.strip()] = v.strip()
    return out


def onboarded() -> bool:
    return IDENTITY.exists() and MARKER not in read(IDENTITY)


def pages():
    return sorted(WIKI.glob("*/*.md")) if WIKI.exists() else []


def cmd_new(kind: str, title: str) -> None:
    if kind not in TYPES:
        sys.exit(f"error: type must be one of {', '.join(TYPES)}")
    folder, tmpl, _ = TYPES[kind]
    path = WIKI / folder / f"{slugify(title)}.md"
    if path.exists():
        sys.exit(f"error: {path.relative_to(ROOT)} exists")
    body = read(ROOT / "templates" / f"{tmpl}.md")
    body = body.replace("{{title}}", title).replace("{{type}}", kind).replace("{{today}}", today())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    print(path.relative_to(ROOT))


def cmd_file(args: list[str]) -> None:
    opts = dict(zip(args[1::2], args[2::2])) if args and args[0].startswith("--") else dict(zip(args[2::2], args[3::2]))
    text = opts.get("--text")
    if text == "-":
        text = sys.stdin.read()
    elif text is None:
        text = read(Path(args[0]))
    name = f"{opts.get('--date', today())}_{opts.get('--kind', 'other')}_{slugify(opts.get('--slug', 'source'))}.md"
    path = RAW / name
    if path.exists():
        sys.exit(f"error: {path.relative_to(ROOT)} exists (raw is immutable)")
    RAW.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(path.relative_to(ROOT))


def cmd_log(op: str, title: str) -> None:
    MEM.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"- {today()} {op} · {title}\n")


def cmd_index() -> None:
    groups = {k: [] for k in TYPES}
    for p in pages():
        m = meta(read(p))
        if m.get("type") in groups:
            groups[m["type"]].append(f"- [[{p.stem}]] {m.get('summary', '')}".rstrip())
    out = ["# Memory index", ""]
    for kind, (_, _, heading) in TYPES.items():
        if groups[kind]:
            out += [f"## {heading}", *groups[kind], ""]
    INDEX.write_text("\n".join(out), encoding="utf-8")


def lint() -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    if not onboarded():
        warnings.append("not onboarded yet (identity.md missing or holds _TODO:)")
    if not NOW.exists():
        errors.append("memory/now.md is missing")
    for p in pages():
        text = read(p)
        m = meta(text)
        rel = p.relative_to(ROOT)
        for key in ("title", "type", "summary", "updated"):
            if key not in m:
                errors.append(f"{rel}: frontmatter lacks {key}")
        if "## Evidence log" not in text:
            errors.append(f"{rel}: no '## Evidence log' section")
        else:
            for line in text.split("## Evidence log", 1)[1].splitlines():
                if line.startswith("- ") and not EVIDENCE_RE.match(line):
                    errors.append(f"{rel}: malformed evidence line: {line[:60]}")
    return errors, warnings


def cmd_lint(hook: bool) -> int:
    errors, warnings = lint()
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr if hook else sys.stdout)
    for e in errors:
        print(f"error: {e}", file=sys.stderr if hook else sys.stdout)
    return 2 if (errors and hook) else (1 if errors else 0)


def cmd_status() -> None:
    print("Identity:", "onboarded" if onboarded() else "NOT ONBOARDED: run the onboarding skill")
    overdue = [ln for ln in read(NOW).splitlines() if (m := re.search(r"due:\s*(\S+)", ln)) and m.group(1) < today()]
    if overdue:
        print("Overdue:", *overdue, sep="\n  ")
    print("\n--- now.md ---\n" + read(NOW).strip())
    print("\n--- index (head) ---\n" + "\n".join(read(INDEX).splitlines()[:40]))
    print("\n--- recent log ---\n" + "\n".join(read(LOG).splitlines()[-5:]))


def cmd_guard() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    tool = event.get("tool_input") or {}
    target = str(tool.get("file_path") or tool.get("notebook_path") or "")
    command = str(tool.get("command") or "")
    protected = (str(RAW) + os.sep, str(ROOT / ".agent8") + os.sep)
    if target and os.path.abspath(target).startswith(protected) and Path(target).exists():
        print("memory/raw/ and the template are read-only", file=sys.stderr)
        return 2
    if re.search(r"(rm|mv|>)\s+\S*(memory/raw/|\.agent8/template/)", command):
        print("memory/raw/ and the template are read-only", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    if cmd == "new" and len(rest) >= 2:
        cmd_new(rest[0], rest[1])
    elif cmd == "file":
        cmd_file(rest)
    elif cmd == "log" and len(rest) >= 2:
        cmd_log(rest[0], rest[1])
    elif cmd == "index":
        cmd_index()
    elif cmd == "lint":
        return cmd_lint("--hook" in rest)
    elif cmd == "status":
        cmd_status()
    elif cmd == "guard":
        return cmd_guard()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
