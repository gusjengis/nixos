// One SSH channel owns one temporary display layout. EOF, timeout, and SIGTERM
// all restore physical displays before removing our virtual display.
import CoreGraphics
import Foundation
import Darwin

enum SessionError: Error, CustomStringConvertible {
    case message(String)
    var description: String { switch self { case .message(let text): return text } }
}

func run(_ executable: String, _ args: [String]) throws -> String {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: executable)
    task.arguments = args
    let output = Pipe()
    task.standardOutput = output
    task.standardError = FileHandle.standardError
    try task.run()
    let data = output.fileHandleForReading.readDataToEndOfFile()
    task.waitUntilExit()
    guard task.terminationStatus == 0 else {
        throw SessionError.message("\(executable) failed (\(task.terminationStatus))")
    }
    return String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
}

func report(_ value: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
}

func onlineDisplays() throws -> [CGDirectDisplayID] {
    var displays = [CGDirectDisplayID](repeating: 0, count: 32)
    var count: UInt32 = 0
    guard CGGetOnlineDisplayList(32, &displays, &count) == .success else {
        throw SessionError.message("Cannot enumerate Mac displays")
    }
    return Array(displays.prefix(Int(count)))
}

typealias EnableDisplay = @convention(c) (CGDisplayConfigRef, CGDirectDisplayID, Bool) -> CGError
let coreGraphics = dlopen("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics", RTLD_NOW)!
let enableDisplay = unsafeBitCast(dlsym(coreGraphics, "CGSConfigureDisplayEnabled")!, to: EnableDisplay.self)

struct SavedDisplay {
    let id: CGDirectDisplayID
    let mode: CGDisplayMode?
    let origin: CGPoint
    let mirror: CGDirectDisplayID
}

var interrupted = false
signal(SIGTERM) { _ in interrupted = true }
signal(SIGINT) { _ in interrupted = true }
signal(SIGHUP) { _ in interrupted = true }

let bd = "/opt/homebrew/bin/betterdisplaycli"
let screenName = "MacBook Remote"
if CommandLine.arguments.contains("--inspect") {
    do {
        report(["displays": try onlineDisplays().map { id -> [String: Any] in
            let mode = CGDisplayCopyDisplayMode(id)
            return ["id": id, "builtin": CGDisplayIsBuiltin(id) != 0,
                    "active": CGDisplayIsActive(id) != 0,
                    "width": mode?.width ?? 0, "height": mode?.height ?? 0]
        }])
    } catch { report(["error": String(describing: error)]); exit(1) }
    exit(0)
}
let lockFD = open("/tmp/macbook-remote-\(getuid()).lock", O_CREAT | O_RDWR, S_IRUSR | S_IWUSR)
guard lockFD >= 0, flock(lockFD, LOCK_EX | LOCK_NB) == 0 else {
    report(["error": "Another MacBook remote session is already running"])
    exit(1)
}
defer { close(lockFD) }

var saved: [SavedDisplay] = []
var created = false
let caffeinate = Process()
var previousSize = ""

func configure(_ body: (CGDisplayConfigRef) throws -> Void) throws {
    var config: CGDisplayConfigRef?
    guard CGBeginDisplayConfiguration(&config) == .success, let config else {
        throw SessionError.message("Cannot begin display configuration")
    }
    do { try body(config) }
    catch { CGCancelDisplayConfiguration(config); throw error }
    guard CGCompleteDisplayConfiguration(config, .forSession) == .success else {
        throw SessionError.message("Mac rejected display configuration")
    }
}

func restore() {
    // Enable by saved display ID directly: disabled displays disappear from
    // enumeration, which prevents displayplacer from re-enabling them.
    try? configure { config in
        for display in saved { _ = enableDisplay(config, display.id, true) }
    }
    usleep(200_000)
    if created { _ = try? run(bd, ["discard", "--type=VirtualScreen", "--name=\(screenName)"]) }
    try? configure { config in
        for display in saved {
            if let mode = display.mode { CGConfigureDisplayWithDisplayMode(config, display.id, mode, nil) }
            CGConfigureDisplayOrigin(config, display.id, Int32(display.origin.x), Int32(display.origin.y))
            CGConfigureDisplayMirrorOfDisplay(config, display.id, display.mirror)
        }
    }
    if caffeinate.isRunning { caffeinate.terminate(); caffeinate.waitUntilExit() }
}

func resize(_ width: Int, _ height: Int) throws {
    guard (320...7680).contains(width), (200...4320).contains(height) else {
        throw SessionError.message("Window size outside supported range")
    }
    let size = "\(width)x\(height)"
    guard size != previousSize else { return }
    let modes = previousSize.isEmpty ? size : "\(size),\(previousSize)"
    _ = try run(bd, ["set", "--name=\(screenName)", "--resolutionList=\(modes)"])
    // BetterDisplay acknowledges mode-list updates before WindowServer has
    // published the new modes. Wait for that boundary rather than assuming it.
    var actual = ""
    for _ in 0..<15 {
        usleep(200_000)
        _ = try? run(bd, ["set", "--name=\(screenName)", "--resolution=\(size)", "--hiDPI=off"])
        actual = (try? run(bd, ["get", "--name=\(screenName)", "--resolution"])) ?? ""
        if actual == size { break }
    }
    guard actual == size else { throw SessionError.message("Requested \(size), Mac returned \(actual)") }
    previousSize = size
    report(["width": width, "height": height])
}

do {
    _ = try run("/usr/bin/nc", ["-z", "-w", "2", "127.0.0.1", "5900"])
    let identifiers = try run(bd, ["get", "--identifiers"])
    let devices = try JSONSerialization.jsonObject(with: Data("[\(identifiers)]".utf8)) as! [[String: Any]]
    guard !devices.contains(where: { $0["name"] as? String == screenName }) else {
        throw SessionError.message("A stale MacBook Remote display exists; remove it in BetterDisplay first")
    }
    saved = try onlineDisplays().filter { CGDisplayIsActive($0) != 0 || CGDisplayIsInMirrorSet($0) != 0 }.map {
        SavedDisplay(id: $0, mode: CGDisplayCopyDisplayMode($0), origin: CGDisplayBounds($0).origin,
                     mirror: CGDisplayMirrorsDisplay($0))
    }
    caffeinate.executableURL = URL(fileURLWithPath: "/usr/bin/caffeinate")
    caffeinate.arguments = ["-is", "-w", String(getpid())]
    try caffeinate.run()
    defer { restore() }
    _ = try run(bd, ["create", "--type=VirtualScreen", "--virtualScreenName=\(screenName)",
                     "--useResolutionList=on", "--resolutionList=1280x800", "--virtualScreenHiDPI=off"])
    created = true
    _ = try run(bd, ["set", "--name=\(screenName)", "--connected=on"])
    usleep(500_000)
    try configure { config in
        for display in saved {
            guard enableDisplay(config, display.id, false) == .success else {
                throw SessionError.message("Cannot turn off physical display \(display.id)")
            }
        }
    }
    usleep(300_000)
    guard saved.allSatisfy({ CGDisplayIsActive($0.id) == 0 }) else {
        throw SessionError.message("Physical display remained active")
    }
    report(["ready": true, "physicalDisplaysOff": true])
    // Heartbeats bound cleanup even if an SSH connection stalls rather than
    // closing. read(2) avoids stdio buffering hiding already-received commands.
    var pending = Data()
    var buffer = [UInt8](repeating: 0, count: 4096)
    while !interrupted {
        var fd = pollfd(fd: STDIN_FILENO, events: Int16(POLLIN), revents: 0)
        let result = poll(&fd, 1, 45_000)
        if result <= 0 { break }
        let count = read(STDIN_FILENO, &buffer, buffer.count)
        if count <= 0 { break }
        pending.append(contentsOf: buffer.prefix(count))
        guard pending.count < 8192 else { throw SessionError.message("Invalid control command") }
        while let end = pending.firstIndex(of: 10) {
            let line = String(decoding: pending[..<end], as: UTF8.self)
            pending.removeSubrange(...end)
            if line == "ping" { continue }
            let numbers = line.split(separator: " ").compactMap { Int($0) }
            guard numbers.count == 2 else { throw SessionError.message("Invalid resize command") }
            try resize(numbers[0], numbers[1])
        }
    }
} catch {
    report(["error": String(describing: error)])
    exit(1)
}
