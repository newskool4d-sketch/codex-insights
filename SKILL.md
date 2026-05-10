---
name: codex-insights
description: Generate Claude Code /insights-style reports for Codex by analyzing local Codex sessions, history, tool usage, friction signals, work themes, and environment audit reports. Use when the user asks for Codex insights, usage analysis, 사용 분석, 시사점, 작업 패턴, 마찰 요인, 추천 액션, weekly/monthly Codex report, or /insights-like reporting.
metadata:
  short-description: Codex 사용 분석 리포트 생성
---

# Codex Insights

## Purpose

Generate a Codex-native usage report similar in spirit to Claude Code `/insights`.

This skill analyzes local Codex data and produces a concise Markdown report covering:

- usage volume and cadence
- common work themes
- tool and command patterns
- friction/error signals
- inefficient or disruptive command patterns
- environment health references
- practical improvement recommendations with command or prompt examples

Use `vibe-sunsang-codex` when the user wants mentoring or request-quality coaching. Use `codex-env-audit` when the user wants environment health checks. Use this skill when the user wants an insights-style report that combines usage patterns and operational implications.

## Data Sources

Default sources:

- `$env:USERPROFILE\.codex\sessions\YYYY\MM\DD\*.jsonl`
- `$env:USERPROFILE\.codex\history.jsonl`
- `$env:USERPROFILE\.codex\session_index.jsonl`
- `$env:USERPROFILE\.codex\reports\*.md`

The script reads session logs but does not print secrets. It ignores large system prompts and focuses on user/assistant messages, tool calls, tool outputs, and error signals.

## Workflow

1. Determine the date range or session count. If unspecified, use the script default: the latest 50 session files.
2. Run the report script:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -Limit 50
```

3. Read the generated report, then add human judgment when the user asks for interpretation.
4. If the report reveals environment friction, optionally run `codex-env-audit` next.
5. If the report reveals request-quality or workflow habits, optionally use `vibe-sunsang-codex` for deeper coaching.

## Useful Parameters

```powershell
# Recent 30 sessions
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -Limit 30

# Specific date range
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -Since 2026-05-01 -Until 2026-05-10

# Custom output directory
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -OutputDir "$env:USERPROFILE\.codex\reports"
```

## Report Reading Rules

- Treat counts as directional, not perfect telemetry.
- Distinguish local environment issues from model behavior issues.
- Do not overstate conclusions from small samples.
- Prefer concrete next actions over generic advice.
- Mention whether connector OAuth was actually tested or only inferred from logs.

## Sandbox Note

The default output location is outside normal workspace-write roots. In sandboxed Codex sessions, either approve writing to `.codex\reports` when prompted or pass `-OutputDir` with a writable workspace path for temporary reports.
## Output Location

Reports are written by default to:

```text
%USERPROFILE%\.codex\reports\codex-insights-YYYYMMDD-HHMMSS.md
```
