import AppKit
// Composites Finder's non-empty folder (back flap, paper sheet, front flap)
// from CoreTypes' asset catalog at each freedesktop size, in dark appearance.
let b = Bundle(path: "/System/Library/CoreServices/CoreTypes.bundle")!
let out = CommandLine.arguments[1]
try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)
NSAppearance.current = NSAppearance(named: .darkAqua)
func component(_ name: String, _ px: Int) -> NSImage {
    // Point sizes the catalog ships; pick the smallest that covers px.
    let pts = [16, 32, 128, 256, 512]
    let pt = pts.first { $0 * 2 >= px } ?? 512
    return b.image(forResource: "FolderComponent_\(name)/image_\(pt)")!
}
for px in [16, 32, 48, 64, 128, 256, 512] {
    for (tag, parts) in [("folder-full", ["BackFlap", "PaperSheet", "FrontFlap"]), ("folder-empty", ["BackFlap", "FrontFlap"])] {
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        rep.size = NSSize(width: px, height: px)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        NSGraphicsContext.current!.imageInterpolation = .high
        for p in parts { component(p, px).draw(in: NSRect(x: 0, y: 0, width: px, height: px), from: .zero, operation: .sourceOver, fraction: 1) }
        NSGraphicsContext.restoreGraphicsState()
        try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "\(out)/\(tag)-\(px).png"))
    }
}
