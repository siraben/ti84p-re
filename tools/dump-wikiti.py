#!/usr/bin/env python3
"""Dump the WikiTI MediaWiki (https://wikiti.brandonw.net) to local wikitext files.

WikiTI is the reference wiki for TI calculator internals (BCALLs, ports, RAM map,
system routines). This grabs the raw wikitext for every page in the useful content
namespaces so it can be grepped offline alongside the disassembly.

The wiki is heavily comment-spammed, so namespace 0 titles matching obvious spam
patterns are skipped (and logged). Output is written under wikiti-dump/ (gitignored).

Usage:
    python3 tools/dump-wikiti.py            # dump default namespaces
    python3 tools/dump-wikiti.py --all-ns   # include talk/user namespaces too
    python3 tools/dump-wikiti.py --images    # also download uploaded files
Re-running is safe: existing up-to-date pages are skipped (resumable).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://wikiti.brandonw.net/api.php"
OUTDIR = os.path.join(os.path.dirname(__file__), os.pardir, "wikiti-dump")
UA = "ti84-re-wikiti-dump/1.0 (offline reference; contact via github)"

# Content namespaces worth keeping by default. Talk/User are mostly noise + spam.
DEFAULT_NS = [0, 4, 6, 8, 10, 14]  # main, WikiTI, File, MediaWiki, Template, Category
ALL_NS = DEFAULT_NS + [1, 2, 3, 5, 7, 9, 11, 13, 15]

# Spam heuristic for namespace 0 (the wiki is overrun with SEO/cheat spam).
SPAM_RE = re.compile(
    r"generator|cheats?|free\s|hack|coins?|gems?|diamonds?|vbucks|robux|"
    r"no human verification|\bmod apk\b|\$safe|giveaway|promo code|spins?\b|"
    r"unlimited|glitch|2024|2025|2026",
    re.IGNORECASE,
)


def api_get(params, post=False):
    params = dict(params, format="json")
    if post:
        # POST avoids HTTP 414 when many/long titles are batched into the query.
        req = urllib.request.Request(
            API, data=urllib.parse.urlencode(params).encode("utf-8"),
            headers={"User-Agent": UA})
    else:
        url = API + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if attempt == 4:
                raise
            sys.stderr.write(f"  retry ({e}) ...\n")
            time.sleep(2 * (attempt + 1))
    return None


def list_pages(namespaces):
    """Yield (pageid, ns, title) for every page in the given namespaces."""
    for ns in namespaces:
        cont = {}
        while True:
            data = api_get({
                "action": "query", "list": "allpages",
                "apnamespace": ns, "aplimit": "500", **cont,
            })
            for p in data.get("query", {}).get("allpages", []):
                yield p["pageid"], p["ns"], p["title"]
            cont_block = data.get("query-continue", {}).get("allpages")
            if not cont_block:
                break
            cont = cont_block
            time.sleep(0.2)


def safe_path(ns, title):
    """Map a title to a filesystem path under wikiti-dump/."""
    ns_dir = {
        0: "main", 1: "talk", 2: "user", 3: "user_talk", 4: "wikiti",
        5: "wikiti_talk", 6: "file", 7: "file_talk", 8: "mediawiki",
        9: "mediawiki_talk", 10: "template", 11: "template_talk", 12: "help",
        13: "help_talk", 14: "category", 15: "category_talk",
    }.get(ns, f"ns{ns}")
    # Strip the "Namespace:" prefix MediaWiki prepends, then sanitize.
    name = title.split(":", 1)[1] if ns != 0 and ":" in title else title
    name = name.replace("/", "___").replace("\\", "___")
    name = re.sub(r"[\x00-\x1f]", "_", name)
    return os.path.join(OUTDIR, ns_dir, name + ".wiki")


def fetch_content(titles):
    """Return {title: wikitext} for up to 50 titles."""
    data = api_get({
        "action": "query", "prop": "revisions", "rvprop": "content",
        "titles": "|".join(titles),
    }, post=True)
    norm = {n["to"]: n["from"] for n in data.get("query", {}).get("normalized", [])}
    out = {}
    for p in data.get("query", {}).get("pages", {}).values():
        if "revisions" not in p:
            continue
        title = p["title"]
        out[norm.get(title, title)] = p["revisions"][0].get("*", "")
    return out


def download_images():
    imgdir = os.path.join(OUTDIR, "images")
    os.makedirs(imgdir, exist_ok=True)
    cont = {}
    n = 0
    while True:
        data = api_get({
            "action": "query", "list": "allimages", "ailimit": "500", **cont,
        })
        for img in data.get("query", {}).get("allimages", []):
            url, name = img.get("url"), img.get("name")
            if not url or not name:
                continue
            dest = os.path.join(imgdir, name.replace("/", "___"))
            if os.path.exists(dest):
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    open(dest, "wb").write(r.read())
                n += 1
                print(f"  image: {name}")
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"  image FAIL {name}: {e}\n")
        cont_block = data.get("query-continue", {}).get("allimages")
        if not cont_block:
            break
        cont = cont_block
    print(f"Downloaded {n} new images.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-ns", action="store_true", help="include talk/user namespaces")
    ap.add_argument("--images", action="store_true", help="also download uploaded files")
    ap.add_argument("--no-spam-filter", action="store_true", help="keep ns0 spam pages")
    ap.add_argument("--force", action="store_true", help="re-fetch pages already on disk")
    args = ap.parse_args()

    namespaces = ALL_NS if args.all_ns else DEFAULT_NS
    print(f"Dumping namespaces {namespaces} (streaming, resumable) ...")

    written = skipped_spam = skipped_existing = total = 0
    batch = []
    batch_meta = {}  # title -> (ns, path)

    def flush_batch():
        nonlocal written
        if not batch:
            return
        written += flush(batch, batch_meta)
        batch.clear()
        batch_meta.clear()
        time.sleep(0.2)

    # Enumerate and write in one streaming pass so a mid-run failure keeps progress.
    for _pid, ns, title in list_pages(namespaces):
        total += 1
        if ns == 0 and not args.no_spam_filter and SPAM_RE.search(title):
            skipped_spam += 1
            continue
        path = safe_path(ns, title)
        if not args.force and os.path.exists(path):
            skipped_existing += 1
            continue
        batch.append(title)
        batch_meta[title] = (ns, path)
        if len(batch) >= 50:
            flush_batch()
    flush_batch()

    print(f"\nSeen {total} pages | wrote {written} | "
          f"already had {skipped_existing} | skipped {skipped_spam} spam")
    print(f"Output: {os.path.normpath(OUTDIR)}")
    if args.images:
        print("Downloading images ...")
        download_images()


def flush(titles, meta):
    content = fetch_content(titles)
    n = 0
    for title, (ns, path) in meta.items():
        text = content.get(title)
        if text is None:
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        n += 1
    sys.stdout.write(f"\r  wrote {n}/{len(titles)} in batch ...")
    sys.stdout.flush()
    return n


if __name__ == "__main__":
    main()
    print()
