---
title: Why Did My Codex Weekly Limit Reset Early?
description: Codex weekly limits often reset days before resets_at because OpenAI runs global resets. Ten weeks of data from one Plus account, the official reset rules, and how to check.
date: 2026-11-23
related: claude-code-weekly-limit-reset, how-to-check-antigravity-quota
---

**Your Codex weekly limit resets early when OpenAI runs a global reset on eligible accounts.** OpenAI refills your limit to 100% and starts a new weekly period on the spot. You lose nothing, so an early reset works like extra quota. The `resets_at` time that Codex reports is the latest moment your limit will refill. Checked on 2026-11-23.

- Tibo, who leads Codex at OpenAI (`@thsottiaux` on X), resets usage for everyone from time to time. He usually announces it on X first.
- On the author's own ChatGPT Plus account, all 10 weekly periods between 2026-08-29 and 2026-10-06 ended 1 to 5 days before `resets_at`. In 3 of them, the author had already used 100%.
- After a reset, your next refresh date moves. The new date replaces the old one.

## Why does the Codex weekly limit reset before the scheduled time?

ChatGPT Work and Codex share the same pricing, credits, and usage limits. On ChatGPT Plus and Business Standard, Codex has a 5-hour limit and a weekly limit. The Pro plans (`Pro 100`, `Pro 200`, and `Pro 500`) have a weekly limit only, with no 5-hour limit for now.

Normally the weekly limit refills at `resets_at`. But OpenAI often applies what its help center calls an "OpenAI-granted automatic reset", also known as a global reset. OpenAI applies it to selected accounts directly, and you don't have to claim anything. Tibo usually announces these resets on X. His posts give reasons such as fixing usage problems, reaching a user milestone, or launching a new model.

A global reset does not show up in your reset **History**. So what you notice is this: your used percentage drops to zero, and your next refresh date moves later.

## How often does an early reset happen?

The author tracked their own ChatGPT Plus account from 2026-08-29 to 2026-10-06. That period covered 10 weekly periods, and none of them lasted until `resets_at`:

- All 10 ended **1 to 5 days early**, and a new period started right away.
- In **3** of the 10, the author had already used **100%**. The early reset let them keep working.

An unofficial site, [codex-resets.com](https://codex-resets.com/), follows `@thsottiaux` on X and logs each reset. As of 2026-11-23 it had logged 72 resets. The average wait between them was 5.9 days, and the longest was 67.7 days. The site notes that an AI sorts its entries, and that nothing on it is a promise from OpenAI. OpenAI also says that free resets are promotional and have no fixed schedule.

## What is the difference between a global reset and a banked reset?

OpenAI's help center describes three kinds of one-time reset:

| Type | How you get it | What it refills | Shown in History? |
| --- | --- | --- | --- |
| Global (automatic) | OpenAI applies it to selected accounts | The covered limits, back to 100% | No |
| Banked | Saved to your account. You use it before it expires, when a covered limit is below 80% left (10% or less if your assistant uses it for you) | Go: monthly. Plus and Business Standard: 5-hour and weekly. Pro 100, 200, and 500: weekly | Yes, for 30 days |
| Purchased | Bought by some Plus and Pro accounts | The covered limits, right away | No |

Suppose you use a banked reset, and a global reset arrives later. The global reset brings you back to 100%, not 200%. Banked resets that you haven't used stay in your account.

## What does resets_at mean if resets can happen early?

Think of `resets_at` as the latest time your limit will refill. If no global reset comes first, that is when your week ends.

When a reset does come early, your schedule moves with it. OpenAI gives an example: a weekly period was due to end on Friday, but a reset restarted it on Tuesday. The next refresh is then the following Tuesday, and the Friday date no longer applies.

## How can you check your Codex limit and countdown?

There are two free official ways, and a third option if you want the number on screen all the time:

- **The usage dashboard.** Open the [usage dashboard](https://chatgpt.com/codex/settings/usage) on the web, or **Settings > Usage & billing** in the desktop app. It shows how much you have left, when the limit refills, and any banked resets under **Available**.
- **Codex CLI.** Run `/status` to see how much you have left. To use a banked reset, run `/usage` and choose **Redeem reset**.
- **The `usage` app.** `usage` is free and open source. It reads your local Codex logs and shows your 5-hour and weekly limits, with countdowns, in the macOS menu bar or the Windows system tray. A limit turns red as it gets close, and you can get a notification at 50%, 70%, 80%, 90%, or 95%. The default is 90%. When a global reset lands, you see the new countdown without opening anything.

## Key takeaways

- A Codex weekly limit resets early because OpenAI ran a global reset. You get a full limit back and a new weekly period.
- On the author's own Plus account, all 10 weekly periods from 2026-08-29 to 2026-10-06 ended 1 to 5 days before `resets_at`. In 3 of them, the author had used 100%.
- `resets_at` is the latest time your limit will refill. To see the current number, use the usage dashboard, `/status`, or the `usage` app.

## Sources

- [How resets work in Codex](https://help.openai.com/en/articles/20001498-how-resets-work-in-codex)
- [Pricing | ChatGPT Learn](https://learn.chatgpt.com/docs/pricing)
- [Understanding ChatGPT and Codex usage limits](https://help.openai.com/en/articles/20001625-understanding-chatgpt-and-codex-usage-limits)
- [Codex Limit Reset Tracker](https://codex-resets.com/)
