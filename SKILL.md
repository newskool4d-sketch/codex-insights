---
name: codex-insights
description: Generate Claude Code /insights-style reports for Codex by analyzing local Codex sessions, history, tool usage, friction signals, work themes, and environment audit reports. Produces an HTML dashboard with per-session LLM facet classification and narrative sections. Use when the user asks for Codex insights, usage analysis, 사용 분석, 시사점, 작업 패턴, 마찰 요인, 추천 액션, weekly/monthly Codex report, or /insights-like reporting.
metadata:
  short-description: Codex 사용 분석 HTML 대시보드 생성
---

# Codex Insights

## Purpose

Generate a Codex-native usage report that mirrors Claude Code `/insights`:
a single-file HTML dashboard combining deterministic session statistics,
per-session LLM facet classification, and agent-written narrative sections.

## Architecture (mirrors Claude Code usage-data)

| Stage | Who runs it | Output |
|---|---|---|
| 1. extract | script (deterministic) | `~/.codex/insights-data/session-meta/<id>.json` — per-session stats, cached incrementally |
| 2. facets | **you (the agent)** classify each pending session digest | `~/.codex/insights-data/facets/<id>.json` |
| 3. aggregate | script | `~/.codex/insights-data/aggregate.json` |
| 4. narrative | **you (the agent)** write narrative sections from aggregate + facets | `~/.codex/insights-data/narrative.json` |
| 5. render | script | `~/.codex/memories/reports/codex-insights-<stamp>.html` (+ stable alias `codex-insights-report.html`) |

Caches are per-session-ID, so reruns only process new sessions.

## Operating Modes

| Mode | Use when | What to do |
|---|---|---|
| Full insights (default) | "인사이트", "사용 분석", "/insights처럼", weekly/monthly report | Run the full 5-stage workflow below. |
| Quick snapshot | brief 상태 확인, "quick insights", no time for faceting | Run `run --limit 30` once (placeholders for missing narrative), summarize stats + top friction + one next action. Or use the legacy Markdown script. |
| Bounded comparison | weekly/monthly trends, date ranges | Use `--since 7d` / `--since YYYY-MM-DD --until YYYY-MM-DD`; state window and sample size. |
| Follow-up action | "what next", fix a pattern from a prior report | Use the report's recommendations or route to `codex-env-audit`, `vibe-sunsang-codex`, `codex-closeout-routine`. |

## Workflow (Full insights)

All commands run from any directory. `PIPELINE` below means:
`python "$env:USERPROFILE\.codex\skills\codex-insights\scripts\codex_insights.py"`

1. **Extract**: `PIPELINE extract --limit 50` (or `--since 7d`).
2. **Digest**: `PIPELINE digest --limit 50` — prints `pending_ids` for sessions without facets and writes a digest per pending session to `insights-data/digests/<id>.md`.
3. **Classify facets (you)**: for each pending ID — batch up to ~20 per run, newest first if you must cap — read `digests/<id>.md` and write `insights-data/facets/<id>.json` using the Facet Schema below. Base every field on digest evidence only; do not invent. If evidence is thin, use `"unclear"`/empty values.
4. **Aggregate**: `PIPELINE aggregate --limit 50`.
5. **Write narrative (you)**: read `insights-data/aggregate.json` (notably `session_summaries`, `goal_categories`, `error_categories`, `friction_counts`, derived stats) and write `insights-data/narrative.json` using the Narrative Schema below.
6. **Render**: `PIPELINE render` — prints the report path. Verify the file exists before reporting success.

If the user wants only a refresh of numbers, `PIPELINE run --limit 50` performs extract→digest→aggregate→render in one pass (narrative/facets stay as cached).

## Facet Schema (`facets/<id>.json`)

```json
{
  "session_id": "<id>",
  "underlying_goal": "one sentence: what the user actually wanted",
  "goal_categories": {"feature_implementation": 1, "bug_fix": 1},
  "outcome": "fully_achieved | mostly_achieved | partially_achieved | not_achieved | unclear",
  "session_type": "multi_task | single_task | iterative_refinement | quick_question",
  "user_satisfaction": "satisfied | likely_satisfied | neutral | likely_frustrated | frustrated",
  "codex_helpfulness": "very_helpful | helpful | somewhat_helpful | not_helpful",
  "friction_counts": {"path_errors": 2},
  "friction_detail": "one sentence; empty string if none",
  "primary_success": "short snake_case label for what worked best",
  "brief_summary": "2-3 sentence neutral summary of the session"
}
```

Goal category vocabulary (extend only when nothing fits): `feature_implementation`,
`bug_fix`, `refactoring`, `code_review`, `troubleshooting`, `environment_configuration`,
`plugin_installation`, `skill_execution`, `skill_development`, `report_generation`,
`document_conversion`, `document_drafting`, `data_analysis`, `automation_setup`,
`repo_analysis`, `version_control`, `session_closeout`, `question_answer`, `research`.

## Narrative Schema (`narrative.json`)

```json
{
  "generated": "YYYY-MM-DD HH:MM:SS",
  "at_a_glance": {
    "whats_working": "2-3 sentences on effective habits, cite evidence",
    "whats_hindering": "2-3 sentences: Codex-side issues AND user-side issues",
    "quick_wins": "2-3 concrete, immediately applicable suggestions",
    "ambitious": "1-2 sentences on bolder workflows now within reach"
  },
  "work_areas": [
    {"name": "Area name", "sessions": "~N sessions", "description": "2-3 sentences on what was built/done and how it was verified"}
  ],
  "how_you_use": "1 paragraph persona analysis: batching style, verification habits, delegation, language mix",
  "big_wins": [{"title": "...", "description": "1-2 sentences with concrete evidence"}],
  "friction_categories": [
    {"title": "...", "description": "what goes wrong and why", "examples": ["short real example", "..."]}
  ],
  "features_to_try": [{"title": "Codex feature", "why": "tied to observed patterns", "example": "copyable prompt or command"}],
  "new_patterns": [{"title": "...", "detail": "...", "prompt": "copyable prompt"}],
  "horizon": [{"title": "...", "possible": "what becomes possible", "tip": "how to prepare"}]
}
```

Narrative rules:

- 3-5 `work_areas`, grouped from `session_summaries` + `goal_categories`; counts are approximate ("~N sessions").
- Every claim must trace to aggregate/facet evidence. No generic productivity advice.
- `friction_categories`: separate environment friction (auth, sandbox, paths, encoding) from workflow friction (vague prompts, scope drift). Use `error_categories` + `friction_counts` + `friction_detail` evidence.
- Write narrative text in the user's working language (Korean for this user), keeping technical terms in English.
- Never include secrets, tokens, or personal data in narrative or facets.

## Expert Interpretation Rules

- Separate **volume** from **friction**: high tool count can be healthy discovery; repeated failures, auth errors, or path errors are operational risk.
- Separate **environment risk** from **workflow risk**: OAuth, permission, sandbox, and path issues need preflight checks; vague requests or long clarification loops need prompt/workflow changes.
- Prioritize one action that changes future behavior, not a list of generic tips.
- Use confidence language: report facet coverage (shown in the report header) and sample size; low coverage means "directional signal", not proof.
- When the report recommends another skill, do not run it automatically unless the user asked for follow-up action.

## Response Contract

When reporting results to the user, include:

- report path (and that the stable alias `codex-insights-report.html` was updated)
- sample scope: session count, period, facet coverage (e.g. "facets 42/50")
- top diagnosis in 1-2 sentences
- the most important next action
- verification: confirm the output file exists

Do not paste the full report into chat unless asked.

## Legacy Markdown Mode

The original PowerShell generator remains available for a fast, no-LLM Markdown report:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -Limit 30
```

## Sandbox Note

Default writable locations: `.codex\insights-data` and `.codex\memories\reports`.
If writing fails with `Access denied`/sandbox errors, rerun after approval or pass
`--out-dir` to a confirmed writable path. Do not claim a report was generated until
the output file exists.

## Data Sources

- `%USERPROFILE%\.codex\sessions\YYYY\MM\DD\*.jsonl` (events: session_meta, turn_context, event_msg user/agent messages, token_count, function_call/_output)
- `%USERPROFILE%\.codex\insights-data\` (pipeline caches)
- `%USERPROFILE%\.codex\memories\reports\codex-env-audit-*.md` (optional cross-reference)

The pipeline reads session logs but never echoes secrets; system/developer prompts and
injected context are excluded from digests and qualitative interpretation.
