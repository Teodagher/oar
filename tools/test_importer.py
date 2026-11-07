"""The reference reading of repositories that aren't templates yet (importer.py, SPEC §12),
and its agreement with agent8's own (backend/templates/gitimport.ts, T-151).

The agreement tests run agent8's converter through Node and are skipped when it isn't next to
the spec (the spec's own repository) or Node can't run TypeScript.

Run: python3 -m unittest discover -s spec/agent-format/tools
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agentfmt  # noqa: E402
import importer  # noqa: E402
import validate as v  # noqa: E402

DUMP = HERE.parents[2] / "backend" / "templates" / "convert_dump.ts"
SHA = "a" * 40


def parse_yaml(t: str):
    """As agent8's tests read YAML (through JSON, dates as text)."""
    return json.loads(json.dumps(yaml.safe_load(t), default=str))


def node_ok() -> bool:
    if not DUMP.is_file() or not shutil.which("node"):
        return False
    r = subprocess.run(["node", "--experimental-strip-types", "-e", "1"], capture_output=True)
    return r.returncode == 0


NODE = node_ok()

BASE = {
    "agent.yaml": "name: base\nversion: 0.1.0\ndescription: Base.\nlicense: MIT\nmodel: {preferred: gpt-4o}\n"
                  "compliance: {risk_tier: high, supervision: {human_in_the_loop: always}}\n",
    "SOUL.md": "Base soul.",
    "RULES.md": "Base rule.",
    "skills/shared/SKILL.md": "---\nname: shared\ndescription: from the base\n---\nBase.\n",
    "skills/greet/SKILL.md": "---\nname: greet\ndescription: the base's greet\n---\nOld.\n",
    "tools/lookup.yaml": "name: lookup\ndescription: Looks things up.\nimplementation: {type: script, path: lookup.py, runtime: python3}\n",
    "tools/lookup.py": "print(1)\n",
    "memory/MEMORY.md": "the base's memory",
}
FULL = {
    "agent.yaml": "spec_version: \"0.1.0\"\nname: child\nversion: 2.0.0\ndescription: Child.\n"
                  "extends: https://github.com/o/base.git\nauthor: Ann\n"
                  "compliance:\n  communications: {fair_balanced: true, no_misleading: true}\n"
                  "  data_governance: {pii_handling: redact}\n  recordkeeping: {audit_logging: true}\n"
                  "  supervision:\n    escalation_triggers: [{confidence_below: 0.7}, {action_type: trade}]\n"
                  "  segregation_of_duties:\n    assignments: {maker: [analyst], checker: [reviewer]}\n"
                  "    conflicts: [[analyst, reviewer]]\n"
                  "    handoffs: [{action: publish, required_roles: [analyst, reviewer]}]\n"
                  "  financial_governance: {enabled: true, spending: {max_per_transaction_cents: 5000}, "
                  "approval: {require_above_cents: 1000.0}}\n"
                  "runtime: {max_turns: 5}\ndelegation: {mode: auto}\na2a: {protocols: [http]}\n"
                  "registries: [{name: skillsmp, url: https://api.skillsmp.com}]\n"
                  "dependencies: [{name: fact-checker, source: https://github.com/o/fc.git, mount: agents/fc,\n"
                  "  vendor_management: {due_diligence_date: 2026-01-15}}]\n"
                  "agents: {checker: {description: Checks facts., path: ./agents/checker}}\n"
                  "mcp_servers:\n  search: {command: npx, args: [\"-y\", \"search-mcp\"], env: {SEARCH_API_KEY: \"${SEARCH_API_KEY}\"}}\n"
                  "  remote: {url: \"https://mcp.example.com/sse\", headers: {Authorization: \"Bearer ${REMOTE_TOKEN}\"}}\n"
                  "  leak: {command: tool, args: [\"--key=${LEAK_KEY}\"]}\n"
                  "  bad: {command: /usr/bin/x}\n  odd: {}\n",
    "RULES.md": "Child rule.",
    "DUTIES.md": "Only analyse.",
    "AGENTS.md": "Fallback instructions.",
    "skills/greet/SKILL.md": "---\nname: greet\ndescription: the child's greet\n---\nNew.\n",
    "agents/checker/agent.yaml": "name: checker\nversion: 0.1.0\ndescription: Checks facts.\n",
    "agents/checker/SOUL.md": "Check.",
    "agents/quick.md": "---\r\nname: quick\r\ndescription: \"Answers quickly\"\r\nmodel: {preferred: haiku}\r\n---\r\n# Quick\r\n",
    "agents/notes.txt": "not an agent",
    "workflows/review.yaml": "name: review\n",
    "workflows/onboard.md": "# Onboard\n",
    "hooks/hooks.yaml": "hooks: {on_session_start: [{script: scripts/a.sh}]}\n",
    "hooks/scripts/a.sh": "#!/bin/sh\necho hi\n",
    "config/default.yaml": "log_level: info\n",
    "knowledge/index.yaml": "entries:\n  - {path: rules.md, always_load: true}\n  - {path: ./notes.md, description: \"Extra\\n  notes.\"}\n"
                            "  - {path: missing.md}\n  - {path: ../SOUL.md}\n",
    "knowledge/rules.md": "R.",
    "knowledge/notes.md": "N.",
    "knowledge/leak.md": "token ghp_" + "a" * 36,
    "memory/MEMORY.md": "the child's memory",
    ".gitagent/state.json": "{}",
    ".env.example": "OPENAI_API_KEY=\nexport GITHUB_PAT=\nLOG_LEVEL=info\nLEAK_KEY=\n",
    "README.md": "# Child\n\nA child agent for tests.\n",
}
PLAIN = {
    "CLAUDE.md": "@AGENTS.md\n\nUse British spelling.\n",
    "AGENTS.md": "﻿You keep notes.\n",
    ".claude/skills/note/SKILL.md": "---\nname: note\ndescription: notes\n---\nNote.\n",
    "skills/old/SKILL.md": "old",
    "notes/today.md": "client X",
    "knowledge/a.md": "A.",
    "knowledge/sub/b.md": "B.",
    "secrets.yaml": "x: 1\n",
    ".env": "A=1\n",
    "id_rsa": "nope",
    "seed/x.md": "x",
    "LICENSE": "MIT License\n\nPermission is hereby granted, free of charge, ...",
    "README.md": "# T\n\n[![b](x)](y)\n\n" + "Plain repo é " * 40 + "\n",
    "link-to-notes": {"link": "notes/today.md"},
    "docs/guide.md": "G",
    "docs/latest": {"link": "guide.md"},
}
MINIMAL = {
    "agent.yaml": "name: Neuron Worker\nversion: not-a-version\ndescription: \"  \"\n",
    "SOUL.md": "Work.",
    "AGENTS.md": "Do the work.",
    "identity.md": "me",
}
OWN_MCP = {
    "agent.yaml": "name: has-mcp\nversion: 1.0.0\ndescription: Has its own MCP file.\n"
                  "mcp_servers: {x: {command: npx, args: [x]}}\nmodel: claude-sonnet-4-6\n",
    "SOUL.md": "Hi 😀 " * 80,
    ".mcp.json": json.dumps({"mcpServers": {"own": {"command": "npx", "args": ["own"], "env": {"OWN_TOKEN": "${OWN_TOKEN}"},
                                                    "url2": "${HOME}/x"}}}),
}
NO_INSTRUCTIONS = {"agent.yaml": "name: empty\nversion: 1.0.0\ndescription: Empty.\n", "README.md": "# Empty\n"}
KEY_IN_MANIFEST = {"agent.yaml": "name: leaky\nversion: 1.0.0\ndescription: x\nmetadata: {k: AKIAABCDEFGHIJKLMNOP}\n",
                   "SOUL.md": "S."}


def write(root: Path, files: dict) -> Path:
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, dict):
            os.symlink(body["link"], p)
        else:
            p.write_bytes(body.encode("utf-8") if isinstance(body, str) else body)
            if rel.endswith(".sh"):
                p.chmod(0o755)
    return root


def src(repo="child", ref=None, owner="o"):
    return {"url": f"https://github.com/{owner}/{repo}", "repo": repo, "owner": owner, "commit": SHA, "ref": ref}


def py_convert(d: Path, s: dict, parents=(), stop=None) -> dict:
    files = agentfmt.check_entries(agentfmt.read_folder(str(d)))
    pars = [{"url": u, "commit": c, "files": agentfmt.check_entries(agentfmt.read_folder(str(pd)))} for u, c, pd in parents]
    try:
        c = importer.convert(files, s, parse_yaml, pars, stop)
    except importer.Refused as exc:
        return {"refused": str(exc)}
    out = {}
    for p, e in c["files"].items():
        out[p] = ["file", e["mode"], hashlib.sha256(e["data"]).hexdigest()] if e["kind"] == "file" \
            else ["link", e["target"]] if e["kind"] == "link" else ["dir"]
    return {"kind": c["kind"], "version": c["version"], "manifest": c["manifest"], "files": out, "info": c["info"]}


def ts_convert(d: Path, s: dict, parents=(), stop=None) -> dict:
    arg = {"dir": str(d), "src": s, "parents": [{"url": u, "commit": c, "dir": str(pd)} for u, c, pd in parents],
           "extendsStop": stop}
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(DUMP), json.dumps(arg)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


class Reading(unittest.TestCase):
    """What the reference reading does, on its own."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="importer-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def conv(self, files, **kw):
        d = write(self.tmp / "r", files)
        return importer.convert(agentfmt.check_entries(agentfmt.read_folder(str(d))), src(**kw), parse_yaml)

    def test_full_opengap_with_its_parent(self):
        d = write(self.tmp / "c", FULL)
        b = write(self.tmp / "b", BASE)
        files = agentfmt.check_entries(agentfmt.read_folder(str(d)))
        pf = agentfmt.check_entries(agentfmt.read_folder(str(b)))
        c = importer.convert(files, src(), parse_yaml, [{"url": "https://github.com/o/base", "commit": "b" * 40, "files": pf}])
        agents = c["files"]["AGENTS.md"]["data"].decode()
        self.assertTrue(agents.startswith("## Soul\n\nBase soul.\n\n## Rules\n\nBase rule.\n\nChild rule.\n\n## Duties\n\n"
                                          "Only analyse.\n\n## Agent\n\nFallback instructions."))
        for want in ("Risk tier: HIGH", "  - confidence_below: 0.7", "  - maker holds analyst",
                     "  - no single agent may hold both analyst and reviewer",
                     "  - publish must pass through analyst → reviewer", "  - at most 5000 cents per transaction",
                     "  - a person approves anything above 1000 cents", "- knowledge/notes.md: Extra notes.",
                     "- lookup: Looks things up. Run: `python3 tools/lookup.py`", "- checker: Checks facts. (agents/checker)",
                     "- quick: Answers quickly (agents/quick.md)", "workflows/: onboard.md, review.yaml.", "## Memory"):
            self.assertIn(want, agents)
        self.assertNotIn("agents/notes.txt", agents)
        self.assertNotIn("missing.md", agents)
        self.assertIn("seed/knowledge/rules.md", c["files"])
        self.assertNotIn("seed/knowledge/leak.md", c["files"])
        self.assertEqual(json.loads(c["files"][".mcp.json"]["data"])["mcpServers"].keys(), {"search", "remote"})
        x = c["manifest"]["x-agent8"]
        self.assertEqual([s["item"] for s in x["secrets"]], ["SEARCH_API_KEY", "REMOTE_TOKEN", "OPENAI_API_KEY", "GITHUB_PAT",
                                                           "LEAK_KEY"])
        self.assertEqual(x["secrets"][0]["env"], {"SEARCH_API_KEY": "{{vault:SEARCH_API_KEY}}"})
        un = "\n".join(c["info"]["unmapped"])
        for want in ("model (prefers gpt-4o)", "runtime", "hooks/hooks.yaml", "dependencies (fact-checker)", "delegation",
                     "a2a", "registries", "config/", "compliance", "tools/", "MCP server leak: a variable",
                     "MCP server bad: an absolute path", "MCP server odd: no command or url"):
            self.assertIn(want, un)
        self.assertEqual(c["info"]["extends"], [{"url": "https://github.com/o/base", "commit": "b" * 40}])
        # The result is a valid template, and the installer takes it.
        out = self.tmp / "out"
        agentfmt.materialise(c["files"] | {"agent.yaml": agentfmt.file_entry(
            "\n".join(agentfmt.to_yaml(c["manifest"])) + "\n")}, str(out))
        rep = v.validate_template(out)
        self.assertEqual(rep.errors, [])

    def test_plain_and_minimal(self):
        c = self.conv(PLAIN)
        self.assertEqual(c["kind"], "plain")
        self.assertIn("seed/knowledge/sub/b.md", c["files"])
        self.assertNotIn("link-to-notes", c["files"])
        self.assertEqual(c["manifest"]["license"], "MIT")
        m = self.conv(MINIMAL, repo="neuron-lyzr-worker", ref="v0.3.0")
        self.assertEqual((m["manifest"]["name"], m["version"]), ("neuron-lyzr-worker", "0.3.0"))
        self.assertNotIn("identity.md", m["files"])

    def test_refusals(self):
        for files, words in ((NO_INSTRUCTIONS, "no SOUL.md"), (KEY_IN_MANIFEST, "looks like a key")):
            with self.assertRaises(importer.Refused) as cm:
                self.conv(files)
            self.assertIn(words, str(cm.exception))
        with self.assertRaises(importer.Refused):
            self.conv({"agent.yaml": "name: t\nx-agent8: {format: \"0.2\"}\n", "AGENTS.md": "x"})

    def test_extends_addresses(self):
        self.assertEqual(importer.extends_github("https://github.com/o/base.git/")["url"], "https://github.com/o/base")
        for bad in ("https://gitlab.com/o/b", "../base", "git@github.com:o/b.git", "https://github.com/o"):
            self.assertIsNone(importer.extends_github(bad), bad)


@unittest.skipUnless(NODE, "agent8's converter isn't next to the spec, or Node can't run it")
class SameAsAgent8(unittest.TestCase):
    """importer.py and agent8's gitimport.ts give the same result on the same repositories."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="importer-same-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def same(self, name, files, s, parents=(), stop=None):
        d = write(self.tmp / name, files)
        pars = [(u, c, write(self.tmp / f"{name}-p{i}", pf)) for i, (u, c, pf) in enumerate(parents)]
        py, ts = py_convert(d, s, pars, stop), ts_convert(d, s, pars, stop)
        self.maxDiff = None
        self.assertEqual(py, ts, name)
        return py

    def test_the_shared_lists(self):
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(DUMP), '{"constants": true}'],
                           capture_output=True, text=True, check=True)
        k = json.loads(r.stdout)
        self.assertEqual(k["guessed_data"], importer.GUESSED_DATA)
        self.assertEqual(k["secret_file"].replace("\\/", "/"), importer.SECRET_FILE_SRC)
        self.assertEqual([s.replace("\\/", "/") for s in k["secrets"]], importer.SECRET_SRCS)

    def test_opengap_with_parents(self):
        grand = {"agent.yaml": "name: grand\nversion: 0.0.1\ndescription: G.\nextends: https://github.com/o/older\n",
                 "RULES.md": "Grand rule.", "tools/g.yaml": "name: g\n"}
        out = self.same("full", FULL, src(), [("https://github.com/o/base", "b" * 40, BASE),
                                               ("https://github.com/o/grand", "c" * 40, grand)],
                        {"url": "https://github.com/o/older", "why": "more than 3 levels"})
        self.assertIn("seed/knowledge/rules.md", out["files"])

    def test_opengap_not_followed(self):
        self.same("lone", FULL, src(ref="v2.0.0"), (),
                  {"url": "https://gitlab.com/o/base", "why": "only a GitHub repository is followed"})
        self.same("lone2", FULL, src())

    def test_plain_minimal_own_mcp_and_refusals(self):
        self.same("plain", PLAIN, src(repo="Notes.Agent.git"))
        self.same("minimal", MINIMAL, src(repo="neuron-lyzr-worker", ref="v0.3.0"))
        self.same("own-mcp", OWN_MCP, src())
        for i, files in enumerate((NO_INSTRUCTIONS, KEY_IN_MANIFEST)):
            self.assertIn("refused", self.same(f"refused{i}", files, src()))

    def test_the_examples_shipped_with_opengap_style_repos(self):
        # Real OpenGAP repositories, when a folder of them is given (not in CI: they're fetched).
        root = os.environ.get("OPENGAP_REPOS")
        if not root:
            self.skipTest("OPENGAP_REPOS not set")
        for d in sorted(Path(root).iterdir()):
            if d.is_dir():
                with self.subTest(repo=d.name):
                    py, ts = py_convert(d, src(repo=d.name)), ts_convert(d, src(repo=d.name))
                    self.assertEqual(py, ts)


if __name__ == "__main__":
    unittest.main()
