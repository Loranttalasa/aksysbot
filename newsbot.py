"""Nova: free Aksys Games + Otomate announcements to Discord."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

AKSYS_URL = "https://www.aksysgames.com/blog/"
OTOMATE_URL = "https://www.otomate-p.jp/news/"
STATE_PATH = Path(__file__).with_name("state.json")
DATE = re.compile(r"20\\d{2}\\.\\d{2}\\.\\d{2}")
JP_ENTRY = re.compile(r"(20\\d{2}\\.\\d{2}\\.\\d{2})\\s*(ゲーム|グッズ|お知らせ|イベント)\\s*(.+)", re.S)
LOG = logging.getLogger("nova")
MAX_POSTS = 8

@dataclass(frozen=True)
class News:
    source: str
    title: str
    url: str
    date: str = ""
    summary: str = ""
    original_title: str = ""

    @property
    def key(self):
        raw = "\\n".join([self.source, self.date, self.url, self.original_title or self.title])
        return hashlib.sha256(raw.encode()).hexdigest()

def clean(text):
    return " ".join(text.split()).strip()

def session_factory():
    s = requests.Session()
    s.headers["User-Agent"] = "NovaOtomeNewsBot/1.0 (public news reader)"
    retry = Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s

def fetch(session, url):
    response = session.get(url, timeout=25)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text

def parse_aksys(html):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for heading in soup.select("h2.entry-title, h2, h3.entry-title"):
        a = heading.find("a", href=True)
        if not a:
            continue
        url = urljoin(AKSYS_URL, a["href"])
        if urlparse(url).hostname not in {"aksysgames.com", "www.aksysgames.com"}:
            continue
        title = clean(a.get_text(" ", strip=True))
        if len(title) < 12 or url.rstrip("/") == AKSYS_URL.rstrip("/"):
            continue
        parent = heading.find_parent("article") or heading.find_parent(class_=re.compile("post|entry", re.I)) or heading.parent
        meta = parent.select_one(".post-meta, .entry-meta, time, .published")
        date = ""
        if meta:
            value = meta.get("datetime", "") or clean(meta.get_text(" ", strip=True))
            match = re.search(r"\\d{4}-\\d{2}-\\d{2}|[A-Z][a-z]{2}\\s+\\d{1,2},\\s*\\d{4}", value)
            if match:
                try:
                    date = datetime.strptime(match.group(), "%b %d, %Y").date().isoformat() if "," in match.group() else match.group()
                except ValueError:
                    pass
        excerpt = parent.select_one(".post-content-inner p, .entry-content p, .post-content p")
        if excerpt is None:
            excerpt = next((p for p in parent.select("p") if len(clean(p.get_text(" ", strip=True))) > 35), None)
        item = News("Aksys Games", title, url, date, clean(excerpt.get_text(" ", strip=True))[:340] if excerpt else "")
        found[item.key] = item
    return list(found.values())

def parse_otomate(html):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for node in soup.find_all(string=lambda s: bool(s and DATE.search(s))):
        parent = node.parent
        match = None
        entry = None
        for _ in range(7):
            if parent is None or parent.name in ("html", "body"):
                break
            text = clean(parent.get_text(" ", strip=True))
            if len(text) > 350 or len(DATE.findall(text)) > 1:
                break
            candidate = JP_ENTRY.search(text)
            if candidate and clean(candidate.group(3)):
                match, entry = candidate, parent
                break
            parent = parent.parent
        if not match:
            continue
        date, category, title = match.groups()
        title = clean(title)
        if category not in {"ゲーム", "イベント", "お知らせ"} or any(word in title for word in ("メンテナンス", "障害")):
            continue
        anchor = entry.find("a", href=True)
        url = urljoin(OTOMATE_URL, anchor["href"]) if anchor else OTOMATE_URL
        if urlparse(url).scheme not in ("http", "https"):
            url = OTOMATE_URL
        item = News("Otomate (Japan)", title, url, date.replace(".", "-"), original_title=title)
        found[item.key] = item
    return list(found.values())

@lru_cache(maxsize=1)
def translator():
    import argostranslate.package
    import argostranslate.translate

    def installed():
        languages = {language.code: language for language in argostranslate.translate.get_installed_languages()}
        if "ja" in languages and "en" in languages:
            return languages["ja"].get_translation(languages["en"])
        return None

    result = installed()
    if result:
        return result
    LOG.info("Downloading offline Japanese-to-English translation model")
    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    package = next((p for p in available if p.from_code == "ja" and p.to_code == "en"), None)
    if not package:
        raise RuntimeError("Japanese-English model unavailable")
    argostranslate.package.install_from_path(package.download())
    result = installed()
    if not result:
        raise RuntimeError("Failed to initialize translation model")
    return result

def translate(item):
    if item.source != "Otomate (Japan)":
        return item
    english = clean(translator().translate(item.title))
    if not english:
        raise ValueError("Japanese translation was empty")
    return News(item.source, english, item.url, item.date, original_title=item.original_title)

def read_state(path):
    if not path.exists():
        return {"version": 1, "initialized_sources": [], "seen": []}
    data = json.loads(path.read_text(encoding="utf8"))
    if data.get("version") != 1 or not isinstance(data.get("seen"), list) or not isinstance(data.get("initialized_sources"), list):
        raise ValueError("Invalid state: refusing to repost existing news")
    return data

def save_state(path, data):
    data["seen"] = list(dict.fromkeys(data["seen"]))[-3000:]
    data["initialized_sources"] = sorted(set(data["initialized_sources"]))
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\\n", encoding="utf8")
    temp.replace(path)

def send(session, webhook, item):
    japanese = item.source == "Otomate (Japan)"
    embed = {
        "title": item.title[:256],
        "url": item.url,
        "description": (item.summary or ("Japanese announcement (headline translated automatically)." if japanese else "New Aksys Games announcement."))[:3500],
        "color": 0xD75D9B if japanese else 0x5479CD,
        "author": {"name": "🇯🇵 Otomate — Japanese news" if japanese else "🇺🇸 Aksys Games — Official news"},
        "fields": ([{"name": "Original Japanese title", "value": item.original_title[:1000], "inline": False}] if japanese else []) + ([{"name": "Published", "value": item.date, "inline": True}] if item.date else []),
        "footer": {"text": "Machine translated • Japanese release ≠ English localization" if japanese else "Official Aksys Games announcement"},
    }
    response = session.post(webhook, json={"username": "Nova News Bot", "embeds": [embed], "allowed_mentions": {"parse": []}}, timeout=25)
    if response.status_code not in range(200, 300):
        raise RuntimeError(f"Discord replied HTTP {response.status_code}")

def run(state_path, webhook, session):
    data = read_state(state_path)
    already = set(data["seen"])
    initialized = set(data["initialized_sources"])
    fresh = []
    errors = []
    for source, url, parser in [
        ("Aksys Games", AKSYS_URL, parse_aksys),
        ("Otomate (Japan)", OTOMATE_URL, parse_otomate),
    ]:
        try:
            items = parser(fetch(session, url))
            if not items:
                raise ValueError("Parsed no announcements: source layout may have changed")
            if source not in initialized:
                LOG.info("First check of %s: remembering %d existing articles", source, len(items))
                data["seen"].extend(x.key for x in items)
                initialized.add(source)
                data["initialized_sources"] = list(initialized)
                already.update(x.key for x in items)
                save_state(state_path, data)
            else:
                new = [x for x in items if x.key not in already]
                LOG.info("%s: %d new articles", source, len(new))
                fresh.extend(new)
        except Exception as e:
            LOG.error("%s fetch failed: %s", source, e)
            errors.append(source)
    for item in sorted(fresh, key=lambda i: (i.date, i.source, i.title))[:MAX_POSTS]:
        try:
            send(session, webhook, translate(item))
            data["seen"].append(item.key)
            save_state(state_path, data)
            LOG.info("Posted one %s article", item.source)
        except Exception as e:
            LOG.error("Failed to post %s: %s", item.source, e)
            errors.append(item.source + " post")
            break
    save_state(state_path, data)
    return 1 if errors else 0

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-webhook", action="store_true")
    args = parser.parse_args()
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook.startswith("https://discord.com/api/webhooks/"):
        LOG.error("Add DISCORD_WEBHOOK_URL to GitHub Actions secrets")
        return 1
    session = session_factory()
    if args.test_webhook:
        r = session.post(webhook, json={"username": "Nova News Bot", "content": "✅ **Nova News Bot connected!** Monitoring Aksys Games and Otomate. 🇺🇸 🇯🇵", "allowed_mentions": {"parse": []}}, timeout=25)
        if r.status_code not in range(200, 300):
            LOG.error("Discord test returned HTTP %s", r.status_code)
            return 1
        return 0
    return run(STATE_PATH, webhook, session)

if __name__ == "__main__":
    sys.exit(main())
