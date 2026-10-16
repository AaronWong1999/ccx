// ccx - claudecodex menu bar app: one click to continue a session in the other app.
// All the work is done by the `ccx` command; this is only the clickable surface.

import AppKit

let repoURL = "https://github.com/aaronwong1999/ccx"

/// Shorten to about `width` Latin characters; CJK and other wide characters count double.
func short(_ s: String, _ width: Int) -> String {
    var used = 0, out = ""
    for ch in s {
        let w = ch.unicodeScalars.contains { $0.value >= 0x1100 } ? 2 : 1
        if used + w > width - 1 { return out + "…" }
        used += w
        out.append(ch)
    }
    return s
}

/// The menu's language: English (default) or Chinese, chosen in the menu.
func L(_ en: String, _ zh: String) -> String {
    UserDefaults.standard.string(forKey: "language") == "zh" ? zh : en
}

struct Row: Decodable {
    let id: String
    let title: String
    let updated: String
    let status: String  // new | linked | updated | mirror
    let linked_to: String?
    let cwd: String
    let partner_tokens: Int?      // Codex rows: size of the linked Claude conversation
    let partner_idle_min: Int?    // … and how long it has been idle
    let own_tokens: Int?          // Claude rows: size of the session itself
}

struct Project: Decodable {
    let cwd: String
    let name: String
    let updated: String
    let codex: [Row]
    let claude: [Row]
}

struct MenuData: Decodable {
    let projects: [Project]
    let version: String?
    let codex_hook_trusted: Bool?
    let pending_history_repairs: Int?
}

struct Release: Decodable {
    let current: String
    let latest: String?
    let available: Bool
}

final class App: NSObject, NSApplicationDelegate, NSMenuDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let menu = NSMenu()
    let defaults = UserDefaults.standard
    var data: MenuData?
    var release: Release?
    var loadedAt = Date.distantPast
    var loading = false
    var busy = false
    var autostartOn = false
    var lastError: String?
    var menuOpen = false
    var needsRebuild = false

    var ccx: String {
        if let p = Bundle.main.object(forInfoDictionaryKey: "CCXPath") as? String,
           FileManager.default.isExecutableFile(atPath: p) { return p }
        return NSHomeDirectory() + "/.local/bin/ccx"
    }

    var version: String {
        data?.version ?? (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "")
    }

    var autoInstall: Bool {
        get { defaults.object(forKey: "autoInstallUpdates") as? Bool ?? true }
        set { defaults.set(newValue, forKey: "autoInstallUpdates") }
    }

    func applicationDidFinishLaunching(_ n: Notification) {
        setIcon(busy: false)
        // An update restarts this app, so announce it from the new copy.
        let bundleVersion = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
        if let last = defaults.string(forKey: "lastVersion"), last != bundleVersion, !bundleVersion.isEmpty {
            notify(L("ccx updated to \(bundleVersion)", "ccx 已更新到 \(bundleVersion)"),
                   L("Claude and Codex pick up the new plugin in new conversations.", "Claude 和 Codex 会在新对话里使用新版插件。"))
        }
        defaults.set(bundleVersion, forKey: "lastVersion")
        item.button?.toolTip = "ccx - claudecodex"
        menu.delegate = self
        menu.autoenablesItems = false
        item.menu = menu
        if clickTest { runClickTest(); return }
        run(["config", "language", defaults.string(forKey: "language") ?? "en"]) { _, _, _ in }
        run(["config", "warn_long_resume", warnLongResume ? "true" : "false"]) { _, _, _ in }
        rebuild()
        refresh()
        Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.refresh() }
        Timer.scheduledTimer(withTimeInterval: 3 * 3600, repeats: true) { [weak self] _ in self?.checkRelease(manual: false) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in self?.checkRelease(manual: false) }
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in self?.refresh() }
    }

    func setIcon(busy: Bool) {
        let name = busy ? "arrow.triangle.2.circlepath" : "arrow.left.arrow.right.circle"
        let img = NSImage(systemSymbolName: name, accessibilityDescription: "ccx")
        img?.isTemplate = true
        item.button?.image = img
    }

    // MARK: running ccx

    func run(_ args: [String], done: @escaping (Int32, String, String) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: self.ccx)
            p.arguments = args
            let out = Pipe(), err = Pipe()
            p.standardOutput = out
            p.standardError = err
            do { try p.run() } catch {
                DispatchQueue.main.async { done(-1, "", "ccx not found at \(self.ccx)") }
                return
            }
            let o = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            let e = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            p.waitUntilExit()
            DispatchQueue.main.async { done(p.terminationStatus, o, e) }
        }
    }

    /// Blocking run for a quick query (e.g. a token estimate shown in a dialog).
    func runNow(_ args: [String]) -> String {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: ccx)
        p.arguments = args
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        guard (try? p.run()) != nil else { return "" }
        let o = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        p.waitUntilExit()
        return o
    }

    /// Tokens the other app reads: full import, condensed new conversation, and the
    /// pending updates a transfer to the linked conversation adds.
    func estimate(_ from: String, _ id: String) -> [String: Int] {
        let o = runNow(["estimate", from, id])
        return (try? JSONSerialization.jsonObject(with: Data(o.utf8))) as? [String: Int] ?? [:]
    }

    func refresh() {
        if loading { return }
        loading = true
        run(["menu-data"]) { code, out, err in
            self.loading = false
            if code == 0, let d = try? JSONDecoder().decode(MenuData.self, from: Data(out.utf8)) {
                if (self.data?.pending_history_repairs ?? 0) > 0 && (d.pending_history_repairs ?? 0) == 0 {
                    self.notify(L("History repair complete", "历史修复完成"),
                                L("You can reopen Codex now.", "现在可以重新打开 Codex。"))
                }
                self.data = d
                self.loadedAt = Date()
                self.lastError = nil
            } else {
                self.lastError = err.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            self.run(["autostart", "status"]) { c, _, _ in
                self.autostartOn = c == 0
                self.rebuild()
                if CommandLine.arguments.contains("--selftest") { self.dump(self.menu, 0); exit(self.data == nil ? 1 : 0) }
            }
        }
    }

    // MARK: releases

    func notify(_ title: String, _ text: String) {
        let esc = { (s: String) in s.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        p.arguments = ["-e", "display notification \"\(esc(text))\" with title \"\(esc(title))\""]
        try? p.run()
    }

    func checkRelease(manual: Bool) {
        run(["update", "--check", "--json"]) { code, out, _ in
            guard code == 0, let r = try? JSONDecoder().decode(Release.self, from: Data(out.utf8)) else {
                if manual { self.alert(L("Couldn't check for updates", "无法检查更新"), L("Check your network, or run `ccx update --check` in Terminal.", "请检查网络，或在终端运行 `ccx update --check`。")) }
                return
            }
            self.release = r
            self.rebuild()
            guard r.available, let latest = r.latest else {
                if manual { self.alert(L("You're up to date", "已是最新版本"), L("ccx - claudecodex \(r.current) is the latest version.", "ccx - claudecodex \(r.current) 已是最新。")) }
                return
            }
            if self.autoInstall && !manual {
                self.install(latest, announce: true)
            } else if manual {
                self.install(latest, announce: true)
            } else if self.defaults.string(forKey: "notifiedVersion") != latest {
                self.defaults.set(latest, forKey: "notifiedVersion")
                self.notify(L("ccx \(latest) is available", "ccx \(latest) 已发布"), L("Open the ⇄ menu and choose “Update to \(latest)”.", "打开 ⇄ 菜单，选择「更新到 \(latest)」。"))
            }
        }
    }

    func install(_ latest: String, announce: Bool) {
        busy = true
        setIcon(busy: true)
        rebuild()
        run(["update", "--quiet"]) { code, out, err in
            self.busy = false
            self.setIcon(busy: false)
            if code == 0 {
                if announce { self.notify(L("ccx updated to \(latest)", "ccx 已更新到 \(latest)"), L("Claude and Codex pick up the new plugin in new conversations.", "Claude 和 Codex 会在新对话里使用新版插件。")) }
                self.release = nil
            } else {
                self.notify(L("ccx update failed", "ccx 更新失败"), (err + out).trimmingCharacters(in: .whitespacesAndNewlines))
            }
            self.refresh()
        }
    }

    // MARK: menu

    func menuWillOpen(_ m: NSMenu) {
        menuOpen = true
        if Date().timeIntervalSince(loadedAt) > 20 { refresh() }
    }

    func menuDidClose(_ m: NSMenu) {
        menuOpen = false
        if needsRebuild { rebuild() }
    }

    /// Never rebuild an open menu: macOS keeps its old height, which leaves blank rows.
    func rebuild() {
        if menuOpen { needsRebuild = true; return }
        needsRebuild = false
        menu.removeAllItems()

        // Title, then the tagline in the chosen language.
        let head = NSMenuItem()
        let title = NSMutableAttributedString(string: "ccx - claudecodex", attributes: [.font: NSFont.boldSystemFont(ofSize: 13)])
        title.append(NSAttributedString(string: "  \(version)", attributes: [
            .font: NSFont.systemFont(ofSize: 11), .foregroundColor: NSColor.secondaryLabelColor]))
        title.append(NSAttributedString(string: "\n" + L("Sync task memory between Claude Code and Codex", "在 Claude Code 和 Codex 之间同步任务记忆"),
                                        attributes: [.font: NSFont.systemFont(ofSize: NSFont.smallSystemFontSize),
                                                     .foregroundColor: NSColor.secondaryLabelColor]))
        head.attributedTitle = title
        head.isEnabled = false
        menu.addItem(head)

        if let r = release, r.available, let latest = r.latest {
            let up = action(L("Update to \(latest)", "更新到 \(latest)"), #selector(updateNow), symbol: "arrow.down.circle.fill")
            menu.addItem(up)
        }
        menu.addItem(.separator())

        if busy { menu.addItem(caption(L("Working…", "正在处理…"))) }
        if let d = data {
            if (d.pending_history_repairs ?? 0) > 0 {
                menu.addItem(action(L("History repair pending…", "历史修复待完成…"), #selector(historyRepairInfo), symbol: "exclamationmark.triangle"))
            }
            if d.projects.isEmpty {
                menu.addItem(caption(L("No Claude or Codex sessions yet", "还没有 Claude 或 Codex 会话")))
            } else {
                menu.addItem(caption(L("RECENT PROJECTS", "最近的项目")))
                for p in d.projects { menu.addItem(projectItem(p)) }
                menu.addItem(caption(L("○ new  ✓ linked  ↻ updated", "○ 未关联  ✓ 已关联  ↻ 有更新")))
            }
            if d.codex_hook_trusted == false {
                menu.addItem(.separator())
                menu.addItem(action(L("Turn on auto-sync in Codex…", "在 Codex 里开启自动同步…"), #selector(fixHook), symbol: "exclamationmark.triangle"))
            }
        } else {
            menu.addItem(caption(lastError.map { L("Couldn't read sessions: \($0)", "无法读取会话：\($0)") } ?? L("Reading sessions…", "正在读取会话…")))
        }

        menu.addItem(.separator())
        let lang = NSMenuItem(title: "Language / 语言", action: nil, keyEquivalent: "")
        lang.image = NSImage(systemSymbolName: "globe", accessibilityDescription: nil)
        let langs = NSMenu()
        for (code, name) in [("en", "English"), ("zh", "中文")] {
            let li = NSMenuItem(title: name, action: #selector(setLanguage(_:)), keyEquivalent: "")
            li.target = self
            li.representedObject = code
            li.state = (defaults.string(forKey: "language") ?? "en") == code ? .on : .off
            langs.addItem(li)
        }
        lang.submenu = langs
        menu.addItem(lang)
        let login = action(L("Start at Login", "登录时自动启动"), #selector(toggleLogin))
        login.state = autostartOn ? .on : .off
        menu.addItem(login)
        let warn = action(L("Warn Before Resuming Long Conversations", "继续超长对话前提醒"), #selector(toggleWarnLongResume))
        warn.state = warnLongResume ? .on : .off
        menu.addItem(warn)
        let auto = action(L("Install Updates Automatically", "自动安装更新"), #selector(toggleAutoInstall))
        auto.state = autoInstall ? .on : .off
        menu.addItem(auto)
        menu.addItem(action(L("Check for Updates…", "检查更新…"), #selector(checkUpdate)))
        menu.addItem(action(L("Diagnostics…", "诊断…"), #selector(showDoctor)))
        menu.addItem(action(L("Refresh", "刷新"), #selector(refreshClicked), key: "r"))
        menu.addItem(.separator())
        let star = action("", #selector(openRepo), symbol: "star")
        let st = NSMutableAttributedString(string: L("Star on GitHub", "在 GitHub 上点 Star") + "\n",
                                           attributes: [.font: NSFont.menuFont(ofSize: 0)])
        st.append(NSAttributedString(string: "github.com/aaronwong1999/ccx", attributes: [
            .font: NSFont.systemFont(ofSize: NSFont.smallSystemFontSize), .foregroundColor: NSColor.secondaryLabelColor]))
        star.attributedTitle = st
        menu.addItem(star)
        menu.addItem(NSMenuItem(title: L("Quit ccx", "退出 ccx"), action: #selector(NSApp.terminate), keyEquivalent: "q"))
    }

    func action(_ t: String, _ sel: Selector, key: String = "", symbol: String? = nil) -> NSMenuItem {
        let i = NSMenuItem(title: t, action: sel, keyEquivalent: key)
        i.target = self
        i.isEnabled = !busy
        if let s = symbol { i.image = NSImage(systemSymbolName: s, accessibilityDescription: nil) }
        return i
    }

    func caption(_ t: String) -> NSMenuItem {
        let i = NSMenuItem(title: t, action: nil, keyEquivalent: "")
        i.attributedTitle = NSAttributedString(string: t, attributes: [
            .font: NSFont.systemFont(ofSize: NSFont.smallSystemFontSize),
            .foregroundColor: NSColor.secondaryLabelColor,
        ])
        i.isEnabled = false
        return i
    }

    func projectItem(_ p: Project) -> NSMenuItem {
        let name = short(p.name, 26)
        let it = NSMenuItem(title: name, action: nil, keyEquivalent: "")
        it.image = NSImage(systemSymbolName: "folder", accessibilityDescription: nil)
        it.toolTip = p.cwd
        let pending = (p.codex + p.claude).contains { $0.status == "updated" }
        if pending {
            let t = NSMutableAttributedString(string: name)
            t.append(NSAttributedString(string: "  ↻", attributes: [.foregroundColor: NSColor.controlAccentColor]))
            it.attributedTitle = t
        }
        let sub = NSMenu()
        sub.autoenablesItems = false
        sub.addItem(caption(L("Transfer to Claude · from Codex", "传输到 Claude · 来自 Codex")))
        if p.codex.isEmpty { sub.addItem(caption(L("No Codex threads", "没有 Codex 会话"))) }
        for r in p.codex { sub.addItem(sessionItem(r, from: "codex")) }
        sub.addItem(.separator())
        sub.addItem(caption(L("Transfer to Codex · from Claude", "传输到 Codex · 来自 Claude")))
        if p.claude.isEmpty { sub.addItem(caption(L("No Claude sessions", "没有 Claude 会话"))) }
        for r in p.claude { sub.addItem(sessionItem(r, from: "claude")) }
        it.submenu = sub
        return it
    }

    func sessionItem(_ r: Row, from: String) -> NSMenuItem {
        let glyph = ["new": "○", "updated": "↻", "linked": "✓", "mirror": "·"][r.status] ?? "○"
        var title = short(r.title, 36)
        if r.status == "mirror" { title += L("  (imported copy)", "  （导入的副本）") }
        let i = NSMenuItem(title: "", action: #selector(sessionClicked(_:)), keyEquivalent: "")
        i.target = self
        i.representedObject = ["from": from, "id": r.id, "tokens": String(r.partner_tokens ?? 0),
                               "idle": String(r.partner_idle_min ?? 0), "own": String(r.own_tokens ?? 0),
                               "linked": r.linked_to == nil ? "0" : "1", "title": r.title]
        let s = NSMutableAttributedString(string: "\(glyph)  \(title)", attributes: [
            .font: NSFont.menuFont(ofSize: 0),
            .foregroundColor: r.status == "mirror" ? NSColor.secondaryLabelColor : NSColor.labelColor,
        ])
        s.append(NSAttributedString(string: "   \(r.updated)", attributes: [
            .font: NSFont.menuFont(ofSize: NSFont.smallSystemFontSize), .foregroundColor: NSColor.tertiaryLabelColor]))
        i.attributedTitle = s
        let hint = (r.status == "new" || r.status == "mirror")
            ? L("Import into the other app and link the two; they stay in sync from then on", "导入到另一边并关联，之后两边自动同步")
            : L("Open the linked conversation in the other app; your next message there brings the new progress", "打开另一边关联的会话；在那边发一句话就会带上新进展")
        i.toolTip = r.title + "\n\n" + hint
        i.isEnabled = !busy
        return i
    }

    // MARK: actions


    @objc func historyRepairInfo() {
        alert(L("History repair is queued", "历史修复已排队"),
              L("Codex still holds an old imported thread open. Quit Codex when convenient; ccx retries every minute. Open Codex again after the pending notice disappears.",
                "Codex 仍占用旧导入会话。方便时退出 Codex；ccx 每分钟自动重试。待此提示消失后再打开 Codex。"))
    }

    /// `--click <codex|claude> <session id>` runs exactly what clicking that session in
    /// the menu runs, prints the outcome instead of showing it, and exits (for tests).
    var clickTest: Bool { CommandLine.arguments.contains("--click") }

    func runClickTest() {
        let a = CommandLine.arguments, i = a.firstIndex(of: "--click")!
        // Use the same row data a real click carries (size and idle time of the partner).
        run(["menu-data"]) { _, out, _ in
            var obj = ["from": a[i + 1], "id": a[i + 2]]
            if let d = try? JSONDecoder().decode(MenuData.self, from: Data(out.utf8)),
               let r = d.projects.flatMap({ $0.codex + $0.claude }).first(where: { $0.id == a[i + 2] }) {
                obj["tokens"] = String(r.partner_tokens ?? 0)
                obj["idle"] = String(r.partner_idle_min ?? 0)
                obj["own"] = String(r.own_tokens ?? 0)
                obj["linked"] = r.linked_to == nil ? "0" : "1"
            }
            let item = NSMenuItem()
            item.representedObject = obj
            self.sessionClicked(item)
        }
    }

    /// The result of a transfer, shown over the app that just opened.
    func info(_ title: String, _ text: String) {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert()
        a.messageText = title
        a.informativeText = text
        a.window.level = .floating
        a.runModal()
    }

    func alert(_ title: String, _ text: String) {
        if clickTest { print("ALERT: \(title)\n\(text)"); exit(1) }
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert()
        a.messageText = title
        a.informativeText = text
        a.runModal()
    }

    func work(_ args: [String], title: String, showOutput: Bool, notifyResult: Bool = false) {
        busy = true
        setIcon(busy: true)
        rebuild()
        run(args) { code, out, err in
            self.busy = false
            self.setIcon(busy: false)
            var text = (out + err).trimmingCharacters(in: .whitespacesAndNewlines)
            var heading = "ccx"
            if code == 0, let d = (try? JSONSerialization.jsonObject(with: Data(out.utf8))) as? [String: Any],
               let msg = d["message"] as? String {
                text = msg
                let n = d["pending"] as? Int ?? 0
                switch d["action"] as? String ?? "" {
                case "created": heading = L("Imported and linked", "已导入并关联")
                case "in_sync": heading = L("Already in sync, nothing new", "已同步，没有新内容")
                default: heading = L("Linked: \(n) new updates to bring over", "已关联：有 \(n) 条新进展待带入")
                }
            }
            if code != 0 { self.alert(L("That didn't work", "没有成功"), text) } else if showOutput { self.alert(title, text) }
            else if notifyResult && !self.clickTest {
                self.info(heading, text.replacingOccurrences(of: "✓ ", with: ""))
            }
            if self.clickTest { print("OK: \(heading) | \(text)"); exit(0) }
            self.refresh()
        }
    }

    @objc func sessionClicked(_ sender: NSMenuItem) {
        guard let o = sender.representedObject as? [String: String], let from = o["from"], let id = o["id"] else { return }
        let dst = from == "codex" ? "Claude" : "Codex"
        // tokens/idle describe the linked conversation on the other side (the target).
        let tokens = Int(o["tokens"] ?? "") ?? 0, idle = Int(o["idle"] ?? "") ?? 0
        let own = Int(o["own"] ?? "") ?? 0, linked = o["linked"] == "1"
        // In click tests, `--answer new|open|cancel` stands in for the button press.
        let a0 = CommandLine.arguments, preset = a0.firstIndex(of: "--answer").map { a0[$0 + 1] }
        // 1. The target conversation is huge and idle past its cache lifetime: the next
        //    message there re-reads all of it, however little this transfer adds.
        // 2. An unlinked long Claude session: a full import makes Codex read all of it.
        let stale = warnLongResume && tokens >= (from == "codex" ? 250_000 : 150_000) && idle >= 55
        let est = stale || (from == "claude" && !linked && own >= 50_000) ? estimate(from, id) : [:]
        let full = est["full"] ?? 0, small = max(est["condensed"] ?? 0, 1000)
        let n = est["pending"] ?? 0, added = est["pending_tokens"] ?? 0
        let fullImport = warnLongResume && !stale && from == "claude" && !linked && full >= 100_000
        if stale || fullImport {
            let k = { (t: Int) in "\(max(1, (t + 500) / 1000))k" }
            let title: String, msg: String
            if fullImport {
                title = L("This Claude conversation is very long", "这个 Claude 对话非常长")
                msg = L("A full import makes Codex read about \(k(full)) tokens of it on its first reply.\n\nA new Codex conversation reads only the condensed progress instead: about \(k(small)) tokens, and it stays linked.",
                        "完整导入后，Codex 第一次回复会读取它约 \(k(full)) token。\n\n新开一个 Codex 对话只读压缩后的进展：约 \(k(small)) token，并保持关联。")
            } else {
                let adds = n > 0 ? L("This transfer adds only the new progress: \(n) updates, about \(k(added)) tokens.",
                                     "这次只传新进展：\(n) 条，约 \(k(added)) token。")
                                 : L("There is no new progress to transfer.", "这次没有新进展需要传。")
                title = L("The \(dst) conversation it goes to is very long", "要传去的 \(dst) 对话已经很长")
                msg = adds + L(" But that \(dst) conversation itself is about \(k(tokens)) tokens and has been idle for \(idle / 60) h \(idle % 60) min, so its cache has likely expired: with your next message there, \(dst) re-reads all of it, about \(k(tokens + added)) tokens.\n\nA new \(dst) conversation reads only the condensed progress: about \(k(small)) tokens, and it stays linked.",
                               "但目标 \(dst) 对话本身已有约 \(k(tokens)) token，闲置了 \(idle / 60) 小时 \(idle % 60) 分钟，缓存很可能已过期：你在那里发下一条消息时，\(dst) 会把整个对话重新读一遍，约 \(k(tokens + added)) token。\n\n新开一个 \(dst) 对话只读压缩后的进展：约 \(k(small)) token，并保持关联。")
            }
            let choice: String
            if clickTest, let p = preset {
                print("DIALOG: \(title)\n\(msg)\n-> \(p)")
                choice = p
            } else {
                NSApp.activate(ignoringOtherApps: true)
                let a = NSAlert()
                a.messageText = title
                a.informativeText = msg
                a.addButton(withTitle: L("New \(dst) Conversation", "新开 \(dst) 对话"))
                a.addButton(withTitle: fullImport ? L("Import Everything", "完整导入") : L("Open It Anyway", "仍然打开"))
                a.addButton(withTitle: L("Cancel", "取消"))
                switch a.runModal() {
                case .alertFirstButtonReturn: choice = "new"
                case .alertThirdButtonReturn: choice = "cancel"
                default: choice = "open"
                }
            }
            if choice == "new" { work([from == "codex" ? "new-claude" : "new-codex", id], title: "", showOutput: false, notifyResult: true); return }
            if choice == "cancel" { if clickTest { exit(0) }; return }
        }
        work([from == "codex" ? "to-claude" : "to-codex", id, "--json"], title: "", showOutput: false, notifyResult: true)
    }

    @objc func updateNow() { if let l = release?.latest { install(l, announce: true) } }
    @objc func checkUpdate() { checkRelease(manual: true) }
    @objc func showDoctor() { work(["doctor"], title: L("ccx diagnostics", "ccx 诊断"), showOutput: true) }
    @objc func fixHook() { work(["setup"], title: L("ccx setup", "ccx 设置"), showOutput: true) }
    @objc func refreshClicked() { refresh() }
    @objc func openRepo() { NSWorkspace.shared.open(URL(string: repoURL)!) }

    @objc func setLanguage(_ sender: NSMenuItem) {
        let code = sender.representedObject as? String ?? "en"
        defaults.set(code, forKey: "language")
        run(["config", "language", code]) { _, _, _ in }  // ccx's own messages follow the menu
        rebuild()
    }

    var warnLongResume: Bool {
        get { defaults.object(forKey: "warnLongResume") as? Bool ?? true }
        set { defaults.set(newValue, forKey: "warnLongResume") }
    }

    @objc func toggleWarnLongResume() {
        warnLongResume.toggle()
        run(["config", "warn_long_resume", warnLongResume ? "true" : "false"]) { _, _, _ in }
        rebuild()
    }

    @objc func toggleAutoInstall() {
        autoInstall.toggle()
        rebuild()
    }

    @objc func toggleLogin() {
        run(["autostart", autostartOn ? "off" : "on"]) { _, _, _ in self.refresh() }
    }

    func dump(_ m: NSMenu, _ depth: Int) {
        if depth == 0 { print("status item visible: \(item.button?.window?.isVisible ?? false)") }
        for (n, i) in m.items.enumerated() {
            let t = i.isSeparatorItem ? "────" : (i.attributedTitle?.string ?? i.title)
            let st = i.state == .on ? "[on] " : ""
            print(String(repeating: "  ", count: depth) + st + t + (i.isEnabled ? "" : "  [disabled]"))
            if let sub = i.submenu, depth == 0, n < 6 { dump(sub, depth + 1) }
        }
    }
}

let app = NSApplication.shared
let delegate = App()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
