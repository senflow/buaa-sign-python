import AppKit
let output = CommandLine.arguments[1]
let image = NSImage(size: NSSize(width: 1024, height: 1024))
image.lockFocus()
let rect = NSRect(x: 56, y: 56, width: 912, height: 912)
let shape = NSBezierPath(roundedRect: rect, xRadius: 215, yRadius: 215)
NSGradient(starting: NSColor(red: 0.11, green: 0.16, blue: 0.24, alpha: 1), ending: NSColor(red: 0.055, green: 0.07, blue: 0.11, alpha: 1))!.draw(in: shape, angle: -90)
let blue = NSColor(red: 0.12, green: 0.55, blue: 1, alpha: 1)
if let symbol = NSImage(systemSymbolName: "graduationcap.fill", accessibilityDescription: nil)?.withSymbolConfiguration(.init(pointSize: 460, weight: .regular)) {
    let tinted = NSImage(size: symbol.size)
    tinted.lockFocus(); symbol.draw(at: .zero, from: .zero, operation: .sourceOver, fraction: 1)
    blue.setFill(); NSRect(origin: .zero, size: symbol.size).fill(using: .sourceAtop); tinted.unlockFocus()
    tinted.draw(in: NSRect(x: 217, y: 285, width: 590, height: 450))
}
image.unlockFocus()
try NSBitmapImageRep(data: image.tiffRepresentation!)!.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: output))
