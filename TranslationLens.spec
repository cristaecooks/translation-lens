# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a self-contained Translation Lens.app.

Everything the app needs is bundled: the interpreter, PyObjC, the lexicons and
the data files that jieba / pypinyin / simplemma load at runtime.  simplemma
ships lemma dictionaries for dozens of languages, so only the four the app
offers are included — that alone saves about 60 MB.
"""

import os
from PyInstaller.utils.hooks import collect_data_files

VERSION = "1.0.0"
LANGS = ("fr", "es", "it", "de", "pt", "cs", "tr", "la")

datas = [(os.path.join("data", "lex-%s.pickle" % c), "data")
         for c in ("zh", "ja", "ko", "fr", "es", "it", "de",
                   "pt", "cs", "tr", "la")]
datas += collect_data_files("jieba")
datas += collect_data_files("pypinyin")

datas += collect_data_files("simplemma")


#: jieba bundles extras this app never touches — a 10 MB neural segmenter
#: model and a 5.9 MB TF-IDF table.  Only jieba.cut() is used.
JIEBA_UNUSED = ("jieba/lac_small", "jieba/analyse", "jieba/finalseg/prob_emit")


def keep(dest):
    """Drop payload the app never loads.

    Filtering has to happen after Analysis: PyInstaller's own hooks collect
    whole data directories regardless of what we asked for.
    """
    path = dest.replace("\\", "/")
    parts = path.split("/")
    if "dictionaries" in parts and path.endswith(".plzma"):
        return os.path.basename(path).split(".")[0] in LANGS
    for unused in JIEBA_UNUSED:
        if unused in path:
            return False
    return True


a = Analysis(
    ["lens.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "langs", "jieba", "pypinyin", "simplemma", "numpy",
        "AVFoundation", "Vision", "Quartz", "AppKit", "Foundation", "objc",
    ],
    excludes=["tkinter", "PyInstaller", "pytest", "setuptools", "pip"],
    noarchive=False,
)
a.datas = [d for d in a.datas if keep(d[0])]
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Translation Lens",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="Translation Lens",
)
app = BUNDLE(
    coll,
    name="Translation Lens.app",
    icon="AppIcon.icns",
    bundle_identifier="com.translationlens.app",
    version=VERSION,
    info_plist={
        "CFBundleName": "Translation Lens",
        "CFBundleDisplayName": "Translation Lens",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.education",
        "NSHumanReadableCopyright":
            "Dictionary data CC BY-SA 4.0 — see Licenses & Credits in the app menu.",
    },
)
