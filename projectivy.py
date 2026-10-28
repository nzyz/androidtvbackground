"""Generate uncropped Projectivy wallpapers from artist photos and TMDB backdrops."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parent
USER_AGENT = "ProjectivyPersonalWallpapers/1.0"


def save_json(path: Path, value):
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def atomic_write(path: Path, data: bytes):
    """Publish a complete file without removing the previous successful version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
            name = f.name
            f.write(data)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def name_key(name: str) -> str:
    return unicodedata.normalize("NFKC", name).strip().casefold()


def slug(name: str) -> str:
    stem = re.sub(r"[^\w-]+", "-", name_key(name), flags=re.UNICODE).strip("-")
    return (stem or "artist")[:90]


def artist_filename(name: str) -> str:
    # The digest distinguishes A$AP Ferg / A AP Ferg, accents, and other slug collisions.
    digest = hashlib.sha256(name_key(name).encode()).hexdigest()[:8]
    return f"artist-{slug(name)}-{digest}.jpg"


def import_library(path: Path) -> dict:
    """Artist rows use Track name in this export, not its empty Artist name column."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"Track name", "Artist name", "Type"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("CSV needs Track name, Artist name, and Type columns.")
        rows = list(reader)
    artists = {}
    counts = Counter()
    favourites = Counter()
    seen_tracks = set()
    seen_favourites = set()
    for row in rows:
        artist = (row.get("Artist name") or "").strip()
        if name_key(row["Type"]) == "artist":
            name = row["Track name"].strip()
            if name:
                artists.setdefault(name_key(name), name)
        elif artist:
            identity = row.get("Apple - id") or (artist, row["Track name"], row.get("Album"))
            if identity not in seen_tracks:
                counts[name_key(artist)] += 1
                seen_tracks.add(identity)
            playlist = name_key(row.get("Playlist name") or "")
            if playlist in {"favourite songs", "favorite songs"} and identity not in seen_favourites:
                favourites[name_key(artist)] += 1
                seen_favourites.add(identity)
    if not artists:
        for row in rows:
            name = (row.get("Artist name") or "").strip()
            if name:
                artists.setdefault(name_key(name), name)
    if not artists:
        raise ValueError("No artists found in the CSV.")
    entries = [dict(name=name, library_tracks=counts[key], favourite_tracks=favourites[key])
               for key, name in artists.items()]
    entries.sort(key=lambda a: (-a["favourite_tracks"], -a["library_tracks"], name_key(a["name"])))
    return {"version": 1, "artist_count": len(entries), "artists": entries}


def render_photo(image: Image.Image, size=(3840, 2160), fill="blur", blur=48,
                 background_brightness=0.5) -> Image.Image:
    """Contain the entire sharp photo. Only the decorative blurred layer may crop."""
    if len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
        raise ValueError("Wallpaper width and height must be positive integers.")
    if size[0] * size[1] > 40_000_000:
        raise ValueError("Wallpaper size must be at most 40 megapixels.")
    if fill not in {"blur", "black"}:
        raise ValueError("fill must be blur or black.")
    if not 0 <= blur <= 200 or not 0 <= background_brightness <= 1:
        raise ValueError("blur must be 0–200; background_brightness must be 0–1.")
    image = ImageOps.exif_transpose(image).convert("RGBA")
    # Flatten transparency before resizing; a transparent PNG must not become black silhouettes.
    flattened = Image.new("RGBA", image.size, "black")
    flattened.alpha_composite(image)
    image = flattened.convert("RGB")
    foreground = ImageOps.contain(image, tuple(size), Image.Resampling.LANCZOS)
    if fill == "blur":
        # Work at a small size for a smooth fill without a costly full-resolution blur.
        small = (max(1, size[0] // 4), max(1, size[1] // 4))
        backdrop = ImageOps.fit(image, small, Image.Resampling.LANCZOS)
        backdrop = backdrop.filter(ImageFilter.GaussianBlur(blur / 4))
        backdrop = ImageEnhance.Brightness(backdrop).enhance(background_brightness)
        canvas = backdrop.resize(tuple(size), Image.Resampling.LANCZOS)
    else:
        canvas = Image.new("RGB", tuple(size), "black")
    canvas.paste(foreground, ((size[0] - foreground.width) // 2,
                            (size[1] - foreground.height) // 2))
    return canvas


class Client:
    def __init__(self, cache: Path, offline=False, refresh=False):
        self.cache = cache
        self.offline = offline
        self.refresh = refresh
        self.last_request = 0.0

    def get(self, url: str, headers=None) -> bytes:
        if urlsplit(url).scheme != "https":
            raise ValueError("Remote image and API URLs must use HTTPS.")
        cache = self.cache / hashlib.sha256(url.encode()).hexdigest()
        if cache.exists() and (self.offline or not self.refresh):
            return cache.read_bytes()
        if self.offline:
            raise OSError("Not cached; offline mode cannot download this item.")
        for attempt in range(3):
            # Shared free photo APIs need polite pacing, including across consecutive artists.
            delay = 2.1 - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            self.last_request = time.monotonic()
            req = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
            try:
                with urlopen(req, timeout=20) as response:
                    data = response.read(25_000_001)
                if len(data) > 25_000_000:
                    raise ValueError("Remote file exceeds the 25 MB limit.")
                atomic_write(cache, data)
                return data
            except HTTPError as exc:
                if exc.code == 429:
                    raise OSError("Provider rate limit reached; try again in a minute.") from None
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise OSError(f"Remote server returned HTTP {exc.code}.") from None
                time.sleep(min(8, 2 ** attempt))
            except URLError:
                raise OSError("Network request failed; check your connection or use a local photo.") from None
        raise OSError("Remote request failed.")

    def json(self, url: str, headers=None):
        return json.loads(self.get(url, headers))


def artist_photos(client: Client, name: str, music: dict, base: Path):
    override = music.get("photos", {}).get(name)
    if override:
        values = override if isinstance(override, list) else [override]
        return [dict(source=str(v), provider="custom", artist=name) for v in values]
    local = base / music.get("local_photos", "artist-photos")
    photos = sorted(p for p in local.glob(slug(name) + ".*")
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if photos:
        return [dict(source=str(p.resolve()), provider="local", artist=name) for p in photos]
    lookup = music.get("aliases", {}).get(name, name)
    key = os.getenv("AUDIODB_API_KEY") or music.get("audiodb_key", "123")
    url = f"https://www.theaudiodb.com/api/v1/json/{key}/search.php?" + urlencode({"s": lookup})
    results = client.json(url).get("artists") or []
    # Search may return a similarly named artist. Never silently select its first result.
    matches = [a for a in results if name_key(a.get("strArtist") or "") == name_key(lookup)]
    if len(matches) != 1:
        return []
    record = matches[0]
    sources = [record.get(k) for k in ("strArtistFanart", "strArtistFanart2", "strArtistFanart3")]
    if not any(sources):
        sources = [record.get("strArtistThumb")]
    return [dict(source=src, provider="TheAudioDB", artist=record["strArtist"],
                 artist_id=record.get("idArtist"),
                 credit_url=f"https://www.theaudiodb.com/artist/{record['idArtist']}")
            for src in dict.fromkeys(sources) if src]


def movie_photos(client: Client, media_type: str, config: dict):
    token = os.getenv("TMDB_BEARER_TOKEN", "").strip()
    if not token:
        raise ValueError("Set TMDB_BEARER_TOKEN to enable movie/show downloads.")
    headers = {"Authorization": "Bearer " + token, "accept": "application/json"}
    language = config.get("language", "en-US")
    data = client.json("https://api.themoviedb.org/3/trending/" + media_type +
                       "/week?" + urlencode({"language": language}), headers)
    items = []
    for entry in data.get("results", []):
        if entry.get("adult") or not entry.get("backdrop_path"):
            continue
        title = entry.get("title") or entry.get("name") or str(entry["id"])
        items.append(dict(source="https://image.tmdb.org/t/p/original" + entry["backdrop_path"],
                          provider="TMDB", title=title, media_type=media_type, id=entry["id"],
                          credit_url=f"https://www.themoviedb.org/{media_type}/{entry['id']}"))
    return items[:max(0, int(config.get("limit", 10)))]


def write_wallpaper(client: Client, photo: dict, output: Path, layout: dict, base: Path):
    source = photo["source"]
    if urlsplit(source).scheme in {"https", "http"}:
        raw = client.get(source)
    else:
        raw = (base / source).read_bytes()
    with Image.open(io.BytesIO(raw)) as image:
        rendered = render_photo(image, **layout)
    buffer = io.BytesIO()
    rendered.save(buffer, format="JPEG", quality=95, subsampling=0)
    atomic_write(output, buffer.getvalue())


def generate(config: dict, base: Path, offline=False, refresh=False, limit=None):
    layout = config.get("layout", {})
    # Fail before any lookup or modification if the layout is invalid.
    render_photo(Image.new("RGB", (1, 1)), **layout)
    output = base / config.get("output", "wallpapers")
    client = Client(base / config.get("cache", ".projectivy-cache"), offline, refresh)
    manifest_path = output / "manifest.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest = {"version": 1, "layout": layout, "items": dict(previous.get("items", {})),
                "skipped": [], "written": 0}
    music = config.get("music", {})
    if music.get("enabled", True):
        library_path = base / music.get("library", "private/artists.json")
        artists = json.loads(library_path.read_text())["artists"]
        if limit is not None:
            artists = artists[:limit]
        for artist in artists:
            name = artist["name"]
            try:
                photos = artist_photos(client, name, music, base)
                if not photos:
                    raise ValueError("No exact artist match with a photo; add a local photo or alias.")
                # Try alternate artist photos if the preferred one has disappeared.
                last_error = None
                for photo in photos:
                    try:
                        filename = artist_filename(name)
                        write_wallpaper(client, photo, output / filename, layout, base)
                        manifest["items"][filename] = {**photo, "name": name}
                        manifest["written"] += 1
                        print("Saved artist:", name)
                        break
                    except (OSError, ValueError, UnidentifiedImageError) as exc:
                        last_error = exc
                else:
                    raise OSError(str(last_error))
            except (OSError, ValueError, KeyError) as exc:
                manifest["skipped"].append({"name": name, "reason": str(exc)})
                print(f"Skipped {name}: {exc}")
    for media_type, section in (("movie", "movies"), ("tv", "shows")):
        settings = config.get(section, {})
        if not settings.get("enabled", False):
            continue
        try:
            photos = movie_photos(client, media_type, settings)
        except (OSError, ValueError, KeyError) as exc:
            manifest["skipped"].append({"name": section, "reason": str(exc)})
            print(f"Skipped {section}: {exc}")
            continue
        for photo in photos:
            try:
                filename = f"{media_type}-{photo['id']}-{slug(photo['title'])}.jpg"
                write_wallpaper(client, photo, output / filename, layout, base)
                manifest["items"][filename] = photo
                manifest["written"] += 1
                print("Saved", media_type + ":", photo["title"])
            except (OSError, ValueError) as exc:
                manifest["skipped"].append({"name": photo["title"], "reason": str(exc)})
    save_json(manifest_path, manifest)
    print(f"{manifest['written']} wallpapers written; {len(manifest['skipped'])} skipped. "
          "Existing wallpapers were kept.")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import-library", help="Extract artists from your Apple Music CSV locally")
    imp.add_argument("csv", type=Path)
    imp.add_argument("--output", type=Path, default=ROOT / "private/artists.json")
    gen = commands.add_parser("generate", help="Generate a Projectivy wallpaper folder")
    gen.add_argument("--config", type=Path, default=ROOT / "projectivy.json")
    gen.add_argument("--offline", action="store_true", help="Use only local photos and cached downloads")
    gen.add_argument("--refresh", action="store_true", help="Refresh downloaded artwork and API responses")
    gen.add_argument("--limit", type=int, help="Maximum artists for this run")
    fit = commands.add_parser("fit-photo", help="Fit a single photo without cropping")
    fit.add_argument("photo", type=Path)
    fit.add_argument("output", type=Path)
    fit.add_argument("--size", nargs=2, type=int, default=[3840, 2160], metavar=("WIDTH", "HEIGHT"))
    fit.add_argument("--fill", choices=["blur", "black"], default="blur")
    args = parser.parse_args(argv)
    try:
        if args.command == "import-library":
            library = import_library(args.csv)
            save_json(args.output, library)
            print(f"Imported {library['artist_count']} artists into {args.output}")
        elif args.command == "generate":
            if args.limit is not None and args.limit < 1:
                raise ValueError("--limit must be at least 1.")
            config_path = args.config.resolve()
            manifest = generate(json.loads(config_path.read_text()), config_path.parent,
                                args.offline, args.refresh, args.limit)
            if manifest["written"] == 0:
                return 1
        else:
            write_wallpaper(Client(ROOT / ".projectivy-cache", offline=True),
                            {"source": str(args.photo.resolve())}, args.output,
                            {"size": args.size, "fill": args.fill}, ROOT)
            print(f"Saved {args.output}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
