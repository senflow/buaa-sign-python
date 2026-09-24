#!/bin/sh
set -eu

macos_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/buaa-schedule-layout.XXXXXX")
trap 'rm -rf "$test_dir"' EXIT HUP INT TERM

swiftc \
    "$macos_dir/Sources/BUAACourses/Model.swift" \
    "$macos_dir/Sources/BUAACourses/ScheduleLayout.swift" \
    "$macos_dir/Tests/BUAACoursesTests/ScheduleLayoutTests.swift" \
    -o "$test_dir/check-schedule-layout"
"$test_dir/check-schedule-layout"
