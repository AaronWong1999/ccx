// Runs the ccx command (https://github.com/aaronwong1999/ccx) and reads its
// answers. Kept apart from index.mjs, because magpie takes every function
// index.mjs exports as a plugin.
import { execFile } from "node:child_process"
import { existsSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

export const INSTALL =
  "ccx is not installed. It needs macOS and the Claude and/or Codex desktop app. Install it with: " +
  "curl -fsSL https://raw.githubusercontent.com/aaronwong1999/ccx/main/install.sh | sh"

// CCX_BIN first (tests and custom installs), then where install.sh puts it,
// then whatever `ccx` the PATH finds.
export function findCcx(env = process.env) {
  if (env.CCX_BIN) return env.CCX_BIN
  const local = join(env.HOME || homedir(), ".local", "bin", "ccx")
  return existsSync(local) ? local : "ccx"
}

export function run(args, { signal, env = process.env, timeout = 120000 } = {}) {
  return new Promise((resolve, reject) => {
    execFile(findCcx(env), args, { env, signal, timeout, maxBuffer: 8 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (err && err.code === "ENOENT") return reject(new Error(INSTALL))
      const out = String(stdout || "").trim()
      // ccx says what went wrong in a line that starts with ✗, on either stream
      const failed = `${out}\n${stderr || ""}`.split("\n").find((l) => l.startsWith("✗"))
      if (failed) return reject(new Error(failed.slice(1).trim()))
      if (err) return reject(new Error(String(stderr || "").trim() || err.message))
      resolve(out)
    })
  })
}

// ccx's `call <app> …` runs a tool as if from inside <app>, and lists or reads
// the *other* app's conversations. These tools name the app whose
// conversations they want, so they call from the opposite side.
export const fromOther = (app) => {
  if (app === "claude") return "codex"
  if (app === "codex") return "claude"
  throw new Error('app is "claude" or "codex"')
}

export function sessionsArgs({ app, query, cwd } = {}) {
  const a = ["call", fromOther(app), "list_sessions", "--no-open"]
  if (query !== undefined && query !== "") a.push("--query", String(query))
  if (cwd !== undefined && cwd !== "") a.push("-C", String(cwd))
  return a
}

export function readArgs({ app, session_id, offset } = {}) {
  if (typeof session_id !== "string" || !session_id.trim()) throw new Error("session_id is a string, from ccx_sessions")
  const a = ["call", fromOther(app), "read_session", "--no-open", "--session-id", session_id.trim()]
  if (offset !== undefined) {
    const n = Number(offset)
    if (!Number.isInteger(n) || n < 0) throw new Error("offset is a whole number, the next_offset of the last read")
    a.push("--offset", String(n))
  }
  return a
}

export function parseJson(out, what) {
  try {
    return JSON.parse(out)
  } catch {
    throw new Error(`ccx answered ${what} with something that isn't JSON: ${out.slice(0, 200)}`)
  }
}
