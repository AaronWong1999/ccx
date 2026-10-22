"""Which parts of ccx are on this Mac.

ccx can arrive two ways: the install script (plugins in both apps from the
local copy under the marketplace name "ccx", plus the menu bar app and the
`ccx` command), or just the plugin, installed from an app's plugin directory
under that directory's marketplace name. Exactly one copy may run per app, and
a plugin-only install points people to the rest.
"""

from __future__ import annotations

import json
import re
import time
from typing import List

from .common import HOME, L, STATE_DIR

OURS = "ccx@ccx"                       # installed by the install script
REPO_URL = "https://github.com/aaronwong1999/ccx"
INSTALL_GUIDE = REPO_URL + "#install--安装"
MENU_APP = HOME / "Applications/ccx.app"
NUDGE = STATE_DIR / "nudge.json"
NUDGE_TIMES, NUDGE_GAP = 3, 20 * 3600


def claude_copies() -> List[str]:
    """ccx plugin ids installed in Claude, e.g. ["ccx@ccx"] or ["ccx@claude-plugins-official"]."""
    try:
        d = json.loads((HOME / ".claude/plugins/installed_plugins.json").read_text())
    except (OSError, ValueError):
        return []
    return sorted(k for k in (d.get("plugins", d) or {}) if k.split("@")[0] == "ccx")


def codex_copies() -> List[str]:
    from .codex import CODEX_HOME
    try:
        text = (CODEX_HOME / "config.toml").read_text()
    except OSError:
        return []
    return sorted(set(re.findall(r'^\[plugins\."(ccx@[^"]+)"\]', text, re.M)))


def full_install() -> bool:
    """The install script ran here (it builds the menu bar app)."""
    return MENU_APP.exists()


def setup_hint() -> str:
    return L(f"For the ⇄ menu bar (one-click switching) and the Codex side, install the rest of ccx: {REPO_URL}\n"
             f"Install steps: {INSTALL_GUIDE}",
             f"想要菜单栏 ⇄（一键切换）并接入 Codex，请安装 ccx 的其余部分：{REPO_URL}\n"
             f"安装步骤：{INSTALL_GUIDE}")


def nudge_due() -> bool:
    """A plugin-only install shows where to get the rest: at most 3 times, a day apart."""
    if full_install():
        return False
    try:
        shown = json.loads(NUDGE.read_text())
    except (OSError, ValueError):
        shown = []
    if len(shown) >= NUDGE_TIMES or (shown and time.time() - shown[-1] < NUDGE_GAP):
        return False
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        NUDGE.write_text(json.dumps(shown + [time.time()]))
    except OSError:
        return False
    return True
