// Loaded before ZCode's command-line agent when ccx runs it. The agent names
// its process "zcode-cli", and on macOS renaming a process that lives in an
// app bundle checks it in as a foreground app: each run would flash a ZCode
// icon in the Dock. Keeping the name as it is keeps those runs invisible.
"use strict";
Object.defineProperty(process, "title", { get() { return "zcode-cli"; }, set() {}, configurable: false });
