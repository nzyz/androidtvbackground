# Your Projectivy wallpaper mix

Artist photographs from your Apple Music artist list, plus general movie and TV
backdrops from TMDB. No album-cover fallback, text, ratings, or logos are added.

Every photo stays complete and keeps its original proportions. A wide 16:9 photo
fills a 16:9 TV naturally. Portraits, squares, and extra-wide images are fitted
inside the screen with a blurred extension in the remaining space. The sharp
photo is never cropped, stretched, darkened, or covered with a gradient.

## Quick start

Requires Python 3.10+ on a computer or server. Android TV only displays the
finished JPEGs; this is not an Android app or an Apple Music account connection.

```sh
python -m pip install -r requirements-projectivy.txt
cp projectivy.example.json projectivy.json
python projectivy.py import-library "/path/to/My Apple Music Library.csv"
python projectivy.py generate
```

The import creates `private/artists.json`. The raw CSV and track list are not
needed after importing. Personal imports are excluded from version control.
Library artists are prioritized by their unique tracks in Favourite Songs,
then other library tracks. These counts describe saved music, not play history.
Collaborative artist names are kept intact rather than guessing their members.

For just a few artists first: `python projectivy.py generate --limit 5`.
All artists get one wallpaper each, so an artist with many songs does not
overwhelm the rotation. The output folder can contain both music and film/TV JPEGs.

## Artist photo sources

The generator prefers TheAudioDB artist fanart (wide photographs) and uses an
artist portrait only when fanart is unavailable. It requires an exact artist
name match, or an explicit alias in `music.aliases`. Missing artists are reported
in `wallpapers/manifest.json`; a similarly named artist or album cover is never
silently substituted. The shared test key `123` is configured for initial testing.
Use your own `AUDIODB_API_KEY` for ongoing use, subject to the provider's limits.

* [TheAudioDB API documentation](https://www.theaudiodb.com/free_music_api)
* [TheAudioDB terms](https://www.theaudiodb.com/docs_terms_of_use.php)

Only the artist name is sent to the photo provider, not the CSV, your playlists,
Apple credentials, or track IDs. Responses/photos are cached locally. Metadata
and source links are retained in the output manifest. Artwork rights remain with
the photographers/providers; a generated wallpaper is not a license to redistribute
their photos.

For your own photo choices, place photos in `artist-photos/` (see its README),
or set exact-name entries under `music.photos`:

```json
"photos": {
  "Mac Miller": "artist-photos/mac-live.jpg",
  "Kid Cudi": "artist-photos/cudi-portrait.png"
}
```

URLs must use HTTPS. Paths are relative to `projectivy.json`. Local overrides
take priority over online results, and work without any provider key.

## General movies and shows

The movie/show modes fetch trending weekly backdrops, excluding titles flagged
adult by TMDB. Set your TMDB API read access token before generating:

```sh
export TMDB_BEARER_TOKEN='your-token'
python projectivy.py generate
```

On PowerShell use `$env:TMDB_BEARER_TOKEN = 'your-token'`. The new command reads
the environment, not `.env` automatically. Missing tokens skip movie/show
downloads with an explanation; artist photos still run. Configure each source's
`enabled`, `limit`, and `language` in `projectivy.json`. No Plex/Jellyfin account
is required. The new command is separate from the original upstream scripts.

## No cropping

The default canvas is 3840 × 2160 (4K, 16:9). For a 1080p set, change `layout.size`
to `[1920, 1080]`. Match the TV's actual aspect ratio to prevent the launcher from
having to crop the completed wallpaper. Set `layout.fill` to `black` for plain
letterboxing instead of blurred fill. `background_brightness` affects only the
blurred extension, never the sharp photo. There is deliberately no crop mode.

To fit any single photo:

```sh
python projectivy.py fit-photo artist-photos/mac-live.jpg wallpapers/mac.jpg
```

Projectivy's app rows remain on top of wallpapers. Move or minimize rows if they
cover faces; the generator cannot control the launcher UI. Disable any wallpaper
zoom/pan or TV overscan if those settings crop the edges on your device.

## Put the wallpapers on your TV

1. Copy the generated JPG files from `wallpapers/` to a folder on the Android TV,
   using USB or your usual phone-to-TV file transfer app.
2. In Projectivy's wallpaper settings, choose the user-defined/custom folder
   source and select that folder. Labels depend on your installed version;
   the folder option may require Projectivy Premium.
3. Set your preferred wallpaper change interval in Projectivy.

The CSV, configuration, cache, and manifest do not need to go onto the TV.

## Refresh, privacy, and failures

`python projectivy.py generate --refresh` fetches fresh source responses and photos.
`--offline` uses only local files and cached sources. Each successful JPEG is
written atomically. Failed lookups, missing photos, and network errors leave
previous wallpapers intact. Output is additive: remove unwanted old JPGs yourself
when you remove artists or sources. A run that writes nothing exits with status 1.

`private/`, `artist-photos/` images, the cache, and generated wallpapers are ignored
by git. Keep your personal configuration and API keys out of public repositories.
The public source archive excludes all imported personal data and artwork.

## Verify

```sh
python -m unittest discover -s tests -v
```

Checks cover the four corners surviving portrait/square/wide fits, EXIF rotation,
foreground color preservation, export parsing, name matching, local generation,
and keeping the previous successful output after a failed refresh.
