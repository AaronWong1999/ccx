// Renders the ccx app icon: the same ⇄ circle as the menu bar icon.
// Usage: swift make_icon.swift <out.iconset dir> <readme png path>
import AppKit

func render(_ px: Int) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let s = CGFloat(px)
    let disc = NSRect(x: s * 0.08, y: s * 0.08, width: s * 0.84, height: s * 0.84)
    NSColor(srgbRed: 0.13, green: 0.13, blue: 0.15, alpha: 1).setFill()
    NSBezierPath(ovalIn: disc).fill()
    let cfg = NSImage.SymbolConfiguration(pointSize: s * 0.40, weight: .semibold)
    if let sym = NSImage(systemSymbolName: "arrow.left.arrow.right", accessibilityDescription: nil)?.withSymbolConfiguration(cfg) {
        let white = NSImage(size: sym.size, flipped: false) { r in
            sym.draw(in: r); NSColor.white.set(); r.fill(using: .sourceAtop); return true }
        white.draw(in: NSRect(x: (s - sym.size.width) / 2, y: (s - sym.size.height) / 2,
                              width: sym.size.width, height: sym.size.height))
    }
    NSGraphicsContext.restoreGraphicsState()
    return rep
}

let out = CommandLine.arguments[1]
try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)
for base in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let name = scale == 1 ? "icon_\(base)x\(base).png" : "icon_\(base)x\(base)@2x.png"
        try! render(base * scale).representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "\(out)/\(name)"))
    }
}
try! render(256).representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
