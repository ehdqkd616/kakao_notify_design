import asyncio
import queue
import sys
import threading
from datetime import datetime

from config import ConfigManager
from listener import NotificationListener
from rule_manager import RuleManager
from sound_engine import KakaoMuteController, SoundEngine
from tray_app import TrayApp


# ── stdout 가로채기 ─────────────────────────────────────────────────────────
# print() 출력을 큐에 쌓아 로그 창에 실시간으로 전달한다.

class _LogRedirector:
    def __init__(self, log_queue: queue.Queue, original):
        self._queue = log_queue
        self._original = original
        self._buf = ""

    def write(self, text: str) -> None:
        # 원래 stdout에도 출력 (콘솔 실행 시)
        if self._original:
            try:
                self._original.write(text)
            except Exception:
                pass

        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                ts = datetime.now().strftime("%H:%M:%S")
                try:
                    self._queue.put_nowait(f"[{ts}]  {line}\n")
                except queue.Full:
                    pass

    def flush(self) -> None:
        if self._original:
            try:
                self._original.flush()
            except Exception:
                pass

    def __getattr__(self, name):
        return getattr(self._original, name)


# ── 앱 ──────────────────────────────────────────────────────────────────────

class KakaoNotifyApp:
    def __init__(self):
        self._log_queue: queue.Queue = queue.Queue(maxsize=2000)
        sys.stdout = _LogRedirector(self._log_queue, sys.__stdout__)

        self.config = ConfigManager()
        self.rule_manager = RuleManager(self.config)
        self.sound_engine = SoundEngine()
        self.mute_ctrl = KakaoMuteController()
        self.listener = NotificationListener(self._on_notification)
        self.tray = TrayApp(
            self.config, self.rule_manager,
            log_queue=self._log_queue,
            on_quit=self._on_quit,
        )
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
            await self.listener.poll()
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
        self.tray.run()

        async_thread.join(timeout=3)
        print("[Main] KakaoNotify 종료 완료")


if __name__ == "__main__":
    app = KakaoNotifyApp()
    app.run()
