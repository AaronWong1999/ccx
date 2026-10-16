// ccx menu bar app: one click to continue a session in the other app.
// All the work is done by the `ccx` command; this is only the clickable surface.

import AppKit

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

final class App: NSObject, NSApplicationDelegate, NSMenuDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let menu = NSMenu()
    var data: MenuData?
    var loading = false
    var busy = false
    var autostartOn = false
    var lastError: String?
    let defaults = UserDefaults.standard

    var ccx: String {
        if let p = Bundle.main.object(forInfoDictionaryKey: "CCXPath") as? String,
           FileManager.default.isExecutableFile(atPath: p) { return p }
        return NSHomeDirectory() + "/.local/bin/ccx"
    }

    func applicationDidFinishLaunching(_ n: Notification) {
        setIcon(busy: false)
        item.button?.toolTip = "ccx：在 Claude 和 Codex 之间接着干同一个任务"
        menu.delegate = self
        item.menu = menu
        rebuild()
        refresh()
        Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.refresh() }
        Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { [weak self] _ in self?.autoUpdate() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in self?.autoUpdate() }
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
                DispatchQueue.main.async { done(-1, "", "找不到 ccx：\(self.ccx)") }
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

    /// Once a day, quietly pull a new version (the plugins in both apps update too).
    func autoUpdate() {
        let last = defaults.double(forKey: "lastUpdateCheck")
        if Date().timeIntervalSince1970 - last < 86400 { return }
        defaults.set(Date().timeIntervalSince1970, forKey: "lastUpdateCheck")
        run(["update", "--quiet"]) { _, _, _ in self.refresh() }
    }

    func menuWillOpen(_ m: NSMenu) { refresh() }

    // MARK: menu

    func rebuild() {
        menu.removeAllItems()
        menu.addItem(disabled(busy ? "正在处理…" : "选一个会话，到另一边接着干"))
        menu.addItem(.separator())
        if let d = data {
            if d.projects.isEmpty { menu.addItem(disabled("还没有 Claude / Codex 会话")) }
            for p in d.projects { menu.addItem(projectItem(p)) }
            if d.codex_hook_trusted == false {
                menu.addItem(.separator())
                menu.addItem(action("让 Codex 也自动同步：去 Codex 信任 ccx 的 hook…", #selector(showHookHelp)))
            }
        } else {
            menu.addItem(disabled(lastError.map { "读取失败：\($0)" } ?? "正在读取会话…"))
        }
        menu.addItem(.separator())
        menu.addItem(disabled("○ 未关联   ✓ 已关联   ↻ 这边有新进展，对面还没收到"))
        menu.addItem(.separator())
        let login = action("登录时自动启动", #selector(toggleLogin))
        login.state = autostartOn ? .on : .off
        menu.addItem(login)
        menu.addItem(action("检查更新", #selector(checkUpdate)))
        menu.addItem(action("诊断…", #selector(showDoctor)))
        menu.addItem(action("刷新", #selector(refreshClicked), key: "r"))
        menu.addItem(disabled("ccx \(data?.version ?? "")"))
        menu.addItem(NSMenuItem(title: "退出 ccx", action: #selector(NSApp.terminate), keyEquivalent: "q"))
    }

    func action(_ t: String, _ sel: Selector, key: String = "") -> NSMenuItem {
        let i = NSMenuItem(title: t, action: sel, keyEquivalent: key)
        i.target = self
        i.isEnabled = !busy
        return i
    }

    func disabled(_ t: String) -> NSMenuItem {
        let i = NSMenuItem(title: t, action: nil, keyEquivalent: "")
        i.isEnabled = false
        return i
    }

    func projectItem(_ p: Project) -> NSMenuItem {
        let it = NSMenuItem(title: p.name, action: nil, keyEquivalent: "")
        it.image = NSImage(systemSymbolName: "folder", accessibilityDescription: nil)
        it.toolTip = p.cwd
        let sub = NSMenu()
        sub.addItem(section("到 Claude 接着干 · 来自 Codex", p.codex.isEmpty))
        for r in p.codex { sub.addItem(sessionItem(r, from: "codex")) }
        sub.addItem(.separator())
        sub.addItem(section("到 Codex 接着干 · 来自 Claude", p.claude.isEmpty))
        for r in p.claude { sub.addItem(sessionItem(r, from: "claude")) }
        it.submenu = sub
        return it
    }

    func section(_ t: String, _ empty: Bool) -> NSMenuItem {
        let i = disabled(empty ? "\(t)（无）" : t)
        i.attributedTitle = NSAttributedString(string: i.title, attributes: [
            .font: NSFont.boldSystemFont(ofSize: NSFont.smallSystemFontSize),
            .foregroundColor: NSColor.secondaryLabelColor,
        ])
        return i
    }

    func sessionItem(_ r: Row, from: String) -> NSMenuItem {
        let glyph = ["new": "○", "updated": "↻", "linked": "✓", "mirror": "·"][r.status] ?? "○"
        var title = r.title.count > 42 ? String(r.title.prefix(42)) + "…" : r.title
        if r.status == "mirror" { title += "（从对面导入的副本）" }
        let i = NSMenuItem(title: "", action: #selector(sessionClicked(_:)), keyEquivalent: "")
        i.target = self
        i.representedObject = ["from": from, "id": r.id]
        let s = NSMutableAttributedString(string: "\(glyph)  \(title)", attributes: [
            .font: NSFont.menuFont(ofSize: 0),
            .foregroundColor: r.status == "mirror" ? NSColor.secondaryLabelColor : NSColor.labelColor,
        ])
        s.append(NSAttributedString(string: "   \(r.updated)", attributes: [
            .font: NSFont.menuFont(ofSize: NSFont.smallSystemFontSize),
            .foregroundColor: NSColor.tertiaryLabelColor,
        ]))
        i.attributedTitle = s
        i.toolTip = (r.status == "new" || r.status == "mirror")
            ? "点一下：导入到另一边并打开，两边从此自动同步"
            : "已关联：点一下打开另一边的那个会话，在那边说一句话就会带上新进展"
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
            if code != 0 { self.alert("没成功", text) } else if showOutput { self.alert(title, text) }
            self.refresh()
        }
    }

    @objc func sessionClicked(_ sender: NSMenuItem) {
        guard let o = sender.representedObject as? [String: String], let from = o["from"], let id = o["id"] else { return }
        work([from == "codex" ? "to-claude" : "to-codex", id], title: "", showOutput: false)
    }

    @objc func checkUpdate() { work(["update"], title: "ccx 更新", showOutput: true) }
    @objc func showDoctor() { work(["doctor"], title: "ccx 诊断", showOutput: true) }
    @objc func refreshClicked() { refresh() }

    @objc func toggleLogin() {
        run(["autostart", autostartOn ? "off" : "on"]) { _, _, _ in self.refresh() }
    }

    @objc func showHookHelp() {
        alert("让 Codex 也自动同步",
              "Codex 要求你亲自信任一次第三方 hook：\n\nCodex 桌面版 → 设置 → Hooks → 找到 ccx → 信任\n（终端版 Codex：输入 /hooks）\n\n不信任也能用：在 Codex 里说「接着 Claude 继续」即可同步。")
    }

    func dump(_ m: NSMenu, _ depth: Int) {
        if depth == 0 { print("status item visible: \(item.button?.window?.isVisible ?? false)") }
        for (n, i) in m.items.enumerated() {
            let t = i.isSeparatorItem ? "────" : (i.attributedTitle?.string ?? i.title)
            print(String(repeating: "  ", count: depth) + t + (i.isEnabled ? "" : "  [disabled]"))
            if let sub = i.submenu, depth == 0, n < 4 { dump(sub, depth + 1) }
        }
    }
}

let app = NSApplication.shared
let delegate = App()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
