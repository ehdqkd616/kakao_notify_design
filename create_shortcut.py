"""
바탕화면과 시작 메뉴에 KakaoNotify 바로가기를 생성합니다.
한 번만 실행하면 됩니다.
"""
import os
import sys
import winreg
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def create_icon(path: Path) -> None:
    sizes = [16, 32,48, 64, 128, 256]
    frames = []
    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 카카오 노란 원 배경
        margin = max(1, size // 16)
        draw.ellipse([margin, margin, size - margin, size - margin], fill="#FFCD00")

        # 말풍선 안 어두운 원
        inner = size * 0.55
        cx, cy = size / 2, size / 2 - size * 0.03
        draw.ellipse(
            [cx - inner / 2, cy - inner / 2, cx + inner / 2, cy + inner / 2],
            fill="#3C1E1E",
        )

        # 말풍선 꼬리
        tail_w = size * 0.18
        tail_h = size * 0.22
        tx = cx - size * 0.08
        ty = cy + inner / 2 - 1
        draw.polygon(
            [(tx, ty), (tx + tail_w, ty), (tx + tail_w * 0.3, ty + tail_h)],
            fill="#FFCD00",
        )

        # 눈 두 개 (흰 점)
        dot = max(1, size // 14)
        for ox in (-size // 8, size // 8):
            draw.ellipse(
                [cx + ox - dot, cy - dot, cx + ox + dot, cy + dot],
                fill="white",
            )

        frames.append(img)

    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        str(path),
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print(f"아이콘 생성: {path}")


def create_lnk(lnk_path: Path, target: Path, args: str, icon: Path, work_dir: Path) -> None:
    import pythoncom
    from win32com.shell import shell

    shortcut = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink,
        None,
        pythoncom.CLSCTX_INPROC_SERVER,
        shell.IID_IShellLink,
    )
    shortcut.SetPath(str(target))
    shortcut.SetArguments(args)
    shortcut.SetWorkingDirectory(str(work_dir))
    shortcut.SetIconLocation(str(icon), 0)
    shortcut.SetDescription("KakaoNotify — 채팅방별 알림음 커스터마이저")

    persist = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
    persist.Save(str(lnk_path), True)
    print(f"바로가기 생성: {lnk_path}")


def create_lnk_powershell(lnk_path: Path, target: Path, args: str, icon: Path, work_dir: Path) -> None:
    """pywin32 없을 때 PowerShell로 .lnk 생성."""
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{lnk_path}')
$sc.TargetPath = '{target}'
$sc.Arguments = '{args}'
$sc.WorkingDirectory = '{work_dir}'
$sc.IconLocation = '{icon},0'
$sc.Description = 'KakaoNotify - 채팅방별 알림음 커스터마이저'
$sc.Save()
"""
    import subprocess
    subprocess.run(["powershell", "-Command", ps], check=True)
    print(f"바로가기 생성: {lnk_path}")


def main():
    base = Path(__file__).parent.resolve()
    pythonw = base / "venv" / "Scripts" / "pythonw.exe"
    main_py = base / "main.py"
    icon_path = base / "assets" / "icon.ico"

    if not pythonw.exists():
        print(f"오류: 가상환경을 찾을 수 없습니다. {pythonw}")
        print("먼저 'python -m virtualenv venv && pip install -r requirements.txt' 를 실행하세요.")
        sys.exit(1)

    # 1. 아이콘 생성
    create_icon(icon_path)

    # 2. 바탕화면 경로
    desktop = Path(os.path.expanduser("~")) / "Desktop"
    if not desktop.exists():
        # OneDrive 바탕화면
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            ) as key:
                desktop = Path(winreg.QueryValueEx(key, "Desktop")[0])
        except Exception:
            desktop = Path(os.environ.get("USERPROFILE", "~")) / "Desktop"

    # 3. 시작 메뉴 경로
    start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"

    lnk_name = "KakaoNotify.lnk"
    args = f'"{main_py}"'

    for dest in [desktop, start_menu]:
        if dest.exists():
            lnk = dest / lnk_name
            try:
                import pythoncom  # pywin32
                create_lnk(lnk, pythonw, args, icon_path, base)
            except ImportError:
                create_lnk_powershell(lnk, pythonw, args, icon_path, base)

    print("\n완료! 바탕화면과 시작 메뉴에서 KakaoNotify 를 실행할 수 있습니다.")
    print("(pythonw.exe 사용 - 콘솔 창 없이 백그라운드로 실행됩니다)")


if __name__ == "__main__":
    main()
