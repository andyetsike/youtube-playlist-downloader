"""
Constantes globales de l'application.
Couleurs, chemins persistants, bitrates, domaines connus.
"""
import os

# ─── Chemins fichiers persistants ────────────────────────────────────────────
SESSION_FILE = os.path.join(os.path.expanduser("~"), ".ytdl_session.json")
HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".ytdl_history.json")

# ─── Palette de couleurs ──────────────────────────────────────────────────────
BG      = "#0d1117"
SURF    = "#161b22"
CARD    = "#21262d"
BORDER  = "#30363d"
ACCENT  = "#2f81f7"
ACCENT2 = "#79c0ff"
SUCCESS = "#3fb950"
WARN    = "#d29922"
DANGER  = "#f85149"
TEXT    = "#e6edf3"
DIM     = "#8b949e"
PURPLE  = "#a371f7"

# ─── Bitrates estimés (bps) par format ───────────────────────────────────────
BITRATES = {
    "mp4_best": 4_500_000,
    "mp4_1080": 3_500_000,
    "mp4_720":  2_000_000,
    "mp3":        192_000,
    "m4a":        130_000,
}

# ─── Hôtes vidéo directs ─────────────────────────────────────────────────────
# URLs de ces domaines sont téléchargeables directement par yt-dlp.
VIDEO_HOSTS = [
    "sibnet.ru", "vidmoly.to", "sendvid.com",
    "streamtape.com", "streamtape.net",
    "doodstream.com", "ds2play.com",
    "filemoon.sx", "filemoon.in",
    "uqload.com", "uqload.co",
    "okru.com", "ok.ru",
    "dailymotion.com",
    "dingtezuni.com",
    "embed.myvi.ru",
]

# ─── Hôtes préférés (du plus rapide au plus lent) ────────────────────────────
# Vidmoly en premier (résolveur JWT intégré, 1-4 Mo/s si ça marche).
# Sibnet en dernier (limité à ~16 Ko/s mais toujours fonctionnel).
PREFERRED_HOSTS = [
    "vidmoly.to", "sendvid.com", "ok.ru", "dailymotion.com", "sibnet.ru",
]

# ─── Sites animés — scraping personnalisé ────────────────────────────────────
ANIME_DOMAINS = [
    "voiranime.com", "voiranime.me",
    "animes-sama.fr", "anime-sama.fr",
    "mavanimes.co", "mavanimes.org",
    "neko-sama.fr",
    "animevostfr.tv", "animevf.tv",
    "franime.fr",
    "animeko.co",
    "vostfree.tv", "vostfree.com",
    "jetanime.co", "jetanimes.com",
]
