#!/bin/bash
# Re-download the raw dictionary sources, then rebuild the lexicons.
#
# The raw files are ~290 MB and only needed at build time — build_dicts.py
# turns them into the small data/lex-*.pickle files the app actually loads,
# so they are deleted afterwards.  Run this again to refresh the dictionaries.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="$DIR/data"
WIKDICT="https://download.wikdict.com/dictionaries/sqlite/2_2026-06"
mkdir -p "$DATA"

echo "fetching sources…"
curl -L --fail -o "$DATA/cedict.txt.gz" \
  "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"
gunzip -f "$DATA/cedict.txt.gz"

curl -L --fail -o "$DATA/jmdict_e.gz" "http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz"

curl -L --fail -o "$DATA/korean-en.jsonl" \
  "https://kaikki.org/dictionary/Korean/kaikki.org-dictionary-Korean.jsonl"

for p in fr es it de pt cs tr la; do
  curl -L --fail -o "$DATA/wikdict-$p-en.sqlite3" "$WIKDICT/$p-en.sqlite3"
done

echo "building lexicons…"
"$DIR/.venv/bin/python" "$DIR/build_dicts.py"

echo "removing raw sources…"
rm -f "$DATA/korean-en.jsonl" "$DATA/jmdict_e.gz" "$DATA"/wikdict-*.sqlite3
echo "done — data/ is now $(du -sh "$DATA" | cut -f1)"
