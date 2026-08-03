#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Translation Lens — a cute floating reading lens for macOS.

Drag the little pink window so it sits over foreign-language text, let go, and
it reads whatever is underneath: pronunciation plus dictionary definitions.
Chinese, Japanese, Korean, French, Spanish, Italian and German; pick one from
the globe button.

This module is the app: window, capture, OCR and rendering.  Everything
language-specific — tokenising, readings, lookup — lives in langs.py, and the
lexicons it loads are built by build_dicts.py.
"""

import json
import math
import sys
import os
import re
import pickle
import threading
import traceback

import AVFoundation
import numpy
import objc
import Quartz
import Vision
from Foundation import (
    NSBundle, NSObject, NSMakeRect, NSMakeSize, NSMakePoint, NSAutoreleasePool,
    NSNotificationCenter, NSMutableAttributedString, NSAttributedString,
)
from AppKit import (
    NSApp, NSApplication, NSPanel, NSView, NSColor, NSBezierPath, NSFont,
    NSScrollView, NSTextView, NSButton, NSImage, NSScreen, NSGradient,
    NSBackingStoreBuffered, NSFloatingWindowLevel,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSApplicationActivationPolicyRegular,
    NSFontAttributeName, NSForegroundColorAttributeName,
    NSParagraphStyleAttributeName, NSMutableParagraphStyle,
    NSViewWidthSizable, NSViewHeightSizable,
    NSMenu, NSMenuItem, NSButtonTypeMomentaryChange, NSLineBreakByWordWrapping,
    NSTextAttachment, NSCursor, NSCursorAttributeName, NSLinkAttributeName,
    NSImageSymbolConfiguration, NSCompositingOperationSourceAtop,
    NSColorPanel, NSColorSpace, NSTrackingArea,
    NSTrackingMouseEnteredAndExited, NSTrackingMouseMoved,
    NSTrackingActiveAlways, NSStatusBar, NSVariableStatusItemLength,
    NSCompositingOperationSourceOver, NSRectFillUsingOperation,
)

import langs

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = getattr(sys, "frozen", False)

#: A shipped .app bundle is read-only, so preferences and logs belong in the
#: user's Library rather than next to the code.
if FROZEN:
    SUPPORT = os.path.expanduser("~/Library/Application Support/Translation Lens")
    LOG_PATH = os.path.expanduser("~/Library/Logs/Translation Lens.log")
else:
    SUPPORT = os.path.join(HERE, "data")
    LOG_PATH = None
os.makedirs(SUPPORT, exist_ok=True)
SETTINGS = os.path.join(SUPPORT, "settings.json")


def install_problem(path=None):
    """Detect locations where macOS can never remember a permission.

    Two traps, both of which look identical to the user — they grant Screen
    Recording, and the app keeps asking:

    * Running from a mounted .dmg: the volume is read-only and its path
      changes each time it is mounted.
    * App Translocation: macOS runs a quarantined, unsigned app from a
      randomised read-only path, so the grant never matches twice.  Moving
      the app in Finder and clearing the quarantine flag is what stops it.
    """
    if path is None:
        try:
            path = NSBundle.mainBundle().bundlePath()
        except Exception:
            return None
    if not path:
        return None
    if "/AppTranslocation/" in path:
        return "translocated"
    if path.startswith("/Volumes/"):
        return "volume"
    return None


def start_logging():
    if not LOG_PATH:
        return
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        fh = open(LOG_PATH, "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = fh
    except Exception:
        pass

# ---------------------------------------------------------------- palette ---

def rgb(r, g, b, a=1.0):
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r / 255.0, g / 255.0, b / 255.0, a)

#: Every surface color is derived from one accent hue, so a theme change
#: stays coherent.  Brightness is kept high across all themes: the tone
#: colors below are a fixed learning convention and must stay legible on the
#: panel whatever accent is chosen.
THEMES = (
    ("Sakura", 340, 1.00),
    ("Peach", 18, 1.00),
    ("Amber", 42, 0.95),
    ("Matcha", 105, 0.85),
    ("Mint", 165, 0.85),
    ("Sky", 205, 0.90),
    ("Lavender", 278, 0.85),
    ("Slate", 222, 0.35),
)
DEFAULT_HUE, DEFAULT_SAT = 340, 1.00

_speaker_icon = {}   # tinted glyphs, cleared whenever the theme changes


def set_theme(hue, sat=1.0):
    """Recompute the palette from an accent hue (degrees) and saturation."""
    global C_HEADER, C_HEADER_2, C_PANEL, C_BORDER, C_TINT, C_DEEP
    global C_INK, C_INK_SOFT, C_TITLE, C_TITLE_SUB
    global C_AXO_BODY, C_AXO_GILL, C_AXO_LINE, C_AXO_BLUSH, THEME_HUE, THEME_SAT

    def hsb(h, s, b, a=1.0):
        return NSColor.colorWithHue_saturation_brightness_alpha_(
            (h % 360) / 360.0, max(0.0, min(1.0, s * sat)), b, a)

    THEME_HUE, THEME_SAT = hue, sat
    C_HEADER     = hsb(hue, 0.33, 1.00)
    C_HEADER_2   = hsb(hue, 0.23, 1.00)
    C_PANEL      = hsb(hue, 0.05, 1.00)
    C_BORDER     = hsb(hue, 0.57, 0.94)
    C_TINT       = hsb(hue, 0.40, 1.00, 0.07)
    C_DEEP       = hsb(hue, 0.68, 0.75)
    C_INK        = hsb(hue, 0.30, 0.24)
    C_INK_SOFT   = hsb(hue, 0.20, 0.47)
    C_TITLE      = hsb(hue, 0.75, 0.55)
    C_TITLE_SUB  = hsb(hue, 0.55, 0.62, 0.85)
    C_AXO_BODY   = hsb(hue, 0.14, 1.00)
    C_AXO_GILL   = hsb(hue, 0.42, 1.00)
    C_AXO_LINE   = hsb(hue, 0.65, 0.84)
    C_AXO_BLUSH  = hsb(hue, 0.48, 1.00, 0.75)
    _speaker_icon.clear()        # the glyph is tinted, so it must be redrawn


def theme_swatch(hue, sat, kind="fill"):
    """A theme's representative color, without touching the live palette."""
    def hsb(sa, b, a=1.0):
        return NSColor.colorWithHue_saturation_brightness_alpha_(
            (hue % 360) / 360.0, max(0.0, min(1.0, sa * sat)), b, a)
    if kind == "edge":
        return hsb(0.70, 0.78)
    return hsb(0.50, 1.00)


set_theme(DEFAULT_HUE, DEFAULT_SAT)

# Tone colors: 1 red, 2 amber, 3 green, 4 blue, 5/neutral gray.
TONE_COLORS = {
    1: rgb(224, 41, 92),
    2: rgb(212, 124, 0),
    3: rgb(24, 150, 78),
    4: rgb(56, 105, 214),
    5: rgb(140, 140, 153),
}

HEADER_H        = 34
RESULTS_H       = 264
CORNER          = 14

# The reading frame is sized independently of the window: the window has to
# stay wide enough to read definitions in, but the frame needs to shrink to a
# couple of characters.  So the frame is an inset rect inside a transparent
# band, anchored at the window's top-left.
WIN_W_MIN       = 380
FRAME_INSET     = 12
FRAME_PAD       = 6
FRAME_W_DEFAULT = 300
FRAME_H_DEFAULT = 76
FRAME_W_MIN     = 44
FRAME_H_MIN     = 26
FRAME_W_MAX     = 1100
FRAME_H_MAX     = 600

#: quick sizes, roughly: one character, a word, a line, a whole bubble
PRESETS = (
    ("Character", 56, 52),
    ("Word", 116, 56),
    ("Line", 300, 60),
    ("Bubble", 360, 130),
)

# --------------------------------------------------------------- credits ---

#: Shown by Help -> Licenses & Credits.  The dictionaries are all share-alike
#: licensed, which obliges any distributed build to carry this attribution.
CREDITS = [
    ("Translation Lens", "Reading lens for Chinese, Japanese, Korean, French, "
                    "Spanish, Italian and German."),
    ("Dictionary data — CC BY-SA 4.0",
     "Chinese: CC-CEDICT (mdbg.net).\n"
     "Japanese: JMdict/EDICT, Electronic Dictionary Research and Development "
     "Group (edrdg.org).\n"
     "Korean: English Wiktionary, extracted by kaikki.org.\n"
     "French, Spanish, Italian, German: WikDict (wikdict.com), from "
     "Wiktionary.\n\n"
     "These dictionaries are licensed CC BY-SA 4.0. The lexicon files shipped "
     "with this app are adaptations of them and remain under the same license; "
     "they are available on request."),
    ("Software libraries",
     "jieba (MIT) — Chinese word segmentation.\n"
     "pypinyin (MIT) — pinyin readings.\n"
     "simplemma (MIT) — lemmatisation.\n"
     "PyObjC (MIT), NumPy (BSD), Python (PSF)."),
    ("System frameworks",
     "Text recognition uses Apple's Vision framework; speech uses "
     "AVSpeechSynthesizer. Both run on-device — no text leaves your Mac."),
]


def credits_text():
    s = NSMutableAttributedString.alloc().init()
    for title, body in CREDITS:
        s.appendAttributedString_(attr(title + "\n", rounded_font(13, True),
                                       C_DEEP, make_para(before=8, after=3)))
        s.appendAttributedString_(attr(body + "\n", rounded_font(11),
                                       C_INK_SOFT, make_para(lead=2.5, after=4)))
    return s


# ----------------------------------------------------------------- tts ---

#: default is 0.5; a touch slower is easier to imitate when learning
SPEAK_RATE = 0.44
SPEAK_RATE_SLOW = 0.30

#: AVSpeechSynthesisVoiceGender: 1 = male, 2 = female
PREFER_GENDER = 2


class Speaker(object):
    """Speaks a word in the language it belongs to."""

    def __init__(self):
        self.synth = AVFoundation.AVSpeechSynthesizer.alloc().init()
        self._voices = {}

    def voice(self, tag):
        """Pick the most natural-sounding voice installed for a language.

        macOS ships novelty character voices (Grandma, Rocko, Shelley …) in
        every language, and they are useless for learning pronunciation — they
        were what made French and German sound incoherent.  They can be told
        apart reliably: the real native voices declare a gender, the novelty
        ones leave it unspecified.  After that, prefer female, then whatever
        quality tier the user has installed (enhanced/premium if downloaded).
        """
        if tag in self._voices:
            return self._voices[tag]

        def rank(v):
            try:
                gender = v.gender()
            except Exception:
                gender = 0
            return (1 if gender != 0 else 0,          # a real native voice
                    1 if gender == PREFER_GENDER else 0,
                    v.quality())

        best = None
        for cand in AVFoundation.AVSpeechSynthesisVoice.speechVoices():
            if cand.language() != tag:
                continue
            if best is None or rank(cand) > rank(best):
                best = cand
        self._voices[tag] = (
            best or AVFoundation.AVSpeechSynthesisVoice.voiceWithLanguage_(tag))
        return self._voices[tag]

    def speak(self, text, tag, slow=False):
        if not text or not tag:
            return False
        v = self.voice(tag)
        if v is None:
            return False
        # cut off whatever is playing so rapid clicks don't queue up
        self.synth.stopSpeakingAtBoundary_(0)
        u = AVFoundation.AVSpeechUtterance.alloc().initWithString_(text)
        u.setVoice_(v)
        u.setRate_(SPEAK_RATE_SLOW if slow else SPEAK_RATE)
        self.synth.speakUtterance_(u)
        return True


SPEAKER = Speaker()


def speaker_icon(size=11.0):
    """A small pink speaker glyph for inline use in the results panel."""
    if size in _speaker_icon:
        return _speaker_icon[size]
    img = None
    try:
        base = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "speaker.wave.2.fill", "speak")
        if base is not None:
            cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_scale_(
                size, 0, 1)
            base = base.imageWithSymbolConfiguration_(cfg)
            r = NSMakeRect(0, 0, base.size().width, base.size().height)
            img = NSImage.alloc().initWithSize_(base.size())
            img.lockFocus()
            base.drawInRect_fromRect_operation_fraction_(
                r, NSMakeRect(0, 0, 0, 0), NSCompositingOperationSourceOver, 1.0)
            C_DEEP.set()
            NSRectFillUsingOperation(r, NSCompositingOperationSourceAtop)
            img.unlockFocus()
    except Exception:
        img = None
    _speaker_icon[size] = img
    return img


def speak_link(index, size=11.0):
    """Clickable speaker icon; the link carries an index into `speakables`."""
    img = speaker_icon(size)
    if img is None:
        piece = NSMutableAttributedString.alloc().initWithString_("♪")
    else:
        att = NSTextAttachment.alloc().init()
        att.setImage_(img)
        piece = NSMutableAttributedString.alloc().initWithAttributedString_(
            NSAttributedString.attributedStringWithAttachment_(att))
    piece.addAttributes_range_(
        {NSLinkAttributeName: "speak:%d" % index,
         NSCursorAttributeName: NSCursor.pointingHandCursor()},
        (0, piece.length()))
    return piece


# ------------------------------------------------------------ settings ---

def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_settings(**kw):
    data = load_settings()
    data.update(kw)
    try:
        with open(SETTINGS, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except Exception:
        pass


# --------------------------------------------------------------- fonts ---

def rounded_font(size, bold=False):
    weight = 0.4 if bold else 0.0
    base = NSFont.systemFontOfSize_weight_(size, weight)
    try:
        desc = base.fontDescriptor().fontDescriptorWithDesign_("NSCTFontUIFontDesignRounded")
        if desc is not None:
            f = NSFont.fontWithDescriptor_size_(desc, size)
            if f is not None:
                return f
    except Exception:
        pass
    return base


# --------------------------------------------------------- dictionary ---

#: langs.py owns tokenising, readings and lookup for every language.
CJK_RE = langs.CJK_RE


# ------------------------------------------------------------ drawing ---

def rounded_path(rect, tl, tr, br, bl):
    """NSBezierPath with per-corner radii (bottom-left origin coords)."""
    x, y = rect.origin.x, rect.origin.y
    w, h = rect.size.width, rect.size.height
    p = NSBezierPath.bezierPath()
    p.moveToPoint_(NSMakePoint(x + bl, y))
    p.lineToPoint_(NSMakePoint(x + w - br, y))
    if br:
        p.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
            NSMakePoint(x + w - br, y + br), br, 270, 360)
    p.lineToPoint_(NSMakePoint(x + w, y + h - tr))
    if tr:
        p.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
            NSMakePoint(x + w - tr, y + h - tr), tr, 0, 90)
    p.lineToPoint_(NSMakePoint(x + tl, y + h))
    if tl:
        p.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
            NSMakePoint(x + tl, y + h - tl), tl, 90, 180)
    p.lineToPoint_(NSMakePoint(x, y + bl))
    if bl:
        p.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
            NSMakePoint(x + bl, y + bl), bl, 180, 270)
    p.closePath()
    return p


#: gill fan: (angle in degrees, stalk length) measured out from the head
_GILLS = ((34, 19), (2, 22), (-28, 18))


def draw_axolotl(x, y, size):
    """A cute pink axolotl in a `size` x `size` box at (x, y).

    Everything is outlined in deep pink so the mascot reads as a sticker on
    both the pink title bar and the pale app icon.
    """
    s = size / 100.0
    BODY, GILL, LINE = C_AXO_BODY, C_AXO_GILL, C_AXO_LINE
    DARK = rgb(74, 42, 58)          # eyes and smile stay neutral
    lw = 2.4 * s

    def P(px, py):
        return NSMakePoint(x + px * s, y + py * s)

    def oval(cx, cy, rw, rh):
        return NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(x + (cx - rw) * s, y + (cy - rh) * s, 2 * rw * s, 2 * rh * s))

    def gill_geometry():
        for sign in (-1, 1):
            for ang, glen in _GILLS:
                rad = math.radians(ang)
                x0, y0 = 50 + sign * 19, 53
                yield (P(x0, y0),
                       P(x0 + sign * glen * math.cos(rad), y0 + glen * math.sin(rad)),
                       50 + sign * (19 + glen * math.cos(rad)),
                       53 + glen * math.sin(rad))

    # Gills, outline pass then fill pass, so neighboring gills never
    # draw their outline across each other's body.
    for width, color, tip in ((7.0 * s + 2 * lw, LINE, 6.6), (7.0 * s, GILL, 5.4)):
        color.set()
        for a, b, tx, ty in gill_geometry():
            stalk = NSBezierPath.bezierPath()
            stalk.setLineWidth_(width)
            stalk.setLineCapStyle_(1)
            stalk.moveToPoint_(a)
            stalk.lineToPoint_(b)
            stalk.stroke()
            oval(tx, ty, tip, tip).fill()

    # head
    head = oval(50, 50, 29, 25)
    BODY.set()
    head.fill()
    LINE.set()
    head.setLineWidth_(lw)
    head.stroke()

    # blush
    C_AXO_BLUSH.set()
    oval(33, 43, 6.5, 4.2).fill()
    oval(67, 43, 6.5, 4.2).fill()

    # eyes
    DARK.set()
    oval(39, 55, 5.0, 5.8).fill()
    oval(61, 55, 5.0, 5.8).fill()
    NSColor.whiteColor().set()
    oval(40.6, 57.2, 1.9, 2.1).fill()
    oval(62.6, 57.2, 1.9, 2.1).fill()

    # smile
    DARK.set()
    mouth = NSBezierPath.bezierPath()
    mouth.setLineWidth_(2.6 * s)
    mouth.setLineCapStyle_(1)
    mouth.moveToPoint_(P(43.5, 44))
    mouth.curveToPoint_controlPoint1_controlPoint2_(P(56.5, 44), P(47, 37.5), P(53, 37.5))
    mouth.stroke()


class AxolotlView(NSView):
    def drawRect_(self, rect):
        b = self.bounds()
        draw_axolotl(b.origin.x, b.origin.y, min(b.size.width, b.size.height))

    def mouseDownCanMoveWindow(self):
        return True


class ChromeView(NSView):
    """Header bar + results panel background. The lens area stays see-through."""

    def initWithFrame_(self, frame):
        self = objc.super(ChromeView, self).initWithFrame_(frame)
        self.frame_rect = NSMakeRect(0, 0, 0, 0)
        self.header_rect = NSMakeRect(0, 0, 0, 0)
        self.panel_rect = NSMakeRect(0, 0, 0, 0)
        self.busy = False
        self.size_badge = None
        return self

    def mouseDownCanMoveWindow(self):
        return True

    def drawRect_(self, rect):
        # ---- header
        h = self.header_rect
        if h.size.height > 0:
            NSColor.colorWithSRGBRed_green_blue_alpha_(0, 0, 0, 0.10).set()
            rounded_path(h, CORNER, CORNER, 0, 0).fill()
            grad = NSGradient.alloc().initWithStartingColor_endingColor_(
                C_HEADER, C_HEADER_2)
            grad.drawInBezierPath_angle_(rounded_path(h, CORNER, CORNER, 0, 0), 90.0)

            if self.size_badge:
                s = NSAttributedString.alloc().initWithString_attributes_(
                    self.size_badge,
                    {NSFontAttributeName: rounded_font(10, True),
                     NSForegroundColorAttributeName: C_TITLE_SUB})
                s.drawAtPoint_(NSMakePoint(
                    h.origin.x + h.size.width - 6 * 23 - 10 - s.size().width,
                    h.origin.y + (h.size.height - s.size().height) / 2.0))

        # ---- reading frame
        L = self.frame_rect
        if L.size.height > 0:
            C_TINT.set()
            NSBezierPath.bezierPathWithRect_(L).fill()
            C_BORDER.set()
            dashed = NSBezierPath.bezierPathWithRect_(
                NSMakeRect(L.origin.x + 1, L.origin.y + 1,
                           L.size.width - 2, L.size.height - 2))
            dashed.setLineWidth_(1.6)
            dashed.setLineDash_count_phase_([5.0, 4.0], 2, 0.0)
            dashed.stroke()
            # corner brackets
            c = 13.0
            C_DEEP.set()
            for cx, cy, dx, dy in (
                (L.origin.x + 1, L.origin.y + 1, 1, 1),
                (L.origin.x + L.size.width - 1, L.origin.y + 1, -1, 1),
                (L.origin.x + 1, L.origin.y + L.size.height - 1, 1, -1),
                (L.origin.x + L.size.width - 1, L.origin.y + L.size.height - 1, -1, -1),
            ):
                b = NSBezierPath.bezierPath()
                b.setLineWidth_(2.6)
                b.setLineCapStyle_(1)
                b.moveToPoint_(NSMakePoint(cx + dx * c, cy))
                b.lineToPoint_(NSMakePoint(cx, cy))
                b.lineToPoint_(NSMakePoint(cx, cy + dy * c))
                b.stroke()
            if self.busy:
                C_DEEP.set()
                glow = NSBezierPath.bezierPathWithRect_(
                    NSMakeRect(L.origin.x, L.origin.y, L.size.width, L.size.height))
                glow.setLineWidth_(3.0)
                glow.stroke()

        # ---- results panel
        p = self.panel_rect
        if p.size.height > 0:
            C_PANEL.set()
            rounded_path(p, 0, 0, CORNER, CORNER).fill()
            C_HEADER.set()
            path = rounded_path(
                NSMakeRect(p.origin.x + 0.75, p.origin.y + 0.75,
                           p.size.width - 1.5, p.size.height - 1.5),
                0, 0, CORNER, CORNER)
            path.setLineWidth_(1.5)
            path.stroke()


class SwatchPickerView(NSView):
    """A row of color circles, used as the theme menu's content.

    A menu of color *names* makes you imagine the result; circles show it.
    """
    SIZE, GAP, PAD = 22.0, 7.0, 11.0

    def initWithOwner_(self, owner):
        n = len(THEMES)
        w = self.PAD * 2 + n * self.SIZE + (n - 1) * self.GAP
        h = self.PAD * 2 + self.SIZE
        self = objc.super(SwatchPickerView, self).initWithFrame_(
            NSMakeRect(0, 0, w, h))
        if self is None:
            return None
        self.owner = owner
        self.hover = -1
        return self

    def viewDidMoveToWindow(self):
        for area in list(self.trackingAreas()):
            self.removeTrackingArea_(area)
        self.addTrackingArea_(NSTrackingArea.alloc()
            .initWithRect_options_owner_userInfo_(
                self.bounds(),
                NSTrackingMouseEnteredAndExited | NSTrackingMouseMoved
                | NSTrackingActiveAlways, self, None))

    @objc.python_method
    def circle(self, i):
        x = self.PAD + i * (self.SIZE + self.GAP)
        return NSMakeRect(x, self.PAD, self.SIZE, self.SIZE)

    @objc.python_method
    def index_at(self, point):
        for i in range(len(THEMES)):
            r = self.circle(i)
            # generous hit area: the gaps count towards the nearer circle
            if (r.origin.x - self.GAP / 2 <= point.x
                    <= r.origin.x + r.size.width + self.GAP / 2):
                return i
        return -1

    def drawRect_(self, rect):
        for i, (name, hue, sat) in enumerate(THEMES):
            r = self.circle(i)
            active = (abs(hue - THEME_HUE) < 1 and abs(sat - THEME_SAT) < 0.01)
            if active or i == self.hover:
                ring = NSBezierPath.bezierPathWithOvalInRect_(
                    NSMakeRect(r.origin.x - 3.5, r.origin.y - 3.5,
                               r.size.width + 7, r.size.height + 7))
                (theme_swatch(hue, sat, "edge") if active
                 else NSColor.colorWithSRGBRed_green_blue_alpha_(0, 0, 0, 0.12)).set()
                ring.setLineWidth_(2.0 if active else 1.5)
                ring.stroke()
            dot = NSBezierPath.bezierPathWithOvalInRect_(r)
            theme_swatch(hue, sat).set()
            dot.fill()
            theme_swatch(hue, sat, "edge").set()
            dot.setLineWidth_(1.0)
            dot.stroke()

    def mouseMoved_(self, ev):
        i = self.index_at(self.convertPoint_fromView_(ev.locationInWindow(), None))
        if i != self.hover:
            self.hover = i
            self.setNeedsDisplay_(True)

    def mouseExited_(self, ev):
        self.hover = -1
        self.setNeedsDisplay_(True)

    def mouseUp_(self, ev):
        i = self.index_at(self.convertPoint_fromView_(ev.locationInWindow(), None))
        if 0 <= i < len(THEMES):
            _name, hue, sat = THEMES[i]
            try:
                self.owner.applyTheme(float(hue), float(sat))
            except Exception:
                traceback.print_exc()
        item = self.enclosingMenuItem()
        if item is not None and item.menu() is not None:
            item.menu().cancelTracking()


class GripView(NSView):
    """Grab handle on the reading frame.

    `axis` is "both" for the bottom-right corner, "h" for the right edge
    (width only) and "v" for the bottom edge (height only), so a phrase can be
    narrowed horizontally without disturbing the line height you already set.
    """

    def initWithFrame_(self, frame):
        self = objc.super(GripView, self).initWithFrame_(frame)
        self.owner = None
        self.axis = "both"
        self._start = None
        return self

    def mouseDownCanMoveWindow(self):
        return False

    def drawRect_(self, rect):
        b = self.bounds()
        C_DEEP.set()
        if self.axis == "both":
            for i in range(3):
                off = i * 4.0
                p = NSBezierPath.bezierPath()
                p.setLineWidth_(1.6)
                p.setLineCapStyle_(1)
                p.moveToPoint_(NSMakePoint(b.size.width - 2 - off, 2))
                p.lineToPoint_(NSMakePoint(b.size.width - 2, 2 + off))
                p.stroke()
        else:
            # a small pill straddling the edge
            inset = 2.0
            r = NSMakeRect(inset, inset, b.size.width - 2 * inset, b.size.height - 2 * inset)
            radius = min(r.size.width, r.size.height) / 2.0
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                r, radius, radius).fill()

    def mouseDown_(self, ev):
        self._start = (self.owner.frame_w, self.owner.frame_h,
                       self.window().convertPointToScreen_(
                           NSApp.currentEvent().locationInWindow()))

    def mouseDragged_(self, ev):
        if not self._start:
            return
        w0, h0, p0 = self._start
        now = self.window().convertPointToScreen_(
            NSApp.currentEvent().locationInWindow())
        w = w0 + (now.x - p0.x) if self.axis in ("both", "h") else w0
        h = h0 + (p0.y - now.y) if self.axis in ("both", "v") else h0
        self.owner.resizeFrameTo_(NSMakeSize(w, h))

    def mouseUp_(self, ev):
        self._start = None
        self.owner.endResize()


class PillButton(NSButton):
    def mouseDownCanMoveWindow(self):
        return False


# ------------------------------------------------------------- capture ---

def capture_below_window(win_number, screen_rect):
    """Grab the pixels under `screen_rect`, excluding our own window."""
    primary_h = NSScreen.screens()[0].frame().size.height
    cg = Quartz.CGRectMake(
        screen_rect.origin.x,
        primary_h - (screen_rect.origin.y + screen_rect.size.height),
        screen_rect.size.width,
        screen_rect.size.height,
    )
    return Quartz.CGWindowListCreateImage(
        cg,
        Quartz.kCGWindowListOptionOnScreenBelowWindow,
        win_number,
        Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageBestResolution,
    )


def upscale(cgimg, factor):
    if factor <= 1.001:
        return cgimg
    w = Quartz.CGImageGetWidth(cgimg)
    h = Quartz.CGImageGetHeight(cgimg)
    nw, nh = int(w * factor), int(h * factor)
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, nw, nh, 8, 0, cs,
        Quartz.kCGImageAlphaPremultipliedFirst | Quartz.kCGBitmapByteOrder32Little)
    if ctx is None:
        return cgimg
    Quartz.CGContextSetInterpolationQuality(ctx, Quartz.kCGInterpolationHigh)
    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, nw, nh), cgimg)
    return Quartz.CGBitmapContextCreateImage(ctx)


def _gray_array(cgimg):
    """The image as a 2-D uint8 array; row 0 is the top of the image."""
    w = Quartz.CGImageGetWidth(cgimg)
    h = Quartz.CGImageGetHeight(cgimg)
    ctx = Quartz.CGBitmapContextCreate(
        None, w, h, 8, 0, Quartz.CGColorSpaceCreateDeviceGray(), Quartz.kCGImageAlphaNone)
    if ctx is None:
        return None
    Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(0, 0, w, h), cgimg)
    stride = Quartz.CGBitmapContextGetBytesPerRow(ctx)
    buf = Quartz.CGBitmapContextGetData(ctx)
    arr = numpy.frombuffer(buf.as_buffer(stride * h), dtype=numpy.uint8)
    return arr.reshape(h, stride)[:, :w].copy()


def _runs(flags, gap):
    """Index ranges of consecutive True values, bridging gaps up to `gap`."""
    out = []
    start = None
    for i, on in enumerate(flags):
        if on and start is None:
            start = i
        elif not on and start is not None:
            out.append([start, i])
            start = None
    if start is not None:
        out.append([start, len(flags)])
    merged = []
    for r in out:
        if merged and r[0] - merged[-1][1] <= gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return merged


def reflow_vertical(cgimg, max_cells=64):
    """Turn a vertical-text image into a horizontal strip Vision can read.

    Vision's Chinese recognizer only handles horizontal lines — a column of
    stacked characters yields zero observations — but it reads isolated
    characters perfectly.  So slice the columns into character cells and
    paste them side by side in reading order (rightmost column first), which
    also keeps enough context for language correction to help.
    """
    gray = _gray_array(cgimg)
    if gray is None or min(gray.shape) < 12:
        return None
    border = numpy.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]])
    ink = numpy.abs(gray.astype(numpy.int16) - int(numpy.median(border))) > 60
    if not ink.any():
        return None

    cols = _runs(ink.sum(axis=0) > 0, gap=1)
    if not cols:
        return None
    # Characters are square, so the widest raw band approximates one glyph;
    # use it to bridge the white gaps inside characters like 川.
    glyph = max(c[1] - c[0] for c in cols)
    cols = _runs(ink.sum(axis=0) > 0, gap=max(1, int(glyph * 0.4)))
    cols = [c for c in cols if (c[1] - c[0]) >= glyph * 0.5]
    if not cols:
        return None

    cells = []
    for x0, x1 in sorted(cols, key=lambda c: -c[0]):     # right to left
        cw = x1 - x0
        rows = _runs(ink[:, x0:x1].sum(axis=1) > 0, gap=1)
        group = None
        for y0, y1 in rows:
            if group is not None and (y1 - group[0]) <= cw * 1.25:
                group[1] = y1
            else:
                if group is not None:
                    cells.append((x0, group[0], cw, group[1] - group[0]))
                group = [y0, y1]
        if group is not None:
            cells.append((x0, group[0], cw, group[1] - group[0]))
    if not 2 <= len(cells) <= max_cells:
        return None

    pad = max(4, glyph // 6)
    strip_h = max(c[3] for c in cells) + 2 * pad
    strip_w = sum(c[2] for c in cells) + pad * (len(cells) + 1)
    ctx = Quartz.CGBitmapContextCreate(
        None, strip_w, strip_h, 8, 0, Quartz.CGColorSpaceCreateDeviceRGB(),
        Quartz.kCGImageAlphaPremultipliedFirst | Quartz.kCGBitmapByteOrder32Little)
    if ctx is None:
        return None
    Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, strip_w, strip_h))
    x = pad
    for cx, cy, cw, ch in cells:
        piece = Quartz.CGImageCreateWithImageInRect(
            cgimg, Quartz.CGRectMake(cx, cy, cw, ch))
        Quartz.CGContextDrawImage(
            ctx, Quartz.CGRectMake(x, (strip_h - ch) / 2.0, cw, ch), piece)
        x += cw + pad
    return Quartz.CGBitmapContextCreateImage(ctx)


def denoise(text):
    """Drop stray single latin letters.

    A tight frame clips the glyphs either side of the one you're aiming at,
    and Vision reads those slivers as lone roman letters ("E說").  They never
    reach the dictionary — segmentation keeps only the target script — but
    they make the "read" line look wrong.  Only ever applied to CJK/Hangul
    languages, where a lone roman letter is always noise.
    """
    if not text:
        return text
    return re.sub(r"(?<![0-9A-Za-z])[A-Za-z](?![0-9A-Za-z])", "", text).strip()


def ocr_text(cgimg, lang):
    """Return recognized text, ordered for horizontal or vertical layouts."""
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(0)                      # accurate
    req.setRecognitionLanguages_(list(lang.ocr_langs))
    req.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cgimg, {})
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        return ""
    obs = req.results() or []
    items = []
    for o in obs:
        cands = o.topCandidates_(1)
        if not cands or len(cands) == 0:
            continue
        bb = o.boundingBox()
        items.append((bb, cands[0].string()))
    if not items:
        return ""
    tall = sum(1 for bb, _ in items if bb.size.height > bb.size.width * 1.3)
    if lang.vertical_ok and tall > len(items) / 2.0:
        # vertical CJK: columns run right to left
        items.sort(key=lambda it: -it[0].origin.x)
    else:
        # Bucket into lines by text height before sorting left-to-right, so two
        # fragments of the same line don't swap just because one sits a pixel
        # higher than the other.
        heights = sorted(bb.size.height for bb, _ in items)
        band = max(heights[len(heights) // 2], 0.01)
        items.sort(key=lambda it: (-int(it[0].origin.y / band), it[0].origin.x))
    text = "".join(t for _, t in items)
    return denoise(text) if lang.strip_stray_latin else text


# ---------------------------------------------------------- results text ---

def attr(text, font, color, para=None):
    d = {NSFontAttributeName: font, NSForegroundColorAttributeName: color}
    if para is not None:
        d[NSParagraphStyleAttributeName] = para
    return NSAttributedString.alloc().initWithString_attributes_(text, d)


def make_para(head=0.0, before=0.0, after=0.0, lead=2.0):
    p = NSMutableParagraphStyle.alloc().init()
    p.setHeadIndent_(head)
    p.setFirstLineHeadIndent_(0.0)
    p.setParagraphSpacingBefore_(before)
    p.setParagraphSpacing_(after)
    p.setLineSpacing_(lead)
    p.setLineBreakMode_(NSLineBreakByWordWrapping)
    return p



def word_font(lang, size):
    if lang.font_name:
        f = NSFont.fontWithName_size_(lang.font_name, size)
        if f is not None:
            return f
    return rounded_font(size, True)


def build_results(raw_text, lang):
    """-> (attributed string, speakables)

    `speakables` is what the speaker icons point at: index -> (text, voice).
    """
    out = NSMutableAttributedString.alloc().init()
    speakables = []

    said = set()

    def add_speaker(text, group=None):
        if not lang.tts_lang or not text:
            return
        key = (group, text.lower())
        if group is not None and key in said:
            return          # same pronunciation, already has an icon
        said.add(key)
        speakables.append((text, lang.tts_lang))
        out.appendAttributedString_(attr(" ", rounded_font(11), C_INK_SOFT))
        out.appendAttributedString_(speak_link(len(speakables) - 1))

    if not raw_text.strip():
        out.appendAttributedString_(attr(
            "( ˃̣̣̥ ⌓ ˂̣̣̥ )  nothing found\n",
            rounded_font(15, True), C_DEEP, make_para(after=4)))
        out.appendAttributedString_(attr(
            "Try covering a bit less text, zooming the page in, or nudging the "
            "frame so a whole line sits inside it. Check the language in the "
            "title bar matches the page, too.",
            rounded_font(11.5), C_INK_SOFT, make_para(lead=3)))
        return out, speakables

    out.appendAttributedString_(attr("read  ", rounded_font(10, True), C_DEEP))
    out.appendAttributedString_(attr(raw_text, word_font(lang, 14), C_INK,
                                     make_para(after=9, lead=3)))
    add_speaker(raw_text)
    out.appendAttributedString_(attr("\n", word_font(lang, 14), C_INK,
                                     make_para(after=9, lead=3)))

    if not lang.has_script(raw_text):
        out.appendAttributedString_(attr(
            "No %s text in that — the frame may be over artwork, or the "
            "language picker may be set wrong." % lang.label,
            rounded_font(11.5), C_INK_SOFT, make_para(lead=3)))
        return out, speakables

    if not lang.ready:
        out.appendAttributedString_(attr("loading the %s dictionary, one sec…"
                                         % lang.label,
                                         rounded_font(11.5), C_INK_SOFT))
        return out, speakables

    para_word = make_para(head=26, before=8, after=1, lead=0)
    para_def = make_para(head=26, after=2, lead=2.0)

    for word in lang.words(raw_text):
        if not word.entries:
            out.appendAttributedString_(
                attr(word.surface + "  ", word_font(lang, 20), C_INK, para_word))
            out.appendAttributedString_(attr("not in the dictionary\n",
                                             rounded_font(10.5), C_INK_SOFT, para_word))
            continue

        for n, entry in enumerate(word.entries):
            # Headword and pronunciation share a line, so a speech bubble's
            # worth of vocabulary fits without scrolling.
            if n == 0:
                out.appendAttributedString_(
                    attr(word.surface + "  ", word_font(lang, 20), C_INK, para_word))
            else:
                out.appendAttributedString_(
                    attr("or  ", rounded_font(10), C_INK_SOFT, para_word))

            # Each pronunciation gets its own speaker, so a word with several
            # readings (那个 nà ge / nèi ge) can be heard either way.
            for r, reading in enumerate(entry.readings):
                if r:
                    out.appendAttributedString_(
                        attr("  · ", rounded_font(11), C_INK_SOFT, para_word))
                if reading.label:
                    out.appendAttributedString_(
                        attr(reading.label + " ", rounded_font(11), C_INK_SOFT,
                             para_word))
                for i, (text, tone) in enumerate(reading.parts):
                    if i:
                        out.appendAttributedString_(
                            attr(" ", rounded_font(14.5), C_INK_SOFT, para_word))
                    if tone in ("romaji", "label"):
                        out.appendAttributedString_(
                            attr(text, rounded_font(13), C_INK_SOFT, para_word))
                    else:
                        color = TONE_COLORS.get(tone, C_DEEP)
                        out.appendAttributedString_(
                            attr(text, rounded_font(14.5, True), color, para_word))
                add_speaker(reading.speech, group=id(word))

            if entry.note:
                out.appendAttributedString_(
                    attr("  " + entry.note, word_font(lang, 12), C_INK_SOFT, para_word))
            out.appendAttributedString_(attr("\n", rounded_font(5), C_INK, para_word))

            for gloss in entry.glosses:
                out.appendAttributedString_(
                    attr("· " + lang.clean_gloss(gloss) + "\n",
                         rounded_font(11.5), C_INK_SOFT, para_def))

    if lang.code == "zh":
        out.appendAttributedString_(attr(
            "\ntones:  ", rounded_font(9.5, True), C_INK_SOFT, make_para(before=8)))
        for n, label in ((1, "1 ā"), (2, "2 á"), (3, "3 ǎ"),
                         (4, "4 à"), (5, "5 a")):
            out.appendAttributedString_(
                attr(label + "   ", rounded_font(9.5, True), TONE_COLORS[n]))
    return out, speakables



# ------------------------------------------------------------- the app ---
# ------------------------------------------------------------- the app ---

class Lens(NSObject):

    def init(self):
        self = objc.super(Lens, self).init()
        cfg = load_settings()
        set_theme(float(cfg.get("hue", DEFAULT_HUE)),
                  float(cfg.get("sat", DEFAULT_SAT)))
        self.frame_w = float(cfg.get("frame_w", FRAME_W_DEFAULT))
        self.frame_h = float(cfg.get("frame_h", FRAME_H_DEFAULT))
        self.lang = langs.get(cfg.get("lang", "zh"))
        self.expanded = True
        self._suppress_move = 0
        self._move_timer = None
        self._pending = None
        self._busy = False
        self._speakables = []
        self._last_text = None
        return self

    # ---- construction -------------------------------------------------

    @objc.python_method
    def build(self):
        h = (HEADER_H + self.frame_h + 2 * FRAME_PAD
             + (RESULTS_H if self.expanded else 0))
        scr = NSScreen.mainScreen().visibleFrame()
        frame = NSMakeRect(scr.origin.x + 60, scr.origin.y + scr.size.height - h - 60,
                           max(WIN_W_MIN, self.frame_w + 2 * FRAME_INSET), h)

        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False)
        win.setTitle_("Translation Lens")
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(True)
        win.setLevel_(NSFloatingWindowLevel)
        win.setFloatingPanel_(True)
        win.setBecomesKeyOnlyIfNeeded_(True)
        win.setMovableByWindowBackground_(True)
        win.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary)
        self.win = win

        content = win.contentView()
        content.setWantsLayer_(True)

        self.chrome = ChromeView.alloc().initWithFrame_(content.bounds())
        self.chrome.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        content.addSubview_(self.chrome)

        self.axolotl = AxolotlView.alloc().initWithFrame_(NSMakeRect(0, 0, 24, 24))
        content.addSubview_(self.axolotl)

        self.titleView = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.titleView.setEditable_(False)
        self.titleView.setSelectable_(False)
        self.titleView.setDrawsBackground_(False)
        self.titleView.setTextContainerInset_(NSMakeSize(0, 0))
        self.titleView.textContainer().setLineFragmentPadding_(0)
        self.titleView.textStorage().setAttributedString_(
            attr("Translation Lens", rounded_font(13, True), C_TITLE))
        content.addSubview_(self.titleView)

        self.btnTheme = self._button("paintpalette", "◐", "themeMenu:", "Colors")
        self.btnLang = self._button("globe", "文", "langMenu:", "Language")
        self.btnSize = self._button("arrow.up.left.and.arrow.down.right", "⤢",
                                    "sizeMenu:", "Frame size")
        self.btnRead = self._button("magnifyingglass", "读", "readNow:", "Read again")
        self.btnToggle = self._button("chevron.up", "▾", "toggleResults:", "Show / hide results")
        self.btnClose = self._button("xmark", "✕", "quitApp:", "Quit")
        for b in (self.btnTheme, self.btnLang, self.btnSize, self.btnRead,
                  self.btnToggle, self.btnClose):
            content.addSubview_(b)

        self.scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.scroll.setDrawsBackground_(False)
        self.scroll.setHasVerticalScroller_(True)
        self.scroll.setBorderType_(0)
        self.scroll.setAutohidesScrollers_(True)
        self.text = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.text.setEditable_(False)
        self.text.setDrawsBackground_(False)
        self.text.setTextContainerInset_(NSMakeSize(13, 10))
        self.text.setVerticallyResizable_(True)
        self.text.setHorizontallyResizable_(False)
        self.text.setAutoresizingMask_(NSViewWidthSizable)
        self.text.textContainer().setWidthTracksTextView_(True)
        self.text.setDelegate_(self)
        # keep our own colors: default link styling would repaint headwords blue
        self.text.setLinkTextAttributes_(
            {NSCursorAttributeName: NSCursor.pointingHandCursor()})
        self.scroll.setDocumentView_(self.text)
        content.addSubview_(self.scroll)

        self.gripCorner = GripView.alloc().initWithFrame_(NSMakeRect(0, 0, 16, 16))
        self.gripRight = GripView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 30))
        self.gripBottom = GripView.alloc().initWithFrame_(NSMakeRect(0, 0, 30, 10))
        for g, axis in ((self.gripCorner, "both"), (self.gripRight, "h"),
                        (self.gripBottom, "v")):
            g.owner = self
            g.axis = axis
            content.addSubview_(g)

        self.refreshTitle()
        self.layout()
        self._sync_toggle_icon()
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "windowMoved:", "NSWindowDidMoveNotification", win)

        win.orderFrontRegardless()
        return win

    @objc.python_method
    def _button(self, symbol, fallback, action, tip):
        b = PillButton.alloc().initWithFrame_(NSMakeRect(0, 0, 22, 22))
        b.setBordered_(False)
        b.setButtonType_(NSButtonTypeMomentaryChange)
        img = None
        try:
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, tip)
        except Exception:
            img = None
        if img is not None:
            img.setTemplate_(True)
            b.setImage_(img)
            b.setContentTintColor_(C_TITLE)
            b.setTitle_("")
            b.setImagePosition_(1)   # NSImageOnly
        else:
            b.setAttributedTitle_(attr(fallback, rounded_font(13, True), C_TITLE))
        b.setTarget_(self)
        b.setAction_(action)
        b.setToolTip_(tip)
        return b

    # ---- layout -------------------------------------------------------

    @objc.python_method
    def layout(self):
        W = max(WIN_W_MIN, self.frame_w + 2 * FRAME_INSET)
        res_h = RESULTS_H if self.expanded else 0
        band_h = self.frame_h + 2 * FRAME_PAD
        H = HEADER_H + band_h + res_h

        header = NSMakeRect(0, band_h + res_h, W, HEADER_H)
        frame = NSMakeRect(FRAME_INSET, res_h + FRAME_PAD, self.frame_w, self.frame_h)
        panel = NSMakeRect(0, 0, W, res_h)

        self.chrome.header_rect = header
        self.chrome.frame_rect = frame
        self.chrome.panel_rect = panel
        self.chrome.setNeedsDisplay_(True)

        self.axolotl.setFrame_(NSMakeRect(9, header.origin.y + 5, 24, 24))
        self.titleView.setFrame_(NSMakeRect(38, header.origin.y + 9, 150, 17))

        bx = W - 8
        for b in (self.btnClose, self.btnToggle, self.btnRead, self.btnSize,
                  self.btnLang, self.btnTheme):
            bx -= 23
            b.setFrame_(NSMakeRect(bx, header.origin.y + 6, 22, 22))

        self.scroll.setFrame_(NSMakeRect(2, 2, W - 4, max(res_h - 4, 0)))
        self.scroll.setHidden_(res_h == 0)

        # Handles scale with the frame, so a character-sized frame isn't
        # swamped by its own controls.
        def clamp(v, lo, hi):
            return max(lo, min(hi, v))

        right = frame.origin.x + frame.size.width
        bottom = frame.origin.y
        mid_y = frame.origin.y + frame.size.height / 2.0
        mid_x = frame.origin.x + frame.size.width / 2.0
        corner = clamp(min(frame.size.width, frame.size.height) * 0.30, 10, 16)
        vlen = clamp(frame.size.height * 0.45, 12, 30)
        hlen = clamp(frame.size.width * 0.45, 12, 30)
        self.gripCorner.setFrame_(NSMakeRect(right - corner, bottom + 1, corner, corner))
        self.gripRight.setFrame_(NSMakeRect(right - 5, mid_y - vlen / 2, 10, vlen))
        self.gripBottom.setFrame_(NSMakeRect(mid_x - hlen / 2, bottom - 5, hlen, 10))

        self._set_window_height(H, W)

    @objc.python_method
    def _set_window_height(self, H, W):
        f = self.win.frame()
        top = f.origin.y + f.size.height
        newf = NSMakeRect(f.origin.x, top - H, W, H)
        if (abs(newf.size.height - f.size.height) > 0.5
                or abs(newf.size.width - f.size.width) > 0.5):
            self._suppress_move += 1
            self.win.setFrame_display_(newf, True)

    def resizeFrameTo_(self, size):
        self.frame_w = max(FRAME_W_MIN, min(FRAME_W_MAX, size.width))
        self.frame_h = max(FRAME_H_MIN, min(FRAME_H_MAX, size.height))
        self.chrome.size_badge = "%d × %d" % (self.frame_w, self.frame_h)
        self.layout()

    @objc.python_method
    def endResize(self):
        save_settings(frame_w=self.frame_w, frame_h=self.frame_h)
        self.chrome.size_badge = None
        self.chrome.setNeedsDisplay_(True)
        self.scheduleRead()

    def themeMenu_(self, sender):
        menu = NSMenu.alloc().init()
        menu.setFont_(rounded_font(12))
        swatches = NSMenuItem.alloc().init()
        swatches.setView_(SwatchPickerView.alloc().initWithOwner_(self))
        menu.addItem_(swatches)
        menu.addItem_(NSMenuItem.separatorItem())
        custom = menu.addItemWithTitle_action_keyEquivalent_(
            "Custom color…", "customColor:", "")
        custom.setTarget_(self)
        self.popUp(menu, sender)

    def customColor_(self, sender):
        """Let the accent be any color; the palette derives from its hue."""
        try:
            NSApp.activateIgnoringOtherApps_(True)
            panel = NSColorPanel.sharedColorPanel()
            panel.setColor_(C_HEADER)
            panel.setTarget_(self)
            panel.setAction_("colorChanged:")
            panel.setShowsAlpha_(False)
            panel.makeKeyAndOrderFront_(None)
        except Exception:
            traceback.print_exc()

    def colorChanged_(self, panel):
        try:
            c = panel.color().colorUsingColorSpace_(
                NSColorSpace.sRGBColorSpace())
            if c is None:
                return
            hue = c.hueComponent() * 360.0
            # keep saturation in a range that stays readable as a background
            sat = max(0.25, min(1.0, c.saturationComponent() * 1.4))
            self.applyTheme(hue, sat)
        except Exception:
            traceback.print_exc()

    @objc.python_method
    def applyTheme(self, hue, sat):
        set_theme(hue, sat)
        save_settings(hue=hue, sat=sat)
        self.refreshTitle()
        self._restyle_buttons()
        # attributed strings hold their colors, so the panel must be rebuilt
        self.rerender()
        self.chrome.setNeedsDisplay_(True)
        self.axolotl.setNeedsDisplay_(True)
        self.win.contentView().setNeedsDisplay_(True)

    @objc.python_method
    def _restyle_buttons(self):
        for b in (self.btnTheme, self.btnLang, self.btnSize, self.btnRead,
                  self.btnToggle, self.btnClose):
            try:
                b.setContentTintColor_(C_TITLE)
            except Exception:
                pass

    @objc.python_method
    def rerender(self):
        """Redraw the results panel with the current palette."""
        if self._last_text is None:
            body = _welcome(self.lang)
            self._speakables = []
        else:
            body, self._speakables = build_results(self._last_text, self.lang)
        self.text.textStorage().setAttributedString_(body)

    def langMenu_(self, sender):
        menu = NSMenu.alloc().init()
        menu.setFont_(rounded_font(12))
        for lang in langs.LANGUAGES:
            item = menu.addItemWithTitle_action_keyEquivalent_(
                "%s   %s" % (lang.label, lang.native), "pickLanguage:", "")
            item.setTarget_(self)
            item.setRepresentedObject_(lang.code)
            if lang.code == self.lang.code:
                item.setState_(1)
        # popUpContextMenu:withEvent: wants a mouse-DOWN event, but a button
        # fires its action on mouse-UP; handing it the wrong event made the
        # menu track erratically.  This API needs no event at all.
        self.popUp(menu, sender)

    def pickLanguage_(self, item):
        try:
            self._pick_language(str(item.representedObject()))
        except Exception:
            traceback.print_exc()
        # whatever happened, make sure the lens is still in front
        self.win.orderFrontRegardless()

    @objc.python_method
    def _pick_language(self, code):
        if code == self.lang.code:
            return
        self.lang = langs.get(code)
        save_settings(lang=code)
        self.refreshTitle()
        if self.lang.ready:
            self.scheduleRead()
        else:
            # first use of this language: the lexicon load takes a moment
            self.text.textStorage().setAttributedString_(attr(
                "loading the %s dictionary…" % self.lang.label,
                rounded_font(12), C_INK_SOFT, make_para(lead=3)))
            self._expand_if_needed()
            threading.Thread(target=self._load_lang, args=(self.lang,),
                             daemon=True).start()

    @objc.python_method
    def _load_lang(self, lang):
        pool = NSAutoreleasePool.alloc().init()
        try:
            lang.load()
        except Exception:
            traceback.print_exc()
        if lang is self.lang:
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "readNow:", None, False)
        del pool

    @objc.python_method
    def refreshTitle(self):
        self.titleView.textStorage().setAttributedString_(
            attr("Translation Lens", rounded_font(13, True), C_TITLE))
        self.titleView.textStorage().appendAttributedString_(
            attr("  " + self.lang.native, rounded_font(11, True),
                 C_TITLE_SUB))

    def sizeMenu_(self, sender):
        menu = NSMenu.alloc().init()
        menu.setFont_(rounded_font(12))
        for title, w, h in PRESETS:
            item = menu.addItemWithTitle_action_keyEquivalent_(
                "%s  (%d × %d)" % (title, w, h), "applyPreset:", "")
            item.setTarget_(self)
            item.setRepresentedObject_([w, h])
        menu.addItem_(NSMenuItem.separatorItem())
        hint = menu.addItemWithTitle_action_keyEquivalent_(
            "…or drag the handles on the frame", None, "")
        hint.setEnabled_(False)
        # popUpContextMenu:withEvent: wants a mouse-DOWN event, but a button
        # fires its action on mouse-UP; handing it the wrong event made the
        # menu track erratically.  This API needs no event at all.
        self.popUp(menu, sender)

    def applyPreset_(self, item):
        try:
            w, h = item.representedObject()
            self.resizeFrameTo_(NSMakeSize(float(w), float(h)))
            self.endResize()
        except Exception:
            traceback.print_exc()
        self.win.orderFrontRegardless()

    # ---- actions ------------------------------------------------------

    def windowMoved_(self, note):
        if self._suppress_move > 0:
            self._suppress_move -= 1
            return
        self.scheduleRead()

    @objc.python_method
    def scheduleRead(self):
        if self._move_timer is not None:
            self._move_timer.cancel()
        self._move_timer = threading.Timer(0.38, self._fire_read)
        self._move_timer.daemon = True
        self._move_timer.start()

    @objc.python_method
    def _fire_read(self):
        self.performSelectorOnMainThread_withObject_waitUntilDone_("readNow:", None, False)

    def readNow_(self, sender):
        if self._busy:
            return
        self._busy = True
        self.chrome.busy = True
        self.chrome.setNeedsDisplay_(True)

        lens_screen = self.win.convertRectToScreen_(self.chrome.frame_rect)
        win_no = self.win.windowNumber()
        t = threading.Thread(target=self._worker,
                             args=(win_no, lens_screen, self.lang), daemon=True)
        t.start()

    @objc.python_method
    def _worker(self, win_no, lens_screen, lang):
        pool = NSAutoreleasePool.alloc().init()
        text = ""
        err = None
        try:
            if not Quartz.CGPreflightScreenCaptureAccess():
                # Where the app is running from can make the permission
                # impossible to keep; say so rather than asking again.
                err = install_problem()
                if err is None:
                    # Must stay on this background thread: the request blocks
                    # until the user answers, and on the main thread that would
                    # freeze the run loop before the window ever draws.
                    Quartz.CGRequestScreenCaptureAccess()
                    err = "permission"
            else:
                img = capture_below_window(win_no, lens_screen)
                if img is None:
                    err = "permission"
                else:
                    h = Quartz.CGImageGetHeight(img)
                    factor = 1.0
                    if h < 300:
                        factor = min(4.0, max(1.0, 300.0 / max(h, 1)))
                    big = upscale(img, factor)
                    text = ocr_text(big, lang)
                    if lang.vertical_ok and len(CJK_RE.findall(text)) < 2:
                        # probably a vertical speech bubble
                        strip = reflow_vertical(big)
                        if strip is not None:
                            alt = ocr_text(strip, lang)
                            if len(CJK_RE.findall(alt)) > len(CJK_RE.findall(text)):
                                text = alt
        except Exception:
            err = traceback.format_exc()
        self._pending = (text, err, lang)
        self.performSelectorOnMainThread_withObject_waitUntilDone_("applyResult:", None, False)
        del pool

    def applyResult_(self, _):
        self._busy = False
        self.chrome.busy = False
        self.chrome.setNeedsDisplay_(True)
        text, err, lang = self._pending or ("", None, self.lang)
        if err in ("translocated", "volume"):
            body = NSMutableAttributedString.alloc().init()
            body.appendAttributedString_(attr(
                "Please move Translation Lens to Applications\n",
                rounded_font(14, True), C_DEEP, make_para(after=5)))
            where = ("the disk image" if err == "volume"
                     else "a temporary location macOS created for it")
            body.appendAttributedString_(attr(
                "Translation Lens is running from %s, and macOS will not "
                "remember the Screen Recording permission for an app there — "
                "you can grant it, but it is forgotten immediately.\n\n"
                "To fix it for good:\n"
                "1.  Quit Translation Lens.\n"
                "2.  Drag Translation Lens into your Applications folder.\n"
                "3.  Open it from Applications and allow Screen Recording.\n"
                "4.  Quit and open it once more.\n\n"
                "If it still asks after that, open Terminal and run:\n"
                "xattr -dr com.apple.quarantine \"/Applications/Translation Lens.app\""
                % where,
                rounded_font(11.5), C_INK_SOFT, make_para(lead=3)))
            self._speakables = []
            self.text.textStorage().setAttributedString_(body)
            self._expand_if_needed()
            return
        if err == "permission":
            body = NSMutableAttributedString.alloc().init()
            body.appendAttributedString_(attr(
                "Screen Recording permission needed\n",
                rounded_font(14, True), C_DEEP, make_para(after=5)))
            body.appendAttributedString_(attr(
                "System Settings → Privacy & Security → Screen & System Audio Recording, "
                "switch on “Translation Lens”, then quit and reopen the app.\n\n"
                "That permission is what lets the lens see the page underneath it.",
                rounded_font(11.5), C_INK_SOFT, make_para(lead=3)))
            self._speakables = []
            self.text.textStorage().setAttributedString_(body)
            self._expand_if_needed()
            return
        if err:
            self.text.textStorage().setAttributedString_(
                attr(err, NSFont.userFixedPitchFontOfSize_(10), C_INK_SOFT))
            self._expand_if_needed()
            return
        self._last_text = text
        body, self._speakables = build_results(text, lang)
        self.text.textStorage().setAttributedString_(body)
        self.text.scrollRangeToVisible_((0, 0))
        self._expand_if_needed()

    @objc.python_method
    def _expand_if_needed(self):
        if not self.expanded:
            self.expanded = True
            self._sync_toggle_icon()
            self.layout()

    @objc.python_method
    def _sync_toggle_icon(self):
        name = "chevron.up" if self.expanded else "chevron.down"
        try:
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, "toggle")
            if img is not None:
                img.setTemplate_(True)
                self.btnToggle.setImage_(img)
                return
        except Exception:
            pass
        self.btnToggle.setAttributedTitle_(
            attr("▾" if self.expanded else "▴", rounded_font(13, True), C_TITLE))

    def textView_clickedOnLink_atIndex_(self, view, link, index):
        target = str(link)
        if not target.startswith("speak:"):
            return False
        try:
            text, tag = self._speakables[int(target[6:])]
        except (ValueError, IndexError):
            return True
        # option-click reads it back slowly
        slow = bool(NSApp.currentEvent()
                    and NSApp.currentEvent().modifierFlags() & (1 << 19))
        SPEAKER.speak(text, tag, slow=slow)
        return True

    def textView_clickedOnCell_inRect_atIndex_(self, view, cell, rect, index):
        """AppKit routes attachment clicks here rather than to the link
        handler, depending on the run; honour both."""
        link, _range = view.textStorage().attribute_atIndex_effectiveRange_(
            NSLinkAttributeName, index, None)
        if link is not None:
            self.textView_clickedOnLink_atIndex_(view, link, index)

    @objc.python_method
    def popUp(self, menu, sender):
        """Show a menu, then give focus back to whatever the user was reading.

        Opening a menu forces the app to activate, and a non-activating panel
        that suddenly holds focus swallows the next keystroke — ⌘Q quits it and
        ⌘H hides it, which looks exactly like the window vanishing.  Handing
        activation back afterwards keeps those keys with the app the user is
        actually reading in.
        """
        self._menu = menu           # keep it alive for the tracking loop
        menu.popUpMenuPositioningItem_atLocation_inView_(
            None, NSMakePoint(0, -2), sender)
        self.win.orderFrontRegardless()
        NSApp.deactivate()

    def showCredits_(self, sender):
        self._speakables = []
        self.text.textStorage().setAttributedString_(credits_text())
        self.text.scrollRangeToVisible_((0, 0))
        self._expand_if_needed()
        self.win.orderFrontRegardless()

    def showLens_(self, sender):
        """Bring the lens back, wherever it went."""
        NSApp.unhide_(self)
        self.win.setLevel_(NSFloatingWindowLevel)
        self.win.setAlphaValue_(1.0)
        if not self.expanded:
            self.expanded = True
            self._sync_toggle_icon()
            self.layout()
        self.win.orderFrontRegardless()

    def recenterLens_(self, sender):
        """Park it in the middle of the screen — the way out of 'I lost it'."""
        vis = NSScreen.mainScreen().visibleFrame()
        f = self.win.frame()
        self.showLens_(sender)
        self._suppress_move += 1
        self.win.setFrameOrigin_(NSMakePoint(
            vis.origin.x + (vis.size.width - f.size.width) / 2.0,
            vis.origin.y + (vis.size.height - f.size.height) * 0.72))

    def toggleResults_(self, sender):
        self.expanded = not self.expanded
        self._sync_toggle_icon()
        self.layout()

    def quitApp_(self, sender):
        NSApp.terminate_(self)


class AppDelegate(NSObject):

    @objc.python_method
    def build_status_item(self):
        """A menu-bar item: the lens floats without a dock window of its own,
        so this is the reliable way back if it ever goes missing."""
        bar = NSStatusBar.systemStatusBar()
        self.status = bar.statusItemWithLength_(NSVariableStatusItemLength)
        size = 18.0
        icon = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
        icon.lockFocus()
        draw_axolotl(0, 0, size)
        icon.unlockFocus()
        self.status.button().setImage_(icon)
        self.status.button().setToolTip_("Translation Lens")

        menu = NSMenu.alloc().init()
        menu.setFont_(rounded_font(13))
        for title, sel, key in (
                ("Show Lens", "showLens:", ""),
                ("Recenter on Screen", "recenterLens:", ""),
                (None, None, None),
                ("Licenses & Credits", "showCredits:", ""),
                (None, None, None),
                ("Quit Translation Lens", "terminate:", "q")):
            if title is None:
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            item = menu.addItemWithTitle_action_keyEquivalent_(title, sel, key)
            item.setTarget_(None if sel == "terminate:" else self.lens)
        self.status.setMenu_(menu)

    def applicationDidFinishLaunching_(self, note):
        self.lens = Lens.alloc().init()
        self.lens.build()
        self.lens.text.textStorage().setAttributedString_(_welcome(self.lens.lang))
        build_menu()
        self.build_status_item()
        threading.Thread(target=self._load_dict, daemon=True).start()

    @objc.python_method
    def _load_dict(self):
        pool = NSAutoreleasePool.alloc().init()
        try:
            self.lens.lang.load()
            if self.lens.lang.code == "zh":
                import jieba
                jieba.setLogLevel(60)
                jieba.initialize()
            if not Quartz.CGPreflightScreenCaptureAccess():
                Quartz.CGRequestScreenCaptureAccess()
        except Exception:
            traceback.print_exc()
        del pool

    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        # The lens is the only window; losing it must not kill the app,
        # because the menu-bar item can always bring it back.
        return False

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible):
        self.lens.showLens_(None)
        return True

    def applicationWillTerminate_(self, note):
        sys.stderr.write("Translation Lens terminating\n")
        sys.stderr.flush()


GREETINGS = {"zh": "你好!", "ja": "こんにちは!", "ko": "안녕하세요!",
             "fr": "Bonjour !", "es": "¡Hola!", "it": "Ciao!", "de": "Hallo!",
             "pt": "Olá!", "cs": "Ahoj!", "tr": "Merhaba!", "la": "Salve!"}


def _welcome(lang):
    s = NSMutableAttributedString.alloc().init()
    s.appendAttributedString_(attr(GREETINGS.get(lang.code, "Hello!") + " ",
                                   word_font(lang, 17), C_DEEP,
                                   make_para(after=4)))
    s.appendAttributedString_(attr("Drag me onto a word.\n", rounded_font(14, True),
                                   C_DEEP, make_para(after=6)))
    for line in (
        "Move the pink frame over Chinese text and let go — I read whatever "
        "is underneath and show pinyin + meanings here.",
        "Resize the frame with the three pink handles on it: the right edge "
        "for width, the bottom edge for height, the corner for both. Shrink it "
        "onto a single character, or open it out over a whole bubble.",
        "The ⤢ button has quick sizes — Character, Word, Line, Bubble.",
        "The globe button switches language: Chinese, Japanese, Korean, "
        "French, Spanish, Italian, German. Your choice is remembered.",
        "The magnifier button re-reads without moving; the chevron folds this "
        "panel away so only the frame is left.",
    ):
        s.appendAttributedString_(attr("· " + line + "\n", rounded_font(11.5), C_INK_SOFT,
                                       make_para(head=10, after=4, lead=2.5)))
    if lang.code == "zh":
        s.appendAttributedString_(attr("\nPinyin is colored by tone:  ",
                                       rounded_font(10, True), C_INK_SOFT,
                                       make_para(before=6)))
        for n, label in ((1, "mā"), (2, "má"), (3, "mǎ"), (4, "mà"), (5, "ma")):
            s.appendAttributedString_(attr(label + "  ", rounded_font(12, True),
                                           TONE_COLORS[n]))
    return s


def build_menu():
    menubar = NSMenu.alloc().init()
    item = NSMenuItem.alloc().init()
    menubar.addItem_(item)
    app_menu = NSMenu.alloc().init()
    credits_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Licenses & Credits", "showCredits:", "")
    credits_item.setTarget_(NSApp.delegate().lens)
    app_menu.addItem_(credits_item)
    app_menu.addItem_(NSMenuItem.separatorItem())
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit Translation Lens", "terminate:", "q")
    app_menu.addItem_(quit_item)
    item.setSubmenu_(app_menu)
    NSApp.setMainMenu_(menubar)


def selftest():
    """Verify a built app can actually reach everything it ships with.

    Run as `Translation Lens.app/Contents/MacOS/Translation Lens --selftest`; exits
    non-zero if any language, voice or lexicon is missing from the bundle.
    """
    ok = True
    print("resources:", langs.DATA)
    for lang in langs.LANGUAGES:
        try:
            lang.load()
            probe = {"zh": "世界", "ja": "世界", "ko": "세계", "fr": "monde",
                     "es": "mundo", "it": "mondo", "de": "Welt",
                     "pt": "mundo", "cs": "svět", "tr": "dünya",
                     "la": "mundus"}[lang.code]
            words = lang.words(probe)
            got = bool(words and words[0].entries and words[0].entries[0].glosses)
            voice = SPEAKER.voice(lang.tts_lang) if lang.tts_lang else None
            if lang.tts_lang:
                vname = voice.name() if voice else "MISSING"
            else:
                vname = "(no voice: text only)"
            print("  %-3s %-11s %7d words  lookup=%-5s voice=%s" % (
                lang.code, lang.label, len(lang.entries), "ok" if got else "FAIL",
                vname))
            ok = ok and got and (voice is not None or not lang.tts_lang)
        except Exception as exc:
            print("  %-3s FAILED: %s" % (lang.code, exc))
            ok = False
    zh = langs.get("zh")
    variants = zh.words("那个")[0].entries[0].readings
    print("  zh variant speech:", [(r.label, r.speech) for r in variants])
    ok = ok and len(variants) == 2
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    start_logging()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.activateIgnoringOtherApps_(True)
    app.run()


if __name__ == "__main__":
    main()
