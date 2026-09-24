import Foundation

enum ScheduleLayout {
    static func visibleDays(week: Date, lessons: [Lesson]) -> [Date] {
        let monday = Clock.monday(week)
        return (0..<7).compactMap { offset in
            let day = Clock.addDays(monday, offset)
            guard offset >= 5 else { return day }
            let nextDay = Clock.addDays(day, 1)
            return lessons.contains {
                $0.starts < $0.ends && $0.starts < nextDay && $0.ends > day
            } ? day : nil
        }
    }
}
