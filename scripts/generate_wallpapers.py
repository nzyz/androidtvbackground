"""GitHub Actions entry point. Read user input from environment, never shell code."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from projectivy import generate, name_key, save_json


def artist_names(value: str) -> list[str]:
    names = {}
    for part in value.replace("\n", ";").split(";"):
        name = part.strip()
        if name:
            if len(name) > 200:
                raise ValueError("Artist names must be at most 200 characters each.")
            names.setdefault(name_key(name), name)
    if not names:
        raise ValueError("Enter artist names separated by semicolons, or set the ARTIST_NAMES repository secret.")
    if len(names) > 100:
        raise ValueError("Use at most 100 artists per run.")
    return list(names.values())


def main():
    try:
        value = os.getenv("ARTIST_INPUT", "").strip() or os.getenv("ARTIST_NAMES", "")
        names = artist_names(value)
        resolutions = {"4K": [3840, 2160], "1080p": [1920, 1080]}
        resolution = os.getenv("RESOLUTION", "4K")
        if resolution not in resolutions:
            raise ValueError("Choose 4K or 1080p resolution.")
        include_video = os.getenv("INCLUDE_MOVIES_SHOWS", "false").lower() == "true"
        if include_video and not os.getenv("TMDB_BEARER_TOKEN", "").strip():
            raise ValueError("Add a TMDB_BEARER_TOKEN repository secret, or turn off movies and shows.")
        config = json.loads((ROOT / "projectivy.example.json").read_text())
        config["layout"]["size"] = resolutions[resolution]
        config["movies"]["enabled"] = include_video
        config["shows"]["enabled"] = include_video
        save_json(ROOT / "private/artists.json", {"artists": [{"name": n} for n in names]})
        # Keep names out of build logs. Reports remain in the downloadable artifact.
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = generate(config, ROOT)
        summary = (f"Created {manifest['written']} uncropped wallpapers at {resolution}.\n"
                   f"Skipped {len(manifest['skipped'])} unavailable items.\n")
        print(summary)
        if manifest["written"] == 0:
            print("No photos could be downloaded. Check names, provider availability, or try again later.", file=sys.stderr)
            return 1
        summary_path = os.getenv("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write("## Your wallpaper pack\n\n" + summary.replace("\n", "\n\n") +
                        "Download **Projectivy-wallpapers** under Artifacts at the bottom of this run. "
                        "Extract the ZIP and copy its JPGs to your TV's wallpaper folder.\n")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
