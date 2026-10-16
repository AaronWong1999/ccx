// ccx - claudecodex menu bar app: one click to continue a session in the other app.
// All the work is done by the `ccx` command; this is only the clickable surface.

import AppKit

let repoURL = "https://github.com/aaronwong1999/ccx"

/// The menu's language: English (default) or Chinese, chosen in the menu.
func L(_ en: String, _ zh: String) -> String {
    UserDefaults.standard.string(forKey: "language") == "zh" ? zh : en
}

struct Row: Decodable {
    let id: String
    let title: String
    let updated: String
    let status: String  // new | linked | updated | mirror
    let cwd: String
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

    func refresh() {
        if loading { return }
        loading = true
        run(["menu-data"]) { code, out, err in
            self.loading = false
            if code == 0, let d = try? JSONDecoder().decode(MenuData.self, from: Data(out.utf8)) {
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

        let head = NSMenuItem()
        let title = NSMutableAttributedString(string: "ccx - claudecodex", attributes: [.font: NSFont.boldSystemFont(ofSize: 13)])
        title.append(NSAttributedString(string: "  \(version)", attributes: [
            .font: NSFont.systemFont(ofSize: 11), .foregroundColor: NSColor.secondaryLabelColor]))
        head.attributedTitle = title
        head.isEnabled = false
        menu.addItem(head)
        menu.addItem(caption(L("Continue the same task across Claude Code and Codex", "在 Claude Code 和 Codex 之间接着干同一个任务")))

        if let r = release, r.available, let latest = r.latest {
            let up = action(L("Update to \(latest)", "更新到 \(latest)"), #selector(updateNow), symbol: "arrow.down.circle.fill")
            menu.addItem(up)
        }
        menu.addItem(.separator())

        if busy { menu.addItem(caption(L("Working…", "正在处理…"))) }
        if let d = data {
            if d.projects.isEmpty {
                menu.addItem(caption(L("No Claude or Codex sessions yet", "还没有 Claude 或 Codex 会话")))
            } else {
                menu.addItem(caption(L("RECENT PROJECTS", "最近的项目")))
                for p in d.projects { menu.addItem(projectItem(p)) }
                menu.addItem(caption(L("○ not linked    ✓ linked    ↻ new progress", "○ 未关联    ✓ 已关联    ↻ 有新进展")))
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
        let it = NSMenuItem(title: p.name, action: nil, keyEquivalent: "")
        it.image = NSImage(systemSymbolName: "folder", accessibilityDescription: nil)
        it.toolTip = p.cwd
        let pending = (p.codex + p.claude).contains { $0.status == "updated" }
        if pending {
            let t = NSMutableAttributedString(string: p.name)
            t.append(NSAttributedString(string: "  ↻", attributes: [.foregroundColor: NSColor.controlAccentColor]))
            it.attributedTitle = t
        }
        let sub = NSMenu()
        sub.autoenablesItems = false
        sub.addItem(caption(L("CONTINUE IN CLAUDE  ·  from Codex", "到 Claude 接着干  ·  来自 Codex")))
        if p.codex.isEmpty { sub.addItem(caption(L("No Codex threads", "没有 Codex 会话"))) }
        for r in p.codex { sub.addItem(sessionItem(r, from: "codex")) }
        sub.addItem(.separator())
        sub.addItem(caption(L("CONTINUE IN CODEX  ·  from Claude", "到 Codex 接着干  ·  来自 Claude")))
        if p.claude.isEmpty { sub.addItem(caption(L("No Claude sessions", "没有 Claude 会话"))) }
        for r in p.claude { sub.addItem(sessionItem(r, from: "claude")) }
        it.submenu = sub
        return it
    }

    func sessionItem(_ r: Row, from: String) -> NSMenuItem {
        let glyph = ["new": "○", "updated": "↻", "linked": "✓", "mirror": "·"][r.status] ?? "○"
        var title = r.title.count > 44 ? String(r.title.prefix(44)) + "…" : r.title
        if r.status == "mirror" { title += L("  (imported copy)", "  （导入的副本）") }
        let i = NSMenuItem(title: "", action: #selector(sessionClicked(_:)), keyEquivalent: "")
        i.target = self
        i.representedObject = ["from": from, "id": r.id]
        let s = NSMutableAttributedString(string: "\(glyph)  \(title)", attributes: [
            .font: NSFont.menuFont(ofSize: 0),
            .foregroundColor: r.status == "mirror" ? NSColor.secondaryLabelColor : NSColor.labelColor,
        ])
        s.append(NSAttributedString(string: "   \(r.updated)", attributes: [
            .font: NSFont.menuFont(ofSize: NSFont.smallSystemFontSize), .foregroundColor: NSColor.tertiaryLabelColor]))
        i.attributedTitle = s
        i.toolTip = (r.status == "new" || r.status == "mirror")
            ? L("Import into the other app and link the two; they stay in sync from then on", "导入到另一边并关联，之后两边自动同步")
            : L("Open the linked conversation in the other app; your next message there brings the new progress", "打开另一边关联的会话；在那边发一句话就会带上新进展")
        i.isEnabled = !busy
        return i
    }

    // MARK: actions

    func alert(_ title: String, _ text: String) {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert()
        a.messageText = title
        a.informativeText = text
        a.runModal()
    }

    func work(_ args: [String], title: String, showOutput: Bool) {
        busy = true
        setIcon(busy: true)
        rebuild()
        run(args) { code, out, err in
            self.busy = false
            self.setIcon(busy: false)
            let text = (out + err).trimmingCharacters(in: .whitespacesAndNewlines)
            if code != 0 { self.alert(L("That didn't work", "没有成功"), text) } else if showOutput { self.alert(title, text) }
            self.refresh()
        }
    }

    @objc func sessionClicked(_ sender: NSMenuItem) {
        guard let o = sender.representedObject as? [String: String], let from = o["from"], let id = o["id"] else { return }
        work([from == "codex" ? "to-claude" : "to-codex", id], title: "", showOutput: false)
    }

    @objc func updateNow() { if let l = release?.latest { install(l, announce: true) } }
    @objc func checkUpdate() { checkRelease(manual: true) }
    @objc func showDoctor() { work(["doctor"], title: L("ccx diagnostics", "ccx 诊断"), showOutput: true) }
    @objc func fixHook() { work(["setup"], title: L("ccx setup", "ccx 设置"), showOutput: true) }
    @objc func refreshClicked() { refresh() }
    @objc func openRepo() { NSWorkspace.shared.open(URL(string: repoURL)!) }

    @objc func setLanguage(_ sender: NSMenuItem) {
        defaults.set(sender.representedObject as? String ?? "en", forKey: "language")
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
