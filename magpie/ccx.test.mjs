import { afterAll, expect, test } from "bun:test"
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { INSTALL, findCcx } from "./ccx.mjs"
import { CcxTools } from "./index.mjs"

// A stand-in for the ccx command: it logs its arguments and answers the way
// ccx 0.0.36 does.
const dir = mkdtempSync(join(tmpdir(), "tools-ccx-"))
const log = join(dir, "args.log")
const fake = join(dir, "ccx")
writeFileSync(
  fake,
  `#!/bin/sh
echo "$@" >> "${log}"
case "$*" in
  *list_sessions*) printf 'Claude sessions, newest first:\\n1. “Fix the login bug” 10-23 17:29 · not linked · id=bd299fd9-1cab-4636-98ac-9062ddece6f9\\n' ;;
  *"--session-id missing"*) echo "✗ Claude session missing not found" ;;
  *read_session*) echo '{"title": "Fix the login bug", "cwd": "/tmp/app", "text": "[user] the login form 500s", "offset": 0, "next_offset": 25, "total_chars": 25}' ;;
  *) echo "unexpected: $*" >&2; exit 2 ;;
esac
`,
)
chmodSync(fake, 0o755)
process.env.CCX_BIN = fake
afterAll(() => rmSync(dir, { recursive: true, force: true }))

const { tool } = await CcxTools({})
const call = (name, args) => tool[name].execute(args, { agent: "test", abort: AbortSignal.timeout(5000) })
const lastArgs = () => readFileSync(log, "utf8").trim().split("\n").at(-1)

test("gives two tools, each with a JSON Schema and an execute", () => {
  expect(Object.keys(tool).sort()).toEqual(["read", "sessions"])
  for (const [name, t] of Object.entries(tool)) {
    expect(name).toMatch(/^[A-Za-z0-9_-]{1,48}$/)
    expect(t.description.length).toBeGreaterThan(40)
    expect(t.args.type).toBe("object")
    expect(typeof t.execute).toBe("function")
  }
})

test("sessions lists the app asked for, by calling from the other side", async () => {
  expect(await call("sessions", { app: "claude" })).toContain("Fix the login bug")
  expect(lastArgs()).toBe("call codex list_sessions --no-open")
  await call("sessions", { app: "codex", query: "login", cwd: "/tmp/app" })
  expect(lastArgs()).toBe("call claude list_sessions --no-open --query login -C /tmp/app")
  await expect(call("sessions", { app: "cursor" })).rejects.toThrow('app is "claude" or "codex"')
})

test("read answers the page as JSON and pages on with offset", async () => {
  expect(await call("read", { app: "claude", session_id: " bd299fd9 " })).toEqual({
    title: "Fix the login bug",
    cwd: "/tmp/app",
    text: "[user] the login form 500s",
    offset: 0,
    next_offset: 25,
    total_chars: 25,
  })
  expect(lastArgs()).toBe("call codex read_session --no-open --session-id bd299fd9")
  await call("read", { app: "codex", session_id: "01a151c0", offset: 6000 })
  expect(lastArgs()).toBe("call claude read_session --no-open --session-id 01a151c0 --offset 6000")
})

test("read says what is wrong instead of guessing", async () => {
  await expect(call("read", { app: "claude", session_id: "missing" })).rejects.toThrow("Claude session missing not found")
  await expect(call("read", { app: "claude" })).rejects.toThrow("session_id is a string")
  await expect(call("read", { app: "claude", session_id: "x", offset: -1 })).rejects.toThrow("offset is a whole number")
})

test("without ccx it says how to install it", async () => {
  process.env.CCX_BIN = join(dir, "no-such-ccx")
  try {
    await expect(call("sessions", { app: "claude" })).rejects.toThrow(INSTALL)
  } finally {
    process.env.CCX_BIN = fake
  }
})

test("finds ccx where install.sh puts it, or on the PATH", () => {
  expect(findCcx({ CCX_BIN: "/opt/ccx" })).toBe("/opt/ccx")
  expect(findCcx({ HOME: dir })).toBe("ccx")
})
