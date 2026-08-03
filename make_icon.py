#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the axolotl mascot into AppIcon.icns."""

import os
import subprocess
import sys

from AppKit import (NSImage, NSBitmapImageRep, NSPNGFileType, NSColor,
                    NSBezierPath, NSGraphicsContext)
from Foundation import NSMakeRect, NSMakeSize

import lens

HERE = os.path.dirname(os.path.abspath(__file__))
ICONSET = os.path.join(HERE, "AppIcon.iconset")


def render(px):
    img = NSImage.alloc().initWithSize_(NSMakeSize(px, px))
    img.lockFocus()
    ctx = NSGraphicsContext.currentContext()
    ctx.setImageInterpolation_(3)

    pad = px * 0.06
    body = NSMakeRect(pad, pad, px - 2 * pad, px - 2 * pad)
    radius = (px - 2 * pad) * 0.22

    from AppKit import NSGradient
    NSGradient.alloc().initWithStartingColor_endingColor_(
        lens.C_PANEL, lens.C_HEADER
    ).drawInBezierPath_angle_(
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(body, radius, radius), 90.0)

    ring = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(body, radius, radius)
    ring.setLineWidth_(px * 0.022)
    lens.C_BORDER.set()
    ring.stroke()

    size = px * 0.72
    lens.draw_axolotl(px / 2 - size / 2, px / 2 - size / 2 - px * 0.02, size)

    img.unlockFocus()

    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    rep.setSize_(NSMakeSize(px, px))
    return rep.representationUsingType_properties_(NSPNGFileType, {})


def main():
    # optional accent hue so the icon can match a chosen theme:
    #   ./.venv/bin/python make_icon.py 205     (Sky)
    if len(sys.argv) > 1:
        lens.set_theme(float(sys.argv[1]),
                       float(sys.argv[2]) if len(sys.argv) > 2 else 1.0)
    os.makedirs(ICONSET, exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = base * scale
            name = "icon_%dx%d%s.png" % (base, base, "@2x" if scale == 2 else "")
            render(px).writeToFile_atomically_(os.path.join(ICONSET, name), True)
    subprocess.check_call(["iconutil", "-c", "icns", ICONSET,
                           "-o", os.path.join(HERE, "AppIcon.icns")])
    print("wrote AppIcon.icns")


if __name__ == "__main__":
    main()
