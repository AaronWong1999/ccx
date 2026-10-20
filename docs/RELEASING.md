# Releasing and distribution

## Releasing a new version

**Only tags release.** Installed copies run the newest `vX.Y.Z` tag, never `main` itself, so committing and pushing to `main` reaches nobody and triggers no update notice. Both apps install the plugin from the user's local copy, so they follow the same tag. Tags must be exactly `vX.Y.Z`; anything else (for example `v0.1.0-beta`) is ignored by update checks.

1. Set the same version in three places:
   - `plugins/ccx/lib/ccx/__init__.py`
   - `plugins/ccx/.claude-plugin/plugin.json`
   - `plugins/ccx/.codex-plugin/plugin.json`

   Claude only updates a plugin when the version changes, and `ccx` forces a reinstall whenever the installed version differs.
2. Commit and push to `main` (nothing is released yet).
3. Tag and push the tag:

   ```bash
   git tag v0.0.2 && git push origin v0.0.2
   ```

   The `release` workflow checks that the tag matches the version, runs the tests, and publishes a GitHub Release.
4. Installed copies see the new tag within a few hours (`ccx update --check` reads the repo's tags). They update themselves: fetch tags, check out the new tag, refresh both apps' plugins, re-trust ccx's Codex hook, rebuild the menu bar app. Users who turned off automatic installs get a notification and an "Update to …" menu item instead.

## Why an install script and not a DMG (for now)

| | Install script (now) | DMG (later) |
|---|---|---|
| Apple Developer ID ($99/yr) | **Not needed**: the menu bar app is compiled on the user's Mac with `swiftc`, and locally built apps aren't blocked by Gatekeeper | Needed, plus notarization; otherwise macOS blocks the app on first launch |
| What the user does | Pastes one prompt into Claude Code or Codex, or one command into Terminal | Downloads, drags to Applications, opens |
| Requirements | Command Line Tools (git, python3, swiftc). Nearly every Claude Code / Codex user already has them; if not, the installer opens Apple's installer | Can bundle Python and need nothing |
| Updates | Built in (see above) | Needs Sparkle or similar |

Everyone who uses ccx already uses AI coding tools, so the script is the lower-friction path today. Ship a DMG when you want to reach people who never open Terminal:

1. Get a Developer ID, sign `ccx.app`, and notarize it with `notarytool`.
2. Bundle python-build-standalone in `ccx.app/Contents/Resources/python` and have the launchers prefer it.
3. Run `ccx setup` on first launch.
4. Add Sparkle for app updates; plugin updates keep working as they do now.
5. Optionally publish a Homebrew cask (casks must be notarized).

## The install script is served from `main`

The one-line install fetches `install.sh` from `main` (`raw.githubusercontent.com/.../main/install.sh`), so a change to it reaches new installs as soon as it is pushed, with no tag; keep it working with the latest release. Everything it then installs comes from the newest tag. Installing and update checks need no GitHub account, because the repository is public. If it is ever made private again, both stop working for everyone else.

## Name and trademarks

- The repository, plugin and app are named **ccx**; "ccx - claudecodex" is the display name.
- Describe what it works with ("for Claude Code and Codex"), and keep the "not affiliated with Anthropic or OpenAI" line.
- ccx only uses the apps' public plugin systems, Codex's app-server API and deep links. It reads and writes local files only and never touches accounts or credentials.

## Plugin directories

The plugin can also be listed in an app's plugin directory (the Claude plugin directory: claude.ai/directory/manage → Submit new → Plugin bundle; the repository must be public before the listing goes live). Track release **tags**, not `main`, so the directory ships the same versions as the install script.

A directory install is only the plugin. It points people to this repository (plugin description; a short notice in Claude at most 3 times, a day apart; MCP tool results) to install the menu bar and the other app's side. The install script and `ccx setup`/`update` detect a directory copy (`ccx@<marketplace>` other than `ccx@ccx`), keep it, remove the script's own copy if both exist, and never install a second one. Syncing is serialized with a lock, so even two copies never deliver the same updates twice.
