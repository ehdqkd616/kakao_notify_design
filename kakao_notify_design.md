# 카카오톡 PC 채팅방별 알림음 커스터마이저 설계서

**프로젝트명:** KakaoTalk Notification Sound Customizer  
**버전:** v1.0  
**작성일:** 2026-06-16  
**개발 환경:** Python / VS Code / Windows 10 이상

---

## 1. 프로젝트 개요

### 1.1 목적

카카오톡 PC 버전은 채팅방별 알림음 설정 기능을 제공하지 않는다. 본 프로젝트는 Windows 토스트 알림을 가로채어 채팅방(발신자) 이름을 식별하고, 사용자가 지정한 알림음을 재생함으로써 해당 기능을 소프트웨어적으로 구현하는 것을 목적으로 한다.

### 1.2 핵심 아이디어

```
카카오톡 알림 발생
       ↓
Windows 토스트 알림 감지 (WinRT API)
       ↓
알림 제목(채팅방 이름) 파싱
       ↓
사용자 정의 룰과 매칭
       ↓
카카오톡 기본 알림음 억제 (음소거)
       ↓
지정된 .mp3 / .wav 재생
```

### 1.3 범위 및 제한

- **지원 OS:** Windows 10 / 11
- **지원 앱:** 카카오톡 PC (Windows Store 버전 포함)
- **미지원:** 카카오톡 알림 내용(메시지 본문) 파싱 — 프라이버시 이슈
- **미지원:** macOS 버전 카카오톡

---

## 2. 시스템 아키텍처

### 2.1 전체 구조

```
┌─────────────────────────────────────────────┐
│              KakaoNotify App                │
│                                             │
│  ┌──────────────┐    ┌────────────────────┐ │
│  │ Notification │    │   Sound Engine     │ │
│  │  Listener    │───▶│  (pygame / playsound)│ │
│  └──────────────┘    └────────────────────┘ │
│         │                                   │
│  ┌──────────────┐    ┌────────────────────┐ │
│  │ Rule Manager │    │   Config Manager   │ │
│  │  (matcher)   │◀──▶│   (rules.json)     │ │
│  └──────────────┘    └────────────────────┘ │
│         │                                   │
│  ┌──────────────┐                           │
│  │  System Tray │                           │
│  │     GUI      │                           │
│  └──────────────┘                           │
└─────────────────────────────────────────────┘
```

### 2.2 모듈 구성

| 모듈 | 파일 | 역할 |
|------|------|------|
| Notification Listener | `listener.py` | WinRT API로 토스트 알림 구독 |
| Rule Manager | `rule_manager.py` | 채팅방-알림음 매핑 룰 관리 |
| Sound Engine | `sound_engine.py` | 지정 음원 재생 |
| Config Manager | `config.py` | rules.json 읽기/쓰기 |
| System Tray GUI | `tray_app.py` | 트레이 아이콘 및 설정 UI |
| Main Entry | `main.py` | 앱 진입점, 스레드 관리 |

---

## 3. 모듈 상세 설계

### 3.1 Notification Listener (`listener.py`)

#### 역할
Windows Runtime의 `UserNotificationListener` API를 통해 수신되는 모든 토스트 알림을 실시간으로 감지하고, 카카오톡 발신 알림만 필터링한다.

#### 주요 기술
- `winsdk` 또는 `winrt` Python 패키지 활용
- `UserNotificationListener.RequestAccessAsync()` 로 권한 요청
- 알림 이벤트 콜백 등록 → 제목(AppDisplayName, Title) 추출

#### 핵심 로직

```python
from winrt.windows.ui.notifications.management import UserNotificationListener
from winrt.windows.ui.notifications import KnownNotificationBindings
import asyncio

class NotificationListener:
    def __init__(self, callback):
        self.callback = callback  # Rule Manager에 전달할 콜백

    async def start(self):
        listener = UserNotificationListener.current
        # 권한 요청
        access = await listener.request_access_async()
        # 알림 수신 이벤트 등록
        listener.add_notification_changed(self._on_notification)

    def _on_notification(self, sender, args):
        notifs = sender.get_notifications_for_app("카카오톡")
        for notif in notifs:
            title = notif.notification.visual \
                       .get_binding(KnownNotificationBindings.toast_generic()) \
                       .get_text_elements()[0].text  # 채팅방 이름
            self.callback(title)
```

#### 주의사항
- Windows 10 1903 이상에서만 `UserNotificationListener` 사용 가능
- 알림 접근 권한(사용자 동의) 필요
- 알림 제목이 `"카카오톡"` 고정인 경우, 바인딩에서 첫 번째 텍스트 요소가 채팅방 이름

---

### 3.2 Rule Manager (`rule_manager.py`)

#### 역할
채팅방 이름과 알림음 파일 경로를 매핑하는 룰을 관리하고, 수신된 채팅방 이름에 맞는 음원 경로를 반환한다.

#### 룰 우선순위

1. **정확히 일치 (Exact match)** — "가족방" → family.mp3
2. **키워드 포함 (Contains)** — "팀" 포함 → team.mp3
3. **기본값 (Default)** — 매칭 없을 경우 default.mp3
4. **무시 (Mute)** — 특정 채팅방 알림음 없음 설정

#### 데이터 구조 (rules.json)

```json
{
  "rules": [
    {
      "id": "rule_001",
      "type": "exact",
      "keyword": "가족방",
      "sound": "sounds/family.mp3",
      "mute": false
    },
    {
      "id": "rule_002",
      "type": "contains",
      "keyword": "팀",
      "sound": "sounds/team.wav",
      "mute": false
    },
    {
      "id": "rule_003",
      "type": "exact",
      "keyword": "광고",
      "sound": "",
      "mute": true
    }
  ],
  "default_sound": "sounds/default.mp3",
  "kakao_mute": true
}
```

#### 매칭 알고리즘

```python
def match(self, chat_name: str) -> str | None:
    # 1단계: Exact match
    for rule in self.rules:
        if rule["type"] == "exact" and rule["keyword"] == chat_name:
            return None if rule["mute"] else rule["sound"]
    # 2단계: Contains match
    for rule in self.rules:
        if rule["type"] == "contains" and rule["keyword"] in chat_name:
            return None if rule["mute"] else rule["sound"]
    # 3단계: Default
    return self.default_sound
```

---

### 3.3 Sound Engine (`sound_engine.py`)

#### 역할
지정된 음원 파일을 재생하며, 동시에 여러 알림이 올 경우 큐잉(Queuing) 또는 중단 후 재생 방식을 지원한다.

#### 지원 포맷
- `.mp3`, `.wav`, `.ogg`

#### 사용 라이브러리
- `pygame.mixer` (권장 — 비동기 재생, 다중 포맷 지원)
- fallback: `playsound`

```python
import pygame
import threading

class SoundEngine:
    def __init__(self):
        pygame.mixer.init()

    def play(self, sound_path: str):
        def _play():
            sound = pygame.mixer.Sound(sound_path)
            sound.play()
        threading.Thread(target=_play, daemon=True).start()
```

---

### 3.4 Config Manager (`config.py`)

#### 역할
`rules.json` 파일의 읽기/쓰기를 담당하며, 앱 설정(시작 시 자동실행, 카카오톡 기본 알림 음소거 여부 등)을 관리한다.

#### 설정 항목

| 키 | 타입 | 설명 |
|----|------|------|
| `kakao_mute` | bool | 카카오톡 기본 알림음 음소거 여부 |
| `default_sound` | string | 기본 알림음 경로 |
| `autostart` | bool | Windows 시작 시 자동 실행 |
| `rules` | array | 채팅방별 룰 목록 |

---

### 3.5 System Tray GUI (`tray_app.py`)

#### 역할
상시 백그라운드 실행을 위한 시스템 트레이 아이콘 제공 및 룰 편집 UI 제공.

#### 사용 라이브러리
- `pystray` — 트레이 아이콘
- `tkinter` — 설정 창 UI

#### 트레이 메뉴 구성

```
[KakaoNotify]
├── 설정 열기
├── 활성화 / 비활성화 (토글)
├── ─────────────────
└── 종료
```

#### 설정 창 기능
- 룰 목록 테이블 (채팅방 이름 / 타입 / 음원 파일)
- 룰 추가 / 삭제 / 수정
- 음원 파일 탐색기 연결
- 카카오톡 기본 알림음 음소거 토글
- 저장 버튼 → rules.json 업데이트

---

## 4. 데이터 흐름

```
[카카오톡 알림 발생]
        │
        ▼
[listener.py: 토스트 알림 캐치]
  - 앱 이름 필터: "카카오톡"
  - 제목(채팅방 이름) 추출
        │
        ▼
[rule_manager.py: 룰 매칭]
  - Exact → Contains → Default 순서
  - mute 여부 확인
        │
     ┌──┴──┐
   mute   sound_path
     │       │
  무시     ▼
         [sound_engine.py: 음원 재생]
          - pygame.mixer로 비동기 재생
```

---

## 5. 카카오톡 기본 알림음 억제 방법

### 방법 A: Windows 볼륨 믹서 API (권장)

`pycaw` 라이브러리로 카카오톡 프로세스의 오디오 세션 볼륨을 0으로 설정.

```python
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume

def mute_kakao():
    sessions = AudioUtilities.GetAllSessions()
    for session in sessions:
        if session.Process and "kakaotalk" in session.Process.name().lower():
            volume = session._ctl.QueryInterface(ISimpleAudioVolume)
            volume.SetMasterVolume(0.0, None)
```

### 방법 B: 타이밍 기반 음소거

알림 감지 즉시 → 카카오톡 볼륨 0 → 커스텀 사운드 재생 → 0.5초 후 볼륨 복원.

> **주의:** 방법 B는 볼륨 복원 타이밍에 따라 카카오톡 기본 알림음이 일부 들릴 수 있음.

---

## 6. 프로젝트 디렉토리 구조

```
kakao-notify/
├── main.py              # 진입점
├── listener.py          # 알림 리스너
├── rule_manager.py      # 룰 매칭
├── sound_engine.py      # 음원 재생
├── config.py            # 설정 관리
├── tray_app.py          # 트레이 GUI
├── rules.json           # 사용자 룰 파일
├── sounds/              # 알림음 파일 보관
│   ├── default.mp3
│   └── (사용자 추가 파일)
├── assets/
│   └── icon.ico         # 트레이 아이콘
├── requirements.txt
└── README.md
```

---

## 7. 개발 환경 및 의존성

### requirements.txt

```
winrt-Windows.UI.Notifications==2.3.0
winrt-Windows.UI.Notifications.Management==2.3.0
pygame==2.6.0
pycaw==20240210
pystray==0.19.5
Pillow==10.3.0
```

### 개발 환경 세팅 (VS Code)

```bash
# 가상환경 생성
python -m venv venv
venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt

# 실행
python main.py
```

### 권장 VS Code 익스텐션
- Python (Microsoft)
- Pylance
- Python Debugger

---

## 8. 개발 단계 (Phase)

| Phase | 내용 | 예상 소요 |
|-------|------|----------|
| Phase 1 | 알림 감지 프로토타입 (listener.py 단독 테스트) | 1일 |
| Phase 2 | 룰 매칭 + 음원 재생 연동 | 1일 |
| Phase 3 | 카카오톡 기본 알림음 음소거 구현 | 1일 |
| Phase 4 | 트레이 GUI + 설정 창 | 2일 |
| Phase 5 | 패키징 (.exe) + 테스트 | 1일 |

---

## 9. 위험 요소 및 대응

| 위험 | 가능성 | 대응 |
|------|--------|------|
| 카카오톡 앱이 알림 제목에 채팅방 이름을 포함하지 않을 수 있음 | 중간 | 알림 바인딩의 모든 텍스트 요소 로깅 후 파싱 구조 확인 |
| Windows 버전에 따른 WinRT API 미지원 | 낮음 | Windows 10 1903 이상 최소 요구사항 명시 |
| 카카오톡 업데이트로 알림 구조 변경 | 낮음 | 알림 파싱 로직 분리하여 업데이트 용이하게 설계 |
| 음소거 타이밍 불일치로 기본 알림음 누출 | 중간 | pycaw 볼륨 제어 방식(방법 A) 우선 적용 |

---

## 10. 향후 확장 가능성

- **정규식 매칭** 지원 (예: `^[0-9]+명$` → 단체방 감지)
- **시간대별 알림음 변경** (업무 시간 / 야간 모드)
- **알림 로그** 기능 (어떤 채팅방에서 몇 건 왔는지 통계)
- **exe 패키징** — PyInstaller로 단일 실행 파일 배포
- **자동 시작** — Windows 레지스트리 등록
