import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from artifacts import collect, export


class ExtractorTests(unittest.TestCase):
    def test_merge_timestamp_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chrome, firefox = root / "History", root / "places.sqlite"
            with closing(sqlite3.connect(chrome)) as db:
                db.executescript("CREATE TABLE urls(id INTEGER PRIMARY KEY,url TEXT,title TEXT); CREATE TABLE visits(url INTEGER,visit_time INTEGER); CREATE TABLE downloads(tab_url TEXT,target_path TEXT,start_time INTEGER); INSERT INTO urls VALUES(1,'https://a.example','A'); INSERT INTO visits VALUES(1,13300000000000000); INSERT INTO downloads VALUES('https://b.example','C:/b',13300000000000001);")
                db.commit()
            with closing(sqlite3.connect(firefox)) as db:
                db.executescript("CREATE TABLE moz_places(id INTEGER PRIMARY KEY,url TEXT,title TEXT); CREATE TABLE moz_historyvisits(place_id INTEGER,visit_date INTEGER); INSERT INTO moz_places VALUES(1,'https://c.example','C'); INSERT INTO moz_historyvisits VALUES(1,1670000000000000);")
                db.commit()
            before = chrome.read_bytes()
            items, audit = collect({"chrome": chrome, "firefox": firefox})
            self.assertEqual(len(items), 3)
            self.assertEqual(len(audit[0]["sha256"]), 64)
            self.assertEqual(chrome.read_bytes(), before)
            self.assertTrue(all(x.time_utc.endswith("Z") for x in items))
            target = root / "timeline.json"
            export(items, audit, target, "json")
            self.assertEqual(len(json.loads(target.read_text())["timeline"]), 3)

    def test_html_escapes_untrusted_values(self):
        from artifacts import Artifact
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "out.html"
            export([Artifact("Chrome", "visit", "2026-01-01Z", "<script>alert(1)</script>")], [], target, "html")
            self.assertNotIn("<script>", target.read_text())


if __name__ == "__main__":
    unittest.main()

