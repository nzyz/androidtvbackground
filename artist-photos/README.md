Place your preferred artist photos here to override online lookups.

Use a lower-case, hyphenated artist name: `mac-miller.jpg`, `kid-cudi.png`,
`a-ap-rocky.jpg`, `mgk.jpg`. Supported extensions: jpg, jpeg, png, webp.
Spaces and punctuation become hyphens; a `$` at the beginning is removed.

For names that produce the same filename, or any other filename, use the
`music.photos` map in projectivy.json instead:

```json
"photos": {
  "Mac Miller": "artist-photos/my-favourite-mac-photo.jpg",
  "Kid Cudi": "https://example.com/my-photo.jpg"
}
```

Paths are relative to the configuration file. Local photos work offline.
The complete original photo is fitted within the screen, never cropped or
stretched. Extra space uses a blurred fill by default, or black if configured.
