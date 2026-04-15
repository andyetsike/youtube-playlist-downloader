"""
AnimeScraper — scraping de séries animées et résolution de lecteurs embarqués.

Responsabilité unique : extraire des URLs de vidéos depuis des pages web,
sans aucune dépendance sur l'UI.

Méthodes principales :
  scrape_series(url)          -> (videos_list, playlist_title)
  scrape_episode_players(url) -> [player_url, ...]
  resolve_vidmoly(embed_url)  -> (direct_video_url, referer) ou (None, None)
"""
from __future__ import annotations
import re
import urllib.request
from .constants import ANIME_DOMAINS, PREFERRED_HOSTS

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_BASE_HEADERS = {
    "User-Agent":      _UA,
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
}


class AnimeScraper:
    """
    Scrape les pages de séries/épisodes animés pour trouver les URLs vidéo.
    Accepte un callable log_fn(msg, tag) pour le journal de l'UI.
    """

    def __init__(self, log_fn=None):
        self._log = log_fn or (lambda msg, tag="": None)

    # ── API publique ──────────────────────────────────────────────────────────

    def is_anime_url(self, url: str) -> bool:
        return any(d in url for d in ANIME_DOMAINS)

    def scrape_series(self, url: str) -> tuple[list, str]:
        """
        Scrape la page d'une série/saison.

        Stratégie (par ordre de priorité) :
          1. Tableaux JavaScript  (animes-sama.fr)
             var x = ["https://sibnet.ru/...", ...]
          2. Sous-pages / liens épisodes  (voiranime, etc.)

        Retourne (videos_list, playlist_title).
        """
        headers = {**_BASE_HEADERS, "Referer": url}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        m     = re.match(r"(https?://[^/]+)", url)
        base  = m.group(1) if m else ""
        url_clean = url.rstrip("/")

        # Titre de la série
        t_m   = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        title = re.sub(r"\s*[|\-–—].*$", "",
                       t_m.group(1).strip() if t_m else "").strip()

        # Méthode 1 : tableaux JS
        videos = self._method_js_arrays(html, url, title)
        if videos:
            return videos, title

        # Méthode 2 : liens de sous-pages
        return self._method_subpage_links(html, url, base, url_clean, title)

    def scrape_episode_players(self, url: str) -> list[str]:
        """
        Scrape une page d'épisode pour trouver les iframes/data-src.
        Retourne les URLs externes (hors domaine du site).
        """
        try:
            headers = {**_BASE_HEADERS, "Referer": url}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            own_domain = url.split("/")[2] if url.count("/") >= 2 else ""
            iframes    = re.findall(
                r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
            data_attrs = re.findall(
                r'data-(?:src|url|embed|video|player|link)=["\']([^"\']+)["\']',
                html, re.IGNORECASE)

            players, seen = [], set()
            for u in iframes + data_attrs:
                u = u.strip()
                if not u.startswith("http"):
                    continue
                if own_domain and own_domain in u:
                    continue
                if u not in seen:
                    seen.add(u)
                    players.append(u)
            return players
        except Exception:
            return []

    def resolve_vidmoly(self, embed_url: str) -> tuple[str | None, str | None]:
        """
        Vidmoly exige un token JWT avant de servir son contenu.
        La page initiale contient uniquement :
            window.location.replace('...?ch=1&js=JWT')

        Étapes :
          1. Récupère la page embed initiale
          2. Extrait l'URL de redirection JWT
          3. Récupère cette seconde page
          4. Cherche l'URL vidéo directe (m3u8 / mp4 / JWPlayer)

        Retourne (video_url, referer) ou (None, None).
        """
        try:
            headers = {**_BASE_HEADERS, "Referer": embed_url}

            req1 = urllib.request.Request(embed_url, headers=headers)
            with urllib.request.urlopen(req1, timeout=15) as r1:
                html1 = r1.read().decode("utf-8", errors="replace")

            m_redir = re.search(
                r"window\.location\.replace\(['\"]([^'\"]+)['\"]", html1)
            if not m_redir:
                jwt_url = embed_url
                html2   = html1
            else:
                jwt_url = m_redir.group(1)
                req2 = urllib.request.Request(
                    jwt_url, headers={**headers, "Referer": embed_url})
                with urllib.request.urlopen(req2, timeout=15) as r2:
                    html2 = r2.read().decode("utf-8", errors="replace")

            for pat in [
                r'["\']?(https?://[^"\'>\s]+\.m3u8[^"\'>\s]*)["\']?',
                r'["\']?(https?://[^"\'>\s]+\.mpd[^"\'>\s]*)["\']?',
                r'["\']?(https?://[^"\'>\s]+\.mp4[^"\'>\s]*)["\']?',
                r'file\s*:\s*["\']([^"\']{15,})["\']',
                r'src\s*:\s*["\']([^"\']{15,})["\']',
                r'"file"\s*:\s*"([^"]{15,})"',
            ]:
                for match in re.finditer(pat, html2):
                    u = match.group(1)
                    if u.startswith("http") and (
                            ".m3u8" in u or ".mp4" in u or ".mpd" in u
                            or "cdn"  in u or "stream" in u):
                        return u, embed_url
            return None, None

        except Exception as exc:
            self._log(f"  ⚠ Vidmoly resolver: {exc}", "dim")
            return None, None

    # ── Méthodes privées ──────────────────────────────────────────────────────

    def _method_js_arrays(self, html: str, page_url: str, title: str) -> list:
        """Extrait les tableaux JS de type var x = ["url1", "url2", ...]."""
        js_arrays = re.findall(r'var\s+\w+\s*=\s*\[([^\]]+)\]', html)
        url_arrays = []
        for arr in js_arrays:
            urls = re.findall(r'"(https?://[^"]+)"', arr)
            if len(urls) >= 2:
                url_arrays.append(urls)
        if not url_arrays:
            return []

        # Choisir le tableau du meilleur hôte
        primary = url_arrays[0]
        for host in PREFERRED_HOSTS:
            for arr in url_arrays:
                if any(host in u for u in arr if u):
                    primary = arr
                    break
            else:
                continue
            break

        alt_arrays = [a for a in url_arrays if a is not primary]
        n_eps = max(len(a) for a in url_arrays)

        videos = []
        for i in range(n_eps):
            ep_url   = primary[i] if i < len(primary) else ""
            alt_urls = [
                alt[i] for alt in alt_arrays
                if i < len(alt) and alt[i] and alt[i] != ep_url
            ]
            if not ep_url:
                ep_url   = next((u for u in alt_urls if u), "")
                alt_urls = [u for u in alt_urls if u != ep_url]
            if not ep_url:
                continue

            videos.append({
                "num":      i + 1,
                "title":    f"Épisode {i + 1}",
                "dur":      "—",
                "dur_secs": 0,
                "url":      ep_url,
                "alt_urls": alt_urls,
                "page_url": page_url,
                "selected": True,
                "done":     False,
                "priority": "normal",
            })

        if videos:
            host = primary[0].split("/")[2] if primary else "?"
            self._log(
                f"  → {len(videos)} épisode(s) via {host}"
                f" + {len(alt_arrays)} source(s) alt.", "dim")
        return videos

    def _method_subpage_links(self, html: str, url: str,
                              base: str, url_clean: str,
                              title: str) -> tuple[list, str]:
        """Extrait les liens de sous-pages avec mots-clés d'épisode."""
        raw_hrefs = re.findall(r'href=["\']([^"\'#?]+)["\']', html)
        seen, sub_links, kw_links = set(), [], []

        for href in raw_hrefs:
            href = href.strip()
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = base + href
            elif not href.startswith("http"):
                continue
            if base and not href.startswith(base):
                continue
            if href.rstrip("/") == url_clean or href in seen:
                continue
            seen.add(href)

            if href.startswith(url_clean + "/"):
                sub_links.append(href)
            elif any(kw in href.lower() for kw in [
                    "episode", "-ep-", "/ep-", "ep-", "_ep",
                    "saison", "season", "partie", "part-", "oav", "ova"]):
                kw_links.append(href)

        candidates = sub_links + [u for u in kw_links if u not in sub_links]
        if not candidates:
            return [], title

        def _ep_num(u):
            path = u.rstrip("/").split("/")[-1].lower()
            m2 = re.search(r"(?:episode|ep)[-_]?(\d+)", path)
            if m2:
                return int(m2.group(1))
            m3 = re.search(r"(\d+)$", path)
            return int(m3.group(1)) if m3 else 0

        candidates.sort(key=_ep_num)
        videos = []
        for i, ep_url in enumerate(candidates):
            slug  = ep_url.rstrip("/").split("/")[-1]
            label = slug.replace("-", " ").replace("_", " ").title()
            videos.append({
                "num":      i + 1,
                "title":    label,
                "dur":      "—",
                "dur_secs": 0,
                "url":      ep_url,
                "alt_urls": [],
                "page_url": url,
                "selected": True,
                "done":     False,
                "priority": "normal",
            })
        return videos, title
