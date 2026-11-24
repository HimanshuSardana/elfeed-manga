#!/usr/bin/env python3
"""Atsumaru (atsu.moe) -> Atom feed for elfeed. Stdlib only."""
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = "https://atsu.moe"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) atsumaru-elfeed/1.0",
      "Accept": "application/json", "Referer": "https://atsu.moe/"}

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_DIR = os.path.join(HERE, ".state")

CDN = "https://cdn.atsu.moe"


IMG_UA = {"User-Agent": UA["User-Agent"], "Referer": "https://atsu.moe/"}
MAGICK = shutil.which("magick") or shutil.which("convert")


def fetch_bytes(url, timeout=40):
    req = urllib.request.Request(url, headers=IMG_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def proxied_img_src(cdn_path):
    return "/img?u=" + urllib.parse.quote(cdn_path, safe="")


def serve_image(cdn_path):
    """Fetch cdn_path from CDN, convert to JPEG (Emacs can't do avif),
    cache forever. Returns (bytes, content_type)."""
    if not cdn_path.startswith("/static/") or ".." in cdn_path:
        raise ValueError("bad image path")
    key = hashlib.sha1(cdn_path.encode()).hexdigest()
    cdir = os.path.join(STATE_DIR, "img")
    os.makedirs(cdir, exist_ok=True)
    jpg = os.path.join(cdir, key + ".jpg")
    if os.path.exists(jpg):
        with open(jpg, "rb") as f:
            return f.read(), "image/jpeg"
    raw = fetch_bytes(CDN + cdn_path)
    data, ctype = raw, "application/octet-stream"
    if raw[:4] == b"\xff\xd8\xff\xe0" or raw[:4] == b"\xff\xd8\xff\xe1":
        data, ctype = raw, "image/jpeg"
    elif MAGICK:
        try:
            p = subprocess.run([MAGICK, "-", "-quality", "82", "jpg:-"] if os.path.basename(MAGICK) == "magick" else [MAGICK, "-", "-quality", "82", "jpg:-"],
                               input=raw, capture_output=True, timeout=120)
            if p.returncode == 0 and p.stdout[:2] == b"\xff\xd8":
                data, ctype = p.stdout, "image/jpeg"
        except Exception:
            pass
    if ctype == "image/jpeg" and data is not raw:
        tmp = jpg + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, jpg)
    return data, ctype


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def fetch_json(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def cached_get(key, url, ttl):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, key + ".json")
    if os.path.exists(path) and (ttl is None or time.time() - os.path.getmtime(path) < ttl):
        with open(path) as f:
            return json.load(f)
    data = fetch_json(url)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)
    return data


def api_manga(manga_id, ttl):
    return cached_get(f"manga-{manga_id}",
                      f"{BASE}/api/manga/page?id={urllib.parse.quote(manga_id)}", ttl)


def api_chapters(manga_id, ttl):
    return cached_get(f"chapters-{manga_id}",
                      f"{BASE}/api/manga/allChapters?mangaId={urllib.parse.quote(manga_id)}", ttl)


def api_pages(manga_id, chapter_id):
    # page lists are immutable -> cache forever (ttl=None)
    return cached_get(f"pages-{manga_id}-{chapter_id}",
                      f"{BASE}/api/read/chapter?mangaId={urllib.parse.quote(manga_id)}"
                      f"&chapterId={urllib.parse.quote(chapter_id)}", None)


def api_search(query, per_page=8):
    q = urllib.parse.urlencode({
        "q": query, "query_by": "title,englishTitle,otherNames,authors,acronyms",
        "query_by_weights": "4,3,2,2,1", "prefix": "true,true,true,true,false",
        "infix": "off,off,fallback,off,off", "filter_by": "hidden:!=true",
        "include_fields": "id,title,posterMedium", "page": 1, "per_page": per_page,
    })
    return fetch_json(f"{BASE}/collections/manga/documents/search?{q}")


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def esc(s):
    return html.escape(s or "", quote=True)


def build_atom(manga_id, manga_page, chapters, max_entries, images_for_latest=30,
               img_base="http://127.0.0.1:8156"):
    mp = manga_page.get("mangaPage", manga_page)
    title = mp.get("title") or manga_id
    syn = (mp.get("synopsis") or "")[:500]
    manga_url = f"{BASE}/manga/{manga_id}"
    scanlator = {s.get("id"): s.get("name", "") for s in mp.get("scanlators", [])}
    # dedupe: same chapter number may exist per scanlation group; keep latest upload
    latest = {}
    for c in chapters:
        key = c.get("number", c.get("id"))
        if key not in latest or c.get("createdAt", 0) > latest[key].get("createdAt", 0):
            latest[key] = c
    items = sorted(latest.values(), key=lambda c: c.get("createdAt", 0), reverse=True)[:max_entries]
    updated = iso(max((c.get("createdAt", 0) for c in items), default=0) or int(time.time() * 1000))
    out = [f'<?xml version="1.0" encoding="utf-8"?>',
           f'<feed xmlns="http://www.w3.org/2005/Atom">',
           f"<title>Atsumaru: {esc(title)}</title>",
           f'<link href="{esc(manga_url)}"/>',
           f'<link rel="self" href="{esc(f"feed?id={manga_id}")}"/>',
           f"<id>tag:atsu.moe,2026:manga:{esc(manga_id)}</id>",
           f"<updated>{updated}</updated>",
           f"<subtitle>{esc(syn)}</subtitle>"]
    for i, c in enumerate(items):
        cid = c.get("id", "")
        ctitle = c.get("title") or f"Chapter {c.get('number', '?')}"
        grp = scanlator.get(c.get("scanlationMangaId", ""), "")
        link = f"{BASE}/read/{manga_id}/{cid}"
        out.append("<entry>")
        out.append(f"<title>{esc(ctitle + (f' [{grp}]' if grp else ''))}</title>")
        out.append(f'<link href="{esc(link)}"/>')
        out.append(f"<id>tag:atsu.moe,2026:chapter:{esc(cid)}</id>")
        out.append(f"<updated>{iso(c.get('createdAt', 0) or int(time.time()*1000))}</updated>")
        body = [f"<p>{esc(title)} — {esc(ctitle)} ({c.get('pageCount', 0)} pages) "
                f"<a href=\"{esc(link)}\">Read</a></p>"]
        if i < images_for_latest:
            try:
                pages = api_pages(manga_id, cid).get("readChapter", {}).get("pages", [])
                for p in sorted(pages, key=lambda p: p.get("number", 0)):
                    src = p.get("image", "")
                    if src.startswith("/"):
                        src = img_base + proxied_img_src(src)
                    body.append(f'<p><img src="{esc(src)}"/></p>')
            except Exception as e:
                body.append(f"<p><i>pages unavailable: {esc(str(e))}</i></p>")
        out.append(f"<content type=\"html\">{esc(''.join(body))}</content>")
        out.append("</entry>")
    out.append("</feed>")
    return "\n".join(out).encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "atsumaru-elfeed/1.0"

    def log_message(self, *a):
        sys.stderr.write(f"{self.address_string()} {a[0] % a[1:]}\n")

    def send_text(self, code, body, ctype):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        cfg = load_config()
        ttl = cfg.get("cache_ttl", 900)
        max_entries = cfg.get("max_entries", 30)
        u = urllib.parse.urlsplit(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            rows = "".join(
                f'<li><a href="/feed?id={esc(m["id"])}">{esc(m.get("title") or m["id"])}</a>'
                f' <small>{esc(m["id"])}</small></li>'
                for m in cfg.get("mangas", []))
            return self.send_text(200,
                f"<html><body><h1>atsumaru-elfeed</h1><ul>{rows}</ul>"
                f'<form action="/search"><input name="q"/><button>search</button></form></body></html>',
                "text/html; charset=utf-8")
        if u.path == "/search":
            try:
                res = api_search(qs.get("q", [""])[0])
                hits = [{"id": h["document"]["id"], "title": h["document"]["title"]}
                        for h in res.get("hits", [])]
                return self.send_text(200, json.dumps(hits, indent=1) + "\n",
                                      "application/json")
            except Exception as e:
                return self.send_text(502, f"search failed: {e}\n", "text/plain")
        if u.path == "/img":
            cdn_path = (qs.get("u") or [""])[0]
            try:
                data, ctype = serve_image(cdn_path)
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "public, max-age=31536000")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_text(502 if "bad" not in str(e) else 400,
                               f"image failed: {e}\n", "text/plain")
            return
        if u.path == "/feed":
            manga_id = (qs.get("id") or [""])[0].strip()
            if not manga_id:
                return self.send_text(400, "missing ?id=MANGA_ID\n", "text/plain")
            try:
                n = int((qs.get("max") or [0])[0] or max_entries)
            except ValueError:
                n = max_entries
            try:
                k = int((qs.get("images") or [0])[0] or cfg.get("images_for_latest", 30))
            except ValueError:
                k = cfg.get("images_for_latest", 30)
            try:
                manga = api_manga(manga_id, ttl)
                ch = api_chapters(manga_id, ttl).get("chapters", [])
                base = f"http://{cfg.get('host', '127.0.0.1')}:{cfg.get('port', 8156)}"
                return self.send_text(200, build_atom(manga_id, manga, ch, n, k, base),
                                      "application/atom+xml; charset=utf-8")
            except Exception as e:
                return self.send_text(502, f"upstream failed: {e}\n", "text/plain")
        return self.send_text(404, "not found\n", "text/plain")


def main(argv):
    args = [a for a in argv[1:] if a.startswith("--")]
    rest = [a for a in argv[1:] if not a.startswith("--")]
    opts = {}
    for a in args:
        if "=" in a:
            k, v = a[2:].split("=", 1)
            opts[k] = v
    global CONFIG_PATH
    if "config" in opts:
        CONFIG_PATH = opts["config"]
    if rest and rest[0] == "search":
        for h in api_search(" ".join(rest[1:])).get("hits", []):
            print(h["document"]["id"], "-", h["document"]["title"])
        return
    if len(rest) >= 2 and rest[0] == "dump":
        mid = rest[1]
        cfg = load_config()
        manga = api_manga(mid, cfg.get("cache_ttl", 900))
        ch = api_chapters(mid, cfg.get("cache_ttl", 900)).get("chapters", [])
        sys.stdout.buffer.write(build_atom(mid, manga, ch, cfg.get("max_entries", 30),
                                            cfg.get("images_for_latest", 30),
                                            f"http://{cfg.get('host', '127.0.0.1')}:{cfg.get('port', 8156)}"))
        return
    cfg = load_config()
    host = opts.get("host", cfg.get("host", "127.0.0.1"))
    port = int(opts.get("port", cfg.get("port", 8156)))
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"serving on http://{srv.server_address[0]}:{srv.server_address[1]}  (Ctrl-C to stop)")
    srv.serve_forever()


if __name__ == "__main__":
    main(sys.argv)
