/** @jsxImportSource @opentui/solid */
import { createSignal, Show, onCleanup } from "solid-js"
import { useTerminalDimensions } from "@opentui/solid"

// The native host and external TUI plugin share one process-local bridge. No
// socket, remote control, server bus route event, or global desktop dependency.
const key = Symbol.for("opencode.desktop.stale.v1")
type Draft = { prompt: { input: string; parts: any[] }; mode?: string; cursor?: number }
type Prompt = { id: () => string | undefined; capture: () => Draft; restore: (draft: Draft) => void; blur: () => void }

function createHost() {
  const [overlay, setOverlay] = createSignal<{ render: () => any; key: (event: any) => void }>()
  let prompt: Prompt | undefined
  let permit: string | undefined
  let pending: { id: string; draft: Draft } | undefined
  let guard: (() => Promise<boolean> | boolean) | undefined
  let rejected: ((id: string, draft: Draft, error: unknown) => Promise<void>) | undefined
  const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value))
  const drafts = new Map<string, Draft>()
  return {
    version: 1,
    overlay,
    blocked: () => overlay() !== undefined,
    block(render: () => any, handleKey: (event: any) => void) {
      prompt?.blur()
      setOverlay({ render, key: handleKey })
    },
    clear() { setOverlay(undefined) },
    configure(input: { guard: typeof guard; rejected: typeof rejected }) {
      guard = input.guard
      rejected = input.rejected
      return () => { guard = undefined; rejected = undefined }
    },
    capture(): Draft { return copy(prompt?.capture() ?? { prompt: { input: "", parts: [] } }) },
    destination(id: string) { return copy(drafts.get(id) ?? { prompt: { input: "", parts: [] } }) },
    bindPrompt(value: Prompt) {
      prompt = value
      if (pending && value.id() === pending.id) {
        value.restore(copy(pending.draft))
        pending = undefined
      }
      return () => {
        const id = value.id()
        if (id) drafts.set(id, copy(value.capture()))
        if (prompt === value) prompt = undefined
      }
    },
    allowRoute(route: { type: string; sessionID?: string }) {
      if (!overlay()) return true
      if (route.type !== "session" || route.sessionID !== permit) return false
      permit = undefined
      return true
    },
    handoff(id: string, draft: Draft, validate: () => boolean, navigate: () => void) {
      if (!overlay() || !validate()) throw new Error("Freshness changed before routing; acknowledgement required again.")
      permit = id
      pending = { id, draft: copy(draft) }
      try { navigate() } finally { permit = undefined }
      // Keep background focus blocked until route has synchronously committed.
      setOverlay(undefined)
    },
    async beforeSubmit() {
      if (overlay()) return false
      // Without the plugin, the native server freshness gate (OC5) remains the
      // authority; silently swallowing Enter here would be an invisible failure.
      return guard ? await guard() : true
    },
    submission(id: string) {
      const draft = this.capture()
      return (error: unknown) => { void rejected?.(id, draft, error) }
    },
  }
}

export const desktopStale: ReturnType<typeof createHost> =
  ((globalThis as any)[key] ??= createHost())

export function DesktopStaleOverlay() {
  const dimensions = useTerminalDimensions()
  return <Show when={desktopStale.overlay()}>{(value) =>
    <box position="absolute" left={0} top={0} zIndex={100000}
      width={dimensions().width} height={dimensions().height}
      backgroundColor="#161b22" padding={2} flexDirection="column"
      onMouseDown={(event: any) => { event.preventDefault(); event.stopPropagation() }}
      onMouseUp={(event: any) => { event.preventDefault(); event.stopPropagation() }}>
      {value().render()}
    </box>
  }</Show>
}

export function installDesktopStaleKeys(keymap: any) {
  const off = keymap.intercept("key", ({ event }: any) => {
    const value = desktopStale.overlay()
    if (!value) return
    event.preventDefault()
    event.stopPropagation()
    if (event.eventType === "release" || event.repeated) return
    value.key(event)
  }, { priority: 10000 })
  onCleanup(off)
}
