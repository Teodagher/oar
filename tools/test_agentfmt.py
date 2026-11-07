#!/usr/bin/env python3
"""Tests for agentfmt.py, the reference CLI. Run: python3 -m unittest discover -s spec/agent-format/tools

Needs git, PyYAML and jsonschema. The agreement test with agent8's installer runs only when
the agent8 repository is next to the spec (it is skipped in the spec's own repository).
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agentfmt as af  # noqa: E402
import validate as v  # noqa: E402

SPEC = Path(__file__).resolve().parent.parent
EXAMPLES = SPEC / "examples"
HELPER = SPEC.parent.parent / "backend" / "agent8-cli" / "agent8-agent"
NOW = "2026-11-07T12:00:00Z"
HAS_GIT = shutil.which("git") is not None

MANIFEST = """\
name: tiny
version: {version}
description: A tiny agent
license: MIT
x-agent8:
  format: "{fmt}"
  layout:
    skills: .claude/skills
  data:
    - /memory/
    - /notes.md
  setup:
    - id: owner_name
      prompt: Your name
      type: string
      required: true
{extra}"""


def tiny(version="1.0.0", fmt="0.2", extra="", agents="# Tiny\n\nYour identity is in identity.md.\n"):
    return {
        "agent.yaml": MANIFEST.format(version=version, fmt=fmt, extra=extra),
        "AGENTS.md": agents,
        "CLAUDE.md": "@AGENTS.md\n@identity.md\n@LOCAL.md\n",
        "README.md": "# Tiny\n",
        "LICENSE": "MIT\n",
        "seed/identity.md": "# Identity\n\nYou work for {{answer:owner_name}}.\n",
        "seed/memory/now.md": "# Now\n",
        ".claude/skills/remember/SKILL.md": "---\nname: remember\ndescription: Remember things.\n---\nWrite it down.\n",
        "tools/run.py": "print('hi')\n",
    }


def run_cli(*argv):
    o, e = io.StringIO(), io.StringIO()
    with redirect_stdout(o), redirect_stderr(e):
        code = af.main([str(a) for a in argv])
    return code, o.getvalue() + e.getvalue()


def tree(root):
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for n in filenames:
            p = os.path.join(dirpath, n)
            rel = os.path.relpath(p, root)
            out[rel] = os.readlink(p) if os.path.islink(p) else Path(p).read_bytes()
    return out


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        af.remove_tree(str(self.tmp))

    def write_tree(self, root: Path, files: dict):
        for rel, val in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(val, tuple):           # ("link", target)
                os.symlink(val[1], p)
            else:
                p.write_text(val, encoding="utf-8")
                if rel.endswith((".py", ".sh")):
                    os.chmod(p, 0o755)

    def git(self, repo, *args):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True, env=env)

    def repo(self, files: dict, tag: str | None = "v1.0.0", name="tpl") -> Path:
        root = self.tmp / name
        root.mkdir(exist_ok=True)
        self.write_tree(root, files)
        if not (root / ".git").exists():
            self.git(root, "init", "-q")
        self.git(root, "add", "-A")
        self.git(root, "commit", "-qm", "release", "--allow-empty")
        if tag:
            self.git(root, "tag", tag)
        return root

    def release(self, root: Path, files: dict, tag: str, remove=()):
        for rel in remove:
            p = root / rel
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        self.write_tree(root, files)
        self.git(root, "add", "-A")
        self.git(root, "commit", "-qm", tag, "--allow-empty")
        self.git(root, "tag", tag)

    def install(self, src, dest, *extra):
        return run_cli("install", src, dest, "--answer", "owner_name=Sam", "--yes", "--now", NOW, *extra)


# ---------------------------------------------------------------- the shared safety checks

class TestSafety(unittest.TestCase):
    def f(self, data=b"x"):
        return {"kind": "file", "data": data, "mode": 0o644}

    def test_refuses_dotdot_absolute_and_odd_paths(self):
        for bad in ("../x", "a/../../x", "/etc/passwd", "~/x", "a//b", "./a", "a\\b", "a/\x01b", ".git/config",
                    "x/.git/HEAD"):
            with self.subTest(bad=bad), self.assertRaises(af.Refused):
                af.check_entries({bad: self.f()})

    def test_refuses_links_out(self):
        for files in (
            {"l": {"kind": "link", "target": "/etc/passwd"}},
            {"a/l": {"kind": "link", "target": "../../x"}},
            {"l": {"kind": "link", "target": ".."}},
            # each link stays inside on its own, together they leave
            {"d/a": {"kind": "link", "target": "../b"}, "b": {"kind": "link", "target": "../.."}},
            {"a": {"kind": "link", "target": "b"}, "b": {"kind": "link", "target": "a"}},
            {"l": {"kind": "link", "target": "missing"}},
        ):
            with self.subTest(files=files), self.assertRaises(af.Refused):
                af.check_entries(dict(files))

    def test_link_inside_is_fine(self):
        files = af.check_entries({".claude/skills/s/SKILL.md": self.f(),
                                  ".agents/skills": {"kind": "link", "target": "../.claude/skills"}})
        self.assertEqual(files[".agents"]["kind"], "dir")

    def test_file_under_a_file(self):
        with self.assertRaises(af.Refused):
            af.check_entries({"a": self.f(), "a/b": self.f()})

    def test_format_gate(self):
        with self.assertRaises(af.TooNew) as cm:
            af.format_check({"x-agent8": {"format": "1.0"}})
        self.assertIn("needs updating", str(cm.exception))
        got = af.format_check({"x-agent8": {"format": "0.9", "data": [], "sidecar": 1}})
        self.assertTrue(got["newer"])
        self.assertEqual(got["skipped"], ["sidecar"])
        for bad in ({"x-agent8": {"format": 0.2}}, {"x-agent8": {}}, {}):
            with self.assertRaises(af.Refused):
                af.format_check(bad)

    def test_digest_matches_the_validator(self):
        root = EXAMPLES / "teo-memory-agent"
        files = af.check_entries(af.read_folder(str(root)))
        self.assertEqual(af.files_digest(files), v.template_digest(root))


# ---------------------------------------------------------------- new + check

class TestNewAndCheck(Tmp):
    def test_new_passes_check(self):
        code, text = run_cli("new", self.tmp / "my-agent", "--author", "Sam")
        self.assertEqual(code, 0, text)
        code, text = run_cli("check", self.tmp / "my-agent", "--all-files")
        self.assertEqual(code, 0, text)
        self.assertIn("valid template (0 warning(s))", text)

    def test_new_refuses_a_folder_with_files(self):
        (self.tmp / "x").mkdir()
        (self.tmp / "x" / "a").write_text("a")
        self.assertEqual(run_cli("new", self.tmp / "x")[0], 1)

    def test_examples_pass(self):
        for name in ("teo-memory-agent", "invoice-chaser"):
            code, text = run_cli("check", EXAMPLES / name, "--all-files")
            self.assertEqual(code, 0, f"{name}: {text}")
        code, text = run_cli("check", EXAMPLES / "installed-copy")
        self.assertEqual(code, 0, text)
        self.assertIn("valid installed copy", text)

    def test_required_fields(self):
        files = tiny()
        files["agent.yaml"] = "name: tiny\nx-agent8:\n  format: \"0.2\"\n  data: [/memory/]\n"
        self.write_tree(self.tmp, files)
        code, text = run_cli("check", self.tmp, "--all-files")
        self.assertEqual(code, 1)
        self.assertIn("'version' is a required property", text)

    def test_declared_skills_folder_must_exist(self):
        files = tiny()
        del files[".claude/skills/remember/SKILL.md"]
        self.write_tree(self.tmp, files)
        code, text = run_cli("check", self.tmp, "--all-files")
        self.assertEqual(code, 1)
        self.assertIn("layout.skills names .claude/skills/", text)

    def test_secret_file_and_data_refused(self):
        files = tiny()
        files[".env"] = "TOKEN=1\n"
        files["memory/a.md"] = "Sam's notes\n"
        self.write_tree(self.tmp, files)
        code, text = run_cli("check", self.tmp, "--all-files")
        self.assertEqual(code, 1)
        self.assertIn(".env: looks like a secret file", text)
        self.assertIn("memory/a.md: matches the data list", text)

    @unittest.skipUnless(HAS_GIT, "needs git")
    def test_only_what_git_would_commit(self):
        files = tiny()
        files[".gitignore"] = "/memory/\n"
        root = self.repo(files)
        self.write_tree(root, {"memory/a.md": "Sam's notes\n"})       # ignored: fine
        code, text = run_cli("check", root)
        self.assertEqual(code, 0, text)
        self.write_tree(root, {"notes.md": "data, not ignored\n"})     # would be committed
        code, text = run_cli("check", root)
        self.assertEqual(code, 1)
        self.assertIn("notes.md: matches the data list", text)
        self.assertNotIn("memory/a.md", text)

    def test_undeclared_executables_listed(self):
        files = tiny()
        files[".claude/settings.json"] = json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/tools/hook.py\""}]}]}})
        files["tools/hook.py"] = "print(1)\n"
        self.write_tree(self.tmp, files)
        code, text = run_cli("check", self.tmp, "--all-files")
        self.assertEqual(code, 0, text)
        self.assertIn("warning: executable: tools/run.py (undeclared", text)
        self.assertIn("info: runs code: executable: tools/hook.py", text)
        self.assertIn("info: runs code: hook Stop:", text)

    def test_check_refuses_a_newer_major(self):
        self.write_tree(self.tmp, tiny(fmt="1.0"))
        self.assertEqual(run_cli("check", self.tmp, "--all-files")[0], 3)


# ---------------------------------------------------------------- install

@unittest.skipUnless(HAS_GIT, "needs git")
class TestInstall(Tmp):
    def test_install_layout(self):
        files = tiny()
        files[".mcp.json"] = json.dumps({"mcpServers": {"notes": {"command": "python3",
                                                                   "args": ["${CLAUDE_PROJECT_DIR}/tools/run.py"]}}})
        src = self.repo(files)
        dest = self.tmp / "copy"
        code, text = self.install(src, dest)
        self.assertEqual(code, 0, text)
        t = dest / ".agent8/template/1.0.0"
        self.assertTrue((t / "AGENTS.md").is_file())
        self.assertFalse(os.access(t / "AGENTS.md", os.W_OK))
        self.assertEqual(os.stat(t).st_mode & 0o777, 0o555)
        self.assertFalse(os.access(dest / "tools/run.py", os.W_OK))            # mirrored, read-only
        self.assertTrue(os.access(dest / "tools/run.py", os.X_OK))
        self.assertIn("You work for Sam.", (dest / "identity.md").read_text())   # seed with answer
        self.assertTrue((dest / "memory/now.md").is_file())
        self.assertTrue((dest / "LOCAL.md").is_file())
        self.assertTrue((dest / "skills").is_dir())
        for target in (".claude/skills", ".agents/skills"):
            self.assertTrue((dest / target / "remember/SKILL.md").is_file())
        self.assertEqual((dest / "CLAUDE.md").read_text(), "@.agent8/template/1.0.0/AGENTS.md\n@identity.md\n@LOCAL.md\n")
        agents = (dest / "AGENTS.md").read_text()
        self.assertIn("## Identity\n\n# Identity\n\nYou work for Sam.", agents)
        self.assertIn("notes", json.loads((dest / ".mcp.json").read_text())["mcpServers"])
        rep = v.validate_instance(dest)
        self.assertEqual(rep.errors, [])
        self.assertEqual(rep.warnings, [])
        man = v.load_yaml(dest / "agent.yaml", v.Report())
        self.assertEqual(man["extends"], af.source_name(str(src)) + "@1.0.0")

    def test_same_version_twice_gives_the_same_files(self):
        src = self.repo(tiny())
        self.assertEqual(self.install(src, self.tmp / "a")[0], 0)
        self.assertEqual(self.install(src, self.tmp / "b")[0], 0)
        a, b = tree(self.tmp / "a"), tree(self.tmp / "b")
        # only the agent's name differs (taken from the folder)
        a.pop("agent.yaml"), b.pop("agent.yaml")
        self.assertEqual(a, b)

    def test_latest_release_and_exact_version(self):
        src = self.repo(tiny())
        self.release(src, tiny(version="1.1.0"), "v1.1.0")
        self.release(src, tiny(version="2.0.0-rc.1"), "v2.0.0-rc.1")
        self.assertEqual(self.install(src, self.tmp / "a")[0], 0)
        self.assertTrue((self.tmp / "a/.agent8/template/1.1.0").is_dir())
        self.assertEqual(self.install(src, self.tmp / "b", "--version", "1.0.0")[0], 0)
        self.assertTrue((self.tmp / "b/.agent8/template/1.0.0").is_dir())
        code, text = self.install(src, self.tmp / "c", "--version", "9.9.9")
        self.assertEqual(code, 1)
        self.assertIn("no version 9.9.9", text)

    def test_tag_and_manifest_must_agree(self):
        src = self.repo(tiny(version="1.0.1"), tag="v1.0.0")
        code, text = self.install(src, self.tmp / "a")
        self.assertEqual(code, 1)
        self.assertIn("holds version", text)
        self.assertFalse((self.tmp / "a").exists())

    def test_refuses_a_newer_major_before_writing(self):
        src = self.repo(tiny(fmt="1.0"))
        code, text = self.install(src, self.tmp / "a")
        self.assertEqual(code, 3)
        self.assertIn("needs updating", text)
        self.assertFalse((self.tmp / "a").exists())

    def test_refuses_a_link_out_of_a_git_template(self):
        for target in ("../../../etc/passwd", "/etc/passwd"):
            with self.subTest(target=target):
                files = tiny()
                files["tools/out"] = ("link", target)
                src = self.repo(files, name="tpl-" + str(abs(hash(target))))
                code, text = self.install(src, self.tmp / "a")
                self.assertEqual(code, 1, text)
                self.assertIn("link out", text)
                self.assertFalse((self.tmp / "a").exists())

    def test_refuses_a_link_out_of_a_plain_folder(self):
        files = tiny()
        files["tools/out"] = ("link", "../../outside")
        root = self.tmp / "plain"
        self.write_tree(root, files)
        code, text = self.install(root, self.tmp / "a")
        self.assertEqual(code, 1)
        self.assertIn("link out", text)

    def test_plain_folder_installs(self):
        root = self.tmp / "plain"
        self.write_tree(root, tiny())
        code, text = self.install(root, self.tmp / "a")
        self.assertEqual(code, 0, text)
        self.assertEqual(v.validate_instance(self.tmp / "a").errors, [])

    def test_refuses_an_invalid_template(self):
        files = tiny()
        files["memory/sam.md"] = "private\n"
        src = self.repo(files)
        code, text = self.install(src, self.tmp / "a")
        self.assertEqual(code, 1)
        self.assertIn("isn't valid", text)
        self.assertFalse((self.tmp / "a").exists())

    def test_refuses_a_folder_with_files_and_missing_answers(self):
        src = self.repo(tiny())
        (self.tmp / "full").mkdir()
        (self.tmp / "full" / "x").write_text("x")
        self.assertEqual(self.install(src, self.tmp / "full")[0], 1)
        code, text = run_cli("install", src, self.tmp / "b", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("Answer “Your name” first", text)
        self.assertFalse((self.tmp / "b").exists())

    def test_needs_yes_without_a_keyboard(self):
        src = self.repo(tiny())
        code, text = run_cli("install", src, self.tmp / "a", "--answer", "owner_name=Sam")
        self.assertEqual(code, 1)
        self.assertIn("--yes", text)
        self.assertFalse((self.tmp / "a").exists())

    def test_secret_answer_refused(self):
        src = self.repo(tiny())
        code, text = run_cli("install", src, self.tmp / "a", "--yes",
                             "--answer", "owner_name=ghp_" + "a" * 36)
        self.assertEqual(code, 1)
        self.assertIn("looks like a key", text)


# ---------------------------------------------------------------- update

@unittest.skipUnless(HAS_GIT, "needs git")
class TestUpdate(Tmp):
    def setUp(self):
        super().setUp()
        self.src = self.repo(tiny())
        self.dest = self.tmp / "copy"
        code, text = self.install(self.src, self.dest)
        self.assertEqual(code, 0, text)

    def update(self, *extra):
        return run_cli("update", self.dest, "--yes", "--now", "2026-11-08T09:00:00Z", *extra)

    def test_switch_keeps_own_layer_and_data(self):
        (self.dest / "LOCAL.md").write_text("# Local rules\n\nAlways sign as Sam.\n")
        (self.dest / "memory/now.md").write_text("Sam's real memory\n")
        (self.dest / "skills/remember").mkdir(parents=True)
        (self.dest / "skills/remember/SKILL.md").write_text("---\nname: remember\ndescription: Mine.\n---\nMine.\n")
        files = tiny(version="1.1.0", agents="# Tiny v2\n")
        del files["tools/run.py"]
        files["tools/new.py"] = "print('new')\n"
        files["seed/memory/later.md"] = "# Later\n"
        self.release(self.src, files, "v1.1.0", remove=["tools/run.py"])
        code, text = self.update()
        self.assertEqual(code, 0, text)
        self.assertEqual((self.dest / "LOCAL.md").read_text(), "# Local rules\n\nAlways sign as Sam.\n")
        self.assertEqual((self.dest / "memory/now.md").read_text(), "Sam's real memory\n")
        self.assertTrue((self.dest / "memory/later.md").is_file())               # new seed, copied once
        self.assertFalse((self.dest / "tools/run.py").exists())
        self.assertTrue((self.dest / "tools/new.py").is_file())
        self.assertIn("# Tiny v2", (self.dest / "AGENTS.md").read_text())
        self.assertIn("Always sign as Sam.", (self.dest / "AGENTS.md").read_text())
        for target in (".claude/skills", ".agents/skills"):                      # own skill wins
            self.assertIn("Mine.", (self.dest / target / "remember/SKILL.md").read_text())
        rec = v.load_yaml(self.dest / ".agent8/instance.yaml", v.Report())
        self.assertEqual(rec["template"]["version"], "1.1.0")
        self.assertEqual(rec["previous"]["version"], "1.0.0")
        self.assertEqual(rec["installed_at"], NOW)
        self.assertEqual(rec["answers"], {"owner_name": "Sam"})
        rep = v.validate_instance(self.dest)
        self.assertEqual(rep.errors, [])
        # and back
        code, text = self.update("--to", "1.0.0")
        self.assertEqual(code, 0, text)
        self.assertTrue((self.dest / "tools/run.py").is_file())
        self.assertFalse((self.dest / "tools/new.py").exists())
        self.assertEqual((self.dest / "memory/now.md").read_text(), "Sam's real memory\n")
        self.assertEqual(v.validate_instance(self.dest).errors, [])

    def test_dry_run_changes_nothing(self):
        self.release(self.src, tiny(version="1.1.0", agents="# v2\n"), "v1.1.0")
        before = tree(self.dest)
        code, text = run_cli("update", self.dest, "--dry-run")
        self.assertEqual(code, 0, text)
        self.assertIn("Switch from 1.0.0 to 1.1.0", text)
        self.assertEqual(tree(self.dest), before)

    def test_collision_with_the_copys_own_file_is_refused(self):
        (self.dest / "tools/extra.py").write_text("mine\n")
        files = tiny(version="1.1.0")
        files["tools/extra.py"] = "theirs\n"
        self.release(self.src, files, "v1.1.0")
        before = tree(self.dest)
        code, text = self.update()
        self.assertEqual(code, 1)
        self.assertIn("tools/extra.py", text)
        self.assertEqual(tree(self.dest), before)

    def test_new_version_cannot_ship_over_data(self):
        files = tiny(version="1.1.0")
        files["notes.md"] = "theirs\n"
        self.release(self.src, files, "v1.1.0")
        code, text = self.update()
        self.assertEqual(code, 1)       # not a valid template: data in it
        self.assertIn("notes.md", text)

    def test_hand_edit_is_saved(self):
        p = self.dest / "tools/run.py"
        os.chmod(p, 0o755)
        p.write_text("print('edited')\n")
        self.release(self.src, tiny(version="1.1.0"), "v1.1.0")
        code, text = self.update()
        self.assertEqual(code, 0, text)
        saved = list((self.dest / ".agent8/previous").rglob("run.py"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_text(), "print('edited')\n")
        self.assertEqual(p.read_text(), "print('hi')\n")

    def test_runtime_mcp_server_kept(self):
        mcp = self.dest / ".mcp.json"
        mcp.write_text(json.dumps({"mcpServers": {"mine": {"command": "my-server"}}}))
        self.release(self.src, tiny(version="1.1.0"), "v1.1.0")
        code, text = self.update()
        self.assertEqual(code, 0, text)
        self.assertIn("mine", json.loads(mcp.read_text())["mcpServers"])

    def test_new_required_question(self):
        extra = "    - id: city\n      prompt: Your city\n      type: string\n      required: true\n"
        self.release(self.src, tiny(version="1.1.0", extra=extra), "v1.1.0")
        before = tree(self.dest)
        code, text = self.update()
        self.assertEqual(code, 1)
        self.assertIn("Your city", text)
        self.assertEqual(tree(self.dest), before)
        code, text = self.update("--answer", "city=Paris")
        self.assertEqual(code, 0, text)
        rec = v.load_yaml(self.dest / ".agent8/instance.yaml", v.Report())
        self.assertEqual(rec["answers"], {"owner_name": "Sam", "city": "Paris"})

    def test_newer_major_refused_before_writing(self):
        self.release(self.src, tiny(version="2.0.0", fmt="1.0"), "v2.0.0")
        before = tree(self.dest)
        code, text = self.update()
        self.assertEqual(code, 3)
        self.assertIn("needs updating", text)
        self.assertEqual(tree(self.dest), before)

    def test_link_out_in_new_version_refused(self):
        files = tiny(version="1.1.0")
        files["tools/out"] = ("link", "../../../../etc/passwd")
        self.release(self.src, files, "v1.1.0")
        before = tree(self.dest)
        code, text = self.update()
        self.assertEqual(code, 1)
        self.assertIn("link out", text)
        self.assertEqual(tree(self.dest), before)

    def test_bad_version_in_record_refused(self):
        rec = self.dest / ".agent8/instance.yaml"
        rec.write_text(rec.read_text().replace('version: "1.0.0"', 'version: "../../x"', 1))
        self.release(self.src, tiny(version="1.1.0"), "v1.1.0")
        code, text = self.update()
        self.assertEqual(code, 1)
        self.assertIn("doesn't say which version", text)

    def test_template_folder_as_a_link_refused(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep\n")
        t = self.dest / ".agent8/template"
        af.remove_tree(str(t))
        os.symlink(outside, t)
        self.release(self.src, tiny(version="1.1.0"), "v1.1.0")
        code, text = self.update()
        self.assertEqual(code, 1)
        self.assertIn("isn't a real folder", text)
        self.assertTrue((outside / "keep.txt").is_file())

    def test_already_there(self):
        code, text = self.update()
        self.assertEqual(code, 1)
        self.assertIn("already runs 1.0.0", text)


# ---------------------------------------------------------------- agreement with agent8's installer

def load_helper():
    loader = importlib.machinery.SourceFileLoader("agent8_agent_for_spec", str(HELPER))
    spec = importlib.util.spec_from_loader("agent8_agent_for_spec", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@unittest.skipUnless(HELPER.is_file(), "agent8's helper isn't next to the spec")
class TestAgreesWithAgent8(unittest.TestCase):
    """The same template and answers give the same files as agent8's installer, apart from
    what each host adds of its own (its name in a comment, its MCP entries, the source)."""

    def test_same_plan(self):
        a8 = load_helper()
        for name, answers in (("teo-memory-agent", {"owner_name": "Sam", "language": "English",
                                                     "timezone": "Europe/London"}),
                              ("invoice-chaser", {"company_name": "Acme", "tone": "firm",
                                                  "first_reminder_days": 7, "cc_owner": False})):
            with self.subTest(name=name):
                root = EXAMPLES / name
                files = af.check_entries(af.read_folder(str(root)))
                man = af.manifest_of(files)
                setup = (man.get("x-agent8") or {}).get("setup") or []
                self.assertTrue(setup)
                ours = af.install_plan(man, files, answers, "Sam's agent", NOW, "/x", "src")["writes"]
                hfiles = {k: dict(val) for k, val in files.items()}
                theirs = a8.tpl_install_plan({"manifest": man, "version": man["version"],
                                              "template": man["name"], "workspace": "w"},
                                             hfiles, answers, "Sam's agent", NOW, "/x")["writes"]
                # agent8 also approves the MCP servers it composes, in .claude/settings.json
                host_only = {".claude/settings.json"}
                self.assertEqual(sorted(set(ours) - host_only), sorted(set(theirs) - host_only))
                for rel in sorted(set(ours) - host_only):
                    a, b = ours[rel], theirs[rel]
                    self.assertEqual(a["layer"], b["layer"], rel)
                    if rel in ("agent.yaml", ".agent8/instance.yaml"):
                        continue        # they name the source
                    if rel == "AGENTS.md":
                        self.assertEqual(a["data"].split(b"\n", 1)[1], b["data"].split(b"\n", 1)[1])
                        continue
                    self.assertEqual({k: a.get(k) for k in ("kind", "data", "target")},
                                     {k: b.get(k) for k in ("kind", "data", "target")}, rel)
                rec_a = v.yaml.safe_load(ours[".agent8/instance.yaml"]["data"])
                rec_b = v.yaml.safe_load(theirs[".agent8/instance.yaml"]["data"])
                for r in (rec_a, rec_b):
                    r["template"].pop("source")
                self.assertEqual(rec_a, rec_b)


if __name__ == "__main__":
    unittest.main()
