# Codex Insights Skill

Codex 세션 로그를 분석해 Claude Code `/insights`와 같은 구조의 **HTML 대시보드 리포트**를
생성하는 Codex skill입니다. Claude Code의 usage-data 아키텍처(세션 메타 추출 → LLM facet
분류 → 내러티브 리포트)를 그대로 이식했습니다.

## 아키텍처

| 단계 | 실행 주체 | 산출물 |
|---|---|---|
| 1. extract | 스크립트 (결정적) | `~/.codex/insights-data/session-meta/<id>.json` — 세션별 통계, 증분 캐시 |
| 2. facets | **Codex 에이전트** (digest를 읽고 분류) | `~/.codex/insights-data/facets/<id>.json` |
| 3. aggregate | 스크립트 | `~/.codex/insights-data/aggregate.json` |
| 4. narrative | **Codex 에이전트** (집계 근거로 작성) | `~/.codex/insights-data/narrative.json` |
| 5. render | 스크립트 | `~/.codex/memories/reports/codex-insights-<stamp>.html` + 고정 별칭 `codex-insights-report.html` |

캐시는 세션 ID 단위이므로 재실행 시 새 세션만 처리됩니다.

## 구성

```text
codex-insights/
├── SKILL.md                          # 에이전트 워크플로우·facet/narrative 스키마
├── README.md
├── agents/
│   └── openai.yaml
└── scripts/
    ├── codex_insights.py             # 메인 파이프라인 (extract/digest/aggregate/render/run)
    └── New-CodexInsightsReport.ps1   # 레거시 Markdown 리포트 (LLM 불필요, 빠른 모드)
```

## 요구 조건

- Python 3.8+ (표준 라이브러리만 사용)
- `%USERPROFILE%\.codex\sessions`에 Codex 세션 로그(rollout JSONL)
- Windows 기준 작성 (한글 경로 안전: 모든 IO가 Python UTF-8 경유)

## 기본 실행

```powershell
# 전체 파이프라인 (최근 50세션, facet/narrative는 캐시된 것 사용)
python "$env:USERPROFILE\.codex\skills\codex-insights\scripts\codex_insights.py" run --limit 50

# 단계별 실행
python ...\codex_insights.py extract --limit 50     # 세션 메타 추출 (증분)
python ...\codex_insights.py digest  --limit 50     # facet 미분류 세션의 digest 생성 + pending 목록 출력
python ...\codex_insights.py aggregate --limit 50   # 집계
python ...\codex_insights.py render                 # HTML 렌더링
```

facet 분류와 내러티브 작성은 Codex 에이전트가 SKILL.md의 스키마에 따라 수행합니다.
스킬을 호출하면(`$codex-insights`) 에이전트가 위 단계와 분류·작성을 모두 진행합니다.

## 날짜 범위

```powershell
python ...\codex_insights.py run --since 7d              # 최근 7일
python ...\codex_insights.py run --since 2026-06-01 --until 2026-06-10
```

## 리포트 섹션 (Claude Code /insights 대응)

| Section | 내용 | 데이터 출처 |
|---|---|---|
| Header + Stats bar | 메시지·세션·기간·라인·파일·커밋·토큰 | session-meta |
| At a Glance | What's working / hindering / quick wins / ambitious | narrative (에이전트) |
| What You Work On | 작업 영역 카드 (~N sessions) | narrative + facets |
| What You Wanted | goal category 바 차트 | facets |
| Top Tools / Languages / Command Heads | 바 차트 | session-meta |
| Session Types / Outcomes | 바 차트 | facets |
| Activity by Hour / Weekday | 활동 분포 | session-meta |
| How You Use Codex | 사용 페르소나 분석 | narrative |
| Impressive Things You Did | big wins 카드 | narrative |
| Where Things Go Wrong | 마찰 카테고리 + 오류 차트 | narrative + 양쪽 집계 |
| Features to Try / New Patterns / Horizon | 복사 가능한 프롬프트 포함 제안 | narrative |
| Copy/Paste Command Presets | 실행 프리셋 (copy 버튼) | 고정 + 조건부 |

내러티브가 아직 없으면 해당 섹션은 placeholder로 표시되고 수치 차트는 그대로 제공됩니다.

## 레거시 Markdown 모드

LLM 단계 없이 빠르게 Markdown 리포트만 필요할 때:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -Limit 30
```

## 주의 사항

- 세션 로그를 분석하지만 토큰·secret 값을 리포트에 출력하지 않습니다.
- 수치는 Codex 세션 스키마 변화에 따라 달라질 수 있는 방향성 지표입니다.
- `lines_added/removed`·`files_modified`는 apply_patch 기반이므로, shell 편집(sed 등) 위주
  세션에서는 0으로 나올 수 있습니다.
- facet coverage(리포트 헤더 배지)가 낮으면 해석 신뢰도를 낮춰 읽어야 합니다.

## 함께 쓰면 좋은 skill

- `codex-env-audit`: 인증, 권한, MCP, skill, scheduled task 등 환경 점검
- `vibe-sunsang-codex`: 요청 품질, 회고, 성장 분석
- `codex-closeout-routine`: 세션 종료 기록과 handoff 정리
