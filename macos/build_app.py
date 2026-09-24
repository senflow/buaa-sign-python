#!/usr/bin/env python3
"""Build a local app, keeping credentials outside the bundle."""
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
macos = root / "macos"
subprocess.run(["swift", "build", "-c", "release"], cwd=macos, check=True)
bin_dir = subprocess.check_output(["swift", "build", "-c", "release", "--show-bin-path"], cwd=macos, text=True).strip()
app = root / "dist" / "北航课表.app"
if app.exists():
    shutil.rmtree(app)
contents = app / "Contents"
(contents / "MacOS").mkdir(parents=True)
resources = contents / "Resources"
resources.mkdir()
shutil.copy2(Path(bin_dir) / "BUAACourses", contents / "MacOS" / "BUAACourses")
shutil.copytree(root / "buaa_sign", resources / "backend" / "buaa_sign", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
iconset = macos / ".build" / "AppIcon.iconset"
iconset.mkdir(exist_ok=True)
icon_png = macos / ".build" / "app-icon.png"
subprocess.run(["swift", str(macos / "icon.swift"), str(icon_png)], check=True)
for size in (16, 32, 128, 256, 512):
    for factor, suffix in ((1, ""), (2, "@2x")):
        subprocess.run(["sips", "-z", str(size * factor), str(size * factor), str(icon_png), "--out", str(iconset / f"icon_{size}x{size}{suffix}.png")], check=True, stdout=subprocess.DEVNULL)
subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(resources / "AppIcon.icns")], check=True)
info = {
    "CFBundleName": "北航课表", "CFBundleDisplayName": "北航课表", "CFBundleIdentifier": "local.buaa.courses",
    "CFBundleExecutable": "BUAACourses", "CFBundlePackageType": "APPL", "CFBundleVersion": "8",
    "CFBundleShortVersionString": "0.8.0", "LSUIElement": True, "LSMinimumSystemVersion": "13.0",
    "CFBundleIconFile": "AppIcon", "NSHighResolutionCapable": True, "BUAAConfigPath": str(root / "config.json"),
    "BUAAPythonPath": sys.executable,
}
with (contents / "Info.plist").open("wb") as f:
    plistlib.dump(info, f)
subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
print(app)
