import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import newsbot

AKSYS = """<html><article><h2 class="entry-title"><a href="https://www.aksysgames.com/announcement/">New Otome Game Launches This Summer</a></h2><p class="post-meta">Apr 29, 2026</p><div class="post-content-inner"><p>The new otome game will release on Nintendo Switch this summer.</p></div></article></html>"""
OTOMATE = """<html><ul><li><a href="/sample/">2026.11.05 ゲーム 「新しい乙女ゲーム」公式サイト公開！</a></li><li><div><span>2026.11.04</span><span>イベント</span><a href="/party/">オトメイトパーティー開催決定！</a></div></li><li><a href="/goods/">2026.11.02 グッズ 新しいグッズ発売！</a></li><li><a href="/maintenance/">2026.11.01 お知らせ サーバーメンテナンスのお知らせ</a></li></ul></html>"""

class Session:
    def __init__(self):
        self.sent = []
    def post(self, url, json, timeout):
        self.sent.append(json)
        return type("Response", (), {"status_code": 204})()

class NewsBotTests(unittest.TestCase):
    def test_aksys(self):
        items = newsbot.parse_aksys(AKSYS)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].date, "2026-04-29")
        self.assertIn("otome", items[0].summary)

    def test_otomate_filters_merch_and_maintenance(self):
        items = newsbot.parse_otomate(OTOMATE)
        self.assertEqual(len(items), 2)
        self.assertEqual({item.date for item in items}, {"2026-11-05", "2026-11-04"})

    def test_stable_keys(self):
        self.assertEqual(newsbot.parse_aksys(AKSYS)[0].key, newsbot.parse_aksys(AKSYS)[0].key)

    def test_initial_run_silent_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "state.json"
            session = Session()
            with patch.object(newsbot, "fetch", side_effect=[AKSYS, OTOMATE]):
                self.assertEqual(newsbot.run(state, "https://discord.com/api/webhooks/example/key", session), 0)
            self.assertFalse(session.sent)
            self.assertEqual(set(json.loads(state.read_text())["initialized_sources"]), {"Aksys Games", "Otomate (Japan)"})
            updated = AKSYS.replace("</html>", '<article><h2><a href="/latest/">Another Otome Game Announced Today</a></h2></article></html>')
            with patch.object(newsbot, "fetch", side_effect=[updated, OTOMATE]):
                self.assertEqual(newsbot.run(state, "https://discord.com/api/webhooks/example/key", session), 0)
            self.assertEqual(len(session.sent), 1)
            with patch.object(newsbot, "fetch", side_effect=[updated, OTOMATE]):
                self.assertEqual(newsbot.run(state, "https://discord.com/api/webhooks/example/key", session), 0)
            self.assertEqual(len(session.sent), 1)

    def test_translated_japanese_title_retains_original(self):
        item = newsbot.News("Otomate (Japan)", "新作ゲーム発表", "https://www.otomate-p.jp/news/", "2026-11-05", original_title="新作ゲーム発表")
        with patch.object(newsbot, "translator") as tr:
            tr.return_value.translate.return_value = "New game announced"
            result = newsbot.translate(item)
        self.assertEqual(result.title, "New game announced")
        s = Session()
        newsbot.send(s, "https://discord.com/api/webhooks/example/key", result)
        self.assertEqual(s.sent[0]["embeds"][0]["fields"][0]["value"], "新作ゲーム発表")
        self.assertEqual(s.sent[0]["allowed_mentions"], {"parse": []})

    def test_invalid_state_refuses_reposts(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            p.write_text('{"version":2,"initialized_sources":[],"seen":[]}')
            with self.assertRaises(ValueError):
                newsbot.read_state(p)

    def test_failed_source_not_initialized(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            with patch.object(newsbot, "fetch", side_effect=[RuntimeError("timeout"), OTOMATE]):
                self.assertEqual(newsbot.run(p, "https://discord.com/api/webhooks/example/key", Session()), 1)
            self.assertEqual(json.loads(p.read_text())["initialized_sources"], ["Otomate (Japan)"])

    def test_backfill_posts_once_even_when_already_seen(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            items = newsbot.parse_aksys(AKSYS) + newsbot.parse_otomate(OTOMATE)
            p.write_text(json.dumps({"version": 1, "initialized_sources": ["Aksys Games", "Otomate (Japan)"], "seen": [i.key for i in items]}))
            sender = Session()
            with patch.object(newsbot, "fetch", side_effect=[AKSYS, OTOMATE]), patch.object(newsbot, "translate", side_effect=lambda i: i), patch.object(newsbot.time, "sleep"):
                self.assertEqual(newsbot.run_backfill(p, "https://discord.com/api/webhooks/demo", sender, 1, 1), 0)
            self.assertEqual(len(sender.sent), 2)
            with patch.object(newsbot, "fetch", side_effect=[AKSYS, OTOMATE]), patch.object(newsbot, "translate", side_effect=lambda i: i), patch.object(newsbot.time, "sleep"):
                self.assertEqual(newsbot.run_backfill(p, "https://discord.com/api/webhooks/demo", sender, 1, 1), 0)
            self.assertEqual(len(sender.sent), 2)
            self.assertEqual(len(json.loads(p.read_text())["backfilled"]), 2)

if __name__ == "__main__":
    unittest.main()
