"""Extract browser history and downloads into a normalized timeline."""
from __future__ import annotations

import argparse
from contextlib import closing
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile


@dataclass(frozen=True)
class Artifact:
    browser: str
    kind: str
    time_utc: str
    url: str
    title: str = ""
    target: str = ""


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def chrome_time(micros: int) -> str:
    return utc(datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=micros))


def firefox_time(micros: int) -> str:
    return utc(datetime.fromtimestamp(micros / 1_000_000, tz=timezone.utc))


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def has_table(db: sqlite3.Connection, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def extract_chrome(db: sqlite3.Connection) -> list[Artifact]:
    rows = []
    if has_table(db, "urls") and has_table(db, "visits"):
        for url, title, stamp in db.execute("SELECT u.url, COALESCE(u.title,''), v.visit_time FROM visits v JOIN urls u ON u.id=v.url WHERE v.visit_time>0"):
            rows.append(Artifact("Chrome", "visit", chrome_time(stamp), url, title))
    if has_table(db, "downloads"):
        cols = {r[1] for r in db.execute("PRAGMA table_info(downloads)")}
        target = "target_path" if "target_path" in cols else "current_path" if "current_path" in cols else "''"
        source = "tab_url" if "tab_url" in cols else "''"
        for url, path, stamp in db.execute(f"SELECT {source}, {target}, start_time FROM downloads WHERE start_time>0"):
            rows.append(Artifact("Chrome", "download", chrome_time(stamp), url or "", target=path or ""))
    return rows


def extract_firefox(db: sqlite3.Connection) -> list[Artifact]:
    rows = []
    if has_table(db, "moz_places") and has_table(db, "moz_historyvisits"):
        for url, title, stamp in db.execute("SELECT p.url, COALESCE(p.title,''), v.visit_date FROM moz_historyvisits v JOIN moz_places p ON p.id=v.place_id WHERE v.visit_date>0"):
            rows.append(Artifact("Firefox", "visit", firefox_time(stamp), url, title))
    if has_table(db, "moz_annos") and has_table(db, "moz_anno_attributes") and has_table(db, "moz_places"):
        query = "SELECT p.url, a.content, a.dateAdded FROM moz_annos a JOIN moz_anno_attributes n ON n.id=a.anno_attribute_id JOIN moz_places p ON p.id=a.place_id WHERE n.name='downloads/destinationFileURI' AND a.dateAdded>0"
        for url, target, stamp in db.execute(query):
            rows.append(Artifact("Firefox", "download", firefox_time(stamp), url, target=target or ""))
    return rows


def collect(sources: dict[str, Path]) -> tuple[list[Artifact], list[dict[str, str]]]:
    items, audit = [], []
    with tempfile.TemporaryDirectory() as directory:
        for browser, path in sources.items():
            path = Path(path)
            before = digest(path)
            copy = Path(directory) / f"{browser}.sqlite"
            shutil.copyfile(path, copy)
            if digest(copy) != before:
                raise OSError(f"Source changed during copy: {path}")
            audit.append({"browser": browser, "source": str(path), "sha256": before})
            with closing(sqlite3.connect(f"file:{copy.as_posix()}?mode=ro", uri=True)) as db:
                items.extend(extract_chrome(db) if browser == "chrome" else extract_firefox(db))
    return sorted(items, key=lambda a: (a.time_utc, a.browser, a.kind)), audit


def export(items: list[Artifact], audit: list[dict[str, str]], output: Path, format: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if format == "json":
        output.write_text(json.dumps({"sources": audit, "timeline": [asdict(a) for a in items]}, indent=2), encoding="utf-8")
    elif format == "csv":
        with output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(Artifact.__dataclass_fields__))
            writer.writeheader()
            writer.writerows(asdict(a) for a in items)
    else:
        cells = lambda values: "<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in values) + "</tr>"
        header = "".join(f"<th>{html.escape(x)}</th>" for x in Artifact.__dataclass_fields__)
        body = "".join(cells(asdict(a).values()) for a in items)
        output.write_text(f"<!doctype html><meta charset='utf-8'><title>Browser timeline</title><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", type=Path)
    parser.add_argument("--firefox", type=Path)
    parser.add_argument("--format", choices=["json", "csv", "html"], default="json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = {name: path for name in ("chrome", "firefox") if (path := getattr(args, name))}
    if not sources:
        parser.error("provide --chrome or --firefox")
    timeline, provenance = collect(sources)
    export(timeline, provenance, args.output, args.format)
    print(f"Exported {len(timeline)} artifacts from {len(provenance)} source(s)")

