// Claude Code and Codex conversations as tools magpie offers every agent (its
// MCP server /mcp/magpie/tools), through ccx. An agent on any model can list
// them and read one to pick up the task where it stopped. Nothing here writes
// or opens an app.
import { parseJson, readArgs, run, sessionsArgs } from "./ccx.mjs"

const APP = {
  type: "string",
  enum: ["claude", "codex"],
  description: "whose conversations: claude (Claude Code) or codex (Codex)",
}

export const CcxTools = async () => ({
  tool: {
    sessions: {
      description:
        "Lists the Claude Code or Codex conversations on this Mac, newest first, with each one's id, title, date, folder and whether it is linked to the other app. " +
        "Use it to find the conversation where a task was being worked on, then ccx_read it to continue. `query` searches titles in every project; " +
        "`cwd` marks the ones in that folder.",
      args: {
        type: "object",
        properties: {
          app: APP,
          query: { type: "string", description: "words from the title, searched in every project" },
          cwd: { type: "string", description: "the project folder, so its conversations are marked" },
        },
        required: ["app"],
      },
      async execute(args, ctx) {
        return run(sessionsArgs(args), { signal: ctx?.abort })
      },
    },
    read: {
      description:
        "Reads a Claude Code or Codex conversation as condensed text: the messages, each tool call and its result in short, and the plan, so you can carry on the task " +
        "without the user explaining it again. It comes in pages of about 6000 characters: when next_offset is below total_chars, call again with offset = next_offset. " +
        "Take session_id from ccx_sessions.",
      args: {
        type: "object",
        properties: {
          app: APP,
          session_id: { type: "string", description: "the conversation's id, from ccx_sessions" },
          offset: { type: "number", description: "where to start, the next_offset of the last read (default 0)" },
        },
        required: ["app", "session_id"],
      },
      async execute(args, ctx) {
        return parseJson(await run(readArgs(args), { signal: ctx?.abort }), "read_session")
      },
    },
  },
})
