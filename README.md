# atsumaru-elfeed

Per-series Atom feeds from the Tachiyomi **Atsumaru** extension source
(`atsu.moe`), for [elfeed](https://github.com/skeeto/elfeed). Stdlib-only Python, no deps.

Reverse-engineered from `eu.kanade.tachiyomi.extension.en.atsumaru` v1.6.28:
new-chapter data comes from two JSON endpoints, no Cloudflare bypass needed
(the API is not behind the browser challenge):

- `GET https://atsu.moe/api/manga/page?id={mangaId}` — title, synopsis, scanlator names
- `GET https://atsu.moe/api/manga/allChapters?mangaId={mangaId}` — chapters
  (`id`, `title`, `number`, `createdAt`, `pageCount`)
- chapter links: `https://atsu.moe/read/{mangaId}/{chapterId}`
- id lookup: `https://atsu.moe/collections/manga/documents/search?q=...`

Same-number chapters from different scanlation groups are deduped (latest
upload wins), like the extension's dedupe option.

## Run

```sh
python3 atsumaru_elfeed.py            # serve on 127.0.0.1:8156
python3 atsumaru_elfeed.py search solo leveling   # find a manga id
python3 atsumaru_elfeed.py dump OlBhf > feed.xml  # one-shot static file
```

Add your series to `config.json`:

```json
{"mangas": [{"id": "OlBhf", "title": "Solo Leveling: Ragnarok"}]}
```

Feed URL per series: `http://127.0.0.1:8156/feed?id=OlBhf&max=30`
(`max` optional, defaults to `max_entries`). The newest `images_for_latest`
entries (default 30, `?images=N` overrides, `?images=0` disables) embed the
full page images from `cdn.atsu.moe` inline, so elfeed renders the chapter
when you open the entry. Page images are proxied through the server (`/img?u=...`) and converted
to JPEG with ImageMagick (`magick`, required) — Emacs 31 can't decode
avif, and this also avoids any hotlink weirdness. Converted pages are
cached forever in `.state/img/`; manga/chapter lists respect `cache_ttl`.
First view of a chapter converts
(~0.5s/page); afterwards it's instant.

## elfeed

```elisp
(setq elfeed-feeds
      '(("http://127.0.0.1:8156/feed?id=OlBhf" manga)))
```

## systemd user unit

`~/.config/systemd/user/atsumaru-elfeed.service`:

```ini
[Unit]
Description=atsumaru-elfeed
After=network-online.target

[Service]
WorkingDirectory=%h/personal/projects/elfeed-manga
ExecStart=%h/personal/projects/elfeed-manga/atsumaru_elfeed.py
Restart=on-failure

[Install]
WantedBy=default.target
```

```sh
systemctl --user enable --now atsumaru-elfeed.service
```
