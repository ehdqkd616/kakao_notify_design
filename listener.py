"""
카카오톡 PC(Win32 설치본)는 Windows 토스트 알림 시스템을 사용하지 않아
UserNotificationListener로 감지되지 않는다.
대신 EnumWindows로 카카오톡 프로세스의 새 창을 0.3초마다 폴링하여
알림 팝업 창이 생성되는 순간을 감지한다.
"""
import asyncio
import ctypes
import ctypes.wintypes
from typing import Callable

import psutil

_user32 = ctypes.windll.user32
_EnumWindowsProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
)

POLL_INTERVAL = 0.3  # 초

# 알림 팝업 창 클래스 이름 (EVA_Window_DblClk로 확인됨)
_NOTIFY_CLASS = "EVA_Window_DblClk"

# 같은 채팅방 알림이 연속으로 울리지 않도록 쿨다운 (초)
_COOLDOWN_SEC = 2.0


def _get_text(hwnd: int) -> str:
    n = _user32.GetWindowTextLengthW(hwnd)
    if not n:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    _user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _get_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _get_child_texts(hwnd: int) -> list[str]:
    """자식 창에서 텍스트를 모두 수집한다."""
    texts: list[str] = []

    @_EnumWindowsProc
    def _cb(child, _):
        t = _get_text(child)
        if t:
            texts.append(t)
        return True

    _user32.EnumChildWindows(hwnd, _cb, 0)
    return texts


def _get_window_size(hwnd: int) -> tuple[int, int]:
    rect = ctypes.wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def _send_get_text(hwnd: int) -> str:
    """SendMessage(WM_GETTEXT)로 창 텍스트를 직접 읽는다.
    RichEdit 컨트롤은 WM_GETTEXTLENGTH가 0을 반환하는 경우가 있어
    큰 버퍼를 사용해 길이 확인 없이 직접 읽는다."""
    WM_GETTEXT = 0x000D
    buf = ctypes.create_unicode_buffer(2048)
    n = _user32.SendMessageW(hwnd, WM_GETTEXT, 2048, buf)
    return buf.value.strip() if n > 0 else ""


def _get_uia_name(hwnd: int) -> str:
    """UIAutomation으로 자식 요소를 탐색하고 실제 텍스트를 읽는다."""
    _skip = {"kakaotalk", "카카오톡", "richedit control", ""}
    try:
        import comtypes.client
        uia_lib = comtypes.client.GetModule("UIAutomationCore.dll")
        uia = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}",
            interface=uia_lib.IUIAutomation,
        )
        elem = uia.ElementFromHandle(hwnd)
        cond = uia.CreateTrueCondition()
        walker = uia.CreateTreeWalker(cond)
        child = walker.GetFirstChildElement(elem)
        while child:
            child_hwnd = child.CurrentNativeWindowHandle
            if child_hwnd and child_hwnd != hwnd:
                text = _send_get_text(child_hwnd)
                if text and text.lower() not in _skip:
                    return text
            child = walker.GetNextSiblingElement(child)
    except Exception as e:
        print(f"[Listener] UIA 오류: {e}")
    return ""


def _is_kakao_foreground(kakao_pids: set[int]) -> bool:
    """KakaoTalk이 현재 최전면 창인지 확인한다.
    사용자가 직접 창을 조작 중일 때 오발동을 방지하기 위해 사용."""
    hwnd = _user32.GetForegroundWindow()
    pid_buf = ctypes.wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
    return pid_buf.value in kakao_pids


def _get_kakao_pids() -> set[int]:
    return {
        p.pid for p in psutil.process_iter(["name"])
        if "kakaotalk" in (p.info.get("name") or "").lower()
    }


def _enum_kakao_windows(kakao_pids: set[int]) -> list[tuple[int, str, str]]:
    """카카오톡 프로세스 소속 최상위 창 목록을 반환."""
    results: list[tuple[int, str, str]] = []

    @_EnumWindowsProc
    def _cb(hwnd, _):
        pid_buf = ctypes.wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
        if pid_buf.value in kakao_pids:
            results.append((hwnd, _get_class(hwnd), _get_text(hwnd)))
        return True

    _user32.EnumWindows(_cb, 0)
    return results


class NotificationListener:
    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback
        self._running = False
        self._last_fired: dict[str, float] = {}

    async def start(self) -> None:
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        if not _get_kakao_pids():
            print("[Listener] 주의: 카카오톡 프로세스를 찾을 수 없습니다.")
        self._running = True
        print("[Listener] 시작")

    async def poll(self) -> None:
        import time
        prev_eva_hwnds: set[int] = set()
        tick = 0
        while self._running:
            try:
                pids = _get_kakao_pids()
                windows = _enum_kakao_windows(pids)

                if tick % 30 == 0:
                    print(f"[Listener] 폴링 중 — KakaoTalk 창 {len(windows)}개")
                tick += 1

                # EVA 팝업 클래스 창만 추려서 이전 폴과 비교
                current_eva = {
                    hwnd: (cls, title) for hwnd, cls, title in windows
                    if cls.lower() == _NOTIFY_CLASS.lower()
                }
                new_hwnds = set(current_eva) - prev_eva_hwnds
                prev_eva_hwnds = set(current_eva)

                for hwnd in new_hwnds:
                    cls, title = current_eva[hwnd]

                    # 크기 필터: 0×0(채팅창 전환) 및 너무 큰 창 제외
                    w, h = _get_window_size(hwnd)
                    if not (5 < w < 700 and 5 < h < 350):
                        continue

                    # title → 자식 창 → UIA 순으로 채팅방 이름 탐색
                    chat_name = title.strip()
                    if not chat_name:
                        for t in _get_child_texts(hwnd):
                            t = t.strip()
                            if t and t.lower() not in {"kakaotalk", "카카오톡"}:
                                chat_name = t
                                break
                    if not chat_name:
                        chat_name = _get_uia_name(hwnd)

                    # 이름을 못 읽은 채널 알림은 기본 알림음 대상으로 처리
                    if not chat_name:
                        chat_name = "_channel_"

                    print(f"[Listener] EVA창 감지: {w}×{h} | 채팅방='{chat_name}'")

                    # 쿨다운: 같은 채팅방 알림이 2초 내 중복 방지
                    now = time.monotonic()
                    if now - self._last_fired.get(chat_name, 0) < _COOLDOWN_SEC:
                        continue
                    self._last_fired[chat_name] = now

                    print(f"[Listener] 카카오톡 수신: '{chat_name}'")
                    self.callback(chat_name)

            except Exception as e:
                print(f"[Listener] 폴링 오류: {e}")

            await asyncio.sleep(POLL_INTERVAL)

    def stop(self) -> None:
        self._running = False
        print("[Listener] 감지 중지")
