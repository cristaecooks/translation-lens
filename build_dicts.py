#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalize every source dictionary into one compact format.

Each language ends up as data/lex-<code>.pickle holding:

    {"maxlen": int,
     "entries": {headword: [(reading, (gloss, ...), note), ...]}}

`reading` is the pronunciation the app shows (numeric pinyin for Chinese,
kana for Japanese, None where it's computed at runtime or unavailable) and
`note` carries the traditional form / part of speech.  `maxlen` is the longest
headword, used by the longest-match segmenter for languages without spaces.

Sources, all openly licensed:
  Chinese  CC-CEDICT                        (CC BY-SA 4.0)
  Japanese JMdict/EDICT, EDRDG              (CC BY-SA 4.0)
  Korean   English Wiktionary via kaikki.org (CC BY-SA 4.0)
  fr/es/it/de  WikDict, from Wiktionary      (CC BY-SA 4.0)
"""

import gzip
import json
import os
import pickle
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

MAX_GLOSSES = 6

#: JMdict priority codes.  The "1" tiers mean everyday vocabulary; the "2"
#: tiers are much weaker signals.
_PRI_WEIGHT = {"ichi1": 100, "news1": 60, "spec1": 60, "gai1": 40,
               "ichi2": 10, "news2": 5, "spec2": 5, "gai2": 3}
#: 薄 and 露 each have four readings in CC-CEDICT; leave headroom
MAX_ENTRIES_PER_WORD = 6


def out_path(code):
    return os.path.join(DATA, "lex-%s.pickle" % code)


def save(code, entries, extra=None):
    maxlen = 1
    for k in entries:
        if len(k) > maxlen:
            maxlen = len(k)
    trimmed = {k: v[:MAX_ENTRIES_PER_WORD] for k, v in entries.items()}
    blob = {"maxlen": min(maxlen, 16), "entries": trimmed}
    blob.update(extra or {})
    with open(out_path(code), "wb") as fh:
        pickle.dump(blob, fh, protocol=4)
    print("  %-3s %7d headwords -> %s" % (
        code, len(trimmed), os.path.basename(out_path(code))))


def add(entries, key, rec):
    if not key:
        return
    bucket = entries.setdefault(key, [])
    if rec not in bucket:
        bucket.append(rec)


# ------------------------------------------------------------- Chinese ---

CEDICT_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]*)\]\s+/(.*)/\s*$")

#: secondary pronunciations recorded inside a definition, e.g. "also pr. [...]"
_ALT_PR = re.compile(
    r"^(also|colloquial|coll\.?|Taiwan|old|dialectal|erhua)\s+pr\.\s*\[",
    re.I)


def build_syllable_map():
    """pinyin syllable -> characters guaranteed to be read as that syllable.

    Used to voice a *specific* reading of a homograph: speaking 薄 always
    gives the synthesizer's default (báo), so to demonstrate bó we hand it a
    character whose own default reading is bó.  A character therefore only
    qualifies if pypinyin agrees it reads that way, and candidates are ranked
    by jieba's word frequency so the stand-in is a common character.
    """
    import jieba
    import pypinyin
    jieba.setLogLevel(60)
    jieba.initialize()

    han = re.compile(r"^[一-鿿]$")
    ranked, top_freq = {}, {}
    for word, freq in jieba.dt.FREQ.items():
        if len(word) != 1 or not han.match(word):
            continue
        try:
            syl = pypinyin.pinyin(word, style=pypinyin.Style.TONE3,
                                  neutral_tone_with_five=True)[0][0].lower()
        except Exception:
            continue
        ranked.setdefault(syl, []).append((freq, word))

    out = {}
    for syl, cands in ranked.items():
        cands.sort(reverse=True)
        out[syl] = [c for _f, c in cands[:4]]
        top_freq[syl] = cands[0][0]

    # Neutral tone rarely has a character of its own, so fall back to the
    # commonest character sharing the base syllable — for ge5 that is 个,
    # which a synthesizer reads unstressed anyway.  Picking by frequency
    # matters: the lowest tone number would give 哥 (gē) instead.
    by_base = {}
    for syl in out:
        by_base.setdefault(syl.rstrip("12345"), []).append(syl)
    for base, sibling_syls in by_base.items():
        commonest = max(sibling_syls, key=lambda k: top_freq[k])
        for tone in "12345":
            out.setdefault(base + tone, out[commonest])
    return out


def build_chinese():
    entries = {}
    with open(os.path.join(DATA, "cedict.txt"), encoding="utf-8") as fh:
        for line in fh:
            if not line or line[0] == "#":
                continue
            m = CEDICT_RE.match(line.rstrip("\n"))
            if not m:
                continue
            trad, simp, pinyin, defs = m.groups()
            # Secondary pronunciations live in the definition list and are
            # usually last, so 那个's "also pr. [nei4 ge5]" fell off the end of
            # the cap.  Keep those notes whatever the cap, then fill up with
            # ordinary senses.
            all_defs = [d for d in defs.split("/") if d.strip()]
            alts = [d for d in all_defs if _ALT_PR.match(d.strip())]
            rest = [d for d in all_defs if not _ALT_PR.match(d.strip())]
            glosses = tuple(alts + rest[:MAX_GLOSSES])
            add(entries, simp, (pinyin, glosses, trad if trad != simp else None))
            if trad != simp:
                add(entries, trad, (pinyin, glosses, None))
    save("zh", entries, {"syllables": build_syllable_map()})


# ------------------------------------------------------------ Japanese ---

def build_japanese():
    path = os.path.join(DATA, "jmdict_e.gz")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        raw = fh.read()
    # JMdict tags senses with DTD entities (&n; &vs; …).  ElementTree has no
    # DTD, so flatten them to plain text before parsing.
    raw = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)([A-Za-z0-9-]+);", r"\1", raw)

    import xml.etree.ElementTree as ET
    ranked = {}
    root = ET.fromstring(raw)
    for entry in root.iter("entry"):
        kanji = [k.findtext("keb") for k in entry.findall("k_ele")]
        kana = [r.findtext("reb") for r in entry.findall("r_ele")]
        glosses, pos = [], []
        for sense in entry.findall("sense"):
            for g in sense.findall("gloss"):
                if g.text:
                    glosses.append(g.text)
            for p in sense.findall("pos"):
                if p.text and p.text not in pos:
                    pos.append(p.text)
        if not glosses or not kana:
            continue
        # Rank by JMdict's priority codes, scored per spelling/reading rather
        # than per entry — 入る is common as はいる, but that must not let its
        # rare いる reading outrank 居る under the key いる.
        def score_of(element, tag):
            total = 0
            for p in element.findall(tag):
                t = p.text or ""
                if t in _PRI_WEIGHT:
                    total += _PRI_WEIGHT[t]
                elif t.startswith("nf"):
                    # frequency bucket: nf01 is the most common, nf48 the least
                    try:
                        total += max(0, 49 - int(t[2:]))
                    except ValueError:
                        pass
            return total

        # "usually kana": if the word is normally written in kana then a kana
        # hit is very likely this entry.  Without it する leads with 擦る
        # "to rub" instead of 為る "to do".
        uk = any((m.text or "") == "uk" for m in entry.iter("misc"))

        glosses = tuple(glosses[:MAX_GLOSSES])
        note = ", ".join(pos[:2]) or None
        reading = kana[0]
        for k_ele in entry.findall("k_ele"):
            keb = k_ele.findtext("keb")
            ranked.setdefault(keb, []).append(
                (score_of(k_ele, "ke_pri"), (reading, glosses, note)))
        for r_ele in entry.findall("r_ele"):
            reb = r_ele.findtext("reb")
            ranked.setdefault(reb, []).append(
                (score_of(r_ele, "re_pri") + (80 if uk else 0),
                 (None if reb == reading else reading, glosses, note)))

    entries = {}
    for key, recs in ranked.items():
        recs.sort(key=lambda sr: -sr[0])
        for _score, rec in recs:
            add(entries, key, rec)
    save("ja", entries)


# -------------------------------------------------------------- Korean ---

HANGUL_RE = re.compile(r"[가-힣]")
_BAD_SENSE = re.compile(
    r"^(alternative (form|spelling)|synonym of|obsolete|archaic form|"
    r"romanization of|hanja form|hangul form|misspelling)", re.I)


def build_korean():
    path = os.path.join(DATA, "korean-en.jsonl")
    entries = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            word = d.get("word")
            if not word or not HANGUL_RE.search(word):
                continue
            glosses = []
            for sense in d.get("senses", []):
                for g in sense.get("glosses", []) or []:
                    if g and not _BAD_SENSE.match(g):
                        glosses.append(g)
            if not glosses:
                continue
            add(entries, word,
                (None, tuple(glosses[:MAX_GLOSSES]), d.get("pos") or None))
    save("ko", entries)


# ------------------------------------------------- French/Spanish/etc. ---

WIKDICT = {"fr": "wikdict-fr-en.sqlite3", "es": "wikdict-es-en.sqlite3",
           "it": "wikdict-it-en.sqlite3", "de": "wikdict-de-en.sqlite3",
           "pt": "wikdict-pt-en.sqlite3", "cs": "wikdict-cs-en.sqlite3",
           "tr": "wikdict-tr-en.sqlite3", "la": "wikdict-la-en.sqlite3"}


def build_wikdict(code):
    path = os.path.join(DATA, WIKDICT[code])
    con = sqlite3.connect(path)
    entries = {}
    # `translation` carries per-sense detail; fall back to the flattened table
    # for headwords it doesn't cover.
    # WikDict's `sense` column is a definition in the *source* language
    # ("der Geist einer Person, der sich selbst wahrnimmt"), which crowds out
    # the English glosses an English speaker actually wants.  Skip it.
    for word, trans in con.execute(
            "select written_rep, trans_list from translation "
            "where written_rep is not null and trans_list is not null "
            "order by coalesce(score, 0) desc"):
        glosses = tuple(t.strip() for t in trans.split(" | ") if t.strip())
        if not glosses:
            continue
        add(entries, word, (None, glosses[:MAX_GLOSSES], None))
    for word, trans in con.execute(
            "select written_rep, trans_list from simple_translation "
            "where written_rep is not null and trans_list is not null"):
        if word in entries:
            continue
        glosses = tuple(t.strip() for t in trans.split(" | ") if t.strip())
        if glosses:
            add(entries, word, (None, glosses[:MAX_GLOSSES], None))
    con.close()
    save(code, entries)


BUILDERS = {
    "zh": build_chinese,
    "ja": build_japanese,
    "ko": build_korean,
    "fr": lambda: build_wikdict("fr"),
    "es": lambda: build_wikdict("es"),
    "it": lambda: build_wikdict("it"),
    "de": lambda: build_wikdict("de"),
    "pt": lambda: build_wikdict("pt"),
    "cs": lambda: build_wikdict("cs"),
    "tr": lambda: build_wikdict("tr"),
    "la": lambda: build_wikdict("la"),
}


def main(argv):
    codes = argv[1:] or list(BUILDERS)
    print("building lexicons:")
    for code in codes:
        try:
            BUILDERS[code]()
        except Exception as exc:
            print("  %-3s FAILED: %s" % (code, exc))


if __name__ == "__main__":
    main(sys.argv)
