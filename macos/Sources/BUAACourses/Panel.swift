import SwiftUI

private let accent = Color(red: 0.12, green: 0.55, blue: 1)

struct WeekSlot: Identifiable {
    var id: String { lesson.id }
    let lesson: Lesson
    let start: Double
    let end: Double
    let lane: Int
    var columns: Int
}

enum WeekLayout {
    static func slots(_ lessons: [Lesson], day: Date) -> [WeekSlot] {
        let endDay = Clock.addDays(day, 1)
        let items = lessons.filter { $0.starts < endDay && $0.ends > day }.sorted { $0.starts < $1.starts }
        var output: [WeekSlot] = [], group: [WeekSlot] = [], laneEnds: [Double] = []
        func finish() {
            output += group.map { var s = $0; s.columns = laneEnds.count; return s }
            group = []; laneEnds = []
        }
        for item in items {
            let start = max(0, item.starts.timeIntervalSince(day) / 3600)
            let end = min(24, item.ends.timeIntervalSince(day) / 3600)
            if !group.isEmpty && start >= (laneEnds.max() ?? 0) { finish() }
            let lane = laneEnds.firstIndex(where: { $0 <= start }) ?? laneEnds.count
            if lane == laneEnds.count { laneEnds.append(end) } else { laneEnds[lane] = end }
            group.append(WeekSlot(lesson: item, start: start, end: end, lane: lane, columns: 1))
        }
        finish(); return output
    }
}

struct Panel: View {
    static func size(for store: Store) -> NSSize {
        let dayCount = ScheduleLayout.visibleDays(week: store.week, lessons: store.visibleLessons).count
        let width: CGFloat = store.todayMode ? 440 : 580 + CGFloat(dayCount - 5) * 80
        let rows = store.todayLessons.count
        let contentHeight: CGFloat = store.todayMode
            ? max(240, 128 + CGFloat(rows) * 96 + CGFloat(max(0, rows - 1)) * 8)
            : 600
        let height = min(contentHeight + (store.notice == nil ? 0 : 48), 600,
                         (NSScreen.main?.visibleFrame.height ?? 850) - 50)
        return NSSize(width: width, height: height)
    }
    @ObservedObject var store: Store
    @AppStorage("appearance") private var appearance = "dark"
    private var dark: Bool {
        if CommandLine.arguments.contains("--snapshot") {
            return !CommandLine.arguments.contains("--light-preview")
        }
        return appearance != "light"
    }
    private var ink: Color { dark ? .white : .black }
    private var muted: Color { ink.opacity(dark ? 0.45 : 0.55) }
    private var primary: Color { ink.opacity(dark ? 0.95 : 0.88) }
    private var blockText: Color { dark ? .white : Color(red: 0.08, green: 0.10, blue: 0.16) }
    private var card: Color { dark ? Color(red: 0.15, green: 0.15, blue: 0.17) : Color(red: 0.97, green: 0.97, blue: 0.98) }
    private var overlayColor: Color { dark ? Color(red: 0.105, green: 0.11, blue: 0.14) : Color(red: 0.97, green: 0.97, blue: 0.99) }
    private var backgroundColors: [Color] {
        dark ? [Color(red: 0.105, green: 0.11, blue: 0.13), Color(red: 0.075, green: 0.08, blue: 0.10)]
             : [Color(red: 0.96, green: 0.96, blue: 0.98), Color(red: 0.90, green: 0.91, blue: 0.94)]
    }
    @State private var selection: String? = CommandLine.arguments.contains("--detail-preview") ? "demo-2" : nil
    private let axis: CGFloat = 40
    private let hourHeight: CGFloat = 40
    private var days: [Date] { ScheduleLayout.visibleDays(week: store.week, lessons: store.visibleLessons) }
    private var startHour: Int { min(8, store.visibleLessons.map { Clock.calendar.component(.hour, from: $0.starts) }.min() ?? 8) }
    private var endHour: Int { min(24, max(18, store.visibleLessons.map { Int(ceil($0.ends.timeIntervalSince(Clock.calendar.startOfDay(for: $0.ends)) / 3600)) }.max() ?? 18)) }
    private var selected: Lesson? { store.visibleLessons.first { $0.id == selection } }
    private var columnWidth: CGFloat { (Self.size(for: store).width - 30 - axis) / CGFloat(days.count) }
    var body: some View {
        VStack(spacing: 10) {
            header
            if store.todayMode { todayHeading } else { weekNavigation }
            if let notice = store.notice { banner(notice, error: store.failed) }
            if store.todayMode { todayList } else {
                calendar
                if let selected { detail(selected) }
            }
            footer
        }
        .padding(15).frame(width: Self.size(for: store).width, height: Self.size(for: store).height)
        .background(LinearGradient(colors: backgroundColors, startPoint: .topLeading, endPoint: .bottomTrailing))
        .foregroundColor(primary)
        .environment(\.colorScheme, dark ? .dark : .light)
        .sheet(isPresented: $store.credentialsOpen) { Credentials(store: store, dark: dark) }
    }
    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "graduationcap.fill").font(.system(size: 15)).foregroundStyle(accent)
            Text("北航课表").font(.system(size: 15, weight: .bold, design: .rounded))
            Spacer()
            HStack(spacing: 2) {
                modeButton("今日", selected: store.todayMode) { store.todayMode = true }
                modeButton("周", selected: !store.todayMode) { store.todayMode = false }
            }.padding(2).background(ink.opacity(0.045), in: RoundedRectangle(cornerRadius: 7))
            Button { selection = nil; if store.todayMode { store.refreshToday() } else { store.refresh() } } label: {
                ZStack {
                    if store.busy && store.signing == nil { ProgressView().controlSize(.mini) }
                    else { Image(systemName: "arrow.clockwise") }
                }.font(.system(size: 11, weight: .medium)).frame(width: 24, height: 24)
            }.buttonStyle(.plain).disabled(store.busy)
                .help(store.todayMode ? "刷新今日" : "更新学期课表")
                .accessibilityLabel(store.todayMode ? "刷新今日" : "更新学期课表")
            Button { appearance = dark ? "light" : "dark" } label: {
                Image(systemName: dark ? "sun.max" : "moon").font(.system(size: 11)).frame(width: 24, height: 24)
            }.buttonStyle(.plain).foregroundStyle(muted)
                .help(dark ? "切换浅色主题" : "切换深色主题")
                .accessibilityLabel(dark ? "切换浅色主题" : "切换深色主题")
            Button { store.openConfig() } label: {
                Image(systemName: "gearshape").font(.system(size: 11)).frame(width: 24, height: 24)
            }.buttonStyle(.plain).foregroundStyle(muted).help("账号设置").accessibilityLabel("账号设置")
        }
    }
    private func modeButton(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button { selection = nil; store.now = Date(); action() } label: {
            Text(title).font(.system(size: 11, weight: .medium)).frame(width: 32, height: 22)
                .foregroundStyle(selected ? primary : muted)
                .background(selected ? ink.opacity(0.09) : .clear, in: RoundedRectangle(cornerRadius: 5))
        }.buttonStyle(.plain).accessibilityLabel(title == "周" ? "周课表" : "今日课表")
            .accessibilityAddTraits(selected ? .isSelected : [])
    }
    private var todayHeading: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(Clock.format(store.now, "M月d日 EEEE")).font(.system(size: 16, weight: .semibold, design: .rounded))
            Spacer()
            if store.todayLoaded && !store.todayLessons.isEmpty { Text("\(store.todayLessons.count) 节课").font(.system(size: 10)).foregroundStyle(muted) }
        }
    }
    private var todayList: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 8) {
                if !store.todayLoaded || store.todayLessons.isEmpty {
                    VStack(spacing: 10) {
                        Image(systemName: "calendar").font(.system(size: 22)).foregroundStyle(muted)
                        Text(store.todayLoaded ? "今天没有课程" : (store.busy ? "加载中…" : "暂无课表"))
                            .font(.system(size: 12)).foregroundStyle(muted)
                    }.frame(maxWidth: .infinity).padding(.vertical, 26)
                }
                ForEach(store.todayLessons) { item in
                    HStack(spacing: 10) {
                        VStack(alignment: .leading, spacing: 5) {
                            Text(Clock.time(item.starts)).font(.system(size: 18, weight: .semibold, design: .rounded)).monospacedDigit().lineLimit(1).fixedSize()
                            Text(Clock.time(item.ends)).font(.system(size: 10, design: .monospaced)).foregroundStyle(muted)
                        }.frame(width: 60, alignment: .leading)
                        RoundedRectangle(cornerRadius: 2).fill(tint(item)).frame(width: 3)
                        VStack(alignment: .leading, spacing: 5) {
                            Text(item.name).font(.system(size: 13, weight: .semibold)).lineLimit(2)
                            if !item.classroom.isEmpty { Text(item.classroom).font(.system(size: 10)).foregroundStyle(muted).lineLimit(1) }
                            if !item.teacher.isEmpty { Text(item.teacher).font(.system(size: 10)).foregroundStyle(muted).lineLimit(1) }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                        attendance(item)
                    }.padding(13).frame(height: 96)
                        .help("\(item.name)\n\(item.time)\n\(item.classroom)\n\(item.teacher)")
                        .background(card, in: RoundedRectangle(cornerRadius: 14))
                        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(ink.opacity(0.07), lineWidth: 0.5))
                }
            }
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }
    private var weekNavigation: some View {
        HStack(spacing: 10) {
            Text(Clock.format(store.week, "yyyy 年 M 月"))
                .font(.system(size: 16, weight: .semibold, design: .rounded))
            Text("\(Clock.format(store.week, "M.d")) – \(Clock.format(Clock.addDays(store.week, 6), "M.d"))")
                .font(.system(size: 11, design: .monospaced)).foregroundStyle(muted)
            Spacer()
            Button { selection = nil; store.moveWeek(-1) } label: { Image(systemName: "chevron.left").frame(width: 24, height: 24) }.help("上一周").accessibilityLabel("上一周")
            Button("本周") { selection = nil; store.week = Clock.monday(Date()); store.now = Date(); store.notice = nil }
            Button { selection = nil; store.moveWeek(1) } label: { Image(systemName: "chevron.right").frame(width: 24, height: 24) }.help("下一周").accessibilityLabel("下一周")
        }.buttonStyle(.plain).font(.system(size: 11)).disabled(store.busy)
    }
    private var calendar: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                Color.clear.frame(width: axis)
                ForEach(days, id: \.self) { day in
                    let today = Clock.day(day) == Clock.day(store.now)
                    VStack(spacing: 3) {
                        Text(Clock.format(day, "EEEEE")).font(.system(size: 10)).foregroundStyle(muted)
                        Text(Clock.format(day, "d")).font(.system(size: 13, weight: .semibold, design: .rounded))
                            .foregroundStyle(today ? Color.white : primary).frame(width: 24, height: 24).background(today ? accent : .clear, in: RoundedRectangle(cornerRadius: 7))
                    }.frame(width: columnWidth).padding(.vertical, 7)
                }
            }.frame(height: 54)
            Rectangle().fill(ink.opacity(0.10)).frame(height: 0.5)
            ScrollView(.vertical, showsIndicators: true) {
                HStack(alignment: .top, spacing: 0) {
                    ZStack(alignment: .topLeading) {
                        ForEach(startHour..<endHour, id: \.self) { hour in
                            Text(String(format: "%02d:00", hour)).font(.system(size: 9, design: .monospaced)).foregroundStyle(muted)
                                .offset(x: 3, y: CGFloat(hour - startHour) * hourHeight + 5)
                        }
                    }.frame(width: axis, height: CGFloat(endHour - startHour) * hourHeight, alignment: .topLeading)
                    ForEach(days, id: \.self) { day in dayColumn(day) }
                }
            }.overlay {
                if store.stale {
                    Button { store.refresh() } label: {
                        Label(store.busy ? "更新中…" : "加载学期课表", systemImage: "arrow.clockwise")
                            .font(.system(size: 12, weight: .medium)).padding(16)
                    }.buttonStyle(.plain).foregroundStyle(accent).disabled(store.busy)
                        .background(overlayColor.opacity(0.97), in: RoundedRectangle(cornerRadius: 12))
                } else if store.visibleLessons.isEmpty {
                    Text("这周没有课程").font(.system(size: 12)).padding(16)
                        .background(overlayColor.opacity(0.97), in: RoundedRectangle(cornerRadius: 12))
                }
            }
        }.background(dark ? ink.opacity(0.02) : Color.white.opacity(0.45), in: RoundedRectangle(cornerRadius: 14))
            .clipShape(RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(ink.opacity(0.075), lineWidth: 0.5))
    }
    private func dayColumn(_ day: Date) -> some View {
        let height = CGFloat(endHour - startHour) * hourHeight
        return ZStack(alignment: .topLeading) {
            if Clock.day(day) == Clock.day(store.now) { accent.opacity(0.035) }
            ForEach(startHour..<endHour, id: \.self) { hour in
                Rectangle().fill(ink.opacity(0.06)).frame(height: 0.5).offset(y: CGFloat(hour - startHour) * hourHeight)
            }
            Rectangle().fill(ink.opacity(0.06)).frame(width: 0.5)
            ForEach(WeekLayout.slots(store.visibleLessons, day: day)) { slot in
                let width = (columnWidth - 4) / CGFloat(slot.columns)
                block(slot.lesson, height: max(24, CGFloat(slot.end - slot.start) * hourHeight - 3))
                    .frame(width: width - 2)
                    .offset(x: 3 + CGFloat(slot.lane) * width, y: CGFloat(slot.start - Double(startHour)) * hourHeight + 2)
            }
        }.frame(width: columnWidth, height: height).clipped()
    }
    private func tint(_ lesson: Lesson) -> Color {
        let palette: [Color] = [Color(red: 0.94, green: 0.30, blue: 0.43), Color(red: 0.51, green: 0.35, blue: 0.89), Color(red: 0.04, green: 0.66, blue: 0.60), Color(red: 0.93, green: 0.52, blue: 0.15), Color(red: 0.27, green: 0.51, blue: 0.88)]
        let hash = lesson.name.unicodeScalars.reduce(0) { ($0 &* 31 &+ Int($1.value)) & 0x7fffffff }
        return palette[hash % palette.count]
    }
    private func block(_ lesson: Lesson, height: CGFloat) -> some View {
        let color = tint(lesson)
        return Button { selection = lesson.id; store.now = Date() } label: {
            VStack(alignment: .leading, spacing: 3) {
                Text(lesson.name).font(.system(size: 11, weight: .semibold)).lineLimit(height > 130 ? 5 : (height < 40 ? 1 : 2))
                    .fixedSize(horizontal: false, vertical: true)
                if height >= 54 && !lesson.classroom.isEmpty {
                    Text(lesson.classroom).font(.system(size: 10)).foregroundStyle(blockText.opacity(0.8)).lineLimit(height > 130 ? 3 : 1)
                }
                Spacer(minLength: 0)
                if height > 82 {
                    if lesson.signed == true { Label("已签到", systemImage: "checkmark.circle.fill").font(.system(size: 9)) }
                    else if lesson.available(store.now) { Text("可签到").font(.system(size: 9, weight: .semibold)) }
                    else { Text(Clock.time(lesson.starts)).font(.system(size: 9, design: .monospaced)).foregroundStyle(blockText.opacity(0.75)) }
                }
            }.foregroundStyle(blockText).frame(maxWidth: .infinity, alignment: .leading).padding(7).frame(height: height)
                .background(color.opacity(dark ? (lesson.ends < store.now ? 0.38 : 0.58) : (lesson.ends < store.now ? 0.18 : 0.30)), in: RoundedRectangle(cornerRadius: 7))
                .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(selection == lesson.id ? primary : color.opacity(0.65), lineWidth: selection == lesson.id ? 1.5 : 0.5))
                .clipped().contentShape(Rectangle())
        }.buttonStyle(.plain).help("\(lesson.name)\n\(lesson.time)\n\(lesson.classroom)")
    }
    private func detail(_ item: Lesson) -> some View {
        HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 3).fill(tint(item)).frame(width: 4)
            VStack(alignment: .leading, spacing: 5) {
                Text(item.name).font(.system(size: 13, weight: .semibold)).lineLimit(2)
                Text([Clock.format(item.starts, "M月d日 EEEE"), item.time, item.classroom].filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(.system(size: 10)).foregroundStyle(muted)
                if !item.teacher.isEmpty { Text(item.teacher).font(.system(size: 10)).foregroundStyle(muted) }
            }
            Spacer(minLength: 5)
            attendance(item)
            Button { selection = nil } label: { Image(systemName: "xmark").font(.system(size: 10)).foregroundStyle(muted).frame(width: 20, height: 24) }
                .buttonStyle(.plain).accessibilityLabel("关闭详情")
        }.padding(12).frame(height: 84).background(card, in: RoundedRectangle(cornerRadius: 12))
    }
    @ViewBuilder private func attendance(_ item: Lesson) -> some View {
        if item.available(store.now) || store.signing == item.id {
            Button { store.sign(item) } label: {
                HStack(spacing: 5) {
                    if store.signing == item.id { ProgressView().controlSize(.mini) }
                    Text(store.signing == item.id ? "签到中" : "签到")
                }.font(.system(size: 11, weight: .semibold)).padding(.horizontal, 12).padding(.vertical, 7)
                    .foregroundStyle(Color.white).background(accent, in: RoundedRectangle(cornerRadius: 7))
            }.buttonStyle(.plain).disabled(store.busy || !item.available(store.now))
        } else {
            Text(item.signed == true ? "已签到" : (item.signed == nil ? "待确认" : (item.ends <= store.now ? "未签到" : "未开始")))
                .font(.system(size: 10, weight: .medium)).foregroundStyle(item.signed == true ? .green : muted)
                .fixedSize()
        }
    }
    private func banner(_ message: String, error: Bool) -> some View {
        HStack(spacing: 6) {
            Image(systemName: error ? "exclamationmark.circle" : "checkmark.circle").foregroundStyle(error ? .orange : .green)
            Text(message).fixedSize(horizontal: false, vertical: true)
            Spacer()
        }.font(.system(size: 11)).foregroundStyle(ink.opacity(0.7)).padding(9)
            .background((error ? Color.orange : .green).opacity(0.07), in: RoundedRectangle(cornerRadius: 8))
    }
    private var footer: some View {
        HStack(spacing: 12) {
            Text(store.todayMode ? store.lastUpdate : store.semesterUpdateLabel).font(.system(size: 10)).foregroundStyle(muted)
            Spacer()
            Button { NSApp.terminate(nil) } label: { Image(systemName: "power").frame(width: 24, height: 20) }.help("退出").accessibilityLabel("退出")
        }.font(.system(size: 11)).buttonStyle(.plain).foregroundStyle(muted)
    }
}
struct Credentials: View {
    @ObservedObject var store: Store
    var dark = true
    @State private var number = ""
    @State private var password = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("登录北航 iClass").font(.system(size: 15, weight: .semibold))
            if store.needs.contains("student_number") { TextField("学号", text: $number) }
            if store.needs.contains("password") { SecureField("统一认证密码", text: $password) }
            Text("本次输入仅用于当前运行，不写入配置文件。").font(.system(size: 10)).foregroundStyle(.secondary)
            HStack {
                Button("取消") { store.credentialsOpen = false }
                Spacer()
                Button("继续") { store.provide(number: number, password: password); password = "" }
                    .buttonStyle(.borderedProminent).tint(accent)
                    .disabled((store.needs.contains("student_number") && number.trimmingCharacters(in: .whitespaces).isEmpty) || (store.needs.contains("password") && password.isEmpty))
            }
        }.textFieldStyle(.roundedBorder).padding(24).frame(width: 340)
            .environment(\.colorScheme, dark ? .dark : .light)
    }
}
