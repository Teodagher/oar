#!/usr/bin/env python3
"""Tests for validate.py. Run: python3 -m unittest discover -s spec/agent-format/tools"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate as v  # noqa: E402

SPEC = Path(__file__).resolve().parent.parent
EXAMPLES = SPEC / "examples"

MINIMAL = """\
name: tiny
version: 1.0.0
description: A tiny agent
x-agent8:
  format: "0.2"
  data:
    - /memory/
"""


def errors_of(rep: v.Report) -> str:
    return "\n".join(rep.errors)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, rel: str, text: str = "x\n") -> Path:
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def template(self, manifest: str = MINIMAL) -> Path:
        self.write("agent.yaml", manifest)
        self.write("AGENTS.md", "# Tiny\n")
        self.write("README.md", "# Tiny\n")
        self.write("LICENSE", "MIT\n")
        return self.dir


class TestExamples(unittest.TestCase):
    def test_examples_are_valid_templates(self):
        for name in ("teo-memory-agent", "invoice-chaser"):
            rep = v.validate_template(EXAMPLES / name)
            self.assertEqual(rep.errors, [], name)
            self.assertEqual(rep.warnings, [], name)

    def test_installed_copy_is_valid(self):
        rep = v.validate_instance(EXAMPLES / "installed-copy")
        self.assertEqual(rep.errors, [])
        self.assertEqual(rep.warnings, [], "digest or own layer drifted; recompute with `validate.py digest`")

    def test_cli_exit_codes(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(v.main(["x", "template", str(EXAMPLES / "invoice-chaser")]), 0)
            self.assertEqual(v.main(["x", "bogus", "."]), 2)


class TestDataList(unittest.TestCase):
    def test_gitignore_semantics(self):
        d = v.DataList(["/memory/", "**/*.log", "/notes/**", "!/notes/README.md"])
        self.assertTrue(d.matches("memory/now.md"))
        self.assertTrue(d.matches("memory", is_dir=True))
        self.assertFalse(d.matches("memory"))  # a file called memory is not the folder
        self.assertFalse(d.matches("src/memory/x.md"))  # anchored
        self.assertTrue(d.matches("a/b/run.log"))
        self.assertTrue(d.matches("notes/a.md"))
        self.assertFalse(d.matches("notes/README.md"))  # re-included: notes/ itself is not excluded

    def test_excluded_parent_cannot_be_reincluded(self):
        d = v.DataList(["/memory/", "!/memory/README.md"])
        self.assertTrue(d.matches("memory/README.md"))

    def test_pattern_rules(self):
        rep = v.Report()
        v.check_data_patterns(["memory/", "/logs/  # logs", "/ok/", " /x/", "#c"], rep)
        text = errors_of(rep)
        self.assertIn("'memory/' is not anchored", text)
        self.assertIn("contains a comment", text)
        self.assertIn("spaces at an end", text)
        self.assertNotIn("'/ok/'", text)


class TestTemplate(Tmp):
    def test_minimal_is_valid(self):
        rep = v.validate_template(self.template())
        self.assertEqual(rep.errors, [])

    def test_data_file_in_template_is_refused(self):
        self.template()
        self.write("memory/now.md")
        self.assertIn("matches the data list", errors_of(v.validate_template(self.dir)))

    def test_seed_must_be_data_or_own_layer(self):
        self.template()
        self.write("seed/memory/now.md")
        self.write("seed/identity.md")
        self.assertEqual(v.validate_template(self.dir).errors, [])
        self.write("seed/tools/x.py")
        self.assertIn("not in the data list", errors_of(v.validate_template(self.dir)))

    def test_answer_placeholder_must_name_a_question(self):
        self.template(MINIMAL + "  setup:\n    - {id: owner, prompt: Name, type: string}\n")
        self.write("seed/identity.md", "{{answer:owner}} {{answer:ghost}}\n")
        text = errors_of(v.validate_template(self.dir))
        self.assertIn("answer:ghost", text)
        self.assertNotIn("answer:owner", text)

    def test_own_layer_names_refused(self):
        self.template()
        self.write("identity.md")
        self.write(".agent8/instance.yaml")
        text = errors_of(v.validate_template(self.dir))
        self.assertIn("identity.md: belongs to a copy", text)
        self.assertIn(".agent8/", text)

    def test_claude_md_must_import_agents_md(self):
        self.template()
        self.write("CLAUDE.md", "# My instructions\n")
        self.assertIn("CLAUDE.md must be", errors_of(v.validate_template(self.dir)))
        self.write("CLAUDE.md", "@AGENTS.md\n@identity.md\n")
        self.assertEqual(v.validate_template(self.dir).errors, [])

    def test_extends_refused_in_template(self):
        self.template(MINIMAL.replace("description:", "extends: https://x/y@1.0.0\ndescription:"))
        self.assertIn("cannot use `extends`", errors_of(v.validate_template(self.dir)))

    def test_secret_files_and_values_refused(self):
        self.template()
        self.write(".env", "A=1\n")
        self.write("notes.txt", "key sk_live_" + "a" * 24 + "\n")
        text = errors_of(v.validate_template(self.dir))
        self.assertIn(".env: looks like a secret file", text)
        self.assertIn("notes.txt: contains what looks like a secret value", text)

    def test_vault_placeholders(self):
        self.template(MINIMAL + """\
  secrets:
    - item: Stripe
      description: billing
      fields: [secret_key]
      env:
        STRIPE_KEY: "{{vault:Stripe.secret_key}}"
        OTHER: "{{vault:Ghost}}"
        BADFIELD: "{{vault:Stripe.nope}}"
""")
        text = errors_of(v.validate_template(self.dir))
        self.assertIn("undeclared vault item 'Ghost'", text)
        self.assertIn("field 'nope'", text)
        self.assertNotIn("STRIPE_KEY", text)

    def test_secret_file_target_must_stay_inside(self):
        for bad in ("../outside.json", "/etc/token", "~/.config/x.json", ".agent8/t.json", ".mcp.json",
                    "./.agent8/instance.yaml", ".claude/settings.local.json", "skills/evil/SKILL.md",
                    ".git/config", "t.json", "a//b.json"):
            with self.subTest(bad=bad):
                self.template(MINIMAL + f"""\
  secrets:
    - item: G
      description: mail
      files:
        - path: "{bad}"
          template: t.json
""")
                self.write("t.json", "{{vault:G}}")
                rep = v.validate_template(self.dir)
                self.assertTrue(any("file target" in e or "files/0/path" in e for e in rep.errors), bad)

    def test_good_secret_file_target(self):
        self.template(MINIMAL + """\
  secrets:
    - item: G
      description: mail
      files:
        - path: .secrets/token.json
          template: t.json
          agent_writes: true
""")
        self.write("t.json", "{{vault:G}}")
        self.assertEqual(v.validate_template(self.dir).errors, [])

    def test_secret_env_with_text_and_plain_env(self):
        self.template(MINIMAL + """\
  setup:
    - {id: lang, prompt: Language, type: string}
  env:
    CONFIG_DIR: "{{folder}}/.secrets"
    LANG_PREF: "{{answer:lang}}"
    BAD_ANSWER: "{{answer:ghost}}"
    LEAK: "{{vault:Api.token}}"
  secrets:
    - item: Api
      description: api
      env:
        AUTH_HEADER: "Bearer {{vault:Api.token}}"
        PLAIN: "no placeholder"
""")
        self.write(".mcp.json", '{"mcpServers": {"a": {"command": "npx", "env": {"D": "${CONFIG_DIR}", "H": "${AUTH_HEADER}"}}}}')
        text = errors_of(v.validate_template(self.dir))
        self.assertIn("answer:ghost", text)
        self.assertIn("LEAK", text)
        self.assertIn("PLAIN", text)
        self.assertNotIn("AUTH_HEADER", text)
        self.assertNotIn("CONFIG_DIR", text)

    def test_repos(self):
        self.template(MINIMAL + """\
  repos:
    - {path: memory/brain, url: https://example.com/brain}
    - {path: code, url: https://example.com/code}
""")
        text = errors_of(v.validate_template(self.dir))
        self.assertIn("repos 'code': must match the data list", text)
        self.assertNotIn("memory/brain", text)

    def test_nested_git_and_absolute_symlink(self):
        self.template()
        self.write("vendor/x/.git/HEAD", "ref\n")
        self.write("docs/a.md")
        os.symlink(str(self.dir / "docs/a.md"), self.dir / "abs-link")
        text = errors_of(v.validate_template(self.dir))
        self.assertIn("nested git repository", text)
        self.assertIn("symlink is absolute", text)

    def test_absolute_paths_in_hooks_and_mcp(self):
        self.template()
        self.write(".claude/settings.json", '{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 /home/teo/agent/tools/x.py"}]}]}}')
        self.write(".mcp.json", '{"mcpServers": {"a": {"command": "/usr/local/bin/srv"}}}')
        text = errors_of(v.validate_template(self.dir))
        self.assertIn("hook Stop: absolute path", text)
        self.assertIn("a.command: absolute path", text)

    def test_skills_layout_detected(self):
        self.template()
        self.write(".claude/skills/x/SKILL.md", "---\nname: y\ndescription: d\n---\n")
        self.assertIn("frontmatter name 'y'", errors_of(v.validate_template(self.dir)))

    def test_mcp_rules(self):
        self.template(MINIMAL + """\
  secrets:
    - item: S
      description: s
      env:
        S_KEY: "{{vault:S}}"
""")
        self.write(".mcp.json", '{"mcpServers": {"a": {"command": "x", "args": ["--key", "${S_KEY}"]},'
                                ' "b": {"command": "y", "env": {"K": "${UNDECLARED}"}},'
                                ' "c": {"command": "z", "env": {"K": "${S_KEY}"}}}}')
        text = errors_of(v.validate_template(self.dir))
        self.assertIn("a.args: a secret's ${NAME} must not appear", text)
        self.assertIn("${UNDECLARED}", text)
        self.assertNotIn(".mcp.json c", text)

    def test_skill_frontmatter(self):
        self.template()
        self.write("skills/good/SKILL.md", "---\nname: good\ndescription: does good\n---\n")
        self.write("skills/bad/SKILL.md", "---\nname: other\n---\n")
        text = errors_of(v.validate_template(self.dir))
        self.assertIn("frontmatter name 'other'", text)
        self.assertIn("needs a description", text)
        self.assertNotIn("skills/good", text)

    def test_skills_folder_collision_with_own_layer(self):
        self.template(MINIMAL + "  layout:\n    skills: .claude/skills\n")
        self.write("skills/x/SKILL.md", "---\nname: x\ndescription: d\n---\n")
        self.assertIn("collides with the copy's own skills", errors_of(v.validate_template(self.dir)))

    def test_symlink_outside_refused(self):
        self.template()
        os.symlink("/etc/passwd", self.dir / "leak")
        self.assertIn("symlink points outside", errors_of(v.validate_template(self.dir)))

    def test_newer_major_refused_cleanly(self):
        self.template(MINIMAL.replace('"0.2"', '"1.0"'))
        with self.assertRaises(v.FormatTooNew) as ctx:
            v.validate_template(self.dir)
        self.assertIn("needs format 1.0", str(ctx.exception))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(v.main(["x", "template", str(self.dir)]), 3)

    def test_newer_minor_is_additive(self):
        self.template(MINIMAL.replace('"0.2"', '"0.3"') + "  schedules:\n    - daily\n")
        rep = v.validate_template(self.dir)
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("schedules" in i and "ignored" in i for i in rep.infos))

    def test_older_minor_read(self):
        self.template(MINIMAL.replace('"0.2"', '"0.1"'))
        self.assertEqual(v.validate_template(self.dir).errors, [])

    def test_placeholders_anywhere_but_declared(self):
        self.template(MINIMAL + """\
  secrets:
    - item: Company card
      description: pays for things
      fields: [number]
""")
        self.write("skills/pay/SKILL.md", "---\nname: pay\ndescription: pay\n---\nUse {{vault:Company card.number}} and {{vault:Unknown thing}}.\n")
        self.write(".mcp.json", '{"mcpServers": {"a": {"type": "http", "url": "https://x.example", "headers": {"Authorization": "Bearer {{vault:Company card}}"}}}}')
        text = errors_of(v.validate_template(self.dir))
        self.assertIn("'Unknown thing'", text)
        self.assertNotIn("Company card", text)

    def test_plain_opengap_repo(self):
        self.write("agent.yaml", "name: og\nversion: 0.1.0\ndescription: d\n")
        self.write("SOUL.md", "I am og.\n")
        rep = v.validate_template(self.dir)
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("plain OpenGAP" in w for w in rep.warnings))
        self.assertTrue(any("/memory/" in i for i in rep.infos))


class TestInstance(Tmp):
    def make_copy(self) -> Path:
        tdir = self.dir / ".agent8/template/0.2.0"
        shutil.copytree(EXAMPLES / "teo-memory-agent", tdir)
        for name in ("agent.yaml", "identity.md", "LOCAL.md"):
            shutil.copy(EXAMPLES / "installed-copy" / name, self.dir / name)
        shutil.copy(EXAMPLES / "installed-copy/.agent8/instance.yaml", self.dir / ".agent8/instance.yaml")
        return self.dir

    def record(self) -> Path:
        return self.dir / ".agent8/instance.yaml"

    def test_copy_is_valid(self):
        self.assertEqual(v.validate_instance(self.make_copy()).errors, [])

    def test_extends_must_match_record(self):
        self.make_copy()
        p = self.dir / "agent.yaml"
        p.write_text(p.read_text().replace("@0.2.0", "@0.3.0"))
        text = errors_of(v.validate_instance(self.dir))
        self.assertIn("extends", text)

    def test_hand_edit_in_template_warns(self):
        self.make_copy()
        (self.dir / ".agent8/template/0.2.0/AGENTS.md").write_text("edited\n")
        rep = v.validate_instance(self.dir)
        self.assertTrue(any("digest differs" in w for w in rep.warnings))

    def test_answers_checked(self):
        self.make_copy()
        r = self.record()
        r.write_text(r.read_text().replace("  owner_name: Sam\n", "  later_question: kept\n").replace("timezone: Europe/London", "timezone: 42"))
        text = errors_of(v.validate_instance(self.dir))
        self.assertNotIn("later_question", text)  # kept for a rollback, not an error
        self.assertIn("required setup question 'owner_name'", text)
        self.assertIn("answer 'timezone' does not fit", text)

    def test_copy_cannot_change_setup(self):
        self.make_copy()
        p = self.dir / "agent.yaml"
        p.write_text(p.read_text() + "  setup:\n    - {id: x, prompt: y, type: string}\n")
        self.assertIn("cannot change `setup`", errors_of(v.validate_instance(self.dir)))

    def test_secret_value_in_record_refused(self):
        self.make_copy()
        r = self.record()
        r.write_text(r.read_text().replace("owner_name: Sam", "owner_name: ghp_" + "a" * 36))
        self.assertIn("looks like a secret value", errors_of(v.validate_instance(self.dir)))

    def test_newer_record_format_refused(self):
        self.make_copy()
        r = self.record()
        r.write_text(r.read_text().replace('format: "0.2"', 'format: "1.0"'))
        with self.assertRaises(v.FormatTooNew):
            v.validate_instance(self.dir)

    def test_extends_parsing(self):
        self.assertEqual(v.parse_extends("git@github.com:o/r@1.2.3"), ("git@github.com:o/r", "1.2.3"))
        self.assertEqual(v.parse_extends("agent8:ws/t@0.1.0-beta.1"), ("agent8:ws/t", "0.1.0-beta.1"))
        self.assertIsNone(v.parse_extends("https://x/y@^1.0.0"))
        self.assertIsNone(v.parse_extends("https://x/y"))


if __name__ == "__main__":
    unittest.main()
