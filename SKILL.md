---
name: codex-insights
description: Generate Claude Code /insights-style reports for Codex by analyzing local Codex sessions, history, tool usage, friction signals, work themes, and environment audit reports. Use when the user asks for Codex insights, usage analysis, 사용 분석, 시사점, 작업 패턴, 마찰 요인, 추천 액션, weekly/monthly Codex report, or /insights-like reporting.
metadata:
  short-description: Codex 사용 분석 리포트 생성
---

# Codex Insights

## Purpose

Generate a Codex-native usage report similar in spirit to Claude Code `/insights`,
then interpret it as an operational review rather than a raw telemetry dump.

This skill analyzes local Codex data and produces a concise Markdown report covering:

- usage volume and cadence
- common work themes
- tool and command patterns
- friction/error signals
- recent-half vs prior-half change drivers
- inefficient or disruptive command patterns
- environment health references
- an expert triage summary with operating mode, main risk, confidence, and next action
- practical improvement recommendations with command or prompt examples
- copy/paste command presets for common follow-up actions

Use `vibe-sunsang-codex` when the user wants mentoring or request-quality coaching. Use `codex-env-audit` when the user wants environment health checks. Use this skill when the user wants an insights-style report that combines usage patterns and operational implications.

## Operating Modes

Choose the smallest mode that answers the user:

| Mode | Use when | Output |
|---|---|---|
| Quick snapshot | The user asks for a brief 상태 확인, 최근 패턴, or "quick insights" | Generate the report, then summarize `Expert Triage`, top friction, and one next action. |
| Expert review | The user asks for 전문가 관점, 개선점, 병목, 위험, or 운영 진단 | Generate the report, read `Expert Triage`, `Why Counts Changed`, `Inefficient Or Disruptive Signals`, and `Recommendations With Commands`, then provide a prioritized diagnosis. |
| Follow-up action | The user asks what to do next or asks to fix a pattern found in a prior report | Use the relevant preset or route to `codex-env-audit`, `vibe-sunsang-codex`, `skill-creator`, or `codex-closeout-routine`. |
| Bounded comparison | The user asks for weekly/monthly trends or a date range | Use `-Since` and `-Until`; explicitly state the date window and sample size. |

## Data Sources

Default sources:

- `$env:USERPROFILE\.codex\sessions\YYYY\MM\DD\*.jsonl`
- `$env:USERPROFILE\.codex\history.jsonl`
- `$env:USERPROFILE\.codex\session_index.jsonl`
- `$env:USERPROFILE\.codex\memories\reports\*.md`

The script reads session logs but does not print secrets. It ignores large system prompts and focuses on user/assistant messages, tool calls, tool outputs, and error signals.

## Workflow

1. Determine the date range or session count. If unspecified, use the script default: the latest 50 session files.
2. Run the report script:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -Limit 50
```

3. Read the generated report, then add human judgment when the user asks for interpretation.
4. Lead interpretation with the report's `Expert Triage` section. It is designed to separate the dominant work pattern from the dominant risk.
5. If the report reveals environment friction, optionally run `codex-env-audit` next.
6. If the report reveals request-quality or workflow habits, optionally use `vibe-sunsang-codex` for deeper coaching.

## Expert Interpretation Rules

- Separate **volume** from **friction**: high tool count can be healthy discovery; repeated failures, auth errors, or path errors are operational risk.
- Separate **environment risk** from **workflow risk**: OAuth, permission, sandbox, and path issues need preflight checks; vague requests or long clarification loops need prompt/workflow changes.
- Prioritize one action that changes future behavior, not a list of generic tips.
- Treat `Expert Triage` as the executive summary, then cite supporting evidence from lower sections.
- Use confidence language: low sample sizes and schema changes mean "directional signal", not proof.
- When the report recommends another skill, do not run it automatically unless the user asked for follow-up action or the next step is clearly required.

## Response Contract

When reporting results to the user, include:

- report path
- sample scope: session count and period
- top expert diagnosis in 1-2 sentences
- the most important next action
- verification: confirm the file exists

Do not paste the full generated report into chat unless the user asks.

## Useful Parameters

```powershell
# Recent 30 sessions
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -Limit 30

# Specific date range
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -Since 2026-05-01 -Until 2026-05-10

# Custom output directory
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -OutputDir "$env:USERPROFILE\.codex\memories\reports"
```

## Report Reading Rules

- Treat counts as directional, not perfect telemetry.
- Read `Expert Triage` first, then validate it against the detailed sections.
- Use the "Why Counts Changed" section to separate volume increases from likely causes.
- Distinguish local environment issues from model behavior issues.
- Do not overstate conclusions from small samples.
- Prefer concrete next actions over generic advice.
- Prefer copy/paste presets when the user asks what to run next.
- Mention whether connector OAuth was actually tested or only inferred from logs.
- Do not print secrets, tokens, private credentials, or unnecessary personal data from session logs.

## Sandbox Note

The default output location is the sandbox-writable report path `.codex\memories\reports`. Use this path for normal Codex-generated reports.

If report writing fails with `Access denied`, `permission`, or sandbox-related errors, rerun only after approval or use a confirmed writable path. In this environment, `.codex\reports`, `C:\tmp`, and the user profile root may require escalation from shell commands. Report which path failed and do not claim a fresh report was generated until the output file exists.
## Output Location

Reports are written by default to:

```text
%USERPROFILE%\.codex\memories\reports\codex-insights-YYYYMMDD-HHMMSS.md
```
