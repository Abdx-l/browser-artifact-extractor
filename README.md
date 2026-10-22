# Browser Artifact Extractor

Read Chrome and Firefox history and download records from local SQLite profiles. The CLI copies each database before querying it, records its SHA-256 digest, normalizes timestamps to UTC, and exports a merged timeline as JSON, CSV, or HTML.

```sh
python artifacts.py --chrome path/to/History --firefox path/to/places.sqlite --format json --output timeline.json
python -m unittest discover -s tests -v
```

Either browser path may be omitted. The input profiles are opened only to copy their bytes; queries run against temporary copies. The output includes visited URLs and download paths, so treat exported timelines as private data.

