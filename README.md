# Codex Insights Skill

Codex 세션 로그를 분석해 Claude Code `/insights`와 비슷한 사용 분석 리포트를 생성하는 Codex skill입니다.

이 스킬은 다음 항목을 Markdown 보고서로 정리합니다.

- 사용량과 메시지 통계
- 주요 작업 주제
- 도구 사용 패턴
- 주요 shell command 패턴
- 오류와 마찰 신호
- 최근 절반 세션과 이전 절반 세션의 변화 원인 후보
- 반복 키워드
- 실행 명령이 포함된 추천 사항
- 바로 복붙 가능한 실행 프리셋
- 비효율적이거나 작업에 차질을 줄 수 있는 신호

## 구성

```text
codex-insights/
├── SKILL.md
├── README.md
├── agents/
│   └── openai.yaml
└── scripts/
    └── New-CodexInsightsReport.ps1
```

## 설치 위치

이 폴더 전체를 사용자의 Codex skills 폴더 아래에 복사합니다.

```text
%USERPROFILE%\.codex\skills\codex-insights
```

예시:

```powershell
Copy-Item -Recurse -Force .\codex-insights "$env:USERPROFILE\.codex\skills\codex-insights"
```

## 요구 조건

- Codex가 설치되어 있어야 합니다.
- `%USERPROFILE%\.codex\sessions`에 Codex 세션 로그가 있어야 합니다.
- Windows PowerShell에서 실행하는 것을 기준으로 작성되었습니다.
- PowerShell 실행 정책 때문에 필요하면 `-ExecutionPolicy Bypass`를 사용합니다.

## 기본 실행

최근 50개 세션을 분석합니다.

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -Limit 50
```

## 날짜 범위 지정

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -Since 2026-05-01 -Until 2026-05-10
```

## 출력 위치 지정

기본 출력 위치는 다음과 같습니다.

```text
%USERPROFILE%\.codex\reports
```

sandbox나 권한 문제로 `.codex\reports`에 쓸 수 없을 때는 `-OutputDir`를 지정합니다.

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\codex-insights\scripts\New-CodexInsightsReport.ps1" -Limit 30 -OutputDir "$PWD"
```

## 보고서 섹션

생성되는 보고서는 다음 섹션을 포함합니다.

| Section | Description |
|---|---|
| At A Glance | 메시지, 이벤트, 평균 도구 호출, 오류 신호 요약 |
| Work Themes | 작업 주제별 빈도 |
| Tool Usage | Codex tool 사용 빈도 |
| Command Heads | PowerShell/shell command 앞부분 기준 사용 빈도 |
| Friction Signals | 오류, 권한, sandbox, OAuth 등 마찰 신호 |
| Why Counts Changed | 최근 절반과 이전 절반을 비교해 수치 증가 원인 후보 분류 |
| Recurring Keywords | 반복 키워드 |
| Recommendations With Commands | 실행 명령이 포함된 추천 사항 |
| Copy/Paste Command Presets | 상황별로 바로 실행하거나 지시할 수 있는 프리셋 |
| Inefficient Or Disruptive Signals | 비효율 또는 작업 차질 신호와 개선 행동 |
| Environment Audit References | 최근 codex-env-audit 보고서 참조 |

## 해석 방식

`Why Counts Changed`는 단순 누적값이 아니라 최근 절반 세션과 이전 절반 세션의 평균을 비교합니다. 도구 호출, 마찰 신호, 메시지 수가 늘었을 때 다음 원인 후보를 함께 표시합니다.

- 로컬 파일 탐색과 상태 확인이 늘어난 경우
- Git/GitHub 공개·배포 작업이 늘어난 경우
- OAuth, 권한, sandbox 경계 문제가 늘어난 경우
- Windows 경로, 한글 파일명, UTF-8 처리 문제가 늘어난 경우
- skill 제작이나 문서 반복 수정이 늘어난 경우

`Copy/Paste Command Presets`는 리포트를 읽은 뒤 바로 실행할 수 있는 명령어 또는 Codex에 그대로 줄 수 있는 작업 지시문입니다.

## 함께 쓰면 좋은 skill

- `codex-env-audit`: 인증, 권한, MCP, skill, scheduled task 등 환경 점검
- `vibe-sunsang-codex`: 요청 품질, 회고, 성장 분석
- `codex-closeout-routine`: 세션 종료 기록과 handoff 정리

## 주의 사항

- 이 스킬은 세션 로그를 분석하지만, 인증 토큰이나 secret 값을 출력하도록 설계되어 있지 않습니다.
- 수치는 Codex 세션 로그 구조 변화에 따라 달라질 수 있으므로 정밀 통계가 아니라 방향성 지표로 보아야 합니다.
- OAuth나 connector 연결 상태는 로그 기반 신호일 뿐, 실제 연결 검증이 아닙니다.
