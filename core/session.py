"""
SessionManager — persistance de la session de téléchargement.
Responsabilité unique : sauvegarder/restaurer l'état entre les redémarrages.

La session est conçue pour survivre indéfiniment (extinction machine, redémarrage,
semaine d'inactivité). Elle sauvegarde :
  • L'intégralité des métadonnées vidéo (alt_urls, page_url, priority…)
  • Tous les réglages de l'application nécessaires à la reprise
  • L'horodatage de la dernière sauvegarde
"""
import json
import os
from datetime import datetime
from .constants import SESSION_FILE


class SessionManager:
    def __init__(self, filepath: str = SESSION_FILE):
        self._path = filepath

    def exists(self) -> bool:
        return os.path.isfile(self._path)

    def save(self, data: dict):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load(self) -> dict | None:
        try:
            if self.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def delete(self):
        try:
            os.remove(self._path)
        except Exception:
            pass

    def build(self, url: str, fmt: str, dest: str,
              completed_urls: set, videos: list,
              settings: dict | None = None) -> dict:
        """
        Construit le dict de session complet à sauvegarder.

        Tous les champs du dict vidéo sont conservés tels quels afin de
        garantir une reprise identique (alt_urls, page_url, priority, …).
        Les réglages applicatifs (ffmpeg, browser, options…) sont inclus
        pour que la reprise après redémarrage soit transparente.
        """
        # Champs vidéo à conserver — on garde TOUT pour la reprise fidèle
        _VIDEO_FIELDS = (
            "num", "title", "dur", "dur_secs", "url",
            "alt_urls", "page_url", "selected", "done", "priority",
        )
        return {
            "saved_at":      datetime.now().isoformat(timespec="seconds"),
            "url":           url,
            "format":        fmt,
            "download_path": dest,
            "completed":     list(completed_urls),
            "settings":      settings or {},
            "videos": [
                {k: v.get(k, _DEFAULTS.get(k)) for k in _VIDEO_FIELDS}
                for v in videos
            ],
        }


# Valeurs par défaut pour les champs vidéo optionnels
_DEFAULTS = {
    "alt_urls": [],
    "page_url": "",
    "priority": "normal",
    "done":     False,
    "selected": True,
    "dur_secs": 0,
    "dur":      "—",
}
