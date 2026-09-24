import AppKit
import SwiftUI

struct Lesson: Codable, Identifiable {
    let id: String
    let name: String
    let teacher: String
    let classroom: String
    let start: String
    let end: String
    var signed: Bool?
    let starts: Date
    let ends: Date
    enum CodingKeys: String, CodingKey { case id, name, teacher, classroom, start, end, signed }
    init(id: String, name: String, teacher: String, classroom: String, start: String, end: String, signed: Bool?) {
        self.id = id; self.name = name; self.teacher = teacher; self.classroom = classroom
        self.start = start; self.end = end; self.signed = signed
        let formatter = ISO8601DateFormatter()
        self.starts = formatter.date(from: start) ?? .distantFuture
        self.ends = formatter.date(from: end) ?? .distantPast
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(id: try c.decode(String.self, forKey: .id), name: try c.decode(String.self, forKey: .name),
                  teacher: try c.decode(String.self, forKey: .teacher), classroom: try c.decode(String.self, forKey: .classroom),
                  start: try c.decode(String.self, forKey: .start), end: try c.decode(String.self, forKey: .end),
                  signed: try c.decodeIfPresent(Bool.self, forKey: .signed))
    }
    func available(_ now: Date) -> Bool { signed == false && starts.addingTimeInterval(-600) <= now && now < ends }
    var time: String { "\(Clock.time(starts)) – \(Clock.time(ends))" }
}
struct Reply: Decodable {
    let ok: Bool
    let network: String?
    let date: String?
    let updated: String?
    let week_start: String?
    let term: String?
    let semester_updated: String?
    let cache_warning: String?
    let courses: [Lesson]?
    let message: String?
    let needs_credentials: [String]?
    let sign_status: String?
}
enum Clock {
    private static var formatters: [String: DateFormatter] = [:]
    private static let lock = NSLock()
    static func format(_ date: Date, _ pattern: String) -> String {
        lock.lock(); defer { lock.unlock() }
        let formatter: DateFormatter
        if let cached = formatters[pattern] { formatter = cached }
        else {
            let f = DateFormatter(); f.timeZone = TimeZone(identifier: "Asia/Shanghai")
            f.locale = Locale(identifier: "zh_CN"); f.dateFormat = pattern
            formatters[pattern] = f; formatter = f
        }
        return formatter.string(from: date)
    }
    static let calendar: Calendar = {
        var c = Calendar(identifier: .gregorian); c.timeZone = TimeZone(identifier: "Asia/Shanghai")!; c.firstWeekday = 2; return c
    }()
    static func monday(_ date: Date) -> Date {
        let c = calendar; let offset = (c.component(.weekday, from: date) + 5) % 7
        return c.date(byAdding: .day, value: -offset, to: c.startOfDay(for: date))!
    }
    static func addDays(_ date: Date, _ count: Int) -> Date { calendar.date(byAdding: .day, value: count, to: date)! }
    static func day(_ date: Date) -> String { format(date, "yyyy-MM-dd") }
    static func time(_ date: Date) -> String { format(date, "HH:mm") }
}

final class Bridge {
    private let queue = DispatchQueue(label: "cn.buaa.courses.backend")
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    let config: String
    private let python: String
    private let backend: String
    init() {
        let info = Bundle.main.infoDictionary ?? [:]
        config = info["BUAAConfigPath"] as? String ?? ""
        python = info["BUAAPythonPath"] as? String ?? "/opt/homebrew/bin/python3"
        backend = Bundle.main.resourceURL?.appendingPathComponent("backend").path ?? ""
    }
    func stop() { process?.terminate() }
    func request(_ payload: [String: String], completion: @escaping (Result<Reply, Error>) -> Void) {
        queue.async {
            do {
                if self.process?.isRunning != true {
                    let p = Process(); p.executableURL = URL(fileURLWithPath: self.python)
                    p.arguments = ["-u", "-m", "buaa_sign.desktop", "--config", self.config]
                    p.currentDirectoryURL = URL(fileURLWithPath: self.backend)
                    var env = ProcessInfo.processInfo.environment
                    env["PYTHONPATH"] = self.backend; env["PYTHONDONTWRITEBYTECODE"] = "1"
                    p.environment = env
                    let stdin = Pipe(), stdout = Pipe()
                    p.standardInput = stdin; p.standardOutput = stdout; p.standardError = FileHandle.nullDevice
                    try p.run(); self.process = p
                    self.input = stdin.fileHandleForWriting; self.output = stdout.fileHandleForReading
                }
                var bytes = try JSONSerialization.data(withJSONObject: payload); bytes.append(10)
                try self.input?.write(contentsOf: bytes)
                var response = Data()
                while !response.contains(10) {
                    guard let data = self.output?.availableData, !data.isEmpty else {
                        throw NSError(domain: "BUAA", code: 1, userInfo: [NSLocalizedDescriptionKey: "后台进程已退出。如已提交签到，请核对考勤记录；可手动刷新重试。"])
                    }
                    response.append(data)
                }
                let reply = try JSONDecoder().decode(Reply.self, from: response)
                DispatchQueue.main.async { completion(.success(reply)) }
            } catch {
                self.process?.terminate(); self.process = nil
                DispatchQueue.main.async { completion(.failure(error)) }
            }
        }
    }
}

final class Store: ObservableObject {
    @Published var network = "direct"
    @Published var lessons: [Lesson] = [] { didSet { rebuildWeek() } }
    @Published var todayMode = true
    @Published var day: String?
    @Published var week = Clock.monday(Date()) { didSet { rebuildWeek() } }
    @Published var loadedWeek: String?
    @Published var term: String?
    @Published var semesterUpdated: String?
    @Published var updated: String?
    @Published var busy = false
    @Published var signing: String?
    @Published var notice: String?
    @Published var failed = false
    @Published var needs: [String] = []
    @Published var credentialsOpen = false
    @Published var now = Date()
    let bridge = Bridge()
    var pending: [String: String] = [:]
    var onChange: (() -> Void)?
    var stale: Bool { term == nil && loadedWeek != Clock.day(week) }
    private var weekRows: [Lesson] = []
    private func rebuildWeek() {
        let end = Clock.addDays(week, 7)
        weekRows = lessons.filter { $0.starts < end && $0.ends > week }
    }
    var visibleLessons: [Lesson] { stale ? [] : weekRows }
    func moveWeek(_ offset: Int) { week = Clock.addDays(week, offset * 7); now = Date(); notice = nil }
    var available: [Lesson] { stale ? [] : lessons.filter { $0.available(now) } }
    var done: Int { lessons.filter { $0.signed == true }.count }
    var semesterUpdateLabel: String {
        guard let timestamp = semesterUpdated else { return "学期尚未缓存" }
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = f.date(from: timestamp) ?? ISO8601DateFormatter().date(from: timestamp) else { return "学期已缓存" }
        return "学期缓存 " + Clock.format(date, "M.d HH:mm")
    }
    var lastUpdate: String {
        guard let updated else { return "尚未刷新" }
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = f.date(from: updated) ?? ISO8601DateFormatter().date(from: updated)
        return date.map { "课表更新于 " + Clock.time($0) } ?? "已更新"
    }
    var todayLoaded: Bool { if term != nil { return true }; if let loadedWeek { return loadedWeek == Clock.day(Clock.monday(now)) }; return day == Clock.day(now) }
    var todayLessons: [Lesson] {
        guard todayLoaded else { return [] }
        let begin = Clock.calendar.startOfDay(for: now), end = Clock.addDays(Clock.calendar.startOfDay(for: now), 1)
        return lessons.filter { $0.starts >= begin && $0.starts < end }.sorted { $0.starts < $1.starts }
    }
    func refreshToday() { send(["action": "refresh"]) }
    func setNetwork(_ mode: String) { send(["action": "set_network", "network": mode]) }
    func refresh() { send(["action": "refresh_semester"]) }
    func sign(_ item: Lesson) { send(["action": "sign", "id": item.id]) }
    func send(_ request: [String: String]) {
        guard !busy else { return }
        pending = request; busy = true; signing = request["id"]; notice = nil; now = Date()
        bridge.request(request) { [weak self] result in
            guard let self else { return }
            self.busy = false; self.signing = nil; self.now = Date()
            switch result {
            case .success(let reply):
                self.network = reply.network ?? self.network
                self.lessons = reply.courses ?? self.lessons
                self.day = reply.date; self.updated = reply.updated; self.loadedWeek = reply.week_start; self.term = reply.term; self.semesterUpdated = reply.semester_updated
                self.failed = !reply.ok
                self.notice = reply.cache_warning ?? ((!reply.ok || request["action"] == "sign") ? reply.message : nil)
                if let missing = reply.needs_credentials, !missing.isEmpty {
                    self.needs = missing; self.credentialsOpen = true
                }
            case .failure(let error):
                self.failed = true; self.notice = error.localizedDescription
            }
            self.onChange?()
        }
    }
    func provide(number: String, password: String) {
        var request = pending
        if needs.contains("student_number") { request["student_number"] = number }
        if needs.contains("password") { request["password"] = password }
        credentialsOpen = false; send(request)
        // Clear request credentials once handed off; backend retains them in memory only.
        pending = pending.filter { !["student_number", "password"].contains($0.key) }
    }
    func openConfig() {
        let url = URL(fileURLWithPath: bridge.config)
        if !FileManager.default.fileExists(atPath: url.path) {
            let data = Data("{\n  \"student_number\": \"\",\n  \"password\": \"\",\n  \"timeout\": 15\n}\n".utf8)
            do { try data.write(to: url, options: .atomic)
                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
            } catch { failed = true; notice = "无法创建配置文件：\(error.localizedDescription)"; return }
        }
        NSWorkspace.shared.open([url], withApplicationAt: URL(fileURLWithPath: "/System/Applications/TextEdit.app"), configuration: NSWorkspace.OpenConfiguration())
    }
}
