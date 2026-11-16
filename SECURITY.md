# Security Policy

## Supported Versions

Only the latest release is supported. Please update to the newest version before
reporting an issue.

## Reporting a Vulnerability

Please report security problems privately using GitHub's vulnerability reporting
form on this repository (**Security** → **Report a vulnerability**). Do not open a
public issue for anything security related.

Please include:

- the ccx version you are running,
- your macOS version,
- steps to reproduce, and
- the impact you observed.

## What ccx touches

ccx runs locally on macOS and talks to the Claude Code, Codex and Antigravity apps
installed on your machine. It does not call the Claude API, and it does not proxy,
extract or export your login sessions — you stay logged in to each app directly.
Please report issues in those third-party apps or with model providers to them.

## Disclosure

We will acknowledge a valid report and keep you updated while we work on a fix. We
are happy to credit you in the release notes unless you would rather stay anonymous.
