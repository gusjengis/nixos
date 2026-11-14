import { execFile } from "node:child_process"
import { homedir } from "node:os"
import { join } from "node:path"

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
const SPINNER_INTERVAL_MS = 80

export const TmuxStatusPlugin = async () => {
  const pane = process.env.TMUX_PANE

  if (!pane) {
    return {}
  }

  const sessionStates = new Map()
  const pendingInput = new Map()
  let appliedIcon
  let appliedMode
  let requestedIcon
  let writingIcon = false
  let retryTimer
  let spinnerFrame = 0
  let spinnerTimer
  let workingMode = "build"
  let completed = false
  let errored = false
  let completionCheck = 0
  let disposed = false

  // Rate-limit retries render in the error color instead of the agent mode color.
  function currentMode() {
    for (const state of sessionStates.values()) {
      if (state === "retry") {
        return "retry"
      }
    }

    return workingMode
  }

  function setIcon(icon) {
    requestedIcon = icon

    if (disposed || writingIcon || retryTimer || (requestedIcon === appliedIcon && currentMode() === appliedMode)) {
      return
    }

    const nextIcon = requestedIcon
    const nextMode = currentMode()
    writingIcon = true
    execFile(
      "tmux",
      [
        "set-option", "-p", "-t", pane, "@opencode_icon", nextIcon,
        ";", "set-option", "-p", "-t", pane, "@opencode_mode", nextMode,
      ],
      { timeout: 500, killSignal: "SIGKILL" },
      (error) => {
        if (disposed) return
        if (error) {
          writingIcon = false
          retryTimer = setTimeout(() => {
            retryTimer = undefined
            setIcon(requestedIcon)
          }, 1000)
          retryTimer.unref?.()
          return
        }

        appliedIcon = nextIcon
        appliedMode = nextMode
        writingIcon = false
        setIcon(requestedIcon)
      },
    )
  }

  function clearSessionInput(sessionID) {
    for (const [requestID, ownerSessionID] of pendingInput) {
      if (ownerSessionID === sessionID) {
        pendingInput.delete(requestID)
      }
    }
  }

  function stopSpinner() {
    if (!spinnerTimer) {
      return
    }

    clearInterval(spinnerTimer)
    spinnerTimer = undefined
  }

  function cancelCompletion() {
    completionCheck += 1
    completed = false
    errored = false
  }

  function checkUnfocused(check, onResult) {
    execFile(
      "python3",
      [join(process.env.XDG_CONFIG_HOME || join(homedir(), ".config"), "tmux/plugins/opencode-viewed.py"), pane],
      { timeout: 500, killSignal: "SIGKILL" },
      (error) => {
        if (disposed || check !== completionCheck) {
          return
        }

        onResult(Boolean(error))
      },
    )
  }

  function markCompletedIfUnfocused() {
    const check = ++completionCheck
    completed = false
    errored = false

    checkUnfocused(check, (unfocused) => {
      if (sessionStates.size > 0 || pendingInput.size > 0) {
        return
      }

      completed = unfocused
      updateIcon()
    })
  }

  // A failed session needs resuming whether or not it was seen, so the error
  // stays until the next prompt starts work (cancelCompletion on busy status).
  function markErrored() {
    completionCheck += 1
    completed = false
    errored = true
  }

  function updateIcon() {
    if (errored) {
      stopSpinner()
      setIcon("X")
      return
    }

    if (pendingInput.size > 0) {
      stopSpinner()
      setIcon("?")
      return
    }

    const working = [...sessionStates.values()].some((state) => state === "busy" || state === "retry")

    if (working) {
      if (spinnerTimer) {
        return
      }

      const advanceSpinner = () => {
        setIcon(SPINNER_FRAMES[spinnerFrame])
        spinnerFrame = (spinnerFrame + 1) % SPINNER_FRAMES.length
      }

      advanceSpinner()
      spinnerTimer = setInterval(advanceSpinner, SPINNER_INTERVAL_MS)
      spinnerTimer.unref?.()
      return
    }

    stopSpinner()
    setIcon(completed ? "!" : "")
  }

  // Clear pane state left by an OpenCode process that exited while working.
  setIcon("")

  return {
    event: async ({ event }) => {
      if (event.type === "server.instance.disposed") {
        disposed = true
        stopSpinner()
        clearTimeout(retryTimer)
        return
      }
      if (disposed) return
      if (event.type === "session.status") {
        if (event.properties.status.type === "idle") {
          const wasWorking = sessionStates.has(event.properties.sessionID)
          sessionStates.delete(event.properties.sessionID)
          if (wasWorking && sessionStates.size === 0 && pendingInput.size === 0) {
            markCompletedIfUnfocused()
          }
        } else {
          sessionStates.set(event.properties.sessionID, event.properties.status.type)
          cancelCompletion()
        }
        updateIcon()
        return
      }

      if (
        event.type === "message.updated"
        && event.properties.info.role === "user"
        && (event.properties.info.agent === "plan" || event.properties.info.agent === "build")
      ) {
        workingMode = event.properties.info.agent
        setIcon(requestedIcon)
        return
      }

      if (event.type === "session.idle") {
        const wasWorking = sessionStates.has(event.properties.sessionID)
        sessionStates.delete(event.properties.sessionID)
        if (wasWorking && sessionStates.size === 0 && pendingInput.size === 0) {
          markCompletedIfUnfocused()
        }
        updateIcon()
        return
      }

      if (event.type === "session.error") {
        if (event.properties.sessionID) {
          sessionStates.delete(event.properties.sessionID)
          clearSessionInput(event.properties.sessionID)
        } else {
          sessionStates.clear()
          pendingInput.clear()
        }
        // A manual interrupt is not a failure requiring attention.
        if (event.properties.error?.name === "MessageAbortedError") {
          cancelCompletion()
        } else {
          markErrored()
        }
        updateIcon()
        return
      }

      if (event.type === "session.deleted") {
        cancelCompletion()
        sessionStates.delete(event.properties.info.id)
        clearSessionInput(event.properties.info.id)
        updateIcon()
        return
      }

      if (event.type === "question.asked" || event.type === "permission.asked") {
        cancelCompletion()
        pendingInput.set(event.properties.id, event.properties.sessionID)
        updateIcon()
        return
      }

      if (
        event.type === "question.replied"
        || event.type === "question.rejected"
        || event.type === "permission.replied"
      ) {
        pendingInput.delete(event.properties.requestID)
        updateIcon()
      }
    },
  }
}
