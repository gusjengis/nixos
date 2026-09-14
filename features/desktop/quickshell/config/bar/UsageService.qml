import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: service

    property var usage: ({
        "providers": [
            { "id": "anthropic", "name": "Anthropic", "available": false, "error": "loading", "windows": [] },
            { "id": "openai-personal", "name": "OpenAI · Personal", "profile": "personal", "saved": false, "active": false, "available": false, "error": "loading", "windows": [] },
            { "id": "openai-business", "name": "OpenAI · Business", "profile": "business", "saved": false, "active": false, "available": false, "error": "loading", "windows": [] }
        ]
    })
    property string accountError: ""
    property bool accountBusy: accountRequest.running
    property bool refreshPending: false

    function refresh() {
        if (!request.running) {
            request.running = true;
        } else {
            refreshPending = true;
        }
    }

    function account(profile, saved) {
        if (accountRequest.running)
            return;
        accountError = "";
        accountRequest.command = ["quickshell-ai-account", saved ? "select" : "save", profile];
        accountRequest.running = true;
    }

    Process {
        id: request
        command: ["quickshell-ai-usage"]
        stdout: StdioCollector { id: output }

        onExited: (code, status) => {
            if (code === 0 && status === 0) {
                try {
                    service.usage = JSON.parse(output.text);
                } catch (error) {
                    console.warn("Cannot parse AI usage:", error);
                }
            }
            if (service.refreshPending) {
                service.refreshPending = false;
                request.running = true;
            }
        }
    }

    Process {
        id: accountRequest
        stdout: StdioCollector { id: accountOutput }

        onExited: (code, status) => {
            try {
                const result = JSON.parse(accountOutput.text);
                if (!result.ok)
                    service.accountError = result.error || "Account action failed";
            } catch (error) {
                service.accountError = "Account action failed";
            }
            // Refresh even when the action failed: a rejected saved login has to
            // re-poll before its card can offer saving again.
            service.refresh();
        }
    }

    Timer {
        // Anthropic rate-limits this endpoint; 5 minutes plus every shell
        // restart was enough to earn HTTP 429.
        interval: 900000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: service.refresh()
    }
}
