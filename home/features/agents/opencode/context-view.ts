import { readFileSync } from "node:fs"

function scope() {
  const id = process.env.CONTEXT_ID
  try {
    const value = JSON.parse(readFileSync(process.env.OPENCODE_CONTEXT_SCOPE_FILE!, "utf8"))
    if (value.context_id === id && value.ids.includes(id)) return value
  } catch {}
  return { ids: [id], hidden: [], labels: {} }
}

export function desktopVisible(info: { id: string; metadata?: Record<string, any> }) {
  if (!process.env.CONTEXT_ID) return true
  const view = scope()
  return view.ids.includes(info.metadata?.desktop_context?.id) && !view.hidden.includes(info.id)
}

export function desktopLabel(info: { metadata?: Record<string, any> }) {
  if (!process.env.CONTEXT_ID) return ""
  return scope().labels[info.metadata?.desktop_context?.id] ?? ""
}
