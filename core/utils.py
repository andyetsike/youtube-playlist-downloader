"""
Fonctions utilitaires pures — aucune dépendance sur l'UI.
"""
import os
import shutil
from .constants import BITRATES


def find_ffmpeg() -> str | None:
    """Cherche ffmpeg sur le système. Retourne le chemin ou None."""
    p = shutil.which("ffmpeg")
    if p:
        return p
    search_roots = [
        r"C:\ffmpeg",
        r"C:\Program Files\ffmpeg",
        r"C:\ProgramData\chocolatey",
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Microsoft", "WinGet", "Links"),
        os.path.join(os.path.expanduser("~"), "Downloads"),
    ]
    for root in search_roots:
        direct = os.path.join(root, "bin", "ffmpeg.exe")
        if os.path.isfile(direct):
            return direct
        try:
            for entry in os.scandir(root):
                if entry.is_dir():
                    c = os.path.join(entry.path, "bin", "ffmpeg.exe")
                    if os.path.isfile(c):
                        return c
        except Exception:
            pass
    return None


def fmt_duration(secs) -> str:
    try:
        secs = int(secs)
        h, r = divmod(secs, 3600)
        m, s = divmod(r, 60)
        return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"
    except Exception:
        return "—"


def estimate_size_bytes(dur_secs, fmt) -> int | None:
    try:
        secs = int(dur_secs)
        bps  = BITRATES.get(fmt, 4_000_000)
        return secs * bps // 8
    except Exception:
        return None


def fmt_size(size_bytes) -> str:
    if size_bytes is None:
        return "—"
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} Go"
    if size_bytes >= 1_048_576:
        return f"{size_bytes / 1_048_576:.0f} Mo"
    return f"{size_bytes / 1024:.0f} Ko"
