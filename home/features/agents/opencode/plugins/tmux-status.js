import { execFile } from "node:child_process"

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

    if (writingIcon || retryTimer || (requestedIcon === appliedIcon && currentMode() === appliedMode)) {
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
      (error) => {
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
      "tmux",
      ["display-message", "-p", "-t", pane, "#{session_attached} #{window_active} #{pane_active}"],
      (error, stdout) => {
        if (error || check !== completionCheck) {
          return
        }

        const [attached, activeWindow, activePane] = stdout.trim().split(" ")
        onResult(!(Number(attached) > 0 && activeWindow === "1" && activePane === "1"))
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

  function markErroredIfUnfocused() {
    const check = ++completionCheck
    completed = false
    errored = false

    checkUnfocused(check, (unfocused) => {
      errored = unfocused
      updateIcon()
    })
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
        markErroredIfUnfocused()
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
