<p align="center">
  <img src="docs/readme-logo.png" alt="usage 로고" width="128">
</p>

# usage

### macOS 메뉴 막대와 Windows 시스템 트레이에서 Claude Code, Codex, Antigravity 할당량을 확인하세요.

작업하는 동안 Claude Code, Codex, Antigravity 할당량을 계속 확인하세요. `usage`는 세션 한도, 주간 한도, 비용 정보를 macOS 메뉴 막대 또는 Windows 시스템 트레이에 표시하므로 세션이 중단되기 전에 사용량을 관리할 수 있습니다.

[繁體中文](README.zh-TW.md) · [简体中文](README.zh-CN.md) · [English](README.md) · [日本語](README.ja.md) · 한국어 &nbsp;|&nbsp; [Discussions](https://github.com/aqua5230/usage/discussions) &nbsp;|&nbsp; [공식 사이트](https://aqua5230.github.io/usage/)

[![CI](https://github.com/aqua5230/usage/actions/workflows/check.yml/badge.svg)](https://github.com/aqua5230/usage/actions/workflows/check.yml)
[![최신 릴리스](https://img.shields.io/github/v/release/aqua5230/usage)](https://github.com/aqua5230/usage/releases/latest)
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![플랫폼](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey.svg)](https://github.com/aqua5230/usage/releases/latest)
[![라이선스: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![OpenSSF 모범 사례](https://www.bestpractices.dev/projects/13538/badge)](https://www.bestpractices.dev/projects/13538)

<p align="center">
  <img src="docs/showcase.en.png" alt="usage — macOS 메뉴 막대에 고정된 Claude Code, Codex, Antigravity 할당량" width="820">
</p>

`usage`는 화면 오른쪽 상단에 **Claude Code, Codex, Antigravity** 할당량을 고정하고, 경고 수준을 한눈에 파악하도록 색상으로 구분합니다. Claude Code와 Codex의 수치는 이미 컴퓨터에 있는 로컬 파일에서 수동적으로 읽으며, 이를 읽을 때 **Anthropic 또는 OpenAI의 LLM API를 호출하지 않습니다**——그래서 할당량을 보는 것 자체가 token 사용량을 늘리지 않습니다. Antigravity 할당량은 Antigravity CLI가 이미 로컬에 저장해 둔 로그인 정보를 사용해 Google의 공식 할당량 엔드포인트에서 가져옵니다.

## 왜 usage인가요?

세션 중간에 할당량이 소진되면 비용이 큽니다. 특히 Claude Code에 의존하는 긴 리팩터링이나 디버깅 작업에서는 더욱 그렇습니다. `usage`는 한도에 도달하기 *전에* 5시간 및 주간 한도를 표시하고, 작업 내내 계속 보이게 합니다. 실행할 명령이나 열 페이지가 없습니다. 이미 보고 있는 곳에 답이 표시됩니다.

## 빠른 시작

```bash
brew install --cask aqua5230/usage/usage
```

Applications 폴더에 자동으로 설치됩니다. Gatekeeper를 통과하려면 한 번 마우스 오른쪽 버튼으로 클릭해 **Open**을 선택한 뒤 메뉴 막대 아이콘을 클릭하세요. 직접 다운로드하거나 전체 설정 과정을 보고 싶다면 아래 [설치](#설치)를 참고하세요.

## 제공 기능

### 실시간 가시성

- **상시 모니터:** 할당량이 메뉴 막대에 상시 표시되며, 녹색부터 빨간색까지 색상으로 구분됩니다. 전체 세션, 주간, 프로젝트별 내역이 필요하면 클릭하세요.
- **Antigravity 지원:** Antigravity(Gemini)의 세션 및 주간 할당량이 모든 패널에서 세 번째 카드로 나타납니다. 수치는 Antigravity CLI가 이미 컴퓨터에 저장해 둔 로그인 정보를 사용해 공식 할당량 API에서 직접 가져옵니다. 몇 분마다 자동 갱신되며 리셋 카운트다운도 실시간으로 줄어듭니다.
- **서비스 상태 경고:** Claude Code, Claude API 또는 Codex API에 장애나 성능 저하가 발생하면 관련 패널 하단에 주황색/빨간색 경고 배너가 표시되며, 수치는 공식 공개 Statuspage.io 페이지에서만 읽어옵니다(LLM 사용량 API는 절대 호출하지 않음). Antigravity는 공개 상태 페이지가 없으므로 지원되지 않습니다.
- **컨텍스트 알림 및 알림 센터:** 컨텍스트 창이 70%에 도달하면 상태 줄이 `/clear` 또는 `/compact`를 안내해 token 낭비를 막습니다. 할당량 한도와 복구에 관한 시스템 알림도 선택해 받을 수 있습니다.
- **섹션 숨기기:** 일부 도구만 사용하나요? 클릭 한 번으로 Claude Code, Codex 또는 Antigravity 섹션을 메뉴 막대와 패널에서 완전히 숨길 수 있습니다.

### 워크플로 도우미

- **진행 상황 컨시어지:** 새 Claude Code 세션을 열면 `usage`가 마지막 요청, 커밋하지 않은 변경 사항, 미완료 todo를 포함한 이전 진행 상황을 바로 AI에 전달합니다. `/resume`도, 요약도 필요 없습니다. 완전히 로컬에서 작동하며 기본값은 꺼짐입니다.
- **Token 절약기:** 메뉴 막대 토글은 Claude Code와 Codex에 해당 세션 동안 더 간결하게 답하도록 요청하여, 코드와 오류 메시지는 바이트 단위로 그대로 유지하면서 출력 token을 절약합니다. 가벼운 메시지별 알림이 긴 대화에서 답변이 다시 장황해지는 것을 막습니다——테스트 결과 대화 후반의 답변도 약 40% 더 짧게 유지됩니다.
- **Token 낭비 상태 점검:** 매일 백그라운드 진단이 로그를 검사해 반복 파일 읽기, 오염 디렉터리, 장황한 Bash 출력 등을 포함한 낭비를 찾습니다. 문제가 발견되면 한 줄 알림이 표시됩니다. AI에게 "show me"라고 말하면 해결 방법을 안내합니다.

### 보고서와 인사이트

- **심층 HTML 보고서:** 일간 및 주간 token 추세, 프로젝트 순위, 비용을 보여 주는 공유 가능한 HTML 심층 보고서입니다. 기여 히트맵 및 "Wrapped" 요약을 담은 Year in Review가 포함됩니다. "최근 작업" 섹션에는 Claude Code가 최근 대화에 붙인 이름이 나열되어 숫자를 맥락과 함께 볼 수 있습니다. .html, .csv 또는 .png로 내보낼 수 있으며 완전히 오프라인에서 작동하고 프로젝트 이름 마스킹도 선택할 수 있습니다(이 제목들도 함께 가려집니다).
- **TUI 및 CLI:** 터미널을 선호하나요? `python3 main.py --tui`로 풍부한 TUI 대시보드를 실행하거나 `python3 usage_cli.py report`로 심층 분석을 생성하세요.

### 경험과 사용자화

- **10가지 시각 테마:** Classic, Matrix, Windows 95, Newspaper, Cloud Observation, Midnight Aquarium, Prism Arcade, Black Hole, World Cup 2026, Lepidoptera(blueprint)를 포함한 패널 스타일을 전환할 수 있습니다.
- **패널 자유 배치:** 패널이 더 이상 메뉴 막대 아이콘 아래에 고정되지 않습니다. 빈 공간을 드래그해 원하는 위치로 이동할 수 있으며, 다음에 열 때도 그 위치가 유지됩니다. 다른 앱으로 포커스가 이동해도 사라지지 않으며, 메뉴 막대 아이콘을 다시 클릭하거나 Esc 키를 눌러야 닫힙니다.
- **드래그로 순서 변경:** 아무 할당량 카드나 잡고 위아래로 드래그하면 순서를 바꿀 수 있습니다. 배치는 모든 테마에서 공유되며 다시 시작해도 유지됩니다.
- **AI 인재 마켓:** 준비된 AI 팀을 Claude Code에 추가하세요. 엄선된 하위 에이전트 페르소나를 찾아 `~/.claude/agents/`에 즉시 설치할 수 있습니다. 번들 CLI를 통해 완전히 로컬에서 실행됩니다.
- **AI 원탁 토론:** 전용 창을 열어 Claude Code, Codex, Antigravity 간의 다중 라운드 토론을 진행합니다. 참여자, 모델, 토론 스타일을 선택할 수 있으며 시작 전에 token 예상치가 표시됩니다. 라운드 간에 토론 방향을 유도하고, 합의 집계에서 누구 반대하는지 확인하며, 전원이 동의하면 토론을 조기 종료할 수 있습니다. 각 자리에 AI 인재 마켓 페르소나를 부여하고 옵션인 읽기 전용 폴더를 통해 실제 파일을 참조할 수 있습니다.
- **AI 업데이트 일보:** 매일 자동 업데이트되는 공개 [웹 페이지](https://aqua5230.github.io/ai-updates/)를 열어 Claude Code, Codex, Antigravity의 업데이트를 다루고 전체 기록을 보존합니다. 심사가 완료된 업데이트는 5개 언어의 알기 쉬운 요약을, 미심사 항목은 공식 원문을 보여줍니다.
- **영적 동반자:** 작은 흰색 애니메이션 실루엣이 사용률 옆에 표시됩니다. Claude에는 불사조, Codex에는 용, Antigravity에는 사자가 함께하며 각자 해당 도구의 token 소모 속도가 올라갈수록 동작도 더 빨라집니다.
- **자동 현지화:** UI 텍스트는 번체 중국어, 간체 중국어, 영어, 일본어, 한국어로 제공되며 시스템 설정에 맞춰 자동으로 전환됩니다.

## 개인정보 보호와 데이터 소스

- Claude Code와 Codex의 수치는 컴퓨터의 **로컬 로그 파일에서만** 읽으며, 이를 읽을 때 **Anthropic 또는 OpenAI의 LLM API를 호출하지 않습니다**.
- Antigravity 할당량에는 네트워크 연결이 필요하며, 실제로 사용하는 경우에만 해당됩니다: 할당량은 Antigravity CLI가 로그인 후 저장한 OAuth 자격 증명으로 Google의 공식 할당량 엔드포인트에 조회해 가져옵니다——CLI 버전에 따라 macOS 키체인, Windows 자격 증명 관리자, 또는 로컬 token 파일에서 읽습니다. `usage`는 그 자격 증명을 다시 쓰지 않고 읽기만 하며, 갱신된 access token도 메모리에만 보관합니다. 이 호출 자체도 할당량 정보만 읽으며, 모델 할당량을 소비하는 일은 결코 없습니다.
- 백그라운드 네트워크 활동 범위: 위의 Antigravity 할당량/token 엔드포인트, 장애를 알리기 위한 Claude와 Codex의 공개 상태 페이지, 비용 추정을 위한 공개 모델 가격표(오프라인에서는 내장 가격으로 대체), 그리고 가끔 GitHub에서 새 버전을 확인하는 것입니다. Claude Code와 Codex의 로그 내용은 업로드되지 않습니다.

## 요구 사항

- macOS 12(Monterey) 이상, 또는 Windows 10/11
- Claude Code, Codex 또는 Antigravity를 한 번 이상 사용한 적이 있어야 합니다(로컬 사용량 데이터가 있어야 함).
- (소스 실행만 해당) Python 3.13.

## 설치

### 1. Homebrew(권장)

Homebrew로 설치하면 `brew upgrade --cask usage` 한 번으로 최신 상태를 유지할 수 있습니다.

```bash
brew install --cask aqua5230/usage/usage
```

*(첫 실행: Finder에서 `usage.app`을 마우스 오른쪽 버튼으로 클릭 → **Open**을 선택해 Gatekeeper를 통과합니다.)*

### 2. macOS용 App 다운로드

1. [GitHub Releases 페이지](https://github.com/aqua5230/usage/releases/latest)에서 최신 `usage.app.zip`을 다운로드합니다.
2. 압축을 풀고 `usage.app`을 Applications 폴더로 드래그합니다.
3. 첫 실행: Finder에서 `usage.app`을 마우스 오른쪽 버튼으로 클릭 → **Open** → Open을 확인합니다.

## Windows 지원

Windows에서도 핵심 기능을 모두 네이티브로 사용할 수 있습니다. TUI, Claude Code 상태 줄 hook, Codex 기록 분석을 지원합니다.[최신 GitHub Release](https://github.com/aqua5230/usage/releases/latest)에서 `usage-windows.zip`을 내려받아 압축을 풀고 `usage.exe`를 실행하면 됩니다. 설치는 필요하지 않습니다. 시스템 트레이 UI에는 Microsoft Edge WebView2 Runtime이 필요하며, 보통 Windows 10/11에 이미 포함되어 있습니다.

시스템 트레이 아이콘은 Claude 할당량 비율에 따라 업데이트되고, 도구 설명에는 Claude와 Codex의 각 창 요약이 표시됩니다. 왼쪽 클릭하면 WebView2에서 macOS와 같은 10개 테마 패널(Classic과 나머지 9개)을 열고, 오른쪽 클릭 메뉴에서는 패널 전환, 새로 고침, 로그인 시 실행, 업데이트 확인, 종료를 할 수 있습니다.

Windows의 차이점: 패널은 트레이 아이콘 옆이 아니라 작업 영역 오른쪽 아래에 열립니다. 업데이트 알림은 시스템 Yes/No 대화 상자를 사용합니다. AI Talent Market 및 AI 원탁 토론 패널은 macOS 전용입니다.

### 첫 실행: 상태 줄 설정

Codex를 사용한 적이 있다면 `usage`가 기록을 자동으로 가져옵니다. Claude Code의 경우 앱 팝오버에서 **"Set Up Status Line"** 버튼을 클릭하여 동기화 hook을 설치하세요.
그런 다음 해당 도구를 다시 시작하세요(Claude Code를 Cmd+Q로 완전히 종료한 뒤 다시 엽니다).

설정이 완료되면 Claude Code 창 하단에 다음과 같은 상태 줄이 표시됩니다.

<p align="center">
  <img src="docs/statusline.en.png" alt="Claude Code 상태 줄 표시(영어)" width="640">
</p>

## 테마 갤러리

UI에서 직접 **10가지 시각 테마**를 전환하세요.

<p align="center">
  <img src="docs/matrix.en.png" width="32%" alt="Matrix 테마" />
  <img src="docs/win95.en.png" width="32%" alt="Windows 95 테마" />
  <img src="docs/world_cup.en.png" width="32%" alt="World Cup HUD 테마" />
  <img src="docs/newspaper.en.png" width="32%" alt="Newspaper 테마" />
  <img src="docs/aquarium.en.png" width="32%" alt="Aquarium 테마" />
  <img src="docs/black_hole.en.png" width="32%" alt="Black Hole 테마" />
</p>

## 문제 해결

메뉴 막대에 `--`가 표시되면 대개 고장이 아니라 아직 로컬 데이터가 없다는 뜻입니다.

| 증상 | 가능한 원인 | 해결 방법 |
|---------|--------------|-----|
| 메뉴 막대에 `--` 표시 | 아직 데이터가 없거나 Claude Code hook이 갱신되지 않음 | Codex 대화를 한 번 실행하세요. Claude Code는 "상태 표시줄 설정"을 클릭하세요(소스에서 실행할 때는 `python3 main.py --setup`) |
| `usage.app` 안의 `main.py` 실행 시 `ImportError` | 번들에 포함된 `main.py`는 앱 내장 인터프리터가 필요해 직접 실행할 수 없음 | 그 파일은 실행하지 마세요. 앱에서 "상태 표시줄 설정"을 클릭하거나, 저장소를 clone해 소스에서 실행하세요 |
| 실수로 "Quit" 선택 | 프로세스가 종료됨 | Spotlight 또는 Applications에서 `usage.app`을 다시 실행하세요. (`launchctl start com.lollapalooza.usage`는 로그인 시 실행을 켜둔 경우에만 작동합니다.) |
| 상태에 "N minutes stale" 표시 | Claude Code가 실행 중이 아님 | Claude Code를 열고 실행 상태로 두세요 |
| Codex 섹션이 비어 있음 | Codex 기록을 찾지 못함 | Codex 대화를 실행하여 로그를 생성하세요 |
| 오늘 비용이 $0.00으로 표시 | 모델 가격 정보 없음 | `~/.usage/pricing_cache.json`을 삭제하거나 `USAGE_DEBUG=1`을 확인하세요 |
| Antigravity 카드가 표시되지 않음 | Antigravity CLI가 설치되지 않았거나 로그인되지 않음 | Antigravity CLI를 설치하고 로그인하세요. 백그라운드 할당량 조회가 성공하면 카드가 자동으로 나타납니다 |
| App이 열리지 않음 | macOS Gatekeeper가 차단함 | Finder에서 `usage.app`을 마우스 오른쪽 버튼으로 클릭 → Open |
| App이 즉시 충돌함(arm64) | 이전 버전의 py2app 번들링 bug | **v0.11.1 이상**으로 업그레이드하세요 |

## 비교

| 기능 | usage | ccusage | TokenTracker |
|---------|:-----:|:-------:|:------------:|
| 화면에 항상 표시 | ✅ | — | ✅ |
| macOS 메뉴 막대 | ✅ | — | ✅ |
| Claude Code 및 Codex 사용량 | ✅ | Claude 전용 | ✅ |
| Antigravity(Gemini) 사용량 | ✅ | — | — |
| Claude Code 및 Codex 서비스 상태 경고 | ✅ | — | — |
| HTML 심층 보고서 및 UI | ✅ | ✅ | — |
| AI 인재 마켓 | macOS 전용 | — | — |
| AI 원탁 토론 | macOS 전용 | — | — |
| AI 업데이트 일보 | ✅ | — | — |
| 진행 상황 컨시어지 및 Token 절약기 | ✅ | — | — |
| Token 낭비 상태 점검 | ✅ | — | — |
| 할당량 조회 시 LLM API 호출 없음 | ✅ | ✅ | ✅ |
| 오픈 소스 라이선스 | AGPL-3.0 | MIT | — |

## 개발

터미널 TUI 실행, 사용자 지정 에이전트 구성 또는 App 직접 빌드를 원하나요? **[개발 문서](docs/DEVELOPMENT.md)**를 확인하세요.

## 라이선스

AGPL-3.0-only로 라이선스됩니다([LICENSE](LICENSE) 참고). 수정한 버전을 fork하거나 재배포하는 경우, 원저자를 표기하고 다음 링크를 포함해 주세요.
https://github.com/aqua5230/usage

## Star 기록

<a href="https://star-history.com/#aqua5230/usage&Date">
  <img src="https://api.star-history.com/svg?repos=aqua5230/usage&type=Date" alt="usage Star 기록 차트" width="600">
</a>
