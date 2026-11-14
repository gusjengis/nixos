import { expect, test } from "bun:test"
import { Schema } from "effect"
import { Session } from "@opencode/schema/session"
import { SessionMessage } from "@opencode/core/session/message"
import { convertLegacyTransfer } from "@opencode/core/session/legacy-transfer"

function fixture() {
  return {
    info: { id: "ses_legacy", projectID: "global", directory: "/project", title: "Preserved goal",
      metadata: { desktop_context: { id: "owner", chat: "ses_legacy", session: "ses_legacy" } }, time: { created: 1, updated: 20 } },
    messages: [
      { info: { id: "msg_legacy_user", role: "user", time: { created: 10 }, agent: "plan", model: { providerID: "provider", modelID: "model" } },
        parts: [{ id: "prt_1", type: "text", text: "Preserved request" },
          { id: "prt_2", type: "file", mime: "image/png", filename: "image.png", url: "data:image/png;base64,AQID" }] },
      { info: { id: "msg_legacy_assistant", role: "assistant", parentID: "msg_legacy_user", time: { created: 15, completed: 20 },
        modelID: "model", providerID: "provider", mode: "plan", agent: "plan", path: { cwd: "/project", root: "/project" },
        cost: 1, tokens: { total: 10, input: 2, output: 3, reasoning: 4, cache: { read: 5, write: 6 } } },
        parts: [{ id: "prt_3", type: "text", text: "Preserved response" }] },
    ],
  }
}

test("offline V1 transfer conversion preserves identity, owner, text, files and model selection", () => {
  const input = fixture()
  const before = JSON.stringify(input)
  const data = convertLegacyTransfer(input)
  Schema.decodeUnknownSync(Session.Info)(data.info)
  data.messages.forEach((message) => Schema.decodeUnknownSync(SessionMessage.Info)(message))
  expect(data.info.id).toBe(input.info.id)
  expect(data.info.metadata).toEqual(input.info.metadata)
  expect(data.info.title).toBe("Preserved goal")
  expect(data.info.agent).toBe("plan")
  expect(data.info.model).toMatchObject({ providerID: "provider", id: "model" })
  expect(data.messages[0]).toMatchObject({ type: "user", text: "Preserved request" })
  expect((data.messages[0] as any).files).toHaveLength(1)
  expect(data.messages[1]).toMatchObject({ type: "assistant", content: [{ type: "text", text: "Preserved response" }] })
  expect(JSON.stringify(input)).toBe(before)
})

test("native V2 transfer input remains unchanged", () => {
  const native = convertLegacyTransfer(fixture())
  expect(convertLegacyTransfer(native)).toBe(native)
})

test("invalid V1 records fail before an import can lose data", () => {
  const input = fixture()
  input.messages[0].parts.push({ id: "prt_unknown", type: "unknown-native-record", text: "must survive" } as any)
  expect(() => convertLegacyTransfer(input)).toThrow("unsupported record")
  expect(() => convertLegacyTransfer({ ...fixture(), info: { ...fixture().info, directory: "relative" } })).toThrow("absolute")
})
