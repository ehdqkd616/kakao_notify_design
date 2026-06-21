import array
import math
import queue
import threading
import wave
from pathlib import Path

try:
    import pygame
    pygame.mixer.pre_init(44100, -16, 2, 1024)
    pygame.mixer.init()
    PYGAME_AVAILABLE = True
except Exception:
    PYGAME_AVAILABLE = False
    print("[SoundEngine] pygame 초기화 실패 — 음원 재생 불가")

try:
    from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
    PYCAW_AVAILABLE = True
except ImportError:
    PYCAW_AVAILABLE = False


def generate_default_beep(path: Path, freq: int = 880, duration: float = 0.3, volume: float = 0.3) -> None:
    """기본 알림음 WAV 파일을 생성한다 (의존성 없음)."""
    sample_rate = 44100
    n_samples = int(sample_rate * duration)
    samples = array.array("h", [
        int(volume * 32767 * math.sin(2 * math.pi * freq * i / sample_rate))
        for i in range(n_samples)
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())


class SoundEngine:
    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._stopped = False
        if PYGAME_AVAILABLE:
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

        default_path = Path(__file__).parent / "sounds" / "default.wav"
        if not default_path.exists():
            generate_default_beep(default_path)
            print(f"[SoundEngine] 기본 알림음 생성: {default_path}")

    def play(self, sound_path: str) -> None:
        if not sound_path or not PYGAME_AVAILABLE:
            return
        path = Path(sound_path)
        if not path.is_absolute():
            path = Path(__file__).parent / path
        if not path.exists():
            print(f"[SoundEngine] 파일 없음: {path}")
            return
        self._queue.put(str(path))

    def _worker_loop(self) -> None:
        while not self._stopped:
            try:
                sound_path = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            if sound_path is None:
                break
            self._play(sound_path)

    def _play(self, sound_path: str) -> None:
        try:
            ext = Path(sound_path).suffix.lower()
            if ext in (".wav", ".ogg"):
                sound = pygame.mixer.Sound(sound_path)
                channel = sound.play()
                if channel:
                    while channel.get_busy():
                        pygame.time.wait(50)
            else:
                pygame.mixer.music.load(sound_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.wait(50)
        except Exception as e:
            print(f"[SoundEngine] 재생 오류: {e}")

    def cleanup(self) -> None:
        self._stopped = True
        self._queue.put(None)
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.quit()
            except Exception:
                pass


class KakaoMuteController:
    def mute(self) -> None:
        self._set_volume(0.0)

    def unmute(self) -> None:
        self._set_volume(1.0)

    def _set_volume(self, level: float) -> None:
        if not PYCAW_AVAILABLE:
            return
        try:
            for session in AudioUtilities.GetAllSessions():
                if session.Process and "kakaotalk" in session.Process.name().lower():
                    vol = session._ctl.QueryInterface(ISimpleAudioVolume)
                    vol.SetMasterVolume(level, None)
        except Exception as e:
            print(f"[KakaoMute] 볼륨 제어 오류: {e}")
