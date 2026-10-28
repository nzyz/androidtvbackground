import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from projectivy import (Client, artist_filename, artist_photos, generate,
                        import_library, render_photo, save_json)


class WallpaperTests(unittest.TestCase):
    def test_all_edges_survive_portrait_square_and_wide_photos(self):
        # Colored corners catch accidental cover/crop, including opposite aspect ratios.
        for source_size in [(90, 180), (180, 90), (120, 120), (240, 60)]:
            with self.subTest(source_size=source_size):
                image = Image.new("RGB", source_size, "white")
                draw = ImageDraw.Draw(image)
                w, h = source_size
                colors = ["red", "lime", "blue", "yellow"]
                points = [(0, 0), (w - 12, 0), (0, h - 12), (w - 12, h - 12)]
                for (x, y), color in zip(points, colors):
                    draw.rectangle((x, y, x + 11, y + 11), fill=color)
                result = render_photo(image, (320, 180), fill="black")
                self.assertEqual(result.size, (320, 180))
                scale = min(320 / w, 180 / h)
                fw, fh = int(w * scale), int(h * scale)
                left, top = (320 - fw) // 2, (180 - fh) // 2
                coords = [(left + 2, top + 2), (left + fw - 3, top + 2),
                          (left + 2, top + fh - 3), (left + fw - 3, top + fh - 3)]
                expected = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
                for point, color in zip(coords, expected):
                    pixel = result.getpixel(point)
                    self.assertTrue(all(abs(a - b) < 12 for a, b in zip(pixel, color)),
                                    (source_size, point, pixel, color))

    def test_blurred_fill_does_not_darken_or_blur_foreground(self):
        image = Image.new("RGB", (40, 80), (100, 160, 220))
        result = render_photo(image, (160, 90))
        self.assertEqual(result.getpixel((80, 45)), (100, 160, 220))
        self.assertEqual(result.getpixel((0, 45)), (50, 80, 110))

    def test_exif_orientation_applied_before_fitting(self):
        image = Image.new("RGB", (40, 80), "red")
        exif = image.getexif()
        exif[274] = 6
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", exif=exif)
        buffer.seek(0)
        with Image.open(buffer) as photo:
            result = render_photo(photo, (160, 90), fill="black")
        self.assertEqual(result.getpixel((2, 45))[0], 254)
        self.assertEqual(result.getpixel((80, 0)), (0, 0, 0))

    def test_invalid_layout_rejected(self):
        for size in [(0, 10), (-1, 2), (1.2, 4), (10000, 10000)]:
            with self.assertRaises(ValueError):
                render_photo(Image.new("RGB", (10, 10)), size)

    def test_artist_rows_have_names_in_track_column_and_are_not_split(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.csv"
            fields = ["Track name", "Artist name", "Type", "Playlist name", "Album", "Apple - id"]
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows([
                    {"Type": "Artist", "Track name": "Artist & Friend"},
                    {"Type": "Artist", "Track name": "Solo"},
                    {"Type": "Artist", "Track name": "solo"},
                    {"Type": "Playlist", "Track name": "A Song", "Artist name": "Solo",
                     "Apple - id": "123", "Playlist name": "Other"},
                    {"Type": "Playlist", "Track name": "A Song", "Artist name": "Solo",
                     "Apple - id": "123", "Playlist name": "Favourite Songs"},
                ])
            data = import_library(path)
            self.assertEqual(data["artist_count"], 2)
            self.assertEqual(data["artists"][0],
                             {"name": "Solo", "library_tracks": 1, "favourite_tracks": 1})
            self.assertEqual(data["artists"][1]["name"], "Artist & Friend")

    def test_photo_matching_rejects_similar_artist_and_album_fallback(self):
        client = Client(Path("unused"), offline=True)
        with patch.object(client, "json", return_value={"artists": [
            {"strArtist": "Another Artist", "strArtistFanart": "https://example.org/wrong.jpg"}]}):
            self.assertEqual(artist_photos(client, "Artist", {}, Path("/tmp")), [])
        with patch.object(client, "json", return_value={"artists": [
            {"strArtist": "Artist", "idArtist": "1", "strAlbumThumb": "album.jpg"}]}):
            self.assertEqual(artist_photos(client, "Artist", {}, Path("/tmp")), [])

    def test_portrait_used_if_no_fanart_and_alias_is_explicit(self):
        client = Client(Path("unused"), offline=True)
        record = {"strArtist": "Machine Gun Kelly", "idArtist": "1",
                  "strArtistThumb": "https://example.org/portrait.jpg"}
        with patch.object(client, "json", return_value={"artists": [record]}) as request:
            photos = artist_photos(client, "mgk", {"aliases": {"mgk": "Machine Gun Kelly"}}, Path("/tmp"))
            self.assertEqual(photos[0]["source"], record["strArtistThumb"])
            self.assertIn("Machine+Gun+Kelly", request.call_args.args[0])

    def test_local_generation_and_failed_refresh_preserve_previous_wallpaper(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            save_json(base / "artists.json", {"artists": [{"name": "Artist"}]})
            Image.new("RGB", (90, 180), "red").save(base / "photo.png")
            config = {"layout": {"size": [320, 180]}, "music": {
                "library": "artists.json", "photos": {"Artist": "photo.png"}}}
            first = generate(config, base, offline=True)
            wallpaper = base / "wallpapers" / artist_filename("Artist")
            original = wallpaper.read_bytes()
            self.assertEqual(first["written"], 1)
            with Image.open(wallpaper) as image:
                self.assertEqual(image.size, (320, 180))
            (base / "photo.png").write_bytes(b"bad photo")
            failed = generate(config, base, offline=True)
            self.assertEqual(failed["written"], 0)
            self.assertEqual(len(failed["skipped"]), 1)
            self.assertEqual(wallpaper.read_bytes(), original)
            self.assertIn(wallpaper.name, failed["items"])

    def test_offline_cache_and_filename_collisions(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Client(Path(directory), offline=True)
            with self.assertRaises(OSError):
                client.get("https://example.org/photo.jpg")
            with self.assertRaises(ValueError):
                client.get("http://example.org/photo.jpg")
            self.assertNotEqual(artist_filename("A$AP"), artist_filename("A AP"))


if __name__ == "__main__":
    unittest.main()
