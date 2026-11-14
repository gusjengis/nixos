// Retain the user's V1 semantic agent colors when a V2 theme changes mode.
// Migrated V1 themes keep secondary/accent at the head of their categorical palette.
export function agentThemeColor(theme, name, step = 200) {
  if (name === "secondary") return theme.categorical[0]?.[step]
  if (name === "accent") return theme.categorical[1]?.[step] ?? theme.categorical[0]?.[step]
  if (name === "primary") return theme.text.action.primary.base
  return theme.text.feedback[name]?.base
}
