# Security Policy

> 繁體中文版本：[SECURITY.zh-TW.md](SECURITY.zh-TW.md)

## Reporting a Vulnerability

If you find a security vulnerability in usage, **please do not open a public Issue.** Report it privately instead:

📧 **aqua5230@gmail.com**

Please include where you can:

- The affected version (or commit)
- Steps to reproduce, or a proof of concept
- Your assessment of the impact

This is a single-maintainer project; I'll do my best to respond and address reports within a reasonable timeframe, and will credit you in the release notes once a fix ships (unless you prefer to stay anonymous).

## Supported Versions

usage ships on a rolling basis; security fixes target the **latest release only**. Please confirm you're on the [latest release](https://github.com/aqua5230/usage/releases/latest) before reporting.

## Security Design

usage **never calls an LLM API.** Watching your quota never costs you tokens — that's the core design principle of the project. usage also does not upload, track, or phone home with your usage data: your prompts, your conversation content, and your usage numbers never leave your machine.

**Claude Code and Codex** numbers come entirely from files already on your local disk — the status file Claude Code's statusLine hook writes, and Codex's session logs. Reading them involves no network access at all.

**Antigravity** is different, and worth stating plainly: its quota is not on your disk, so usage fetches it over the network. See below.

### Every outbound request

| Purpose | Endpoint | When |
|---|---|---|
| Antigravity quota | `https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary` | periodically while the app runs, and only if Antigravity is signed in |
| Antigravity token refresh | `https://oauth2.googleapis.com/token` | when the stored access token has expired |
| Service-status banners | `https://status.claude.com/api/v2/summary.json`<br>`https://status.openai.com/api/v2/summary.json` | every 5 minutes |
| Token price table | `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` | on first need, then every 7 days |
| Update check | `https://api.github.com/repos/aqua5230/usage/releases/latest` | at most once per 24h, toggleable in the menu |

None of these carry your usage data, your prompts, or your conversation content. The status, pricing, and update endpoints are plain unauthenticated GETs.

### Credential access

To read Antigravity quota, usage reads the OAuth credential that the Antigravity CLI already stores on your machine — the **macOS Keychain** or the **Windows Credential Manager**. This access is read-only: usage never writes or modifies the credential, and never sends it anywhere except Google's own token and quota endpoints, exactly as the Antigravity CLI itself does. If you don't use Antigravity, no credential is ever read.

Claude Code and Codex require no credential access whatsoever.

### About the OAuth client constants in the source

`agy_quota_probe.py` contains Antigravity's installed-app OAuth client ID and client secret in plain text. This is deliberate, and it is not a leaked credential:

- Under [RFC 8252](https://datatracker.ietf.org/doc/html/rfc8252), an installed application cannot keep a client secret confidential. Such a secret is not a security boundary, and OAuth treats these clients as public.
- It is **not your credential** and grants no access on its own. The actual authorization comes from the OAuth token already on your machine, which only you have.
- Automated scanners flag the `GOCSPX-` prefix on sight. That match is expected here.

If Google ever rotates or revokes these constants, `usage` simply stops showing Antigravity quota — the token request fails, the probe returns nothing, and Claude Code, Codex, and every other feature keep working.
