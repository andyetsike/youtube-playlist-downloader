"""
DownloadEngine — moteur de téléchargement.

Responsabilité unique : construire les options yt-dlp, gérer le téléchargement
d'une vidéo (multi-source, retry, Vidmoly), et orchestrer le worker parallèle.

Dépend de : yt-dlp, AnimeScraper, constants.
Ne dépend PAS de tkinter.
"""
from __future__ import annotations
import os
import re
import threading
import time

import yt_dlp

from .constants import VIDEO_HOSTS, ANIME_DOMAINS
from .scrapers import AnimeScraper


# ── Exceptions ───────────────────────────────────────────────────────────────

class DownloadPaused(Exception):
    """
    Levée depuis App._hook quand l'utilisateur met en pause.
    Propagée à travers yt-dlp (non capturée par DownloadError),
    remonte jusqu'au worker qui remet la vidéo en file d'attente.
    Le fichier .part est préservé sur disque — la reprise continue
    à l'octet exact où le téléchargement s'était interrompu.
    """


# ── Logger yt-dlp → UI ───────────────────────────────────────────────────────

class YtdlpLogger:
    """Relaie les warnings/erreurs internes de yt-dlp vers le journal de l'UI."""

    def __init__(self, log_fn):
        self._log = log_fn

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        low = msg.lower()
        if any(k in low for k in (
                "ffmpeg", "merger", "merge", "mux", "postprocess",
                "unsupported", "fragment", "unable to download")):
            self._log(f"⚠  yt-dlp: {msg.strip()}", "warn")

    def error(self, msg):
        self._log(f"✕  yt-dlp: {msg.strip()}", "err")


# ── Moteur de téléchargement ─────────────────────────────────────────────────

class DownloadEngine:
    """
    Orchestre les téléchargements en utilisant yt-dlp.

    Paramètres du constructeur :
      log_fn        callable(msg, tag) — journal UI
      hook_fn       callable(d)        — progress hook yt-dlp
      pp_hook_fn    callable(d)        — postprocessor hook yt-dlp
      settings      objet avec .get_*() — accès aux réglages de l'App
      cancel_fn     callable() -> bool  — retourne True si annulation demandée
      pause_fn      callable() -> bool  — retourne True si pause demandée
    """
    MIN_VALID_BYTES = 50 * 1024   # un fichier valide fait au moins 50 Ko

    def __init__(self, log_fn, hook_fn, pp_hook_fn, settings, cancel_fn,
                 pause_fn=None,
                 per_dl_bytes: dict = None, per_dl_time: dict = None):
        self._log       = log_fn
        self._hook      = hook_fn
        self._pp_hook   = pp_hook_fn
        self._settings  = settings
        self._cancelled = cancel_fn
        self._paused    = pause_fn or (lambda: False)
        self._scraper   = AnimeScraper(log_fn)

        # Partagés avec App._hook pour le suivi par thread
        # (on accepte des dicts externes pour que hook et engine voient le même état)
        self._per_dl_bytes: dict[int, int]   = per_dl_bytes if per_dl_bytes is not None else {}
        self._per_dl_time:  dict[int, float] = per_dl_time  if per_dl_time  is not None else {}
        self._done_lock = threading.Lock()

    # ── API publique ──────────────────────────────────────────────────────────

    # Priorités : 0 = haute, 1 = normale, 2 = basse
    _PRIO_MAP = {"high": 0, "normal": 1, "low": 2}

    def run(self, videos: list,
            on_video_start,
            on_video_done,
            on_all_done,
            on_video_paused=None):
        """
        Lance le téléchargement de la liste de vidéos en parallèle.

        Les vidéos sont servies dans l'ordre de priorité (high → normal → low).
        La priorité peut être modifiée en temps réel depuis l'UI — les dict
        étant partagés par référence, le prochain slot libre tient compte de
        la priorité mise à jour.

        Si pause_fn() retourne True en cours de téléchargement :
          1. DownloadPaused est levée dans App._hook → propagée par yt-dlp
          2. Le worker remet la vidéo en tête de file
          3. Le worker attend que pause_fn() repasse à False
          4. Le fichier .part reste sur disque → reprise octet par octet

        Callbacks :
          on_video_start(v)        — appelé quand un téléchargement commence
          on_video_done(v, ok)     — appelé quand il se termine (ok=True/False)
          on_all_done(done, total) — appelé une fois tout terminé
          on_video_paused(v)       — optionnel, appelé quand une vidéo est mise en pause
        """
        total        = len(videos)
        done_count   = [0]
        lock         = threading.Lock()
        pending_lock = threading.Lock()
        pending: list = list(videos)   # mêmes refs que _videos

        _on_paused = on_video_paused or (lambda v: None)

        def _prio(v):
            return self._PRIO_MAP.get(v.get("priority", "normal"), 1)

        def worker():
            while True:
                # ── Attente pause (avant de prendre une nouvelle vidéo) ──────
                while self._paused() and not self._cancelled():
                    time.sleep(0.1)
                if self._cancelled():
                    break

                # ── Prendre la vidéo de plus haute priorité ──────────────────
                with pending_lock:
                    if not pending:
                        break
                    pending.sort(key=_prio)
                    v = pending.pop(0)

                # ── Télécharger ──────────────────────────────────────────────
                paused_mid = False
                try:
                    on_video_start(v)
                    self._download_one(v)
                    success = True
                except DownloadPaused:
                    paused_mid = True
                except yt_dlp.utils.DownloadCancelled:
                    break
                except Exception as exc:
                    self._log(f"⚠  Erreur [{v['num']}] : {exc}", "warn")
                    success = False

                # ── Traiter le résultat ──────────────────────────────────────
                if paused_mid:
                    # Remettre en tête de file, notifier l'UI, attendre resume
                    with pending_lock:
                        pending.insert(0, v)
                    _on_paused(v)
                    while self._paused() and not self._cancelled():
                        time.sleep(0.1)
                    continue   # re-boucle (re-prend ou annule)

                with lock:
                    if success:
                        done_count[0] += 1
                on_video_done(v, success)

        n_par     = max(1, self._settings.get_concurrent())
        n_workers = min(n_par, total)
        threads   = [threading.Thread(target=worker, daemon=True)
                     for _ in range(n_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        on_all_done(done_count[0], total)

    def build_opts(self, video: dict) -> dict:
        """Construit le dict d'options yt-dlp pour une vidéo."""
        s   = self._settings
        fmt = s.get_format()

        is_anime  = self._scraper.is_anime_url(video["url"])
        is_direct = any(h in video["url"] for h in VIDEO_HOSTS)

        dest = s.get_dest()
        if s.get_playlist_folder() and s.get_playlist_title() and s.get_total() > 1:
            safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_",
                          s.get_playlist_title())[:80].strip()
            dest = os.path.join(dest, safe)
            os.makedirs(dest, exist_ok=True)

        if s.get_number_files():
            tmpl = os.path.join(dest, f"{video['num']:03d} - %(title)s.%(ext)s")
        else:
            tmpl = os.path.join(dest, "%(title)s.%(ext)s")

        opts: dict = {
            "outtmpl":             tmpl,
            "ignoreerrors":        False,
            "continuedl":          True,   # reprend les fichiers .part existants
            "progress_hooks":      [self._hook],
            "postprocessor_hooks": [self._pp_hook],
            "noplaylist":          True,
            "merge_output_format": "mp4",
            "prefer_free_formats": False,
            "logger":              YtdlpLogger(self._log),
            # ── Résilience réseau ──────────────────────────────────────────────
            "socket_timeout":      30,             # timeout socket (s)
            "retries":             10,             # tentatives internes yt-dlp
            "fragment_retries":    10,             # tentatives HLS/DASH
            "file_access_retries": 5,              # tentatives accès fichier
            "extractor_retries":   5,              # tentatives extraction info
            # ── Téléchargement segmenté (style IDM) ──────────────────────────
            # http_chunk_size : taille de chaque requête HTTP Range.
            # yt-dlp écrit sur disque AU FUR ET À MESURE (pas de buffer 1 Mo
            # en mémoire). En cas de coupure, on perd seulement les octets
            # dans le buffer réseau (quelques Ko), pas 1 Mo entier.
            # 1 Mo est un bon compromis : peu de requêtes, reprise fine.
            "http_chunk_size":              1 * 1024 * 1024,   # 1 Mo par requête
            # concurrent_fragment_downloads : pour les flux HLS/DASH (anime,
            # YouTube 1080p+), télécharge N fragments simultanément dans le
            # même fichier — exactement comme IDM parallélise ses segments.
            "concurrent_fragment_downloads": 4,
        }

        fp = s.get_ffmpeg()
        if fp:
            opts["ffmpeg_location"] = os.path.dirname(fp)

        # Referer — indispensable pour les CDN (Sibnet, Vidmoly…)
        page_url = video.get("page_url", "")
        if page_url:
            m_origin = re.match(r"(https?://[^/]+)", page_url)
            opts["http_headers"] = {
                "Referer": page_url,
                "Origin":  m_origin.group(1) if m_origin else "",
            }

        # Sélection du format
        self._apply_format(opts, fmt, is_anime)

        # Postprocesseurs MP4 (seulement pour YouTube/TikTok, pas les hôtes directs)
        if fmt in ("mp4_best", "mp4_1080", "mp4_720") and not is_direct:
            opts["postprocessors"] = [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
            ]

        if s.get_subtitles():
            opts["writesubtitles"] = True
            opts["subtitleslangs"] = ["fr", "en"]

        if (s.get_thumbnail()
                and not is_direct
                and fmt in ("mp4_best", "mp4_1080", "mp4_720", "mp3", "m4a")):
            opts.setdefault("postprocessors", [])
            opts["postprocessors"].append({"key": "EmbedThumbnail"})
            opts["writethumbnail"] = True

        browser = s.get_browser()
        if browser and browser != "none":
            opts["cookiesfrombrowser"] = (browser,)

        try:
            kbps = int(s.get_speed_limit())
            if kbps > 0:
                opts["ratelimit"] = kbps * 1024
        except ValueError:
            pass

        return opts

    # ── Download d'une vidéo ─────────────────────────────────────────────────

    def _download_one(self, v: dict):
        """
        Télécharge une seule vidéo dans son propre thread.
        Gère : multi-source, résolution Vidmoly, retry exponentiel.
        Lève une exception si tout échoue.
        """
        tid = threading.current_thread().ident

        primary_url = v["url"]
        alt_urls    = v.get("alt_urls", [])
        is_direct   = any(h in primary_url for h in VIDEO_HOSTS)
        is_anime    = self._scraper.is_anime_url(primary_url)

        # Construire la liste brute d'URLs
        if alt_urls:
            raw_urls = [primary_url] + alt_urls
        elif is_anime and not is_direct:
            players = self._scraper.scrape_episode_players(primary_url)
            raw_urls = players + [primary_url]
            if players:
                self._log(f"  → {len(players)} lecteur(s) détecté(s)", "dim")
        else:
            raw_urls = [primary_url]

        # Résolution Vidmoly JWT
        resolved = []
        for u in raw_urls:
            if "vidmoly.to" in u:
                self._log("  → Résolution Vidmoly (JWT)…", "dim")
                direct, ref = self._scraper.resolve_vidmoly(u)
                if direct:
                    self._log(f"  → Vidmoly ✓ : {direct[:70]}", "dim")
                    resolved.append((direct, ref or u))
                else:
                    self._log("  → Vidmoly ✗ : source ignorée", "dim")
            else:
                resolved.append((u, v.get("page_url", "")))

        if not resolved:
            raise ValueError("Aucune source téléchargeable trouvée")

        # Retry exponentiel
        max_retry = max(0, self._settings.get_auto_retry())
        last_err  = None

        for attempt in range(max_retry + 1):
            if self._cancelled():
                raise yt_dlp.utils.DownloadCancelled("Annulé")
            if self._paused():
                raise DownloadPaused()
            if attempt > 0:
                self._log(f"  → Retry {attempt}/{max_retry}…", "dim")
                time.sleep(min(2 ** attempt, 15))

            for idx_src, (try_url, try_page) in enumerate(resolved):
                if self._cancelled():
                    raise yt_dlp.utils.DownloadCancelled("Annulé")

                v_trial = dict(v)
                v_trial["url"] = try_url
                if try_page:
                    v_trial["page_url"] = try_page

                self._per_dl_bytes[tid] = 0
                self._per_dl_time[tid]  = time.time()

                if len(resolved) > 1:
                    host = try_url.split("/")[2] if "//" in try_url else try_url[:40]
                    self._log(f"  → [{idx_src+1}/{len(resolved)}] {host}", "dim")

                try:
                    with yt_dlp.YoutubeDL(self.build_opts(v_trial)) as ydl:
                        ydl.download([try_url])

                    bytes_dl = self._per_dl_bytes.get(tid, 0)
                    if 0 < bytes_dl < self.MIN_VALID_BYTES:
                        raise ValueError(
                            f"Fichier trop petit ({bytes_dl} octets) "
                            f"— source vide ou bloquée")

                    last_err = None
                    break   # source OK

                except DownloadPaused:
                    raise   # pas de retry — le fichier .part est préservé
                except yt_dlp.utils.DownloadCancelled:
                    raise
                except Exception as exc:
                    last_err = exc
                    if idx_src < len(resolved) - 1:
                        self._log(
                            f"  → Source {idx_src+1} échouée "
                            f"({type(exc).__name__}), essai suivant…", "dim")

            if last_err is None:
                break   # succès, pas besoin de retry

        if last_err:
            raise last_err

    # ── Format helper ────────────────────────────────────────────────────────

    def _apply_format(self, opts: dict, fmt: str, is_anime: bool):
        if fmt == "mp4_best":
            if is_anime:
                opts["format"] = "bestvideo+bestaudio/best"
            else:
                opts["format"] = (
                    "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[acodec^=mp4a][ext=m4a]"
                    "/bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]"
                    "/bestvideo[ext=mp4]+bestaudio[ext=m4a]"
                    "/bestvideo[ext=mp4]+bestaudio"
                    "/bestvideo+bestaudio[ext=m4a]"
                    "/bestvideo+bestaudio"
                    "/best[ext=mp4]/best"
                )
        elif fmt == "mp4_1080":
            if is_anime:
                opts["format"] = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
            else:
                opts["format"] = (
                    "bestvideo[vcodec^=avc1][height<=1080][ext=mp4]+bestaudio[acodec^=mp4a][ext=m4a]"
                    "/bestvideo[vcodec^=avc1][height<=1080]+bestaudio[acodec^=mp4a]"
                    "/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]"
                    "/bestvideo[height<=1080][ext=mp4]+bestaudio"
                    "/bestvideo[height<=1080]+bestaudio"
                    "/best[height<=1080][ext=mp4]/best[height<=1080]/best"
                )
        elif fmt == "mp4_720":
            if is_anime:
                opts["format"] = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
            else:
                opts["format"] = (
                    "bestvideo[vcodec^=avc1][height<=720][ext=mp4]+bestaudio[acodec^=mp4a][ext=m4a]"
                    "/bestvideo[vcodec^=avc1][height<=720]+bestaudio[acodec^=mp4a]"
                    "/bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]"
                    "/bestvideo[height<=720][ext=mp4]+bestaudio"
                    "/bestvideo[height<=720]+bestaudio"
                    "/best[height<=720][ext=mp4]/best[height<=720]/best"
                )
        elif fmt == "mp3":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key":              "FFmpegExtractAudio",
                "preferredcodec":   "mp3",
                "preferredquality": "192",
            }]
        elif fmt == "m4a":
            opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"


# ── AppSettings — interface entre App et DownloadEngine ──────────────────────

class AppSettings:
    """
    Adaptateur (pattern Adapter) : expose les réglages de l'App
    sous forme de méthodes simples consommées par DownloadEngine.
    Respecte le principe d'inversion de dépendance (D de SOLID).
    """

    def __init__(self, app):
        self._app = app

    def get_format(self)        -> str:   return self._app.format_choice.get()
    def get_dest(self)          -> str:   return self._app.download_path.get()
    def get_ffmpeg(self)        -> str:   return self._app.ffmpeg_path.get()
    def get_subtitles(self)     -> bool:  return self._app.subtitles_var.get()
    def get_number_files(self)  -> bool:  return self._app.playlist_num_var.get()
    def get_thumbnail(self)     -> bool:  return self._app.thumbnail_var.get()
    def get_browser(self)       -> str:   return self._app.cookies_browser.get()
    def get_speed_limit(self)   -> str:   return self._app.speed_limit_var.get()
    def get_concurrent(self)    -> int:   return self._app.concurrent_var.get()
    def get_auto_retry(self)    -> int:   return self._app.auto_retry_var.get()
    def get_playlist_folder(self) -> bool: return self._app.playlist_folder_var.get()
    def get_playlist_title(self)  -> str:  return self._app._playlist_title
    def get_total(self)           -> int:  return self._app._total
