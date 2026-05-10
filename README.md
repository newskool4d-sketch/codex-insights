# Codex Insights Skill

Codex 세션 로그를 분석해 Claude Code `/insights`와 비슷한 사용 분석 리포트를 생성하는 Codex skill입니다.

이 스킬은 다음 항목을 Markdown 보고서로 정리합니다.

- 사용량과 메시지 통계
- 주요 작업 주제
- 도구 사용 패턴
- 주요 shell command 패턴
- 오류와 마찰 신호
- 반복 키워드
- 실행 명령이 포함된 추천 사항
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
| Recurring Keywords | 반복 키워드 |
| Recommendations With Commands | 실행 명령이 포함된 추천 사항 |
| Inefficient Or Disruptive Signals | 비효율 또는 작업 차질 신호와 개선 행동 |
| Environment Audit References | 최근 codex-env-audit 보고서 참조 |

## 함께 쓰면 좋은 skill

- `codex-env-audit`: 인증, 권한, MCP, skill, scheduled task 등 환경 점검
- `vibe-sunsang-codex`: 요청 품질, 회고, 성장 분석
- `codex-closeout-routine`: 세션 종료 기록과 handoff 정리

## 주의 사항

- 이 스킬은 세션 로그를 분석하지만, 인증 토큰이나 secret 값을 출력하도록 설계되어 있지 않습니다.
- 수치는 Codex 세션 로그 구조 변화에 따라 달라질 수 있으므로 정밀 통계가 아니라 방향성 지표로 보아야 합니다.
- OAuth나 connector 연결 상태는 로그 기반 신호일 뿐, 실제 연결 검증이 아닙니다.
- 실제 Google Drive, Notion, GitHub 등의 연결 상태를 확인하려면 별도 connector 테스트나 `codex-env-audit`를 함께 사용하세요.

## 업로드 시 제외할 것

GitHub 등에 공유할 때는 이 `codex-insights` 폴더만 업로드하세요.

다음 항목은 포함하지 마세요.

```text
%USERPROFILE%\.codex\auth.json
%USERPROFILE%\.codex\cap_sid
%USERPROFILE%\.codex\sessions
%USERPROFILE%\.codex\history.jsonl
%USERPROFILE%\.codex\logs_*.sqlite
%USERPROFILE%\.codex\state_*.sqlite
%USERPROFILE%\.codex\reports
%USERPROFILE%\.codex\plugins\cache
```

## 라이선스

개인 사용과 수정은 자유롭게 하되, 공개 배포 시에는 세션 로그나 개인 환경 파일이 포함되지 않았는지 반드시 확인하세요.