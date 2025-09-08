import os
import argparse
import json
import time
from pathlib import Path
import requests
from io import BytesIO
from mutagen.mp3 import MP3
from mutagen.id3 import ID3NoHeaderError

# --- THE PARTY (LIBRARIES) ---
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from mutagen.id3 import ID3, TPE1, TIT2, TALB, TPE2, TCON, TDRC, TRCK, USLT, TBPM, TKEY, TXXX, APIC, COMM, ID3NoHeaderError
from tinydb import TinyDB, Query
from rich.console import Console
from rich.progress import Progress, TaskID, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
import google.generativeai as genai
import lyricsgenius

# Try to import python-dotenv, but don't die if it's not installed
try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False

# --- GLOBAL CONSOLE (Because passing it around is for masochists) ---
console = Console()

# --- SPOTIFY CACHE (Because why waste API calls) ---
SPOTIFY_CACHE_FILE = 'spotify_cache.json'
spotify_cache = {}
spotify_artist_genre_cache = {}
SPOTIFY_ARTIST_GENRE_CACHE_FILE = 'spotify_artist_genres.json'
lastfm_track_genre_cache = {}
LASTFM_TRACK_GENRE_CACHE_FILE = 'lastfm_track_genres.json'

def load_artist_genre_cache():
    """Load persistent artist->genres cache from disk."""
    global spotify_artist_genre_cache
    try:
        if os.path.exists(SPOTIFY_ARTIST_GENRE_CACHE_FILE):
            with open(SPOTIFY_ARTIST_GENRE_CACHE_FILE, 'r') as f:
                spotify_artist_genre_cache = json.load(f)
    except Exception as e:
        console.print(f"[yellow]⚠️  Failed to load artist genre cache: {e}. Starting fresh.[/yellow]")
        spotify_artist_genre_cache = {}

def save_artist_genre_cache():
    """Save persistent artist->genres cache to disk."""
    try:
        with open(SPOTIFY_ARTIST_GENRE_CACHE_FILE, 'w') as f:
            json.dump(spotify_artist_genre_cache, f)
    except Exception as e:
        console.print(f"[yellow]⚠️  Failed to save artist genre cache: {e}[/yellow]")

def load_spotify_cache():
    """Load previously cached Spotify search results"""
    global spotify_cache
    try:
        if os.path.exists(SPOTIFY_CACHE_FILE):
            with open(SPOTIFY_CACHE_FILE, 'r') as f:
                spotify_cache = json.load(f)
    except Exception as e:
        console.print(f"[yellow]⚠️  Failed to load Spotify cache: {e}. Starting fresh.[/yellow]")
        spotify_cache = {}

def save_spotify_cache():
    """Save Spotify search results to cache"""
    try:
        with open(SPOTIFY_CACHE_FILE, 'w') as f:
            json.dump(spotify_cache, f)
    except Exception as e:
        console.print(f"[yellow]⚠️  Failed to save Spotify cache: {e}[/yellow]")

def load_lastfm_genre_cache():
    """Load persistent Last.fm track-genre cache from disk."""
    global lastfm_track_genre_cache
    try:
        if os.path.exists(LASTFM_TRACK_GENRE_CACHE_FILE):
            with open(LASTFM_TRACK_GENRE_CACHE_FILE, 'r') as f:
                lastfm_track_genre_cache = json.load(f)
    except Exception as e:
        console.print(f"[yellow]⚠️  Failed to load Last.fm genre cache: {e}. Starting fresh.[/yellow]")
        lastfm_track_genre_cache = {}

def save_lastfm_genre_cache():
    """Save persistent Last.fm track-genre cache to disk."""
    try:
        with open(LASTFM_TRACK_GENRE_CACHE_FILE, 'w') as f:
            json.dump(lastfm_track_genre_cache, f)
    except Exception as e:
        console.print(f"[yellow]⚠️  Failed to save Last.fm genre cache: {e}[/yellow]")

# --- THE DOTENV DETECTIVE (Sherlock Holmes but for API keys) ---
def load_environment_variables(env_file_path=None):
    """
    This function is like a detective looking for clues (API keys) in all the usual places.
    First it checks if you specified a custom .env file, then it looks for one in the current directory,
    then it falls back to whatever's already in your environment.
    """
    if DOTENV_AVAILABLE:
        if env_file_path:
            # You specifically told us where to look
            if Path(env_file_path).exists():
                load_dotenv(env_file_path)
                console.print(f"🔍 Loaded environment from: [cyan]{env_file_path}[/cyan]")
            else:
                console.print(f"[yellow]⚠️  Specified .env file not found: {env_file_path}[/yellow]")
        else:
            # Let's check if there's a .env file in the current directory
            if Path(".env").exists():
                load_dotenv()
                console.print("🔍 Found and loaded [cyan].env[/cyan] file")
            # If no .env file, we just use whatever's already in the environment
    else:
        if env_file_path:
            console.print("[yellow]⚠️  python-dotenv not installed, ignoring .env file[/yellow]")

# --- API KEY CHECK (The Bouncer, but fancier) ---
def check_api_keys(use_gemini, quiet=False):
    """
    The bouncer at Club API. No keys, no entry. But now simplified!
    """
    required_keys = ["SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "GENIUS_API_KEY"]
    optional_keys = []
    
    # Gemini is optional for analysis
    if use_gemini:
        optional_keys.append("GEMINI_API_KEY")
    # Last.fm is optional and used as a genre fallback
    optional_keys.append("LASTFM_API_KEY")
    
    missing_required = []
    missing_optional = []
    
    # Check required keys
    for key in required_keys:
        if not os.getenv(key):
            missing_required.append(key)
    
    # Check optional keys
    for key in optional_keys:
        if not os.getenv(key):
            missing_optional.append(key)
    
    if missing_required:
        console.print(Panel(
            f"[bold red]💀 Missing required API keys:[/bold red]\n" + 
            "\n".join(f"• {key}" for key in missing_required),
            title="[red]Authentication Error[/red]",
            title_align="left"
        ))
        exit(1)
    
    if missing_optional and not quiet:
        console.print(f"[yellow]⚠️  Missing optional keys: {', '.join(missing_optional)}[/yellow]")
    
    if not quiet:
        console.print("[green]✅ All required API keys found[/green]")

# --- THE DIGITAL JANITOR (New and improved filename cleaner!) ---
def clean_filename_with_gemma(filename):
    """
    Ask Google's free Gemma model to clean up garbage filenames.
    This is like having a digital janitor who speaks AI and works for free.
    
    Input: "track_001_FINAL_copy_bohemain_rapsody_v2.mp3"
    Output: "bohemian rhapsody" (hopefully)
    
    Returns: cleaned string or None if Gemma has a brain fart
    """
    # Remove the .mp3 extension first
    clean_name = filename.replace('.mp3', '')
    
    # Simple prompt because Gemma is like a smart but simple friend
    prompt = f"""Clean up this music filename for a search query. Remove numbers, version info, and fix typos. Just return the cleaned title, nothing else.

Filename: "{clean_name}"

Cleaned title:"""
    
    try:
        # Using the free Gemma model because Google is feeling generous
        model = genai.GenerativeModel("gemma-3-27b-it")
        response = model.generate_content(prompt)
        
        # Get the response and clean it up
        cleaned = response.text.strip()
        
        # Basic sanity check - if it's too long or looks weird, skip it
        if len(cleaned) > 100 or not cleaned:
            return None
            
        return cleaned
        
    except Exception as e:
        console.print(f"    [yellow]→ 🧹 Filename cleaning failed: {e}[/yellow]")
        return None

# --- COMMENT NUKER (For when comments are just digital trash) ---
def strip_comments_from_audio(audio):
    """
    Deletes all comment tags because let's be real, they're usually garbage.
    Comments are like that one friend who won't stop talking - sometimes you just need silence.
    """
    # ID3v2 comments can have multiple instances with different descriptions
    # We need to find and delete all of them
    comment_keys = [key for key in audio.keys() if key.startswith('COMM')]
    for key in comment_keys:
        del audio[key]

# --- CLEANUP CREW (Marie Kondo but for cache files) ---
def cleanup_temporary_files(working_directory, quiet=False):
    """
    Deletes the digital breadcrumbs our script leaves behind.
    Because leaving random files in the music folder is like leaving dirty dishes in the sink.
    """
    files_to_delete = [
        Path(working_directory) / "processed_log.json",  # Our quest log
        Path(working_directory) / ".cache",              # Whatever random API garbage
        Path(".cache"),                                  # Sometimes it's in the current dir
        Path("processed_log.json"),                      # Sometimes our log is here too
        Path(SPOTIFY_CACHE_FILE)                         # Our Spotify search cache
    ]
    
    deleted_count = 0
    for file_path in files_to_delete:
        if file_path.exists():
            try:
                file_path.unlink()  # unlink() is just a fancy way to say "delete this file"
                deleted_count += 1
                if not quiet:
                    console.print(f"🗑️  Deleted: [dim]{file_path}[/dim]")
            except Exception as e:
                if not quiet:
                    console.print(f"[yellow]⚠️  Couldn't delete {file_path}: {e}[/yellow]")
    
    if deleted_count > 0 and not quiet:
        console.print(f"[green]✨ Cleaned up {deleted_count} temporary files[/green]")

# --- HELPER FUNCTIONS (The Spellbook 2.0) ---
def get_gemini_analysis(artist, title):
    """Summons the AI wizard to analyze the song. Now with retry logic!"""
    prompt = f"""
You are a music analysis expert. For the song "{artist} - {title}", provide the following details.
Return ONLY a valid JSON object. No other text, no markdown.

{{
  "bpm": <integer>,
  "key": "<e.g., C#m>",
  "mood": "<e.g., Energetic, Hopeful, Melancholic>",
  "danceability": <integer from 0-10>,
  "popularity": <integer from 0-10>
}}
"""
    
    for attempt in range(2):  # Try twice, because APIs are moody
        try:
            model = genai.GenerativeModel("gemma-3-27b-it")
            response = model.generate_content(prompt)
            cleaned_response = response.text.strip().replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned_response)
        except Exception as e:
            if attempt == 0:
                time.sleep(1)  # Wait a sec before retry
                continue
            else:
                console.print(f"    [red]→ 💀 Gemini API failed after 2 attempts: {e}[/red]")
                return None

def get_lyrics(genius_api, artist, title):
    """Asks the bard to sing us a song. Now with retry logic!"""
    for attempt in range(2):
        try:
            time.sleep(1)  # Be nice to the API
            song = genius_api.search_song(title, artist)
            if song and song.lyrics:
                lyrics = song.lyrics.split("Lyrics")[-1].strip()
                if "you might also like" in lyrics.lower():
                     lyrics = lyrics[:lyrics.lower().rfind("you might also like")]
                lyrics = '\n'.join(line for line in lyrics.split('\n') if not line.strip().isnumeric())
                return lyrics.strip()
            return None
        except Exception as e:
            if attempt == 0:
                time.sleep(2)  # Wait longer for Genius, they're pickier
                continue
            else:
                console.print(f"    [red]→ 💀 Lyrics search failed after 2 attempts: {e}[/red]")
                return None

def get_album_art(sp, artist, title, album=None, verbose=False):
    """
    Downloads album art from Spotify by searching with a compact query.
    Returns image bytes. Used when we don't already have track data.
    """
    try:
        # Build a compact, safe query under the 250-char Spotify limit.
        # Use primary artist only and drop album to keep it short.
        primary_artist = (artist.split(",")[0] if "," in artist else artist).strip()
        title_clean = title.replace('"', '').strip()
        # Hard cap just in case of extremely long classical titles
        if len(title_clean) > 120:
            title_clean = title_clean[:120]
        query = f"track:\"{title_clean}\" artist:\"{primary_artist}\""
            
        results = sp.search(q=query, type='track', limit=1)
        
        if not results['tracks']['items']:
            return None
            
        track = results['tracks']['items'][0]
        album_images = track['album']['images']
        
        if not album_images:
            return None
            
    # Get the biggest image (first one is usually the biggest)
        image_url = album_images[0]['url']
        
        # If verbose, show a download progress bar because we're fancy
        if verbose:
            console.print(f"    [green]→ Downloading album art for '{album or 'Unknown Album'}'[/green]")
            
            # Get file size first for progress bar
            response_head = requests.head(image_url, timeout=5)
            total_size = int(response_head.headers.get('content-length', 0))
            
            # Now download with progress bar
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
                transient=True  # Don't leave the progress bar in the console
            ) as progress:
                task = progress.add_task("Downloading", total=total_size)
                
                response = requests.get(image_url, timeout=10, stream=True)
                if response.status_code != 200:
                    return None
                    
                content = BytesIO()
                for chunk in response.iter_content(chunk_size=4096):
                    content.write(chunk)
                    progress.advance(task, len(chunk))
                
                return content.getvalue()
        else:
            # Quick and dirty download without progress bar
            response = requests.get(image_url, timeout=10)
            if response.status_code == 200:
                return response.content
            return None
        
    except Exception as e:
        console.print(f"    [red]→ 💀 Album art download failed: {e}[/red]")
        return None

def get_album_art_from_track(track_data, verbose=False):
    """Downloads album art using images already present in the Spotify track payload."""
    try:
        album_images = track_data.get('album', {}).get('images', [])
        if not album_images:
            return None
        image_url = album_images[0]['url']

        if verbose:
            console.print(f"    [green]→ Downloading album art from track data[/green]")
            response_head = requests.head(image_url, timeout=5)
            total_size = int(response_head.headers.get('content-length', 0))
            from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
                transient=True
            ) as progress:
                task = progress.add_task("Downloading", total=total_size)
                response = requests.get(image_url, timeout=10, stream=True)
                if response.status_code != 200:
                    return None
                content = BytesIO()
                for chunk in response.iter_content(chunk_size=4096):
                    content.write(chunk)
                    progress.advance(task, len(chunk))
                return content.getvalue()
        else:
            response = requests.get(image_url, timeout=10)
            if response.status_code == 200:
                return response.content
            return None
    except Exception as e:
        console.print(f"    [red]→ 💀 Album art download (from track) failed: {e}[/red]")
        return None

def search_spotify_with_cache(sp, query, type='track', limit=1):
    """
    Search Spotify but use cache if available.
    This is like checking your pantry before going grocery shopping.
    """
    # Generate a cache key based on the search parameters
    cache_key = f"{query}|{type}|{limit}"
    
    # Check if we have this search result cached
    if cache_key in spotify_cache:
        return spotify_cache[cache_key]
    
    # If not in cache, actually search Spotify
    try:
        results = sp.search(q=query, type=type, limit=limit)
        # Save to cache for next time
        spotify_cache[cache_key] = results
        return results
    except Exception as e:
        console.print(f"    [red]→ 💀 Spotify search failed: {e}[/red]")
        return None

def _normalize_genre_label(label: str) -> str:
    """Map granular Spotify genre labels to a clean, top-level genre."""
    l = label.lower()
    mapping = [
        (['hip hop', 'hip-hop', 'rap', 'trap'], 'Hip-Hop'),
        (['r&b', 'rnb', 'neo-soul'], 'R&B'),
        (['pop', 'synthpop', 'electropop', 'dance pop'], 'Pop'),
        (['metal'], 'Metal'),
        (['punk'], 'Punk'),
        (['indie'], 'Indie'),
        (['rock', 'alt rock', 'classic rock', 'hard rock'], 'Rock'),
        (['edm', 'electronic', 'house', 'techno', 'trance', 'dubstep', 'drum and bass', 'dnb'], 'Electronic'),
        (['classical', 'orchestra', 'symphony', 'opera', 'choir', 'choral', 'baroque', 'romantic'], 'Classical'),
        (['jazz', 'bebop', 'swing', 'fusion'], 'Jazz'),
        (['blues'], 'Blues'),
        (['country'], 'Country'),
        (['folk'], 'Folk'),
        (['latin', 'reggaeton', 'salsa', 'bachata', 'cumbia', 'tango'], 'Latin'),
        (['afrobeats', 'afrobeat', 'afro'], 'Afrobeats'),
        (['k-pop', 'kpop'], 'K-Pop'),
        (['j-pop', 'jpop'], 'J-Pop'),
        (['soundtrack', 'score'], 'Soundtrack'),
        (['lo-fi', 'lofi'], 'Lo-Fi'),
        (['ambient'], 'Ambient'),
        (['soul'], 'Soul'),
        (['gospel'], 'Gospel'),
        (['reggae', 'dancehall'], 'Reggae'),
        (['world'], 'World'),
    ]
    for keys, canonical in mapping:
        if any(k in l for k in keys):
            return canonical
    # Default: title case the original
    return label.title()

def get_genre_from_lastfm(artist: str, title: str) -> str | None:
    """Use Last.fm tags to infer a canonical genre for a given track.
    Tries track.getTopTags then artist.getTopTags. Returns canonical genre or None."""
    api_key = os.getenv("LASTFM_API_KEY")
    if not api_key or not artist or not title:
        return None
    try:
        cache_key = f"{artist.lower()}|{title.lower()}"
        if cache_key in lastfm_track_genre_cache:
            cached = lastfm_track_genre_cache[cache_key]
            return cached or None

        base_url = "https://ws.audioscrobbler.com/2.0/"
        # 1) track.getTopTags
        params = {
            'method': 'track.gettoptags',
            'artist': artist,
            'track': title,
            'api_key': api_key,
            'format': 'json'
        }
        r = requests.get(base_url, params=params, timeout=6)
        tags = []
        if r.status_code == 200:
            data = r.json()
            tag_list = (data.get('toptags') or {}).get('tag') or []
            for t in tag_list:
                name = (t.get('name') or '').strip()
                try:
                    count = int(t.get('count') or 0)
                except Exception:
                    count = 0
                if name and count > 0:
                    tags.append((name, count))
        # 2) fallback artist.getTopTags if needed
        if not tags:
            params = {
                'method': 'artist.gettoptags',
                'artist': artist,
                'api_key': api_key,
                'format': 'json'
            }
            r = requests.get(base_url, params=params, timeout=6)
            if r.status_code == 200:
                data = r.json()
                tag_list = (data.get('toptags') or {}).get('tag') or []
                for t in tag_list:
                    name = (t.get('name') or '').strip()
                    try:
                        count = int(t.get('count') or 0)
                    except Exception:
                        count = 0
                    if name and count > 0:
                        tags.append((name, count))

        if not tags:
            lastfm_track_genre_cache[cache_key] = ''
            return None

        # Normalize tags to canonical genres and pick the most common/highest count
        canon_counts = {}
        for name, count in tags:
            canon = _normalize_genre_label(name)
            canon_counts[canon] = canon_counts.get(canon, 0) + count
        top = sorted(canon_counts.items(), key=lambda x: (-x[1], x[0]))[0][0]
        lastfm_track_genre_cache[cache_key] = top
        return top
    except Exception:
        return None

def get_genre_from_spotify(sp, track_data) -> str:
    """Collect genres from all contributing artists and pick a clean primary genre.
    If Last.fm API key is available, prefer Last.fm. Otherwise use Spotify with fallbacks."""
    try:
        # If Last.fm is available, try it first
        if os.getenv("LASTFM_API_KEY"):
            primary_artist = track_data.get('artists', [{}])[0].get('name') if track_data.get('artists') else None
            lf = get_genre_from_lastfm(primary_artist or '', track_data.get('name') or '')
            if lf:
                return lf
        
        # Prefer track artists; include album artists as fallback
        artist_ids = [a['id'] for a in track_data.get('artists', []) if a.get('id')]
        album_artist_ids = [a['id'] for a in track_data.get('album', {}).get('artists', []) if a.get('id')]
        # Keep order but avoid duplicates
        seen = set()
        ordered_ids = []
        for aid in artist_ids + album_artist_ids:
            if aid and aid not in seen:
                ordered_ids.append(aid)
                seen.add(aid)

        # Limit to first set, but allow more due to batch endpoint
        ordered_ids = ordered_ids[:10]

        # Batch fetch artists not in cache
        to_fetch = [aid for aid in ordered_ids if aid not in spotify_artist_genre_cache]
        if to_fetch:
            try:
                # Spotify batch endpoint supports up to 50
                batch = sp.artists(to_fetch)
                for artist_obj in (batch.get('artists') or []):
                    if not artist_obj:
                        continue
                    aid = artist_obj.get('id')
                    if aid:
                        spotify_artist_genre_cache[aid] = artist_obj.get('genres', []) or []
            except Exception:
                # Fallback to per-artist fetch if batch fails
                for aid in to_fetch:
                    try:
                        info = sp.artist(aid)
                        spotify_artist_genre_cache[aid] = info.get('genres', []) if info else []
                    except Exception:
                        spotify_artist_genre_cache[aid] = []

        all_genres = []
        for aid in ordered_ids:
            all_genres.extend(spotify_artist_genre_cache.get(aid, []))

        if not all_genres:
            # If no Last.fm key was available, try Last.fm as final fallback
            if not os.getenv("LASTFM_API_KEY"):
                return 'Unknown'
            else:
                primary_artist = track_data.get('artists', [{}])[0].get('name') if track_data.get('artists') else None
                lf = get_genre_from_lastfm(primary_artist or '', track_data.get('name') or '')
                return lf or 'Unknown'

        # Normalize and pick the most common canonical label
        canon_counts = {}
        for g in all_genres:
            canon = _normalize_genre_label(g)
            canon_counts[canon] = canon_counts.get(canon, 0) + 1
        # Sort by count desc, then by name for stability
        top = sorted(canon_counts.items(), key=lambda x: (-x[1], x[0]))[0][0]
        return top
    except Exception:
        # Any Spotify exception -> try Last.fm if available
        if os.getenv("LASTFM_API_KEY"):
            primary_artist = track_data.get('artists', [{}])[0].get('name') if track_data.get('artists') else None
            lf = get_genre_from_lastfm(primary_artist or '', track_data.get('name') or '')
            return lf or 'Unknown'
        return 'Unknown'

def get_directory_from_user():
    """Shows a GUI dialog using PyQt6 to select a music folder."""
    try:
        import sys
        from PyQt6.QtWidgets import QApplication, QFileDialog

        app = QApplication.instance()
        created_app = False
        if app is None:
            app = QApplication(sys.argv)
            created_app = True

        options = QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        folder_path = QFileDialog.getExistingDirectory(
            None,
            "Select Your Music Folder",
            str(Path.home()),
            options,
        )

        if created_app:
            app.quit()

        if not folder_path:
            console.print("[red]No folder selected. Goodbye![/red]")
            exit()
        return Path(folder_path)
    except ImportError:
        console.print("[red]PyQt6 is not installed. Install it or provide the path with --path.[/red]")
        exit(1)

# --- THE NUCLEAR OPTION (Now with better messaging) ---
def strip_metadata_from_files(directory, mode, quiet=False):
    """Scorched earth protocol. Choose your destruction level."""
    mp3_files = list(directory.rglob("*.mp3"))

    if not mp3_files:
        console.print("[bold red]Found no MP3 files to obliterate.[/bold red]")
        return

    if mode == 'keep_basics':
        desc = "Surgical strike (keeping artist/title)..."
        if not quiet:
            console.print(f"[bold yellow]🔥 Executing surgical strike on {len(mp3_files)} files...[/bold yellow]")
    else:
        desc = "Nuclear option (destroying everything)..."
        if not quiet:
            console.print(f"[bold red]☢️  NUCLEAR OPTION on {len(mp3_files)} files...[/bold red]")

    # Stats tracking
    success_count = 0
    failed_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        disable=quiet
    ) as progress:
        
        task = progress.add_task(desc, total=len(mp3_files))
        
        for file_path in mp3_files:
            if not quiet:
                console.print(f"[dim]Nuking: {file_path.name}[/dim]")
            
            # Try up to 2 times (more retries for destructive operations is dangerous!)
            for attempt in range(2):    
                try:
                    audio = ID3(file_path)
                    
                    if mode == 'keep_basics':
                        # Save the survivors
                        artist = audio.get('TPE1')
                        title = audio.get('TIT2')
                        audio.delete()
                        # Resurrect the chosen ones
                        if artist: audio.add(artist)
                        if title: audio.add(title)
                    else:
                        audio.delete()  # No mercy

                    audio.save()
                    success_count += 1
                    break  # Success, exit retry loop
                    
                except ID3NoHeaderError:
                    success_count += 1  # Already empty, mission accomplished
                    break
                    
                except Exception as e:
                    if attempt == 1:  # This was our last attempt
                        if not quiet:
                            console.print(f"💀 Failed to nuke '[red]{file_path.name}[/red]': {e}")
                        failed_count += 1
                    else:
                        # Try once more
                        time.sleep(0.5)  # Brief pause before retry
                        continue
            
            progress.advance(task)
    
    if not quiet:
        # Show summary stats
        console.print(f"\n[bold]Operation Summary:[/bold]")
        console.print(f"✅ Successfully nuked: {success_count} files")
        if failed_count > 0:
            console.print(f"❌ Failed: {failed_count} files")
            
        console.print("\n[bold green]🎯 Destruction complete. The slate is clean.[/bold green]")

# --- THE SKIP METADATA MODE (For when you just want art) ---
def add_album_art_only(directory, quiet=False, verbose=False, fetch_lyrics=True):
    """Adds album art to files that already have basic metadata and (optionally) fetches lyrics."""
    # We still need Spotify for this
    check_api_keys(use_gemini=False, quiet=quiet)
    
    # Load cache
    load_spotify_cache()
    
    sp = spotipy.Spotify(client_credentials_manager=SpotifyClientCredentials(
        client_id=os.getenv("SPOTIPY_CLIENT_ID"), 
        client_secret=os.getenv("SPOTIPY_CLIENT_SECRET")
    ))
    
    mp3_files = list(directory.rglob("*.mp3"))

    # Setup Genius if lyrics are requested
    genius = None
    if fetch_lyrics:
        genius = lyricsgenius.Genius(os.getenv("GENIUS_API_KEY"), verbose=False, remove_section_headers=True, timeout=15)
    
    if not mp3_files:
        console.print("[bold red]Found no MP3 files.[/bold red]")
        return

    if not quiet:
        console.print(f"[cyan]🎨 Adding album art to {len(mp3_files)} files...[/cyan]")

    # Stats tracking
    success_count = 0
    already_had_art = 0
    no_metadata_count = 0
    lyrics_added = 0
    failed_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        disable=quiet
    ) as progress:
        
        task = progress.add_task("Adding album art...", total=len(mp3_files))
        
        for file_path in mp3_files:
            if not quiet and verbose:
                console.print(f"[dim]Processing: {file_path.name}[/dim]")
            
            # Try up to 2 times
            for attempt in range(2):
                try:
                    audio = ID3(file_path)
                    
                    # Check if it already has art
                    if any(key.startswith('APIC') for key in audio.keys()):
                        already_had_art += 1
                        break  # Skip this file
                    
                    # Try to get artist and title
                    artist_tag = audio.get('TPE1')
                    title_tag = audio.get('TIT2')
                    album_tag = audio.get('TALB')
                    
                    if not artist_tag or not title_tag:
                        no_metadata_count += 1
                        break  # Skip this file
                        
                    artist = artist_tag.text[0] if artist_tag.text else None
                    title = title_tag.text[0] if title_tag.text else None
                    album = album_tag.text[0] if album_tag and album_tag.text else None
                    
                    if not artist or not title:
                        no_metadata_count += 1
                        break  # Skip this file
                    
                    # Get the album art
                    art_data = get_album_art(sp, artist, title, album, verbose)
                    if art_data:
                        audio.add(APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,  # Cover (front)
                            desc='Cover',
                            data=art_data
                        ))
                        success_count += 1
                    else:
                        # If we got no art data and this was our last attempt
                        if attempt == 1:
                            failed_count += 1
                            break
                        else:
                            # Try once more
                            time.sleep(0.5)
                            continue
                    # Optionally fetch lyrics (if we have artist/title and no existing lyrics)
                    if fetch_lyrics and genius:
                        has_lyrics = any(key.startswith('USLT') for key in audio.keys())
                        if not has_lyrics:
                            lyr = get_lyrics(genius, artist, title)
                            if lyr:
                                audio['USLT::eng'] = USLT(encoding=3, lang='eng', desc='Lyrics', text=lyr)
                                lyrics_added += 1
                    # Save changes if any were made
                    audio.save()
                    break  # Success, exit retry loop
                
                except Exception as e:
                    if attempt == 1:  # This was our last attempt
                        if not quiet and verbose:
                            console.print(f"💀 Failed to add art to '[red]{file_path.name}[/red]': {e}")
                        failed_count += 1
                    else:
                        # Try once more
                        time.sleep(0.5)
                        continue
            
            progress.advance(task)
    
    # Save cache
    save_spotify_cache()
    
    if not quiet:
        # Show summary stats in a nice table
        table = Table(title="Album Art Mission Summary")
        table.add_column("Status", justify="left", style="bold")
        table.add_column("Count", justify="right")
        
        table.add_row("✅ Successfully added art", str(success_count))
        table.add_row("⏭️ Already had art", str(already_had_art))
        table.add_row("🔍 No metadata to search with", str(no_metadata_count))
        table.add_row("❌ Failed to add art", str(failed_count))
        if fetch_lyrics:
            table.add_row("📝 Lyrics added", str(lyrics_added))
        
        console.print(table)
        console.print("\n[bold green]🎨 Album art mission complete![/bold green]")

# --- THE MAIN QUEST (Now with smart Spotify fallback!) ---
def process_files(directory, use_gemini, fetch_lyrics, force_album_art, no_album_art, batch_size, keep_comments, quiet=False, verbose=False):
    """The main quest loop. Now with smart album art logic!"""
    
    check_api_keys(use_gemini, quiet)
    
    # Load cache
    load_spotify_cache()
    
    # Setup the gang
    sp = spotipy.Spotify(client_credentials_manager=SpotifyClientCredentials(
        client_id=os.getenv("SPOTIPY_CLIENT_ID"), 
        client_secret=os.getenv("SPOTIPY_CLIENT_SECRET")
    ))
    genius = lyricsgenius.Genius(os.getenv("GENIUS_API_KEY"), verbose=False, remove_section_headers=True, timeout=15)
    
    # Setup Gemini only if we need it
    has_gemini_key = bool(os.getenv("GEMINI_API_KEY"))
    if use_gemini or has_gemini_key:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

    db = TinyDB('processed_log.json')
    Song = Query()
    
    mp3_files = list(directory.rglob("*.mp3"))
    
    # Filter out already processed files
    unprocessed_files = []
    for file_path in mp3_files:
        if not db.search(Song.path == str(file_path)):
            unprocessed_files.append(file_path)

    if not unprocessed_files:
        if not quiet:
            console.print("[bold green]All files already processed! ✨[/bold green]")
        return

    if not quiet:
        console.print(f"[cyan]🚀 Processing {len(unprocessed_files)} new files...[/cyan]")
        if has_gemini_key:
            console.print("[green]✨ Gemma filename cleaning available![/green]")

    # Stats tracking
    success_count = 0
    failed_count = 0
    skipped_count = 0
    art_added_count = 0
    
    # Failed files list for summary
    failed_files = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        disable=quiet
    ) as progress:
        
        # Main progress bar
        main_task = progress.add_task("Processing files...", total=len(unprocessed_files))
        
        for file_path in unprocessed_files:
            # Show what we're working on
            if verbose:
                console.print(f"[dim]Now processing: {file_path.name}[/dim]")
            
            # Try up to 2 times
            for attempt in range(2):
                try:
                    artist = None
                    title = None
                    
                    # Step 1: Try to read existing tags first
                    try:
                        audio = ID3(file_path)
                        artist_tag = audio.get('TPE1')
                        title_tag = audio.get('TIT2')
                        
                        if artist_tag and artist_tag.text:
                            artist = artist_tag.text[0]
                        if title_tag and title_tag.text:
                            title = title_tag.text[0]
                            
                    except (ID3NoHeaderError, KeyError):
                        pass  # No metadata found
                    
                    # Step 2: If no metadata, try filename parsing
                    if not artist or not title:
                        try:
                            # Try "Artist - Title.mp3" format
                            artist, title = file_path.stem.split(' - ', 1)
                            if verbose:
                                console.print(f"    [blue]→ Parsed from filename: '{artist} - {title}'[/blue]")
                        except ValueError:
                            # Step 3: Filename parsing failed, time for the fallback strategies
                            if verbose:
                                console.print(f"    [yellow]→ Can't parse filename, trying search fallback...[/yellow]")
                            
                            search_query = file_path.stem  # Start with raw filename
                            
                            # If we have Gemini, try to clean it up first
                            if has_gemini_key:
                                if verbose:
                                    console.print(f"    [magenta]🧹 Asking Gemma to clean up '{file_path.name}'...[/magenta]")
                                
                                cleaned = clean_filename_with_gemma(file_path.name)
                                if cleaned:
                                    search_query = cleaned
                                    if verbose:
                                        console.print(f"    [magenta]→ Cleaned filename: '{cleaned}'[/magenta]")
                                else:
                                    if verbose:
                                        console.print(f"    [yellow]→ Gemma couldn't clean it, using raw filename[/yellow]")
                            
                            # Search Spotify with whatever we have
                            if verbose:
                                console.print(f"    [cyan]🔍 Searching Spotify for: '{search_query}'[/cyan]")
                            
                            spotify_results = search_spotify_with_cache(sp, search_query, type='track', limit=1)
                            
                            if spotify_results and spotify_results['tracks']['items']:
                                # Found something! Use the first result
                                found_track = spotify_results['tracks']['items'][0]
                                artist = found_track['artists'][0]['name']
                                title = found_track['name']
                                if verbose:
                                    console.print(f"    [green]→ Found: '{artist} - {title}'[/green]")
                            else:
                                # Still nothing found, skip this file
                                if verbose:
                                    console.print(f"    [red]→ No results found on Spotify[/red]")
                                skipped_count += 1
                                progress.advance(main_task)
                                break  # Exit retry loop, but we're counting this as skipped, not failed

                    # Now we should have artist and title from SOMEWHERE
                    if not artist or not title:
                        if verbose:
                            console.print(f"[yellow]⚠️  Skipping '{file_path.name}' (couldn't determine artist/title)[/yellow]")
                        skipped_count += 1
                        progress.advance(main_task)
                        break  # Exit retry loop

                    # Search Spotify again with the clean artist/title to get full metadata
                    query = f"artist:{artist} track:{title}"
                    results = search_spotify_with_cache(sp, query, type='track', limit=1)
                    
                    if not results or not results['tracks']['items']:
                        if verbose:
                            console.print(f"[yellow]⚠️  '{artist} - {title}' not found on Spotify[/yellow]")
                        skipped_count += 1
                        progress.advance(main_task)
                        break  # Exit retry loop

                    track_data = results['tracks']['items'][0]

                    # Extract the loot
                    metadata = {
                        "artist": ", ".join(artist['name'] for artist in track_data['artists']),
                        "title": track_data['name'],
                        "album": track_data['album']['name'],
                        "album_artist": ", ".join(artist['name'] for artist in track_data['album']['artists']),
                        "track_number": f"{track_data['track_number']}/{track_data['album']['total_tracks']}",
                        "year": track_data['album']['release_date'][:4]
                    }

                    # Get genre from Spotify (aggregate across artists with normalization)
                    metadata["genre"] = get_genre_from_spotify(sp, track_data)

                    # Optional side quests
                    if use_gemini:
                        if verbose:
                            console.print(f"    [magenta]🔮 Analyzing '{metadata['title']}'...[/magenta]")
                        analysis = get_gemini_analysis(metadata['artist'], metadata['title'])
                        if analysis:
                            metadata.update(analysis)

                    if fetch_lyrics:
                        if verbose:
                            console.print(f"    [blue]📝 Searching lyrics for '{metadata['title']}'...[/blue]")
                        lyrics = get_lyrics(genius, metadata['artist'], metadata['title'])
                        if lyrics:
                            metadata['lyrics'] = lyrics

                    # Write all the tags
                    try:
                        audio_write = ID3(file_path) # Re-open for writing
                    except ID3NoHeaderError:
                        # Create a new ID3 tag if file doesn't have one
                        audio_write = ID3()
                    
                    # --- Smart Album Art Logic ---
                    # This is the brain of the operation.
                    # It checks if we should add art based on our rules.
                    has_art = any(key.startswith('APIC') for key in audio_write.keys())
                    should_add_art = not no_album_art and (force_album_art or not has_art)

                    if should_add_art:
                        if verbose:
                            console.print(f"    [green]🎨 Getting album art for '{metadata['title']}'...[/green]")
                        # Prefer existing track_data images to avoid long queries
                        art_data = get_album_art_from_track(track_data, verbose)
                        if not art_data:
                            # Fallback to compact search if album images weren't present
                            art_data = get_album_art(sp, metadata['artist'], metadata['title'], metadata['album'], verbose)
                        if art_data:
                            # If we're forcing it, delete old art first
                            if force_album_art and has_art:
                                apic_keys = [key for key in audio_write.keys() if key.startswith('APIC')]
                                for key in apic_keys:
                                    del audio_write[key]
                            
                            audio_write.add(APIC(
                                encoding=3,
                                mime='image/jpeg',
                                type=3,  # Cover (front)
                                desc='Cover',
                                data=art_data
                            ))
                            art_added_count += 1

                    audio_write['TPE1'] = TPE1(encoding=3, text=metadata['artist'])
                    audio_write['TIT2'] = TIT2(encoding=3, text=metadata['title'])
                    audio_write['TALB'] = TALB(encoding=3, text=metadata['album'])
                    audio_write['TPE2'] = TPE2(encoding=3, text=metadata['album_artist'])
                    audio_write['TCON'] = TCON(encoding=3, text=metadata['genre'])
                    audio_write['TDRC'] = TDRC(encoding=3, text=str(metadata['year']))
                    audio_write['TRCK'] = TRCK(encoding=3, text=metadata['track_number'])

                    # Optional tags
                    if 'bpm' in metadata: audio_write['TBPM'] = TBPM(encoding=3, text=str(metadata['bpm']))
                    if 'key' in metadata: audio_write['TKEY'] = TKEY(encoding=3, text=str(metadata['key']))
                    if 'lyrics' in metadata: audio_write['USLT::eng'] = USLT(encoding=3, lang='eng', desc='Lyrics', text=metadata['lyrics'])

                    # Custom tags
                    for key in ['mood', 'danceability', 'popularity']:
                        if key in metadata:
                            audio_write.add(TXXX(encoding=3, desc=key.capitalize(), text=str(metadata[key])))

                    # Comment management (the real MVP feature)
                    if not keep_comments:
                        strip_comments_from_audio(audio_write)
                        if verbose:
                            console.print(f"    [dim]🗑️  Stripped comment tags[/dim]")

                    audio_write.save(v2_version=4, padding=None)
                    db.insert({'path': str(file_path)})
                    success_count += 1
                    
                    if not quiet:
                        console.print(f"✅ [bold]{metadata['artist']}[/bold] - [italic]{metadata['title']}[/italic]")
                    
                    # Success! Break out of retry loop
                    break

                except Exception as e:
                    if attempt == 1:  # This was our last attempt
                        if not quiet:
                            console.print(f"💀 Failed to process '[red]{file_path.name}[/red]': {e}")
                        failed_count += 1
                        failed_files.append((file_path.name, str(e)))
                    else:
                        # Try once more
                        time.sleep(0.5)  # Small delay before retry
                        continue

            progress.advance(main_task)

    # Save cache
    save_spotify_cache()

    if not quiet:
        # Show summary stats in a nice table
        table = Table(title="Processing Summary")
        table.add_column("Status", justify="left", style="bold")
        table.add_column("Count", justify="right")
        
        table.add_row("✅ Successfully processed", str(success_count))
        table.add_row("🎨 Album art added", str(art_added_count))
        table.add_row("⏭️ Skipped (no metadata)", str(skipped_count))
        table.add_row("❌ Failed to process", str(failed_count))
        
        console.print(table)
        
        if failed_count > 0 and verbose:
            # Show failed files in detail
            failed_table = Table(title="Failed Files")
            failed_table.add_column("Filename", style="red")
            failed_table.add_column("Error")
            
            for name, error in failed_files[:10]:  # Show max 10 failures
                failed_table.add_row(name, error)
                
            if len(failed_files) > 10:
                failed_table.add_row(f"...and {len(failed_files) - 10} more", "")
                
            console.print(failed_table)

        console.print("\n[bold green]🎉 All done! Your library is now slightly less chaotic.[/bold green]")

# --- THE COMMAND CENTER (Argument parsing paradise) ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="🎵 Pimp your MP3s with Spotify data, AI analysis, and album art 🎵",
        formatter_class=argparse.RawTextHelpFormatter
    )

    # Path selection
    parser.add_argument(
        "-p", "--path",
        type=str,
        help="Specify music directory path (skips GUI folder picker)"
    )

    # Environment file
    parser.add_argument(
        "-e", "--env-file",
        type=str,
        help="Specify custom .env file path (default: look for .env in current dir)"
    )

    # --- ENHANCEMENT FLAGS ---
    # Group for album art controls
    art_group = parser.add_mutually_exclusive_group()
    art_group.add_argument(
        "-i", "--force-art",
        action="store_true",
        dest="force_album_art",
        help="Force replace existing album art. (Default: only add if missing)"
    )
    art_group.add_argument(
        "--no-art",
        action="store_true",
        dest="no_album_art",
        help="Disable all album art fetching."
    )
    
    parser.add_argument(
        "-g", "--gem",
        action="store_true",
        help="Enable Gemini AI analysis (BPM, mood, danceability, etc.)\nRequires GEMINI_API_KEY"
    )
    
    parser.add_argument(
        "-nl", "--no-lyrics",
        action="store_false",
        dest="fetch_lyrics",
        default=True,
        help="Disable lyrics fetching (why would you want this?)"
    )

    # Comment handling (opt-out, because comments are usually trash)
    parser.add_argument(
        "--keep-comments",
        action="store_true",
        help="Keep existing comment tags (default: delete them because they're usually garbage)"
    )

    # Cache management
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable caching of Spotify searches (slower but uses less disk space)"
    )

    # Cleanup flag
    parser.add_argument(
        "-c", "--cleanup",
        action="store_true",
        help="Delete temporary files (.cache, processed_log.json) after completion"
    )

    # Batch processing
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=10,
        help="Process files in batches when using Gemini (default: 10)"
    )

    # Destructive operations (mutually exclusive)
    destroy_group = parser.add_mutually_exclusive_group()
    destroy_group.add_argument(
        "-r", "--rm-metadata",
        action="store_true",
        help="Surgical strike: delete all metadata except artist/title"
    )
    destroy_group.add_argument(
        "-n", "--nuke",
        action="store_true",
        help="Nuclear option: delete ALL metadata (no survivors)"
    )
    destroy_group.add_argument(
        "-s", "--skip-metadata",
        action="store_true",
        help="Skip metadata fetching, only add album art to existing files"
    )

    # Output control
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Minimal output (just errors and warnings)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Extra detailed output for debugging"
    )

    args = parser.parse_args()

    # Load environment variables first
    load_environment_variables(args.env_file)

    # Disable caching if requested
    if args.no_cache:
        spotify_cache = {}  # Empty cache that won't be saved

    # Load persistent artist-genre cache
    load_artist_genre_cache()
    load_lastfm_genre_cache()

    # Get the directory
    if args.path:
        music_directory = Path(args.path)
        if not music_directory.exists():
            console.print(f"[red]💀 Directory doesn't exist: {args.path}[/red]")
            exit(1)
    else:
        music_directory = get_directory_from_user()

    # Route to the appropriate function
    if args.rm_metadata:
        strip_metadata_from_files(music_directory, mode='keep_basics', quiet=args.quiet)
    elif args.nuke:
        strip_metadata_from_files(music_directory, mode='all', quiet=args.quiet)
    elif args.skip_metadata:
        add_album_art_only(music_directory, quiet=args.quiet, verbose=args.verbose, fetch_lyrics=args.fetch_lyrics)
    else:
        # Note the new album art arguments being passed here
        process_files(
            directory=music_directory,
            use_gemini=args.gem,
            fetch_lyrics=args.fetch_lyrics,
            force_album_art=args.force_album_art,
            no_album_art=args.no_album_art,
            batch_size=args.batch_size if args.gem else None,
            keep_comments=args.keep_comments,
            quiet=args.quiet,
            verbose=args.verbose
        )

    # Cleanup crew (Marie Kondo mode)
    if args.cleanup:
        cleanup_temporary_files(music_directory, quiet=args.quiet)

    # Persist artist-genre cache
    save_artist_genre_cache()
    save_lastfm_genre_cache()
