#!/usr/bin/env python3
"""
YouTube / TikTok / Anime Downloader  v6
Requires: pip install yt-dlp

Architecture SOLID :
  core/constants.py  — couleurs, domaines, chemins
  core/utils.py      — fonctions utilitaires pures
  core/history.py    — HistoryManager
  core/session.py    — SessionManager
  core/scrapers.py   — AnimeScraper (scraping + Vidmoly JWT)
  core/downloader.py — DownloadEngine + AppSettings + YtdlpLogger
  youtube_downloader_v2.py — App (UI tkinter uniquement)
"""

# ─── Auto-install yt-dlp ──────────────────────────────────────────────────────
import subprocess, sys
def _ensure_ytdlp():
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp"])
_ensure_ytdlp()

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import time
import os
import re
import webbrowser
import yt_dlp

from core.constants import (
    BG, SURF, CARD, BORDER, ACCENT, ACCENT2,
    SUCCESS, WARN, DANGER, TEXT, DIM, PURPLE,
    SESSION_FILE, HISTORY_FILE,
)
from core.utils       import find_ffmpeg, fmt_duration, fmt_size, estimate_size_bytes
from core.history     import HistoryManager
from core.session     import SessionManager
from core.scrapers    import AnimeScraper
from core.downloader  import DownloadEngine, AppSettings, DownloadPaused


# ─── App ──────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    PH = "Collez une URL YouTube (vidéo / playlist) ou TikTok…"

    # ── Regex pour le moniteur de presse-papiers ──────────────────────────────
    _CLIP_URL_RE = re.compile(
        r"https?://(?:"
        r"(?:www\.)?youtube\.com/(?:watch|playlist|shorts)|"
        r"youtu\.be/|"
        r"(?:www\.)?tiktok\.com/|"
        r"(?:vm|vt)\.tiktok\.com/|"
        r"(?:voiranime\.com|voiranime\.me"
        r"|animes-sama\.fr|anime-sama\.fr"
        r"|mavanimes\.co|neko-sama\.fr"
        r"|vostfree\.tv|vostfree\.com"
        r"|jetanime\.co|jetanimes\.com"
        r"|franime\.fr|animeko\.co)/"
        r")"
    )

    def __init__(self):
        super().__init__()
        self.title("YouTube / TikTok / Anime Downloader")
        self.geometry("980x850")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(780, 680)

        # ── Variables tkinter ─────────────────────────────────────────────────
        self.download_path     = tk.StringVar(value=os.path.expanduser("~/Downloads"))
        self.format_choice     = tk.StringVar(value="mp4_best")
        self.ffmpeg_path       = tk.StringVar(value=find_ffmpeg() or "")
        self.subtitles_var     = tk.BooleanVar(value=False)
        self.playlist_num_var  = tk.BooleanVar(value=True)
        self.cookies_browser   = tk.StringVar(value="none")
        self.thumbnail_var     = tk.BooleanVar(value=True)
        self.speed_limit_var   = tk.StringVar(value="0")
        self.playlist_folder_var = tk.BooleanVar(value=True)
        self.concurrent_var    = tk.IntVar(value=2)
        self.post_action_var   = tk.StringVar(value="none")
        self.auto_retry_var    = tk.IntVar(value=3)
        self.clip_monitor_var  = tk.BooleanVar(value=True)

        # ── État interne ──────────────────────────────────────────────────────
        self.cancel_flag       = False
        self.pause_flag        = False
        self._videos           = []
        self._total            = 0
        self._done             = 0
        self._focused_idx      = None
        self._completed_urls   = set()
        self._active_urls      = set()   # URLs en cours de téléchargement
        self._playlist_title   = ""
        self._clip_last        = ""

        # Thread-safe: partagés entre App._hook et DownloadEngine
        self._per_dl_bytes: dict = {}
        self._per_dl_time:  dict = {}
        self._done_lock = threading.Lock()

        # ── Objets core (SOLID: dépendances injectées) ────────────────────────
        self.history = HistoryManager(HISTORY_FILE)
        self.session = SessionManager(SESSION_FILE)
        self.scraper = AnimeScraper(log_fn=self._alog)
        self.engine  = DownloadEngine(
            log_fn       = self._alog,
            hook_fn      = self._hook,
            pp_hook_fn   = self._pp_hook,
            settings     = AppSettings(self),
            cancel_fn    = lambda: self.cancel_flag,
            pause_fn     = lambda: self.pause_flag,
            per_dl_bytes = self._per_dl_bytes,
            per_dl_time  = self._per_dl_time,
        )

        self.format_choice.trace_add("write", self._on_format_change)

        self._apply_treeview_style()
        self._build_ui()
        self._check_ffmpeg_on_start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200,  self._check_resume)
        self.after(800,  self._check_ytdlp_update)
        self.after(1000, self._tick_clipboard)

    # =========================================================================
    # UI — Construction
    # =========================================================================

    def _build_ui(self):
        hdr = tk.Frame(self, bg=SURF, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="▶  YouTube / TikTok / Anime Downloader",
                 font=("Segoe UI", 14, "bold"), bg=SURF, fg=TEXT
                 ).pack(side="left", padx=20)

        self.ffmpeg_badge = tk.Label(hdr, text="", font=("Segoe UI", 9),
                                     bg=SURF, cursor="hand2", padx=14)
        self.ffmpeg_badge.pack(side="right")
        self.ffmpeg_badge.bind("<Button-1>", lambda e: self._locate_ffmpeg())
        self._refresh_badge()

        tk.Button(hdr, text="📋  Historique",
                  bg=CARD, fg=DIM, font=("Segoe UI", 9),
                  relief="flat", cursor="hand2", padx=12, pady=4,
                  activebackground=BORDER, activeforeground=TEXT,
                  command=self._show_history
                  ).pack(side="right", padx=(0, 4))

        self.clip_badge = tk.Label(hdr, text="📋 Clip: ON", fg=SUCCESS,
                                   bg=SURF, font=("Segoe UI", 9),
                                   cursor="hand2", padx=10)
        self.clip_badge.pack(side="right")
        self.clip_badge.bind("<Button-1>", self._toggle_clipboard_monitor)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=22, pady=14)

        self._build_url_section(body)
        self._build_video_list(body)
        self._build_options_row(body)
        self._build_buttons(body)
        self._build_progress(body)
        self._build_log(body)

    def _build_url_section(self, parent):
        self._lbl(parent, "URL  —  YouTube (vidéo ou playlist)  •  TikTok  •  Anime")
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(4, 14))

        wrap = tk.Frame(row, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        wrap.pack(side="left", fill="x", expand=True)

        self.url_entry = tk.Entry(wrap, bg=CARD, fg=DIM, insertbackground=TEXT,
                                  font=("Consolas", 11), bd=0, relief="flat")
        self.url_entry.pack(fill="x", ipady=9, ipadx=12, pady=2, padx=2)
        self.url_entry.insert(0, self.PH)
        self.url_entry.bind("<FocusIn>",  self._clear_ph)
        self.url_entry.bind("<FocusOut>", self._restore_ph)
        self.url_entry.bind("<Return>",   lambda e: self._fetch())

        self.fetch_btn = tk.Button(row, text="  Analyser  ",
                                   bg=ACCENT, fg="white",
                                   font=("Segoe UI", 10, "bold"),
                                   relief="flat", cursor="hand2",
                                   pady=9, padx=14,
                                   command=self._fetch)
        self.fetch_btn.pack(side="left", padx=(8, 0))

    def _build_video_list(self, parent):
        toolbar = tk.Frame(parent, bg=BG)
        toolbar.pack(fill="x", pady=(0, 4))
        self._lbl_inline(toolbar, "VIDÉOS  —  ORDRE DE PRIORITÉ")
        self.count_lbl = tk.Label(toolbar, text="—", bg=BG, fg=DIM,
                                  font=("Segoe UI", 9))
        self.count_lbl.pack(side="right")
        btn_grp = tk.Frame(toolbar, bg=BG)
        btn_grp.pack(side="right", padx=(0, 14))
        for txt, cmd in [
            ("↑ Priorité haute", self._move_up),
            ("↓ Priorité basse", self._move_down),
            ("Tout désélectionner", self._deselect_all),
            ("Tout sélectionner",   self._select_all),
        ]:
            tk.Button(btn_grp, text=txt, bg=CARD, fg=DIM,
                      font=("Segoe UI", 9), relief="flat",
                      cursor="hand2", padx=8, pady=3,
                      command=cmd).pack(side="right", padx=2)

        tree_frame = tk.Frame(parent, bg=CARD,
                              highlightbackground=BORDER, highlightthickness=1)
        tree_frame.pack(fill="both", expand=True)

        cols = ("sel", "num", "title", "dur", "size")
        self.tree = ttk.Treeview(tree_frame, columns=cols,
                                 show="headings", style="Video.Treeview",
                                 selectmode="browse")
        self.tree.heading("sel",   text="",       anchor="center")
        self.tree.heading("num",   text="#",       anchor="center")
        self.tree.heading("title", text="Titre",   anchor="w")
        self.tree.heading("dur",   text="Durée",   anchor="center")
        self.tree.heading("size",  text="Taille est.", anchor="center")

        self.tree.column("sel",   width=30,  stretch=False, anchor="center")
        self.tree.column("num",   width=40,  stretch=False, anchor="center")
        self.tree.column("title", width=500, stretch=True,  anchor="w")
        self.tree.column("dur",   width=70,  stretch=False, anchor="center")
        self.tree.column("size",  width=90,  stretch=False, anchor="center")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.tag_configure("checked",   foreground=TEXT)
        self.tree.tag_configure("unchecked", foreground=DIM)
        self.tree.tag_configure("active",    foreground=ACCENT2)
        self.tree.tag_configure("done",      foreground=SUCCESS)
        self.tree.tag_configure("focused",   foreground=PURPLE)
        self.tree.tag_configure("high_prio", foreground="#ff9944")   # orange vif
        self.tree.tag_configure("low_prio",  foreground="#557799")   # bleu grisé

        self.tree.bind("<Button-1>",  self._toggle_row)
        self.tree.bind("<Button-3>",  self._show_ctx_menu)

    def _build_options_row(self, parent):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 12))

        # Colonne gauche : format
        fmt_col = tk.Frame(row, bg=BG)
        fmt_col.pack(side="left", fill="x", expand=True)
        self._lbl(fmt_col, "FORMAT")
        rb_row = tk.Frame(fmt_col, bg=BG)
        rb_row.pack(anchor="w", pady=(2, 0))
        for label, val in [("MP4 Meilleur", "mp4_best"), ("MP4 1080p", "mp4_1080"),
                            ("MP4 720p", "mp4_720"), ("MP3", "mp3"), ("M4A", "m4a")]:
            tk.Radiobutton(rb_row, text=label, variable=self.format_choice, value=val,
                           bg=BG, fg=TEXT, selectcolor=ACCENT,
                           activebackground=BG, activeforeground=ACCENT2,
                           font=("Segoe UI", 9), cursor="hand2"
                           ).pack(side="left", padx=(0, 14))

        # Colonne droite : destination + options
        right = tk.Frame(row, bg=BG)
        right.pack(side="right")
        self._lbl(right, "DESTINATION")
        dest_row = tk.Frame(right, bg=BG)
        dest_row.pack(anchor="w", pady=(2, 6))
        tk.Label(dest_row, textvariable=self.download_path, bg=CARD, fg=TEXT,
                 font=("Consolas", 9), anchor="w", padx=8, width=32,
                 highlightbackground=BORDER, highlightthickness=1
                 ).pack(side="left", ipady=5)
        tk.Button(dest_row, text=" Choisir ", bg=CARD, fg=DIM,
                  font=("Segoe UI", 9), relief="flat", cursor="hand2", pady=4,
                  command=self._choose_folder).pack(side="left", padx=(4, 0))
        tk.Button(dest_row, text=" 📂 Ouvrir ", bg=CARD, fg=DIM,
                  font=("Segoe UI", 9), relief="flat", cursor="hand2", pady=4,
                  command=self._open_destination).pack(side="left", padx=(4, 0))

        opt1 = tk.Frame(right, bg=BG)
        opt1.pack(anchor="w")
        for text, var in [("Sous-titres FR/EN",       self.subtitles_var),
                           ("Numéroter les fichiers",  self.playlist_num_var),
                           ("Miniature intégrée",      self.thumbnail_var),
                           ("Sous-dossier playlist",   self.playlist_folder_var)]:
            tk.Checkbutton(opt1, text=text, variable=var,
                           bg=BG, fg=DIM, selectcolor=ACCENT,
                           activebackground=BG, font=("Segoe UI", 9)
                           ).pack(side="left", padx=(0, 12))

        opt2 = tk.Frame(right, bg=BG)
        opt2.pack(anchor="w", pady=(4, 0))
        tk.Label(opt2, text="Cookies :", bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(side="left")
        ttk.Combobox(opt2, textvariable=self.cookies_browser,
                     values=["none", "chrome", "firefox", "edge", "opera"],
                     state="readonly", width=9, font=("Segoe UI", 9)
                     ).pack(side="left", padx=(4, 16))
        tk.Label(opt2, text="Limite vitesse :", bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(side="left")
        spd = tk.Frame(opt2, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        spd.pack(side="left", padx=(4, 4))
        tk.Entry(spd, textvariable=self.speed_limit_var, bg=CARD, fg=TEXT,
                 insertbackground=TEXT, font=("Segoe UI", 9), bd=0, relief="flat",
                 width=5).pack(ipady=3, ipadx=4)
        tk.Label(opt2, text="kB/s  (0 = illimité)", bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(side="left")

        opt3 = tk.Frame(right, bg=BG)
        opt3.pack(anchor="w", pady=(6, 0))
        tk.Label(opt3, text="Simultanés :", bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(side="left")
        sp1 = tk.Frame(opt3, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        sp1.pack(side="left", padx=(4, 16))
        tk.Spinbox(sp1, textvariable=self.concurrent_var, from_=1, to=5, width=2,
                   bg=CARD, fg=TEXT, buttonbackground=CARD, relief="flat", bd=0,
                   font=("Segoe UI", 9)).pack(ipady=3, ipadx=4)
        tk.Label(opt3, text="Retry auto :", bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(side="left")
        sp2 = tk.Frame(opt3, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        sp2.pack(side="left", padx=(4, 16))
        tk.Spinbox(sp2, textvariable=self.auto_retry_var, from_=0, to=10, width=2,
                   bg=CARD, fg=TEXT, buttonbackground=CARD, relief="flat", bd=0,
                   font=("Segoe UI", 9)).pack(ipady=3, ipadx=4)
        tk.Label(opt3, text="À la fin :", bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(side="left")
        ttk.Combobox(opt3, textvariable=self.post_action_var,
                     values=["none", "open_folder", "sleep", "hibernate", "shutdown"],
                     state="readonly", width=12, font=("Segoe UI", 9)
                     ).pack(side="left", padx=(4, 0))

    def _build_buttons(self, parent):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 12))
        self.dl_btn = tk.Button(row, text="⬇  Télécharger la sélection",
                                bg=ACCENT, fg="white",
                                font=("Segoe UI", 12, "bold"),
                                relief="flat", cursor="hand2",
                                padx=28, pady=9,
                                command=self._start_download)
        self.dl_btn.pack(side="left")
        self.pause_btn = tk.Button(row, text="⏸  Pause",
                                   bg=CARD, fg=DIM,
                                   font=("Segoe UI", 11),
                                   relief="flat", cursor="hand2",
                                   padx=20, pady=9,
                                   command=self._toggle_pause,
                                   state="disabled")
        self.pause_btn.pack(side="left", padx=10)
        self.cancel_btn = tk.Button(row, text="✕  Annuler",
                                    bg=CARD, fg=DIM,
                                    font=("Segoe UI", 11),
                                    relief="flat", cursor="hand2",
                                    padx=20, pady=9,
                                    command=self._cancel_download,
                                    state="disabled")
        self.cancel_btn.pack(side="left")

    def _build_progress(self, parent):
        r1 = tk.Frame(parent, bg=BG)
        r1.pack(fill="x")
        self.prog_label = tk.Label(r1, text="Prêt.", bg=BG, fg=DIM,
                                   font=("Segoe UI", 9))
        self.prog_label.pack(side="left")
        self.prog_pct = tk.Label(r1, text="", bg=BG, fg=ACCENT2,
                                 font=("Segoe UI", 9, "bold"))
        self.prog_pct.pack(side="right")
        self.progress = ttk.Progressbar(parent, mode="determinate", maximum=100,
                                        style="Blue.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(2, 8))

        r2 = tk.Frame(parent, bg=BG)
        r2.pack(fill="x")
        self.overall_label = tk.Label(r2, text="", bg=BG, fg=DIM,
                                      font=("Segoe UI", 9))
        self.overall_label.pack(side="left")
        self.overall_pct_lbl = tk.Label(r2, text="", bg=BG, fg=SUCCESS,
                                        font=("Segoe UI", 9, "bold"))
        self.overall_pct_lbl.pack(side="right")
        self.overall_bar = ttk.Progressbar(parent, mode="determinate", maximum=100,
                                           style="Green.Horizontal.TProgressbar")
        self.overall_bar.pack(fill="x", pady=(2, 10))

    def _build_log(self, parent):
        self._lbl(parent, "JOURNAL")
        self.log = scrolledtext.ScrolledText(
            parent, bg=SURF, fg=ACCENT2, font=("Consolas", 9), height=6,
            relief="flat", bd=0, insertbackground="white",
            selectbackground=CARD, highlightbackground=BORDER, highlightthickness=1)
        self.log.pack(fill="both", expand=False, pady=(4, 0))
        for tag, col in [("ok", SUCCESS), ("warn", WARN), ("err", DANGER),
                          ("dim", DIM), ("txt", TEXT)]:
            self.log.tag_config(tag, foreground=col)

    def _apply_treeview_style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("Video.Treeview",
                    background=CARD, foreground=TEXT, fieldbackground=CARD,
                    borderwidth=0, rowheight=26, font=("Segoe UI", 10))
        s.configure("Video.Treeview.Heading",
                    background=SURF, foreground=DIM,
                    borderwidth=0, font=("Segoe UI", 9, "bold"), relief="flat")
        s.map("Video.Treeview",
              background=[("selected", "#1c2a45")],
              foreground=[("selected", TEXT)])
        s.configure("Blue.Horizontal.TProgressbar",
                    troughcolor=CARD, background=ACCENT,
                    darkcolor=ACCENT, lightcolor=ACCENT2,
                    bordercolor=CARD, troughrelief="flat", relief="flat")
        s.configure("Green.Horizontal.TProgressbar",
                    troughcolor=CARD, background=SUCCESS,
                    darkcolor=SUCCESS, lightcolor=SUCCESS,
                    bordercolor=CARD, troughrelief="flat", relief="flat")

    # =========================================================================
    # Analyse URL
    # =========================================================================

    def _fetch(self):
        url = self.url_entry.get().strip()
        if not url or url == self.PH:
            return
        if self.dl_btn.cget("state") == "disabled":
            return

        self.fetch_btn.config(state="disabled", text="  Analyse en cours…  ",
                               bg=CARD, fg=DIM)
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._videos = []
        self._focused_idx = None
        self._completed_urls = set()
        self.count_lbl.config(text="—")
        self._log(f"→  Analyse : {url}", "dim")
        self.progress.config(mode="indeterminate",
                             style="Blue.Horizontal.TProgressbar")
        self.progress.start(10)
        self.prog_label.config(text="Récupération des métadonnées…", fg=DIM)
        self.prog_pct.config(text="")
        threading.Thread(target=self._fetch_worker, args=(url,), daemon=True).start()

    def _fetch_worker(self, url):
        is_anime = self.scraper.is_anime_url(url)
        try:
            if is_anime:
                self.after(0, lambda: self.prog_label.config(
                    text="Scraping des épisodes…", fg=WARN))
                videos, title = self.scraper.scrape_series(url)
                if videos:
                    self.after(0, self._populate_list, videos, title)
                    return
                self.after(0, lambda: self.prog_label.config(
                    text="Scraping vide — tentative yt-dlp…", fg=WARN))

            opts = {"extract_flat": "in_playlist", "quiet": True, "no_warnings": True}
            fp = self.ffmpeg_path.get()
            if fp:
                opts["ffmpeg_location"] = os.path.dirname(fp)

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            entries = info.get("entries") or [info]
            entries = [e for e in entries if e]
            videos  = []
            for i, e in enumerate(entries):
                raw_url = (e.get("webpage_url") or e.get("url") or e.get("id", ""))
                if raw_url and not raw_url.startswith("http"):
                    raw_url = f"https://www.youtube.com/watch?v={raw_url}"
                videos.append({
                    "num":      i + 1,
                    "title":    e.get("title") or f"Vidéo {i + 1}",
                    "dur":      fmt_duration(e.get("duration")),
                    "dur_secs": e.get("duration") or 0,
                    "url":      raw_url,
                    "alt_urls": [],
                    "page_url": "",
                    "selected": True,
                    "done":     False,
                    "priority": "normal",
                })
            self.after(0, self._populate_list, videos, info.get("title", ""))

        except Exception as ex:
            msg = str(ex)
            if is_anime and ("unsupported" in msg.lower() or "no video" in msg.lower()):
                msg = (
                    f"Le site animé n'a pas pu être analysé automatiquement.\n\n"
                    f"Conseil : colle l'URL de la PAGE DE LA SAISON (ex: /saison1/vostfr).\n\n"
                    f"Détail : {msg}"
                )
            self.after(0, self._fetch_error, msg)

    def _populate_list(self, videos, playlist_title):
        fmt = self.format_choice.get()
        for v in videos:
            v["size_bytes"] = estimate_size_bytes(v["dur_secs"], fmt)
            v["size_str"]   = fmt_size(v["size_bytes"])

        self._playlist_title = playlist_title
        self._videos = videos
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for v in videos:
            self.tree.insert("", "end",
                             values=("☑", v["num"], v["title"],
                                     v["dur"], v["size_str"]),
                             tags=("checked",))
        self._update_count()
        self.fetch_btn.config(state="normal", text="  Analyser  ",
                               bg=ACCENT, fg="white")
        self._stop_fetch_progress()
        suffix = f'  —  "{playlist_title}"' if playlist_title else ""
        self._log(f"✓  {len(videos)} vidéo(s) trouvée(s){suffix}", "ok")

    def _fetch_error(self, msg):
        self.fetch_btn.config(state="normal", text="  Analyser  ",
                               bg=ACCENT, fg="white")
        self._stop_fetch_progress()
        self._log(f"✕  Analyse échouée : {msg}", "err")
        messagebox.showerror("Erreur d'analyse",
                             f"Impossible d'analyser cette URL :\n\n{msg}")

    def _stop_fetch_progress(self):
        self.progress.stop()
        self.progress.config(mode="determinate")
        self.progress["value"] = 0
        self.prog_label.config(text="Prêt.", fg=DIM)
        self.prog_pct.config(text="")

    # =========================================================================
    # Téléchargement
    # =========================================================================

    def _start_download(self):
        selected = [v for v in self._videos if v["selected"] and not v.get("done")]
        if not selected:
            messagebox.showwarning("Aucune vidéo sélectionnée",
                "Analysez une URL, puis cochez les vidéos à télécharger.")
            return
        if self.format_choice.get().startswith("mp4") and not self.ffmpeg_path.get():
            if not messagebox.askyesno(
                "FFmpeg manquant",
                "FFmpeg est requis pour fusionner vidéo+audio en MP4.\n"
                "Sans lui, les fichiers seront séparés.\n\nContinuer quand même ?"):
                return

        self.cancel_flag = False
        self.pause_flag  = False
        self._total = len(selected)
        self._done  = 0
        self.dl_btn.config(state="disabled", bg=CARD, fg=DIM)
        self.pause_btn.config(state="normal", fg=TEXT,
                              text="⏸  Pause", bg=CARD)
        self.cancel_btn.config(state="normal", fg=TEXT)
        self.fetch_btn.config(state="disabled", bg=CARD, fg=DIM)
        self.progress["value"] = 0
        self.overall_bar["value"] = 0
        self.prog_pct.config(text="")
        self.overall_label.config(text="")
        self.overall_pct_lbl.config(text="")

        self._save_session()
        threading.Thread(target=self._worker, args=(selected,), daemon=True).start()

    def _worker(self, videos):
        """Worker principal — délègue à DownloadEngine, gère les callbacks UI."""
        url_to_iid = {}
        for iid in self.tree.get_children():
            idx = self.tree.index(iid)
            if idx < len(self._videos):
                url_to_iid[self._videos[idx]["url"]] = iid

        self._alog(f"📁  {self.download_path.get()}", "dim")
        n = self.concurrent_var.get()
        self._alog(f"⚙  {len(videos)} vidéo(s) — {n} simultané(s)", "dim")
        self._alog("─" * 55, "dim")

        def on_video_start(v):
            self._active_urls.add(v["url"])
            iid = url_to_iid.get(v["url"])
            if iid:
                self.after(0, lambda i=iid, vv=v: self._draw_row(i, vv, "active"))
            self._alog(f"▶  [{v['num']}] {v['title']}", "txt")

        def on_video_done(v, success):
            self._active_urls.discard(v["url"])
            if not success:
                iid = url_to_iid.get(v["url"])
                if iid:
                    self.after(0, lambda i=iid, vv=v: self._draw_row(i, vv, ""))
                self._save_session()
                return
            with self._done_lock:
                self._done += 1
                snap = self._done
            self._completed_urls.add(v["url"])
            v["done"] = True
            overall = snap / self._total * 100
            iid = url_to_iid.get(v["url"])
            if iid:
                self.after(0, lambda i=iid, vv=v: self._draw_row(i, vv, "done"))
            self.after(0, lambda o=overall: self._update_overall(o))
            self._save_session()
            self.history.add(v, self.format_choice.get(),
                             self.download_path.get(),
                             self.url_entry.get())

        def on_video_paused(v):
            """Appelé par l'engine quand une vidéo est interrompue par Pause."""
            self._active_urls.discard(v["url"])
            iid = url_to_iid.get(v["url"])
            if iid:
                self.after(0, lambda i=iid, vv=v: self._draw_row(i, vv, ""))
            self._alog(f"⏸  [{v['num']}] {v['title'][:55]} — en attente", "dim")

        def on_all_done(done, total):
            self._alog("─" * 55, "dim")
            if not self.cancel_flag and done == total:
                self._alog(f"🎉  Terminé — {done} / {total} vidéo(s)", "ok")
                self.session.delete()
                self._notify_windows("Téléchargement terminé",
                                     f"{done} vidéo(s) téléchargée(s) !")
                self.after(0, self._do_post_action)
                self.after(0, messagebox.showinfo, "Terminé",
                           f"{done} vidéo(s) téléchargée(s)\n\n"
                           f"Dossier :\n{self.download_path.get()}")
            elif not self.cancel_flag:
                remaining = total - done
                self._alog(f"⚠  {done}/{total} ok, {remaining} erreur(s).", "warn")
                self._save_session()
                self.after(0, messagebox.showwarning,
                           "Téléchargement incomplet",
                           f"{done}/{total} vidéo(s) téléchargée(s).\n"
                           f"{remaining} en erreur — relancez pour réessayer.")
            else:
                self._alog(f"✕  Annulé — {done}/{total} terminée(s).", "warn")
                self._save_session()

        try:
            self.engine.run(videos,
                            on_video_start=on_video_start,
                            on_video_done=on_video_done,
                            on_all_done=on_all_done,
                            on_video_paused=on_video_paused)
        except Exception as ex:
            self._alog(f"✕  Erreur inattendue : {ex}", "err")
        finally:
            self.after(0, self._reset_ui)

    # =========================================================================
    # Hooks yt-dlp (progress)
    # =========================================================================

    def _hook(self, d):
        # Priorité : annulation > pause (ordre important)
        if self.cancel_flag:
            raise yt_dlp.utils.DownloadCancelled("Annulé")
        if self.pause_flag:
            raise DownloadPaused()

        try:
            tid = threading.current_thread().ident
            if d["status"] == "downloading":
                fname      = os.path.basename(d.get("filename", ""))
                speed      = d.get("_speed_str", "—").strip()
                eta        = d.get("_eta_str",   "—").strip()
                downloaded = d.get("downloaded_bytes") or 0
                total      = d.get("total_bytes") or d.get("total_bytes_estimate") or 0

                self._per_dl_bytes[tid] = max(self._per_dl_bytes.get(tid, 0), downloaded)

                cur_pct = (downloaded / total * 100) if total > 0 else 0.0
                with self._done_lock:
                    done_snap = self._done
                n_total = self._total or 1
                overall = (done_snap / n_total * 100) + (cur_pct / n_total)

                label = fname if len(fname) <= 70 else fname[:67] + "…"
                extra = f"   {speed}  •  ETA {eta}" if speed not in ("—", "") else ""

                t0 = self._per_dl_time.get(tid, time.time())
                if cur_pct < 0.1 and (time.time() - t0) > 4:
                    label = f"⏳  Connexion au serveur…  ({fname[:40]})"

                self.after(0, self._set_progress, cur_pct, overall, label, extra,
                           f"Vidéo {done_snap + 1} / {n_total}")

            elif d["status"] == "finished":
                fname = os.path.basename(d.get("filename", ""))
                self._alog(f"✓  {fname}", "ok")
        except (yt_dlp.utils.DownloadCancelled, DownloadPaused):
            raise   # ces deux exceptions doivent se propager — ne pas avaler
        except Exception:
            pass  # Ne jamais planter le hook — yt-dlp en dépend

    def _pp_hook(self, d):
        pp     = d.get("postprocessor", "")
        status = d.get("status", "")
        is_merge = "Merger" in pp or "VideoConvertor" in pp
        if is_merge and status == "started":
            self.after(0, self._start_ffmpeg_progress)
        elif is_merge and status == "finished":
            fname = os.path.basename(d.get("filename", ""))
            self._alog(f"🔀  Fusion terminée : {fname}", "ok")
            self.after(0, self._stop_ffmpeg_progress)

    def _start_ffmpeg_progress(self):
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        self.prog_label.config(
            text="🔀  FFmpeg — fusion vidéo + audio…  (patientez)", fg=WARN)
        self.prog_pct.config(text="")

    def _stop_ffmpeg_progress(self):
        self.progress.stop()
        self.progress.config(mode="determinate")
        self.progress["value"] = 100
        self.prog_label.config(text="Fusion terminée.", fg=SUCCESS)
        self.prog_pct.config(text="")

    def _set_progress(self, cur_pct, overall_pct, label, extra, overall_text):
        self.progress["value"]    = cur_pct
        self.overall_bar["value"] = overall_pct
        self.prog_label.config(text=label, fg=TEXT)
        self.prog_pct.config(text=f"{cur_pct:.0f}%{extra}")
        self.overall_label.config(text=overall_text, fg=DIM)
        self.overall_pct_lbl.config(text=f"{overall_pct:.0f}%")

    def _update_overall(self, pct):
        self.overall_bar["value"] = pct
        self.overall_pct_lbl.config(text=f"{pct:.0f}%")
        with self._done_lock:
            done_snap = self._done
        self.overall_label.config(
            text=f"{done_snap} / {self._total} vidéo(s) terminée(s)")

    def _cancel_download(self):
        self.cancel_flag = True
        self.pause_flag  = False   # débloquer les workers en attente de pause
        self._log("⚠  Annulation en cours…", "warn")
        self.pause_btn.config(state="disabled", fg=DIM, text="⏸  Pause", bg=CARD)

    def _toggle_pause(self):
        if self.pause_flag:
            self._resume_download()
        else:
            self._pause_download()

    def _pause_download(self):
        self.pause_flag = True
        self.pause_btn.config(text="▶  Reprendre", bg=WARN, fg="white")
        self.prog_label.config(text="⏸  En pause — cliquez Reprendre pour continuer",
                               fg=WARN)
        self._log("⏸  Pause demandée — les téléchargements en cours s'arrêtent…",
                  "warn")
        self._save_session()   # sauvegarder l'état immédiatement

    def _resume_download(self):
        self.pause_flag = False
        self.pause_btn.config(text="⏸  Pause", bg=CARD, fg=TEXT)
        self.prog_label.config(text="Reprise…", fg=DIM)
        self._log("▶  Reprise des téléchargements.", "ok")

    def _reset_ui(self):
        self._active_urls.clear()
        self.pause_flag = False
        self.progress.stop()
        self.progress.config(mode="determinate")
        self.progress["value"]    = 0
        self.overall_bar["value"] = 0
        self.prog_label.config(text="Prêt.", fg=DIM)
        self.prog_pct.config(text="")
        self.overall_label.config(text="")
        self.overall_pct_lbl.config(text="")
        self.dl_btn.config(state="normal", bg=ACCENT, fg="white")
        self.pause_btn.config(state="disabled", fg=DIM,
                              text="⏸  Pause", bg=CARD)
        self.cancel_btn.config(state="disabled", fg=DIM)
        self.fetch_btn.config(state="normal", text="  Analyser  ",
                               bg=ACCENT, fg="white")

    # =========================================================================
    # Session
    # =========================================================================

    def _current_settings(self) -> dict:
        """Capture tous les réglages de l'app dans un dict sérialisable."""
        return {
            "ffmpeg_path":       self.ffmpeg_path.get(),
            "cookies_browser":   self.cookies_browser.get(),
            "subtitles":         self.subtitles_var.get(),
            "thumbnail":         self.thumbnail_var.get(),
            "playlist_num":      self.playlist_num_var.get(),
            "playlist_folder":   self.playlist_folder_var.get(),
            "speed_limit":       self.speed_limit_var.get(),
            "concurrent":        self.concurrent_var.get(),
            "auto_retry":        self.auto_retry_var.get(),
            "post_action":       self.post_action_var.get(),
        }

    def _save_session(self):
        data = self.session.build(
            url=self.url_entry.get(),
            fmt=self.format_choice.get(),
            dest=self.download_path.get(),
            completed_urls=self._completed_urls,
            videos=self._videos,
            settings=self._current_settings(),
        )
        self.session.save(data)

    def _check_resume(self):
        data = self.session.load()
        if not data:
            return
        completed = set(data.get("completed", []))
        pending   = [v for v in data.get("videos", [])
                     if v.get("selected") and v["url"] not in completed]
        if not pending:
            self.session.delete()
            return

        url      = data.get("url", "")
        n_ok     = len(completed)
        n_rem    = len(pending)
        fmt      = data.get("format", "?")
        dest     = data.get("download_path", "?")
        saved_at = data.get("saved_at", "")

        # Formater la date de sauvegarde de façon lisible
        date_str = ""
        if saved_at:
            try:
                from datetime import datetime
                dt   = datetime.fromisoformat(saved_at)
                diff = datetime.now() - dt
                days = diff.days
                if days == 0:
                    hours = diff.seconds // 3600
                    date_str = f"il y a {hours}h" if hours else "il y a moins d'1h"
                elif days == 1:
                    date_str = "hier"
                else:
                    date_str = f"il y a {days} jour(s)"
                date_str = f"  ⏱ Sauvegardée : {date_str} ({dt.strftime('%d/%m/%Y %H:%M')})\n"
            except Exception:
                date_str = f"  ⏱ Sauvegardée : {saved_at}\n"

        if messagebox.askyesno(
            "Session interrompue — Reprendre ?",
            f"Un téléchargement précédent n'est pas terminé.\n\n"
            f"  ✓ Terminées  : {n_ok} vidéo(s)\n"
            f"  ⏳ Restantes : {n_rem} vidéo(s)\n"
            f"  📁 Dossier   : {dest[:55]}{'…' if len(dest)>55 else ''}\n"
            f"  🎞 Format    : {fmt}\n"
            f"{date_str}\n"
            "Les fichiers partiels (.part) seront repris là où ils s'étaient\n"
            "arrêtés — aucun octet ne sera re-téléchargé.\n\n"
            "Reprendre maintenant ?"):
            self._restore_session(data)
        else:
            if messagebox.askyesno(
                "Supprimer la session ?",
                "Voulez-vous effacer la session sauvegardée ?\n\n"
                "Si vous répondez Non, elle restera disponible et vous\n"
                "serez de nouveau invité(e) au prochain démarrage.",
                icon="warning"):
                self.session.delete()

    def _restore_session(self, data):
        # ── Restaurer les réglages sauvegardés ────────────────────────────
        s = data.get("settings", {})
        if s.get("ffmpeg_path") and os.path.isfile(s["ffmpeg_path"]):
            self.ffmpeg_path.set(s["ffmpeg_path"])
            self._refresh_badge()
        if s.get("cookies_browser"):
            self.cookies_browser.set(s["cookies_browser"])
        if "subtitles"      in s: self.subtitles_var.set(s["subtitles"])
        if "thumbnail"      in s: self.thumbnail_var.set(s["thumbnail"])
        if "playlist_num"   in s: self.playlist_num_var.set(s["playlist_num"])
        if "playlist_folder" in s: self.playlist_folder_var.set(s["playlist_folder"])
        if "speed_limit"    in s: self.speed_limit_var.set(s["speed_limit"])
        if "concurrent"     in s: self.concurrent_var.set(s["concurrent"])
        if "auto_retry"     in s: self.auto_retry_var.set(s["auto_retry"])
        if "post_action"    in s: self.post_action_var.set(s["post_action"])

        # ── Restaurer URL / format / destination ──────────────────────────
        url = data.get("url", "")
        if url and url != self.PH:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)
            self.url_entry.config(fg=TEXT)
        self.format_choice.set(data.get("format", "mp4_best"))
        path = data.get("download_path", "")
        if path and os.path.isdir(path):
            self.download_path.set(path)

        # ── Restaurer la liste de vidéos ──────────────────────────────────
        completed = set(data.get("completed", []))
        self._completed_urls = completed
        fmt    = self.format_choice.get()
        videos = []
        for v in data.get("videos", []):
            v["done"]       = v["url"] in completed
            v["size_bytes"] = estimate_size_bytes(v.get("dur_secs", 0), fmt)
            v["size_str"]   = fmt_size(v["size_bytes"])
            v.setdefault("priority", "normal")
            v.setdefault("alt_urls", [])
            v.setdefault("page_url", "")
            videos.append(v)

        self._videos = videos
        self._focused_idx = None
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for v in videos:
            if v["done"]:
                tag, chk = "done",    "✓"
            elif v["selected"]:
                prio = v.get("priority", "normal")
                tag  = "high_prio" if prio == "high" else ("low_prio" if prio == "low" else "checked")
                chk  = "⬆" if prio == "high" else ("⬇" if prio == "low" else "☑")
            else:
                tag, chk = "unchecked", "☐"
            self.tree.insert("", "end",
                             values=(chk, v["num"], v["title"],
                                     v["dur"], v["size_str"]),
                             tags=(tag,))
        self._update_count()
        n_done = sum(1 for v in videos if v["done"])
        n_rem  = sum(1 for v in videos if v["selected"] and not v["done"])
        self._log(
            f"✓  Session restaurée — {n_done} déjà terminée(s), "
            f"{n_rem} à reprendre  (les fichiers .part seront continués)", "ok")

    # =========================================================================
    # Historique
    # =========================================================================

    def _show_history(self):
        history = self.history.load()

        win = tk.Toplevel(self)
        win.title("Historique des téléchargements")
        win.geometry("900x520")
        win.configure(bg=BG)
        win.minsize(700, 380)

        hdr = tk.Frame(win, bg=SURF, height=46)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="📋  Historique des téléchargements",
                 font=("Segoe UI", 12, "bold"), bg=SURF, fg=TEXT
                 ).pack(side="left", padx=16, pady=10)
        tk.Label(hdr, text=f"{len(history)} entrée(s)",
                 font=("Segoe UI", 9), bg=SURF, fg=DIM
                 ).pack(side="right", padx=16)
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)

        search_var = tk.StringVar()
        s_row = tk.Frame(body, bg=BG)
        s_row.pack(fill="x", pady=(0, 8))
        tk.Label(s_row, text="Rechercher :", bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        s_wrap = tk.Frame(s_row, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        s_wrap.pack(side="left", fill="x", expand=True)
        tk.Entry(s_wrap, bg=CARD, fg=TEXT, insertbackground=TEXT,
                 font=("Segoe UI", 10), bd=0, relief="flat",
                 textvariable=search_var
                 ).pack(fill="x", ipady=6, ipadx=8, pady=1, padx=1)
        tk.Button(s_row, text="  Vider l'historique  ",
                  bg=DANGER, fg="white", font=("Segoe UI", 9),
                  relief="flat", cursor="hand2", padx=8,
                  command=lambda: _clear_all()
                  ).pack(side="right", padx=(8, 0))

        tree_frame = tk.Frame(body, bg=CARD,
                              highlightbackground=BORDER, highlightthickness=1)
        tree_frame.pack(fill="both", expand=True)

        cols = ("date", "title", "fmt", "dur", "dest")
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                            style="Video.Treeview", selectmode="browse")
        tree.heading("date",  text="Date",    anchor="w")
        tree.heading("title", text="Titre",   anchor="w")
        tree.heading("fmt",   text="Format",  anchor="center")
        tree.heading("dur",   text="Durée",   anchor="center")
        tree.heading("dest",  text="Dossier", anchor="w")
        tree.column("date",  width=120, stretch=False, anchor="w")
        tree.column("title", width=380, stretch=True,  anchor="w")
        tree.column("fmt",   width=90,  stretch=False, anchor="center")
        tree.column("dur",   width=65,  stretch=False, anchor="center")
        tree.column("dest",  width=200, stretch=True,  anchor="w")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))

        def _get_filtered():
            return self.history.search(search_var.get())

        def _retelecharger():
            sel = tree.selection()
            if not sel:
                return
            idx = tree.index(sel[0])
            filtered = _get_filtered()
            if idx >= len(filtered):
                return
            entry = filtered[idx]
            url = entry.get("playlist_url") or entry.get("url", "")
            if not url:
                return
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)
            self.url_entry.config(fg=TEXT)
            self.format_choice.set(entry.get("format", "mp4_best"))
            dest = entry.get("dest", "")
            if dest and os.path.isdir(dest):
                self.download_path.set(dest)
            win.destroy()
            self._fetch()

        def _supprimer():
            sel = tree.selection()
            if not sel:
                return
            idx = tree.index(sel[0])
            filtered = _get_filtered()
            if idx >= len(filtered):
                return
            self.history.remove(filtered[idx].get("url", ""))
            tree.delete(sel[0])

        def _clear_all():
            if messagebox.askyesno("Confirmation",
                                   "Supprimer tout l'historique ?", parent=win):
                self.history.clear()
                for iid in tree.get_children():
                    tree.delete(iid)

        def _on_ctx(event):
            iid = tree.identify_row(event.y)
            if not iid:
                return
            tree.selection_set(iid)
            idx      = tree.index(iid)
            filtered = _get_filtered()
            if idx >= len(filtered):
                return
            entry = filtered[idx]
            ctx = tk.Menu(win, tearoff=0, bg=CARD, fg=TEXT,
                          activebackground=ACCENT, activeforeground="white",
                          font=("Segoe UI", 9), bd=0, relief="flat")
            ctx.add_command(label="⬇  Re-télécharger", command=_retelecharger)
            ctx.add_command(label="▶  Ouvrir dans le navigateur",
                            command=lambda: webbrowser.open(entry.get("url", "")))
            ctx.add_command(label="📂  Ouvrir le dossier",
                            command=lambda: (
                                os.startfile(entry.get("dest", ""))
                                if os.path.isdir(entry.get("dest", "")) else None))
            ctx.add_separator()
            ctx.add_command(label="🗑  Supprimer de l'historique",
                            command=_supprimer)
            ctx.tk_popup(event.x_root, event.y_root)

        def _populate(filtered=None):
            for iid in tree.get_children():
                tree.delete(iid)
            for h in (filtered if filtered is not None else history):
                tree.insert("", "end", values=(
                    h.get("date", ""), h.get("title", ""),
                    h.get("format", ""), h.get("dur", "—"), h.get("dest", "")))

        tk.Button(btn_row, text="⬇  Re-télécharger", bg=ACCENT, fg="white",
                  font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2",
                  padx=16, pady=7, command=_retelecharger).pack(side="left")
        tk.Button(btn_row, text="🗑  Supprimer cette entrée", bg=CARD, fg=DIM,
                  font=("Segoe UI", 10), relief="flat", cursor="hand2",
                  padx=16, pady=7, command=_supprimer).pack(side="left", padx=8)
        tk.Label(btn_row, text="Double-clic → Re-télécharger",
                 bg=BG, fg=DIM, font=("Segoe UI", 8)).pack(side="right")

        search_var.trace_add("write", lambda *_: _populate(_get_filtered()))
        tree.bind("<Double-1>", lambda e: _retelecharger())
        tree.bind("<Button-3>",  _on_ctx)
        _populate()

    # =========================================================================
    # Presse-papiers
    # =========================================================================

    def _tick_clipboard(self):
        if self.clip_monitor_var.get():
            try:
                text = self.clipboard_get().strip()
                if text != self._clip_last and self._CLIP_URL_RE.match(text):
                    self._clip_last = text
                    self._on_clip_url_detected(text)
            except Exception:
                pass
        self.after(600, self._tick_clipboard)

    def _on_clip_url_detected(self, url):
        if self.dl_btn.cget("state") == "disabled":
            return
        current = self.url_entry.get().strip()
        if current != url and current != self.PH:
            if not messagebox.askyesno(
                "URL détectée dans le presse-papiers",
                f"Une nouvelle URL a été copiée :\n\n{url[:80]}\n\n"
                "L'analyser maintenant ?", parent=self):
                return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, url)
        self.url_entry.config(fg=TEXT)
        self._fetch()

    def _toggle_clipboard_monitor(self, _=None):
        val = not self.clip_monitor_var.get()
        self.clip_monitor_var.set(val)
        if val:
            self.clip_badge.config(text="📋 Clip: ON", fg=SUCCESS)
            self._log("📋  Surveillance presse-papiers activée.", "ok")
        else:
            self.clip_badge.config(text="📋 Clip: OFF", fg=DIM)
            self._log("📋  Surveillance presse-papiers désactivée.", "dim")

    # =========================================================================
    # Action post-téléchargement + Notification Windows
    # =========================================================================

    def _notify_windows(self, title, message):
        try:
            ps = (
                f'[Windows.UI.Notifications.ToastNotificationManager,'
                f' Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null;'
                f'$t=[Windows.UI.Notifications.ToastTemplateType]::ToastText02;'
                f'$x=[Windows.UI.Notifications.ToastNotificationManager]'
                f'::GetTemplateContent($t);'
                f'$x.GetElementsByTagName("text")[0].AppendChild($x.CreateTextNode("{title}")) | Out-Null;'
                f'$x.GetElementsByTagName("text")[1].AppendChild($x.CreateTextNode("{message}")) | Out-Null;'
                f'$n=[Windows.UI.Notifications.ToastNotification]::new($x);'
                f'[Windows.UI.Notifications.ToastNotificationManager]'
                f'::CreateToastNotifier("YTDownloader").Show($n);'
            )
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass

    def _do_post_action(self):
        action = self.post_action_var.get()
        if action == "open_folder":
            path = self.download_path.get()
            if os.path.isdir(path):
                os.startfile(path)
        elif action == "sleep":
            self._alog("💤  Mise en veille dans 10 s…", "warn")
            self.after(10_000, lambda: subprocess.run(
                ["powershell", "-Command",
                 "Add-Type -Assembly System.Windows.Forms;"
                 "[System.Windows.Forms.Application]"
                 ".SetSuspendState('Suspend',$false,$false)"],
                creationflags=subprocess.CREATE_NO_WINDOW))
        elif action == "hibernate":
            self._alog("💤  Mise en veille prolongée dans 10 s…", "warn")
            self.after(10_000, lambda: subprocess.run(
                ["shutdown", "/h"],
                creationflags=subprocess.CREATE_NO_WINDOW))
        elif action == "shutdown":
            self._alog("🔴  Extinction dans 60 s…", "warn")
            subprocess.run(["shutdown", "/s", "/t", "60"],
                           creationflags=subprocess.CREATE_NO_WINDOW)

    # =========================================================================
    # Treeview — manipulation de la liste
    # =========================================================================

    def _toggle_row(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        idx = self.tree.index(iid)
        if 0 <= idx < len(self._videos):
            v = self._videos[idx]
            if v.get("done"):
                return
            v["selected"] = not v["selected"]
            self._focused_idx = idx
            self._redraw_all()
            self._update_count()

    def _draw_row(self, iid, v, state):
        if state == "done" or v.get("done"):
            tag, chk = "done", "✓"
        elif state == "active" or v["url"] in self._active_urls:
            tag, chk = "active", "▶"
        elif v["selected"]:
            prio = v.get("priority", "normal")
            if prio == "high":
                tag, chk = "high_prio", "⬆"
            elif prio == "low":
                tag, chk = "low_prio",  "⬇"
            elif (self._focused_idx is not None
                  and self.tree.index(iid) == self._focused_idx):
                tag, chk = "focused", "☑"
            else:
                tag, chk = "checked", "☑"
        else:
            tag, chk = "unchecked", "☐"
        self.tree.item(iid, values=(chk, v["num"], v["title"],
                                    v["dur"], v.get("size_str", "—")),
                       tags=(tag,))

    def _redraw_all(self):
        for iid in self.tree.get_children():
            idx = self.tree.index(iid)
            if idx < len(self._videos):
                self._draw_row(iid, self._videos[idx], "")

    def _update_count(self):
        sel = sum(1 for v in self._videos if v["selected"] and not v.get("done"))
        tot = len(self._videos)
        self.count_lbl.config(
            text=f"{sel} sélectionnée(s) / {tot}" if tot else "—")

    def _select_all(self):
        for v in self._videos:
            if not v.get("done"):
                v["selected"] = True
        self._redraw_all()
        self._update_count()

    def _deselect_all(self):
        for v in self._videos:
            if not v.get("done"):
                v["selected"] = False
        self._redraw_all()
        self._update_count()

    def _move_up(self):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        idx = self.tree.index(iid)
        if idx > 0:
            self.tree.move(iid, "", idx - 1)
            self._videos[idx], self._videos[idx - 1] = \
                self._videos[idx - 1], self._videos[idx]
            self._focused_idx = idx - 1

    def _move_down(self):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        idx = self.tree.index(iid)
        if idx < len(self._videos) - 1:
            self.tree.move(iid, "", idx + 1)
            self._videos[idx], self._videos[idx + 1] = \
                self._videos[idx + 1], self._videos[idx]
            self._focused_idx = idx + 1

    def _on_format_change(self, *_):
        fmt = self.format_choice.get()
        for v in self._videos:
            v["size_bytes"] = estimate_size_bytes(v.get("dur_secs", 0), fmt)
            v["size_str"]   = fmt_size(v["size_bytes"])
        self._redraw_all()

    def _show_ctx_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        idx = self.tree.index(iid)
        if idx >= len(self._videos):
            return
        v = self._videos[idx]

        menu = tk.Menu(self, tearoff=0, bg=CARD, fg=TEXT,
                       activebackground=ACCENT, activeforeground="white",
                       font=("Segoe UI", 9), relief="flat", bd=0)
        menu.add_command(label="▶  Ouvrir dans le navigateur",
                         command=lambda: webbrowser.open(v["url"]))
        menu.add_command(label="📋  Copier l'URL",
                         command=lambda: (self.clipboard_clear(),
                                          self.clipboard_append(v["url"])))
        menu.add_separator()

        if not v.get("done"):
            # ── Priorité (style uTorrent) ──────────────────────────────────
            cur_prio = v.get("priority", "normal")
            prio_menu = tk.Menu(menu, tearoff=0, bg=CARD, fg=TEXT,
                                activebackground=ACCENT, activeforeground="white",
                                font=("Segoe UI", 9), relief="flat", bd=0)
            for label, key in [("⬆  Haute",  "high"),
                                ("●  Normale", "normal"),
                                ("⬇  Basse",  "low")]:
                is_cur = (key == cur_prio)
                prio_menu.add_command(
                    label=("✓ " if is_cur else "  ") + label,
                    command=lambda k=key: self._set_priority(idx, k))
            menu.add_cascade(label="⚡  Priorité", menu=prio_menu)
            menu.add_separator()

            toggle_label = "☐  Décocher" if v["selected"] else "☑  Cocher"
            menu.add_command(label=toggle_label,
                             command=lambda: self._toggle_by_idx(idx))

        menu.tk_popup(event.x_root, event.y_root)

    def _toggle_by_idx(self, idx):
        if 0 <= idx < len(self._videos):
            v = self._videos[idx]
            if not v.get("done"):
                v["selected"] = not v["selected"]
                self._focused_idx = idx
                self._redraw_all()
                self._update_count()

    def _set_priority(self, idx, priority):
        """Modifie la priorité d'une vidéo (high/normal/low).

        Comme _videos et la liste pending de l'engine partagent les mêmes
        dict par référence, le changement est pris en compte dès que le
        prochain slot de téléchargement se libère.
        """
        if 0 <= idx < len(self._videos):
            v = self._videos[idx]
            if not v.get("done"):
                v["priority"] = priority
                iids = self.tree.get_children()
                if idx < len(iids):
                    self._draw_row(iids[idx], v, "")
                labels = {"high": "Haute ⬆", "normal": "Normale", "low": "Basse ⬇"}
                self._alog(
                    f"⚙  [{v['num']}] {v['title'][:50]} → priorité {labels[priority]}",
                    "dim")

    # =========================================================================
    # Helpers / Divers
    # =========================================================================

    def _lbl(self, parent, text):
        tk.Label(parent, text=text, bg=BG, fg=DIM,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(4, 0))

    def _lbl_inline(self, parent, text):
        tk.Label(parent, text=text, bg=BG, fg=DIM,
                 font=("Segoe UI", 8, "bold")).pack(side="left", anchor="w")

    def _log(self, msg, tag=""):
        self.log.insert("end", msg + "\n", tag)
        self.log.see("end")

    def _alog(self, msg, tag=""):
        self.after(0, self._log, msg, tag)

    def _refresh_badge(self):
        if self.ffmpeg_path.get():
            self.ffmpeg_badge.config(text="✓ FFmpeg", fg=SUCCESS)
        else:
            self.ffmpeg_badge.config(
                text="⚠ FFmpeg manquant — cliquer pour localiser", fg=WARN)

    def _check_ffmpeg_on_start(self):
        if self.ffmpeg_path.get():
            self._log(f"✓  FFmpeg : {self.ffmpeg_path.get()}", "ok")
        else:
            self._log(
                "⚠  FFmpeg introuvable. Lancez : winget install --id Gyan.FFmpeg -e",
                "warn")

    def _locate_ffmpeg(self):
        path = filedialog.askopenfilename(
            title="Localiser ffmpeg.exe",
            filetypes=[("FFmpeg executable", "ffmpeg.exe"), ("Tous", "*.*")],
            initialdir=os.path.expanduser("~/Downloads"))
        if path and os.path.isfile(path):
            self.ffmpeg_path.set(path)
            self._refresh_badge()
            self._log(f"✓  FFmpeg configuré : {path}", "ok")

    def _clear_ph(self, _):
        if self.url_entry.get() == self.PH:
            self.url_entry.delete(0, "end")
            self.url_entry.config(fg=TEXT)

    def _restore_ph(self, _):
        if not self.url_entry.get().strip():
            self.url_entry.insert(0, self.PH)
            self.url_entry.config(fg=DIM)

    def _choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.download_path.get())
        if folder:
            self.download_path.set(folder)

    def _open_destination(self):
        path = self.download_path.get()
        if os.path.isdir(path):
            os.startfile(path)
        else:
            messagebox.showwarning("Dossier introuvable",
                                   f"Le dossier n'existe pas :\n{path}")

    def _on_close(self):
        if self.dl_btn.cget("state") == "disabled":
            if not messagebox.askyesno(
                "Téléchargement en cours",
                "Un téléchargement est en cours.\n\n"
                "La session sera sauvegardée.\n"
                "Voulez-vous quitter quand même ?"):
                return
            self._save_session()
        self.destroy()

    def _check_ytdlp_update(self):
        def _run():
            try:
                import yt_dlp as _ytdlp
                current = getattr(_ytdlp.version, "__version__", "?")
                self._alog(f"yt-dlp v{current}", "dim")
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()


# ─── Entrée ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
