---
title: How to Check Your Antigravity (agy) Quota
description: Type /usage in the Antigravity CLI, or run agy -p /usage --output-format json to get your quota without calling a model. Here are the three quota pools and when they reset.
date: 2026-11-23
related: claude-code-weekly-limit-reset, codex-weekly-limit-early-reset
---

**To check your Antigravity (`agy`) quota, type `/usage` in the CLI, or run `agy -p /usage --output-format json` in your terminal.** The second command does not call a model, and it returns in about 6 seconds. Your quota is split into three pools: Gemini Models, Claude and GPT models, and Gemini 4 Argon. Each pool keeps its own timer. Checked on 2026-11-23.

- `agy -p /usage --output-format json` gives you your quota as JSON, and it does not use any model quota.
- Gemini Models and Claude and GPT models each have a weekly limit and a 5-hour limit. Gemini 4 Argon has a weekly limit only.
- In our testing, the 5-hour window starts with your first use of the day. Google's docs don't say this.

## How do you check your quota in the CLI or the app?

Google documents two built-in ways to see your baseline quota and your AI credits.

The first is the CLI. In an interactive session, type `/usage` (or `/quota`) and press Enter. Google's CLI docs say this refreshes your quota from the backend and opens a **Models & Quota** panel. You can scroll with the arrow keys or `J` and `K`, jump with `G` and `Shift + G`, and close the panel with `Esc` or `Q`. The right side of the status line also shows how many AI credits you have left, and it highlights the number when you are running low. To open a separate credits panel, type `/credits`.

The second is the app. Google's **Plans** page says you can see your baseline quota on the **Settings** page. If you are on Google AI Pro or Ultra, you can also set **AI Credit Overages** there. **Never** means you wait for your quota to refill. **Always** means Antigravity uses your AI credits once the quota runs out.

## How do you get your quota as JSON without calling a model?

If you want the numbers for a script or a status line, run the CLI in headless mode (`-p`) with JSON output:

```bash
agy -p /usage --output-format json
```

In our testing, this command makes no model call and returns in about 6 seconds. Google documents `/usage` as an interactive command, and it documents `agy -p` with `--output-format json`. It does not document using the two together, and it does not describe the `command.data.groups` field that holds the pools.

## What are the three quota pools, and do they share a timer?

The `command.data.groups` field lists three pools. Each one keeps its own timer:

| Pool | Limits | Shares a timer with the others? | Covered in Google's docs? |
| --- | --- | --- | --- |
| `Gemini Models` | Weekly and 5-hour | No | Partly. The docs say Gemini Flash and Pro share limits |
| `Claude and GPT models` | Weekly and 5-hour | No | Partly. The docs say Claude and GPT models share limits |
| `Gemini 4 Argon` | Weekly only | No | No |

So if you use up the 5-hour limit on Gemini Models, your Claude and GPT models pool and your Gemini 4 Argon pool are still full.

## When do the 5-hour and weekly limits reset?

Google's **Plans** page says the refresh schedule depends on your Google AI plan:

- **Google AI Ultra:** the highest quota, refreshed every five hours, plus the highest weekly rate limit and access to third-party models.
- **Google AI Pro:** a high quota, refreshed every five hours until you reach the weekly limit, plus a higher weekly rate limit.
- **Other plans:** a baseline quota that refreshes weekly, plus a weekly rate limit.

Google also says that how fast you use quota depends on how much work the agent does. Simple tasks let you send more prompts, and complex tasks use more. The docs don't say when the 5-hour window starts. In our testing, it starts with your first use of the day.

## How can you keep your Antigravity quota on screen?

There are two free official ways, and a third option if you want the number on screen all the time:

- **`/usage` or Settings.** Type `/usage` in `agy` to open the Models & Quota panel, or open the Settings page in the app.
- **`agy -p /usage --output-format json`.** Read the three pools from `command.data.groups`.
- **The `usage` app.** `usage` is free and open source. It reads your quota with `agy -p /usage`. If that fails, it falls back to Google's quota endpoint, using the sign-in that the Antigravity CLI already saved. It shows your 5-hour and weekly limits, with countdowns, in the macOS menu bar or the Windows system tray. The Antigravity card shows the Gemini pool first. Tap the `Gemini ⇄` tag to switch to the Claude / GPT pool or the Gemini 4 Argon pool, and the card remembers your choice. A limit turns red as it gets close, and you can get a notification at 50%, 70%, 80%, 90%, or 95%. The default is 90%.

## Key takeaways

- Type `/usage` in the Antigravity CLI to open the quota panel. Run `agy -p /usage --output-format json` to get the same data as JSON without calling a model.
- There are three pools. Gemini Models and Claude and GPT models have weekly and 5-hour limits. Gemini 4 Argon has a weekly limit only. Each pool keeps its own timer.
- In our testing, the 5-hour window starts with your first use of the day. `usage` shows all three pools, with countdowns, in your menu bar or tray.

## Sources

- [Model quotas (/usage)](https://antigravity.google/docs/cli/commands/usage)
- [Plans](https://antigravity.google/docs/plans)
- [Headless mode](https://antigravity.google/docs/cli/headless)
- [CLI AI credits](https://antigravity.google/docs/cli/credits)
- [Choose a model](https://antigravity.google/docs/models)
