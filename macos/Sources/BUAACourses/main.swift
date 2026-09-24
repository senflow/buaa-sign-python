import AppKit
import Combine
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    let store = Store()
    var item: NSStatusItem!
    let popover = NSPopover()
    private var sizeObservation: AnyCancellable?
    func applicationDidFinishLaunching(_ notification: Notification) {
        if CommandLine.arguments.contains("--bridge-check") {
            store.bridge.request(["action": "snapshot"]) { result in
                switch result {
                case .success(let reply):
                    print(reply.ok && reply.courses?.isEmpty == true ? "BRIDGE OK: no network, empty initial snapshot" : "BRIDGE FAILED")
                case .failure(let error): print("BRIDGE FAILED: \(error.localizedDescription)")
                }
                NSApp.terminate(nil)
            }
            return
        }
        if let index = CommandLine.arguments.firstIndex(of: "--snapshot"), CommandLine.arguments.count > index + 1 {
            snapshot(to: CommandLine.arguments[index + 1]); return
        }
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let b = item.button {
            b.image = NSImage(systemSymbolName: "graduationcap", accessibilityDescription: "北航课表")
            b.imagePosition = .imageOnly; b.title = ""
            b.target = self; b.action = #selector(toggle)
            b.toolTip = nil
        }
        popover.behavior = .transient
        popover.contentSize = Panel.size(for: store)
        popover.contentViewController = NSHostingController(rootView: Panel(store: store))
        sizeObservation = store.objectWillChange.sink { [weak self] in
            // Published values update after objectWillChange; size from the new state.
            DispatchQueue.main.async { self?.resizePopover() }
        }
        // Refresh today when the user opens the panel; no timer or polling.
        if CommandLine.arguments.contains("--show") { toggle() }
    }
    private func resizePopover() {
        let size = Panel.size(for: store)
        if popover.contentSize != size { popover.contentSize = size }
    }
    @objc func toggle() {
        if popover.isShown { popover.performClose(nil) }
        else if let button = item.button {
            store.now = Date()
            store.todayMode = true
            resizePopover()
            NSApp.activate(ignoringOtherApps: true)
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
            store.refreshToday()
        }
    }
    func applicationWillTerminate(_ notification: Notification) { store.bridge.stop() }
    private func snapshot(to path: String) {
        // Visual QA fixture only. This code never authenticates or submits attendance.
        store.todayMode = CommandLine.arguments.contains("--today-preview")
        let now = Clock.calendar.date(bySettingHour: 16, minute: 10, second: 0, of: store.week)!
        store.now = now; store.day = Clock.day(now); store.loadedWeek = Clock.day(store.week)
        store.updated = ISO8601DateFormatter().string(from: now)
        store.semesterUpdated = store.updated
        let f = ISO8601DateFormatter()
        func sample(_ id: String, _ name: String, _ day: Int, _ hour: Int, _ minute: Int, _ duration: Int, _ room: String, _ signed: Bool = false) -> Lesson {
            let start = Clock.calendar.date(bySettingHour: hour, minute: minute, second: 0, of: Clock.addDays(store.week, day))!
            return Lesson(id: id, name: name, teacher: "示例教师", classroom: room, start: f.string(from: start), end: f.string(from: start.addingTimeInterval(Double(duration * 60))), signed: signed)
        }
        store.lessons = [
            sample("demo-1", "矩阵理论与应用 I", 0, 9, 50, 95, "主 M101", true),
            sample("demo-2", "并行处理与体系结构", 0, 15, 50, 145, "G101"),
            sample("demo-3", "中国式现代化的理论与实践", 1, 8, 50, 205, "(三)409"),
            sample("demo-4", "软件开发方法", 1, 15, 50, 145, "(三)304"),
            sample("demo-5", "机器学习", 1, 19, 0, 95, "教学楼 201"),
            sample("demo-6", "马克思主义与当代科技", 2, 9, 50, 95, "(三)409"),
            sample("demo-7", "深度学习基础与应用", 3, 9, 50, 145, "B202"),
            sample("demo-8", "矩阵理论与应用 I", 3, 15, 50, 95, "主 M101")
        ]
        if CommandLine.arguments.contains("--weekend-preview") {
            store.lessons.append(sample("demo-9", "周六实验课", 5, 10, 0, 120, "实验楼 301"))
        }
        if CommandLine.arguments.contains("--sunday-preview") {
            store.lessons.append(sample("demo-10", "周日研讨课", 6, 14, 0, 120, "主 M101"))
        }
        if CommandLine.arguments.contains("--empty-preview") { store.lessons = [] }
        if CommandLine.arguments.contains("--many-preview") {
            store.lessons += (0..<5).map { sample("extra-\($0)", "课程名称较长的示例课程与应用实践", 0, 8 + $0 * 2, 0, 95, "教学楼 A 座 101", true) }
        }
        let size = Panel.size(for: store)
        let view = NSHostingView(rootView: Panel(store: store))
        let window = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: .borderless, backing: .buffered, defer: false)
        window.contentView = view; window.orderFrontRegardless()
        view.frame = NSRect(origin: .zero, size: size)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            view.layoutSubtreeIfNeeded()
            if let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) {
                view.cacheDisplay(in: view.bounds, to: rep)
                try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
            }
            NSApp.terminate(nil)
        }
    }
}
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
