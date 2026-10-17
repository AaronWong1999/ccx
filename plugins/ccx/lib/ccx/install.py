"""Install, update, check and remove ccx, using the CLIs bundled inside the
Claude and Codex desktop apps (no separate CLI installs needed)."""

from __future__ import annotations

import hashlib
import json
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from . import __version__, claude, codex, pairs, presence, repairs
from .common import HOME, STATE_DIR, proxy_env

REPO = "aaronwong1999/ccx"
REPO_URL = f"https://github.com/{REPO}"
SRC = Path(__file__).resolve().parents[4]          # repo root: plugins/ccx/lib/ccx/install.py
PLUGIN_BIN = SRC / "plugins/ccx/bin"
APP = HOME / "Applications/ccx.app"
LINK = HOME / ".local/bin/ccx"
AGENT_LABEL = "io.github.aaronwong1999.ccx"
AGENT = HOME / f"Library/LaunchAgents/{AGENT_LABEL}.plist"
LEGACY = "claudecodex"


def run(cmd: List[str], timeout: int = 300) -> Tuple[int, str]:
    # git talks to GitHub: give it the system proxy (the menu bar app has no shell env).
    env = proxy_env() if cmd and cmd[0] == "git" else None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def say(ok: bool, text: str, quiet: bool = False):
    if not quiet or not ok:
        print(("✓ " if ok else "✗ ") + text)


def is_dev_checkout() -> bool:
    return not str(SRC).startswith(str(HOME / "Library/Application Support/ccx"))


def marketplace_source(dev: bool) -> str:
    """Always this local copy: the apps install from disk (no GitHub access of their
    own needed), and `ccx update` refreshes this copy and then both apps."""
    return str(SRC)


def repo_version() -> str:
    """Version of the plugin in this checkout (what the apps should end up with)."""
    try:
        return json.loads((SRC / "plugins/ccx/.claude-plugin/plugin.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return __version__


def _vt(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


# ------------------------------------------------------------------ plugins

def _registered(tool: str) -> str:
    """How the app has the ccx marketplace registered (raw text, '' if not)."""
    try:
        if tool == "claude":
            return json.dumps(json.loads((HOME / ".claude/plugins/known_marketplaces.json").read_text()).get("ccx") or "")
        text = (codex.CODEX_HOME / "config.toml").read_text()
        m = re.search(r"^\[marketplaces\.ccx\]\n(.*?)(?=^\[|\Z)", text, re.M | re.S)
        return m.group(1) if m else ""
    except (OSError, ValueError, AttributeError):
        return ""


def _add_marketplace(cli: str, tool: str, source: str):
    """Register ccx's marketplace at `source`, replacing a registration elsewhere
    (e.g. GitHub, from older versions)."""
    have = _registered(tool)
    if have and source not in have:
        run([cli, "plugin", "marketplace", "remove", "ccx"])
    run([cli, "plugin", "marketplace", "add", source])

def _claude_installed(cli: str, plugin_id: str = presence.OURS) -> Optional[str]:
    _, out = run([cli, "plugin", "list"])
    m = re.search(re.escape(plugin_id) + r"\s*\n\s*Version:\s*(\S+)", out)
    return m.group(1) if m else None


CLAUDE_APPS = ("/Applications/Claude.app", str(HOME / "Applications/Claude.app"))


def claude_app() -> bool:
    return any(Path(a).exists() for a in CLAUDE_APPS)


def needs_setup() -> List[str]:
    """Apps that are here now but don't have ccx yet (installed after ccx was)."""
    out = []
    if claude.desktop_cli() and not presence.claude_copies():
        out.append("claude")
    try:
        codex.codex_bin()
        if not presence.codex_copies():
            out.append("codex")
    except RuntimeError:
        pass
    return out


def setup_claude(source: str, quiet: bool = False) -> bool:
    cli = claude.desktop_cli()
    if not cli:
        say(False, "Claude: the desktop app is installed, but Claude Code isn't downloaded yet. Open Claude and click "
                   "Code once; ccx then finishes setup by itself (or run `ccx setup`)." if claude_app()
            else "Claude: desktop app not installed (https://claude.com/download); skipping", quiet)
        return False
    run([cli, "plugin", "uninstall", f"{LEGACY}@{LEGACY}"])
    run([cli, "plugin", "marketplace", "remove", LEGACY])
    other = next((c for c in presence.claude_copies() if c != presence.OURS), None)
    if other:
        # Installed from a plugin directory: keep that one (it updates from the
        # directory, which tracks our release tags) and never run a second copy.
        if presence.OURS in presence.claude_copies():
            run([cli, "plugin", "uninstall", presence.OURS])
        run([cli, "plugin", "marketplace", "remove", "ccx"])
        say(True, f"Claude: using ccx {_claude_installed(cli, other) or ''} from the plugin directory ({other}); "
                  "no second copy installed", quiet)
        return True
    _add_marketplace(cli, "claude", source)
    run([cli, "plugin", "marketplace", "update", "ccx"])
    run([cli, "plugin", "install", "ccx@ccx"])
    run([cli, "plugin", "update", "ccx@ccx"])
    want = repo_version()
    if _claude_installed(cli) != want:  # `plugin update` only moves forward; force any change
        run([cli, "plugin", "uninstall", "ccx@ccx"])
        run([cli, "plugin", "install", "ccx@ccx"])
    got = _claude_installed(cli)
    ok = got is not None
    say(ok, f"Claude plugin ccx {got} installed (new conversations pick it up)" if ok
        else "Claude plugin install failed: run `ccx doctor`", quiet)
    return ok


def setup_codex(source: str, quiet: bool = False) -> bool:
    try:
        cli = codex.codex_bin()
    except RuntimeError:
        say(False, "Codex: desktop app not installed (https://openai.com/codex); skipping", quiet)
        return False
    run([cli, "plugin", "remove", f"{LEGACY}@{LEGACY}"])
    run([cli, "plugin", "marketplace", "remove", LEGACY])
    other = next((c for c in presence.codex_copies() if c != presence.OURS), None)
    if other:
        if presence.OURS in presence.codex_copies():
            run([cli, "plugin", "remove", presence.OURS])
        run([cli, "plugin", "marketplace", "remove", "ccx"])
        try:
            codex.trust_hooks()
        except Exception:
            pass
        say(True, f"Codex: using ccx from the plugin directory ({other}); no second copy installed", quiet)
        return True
    _add_marketplace(cli, "codex", source)
    run([cli, "plugin", "marketplace", "upgrade", "ccx"])
    code, out = run([cli, "plugin", "add", "ccx@ccx"])
    ok = code == 0
    say(ok, "Codex plugin ccx installed (new threads pick it up)" if ok
        else f"Codex plugin install failed: {out[-300:]} (run `ccx doctor`, then `ccx setup` to retry)", quiet)
    if ok:
        # Installing ccx is the user's consent to its own sync hook; Codex otherwise
        # asks for each third-party hook to be trusted by hand (and again after updates).
        try:
            codex.trust_hooks()
            say(True, "Codex trusts ccx's sync hook", quiet)
        except Exception as e:
            say(False, f"could not trust ccx's hook in Codex: {e} (Codex → Settings → Hooks)", quiet)
    return ok


# ------------------------------------------------------------------ menu bar

def _swift_hash() -> str:
    return hashlib.sha256((SRC / "menubar/main.swift").read_bytes() + __version__.encode()).hexdigest()[:16]


def build_menubar(quiet: bool = False, force: bool = False) -> bool:
    stamp = STATE_DIR / "menubar.hash"
    if not force and APP.exists() and stamp.exists() and stamp.read_text() == _swift_hash():
        return True
    if not shutil.which("swiftc"):
        say(False, "no swiftc (run xcode-select --install); skipping the menu bar icon", quiet)
        return False
    code, out = run(["/bin/sh", str(SRC / "menubar/build.sh"), str(APP), str(PLUGIN_BIN / "ccx"), __version__], 600)
    if code:
        say(False, f"menu bar icon build failed: {out[-300:]}", quiet)
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    stamp.write_text(_swift_hash())
    restart_menubar()
    say(True, f"menu bar icon ready ({APP})", quiet)
    return True


def menubar_running() -> bool:
    # -a: also match our own ancestors (this may run as a child of the menu bar app).
    return run(["pgrep", "-a", "-x", "ccx"])[0] == 0


def restart_menubar():
    """Replace the running menu bar app with the freshly built one (even when this
    update was started by that very app, which is our ancestor then)."""
    run(["pkill", "-a", "-x", "ccx"])
    for _ in range(30):
        if not menubar_running():
            break
        time.sleep(0.1)
    run(["open", str(APP)])


def autostart(on: Optional[bool]) -> bool:
    """Start the menu bar app at login (a LaunchAgent). None = just report."""
    if on is None:
        return AGENT.exists()
    if on:
        AGENT.parent.mkdir(parents=True, exist_ok=True)
        with open(AGENT, "wb") as f:
            plistlib.dump({"Label": AGENT_LABEL, "ProgramArguments": ["/usr/bin/open", "-a", str(APP)],
                           "RunAtLoad": True}, f)
    else:
        AGENT.unlink(missing_ok=True)
    return on


# ------------------------------------------------------------------ releases

def latest_release() -> Optional[str]:
    """Newest vX.Y.Z tag on GitHub (works for the private repo with git credentials)."""
    code, out = run(["git", "ls-remote", "--tags", "--refs", f"{REPO_URL}.git", "refs/tags/v*"], 30)
    if code:
        return None
    tags = re.findall(r"refs/tags/v(\d+\.\d+\.\d+)$", out, re.M)
    return max(tags, key=_vt) if tags else None


def latest_local_tag() -> Optional[str]:
    _, out = run(["git", "-C", str(SRC), "tag", "-l", "v*"])
    tags = [t[1:] for t in out.split() if re.fullmatch(r"v\d+\.\d+\.\d+", t)]
    return max(tags, key=_vt) if tags else None


def check() -> dict:
    latest = latest_release()
    return {"current": __version__, "latest": latest,
            "available": bool(latest and _vt(latest) > _vt(__version__)), "url": f"{REPO_URL}/releases"}


# ------------------------------------------------------------------ commands

def setup(dev: bool = False, quiet: bool = False) -> int:
    if sys.version_info < (3, 9):
        print("✗ ccx needs Python 3.9+")
        return 1
    dev = dev or is_dev_checkout()
    source = marketplace_source(dev)
    if not quiet:
        print(f"ccx - claudecodex {__version__} · plugin source: {source}")
    ok_claude = setup_claude(source, quiet)
    ok_codex = setup_codex(source, quiet)
    LINK.parent.mkdir(parents=True, exist_ok=True)
    if LINK.is_symlink() or LINK.exists():
        LINK.unlink()
    LINK.symlink_to(PLUGIN_BIN / "ccx")
    say(True, f"`ccx` command → {LINK}", quiet)
    run(["pkill", "-a", "-x", "ClaudeCodex"])  # the pre-rename menu bar app
    shutil.rmtree(HOME / "Applications/ClaudeCodex.app", ignore_errors=True)
    if build_menubar(quiet, force=True) and not AGENT.exists():
        autostart(True)
    if not quiet:
        if ok_claude and ok_codex:
            print("\nDone. ccx is set up in both apps. Start a new conversation (or keep using an existing one) "
                  "and click ⇄ in the menu bar to move a conversation to the other app, or say "
                  "“continue the <name> session from Codex/Claude”.")
        elif ok_claude or ok_codex:
            print(f"\nccx is set up in {'Claude' if ok_claude else 'Codex'}. Install the "
                  f"{'Codex' if ok_claude else 'Claude'} desktop app too: ccx finishes setting it up by itself.")
        else:
            print("\nccx is installed, but neither app could be set up yet (see above). `ccx doctor` shows what's missing.")
        print(f"Like it? Star it: {REPO_URL} · follow the author for updates: https://x.com/aaron0x10")
    return 0 if (ok_claude or ok_codex) else 1


def update(quiet: bool = False) -> int:
    """Move to the newest release tag (vX.Y.Z). Commits on main that aren't tagged
    are never installed, so they never reach users or trigger update notices."""
    if (SRC / ".git").exists() and not is_dev_checkout():
        code, out = run(["git", "-C", str(SRC), "fetch", "--quiet", "--force", "--tags", "origin"])
        latest = None if code else latest_local_tag()
        if latest:
            code, out = run(["git", "-C", str(SRC), "checkout", "--quiet", "--force", f"v{latest}"])
        if code or not latest:
            say(False, f"could not download the update: {(out or 'no release found')[-300:]}", quiet)
            return 1
    # Re-run the (possibly new) code to refresh both apps' plugins and the menu bar.
    code, out = run([str(PLUGIN_BIN / "ccx"), "_refresh"] + (["--quiet"] if quiet else []), 900)
    if out:
        print(out)
    return code


def refresh(quiet: bool = False) -> int:
    source = marketplace_source(is_dev_checkout())
    setup_claude(source, quiet)
    setup_codex(source, quiet)
    build_menubar(quiet)
    say(True, f"ccx is up to date: {__version__}", quiet)
    return 0


def doctor() -> int:
    rows = [(sys.version_info >= (3, 9), f"Python {sys.version.split()[0]} ({sys.executable})")]
    cli = claude.desktop_cli()
    rows.append((bool(cli), f"Claude Code: {cli}" if cli else "Claude Code: " + (
        "open Claude and click Code once" if claude_app() else "Claude desktop app not installed")))
    if cli:
        copies = presence.claude_copies()
        v = _claude_installed(cli, copies[0]) if copies else None
        rows.append((len(copies) == 1, f"Claude plugin: ccx {v} ({copies[0]})" if len(copies) == 1 else
                     f"Claude plugin: {len(copies)} copies {copies} (run `ccx setup` to keep one)" if copies
                     else "Claude plugin: not installed (run `ccx setup`)"))
    try:
        rows.append((True, f"Codex: {codex.codex_bin()}"))
        trusted = codex.hooks_trusted()
        rows.append((trusted is not None, "Codex plugin: " + ("installed" if trusted is not None else "not installed (run `ccx setup`)")))
        if trusted is not None:
            rows.append((bool(trusted), "Codex sync hook: " + ("trusted" if trusted else "not trusted (run `ccx setup`)")))
    except RuntimeError as e:
        rows.append((False, str(e)))
    running = menubar_running()
    rows.append((running, "Menu bar icon: " + ("running" if running else "not running (open ~/Applications/ccx.app)")))
    rows.append((True, "Start at login: " + ("on" if autostart(None) else "off")))
    c = check()
    rows.append((not c["available"], f"Version: {__version__}" + (f" (update available: {c['latest']})" if c["available"] else "")))
    rows.append((True, f"Linked sessions: {len(pairs.load())} · state in {STATE_DIR}"))
    queued = repairs.pending()
    if queued:
        rows.append((False, f"History repair queued for {len(queued)} Codex thread(s): quit Codex when convenient; "
                     "ccx retries after the writer is released."))
    for ok, text in rows:
        say(ok, text)
    return 0 if all(ok for ok, _ in rows[:2]) else 1


def uninstall(purge: bool = False) -> int:
    cli = claude.desktop_cli()
    if cli:
        run([cli, "plugin", "uninstall", "ccx@ccx"])
        run([cli, "plugin", "marketplace", "remove", "ccx"])
    try:
        cb = codex.codex_bin()
        run([cb, "plugin", "remove", "ccx@ccx"])
        run([cb, "plugin", "marketplace", "remove", "ccx"])
    except RuntimeError:
        pass
    autostart(False)
    run(["pkill", "-a", "-x", "ccx"])
    shutil.rmtree(APP, ignore_errors=True)
    if LINK.is_symlink():
        LINK.unlink()
    if purge:
        shutil.rmtree(STATE_DIR, ignore_errors=True)
    print("✓ Removed the plugins, the menu bar icon and the `ccx` command" +
          (", and the link records." if purge else " (link records kept in ~/.ccx)."))
    return 0
