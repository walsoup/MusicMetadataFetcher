# MusicMetadataFetcher 🎶

A Python tool to **automatically fix, enrich, and manage MP3 metadata** with help from Spotify, Genius, and Google Gemini AI. It cleans messy filenames, fetches proper tags, adds album art, grabs lyrics, and can even run AI-powered music analysis.

---

## ✨ Features

* **Spotify Integration** → Fetch accurate artist, title, album, genre, year, and track number.
* **Album Art** → Embed high‑quality cover art directly into your MP3s.
* **Lyrics Fetching** → Pulls lyrics from Genius.
* **AI Analysis (optional)** → Gemini AI estimates BPM, key, mood, danceability, popularity.
* **Smart Filename Cleanup** → Gemma AI can turn `[sketchywebsite] R U Mine song download.mp3` into `R U Mine`.
* **Metadata Management** → Options to strip, keep, or nuke metadata.
* **Cache System** → Speeds up repeated runs with local Spotify result caching.
* **Cleanup Utility** → Delete leftover `.cache` and log files when done.
* **Pretty Console Output** → Progress bars, tables, summaries via `rich`.

---

## ⚡ Installation

### Requirements

* **Python 3.11+** (needed for `typing.Self`, can be installed by `pip install python3.11`)
* Dependencies:

  ```bash
  pip install -r requirements.txt
  ```

### API Keys

Create a `.env` file in your project root:

```env
SPOTIPY_CLIENT_ID=your_spotify_client_id
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
GENIUS_API_KEY=your_genius_token
GEMINI_API_KEY=your_gemini_token   # optional
```

Guides:

* [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
* [Genius API](https://genius.com/developers)
* [Google AI Studio](https://aistudio.google.com/) (for Gemini/Gemma)

---

## 🚀 Usage

Run the script with:

```bash
python simplemetadatafetcher.py [options]
```

If no path is given, a GUI folder picker will open.

### Common Flags

| Flag              | Long Form         | Description                             |
| ----------------- | ----------------- | --------------------------------------- |
| `-p PATH`         | `--path PATH`     | Music folder path (skip GUI)            |
| `-e FILE`         | `--env-file FILE` | Use custom `.env` file                  |
| `-i`              | `--force-art`     | Replace existing album art              |
| `--no-art`        |                   | Disable album art fetching              |
| `-g`              | `--gem`           | Enable Gemini AI analysis               |
| `-nl`             | `--no-lyrics`     | Disable lyrics fetching                 |
| `--keep-comments` |                   | Keep comment tags                       |
| `--no-cache`      |                   | Disable Spotify cache                   |
| `-c`              | `--cleanup`       | Delete temp files after run             |
| `-r`              | `--rm-metadata`   | Remove all metadata except artist/title |
| `-n`              | `--nuke`          | Remove ALL metadata                     |
| `-s`              | `--skip-metadata` | Skip metadata fetch, only add art       |
| `-q`              | `--quiet`         | Minimal output                          |
| `-v`              | `--verbose`       | Extra debug info                        |

### Examples

* Process MP3s with AI + lyrics:

  ```bash
  python simplemetadatafetcher.py -p ./music -g
  ```
* Only add missing album art:

  ```bash
  python simplemetadatafetcher.py -p ./music -s
  ```
* Force replace all album art:

  ```bash
  python simplemetadatafetcher.py -p ./music -i
  ```
* Remove all metadata but keep artist/title:

  ```bash
  python simplemetadatafetcher.py -p ./music -r
  ```
* Nuclear option (wipe ALL metadata):

  ```bash
  python simplemetadatafetcher.py -p ./music -n
  ```

---

## 🔧 How It Works

1. **Reads Existing Tags** (if present)
2. **Parses Filenames** (`Artist - Title.mp3` style)
3. **AI Cleanup** (Gemma, optional)
4. **Fetches Metadata** from Spotify
5. **Enhances Content** → Lyrics, album art, AI analysis
6. **Writes Tags** using ID3v2.4 via `mutagen`

**Saved Fields:**

* Artist, Title, Album, Album Artist, Genre, Year, Track Number
* Album Art, Lyrics
* (optional via Gemini): BPM, Key, Mood, Danceability, Popularity

---

## 🧹 Temporary Files

* `.cache` → Spotify token cache
* `spotify_cache.json` → Cached search results
* `processed_log.json` → Already processed tracks

Remove them automatically with `--cleanup`.

---

## ⚠️ Notes

* Works only on `.mp3` files (will try to add support to other music files later
* Internet required for APIs.
* Gemini/Gemma are **optional** but "can" enhance results (sorry i just added them because being good with ai looks good on a resume.)
* Some obscure tracks may fail if not found on Spotify.

---

## 🤝 Contributing

Pull requests are welcome! For big changes, open an issue first.

---

## 📜 License

MIT License – free to use, modify, and distribute.
