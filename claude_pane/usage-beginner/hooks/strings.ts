const defaults: Record<string, string> = {
  "claude_beginner_menu": "Beginner Mode",
  "claude_beginner_tooltip": "Understand Claude’s answers: after each answer, see up to 3 technical terms explained above the prompt. Press 9 to mark them as understood so they stop appearing; a new conversation will later quiz you on them with a multiple-choice question. Uses a small amount of Claude quota.",
  "claude_beginner_title": "Terms",
  "claude_beginner_history_title": "Term history",
  "claude_beginner_description": "Open your term history",
  "claude_beginner_all_known": "All understood",
  "claude_beginner_dismiss": "Dismiss",
  "claude_beginner_known": "Understood",
  "claude_beginner_unknown": "Not yet understood",
  "claude_beginner_empty": "No terms yet.",
  "claude_beginner_opened": "Term history opened.",
  "claude_beginner_quiz_title": "Quick quiz",
  "claude_beginner_quiz_question": "What does {term} mean?",
  "claude_beginner_quiz_right": "Correct! Next quiz in {days} days.",
  "claude_beginner_quiz_done": "Correct! You have learned this term.",
  "claude_beginner_quiz_wrong": "Not quite. The answer is: {answer}. This term will show up in the hints again.",
  "claude_beginner_enabled_msg": "Beginner Mode enabled. Restart Claude Code to apply.",
  "claude_beginner_disabled_msg": "Beginner Mode disabled. Restart Claude Code to apply.",
  "claude_beginner_action_failed": "Could not change Beginner Mode",
  "claude_beginner_error": "Beginner Mode: {error}"
}
let strings = defaults
export let lang = 'en'
export function configure(value?: { strings?: Record<string, string>; lang?: string }) {
  strings = { ...defaults, ...value?.strings }
  lang = value?.lang ?? 'en'
}
export function t(key: string, values: Record<string, string | number> = {}): string {
  return (strings[`claude_beginner_${key}`] ?? key).replace(/\{(\w+)\}/g, (match, name) => String(values[name] ?? match))
}
