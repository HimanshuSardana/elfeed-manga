# atsumaru-elfeed

Per-series Atom feeds for elfeed, built from the same JSON API the Atsumaru
Tachiyomi extension (`atsu.moe`) uses. Follow a manga, open a chapter in
elfeed, read the full pages inline.

```sh
python3 atsumaru_elfeed.py search solo leveling
# OlBhf - Solo Leveling: Ragnarok
python3 atsumaru_elfeed.py
# serving on http://127.0.0.1:8156  (Ctrl-C to stop)
```

Add `http://127.0.0.1:8156/feed?id=OlBhf` to `elfeed-feeds` and update.
It avoids heavy dependencies on purpose: the server is one stdlib-only
Python file, state is flat JSON under `.state/`, the only outside tool is
ImageMagick for image conversion.

## Features

- **Series feeds from the extension API.** Manga details come from
  `/api/manga/page`, chapters from `/api/manga/allChapters`, page lists
  from `/api/read/chapter`, id lookup from the Typesense
  `/collections/manga/documents/search` endpoint.
- **Full pages inside entries.** The newest `images_for_latest` entries
  embed every page image, so a chapter renders directly in
  `elfeed-show`.
- **JPEG image proxy.** Pages on `cdn.atsu.moe` are webp/avif, which Emacs
  cannot all decode, so `/img` converts them to JPEG with `magick` and
  caches the result forever.
- **Scanlator dedupe.** The same chapter number often exists per
  scanlation group; only the latest upload is kept, and the group name is
  appended to the entry title (for example, `Chapter 73 [GenZ]`).
- **Stable entry ids.** Ids are `tag:atsu.moe,2026:chapter:<id>`, so
  refetches update entries in place instead of duplicating them.
- **Layered caching.** Manga and chapter lists respect `cache_ttl`
  (default 900 seconds); page lists and converted images never expire
  because upstream never changes them.
- **Small operational surface.** Three CLI modes, four HTTP routes, one
  JSON config file, file logging to stderr.

## Requirements

- Python 3 (stdlib only, no packages).
- ImageMagick (`magick` on PATH) for webp/avif conversion. Without it,
  JPEG pages still work; anything else is served as
  `application/octet-stream` and will not render in elfeed.

## Install

```sh
git clone https://github.com/HimanshuSardana/elfeed-manga
cd elfeed-manga
cp config.json config.json  # edit ids to taste, or leave the examples
python3 atsumaru_elfeed.py
```

## Usage

### CLI

```sh
python3 atsumaru_elfeed.py search <words>   # print "id - title" matches
python3 atsumaru_elfeed.py dump <id>        # write one feed to stdout
python3 atsumaru_elfeed.py --host=127.0.0.1 --port=8157 --config=/path/to/config.json
```

Flags override the matching `config.json` values. `config.json` holds
**host**, **port**, **cache_ttl** (seconds), **max_entries** per feed,
**images_for_latest**, and the **mangas** list shown on the index page.

### Server

| Route | Query | Result |
|---|---|---|
| `/` | | HTML list of configured series plus a search box |
| `/search` | `?q=` | JSON id/title hits from the site search |
| `/feed` | `?id=`, `?max=`, `?images=` | Atom feed, newest first |
| `/img` | `?u=/static/...` | Converted JPEG page, cached forever |

`max` defaults to `max_entries`, `images` to `images_for_latest`
(`0` disables images, link-only entries). Point elfeed at a feed URL:

```elisp
(setopt elfeed-feeds
        '(("http://127.0.0.1:8156/feed?id=OlBhf" manga)))
```

A systemd user unit keeps it up across reboots:

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

## Notes and limitations

- Novel entries return empty page lists from upstream, so those feeds
  are metadata plus a Read link only. Comics are unaffected.
- A cold feed build fetches one page list per chapter (roughly 30
  requests for defaults), which takes on the order of 20 seconds once;
  afterwards everything is served from `.state/`.
- If upstream rate-limits page fetches, the affected entry gets a
  "pages unavailable" note and succeeds on a later update.
- Chapter entry dates are the upstream upload dates, so back-catalogue
  series sit far back under elfeed date filters such as `@6-months-ago`.
  Drop the date part of the filter while catching up.

> [!NOTE]
> `config.json` ships with example series ids. Delete them or keep them,
> but do not be surprised when Naruto shows up in elfeed.
