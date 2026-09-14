import Quickshell.Io

Process {
    required property var launcher
    required property string provider
    required property string query
    required property int generation

    command: ["quickshell-search", provider, query]
    stdout: SplitParser {
        onRead: data => launcher.enqueueResult(generation, provider, data)
    }
    stderr: SplitParser {
        onRead: data => launcher.reportSearchError(generation, data)
    }
    onExited: destroy()
}
