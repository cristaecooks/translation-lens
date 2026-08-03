#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance check for an installed Translation Lens.

Run this after every rebuild, and any time the app misbehaves:

    ./.venv/bin/python verify.py           # 3 launch/quit cycles
    ./.venv/bin/python verify.py 5         # more cycles

It checks the things that have actually gone wrong in practice — the app
living somewhere macOS can't remember a permission for, stray copies with
different signatures competing for the same permission record, and settings
not surviving a restart.
"""

import json
import os
import plistlib
import subprocess
import sys
import time

import Quartz

APP = "/Applications/Translation Lens.app"
BUNDLE_ID = "com.translationlens.app"
SUPPORT = os.path.expanduser("~/Library/Application Support/Translation Lens")
SETTINGS = os.path.join(SUPPORT, "settings.json")
STATE = os.path.join(SUPPORT, ".verify-state.json")

#: window geometry is derived from the saved frame height, which lets us prove
#: the app actually read its settings file rather than just starting up
HEADER_H, FRAME_PAD, RESULTS_H = 34, 6, 264

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print("  %s  %-46s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def sh(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=120).stdout.strip()
    except Exception:
        return ""


def lens_window():
    """The floating panel, as the window server sees it."""
    for w in Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID):
        if (w.get("kCGWindowOwnerName") == "Translation Lens"
                and w.get("kCGWindowLayer") == 3):
            return w
    return None


def menu_bar_item():
    for w in Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID):
        if (w.get("kCGWindowOwnerName") == "Translation Lens"
                and w.get("kCGWindowLayer") == 25):
            return True
    return False


EXEC_SUFFIX = "/Contents/MacOS/Translation Lens"


def app_procs():
    """(pid, bundle path) for real app processes.

    Matching the path anywhere in `ps` output is not enough: this script's own
    shell command line mentions the path too, which made the app look like it
    was still running after quitting — and made a pattern-based pkill a risk
    to the shell itself.  Only lines whose executable is the app count.
    """
    out = []
    for line in sh("ps", "-eo", "pid=,args=").splitlines():
        line = line.strip()
        if not line:
            continue
        pid, _, args = line.partition(" ")
        args = args.strip()
        if not pid.isdigit() or not args.startswith("/"):
            continue
        if args.endswith(EXEC_SUFFIX):
            out.append((int(pid), args[:-len(EXEC_SUFFIX)]))
    return out


def running():
    return bool(app_procs())


def wait_for(predicate, timeout=25.0, step=0.5):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(step)
    return False


def quit_app():
    for pid, _ in app_procs():
        subprocess.run(["kill", str(pid)], capture_output=True)
    return wait_for(lambda: not running(), timeout=20)


# ---------------------------------------------------------------- checks ---

def check_install_location():
    print("\nINSTALL LOCATION")
    check("app is installed in /Applications", os.path.isdir(APP), APP)

    strays = []
    for root in (os.path.expanduser("~/Desktop"),
                 os.path.expanduser("~/Downloads"),
                 os.path.expanduser("~/translation-lens")):
        for dirpath, dirnames, _ in os.walk(root):
            if dirpath.count(os.sep) - root.count(os.sep) > 3:
                dirnames[:] = []
                continue
            if "Translation Lens.app" in dirnames:
                strays.append(os.path.join(dirpath, "Translation Lens.app"))
                dirnames.remove("Translation Lens.app")
    # a copy inside the build output is expected; anything else competes for
    # the same permission record under a different signature
    unexpected = [p for p in strays
                  if "/translation-lens/dist/" not in p
                  and "/Desktop/Translation Lens/" not in p]
    check("no stray copies outside /Applications", not unexpected,
          "; ".join(unexpected) if unexpected else "only the build copy")

    mounted = [v for v in os.listdir("/Volumes") if "Translation" in v]
    check("no disk image left mounted", not mounted,
          ", ".join(mounted) if mounted else "none")

    quarantine = sh("xattr", APP)
    check("no quarantine flag (avoids App Translocation)",
          "com.apple.quarantine" not in quarantine,
          quarantine or "clean")


def check_identity():
    print("\nIDENTITY macOS USES FOR PERMISSIONS")
    plist = os.path.join(APP, "Contents", "Info.plist")
    bid = ""
    if os.path.exists(plist):
        with open(plist, "rb") as fh:
            bid = plistlib.load(fh).get("CFBundleIdentifier", "")
    check("bundle id is stable", bid == BUNDLE_ID, bid or "missing")

    out = sh("codesign", "-dvvv", APP) + sh("codesign", "-dvvv", "--verbose", APP)
    cdhash = ""
    for line in (sh("codesign", "-dvvv", APP) or "").splitlines():
        if line.lower().startswith("cdhash="):
            cdhash = line.split("=", 1)[1].strip()
    # codesign writes to stderr; fall back to the combined capture
    if not cdhash:
        raw = subprocess.run(["codesign", "-dvvv", APP], capture_output=True,
                             text=True).stderr
        for line in raw.splitlines():
            if line.lower().startswith("cdhash="):
                cdhash = line.split("=", 1)[1].strip()

    prev = {}
    if os.path.exists(STATE):
        try:
            prev = json.load(open(STATE))
        except Exception:
            prev = {}
    changed = prev.get("cdhash") and prev["cdhash"] != cdhash
    check("signature unchanged since last check", not changed,
          "REBUILT — re-grant Screen Recording" if changed
          else (cdhash[:16] or "unknown"))

    os.makedirs(SUPPORT, exist_ok=True)
    json.dump({"cdhash": cdhash}, open(STATE, "w"))

    signed = "adhoc" not in subprocess.run(
        ["codesign", "-dv", APP], capture_output=True, text=True).stderr.lower()
    check("signed with a real Developer ID", signed,
          "ad-hoc — permissions reset on every rebuild" if not signed else "yes")


def check_permission():
    print("\nSCREEN RECORDING")
    granted = Quartz.CGPreflightScreenCaptureAccess()
    # this process is not the app, so treat a negative as advisory only
    check("this checker can capture the screen", bool(granted),
          "if False, the app may also be denied")


def check_selftest():
    print("\nBUNDLE CONTENTS")
    out = subprocess.run([os.path.join(APP, "Contents/MacOS/Translation Lens"),
                          "--selftest"], capture_output=True, text=True,
                         timeout=300).stdout
    check("every lexicon and voice loads", "SELFTEST PASS" in out,
          "%d languages" % out.count("lookup=ok"))


def check_cycles(n):
    print("\nLAUNCH / QUIT CYCLES  (x%d)" % n)
    quit_app()
    for i in range(1, n + 1):
        subprocess.run(["open", APP], capture_output=True)
        up = wait_for(lambda: lens_window() is not None, timeout=30)
        bar = menu_bar_item()
        procs = app_procs()
        path_ok = bool(procs) and all(b == APP for _pid, b in procs)
        gone = quit_app()
        check("cycle %d: window appears" % i, up)
        check("cycle %d: menu-bar item present" % i, bar)
        check("cycle %d: runs from /Applications" % i, path_ok)
        check("cycle %d: quits cleanly" % i, gone)


def check_settings_persist():
    print("\nSETTINGS SURVIVE A RESTART")
    quit_app()
    os.makedirs(SUPPORT, exist_ok=True)
    cfg = {}
    if os.path.exists(SETTINGS):
        try:
            cfg = json.load(open(SETTINGS))
        except Exception:
            cfg = {}
    original = dict(cfg)

    # a distinctive frame height shows up directly in the window geometry
    cfg.update({"frame_h": 118.0, "frame_w": 300.0, "lang": "ja", "hue": 205.0,
                "sat": 0.9})
    json.dump(cfg, open(SETTINGS, "w"))

    subprocess.run(["open", APP], capture_output=True)
    wait_for(lambda: lens_window() is not None, timeout=30)
    w = lens_window()
    expected = HEADER_H + 118 + 2 * FRAME_PAD + RESULTS_H
    got = int(w["kCGWindowBounds"]["Height"]) if w else -1
    check("saved frame size is applied on launch", abs(got - expected) <= 2,
          "height %d, expected %d" % (got, expected))
    quit_app()

    after = json.load(open(SETTINGS))
    check("settings file survives a quit", after.get("lang") == "ja",
          "lang=%s hue=%s" % (after.get("lang"), after.get("hue")))

    json.dump(original, open(SETTINGS, "w"))   # leave the user's setup alone
    print("  (restored your original settings)")


def main():
    cycles = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    if not os.path.isdir(APP):
        print("Translation Lens is not installed in /Applications.")
        return 2
    check_install_location()
    check_identity()
    check_permission()
    check_selftest()
    check_cycles(cycles)
    check_settings_persist()

    failed = [n for n, ok, _ in results if not ok]
    print("\n" + "=" * 62)
    print("%d checks, %d failed" % (len(results), len(failed)))
    for n in failed:
        print("   - %s" % n)
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
