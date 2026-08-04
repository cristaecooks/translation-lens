# Translation Lens (macOS)

### [⬇ Download Translation Lens](https://github.com/cristaecooks/Translation-Lens-MacOS/releases/latest)

Requires **macOS 12 or later** on **Apple silicon** (M1/M2/M3/M4). 50 MB.

Open the `.dmg` and **drag the app into your Applications folder** — don't run
it from the disk image, or macOS won't remember its Screen Recording
permission. On first launch macOS will say it "cannot verify" the app because
it isn't notarized: choose Cancel, then System Settings → Privacy & Security →
**Open Anyway**. Full steps are in `READ ME.pdf` inside the download.

---

A small always-on-top window for reading comics in another language. Drag
the frame over a word or a whole speech bubble, let go, and it reads what's
underneath: **pronunciation plus dictionary definitions.**

Eleven languages, picked from the globe button in the title bar:

| | Pronunciation shown | Spoken | Dictionary |
| --- | --- | --- | --- |
| Chinese (Mandarin) | pinyin, color-coded by tone | yes | CC-CEDICT, 198k words |
| Japanese | kana + romaji | yes | JMdict, 464k |
| Korean | Revised Romanization | yes | Wiktionary, 33k |
| French | — | yes | Wiktionary, 163k |
| German | — | yes | Wiktionary, 144k |
| Spanish | — | yes | Wiktionary, 97k |
| Italian | — | yes | Wiktionary, 71k |
| Portuguese | — | yes | Wiktionary, 67k |
| Czech | — | yes | Wiktionary, 49k |
| Turkish | — | yes | Wiktionary, 42k |
| Latin | — | no voice on macOS | Wiktionary, 24k |

Chinese reads both simplified and traditional. Latin shows definitions only,
because macOS ships no Latin voice.

Every word gets a 🔈 speaker icon — click it to hear the word in a native
voice. Your choice of language is remembered between launches, along with the frame
size and color theme. Everything runs offline on your Mac.

## First run

1. Open the `.dmg` and **drag Translation Lens into your Applications folder.**
   Don't run it from the disk image: that volume is read-only and its path
   changes each time it mounts, so macOS cannot remember the permission below
   and the app will keep asking for it.
2. macOS will ask for **Screen Recording** permission. Grant it:
   System Settings → Privacy & Security → Screen & System Audio Recording →
   switch on *Translation Lens*.
3. **Quit and reopen the app.** macOS only applies the permission on relaunch.

That permission is the whole trick — it's what lets the lens see the page
sitting underneath it. Nothing is uploaded anywhere; OCR and the dictionary
both run locally on your Mac.

## Using it

| Action | What happens |
| --- | --- |
| Drag the window over text | Reads it automatically when you let go |
| Click 🔈 next to a word | Hear it spoken |
| ⌥-click 🔈 | Hear it spoken slowly |
| 🌐 | Switch language |
| 🎨 | Switch color theme, or pick any accent color |
| Drag a handle on the frame | Resize it (see below) |
| ⤢ | Quick sizes: Character · Word · Line · Bubble |
| 🔍 | Read again without moving |
| ⌃ | Fold the results panel away, leaving just the frame |
| ✕ or ⌘Q | Quit |

The frame is see-through, so position it like a magnifying glass. For Chinese
and Japanese it reads **both horizontal and vertical** text; Chinese works in
simplified and traditional.

### Colors

The 🎨 button opens a row of color circles — click one to switch instantly.
Eight built-in accents, plus **Custom color…**, which opens the system color
picker and derives a whole palette from whatever you choose. The circle you are
using is ringed in its own color.

The entire palette is computed from one accent hue, so nothing ever clashes:
title bar, frame, panel, handles, the axolotl and the button tints all shift
together. Themes vary hue and saturation but stay light on purpose, because the
tone colors (Chinese 1–4) are a fixed learning convention and have to stay
legible whatever accent is picked. Your choice is saved.

To match the app icon to a theme, pass its hue when regenerating:
`./.venv/bin/python make_icon.py 205` for Sky, then rebuild.

### Hearing words

**Every pronunciation gets its own speaker icon**, so 那个 can be heard as both
*nà ge* and *nèi ge*, and Japanese 上手 as both *jōzu* and *uwate*. The whole
line at the top of the panel has one too — handy for hearing a sentence's
rhythm before drilling single words. Hold **⌥ Option** while clicking for a
slower reading.

Voicing a *specific* reading of a Chinese homograph takes a trick: handing 薄
to a synthesizer always produces its default *báo*, so to demonstrate *bó* the
app speaks a different character whose own default reading is *bó*. A character
only qualifies as a stand-in if pypinyin confirms it reads that way, which
keeps the audio honest. Where no stand-in exists the variant simply gets no
icon rather than playing the wrong sound. Japanese needs no such trick — it
speaks the kana of each reading directly.

The voices are macOS's own, so they work offline. Japanese speaks the *kana*
rather than the kanji, because synthesizers routinely guess the wrong reading
for kanji homographs while kana pins it exactly. If a voice sounds robotic, you
can install a better one in System Settings → Accessibility → Spoken Content →
System Voice → Manage Voices; the app picks the highest-quality voice installed
for each language automatically.

### Sizing the frame

Three pink handles sit on the frame itself:

- **right edge** — width only, for narrowing onto a phrase
- **bottom edge** — height only, for adding or dropping a line
- **bottom-right corner** — both at once

The frame's top-left corner stays put while you resize, so it won't slide off
whatever you were aiming at, and the live size shows in the title bar as you
drag. It goes down to 44 × 26 points — small enough to isolate one character —
without shrinking the definitions panel, which stays a readable width no matter
how small the frame gets.

Aim small to disambiguate: parked on just 說 you get *shuō* "to speak" **and**
*shuì* "to persuade", instead of it being swallowed into the surrounding
sentence.

Pinyin is colored by tone: 1 mā (red) · 2 má (amber) · 3 mǎ (green) ·
4 mà (blue) · 5 ma (gray). These stay fixed across themes.

## Tips

- If nothing is found, zoom the page in a little. OCR needs a reasonable
  number of pixels per character — the lens upscales small captures, but very
  tiny text is still hard.
- Cover a whole line or bubble rather than one character. Words get segmented
  properly with context, so 知道 is looked up as one word instead of 知 + 道.
- The lens sits above other windows and follows you across Spaces and
  full-screen apps.

## Accuracy notes

- **Korean romanization** is computed from the Hangul, covering liaison and the
  common consonant assimilations (독립 → *dongnip*, 신라 → *silla*). Rarer sandhi
  isn't modelled, so treat it as a strong hint rather than gospel.
- **Japanese conjugation** is handled by a rule table, so common forms
  (言って → 言う, ました → ます) resolve, but unusual ones may only match a stem.
- **European inflections** go through a lemmatizer. It's good but not perfect —
  Italian *stia* is listed as a noun ("chicken coop") and won't resolve to
  *stare*. Where a surface form and its lemma are both real words, both senses
  are shown rather than guessing.
- Homographs are ranked by real frequency data, so Chinese 說 leads with *shuō*
  and Japanese いる with 居る "to be" rather than 射る "to shoot an arrow".
- **Czech and Turkish are a step behind the rest.** Vision has no recognizer for
  either, so their text is read with the English model and the accents come back
  wrong (Příliš → Prílis). Lookup compensates by matching an accent-free form of
  both the text and the dictionary, including the lemmatizer's own vocabulary,
  which recovers most words. A letter genuinely misread cannot be recovered.
- **Chinese shows every recorded pronunciation.** 那个 gives *nà ge · also nèi
  ge*, 谁 gives *shéi · also shuí*, and 薄 lists all four of *báo / bó / Bó /
  bò* with their own senses. Secondary readings are labelled with the kind of
  variant they are — *also*, *colloquial*, *Taiwan*, *old*.
- **Speech follows the written word, not the sentence.** Chinese tone sandhi
  (你好 spoken as *níhǎo*) applies within a word but the synthesizer can't know
  about neighboring words, so click the sentence icon to hear it in context.

## How it works

- **Capture** — `CGWindowListCreateImage` with `OnScreenBelowWindow`, so the
  lens photographs everything *beneath* itself and never itself.
- **OCR** — Apple's Vision framework, offline, given the selected language.
  Vision can't read vertical CJK at all, so when a read comes back empty the
  app slices the columns into character cells and reflows them into a
  horizontal strip, which Vision reads fine.
- **Speech** — `AVSpeechSynthesizer` with the system voice for each language.
  The speaker icons are link attributes in the results text, so a click maps
  straight back to the word it belongs to.
- **Words** — Chinese uses jieba, repaired by longest-match against the
  dictionary (jieba is trained on simplified and glues traditional characters
  together). Japanese uses longest-match plus deinflection rules. Korean peels
  off particles and verb endings. The European languages split on spaces and
  fall back to a lemmatizer.

## Building a release

```
./.venv/bin/python -m PyInstaller TranslationLens.spec --noconfirm   # -> dist/Translation Lens.app
./make_dmg.sh                                                   # -> ~/Desktop/Translation-Lens-1.0.0.dmg
"dist/Translation Lens.app/Contents/MacOS/Translation Lens" --selftest    # verifies the bundle
```

The release app is fully self-contained (127 MB): interpreter, PyObjC, all eleven
lexicons and the data files jieba/pypinyin/simplemma load at runtime. It does
not read anything from this folder, keeps preferences in
`~/Library/Application Support/Translation Lens/` and logs to
`~/Library/Logs/Translation Lens.log`.

`--selftest` loads every lexicon, does a lookup, checks a voice exists for each
language and confirms Chinese variant readings resolve. Run it on any build
before shipping.

### Before you can sell it

1. **Code signing and notarization are not optional.** An unsigned app is
   refused by Gatekeeper on every Mac except the one that built it. You need a
   paid Apple Developer account, then:
   `./sign_and_notarize.sh "Developer ID Application: Your Name (TEAMID)"`
   That script signs every nested binary, applies the hardened-runtime
   entitlements CPython needs, notarizes and staples.
2. **This build is Apple Silicon only.** It was built with an arm64
   interpreter, so it won't launch on Intel Macs. For a universal binary,
   rebuild the venv on a `universal2` Python.
3. **Attribution is a license condition.** The dictionaries are CC BY-SA 4.0.
   The app ships `LICENSES.txt` and an in-app *Licenses & Credits* item; keep
   both. The lexicon files remain CC BY-SA and must be offered on request —
   they cannot be presented as proprietary.
4. Get a lawyer's read before charging money. Share-alike scope over databases
   is genuinely contested, and this is the kind of detail that matters once
   there's revenue.

## Files

```
lens.py           the app — window, capture, OCR, rendering (macOS only)
langs.py          per-language tokenising, readings and lookup
build_dicts.py    normalizes raw dictionaries into data/lex-*.pickle
fetch_dicts.sh    re-downloads the sources and rebuilds the lexicons
TranslationLens.spec   PyInstaller recipe for the shippable app
make_dmg.sh       wraps the app in a drag-to-install disk image
sign_and_notarize.sh  signs/notarizes for distribution (needs your Apple ID)
build_app.sh      quick dev bundle that runs lens.py in place (not for release)
make_icon.py      draws the axolotl icon
data/lex-*.pickle one lexicon per language
data/settings.json remembers your language and frame size
.venv/            dependencies
```

To add another language, add a `Language` subclass in `langs.py` plus a builder
in `build_dicts.py`. Vision can also recognize Russian, Ukrainian, Thai,
Vietnamese and Cantonese. Languages Vision cannot read at all — Devanagari, so
no Hindi — would need a different OCR engine.

Edit `lens.py` and just relaunch — no rebuild needed. Rerun `./build_app.sh`
only if you change the icon or bundle layout. Colors and sizes live in the
constants near the top of `lens.py` (`PINK_*`, `TONE_COLORS`, `WIN_W_MIN`,
`RESULTS_H`, `PRESETS`, `SPEAK_RATE`).

To refresh the dictionaries later, run `./fetch_dicts.sh`. It re-downloads the
raw sources (~290 MB), rebuilds the lexicons, and deletes the raw files again.

## License

The source code is MIT — see LICENSE. The dictionary data is CC BY-SA 4.0 and
remains so; the two are separate works.

## Credits

All dictionary data is openly licensed, CC BY-SA 4.0:

- Chinese — [CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cc-cedict)
- Japanese — [JMdict/EDICT](https://www.edrdg.org/jmdict/j_jmdict.html), EDRDG
- Korean — English Wiktionary, extracted by [kaikki.org](https://kaikki.org)
- French, Spanish, Italian, German — [WikDict](https://www.wikdict.com), from Wiktionary
