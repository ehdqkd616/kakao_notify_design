import json
import sys
import winreg
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "rules.json"

DEFAULT_CONFIG = {
    "rules": [],
    "default_sound": "sounds/default.wav",
    "kakao_mute": True,
    "autostart": False,
}


class ConfigManager:
    def __init__(self):
        self._config = self._load()

    def _load(self) -> dict:
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[Config] 설정 로드 오류, 기본값 사용: {e}")
        return dict(DEFAULT_CONFIG)

    def save(self) -> None:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"[Config] 저장 오류: {e}")

    def reload(self) -> None:
        self._config = self._load()

    @property
    def rules(self) -> list:
        return self._config.get("rules", [])

    @rules.setter
    def rules(self, value: list) -> None:
        self._config["rules"] = value

    @property
    def default_sound(self) -> str:
        return self._config.get("default_sound", "sounds/default.wav")

    @default_sound.setter
    def default_sound(self, value: str) -> None:
        self._config["default_sound"] = value

    @property
    def kakao_mute(self) -> bool:
        return self._config.get("kakao_mute", True)

    @kakao_mute.setter
    def kakao_mute(self, value: bool) -> None:
        self._config["kakao_mute"] = bool(value)

    @property
    def autostart(self) -> bool:
        return self._config.get("autostart", False)

    @autostart.setter
    def autostart(self, value: bool) -> None:
        self._config["autostart"] = bool(value)
        self._apply_autostart(bool(value))

    def _apply_autostart(self, enable: bool) -> None:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "KakaoNotify"
        exe_path = f'"{sys.executable}" "{Path(__file__).parent / "main.py"}"'
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
                else:
                    try:
                        winreg.DeleteValue(key, app_name)
                    except FileNotFoundError:
                        pass
        except Exception as e:
            print(f"[Config] 자동시작 설정 오류: {e}")
