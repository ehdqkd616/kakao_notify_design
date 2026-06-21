import asyncio
from typing import Callable

try:
    from winrt.windows.ui.notifications.management import (
        UserNotificationListener,
        UserNotificationListenerAccessStatus,
    )
    from winrt.windows.ui.notifications import KnownNotificationBindings
    WINRT_AVAILABLE = True
except ImportError:
    WINRT_AVAILABLE = False
    print("[Listener] winrt 패키지 없음 — pip install winrt-Windows.UI.Notifications.Management")


class NotificationListener:
    # KakaoTalk 앱 이름 식별 키워드 (대소문자 무관)
    _KAKAO_KEYWORDS = ("kakao",)

    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback
        self._listener = None
        self._token = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._seen_ids: set[int] = set()

    async def start(self) -> None:
        if not WINRT_AVAILABLE:
            raise RuntimeError("winrt 패키지가 설치되지 않았습니다.")

        self._loop = asyncio.get_event_loop()
        self._listener = UserNotificationListener.current

        access = await self._listener.request_access_async()
        if access != UserNotificationListenerAccessStatus.ALLOWED:
            raise PermissionError(
                "알림 접근 권한이 없습니다.\n"
                "Windows 설정 > 개인 정보 보호 > 알림 에서 이 앱의 권한을 허용해주세요."
            )

        # 이미 존재하는 알림 ID를 수집하여 재처리 방지
        existing = await self._listener.get_notifications_async(0)
        self._seen_ids = {n.id for n in existing}

        self._token = self._listener.add_notification_changed(self._on_changed)
        print("[Listener] 카카오톡 알림 감지 시작")

    def _on_changed(self, sender, args) -> None:
        # change_kind: 0=Added, 1=Removed — Added 이벤트만 처리
        change_kind = getattr(args, "change_kind", 0)
        if change_kind != 0:
            return

        notification_id: int = args.user_notification_id
        if notification_id in self._seen_ids:
            return
        self._seen_ids.add(notification_id)

        # WinRT 콜백은 별도 스레드에서 호출되므로 async 작업을 루프에 예약
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._fetch_and_process(sender, notification_id),
                self._loop,
            )

    async def _fetch_and_process(self, sender, notification_id: int) -> None:
        try:
            all_notifs = await sender.get_notifications_async(0)
            for notif in all_notifs:
                if notif.id == notification_id:
                    self._process(notif)
                    return
        except Exception as e:
            print(f"[Listener] 알림 조회 오류: {e}")

    def _process(self, notif) -> None:
        try:
            # 앱 이름으로 카카오톡 필터링
            app_info = notif.app_info
            if app_info:
                display_name = app_info.display_info.display_name.lower()
                if not any(kw in display_name for kw in self._KAKAO_KEYWORDS):
                    return

            binding = notif.notification.visual.get_binding(
                KnownNotificationBindings.toast_generic()
            )
            if binding is None:
                return

            elements = list(binding.get_text_elements())
            if not elements:
                return

            chat_name: str = elements[0].text
            if chat_name:
                print(f"[Listener] 수신: '{chat_name}'")
                self.callback(chat_name)
        except Exception as e:
            print(f"[Listener] 파싱 오류: {e}")

    def stop(self) -> None:
        if self._listener and self._token is not None:
            try:
                self._listener.remove_notification_changed(self._token)
            except Exception:
                pass
            print("[Listener] 알림 감지 중지")
