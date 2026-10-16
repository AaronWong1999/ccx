// ClaudeCodex menu bar app: one click to bring a session from Codex to Claude or back.
// All the work is done by the `ccx` command; this is only the clickable surface.

import AppKit
import ServiceManagement

struct Row: Decodable {
    let id: String
    let title: String
    let updated: String
    let status: String  // new | updated | synced | mirror
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
}

final class App: NSObject, NSApplicationDelegate, NSMenuDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let menu = NSMenu()
    var data: MenuData?
    var loading = false
    var busy = false
    var lastError: String?

    var ccx: String {
        if let p = Bundle.main.object(forInfoDictionaryKey: "CCXPath") as? String,
           FileManager.default.isExecutableFile(atPath: p) { return p }
        return NSHomeDirectory() + "/.local/bin/ccx"
    }

    func applicationDidFinishLaunching(_ n: Notification) {
        setIcon(busy: false)
        item.button?.toolTip = "ClaudeCodex：在 Claude 和 Codex 之间导入/同步会话"
        menu.delegate = self
        item.menu = menu
        rebuild()
        refresh()
        Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in self?.refresh() }
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in self?.refresh() }
    }

    func setIcon(busy: Bool) {
        let name = busy ? "arrow.triangle.2.circlepath" : "arrow.left.arrow.right.circle"
        let img = NSImage(systemSymbolName: name, accessibilityDescription: "ClaudeCodex")
        img?.isTemplate = true
        item.button?.image = img
    }

    // MARK: data

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
            self.rebuild()
            if CommandLine.arguments.contains("--selftest") { self.dump(self.menu, 0); exit(self.data == nil ? 1 : 0) }
        }
    }

    func dump(_ m: NSMenu, _ depth: Int) {
        let visible = self.item.button?.window?.isVisible ?? false
        if depth == 0 { print("status item visible: \(visible)") }
        for i in m.items {
            let t = i.isSeparatorItem ? "────" : (i.attributedTitle?.string ?? i.title)
            print(String(repeating: "  ", count: depth) + t + (i.isEnabled ? "" : "  [disabled]"))
            if let sub = i.submenu, depth == 0, m.items.firstIndex(of: i)! < 4 { dump(sub, depth + 1) }
        }
    }

    func menuWillOpen(_ m: NSMenu) { refresh() }

    // MARK: menu

    func rebuild() {
        menu.removeAllItems()
        let head = NSMenuItem(title: busy ? "正在导入…" : "选一个会话，拿到另一边继续", action: nil, keyEquivalent: "")
        head.isEnabled = false
        menu.addItem(head)
        menu.addItem(.separator())

        if let d = data {
            if d.projects.isEmpty { menu.addItem(disabled("没有找到 Claude / Codex 会话")) }
            for p in d.projects { menu.addItem(projectItem(p)) }
        } else {
            menu.addItem(disabled(lastError.map { "读取失败：\($0)" } ?? "正在读取会话…"))
        }

        menu.addItem(.separator())
        let legend = disabled("○ 未导入   ↻ 有更新，点一下同步   ✓ 已同步")
        menu.addItem(legend)
        menu.addItem(.separator())
        let login = NSMenuItem(title: "登录时自动启动", action: #selector(toggleLogin), keyEquivalent: "")
        login.target = self
        login.state = SMAppService.mainApp.status == .enabled ? .on : .off
        menu.addItem(login)
        let r = NSMenuItem(title: "刷新", action: #selector(refreshClicked), keyEquivalent: "r")
        r.target = self
        menu.addItem(r)
        let q = NSMenuItem(title: "退出 ClaudeCodex", action: #selector(NSApp.terminate), keyEquivalent: "q")
        menu.addItem(q)
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
        sub.addItem(section("拿到 Claude 继续 · 来自 Codex", p.codex.isEmpty))
        for r in p.codex { sub.addItem(sessionItem(r, from: "codex", cwd: p.cwd)) }
        sub.addItem(.separator())
        sub.addItem(section("拿到 Codex 继续 · 来自 Claude", p.claude.isEmpty))
        for r in p.claude { sub.addItem(sessionItem(r, from: "claude", cwd: p.cwd)) }
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

    func sessionItem(_ r: Row, from: String, cwd: String) -> NSMenuItem {
        let glyph = ["new": "○", "updated": "↻", "synced": "✓", "mirror": "·"][r.status] ?? "○"
        var title = r.title.count > 42 ? String(r.title.prefix(42)) + "…" : r.title
        if r.status == "mirror" { title += "（从对面导入的副本）" }
        let i = NSMenuItem(title: "", action: #selector(sessionClicked(_:)), keyEquivalent: "")
        i.target = self
        i.representedObject = ["from": from, "id": r.id, "cwd": cwd, "title": r.title]
        let s = NSMutableAttributedString(string: "\(glyph)  \(title)", attributes: [
            .font: NSFont.menuFont(ofSize: 0),
            .foregroundColor: r.status == "mirror" ? NSColor.secondaryLabelColor : NSColor.labelColor,
        ])
        s.append(NSAttributedString(string: "   \(r.updated)", attributes: [
            .font: NSFont.menuFont(ofSize: NSFont.smallSystemFontSize),
            .foregroundColor: NSColor.tertiaryLabelColor,
        ]))
        i.attributedTitle = s
        i.toolTip = r.status == "synced" ? "已同步：点一下直接打开" : (r.status == "updated" ? "对面有新内容：点一下同步并打开" : "点一下导入并打开")
        i.isEnabled = !busy
        return i
    }

    // MARK: actions

    @objc func sessionClicked(_ sender: NSMenuItem) {
        guard let o = sender.representedObject as? [String: String],
              let from = o["from"], let id = o["id"], let cwd = o["cwd"] else { return }
        busy = true
        setIcon(busy: true)
        rebuild()
        run(["-C", cwd, from == "codex" ? "to-claude" : "to-codex", id]) { code, out, err in
            self.busy = false
            self.setIcon(busy: false)
            if code != 0 {
                let a = NSAlert()
                a.messageText = "没导成"
                a.informativeText = (err + out).trimmingCharacters(in: .whitespacesAndNewlines)
                a.runModal()
            }
            self.refresh()
        }
    }

    @objc func refreshClicked() { refresh() }

    @objc func toggleLogin() {
        do {
            if SMAppService.mainApp.status == .enabled { try SMAppService.mainApp.unregister() }
            else { try SMAppService.mainApp.register() }
        } catch {
            let a = NSAlert()
            a.messageText = "设置登录启动失败"
            a.informativeText = error.localizedDescription
            a.runModal()
        }
        rebuild()
    }
}

let app = NSApplication.shared
let delegate = App()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
