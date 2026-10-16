# Releasing and distribution

## Releasing a new version

`main` is the release branch: installed copies and both apps' plugin marketplaces follow it. Do day-to-day work on another branch and merge it when a release is ready.

1. Set the same version in three places:
   - `plugins/ccx/lib/ccx/__init__.py`
   - `plugins/ccx/.claude-plugin/plugin.json`
   - `plugins/ccx/.codex-plugin/plugin.json`

   Claude only updates a plugin when the version changes, and `ccx` forces a reinstall whenever the installed version differs.
2. Merge to `main` and push.
3. Tag and push the tag:

   ```bash
   git tag v0.0.2 && git push origin v0.0.2
   ```

   The `release` workflow checks that the tag matches the version, runs the tests, and publishes a GitHub Release.
4. Installed copies see the new tag within a few hours (`ccx update --check` reads the repo's tags). They update themselves: `git pull`, refresh both apps' plugins, re-trust ccx's Codex hook, rebuild the menu bar app. Users who turned off automatic installs get a notification and an "Update to …" menu item instead.

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

## While the repository is private

`raw.githubusercontent.com` and `git clone` need GitHub credentials. Run `gh auth login && gh auth setup-git`, then `gh repo clone aaronwong1999/ccx /tmp/ccx && /tmp/ccx/install.sh`. Once the repository is public, the one-line install in the README works for everyone.

## Name and trademarks

- The repository, plugin and app are named **ccx**; "ccx - claudecodex" is the display name.
- Describe what it works with ("for Claude Code and Codex"), and keep the "not affiliated with Anthropic or OpenAI" line.
- ccx only uses the apps' public plugin systems, Codex's app-server API and deep links. It reads and writes local files only and never touches accounts or credentials.
