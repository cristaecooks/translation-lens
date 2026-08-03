#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Language packs for Translation Lens.

Each pack knows which languages to hand Vision, how to cut recognized text
into words, and how to look those words up.  A pack yields `Word` objects; the
UI renders them without caring which language produced them.

Lexicons are the normalized pickles written by build_dicts.py.
"""

import os
import pickle
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))

#: when frozen by PyInstaller the lexicons live in the bundle's temp tree
DATA = os.path.join(getattr(sys, "_MEIPASS", HERE), "data")

MAX_SENSES = 3

#: how many distinct pronunciations to list for one word (薄 has four)
MAX_READINGS = 4


class Reading(object):
    """One pronunciation of a word, and how to make a synthesizer say it."""
    __slots__ = ("parts", "label", "speech")

    def __init__(self, parts, label=None, speech=None):
        self.parts = parts        # [(text, tone_or_kind)] shown to the reader
        self.label = label        # "also", "Taiwan", … for secondary readings
        self.speech = speech      # text to hand the synthesizer, or None


class Entry(object):
    """One dictionary sense-group for a word."""
    __slots__ = ("headword", "readings", "glosses", "note")

    def __init__(self, headword, readings, glosses, note=None):
        self.headword = headword
        self.readings = readings        # [Reading]
        self.glosses = glosses
        self.note = note


class Word(object):
    """A token from the page plus whatever the dictionary knows about it."""
    __slots__ = ("surface", "entries")

    def __init__(self, surface, entries):
        self.surface = surface
        self.entries = entries


# =========================================================== romanization ===

_ONSET = "ᄀᄁᄂᄃᄄᄅᄆᄇᄈᄉᄊᄋᄌᄍᄎᄏᄐᄑᄒ"
_VOWEL_ROM = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae",
              "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
_ONSET_ROM = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "",
              "j", "jj", "ch", "k", "t", "p", "h"]

#: final index -> (kept jamo, jamo that moves on liaison)
_FINAL_SPLIT = [
    (None, None), ("ㄱ", None), ("ㄲ", None), ("ㄱ", "ㅅ"), ("ㄴ", None),
    ("ㄴ", "ㅈ"), ("ㄴ", "ㅎ"), ("ㄷ", None), ("ㄹ", None), ("ㄹ", "ㄱ"),
    ("ㄹ", "ㅁ"), ("ㄹ", "ㅂ"), ("ㄹ", "ㅅ"), ("ㄹ", "ㅌ"), ("ㄹ", "ㅍ"),
    ("ㄹ", "ㅎ"), ("ㅁ", None), ("ㅂ", None), ("ㅂ", "ㅅ"), ("ㅅ", None),
    ("ㅆ", None), ("ㅇ", None), ("ㅈ", None), ("ㅊ", None), ("ㅋ", None),
    ("ㅌ", None), ("ㅍ", None), ("ㅎ", None),
]
_CODA_ROM = {"ㄱ": "k", "ㄲ": "k", "ㄴ": "n", "ㄷ": "t", "ㄹ": "l", "ㅁ": "m",
             "ㅂ": "p", "ㅅ": "t", "ㅆ": "t", "ㅇ": "ng", "ㅈ": "t", "ㅊ": "t",
             "ㅋ": "k", "ㅌ": "t", "ㅍ": "p", "ㅎ": "t"}
_MOVED_ROM = {"ㄱ": "g", "ㄲ": "kk", "ㄴ": "n", "ㄷ": "d", "ㄹ": "r", "ㅁ": "m",
              "ㅂ": "b", "ㅅ": "s", "ㅆ": "ss", "ㅇ": "ng", "ㅈ": "j",
              "ㅊ": "ch", "ㅋ": "k", "ㅌ": "t", "ㅍ": "p", "ㅎ": ""}
#: coda + following onset -> (new coda, new onset), the common assimilations
_ASSIM = {
    ("ㄱ", "n"): ("ng", "n"), ("ㄱ", "m"): ("ng", "m"),
    ("ㄷ", "n"): ("n", "n"), ("ㄷ", "m"): ("n", "m"),
    ("ㅂ", "n"): ("m", "n"), ("ㅂ", "m"): ("m", "m"),
    ("ㅅ", "n"): ("n", "n"), ("ㅆ", "n"): ("n", "n"),
    ("ㄴ", "r"): ("l", "l"), ("ㄹ", "n"): ("l", "l"),
    ("ㄱ", "r"): ("ng", "n"), ("ㅁ", "r"): ("m", "n"),
    ("ㅇ", "r"): ("ng", "n"),
}

HANGUL_RE = re.compile(r"[가-힣]")


def romanize_korean(text):
    """Hangul -> Revised Romanization.

    Covers syllable decomposition, liaison onto a following silent ㅇ, and the
    frequent consonant assimilations.  Rarer sandhi is not modelled, so treat
    the output as a pronunciation hint rather than gospel.
    """
    syls = []
    for ch in text:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3:
            c = o - 0xAC00
            syls.append([c // 588, (c % 588) // 28, c % 28])
        else:
            syls.append(ch)

    out = []
    for i, s in enumerate(syls):
        if not isinstance(s, list):
            out.append(s)
            continue
        onset = _ONSET_ROM[s[0]]
        vowel = _VOWEL_ROM[s[1]]
        kept, movable = _FINAL_SPLIT[s[2]]
        coda = _CODA_ROM.get(kept, "") if kept else ""

        nxt = syls[i + 1] if i + 1 < len(syls) else None
        if isinstance(nxt, list) and s[2]:
            if nxt[0] == 11:                      # next starts with silent ㅇ
                if movable:
                    nxt.append(_MOVED_ROM.get(movable, ""))
                else:
                    nxt.append(_MOVED_ROM.get(kept, ""))
                    coda = ""
            else:
                key = (kept, _ONSET_ROM[nxt[0]])
                if key in _ASSIM:
                    coda, forced = _ASSIM[key]
                    nxt.append(forced)
        if len(s) > 3:                            # onset supplied by liaison
            onset = s[3]
        out.append(onset + vowel + coda)
    return "".join(out)


_KANA = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "wi", "ゑ": "we", "を": "wo", "ん": "n",
    "ゔ": "vu", "ー": "",
}
_KANA_DIGRAPH = {}
for _base, _pre in (("き", "ky"), ("ぎ", "gy"), ("し", "sh"), ("じ", "j"),
                    ("ち", "ch"), ("に", "ny"), ("ひ", "hy"), ("び", "by"),
                    ("ぴ", "py"), ("み", "my"), ("り", "ry")):
    for _small, _v in (("ゃ", "a"), ("ゅ", "u"), ("ょ", "o")):
        _KANA_DIGRAPH[_base + _small] = (_pre + _v if _pre.endswith(("h", "j"))
                                         else _pre + _v)

VOWELS = "aeiou"


def romaji(kana):
    """Kana -> Hepburn romaji."""
    if not kana:
        return ""
    # katakana share the hiragana layout one block up
    s = "".join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c
                for c in kana)
    out = []
    i = 0
    while i < len(s):
        pair = s[i:i + 2]
        if pair in _KANA_DIGRAPH:
            out.append(_KANA_DIGRAPH[pair])
            i += 2
            continue
        ch = s[i]
        if ch == "っ":                              # gemination
            nxt = s[i + 1:i + 2]
            r = _KANA_DIGRAPH.get(s[i + 1:i + 3]) or _KANA.get(nxt, "")
            if r:
                out.append("t" if r[0] in VOWELS else r[0])
            i += 1
            continue
        if ch == "ー" and out and out[-1] and out[-1][-1] in VOWELS:
            out.append(out[-1][-1])
            i += 1
            continue
        r = _KANA.get(ch)
        if r is None:
            out.append(ch)
        else:
            if r == "n" and s[i + 1:i + 2] and (
                    _KANA.get(s[i + 1:i + 2], "z")[0] in VOWELS
                    or s[i + 1:i + 2] in "やゆよ"):
                r = "n'"
            out.append(r)
        i += 1
    return "".join(out)


# ================================================================= packs ===

CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
KANA_RE = re.compile(r"[぀-ゟ゠-ヿ]")
WORD_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", re.UNICODE)

#: letters that carry no combining mark to strip, so NFD can't fold them
_FOLD_EXTRA = str.maketrans({"ı": "i", "İ": "i", "ł": "l", "Ł": "l",
                             "ø": "o", "Ø": "o", "đ": "d", "Đ": "d",
                             "ß": "ss", "æ": "ae", "œ": "oe"})


def fold_diacritics(text):
    """'Příliš' and 'Prílis' both become 'prilis'."""
    text = text.translate(_FOLD_EXTRA)
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text
                   if not unicodedata.combining(c)).lower()


class Language(object):
    code = ""
    label = ""
    native = ""
    ocr_langs = ()
    #: BCP-47 tag for the Windows OCR engine, which covers more languages
    #: than Vision does — Czech and Turkish natively, and possibly Hindi
    ocr_win = None
    vertical_ok = False       # try the vertical-column reflow for this script
    strip_stray_latin = False
    font_name = None          # face used for headwords; None = system font
    tts_lang = None           # BCP-47 tag for the speech voice

    def __init__(self):
        self.entries = {}
        self.maxlen = 1
        self.syllables = {}
        self.ready = False

    # -- lexicon --------------------------------------------------------

    def load(self):
        if self.ready:
            return
        path = os.path.join(DATA, "lex-%s.pickle" % self.code)
        with open(path, "rb") as fh:
            blob = pickle.load(fh)
        self.entries = blob["entries"]
        self.maxlen = blob["maxlen"]
        self.syllables = blob.get("syllables", {})
        self.ready = True

    def has_script(self, text):
        return bool(WORD_RE.search(text))

    # -- overridden per language ---------------------------------------

    def readings_for(self, headword, raw_reading):
        """-> [Reading] for this dictionary record."""
        parts = [(raw_reading, None)] if raw_reading else []
        return [Reading(parts, speech=headword)]

    def clean_gloss(self, gloss):
        return gloss

    def make_entries(self, headword, records):
        out = []
        for reading, glosses, note in records:
            out.append(Entry(headword, self.readings_for(headword, reading),
                             list(glosses)[:MAX_SENSES], note))
        return out

    def words(self, text):
        raise NotImplementedError


class SpacedLanguage(Language):
    """Languages that put spaces between words."""

    lemma_lang = None
    #: Vision has no recognizer for Czech or Turkish, so their text is read
    #: with a different Latin-script model and the diacritics come back wrong
    #: (Příliš -> Prílis, şaşırdım -> sasirdim).  Matching on a diacritic-free
    #: form of both the text and the dictionary recovers those words.
    fold_lookup = False

    def load(self):
        Language.load(self)
        if self.fold_lookup and not getattr(self, "folded", None):
            # Several words fold to the same form (Czech čem/cem), so keep
            # every candidate.  The lemmatizer's own word list is folded in
            # too: inflected forms like čem are not dictionary headwords, so
            # without it a de-accented čem could never be traced back to co.
            self.folded = {}

            def remember(word):
                bucket = self.folded.setdefault(fold_diacritics(word), [])
                if word not in bucket and len(bucket) < 4:
                    bucket.append(word)

            for key in self.entries:
                remember(key)
            try:
                from simplemma.strategies.dictionaries import (
                    DefaultDictionaryFactory)
                for key in DefaultDictionaryFactory().get_dictionary(
                        self.lemma_lang):
                    remember(key)
            except Exception:
                pass

    def has_script(self, text):
        return bool(WORD_RE.search(text))

    def candidates(self, token):
        """Surface form first — inflected forms are often entries themselves."""
        seen = []

        def add(word):
            if word and word not in seen:
                seen.append(word)

        add(token)
        add(token.lower())
        add(token.capitalize())

        # forms worth lemmatizing: the token, plus any accented spelling
        # recovered from a de-accented OCR reading
        bases = [token, token.lower()]
        if self.fold_lookup:
            for real in getattr(self, "folded", {}).get(
                    fold_diacritics(token), []):
                add(real)
                bases.append(real)

        if self.lemma_lang:
            try:
                import simplemma
                for base in bases:
                    add(simplemma.lemmatize(base, lang=self.lemma_lang))
            except Exception:
                pass
        return seen

    def words(self, text):
        """Merge every candidate form rather than taking the first hit.

        A surface form is often a real but rarer homograph of what was meant —
        German "Ich" is a noun ("self") while "ich" is the pronoun, Spanish
        "sé" is an interjection as well as "I know" — so showing the surface
        and lemma senses together beats guessing between them.
        """
        out = []
        for token in WORD_RE.findall(text):
            entries, seen = [], set()
            for cand in self.candidates(token):
                for reading, glosses, note in self.entries.get(cand, ()):
                    if glosses in seen:
                        continue
                    seen.add(glosses)
                    entry = Entry(cand, self.readings_for(cand, reading),
                                  list(glosses)[:MAX_SENSES], note)
                    if cand != token:
                        entry.note = ("%s · %s" % (cand, note)) if note else cand
                    entries.append(entry)
                if len(entries) >= 3:
                    break
            out.append(Word(token, entries[:3]))
        return out


class CJKLanguage(Language):
    """No spaces — segment by longest match against the lexicon."""

    vertical_ok = True
    strip_stray_latin = True

    def has_script(self, text):
        return bool(CJK_RE.search(text) or KANA_RE.search(text))

    def is_script(self, ch):
        return bool(CJK_RE.match(ch) or KANA_RE.match(ch))

    def deinflect(self, token):
        return ()

    def longest_match(self, text):
        out = []
        i, n = 0, len(text)
        while i < n:
            if not self.is_script(text[i]):
                i += 1
                continue
            hit = None
            for L in range(min(self.maxlen, n - i), 0, -1):
                cand = text[i:i + L]
                if cand in self.entries:
                    hit = (cand, cand)
                    break
                for base in self.deinflect(cand):
                    if base in self.entries:
                        hit = (cand, base)
                        break
                if hit:
                    break
            if hit is None:
                out.append(Word(text[i], []))
                i += 1
            else:
                surface, base = hit
                entries = self.make_entries(base, self.entries[base])
                if base != surface:
                    for e in entries:
                        e.note = ("from %s" % base) if not e.note else \
                            "%s · from %s" % (e.note, base)
                out.append(Word(surface, entries))
                i += len(surface)
        return out

    def words(self, text):
        return self.longest_match(text)


# --------------------------------------------------------------- Chinese ---

_TONE_VOWELS = {"a": "āáǎàa", "o": "ōóǒòo", "e": "ēéěèe",
                "i": "īíǐìi", "u": "ūúǔùu", "ü": "ǖǘǚǜü"}
_SYL_RE = re.compile(r"^([a-zA-ZüÜ:]+)([1-5])$")
_SYL_SCAN = re.compile(r"[a-zA-ZüÜ:]+[1-5]")


def numeric_to_marks(syllable):
    """'hao3' -> ('hǎo', 3)"""
    s = syllable.strip()
    if not s:
        return "", 5
    m = _SYL_RE.match(s)
    if not m:
        return s.replace("u:", "ü").replace("U:", "Ü"), 5
    body, tone = m.group(1), int(m.group(2))
    body = (body.replace("u:", "ü").replace("U:", "Ü")
                .replace("v", "ü").replace("V", "Ü"))
    if tone == 5:
        return body, 5
    low = body.lower()
    idx = -1
    for pref in ("a", "o", "e"):
        if pref in low:
            idx = low.index(pref)
            break
    if idx < 0:
        for i in range(len(low) - 1, -1, -1):
            if low[i] in "iuü":
                idx = i
                break
    if idx < 0:
        return body, tone
    marked = _TONE_VOWELS[low[idx]][tone - 1]
    if body[idx].isupper():
        marked = marked.upper()
    return body[:idx] + marked + body[idx + 1:], tone


def split_pinyin(numeric):
    out = []
    for tok in (numeric or "").split():
        out.append((tok, 5) if tok in ("·", "-", ",") else numeric_to_marks(tok))
    return out


#: CC-CEDICT records secondary pronunciations inside the definition text,
#: e.g. "also pr. [nei4 ge5]" or "Taiwan pr. [xi2]".  Alternate *spellings*
#: ("also written ...") and cross-references ("see ...") are deliberately not
#: matched — they are not readings of this word.
_ALT_PR = re.compile(
    r"^(also|colloquial|coll\.?|Taiwan|old|dialectal|erhua)\s+pr\.\s*\[([^\]]+)\]",
    re.I)


def _norm_py(p):
    return (p or "").lower().replace("u:", "v").replace(" ", "")


class Chinese(CJKLanguage):
    code, label, native = "zh", "Chinese", "中文"
    ocr_langs = ("zh-Hans", "zh-Hant")
    ocr_win = "zh-Hans-CN"
    font_name = "PingFangSC-Semibold"
    tts_lang = "zh-CN"

    def clean_gloss(self, gloss):
        """CC-CEDICT writes embedded pronunciations numerically ([zhi1dao5]);
        show them with tone marks like everything else."""
        def marks(m):
            return "[" + " ".join(numeric_to_marks(s)[0]
                                  for s in _SYL_SCAN.findall(m.group(1))) + "]"
        return re.sub(r"\[([a-zA-Z0-9\u00fc\u00dc:\s]+)\]",
                      lambda m: marks(m) if _SYL_SCAN.search(m.group(1))
                      else m.group(0), gloss.strip())

    def readings_for(self, headword, raw_reading):
        return [Reading(split_pinyin(raw_reading), speech=headword)]

    def default_reading(self, word):
        """The reading a synthesizer will use if simply handed `word`."""
        try:
            import pypinyin
            return _norm_py("".join(
                s[0] for s in pypinyin.pinyin(word, style=pypinyin.Style.TONE3,
                                              neutral_tone_with_five=True)))
        except Exception:
            return None

    def stand_in(self, reading, headword):
        """Characters a synthesizer reads as exactly `reading`.

        Speaking 薄 always produces the default báo, so to voice bó we hand
        the synthesizer a character whose own default reading is bó.  Returns
        None when no stand-in exists, or when the only one is the headword
        itself — better no audio than the wrong reading.
        """
        chars = []
        for syl in (reading or "").split():
            cands = self.syllables.get(syl.lower())
            if not cands:
                return None
            chars.append(cands[0])
        text = "".join(chars)
        return text if text and text != headword else None

    def speech_for_reading(self, headword, reading, default):
        if default is not None and _norm_py(reading) == default:
            return headword          # the synthesizer says this one unaided
        return self.stand_in(reading, headword)

    def rank(self, word, records):
        """CC-CEDICT orders homographs arbitrarily; pypinyin knows which
        reading is actually common, so 說 leads with shuō not shuì."""
        if len(records) < 2:
            return records
        want = self.default_reading(word)
        if want is None:
            return records

        def rank_key(rec):
            gloss = (rec[1][0] if rec[1] else "").lower()
            dull = gloss.startswith("surname ") or gloss.startswith("see ")
            return (0 if _norm_py(rec[0]) == want else 1, 1 if dull else 0)

        return sorted(records, key=rank_key)

    def make_entries(self, headword, records):
        """Show every pronunciation the dictionary records.

        CC-CEDICT splits some homographs into separate entries (觉 jiào / jué)
        but buries others in the definition text as "also pr. [...]" — 那个 is
        one entry, [na4 ge5], with nèige tucked in as its last gloss.  Those
        get promoted onto the reading line so both readings are visible.
        """
        out, seen = [], set()
        default = self.default_reading(headword)
        for reading, glosses, trad in self.rank(headword, records):
            key = _norm_py(reading)
            # Keyed on the sense too, not just the reading: 薄 has separate
            # entries for Bó "surname" and bó "meager" at the same pinyin, and
            # deduping on pinyin alone threw away the commoner meaning.
            sense_key = (key, (glosses[0].lower() if glosses else ""))
            if sense_key in seen:
                continue
            seen.add(sense_key)

            readings = [Reading(split_pinyin(reading),
                                speech=self.speech_for_reading(
                                    headword, reading, default))]
            kept = []
            for gloss in glosses:
                m = _ALT_PR.match(gloss.strip())
                if m and _norm_py(m.group(2)) != key:
                    alt = m.group(2)
                    readings.append(Reading(
                        split_pinyin(alt),
                        label=m.group(1).lower().rstrip("."),
                        speech=self.speech_for_reading(headword, alt, default)))
                else:
                    kept.append(gloss)

            # The stand-in machinery leans on pypinyin to guess what the voice
            # will say unaided, and the two occasionally disagree (pypinyin
            # calls 谁 shuí, most voices say shéi).  So the leading reading
            # always falls back to the word itself: some audio for the
            # commonest reading beats none.
            if not out and readings and readings[0].speech is None:
                readings[0].speech = headword

            out.append(Entry(headword, readings, kept[:MAX_SENSES], trad))
            if len(out) == MAX_READINGS:
                break
        return out

    def words(self, text):
        """jieba knows phrases longest-match misses (不知道), but it is trained
        on simplified and glues traditional characters together (喜歡貓), so
        anything it invents gets repaired by longest match."""
        try:
            import jieba
            tokens = [t for t in jieba.cut(text) if self.has_script(t)]
        except Exception:
            return self.longest_match(text)

        # jieba also splits traditional words it doesn't know into two words
        # that both happen to be real (聽說 -> 聽 + 說).  The repair pass below
        # can't see that, because each half looks fine on its own — so first
        # re-join neighbours whose combined form is itself a headword.
        merged, i = [], 0
        while i < len(tokens):
            joined = None
            for j in range(min(len(tokens), i + 4), i + 1, -1):
                cand = "".join(tokens[i:j])
                if len(cand) <= self.maxlen and cand in self.entries:
                    joined = (cand, j)
                    break
            if joined:
                merged.append(joined[0])
                i = joined[1]
            else:
                merged.append(tokens[i])
                i += 1

        out = []
        for token in merged:
            if token in self.entries:
                out.append(Word(token, self.make_entries(token,
                                                         self.entries[token])))
            else:
                out.extend(self.longest_match(token))
        return out


# -------------------------------------------------------------- Japanese ---

#: crude deinflection: (suffix seen, suffix to try instead)
_JA_RULES = (
    ("しました", "する"), ("します", "する"), ("しません", "する"),
    ("ました", "ます"), ("ません", "ます"), ("ます", "る"),
    ("ています", "る"), ("ている", "る"), ("てる", "る"), ("ていた", "る"),
    ("なかった", "ない"), ("ください", "くださる"),
    ("かった", "い"), ("くない", "い"), ("くて", "い"),
    ("った", "る"), ("った", "う"), ("った", "つ"),
    ("んだ", "む"), ("んだ", "ぶ"), ("んだ", "ぬ"),
    ("いた", "く"), ("いだ", "ぐ"), ("した", "す"),
    ("って", "る"), ("って", "う"), ("って", "つ"),
    ("んで", "む"), ("んで", "ぶ"), ("いて", "く"), ("いで", "ぐ"),
    ("ない", "る"), ("たい", "る"), ("れば", "る"), ("られる", "る"),
    ("せる", "す"), ("た", "る"), ("て", "る"), ("だ", "る"),
)


class Japanese(CJKLanguage):
    code, label, native = "ja", "Japanese", "日本語"
    ocr_langs = ("ja-JP",)
    ocr_win = "ja-JP"
    tts_lang = "ja-JP"
    font_name = "HiraginoSans-W6"

    def deinflect(self, token):
        out = []
        for suffix, replacement in _JA_RULES:
            if len(token) > len(suffix) and token.endswith(suffix):
                out.append(token[:-len(suffix)] + replacement)
        return out

    def readings_for(self, headword, raw_reading):
        """Speak the kana, not the kanji: synthesizers guess wrong readings
        for kanji homographs, but kana pins the pronunciation exactly."""
        kana = raw_reading or (headword if KANA_RE.search(headword) else "")
        if not kana:
            return [Reading([], speech=headword)]
        parts = [(kana, None)] if kana != headword else []
        r = romaji(kana)
        if r:
            parts.append((r, "romaji"))
        return [Reading(parts, speech=kana)]


# ---------------------------------------------------------------- Korean ---

#: particles and endings to peel off when the whole token isn't a headword
_KO_SUFFIXES = (
    "에서는", "으로는", "이라고", "에게서", "께서는", "에서", "에게", "한테",
    "부터", "까지", "으로", "이나", "이란", "라고", "처럼", "보다", "마다",
    "께서", "이는", "은", "는", "이", "가", "을", "를", "에", "의", "도",
    "만", "과", "와", "로", "야", "아", "여",
)


class Korean(Language):
    code, label, native = "ko", "Korean", "한국어"
    ocr_langs = ("ko-KR",)
    ocr_win = "ko-KR"
    tts_lang = "ko-KR"
    font_name = "AppleSDGothicNeo-Bold"
    strip_stray_latin = True

    def has_script(self, text):
        return bool(HANGUL_RE.search(text))

    def readings_for(self, headword, raw_reading):
        rom = romanize_korean(headword)
        return [Reading([(rom, None)] if rom else [], speech=headword)]

    def lookup_token(self, token):
        """Korean glues particles and endings onto stems, so try the token,
        then shorter prefixes, then the prefix as a verb stem (+다)."""
        if token in self.entries:
            return token
        for suffix in _KO_SUFFIXES:
            if token.endswith(suffix) and len(token) > len(suffix):
                stem = token[:-len(suffix)]
                if stem in self.entries:
                    return stem
        for i in range(len(token) - 1, 0, -1):
            stem = token[:i]
            if stem + "다" in self.entries:
                return stem + "다"
            if stem in self.entries:
                return stem
        return None

    def words(self, text):
        out = []
        for token in re.findall(r"[가-힣]+|[^\s가-힣]+", text):
            if not HANGUL_RE.search(token):
                continue
            hit = self.lookup_token(token)
            if hit is None:
                out.append(Word(token, [Entry(token,
                                              self.readings_for(token, None),
                                              [], None)]))
                continue
            entries = self.make_entries(hit, self.entries[hit])
            for e in entries:
                e.readings = self.readings_for(token, None)
                if hit != token:
                    e.note = ("%s · %s" % (hit, e.note)) if e.note else hit
            out.append(Word(token, entries))
        return out


# ------------------------------------------------------------- European ---

class French(SpacedLanguage):
    code, label, native, lemma_lang = "fr", "French", "Français", "fr"
    ocr_langs = ("fr-FR",)
    ocr_win = "fr-FR"
    tts_lang = "fr-FR"


class Spanish(SpacedLanguage):
    code, label, native, lemma_lang = "es", "Spanish", "Español", "es"
    ocr_langs = ("es-ES",)
    ocr_win = "es-ES"
    tts_lang = "es-ES"


class Italian(SpacedLanguage):
    code, label, native, lemma_lang = "it", "Italian", "Italiano", "it"
    ocr_langs = ("it-IT",)
    ocr_win = "it-IT"
    tts_lang = "it-IT"


class German(SpacedLanguage):
    code, label, native, lemma_lang = "de", "German", "Deutsch", "de"
    ocr_langs = ("de-DE",)
    ocr_win = "de-DE"
    tts_lang = "de-DE"


class Portuguese(SpacedLanguage):
    code, label, native, lemma_lang = "pt", "Portuguese", "Português", "pt"
    ocr_langs = ("pt-BR",)
    ocr_win = "pt-BR"
    tts_lang = "pt-BR"


class Czech(SpacedLanguage):
    code, label, native, lemma_lang = "cs", "Czech", "Čeština", "cs"
    ocr_langs = ("en-US",)          # Vision has no Czech recognizer
    ocr_win = "cs-CZ"               # Windows OCR does have one
    tts_lang = "cs-CZ"
    fold_lookup = True


class Turkish(SpacedLanguage):
    code, label, native, lemma_lang = "tr", "Turkish", "Türkçe", "tr"
    ocr_langs = ("en-US",)          # Vision has no Turkish recognizer
    ocr_win = "tr-TR"               # Windows OCR does have one
    tts_lang = "tr-TR"
    fold_lookup = True


class Latin(SpacedLanguage):
    code, label, native, lemma_lang = "la", "Latin", "Latina", "la"
    ocr_langs = ("en-US",)
    ocr_win = "en-US"
    tts_lang = None                 # macOS ships no Latin voice


LANGUAGES = [Chinese(), Japanese(), Korean(), French(), Spanish(),
             Italian(), German(), Portuguese(), Czech(), Turkish(), Latin()]
BY_CODE = {l.code: l for l in LANGUAGES}


def get(code):
    return BY_CODE.get(code, BY_CODE["zh"])
