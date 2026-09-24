import Foundation
func assertEqual<T: Equatable>(_ actual: T, _ expected: T, file: StaticString = #file, line: UInt = #line) {
    precondition(actual == expected, "Expected \(expected), received \(actual)", file: file, line: line)
}

final class ScheduleLayoutTests {
    private func date(_ value: String) -> Date {
        ISO8601DateFormatter().date(from: value + "+08:00")!
    }

    private func lesson(_ start: String, _ end: String) -> Lesson {
        Lesson(id: start, name: "课程", teacher: "", classroom: "",
               start: start + "+08:00", end: end + "+08:00", signed: false)
    }

    private func days(_ lessons: [Lesson], week: String = "2026-09-14T00:00:00") -> [String] {
        ScheduleLayout.visibleDays(week: date(week), lessons: lessons).map(Clock.day)
    }

    private let weekdays = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]

    func testWeekdaysRemainWithoutLessons() {
        assertEqual(days([]), weekdays)
        assertEqual(days([lesson("2026-09-15T09:00:00", "2026-09-15T10:00:00")]), weekdays)
    }

    func testWeekendDaysAreIncludedIndependently() {
        let saturday = lesson("2026-09-19T09:00:00", "2026-09-19T10:00:00")
        let sunday = lesson("2026-09-20T09:00:00", "2026-09-20T10:00:00")
        assertEqual(days([saturday]), weekdays + ["2026-09-19"])
        assertEqual(days([sunday]), weekdays + ["2026-09-20"])
        assertEqual(days([saturday, sunday]), weekdays + ["2026-09-19", "2026-09-20"])
    }

    func testMidnightEndDoesNotIncludeFollowingDay() {
        assertEqual(days([lesson("2026-09-18T23:00:00", "2026-09-19T00:00:00")]), weekdays)
        assertEqual(days([lesson("2026-09-19T23:00:00", "2026-09-20T00:00:00")]), weekdays + ["2026-09-19"])
        assertEqual(days([lesson("2026-09-19T23:00:00", "2026-09-20T01:00:00")]), weekdays + ["2026-09-19", "2026-09-20"])
    }

    func testWeekSwitchUsesOnlyIntersectingLessons() {
        let lessons = [lesson("2026-09-20T23:00:00", "2026-09-21T01:00:00")]
        assertEqual(days(lessons), weekdays + ["2026-09-20"])
        assertEqual(days(lessons, week: "2026-09-23T15:00:00"),
                       ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"])
    }

    func testInvalidDurationsDoNotRevealWeekend() {
        assertEqual(days([
            lesson("2026-09-19T10:00:00", "2026-09-19T10:00:00"),
            lesson("2026-09-20T11:00:00", "2026-09-20T10:00:00"),
            lesson("invalid", "invalid")
        ]), weekdays)
    }
}

@main enum Check {
    static func main() {
        let tests = ScheduleLayoutTests()
        tests.testWeekdaysRemainWithoutLessons()
        tests.testWeekendDaysAreIncludedIndependently()
        tests.testMidnightEndDoesNotIncludeFollowingDay()
        tests.testWeekSwitchUsesOnlyIntersectingLessons()
        tests.testInvalidDurationsDoNotRevealWeekend()
        print("All 5 ScheduleLayout test cases passed")
    }
}
