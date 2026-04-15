"""
HistoryManager — gestion de l'historique des téléchargements.
Responsabilité unique : lire/écrire/rechercher l'historique JSON.
"""
import json
import datetime
import os
from .constants import HISTORY_FILE


class HistoryManager:
    MAX_ENTRIES = 500

    def __init__(self, filepath: str = HISTORY_FILE):
        self._path = filepath

    def load(self) -> list:
        try:
            if os.path.isfile(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def save(self, history: list):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add(self, video: dict, fmt: str, dest: str, playlist_url: str = ""):
        """Ajoute une entrée en tête ; évite les doublons d'URL."""
        history = self.load()
        history = [h for h in history if h.get("url") != video["url"]]
        history.insert(0, {
            "date":         datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "title":        video["title"],
            "url":          video["url"],
            "format":       fmt,
            "dest":         dest,
            "dur":          video.get("dur", "—"),
            "playlist_url": playlist_url,
        })
        self.save(history[:self.MAX_ENTRIES])

    def remove(self, url: str):
        history = self.load()
        self.save([h for h in history if h.get("url") != url])

    def clear(self):
        self.save([])

    def search(self, query: str) -> list:
        q = query.lower()
        return [h for h in self.load()
                if not q
                or q in h.get("title", "").lower()
                or q in h.get("dest", "").lower()]
