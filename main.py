import asyncio
import threading

from config import ConfigManager
from listener import NotificationListener
from rule_manager import RuleManager
from sound_engine import KakaoMuteController, SoundEngine
from tray_app import TrayApp


class KakaoNotifyApp:
    def __init__(self):
        self.config = ConfigManager()
        self.rule_manager = RuleManager(self.config)
        self.sound_engine = SoundEngine()
        self.mute_ctrl = KakaoMuteController()
        self.listener = NotificationListener(self._on_notification)
        self.tray = TrayApp(self.config, self.rule_manager, on_quit=self._on_quit)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False

    # ── 알림 수신 콜백 ──────────────────────────────

    def _on_notification(self, chat_name: str) -> None:
        if not self.tray.is_active:
            return

        sound_path = self.rule_manager.match(chat_name)

        if self.config.kakao_mute:
            self.mute_ctrl.mute()

        if sound_path:
            self.sound_engine.play(sound_path)

    # ── 종료 ────────────────────────────────────────

    def _on_quit(self) -> None:
        print("[Main] 종료 중...")
        self._running = False

        # 카카오톡 볼륨 복원
        if self.config.kakao_mute:
            self.mute_ctrl.unmute()

        self.sound_engine.cleanup()
        self.listener.stop()

        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)

    # ── 비동기 리스너 루프 ──────────────────────────

    def _run_async(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception as e:
            print(f"[Main] 비동기 루프 오류: {e}")
        finally:
            self._loop.close()

    async def _async_main(self) -> None:
        try:
            await self.listener.start()
            self._running = True
            while self._running:
                await asyncio.sleep(1)
        except PermissionError as e:
            print(f"[Main] 권한 오류: {e}")
        except RuntimeError as e:
            print(f"[Main] 리스너 초기화 오류: {e}")
        except asyncio.CancelledError:
            pass
        finally:
            self.listener.stop()

    # ── 진입점 ──────────────────────────────────────

    def run(self) -> None:
        if self.config.kakao_mute:
            self.mute_ctrl.mute()

        async_thread = threading.Thread(target=self._run_async, daemon=True, name="AsyncListener")
        async_thread.start()

        print("[Main] KakaoNotify 시작 — 트레이 아이콘을 확인하세요.")
        self.tray.run()  # 메인 스레드 블로킹 (pystray 요구사항)

        async_thread.join(timeout=3)
        print("[Main] KakaoNotify 종료 완료")


if __name__ == "__main__":
    app = KakaoNotifyApp()
    app.run()
