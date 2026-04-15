# YouTube / TikTok / Anime Downloader

Téléchargeur de vidéos avec interface graphique — supporte YouTube, TikTok, les playlists, et les sites d'animés français (voiranime, animes-sama, neko-sama…).

---

## Prérequis

### 1. Python 3.10 ou plus récent

Télécharger sur [python.org](https://www.python.org/downloads/).  
Cocher **"Add Python to PATH"** pendant l'installation.

Vérifier :
```
python --version
```

### 2. yt-dlp

L'application l'installe automatiquement au premier lancement.  
Pour l'installer manuellement :
```
pip install yt-dlp
```

### 3. FFmpeg (obligatoire pour le format MP4)

Sans FFmpeg, la vidéo et l'audio sont téléchargés en fichiers séparés.

**Installation recommandée (Windows) :**
```
winget install --id Gyan.FFmpeg -e
```

Ou télécharger sur [ffmpeg.org](https://ffmpeg.org/download.html) et placer `ffmpeg.exe` dans `C:\ffmpeg\bin\`.

L'application détecte FFmpeg automatiquement dans les emplacements standards. Si ce n'est pas le cas, cliquer sur le badge **"⚠ FFmpeg manquant"** en haut à droite pour le localiser manuellement.

---

## Lancement

```
python youtube_downloader_v2.py
```

---

## Structure du projet

```
YouTube-Downloader/
│
├── youtube_downloader_v2.py   Interface graphique (tkinter) — point d'entrée
│
└── core/
    ├── constants.py           Couleurs, chemins, bitrates, domaines connus
    ├── utils.py               Fonctions pures (durée, taille, FFmpeg)
    ├── history.py             Historique des téléchargements (JSON)
    ├── session.py             Sauvegarde/restauration de session (JSON)
    ├── scrapers.py            Scraping animés + résolveur Vidmoly JWT
    └── downloader.py          Moteur yt-dlp (téléchargement, priorité, pause)
```

Deux fichiers sont créés dans le dossier utilisateur (`C:\Users\<vous>\`) :

| Fichier | Contenu |
|---|---|
| `.ytdl_session.json` | Session en cours (reprise après extinction) |
| `.ytdl_history.json` | Historique des 500 derniers téléchargements |

---

## Guide d'utilisation

### Télécharger une vidéo ou une playlist

1. Coller l'URL YouTube, TikTok ou animé dans la barre en haut
2. Cliquer **Analyser** (ou appuyer sur Entrée)
3. Choisir le format dans la section FORMAT
4. Choisir le dossier de destination
5. Cocher / décocher les vidéos dans la liste
6. Cliquer **⬇ Télécharger la sélection**

### Formats disponibles

| Format | Qualité | FFmpeg requis |
|---|---|---|
| MP4 Meilleur | Meilleure résolution disponible | Oui |
| MP4 1080p | Maximum 1080p | Oui |
| MP4 720p | Maximum 720p | Oui |
| MP3 | Audio uniquement, 192 kbps | Oui |
| M4A | Audio uniquement (AAC) | Non |

### Options

| Option | Description |
|---|---|
| Sous-titres FR/EN | Télécharge et intègre les sous-titres |
| Numéroter les fichiers | Préfixe chaque fichier avec `001 -`, `002 -`… |
| Miniature intégrée | Intègre la vignette dans le fichier MP4/MP3 |
| Sous-dossier playlist | Crée un dossier au nom de la playlist |
| Cookies | Utilise les cookies d'un navigateur (contenu privé / âge) |
| Limite vitesse | En kB/s — `0` = illimité |
| Simultanés | Nombre de vidéos téléchargées en même temps (1–5) |
| Retry auto | Tentatives automatiques en cas d'échec |
| À la fin | Action après téléchargement (ouvrir dossier, veille, extinction…) |

---

## Pause, reprise et gestion des interruptions

### Bouton Pause / Reprendre

Le bouton **⏸ Pause** s'active pendant un téléchargement.

- **Pause** : interrompt le(s) téléchargement(s) en cours immédiatement. Le fichier `.part` est conservé sur disque.
- **▶ Reprendre** : redémarre depuis l'octet exact où le téléchargement s'était arrêté — aucun octet n'est re-téléchargé.

### Reprise après extinction de la machine

La session est sauvegardée automatiquement :
- Au démarrage de chaque téléchargement
- Après chaque vidéo terminée
- Quand la pause est activée
- Quand la fenêtre est fermée pendant un téléchargement

Au prochain lancement, une fenêtre demande si vous souhaitez reprendre. Elle indique :
- La date de la dernière sauvegarde ("il y a 3 jours")
- Le nombre de vidéos terminées / restantes
- Le dossier et le format utilisés

Les fichiers `.part` laissés sur disque sont automatiquement repris par yt-dlp — la reprise est à l'octet près, même après une semaine.

### Téléchargement par segments (style IDM)

Le moteur découpe chaque téléchargement en requêtes HTTP de **1 Mo**. Si la connexion coupe en plein milieu d'un segment, seuls les octets dans le buffer réseau sont perdus (quelques Ko). Les segments précédents sont déjà écrits sur disque.

Pour les flux HLS/DASH (YouTube 1080p+, animés), **4 fragments sont téléchargés en parallèle** dans le même fichier — similaire aux connexions multiples d'IDM.

---

## Priorité des téléchargements (style uTorrent)

Pendant un téléchargement avec plusieurs vidéos en file d'attente, faire un **clic droit** sur une vidéo pour changer sa priorité :

| Priorité | Icône | Comportement |
|---|---|---|
| Haute | ⬆ (orange) | Téléchargée en premier dès qu'un slot se libère |
| Normale | ☑ (blanc) | Comportement par défaut |
| Basse | ⬇ (bleu-gris) | Téléchargée après toutes les vidéos normales |

La priorité est prise en compte **en temps réel** : si vous changez la priorité d'une vidéo qui attend, elle sera choisie dès que le prochain slot se libère, sans redémarrer.

---

## Surveillance du presse-papiers

L'application surveille le presse-papiers en permanence. Dès qu'une URL YouTube, TikTok ou animé est copiée, elle propose de l'analyser automatiquement.

Le badge **📋 Clip: ON / OFF** en haut à droite permet d'activer ou désactiver cette surveillance.

---

## Historique

Le bouton **📋 Historique** affiche les 500 derniers téléchargements. Depuis l'historique, il est possible de :
- Re-télécharger une vidéo en double-cliquant
- Ouvrir le dossier de destination
- Ouvrir l'URL dans le navigateur
- Supprimer une entrée de l'historique
- Rechercher par titre ou dossier

---

## Sites animés supportés

Le scraping est intégré pour les sites suivants :

| Site | Méthode |
|---|---|
| animes-sama.fr / anime-sama.fr | Tableaux JavaScript (var x = [...]) |
| voiranime.com / voiranime.me | Liens d'épisodes + iframes |
| neko-sama.fr | Liens d'épisodes |
| vostfree.tv / vostfree.com | Liens d'épisodes |
| mavanimes.co / mavanimes.org | Liens d'épisodes |
| franime.fr | Liens d'épisodes |
| animeko.co | Liens d'épisodes |
| jetanime.co / jetanimes.com | Liens d'épisodes |

**Utilisation :** coller l'URL de la **page de la saison** (ex: `.../saison-1/vostfr`), pas de la page principale de la série.

Les lecteurs embarqués supportés : Sibnet, Vidmoly (résolution JWT automatique), SendVid, StreamTape, DoodStream, Filemoon, OK.ru, Dailymotion.

---

## Ajouter des fonctionnalités

### Architecture

Le projet suit les principes SOLID. Chaque fichier a une responsabilité unique :

```
youtube_downloader_v2.py   → UI uniquement (tkinter), ne contient aucune logique de download
core/downloader.py         → Logique de téléchargement (yt-dlp), priorité, pause
core/scrapers.py           → Extraction d'URLs depuis des pages web
core/session.py            → Persistance de l'état entre les sessions
core/history.py            → Historique
core/constants.py          → Toutes les constantes (couleurs, domaines…)
core/utils.py              → Fonctions pures sans dépendances
```

### Ajouter un nouveau site animé

1. Ouvrir `core/constants.py`
2. Ajouter le domaine dans `ANIME_DOMAINS` :
   ```python
   ANIME_DOMAINS = [
       ...
       "nouveau-site.fr",
   ]
   ```
3. L'application essaiera automatiquement d'extraire les iframes et data-src depuis la page. Si la structure est inhabituelle, implémenter une méthode dédiée dans `core/scrapers.py` (s'inspirer de `_method_js_arrays` ou `_method_subpage_links`).

### Ajouter un hôte vidéo direct

Dans `core/constants.py`, ajouter le domaine dans `VIDEO_HOSTS` :
```python
VIDEO_HOSTS = [
    ...
    "nouveau-cdn.com",
]
```
Les URLs de ces domaines sont envoyées directement à yt-dlp sans post-traitement.

Pour les CDN qui exigent un Referer spécifique, le moteur l'injecte automatiquement depuis `v["page_url"]`.

### Ajouter un nouveau format

Dans `core/downloader.py`, méthode `_apply_format` :
```python
elif fmt == "mon_format":
    opts["format"] = "bestaudio/best"
    opts["postprocessors"] = [...]
```

Dans `youtube_downloader_v2.py`, méthode `_build_options_row`, ajouter le RadioButton :
```python
for label, val in [..., ("Mon Format", "mon_format")]:
    ...
```

### Modifier les couleurs

Toutes les couleurs sont dans `core/constants.py` :
```python
BG      = "#0d1117"   # Fond principal
SURF    = "#161b22"   # Surface (barre de titre, journaux)
CARD    = "#21262d"   # Cartes, boutons
ACCENT  = "#2f81f7"   # Bleu principal (boutons actifs)
SUCCESS = "#3fb950"   # Vert (vidéos terminées)
WARN    = "#d29922"   # Orange (avertissements)
DANGER  = "#f85149"   # Rouge (erreurs)
```

### Modifier le comportement du moteur

`DownloadEngine` dans `core/downloader.py` accepte des callbacks injectés :

```python
engine = DownloadEngine(
    log_fn       = ...,   # callable(msg, tag) — journal
    hook_fn      = ...,   # callable(d)        — progression yt-dlp
    pp_hook_fn   = ...,   # callable(d)        — post-processeur yt-dlp
    settings     = ...,   # objet AppSettings
    cancel_fn    = ...,   # callable() -> bool
    pause_fn     = ...,   # callable() -> bool
    per_dl_bytes = ...,   # dict partagé pour le suivi d'octets
    per_dl_time  = ...,   # dict partagé pour le suivi de temps
)
```

Le moteur ne dépend pas de tkinter — il peut être réutilisé dans un contexte CLI ou autre interface.

---

## Dépendances

| Package | Rôle | Installation |
|---|---|---|
| `yt-dlp` | Téléchargement vidéo | `pip install yt-dlp` |
| `tkinter` | Interface graphique | Inclus dans Python standard |
| `ffmpeg` | Fusion vidéo+audio, MP3 | Via winget ou ffmpeg.org |

Aucune autre dépendance externe n'est requise.

---

## Fichiers générés automatiquement

| Fichier | Emplacement | Supprimable |
|---|---|---|
| `.ytdl_session.json` | `C:\Users\<vous>\` | Oui — supprime la session en cours |
| `.ytdl_history.json` | `C:\Users\<vous>\` | Oui — vide l'historique |
| `*.part` | Dossier de destination | Oui — mais yt-dlp ne pourra plus reprendre |

---

## Problèmes courants

**"FFmpeg manquant"** : installer FFmpeg via `winget install --id Gyan.FFmpeg -e` ou cliquer sur le badge orange.

**"Unsupported URL"** sur un site animé : utiliser l'URL de la page de la saison, pas de la série. Exemple : `https://anime-sama.fr/catalogue/naruto/saison1/vostfr/` et non `https://anime-sama.fr/catalogue/naruto/`.

**Vidéos à 0 Ko** : l'hôte vidéo bloque le téléchargement direct. Essayer avec les cookies d'un navigateur (menu déroulant "Cookies").

**Le téléchargement reprend depuis le début** : vérifier que le fichier `.part` est toujours dans le dossier de destination et que le dossier n'a pas changé entre les sessions.
