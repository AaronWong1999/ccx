"""Exercise the pasted installer with isolated HOME and fake external commands."""
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest import mock

import test_ccx  # initializes isolated CCX_HOME and imports the checkout
from ccx import install

ROOT = Path(__file__).resolve().parents[1]


class InstallerFlows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ccx-install-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.home / "Applications/Claude.app").mkdir(parents=True)
        self.dest = self.home / "Library/Application Support/ccx/src"
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                        SHELL="/bin/sh", https_proxy="http://unused.invalid:1", TEST_TAGS="v0.1.1\nv0.0.41")
        for name, text in {"uname": "echo Darwin", "sw_vers": "echo 15.0", "xcode-select": "exit 0"}.items():
            self.script(name, text)
        self.script("git", '''
echo "$*" >> "$HOME/git.log"
if [ "$1" = clone ]; then
  for dest do :; done
  mkdir -p "$dest/.git" "$dest/plugins/ccx/bin"
  cat > "$dest/plugins/ccx/bin/ccx" <<'INNER'
#!/bin/sh
echo "$*" >> "$HOME/setup.log"
exit "${TEST_SETUP_EXIT:-0}"
INNER
  chmod +x "$dest/plugins/ccx/bin/ccx"
  exit 0
fi
case "$3" in
 fetch) exit "${TEST_FETCH_EXIT:-0}" ;;
 tag) printf '%s\\n' "$TEST_TAGS" ;;
 checkout) exit "${TEST_CHECKOUT_EXIT:-0}" ;;
esac
''')
        # Redirect only OS dependency detection; the install body runs unchanged.
        self.source = (ROOT / "install.sh").read_text().replace('"/Applications/$1.app"', '"$HOME/system-apps/$1.app"')
        self.source = self.source.replace('/usr/bin/xcode-select', str(self.bin / 'xcode-select'))

    def script(self, name, body):
        p = self.bin / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)

    def run_installer(self):
        return subprocess.run(["/bin/sh"], input=self.source, env=self.env, text=True, capture_output=True, timeout=20)

    def test_fresh_pasted_install_runs_setup_from_release(self):
        r = self.run_installer()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("checkout --quiet --force v0.1.1", (self.home / "git.log").read_text())
        self.assertEqual((self.home / "setup.log").read_text().splitlines(), ["setup"])

    def test_repeat_install_keeps_existing_state_and_uses_fetch(self):
        self.assertEqual(self.run_installer().returncode, 0)
        state = self.home / ".ccx/pairs.json"
        state.parent.mkdir()
        state.write_text('[{"old-link":"keep"}]')
        r = self.run_installer()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(state.read_text(), '[{"old-link":"keep"}]')
        log = (self.home / "git.log").read_text()
        self.assertEqual(log.count("clone --quiet"), 1)
        self.assertIn("fetch --quiet --force --tags origin", log)

    def test_installer_excludes_prerelease_and_non_version_tags(self):
        self.env["TEST_TAGS"] = "v999.0.0-beta\nv2\nv0.1.1\nv0.0.41"
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertIn("checkout --quiet --force v0.1.1", (self.home / "git.log").read_text())

    def test_failed_fetch_does_not_checkout_or_run_setup(self):
        self.assertEqual(self.run_installer().returncode, 0)
        (self.home / "git.log").write_text("")
        (self.home / "setup.log").unlink()
        self.env["TEST_FETCH_EXIT"] = "1"
        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertNotIn("checkout", (self.home / "git.log").read_text())
        self.assertFalse((self.home / "setup.log").exists())

    def test_no_stable_release_stops_before_setup(self):
        self.env["TEST_TAGS"] = "v9.0.0-beta"
        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertFalse((self.home / "setup.log").exists())

    def test_setup_failure_reaches_the_calling_shell(self):
        self.env["TEST_SETUP_EXIT"] = "1"
        self.assertNotEqual(self.run_installer().returncode, 0)

    def test_identical_menu_install_reuses_existing_signed_app(self):
        app = self.home / "Applications/ccx.app"
        app.mkdir()
        state = self.home / ".ccx"
        state.mkdir()
        (state / "menubar.hash").write_text("same")
        with mock.patch.object(install, "APP", app), mock.patch.object(install, "STATE_DIR", state), \
             mock.patch.object(install, "_swift_hash", return_value="same"), mock.patch.object(install, "run") as run:
            self.assertTrue(install.build_menubar())
        run.assert_not_called()  # no compiler, signing or restart: preserve this app identity

    def test_failed_compile_keeps_installed_app(self):
        app = self.home / "Applications/ccx.app"
        app.mkdir()
        (app / "old-binary").write_text("keep")
        self.script("swiftc", "exit 1")
        r = subprocess.run(["/bin/sh", str(ROOT / "menubar/build.sh"), str(app), "/tmp/ccx", "test"],
                           env=self.env, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((app / "old-binary").read_text(), "keep")
        self.assertFalse(list(app.parent.glob(".ccx-build.*")))

    def test_failed_final_rename_restores_installed_app(self):
        app = self.home / "Applications/ccx.app"
        app.mkdir()
        (app / "old-binary").write_text("keep")
        self.script("swiftc", 'while [ "$1" != "-o" ]; do shift; done; shift; touch "$1"')
        self.script("codesign", "exit 0")
        self.script("mv", 'case "$1" in */.ccx-build.*/ccx.app) exit 1;; esac; exec /bin/mv "$@"')
        r = subprocess.run(["/bin/sh", str(ROOT / "menubar/build.sh"), str(app), "/tmp/ccx", "test"],
                           env=self.env, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((app / "old-binary").read_text(), "keep")
        self.assertFalse(list(app.parent.glob(".ccx-build.*")))


class UpdateOutcomes(unittest.TestCase):
    def refresh(self, fail=None, missing=False):
        with ExitStack() as stack:
            for name in ("setup_claude", "setup_codex", "setup_antigravity", "build_menubar"):
                stack.enter_context(mock.patch.object(install, name, return_value=name != fail))
            stack.enter_context(mock.patch.object(install.claude, "desktop_cli", return_value=None if missing else "/claude"))
            stack.enter_context(mock.patch.object(install.codex, "codex_bin", side_effect=RuntimeError("missing") if missing else None,
                                                  return_value="/codex"))
            stack.enter_context(mock.patch.object(install.antigravity, "installed", return_value=not missing))
            with redirect_stdout(io.StringIO()) as output:
                code = install.refresh()
            return code, output.getvalue()

    def test_plugin_or_menu_failure_never_announces_success(self):
        for fail in ("setup_claude", "setup_codex", "setup_antigravity", "build_menubar"):
            with self.subTest(fail=fail):
                code, output = self.refresh(fail)
                self.assertEqual(code, 1)
                self.assertNotIn("is up to date", output)
                self.assertIn("ccx setup", output)

    def test_missing_optional_apps_do_not_break_update(self):
        self.assertEqual(self.refresh("setup_claude", missing=True)[0], 0)

    def test_success_announces_success(self):
        code, output = self.refresh()
        self.assertEqual(code, 0)
        self.assertIn("is up to date", output)
