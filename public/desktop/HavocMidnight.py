#!/usr/bin/env python3
"""Havoc Midnight desktop menu. Run with Python 3.10 or later.

The standalone workspace stores its preferences in the current user’s data folder.
The desktop assets are embedded at the end of this file.
"""

import ast
import base64
import hashlib
import http.client
import platform
import uuid
from importlib.util import find_spec
from itertools import groupby
import io
import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import random
import re
import stat
from urllib import error as urlerror, request as urlrequest
import shutil
import socket
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace
from typing import NamedTuple
from zipfile import ZipFile

APP_DIR = Path(__file__).resolve().parent
WINDOW_TITLE = "Havoc Midnight · Local workspace"
CREDITS_TEXT = "made by biggy, dodo"
DEFAULT_DAILY_MESSAGE = 'Zenix is a Bitch'
CUSTOM_FRAME = sys.platform == "win32"


def startup_error(message):
    if sys.stderr:
        print(message, file=sys.stderr)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "Havoc Midnight", 0x10)


try:
    from imgui_bundle import imgui, immapp, hello_imgui, ImVec2, ImVec4
except (ImportError, OSError) as error:
    message = ("Havoc Midnight needs the desktop UI library in this Python environment.\n\n"
               "Windows: py -m pip install imgui-bundle\n"
               "macOS or Linux: python3 -m pip install imgui-bundle pygame\n\n"
               f"{error}")
    if __name__ == "__main__":
        startup_error(message)
        raise SystemExit(1)
    raise

from contextlib import contextmanager
from functools import lru_cache
from array import array
from tempfile import TemporaryDirectory
import queue
import threading
import wave

V = ImVec2


def user_data_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "Havoc Midnight"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Havoc Midnight"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "havoc-midnight"


ROOT = user_data_dir()
ASSET_ROOT = ROOT / "assets" / "bea467457c65ec69"
FONT_BIG = FONT_HUGE = None


def read_object(path):
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return record if isinstance(record, dict) else {}


def write_object(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8"))


def prepare_assets():
    missing = []
    for name, expected in ASSET_DIGESTS.items():
        try:
            actual = hashlib.sha256((ASSET_ROOT / name).read_bytes()).hexdigest()
        except FileNotFoundError:
            actual = ""
        if actual != expected:
            missing.append(name)
    if missing:
        with ZipFile(io.BytesIO(base64.b64decode(ASSET_DATA))) as archive:
            for name in missing:
                data = archive.read(name)
                if hashlib.sha256(data).hexdigest() != ASSET_DIGESTS[name]:
                    raise ValueError(f"The embedded asset {name} is damaged. Download a fresh copy.")
                atomic_write(ASSET_ROOT / name, data)


def rgb(r, g, b, a=1.0):
    return ImVec4(r / 255.0, g / 255.0, b / 255.0, a)

def tint(color, alpha):
    return ImVec4(color.x, color.y, color.z, alpha)

def blend(a, b, t):
    return ImVec4(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t,
                  a.z + (b.z - a.z) * t, a.w + (b.w - a.w) * t)

_ICONS = {
    "brand":   (0x42, 0x66, 0x7e, 0x5a, 0x5a, 0x7e, 0x66, 0x42),
    "home":    (0x18, 0x3c, 0x66, 0xc3, 0x42, 0x5a, 0x5a, 0x7e),
    "library": (0x00, 0xfc, 0x84, 0xfe, 0x82, 0x82, 0xfe, 0x00),
    "device":  (0x00, 0x7e, 0xc3, 0x81, 0xa5, 0xdb, 0x66, 0x00),
    "style":   (0x24, 0x24, 0x74, 0x54, 0x2e, 0x2a, 0x24, 0x24),
    "credits": (0x00, 0x66, 0xff, 0xff, 0x7e, 0x3c, 0x18, 0x00),
    "star":    (0x18, 0x18, 0xff, 0x7e, 0x3c, 0x7e, 0x66, 0x42),
    "power":   (0x18, 0x5a, 0x5a, 0xc3, 0xc3, 0x66, 0x3c, 0x00),
    "arrow":   (0x00, 0x10, 0x18, 0x7c, 0x7c, 0x18, 0x10, 0x00),
}

@lru_cache(maxsize=96)
def _icon_tiles(name, x, y, step):
    tiles = []
    for row, bits in enumerate(_ICONS[name]):
        column = 0
        while column < 8:
            if not bits & (128 >> column):
                column += 1
                continue
            start = column
            while column < 8 and bits & (128 >> column):
                column += 1
            tiles.append((ImVec2(x + start * step, y + row * step),
                          ImVec2(x + column * step, y + (row + 1) * step)))
    return tiles

def draw_icon(dl, name, x, y, size, ink):
    color = imgui.get_color_u32(ink)
    for p, q in _icon_tiles(name, round(x), round(y), max(1, round(size / 8))):
        dl.add_rect_filled(p, q, color)

def _ink(color, opacity):
    return imgui.get_color_u32(tint(color, opacity))

def _aurora(dl, x, y, w, h, accent, alternate, phase):
    # A crisp lower edge and a transparent upper edge give each ribbon a pixel silhouette.
    columns = max(12, min(48, round(w / 16)))
    for layer, shade in enumerate((alternate, blend(alternate, accent, 0.48))):
        clear = _ink(shade, 0)
        for i in range(columns):
            u = (i + 0.5) / columns
            swell = math.sin(u * 6.8 + phase + layer) + 0.32 * math.sin(u * 13 - phase * 1.7)
            hem = y + h * (0.61 - 0.14 * layer + 0.14 * swell)
            reach = h * (0.36 + 0.13 * math.sin(u * 8 - phase + layer))
            strength = math.sin(math.pi * u) * (0.17 + 0.055 * math.sin(u * 23 - 1.5 * phase))
            bright = _ink(shade, strength)
            a, b = round(x + w * i / columns), round(x + w * (i + 1) / columns)
            edge = round(hem / 2) * 2
            dl.add_rect_filled_multi_color(ImVec2(a, edge - reach), ImVec2(b, edge),
                                           clear, clear, bright, bright)
            dl.add_rect_filled_multi_color(ImVec2(a, edge), ImVec2(b, edge + h * 0.08),
                                           bright, bright, clear, clear)

def _signals(dl, x, y, w, h, accent, alternate, phase):
    for lane in range(3):
        low, high = y + h * (0.64 + lane * 0.13), y + h * (0.12 + lane * 0.16)
        first, last = x + w * (0.20 + lane * 0.075), x + w * (0.65 + lane * 0.055)
        turn = min(w * 0.12, low - high)
        rail = (ImVec2(x, low), ImVec2(first, low), ImVec2(first + turn, high),
                ImVec2(last, high), ImVec2(last + turn, low), ImVec2(x + w, low))
        dl.add_polyline(rail, _ink(alternate, 0.18), thickness=1.0, flags=0)
        lengths = [math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(rail, rail[1:])]
        u = (phase * (0.53 + lane * 0.07) + lane * 0.34) % 1
        head = u * sum(lengths)
        glow = math.sin(math.pi * u)
        for a, b, length in zip(rail, rail[1:], lengths):
            if 0 <= head <= length:
                tip = ImVec2(a.x + (b.x - a.x) * head / length, a.y + (b.y - a.y) * head / length)
                dot = min(2.5, max(1.5, h * 0.016))
                dl.add_rect_filled(ImVec2(tip.x - dot, tip.y - dot), ImVec2(tip.x + dot, tip.y + dot),
                                   _ink(accent, 0.88 * glow))
            tail, end = max(0, head - w * 0.070), min(length, head)
            if tail < end:
                dx, dy = (b.x - a.x) / length, (b.y - a.y) / length
                dl.add_line(ImVec2(a.x + dx * tail, a.y + dy * tail),
                            ImVec2(a.x + dx * end, a.y + dy * end), _ink(accent, 0.42 * glow), 1.6)
            head -= length

def _folios(dl, x, y, w, h, accent, alternate, phase):
    half = min(w * 0.125, h * 0.32)
    for stack in range(3):
        breath = 0.5 + 0.5 * math.sin(phase * 2.6 + stack * 1.9)
        cx = x + w * (0.16 + 0.34 * stack)
        cy = y + h * (0.62 - 0.10 * (stack % 2))
        for sheet in range(3):
            lift = cy - sheet * half * (0.13 + 0.25 * breath)
            corners = (ImVec2(cx - half, lift), ImVec2(cx, lift - half * 0.42),
                       ImVec2(cx + half, lift), ImVec2(cx, lift + half * 0.42))
            shade = accent if sheet == 2 else alternate
            dl.add_quad_filled(*corners, _ink(shade, 0.045))
            dl.add_quad(*corners, _ink(shade, 0.14 + 0.045 * sheet))

_STARS = ((0.0, 0.74), (0.16, 0.30), (0.32, 0.51), (0.47, 0.08),
          (0.65, 0.32), (0.78, 0.12), (1.0, 0.46))

def _constellation(dl, x, y, w, h, accent, alternate, phase):
    points = [ImVec2(x + u * w, y + v * h) for u, v in _STARS]
    dl.add_polyline(points, _ink(alternate, 0.24), thickness=1.0, flags=0)
    for i, p in enumerate(points):
        light = 0.5 + 0.5 * math.sin(phase * 2.7 - i * 1.4)
        r = max(1.0, min(3.0, h * 0.035)) * (0.7 + light * 0.7)
        ink = _ink(accent, 0.30 + 0.50 * light)
        dl.add_line(ImVec2(p.x - r * 1.6, p.y), ImVec2(p.x + r * 1.6, p.y), ink)
        dl.add_line(ImVec2(p.x, p.y - r * 1.6), ImVec2(p.x, p.y + r * 1.6), ink)
        if i:
            prev = points[i - 1]
            u = (phase * 0.45 + i * 0.23) % 1
            px, py = prev.x + (p.x - prev.x) * u, prev.y + (p.y - prev.y) * u
            dl.add_rect_filled(ImVec2(px, py), ImVec2(px + 2, py + 2),
                               _ink(accent, 0.56 * math.sin(math.pi * u)))

def _flock(dl, x, y, w, h, ink, phase):
    u = (phase * 0.15 + 0.43) % 1
    color = _ink(ink, 0.77 * min(1, u * 9, (1 - u) * 9))
    wing = max(2, min(7, h * 0.06))
    for i, (dx, dy) in enumerate(((0, 0), (-3, -1), (-5.6, -2.2), (-3.5, 1.8), (-6.8, 3))):
        bx = round(x + w * u + dx * wing)
        by = round(y + h * (0.48 + 0.13 * math.sin(phase * 0.9)) + dy * wing)
        flap = round(wing * (0.15 + 0.55 * math.sin(phase * 9 + i)))
        dl.add_line(ImVec2(bx - wing, by - flap), ImVec2(bx, by), color, 1.4)
        dl.add_line(ImVec2(bx, by), ImVec2(bx + wing, by - flap), color, 1.4)

def draw_ambience(dl, p, q, page, palette, phase, blur=0):
    w, h = q.x - p.x, q.y - p.y
    if w < 40 or h < 30:
        return
    dl.push_clip_rect(p, q, True)
    if blur > 0:
        # A separable 1:2:1 kernel spreads only the translucent scenery.
        # Clip once to the canvas so light cannot bleed into controls outside it.
        alpha = imgui.get_style().alpha
        for dy, wy in ((-blur, 1), (0, 2), (blur, 1)):
            for dx, wx in ((-blur, 1), (0, 2), (blur, 1)):
                imgui.push_style_var(imgui.StyleVar_.alpha, alpha * wx * wy / 16)
                _ambience_layer(dl, ImVec2(p.x + dx, p.y + dy), ImVec2(q.x + dx, q.y + dy),
                                w, h, page, palette, phase)
                imgui.pop_style_var()
    else:
        _ambience_layer(dl, p, q, w, h, page, palette, phase)
    dl.pop_clip_rect()

def _ambience_layer(dl, p, q, w, h, page, palette, phase):
    accent, alternate = rgb(*palette[0]), rgb(*palette[2])
    if page == "sign-in":
        _aurora(dl, p.x, p.y, w, min(170, h * 0.22), accent, alternate, phase)
    elif page == "Appearance":
        _aurora(dl, p.x + w * 0.19, p.y, w * 0.86, min(160, h * 0.23), alternate, accent, -phase)
    elif page == "Connection":
        _signals(dl, p.x + w * 0.21, q.y - h * 0.25, w * 0.83, min(125, h * 0.21), accent, alternate, phase)
    elif page in ("Credits", "public-credits"):
        _constellation(dl, p.x + w * 0.48, q.y - h * 0.16, w * 0.47, h * 0.13, accent, alternate, phase)
    elif page == "Dashboard":
        _flock(dl, p.x, q.y - h * 0.15, w, min(100, h * 0.12), alternate, phase)
    else:
        _folios(dl, p.x + w * 0.35, p.y + 3, w * 0.63, min(108, h * 0.17), accent, alternate, phase)

def draw_opening_orbits(dl, cx, cy, radius, progress, palette):
    for ring, channels in enumerate((palette[2], palette[0])):
        shade = rgb(*channels)
        r = radius * (0.48 + 0.38 * progress + ring * 0.19)
        for i in range(36):
            angle = math.tau * i / 36 + (0.45 - 0.8 * ring) * progress
            x = round(cx + r * math.cos(angle))
            y = round(cy + r * (0.43 + 0.12 * ring) * math.sin(angle) + (x - cx) * (0.21 - ring * 0.40))
            lit = (1 + math.cos(angle * 2 - 4 * progress)) * 0.5
            size = 3 if i % 9 == 0 else 2
            dl.add_rect_filled(ImVec2(x, y), ImVec2(x + size, y + size), _ink(shade, 0.10 + 0.48 * lit))

@lru_cache(maxsize=12)
def _landscape_tiles(x, y, w, h, night, palette, alpha):
    """Global style alpha affects ImGui's color packing and must be part of the cache key."""
    accent, highlight, alternate = (rgb(*channels) for channels in palette)
    p = ImVec2(x, y)
    tiles = []
    s = h / 100
    span = w / s
    color = imgui.get_color_u32
    top = blend(rgb(43, 32, 76), alternate, 0.12)
    dusk = blend(rgb(223, 119, 101), accent, 0.25) if not night else blend(rgb(97, 92, 151), alternate, 0.20)
    glow = blend(rgb(255, 214, 142), highlight, 0.20)
    far = blend(rgb(125, 96, 146), alternate, 0.18)
    middle, ridge, coast = rgb(85, 74, 121), rgb(53, 47, 84), rgb(31, 30, 53)
    stone, light = rgb(57, 45, 76), rgb(183, 124, 132)
    if night:
        far, middle = blend(far, top, 0.35), blend(middle, top, 0.23)

    def block(x, y, width, height, ink):
        a = ImVec2(round(p.x + x * s), round(p.y + y * s))
        b = ImVec2(round(p.x + (x + width) * s), round(p.y + (y + height) * s))
        if b.x > a.x and b.y > a.y:
            tiles.append((a, b, color(ink)))

    sun = span * 0.77
    for i in range(12):
        half = round(math.sqrt(max(0, 13 ** 2 - (i * 2 - 11) ** 2)))
        if i not in (8, 10):
            block(sun - half, 11 + i * 2, half * 2, 2, glow)
    for i in range(17):
        sx, sy = ((i * 61 + 7) % 101) / 101 * span, 4 + (i * 13) % 33
        block(sx, sy, 0.8, 0.8, blend(top, glow, 0.30 + (i % 4) * 0.14))
    cloud = blend(dusk, glow, 0.36)
    for anchor, level, length in ((0.11, 33, 23), (0.37, 18, 13), (0.57, 30, 24), (0.88, 22, 15)):
        x = span * anchor
        block(x, level, length, 1, cloud)
        block(x + 4, level - 2, length * 0.65, 2, cloud)
        block(x + 8, level - 3, length * 0.29, 1, cloud)

    # Overlapping mountain profiles and sunlit ledges above the lake.
    profiles = (
        ((67, 53, 61, 39, 52, 36, 56, 41, 61, 37, 50, 42, 64), far),
        ((70, 66, 48, 60, 53, 69, 59, 48, 62, 56, 44, 59, 66), middle),
        ((73, 66, 69, 70, 59, 70, 65, 70, 65, 48, 58, 64, 59), ridge),
    )
    n = 60
    for layer, (heights, ink) in enumerate(profiles):
        ledge = blend(ink, dusk, 0.31)
        for i in range(n):
            idx, frac = divmod(i, 5)
            level = round((heights[idx] + (heights[idx + 1] - heights[idx]) * frac / 5) / 2) * 2
            x = span * i / n
            block(x, level, span / n, 77 - level, ink)
            if frac in (1, 2) and heights[idx] < heights[idx + 1] and layer < 2:
                block(x, level + 1, span / n, 1.1, ledge)

    # A hilltop observatory with lantern windows and three stepped roofs.
    tower = span * 0.75
    block(tower - 13, 63, 26, 5, ridge)
    block(tower - 8, 45, 16, 20, stone)
    block(tower - 6, 36, 12, 12, stone)
    for level, half in ((35, 7), (42, 11), (52, 14)):
        block(tower - half, level, half * 2, 2, stone)
        block(tower - half + 2, level - 2, (half - 2) * 2, 2, stone)
        block(tower - half + 5, level - 3, (half - 5) * 2, 1, light)
    block(tower - 2, 30, 4, 4, stone)
    block(tower, 26, 1, 5, light)
    for tx, ty in ((-3, 38), (2, 38), (-5, 47), (3, 47), (-5, 56), (3, 56)):
        block(tower + tx, ty, 2, 3, glow)
    block(0, 75, span, 25, middle)
    block(0, 75, span, 1, blend(far, dusk, 0.42))
    for left, right, level in ((0.03, 0.21, 78), (0.34, 0.47, 81), (0.55, 0.68, 77), (0.82, 0.94, 80)):
        block(span * left, level, span * (right - left), 0.7, blend(middle, dusk, 0.33))
    for i in range(27):
        depth = (i * 7) % 22
        xx = ((i * 29 + 13) % 97) / 97 * span
        block(xx, 77 + depth, 3 + (i * 11) % 15, 0.8, blend(middle, far, 0.68))
    for i in range(6):
        length = 12 - i
        block(sun - length / 2 + math.sin(i * 8) * 3, 77 + i * 2,
              length, 0.75, blend(middle, glow, 0.52 - i * 0.05))
    for i in range(30):
        a = i / 30
        line = 95 - 15 * abs(2 * a - 1) ** 1.7 + 2 * math.sin(i * 0.8)
        block(span * a, round(line), span / 30, 101 - round(line), coast)
    for ax, base, height in ((0.008, 90, 18), (0.06, 91, 11), (0.115, 93, 8),
                             (0.89, 92, 8), (0.95, 87, 15), (0.985, 88, 23)):
        x = ax * span
        block(x - 0.6, base - height, 1.2, height, coast)
        for j in range(1, 5):
            half = 0.9 + j * height * 0.058
            block(x - half, base - height + j * height * 0.16, half * 2, height * 0.18, coast)
    return color(top), color(dusk), tiles

def draw_landscape(dl, p, q, palette, phase=0.0, night=False):
    w, h = round(q.x - p.x), round(q.y - p.y)
    if w < 12 or h < 12:
        return
    top, dusk, tiles = _landscape_tiles(round(p.x), round(p.y), w, h, night,
                                        palette, imgui.get_style().alpha)
    dl.push_clip_rect(p, q, True)
    dl.add_rect_filled_multi_color(p, q, top, top, dusk, dusk)
    paint = dl.add_rect_filled
    for a, b, ink in tiles:
        paint(a, b, ink)
    if phase:
        if night:
            _constellation(dl, p.x + w * 0.32, p.y + h * 0.05, w * 0.36, h * 0.19,
                           rgb(255, 230, 180), rgb(205, 183, 236), phase)
        else:
            _flock(dl, p.x, p.y + h * 0.09, w, h * 0.20, rgb(48, 36, 61), phase)
    # A handful of moving highlights can animate without rebuilding the landscape.
    for i in range(4):
        x = round(p.x + w * 0.77 + h * 0.042 * math.sin(phase + i * 2))
        y = round(p.y + h * (0.784 + i * 0.026))
        paint(ImVec2(x, y), ImVec2(x + max(2, round(h / 35)), y + max(1, round(h / 170))),
              imgui.get_color_u32(tint(rgb(255, 210, 159), 0.36 - i * 0.05)))
    dl.pop_clip_rect()

_SPRITES = {
    "device": (
        "................aaaaaaaaaaaaaa........",
        ".............aasssssssssssssssaa......",
        "...........assmlllllllllllllmmssaa....",
        "..........asmlmssaaaaaaaaassssmlmsa...",
        ".........asllmsa.............asslmma..",
        ".........asmmsa...............asmllsa.",
        ".........asmma................asmmmsa.",
        "........aassaaaaaaaaaaaaaaa...asmmsa..",
        ".....aassmlllllllllllllllllmaaasmmsa..",
        "...assmllllllllllllllllllmmmmmaaassa..",
        "..asllmmmmmmmmmmmmmmmmmmmssssmmmasa...",
        ".aslmvvvvvvvvvvvvvvvvvvvmsssssmmma....",
        "aslmvfffvvvfffffffffffffvmssssssma....",
        "aslmvffvvvffffffffffffffvmssssssma....",
        "aslmvfvvvfffffffffffffffvmssggssma....",
        "aslmvvvvfffffffffffffffvvmssggssma....",
        ".asmvfffffffffffffffffvvvmssssmma.....",
        ".asmmvvvvvvvffssssffvvvvmmssmmma......",
        "..assmvvvvvvsmaaaamsvvvmmssmma........",
        "...aassmmmmmsa....asmmmmssmaa.........",
        ".....aaassssa......assssaaa...........",
        "........aaaa........aaaa..............",
    ),
    "library": (
        "...........aaaaaaaaaaaaaa.............",
        "..........allllllllllllllma...........",
        "..........ammvvvvvvvvvvvlma...........",
        "..........amvmmmmmmmmmmvlma...........",
        ".......aaaaaaaaaaaaaaamvlma...........",
        "......allllllllllllllmavlma...........",
        "......ammggggggggggglmavlma...........",
        "......amvggggggggggvlmavlma...........",
        "...aaaaaaaaaaaaaaaaavlmavlma...........",
        "..alllllllllllllllmavlmavlma...........",
        "..amlsssssssssssssmavlmavlma...........",
        "..amlsffffffffffssmavlmavlma...........",
        "..amlsfgggfffggfssmavlmavma............",
        "..amlsfgggfffggfssmavlmaa..............",
        "..amlsffffffffffssmavma................",
        "..amlssssssssssssmmaa..................",
        "..amllllllllllllllma...................",
        "..amvvvvmvvmvvmvvvma...................",
        "...aaaaaaaaaaaaaaaa....................",
    ),
}

def _sprite_runs(rows):
    runs = []
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            ink = row[x]
            stop = x + 1
            while stop < len(row) and row[stop] == ink:
                stop += 1
            if ink != ".":
                runs.append((x, y, stop - x, ink))
            x = stop
    return runs

_SPRITES = {name: (max(map(len, rows)), len(rows), _sprite_runs(rows)) for name, rows in _SPRITES.items()}

def draw_plate(dl, p, q, motif, palette, align=0.5, phase=0):
    alternate = rgb(*palette[2])
    w, h = q.x - p.x, q.y - p.y
    color = imgui.get_color_u32
    shadow, paper = rgb(32, 28, 51), rgb(67, 56, 89)
    ink = blend(paper, alternate, 0.16)
    a, b = color(shadow), color(ink)
    dl.push_clip_rect(p, q, True)
    dl.add_rect_filled_multi_color(p, q, a, b, b, a)
    pitch = max(12, round(h / 9))
    grid = color(tint(alternate, 0.13))
    for x in range(pitch, int(w), pitch):
        dl.add_line(ImVec2(p.x + x, p.y), ImVec2(p.x + x, q.y), grid)
    for y in range(pitch, int(h), pitch):
        dl.add_line(ImVec2(p.x, p.y + y), ImVec2(q.x, p.y + y), grid)
    if phase:
        detail = _signals if motif == "device" else _folios
        detail(dl, p.x, p.y + h * 0.18, w, h * 0.65, rgb(*palette[0]), alternate, phase)
    sw, sh, _ = _SPRITES[motif]
    scale = max(1, min((w * (0.80 if align == 0.5 else 0.43)) / sw, h * 0.74 / sh))
    x0 = round(p.x + w * align - sw * scale / 2)
    y0 = round(p.y + (h - sh * scale) / 2 + math.sin(phase) * min(2, scale * 0.4))
    paint = dl.add_rect_filled
    for a, b, ink in _sprite_tiles(motif, x0, y0, scale, palette, imgui.get_style().alpha):
        paint(a, b, ink)
    dl.pop_clip_rect()

@lru_cache(maxsize=24)
def _sprite_tiles(motif, x0, y0, scale, palette, alpha):
    highlight, alternate = rgb(*palette[1]), rgb(*palette[2])
    paper = rgb(67, 56, 89)
    color = imgui.get_color_u32
    inks = {"a": rgb(32, 27, 49), "s": blend(paper, alternate, 0.32), "m": blend(paper, alternate, 0.69),
               "l": blend(rgb(242, 226, 217), alternate, 0.20), "f": rgb(47, 40, 68),
               "v": blend(paper, alternate, 0.29), "g": blend(rgb(255, 201, 130), highlight, 0.20)}
    colors = {key: color(value) for key, value in inks.items()}
    return [(ImVec2(round(x0 + x * scale), round(y0 + y * scale)),
             ImVec2(round(x0 + (x + length) * scale), round(y0 + (y + 1) * scale)), colors[tone])
            for x, y, length, tone in _SPRITES[motif][2]]


class MenuAudio:
    files = {
        "hover": "sfx_hover.wav",
        "click": "sfx_release_main.wav",
        "back": "sfx_back.wav",
        "open": "ui_appear.wav",
        "close": "ui_disappear.wav",
    }

    def __init__(self, root):
        folders = dict.fromkeys(
            (
                Path(root),
                Path(__file__).resolve().parent,
                Path(getattr(sys, "_MEIPASS", root)),
            )
        )
        self._paths = {}
        for cue, name in self.files.items():
            for folder in folders:
                path = folder / "ui_audio" / name
                if path.is_file():
                    self._paths[cue] = path
                    break
        self.unavailable = not self._paths
        self._events = queue.SimpleQueue()
        self._thread = None
        self.clip_error = ""
        self.clip_backend = find_spec("pygame") is not None
        self._exiting = False
        self._closed = False
        self._volume = 100

    def set_volume(self, percent):
        volume = max(0, min(100, round(percent)))
        if volume != self._volume:
            self._volume = volume
            if self._thread is not None and not self._closed:
                self._events.put("volume")

    def play(self, cue, *, preview=False):
        if self._closed or self._exiting or self.unavailable or cue not in self._paths:
            return
        if self._volume == 0:
            return
        if cue == "close" and not preview:
            self._exiting = True
        self._enqueue("sample_close" if preview and cue == "close" else cue)

    def _enqueue(self, event):
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name="menu-audio", daemon=True
            )
            try:
                self._thread.start()
            except RuntimeError:
                self._thread, self.unavailable = None, True
                return
        self._events.put(event)

    def play_clip(self, path):
        if (
            self.clip_backend
            and not (self._closed or self._exiting or self.unavailable)
            and self._volume
        ):
            self.clip_error = ""
            self._enqueue(Path(path))

    def stop_clip(self):
        if self._thread is not None and not self._closed:
            self._events.put("clip-stop")

    def mute(self):
        if self._thread is not None and not self._closed:
            self._events.put("mute")

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._thread is not None:
            self._events.put(None)
            # Native window teardown can finish while the disappear cue plays out.
            self._thread.join(timeout=2.5)

    def _run(self):
        try:
            try:
                from pygame import mixer

                owns_mixer = not mixer.get_init()
                if owns_mixer:
                    mixer.init(frequency=48000, size=-16, channels=2, buffer=256)
            except (ImportError, OSError, RuntimeError):
                if sys.platform != "win32":
                    raise
                self.clip_backend = False
                self._windows_playback()
                return
            sounds = {}
            clip_loaded = False
            try:
                while (cue := self._events.get()) is not None:
                    if isinstance(cue, Path):
                        try:
                            mixer.music.load(str(cue))
                            clip_loaded = True
                            mixer.music.set_volume(self._volume / 100)
                            mixer.music.play()
                            self.clip_error = ""
                        except (OSError, RuntimeError) as error:
                            self.clip_error = f"Could not play {cue.name}: {error}"
                        continue
                    if cue in ("clip-stop", "mute", "close") and clip_loaded:
                        mixer.music.stop()
                        mixer.music.unload()
                        clip_loaded = False
                    if cue == "clip-stop":
                        continue
                    if cue == "volume":
                        if clip_loaded:
                            mixer.music.set_volume(self._volume / 100)
                        for sound in sounds.values():
                            sound.set_volume(self._volume / 100)
                        continue
                    closing = cue == "close"
                    if cue == "sample_close":
                        cue = "close"
                    if cue == "mute" or closing:
                        for sound in sounds.values():
                            sound.stop()
                        if cue == "mute":
                            continue
                    if cue not in sounds:
                        sounds[cue] = mixer.Sound(str(self._paths[cue]))
                    sound = sounds[cue]
                    sound.set_volume(self._volume / 100)
                    sound.stop()
                    channel = sound.play()
                    if closing and channel is not None:
                        deadline = time.monotonic() + sound.get_length() + 0.1
                        while channel.get_busy() and time.monotonic() < deadline:
                            time.sleep(0.01)
            finally:
                if clip_loaded:
                    mixer.music.unload()
                for sound in sounds.values():
                    sound.stop()
                if owns_mixer:
                    mixer.quit()
        except (ImportError, OSError, RuntimeError, wave.Error, EOFError):
            self.unavailable = True

    def _windows_playback(self):
        import winsound

        flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT
        active, started = None, 0.0
        with TemporaryDirectory(prefix="havoc-audio-") as folder:
            while (event := self._events.get()) is not None:
                if isinstance(event, Path) or event == "clip-stop":
                    continue
                if event == "mute":
                    winsound.PlaySound(None, 0)
                    active = None
                    continue
                elapsed = 0.0
                if event == "volume":
                    if active is None:
                        continue
                    elapsed = time.monotonic() - started
                    winsound.PlaySound(None, 0)
                else:
                    active = "close" if event == "sample_close" else event
                    started = time.monotonic()
                source = self._paths[active]
                if self._volume != 100 or elapsed:
                    # Scale our own PCM stream. Other apps keep their system volume.
                    with wave.open(str(source), "rb") as wav:
                        skip = int(elapsed * wav.getframerate())
                        if skip >= wav.getnframes() or self._volume == 0:
                            active = None
                            continue
                        wav.setpos(skip)
                        samples = array("h", wav.readframes(wav.getnframes() - skip))
                        params = wav.getparams()
                    gain = self._volume / 100
                    samples = array("h", (round(n * gain) for n in samples))
                    source = Path(folder) / (active + ".wav")
                    winsound.PlaySound(None, 0)
                    with wave.open(str(source), "wb") as wav:
                        wav.setparams(params)
                        wav.writeframes(samples.tobytes())
                winsound.PlaySound(
                    str(source), flags | (0 if event == "close" else winsound.SND_ASYNC)
                )
                if event == "close":
                    active = None
            if active is not None:
                winsound.PlaySound(None, 0)


NUMBERS = {
    "scale": (100, 80, 125, "%d%%"), "font_size": (16, 13, 20, "%d px"),
    "border": (1, 0, 4, "%d px"), "rounding": (0, 0, 14, "%d px"),
    "gradient": (0, 0, 100, "%d%%"), "panel_transparency": (0, 0, 75, "%d%%"),
    "speed": (100, 35, 200, "%d%%"), "duration": (160, 60, 450, "%d ms"),
    "softness": (0, 0, 8, "%d px"), "glow": (0, 0, 100, "%d%%"),
    "shadow": (100, 0, 100, "%d%%"), "opacity": (100, 40, 100, "%d%%"),
    "acrylic_tint": (35, 0, 100, "%d%%"),
    "spacing": (100, 65, 145, "%d%%"), "gutter": (0, -8, 24, "%+d px"),
    "sidebar_width": (256, 168, 330, "%d px"), "volume": (100, 0, 100, "%d%%"),
}

CHOICES = {
    "menu_layout": ("Classic", "Midnight"),
    "button": ("Pixel", "Flat", "Outline"),
    "gradient_direction": ("Vertical", "Horizontal", "Diagonal"),
    "transition": ("Slide + fade", "Fade", "Slide", "Instant"),
    "hover": ("Highlight", "Glow", "Off"),
    "sidebar": ("Automatic", "Wide sidebar", "Page selectors"),
    "sidebar_tint": ("Palette", "Accent wash", "Darkened"),
}

FLAGS = {"ambient_motion": True, "background_motion": True, "blur": False, "counts": True,
         "ui_sounds": True, **{"cue_" + k: True for k in ("hover", "click", "back", "open", "close")}}

TONES = {"acc": "Accent", "alt": "Secondary accent", "bg": "Background", "panel": "Panel",
         "card": "Control surface", "edge": "Border", "text": "Text",
         "grad_top": "Gradient start", "grad_bottom": "Gradient end"}

GROUPS = {
    "Colors": tuple(TONES.items()),
    "Appearance": (("scale", "UI scale"), ("font_size", "Font size"), ("button", "Button style"),
                   ("border", "Border thickness"), ("rounding", "Corner rounding"),
                   ("gradient", "Panel gradient"), ("gradient_direction", "Gradient direction")),
    "Animations": (("ambient_motion", "Interface motion"), ("background_motion", "Background animation"),
                   ("speed", "Animation speed"), ("transition", "Page transition"),
                   ("duration", "Transition duration"), ("hover", "Hover effect")),
    "Effects": (("softness", "Background blur"), ("glow", "Edge glow"), ("shadow", "Button shadow"),
                ("panel_transparency", "Panel transparency"), ("blur", "Windows acrylic"),
                ("acrylic_tint", "Acrylic tint"), ("opacity", "Desktop window opacity")),
    "Layout": (("menu_layout", "Menu layout"), ("spacing", "Item spacing"), ("gutter", "Extra page padding"),
               ("sidebar", "Library navigation"), ("sidebar_width", "Sidebar width"),
               ("sidebar_tint", "Sidebar color"), ("counts", "Sidebar counts")),
    "Sounds": (("ui_sounds", "Interface sounds"), ("volume", "Volume"),
               ("cue_hover", "Hover"), ("cue_click", "Click"), ("cue_back", "Back"),
               ("cue_open", "Open Havoc"), ("cue_close", "Close Havoc")),
}

PROFILES = {
    "Standard": {},
    "Compact": {"spacing": 78, "scale": 92, "sidebar_width": 205, "gutter": -4, "button": "Flat"},
    "Soft light": {"theme": "Amethyst", "rounding": 6, "glow": 35, "softness": 4,
                   "gradient": 48, "panel_transparency": 14, "sidebar_tint": "Accent wash"},
    "Quiet": {"ambient_motion": False, "transition": "Instant", "ui_sounds": False, "hover": "Off"},
}

LEGACY = ("theme", "custom_acc", "custom_bg", "ambient_motion", "ui_sounds", "blur", "opacity")

def defaults():
    return {**{k: spec[0] for k, spec in NUMBERS.items()}, **{k: values[0] for k, values in CHOICES.items()},
            **FLAGS, "theme": "Havoc", "custom_acc": (232, 160, 191), "custom_bg": (28, 28, 31), "colors": {}}

def _rgb(value):
    if isinstance(value, (list, tuple)) and len(value) == 3 and all(type(v) is int and 0 <= v <= 255 for v in value):
        return tuple(value)
    return None

def normalize(raw, themes):
    values = defaults()
    if not isinstance(raw, dict):
        return values
    for key, (_, lo, hi, _) in NUMBERS.items():
        n = raw.get(key)
        if type(n) in (int, float) and lo <= n <= hi:
            values[key] = round(n)
    for key, choices in CHOICES.items():
        if raw.get(key) in choices:
            values[key] = raw[key]
    for key in FLAGS:
        if isinstance(raw.get(key), bool):
            values[key] = raw[key]
    if raw.get("theme") in themes:
        values["theme"] = raw["theme"]
    for key in ("custom_acc", "custom_bg"):
        values[key] = _rgb(raw.get(key)) or values[key]
    colors = raw.get("colors")
    if isinstance(colors, dict):
        for theme, tones in colors.items():
            if theme in themes and isinstance(tones, dict):
                values["colors"][theme] = {k: c for k in TONES if (c := _rgb(tones.get(k))) is not None}
    return values

def load(root, legacy, themes):
    try:
        record = json.loads((Path(root) / "havoc_appearance.json").read_text(encoding="utf-8"))
        if isinstance(record, dict) and isinstance(record.get("current"), dict):
            saved = record.get("saved")
            return normalize(record["current"], themes), normalize(saved, themes) if isinstance(saved, dict) else None
    except (OSError, ValueError):
        pass
    return normalize(legacy, themes), None

def save(root, values, saved):
    path = Path(root) / "havoc_appearance.json"
    data = json.dumps({"current": values, "saved": saved}, separators=(",", ":"))
    with NamedTemporaryFile(dir=path.parent, prefix=".havoc-appearance-", delete=False) as stream:
        temp = Path(stream.name)
    try:
        temp.write_text(data, encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

def palette(base, colors):
    if not colors:
        return base
    painted = dict(base)
    if "bg" in colors:
        painted["panel"] = tuple(round(a * 0.86 + b * 0.14) for a, b in zip(colors["bg"], base["panel"]))
    if "acc" in colors:
        painted["acc_hi"] = tuple(round(c * 0.75 + 255 * 0.25) for c in colors["acc"])
        painted["p1"] = colors["acc"]
    painted.update((k, v) for k, v in colors.items() if k in base)
    painted["grad"] = (colors.get("grad_top", base["grad"][0]), colors.get("grad_bottom", base["grad"][1]))
    painted["p2"] = colors.get("alt", base["p2"])
    return painted

def gradient(dl, p, q, top, bottom, direction):
    pack = imgui.get_color_u32
    a, b = pack(top), pack(bottom)
    if direction == "Horizontal":
        corners = (a, b, b, a)
    elif direction == "Diagonal":
        mid = pack(blend(top, bottom, 0.5))
        corners = (a, mid, b, mid)
    else:
        corners = (a, a, b, b)
    dl.add_rect_filled_multi_color(p, q, *corners)

def sidebar_color(panel):
    surface = rgb(*panel.palette["panel"])
    mode = panel.preferences["sidebar_tint"]
    if mode == "Accent wash":
        return blend(surface, rgb(*panel.palette["acc"]), 0.20)
    if mode == "Darkened":
        return blend(surface, rgb(0, 0, 0), 0.30)
    return surface

def navigation(panel):
    groups = tuple(GROUPS)
    width = imgui.get_content_region_avail().x
    longest = max(imgui.calc_text_size(group).x for group in groups)
    if width < max(315 * panel.zoom, 3 * (longest + 18 * panel.zoom)):
        imgui.set_next_item_width(-1)
        changed, i = imgui.combo("##appearance-category", groups.index(panel.appearance_tab), groups)
        if changed:
            panel.appearance_tab = groups[i]
    else:
        gap = 5 * panel.zoom
        col = (width - 2 * gap) / 3
        for i, group in enumerate(groups):
            if i % 3:
                imgui.same_line(0, gap)
            if panel._button(group + "##appearance-tab", col, 31, primary=group == panel.appearance_tab):
                panel.appearance_tab = group

def presets(panel):
    panel._section_caption("Style presets")
    names = [*PROFILES] + (["My preset"] if panel.saved_style is not None else [])
    gap = 6 * panel.zoom
    w = imgui.get_content_region_avail().x
    action = min(w * 0.32, 78 * panel.zoom)
    imgui.set_next_item_width(max(30, w - action - gap))
    changed, i = imgui.combo("##style-presets", names.index(panel.style_choice), names)
    if changed:
        panel.style_choice = names[i]
    imgui.same_line(0, gap)
    if panel._button("Apply##style", action, 29):
        chosen = panel.saved_style if panel.style_choice == "My preset" else {**defaults(), **PROFILES[panel.style_choice]}
        values = chosen.copy()
        if panel.style_choice != "My preset":
            values["menu_layout"] = panel.preferences["menu_layout"]
        panel._apply_visual(values, save_now=True)
    each = max(1, (w - gap) / 2)
    if panel._button("Save my preset", each, 29):
        # Individual edits replace nested maps, so saved profiles keep their own colors.
        panel.saved_style = panel.preferences.copy()
        panel.style_choice = "My preset"
        panel._flush_visual()
    imgui.same_line(0, gap)
    if panel._button("Reset to defaults", each, 29):
        panel.style_choice = "Standard"
        values = defaults()
        values["menu_layout"] = getattr(panel, "default_layout", values["menu_layout"])
        panel._apply_visual(values, save_now=True)

def preference(panel, key, slider=None):
    values = panel.preferences
    slider = slider or imgui.slider_int
    widget = "##pref/" + key
    native_window = key in ("opacity", "blur", "acrylic_tint")
    disabled = ((native_window and os.name != "nt") or (key == "opacity" and values["blur"])
                or (key == "acrylic_tint" and not values["blur"]))
    imgui.begin_disabled(disabled)
    if key in TONES:
        tone = panel.palette["grad"][0 if key == "grad_top" else 1] if key.startswith("grad_") else panel.palette[key]
        changed, value = imgui.color_edit3(widget, [c / 255 for c in tone], imgui.ColorEditFlags_.display_hex)
        if changed:
            tone = tuple(max(0, min(255, round(c * 255))) for c in value)
            panel._set_tone(key, tone)
        # Keep the chip opaque on backends that composite ImGui's color preview with window alpha.
        a, b = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        size = imgui.get_frame_height()
        x = a.x if imgui.get_style().color_button_position == imgui.Dir.left else b.x - size
        imgui.get_window_draw_list().add_rect_filled(ImVec2(x + 3, a.y + 3), ImVec2(x + size - 3, a.y + size - 3),
                                                     imgui.get_color_u32(rgb(*tone)), imgui.get_style().frame_rounding)
    elif key in NUMBERS:
        _, lo, hi, fmt = NUMBERS[key]
        changed, value = slider(widget, values[key], lo, hi, fmt, imgui.SliderFlags_.always_clamp)
        if changed:
            panel._set_visual(key, value)
    elif key in CHOICES:
        choices = CHOICES[key]
        changed, index = imgui.combo(widget, choices.index(values[key]), choices)
        if changed:
            panel._set_visual(key, choices[index])
    else:
        changed, value = imgui.checkbox(widget, values[key])
        if changed:
            panel._set_visual(key, value)
    imgui.end_disabled()

def editor(panel):
    navigation(panel)
    category = panel.appearance_tab
    panel._section_caption(category)
    flags = imgui.TableFlags_.sizing_stretch_prop | imgui.TableFlags_.no_saved_settings
    values = panel.preferences
    w = imgui.get_content_region_avail().x
    stacked = w < 235 * panel.zoom * values["font_size"] / 16
    label_share = 0.69 if w < 425 * panel.zoom else 0.93
    if imgui.begin_table("preferences/" + category, 1 if stacked else 2, flags):
        imgui.table_setup_column("Setting", imgui.TableColumnFlags_.width_stretch, label_share)
        if not stacked:
            imgui.table_setup_column("Value", imgui.TableColumnFlags_.width_stretch, 2 - label_share)
        for key, label in GROUPS[category]:
            imgui.table_next_row()
            imgui.table_next_column()
            imgui.align_text_to_frame_padding()
            imgui.text_wrapped(label)
            imgui.table_next_column()
            imgui.set_next_item_width(-1)
            preference(panel, key)
        imgui.end_table()
    if category == "Colors":
        if panel._button("Restore palette colors", w, 29):
            panel._clear_tones()
    elif category == "Sounds":
        sound_preview(panel)
    elif category == "Effects" and (os.name != "nt" or values["blur"]):
        imgui.text_disabled("Desktop opacity and acrylic use Windows composition." if os.name != "nt"
                            else "Acrylic uses full desktop opacity. Panel transparency is adjustable.")
    elif category == "Layout":
        # Use the same surface, sizing rule and border as the real library sidebar.
        panel._section_caption("Library preview")
        p = imgui.get_cursor_screen_pos()
        h = 57 * panel.zoom
        imgui.dummy(ImVec2(w, h))
        dl = imgui.get_window_draw_list()
        edge = rgb(*panel.palette["edge"])
        compact = values["sidebar"] == "Page selectors"
        part = w if compact else w * panel._sidebar_width(1080 * panel.zoom) / (1080 * panel.zoom)
        a = ImVec2(p.x + part, p.y + (h * 0.38 if compact else h))
        dl.add_rect_filled(p, a, imgui.get_color_u32(sidebar_color(panel)))
        panel._border(dl, p, a, edge)
        ink = imgui.get_color_u32(tint(rgb(*panel.palette["acc"]), 0.68))
        for i in range(1 if compact else 3):
            y = p.y + 9 * panel.zoom + 13 * panel.zoom * i
            dl.add_line(ImVec2(p.x + 9, y), ImVec2(p.x + part * 0.65, y), ink)
            if values["counts"] and not compact:
                dl.add_rect_filled(ImVec2(p.x + part - 13, y - 2), ImVec2(p.x + part - 9, y + 2), ink)
        b = ImVec2(p.x, a.y + 3) if compact else ImVec2(a.x + 3, p.y)
        panel._border(dl, b, ImVec2(p.x + w, p.y + h), edge)

def sound_preview(panel):
    w = imgui.get_content_region_avail().x
    values = panel.preferences
    cues = ("hover", "click", "back", "open", "close")
    action = min(126 * panel.zoom, w * 0.47)
    imgui.set_next_item_width(max(1, w - action - 6))
    _, panel.preview_cue = imgui.combo("##sample-cue", panel.preview_cue, [s.title() for s in cues])
    imgui.same_line(0, 6)
    cue = cues[panel.preview_cue]
    imgui.begin_disabled(panel._audio.unavailable or not values["ui_sounds"] or not values["cue_" + cue] or values["volume"] == 0)
    if panel._button("Play cue", action, 29):
        panel._audio.play(cue, preview=True)
        panel._last_cue_frame = imgui.get_frame_count()
    imgui.end_disabled()
    if panel.ui_sounds and panel._audio.unavailable:
        imgui.text_disabled("Local audio output unavailable")


appearance = SimpleNamespace(
    FLAGS=FLAGS,
    GROUPS=GROUPS,
    LEGACY=LEGACY,
    defaults=defaults,
    editor=editor,
    gradient=gradient,
    load=load,
    os=os,
    palette=palette,
    preference=preference,
    presets=presets,
    save=save,
    sidebar_color=sidebar_color,
    sound_preview=sound_preview,
)


menu_font = None

PALETTE = {
    "bg": (17, 18, 39),
    "panel": (37, 37, 61),
    "card": (23, 25, 46),
    "card2": (33, 33, 55),
    "edge": (78, 79, 107),
    "text": (236, 235, 247),
    "muted": (183, 182, 209),
    "faint": (149, 149, 179),
    "acc": (188, 164, 253),
    "acc_hi": (226, 215, 255),
    "alt": (145, 143, 205),
    "grad": ((45, 44, 72), (30, 31, 52)),
    "p1": (188, 164, 253),
    "p2": (145, 143, 205),
}

DESTINATIONS = (
    ("Appearance", "Style", "mask"),
    ("Dashboard", "Home", "home"),
    ("All Mods", "Library", "cube"),
    ("Connection", "Device", "device"),
)

TOOLS = (("search", "Find a page or control"), ("moon", "Palettes and presets"), ("gear", "Workspace options"))

TABS = ("Controls", "Palette", "Audio")

pack = imgui.get_color_u32

def _point_list(cx, cy, size, points):
    return [V(cx + x * size, cy + y * size) for x, y in points]

def _icon(dl, name, cx, cy, size, ink, cut):
    color, hole = pack(ink), pack(cut)
    width = max(1.4, size * 0.083)

    def pt(x, y):
        return V(cx + x * size, cy + y * size)

    def line(a, b):
        dl.add_line(pt(*a), pt(*b), color, width)

    def shape(points):
        dl.add_convex_poly_filled(_point_list(cx, cy, size, points), color)

    if name == "mask":
        shape(
            (
                (-0.46, -0.12),
                (-0.36, -0.33),
                (-0.15, -0.46),
                (0.15, -0.46),
                (0.36, -0.33),
                (0.46, -0.12),
                (0.43, 0.19),
                (0.28, 0.30),
                (0.26, 0.42),
                (-0.26, 0.42),
                (-0.28, 0.30),
                (-0.43, 0.19),
            )
        )
        for x in (-0.19, 0.19):
            dl.add_circle_filled(pt(x, 0.012), size * 0.105, hole, 16)
        dl.add_triangle_filled(pt(0, 0.14), pt(-0.065, 0.24), pt(0.065, 0.24), hole)
        for x in (-0.11, 0.11):
            dl.add_line(pt(x, 0.32), pt(x, 0.44), hole, max(1, width * 0.62))
    elif name == "home":
        line((-0.45, -0.02), (0, -0.40))
        line((0, -0.40), (0.45, -0.02))
        dl.add_rect(pt(-0.30, -0.04), pt(0.30, 0.36), color, rounding=size * 0.04, thickness=width)
        dl.add_rect_filled(pt(-0.085, 0.12), pt(0.085, 0.38), color)
    elif name == "cube":
        shape(((0, -0.44), (0.43, -0.21), (0, 0.035), (-0.43, -0.21)))
        shape(((-0.43, -0.13), (-0.035, 0.10), (-0.035, 0.46), (-0.43, 0.23)))
        shape(((0.035, 0.10), (0.43, -0.13), (0.43, 0.23), (0.035, 0.46)))
    elif name == "device":
        dl.add_rect(pt(-0.46, -0.25), pt(0.46, 0.29), color, rounding=size * 0.15, thickness=width)
        for x in (-0.20, 0.20):
            dl.add_circle_filled(pt(x, 0.015), size * 0.085, color, 12)
        line((-0.22, -0.29), (0.22, -0.29))
    elif name == "search":
        dl.add_circle(pt(0.06, -0.08), size * 0.25, color, 22, width)
        line((0.23, 0.10), (0.44, 0.34))
        for y, end in ((-0.29, -0.31), (-0.05, -0.37), (0.20, -0.25)):
            line((-0.49, y), (end, y))
    elif name == "moon":
        dl.add_circle_filled(pt(-0.03, 0), size * 0.43, color, 32)
        dl.add_circle_filled(pt(0.19, -0.21), size * 0.375, hole, 32)
    elif name == "forward":
        line((-0.22, -0.30), (0.12, 0))
        line((0.12, 0), (-0.22, 0.30))
    elif name == "gear":
        for k in range(8):
            a = k * math.pi / 4
            dx, dy = math.cos(a), math.sin(a)
            dl.add_line(pt(dx * 0.21, dy * 0.21), pt(dx * 0.43, dy * 0.43), color, width * 1.45)
        dl.add_circle_filled(pt(0, 0), size * 0.34, color, 24)
        dl.add_circle_filled(pt(0, 0), size * 0.14, hole, 20)
    else:
        for x in (-0.18, 0.18):
            dl.add_circle_filled(pt(x, -0.11), size * 0.22, color, 18)
        dl.add_triangle_filled(pt(-0.37, -0.015), pt(0.37, -0.015), pt(0, 0.40), color)

_WALLPAPER = ASSET_ROOT / "midnight_landscape.jpg"

def _wallpaper(panel, dl, a, b, colors, phase):
    # The texture cache belongs to the renderer. Both focus levels live in one atlas.
    if not hasattr(panel, "_landscape_image"):
        try:
            panel._landscape_image = (
                hello_imgui.image_and_size_from_asset(str(_WALLPAPER)) if _WALLPAPER.is_file() else None
            )
        except (OSError, RuntimeError):
            panel._landscape_image = None
    image = panel._landscape_image
    blur = panel.preferences["softness"]
    alpha = 0.24 if panel.blur else 1.0
    if image is None or not image.texture_id:
        top = pack(tint(colors["bg"], alpha))
        bottom = pack(tint(colors["panel"], alpha))
        dl.add_rect_filled_multi_color(a, b, top, top, bottom, bottom)
        return
    texture = imgui.ImTextureRef(image.texture_id)
    # Fill the window without stretching the mountain silhouettes as the aspect ratio changes.
    ratio = (b.x - a.x) / max(1, b.y - a.y)
    aspect = image.size.x / (image.size.y / 2)
    uw, vh = min(1.0, ratio / aspect), min(1.0, aspect / ratio)
    dx = (1 - uw) * (0.50 + 0.025 * math.sin(phase * 0.09))
    dy = (1 - vh) * 0.50
    pad = 0.5 / image.size.y

    def layer(offset, opacity):
        dl.add_image(
            texture,
            a,
            b,
            V(dx, offset + dy * 0.5 + pad),
            V(dx + uw, offset + (dy + vh) * 0.5 - pad),
            pack(rgb(255, 255, 255, opacity)),
        )

    layer(0, alpha)
    if blur:
        layer(0.5, blur * alpha / 8)
    theme = panel.preferences["theme"]
    edited_bg = "bg" in panel.preferences["colors"].get(theme, {})
    wash = 0.38 if theme != "Havoc" or edited_bg else 0.06
    dl.add_rect_filled(a, b, pack(tint(colors["bg"], wash * alpha)))
    for i in range(26):
        u = ((73 * i + 17) % 193) / 193
        v = ((53 * i + 7) % 157) / 157 * 0.32
        strength = (0.09 + 0.06 * math.sin(i * 1.97 + phase * 0.5)) * alpha
        dl.add_circle_filled(
            V(a.x + (b.x - a.x) * u, a.y + (b.y - a.y) * v),
            0.68 + i % 3 * 0.2,
            pack(tint(colors["alt"], strength)),
            6,
        )

def _shell(dl, a, b, colors, prefs, zoom, surface=None):
    radius = (13 + prefs["rounding"] * 0.45) * zoom
    shadow = prefs["shadow"] / 100
    for n in (9, 5, 2):
        dl.add_rect_filled(
            V(a.x - n * 0.55, a.y - n * 0.25),
            V(b.x + n * 0.55, b.y + n),
            pack(tint(rgb(6, 8, 23), 0.12 * shadow)),
            radius + n,
        )
    surface = colors["panel"] if surface is None else surface
    opacity = 1 - prefs["panel_transparency"] / 100
    dl.add_rect_filled(a, b, pack(tint(surface, opacity)), radius)
    edge = tint(colors["edge"], 0.51)
    thick = prefs["border"] * zoom
    if thick:
        dl.add_rect(a, b, pack(edge), rounding=radius, thickness=thick)
    glow = prefs["glow"] / 100
    if glow:
        dl.add_rect(
            V(a.x - 2, a.y - 2),
            V(b.x + 2, b.y + 2),
            pack(tint(colors["acc"], glow * 0.35)),
            rounding=radius + 2,
            thickness=3,
        )

def _tile(panel, key, name, label, x, y, w, h, colors, active=False, small=False):
    imgui.set_cursor_screen_pos(V(x, y))
    pressed = imgui.invisible_button(key, V(w, h), imgui.ButtonFlags_.enable_nav)
    hovered = imgui.is_item_hovered()
    hover = panel._animate(key + "/hover", hovered, 0)
    selected = panel._animate(key + "/selected", active)
    dl = imgui.get_window_draw_list()
    z = panel.zoom
    face = blend(colors["panel"], colors["bg"], 0.48 if small else 0.10)
    face = blend(face, blend(colors["bg"], rgb(10, 10, 17), 0.55), selected)
    face = blend(face, colors["alt"], hover * (0.15 if panel.preferences["hover"] == "Glow" else 0.08))
    ink = blend(colors["faint"], colors["acc"], max(selected, hover * 0.72, 0.76 if small else 0))
    radius = (4 if small else 8) * z + panel.preferences["rounding"] * 0.35 * z
    button = panel.preferences["button"]
    if button == "Outline" and not active:
        face = blend(face, colors["panel"], 0.8)
    elif button == "Flat":
        radius = panel.preferences["rounding"] * z
    dl.add_rect_filled(V(x, y), V(x + w, y + h), pack(face), radius)
    thick = panel.preferences["border"] * z
    if thick:
        edge = blend(colors["edge"], colors["acc"], 0.88 if imgui.is_item_focused() else hover * 0.6)
        dl.add_rect(
            V(x, y), V(x + w, y + h), pack(tint(edge, 0.44 if active else 0.85)), rounding=radius, thickness=thick
        )
    if small:
        _icon(dl, name, x + w / 2, y + h / 2, min(w, h) * 0.50, ink, face)
    else:
        size = min(w * 0.40, h * 0.43)
        _icon(dl, name, x + w / 2, y + h * 0.35, size, ink, face)
        title = label.upper()
        sz = imgui.calc_text_size(title)
        if sz.x > w - 3:
            title = {"LIBRARY": "MODS", "CREDITS": "INFO", "DEVICE": "LINK"}.get(title, title)
            sz = imgui.calc_text_size(title)
        dl.add_text(
            V(round(x + (w - sz.x) / 2), round(y + h * 0.75 - sz.y / 2)),
            pack(blend(colors["muted"], colors["text"], selected)),
            title,
        )
    if hovered:
        imgui.set_tooltip(label)
    return pressed

def _thin_slider(widget, value, lo, hi, fmt, flags):
    dl = imgui.get_window_draw_list()
    style = imgui.get_style()
    p = imgui.get_cursor_screen_pos()
    width = imgui.calc_item_width()
    font = imgui.get_font_size()
    readout = min(width * 0.45, max(imgui.calc_text_size(fmt % v).x for v in (value, lo, hi)) + font * 0.5)
    imgui.set_cursor_screen_pos(V(p.x + readout, p.y))
    imgui.set_next_item_width(max(1, width - readout))
    editing = imgui.get_current_context().temp_input_id == imgui.get_id(widget)
    if not editing:
        for col in (
            imgui.Col_.frame_bg,
            imgui.Col_.frame_bg_active,
            imgui.Col_.frame_bg_hovered,
            imgui.Col_.slider_grab,
            imgui.Col_.slider_grab_active,
            imgui.Col_.text,
            imgui.Col_.border,
        ):
            imgui.push_style_color(col, rgb(0, 0, 0, 0))
    changed, new = imgui.slider_int(widget, value, lo, hi, fmt, flags)
    if not editing:
        imgui.pop_style_color(7)
        a, b = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        cy = round((a.y + b.y) / 2)
        r = max(3, font * 0.27)
        x1, x2 = a.x + r + 1, max(a.x + r + 1, b.x - r - 1)
        x = x1 + (x2 - x1) * (new - lo) / (hi - lo)
        accent = style.color_(imgui.Col_.slider_grab_active)
        line = style.color_(imgui.Col_.border)
        dl.add_line(V(x1, cy), V(x2, cy), pack(line), r * 1.18)
        dl.add_line(V(x1, cy), V(x, cy), pack(accent), r * 1.18)
        dl.add_circle_filled(V(x, cy), r + 1, pack(rgb(11, 11, 24)), 16)
        dl.add_circle_filled(V(x, cy), r, pack(rgb(245, 242, 255)), 16)
        display = fmt % new
        sw = imgui.calc_text_size(display)
        dl.add_text(
            V(p.x + readout - sw.x - font * 0.52, cy - sw.y / 2), pack(style.color_(imgui.Col_.text)), display
        )
    return changed, new

def inks(panel):
    cached = getattr(panel, "_midnight_colors", None)
    if cached is None or cached[0] is not panel.palette:
        colors = {
            name: rgb(*panel.palette[name])
            for name in ("bg", "panel", "card", "card2", "edge", "text", "muted", "faint", "acc", "alt")
        }
        panel._midnight_colors = panel.palette, colors
    return panel._midnight_colors[1]

@contextmanager
def _midnight_font(size):
    imgui.push_font(menu_font, size)
    try:
        yield
    finally:
        imgui.pop_font()

def opening_backdrop(panel, dl, viewport):
    c = inks(panel)
    p, size = viewport.pos, viewport.size
    _wallpaper(panel, dl, p, V(p.x + size.x, p.y + size.y), c, panel._art_phase)
    half_w, half_h = min(247 * panel.zoom, size.x * 0.44), min(152 * panel.zoom, size.y * 0.38)
    cx, cy = p.x + size.x / 2, p.y + size.y / 2
    _shell(dl, V(cx - half_w, cy - half_h), V(cx + half_w, cy + half_h), c, panel.preferences, panel.zoom)

def poster(panel, kicker, title, caption, height, night, motif):
    c = inks(panel)
    z = panel.zoom
    w = max(1, imgui.get_content_region_avail().x)
    pad = min(23 * z, max(8 * z, w * 0.045))
    art = (panel.palette["acc"], panel.palette["acc_hi"], panel.palette["alt"])
    is_cover = night or title == "Havoc"
    target_h = min(height, 325 if is_cover else 115) * z
    copy_width = max(1, w * (0.70 if w < 480 * z else 0.57) - pad)
    with _midnight_font((31 if w > 360 * z else 24) if is_cover else 24):
        title_h = imgui.calc_text_size(title, wrap_width=copy_width).y
    h = max(target_h, title_h + pad * 2 + (40 if caption else 23) * z)
    p = imgui.get_cursor_screen_pos()
    q = V(p.x + w, p.y + h)
    imgui.dummy(V(w, h))
    if not imgui.is_item_visible():
        return
    dl = imgui.get_window_draw_list()
    dl.push_clip_rect(p, q, True)
    if motif:
        draw_plate(dl, p, q, motif, art, align=0.79, phase=panel._art_phase)
    else:
        draw_landscape(dl, p, q, art, panel._art_phase, night)
    # A graded scrim carries the text and leaves the illustrated edge visible.
    mid = p.x + w * 0.44
    dl.add_rect_filled_multi_color(
        p,
        V(mid, q.y),
        pack(tint(c["bg"], 0.97)),
        pack(tint(c["bg"], 0.85)),
        pack(tint(c["bg"], 0.85)),
        pack(tint(c["bg"], 0.97)),
    )
    dl.add_rect_filled_multi_color(
        V(mid, p.y),
        q,
        pack(tint(c["bg"], 0.85)),
        pack(tint(c["bg"], 0.06)),
        pack(tint(c["bg"], 0.06)),
        pack(tint(c["bg"], 0.85)),
    )
    x = p.x + pad
    y = p.y + (h - title_h - (40 if caption else 22) * z) / 2
    with _midnight_font(12):
        dl.add_text(V(x, y), pack(c["acc"]), kicker.upper())
    with _midnight_font((31 if w > 360 * z else 24) if is_cover else 24):
        dl.add_text(
            imgui.get_font(),
            imgui.get_font_size(),
            V(x, y + 19 * z),
            pack(rgb(248, 246, 255)),
            title,
            wrap_width=copy_width,
        )
    if caption:
        with _midnight_font(13):
            dl.add_text(
                V(x, y + title_h + 25 * z), pack(rgb(212, 209, 229)), panel._fit_label(caption, w - 2 * pad)
            )
    dl.pop_clip_rect()
    panel._border(dl, p, q, c["edge"])

def heading(panel, eyebrow, title, detail=None, detail_color=None):
    if title == "Connection":
        poster(panel, eyebrow, title, detail, 83, False, "device")
        return
    c = inks(panel)
    z = panel.zoom
    with _midnight_font(12):
        imgui.text_colored(c["acc"], eyebrow.upper())
    with _midnight_font(22):
        imgui.text_wrapped(title)
    if detail:
        imgui.push_style_color(imgui.Col_.text, detail_color if detail_color is not None else c["muted"])
        imgui.text_wrapped(detail)
        imgui.pop_style_color()
    imgui.dummy(V(1, 2 * z))
    imgui.separator()

def section_caption(panel, label):
    c = inks(panel)
    z = panel.zoom
    p = imgui.get_cursor_screen_pos()
    w = imgui.get_content_region_avail().x
    with _midnight_font(12):
        text = panel._fit_label(label.upper(), w)
        extent = imgui.calc_text_size(text)
        h = max(19 * z, extent.y + 3 * z)
        imgui.dummy(V(max(1, w), h))
        dl = imgui.get_window_draw_list()
        cy = p.y + h / 2
        dl.add_text(V(p.x, cy - extent.y / 2), pack(c["muted"]), text)
        if extent.x + 14 * z < w:
            dl.add_line(V(p.x + extent.x + 9 * z, cy), V(p.x + w, cy), pack(tint(c["edge"], 0.65)))

def index_row(panel, key, label, detail, icon, selected):
    c = inks(panel)
    z = panel.zoom
    w = max(1, imgui.get_content_region_avail().x)
    h = max(31 * z * panel.preferences["spacing"] / 100, imgui.get_font_size() + 12 * z)
    pressed = imgui.invisible_button(key, V(w, h), imgui.ButtonFlags_.enable_nav)
    if not imgui.is_item_visible():
        return pressed
    a, b = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    dl = imgui.get_window_draw_list()
    hover = panel._animate(key + "/hover", imgui.is_item_hovered(), 0)
    face = blend(c["card"], c["acc"], 0.16 if selected else 0.08 * hover)
    dl.add_rect_filled(a, b, pack(face), 3 * z)
    panel._border(
        dl,
        a,
        b,
        c["acc"] if imgui.is_item_focused() else blend(c["card2"], c["edge"], 0.50 + hover * 0.5),
        hover=hover,
    )
    if selected:
        dl.add_rect_filled(V(a.x + 1, a.y + 3 * z), V(a.x + 3 * z, b.y - 3 * z), pack(c["acc"]))
    cy = (a.y + b.y) / 2
    _icon(
        dl,
        {"library": "cube", "device": "device", "home": "home"}.get(icon, "forward"),
        a.x + 15 * z,
        cy,
        13 * z,
        c["acc"] if selected else c["faint"],
        face,
    )
    info = panel._fit_label(detail, min(w * 0.49, max(0, w - 95 * z))) if detail else ""
    sz = imgui.calc_text_size(info)
    reserve = sz.x + 10 * z if info else 0
    title = panel._fit_label(label, max(0, w - reserve - 43 * z))
    dl.add_text(V(a.x + 27 * z, cy - imgui.get_font_size() / 2), pack(c["text"]), title)
    if info:
        dl.add_text(V(b.x - 11 * z - sz.x, cy - sz.y / 2), pack(c["muted"]), info)
    if imgui.is_item_hovered() and (title != label or info != detail):
        imgui.set_tooltip(label + ("  ·  " + detail if detail else ""))
    return pressed

def _check(dl, a, b, c, amount, zoom, opacity=1):
    size = b.x - a.x
    ink = blend(c["edge"], c["acc"], amount)
    dl.add_rect_filled(V(a.x + 2, a.y + 2), V(b.x - 2, b.y - 2), pack(tint(ink, 0.95 * opacity)), 1.5 * zoom)
    if amount > 0.02:
        points = (
            V(a.x + size * 0.24, a.y + size * 0.52),
            V(a.x + size * 0.43, a.y + size * 0.69),
            V(a.x + size * 0.78, a.y + size * 0.31),
        )
        ink = pack(tint(c["bg"], amount * opacity))
        dl.add_line(points[0], points[1], ink, 2 * zoom)
        dl.add_line(points[1], points[2], ink, 2 * zoom)

def switch_face(panel, key, label, on):
    z = panel.zoom
    c = inks(panel)
    w = max(1, imgui.get_content_region_avail().x)
    h = max(30 * z * panel.preferences["spacing"] / 100, imgui.get_frame_height() + 4 * z)
    box = min(h - 4*z, imgui.get_font_size() + 7*z)
    label_width = max(1, w - box - 18*z)
    label_height = imgui.calc_text_size(label, wrap_width=label_width).y
    h = max(h, label_height + 8*z)
    pressed = imgui.invisible_button("##switch/" + key, V(w, h), imgui.ButtonFlags_.enable_nav)
    if not imgui.is_item_visible():
        return pressed
    a, b = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    dl = imgui.get_window_draw_list()
    hovered = imgui.is_item_hovered()
    hover = panel._animate("hover/" + key, hovered, 0)
    tick = panel._animate("state/" + key, not on if pressed else on, on, 21)
    dl.add_rect_filled(a, b, pack(blend(c["card"], c["acc"], hover * 0.11)), 2 * z)
    if imgui.is_item_focused():
        panel._border(dl, a, b, c["acc"])
    y = (a.y + b.y - box) / 2
    _check(dl, V(b.x - box - 4 * z, y), V(b.x - 4 * z, y + box), c, tick, z)
    pos = V(a.x + 7*z, (a.y + b.y - label_height) / 2)
    dl.add_text(imgui.get_font(), imgui.get_font_size(), pos, pack(c["text"]), label, wrap_width=label_width)
    return pressed

def bookmark(panel, saved, width):
    c = inks(panel)
    z = panel.zoom
    label = "Saved" if saved else "+ Save mod"
    pressed = imgui.invisible_button(
        label, V(width, max(28 * z, imgui.get_frame_height() + 3 * z)), imgui.ButtonFlags_.enable_nav
    )
    if imgui.is_item_visible():
        a, b = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        dl = imgui.get_window_draw_list()
        cy = (a.y + b.y) / 2
        cx = (a.x + b.x) / 2
        s = min(8 * z, width * 0.30)
        shape = [
            V(cx - s * 0.70, cy - s),
            V(cx + s * 0.70, cy - s),
            V(cx + s * 0.70, cy + s),
            V(cx, cy + s * 0.50),
            V(cx - s * 0.70, cy + s),
        ]
        ink = pack(c["acc"] if saved or imgui.is_item_hovered() else c["faint"])
        if saved:
            dl.add_concave_poly_filled(shape, ink)
        else:
            dl.add_polyline(shape, ink, thickness=1.5 * z, flags=imgui.ImDrawFlags_.closed)
        if imgui.is_item_focused():
            panel._border(dl, a, b, c["acc"])
    return pressed

def control_grid(panel, groups):
    """Columns hold contiguous groups in the order supplied by the installed library."""
    width = imgui.get_content_region_avail().x
    cols = len(groups) > 1 and width >= max(575 * panel.zoom, 38 * imgui.get_font_size())
    if not cols or not imgui.begin_table(
        "##library-grid", 2, imgui.TableFlags_.sizing_stretch_same | imgui.TableFlags_.no_saved_settings
    ):
        for primary, sliders in groups:
            panel._control_group(primary, sliders)
        return
    weights = [1 + 2 * len(sliders) for _, sliders in groups]
    target = sum(weights) / 2
    total = 0
    split = 1
    best = float("inf")
    for i, weight in enumerate(weights[:-1], 1):
        total += weight
        if abs(total - target) < best:
            split, best = i, abs(total - target)
    for column in (groups[:split], groups[split:]):
        imgui.table_next_column()
        for primary, sliders in column:
            panel._control_group(primary, sliders)
    imgui.end_table()

def track(panel, dl, x0, x1, x, y, highlighted):
    z = panel.zoom
    c = inks(panel)
    dl.add_line(V(x0, y), V(x1, y), pack(c["edge"]), 4 * z)
    if x > x0:
        dl.add_line(V(x0, y), V(x, y), pack(c["acc"]), 4 * z)
    if highlighted:
        dl.add_circle_filled(V(x, y), 8 * z, pack(tint(c["acc"], 0.23)), 18)
    dl.add_circle_filled(V(x, y), 5 * z, pack(c["bg"]), 18)
    dl.add_circle_filled(V(x, y), 3.8 * z, pack(c["text"]), 18)

def _card(panel, title, items, c):
    imgui.text_colored(c["muted"], title)
    flags = (
        imgui.TableFlags_.sizing_stretch_prop
        | imgui.TableFlags_.no_saved_settings
        | imgui.TableFlags_.borders_outer
        | imgui.TableFlags_.borders_inner_h
    )
    if not imgui.begin_table("##rows/" + title, 2, flags):
        return
    imgui.table_setup_column("Setting", imgui.TableColumnFlags_.width_stretch, 0.98)
    imgui.table_setup_column("Value", imgui.TableColumnFlags_.width_stretch, 1.02)
    for i, (key, label) in enumerate(items):
        imgui.table_next_row(
            0, max(imgui.get_frame_height() + 4, 31.5 * panel.zoom * panel.preferences["spacing"] / 100)
        )
        imgui.table_set_bg_color(
            imgui.TableBgTarget_.row_bg0, pack(blend(c["card"], c["card2"], 0.15 if i % 2 else 0))
        )
        imgui.table_next_column()
        imgui.align_text_to_frame_padding()
        imgui.text_wrapped(label)
        imgui.table_next_column()
        imgui.set_next_item_width(-1)
        if key in appearance.FLAGS:
            imgui.set_cursor_pos_x(
                imgui.get_cursor_pos_x() + max(0, imgui.get_content_region_avail().x - imgui.get_frame_height())
            )
        appearance.preference(panel, key, _thin_slider)
        if key in appearance.FLAGS and imgui.is_item_visible():
            box_a, box_b = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            enabled = not (key == "blur" and appearance.os.name != "nt")
            checked = panel._animate("check/" + key, panel.preferences[key])
            _check(imgui.get_window_draw_list(), box_a, box_b, c, checked, panel.zoom, 1 if enabled else 0.32)
        if key in ("opacity", "acrylic_tint", "blur") and imgui.is_item_hovered(
            imgui.HoveredFlags_.allow_when_disabled
        ):
            if appearance.os.name != "nt":
                imgui.set_tooltip("This effect uses Windows desktop composition.")
            elif key == "opacity" and panel.blur:
                imgui.set_tooltip("Turn acrylic off to change desktop opacity.")
            elif key == "acrylic_tint" and not panel.blur:
                imgui.set_tooltip("Turn acrylic on to adjust its tint.")
    imgui.end_table()
    imgui.dummy(V(1, 5 * panel.zoom))

def _palette(panel):
    panel._palette_shelf()
    if panel.preferences["theme"] == "Custom" and imgui.collapsing_header("Custom palette"):
        panel._custom_palette_controls()
    imgui.spacing()
    appearance.presets(panel)

def _tabs(panel, c):
    z = panel.zoom
    available = max(1, (imgui.get_content_region_avail().x - (len(TABS)-1)*4*z) / len(TABS))
    for i, name in enumerate(TABS):
        if i:
            imgui.same_line(0, 4 * z)
        active = panel.midnight_tab == name
        imgui.push_style_color(
            imgui.Col_.button, blend(c["panel"], c["card"], 0.75) if active else tint(c["panel"], 0)
        )
        imgui.push_style_color(imgui.Col_.text, c["text"] if active else c["faint"])
        if imgui.button(
            name + "##midnight-tab",
            V(min(available, max(55 * z, imgui.calc_text_size(name).x + 21 * z)), imgui.get_frame_height() + 2 * z),
        ):
            panel.midnight_tab = name
        imgui.pop_style_color(2)
        if active:
            p, q = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            imgui.get_window_draw_list().add_line(
                V(p.x + 7 * z, q.y - 1), V(q.x - 7 * z, q.y - 1), pack(c["acc"]), 1.5 * z
            )

def _settings(panel, c):
    z = panel.zoom
    groups = appearance.GROUPS
    tab = panel.midnight_tab
    w = imgui.get_content_region_avail().x
    columns = w >= 580 * z * panel.preferences["font_size"] / 16
    flags = (
        imgui.TableFlags_.sizing_stretch_same
        | imgui.TableFlags_.no_saved_settings
        | imgui.TableFlags_.no_pad_outer_x
    )
    if not imgui.begin_table("##spread/" + tab, 2 if columns else 1, flags):
        return
    imgui.table_next_column()
    if tab == "Controls":
        # Gradient colors and their direction share the Palette page.
        _card(panel, "Appearance", groups["Layout"][:1] + groups["Appearance"][:5], c)
        _card(panel, "Layout", groups["Layout"][1:], c)
        imgui.table_next_column()
        _card(panel, "Animations", groups["Animations"], c)
        _card(panel, "Effects", groups["Effects"], c)
    elif tab == "Palette":
        _card(panel, "Colors", groups["Colors"][:7], c)
        _card(panel, "Gradient", groups["Colors"][7:] + groups["Appearance"][5:], c)
        if panel._button("Restore palette colors", imgui.get_content_region_avail().x, 27):
            panel._clear_tones()
        imgui.table_next_column()
        imgui.text_colored(c["muted"], "Color palette")
        _palette(panel)
    else:
        _card(panel, "Playback", groups["Sounds"][:2], c)
        imgui.text_colored(c["muted"], "Preview sound")
        appearance.sound_preview(panel)
        imgui.table_next_column()
        _card(panel, "Sound effects", groups["Sounds"][2:], c)
    imgui.end_table()

def _page(panel, c, now, page, notice):
    prefs = panel.preferences
    changed_page = page != getattr(panel, "_drawn_section", None)
    if changed_page:
        imgui.set_scroll_y(0)
        panel._drawn_section = page
    span = prefs["duration"] / (10 * prefs["speed"])
    effect = prefs["transition"]
    t = min(1, max(0, (now - panel._section_at) / span)) if panel.ambient_motion and effect != "Instant" else 1
    t = 1 - (1 - t) ** 3
    if t < 1 and effect in ("Slide", "Slide + fade"):
        imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + 5 * (1 - t))
    imgui.push_style_var(
        imgui.StyleVar_.alpha,
        imgui.get_style().alpha * (0.58 + 0.42 * t if effect in ("Fade", "Slide + fade") else 1),
    )
    imgui.push_id(page)
    if notice is not None:
        panel._release_contents(notice)
    elif not panel.workspace_open:
        if panel._signed_out_credits:
            panel._credits()
        else:
            panel._key_screen()
    elif page == "Appearance":
        _settings(panel, c)
    else:
        library = page not in ("Dashboard", "Connection", "Credits")
        w = imgui.get_content_region_avail().x
        sidebar = (
            library
            and prefs["sidebar"] != "Page selectors"
            and w >= (625 if prefs["sidebar"] == "Wide sidebar" else 825) * panel.zoom
        )
        browsing = page == "All Mods" and getattr(panel, "_category_index", False)
        if sidebar and not browsing:
            imgui.push_style_color(imgui.Col_.child_bg, appearance.sidebar_color(panel))
            imgui.begin_child("library-navigation", V(panel._sidebar_width(w), 0), imgui.ChildFlags_.borders)
            panel._library_navigation(compact=False)
            imgui.end_child()
            imgui.pop_style_color()
            imgui.same_line(0, 7 * panel.zoom)
        imgui.begin_child("page", V(0, 0))
        if changed_page:
            imgui.set_scroll_y(0)
        if library and not sidebar and not browsing:
            panel._library_navigation(compact=True)
        panel._controls()
        imgui.end_child()
    imgui.pop_id()
    imgui.pop_style_var()

def _utilities(panel, c, actions, positions):
    for (icon, label), (x, y, w, h) in zip(actions, positions):
        if _tile(panel, "##midnight-tool/" + icon, icon, label, x, y, w, h, c, small=True):
            if icon == "search":
                panel._palette_requested = True
            elif icon == "moon":
                panel._navigate("Appearance")
                panel.midnight_tab = "Palette"
            else:
                imgui.open_popup("Workspace options")
    # Keep the original inline search shortcut, command palette, saved mod presets and window controls.
    popup_w = max(170, min(350 * panel.zoom, imgui.get_main_viewport().size.x - 26))
    if panel.workspace_open and getattr(panel, "_focus_global_search", False):
        imgui.open_popup("Search library")
    imgui.set_next_window_size_constraints(V(popup_w, 0), V(popup_w, 600 * panel.zoom))
    if panel.workspace_open and imgui.begin_popup("Search library"):
        panel._navigation_search(imgui.get_content_region_avail().x)
        if imgui.is_key_pressed(imgui.Key.escape):
            imgui.close_current_popup()
        imgui.end_popup()
    imgui.set_next_window_size_constraints(V(popup_w, 0), V(popup_w, 600 * panel.zoom))
    if imgui.begin_popup("Workspace options"):
        if panel.workspace_open:
            imgui.text_colored(c["muted"], f"{panel.account.user}  ·  {imgui.get_io().framerate:.0f} FPS")
            if imgui.menu_item("Log out", "", False)[0]:
                panel.logout()
            imgui.separator()
            if imgui.menu_item("Credits", "", False)[0]:
                panel._navigate("Credits")
            if imgui.menu_item("Manage appearance", "", False)[0]:
                panel._navigate("Appearance")
                panel.midnight_tab = "Controls"
            if imgui.menu_item("Use Classic layout", "", False)[0]:
                panel._set_visual("menu_layout", "Classic")
            imgui.separator()
        if panel.changelog and imgui.menu_item("Release notes", "", False)[0]:
            panel._show_logs = True
        if CUSTOM_FRAME and imgui.menu_item("Maximize / restore", "", False)[0]:
            panel._toggle_maximise()
        if CUSTOM_FRAME and imgui.menu_item("Minimize", "", False)[0]:
            panel.minimize()
        if imgui.menu_item("Close Havoc", "", False)[0]:
            panel._request_close()
        imgui.end_popup()

def workspace(panel, now, notice=None):
    z = panel.zoom
    prefs = panel.preferences
    c = inks(panel)
    private = panel.workspace_open and notice is None
    if notice is not None:
        page = "Updates" if notice else "Changelog"
        destinations = ()
    elif private:
        page = panel.section
        destinations = (*DESTINATIONS, ("Credits", "Credits", "heart"))
    else:
        page = "Credits" if panel._signed_out_credits else "Sign in"
        destinations = (("Sign in", "Sign in", "mask"), ("Credits", "Credits", "heart"))
    actions = TOOLS if private else (("gear", "Window options"),) if destinations else ()
    dl = imgui.get_window_draw_list()
    origin, size = imgui.get_window_pos(), imgui.get_window_size()
    ox, oy = origin.x, origin.y
    w, h = size.x, size.y
    narrow = w < 690 * z or h < 425 * z
    outer = min(1290 * z, w * (0.86 if w >= 1130 * z else 0.94)) if not narrow else max(1, w - 16)
    x = ox + round((w - outer) * 0.5)
    y = oy + (round(0.061 * h) if not narrow else 8)
    gap = max(7, min(28 * z, w * 0.021)) if not narrow else 7
    railw = min(114 * z, max(80 * z, w * 0.085))
    bottom = oy + h - (round(0.048 * h) if not narrow else 8)
    if not narrow:
        limit = {"Sign in": 530, "Connection": 600, "Credits": 560, "Dashboard": 610, "Appearance": 655}.get(page, 740) * z
        inset = max(0, (bottom - y - limit) / 2)
        y, bottom = round(y + inset), round(bottom - inset)
    if narrow:
        railh = min(58 * z, h * 0.16)
        a, b = V(x, y), V(x + outer, bottom - railh - gap)
        ra, rb = V(x, b.y + gap), V(x + outer, bottom)
    else:
        a, b = V(x, y), V(x + outer - railw - gap, bottom)
        ra, rb = V(b.x + gap, y), V(x + outer, bottom)
    if not destinations:
        b = V(x + outer, bottom)
    phase = panel._art_phase
    _wallpaper(panel, dl, origin, V(ox + w, oy + h), c, phase)
    _shell(dl, a, b, c, prefs, z)
    if destinations:
        _shell(dl, ra, rb, c, prefs, z, surface=appearance.sidebar_color(panel))
    pad = (10 if narrow else 19) * z
    p, q = V(a.x + pad, a.y + pad), V(b.x - pad, b.y - pad)
    rad = (4 + prefs["rounding"] * 0.4) * z
    if prefs["gradient"]:
        grad = panel.palette["grad"]
        amount = prefs["gradient"] / 100
        appearance.gradient(
            dl, p, q, tint(rgb(*grad[0]), amount), tint(rgb(*grad[1]), amount), prefs["gradient_direction"]
        )
    if prefs["border"]:
        dl.add_rect(p, q, pack(tint(c["edge"], 0.85)), rounding=rad, thickness=prefs["border"] * z)
        dl.add_rect(
            V(p.x - 2, p.y - 2), V(q.x + 2, q.y + 2), pack(tint(c["bg"], 0.49)), rounding=rad + 2, thickness=z
        )
    dl.push_clip_rect(V(a.x + 2, a.y + 2), V(b.x - 2, b.y - 2), True)
    for center, start, stop, base in (
        (V(a.x - 5, b.y + 5), -math.pi / 2, 0, 0.112),
        (V(b.x + 1, a.y - 4), math.pi * 0.5, math.pi, 0.115),
    ):
        for mult in (1, 1.87, 2.8):
            r = (b.x - a.x) * base * mult + math.sin(phase * 0.13) * 1.3
            dl.path_arc_to(center, r, start, stop, 34)
            dl.path_stroke(pack(tint(c["muted"], 0.185)), thickness=z)
    dl.pop_clip_rect()
    gutter = max(5, (12 + prefs["gutter"]) * z)
    lane = min(66 * z, (q.x - p.x) * 0.11)
    if not actions:
        a_body, b_body = V(p.x + gutter, p.y + gutter), V(q.x - gutter, q.y - gutter)
        tools = []
        drag = (a.x, oy, max(1, b.x - a.x), max(1, a.y - oy))
    elif narrow:
        bar = min(33 * z, (q.y - p.y) * 0.14)
        edge = p.y + bar + 6 * z
        dl.add_line(V(p.x, edge), V(q.x, edge), pack(tint(c["edge"], 0.65)), z)
        tools = [
            (q.x - (len(actions) - i) * (bar + 3 * z) - 3 * z, p.y + 2 * z, bar, bar) for i in range(len(actions))
        ]
        a_body, b_body = V(p.x + gutter, edge + 6 * z), V(q.x - gutter, q.y - 4 * z)
        drag = (p.x, p.y, max(1, (q.x - p.x) - len(actions) * (bar + 3 * z) - 4 * z), bar)
    else:
        edge = q.x - lane
        dl.add_line(V(edge, p.y), V(edge, q.y), pack(tint(c["edge"], 0.8)), z)
        side = min(lane - 14 * z, 46 * z, max(18 * z, (q.y - p.y - 14 * z) / 3))
        tools = [
            (edge + (lane - side) / 2, p.y + 9 * z + i * (side + 5 * z), side, side) for i in range(len(actions))
        ]
        a_body, b_body = V(p.x + gutter, p.y + 7 * z), V(edge - gutter, q.y - 5 * z)
        drag = (a.x, oy, max(1, b.x - a.x), max(1, a.y - oy))
    imgui.set_cursor_screen_pos(V(drag[0], drag[1]))
    imgui.invisible_button("##midnight-drag", V(drag[2], drag[3]))
    if imgui.is_item_hovered():
        panel._quiet_hover = imgui.get_item_id()
        if imgui.is_mouse_double_clicked(0):
            panel._toggle_maximise()
        elif imgui.is_item_clicked(0):
            panel._native_drag()
    # Native widgets keep their mouse, keyboard and accessibility semantics under this compact styling.
    S, C = imgui.StyleVar_, imgui.Col_
    vars = (
        (S.frame_padding, V(6 * z, 3 * z)),
        (S.cell_padding, V(7 * z, 3 * z * prefs["spacing"] / 100)),
        (S.item_spacing, V(6 * z, 4 * z * prefs["spacing"] / 100)),
        (S.frame_rounding, 3 * z + prefs["rounding"] * 0.45 * z),
        (S.frame_border_size, prefs["border"] * z),
        (S.window_padding, V(9 * z, 8 * z)),
    )
    for var, value in vars:
        imgui.push_style_var(var, value)
    hover = 0 if prefs["hover"] == "Off" else (0.23 if prefs["hover"] == "Glow" else 0.12)
    styles = (
        (C.frame_bg, c["bg"]),
        (C.frame_bg_hovered, blend(c["bg"], c["acc"], hover)),
        (C.frame_bg_active, c["card2"]),
        (C.button, c["card"]),
        (C.button_hovered, blend(c["card"], c["acc"], hover)),
        (C.button_active, c["card2"]),
        (C.check_mark, c["acc"]),
        (C.slider_grab_active, c["acc"]),
        (C.border, c["edge"]),
        (C.table_border_light, blend(c["card"], c["edge"], 0.28)),
        (C.table_border_strong, blend(c["panel"], c["edge"], 0.55)),
        (C.header, c["card2"]),
        (C.text, c["text"]),
        (C.text_disabled, c["faint"]),
        (C.child_bg, tint(c["bg"], 0)),
    )
    for key, value in styles:
        imgui.push_style_color(key, value)
    imgui.push_font(menu_font, 14)
    if narrow and actions:
        page_name = panel._fit_label(page, max(1, drag[2] - 13 * z))
        dl.add_text(V(p.x + 8 * z, p.y + (bar - imgui.get_font_size()) / 2 + 2 * z), pack(c["muted"]), page_name)
    if actions:
        _utilities(panel, c, actions, tools)
        if private and not panel.workspace_open:
            imgui.pop_font()
            imgui.pop_style_color(len(styles))
            imgui.pop_style_var(len(vars))
            return
    active = page if not private or page in ("Appearance", "Dashboard", "Connection", "Credits") else "All Mods"
    if narrow:
        available = rb.x - ra.x - 8 * z
        cell = available / max(1, len(destinations))
        th = rb.y - ra.y - 8 * z
    else:
        margin = min(16 * z, railw * 0.145)
        cell = railw - 2 * margin
        th = min(cell, (rb.y - ra.y - 3 * margin) / 5.1)
    for i, (destination, label, icon) in enumerate(destinations):
        if narrow:
            xx = ra.x + 4 * z + i * cell
            yy = ra.y + 4 * z
            ww = cell - 2 * z
        else:
            xx = ra.x + margin
            ww = cell
            yy = ra.y + margin + i * (th + 10 * z) if i < 4 else rb.y - margin - min(th, 32 * z)
        small = not narrow and i == 4
        if _tile(
            panel,
            "##midnight-nav/" + destination,
            icon,
            label,
            xx,
            yy,
            ww,
            min(th, 32 * z) if small else th,
            c,
            destination == active,
            small,
        ):
            if private:
                panel._navigate(destination)
            elif destination != active:
                panel._signed_out_credits = destination == "Credits"
                panel._cue("click" if panel._signed_out_credits else "back")
    # Navigation can select a different page during this frame.
    if private:
        page = panel.section
    elif notice is None:
        page = "Credits" if panel._signed_out_credits else "Sign in"
    if private:
        # Keep status and local presets in reach while the page itself scrolls.
        footer_h = max(37 * z, imgui.get_frame_height() + 10 * z) + imgui.get_style().item_spacing.y
        imgui.set_cursor_screen_pos(V(a_body.x, b_body.y - footer_h))
        if imgui.begin_child(
            "midnight-status",
            V(max(1, b_body.x - a_body.x), footer_h),
            0,
            imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_scroll_with_mouse,
        ):
            panel._footer()
        imgui.end_child()
        b_body = V(b_body.x, b_body.y - footer_h - 3 * z)
    if private and page == "Appearance":
        tab_h = imgui.get_frame_height() + 7 * z
        if narrow:
            imgui.set_cursor_screen_pos(a_body)
            a_body = V(a_body.x, a_body.y + tab_h)
        else:
            b_body = V(b_body.x, b_body.y - tab_h)
            imgui.set_cursor_screen_pos(V(a_body.x, b_body.y + 3 * z))
        _tabs(panel, c)
    imgui.set_cursor_screen_pos(a_body)
    panel._daily_notice(b_body.x - a_body.x)
    a_body = V(a_body.x, imgui.get_cursor_screen_pos().y)
    imgui.set_cursor_screen_pos(a_body)
    imgui.begin_child("midnight-body", V(max(1, b_body.x - a_body.x), max(1, b_body.y - a_body.y)))
    _page(panel, c, now, page, notice)
    imgui.end_child()
    if private and panel.workspace_open:
        panel._command_palette()
    imgui.pop_font()
    imgui.pop_style_color(len(styles))
    imgui.pop_style_var(len(vars))


midnight = SimpleNamespace(
    PALETTE=PALETTE,
    bookmark=bookmark,
    control_grid=control_grid,
    heading=heading,
    index_row=index_row,
    opening_backdrop=opening_backdrop,
    poster=poster,
    section_caption=section_caption,
    switch_face=switch_face,
    track=track,
    workspace=workspace,
)


class Headset(NamedTuple):
    serial: str
    model: str
    state: str
    transport: str

    @property
    def name(self):
        return self.model or self.serial

def parse_headsets(payload):
    devices = {}
    for line in payload.decode("utf-8", "replace").splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] in ("List", "*"):
            continue
        serial, state = fields[:2]
        if fields[1:3] == ["no", "permissions"]:
            state = "no permissions"
        info = dict(field.split(":", 1) for field in fields[2:] if ":" in field)
        if serial.startswith("emulator-"):
            transport = "Emulator"
        elif "usb" in info:
            transport = "USB"
        elif "._adb-tls-connect._tcp" in serial or (
            ":" in serial and serial.rsplit(":", 1)[1].isdigit()
        ):
            transport = "Wireless"
        else:
            transport = "ADB"
        model = info.get("model", "").replace("_", " ").strip()
        devices[serial] = Headset(serial, model, state, transport)
    return tuple(sorted(devices.values(), key=lambda d: (d.name.casefold(), d.serial)))

def platform_adb(folder):
    name = "adb.exe" if sys.platform == "win32" else "adb"
    locations = [folder / name, folder / "platform-tools" / name]
    sdk = [os.environ.get(k) for k in ("ANDROID_HOME", "ANDROID_SDK_ROOT")]
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        sdk.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk")
    else:
        sdk.append(
            Path.home()
            / ("Library/Android/sdk" if sys.platform == "darwin" else "Android/Sdk")
        )
    locations.extend(Path(root) / "platform-tools" / name for root in sdk if root)
    for path in locations:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return shutil.which(name)

def adb_packet(stream):
    header = stream.read(4)
    if len(header) != 4:
        raise ConnectionError("The local ADB service disconnected.")
    if any(c not in b"0123456789abcdefABCDEF" for c in header):
        raise ConnectionError("The local ADB service returned an invalid response.")
    size = int(header, 16)
    data = stream.read(size)
    if len(data) != size:
        raise ConnectionError("The local ADB service disconnected.")
    return data

class HeadsetFeed:
    """One cancellable connection to ADB's read-only device list."""

    def __init__(self, folder, port=None):
        self.folder = folder
        self.port = port
        self.updates = queue.Queue(maxsize=16)
        self.stopped = threading.Event()
        self.sock = None

    def start(self):
        try:
            threading.Thread(target=self._watch, name="headset-status", daemon=True).start()
        except RuntimeError:
            self.updates.put_nowait(((), "Could not start device detection. Please retry."))

    def close(self):
        self.stopped.set()
        sock = self.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _publish(self, devices, error=""):
        # A hidden page only needs the most recent updates.
        if self.updates.full():
            try:
                self.updates.get_nowait()
            except queue.Empty:
                pass
        self.updates.put_nowait((devices, error))

    def _open(self):
        try:
            port = int(
                os.environ.get("ANDROID_ADB_SERVER_PORT", "5037")
                if self.port is None
                else self.port
            )
            if not 1 <= port <= 65535:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise ConnectionError(
                "The local ADB server port must be between 1 and 65535."
            ) from error
        address = ("127.0.0.1", port)
        try:
            return socket.create_connection(address, timeout=2)
        except ConnectionRefusedError:
            if self.stopped.is_set():
                raise
        adb = platform_adb(self.folder)
        if not adb:
            raise ConnectionError(
                "Install Android SDK Platform-Tools or put adb beside HavocMidnight.py, then retry."
            )
        # The standard listing command can start the local ADB service on first use.
        env = os.environ.copy()
        env.pop("ADB_SERVER_SOCKET", None)
        env.pop("ANDROID_ADB_SERVER_ADDRESS", None)
        env["ANDROID_ADB_SERVER_PORT"] = str(port)
        result = subprocess.run(
            [adb, "devices", "-l"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=6,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise ConnectionError(
                "Android Platform-Tools could not start the local ADB service. Check the installation and retry."
            )
        if self.stopped.is_set():
            raise ConnectionAbortedError()
        return socket.create_connection(address, timeout=2)

    def _watch(self):
        try:
            with self._open() as sock:
                self.sock = sock
                if self.stopped.is_set():
                    return
                sock.settimeout(5)
                service = b"host:track-devices-l"
                sock.sendall(f"{len(service):04x}".encode("ascii") + service)
                with sock.makefile("rb") as stream:
                    status = stream.read(4)
                    if status == b"FAIL":
                        detail = adb_packet(stream).decode("utf-8", "replace").strip()
                        raise ConnectionError(
                            detail[:180] or "ADB could not list devices."
                        )
                    if status != b"OKAY":
                        raise ConnectionError(
                            "The local ADB service did not accept the device check."
                        )
                    while not self.stopped.is_set():
                        self._publish(parse_headsets(adb_packet(stream)))
                        # There may be hours between plug or authorization changes.
                        sock.settimeout(None)
        except (TimeoutError, subprocess.TimeoutExpired):
            if not self.stopped.is_set():
                self._publish(
                    (),
                    "The local ADB service took too long to respond. Retry the connection.",
                )
        except OSError as error:
            if not self.stopped.is_set():
                self._publish(
                    (), str(error) or "The local ADB service closed the connection."
                )
        finally:
            self.sock = None


ACCOUNT_HOST = "havoc-keys.ninjabro0329.workers.dev"

ACCOUNT_PATH = "/verify-check"

VERIFY_LIMIT = 8 * 1024 * 1024

class VerificationError(Exception):
    """An account check did not establish a verified identity."""

@lru_cache(maxsize=1)
def machine_ids():
    guid = ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            guid = winreg.QueryValueEx(key, "MachineGuid")[0]
    except (ImportError, OSError):
        pass
    parts = [platform.node(), str(uuid.getnode())]
    if guid:
        parts.append(guid)
    legacy = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    current = hashlib.sha256(("havoc|" + guid).encode()).hexdigest()[:16] if guid else legacy
    return current, legacy

def verify_identity():
    current, legacy = machine_ids()
    body = json.dumps({"hwid": current, "hwidLegacy": legacy}).encode("utf-8")
    client = http.client.HTTPSConnection(ACCOUNT_HOST, timeout=12)
    try:
        client.request(
            "POST",
            ACCOUNT_PATH,
            body,
            {"Content-Type": "application/json", "Accept": "application/json"},
        )
        response = client.getresponse()
        if response.status in (401, 403):
            raise VerificationError(
                "This computer is not verified. Run /verify in the Havoc Discord, then try again."
            )
        if response.status == 429:
            raise VerificationError("Too many checks. Wait a moment and try again.")
        if not 200 <= response.status < 300:
            raise VerificationError(
                f"Verification is unavailable (HTTP {response.status}). Try again later."
            )
        raw = response.read(VERIFY_LIMIT + 1)
        if len(raw) > VERIFY_LIMIT:
            raise VerificationError("The verification response was too large.")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise VerificationError("Verification is still pending. Check the machine ID used in Discord.")
        # Only the display label belongs to this interface.
        label = data.get("label")
        if isinstance(label, str):
            label = "".join(char for char in " ".join(label.split()) if char.isprintable())
            if label.strip():
                return label.strip()[:80]
        return "Verified user"
    except TimeoutError as error:
        raise VerificationError("Verification timed out. Check your connection and retry.") from error
    except (OSError, http.client.HTTPException) as error:
        raise VerificationError(
            "Could not reach the verification service. Check your connection and retry."
        ) from error
    except (ValueError, UnicodeError) as error:
        raise VerificationError("The verification service returned an unreadable response.") from error
    finally:
        client.close()

class AccountSession:
    """Workers return to their own attempt. Only the UI thread can open a session."""

    def __init__(self):
        self.user = None
        self.error = ""
        self.pending = None

    def start(self):
        if self.pending is not None or self.user is not None:
            return
        channel = queue.SimpleQueue()
        self.pending, self.error = channel, ""

        def worker():
            try:
                channel.put((verify_identity(), ""))
            except VerificationError as error:
                channel.put((None, str(error)))
            except Exception:
                channel.put((None, "Verification could not finish. Please retry."))

        try:
            threading.Thread(target=worker, name="havoc-verification", daemon=True).start()
        except RuntimeError:
            self.pending, self.error = (
                None,
                "Could not start verification. Please retry.",
            )

    def poll(self):
        if self.pending is None:
            return False
        try:
            self.user, self.error = self.pending.get_nowait()
        except queue.Empty:
            return False
        self.pending = None
        return True

    def clear(self):
        self.pending, self.user, self.error = None, None, ""


MOD_OPTIONS = {
    "Slow Monsters": ("Monster Speed",),
    "Set Tag Cooldown": ("Tag Cooldown",),
    "Set Infected Threshold": ("Infected Threshold",),
    "Time Scale": ("Game Speed",),
    "Slide Control": ("Slide Amount",),
    "Custom Turn Speed": ("Turn Speed",),
    "Use Custom FOV": ("Freecam FOV",),
    "Fly (B toggles flight)": ("Fly Speed",),
    "Hand Lag": ("Hand Lag Amount",),
    "Loud Boards": ("Tap Sound ID",),
    "Name Tags": ("Tag Height", "Tag Size", "Show My FPS"),
    "Physical Menu (hold Y)": (
        "Physical Menu On Right Hand",
        "Physical Menu Size",
        "Physical Menu Height",
        "Physical Menu Text Size",
    ),
    "Show In-Game Menu": (
        "Menu Width",
        "Menu Height",
        "FPS Box Width",
        "FPS Box Height",
    ),
}

OPTION_OWNER = {
    child: parent for parent, children in MOD_OPTIONS.items() for child in children
}

def organize_controls(schema):
    roots = {(item["section"], item["name"]): item for item in schema}
    children = {}
    attached = set()
    for item in schema:
        parent = roots.get((item["section"], OPTION_OWNER.get(item["name"])))
        if parent is not None:
            children.setdefault(parent["key"], []).append(item)
            attached.add(item["key"])
    groups = []
    for item in schema:
        if item["key"] in attached:
            continue
        if item["type"] == "number" and not item.get("options"):
            groups.append((None, [item]))
        else:
            groups.append((item, children.get(item["key"], [])))
    return groups

def visible_groups(groups, values, page, query, favorites):
    words = query.casefold().split()
    result = []
    for primary, options in groups:
        members = [primary, *options] if primary else options
        category = members[0]["section"]
        if page == "Favorites":
            visible = any(item["key"] in favorites for item in members)
        elif page == "Enabled Mods":
            visible = any(
                item["type"] == "bool" and values.get(item["key"], item["value"])
                for item in members
            )
        else:
            visible = page == "All Mods" or page == category
        if visible and (
            not words
            or any(
                all(
                    word
                    in (item["name"] + " " + category + " " + item["key"]).casefold()
                    for word in words
                )
                for item in members
            )
        ):
            result.append((primary, options))
    return result


DESKTOP_RELEASE = "2026.11.24"

PAGES_ORIGIN = "https://havoc-midnight-preview.pages.dev"

DESKTOP_REPO = "https://raw.githubusercontent.com/yibbbbbbb/havoc-updates-1"

RELEASE_BYTES = 8 * 1024 * 1024

def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=".havoc-", delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(data)
        except BaseException:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

class DesktopServiceError(Exception):
    pass

class SameEndpoint(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def desktop_request(url, limit, *, method="GET", body=None, token=None):
    headers = {"User-Agent": "HavocMidnightDesktop/" + DESKTOP_RELEASE, "Accept": "*/*"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urlrequest.Request(url, data=data, method=method, headers=headers)
    try:
        with urlrequest.build_opener(SameEndpoint()).open(req, timeout=12) as response:
            data = response.read(limit + 1)
    except urlerror.HTTPError as exc:
        with exc:
            raise DesktopServiceError(f"The service returned HTTP {exc.code}.") from exc
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise DesktopServiceError(
            "Could not reach the service. Check your connection and retry."
        ) from exc
    if len(data) > limit:
        raise DesktopServiceError("The service response exceeded its size limit.")
    return data

def release_number(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"(0|[1-9][0-9]{0,5})(\.(0|[1-9][0-9]{0,5})){2}", value
    ):
        raise ValueError("Invalid desktop release number.")
    return tuple(map(int, value.split(".")))

class DesktopRelease(NamedTuple):
    version: str
    revision: str
    sha256: str
    size: int

def desktop_channel():
    releases = []
    for url in (
        PAGES_ORIGIN + "/desktop/stable.json",
        DESKTOP_REPO + "/main/public/desktop/stable.json",
    ):
        data = json.loads(desktop_request(url, 4096))
        if (
            not isinstance(data, dict)
            or data.get("product") != "havoc-midnight-desktop"
        ):
            raise ValueError("Unrecognized desktop release channel.")
        release_number(data.get("version"))
        if (
            not isinstance(data.get("revision"), str)
            or not re.fullmatch("[0-9a-f]{40}", data["revision"])
            or not isinstance(data.get("sha256"), str)
            or not re.fullmatch("[0-9a-f]{64}", data["sha256"])
            or type(data.get("size")) is not int
            or not 0 < data["size"] <= RELEASE_BYTES
        ):
            raise ValueError("Incomplete desktop release information.")
        releases.append(
            DesktopRelease(
                data["version"], data["revision"], data["sha256"], data["size"]
            )
        )
    if releases[0] != releases[1]:
        raise DesktopServiceError(
            "The release is still being published. Please check again shortly."
        )
    return releases[0]

@contextmanager
def desktop_install_lock(path):
    with path.with_suffix(path.suffix + ".update-lock").open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt

                if handle.seek(0, 2) == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DesktopServiceError(
                "Another Havoc window is updating this file."
            ) from exc
        yield

def install_desktop(path, starting_digest, offered, current=DESKTOP_RELEASE):
    if (
        release_number(offered.version) <= release_number(current)
        or desktop_channel() != offered
    ):
        raise DesktopServiceError("The release has changed. Check for updates again.")
    payload = desktop_request(
        f"{DESKTOP_REPO}/{offered.revision}/public/desktop/HavocMidnight.py",
        offered.size,
    )
    if (
        len(payload) != offered.size
        or hashlib.sha256(payload).hexdigest() != offered.sha256
    ):
        raise DesktopServiceError(
            "The download failed its integrity check. Your desktop file is unchanged."
        )
    tree = ast.parse(payload)
    compile(tree, str(path), "exec")
    versions = [
        s.value.value
        for s in tree.body
        if isinstance(s, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "DESKTOP_RELEASE" for t in s.targets
        )
        and isinstance(s.value, ast.Constant)
    ]
    if versions != [offered.version]:
        raise DesktopServiceError("The file and release number do not match.")
    with desktop_install_lock(path):
        if path.is_symlink() or not path.is_file():
            raise DesktopServiceError(
                "Open a regular desktop .py file before updating."
            )
        previous = path.read_bytes()
        if hashlib.sha256(previous).hexdigest() != starting_digest:
            raise DesktopServiceError(
                "The desktop file changed while Havoc was open. Reopen it before updating."
            )
        mode = stat.S_IMODE(path.stat().st_mode)
        with NamedTemporaryFile(
            dir=path.parent, prefix=".havoc-release-", delete=False
        ) as f:
            staged = Path(f.name)
        try:
            with staged.open("wb") as out:
                out.write(payload)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(staged, mode)
            atomic_write(path.with_suffix(path.suffix + ".previous"), previous)
            os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)

class DesktopUpdater:
    def __init__(self, path):
        self.path = Path(path).absolute()
        try:
            self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        except OSError:
            self.digest = None
        self.phase, self.message, self.offer = "idle", "", None
        self.pending = None

    def start(self, install=False):
        if self.pending is not None or self.phase == "installed":
            return
        offer = self.offer
        if install and (not self.digest or offer is None):
            return
        self.phase = "installing" if install else "checking"
        self.message = (
            "Verifying and installing the download…"
            if install
            else "Checking the latest desktop release…"
        )
        channel = self.pending = queue.SimpleQueue()

        def work():
            try:
                if install:
                    install_desktop(self.path, self.digest, offer)
                    result = ("installed", "Update installed. Restarting Havoc…", None)
                else:
                    latest = desktop_channel()
                    if release_number(latest.version) > release_number(DESKTOP_RELEASE):
                        result = (
                            "offered",
                            "Desktop " + latest.version + " is available.",
                            latest,
                        )
                    else:
                        result = ("current", "You’re up to date.", None)
            except DesktopServiceError as exc:
                result = ("error", str(exc), None)
            except (ValueError, SyntaxError, UnicodeError, TypeError):
                result = (
                    "error",
                    "The release could not be verified. Try again later.",
                    None,
                )
            except OSError:
                result = (
                    "error",
                    "Could not write the desktop update. Check this folder’s permissions and free space.",
                    None,
                )
            except (KeyError, RuntimeError):
                result = (
                    "error",
                    "The update check could not finish. Please retry.",
                    None,
                )
            channel.put(result)

        try:
            threading.Thread(
                target=work, daemon=not install, name="havoc-desktop-update"
            ).start()
        except RuntimeError:
            self.pending, self.phase, self.message = (
                None,
                "error",
                "Could not start the update. Please retry.",
            )

    def poll(self):
        if self.pending is not None:
            try:
                self.phase, self.message, self.offer = self.pending.get_nowait()
                self.pending = None
            except queue.Empty:
                pass


def presence_request(route, method="GET", token=None, body=None):
    return json.loads(
        desktop_request(
            PAGES_ORIGIN + "/api/presence/" + route,
            40_000,
            method=method,
            body=body,
            token=token,
        )
    )

def online_roster(token, current=lambda: True):
    names = {}
    cursor = ""
    while current():
        data = presence_request(
            "members" + ("?after=" + cursor if cursor else ""), token=token
        )
        members = data["members"]
        if not isinstance(members, list) or len(members) > 100:
            raise ValueError("Roster format")
        for entry in members:
            member, name = entry["id"], entry["name"]
            if (
                not isinstance(member, str)
                or not re.fullmatch("[0-9a-f]{24}", member)
                or not isinstance(name, str)
                or not 0 < len(name) <= 80
            ):
                raise ValueError("Roster entry")
            names[member] = name
        following = data["next"]
        if following is None:
            return tuple(sorted(names.values(), key=str.casefold))
        if (
            not isinstance(following, str)
            or not re.fullmatch("[0-9a-f]{24}", following)
            or following <= cursor
        ):
            raise ValueError("Roster cursor")
        cursor = following

class OnlineSession:
    """One serial worker owns a login's bearer and discards superseded views."""

    def __init__(self):
        self.cv = threading.Condition()
        self.desired = (False, False, False)
        self.revision = 0
        self.ended = False
        self.retry_available = False
        self.thread = None
        self.snapshot = ("", None)
        self._count = (None, 0)

    @property
    def count(self):
        value, checked = self._count
        return value if 0 <= time.time() - checked < 75 else None

    def set_interest(self, share, view, *, watch=False):
        with self.cv:
            if self.ended or (share, view, watch) == self.desired:
                return
            self.desired = (share, view, watch)
            self.retry_available = False
            if not any(self.desired):
                self._count = (None, 0)
            self.revision += 1
            self.snapshot = (
                "Refreshing online status…" if any(self.desired) else "",
                None,
            )
            if self.thread is None and any(self.desired):
                self.thread = threading.Thread(
                    target=self._run, daemon=True, name="havoc-online"
                )
                try:
                    self.thread.start()
                except RuntimeError:
                    self.thread = None
                    self.desired = (False, False, False)
                    self.snapshot = ("Could not start the online list.", None)
            self.cv.notify_all()

    def retry_now(self):
        with self.cv:
            if self.ended or not self.retry_available:
                return
            self.retry_available = False
            self.snapshot = ("Refreshing online status…", None)
            self.revision += 1
            self.cv.notify_all()

    def close(self):
        with self.cv:
            self.ended = True
            self.retry_available = False
            self.revision += 1
            self.snapshot = ("", None)
            self._count = (None, 0)
            self.cv.notify_all()

    @staticmethod
    def _leave(token):
        if token:
            try:
                presence_request("session", "DELETE", token)
            except (DesktopServiceError, ValueError):
                return  # A missed heartbeat also expires on the server.

    def _run(self):
        token = None
        retry = 5
        was_sharing = False
        try:
            while True:
                with self.cv:
                    if self.ended:
                        return
                    share, view, watch = self.desired
                    rev = self.revision
                delay = None
                if share or view or watch:
                    had_token = token is not None
                    failed = False
                    try:
                        if token is None:
                            primary, legacy = machine_ids()
                            token = presence_request(
                                "session",
                                "POST",
                                body={"hwid": primary, "hwidLegacy": legacy},
                            )["token"]
                            if not isinstance(token, str) or not re.fullmatch(
                                "[0-9a-f]{64}", token
                            ):
                                token = None
                                raise ValueError("Invalid session")
                        with self.cv:
                            if self.revision != rev:
                                continue
                        if share or view or was_sharing:
                            was_sharing = share or was_sharing
                            presence_request("live", "PUT", token, {"visible": share})
                            was_sharing = share
                        names = (
                            online_roster(token, lambda rev=rev: self.revision == rev)
                            if view
                            else None
                        )
                        count = len(names) if names is not None else None
                        if watch and not view:
                            count = presence_request("count", token=token)["count"]
                            if type(count) is not int or count < 0:
                                raise ValueError("Invalid online count")
                        result = (
                            "Your name is visible."
                            if share
                            else "Your name is hidden.",
                            names,
                        )
                        delay, retry = 30, 5
                    except (
                        DesktopServiceError,
                        OSError,
                        ValueError,
                        KeyError,
                        TypeError,
                    ) as exc:
                        count = None
                        status = getattr(exc.__cause__, "code", None)
                        failed = True
                        delay = retry
                        if status == 401:
                            token = None
                            if had_token:
                                delay = 0  # Renew a previously established session once immediately.
                        if delay:
                            retry = min(retry * 2, 60)
                        result = (
                            "Online list unavailable. Retrying automatically.",
                            None,
                        )
                        if status == 503:
                            result = (
                                "The online service is unavailable. Retrying automatically.",
                                None,
                            )
                        if status == 403:
                            result = (
                                "Account verification was declined. Check your Havoc sign-in.",
                                None,
                            )
                    with self.cv:
                        if self.revision == rev:
                            self.snapshot = result
                            self.retry_available = failed and delay > 0
                            self._count = (count, time.time())
                else:
                    self._leave(token)
                    token, retry, was_sharing = None, 5, False
                with self.cv:
                    self.cv.wait_for(
                        lambda rev=rev: self.ended or self.revision != rev,
                        timeout=delay,
                    )
        finally:
            self._leave(token)

class HeadsetPanel:
    """The device inspector shared by the standalone and installed menus."""

    def __init__(self, panel):
        cfg = panel._load_cfg()
        self.auto_retry = cfg.get("monitor_reconnect", True) is not False
        self.retry_at, self.attempt = None, 0
        saved = cfg.get("monitor_serial", "")
        self.serial = saved if isinstance(saved, str) else ""
        self.pinned = self.serial
        self.feed = None
        self.devices = ()
        self.phase, self.error = "idle", ""
        self.visual_state, self.changed_at = None, 0.0

    def close(self):
        if self.feed is not None:
            self.feed.close()
            self.feed = None
        self.devices = ()
        self.phase, self.error = "idle", ""
        self.retry_at, self.attempt = None, 0

    def connect(self, *, retry=False):
        attempts = self.attempt if retry else 0
        self.close()
        self.attempt = attempts
        self.phase = "checking"
        self.feed = HeadsetFeed(APP_DIR)
        self.feed.start()

    def selected(self):
        return next((device for device in self.devices if device.serial == self.serial), None)

    def status(self):
        if self.phase == "idle":
            return (
                "idle",
                "Ready to check",
                "Connect to the local Android Debug Bridge to see USB and wireless devices.",
            )
        if self.phase == "checking":
            return "checking", "Checking devices…", "Contacting the local Android Debug Bridge."
        if self.phase == "error" and self.retry_at is not None:
            remaining = max(0, math.ceil(self.retry_at - time.monotonic()))
            return "checking", "Reconnecting", f"Device-status connection lost. Retrying in {remaining}s."
        if self.phase == "error":
            return "error", "Device check interrupted", self.error
        device = self.selected()
        if device is None:
            if not self.devices:
                return (
                    "waiting",
                    "Waiting for a headset",
                    "Plug in your headset. This page updates when it appears.",
                )
            if self.serial:
                return (
                    "waiting",
                    "Selected device disconnected",
                    "Reconnect it or choose another device below.",
                )
            return "waiting", "Choose a device", "Select the headset you want to monitor."
        if device.state == "device":
            return "ready", "Device connected", f"{device.name} · {device.transport}"
        if device.state in ("unauthorized", "authorizing"):
            return (
                "attention",
                "Authorization needed",
                "Unlock the headset and approve the debugging prompt.",
            )
        if device.state == "offline":
            return "attention", "Headset offline", "Reconnect the headset. Its status will update here."
        if device.state == "no permissions":
            return (
                "attention",
                "USB permission needed",
                "Your operating system needs to grant access to this device.",
            )
        return "attention", "Device unavailable", f"{device.name} · {device.state}"

    def update(self, panel):
        if self.retry_at is not None and time.monotonic() >= self.retry_at:
            self.connect(retry=True)
        while self.feed is not None:
            try:
                devices, error = self.feed.updates.get_nowait()
            except queue.Empty:
                break
            previous = self.status()
            was_live = self.phase == "live"
            self.devices, self.error = devices, error
            self.phase = "error" if error else "live"
            if error:
                self.feed.close()
                self.feed = None
                if self.auto_retry and (was_live or self.attempt) and self.attempt < 3:
                    self.attempt += 1
                    self.retry_at = time.monotonic() + 2**self.attempt
            else:
                self.attempt, self.retry_at = 0, None
                if self.pinned:
                    self.serial = self.pinned
                elif not self.selected():
                    self.serial = devices[0].serial if len(devices) == 1 else ""
            current = self.status()
            if current != previous:
                if error:
                    panel.log(error + (" " + current[2] if self.retry_at is not None else ""))
                else:
                    selected = self.selected()
                    panel.log(current[1] + (" · " + selected.name if selected else ""))

    def _status_card(self, panel):
        kind, title, hint = self.status()
        prefs = panel.preferences
        now = imgui.get_time()
        if (kind, self.serial) != self.visual_state:
            self.visual_state, self.changed_at = (kind, self.serial), now
        duration = prefs["duration"] / (10 * prefs["speed"])
        fraction = (
            min(1, (now - self.changed_at) / duration)
            if panel.ambient_motion and prefs["transition"] != "Instant"
            else 1
        )
        opacity = 0.35 + 0.65 * (1 - (1 - fraction) ** 3)
        ink = imgui.get_style().color_(
            imgui.Col_.check_mark if kind == "ready" else imgui.Col_.text_disabled
        )
        if kind in ("attention", "error"):
            ink = ImVec4(0.96, 0.68, 0.48, 1)
        p = imgui.get_cursor_screen_pos()
        z = panel.zoom
        imgui.get_window_draw_list().add_circle_filled(
            ImVec2(p.x + 5 * z, p.y + imgui.get_text_line_height() / 2),
            3.5 * z,
            imgui.get_color_u32(ImVec4(ink.x, ink.y, ink.z, opacity)),
            16,
        )
        imgui.indent(15 * z)
        imgui.text_wrapped(title)
        imgui.unindent(15 * z)
        imgui.text_wrapped(hint)
        imgui.spacing()

        active = self.phase in ("checking", "live")
        w = max(1, imgui.get_content_region_avail().x)
        gap = imgui.get_style().item_spacing.x
        button_width = min(128 * z, max(1, (w - gap) / 2) if active or self.retry_at is not None else w)
        if self.phase != "checking":
            label = "Refresh" if active else ("Retry" if self.phase == "error" else "Connect")
            if panel._button(label, button_width, 30, primary=True):
                self.connect()
            if imgui.is_item_hovered():
                imgui.set_tooltip("Read live device status from this computer’s Android Debug Bridge.")
            if active:
                imgui.same_line(0, gap)
        if active or self.retry_at is not None:
            if not active:
                imgui.same_line(0, gap)
            if panel._button(
                "Cancel" if (self.phase == "checking" or self.retry_at is not None) else "Disconnect",
                button_width,
                30,
            ):
                self.close()
                panel.log("Headset monitor disconnected")
            if imgui.is_item_hovered():
                imgui.set_tooltip("Close this device-status connection.")
        if self.devices and (len(self.devices) > 1 or not self.selected()):
            labels = [
                f"{d.model} · {d.serial}" if d.model and d.model != d.serial else d.serial
                for d in self.devices
            ]
            serials = [d.serial for d in self.devices]
            if self.serial not in serials:
                serials.insert(0, "")
                labels.insert(0, "Choose a device")
            index = serials.index(self.serial) if self.serial in serials else 0
            imgui.spacing()
            panel._section_caption("Device")
            imgui.set_next_item_width(-1)
            changed, index = imgui.combo("##headset-choice", index, labels)
            if changed and serials[index]:
                self.pinned = self.serial = serials[index]
                panel._save_display_settings(monitor_serial=self.serial)
                panel.log("Selected " + self.selected().name)

    def _checks(self, panel):
        panel._section_caption("Connection checks")
        selected = self.selected()
        waiting = (
            "Not checked"
            if self.phase == "idle"
            else (
                "Selected device disconnected"
                if self.pinned and self.phase == "live"
                else "Waiting for a device"
            )
        )
        checks = (
            ("Account", panel.account.user or "Signed out"),
            (
                "Android Debug Bridge",
                {
                    "idle": "Not checked",
                    "checking": "Checking…",
                    "live": "Listening",
                    "error": "Unavailable",
                }[self.phase],
            ),
            (
                "Headset",
                selected.name
                if selected
                else ("Choose a device" if self.devices and not self.pinned else waiting),
            ),
            (
                "Authorization",
                {
                    "device": "Authorized",
                    "offline": "Offline",
                    "unauthorized": "Approval needed",
                    "authorizing": "Waiting for approval",
                    "no permissions": "USB permission needed",
                }.get(selected.state if selected else "", selected.state if selected else waiting),
            ),
        )
        if imgui.begin_table(
            "##checks",
            2,
            imgui.TableFlags_.sizing_stretch_prop
            | imgui.TableFlags_.row_bg
            | imgui.TableFlags_.borders_inner_h,
        ):
            imgui.table_setup_column("Step", imgui.TableColumnFlags_.width_stretch, 1.15)
            imgui.table_setup_column("Status", imgui.TableColumnFlags_.width_stretch, 1.0)
            for index, (label, detail) in enumerate(checks, 1):
                imgui.table_next_row(0, max(31 * panel.zoom, imgui.get_frame_height() + 5))
                imgui.table_next_column()
                imgui.align_text_to_frame_padding()
                imgui.text_wrapped(f"{index:02}  {label}")
                imgui.table_next_column()
                imgui.align_text_to_frame_padding()
                imgui.text_wrapped(detail)
            imgui.end_table()

    def draw(self, panel, *, standalone):
        if not standalone:
            self.update(panel)
        w = imgui.get_content_region_avail().x
        spread = (
            standalone
            and w >= max(570 * panel.zoom, 37 * imgui.get_font_size())
            and imgui.begin_table(
                "headset-overview",
                2,
                imgui.TableFlags_.sizing_stretch_same | imgui.TableFlags_.no_saved_settings,
            )
        )
        if spread:
            imgui.table_next_column()
        if standalone:
            panel._poster("Workspace", "Connection", height=160 if spread else 94, motif="device")
            imgui.spacing()
            panel._section_caption("Session status")
        self._status_card(panel)
        if standalone:
            if spread:
                imgui.table_next_column()
            else:
                imgui.spacing()
            self._checks(panel)
        if spread:
            imgui.end_table()
        imgui.spacing()
        if standalone:
            panel._section_caption("Session details")
            imgui.text_wrapped("Signed in as " + panel.account.user)
            if panel._button("Log out", min(w, 104 * panel.zoom), 28):
                panel.logout()
                return
        if imgui.collapsing_header("Device options"):
            changed, enabled = imgui.checkbox("Reconnect after a lost connection", self.auto_retry)
            if changed:
                self.auto_retry = enabled
                panel._save_display_settings(monitor_reconnect=enabled)
                if not enabled:
                    self.retry_at = None
            selected = self.selected()
            if selected:
                if selected.model:
                    imgui.text_wrapped("Model   " + selected.model)
                imgui.text_wrapped("Transport   " + selected.transport)
                imgui.text_wrapped("Serial   " + selected.serial)
                if panel._button("Copy serial", min(110 * panel.zoom, w), 27):
                    imgui.set_clipboard_text(selected.serial)
                if not self.pinned:
                    pin_width = imgui.calc_text_size("Remember this device").x + 18 * panel.zoom
                    if w >= pin_width + 120 * panel.zoom:
                        imgui.same_line()
                    if panel._button("Remember this device", min(pin_width, w), 27):
                        self.pinned = selected.serial
                        panel._save_display_settings(monitor_serial=self.pinned)
            elif self.pinned:
                imgui.text_wrapped("Remembered device   " + self.pinned)
            if self.pinned and panel._button("Use automatic selection", min(210 * panel.zoom, w), 27):
                self.pinned = ""
                self.serial = self.devices[0].serial if len(self.devices) == 1 else ""
                panel._save_display_settings(monitor_serial="")
                panel.log("Automatic device selection")
        if standalone and imgui.collapsing_header("Activity log"):
            if not panel.loglines:
                imgui.text_disabled("No activity yet.")
            else:
                if panel._button("Copy log", min(100 * panel.zoom, w), 26):
                    imgui.set_clipboard_text("\n".join(panel.loglines[-200:]))
                for line in panel.loglines[-40:]:
                    imgui.text_wrapped(line)


def page_filter(panel):
    w = max(1, imgui.get_content_region_avail().x)
    clear = imgui.calc_text_size("Clear").x + 2 * imgui.get_style().frame_padding.x
    imgui.set_next_item_width(max(1, w - clear - imgui.get_style().item_spacing.x) if panel.search else w)
    changed, query = imgui.input_text_with_hint("##page-filter", "Filter this page…", panel.search)
    if changed:
        panel.search = query
    if panel.search:
        imgui.same_line()
        if imgui.button("Clear##filter"):
            panel.search = ""
    imgui.spacing()


CATALOG = (
    ('hb187fb', 'Slow Monsters', 'Game Mods', False, None),
    ('h11ef52', 'Monster Speed', 'Game Mods', 0.02, (0, 1)),
    ('h900636', 'Tag Freeze', 'Game Mods', False, None),
    ('h5ed5df', 'Hand Tap Volume', 'Game Mods', 0.1, (0, 100)),
    ('h3bbf7b', 'Set Tag Cooldown', 'Game Mods', False, None),
    ('h0471d7', 'Tag Cooldown', 'Game Mods', 1.0, (0, 10)),
    ('h535f7a', 'Set Infected Threshold', 'Game Mods', False, None),
    ('he9baed', 'Infected Threshold', 'Game Mods', 4, (1, 10)),
    ('h29ba51', 'Time Scale', 'Game Mods', False, None),
    ('h166bce', 'Game Speed', 'Game Mods', 1.0, (0.25, 3)),
    ('h242d67', 'Jump Multiplier', 'Movement', 1.1, (1, 20)),
    ('h772320', 'Slide Control', 'Movement', False, None),
    ('hfc037d', 'Slide Amount', 'Movement', 1.0, (0, 2)),
    ('h3650b5', 'Low Gravity', 'Movement', False, None),
    ('hbf8366', 'Zero Gravity', 'Movement', False, None),
    ('h7a0d0e', 'Custom Turn Speed', 'Movement', False, None),
    ('h6c9186', 'Turn Speed', 'Movement', 360, (90, 720)),
    ('hc20047', 'Force Rain', 'Day / Night', False, None),
    ('h8ca1ac', 'Use Custom FOV', 'Visuals', False, None),
    ('hbd8e24', 'Freecam FOV', 'Visuals', 90, (60, 120)),
    ('hc6763f', 'Bunny Hop', 'Movement', False, None),
    ('he3005b', 'Water Off', 'Movement', False, None),
    ('hab9e07', 'Noclip', 'Movement', False, None),
    ('h2c632b', 'Platforms', 'Movement', False, None),
    ('ha7091e', 'Fly (B toggles flight)', 'Movement', False, None),
    ('h6a8280', 'Fly Speed', 'Movement', 10, (1, 60)),
    ('h7c64f0', 'Freecam', 'Visuals', False, None),
    ('h003b4d', 'Spaz Monsters', 'Game Mods', False, None),
    ('h630d2b', 'Loud Boards', 'Detected', False, None),
    ('hb11fe3', 'Tap Sound ID', 'Detected', 84, (0, 128)),
    ('h529cd1', 'Slow Everyone', 'Detected', False, None),
    ('he63c1f', 'Vibrate Everyone', 'Detected', False, None),
    ('hb607fe', 'Projectile Rain', 'Detected', False, None),
    ('h603ab2', 'Impact Spam', 'Detected', False, None),
    ('hbb9928', 'Set Master Client', 'Detected', False, None),
    ('he17165', 'Destroy All', 'Detected', False, None),
    ('hff1e08', 'Lag All Players', 'Detected', False, None),
    ('hcd35ff', 'Name Tags', 'Detected', False, None),
    ('hf9bf19', 'Dump Tag Classes', 'Debug', False, None),
    ('hc5e564', 'Tracers', 'Visuals', False, None),
    ('h919d60', 'Box ESP', 'Visuals', False, None),
    ('h93505b', 'Rig Gun (view)', 'Rig', False, None),
    ('hdf4d57', 'Grab Rig', 'Rig', False, None),
    ('h18b7d1', 'Spaz Rig', 'Rig', False, None),
    ('h4c773a', 'Freeze Rig', 'Rig', False, None),
    ('ha33a96', 'Paralyze', 'Rig', False, None),
    ('h130eb1', 'Chicken Rig', 'Rig', False, None),
    ('h33680b', 'Amputate', 'Rig', False, None),
    ('h185276', 'Decapitate', 'Rig', False, None),
    ('h7a01f6', 'Floating Head', 'Rig', False, None),
    ('ha8c2ed', 'Laggy Rig', 'Rig', False, None),
    ('h720c2b', 'Update Rig', 'Rig', False, None),
    ('h4ad556', 'Show In-Game Menu', 'On-Screen Menu', False, None),
    ('haf8683', 'Hand Lag', 'Hand Lag', False, None),
    ('h25db57', 'Hand Lag Amount', 'Hand Lag', 0.7, (0, 1)),
    ('h866fe3', 'Tag Height', 'Detected', 0.55, (0, 2)),
    ('h793faf', 'Tag Size', 'Detected', 0.004, (0.001, 0.02)),
    ('hcdcf84', 'Show My FPS', 'Detected', True, None),
    ('h1a0a31', 'Gui Temp Menu (in-VR)', 'On-Screen Menu', False, None),
    ('hc17916', 'Physical Menu (hold Y)', 'On-Screen Menu', False, None),
    ('h65a00e', 'Physical Menu On Right Hand', 'On-Screen Menu', False, None),
    ('h674dc0', 'Physical Menu Size', 'On-Screen Menu', 1.15, (0.15, 2.0)),
    ('h58c0c4', 'Physical Menu Height', 'On-Screen Menu', 0.26, (0, 1.0)),
    ('h47d5ae', 'Physical Menu Text Size', 'On-Screen Menu', 1.0, (0.2, 5.0)),
    ('h59eb98', 'Menu Width', 'On-Screen Menu', 460, (0, 500)),
    ('hb6c1ff', 'Menu Height', 'On-Screen Menu', 360, (0, 500)),
    ('hee67a6', 'FPS Box Width', 'On-Screen Menu', 210, (0, 500)),
    ('h554510', 'FPS Box Height', 'On-Screen Menu', 300, (0, 500)),
)
LOCAL_PAGE_ACTIONS = {'Debug': ('check for updates',
           'DUMP ASSEMBLY-CSHARP',
           'DUMP EVERY ASSEMBLY',
           'PULL GAME INFO',
           'COPY RESULTS',
           'SCAN LOBBY',
           'COPY'),
 'Jump Speed Checker': ('Refresh lobby',),
 'Pull Mod': ('Controller binding',),
 'Speed Boost': ('Controller binding',),
 'High Gravity': ('Controller binding',),
 'Predictions': ('Controller binding',),
 'Tag Aura': ('Controller binding',),
 'PSA': ('Controller binding',),
 'Hand Snap': ('Controller binding',),
 'Game Mods': ('LIGHTNING',
               'MUTE ALL',
               'UNMUTE ALL',
               'SLOW EVERYONE',
               'VIBRATE ALL',
               'TAG ALL (MASTER)',
               'UNTAG ALL')}

COLLECTIONS = (
    ("Movement", ("Movement", "Pull Mod", "Speed Boost", "High Gravity", "Hand Snap", "Hand Lag", "Local Scale")),
    ("Tag", ("Tag Aura", "Tag Fix", "Predictions", "PSA", "Right Hand PSA")),
    ("Visuals", ("Day / Night", "Visuals", "On-Screen Menu")),
    ("Game", ("Game Mods", "Fun", "QOL", "Detected", "Rig", "Modsided Cosmetx")),
    ("Utilities", ("Debug", "Soundboard", "Jump Speed Checker")),
    ("Workspace", ("Connection", "Appearance")),
)
class Navigation:
    VIRTUAL_PAGES = ("Dashboard", "All Mods", "Enabled Mods", "Favorites")
    HIDDEN_KEYS = frozenset()

    @staticmethod
    def navigation_groups(schema):
        return COLLECTIONS

    @staticmethod
    def section_label(page):
        return page

    @staticmethod
    def section_for_item(item):
        return item["section"]

    @staticmethod
    def matching_items(schema, values, page, query="", favorites=()):
        words = query.casefold().split()
        result = []
        for item in schema:
            key = item["key"]
            if page == "Favorites":
                visible = key in favorites
            elif page == "Enabled Mods":
                visible = item["type"] == "bool" and values[key]
            else:
                visible = page == "All Mods" or page == item["section"]
            searchable = (item["name"] + " " + item["section"] + " " + key).casefold()
            if visible and all(word in searchable for word in words):
                result.append(item)
        return result



nav = Navigation
_blend = blend
_tint = tint
RESERVED_PRESETS = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
}


def pretty_key(key):
    return key.replace("_", " ").title()


THEMES = {
    "Havoc": {
        "bg": (19, 19, 32), "panel": (28, 27, 44), "card": (38, 37, 56),
        "card2": (53, 49, 73), "edge": (79, 74, 99), "text": (248, 242, 226),
        "muted": (196, 187, 210), "faint": (162, 153, 182),
        "acc": (251, 192, 115), "acc_hi": (255, 226, 173), "alt": (179, 162, 241),
        "grad": ((40, 34, 57), (18, 18, 31)),
        "p1": (251, 192, 115), "p2": (179, 162, 241), "fall": False, "style": "dust",
    },
    "Havoc Pink": {
        "bg": (24, 21, 27), "panel": (30, 26, 34), "card": (45, 39, 51),
        "card2": (60, 51, 68), "edge": (84, 68, 94), "text": (242, 234, 242),
        "muted": (158, 140, 158), "faint": (110, 96, 114),
        "acc": (255, 96, 196), "acc_hi": (255, 148, 222), "alt": (188, 104, 255),
        "grad": ((66, 42, 78), (34, 27, 40)),
        "p1": (255, 108, 214), "p2": (188, 104, 255), "fall": False,
        "style": "orb",
    },
    "Matrix": {
        "bg": (5, 12, 7), "panel": (8, 18, 11), "card": (14, 29, 19),
        "card2": (20, 44, 27), "edge": (32, 66, 42), "text": (188, 255, 200),
        "muted": (94, 182, 116), "faint": (56, 118, 74),
        "acc": (48, 255, 106), "acc_hi": (140, 255, 168), "alt": (16, 236, 92),
        "grad": ((10, 32, 16), (2, 8, 4)),
        "p1": (48, 255, 106), "p2": (180, 255, 192), "fall": True,
        "style": "matrix",
    },
    "Vaporwave": {
        "bg": (24, 10, 46), "panel": (32, 15, 60), "card": (49, 25, 86),
        "card2": (66, 35, 108), "edge": (92, 52, 140), "text": (246, 226, 255),
        "muted": (178, 142, 218), "faint": (124, 94, 166),
        "acc": (255, 84, 204), "acc_hi": (86, 242, 255), "alt": (150, 92, 255),
        "grad": ((60, 26, 100), (14, 7, 32)),
        "p1": (86, 242, 255), "p2": (255, 100, 214), "fall": False,
        "style": "wave",
    },
    "Ember": {
        "bg": (24, 12, 8), "panel": (33, 17, 11), "card": (52, 28, 19),
        "card2": (68, 38, 25), "edge": (96, 52, 33), "text": (255, 233, 216),
        "muted": (190, 142, 118), "faint": (134, 96, 78),
        "acc": (255, 118, 34), "acc_hi": (255, 188, 108), "alt": (255, 62, 40),
        "grad": ((66, 30, 15), (18, 8, 5)),
        "p1": (255, 134, 52), "p2": (255, 206, 140), "fall": False,
        "style": "ember",
    },
    "Ice": {
        "bg": (10, 17, 27), "panel": (14, 23, 35), "card": (25, 40, 57),
        "card2": (35, 54, 76), "edge": (50, 76, 104), "text": (226, 242, 255),
        "muted": (140, 174, 204), "faint": (92, 124, 154),
        "acc": (80, 206, 255), "acc_hi": (178, 236, 255), "alt": (86, 148, 255),
        "grad": ((24, 44, 64), (7, 12, 20)),
        "p1": (138, 222, 255), "p2": (220, 248, 255), "fall": True,
        "style": "snow",
    },
    "Mono": {
        "bg": (18, 18, 18), "panel": (24, 24, 24), "card": (38, 38, 38),
        "card2": (50, 50, 50), "edge": (66, 66, 66), "text": (238, 238, 238),
        "muted": (150, 150, 150), "faint": (104, 104, 104),
        "acc": (235, 235, 235), "acc_hi": (255, 255, 255), "alt": (170, 170, 170),
        "grad": ((44, 44, 44), (14, 14, 14)),
        "p1": (210, 210, 210), "p2": (255, 255, 255), "fall": False,
        "style": "dust",
    },
    "Overworld": {
        "bg": (16, 24, 17), "panel": (24, 34, 25), "card": (35, 47, 34),
        "card2": (46, 63, 43), "edge": (82, 104, 74), "text": (240, 246, 222),
        "muted": (183, 201, 166), "faint": (149, 172, 133),
        "acc": (186, 231, 128), "acc_hi": (224, 251, 179), "alt": (246, 193, 106),
        "grad": ((35, 52, 33), (14, 22, 16)), "p1": (186, 231, 128),
        "p2": (246, 193, 106), "fall": False, "style": "dust",
    },
    "Redstone": {
        "bg": (25, 17, 20), "panel": (37, 24, 29), "card": (52, 34, 39),
        "card2": (71, 43, 48), "edge": (117, 77, 78), "text": (255, 238, 230),
        "muted": (220, 184, 175), "faint": (190, 151, 146),
        "acc": (255, 136, 123), "acc_hi": (255, 191, 158), "alt": (239, 198, 134),
        "grad": ((59, 30, 36), (23, 16, 19)), "p1": (253, 119, 109),
        "p2": (239, 198, 134), "fall": False, "style": "ember",
    },
    "Amethyst": {
        "bg": (23, 19, 35), "panel": (33, 27, 48), "card": (46, 38, 66),
        "card2": (59, 50, 85), "edge": (96, 84, 126), "text": (247, 240, 255),
        "muted": (202, 190, 219), "faint": (169, 156, 190),
        "acc": (207, 172, 250), "acc_hi": (238, 215, 255), "alt": (140, 219, 206),
        "grad": ((50, 39, 72), (20, 17, 32)), "p1": (207, 172, 250),
        "p2": (140, 219, 206), "fall": False, "style": "orb",
    },
    "Sandstone": {
        "bg": (226, 214, 187), "panel": (250, 244, 226), "card": (241, 229, 204),
        "card2": (231, 214, 182), "edge": (150, 125, 90), "text": (55, 44, 33),
        "muted": (89, 72, 55), "faint": (101, 81, 62),
        "acc": (128, 60, 32), "acc_hi": (150, 66, 32), "alt": (37, 107, 102),
        "grad": ((229, 217, 188), (210, 196, 167)), "p1": (158, 105, 52),
        "p2": (45, 114, 105), "fall": False, "style": "dust",
    },
    "Tidepool": {
        "bg": (13, 28, 38), "panel": (19, 40, 49), "card": (28, 54, 63),
        "card2": (40, 70, 78), "edge": (74, 100, 105), "text": (238, 250, 234),
        "muted": (184, 212, 204), "faint": (153, 181, 180),
        "acc": (139, 229, 206), "acc_hi": (206, 251, 218), "alt": (253, 172, 130),
        "grad": ((24, 49, 55), (14, 27, 35)), "p1": (139, 229, 206),
        "p2": (253, 172, 130), "fall": False, "style": "dust",
    },
    "Parchment": {
        "bg": (224, 215, 201), "panel": (247, 240, 223), "card": (236, 226, 207),
        "card2": (225, 212, 191), "edge": (157, 134, 117), "text": (55, 42, 48),
        "muted": (92, 72, 76), "faint": (111, 90, 91),
        "acc": (128, 55, 75), "acc_hi": (149, 66, 79), "alt": (80, 96, 132),
        "grad": ((233, 223, 206), (213, 201, 190)), "p1": (128, 55, 75),
        "p2": (80, 96, 132), "fall": False, "style": "dust",
    },
}

THEME_NAMES = [*THEMES, "Custom"]

THEME = "Havoc"

CUSTOM_ACC = (232, 160, 191)

CUSTOM_BG = (28, 28, 31)

def _mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))

def _lift(c, amount):
    if amount >= 0:
        return _mix(c, (255, 255, 255), amount)
    return _mix(c, (0, 0, 0), -amount)

def _ease(t):
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3

def build_custom(acc, bg):
    lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    dark_bg = lum < 140
    text = (238, 238, 242) if dark_bg else (26, 26, 30)
    step = 1.0 if dark_bg else -1.0
    return {
        "bg": bg,
        "panel": _lift(bg, 0.05 * step),
        "card": _lift(bg, 0.14 * step),
        "card2": _lift(bg, 0.21 * step),
        "edge": _lift(bg, 0.30 * step),
        "text": text,
        "muted": _mix(text, bg, 0.42),
        "faint": _mix(text, bg, 0.62),
        "acc": acc,
        "acc_hi": _lift(acc, 0.28),
        "alt": _lift(acc, -0.18),
        "grad": (_lift(bg, 0.10 * step), _lift(bg, -0.12 * step)),
        "p1": acc,
        "p2": _lift(acc, 0.45),
        "fall": False,
        "style": "orb",
    }

BG = PANEL = CARD = CARD2 = EDGE = TEXT = MUTED = FAINT = None

PINK = PINK_HI = PURPLE = ON = OFFCOL = None

GRAD_TOP = GRAD_BOT = P1 = P2 = None

FALL = False

STYLE = "orb"

CUR_ACC = (232, 160, 191)   # active theme accent + alt (for the in-VR menu)

CUR_ALT = (198, 150, 220)

def apply_theme(name, overrides=None, layout="Classic"):
    global BG, PANEL, CARD, CARD2, EDGE, TEXT, MUTED, FAINT
    global PINK, PINK_HI, PURPLE, ON, OFFCOL
    global GRAD_TOP, GRAD_BOT, P1, P2, FALL, THEME, STYLE
    global CUR_ACC, CUR_ALT, ART_PALETTE
    if name == "Custom":
        t = build_custom(CUSTOM_ACC, CUSTOM_BG)
        THEME = "Custom"
    else:
        t = THEMES.get(name) or THEMES["Havoc"]
        THEME = name if name in THEMES else "Havoc"
    CUR_ACC = tuple(t["acc"])
    CUR_ALT = tuple(t.get("alt", t["acc"]))
    if layout == "Midnight" and THEME == "Havoc":
        t = {**t, **midnight.PALETTE}
    t = appearance.palette(t, overrides)
    ART_PALETTE = (tuple(t["acc"]), tuple(t["acc_hi"]), tuple(t["alt"]))
    BG      = rgb(*t["bg"])
    PANEL   = rgb(*t["panel"])
    CARD    = rgb(*t["card"])
    CARD2   = rgb(*t["card2"])
    EDGE    = rgb(*t["edge"])
    TEXT    = rgb(*t["text"])
    MUTED   = rgb(*t["muted"])
    FAINT   = rgb(*t["faint"])
    PINK    = rgb(*t["acc"])
    PINK_HI = rgb(*t["acc_hi"])
    PURPLE  = rgb(*t["alt"])
    ON      = rgb(*t["acc"])
    OFFCOL  = rgb(*t["edge"])
    GRAD_TOP = rgb(*t["grad"][0])
    GRAD_BOT = rgb(*t["grad"][1])
    P1 = t["p1"]
    P2 = t["p2"]
    FALL = t["fall"]
    STYLE = t.get("style", "orb")
    return t

def safe_float(v, default=0.0):
    """Coerce anything to a float without ever raising.

    A preset written by another build can hold a string, None, or a bool where
    a slider expects a number. float() would raise inside the render frame and
    take the whole window down, so every slider path goes through this.
    """
    try:
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        f = float(v)
        return f if f == f else float(default)      # reject NaN
    except (TypeError, ValueError):
        try:
            return float(default)
        except (TypeError, ValueError):
            return 0.0

_PARTICLE_BOUNDS = {
    "matrix": (-math.inf, 1.12, -0.14),
    "snow": (-math.inf, 1.08, -0.06),
    "wave": (-math.inf, 1.08, -0.05),
    "ember": (-0.08, math.inf, 1.06),
    "dust": (-0.05, math.inf, 1.05),
}

@contextmanager
def _font(size, face=None):
    imgui.push_font(face, size)
    try:
        yield
    finally:
        imgui.pop_font()

def _wrapped_tip(text):
    if imgui.begin_tooltip():
        width = max(1, min(380, imgui.get_main_viewport().size.x - 42))
        imgui.push_text_wrap_pos(imgui.get_cursor_pos_x() + width)
        imgui.text_unformatted(text)
        imgui.pop_text_wrap_pos()
        imgui.end_tooltip()

def _pixel_border(dl, p, q, ink, *, accented=False, thickness=1.0):
    """Pixel-aligned, stepped corners that follow the typeface's square grid."""
    x, y = round(p.x) + 0.5, round(p.y) + 0.5
    r, b = round(q.x) - 0.5, round(q.y) - 0.5
    if r - x < 8 or b - y < 8:
        return
    step = 3 if accented else 2
    outline = (
        (x + step, y), (r - step, y), (r - step, y + step), (r, y + step),
        (r, b - step), (r - step, b - step), (r - step, b), (x + step, b),
        (x + step, b - step), (x, b - step), (x, y + step), (x + step, y + step),
    )
    dl.add_polyline([ImVec2(*point) for point in outline], imgui.get_color_u32(ink),
                    thickness=thickness, flags=imgui.ImDrawFlags_.closed)
    if accented:
        # Opposing inset ticks keep large frames legible in both dark and light themes.
        color = imgui.get_color_u32(_blend(ink, PINK, 0.58))
        length = min(23, (r - x) / 4)
        dl.add_line(ImVec2(x + step + 2, y + 2), ImVec2(x + length, y + 2), color, 1)
        dl.add_line(ImVec2(r - length, b - 2), ImVec2(r - step - 2, b - 2), color, 1)

def _initial_release(info):
    return isinstance(info, dict) and str(info.get("version", "")).strip().lower().lstrip("v") in ("1", "1.0", "1.0.0")

def _page_label(page):
    return page if page == "Credits" else nav.section_label(page)

def _menu_groups(schema):
    """Keep all installed collections reachable alongside the desktop pages."""
    collections = nav.navigation_groups(schema)
    pages = set(nav.VIRTUAL_PAGES)
    for _, group in collections:
        pages.update(group)
    workspace = [p for p in ("Dashboard", "Connection") if p in pages]
    settings = ["Appearance", "Credits"] if "Appearance" in pages else ["Credits"]
    pinned = set(workspace + settings)
    library = [p for p in nav.VIRTUAL_PAGES if p not in pinned]
    pinned.update(library)
    groups = [("pinned", "Workspace", workspace), ("pinned", "Library", library)]
    groups.extend(("collection", title, [p for p in group if p not in pinned])
                  for title, group in collections)
    groups.append(("pinned", "Panel", settings))
    return [group for group in groups if group[2]]


class DailyMessage:
    def __init__(self, path):
        self.path = path
        self.text = self._text(read_object(path)) or DEFAULT_DAILY_MESSAGE
        self.next_check = 0
        self.pending = None

    @staticmethod
    def _text(record):
        text = record.get("message") if isinstance(record, dict) else None
        if isinstance(text, str) and 0 < len(text) <= 120 and text.isprintable():
            return text.strip()

    def poll(self):
        now = time.time()
        if self.pending is not None:
            try:
                message = self.pending.get_nowait()
            except queue.Empty:
                return
            self.pending = None
            self.next_check = now + 300
            if message:
                self.next_check = min(now + 900, (int(now) // 86400 + 1) * 86400)
                if self.text != message:
                    self.text = message
                    try:
                        write_object(self.path, {"message": message})
                    except OSError:
                        pass
            return
        if now < self.next_check:
            return
        channel = self.pending = queue.SimpleQueue()

        def fetch_message():
            try:
                raw = desktop_request(PAGES_ORIGIN + "/desktop/daily-message.json", 2048)
                message = self._text(json.loads(raw))
            except (DesktopServiceError, OSError, ValueError):
                message = None
            channel.put(message)

        try:
            threading.Thread(target=fetch_message, name="havoc-daily-message", daemon=True).start()
        except RuntimeError:
            self.pending = None
            self.next_check = now + 300


class Panel:
    default_layout = "Midnight"

    def __init__(self):
        cfg = self._load_cfg()
        self.msg, self.loglines = "Local workspace", []
        self.account = AccountSession()
        self.updater = DesktopUpdater(Path(__file__))
        self.daily = DailyMessage(ROOT / "daily-message.json")
        self.online = OnlineSession()
        self._online_open = self._share_online = False
        self.remember_account = cfg.get("remember_account") is True
        self.schema = [
            {
                "key": key,
                "name": name,
                "section": page,
                "value": default,
                "type": "number" if bounds else "bool",
                **({"min": bounds[0], "max": bounds[1]} if bounds else {}),
            }
            for key, name, page, default, bounds in CATALOG
        ]
        self._section_counts = {}
        for item in self.schema:
            page = item["section"]
            self._section_counts[page] = self._section_counts.get(page, 0) + 1
        self._nav_counts = self._section_counts | {"All Mods": len(self.schema)}
        self._counts_dirty = True
        self.mod_groups = organize_controls(self.schema)
        self._filter_scope, self._filter_opened = None, set()
        self.values = self._read_values(cfg.get("values"))
        self._state_due = None
        self.section, self.search = "Dashboard", ""
        self._category_index = False
        favorites = cfg.get("favorites")
        self.favorites = (
            list(dict.fromkeys(key for key in favorites if isinstance(key, str) and key in self.values))
            if isinstance(favorites, list)
            else []
        )
        self._preset_sel = self._preset_new = ""
        self.just_updated, self._show_logs = None, False
        self.changelog = {
            "title": "Havoc Midnight",
            "notes": "The daily message now appears in both Midnight and Classic, including on the sign-in screen.",
        }
        self.headset = HeadsetPanel(self)
        self._audio = MenuAudio(ASSET_ROOT)
        self._clips = None
        values, self.saved_style = appearance.load(ROOT, {"menu_layout": self.default_layout}, THEME_NAMES)
        self.preferences, self.styled, self._bar_anim = {}, False, {}
        self.appearance_tab, self.midnight_tab = "Colors", "Controls"
        self.style_choice, self.preview_cue = "Standard", 1
        self._visual_due, self._visual_save_error = None, False
        self._visual_legacy = {key: values[key] for key in appearance.LEGACY}
        self._visual_time = self._clock_last = None
        self._art_phase = 0.0
        self._apply_visual(values)
        self._section_at, self._last_cue_frame = -10.0, -1
        self._hover_id = self._mouse_down_id = self._quiet_hover = 0
        self._mouse_position = self._closing_at = None
        self._page_trail, self._signed_out_credits = [], False
        self._palette_query, self._palette_index = "", 0
        self._palette_requested = self._palette_visible = False
        self.particles = [self._spawn(True) for _ in range(36)]
        self._shooters, self._next_shoot = [], 0.0
        if self.remember_account:
            self.account.start()

    def _load_cfg(self):
        return read_object(ROOT / "workspace.json")

    def _save_display_settings(self, **changes):
        try:
            cfg = self._load_cfg() | changes
            cfg.pop("opened", None)
            write_object(ROOT / "workspace.json", cfg)
            return True
        except OSError as error:
            self.log(f"Could not save workspace settings: {error}")
            return False

    def _read_values(self, stored, current=None):
        stored = stored if isinstance(stored, dict) else {}
        values = {}
        for item in self.schema:
            key = item["key"]
            default = current.get(key, item["value"]) if current is not None else item["value"]
            value = stored.get(key, default)
            if item["type"] == "bool":
                value = value if isinstance(value, bool) else default
            elif type(value) in (int, float) and item["min"] <= value <= item["max"]:
                value = float(value)
            else:
                value = default
            values[key] = value
        return values

    def push(self, key, value):
        if not self.workspace_open:
            return
        self.values[key] = value
        if isinstance(value, bool):
            self._counts_dirty = True
        self._state_due = time.monotonic() + 0.35

    def _save_values(self):
        self._state_due = None if self._save_display_settings(values=self.values) else time.monotonic() + 2

    @property
    def workspace_open(self):
        return self.account.user is not None

    def _poll_account(self):
        if self.account.poll() and self.workspace_open:
            self._share_online = self._load_cfg().get("online_share_for") == self._online_pref_key()
            self._signed_out_credits = False
            self._show_logs = False
            self._save_display_settings(remember_account=self.remember_account)
            self._navigate("Connection")
            self.log("Signed in as " + self.account.user)

    def logout(self):
        self.online.close()
        self.online = OnlineSession()
        self._online_open = self._share_online = False
        self.headset.close()
        self._audio.stop_clip()
        self.account.clear()
        self.loglines.clear()
        self.remember_account = False
        self._save_display_settings(remember_account=False, online_share_for=None)
        self.section, self.search = "Connection", ""
        self._page_trail, self._recent_sections = [], []
        self._palette_query, self._palette_index = "", 0
        self._palette_requested = self._palette_visible = self._focus_global_search = False
        self._show_logs = self._signed_out_credits = False
        self._section_at = imgui.get_time()
        self._cue("back")
        self.log("Signed out")

    def _online_pref_key(self):
        identity = machine_ids()[0] + "|" + self.account.user
        return hashlib.sha256(identity.encode()).hexdigest()

    def _poll_services(self):
        self.daily.poll()
        self.updater.poll()
        if self.updater.phase == "installed":
            self._request_close()
        if self.workspace_open:
            viewing = self.section == "Dashboard" and self._online_open and not self._show_logs
            self.online.set_interest(self._share_online, viewing, watch=True)

    def _daily_notice(self, width):
        width = max(1, width)
        start = imgui.get_cursor_pos_x()
        label = "Daily message"
        gap = imgui.get_style().item_spacing.x
        imgui.begin_group()
        imgui.push_text_wrap_pos(start + width)
        imgui.text_colored(PINK, label)
        if imgui.calc_text_size(label).x + gap + imgui.calc_text_size(self.daily.text).x <= width:
            imgui.same_line(0, gap)
        imgui.text_unformatted(self.daily.text)
        imgui.pop_text_wrap_pos()
        imgui.end_group()
        p = imgui.get_cursor_screen_pos()
        imgui.get_window_draw_list().add_line(p, ImVec2(p.x + width, p.y), imgui.get_color_u32(EDGE))
        imgui.dummy(ImVec2(1, max(1, self.zoom)))

    def _footer_status(self, width):
        if width <= 1:
            return
        count = self.online.count
        label = f"{count:,} online" if count is not None else "Online —"
        z = self.zoom
        height = 32 * z
        label = self._fit_label(label, max(1, width - 19*z))
        badge = min(width, imgui.calc_text_size(label).x + 19*z)
        p = imgui.get_cursor_screen_pos()
        clicked = imgui.invisible_button("##online-count", ImVec2(badge, height), imgui.ButtonFlags_.enable_nav)
        dl, color = imgui.get_window_draw_list(), imgui.get_color_u32
        center = ImVec2(p.x + 6*z, p.y + height/2)
        ink = ImVec4(0.35, 0.87, 0.52, 1) if count is not None else FAINT
        dl.add_circle_filled(center, 3.5*z, color(ink), 16)
        y = center.y - imgui.get_font_size()/2
        dl.add_text(ImVec2(p.x + 16*z, y), color(TEXT), label)
        lines = str(self.msg).splitlines()
        message = lines[-1] if lines else ""
        room = width - badge - 16*z
        if room > 48*z and message:
            dl.add_text(ImVec2(p.x + badge + 10*z, y), color(MUTED), self._fit_label(message, room))
        if imgui.is_item_hovered() or imgui.is_item_focused():
            detail = "People sharing their presence in Havoc." if count is not None else (self.online.snapshot[0] or "Checking online status…")
            imgui.set_tooltip(detail + "\nOpen Who’s online" + ("\n" + message if message else ""))
        if clicked:
            self._navigate("Dashboard")
            self._online_open = self._reveal_online = True

    def _home_services(self):
        width = max(1, imgui.get_content_region_avail().x)
        half = max(1, (width - imgui.get_style().item_spacing.x) / 2)
        if self._button("Who's online", half, 30, primary=self._online_open):
            self._online_open = not self._online_open
        imgui.same_line()
        if self._button("Updates", half, 30):
            self._show_logs = True
        if getattr(self, "_reveal_online", False):
            imgui.set_scroll_here_y(0.03)
            self._reveal_online = False
        if not self._online_open:
            return
        imgui.spacing()
        self._section_caption("Online in Havoc")
        imgui.text_wrapped("Only signed-in people who choose to share appear here.")
        changed, share = imgui.checkbox("Show me online", self._share_online)
        if changed:
            self._share_online = share
            self._save_display_settings(online_share_for=self._online_pref_key() if share else None)
            self.online.set_interest(share, True, watch=True)
        status, names = self.online.snapshot
        if status:
            imgui.text_wrapped(status)
        if self.online.retry_available and self._button("Retry connection", min(width, 180*self.zoom), 30):
            self.online.retry_now()
        if names is not None:
            if not names:
                imgui.text_disabled("Nobody is sharing right now.")
            else:
                imgui.text_unformatted(f"{len(names)} online")
                line = imgui.get_text_line_height_with_spacing()
                imgui.begin_child("online-members", ImVec2(0, min(4, len(names))*line + 2*imgui.get_style().window_padding.y), True)
                clip = imgui.ListClipper()
                clip.begin(len(names))
                while clip.step():
                    for i in range(clip.display_start, clip.display_end):
                        imgui.text_unformatted(names[i])
                clip.end()
                imgui.end_child()
        imgui.spacing()

    def _update_controls(self):
        self._section_caption("Desktop updates")
        imgui.text_unformatted("Installed  " + DESKTOP_RELEASE)
        update = self.updater
        if update.message:
            imgui.text_wrapped(update.message)
        width = max(1, min(280 * self.zoom, imgui.get_content_region_avail().x))
        if update.phase == "offered" and update.offer is not None:
            if update.digest is None:
                imgui.text_wrapped("Open Havoc from a writable desktop file to install this release.")
            else:
                imgui.text_wrapped("Havoc will save your settings and restart.")
                if self._button("Install " + update.offer.version + " and restart", width, 34, primary=True):
                    update.start(install=True)
        elif update.pending is None and update.phase != "installed":
            if self._button("Check for updates", width, 34, primary=True):
                update.start()
        imgui.spacing()

    def _sign_in_form(self):
        self._section_caption("Account")
        with _font(29, FONT_BIG):
            imgui.text_unformatted("Sign in")
        imgui.text_wrapped("Copy your machine ID and run /verify in the Havoc Discord.")
        imgui.spacing()
        self._section_caption("Machine ID")
        w = max(1, imgui.get_content_region_avail().x)
        copy_width = min(72 * self.zoom, w * 0.3)
        imgui.set_next_item_width(max(1, w - copy_width - imgui.get_style().item_spacing.x))
        machine_id = machine_ids()[0]
        imgui.input_text("##machine-id", machine_id, imgui.InputTextFlags_.read_only)
        imgui.same_line()
        if self._button("Copy", copy_width, imgui.get_frame_height() / self.zoom):
            imgui.set_clipboard_text(machine_id)
            self._id_copied_until = imgui.get_time() + 2
        if imgui.get_time() < getattr(self, "_id_copied_until", -1):
            imgui.text_disabled("Machine ID copied")
        imgui.spacing()
        busy = self.account.pending is not None
        imgui.begin_disabled(busy)
        changed, self.remember_account = imgui.checkbox("Verify again on startup", self.remember_account)
        if changed and not self.remember_account:
            self._save_display_settings(remember_account=False)
        if self._button("Checking…" if busy else "Check verification", w, 36, primary=True):
            self.account.start()
        imgui.end_disabled()
        if busy:
            if self._button("Cancel", min(96 * self.zoom, w)):
                self.account.clear()
                self.remember_account = False
                self._save_display_settings(remember_account=False)
        elif self.account.error:
            imgui.text_wrapped(self.account.error)
        imgui.spacing()
        half = max(1, (w - imgui.get_style().item_spacing.x) / 2)
        if self._button("Release notes", min(half, 139 * self.zoom), 28):
            self._show_logs = True
        imgui.same_line()
        if self._button("Quit", min(half, 74 * self.zoom), 28):
            self._request_close()

    def _connection(self):
        if self.workspace_open:
            self.headset.draw(self, standalone=True)

    def _soundboard(self):
        self._page_heading("Library", "Soundboard", "Local playback")
        folder = APP_DIR / "sounds"
        rescan = imgui.button("Rescan")
        if self._clips is None or rescan:
            try:
                self._clips = sorted(
                    (f for f in folder.iterdir() if f.suffix.casefold() == ".wav" and f.is_file()),
                    key=lambda f: f.name.casefold(),
                )
            except FileNotFoundError:
                self._clips = []
            except OSError as error:
                self._clips = []
                self.log(f"Could not read the sounds folder: {error}")
        if self._clips:
            imgui.same_line()
            if imgui.button("Stop preview"):
                self._audio.stop_clip()
            if not self._audio.clip_backend:
                imgui.text_wrapped("Install pygame to preview WAV files on this computer.")
            elif self._audio.unavailable:
                imgui.text_wrapped("Local audio output unavailable.")
            imgui.begin_disabled(
                not self._audio.clip_backend or self._audio.unavailable or not self.preferences["volume"]
            )
            for path in self._clips:
                if self._index_row("##wav/" + path.name, path.stem, "Play", "power"):
                    self._audio.play_clip(path)
            imgui.end_disabled()
            if self._audio.clip_error:
                imgui.text_wrapped(self._audio.clip_error)
        else:
            imgui.text_wrapped(
                "Place WAV files in the sounds folder beside HavocMidnight.py, then select Rescan."
            )
        imgui.spacing()
        self._section_caption("Interface sounds")
        appearance.sound_preview(self)

    def _controls(self):
        if not self.workspace_open:
            return
        special = {
            "Connection": self._connection,
            "Dashboard": self._dashboard,
            "Appearance": self._appearance,
            "Credits": self._credits,
            "Soundboard": self._soundboard,
        }
        if self.section in special:
            special[self.section]()
            return
        if self.section == "All Mods":
            self._page_heading(
                "Library" if self._category_index else "Local editor",
                "Mod categories" if self._category_index else "All mods",
                None,
            )
            if imgui.button("All controls" if self._category_index else "Browse categories"):
                self._category_index = not self._category_index
                self.search = ""
            if self._category_index:
                self._categories()
                return
        else:
            self._page_heading("Local editor", _page_label(self.section), None)
        page_filter(self)
        scope = (self.section, self.search)
        if self._filter_scope != scope:
            self._filter_scope = scope
            self._filter_opened.clear()
        groups = visible_groups(self.mod_groups, self.values, self.section, self.search, self.favorites)
        if not groups:
            if self.search:
                imgui.text_wrapped("No controls match this filter.")
            elif self.section == "Favorites":
                imgui.text_wrapped("Bookmark a mod in the library to find it here.")
            elif self.section == "Enabled Mods":
                imgui.text_wrapped("Controls you enable in the desktop editor appear here.")
            else:
                imgui.text_wrapped("This page gets its live controls from your installed Havoc runtime.")
            if not self.search:
                self._related_pages()
            self._session_tools()
            return
        origins = {}
        for primary, options in groups:
            category = (primary or options[0])["section"]
            origins.setdefault(category, []).append((primary, options))
        for origin, related in origins.items():
            imgui.push_id("category/" + origin)
            if self.section in nav.VIRTUAL_PAGES and imgui.small_button(_page_label(origin) + "  >"):
                self._navigate(origin)
            if self.preferences["menu_layout"] == "Midnight":
                for wide, batch in groupby(related, key=lambda pair: len(pair[1]) > 1):
                    batch = list(batch)
                    if wide:
                        for primary, options in batch:
                            self._control_group(primary, options)
                    else:
                        anchor = batch[0][0] or batch[0][1][0]
                        imgui.push_id("grid/" + anchor["key"])
                        midnight.control_grid(self, batch)
                        imgui.pop_id()
            else:
                for primary, options in related:
                    self._control_group(primary, options)
            imgui.pop_id()
            imgui.spacing()
        self._session_tools()

    def _draw_field(self, item, available=True):
        imgui.begin_disabled(not available or item.get("available") is False)
        if item.get("options"):
            self._enum_card(item)
        elif item.get("type") == "number":
            self._bar(item["key"], item, self.values.get(item["key"], item["value"]))
        else:
            self._switch_card(item)
        imgui.end_disabled()

    def _control_group(self, primary, options):
        anchor = primary or options[0]
        key = anchor["key"]
        members = [primary, *options] if primary else options
        keys = [item["key"] for item in members]
        wide_group = primary is not None and len(options) > 1
        width = max(1, imgui.get_content_region_avail().x)
        compact = self.preferences["menu_layout"] == "Midnight"
        bookmark = min(32*self.zoom, width*.23) if compact else min(width*.4, imgui.calc_text_size("+ Save mod").x+18)
        imgui.push_id("group_" + key)
        table = width > bookmark + 72*self.zoom and imgui.begin_table(
            "edit", 2, imgui.TableFlags_.no_saved_settings | imgui.TableFlags_.borders_outer)
        if table:
            imgui.table_setup_column("Control", imgui.TableColumnFlags_.width_stretch)
            imgui.table_setup_column("Favorite", imgui.TableColumnFlags_.width_fixed, bookmark)
            imgui.table_next_column()
        for item in ([primary] if wide_group else members):
            self._draw_field(item, anchor.get("available") is not False)
        if table:
            imgui.table_next_column()
        self._bookmark(key, keys, not set(keys).isdisjoint(self.favorites), bookmark)
        if table:
            imgui.end_table()
        if wide_group:
            if self.search and key not in self._filter_opened:
                imgui.set_next_item_open(True)
                self._filter_opened.add(key)
            if imgui.collapsing_header(f"Settings ({len(options)})###mod-options"):
                split = width >= max(540*self.zoom, 34*imgui.get_font_size()) and imgui.begin_table(
                    "options", 2, imgui.TableFlags_.sizing_stretch_same | imgui.TableFlags_.no_saved_settings)
                for item in options:
                    if split:
                        imgui.table_next_column()
                    self._draw_field(item, anchor.get("available") is not False)
                if split:
                    imgui.end_table()
        imgui.pop_id()

    def _update_library_counts(self):
        if self._counts_dirty:
            self._nav_counts["Favorites"] = len(self.favorites)
            self._nav_counts["Enabled Mods"] = sum(
                self.values[item["key"]] for item in self.schema if item["type"] == "bool"
            )
            self._counts_dirty = False

    def _toggle_favorite(self, key, group_keys=()):
        if not self.workspace_open:
            return
        saved = set(self.favorites)
        related = set(group_keys) | {key}
        if saved.isdisjoint(related):
            saved.add(key)
        else:
            saved.difference_update(related)
        self.favorites = sorted(saved)
        self._counts_dirty = True
        self._save_display_settings(favorites=self.favorites)

    def _categories(self):
        self._update_library_counts()
        page_filter(self)
        words = self.search.casefold().split()
        matches = [
            (title, [p for p in pages if all(w in (title + " " + p).casefold() for w in words)])
            for title, pages in COLLECTIONS
            if title != "Workspace"
        ]
        matches = [(title, pages) for title, pages in matches if pages]
        if not matches:
            imgui.text_wrapped("No categories match this filter.")
            return
        columns = (
            2
            if imgui.get_content_region_avail().x >= max(595 * self.zoom, 38 * imgui.get_font_size())
            else 1
        )
        if imgui.begin_table("##category-index", columns, imgui.TableFlags_.sizing_stretch_same):
            for title, pages in matches:
                imgui.table_next_column()
                self._section_caption(title)
                for page in pages:
                    count = self._section_counts.get(page, 0)
                    detail = (
                        (str(count) + (" control" if count == 1 else " controls")) if count else "Runtime"
                    )
                    if page == "Soundboard":
                        detail = "Audio"
                    if self._index_row("##browse/" + page, page, detail, "library"):
                        self._navigate(page)
                imgui.spacing()
            imgui.end_table()

    def _related_pages(self):
        pages = next((pages for _, pages in COLLECTIONS if self.section in pages), ())
        nearby = [
            name
            for name in pages
            if name != self.section and any(row["section"] == name for row in self.schema)
        ]
        if nearby:
            self._section_caption("In this collection")
            for name in nearby:
                if self._index_row("##related/" + name, name, "", "library"):
                    self._navigate(name)

    def _session_tools(self):
        labels = LOCAL_PAGE_ACTIONS.get(self.section, ())
        if labels and imgui.collapsing_header(f"Installed tools ({len(labels)})"):
            imgui.text_wrapped("These controls are provided by the installed runtime.")
            for label in labels:
                imgui.bullet_text(label)

    def local_presets(self):
        folder = ROOT / "presets"
        try:
            return sorted((p.stem for p in folder.glob("*.json") if p.is_file()), key=str.casefold)
        except OSError as error:
            self.log(f"Could not read presets: {error}")
            return []

    @staticmethod
    def _preset_path(label):
        cleaned = "".join(c for c in label if c.isalnum() or c in "-_ ").strip()[:80]
        if not cleaned or cleaned.upper() in RESERVED_PRESETS:
            raise ValueError("Choose a different preset name.")
        return ROOT / "presets" / (cleaned + ".json")

    def save_local_preset(self, name):
        if not self.workspace_open:
            return
        try:
            path = self._preset_path(name)
            write_object(path, {"values": self.values})
            self._preset_sel = path.stem
            self.log(f"Saved {path.stem}")
        except (ValueError, OSError) as error:
            self.log(str(error))

    def load_local_preset(self, name):
        if not self.workspace_open:
            return
        try:
            stored = read_object(self._preset_path(name)).get("values")
            if not isinstance(stored, dict):
                raise ValueError("This preset could not be read.")
            self.values = self._read_values(stored, self.values)
            self._counts_dirty = True
            self._save_values()
            self.log(f"Loaded {name}")
        except (ValueError, OSError) as error:
            self.log(str(error))

    def delete_local_preset(self, name):
        if not self.workspace_open:
            return
        try:
            self._preset_path(name).unlink()
            self._preset_sel = ""
            self.log(f"Deleted {name}")
        except (ValueError, OSError) as error:
            self.log(str(error))

    def _reset_values(self):
        if not self.workspace_open:
            return
        self.values = self._read_values({})
        self._counts_dirty = True
        self._save_values()
        self.log("Local controls reset")

    def shutdown(self):
        self.online.close()
        if self.online.thread and self.online.thread.is_alive():
            self.online.thread.join(timeout=0.35)
        self.account.clear()
        self.headset.close()
        if self._state_due is not None:
            self._save_values()
        if self._visual_due is not None:
            self._flush_visual()
        if (
            self.ui_sounds
            and self.preferences["cue_close"]
            and getattr(self, "t0", None) is not None
            and self._closing_at is None
        ):
            self._audio.play("close")
        self._audio.close()

    def _cue(self, name):
        self._last_cue_frame = imgui.get_frame_count()
        if self.ui_sounds and self.preferences["cue_" + name]:
            self._audio.play(name)

    def _input_feedback(self):
        # Use ImGui's resolved item after all children and popups have drawn.
        ctx = imgui.get_current_context()
        item = ctx.hovered_id
        window = ctx.hovered_window
        if item == self._quiet_hover or ctx.hovered_id_is_disabled or (window and item == window.move_id):
            item = 0
        if item and imgui.get_mouse_cursor() == imgui.MouseCursor_.arrow:
            imgui.set_mouse_cursor(imgui.MouseCursor_.hand)
        position = tuple(imgui.get_io().mouse_pos)
        entered = item and item != self._hover_id and position != self._mouse_position
        self._hover_id, self._mouse_position = item, position
        if imgui.is_mouse_clicked(0):
            self._mouse_down_id = item
        clicked = False
        if imgui.is_mouse_released(0):
            clicked = item and item == self._mouse_down_id
            self._mouse_down_id = 0
        if self._closing_at is not None or self._last_cue_frame == imgui.get_frame_count():
            return
        keyboard = ctx.nav_activate_pressed_id
        key_down = keyboard and (imgui.is_key_pressed(imgui.Key.space, False) or
                                 imgui.is_key_pressed(imgui.Key.enter, False) or
                                 imgui.is_key_pressed(imgui.Key.keypad_enter, False))
        if clicked or (key_down and ctx.active_id == keyboard and not ctx.active_id_disabled_id):
            self._cue("click")
        elif entered and not imgui.is_mouse_down(0):
            self._cue("hover")

    def _animate(self, name, target, initial=None, speed=18.0):
        """Store paint state with its ImGui window and scoped widget ID."""
        key = imgui.get_id(name)
        storage = imgui.get_state_storage()
        target = float(target)
        if self.preferences["hover"] == "Off" and (name.startswith("hover/") or name.endswith("/hover")):
            target = current = 0.0
        speed *= self.preferences["speed"] / 100
        current = storage.get_float(key, target if initial is None else float(initial))
        if self.ambient_motion and abs(current - target) > 0.001:
            current += (target - current) * -math.expm1(-speed * imgui.get_io().delta_time)
        else:
            current = target
        storage.set_float(key, current)
        return current

    def _button(self, label, width, height=32, primary=False):
        pressed = imgui.invisible_button(label, ImVec2(max(1, width), height * self.zoom),
                                         imgui.ButtonFlags_.enable_nav)
        if not imgui.is_item_visible():
            return pressed
        hover = self._animate(label + "/hover", imgui.is_item_hovered(), 0)
        down = self._animate(label + "/down", imgui.is_item_active(), 0, 35)
        p, q = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        dl, color = imgui.get_window_draw_list(), imgui.get_color_u32
        ink = self._ink_on_accent() if primary else TEXT
        face = _blend(PINK, PINK_HI, hover) if primary else _blend(CARD, CARD2, hover)
        a = ImVec2(p.x, p.y + round(down * 2))
        b = ImVec2(q.x, q.y - 2 + round(down * 2))
        style = self.preferences["button"]
        rounding = imgui.get_style().frame_rounding
        if style == "Pixel":
            shadow = self.preferences["shadow"] / 100
            if shadow:
                dl.add_rect_filled(ImVec2(p.x + 2, p.y + 3), q, color(_tint(_blend(BG, EDGE, 0.25), shadow)), rounding)
        else:
            a, b = p, q
        if style == "Outline":
            face = _blend(PANEL, PINK if primary else CARD2, 0.10 + hover * 0.24)
            ink = PINK if primary else TEXT
        dl.add_rect_filled(a, b, color(face), rounding)
        edge = _blend(EDGE, PINK, hover * 0.84)
        border = PINK if primary and style == "Outline" else (face if primary else edge)
        self._border(dl, a, b, PINK_HI if imgui.is_item_focused() else border, hover=hover)
        caption = self._fit_label(label.split("##", 1)[0], q.x - p.x - 8)
        ts = imgui.calc_text_size(caption)
        dl.add_text(ImVec2(round((a.x + b.x - ts.x) / 2), round((a.y + b.y - ts.y) / 2)),
                    color(ink), caption)
        return pressed

    @staticmethod
    def _ink_on_accent():
        luma = PINK.x * 0.2126 + PINK.y * 0.7152 + PINK.z * 0.0722
        return rgb(27, 23, 32) if luma > 0.52 else rgb(249, 250, 252)

    def _poster(self, kicker, title, caption="", height=190, night=False, motif=None):
        if self.preferences["menu_layout"] == "Midnight":
            return midnight.poster(self, kicker, title, caption, height, night, motif)
        w = max(1, imgui.get_content_region_avail().x)
        p = imgui.get_cursor_screen_pos()
        pad = min(30, max(14, w * 0.046))
        size = (50 if w >= 560 else 36) if len(title) < 13 else (37 if w >= 580 else 25)
        copy_w = max(1, w * (0.53 if w >= 580 else 0.73) - pad)
        with _font(size, FONT_BIG):
            lines = imgui.calc_text_size(title, wrap_width=copy_w).y
        h = max(height * self.zoom, lines + pad * 2 + (52 if caption else 30) * self.zoom)
        imgui.dummy(ImVec2(w, h))
        if not imgui.is_item_visible():
            return
        q = ImVec2(p.x + w, p.y + h)
        dl, color = imgui.get_window_draw_list(), imgui.get_color_u32
        phase = self._art_phase
        if motif:
            draw_plate(dl, p, q, motif, ART_PALETTE, align=0.75, phase=phase)
        else:
            draw_landscape(dl, p, q, ART_PALETTE, phase, night)
        shade = rgb(23, 19, 41)
        left, right = color(_tint(shade, 0.88)), color(_tint(shade, 0))
        dl.add_rect_filled_multi_color(p, ImVec2(p.x + w * 0.78, q.y), left, right, right, left)
        self._border(dl, p, q, _blend(EDGE, PURPLE, 0.42), accented=True)
        y = p.y + (h - lines - (45 if caption else 23)) / 2
        with _font(13, FONT_BIG):
            dl.add_text(ImVec2(p.x + pad, y), color(rgb(255, 213, 155)), kicker.upper())
        with _font(size, FONT_BIG):
            dl.add_text(imgui.get_font(), imgui.get_font_size(), ImVec2(p.x + pad, y + 20),
                        color(rgb(255, 249, 232)), title, wrap_width=copy_w)
        if caption:
            with _font(15):
                dl.add_text(ImVec2(p.x + pad, y + 25 + lines), color(rgb(236, 227, 219)),
                            self._fit_label(caption, w - 2 * pad))

    def _banner(self, eyebrow, title, detail=None, detail_color=None, illustrated=True):
        if self.preferences["menu_layout"] == "Midnight":
            return midnight.heading(self, eyebrow, title, detail, detail_color)
        w = max(1, imgui.get_content_region_avail().x)
        wide = w >= 565
        art_w = min(240, w * 0.28) if wide and illustrated else 0
        if illustrated and 282 <= w < 565 and title == "Connection":
            art_w = min(110, w * 0.29)
        p = imgui.get_cursor_screen_pos()
        copy_w = max(1, w - art_w - (16 if wide else 2))
        size = 39 if wide else 31
        with _font(size, FONT_BIG):
            lines = imgui.calc_text_size(title, wrap_width=copy_w).y
        with _font(14):
            detail_h = imgui.calc_text_size(detail, wrap_width=copy_w).y if detail else 0
        h = max(96 if wide else 75, 33 + lines + detail_h)
        imgui.dummy(ImVec2(w, h))
        if not imgui.is_item_visible():
            return
        dl, color = imgui.get_window_draw_list(), imgui.get_color_u32
        if art_w:
            a, b = ImVec2(p.x + w - art_w, p.y + 3), ImVec2(p.x + w, p.y + h - 12)
            motif = "device" if title == "Connection" else "library"
            phase = self._art_phase
            draw_plate(dl, a, b, motif, ART_PALETTE, phase=phase)
            self._border(dl, a, b, EDGE)
        with _font(12, FONT_BIG):
            dl.add_text(ImVec2(p.x, p.y + 2), color(PINK), eyebrow.upper())
        with _font(size, FONT_BIG):
            dl.add_text(imgui.get_font(), imgui.get_font_size(), ImVec2(p.x, p.y + 18), color(TEXT), title, wrap_width=copy_w)
        if detail:
            with _font(14):
                dl.add_text(imgui.get_font(), imgui.get_font_size(), ImVec2(p.x, p.y + lines + 22),
                            color(detail_color if detail_color is not None else MUTED), detail, wrap_width=copy_w)
        dl.add_line(ImVec2(p.x, p.y + h - 1), ImVec2(p.x + w, p.y + h - 1), color(EDGE))
        dl.add_rect_filled(ImVec2(p.x, p.y + h - 3), ImVec2(p.x + min(44, w), p.y + h), color(PINK))

    def _credits(self):
        width = imgui.get_content_region_avail().x
        height = min(510 if width >= 640 else 350, max(237, imgui.get_content_region_avail().y - 8))
        self._poster("", CREDITS_TEXT, height=height, night=True)

    def _request_close(self):
        if self._closing_at is None:
            self._closing_at = imgui.get_time()
            self._cue("close")

    def set_theme(self, name):
        if name not in THEME_NAMES:
            name = "Havoc"
        self._apply_visual({**self.preferences, "theme": name, "custom_acc": tuple(CUSTOM_ACC),
                            "custom_bg": tuple(CUSTOM_BG)}, save_now=True)
        self.log("theme: %s" % name)

    def _apply_visual(self, values, *, save_now=False):
        global CUSTOM_ACC, CUSTOM_BG
        old = self.preferences
        self.preferences = values
        self.zoom = values["scale"] / 100
        self.ambient_motion, self.ui_sounds = values["ambient_motion"], values["ui_sounds"]
        self.blur, self.opacity = values["blur"], values["opacity"]
        CUSTOM_ACC, CUSTOM_BG = tuple(values["custom_acc"]), tuple(values["custom_bg"])
        palette_keys = ("theme", "custom_acc", "custom_bg", "colors", "menu_layout")
        if any(values[k] != old.get(k) for k in palette_keys):
            self.palette = apply_theme(values["theme"], values["colors"].get(values["theme"]), values["menu_layout"])
            self.styled = False
        style_keys = ("scale", "font_size", "spacing", "border", "rounding", "hover", "button", "blur")
        if any(values[k] != old.get(k) for k in style_keys):
            self.styled = False
        if values["volume"] != old.get("volume"):
            self._audio.set_volume(values["volume"])
        if old.get("ui_sounds") and not self.ui_sounds:
            self._audio.mute()
        if old:
            if self.blur != old["blur"] or (self.blur and values["acrylic_tint"] != old["acrylic_tint"]):
                self._apply_blur()
            if self.opacity != old["opacity"] or self.blur != old["blur"]:
                self._apply_opacity()
            self._visual_due = time.monotonic() + 0.20
            if save_now:
                self._flush_visual()

    def _set_visual(self, key, value):
        if self.preferences[key] != value:
            self._apply_visual({**self.preferences, key: value})

    def _set_tone(self, key, color):
        theme = self.preferences["theme"]
        if theme == "Custom" and key in ("acc", "bg"):
            self._set_visual("custom_" + key, color)
            return
        palettes = self.preferences["colors"]
        tones = {**palettes.get(theme, {}), key: color}
        values = {**self.preferences, "colors": {**palettes, theme: tones}}
        if key.startswith("grad_") and not values["gradient"]:
            values["gradient"] = 45
        self._apply_visual(values)

    def _clear_tones(self):
        values = self.preferences
        theme = values["theme"]
        colors = {name: tones for name, tones in values["colors"].items() if name != theme}
        if theme == "Custom":
            base = appearance.defaults()
            values = {**values, "custom_acc": base["custom_acc"], "custom_bg": base["custom_bg"]}
        self._apply_visual({**values, "colors": colors}, save_now=True)

    def _flush_visual(self):
        try:
            appearance.save(ROOT, self.preferences, self.saved_style)
        except OSError as error:
            if not self._visual_save_error:
                self.log("Could not save appearance: %s" % error)
            self._visual_save_error = True
            self._visual_due = time.monotonic() + 2
            return
        self._visual_save_error = False
        self._visual_due = None
        legacy = {key: self.preferences[key] for key in appearance.LEGACY}
        if legacy != self._visual_legacy:
            self._save_display_settings(**legacy)
            self._visual_legacy = legacy

    def _sidebar_width(self, width):
        base = min(256 * self.zoom, width * 0.235)
        return min(width * 0.38, base * self.preferences["sidebar_width"] / 256)

    def _border(self, dl, p, q, ink, *, accented=False, hover=0.0):
        thickness = self.preferences["border"] * self.zoom
        radius = self.preferences["rounding"] * self.zoom
        glow = self.preferences["glow"] / 100
        if self.preferences["hover"] == "Glow":
            glow = max(glow, hover * 0.85)
        if glow:
            for spread, alpha in ((3, 0.10), (1.5, 0.22)):
                dl.add_rect(ImVec2(p.x - spread, p.y - spread), ImVec2(q.x + spread, q.y + spread),
                            imgui.get_color_u32(_tint(PINK, glow * alpha)), rounding=radius + spread, thickness=2.0)
        if thickness <= 0:
            return
        if radius > 0:
            dl.add_rect(p, q, imgui.get_color_u32(ink), rounding=radius, thickness=thickness)
        else:
            _pixel_border(dl, p, q, ink, accented=accented, thickness=thickness)

    def log(self, m):
        self.msg = str(m)
        self.loglines.append(str(m))
        if len(self.loglines) > 300:
            del self.loglines[:100]
        print(m)

    def style(self):
        s = imgui.get_style()
        s.window_rounding = 4.0
        s.grab_rounding = 1.0
        s.tab_rounding = 0.0
        s.scrollbar_rounding = 1.0
        s.separator_text_border_size = 2.0
        zoom, prefs = self.zoom, self.preferences
        s.font_scale_main = zoom * prefs["font_size"] / 16
        spacing = zoom * prefs["spacing"] / 100
        s.frame_padding = ImVec2(10 * zoom, 7 * zoom)
        s.item_spacing = ImVec2(8 * spacing, 6 * spacing)
        s.item_inner_spacing = ImVec2(6 * spacing, 4 * spacing)
        s.window_padding = ImVec2(12 * zoom, 10 * zoom)
        s.cell_padding = ImVec2(9 * spacing, 5 * spacing)
        s.scrollbar_size, s.grab_min_size, s.indent_spacing = 9 * zoom, 12 * zoom, 14 * zoom
        s.frame_rounding = prefs["rounding"] * zoom
        s.child_rounding = max(2 * zoom, s.frame_rounding)
        s.popup_rounding = max(2 * zoom, s.frame_rounding)
        s.window_border_size = s.child_border_size = s.frame_border_size = prefs["border"] * zoom
        s.popup_border_size = s.tab_border_size = prefs["border"] * zoom
        C = imgui.Col_
        put = s.set_color_
        # Acrylic composites a translucent base over the native window.
        put(C.window_bg.value, _tint(BG, 0.55 if self.blur else 0.0))
        put(C.child_bg.value, PANEL)
        put(C.popup_bg.value, PANEL)
        put(C.text.value, TEXT)
        put(C.text_disabled.value, MUTED)
        put(C.nav_cursor.value, PINK)
        put(C.border.value, EDGE)
        put(C.table_border_strong.value, EDGE)
        put(C.table_border_light.value, _blend(PANEL, EDGE, 0.65))
        put(C.frame_bg.value, CARD)
        put(C.frame_bg_hovered.value, EDGE)
        put(C.frame_bg_active.value, EDGE)
        put(C.slider_grab.value, PINK)
        put(C.slider_grab_active.value, PINK)
        put(C.button.value, CARD)
        put(C.button_hovered.value, CARD2)
        put(C.button_active.value, EDGE)
        put(C.header.value, CARD2)
        put(C.header_hovered.value, CARD2)
        put(C.header_active.value, EDGE)
        put(C.check_mark.value, PINK)
        put(C.scrollbar_bg.value, BG)
        put(C.scrollbar_grab.value, EDGE)
        put(C.scrollbar_grab_hovered.value, PURPLE)
        put(C.separator.value, EDGE)
        put(C.title_bg.value, PANEL)
        put(C.title_bg_active.value, PANEL)
        if prefs["button"] == "Outline":
            put(C.button.value, PANEL)
        if prefs["hover"] == "Off":
            put(C.button_hovered.value, s.color_(C.button))
            put(C.frame_bg_hovered.value, CARD)
            put(C.header_hovered.value, CARD2)
        elif prefs["hover"] == "Glow":
            put(C.button_hovered.value, _blend(CARD2, PINK, 0.24))
            put(C.frame_bg_hovered.value, _blend(CARD2, PINK, 0.24))

    def _apply_opacity(self):
        # layered-window alpha: below 100% the desktop shows through
        if not CUSTOM_FRAME:
            return
        try:
            import ctypes
            hwnd = self._hwnd()
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            LWA_ALPHA = 0x02
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            op = 100.0 if self.blur else self.opacity
            if op >= 100.0:
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_LAYERED)
            else:
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
                user32.SetLayeredWindowAttributes(hwnd, 0, int(op * 255 / 100), LWA_ALPHA)
        except Exception:
            pass

    def _apply_blur(self):
        # flicker-free acrylic: per-pixel alpha compositing via
        # DwmExtendFrameIntoClientArea (same thing GLFW's transparent
        # framebuffer does) + accent blur behind. No color-key involved.
        if not CUSTOM_FRAME:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = self._hwnd()
            if not hwnd:
                return

            class _MARGINS(ctypes.Structure):
                _fields_ = [("cxLeftWidth", ctypes.c_int),
                            ("cxRightWidth", ctypes.c_int),
                            ("cyTopHeight", ctypes.c_int),
                            ("cyBottomHeight", ctypes.c_int)]

            class _AccentPolicy(ctypes.Structure):
                _fields_ = [("AccentState", ctypes.c_int),
                            ("AccentFlags", ctypes.c_int),
                            ("GradientColor", ctypes.c_uint),
                            ("AnimationId", ctypes.c_int)]

            class _AttrData(ctypes.Structure):
                _fields_ = [("version", ctypes.c_int),
                            ("data", ctypes.c_void_p),
                            ("sizeOfData", ctypes.c_size_t)]

            def set_accent(state, gradient):
                acc = _AccentPolicy()
                acc.AccentState = state
                acc.AccentFlags = 2
                acc.GradientColor = gradient
                d = _AttrData()
                d.version = 1
                d.data = ctypes.cast(ctypes.pointer(acc), ctypes.c_void_p)
                d.sizeOfData = ctypes.sizeof(acc)
                user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(d))

            if self.blur:
                # -1 margins = glass sheet covers the whole client area
                ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                    hwnd, ctypes.byref(_MARGINS(-1, -1, -1, -1)))
                set_accent(4, round(255 * self.preferences["acrylic_tint"] / 100) << 24)
            else:
                set_accent(0, 0)
                ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                    hwnd, ctypes.byref(_MARGINS(0, 0, 0, 0)))
        except Exception:
            pass

    def _key_screen(self):
        avail = imgui.get_content_region_avail()
        wide = avail.x >= max(550*self.zoom, 36*imgui.get_font_size())
        if wide:
            h = min(420, max(330, avail.y * 0.68))
            start = imgui.get_cursor_pos()
            imgui.set_cursor_pos_y(start.y + max(0, (avail.y - h) * 0.45))
            flags = imgui.TableFlags_.sizing_stretch_prop | imgui.TableFlags_.no_saved_settings
            if imgui.begin_table("sign-in-spread", 2, flags):
                imgui.table_setup_column("Cover", imgui.TableColumnFlags_.width_stretch, 1.15)
                imgui.table_setup_column("Account", imgui.TableColumnFlags_.width_stretch, 0.85)
                imgui.table_next_column()
                self._poster("Desktop panel", "Havoc", height=h)
                imgui.table_next_column()
                imgui.indent(15)
                self._sign_in_form()
                imgui.unindent(15)
                imgui.end_table()
        else:
            self._poster("Desktop panel", "Havoc", height=142)
            imgui.dummy(ImVec2(1, 9))
            self._sign_in_form()

    def _round_window(self):
        if not CUSTOM_FRAME:
            return
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = self._hwnd()
            if not hwnd:
                return
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2
            pref = ctypes.c_int(DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
                ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass   # older windows, or no dwm - just square corners

    def _navigate(self, section, query="", feedback=True):
        if not self.workspace_open:
            return
        self._category_index = False
        if section != self.section:
            self._section_at = imgui.get_time()
            self._expanded_group = next((name for name, pages in nav.navigation_groups(self.schema)
                                         if section in pages), None)
            trail = self._page_trail
            if not trail or trail[-1] != self.section:
                trail[:] = [self.section]
            returning = section in trail
            if returning:
                del trail[trail.index(section) + 1:]
            else:
                trail.append(section)
            if feedback:
                self._cue("back" if returning else "click")
        self.section = section
        self.search = query
        recent = getattr(self, "_recent_sections", [])
        self._recent_sections = [section] + [s for s in recent if s != section][:4]

    def _navigation_search(self, width):
        if not self.workspace_open:
            return
        if getattr(self, "_focus_global_search", False):
            imgui.set_keyboard_focus_here()
            self._focus_global_search = False
        action_w = 72
        imgui.set_next_item_width(max(1, width - action_w - 6))
        changed, query = imgui.input_text_with_hint("##globalmodsearch", "Search mods  ·  Ctrl+F", self.search)
        if changed:
            self._navigate("All Mods", query, feedback=False)
        imgui.same_line(0, 6)
        if self._button("Clear" if self.search else "Ctrl+K", action_w, imgui.get_frame_height()):
            if self.search:
                self.search = ""
            else:
                self._palette_requested = True
        if imgui.is_item_hovered() and not self.search:
            imgui.set_tooltip("Find a page or control")

    def _launcher_results(self, query):
        words = query.lower().split()
        pages = dict.fromkeys(p for _, _, group in _menu_groups(self.schema) for p in group)
        results = [(_page_label(s), s, "") for s in pages
                   if all(word in (_page_label(s) + " " + s).lower() for word in words)]
        if words:
            for item in nav.matching_items(self.schema, self.values, "All Mods", query):
                name = item.get("name") or pretty_key(item["key"])
                results.append((name, nav.section_for_item(item), item["key"]))
        return results

    def _command_palette(self):
        if not self.workspace_open:
            return
        requested = self._palette_requested
        if requested:
            self._palette_requested = False
            self._palette_query = ""
            self._palette_index = 0
            imgui.open_popup("Find anything")
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(ImVec2(vp.pos.x + vp.size.x * 0.5, vp.pos.y + vp.size.y * 0.42),
                                  imgui.Cond_.appearing, ImVec2(0.5, 0.5))
        imgui.set_next_window_size(ImVec2(min(620, max(280, vp.size.x - 40)),
                                        min(540, max(250, vp.size.y - 60))), imgui.Cond_.always)
        visible, opened = imgui.begin_popup_modal("Find anything", True,
                                                 imgui.WindowFlags_.no_resize)
        if self._palette_visible and not opened:
            self._cue("back")
        self._palette_visible = bool(visible and opened)
        if not visible:
            return
        if imgui.is_key_pressed(imgui.Key.escape):
            self._cue("back")
            imgui.close_current_popup()
            self._palette_visible = False
            imgui.end_popup()
            return
        imgui.text_colored(MUTED, "Jump to a page or find a control across your workspace.")
        imgui.spacing()
        if requested:
            imgui.set_keyboard_focus_here()
        imgui.set_next_item_width(-1)
        previous = self._palette_query
        enter, self._palette_query = imgui.input_text_with_hint(
            "##launcherquery", "Search pages and controls...", previous,
            imgui.InputTextFlags_.enter_returns_true)
        if previous != self._palette_query:
            self._palette_index = 0
        results = self._launcher_results(self._palette_query)
        index = min(self._palette_index, max(0, len(results) - 1))
        moved = False
        if results:
            if imgui.is_key_pressed(imgui.Key.down_arrow):
                index = (index + 1) % len(results)
                moved = True
            if imgui.is_key_pressed(imgui.Key.up_arrow):
                index = (index - 1) % len(results)
                moved = True
        self._palette_index = index
        imgui.spacing()
        imgui.text_colored(FAINT, "%d RESULTS" % len(results))
        imgui.begin_child("launcherresults", ImVec2(0, -34), False)
        chosen = results[index] if enter and results else None
        if not results:
            imgui.spacing()
            imgui.text_colored(TEXT, "No matches yet")
            imgui.text_wrapped("Try a page name or a shorter control name.")
        for row, result in enumerate(results):
            name, section, key = result
            p = imgui.get_cursor_screen_pos()
            clicked, _ = imgui.selectable("##result%d" % row, row == index, 0, ImVec2(0, 46))
            dl = imgui.get_window_draw_list()
            dl.add_text(ImVec2(p.x + 10, p.y + 4), imgui.get_color_u32(TEXT), name)
            dl.add_text(ImVec2(p.x + 10, p.y + 25), imgui.get_color_u32(MUTED),
                        "Control / " + nav.section_label(section) if key else "Page")
            if clicked:
                chosen = result
            if moved and row == index:
                imgui.set_scroll_here_y()
        imgui.end_child()
        imgui.separator()
        imgui.text_colored(MUTED, "Up / Down to choose    Enter to open    Esc to dismiss")
        if chosen is not None:
            self._navigate(chosen[1], chosen[2])
            imgui.close_current_popup()
            self._palette_visible = False
        imgui.end_popup()

    def gui(self):
        self._poll_account()
        self._poll_services()
        if self.workspace_open:
            self.headset.update(self)
        now = imgui.get_time()
        if self._clock_last is None:
            self._visual_time = now
        else:
            self._visual_time += (now - self._clock_last) * self.preferences["speed"] / 100
        self._clock_last = now
        self._art_phase = self._visual_time * 0.28 if self.ambient_motion and self.preferences["background_motion"] else 0.0
        if not self.styled:
            self.style()
            self.styled = True
            if not hasattr(self, "_rounded_at"):
                self._rounded_at = now
        self._quiet_hover = 0
        closing_on_entry = self._closing_at is not None
        if closing_on_entry:
            imgui.begin_disabled()
        try:
            self._draw_frame(now)
        finally:
            if closing_on_entry:
                imgui.end_disabled()
        self._input_feedback()
        self._fade_overlay(now)
        if self._visual_due is not None and time.monotonic() >= self._visual_due:
            self._flush_visual()
        if self._state_due is not None and time.monotonic() >= self._state_due:
            self._save_values()

    def _draw_frame(self, now):
        if getattr(self, "t0", None) is None:
            self._intro_span = 0.42 * 100 / self.preferences["speed"]
            self.t0 = now + (self._intro_span if self.ambient_motion else 0)
            self._cue("open")
        if now < self.t0:
            self._start_logo(now)
            return
        if self.just_updated and _initial_release(self.just_updated):
            self.just_updated = None
        if (self.just_updated and now < self.t0 + 5.0) or self._show_logs:
            self._updated_screen(update_mode=not self._show_logs)
            if imgui.is_key_pressed(imgui.Key.escape):
                self._cue("back")
                self.just_updated = None
                self._show_logs = False
            return
        if getattr(self, "_rounded_at", None) is not None and now - self._rounded_at > 0.5:
            self._round_window()
            self._apply_opacity()
            if self.blur:
                self._apply_blur()
            self._rounded_at = None
        if self.workspace_open and imgui.get_io().key_ctrl and imgui.is_key_pressed(imgui.Key.k):
            self._palette_requested = True
        if self.workspace_open and imgui.get_io().key_ctrl and imgui.is_key_pressed(imgui.Key.f):
            self._focus_global_search = True
        if imgui.is_key_pressed(imgui.Key.escape) and not self._palette_visible:
            self.search = ""
        if not getattr(self, "_native_resize_done", False):
            self._boot_frames = getattr(self, "_boot_frames", 0) + 1
            if self._boot_frames > 8:
                self._enable_native_resize()
        self._resize_grip()
        if self.preferences["menu_layout"] == "Midnight":
            midnight.workspace(self, now)
            return
        self._backdrop()
        self._titlebar()
        self._daily_notice(imgui.get_content_region_avail().x)
        if self.workspace_open:
            dock_h = 51 if imgui.get_content_region_avail().x < 620 else 45
            body_h = max(1, imgui.get_content_region_avail().y - (dock_h + 54) * self.zoom)
        else:
            body_h = max(1, imgui.get_content_region_avail().y)
        width = imgui.get_content_region_avail().x
        gutter = max(10, min(42, (width - 940) * 0.12 + 18)) if width >= 620 else 12
        flags = imgui.ChildFlags_.always_use_window_padding | imgui.ChildFlags_.borders
        in_library = self.workspace_open and self.section not in ("Dashboard", "Connection", "Appearance", "Credits")
        gutter = max(3, (gutter + self.preferences["gutter"]) * self.zoom)
        nav_mode = self.preferences["sidebar"]
        sidebar = (in_library and nav_mode != "Page selectors" and
                   width >= (650 if nav_mode == "Wide sidebar" else 850) * self.zoom)
        if sidebar:
            imgui.push_style_color(imgui.Col_.child_bg, appearance.sidebar_color(self))
            imgui.begin_child("library-navigation", ImVec2(self._sidebar_width(width), body_h), flags)
            imgui.pop_style_color()
            self._library_navigation(compact=False)
            imgui.end_child()
            imgui.same_line(0, 10)
        imgui.push_style_var(imgui.StyleVar_.window_padding, ImVec2(gutter, 16 * self.zoom))
        imgui.push_style_color(imgui.Col_.child_bg, _tint(PANEL, (0.79 if self.blur else 0.98) * (1 - self.preferences["panel_transparency"] / 100)))
        imgui.begin_child("canvas", ImVec2(0, body_h), flags)
        imgui.pop_style_color()
        imgui.pop_style_var()
        page = self.section if self.workspace_open else ("public-credits" if self._signed_out_credits else "sign-in")
        p, size = imgui.get_window_pos(), imgui.get_window_size()
        q, dl = ImVec2(p.x + size.x, p.y + size.y), imgui.get_window_draw_list()
        strength = self.preferences["gradient"] / 100
        if strength:
            appearance.gradient(dl, p, q, _tint(GRAD_TOP, strength), _tint(GRAD_BOT, strength),
                                self.preferences["gradient_direction"])
        if (self.ambient_motion and self.preferences["background_motion"]) or self.preferences["softness"]:
            draw_ambience(dl, p, q, page, ART_PALETTE, self._art_phase, self.preferences["softness"])
        if page != getattr(self, "_drawn_section", None):
            imgui.set_scroll_y(0)
            self._drawn_section = page
        if self.workspace_open:
            transition = self.preferences["transition"]
            duration = self.preferences["duration"] / (10 * self.preferences["speed"])
            travel = _ease((now - self._section_at) / duration) if self.ambient_motion and transition != "Instant" else 1.0
            if travel < 1 and transition in ("Slide", "Slide + fade"):
                imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + round(5 * (1 - travel)))
            alpha = 0.58 + 0.42 * travel if transition in ("Fade", "Slide + fade") else 1.0
            imgui.push_style_var(imgui.StyleVar_.alpha, imgui.get_style().alpha * alpha)
            if in_library and not sidebar:
                self._library_navigation(compact=True)
            imgui.push_id(self.section)
            self._controls()
            imgui.pop_id()
            imgui.pop_style_var()
        elif self._signed_out_credits:
            self._credits()
        else:
            self._key_screen()
        imgui.end_child()
        if self.workspace_open:
            self._footer()
            self._dock()
            self._command_palette()

    def _start_logo(self, now):
        dl, vp = imgui.get_foreground_draw_list(), imgui.get_main_viewport()
        color = imgui.get_color_u32
        cx, cy = vp.pos.x + vp.size.x / 2, vp.pos.y + vp.size.y / 2
        progress = _ease(1 - (self.t0 - now) / self._intro_span)
        if self.preferences["menu_layout"] == "Midnight":
            midnight.opening_backdrop(self, dl, vp)
        else:
            dl.add_rect_filled(vp.pos, ImVec2(vp.pos.x + vp.size.x, vp.pos.y + vp.size.y), color(BG), 12)
        draw_opening_orbits(dl, cx, cy - 14, min(198, vp.size.x * 0.30, vp.size.y * 0.36), progress, ART_PALETTE)
        draw_icon(dl, "brand", cx - 24, cy - 47 + 5 * (1 - progress), 48, PINK)
        with _font(28, FONT_BIG):
            size = imgui.calc_text_size("Havoc")
            dl.add_text(ImVec2(cx - size.x / 2, cy + 12), color(TEXT), "Havoc")
        dl.add_rect_filled(ImVec2(cx - 32, cy + 59), ImVec2(cx + 32, cy + 61), color(EDGE), 1)
        dl.add_rect_filled(ImVec2(cx - 32, cy + 59), ImVec2(cx - 32 + 64 * progress, cy + 61),
                           color(PINK), 1)

    def _updated_screen(self, update_mode=True):
        if self.preferences["menu_layout"] == "Midnight":
            midnight.workspace(self, imgui.get_time(), notice=update_mode)
            return
        self._backdrop()
        self._daily_notice(imgui.get_content_region_avail().x)
        avail = imgui.get_content_region_avail()
        w = min(610, max(1, avail.x))
        h = min(530, max(1, avail.y))
        p = imgui.get_cursor_pos()
        imgui.set_cursor_pos(ImVec2(p.x + (avail.x - w) / 2, p.y + (avail.y - h) / 2))
        imgui.begin_child("updates", ImVec2(w, h), True)
        self._release_contents(update_mode)
        imgui.end_child()

    def _release_contents(self, update_mode):
        self._banner("Updates", "Havoc updated" if update_mode else "Release notes")
        release = (self.just_updated if update_mode else self.changelog) or {}
        notes = "" if _initial_release(release) else str(release.get("notes") or "").strip()
        imgui.begin_child("release-notes", ImVec2(0, -39), False)
        self._update_controls()
        if notes:
            self._section_caption("Latest release")
            imgui.text_wrapped(notes)
        else:
            imgui.text_colored(MUTED, "No release notes to display.")
        imgui.end_child()
        if self._button("Continue", min(136, imgui.get_content_region_avail().x), primary=True):
            self._cue("back")
            self.just_updated = None
            self._show_logs = False

    def _fade_overlay(self, now):
        speed = self.preferences["speed"] / 100
        if self._closing_at is not None:
            amount = _ease((now - self._closing_at) * speed / 0.16) if self.ambient_motion else 1.0
            if amount >= 1.0:
                hello_imgui.get_runner_params().app_shall_exit = True
        elif self.ambient_motion and 0 <= (now - self.t0) * speed < 0.20:
            amount = 1 - _ease((now - self.t0) * speed / 0.20)
        else:
            return
        vp = imgui.get_main_viewport()
        imgui.get_foreground_draw_list().add_rect_filled(
            vp.pos, ImVec2(vp.pos.x + vp.size.x, vp.pos.y + vp.size.y),
            imgui.get_color_u32(_tint(BG, amount)), 12)

    def _spawn(self, anywhere=False):
        return {
            "x": random.random(),
            "y": random.random() if anywhere else 1.06,
            "r": random.uniform(1.4, 4.2),
            "sp": random.uniform(0.012, 0.055),      # upward speed
            "dr": random.uniform(-0.020, 0.020),     # sideways drift
            "ph": random.uniform(0, 6.28),
            "a": random.uniform(0.28, 0.85),
        }

    def _backdrop(self):
        if self.blur:
            return          # blur mode: the acrylic layer replaces the backdrop
        dl = imgui.get_background_draw_list()
        vp = imgui.get_main_viewport()
        x0, y0 = vp.pos.x, vp.pos.y
        w, h = vp.size.x, vp.size.y
        x1, y1 = x0 + w, y0 + h
        t = self._visual_time
        dt = min(0.05, imgui.get_io().delta_time) * self.preferences["speed"] / 100
        gb = imgui.get_color_u32(GRAD_BOT)
        R = 22.0
        # Keep the gradient inside the transparent window's rounded base.
        dl.add_rect_filled(ImVec2(x0, y0), ImVec2(x1, y1), gb, R)
        appearance.gradient(dl, ImVec2(x0, y0 + R), ImVec2(x1, y1 - R), GRAD_TOP, GRAD_BOT,
                            self.preferences["gradient_direction"])
        if not self.ambient_motion or not self.preferences["background_motion"]:
            return
        for i in range(5):
            ox = x0 + w * (0.5 + 0.44 * math.sin(t * 0.11 + i * 2.1))
            oy = y0 + h * (0.5 + 0.42 * math.cos(t * 0.09 + i * 2.7))
            tint = rgb(*P1, 0.022) if i % 2 else _tint(PURPLE, 0.020)
            ink = imgui.get_color_u32(tint)
            for k in range(3):
                dl.add_circle_filled(ImVec2(ox, oy), 130 + k * 30, ink, 32)
        # edge vignette for depth
        ve = 60.0
        blk0 = imgui.get_color_u32(rgb(0, 0, 0, 0.0))
        blk1 = imgui.get_color_u32(rgb(0, 0, 0, 0.34))
        dl.add_rect_filled_multi_color(ImVec2(x0 + R, y0), ImVec2(x1 - R, y0 + ve), blk1, blk1, blk0, blk0)
        dl.add_rect_filled_multi_color(ImVec2(x0 + R, y1 - ve), ImVec2(x1 - R, y1), blk0, blk0, blk1, blk1)
        dl.add_rect_filled_multi_color(ImVec2(x0, y0 + R), ImVec2(x0 + ve, y1 - R), blk1, blk0, blk0, blk1)
        dl.add_rect_filled_multi_color(ImVec2(x1 - ve, y0 + R), ImVec2(x1, y1 - R), blk0, blk1, blk1, blk0)
        if STYLE == "orb":
            self._shooting_stars(dl, vp, t, dt)
        self._draw_particles(dl, vp, t, dt)

    def _shooting_stars(self, dl, vp, t, dt):
        x0, y0 = vp.pos
        w, h = vp.size
        if t >= self._next_shoot:
            self._next_shoot = t + random.uniform(3.5, 8.0)
            going_left = random.random() < 0.5
            self._shooters.append({
                "x": random.uniform(0.15, 0.85),
                "y": random.uniform(-0.05, 0.30),
                "vx": (-0.45 if going_left else 0.45) * (0.7 + random.random() * 0.6),
                "vy": 0.28 + random.random() * 0.25,
                "life": 0.9,
            })
        keep = []
        for sh in self._shooters:
            sh["x"] += sh["vx"] * dt
            sh["y"] += sh["vy"] * dt
            sh["life"] -= dt
            if sh["life"] <= 0 or not (-0.1 < sh["x"] < 1.1) or sh["y"] > 1.1:
                continue
            keep.append(sh)
            sx = x0 + sh["x"] * w
            sy = y0 + sh["y"] * h
            fade = max(0.15, min(1.0, sh["life"] / 0.9))
            dl.add_line(ImVec2(sx - sh["vx"] * w * 0.12, sy - sh["vy"] * h * 0.12),
                        ImVec2(sx, sy),
                        imgui.get_color_u32(rgb(*P2, 0.55 * fade)), 1.4)
            dl.add_circle_filled(ImVec2(sx, sy), 1.8,
                                 imgui.get_color_u32(rgb(255, 255, 255, 0.75 * fade)), 8)
        self._shooters = keep

    def _draw_particles(self, dl, vp, t, dt):
        x0, y0 = vp.pos
        w, h = vp.size
        x1, y1 = x0 + w, y0 + h
        sty = STYLE
        y_min, y_max, restart_y = _PARTICLE_BOUNDS.get(sty, (-math.inf, math.inf, 0))
        primary, secondary = rgb(*P1), rgb(*P2)
        pts = []

        def packed(ink, opacity):
            return imgui.get_color_u32(_tint(ink, opacity))

        if sty == "wave":
            gl = packed(PURPLE, 0.05)
            gy = y0 + h * 0.62
            while gy < y1:
                dl.add_line(ImVec2(x0, gy), ImVec2(x1, gy), gl, 1.0)
                gy += 34
            gx = x0
            while gx < x1:
                dl.add_line(ImVec2(gx, y0 + h * 0.62), ImVec2(gx, y1), gl, 1.0)
                gx += 56

        for idx, p in enumerate(self.particles):
            if sty == "matrix":
                p["y"] += (0.28 + p["sp"] * 6.0) * dt
            elif sty == "ember":
                p["y"] -= (0.05 + p["sp"] * 4.0) * dt
                p["x"] += math.sin(t * 1.3 + p["ph"]) * 0.0007
            elif sty == "snow":
                p["y"] += (0.012 + p["sp"] * 1.4) * dt
                p["x"] += math.sin(t * 0.8 + p["ph"]) * 0.0011
            elif sty == "wave":
                p["y"] += (0.008 + p["sp"] * 0.9) * dt
                p["x"] += p["dr"] * dt * 0.4
            elif sty == "dust":
                p["y"] -= p["sp"] * 0.15 * dt
            else:  # orb
                p["y"] -= p["sp"] * dt
                p["x"] += (p["dr"] + 0.010 * math.sin(t * 0.6 + p["ph"])) * dt

            if p["x"] < -0.05:
                p["x"] = 1.05
            elif p["x"] > 1.05:
                p["x"] = -0.05

            if p["y"] < y_min or p["y"] > y_max:
                p.update(self._spawn())
                p["y"] = restart_y
                continue
            px = x0 + p["x"] * w
            py = y0 + p["y"] * h

            if sty == "matrix":
                ln = 16 + p["r"] * 9
                tw = 0.65 + 0.35 * math.sin(t * 3 + p["ph"])
                a = p["a"] * tw
                dl.add_line(ImVec2(px, py - ln), ImVec2(px, py),
                            packed(primary, a * 0.30), max(1.0, p["r"] * 0.35))
                dl.add_circle_filled(ImVec2(px, py), max(1.2, p["r"] * 0.55), packed(secondary, a), 8)
            elif sty == "ember":
                af = p["a"] * (0.45 + 0.55 * abs(math.sin(t * 6 + p["ph"])))
                ln = p["r"] * 6
                dl.add_line(ImVec2(px, py + ln), ImVec2(px, py),
                            packed(primary, af * 0.30), max(1.0, p["r"] * 0.5))
                dl.add_circle_filled(ImVec2(px, py), max(1.0, p["r"] * 0.7), packed(secondary, af), 8)
            elif sty == "snow":
                dl.add_circle_filled(ImVec2(px, py), p["r"] * 3.0,
                                     packed(primary, p["a"] * 0.10), 12)
                dl.add_circle_filled(ImVec2(px, py), p["r"] * 0.9,
                                     packed(secondary, p["a"]), 10)
            elif sty == "wave":
                bw = w * (0.015 + (p["r"] / 4.2) * 0.05)
                stripe = primary if idx % 2 == 0 else PURPLE
                dl.add_rect_filled(ImVec2(px - bw * 0.5, py),
                                   ImVec2(px + bw * 0.5, py + 2),
                                   packed(stripe, p["a"] * 0.55), 1.0)
            elif sty == "dust":
                dl.add_circle_filled(ImVec2(px, py), p["r"] * 0.8,
                                     packed(MUTED, p["a"] * 0.22), 8)
            else:
                if p["y"] < -0.06:
                    p.update(self._spawn())
                twinkle = 0.65 + 0.35 * math.sin(t * 1.7 + p["ph"])
                a = p["a"] * twinkle
                pts.append((px, py))
                dl.add_circle_filled(ImVec2(px, py), p["r"] * 3.2,
                                     packed(primary, a * 0.14), 12)
                dl.add_circle_filled(ImVec2(px, py), p["r"],
                                     packed(secondary, a), 10)

        if sty == "orb" or (not FALL and sty not in ("matrix", "ember", "snow", "wave", "dust")):
            link = (w * 0.085) ** 2
            for i in range(0, len(pts), 2):
                xi, yi = pts[i]
                for j in range(i + 1, min(i + 14, len(pts))):
                    xj, yj = pts[j]
                    d2 = (xi - xj) ** 2 + (yi - yj) ** 2
                    if d2 < link:
                        fade = (1.0 - d2 / link) * 0.16
                        dl.add_line(ImVec2(xi, yi), ImVec2(xj, yj),
                                    packed(secondary, fade), 1.0)

    def _titlebar(self):
        dl, color = imgui.get_window_draw_list(), imgui.get_color_u32
        p, w = imgui.get_window_pos(), imgui.get_window_width()
        x, y, h = p.x, p.y, 50 * self.zoom
        pad = 22 if w >= 600 else 12
        dl.add_rect_filled(p, ImVec2(x + w, y + h), color(PANEL))
        dl.add_line(ImVec2(x, y + h - 1), ImVec2(x + w, y + h - 1), color(EDGE))
        draw_icon(dl, "brand", x + pad, y + 13 * self.zoom, 24, PINK)
        with _font(23, FONT_BIG):
            dl.add_text(ImVec2(x + pad + 35, y + 11 * self.zoom), color(TEXT), "HAVOC")
        imgui.set_cursor_pos(ImVec2(0, 0))
        drag_w = (w * 0.31 if self.workspace_open and w >= 700 * self.zoom else w - (180 if not self.workspace_open else 92))
        imgui.invisible_button("##titledrag", ImVec2(max(1, drag_w), h))
        if imgui.is_item_hovered():
            self._quiet_hover = imgui.get_item_id()
        if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
            self._toggle_maximise()
        elif imgui.is_item_clicked(0):
            self._native_drag()
        integrated = self.workspace_open and w >= 700 * self.zoom
        if integrated:
            imgui.set_cursor_pos(ImVec2(drag_w, 10))
            self._navigation_search(min(420, w * 0.40))
        if w >= 975 * self.zoom:
            status = "Verified" if self.workspace_open else "Signed out"
            start = x + w - (259 if self.workspace_open else 341) * self.zoom
            ink = MUTED
            dl.add_rect_filled(ImVec2(start, y + 21 * self.zoom), ImVec2(start + 6, y + 27 * self.zoom), color(ink))
            with _font(13):
                dl.add_text(ImVec2(start + 12, y + 8 * self.zoom), color(TEXT), status)
                account = self.account.user or THEME
                dl.add_text(ImVec2(start + 12, y + 26 * self.zoom), color(MUTED),
                            self._fit_label("%s / %.0f FPS" % (account, imgui.get_io().framerate), 132))
        if not self.workspace_open:
            imgui.set_cursor_pos(ImVec2(max(1, w - 174 * self.zoom), 9))
            if self._button("Sign in" if self._signed_out_credits else "Credits", 78 * self.zoom):
                self._signed_out_credits = not self._signed_out_credits
                self._cue("click" if self._signed_out_credits else "back")
        imgui.set_cursor_pos(ImVec2(max(1, w - 86 * self.zoom), 9))
        if CUSTOM_FRAME:
            if self._button("−##minimize", 32 * self.zoom):
                self.minimize()
            if imgui.is_item_hovered():
                imgui.set_tooltip("Minimize")
            imgui.same_line(0, 4)
        if self._button("×##close", 32 * self.zoom):
            self._request_close()
        if imgui.is_item_hovered():
            imgui.set_tooltip("Close")
        imgui.set_cursor_pos(ImVec2(imgui.get_style().window_padding.x, h + 10 * self.zoom))
        if self.workspace_open and not integrated:
            self._navigation_search(imgui.get_content_region_avail().x)

    def _hwnd(self):
        """Our top-level window handle, by title first so it still works when
        the app is not the foreground window."""
        import ctypes
        u32 = ctypes.windll.user32
        u32.FindWindowW.restype = ctypes.c_void_p
        u32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        u32.GetActiveWindow.restype = ctypes.c_void_p
        u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        for handle in (u32.GetActiveWindow(), u32.FindWindowW(None, WINDOW_TITLE)):
            if handle:
                owner = ctypes.c_ulong()
                u32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
                if owner.value == os.getpid():
                    return handle
        return None

    def _enable_native_resize(self):
        """Give the borderless GLFW window native resize and maximize behavior."""
        if getattr(self, "_native_resize_done", False):
            return
        self._native_resize_done = True
        if not CUSTOM_FRAME:
            return
        try:
            import ctypes
            u32 = ctypes.windll.user32
            hwnd = self._hwnd()
            if not hwnd:
                return
            GWL_STYLE = -16
            WS_THICKFRAME = 0x00040000
            WS_MAXIMIZEBOX = 0x00010000
            SWP_NOMOVE, SWP_NOSIZE = 0x0002, 0x0001
            SWP_NOZORDER, SWP_FRAMECHANGED = 0x0004, 0x0020

            u32.GetWindowLongW.restype = ctypes.c_long
            u32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            u32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
            u32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, ctypes.c_uint]

            style = u32.GetWindowLongW(hwnd, GWL_STYLE)
            u32.SetWindowLongW(hwnd, GWL_STYLE,
                               style | WS_THICKFRAME | WS_MAXIMIZEBOX)
            self._kill_frame_border(hwnd)

            u32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
            self.log("window resizing enabled - drag any edge or corner")
        except Exception as e:
            self.log("could not enable native resizing: %s" % e)

    def _kill_frame_border(self, hwnd):
        """Handle WM_NCCALCSIZE to hide the frame while preserving native edge hit testing."""
        try:
            import ctypes
            u32 = ctypes.windll.user32
            GWLP_WNDPROC = -4
            WM_NCCALCSIZE = 0x0083

            LRESULT = ctypes.c_void_p
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_uint,
                                         ctypes.c_void_p, ctypes.c_void_p)

            setter = getattr(u32, "SetWindowLongPtrW", None) or u32.SetWindowLongW
            getter = getattr(u32, "GetWindowLongPtrW", None) or u32.GetWindowLongW
            setter.restype = LRESULT
            setter.argtypes = [ctypes.c_void_p, ctypes.c_int, WNDPROC]
            getter.restype = LRESULT
            getter.argtypes = [ctypes.c_void_p, ctypes.c_int]

            u32.CallWindowProcW.restype = LRESULT
            u32.CallWindowProcW.argtypes = [LRESULT, ctypes.c_void_p, ctypes.c_uint,
                                            ctypes.c_void_p, ctypes.c_void_p]

            old = getter(hwnd, GWLP_WNDPROC)

            def proc(h, msg, wp, lp):
                # wParam TRUE means "here is the proposed client rect" - return
                # 0 and Windows keeps it as-is, i.e. no frame is carved out.
                if msg == WM_NCCALCSIZE and wp:
                    return 0          # plain int: LRESULT(0) will not marshal back
                return u32.CallWindowProcW(old, h, msg, wp, lp)

            # Keep hard references alive: if either is collected the window
            # proc points at freed memory and the app dies on the next message.
            self._wndproc_ref = WNDPROC(proc)
            self._wndproc_old = old
            setter(hwnd, GWLP_WNDPROC, self._wndproc_ref)
        except Exception as e:
            self.log("could not hide the window frame: %s" % e)

    def _toggle_maximise(self):
        if not CUSTOM_FRAME:
            return
        try:
            import ctypes
            u32 = ctypes.windll.user32
            hwnd = self._hwnd()
            if not hwnd:
                return
            u32.IsZoomed.argtypes = [ctypes.c_void_p]
            u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            SW_RESTORE, SW_MAXIMIZE = 9, 3
            u32.ShowWindow(hwnd, SW_RESTORE if u32.IsZoomed(hwnd) else SW_MAXIMIZE)
        except Exception:
            pass

    def _native_drag(self):
        """Ask Windows to run its own move loop, as if the titlebar were a real
        caption. Smooth, and it brings Aero snap with it."""
        if not CUSTOM_FRAME:
            return
        try:
            import ctypes
            u32 = ctypes.windll.user32
            hwnd = self._hwnd()
            if not hwnd:
                return
            WM_NCLBUTTONDOWN, HTCAPTION = 0x00A1, 2
            u32.ReleaseCapture()
            u32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                         ctypes.c_void_p, ctypes.c_void_p]
            u32.SendMessageW(hwnd, WM_NCLBUTTONDOWN,
                             ctypes.c_void_p(HTCAPTION), None)
        except Exception:
            pass

    def minimize(self):
        if not CUSTOM_FRAME:
            return
        try:
            import ctypes
            hwnd = self._hwnd()
            ctypes.windll.user32.ShowWindow(hwnd, 6)   # SW_MINIMIZE
        except Exception:
            pass

    def _dock(self):
        tabs = (("Dashboard", "Home", "Home", "home"), ("All Mods", "Mods", "Mods", "library"),
                ("Connection", "Connection", "Device", "device"), ("Appearance", "Appearance", "Style", "style"),
                ("Credits", "Credits", "Credits", "credits"))
        w = max(1, imgui.get_content_region_avail().x)
        small = w < 620
        width = (w - 4 * 4) / 5
        height = (51 if small else 45) * self.zoom
        current = self.section if self.section in {t[0] for t in tabs} else "All Mods"
        for index, (page, label, short_label, icon) in enumerate(tabs):
            if index:
                imgui.same_line(0, 4)
            key = "##nav_" + page
            hit = imgui.invisible_button(key, ImVec2(max(1, width), height), imgui.ButtonFlags_.enable_nav)
            hover = self._animate(key + "/hover", imgui.is_item_hovered(), 0)
            selected = self._animate(key + "/selected", current == page)
            p, q = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            dl, color = imgui.get_window_draw_list(), imgui.get_color_u32
            dl.add_rect_filled(p, q, color(_blend(_blend(PANEL, CARD2, hover), PINK, selected)), imgui.get_style().frame_rounding)
            ink = _blend(_blend(MUTED, TEXT, hover), self._ink_on_accent(), selected)
            edge = _blend(EDGE, PINK, max(selected, hover * 0.6))
            self._border(dl, p, q, PINK_HI if imgui.is_item_focused() else edge, hover=hover)
            with _font(12 if small else 16):
                caption = self._fit_label(short_label if small else label, width - 4)
                ts = imgui.calc_text_size(caption)
                if small:
                    ix, iy = (p.x + q.x) / 2 - 8, p.y + 7
                    tx, ty = (p.x + q.x - ts.x) / 2, q.y - 19
                else:
                    ix, iy = (p.x + q.x - ts.x - 26) / 2, p.y + (height - 16) / 2
                    tx, ty = ix + 26, p.y + (height - ts.y) / 2
                draw_icon(dl, icon, ix, iy, 16, ink)
                dl.add_text(ImVec2(round(tx), round(ty)), color(ink), caption)
            if small and imgui.is_item_hovered(imgui.HoveredFlags_.delay_short):
                imgui.set_tooltip(_page_label(page))
            if hit:
                self._navigate(page)

    def _library_navigation(self, compact):
        groups = [(kind, title, pages) for kind, title, pages in _menu_groups(self.schema)
                  if kind == "collection" or title == "Library"]
        if not groups:
            return
        if compact:
            width = imgui.get_content_region_avail().x
            stacked = width < 390
            field = width if stacked else max(1, (width - 8) / 2)
            index = next((i for i, (_, _, pages) in enumerate(groups) if self.section in pages), 0)
            imgui.begin_group()
            imgui.text_colored(MUTED, "Collection")
            imgui.set_next_item_width(field)
            changed, index = imgui.combo("##navgroup", index, [title for _, title, _ in groups])
            pages = groups[index][2]
            if changed:
                self._navigate(pages[0])
            imgui.end_group()
            if not stacked:
                imgui.same_line(0, 8)
            imgui.begin_group()
            imgui.text_colored(MUTED, "Page")
            imgui.set_next_item_width(field)
            current = pages.index(self.section) if self.section in pages else 0
            changed, current = imgui.combo("##navpage", current, [_page_label(page) for page in pages])
            if changed:
                self._navigate(pages[current])
            imgui.end_group()
            imgui.separator()
            return

        self._update_library_counts()
        for kind, title, pages in groups:
            if kind == "collection":
                active_group = getattr(self, "_expanded_group", None)
                active = self.section in pages if active_group is None else active_group == title
                imgui.set_next_item_open(active, imgui.Cond_.always)
                opened = imgui.collapsing_header(title + "##collection/" + title)
                if opened != active:
                    self._expanded_group = title if opened else ""
                    self._cue("click" if opened else "back")
                if not opened:
                    continue
            else:
                self._section_caption(title)
            for page in pages:
                count = str(self._nav_counts.get(page) or "") if self.preferences["counts"] else ""
                if self._index_row("##library-page/" + page, _page_label(page), count, "library",
                                   selected=page == self.section):
                    self._navigate(page)

    def _section_caption(self, text):
        if self.preferences["menu_layout"] == "Midnight":
            return midnight.section_caption(self, text)
        w = max(1, imgui.get_content_region_avail().x)
        p = imgui.get_cursor_screen_pos()
        dl, color = imgui.get_window_draw_list(), imgui.get_color_u32
        with _font(12, FONT_BIG):
            title = self._fit_label(text.upper(), w)
            dl.add_text(ImVec2(p.x, p.y + 3 * self.zoom), color(MUTED), title)
            cut = imgui.calc_text_size(title).x + 12
        if cut < w:
            dl.add_line(ImVec2(p.x + cut, p.y + 10 * self.zoom), ImVec2(p.x + w, p.y + 10 * self.zoom), color(EDGE))
        imgui.dummy(ImVec2(w, 18 * self.zoom))

    @staticmethod
    def _fit_label(text, width):
        text = str(text)
        if imgui.calc_text_size(text).x <= width:
            return text
        ellipsis = "…"
        if imgui.calc_text_size(ellipsis).x > width:
            return ""
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if imgui.calc_text_size(text[:middle] + ellipsis).x <= width:
                low = middle
            else:
                high = middle - 1
        return text[:low] + ellipsis

    def _page_heading(self, eyebrow, title, description):
        self._banner(eyebrow, title, description)
        imgui.spacing()

    def _dashboard(self):
        self._update_library_counts()
        width = max(1, imgui.get_content_region_avail().x)
        self._poster("Workspace", "Dashboard", "Signed in as " + self.account.user,
                     height=181 if width >= 600 else 141)
        imgui.spacing()
        self._home_services()
        self._section_caption("Library")
        gap = 6.0
        bw = max(1, (width - 2 * gap) / 3)
        for index, (page, caption, icon) in enumerate((("All Mods", "Controls", "library"),
                                                       ("Enabled Mods", "Enabled", "power"),
                                                       ("Favorites", "Favorites", "star"))):
            if index:
                imgui.same_line(0, gap)
            key = "##collection_" + page
            hit = imgui.invisible_button(key, ImVec2(bw, 70 * self.zoom), imgui.ButtonFlags_.enable_nav)
            p, q = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            dl, color = imgui.get_window_draw_list(), imgui.get_color_u32
            hover = self._animate(key + "/hover", imgui.is_item_hovered(), 0)
            dl.add_rect_filled(p, q, color(_blend(CARD, CARD2, hover)), imgui.get_style().frame_rounding)
            self._border(dl, p, q, PINK if imgui.is_item_focused() else _blend(EDGE, PINK, hover), hover=hover)
            if bw >= 120:
                draw_icon(dl, icon, q.x - 29, p.y + 11, 16, PURPLE)
            with _font(27, FONT_BIG):
                dl.add_text(ImVec2(p.x + 12, p.y + 5), color(PINK), str(self._nav_counts[page]))
            with _font(14):
                dl.add_text(ImVec2(p.x + 12, q.y - 24), color(TEXT), self._fit_label(caption, bw - 19))
            if imgui.is_item_hovered():
                imgui.set_tooltip(_page_label(page))
            if hit:
                self._navigate(page)
        imgui.spacing()
        spread = (self.preferences["menu_layout"] == "Midnight" and width >= max(565*self.zoom, 36*imgui.get_font_size())
                  and imgui.begin_table("home-overview", 2, imgui.TableFlags_.sizing_stretch_same | imgui.TableFlags_.no_saved_settings))
        if spread:
            imgui.table_next_column()
        self._section_caption("Collections")
        groups = nav.navigation_groups(self.schema)
        for title, pages in groups:
            if title != "Workspace" and pages:
                count = sum(self._section_counts.get(page, 0) for page in set(pages))
                detail = "%d %s  /  %d %s" % (len(pages), "page" if len(pages) == 1 else "pages",
                                             count, "control" if count == 1 else "controls")
                if not count:
                    detail = f"{len(pages)} pages  /  runtime"
                if self._index_row("##collection_" + title, title, detail, "library"):
                    self._navigate(pages[0])
        imgui.spacing()
        if spread:
            imgui.table_next_column()
        self._section_caption("Session")
        if self._index_row("##session_overview", "Connection", self.headset.status()[1] if self.headset.phase != "idle" else "Not checked", "device"):
            self._navigate("Connection")
        if self._index_row("##home_appearance", "Appearance", THEME, "style"):
            self._navigate("Appearance")
        if self._index_row("##home_categories", "Mod categories", "Browse", "library"):
            self._navigate("All Mods")
            self._category_index = True
        recent = [page for page in getattr(self, "_recent_sections", []) if page not in ("Dashboard", "Connection", "Appearance")][:3]
        if recent:
            self._section_caption("Recently opened")
            for page in recent:
                if self._index_row("##recent_" + page, _page_label(page), "", "arrow"):
                    self._navigate(page)
        if spread:
            imgui.end_table()

    def _index_row(self, key, label, detail, icon, selected=False):
        if self.preferences["menu_layout"] == "Midnight":
            return midnight.index_row(self, key, label, detail, icon, selected)
        width = max(1, imgui.get_content_region_avail().x)
        pressed = imgui.invisible_button(key, ImVec2(width, 40 * self.zoom), imgui.ButtonFlags_.enable_nav)
        p, q = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        hover = self._animate(key + "/hover", imgui.is_item_hovered(), 0)
        dl, color = imgui.get_window_draw_list(), imgui.get_color_u32
        face = _blend(CARD2, PINK, 0.15) if selected else _blend(PANEL, CARD2, hover)
        dl.add_rect_filled(p, q, color(face), imgui.get_style().frame_rounding)
        self._border(dl, p, q, PINK if selected or imgui.is_item_focused() else _blend(EDGE, PURPLE, hover), hover=hover)
        draw_icon(dl, icon, p.x + 12 * self.zoom, p.y + 12 * self.zoom, 16, _blend(FAINT, PINK, hover))
        with _font(13):
            short = self._fit_label(detail, width * 0.43)
            detail_w = imgui.calc_text_size(short).x
            dl.add_text(ImVec2(q.x - 28 - detail_w, p.y + 13 * self.zoom), color(MUTED), short)
        shown = self._fit_label(label, width - detail_w - 78)
        dl.add_text(ImVec2(p.x + 40 * self.zoom, p.y + 10 * self.zoom), color(TEXT), shown)
        if shown != label and imgui.is_item_hovered():
            imgui.set_tooltip(label)
        dl.add_text(ImVec2(q.x - 19 + hover * 2, p.y + 10 * self.zoom), color(PINK), ">")
        return pressed

    @staticmethod
    def _color_picker(label, widget_id, color):
        flags = (imgui.ColorEditFlags_.picker_hue_wheel.value |
                 imgui.ColorEditFlags_.no_side_preview.value |
                 imgui.ColorEditFlags_.no_inputs.value)
        imgui.begin_group()
        imgui.text_colored(FAINT, label)
        imgui.set_next_item_width(118)
        changed, value = imgui.color_picker3(widget_id, [c / 255.0 for c in color], flags)
        imgui.end_group()
        if changed:
            color = tuple(round(c * 255) for c in value[:3])
        return color, changed

    def _appearance(self):
        w = imgui.get_content_region_avail().x
        self._banner("Panel", "Appearance", illustrated=False)
        columns = w >= 780 * self.zoom and imgui.begin_table("appearance-spread", 2, imgui.TableFlags_.no_saved_settings)
        if columns:
            imgui.table_setup_column("Palettes", imgui.TableColumnFlags_.width_stretch, 0.84)
            imgui.table_setup_column("Settings", imgui.TableColumnFlags_.width_stretch, 1.16)
            imgui.table_next_column()
            self._section_caption("Color palette")
            self._palette_shelf()
            if THEME == "Custom" and imgui.collapsing_header("Custom palette"):
                self._custom_palette_controls()
            imgui.spacing()
            appearance.presets(self)
            imgui.table_next_column()
            self._poster("Palette preview", THEME, height=104)
        else:
            self._poster("Palette preview", THEME, height=95)
            if imgui.collapsing_header("Palettes and presets"):
                self._palette_shelf()
                if THEME == "Custom":
                    self._custom_palette_controls()
                appearance.presets(self)
        appearance.editor(self)
        if columns:
            imgui.end_table()

    def _palette_shelf(self):
        w = max(1, imgui.get_content_region_avail().x)
        cols = 2 if w >= 300 else 1
        gap = 6
        width = (w - (cols - 1) * gap) / cols
        overrides = self.preferences["colors"]
        for i, name in enumerate(THEME_NAMES):
            if i % cols:
                imgui.same_line(0, gap)
            key = "##palette" + name
            hit = imgui.invisible_button(key, ImVec2(width, 41 * self.zoom), imgui.ButtonFlags_.enable_nav)
            hover = self._animate(key + "/hover", imgui.is_item_hovered(), 0)
            t = build_custom(CUSTOM_ACC, CUSTOM_BG) if name == "Custom" else THEMES[name]
            if name == "Havoc" and self.preferences["menu_layout"] == "Midnight":
                t = {**t, **midnight.PALETTE}
            t = appearance.palette(t, overrides.get(name))
            p, q = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            dl, color = imgui.get_window_draw_list(), imgui.get_color_u32
            chosen = name == THEME
            dl.add_rect_filled(p, q, color(_blend(CARD, CARD2, hover)), imgui.get_style().frame_rounding)
            edge = PINK if chosen or imgui.is_item_focused() else _blend(EDGE, PINK, hover * 0.75)
            self._border(dl, p, q, edge, hover=hover)
            for j, tone in enumerate(("alt", "acc", "acc_hi")):
                x = p.x + 9 * self.zoom + j * 6
                dl.add_rect_filled(ImVec2(x, p.y + 10 * self.zoom), ImVec2(x + 6, q.y - 10), color(rgb(*t[tone])))
            with _font(14):
                dl.add_text(ImVec2(p.x + 35 * self.zoom, p.y + 12 * self.zoom), color(PINK if chosen else TEXT),
                            self._fit_label(name, width - 42))
            if hit:
                self.set_theme(name)

    def _custom_palette_controls(self):
        global CUSTOM_ACC, CUSTOM_BG
        avail = imgui.get_content_region_avail().x
        imgui.dummy(ImVec2(1, 8))
        imgui.separator()
        imgui.dummy(ImVec2(1, 6))
        CUSTOM_ACC, changed = self._color_picker("ACCENT", "##acc", CUSTOM_ACC)
        if changed:
            self.set_theme("Custom")
        if avail >= 330:
            imgui.same_line(0, 24)
        CUSTOM_BG, changed = self._color_picker("BACKGROUND", "##bg", CUSTOM_BG)
        if changed:
            self.set_theme("Custom")
        if avail >= 490:
            imgui.same_line(0, 24)
        imgui.begin_group()
        imgui.text_colored(FAINT, "PRESETS")
        imgui.spacing()
        for label, a, b in (
                ("blood",  (220, 40, 60),   (20, 12, 14)),
                ("gold",   (255, 190, 70),  (26, 22, 14)),
                ("mint",   (90, 240, 190),  (14, 24, 22)),
                ("violet", (170, 110, 255), (20, 16, 30)),
                ("paper",  (60, 60, 70),    (238, 236, 240))):
            if imgui.button("  %s  " % label):
                CUSTOM_ACC, CUSTOM_BG = a, b
                self.set_theme("Custom")
        imgui.end_group()

    def _stage(self, n, title, state, detail, action=None, act_label=""):
        """One row of the connection checklist.

        state: "ok" | "wait" | "bad" | "busy"
        Returns True if its action button was pressed.
        """
        dl = imgui.get_window_draw_list()
        p = imgui.get_cursor_screen_pos()
        w = imgui.get_content_region_avail().x
        h = 62.0 * self.zoom
        imgui.invisible_button("##stage%d" % n, ImVec2(w, h))
        stage_id = imgui.get_item_id()
        hov = imgui.is_item_hovered()

        col = {"ok": ON, "busy": PINK, "bad": rgb(234, 137, 116)}.get(state, MUTED)
        cr, cg, cb = col.x * 255, col.y * 255, col.z * 255
        color = imgui.get_color_u32
        dl.add_rect_filled(p, ImVec2(p.x + w, p.y + h), color(CARD2 if hov and self.preferences["hover"] != "Off" else CARD), imgui.get_style().frame_rounding)
        self._border(dl, p, ImVec2(p.x + w, p.y + h), EDGE)
        # A numbered tile and a small status light share the checklist gutter.
        tile = ImVec2(p.x + 8 * self.zoom, p.y + 12 * self.zoom)
        tile_end = ImVec2(p.x + 44 * self.zoom, p.y + h - 12)
        dl.add_rect_filled(tile, tile_end, color(_blend(CARD, col, 0.15)))
        with _font(15, FONT_BIG):
            number = "%02d" % n
            ns = imgui.calc_text_size(number)
            dl.add_text(ImVec2((tile.x + tile_end.x - ns.x) / 2, tile.y + 4), color(col), number)
        t = self._visual_time if self.ambient_motion and state == "busy" else 0
        dl.add_rect_filled(ImVec2(tile.x + 10, tile_end.y - 9), ImVec2(tile_end.x - 10, tile_end.y - 6),
                           color(_tint(col, 0.8 + 0.2 * math.cos(t * 4))))
        reserve = imgui.calc_text_size(act_label).x + 42 if action and act_label else 0
        text_w = max(1, w - 64 - reserve)
        shown = self._fit_label(title, text_w)
        short_detail = self._fit_label(detail, text_w)
        dl.add_text(ImVec2(p.x + 54 * self.zoom, p.y + 10 * self.zoom), color(TEXT), shown)
        dl.add_text(ImVec2(p.x + 54 * self.zoom, p.y + 33 * self.zoom), color(MUTED), short_detail)
        if hov and (short_detail != detail or shown != title):
            _wrapped_tip(title + "\n" + detail)

        pressed = over = False
        if action and act_label:
            bw = imgui.calc_text_size(act_label).x + 28
            bx = p.x + w - bw - 10
            by = p.y + (h - 24) * 0.5
            mp = imgui.get_io().mouse_pos
            over = (bx <= mp.x <= bx + bw) and (by <= mp.y <= by + 24)
            dl.add_rect_filled(ImVec2(bx, by), ImVec2(bx + bw, by + 24),
                               imgui.get_color_u32(rgb(cr, cg, cb, 0.9 if over else 0.6)), 6)
            self._border(dl, ImVec2(bx, by), ImVec2(bx + bw, by + 24), col)
            ts = imgui.calc_text_size(act_label)
            dl.add_text(ImVec2(bx + (bw - ts.x) * 0.5, by + (24 - ts.y) * 0.5),
                        imgui.get_color_u32(rgb(12, 14, 17, 1.0)), act_label)
            if over and hov and imgui.is_mouse_clicked(0):
                pressed = True
        if hov and not over:
            self._quiet_hover = stage_id
        imgui.dummy(ImVec2(1, 6))
        return pressed

    @staticmethod
    def _slider_limits(item):
        lo, hi = safe_float(item.get("min"), 0), safe_float(item.get("max"), 1)
        lo = lo if math.isfinite(lo) else 0.0
        hi = hi if math.isfinite(hi) else lo + 1.0
        lo, hi = min(lo, hi), max(lo, hi)
        span = hi - lo
        if not math.isfinite(span):
            lo, hi, span = 0.0, 1.0, 1.0
        precision = max(0, min(6, int(math.ceil(-math.log10(span / 1000))))) if span > 0 else 3
        if item.get("key") == "ARM_LENGTH":
            precision = max(3, precision)
        return lo, hi, precision

    def _bar(self, key, item, val, on_change=None):
        set_value = on_change if on_change is not None else lambda number: self.push(key, number)
        lo, hi, precision = self._slider_limits(item)
        span = hi - lo
        val = safe_float(val, lo)
        val = max(lo, min(hi, val)) if math.isfinite(val) else lo
        fmt = "%.4e" if 0 < span < 0.0001 else "%%.%df" % precision
        default = safe_float(item.get("value"), lo)
        default = max(lo, min(hi, default)) if math.isfinite(default) else lo
        w = max(1, imgui.get_content_region_avail().x)
        compact = self.preferences["menu_layout"] == "Midnight"
        z = self.zoom
        low_text, high_text = "%g" % lo, "%g" % hi
        field_w = min(w * 0.37, 87 * z) if compact else 96 * z
        pad = (7 if compact else 14) * z
        row_h = max(imgui.get_frame_height(), 22 * z)
        label = item.get("name") or pretty_key(key)
        label_width = max(1, w - 2*pad)
        stacked = imgui.calc_text_size(label).x > w - field_w - 3*pad
        extra = imgui.calc_text_size(label, wrap_width=label_width).y + 4*z if stacked else 0
        track_y = row_h + 7*z if compact else 43*z
        track_y += extra
        step_y = track_y + imgui.get_font_size() + 8*z if compact else 103*z + extra
        step_h = row_h if compact else 30*z
        h = step_y + step_h + 6*z if compact else 140*z + extra
        imgui.push_id("tuning:" + key)
        imgui.begin_group()
        p = imgui.get_cursor_screen_pos()
        imgui.dummy(ImVec2(w, h))
        after = imgui.get_cursor_screen_pos()
        dl = imgui.get_window_draw_list()
        color = imgui.get_color_u32
        dl.add_rect_filled(p, ImVec2(p.x + w, p.y + h), color(CARD), max(2, imgui.get_style().frame_rounding))
        self._border(dl, p, ImVec2(p.x + w, p.y + h), EDGE)
        label_y = 3*z + (row_h - imgui.get_font_size())/2 if compact else 10*z
        dl.add_text(imgui.get_font(), imgui.get_font_size(), ImVec2(p.x + pad, p.y + label_y),
                    color(TEXT), label, wrap_width=label_width if stacked else 0)
        
        # The numeric editor is separate from the track, so exact input and
        # native slider keyboard navigation both remain predictable.
        if not hasattr(self, "_slider_inputs"):
            self._slider_inputs = {}
        buffer, was_active = self._slider_inputs.get(key, (fmt % val, False))
        if not was_active:
            buffer = fmt % val
        imgui.set_cursor_screen_pos(ImVec2(p.x + w - pad - field_w, p.y + (3 if compact else 10)*z + extra))
        imgui.set_next_item_width(field_w)
        flags = (imgui.InputTextFlags_.chars_scientific |
                 imgui.InputTextFlags_.auto_select_all | imgui.InputTextFlags_.enter_returns_true)
        imgui.push_style_color(imgui.Col_.frame_bg, CARD2)
        commit, buffer = imgui.input_text("##value", buffer, flags)
        imgui.pop_style_color()
        active = imgui.is_item_active()
        finished = imgui.is_item_deactivated_after_edit()
        canceled = (active or was_active) and imgui.is_key_pressed(imgui.Key.escape)
        if canceled:
            buffer = fmt % val
        elif commit or finished:
            try:
                number = float(buffer.strip())
                if math.isfinite(number):
                    number = max(lo, min(hi, number))
                    if number != val:
                        set_value(number)
                        val = number
            except ValueError:
                pass
            buffer = fmt % val
        self._slider_inputs[key] = (buffer, active)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Type an exact value. Enter to apply; Escape to cancel.")

        left = min(w * .24, imgui.calc_text_size(low_text).x + 5*z) if compact else 0
        right = min(w * .24, imgui.calc_text_size(high_text).x + 5*z) if compact else 0
        imgui.set_cursor_screen_pos(ImVec2(p.x + pad + left, p.y + track_y))
        imgui.set_next_item_width(max(1, w - 2*pad - left - right))
        # Let ImGui own focus, dragging and arrow keys. Paint the track and
        # handle ourselves over an invisible native slider.
        for slot in (imgui.Col_.frame_bg, imgui.Col_.frame_bg_hovered,
                     imgui.Col_.frame_bg_active, imgui.Col_.slider_grab,
                     imgui.Col_.slider_grab_active, imgui.Col_.text):
            imgui.push_style_color(slot, ImVec4(0, 0, 0, 0))
        imgui.push_style_var(imgui.StyleVar_.frame_padding, ImVec2(0, 2*z if compact else 10))
        imgui.push_style_var(imgui.StyleVar_.frame_border_size, 0.0)
        imgui.begin_disabled(span <= 0)
        changed, number = imgui.slider_float("##track", val, lo, hi, fmt, imgui.SliderFlags_.no_input)
        held, hovered, focused = imgui.is_item_active(), imgui.is_item_hovered(), imgui.is_item_focused()
        track_min, track_max = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        imgui.end_disabled()
        imgui.pop_style_var(2)
        imgui.pop_style_color(6)
        if changed:
            number = max(lo, min(hi, float(number)))
            if number != val:
                set_value(number)
                val = number
        if hovered:
            _wrapped_tip(label + "\nDrag to adjust. Use arrow keys for small changes.")
        ratio = (val - lo) / span if span > 0 else 0.0
        previous = self._bar_anim.get(key, ratio)
        amount = 1.0 if held or not self.ambient_motion else min(1, imgui.get_io().delta_time * 18 * self.preferences["speed"] / 100)
        ratio_draw = previous + (ratio - previous) * amount
        self._bar_anim[key] = ratio_draw
        # Match the native slider's usable grab travel, including its padding.
        inset = max(1, imgui.get_style().grab_min_size) * 0.5 + 2
        x0, x1 = track_min.x + inset, max(track_min.x + inset, track_max.x - inset)
        cy = (track_min.y + track_max.y) * 0.5
        knob_x = x0 + (x1 - x0) * ratio_draw
        if compact:
            midnight.track(self, dl, x0, x1, knob_x, cy, held or hovered or focused)
        else:
            dl.add_rect_filled(ImVec2(x0, cy - 3 * self.zoom), ImVec2(x1, cy + 3 * self.zoom), color(EDGE))
            if knob_x > x0:
                dl.add_rect_filled(ImVec2(x0, cy - 3 * self.zoom), ImVec2(knob_x, cy + 3 * self.zoom), color(PINK))
            for index in range(11):
                tx = x0 + (x1 - x0) * index / 10
                dl.add_line(ImVec2(tx, cy + 11 * self.zoom), ImVec2(tx, cy + (16 if index % 5 == 0 else 13)), color(EDGE), 1)
            if span > 0:
                dx = x0 + (x1 - x0) * (default - lo) / span
                dl.add_circle_filled(ImVec2(dx, cy + 19 * self.zoom), 2, color(MUTED), 8)
            if held or hovered or focused:
                dl.add_rect_filled(ImVec2(knob_x - 10 * self.zoom, cy - 12 * self.zoom), ImVec2(knob_x + 10 * self.zoom, cy + 12 * self.zoom),
                                   color(_tint(PINK, 0.18)))
            dl.add_rect_filled(ImVec2(knob_x - 5 * self.zoom, cy - 8 * self.zoom), ImVec2(knob_x + 5 * self.zoom, cy + 8 * self.zoom), color(TEXT))
            dl.add_line(ImVec2(knob_x, cy - 4 * self.zoom), ImVec2(knob_x, cy + 4 * self.zoom), color(EDGE))
        label_y = cy - imgui.get_font_size()/2 if compact else p.y + 81*z
        dl.add_text(ImVec2(p.x + pad, label_y), color(MUTED), self._fit_label(low_text, left) if compact else low_text)
        upper = self._fit_label(high_text, right) if compact else high_text
        dl.add_text(ImVec2(p.x + w - (pad if compact else 14) - imgui.calc_text_size(upper).x, label_y), color(MUTED), upper)

        imgui.set_cursor_screen_pos(ImVec2(p.x + pad, p.y + step_y))
        step = span / 100 if span else 0
        if imgui.get_io().key_shift:
            step /= 10
        imgui.begin_disabled(span <= 0)
        imgui.push_style_color(imgui.Col_.button, CARD2)
        for index, (text, target) in enumerate((("-", val - step), ("Reset", default), ("+", val + step))):
            if index:
                imgui.same_line(0, 5)
            width = (44 if index == 1 else 26) if compact else (62 if index == 1 else 36)
            if imgui.button(text, ImVec2(width * z, step_h)):
                target = max(lo, min(hi, target))
                if target != val:
                    set_value(target)
            if imgui.is_item_hovered():
                imgui.set_tooltip("Restore loaded default: %g" % default if index == 1
                                  else "Adjust by %g (hold Shift for finer steps)" % step)
        imgui.pop_style_color()
        imgui.end_disabled()
        if w > 300:
            hint = "DEFAULT %g" % default
            dl.add_text(ImVec2(p.x + w - 14 - imgui.calc_text_size(hint).x, p.y + (step_y + (step_h - imgui.get_font_size())/2 if compact else 109*z)), color(MUTED), hint)
        imgui.set_cursor_screen_pos(after)
        imgui.dummy(ImVec2(0, 0))
        imgui.end_group()
        imgui.pop_id()

    def _switch_face(self, key, label, on):
        if self.preferences["menu_layout"] == "Midnight":
            return midnight.switch_face(self, key, label, on)
        w, h = max(1, imgui.get_content_region_avail().x), 42 * self.zoom
        pressed = imgui.invisible_button("##switch/" + key, ImVec2(w, h), imgui.ButtonFlags_.enable_nav)
        if not imgui.is_item_visible():
            return pressed
        hovered, focused = imgui.is_item_hovered(), imgui.is_item_focused()
        active = not on if pressed else on
        state = self._animate("state/" + key, active, on, 21)
        hover = self._animate("hover/" + key, hovered, 0)
        dl, color = imgui.get_window_draw_list(), imgui.get_color_u32
        p, q = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        cy = round((p.y + q.y) / 2)
        dl.add_rect_filled(p, q, color(_blend(CARD, CARD2, hover)), imgui.get_style().frame_rounding)
        self._border(dl, p, q, PINK if focused else _blend(EDGE, PINK, hover * 0.45), hover=hover)
        cx = q.x - 30
        rail = _blend(EDGE, PINK, state)
        dl.add_rect_filled(ImVec2(cx - 18, cy - 9), ImVec2(cx + 18, cy + 9), color(rail))
        knob = round(cx - 15 + 17 * state)
        dl.add_rect_filled(ImVec2(knob, cy - 6), ImVec2(knob + 13, cy + 6),
                           color(_blend(TEXT, self._ink_on_accent(), state)))
        dl.add_line(ImVec2(knob + 5, cy - 3), ImVec2(knob + 5, cy + 3), color(rail))
        reserve = 70
        if w >= 190:
            caption = "ON" if active else "OFF"
            with _font(12):
                ts = imgui.calc_text_size(caption)
                dl.add_text(ImVec2(cx - 26 - ts.x, cy - ts.y / 2), color(_blend(MUTED, PINK, state)), caption)
            reserve = 102
        shown = self._fit_label(label, w - reserve)
        dl.add_text(ImVec2(p.x + 12, cy - imgui.get_font_size() / 2), color(TEXT), shown)
        if hovered and shown != label:
            imgui.set_tooltip(label)
        return pressed

    def _switch_card(self, item):
        key = item["key"]
        on = bool(self.values.get(key, item["value"]))
        if self._switch_face(key, item.get("name") or pretty_key(key), on):
            self.push(key, not on)

    def _enum_card(self, item):
        # dropdown for a fixed-set-of-choices value (e.g. Day / Night, pull mode)
        key = item["key"]
        label = item.get("name") or pretty_key(key)
        opts = list(item.get("options") or [])
        if not opts:
            return self._switch_card(item)
        cur = self.values.get(key, item["value"])
        try:
            idx = opts.index(cur)
        except ValueError:
            idx = 0
        if self.preferences["menu_layout"] == "Midnight":
            imgui.text_wrapped(label)
        else:
            imgui.text_colored(MUTED, label)
        imgui.set_next_item_width(imgui.get_content_region_avail().x)
        changed, new_idx = imgui.combo("##enum" + key, idx, opts)
        if changed and 0 <= new_idx < len(opts):
            self.push(key, opts[new_idx])
        imgui.dummy(ImVec2(1, 4))

    def _resize_grip(self):
        """Mark the resize area handled by HelloImGui."""
        dl = imgui.get_foreground_draw_list()
        vp = imgui.get_main_viewport()
        x1 = vp.pos.x + vp.size.x
        y1 = vp.pos.y + vp.size.y
        self._border(dl, vp.pos, ImVec2(x1, y1), EDGE)
        mp = imgui.get_io().mouse_pos
        near = (mp.x > x1 - 22) and (mp.y > y1 - 22)
        a = 0.55 if near else 0.22
        for i, off in enumerate((5.0, 10.0, 15.0)):
            fade = a * (1.0 - i * 0.22)
            dl.add_line(ImVec2(x1 - off, y1 - 2), ImVec2(x1 - 2, y1 - off),
                        imgui.get_color_u32(rgb(PINK.x * 255, PINK.y * 255,
                                                PINK.z * 255, fade)), 1.6)

    def _glass_overlay(self):
        dl = imgui.get_window_draw_list()
        p = imgui.get_window_pos()
        size = imgui.get_window_size()
        if size.x < 28 or size.y < 28:
            return
        color = imgui.get_color_u32
        tint = _tint(PINK, 0.045)
        clear = _tint(PINK, 0)
        dl.add_rect_filled_multi_color(
            ImVec2(p.x + 12, p.y + 1), ImVec2(p.x + size.x - 12, p.y + min(130, size.y - 12)),
            color(tint), color(clear), color(clear), color(clear))
        dl.add_line(ImVec2(p.x + 16, p.y + 1), ImVec2(p.x + size.x - 16, p.y + 1),
                    color(rgb(255, 255, 255, 0.09)), 1)

    def _bookmark(self, key, keys, saved, width):
        if self.preferences["menu_layout"] == "Midnight":
            pressed = midnight.bookmark(self, saved, width)
        else:
            pressed = self._button("Saved" if saved else "+ Save mod", width, 30)
        if pressed:
            self._toggle_favorite(key, keys)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Remove from Favorites" if saved else "Add to Favorites")

    def _footer(self):
        imgui.separator()
        start = imgui.get_cursor_pos()
        w = max(1, imgui.get_content_region_avail().x)
        button_w = min(96, w)
        self._footer_status(w - button_w - imgui.get_style().item_spacing.x)
        imgui.set_cursor_pos(ImVec2(start.x + w - button_w, start.y))
        if self._button("Presets", button_w):
            imgui.open_popup("local-presets")
        imgui.set_next_window_size_constraints(ImVec2(min(282, w), 0), ImVec2(max(w, 1), 420))
        if imgui.begin_popup("local-presets"):
            self._section_caption("Local presets")
            names = self.local_presets()
            if names:
                idx = names.index(self._preset_sel) if self._preset_sel in names else 0
                imgui.set_next_item_width(-1)
                _, idx = imgui.combo("##preset", idx, names)
                self._preset_sel = names[idx]
                if imgui.button("Load"):
                    self.load_local_preset(self._preset_sel)
                imgui.same_line()
                if imgui.button("Delete"):
                    self.delete_local_preset(self._preset_sel)
            imgui.set_next_item_width(-1)
            _, self._preset_new = imgui.input_text_with_hint("##pname", "New preset name", self._preset_new)
            if imgui.button("Save"):
                self.save_local_preset(self._preset_new or self._preset_sel or "preset")
                self._preset_new = ""
            imgui.same_line()
            if imgui.button("Reset"):
                self._reset_values()
            imgui.end_popup()


def load_fonts():
    global FONT_BIG, FONT_HUGE, menu_font
    io = imgui.get_io()
    io.config_flags |= imgui.ConfigFlags_.nav_enable_keyboard
    size = 16.0  # The supplied face has sixteen design pixels per em.
    imgui.get_style().font_size_base = size
    system_faces = ("C:/Windows/Fonts/segoeui.ttf",
                    "/System/Library/Fonts/Supplemental/Arial.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/truetype/open-sans/OpenSans-Regular.ttf")
    # Support the loose script, a font next to the EXE, and a bundled asset.
    folders = (ASSET_ROOT,)
    pixel_cfg = imgui.ImFontConfig()
    pixel_cfg.pixel_snap_h = True
    pixel_cfg.oversample_h = pixel_cfg.oversample_v = 1
    def first_available(paths, config):
        for path in paths:
            if os.path.isfile(path):
                try:
                    return io.fonts.add_font_from_file_ttf(path, size, config)
                except RuntimeError:
                    continue
        return None

    main_font = first_available((os.path.join(folder, "Minecraft.ttf") for folder in folders), pixel_cfg)
    # Merge a system face for the punctuation and names outside Minecraft's glyph set.
    fallback_cfg = imgui.ImFontConfig()
    fallback_cfg.merge_mode = main_font is not None
    fallback = first_available(system_faces, fallback_cfg)
    if fallback is None:
        fallback = io.fonts.add_font_default(fallback_cfg)
    io.font_default = main_font if main_font is not None else fallback
    FONT_BIG = FONT_HUGE = io.font_default
    menu_font = first_available(system_faces, imgui.ImFontConfig()) or io.font_default


def main():
    panel = Panel()
    params = hello_imgui.RunnerParams()
    params.ini_folder_type = hello_imgui.IniFolderType.absolute_path
    params.ini_filename = str(ROOT / "window.ini")
    params.ini_filename_use_app_window_title = False
    params.app_window_params.window_title = WINDOW_TITLE
    params.app_window_params.window_geometry.size = (1200, 760)
    params.app_window_params.borderless = CUSTOM_FRAME
    # Native dragging owns the window position.
    params.app_window_params.borderless_movable = False
    params.app_window_params.borderless_resizable = True
    params.app_window_params.borderless_closable = False
    params.app_window_params.resizable = True
    params.app_window_params.restore_previous_geometry = True
    params.imgui_window_params.show_menu_bar = False
    params.imgui_window_params.show_status_bar = False
    params.imgui_window_params.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.provide_full_screen_window)
    # alpha 0 so blur mode can composite per-pixel; RGB still paints normally
    params.imgui_window_params.background_color = ImVec4(0.04, 0.04, 0.05, 0.0)
    params.callbacks.show_gui = panel.gui
    params.callbacks.load_additional_fonts = load_fonts
    params.fps_idling.fps_idle = 20
    try:
        immapp.run(params)
    finally:
        panel.shutdown()
    if panel.updater.phase == "installed":
        os.execv(sys.executable, [sys.executable, str(panel.updater.path)])

# Includes the font, wallpaper and five WAV files.
ASSET_DIGESTS = {'Minecraft.ttf': 'bd47314d301e50ff4d109bff28dfcf637cb7eb13945480259878b848875acc65',
 'midnight_landscape.jpg': '6eca7dd90dccb79c2d9799618b1d675ec230e3c345ad18e7aa984dbd7b7e3fb4',
 'ui_audio/sfx_back.wav': '2b0650f786e2a77b20b12415934fcae7b233cff418dc8f16442a4b54a5a6e00d',
 'ui_audio/sfx_hover.wav': 'e22130e333ecfb06a8cb48202f3e7f5a085ffffd50ffd8a93eb709d5eaf2ca0c',
 'ui_audio/sfx_release_main.wav': '1d161b277b4ea7851c5b4134373a3903cac03cf85bee5042fa89553f3d30e9c9',
 'ui_audio/ui_appear.wav': '37cf4eba9e7ad26a0d113c9d5b68bdb682ef70e9010499544cc340baac155bfe',
 'ui_audio/ui_disappear.wav': '6e94b826e91f6af4bbe1882bd865be6190299ecec95e9adeb0e4836228b5d653'}
ASSET_DATA = (
    b"UEsDBBQAAAAIAAAAIVwEOxY8FRIAAJg4AAANAAAATWluZWNyYWZ0LnR0Zr1bfYxU13U/97735s3sst/7WDtmYJdhs8ETYOExLDCM"
    b"eRgbHNuExGBIbAd7AwsmNYuLcUpVq3qSk8pSJbfhjyit8kflVpWaVlXNH5X7R5unVGrc1KpSyUqtynIst3+k+ZIaJZIrhd2ec+69"
    b"790382Z2MKizmr3v895zz8fvfNw7IABgGGJw4JkjR04e++KePX8HsPclvLrh6AMPHoER2IjnT+H5xuMnduz66v9eWQ8gnsXzU2cv"
    b"LT7/9umfvQzgXMNrT5z98tVp2CxfAXDfxvvuhcUXnl9dxZ5h70k8L1947rfPnxoIfgDgvQGwI3l2afFcqfrhNrz3U/zueRYvlN5z"
    b"LmNfW/B8y7OXrl77n3+Rr+F5gt83nrt8dvHlD3/rA+z6Hbz/3qXFa8/Dd+Ef8d5DeD69vHhpaeu6/5YADaLnzecvv3D13//1scMA"
    b"CxGeTwDNFb8bfyx/9fTIgV/BoAv0+bdvP/GNrEWCY4dOyyBBffAdB6/DU+p5J+ae7M8yX1mG6zDF55LfomsRbFd9iF+KX4KHt/5I"
    b"voXnf6Ba8RMIRYVeKDlpbw6+acaGXVevnsdepuc1DY4aXFMgvgybuX0cvzhLQE5JbKVukdaIjum6sL4Sr/O12Hon0vf0MT6j+omt"
    b"axEPHfE3yb/jJNk7NBl+V18z54LoAf1cnD3jRFnrRLl7UdqP9RWGFotWPI660Wy+PFfIjh37WdMaAcYZL9P5mHE130Sc0cNzs3kX"
    b"K17heUTPmXm5Rsrqu0HL8iQo0W7AB/ZiO8AaKOF34S+m/2oe0JJQx+FP1PHqf65+54fJ9y/lNVGUUsUAYaaRewCHdL2SX64MDK4b"
    b"Gh4ZHRufmAzWT91198fu2VDduGl6ZnNty+zH5z6x9d76J7dt3zG/c1e4u7FnYe++/c0DrfsORofuP4yocPShTz38yKPHPn38M599"
    b"7MTJx0+d/tznn3jyqS+cefqZRVj7c27pIjW/AfAlfeWCffusOfhi+4vPQX8fxiC4V/89DC/B98SkuC5+IV25Wz4jX5U35JvyXflT"
    b"Z9r5knPded+dd5fdNzzwdnuveN/z/qvklvaUzpReLX3ff8CP/X8qD5TvL18rv1b+cWVj5f7KcuVvK/8xsGHgzMCfDbwzuGXwyuAb"
    b"g++tm1x3ct031n04tHvopaHXht4dlsN7hh8dPjf82vAHI5tHTo1cH/mH0dLofaNnRq+PvjP6i7G9Y+fGvjn27vhd4/eNvzT+5+Nv"
    b"TwxMRBPfnPjB5PjkQ5PnJ/948jv496PgSPBK8MH6/evPrH97/c+n/nDq/an3WbJo92KX/BZqjQ/bXxew48AN34Wf7Xq95L174IYj"
    b"8RBed+iyR5dv+CXx6wM3BF0Px2bG5sKx2mYx+vO33pLfunlqszxvtIXQz4cqQFhriaaoirlaq4xtObI+SdTxYcUWsQR+fwTugTk8"
    b"133M6Ha25WDj1B1upaAXV6gzAaZXEZse444RNI2SaDwIRwGwX1nHjuqCWhqjJXQraYCsreL1qtCtdMIWn4uCifSaZOFHZPNfVfO/"
    b"B2pQRwrBw3njZEXTUfM3dDiKyGBOt7N1VxFvHhLtg8TpP9FxOSUk7hDKKDCiOoQ1FZhAudZQLtsghAVowWE4BqfhSVgkEwwbYTAb"
    b"BnXRCFtOWCUSsZFeS4RVpCwMWhIPZvF+U8ykz87w7Rn7jdlG7tkkYi7HxM+VOJ0Ail1JPqYWj+ipld6cjqP+P+TBja74OPNNKJEQ"
    b"Z/wInGC9UXpZlyScqlgg2klTPHMwq56oe3xKQlpoE5pMtTelbSVO5ZB0Sq7bNJJC8gmtpbLHQYCJmjIduichfYqjBqGeoRlCOiNk"
    b"fsvHN0oT5kqqOKvQPmo7RcoutIfK9R+a3hgU/Jqj1DtI+hUZE09zEzH3W1MoUWfLQGVqGcww5lCrkoZ1GISIi6VOfIsglhQLbAKY"
    b"JYQgkqVGAonjSA09PQkl5q/GEHN0PAQQkFpr4mT+DeV2E4GqTU/OMk9cJBryMjbumfr0M4S1iFc6C9peh1Bvp9BmZwhLdxqzSm2x"
    b"86DLnNpbLVceZxBx6hFLb1peTWFULdAa5IYKm8JGTuKiHyvsy2KVSujAlnRijuhRiOgZWMexK4XI2BUASukcp1AT5mAHYt5h6rmk"
    b"TdrD3rSOLbS1qcMyk23X75W4/cQStlFR6LT/WMnZt/gfoIRnM+qMHBiFajOph1CtvjzbTp9NTRLZ5BQQF3eVT5zzs+Q3tsI+hZcK"
    b"CY0weHg/ZPNEb+rUUw9b4FPX8qQZdTSsl+L2GNyNktuh9BMdUbNUVQ5dCQh9EF/1mDte0ye4RtPuGG4FDKQVim9NbTU0ET+GUF6p"
    b"rLSdG5qYCmICXqu7wZhWptkUgeM1aMiJKS6MM+IM91l/RlC7Q8YSGtobyxS57jCkOsgXp9ZHMCM6PVWbnpIHaLTjRaan0tbIbtd7"
    b"aGqXSzmSuiisa9E5h/w4aFModQjmMH6J1MP3ALK1yMhLK2EiJHBWKSOOf1N0d3QbF/vXCH0MveOwZsGU7WWcNgdhkaBiANZL9KOS"
    b"/Am9T5EnGHCY4/iL2YDRiw7tlHqIYmSK2y8bLEgk5bUThMyziJ+CbM0xB2It5bKYqe27g+YFTXOezNwMOpiQEZpYFyzc99k6ZhDD"
    b"Grl8hltttAsqLuhA1KQA7/P6kBRGd7HWBViNuJL0MnwNp1wvN2qNWmsAg+xGsxKEQVgt10VQ98lqGUS8sOXXK9WBZgVnHNTwTxCs"
    b"yqoTyn4zkV4fFfRFt92VKMjHCBcbjIiIQnWcC5pYRQGhctwOe3M3kHBbMT3pfZzFCuwjTiiPPkiK2DSpIHoB8u7t5+JOMLLDOSgs"
    b"TrC5GzOro4oe9FVp+JqG4hzoaqNB1ykLcAfyAf6a7LLEkfHkaJ4nPo2PPPDvKA+s8Q7ReGUcr4Ieh8ZUQTZ5nqJJ3vJIRt6kZzvZ"
    b"kgebZRwCwwECeHR03kfo1U3lNobx1z44bkcZLsdb2DF7MCU9tFZB4xaLp6foemm5sHMDXdsgS3JRZETGIMXgTa/lYjsob5+ZlB+B"
    b"iFTuxV4SoaemfGWNYzoBfeu9IP5VGGNBxaoo+9YAGX0au2bdrcLaoZaWS8T9htDUuMIoPVPT3JCmltIiRXMn2sJ3lsIKfKRyjhFI"
    b"nOWTWSyMc/SZhAppiYRb0eGsdjWna1e+yXqtmHpQz9HUivycxG8mt2dHGQ2bNA2uHt/Nxg6y4TkxL8s7Mrzhp6vK30gDxRNNZXca"
    b"FXVVoc3m/KBI7RUxxTKI+xEx2DbX1LjiW1P3VJKIrXebk87mTD7iEDyOcRRGOhWyugZzPOg69S487zX9fpVc6YOjYiW7LqYRNuUE"
    b"IW2JnVmmF5xheEzezTvuVMHOucYwQ6bq3YM5hKZyWM1EFrNpnqzvi14qsJJ0KSHFhZmY7evqzKUKR4kV9j0VcWszcyDSfQ2h32nZ"
    b"eWSGmxQ+lbvlrHHfY2W5tMrftpGez+ha4pgCVRxdZWjMUpeHZ+aKjvB9pf9s1a4zKbwxFXuDeL6Fdr6pjAu7uJqDHPGRNF2o2lLF"
    b"4kNWDSKKjmf8MK2hwTNexdRe1DqCoxTNVIpsgm8mqVqt2EXgbhzs5GQxGy05TujVhVB5EOKdzvm7ECb6pKEDSVKs5nHVqEdVpJet"
    b"VRTX0Bi6KmieheHKStyv4NrSK8brVbylfPEUxi7DHACKKllOzlySNQGmR62V1jfmuMI0V2uEXJcuPLqlYFrHEnn6iZMDOtYcvjX6"
    b"vXS9zUOtVnoBQq/HCLX+UqjHSPUKdKhpwcKbnWtFQPk/e61yo1kq9juEbVLNj9Ylad2iYfjVCM2UZMYPhQ+0Rk7YdFDjexoSuVRy"
    b"Ls3Rap1LacWEyqyK8sikP9+fLaFZ2FTPKsMERl66XOhZfqZLIbjfT9yGSKl/kxFXQci69hXXFJmCrKijHF5RLVHEndOPi5cR01gQ"
    b"OB7dp2ZfYq4rfzCIbHfRvbkFJd2k38laaw04zzFE3X2mtk9xDxXheH5UxaUFxKDuBAthA/+3jdqJGUmPaSaZ3tLw2zi2K6Urw1Se"
    b"lYFOHUvJLUYmtM6r5jOI2eg+ikpEtnpC8kv116sOpDg8EaqSbLPrEoaKSpJcrhSvUa4FyNWCyatxFYbUWPtWo86pX2PGrkS37FdF"
    b"WtvS+wQCvU+A9wd0FCuLazeRWicXiYwRdZVXAS/NHDn0zXyX7rM9g+TzuJg/aW3VteqAytvn41vNGSvRcdrzyDynbiX0sorp2X4t"
    b"5UdVnoEG1lfOELPd1DBnOMb0l4hBVlvmDMWhfEEhFC8Rr0TthMv4o+GWlScwVo1RBSY3fokWO6qlopy7zxqMsqW7uXJvr0S2haP9"
    b"rSAUisiArkP+l+exlVcyYCqfbeulGxxMhYKI+7x4HPQqhPbAQ9EG+1wX5vlupUjcq6nFiRQEZcCrrIO0pFZrUGmjB/om/VRpLf0T"
    b"tM5AMQJ2HNS4SouWSyPisB0ZU7cESvkttt8hzinmqLre7rfmNN+yHS6da+KFCwRR930TxmcJ2hPoY6SW2jON4tZ49wCd8rKkk4FE"
    b"d83IatgkkyrihPFOrOBlck904K3hjIr6t9YyRZKuRdQzqtvyCZlfMOsVtxdmCWoeiSR/vqAqVdm2B2VN/qxeonQL4KBXcSdum5fO"
    b"p3gNZ6Qto7JRVi+p/H/lU/EaaRTbf8yyHlG5sMfS9qxVQsKack20J8HFzrqLD7J1OY1/YubTgq52aVVlk7ASJ1fVwWrG+XQOuXa+"
    b"lMUFq6rO67N00t14ZC0exuQ630fbd82ycYfN9I5CZJLV51eVf6vxXqUR7G0kX/HtVUfO0zlh7KMUNmqKyJDwqma2zRWvbXV1cA6Y"
    b"uA2RQ9niEOdLgClcXTbCGV50VBvafLzQNHsImOPSwloLFGm9F3M52s9MckVNwp6UWwwDpz1wiYvwWqZ6WVZ+gXO5CszqHXqPwGcx"
    b"yEo34C0QphoDDgOOlxTazlrPcElceVBefuZbHYMTy/LLlkk3HhbvFkmXc604+6DR7UbY0ru5JK94Sl7xNOV6tQmLtxix+t+BojLh"
    b"UcR7vlTeSRldE+k5THhEGxJ5xyLqvI8irgV4gJpl0yZpxRUzHkn0hZS1zuBDM7pFUd9U+xiTLgvcBE+0lRHWxFCjErS3YhU9Mvqy"
    b"nehB90ELY7yjFOV5ZtNogxvSRxY2ZUUqZxHtBOptmFyy6CugJ/njg73IbkuyWd8B1HqZsnJWdke3cccaTy7bz/oZJ7uRtG/e4brF"
    b"FFriJuxxK2o9ccLIjbT/8xStoDmxnVLuFtIikConkDhpUxwbrOEDfj3mgnnKxzsLacFmQVl3rIURG2rthIKMns5N2xlxyX5L3uST"
    b"EXEivRehYz80d88kZP5Y/YbEUTWUIeR1wLugaN9uHdExRD15EI7DCTgNX4BFWIKLcAl+E34n45Rj8SPdqOsbbWmoHRZ8ztt2aXEN"
    b"lcev8e7dBW0oHm+98MyZ3dIAjrALLswqPZOYcwY8VNYiVVLAJ4SeiuGod6ReugyFZ5nS8j7gvpOVuOvaNNkW8vAYZ5e0+4J3YIiw"
    b"oeJEtn0nUHE/B8SB3ralbCwggG1QJBmIOLqjH84Fh+Gv0x9rDMNGfSwQyQ7pYwkl1H+hfy1yF1zXxy4+82197MEo/EQfl6AiRulX"
    b"JG6Ff0cC+ligxW3TxxLWoV2pYwfm4Rl97OIzf6mPPZiGf9bHJbz+a7TGK6hp5+EqtpdhGW1zEXXuIh5dADh8ZfH81SuXl48uXrq4"
    b"fIEYTjeW4Gz6Ehy7uLx0lh6ju0twDp94ETuAY0vnLr6Iba/+9xd1mB9zf67/XqOfwjtX4AV8hoaZRgbMI+Rs53Yez+HU0pUXLl5e"
    b"np6f37l9fn5+eq0O9S9sVmPKXAs+yyxTco4u8rWEKFBG6Q0g7q1D2x5GTBhFCx9HFJxEO1+Ptn8XWvvHEBE3YDayEe1+GnOGzWj9"
    b"WzAq+DhiwCcQJ+9FJPgkynQ74gFNYBeOvhuRcw96vb3oSfYjhh5AnLgPkTRCfbofOfwAosYR5OxD8Cl4GHXgUZzZpxFHPoMo+xii"
    b"yUl4HNlzGj6HOvcEPAlPIbqcgadRQxaFhD+Fr8BX4e/h6/Aj+D14FX5fOML1X1y+OD9/aN598MUrl+kkRJaxFq9SgSzT7vW6miF1"
    b"tCCy3yMBfHflb35I7ZvX6ofM7/D+D1BLAwQUAAAACAAAACFcEyS072u8AABUyQAAFgAAAG1pZG5pZ2h0X2xhbmRzY2FwZS5qcGeU"
    b"uns8k/8fPn5vs2lzZsSS5DhythVCc5qzNqRooZwWKeZQpAyRw5zHkMOYYxQ5FB1E5VyxTFR6J4dI6oNa4V353t7fx/ef33+/2+qx"
    b"7d5e9+v1fF3X9byum+2p7RlA3IFoTwQgEACAgD/A9jvACoBBoTsPGPgADwFBuAB4IBGCcEEUUkgIhUShhEUkRIWFxYVRKFG0mLiE"
    b"pJSUlJAoWgYtKQM+l9wZBLLzTQGBXXD4LklhlLDk/+9juweQ2CWwSwCAQSQAqAQEJgHZfgbIA+Dr/w7g/x0QKEwAjhDcBZ41FQeg"
    b"UCgEBhWACcLg4HMYeFYCJrlfn3xawAKuFM6RkvmIQBtY+yfMuufeUcZZulYarkr3up2pAr+9B/L/jv/v2OBJdYmd98Gx4ZCdGfx3"
    b"UgK6Xx8maSElfaby42kBcjgcvf0WEIaBH5OASQBHgL+Y5XjnuCeVCRMM2HVTgHcJQkKwzQju/YKNEDdZscDO2n+BBqmWYGi4rEzH"
    b"isWxF61JDWEYugowq4dS9GBj6CHTggQ0lAcjiRBcFJFAKRFi7St/WQpa65J4e6GnQ/FstOze3exXlYkd2OoHQMk3KA/eCFmGOdCj"
    b"fDXZGradovTCJnhzGIqgLq76DCgSFFetTAi2Ud8HoHvwkBACcLBA8+ggkq1WBCNok6zYNXap2JuR0MZdtywzLaUyc+0VNTXTcekS"
    b"aJbfib369MoEvK+23V4SHbwolOrr1RqJqPe1AgglKC86noA8IYVNwORgrqmLYwjqCoRY+mc47gEa3RN7TVW8zg4hrNaEIgM8iE4M"
    b"9FXrtOXrYj3pq0+BXBtVG9GiHt5l+pce5O0eDH0LUJ0SrBcDV+zVogCWIBhSj2Br+qo9oJdeBrC/oNU/l1kOHyEmbEFxEUIkwPLd"
    b"qycCXgsHI0PaSSWKXnT+HBs50CIEDoAHgunOJ8AXqBSYDwxS38OHjIkoYhFVJdGvav73TWAZUg8HjivimgQbCCxF6XOQgTvALFlH"
    b"5b95lBJyULLSnnoYBjiU/avr4slW6Fe0pSbZEkgwbLJFclba4eCryOb315yjAXbnLUvJVNEcWLavNAzVJZRO3vUKy7OpAReCZKuD"
    b"M0FfpvecBYwS0D1YoEh6/5RmP4JdElfj+KcfGb4CVcqOHK+leyXomCZj/ljKsDFJHIfEmcafu2oUZjD0BjqPEAml6gZ5I/ZXk/i7"
    b"8DogJno0GGLeM7iuGRQZ8gqAuAITQE8sPRhghe3dDS40WE8nO1HwOA9y2whKwMJO/gTCwVmzpRX3AseAVwCvE2NvfoyB6EYI1iXQ"
    b"m2EQJ99Yxi5fyRU9keMk1YE7MDI2dgNyDOhYgYZ07WAKygmPblijNEKMJkXHATsEB7wu9jxOD0MvAa8cDOWh7Hw1WGw3dQJboWYs"
    b"zReBnLwDhYBoIRygS9MgdsjgtDMJdNlIK4jj24HTwbgVvDWZIlONlIg1c0x1H8rgkkzwCgvPTKwgVm3I28/I9cgDfnAbGdWzaHcv"
    b"gqiiJuBzoOPUgQJwvGBFkD/gUtshRvR2YHIJ2gyo0SVbpKz7tAklZ2Zi89FuUK8WuLiGNYyk0OHtkJjz1NG79zKuXtXsnKB8sKt9"
    b"+y3+1T6L5lz6BLDcszMaiBhIPVjjDqkTUtmJ0IfCIta+LqY/AB6KvHrs6ZgvDostitZgGORbCSw7ibn+ECFaIaqhqT3BFGQVSULo"
    b"pI5GPZ0P4tq6qkNWhIjgTFfWJyHoKEVRRW0knYyVJ5TFSUFuAUu+zieeoa8Hu6hINUDqrSZ7w4kcYTMiCD1HtiwkVXMkPZYBS+3B"
    b"jvUEu8ENTl9vsABxr00U4JoKzFrgCJ9dbz+2TJvME6wX8mELEaRSpbwBLJSOUaotIlDEyCkF+q9+nhUwOwdv5iHYMB781r8AFZgc"
    b"ZqErfGWqnx6TZVKryF6/IB1+24D1uKzvZE9Px1aCPcDXARUlVhhEgixL0tcr3E+gw1rIB3gSDomERAHjPXqlsj1YuhG9Y5UQDONV"
    b"wsTItSDbgB+7YumqBNdUMjhHkKJw7G5hM0LsH0f66+unawLESDLg0gj4FgW6meXHMRMRmBBJgT3oldTemYSoftZb39db/+wpGQjp"
    b"Oh6/UmqR3HD4MCbr5Sg5geuSlE1PsNZkgmMBwfKXrwC3gNiDn2lTQg4IQYWZpQ7CE97e/FRUjktSqhCJ4wXyu2R/TikRWrSywpf1"
    b"JSMUOlZIS+AnoNl0kZglGE82NgmuGKkBfzLZEoSopFUQLmGShDXwp8VnUXg1JUqMooZoVko3AqtLTLd+WjUhsFQa3+kariRTaT+Q"
    b"ZanKripyUhVvJM8ojgmyyc1h128KWpEUkikYgUMS6SxxmWp0FfmsjIJLeuR5U6D0spTUNoA8oCLmOjtjV9WQ1MKZ3rcVmcANFtYm"
    b"uKg8lZx1SK7ve8K77j8r3l67W4zkj7mGSXZMtQxnV1or8mBENA96enl3G3lX1Az0IXyFjw1WNEG+wYHy143Q3MxzcO5Q2J2YTsLi"
    b"EILiMuyn1aIp7M8OinjxA16QkB8oPMR2T371jQtVyCQfoLeZLpXtezpkBuYDsWcXSSL26lXentG29AULsgE0A2g0CPkEB0Vc81Sn"
    b"wiN6LP34meR6RDWCI4VqOn2Ni66HE/RQLarP9od49zrkOGlblrNdUy2Di8RInP9klacmQojq0euATELCtUk2JD1XBAqBSEjjYWsF"
    b"Oq9pKqVj8Y/PnAFBJlp8TEctXIgklU2Xshaf9AUnIPlN2Cs77PSXmTrLxMJqJ48at8mucGjqU+lmBYea5sQzUqlI6xwTm6XP9tLu"
    b"VeLH4GpN+1UIfI2UKjQfcEg809jiGo5MUKyem0KGQyl2yfXDUmnoDuQYO3KHyyxIgpEnDKwRMNljoJAkLBLxhC1Aj2Whg8V5CFlQ"
    b"II9hdriKYhDuQyb+3Q18fLJY/lSgUwrKU9MgaHyZ6cRkhycsk1wVsZHSxwkoRTwWLf17WldAgmBGcAbyVmA8kHJscUDkAJRJwK/C"
    b"aiENNqpTiDFoNu26HZwCfAZhANSDbVLtgTgSwBM0W1AQ/BTyNuHiU+/nAgCE4OpO30fCuEODeyIBgY5BuB7KVxHjASFg6G5ALcRJ"
    b"YCIB16NB53+D1CNv7uinHaKeLKoi5ApzBEjzKPI3shcLCooAKA4imhAm8oQYSQWaKkcoSCAAavVwHoIVphEFpXvRewBnRUlwAEd3"
    b"gY4hnKJYeA4uFeNOBUlKb1+FNNNlqhGPyQn1THUAkyqyI5XdAP6x7wES2Hzo2IRgNEXMp16UHsvE0NtlQSn1AUEIRNkgb3+ietGX"
    b"ItVSNZRm5Im7whXxoAyDwiAwAYAXBXUgwT4askwCezbcDZrXev0mxOgnUDklCVkW6JiGN0AaLEDtg6Yic1zYKLMe/D3naoFXABvj"
    b"Dpo68jcYGwStNEnMG3AmwQGgsRyIBCsGoIEJegcw2QlXlJXcot/scRbHMF1qLXk7k0aB8w42GxYhHLMGxkii6TsjgceOKdj71X5S"
    b"qAXJhu92rv58mU4/Cw4FHtJTADIPGqXoTKpUsfBiggbFg40EjP6zGXS8uAiAA3iC9dDsMAW2WRwQMgMhdCqwXbPhoCG5WiNdL0TY"
    b"MRv/eRIRcRe2CBBMCAbGxmqkz99qDgIBow6qAngqGhq1CpvsgWb7w+zAThlL7/gGm4jBRkLcYQ49odEQN2CyizAhmexxWIgkmXGe"
    b"1QUU0INNYO5920ALCB+CJrh1mr4gViE1U1A6FmUHzZEcg4eBsPFFMfPPmvy8OuPoDnGCE06g6JJsGbYJUA1xh4AQPbYDwA7IMjRc"
    b"0Qt0CGBxeryYaEIwKWQmof4XUHWdgARKIKCNqkeAV9xp0ZpUyAHF28lgaUQ7ITUEHOiYJOem4fWwVCFXBNgzwM4Y2yJyDkbCpIrt"
    b"wAAlskumfWcTpRsIMHKLQnIPDyyBWRzabEcYUDxID4wgA6JpFfb6Dz29RaEa9RAsI4ygTlKoAGvIAWYFgp3cJnuQz86IEGFkOs83"
    b"WBkewtcRbKaLAJp0UHiw4RnMvGOhkzppCQDZEuRPeuw1bVvHJFISqVPePkX60t5KIwaCLaromCYwDlmGY+n0yJ7YAldrANckMAu9"
    b"3Ut89OQ/lYLsGGD8nYyUKopeiRKiCb7jJNnIQwenb4SuT0nVi/kA2jufg5GkIQ6mOzYG/IYYSaAeBb4FrsEL4rX2n/fGQykEZpMg"
    b"+HUTsH7H6J+TYO5AAdg+SwnHCJgpIYKGNWqsU4Nw5qMRg1Cl55oQhpm0SKinU2GgQQmTFcx8db7hvqwkvecH5GGo2zd9y1QrHpsn"
    b"tOOGFTVs7iSWHywzx/wEWzGiioLgQMPUkBNv9FwzZYQ7FCPp4AThTjBSXTME7LUQk0sQo2RN/8NmFhyQJJg0m2Bx7C+gGpiFhoPC"
    b"rogSqsoxUR/b3SuAF68DHcJeGXZvgzAmSZEKOwnwwOqMFck8JogQ92ZeZiA4MF6d9dxU0ekQa1SON6NG2t+SKugOrRZlYPPe3J30"
    b"7gVJj4Iqap04e4Jcb8EGXaU6JCHEWogkftjsHIzgC7oMOuiTZGMTTDYg1bCwmV2TObI22F9CKZwARBKkLiFhWfQVV0zVXbykpTpH"
    b"721LjMqDpN5JOmr1P4YGYJLayH9nTKpKzp5APvP1umKnUC6UgkkL82ZjfsmCPJt0TckhzELqRawhz2DeMygAsw4S7zEJQxcD//Xw"
    b"dX3JsnuBV1q7CRjADQK6eaS1YN020I5AqYWZrELZKGAMUQUsa76Tmf/q/yqrlYIb0qp1ZeYRYyLyn7pd/9PaV+xCY9z/gLgU8Y65"
    b"MPDpYJhJSxkW2/gTGNu/DCMDgB0qHHTBDRBtGuTU2Ck1ur0PF3b44AO4JqLEXXzrmrR3r/0zGClSA8BPiatOo5f/JArugziSqDyM"
    b"lzheMuEZ3EmTclnc8dSQhbegrfXkGdWUTmJVGcCHGOVgNiDLw9J6qFWXxOC+ZLxECubUMKhnIsiEZTCBIDgCnfkQNoIjjE6RxVsB"
    b"VXoeNT1GwpJcKC+h2k26wbozH8q7HkzWQfEqJ5igz6wWdkxt0UYmGAkLHRXQM6IzCTXi/3FANlj1qXSDZbgiKJO+vNNJIIU5cOw1"
    b"j24UJtVqDEIQrKOLIARrdkPDb1/rOVbYEwxa3Bn8Chh7QBscuyErIpSwvKN2eHEFNg6MlSDLsXjFYHOUQo38gB5AouDosSWWUdLn"
    b"XnTh/Sd14u7tnvr+feH2Kz95Y02fqUXN2zHamHaaRkdux4C62UqskZkTTaXm2eN5fhhfdbnL2+j9s+UnUUplwHLCNfeWY8koHGG3"
    b"+DE6qIEWBKV9JDaAgZJACQUEAwgiJ4RIkVEE3AOAfxo0fz6AJsEEIX1Ccit5U61JA2+9q0iGjZe8Xi/mmtyoGFsAZjERywIDKNjE"
    b"0OK9b6qF0b2JRYfV6GV2HO8FiwY0qOEitl2kJVi9kKM/jI5jEiJJpXYci9Sz6GN6mFTCpK/aQ7jIRaj75WSwAYNlqwZzoINA6l6l"
    b"WRlOhzkd14SocjeDcEglsUlE0B5J35wI+9kdsytYtYePAusDuh+QPrFJ1WPQNL0debQUscwk4CHLwuiEqWbAzBSggsoVMgPqHgrg"
    b"VYJ4g4xrcMmHvUu/mQtXhvBRNRKpeGBWc147f3ioW774+7mNpewj5pdPqQwonKs4YOw1Lh9jfmElkMwZPCW/DaR9f9yQ0GSAYUb7"
    b"8mnJGhFSzWIeo1r/GDyoxM5n9tZmO7W+yIo+06EpZRFWelkC6g4LflJYCQYMAgbUNq8NlDxVoMAnB9GEsb8IfdVynTCsAWvl6Z4e"
    b"aLEApR5dkIRgL/H/ExAE2KRVn2kEQ5UKH9Hxe1PoKHq6ZGt6tXgJGGQT2JBxrDPw6psEAXjKUwyHRqHwO637eAviLtgPncG0lWxG"
    b"iEw8Q7EsUATbFmHlS4+IzkdpwpPXT/JTrdvR9RokCA7YC4YyUI2jwfyf4KBqg71207EFFGv1fYDRM8SsMC5D2j292PnADuV36VhN"
    b"XHsShgrGwaqFd0gF5SGqIPVO2tBGUhFWY0yP7JL9fz0rguUbfcvxTRIp0l50XDY4CERAgwnqGHq6YtfJXIpn27nfCucpd+/bZ1GK"
    b"RaMb8w96Y/Sp/VLzz6v+cRHiSB8p/uO09FoK+1ZOxMFEP2BidWm6E+99M5wlGVjXcMbzgM3y4vs9W6X57zCx8R6tzk9VfdrwT3nv"
    b"CnTlV5c98h26A1y472r/C0tQni9eVsRup7/8BGtvf3EnfV5OcE9IbBKYm4KDaidIwGXsnwmGVUN5dLD/+PKQVNDsen2DVts4uuuZ"
    b"EaII+mwsADh7grnb8Q6Jd5lewgYU2CuzeXEJXnSw+4OlRtAdU/VAZwauWoQITbgue3BjG1jSK72cYEIv+SaMjAYdAMtXoUkWD9NY"
    b"SIzrdvqHpnuXqS6f1vndpai0ZtXz+k1cGRi1UqtyEGzpHiESyndHEqqYlgdIGpoIzKke+ctovLiui27JN7JJy+maaUSOdD2SXcsK"
    b"S/Im4LfowUAVvJ55CAONWtmJjhBFhbukjlU9vEQC2LFZ6I5Vcf7ehP4eEHp75qlIkmj/eRX3ZYGX5IE9xca0PMmQ64fqI04VlF+l"
    b"fI3Ml88vHp6gLQxyM2wP2r8vag+scyoR1OcYjXwKjAyVu8GtKo4MyVZXZVJb4wbv664JVckcLcu3vbX0yHVkL+1I2eVfZlcrGh55"
    b"aEU6ailWYN8vKNlT8vjrKV5njX4aXzl5wHvSQ5ecbeB1/0rxZLY5/oZW8NzUW5E4YQRbXdLXRVnAXtwZmBPXBXVRFi5BD5eBN+iJ"
    b"ACqwWoqIJhD8DMFRRF9mikQDvCIpK2yadSLmm4Q2iP8eYTGfgsOU7kTCpOW1CdAzNsDsKscB0ObXg+3rFL1GIuHLDx1Bdg9fB0aS"
    b"StNzSYKRoUzHhM4Ek3UnEULlksCwSotVmh6GzosBPXgn+NDnG6OV7ddfXq3TWsb3xz2czl8oDzmpwOJdVQhq2wzgPTRecMR//hJ3"
    b"M6jhhY6iC+jCIP9Z1Z2IrgIHEx+810G1ZycW1q+YSAqe6ondgATDVXdEfYvOc1AACemYulvW01+a3VP6f+19DUE7NCHYbIQ+2QIa"
    b"PfwqiQQAcMCcbkMjfEn0LSwSzel9sWzm0Pfs1Mhf0bjN2Zcm39c/RVxUi9mkdXBHjVfPcEdNmc/fGq8Pg/8t6silG7jOD0bjHFjP"
    b"LYID290DcSHIEqb3b5ZNUzL3SNp3A+rS0/xPlH9LmJF/1d1i9UdYi3/7Q1ckBremuF9jhT9kJ5/7S10dDaobeS+/6RS5nJXqRXcD"
    b"WVRszXS5hq4i8WUx2TRwn0SI8PoeEHYwcgJ+iqRiD6sGQwmYqKZIbmpI5jnh+VR1D2hIJ1wJmmvl0IOHvNq5jQXWv0NWRBbNpghZ"
    b"JCzpmRGFSGAI33HhoF/vRIKtXoGN7gmWPxmyBMef9aLo9AlZCswILAEzABt+lhARxNfUqI/6RltYjh93y/7TaRjQXSd0kuYQb2j8"
    b"1sBt8w0utkKUv6f5ScWx3+p1rxYfeRgfZUWkvWEO46D2LYIoCPYS5AtB+8LUjtEMkb11XOd/5ULwTlW1/PZHk11g4vsvh7HR9LMn"
    b"xFxTqmBsuMKCyMAdLSHvOTgGaV2EYzgg6uEe0HCCdpw4RljEuhLMVrJQMPZo0Dbsw1cIw2qn7JRdUVXJdr7fv299a9wt1LW4sLwN"
    b"jEdkJKmdjCvVPsuoDeQy1l1VOSVuevqlKy8ZNMeUQAZHx2npfMjUfeX44mJucHQIMTfXpt+Ge5lG+jVDdYjX43JTfAy2SpIa/fxu"
    b"qHRHHExnLFF/dEtXOC3rbgT1fuAuFJS71XU1rPiG+KpLgp6x3CC5EnZieN9HOpVwdhrsKZM9YgSpVKg75BY9hIDeuZObty7QSa8Y"
    b"Q1ILdwUPqoIJR5ONWoVQEhwUwVTGI4TIhWGE0VUUMQs6KPdwKokKIyvWSJ0QsVOo6dVRgSuKgNltUOT2jKrQ5xcQLwaUcGgfXMjV"
    b"t8wUmI4DmIQ5fnmdx0dBvtFW6V9lStDIaLmjkde7CpXnXsbq5p4JEhXPnfca0TrtHXSZX/fMhV0Rq3uxj5zpIFYR9ab8m3ydxm2P"
    b"M9NaY16knhA/2JivC0wgZKoIk00/4DpTI65tLXgLJNMBMmjGEBxIfc+Xnp5XIMUxYMjnUStxcBVIJPCezgLBZEaQBNgogjZBEtKN"
    b"YQt6zxwlSEVCWhUxLdJ6GHcolbp5L2dza7k/QpWj4W/IQToNDrsa6N8wJLoVKJHz4ophORKRg9oG6W5VS6+kWod1zztW3fWzbqDh"
    b"LqRHTvJ4nIusoUeywxeVTbSdWrMqjuaV1A3j+7Mrfyg8ik2tD4jKjbwyeqFu+cKxjL33fx02iL1DJ8keWB1J+Cve81pp5oLUip5u"
    b"r+zuj8KSa1LQS2kJZ2d8WVDfp7zALPiowU+iMe1nU8lsdh/F/7HkAZ9Y46Mnu9/+fCTsub/ksF8e9auxo8mZvnEsAVB7AIChHaJ9"
    b"EUoB/Sm9QxEPkO8kzknOxO4GCcfbuU342PV63ZgvDmQtyiEj4csVR/r4NvBWVqBrXqP+mvSMwKwT6kE+QNE7lg+j+joow7kcVCrG"
    b"g2QEmmB2uOInvnet0Rne3v8EaIgXbJvNUn1gevfuIvM59akWKDsBOk5eagabxYi14juTn/84rdo7yjdsA0Pdpk2rJ35eUX+mv8Xk"
    b"aKa4vB/1EfOgRTwMn7S1BiUTmPMVPXiz4BckZAZRBU41b8dtV8Nmlyd+7oXcxEre2XHGyJuQGio6GMY+PQ6muZ17NqoKMzgwXScQ"
    b"NAloMLxNACXsTuiZAJ4AgGXxcp31p530AXLvmpjnzUtr3fHrQWLHy6MwcwoCreS511Oj2sVcRq2jtQNFTs5YihiRm3ttPjDVdZ5+"
    b"oVPinsoYr+n+wYEszyPJB0/gTtTJHXdN+SZyLqPyfErC0UJQSWkZiAeelSK/n21i1MjchPXzotNu4XnhkePtkaw7P/7J0OSfQE96"
    b"53kfjd/Rz5UBh74gJ2dK2EEKZmCcJUx9dCjxXyfXH1/uXKk58n4k4YjLAymBxy4PxII/7jyVktB1SpFdv3L1opzRbCTL49GobsPI"
    b"w8zBj4XnKv4dnIuhhcgFdh04/6bEKDAr0kOr7dk3ybMb8qHlgs2rH47/+yxyeBtY1sm+b+bNOnIRRNxtQYr1MrRKViOpKrjH65om"
    b"QvUZlowQsUgnAWAbdNAg+Aar9jrAYGNsHjRhrBlAKbq6C0OIj0nXnfaifAedL0LPJnHAQENSeEySTJV2ksV3s82A2A2Y1qaM8HnX"
    b"n0sPihdG3uFyZ/35xaq5v//XMP9wM+RSf8z5r8UdlC4aOcMWt/4mU/ZltCPRoEINZ1mhwm1XCyY/DKSelS9l2XI+X9XOl7bVHd33"
    b"t2wj9nVM4NrlSzQrnp/bs29a/LXWF4x2Xqcvr/N0sMVC7P+yPv5oC+svt9fpGPseW7FutNYlY5tf8TObB65ZiHI22iNmM35oIQ6f"
    b"O760DQTnZ8Y2RW8DP7O7xq//7n5wNOTuvvZ/Co+1lsbfeRU//HG9/PX4H/aP8MyG4eMruQ+2AfUU2Rl+fDutpNl+7+6/ow0DFb9v"
    b"xOl2zB+d9VxbTDmW53L2g9sIP8bx/mvzkY//3N0n/qNlJDtlI29ltOFzbH7FXsaJZd5SQu0u9OUke7YA/SxsaEzvM32pykuxxHcJ"
    b"pujQm+7Ygs4lucqioF5KdDvaeZf5d1vXHE+fwcyL1+8FTofM0M/asnoORyzwN8LjF9pWGD7HGZ7ynn81NGrv3Nq9DbiYPgqJw2cJ"
    b"d+k2Gnk1H3Q1ZtQoH0zNV0wbSTrIkF96mcoc4mjYFWY+Uq/9HcK8ZRPPZzG4kxuy7M70v5/WhWlnBowPp/tYoT2O2GdpH7qwPGLU"
    b"25jnwNr1mnGxoW3PlFvBfV+/AxkQHXZo5g88YuhNS4VrXKZSE6dOIOaQ4HlcZNLERlD9VZbShSLHjdwPrxa+NgR2V6CV81CkOrkD"
    b"zgqbH1L028NKetv13jQgGuFROvuNVPSOwiolq8g4m68GZ0WOCz67ci7cyu5I+ak45eyGZf++3JnF4eK5Ba+Ib4ylGLVSG05WqPxS"
    b"gfczzOkbfXkGSXW7qZN7Arg/ym+oXPGQNrrMP1X87eOV8ROPNOZ0kGGViZFq+42kdu/c02AIHWWLeQG8M6frhd1IOigwsZPBjFJa"
    b"mUl56ziknT9YzSvoL7m6xPuKC7bBQ2dcVFD0WHpvSgHdDQKUtIgQsBDFA96gj/sy05lSpWfmmFY9ISU9G+f4+qoOservidVs9cbR"
    b"EJppw3xXqbY7CGZbHc836Xr5hkTX3BtEFwrfQP38CYylTVKUsiWv/nWm8mHs/zbib7M4Zc0lYhuc6S+ft1iZjvtsP7fN8UluT8aP"
    b"3vxl+yBbYzjy5b6G0exXZ2IMh4gHtgEOy7g/dJ/+2pGsef4h4d3Z+7YBz+9/fDblu6IwAxn5quUnjzEW19twRA2aXce9WQyPQgs7"
    b"Jb1Rupso10pjvDXblxgXGC88/PbkXMUa8eU/2beumBSaD3DjTo7HWR66ruT6i9EZ9OrHn/Omvw2LvjQucXmup3qco4EJMNhoYhuO"
    b"1SMeDV+bpGlGKWWeQLBx9Z0Zp1AJjerJz7jBqhxtEQKhAWCL68EA/QWwMCv/mF5YOOUT8WJ56wbYDArXPRcnjs5Kgf2KrC0f+gu0"
    b"YvnzTOvqQEaNEjk/kEjzF1OQC8xjSC1+aLlhW0d+Ct8VmTb+rJe5OHSDKFnx/PnSa2MTDNegGBdw7+XQOrpuWLWK9bK+xcHZ3OHg"
    b"gELKzBvrsViaXsguTO9Eohp7ZUBh0e5weKTtCbPmpNiFlPjkAp76b+1/DceXvr9sPGi2DVR+OR1ekhZl3aZ7mjo0T4tSOLmUe8Pp"
    b"tGl74Lq76bNfkIA7nOuTv12NpLIO1hzZMI4tv33Jc9+RitfGQ8Mu7+LaBkbKbhmtb6X8eXkxZ3Ttd76vakVCjGhMbEag7n7Sc09i"
    b"0XrVsJnu9d82W/bbwFdkvOTh2Kt1HVqTY76j2bw512fjPquXL62X1vbrOjAlwqwS9F1nLERxUDJkCZgF2D01DMH1vvGzR+rFCMZX"
    b"gpqya736S7eBmcXRig7/GNpGbUB+2qurA+VbD+8Nz/tVTDiq+C+o/a2NoU3o2q6Zlhe8umz1j1YY/wK6zXsbqOaf+EM5+Gzz1Jkt"
    b"zpunpQsmgQOulL1yjmkYl+qdO0qyYq5JJKnsRPjOrd9gwDWNBGaQSjgN97SAeEgtb127b6B4TSzV0mhBWOfdx+4BMTdecW6DAuIc"
    b"KyjvdSlt6HvpD6kyIVvTT6BprfYPOBjIoFSohaJ0cwWJuPkNIvvdqdjWt4YxHWXmKVfeZ1YeXopkXkBi9pzmf/+R7/bkb8DfvvKa"
    b"uVjZrQ+pC/y8d6bvbme8kV1cpi3Mh/kP0toj/IsziLT8On+pLPch6dpPHbvlS3fbGK/iTudFc2/YWEaqemy0DUu6Xiv1Who/ZOz5"
    b"UWGSvfGPnYv2iwbbB7O2jeP8Ff2v28Dv3yWb4QN/Ro9vA1VtX6O29mXM8jVstf2GFjkmYfw6XY3AwzyO7se8eGJ0Ydz+L76uaVa8"
    b"s0nkWpkmmCu8OTHJVaBAyMNKywHpASQ2T7HDqzQxrchwALTE6Ec93/8qf5lLF5U99YIfMvVxeavYQCtbTM1qKMRJwcGwSoHMkS8W"
    b"fou+g+edMGAKTxkwPW8g4pM11qT9e8N/+GwDecc+ilHfGun7eVTd+DaSQ/FiyDSo2iRVaHXpEw1ycxk13w2VeCOVxply//tuILAw"
    b"iHkSkETtUHbNXJu7z6lOCkAtn8NjG8b9fznvUbk5ey4keVxrr2Zg/0bbcTfXzLmKocdhP9bifA73VD6WmP3zcnxioajo6b7+tq2Y"
    b"jrtr3XmGZuddi35d0b2V3fisLu3+leOBsZ0RpbWt3Bf/ynCZt3ICNzz+PBrMPvA67tiDLBle/M9fQRUVjWuY3IWAlwvRo2a3jA0C"
    b"2mSyKF0+dzKIusqG7HJvE/DJ/jJp4Rpu+IujDZGRsy+meZzm8diV8nKHE9WzL0tj3szEGmx8i25e2Ab87k3OF3354bPnen1p+EJW"
    b"Hgv5AbER+2q6wW/8MMdYUYAeSUcDdaTMF9WsB3uPKo/yfdAMtyxRn7/P50YmtoGa3LmtCrLxC/uh9/y20ZGC1zdifdKD+nkX35pf"
    b"yQznx1j3G383Huo6fKHRcLgxQ+1o6cIF33KfggwiadDe1ofDz//R5b525OZP6gfRi5lT5hxunO3uW9nDvKD/yVzujM3Pl10ON9kf"
    b"8kOpsBuIpYeMEhRqrCbpUqmkKn0cfxXGq1wCODOVy6JTC3zZFrV1e7VHzfm7S1NMdU99WVxW+cq7UhUT8/3hjXx5OYMwWgclpnXS"
    b"qoyTO7/JoKqbwzk6/svYweK+gaz2QIa65rKF+LV1B/YNlbeHBpYWLuZWP1B6qVy30H8TldsMQ84vFLdHzLNePvdRprg2gLv/Mb+h"
    b"wZLZnxW3yVNcULeXXbDNWDaL9nzxRR39J3dx4eXYoyPNeUO3YygB3MeBLqb/rkQPUwxvVfluqmBO4ivrekRG6AalXURqWG4Ahmjj"
    b"cae4gTwuRjaKF674t6S0ac/HjWuVv+MNDpk5rptpmXe81DzRipssv37VvPaXYNvqNpD9hcSvMPhZshx75YiPSdM/uhHojyWoS9U1"
    b"u7mcCa02P6NbDqe/8CHdru6dx55ocIOtMcmOpwZl2NrEIjzmdM2fgfzeMdipnuuSml5QqiA3gguZjzs6e6D0xL59m/YK8cd5G5l2"
    b"a+v+pq8bb6g56FMXIwwrjVedZV8Ghir8PXrd/rLCg89ZlPKEZr/d9PmRz8x9z2kLeoFv0+tXGdSXbgZKETMkTv6Cj6WD3pCBlz5z"
    b"05B4nlLMPYl2qnaW+/rd3E5Qh/DKQItzwp/j2tg2Hvja3tzNJGwhdan0hZdx69G/HP0LZ1oWwwp0sm/qKniIpn1iXjhO/J/moR9X"
    b"OWsFjhusbcB5dYHTqlFGnJo7x9vb6bceH1GdpDF38rBhUvPHvzVbWg+sih7PZkfU1Y28cx3gnf6tS040Dh8KnuAvXQ70bOoy2AKH"
    b"EL5vbLINvNER9o4L6BvY12fmFJS9+sf0luNGxTbAHeUttO1XfjKS+a+CI4bmn0TUku9ys+uTL1Z5DrZMS2YnWiKdcf6UZ67oFcaS"
    b"srmzg4n+82nOiXnq2Ic1Izw7y+ts7bhTiXnjxyPi3m1Qt5C1089Y8eqPX/HNuDf23lZ3RynixeWnwy1GlR0ONJ6ZXrmk8HhWkm+s"
    b"YZK4lK1+xC3E1agm72VsE220skRNajNX0WBeJsu0WCdQW8q04oAqB+uvwqlTsHLNYnhOq9Qgxk9h8Lp/xKo2jve/ju1bLmFsaVw0"
    b"K6+4pUspvrNi9GbJol7sJDDeI2LN5lV+4SuCMfMqGy+ZzhP1OfklfMvo98tPW9YD5hHpg2sRv/0Ohjg4CLUfPaR7vICSJRcY+i70"
    b"j4tHo9zzQgbtaNLBLK28e0PD3CGNbYAX71b4E8fILzDvY1JLThnh9EaOlK2f+edJepa9quqZaJOTpEwLlYd75DSKuVLFuNMatOeM"
    b"Gs3iG/NG85u5Afrk4aob+dWP+rPEjq1p3NsGbJZZj6KMaXzdnoWKm0Pl+DyP/JUz6yDv4orbA3RqbW3r+OeFKFlzX2cmFWLmo58q"
    b"sWyDPG2+Tt/XdkwclmJBuYX21RPtTS+qOIraJniOjVJjlLIduj/zzqdL7/vGtbpmYhUqJprSd3718r+BUg5vI77PYEvun0NhV85s"
    b"GT4Wc11bLdqqsPqyFvv78pko1de6N82mzexHnurccklYhvKgDyE6KshniVR61ZOSU/QahQXwBYWQkqrHV+Dsq0l543WKFWHa5WLY"
    b"ccm8bTbGzOqs2emv6JiYrbu3jQz8jd7ejiu+ZEj9VG4lw7ir+PRI4/W643mUf3Wj/VjGgsXL5qqmdyvXbQfcruu6cv8NjL+mGrev"
    b"duGzWPHGX0q8aHxyVvnZqG3gD/njNpA7HLYcs8+QdSA/9MG5VS/jxZwXHDmnQZc4iGacuF9eYKhclyRXZN3fY3q3dRdkT9zzBGMa"
    b"7qwMIjeQvfRUt/yIGylydP8DW9zi97aDP+XVv+vWMyP9K35j2hVYh/ty7S9HyRsHcL8cObY31LyucXrX1v0r1vMmd2In69wiKqw0"
    b"tvrfzb+Y37XVddFv+vAj3WcGWrSUrzbfPSLnlim95ReOa+c87K/ofiRxZU5ua8QwhlFTZr8eNG0whG0lDxTbGJbJfyvO4e32jL+D"
    b"iGmVbacNB+Lc1VT3iheUBWD6iSnv4moTXWF1iBi/vEJjo6FI6qSCh1jlhk9/YYyW922O+m+D//HNrlbceuRx7nKwIEfi+k3QX8nr"
    b"KneZ5/7yXxgOL7tteuTUmsZW3TbQtNuOMzLKe8hSOLc4NDzhCOKPpUq+Yf1U/XkalvEmRpVTHnGP90LCeHWIGJ5bbEs0vsEMleNW"
    b"coXLMh1Aj3otLuJU2NZQ+CvDqx/cJj7HfpDPG+i+6TCpUd78O8CrcOfvJWmCNqJFCDYmoW9NLM1qLLj6LrOrekt+cys/fXD9+9Wx"
    b"wMGSfk7mJSMfrw9C2YeP1Bd6Gru4OPPPLcQEd01vBiJiDM/u+WUY4zt39fZl3Fvjf5cqBmgP1O9zs+yL2sOH4w/rc5wiNreBO77c"
    b"ow1EOfXvbYcGm9waKk0zFwxjDaZfMhYOKA4NFjKCdIteVPZT2Ld9jlcENfkM39/UH+ZkKM8sUou65QSc1x0MmN0XVvxxKyL6nwrV"
    b"w+OneHdFO7eevQo1vLpWfcXda/bFZbYbX2wbUEBSP42qzf15Tqv6c+RmeLCx8al/d2fr/ru3oQyRG5Dk/AAD34RyTOIKj4XK/dSq"
    b"/3y9sRTz6W+d/cvepS3d9Idyfqa0S5+yps0o980nPz6Wefplta+h1/8z1qfrx6Mjx7OxL7Kt3G6KELx+QnACHdaSc1N0NuZUumZn"
    b"7QYE/3RtBZtVlaXrsybvnaVboFXOtVW4Wj3budl8/Iv6Ms14PvoPy29gtGzBizayP1N2fmiqMOtcvj71SYQh9emh+hPhXY7v6vLl"
    b"u/wV1CjNKtO1X9tGhr/KGRfve/x37O/41oXkubCnnlesKDaR2bw/Qb+zNymXnMptP5W3TRzlfSqnvKKVvr87mjZasBCdZfx8kSNn"
    b"Nzjsqlqlao6s1AizYM477B/pyr3BUrb5ADjV9Mh9HTEQ6YLZ2fEwGujQ9P/u/MY4jT1x3Swuk0bGjSwr3Rs68LjyfmqfjlPvm6zo"
    b"my8fUl8LfxYkHlovSTr4zSnphLmQoAvSNXDGwJGJpbGGsYulSyCL/a+AAln8S73zdP4BfeqlI8sHP6w+s/DcSW3FBp4ZRO03yUbD"
    b"RXsso89i5oYaF5nBtN7J1vC5O1Muz7jtKtRQOVoweWVLNzuoT+xpmf8x8oWpH2H8Lvu0rHN/az1rF/NcXAONaR0nHAIjI17GFbUH"
    b"aFVzs5wKA7kSQ67WY3WHZRiq5k5eaq4fM6XkpIgtuQ1EbvGtPcQAbruBj5tr9lHu7yBerLN7wMPdfw0Oh/FjwvV/bAMiG1m6qbNv"
    b"xTybZ6/7vfu8lV8a+MDVRKkdmGzZoYYxzRahcVS5vu+katfB7MyN6zev1pm22q9/cBlcjVi4dzLr1HNqMdhappdXSkwr0n47n+6c"
    b"u5i7DWwD6jd4fMN60wv2a/Yzz+dKXE7Mb3Z7mf6+4qjrN3W9Psm5of/Bm39oScL/PEDHfz/6ZP7FoiC6e//eMqLtkXjf7GevhlzE"
    b"Cvr0+YflPm1kuY8nkU/Vs3ico85fHivwPjtH/9JViDVZG/1ka09sLWNZh/KhqkpkZk1gZIBGXD91QL0+JDV8/gWn0FWfOnwhy4mr"
    b"z4Luyr9rwbxfvCmqVcWkT5gk4ld1xBJ7z1OYxKBwHzecf4Wa7YWaF+1RV/y2AUFv0+vunmNnA8bO4dz9ydUBFl5fx15XcUxs9tia"
    b"3uFVqsupn60NprX1/CuW+HdqdijNb6NiKO/AxqT9PivuNsDSemnv9/bHY4Uf5m248NPPSxe45lo/1vidtC5NP251lHVnAih9Ro9U"
    b"Do2qyt7rLafUyb1te/rFzDzqUmvvhzyXuAvpfoGz94d0G3UYrVvTstLzI/Cr9jFrFUotW03mnG3gaZ7klr7xWjeU7123r6Z/scT+"
    b"+L0H8mD3oq4+ujBQl2u0FVXt87jr0+KXkx/D5wKG59/lh3Yvlk9E+A8RtWVH9uMCjIvb/TRAV/xp+E7fsEue/nmxfROxdcU/05ey"
    b"D5l7GVMeFEm+uWH7LvCFxtAwjZa//ObH13+WPg3lLIKUbVOWs0vcY6DkhHyXSH1JMzCktahtGlYx09Vc71j7qMDX4X2peEbT2KT8"
    b"TcdlT2JrbmU+6/lzLpmlygwxLmm3Vh0S9NbgdtlaG9AiS1Omvjd/jDN0Y8K/91ZW71OMnI07eB6mvIAS1GWKnsszJEpeYXgZ5IN9"
    b"8S+6FZfX+GslCHdBsw8u+8PmkSilWKuPU0Kb75PwH5sdxl2rb2200XGs//y0sODynrmr8JVzIUgZcnXQUOV4SrzxbRzlUzCXsc4t"
    b"kz2qCpoScP07dcCO5FYFKXkZ0DbTKvuPZGj+/OW/vu9jn0PBqkWTn+ztT4meGmmDIXLRh7CvDfGcS6NJVnWvYh+Ws7RovvmM3G7T"
    b"pgeCr34b/sz+xbjT90WpauFJyeeg5nH+zwXHfQSW3wSjkO3ilNO3t3VY3/F9hv+6UcDaB9ssyrCb48204a3pM3N9G819NV8U7myG"
    b"6+T+b6E83o33S8eU0qVdfvkYoxXLPys3hW5tPuNNCos7Onn1a3L94/I424H87MZl/33GGnffnX+3HIOLcJ6u4PVh/OJkyCd3W4cO"
    b"wR5v5e5THPmtxBg/+zYUz825GHvBu+Aq/u0vW2/TbWDl4l/NUrckZ/PMvdG+mUOVDh4WN/y5KZQykC+f8kG/TyR6qvZii8yNDZTO"
    b"F4l/UIHYWIu4bZJt1DxtPqhKFaz9GSKe/WmAG1CX09Cp5ylkGTf04bllNdyqHOQDKHuphVpN9X4PBJ/2utB7i1i08F2pt27OUX4O"
    b"e0jO5m3I1OuFpSsDPfEhLVsM0tM1Oa0Y1p7uPHNW5TagSSse0roi/IeI/Vh4avajdGhd0O314vqNbSAjztL7nlb1RuKs/kq2YOPo"
    b"e6+YO8Oz37TrPpa2h/772r4vNO9Cdgzml5ea556Me/7tQfKvrt2WDL8yXuWYxFG/OVSisVBa/epXYPOBOIZq3vOlp2peS4HcUeMd"
    b"HMjJvbRu96vAhVmum6w8epMxfFS5n29e67kwKvHT9gbrsC2u2td/Psh6xeKnW/EPbfnvZTvskeTeyM3VIViXcXDOqxaMDypVWgmH"
    b"RoHDkIMCPiqIHoonMd2G26QaKiOiMkJ0rXjuLI2kIfJyGy2vpWGXBgxpmRxzZ+r5uIQmgza3gj1PNePdqhewX3rzUyKZcurDMska"
    b"q45Eyby2Ms4hA2qBATU47jGbm3IuJVS+NTd951dol+XQxb6vtMZqdCzvDiiT92jsVcUQiSm5uQF7ZYO+x/uR3NdluIwafzkHIvWl"
    b"E9PhWh1XDpFl+sFy11DIFLVfr9DeXercaO6krJZe88WJklXjhSPFxe3e2wCWW/5BH5GTb8MMFS78fKP0wV6JAmX2aymtPf2heOLA"
    b"27+jcc6x24DTnfl4/h3Nq8cjlmIV6u4HrBcsbT12y+aejjE0caz6de7LCHPuYK35kdkjEkNfIoz9o/b9PnNf+eloWUcd4ndpQl6c"
    b"kK2aJ/fltHxxXaj8LcnvWpemaz+rDpm9EUz4YubIN6Z8cEmLBsuvvSPjwcYLv536PHLiZFBTyG4qdJkadz2PIsNFvoG50D+Mx9Yl"
    b"8x4n8FdDsrX2VmSgmwNsj4YdNfWx9XuPMBwBtcOBSHTNzQUxXm7bK2DzuynRh7SfryKiS8tIxeh+tBHVTYDv4HoV+8JQ2e6H1h7f"
    b"52vd8cn8Q/0zX7NsdDINa6+3oIvQxZFuuZG4njpNG4zf0FDAbuMf2lUfzYWwywNrwlOcJoMXttvAyZlpvrFFK//74E172oVlL/2R"
    b"4o6Joof1I/uayjVWv0b7l65w7prflbrudSWrjcfcl3Z+jHu/YjCTscAs0StdecE5uNLHUXvNC7os/8+91wPjxMqjyksPZBdHBTNZ"
    b"pq1DIyql1f+WXx7mMotzS4uxQ21Ke2Bf1l1GozhIuxecQwcUX7R6qXY/k3wj0BWGkGKpWZ+D3MHtEUGODKI2FY8P7pZDU4uJOXFV"
    b"vdXV5Ix4fLGowXzLWQ0m1om6dC3TojrIqeru/H1tf53M/ebkgL0HVHXkHknLdztWjqhmyh1VV4v0X5citNJw+HzWD4zeiOFBhjyD"
    b"UaeMIw4m1BGoFREWDTRcCJIZafH2EJZrSEtnZIqsHf2Ex6rvJ9KKteVA6+Jtep4ymrwNKFJq82qeqHKQR1MCuYdzQtPt/ea6GmIl"
    b"CqMdjE9uMuIy3iVZmXUFEu9cGdbRzevlyjO7TFysqA5L0/cPMl5Qv/4wb1bnjMp3qrpmbAMRdaLHM6fMxE6tyXe3ngwq+Ok9+AU0"
    b"m/Mx42VtBRx1c6el0mKQr0P5qqW35LuChvWpMxuF8XlGs7/bWA0jTQqUCnV0kFrAiXvfwe0vQQt0s9X++hOcV7HXhqryW3vUyO2q"
    b"IN55q5o6RXTarmIDr6b5QQNQJyP8GxzMZBN9BKosG/RhNiCUPOA228APRIhlhSUZm1g1rGMmBH+P9rrh2LgN0JZCtPKPqR1MjAls"
    b"aNCPEfKuDY3yWfGJktI9lofmNfeJRe2Z5XOHnr1ujV8JjmBG9ru/GEY/8sCr7lYd7XzIXmJ8xnBPZoLe0YknpuYC55S7bjImzsr9"
    b"bmrlOHmW+iRRYny/ZfnP1H/5tuSXr77XydsK3CZ/rpwhtq/LxO7FvOnDx9L5N34bVT+6YfSBFPbyPO28c5d502Io55AS8hwzSEPc"
    b"/4OKlM4124nhoPuNcoOD15WoKV+LJeehzE7YIXMkR848xtB6xUlyauxbz0lx5BQ8XVM1ya7Nck6HJOo6325V0F2NdCiSWRwcIxIu"
    b"ZAXWYPopJUyPBRE7zY95JTqZhS4iwfK0wxgdTyGOxjxoz448U0vwx2gczVsaUUkjuhAjgw7626HLEuzHRMwdcBm4QwOGpNCLQw1W"
    b"rjjctS48tk6fYzxYmD6Q1X2W/9Na1BNJHY7RKmQEmMuVSd3BhWbFK+GxpQxyBksN29hOtf1LJN7BI3KDhw/6PMkU6l+a3JNUae6S"
    b"VCWJF3Ra7H1AlAQVIVdbLqCs9Cv3hbEsJ58XcGLi8YpfQe9C0ODiIY2oINHjd0YPBvJ2oDGSZoijyPneSpfydb6Va25xqIeD+1ws"
    b"fe9MgkPPW7F5PNzmew/sSvr+wcRotdRc7LB1vf3Y9TyWiiRh0jW9G3XT5wm9cY6+t0XGtse6lt7JRz3AT1WTfZHjUJo+td4cKGUw"
    b"AwLBGHu34N6x6c9Yz7Iavvr+ulp+61NyxQuxv1Vri0ljKVT/40i1rHHmzX+k5nn16qDlvztfomO4eeIYkVIo+txtG6jNyvvBWDRH"
    b"UpMNlUf4f2vmB2cqRvb9bcs294ElPy76JKgDgLvKUhJeUNrlz+PlH/vx0rbdGqRmlxxqSnI+R0rjrSpH7d+cIPVAasrnHEUAkIyG"
    b"QfOxXPM+6d2jcNGjOYYP/OHjinu0RSXFL2QR2ZPnHTA56OpT0nIy5KoKuDSykLSoTx0afgP9JyXpqn1lf4CUsSSjlJF2DklDGw2i"
    b"pgR9wc7YUlw5nnWcx6t8XLB+zl11yPe8xwYGD27suYo3wgj7PO6ohmduabWznHGUgZDQnrkogeBLIKUYPm5K/0v8jXQphvcxKT6q"
    b"e/p9dNXYna2ZlQc4bjlvjdHBL15aVXm6UTAPr5uuP+rUj4HSZrz0hpRlsiibr7HTj7aUZWa+Gy7E7KH9HbnT/16+WDVQUz9f32N/"
    b"94yfBu15RsYM4SfWOcfxLw6S557M0S7Lt9GYklagh+5exyT0MSV9rfy5ot6frI2vWflXqveK32ihWkT+tNDrqf6sTHYvOlH7ROn8"
    b"GB5yfLdvcAb8dkrSFHQT6r/CxH2WgR/qxb6Q22NJUQ5zORuWtmOfNLVvhjT4fvtx9f7blOOj7Q/KLkVscDqGX5bsH8lDuc60prvq"
    b"NHLk/1qDS2duyDAMA39r0ViP7/H6ugTzjWlhHGPHPGrhv3mp+YqsA1CVDSWVlIIx0+7MtjfHRIlEWo7kvLPkvIV2gvbaECI0L03R"
    b"fh0G8TEHpLx7dBhCLvT61qX2zyUiD2DGUYZUqbuE+RHrvpwLSHI97u2bWwjeVia6zs+m3wajgeE6WBHeZ4rPO1p3kaGMng6lXu0p"
    b"8TcC9jmq+6uiay2qiiP3rOMoAQF7LEqS4mgcUmS//e2YQ9iHl+Y0+FUv+x9rHUlWtjTwN6R+AvtblaqScPXztG4ghL2n93ctu/gO"
    b"8fhQbjTVKq64iqO01KHjgHOd4dg9B/fU3JmwYJ5EXI7bw2Usfpdrp9T1RvoZy7XHeDce3DSK05F4WrBCexl9hssoK64fdhpuPQeG"
    b"cMdCa0qAhfMDyAmU62YBxPDKE+UzCNx4hua9jE2ylUux754W1Talk9WI0CnrkUpmciQ6v6XI+SfkD6H6M/xpm9fZWhhtHq6meVqc"
    b"cknz9pP6sdZrZa1wdcsEPTUnplVcTojgEw7J5aL9FRs5DTlM3yop9dDT5XW/2a/RgYsHENtA9wEX++oXlwecDDT6Z8eJC+iaaZGP"
    b"ujnTj5BM+ke+8d3I+8osTePA58Jgk0t0VUzTU0Recap7cjJaNBWzRRz1as1fTNyVP8MMfJ8jA/YhK3+5e0M5zTlYQOAtRJ2gqKGH"
    b"iYT3FaLOZ1gfGsphkeTL6CwSjpHpoO2Yo/A+HeN7FikjIt+JdfCAr5AlC8StCviKSj2drclqAncRtEBrOvBzHlGErsaFIkuYocj1"
    b"YDJXOGVhz+mh7/FnhrXn5+8bljYVMvwH9w8mHRyU6TFrnIZ68jN1ONPGtMB8l/ltYHqRqh/bfK7im+dgZFNhZ+AP7aYSDbsq5iZG"
    b"96oItf459YP8Jh7b4Bx2kvg4bcB1aWj0k1qmfAaHNbH4Slt9RH+kUOyAShbaT0OOF2As5+FafIPoxjqjfHg+cYJs9ZZe2F8mvQ5l"
    b"WXoFX8jDnF13Qz+UOXDCcR4bTMkRJTjVWIjPv9HGywxS1J5Ir0IBxfM2iN7w8AUBgz6myFdczdixf15EqtWWXHmhyUts9NU2N9JJ"
    b"jstEnc+B5qDO5wqcwPS+skk06JbQloOEswBXXzwPxVqtGltz7v19q5ldmMmqH7xv9+F+Zkvs36iRPyV4MwtPM8dozt+Fh9dx8xEc"
    b"ObsXcj7PCdU9N9Spzun7u5/tSnX+qXyUHWGWZGw3eF1RtUV1sERQB5F6/jnjgyKAW0K1qPJnBATyxsYlM1ze2p8MwPSLfUgc3ONt"
    b"I2c/rgjsgWhAggle0ScADYPe8Fyb0J4xXgbcmGVtTAuyvgtUw/ttmMaOif83Z1hdGRRYoaIUnnEdbDC9XN+3WmP/GHCsKK6bGfAu"
    b"GlXDLunQsKqEei+ClqstdU8A5VZtwWz11JYd9jlgSLTfCWsFTyiX+TYsQYeyH79MqB1K11u4DpTdNhqZmKfqajXSGoXc4Di0ug4h"
    b"pu2zUPyU9ymxQzrHD76LfnkwK8aur37ogUHTvINBMYjMpCf73NTK+8bGW0gbSmqbKJUnqrQnH1BC0EiJYApm7CRGoUfpbLW1la/z"
    b"L7XbktEOvuevQQOE3VMKWkuqv7DhLZGNM7KFKxATRMNhzCWD5eXmxJLqDRRL0/fgVwEU4VV+uzQQIhdGZzSzOYf9ueQzpPGqJe5h"
    b"yNDvejYjVXNDJ3n3NkC+QnjfZmXcSr62MJR78FBLWkPDFVv6jSqkqrl9K1Lp0eslftq5XZBDvRJmyJT8aBun+5BDhN09UACAHBqU"
    b"fC83NltaAm7I3kszd26v/wqch+VwQdWMWMjbFHFcgJ5zkLBq0TaBfPV1DeCGByavQN3mIcM9LE1gqkRgpSqfLQXKK+EGW/WBKmBx"
    b"LrhwMLFqBPvaAIe/1qXFiVL2wvf/9SMFV6glssjWxuJB6v5yQ8US93CDSrTua+3+73Os7xsqq/ISe8bl3wbfxzAvaBj9iAzm7ss4"
    b"oJYxUBHU1Hm1jxkqZQVaqxtL8NoTUgV6xt8X3mycEqbdN65e6el3emH30trdmYsddjVg3FBL7bZLpyRfjxpT/5t/pef4ILJFmot3"
    b"duwi+ez3KFO8VgZfvwwD37u2chex/4Ghh8AS9vygOChMlQUVgnFoZIIFAEAjZbCVH+ATSydRBCivfRxlklcTVMDbG61qfXr0QO1K"
    b"3kRN+fn8o8y+atMY90lT8yfHqMGQKJhd6/VDTyB9U9K+1kd+ZyyTx95Uln5AUHvbsDc+DbHP9ziPSf4frq4ELKm0bR9AEFAUFTdK"
    b"Q8oFTSSDLFsEt8gV0cpME03NpU0zpymtAy65FuaatuAaaqVWltlkaJvaVKg0alNfVvpFZo1j6aiV/edozcz3X3M1V0cO73nf57mf"
    b"+7kfKm5nmrYlt2a37K+tHw7eafXXfq6lE4aqtVzywHkGoT2CKd47a26T/rmQczk7dGSZ3zaR5xam1ZsyFU+z52WuMRo9lTN/mWmc"
    b"OvCb6fNb++IEC9PKF2bXrVDi9uQx9cfBPOQpXbudZTZUTKYFPguZn0nruJqawA7S5zSM62aqfBZuZruHdq/wxHVEbpgMA9AgwkcQ"
    b"ZUjOj9GQNsSv75f/vsh3b1RkmRvXJ7uyvuY0cYDp9eySesL0yVxbMXHI07Ar0JBY6anb6NIebLt0gdem3LLS3NPENx+Jexb5LLl5"
    b"8nrHnqwnju5ni0ai45LDmU/uVv9Clg+fYYyMbuPtWPr7xZXOzw28NsF/T2cxbTn+YYf6JY+H0s7LKzJ2poNG4KoExBbWIashyp6G"
    b"OhMzF+aomeH+NUZjG3F/YRdUI3fPiK3TLurkMs2UmfYXAa7JNY5jAtoseEJD2SK4QS6O6ubsVG3AyJjtJYLb9GqRSj8yIYg3oHVm"
    b"/fitMprBqyO2S7YOfrxVkOSymH5a3apCI6i5KHja7l7O0p7oXsvSRKrc1U8mIS36tVWy88U+J9rlxeaKEtNWbrIgBFk1YVaj43vp"
    b"rO7hIX4d3exm0eKeskZp4R/PRNzy0ShQpR+/8j8bTBftte/hZfooc7KrpyMiSyn5Mn7iiaM5X5Tu/b/xWZEPISXs3G19Int4XaQo"
    b"b9rQuZpz4Ut2nyy/g2bbRU7oWvBaSuBiUB4q/WoCC+CS6F7G7g7TVplXnwL57hmmWFOgnTiO8pL1oJMrtCMkb0X2XNZR9TKv/fLC"
    b"Y1vc3yRsd/z9jdOQXzUz4s0DyqNps4z8jGjb/HRp3Gsoj9Xoneh7geVdzPwpVnlgusmDPHtr92TOXWElJDWfxl32cysCnCvdfUpz"
    b"C3aYcQgDGN8Rt4LSkXDtfp0IvxccWsZVFhfcDS6QaEiA5VtRrUiVz8ka94oLRwu4Qrt+FUQiwo1QN0mnLmzZQuqVWKgmAKf1X2pM"
    b"I3IYWF4UFRTIWfFmyJ2kmXhLnTDXLUZ3+0I3ZjfeOmmYef6mvuJKdvYT3JXeIB+t7oUXL97M6bI0fE3/xfZzQXXnXd/LAWhF5JXP"
    b"emh9X/auJmH+C3qqsyFLs5CoFWKmnkq3/No5lliyUXHJrGL51YxNZKV/wTujEvdEEPSU42U/JQEvjNHYZ287PyewKD30+pRMapyp"
    b"q8am5yf5/SVmUJDihvApreEdya4PcXGjnoajHOsBFbfAcaBqHOQIm76cL/elSBvsZD3eN0+vTM+72ul8zjl/4xgPAAB/gj1ihcpV"
    b"lff9JaageZjwnGsqgNi7CSMX1qh6rexutvNqIWtGuxg+8gs9FuX9JiLe6xtgS1koO0rfUJ4wJDKlUD0eZZ9qppRKaFy1rGFSFO1n"
    b"6/LdnWXBv6LPtQkWyzlwanq8BmpFU2SqR+bDS+pDvypqkrDnh6kBD1Z0mLRQ8qyRIzphPpEQYCTqqnooAKCD4E4cROvWouiyj+sO"
    b"Um8HXLs9o7vwfVxrmpXraT38U7kTf5D2FEAM8MydPPgJQWz+RooBXmmw/5nKcxUngfM3IPXkheX3WmMoPwc79iyngsys15+x6cf5"
    b"oRfXuqna4cz17FQhIXd/2O5S2tlf17lejEiLC5OmdaSwg3RIpvWKnoDs+nOKh/5V8t6l4zciH0bT1mHIE8HYT7pL+LvF2pji2Nkl"
    b"v9CrxPH3/W8VLImkPUhToen4aOcWhJt7FGZAkeSKlkwjG2+VnmirS9jq7BZIDG9k6jEVD2qYalNuC/3J18btkVQZlJI7s5uDHnJs"
    b"Ey+hBcyppRKvTMwoUragQQX6BelSz29Ao8o1gRGWHC56lcOJBnZhu8t+iVrsqMik02c+WcSd1u5+mGd6eUX2wtmIMOvrziix2m6J"
    b"y7gn3gMe+yNmdBy9m53ItdnXXcgbJi1ON1PcAoXliSTmFJmuPaQgbyhMDdMyU1kR0V1atMST5g7a5g11mYx3cgs7arwGSB/AIoUJ"
    b"mqGzCWhmpwFoOmj2FrwIcb+nZyqK86RnxGmri8Xi2JIlU6G5WZO2ZWOk/BLBtg7EapxGv+9AyuhOUi/yfE9IvyJgeIujX6tEDuUm"
    b"Hrm7cxN1z3BoetawT4EhmohHXjnuPaq1bBB/nFdzls+rMNePXdJsv+y/vjEDk3b0il05p6u9RTgqWv+nUYL+Y8BMKc0+pnwYbSF9"
    b"bO7n1uiTkKU1YrcjAtR+DnJWPfCv26nRwQlNq6u/YVcMjVvUcGqAiXuNrjY0ufOHxa6KDl2w1FRD840jJKaHysPlWANkaAhrp2B/"
    b"m98SRlSwFcKVwjwtvErPVujYxAlO4AMBPUQLU+82R7AA2OmpY9bpGAgqmwk7Bc2v6YTtx6/XqLp/ekT0vFI6yUpecSrpVr/wQl3F"
    b"N0BgueI5ZUV+vu7igGWF7ssrDLt+fbpsT+GOIf0OVALyUqQ14tQQh9DvfDWM0rDFg/k8f6sYGYIcaa/bDUjXrbJonlhKXuFjJ9Oi"
    b"GUJDvFZpAlNxrf+hdMPWIVzHCbcbmaRmrwzuvaUP1isAdGDKIp4BVMkIAeAuoCAjC+8tv8C4/w0w/5rDiUvMbLj6st9wBYcyreI7"
    b"6aJhK8niY7LwAiNA+uU5kuXD/Q9lJ9V3FLkTR81LSqUumd3EYcxSVfP6m/ar8ND3z00iN/MyvUT510O0FjPKbGK5L4zXR22NVFxz"
    b"vZyQ45cetIX65AW2l/YXNUNXy2FPTZoiKj9sJGOTk1du6ObaqdXMwlG1+yLfzd0/hYvjnRburS+qv0EX8IsVES/MNmqLtauelVD5"
    b"5T5ZCZ1lds6O3sf81erIdaJpcfKm82WRMndDpy/LwC90V7z/lAH5HiP45VigtoRBPmDATFkZLvYoe2CGkwtIBrJPBsateNPXh+/I"
    b"mmbyrQ0wlbLfbAePpNzD+2eJXqc3W23UzrnJXHHm8dT2b0BPh41i6OpRy2X8IVHVOkzm3ROl2hmdq0O780+WZFd2nK+yOXlS+00n"
    b"ohlVIFwdB7XrHGe7MBNbSmAqo2w/PZMuIbfQ+7s9xxCGPH3DcZ+K3HirwZLl+enpu2WF07YZu8HY6c1r/bWKymdO5NqG5maU9OQ1"
    b"AJib7fyGkj3iqnidvXb99BQl7XmKIuUoh0tjbuDfTlkx/IkekFu3/xPT9IZt9zow4quIuAY4N4pcjmmcJUUujdnxEZtTknm8KyfU"
    b"NfYv217/vSelD1d81sUJaSc2NpQidjLbqeU7RZuhqbFSRxuLHHnd+xk1VCcOLaI4t5yoMVR18mce/dOmJpRVWhld6RF0NXxTC9nx"
    b"L2C3LOOz9nk+s8t2v2v0NPPexbXbzu3flUVKuHrxRkkxKz+Tysc+4i/nPmzlSvNMiVW/ZWfki5bvOUGjqIBNC5LUkgMPTC8lzxqe"
    b"J2w3oIXSzc6+VGceNmhzN7jtuZ2OeSnDOd7DNG6JDXDSVOea+beMLXWe1Vq2fvBFw2TazdWja8tmVUWfnfxVr3jctAq8mPx04VrS"
    b"fy/QV196RNr6iW75XL9/8RhrxDvySFqW0K0cGnpM5Y9Sc9b0/ubwfFKnccB9IWl794I/VVdExWX7lJw1c8p/EHlgiMIXX3HKxeyL"
    b"iLzbukXlWifg6anhIr9K8ez3tBo02BzipjQrKdprNE76/YPmF6Bb0NvfYnRcNdkry6L6+QTiPVRxeOpAvq5AfuK4TSHwYm/2+LqU"
    b"Ou0ZvKtrALB6kBLkyKGXxYsE29hIWQTtnKsIB1ogy47vDu/t5z6Mojs0RhFfxDGL6G3MLT7qaZkNGOlSCrAp95WJq/lH23sxm+lq"
    b"3Ec2heHVuQk5rlHXExD+vViV5yfOU0w7cElY7URwSNcEcLkodLuOEOokik5ERKk3BqzPoBZUXrfmFrf6i58U6CTmbUYX6NiE8g34"
    b"O6NDjhdMHcxcv2vT1LBCQehoyYgzrVhla7Vi2iwd6smpVOrWcmNfhej1AmUg2Um3JHfres1k3/QXxhoHybkLlmo2nlcd5Ml+sx9h"
    b"0Ja04DdtG3LysHy9bXDVE730LGeya9T+pbVPCaw2KUmMWzJD5Ge6iPJ96aq1FjTgib+RoVmT3+7utA21yyLbt+jfMtu1cCDubW9Z"
    b"6Xrmxy1ZTp+mgqV5VxWbNy3pfoFdT4q2zO3hnAk8nf10le2jp8siU+kHT3Z7lmhov2NrCyIGrA27XF29Ak+U7RfoufG07DqCwZkU"
    b"M2XWQDCCcRVfVg2U0LskaVlk2jq8cDW+chqTpmwxGmO6JzibP+HpdgNp5WGyx4tN/flKt/OlQ6nVIpDs1aw+uZtgFRmiTVZB+EpI"
    b"AEBceaEq+MMSRVNTn1MFLQkrLXKy4j1HftIZwZYCGLYGSNiP/OMY4D+T3lTZolfpHMxXO+7YfroA1zg4vqGbtVfoNioKw2+WcTlR"
    b"1wTjHLaLGYLohE+7kDJOo29gUy/sD+bfubAkwPnieVGfEzdtejBze+dg6Utgp9Ol3W3I8F7jU1ueBLT1RiTHIVYhCCe6T53MPVUV"
    b"Wh7qeOZqm766ZyGn+zjuuu6TrF670d2x6z3W2rq+0d21kDlDPuV0oMeAGrtB+1jUo5NZPtnVO1x3J+Z5uD9w7vb5NYj0MYBenCou"
    b"Cb1FjOzT2+XpFvVAEST/C62uMGXtUfgkdcVOWD07lOrAk7a+1FQkmA5pT6zJWeCt+PKL7X+cSm1qrkSMG/xy4XOx/HpJFLj9075O"
    b"S0/TDw+9Vhybal+5THq//BvwtlVy32zr8sg3p34NWFZ6menSS7n6oKzdBYzTyx5evHiVrR9HU0xAWCZgdPP8ToEnIjFSCv1k/Ooh"
    b"k1Ff3KVIx42b7ioYUeeelZd+0NnQcLPgqpbP6yIFx3oSuwmQPTp8L7o974rlvQ1bqS4YUF+/HTl+ZOqFommxNi1Ia41BL4VGweOG"
    b"0AucjBvf1LEWM1NTKgd0NWtUVhCFuAn2uZCDgAwrqA0CeCPY6+vUyvWvY8RK/7NAYr0MmUCNQouD0DSVGqylSK4NyJEnBs2044l0"
    b"/zVHFUspEvxxv8VWeVcCQsxcxuqu+BgPkaaXWm5VpoNMzxSzUdODsblPqhuTPN0IacLWV9BRqSuwRZ02J2oNRi8R/nzJory7+3br"
    b"pN3KY79sK7x5LC/97TFyEOGR2ZXsVSxKXGYQ2uBhd8n6dYE1i/XqssycTkvfnAlYFt1YGBpN3bJ1efn2gvpYKLiG3fGLspl++/7S"
    b"yb2gt5sQfe7Pzg+erFPRR0s75N+ABZ3xrLMd8sMW8qWncshduyoCTKo7LFd+zsDkSkvGWLcLzC1HtzgPdf0+FGCbn628x18e+Yg/"
    b"bEgc7iA8ABfueIBYJbTuVzgl/JpCXHcVIbhzovYgQ6uAIMc16MoBUgsWo7xina6GAHvLZa87fTwLDK8zny9fcT6mx+ykdfOgSj+A"
    b"a6A6QwSoteUTNTqZjT/ujPb8cnxk60vzwjCeZLjLkH9UFb0zgmgeES0El5JDUm8kadVolVXzpy5tTB8Jr7y2c4kTh4bCfVJzfCtj"
    b"F6DTNPNGCH4Hj4SWXayMcnETWZYrL1UbjB+wGiRva8PmAKRit0KgBTVY0iBkOBFoe0VLjAn2uCq64zSC7bFyTL5sV7/OB1ml0ihl"
    b"2jLkmlPbcGlirkvD6byQRA3JQdyk/cjV7JZ8DWft/6p09jfhrEICbusWOu9/+enhZyNzrRfJ3UF797+W/fTq0/4nRjvQ8et7pRfT"
    b"vkpPiX2cG+Lc/B4dJF3S8Yj7b0do9/0Tu069d9XZdTIqjXs1okJfNSIW15aH7E496mGm46FygVHnDZo2CFeQ3qfeHpJG24Zvyr0z"
    b"sHeXuvrl9LdfdHU7f3F+5JM5mB82Xh96qMAhI6z7QNWDpWVd7B1mbsvzs7PDpk2l+dPk2t1p1SXhQu0exVX2eRO7Dj4VEX3nWieS"
    b"mqbEIbdio/7CC/SA5+AFIAiUSatnPi3NiO69mCZeoXWq5TJLeuP1Z130mJ/ZqIoLQa7dLz/raEU16cVYMKvkqqsSj48EZJdeMmu6"
    b"/wXh6j1obWjuutehDEH6kDV0LL8pk/vMrbArIyLGx1ru1eOSjgMC+DgufpsjCFJ7B2t9EsVbh/cGBnlqeZkQrvht0FPBI7Tbibj+"
    b"AKo2Rq8dG9PhL5CR6sUlu+RrzEapyZx1jrQHDczzZiWJaPnp5A0NhdXbZIxud2lE1mvw4qfPC7pji7a7rSCn6Poki+/Eh3x635p2"
    b"Tveg8dluuydGzWPra97eVHX3++n12+PumuVVPcd6wd/HSD7nDYcyg3CCV4/phg9yAw2NVsTWGXRFxIfkDpRkh2svttNZ2VJ0rFO4"
    b"hisoytEhFTIZW9tLJg30P7xr3NvzdUDn6dHPtTZX3D+lTKL+cl571PWmpctkpv9irfcbpZwEurPG3szBncSvjq24Dz5r3pf9rL5j"
    b"Rfdpreto102Y4uEHLFQeCZqg4E/4PD+25ePA3xsWulenyYq2DTmLrYaiX54glSK3UgvA0g/IftxuGWDTydLcPcx7fkJeWh65ob+7"
    b"cvuHhx2FF7tE/b24xmqqd2H45kSyQoYQWFliRgtCF1Blv4eY59OxVtJI5NlZE5UXXb5bcq38HQrQqQ4v8akdC7bfu7JrfMk7nwM9"
    b"3mUhXh69Fgj3Gss77jU0y63Up2IxEmzgMZByIvIuXRjivCSqm0zd/euV2KVue04oNhSCuCaONTcMnfLCCPkW45IqB4i9H8jyYmZp"
    b"g/AGGgDK9qtsTLXCFLshhC34wlGzkpD4enFa3TOt/l3buYWWJ1pT71yIHdx5yeqyZlXcpL2XxcRac8mt7dcWeW67Vf2J/Nn4zLqS"
    b"1X/OhOvK363Mia+M2hLuGr1yn9exhGNrejwXXvdpK3HPK6gdOhOwY60r/+HQo+z/+Hkuc8jM+OD8wJYbfflw2ZazsdIi6aVDOaZn"
    b"bmjG1m6rPJTj8J+sDz6f+/86x/sGJBqPFZ03/ug0kfwf05kaVtvae2UzGQ5xh2qqpi59WHsvp3SEyVLUDrQCj+IG1Z/dABRgH+l6"
    b"eP4qrnrpJdxOaITtSI1n6m18u2EM0OnibGihVpZgPufwpiiFsg39eA/cnkYdd0HkTujY5GbSDeB9yiqz8vpnzTYLdbcuzbw0ErIT"
    b"0aAcPUvNtanRPddYfdhRqdJaWYdrQRPkY2f4w8+yBt0C9XrbsV15BLefQlxSGt58oZxv09fnIr1e4XySMnS7c74Bvaw1ttL0K9xe"
    b"GrVqgpSRtIGbJk1NUQcQEsAQmEZEvUCsQ47oevagLUQGAA+ZhORLOtGy5+gxKB+gAMACABLUiUcIlO2DQY6qD1Q7llh4ZWIg6dMM"
    b"IFCoeBTq+v4ViSvu53QocuwbZiJmFu9L/3TTrmzXp9Wxg8c39yauq+1+cbx6rYdxrgtd48sBqxt65MDTYa6NIq78/poTHo9N3vz3"
    b"17qaBwXGu4/wL/SujBuKOWpXE/Qo8LqG+mz1o83iV51n804PLfu5dNkH3PDO6GgHYknUqqvuHk55pnX4/l7Vdet3OA5wdoJXeX1e"
    b"jgZmKsUbTV3YFf2W+YeSPS0t8LX5NQjtgjyfFekGojLLnY3OlUyz0fRCJXWJu1+eUtf5vT06H83UrnRP6NykRSodVEGOqHxKVGnf"
    b"nX5gA3aBpGYxBaG73d/xxa81ei5r6sucjo+Vl71AeVinl8vUMmqSuI2bgnZUkJs3d3Aa4+9ce9Y1ZS4n+Qq6xB34KPkaozHS0HuE"
    b"pmSdxqJ2bJySlqGa1v/iq+0X8y6J0qX6+aXyrYNSZ7/lrNCtDWe4TBSFpIIQqLHdgBhpwIKr2ilKy5tCAX6zx/LqjQotxgpSHVjM"
    b"AQCApw60tyKL/R7UWPK1CszDGms4ob2WjkFbUJaA8IbaUKlqslolQnBw6ubqgr37T62ventTrajx9+OIdweDj8ZdMD5mXHLzrPtY"
    b"14but6/fVlxdd9rp2NENd3ZlkVs9O1gFNmWRt22kPoHL7Qo1lz+ZuZM39PJx8Z83veuHe9c8u8l5EzGR8/nUHpP7eYqr+345yhxf"
    b"8Sv8D0bbzVNkJ703e2r3qgQUuTJlbw9l4n8/RyGrM99mM6MZ8nIGOZtU4YK7f4ZdpSUcCeQxZBtVFD1xgLg8XC7iluiMbgxctCYd"
    b"t85RR+AeRhywYqvulEb1j/lv98X/UaO7BEI9Yj/CH9fXECGOsqkpObvkdCuWeaDWjn4z55CzK64uYckyn5RD6ozhdkup+vi6jfiS"
    b"2KIucFc/FqlEfkaZBFN694DCdci8eE2V5ykUn8OctH6maBAPoKhTKohEy7XIjHik43b/I1NTNC/NolDMAC+9cka//Wd3ZTgPiwQL"
    b"Af9I2yUBlc4AgxiABJp/kjF/HyS7dzjikfkiPlwlAIqnUpPEcZMh0UMW2MrRs9ZR+alsBkghODc9Bu6q3LELk+suilXOGl0OXOR0"
    b"9NyFtfUbxt5Hd799+bau977yN/vKn05pKbe7MTbl/ma1ND+i4swWxUHDX7JDivqWZG/b/nBi3a2jnfeLpGuObHxXusvs5+v7jCN2"
    b"vr/WeW984eUHEdaGVwdOe1IDTDuwcUOLV90qfhitnuiZQKwrclRk/xV7+s4Dr+y4LYtjfq+1s71U6yLjyUbSbE7QDSqbsZ7q9mod"
    b"vCEWvpsVX0o2vYRuYDwDT9rytZM6sPm1GZ5mo8a4Vhz3RHSaEuQCLUfDp9An+WQBMlicMoPmKsTAWT6pad8RSzNC7Gvem7oPuz04"
    b"uV/qlZaXk5srlnk6TFuSWoA/QGnnqHbtWqJPd8o0g2KbQBI9VgPwRQpbTzm/3+SQkN3e6vgWBFTKPgFqm1pUepKQlVZcB3FLcez+"
    b"UJPj5iKvO5Zb9ByTEPwZ1KDYJBlwQ5KVDxCJWvEsF0dqm5wEoBEMlAxAmymNsRQAIAAdgBqw1VfqQeBB12aYZrVMC6QSJwHI3hKK"
    b"V/tIMA9cPPHC8+1i3fZ1fxgT1i40OLEjSjX6Xl1+/N19/y3JHLwrHXw8cuKvoeEH4o9rvS/U7ztO3/7g8buZ8Z//kK5cPnO1tzpu"
    b"uGNv2MOdwz8bGzxKiOjOflM7FtFtZbn7Qh57ONz5egI2j1Xp+aW9+MBMGdrzqTX34YRtd/uehRdw690eGFp92LOlprOgLSAI81LD"
    b"sNDl/rbbG7cSnPh0YUdkERUXZya6J+yIfunfi5ePttHBDSwO2rmRlm+mxO0scN+N1UlACPhKwE+Fv9PEH8+uStyrw90kZPotG/0Q"
    b"5DB0KYZV8ZLP1Hmpfd55Oot6+ehYelqxDx3UT9DxofItbY65A8+TmULQAKm5t7rYk9BvbYXRScBzAB+BvEDk4h95FVeNP9xmgtpU"
    b"BJhNqdXgexzakRyLxmqArWvdH/GzFX4pYKEO8oiYBgwb2IqKx+o0NAAoABLW7ZGmFEB7nLSZot+hbuu5dYwkAwrbuBREpZ4TlOEU"
    b"+Fvh8UHISpPnqZTjT/cqgs2V2zf2HfO5YYc4+9t68si2wLGfjS+/opl7fPw4Qflz+Rf3os7h4RFNB8XB3wOXF9G3PzpzKMnLTtz1"
    b"8y7DK3GPLb3z9FLGA14LpdnHh+PdXPfOUl0uLBj1c4/3CDIbxeVddeMsesXx8hYpnIqWMM8TBFMbn7lsCn4ZUbcs2yH9gXv+s6hq"
    b"TPP4zvqymv0lxm5hT+7MmuYw3jeoDkVuSivGFGPLWofZLgBawf+LtuGGWXFhR6XKtX4MqoGcgGrQiaRulRzgMpAYZUntfaMXa4mn"
    b"fAOuBRHK7LZ7eJzUPfV7NUfrJRbgPc80sAxzq27RpeCRPHWJll2HC7COqE1Etx9GftEUGLjRwQUNAUSSHihW4SvJoiBAHN07zY5s"
    b"qHRUbUd79juq4USpiiV2cpVidUpD2RTerX2BErtBxE8Eg4BXepinkNhNGQ+RGLbyZ0Rgyhd0GkCgOxa7IWXq7oEpFEhP2ayPpJ8Y"
    b"7qcmU1igLYDMU2ILhgCT1ZPUW4L7I/o31n0Zqut8V4Hdb/0mbU39lj+tWr0dHPwO/Keub1WweWnRWuMIb79n13cs6Ni+ZrLl5C9H"
    b"V3jUl0CMc39xwejoiZ7851fc2GexjTTPMRfnIxlamwZ8rHsopYgN4whVPnJYbvBwAs+O0kinjq/OYvFtj/pa6eZJNobs175TNkGt"
    b"2o8KTDIM9THhiix9p4vJ92uZXcvjZ4eGnNcvDly+PCCgIJ+n8p+M4Bs2Ke4nqoYyAc+UGnyVnCgDgNOiyItLTdBZ/lWbpujkvXfO"
    b"Ln8jy7Vav+3ZYm7haGZhR00S1q9VuI7XggZJDDEm01nilcv70A4CwOOuYJ5vK1K5BwzgUAgAaAbqfuzwxbFd0OcSsOxGHzWUUiVt"
    b"062UW2oaa50DvGtoqGHUSxPxlLV/YfoVZ6Id+4p5MK9kharLHx1ouaYgcncbl1rEVnDDzDkbo1LNZbgbuOqzCK4t/H26SJBI9ZUY"
    b"y3qSOJ70QdkT5G01D1ukjJTXkPJCoNvPGSWpAIeLip5Enpz4Y8WZhCPp6zZehqjm8eORZzcfrbmusXDgj2fDP2tsGbqsl/3XZfvQ"
    b"sPcM80XNqYb25Ziz2IYq88iAUN+hzF0fZY4Y01aZOZ1zTr/DdyfVUYbJTVRZc/yYmmtMjS4/CWmlM4jRtVgSpeqSqp0QkKuZH15p"
    b"8woV2Zqa4VtU/A2I5T6Y5QpXtGBO+1QW7fMpeexAS3JZvOobgLeVZ988ScEX42rxmR7krShvQTSH+jLnQfvS9N8Y2fbUl+XeIOkg"
    b"lgdlvVvX5kTAJaSl6QctNQmbTIvHOQoKbArdxA/wQKyaOi3YhCkCBGhEvBBAheDb32L8WtC1HsT2fiTQqks8Uh6E4GvFzmp/AXJ4"
    b"Oqh4P+/rxHUHdblp+cIxDhAjIQLwF0QzUVBQ2c9TK6SEhJAQnsdax5csDsCGAl3ErsECuyAaI6DTngPBgOz6iKaoBaEy943HSWeO"
    b"bPzJ46+4od7HD0vrdg5Hvu48eTXuyvZVY+6uOmfNrHktRzrw3mlEZwsxugfLTxAOW0kZQ21ubalyy2B+oiTItbj8DH4aczo18CBF"
    b"tAc03Y+Pm8RtRHMlrVztEfUo7fb853hnrQ37Q8h3x/35XVO6hubPhGPtLfoun1jaFTZz0fzkGuBxMFvfWKJWh9xdOiNedxNf3GOw"
    b"9b+B9Lu5pB5v4bj0+KqfF5mOvdjuUTWu0nnivEUrTi/trV6le1JHq/Zw/9Edifo6PvQUv4vgFNAjlniJnK+6lcVbbHdHxmvTPuHF"
    b"HQQ2SaTXxgym8ALYKTMpZVYqPMJ+FYaEohZ1jmt2dmmZaRj1G/CnTfuXgheOAG2FYQ0y73Wmpcm1MN7zZC41jOTPHEWsVrmNBmT4"
    b"TXoGbvo89nNR6rZB0OSisIxeZtGP/JzMpQD4zWz3BOK7LLUUIuCAYLuYPrNQkkpGdbAURIB5dDibe0UXWMRZc7/8t1MDtgNZrtq5"
    b"Wa673svPOFYZajk3Y4/KaS59zewXFAbpNMWUkQiAzKIH6j27TxJWfvbPWRDuxiHwBfwQz08IuqRXbFn2hZL8TEXvIpqzDI6wILKl"
    b"kBoHcYRhSvVpRHdCbtkZr6wRt5q8K+lQVqS3SsG0lgZp0pYSG9U/vwHbY60OMbsWDD2MWvYNGMcNtZKDzU7qqbiXWbYZp/B391e6"
    b"666mkpEv14E1qh1oWjx6jCPWZwNMwJ+pYi63kQ3ZhHxCc8M37CW1T7LlOuyAEOQmdb5SfxAO4+0lLvaDBkuJdMndz/ovD/OLlnAX"
    b"OV5wD8N/FvFeCPjq4CXTBw34UdW7gIhGqeynvUA4JuiwfbFIAL3tpSAa1JFEYufg6UcqQQDvmhkiQEIVgYBzispYFbfEP1yui2Bx"
    b"fN4NFxjtinq4yq67uHLHYsu9b792Ccc7Koe0NCW16Z/T9ntmNtD2EjTPlGmfZZLaUEp8LrdIkeG5mthLQ7D26vPvuozp0W6wubQO"
    b"teQrwEzKNKWnQt4o7q89QaOfp/5R5knjpl3GIhbQ9mb1TJ461kNyPm0ahiW9Vmht6EUG+2z0v3X8M261W//vFkkeX5rGfI6snF5H"
    b"3m9J7MUHoU1oez2DKVgTdDKuVdZknUJPt5H1L0CFQJXegJQRgc3iZhtQZxwb8tMlSL0ZrmxoeNpw5TYk0VSJDbKlROB9DgNEPjGP"
    b"LDN3DtuyP8xMmVX5POUK/PcN2iqJUGQm1SqJ78BzRAOA/bfpjB7Ab2UL3P2Aqmdkyxlk5iSG7Ac8B3YC05glFDN6pgHSUZSamI55"
    b"JzFOqdrB0batKXK0XmmfZal/HesJFZZQ7ZnJNU6iRhkTqT2imUcwbXgoKTzv0ZKZTy9XpQujzD2WVFMvxNPGdpqYkX5viLovYfYz"
    b"gpmojBBhCpVm2rFsw+8YUhuRhKh+ptJTxD5RHgS4S6kVCnrd81T3ETcr/T+PbPc5/VtF15T7CA3vcM9kc7yfFQLvODko3ErW0td+"
    b"nlKprlmB39a2DkvBA5Yggu10WKEnhiY7lVawzAqbhCx83k5OwIag0Xoo92dEqGdJbMlX9O1Nb+PUIdlQxOZjkTrxunYCBCqBFI8w"
    b"D9Mc8URUAnwlSYYEVJQWI8TvkUJT8EMYHJdMblCRIts/LTXw/B3n6EGcFfINAZW7ZspinUugJBr8Qxmda5uUsdF6AHWcXTnTkLEb"
    b"LOoW0uQ9nxY0nIFIWjbFHiv9bzvUxZBb34D8iEj9XNTOFv4iiyp5YtNYk7xSU+KYiTzL8z3ONogseQPmv3onXe3738wS9w5rq6HM"
    b"GCnN4wqHhIiROBZhsUXsQuyESuDB1LbEhmj2+UQupy6R3LTE6Yatj/5HPcvSqwFinSblWbZ2fAo2K6XfnW9oPItynmHoK0z6EHtF"
    b"gKj9uACec9kmwSZOgisXUuQFE4gx0afCUZOqZ+huoUCCsEImOxdH+CYhKqSRmEjECjWXp/jFCsrORSpEtIeQWwxuXMRW7T2RMQP0"
    b"WZ1IPIvxY5LsBHiZBAQsEDYmHnONG/BYygBAC6g+Pf356SZy3jTWGySyARez8we0tTbgy7t1+x/2mDn7XeOsWRguW60f4mumpafD"
    b"WWO8ocV4c9tFvLChpXQo42ZpvP6GG7hKrv+uAU+qi6SXgilaoxX6auO0nZySpUZIOWcMim+zVY3dtU9usboUwze7bjIe4ksvW8e1"
    b"QPaxnT2fqj8tRB3nNbR57lOoqPs5pFv+Xu23RLbhy5BT7k5slgAHslDxKpgjchLaXLGci/dqf8s1gTslNeEDGqVDl1Rfx69k4/px"
    b"DSWxKmajehCbMwyQSFmqAg+4iQZbHfGShpK/0CkFKfYxEoYIj0fqKMk16kJ2BCtyRIsZtIzrKJLgo+LQcCNFsOdNAlhsHhILIJUw"
    b"e3nXI5yG0e2tSCg4AMT8uDrz1GX9haeF/c91K6+ruCdomtijy2Uc/m1KbqQBJz7T9AY1Kp6yR9QuluIsX9pBews2C/JAu5hyLVso"
    b"rSatYKVQfUlmuv8CzIkRbdpe/6u0FmvnaxGbAAlud3sUmoaJvqpWI3YkgblR53ZWF2vPpAQaMep2d/tY91KV3v/FnqO+TXHNaMFF"
    b"+TsC2AXVZDlpPxZKrAj0a+JYYACdTW0l5EG6mZQCnQAEkiU8rZCdgJz4TKQMQt4+LCMEIB0xo2TthgUv0WXrHN08SCoIXwofC+Cy"
    b"KltEJ+G/47BhTL8zZQ4kOH/fVkSlljWaNYT5UXQA2p1NATPxkNIEIPwo9zTHVDboxON9lNifOvyuhZSyEasjS8ue6ggqLdUu2cj0"
    b"Ks2eIoJAOwFLjnHiSDO9RbV97MuyJKS2Ug/zh8QtJkWd1cEQWZpIL7hnVLrg+plI0xRKo02Hm4Qv5puAVYg8r9u8s7wCnpqe7rov"
    b"aY4j2F2pV0obCsUMaCbTB1D4UknaBYlBAB83xtbswLVgsgbphW3MdRzHpDZUvYDo1Ip8qwLYedBUNqbi+tUp2xxL30h8dwtrrupE"
    b"TvoBRHpZaGvZhkox1J5AXJKj/F2/CnxWfx4R+Frs02CPZ/MYZ0HAAFZhI8jA/fif9oAGbISHReJ+AKM7jsIiwYw8POdHeBb0JjkF"
    b"5eG0n/6Fj0R3Q91Id4pin969P3zHQ80yvao6KoTIUuyCFoQWQNhveRfL81tZEPqK1O4otmCn6ZUMmold7ouaTlvN4juS0P4lFVYo"
    b"NJu7alTXpt6EwIiM17UR6Z0MYYeZkYCXCi3PZO5S0TSARbD9EZ4Y7lKJtaZknXZBCk6O/ijohZQ7ZU8zT1OlX5so5/UAg0ZEzUxV"
    b"Z6KSTiRQ2JCslwE6ktrK9pTmIQN7hHW/G1INXy+oSXIEUh9O4WkIBzYAzvug/YyvZZMIVhdBHo3fAB0+EIJBykwcAIYQqDWf2GNF"
    b"j/kUBBpilKVsTiL6h4HaIt/p9TO3mmbOer9/UfRu5v6Tb4Da+NGJIzsmFu3+ciu4d+RI6vTqmceXZ53mXj/Ls+mfmd0zOlsxd3lZ"
    b"8Q1QHfpjZPbxyLrn04dv1Uw4tEG337o8kzf3+i3fLzadvxz5T9LZ8R/LCQ/f6/t4dseXo7/fsun7dObclIPZx2/AT5NHOpJujH89"
    b"4l0zq/p5wZFH0Dv0vwGl0JrnFPCWdkz8eM/EOsmRxrO/wUvugpZ8MnP2pUP/jdl9o9+A3LlNVE04tH8p/GP2I/QT8ec9wzOzZ32/"
    b"LDrxYv4Ut+ZOcdj9yLt1j6c1r84eqX87oTp0bfYy/P7Dz+ceyPps8A148vX7pp/MHJ22O/4ZOtTxa4eDodsdbgc3Xrn1ATp08PwP"
    b"CIfv9338V8iOTjvN/Ot2GSQCS/8JWpLjl5J/La+YyQxufAFdKuYCsHnkSPL4T1ACvkeoFYqQObR6zMT3u49Oc74BtZ+DpZ9/go5W"
    b"DyVMczzvG7Bx8hb/6y1oAV8oxrOddl/6nn51+Qa8mQ2uH/nq/adDfsw0lOb5tCR5jzkMLBqZ7ZvP2jmFTdeivzewAd7APwh4MnPr"
    b"VfDooUn4B+bz8T83FZzvUPfZoebwfM5VhzVhBLh/Ax7NJ2TwSONfX14MfN0w+Q14MPEVeoODxZHNk0f4j2fhPRfNoQZ6rfSzw/wp"
    b"oAQ5dM7F4NbfIYRh9Dfq+kZ3HVn1AyObf7w8H+GRJMcjjX98DR74un5uf4frp9wn7W/97+L/vP4JAsys12z93+nwHjvsNZd+8fzt"
    b"EMSfzsFJ/M/b+6DjfANMJv/4fhyzW/+ToeC8W3X/epzm5IpvwKnPDkPfw+s91Ac978eC5xSL/vf2+csfN9t0Tnx58fTHWc5NLRo9"
    b"MgFl3/z3b8B88L0n/0EXlNqxotHk4IdJ9YqkW/P1o/NVfGSuIl/A6/1ymDd/1m/A98POXVd+PgI9/Mw3YOx/Xocq439u5/xA8iyM"
    b"ZLXx1CN2k7d85tMa/PNh/mz9+8Pf7z30DWibdoe5ZP7uP6AkD9vMgezFHEwIhzv7PgZDON7zAyWXNs+fFD4ZnJb/WQ+Oe9eRJz8O"
    b"tvnF7KJhh5HW78udu/VlUf73Opg7yZ/Tnv++/Pil7v7Xvv9Z3G+27p/FIUQVfANY/zpM/YDa7J73h6vm3g9zgNGRhz9qwlu6Z9Jh"
    b"jgKKfvDav5NWM4GbvZ/wT4Uclnw5A1d4veIHp+kP/QYjIrjmb4ZZEPzo36w4e+/FP6wI79az/g1MUN8ppP3IvygCWk9zrlp+EMh3"
    b"wsiYh6fky+l5sM+fPHV67Teg7kdg/knwiyLlTNqtsDlamMsYjCUoA3X/zuidWwPGRz5AQfeez+m/MwJtw3y8wOFz/Y+MT2iOV3wD"
    b"fP+OqbfUwfLf13CMdzt8OPw9hXV/2HQd/7r5R44m1r6Z9p35ZzHcbOeLv+HS+2IW/dn8XzD/edb3f3d6+0vdEfjlW3u+U7bPHBxq"
    b"voMPWi3479V6IPB9qfoa/PejoZj9+zLpGzD4pRzKYNLZ+fV6RxYNq/4bm/+vTBx/hHw+e4Nzl3/zxfeEuM9flc16/A/bfANMvwFb"
    b"/u5/UgfTWxP/ICF5PPhfV8LZuw7/8+LWf7+1ZnbRUP27f1CzyL12Xd7JHkgbyOf/FJUG+0VWIzyQxbCtGQn2o0RVQsIvXsaas7KK"
    b"RtQBT0AeAMklP2SkCoOUASpuCi0p8V3k43vJQeAFNgt+Pxv2Jh1BcDEAzwcZC/0EGdOsxtPxA5CxRqkep9HOMt57F0pCQLKrpFvK"
    b"rBV2o9u45qHi1da8oAreLrKkJF7jLrorXgeNwotXk4QDVc/U3K/7RP1kEY+MRHtA2wQngCcAqx/NtjQgrA+J9kQvkzsBtjVMdq0w"
    b"Q0HPcdRl4DF4jLFEGa3vJQoHZOr2DYInyRUKMkutOjdW4yQx2t/IpJ+m0cZNIAdlCaue4eFzzRktrD0E8hF9IB7RC1Qjy0FIO0l0"
    b"KQR2wLy7G2wlBQelT6ZRjKnCVGKqNHmwXdic+RuymrdZhObCFiBBMgukGBkEHmyYDwxsOFb3Y4H4TLxRmm2qkwUL4YvwQcLWa9I5"
    b"Y6uwDp2ge0jxe1eJNZew3rVA3Z5EqkE1co0y2WRJAg112b2B46RxrNie1NYTpY6mbDR9Vt7zwS8gSBYPBkwifAEJvDs+UIlUIG+A"
    b"NUAToFBhWJoh7jf4dTMsnWDDHDz05vb4g6lksGd0GRp6AEpCcDOuIJBTmL/oo55kw/5YJMQ2IF4WTdnIILgRuAQ2C9G9d60rbYQY"
    b"jajhSPEnSdIEkRSDrGRDT+LBXwavsFCYwJZx9cLMC44Ed1AReuYMwBzjwdY4IkEA2GQJLQOdiK2IJ6x38/zJwPR+IxEKGMkXC+EE"
    b"KA/0LRPCq0uV82axVRriUZKtKA2Zhpbi03X91fjIYjzoB7IQ0XNIgraE3+isHFW3t3S6XMZNiLcIt7c3wI9B+2YZGFfddpWQs5l1"
    b"MlnMoKCKmOmD7PmA4EoUwmgZDbQo8A5Gqa9NVMeUqQUj3PkmMYMqr6BwQet7rQX97lnUoxDbsLoHDPRuinJcVWsNROJRpVJAyxaO"
    b"PAChU5J6xoiwKQUPz16biL4NgYY4MVNEUrAP5pPzybmasKvRnJMa7MuB4CLF9mSwJu9yo1PT043PEkosEoxbMb6NHiEDrGfoGnt7"
    b"8rFjORQj28kElsF11wott3V441tsgQ/yyhgpatCAiSEg9STW7IWOha1IQiJQA0QL5bGjHtp98aQmKoEjV8THR69TE44siztToYOp"
    b"qICAmK+M1kilxNMAKDkIrip7lLeapHE7SHb6kDpjsygh4TSX4Grgd8/QhZHAGkP2tSFjESthc74GbY3BSgJJWBGMOLTW1WQEIbUn"
    b"f4VOAcgNWIh3n6DI942gLYRupqSi0KPQ/iGkS5XKaHt7lvFdXWmHQHFuPexJeLtcofKKQ6dYc/Uk7THNeDG0pa+wN8kpdkAqfh0S"
    b"dikcg+1ToI1Dv1M/J2VEoy3y17rahEtvN3qEJhzMZijcRfnsg+qMmEHJnAMTa0zjMewY5i0JXMvph2KfwFLdzjO9qDSCjXYbPYwy"
    b"BaPR6uRkNGPetU5hlMM5KrUlHweNJaxFwF2LVFIWWMkgpSHFsmj2KUeddAhC0EJGOY5Vd0yiNTrvQ0/BEqCsQT80iBeK+apOwYDy"
    b"nQx9AKgmkNrKhVUcJspLpJRESnbpPiMHJKvxEoq0BSwDgSKcEW1bzDJK9ukvMh5S44WsFJuBhTeSL1USqosECVXEkHeDqGAA4k7V"
    b"7fyXR6GYTiHezSFOEE3hZ7hEdyWwMPyY65pfLZ0qKurR9iyiESV+/wDgqxoK+gm7Y/rhaFJTXnnYWx8CasSj8DrJsMfjAZNkb6Dt"
    b"HCjolTEgqBzMH4UqxyvHmTYSOG/7FR+Q7ZV2yycrrWKwHPYSMwbJQNMMODEDRqqziOSMvfZjiHqRBcRueDYZbELw0BTYOvItzBrz"
    b"jnn5c1RXDvtxTeLNOUUSDZEE76y2TWZphOaClTBbmhN12N8N+JL91Jk30PbA9/bxz+d7etBduiYZotxlLtRkqPhIoNcSfBq6PhQX"
    b"c53YhGfh+hV4H8szc0bR3OtO7pcMUVBZ8aBuw/YFFGWV6GhitLrZjVRLxBOw5wNKcho4x1lNbiiHWlAscuEhoOSDB66sn0Vh2YRI"
    b"Jw2MK5C9SvifPhDWwKaFwSjEORAqnQkDiOYka384P7KINGfYyrrZGCoviDMkUM3O+YoKfQEItaAFMl2XoQtIUX6o7/Q/AXDxPh+g"
    b"bsjF8BSHihre6khIAIrDBsyNZZaUjWFoCt4FTUXXC3SCZLD1FRQGTMUzDACgqpESAD/n7xyNVKiySeBcbUKdDGoSsA+0p78aT18h"
    b"5KnxcRI8GwLsWqhDEHgYKTINg3AhrG/WEM9RHqKKDQCwhZoBYT9ybqYPgKqq8LxK315dKsqnX3uUwT8edxT2+WTBBtcjiHoFjL0D"
    b"QJ9Mc65vTcC+oXAwENJ8fromPxniKih5fUrGWrc5gy0UH11HoRU1SFWd8bAbKPsUGw7A3MalBLpsLXv/YBnUHGExYLG9YSPUY5QJ"
    b"gE4Q6Lcafx5CBHQ4P3Zds5ofsq8BDcXPFyH9Cza37oX9raHQwV2OAgCwBw/0NIh0IaAYMUzrIHYB5qyyhL6w9ygcZaQYTUEeZUPt"
    b"GEoYbD6MA2QWKn2CJQDeDRRAh187Zw5eeB7NNrsB8s0wuU4+iErUPHQR7yaAvhFUrwwOHMTEEJtp8geZY6g+JUpRJoU2f3DOt02O"
    b"CpZgbrGNJZYCqDCj2RD0BTS4lXuoBaMxrRjYtqQYbYuQwMQyA8IuIj4QRxsxCK7zz+kxEkH7xLMJCcioZLQ6HupbR0O6V+MkehLd"
    b"QeFmUA9amTSHBOh+njqAhFKpy2impbSxAUuEfNtdRjEsZhSoTfOyC3cH6nigFcQ8iGiQNcfg2wDoEtgsgBUJlIW5E0E9HpiTDZBm"
    b"O5jaBrtaYgUABKWfEDH9qE3QA8vRFqDFfMKhjoLWHjyYDdvFvhtE18+Zl7nCroEQ47mqwiBB686ZMqbrwgJojbrmXFT0zmCgm1XP"
    b"CUU0qJIsKolzxFDBi2dRB2ON1b1acVKWkZFehYkcWpFuZFyhkeOsKnVSQKSNOg7qzRu/B5KTcbVYwLIDH77t7gGTgc0g3qiEhnKV"
    b"KJvMUD5grIHpHRSfAgFvEKIs/BiJh7vfcFuNbwC1gSYDQbU6qS0fosLi1eRkC4UBC0NwNJaQU5XRsFjwa4ZSRowmzV34QBiCk58M"
    b"bVAA3YmF8KXKRQUj9kbBeaYoLGKaPbykKF4V1C6gBRkTGAInGToLW/mugfk2uRHqQwgp48qYOvkABuYGCzhgsF+YMYwPcjYHdvO+"
    b"BVuVVARLOVDQYDdVKBcX5hxQ5+4nlQfCSnClOiYZIWnLOWAL45wGNo2RNqJJ7s7X+h+lbve7iihU3TwaxKkXSeCacjbpnVOedQjW"
    b"c6CJTU41k5oA6G6ujWuR4HSmoIslGIXOL7ziqxoOAwH2O00EIM2FD/gKHEyBQqx/KabZYYK+NiMjeRPrEOneue18AxbdF1NhOQg3"
    b"p9WMCahLhaRKuwSK0JARRts2Vffud/ONFU5vekA2P3bMmTwFfG+1UKUEl8W6Vmh03gH7ZJw5+FS+Im4GyRmbL/tAzSuUkKiuFozS"
    b"yNp2W906kWi+aBTKsrVj+FoonGHkZMoTVBnXiMzx5k+GjCyzJfCUypjBEHkf9Oh6oSjfrbavjQeTEwGq3zFIOwHz9mbZmlAUoUj2"
    b"wc53sphPdFVoHyhIUQql+UywFk4mUgy7MU4BCnWW7RxbqTzRqtExc9+onXs60Onk6WV05yeyStYyN9cq14ySfNYDlrTWRd08VGQ8"
    b"D0W8FA0REF+tXCiv1MgU2xp44vwZcO3xEmjJlyQJ0JCDPQg2qVUESyBp6A07XqdK+ZGiAEBRonXQFyb/ZQy+gWBOSaQZ0NQZTU4N"
    b"EFcxmDeAaN/Lc8zjtURHiimD9CeUGgVUW2BFMIrYBFWhAv3dqxYhzdatj0uet6Q9lIdUIO4IYwYNAqZgR/fbJn3CNPyYLfIXDaGT"
    b"pMciPg1TziDnw06xkRDGsNEmpHI4QQB5ygKOhMBrrVxmMQVhlCOc82zGzFseq845xilgph9B1CK6N2sIRcUcqWzCJvqNQgbJFb6R"
    b"jp+L88nSzYZurrtiDN0irA1XnWw6797hyVia2qtvOBC+g3wvYtgjujLaLyDiClPZQltNfoQsjmcqfeI7aGKZutl5o0KJpdoAH1MI"
    b"jVk6FIURjS4jtcmrNVJRAIOHZsQfBN/Cs0vhfPS1X6k0cTaU03zJxH4y296JqBRYWFgAWD2oJg3ZRFPBJmgZIh+IHSU1IWLmRBOM"
    b"SYIz+eB8ByBwyotx92U+9eBRKYFy1AN5I9WcaHrxpVuuPeYmGNDYDxN3uco20B5QMsHKG7pQ5ySsv4SFvT17FZhyFCwlfFWd+Efn"
    b"gtMEk6nm96fAhQyRC+dorep2uCceTCWJBJUbR9tEorC1Ww5BGn7CkLCvh3GzsBKLzVu+yXV5blZAyKriprCQVafeR+VfMrzi1OWJ"
    b"7GJGLUyrWrDefF9cVc52seL8FV9WtbXHb9U07qXiK6MtmR41R6/FVRsw0G2b1K3ZASmWY6SmUWK0RpqEeQP1DfCCJzu5JIzSHN8e"
    b"RmovYdtDUywkP3gQ/TXORZDtflygq9OEYqMUEgVGrG4C+5SjSZ1CaNqW0qAuYcQwvimLVydBDRtq9YdhdQOhxpsHkx3EiwFT83aC"
    b"kMRAeKjM6GzUd5ZfvHfRSJ/HRCrgxoF2agAAHmH9dZ8NCbAA/At7UFLBIx8XGFfBloeZ8OpCEfzfL8Bcd8EL1s7rP0hFTiHk8BdK"
    b"r3WDhhyLPtl7tO2koHo1w9eo+OCxX8nZmArd5KBfDxCnKI88HtYtpv16t/ZN53K98/uGOvY1nWOOG1wJ++8O5z1DJYR7WcfcWBZP"
    b"DT3dVhxzCmBuca/J2uIZvZ07xLJkZj90Y/rSq42He0mVQctiEwsK8tvqRak1DHNiTewoEfbO5KpKfaRohghSF9DeOeo3i50sLBLw"
    b"UK/uInBrYpq15c7Nkwgtt6MCaA4HkZnwRx00cAl7wtII6uXA7WrSxAeUe4PH2jklYVDBf6WTgeyTMSDdVET6NAaLA9mnMfYVxMoU"
    b"a8fCWzxLER5fJM/fYRbxW2Np7mmkuDtqoLK2zkVBLsGUYSr585LYtkz6FxTSJkh7O9UD8CDwLPRMFcRp8KxtP0Z8C0bLWHiIgSB1"
    b"tglG6BhDdxD5C2ABcaOcZYSpGFStOQTTJNS/9SrvEHh8MoDi7XNbb3Jq2HXXFgOvCOvNa/4b+uT+ug0QJh/mmWStX1Md2l2aq/J+"
    b"wix5j7TbLZzsGt5dGedzgby0qjvGutDnfBw5PwaCbMS9LJP62MwtatKeVQS3FSk5boV2x826D/5lw+5r3OuewXBPl10xIINtAV9d"
    b"Ud6QpLRgzeTBLqiQqH1LALoQ+dD4HS7zNdAlmmtjYxq0+yBYgiUUlgUkkRByNIPAhmQONIXPgTIZBZUjb2KMwc/Y+12Ry6Dx8ADU"
    b"XGDiwlPWAgvZXhSvZIg2i3Wcle6JiPxhV+sY+IQQVe3fm3+nItLtYVdO+Xtyhl9BqdMc9QbALvaYin412IJT1ESHfnYYZsOJ7ybs"
    b"qnADl0JyKh4o33bbx8CKn9IXB1tMMmBkUqIOIHot5oBM2ABCxaXiTY0sxgtMKkRbNOx7DYeWRbb/rB5wadUb8d0Lq8bDlkW+OZUd"
    b"sCw/fXnc8vKEcfauITyfnsVfWq7osvZooXm00FepVUQOsyy6w+hQXCv8w+ysVtg3ery1tG+8XOm+4G6AnVbAiwY1tiqg/3IKIQU+"
    b"WTApTIsAojmRcBi0RKzItcbZk8kJQepn4Y9WkDHNkDBqoy8hvuJY/wSJ6bmCY8KfK6F6Rxgs5OAFDIoz50Yq1WQTgCpovkHBg2Ir"
    b"Vg9umoh5l2IBiwg7VCcCp7imd1SeIE6dLFl2SvrwwnoYMgs/QmVYY3D95BOts1Sfq6tOm4b34hYULLh7evEKazqenAN+QkQiFUgx"
    b"KVdQCV45XyZXRxZrbhsk58Mziz/8uzJhn+gTHprAE+BpiwEAusD8FA0VAKjdYCwxk8J/Ih35K1a+oIK6gPJneP7459J7vh0RT+7p"
    b"dIQ+CVmTtgvK8i6DLlf4K0ud3Zy1h9zLdg2V0Li/ZfGRvfRMPv3oNXmLtYda9sPIbo/yCnHLivtiRUW9hlPl+b4EQ6Oq9RHLKyOa"
    b"fFhoC33EVEKg5tg91an9o4xFaYGqL/MgWWZjoP3auY1gaNh54sm9Xd3q1r/keT3kSnuWtlhbQVNBCYKPWCnUWAKFGmo2siZ4jPAx"
    b"IKdD2o7Abraat4TvVSLq5ao1e2F0zQATdNVtGFUPAS0b6v1znwVGI2r2bqrEVGEkZjfE7n6c7AHLxlPSu3ULr9saXNkX1hHXVLOw"
    b"Fzru9qVp8VqdHd2ta9KGjfzHjeCAnzZ1/TNi2J1MT3WpigD79pqcJD4nWot7SdXMuzVFLodN4helM1niyCYriyZ5+QmLg/kkcP+A"
    b"DoWWP8fDkEwCPRMALgY1TzoADwuN4EQAIbTOd8/FxJ0NDVi+z+ziGn3xn+8qVg0th1C9FPZfeFixiptM4z407HImeiODxCQ0gtsQ"
    b"EN7tFiRbYRHt5FJD1qtE08jdV1f1Lq2oVz92ouCFKEnjWYymk07L6lijvTmnqaxswivr0LFAUkPrbfRSU9lhQHaGbGD6qlyQwS5U"
    b"j5A+8Ij4NWDVG/tlkfe2rDZs8plK6fbpMHWV5153HYso31gVzuA5zsFcW844xfZCIWHNeE4RkiZh8NMJ0GgRyAh5kt8RT3zXFrsX"
    b"1jiy6EBNHvyBUoj9WsccNjT8RCO4R0PFq+fUERbWH2q8miLsQ4NHrrsWDtj6ZG18kGfy6AmUgX1NYXFDUAb2eZsWw12HXc2MOW5K"
    b"zt+/vWu3T+9xWs+mWPj/fvHtCbv9GmtzL3BoBINH8RBMl/8aOr5pz1qdZ+iRVcYvYxQ/2zQ7/Ec/9oPq62njlz6PzE2urqn5XHoq"
    b"z2jl+Jbrrp0DNS5LTla09eAkqpv0MRLlnCRKu4GgyNSBu6bP8JBcYpyGJkKkAMES9CQyWn0pjhiEr/ZAavawvdLa0N2k1GP7mns2"
    b"piFL78UfONHxM+tqXDEs2qBEGV437CaIdygeTSIkEuD/2noTuKautWv8ZJQAwZCEAAFpQAlECSIEEFAbCIRACEJAZBAbRgNSFEjp"
    b"RWtvGERmwyAzGiBMTg2ICjg0UJGAQhNAG1q0WkGRUtpLq7ba3vfbB3vv9/7/v08GgZBw9rPXs9Z69jnn2QCjECJNzKwRJlEaRP2T"
    b"+kF4UarRzb2t00b/A+11PHXQ1aquC0xZ6v7PrYK1m/7xRFJc/gzlM6tvJb0zAAjBpcp2R8H9aY/MiYrsC9VbprIve2Qmenx70U42"
    b"2e4umyqp8Jnw3JHoGVhxM7NfcsbCb66dHGWIuTPygITMsC74gXzV3pXmitBw5JJtA6yjuXORodcrOxmBI0znP+tTojoAOtmeK6jO"
    b"9xW6AL3VIC+3UBYEJs5n0z8g+UDDUfuxLWXRHs4L7S3tpx05LQuX4V28L3v0Je5IHewLvg/I9j4QM6RwBVtZmWTBsaWEak8zBv0j"
    b"do0FjDt8knBf0tyQfoX6BrPrhzXLuaw/PB4HLowvH55/kePosbg8uBy/ZvDm3ObH2VeXB5Y/yon/8pjVqw9unT7afezysdqspAel"
    b"s3PTmZsGTng/zPQ/uGu8XbHgVuE7GcjkAffmfP4ba6dp5W2jyhDhppYNVndI7CUUBoV3fLIP1Rq0CYqP3u6fuOOzPNviE956ZgJU"
    b"/3Xux9ETme1uFZ812I+2N9ETTGUvziaYVj0zT3JJfXY/7em+5gb7YufQpmTxKU0NJwKqlKngBR2BxkBkkptx4p79wCt7rYTlaN8e"
    b"uTnkk3j3DckbBJtovyl5P93tOO0/83X1dWrFSubSJ2c2GVcOsIIn2LH6QY0uNcXiu1ku4oXJ2orsCoe5Y82DmVGWUVmWl/Y7Bj18"
    b"TzcctcDEMi/0tkNXgPCG0+KSpLnyG5hzznM7yA1BngRqW35oLpDEaqScJOHg1GZ1NuI6WaNLbTS953Pn1UPzWz2q37iucjXjyR0W"
    b"3Ij00JQojgIlB7ZTTpa6su2sVLCVWj9BUlqk1yOD91yyHOwLnXpw9Pm92cWJCocGh8XUZ41ASy/aebmsN20GtEOcgzB+dX49ptxK"
    b"dazFs0nu4qadv/7h7mH24FgJ+HNB3L37Dj4/4mLZcGt/dctzD+dj5+y8xiP5s+ZvEIesnvJ3vtE/2K5+g3pzejM4wD9rMzftvCU4"
    b"3mK3ZSz9g30LL8fqfxpdvtnStWUs4kNheqa/r0vXanqmhT+zUXvxUHIHdXSuNcU0zKgys4XSrkxl90j3S9Gn/FOX/FSGTH5PfoSn"
    b"19ZVE2Y2rfYiJhw93tCf4EHUTtYxLX/ab3VgbJu/Y1An80Dcrk5mhPP9Q9zMu1qnJPsGZdKWQBexurbIhITgSTYMo6+hB7MhXa5H"
    b"Dr04i0r5N7ck+F7bs/+BXke6lVzxeTY7a2rVQf1KN7vJbK7bs5c3334Dy/mC6qVcPO8VWDEfNVXV3mmuHVR/bNnZtSVaHasfhS07"
    b"VAs3iXixknXzFCXtxbbxjK+aPKYeZCzc+/yF176CPrP+JIdOCWeCtXOR6jZWM9t+gZLqGcxbGT03DpBOmEx+seXuv8aTF7m9Z2pD"
    b"xUrPXw7mclq35+nVdDc61ywBQUhq9xyYiipe3VHza47LaoTzVPKa+b9/OTQf/7T5mwHJD1PpcKZck5zZ5NQwyO3NFgsjUN8MGFUe"
    b"Dz79EYJ7G0lp5X4JPFgr0H+bagk6UCIw+9q6yd/twGz82n5K2sPMm6eMDlzLuppQR+e0nH/RvDIKNKi2TLGS90GYJymCjQgIwWg5"
    b"8+LuBcfyzY237q2iXln5DyRVP8hxyTE6cLvzr/sHOWejVkYX7P4V0HrxpJZP0/6zKHbDD3jkPbX28q7fUmEUBAyqP/nh1b5VSfPY"
    b"we37F156dHpmvP3CLmByB8j4PzyDOV980L13fn6h4mJOcFVFfYBLNCsWvyHigABeDyQ0Hzf226GdM2SZ4l2JVntD4lgmTILvAMqD"
    b"B3zT0mh7nWP0jtSBtece0Tv7FhdeHA5OawCZl5PkIp6IClp6lZQ//PhflnMZZsqsYKz9Xd4o4QGB3xYyROCLOJUs8M4sslXj5hE8"
    b"g7K8qwXlm8W8WWqn2NVmaUA95D4Gb8qVseBu/3K0qqKq4n5URbXsZWFWVlXCP46dpndtkXBmQYLg25f/4bqKvuWPXPPfE/RmNX7N"
    b"siHL7GadZdSVHI9vL+8aBNk22Bc02o5LdIH76Nc5iwMTtQpnbY8/d9fdDpBlAFSSZ682BIy/zzijizlpwKQmeLlvZe3tZeu0NQvJ"
    b"2sKgwo/3s341u5pR8OsfO8Dg7j/mMJLX+PvK+hq0TRPJcHeNTWZXtIPjOx6d8oB59ErUw/BPnjUMht6MbdKmQNMrIa+2Wn0Zkkj9"
    b"izfginBl8yXezV2+2pq1bwaZZolAUy3nXP7YAaja+cVa1s0zY3WuzT/bZibd070QP6+5L4Ybcb+r9r0dhb4dhWB7ykkgfDJN83jr"
    b"5zTN2VSrp81X/oB3nfmwGibaLFPZ+HPb1jGGJMXypLatQRLdILFzFseUm4BvLzprLwHwL8wueFqfGwdjT3jFPN7UfCpiOyAKD6P5"
    b"PV3jDzODPn36ak/wzZzNNyiH34Cc+XGs6m2LrYVfzb6oS4K2el12MI0ZAHAR4jQTOFawdqzcqbFtm0eGKM6joT+uGoCcfuDR+/BX"
    b"fFo1sLa4/mVwdkVagyFwQI1l0U61WVZPXzccPRc4PHyWnLG44VxD2KGtHs+zABk2Wl+xsZQWAy/mQeBX2sfgcepGuzi5kOoI7znH"
    b"m75WVlJOnhQfr4Mbl45Z93B/gT2LYeeixVeMHu6/piYn3E51u3rgny7vamyu7D/h/UVG4V/eJ8bLus7ef8zf3OSYQLlQTed7fOvR"
    b"B2xfY+YVFMPFrSgtz7JsKeYvXOvdJBAjas2R9Rfc0eMfvGsehCfZ8i+j6iqvjOeeE7Wem2UPW/k0MFJG037LwSzAg+v6EufQyUpe"
    b"I3GFE3xu2PgCbBsa9Rao7mNNgz3+Bx0eeYB0+3JDN4jnz181Tt3MoXv+awH4ifrAyaUHmZEMx9GNwnwh+k/ZIXdeTdYCQNXX1a6w"
    b"X/764PPttmP0j4SAN+h7wwC7qbMSX1kFHQx8Pn4WJoGcoGjnWo5bUU7Q0kdFLOaKOJXDAdhdnM+ztYm2EaI8gqaKcnDtHiAFzJ+7"
    b"iF+cjQEJGubS5r6gH4biLbjaP/QwaHvos/QhQXzuzotumEkuJh/m9jb0cHuBHHFAWH//NQfOjT1tF6qzZD8PLw9lZj9TH9u5e38w"
    b"gIntMbMTPp+/SBnfMXd6xzTQF3rDJapdEoo/Ly5tw6WrsPWpsarjCGILiWvuTNTeq2OU+luljXmNX8xI+job0Dc9aMxr31gdY0q7"
    b"XrY7HpjN6s9cAFlhxnevppzW/hrwQcIZq0PdVQtPJ067swZ3rrVXZXp8u6OmrCiTdsom2qWmyFpdW6zLjaEFs4Mfc3MBo0innV3X"
    b"N2zxc15yf4sITNJmwGOB8aJOD9Ua3poMdK0Ii2YmubZHJn+ROeF2uju5f//PhkM2UU1vbNtxoDa4mwWXuSugPggcFxfeD21KNAeF"
    b"GeE5GwDvLtzdHnx8ZQ0zSSeoX/r+cLdfGV0GMPFMgDcOtT2nfrPtHD3LXbY4XjuVXQYbSeB/2hmJtGLYrNwvyoSE9HJrl2jPHYvt"
    b"woqbURfmX9qvDi97XVEsVPzp8fP8jx6brxvFeAZ6wqAu/2Ey0F5j0RbavMiVZD6fiH+QkQQitGOsbjYHeL1n95Z3Nf9sPV43u39w"
    b"am2/1UdC+N7vv3wAI5rdAz7BcLH564FDDne0H5YINvxw+igltO2ZDBSS8ixkko14QkgvW9zsVtbhCVdEhiCy9791/juoUiHymfPS"
    b"Qxf7Duel9ATfVVZ4cqyFT1K+OEjzgPewJAxGj/1jc/F8exfln/QX1o/yH+yP+KT5VHv+g98Wfhpr3G245/JfU1eqvHqPlQIy4bSZ"
    b"l0/xvhz10xLvu0bdfBy0bPosh7px7IuMVdTXC8cLM+/vPfpivHl0YeDZ5LnxKVgqXwM0JN3Punpg0HkOCGjQKS8AkTEvf6sDXV7r"
    b"7sOMb13+QfviK/fVE6XqnH+3uzYPhg7XWd/V3vOoh/ftLsp0tlbrZboAHsVlrrGYhcWZ9OJrAvyeRW2GrCbFnEplUEJT/bCP2aki"
    b"QJaH4dbYhvBKpjUQdnVqaMZEFLd3PKkmtY+qjanznUgExG2uLXuR2J/EiGohzDX5unnDOlGjSEx+LsAHiQfUmm9dAFup59t592fb"
    b"263ChBXNOYIJt4oj9FvDN0fB84GNgqt9eCOixOcCwvNDvoMkXzcBUWeYV1PazpsCyff7GpCpCIfHQJlX4MxTLOw2tGr7a6q6KuFL"
    b"oyN2KaFzp23bM8s/de0uXmyLvpw2WBa988qhH8e/PrNj+Nxuy8HM/ZQD/w7OvnDa8dgSUJicK99EwLdEP3+1qWFizXJ6Kn6N8GsO"
    b"vQB8FOUUtx2MF39oJu5edCyPkz0sp/gsXbrXdkANm+qJrPbNuPuTcPtruEz2cGFxEonfH8XQHJ3tr9oswY2k9VWpbLjz+FMXYXn7"
    b"Zp/Z0rb1QZSLH5rz7ZfGzpZPca5sPP9FlmLBS3nsa7uDu8ZaTz3M8ZwS/zT24/b5lx50t79e7g87+Mx4e9jC2Wfm/Ac5doMZH95y"
    b"XHizaePjm6dz8uHaJd52+WbVmuUfuwOa1JmJk58DWsxcvA9TxT3gsn9VxwNXCjhk/P0nJryk01Bu7kHyn/96FkDjw6PPx2tGF0BZ"
    b"d6UFNt5tlkXWfeJCtY2QNqlupM+xKKpgtkA6g6yWu5bdaKTSQ2NyqPib5chKibBSkmKee5GeGtqfSdUqADmWgNznJvcfBpIKXBfJ"
    b"oUAL71YwwZUkf58Zbdtn+AJkU9LmzUDObOagjnmDsu4h17IS17LJCdey8kB4Fde9MBBQz6JjSQ63bLEGEDK9bL7sW2t1nuUgvfgG"
    b"TaBl8Yzu5yf41EinXVxBgtnDDjZB0X4de+xQAMy9/jD3Gv0ZNXWlmvnlP7i3Ju7Zda8lr/nTPwpdAFXfzivHTtt5+VNApuwbBX7i"
    b"J8uGTO3UmqXHlagJLfiB5U+WaxP3xafv0PP/hS14zmKOy+fFh62BaeiP4monDvtdPKnxKDdmVAGgr++g87F5gIyT2O52vygNR21E"
    b"XnYwCJb2L7WuxOa6Jyjt2AcSQ/vhACVHgeD0CyuBPFM6Y03hV9N8ze2yfnAaNmxGN/dcAjB47pXx9nu7gPvpt45sEhwfqbvwrPtN"
    b"Wcfyn9WPbd9+ufkx9dVB/4EPHx+Zv/1k17N5l7P/pH9s+YdLVJP/rjWgiLA2TlYDEXEMWieAa1n9WVPJ9nBPq0LV25dJu986n4V7"
    b"acIb4tjoHem1r31nbsxANCv43I9l29YQn7ODY6UR4/Ig/aB2npIldG27hkiDFBgGItUPTK74sHkjIIU6UIulhl4Ew6lUH/brqfPJ"
    b"oheB90z4c3HNOOCVfIYaVG/OOHquJ71kb29rhox6l7toweUCaICPu0mUzsOcefQCi1OXYGOxgnRps1jIO3CD5EMzaHXX5aVhFawU"
    b"c0roxcT09cg9KAXlfLblK/8A/+ztoWNhFxdc//wn/dZXu862jwPAJ32dzLQcdK4HXDgBE6I6qz8jeSKzP+P5uD/gwoDvgCBmOhNl"
    b"RjrUCVWL1A2ayw2thzEKyqWN/9pVjlMbLtqENjdUEsEcjvsGyNgd9HdE36+C75mEIr9hM738IM2efHXNkkGp/bSz/UMgn1edlzp2"
    b"tNX6LB221/IZkmiYBif9mgt/eWUCCshNhFcHBcGcpOV/LB+Z3/amwvP00b0fVq6Sfv93wCr5ivO7kxfv3hqpjXlDpYNirQuo3zl6"
    b"GAV4wKBoj76kHeLn47X3o52AuZ0IqoW7w7nT9vTcf700JbRdn7VBJvFRA4mOzay0n+zTS8uNRqQVy3WYNDHJoW1GznQu3Tuw8QjN"
    b"zmYp0FcLxL2tgVtZmURRgMxM8Lub3P9+/mIpfabsNTxhjeS7q0DrBWKwvkowBTL+CisAakEEvHYshTeXKcX2VrZeTEzFk8sDmbzW"
    b"FeSRAeKjap90UKA0Wt8bbDEQ4aUCHfF7EV2D36OKhpuI54vVs+1pWa72y6M18+3nzQc8A1l/fjo/ZJMTsK6hHmuJV8Bwqz2+3flr"
    b"Ivi0dv+F+Nk9Lw/t1/TksrcyyEu0TYnEXYMESGBNKv16EIF+muYb5cQ5tBt6T6F4Kqg45O1Jm/Cerc1+fnbe4S2IlNeIFWS6yqD1"
    b"jkFQu+8Ew8lqVMMo3/jP/4HShjAycYdMPADIe3N9X3lC8+yCa8U/6V3WF7NMOX8Kl4DaA383ACpJwOtCNSsBWFcgpJ0woGCaHF9f"
    b"c+am+/YfYpibXxfxs41/W/W/FLKA9oDX2PgnVMW8Rpe0PIs+vXS1SRtKRFFRVCk1QpEwidJC3i2tfSe9BM1KB9Tiadhx2ZQKqQze"
    b"kKPL38v/8hwsKPpt7zdSFnBAh5Fb7oMX5eE9EV06A6E9EMuHRFgsZ9sjb7CYexY1P9WxBbgh4OzgJuIHpG40NygNFEBQcetl8yQy"
    b"mGnRYaDZd7kdFj7JHcD236J+TtM6q1lJuwr64zxAhjyHk2OxAchA7SEvf9ZC8mwCPSnkrUxPYvWV8hrUh8tEZtNSXiOrV2Ip5xJ8"
    b"LkGRRB3h+yy3omobayV9qbD6RFEc9cHOV7aBSTVnAnQmhPPImBVEHLl+HzVP62enwkjTkDoUwESHEwMeIbc8rn4WPt/R7icbojZI"
    b"DiTHUv2tJSDzSA75XBegTPfqgLFlPY8HHsG7KVniq/BuricuBBb4fDPtYTUZ7uYNogy3nCcseONzmQ2ER/DWOxDE8EJW2ysmrEaJ"
    b"32di+hC6FaEM3sJLEUtRhAaygSxFV0oiFrFP+PBuL9jvveU6cbAvCC5HxD+hQ9ZV6QvtO2isshJWWTm+dXPIYUoUt3iulS9HSeBt"
    b"IuDVbvhPCrBfcb5TazzwpOuV8i+3bIwvbJCIFaGKRFt4V9/KykvUnkZtTDmqXtvcyQcePhT49wOwCwsAsQ6OiAfRjb/gpra+14vo"
    b"RfWHNN8g2NGs1TbZ+qnsaFH0idK2a455d4vTGq379KpxxEfGuzrWBB9BdKnYYEjxE9pFwPDCPUEFDC3pBayZpOQCXFX6kaFtvpqP"
    b"deLadzIKK2IU/pJcWFo2waoQLj30EIivyoZYFT5L7/HVGpgAjsoc1EpgygvWA8yvxH6sI84ZM7VGLz2ysXvKb4/1hNLRgWxOpT3c"
    b"+ksPgNkZvkiPuKjboMQ7wYFeDVnJtn1FRULYc5mlQW01N2qEMi2QhFQ/sgKTFgvsYR3NLh4l2iTf4KjiiDiV6EECU6p4BzIXZDC3"
    b"t1L0kMhyKysXP3Au0Q2RZP1glmsUAsJcpReUpoqBQL2eztLncOA5YfKGwLtr2T1gEB+Wk++1XadSnnGzxn3hEyTAyFQBsm+wS3vB"
    b"JVY2hdYo/A7REzmVSKHeccx05hqh+QaCKb2GRa9YUer39SAiSjbJgXGw0Ksd972euBf9CDUes8GbP+DphTj5wDGXRX2gwaNnvCUP"
    b"6BvPdMVFtNRgllBykrcEma425uhyPaBriB4ywCzQa0CYMG+uo3cCoLedG9bQxCVVVtY0wNOXrhJoG4uPDBD+EP3iWNxzujVz98c2"
    b"QqoLMNhDiEjAXdcAkHnkFqmqbhYNtUi/CWF8ggSU5e5LApwBykCFCjjG7NDA2Akmz0DoeGpQYlFOBOYDcLv4ONkIxiPxUa5jrDQG"
    b"es12BQ6T6loAQ1dY3mpTHl4uvjRgH8z2bYC3snFDXxPg7r2r9vWQcdSs7XfeVnOiHEBU22YLS4SOoDCZdnEsBQEGBeAXdxwL1vDm"
    b"e62buOZ0kIy1ILq/VjaWJd6/ANxsEoPAz2YKbFK6kmba6I24np70uU8+Q1INzitW7PLh2Wo/IsfdHibyw4T8/cLvRWf1oEYRVcTo"
    b"PGd95KQd+/d98noHpMYpGosSXhSKRrvmt15DxCA+khmw7WiUx+yYv9iWhcU6rALTg0iNnQDMyAgSg2oKyKvl3bJFG0O49Fq00UsH"
    b"OVJMknCEf0DpxYriZYHVr5XL4W7o62y+SNCHfmQMUicEwmxBIT8KIeAc2Qppv1QO2d4Q0Uykaagg/b1Kk16RYoLpfOq6zOox220N"
    b"mYmIgYSrqH5oAX19HlTidTR8EV4KiG+2hFVQYOHDLeyt7Aa+dHv68347G3ExL88CaUEvOjJY6Vyvrek85OtB8l0BvigD8EFnLHn9"
    b"ndIJHFEDMESc75ZYdjvaGUGT7YbV8OZOFyecq132NQO8CJNBsdzPWSyHHrDeVToYeetRIzbagAhtSDYVOG1qe23gt8IsK3hUYKcp"
    b"4E37HOl1+ffspYqK0YqKB/EUzLAiQjUschLrIRtFzhO9ACsG7JVofTdIRyedUNU53sGpc9NYzLwefi9w5rBysoWyjfFLHTZLblRb"
    b"dS0c0u9WCdecCa5MHcgGMLuCFKbs+KW5H4k6Ivwt4ZyeXU2DuEODPiOdljO2QQ+k0tobkK0omh0CAZW3VW5pRMipVElowGvkNUSX"
    b"H+VcXOtKSFoIoP1GgwR2/cb4ggVvL6hp1dUgnpHGfg0FtYGQltp/azhLHa3Fx0/qK+EdYt7L5yEGiZtZiQax9DA3VgIu6aFqA9m7"
    b"JwAKpj0MAAG0zYL8dyzOopd1edq249QTO0A8p4JKpoImucLED2cDGnx1mPxe8abaR1KmtLhLlLqI8MJp90UYjeb75XOH9dWkJ41f"
    b"vq1dEfuGQKilcGH2LnP5UL0+Y88TEEep49nhoyu3OjWuEjwLvLk6J/pe1+HSgBXtvZDLV4NjiU7ax/jUgawIeY2skSpUxxHOMvNA"
    b"Nj+xO6Iou3bFCjdkwxPM7WL5Et/m/nRd96oAhmL+SPaKwKmpzx5CdIg82U6Q9av1Hi/YJQC02nckn7TcNFD5iE+w0a2XO09CM3LG"
    b"HtVu4Et1mCRNpIbO2i0VlJN60dcQSmQ2CgI6N00v1N3D/vLavn9Jly0N5ko4MsJ6acxNZ68vGFcasQVKqowC2Bg8qVISvi6z3FJr"
    b"yf4fjrKC+rKpLjUX8z14k90TQSXFzqE1DTVJdL7vdV/ffG+j0dYLNc030EuXKmqKz2MLW0wnrFRf9XUdxWg4AUNYk0peowEbgph5"
    b"4n6T/WwLUwVr5VOjsqF6hK4vb5gCue5NfzKsDKK/w6hYs9eMma9phe+Mw8QlMTD5p9SFpvrheamNcKXox0BEoN2MN/aw+MvsXHnx"
    b"ovPyZt+tn+Vvtd8Ye3usm//JrLV74oweE43f5ogl4bchrvoKkTFK23u9SF02VWaSlk06cRdQrJYp49QBtaFmo4Klx005xFIWBFnd"
    b"B66jHqPE35C+RnhkwztyIJUUFWsF0o+FugHwyvFPSrHaH0o21djZ6NUGUl1ycG0HgIstOgWnd0mhGpS8+xewHfP6QUNWj7m5arEb"
    b"Fd6+S3p1c/R2UQFALFFr5BvuBteyXMF3JnsIbxt8r6fhMmkRngfVjSKbwiUMvOvMCjRUb9B1KK0FFTddyWLegJqUkKWPxRJFAdTz"
    b"KDUbQgWX9sytOM3Y5EdPWY3u8IZiIQ2e/hLNkUjrNCXFEucefcEMogd2tT2mfgwTPDiIG7mpfg+8/DRuSbtahzC8QCRyX3FdKNU6"
    b"6qx3rdSq9yXhbTkCiqyZ7tVXXNQ/TxVRqmz7tlogY/pCHWOL8EXolaGtc8gjg77X5/MsVtEriDT9IP1gVRLeCznjgGk7mYYSWaks"
    b"oEgjVYTUbQV9DX1dBEGus/qBqu47BiWu2F4/C7YyOgl1BtHcKTAfbGhzp9rFAz8FLALuSC/AHzbdlwTnLwMRY+qt1KSxWO9M/TpD"
    b"A3JjoI91wFNa2BrTfQ/ROffcls6Q6N7EJe8tVxPRwiNKffj0JklupfKCwGzRVzBKnLJOIEGHs4/Io09pcIiueWyLdAZ5CYrGShl7"
    b"FjkOPU9m7OVSNPD7heqearuRP9t8GRj+MjRUEBKm25CkmYENdv1V2rb4vJHw63GfQWrEnoLIqtwhu+rhNCdNS+7ytWyxFEqJCg1l"
    b"h5JjTYhzJrCvbLMsslWa/IGsRnwHIT8IIcHXXXdTAAkqUA54a0yYA8IH7n21fusCA4LvNFvFbMEAr2lLqfQb66bUm1yvWirmgRzL"
    b"d99s4wZqaW7BArtpFfatRBnhEZpZaMZEBHqH128UNbqtmgD6rO4rCZ7YFp8vsgXujzYltLHus4npM3FGbmE3tTPpuv82jcENIdxF"
    b"NGifY651FxuvI8LlVgrjU33FCraeoy+CRu3EV23aJgrD9/1CvrZCaFoF80dfApDuSVezTRDWl+Xn9cHLpOSCjEzlhAbMSVYumRha"
    b"75EGkM3FilQXXkruJ9SEB14sopJh09qRMP6UjdeaMN8ggea5rGsfAnKURx/I3SdyJ57cv4LUSDUbWjmzovV7jJxcrQK3heAj9W9C"
    b"+6X6f99JsH6hJpMdvFsK3yA4y75KfNJBLA1dDVHBk20UKy3mwbWtjQWt/CT2jqYZPt+VuQJMKfp6QnAumRLyjbCQ5SWyAHUoIN5+"
    b"4PM1bt6O3rAvB0JVySJwltG3O1PvuCeGAG5VmkGQvkoUPMy6PAwBnepmSBXGxCV9GZuMCMjld5OhM/nhZyiKnWfI4RB9Cf1IWtRz"
    b"IiDC9kZ8le1v1oEjBFvXWapcAyF4ttvk58ukV2kML0e5Y+cmbQg40giIXBxhTKbYHrvQ8yhChrdpPV39xB1QAUgU9/mpopoia+UW"
    b"a4VJRpGpWR2muw6lkWvW769ALKNmUcIfUn58Uj+UanvnweEn8bW3sZjuO7u59hrRMVOEXCV2okL9ZqQi1dVfnLaaUTkYW13btJwk"
    b"YTdBva0rwMUNaImV2MzEdg9enmUR5fsQkCTvqsMCACdiz8jrmShGPjt2d26+KMmClp00I3A+XyPtoG2gFWUiY1aNmd/RpUV7pba/"
    b"IT/guHYXLpVEIJQCvI7Ps9bFblOK0YijaBUOEkOzx3MBw4PalojjUZETyOZjud5bR5p9OPoZyQ37KqZKRaRsYLZsovtIia7WAb/h"
    b"hOaAHrbmsyFc+gghrMjUSi78rOC8IxXhHRJtlpqWIj0jspHuTpr9TT+W3SZPL+oGZQUubaooLY/d4n0hRG9ANXBpMyqSmeBIv8QW"
    b"sRxRH8nv2BHja+WePmQ9ESuuQ/RLSojd4Vmqq374iIR8/KSwSPXKERWaV4NF+TypI0Zat+mlStmAohDubH6y7+CnNGCLga1DWtCK"
    b"4euV8mJwc2lktySn2/LpTJA9S3lia93Wl99t4IjiVgzbE43uUx1umSlWNqQNSZhVM4prSEqHvAhqQBBtOmN53Sd4CogoVUP6yCdo"
    b"BAgNWUaWoXA8pl/BSD++gCBFQOJns3YTeT0ShNQ0jNxyBpqBDESmwvTL8TErpHF334/gfi8QRgWRyPVRQfYnECFEqHMoN2AGF0GO"
    b"cd3mZjXqk66WNw7oyTHinvbE2KTlrkPJs+eOboU3htOBwgheBuCqQJxYFS5CfELZQOP0zpvU4bY7B0x+T0APhAwTfY1twovSi9pF"
    b"GMdnQV5+M73ilLkePKChU0qMUpLyRj81HKUboso0sxfF6RzfQB8tMZHwSCpVSC3acGmNLpm0FmkMYXfJBlj/4JBZIEhs3340P5ti"
    b"zFqLQbWlj3nj9zGMje51IlMKHpGH+xg1q9LjKLwXtkUpYebLSWwfSAcXjMBRMAP0kNKtsiBybsEDJwK8LRZ0JjclGykV6hU72Q5h"
    b"egylOggnZXQFuazJtV3erDS8BSq84TOrvXGdpGyWCs+XCaZtRurY4YXsSBSIuPOlvJfucaw8FRl9ASPMxgXZQw6BAu1n9DPVPN8D"
    b"0NI1tu5V2JW+S/xBidcaiw4KhDz2VlUq5QDV3zyRq7mT6t3v5BLpVkFUsyLvlRzTHuUX208kdo8EwVY8wlpdUmct1zVaPfMelLg6"
    b"bTuKv5ufuZSaELYx4/zxcmSDRFivmS+xVTfa3hvQxFazY00+Q/MTHxxiEHwVAuPrVagjWzaKSDLzCW+CTm+yU9qIpDlWJzo1KRWH"
    b"9mOk16A56F6PNDVPbNA6x9k7GPVVcG6X0tPCSeK2wV9JfFQAMSTID3y2JmnOGaxV2UNIFdTwyXpfFeCzY6WKbgh3gi+0fWVNeFug"
    b"0EP5DMshyEmpM5RKHRkSZmRiCPp2x0VjC4iB7sHRDGiA21EsNIToRkrP8OXWj1BGOie7+V5yCvFRw/n9vh9h+rDV2aRxlFVb5YMO"
    b"BvTaTwP80SfIGq5BmcNDfGvhJK+i7PPm+R8S2sx2UZu5F0yor8/Xepo1BrN2CN8SkujJZc68Sf9dc41livv9U0FnCHNV5bmavWqn"
    b"12vkmdWQ19B3497XK1tXWK7WrT8tiIHh46tNlLjbT5hSEqITlYm0lMJrlx48dQtcvCI8EEwtadyY1SSPS0P2ffC7QLvr8haxnuJ7"
    b"EQGC8HsgCyUBo8F7IRrPUGwdNub2FOu6uC3SEZIEocT1bY3p5RU7bx83ZkPkIQjB1B1iQzQ8HNCqJ9jDT8/JHpFMhTp3go/tKz3v"
    b"OL6c4dhqk892AS+/4sooZENpP5D2tmawLpU7FQ0gqyWkgDVCPhvxGzLMcDmfTYdEWEgOYYcK9p3UAgtEX7J1bHXKe6LvQL8x43l+"
    b"BjmjZGyzH7h7j/bQ7OLDzV2mXbc7Xxh/UzrzmvvCeGaj4MnLneW1qIOax56vzVyaxTUJbvGVZYrkC7j7k1xSZU0CPflBWYdm0tgm"
    b"bNF5yUfhjAqZ1k/9SyWCMAhUUHdC+DfCU+KhrTriHItZmMsTd1jLM9fgy0Hgnch0pETNbFF9dumcLi3PJ3zFqIiK68Qund1P/IPa"
    b"kYi7gUAw1wh0hNJIE6rU1yE/g2XPOlxxQEBf6eZckUPhYDhqRVAsZzmQDWwMVoyWOkL1SDWyx/GJkO0idBGTTzq2/W5Xoz63YeIj"
    b"n60omisqQj8gDF2oj6Jhh06W6CNFeMxXxo0ff8vs9k2D9ki7DSGlu/fHzHrBNpGGYOedtK9QipIQZwvZG0VD2aZsJxTEURKcIkPF"
    b"VMFrjGJA7zfTsK6R/pK+C5F3+vAJFZOi762wk8H2K6Mv/9xkZzxXOv19+CfN/gc/3HtwLOBOem/oRdZOodlhRkN7nUP3qOUcPevq"
    b"gTlns6uWvzY0li26uF12qSlygZfDAVu+2VDVTzLShOBN2TNz+VyVVslKI69gzyWjdK3fUg04voMIL+g1rcMmV60HnpXWCEp5hDLI"
    b"gnZLmlJwlZk/TDjZuyOb8pXcPTH8GhKIiqBgOFFzbVOjG7bUO0isTz2Qyw5BHA8u7n2yFsH6KiilEAT2HXSper+ereL7OLFvihf2"
    b"E34NVQrRAYAAgoCAlurjnQHdD5X48mrOhtnAuwnAnevlNAh5DZ/y6CSEcIBUZASzUJIHzfKzR0L+vjUWozKEVITIWMpwlzLWAhUH"
    b"aBBuYHYsI/fBtV/upnprT+MbKzdF3vowS/GDV8axw5eNqot++upl1WvPqc1fWG3cEHDniGUKVaWoIsdVBZj1ZyaN+3sFPrsne5Fi"
    b"mZPZ/BN8hbG2rM+8PxmUkGsk38FK4oKApJwuLzwlTn3NxHuZLqT0r6RoejuHYXHMp+nMjmP02btvSj1yHdnBKn22UIZV0Zcai9JO"
    b"/V67QrPWMTpbUGqdo/FWeqz/SOWZTZBAKq0difadtr2xNQUjMz9vAIVfiDX8QSU+H4vk6DusN5edy+5EFJ5pe0WcvZ4cwSY3bXNT"
    b"FH3qLZlZpYTpQy35nm7Y8tzz3uEt+RP31j5DBZ0asVEI6bEBEb57FIHeEFw0rYdrRt7XmA0/BTKPDzeWUQu+F0V7y9bjaAodoC+d"
    b"5QfOhYULxCYAjUEwx8Lq4pLwuPCDDW1+3wRvD54bHI0dOOGe32W1+cbGjtWKK0UrYy9/1P24s3Mo42l7Jl7I0wirePlNjmGUCoc5"
    b"uLm/w+CfzT9bj9W5zk3MHLgyEa8tWDPvT3BoKVs65Zxqd6SVZZGDSEPqsC159Wwyih2aED6DiwPU80ATS6MOWcht1XnZWOoJVYom"
    b"TIeLYzUpi44oQxPVXeKW1kdnnPBeG1t3fVFgwNNTPII3r+QLyXsKPw9sZKk7XXn14q2pVU9KDc9DKRpvJStmQ7wueGJYhzWIy2xR"
    b"Jm3D5Y28MhCJM1cMhOaIoyjI6ad8Px0rjwpfYTyKrbDeE3Euc6Sl7YfUmN5OksSvJ3EPgcimIuwN33cCg6gS8k8YrWhaN6TuQ1PY"
    b"jzBXrd+HklrwCMWPj1M8qrVF4D1tSxlVrGQpZAYhRHiIJPG9ypwLfa387fbGz36Y+WKjwjN48w3Tji8SvrCy//FU1+WugDtp8rYh"
    b"Ml7LzZqohC/0+3fQQU6pe89a5s1T2COhC4s5Rrsafp5/kbO5MSco+uIh2VTj3bArnkWZtNo/pddoTKOpk61zWumz2a6RPAhCX3R9"
    b"8gpbIm+Mw5yk5BboPLcZKJvkKe5xuwiQ7e68Jzr090cLFvwCmE7G3j0hM61xXb1O0+lj/ol+/GUCJnjYiybSh5Bi/Wh5feIoBtLX"
    b"CCxQQfaINNI6a4xIbZWTChx0ALHeLjBZKtWPRYWMSDGztpEhsUFIE6buqs1HPkwekF0Ubf1UBOwScVIaZCDdXnA9jvl3g7RU21c4"
    b"Hngc2a6puxcyIadL4b7u4ssniWbQ500bg+p6X72gPNp5y2M6wz98x5Z0v5jw0Jq1LcmzWQtfc7fD16t8Mzi1Zhl1a291y8LOK8fO"
    b"2W1TXx2rdq3vz9rLKOUKx5M/5qZzfa/rbGJsOtVtGkxrYalvWHB5KmPP8EZQVG7SOc2AUmubCJpWZjNRfZkrRiU6lvu8Y8ftO8En"
    b"K+oETuZh3qzVDqUi6Wg01L+ek5krJJ4DP45Jk2Prjm6CVMIlNEBGE05oiHB6jS3FytgQJhov7sfzfKoNeM4Q8+RM8MhEHPs/Ydoj"
    b"VZyztg0Rz+DmVg5W96WlWBsrrsed20KFIEQj8n1cZqX2OHYQpIJ7LMN9plGRyEjwUJ90Gm6PrB9YNO/cB/8q6YkDP9uAzd7wY+/d"
    b"yjcZnZXh5X7uLJm28MBLs5uVY03rl/NYetzaX33mfXi81JlJr0xXs+Am33eZlr/COwsEZh8KhbNRKphj3bnmF0COxEijEV1s4YmS"
    b"El0nvrATrbogx5cYIEjBo+VeTGBPYszENyzIxZ1IRhf3pmJ38ZmAG1bI9KItgNPPQU4QCQTH9vYwk5bf/XFACLl9fgOb/7SkkpnL"
    b"XDMI1AloUB9M/2YoN0hkIHVG1qqm9ZBqhJSGWDH1+Sw/iIWC4Djx5Vs52w4UqkBpD16Lx4MNry1CBlFVINDu3p9R3iMRgjZoTKyl"
    b"EBmjMWAnAl2g8pfNFQTom9AI+/Vm0hD6LYbHhjb8+GXR6RuX6FHTdgNxdbMZs5MgIm/PD3kcTH0yuXyz+YstGUmv3EBgHIPgS+S+"
    b"3tEEw+cT80ECP3GG1EtOQ8JnL9DX49iBCKn9ELJa71Je9WdSu/HQ/XPlTivi/fMpUvB2UhmqvDPTx3BDKJEiJwi7hFtGpkvdcO3d"
    b"YVCw9DiUF7cnl3/wabOnQWGdqPMMpAJUpyxCswOgA5AMg5VgpPbrKBPB3XQRF0GCJaIhg+5IeT+WbWKV220LBnvGMbc7jo1aIsqd"
    b"kSoq3J2wmSl1M+gSOxa+Q1+1hthQC+ZMRN6Ssk0joA+nYP/urJt2EXeCA1Ry5ysDMlXuBCGlJvk4JQGE5uXPu4+fi187bJb4ap+2"
    b"/uYp+pF9C6MLO7OOXe4H7GN14N/Bn8qejzfeP8hV1vJduk+52MSsumZ4EejvZNvYYBaalCQJ+RquXSTWUWNQAi+0lzzsGk5BtgvS"
    b"v4Ft+MSJtB/Y0D0QoEnSU2TtMN5LXzEiTtsaI6eo8LpD4yi8p8GAHEACop+Vr7yETPGYOxoG8W3V71EL53xMtsv3EEDhhF2y7ejd"
    b"wbpUxnq99WUXyCfi20KxHrQegW3yvOFO4slZY7acBrjEFT2ErFo2Dz0cYsxGxIff675YCVn8nUr/j38CTdRTa/C/0W6fUaz0EBQp"
    b"yIdbusLSiXiT+cpqb2sO6/n4ctBjTt327iOAgo2CGv6EKYZZ35/8IlkCzOedQcI2fQeqQLfXVrIRI6a6reBpce5sbTYewd4oD1wf"
    b"nO0+ecpJnDY+LH10B1NLjpUC6iAqGHfsJnLZNolkWF4yls1L8PrKxmNvGIsB2RvyQ1eNpsMxbD/6u40bqpy1bsTZPdIeNIIDngcP"
    b"5XB3ZDZ19nqczBAWMlBQom+3NvK7bYZ9lvXk1yA1ostb4i6aicX7ujClEPYlxTbAnAbNwpgIXHI0YDv93d3yPUG//vfwFwWFMFhI"
    b"dHIe/CN7N5GdxpaX+L4F5ivi1LuzN6ITqnfA1848TNYWdCUzfT0+pV+2Vk90KFvgdqROTXJh+giBbUEfiWZLya8BJlK64sLrrW8T"
    b"ooFfUaywkCHmrD8AACE2DQkw8qhgzVs+VHA7Ani872BVQPDlPMXFD+gslUmo2/CVD5mf0a7ShuzO/CJ4bbWRkZ4X3URDPuWZWIvA"
    b"Lwb+bWIgqpQBAmPIkOA5+sgUVxEuZJdZomNrfH44FjxKbug2r1WhJAcE/GzfVZkT5s71OHu9/d4BN0S0PF2scIliBg7dAfH3iyHi"
    b"1rvgglimrDeXF+JT8gN+2zDCoYWYa+B0s1roa7na6bJ+2YOvr4exMAle7XmE8EJxVd8eRwlJarjelKnp/ege7ygIp9mHBNRflGoW"
    b"jYIMTLr3ysNBdNUG+hrW6rDASZw+PFQ7HDgC4pTkJNcPwrZQrFcOCCiF1HiyCaKBepWpU6DDQTFbSYX42ebTeIicJ/yPGZlFrC80"
    b"hR/DtuYB7YQQl1vjTsrXYa54VxcevQlAsjtWb849rolHQ7hRi+Enopccz6pgURLJ/z8JgRxJHdEJQvh6NAjREZcYAuF+M/hFpgak"
    b"S4EeShsR53+br2h0qYbPXfBKoLpZu4ktRFkUFGIuJ2Cl+t4Mfd97PTYhLQY4gZfd4U4ytTh8CCOFXASfoEPE2KMoo+G2YQVs/rEb"
    b"9XAlRVGG9kvo25w9PEfqMtGeBbCPgfBO1DNN5CEDHPsr4aOqiyiDQM1L1y2RAg2TdpbnSBJ1xP23TTg85blbOVtPs2edADeyIRQI"
    b"cAgJcsKyU9mgNiBBB/jZRA0hr/qE9O/WtEbW3fIa9P8eMYJ9mO3bTyy4cVK2xMhlFor3ygItYNHGiQyv2vn1ZnhuS/qK1/1b8w1q"
    b"eEBlWGKoyM5xmJUn37LO0koDb1frqvTi6F9qV3rt9SBmGcCS6dPDcpo+ioWOTAORljujhFI54jcMm4aLGMIADhLqIRufFsbpQNEi"
    b"cNpnJ5pxpGKpDil5d+v1eioPb/FT/e4tNKcpMfzFQvZ/xkphUyE7NTKcpP+2YBuik7IPjYAHEwevR8JpjzwirZUlIpwNYC9l4l2Y"
    b"Gx+SIkMVRcpDCP8/qsNo8AiRfm1eyFBBwVspiAWWWuQ23hHHeWL0fBKXXul6pEAGKqs71zYy0sj5NMYKHq+LncZCce6+QXeuJyFc"
    b"ERIIAmjrOulLGJFOIihD2CdAoNmJGClrfe8OqIPWKNDtCVOyZpRijNQZuqpxR0pcG487L+PrNWmmsH/UFIHhxTWyZdgSbwZWsM2g"
    b"4AHcSn69qEO06ejlMtZIl6jRW4aK9RlFSnM/0Zdr1o8+XVq74gL3wEHwXIXmQMCmLqLFFFtsA+Q66xDyvzrI/+cfGdsK88I6uCM7"
    b"umeQ4fz9qAhbh2xq+HjBH7QOMb08twddfMInBKIinJrarPTnMlh5wPjqydlUNsZfnvqPcG9De8hw627Y30I1MLjICOdl0kKeFFLF"
    b"xfuglxxCxGiVoVBUMwIMrhmo/0WIaJjX+vOgeQgfGcT0LiS7inpS8+HlJ7YYlLIf06RYXSwNZKIBPsQcYq24Mk5CkB2t0e296IDc"
    b"pfYYSgFTIjIkgChRRfvQ/w/ZQgArkcp5767rEaXyuMu1K+drVTLg3C3ktQqAPMR5wbRN+BnZIXYsRrvrsknrKU5caScb693Ll390"
    b"0l8eCRBk6PIkj7qM0f9GZSidhyBeADyyeiGOZ4YEY9sti/VSDiH36cKvf41o8jkxvPUiS1AwnT4SDedUGnSR3phNhtzZgJjAvOCl"
    b"1jcMl/T+Pj7lA8CoGKwKtaT//gY9MAmJVIX53w+zRkZR/3fKTJ/83yEyML/z/vPABs6SRc8NnJ49wl0F6J7C5kdjfS1E5hcQVAzx"
    b"UWGKMYTfw/+l19fe3TgU5F4o4PJQCQLIrr1h4zKt7eFto0LnvXmu9vof6OkZqqiUPGDM+dkAGMA6kOTnYcsIA08GAxCrIprpbb2E"
    b"mX1foKSSJBSF03+PCvj4vQNkAjRjYJ+e961Ax/9PelLo3v/1WBB5EF+fLB1A/p15WDlO9J94AMZk/HeQRxxzz8tkzbkdaVQkpDQX"
    b"EyDva+CYr5McOx6CQUF4ytah4gX5NGOrwT6CcqQGUH5PZv5RrOATBz/92V86NL1VJwIijKn037e5KQoMWSDCoHCCsEchNGuknk2V"
    b"2htqCFi5PlIE7IKEJFyPOiKRvrQ9L31EqPe/YNShYRT8L1B1183a0v5jC4AP/whrjuhhOyCc0O8fRrCTwiOUITu2F/quF3GEtyfl"
    b"tL9/HfU/c/8HUEsDBBQAAAAIAAAAIVy18Fqob1MAAGyCAAAVAAAAdWlfYXVkaW8vc2Z4X2JhY2sud2F2VHwDlCRLG2xmFhrTM7Oz"
    b"tnnXtm3btm3btm3b9qx9d1azxqCnUcjMFzv/Pe+8d/PUTKO6uiq++OKL2N1bTWrXqNFtCiEtK7eo3qP/sMxJCCEUa9JZPBhJCSNJ"
    b"SLfOwzpXmvK/14VkeOPvTyEJ3uWS/vdc4j8Fz//ux//bS8Grf/f6+z79by+BT9iS47cpbWnJIH4HpB9bPJZXxsg4bD/lL/lDfpPf"
    b"5Rf5GetD4oqS7+Rb+QbrlXwhX8rn8hm2J4nrEdZD+QBbZOK6n7ju/d/199n/3nmQuO9j+RTrBY70Csd7i2N/kB/xTX+/8xfOIFYm"
    b"4JwMnKnEGWvESUJIOIkgyUlqko5kIllJdpKb5CMFSFFSgpQm5UlFUpXUJLVJfdKYNCUtSRvSnnQmXUkP0of0IwPIEDKMjCCjyVgy"
    b"gUwmU8h0MoPMJHPIXDKPLMBaRBYnbkv+2/73/O8787DXbOw9DZ+aQMbhGMNxtAE4bg98QzvSijTBt9YiVUg5UpIUJP+QbCQ9SUlC"
    b"iY46BHEt3+V7XOdjeUtelqflIblbbpKr5CI5U06Uo+RA2Ut2lq1kY1lHVpZlZTGZX+aSmWVamUKGSZfUUDZLBES8iBG/xDfxRXwS"
    b"H7DeiSist/j9HttHvPpZfMcef0SCCApbMOmQoTI5jpNV5pGFZGlZBd/QXLaXPeQQOU7OkEvkOrlLHpMXUaGXMhq159IFhLOTQqQC"
    b"sGxJupFBZDyufwXZSg6Ss+QWeUyiyA+SQCQJoclpRpqLFqSlaWVaizamLWkH2oP2oQPpcDqajqeT6VQ6g86ks+gcrNnYZuH5NDoJ"
    b"742hw+gg2pd2ox1pK9qI1qaVaElaiOag6WhSqlOLxJFo8prcJ5fIMbKTrCbzyUQyGGfUHHUuA5TTkzAwOl5+ApNuylNyj1wvF8jJ"
    b"cpjsLlvLerKCLAoc08pwqcggUPkkXoqH4ro4L46JvWKbWC+WiYVitpgixotRYqgYJPqK3qKn6Cq6iM6i43+rM1ZX0UP0wrsDxWAx"
    b"QowVE8UMMU8sFqvEBrFdHBAnxAVxUzwQr/Adv1ApKkNkKplF5gPm1WRDIN5LDpdTcHbrUPsT8ho6IEr+Ru85SCqgXZhUIvVIWzBq"
    b"JHi5lGwiBxKxfgEEYokgbpqKZgfO5YByU+DVmw6lE4HnErqObqP76Ul6gd6gkfQpfUM/0C/0F42lCdSgJuUQEcoYU9jf/ygT1Mar"
    b"fhpPf9Nv9BP2f0rv06v0LD1Cd9D1dDGqMxpV6YCKVKKFaVYaQSmNJW/JPXKabMe5TcRZtiSV0XupoSo/oQAXgfwyOV72lI1wvdnB"
    b"OT/YeUccF5vFXODVRdQXZUQukVRQEcPf8vv8PN/PN/KFfCofyfvwjrw5r8Or8rK8KC/A8/DsPAvPyDMkbpl4Vp6T5+WFeQlekdfi"
    b"jXl73pMP5VP4Ir6JH+aX+VP+lZs8XOTAdzRB/SaLteKouI9OUGRGdFMLOVQulPvkXWiLBqwrkQ5g9GpykjwDw8JpXlqTdgWaq+lx"
    b"IPEFeKViBVkN1pYNYtPZSraXnWP32Fv2kwWZQ0mqpFdyKQWUEkp5pbJSQ6mt1FHqKXXxu5ZSTamolFGKKP8oWZSUSqhClXj2mT1n"
    b"N9gJto0tZhNYb9acVWK5WVJmok636SG6go6jnWl1nEUYjUe9z5D1UKeuYPg/xEPiwOwTci1UoqusJfPKJED2jbgidoO3o0QnUUsU"
    b"FemFLrw8it/lp/lOvoJP58OBUGtel1fixYBmFp6Kh3Enp9y2g7bXjrX/2L/s34krDs/9tm0TrmOf5MA7Fy+EOtQAzh15Xz6Kz8IR"
    b"d/CT/AZ/wX9wi4eJrKKYqC3aoxNminXiiLgNDfKJUJkNWDeVfeRUcPwo9CQaWpIS+lyTdCKjoKV7yBXyhnihGjnA42a0H50CzA+D"
    b"t/9SL3WwDKwIq87asP5sElsKvI4Dt2fAL4FRJTwR9aJKBaWm0khppXRUeih9lUHKMGWEMkoZo4zGzxHKELzSV+mqtFeaoyZVlZJK"
    b"XiUjPkuVOPaO3Wdn2Ha2hI1l3Vh9VpSlYYRF01t0H50PHWoM5UlCY0gk2Q+t74FZkpFYmE9H0LO9ZVWZSZriqTgk5kAJqogMwgAe"
    b"R/liPog3AGdD+R/7kX3UXmGPtTva1e0Cdkqb2D+tF9Z165i11VpuzbLGWUOt3lYXq73VymqRuFrhcRe8NgTvzbZWWNutE9Yt618r"
    b"3nLaWeyydnN7qL3YPogjx9vJeRnegU/j+8B3znOJRtCs3eIZNL4Q1GW+PIMZk5rUwGTaDoWmuJr2UNuTNJomYWVZd7aQnWRRTAc3"
    b"GwG15cpJ5YWSoCRVC6i11M7qKHW+ukU9pl5Xn6of1D9qUJWqQ/NoYVqElgQ/QzRNE6pf/am+Ux+rV9Qj6kZ1rjpC7ajWxBGSqn7l"
    b"tXJGWYNKtFSKKxHKL3aTbWajWROWByi/AMZToPH5KaMvyV4yCQqeB8r9BLNnomwm/5FMvgK2s6C0ZUUKEcsj+R4+Eyyugd538h92"
    b"JLBdZU+0e9mNgUsuO7mt2HHWR+uZddM6ax2xdlmbrDXWMmuRtcCaizXPmm8tBuprrS3Wbrx/Dvs9sd5bvy1uhdoZ7UJ2Vbul3c+e"
    b"bK+0D9g37Cg7YEdAZWryLnwiX8tPobo+nhxMbyqGYEocA9IBkQrq1hY6t0legVNx4BrqYzouxnR6QQySjlaAMk+mW6Cm0VRjOcDm"
    b"bmwq28IuQj1MlhL8baD0VKYoa5Wjyl3loxJQQtUsajG1htpS7aWOVKerS9UN6m7U4Zx6Vb2jRgLrZ+pzrGfqI/W+elO9pJ5SD6rb"
    b"1JXqbHWM2hufq6YWVFOrVP2m3FeOKMvQBS2gTcmUWHaX7WATWUtomcpe0wM4s2Y0Jw2Qm2Ql+F2cqOSR3Cj74Zp0+URsEgOgn07x"
    b"nG/lQ3hlnoS/tw/bU8DBPLZtPQbCk6zWVlErzPpp3jH3mHPNAWYzs4yZ1Qw1DeOr8cK4bZw3jhn7jJ3GVmMLth3GXuOIcc64ZTw3"
    b"vhhBI9TMZpYzW5pDzSXmUfOZaZpZrNroiY3WPcuy8tkdwPXrtmUXwUTYBj1LI5qLJSJSeOBZZmG+66Q6mQoNobQi3MNZGqDFoNB7"
    b"WDTLgH6fp1xR/EputY06Bxh9VpNopbVO2gxtj3ZP+6W59Rx6Rb2F3lefoC/U1+u79aP6Gf2ifhXrsn5BP6Uf1Lfrq/TZ+ki9m95Q"
    b"L6ln1JkerV3XtmmTtfZaSfTAZ/WMukDtpBYG2g+U9UpvpZgi2R0oSluWnf3E/ByDianT+5iRrUlm8lUewMwvD/cWKVZiBuYTQX6d"
    b"L+GdoLCEP7a326PtBnYOm1vPrcPgax+rjpXXCrVizefmeXOHucgcb/Yx25h1zfJmETO3mdlMY6YwI8wkWEnxKK2ZBa8WMSuYdcxW"
    b"Zi9zNGqy0TyG6nw0LTOFVciqj2POBv9vWz+tMLswajnW3mzftGPs1JgNffgyfoF/5ylEZdFfrIF/SRBZMcEnYFa+lk646u64kssk"
    b"hmSgdekouIPHVNJ8rBU4fYC9hKXIqzRTxilblTtKrJJCLaO2Vyeqm9XL6nuoR3qtlNZU669N19ZpR7Sb2ivtp2ajDqn17HoB4FtB"
    b"r6rX1Gtj1dKr65X0MnoRPbeeTg/TpfZbe63d0A5qK7RxqGEVLZvGtCigv0ztp1YB238q55UFSjtomZ9dZnNYU5aOfaA7MVEKYoYe"
    b"h8svCdd9So6UJTAvj8HZFRXx8ApDeBEebx+zh9ulbMu6ZE236lnJrbfmTnCykhluvgNfZxjtjOJGmPEzeDu4OzgvOCTYOlg1WCiY"
    b"ORgR1IM84A/EY3kDgYAMuIIpgzmCpYL1gt2CE4PrgueC74KKkddobkw2DhofjORmbXOyedYMmMWsYdZxK2iVt6fat+2kvB0mtZdX"
    b"hId8I/IgAdyUqUhPcoLotDndCm9Wic1nr1gOZaBySiHQ2LnqAzVCa6wt0u5rDqA1Qt+j/6t7HKUdXR1zHYccTxxeRxLnP84qzpbO"
    b"3s5RzunOBc5lzlVYy52LnLOc450DnR2ddZ3Fnemd1PnRccWx0THa0diRy2Hqd/U1ek+gb2lXtVlaPS1ce6AuVOurbvUGtKqc4mMH"
    b"WU+WkT3HnKxKTXIYZ5qRPJPz4Gw5nO8gkVd84VvA60w8yt5odwGnf4DRo62qVrj1r7nXHGc2RO+bxhNjvzHb6GXUBkZJjEDwffBe"
    b"8HRwV3BNcEFwWnBccERwaHAwEB8WHAU8ZwWXBDcGDwQvBB8FPwetYFIjn1HT6GpMgbpcheJ4zMLg/WRo0TOTWQUxS+dbF6wYKwt4"
    b"Pts+D2eTB+e0ij/kTjB8DDzhb5ELOWsdpnoEqYs8d4mYpBiyyi54sXRg0Rx2hRmsoNIdkyxSoVDmHuoKqK5PzaY11MZq27VIza+l"
    b"1yvr3fWZ+k79ph6tE0daRxFHbUcHx2DHVMcSxybHXsdxx3kgfMNxy3HTcc1xyXHacdCxzbHSMdMx3NHZUddR1JHaYaF+Z6E4Q/S6"
    b"elbdr93SVms9tWKaxPctUJupqdRXymo4nRTKYzYPblTAnfalWegzuJNyJEZulk2kKo/DjaQSt/gYzK4oexGmWtDaD0+RxnoMNahu"
    b"MvOiMcGoZCjGzeDCYKtgtmBc4HJgWaB3oHIgfcDwv/Kf82/xz/WP9Pfwt/Y39Nf0V/NX9Vf31/U383f2D/JP86/xH/M/8sf5UwTK"
    b"BroHFuPTCYE8wS7B9cE3wXRGR2Ob8csoYU41H0HNh2HKZrCH2fftnHwyfH4Z6J5PNIMbTIrc9pAUpAuQTOqwnUxROoDZEZh6F9Sk"
    b"WnfthKbqjfW1wPMfR3/HAccvRy5nJ3D3pjPgzOaq7xrqWuE67nrs+uki7gh3ZndedxF3Saxi7gLuHO5Ubofb6/rXddm1zTXV1clV"
    b"2hXu+ug84pwExidzvnasR3UyOF7ry/T6uqqfgSpl1h6qk+Bc/lVmQcWj2Gz4wX/pdFoA/mQynPdTqGBu+VRMgmq/5rN5aXiQ9fAe"
    b"un3eGg5l/WXuNnubec0YTLxxYGUy42PwaHBmsF2weDA8+CtwL3AgsCQwJtA10ChQIVAokD2QNpAsEBbwBEID4YHkwD5noChq0DTQ"
    b"IzA2sDSwP3A78DXgCOaGlgxBP1wNxgDdOsYYzNN3RjLoyCTzlBlv5odb3GFFW9nsrvZWO9rOxXvDEcby4mI0EqgiayPpPJPpSGfk"
    b"5d+kCFT7PMJfDTA7kkUoTeH7nisp1eZQ0kdqmFZbm6ad13xaXr0zsLmpB/VcjmaOSWDwE4fpyAQ16eqc4tzoPO187PzmtJ1hroyu"
    b"vK4Srgquaq5artqumq6qrvKuYq7crjQup8vnjHJed+5xznX2ddZ0ZnEajkh0wyBHeYfT8UhfqbfV0+v/guXNtFDtmjpazadGQcXL"
    b"Kd/ZMlaBfaULaXH6BukyG7mJFOGRB0Vj5JrlvCR/bY+HH75u9bUirFNmJ9NtHje6QEEuQy9yBaMCKwKNgeoD/xJ/S39m/0/fGd88"
    b"X2dfaV8KX0LCi4QLCbsSViTMTBifMCJhKNaohMkJ8xM2JBxJuJvwNcHhy+tr4pvg2+9770vpb+Sf74/0Jw20DmwLxAWqBJcHfwar"
    b"GRsNbrQzL5hZ4eJjrdb2VbsgX8fdSGDfRCt5S5Yiu0kapHGD9kLaq6YcUtLBy/1Wm2qntLT6WP2VXtyx0PHFUcY5z/namcPV33XE"
    b"leAq4u7n3up+7tZCCoe0ChkXsi7kVMjDkOiQhBAZ4vC4PS6P5rFDYkLehdwJORyyPGR4SOOQPCHc/cC93t0TvI/HUQahHp+g8nWd"
    b"lmO3o7lD6Dv0enqsthRK8lQdqkao+5FMP8MHpmXHaAP6nUwjmcgZZOJ4sUgUEPf5AB7Oj8ILc6SPhpZl7oKmus0LxjAjv/EtuD3Y"
    b"HQj/DhwPTAzUD2QIxPqv+zf4x/hb+Uv7M/hV/x/fG99d3wXfUd8+307fdt8O3x7fId9p33XfU98Xn+lL4s8DNenqn+rf7r/jj/en"
    b"C9QMDAO2zwPuYEXo/cHgj2BOoxtU5LORC27noOkzy1nTrEgrNRh+EG6wFvJnNC8qpojHcCdD5FWZjHSD41bhZrfRBFoV/us9K6CM"
    b"VW4qyeBAdqqxailtIpybC0gs0CP1UCjuDMdlh+Eo5OzmXOm85fQnaspw1zrXRdcHl3Sld5dw13d3dg91T3UvdK92b3Jvc29HbTa4"
    b"V7rnuSe4B7jbuKu687hD3b9dd6AxY10NXZldf9AXU8B0t/MOlL0KJulBvYueVL+k9dNSahfUrqpD3QX0v7JpLDM7Q5vSn2QKSUMO"
    b"IE2+FP0EEct4bn7ebmJ/syZYKaz9Zg3zPdQkjXEKnsMObA7UCsQB7Xp+4Tvi6+PL4fuYsDWhV0KhBNt717vRO8LbxFvYm8Jrx3+L"
    b"fxV/P/5G/DVs9+NfxH+Nt+KTeQt6G2OfTd4HXppQCrw/kuBLKOeb6Xvuy+Of6H/pLx5YDhfTPngjWBgMTwIND5gDrC9WJ/tfuxV/"
    b"zpsj7zaTT2Uz8pQ0o09pU/aINVTuKTXh8ErDnWXTV+i6Y6gjylHDuQ/a0N9125XVPdJ9y50ypFPI9pCvITk8HTxLPdc8sZ7UoeVC"
    b"24QOD50TujZ0V+ih0KOhh0P3hW4OXRI6IbRHaO3Q3KFK6GvPPs8YT3VPiOd+yLyQWiEk5Ji7uzuZ+4KrhyvEdcDZwPnLMcuRxXEa"
    b"/jxaG6E5tdVqbvWkUh0TsiP7Ba3T6BKwe78sK++KtuIXn8CT8p12Bfu5NcjyWHvgpH8bi41S0OoFwXLBP4Et6PPkgUf+xZh2af3R"
    b"YO4kX1PfPz7F9yHhcsL2hHlQjG4JzRPqJFROKJdQBlulhFoJTRO6AM2ZUJDTCc+BaWpfeV933yLfed9vXyYcaY7/ql/6ywXGBc4H"
    b"SLA6POSzYCajj3HK0M0W8JqmWd/abAWs+vY227ab8wPcgdx7DulysLwvcyPjRJHSdBn9Q2shQ5usqbJXYWor9YDKtBbaLs3QasM3"
    b"fNYLO8bCXYQ4GzmXOp85k7uauOa7brqEqyhQW+6+6v6DOpQL6RgyEcpyMiQy5BOURfGEeVJ60nnSY0vpCfUwjzfkfcjdRH0ZBn35"
    b"J0S6H4H/fd1F3UHXaddIVxHXD+cGfIdw7HE0dRj6Or28/gboJ9F2quWQgzopMWwcc7KlND3dTvKRI7KUvCCqiJu8Hn8IJ/ba6mR9"
    b"RVYMwBN7jNVQk1OBOoF3/hH+JP79vnq+mIRlCeUTvntXe+t7Ne+l+EnxVeND4l/G7Y6bGNc6rnRchjg9LiH2a+y72LfYvsR6Y7W4"
    b"9HGl4trETYrbF/dvXNL4+vHz4h/Fp/X29J7xJknom3AnoYBvuY/4B/o/+FsGHgbqBu8E6xoPjOZmlNnLSrCmIOlvhqJcEy3ldzmO"
    b"hNPNtCi7xpop0cpglasztSRgdhrHWkcaOJAw1zSX39Xd/dBdMmRNiBHS1LPbY3lqhS4OfRaaPKxB2NSwI2Fvw5TwbOEVwpuFdw8f"
    b"FD4yfFT40PA+4W3Da4bnDw8P/xV2LWxlWI+wQmG+0BOhQ0Pzhr7zLPKU83wOmROSN+QOqsVdS1w5XMedVZ2RjlaO93oP/ac2UItT"
    b"h6heZYgSzwazWLjUP6Q/+SMHyFjkGT8fyxmfYye3N1kFrAtmIzPaGGskNw4FG8LhLQ+UD3zzr4Cbs6DMA3z5gfKxhAngcbqEGO8N"
    b"7xbvZG83bx1vMW9WbzKv00u9iEXxxKt7k3gzegt4q3rbeId7l3qPeV96pTcPOmB6wsmEXwnZfO19a3yvfGn97f1b/T+hIJMCkYGM"
    b"wYHBK8FURn/jmpHBHGk+NgtY86wfVm17t+3m/XgkLyyWiaBoJy/J7GQW+UUa0WM0NRvLolhlpEdV7a5eg8OerEVpZeBD/ug1HOsc"
    b"cY7qzhXOL85irknQ3KTulu617n/d6UJahiwOuRVih+T3tPPM8hzyPPMEPClDi4TWCe0YOjh0Yujs0EWhS6ErC0Knh44O7R3aIrRC"
    b"aFaoy3vPKc986FFeT0LI6ZAxIaVC4tw7oesu9zFXOxdxbXZWdL6CW9EcK/Uc+hGtrHYFueuOUle5w2qyq7Q8PUHyk20yrVwkNDGG"
    b"x9jdwO1G1g3k7xNGQWMvmL0Drm63v4D/hK+S735C+4Q47yxvNu/l+K7xrvhjcV3jUsZFxs6NrRebNDYq5kDMtJiOMZVicsZExCgx"
    b"5p/AH+MPjQmPyRZTPqZdzOSYvTFvYiJi68cuiH0amzlucNzNuKzxU6H0TbyXvEUT9iTk8G3z5fLv95cMXAs0D34LjjdSmIfMesB9"
    b"jp0XmA8WKeRp2YEw5PY67DdbqBRSH6oDkMC36mUdDx1dnPHOCS6He747PGQ+/MZ4zx9P29CroTnDpoHPhcMnhd8OD01SN8m0JCeS"
    b"fEoSEpEvomZE+4h+ESMixkSMihgU0SWiQUTxiBQRsUluJFmRpFOSnEm+hG8ObxnuDD8e1j6MhG0MLRP6yNMN+jIxxBGCb3EvdHlc"
    b"M53EOcLxU++gP9QqaQfVjOo8xWS92DMky8MkM1kopRgsPvFWPNKuYV+0ylqnzTLmOaOKcSfYIvg5MBL+eQcSyifMsYK+1wmzocle"
    b"7wFvf28hrxF/PX5lfL/4GvHZ4/X4X3HP467FnYjbH7crbmfcnrgjcefj7se9jwtAMQrFN4kfFb8Zs5LHF/L28G7wvvamSWgDRf8M"
    b"7Rjju+VL7e/rv4jM0z9wI5AlOCH4b7Cssc4QRifzmpnHWgAVaWtfQb5czA3eWdwWheVqSUgv8oAUp+soZT3YHXiSRUqc0lg9BKfd"
    b"R7uhZdZH6Q/07I6RjtuO1M4eyCe2s5prjuu+KwzuYzYU23QXwORcGHI25HNIiKegp5FngGe2Z5PnuOeG54knyvPZ8x3ri+ed57nn"
    b"luekZ6tnrmeQpzH2dHnehxwNmRrSMCR1SBT0u6M7nfupa7arnOsn3GEV5zfHPEcBx329D/LPeq2odlNtrf5QRimaspilZ9uRe44j"
    b"VV5Ffnggmos3vDP/ag+w/dZEy2UtMzObB4zyRmSwczAQWBDIHbjm7+bX/XsxK2XCgYROCSkTHnoXeBvCi7yL3w8FbxFfJD4i3hcX"
    b"FXcv7kLc8bjDWCfjLsc9iouO43Fp48uhIxbEX4iPj8/r7eXd443xlsY8fQXsZ/qifdX8O/1hqHR0oGnwWrC0cRDOcLOZwVpjpbFX"
    b"22n5Wp5RbBbZ5U75D9mPTHmYFmGHWSFlv5JH3aqm0xZrmj5S/6I3cZx1ZHVOd352VnGtdcW5qrmXuN+6s4f0gDd5F5LCU8Mz1LPO"
    b"c9nz3mN7koXmgIaUC60UWjm0fGix0FyhKUNJ6BegvN0z0dPMkwM8Pg98a4ToIVfcY92F3dGuZa7Krl/OZc4yzihkpsyOi0g4fm2R"
    b"lke7jGn9R5mqpFb2syrsBe1HKV0J9bgm20mfWCDyiOu8K/R7i13d/m4tskpZn8yF0JFYY6vRBlkyEp6hfjAi+CKwKdAvUA658ZP/"
    b"LPR8mL85fHdmv9sf8H31vfY98t2G077mu+G7g8dvfN98AZ8LvryYv4G/j3+Wf7f/HpJ7auTMfoE1SJhmID9quCr4IOg0qhoTjXOG"
    b"ZZQ1xyLZUKuaNdt6YKW028OV/LaL84n8Fk8q2okdIlaUkdPlA5mGdAXeAVIJSecRTcM6I8f/ZkWUkcoZxVYqqBOR5blaBt7gkPZD"
    b"y6q30ufrl/R4PZujsWMC0snj/y9TnnU+cf5wCmcSOOn8rlLAsqarrqsetpquSq6SyDUZXKEuwxntvOs8BIczFB4kr1NFmt+Po9V3"
    b"pHF80vfqg/ViwPy4NkQroH1VNyLZutRzygAlo3KfjWG52GM6nuakD8koaMstOVCmlOdFNxEijvK2XOX7kXuYfcBqC5afRvrIYD4y"
    b"ZhoVDTN4IjgMST4YuBCYgWyZMRADT7faPxT5sJA/md8ESx/5rvhOIDXuQu7Z7TvgO4VKPPN9h+9Ihxq19U/y7/I/9bNAsUAvVPFN"
    b"IDU8/brgh2AeJKtLRjhS7BFTt9pbx6xQuycSZSY+jr/hpcUqTMpW8pRMTUaS56QYXUpjaT22iylKW+Wo4kLCOaRSrZG2TvuqFdSH"
    b"66d0Qy8JF77P8cGR3FnNOdi5xnkZnNdcWVxlXY1d3VzDMEFnuxa6FrsWuebBzYxx9XW1BcoFXSlcQedL53HnQmdPZzlnGHi8D+pU"
    b"yeFw3NMX6o30JHqkNkerrkn1lDpQzaG+gaJVUwJsD2vPwtkVOgzYviLzSEXiRTe2kxHylpgkSol4vp/34jl4NLjU3c5j/8FVjrdq"
    b"WsmsD+Zh5IwWZj5TM6OMM8ZqY7TR1qhk5EKat5EFXwXvBi8Gjwf3B3che24NbgvuDO4LHgmeRUp5DPTigoqRysgH9rYzRhpLoA0P"
    b"jBhkl6JIrePNreZdM8HMaNW2hltbwGZh5bfb2fPtC3aMnZU35zP5WR7Ds4tWYr64IgIin+wsV8i7kpISpC/ZiJzjpOXoILqVPqNO"
    b"Vob1ZevYfWazvEprZSbQf6e41WKowAx1v/pEDarptQpaJ/iWjdp57bXm08L13HpFvZneSx+jz9XX6Lv0o/p5/YZ+X3+sP9Nf6M/1"
    b"p/pD/Y5+RT+t79c36ov0iXpfvQU+k1MP0WO0R+icBZgV1bQMWoJ6W12nDlArqqHqa2WHMkgprVDlJpvHGrPk7DldSVvR1PQFWU6a"
    b"kQgSKefKWlKVl8UEUUYE+XE+lBfmcfYhe5BdxPZZp4B/VSvEemJuAM9LmU7zlbEPjry1UcQIM34F7wUPBJcFxyLtNwlWDhaFl8kU"
    b"TBNMgZU6mD6YPVgQealusENwaHBucEfwavBTUDPyGI1Qve3GE4OZxc3e5kbzhRlh1YOO3LKcdm17nv3QTsHb8C38OxzgGHFVhMoW"
    b"crP8KYuRCeQWSUJbw3l/owXYMHYaKFdQJioXoCSl1WHAN1pNq9XXJmgHtDearhcESmOQPc4CxXjd7cjkKOKo6mjkaOvo5ujt6Ofo"
    b"j62no5OjJbJ+OUdeR2oHc/zQH+nH4OSH6031ArpTf6+d0OZqHbSC4PN9dY3aQy2kmspVZY7SBEr9lm1lPVleFkOP0hG0DOXkMplG"
    b"apFQ8ggcaS+zyR/iCK6imggTr/kO4FsF6fKTfcKeY3e0S9hh9lfrirUROLe3KlpZLd36bT6Dsu4xV5rTzRFmL7Od2disZVY2ywH/"
    b"EkCsBH6XM6uYtfF6O7OnOcycYi4xt5jHzVvmW9NrunGUclYLawj8xl7rjvXdctn/2PXsgfYSfOtrm6DD6uE81vIr/CdPJsqJ7mKh"
    b"OC0+iTBksC5yPlTkowwlpaDb88kp8pF4aHHakc6ih+greJTcrBEbAYZfZl+YWymgNFaGKsuUY8pTxaskUQuoddRu6gR1JXLndfWN"
    b"GoP0mVzLoRXTqmgNtTZaV62fNlQbpY3XJmFN1iZqY7WR2iCtl9ZRa6rV1EppubVUmqrFqK/VK+oudQHSTDO1hJpCTVAeKvuUGUpH"
    b"paQSpnxiJ9lc6EkBJmkkXU/70tJUp4/JetKbFCVc3pJLoCy5kHrOiOmioUgrPvPDfDyvw1PxL/Yxe7rdws5lW9ZDa5s1zmpm5bec"
    b"1mfzqrkNqPcyG5jFoOouM8GINp4ZNxP/hnK/scvYAd7uQgccMc4a143HxgcjztDMdGZhsy4qMRWfvm5+M0OtolY7a4Z12HoHlS4H"
    b"R7TZfopMU5GPQGr/yjOLNkg2D0SIrCGnyAvSkCXIEMzI7yQ77UBXYUq6MP9HsQPsE0up1FbGKHuU14quFoaGTFf3qo/UBDWFVlxr"
    b"og3QZkFFTmi3oSM/tYDGdI+eVE+lp8NKi99JdJcuNS80/7l2TTsC9Z+m9dcaoxqptID6XD2mLlT7qtXU9ED3trIBlayupFK+o69m"
    b"szaodIBexyTpDJ9nk7tkJelOihEKZm9Cnqwgw+U7cHuaaCHyCiKeQ72n8fa8JI/gf+x7SHFz7L52fbuwndK2rWjrnnUSWC+yJlmD"
    b"rc5Wc6uOVcEqaRW0cls5wdjMiSsbnuUDemWhOg2tNlZ3a5g1xVqCzx23bltRVjy4nNkuaTe2+9hT7U32WfuF7beTQbMa80Fw1Uf4"
    b"Y+7jqTBL2ouJYou4KX6A1UWhH2NxzteQ28NIYdKSjCUbyDXylbhpQdoY82glPUVfU5umZxXAqXFg92n2nPlYEiWvUkvphAosVXYr"
    b"l5UXyk+FqMnU7GpJtTp42Q3zbaw6EyxdCRexVd2t7oMGHQT39+LxNnWDugrvTcc+/dVOamOockE1naqr8ajnFRxxPnL63793T43p"
    b"+JQdZQtZH1aDZQLuj5C/xtNmNBcU5RHZCidSh6QjMcjCi2U3WUzq8qXYLcaKBiKTSOA3+Rpcf3WeBtp9C7iMtZvZBe1Q+xs0dTeU"
    b"tb/V2CpuZYS6xEIjbpunzL3mOqjGbHMifNwIcyhUZLg5Cs9mwFGuNXeaJ6AmL80/pmqls0rg0/2t+dZ+K9LywuuVw3Seb5+0P9nh"
    b"vAKS+hp+j3NeQHQBq28JLgrJ7nItnJ9GypIBZDt5RUJpFaC8k76hHlaeDQC+d5nBsimNlNHKZuWOEqMkA6It1ZHA8TBU9iscYXIo"
    b"QSmtjtYKmjEQGjEe3J2uzcCaAn0fBR53w3u1kbjzaCk1RfuJ2XoWiE+FQldXc6qq+k45r6zEBKyrZFEM9ohtg7dryLIwP71N19AB"
    b"tBJNQqPJcTKTtCF5oRmP5BY5UtaVGaQX2WyDGCnqixxC8pf8KF/E+/LaPE/ivyq5bx+0l9tj7E52HbuoncEOsQPWF+slsD5rHbK2"
    b"WuuspdY8a5Y1FVyfjCw0yZpmTbfmgscrrc3Q5GPWZeu+9cb6ZZlWiJ0Rlapmt7b72dPstfZh+64dbXM7DS/KGwLbmXw7v8Y/cCIy"
    b"iwqiI1i9QVwS7wXFZKkKnGfJXfKO/CU9pCBpTAaRpeQY/IifpIRmtwTmy+lxcCmOhrN/WC3WjU0E9sdZJPvBqJJGKazUUNqDg9OV"
    b"NdDWc8oDJUr5hVnqAMczqbkw6UqrFYBmbbWu2hCrAba6ag21qloOjia/mkVNpYaolvIHn7urnIXfWKSMU7oC8aJKSsVi79kltoVN"
    b"ZZ1YJZaBGfQFUtdc2oOWpylpDLlO1pGhpCbJRBKg1xvlUHiRjDIeXbseab6myCi8/C7fysfwZjwf1/lH+7y9xh4N5S5hp7aD1r/A"
    b"cTum3AirI/xDKehIKsthWWac+dmMMl+ZT8xHWA/Np2ByFHQ51rQxHVNbeTAfG1o9MHOXQ6PvY0K6MSHrYkIutU/bH2wHLwIdm8GP"
    b"AfdQoN5PrBOR4HV+2UkuklekT+YkrclccpbEkMy0IZ1MD9IoGgbn15MtYxfYd5YMrqszZtVuJRLcDkPX11V7gplrwO6b6iv1N/jt"
    b"1lJrWbV/kKpLgcMVtfJaOa0MnuXHtEyjhWlEi1Xfq/fgobepc9Whahu1PPBW1U/KNWUrPE97zMEI5Te7ztZjHtdlWYHvPXjQUbQu"
    b"zUwTyE3MwkGkGklLfuGcV8m+sopMI/8A3Y1ihGgs/hGa+MjPwweM4S15aZ6OW/Z7+zp0ewkw7mw3sEvZOewUSDoJ1lewO9K6Zp22"
    b"jlr7gPlWa5O1AdtG+OUdUJhDcIoXoNBPrLfWTyto6XYqOyc+Xw+5cIg9y16HiXvX/mjbcHYFeF3enU/iG/kZdJYfDqSoaCIGicXi"
    b"sHgovCJZol4PlyvlaflKmjIDKU86kklkE7kCL8JodmhJZzqFbqIXgbqFRFkC3nYAJtZWdpG9YLFwJZmATQNUYKQyT1mvHIJyP1Q+"
    b"oBI2nHgyNaOaBxUpCWZXBpdrw7HUQ31q4XFl8LokeJ0dKh2mMtWnRCvPgfchzMZZymClnVJFya2EK3GYDqfYKuhJa3x7ChYP5HfT"
    b"qbQdLUFD6RdyAX3Yl1QmKYD9Zbkc2FeUyeAEL4ilojcYlVz85Jf4aj6Y1+LZuG0/t4/aCzAt6yL1uO3fwPqotRrK0ctqAq7mBWcd"
    b"lmn+Mj+AyQ/MO+YN8wq8yjW4jXvmY/M1+B5rCjMcCl8EeakdcsxCVOWm9dnS7Nzw1P3tZfYZ4O/hxXkXvgDI/+Cp0WGjMUNeY0JW"
    b"kIPldvlcukkFcGYbEqSTlqX94KseUE7zs3ZA9wT7yDyYVR2Vacpe4BmvpFCLYwYOUeerO9VLcBO/VKmGa5mRqUsj/dWDP2kFx9cW"
    b"qyW8XQO8Vk4rpGXRkmkM/u5f9QYm5Up1nNo5Ua8d6hcgvUUZr7RUiighcHjn2BLWCxM5GftGz9GFtBstSV30LTlEpmCG5yG2fCi3"
    b"ylGyvswqg+jQbWK8aCbyC6f4AF6vgdtqxovxZNxnv8TVb4Tn64u5WD7x3wESOwbuLBIKcszaBR6vgI78VeyJUIVxWBPwaCpemQ+N"
    b"2ACOH7HOg98voPM+ywH1yWtXtJvaveyJQHY/uibKDsKHFIC/7MGn8s38In+LmZge7ro9zmqDuAjNVmQOWVP2kfPkQflYJshUpAxp"
    b"B2ZvgRf5Bi+SlzagA+kieoQ+pl6ajBUBrwex+Wwfu80+Q6/TA/1GSi9lsrJaOahch4f4rVDwORu0uCrcRUe1jzpcnZjoR5arq9X1"
    b"6iaszXAm6/BsqTov0YkMgmtpCbaXhr6nUKn6U3mGOblNmasMRKIppqRQfPAih9kCeJHqiV7kASb3eNqU5kn0ItvhReqSDPAil+Gx"
    b"u8riiV5kD7xIfcyoeH4DvO7Pq/LUcIE37PX2CLsR0HLY0dZVqMVUeLracH0pLG5+BXcvmQeQAJfAd4yDB+mPPNjD7I6ttzkAjmQC"
    b"HMpyuOpj5k2wPNZ0WlnQD62tUdYq6wy0hoHdDe1R9hbMZNPOxVtAtU/AYacR9cQkcUx8ExlkEzlTnpfxMjfpgK68TQQpSnvStUgN"
    b"BAh3ZUvZVRbHMip1lOHKRuUmZllytZTaFrxcq55Wn6mxqlPLBLddC1zuA98xVZuvLdfWwndvwdqsrddWaYvhw8drg7Uu4HwlKHgq"
    b"qPc3NVI9gjqMBNol1ORqLCbkDuh2S2QmTXnNDmIutmB5mI0z2UQHQ9WSwY0cI9NJC5KLBOVtuUb2g24klZ+RzubDXZVChvzCL/BV"
    b"fAivDy+i82j7mr0NvO4FpS0MVkrrGzT4AjzGari+MXBtnZAE61nVrPKYj8WswlYhrMJ4VAqvVLXqIvl0sPpggk6DO9mKXrhhvbL+"
    b"WIqdBserjSkw1l4BT3Lf/mE7eU44zO58OlLsTWTzEFEAU2S4WC3Oi4/CIfPJxnIEfN9l+RXpsShphbS+DXjHkOTIZh2g2DvpHfqH"
    b"JmXFWUs2mq1hZ9kbZrE0Sil44KHKAqSca/ARfszLHGpZtRF4OkKdBebuVk+q19SHSITR0BivGsT0lCrVKFDmqoE09Fv9jKz5QL2q"
    b"Hld3APOp8OWt0RN51aRqQHmjXEBlJyodlLJIN152n+1gE1hzpHbCntFddCytRzPQP+Q88m47OEFD3pTLkIQLSi7uiFWihygmmHjI"
    b"N/GByHBJ4EOO2TPttnYhW7ejrBPQ2j5Q3eyWYkWDp3vNReZIsxMSYSkzp5kKKVIYCcYv4yuy5Efjk/HZ+IHUaBm6mczMipxZ02wP"
    b"5i8wd+OzX0wH3EkDpJ51qESclRF1HWvvg7pEAPsx/BC4nUm0FItwXipUe7Q8JmPkP8hlm8gbeL5GdDa9gplYhPVmG9HFTlxxf8yu"
    b"+4ql5FKbgNNb1dvqHzWJVlhrBAc9C/w9rUVqH7R4jephemo9i55Lz6cXwMqn59az6mn0cF3Rfdpn7bF2QdulLYITb6tVgMpLNQp+"
    b"ewX0pLaaWfWD3RvhJKvB933BrJjOmsGRxNLzdA58aDYaS86R2WB2VujGOTlHtkI294sbYqXoJcoIj3gHtzWHd+KlgO8PsHqTPcFu"
    b"h6SRAZz+BGd9AAo9yeprtQSXiwLrlJbLEqbP/A3MPiDTvIbfe22+Md+Zn8zvUArDVKwwKy3yZAmrBj7VB7q+2NoJFX8K360jRZa1"
    b"W9rDEv+dfKT9xw7jBZEhh/Ll/BT/F247u6gtBmBanxbvhA5uN5VjkCBvyj8yBSlHupI55DB5CS3JAbc1mK7AfPpAdXjsBmwwPOAJ"
    b"9pKZLK1SRmmtjFJWKEcxL38iwWeG6jZWe6kToMY71TNwd/+C0abqwEzMqOXSCmolEr1gZa0KViV4wlJaES0vfGIqLQRc/6O+Ve+i"
    b"G7YkOsLWcDBZ4Qg/J87NCUobqLdHiUZfLYLTL8nc7A3dB3bXoanhSY6QiciQKckHuQ99WlmGyGdik+gjiiPh3OUr4AsKwoncsVfb"
    b"ve0yyDRR8MYz4CWKWaHWV7iNTUiHncyqZi4z1PQZ74y7xmljt7HWWGhMNyYYo4zhxjBso/F4hrHYWG/sM84bD8F2bqQyi5qNzEFQ"
    b"+ROokIKE3xJ6cxR1TWHXssfZR+zvdhbeFtg/5B7gPkNcw6ysIicj7RJSCed9EUiXx5Wcpn5alA38719vN8PMuqT4wOzW0IkT6ic1"
    b"FPi1Rz7crt3QvmiKnlEvodfTO+tD9an6Yn2dvl3fpx/Sj2Ad0vfq2/S1+iJ9Ct7trNfXS+qZdF3/od3T9mtztV5aVS2D5kOFNmOm"
    b"1lLTqD+U08pMfGdm5Rc7ySazOvAl/9JttD8tRm1M8HmkGUlPooHucHSmUz5GiuktSghFPIYfGMyr8OT8m30O7rq3XdlOZ/utx/DN"
    b"C61B8HglkLKZ9dN8Zl42D5obkMEnY/r1MTubbczmZmOzodkAqzEetzG74PVhqMU8c425xzxr3gf//abHymaVtZpbA5Ezd0E7oi3V"
    b"zm7XwGSYC4Y/sQ07IxSkL1/Kz/JopJoSopOYgwn5TrgxwTvBk5yUn2Q4HEkPshi9+pUkQ0rrRZeA2V+QHkuxzvCAh8FrwbIrtaEq"
    b"i5Vj8MYBJTUccwt1mLpI3Yds8wF6HKHlBIsbap21oajFYkzI3dpR7ax2VbsFdB8krnt4fAWvHdF2YpbOR6Lvj/laHR2QShPqR/U6"
    b"+mOm2h0anlENKo+UXeB3EyWHEmC34Lt7sGLQ7nvou05wJfHkNFxUTRJGnmJmdpTZ5XdxQAwTpcHs63web8rTQrP32sPh2ULsF8gv"
    b"w6AiKaxv5jlwsrdZxcxgmsZL45SxxphodDcaGKWMHEZyQzeMYEzwa/BDMArrfTA6+COYEJTBUCOjUciobrQ3RhpLjSPGY8NnpDUr"
    b"oy7L0SfxZjbUYbZ10QpYhew+9g77E9jdCdPjA88muotd4qcoJIch3XBZhcwgd0k4vNUK+oqmg89ez96ydEorZTkUw4U8MkrdD0yT"
    b"gY2DtHXaTS1GS6GX0tvoY/SVYPEd/b2eoOuOFI6sjnyOYo7SjnJYZRwlHAUdOR1pHR6Hrf/Qn+kXwPw5ej+wPJ/u1D9p57RlWm+o"
    b"eBLtAxLpROSf1MiV+5URSgV4k3vw3S1ZevYe7O4FVxoD7RhBShOOHDlT1pMR8HsbMBULiiC/gjTRhufifnjgFWB2eTup/c26BP8x"
    b"3GoMnxduxcLlnTTXm9Ph6Npg2pU0c5vpzHBTM7kRMOKNGOMPVixmpGFIw2kmNTOaec3SZh2zLT4xxVyFjrgJjltmaqu41dQaAqdy"
    b"zHpuGVYG9FFP5Kbj9r+2yvMjxU7me/lzzuBM2kBFjsJzh8oyspdcIa/KOJmJ1CNjyA7yhBCan7ahM+C031InXGA7NgN+7AWTLKdS"
    b"D1NshXJGeatIJQsq0An4rIMTfAr1dSQ6wTpaB3i9KdoSbRO04jR4fBfT8aX2rxalvcP2RnuhPdLuaJe1E9oeVG2+NhZ60gx459RC"
    b"tXh4ypPIPSOQnQqpbjVaOYte6oFZEaq8w1lMYPVYGvYF5zaO1qRJ6Cvkgz6kMBzhRTkD6CeTr6DbPXGNPqSc6XCCqfgHsHukXc2O"
    b"sN9DUybD1eWybPMJvMh0aHZ5Mz2wfm9chyYvA8P7GW2N+kYlo4SR38hlZDeyYcttFMDzyni9vTHQmGKsNg5D4b8ZDlSrLrR7JZz6"
    b"T1SgBrziLuuNFQ5tGQ/kY+w8SDxb+XueEUlnnfhXpJft5HoZBbQ7k83kA8mCHt2EpJ6OtcJkfMBcSmXMxAPKJyUldHUU+vyJKtTc"
    b"0IthcNKngaNfi9D/0SvrzfVe+ih9hr4EOr1F36Xvwdqlb9U36MvB5vH6AL2dXlsvpmfQVf0barBfmweHXgMJ01Qfq7vU8Zi12ZDh"
    b"r6ObuiqFFIEctZx1wpROoBfpLNqEpoPj3k9GYsaEkGdyI3J6CcnkQyh3P1FWhIi3/AA41Zz/wyl/BR88F3yramdBevyANLPTmgcl"
    b"aQdMiliZ4DYkfMcnJPRI5POL5hmw/hjWcfw+A/Ru4PWX5kfzD5jsgjP5B0mmkdXNGm0tQr68CN8db4XZ/wDXbvYUe7N92X5vU54N"
    b"qt2Lz8V5POEBnk5URt/NA7NfCilyyLpyiFwNXnyRHjjuNpiUO8g9EkdSQ7s705l0D7JFPE0OL9CGjWXr2Pn/HHcJpakyQJmtbIcz"
    b"foHEo6pp1YJqFeh4T+SVmXDQW5DNT8NP31UfqS/hUqKgQh/U9+o7uPBn8OK31Ivw2rvQGfOBc3+1DTJ8YRxFwZx8gMmwShmttIX7"
    b"TKME4UMPsrlIWuVZSvaLXkv8s9eqNBX9gbm+GF6qBNHJS7lHjkWSzyRjxBWxDFf51xW+58f5bN6Rl+AeZJ3zUJjBdn1g5LK/whPu"
    b"RTofgjRYCVgmt4gVY0aZD81r5ikoxm5zM+boOnMtfm42dyBlnsBsjYT/+GUKMwL9UQEqPThxWt5CanLZ+ZFTRyCvXoMbTI1pPZCv"
    b"5beAeXbRTEzHpPwsUsoacNx75BsZRiqQgWD3QyhJYdqRLsCU/EZTssqsL1vBLiCte8C35sBgNZTkFTxKUjUfEOqgDlFnqGuQaE4D"
    b"wSdA9Qv8X7zqU/1INT48+oNX3gHh2+p59YC6AUl+jNoDzr0MnJ5b/aM8UU4A2zHweqWBrY89BrZzWHd8c1qw+j7dTifBbxekTvqO"
    b"nCSLSE9wOw2Jk3flNjlBtpHFZLj8JW6K7WIqHEBlkUVQEY3Mvpsv5MOg5FXA9eRc2N/s50DiiL3VXmpPs0fb/ZAFWyNr1wb/y9ml"
    b"7RJ2MayidnE8LoO5Wt2uYzex29hd7AHI41PsRUByj33Wvm2/sn/ath3Os/LivA7vAI89h29ESo+ED+E8JXSslugsxojl4qC4BZSF"
    b"SANH0hC9OAOO+7x8ieweTvKQaqQTGU2WkUPkFvlEOElBC9HaYPlYupjuppfpc/qbqiwVy8+qINv1YePYfGSgg+wSe4iZ+hu815Rk"
    b"SkYll1IEWltFqas0Qu5sh1TYRemG1UPpDpXoorSHZ2+uNFBqKpWU4ko+JYuSXHEpFvvFopAcz7F9bCWbBpffltVgBfF9BFp9jx6j"
    b"q+h42oVWo7lpCP0FZhwC+kNJU/RlcuKVT5DUlmDqN5NFZHKZIJ6KE2KFGIU5VVZkgkf8DA9+CA54PO/G6wKpjNzFfVCAB2D9XnuD"
    b"vdCeDHb2TaxCY7uuXROzrxJWRbsKdL+m3cBuikTawx6IvDjLXmZvgzbfsF/bv2yC+ZAfKtKRj+RLoCO3+Beuou6VUf+JYrO4hPSu"
    b"yRyyFhCfJw8l/slU6v/+ZGozuUKiiUpz0Oq0G51Gt9ALmJhBmgxXXguOcDRbiCx9lkWyTyyBqUoKJZtSOPH/tm6M7u+i9IbK/P2/"
    b"rYdjjUDGH6T0A8qdgHADpQbUoYCSFehqih9+/gm7DGzXIDkOhFpVRTpPziz6kd6hB+hyVLkjzuEfGka95AU5i7w7lfQi9UkhkoJY"
    b"mDbX5G65ALmmLXJDXjgUU0SLu8D4750ERoquoqGoIPKKtNB0k//iUfwBv4qkt5dv4avgYGbxSXw0H84H8D68J++K1RmOrQtWVzzv"
    b"zfuDtSP5BD4N3F3K12HeHeAn4X0i+Uv+mcdzgdySVuQSJUUN0RzaNRzuY6XYKU7hHN6IP4LgjHLIkrK2bC8HyinwIzvlWflAvpc+"
    b"6UB/5icVSRM475HIyOswkS6Rx+QjSSAaTU5z0uK48ha0Kx1Cp0Bp1tO99CS9Th/RN9CcOGpTBwtjqVkWlgtVKcHKgv81WV3WiDVB"
    b"Bm+F1Rp4/v3dAs+bsPqoXHVWAY6+CCZhVuhGOHMwm8bC57+kdzEZD9LNdCm+ayj4/PduDgUwJ13Uh1n+IPFeDovJWOhKY3AkBwkn"
    b"hoyW95EetiDVD4f7rgWNyYj8k4BscUecFFvEQjEeSagVsCkmcogUQhMB/o2/Rg2uAMV9SEer+WLUYAofx0cA6QG8H5JKb6y+WAP5"
    b"ELw6DnN4Jl+Eam3BJ07gkw+Q039ygztFGpEH06K+6CCGQKlXw/tfFS+AuiLTyMKypuwAXsyH/p2TT+UvqZC0pAipnXh3gQW4mrPk"
    b"EdIOJxFAugytD0UZAqavoDvoCXqDPqWfgIxNXUh7GVluVoiVZpXQ+fVZY6hMa6hAO9aBtcdqh2ct/sO3CqpQDAz+H7oqM+gv+oE+"
    b"QdVOQavW0Dl0NO0DB1qLlsS3JqMMHvstksApzO9lmOL9SVvkmeIkK/Dl8qd8JW9CP7ZCQSbJQUhrDWUlWUhmhhdUpV/8AMce4JpP"
    b"in3g+wqxQEwTY5F/+opuwKSlaAxsaopqopIoB7UphexXApUohp/FwdjSwK4i1KCaqIP9GqNO7UQX1Gsg+mYCjrQQTN4o9ogj4qy4"
    b"ISLFK2j0H2FBM8JlBpkH1a4MV9pa9pSD5UTgvFLukEfkBXDiFXyJDwk+jGQguXA1VUkD0p70JsPINCC/muxCrriAq34KZv0iPsLo"
    b"3zvDZIGCFoZ/qYpatKBtaXfajw4GXhPpVDoX/F9CVwPBjXQr1k6guQv9sCfx5y7UbAe4uwk9shKasQgebzqdQEegor1Q1za0ARx1"
    b"BRw9N81AIzAjTfIbs+QpuQkW7CEbwOyJ0Oyu6MUaON/sJBWciV9+k88S7xOzA15rlhwJnWyNTq4g84PnSSWVPvENqDyAb/l7f5iN"
    b"cC9zoawjgWA30RF4NhT1RHVgXAHY/8W9EJJTQZEP299Hf+tQCu9WQY0aiqaiLT7VB9UbDy4vEWsxqY+JC9CRV1A0r2AyFN+aX5YF"
    b"5m1lHzkOXbdW7oea3Jfv5G+gnYRkRFqoTBqRLmQQNHwxrusAOU/ukNfguRcoh9I0NBemZzmg0RCodAUXh9IxdDKdTecD31XAdwO0"
    b"fgvcxE4gugs/t2NtwavrgOxSuhB7TktEdjCQ7UBb4TjVcby/yGakSYGsTWLIZ/IK1b2EKu8ga8jcRGy7kVakLikH3c4G5XYRW8bI"
    b"T8D3NhhzSG5Hfp8vp8pRsr/sKlvJBrI6rrQIWJYZvRwhXeC7LXwiVnwHGu/B+xfiCZC/D6W5Ka6jB65gXfpvXcbjq+DsLbx7D3s9"
    b"Fs+B4lvMuy/I4LE4jgVl1oFoUhw9s8wlC8B5lJfV4KubIcV0lf0wscfL6ZgsK5AOdsrD8gwy8F3oSJT8KmOlIRlxY75nIDlJQVIK"
    b"qNfBxG+Lq+xHhpPxZDqZT5ZD0beTfeQoOHYF3uUBeU7+hbp/JX+g8EEiUBEH9dBw6EAqmhbMzEyz0uzQhdyYd39XPmTwv7/z4JVc"
    b"eCcb9kiPPVMC6XDqphol1MCxYnDMj6jyY2SAa+QMvnEPJvhq9NoMnMtgzMsOOLva8K5FyT8456TECfzjcSWv5UN5XZ6WB6Exq3C1"
    b"U1CBAbIL/GIjoFFOFpW5ZRaZGh3vlFIEwcMfUIF3SCHPxEOgews4XwRLz2DinRLHsU6AtSegSCehGufwzlVU505iDV7hc5+Af3zi"
    b"/Y4cOGYaHPsf6EhZaHVjfGdPaNwYOVMuTrzr0dHEu0w9A0tiZBDTMilJj7MvholZjzRHxuxPRpApZB50cxPZTQ6Tc7j2e4kYR6O7"
    b"44hBJFGgLOFAKw0mWUbglw3o5sHKR/MD2/z4nQe/c8HnZKeZUIG0qEUE+kSnCuXET+LJdyAbBaWIRAXPkRPkINmGvlpG5kDLRqPP"
    b"ekPZmsOPVMJULATlyEiSAV1KAvIP8H0D/3dPXgZ7jshdwHgNrm0eUB6XiHNv2Q293Eo2RU/XllWhLOWRQ4tg5QMueWQ2mV1mRddn"
    b"xpYeWzqs/z36+0pWvJ8Ne+XBvoUw74rJMlgVUbfq4HFD2QSItped8S19odCjkLKmQMXmymU4i/XQtL3ou9Pw2ddwhg/gtqPkR0yc"
    b"WCi3lCo6NClJCcT/3jWtECmJq6tKaiUi3xps6oHrHgCmj0Jv/70v2nyyBJisBTKbyU5UYz96/whyyFmsi+Qy1g1o7U2owh1s9xO3"
    b"SPyMRMXuYLud+P5V7HcJnziDTx5BRffjWDtQ3bVkFdRsPjCfTCbgOweiy7oD99bwInVIdahKCZxjTpIFEz4J+pLBmyTgWj7Jt+jY"
    b"+9Dw8/ApB3HNm/+rwFR092iwrY/sDoxao+vryzpAriI4XwKsL5xYgVzAOCuwTo95lx5sTYctLR6lxfNMiRXIIXPCdeYH/iVkKXy2"
    b"SiL2TRLvmdZV9sI3jECtp0GrF0OtN4HVRzBPLss76LvXwPuH9EoTzsQD1qSHq8oLfpcD0vXQr20wj3qDYaMS9WQuUsVKKMpmTM+9"
    b"YOFxeIZzwOsqcLsNDCORPB6SJ4nrGfj6FD+fQBEeQ3ciExG+if64hLl7Biw+ismwG+q0CUdciSPPQw0nwd0NR1V7Y360Q50bot6V"
    b"SVnMw/yY4n+xTfbfHeoMGYeJ8wVz5zX4fT/xLnXncV2HMY92wQ9uxLxclojzLGjoZOTPsZiew+UQeOAB0NZe6PQe4H43KE1nrE5Y"
    b"neEgOyU+7wLkuqEuPbBfH+w9AJ8agk+PhDaMh9OYgmPOwrEXwhWtxDetQ1W3A9n94PNxdNp5KPUNzJUHOLfn8l947Wj5HecbJwPS"
    b"SuS2E3hHYAqlRbdmBW/++e+ugGWgLVXApzrwK41JM9ISit4BStMNCtoXejMIc2w4vPr/7gk4EYhNgQpMJzPJLPj3OVjzsOb+Pz/n"
    b"JN4JcCbW37sBTsUnJqCaY1DTEWQIjtef9IGj7gZP2h71bg7/0QA6XQNnUZ6UBhf+3hvwL6/Tw5FE4KydRCECauiFunwHv6NQgafg"
    b"0h108SV4gRPg1z7UYDtqsBaKvlQu+n+q8JfzwzHZBifWoS/Q7Y1K/K1F98T1P9R74JVeiarRH3sNlkPxmb/qMQHHmJaoIAtx3FXA"
    b"fRO89W55AEp9Ch77CvrsHlLkC3TdJ3in3+hBQwqpQUvCgXYakgkMz4NrKo5r+9/dF//ee7F54p0XuwCH3sBjMDAeCYTGJaI7Fbj9"
    b"xXZuIp7zMdEWgq0LE9ffOy3OT0R6DvaZgTpMTdSHv/dbHIGjDPrvjot/0W0LrWgGZ/T3rovVErW6JCqeH/2Wk2TGREwNbv9VDj0R"
    b"3793uPzL8B9gzkdg/PfulU9kJOb/TeB8BQw7gys+jus+BLT3AoMdQGIL8NgIZV0LjVkNfJbDO6wAUsuwluD30v9+LsU7y7CtxLur"
    b"sOdfBq/H2oQjbMGRdqB++7AO4vhH8S2n/09rV9YjR3WFq2q6e/axx/bgcYyxx9iGYAwYooBYwk5CpBApqxSJBBKH/J7kIQ954CF5"
    b"jBQpAYwcSEgARYBZTIhYjMGM4228Mfbs091V+c53z92qqscvmas+3dNVdeve73znO6ds6Qzu9ndE2KvI1G/A09IP8wN2wvysmAbS"
    b"p9kBcxb5fAF4d8DwLBHMh1F/bwDu0v9yGzi0i0zfB/zvgAfuRGTfSy88Ar49Ds5/B/gI639Ijf8JXk+C/T8D/5+Gdw5AjQ5AdQ8A"
    b"0Wfw/gw//5Lf/4LnPIWzfwrlkCt/jDm+j9m+CyX7NmZ/FIx+EJy+G7XS11Cl3oKV3Ag27EAEbsEaN2Ktw2R3gueeJezkCjuKnsYO"
    b"jyOLfgiWvwd2vQUMXiXTD4Hrz0Fx/uTw/wMQfBY4GvQFXcHZoP4bqNGvYb0Hfkvt+B2wfxZe+z2uFw35I+b7M2LoIDB/Cfd5HUpy"
    b"GJ4/gjrkY6xD8D7DfqNzwLrNHqotxOU6IL0ZerINeiIc34d8dAez5n1g28NA+Fuofp8AHt8DMj8ivk8Sr6eA7c8V22c4fqX2AMfT"
    b"HHKm5DtB9gdk8hPw1+OIoMeA6wNUizvhVUF2L5AVzdgO1ZgEthuwOlGOJju7trHuBfZtvcBurf8lw4+BTdKd9QOgLDx/E+Nf2P3r"
    b"4N0rGC8DjZfA+UN4HUQuPQhevoAn0+cZBc/h/Tn+9jyOHOQZL+LMvxLFv4G9rwDLfxavYQiH38Ad3mHVIX1dpSfsx1jBp+zpOo2Y"
    b"O4NxHvF3iR1mRUUM1qazq+ntOsLurlKjbMYurwXy12HP0uX1BoybkpsxbgUe+8l24ftd8MY9GPehDv4GMHsQ4yEMiYBHwFAZj+n7"
    b"I3w9zJec8wAi5QFcdS/G3cD6LmSLr5PJ+3EXuZeweQ/uvwNjK5gwiaeDjdTsEcRiM2mwo24XO5HuuZcRr6LgZ+GBE+yUK11yP2KP"
    b"2yPshvsWPPAGPSB8/wdQfBnjEH3wIjF+nh4w2P9F0X+BHpDjohqHcIWg/yrGa/CnZMXDDndB/RP26J0uTlFFDOKLGKvso9uHdfcD"
    b"61Fo40btpHst9rcTz3B7sGNRE2H67cyed2GIpkhn3fuB7cN4GRwfI67fVPsorUH8IeIrZ9/PK+8BtncTWeHybcR2L+JpD9C9nmoh"
    b"2BrF2ADNGMXqBrHGRpJROTranXgOCIuCn8c4CzYZlKfZN/gYewhLN2LB+9/g/BGM97XXsOk8/BZ7EL9JK58PK2Pf1k7F72lf4iPU"
    b"YulN/CEVQuY9qlw+zor6BBVaGH0OQ5TjEnw/h7GAlS5hvW2MnNxuYAji/chEwpsx4L4e+xTsr8GYxN6/Qq5vI8+mgMn11PXd4PyN"
    b"9MhN5P5ejH143wc9EMW/Fe+38d3YW3nkFvZDvpnnfRXjJs5yA2fcxYyxHYgLn7eyP/EkxgZV63HyWurBJp93Umh3G6zpMgsJwxew"
    b"zwt4l77QF9gV+jS5Nk10jlFPPwJqH7Ef9H+I5fvAVrpCv0NPvE0tEo8Y9A8T/XcZIUeA+nu8UiqODzGOEvvPWfGdwJ3kfieJ+jlG"
    b"22VmFeH2MvHuohLswxjE+oewoxFgvQn72owxgf3Krqe4/9143w1kdilG+8hJE/f7ieHtjIP9sMLam1UVbqMPJNftZQ0tGIun9sBr"
    b"u6kVU/TlNjB6C7AVH28CwqLYoxhDGANAWKoS6e0t3bi7VMNlRuk89VH2JmouijmjPbjPUNlP4SVYfEHcj2s/7s+J0WfszG3tMbXH"
    b"aD/Xc4+rv6aVx6eAp6B6mneZYXSdx90vEt1ZruYKVrUIpJc5OmR3Qbwz7kEwb4HhLeA+RAaNEPl1ZPo4uCX8ukb5PknNMazfSo2/"
    b"Fq/t5P92jCnGwU5+2sku31OB3U67jT40GULm2Mo5J+HlLbjHBF4SYRu5gvVYzxiZPcQ19jMmpSpJkoLsboM/K+x/vsAoln3PAoGL"
    b"RF+4doaqflJz60mg/wVz7HG8f0r0jxLlT6j6R/n7p7TH+I3xj/GX+G+aVahkxZPE/Qx9fY5K8iVXME8uLJMXHY6UfeFl5VZPhlkP"
    b"jjFyhWGbqCmbiYLgu1V15Tqitl31ZYro7qTSGDtFu0Px3sHq2eiy1BtbyGXB1/hPvLmJ1dE4s4hwelQjTjJ5i7rRx+70BdZt6hOJ"
    b"0CUiPE+OX1GUv+SehW0XyDyD91nNo0bnzyo/T9EPp6i89tiM6rAckesExRmdS+a8SE/OsqO93FV6ygujl/BuVE3qEHmK7PDJJse7"
    b"9M2XzvmCd5P87udrgAwfZB0+xBw6TG6NAo11rF3W0xPjZJ/xh0Frgipg7GZnJ6hK4rFN9JqJEXOF0eSNVC+jHjKvZI8x1kkjvPcg"
    b"1yEr6ycrmmRHpsoiPx0yfFU5bvv8z6sX5ojIZc1gF+kH6ft/gUpg8JxRZM8qyjO0gv6Ms2eJ+jlec54zmOgx887yHlf4NDPPHLmo"
    b"zDZ/fyCnBgraCdafUU2ER7IroyjDmjvHNH+Oc5gYNyhNaD6dUDupbDW15IRao8bXqB5tJMobOI+Zc4yqNaJVyAgrEdHrASpHizVf"
    b"Q5Xb6IdZe4f7WCXTl1kPGq4vUFEM40z9ckXx+JL2EhGy9pIidjH61pw1y0+X+bcZZMxxrgXOu8DXIv9awpLT6VWupMNVyeq6XGdB"
    b"5ZaVmz30sc4y+2ppJd4i7sKqQdbl4oERvo9Sc0bJ+jG1Y8r+9aq21o7rt2Nq1zMDrtN4GSXKxqvDWlEPE+9h1ZJ+rqBJ3BtcYR/Z"
    b"YbGX2rBgvHa5v44+UyzxfZFYmLw1p7o+r3/fYlaV4LLiabzhPWJ/t58s6rOqW3OK+hVV6UWHurn3Crlg1pUr3sJtny0byvAWFWWA"
    b"+x1khShYjCrGI0RrTDEcd3Y9sR2PUPZYr6Md06wnYyhA1vJ5kF7uJ7JNrshEnlmnsETwzSN8LcNNtWL2a6qWJdpFsnBRUZljtFvs"
    b"TRzME7P4mDl7wV29oLOZGDL3WKF2WWRXdT3dgNVGQczfNjF/8URemeaiTNnTdMNgb6J6gEwbcIwfUm8YdTXWYDikmjCi3wxFx+w3"
    b"g3r1IGcz/h0g2v2KulmDZbXHXkZBthSFqU6sB6zGtEseWNa8aob1woLDdJ6/zWveXXDYG9Tn9ZjF3qO+rAq9othbFekUHV1VbhIM"
    b"12n5bfbRxz15RTG7HtCINuwbVJSGAnyHajAddscGI2Qtiwec5/qdP1sO24auJlMupNSNNDFrzjU6PcZtRdlyfdUx3qjpqiKyXPJA"
    b"eSxFdiW4dlXRXKYN+dzm/dvq6a6uqKvc9liLTXQfKRXF6IrBvuGwb2hsN8h2y3jL+5CN1iseyf4oJvo1Rlr65DKgczQV61bAZc9o"
    b"k1myCP1U0Te502LfdaMTqU078MBqBXtrl13G9Z+9tQxeCdC3s9rRcRGWByNkt8U61d00Ao7bXYdsbwW23+HXX7ItItzSz/4K7yur"
    b"E/GwnK4imzKvJ4lnSq7PxYbj1nZZdXVUQ9taJVj+ryr/4yhYVX94Wx0dZzsRqtZ21RbK6Fw126w2dTbRnaSBimcB+plDIGRb3Wi6"
    b"OAh91AoU2NtWwOCm5gszr7lfuIpU9Tpzqu3ZXeiuCmWR55RHwDO+q1h55Nq1HuhE2K/oZ39eO6r1cqcf9q65W5HldMjrNNhN5uLW"
    b"a3mfq1sazobINUvYtlR3QoT7nDc8tk29h1VpW+HVa4bVDYtv4RQ85HjIuY7arlPUtrOdSG07yv9udHYdit1IJ2LNyDXqCud9i3XM"
    b"7iRJXU2YOA23vMrUZu5zX+CPWIP6nJf6otGoWFsHZUEcZcH9PLsTx4QkSdSmyhpvTeTmgQ/qmB7zvVuDb9UD3g/m+TDUj47qh/dE"
    b"V+9s1mLQT5I8UhHzyiqohkzPolrR57C+oEqzNguOhdelimoj8qL3sEU1dagmbnVllMOMHzIqdzVB7rAw1XpR2GeiQutiq7ZVzHJ3"
    b"dbfE4Dy6k7+/X1GSGHwTzTfV1Zc1MfRA7Af/e1pjs5L1CpE6hciCT2UlC79Nam31x+6h/FP3XVGLWDeKiFihQi3u1ihIEeQMf89Q"
    b"t0Mbops4ZlmWZT2QjjXW8zRzEZGWNMnP0FficBXNKqdjXGP9CPmVR1WBj+rC8TuMgKLC0/K3/h55dI9QI6wq5xG/y7yId5JGewzV"
    b"PPRC4ryQRraqA+UcnLk5q0iHs9mYsk+8db7wz5Nl5ng+12tNqPCxh7o9vOWjoRoz4T3q1hPWf2EVGOtJjHrojdRFeRXp0ENxduvN"
    b"5Pi6xP2eRHdOapU7KdXhvb0QnlfvkbpsECpw3jOS6jJ2XP315niMdLh6W+P2OjuJ0KrzUlWzyp5Okqqn66+u94J/DjI2Uy/kag1u"
    b"qVr7r0Yesbrnkliz/BXVOYuaY2lwP7OiRP+lzVcpYRwkPVU1viKMiyx4BswqMeN9GCMXqsHV8Ozts9jWq305g4X3L6+iiPCsXp26"
    b"+iPUjqS0y/QqvC5zuYyt91Ra8lf1vLTGo3b+sI7OSk/qnqG9V1AU/oy12OsVIU3qeJrU8jSpXB2fUc0iVX/HnL1aFCcVBa9WDH6O"
    b"tEcWXlu3PFPs57TC8aRG04pSHRByqahBJalBxT7t1dXKYXyHua2cA+uuq/NIWonOeHV5Kap7+bNap6U9UIu90uvqpMYT5W97PfH0"
    b"0o+1VlheRf2xauStFftXO1a4/20oZ50wYsOr85Kq5NHVmYvpMGf5u5q//e7n95mlnF987kkTP0cWaU14LC9pTa5/NT7MXFmwrniO"
    b"cp71SlVdV6/85TGpnuH/9aR3jq9muLSWG2lU/9j5q7VQr6fD/99PWYPKn8sKU87aYTYsZ9SqgvVSqXL9sVa9URfxaY94XevJr/wM"
    b"0utYVSvq/FOfZar5ZC1Fqssn9TvqXcn3zlFeuaq7CBWu7rpefumFwVo58X9QSwMEFAAAAAgAAAAhXA5XCgCsDgAAwiAAABYAAAB1"
    b"aV9hdWRpby9zZnhfaG92ZXIud2F27VlnmBTF1j5V3ROWuCzIkgUEQdLqgiASJAhIELwgkuRKUpKAH4IgqAQlC4JcFJHgqhdBP0FZ"
    b"LgoSLggiGdkVFxRJImHJYXemu6vOfadnFmaXBb77PN8Pf9Dv09PV3VXV7wkVzpn2LZs3X1OWqFPjZ5q9MGhY2VgiEsDY71AYIUhS"
    b"LPXpOazne6hz4+BbHllvc69FdzxEtrK4Q+1b89A34daMo5mJbJAuwlfjOqLLN0NGwXBbRyMn/+wcVRR01NUBomvdkCdLZ+Fybuxl"
    b"Dla5Mb6ZuczGWNxS39m555Qhuzy3s8jNfpC7xu7sAToX3IqBzoVBtO7CejEj8ETgvQ081xFuk90rRA5NRrNzrsOOgnUbRNfLanuz"
    b"vm8locjhD+ZNct5e0tzkNrNJnZvMNyS+IWtYmuB1BHJB1rtoyW/Im3M85PT+/xtyen5278vNz1QO29lRVnRy2CSrrK9bIswyS/vR"
    b"GvcBfiD8mwVfRNPhWSU8eyhXf2GdZbrIADKz6S1LZ+FvZ2nGRH8xlIfyUX4qAMRSIaAw3QMUwbUIrvFUjIpTSSpFZYDSKIXK9wKl"
    b"8Cb0rphbP4TCQBx6iAUKusiP3n0RxgJsFbhk8FW+zOc5nU/yET7Iv/DPvI938w7eyt/zRv43b+C1wAaUNuLJVt6Ot6n8Gx9Fi4uQ"
    b"w0C/JakyJVIDepKepQH0Kk2lebSEvqXtdJBOU5DyihKisqgtmosOorvoJ4aK0WKcmCTeFu+IWcA7YqoYL0aKQaKHaCseFfeJGHGe"
    b"9tJX9DY9T/XA/Sh/xa9xCy7AqXquflaX1cfUx6qXKq+OOZ84zzuVnHT7K3uE3cQuaB+2VliTrZ5WA6uM5bUuB48E9wV3BLcFdwZ/"
    b"Dv4RDAbjrESrqzXFWmtlWI/YY+wddinnZWePk6D+oZTqr9N0G0hbk5ZSOTFXFJBvyoDsZ+w3mphfmAU8Az2bPcW9fb3LvBe91X29"
    b"fe/61vgO+q74TH8BfxxOj/+a75BvvW+e7yXfYz6fb6d3qrepN9Pzmedpj2XON+ubB4yXjRhjvqwh14lWIo36Uga/ybG8UCfojeoZ"
    b"dc6Z5FRwttiD7OL2Vmu0VccKBNcHpwS7BWsHiwadwKnAoUBa4GDgeOBqIF+warBDcHzwm+ClYKI1ytpu3WuPtH+26zgLnDxqlDqv"
    b"+uhDujOs2p5SqJNIE51kquxg7DFamOvMRE+SJ8b7onebt5xvqG8d3Luef4h/vv/f/oP+s/6gX/sD/jP+FH+yf6q/q7+C/4Rvga+t"
    b"L+id533Yu9Pzd89pc7B5yRhinJY9ZZpoLdZSdfqI43iCttVQdcbp4xy3+9rnrJFWjLUoWD94JDA1UDdwOTM587XM1pnlM2Xm6YwD"
    b"GfsyUjMOZVzMyJuZkNklc2rm95lmoHVgXuBCoGVwaTC/9Yp13Opob7Mfc751aqmvVQ39ha7KS7gsfUCFxTThiP7yF9nY+MQQZjdz"
    b"uanMZp5Jnk2eDM/93nbewd4J3rnexd7/9S71LvJO9w71dvDW8Ervbs/7nm6eeM928zWzOmwy1rjP2CR7SEe8Lx4UW6kH2fw+P8S7"
    b"9Is6v16mOijtfOF0dQo42+xJdku7kH3ESramWv2tdlY9q5pVEahi1bZaWS9YE63PrVTLYzewR9vrbcNp48x3LjpPqCRlq456hS7M"
    b"L2OUJdI/6Cp1EF+L/LKv3CCLGH2NfxkMy0wzt5mm51HPAM9sz2rPb55MWKmY9z5vJW9FbxlvQW/QcwReuMgzzNPME+c5CK/qZhY1"
    b"dxnjjETjsJwma8vDYoKoIvbSK5gZNvMgvofX6wG6tP5JTVQNlOWsccY4LZ1456S9zv7AHmU/Z7e2H7Vr2JXtSnZVu6bdyG5vD7Sn"
    b"2V/aKZjaE5zezjznZ6ewelrNVUdUFT1Mr9f5+Fn+HDNIE5pOaVRBvCRWCyUek+PlJqllHWOgMd/Yblw1ipt1zY7mIHOcOdtcZH5q"
    b"/tNMMueaU8wRZi+zhXm/Kc2DxpfG60ZrI974XSbJ3rKiPC4WiE4iFnZ4nWrRWf6Uu3Fh3q2n6Gbao39U01V7VVqdddY6M53+TnOn"
    b"ohPjXLaP2PvgJ9/bG3Fut/fbJ+ygXdCpjPf9nBnOKuc4JGimRqhl6qQqq7vo93SqLsRteTrmOz81ozdpAwUoUbwoksRPgkWC7C4n"
    b"yS/lHnlO5jHuNxoa7YzuxgCM35HAcGOw0cvoYDQyqhpFjIA8KL+V78oBsrEsKk+KVeJN0Q7z3h+0DFZoiPViH3/AvbgG23qLnqV7"
    b"6Icgya8qWb2t+qkWqoqKVQEwTHG2QqqVzlfOMudrZ7XzA/T+p2M5hdQDqrnqq6ZhBBxQUlfTnfVEvUqf0iX4SR7DKzAfl6S2NJZW"
    b"0FEqJBqLwZi9vhfpIlY+JJ+Sg+Vk+ZFcJbfKFPm7PCHT5QUgXR6XaXIbmH8qZ8hhsousJ0vIDLFXLBFvYLauLGzaRQtpMCTIT4d4"
    b"OY/l9lyBM/UOvUiP0O11DZ1Pn1M/qVXqQzUBo74HLNNSNVX1VB1VVzVEqY3qpgaq0WqmWqzWqf3qmorXdcB+lE7SP+qLujg34QE8"
    b"m9fxKS5Edak3/CmZfiGHykKKnmIsfOEbsVucEEGRVxaHdyTIuvIx2UQ2lY3AtzbuK8p46ZVXxGGxXawU87G6PC+ewAjII87STvoC"
    b"K9IAakmVsPqd5B/4nzwJX2zDCfCpgD4MFsl6oZ6sh+u+8Io2upGuq2tCsmq6qq6iH0Cptm6oW0Da5/Qg/YaeqT/Vq/Ue/Ye2dRH0"
    b"0or78lucxOuxLlpcjB6mp2kopFhCW+gIPKqgqCTqY2XrgZVvnJgOuyRBv8tEMrgmixUoLRYLxRysh2PE/4g+0HsjUU0UE1KcoVRa"
    b"R0k0kYZQJ6yE5eBH57H+fscf82Qewl35cXhUMTb5ov5d79Wb9Er9mV6gZ+tp8I7x4DoaeF2P0RP0DPj7Qr0UPrNZp4D7Ne3hEmDf"
    b"hDthhhjPc7HGbuVf+QJ7sbdIpCewmr+EMTGHFtM39CMdoBN0iZjyiaKitKggqooEkShqiYfx+6CoAV8pI+IxZk2RQWfoEO3GaFpG"
    b"86H7V6kPtcP+oDp2KB66gr3DXlh7KebXiTycn+eO3JzrgklFLs4F2c+SLbC7rC/oc8BZnJd1ALoWnJeLcGmuzLW4Mbfj7tyfX+Wp"
    b"/CH6WsO7sIO5hP1UHFWk2hjNHbF3GAb+s+kj+hwSbIEnp4DXn2B3HjNvkCyyScHPbMqkK3h2GiMnjfag5how/5jeo8k0igZCD0+6"
    b"7MtgX8bY9RzjFN7M/8IaNJ9nQnOvQH+9uQs/BU9oyg34Ea4JaWpwNX4AXKtydZQT8bQhrNUK4+dZyDyYR2DVfwdzwmJOxt5qFx/g"
    b"P7EbExhnJegBeoQep6eoO/WHJ42it+BNc6DLT7ArWU4rIc1q+g6eEcJasP0Gz5bTZ/CUD7GqTKXxNBq26wPmf6OmVAfcy2Iv6Me+"
    b"7wqfgJem8Bb+FvZewgv4XZ7GE/gNSDGEB/IL3AP8unJnfgbo5J5doeke4DwQNYbx67Da2xivC9F6OXrZjB3hL9DJOawFhD1mHLyn"
    b"CvynLr7cDlboBh4DweYVeo3G0QTodApNoxk0k97BOQu/08F4IjiPoZGoN5BeoL/TM2jbHFqvTdXAPR67WB850M9ZPs5p+OIPGG2r"
    b"+EtoLwn2n8Oz4AdvQaPjsE8cyaOBEZBoJI/C/Rt4GuI8C/UWYC1ZCsnXQOdb4YcH+DBmzsvYj0uXewm6D9qqCf03xozRltpTF3oO"
    b"EvQDryGwxcs0nEa4GAkMx/1QcH4Ru7hesFaIdStYLsT7QWihHDw+Dv0SBcE9HZ7/K/Ziu8B+I8ZwMi8Dl094ESR4Hxp9FwxnADOB"
    b"GfCNWXg2B+PyQ8i4GGvtMl4J3hug8R38E3R+GB5zDv3a8Bofdsn3gH05+E4NaL8O1YcEzcCmLXygI5h1pq7wh65AN6AL7jvj+d/g"
    b"ZU9irD+O2g3QqhYlYDdfHr4ejx7zISaR0HuQr+FLp+A7RyBBGmagvbyTt8GLNoLPOsiyhlfDF0JYDazBk3XYRW8C161guxv1U9Hu"
    b"ENofRz/nofFr4E1u5BODLxXG90rC0hUwS1eBBR6EDLXA51HMevWx+jSOoJGLhnhWH28egZ4fhrUSqCpYV4T0ZaCDeERLseDuR98S"
    b"I9ZBBHYtEuecgc6OgcVhRDv7YYtQvLMH/HZDnh3ATve6HecuF7uh6RTU2g9P+R3twvzT4YcXoPlQNKegfQPzmp/yYn6Ic+O04hgD"
    b"ZcGmPOSpCIkqwypVwLEaJKuGawhV8LQScD88LsS7pMu8sBuvhbiH4jSiUEQZcKO0i7BAiP0f8KLDGMO/AuGIbb8rSSp4prjlVJwH"
    b"gQM4f3NZH0OrLNaX0ds18A5H6dKNcn3gnh/fjXPjzGJgEo4yQ7FlWfALSZGFCrgvD8bl8OZeNwotAXmLRqLNUJQZA/ZeN+8Q5h+K"
    b"M6/hq5fw9fPgcIZPg81JeNMJ8DoOHAXHo65dwlxDz/5EnVOomY42l8D6CqwYdCNnHfEbD3hnRcyFIjFyUZd9CKXcGLm0K0WZSMRc"
    b"CijpxsnxqFkEnGMjkXEonvegV3Ij41AUH3Bj95DfXAJC2j8LLumuD53CecaV4bQrTeg33dXvObC9gNoXXcZX0UPAZR3KNbDrKWHe"
    b"oQxCDLSez+Vf0I3TC4FPKGoPo3AE4buQbgu4yO+2yetqOUvPIpITUe537Ej2IRTdXwWLEPsLLs6D3wX3LusaZnspgitui5B/ZEbx"
    b"DudIwrmRcF4klKuIieQr8l3PWRSMMLxxLejyDSNfFPJGkMft5UZGxedaIZx9Ma7nSrNyP7nnOR33zMpAWS7nrPucOTk7Ww5IZ8tU"
    b"hb+RM1t7c8ZW3jJPJXPNW92cs8otw5wzX3hzrlZF/eqITbJyV7fK5YvbQOa45o475/dzy+JGX+/0n0PuXxW5vI3+F+LOuei/6vHf"
    b"/P/y1+H63/5zdPf4/9f6Xe3fPe4ed4+/8vEfUEsDBBQAAAAIAAAAIVxqGpchN6UAACwrAQAdAAAAdWlfYXVkaW8vc2Z4X3JlbGVh"
    b"c2VfbWFpbi53YXYsuwV021jXNiqWLLMdcqBNmZmZmZmZmZlppswwU2ZmmjJPMe2UOcWAEzPIYunu//1uz5Kj2rKtffZ+aK2kc6vm"
    b"zYuWQZEejbo3Gz5uaroNQRAU1sLrcDIDRTDEhgwdNHUQAtdIuqSL+v89yv87U/53qHD8v3+ajv7v3QS8i0QoOAwIA8v4v8OCmBEn"
    b"koAkIgWRQkhxpAJSCamFNEKaIR2Q7khfZAQyFpmKLECWImuQLch25CByDDmFXEauIreQ+8gD5AnyFI4MeHwE6y48ew05D1ccQnYg"
    b"m5A/kbnIJGQw0g1pgVRHSsK3EEhE/6Fn6Ff1g/p6fa4+XO+k19GL63Zd1nK019pN7Zi2VVuiTdIGah21xlpVrYSWqjk0VsM1TZVU"
    b"QeXhkFVdJTWzlqCla2W12lpLrZc2WpunbdAOaze0N5pHI/Q0vYbeWR+nr9AP6ff0b7A3SUg1pDMyHlmFHIU7/4EoSBJaBW2HjkAX"
    b"odvRC+gz9BcqolasKFYTa4P1xyZiC7H12B7sJHYVe4C9wN5jmdhvzI3lY17Mg+Vh2dgP7CP2H7z2D3YU24YtxSZgPbD6WBGMxHLQ"
    b"B+g+dC7aDS2Louhb5DAyA2kOO/1DP6nP0BvprP5G26kN1cppMfWOulLtphZWA8otZa0ySKmmmJRs+a68R14kD5PbyTXl4nKSbJEZ"
    b"mZRp2SQnyEXkqnJreQi8vl9+LIfkNKW9ski5ooSVCup49azKqXW0pdoLzQX7ewH63xHZg/iQOugK9B1aCBuDXcAkrD6+EL+Dq3gN"
    b"Yhyxj3hFqERxsg05jlxJHiCvkE/I9+Q38jes7+QHMoO8QR4lN5DTyO5kVdJK5hDXiFVEb6IYEcAv47PxeriG3cTmYDWwMHoSHYYW"
    b"QN/BvDSF2Tynj9QL6u+1tVoLDdGuqdPUSlDnaWW8UlGJyFfkhXIrOU7+JZ2Xlkm9pcqSWcoXn4lnxG3iYnGiOETsJXYRO4qdxZ7i"
    b"YHGSuFTcIf4jfhQVsbjURfpDuiHxUg15tnxPtij9lXMKow6G3UyH+cnTOunX9eIwgwg6Hs1E22DXsBL4JlzDRxAviMrkJjJEtqH2"
    b"URGqIb2cfkYzTENmErOTuct8Z3iGNtgNToPFgBkCzDvmIrOa6ceUYDz0UXoAbaNvUIMpnNpD1iCfwh7k4hNxHpuL6ehCgOhCwNpC"
    b"HdEXa6S2QrWpfyvFlUtyS/mbNEtKkq6LQ0W7eF+YI9QUZP4Bv5EfzjfkC/E0H4llxzJjX2LfYu4YHzPxxflm/Ch+E3+X5/hywijh"
    b"mOAXaohLxDdQ+VzpvVRZ3iCH5e7KDaWougYQMQyw0wh2uxCyAcHQKWgW2hXmsiq+H7cSc4hsoj15kUyiZlOfqGr0Wvo3XY1ZwmQw"
    b"dkNnwxrDfUPUUJBtxg5l57Hr2R3sXnY3u4Vdxo5j27MlWBFe/8PQyBBl9jLNmN/0bJqlN1EJ1CaSJecQbrwjfhGLwyahz5DCyEw9"
    b"AxA5VX2spCpT5GdSCWmZmCu0F67ypfl9sYKxA1xF7n50YJSMXoiMjpSJxMIZ4RPhreGVsDaHj4Yfh8Ph4pGhkVMRPdIneidajjvA"
    b"FYodiVXhH/EDBV04ILaBjh+Reylm9b46W6uku/XdSBeUAgQOhUovET3IKLmGKkifpCsz55kyhl0Ghh3DPmJTjCOMJ4y5xlRTS9NY"
    b"03LTTtNR00nTMdNu02rTZFMnUymTZPzXuMLY3KixZ9m+LMYeMDQwfGBGMTy9iKbo5RRFLSIFwMo3vD1+DSuGrUU5pA9yWy+i/6Hl"
    b"qW3U04pDmS5/lZpIJ8QEcakQ5Ufy32O9Y5+4/lxudHrUGD0caREJhveGe4aTwj9D50OrQxND/UJdQ91CA0PTQltCd0JcqFp4Qfht"
    b"uGpkd8QRXR9N4o5xTWO5sU18CwETH4hrpL5yRZjybPVf7Yi+GpmE9sTq4YUJkswm71E76AlMPQPJPmQXGCuaPppmmI2WzRan9Q+r"
    b"z9rCtsX23sbaK9lb27vbu9qb2UvaNdsj2xJbFdt763iraJltCZr7mm+ZEk0jjefYiKG8YQizib5N5ZJGsjzRHh+PrUFPIhm6X7Nr"
    b"NdXBynr5viSJNcTZwn3eyY+OPebKczujjuiGSFLkWLhxOCu0LtQ0hIWeBP8OTgl2DzYO1ghWC9YNtg0OC/4RPBv8FUwLDQgdC8mh"
    b"ruFL4bTI6ggWXRDFuNVcSuxsrA3v5TcKdUWvuEfqITuVN8pWtY9WVPfr15EVUHVJXMAfE9vIYVQlWqbvM38aWrC48bpxrCnJfNPc"
    b"xxK2LLSStkW2iK2P/Yrd4OjgWO647HjvyHMEHLmOV45TjjmOOg6vfb29uP20raRtszVqaWFZa35sEoxpxhpsS0MnphPdmqpHliLs"
    b"eAz9gFzWt2hT1M5KFTlR0oR8/mvsLfcm+iXiCzPhcqEBwZ2BHH89/35fgu8vb2nvM88cT12P2ePP/57/Iz+c7/Q09SzzvPNU8e71"
    b"pvgO+Gr6P/v/DDQM4qH/QofCSyKjot24FrEGfB2hjlhfaiK3VjqpPbX++lBkBDoCZrsf0ZlsRJWhrYyXuW/YyPYyJpn+M80zF7bc"
    b"snSyfrL2tL2w1bL/bQ/a6zrmOy45fjkIZ6qzlLOss6jT4eQcLxw7HQMdyY6n9ol2k32PrYTtsDXVusLiNbcw/236bSxq7M+uN1xn"
    b"vtEK5aSKkhWI6ngtrAZaBSmjF9LiVUaRJb/4W/jEv4o95zKiLyOfw/khNFQw2CIww3/eJ3hbeQ977J7l+db8A3kt82T3HfcW9xz3"
    b"ZPds+HnXrbs75p3PK5Z/Ir+RJ8+zzzvK18hfMpAWTA9VCLeJTI4e4L7FCgljxRuSQxmrPtFKIn+iOVgTYhcZpZox6w1vWKupkXmk"
    b"Zal1s22bfZVjsrNlnDX+3/jRCVrCgsRAYpukrUnPk8JJuAt3BZKeJG1MapnkS1ycSCbOSvgWXzV+btw/zmwH7ShoL2urYC1tSTMb"
    b"TEH2peEUs4zuQ1UgUeINdgidhbTXi2mI+k2+Kx0VtwjL+UWxxdzK6N+Rc+HXITlYPjgmcM6P+fv57nureM94qnue5I/It+c/yluR"
    b"1yOvcp4rzwzLlVclr1fe6ryMPFf+5PxP+W09zzw9vUHvFl9zPxHICOwLLgqNCQ+MDIiO5GbHtvJXhSwxQW6vrFFfaonIYPQspuMd"
    b"yD2Un65r+IPNMFrMrSzzrSdsL+xuR8wpxgXi3yecTZyVVNn1yTUhOZw8OOVWCplaM7Vbar/UDqllUkMp+1PqptxNrpS8yvUqCUtK"
    b"TyyTUCTeGPfTcdQ+0Ga0HjPXNT1gmxpu0OWovwkMH4W+0KtqOxRSnirm8UNj7ui0iDl8NjgoUNDv9T72XMq/mPfAnZubljsi50F2"
    b"9eybWT2zDFkvfh/9ve339t/nf2f+TsuakPU2q232u+wJOa7cN7k73VPyeuS39DTztvX1988K7Aw+DAnhCtEx3IlYgK8mzpMeyja1"
    b"l7ZPz0XKYGPx48RvMpFuzkw0bGLPGB+YXpk/WN5YH9nO2zc5RjurxwlxZ+J7J0gJaxLjk9YlqUn9XGddnKtscrfkCclzkmckD0tu"
    b"kmxPfula6CroOpNUIWlPIpLYKWFj/IO4XKfiQB2i7bf1jmW9uZvJbLxuGMBI1BoyidiJpaBbdJO2UIlKI8QvfOdYRrRN5GWobzDo"
    b"X+er6fXnn8tb4h6a2z2nV/bErO2/P/0q92vbz8SfZ34M+FHiB/MD/eH80eDHkh8/fnT/mfVz5a8Wv1OzqGwqJzm3sXte3pP84t6N"
    b"PnNgc7B4+H5kJBfPPxYWSDWVqHpGH4Wm46+JBVQx5p6hu/GbqY/lmbWsfYHjrjMc50gomOhKQlyvXeuTa6e8SGmX+k+qKa1N2rS0"
    b"VWmr02amdUpLSHuUOiI1mjIx5Uty9eRFrlsw6dbEognl4svGpTuNDp/tsXWHZZS5oinCnjeMY4rTX8mNRHNcRs8gw/Q07YOySe4i"
    b"JYo/+FOxBVyPaPVIapgJqQHJj/gtvhLe1p4Z+WfyIu7G7t25dO78HCxnc3bV7KysA1mTszpmNYDVEc4OZeVnNcw+ml0453ROm1wp"
    b"97p7Td6E/MGe4d5Zvh3+jIAx1CN8NhLPLY1p/ELRKO9Uqmgv9HGoBT9LdKKC9BpDMeM/psaWB9Z69hMOU9zA+IMJnxLVJGuyOYVP"
    b"eZ66Oq1agUcFGhU8UNBbMDW9Snql9Pj0HwU3FSxb8FSBhAIj0vanPkx5Bz3/J2lVYvsENP6gs5bjnq2B9bw5zbSQzWSq06vI73gV"
    b"bDnyXautbpcRabyQHRvGhSLLga+/B/b6J/o6eht5muT3yJvnvpSL5g7IeZXdLduX9XdWj6ySWaYsHI7iWZ2z1mVlZtWBSovlnM1p"
    b"lRvMPeAenFcuH/dkeV547/pu+u8GMoLfQrFwXLQG1z+2gr8i5IlpchdlpXpPk/TK6GhsL/6WoKjq9GBmpeEM+8LoNilm1mqzWe2U"
    b"I+r45LwYtzS+dQKeeC6xc1J20hjXL1fr5APJ3uRiKe1ShqaMSumXUj/FkvIseVqyKXmDi3ANTTqX6EtISCgfXz2urNPpyLddsI6z"
    b"pJhvGDuz35hB9BeyA3EDK4au0gOgWJekFHEpH+KGRr+HB4eCgeX+cr4fnn35U/K6uVvnds4Zl70r69fv+r/P/qr16/PPjT+H/Gzz"
    b"s+3PYT+3/vz+s8Gvy7+a/nb/3pc1IbtTTvPcdu5heWvyH3hYXx//1UB6aEPYEF3OmfjNQkHphFwDKm6DvEQ74c+IBtRJ2moYxV4x"
    b"KqYqlv7WObaV9pWOOc5+ceXjg/H7EholvkrsmHQrKcU10nXA9Z8r3xV1BVyfXZddS1yNXeGkzUmloMqyiTsStPju8Qfisp0FnO0c"
    b"U+zrbYes5y1XzP+YzhoPgGbNZPrSdakkMog/xLajY5F6uln7ppyWF0pdxJICwn/hrkV3R/4MTw+NDY4KjPPP8W30nvd8y4+Hvh9x"
    b"E+4Jue6cSTmGnPPZY4HbnNloNpadkF03e3r2PZjtLTkpuRdzB7oL5gXyXuf/63nq/ebDAlWDU0P3winRBZwvNlT4LY6UI8pizYkc"
    b"QWvjGURfyk1PMATYkaYP5nrWrbYsexFn17hp8csSliSOT2ruYpOvJXdN+ZjSPHV36vdUQ1paWnIakvYydUVqudTrKdVStid7XWVc"
    b"PZKmJM5PmB0/Iq6FM9nxy7bX2tWCmo8YW7K/mbm0gzpC1MVfo2MQSj+stlY46bA4QEjnPdxtqHZ5eH5oYXBt4Jj/tY/xtfXu8ej5"
    b"4/M9eTPy7HnX3JPcNdxGty83M/dLbm4u4i7h7u3e7s51N8w7lJeQvzE/2XPS08ob8u739fMXCvgDD4IHQivCMyPjoqO5cbHp/DLh"
    b"b/G89J8cUuK1evoIZCN6G/PiLrI5NYneztwx/GJRU7K5vKWOtaGtvr2Ko4BTc76N2wUMziaeSKyfdDepqmuby+0qmdw9eXLy7OSJ"
    b"yV2SCydnuv5wJbt2JrFJwxJPJ2TFG+LTgM2cDt6WYd1s6WDWjQfZhoY39AAqmxiOZ6EDkE9aV/Wl3EF6LfTm87iF0fTIU6i6ccDh"
    b"D3q/eb7me0GLG7r/zP2V0zHnLXTXlf0l63zWnqy9Wf9k/coqDB3OzO6Rk5WzOLeyO+y+m7c3f7VnmXclsNelwKcgGa4ZmRQ9w4Vj"
    b"NYQF4mPwJX3U/VquXgodju3B3xAIVQIUq59hDDvJOM7U39zcUsTKWW/YZtiLO546Bjl9zrFx3+Kaxe+O98aXTRiUsDzhYMKFhMsJ"
    b"JxO2JkxLaJFgTngcPyM+Of58XIO4u86azoMO0tHXfszmtRazdrPMNW83nTHeZO8Z7jD/0EepjeQMogewmRH9rp/TFqsdlYKyX7wl"
    b"rAe9rsu5onL4V+hV8HHgkf+lL8uLect5huUfz9Pcg9xvc3vkenI25LTKicsJZf/KzsnWskvljMq5kVMkd3duWfdz96K8FvkFPLQX"
    b"8Rmg3y2Cs0NXw3i0J3cpliz8IfLSOCVbHaB/Rrpiz/CG5FkqmZln+MCWMk00n7R8sao2myPOaYjzxt2OX5hQPvEJcNjDpJKuaa4z"
    b"rneuXFe266XrqGucK911N6lj0n+J9RJ3Jnjjy8cPiVvlPOK4ar9ju2W9aDlgXmUaZ2zDFjPI9EvqADmNaImnYEHksb5fW6gOUVrL"
    b"1aVSYmGhMF8qVpPrEB0f2Rp+BOmieXBzwOtv77/uq+y76G3o/Qi+u5Tnd/6R/Jn5XfLr5JfPL5dfI799/sT83fkf89M8EzwZnmre"
    b"497Svsu+dv6Af2egazAxlBW6Ht4Z+SM6i5sWm8UvFbaJZ2G+o0qa1lqfg5xGf2NJkKCXUJfpXCaOrWscCM57k2Wv9ZBtr32dY4qz"
    b"TVx8/Mv4eQnJiUcSiyStAQ4v4+rvmuda6VrsGuGq6eKS9iRVS/onsUTi0oSXMNmV41o7uzja2WvZkqwe8wXTJGNx9i0zm06hrhCd"
    b"8Xx0EeLSL0CPg9JWsYkQi13gZkVbR4qHLSEiSAdc/jq+sd7THsQzNP9T3sA80X0Q+lzRbQc2Y9wF3M3cc90P3Kl5S/KEvLn5ZkBz"
    b"d6/J99z3l39coHWwQiglbIlQUZwjYyzvEFLFElJVuZHSDvLGYH00MgGdhE3ExxCDyC5UA7o4Qxt+GS6zS4ytTQbzHfMES6L1srWt"
    b"7ZOtv/2TvY3jgsPhHO485ww5i8d1ipsU90fcuri1cYviRsY1jYuL++jc4KznzHRMdkj2GXa3rZ3tiJWz1LJMMu81PTB+YwMGgRHo"
    b"IPWTfEacxddho9FGSILuVq8qK+U+UnkRF77GrnI7oksjU8NjQ+OCMwNr/Gd8mV6Xd7DnWn7h/O15RfJuuEe6i7m53A+5GblvcwO5"
    b"ae5+7nPuxLx14L4v5g/0pHnzvA98p/wHA0eCl0Mvw9FIOtcttp5/KSRI/eXjSkxtrK9FPqIF8IHEbvIdRTLlDG3ZQZAkx5oHWlpY"
    b"C9v8tlP2fg7Nsd7phPry4urFL4q/FP85PhDPAbbfxp+KnxlfPT4nbmVcetwJZxnnHgfrGG2/a7PaugNzZZhVU0lTe+MEdrXhMHOD"
    b"/o/6QQYJDTfhLqw4WhVponfVhquzlQ3yCemx6BbMQnXA9FbuRdQU7RjZHvaEmoT2B9ngrEDIP8kv+db4SvteeRd763tJ7wfPRc9u"
    b"zybPFs8Bzy1PjifZ2xdmm/KN92X5Rvhj/o2BOsFg8FxoXrhrpHq0COeKJfHpQkWxhTRU/lM5o37RjEhddAK2H39H0FQ1ehCz3HCM"
    b"fWD8aPptzrZ8tT6xHbfPdzR1qs7DcQ3jn8Q3TjiegCQ2TZyeuDXxYOLuxD8S+yYWTHyZMCFBjZ8Vnx3XMG6184lDsLvs5WzVrVUt"
    b"Jcx2U5R9YTjATKHrUxSZgW/EeqBpSLZ2Vl2gdJbLSiYxwv+OfeG+RfMjaKRouEtobfBdoDT0WfXN8dG+fZArEe8DzzbPTM8IzxDP"
    b"OM9SzxHPB08cVHrWa/XN8nl9o/0h/6JAcvBacHDIEX4UXhppHjVzn7jjsfl8d6GyaJNC0hv5irJLXaKN1jshNdA0DMWz8IfEIXIR"
    b"1YeuxOCGV4Yd7ABjQdNH0ypzTUumZY7VbttjK2LfY7c7Zjk+OEo7JzvPOL87ibjUuBJxxeIS4yTnK+d2Zzcn7jzgqOa4Zq9k32ET"
    b"rK2sayz/msOmOFMZY022rqEGU5pOoGTiC34ZW4MOQqrohPZOOSLPljqJZQSW93Ofos8jj8PPQ5lBIVAw0MW/2ffb2xiyZTnP9fze"
    b"+Wz+s7zdeYvzZuUtzNue928elt8x/wyw9S5PGe8T7zRfeT/nfxQ4HFwbWhSeF1kYXcXtjF3gnwse0SSXVzqqU7TN+gXkBZqLSThD"
    b"2igHbWJUJsfwkN1pHGkqbf5hXm0pY71tbWG7b6ti32r32Ws6pjuOOl443A7eITqCji+OG46Njn6OAo539sX24jDXXWyZ1v7Wj5Y2"
    b"lsvmZPNM00tjYZjuywaRqc5MpA9TH0mGrEr0x5dhJ9D/kLAer9fQeqlzlD3yAylfdIr1hbH87thbzsK1i26MZIYrhP8M5QY7BG8H"
    b"agVu+Fv5f/iW+Cr58qG/i70DvW29kCK9g7xLvBe9YW8D33Yf5p/lV/3rAuWDn4IbQ93DxSJINDv6lsuIZfBvwY0JoNWV1C7aDH0X"
    b"8gDNx6xEZbITNZZezGwwbGe3GzeaFpqHWOpaGdsj22x7AcdFRx3neWdy3OS4a3HhuKT4CvFV40vFW+J/xR2J6xuHxv3lTHdud9CO"
    b"EfZrNszW0DrFsst82/TR6GF5g8agDEIrZIwI4G7sB/oZea+/096rX5UcOSYZpRJiK2EKfzD2jUvnxkRvR9Iiy8Kx0KQQH/wjmB78"
    b"NzA1UD4Q9t/x/+2f6x/tH+Qf7B/vX+Lf73/qV/zVA7MDDwMpwZnBzGCb0J1Q3fDdcNvIt8iMaAJ3nRseS+Rf8CuE1qJV+igdkqcp"
    b"rdR0TdTe6meRtehYrA1emqDJLPIWtZUey9Q3mNj3UHtPk918zzzWYrYetla33bTVsh+32xyjHVcckqOCs7tzonOec45zjLMd1Jzt"
    b"2OFo4si0j7Ln2nrarlsd1r6W7ebnpqjRYSzBVjZUYyrTJahEEiPysRfoWWSjPkXrptYCZ2KQBMHL58bcXDhKRgtHWoXnhK4G8WDv"
    b"wG1/Zf8FX2PfT+866KrLy3l+eL56cj2ot7R3sPeoV/UO8L3wtfG/8Y8I0MFzwaGhQuGc8IXIn9HBXONYCd4mKDDbX0Gd7ykX1cPa"
    b"Vn0ZMgnthdXHCxAS8YrcB32uyPiYA4ZOrMBuM5Y33TA1Mt8yV7LstGiW7tZDVo+1pK2PbZntMFT/zPYSjlu2I7bltgG28rao9Zx1"
    b"ONR52dLJkm2eZOZMk0w5xi7Ga2wyO8XwkHEyvekdMN9WsjExCd+F/YvmIxakgt5BG6+uVk7IzySvaBOrCwP41bFbXDRaKTo1cits"
    b"DY8KZQRrBk8HKgSu+zv7Y75DvsG+sj7Cl+f96v3m9YM61/JN9d30xfvngCeZFECCO4NNQ0LoSnhxBPI5lxYz84SAiaRkkZOV0mpd"
    b"rYM+BJmOLsf+wg8Rp8CTnaYPMVsMc9k+xoomyXTNPN6SYD1vbQSormHfZY/ZGzrmAKofOT46PgO2LzrWOHo6EhyP7GPtpH2jLd62"
    b"1qpYBltumZ3mgabDxhy2ENvd8Cdzif5BMVQFsisxC6q9h7oRG1JbH65tVZ8oulxbniXdEmmxu3CCp/gRsf+4+tyFaMXoxUiDyOvw"
    b"uLAtfC00LlQylB+8HFwRHBZsFaweLBMsFawYbBDsHpwR3BN8FTSG2oX+CnlDLcInwkmR1REmujqayB3nmsVyYmv5ukJIOCGOkSrK"
    b"kvxY2a5O0FrohREd+Ypex/7GZxDdyIqUgf5On2MWGFqyRuNj43xTWfNrcCm4dY3VZFtky7M1B1b7DDNey9HNMRhWV0cNh8nxxr7a"
    b"XsP+zjbMlmcdYH1iKWGZbb5nQkzVjAPZJYY9zEX6PpVBvibe4m+wV+hz5Kn+WHukPlaey++lLFEQHEJVvl9sHfc0aon2i/wTTgmv"
    b"CtGhdcGi/8N0hQDvf+Y/5d/p/8u/13/J/96PB+oEFgSeB4rDTsSCY0Oe0OQwGtkWqRr9ACmyXOx7bAvfXjCKT8VVUnvZobyHavtr"
    b"hfQs/SAyBC2IfcLW402ICLGXbEl5qVV0MeYa09rw1tCL/cB2NN6DOd9sCptam7ebs8zFLAMtGy03LT8sssViTbImW+OspNVneW45"
    b"aJlsqWGJmo+au8BsrzOlm44ZSxn3sw52jiGTqcGsoj9SBamB5E7iDU7h1bBB6ArkLPCZqKaqDZVh8irpovhdsAiN+dmxK5wabRnd"
    b"EeHDfcKPQw1D94DBcwOrA3UDov++f7t/AbiVif75sAN3/by/dmBlwB3oHHwCTPYJao+P3I/Mitbi0NjL2GF+sTBEbClVlgsoJlVR"
    b"fVqmnoFcRQ9iq/AJRDuyBCVRj+g1TBsDwp5iOxk9xjkm1DzX7DV3tpy0KJYG1pmA60fWTGserO/Wp9bj1kXWdlab9alltqWI5b65"
    b"j9lrmm4SjdONPrY/+8xQxbCN4emu9GmKpHqRJ8GNtYf59qJ10JXIZ720Pkd7oRZWZyqv5LLySskjdhAvC4WEDTzBz4tJ3FyO4DZG"
    b"i0VvRfpHiMi58LBwevh36HRoUagv7EPZUHqoQKhYqFqoQ2hyaE/oXSgu3D98NmyKTI78jPSKfo4O5WLc+lgVPpNfKzQXCemxtFEe"
    b"qFRRWe23dhs0aw7aB6uNJxEc8R95mJpNt2QchveGTWwrI2/cZaptzjB3s7yxNLOetNK27ra/bM9tnM1qT4NltUdtGbattq42wnbU"
    b"2tCaYWkH1Zc3rzPlGmsY57O3DDxTiulBL6QOkQ+JHBzH07F6aC9khr5Nu6b+UFilljxOOizmCOWEOfzLWPnYZg7n5kbVyIpIgcjN"
    b"8PCwK/w+tDs0MdQ2VDlUOJQKtZYLNQ0NCa0O3QzxoZrhReHX4dJwtT/SO5oRbcLd4RrFHsU68z/4yQIj7hXrSp+l2XKKclsZqhq0"
    b"s1oPXdMPIW3RMPoXVhf/ji8kCpLXyW4w4wtpG7OLKW44bijFHmRdxuXGkLGr6ZyJNncz7zR/NTstjS0jLcssf8NUH7bstqyxTLK0"
    b"taRZssx7YboV0w5TJdNNYwPjVbY0u9EQZlozO+gsqiQ1nNxNvMIRvCzWFZ2N7NHvazkqq1ZQussLpZNipuAU2vPrYx+5ktzC6I9I"
    b"a+DvOuEHoR6g2PuDvYKpQW/gSeBC4HjgVOBW4EuADNYJzg8+D5YIrQlpoVlhLbw6UjT6IDqGS4bJXsW3FeziZ/GINF1uobhUj3pT"
    b"W6cPQMqhAnobWwKI1ogL5GDKRJ+mWzPfmNGGgGEs+4NtazxjNJj6mA6Yfptc5hbmseblUPMR8zHzQfNW80LzYHM9s92cCa8PNiWb"
    b"MowzjQWMt9hebNCwyGAxbGWSodZEegNFU7PJfKIncR8vi2/GRLQ/ehcpgizTc7WW2nHVpE5Q3si15L2SQZom/ha6Ck/4RvytWIPY"
    b"A64D9yM6PeqMXo4MijgjGeG14R7hUmEinBd6H3oO6yNwNhuuAhNxIJwfrhPZGpEjo6O/okM4H7cglszf4IcLCeJzcaXUFtgsUzmh"
    b"zgXNKoKI4EUPYNPxFkQ8+QOmeyRdlPkEqaMi+5IdYYwaZ5kipiHmJ+YiwFSXLT6Ly1rT2tbaxdreWs+abhUsD6DjdSw55j/NBc0n"
    b"ocOnwXuuYzlDV8NpBme60HsoN1menExcwmNYTWwWegNBkOb6Wu2TWhIc6Cu5nLxGioj9xZdCC+Eh34b/EBsdI2KHufacHv0HKq4H"
    b"qetX5HbkYGR9ZElkXmRB5E9g6VORpxFfJCHaPDoXrhKiDbjVXCZXNbY+Fox142/z5YW9QqK4AZLGRilR3iOXUa6CG/uqTtIYfZ9e"
    b"G3mHTERN2FGsCUz4LMJBHiPrU6+oQbSfnsHIzFwDbxjHZrItjCeMjKmf6YQpZKpgHmJeZz4PWP9i/mnONL8wXzZvMg8DLHtNe02t"
    b"TfnGhUazcQNrYhcY8pi2zFFaodpQm8mPRCLRGV+J3UGjSHGkp75Su6mGlBLKIHm39F0sJk4U7vHJ/KzYD+jwI+Dv15ERETJyJjwk"
    b"XBiS5p3QPkDyktCy0MbQceiyFKocnhq+HY4D7voUaRm9Ha3H3ePagVpN4+3CWaGLKIkHQK9k+ZjSU6W1S9oQ3YpcRQajNHYca41n"
    b"4/MIG7mHLEWdpsrRR+gUZiUTZroazhoothu7m/3Jphk7GxcZjxmfGrONopEymWHRJtnoNr4ADKww9jOWMUbYy+xktiT7ybDUUNrw"
    b"lBnGyPRqOgl6XZjaR6aSmwiKmI7/xtpiF1EXOhfJ1OvpOzVJ7an+oyQoM+RPUl3pgGgSZwp5fD/+fawroHswONOV0ZLRF5G5kcqR"
    b"cPhaeBXMclvAetVwjXCzcL/wwvCpcFa4OFT+OFIiuj6Kc/M5LLY2Vpi/yQ8ALrssjpYKy9/k3cpAtZjm0c7rs5AGKIk9xlbiLQmM"
    b"vEKOphLoG3QfJsIsBfe9miWMk40fjFVMy0wZJhYQPNy81PyXeR+sreZF0O86ZoP5hWmlqb4pz7gGdPkW2459Z+hpeM+0Z+7RVaBe"
    b"AzWRfE/UInbgKtYfu42mo4uRHL2Nfl5L1f5UY8pIJVPuLr+RukgfxcFiUFgipAj/8L14lD8dGxhLir3ntnNDuCocw2VF/42eim6P"
    b"ro0uh7U2uiN6OvoomhM1cjW4Udw+7jtXNDY+disWx0/gX/I1hANCnLgS/OdSiZHXy6nKSaWB+k4dB/N9WG+KZCHL0OLYI2wEThOH"
    b"iMbkV3IKRdPb6CLMCaYcMHg6u56VwJteMtKmTqYNpicm3pRqrmFuZe5obmduaC5lps1fTYdNw01ppqfGcUba+DdbmN1vSDGsYQS6"
    b"L32diqNGkdcImuiE/4V9Qwujw5HjekCrps0DTxavjJBvSInSdPGr0FK4xlflL8XqgxsdybHcpejoaImoL3ITGGpWZFikT6R3ZHBk"
    b"SmRt5Gzka8QabR1dAw4MuJ77BvniZCyFX8tTwmLw2stEk7RZKiifkGspj2G6c9UZGqVvAQ47i9RBH6BtsVdYV/wt3ol4RjQiL5FF"
    b"qfUUT/Whr9FxzBjmBsMYOho2GV4aGLY2O5Jdx55jn7NZbJTVWdyIGgU2n33HXmX/YieyjVgz+8qw3tDSIDGHActe+k86hT5BVaWu"
    b"krXIS0RZYg9uxedgWWgb9AziQKbob7Wq2iY1qnRT/pFT5MXgUHqKj4V60Ovq/PVYc5jvSZyduxIdGS0EbHYSWKxvpEmkSqRcpBJ4"
    b"8x6wE4cinyPJ0cHRi1ErNxlq7xTLiLXnPwBry8JWsRokyvlySeWdskStAq5kM/Q4iuxD22ExbCden/hKTCMN1F9UOn2ALshsZlDD"
    b"SMNDQxo7BqoMsMUA09ONG42HjeeMFwHF+2GaJxrbGtONfvYSO52tyGbBztQ1/GQWMinMeboZ/Y4aTHnIKaRAzCFUfB6uYHNAraYD"
    b"h01CgvoE3a9N0MLqdFVRlioWZbtcSr4udZByxcViunhPGAlu/A4/mS/FZ8UOxkbGKscwmPRz3AZuBkx7N64d14bryPXhxnF/cIe4"
    b"Z5zAlYkNix2O+WJ1+HV8Pt9GOC8UBPY2SH9ItLxWTlKOKLXUF+pwDdV36XWQT8hMNAn7B+uGh/DVRFHyGtmG+kQNpnPoYaDZnQw3"
    b"DYXZhdDNIsaRxkPGT0bcVNRUFzi6Axx1TEVMqOk97MFQ0Oj/2Jmsiz1vaGp4wXRhXtGt6JtUWWorqRKDiHt4IXw+9gWtgW6Cmtvr"
    b"pzSrNkX9ojRTLsolgL1TpF3A3+eF5sJPfjFfmv8UWxdrG7PHMrmz3CqorQfXkmvINeCacZ25YdwCbg/3kAsDivvG/o59AdYaz9/i"
    b"HcIY4aFQXFwu+sXu0l2pvLxLtiiLFE4Zrf5Ue2ovtVb6XdCr80hpdB/UvBbD8Gl4Lt6D+JeoSG4nEWoo9S9VmJ5Lv4YEMgWmHDM0"
    b"NswzXDBkGaxsVbYLO5adz66EaV/LLoNOD2QbswXYsOG2YRnULDMnmR6MBLxQnr5NtaZekp3IDKIJcRkvjm/AZHQQ+hAphazSvVo7"
    b"7YzqUKcDmzWTz0mFpC2iWVwpmITNfBH+CvC3wB2Eep3cx+ih6Jxo72jjaNVo+WjlaINo9+i06K7oiyjDteY2czlcg9ieGM1P5d38"
    b"IOG7MFjME6dKuLxZLqHcULqo+epiLVk/p7dAviITUARbgyXhe/EixAGiALmZJKnJ1EeqNr2F9tC1mSXMQwY31DaMgtm9bHhjyDdI"
    b"BoJlWJJVwbV9NdwzHDQsNPQwlDRwzE1mEdMQVOo8PZyOp+9SoygLdZbsQHqJZUQacR5vhr/HhmNRdCFqQrci6cgxvbJ+XWuqPVd7"
    b"qD+VcYooL5eT5ONSA+m9OBFqPy10FiT+CN+Tt/BPYitjHWOpMT/09xC3kpvOjYZ+j+Amcou4v7mr3E/OFmsR+yP2LJbEj+Mf86WF"
    b"jQIqTheD4kSJA1SblF1KZfWJOkTTtf833Z+RWWgidgFrD33+P7UuTZ2lKtEn6ULMekZgehnOQ53toaePWYFNN9Y3djUOhGkeYOxk"
    b"rG1MNobZu+wKtiWLsOcMvQ0as4OpzNynO0KS7EN9IXuSr4hWxC28Mn4IS8RWoDIyHvml99BfgAN9oDZR/1XaKG/lwXJEWiEVlR6I"
    b"I0UHIHq6UFEI8pf4hXxHvgSPA66fxa7Ejsf2Qzf3w89/Yk9iP2JKLI1vAjXu4F8AZzcSFgoPIEF3Fw+KMbGNdFDSpX7yLbmw8qcS"
    b"VHqrD9Wq2kEtXv9Tl3S4B6QHmoE2xC5iJfHtuBF4x010JW+SRag/qByqMb2DDtD1mRXMf4zV0Mow33ASsnbMYGeLsZXYGmw1tiyb"
    b"wuLsb8MNwxroucvwllnOVGO+AjLi6WNUDeoO2ZR8QDSA2S6N78BYbDr6C2mLXNbTwZFx6mD1ldJYuSyXl49JpaTTYg3xkdBX4Pm/"
    b"+cZ8OHYMOKxCTOXecOeho3+C75jHLYVpPsE94YJcWqwzuJCXMRc/gr/OxwtThY9CQ/GEmCKtkTB5thyVJyo+ZYyap47QssGP/dD7"
    b"IO+R9qBYNcGTJeFLcS9o1nnCSo4ib5FWqi91kHJTJehBgMvHNEenMg2Yfsx0cGp/MweZ46DgR5g9zEbg6tFMB6YiY2ay6av0croL"
    b"aNQ3ahfVi7JRD8hpZCHA8mQiHiruigexFVg6dgltiX5CRiMi7Hm8vl+rAF60jfpZGaMo8jq5GGh2DykqbhFri7+EddA/nj8PSK3N"
    b"U8Bt52MbYjNjQ2O9AO3dwbtMjC2PHY29gJ5X4sfyZ3iRbynsFkShj3hPLCftlpzyaplRliusuk5N0HZrJQHVdZB/kXboW0jTmVh/"
    b"/CvenXhONCRPkYn/+z3YyvRS+iWdwHRj1jK3mTzGDN6yvqEdJIku8FjfUAqSlJd5wGxlBkNmzqcP0/1pO/DWGMpBXSZ7kByxAZT5"
    b"Pt4bql2KubDTaCP0AzIWwZC/9Ur6M22ERmgH1RaqR9mo1FXy5L/ltjIm35RmSbUlXXwobgSHVg2w7RYeCScAo/OEccJAoafQDVZv"
    b"YYgwQVgkbBPOCC+EICSphuJ4SM8fIGG0l9ZLb6UC8mj5KmB5ECSNeHWy+gqm+y9N04bpGXp1ZC9iQKei39AW2Dno+Hw8C29GHCYI"
    b"sh/4FAPVEzruAT8+BtT7PY0zpZl2zEhmLrMalHwLYH4pM5npzdRinIybvggTXZ8WgREGUSbqItmdjBLriOLENbwt/hkbgUXQuSiF"
    b"rkcSkX16Gf2y1kR7BdMdU1YrxZUH8jDZKF+ShoA3eymuETuJyWKecEv4S5gFlbYBv1JdqCLUhM53EIYJ84Wdwl3BLcSLLcQ54iUx"
    b"LFaWZkg3JUruLO+VA3JjZbOSB65zE7B2I22bFtCa6dv1IDiTbUg+UhtdgX5Ei2DjsEv//++238JlvBoxlthHvCZQyITdybnkXvI2"
    b"mUnypIlKpypQdahmoEJtYTWn6lNVIE3YKIn8Tt4n95Pz4PrSpALebjPRjyhM/Mb34wPwJPwltgyrgeWh29CmaAjZjjRD/PpWvYHu"
    b"1tZptbTf6hq1jupWtimtFVW+KE+QS8se6Yw0TWos2aUs8aa4XZwrDhU7QD9rilXEqmIdsbnYQxwHinxMfCEKYkmpl7RBeiGZ5I7y"
    b"Vvm7XF6Zp7xQiqqz1JdqKW2xlqnV1DfoHr0ZsgvhkDbobjSMNgKd/owVwofjRyFxpRM9iOXEFeIXwZBlyFbkIHImuYLcCry+nzxI"
    b"7iO3kWvJBeQYqK8uWYBEyK/EJWItMZioDu76HX4An4DXxFH8MXxmN5jqb+hBdDhaBg2AJ5iJ1ENQ5LG+Vu+mF9RztfPafK215tLy"
    b"1KtQ92C1umqF2u8r+5WFMJfNlFKKHZCeK7+XH8pX5DPyYUjGu+QdcByQj8rngJufyZlyWKaVQoCQXsocUKZ7Sr7iUOurY9Xtaoaq"
    b"g/scre3TPmpOvS2wyANdB1TPRC4gAXAoQ6D695Crm2DTIVt/xmi8Ct4fXwK78ATPwXEihahANCI6EL2humHEcGIo0ZfoQjQnqkI/"
    b"jUQQf4dfwjfi40GNUwHDd7GN2CCsHCah/6Jr0V5oITQPvmc20gQxI+/0vfpYvYZO6e9AQ2ZqbbRCkC/fqGfUtep4tZNaQy2gGmDq"
    b"s5QPylPljnJduaRcUC7C4zWo6Bk8m6WEFFyNV0upDdRu6jh1ubpPval+UXk1UauuddNmwERf0b5oqlZQb6wP0ZfpR/Unulc3I+WQ"
    b"DqCZa5HTyDPEjVBwX/XQnuhEmPe96CXQsO9oCCUwJ1YYq4jVwVpgnbAe2ABsKPiLUdhoQOhwqKo31hVrjTXEqmHFoacGLIZmo6/Q"
    b"6+hhqHQa2g+YqzhqRH3IK+QishmZgfREaiLJiKJn6nf0ffpSfRRkzEp6gi5DFsjQLmp7tdXaLG2U1gt2ooFWRSutFdZStEQtTnPA"
    b"EQdnafBMaUgp9bRWWg9tqDZVW6Zt0Y5q17Tn8BkxzaQX0WuCyx2mz4Z5Pqrf1N/qebqmO5ESSG2kPTIQnP9iZAOyHzmD3ECeIG+R"
    b"TKg+iAiIjuAog5pRC2pHHXDY4cyIGlAC1REZiSA+JAf5hnxAXiAP4J3nkaPIHqhpBbIAmYKMQgYgXZBWSAOkClIaKYjEISbgaxFY"
    b"JFf/rn/U/9Mf6/f0a/ol/Yx+HJLtPn23vlP/CxC+Rd+ob4K1Ud8M51v0v/UdkA326wf1Y3DtBf2qflu/rz/VX+rv9W96lp6vh3Ue"
    b"6qEQIyQ2F1IAKQrethxSFXa2LtIQaYw0h/tohbQBV/B/R0ukBcxaA6Q+UgvurgJcXQRJgzu0IDSi6jHdp2dDP97Ad9zXr+hn4Xv3"
    b"wJ2t15fri2EPp+jj9RH6YL2/3hvcVVe90/9WBzg6613gmV56P5iqEfo4fRpcvURfCZXsggrP6tf1f/VX8Mm5elRHYT9cSHGkEtxH"
    b"G6QHMgyZiMyDvdsMinISuYzchRl8i3yHTgQQETpBQR8caBKahqajRdGSaCm0LKxysMrAeQnI6QXQFDQOOkSjKhJDvMhP6MxT5CZk"
    b"6H3IJmQpMhkZjHQCXikDCoIhAf0TVHcG6loEeOuq19dL6jaYuiyYmqvaAW2NNlsbrnUFlamkFdHiNUpT1BAk85/qZ/Ud4PEVrLfq"
    b"B/U7PBdQFdWgJcEU1tU6wawu0rZr/2ivtZBmh1nuqs+AHt7Wf+sGpCLSDZmLHEAeQ1XxaE20P7oIPQAskI3iWCGsLtYdmwisvx07"
    b"hd3AMrCP2E8sD/NjISyCBTEvlgvu4g32ELuMHcY2Y/MBdR0BZ8mYAvp7G92FzgG0VkGtaD7M427AVkeYPBz5ol8GHh2lNwUmlbUP"
    b"2gVtozZJ6whYitNi6lf1jnpEXQ+sP1TtqNZTywO/2FRCFcHJ5im/lG/KV+WT8gV+/lTc8JygkKpdTVcrqY3V7sAuS9Rd6hXYiajq"
    b"BAz20ubB3mVoHHBLW6j7sP5OJ5BqyAjkL+inilQAJt2CPkIltDTWF1uFXYWanHhd0JPV+Fn8LR7BbUQZyGk9idHELEgwa4iNoIob"
    b"iVXEEmIasGonogaRCrn9M34RXwUMXB6XYT/WYV3A8X8CpeyK2tCn0Ot6SFQ/BYhP+9/fg7UEf3RHnQ98iEAKWK10UworIfke+KTJ"
    b"cnu5guyUZSlXei89le6BC7gFafUx+J7fUgy0sZjcRB4q/ymflj/KuFJFGQqK+1whYKdmqRdhIipq47Uz4BAq6BPBB4b0ysAmZ6G7"
    b"ZdFRwHnfURew5J/YTehfOt4Rn4cfw9/gEihnE6hmCbGHuEq8InIIARQ0nixIliTLgn8oD36gKJlCWkAz/cQn4i44qhXESKIpUYDg"
    b"8Ef4X/gIvBIuYXfADTbDCOwuOg+thnqBwbojLHIDkFcAUs88rbz2DTxqIzWiHFH6KXHKC3ml3FI2yM+lzdIAqbyESB/Ec+IGcZrY"
    b"T2wj1herg0+oLtaD837w3EZwRl9Fg1RHmiSdlDxSBXm6fFe2K0PABzqg80/V0tpKzat10M/rCcgsyLX10T2ojvbHrmFx+Bj8NvSy"
    b"P3GUCBCVyAnkcXA7VvBBg6ml1D7qCvUMfPFPKpvKojKp19R96jS1hZpJdacqUhT1kTxCTiZrQ/X3iMWQbCT8AnxeOv4OW47Vxjzo"
    b"DrQtpLsTSB9gvOuA3jT9P22JVkPzqQfVvmqC+lpZp3RQbMob6PAguYwsSI+kv6XxUnMpXdLE7+J98bi4WVwiThVHgTPuLw4Qh4hj"
    b"xBnin+CZLoj/iQExTqorjZK2S/9JjNxMXiY/gbr7KicURemkHlNxbaB2W0sHNszV2wLvuyBd56LtIeG5oMPf8QbEToInOoAH4sjG"
    b"1CrqJWWlW9ML6TP0J1qlU5gqTFPIN12YTkxLpiZTmKGY35BzVtJd6ST6A7WeakKFyB1kQ/InMZ9IJE7jjfE32BAsCP6XQTcCUx/V"
    b"q+p3AcE/wI3T6m6llvJBnikXkB+Diy0t/RL3iIPEUmJMeCzsBa87SGgt1BLKCcWFYkIpcMGNhe7g+NcIZ4UPAiZWFoeJO8X3UHE3"
    b"6S/pu1RSngJdtoGruqgwaj+YcaM2GLTUqY8BvkxFpgKOC6Mz0edoIWwq9i+WgA/Fz+Mq3gKc3RsiAbzeZvI/kqbqUuMhsT2hQlQ8"
    b"XR0S3Biofz29iz5IH6EP0XvozZCJJtDd4DUHnUddp5ZTHSkn9ZpcTTYiw4CLFoQXOKEUfh8chR9dAKy2C3TqIvD0Y62z9lUdAVO9"
    b"ULEq++RqcoY0XCKlI2J7URSOCQOEFCGTP8hP4VvwRSDhBSC/f4x9iGXGPDE9lsLX50dC+n3FW4Uuwi7BJzQRd4uqOEh6IlUFtxiv"
    b"rFRQwHZEHa/lQ8b5f5n2HWS7/8u0LnwZ7vtfprWQw8krUGdHahPMr5FuQI+jt0IX39N+GmFMkGjiGDvDMCKdQ7+gz0Hto+lGtJP+"
    b"SZ2kplI1KZG8TE4CnH8nNhHNANUHgB0U4PUOGA8oag4OaTO4kx/gRMuDE5yrFdNewF0VhTS/UKmo/JS3yK0h492AjFdLksU74Oq7"
    b"ikVETsgQDgtLhRFCe+h5aaGgkCQkwn4Ug763gJ2ZL+wTngqCUAYmfp+YJZaF9z+V0iHLf5RrK3ug41PV32pX7ZFWF1BdCpTThW5A"
    b"DdhCjMNG4V/w1sQ/RDr5B+kmm1G7qTDVkF5BZ9Ds//6idQdzi/nMBBmNIQ2kQYOzL5B2d0DCa8SwzAt6Fd2EjlEHIAMFyfVkOfJf"
    b"og8RwBfgFnwnVhK7gNYH5u6G/AR3oYL6pmuX1LZqrrJUKaY8BZ4uKP8nLZXqS4p4G3DaVSwmKjC/V6CDy4UZwlhIdUPgGCvMhP/v"
    b"FC4KLyHLxkHmGQ6p/5GoiFUB/yclL7DYFPkaMHl7ZQfoWy11pZoJHL4M/HBlfYX+U68FTjAPaYT+hQbR5thO0N5m+DbcjdcENXpF"
    b"JEPGOUTmkMWogdQ24DCZKkF3oCfTG+gT9B36Ff2V/gXrG/2GfkCfpjfBK23pdNpP/UPNoWpTEeC1HiRGHiPaEPn4H3gB/ALw9zvQ"
    b"xCAyByGRdXqSvl8rp11Rm6lvlWGKKK+HVPdYGi3ZpOviaLGg+FnYDnm2rKDxH/jL/A5+OT+Hn8ZP5+fxq/i9/HX+K48LlYShsAOf"
    b"hTRA9jkRk3pAKjRChn8mV1C2KKoyXP1Pra0d0qzgzn4Df11EktH56E/Idnsgz3bGj+AC3pzYQHwkUsjekOYySJ0sD0l+PrWXukl9"
    b"oLyUShkAtQmwHDRL61SA+kr9Sx2nVlOjIeemAnvdgw73BQ3LJ04R44myhBvfh/eCTt/FpmBFsNeA59LoO/DJJZGX+kw9XX+kTQAn"
    b"f1sdCd7ihjJKSVAeyjOAuX8Cb3eT4qT3wFHDQJ1I8YtwSdgCqX6w0FFoKtQX6kKmbyP0ESYKq4STwhsBAUYbJR4W3WIFaTbMdkH4"
    b"nLdyNeVvBVFHgXNrAv6nKLhsA+y4HxkI2aQRdgZLwZfiHrwDcYYwkkP/h+vO0N8PlJ1uTk+jd9N3oadRmmAsgGkr8DUPXX5EHwZO"
    b"60YXhf5epKZRlah8SL4dSY04RnQmBHwn3gD/AcgpiN1C+4Je/Q1+/BPseap+B5ylWftHHaI61PvKDKW84obEOhx6HZKuSyukPlIl"
    b"iZVyYW5PiJvEBeJ44POeYhexExw94Xy8OB9U+6h4T/wholIxqS3w/iHpnWSQG8qz5EtyFOqdBdmQUbuoe1W/2kDbAL62lr5Oz9Hr"
    b"I1vBnbRE94EH6wKMhuI98BPA3+1Bs9yg1DPJ66RM1qAmUgept5ROFadb0sPoufQ6eid9ANh7L72N/hPmujswt5X+TZ2jZlP1KAXY"
    b"bAw4lkfEBMJJXMQ74z7sDywVO4c2Rd+D+xMhBaTop7VG2ntwDpS6X2mo/AJXVVHOlNZKTSVdvAV63E5ME8PCc+G0sFlYJEwRRgsj"
    b"hTHCVGGJsA3U6j8hIqSILcXZ4hkxTywhjZROSVGpvrxK/iyXUeYrr5US4PHeqeUAzZlaNX0NZKPakGZ/IVXRZehbtDA2DpyzijWG"
    b"Xj/AUaIuMRU69YVgyerkAHIZeZR8TGaTGhlHlaBqgAa3hRnoRnUFhm8JFVag0igGmOsteYncSI4lm5CJZC5xiVgAKZ8lnuEr8ea4"
    b"Dp8/Gqp+Dk68BPoanH5R5Jk+GVB9C3Ipq51Te6qoekLpruDKeXCVScBpK6UWkkF6If4FTFVTtIle4QVM+D5hk7BS+BOOTXB+CWoP"
    b"AJs1ECeKh6Dn6dIw6bQkS+3k/bIs91AuK4nqHEgmLbWzmgsSl0/vgdxBSqHr0RjaC7sOqjUNf4EXBQd9nzCTnclNoNAUVYsaTq2j"
    b"zoM7cQOPGWg7HQ/6ZKIROkB9pm6DS5sPfqwM9PYJvKM3WYD8QewGzo4nnsMO1oIO7wFviwFzD4Xc9S8yDfL0R30VKHQE0vcAwPNL"
    b"dZXaEhzKI2UF8G28kikfAzS2kF1yABzZfmkBuNAmUinJAa7ML/4UP4qvwX39J74Rv4g5IifSUppUA/A/HZzYfSkgFZA7wczclTW5"
    b"vrJIeazYwZ+cgOzVHjKHqHWCHE1A6r6GJKCT0RdoSWwJ9hWrAp35hleAPj0j4qCKXeQXMp5qQ82jjlGvqCggvDRdF9xZJ/AoHehm"
    b"dDXga5LOhvo3UUOo8sDZF8mJ4Mu/QhapTfyGTyuPv4SUZsVOoi3R38BhycglyL4B0KzyUPE0NVV9qExRioAnWwsabQB3slkaCIim"
    b"pZ+g0wfF1TDBY0F/B8AaClieK66FZ2+B19bEIoDlmdJR6bNkkZvLC+UbsgS6PEe5pWCwk2vV92oB4I4zmqA1AkS9AT82FNJyBKkF"
    b"DH4PpbAW4JAfYSTeCJ8DnjkfLwCJaRGw2heCAK/RHnz4GpjzO+R7UPAYiVIGykxZKCNFUBLpJT+TD8gTcMVYsgVkkTBxDzxdD8hb"
    b"mcBlPXE7/gibjZXBPqN/oJXQz8hi8GP/QcZP1m9rwzSjdl7treLqGfDJJuUWqGxZ2S0dAe2qJKliBriNOWIvyBbFxXiREVEREQnR"
    b"AnivLLYF771OvCrmislSJ2mN9Fyyy73kg3JYbqJsVbxKU3W3KqrdtPOgWGP1J3px+OZMpAa6DlJzbciQX7CS+CT8Ci7jdYgZUGsW"
    b"9LkROQrqOAWT+4OMkjjUGE8lUYmUAypWoNKPsAeHyeXkCMBxKhkhHhF/ESOIqgRCPMHX493xZDwTpnsglo59h1zdG01E3yLrkbYI"
    b"gzzQF+n1dEm7ok3XqmlR9ZI6Q62lqsp98I2dlTQlT/5HXi73hlRJg3r9f3ydB3wU1fv1Z2Y3EErovfeOSJMmSBUBBUUBAQtFVETh"
    b"J0VAQEFR7A0VlS4gCCiCijQFBZQiTUF6770EkrC7M/N+73PvlqD/93M/u0k2u7Nz7jnPec4zgeSX0LTQuNBTofuZJ2qESocK0clz"
    b"h/KGCofKhm4PtQw9HBoc+iC0JLQn5OCFfcKTwtvDOSP3Rj6I7IqUcp9hsk72esB3kv+I/4OfYj1JXRezh9ib7fLOSGerUxbkawI5"
    b"g12Ck4MHgyVI3+8mrU66mFSISasHPemtLJOzfJVlAZlzLmn8Pby6V5aWWUpnSU/anPRFUj+mzcvs2LPBisED4G4ZuObMcO5zMuxZ"
    b"9n12mjXDam/d8GcwyYeo6O5wvAa0td2LkYWRgczC4fAf4U/D/cN3UdFpod2hVaHZoBkbGgLr/UJ9Q08wQz0fGh16OzQVjBtDJ0J2"
    b"uEy4JZ3u3fDS8NFwrkhTjjMTrDncljjYD+5lt7r3NNnkuFfO7+N/6R/zy1t9rdnWSaui3c+eY5/AxXuRyvY4+QP3Bl4NLCeNlw52"
    b"Co5mztzBzFU86U5qfGjS23TiRUmrktYnbQLphqRf6U9zmUzGJPWB8TJJGcEteNkAGA8FfmZmawTyr51HqerV9kC7mP279T/qei16"
    b"K4S6n/EKer+6g9zSpO/XIndG0sLfo+8GYZ988QW5sm2oAvPHhZu76dirbi5lbl5Ob96Go2UwV9ULdUcD34YOhfLhB6+FfyN9tom8"
    b"Tb8q7j7pLnY9915vsnfWa0jW3+WXswZZK60ku6P9ib3PLuU87kxD4QUD9wXGUdHHA7mDDZiqxwVnBH8O7g5eDFpJeZJKJlUmT9dO"
    b"qpNUiyovn1QkKXtSKHg6+FdwBZPUq8Engi2DpYM3AzsC8wKjA52YpC87q3CKB+lVJ+wF9v/senYGvjnaamp5/i/+S3i45/3iveQ1"
    b"83z3V/dVt62bk6n680ifSE1S6Qbm6ufCrcIlmKx3h5aHpofeCA2D8R6hzqH7Qh2574nmR1DLX+HbJ0PZw/WYwz9CLRa792JkFRNW"
    b"O3eie5hePcbb6pX1h/ob/JLW89bvzBvP2WvsPOD+xrlJr34j8Cf6bgeK5cEL5O82Sc8wI35NwvyHHH41KT3pJlP2paRjSTvgexaz"
    b"ST8m58JJ54Mrg28GHwwWDx5htnoiUJ4sNsXp6uRxNtrj7EYk7nlWL6uo9Zf/jt/WDzBPjyWdBLw/3Hfdrm4ZNL4q8i5TcMNI3shF"
    b"svPC8PvhF8K9wveGm+BsZcOFw3nDKeGc4VzhfKi/PNXbLHw/Pf3F8MTwovCf4Quou26ke+SVyDeRfSSxRu6zZLF/3FxeW+8V9jZM"
    b"HhvhL/NvklFGW79Ylt3SHm//bmfFw19nrrYDTQPDA4sCJwNFmRZGBr8KbgveCBZJapD0IElrLPl6Kg62gDU3aRqJZByPdk6qn5Q/"
    b"6QJd/pNg3+BtTJUrAi+i7evsZV+niLPZHm3XtA9Yb5FET/oT/Rb+FW+G9wCol7kD3UruUSbAxyPl8LDv6T2dw5XDFvlsNdnyPap4"
    b"EFN2bzrZE6Fn4faN0JTQD6FtoUu49R3hx8NvhZeFz4ZLRh5E2esifuROptVlbobb0BvprfAiXlNUtdr3yZ9j0HeGVZc6+8o+ZBdw"
    b"7nFGOQvlZyq1Az0CYwOzA78HTgWCKLYhld2XlDaeaWRycBZpbUFwYXA+ezEdhG8FRwWfoT+1CFYN5gpeDfwV+C7wTqBf4E461Qnn"
    b"R2e8cz/6PmkvxC8b2CHrZ+slqxn6/tkf5Tfy070fvaFeHe+a+z0zbwM3HPmVlPJgpDRs/4JW+6PvMmE7fIp+tDz0NWg/xts+4H4K"
    b"Xy0PbQ2dCSWFK4U7hIeGZ+DawUhjuv53kcuR2zneCtf22nsfe0e86rC8zs9rPWp9bV23mtE7t9r5nW7OZ85uPOw+ktQypsuCwbuC"
    b"TwbfwMXW0qsvBT1SaX5UXCSpYFLupCT86nTwbxQ9U6q5BT35RmBzYDru3xK0h8jxLzjNnWxMVl/Yve0qqPsn0N4tP0+a5j/t12Gm"
    b"3uh9SgqtC9u73HnuaLezW41+fTCyPPJZZARKbUpmyRG5Hj4S3soOLGYimUo/mhj+kN34JDw5PAtdr0LZh5kvckYqR1ozoU6gE/zN"
    b"TFnV7ea+4a7Evyt5j3mfeX97efyOJPCtfm7rfibqv62Cdjdm6r12EbB/4uxwcgRaoc1vA4cDuchVfanVhcE/mUCspALMjbWTGiU1"
    b"ZTXis4o8YiWd4bsLeVbv4B3B5OA/gS8DA9DLDRL3C04954o9nxRa0vwusIj/oz/Qr+wf86Z5Pb1i3n4SRF+3unsj8lvko8gTMJU/"
    b"chmUi8E3Did7DK23C7eG8dZ8vD/cE/ZfJL3NZh/2hTPCRXjF45HXI99G9kSC7u3uY3jEL2At6z3ovY66L9GtupJ8V/upfmWrB+ew"
    b"2rpqlbcftF+1F9uH7ZxOA6cPSeV7Z6/jOeUCrfGjV2FvReBvMpofyBcsH6wdbBpsG+zI5NiF1Tl4b7AN+1ID/0oOXgvsC6xmgh4b"
    b"eDTQgCn6OKgnOF2css4F+wdmjeZ2kI71hnUP+eQP/3W/NX72Gy7TEq7Xu2+6Hd0C8DwvMoy+UzhyIbwOxb6El7UhpZTAw+xwKJTG"
    b"CoeC4Tyovj4u9zRJez66vhmuFOkCz6siqZGazOdz3BNuBfLeXDpWTf9/pJJ0HGwMDuZZTTmXn+yrdjV69Cfk0DSw3hsYEvgMpHsC"
    b"1/HxcnTcVlR19+DjwT6sXswTncHdOFgtWDgYCF5gR34KfEF67RFoGCgQuMRRZsBwB6boVNzxc/sZu4mdEw9biGt2sIpb5/wVJOGe"
    b"fnU/QieZ7g322sD4ZXe9O4U6vM+t4gbdY9T2zMj4SH+mkDsiZSIpJJcL6HhXeAu9bD1rA5/9QyK5TIfKH6kWaQXfL0Vm4GTnIwXd"
    b"FvT+Ge7fblb64QvMWOe9Kv6T/mz/OOmkj/UlE2Y5qm66fdAuSk9911lH56oZeAw3WhY4GsiKP7UL9gu+FJwYnBP8nr69Lvg769fg"
    b"MvxsClX/PC7WKFgkeD2whV71QuCeQGE4/tYZ7jRzgvSrd+377fxoe5LVHcSHyUVP+jX8a95yOL7PK+qddn+C5cfc+m6Keybye2Qu"
    b"TjYo0i3SIlILP8sXyRrx4TGNlRGOkD5yRApFKtCd2kQeJn+9jusvj/wTuR7JzxG6kcNmuH+4l9yCoO3vTfRWg7ew38Yf4s/0t+Pg"
    b"Na1HrLfx8LNWYbsN3jrT3mLftCs4HZ0RcPWHc8HJE6gTeDAwOPB+YD6T9r7AZabtvMFS7ENtqrchq36wFpmzKJNzOplmEz7wQWBQ"
    b"oEOgYiDsbHdmOs87dznZnZ32FLsPk/Q56xtroFXLuuIv9p/Hy655P3jDvcZkk/XSrcu5VyJrqOynQVwiEgrvD68Jzwt/HH41PCz8"
    b"LGmzb7hf+Jnw4PAYcucMkuc22M9BkukcGRmZFdkW8SK3ub3IIxtd373DG4i2j3jF/If890glttWIXDLPOmTlt9vaL+Iz++jRdZxH"
    b"nNdw3a3OFSd3oEagbaAXvL3FnLQAzteSWf4K7ArsZu0MbAtsoHp/CMwNfE6aGcYz27M/RQOec9RZ68xyXqFa7nQKO1ftTezlcJJ3"
    b"ObL3RmsKmO+y8lhHQD2OCbMsuH+Djye8Bl4276C7xJ3A/Fvfze2eg/M5JNOnI/dF6jGDZIukh8+ED4T/Irf8wdoI4j3hE0xUwUix"
    b"SB2e9SzZ5rvI7ojl1mBqe9v92b3mVvF6eV94u7y8OPfbzFnJ9I/x1m8kk6b2SHzmol3R6em87/zmXHNKg0HV9UrYTSOTVoTTtlRy"
    b"Tyq6N7Xdg8/vJqlWCOaG4YPgn0ZNdw3UCmQJ7EfZY+nNpZ2L9gr6YWe7lH3W+oFJuoNVyDruL/LH+B384v4F72fvA5ymiZffO+/+"
    b"7n7pjnN7u63cyqj8euRQZFPkJ5T+OUheIVMOQfHPsgZGno+8QO2+HvkwMo3utAp+j0XSIynkm+buI6SSz8gl+1wX927rPUeP/tk7"
    b"7eUj8T7jT/LX4+Dl6FgvW4tgPMW+0x5A1/rdTrVLO+2cIc5k0J+md90W6Bh4FjZnMoFsCRxB4ZFAlmAKKs8fzBPMgZNl4Ox7Uf83"
    b"gYlw3iVQF98+Rep+3+nt3O649kZ7ov2IXcE+by22XrDutCxrPT7WyS/o7/dmec96d3iOt52+NQjERd2rkc2Rr6nqZ9FsE3pvQWo6"
    b"Er4RvhK+xO0GVZ01UoCabgC3/SJjI1MiKyMHYLei28Ed4k6lnlPd0njFKO9rb6+X7DfwnwLt7/51HOwBksIC6x/LtqvTsUahwd/t"
    b"s/Ssms69Tn+y6AxnOTV5ygk5OQMl0Xoj+td9IOoZeDzQO9CH22OB7oHOKOIuUFYMFAoEA1edA87vpM6JeEIP1F3cCdm77SU4WT/U"
    b"lB++f7E+sp6wGljZrH3+An80M2ZJ/5K3xvsIfd/hZfcOM1m/4z7h3uUWc9PpuysiU+F5AK7WGo1XjpTCw/JG8nArxOdV8PW2kR5w"
    b"/1bkq8j6yKlIdubU7u545qvDbm6S/RAm2INefpT1ir/cv+pXIf1PsrZYAbshPWUqqcy1qzMfvOx85Wx2LklV30OtDgu8ST+aG1hC"
    b"D1sd+C3wa+AXOP8uMAf1v0HN98G16lLNEeews5pZbbTzsFPXyeWcsn+xJzHLtGaavMxcM5mJ8m6rhHWVypruD4fpyr4N10tBPAhm"
    b"anop3kV3O2n0M3es+5R7v9sExRage12PnI7sj2yPbJB/7bMsspS1nM9+owJ2Rg5HLkYikVxMLPXpdv147VTSp9J3aTrhAI6+0jtJ"
    b"GmuKvj/Hz9L8SlY3awL58Az+3dZ+wZ5t/2X7dlXnIc59trMJ/86FvtuTpF9Cu3Ppx+sD23GyA4FDVPJenO0P6n5BYFLglUB/lHB7"
    b"IE/gorMBnQxHMaXJYmvs9+1H7Wr2DetXOkVXq5x1wf/JfxXMJfxzdK03SWW1vCC57Hv3PXeA255slhucB8G4FCebRE2Pp4ZHUdej"
    b"UfOEyPuRL6j1pZE/mKWuRLK4pdyG7kPu8+777iL27KqbH0/syQQ3x9vsXfOK+HfRId8lm+z3Hauq1ckaZn1hrbFOWNnsGkzW/7M/"
    b"JJftsC/bKU41pzWz5nDq8itnhbPFOYKjeyi9SKBcoBrY6pNDGpK66uNdVQOlySTJgQw8YKfzizOXVw0hzzbEvdPYxQX2a+Cua2ez"
    b"91vfWq9Yna3y1nV/rf+x/4Rf1w/6Ozm/EcwFJb3r7ga67Ci3i1vXzedew4lXRWZHPoiMocJ7R7qSU9qj5/aRTpGHIr0iz7ELH7Av"
    b"q6gD1aXvcB92X3K/cre6Ibey15kUsMQ7irZb+cP8ef4ePzt+MoD+8SdzVmVqerQ9F31fI500phpHOh87i+DrAEgDcFcKXLeDsQmT"
    b"U1Oqux5IKwaKB3IHfOcq+7HZWeZ86bzpDAbpnWROxzlh/2HPwbmfZGYtZ/vWfmuF9SldspNVzcpinfB/8af4I+mfdf28/kVS2Tfe"
    b"O3TVjt7tXgEv3T3grmX++BD0TzCD3OXWdEu7edF5OHI1cjZyMnI0cgTHPs7n+l+b5EPbddw29KkhdKq5dIITbhaviteBmv6CjniR"
    b"dNKKXDDV/9OP+FXJSG9aS62TVgG7hT2IeWi9fcUuTJJ6Ai+bB+6TzNZFwdiGftQ38D+mkLFMYeNR80vU87PU/AM4WfVAfrLIYfx+"
    b"ljPOedRp5ORzztu/UtPPctwC9mkwv2M9btW2gtYeHOxl8FajovfCxbvkpru9il4W74z7J336C3xoEL2ng9uU6aGiW8It6Oahi+Vw"
    b"c7q5wFeEHaiCEu5y7+VZz7pj2J3ZVPF297RrkWbreZ2o5De8r7x13nEv4JfzW6Ko8f4c6vmsn8OqaXW0Blsf00N3w3gRu7Hdg479"
    b"ub3U3gXrOZ0qTkunO5lqAv1rkbOG6euIc550btONc8KzWjn53GKeOosuFONzyLHD6PdNnTKObx+gU3+Cm7W1S9jXrA1U00CrpZXP"
    b"OuUv89/wH/Fv8y1/F73lJa8rTpbFO0aimMKM+YjbEmS53UjkDBrfHFlNDS+JfENfXsTHFeTrrXTyyxGbPbjNbYsiXqbnrXGPuEGv"
    b"Gq44zJvirWW+KkRFD/An+iv9U34uukYv63UqbKeVbpW077Ift1+xZ9g/2/vt63Yup7LTxHnA6ecMJaFNxJHnO0voYGvIWutJp+v5"
    b"uIavf3AW4FiTnLecUc5zpLl2VHF5fPumfcTeYC+iO4+klu+yy9sB+7i13ppNPfchj5W0wv5ufynnMtC/D8az+Cc5w5nUYG/mrQpe"
    b"kneWuvzenQznz6HZu916+HhhmA6g8DTq9yqTVHokzCSZi95WzW0E633JJR/hZZvdc25O7zbmyhHMrhu8K+TQu/3BzPCbmbMq4iiq"
    b"V++2HLum3dV+mbr+k3mrgFOfaXCI8x76Xo0znXbSnaRAPmq4bKBSoEqgMvVcGkfLFXACqc4xuvlKnP4d8a7GTgknws4tR9lD7E64"
    b"dtA+bC23JlrPWm2tsoJ2CV76jN/Wr+Qn+Se83+mkb3v/87p4d4I3xcugHne4v6LzWe4kKnSc+6I7GOz93SdlPYXDD2IWG+2+hl9/"
    b"gW/94K5jmjrpZoC1LM7d0XvKe9n7nF64g2rO6Vf12/n9/Tf9+VT0BT83NfYgGekzKu6Q5Vtl7VZMBa/as+gzh+2IXcip7bQnVY0A"
    b"0TRnMTuwhTn7qHMOf7vm3HBSncuo/QSPbcWzv3WmUgfPUw9NnXJMV8fttWhntN3Nvt1Oto/SF9+z+pH5c1snmSw/8Pv5TfwC/nkq"
    b"b4Y3Esz1SaPX3d3uSvLoWzhSb7cTdVsHjkui4fw4WT7uVUVX4tFmcPso6F+hq39LCjvqht3CHKOz97z3obfY+8tL9QqQxrr7L+Jf"
    b"v/hH6FflrdacwXhrFtn7sOVaRe168NLfHktFL+Js99rnQZ3LKenUgL3WTiew9HKedgaCahizslpDnEHOAKcvun4IZTdjh8o5BZwA"
    b"vfkwU8b39jQ61bP2Q2SfkrYF6nXWHOtV3rWVVcayrUPU2Rf0EuXguUhlW7z5OPiz1GNt0KeTqNaB5gv3VXju4z6Axhvja9VxtnJu"
    b"eVZltxZppIXb0e3pDiSRfOx+w6R2yI24RbyGXg/vRbS9jtSd278D73jd/8bfxVxZERcbYU2l1s5bue36MDLCnowu/7FvSFXf5XR2"
    b"nqJ7ve58yoT4NVW9lDpexW0Z1bwQx5pMBbxCn+rNdNGEV+RzMuyjVPMC+yPmqodJnqXoVsfZ19n4Rz/0XcXKap1HZd/4HzLfdoHr"
    b"Un6AjLLNWwbfE+gwjzIl3OGV8/J6Ae8qSt/jbnJ/Y4L41p2P3qeyvmBNYc2kqy0gtf4Cz/+4x9wrboDdquQ1xb2fIptMYmrd5p31"
    b"slNHrf2nwT2Xqj6Hn9WlrkeQEFdZR6ns8vY9pOTXqO1fRd/5nVpOW/r2YLB9SDf6FrxrcbIt+PgWNL3J+ZVdWMSefMozBtGrWqGM"
    b"/M51JtWVTC8vspN17Lxk7rXWDOroAauG5cDxMv99/zmquixd6yApcZo3hgnwbjprXi/M+W8HyUJSykfu63A4HK6fpzcN5H4wbjWW"
    b"6fNjdzqIV7Ej+0Fre4VxrpbksKH4w1yy/D4vg8mqJtn+KdLfl/4qfx8uls+63brXehKFT7OW4eEXrCS7NHzfB+oRJMdZ9o9MR/vt"
    b"c3bYzuYUciowiTSkg92D0h8iofegK3VndeHr9k4LvleLVFLAyQLiY/Y2FDOHOWOI3VPcO6t9hll6vvWG9TR8l0fdh0XdL/gP+rVR"
    b"9wXUvQB1D/Lup88W9Tx67nZ67zz3E/xqJN7VGxd/kDzekXz9gNsVTfejokfhdJPR9Vq84IqbDYU0Rysv0q9WeQc83ysLx/2Zo79D"
    b"2+l+CTpHb+s16ysmgTPgLU9yegRNfmjPw8V22WfAmtMpRqeuS7W2JUd3Bmk3UD4M5s583YbH6zlVnVJOHhJYKkh32KtR9mc44UC7"
    b"O8erTioJo+5N1ndMNi8xXbVnpwtZEf8YOeFbOtaLfm//Hr+WX9j3qb7t3gry6Pvy75wfZEK63SsD8w7udpZa3UkvWocClrlL0fQP"
    b"3C/D835zN7p/uQd5Rpqb5BVEK3eyb8q9P/O+ZyfPedlQ992k79dJopv888a9h1ufWytxb88qDSuP2mPIZT/Y25kzLaeIUx1s9zuP"
    b"Oc9S3WNJmu+h84/p3R+QQV5jKhlKN+8G//Xp0CmwfMheZ39tf2A/T7ZtYBe00+iI6n8TDGVyr41zX/K3UdHvkQnv9+v5Rf2wd4xe"
    b"+g0d5hVc7BGp6CpwnUJNp8HeWdR+hFy6j9t+sJ+gN110b+DVWdmR4l5VHLsV3t8HP5jgfYobrmb3TnsR5qoqfjOU9BxT5WT/RxCf"
    b"kP9ZUAutPWaNtD6w5uI2u63LVjLJqa7dHuxD7Qmw9o29it59CJVn2FnIHUVx6CrO7XBcn6zZgPt66L4Kyi7o5HQs5zKMb+c180km"
    b"o0ne7elXhewM64D1M0n/Zd7tTquUFSL9L/c/Rd1dQV7IT/N2o8dp3jgSaSc6bTkvh3fTPYNmN1G3i/GwL3GwyXSnz/k4nXT9HTyv"
    b"h+Mj7jXXgeHq6Lob3f4Nb5b3i7fXS2fOqOV3JI29CcPr/OO+TSZqYj1MAv2AOlsHyzesFLsCvaUjfXoITvYJNb2EeXijvZMkeYL+"
    b"dQVPz7Bv4m5hPqaTUi+ihaM41g77d5LcEqbSz+w37VF0qZ5gbWRXtPPTqc5Z/zBTzrc+Qd9PwnYDq7SVDN+76Z2zSSlD/Z7UXXU/"
    b"v+96J5g81L/kf88bhUK7eq29urhxYS+757up5KwTsL3H3QXWv+Vf8h9ABWfd667nZkcbVbzG9Lte3guk+dkg30OnzuPX8NuThN4A"
    b"+Qb/tJ/MbNnOeoZ5Yx6Z+KQVsMvad+K2g+237Jn2Mvg9Qjqznbz0alXZjehhrZ27qe+78bNm4lyVqPoUx3au4vVbSdlz0PUI9q29"
    b"XcsubLvWMesPEt8HTLAPW03xryzWOX8HSpuCo/b3O/uNmQZy+TeZC3Zwlgu9qXjZGPjqA2sdUW0TXK0GCq5AdZdh8iwpHyvwSA32"
    b"ozF138F7yHuM+eIFb7w3ka63mJlqh3cSprP7pf06dIjH2de38O9lvPM5+C5Ox2rP/o+Bh+9AfsS6aeWyK9FfH7CfRp3v2l+SMdbi"
    b"a0ftS3AcdHIzIRdH4RVZVbiVdUrzSC4nqxOC+aO49mp7IQl0PDPGgxynHL590dpqLeYdhlndyGNFSKL7SWRT/Zc4n1Z+RT+bf5n8"
    b"tML70nuTjvM4OBqDqpiXy7O8G+4lavgoTrVPluL2FI+lM0+lwG4laqEtOzSAieVD8uwqjnTOs/xi4G3n9/VHM7N/6//uH/Jv+nlI"
    b"CS04h4Fkhsmc0Xprj3XRsux8aLye3ZoU1Zs5czRV/ZE9Ff6+oX+tpHevJ3lstrfA6lbuNzEzr6UGltmL8a6ZYH2HRDeUSn7Yboe+"
    b"q1DNAfsq9bzB+p73eY3362o1sypZOa1U+uYa0oLWdwv5nyoZ3hFvI7PmNEHfGxe+CwcvS+JIpocp/Kfd41TxYW4K+wXqOYxn5/VK"
    b"M6E14/l9mTHeQ9s/e7uYsLKzoy3Y2dH+5/C800+lT99m3WcNAPVsa421j6rOZVe2m9td7GeYPD6kpr+nd22Xir5sp9khlB4gUSfR"
    b"n3xYvw73p/nuX1T0MjrVZPtt6rk/9dEGbReHYYX2d2sR0+SrTBtd6ZFVmCnD/kn8W/3VpvfpWE+i8buou6J+sp/uncLP/iCbLaDP"
    b"fui9Tu/6H7X9KEze77Uju7QAWTM034TU1Yyv2vDoA3z3UfxvCHXxNilsDnPGOu8fkliIBFrRb0SXeApVTfIX+X/QK0N+AfpmO/rn"
    b"y8wcS6w/rRP0rUJMXG3wov+h0Um48EoY3Wefor6VvnOSNQvh4UXpZoX4PCe7EOZ7J0mvG0A/B22MsZ+yO8N0GeaMi9ZfZJ8vcLE+"
    b"pP0qVg7rov8XVf0Z59GHiqvlF8TBVI9ehTo/pjKHwFc3rz0sNyBlVcLJS6L1oqziXil4rwyr6v/A3Q1ehXa49xqvm+39yLy2G6wu"
    b"7qX+H9y9Us1vMlF+D9oD/jU/C/Vci+T/MFy/xNw3hxlok7WfXOZZOZkPanLO9zBt9iZnjGDSfhc/VzqfzzTyg70Uz1opt+Xofgnq"
    b"/4p5apL9Hvs03B5gP8bs0hy+S9o57HTSyVZwz7Teplv0sFqCPLd1g7r+DUd9T9Tdkukvr/zvvy3wPMv7gAodQM++T/73XxWwFvby"
    b"0MWSmbSTvKx8TEHzRb3y4G8I+ofYp2Eo43NvET62hwk6Cy7WEI4H+ONxj+Xs8wU/K3NOI3LJAFLoFDjeyKR1zcpqFyVF3Wl3sHvg"
    b"Y0Opz7fptlNws7ngWkTlfg/CJXy2kNz2Jd/5hCoej6oHkV2787q77Np4V0Fm6Ov0g79J3Eus6UyUY6z+7G8b0kkZK4Uufcb/2/+V"
    b"bDiVhDgSjXeha9WBn3y+46fSuXZR2yu9b8E/if4zHp0PIbn0ox894j2MDrqwuvJZTx7px3eGeKPB/CFusICet4E+fU4Yr4C61f98"
    b"HO1/5C/w17LTN/wUPKW51R0G3mHGXMlZnrVs3KcaZ9/Z7mu/QMf+mOr+Bt2uReU77N3MnAfJKgdI5Xuo5y1420p2Yw49+m3miwFg"
    b"vxsvLCMcH2E3lYONp6YfIpVUwMFu+Adx00V4y6v+QKbdu0Fbmr7lMu8fYir6jZqc780E7XskjXF07BG42vOsQdyGsIaDcCzp6116"
    b"1FRq+FtwruWV+6mSG17Az+2XoWqagvYx3mEsk/uX/g/+epLBOT/MjFWWnnU3HDwDF+8xB30PNzvh6AZpvCB5vDbo7wXHE3A5wh5H"
    b"B/8QFU/FqWejaLXmwPh0ZvCJcP6qPZLn9cEL7yGBVjbefZBe/T16es0aJN5dGa4V8t/8+ez/SCq7PRN1ST+rf8077G0GwTwQvwHa"
    b"51BtdxLaPcxPyr8aoeVGfLyL1NKBdN4Tlp8X//rc+5qet9k7iLIDfhGcsYXfTfLn53SsdTB8hYouidLutnrSQ161PiWdrLA247UX"
    b"rRA5tDAKvc1ubLdi4urCFNIXT36OzDIU5kfIGm4P4+tB+PyTdi/2pDNppCUucBsdr5idYtuo+5S1F5dYZX3DxP4uezrAeoRM0BDM"
    b"BZixroB6E7U2h6ljLGf3qN+BGqxCIs1C5zpNXW7G2b7DnyYxgbzGDrzgDfSeBmVvOvnjOFhv7wm+es4bjBJeBfenPHcRCWcbernq"
    b"Bf0CfjX6woOksbHk3UUwfYg5S2n7LquL6dXf00sPWqkwrOq6Cfz2pK5fgN237U+p3ll04gVS14tMTc+G8U/wrlfYhYH24yBvzexc"
    b"kcnKFn43WsupmffB+yTu0Zz8V4hZ+gK7/gd++iUdawxoe4K2KcyUop4D4L3gHQXxFrrOL+j8O2p0DqllujeZ9TnrCz5ORf2z0MO3"
    b"zFErvF+p4R1U8XHvsnfTSyLPluJ4TZjeHqZXDSeBfuZ/zTy9xT/sX/UDnEU1Kq0T3WSoNYFZa4H1i7WNSrxGZeelLmuRqdrj4X3I"
    b"08Psl6jwd+hInzKFTZE1Ga1/DO438DyFvC/PbceOVadPZ2fKOGntgOt51kfWaMndDamn7OSSAyjuGzrnWNy1K0pUfTqLfx0H2+mt"
    b"935Cq1Op1zepaOVgg3Dyp2X1x7MG8chIavoNfOsLdmQxSWQT+3Sa5JmVGbUK3tXef4RqHoeKviKVbEJVV3wHhVUk+bfDw56xRllv"
    b"gXee9SOTx18wdN5KI5vlgLGS1GVNXOlOuwXu1AG1P0C2fAhkXbl/kK868mhbvnunfQfarmyXwglywnSadY4pZgcO8SMT+yTrDebX"
    b"p6joNnhIWTqWi6fsRnFL/Olkshf9p8HemsouR+fS/v0P/q30/RU5ZSKJ/DUm5FF42DBcbSj3I/hqLI79Lrqezi4txQGVsi95Hq5d"
    b"lmPdg4oG+a9JVa/394I7K326NnNlT+t5vPUzayEc72A+uGo5cFzKroETtUTjXei5T1DTA5mPh8D2UO6HUM0DyB+96GwPwmwLnlud"
    b"aaUAKSxMpz/IkdaQbWdZH+IYQ6xeVme68+1WOUv9PdBr/hGS/1rwzoHr10H8HC77EC7e2L+dHlMU3Fl8z0vDzU+TS/fSv7ZR4RtR"
    b"/FqQrfbWoOg1fLWe9LYVZf8D1mPeeZw7DNd5yd1VmFfvoks/QkWPJp984S8k7W/hna/4QfRdGX3fZz3OuSlH+5oUoRztnBW2suNo"
    b"lfBvpfDO+Fk/fOt58bIxsl6iQw1nF54T/F3QQUu7Pt2uGMr2wL4PH1tKxv0ILfXHO5pZNXg/i6lyD5gXM2m96Y/wn8BrWoG2HM6T"
    b"xLx1Hpy7vT/B9zMZ6zsmr3mwPZsans2aS43rSl4N4m088ygd+Ybn+Dnx7Ip+bb85naoHE9wIOP7En8XermWPFVoXFytBPTey7uFs"
    b"+sL2S3TqzzjDxcz6G+hah6wzsB5i3szBFFKM+q4Em7XQegNcugl6bspqgsc35LHb+V5FnlPEziP/Nz6Vfn/Q2k69LLXmUjtvWiPB"
    b"3Y1+UR++81qefx69/UH3/FL+buoAzvMece/CzFxhOD5KdW8A2Y+g/orM8TkqnkgVf8D6yPsET5/KPswH/yoY30GvOutlkMMKgrw+"
    b"6bY7xxzDsWf5S/2NUtMBq7BxsF7kkvHWx6D9gUl/O1jPWekoPAc9tiQ4asB0AxA2Q8Mtza0ZXzcSpNXo5CWp4hQSWIg9Ok2O3cGM"
    b"sZw+NZOjTrBeJJU8jrrbyF+JLUaH9nHQ4/4/TPQr8LIZeM3r9OqBdOuu+Hhzzrg6rBcmYWRF4+n03XNMx4dJHnvYhx1k9G2s7ay/"
    b"0P1e0B7zzuDb6Z7vJdMBSviV0XZz/z60rfhW3j2P3riRrnHR9/y87LrKJt1gYRTJeAqVvQp174PlNDjODcMV8Kc7wNkGjXeigrsw"
    b"RT3MrSufd8LFWsN3A9yuAn6dmyySDscHyNo/M11Npz+/BOqeVgc0VYmdTrKug3gHuWSJP5NkMp7k/TQs34uDK7Rl6dO5QOvTe1Lh"
    b"W+E9DuuHzTrGVyd59AKdOJ0Kdvzs7E4RElhlcl0T6qQTHPf1/8c+juf4U8C7lAl2K4hPkUBtSym8CnprZXXkvPpT1eM4y0mwvois"
    b"8ju9ax9T13nSmcsO5MTfCtkl0HB55uQqsFzDrsp9VfCWx/mKiG+r38qRilqOkmg3gFwx/pH1Ch2xL3y3luydB+8+zzT9h/8THeVj"
    b"am8IPD+Ee9/B3FHUT6FfKxc75u2D283MTqq+V1LHP5HWVvCZcrENcL3LO4DXXZLunBuOq7JzrZlVe/nP+y8zy0zHt39hjj3kX4Lj"
    b"FKsUrtIEBh6mfw4F7XtMf3OYDlZSh9usPfKbLi5Z16lq3wpSp9nQcG6W+q0jefiYE7dKBqNlR1DFNXzrhPzukW1kzl/oUwutL/GI"
    b"93DHEXDdi+Tdjnq63SqPl2WzIpzFUab6P9DdQjT+EchH+M9ytg9S201hrTK5NL+fg/4VgvMLTNpHQbgHp96Jrndw+xvMe3jsCN+7"
    b"6F1nvkhCJcWo6dv9ZlRKdzT0ArXzKTv7E9W0h52OgLw0Z9GCtNQX3OOZL2eDeg3a3E91psJvVhAWgdvK+FRtqvgOalmthrh0XVyt"
    b"KlVfGv5z21nAnso+HaDTr6MDLKRWPoDhwVY/qqet1RgPKW7lMhW9k3NYCdqZ+OsE/GYw5/c4XHdAn43psDU48zKcfwH6TwrOluwH"
    b"YT/g2+yBw8csVEA2EObhGcXYnfIkzlp+A7pUG/TdjWM9wzFVr/qIaXo+fvkrfO+V325ikRKK07MaoPD7rcfIKSNIpB+QleeLr222"
    b"dqHTs/AYJqFlA1sBKreU/G6TiqxKfCzHV8XZmfx4X5L49gUS3S5eq36nyWxxsxHkku4w3UD+4nWSleafAPc6suhsUI+Hj6fh5T7c"
    b"py4KLWUYDsPeJTz5pNT0QTg9yFJ1fZK+doU+FWG2yM6zSwi7jUH8AHnkaX8YSe9devNc/0fcYyvefZZ6DlJXJcjC9ckMHVH4E8w/"
    b"I+XveH/KpPU1fWs5jP9hbaEy96Da40wP51D7FfBfp8ZvoOgbfJaKY18G5Rm0fQQH2IW6N7BbyzmC+t06n9IHXyGLaX3fQz3dhncW"
    b"tLIyUV+g0lRG+RGv+YJzHEtlP4mn3ee3hDPl4EXFwS3yuPK0Mwa9wn8ITR8ltZ3l8VQv5Nnwns8v7leiT9/pt6MP9JWqfh+eF5K6"
    b"/yT3XmCqzAnq6lTZvVYPYfg1OJmOKpeTHLeC9Agor9G9dEWres4Dm/np2fn5LIWKTrId+W01V8B8hIlqu1Tz9+zZdCrlDeaM5/GL"
    b"7uxqS6seO1wSXQWtm7z7UX8XHWQNqvtaetZbTIAvkBifYtbqRra4G9yN6Tu3w3sF0JcETxGUXABW84BOrYL4fBE4Ls0zqvo1eXYT"
    b"lHIP6n4YV+zPDr5E5UzEy76mouN8J5ESSrP3KqF0tXrD9mjO9VP8dgHYf7P+xJcOUd1XQab8OwvupZysICovwH0+vkoRN/PYnatg"
    b"P8wr/oTpn6iPafLbeobTFXqS+JpZtcjcea0Ak/RJUvdG06U/ki79HMw8DMdtOHNV0RXQeFFBqCs6C1kti1RydpJXbr5TGLzlyDK1"
    b"8OumOPZ9fhey7FPwOwpPfJ+8PRvnXoaSVC2fwDdvgje3VZSZoxaIW3NO3cD8DG42BsbfA/dUnHwhrC23VlvrSZPbyGh78LdD1Phx"
    b"tHyKvTjFDHWStH4UrPtA+zfVsIG9WokfLCR3TyZ5v0GfHmw9bT2KZ7Thvaqzy/ngO4N546C/HX/5QdT9HlwPw30eo9/cg/fWB3l5"
    b"cBXErbLjYhY5JURnukl3zuCziGfhZ1n5bn52pxxc1wF7G0nbT8Lyy6jnc1x7Ce+wFW2f89PAnJ93r4mn3o13Pw7eF6yxpJNP4Gce"
    b"/vOTYN1MutqFbg+h3uOCUCM9xVca6T+CdKP8hqyfeN08+tTnYH2Low23/odzPyK9qjl5rDrVXAT/Vgq/TFLY7/+Fh/8M6vkw/jns"
    b"vI4ih8L6k6Ly+0HfGvwNUG4t3LmKKL0sGlBL6boMX1Xk8epUcn3qoSXpU6n7cdQ9GMYn+B+STr7mHVQ62ct7puLdufDuKpyP8u5H"
    b"4WMYrvOuJPBv6Dq/guYvMB8B6wUq9wYaDlkRlsstZN2U/nwJdz9Ozt4F+vVg/94o+01T0z3QUQtqujLvlWI5qPsMHO/Au5ejv1mg"
    b"fQ//Hs1ZDkDjPehbnUDbCrSNwVuXuq5FxdZgVedW078NhHUFY1Nq+G4m504ouyd1/DRZ9gX633hc8WPQzuX4S2F6o/83XJ9gp2/K"
    b"b+MqBN/VrDr4WVty+MP062fIZWPExz+h084GwWLw/4xqN1Ct21H5bhg+AMpD3NTah+7/YXe2UgVrcTLF+Nf4wmfW+9TKKOG7h7jZ"
    b"HbxXCfpGgJ51lvPYhr/8CM9TYeQ1Jsz/+f04e6Xv5n4j9FoDNy4Dp0VQeQG8Ky8rH59pB1MsK44bCPaO9Lze7NswUfYnaGehIN5G"
    b"8jtJNgj7yVYBEllV9r8p2nsQp+lnPYfCX6ZLv4uLf8E5zwXvd1TnT7D3M2pfC+616Fjf1qCD1VTvcqaoJaTWr/GAmbzuE7r8m6Sw"
    b"MahmEDw/hlt0pIbuojvWsCowceS1kpmxbpCOjpKRtjLdr6LylIt/Cuevw/kwFN6P6u6Kwtuj8LtgtT57UItdqIqaK5uldK14r8cO"
    b"NeN5HdgvhfwZanq0aHsybH/vr/Y345zHZbbMBs/lSGSK5YfoowOownHU9ad0nHmxTv0nHP4Dm4ep4mPU8wnWST4/AtN70fQOKv93"
    b"8P8kv/VuhiTP1+gCz1Mtj5G227GvdaihEqBV6fOaqHsn57GaTvKtP4dO+gl6nABDIznbZ3HgvtR0DzA/AOp7wd2OWr2b1YZbW1Y7"
    b"HruX73VG1+p3zPXGBZ5BJ+q3zI1jqnqPI06hchaCeBV19Ccd8jBp7Ar6DlBjhcj/1Zi0msJGJ3pqH/Hw0Zy31vcs0fdS2P6Vit1I"
    b"3W5jF3ay/gHxLnxsB49sZnfWibKX0O1m4/0T2T2VSgZSMd2o6pYwXR115ZVcctE/xnlsYhZYgncrdb9hPKwv7tsFRG1xpTuZr+uZ"
    b"mlb1XE2YvU1cqwHfbcEu3MvOdCOxP8lrVT2/zgT9GTP6QtxrNdW8gyo6Kf3KtnKAtiTecrvVEJdph491x8Of5ByHMgGPQ+Vvo1Ol"
    b"86mwNwetf00X+hYdL5a1RO4X8chCdmUuOGfyzM9F3W/z6rEcZSgV8yRH7cbR29Kn7yARVIDxfOjbR98XQK5+z+F6UrjS9zT0/Y7/"
    b"KspUfPcTB38ATu8G3Z0o/A78S2m8luzD7XxVj11pIspuJ4n7Uf8JvGwY+/eG+PZc/zuY/oMucRgP0b9TsAjncBtdqw0c9yCJPkcu"
    b"G0tn/ZDpcjpIFoLtJ2bM1VTzOnxsA0xv4rYBXtdLXa/E434A+dfC7iTpVa+QZwejl97s4wOknrtI3LeRCErQJbNZNh36Mko75P9D"
    b"Pf8O1z/5i2B7Jr36Y1T+Ov16NJwNhrn+8Neb/vMIXagb/D/IekB+d6K6PcRXXVF3T57Rl2cOINENpU+9jCe+S+b5Ar7n+YvpEb+h"
    b"753U1Bn0HaJbp4C8PLq7g056D5X9CI42CFWO5ezfpz5nSEZZIvpeA06FfBMa/5O1BVVvAv9alL9K/Ewpexqe8D4zhnKyZ0Gutd0Q"
    b"FyvLrJED1GkkhSNg3kz3XEoqm835fcQ8NE5+S6Sq6V4g6QYuVdHt8HJVzW2kou9hdSB9dQLzwzyrN4p4hhQ2jJ16FX4/8CdRLXM5"
    b"6o/s5zp/C++j9X2deTpJ+lVJ4bouc0ArMD9Az3oU1AME9yiQTwD7e6j8U9LVdNZs6yvWfFnfyP0C3Gsuj81kfxTXSt9voe+X4Xso"
    b"fD/BER8Ed2sUVRc/K8W7KuQ3qesTdJNtsL0KPtRvyPxUOvYYeH5OkHcHWUf0rer7LlTchNUYp26C2pui+VbsQgfTpXvTpQfxyrE4"
    b"4gfCsupYyrd3oaqzpBLl3PnQWyVRdyurPRw/iuM8R49+EX2+zmw00SCdCaJ5rIXgWyg1rNZc1hxBOkWQvg/SCezSKPreQLD2pV66"
    b"UTVtYbmRVRuey/N+hdjprNRzGjo7A9sqk22SnvUj1TeXM52Cxj+gz77K2b8If4Nhvr/8htBe9LCerO5o4GG5dRdtPybqfgq+B6GT"
    b"kah7vP82c8bnVMzXHHUF6Vu5t1L3Nbp1FnJCUbiuibpbGOT9OOfh5OUJwvAUo+9F5KyfqN+VdGzVs3+Rj8t57Ed6+UL2ZCa6niTY"
    b"XxEPUzXdQ1A3g+HqaLuQJNAQ76x+U+tuzmQ9GfR7lPgVivwM53mLin6ZqhyOXgeB9mmw9ANvH3jsxU2tvlK//VnP0aMG+yN4/kvg"
    b"fJM6nijankUlL2IXV1LLG1DSbvCeIBVcEwfPysxRGIVXhIc6MN5cUlkX6roPPVaxPhL0r+Js74iTT4L5aezCTPrYbPZCr1mkbaXs"
    b"yXx/Iqjfptsp7x4i3h3NJs3IQYrtouxzFrp1KorTyNdydos5zxmcsfr9r+NAMVRcrK94mPr9r53RcCeUfp987ISDPcTjiuW+gl4x"
    b"/BI7pnCr/jzf9Oct4l+nqeh0Mncy/bIoHboqPasB/no3VfeQdK1+cPQ/mBqBE40F8evkq7fp2e+D+yPWh3JT63208A7fnUBmHUcN"
    b"j0IhQ0TbT8LyI6B9gFm9LUdvDOKa1HNZ3jM/Ck8ikSmFnyOT7Zecsp7qW0bfWoCrTQf9h8bHx8DkMHh/DvUq1p8QznuxG5r5J2D9"
    b"KXx7IJwPZ7dURb8D8i/Yw3loexleqXr1PvLYBbqk5yvkxdj9GuSGZsJyN+nVz+G7o8AxQRj+hO47RWp7ljCrnEwzPAPeJ+PwHwu/"
    b"E3iFruinUUoP9vBeemEzjn0beaAk6s4Nxz57fhm0x5h5dorC13Bm35PM5sLQNFT+CXy/g9JfA/M4UI+itoezXgC9ug2Vr4bL42NA"
    b"OY5nvsnzP8ANlLpnkvEWgvdHuF5Dj94q08YxyWNpuFkWdj0//lKOTFYbxpsL4104414xfY8Rfb8NromC/wt2YBp7MIM1nc+m8IjK"
    b"JB9JPb9ukA+y+gvyB0Heit5QF00pnnPLbze+Lrlkn0yWv9JHv0OPX5KTdRpV/j0SdP+DvwHw+BR89uWmaltxrTyrPzU/GPwKt8qd"
    b"70hfnopOFgi/q9H2VnZVMXxGpiv1u5lThOWy1LPqWA3B24pc9gBn2Z067AXfz9BlB6PzF0AxCuzjUPsrKPlVavY1Pr7GZ69wG0vd"
    b"j2F3hqOP/4m6+4H3EbrfQ+xgO3rVnexnbfa1AnwXpKaT6Vgh5p7z+MsBk1HWgH0JDM1B3Z+D4F357c4vgf4FKla52gDxtSdF0U+K"
    b"lz3Do4OkR79ouvQ7sP05R5iXqU8fZI6+hLZVVecBtarqOsJxO/ymG+faG46eA+1I6dMK21uoXOn8Q6nqD+Wzd+WxCTD7KphHg3iw"
    b"sPsE+9UdtPfT9VuR5+8QtOWlO+dBV0GqOQO8FziPw9TzLtx1s2hcda3FnOs8cM/Ejb6ga0+U2n4b7U6gwl8D16ui+VdkjWe9znfe"
    b"BOt7Rt2TQfwllbKQY/3EMX9FS8rN9uMeivEb6DtITsiP6sqCvZY4Wmv02BmWoo42DB9+GUYnoHClceVlH6PmT+jiH7MmGj+bYDx7"
    b"ONPVAOspXt8d1XTgeE3FxSpJVaeIh10nl5xi//8B8R+c1wqp6Xmc7TTOeyLn/zasjadex0pNj4JvvRSjo+FfV/IEduN9VPEpWKdJ"
    b"p1qIWhTW3zjuFmpZd6uzgjZEv9L1rDpWeXympvCtfvt4G/p1R3B3oyIfQ6f9qO4BcP+8aH04rj4SbC+ig9Gi+xd5ZAQ1MJTvD6Qi"
    b"+ou6HwNzF/huj0s0x721m2n3Vsi1n51l//cZP1Nz5mLR9wxJ4Qr56zD7MihfNA422KwhrGF4mXayV8WxPxDsM+n5ap5cgXZUj1ba"
    b"PomurpNKHJJ/HhCXhoGa1HQj8bAO1LRyscfJU0+BdCBIh8D1cME5KgHnSME5TDT9nDCrdK3r+H7pU63kN7TXoyNWxzfKUElK3znY"
    b"a4t6Vv3qPGwflZreASsb6NerOdelwvp88fIZqPxz8fMPWe+jdOXqb6HnN+TjW3z9Lsr+ELb175qfwau+Mt69kuOtZz93wPchk04y"
    b"qOssMk9r91b9uhnnqpE/AoZ+gnuIcKt69jip8NdQsqrlCeJpr4iLvQj+IVLT/dgxnT/boxntYFUkgRYQ57asMO99QTKZ5ngjaFfh"
    b"YgrrQs54FmxNhuvPYPtjwfqBoH3XIHyXr9UefAKzk9iVqSCdw+vm8/rv2LPlHG0tzrgJtH/TF4/QJ87gY1dB7KLwZBSelylLoa5i"
    b"ulZjUfg9nLVmXaN/UvAPFIUrjSuVa12PhHHF+fMs5dxPo5LHSbNdqehOHKe1zNG14bs8uioM8uzi3deFaZXJ/sLJ1sqE+Z2oeyY4"
    b"Jhl9vyUKVxp/idsY1kumN7/Cd96Qmlb4dU1/jQ/+AOqfYXgzmPeg7eO8zxX5awIBdJZXZqxyVNptUs9NTT3fRz13ER9XnesJQdyf"
    b"NYB6VTd9/4w89iTffQK/Vyi7o+0u7FRHqePWHK0JR1V/gUD1qrIybeRDWVmtgDi4crOzqE4xrj38d/FwlVS+o9vOpefOAP9k2QHl"
    b"bu+Lk78tun5btP2eaHui0fY0nPArXrlYkKtOvTmm7XOibc8kk+KcT2UzXbYA9b3CcE+p66fBptgdApeK1VGxuh4pPq3cS3XmAaBX"
    b"Nd2Tveosvbkle6hmK5U9ywje3Oyz6lc3efdLoD3GuexFf9sF7TqYXmHwqor+WmpaKX06a6qoeDJrivyNiGmsGSyVvebwzAWsRfj2"
    b"9xxhJUdS6t7IPv4ls/Rh8e8LpP0M3CzArqu/H1HIpJTq1HVd9H0X53wP6DsJ4z1B0xtG+0v/HgTKwbJUFQ8R1P/j0QFG2b2F8668"
    b"tgNu1lyquhZHVleJiqCu7Di3i9quCsvq6olS9zo4XgE/izn7eZK+FUb9dzFUTb8nrOqa1tyqeeozKn86yNVfyVgo9bxMEKtutUN8"
    b"+4g4t0qfYd+Xv5aRi3Sk67kSCqwFL3fAdlP4bs353gtjnajLh0CglNsTNI/Cv1q9zMfHWI/ynZ6CU1Xx/YK2nUzRdwli7d9V5G9s"
    b"FOMdFeNJVHWYzqkzyjFx8L/wNOXgP8tfBfmO6pwvrjZd2J1kdkA52AfmNlF0PQllT5FEorzsG/heCttrqGr1N0J2mdStrpvoPp2C"
    b"uouYvxJSi7NTHLcSvAqt6tMKZW9T10+z+pv1ND1KKboP+B8TzF3QdSf5iyKtBW1Dqebq7Gc50BYV71bXD2x4vskZqI51Gpc5zFnt"
    b"wcV3iI//TqpYLbh/AvkSmF8EhwtAM4/1law5ZqnP58Lx14L1W6nkH42+fwPzRuF7F1nskPj3BfZYMa6Qa0crHtN3PaPvtiBQ2Lsa"
    b"7H3A+KRU+TNoeUDMzZ4WN+trvEx7dnthuinI6+AWVQR3Yd4nRbp0GMxqzjohV052SVX/If6tsEarep44mapqVb2qsmfIbSZrlmBW"
    b"aJWqlyRgXSdYt7OLe9jNo6j7LH55BVXd9COkkyzUV25T0SXBXEn+KoyqatW3lMpbSe9qLzq/HzRdpMYfZvWQ1VPuu8sj3fjeQ3hg"
    b"J56tMLehnptKEqvDUatKPikuyDXfEalr1a9VPlF9a2tCPlkCbu3fX5r6VhlF/fUbvT7ja6XqaaLrOZI/v2W/fhJlrxMXU7gPoSWV"
    b"QZW2fTJ3dvJRQc6jtPkbOHWo6Mb01Jacr/oLOB1l4tIoe0jdPgKXj0gNa6zdhNfOPO8+KqKd9KkWIG1iKrkGx63EbpaSWs6Hh2QH"
    b"r4ODq0SmPPxcTOG7ReFb4Fwh/xXsK+k6P6FYzfw34tDzRc1KA/NkzWctEG1/J979kySTNeLem9nFvzjufnEzhTxVelaAdJKLsyls"
    b"+nUNzlQjbyV//UfhfkhQ96RyVXX3YfU1q4+paLULDxtd3ys13cLU9G34Y0V2tUSMYUecO1XUfVI4VlcStksKXS8863peClpd0d9K"
    b"TlsIMn2vvl5kMP7IM7WuV0sV/4F3aW3vpvcr7z5BLZ9nd6+xyyHJY0nkbzVVFxAPLwXuinBTA/9RrDfizJuJk98tGr+XPbifXegs"
    b"jv6QaL2LfKbZvp/v38vz7kEp2rkboe3aMW0r5IrtbHRr3w8ZL9Ppew/9eptU9m/C8TKZMhcJv6pjK9+aLX17tqyvhOuvRdPfgX5p"
    b"jOE/8ENd0Qelos+BWDEcMXhz4d3KwUpJz6oqPNcVtE1A29zgbQvj7Vkd5O89KR3fK3/3qYPgu0c03RqUzXnNnaikIUjrcqSauGJl"
    b"Kqccxy/OrhYAsUqgyYJZOfgNo/AzKPwI57iXvqWwb4EvlVZ+NbwvMypfAr7vDPeab8X4Yh7/AdSqmn+Wv2a1HtX8aWp6v2Fbcx1h"
    b"2ghKr1bTdAnxsWqSR+uLizUXxO0Mv52Ni3WVOtb3XQzDnczfvmojf/tK81tHlF1Jrh0UNwyrVJJYz6pjnYCNgyhxN2h3cJ6qa20Q"
    b"xL8J5l/AsYq1EuwrYHOFrJXyyCq++wvs/iqe/bto+0/qWE0Z/wjeQyA+zrto/9Z5zMPBk9j5FBxNKbwY1acUXk0UXk84byoKbyMu"
    b"3kHcrZNMIg+Iyz0gald5pKMgV16mtd1UGNe+rb1MdWo9WTo4t0reGrfmeCees0UQ/yZYlwu/qm4XC6ffipK/YS2Sr1W9//gf/G6R"
    b"5LlH6vm4qefrUs8+LCt955B6Vg5eUjy8Ih21hulaum9p1MrRW4irtxb+1U2hu1vYbS3fbcGzmgrPjcS74wqvKHyXENSa8WRhPMK5"
    b"pMpV4NPU3uEY9q0wtsGoe6Wo+0ej7UUG90K5/yaToykV/Mxr9EypsO/ieCqVnAK56lm6T6vcnUeSaElJJtUEbz3OWde06tJtpZ6V"
    b"xjXH94ueO0o31n2qnVwvaCUpW3l2PUliNcS3y0lv1hwrtFmkniPsu6rny5zNOUmhWuMql/0tfUtV9R+sdWBYi4JXc/tZ1gpR9nK5"
    b"V669SpBq714nCt/Erm2X2WoPxzxsavqc6PuG6Fv9jCO71HVBUXcZcbTqeG5d1NlE0LeSdNYOfd8nKr5f9NzZ6Pw+2Y/2kkdam3my"
    b"CZVRRyboKuLbJeUake5Zas4Ky5VBhfmkpLJ9wvEOSWYbpU//xvpFMK2Q2zJx9GVS1yulzn+RvVgLUpU3N4ln6161R+Yq5dynxbsV"
    b"2jS5fmBZKpElSybTPUt1LYW6Argrc7418aLanLtivoE4ehOj9eaylKKby625/O0+pe0mVEQDEKtOVUvUXSWB70Li3zl534Bk0QxJ"
    b"o2qmPilzZtTPNM/rwb1G8K0QvEulhn+M3f8kSWSF8K3cTDnZRmF5p3CsspjqWBdlxroJZocdV7kkt3Ew1bUqyLUT1bdqC9KGYLhT"
    b"enUzUGmErQSrcqrm4tTNeE5DQVoPpLeD9DaUUpVdK2ewKu/Oz1JolX8HZeKIyMxxHb4vwvcZw/hhySp7qMa/pLb/NG6+QfhcJz6t"
    b"fO5XYVndrxFVKF2r+Xkzaxu7tkO8bK9x7zPC9zVJ3670rGSpa3VNVPXrssbLaknn0gm8mfx1xlbiWyqltJObquR7xMm0jzWXHt3I"
    b"9GhV0ZUFtZqhC8qkkV1825LMfUPQnjM96xBY93GeO6VLb5UsqrAqJOsNXqVjvdazFKsbjKq3CM6/2Sndp7S2j7GPZ6RXXea9rgvX"
    b"EannJGpMZTKl8ILgLia5rCxuW8mwXsso/A5ReGPhvqnhXq9msu4UbTcSbdfjFdq5q4pzqxSqroTml46VzLtacB2KZROdvg8KbnUd"
    b"Zavw+0dCr1bdeqVZq2T9HOvQ6wX/ZkmfCrnuz0cF83m5GqjnK99MWDlBm1/cW/WsMpyf4rmqZJRanHcd6Vx3COKGLNWNGpqepL5W"
    b"tV4fjPXEtW7nVTXZpyoslUrKiYOVkFpWXOdmd7Oxy+r6gU5k6aJv5WdnJZUdFX1rF1e+tpW12aSV9ZLM18o+/CbK/k2W5l7h3iSu"
    b"r5DvNIwfRUeqX10U5On4p2Xpa0UpMlsqFysjabQKDN0m7n2H8a87hdfmUst6tZCleY4yrHRdm1fqyaq85JHiom3tXtlE3b5Us+7P"
    b"l6SaT8XQ7qcKd8O2qugdwrjiXNWp6kPqfqN8tkke+1MwbhXP/kuQ7pY63o9mDqPu48L1OWZXre/0GN9J0rFSpKoTGa9ARSp13yZ8"
    b"15P6jqpb61trvKksXc0NTSbRyKtJ7o4jz4tr5pDroKqqb0pVX+aMzsisdcgk752SRbcahFF+18msGWdWZc7fTU9WFb3dVPQ+dk6l"
    b"EcWvQqvcS6ENGbTawRTafPh3YTSoU1lZQVxJVF5d0plWem3hvq5RfB1BV0dutaU71ZI8UkN6VBXwlmcpdaurYoXFv/MYvhVupe+w"
    b"6Psa2FVd666lMsp+qe1dxtOi+KOeptPKOtOfta43CO86kcT7tMok8T6dIXOlxp2T/dcepry7tDhYZUGre3Tmim4s9dxYPm8oj99h"
    b"uK1lMphStpqrSpvcWYgdzQveFLl6kCTu7Uo2STP1fFEQKxc/Jio/KFWtda79XGt9O3uwTfZB74X+arv0p79F3f+YDKb1fVT0fdow"
    b"HvfvuL5zib4Lib5LGUeL6ruWYK9vKryRVHljUXpjWVrX9Y1nq0RSLVNVF/2Pqs4wVX1R5krF8RFx773C8U5Bsl1615+mgjdJdev7"
    b"P+U72+Q5Ste7BOs+war41Qxr51YOliHTtAfegODNIbNlXslkhSWllIipvKIgrypuXkMSWi2j9dvFq6P3twvPtxl1VxXvrmDqWaPW"
    b"s3ReSSfqCoLu1iG5gnJNrqGcEz9TqWw/a7cg0fz+KTg3Go3r7r3RaHqTXBHaIk72l8kjByWRnOR4qkdr306TxK2ukGWRmVKrW1/9"
    b"1v6trhpVlitH1VkaZ23Tr5Wr6fvbxeNqStVXk52pxKoory8tx9K1rNAqdetqziL1rLv0Tcko1+Bb+ZnqWqcklx01yWy/9K49wv0u"
    b"UflfogC9F9tN8tohj+8UH9PqPmDUfUzUfVbUfeWWdJJF3Fv3a1XZ+qpReeNlNQzmOpLQtIvfIau+3KI9unamHl3OXC0pLqh1AlVz"
    b"dJJcIdO55IY4mPYw1aM1z9rF9wnW3aL0XaZi/0q415pWqt4tz94vrq2RHheWz4i+VepW1XxD+pVm27YCpqZzSlUrjReSXFbczB5l"
    b"RaeVBIvWuMIW17nWunL424Tz6vK8ylIZZXl9aY5UTCbLAqJulU5U+rYkfadxNqngvihXyk5JLtPpe5/hV/O6xVR3/H6LuNn2BJb3"
    b"CseH5aeyp0Tb2r9SpaYVXjVhqSsm2QzafIK2qKnoUoK2nFxTqCRKryKVWk10XM2sKmauqGIwVhB9lAVnaclhxWVuKySzhurRqktn"
    b"kwwaYKlEpvwsXRztmnjaBXHxU+LjxxJ8fI9JLDuNlyeuv+XRqLZ1MjkkyE8YvqNsp5tpI55N1BX/goK7hKSTqL4VUt2/bpMa1h1b"
    b"83ubcS+dsasK9grCbynDb0FzLTCXJO6sMl/pjnXTsHxFetZ58fBTMbyqptUMckBQ7xPkewX9Xqly/dU+o2uNUyE9Klg12rOC95Kk"
    b"sdSYvl3pWAHDeA6ZMvW1o3hSKSMZo6LhuppJKzXNHkRXTalmrYPKxs3KCt/FheuC4mX6KpGepDVuhfqqwayuFx03fVo72K3s7khg"
    b"V9f0reweNfV8liNqbV8TtBmmmlUyUdfIssfQ5heFFzFJVFd0aXGkcsJgBUFTSVBVkSsDVeQRfQVMu3Z50XZpOUJx2btCclyVxdS1"
    b"X7WCLPUTeU/Ura8Cq1nrgiTS06xjJpkdMtWd2dN2ipvtNG72j/QpjfyAXAs8Iq6tkaup8prxbX2VSHOc3cyVUQfT6i4jc7W+TlhZ"
    b"ONY6V8m0mtxr5VeSXSgve1La+JbOYUVAm0/+FVGK/MuDZPnZhs7dnnSrm/CcKj/puCwernvWGWFcpfGjUtfa2Q4J/weNlveb+wOy"
    b"L4elFo7GtK2mDD1nqEkj7t4hyaHKvVW3zip8p2Ryb92ztXtrfVcyblZddKzVrGu5quFf811aErfuVoXk3wZqZevMHZA8phOZ6llX"
    b"ZK7UePW0dUwwxCt6v1S09rN9pj/pXnxQ8B4RZZyQ15+RlKMr+ZrhWNdyRK7/2qLvLJxLNkGsPTyf5JSCcFVUPE13be3mOreUFZcu"
    b"J3tR3jh2efH6spLjSolWikknKGTqWWdvnb6zSh7T14vC4t3XBfslwX4mhl3PXZrVfcbBdsster831qEPZurRp01NX5aavh5zMOXb"
    b"QXNVMNqz8ot7FxEP031L9+myplorJKzyssrJd3U3LiU+UIxVxDCc38xVuUz2zCrZJCAJ1POVk4WMh1+XhHxFMqPi/GzMyU8Y/EeM"
    b"zg/KThwwOtC7on37iGH8uLzytBzlvGSfKHI9ZXkGe1bxM1XZeYybFZV0ktivKxiF666sda4nSN2jK5o90D26mCTQgsa18xjUGjMy"
    b"k6sINwXtddG3Vrhy8DOCVc+YunMdERZ1XR8SRWuUWtdHBKd2rlOyW2elli/KUa+KZ6QZ/44I2xpzkrhMNklLOpXll/MtLAovlqDw"
    b"MkbhcW2XT+A9qvAyCQovajiP1nV2ySZBmaY9YTpDzkvn0fPiQCeF4aPC3QHhda9ReLSutVfvNT1a70mc5TNmvrpiru2nxfrzrfrO"
    b"bRSufaxIDG1Jwav7UBnjbPpef13KKFsnMD1P6c5cUBwirxw7RWY51aOzSEU7gjkifpohKfyaKPySpLJzos1TMn0cF30fMWlFs3zI"
    b"aPqg+epwgrZPiLajuVshT3SzqHcnGe+Ocxyta13VuqbLm0xaweTNiobl8iZ5lhFVlxTURTMpW+HNburZNnksIlgzRN+pxsEvmjnr"
    b"rOnVpwzjJ8wkknkdl6X700nxrtPGuc/JkTTP12LqVlcEtYNr1AHhW105ysnKY/pWAZk1dTIrZpjUflXO1LlOqtrpSsutlEyUuk8X"
    b"kQm6QEzZcaaVj/ni3MrF0gzqiyZ5nxV9n4yl0aOxmtbVfNA42lHj1sfMs8+Yaj4n/2JMJ5JUqeUM6ZDq3x/on+gEheVkqeac4rR5"
    b"JCvnl3mwkKDWfqx9WXffkkb3xYxflzD9qYhRdiG5QqSnaH3VV7Ot+5WeNixJZGHRd7o4+DWZOS5JMtO967QkU41fa/yoKPmo0fNh"
    b"8fWjooPjoozT8qrzcoRoKtE/o9V5zJPUHRCOswnmXNJN88uMUFi4Km4w6isp2stLGX/Wai4lGUbvSFHxgoKikaiy9ZUDPVnpqwfa"
    b"wdQ8rZnOkPyte5Z2s0tSjeel45yV3qO1e1Kq9aSZwvR+nDHd6bRMF2dMD7gk1XzVoNY/uUsXdYdF35boO0kyYnZhJLecbwFZRQRH"
    b"cVPhJYxnlTZeHr8vZb4f7dIaewE5Um6pmuyyu0Hp0lHU+rqJnrSumjM9L1V5Rhg7KbcT4maJ95r9U4L+jKllnbN1EtNZLFVqJ116"
    b"o3Iw7d6WMB2UOksW9eUwjOc22Syfqe3C4uhFjacXFWyJq6jpTkUFsU4mBSSb5DPpJMV06mTxMz1f6nk6JCxEHe2yuZ5wzvhZ1MFP"
    b"xLzsqNyOmvR13OzEqZiT6enqknGxG4I7JCx7ZqbUPSubeJjOJnnlXAuYPl3Y9GrtZsWM3otnwlpEdF3IOHZBQZrPcBytZp3Gspj5"
    b"yjKIXVPTGcLJdXMl4YpUtp6xNfpzhs9TZg/i96fMvmjEZ+W552OcXzH96rro+2YsndixdJJN+nU8gRcw1wqLGGZLmBouZe5LxT7P"
    b"XNWFYy6WV3p0XNtJ5hqoJf/qIhzj+Eamir4oeSqu8rNyr10tqufT5jvnYigvGJyXxL+iveqG9KoMo/CIKFwnFM23xp3N9K1cMv2q"
    b"s44qXDNfxDBfxOg5ru+ihvMiwnmhGOd5jbpzCOPJCe7tG/e+aWaOa+YnHVH3jibw0yaXnjD3x033Phlj+4yZJKPKviw7mCr7qTFH"
    b"RN2KY+VfSaZHZxe0iVijKi9gUGitFzE+VTh2X0jSTBxlfsNxbrkmliLXQLMbvFlF3foKsJ45dCa7KYzcMD+hv5Xzs6bC42yfjqk6"
    b"yvxZo+1zhnPdr+KzZYbUtWuyScDM08nCRYpBHdd3YaNwnUp1Mi1m6jpe20XMZFXI5JG8/1HRer6KdqyIyd0ZZsq6Zvr0FfEyfRVF"
    b"M37e5KyzsXs9P50zytZd+aLsUlTbGu0Nk8UyZGfDMmH5hu9/O3iKcfC8Jo0XMGz+W99FzY4UjuWSgjHcUbZzGmUni5MFTCJzTSbL"
    b"XNdXbqnqs6aqT2daZ4xvRXNnfKq6IjVyTY6YJnsakvzpmevd2sO0f2sfy25cXKs8j/HyfAl+Hq3u+CpkHs1vOlTUufPE1J3yf+hb"
    b"+3ckwb+jfeuqSWaJ6M+ZGk9cZ00tZ3YzrexUSTxpgjwkP6f1zCTtmGsnyWay1H1L+7f2sPwGVyHDdLyWC8d4jfdk7Vu5Y505ynBW"
    b"cQ89XSl9a/+Od6wM+fcIOqekxnBfNtgvC5aLBtMFsy6a++i6JHURr+VUcYi4f4fkHRP1nST6ziYrp+g7dyyhxPVd0GDVSk7EHu/R"
    b"+ROUHcUdzySJOTTq3PontrpLXzNXFC5mqmvNdvz+vNmBS7EEdsX49TXj2Tcy1XLEJBPf9Og44qzGxbObrpUi+oyqPE8so+U3+xDV"
    b"c/4Ez9bXwqJspxgn07gT3Uz/RD5a19rR4vkkyvMlw+F/u9k542bRHbhselU0j9yIZdAox9FrJtq5oxX9b6z5DKr8hu8CxqU06sxY"
    b"8/wfWJPNbBVM0Le+YqQrOmxcPN3gvp7g5VcN85dMjf/3umSqIMp4tKKjfTrqZq7U9b/dLIfp1ymG33gCLxBzrkKmmqP3BWM78e8O"
    b"nS2Ttp0EhnXP0hN1or6vxvrWZaPfizElX0pAGMd5JeZcqQkcZ5hKDmfKYvYt+k6+Rd85Y5znNjuQ1/CaWdWJfGvMef7Fd7LRdhR5"
    b"NJlEtZ0e8+7M3fqS8a7zCdV93nwWr+vL8vyrsmNx90qcr7S2NV6dyPRVwX9Xc64Y1ijnUWRRfHkSUOYy3qX7sp6p4t6tq1lf79Z9"
    b"Osp3OJZS0oWhGzEXj1b3FaPxy5nYvmhcPerZl001xJNJ3M0SsetEFk+jeuaI9+o8BlXmyo7Wd9zNojuQJ0HZOc3PrbLeUtFRvIkz"
    b"VrpZaSalpMaUftVcCUjEfiW2rsZq+Jpx7qi+4wqPajyS0LGinAf/xXrOBNYzK/zf2s6XCXmeBOSJuSTJTJaOmTYiscrOSMjeqf/h"
    b"Yf9V3ZcM+1dNRV9LqOg0gzfqX67pWLbUdMBcF0ysaf1zzOyxuk4xiSWX0XAeo4Hcxq/zxPJILvPsRLxx/86SgDo+cSR62r/Z1nV6"
    b"+V/6jn9+yXzvqkklV43/p2XqWNrJPONkgUx9S+ON+nfuWBrNY3iMr3yZNB1HnDOm7GymnqPXDrS6ndgVBJ1PdAoNGWbSMqG+Yfi7"
    b"au6vigKiOrhqcvZVszdRrqPpJC3mZXEHd/+/6s7xnwklWt/5jKvlj+HPk+DaenpOVHayHD3JoP53Ck031/vTzFlfzaTwq6aSL5uq"
    b"jtbz1YS8mZpQyfHrBplrOZrHHDNjRZ1MY46j1pzrRJ4S03duU+W5TU/OY3YmxXh3inllDuPfWU2n1lcPAuaKv3dLv85ImLdSE7ws"
    b"0b0vJ/TnywmefTXm2bpfpSVkklCMY1/+/a8j/+JEXy3KImeYzXTWFHOFMF7PeQzjuYxT5b6lS+U0XTmHce1kyZ1xvHq6ckw9+5KN"
    b"XNOrw+ZKQkZCMrth8OtZO9VwGq3yuKajyr5urg/F6zkjoV8l5jGdRnXHTpwxs5nzT0lgOU9ChedJ+CzPLS6WM1MCvTWV2KZneaZn"
    b"hWM8pxum02Kd+nqM86uG+euGz9QETaea3dE7FVV3uqj7prnWrR3Ejzl4Iur45HGrzqP9K8Wgu3WlZPLtnGbPos6t2dZXEIIGu0ae"
    b"OX/fjLF83eSTeAqP3l+NcZ36n/6VnjBLhmMO5v0rhcZdLGtCFs1uzjyKN3qfErvPYTSdM1bDUaTZzYQeTSZRvNEJy4pNHW6M8bCc"
    b"Z5TxRB+/bhQe1/i1hM9SM/XoG6ZPx7N3opvpnmXF0neSVHYiw9kNkpRMlZ07k59FWc6VwHA8fyabBBBMmLASO1Y0hWqFRzNK2i01"
    b"HcWdGruPJq/r5hlpsUwS5TnDzNLxenZjqKM17ZjzymL0HceeM1P3SknI5Yn3KbErQ/+l7qyZvCyKOzPqUIKHpd3i4FH/umb8PJHj"
    b"6//BcPTqQTSVRNOnqmfHXDXR+eTf9ZzNcJZZ6TliHSlxRX07RyyHJccQ63wST2NOAu7MDn4zIYmnJThafP1b2amZsKfF+E6satdc"
    b"F/T9qIMFDeZ4Nsl2C9aUGIspCfeZKznaqeLelZjFAqZf2eYKmcZ7a8+6VeWJWo/vwY1bNH0jAWu8lqP1HJLjRxLyd9TN4ujj142S"
    b"M2HPmcnBE1diFknEnpxJ2Ukx1JZxMM9oWzvYTXO17N88Rys38T6OO3Md3zQ5LJq3I7GrY4l4/812klFkcgL2uMqje5Co+ERlZ4vl"
    b"kniPzmpUFFe3E1N3fKYOx3hOz1TbaTEfi3ft1IRHEus5LQF9KIbb/Y+Opa8C3+phyf+q6Ph9Iu5sMU3HqzgRa7ySo/kzWs/RfuUZ"
    b"/cWr+qbRZ5z5/9Z4HGt8xWfom5n6VcTUUxR51M2SbunW2RKmzBwxBSd27Jz/qetsmearpFhNOzHM8YqOunc4Vs03b+nU6Salpccw"
    b"p8fqN17FaWZ/bporRNFaDst7xPNYYgp1THaIprIkU43xCTu+A9n+g/ecmXhPNtd7MzMenTUSvds35/TvNJqYTeIZPDXhPlrd6bGq"
    b"jl8bCpmddGOZJDpRRvNYvGNpnqNYM7tZ5qrOnsBrtD9li70m2qWy3MJ1vF9lTuCuUWBU36H/YDwt5tPxKo7fp5urJf+dS6JXEHw/"
    b"ynJmdcddLJv5aXV8+shpdB6/z2H4zWb+l0J0rkoyaJMS0rZ2L9vyTDXrawiuqeib/6FxncQzDINpCXqPP5oeSyPRLnXT7N2t6vbM"
    b"lRO1246p6vjMkfR/qDt7JlfLeYvGc/zLz+KpJCnGdKKTJVZ1onsndq3/XjcSfCvKbUaCc4Vj7hV37vgVE8f4dyChY8VVnrlvJcdy"
    b"S6Kas2Wq4KwJaBM7tP7ZXfR6kR2bsv7NuD7rjEy9K8P4142ERHL9X96Wbl5xM1MGDZsK0tUUnTUcU3FRhvXP8bIm4EmOaTzuVnHP"
    b"yn5Lr4pOVVmML0Znq2BstrLMVZP41OEabkKxWSves+O1nZ5Q5RmZHs3IpO7Eev4337f2rHgCz5KpcyWu//aybAmd6t/KTuxYUf/K"
    b"nEHDxm9vmrnjZoIbpyf0p/RMj0e7VIbx7HhfDpt5NVrN0XnDEmfR020gxnjQnGlWgzpLzNkSNZ5sZsdEpce51hPlfzEeV7cVS+D+"
    b"LVz/l3en/0e3zpxA40528/9g+f9VcjVMbuow0B+EpP//v/ZdAthvWmxrV5Ihvcx40pBLECvtrmSuvaf0nAnW88upZ40s53X32j3W"
    b"x+g30iTiQp01Y/4e80KZnonPxmc/lOPoTzhuUevYzkn8N2IsjlR8qay/CHPG+NQC0ec09Pmc8pcxNdlbPdtY/xvrj4qwx4eV3D1J"
    b"j3Vv39BruXOZzIGl61gU5n5+a0fyIszXwd0PwrorFnfTu+ovfwhZrOffDsJv8tqIr/TRlfxnz+4F+o5Hy9LXmOGeGFpt+kU13HXq"
    b"OVBeBn/HxmXao5w9Zmnsc06p3023zvr+DKciqvQbWOx3Y79PuxPy3TSgK9Z5Z6TsWKYR+3mGz5bd6E5WxV/PFntfXy32Z4t9bWzY"
    b"1Tm3axvGBOFUrNI6LMzwvZ3zh7L9A7n8Adcm+oS5La57H1jbirYuvLPa2vKUnQrn+mt0VK+BNfaVErmgLL6kz4C1Sv9Ah2nXHj/j"
    b"23czxJHUtiN93kEmE+/49y/SUsvBpSG0Qp537FdgqWfb5VzHq69REx3rU//Oz0wjw89v7WwmsW9uhneH8qEoMc/l2HvEvrednK2x"
    b"Rm1T0DrmvynExjOPdp7LiFLUGuv4Ra8ytl2pcpv59tzunlvrVYE+6wDlEv36UBa/KauFvaQmNuit9vbp6E60ZmXA+jE6JcltzHDU"
    b"Z5yWII8toFmResrz7ze4ojeYJ3T/LXkuWPdXpZ/ahg/bmw872qREo4x7OnF0HRj10rR2hQx/KpR7bnesn8D9a4v6/OTYvunM7Tim"
    b"g2Uw2kaTUfbgP0q5tVK9R+zsxaSP5tyWeIXHRKk5UnQtyHErOc4FnFgGNyb9lbCZdWXam/Xa5iz/gecf4PsNqgN76WI6zOj0WxIv"
    b"exS7rjQnkX4So8ZOWmYmFdyJeJSd4mXUvUj7Fdqhlnsl93jP7xS8e9TozLJyZit0X/parIPNtet+jD0s7USluywui0m8iOy71TN3"
    b"kB/Cd5/ii/mdhvPW8Xa8BXWMH489VKTd0S7w+RF0ujO47jL3tgNwjPuOuAORq7CNf23QPXM97xS5x93svjEafjzNulLkna8xs8Vx"
    b"xyDOH1nsMPm9Qd6y15JnO/D+Dpm9j26G+bvPf7sfi+MM86jGh3qs7uMJ2D/Ih8l+NLJYgFl/MdNQjhUfb/PKRvgyZx+OPks9R+iz"
    b"RLUWytaeveLTVpX7Xn5nuI6xcZloNUdexnnuFP8dn32gc/6oqkat7qyNKHsMxjy2qmr2atoqVaZ6jpN6xpgP2HeTTJdVOmZed8J6"
    b"xmcyPWHV8jtrduPC1+JAV3Cgj1YdecyIcssn9qFF+VBEeYda/ow63lVd7xDxMTrJnfqN2v5HgPM+73PmLV1HbFPa3Oa1Cyi3uHJc"
    b"BekHTYfkwWwm38fuRDquPg+WuKX72lTf+VGZbacHskfrZXcC781Io3496Pli9Fii9JyYZrJgJqNl7GIyl+s89x9YF8dN5Il2d7pe"
    b"S7ewKGyRyxajVctgQnQkXsRefmtvdpAebbTuf/8W+VyP1kceTekxs8/uJjTHH1pnG2EWnIB/evTIbZmw5auRibcX6DOwoiOodWnn"
    b"JWotWos61GuZWY3ZuoxVZgc94hj0BAH1JLe7ghPMtjDuhZ4vRp+yw9xJKVWEGVkwk7KDXNkxMN0I+wOw91UK+0rsM3BWJHedZNJq"
    b"XduIMSrUMnIDd6w44kiOrFQ9R9DTBJ3xh3mO1VDIk2A1c7cR4Fyi6ju0G1/Ap9lV8mGB2Pt8iCuad7MKVJ+t7l0hvFNFb+Cwd2cq"
    b"1tezlqWi0Z1wRWfico5bX4GF3pvIeea29tkYR42xy3S0uGhrx4I4c37IfvQxpibWheLEKKmqXpQmYe5n6pq102bukiseBo9VQFhm"
    b"CQflqs33Qz3DjOa8lqkJOvDkxu5hvZBL9R5Z6fQ8di9qzFLuMLF6+fkBs4IDsK1OvMJkci9ZHPUn88t8ke28SpT4G8llMr+jZuXa"
    b"qds8nCuwqbxmN8Kzg0qOm+cmso+XwI9mR5FsvBw1OjFRK+vGAul1GW6i0BVAp3ZQt8zZjRFLhyF78biDJ3dKMndnFbtmMh279JCs"
    b"VujE2H/qTstGecCc2B7T79P1jNHid6MLZ9VG9U4qdzPlPD/XOHPsGD321NqTchwHdWIa9yv+0pEGqulEeZ5AxzTuCVDFDipDD5lB"
    b"C6Wv0hMEdOFB9VyVfNXJTruKVWNd272vB6gg7mThtD8ODdVxc6Yzq3l8pbG17hMruZqq0zXJ2Beq2sN5L/4UUGhEGbU60rkmwJqj"
    b"y+A0/fgXFXWCPTth7dOd4D0YyOLVYbJ9kvn82+zEOnN1lJnBtVqLviaVtQnYKqvVOm6NtexQI+KIdVW1qR+HgzNqFOPNPMaR2t5j"
    b"ntXJKFOm7Igw446OQsueDnvQYrSrVJsHEnk1vVSBqHEmVmH/rvfVzDQa66h4ymeySL3FzJNoheZz9KrZw9rWsa/KHWNd195DJtRJ"
    b"xZ8Ux8WpOl1jLVrF7G1zu7raVdy1uIizIwmjwiIwrY8163acsnWkPjKSOluFZp32fsokcz28i5oYVMVoiDgz2n3kGRQ9E9vJiijr"
    b"WupsWqvuLTviWN3HOGZr91C/V0mT9WRM3CdiLewdVMTZyd3kOM5ErD/Pa9+NeuxdJhw9e7Uan63zKlJd81z0Lstntcv+y0YuVx07"
    b"3EKuTLC2Dq2z/AF5gNnA/itAhvmzUJvXwUE5q3V2HeQqar3inl7nta871fHV+lh19dlD+7rzmCk48rq+s2LGZdhFM6egd5rFWE0G"
    b"F1UT1UwM5lhrRBL5cOvYmKdspgTz23VMndmb3PGbTOkrTfqKw338jl4xOP1EvtbepE8LPTbWmf8vqhynucWZqDPTP/avP5JRPqcx"
    b"s818ajQdhVfRPC3RFe31XNJ5yYz4OnL9GSF4q86wGS5xugaKLak44wVrS0b7Efs1XEy3jTVcKmaL9rmR3MhVnznrurRLjUrvosmV"
    b"ax/GWo2vWl7yvSUe87KGsWYmCwZJL3KPw666R7+/Ck5n6WVmhRlAcdXc95nIiJa/Mc/Zl3moW172GV9HmmDVnRZfhVL9jNeKXh2e"
    b"rma/CjWKZxeISFDnicweHBWzGhWn7K2VC32ZvgrV+Gdbv17UqHv2MzW+wXHjM7Q8lYu3mqzx9X2oZeHyRc7aeZD3TVcuZYZ9/ALJ"
    b"b/G9vgoxMKP5Vfz9tQgOo3j+gWekwWhtdKeKwexizCYHdpYRbo/deUzf9cwVzOpKdLyUdRqz988+9c7393PytGaGaDFxWYc7Qzc6"
    b"en31apzgyL/hR3nX8ejdXOHUWVVqF++xV5jUWLz4zPtvijfvsJ9xf1Wqg+PMY86x8n/mHsVObf1pgK/4GL/HoezJ53XtH7uq5m9/"
    b"5pH/2be/ig7fMcuNK981x3B+THsN33N6VyNexHylR75/9b0e60G4rJhvKvTPev7fWuWyhrUz0+rhacNdLoQv6obnMV4/f63VzBjn"
    b"3ellMomIju+0GYn3P2i+uWI2n6eu5gXB0Xr//bYb8nLqisOCe1b6k32GuLrqVlXitLJ8xpn3PrO6iS6a4faY5d4wvb7zytJ8FpzK"
    b"Cu1/BeVvLdXHz/KOp/Dy76h2KOx7rrPN5oN1APbzozM9te/wddrDWk+HIx2zXuuK6+cKoK+DvQvFn1vO+DsaPklUHX7fPt9r8Z2H"
    b"d+Z/3v0/UEsDBBQAAAAIAAAAIVwUYKVOglYBACwmAgAWAAAAdWlfYXVkaW8vdWlfYXBwZWFyLndhdix4A5gc6fd1ma3p7mFsTqyN"
    b"OfHGtrWxsZl4Y2NjY2Pbtm1n0K7uMr77y/d/3uetKXfVqXPPPWdaN05LK1gYQzrUad+g/9AxeV0IgqAwpp2DlfEogiEupG+vMb0Q"
    b"OAdDLAtHNItBZIuEdf33GoXosNewCPiLwUWGhSAEErNcSMhiERwJWwlIlhUHZyJwBxT+OuCIHe5jwPGw5UGyrUSYLkSFPXYkCHuC"
    b"lhOR4M6Ghf5+Hgv+4nDl/4664RoOziVh24YIsG5aEtzfD/fVLRP2I3CtC8m0kn7f9X+/SyFROBq1aDj2v+dX4IlRuDv++84G3CME"
    b"z5AF95bgHf6314CzVMuCX/BZXkS0NHiqDJimFbTyIm+tArBlg/PU33ejYLJwfx7+YvD2IjxpBKYMW+RvLAJw7f/uFIDnkOB3MXhW"
    b"8v+Q+9+kYK8d3iEentkN1//vOgmeS/qNLzw2/DL2f+f+DxENrtZg63/70d+o47/x/9+WDu8pwnPp8IU4QMsOT6XD72bD3cNwHgO/"
    b"879v4vqNiPz7K6IIDcdzIp8BtSCcQ8KZLjjvf7j+/+v531dF4Y4s3Pl/SMQBrvbfwwnDhTiQJLhLbjiehHhhTyLihhGPeBAbkhPe"
    b"OC/MRIRHONhjWMnwbt7fvCF+v6FpxQD1qBWAb/ge3uSNFbEyrLewfGxlWi+sd7D+1HplPYLtR9Zt66F1DZY3rUuwPGddtS5YZ62L"
    b"MM9ap6zz1lHYd8baZ92zNsE8ZB2Ea1dYn6wN1i3rirXbemPtgD3n4OoHcNU967513Xpp3YH5HMZ7+J0fMAPwm4L1HZ5BgHUcvh7/"
    b"+6tQ8I5eeO8cSAqMIvBmJZDSSFGkNlISqY/UhNEKZiekBfztj/yJDEe6IwOQcUhPZAYyEJmOTEImI/8g6ch8ZB6yAFmCLIW5FlmE"
    b"bEUWItuQ1bC+FVkBa6uQzchyZDuctxVZDGMdMhX2z/l99QRkKFzdAu7YHmmLjERSkUFI2d+/nRcpBU+WADg7gHM48hWwy7JOWJ+t"
    b"PYDOIWsRzNHWemugNcXqb3WEWdnqZhWx6lmFrQIwOSuXhVgszLCJWD/MiOkz35iSeQ/WXpgfzJ/mE9NvPoetN6YIWxHTMoOmy0Kt"
    b"OCsHXFvYqmqVsZpabaxm1kSrpzXLWmZNsy5bKwHr+/C1cOS1lQMYlh+pgFRGWsPTj4B3WQpvsxs5iJxCniAPkZ9IAIkhPMqhedD8"
    b"aAm0OloZbYXWQ7uj7dBe6CC0NzoOHYyORiegw9FJ6Hj0L3Qa7JuI9kX7wWyPdkYboa3RsrDMg6aiKSiLxqFBREXeIp+RK8g15ACy"
    b"EdkEGM5A+sF3aoNUQioCR91QSaL1DVhwzzoGiK2w1sEbTLH6AD7trYrwPl5YcpbLoq2QaQAWPvMhLK+Zd80r5jGYe8wT5j5zh3nI"
    b"3GTuNbeZW2G5wTwIW4fMXeYRGEfNS+ZxwPIyXPkc8PxkZprf4F4Rk7IcFg/fIdH6wyphNYTxp9XP6mJNtsZas61VgN9+GOeBpQ+s"
    b"r9YX0KT/VZAD+JeKlIN3qI6MATRnADtmIHuAV9eRXch95BHyGBGQTwgFsm4DLBPQPwCR+mhjtAXaDfAcCmMaOgZdiU5FN6HL0H/R"
    b"vegK9Cy6Cr2IbkGPo8fQHbC2GT2B7kR3o9thbTWcuxidjs5Gh8Hoj/4JaJeDL1QEdaC50W8gTw+Re4DxSvj90TC6IjWQKsBHGjTl"
    b"DdTZQWstoDreqms1t3LCO9PWXTMbUDphzjHHmiPMemZzM49Z2DQNwvxofDXuGmeMy8ZK44gxy1huzDVGGAuMXsY0Y7AxxEg3usBW"
    b"f9g7C8ZmOOuEsc94alwzwkaWQZl5zZxmO7jjFPNvc7150bxhRoHT+axaVjt4hpXWEesJVDaLlEHqAAdnIxuAffcQJyBVBe2A9vz9"
    b"rjfQe2gE1dFcWAmsDtYB64NNwmZj62BcxHZjL7Gr2DPsF3YPi2FvsJ9YNiy/YV+xW9hHOH4au4Itx/Zg87DR2N9Yc6wZVhNzY7kw"
    b"P/oFfYzuAmwnAJtboUXRAmgI+YXcRLZAlfdCekMNFwB1/AEVs9vaaA22hlmVoE45ywS23DLPm6vMNeYgQKshvF0pM8V0m7ohGN+N"
    b"18Y94w5gdQHQ2GtsNFbA/MdYY8w3FhlLYbkalv/Cvg2A027jFIwbcP4r46ORbSgwkk27WcEsbdY1u5htzHRzvLn0N5OfAGd/AHay"
    b"WQqqvDnUQl9rqjUdGLnDegaMjIJ6u0H//lfRvZGxoFnbgYVPAU0R0REXWhw40hKYMgb9G10HTLuAXkbfoz/RGOrCGKwiVghLw9pg"
    b"jQGlboDuImwydgRbiB3CjmG7sOvYSewcdhc7j13DbmMnsDuw9zQc341txdYDtnOw8VhfrD9WA67PA+iimA99B6w9iM4Dnv4JvxuP"
    b"utGfUBFnQXsnwbcuCn3oPXSQTdYoqztUW5yVZV6H6p0AmJYE7gWM58YVYzpg1sCobxQwwjpqnNZv6lv0mfocvTOMBnoFvaReWGf1"
    b"fLqqxem4rmnJelgrpltaGT0/HG2l19HT9X76Nn2zfkX/qvv0vEYJo6Mx3lhlXDU+G7xZ3uxkzgW9+Ghi8HW7WUugZ2WBE6mNTAHt"
    b"fwPIFUV7gNKdRF+iGloJa4JNwXYCEiGMxovgf+L98Kn4Lvwg/gj/hftxJxFP5CGqEpWIukRrog7RmWhKNCdawFZN4g+iIByLI2K4"
    b"jN+G8zfja/CJeFu4hwOPx59hNwDJYVhvrCjGAnaH0A3oCLQ86OcHqIftoJE9oY9b1mtrszUfFCnVSrG+AV77zeHmYLOimWjS5iPj"
    b"gbHeWGIMN9oZDY18MBRd0t/rT/Sr+gl9r75RX6fP1xcCIjP0Cfp0fZQ+G/5O05fqE/UdcGSXfhjOeqjfgGsCMFyG1yhi1AX8Bxqj"
    b"oL63GYeBpz+grj3wff4we5r9gZlbzHPmO1BhF9R0GvSyiaCTe4CPH8A35YL+0hX67TJkJ6jRJ0RD3Ggl6AgD0TmgczfRK6iMWmgS"
    b"Vh+rjo2FsRIYdRZ7h/kwA0vAC+EVAZ0O+EB8Mj4DX4FvBaRP4Ofxq/h9/An+AP+EP8Vfw/ImzGv4DZj/4Ufw1fhiPB0fgnfFG+Dl"
    b"8CScwH8BY48Dk0dhbYHjbuwbegbqvifUfE70O3zjGchE5A9wRkFQxblWE8ttiYDrImBGDpMwT0EVDzJSjTzGA/2yPk/voDfSCT2m"
    b"3da2aYu1HlprraSWoiHaL/WzekG9ru6EsUVdrG5WF6gb1bXqNvWIelx9qD5Twyqi5dKqaC21Sdoi7bL2TqP0Snp7fbl++jczW4NK"
    b"XDdiRjnQlC2gxylWD/AIL8CntQbP8RCJQ9PQ+YCZjtbABkNdfsDiAZ+xgMlL3A786kgsI3YQL4gIwZIVyJpkb3I0OZ1cT24kj5LH"
    b"yTPkNZhXYe0YuZv8l1wKR4eTjclqZH5SIkLESWInMZVoAuyVAc+9gHk7PAGP/kauJVR0ALrSP2gt1IN+Anc0AfQaQZ6BkxlslbQk"
    b"85m52BxmVjFxM8PYCfrWxShvJBkf9efAuQX6QL02DFS36V+1e9oTbZ12SFuoTdPmav21MVo/QHGA1lXrC2sDYHuUNh2OLtH+0/YA"
    b"Ss+0N5qmIXpOvSJUc399rL5EPwJf4jvogdeobbQxRoOSHjTeGpLhNmuZHcxJ0OfPmr9Mu5XX6moNAT7eBL/qAlfWCJ57LnIJeY0Y"
    b"SCG0Aej+EvQI+gg1UCdWC+sMGrYbO4r9wDRAti5gOw5fjm8Dpn3AI3gKkQJ13AZq+h9iErGd2EUcIh4S54nvgPhPwk98JnTiExGF"
    b"7Y/EV+Im8Zg4DGesJWYQk4mWoAEFCDsh4tfxM/hMvC9eH+dxARR0KdYPK4LR2BV0DbiqXKgGij0D1EcDDzzF6gDd5gE4lzSzoPkE"
    b"ansgvHEUanW4Xl8XtOfaCq2LVkOLqq/U3epItbtaQLWpmcpV5biySPlbGay0UZootZQySgWlpFJUqaqUUpoqzZRuyhQ4ekw5ofxQ"
    b"GDWn2kf9Sz2pvlEZYOZQ7bqWqVUAlPfpuFEW1PeuEQcKs9U0zQbWQsgDRcHdPIT+PBC0XUEbQ594h+XAB+Pb8SBemuhFnCaeEQXI"
    b"tuRY8jb5hEykqlCtqMXUUuoa9ZT6QVE0Ruej89CF6HJ0ATqVzk17aCcdprKoh9RRahM1lupKlafs1A/yJLmQ7EAWJ8PERWIW0Zjw"
    b"EI/xtaCXSfhzbBX0KTv2CJ2JNkV1+J5TwHfr1l5wNKngCk+YQ4EHgnHTmGM0BxX8rJ8FtWuvF9ENwGyftkDrrjXS8miM5oe6vAIV"
    b"uladpY4DFHqqndQ2aiu1idpWbaR2ULvA9hh1sPqPulRdr55SL6nvVJ/KaslaVa2tNlBbo23WHmvZGq5XgW40Cbh+CioZNyoYXY0p"
    b"4AAeGaZRHLzUdHMnOE3EKgr6OAO8/xtIMWWQPpA1TiB+hIG67o8uR++iH9GCoISDoRMcxQTMgVcAHUsHTXuFh/CCRDWiOzGPWEfc"
    b"Id4TBpGLLAkodyWnkYvJzeQ58jz5jnxDBsgoKZIMpZJ2yiJRyiSDZIR8S74gL5GHyXXkTHII2ZSsSDJkjLhGbCbSiVpEUeInfhZf"
    b"iKfh+fA32Bb4/dxYJvjMjmg+9AFkokaQzc+BFuWwXkF3rm/+NLYY3QzEuKePgf4b1NZqvQCRJ6B2bdTc6ndlhzJRqaF4lC/yKXmF"
    b"3E9uIReRnbIufZBeSjekMzCOS0ely9IV6Yn0SwpJCXIxuak8Wl4mX5cDch6lg7JYua3Y1PrqEvW1mqCN0w5oDr0n8D7eaAmuymP2"
    b"BTRzWAugx9SCfBZFeqH70Xh47itYAXw4/hDPQwwjrhBO4M8O8hdZhBpJ7aC+U7nohvQsei99nyaYOOYPphvTjlnMpDOLmCOwPMYs"
    b"Z6Yxm5i2zAgmjUlmCjFP6Uf0Zro73Za2qA/UHqoTVYn6Ru4FBFPIT8QSohGhwbfpjnvwW/DbqdgdcPGV0cfgYCtBtt8L7pq3Tpl9"
    b"zBLmU1DENoal3wPnUk/36Pe1jVofrYyGag/VfeootbNaUqVVUbmmnFfWK+nKVKWz0l5pqVRU6vyu3dpKcZgNYPaD/ZOUOcoSOPOk"
    b"8lOJKXa1GiA1UV0EXeajKqupWkNtsrZVuwWamQKsnw59PUsnjDrGOHA9nw3LqGKOA+/60SQhJY63tlofLQdk5vHIEeQL4kXbgNs5"
    b"h2agbnCB48D1BcHpdMDH4Dvwn7iC1yR6g/5dAwbGQY/pDHzaQT4gf5JuqgjVkBpCjYMa3ktdBLw+UBKF0wSdQnthFoBlLtpBUzRK"
    b"Z1BfqevUCWotNYnqD5jmo8LkLbjPALIu8PIxsYHoQuQlPuPr4Hfd+HVsGmD7GXJAFVSAZF4LiUHXqWdlmLPNGuZLY4ZR2rgDLiaP"
    b"fk+bAv31tTpZLa/+UpYDhphyW54r15S98n1ps/SX9IeULP0UH4p7xEXiVLGb2ENsJNYTm4vVxY4w+ovzxYXiRfG1KInlpebSImBr"
    b"VKojT5Yvyx6lk/KfQoA2HFFdWm/tqZYKfQiDOnhg1DA3ml4r3fpl9QR/WwEyGgMe+gfWGLQ+GdT/G1ENurBKNqR2USGqJr2Mvkfn"
    b"YNoA7x4yUaY025qdyG5nj7Nv2R+sxHIcwbk5lsM4k/3OvmbPsZvZGWw7tjKLsi+Y7UxvphKTQR+kh9KJ9FdqJlUN0FsANf0TGFmb"
    b"eI7PxfMDZsMwEjsC6hgEF1safPZE6IV3QMdTzMvGMCMnIDZVL61naJu0zlqS9hLUrbtaWA0pl6Fz9FKqK7wSlu/Je+X18ih5iNxO"
    b"ri7XkwtCnRaV4+Uycl65hFxHrih3lnvIQ6HGV8vn5RdytpwIXG2jTAYO31YCSpKaBtzeqj5RUa0CdPd12kPgZA19qL5b/6a7wYfP"
    b"B4fPggefBJr9wyxv9bS2W98hUfdAloLrdUFGXoCeRxHsD3ifE9hnrDC4ukX4c1wHHo4ithBfCIqsT44Ah/MaVK8s1Y6aTB2hblIa"
    b"FU9XoHsBRmvp/+iL9Gf6K40yNFR9QSYXUxJquzCseZh4RqUj9Ef6An2MnkMPp/+kk2mcvkGtp4ZRRSmEOk1OImuTAeIosN5L3MVH"
    b"4QXwu+Ajk7Cz4B91SIrVkddQQ07rgNnA/GJMgv58VE/TM7WZWm7tJvQPQt2npCmqvFluImPyfqm/lF96LW4Re4sFRCV2PbYqNj7W"
    b"JFY2ljOmR6VoRvQDzC/RQBSN8bHisbRYv9iK2LlYdqyI2FXcJP4QC0uTpFtSDuDkA7mSskZRleHqAzVNO6Xl1/eAY19qOCFnc+Ad"
    b"dGsaEkYmoUF0CPjpLvh7vBlxmagEvSKOGk99purS22iLbsscZBSmMbucfcgmcg256dwx7iXH8rn42nxHvic/hR/FT+Un8/344XwD"
    b"vgpfgM/mvnBbubFcK85gP7CL2DTWze5lRjEJzDl6AqB3lmpLZQDfc5O3iG7EL/DtbvwY1hS69XhAbA1SHjlr9baC5kLIzJeMwQZm"
    b"7IKc5te2Q08W1cPQcZPVp8o8pbUSp7ySd8kj5NpykuyTbkp7pdnSMKmjVEOqACgmSB6Jk+ySQ/JKSVIhqZJUU+oqDZKmSXukI9Jn"
    b"yZQS5TZyb3mtfEf+KqcqDcHzXFHeKSXU9tDPX6mK2kCboR3VCMiJE8FPxvS6RrpxyeAgzy8yX5ge8I7brE9WKWQYcggxkcroDOjQ"
    b"GGSIJdhTLBfeBt8EvjAJHM+/xBsimWwBjvoOiUA9jqC2U+8onq5KD6NX0zfoAO1majBdmanMZuYU84LJYhDWy+ZmS0FNV2XrsbVg"
    b"WY0tweZhPazEZDB3mT3MEqYHU4txMm+AmUPpmrRBHaPSqYLUT3I1+QepEQugb//AR+Ml8MNYOyyCjkXzo5uRKsgjqxk4oKEmYi43"
    b"PMZBqPEbWivtozpeNZStSjHlljxYjkj7QQl/iBvFVFGPbYh1iBWK3Y7uj/aJVogmR18JT4RtwjJhrjBQmCr0FSYIc4TpwjnhhJAl"
    b"JEULR2dF10a/RSvHusSexFjg8XPRK62WwlJn+b1cQ7muVAEvWQ34mAaps53xzuhjauZ4qOl1SAH0EiToJ1gH8DPDoHaHkj6yJ/WT"
    b"akXfpasANjZ2IHufzc+N5+5ydr4zv5p/xHO2srZettm2jbbztnu2l7avtg+2t7Yntgu2fbZFtsG2hrYkWwZ/lB/H/8FHuL1cV87G"
    b"nWS7sTi7kanNvKb/oll6GVUcKrk6+YJoS3wFf5ANHcVC56KJ6CqkKHLQqmLdM1ubv4zxBmfsACf3EjJInHZa7QbVewLU0K08lqfL"
    b"DWRaviatBf6lSqz0UDwvLhWHiwPEqmIVsajoEnOJlOgQE0S7WBi2/xDbQn+ZKq4Rj0A/iYk5pTRpiLRBui2JUim5K2jmQ9mS64FT"
    b"Oq7oShnoWWdVUW2opUM+8kI97NJ/6qWNqcZlw2V2NreZYbO6NdN6aeVB+iEXIb00R7ehb9Fq2GTsEpYbbwF5LYyXIOZDHrGT7clF"
    b"5BcygepJbaZeU/no5sDCO7RO12J6MluZe4zAlGQbsOPZ1b97Thbr5HJwZbh6XBqg14brBqMJ15arwJWE/RE2mz3NroUOVZXNyb5l"
    b"tjHDmTzMT/pfuiltUjupNtB91pLlyfvEX5BuVuA58d1YDewk2gS9C77xtdXIeg7Y3jLaG9f0ZvoDrZb2DNzKQ+jNj+S/5CxQM6+0"
    b"SqwtPor9FcsVOxAdGvVErwpLhPKCXXgcWRaZHqkVKR1JiYTDVvhbOCushCPh5EjBSKPImMiKyMsIIjSCsx8IZaPjo++idWJrY4ni"
    b"RMB7tPRTGi8H5engj1aqlbRzWhdd1GcbZcwrZm+LhARbB32DjsO8gFwa1O8I0iKXUDnoLXRxZgdTkN3E8twM7gfXnD/II7Yeth22"
    b"gK2Svb/9P/szu2Qv4ijvaOXo5+jmGOXo7WgDo7Aj3iHYz9g32TvZc9szbctsbW0mv51vy2dxS7hC3Gm2BfuKGcBk02NoEVKORg4j"
    b"RWIw8QUfiD/AOoF3rIbeQ4qDNlawtoGv2WlUNq7olfV3WmstoM6GXHdRqa9E5HVyOVmSlkktQflOi0vEOqJb/BHbHVsC9Vg7Vjhm"
    b"RVXoIc+jj6MXo/ejN6MPoh+jX6N61BkrGGsQ6x6bGfsv9jCmx4qKncADXREVsYI0QjooBaQy8hj5nIxAYlyjfFBKq1PUm2pebZB2"
    b"XovXe+jndYfR0zhv2Mz+5jnQxsHWRSsFGYTcQlLQoegD1Ate8ToWB4n5KJ5A9CR2EDayGvTln2RO6h9qHzjB5vQo+i0t0zWZBVDr"
    b"OpPMNmKXsRvB46BcLq4D151byG3nDnGvYPg4lRM5mkd5jTO4LO4z95Q7zm3jZsNZDTgPl8VeYdPZ9qCXT5gNTF2GYE7SnegE+gD0"
    b"HgvcUHnyJtGKCII+WtgyzIatRnOiy5GcyErI08tMy/jbUPWBehbkwGeQ9G5Dh74JXeaq1FC6LbYWP8b6x5DYkmiR6AOht+AVzkb6"
    b"RYpFnoW3hfuHi4ad4Zehy6G9ofmhpaH00JzQytBG2H4RIsKp4V7h/8Lvw5Uj6ZFnkbqgoc7oxGhWdFLsR2yaSEuLpT8A4UEKB56o"
    b"hyZo+/RuhmZcM/tZScgbZBxaGfuJzcObEBnEcvCKr6g5dCHmANMJarQ/Z3H9eZkfYntoa2vfbGccgx3bHLSzunOs84LzhZN1FXNV"
    b"drWH0cnV2dXIVdWV26U4nzt3OIc6yzv9jl2Ojg7Tvttez/7BNtZm8Yt5N78SXOZ8FmNHMT/oFtC1C1EzySDRjDiAe/HB2DM0FV2I"
    b"CFZj64TpNscZ3/Q6+mnwNEtVTh2rGOAKJWmmhEtbxGLirdigGB47G+0aTYo+g77RXUgWhMjDyCao0KGRvpFukaaRrpF2kUGRvyPz"
    b"IicjdyNypIjQFPC5KFhCo+i06Kto7tiQ2M2YRxwh3hMLSnOhehvKB2WHMlb5qNRS94PnHq191eroe3WPMdz4YFQzN5i41cm6BCwc"
    b"ibxACqHpoIcFsXTsEZaEj8SP4wio/ULiE1EAMvIR0MOi4OnWUllUEt0SXOFp8IPlmM7AxIuMyBRjG7PTwIPfZ0U2nqvKdeEmcSu5"
    b"o9xN7j0X5TTOxSfyOfmifG6+IJ/CO3iW94MLusHtBM5246pzHPea3c32YcuwP+COXRgL7t+Z1sHvV6Jek0NJhVhOJBBboFvvgixz"
    b"AHr1LiQHstiKsyaaIrzPc72LflX7Qzun5lL3KsnKEjmPPEfKIW0Q48XTsVKx+9H+0Sxhs1BGeBlZEike8Yd3hDuFS4SzQ+dDa0ND"
    b"Qq1DVUP5QrlDHhj5Q0VDDUJdQ5NDB0PPQu5ws/CC8NdwocjcyPdIbeGskDO6PpoSWw4KsFesK72XRsm5lDPKIMjZV7V0vZQRMPYA"
    b"I4shP5BD4BzLQuY7SkwlK1MidYYezBSFRDKHq8S/5Sfbku1H7DUcjxzNnHecDV07XMlxw+MuxuV0p7mXuy+537hdHtZTwFPYw3m8"
    b"nnfua+517qbuQu4rcePj8sftdLVx3XK2cr52VHCctbvtY2wf+Dz8DO4W62B7Mqvoj1ROqi25iniI03h9LB09iWigjGPMK4amt9TX"
    b"ad/VRuoK8NU95QtSdWm7mE/cHcsLHGwQ/SDMFvIBTnMj1SNE5HZ4dXhYOA3q1h02Q0IoACMaQmCrCOztF54bPgfo5Ii0j8yJvI64"
    b"hE7CESFbaB3dGg1Ge4KuesUpkBebSjukOHme/EPurTxUqqqn1HzaWs0JqVPSh0Km7mjeh/580soP+dSGjkSz0FbYGawU/g8u4x2I"
    b"Y0Re4MBTsgg1hnoJyWQIfZwO0/WYMcxp6MV52V7sTPYU+5VFuNJcXW4AePAl3GHw4XdACZ9zGcC0H6CB77hPoIK3uSvcPm4L8G4i"
    b"15drylXkkjiE+8BeBvZOBN9ThmXYX8xhZiFwuwCj02foeXQrmqHfUAsgn3PUIXIkmZO8DKnURZzFe+E+bA1WCDsMqf8u0g3JsjqC"
    b"M+9lvjD6QPepr5/RErUtqqb8pfyEBHhFKiAtEp3ioBhgE30k9BDuRTpHvoZ7h+nw4lC50KvguGDF4NfArsCIQOVAjkDI/9n/1H/T"
    b"/9L/1i/6kwM1ApMChwJqoHlwa5APjQz9CvUPZ4YnRnhhr9Ac0s9/se5iHumDtFMepdRQE7Vf2mV9szHabG+VR+xoGL2D7cJnEh0g"
    b"5+H0I3oL04ctCuhs4NvbTNtue1PHR8ckp+Wc6aKBh1lxDd2b3Iinqmeu55LnhyeXt7S3ibeTt523i7eut6zX6f3hOesZ66nhyXL/"
    b"C4x9DKzUXFNcvGuIM9vR2rHXnmzvaTvNc3wDbhl7jyGZGvQIagP4HB1Pxv/EhqFLkBvWa9NmVjRa6ku1/eo3JY/SQF4u3RF5sVds"
    b"exSL9hDOR0pFNoQ94Q2hvKEjwfbBQGBHoFvAFgj4D/uX+Of4O/lH+gf6B/s3+9f7P/odgTKBtYErgYLB+cG7wY5Qv4XDx8LuyPFI"
    b"GeGU0BVUcjrwcZfYWvokzZbzK2eVbqqgLtcK65f0tsDCiaZi/mM5kFmQnNPRCDoMu4/VwLcBB3sQBwiLaA/Z4SuwsAe1A7oLT9cD"
    b"Jm6EfOKjE5lKTHdmIrOeucA8hTxoZ4uzzdmOoInL2f/YR+wLVmNdXF7Ih824IdxMYN+B3/z8ANyUoVeTfBxv5728k7fxNK9wfu4t"
    b"d4vbzy3lRnCNuPxcmL3Ezmf/ZF3sXWYmUwH842K6HHByBOWktpFlICmmEa/wTvhTrCd2D22O3kJKIcetRGuhSZh9jS+QqE9pJaD3"
    b"8OooxQfu+Z7UQjoJ3ucMaOPtaEXo012EN1DxbORguEP4R+i/UFpIC14KDgjWDuqB24G9gZGBXoG6gaKB4oGkQJ5ACUC6VWBoYGHg"
    b"WiASSA1ODp4JJoTGhe6GmoYPh0tGrkXKC++FkVEydi/WQywkZUlr5GlKdTVeQ/Tb+nVjh7nAmo/8hQ7FeuFtAdcGVH26KrjqgtAp"
    b"LP6n7Z79P8d0Z3tXjrjvcRvczT26Z7k3Nf5EfNmE/Qlc4qDEM4nRxDJJLZP+Svo7aWTS4KQmSSlJgcQNic0ShYSJCfaEGfHZ3u7e"
    b"XR7D3cA9PO6E67Ez6kh2JNur2aryf3CN2bJMNbo0lZMsQDA4i+GoYOlm2FB0TGe1/GpZpZ08RtokvowRsZbRlcLXSIPIRlC82SEz"
    b"uDCYFDwR6BDAA2f9E/x1/S5/wPfAd9Z31LfLdwz+PvSFfbS/un+Qf4P/uz8XYHQ+4AgODd4Olg2tCdHhceDBh0Q+RQYIP4TBUTM6"
    b"MRYvbhZLSo+llrIkz1NS1DtqYy2mLdKTjYdGMzNmLrXcyDWkNvoeHY35sCU4SSyDtDwX8slUSqGG0vfpBswaxmQ6s9tYnKsB3HrE"
    b"mVwaP5Bfy9/g3/GUzW0rZqthq25rZkuzNbDVg0RYzBZvQ2xZ/ENIfqv4sXwLvhRP8Z+5C9wibhBXCxxiCBi3jh3F1mcLsjHmIfio"
    b"dGD4H4yNCdK36A30DLo1nUo76BfUOVDGNpDaY+Q98Kt/kqnke0j0/QkLvwVZkcdvYy0xCV2OxqHHgJWHrKrgz/OZq4yYPki/oxXQ"
    b"lqiflMrKOvkj9KFl4otY9dj06EuhqpAOXbpReFsoR2hSMBYYHcjwT/Ez/s2+Bj5f9tbsPtlFstWsL1nXs65l3ci6mxXN4rPrZ8/L"
    b"vpKd6pvmC/jG+r/65wXig8eDY6GHZ4T3RoYJ3aMFY8kiJf2SIvJ75ZP6U/ugB4ygKVooSmI23E3Ek3FUAk0xFiOxz7i7/BbbOHtX"
    b"R5zzl3Obq0kc797oru156Wnn/extGn8hPnfC2ITbCUhi48ShiSsSTyceS3yQeClxX+L2xMGJzRPjEq8lzEsokHAvvm/8D+9Yb6an"
    b"s+eOO797UtxDV5yrlXOp45Q9y+aw5eWbcC3YHsxouh81kRxB9MVHYO3Q9sifVmWzplFcL6gVUZOV/HIRqahYG/g4QFgeOQI1WiDU"
    b"MXg4YPg7+5/4yvuuZDfJfpW1NKtElpB5JXNe5vTMnpl9M8dmpmcey3yZmZLVL+twVp7sSdla9iSf4tvkLxh4HZgZLBiKhTaEB0Uq"
    b"C37heXRlbIDYUGLkLPm0MlvtquXTQ/oJY6xZwcqyNiNNQBGXYan4RXDYT4gm5C2yNPhBk2pG7wUFLMOMhSTxnjGYfKB8rdlJ7AxQ"
    b"rO3sCvB1W9mV7A72H3YxO5sdxo5ju4AytmKrsbXYEmxR4JeXTQbX4mRt0HvtMONg6WJzQDopwOZlc0FPzgd6WhrWUtnccHYSqzMy"
    b"85O5Bd5zDTMVUnkpxs28pw/QU+kqNEtfoiZRValP5CayNplBrCOKEa/xvyDJ7MYKYzfR1ugLZAx06nSLsaabyeYiI8XYrifph7TC"
    b"2gG1hnpEaaTclZvLP6U+kiguhH59IFYz9iA6JkpGtwvNhc+RlZFqkffhzeE6YSN0BdxjnRAWuhHcFRwSbB4sF7QH0WA48DOQEQgG"
    b"xIAzWDKYFvw7uDv4DRRgaOhJqFh4fpiLjIqgwnwhPnot2jHmFu+I6VIHOVmRldfqCW2/vspYZi6yFiCr0DXYHvwQcYV8RL2ig0yQ"
    b"xXjahtgdjqhDcH50HY3b6e7pKe+Vvcvj2ye8T/grUUtsk/QkKTm5c/L25GPJn5I/Jz9Ovpu8JLl/cs7k80n9k76Ber5KKJOwJP6+"
    b"1+6t5unq/jtulmulc7Fjtj3d1o1vxZVmWSZGnSe3E3/jTbGaKIOEzc/GMf28tkn9Vzkgr5GuiE9j36Kp0TrCIsDBA97lc7B18FOg"
    b"SSACPbmwP9O33NfPV9HH+PTsD9kfs79m/8gmfSm+Or6xvm2+H75i/lH+O/484GZ+gpc5F6wU2h0qAX0jNXI10lh4LYyLorGtsVri"
    b"c3GqlCKflQcouLpPbQ+quE1vaGQaq83y1ntrKpKIXkZbYwJkPjdxkihLXiNbUGeo1vQJuiizlwkxw9mLLMuN4zZyEleab81v4nfx"
    b"r/koH+ZTbARUnsP2i/fzl/it/D98Q0gnGdxByC0lQft2sl1ZN3sJOJ2feUnPoivQmdS/VAsKpy6QE8hKpEqcIeYSLYj8hILfxo/h"
    b"8/FReB+8Fl4fL4MXwcvhufGysCyPN8Mb4j3wwZCj5+MLwEnsxA9B/RzFr8A1+2DMwafj3fAKeC78LXYEGwv89KGL0aroJ2QoYkOW"
    b"QwffYNrNuYakdwWtLKjNUn8olZTVchZo5SYxK9Y4tjuqCUOEG5HykX1hb3hLKCW0O9gw+CywIFAukOW/7P/bP8Df1F/R39Bfy98D"
    b"vs4ev+AvFZgZyAykBW8F64Ruh/qF1fDuSAeBiz4FBegrVgOnHpNfKhfVA9oqfYEx2fzL6o+0Qptg1fBCRC7SJLOoJ/R/zBK2K1cW"
    b"uvUF2z/2ig6fY52zrOudq3dcJG6K+5d7oOeup4j3H+89b2J8q/hp8fvi78R/ic+ID8V/i38afzF+cfzg+BLxv7y7vfW9Qc9Mj82z"
    b"3s2758Rlu5q4dkPiru4Yaz9g+8xbXAmuGtuG6U/3pcaSQ4jB+ACsFdoKqWqVNPMZrI5pQeWX/El6Lb6LvYv6BSnijlQMtw2tDF4L"
    b"2AN9/Id9JXzLsuOzD2VVyYplbs8cmNk0M3dmnsycmcUy22ZOzDyfiWd1z7qZVTn7YnZd33ffTH/pQDiwIzg11AhSDSe8A108F9sm"
    b"7pJmynOUsaCKPfRKRknTZX21niDL0P5YafwjvpOoS2aQcymO3kS7mOnAvTrQPT+zObh2wKgN3AlIHXche1yAXLKam8B1BpZh3FP2"
    b"X3YAKJufOcqMgDQdgVwzGhRMpy5Si6mWVD5KJM+Tm8lRZFOyCukgDSKDeEjcAa4fJPYS24mdxDZiD6wdJk4R54m7cOwt8YX4QUBs"
    b"IwwYOkGSIiwjxFfYe4O4QOwj5hDpRBuiApGb+IbfxTdAgqmHI/h9bDPWGiuAfUNXo/1QD/oQWY5URnTrgNXBymldNMeZxcz7xgKj"
    b"lPFeX66X1TO1pVplLVtdoFZVvyv/ACc/yjPkVPmFNEEqBg5+uJhfPB8bHcsROxedGk2MPgGtKynokZ2RfsDUH+HrkBu7gH66w1TY"
    b"H/oS+gYzFiLCxcPNw+nhq2El3CWyG9LkYuhLS6KO2I5YPzEg3pRmyNWVympYzdY+6eeN1+Y16ynyC/2O8YSHTKWa0O2Zsex0bhW/"
    b"FfLMPsdm53rX33F93DXAPz7wjo3PkXApoUri1cTUpClJb5K45LLJnZJbJjdLrpFsJD1NmpHkTrqUWCxxS4InoVH8fu8rj+yu6C4W"
    b"18SV5kx1VLXTNoV7zW5mFtONqSKkhp/HdqJ9kQZWQVPQs7Ub6nnllLxfuireiGVEuWhZYUJkf5gI9widDlYN7g1UCDzx9/Gn+B/5"
    b"5vl6+yr4knx2UEfK5/EV8v3pG+bb4fvqS4E0c9bvCUwJPA80C54NlgydAF08Ga4feRDpJ6jC8mjp2LPYCDFBuiL1kBMhv/RV82gX"
    b"tYl6QeOB8Y9Z3PpizUHKo1/QyVg5/Co+mHCQC8k61Gkqjf5B12A+MPVB2cpzf3GfuUrgD5/wIT7V1s82zLbLtsd22HbFtt220zbH"
    b"1sNW34bZXvDL+bo8xm/kmnPZ7HjoxVsgedyhK0HuaEbdJftD6uhP/AL9ovHxWA7sKOiWAtmpDiJam62/rWKWw/phHjcvmAvMjeZ6"
    b"c7F50zxm+kyvldeaaS0GBU9FGiFXkAykKroFvYlWw8ZgF7C8eBq+C3+HO4lOxChiP7D6I2H+ZrJJZBJPgcHpkHUY4hTeD373X6ws"
    b"dgAtje5BOGS69dKsaC43nuoV9DHaWdWl1lH+lT9IuaSJ4qmYNzYsekUoLyyLcJF/wggkyiKhh8H0YNGgGbgU2BRYApl7DoyNgReB"
    b"UKBecG7webBZaHuoePhQuFTkdaS/kBS9Fx0fayga4mNpuzxcaa8W1hx6UL9vXDBXWbORAWgaVhFnodrukpuoqXQdJpn9wG7g+vJO"
    b"2wPbaHu847KjCTjJoa5M16i413FN3UfcmKeXZ5fnp6ewt5V3sneD96D3nPeq96T3P+8y7wBvHS/rveqZ6inkue7u4/4VNwTUsYXr"
    b"gjPR2dNx2p5tK2Dryo/gNrMHmBP0I+hMN4lL+DZsBzoN+cvqZJYx8umW+kV5JB+VtorLY/9Epwv/RBaHN4euBN8HPIFm/kU+f3ad"
    b"7FNZFbLOZPbJRDJvZCzN6AOjRcbAjAUZBzKIzAaZBzKLZK3JqpZ9H3xjbegdzwP7gotC88KjI5OE9Ojs2AZxt3RJfqFkqbjuMoqa"
    b"Za2qSF20IlYezwkK9I3cTY2nyzEvmXmsh9vGFeZn8yqfZltse2EL2wrYy9or2evZ89qT7AHbWdtqW10bazvNd4QcvBFSyGu2J2sy"
    b"Mxgvs5UuTl+gGlDvyIEkRq4nyhDv8DHQaZ9i6VgaJqA30HloS7QKqiN+5D6yHzmGLELWIsuQOchOULIjyHnkEhz5hcShRdGyaH+0"
    b"L7oE3Y8eRX/BYKDrFoSM0gqy82RsFDYPW4LNx/7FlmELseXYTGwSjO5YJ6wZVhQrjpHQob+hh9Fd6DS0A9oYdaIy8ghZj8xE6iJ5"
    b"kKB10Fpi1bdc1jtzntndtJlXjXlGEeOXvkIvo/u06VpR7YnaVWXVtUqq8lBuJYekvyVO2vn7v8CtYz+j/0Sd0YtCayEWORipH3FF"
    b"Locnh7uBThLh76Grodehy6FPITPkCncHBf0QrhVZFUkBlcwbvRTtGcstvhD3SulyD6WDWl9rrrcxepvTrbXIVfQn5iVqk0OpbfRN"
    b"Rmfz8HVsQ+yjHSucq1yL45a5+3tae3PFP4lfk5A/8UJinaSNSfbkRslTkvcn70k+nPxvcm9QyudJw5PwpL8S3yaUShgcf8B72/PV"
    b"HY3LcGU47zv22xfa2vDFuUzmMD2eKk7K+D5sFFoNiZnPjRX6WK2TmqpUkhOlgmLVWOXoZGFJ5HG4aLhT6D245f8CDQOn/GP9cf6r"
    b"vq2+lpDuCvh4Xz6fDTJNE1DKPb7bPi84l41+JtA+cC5QNrg86A4tDJHhVeFk6Cc1hQfCoCgf2xb7UxTE1VJTOSBvVTqqlnpRG6bn"
    b"Nr4ZC8yGFgGcGInmxO5g8/HCxAdiLpmbekX1oVFmG5ODPQuaeICrwC/mGVtv2zGbx97Ivtx+2Z5l9zpyOqo6SjpSHfkdIfsv+yb7"
    b"IHt5+w3bUluS7SCk5qNcK+4YZJJNzCe6K70TMnAPcgmh4lXxGdgvNAWdjTy08lmrzQ9GN+OWXlG/p9XQPqtT1BT1o7JI6a5UUdyK"
    b"TcEUXimoNFBGKoeVqFJX3a1S2kRN0UbohLHMyG/eMrtZGLIXaQgJbBVWFn+BD4HaWkI6qSUUQQ+iH9A5mD7MRuY6kwnOQ4BkdJnZ"
    b"xHRkXMwZOo3+QP1JXSKLkKOIeziO18BGo8uQy9ZzM2jYjHi9vFZHbaeMledK+8HVG9EK0ZHCiQgd6Re+BbnmQrBxMBhYGGgOevHZ"
    b"/8x/zn/N/8Lv8xcOdArsCaDBHsG3wT9DH0KjINGcB40sGM2KHorNFrtKVeQc4Nqz1bfaXf2UcdzcYq1GFqNjsdF4F6IRWZlyA/Yv"
    b"mSPsAq4ZX9D21rbG3tYRdux0VnHdd/WKexHXzX3VXcyz2PMEXGRX7wLvJe8D7y+v3/vV+w40ciWoYyHvF88yT0nPfXdH94u4znEX"
    b"XSVcC5yPHaUcvexbbB/5MFeaqwXOcQo9iJpPziUm4suBleORUVZ7s6fRQK+tVVOLKaXlglIJsXSsSrSl0DUyK7wt9CjoDNYJrPH/"
    b"8NXznc4umH08q27W58w1mc0y82dqGd8zMjL8GXGZNTMnZN7PLJS1Nisxe3t2fV+2b69/ZKBusDjUJh9xCK5oyVgNwGGOvFl5qapa"
    b"XqODOdTagpxF72MCnkGYpEi9oF8yK9ihXEX+Lr/EZrOvtOd29He8dcQ705xznfOdu53b4e8UZwNngvOFY6ajouOxfbBdts204bZp"
    b"vMYN5L6yjdjjTDFmNnjGvtQdsgG5BzLJWpzHV2I2bCWaF92N1EdeWqOsFOuMOdjMBS5umdHccBjf9N36LL0XqFJhHdODWkh7rH3S"
    b"3mgvtKjm05x6Eb2SPlSfpp/UM3SH0cmYbTw0vGZLc5+Zbda31lrfrabIv4iEtEN3ozZQzrOYF++Pn8MZogMk7s+QE1qSC8iD5Csy"
    b"RmJUCpVIJVAOKkS+hX1/k2nQzU8SXQmEWAcqfgJLxfahudHpSMhKszabulHHWKN/0nJrI9R9SkiuKo+Tboq82C62NyoLnYTjkZTI"
    b"wrAamgG5e3WwSvB5YFWgaSAlYPlf+j/53/v9/gKBeoG1gaxA/eDjYL3Qj9DicKVInPBKuBa9EDssPpA+yrRaSxuuXzRIqx1yHGXB"
    b"Kz0ki9LzmGz2D36l7ZM90dnHNTNul/um56T3QvzahJ6JZZJuJPVN/p5cM2VLyoMUIQXL4Ut5nLIkpU7Ki+SOyXeSEpIGJC5NOBr/"
    b"wHvec9G9OW6Mq4PT7nhjW8PX4Rj2EN2HykvewRdjTVEW+WTuNeboI7UOakelq9xfWiQegERdMjpMeB6pHNkeLhs+GGoWigSXBjsA"
    b"G18HTgZmB8YGugWaBVoFGgc6BvoERgdWBvaCV1EDBYI9g/OCD4P2UMPQNugOVcJrwp/DHSJHI8nCRsEU5keZ2MxYQXGHWF/6KU2Q"
    b"yylPlJlqHS1bO6mPNMqYlnnRWox0QvNjQewcPodoRiaDNq6nuzAse5cdziXwl/kmtkzbX/af9iGOW47ywMwHzhyu+q6RriWuta4d"
    b"rhWu6a7OriKugHO9s6nzk2O4I2bvaX9hS7VN559wBJfGDmOW0aepa+RnwoeHMQyzwK+5LK9ZwCilN9C6qenKf/JbKa/UR7wUKxxb"
    b"ES0QPSx0FJKEV5GrkUORI+C/5EhdYZ2gCLOiXOw/SAMpUlR6IZ9UzqontXP6a+ObiSEF0PJYZ3wYMZFcSc2n/2GmsM25VD6TX2Gr"
    b"ZT9lr+D41/Hckegs7CzhzOf86TjmaOX4ZO9jP2NLsDXnR3Nr2WXMv/RsqjuZRhD4c3QD0tLKZT7Rl2td1AQlKF0Q18cWREcLf0fm"
    b"Qs5+FWSCXQIX/YX9x6BnZWcfzh6b3TW7TXbr7HHZ67NfZJfwTfEJvuH+kP/fQJngz+D+UO9wWiRJEIVo9EnstfhSuiP/VD6oQY02"
    b"ULOQVRypgLbGGuLdiZ5kW6ov3ZipzZblCHDoF2yzQRtR5ylnd1fEtSCOc892x9ytPPs8IU+qtyf4xn+9m2Eu8w72NvQmeO94FnpK"
    b"e+64h7i/xQ0Hx9jUdcuZ5BzheGbn7D1tW/nHXC6uATuROU4/oRiqNNmKmIFvx+6iAuJFalgDzAXGcf2bRml/qAOUpfIjSRUriONj"
    b"u6IxoaIwKfIqnBJOD30KVg+eC+QN7PCXg/fv4dOy92aPyi6V7cwOZX3M+pkVyHJn18qeAq6xsG+1L86/zV8j8BNSdb9QvXD+iE1w"
    b"AidziWWlNHmMslS9ogV1t9nCGoasQ29hL3GTYCgbncjoUI23uUV8Oxtu32av4jjtKOJc4vwE3OvgGuaa5VrmGuP6y1XdhbpeOkfD"
    b"V33gaOmQQSEDtjG2B3w7/hjn5RazL5jGzE5apP6iTpJ5yFnES/xPfAfmxGagH5FuyE2rsnXeLGoeMSoYR/Q0/ZHWWzPVVZBrvymL"
    b"lXqKJV+U58gd5BKyQ5akH9IX6ZsUkmi5KHi3OfINmVN6Qw7Lpa5QTfUfza4v1SsbV41+Zry1y+qHcOgBdDiG46fxfpALdpKlqLNU"
    b"a/oCXZPZA2/XjV3HvmApLidXnivLFeTs3Ad2L3henj3EVGGu0JXpTfCF2pO7CT+eD++BzUEPI6+tsJlgljAa6n208eoG5Yj8SrLE"
    b"3GK32JzoTcErNI+cDHPhkSERerMRWBwoHoj61/on+tv7S/ub+P/w9/Kv8h/3Fwz0D7wJDAm+CP4bqhAOhN9Flgmboktjc8Xr0mWZ"
    b"VGtrA/SXBmcNQV6gSfgq4hfZiD7BqGxvfqcty17G2dw1I26Be6FnobdjfOWEXwkzEvMlpSdlJ5VO/jN5UnKP5ObJOZPPJY1M+pLY"
    b"IfFMQmZ85fg0byfPYHf9uIauJGe2/YFtCt+B87L36d1URzKVQPFb6BlklTXLXGTM0rdBmv6hlFWGy9elytIKMT+oY6VYNLoo2iKa"
    b"N/pCuCWsESYIE8EldxVaCg2gI6QJnWG9ozBS6CWMEybD38XCJGGusFKYJmwRVghrhWPCduGm8FB4IxCQzqtHe0ZnQp6LRGvH5sce"
    b"x6qJC0VLHAVfd5QclOcq+dXT6mBId1f1dKO8KZvnrL+Rpmgc9gb7D/+LqExa5DlqJl0F3NZOthEncQv5AuAby4DK5HbMd/xylHPO"
    b"dh5z+py8K5ergiuvK49LB83cAerIO3c4yjvu2kvbD9loWwdwkO/YfGxDphs9j/qH3EBsxVdgm9GFyCxrpjnEGK4P1HqpE5QJ8krp"
    b"ovgGtLFP9LRQRlgRKRe5F54Y7hDOFS4UTg03BM1/HG4UuRZpKnDRw9ElsZFiO2m4PFhZpl7Q3uuFzbbWGuQ9asPbE+nkEeoN/Z1B"
    b"uAD3gb9oG24v57joqOk84fQ7K7oaga5Xc0Wcx8GDXHX84Rhvv2L7zAucxX5mntMbqL/IisRn7D+0KYJZp4wuekHtsbIBOlhFsXAM"
    b"izoFT6R4eEBoaTAaaBm44u/q/+Xb6Rvgq+4r5yvmq+Xr41vr++Sr6t/s9wa2BYoGXwanhsqE8ci5yHZhSrRLrItYWaorV1UqqM20"
    b"6noHozM430nICHQWNgefTiwkJ1Nj6L5MY7YkR/Ev+PW2nnbOccbRwfnZOcr1yfVn3IG4aFxt92D3Mvce914YC93D3dXcStypuJZx"
    b"omuuC3MtccYcPcBHJdvTbY95Bz+S280KoBDj6ZfgULqS1wgT74tfwzzYMjSA9EC+Wy2st2Zf85sx03AZ2/SW+jttrlZWu6LOVhPU"
    b"K8okcO935C6yJh2XKkhhMV1MFG/G6sek6PRoSvSa0FjQI8siVSKZ4YXhpmEjdC+0NDQ41DxUPPRHqCA47D6hCaHHIS3UNXwblPFi"
    b"pAIwdHa0SEyPHRWXSUPkhkodNa9WUI83HKbHsiwOlVA/9gW/SBwip1Ht6HzMK/CQFbkXXF/+F9/DdtNW1D7aftYesic5qjkaOto6"
    b"/nTUdBRzoI739p2QXorbX9kW2irYnvBjeZpfCx75EFuVvciUY87SRel1gME4MotoRRzGc+ITsJdoJUgLGVZja6MZMzobu/Q4fZh2"
    b"U60P+TVRWS4b0mYpRTor9hNR8XFsQax3rHGsTKxKrC6sLYo9iiWKY8UfYhspKI2RcyuvlYlqDy1ej+ifjK3mAfiyf6EDsFS8CqER"
    b"H8gLVD+6EfORmc+W4tZzpfnp/HtIBmmg5cNsI2wtbCm2H3w6X4TfC/1rKbCxLDOC3kbdJX0ERrjwAlhutDhSzCpgljYK6uW0ympt"
    b"cFYDpeXiidj3aOFod+FMxBYZFc4OdQtFg3OCJYI/AxsD4wItAlUCNWB0DswMHAlYgT+Dh4JFQ5tC5cOPwuMjlQVJeBQ9EFsPyXK1"
    b"fADcxg/NblQ0/7Z2IgJaAXLYDTJE1WbGs1u4X3zYlteR6sznSo1T496713lqezO8XeJfxRdI6J+wMmF1wpaEoQl1EyLx6fFJ8cO8"
    b"Lz25PHXdk+KmuOY6ZzkG2TvaKvA89wUy2yxqAFmNcON27AsSBL33GalGBX2W9kx1qjsUTV4p15BvSbukjlJ5qaiESx7JLeWX6khd"
    b"pdnSfumjRMDxgfJy+Z78UXYrJZWqSk+lvTJQGaD8qbRRikLijMjH5VVyRzlR9kkbpb5wlzfiAbGvmCqS4tXYgdiMWF8YDWNd4DuO"
    b"jO2MXYlRYhNxuaiJ7aVHUjO4cz9FVtapjTRBO6APMwqZonneSkd6oClYGLuO/030Ij3UR2oP3QTy9Um2D+fiV/LVbSds1ewn7YmO"
    b"eY7HjuLO/s5/QRVfOzVn2JntfOvcBqpZzpnhWObwOA7YPfYZoDwF+OHcv+wt5gMdpGTSTwTxx9g1dAsyxRpoljMK6ar6QXkjH5Nu"
    b"i9diT6NUNK8wIXItXCJ8KlQtpASPB1fCWBt8FnSGxoSE0JRwxUg48gBywMXYBxEFL5yuXtdyGn+bT61a6DosircnV1MZdDJbE+qp"
    b"ja2Dvbjji2Or0w0+N+hKiPszrmJc/riwa6armGux87ujkqOpfYhtGN+Uq8YizAVqLpmfeIWlo27kvtnDcOo31CFKbVkX38WuRvcL"
    b"1yK3wmaoQmhKMAQ+PuKfDf04zv/c99X31BfwFfGn+U/6Ff/QgBboFywQOhzqE64Q+RC5J6yKjokNExtKLeS6Sk21iVZPb210MntZ"
    b"I5Ax6BRsFijjHHIqNYwexNSB2qH5m/wuW3076jjkKOB87izr2uKKj6scty7uWNztuGDctbg7cWvi2sUVjjvi6u767mznfAv6sMj+"
    b"wRZv68sv466xGpPENKcnUOvI16CGlfF07ATqRHsi562y1gazAHilNCOgb9A76nl1SbunndV2amthrtEOa+e0y1qW9l2j9WQ9Ua+p"
    b"l9Cr6n/oOfX8elR7qx3TRmuNNEU9ovZQUXWXUk15KfeWBWm6xEobxELimViLWGZ0QbRyNEPYJowQKgsFBbtgRXIKOYV2wnzhglAq"
    b"OjYai46PBWLbxdJSlrRL7qhUVAX1hbZPn2EMM2tYqYiFfEQvYlPx3kQK+ZHcTtWiNXoJk589D33jEJfCj+Hf8vlsfW27bA9smi2n"
    b"vai9jr26vaq9oj3eztjfQiefZ6tj89ougUYW409zQ7gQm8662UkMzQyhH1O1qDnkL6IsMRQ/i/nQAmhXZLp12PxkmHo5vbM2Xb2k"
    b"ZMip8ijppJgijoz9jPaJZoEfKSfIkeuRA5E9MD9GKPArl4Vi0ZvRVjFOfCSulP6R+yuD1bHaBH2LccR8bumIF6uBtyP6Q9ebRA9l"
    b"erFlOIu7wLe0RW297dftBR21HWNhdHY0cYTtB+Edjtkq2ibz9zmay8c2Yf6kW1OtyZpEKp6Mycjn/8fROUDXtXVR+Jx9eI2kqf1q"
    b"2+2r8WrbNl5t27Zt27ad4tVpcHWMvf/1d9zRtEnbZGftueb8ZkdzQ+7g7fZ6a5I5zBir99ZmgTPukVMlQeoSOxo1I3Miv8PjwrnC"
    b"h0ITQhVDKGQCH35M08ARK4WGhfaF0oV7ht+Fu0SeRqZE08HJF0gVgOBjylP1uXZBv2U8A8ow7fSkAnjAQnSE+cp6+IJCd3G4Y5nz"
    b"kGub+5Rnk3eqr5c/S+BDYEJQjJsflxRXJX5E/CroLgvjB8fnAz8cGPdfsCk05zd+vz+Xr5i3nCej2+NKdZwTtwk9+cpcBvY/9Jje"
    b"T60n6/Fa+4z10vSZrYyDei59jVYR+uNqdYRaW20Mj57gatfVBK2XdkYrqM/XiT7S+AnZ8wJ255CV0R5q37Uz4MZ4ET6Mb+NP+Cm+"
    b"i4/iCbg5duKT9gBbtZZaf1mrzCLmeiNgbNYtbYHGa2PVbOoKpbzySR4L3mhIz6QT0ippi7Reuih9leLkXvIeOV6ZClOZq/q1Y1pH"
    b"nTNuGlPNulZ6+7t9Bi8l/agadE6koCfMPnYU14jPILwTdogdHH7nbfAbh3ubO4/njCe/d7XX6WviOwCuGPQ38bfy94aeU8tfxm/4"
    b"jvoG+0zvfK/b2x8oOp27tmusc6FjhbhZmAps1pD1MD/BHduRnPi2Nd+sYxjaI3WJ0k9uJVWK1Yt2gO52OxQfmpOWkHYsdVJqm9SW"
    b"qeNSd6e606amBULPQivCcyKLo1tj36ScyhQ1onU20syRNke2UiXA1VtyL/hG4mVH0NXZvdKzw3vct9zfLhAXXBwU4prHDYfe2Teu"
    b"RNznYPvgo0D6QHV/N18rb1VPnPuBc6ojl3iKr8vdZZqix1QT8sZuZ8WMeXpBLUlZJ/8rtY9Vg7P1D28IRdMqATfWTf2csj+ld0qr"
    b"lBYpzVLmpRxPMVP6pF5ObQSq7BPKF34YXhEZFC0Vyys5ZUXGSki1Nd5wm3mt4nY93Bma5Bx6BbD6SfYsd50/D91ll2Oec4Crkpv3"
    b"XPUM8cb5tvvy+9f5LX/TwPzA+cDzwKvAo8DewJhAqcBz/1B/iq+j7wbMuI1nnvuQ663zh0MTOZEW3LyDc7HpmUyoKF2b6kWW47t2"
    b"0O5p3Tb/BiLsaPDGRX2pPkzvovcHMtygv9a9RjfjgpHOnG9K0KmSrFb2G7shPoOLk7kkldSgJlG3qSTKBS6SQKejQ9QFaj5VlPpI"
    b"/iUxPAV/s5vb5y3BGmieNFijq75dY7WO4CtFlOVyBujkJaWf0G46xCrGEsAhc8WqxEbHDsQEqY/0Quomf5dnK6XURHWP1lMvafjM"
    b"N+Y1a709AvcgJagEOkafRRuYdmx2Lombz/8jJAtTxPyOrY5izgNOj2s+eGQp90L3RbfbU9bTwbPYs9xzzHPWsx86zhLPeE8nTyaP"
    b"4t7hbu12uZe5yrhOOvM69zp0sYN4UPjEF+T/4Yawq5jV6Ah9lNpLTuCN4D0rzSlw51O1mepGZZf8QmKkCrFV0ZRIz0gsPDvcIByA"
    b"1orCvnDj8MawHV4YyRp9Hd0dmyhNlacpm9RnGtabmmutJLsJ2URxqAOzh2X5csIocatjn/M6NNOpnibeH97ZPs3XwL/av89/2r/d"
    b"39ef13/KV9a3xfsbfL6hu6urq7ONo4qYTghxR9gJTHWkUw/IVNzYzmf9Mt7rZ7Sd6gXlkPwWWKJQbFH0RaR65E64ajgUWh5qGCoY"
    b"ktMiacnwI1uoPDjljZA3PDn8JdwNOvToaM7Yzdh4qaqMlPfKSXWjNg/oYro51VoOtHucvKJ+0l6mKFubG8JPEzaIxx2nnNdcZ917"
    b"PAu93XwF/B/8MwK+4JKgHqweNztuS9z+uF1xg+Mqx30M9gmmBCoFFvmvQ1LLnu/ut65zzlmOzmKCkMitZxsymdETaiMZg2vZ1awS"
    b"Zlmjuz5de6YWV9crJZXH8mK5j9xM7iSPko/IqtxaeaDUgZ47Tsurf9WXGF3NLFaidQh4Iid5An0/C72KzoFWov9QLWYgs5I5xmxk"
    b"1jC9mXzMf2g4cqGZtER1pg4SltTBs+07lmFWMocbh3VFq6QtVn8pTZQrQP9PpP5SdulVbG9sCShyXmxd7HKMl/6Wdkp+eZKcTtmo"
    b"VFcldT3004KGYrw1t1uL7KG4IexDZtqJJPSIucwu50byzYSMoiIedYx2lnd9cK1xF/Pc8XT1vvR29F335fJP8p/3m/5sgQqB2oHy"
    b"gXyBmP+Sf4Cf8a/30b4h3suekLuwu6SrsrOiwy1G+SNcbzY3c4buTKl4qp3D2m9U1j+ro5V88tfYxuikSM9wp9CUtB2pUkq3lPfJ"
    b"C5MbJ5dOrpc8IPlqcsmU6ylTUpum1Qt1An98FS0j7ZPLqY+0UUZB66O9hXSk45ln7Cg+K9xpQci6kKeQr7X/n0B5uMtlcRnjB8Zv"
    b"jT8Zvym+d7w3fnFcOFg+2CrQzd/cl92b7F7iKuy8JlYQLnJF2PUoQI8nCrR+2ZitZ9eeKrPl9lLFWLFojUj78MbQb2gr71L7pOaE"
    b"Vn015RqcKjklR2rv1LupJdNOpdUMfQktDteN+KOJ0QuxDdJc2JoR6iRtgj7T2GBusi7a9/E7YlKEzsQUYAtxf8PulBNLOhKcnOuj"
    b"a797nKeQ9713vI/yz/Wn+esF1gcuBdICSuBL4F1gSaBFwPCP8HP+Nr79XtXj9VR313TVcNZxZBX9wk/uLLue6Ylq0tkoEyfZ76y3"
    b"ZpLhMEroE7SHahn1htJIcSsv5L3yOfmk/FsurgxVFKW7GlG3aOV02rgKW9LdKmIzOBHvJsOoCnQyvRZVYi4zddgDLGYbcv25edxc"
    b"ePkPZ7P72WrsWaYEMxu9oTPSDalxZC0+bz+xfpusmQlaX3dtufpI8Sm95TtSJelyrG2Mil2NroyOjk6Izogeiv6OFoytj9mxaVJW"
    b"ONEAJaP6Tj2tjdF7Gn+bOa0EO2b/wA/JSWojsHUXpgTr5p5z6/hugku8K/ZxiM59zgKuy66S7j3ubJ6hnkRPDm9/IO0XXo8vu6+C"
    b"r7avjK+8z+VL9Z7z9vYW8p7xNPEkuiu4j7ksZ0XnTMdq8YzwgD/JnWM3MANQW9pDvcH77AZWHvOtvkgbpeZQPLIaexCNRlLCCeFe"
    b"oQ1pudK2pFZL9aZ+SPmRglPKpq6BtN6b1jlUMpwrUiDaMDZLeiaXUHdoGY3dZhn7Bu5JpdBzmAA3l/eJPR3XnIw7l6e2t5Avzv/E"
    b"3zugBeoGVwaPBPcG1wRrBpXAIMi7ov7avrHeQZ727iYu2/FOnC0U5FPY4UwBdIfqAiRx3pps1jY4Pao+UR7IiVJqLGesS/RgJGNk"
    b"YTh9+EKoV6hYiA/9SktJS0vzhiqHBoeuh4Lh8eFwuG8ER+ZHy8Q+x5ZLXeQsiq28UE9Bj15qbDRXQBadwEfIO+o7jVEBtjDXkR8g"
    b"jBM3OpY7d7jWuad7Rnmr+/z+e/4BATY4Pfg7WCNuctz6uONxa+KGxlX8838ibgf8gX7+Ab4l3nnQnxu7Yo7T4iAhxh1iizN36CFU"
    b"FO+x/4GO+EhfpU1TpyuL5KuSKPWI/Y5OjZaJZozS0azRJtGlUXdsciyX9E5aLk9VOqqdtD56b2ORuco6YT/FL0mI+kp/QLeZpWxn"
    b"DvGb+ZzCVOGNwIu5xDyiKL4Q5gq5hJ18Br4/d5pNYbxMKVSOrkvVJZVwbbukVdGsYlTVu2pD1B3KWzmLPEVKjPWNhaKrou2jCVF/"
    b"VIk4ouWiLaLnonRseIyShklF5VvyJGjavGZoD/XDxjFzvrXano+nkKXUJHo2msmMYSdxA/kuQguxtCOr03TedW1xd/Nk9r7xDvdl"
    b"8u/15wrsC5BAl+CB4NOgM84d54nDwWvBZcHiwevglRv9su8vX21vM081d05XkmOrWEf4wHVlE1ET+iDJhAdZ94xi+lTVkLtJn6Jj"
    b"Ilz4ftqC1BEpk5IX/P6cVDbpyq/hv0r/qv6r2a+tv+KTNiYN/l0luVnKuNTTaWXDWyNNYkg+q+zTRhpDrF64HtUMFWTT85JwwDHc"
    b"hTzzvbqvbGBQcGBcg/hAuvXp3AmtE3ol9E4onnAvXad0u+K/xXFxPwPv/Qt8pbzv3dVdDx0Fxcl8iM3HLKK/kBJ4n8WYc/Q4bYfS"
    b"WY6TwtEPkU9hJlw6ND8tljo2NWPq45SdKQtTlgI9vk/JmTohNSW1bxoKbQg1D6eLvI5cjq6IzZFmyMOVhepMbbN+3rhkqpZt5yHN"
    b"qJb0crSeOc1+5l7xRNBFxUGcb12P3ds8g71lfR99c/3xgTUBJtghuCt4PxgOJgVfwh51DPqDiwNMYIB/o++9N+wJu9NcN50bHd3F"
    b"DMIdbjAbYA7TTak0vMquZWnQDBdpw9S+ynB5hfQslhfop1D0QWQTtK8ZkYuRUKQN9P3OsULSJ+mqfEPZo77Tvumi2dhqb+8HT0qh"
    b"CqGcTHW2DBfgDX6L0Ep8L9Zx7HU8dRiOiOO5Y4ujiuONWFvcLqTwCXwVrgZbhymPMtEs9Q6fsVdYQ6EtVdfLamXVRkoPeb30NVY8"
    b"diiaN3orMi1SOVI8kiNSElhsRUSGczyL9opZsaNSf7mMIqg/IO1O68eNLeY2a5O9DG8mc6kF9EzUm+nPVufy817hmXBcHAYNNepc"
    b"5arn/uYe63F753kF31hfoq8CJMpNPxvIH/g70C5QJ1AtkCWQCHxW1f/J1xM4uxx0mX3uh66Hzs+O4+IG6Ho+7iXTEbH0YuLEuyyX"
    b"uVnPoa1X6sg3Y1OipSKpoR9pV8AP+ZQqyWd/F/ydmLQ3aW7S4aQ3SZV+X/3dPrlESiA1W1qz0LywHhka06SDSlMtwUgyd9gLSAs6"
    b"M6Oxa/j2ouwY6DLc5aGV7vYvDswOFom7F1c7flL8+fgD8Uvim8a/iesUtz34CXIv5PvPu9PT1x10HXDUEq/zjblbTF10l6pD3tnd"
    b"Ld48DJlTVkWKLikxLlYxOiByP1wqfCTUDGjxatrytGlpM9OWpt0AaqwR2hSyQzPCOLw6UiH6Mbo51k7KL1vyW+W6ulfbpa83Npt7"
    b"rYP2XfycpFEelI2pzbYHDlohbBdPOa47b7quQJNe6f3XV8Mf8+8PlAteCJaNGxN3H9p0WpwM3jgpLkfc8mAg2Cgwzb/Tt+qPL/pd"
    b"tx0dxF/8CO4/pgN6SJUgx+1s1hajnH5eHa8UkzEkZHIkf6QHeHnH0Ne0m2kH4UGFSoeuhtqHzXA0cjX6OoaldMoY9YQWNGaZL63m"
    b"+Bjx0CPRCUZnC/IVhdpiMYfuOOGs7Trnyuiu7+7l7gj0leKaCLnXybnB8UT8JHznX3HH2AVMc5RAvyRLcEPbbb00NgIldFKbKB3l"
    b"PtL62Oto/uimSELkfHhwuGw4TzhjuEy4a3gzTKxPJDkyKZo39ja2WRopN1RqqEW1InpFo6zZ1upuj8NbyW7qDf0TYSY/l5OvLzQW"
    b"6zt6Omu6artLe4gn5j3kG+wvF7gVGBzEwV5x3+JKAJcdjz8XfzP+SvyU+FbxsbhRcXRcbdjmC/7TviveJZ7mbo9rjSOPuJaX2WbM"
    b"Gvo58eOa1jDjoPZJySYPjV2MFAvvTiuXmpq87/fGpK2/7vzM93Ppjyo/xB+R77l+dPvx9sf0n9V+VUlq+Xt+spEyPC0u/DqyMbZI"
    b"nqVO07eYu+0r5CP9nknlPggXHatdNTw/vV395wNWkI3H8efStU54miCmL50+a/pvCYsT1HTt0k2Onxs3NVgtwPjXeLN6NrsURzfx"
    b"IK/C2ebTv0kVvNKKN8frfu2o0kwuKuFoLBIfyRseE3qT9ndacur81OaptVILpjZMHZm6LzWYNigtlDYjlD78Ijw30iJaIiZKtpQq"
    b"/1LCahS6dHqzgFXX7oTHkjXUYfo++sHIrIfPKGQRCzoyOQMu2v3MfcYzxlvMl+Ib6fcH5gW+BxoHJ0Li3A2eALoYGswWvBWoGjgM"
    b"PF7O1xPooq+7mSuH85e4XqjJf2dHMy60isoBSqxufTKm6SU0BZrDfmlX7FQ0NVI0sj6cO3wVOtew0MTQ/tDvULfwf+HZkebRXLHc"
    b"sDG1lMnqMY01Wpm7LRfuCLTGQV+Zzu7kLvKXhV3ieEdR5wNnXddO1y8Xgob6y7XH1dr1zFnnz78lGwIUdS7MXmB2oD50QQqRQ/Zc"
    b"q5WZ0Uin/1RTFKQwcktpVuxjtH/0WWRxpE5EgEmawFtdI4sgrQdFQ9E1sfxSVDoqj1H6qBW04npe6NfZLJ8dhzMTN5WJ9iCGYdmv"
    b"7HvuEr9cGC9WcXicL51TXdXdX9yTgRk3A5Ft9XH+4dBheMjkXoGFgVXA2bMCbQJ5A5/94/0J/kU+1dsCNviq+70r0fnecUKcL7Tg"
    b"TfYQUwc9p/qRL3ZfK9nooYfVkQov7401inoi70Jn086k3kpRkmuBKiv8/pF0NGl30sUkKanN71e/xyTXScmTWiytbWh+OBzpGHsr"
    b"TVaC2j19rlnK5slZaiAqyV7megthsTF4jerO4a3qC/ol/7pAxuDq4K1gNKgGrweXB3MENwb4QHn/MODG4Z6e7sIuynlS7CVk4o+x"
    b"PRgG7QBuZPBda6nZzvhHLw7u2FjpJx+UYrGWsYdAXFJkY6RvpFokZ6RIpHCkRWRW5EQkQ7Rb9EG0aexkrL30XRotV4amukrtoAm6"
    b"rB8y5ppjrQp2FZyB6ISlX9Dv0ENmP3ueW8rPESaKdR21nC7Xe9cpdxuY7UVvHd8vXy3/Cb87UCowPDAqMDjQLZAx8Aamnerr7jvg"
    b"TfYEPNnc2VyM86O4Q+jKB7jjTFsUouaRvEC7fUy3cU1bpLZWasnVpAaxSdFzkayRTeGS4VjoDnhiIrT+/uG34QGRjNG30LX2gw4e"
    b"KKnqX3oHY5P53cqDB5M9VCLtYf5iy3El+QQhTdgGSf3IUcY513nO+dj50LnbOdCZzrnJkdExSrwIeszEF+eqsaWZYignzVE6/mw/"
    b"sO6YF42b+lstrOZWOyl7ZZ88SXJIO2PNY9ljSvRXNBplYhVio2K3Y2WkTVIR+YrcRklQr6hztE56NsNjfjNvWdfs1X/+d3JveiCq"
    b"x1Rki3I0r/GPIE9mOmo6E1wvXTPdNTwfPBO9cb7FvnT+cf63/lKBvoEdgauBO4HngcOw2c0DYf9Kv9c/DgjH463jaeNu5WrqzOqI"
    b"CXshCzVmHHLTC4hlT7GSjN76F7W9EpbGx/JG34XXh2amDUmdlXI8Wfo94HdS0oakoUltkyaDJuN/b/tdMdmfoqeYqSVC/cJ3IjVi"
    b"l6VuCqed0EebRW0Jn6D6ob/Yq1wX4ZfYzHneFXNn9Rb3uf2//PMDnuDU4LHg++ArYLEB0GJGBB5BNy0BzFjc43MnOvc4mokO4QBX"
    b"m1XQLLoE9QVPt5taXjNRf6qdUK8p/8lYaiptjrFAYNmizyPrgHu6RtpEBkTWR25GskQHR19E28TuxfpJlLxR7qKw6gN1jdZKL29w"
    b"5keY6lp7Bu5DalEl6QCKonfMcXYpN5ivJPjFt+IaRwen4Drlau3+AZ06ydPDe83L+zr6Rvo2+I74FvgW+er7GN9Vb1HvfU8Bz1D3"
    b"S9cnZ4Izr8Ml5hF+cU/ZY0x71ICWyBm8zq5oFTUN/aH2VT0HZ3bJuaU1sa/RntFgdAc40ZBI/8iuyN1I8eiuaA7IxRlSS7makhNy"
    b"sZxezxhszrUO269wlPjp3KgAk4cNcMncSb6PwIgLRFn8xzHbsd1x4M/XoOR13BD/EW8L2YWh/FHuOUsYP5MBFYI+n5/kxznt8lZZ"
    b"s4UxRl8NJ8mqTlTS5A4ykZbDDPPATtsxJZYgNZMmSD+lyvJhubpyWumvCtoxbaqe32DNx+ZSa7L9N85BKOompMkYVIfJwX5g93P9"
    b"+RzCB2GmWMrxwjHIKboWuDK4l7lpzxjPPU9h70To1bY3va8iTK+Wr42vNMwt2TvdW937wdPY88Nd2r0YZmc7yjmqiLWEWnw2zsU+"
    b"R1vonlQ68taebFU20/SNWn81s6JKj2P7o2cjB8JvQr5QvbTbqcVTX6SsTGmZ0i2le8qKlHBKvdSk1BlpdaBVp4uUBReaISXK2dTl"
    b"mqH3NqNWa/yRNKdPoCLsCO4uL4g5HHWdpVxZ3RH3Ek857y4v9jbwdfIN8LX0ZfA99/b1fvO08Gx3f3QluAo4KznqisWEknwGTmUk"
    b"dJ2+QB0gi/BOe7m1z3xifNFL6r2082phdb6SRzkkt5QT5IfScWmZNAfmu1G6I6VKheXh8iU5pzJeiSk91c/qMC1VW6xnN84YA01i"
    b"nrP62j78Bk8n1SmBPkNPgyQ0mZvsdK4cj/mDQmcxo+Ooo7NTdo5zBd3j3RJ45GaP7Envrett623obewNeH961njyee6587vXudKc"
    b"GZ3dHf3EKcICvh83kK3BZEI0fZ1swWPsOlYx02/YGtI4NbfSWp4nJceaxZ5Ex0azR63I50hixB0tDn1ajQ6OZZWOSNPl5kpe0KNX"
    b"z2MUNotBj2mCR5B/qcH0JNSIqcs6uWvcLN7iNwqGUF/cIm4Xn4lnxGXiSJERrwqVhYN8Ib4nd5uVmbxMNzSA3kEdIY+xaTPQprqY"
    b"q4xvenp9lvZJbap+VXoqCcp9eZ48CGbYSO4hT5R3yzG5lLJa4dWBoMZpWjb9od7JKGA+MRdaXWwnTsV74CxNaQ79RjuZ4WxtTuYe"
    b"8GOFCmJUXO5o4vzgnO1KcK91l/As8SR4B3uve/8CHa7y7fGd87317fYd9Q31FfKZ3gHezN4ZnvfuJu4+rmPOW45r4lthH7+W683m"
    b"YVLpFVRDkmKvtSqZH2F/SqqUclaaFhsfrR/pA2y2Ko2kVk19kjIgxZlCp7xLVpJLpQxJUVJGp+ZOk9PuhR6HP0eEWG1pmZyqtNTu"
    b"65XMS1ZFfJSUptcjke3J7eXDgs+R15nfRblfu6d6vN6l3o/ebHDOcr4CvjTvcmhX2zxuT3f3fOilLxyJ4i/hAX+L28fOZcaj5nQN"
    b"qhjJjHPZOazS0A4n6Rc0UeuqPlaaK2/lmXJZWZESpZPSWemm9FQKyGXkaXKinEfZq4jqAjWbtkyrDTMdDDM9aU628tqP7C24MkHU"
    b"VcibkugzWsq0YDV2D9eJl/lNQjXxjtjP8cPR25kKPeGCy+du4d7vvuXG7niPx5PDE3G/cm+D7sC557jSuRY6vznqO6aKV6DNIj4X"
    b"l5MtxORF6el0lIVlO9n6ZP4wfuq6llGrpo5TbslZ5MVSOmlHrEssS0yLmpCOBeHXu2L5YJMKy0/koUpr1alJ2i/9nPHUPGkdsi/g"
    b"1WQzNYVui6oxCjT/HlyEm8An8zWFBcJl4TE40x1hrTBYcAnH+Or8bi4/N5K9xWRg/kZz6aPUO5KOFMeD7E3WYzOH2dk4rWfVp2mC"
    b"tljNp75VFiudlepKQaUYvOykrFGe/3lWnmS1r/ZLG657jF1GY1MHeu0IxPgQzyK1KZM6TQ+HxveRmQUp/QVaXxbhlFBVfCO2dLx2"
    b"tHFecpZ0rXAl//nqmUdur6eCp7Nnmme2Z4VnqWe4p4eniEdyn4GJYtccF+ua5nztqOAYLx4TknmTy8blYrMyuWGPVfIWH7W3WEPM"
    b"NkYVPbOWXmUVt5xFKhHrE10fiYRbhe+FeoRQ6E7atrQladuhC4qhbqGXwN905GpkVnRIrIfURZ6qLFWvaaae0xxmbbE/4DxUdXo6"
    b"2sAcYO9xB/jdwlixhENyjHRyrqGu4y7WHe/O687x/38Zgdc9rs3OOOcUUGIhcYCwn3/NcVwptgEzAa0Fb5SJn7TBi+2HVnHrXzPZ"
    b"aGs81AfqIW2X1lJzAwkdVQ+qG9Sl6hn1uPpbjdcqaCu061p2fbx+R69ubDCC5nyY63TLsmaAK67E+cgJUo96Tw2HLd+MyjF3mX6s"
    b"wi7icvH7+RrCFeEf8ZZY0XHa4XNOASpLcPV3TXPddr1wvXHJrvOg0amuIjDNUc6cwGpRcYK4U7D58nx9biE7g9mOjtBbqIvgjMfs"
    b"43/c/Jaualm16upm5bXcQL4mVZEiscWxnrGascKxhrGOsU2xUKyGdF+qK3+R1yh/q0Htm3ZU32FMN/tave1quATJQv2gntNLUUMm"
    b"wG5k/wZ/zM2v5J/yolBaKCuUE3IIqfxRvg/c6XIuPTeRtZiGzDbEodL0Uuo5cZL+eKMtW42tdWbAHGKk6qN0U9uh1dZY7T7MbZ46"
    b"Qp2kzld3qomqQ2uj7daINlR/o7c1Eo0upmHOs/LDDvfHGcl10pfKQd+gRwA53GYmsbngJCN4Ttgn/C3eF/s6PjsGO386W7qeunK7"
    b"F7g/uLN4Bnjme654Xns+eiKeB54boMrGniyeHe7m7meuCq6LzpijoWOWuE54zt/hXrAvmANoLz2WakFKYsV6YW4HumirlVPzKJnl"
    b"7FKxWMvozMiDcKHwqlDe0PW0iWlt0iqnNUobmLYrjQ0NCtmhjeEWkdxRFFNjuuRXCqpttAX6BYOzytuj8BnyicqEyjIN2c5cI766"
    b"EBRfi3MdGYG5OVcX1wbXCTj1Kdc6V1+X23XBWcV51lHEMVF8LWQQmvPzuOPsJ4ZlioA3TqQOkUScBXewd1nE7GQ+NGqDGrvqrH5S"
    b"G6bV0DJovKarlhrQ/tLaalO1q1pQb6xf0gPGSMM0mphfzfbWA2uE/d4ej51kGinz52t4vtIdkMjMYNKzh9jc3CWuDH8ayHGn8Jc4"
    b"S0wTmzk2O1ToCSOce533nClO3Wk5FUiis875znpO07HDUdxxVawgbhO8Qmt+D/eLjWebMH3RIvoAdZ58xEk2b+e0ypv9jLn6HThf"
    b"E/W44lNWyunlE9IgKRv0h5+xHzGXlEEaCJThktfKjLJHaaymqle1f4Ea85hp5jvwxtm4PylJcfR9ejJszUumNyuzXbhbXDa+KT+f"
    b"38Rv4Xfw/8Kvffwxrif3nR3GhpgmzA2UAQ2n71Px1GByCvtwL/u8lc+aZSJzvEH0DXpRPUnbqHXX6oJrZ4MfObUWWh/tsCZrJfRd"
    b"uqb3M0JGSzjBKEuzttuF8B2gBYvso+rTb+j5KD1zhGnNvmD/5TA3jg8KUwQkThI/ix0cJx3pnP86LzgDrkbAkNdcP13x7tzu8u6/"
    b"3aXcRd1u90/XWde/rqKuF84hwItTHDGxnXhGoIQG/GRuD/uS+Y4I7aQdVAIRsccWLdtwGkhPp+VRKygD5SXSu1heaIF2ZFgkLnIh"
    b"PCrcKVwhXD/cPTw3/CVcLLIvUjp6LTopVlKi5a/yDeWiela7oN80Xpn/WSGb+v93CaNN+id6y2wEfizM3+aHC9+FTuI10RRrOjo5"
    b"+jmGwG7kd6SJm8S64kehl/Cd78Bf5gpyM9i3THlmCnpPl6CnUN9JVbITx+GZwD9zrCzWIdCkAzriSqOZUdnIZ/BGDsMPPzcz2hlb"
    b"jBuGbTQ1p4AKC1lTrGSrnH3QFvFwnIRrkzukMLWFyk5PoUU0HP1AfZj7sC3n2PzcZo7lR/Hv+GrCZkEXmokbxFSxgKOvY73jvOO3"
    b"I+JATt75CzL8sGMynPmXuE0sAZOsLezgM/BDuLOsi60MXLGHfkgZkI+VcCd7orUTnJEyyuuTtJtqLnW2IgNFuOXT0hCphJRJIjGH"
    b"lF2qIc2THknl5J3AuZeU+iqtHdF66pVBDw/NTVZnuy7G+DFZBzkjom2oCvMK6PEGm4Mbwp3mPnKI9/Iir3JPuA1cR87J7WfrsQ+Y"
    b"lsxTVBGdoRPoqVSE1CZXcU68yI63R1lea7mZxXxmdDfyAENs15fpvfSOejf4MVVfB0nCGtWM5cYXo5a514y3FlkE0kTA83FWspOU"
    b"o+5S7eg02Isgs50py15mG3NvuTb8T76D8FZoK54TKzhWQfp1dW5wYmdl1yDXRdd9l+XK7Pa5i7kDbtuV5trhmuIq4XrsnO7EjjkO"
    b"1tEeupcb1LiEO8C+gZag0eloH+UHMuPsgOU2GSOzngDs2FIZJB+XfsUqxnZGndENkRKRd+Gd4dHhPuGB4ZnhE2EcbhO5HmkafR9d"
    b"EKsnITlZvqIcVI9qq/WDxn5zl3XdPoTPkzPUSnol6sKUZBG3kWvNf+TbCq+EbOIIcad4WXwn3hbPi0vEFmI68YjQRvjEd+G/cbW5"
    b"82xmdiTzGRVCS+kQVYM6SYJkKqbxEJtYi61s1hNzlFnUpMyrxm6Y3ShjljEdfr5qPDf8Zj1zjPnCDFp9rYdWRnuunQw94DYuQraR"
    b"OGomhalB9C+6NbqPajD7oKcugITuD3lTkl/Ef+PrC4uFn0IJcYB4EnY9wVHN0dox1jHBMdMxFXTZzlHQYYrXxWFiPvEanPYH3wmI"
    b"ohq3gdWZGsxC9JjmgXGHkh34FWxNZWuAuc9I1gvqs7UXamX1lJJduSI3k2PSbWm01EtqBzocKc2QLkgJchNgxqrKKaWr+kVdq9XT"
    b"Q/oNY6hZ1eLtC/Yy/DdQ7hmqDe1ES1FeZifjZaeCHhO4+lwfbgE3lZvJ9eMqc/HcdXh7LvYi04Z5jfqiRLoj/QZmd5uUJEdxCbzH"
    b"rmxfsTpYqrnObGEy5ksgmLHGAOMfo4PRCX5ebxw1IkYxs495y/Rbg613Vhn7sJ0NL8JBMoNw1ByKomfTLJqKWGYSozIj2d9sW+4F"
    b"V57fyacTesOt5hfHwI0GoONvc7xyZHKWcvZ3Tvvz3IzbncdBoTOdw+FtQWgt4x3FHBfEruA/7SGji/Mruf/YYuwgZjecmqaLUw3I"
    b"ELzA3mHdN78abqOE3k1boz6HzjpQToSpXQS6+RzdG+0ULQQPNlokWiM6IPogysZmxpTYKCmvfFgepRQGZnugzddHAv3msYL2f/ZN"
    b"vIb0pErRSfR21ID5wYyFnBnEPeRy8v34FfwV/jH/BOhnL7+Ab8s7+adcf87PHYFzPWJqM/dQK3SDbgF504R6SzqRKJ6G/8KX7OF2"
    b"dvultd/qbDW0ckJy+/7/9UyWaDmtRlYta6F1BuZYxW5tn7GJXQnvx19wY7KVaKQXdZj6ix5Jf6BropXIw7QF8snDjmGT2WLcWi4V"
    b"pvr/5wMuJYwSjgoU6K2PuFQ8IiaK38DHKYcsxqC9nhDni/+IAfESuLggLOWzwhz5P197W5AZgS6BGitR0+Duf9sF7ZbWJrjx9MZg"
    b"/biWXpug/lSGKDF5oVxBTpFOS8ukUfCYJq2H5iXKHeSzcg5lu5JdPau21GLaIb2pkc58aE61mtm6fRlyMgP1jOpGI7QY8cxcmGQt"
    b"djl7n8VsFq4YVxS6i4P7xp5kB7BF2SfMcCY9sxaVQ6fpSvQ9qiL1kNQn93E3/MmeYsfZx6yeFgetZo7Z0ixvsqDLsPHLECHFS5qt"
    b"YcvvmGGzlrXWemv9Y6+3GTwaP8PNyEVSlDr45/8P+dFMZKFRzHemM/uULccd4wL8ePDHCkA5klAPev5HsYijN5DOS4fhyO2s5Gzu"
    b"bO/s7GztrOksCo74xrHS0cQhOtaJtcRbQh3oq7n4dVwSW4ZdyJxBCBWn21NLyEGcaGMrv9XUnGCc0P/TimqD1EtKPmWSzMszpYB0"
    b"KzYgVj4WjIWjWvT//4O4NZD4z1hD6LLV5ftyf8WvXlIna6V13rhrrDCHAvk6wZNmkbZUlDpDN0Zf0XTmKzOavclm5cZy87gPXCKX"
    b"xBHuBqTMfK4FV5g7w85k07EHmdbMQzQYpdGj4HZnUJmpzaQseYB7YBc+bHezM9rvrM3WKNBecSsPJE8meOS1/rHaW0v+fHVtUbuL"
    b"fcyW7Bp4Lf4G2byWKKQ5dYzy04PoF3QetAr9RDWZY0wEGOwwS3EDufWcyNfi5/A/gMe7C/OF86BGj9hA7CgOEReLM8QV4mzxX7G7"
    b"WFH0i4nCRqGpwAtb+Cr8C64Bl8jWZI8wuZlB6C2dmx4EToRxc7zafm0VtIaBd2c1RupvtCbaObUmbHc3JbNyVV4g95bLyVXl4nI9"
    b"eYi8TP4s51JmKMlKJ/Wb2k1j9KV6WeObMcmsZn20Fts18Ue8lOSnroM7vqc7oQeoIrMY9PgX246dz65gj7O72fXsYrY5WxGYcT8z"
    b"mLHROVQPfaRn0ia1g8pHHSWtyTM8FgfBHzvbtnUSplfc4q3X5lFzqznXnG0uMhebh82bZpKZ3apnzbfuWx67OzgjD1O/BCk9i3wn"
    b"jagLVDp6ESR1U/QQZWSWMzJTB26T54Zxzzk/P4O/xPuFvsIKISRkF1uKq2CXf4isI+OfZ5WvDTlTypHTQcRP4m5Il6LiW5h0DuEU"
    b"X5u/wFXhdrFudihzBaVHneld1G+SF5rXFvurlcPqbO43UvTa+lpNVfurz6D9f5cnyEXk19JuaYzUQWojtZKGw3bfk3xyZ/mmXEQ5"
    b"rJRQr6pdNV07oLcwBPOqOcgqbifaS3Ed8o0sp/LS5+iG6CKqymwFj2/JzmGvs2HWYjNwAY7mVMidLWw/Niv7hZnJlGTegxYTgMCq"
    b"0h+ogZST2k1qkp94Ka6Ew/YBu49dxkb2G+uCtcVabs2B2S0GdZ6DnkLbWe2m9nL7OPTm6ngW/oXjoLPcJkFqGnWeKkCPpe/RpdAY"
    b"9AkVgY/ziSkA6r8PBNafO8JZXEV+MvSYGJ9XaC1MF3YI94UPggp8zopuUYYJPxL2CnOEmkJAuMEP47NDa2gELbAt+5ypw5xA6dAk"
    b"+glVlJpBHuGieLh938ptDTETjaLGZt2rT9R82hy1qPpAGaHUUjT5m3xLPi4/hC225cJKT+Wi4lLHqz/UXtpvbYQeNLYajUAZi6xq"
    b"9it7Ls5DrpFuVAo1kbbp0eg7NOttTJgpxXZll7LbwBFPszvYtWxfti7rYG8ws2A3PqKhKICO06Xpr1RXyiTrSEY4VxtM4UN2Q/DH"
    b"yzC1lpAsDuuj+RaS+ab5EujGgpwpDxm9HLYgzu4AtB2yG+ONWMOtyWGSjhpCvYacW0NjGlILJTDjmEQmP3h0IluGW8g94PLzPfmD"
    b"fJTPJfQTlgg3YWZOsYxYFZpKV9js3mI9sZqYU4wKL4SFQivBJxyDP69xi7nMwDqZ2HkMzXRGd+l89AjqC8lGxuMPts+eZz0wc0O3"
    b"/qwP0d9r9bSY2kNNp15Reit/K5TyQ34JU3wtR+X0MNeVykOlnLpe1dRlWlhbrOc01hmd4POaaRW099sD8U88h+SgVlBF6NW0F41F"
    b"j1ABZiDs71uGYhPYvGwBOEWATYLMXAeO+BfzAs1B1dAHejFdin5KTQZfvE6GknhyD4/HJbFkn7Sn2i3sQrbTlqxP1hvrtfXS+m0p"
    b"QAVl7Ob2HPuo/dPOgzvi7eCKBclIuEUH1ZHaT0WopvQS+jtdEY1E71E80505w/yEzR7PXmBdXClgr2PcFy43OORofivs+Dce8wEh"
    b"n1BSKCNUEor9+U46afwLfjc/hK/OR7hDXBdOAU8qwl5lmjGXUTN0ki5Eb6FkMpzcxMXAG1MgDy+YpcwtRsBYB3o8qJXW3qvz1WKq"
    b"G2a5HyY3WlmrzFfOKb9AiQPU7aqgDdOea231J3ob46cxGuhjD/SvR/ZIHMabSFZqE1WZXgbePhW9AeoZwTxjdCYX25RtxA5i27Ct"
    b"2MqsnzVgtrOh/SWhQ6gq9NOVdDn6JzX0z3Pc94Q57sPDoAs+s1fZ/8AUk4GsD4Mu54MCx1jjrImw1TutZ1bYymA3scfYl+wUuwIe"
    b"9ee552uTIySZVAOvfUE1pufQn+k6aDxKQ4WYGcx7JgtM8jTr5RpyqyDzfMDTM/nrvAw8WU/oJkwUVgpbIccPQ64sFaZCtlQVTP4O"
    b"8FkRPspN4fJCByzPPmTKMhdRLrQEHL0ZdYN4yAT8HE65zkoye5jXjArGKb2wfhMUKanL1XpqUH2knFdWKYvgxzrluvJdyaV2Uw+p"
    b"Hq2P9p/WSH+otzWeAX1r5lyrkL3Pbobf4E7EIl0plepOX6Nro3EoCf3FtIDd3sG8A3dKZH4zV5nzzELQRykmhE6i3igHukVPoLPS"
    b"N6lRlJu6A1OMg5wejsvjVPu0PQ7c7y/btGLWDZjbFeus9Z9120Kw73ntUTDBBzaN84KPHsJO0oXMIwxVnppPaUCMG+gvdAG0Ed1F"
    b"ZZkpzEWmENuCPQYdJj83i9vNSVwBvhG/EvT2gbd5j1BBKCs0FpoB1zQRigp/CUh4xZ8CT6zOS/Cn23Mhdg00hhNMJeYUKo920NDS"
    b"qRhpQ07iIniMLVtNrVNmZXOBkddYqSfoV0GLqrpGraP+pb5W7kCWrFeOKSeUt4qgllenqU/UwtoSjdZH67I+zWDNLWZx66o1wE6z"
    b"1+ACoIN21E2qM/2SroyuIZH5F06vMn+z7SFjVoM7boe8ngK5XeHP8xxOYUowKWguqoxewRwz0cepTlQK+T/t/IdX4VLYBp8YbFe1"
    b"afuzdd7aCKQ91RptTYPHKusYfFTV8tp1Yc47bNnOjIfiA7ANdckE8omkp4ZRF6HL9AR6NOnyaBp6h9xMP2Yj8ws8sgds5wvg2Grc"
    b"RG4Xd4+joe1X45vwvfiJ/AR+IT8Nsnw4342vy+fmGf4ut5Vry2XinrEjYacvMT0YGd5fEC2jM9PLqUzUXFDjdKzY0+yf1mRLNiea"
    b"GcxVRn3jjb5Ir6bL2gNtpjZBa6zV1ppq5bXhsMlbtZ+arfXTt+kxvb9x0CgMbe3/Skyyetmpdh3QYjmyl2SjBlA/qZz0LPoufA7N"
    b"UFu0Be1DZ+EzOYueoQNoHZqCGqCi6BfodQRdjdap7dQ4yOevZD6pRNLBPi/FNbAbJ9vbgKq7283s2nYO8MKs0BT+tiva/UCDa0CF"
    b"P+3cuCWeje9gCpL9/wntphpTGyBdCtD96IM0oYuh2egCwqg+M5K5DtxYDNJtJfsYiKEgTGYStx3S5ivn4rPwJfmGfH2YYye+I6RJ"
    b"Db4On4enQIcHuGVca07gPrGj2NJsIjOIycTsQCXQdTj3VaoedYxUJHtwRrzJpuz5lmWONjlzPDSZHXoV/Zc2R6uj0do98MGJ6iDY"
    b"4x7qcHWhelj9rmbRemqnNV4foz/XGxo3jXKQntWBPdrY7+0+OISHQAsbQiVTneibwBpT0TfY6X7MXuYuQxgfbEVJNjckjYdNhv1e"
    b"BY23EtztU9QDVQd6XEG3pNOo01QrSJrLZC6pQGT8BA/E/XA83PYPezUkznDY5LF2I3si5PNYe669wD5vX7QjwI2lcAc8BV/EiTgb"
    b"aUimkytEJSWpkdQhIIeydF8gsAhdGm7wBDTtysxU5hqDmRrsMPY8+4XNyTXnhnMnuQucBtrMzJfj88Fcc/MV+CBvcT9Bj8u4spyP"
    b"O8H2Z4PsXqYl8wjy8zsQlUr1gZxpTxJxM3wDduOSVRkSu7b5wxhuxBvX9J56cf2LdlVbrI0HJ+yuDdX+1XbCBC2tqD5Sv69nMCYZ"
    b"H6BLHzMrWiutvEBvNF6PP+Np5AX5m7pCSdS/9CFapeui/mgX+NNH6GU2MuFHInqCdqNJqAWw4jd6Hd2DdkNKT6SKUFGYXWdi4ivQ"
    b"pktgB5xrLWivgZ3ZTrDDVrKVCjltQVLH2TntWsCTy+1rsAWVcVN8Fb/CZWF2u6EJVgFmVKmq9AH6NV0LzULPUWG4yQsMz1YH2rrJ"
    b"pufqc5O525AwhfmK/L+wxbv4e/wDPon/yqfyifxn/gx/gp/Od4BN/wK83oUrwT2BdMzJrmXqgzO2gi7dkAYupY5Dg1mDv8JJ3liV"
    b"rHtmMfOiUcl4qLfSkb5Ca6g5tePqHrWV2lGtphZX20OvWaBuVD+p+UGLT7Ss+ird1McbsjHKRNZsK5293S6Bz+DG5AZpT92n6tFX"
    b"6WxoGVBvRWYi3Hoy+FEp8MdebEvwl6JsAxax3yFp+jCtmB/oOur8J2VG0QXoW9QSUKIEXaQ5cZAreCVuCA6eZn+0d9tb7cn2SPtf"
    b"2PKx9gB7kb0EqPuOnWR7gIy6wtyv4XfgzrXJDKCeT6Qi1ZRaC1ktUfXp/vR2+gdNg5OMQJuAfzAqynQBZz7IvGZSmdxwonagykng"
    b"mBuhF5xl78HjAnvrz7OFToSWUBtYTYE2uZCpzrDMDdQdtvo8PZ7OSB8AtnhPDpGs5CUe8ue7f+aH7JtmtbEoa4+5wsz051kPHhub"
    b"jclAhj2NDcYU44hxDfgmo1nTnG6eMR1WNWuT9d4qC/T23C6FJ8D+5SF9yWlCSBlqCrWH+o8S6cJ0fbobPYAeDRnSn/4XXqsPzkxD"
    b"W9kFE6tKFYNTnCSzSUmSnzzG+/E8yOeKWLbf2C/shUDVY+wpQI5D7MXwcr+9135nf7cTcAUgxQ34FHhiDjKILCZfCE81oRZCj05P"
    b"Z6MX0pvoFDoXqovWoj2IIB/s4GhghRfQBHKzf7N92FnsPvYK+5uNQc7khX7XDJxyCNcXNDqAm8D15rqDH5biinI6+409BZNsw/rY"
    b"R+BBRRgdErEU+E9rOoGeROWn9pDC5Ab4yVO7pv3eamelmBNMp3nAqAGtcLVeV3fod7TVsMkNtKpaXq2sVkhrDpu9ULunJWkt9X/1"
    b"sF7U2GTwwElRs6r11SpqP7aL4OO4GFlKclP9KUKVo6/QGt0R0uUlqgRutI5Zy9wD6vkAXv8fsM895hw07ulww8WZVMj1xaghqPIV"
    b"vZ9uT5enE6mr1HCYc1bqErlJupO2f77nq4SPwayXw82PgKbTEBKmPK6P6+K/cXvcAnfDU/FIvAMfweewAU2gFPh/N+hF20iYINj1"
    b"QZA/TygXEOo4SKBvdH7wla2wDRngBNOYXcC32aAdjIT93QZqvMp+ZT/9eU7aF/DaWXj7KHB1xN5hhjM1mbdoPSoCntQHyGctvO+3"
    b"pAEJQLsujvcD6SrWDKu69dncZDY3s5nvjRvGTHh0MToY/YxWxgLQ5E3jrZFgNjFnm+/MBGukdcrKAXv2FIhjPCR1LiC3G6QgkMth"
    b"6jeVme5Ij6R30xfop/RP4OAUOpF+BPm8kp5HN6JLQEZfp1ZRDam/qGdkD2lH8pFveB/+F9TmA/K+CFocA7xT3s5ji3Z2YMectt8u"
    b"AW9pb0+y18G9pdrFcSu8Dj/GAdIM5vWKFADHPwZbUIHeQz+gy0BXP41cf+7wBpOZrccuY6+xNFeM68kt5U5wyVyYK83n5dvBowv0"
    b"mY7QWRrzDSBb4vl33GVuBleTS4BcmcqmZx8A6TLMcpQPmms5YNzy1D1SmtyCBnPRLmkfs2pYR8325gNjnOE0DurdQIdPtAVaD62k"
    b"llPjNaS5wClLa420sdol4J0G+lz9l97a2GKUMSebcUBykjUfUnQaTsYDyQ/SErixNOyVTNdDS4C9/UxXaLQHgTfeAbN9BS/6//cY"
    b"3wg67AjUyDM30SrUFGVGj+iNdG1gx1vUIkhqgfpBVpGxkNWZSBJ+BES46M/zZg7BzUGFnUF5/UB3/+Kt0KMv4e/4Iy5MMoDyBpMF"
    b"5A54YzrKAe+lMzUX0uYc5aYpuircaB96L6TeExohCpVDjVBr8O+5kNwPgBV0SEAfk4vJC62gIlOBqQIMUZwpDHwjwiY/R7fgnBNR"
    b"E5QN2fRhaOvV6PT0c2oW1YGyyH1g1Yokik/jXrgccNpxezZwWWE70XprrbeWWmPBK4dBBg21GlnDrenWHGgS1y3ezmK3smdAn43a"
    b"WXEn2LHb2EFKQRfeDp+Dg8oIn0Evag61k9pL3aMuUE+pa6C6E9Q2cMMR8HFLURmoX0B5q8kQ8jd89t8hHZbhvrgRTodd+J193z5m"
    b"b7SXwVmmQaosgI+0C/Lljv3aVuDjlcX98Uz4Gx/BiauQOeQg+UwKgTa2UVvASbKA966HPo/hUQMNBR74/4xEpihMZTwzmdnHPIZb"
    b"dLMutgRbB3rpYEiWBZDfR2CP77EH2evsZXYv+OZCdgukTg/QbzqWZS8zW5lOTB5ormtQB7iDE3AnJrh7BeoTGUG8QI4VcKLd0w7a"
    b"G6za1m9zKuTHB1BaByPB+KWf1efo4/SW+j96E72S3ltvry/Vd+tP9fRGKWOtcdXIbg4zz5t5oOO+smoBmxB7GLhjVXjPKaQqpIxJ"
    b"eejl9DZaB16rhbaD+32CnJTg1jHKxCC4Zxn9RC/QeXComZDX9YCAdPo93PUmuiZdiw7SL6mv1FRqGdWSKgdtO0ZC5BZk2BqyjAyA"
    b"bGlBqpP6JCfsVgaSnSRAE08P/pQDfi5K8oKS65BGkHn/AtXvJudh4ylg/LpUWzjZBbjZIJ2HbgP+spOO0Q5UDQ1Hc4DL3iMnU5Cp"
    b"xvRmhjDzYGfWMeshW5YA4Q5gmoE+ReY/tBNNQKWRRp+nuwNdPIATFqdeQk4WI2/xArjnJLj15nZG+xk0r/5WRSve0sxX5kPzmnnY"
    b"fGKeNn+aMVOwGsJjm3XNMq369gjIeB48fiXQRnrSn2wh30h+UONy2O3vVDbwvyb0cGDfpUCqcyGt+8CvS9IVaQmY+CQ1HXghHeWj"
    b"zpPlpDfJRmhyFd5TP1wVB7AEPeU4tJgZQDl94aY7/Hk5xp5lr7TPgTYVOw7yZQheiO9DnuSHqa4jb0gWqgG1gnpMsUDy0+g7tAu2"
    b"9/97K6HSTAfo9Q8Zm6kMKlwCCfyIFYGoKwJ5t+PGc6PACWdDVo+FzG7O1eGycyb7FnQ6mi3AypA/HRg/cwD1Qmn0ZroofZ3qTn0n"
    b"U4mbrAF3vABsmwL7ms06abY1vZDUY4zchqJf0heDDpuBCqvpNfQWeid9mr4LmNtrVDbmGM+BeiaZd82i1mIg4nbQI3Lh+TgFt4RO"
    b"HYAmeJ7KQLeg99Ef6YyoDRqG9oLeXqEUFIbPxkBf4XEP3rYdztQB5UEG6G8jUFg9Op5OBZ3MhITOR2WjfpOr5DIZDZnVgjQhNUgB"
    b"UpxkJnlAeQVh4uWAkerA77Qn48lIsoNsAJ0+gjtkwFdLgTo6Ul2B6FdQm6gb1C3qB6VTCNRXFDytB92JnkMvBsVfoi/DGX9CYxVQ"
    b"FpQTFFYZ1UTNUGPUHjVHHYEzW6IKqBLKi9zweAJ/djW9BJRQ8I8Gb1LT4M6KUJ/JWVBiNZKLfMF78ApcBfzRgPy7bc+EO+9pN4TO"
    b"VQ66bBVIogZ2U7sLMNw8cMSHdthOh6uD068CV/0CKiwOWphOTpGn0ATjqcKQvS2ghQ2mZlOTwYWnUqOoYVRrqjn8Tm7KhBy6SnaS"
    b"KaQjOKOHMOQ6tJaFeBTug8vgajgIzY/Bug3l3Y6B0jlwzFK4AB6A28HHO4AvYBF6TmP42zOh7z2DHl0KPtps6Hy3KAftpf9P2+OA"
    b"DU7RUZpBGWAW//93smloA7qCLqIQ+g2ekh32thFThxnB9GXmM4tgc48yO5nbzHFwzvPMHeYSvH4GaHsTNITeTFUmPTjQNWhefVAZ"
    b"cJ2L9Ig/3+1hG9WIUmCGNcBP1kMDYPEOe6htQNPqB40wFTZ4tlkems1347Nx2thu7DDmGVuNVcZx4xK8hTJzm53N8eZ92PCK1kwg"
    b"nkx2fWgZacDgSyFt8pMu5BiJQiubQG2nQlQcfGZjoC/foF+CSzpQRlQMFYAOXQJuujyooDSy6DiUQr8CIloDn/8wmEI7uhScVKX8"
    b"9F3qDXWAWglc1B5upgxVi8oJLuCBjYpASj0hx8lh4MIlkOsjofsMgNQaCH2yP+lE+oBPDCLDIUVnQpptA0+9Tz4QTLzgs3XhZhdB"
    b"6v1HyVQZ+m96KujsBh2iWVQVXHwCOPX/N+gRNNivKIo+Q4o/hF9dQNvQFmDNjsiLUunr0Lta0A76DpyuOsVS90k/8g/k5XE8DufE"
    b"XnzEXgPKK2HHw76/sC5aJ6w11hFrGfx8wrpspVk/rSKgz8H2Cthm3c4GqpyNH+BUXAEYeTl5AGctCls1GLJ6NXWHugwb9Z1Kgpb7"
    b"lUqlXlOPYOe3U4upgZDZBaks1E/YxX1kHLBKIWgyYfwWUngF3Ec/3AX/Ay5ZAhfFeUCN+cGDKuIawIk9oDEtgNNexCFM4Naaw7y2"
    b"QxdKhQlVAc9aS52G28tAl6Vn0NPBMX7RmWE7u0EPOA/Oko4pzbRlZjJLmVuQ2RHGzwbZKtBV27D/sJ3hZQtorBXYimw862A/wp9Z"
    b"CrRdAojxLmi6GfoJWmxOx9Gn4fRx1BbSg/wG0q2Mw+DYFYFsl4ISkZVoLjc7mlVN1dCMC6C9vcZG6IDbjNvGI0My0sHvDDO3m1/M"
    b"9FZfa4OlWhVgz7/ZQWi0F4B5+kGDMUleaggQ8DsqJ/jQKHoZfY5+SCeBDjEdRCzyI0Ib8HoiONNxcJqR4DVFIHUiQOtXqK2gkW7g"
    b"a/mhJZqQrF9ga5+B4i4DnR+CWR0km0FVO8gFchGy9z2QvkReEw52ywNuGqRqgGu0omrC59gbHpOp8dAQV0N32UedgTO9AT9LgmwL"
    b"UQnQRwvBowzdFKbSFZx5BKTgWtDkGWDLy9C/roE670MW36DPQiM/Rk+hF9H96MZ0Q/ANH3TZs/A+e1HtoDlI0EXXg4O3gvYQR17g"
    b"69BTh4IHlYKunx5rtojf2LL91v4K+/oFXOp/LJ0FfBVXE8V3k+DuLsUhOMHdXYuV4tri8OEUp6XQYm1pcXcpXtw9WHB3CO5Bk+x+"
    b"/zmQ/e17L0+vnDlz5t65dz9HZ/WyEHs19gah85bim6956YnKv8V+RvqrqOcdkBgT5ZsW5s0GMgrAWyFOFiczNfzsf0BzHPQ3oZB/"
    b"xu5q4CMS4JuvE4Os9xaCvyHeYJDdGX3djJi5udfR64nC/s2b4S3xzuCPg/x4ILYF9jqHFr2I+kmClTfEPic7/4H7N46DFylBy3RD"
    b"E/zlLqUHj7m38CEB9F8mPEVIQE24snPAjwGDAiYQHcwPWBfwL/Z6IOAq9nsz4F3AHWLwewEfA8Kx5DuwaWjAXCLzAfjC0qixp+4R"
    b"vrc1MdIj5yS/WxV/tsGfSFztE6V290K8R6iLHtHloz/BkLOjekU1j0odlT7qQeQDlM7uyNORmyKvRIZGvoz8EJk2KiSqadQvaKL7"
    b"Ue+iqmP/q6IvgMiGxBVh2GQFvw5cdMR/4OelJQdRxz3OccejjjmIokq5bdBAvdyOcGBPtFB3js6UrBX93JDXy+MFc7rp6PE47mfn"
    b"PXwQjn45y3dsAU9zOSahk4bDCR1hyxogrzB+PY2TmH6KAhc3QOd2mGUpqF0AbhdSltXozK3+XDC9n/jgGe9K6iRBO9dyfoB5ZlO6"
    b"cyjclHBkR0q2lOj1PBH3OzdJQLKA4IA8+JXC8HleWD0JPH6LOGgR0WxHbCi1exFcDqAvkzl34JWuRLSe98pb6w0jSsjmpfFe4LP3"
    b"Ej9Mgin7RE+OHkxMsQAPfix6bfTj6IjoxF4FkDnBm+ydw1sn8cv49dC50/wDlPK1nxEMVnTqoXW7YV1DOYc5bYh3W9KydZxU2N4n"
    b"uOwCNV7Mp/qCsZp+NjTNay+uf9a74dloTxieeR84XQtat3hbiQnDsIBA/55X1I/rN+BoQ9uMoN12wyVx+cW6tOw4vNEBIifPSYKf"
    b"aur2cH/Da+9yX7txaYXW+JCJxIDzAu4H7CdSDQpMrys1dQhsjNf+H355cGBHHrUMrB5YgdcSBD4KOITe7kkcmCjgLiquPUxwC4tu"
    b"h6e75g/zy/mfiUh7oSfORS+JrhydL/py1FrivWpR5aICoz5FXgWDuyMPEKccBomXIxNExea1ZlG/RW2LuhuVBQ30V/SW6EReHm+s"
    b"t8Z7TN3q+yvgrHhOdlpsFLHSOecKLBQTjJV0y4K3iiCxLvqwvlsA28voJnFjuU9A21Fnl7MMjfcruqgLyqgaHJfXyQ8XpIAbHL4v"
    b"0EnuZOC2gBOP8xunEBgsjdcuAwuWc3506uNZfnBaEWt24OyG8uzF2Rff3hu90BP0DubxJL5/OmpvujMHDG6iLY7wyzec87DlO3xg"
    b"WjfALehmRl1WgzebuGXc6jBEMbcWUUQh+CI15TVPeczZTXwxgd+qgS+N7bxA6a0E8f/DU9t1M+L6j7yz3lFvhbcMlP2BR/wVxhoB"
    b"5oZ584kvVuJFd3iPvCfEDXlQS6aLO/uT/OHi/VN+KKz/xL/pu84NdPB9/ykWdAzG3CjU/Y5K7QwrVvSLEbUl9t+D4vvef95Jfm0p"
    b"ivB3fneqtwD8rcIP7/MucATS1zn9EijtIZRyPXZz2Q9wfL8KNtkVpf6Ls49o6JbzyomgFVLhrSrQZy3prY7gsC1I7ACbDUVvzyaq"
    b"We9OdDdjs1vcfXiR8+5Z964b7n4EqcnwfBkD0nGEoMOLBOTDmrMEFIRTswa8dZ+7z8DhESKxobRpdjfIPYcKG0CMGs95hwYeC9Mn"
    b"Qusso7WqYcn3ow9G/x49MLo6eicR/vtBVBiaZ13U6ag1UYejTnBGRIVHJYvOGl06ujPvWxq9HwtP7hVEnwzD8s57H7xCRBjD8CIb"
    b"qPFtPw28VYnfaw8KxqJYl+INDmJ117C7R9T/KZ7hsRPohjtx8dauG5vbNJzJ3ECwkdyNJPZ1eDbQ9RyftnoPesNB+SkYbTOaexEY"
    b"Hg/evgeLeUFoUicGGu4CPbgNf/Yvnt1Y42805RTOmTxeQYS9wT9H/34mWkgHuuvz6d+xhk3OfV3TOhHxfBP4egwtP9ed5W6CC7fS"
    b"jsvcxUQ/Y2H077CsvJToNVHXIvi/EdoiyDlPP//mN8Y3RHsxiSo2gb0uoLCMVx+/nQPFlo7bYC8nz1T16sAEPb0/vXnebpD0Bg+a"
    b"wa8Oxob7gyjnVrB3i+OJH8v56CfGGmPChEHcx5GGeUTEdoXIbTeR4yze/xPs1hH91cSvik3kJ7LJQ1SUH59c0C/qF8FKqlCuTpTu"
    b"F7T1NNplvn8SxfOIw0GHZ0EVVEDlNMV6Bzl/oJlWYalnaY8XtLvv5HK/gVEaEmP/zx0BGpfAlLvxIDddJyApOroyHrwZmrpZwDDO"
    b"KQEdA0ahv9sQ91TjtjSYzEBscI1P/YZPLOUmde85K/ByZZyUzim8WHsY/SPsPRVfkdu7F70r+p/ottH1ojNFx4l+HnUr6kDU0aj1"
    b"UVuidhKnnAGTT6OCotMRHXaI7he9OjqUiDAvEeFwkHzci8F31fXH+zP80/4rNE8I/NYGRprgzESxLQd5u5ww6nYYPbnDueisB5Gr"
    b"OBZS7xmqfQfQ2h4l1h1s9BDXtUGVdcEfd4LXuvLqCM5pYG8ht8ud+c4abtfodqMzi2/8y5nHK+PA1WD4sS/obIFHK+o0AykluU/B"
    b"bWInB/oyLWybFdYtDMeWcmqiW1rz7t5OP1hiAjpzMb+xi2894ITCGefA/QF6ZTOPt1KftdRrPGVswjdnhxt9FMIdVMAhtONsooj2"
    b"8FZR0JDFz+Qn95OghRJyOnDgJy8LyjIr2CgGSzXDQ3aH535CE88kkt5DbHsJhDzwzZau8p134MkrPLsLlTgXxTEOHPUAU1X8ED8N"
    b"3+d5L7xnsPBpvO86zpXeHlh3nXed+4d4qwgvjZ+CaL82KP0V7t4L674iRkmP769Pa46j9Xahg16h2dPAVIXdrG5ptFIpbLE4vqwU"
    b"2KviVsJTWKRXwA1BRQWDyjx4iTwwaDb5ixJuGj4TDFYr895GeL42bgv0Vztw+yPKp5f7A0crLLgmr9vnY+BhLoCAufDTD8SUwc4z"
    b"vMEqfwxtV4wWe4JfmYnSbeRVR2H70VGonePR21A4S8DoxOiZMObM6EXR86N3gtqz0U9QPEmw8dKo5D7Egsux74teFKjMSz/U9wf6"
    b"Q7HYf7Hwi3icl3iF2PjdzOChJL3fEmUynP4fT9+PodenOvtRhUdA6lVa5gNMmdDNwFECj1GT9qgjn9EZy2zrNqO+39I2leCm7Gi9"
    b"KOcTnjYUXpvoTAG/NjKZ1EmIijtP6y+AFcei5rrCCfX8Wn4l+qYat7X9ljwzxO8HSyyERcP8cGKhxOCyFNzwP3C9FQ5/S+yalLZL"
    b"qzYMoT/ycmQjFkwFe7/Hvg7j7ac6Q0BmbVgrhXOVX10DC48Eaw2w0FzEFzHxPffRcEe9y0Q4p4mbz6ARH3i3vE9eJBya1U8NI5bC"
    b"X3eEu8b4o4mo51PyjbDedjC6Ew2+Bb27ibhti6LeP7idRL1+B50/UbeOxI+G7RYwY0sdnXm2O6UYRlnmwIM7+Z4wcP4UHkzipMYK"
    b"S6AymsEBPVCjv2CFFp+vga2W0RfLqdcWbO8AZ6jU41Gx5EXnNt7jETV/7wThQZLRFvlRMjXRM9/jMbrBe7+4f8Kb04n7VuBNzJ8v"
    b"cFfjZf7APzcBlVlAdAw89AX6azglSIviPoivGg2nl/Ufe/eItcZ6PxDJ5PQ+RD+LPhy9GxTOip6A1h4d/RP3o6LnEHlvi94efZW4"
    b"MAAmLULM1hNlsh49/AntXZb+7Qc3LqLW5/AhQY4LC2WFfaqBv++oeUu8WSuw0pISNES7VkKRV0KdN+YdHZzqiqTboPh6wJQjwek0"
    b"OHM97XOQdjjqfASnLt76I37Ud3KAj+QgNR6tYdFOQveZE8U7LsJiK0D3zzBob+dbfikPJUiM7/b862ivfTD3HtByAKbZRmyzgv79"
    b"F+Y5zHEZr3jP9/z3fjLQnBX/XZAopzRlrglPt8SX96DcPbGjlk4DSl6d1/OhZVPCjQHOAz59WdpgGeieB4tN8kfhcUcQWQzANvv7"
    b"g/HAYzim+VNhUBuVOsiv24z6ITByE03zjvMVpTTvfI2SXgWP+1FT07GoPnxXI7+pXwDuSOrHB+HXvGg04W3vIAg/4u30QuGDWzBj"
    b"JM/F8jPCwc2xuuFw4lL/ON8ZE0asQk8Mg/vXOydQSG+ddGCjALZdEUtvxzEIldgdLmvB4yZYfA2sMCv63jz1E9TROWLJzXi0ufTO"
    b"ZFp5DHY43BlIj41GkU/FJ03Gd/yCHf8BmjfRe2eIPM85h0D3ObR2KJ/fwKvz8GNT1dcN8KIFwcpnarudHvmZmjZB6X3jx4Ehb8Dx"
    b"q1HAY70xXjcQ19JrTKxcx2uAqvzOq+W15+io2eBpHMvQznvRijeJIj/jj1LABgU0P9LEb+d3gXsG0Cu/w5IL8Eb/0VsnsfFw4t7P"
    b"9GAQcUpqfIb5yZF41rV436POTecuUVxCbK6yW1sZAsNRbn/pen1r3P3c7kB7rEHBzUPBjcba6nIkBZ8Pwe1usW194tBkYPAKrLKG"
    b"Gv7mN8QHlPILo6GS+TnozXTcZ6DOefyScHlzeGUIemoRKDlBzz33k8OuZYiPGhINtaflhhJhzkMDbHZ+A++zafGFIPNnWrQxNlQI"
    b"Ps6MrgtEzV2BgzbzPQv8iRwDObrREp3872Gw7yhFO7xmV783KB0mHpxJ+yxB2y7Fj6zCXjaB0m2gcBdYPAyud2M5s4iRBoHh/nzu"
    b"Jzi+G7ZfFS7NC9sX9AsRj+aiFsVo+apgtonmnwbDiX9ge7vx+2/8t0TnmdCFteCAHrL1eSBjHVx3TGNe95w47gPOj5olsIjuE3h9"
    b"TnR3FtQeok/CnL3OHWKOm1j7MY6tzmVwdR0mNRa4yLdcQ0U/gDWfOpFozfd8RziPLvL/afzeYVpsJZ55EL65EgyVxnnvvwCB5kna"
    b"0irZ6RPfu4TuWIGXHo+m7ui18Cp5Nb2iXnF8cD4QWBT93RBMDgR/M7253nbUyR2sMgEtURpb7U6b/kNLbsaWz4Kzd9Q7Hv2SyEmF"
    b"50qJPSbBf6UA/WnQ4oH010Os9J7/mha640fACs/9T2Azkv6PhZLLC980Bp+9QcEYyj8DfO6nzV7Ajongw9xuLnx0CXBaBzXzvVsO"
    b"z10BxVIBK88HhuO6n2iDa3xmK3HzFLxuZ/igKrjP68TlF6JByxv6/Aw9vRwVZdHCUvp8PbVYS3+vFDLWg4Ct3K/Fghbg5RbDoOvw"
    b"nv/y/Hx6eQYtaCpuPHjrS5/3xCeOBmNT8Zi/82gk3/Qz37uQT+yE+07gLR5S20S0QwFwWxpmrYwibkQtO4PqAaC6P4rZxkibYJ/V"
    b"KG0w9hDgPIdx9/Etf6N8/gfW6sB6qfx4/h3vIzxw2dtGpLSPfjnsLfIOwSRHUADXvTh+kPqnOfidQN/sp71j0rp1nLbKCvoXXL0A"
    b"KQXcdKi8+m5TWLEzlv2TOxKfOozbPu4A+LGt2xwdWQfNlJu2f+skdI+DrcPg8QhW+S899Av46kwrN3N+pOSNOavhPSpwW5RWz0VN"
    b"c2MFhWGePE4UyIimHV7DSZdp2V205Bw4YAC20wCVEQJfZAST8YkBA/yb+Nwz3l3vGnUKp453UDdXeHTbe0vEZ/onJQqnAFFaZdiv"
    b"AS3fCk80AF/wu7zJMnptMbY4g19bKPueT68vkQpfA0ttpF0PYK2n6Z0reM6n+CWL5pLDLQXomeb0zc9w+GrinMvODScGnjkbai0E"
    b"VVwHVWLHZFppMtpkmDue/3rhV+rDjCXd9G4m9yWWfAxPsES+oxJ+KTV28ZHSnAN5C/2/4IvB8IYxVA0sqQ5HI1izBY97o7XGgazJ"
    b"oOxvkLgMhtth17/W6IrFtY+xl5dEAB7e3MZ04jh3iV5uc9wD2VdB3QE+twFvs4p6z+P3JvHI/ORMvnEjmN2FMviPdtiOtrzAN7/C"
    b"R7xWdJwCnoiHonDRCLGx2Pj02iff55vfENdcxmoO8M3r9J1zwP4k+LU76G9AbWrDusaHzYidWvFsb+r4O8dyfn0vNb8OQ8Tgewui"
    b"FGuDHMvDmIyVb8fjnsFjnwOXl5xozZ1+hg0D3adY/mv04St48Ar3++mLvRyhaMpDnGvw9HPhuaV8y2rOhbT4DJ6fzaPZYH0yr02C"
    b"fWdjZTOIPwdxNgKvpSlDDhjBdcLBwGEYfx4xWTei3/zYjsffbeLhQ95SFOA0bxhRzI/eYPRgF28oPDkaRhzv/eHN8dZ6W0HmZewx"
    b"EMssjndrJ1ZcQLvvpW3Pi98CsIW4cHAesFUT224Eyuo6xUBFCTxZWWyzPIxZEh+aD5xkcr5xbC42Ec8k5T1ZsaWavKMvt7/iTaY6"
    b"0/Hc2zguOqecCHxJTNAZy83JGYJfzu4WIoYpRDyRHjUd142mLe/SbqZUduNTZ8I2P6BIS/G96dB3sZ039Mt5jYr8h13MACF/gb25"
    b"6Ls5WNVUefQxsN1Ycd4oMDQMJA3lncN5ZTI8M52o4Xd873Cs+SdaoC/+swWIs3ioN23yCzj/mefGyksv5JOGwNPYwwX/I/yYFOvI"
    b"RCsVRQXURQW0gFFaOCNQoqN5ZBzZnAiqFs9VoFXy4k8SOe9AbRj2a3z9N784kF9rhE/Oi2dOADMEwBAJ4cLs+LkQeqckarGaYpjf"
    b"qNdGkPwYLZyJXqmH5hiO4liJzYbhST8RoX0D65VGN9ZEPTYg6v0WvdgIvViHKLosmjELbRvkRsKI1/G3B0DivyDNlEtfSvydxoar"
    b"ov2Kw4E2TpGKqCSJE88xLxATNvzsW/mfY7MPaYWroOUArb8KjvqDWG0QrdwGHVMLmyoBz+XxE6Ge3hOHvPLecdz2Ijgfczz0nnvv"
    b"vZdEyQ7cmV6sWNQvA5eYJuyP35ggJllJe2/hN3bSz0ex9tu0fAS9/h5meY7tP+LRE843nB9hgk9+YifSzwATZKQO6Wj5wviszpwz"
    b"UMEbsdgdIO8UNmoZQHnxElXdMjBgM7R1B/xJJ84uPG6Pt64HKxaGFZMSWT/FP29DyfwOv3ZAHZfAI8Zz3lKeY/D0YnpyNMjqBKPX"
    b"AUFV/SrYZAj9WoqWqMfj5vBNS3ilD+/6G6ytpbXWSgEegyXNls+KZc/6p/yLMJw9cxBU7+Db16L2FsKKs0HMHD43FyTMB9Pz8eiz"
    b"uZ0lHbmHtjpDX1znOy5hv+fx3E/8BNhJXPowKThN42ThzIatZkTdJKONYqJ+I2m717TmbT51jF83z7sSplzJb60E8Yv4hfn07yr+"
    b"2wE/H6aU52n7l7B4MnmeYiCmFXHYcI2lzcLKt6CADxPzncHWb8GAj1F/j7DlWxxnackDcKZF1RvojxV8YiYYnEQENNbpx9EbO+8C"
    b"GpsJkY3hvmr0YGPw3g7+rYd1lcBnV+SX61CfUmA0Gcc7/wNRfRj28R+tspCW/olWr4H1ZMBDRxN/3SImDoX5dnrziUlme1Nhwkne"
    b"P2jEGd5i4pl1RGnH0ZbPQWlCLK8wauQ79PhQtfN2bP8W8aCDZ0mDRgzGoouDhAqUqipaqA5lbgNH9kUl9YP/OsMITTlq8Ho5/qvC"
    b"q02pTwestgfcMBI++0cRwjKOw1LK55Ul8MrxOOK7Md3UbgLOlG5izYwkBoeO+xwdbqPpB4XmKRw9iPHq8fuF1bee7xLRPAI7B+mt"
    b"hXjPv2VLI7CqcdjWcLikE5rDxv964u/6+p1R1oOIE4aAUBsfagn3NdHZhRZsxdEQ9Nbisw3wkfZfR+47aWTlf3zTWKx+Frg037wR"
    b"+zxFP0T4NpuemnYqrrGGbylhV1DSAz7sTnTaj9uhtITNeVrkXpqjML2Z0onjmD0bQx7WyM/vfPMo+rI3v9WJEvXAvobhqUdjTWPh"
    b"87/gh/94/x3ihNj8Xnb6pCZtayOMO/Grl8HeA+zdd5KjHHOgh4qjukNgyZxuKc6sPJMYFR7DfS1/bTMN62DFv8HyEBi8M7xucw21"
    b"sJqs+DjPT43niQb/NiLwAGs7j93twXrXw4Yr0GmLKNV0yv0LpR6EvuhK2zZH8VWG4fLA8MnAY6AfF36P8KK8J0TFT2HEpxzPOT6i"
    b"FANQirH9zGDQWLGs1Eln+aiJWOR86vsf7XNKs1jhIDLCj4uVxxEn5YT1MmkEpBCPC/CouGMrLUphNY1h9nbUpCX4awWT2YydzdX9"
    b"S5S3i7pfhecCiUYyuCloo7z4kRKwYF23CpxYEm6sqrnFfMTc6Wm1OPjot1jyWT4/DxzafG5V5Vx9pgcv+DaWNQfbGURPNaT8ZbHF"
    b"ymjlWn5ivEM2PxPsmIbncsGWZeDJBtSzKy01DEUzCi9sUe+fIGsZ1reKdl2o2TnLHFrK7WLN7CzkWATCl4CDWbTM77xzIs8s5pPb"
    b"aastipfP0V4XOc7BdLeI2z6iDBPQYqlAaGZaK1hRXAFKXpwezo9HT49/TeyYH4mLvv5MFGjR8Qv6+zGtfg9FeY3jIrx5kWdu8oq9"
    b"mhgWygyGM8NOOfE9NZ3WIL2rMxEF9LezCHv9FxW4Dz1zg/M27BiKNe9xHhIxnqQd/+NcxusL0YALiFZmgb+JtOtAmLAVrVsblq3G"
    b"bWUYpRz8U4Ty5qO8hShvCFycCwtKQv976GEbaX5E+e7RD6fA5ipacSrWOgSt3tCvDgYLg8A4eOab3g1ilQOowjUw4kJvCpw4Rcw4"
    b"Faacw7P/egdRldeJZN55ifykaJLiGlkdRqsvxiucQA2YBo9JSYpiye0p4wDqPdwZJa08BSX7RdOuxA/P4nYiLWFzJvPVLrN5tJD7"
    b"hTy7FF6zvAibsw7Feo9qzOAekd9t4pk33Mdx3xFXf0I/emhEG0V4DXbv0ILHsfjVtPJv/Fp/2qsN7FyeXk1HyT5gr+YZ/1UMZ2jp"
    b"DjbbwCsdaY9OfgU4pYyUWDmQmB+LK4LuqgpS6/C8jZRX5TWbsavMbXl5lio8X5lH1Tnrcdvcr8/ZUVzaHr9h2nEJ3notlrAZpBxX"
    b"LORhrSngqeCv8+tNaK+B8OAvtNlIZwKsM552G4qO7E+/94U7W9Ge5mVTgsoE9G4M5yaosznNIyB7E9pgqfJCzFMvVeS/mWeNQW/T"
    b"L29802+5iR3qwsL/A5G/wYuzwNpmmPEO6IvrvnLS42HScqRB8aRBF5nPcd34tPVbMHoebtiDAlqLz/oLP92Nstah5JXAXCmYJ5Pj"
    b"YCWfYeFwxWb78cPrNJY7D90wGUscD1sP1xh9b/xNU86ytHsxUBiiMbZUMF583/XfESffJY6+492HDc8ROZ+HGR8SVX/kPtoLQiGn"
    b"4d1Z8M755OG74MN6SPNvpvY7YeOjUqjRWHoCap4RewzGVorQgqYcymGV9bDOH+DDIbT/CLzSKGcMxwxa/l9quBP87XUuoKufEtVF"
    b"OEFuPDxEAVqkHGqxKOqwmNsVfd3C/QE+7Mr5PQq7Bgq7KB4mHe+NAJPmSVbCr+Po25a0UnYs9C0tdAZbXIV3GIT/rQ1W8qsFUvgp"
    b"/SisK4IoLgpt7FFXz4tJLGDzIsn8nLRUTulq88KNqHE7xSv9YMqRePY/QNtM4tq/sPOJyq2cw//T4MI/QcRMzYzPhzNX0Ceb4E8b"
    b"49mNqg6FEe/TWh5ISYjCT4xaTIQvTk2Jg+GX8lh0TbimNo+qgdhy3JbCn1gsWlScWYBPZMPGknMmBNnxUWNx+bydFvEUQH0WA39F"
    b"vs451EED2QjSMA6bqZqJ5S/F525CA+0nqj4ONx5DEe3H/rfxaC2MuIJ+sfmlFfTWP/TaT+Cv09dx1SrcloATLQ+/JEyYjzMTtmIx"
    b"YhpFyyk0QnDfj8L6bhK/HICvNuCxLRtwFaj8G1T29L/3a8IC+WHGpGDsNWg7y7HN2w0LrvSmE00v9Pp6c5VtMp3oerH3F+dmb5N3"
    b"FA69RF9Fe2nwacH0TXPwPg39EoqFvsXrpFZ7VsSWe1D7P7HuedR6AShbjxo+7hzCGq9Q10cou5tY5Vm0yAXnCRHwXazvNv89lDJ8"
    b"4xgDvkMfWgQTnwg6NpZq2jA5jzO6DooxufsCa76HVnyDd44AzZfhVBvV+R1N0wWVbiq6JO2TBZv1aZHLYGEDLGUx3GB8RBd0b3Ox"
    b"neUS5MfWcmJxmUBhclAalzMetpoEi02EL48NduPyKKUfh0guHlhOgpf/hldCeLaYn5tP1yCebaT50Na0cy+03EhaaA4svBMfHabI"
    b"LtD5SFybFk9WHkttD1IsKh2H15iMn5iFZ1xIvGo+YgGttwRbnSsP85PTFjTVkhbPByqT0d+x4PuPIPq2RqAuEk+Fwv6HeXSCCOk6"
    b"z3+EqZI4ASCkIJZZD4y34teGwMKLQOR29PVOWv6E8xH/8haGfOukcD87SWjlIJT5R3rgKTZ+hf45hI/appU5v1LWvsQvLUBkRTCf"
    b"l15PS0niOVdh4Yto8lvU+CTWOB9r/AmV2A/0dcMTtZCurowXCaaVstJambD85ETHMUDiZ+8BOvGed5H7Y8Qxx70zPD6E3z7GeQXP"
    b"/BR+jEQ5xvIT0Pp50Y6V6T+bA2gpfpgK1ufwy/vg5mdwkI0qJ4EZTTcUwabrgIlm4qmBtOVA6jEIXTiVVl9Ha+8hajaEXsRbPAd9"
    b"UbRDAhRgsNZpllH03EKjr2Pcvu4wd5Lb053FOc4d7bZ1f4UpO7nfwo0V0Y2G1vtSPjOcxZo3+RYkBjs2lnkMlbeSNhkDTmrjH1LR"
    b"Eha5vaWW96hzmHcCWzvkHeF+L9HcYe8az1+AL+94gbRVTDxDcjR2djx2IWpfGXZtQ7v2pxUGasbP5vpGEQ9NRV0u02nZNJvwT7vx"
    b"HQfA4iHU0kGwcUqjls8V78WCTRKBkuzwXCVuG8I3tYjmymmWooPyaNoR+7WhLt8rt7EGaLTx8hpiphBptRCUWgg8WEiRWkWsz0aF"
    b"Qmj7cnhmG99rTCT3nTMYFHZDE/WlB/6CH9c50zhXoGw2gf0tPN6sCGUTVmDZJ3PB3kgYdDAW8QusOI4ydKddG1CeGvRrbY3ZFQeN"
    b"5TSunQOezgMnZ9DKnHgaKzXvHU4EfR6EnlE+yVKY8U/0tI2LdUADVYMHssOMQcqHu6GR+w0w4wJ4caI30hvuDfH6wI3deNzPG+GN"
    b"55jlzfPWw6Bn8OER+PSkcEEhmOU7Wf8StPkJFPUbjSNYBNgUvdMV7P1CjZZQ0914gUsw4hP08lvsMAJO+4gKNAuMLyRlgP8yoFqS"
    b"gMXEGs/JqgyFYM26BBOrZHULoWhyciTDNydwk7qJ0DSx3Acg+QYoPEPLboeRJ2O97bDdavRKMWUwRKGx7sEbO9EV/2CrP6NcBoKm"
    b"tijBcmArEzrYMmqSw3mp/Ehq9wF14ipT9SkxXKT3zIvvP+S5KGK8xP5Lno/B45R4l2QgNT76JSVevQBnLfx6J/h2IPHiYH5rGL86"
    b"Gx1zmt74QKyZgPLk1DhsLXq1F600Ge85G6aaAxrm4kdW0F7bQcF28eRKXp8GdnpRqxZgoilKsxaIy+vYashYWq/2FC64o2zIi1JN"
    b"x8D/ZXrknJSyjz1G+RlgyBL8cjmQ3Qi0DwJlxgoz4ISV+K1QGPIO/iUchf6MR2/gw3CY0frsKFZ+mD7cQdlspGI+iJ5MG3dHf1WA"
    b"adJhKTGpUxDaMaETRh23Y2+2lukw+mWT/OcY9EwvWqMHmOmF6m7BWYzWtznZtPgd80ORng+2HsET172XqMbrcOU17h96t/n/Eacx"
    b"YyJaPgP4zUZr54UbyqLQv9P4xWh+6U/4cTUcEApH3kIdPCd6+oxmSEg8mAN2KgcmGoCNVtKNlvlqmSJ/0voL8OA7qOU5kHpHWa6B"
    b"KMAEbnE3j3KYyrrd3aac/dzeMOMIzlEw4v++zr4McBu5HdzqRNclNTttvuYovbkKzzYFjmgLQ6d2YjhnQOIcFPUwvw8IKYs1ZgY7"
    b"Sfy3qOJ7Uh9fuPGEtwtb2wUnnsLq7nmXvdfeY/gxGiQmxDNnwQLL4dUbwLAN+K6m2PdAWnaOVpraepx/4cJN8PAm4ue94OIct1dA"
    b"yHni20vC4ms/jvMenZgY7rAo2bLV88GD+UFYJcrcDLZpRB+Xg83KwY42l9kL/ukqFNVBOzbkMzVgxBLykUWIIXLTxpm5/wZmzArD"
    b"ZtH4cz7QkYdvzAWHFYdHDcWdeNxKM3eDwVI/fFVXGO9H4qa+sOAIdOEYPerJ4060YmtK8QNl6gsf/wDiGsKytejJBuixWnxnMac+"
    b"v1KL+wo8U46zOLXIrZnAEnB1Vl5JQUkS4gMSYzdJnCv+e1rCRmyX0iP/oOSH0YKN4LWCqKV0YDKmH067H6NXtnnbiauXoBzneNNQ"
    b"jTPhypXeBG+jstcPe1vou8vEOYHwag4wbVFoU+KlIfjBbcR2EbR8Arg6tWbDzUN3VxbO39j8BizwENr4iHMLO3xOlGwz8S9RLB+c"
    b"aI6Yro9CDAKLdiRBF8aHCePAkam4DXajnBzc2yoBh/tA12YQ3jjXOQ+gOLeBassXWUELj6fl2mr+qQw9lBb+iIQbb2EruzXKspzY"
    b"61dikdZYUzm/M7qvOtyYnQgtCdYWH9QlkK3GQw9Gw38RXnLuA7HGd14qGDMWbBjpZeH11PBpShgx+9cs1nLE4Y1g3D4wwAR+Y4bG"
    b"pvfCU2G+jVzbip0MtE0ZUGZZlAMo60R4cRHech1cuItanMJCL9JaBzjm01JTsK4ZaMvpYGMImKqN981OX8eTVovE+m/6V+HCMM25"
    b"LqKGS/Wri/BXK6jxf5pNtFUZT/13WoGYGKzk1wxyS76zN6izbJ6/lQO/gB7agZ++THm+8OF54pzD8OdG2ngVbL2YkvypjJQBRPzt"
    b"iY0agEmLZ4rJFiwbOJqY/zmMfJeaX0afhCqCW0jLT0fLTILDLM+wA23fCd3XmRasRwsG0wtpYLuksEVc2jY2twlp+aScCfFFcXkl"
    b"tpRmdvooG7FLXnqusl9XerSD1qVNIJr8ldr/qVyTvf5xcH9V86qP/bgodht7T69c1CL0Q01a01axDHD+B0NO0MjORuq/B0SFgUxb"
    b"F5QaLObHM5dyaxMzt3a/I4ru4XZzh8KQg7jt4Q6EGVtx1oQ/K4PUAqA0lmujPIfo0am0Vjfsvw79ld55hQ87AXfP98dS2g74h8rw"
    b"nMUhbzzHP++98EKxw1A040l48SznRXjyCurR8pEeejF8y0lK71uuXFZqX5OzB5gbye2v2Paf+OE5moE5RoR0mtvjxMumDh8QX0TC"
    b"ioGOz2kjhRYDZweR+eGPEKLjkrRIWdBVEUVYGXzWoWW+g4Ha079t4aHvpBeryx82FMc1gu+qiRPzw6p50Gs2PpmCeppWy+QE8u02"
    b"mpNOszop+b3McEMWjmy8OyefC8YW8klzVuZ3y2iuqrE4twq/X4Nfq83z9XmmlsYRa2LV5XkcjCXkkWbNj6XnpMRFYMvK8OC3lM7G"
    b"HZtRuqbKFKwP8zbkHd/x/lZ8Rz2+MYRvzMphI0GJHBspfejvoK1WgNBZ8ONA4r6q6JyMfi4YwUFFPsZLXfUOeDuIZ/7BX/3hbfVW"
    b"wZOH+C/MW6EI56ZmCw2zBcGpzSu21yzjXGzyENb5Ao0eTziohU/pREv+CGf1xvr/xLb2Ocudq1jcZdB3AWZ8gEb5hI70iKGjNH4Y"
    b"B36MC7biwYBxv97GQlMGoDAjwarld1qGss1eXUfrnAZ/O4lCl8K/E1CqFiu1lk+x1QjpqXly5wle8iba7QIKehMWOg4E9YMZB+Nz"
    b"e4Cu6njenNxmxT5zox4t0ywNDBkfzMbCd8REH8bg8NEsn2DKIOw0nR/IZ5JipQUU2xUhom6MnfamPUaikqbCTstokX0a8f2EZSYH"
    b"gyXo86ZE/N0p689w32JKbqPPJ+Ggs3gNq9N9Ytjbymg9BjduRU2uJuqYg9L7iU82pm5FqVtmOD8IBroL69mvrPI34PlsBnK8/wf+"
    b"bwK1HI6OGst/C4kadsHUR+FKW5t2ih565qcUTkuAlhpgph0eZQLncphyMbdTadspnCthzGNwxllKu8dZi5Ld4fwOg/yC5hzPe3+l"
    b"j42zbdaoDqgrjofOBuaSOF/ySp5IpVzHOx9VLskayrEU7zSTlhoFCtvTA3XxJxZpl8PiS0p954X/gmnXrPRFalR5KvolB/8XgROL"
    b"fl1BXx5m+FYryzrCr7Y+uT/1Ha1ZB8vIWkltbS1eKO1/Suz4FO/03E/vfJmVygU+K2BPddHvzdEutkJ4Isy/nFruRkmfpSeeo/6S"
    b"uC6xSmbilypuEWU61XXbu83hyR+IsTtx35x4ux6xdGVFObYrUpB7C5wfAvGzaFXzIKWw4CxOuP8Zxt5BC4wFJW1gtfJEcem0GiBa"
    b"+tjW052EHQ9hh8e83V815CU0yU1080OiGM+Lh+WlIKIOxv7qoU5srGwI3DgFbW4ZZjY7fxSvdBGbf4JieevHdz75qcVYIXiHYtzm"
    b"gjPyU3fjnNYwUEswYDsP9IBVBvO4O7ff0sNN8BzdaaE+PNeB+1bgrzWfaUZfV4FNC8EyOfE1xnhpNduRiPjVcioD0STRHG9AwUu8"
    b"spXjHYfNRH7msYuvivItmymuIg6L71IRCyUEl/HE3ManWeHxfFoVF8x/JXk+BFYswu+WBLtlYcEysGBV8aApjk6Usjec0x976U3b"
    b"9wCtQ7RG43/070BqY3M3lrfyrRi4mHLpLPM5ApxcwpOv1ljwKBiiNj2UC8ylgQGCiBuf0TdXUJBHiKE3oRZXe2u85ejJBXDlKjxZ"
    b"GPcfvVuwY2z6tCiHZb73xfqmELFuRrGH0x82o1pQys1m1AdpfmE9cdhW1Md6IpZNcGIYDPAGHviSw/QeFLruG85IHsciJonJfx9h"
    b"zCeOD0rfa0X7XeeWcjrPgrswLHQfOF4Gmv/iMEu1nCUbGWlAq5Wg723Gw7IJH2oObRvqcaGyVi2yHgx/dIYhvxNGq2KhBdB+ubDL"
    b"/PBjXrgxLRFzXM6YPI4h/5FEZxz+T80rOVGWRbTbRSki6SawYyfNmI6Ej6Z+zbOwTHDLYUkn71wHK/xR433/wDI29hwKC17QHHCk"
    b"cjc92iTAfcZ/4bTRTWLa87xvL8w/G8vtBWKrg4H8ilYsJjoP7xzkt1ZiExOp0RhKMN6vAy82RRn3pUzD4OwB8oVj4ctpmtdchxc7"
    b"JNa2LLO4ioKKyku3xI67wcLDwNRv/OZ0VO0y9ORmyrtZM2VbKct6zZ8t5z1zQZypSFu10QvMNQWd5bgtSvsXQSXnAOfJwX9M5z5W"
    b"co2I/6q/HkWzkNZZppySn8DhSDRUP8pr2c7V6YmaqHhbk5EftsxB7J2HRwXgx6JwZnn4sQrsWIG6lca/lyc2reN347Yj9euEdhpB"
    b"LGNeYq2/hJaxiPIYv3sJ//gUfeA47/yETgIsLZdGw4pgW7UodSdq8DNxzhK8+Hba/Ag4u6rxnwBiGJulKgT3lXfLoRBruQ2JoRu5"
    b"LYmiO7gVpBiLcqZ186IaA9xoeu6yVnwtoK974Tkslk8LDt7D04e1kvoXvML3sFtp6pONeMS040PvDYz4lBjtLDplH5Z4XKuMr3nX"
    b"ie0eepGejc2mApm5aYEytFUTvqMHvWt9+6dmW7Yph9Oyem5R30fwTyQ8ZHFzGnTcN8qsK4xlloEZqqOi6oGnL6xiYzxdNJbcnxh3"
    b"MNZkqy/6qAYj4ZRecEwX2KUL/dwRhvxejGSjfWWpX1EsPi8clkUz3HHhOEI8avxOY+Lv6fvXnHfRsWEacXkFbm+A3v0w51Y8trG5"
    b"KZgn9NYDHl+BSa5yhqO13/LMe2WBxQb1yZRxmZY6FeSXTHmaoqwAs1u+RydZyVBwORYr+40e+BtlsYLbNXgqmwGZwv0kZ7TWtPWB"
    b"L+ooy7AA7RMPH/KYX96Nd/kDlhgILjuBusr45WQcz+iBaxznvIP0zBb6aT0+bCv6/gSK8ha3j2DQt1582CEXvquSRu760TvTFFsf"
    b"Vwa/i/8wrq8K7mwlSQ9KOQpLmkPZdmivrT0axzqKVroIjkwt3YP7rqMIr8ELN2HBuzx/zznH43PSVcdRifv5xE60ou0YYTNX86j7"
    b"X9R0Cn02jj7rSdvUo6fL4tOK4dEscycWlvAGy3xB2R4SZR6llHM4f/bn4W0HcnYCXT+gIjtglVXQInk1KhtMvJ2O2wwcaYlkEsGD"
    b"idGK38CWufRfdp61bDzTMjWx4zZ4ivbY+o+ol0kox91Edjdo61d+EGolF9ixObVW4OwnlNlc2mGr8rmuqe5RsL+DXb1xErjPscgI"
    b"/o+g5rc1/74PNrIdOHrDWzbaUgEfGux8VsbMCVC0Ac5ZDS/OJl4dBje24fZ7cUYrovw28OOPlKw/75gCh9oo4CF44xBYPa8cvwDQ"
    b"nEV5X5Zp0JrYpQdM2Ylf6wxnDMUuftMIyST6cQptbXt0DeL/keKUH8WNrZVZ1oSjllYMFZJfTguXx+Y2JsiL7dxCNdiKPctjOQFL"
    b"76EXLKf9T7A4AFbrpSzF1ip3Y78lvVIHBqhEr1SnV+pwW4vb+oqlG4C8Vsqx7UI/9pNitzWR5gEWK5tlg1Y77eX3jmB15g0CUW9J"
    b"ifuTO7amugBexmaUGmFd7Ti6qT5zsZw16Oe1tPx/YPMECvIJ/RLD/eikhvsyuSndNG4e4u1CblI3G//HdXO4H5zkxDVPnA8aOdos"
    b"fzKRlupEq5Sl5zOiqmJR/3BwsRV0TKW8Ayl/c9RffupmMyypUCiZ/NdEJx89m3d5jwqx9Wax8MnpUYvBYK4ICrscn7Hsp6706kD6"
    b"dSzfZnPSC/AGttr+FOr0Nj7oGti75Ptwj7X9Z2qeAOVoYzvfUPec6PxS1L4u7NKIo6FGFTsrT9B2IuiHH+9NW/QDBSM1Z2j5dZZJ"
    b"aHkVfWHTTmCksdYmVlaefxG+LRUqIAH9nUojva9B1gt47T5lCMdHvaVHnmGJx3hmM2Xcp4yrQ8qqCBOrH+OwtUMXQPUxePWcanEG"
    b"3HwZP37px1KGZUqOtHB9Nn7X5tNraq7R1qy1F4/3AKdDQe2flHuGRjemg9nJPBoHYkdrj4WuwmsNSl1IWUkBMMVNreu03I9xtKyN"
    b"5TbFtgtwJEDhB9E7Qf5VGNBmyF6jFR/xyFYivEQ1xtQsbm7lXlneis3ITgLdq+kT22/pEX0RC8vNRUtV1xqMzuBtBNb0D0pjGchb"
    b"BicshuXWwHV7eXxcCmqnRmgOwJ27OGxuezn3q3iXxXK2Qs3Wx8wBbzOp2yROU6SdUC1t0f0d6KN29NC3GjmxHWuyfB1vTEMklQDt"
    b"+IyWtVXK++gLG3vcSImXYZlzFI38orHYn2iLgSiQXpyWx1gBdjFN+T381xIGrI2VVsCPVNAa2FrEgI3x3814vjGfaMDnW8C5P4F6"
    b"i2Rt7eluetyyvqK12qIA7VJXM3xDKe0UemoSdV9IKxzmvIYavo63uI0/uId9nUMtH4QdD9ECB+jZxZq5+YlPtqGmVVBltgvHO/By"
    b"mXY/De/vxj4s13wSHDEObTyCaKsvpelFLw/WzNkYXp2siH8lCLA1u4bBVzCHRTZJtfqxLN9bA7SVB2UVaNtmWt/+A1jqo7U7lsf8"
    b"K7jqR5+2oD++FYN+z2s1QWQt0NYQxqlNT1hmZl7FkxbTxdOKpI/0xFPa5AraxtajLON2IWp+OeWbrxUtNqswSPlVlkPbnDZtLoQ2"
    b"4b4xbNIUL/a9Vuz2hBF7K1dqMoz/N3VbiFpcq/g9jNpdlWJ8wX0kvxoFM5rXTqwMj6y0X0FsojTMUJ36Nqce7eGxjth/L1h/PGid"
    b"B+Isf2SdvNNe/PgR+sYU5WNu33C+or/uwp+n8eh78fBbubVZtTXg8g9w34PeqgtvFKQVkqKn3lJ3W1OyB/RZ9uE4at0P7/wDGsNG"
    b"ZcqDt9Jo5bJwYAi3wVhZEfBm63obg7p2vKczNbds3I7ECrb+cbLyFv/AO87xtyjn+wjIuyjsXRG/XISXnnJ+pKd9sGi7O8WX9sqj"
    b"GfQSxDU1tar8W63bbY6fs2yTPqrBMG6H0Co2P2J+fSg9/xP9P5Be78LxrbI3m3CW5NNZwE9ajeYFYIFviJmjKEGAcxX7e0B/PKL2"
    b"l7k/RM/YHNEeSnsMezxLuc/CnAe53Uq592Otl3jtC1Ie85lHvo3YBjhPKL/Pae2ZnVuz9eIoyBLgrpIyqTtT9u6wXy8QOhC8jtLK"
    b"rQncj+N+MGcPnv9BowT1NNoZTIkzaL7+Hr9x+uveBdNRGmPAXwd8USn6IJOfj5gxKcrIcnDj+Z/xYAn9V14mHqXl1aTEO1kU+TQB"
    b"m93o3Ylg2mYHbdXVM/8DcVpafqcwbVRRfqU7bdwXaxoJG/wFYhZqTY+t51kH1638+uhvuHAO/Gnry7+M+P9BTcaA0EHUbjD9YZp+"
    b"MGdXENya+yawos27NqZ2DfRrtvN1KTCfj5qm10pF2wElrvPBt9G51xznKd9BKfs9eIiVtMIm0LQTj7sGTzFdzPL71xUyY2G58djp"
    b"SOr5P+5/VG647X3zZRVqCyy0HfbanqMV7+lIfDOUd02EkSajHS2yXuIf4DiniO4TejotMWZJ5Ro2oV/60y6TqOUSarwJLbxRYwXX"
    b"sMMwmPEAtrdHmZ5baZ+V+ITptOIQsNkC/FbDqkvgnS1709Z3XFZu+SbqtYhfnSt/NRbGGK1jlLLgbM3Pn1q79adWktmI/UaY+zio"
    b"fYntmMJOT3tloAXTgfU8WqVk49s2HtBWMXNnfr2f5hj/x/+WIdgFpDWll1to1Ko5fdEMrrG5jqJab24ZHRnw75ZxZhn4li98DbY6"
    b"Q0x1HhSeIM7fQZuvpsyz4Mbh3LenlC3gvPZwZDd0Yi88UQ+8TydaujVK0VaLtAO3PanVWD4zEw+3XBnxG+nfXbTGcTB+H63oKZPp"
    b"jZ/WCeLXs8IJFWDpql99d2FqVln+qh3ephulN11v6817grvh2nlsKq0+BWxOpp/mcC6gp2biw5eC1YP4hiNg1/JPJsGIo5z5tMmv"
    b"fL4teqA61lcfu6tLP9nOXs+ICO9SrsdY/yXquxEETsN6xoCXodrrphdM+aOUcHfq15va99K47BhqPQ4UDqZt+oPRUfKAc7mdB3L/"
    b"xuNPxwLX8/gY32mrbg7QDsdQYydhlmNa93KFnr6O+nrJvY8tRPtxlK+fEB7LSI/nwIaKY0ONQdYP9N+PtEknMGr6o4v2FRoLJ/bH"
    b"MrtSw27g0CJCm/vsJA1UlrqW1rx1RjxiYhAUiyMA7Ril9Ug34TnzVme0ksb4YodyaTbw/yZscB/Mvk+rHENhxj2U9z+U5VHtuXEY"
    b"xXmR77Aj0o9QhlZS+tFW61g+fz60Xzm8uY172/5KjSmnZWvZeorfKf1krXkwbh/DoyHUpR+v99AqFENBRewyjxMIW7zTmktbH7IU"
    b"O5qC7fxEb1hOru0aVBR2zEvMmBmOtFgyix/fz8p/tpdLSlixKDqpFZre8oL+xPpstwabKz3nW7yenBLn4HfKgrl6Wi08mja2NbcD"
    b"8cMj4MXpoGiRckhmg7m5lN1GBiZwP4z7/2nHAttXzHJxWuIBWmFrNvNUX5lMVTkq8+3l6QNbdZdTI925sMFUnMkVRydTv6SiXxJw"
    b"uiiiD/TPa9r3ubS9zVzbrnoW3Z0CpZYBc4o6HObcgZ6yHQg2grMNWJtlzc0HhX9qLykb758CikehM21mtCuP+2O1I/H8I8D1QK1K"
    b"+RVOHc9n/qBtVvI9p0GtZWuHg8aHfm5KZe1jewPZ3EwvMDcMa7O19htQh7YTg80Y79OOP4fQLTtQjrZ2wCKD8RpRbgcT1dE4VhbQ"
    b"YaPfr/n2W+DNVpNt0Hq8GYrtp1LqcZToZ/Hkn5wzKNffMMkMrdszTB6h9jfB4hOtbU8Kk3wDh6RTe9bA+1ejtGXBW3lK3EC7hTSF"
    b"RWyW2lixDbZSnz5roOxBy1Vv8LW3jFlLaD6xKDXOAi4S4h0MgTYe/1S2GqadP3bD02u0+nQqPPErGn4kTNCPNu4JR/TBF3XH97Sk"
    b"rZvDIF24768dsCyG/pXP/s43rMCqznDausRnqIwIeNFyHGPBymk1J5tdOy4FU7LCWEQtyvY9/zdT5mhjcbrNNdRVzdpLP/WEJ7vR"
    b"R52pXzet5+wOP/RRhp4htQe47g5/DoBJTEUPofateXc1bispHyC7Vgqm4PzsJ6JlX6FjbUeTUPpqNzW3TH3zZmaHy76y/G9EMhPU"
    b"ElPk48zT/qVZ6Lm8b74ivjVg6l962jLsD/B4Gyyzirb8l/v99OxJzmNg+SCoPgLDHNfKONt14hbIv0sLPdSsSADoiStdnxeWKUcL"
    b"ldPMb398xQ/Uqz7M/x3WaVH1NBhlojjGzkHUuA/v60G/GwI68MkGYkfbtSEYhZ6Mtjfbi6A37kmRXKUMhymLjQPvpg620tBmKpbx"
    b"zHLuN2j3gq3UZ7/ioFD48hIIPcftGe1JdY/2e03p46F2UuJt46CHYijWKQLSCoE/yxJqRj+0p1SdqUEvzWRavlZvSt1POqu31iq1"
    b"E44tHrf59rRae/YOnXERdtxBy9mKChvB/hlu7Os34qhPrGhKvhCqPpdfEKa03H1boVUebVkTrLaDEyyz3+YEV9LyO3xToi/RzzFQ"
    b"a7ayqAZ4q0Wpmml2aIBi/F9QgpOw7cU8txI2sN1auuGHO9Hyg+kHW1HcjfI2Bld1hNcS0h4lldVZCN2fC6TlpB9zowe/UUyQjZ41"
    b"OzabsyxnixaS4A0TUJIoP6Fjsw0uvJFAu1u8oJci6SOPun+ixK/Ax33tkfgQK72L8nqgPU/MXs+DseO0z35qd0C6eLnWZ83Bgudq"
    b"rcdkGHI2vn0abPgTWO4NsofwnGXe/kTL/IIvXwym9ypD/gD88xBs2hqrlCAxK7xeBNTVx6p6U/9xtM40zS2t0nhCGLHZfuc4OvIk"
    b"j2wea6n2ZLPR1eFab9WGPq2nfTm+oY7JnQfa4fcc2NsJsy+jvBY9jxSfj6RMA6XJRlOun7UTjc1J2V5Ac6jpSuUE7vHf8PgzLWI7"
    b"GLzx0+HnUtHaKUH8N8oaC6F3CsMBlcBgY61S/bKnUjv+7yJG+Q5e7AQntFPpGlLL+vRhRY1359cIUSA2+Nl3iIuu81tH6Qfj81Dt"
    b"VzwXRlhCpPgP6LI1l21BZjtp9h84unNvyqoPtRhEDX6lBtNgA1sXvJ2+us632Lh/kBNB+RMrOyAdJQgG/xVhqrqam22juNH2xOgC"
    b"Tq3ULfivOeVsSi2qYFU2+1mX2jaVh29Ejb/lG0pTz/zKeS9NLQvwiS+vFuXTJfkmW+dUWSN45ZSVYPtrFEOt2h4bSR3zOAlRjhGg"
    b"zvaCuCVlu0uR5QFQtpb2n+PbroHbtKJ1H/23gddW8p5t4O4EPXqKZw7x7u3wxAbQ+h/P7JM+3EXN7Ro2e8U5u7WP2Fat5t3EO/7T"
    b"fmBbFbuG8f4wZZY9hQM+chuFCvP9zHBZHuoXTK+VoH7NqdUQ7m2U8ReO0aiakcR7Y7T3j81/jsNTj8SvD9degF3xMx2UE2n2WkBa"
    b"ND4q4CP+yfZjvAkyz1DKHfDFWq2hncvjv2DB2RpRmcZpeyMt479V2M0areaz9d4nNEJyiNLfpe42n/WeUr/Ent+ixAI1Q56RX8xG"
    b"u9uODdZX7eTBu8IkfRW39odz+lBSGxUarJnsHzXaZ+Osdegz27cgA98T1/kEQ1zhlw4rB85U0URUez+t7vwfMXNTOLAIMbPlCYTA"
    b"kyVRi2V5tjGvD/KbgcpBeLRFX3ctPi69HBteSghO0vJrpRRfdaJcA2jT4ejCYbTqr3DhTPzOfPhxupTiePjQ1pr30uqBVtoJrIlm"
    b"UsopUzml5qJSU2qL06PhFMtW/aydgB/hhZ/TrzbSHEArvcXanvLfC159TeT8gfaL4dzS3iQez7ygj2yF7QPeYx7zKSh9TQtHKNoN"
    b"51PGLS94ZPP5j/nW6+rRqxqdPau9IvZybgBr6zjWaj3cn9qHZJrGuybCOr9Kof2GarTVzpN5z3St07JP2XqEu3ybzaDE0I4MNr9X"
    b"H/y1oef60yI2lroYftyMctylXYTO8Piks1e5NIvhx2VaZTkSTzOEfu+u/K8C4Nni1YTOPdojlHIfUMbpMvmu6WLwPnDOYJh7PP37"
    b"C0xpY48TOGfy/AKOVWJ/m0M+yBkOYwU6Yb7tzPHRT8NtML1rmWmZ4bh82lXCZrvqwTc16LEK8mbm0+rDlC2UM9xMUUNlxePGpPaJ"
    b"0pQ0hJrb3gU+0dxbyvtKY9SHwONGbpdpT/e/OX6WhxmBxxnud6C87eBKW+H+M3H1ePD3izTVbGmu7crktAjgMb7OASVJsMpM/FI+"
    b"zcpWwVpaUJYOspjOcF4PjQV0wIY6YCNttJq/Nqetq2xNr7TnrAOHhvB/fkVdNp4VArIL80oIrRCi/esKwic2lmhztHYFj+xgNpNj"
    b"O3gnp4bJ8cqxnVdg0/abeqZ9dc9xnJJ6MuvbiwX9p2hyI22+GB6wFX2XaIO76o2zvOMObHKHR/d53vx4uNb9mF9/zP9PYVnLAQjX"
    b"jp/3tefLVc3Nn8A2w2ibUOnyw2DiiDKbLNf3slZRhfOeaPDyUTmpOdAUOWD0jLREsHKrm9IirUFmR40v22j3KCy3P+xoyubLnMZo"
    b"7TA0gDYcQFu1xdNYZJtfvjAJbRKkcebH/MIlzQyZ9w6lrruUMWPabIuiHNvxdxlIXMT9Uq0Vn6sZtYW8ukxRxQYpSvuc6Qy7EoDF"
    b"Hc99m2mNiT61/NVvOAprlU59eqyzchC6gsmR1GGYFKPF1EN53Et6rLt2RWxGhFOHPiyulTTJwGWkWvISv/efVtPNw4qGE83YHgCd"
    b"iZnbwo61wWQ1vwVHI3y2ZeyOwM4m8O4p9N1yevWoIlPLXIqDj04Es1k2egPtymYzf/0oSX/Nco6BIwdqJmU0j0ydD6VVv+zl0pNW"
    b"bUFPVKak5TQ6ml8jh7mpawbHZhXN9m2uzXxvkPNaY+vWq2ZZd3lks2APFRtajHyDXr9AySyKOCMteBg8hfHabdr0Ea894T1PePSY"
    b"ln0CO1oWlq21j/JdbCs2/sNGZi1v4K1eeUIdH/u2s/EtvvMS32WzbXs4NtO7K5WVsoDenqYcUtsRyvp4Lq/Oo5XWax/PfZp3sxWW"
    b"nm/XFwnW2nu7FmJzrefrBgYHaV3vbO3daxnt22mxFc4a4ulNeO/52nFtMrZt/rCR9sQsJlVncZvtP/gCtNyifOf5RVvVvFUsvhEO"
    b"tHJZpsevWjsxQ+vKFykf3sasVmgOYy3ttAnrMc1sFvZEO+xa/OXzvYbAAK1XTEd8kIo+yqh4OTc9ZvnUVbGLBtJSpvotR7i5dtOo"
    b"Azs1kM+rwPtLov+/ZIqnprxBTqT2xrmo1UtHOWwfK2O8FXibBfDfBCnfiXicsZpln6h57Tmyo3VYjM23HxYjGGO8pqRBytJJS7my"
    b"0rqFlNVcBHSVkcIthV8pKYupRFsWpCVr0Yo/YFMdlGdcnVJaLnIF7aPxDfcF+Z5KYLAEiLR1HpZDlUvz+gXQRrmpx5cIJi3/xQOl"
    b"sR2b9/msmY9bYOsGqHkAKsMp6VXV8RRMdUKRpc2I7dI4zl4pvFPaM9Zmmq/q/rZyNG/AZi/BnWUQP1CM+kat9gw0PeOwWYo3/JbF"
    b"rjeVq2c4t1HGCxqHvqSdemxm6oJG/Wy+/K7GNSzLJ9BJoFyuVDC9rUmtpKsb2MhIO7jRGKSbMgZHYLUjaLOBGkkYp72++mK5A2nf"
    b"HuiaRooRatM+xeWZksIzZrNxnZu+7UBuK9T2Udp1lMD2CgqlBw+L+TZpJ78VIHGtVpuuAaub8dz23GJdO2I/1rRbEdE5TpvJPufb"
    b"tVJeK7s/yrdMyfgc5nlzYRM5KE8p0Ge57O25bQbHNFcui8WyrbQK13bBqU8f2wrJCtqBxBRLfJTYJ6mkK1qJu00ZebP4/d/A3+8o"
    b"jAlwoOVADvKHcvsz50R4cQplnkLdZku376f1j8MZD7Su3wElNuZneSANdO00yyftor11+koZDeF2GPfDNJ7Yj5L2o+1tJr2lMgEa"
    b"K98+WCvc04LPmNppNJC6RvhJuY/A+7zRrpjPaZG3mgF+DMaeyIvc1Z51FlPaGvpjoGm/9N5h8HCU508r7+uib/sgG3oeaLT+Kfdv"
    b"wZTN4dkIlWXcvOPe0QzOO91/4tXXnA+p6z3eH86nzZObAjihnRV2aL/u1fTYcsUxlp2yVmMmRzRfGCrNcFm768XDcuKDneRiFeML"
    b"m1Gync17oKJ7alRnpnT1cv5fAwb/cWbhsWfjR8Yrl7A/VtwBr94ANiqHl7Q+TQa+bY21MfgNzVuHal8+01Srwdoq6VwbsVqmcdBp"
    b"2onoH3D2D31vu1Ru4/8TlN9qtBPr2UaLnteefmGyonBs6CltYrv4JlDmYhL4ISn9ZSvybGVMeSyrDP1fSnFnZcWc5aUXbTVCOa2h"
    b"sLGoYlo/kYlvSgsKTfvfl2VfplUP0EO7tIvZMso/S2t95nE7hTaehaVs1I7Rq7GXvcrQMRVyGz64oyyPmI7tZJgKP2rXaymizM2K"
    b"lKopuPxWuXjtKUEb5Qo0luatDE5L8bic5tYLSD+U117wIRrFzq5c+2C8QQ6xRy78fxbtcJWBX0nOfTzawewpvmPXl7CrFtk+F4+5"
    b"vavsiDPU7aTWuNtqc1uvc5LSn+LcTy03g03bMdbi3yPaN2m7dtsN1f5jNj54T/O0N7g3rxchbnzm2y6s7xTpfFYe4yMipcf895Jf"
    b"jcAy3ijuMaZ8Bv7N9zzCTq7yrlv8947HgaA7yImDd0qn6w9koQcttqyAJ7MrEdTVFS6baHfRTtobaigxaU/NUdsono0FtcO+W8vS"
    b"a4DhsvL0wbSdzTzZnq2B4sY30jBvQNNt2cxp2cx/2uV3L/xn2Va2j+5MrGYavmEp/HLQH0crTAez+/GPpzTiYvwYxnsN2bYP9VEp"
    b"oieKFoLQpja7EEv9kl06voginMoa962vWXgbB/qevrcxlJrwThX+r6K9ewqASpuDTKBMxwi+6watdJPvv6YZol1YyPqvu6dM025G"
    b"synvH5Tod175i1qswnZszNfW7ppCs3y128QOEcS76bCTUnx/ZVq4IqWootXgHZVz0kezRu1p2Z5aP/llZPF7nmlCiW2uyNYY2zUU"
    b"CmiHj/T0UTrlWsSljeM4tn/9W3D3TCx1GyycoeSXpReP0uuHxdJhX/e026PV5Me1m90RjoO85xg1NKuzrAbTkQf4ZBifsl2VnvCN"
    b"TxRH20j5B26ND22/rffSjO85PomT3/Oud9rHPVz5cle5DePTJ7X/jHHzQR6d4jdszwfbJ/IcVntb1yB64lsGi4182x5PNjOYV/sp"
    b"medqLm1vc4IjNMY/Cp09GSz+pczC8crUGqAZgC60oM1wWX5NbT6fB59nKwgSaVbwFeW8q1jjpOaAj+oaH7s0tmOrl9aiHzegu2yv"
    b"qjmcS/TIdoXcDu+sh8ctztmtWcSjYnTb7+s29XiqOawP2OdnlPU7ZQkmlobMTY3yUJ+M9FsaeNBWjNtutsaFheGZYGymkFgzE/jI"
    b"CLvkgFFy0qPpHLNNF0b35HfuyFudpvT262exhtOU29Z5/EtvbtQutDs1v3lOSvGiRohvaFX5BymghHBUCr43xVdNWwIrMcarDL6K"
    b"grPSGnOshFKoyvM1v+4WagrDmNz26smu7KjCmlsvLm2cXvNd6RS/ZKKumShzcrAepN2abQ9nFw5wlG1qe0J+0A7GNht9l3a7r73b"
    b"be/ck8Kgja3u5n6DZlC20z8Wd+xQL+3gcajOQ5p/OPr1szflN55qn6M3Os0DOs4z7VD/DpazuQmLWz/SFvGdO5wveCXICSf2sZGn"
    b"T4qI7Joukb5d28X2IEmq2ZL09Fl2XXspu5RyVW4r0FLlsdp6yohoDubayXZbwoYdNEf6rWapmmvPraZq0Rr0b4higpwc5jni0DY2"
    b"6+ZRVtvR/aVW69h1Q27pymL7qfshEGl78FvkanNptuPhXDD4L37QRiN3acZwOYftT3wKzB6jfbZppukiLWg749u88i1qe9//0gdJ"
    b"NQaZiprlhiELKc/WdleoRQ+bTyyJYiuuXAqrp603DAEXRTXamoV+zggyrX0+ft3J97pW3Z5W5qXNXG7XKthV2qH+P/pxo/THXs25"
    b"n9J+oaba31Imy1WPq1yZYBBTQHMmtbQKpD4oa0u7tdK6rA5YtPmgplpFVR/fY1nadSmjxWDltfuRReOZwHN6jd2YKnHRjTbTbPsq"
    b"2KjhK477GgsM1z7Nl6UET0qZnaBsoZTxKKU8QB12ie1t14N9PLtfu34e4z2H+MR2ar1X33AIHO9XhoCtsbLI5O5XdFu08lm/6PGa"
    b"A8Ze6JowH6U1I7RT6yt+P0KrLp5Qhkd835eM/jta6/xCGRO2WspWJwTqOp3ptWatkDLKCuNBzJt1BGc2YvwjjGjzn/+gqOcRr9h1"
    b"1XqjGW2ObbhmR7trTvBbzRyU1U7mlr+cyrEZO9tX4TU4vK3Mh2uKzXZr7eJ0lOwSvNwK8DVDM6ILwN40ZdjZtRsWaTRgkVb1raef"
    b"t/PZI2rFSyD0Id9zV7Obz6Wxn2sHiziOjeHHxwKSaW/3dJody02fZdfeVYW0zrYk/xXV/uUFNZdmGiyboq2c8vBxZEFRWPFHqSCb"
    b"X34J41m2r+0JekK7ppyiXU9pHHQ3rxz/2tqfaOd39Jftx/cJnxNPu1IlUWbzN4oO84B5y+qyHRTqU6Ja0rC1NGdSWes5KmksoDCW"
    b"U1xtabsS5Ndq2+zUKDOnXTskM32XA/az2NkBoRF+eo3uOKDedrGJCTbiO4/EjQ+4va041+b9rwgbYdrRdwf1OiBeX06d1uoqmaab"
    b"1ipq26zciF3c7wSpa0H2Gt5vsyyPeOW+duV+otUj78BcpEZ3YjjXNbf3ittXio1tfPMjWAtQqSxLJ1rlNM+ZkFvbiT+R1uLl0O59"
    b"Zmul1EP1aK8GaBobcbXriFjWYj0w11irTdoKeba/aiuNlNk+oLbe0GarvudbKolXQzgzihlT0htxtftNhPTGfekI83mXpFSOUCfb"
    b"g3ct9Vv1NabeoPHFFYpnlmqcZwbP2bUXbHXAIV3pyMZ+jnDu5/8teMcjWPx9bp9rx9BPtHokLfCe/olJGXKDroogwuKZQuivPDCQ"
    b"XaXMSmtzRg0U2VTUrmu2ki8LOEhPb38jv+06dk2X98oaMuV9VRa+B8s6rtyo4/TURa3ENaVoo3hntIr3LjW+JbaKBBW+b1nqybAA"
    b"2w2ztHx1iPRqOVq5jq6ZZtdQbK5dp2vQpjYeaetXmlDiUpQzH3ZelNsS2mUmA9+QEBuyjLTYREmJ5RcfiscjNI//FNS8pXVvSAve"
    b"0TznKbAVphypXRxbKLWh7Yjm91aLHf/VtYNtvGc7ddilSPwwbXoIq7uo8ewb0oS3NAZpV7k+T+0sjnGda+DMsgAd/o+mt++AvTDO"
    b"G4ptLlO2K7zvscYvX9BH0XxDAPrKVxZZSrCZnjbKQQuFyGZtRMuiuu+064PtaPejxootM2KwslT7O38oL3QE/PgbrTUBJA7UGq+2"
    b"9LblWVSUrzMbju3YztWfdbUZWylzRxm1B8Vy/4ElG7eZAwr/ERPaPJpda36l/yvPTdPI6AyNhq+jtTbxaDs2uosW261VC6e1B9od"
    b"sG2rnu7476UeLes82o+tHYFsPPgbypBZsXI2HltOQR5u83y9zS3WSavMSbuCVTLtN5uGTycQrwfxXZ9Bt333ezBoM5G2P/9N+SxT"
    b"Hdd8W0FuK6MfK8a3DBRTQh69YNFURu2nbjMhRWHrEP1uae0wWRzkVwFXtl9LUeVtWnxSQuu/C9OOORV9Z+PWPptM7B2fksbR3KXV"
    b"LCYaMQm3qRzbqyGOY0wcSJltXjM+utfGYZ+C0S+5yTYbbVfrskj/pjJPr2hV3B5lN1um2EbacwG2tFS6eBGvLuJ+k/YX3aAZhy0a"
    b"pdmjOZsjWOJJjeFc0a5L18W+l/DUVzRS/pBeuMmvv6Q9ghzTizE0bmO2k5HSfaNVfNkpb15lEwUr/9j2EiuitTGl4bri4KoMCGtC"
    b"S/UCWT2UB2Mrnboqg7E93NhWWVpfcsMb8IrtBGhqrKb2jLAVKlk0zhhP66BiKlvQZttsdNR2zz2mvOojmne7rLn3DVLOq7UbyQ5a"
    b"ZB2PLYN9Jverweg2XbthkXLhVinb6bA/n+/ZADKPaD3oOfHtfdonmraJkm43jxVPe+4kw+LsKl1ZKFt+7YlSFk6soKyDWjxfj3ao"
    b"pJn1EO0ymV87IOfisxlAdVJsyvZpt90A73B7TeNwF7CCC9TjLr0Tjo1c4TiIzR/U7r63ND92Hxw8pB++7Er4yc/mJJHXyCY8Zuc3"
    b"7Re/5Rm7sk9D2LEErVvs66x5M12nwBRmde39VkYzmJV1vSCLiYrjcUrQtpaL7CnnzmZNfX7ZZpRfaE/hR1jPl3nk85p5uyD1aPuP"
    b"7Jdm36+9yY4qk/SIRndMV9rudSf5/wzvs53aT1LfLyMX9zSCabrrhdr5gnYpuK1o74Vs8pEyZ59z/0DXFLbzkUaD3tFDb1WqAOei"
    b"ohzLaXoIr5sqSo0HyqaYrDC1Mx1TTqNf32lFq61XM3bsAQvamM4wjciOV9bBCLy07Y9qWf7f83oj7Z1YlVYrp3ghj3ZUiQEW4qBc"
    b"Ap3bGvcP1VUfzLvaLlWWE2yrgJZq91ubOf9b+0L/gceeAuoW4503KZ/HfLeNAG3TnMxpWuwYrXAca7ykGVLzE/exR9s3wPxzQuwt"
    b"oVCYSPvnp8H6ksFEmej1YE5TyJn536yxFKxi64rtehCJpR1TcCbWGg1blROL3rZo/aVyrBys/S29fQtcnpPnfkvLP5Kuf68rPLxU"
    b"jkJcrQyyfaUNzbHBt+db5k58WjeI3zSk59P13OyKgml5Nr1W62TWyE1+7aeVQ5FKWu0kY61po2+JtONBcnFiKlo3PTjPAn9ngQVN"
    b"F0WD93ewTpRvV8gyD+HBRh+l26LE228U572TtRif2b62lk9r2c/muU5i65e07n4v9n+cRwfk2ddrt55Q+NEybjbx7n28+mV3ztt8"
    b"8pYyqJ/RKk9lqy813uFrf9CX/KatfIvlRGnmzPb8SEOJbXw0KdaZUmoxL7UpptUkBbVG1JS1jSxUBF1VYMf63DeRdmyjmX1bWdea"
    b"R7avTWvNbZTRdTBK8Q7beSyX5k0LarVRJlo+i+Np3XMUZbFZ+rfUO0J7gd+Spe2hN09gmeelVPZoDcIc6rqYFtmD/w4DlUdgSrtK"
    b"8EKemUMLLJa6Xs+jjYpodtJ+tm+3zSFco3UfaJz1gR+gdYp2TaJM9Iv56ozavbygVpLblUbLU9ry2hGrkvLFTafY2E9BbgtqTCCr"
    b"fHcW2i89NQl0bFzC9go37D/nt2xNwWl61eziJr3ySNc7eUx5XsFDV7GPUxpJeIQuuu8noCwu3xdTaDJUFdRqHhuHqkaP1NDey5X5"
    b"3ZraJc4YvJI8eQFKW1a5STYOVZL3FqFkljtqCLV5edvVxawnkfYJiND6knDOB5qnu6/r84Vr5O+SYtow/j+m8UfztLbqaC/nUXrj"
    b"Gq1q2jeU9x7UtS5CqethamFzOG/4xGvNY0QoUr6j3RguYZu2z/YrPh0hPn6sdfy3lTVxS/77pTzKc/o6SjZsM0U2s/1R1wfzpaxT"
    b"a+7U4l/bKS+EnrGcOLvmVOOvmdSWj9UL7zEaRA7TzuXj+G+4co67a7/EjppF+IFP266jefl0Glozs/y0q2s+PBZ33NJI3DHl/K7j"
    b"tBmMbehDw91irG0cdjdFs4GTUZUzlWW0VJHNKs0kbdfVD0+CwLNa7XRRMwF3qNdjjTV8VK0CHMtntVEri2OTgKi08o0ZtMrVuDEH"
    b"Zcwh/inEac+k4lESzdml4X3xlZ2VktO0p+fbnHXkV+a1nfRtPtYU4hNu72r+wLIFwrX/4Bvladm8h89tUiwihWKgLKAkO9+XmEem"
    b"+FJLKaXTzplJNZ+fiFLF1xhiPB7Fcmy34TiU2FbtWPZveseuIWW5sumUoZee702viPRLvqfNZKYXKk1PZlD5LcZJwvdE4stNtaRS"
    b"Tm20b7OHT0CFXS3uiWYOL6LybB2p+fGrGlW0XI9DylDcrIhmj3br2acciL28shNLMyYIpVfsEzd5fFFZuF9WA96TDdieR6+0I4Pj"
    b"WO6fjfMlUHRpu/DYVV7y0Dr5sEzLBUyFTvlGcxUWS5bU7l/VNCdVRogsDdbKw4jfwRvtNQPdTPO5jcBfXa3AtrOsxiNKa5+JArqe"
    b"cSat1Eoki3WcL37CIoEIoec29b6vdd5nqc058GUxnGU8mlLerWtnrJEvX6c5uN3K8LFc3QO6dukmXXNzM/+Zatwn6z6rEaS38hQf"
    b"sfoEjuX0JaInLL/SssXMRnJq5UxB+YFS6Eabeauk2LqyxvNsD17LTC2skfFcihzM0yfXPmuBmn98oxG2h7p6xAPtwXcH27csHRsh"
    b"v6DZ4FBFoJfpi5Og8wbvjuT1GI5lEAboOnJBupJSal2hISP3wV/Ll4PeyM6ZF3spohyoIsqWC5Ynzy1PXkJZYvn5bCF5uoy0s9Uy"
    b"OZaYSFZk+x/ZVdVslMfs47auA2NzzZeVGWojPbZv32lOy8S/pGweuybGZWXX39R+MNelEy/x3gdwmrHcNek/i9qua83GPUXXz/j+"
    b"x1//u8yvXFBkdxkUHsWKT/Or4dq59gT9f11jDdekH5/Jgj+B0CjNBsZU5lQqWj2jcuLsSiWWJ1IHTNreY99LP9pqjB4wYh+t+O8P"
    b"Xw7QnHQfUNld40C2i2M1PlVEK7xMB8WmXZOAxJRYYWzHOPohdX2kWVGbjTmg3QxXg7LlPLKVPnYVxZXKJ1ui/DHLl1kHFrfw2iY+"
    b"s175/JbpuI/aGDve1q4oz3VVoHDtLvUYv/wCTZKQ/gjG6nKJH0vAJUW1H0sx6mmRagH6tbDGIHOrXzNrpMuuVJBBDJlazB4k/ejy"
    b"6Q8owQjlUdkI5AeN9jzSWOQ90HUNL25jvZYzYFGL43yJoR75yZ3HWnvwCpt4oit02Ho4my9KyONkGnWwveJiaGzWriTogjbz54nQ"
    b"VbZax67i8wFe/eSn4r2BlC9Io3NJtStpIs1/ZhImU0tjJqcmSWVDaTUrm11ItTnyzHxjen1jLO3X5fmfNA7zEQZ7+DW+PKcx/pPK"
    b"sdnFoy3Kyt6lDMcT2rN/o65bYKOPe7R2aZ+yti1b/KjyxveCsWOaebOVsGfplZuaR7Q5xA/KQPuAejMPlpE6FeRRNpWzqJRHYepS"
    b"UblJ+bXqqSgRTAHwFaJrC9fSqk+7bux32o3VMkRb0YNtNTphWTpN+a6KXzMBcvELIcpJs6wda8sUsEls7VNne5I90/ylzWq8kHq8"
    b"rhGaQ9pFKkye4Zi04H4Y0TLbt1HvLcr7tNHFVdqdY7MU4xFa5pSuZ2o5cUewQ4vTz/s2snUWVF7Q/Mdnej0CHATpSmAJYcRE2k0t"
    b"PzXLQekLKd+suK4NUI3DtEY24rGsejYbdbcxytTKv7DcpjhaUfLGT+TYWNlbzUbYbIMxx1P64h61spUdu6npfl2b64r2U7mrWbRn"
    b"Ght6qlXltynZQ/g7Slced+V3M/PdVs7kcKHN/WWSqsiluKuwrkeaCgZPobnMvFpfZvPUBahXCb6hmLx5JsWlQfBkqq+9/k7XgUjo"
    b"vNDap2ug4YoyGexawyfBygn644Kuh3FJVzK5R5ktU+w+r7ymR17Rxg+w+hvC1yueNf/zQPM8VvOLtMEZ4TkMXFvtHyqf5az2Trqu"
    b"WdWL0pGXQf9++uWo8sjvoGVuYN8v/Q8aD/Mp52ffdExGrRcI1l5RpXUtLdvpoBEc2Vn7Otgu7z/ClP3orW66cmxfXu2BB2+nlVAN"
    b"NcJTQeq7Kt9UUldpjOUYDgKcLzOUFxXDXNLI90mNKOxVhshq0LUAzlsOJ24hit6q68muUm7mWs0V2jVetmgdxnHuL9PXlql7khYI"
    b"1dUZP9DbH5VZ74rDXPolEehJqas0pKfH0mnH1CzaIa4sfV7KyaRZkaxasWdjjpYNk59P2I582ZSJYNfp/cJBFp3H0v5WNuf+mbpY"
    b"lokpj1iO7QwarlEKy259T5s+Vd6CsaPtheXT15bBHMexPMwPIMDWQdn6AMvIsJFRm6t4z7P2ncZVQc5bYScB95ZpYjsYOLRhhJ8W"
    b"hk3NfwmVUxBHe5ak15xTFpi8AM8UUuxtY1n5tKtrAepra0HSc5tYq3GSSKdl1Tx2epCQju+0vLkIzTLfVjb4FbznIWzmtPaz262M"
    b"5g0gZx2Pvswifrl6+SHN2G+iL7Yqb/W0PmF+/oLmI29otMMyeCxeeaqR4OdSjXGVex1PYxeptPo4lfIx82skwa5gXV5XQTDGyAq2"
    b"CirDMxi85eO/4tqBooZUZWU4sJpivJLYYzGN0wZzb2t/0ugqLdb3cfh2G22wqynbOElMXUfI0+iw7SL7WSuLz4Koi8qCu/41U2mf"
    b"sjwOazRsn3IKD2ut02GNMuyDDY+D1bO0zEllsl+kNW7Ao6bYjmlU1+anToHLe/4HzYMkpK2TUp6klC4V9cyukf6suoKdjeCZ2q2v"
    b"nSxNLzbmleZwUQ16tgRHLo3sWb6Z7UkSg/e+9y3Gtv3eHsNvD3SFnQjln9zQ7rhnqeNZjTCf5JUzPGv51M/EH9fEEa80m/5Ic7vh"
    b"YPspqHNpqWQg3LAfR1acQ1onqWZsE1HS+EKY5aMlohS2P7CxYYgsJxfvs5mjOGAtruKjSD8XZwplCBijfxIKvuwW52v9i+V7PeC/"
    b"p7pWtrH2A+UFW/R7XVeJvqrS3tAVBZ7Jg7/4P1fv9WRHlqT5xQ1xI66+NxUyIUpXtZge0eTYckeRs3zYtX0huSQf+XeukQ8c0kib"
    b"3ln27MjuYXWXAgoFIBMprhYhzx7/uccFZq0NXYlEihDnuH/+fZ/78c859/e1AnPKWnuJ1vwDddDW/+uGvgvxmbyiov6Wu76jzn7F"
    b"pJMfOJdyz7y5tf99Eh0zvxcn1DUBXY7C+MgZlNIVc+nX4ac+D/+Zv9//xa+7/xX96n/0EVJYyH8b/G/+v/+T////zufrf4Ub91/4"
    b"6PiHnGX0e/6ZiW7wh/6pPvJPb+0Rzxs3w7ux4m6l3voHXOr/yUfJ/xfu9S/JyFJl/3/w/v8nHTv/normL6hU/gK9/5dMKNA5NtIH"
    b"O6dOuAbB3dJ5FAY7Ov6F40s4w/iM2R5XcCqPDFddsCpPOFFJnCKPWKOn/ur7dH9KfR35N5tQG0g3iegdQSC9YD1YozFVQuTfbs9H"
    b"PJmGKTl37f8mE1I7PuJM/GqV+FehfYVMVS2pgQZ+/UmH7IE+9hl9UyEdVW+dxMEHl9ID0eBxkVg6oGds5KPvlAnmfX89mV+VOrcm"
    b"QqORqBj5NzgEVwxZtdKjcOHvampqx1P/VZ/67/wRkULQ6wRE+9zvAunkKHGHiA/sBa7wG860+BpdUWKknEQtKuN/5IyLX/o38ld4"
    b"z/6KavTv8Yl9Qz35W37Ga86zWznRym/9PW7wRcjvDXBgTmEc5a2ccFbgB/76L/z6ER+gTIH+E3ru/o3fb3+OU/V/8B+JR/VDv+ae"
    b"sd6eMjHjv+W0xD/zH/2xf3u/zwwRfasDemA+pkfjBL5RfAyy950rOPP6FT7WJRqVcMhyKq70FrzkvOvn/j7nPgY++NgnPv5/7/9N"
    b"8sQvqJv/Ek7hr5neI3FUMONzPHNf4V/4DefG/cCsSOkJ3vh1OvJP/JF/Bqfk3Wf+/n/s383P/eoUl8jPqFf/CDf1T3B+/77ffR/5"
    b"PPEH/i7+jf+OP/KfP/UxsguHfsLJXDO/UoX9EYfPgV0uyuG3uEZf++tXDHVPDHkOdpKK9m/9E/iSs8+lE0Cio86Fqv1HsmOn1Own"
    b"TMKSdzVmHsTnTH2RCd3qqb2EsfiMCeof8B6n8EEnuMskmvZhfTTOnrCLpIe/djLBYE+PZQAnufO/90Bn4BxfrLpmX1PzrohnP/j/"
    b"vaCCvmbyhPhxtnCqr/3XPPiv+d7/vzgxZFp2N/hLHDy/9U/+r/2f3+Imkt7YHXyP3P0g+NKjkVv/GY0ea9MrKidswBQPxQf+Dn7m"
    b"n/GPYf//BBedVCb/2v/9X8MU//d+3f1b/+b+Z/+2/p1/Q8Lt/NSv0T+AQ/4J6/gT/86mvGeZMyW8c8gscOfvMgikH3rrV18Nn/pr"
    b"EPP/Qzfqr1Ch/g4W+xfsvF/AK8rMul+jD3zJ3FtR73/pn8OvcSP9k3+ef+/v+Tf+CYgSs3H3aLIX+G0lViV0g0hcy32Mrp14XUfw"
    b"NTN6+KeckP5jOLtn5qq7wIV2gsr+qc07kPn5EmWlw2EapPSZhP5n1OaYiXFWiAa7YLqOaMXS+z1HKb73OElQbS/4zuOWH4iE3/uv"
    b"e0m02FqVLl1Jd3RS3Pnvv2d65Sv/hq7hO6W/S6Lqzv8O8UvqmaSJv9JO8CExfAR7+Rim8QtO0huDhD8h3/+B/9tPuatzau+e32k1"
    b"U4Bk9S/8TxNGoIaJegmWem69BL/2z/5X/q39nf9/mVP/H9Bt/m+/Pv8Pvxb/Aq/AL/zX/u/+Dv4vGPZfsRu3/r3IhMQ1fiZlG3N/"
    b"LzKBZAyXMCMny/N9xj76PX/Vv8tu+2Mqzie4rD6DFf5Df+V/iOP9p5x18DP/dTLdUNaczHPIfARp3B8TK37un9Cf+t/1O7AV8vZO"
    b"ySTye2t/p6WPjjke8w57Mse7ITrbSxxyb3D3vDGvsCih1/6erpm88w/06/493VKCxaSb4TubdvD/+7/9kmln0if5nLrvGzSAW5sy"
    b"9NzFcHwdriHzT/+UFfXUv70vmCZ+yu5Rn8ef+2v/czign/k1+nMmeX1hrpvH/lk85czk80DONancYzL1Y38fz4j3gsNEAVnh3HqJ"
    b"837BHd0yf+t7sNONkzmJolvcUNse6KyP/aob8cYk2spJlLLOhPkuTfV75lfg7/iPJEqm/nozf1Xi1f+UfCecvczZP6Un65IsMMUr"
    b"OMBf18Pbn+AzFcVd3CDS6/eGymJDx/SOPf0tWvxb/6+/8bHsV6C8b/3//9o/0e/oeP0tM1BfMXH4peku4tDZ89z1DN9viJE5ThJR"
    b"BhIfJZLgFt1lzSqQ+wwDqaYH7K8U5kPuNoJhG4OXf0SP1iUr73dZg1KB/ql/K/+SakW6df/If9Wf8gaFO/8XaFt/4u/8D/G2fsLb"
    b"GgTnvPvc/6a9f1dyOk3ur3bt73nj73QJ//81/oJfMfP0BWvsP6Gy/IOdsfQNTvXnfjXe+NX3lq7Kr2FTX/if8qVfz1+ivT1QTTTk"
    b"HqlR9z6GvPVoSOrsARhviHYbo2Cs3Rf+Xz70+3Ti317j3/LO/0lQBFKy3xSkOUbfPCeWPAY9fkbEF2ZQcOQz/26fcHJgwjyRhFgj"
    b"8xDPfV098T9V6h2ZLLL062yOWlm6lrPco2nfMKP/zl+n9NMX/j1LfK/J5DLDrmT3ys8QtL/3PyNiXsnBCYdzCZtzToUsZ6KJp/Tc"
    b"v5Oxf1+ClD8j353DkEu9c8ndTGELxuCNsb9i8SptYVMX/gpegR2vwY5f0YfwH2GsXnCS7Pec+/4LnGZ/g4/37+DH/9bfyS85bULY"
    b"7V/hi5COTkHBr/yTl+ehvZ2VR6ohZ6M+4no+9tfxBczAh+x5cYJ+iqPqc5T6j6nTLuEPn7I+Rbu6AKfMqNs+9j8t8x+FKPlTFPw2"
    b"JqpiKqvd+auQifuCGIWjGwdSQxV+HTn/Jmp6K1b0zs7RCdZoujscSV+BRX7j//1L2DGp2h7I7q/9it1wrseX6ALfgF6e8zW/QemR"
    b"ym0OLlvSLyT4vHLCaWX+WibUNwMiiEynkMnhQ3oEPoTlk5OUnjEN8nNOj/gzatpn6ANTXJtXOBREo5O5vaJ99vxaGfj1LxXihj7O"
    b"e38Fr/wVvCLyf8WJXSsmnkuMeUCnlcr6nijS9WuxcYJBG/4ncVH47p3HHTIRW3Q+waw94uEEp8Tv+Xv5hD64T5ly0IMR1TjwCPYn"
    b"AV2IipRxRkUaiBt55t/CNBD+t+9z06lf+4IrBMO+trUoPdQPxyuXCvoODVb05i2Y+EvmTfy1/85/YGLyL/3dy/sJgr/xMeBL9tVL"
    b"vw6v2Vc7sPEB/3EMfg3h4aRjWpyZ4i/JuC/ROMWBJ5XHhJkEo0DmlYnLWHpABS/Lxz/BZ/Ffw8n9xN/vv/Tr8ndxVv8O/SQyh03w"
    b"p9z/R2C0BBW/5snOOYXjjf/tv/K7/IYM+kv/1L+ynXTPabAv0JPewhnf+p23hjm+8/++gkfQlXbLWxYNVGLKA/W0aMhzXGs5Uafk"
    b"echcnYP/TQ1TAeVMVtHNz3wcuESvPOdkiMjfU5/8qyjjE3/dn4EVpU9LlGLxTkzpPnnG25eoesUTFC+ufLf8DMHhEflVHM4llbGg"
    b"vRpE2PeIsRuIaikxcY96e+v/5Tuy2IEZ+4peZMLIPXe04HQbcV453mnMTzyAiGVVycnNGfchf6b0w13gWRP89CGajCjYn7J+r6iy"
    b"Iypu0SNDOzVeNILc/94I9vQ5UVrOHfuWtfgKj8RXaNjy5x/pbvrKvxPtvPoOd+NrTh55TsUjnUri1VjR8RrBKIjyMwa5jYnlE/jc"
    b"S7wjn+BMecLs2Ud89DEqgH5mBv8rLPAQ3kecBzF/kz4u8Y/26KTJ6JGU7mVZ1xLzxcd34n/7hb87cZOt/L3O0enF/Sletr11U1Xo"
    b"1gUTAxuQbsW6EpVqT+dCSX+BdE2sQVq35OcHeg6/Zc7oP/rv/3v28Jd+n/7af/QcNHPNlMhrfAzfMFFmQ+2qPcARpzRMiNsTzlSX"
    b"9XcO//8hueH36Y//DL/XB8xF/4SY+Tl7U/hx+coJlcMplU2Kfih5aON/vnSGzKnYfkA5vKWXUVGxzmh7CxL7morzGtdL499jydS1"
    b"2l9p16+/Hvyg7OET/kTEOKlbYtzAunM+wHsrfWlX7BL5jGDGJ+DKnr/WE9ifHvc6pu8kgB/a+/eypdv/gBu0giMTf4tc1Z4rFDy0"
    b"ZBqvYMd7/9GNf8JfU0tLbBBc/Bov3XNqyDu8CAfuYs4ULJkGdOOx9Z2TlbLwsfye84AkWxduxpl7z1CoP/V3Kf5bqa8aJyvuMR6Q"
    b"j4j7A7K61p7n4MoT/9khDNYJ1eanPAXpZfqE6uXKv5GP2W1Suzz1GOkRtUsaCAd97ffdNc6Wa/+0f+OvVdjHNdX/C1ad5NcHmzYk"
    b"qsBzHCbX1ATSyXPPjOjv8RBKBtDzOl6jfyxw4MdM25L1F6Pd7enZO4AnE4sroqjsQJRDZpwKdhqhFs/IEh8HI1jICI/mxK/DBAdQ"
    b"3+dzeVKCJH/E9LlHeLnOAj3pJcCBLVOfZOcJy9jAMO5hmxtmGJd0yD+gkF6TEe+5lyUOVbnbJfXNA3Nc7sEwK9TwA+c/bZg5soF/"
    b"jMDDU9D/ub9GQR0h7+2MU81+igNI3t0X/qPfBV099df+BTzBI96YaJKP4Ez7sAHS7VfQS3fDLA/hw4X7fsO83xvc+9pL/fdMzPpr"
    b"mI3f+q/5W3+tv+F+vucEcoktDi+TKD1T/yxm/nfI7h0bxygr6go19CfU+p/5f/25v/rPQYM/ptJ8whksV6y1GIzZuB/5+//I32+E"
    b"lvSx31HiaBKlSvxJEXXKDgXLoXVpd9LeSXTeoxdLJSfPb0NtK5pMiQNvQyW6huGVyLUHT4o7syHO59zTDQhTcvAb6qAF8+kX1C5v"
    b"YL/l/0XjeEnM/Jb5zIrZ7nnTW96wRB3pJpTrX7sRuPYJq+icpzAGR0sN95h+R/HG//joO/uv/JP5ExiTn/vv/G/8d0iEzHjzp3Di"
    b"IVMqVfsTlnvJGTkbdtdbuth/wL8l1/sCr4fsL5kg8I2/8x/Izi+pyaTOkWewR+0Uj4vEyCGsfg8dqEMHor5hWYvP/D6Q2DHCeXaJ"
    b"p+IUl9kVXyUzC56aHiiaR7tvJvCPNbv1lq6qFdix4EneozF9x6zb5+js13A/NzCo8rHEj+/p3pczDV7Cs93hF+kGO3qTtnbdGdPF"
    b"ZRbThJpCGIlLFE6pHC9tnc6ICVNUWeHixpxMOYON0z8znMZneAYf0TUy5F57nEc9ZlpKH/ZLWYQYp8SOXCN7+Q68JNlAlNy3MFol"
    b"HKv4A0t/Z9KHO6dTQWJfwVoTlCk7bE2PReHfy5o1WnDHjf+eGnx4wNcof9v6f9N6VeqkPS4N6fUXZLDwz+MHzjKUCY2yix6oeUV5"
    b"rujClgkE6lm94gmNzRP3MTXBpzgTZa/+xM6wOeMsOHEUXsKsyEqY0emR4KLrBwFc5NY/hwX16paupBoscs9ZzG9xjm9ZiVLVLNCV"
    b"7li3kr910q6wyI56RxgrmaxV0LWsTE3KiSviGhyT3WLU6BlVzY/8FX6A0iEuys+Y8/0U7UO9n2ewB318hlJJiIIkbE8cvISjuKUf"
    b"8xUc+Jconi/oIZHeyG9gOkRv+IoJoLpOF3D/EtdzfJ6CBEIy8zm76Izsk6F8XdKz9BP/jL/w1/3Y+tnPqUWewkB+zPVLxfiI2N9n"
    b"/Qm+D3EtC1suLK84/eQ8WznbuEH7kthW27rYMYdA8J8gqB2TAB11c2mdVEtWzIbZ3Qc+o+uqgs+QGN+Q5UKUNlHIHDlYptnJHJWK"
    b"WHdPrn7L2pY3LN30ok9f42B6w0eihWrVIOtUfnpJhBQlJaX+UBVbUMc5mPCEmuxjns7P4ZJ/hKdGlCZxyKoaIqtxTCdp5p9c6R5R"
    b"wUyJumv61eecSuRAGuKrqmEbd35tCY8jV/elvyZBujtTrsWZqjn6wLq949k8wA51Atl9XZ73gHMZBfs9tjl8gsNEl56wGhNmn2RU"
    b"YTO8apd+hyjWV7yvDL5gZ9FB5FkP/Frs+rVYUGctUXJvmIlzsCllL8g2d2CqGyL+DTNUHuj/uiGer6i7ZJ5DA7cvDpMBc1+6YFbx"
    b"yoXMHrlA15Se2x/7OxNU6NzncIKXViNqXLhAkzq3OvOEXX9CDSMV0ZR3l+KSyWCrJsw26LC/5FSeDZqE4KYH8Liss3vW4RoFbcsk"
    b"77dEh2tDUHNqsHsw9Ir/bcl0a1bQmp8hDpk9b0QUYPFhz3wFeBrIbExh4xIy/4b+3ZCTsiVedgJFAhm1U0qfvfQBjmEbRIeQ7inJ"
    b"bhv3hX+rF7B3Uh1cUilc4L2+ZN19AI55xFmcM2rUC07UHRNVpX+/gxLXg9fU2e6iRt86wWV7OgPi4O0xG4prPffve8+JTHPQ4zXz"
    b"rfa2Pm/J3gUr9g42dcv/CvbrwQlOSkF+IRVAxtv+wP/mD0DDH4F/hUN9zOT7Hqc1n5INJTeegjMiODnt6Qupnu65Vod7tPTRcBj8"
    b"BzqyRff6K//nV8TvF2iHN0yf+o67mJPTInJQCesrquzWibNYapO9+4xK7JyqfgaD8yOiuPz9Q3jSoY/iY9iLc+LhM9bkhPsZ0mk1"
    b"QXGW/C/a/RO/HmaB8LjCVj1iXrRo0Dqf8d7VxD3JrRuqfIlmLT+tlbPWnTlnse6JnlsiX8NHsobl/WlW7VNhzpm95VA3hZ2T7q+A"
    b"d7zHTXbPOe0BOeYtv/0GtkSmudZ0CDRc4Zq316GPcoIinLGielRvn6MSSiXze0zlv6Jv+QkdAh/iTpIKRyq2pzDkE9DKOQ6pMcyR"
    b"RJjEv8mr4CvizY2/0i/975Suuju4gQXRZc1867/xq/Mr8sdv/f1JH913ZJI56zVmRQh/qbqyeMf77DOZ0HiFopf69S5nnj8BH134"
    b"9yBuXYkgIyKI1OEf0i8a4YDc8+99pg4EMHAyTUsZyAqeXtjhOStyz1NU5KTxQ6J4FHzNm/vGX8U/+nt8STy9BwtN/ROXyF2A06RK"
    b"jEAusstFzZxQNykmkgkMfdjqIfyv/m1GZIzBgo37mDMvLvxVf+F/nniGnb9v6Y/swhCccC/y88/QOHrMUJEZWKcosh3/xE79UxTk"
    b"uMHftybnyNOUE/VekHtkNuUP/h5uiO635FPxpb8lQyxYYTIHfsOsoQ0rSaqbKJC12/P3fOpXvkwklMx4a9kxQG0qeJ4RukXAXCfh"
    b"liSSTLk2qaxino26SWagkB54RKYd9unKm5q/8bE5EWYwdye2rxVpyx/JhxGYuvK1npw1LUjg1F/TqfkZV6BnudpbtOAfmESzhy1d"
    b"gR439I8sjc1a4/R6Ta64AXsI27WnVshBZCvYR0FEAffVNy41JGqcM289g+npUr98Sjx6xI5LqXMujJ0as1rFoz8EaYiWLJXomj59"
    b"cWoKo/0V8yMOMGy3oJ+v/Rv5J39fL8l4r5nZvAU9vSVPiRdp7Xf7En67C68kT3fK2rtAy5qRe06ouUT5OqOWeQRz+pj6ZAR+yli/"
    b"uoa7ZGVZoSXMRUY0j3ina0MzFSxLH+ZdHAwye0BUrTV7puAJzpkHovlX9ZENb0TnXN3j6xC37JpM3A/ucZ/qylPuQRWmWxypcs97"
    b"3MzSn5XgdpUY0uErt0Rjdb7K70vxa0mEiZmoKfy08F8yG6/B4T+gYjmDu3tKDhEvxecowB9xvtAZfz6EHXnCVw2p8CSjB7x36Vgo"
    b"mPiaoMNuWC0a4eSeH3B+L9mF34G0xFkoVavU1ms4giXK7j3YZUNEkuwsrGxuuLrAa1aj11R0jEt0KIjzsq5kBrWw4gMUJ4kxovvm"
    b"TjyPUoXeu9/3MewjuJAP/XO8ArEkzANpQOxdVpN4wHT/iFdUMt4cXjzH9VMz78fxJkucWdJrHoOK5PqERZFZ71N6gHowFwdU1FPm"
    b"+F3BATq4R/FFS79/5WRmgVQqpb++g9Ne/Ctiv3D9GWp7Biq88E/3CSeWClJ/DOvVxQldovRUdB/V8NoFMWBFRNtTQeRUHMqg3aPR"
    b"L+FpNmSuNRj4Bhb8lrklmuW3RNQlDhDJ0XNmXsn7Fn/0DZ3CJR3tUlEFOA665GFlmkIY6Yh6xVF/dsB0mf9I+6Qi+AY5M0M7Xc+t"
    b"164Dh3oJhn4GP576VTmCV06IMGecKKf8v7AKMV3CGqGSoGQyV8icsz2q0AoXU8Pd78h/b8CCugJXzAJYocvdodB9i+dAeIVvYKYf"
    b"LP6s2dUVDHNOn7JUrjURIqTO1LtLcRtN8U1cwKH0qPz79MZcwdk/tRXgyPUXgZxdL31ME6aDxmClBc89R2XdGx+wAm+95c3e4Rlu"
    b"LAcKpxHgxhQmQfPQ0K8S6VsUXkn7yGT//tT/rh/btInS/CATqq8RDpEf0V834GlvfHQv6CWSFS09uhl9FnLnPZ/vZlR5IY76G+af"
    b"1cRBmbA/RPUXR0jm47twLGsw046V9go/VUVPcj/4Bo5rzmSOhtyc42pxVC/yLMQDkcPSODidDitQ8oDwlw18ZYwjQb9jyVOUr9Ln"
    b"Kd1VAQy8xI2I+DXlnY1ZRzNW1FOi4yUous/U9kuw9O+Yj+SKz/8ebsML/D8BU4xPyR7SMy6IZsD8XlmBMT7ab8G6b/zz+Sf/0Usq"
    b"uOd0TsypUN7yvxs+0m7P1/A9W1ieis74NzyTa2amKgNZH+OjZAlBaBKRQ3BhQzQSNDUkhpwbdzUkIgnP1ye6COsv3LlOBVv5GLUw"
    b"zWzk3+UYTFSwslb8UeZ9R5xRRk0QfUy9WOKWEwedRMYItlvm7FbMfindBc67Mf3SAU+8cY/pUDkjOibs6giuMKJCllNt9k6cAJV7"
    b"Rv9FCPoQTSogW8u+i41PjIjsGbhRI+OWjtEBjmbhUSXaV4b7Vqgne6LCAg5jQxwUjrr2O78Gj8g7CljH16xKyb3fc/LvhtpHn8ua"
    b"bK4e6h5ThSt8MlJfyckUayfV4d6/gbWpxn2uuEef3AyVOuS+JVtIfojgsyLU6UewCx/CHHziv+IT0Pbn/qf8CDQpPoSP8UuO8RJL"
    b"tEmIQcKYdHCsRUxNlPqrJnqVeKhq+IQSNko7jG9Ai0sqllv+/zV84y2Kxhv7WFS6nc2xuAdDBqzPgvUp57BJT46gYkGsr1h5O39X"
    b"osnKickzYuA5s7mEA/oMP6Ocq/g59U6GxijnJIhaon5NmQVx7z8zJ7s80NPTUMkfeJ/yZ0m0zNEolM/b8b7lmnrgFGGLxDMz5adG"
    b"sJqV+8R/5hPyyBM8HwHsxTlVpDiLL7jic6aXPcOvJ7ztx/6nPjMkImxIiJ+0yxtfcPbSPfVTj7MtO/D4Et3msNU3sLUH1Nq9dWCU"
    b"ZCVZfRIldjBtEThkSw44gI82YMFrv8rviXsLsIvoOQ35uh88UK1Ibbl2EhOuceiLUvEDEVuQ7VuuMsLNJfWNsAsBldcoiDmpPqPe"
    b"VHVsSk0i3mplhZ/he8x8JDxl2l6Gv/8TKpkv/Hv9GHbyA5iUDPZk4Ws/6Vid+TxwCZbQGLYgx9Z0uX4LWhG3yN9Sld5xgoUwOXNq"
    b"7Gu09duj93EJ5/PAzq2oAmvmLAlTUDl9EkkgOWQMT5DiiVz5O+yhtuzQtlO4mxHvP6QKHeB8k/nLA/50UElk1kPuBN9VVMOirOVg"
    b"c/lMCQIrceLkODgcfoOcdyE8ztL/kfc14YQmRwYNeTqpORj61EkTPjflmgTpjWw64QBtM+bqUtBhj31zcOdgLDnh/AN+tmSCM9ah"
    b"zI8W1lgyQmJ4rOCt56C3LnHLUU3MQY1arYgWIhOhd/Brr1ivD8wRqkFFL8GTr8hNymTf8T0r1MAEz9MDfKPqOl0yhOzFPj61jdNZ"
    b"micoHzGY9+D/CPs58Vd4abmigw9sZHz3DMTcBwGOqeIeU+ddwt2cwDdeUEE/RqWSulk6TWXq2Ama6cf+qTwmHp77a7jkadX41kTV"
    b"eHB6cmHIlK4deGVnU4rv4eX2xim85CSNgo7Qxv2jv9uv/fPYULl+Y2c0PbA+V0RUrSvuOONHTo2fU1G27p6Suz/FO9clY/epZ2Ty"
    b"x2Pi5QkceQTjmPIc5H2XIJia82TOyDsRNbGw2Qd43AUYYQ5iEkbnNZnq1q/El3T6rPEijOCK+ugANUpMAEJI4N11As+IyuozctU5"
    b"/vUQBTCl8h9zksYVM9cuDHGmgSpOmVXU4soRrLukKn1LfSsx8wZPhOgbtyiUjky0gc+/Iy461zK+UpUdQLwr4qB41AVfvmbfvfTP"
    b"4zuXouR18cI01ELi2hxyHvUexncOo9wDZdfM9NW5/BHIZcOOlSpryfzemrpnwNrs4l/J8B2dkHN17ugQX+AHrLxLfHUznKoaKT9F"
    b"IfgQ5kGw5RX5RNahoHLtbh3hYN6AHbdEaoleK1ZOjR/G4au+97m35KT0FyjBrywn33KeRQnrLdp7jkfkFv/ZgTwv2Tiif8txzwem"
    b"nUqskLpM+qalT6ELi9gBJw6ITWM0oi5XK57JAJ5ccqd4mXZwpOIxFKT2QIwT9BVwIswWZUG7XOX8A8nJKfzvni6zOextSUevRCip"
    b"9BNiVZc12IVJi4hze048E2/AHMVBsKysxtyvz7V7CkslsfWZ/zNjj/dZhSle5i53kIIV+8Qbwegpe0iUtQTFR35zzQwswWeyWl/S"
    b"G3JgjY09lunaaWIHarLIVy6pX3OSbd7iNG3g1+bgomvrGlJ17BZ2aE+cLI3l2OK4UF+OcOUOTm/LumvA4E/973uERtFHLVv7e7/z"
    b"+3AJe7p3P/PX9Af43gTjf05PeYLaPCT/fsoZaafM40mpqB/jYJ3iR8ioezLiaeM+8j/1MafLPOO3CqMwIr91wRUbeA+p827pr16Q"
    b"dQ9EuNq6OL+n676gG0OywxIVroL7kekBjo7PB7L2ElSzoqa4Iz7KKqpRPmTaSR8nhLIqMr+04vThCJf6U+qXKzzr6umc4VLrw5OL"
    b"Jlfg7z1lfp3EtlOcYHv40q3ptUv4eMlG6k0/MK+iQ2R44D67cB4zvx8f8ZmIeYMNH/Xhdzvk6YRYOIDvvWCux4zKWvz0MU9capyY"
    b"qUMJzIdUYFKHSndLh5Uq+LwHShInn6w9YfF3+Nh6Qes82R852larzmEexQXXQSFZwFPoKdMb0OOGGKpaojh3JAtX+AMSTkSVZ5+i"
    b"FeTU1rIvH3gb4v05UAHuqHAW5I2K/JXCW4jLSNXLhCcgOUv8dDKHZILHJQx+7O/sx6w90aJ+x9/5Z0wI+AQvo/joRMd6jBL4GA1u"
    b"BldSoQyIVrVkhmJKVZ3znuQufuPf6Lfsxa/9df2a2fZv6D5ZcHLFAcfxnHrlB/qExHG0ghN7gJW9gz2XFbFB7xrBaAgHeOmfpSCE"
    b"Lm7SZz5/fOj/e0pkOSXqKPIa0ymRkhdkl4Zo28LAzOh8HFP3SLbvwBQK0liDwVY4TDK6Kgo8VyXugb49ZUEjqoCO4Fr2zOU60MF/"
    b"wNk8QC+6RCM8MAfG0QE8ZZXqO+kS81IiacGUohrX3xTUOMALmaP/CSrtMi9VUPKl/28fLHmCyykyZiODc+ybdyfjCUm9NfBx8JJ4"
    b"uIUh/47eoJyuScWGD+jyBW7NmlhwQ3/GG5j9Aq/+HUzOCh9CD66jotunAE0XuGgPMPMxlbTE9JquzSG8h7gLnnCvU1ZiwAxo1d9P"
    b"cGX18DAJ1yXxMqS3LvBxsmFW5xhNQKoXmWUjiOzcP4uf+vjwAZzxpd8pT0BZ73D0gl7BEOwoWuYA943zq3Dkn4JEkyVsw5o4+TXs"
    b"2JoejDj4hgz9Bn9FiT6zhRt7AQ5aEo9Kar8D3TZ9+loS3ogjsoX05dWgtDHq9RVZ+4zuxzGYOQRtTCw6hdxnB+5rQ5SUmufeTdjZ"
    b"wqfV5vhbmJOqxMXyAD/XoZ4NUS60L24B93sgdol2v4Z96jDV8pzqY0ikjKgqR8TKGL/pBJwha/cjfxVyBzJxpuKa5Ck/hcc88b/1"
    b"M/9cT3A5n+Bc7DBDt3X9782dKC69cfCaq3oJ5lszd1eu6dpflWq4wh688Fd/Cx6/53srY0RyssGa1XZLnOxw4kzXr4Bh8AZ3xgY0"
    b"MOTulRFzfMWG1SkM2D2ZRnBL4/qG78+oIMcopjHzl8b0nMxQ/s7s1JwxmsyIufSfw9hKLfMxLuWEHiPNehfkkoSe/x7+xiGsyI53"
    b"c0f98gAfckcFt8YJIyeWrPDDiA64tL6Ka3x1sgZ/gGO4pY5uyCorGIcCzCN4JKXqFVwmeTlgbvacySiiMK3h8UJqAPVeiY57xQ4d"
    b"4KSR3jJlSSdk0SGaxr3/anUJLeHLeiiFFTpNTr004q1XaK8H6uqYSLniBKkt9XUPHUTqKe0KjFGNGvBLDrrrwI/moBrZOw94H04C"
    b"8cVIfj+xDpaICCI/QfbEIzhFzdQJ/ECGT6WGSXBwVAPYfDm1TP79QCXlqMO6YFvNndIbU7D/L4KvwN8v/Gr5LazuitOX9Hy5F/QR"
    b"S4yQjpHn+CLvzHFxR17fokQI91gzZetADqnI5wN+awSCDpjc3SMrddh/KZjlHF06hVVM4L2eUteISqh9hI+IgCmeCJniNqSTpA/G"
    b"SVAD5Sc56tYeeUQrCGFExBU0RC8V/XwIspCIkoEeNYZIVH/hr/Ub3C7ap+fwq77CT7zEzdWewVuS1x+oZX8g+pSwFfIMhAUU7fQM"
    b"FKOYZE+EnhAdx9QPfTiEAbg3wmc25DTFR9zZGVh4ROwP8SEMDHFveL+SX7SXu+E3CmLQTlRBio4Ky1ER3ICfDvgSMpwtD8SQPQqt"
    b"doRvOBHB4TU75Xo74IcY7nsU6CkSE5BGB79pBL6/pNpPqK1zct2pcfdbd0Ze7KIEVGhyqpyWxMUc5ndPlSERbknEW9Af4ODD5crl"
    b"FIcNZ4w05qXdgJMX4L8t31eDKGtcZYJTG2b5yLkTwnhrzGwsf2xZl1swpMMbWbEm7nk7JZhuBhc2Nvajx+o6J2eLb+QZ6+0Jju4x"
    b"HaBDPrrE2fQJjuVTVBvJI5n5f5Rl3vlnskfx3RMV9FyeBzqlSxwHQXCNy/IVu+9bfwffkqt/S2W3pbbemg93xc67PvpD56hMDTqI"
    b"8n+O7NmgM+WgrT5ocQB7HdgOTNhTzp2Y+hSxEgN8b31cXhILterV6B6ibErvkFSnemKeIEuH2rdiv4vWsCIDO1ZbyJoN+ajCMVE4"
    b"nWpx4Bor/pbymYKfVZFPE7oEDtZtH7I25z4mS1XQhznP4QsKeLuGWT0jZimckMEF4Y78556Af1P2UuP0rpU1CLnvGk5SVv0ODqIi"
    b"nkcwBA0+iY2dBHYwrmcN56hoco6D55aIsMIbsue/azJewecj1EjHaemiBKfUD5K9Jkz5kog0hSXt0PkS8fQTNOUu7uEzuOET/CGC"
    b"VyYgKp3Y0oW7GeALPSdyjvmXlLmLQ9OlI/QdeRIB55TfcVa5ML9biwIreLcAZ9MoeENdtYPHb6jeDqxCR+SfU3G/Ma57aYj6jrt+"
    b"6e/yOXqrnEP1PbvtjlmhNftXflNoTPTW9cGOPWbwJ/gSesSUkL3UAyNe4qiZobj30AJUEZBKPABBVqxUWd3y/h38Tg+/eW4sU8C9"
    b"6TS2AxFDVbM5GUvjUAcXdmH8eYf1J2ssoBqpiegJ9XECR67ngHW58gEVl7LhGc6CCXusi7IpnKowOkN4hJrJCDGceIivbEtu1l1S"
    b"W/4M4WaXIMg5vHVNvZmDgyoyTpc+ijXY8g1ZXOc7LVFiapzxs+AtPNg1lXuFK6NDDV0RUXNU6h0x44C67ax/tYJ/VAdF1/ipEe74"
    b"K2qxPmx2D3fVDE4nxNHTY275p6xM8U8/pk90yCp+xJo8RdkX1SNlGtsGVrNgr5fEfmd+iXt0pT0OsoIesxswxw1uxrVNcF6yH5es"
    b"0xX5Yov788D/tLvvAPYpmdUglWfFM1enbI+7HMLw6Hy/CE7vFLQcsgZFY5M6dESsEV7SUa9O8UrP/D0I6hixWkY4FAr4E4dOKLEw"
    b"hj3LQY+OfNhlB+xgn3dgyIwTyGL/0di0uxV6QBcM0yNy5GTT3OKpw4cQUwVKHE75vdqJGRs/5JhboqeQpMTCHpjiiqjTR4PKcWcp"
    b"p1rZZKMJVY5gGlkdPboGH2ChD9Rk+qaWVMYb3o3UKntzzc5RQ1dHDl1VjDUrt+Ljhhy4JEuLKnVPXV/wWyRrJqCICWxBBIpX784A"
    b"B5muQYf36pQ4J0i/1e4noH/BMGPqu8y0qwjUOWT/njDvIWQ3O8tvKe6uFBajpMLdgri6qEbdoOUAcuJizbzmhN5GWZFd/HjSgSCO"
    b"ixqXp/ZtzNFYCzKEPJ+AWWZL282SX8TLNwahJuSFLSfqZnALfRRoWXkZmLgLc5Dhpe6Bn6fMRtEO1x6YMTV+fEjc6lOZ1ehdugYb"
    b"OzuvMkyUm/90CYaYw0OGNmdNNNy3rD3xEAielPU4oHtWOIABTGmGX7GBzVH91oF8puzzx5wgKRXblKedEksz8Eh1rFj2vPkhFVOH"
    b"HblEIU7x+ifEyi1PSOqnnDq3iyOkBFVuj91WOXpFzBwlue6UyvkWD9+d/5kvOCtKIu0tFXoKd3IAH4sD6pbYL5jjlt++O3oqOpxm"
    b"oPNehM+V5zlCgdgz/UVWlsSELixrhifnBFX1lPnHfVT8FHZH5yELety7Z2CSx+gKEg8G4GpBRwFvzsEvCOYLUa7nIOEb3uA102+W"
    b"8A0BHqaS2KjnP9fm5d/hkOgzL16qBJm0pxq9qHV9qgPxqpxw8mqCllGzCyTCnLIuhVd7DNrrE/9i+qVk5uqYGnqHe7xmRtgI3iFE"
    b"y9mzIg4ob5IZt3w0BKfGYO+KJzyByQuZvzins7aiWzBBB5CnXpDZKzyfKbsxZQ5MDu5VfSem3tCpqpWdgtbl3NER+aZmmkdh6FiU"
    b"1wB1PQimOGQq2KKG00Vjcp30nB2ozIVdzv3T2NqZFK3jsCR2z4lkUoPMcXyVYA49ZaXA5dj1uKjDLI4AJXROFX3PV27t7Fl1OQX4"
    b"oKSCidgHK66zgfdIidZy5alhkdC4gL7Fx1OQe5+IIWipwOGnLJ365jPDLhJPVG9LmQH+mLMOQr5uibbVZ3/GvFPtS9J5Ew78rr28"
    b"PTDLgY+uwZUbopp8hfrgDuQKnZAr2uacGqiBe5R71fUcckqeeI97MH+OGn1HR3Av0LMWC9wiY1xdMfc+wNs5xBezY35PQi/1OVlh"
    b"YNV3wl5srE9bT3IdG3oUFLrGmTIg2k/825HYU1Od9okkOrtFEWNkcWdDB0WGB0v2aGqOzAC+5kAML+CTJnih+/y+kGt29OyWxMkZ"
    b"XMmMVVY5ZVQD1EOJmUv/LrZUciV5ssefjc0wEE3lEdqgIKeZf3ZjThPI0LXvQHVv4SRT3kYPjL+Et5yjx6ofK8d9PIdNbsCNJ8Eb"
    b"PM/3eMKFx9pRxeYw7CF7aoCGsMZrVTCx84pJgRnd345JoH04N+Huh3auzcimeY3ouhjyZmIydhfFJsF9NaOn+RyVI0DR2sGECHu8"
    b"p3orQfsJk2RTesX3vJNb3tCOXp0EXmBFhvseXVuywltm40jFt6GKLnAChXx/j3yxgMm7JVeIg2Vjc5tFrzvHvSSfu/LP+zH6ycz/"
    b"6xVxqc91Cj47AWfF6IYywSqHnXKoSU/8NUkWEAz2gHqSgT7EYfYoEIZ34D8vU9kecdKFvI0rFMSCPsGCPHCKv3OLX/LGfF8FyLAy"
    b"JUdZywPvTFZQRR9+y0jUdDCNTUtTxbOPAl0fHQeOtXWKRhPAHYjvfQ8mqa2La2CueEFYBzrzukyhj6nkN7yZiuqwsXO2V9QhC95K"
    b"xtky3eC3ZGe5vx/4XEU17cCONW/qQP7KjV3QvZZaD3zEVeiqS9jlPabFjdCbHFMmEjiQmbHAKZH9kuk5Z7iXRHe/8u//U6aZPKIr"
    b"StDgiHijs3YSuAOH7zriM4HpUQl8RY+80+MdVnQu6VRH2UFLduiE7qFhcEOOWsLc71D2xe26oGp2sFw5T6pGm5K1KxFmzkcjY77W"
    b"rIOeuUZyYnOIF11nA/VR4ZQlrrjrHlzXObGlyy6M6JGZkU0G9pVjMEmPdaBnYTXH2rDEcVag1IS8WdkLenLUBty4saq6sokOOyLk"
    b"xq4zBkUU9J1JnpN7PaHKCOBqSridgFor5S6mVNBSj6u3TNTBNTlaehfeuA/IDr1j3VIR7YYWIe+JkBMy1Jj+lMVRN1oTyXewBTU6"
    b"V00Fqi7uBzBmDjIcwrN2cCIsQCYxNZxk7DO/iq/IExP/fj/0f6Y4UE5RDpxTtikgAyTcw5CpczNq0RPuR1awuObOLRuHvI2QHqaE"
    b"cwbP6EztsbIF39d8/wD2o8e71tnaGbF5gh4j9yYZqhPoO9pZl0YFO7LgTg+wVKGxiXv2Wg3HKG+vsF6sA/iz9ezpBL4CZ8oaTnAP"
    b"oxGbJqnqpObBHvtUZyKt0Ix3OL1P+feuKcMnOPBKYmSAdnfJ++yQqffwEH3DP128hEP4wD3zQbfguy56TQZeKpiAdsfna/xYQ95n"
    b"jn40N81UV+USXL8G17dV+YZOfcV3GbWJMo/yZEuiTc6zb7jqfpCZptQHgWTGFfRtdkPOR3u8ckN26gg19cBK3MN8qI6yQ+sKLDfd"
    b"sioVJa05hSXlo65f0Rk1m+6xhl03wt0of+uDEEriemr9KTF+qUfghxHVfmSMfwK/MeLKNWqmfNeUuw1h/RegY8ngC2Y5yPfLXovY"
    b"rw1qk2SXlEogp+JULSiibqpYJTnXOKOe7lJlPbBuK9j6hB1VwBnmdP6UrMl31WpDT01lcw8OREAHl9fFpbLEwXQDxx9SrYZkTMdT"
    b"lngzJu9NwLd73kWPJyDP7Sk7MULD3qDj6+SoPogx5eynU5jGGTxWZVz0gPxdMMV7C6MTUjl28J0J67mFqxOuVTie7/FhFLApXfbU"
    b"lik5UiGteDJLerocPzXGoym/f4Mzoo8X/RM8jF3O+Jy7MxjQKWsy4V2qOl8dEXxMXneoPivendy11ER73o4zLbtmv0d0sGg0XxHN"
    b"D/AWDfrDAHSfM6PkDbum4u100EYPVolpttCz13qwBbI+MlMnQ7iJATlU1sMZu+rEr46PwJwZ54s/uHNybI8MXjN5oVU1HGg6g53t"
    b"8bcOOT6kG3vAHpPfM8Q3s8Y5coC90ArGMX1DK4wSDe8t766AA0nt7nf8/5bcpmxDDFeuMwxkfzz31/mS53zrsfoP+BhKckuXUz2E"
    b"bwnYMRFvswC5OHpWdLco1yZc69xJv10fxVgnTQTsxog/PeOhFd3o1IbEmLs9mLRjfp8tfcA5Pzs17iIAkwWos0t+c2Vu1AWsSoHz"
    b"IGb16jl8O4tNJatCp4B0qMdjq7Ar2MkxvKTE/ynYXOc/Op5JD3ZN3VkJH+nVBzBUXZsTWVL3NCicPXjazM7h3BHnnOXlnNW4ptvq"
    b"NQjkHvatsalQO3i5B2L8a2ohqVLuWfl7cG1NVowCRQnKZXSYp7HmhBDxdKpy2zMMGaOgDYgSXZxMQ3gCdU6v4ItjlKQZszO0J6+2"
    b"uFeDyRMiZMRvduYSCJgSOwR9S5QbkB3bnVNTh21AekOQb0bG2IN8D6DrubEEIcqOqPq3IGKZF/ANFa3inB4nT99QBezpvpB1rm6v"
    b"kMouYxckvD25/timS7Z9TkN4AsGGIVxrgTfmnDwn1cAV+3JqtYFUeDswmuCcAo9edlQFA3r5VzDZW5hgRzUdUlcXoI21zUqs8ZOo"
    b"KzPnzlUFd+jap3if1EEvLOMcvTwjdkhddYa3NiUeyns+oMMkxOypxaEuLJSe0l1al0Js3Updm8ciHNGtk9gUo5QJaxaD3TOUMseq"
    b"WxNBVYspwVkF91M6nVl8oBqvqd+ERxkQt9d43pb+uT2YT72Lmyy3+rF2LQ7Xs73GrLMCXWnLd52D+cf0FuVWs3XxLQ6oUwaGWRIy"
    b"Q5d84GDQulb17Zk+vwZRSQ5bmZtni+awZO0MwYcxCGPOR+q7WpnjP+BKXoGzD3z/CJ9CSFVVmgYcW+VZgc1OqdplHc+Yr6D8Sc2z"
    b"HIHiHJG0gW/S3LUDZcUw9qppKAIb8Z5PeFKqLKbwDXvq7IJJjJfEqQmIXXFyTX0cETlr/tQw/Q5UERP9HDNEVkfmeQlOKcnXERm+"
    b"iw+ooM9vxVrsWHfOwWkkyHHOyV568PXBa3rSVu5jqvoG/iBHX+pb10/KzhqZPpGyQitWriCUa9aFeLBfMGdUTwYcsio3oKIFvHCH"
    b"6qWE/bizcyYFXQ6IAFLjyAlWF3AcMU6TDVxODCvasJOEPVyDehIYsxMcmw1d4A5UPrEo0eG5Z9aHpkg9ZB3GKFMdImZMBanzPNQH"
    b"0ObDhijvzMnQAW2GXNEKVL6GW+zgsBHkfjDGrQP62rBedbpWikNyDlfWmPa3hS1StrjDXizhviI4pC2fa5iVlXGu4Su4FlkpLzwS"
    b"fEONUoJer5h/cWBfHtAxz2x2Y4D+NIB57PLfzPpYMuvc6OB076GMTKiNIjBazuTgIKgNr4bUCXfUT4IoX/ln/ob73eL+O/fRXuK7"
    b"RK3nfm2/IGJsmR43tOn4FfHWsaobvndoeXqNI1CxwglVTosa+iijyrUd4PETap4zUP8BFnONTpAymaLHubrqg5Pa+ATOrXXrheCq"
    b"iKq/oKLewNQXzNHoojv02UUdfrdg/i7Kh2O6YUMVUZnvfYrTu+1XUn60BzfYJVd10OUrGLEpyPOEHooD3I3O1EhZlw18ekQ8THn+"
    b"B/aXukfHVCHKkxW2DpX1aPudHXt+SQ5YwSn08SBnFhECVsfGqsoxNc6BfK6el4SvcU4xWYCrJud5ONfGy8beWwh67BA7K37GOwxR"
    b"8eQ0NkZk7ITqJSNXdMx3rU60xni6MzxfNfnjcJxmFtsTKom5HaqFNu4eqNwOtn+UTVxzNTrzu6Dr3cHUJYH6UbdE0dxmAqj/qjQE"
    b"6VzLlkvckKxxz7qb44Y85S4nzJwq2R8xuCvCnxbSOa9RPYC1mtORI/2L4rd6gK1siMYB0bwAb3TgLxx+uT012QpEuwTvVvxdV6bD"
    b"axGyP7SHe0tOXsM7DeCczlCpOqjSEShJcG9bWe+oyK7gaIc2xemMzJwE2tEyYb0pwmgMLbYdiQ9EYLn7a/BNYs9+xS7rWkYqQEUx"
    b"rOOeu1W0qLOmlfuYgxsd0S2z+9nj0Wrr1B2/e0PEkBW/hJWQj9a8H/eeK0Y7qfrWfbFgRZcgyoSfO+ajjC5+wQ8Ska/I48rZqbJW"
    b"m19zCKcgdXhMpHRoJMrexmQNZ3PRdFpzF0+EsOBTVlgX9LHnHTpjQTsWd25xkBVMJKmo5h6otx2zVUZ2B0si1gp1TTDtHdixQfc9"
    b"Qec4A+kF8FLaJ1pTQ+reUiTWAzNP2bMp1XdtZ3mFvN8AhBXj84l5QiV1v56Ap10XBXsjP56HpnOVUnOlaT3grILrsNMbVkXIFfVt"
    b"z0Z2umEA7umjcdZEvoK8PgODdKi7dtbRkqPZr0ybDaxq7sNrhDAIgXHJQdBWMRUro2tVYG64robLGOJX6np0McN1Gtg5l3ui1pZI"
    b"OUZzSulOvzcsHwU7U2pzwwIdUJPWrY43W/G+u/gBeqywLfe8gUMSPisn0k6YCJOa41r76hTlN9Y5pfMIdHqD9qWoGlfBMcdMG5lR"
    b"u42OPsMePKDOUpC3NbTKoEdEL7gjQbE3dFE6Yo4yAAsmLPVAWynTvB7IEbUx46r2jvnOFWv0Ae42oyZsJ2Wr9przXGc8g0f0yMlP"
    b"eWoo8kCX0AX46tQ0Q/Wv1YYwUqrVOWv1GtZCGIRrjx++o0JaUCvLul2zEleoFD0iZkZkUnSboHHorOotP+3AT6rRNoZolef+X6+o"
    b"bzPOVlmZGy4lT+l8qx6dk7eoggeLrx1WdtdYxIaINiOXxsbLKsur9VR7Bs+WNRHZCYN3OPhzmxa5Jo837DJnMS0xh1UfR7BUMGd0"
    b"nQWoSQv6JwL4sT4RNyX+7k3/CPmzJ/p12QOKQdfExxTU0AFtbJmGNQF3DdlpW9idGmyVGVfc+gpjXJsV7rKE6e1DIqG6B4fmslZE"
    b"NmQ/6mztDmhPkYfyNKrPrGGc9uS4ttd4f1yHulcly1yjVW15VmGgfFUEclnA7R5QP2dHnbCHrueIdBF6WMF0vpr6TP1GfSJ3xXlB"
    b"G55AB1agTzRrz8lYszulzr3m59dM1mgn3u25/so4xRw0pFEi4Pm6YzdWTew5IR9mZKOCvNSxXBKBDAd2nq469ip+4xQ8lcJFlmDD"
    b"rjktImJgl3/Zgf9bdvvg9HzxIFCvcsNu2DD5pTk69Cp2kvY5N+COkLwibyOxiS1r+PwUhNygY6/JXnqWyoF11E750yhb8pUd0MWO"
    b"HKmYuWeO6RJ2swNiTmD8dOZCl8pZ+05W7LWReR8O9PZN0flSeNSArr0M7beCow3hG7vEzYr9qGzjCI1mA3KMWQvKKxTg3JQ3FfO7"
    b"lmSTNSxXh56ZxKoBxwkq7bOQ66xhXEVjymxWgcNPLfl/SIf6FPeWuOhHfF9oXRexsZDylEZ8VDutDxLuoaB2mbH6lC9SHqDDm66I"
    b"N9c+jr5kz82psM9gqEJqxNZpv4Mb0tXZwFM1xm8U5K3I3oP65KZMelAFsKITMwb3NKzTAfHyzKbzlNRZXToth3QLnfKetYd4SybL"
    b"yT9jOpUES8/oIhI+V92UJaznGhyv5/Q1RLwIvSul+33Ajluw0xdE2QxNcwvzKutbOg2/cY9hewaoDVrHxNxXYX5u9Y0t8YooqlcP"
    b"/5odKU99Dit+Dm6TswkvyYchbNyGfaVT2mLDVKfMOemjzW9RqUvz2PV5ThIjMtiGBHY2gx1xYMSYd9mlfp2zeg+gAj0pVtb7knuV"
    b"2Cua7Ut27wNoOQxUBw7Na7dgBxZEn8rpCSc1J3/viZwbosTelLyGWly9MI4+fo0fGoUSq9K61KuRIbUoaDFcQXZeswqkxp6zJxtD"
    b"RdrZ0TF9v7ITw7WrS/vhcuZErNHVHShTJy4F5mmtWXs6P8bB8cZgpCFYLzXHaUjtuGPFSf65dR+QKbqm3fbfqzaDILbp8RWrpSQO"
    b"az2qbI+y3/rfnN1V0LM5wjOQ0Y+2t7xcGQaO2fPaB7o0jbbkHbR6e25ccJvt1G/VAZl2Wb3ye4Y2O18q+iX7rxtonV05da7ujMGY"
    b"8tQC4lwBkk4CPUksxstzQXTLmC+xRRfoUL2MTInqmL9f7lqqt0vw55l/bo95Sz1Yi4rdEvEbCmNFtXc5J3srnoiCdm7PzjJ3Dy1T"
    b"Vc07UGSJJpPb1DNZuxOYfal91LPqcOsqGtqTkwJWmZ432qV/eoR7y6HHVbbrtlQ7BZ3nH9FDKvH4MdhozypUNXyI8+iBVaQnTw3N"
    b"JdaHlTznPNXlETVtWJlD3rVMpHpM7X3mY/kF7/YMhjnGFdFQizn4iJrqPwiUq0nZPRHOuAJtW+cq6HeHdP3Nj+h/Rz7s8M5VadNc"
    b"nJBvAv6trbwKnmgQqFelPVujMl4jBmd2jIdMqDNSOw83Mtx1OJ4lEVuPyxwnhqOSG/JTAhiAAzFYWZyYP9qnuaErKGNS2SlKQG47"
    b"VKfY5TglauYF9dFgAiZE6TTkqX0U0v+TM7lMevfEQSZvoE9n7ILv1h0bB1q7p7yBzHLDis/luCW0a0m753Kn2HHF/tvZ2duLIyMu"
    b"uP0B7NvgrZiAad7FxorMtKRaiDjj5hFuS0EAF/SN6aQ6yaNT0EKIuvQAb1UTVydg/NrQztCmlCjObjNSQubMLSpmsMBLuL4N835m"
    b"RI8ByFbVQMFF2i86I56eoipJNBrxRiPmEuSGK05ZBbG9lRZjNty5xpEOEeMtylPBzI8ZtceAHaQRqOGqGzsVp2FlOvqASnDtzub9"
    b"BmT7PfNp1ny1OuBD1uiWNSSez+/cIxztcurbBZ3h6ibQWakyubpLXXQGSlhbph7DeDywmjZUhQNqmz6xKjGuVFmFxDJYn92v57ZU"
    b"xhA7q+kSWLoGLmTMbj4ju6uSvbfpEKoo6k9LbcaxcA0F1diUGNGHxVNeQCuAln3VM+MT2JPC2J0OXMkDe0g74VMy98YQm3qUlBXX"
    b"Hps+399yYV0iY0i02bHKtK98yN0VMDopXvY+T8fBG3WpZWOws3In4mt/A8qp4aBO2AOq/Ne8swQ8Xztdm1pjljgJLuzc3JyOgw5R"
    b"ztn17GAgChibKbFjak+zwr3iWJ8pPM4lMaRnXOWYqOFQL/fm397zGxzYe8Ra6PB59XDtqP+1BymAGxMf8D2oI4ezn6Ak74gZS6en"
    b"dGdMOe2Zk6c0Z3hNJtMqXbmRBbvtAf/s0KqZwmnFItzeW9bOwX7rjlgie6cHZhOmY8oVlDBfoWUGyb97VKksUH20Nl9IN1AG5wKk"
    b"KVf5zK+DZzxRURefoBDL8x4a/x+xDtpqStb9Ah52hitaPMNP/W6b4HyRTDZC802Y8rkgS0iHyRuYgg2VxNAmTa1gWhdwPKqwjohM"
    b"mkEP/OaciKZvq3VUac2wh3WqiUm6OlP26pTZVw3TA17DtnaI9QObZyXoqE8GKkCsOSu9AlfO8QA5dtsM/SYmCy2pHxwod0C9vmfd"
    b"qEPlxN/TR8ErpiFJv8APnC+XgjJ7xLeMNTogvnZQFrTDo8IDuAV1KP7owp0O0VkC3mRANI3NM5EdNaGM+1wQQQ+sito4VIce1jJu"
    b"DtQ+wEeQsp7uibcb8po71uA1GD+zWBCY9q3qhrN4rJ0p2uMRU6PUuA621J0dtL/M8FDFqQero1O//md+g4zoGKHGVOzMczL/APwd"
    b"wKF0wWQl7MWONe7MrSZv94yqLoLh2DCZ64aPlC0ZU2fl1J8NXRWpzcuqbdaUwzG4s+lnI2qd2rqKQhBTCQ6vnDILCTk0IAfkrMLI"
    b"uJTINIuEWn9EXFEvV0ldG5IvlLl3XKnU2Eur98bspzlaQas8LInC4bEzrWOd4zlZUrHUkLzdYxWs7YRxnVbXsCs2ME2aqyIwecR+"
    b"V5Zb9tSUKSEr9pFO6h2QA/V0+T3vS7udekTXnTlxJF6JunqF+0Hcbo/8uhpZdlrTp/auF6lHRE/JpVu+YsPuVm2mRx3ZA9UsUbS1"
    b"lu5YBBziqa0Njw3ARTtT/TqB9l30TENozEum09e77Dad7vkAWo84WeUC/SWg/1NdcTN6tdZU1RWs7BVOxob5iAd8EWPe8thm/EhE"
    b"EeSzIgYXZIAz2AKdnLchE2QwWB2egfpEbqlBCvZhz2bW76yuS8CNCfXPnvsPAlX8W5/mPVFWIpxWHxUs/5R8OqDPNrc1+A6lRORE"
    b"rXIdUUNZ0og+iwys3iPWxuQAQQ8DNLWQdfJAxNrh5gwC9W4k4KY7cM6e/KMawNZYwJSzUl4xLUgnvJ77Oz9nlSbHddWx6QkVeLGm"
    b"BtQq2lGlVWSDCZhmenQID6hYxNMlKtmd+4QJV1IVnqOw7JzOYygtw56xMnNcHW/917wmrstKFz/YD+zWAh6oS0fjhv92yO1d3uGO"
    b"578zlaoLmsitVh/Z5Ked8a0ZiCa0Wrpn/YKF65vTqIAtKM3Zn+BVWhge1OkHY7DfiClNB3BLbpiytrNeUnw9eyKjer7VPbrlvSrP"
    b"04cRV56hEzS2V7o2v6wCMXfNZ72jVnN2Xnhu+eBgUbODwyMIVP9d2ZoODI9n7CqdU1HCmimnMqey6nHu9FNWa+U61ndbcp0DMIVW"
    b"spVTFFnaPCBlKzewelvu1VleqmwKuk5HzcDEbU3fNSSpkworY6P6xP+MqKq4NmANqgJxQMU+sL5UaQmJkAt0dj3vKiR6as/aiHsd"
    b"U0WoB7mwqWu1/Rb9fV0YqsYp4xuZe36LSlmbo2VHB+4UR+3MR9MP6EdLYHQVRdamyfbAFWNyt85WKkD2A96ixsatzfdUHK+5e8VK"
    b"dfa77rmDCB/1zCrACiYkNk6uQ5ZyqIGOnaa90jPwx4ypS/Kbxzyjiu6sAJUmhklW9rYL29Wznv/cvNSqDB0sk1XHyQ4rY7KDYG1n"
    b"nVV0V5SmAR9ceyrImgpWEPwtdciB56erQx1y6hXpg6bn1Klb22lavdVEOc11pXuHbxNjvFTFHPMWHdX5mogmWWKJI2NoVfMcXJdb"
    b"pTCmxp/S9zaHY78DqysyqE2P6FN9qH99Zx31IbFK/6g2Hpn7rv2bzpTRWPkOCcZUMAm6tHZXxTYFc8OKGrDn+8agjFjnHe55xf2l"
    b"1rN6MF2k4SmrOqOziUr+9s7XoxNEcusZ0Z467XZSzndnNWljMXKAAqE5OUfT0l6UhCe5gMu/h8t2sBDnVLInXHtsE3YC+iTTQGtL"
    b"PU9saP2iFThG48oEHTV3XdOzCji32FS43OrpdvZ/n1Wo/JQiutI8uK2L+2A8Q5/aQafHPfDM19bntOU5FTbFfs0T3PGEalMb1QWg"
    b"7oaANbLBZbYw1S+zE9IK3AhrOqWm1DuP6M3a4uWqiVoT8EeBztiwKqewIBF5JqfyU3VLa7SaSmaEZtSj+loRndR9qifDdFgBOpeo"
    b"a3p9CNM2pfYRtm8Mp6nqSmWOAXWKp7yBIb+vgxNA91Zje6vP7o/NAdO3+l070EYg+AMMlrpdM1gm9ZWV9LwMcAjsiaQPsKKqg0q3"
    b"/gnu7o55d3Y83zVe2S6u2TE+1AFcrFQ5Y+v5UjasE2iflqAWQYC3TL7voyhOzTndGN5V79seBtaBgNTfPmZ1DckbjdPZxSPr7M3s"
    b"dIeQiUszOytNnap9e4rJcQZKH26+xLfW9uk3+LMi6w9cgfAlhj+YXyKBydETQCq3Nz/hmGckPZSPgm98zr3D43yLj3Vo/s8Dv7kx"
    b"D1ufmmvOnDOZ0PzcfYrndcxU1RvrK1YHneONXIH5IiLgggyuJwqV1KA5DOcAZXwIllIctLc6vk9cPZhm02ddtOtOM9EGxDfgzXZh"
    b"NxdEaWXYE6vBdH5fbd32WpGExPKc97WCCxImWOLLHFZog1dzyN2rl79riOxg0VFr64anU/H79WcnuAx7VBnqW26cRv4tqznAg9un"
    b"szOlIt3jU3tlc4LHcEOqlZWs8i1eshU1w8TYhjveU49nOyGD98lHNXzpW9x8Pd7np8FLn2UEY8yIf1t6t/owBe8mhqiGncOL1OaK"
    b"yPjXPVEyJ/9EgWaZjNVes2uW7Fj1IydUgrkxyOq5KqiuZ7hwZV7LFES9tJ06tFx+OKrCep5nYf4t7Usf4ipx9OatiNM7dqhqdLFl"
    b"ug7Zs/Upac9tah0YqnpoVuhY14rOY8hBdHvjIzLDZorMY5iS1HgfnZfRmBNQdYuSbBWjpJXw0JU9AWXVa7JxQ17WPD5ijai2uoL1"
    b"6ATqjthzxargdnk/WnO1foM5lWiIonhBlTHmyR5Yo6paBkFks7e0NyY0Ll/XYWMe3Jg91FgGc+YaD8wD05hzvL0f7XOvrFrWzwVB"
    b"cGQ4FF0ezI2iiDWx7FAc/a81nJw6QDqmOW3IzCWx+sT6QQ8WLVPjxCsqmZh6VblwnTh3AJFPUSA7QX10S/ThCPYwA1ui+oC8Fpvv"
    b"s0GVUrSSWx134D1urHMyt7zeee/Nqncu5bfV+FTWxvC13hWdGZWTO/sgyUeo/bnlhIydE1se3BENQ+t9L47Vn+6tgc1O03PpUioH"
    b"9e91bP5pfsyKAd2LQ+46t3UWWjdG63PuwIbdsZIa9OCRzU0LzWWhP3NgnYwJu3mAW31JL8wKtkLnzUQ2kytj0vwtnV87qqG+6dUp"
    b"9djO4uXA4m/XYm5I/du3d6T9TO3smdxO9U4sAizhzg7U4jPr0lrASCrz0LUzPCvTgBpWq7IUQyJiQZ3zLlqPWGs7Q3x63lxtTk+d"
    b"2BNTMQ9N11LXkzoAW6dWZvefW99UjxhaUMkucbz2yW99eyMJk/5foWcJcvsOjaG2GSAR7E/OnB3lvIJAsbR2V3TsydROezZK64YM"
    b"+ekHczM5MOSOzNOq47VTDSQ0rL+32SeVIcOxORJGptXkhs4G7NsUTuEBRbFkhse5YdKleQnVn7IDq+W240YoNh1Q+w9oan3yWAaH"
    b"+b1HGtfkmzVdDjM4gYrvrZ3y36VxIG2VUlEPdWE7usZhHEB1U/aprIYL071SnlyfyKBn3A/ssweb/vGAKv5ANRAGyhjqlCTF33tW"
    b"RavraMyMTceYw2JlZPCRdbQtbe6aeiX0PEmNjqq47LmbnHdwOPoICvO2NMc/ifnmHLhBV6dOOuyZw+Dd3IwQtVpPINKaJ4T36cHJ"
    b"XVBNquZz4NmpTr1nlalrvWd9A8pIleyvqeVi9apXnFv9FrSzBRMntvf0xKmNTevQWc7aj+Fw7+gTVZ9EaF46fcNanyqa2NsqU41O"
    b"J4KPzCeuvMrOUGPHPE59MlcDf9S6MN75xKNAf7fW3wmZRvFjavP9anCJqoka95ydgaAIMibqKu7qcTXqfFmAuiJTFrXHyLEmWg08"
    b"MtfRwtRfnfk3IUIH9HCKS2NvU7Ni4zATaidlgNondCBOn9IBk9pUItEx1uydczQHjRdbm+e2tqk0Wktrf8Gp33mXzBuSCTAy22OM"
    b"8pfxVYnxEKWtDdWMIvM5FaZAjZnqq8x+wToemc6ktVsCq7gmL8yIRD388a13q2t6hzoCU/M3aabL7MnnR8Vuz35wThHDwaaH6qyy"
    b"DrE0g8k/WAVac59DNNSJR7hXwVue2L3Vrl3q7Bz0ueB3Kg5z5nYesDfVUbFAY2qz1tq8dB26riWL33C+Z59K4YoouLUegMROSO0c"
    b"deat9UV30G4WMD8ZjMAZ/dM6iWxJ7btiRe/QRkXhuvdV1G98XSWnEJ/j9duZ71RRRmx4KqJKFhZLfIBPqPNSqtGddQtqnEytB7ni"
    b"Z6TmpWvAcl37t4MhB0W8W3N0KTOrmbPkzSga0HkzmWUtZSy14zplfaWW0w/mLtbur5zc7KxzS9WYEAbmGmYnwSU9Zd0vbArWwCa2"
    b"9YgIEyLCu1UVHJmaHn9v1TLtu3DGlnTJgH07QXln+UEnbeg7CuxpqXNVa2rtFUjgveZk8Bpc2LXc27FpzLWpNgfrvNCZUQE4V9U/"
    b"raEXZKoUD6kqkA06f05srCyaKVPXIX7PQFrqSF3A2odBYPHO2byfE6qREBVgSewc8nOF+XiMOj6hStgYO94zLUTn+LWRckek3BCp"
    b"9PxzdRqVrjKd7MC707Ob9ZRirRHe9fVF1k/Qs9mw2ik1Yyce6DVeEM9aXVvZteToDo+ODJEzz0Z4jEg6JS8G32lE0E7mvU1B0chX"
    b"W76qjycNrFmze1aqM2QvEzhOOSdNZjCLZ/UUnXHAk1Tf/4jcpR0iCxg0ZfMr1lmDu+IJGK2LF+zeOqBj0OPWWNTMJvVs4HgK9vvI"
    b"nPqFqfSRvXH1mvd5LyExdnfc5425DdoZQMp/JLy/AUrXimeovRajY79lZH7ODqh0xXcoNxLzuZ6t2fYr2/qmPPaN5+Ty1gMf25xG"
    b"rVlqVtyU9ZsZ1ziwacAFrOXYnF9rVkBIrTdjflnGHljhA7tH0daesTMiYpdMMrc5Dpkpc/WxL2TLatG3eELNJp7Nc/venZ0aMIRn"
    b"lfh5hZfpzH/1I9joyFaYKoULKucgUM2wNh4/Re14BMfYpeK+fw/LKycZEDczq3h1PlsGT1Ieq2jlBRLrsdBp7IFp9Vu4wbdgY9Fv"
    b"HvC6jcGfimUqPJ8z68g6wJ7MbLZEYXm0ZdAeOAdIK4/TI6OQkLO38BvqRh6b32LP/ZTGs3bwjClz1Jhir5V75fS9a49IYjlhZ3MO"
    b"QnNrRjaRpdUEAutBV2ZBz6oN7SSwwKZa7ViHW9ZR1zLBnMi8Nqehduzqk+jZPN+Yc581QwQw9oVltwjsN4GJKo2FPmf/VhZ/HsEC"
    b"xOboigP1NGr239iEyczWek400Hesrtu23u9TeXWtFthYbsj4vWvrWklY/5opa+veqMAcbTWvTIgi8twyUddmvkSBVi4lHRQ64T1A"
    b"KXPmDh+AYDuBoqfUEHZlk3X1STcWI7WzoGc+vR1rNAhC440r6/pq+2K7KBJDnm9u8SEzt1vM/bYK685cnS2ik4mVT/AOToPn7mfB"
    b"N0wNvYF5PCObj03lbnhjhTn1I7ie1pV2AltysPc3NZRQkx81VqpKqt9RGo8xo+raHqPi2uq93J59gQbwgKvwBNWtj176YLqrZvTA"
    b"uksrqtSZubIVO47BmRvDOhM8iWurMDJj+TSiq9Ouz25PmJ3yho6LmlPgPoX3DKjPbvzzurf+Gu1I0ZPBEut321sHXOW0f7MxHkqn"
    b"hWqN2XJ3yugl/0VHl/bbq5/hAQb3/r1Y1iM2KZdTGb+U2CnXPXsve5hIjesHm3nQBTnsuccEv+nAMGfJeoyt7l1Td8nKbSeQFHYS"
    b"kHpm37KPNeKfcFWqOud2uoWemNYY26X9BlrBxUfE1Lh27x9Mqe/Y3OvaXKAz3qWqsWsq9wvQjTzFU/62BpWo0tE3/bmw/sUTuNUS"
    b"74g4Uxawk3PjW1WbT9Ga9CzUxXHiQW3z3ofw3dL7dMk8EZ0zenClocaEZ5QRwSVTzajaNobipItgwZotmaMh3JGcpfUc1+CG95ra"
    b"7LGart2VdaiENglhcJxQluFimsO7FMbHKfqIrO9Z670BVcmlX+NjMu05cVNrpnf4dGQ9O9qX3Vg0HPOea3MwdO2Nh8Ql5xrrvA6s"
    b"/zo3haTlRUamI6Q253Fn3kZVs2P+2/aAtSirMG2sdQJFVApL+OIaXDe0qQttNmmVy53NbY257rfEg4hu3sf0rJXGeGQ8WUX+4XFX"
    b"trhMr6riTpR16MGTLsxXpd1wLULfsPcq+D31R5egKvVUOZtDEfL30jJbxziHEi5nBQuSWBbOba2pMt0iw4OdSFIaQ9EygcWRBVGE"
    b"0n3vbtS/NXxvCszePmr7pHbmIUnem61RGMvVJQ5qR4b6SlJTHtpO++C9fs+Edak1pTpya3oI5WS+O5s/cc6uUu+DTm9X/+MDVVHB"
    b"E8ysYtUYXNF5NkXz0hy9tky2sZWomsSG3DIGiyoCmXM1OiEhOjJ0jvvrGs+jTovAOrsqN7CpkI7rukA5ry0mqKsqt+9VXWlnq7pr"
    b"uLqxnpXyeF1bu1KN9Kp3TfApJTbBPzOcpf1ZB8sFI2MfVflyvKUKBfES10GKI1wxTGxqfHh8B6FNEoqO+ntgrpHIapKeuZ80UqgH"
    b"fk3/Schk5XOqi4wss4A73lH5zWDO+tSYubEXUaDOgdy6Oxvi4IpokhjDszVOSP1ONfhRZxiUx4yg/6JPT1VcnZ2xpeLQ89xVOd5y"
    b"v5r/z/DiaJyc28lm6vjbESW61o0XmsewNPa5RSuJcVftisxAWhEZR9+t8neN7TbVm2Or3WubtzQgMxbu3Sk7quAt7dTvM85O2Bsb"
    b"7iyCOkNjfWKfPsna1LWUlTfAP3dLh1OL9rfmV1KWLzEkWZpWFZsT/g5UoJzECFb81jirGi6xtAk7B7jgM9j8wmYw6mSOHT6mD3zu"
    b"mqHVSu46M59ZTIw+GMqNYAxXxvQW5oB2cKybI4fhrJNFK+G+7bCeRcbGskNqeDC3nbrjSSoyE8/HM7rnttzjwvpKe4YG16ZxlWTg"
    b"xOapLq1WcjZJqO2Rah0IjWW7dh1qx1QFhjqY/tnyI84mcoU25zki/i2IDA2x6hRPYmXnkodWUTqw8txOiU25whj+XM/jW+FfP1jU"
    b"HBHpQ7xoS2pwZ/qf8txtXJyhyLRK9juvoc6Xm5rzJ+G3963DSTWs0vjxqblktLNDXb0Zv6/VJ3twPg9WpQ6pCG7AT42xTrHV5vpG"
    b"9N571iu+sIjRo8K7QwHQU756fK9260fs1SW5r7G8kzvdgzuL7AUT9G/wOeg+1jpB/6VVgHpWLag/XVW6LjzYnkkLc7zH2kF8ejw3"
    b"IjXknNo8gIP5kDTjOsNgmU2/2JrDvm/KSG0z7A6oUwNYijFeq+3x/IvQ1KENdb36+2N2zA2+qsZ8/LXTq49tV+isAJ0LUZgqNbP1"
    b"pnFbc/7WNAn1y2y5ysym0extktzAVFOdytAzLFKaJjwmL6uCv2K/9e1MDVWu1P+/A6mkNnUmNp92adpkae9szxqqrMrakL3a85ga"
    b"XCOnzMSdgn7lFJrHdOltwdLSPbMwd6pyX7H1HLyLvXoiygqE3PDbx4bVtD+vazWPeqy1uzDmcyvrItV+UuXC1CGs6viBOKLcvLK9"
    b"egZVD4Zc5r084uRZcaKOjJ3THmZlYHfH3ZK+52B3rj35MbFqUicUqGNkQ9Q4s/6Nge0lnaQ3sycbGzeiapmiF/0qRfUlPJd0VT/3"
    b"MfsVCuqe9XUG86InGwysmnF0sp3TmVWA4LWrq3ovjqa2K4f21tamKOyOX6GTmE9srbdOoYN5K9s6N7MaYkAVm5IN749XrKheGf5O"
    b"oJX/HsS94yk7WJECpuyMK59Q8a5gydvV2zf/Rm0ZQ7voJsxYm+D2v7MTQd6xWrXTXawnfivS0C6nFpG1vW57W3mKuu7tvMWUr98b"
    b"x9w6c53ln4CcuDD2Jwly44grc0scWNc76pq+ncWzNad43+a+5G5gzOmAyNjj/X5Pp06N3+qKWrFjqkdpWCw7+kq0lo6NVyqsu139"
    b"JFo73jNFY4338YxsoTrKnnXSt4qsdJF1eTmn+L5nFYo75qb2eYR0M4xYEXriQ4v8omMeVfRTH6fnlUdVZWvZvGd1oz7J1CJAanE0"
    b"p5bJzJtQGl6o7MyL8L3PuGPnQ2y1qVZGI1N/W2bmYDPhde7BBm1nZFlAPdONqWytf7j1MLTKR2RnF695n7VxVrqjtpb1+vaO303v"
    b"0gpOY1u7BlT16JqjdUvOGLBGUvMp1zCSB8PBiXl+FalW9iTUV/TOPa59g4pjA1NhQvPl70zbSI6nEygiT1hJ2me2NISY2hSJyvQa"
    b"ZSUPx7nMiT0vWVMyG1RO7/gw+NJ95u9Ceqpe0jugvRWpVTJ76o41OzYI1K1+sJMLZmAgfWftybyR5T1dl/+8FmvPVkiOfI167ft2"
    b"enXKessMZQSBdooE5uYrjnekays/Vm+F1cqZ9aMezHURmnuhsu+JyUbaO7wHQ2TmK+8cPSxjO3tjY5k8NBzSzticGLu1O86ximBL"
    b"IrpPFrhAavzZp1xN1ziTyCbJdkxr6xy56cbmkLZnCd6T7YV3uSHHVHiwp3bCQ2HcjnICLe8T2bPfE6F69oSqI3en0+z31AI9nEDn"
    b"zG1zbmsdJ6n12oiOuyWqJcYEKT7XntJ2QlKLLgbHd6j7V7tY9rzTOVm04RrbDFSZyt2zHZ2g+p6hutSuNP9uZAz92rSH0BTaCW+k"
    b"jeKBcQOZ5Ud1nKXG6bhj5FcXXO/I1rTzA4bGLj+Y+6X1cNbWsXliPUzK86vHRLLXNUx5be6I3HCyurAyul6HxstVNj86Mdyn87ZS"
    b"6wTu2vsY2HlGO3MhLXk3p3RyXPh9+hHuLcVyuZ0CqhEkgX1bmAajuGVjdWj+3h4dE5tT8/u351xnxiuODINJHXmLyqfV4cAygE7j"
    b"qa0yDkwXzWx+XRsjS+PBw2OnWcf2aGF6SWh6+IanlNva2TjtrdZd84YOqykKyYQn1mH/96mI2hyovorazso5GAOtETM1XfGtz8A3"
    b"6FE51c7Y5iwrMtyzYrUmnJpnLGQtzgwzRTbjfmcsp+rU5RHZ3bF7cjvVTZ+kulsm5hB2xzVX2iQkRcqBZfHM2D6dtTLD+aDPZW2Z"
    b"KDjGMu2HS63LW3N3QSZ7QPEtra7ZGb/SM+0pNX9ycVxx+tR31LpL2IWpObF08lLFDmhAX+fwtHuU9Xs8bmNbEx1z1rZdxwer0tRx"
    b"vDXvmPYxaD3ibLaldri2fjvneqZUZ+zyqdVK7Ty4wrjAyiJcYjFZn7doq3fw9RUdhwO6fyZ05oUwfFvrjG/nODnLI62uoffRulDy"
    b"I/LTePDOrxIGyhKcWZWypdbTaQVdQ3fKNvasxtJ3c45Xd0vdszaebsW/N+bj066uyPKRsiQN8WBjHMDeuArd/fV73WehKUmtrqT1"
    b"8sBmZS+svohROrem1uhs6jaap8dZgANjuLWXQrmZ0mrTzJhPPXllZx3UKZEitkmTHXPB6wTJ0tzviXU7psaJ7+E/Tumq2NkeVO5j"
    b"fpzKtLdTh3PrwdvbuorNg6FsRc5Mh7fMlaxNLYypMHZ26lfX+j7VMz5AF2snkY7MnfoArmnPhw/MaZwb5oqOU28C8/S+Q8e5Mait"
    b"Xl0f911q2sWOmkWxRo8qIX1PYVSusWb9rI1HVRZjdZyCodixcO15nYoZlalbUKmLq2OO1j6061ItR73viiYu6Ek/mHv8HCVQp5Ie"
    b"jmpqY3ukZ+qzRr+2AqqtL0n9i4Xh6Xe1jPL0pb2vGse3Xl/C+jhjuuuCtbjmCs75ydqPuzbnz8Gcq6k5uZKjo76dMR4dO6VbB1Xv"
    b"WO0PzZWtGFcz+1tjWrVeW/wXZ8q4YwUS2P5pz1nam/dmaI7btmLWNzgyH1CbDZQfSFndA5t619i6UYyfWIetxrgLmyQmU9dee/x9"
    b"C8O4hyPp2hTZEG5kZ0zR0JSZ2HSnrU0zbJXfEZhPUcTSvBB7m0IxoJrSDh7NMhlrX3dlbnWEYrk5jLByokPTCQbH8w4UpSvzX9mp"
    b"FvGxXomCwM6yLwxVJ9ZVEVpuecfRd22Sam5ZSHupU9M0uqa2vYs+oen1fZvMtbGzC9Ur2T0yTX3jAg7GyzTmyFcM3p7t2Fb5XXOM"
    b"7o+1885mxWgXg8ZwxWc6z1ARUcd0XmVnu7jq5zbPcgSnph1AjZ0QHwSJYb/cfJuN25kOplXbmqfceg22x/pEXTuluaYT67B4OHLu"
    b"d3ADU+tI2eDnPANHhLbrTmwt54aLG3sW7XzPsaEWZ5pBwRsNTZFq7Cz4yCYx6wnfFSzOGdEnAyXMTeFXN1fbe6Xe8+J4ssXauhL6"
    b"700JmPPOdnZGqU6Pv+dzqty0/TXNP1NjtIeg7Y8vzU2hp9NE5lZv/T7V0RWvunt75k6rje6NRWi1htDOfGszpM6/G/4znJ6a47R1"
    b"aWlXb8szFoYkEpv00T6XCOfeAsZbK8wT85o6O6dPGZbOsYMnsRpO3QDtqYQJLIgqDNGx90W1haU9nxYxtbOcB9axNrdqL7KJnC3P"
    b"0T2yPQPr4dCKcIpLqfXqhEfewVkdrohR+YXQnprG08gqT2cfqcpU2HSH1HiqhtXRdjfF780Z0R49ne+g8246gWazLWrHinWvXSql"
    b"nQinyODg3LGPqs+e6dqkDY34bc9kfXQjPKBDFbDeTzjdtIdf6IbujjX/WhNhuob95uyalkfcmjOnxX6RocbaokbutIKZ2FmrJXcd"
    b"H/dIZR22LfbsmzaouSjAaT4yR0A7a0AZkey9DpODIcjdcaJy2ye+OfboqN45425PYSkX7OKVXZv+5MRiRAMXfUXFK13al7j+l9Z7"
    b"MbYpzrFV3AfTxhvmks/RGxurFdVdGNjs58QYt7UpyZqfH1h3nSC1/Joac7M5KgwtbgrMdaoIXD3EfVNz9B2Hxuc3hhtiqxQj8xge"
    b"jvPqcov2NSqW+o8K3vAI55TqEon1YQ/ITSfcZ235PQyU41AvjSKcOyZBygzSG3q3l/hNJ/xsdX7szZWoXdWrY+bYm5LQ1tSxuTZV"
    b"x8yIieoIaY4r21lm0Q7DALbkFpSnPqz2TSmqav3sM6rAzE6wz44KW++YLfTatsacluB1nTfUcj735q+v36uyu6Zq6l2q97dVxLSf"
    b"XiuIwLyGFbXOic3MlFNH2rOjxzAsWu02rjSc06p+rc92BTYYm/a65G66loWcOb9imHTVQzbWzfxubqM+1Q5RVc/UuCdzlnYiUUKW"
    b"LEz91kzyjvtITT2IjOXcGquzs7PzYlPKZ9ZHvjDtf2AzLmrrqZazY95wqkAaDHHnKENXmUbUdiME5PN3s4SyYydkZvOlOvZW1zb9"
    b"QRH7nim7WsXvnda0+nX3MD/KOs6YBbmwiNo3z5Fz6ktue1oP4CWd0DBDNXygA1fOCPva/7mjGttbP4y+l1OcK8q67LnbWzTjKND3"
    b"f2d+OX3TG9BRfFy1lTEBjWUa5U4L44DWxyj7wNypsc1s3ls32QxPqPTuXLEPD8f7V5Q/MOdbYHxTeOw3Ux9lx7xFa55qan0DK9bh"
    b"xLrvnNO5BhptQ1SmBzRkcbzfohlOjt6c1tNWHJWh3O52Z/6Jd+eCrIwryq3fO7UuO63cSvhhQc7qw7jkDNCAHab1wJ6K7MGm2HZs"
    b"TW1tfyY2Y/bMeOCNnTSrTF1k7IGekuDAnxdMUxG27kM8vsVxyp7G+xm7UHFSbErhlifXs7uuDJ/phIfS5k0MDXsoRqitz133zsZq"
    b"YdX6hsw3n5CvX5ua2Oogqo5szeUUHueixYbeC/MwKCM+th5qxcunR+dWYzqidpJULjiejRPYCTOVOcv6FoGm/D51vIvn4d7cWRP7"
    b"/M7m+Z6hUoem5XeCnrkXa3NeNK5js6pPuOsha+ctb0X1lcYQ58ieRMsJV+TUkeGB+qg8xcfehSH5ttVBsuMkvraSHBydUIE52xXf"
    b"FaZWKgMzshUlfY7XxrEqWtmaUyOxOjU9On0Gpo1XpimUNonrnROn3WdBoN6S1dHddnfkEvbGGBegxcPRV6saamosjqqfbV9TYpMe"
    b"1IEyIXMU5q6Nj95vVcDXvC2ts3s2DatlsPfW87M94t+tsQrK8mzsNIMNOpnGe+XW2ulzga2yKZ1SJ7DtW/LL3s5EaMwXGVt0Kq0v"
    b"RN+wshTl0dHYvLeLwmPH0sDUSd0553hvIibD6F4tiJea70PjBAvrq0m5C63nVqbUq1ezMMfEnsp1xOw9nXGocwjfnz/ZVmindJvo"
    b"fLid5S6tm2qr10vTIQbH/KVn5yh+X6EPKa6f0DGuE9I2puWNzP3REBNGVC0hkbwyDcIde4LeOSD1RLKDaVpa9elpwCNYxQnYaYc/"
    b"+4743QlSm3Cg8whKYyWVKdX1pJ2rA0PN6nLfH2ej58Ynv+sFLd/rzW39gbVre1Qyq1tzm9u6PzLIWvNqLTy0DF1bBljaVw0NWbRq"
    b"Vvc4USuxLnp1Amh3TUbGqu0kmJ55JQuLzYWdJp9avTqEPVKkrFfVsi0dm3pQHPmTkj7bJ3hZIjicO8POhTEWM+tAzcAWJ/SNPViV"
    b"NTJfc2LrSs/MatFnxyartROKFOkV5pdTvDM0hXFjSrUix4Ux22OYlAMTzYSRW5DTXoG7+sbmban8Z4YvpUf4JVOEpR4Sb9S3/m83"
    b"nMF1yzyEzM5G7Biz2zoh1AOuTGZq6mxh8d5Zr1PrVHzgGXVRMMbW6aToRjrYnqKPNU4V3DNyS8d8GAPzZofWj9B2IevqanvDNR8o"
    b"vxC/57B19uziY49r397KnI9aBSC2FVvYW0lsxakzRJ0IvffqlPcdPVvrPD6x6Xz74xSq3FxCqjy+Y1aXdNIsybBD4oXOqXhXxbWf"
    b"2Zl6oohlYVNIJ3YfhfEz6k6oTNVu3vOltC6V2LwLiknHPOsL639sr2935Jxqc9fs7C5a7b3VI5UHVEW4Q428scjRcriVTQHt2DkV"
    b"LT5qWSCtXvV9Bcdzf9u5062rSasIVVtafSs37mfHflizjgfvOZrKo9M7PLrBu6ZbF8dexHYGoTtm+YLdc2exP7JTDd6pgA70uCRe"
    b"tH6JBV39/7mrM11uGzuiMHaApHZb8WSqkrz/g6XGtixZEheA2Jioz9cNaP5MTblqxiR40bf7bP1otWcDeifv/mi14ER6SAtCoryr"
    b"NqbRBLeUd7Eb9Nc3YP1CHgb6iDx8GAU3eUVfcv7kIu1Jsxp5IxvUKgPq4sVxk4LbnMFkHRv0fjAhY23iXUtxcmV0XXWo4bakeU5R"
    b"6XPY1DHmnJT6oMlVv/4FF02Cjvts9UkIunLQvevdgBx0nDHn/fQ35uT7ym12jiyYFCVSGhtwfFovLU34m6XfF7Zd6bvtwHhFKZSs"
    b"9nKoGypNQ/4T3eyWlPIrvDR7GMDe5pATGOAYOyVSsJXWavSNJTY82u7gzlg7pRqfyMGpQN0S+NCWDSqNncC96Zd+2aQ5g/UpP1ks"
    b"19lO9gSyKv3YEI7xmdotNW5GJm1t3/3RuJTCsDnl382RGiFd1ntoyw7wfgU7cjM2ariKPbF3/TXywsXRez6KT9/DigW7oLdoYtOr"
    b"klRfeONKausOB4zmlxIlw411Ove202pvqWZPhnjMMC7aWjlyFhzRFcvTr7R6u9Xmpo665f+FV9KU7JkqsPoclO4Se0En5hrVrD7O"
    b"bB9VOWcy8K2qGbmqJe+gOFphBFlwQ/Xq2/vZaLlzd+SsNjCce3yn4tv3OMCPNhe8Gt6+JRdkj+o8RYdQ4mLynO6MSUIJh/IWqIes"
    b"qaklteKy8kEK40/YJ/QOfupZKVkih20CCjSh/E5JFRnI9P5qiO7ONE579v6VYHAFSpuBs5mDSSfs7XKsS5mOPXP7lkR71/Cpi1QS"
    b"QmqT2mvkWuxNUaOJUL3dCTXRFehFEZ67K/rlIhBUIVYz+OQ1+x56fIi13VHuRZ7QO3eBD6X22R9MN/uRW/iA9/bE+6EO5MQ+hCZu"
    b"7RSdQI2PYyAHLke/suxJ9Lw/zzQqcVcJa7/hqalHuAKz/qx3K+BuntFlC03+YXqineHE3yxF4bept1TXhUuN3M4fjM8f5mv+4M3k"
    b"aemDu5qY0xfPzAUHaB7sa82nKyL7s2JjgjP74gGzmDunT468BE5w4jaVS/lgGE1JJuiJk7cJpmwiz1Anqg8tT870PeEnPIBQl3Zv"
    b"H0OX63kA/l1ndlhtrI9Qzv5P00nL7bKziaZCwS63SG//tqXG6Ca9xQcuZ+H9p+xnT0XRBLWJ3965CM0cZ3u3lYI1R2qBWNSeWXRn"
    b"b/GBN7cAU1l8Pmc8hN9sWpeCTv+cIyXI0+IvOGsTspI1gbYgSQ/2xmkHg25aTdEttSM3LkP7uRtq00guRGOM8ot5wH4aGqvdKjty"
    b"QS5whWewbt8G1+NwUC6IVJIvNgHOdvJv2OQygx567vctWGkafvABT4lSjZXt1QVrWqAKm6K7upAFm3GTJzGRd5EIdTCkRckzD7YH"
    b"Y2+dwC82FW7h8ks802mgaXIlPRmmk1nS1cdGjT/tCZUxK2fMGU90BJl9s9/gnefozdtw7ns35mxuh8eiCo9/zQ3VwbXd4U47khXi"
    b"GHXOfSdnwYXE+Z4NteLbd7C+Jbfas33bAqfQCDpw5Gb0BKqGXdlJIsT1q3Vso3Vi/7XdenfMU84rPsU8oN3B/sZ1djK1Qy21HWpy"
    b"aTR0TkXkYF7RC83c9im6/RfDgirU/7+svhR4HQtTh3zMwreWN6SEl8Y4iQNcurrqllyE3L7NM2oS5SG7SuMmEj61I/rA9FXToQmb"
    b"ekOtvAMX91kuQ5uagIqM4cM+oFPNVjlQJftPdry7UnPcUuGEf6fmv38iFaAH1dkZ67DHKTajsujpWz70RX+Y+6Sy3TE/jO8d0TBM"
    b"qGp27N/t8JGpWu2YVLrVzKI66cjxic+eoPxK2D+24YkcIjXflUwd6SLH4GGVFHkNOyPf3CZcGM0qC8azBYVYv6PA8b15GZyWtCjS"
    b"K+x5yhVT3Ih2pzb3+aPln31Ugg8k5982ocxU5IoMrQc+14EktB2KAqERNfPXSDbs4lcomCTzUFN9sV/NE2wqMvZvrPdyN+QGJUbO"
    b"n7SkFF6xQ/wt/Fgv9sZ5PViUI66PzNhwrZyYi+F6dzCmnWmD7g3BuDOW8bvx23vLSBUzpX3te/zIOvkDs3ljm2b+aWkawp5ezOv+"
    b"QppcHbywdz16Mu9oMlq7CZzd8bzcCgfkGUx5umjLR2131LWxOvdWf08rRd4VPalnlAnLyc2t+52U149Nnv8hjfGAqsu7fle2CxP6"
    b"DdpW2Gd9hj8t2Mm4ZUYo2InwZKmObeRETeGJ2LAFxZW3L5Flplt6rdPXfoGJyqZ5eW/MwCPp9sKjH6yKvdoZUh8p/81v1McDiPgX"
    b"tp0vShzHOsqYuXxuWTbLnqI6Ko26itTWO7YYjfEJa/CIFsVoFrzsROW8C+3Hl8B5nI0qIu+vJP1yCsx4prec6Kani3MDo/FZB2bo"
    b"K9ytAwhcy7whxYFv86kCScjoIrRr+5a9IHtz2peWwnpHpuIIdlPAi57AKk50P1+tr9x/4s1mttS52n6M/ArvXE8xr7xH5R6oAyO6"
    b"GNc4vpInX9mNeARxT7nhxO74ZrceHaB6gSPYmKbh98iJGUOvJV2gTqvekH+w41QajVvUeBNzwZF8g2qFv0kDd23z3Lt1eKqF2vws"
    b"9Yd4sYIMhIzaqNQkaRalgj+SIqZecoO/TbsgvtI1qtr5qZ7iqRXB+8/hNew44xvyiLrVSdmCL15iluuZEu9g2D3rzFGMGj93xozh"
    b"PuoeH/V86SOt8ogT9Mrej4RZyFM8U6bNzOa4O2bxV8M93Wd/ZDJxxMhzaBvrTG5sMlnYkkV7oE63Rc37kTP1r/9PjV/NMaQb7IiO"
    b"Lgvsbyah2TMst8zjeTwx9UW/UMm7pmpm+uhjI+MZRdoVvpGObrYMVe/6F1Fvd8TzUIPS16CRUqdkkQGnjqThdtfMK/WktFjPaBMa"
    b"uoJz7IR9w9FZM5u756uITRYN3azr3mfu6Lc4ZR35TXt8aQ+GqtZ2B4jvfLZbqo+nkzGNuf7utFKRqF4f4ykeIm1pYKfwgVzsb7ZX"
    b"orRdGM/GJj0bepMkvm1gwnms3QB6Tid+gYqb4gZH0Bvdd48X05+5VOUZ6M3J9DB/WSpajcJJCR0NJ61kUnw2nL5auVLewvnSg645"
    b"9uronTqzF8usnFb5Gp5vUMADX8CZ9bssOT0Jvr4GvfgZf2wCKiGMvwUNGq1+yN07oxcuyXo6wp3VIPs96RBJOAf7UNgKsWxWmilX"
    b"qw04LyYwFGV2KCPlZG/pFTrgRfGahTvPXfrXuHuALO3bC6Os0M36/lDPipNGwV3WPbztLXrABIWKe6YqfEnXnLgu+vQKFY+0bTpb"
    b"O9JfuuhIpdtUZ1CzgawONGIKFYTPdls0bik4yUz/UcAX9dTGy2XhxWZuNs/FcgblvKrgC0e7JRkjDQ+bZzl2kR/VrnA8v0/cjTOg"
    b"Nfa8L9fE5HjpPdlzQyVxTmYGudjF275DZemsgacfdpEg1sUv6UqSd9JKmnBsXOh8fU6YQ9Hmya8lbFqJot7vlg09XB/ost6sZzBW"
    b"6YX2TBaeyp5Y/ytVQhXZ355JfmT2rJnEdZ42nJ4WJK6mksxkiPR0jFVs9vE7xHNNBpixGd5kxgXs+2zc8T6Qpillfo/2ybMRKjrE"
    b"JelpRL8lj0RtlfPFtpT9vPxpc3/NlgH1alvu9C7ucH/zXUvn72HKn7rHsg4dTUqe0tKF+cy39Bi+HWdCX7CxaenRkpvS8FEN6CoK"
    b"dBW+w+iEDq/ilxpxs3n+p2t4W3LDKpRx/oxSkvePzKa72JPijMOEp9N53IEkwN7epCWVbghFwghaW9L9ufNg/psTvMI58253RMZs"
    b"eoBBqkEHy5X6f+T/4OkQE3+Lc0eaBfJVrpN3kvouI/6RATZTt4imggptwRtJMle8nf7WL31JTa2VolQaKj+ldagT81We3pJZnnC2"
    b"3Yc+8jQHFKA3PIkDusOKLqSDiVemrk+5X3C+dPQwOlNtaNBGuIoNU2ELT5GRhFjighjJgeliu6hrrxfOugn/krsMB9I22vB8q9cc"
    b"I494wbTK+FNVqS1u5xcSNu9ttjiApN/CiV7ohka2YYzRZf/9hParnJAcRHAbbNANCtt9qMoH1OotuTBC7BznFBqh/+YQmNUATuaz"
    b"idCNzYrVGfCvlitNnc8YDXhNFp/PZ5c9zqgdiocFPyyjtpdMBA2JGb/ZKODP/cKcM9MFOevpGQbOS2Wc3Zkq3fDmdtxlfn79Tpro"
    b"u7fMJXPokXTrLn2Rqzfz2EqrbkY1XFj6eiY44+rzv7vlfizpEl0D90a/0LD7tgUt3Ia7rgQluARDNF3OZORncEuZsZQPgSLfo6vt"
    b"YgfcmVmqCNVtHneUp6A60yyeb0k2zElxEjYrVdMDtfwQW1n34cf2p9t/6lZde5XHFLDcMCm9ZQO3sGdSzoJjc5fiuPLzOA4idagY"
    b"rIrp8giX6WnfBd8pCf+Xf4Yle8a7TlealCvt8NsKYbwBYTmDp+5QFSjPq6ITPJGN6mjJETwmweMkBYVnXqTk/XtXtTfc7c3mrA+V"
    b"xg9TTVdWIe/oJ5besgq/ch7uqUWpMsOxuIPuHDjkBZ+M33zuPknj/tfOLlfBLsxKuco68cSpczhfXZ8ww2U2dJvvdNoNHFZlKJJ0"
    b"BTnnxbU9n9nAE+k9u3AUlJGe4RXvvMrkkP7jxHnYrfo9KR33diOe424/cy9dk2Q7h598G6q7TeirnWV0lilJ/gdQSwMEFAAAAAgA"
    b"AAAhXNAXiYYIGgEALMIBABkAAAB1aV9hdWRpby91aV9kaXNhcHBlYXIud2F2LHwFtBTH93T3+Op7uCe4u7t7gGAhuAd3SHCH4PDD"
    b"3Qnu7hDcHQJBgvvbJyvj3f+C7zt9Znd2Vub2vXXrVuXw0rxB3bq5z1Hya41WdXr0H5Y9nhBCsSacwMlwSgQST7p3GdaF4DOMS8Tg"
    b"PpLIU5EkrhCRhHmQRLiIT5l4T8LrtOQrT01i3IsrcXgdR1zu4moiT4PvM7w28U0vifJ4YnFKVHzWg18VCOcGl/G7Kg6CqzYP4/kz"
    b"fv0LzqM8hes8gmsxPCfg8+/wyQ/4hQjeE0gI341xk2s4C+D3KO4Rw90YPuVHfHHk27OPBHGkwqsgSYcjLUmDIxXJjF1mJhlwlo2k"
    b"xnNmXE1HsuJzGXGukLxExpWsxOZ5iYP9pUbsWYmO3cvYTwAxCLge5Q6iS8E+EnkSXr3D8Qkrhb/iyfwjf4/rb/lXRP8B7yfgLMJD"
    b"OGLYlY3YLc6RIYI8Cjg8+G0vYpYRlRev0uJqGqIhmtS4Vzx2JqACOh5TcN/Q99/6hN99hl9+zF/z5/wR/4/fweubOK7j2n1+FTGc"
    b"QiS3+T3c/RIie4wrIUQVQ2wGMitjj3G4SwC79ZN8yEJ+khvPJUgBUpEUJDVJcVKNVCelSWNca0QqkRqkLqlAGpByeC6H98uR8qQq"
    b"vlGT5CBlSBH8TmnEnR+ZTINzFb8oYymojkCSsfMIf4m7P0a23vPLiP8sf4pXR5GjA/wB4j7C/+WHsI9L/Byi/pvf5bewo8d478n3"
    b"XX7iX7As/M43fFJky4dcZcNzIZIFsZdGPWuS7Ii7KmJoiHqWReSZSGVUtxg+mQGfoiQ9+Ya+CDKSgGy8Re6e84u4w3HEdJ5vwz1X"
    b"IrJdfAMel+HqZr6TH+Y7+DE8nsS6xs/wh8jrA8T9GLv6hGyawK6GHWfHfovjjnmQtwykKSmMDDbBlfakCmmGVZ+0Q1xtyc/kF6yf"
    b"SWscLXG9KXLcFJltgDxXxnkF7KDW9xoUIkWxryz4jczI6Y+oVEYg5Nu9HGQhilwkYL1Dft4gqhfI2108X8bjFawb/AKQcBX7u4m4"
    b"r/J/cO1fRH0X37kHHHzGt7711zcs2ECag/7V0CHpcGTE47eVAffM/B0n8d87IIoKxLDrz8D6/0Pdafz6OWTpKl+D+m3ny/kevhD5"
    b"W8WX8tV8BZ7X4NVafGIz3jmCz1xARDeQ838ReQhxiOCEICqTHijKCaR9w1UTUg+Z+oV0I53IANKL9CdjSA8yDefjyWQyiMwmg/E8"
    b"jozA6xFkOPmDDCO9cdYR73UhbXBel3RHBr/9TklkPQdQ/SPQkgN7SYedUnRTCEh8gThuIprTqPdexLaRb0Gsi/kmPgVRT+YL+CI+"
    b"DldH49U8vgQIWQBUrAUKjgOjj7Drz8iBjpxQ8IwfOMxMSmEfFXHvqqhvve/1bUaakxao7rcq1wQOSqLGBRHLD/iORr5V8i1iufE9"
    b"k9uAtUW4w0Lcdx4fiDsP5r/xQbwr78F78y68L1ZvPhJXx/OpWMsR7VYg9ijyegOxvODfmFIB4r/lswiwVx+Yake6IovDyUgykcwj"
    b"M8kqspysJ5vJFrKbbCNHyXZynBwge8hpvDpOdpJdWOvJVrKErCVz8I3pyPAUZHYgfqkJ9lIau8uFaqVBhwuYBSHg7i6ycQBx/IWY"
    b"1iF3s/kkRDkR0Q7G6saH8D6IfQQfwMfi3QmIexG67QAyfh6RXwJ3PgEzCpgkBcGE5dE/pZCx0qhpHSChParYjfyEsyaobS10SnHk"
    b"MDfyl5l844V3QNUrvh68twa1W437jULGfkLeqvBavC4vxKvxkrwgr8kL4KwGL8fb8tq8JzI6GJ+fhBqvAgZOI4b3iMQPvBfEvetg"
    b"rz1IPzIV2FuG3Gwm58gJcoM8ITfJV/KUfCA6HkX6liQTk/xHDPKavCNvcO0eeUAukrPkDHK8C/meiyyOIkNIX/xiS1SlLJg2I9jL"
    b"Bnpe4643wC4HEMVKPgdVHYnK9+OtEX1j3oS34BV4KxwN8Koq74Dnjrw7djgan5sBnlrL9yPyq+CyD/zbTA6COfKDhRqi8r2QvxGo"
    b"2yTUfgaZgPrPRjf9D301inRGLO3AkjXAMZlRxwgiuQ0c/QX8T8avD8C92/BivDzPxdPy7DzGMvMvzMtNlsTS8PcsG2csPc/LMyPD"
    b"FXhzxNSLT0P8f6HPLwOJXzGn/UB7MVStLemDO48iB5HH8+QKMhMmt4hNoiSJpKMxkpamogrNQT00Lc1MZZoJZ4SmpglEpiFkNIVc"
    b"Jy+Q/dNA60Zgcw4q8gd21wU9Vh/7zYkdxDAZHgEFF/hB9PL/wD5jgIKeiKspcliLV0L1C2M3JYGBcngszuvzUninEXbZG9ichMyv"
    b"QqcfB4qegZ8MsKwPfP4jurYicNcK2foNFexFfgcmBiOPPcEy7civeL8R+L882NkLQXUPDLsDqF6GHpjGO+G3awBrRXhuZMrPv+VP"
    b"4J8ZY19YhBH+kWXgUZYF+c0MnJZHpXuj+tO/s+YtrHfIooxOLot7dAaCJqErN6NbL5L7wGEE+ZNogPppTuSsAC1EC9MStDzOatH8"
    b"eC5Df6RVkNuiONLgc4Ra+MYb8pjcRSbPfv+tUcDFb9+ZKg/QIKCnPwCRV5DD9ejS8bw/OrcO6lscXVQY8f/ANe6yTMBCWi5wh+UG"
    b"DorwnLwEPtUQ++2Hrp+FWbAXmPzGbD7MkeyoUmV0cE9w+Cww90qyEF2xAfffiLMF6I/RWF2B1lrQFjmRRxcK4S7fDS6ZBP5rifrl"
    b"5xm5yBPZB3aF3WL72AG2mW1gq9lathLPW7BOsRPsAXvKUpjFfuRZUNmmiH4R6vCQnwA6OM8NDqmLfh6PfZ9GF38gApVoEaxatA1t"
    b"TYfQP+hEOpMupAvoBroSxya6jq7F4//oajqLTqCzaVc6kv5MW+Ab+ZBtEesTOOEquHIhplITYDIruF0mN7H3peC38bw9MJiXl+Ee"
    b"ZCvK7iDCI4h1ByLejPg3sXVsO9ZJdhzRP2YhoCI1z4cdNwU7zUb8t4HIb9rzx+9zZQSqtQw5206OYd0g19BJD/B4lVwg+4GMpWQ+"
    b"ur03IqmGrghAXd/ExJoLrvjGHcV4Om6wZHaRXUMEy5G5YWwx68MmsyFsDBvHJrAlbDbi28z+YQ8RbQB5rItMjuEzMcVvQcf5sLvq"
    b"pAO6YClmxC3yD2HEC5xVo5VpD9qFjqAz6J90PbK3je6hu+gxHKfpDnoYz+vpbmR3PR2LLP+OjHfFdyojj36s1+jwS2QN5s9viL8+"
    b"JkAJzBYH6uUw1MNkoKALerg8+kQF7l6xt0DBVXYGeduPuu9iZ9lhIOMOu8ti7D3LyON4WXR8Bz4MnPRtrn4AN/wA1q2Bju2KSs1B"
    b"xfaCz09hB+fJv9jJNSDiONkHpp+LPhuMGOpjkirkE/K/F6jujomSA+j/wi4Df8vYH2wAa8qqsEosI8vHAiwtS8XiWDaWiZVhRVlL"
    b"1pYNZgvZGnz6LTNYIfBAN7DCBsRh8cxQBR3IItTrMjhOQJc2ot3oXKyTWC+xqODQ9EIGIatQQsgsVBUyCZWFLEIh4QchTsgoRKkk"
    b"PKdv6Hl6BuhcSMcj983R8dkppSlAwnHsYTi0UFloUhta5TT4cBS0RHl0scxD7BEQuAmd8zuq3oG1YO1ZKdaOlWCNWUNWh/VkrYCF"
    b"SUDGYXaavYapC2JuNuVDwZB7oCJtzMgqUDi90MHzyd9g5weYgF+IBhYXwDQmEPGVJCCrZ8hJMP9sRNIYTOohbzHptnyvZRFUMoH9"
    b"y/YC/2PZb8hWGVaRZWFZkcUg8yKbAZYbqyz7CfGNRjy7gcs3zMXkqY3ZOA01uQW1kwM4GYiu2I5MviUeMGFV2p4OAwa3Y92nd2kC"
    b"jVFG0yBvPwi5hRzIYQGclRbihfw4NCEgfMInHtHbyPw2uohOoT2Ry2pgVC99j77aD84agClWgHzzxOeBpUng6FbAQj7+CXx0Gd37"
    b"F7I1BbsYyJqzrqwZ+5V1wzECCJiFLtsHnL7H3MzESwNDo9FLR+HUojwd6vMzVOs08OBBcps8Qs5SoCNUGkYuP4LfHwOVJ6DXZgKz"
    b"DaG6RPIP7j8F86oo+PANOGM97tSGZWep2Sf3sXvE3eUucWdgDXWnu0Pc+e6f7iZ3t3vW/ex+dAuz4qzLd0yGGAUjDUUW70I15Pze"
    b"EUdwdw+tAyTNQcfepzLQV1NoJgwTpgpLhQPCPuGBcE14IbwTngsh4bXwEsdt4aZwUdgm7BDmC78Lo4TqQi0hl5CEfO+gh+go2pbW"
    b"xDw3sLvNuEdj6O/PUDszoV0q8kyYfGfYNtT2F1YP1Y5nL9377hXEe8Bd4K7GPpa66xD7Pvee+8Q13MwsD+sOrtrKLrBEzJ0a4NY1"
    b"cGMiJkZnIGATeQgOyfz/EdCBDqdjEMEU8HVfOpDWxcqF7khGPjeAveoBj4lQfQuBxWLglLuo4gT0c1kmsWT3unsQcUx2Z7u93JFu"
    b"f7ePO9X93V3hbnQPu8/cT24GVhJZnwIOfwpEloeGWAiWfc/zgqPHQvVdRVf/SOuhL8fTa/Q6DdHsgl9ohXz2RJZGCEuExcIaYQvy"
    b"9pdwUFiH59XCMuF/wiRhtNBd6Ip+rwKMKoJLb9IrmEBjgejStBhlmPvXv/ue+tDfPnIR/TiXNwNDB7n1vZs2o6dHsrqsCbr5B1aa"
    b"cbcIWCkDKwdmaoZe+o1NZwvQ/Y/ASVkxZbrA1ezCxBfAFN8U4QJk5wR07HMSwGxMS3PTOJqX+qhKXSiOh9jbAvRbNWDxKxzLIqjR"
    b"otzGPFkE3BdllD1wNwBzzdwqbmZXd0zngvPcOe6ccW47R51PzhNHdDO4pd327jh3D6qdhlVA/Q+gO4pCq62FI8wGnGwnd0hB2pjO"
    b"x+4TaRWhubBAOCw8EXxiZrGR+Is4WpwuLhP3iTvES+IJHBfweErcJv4lLhDHi0PF5mJ1Ma/oConCSWGjMFZoJBQVdPqArgAmymEv"
    b"/0EDT4DeEaDWRmFCxEHdnscEHAoMyuyRu8hd6zZ0f3aLuQJ28cqJIfJ/Hdd57wTc9G4e91e3g7vYPer+4/4A1hoNZnrCCmK6LoPy"
    b"5bwWpu8uMKKGirXGpFtDj+DeT4GBMP1MbZz/B6ZZifUTlIRGn0DZdiatMeFvQO/UhNK6y3YimkLgwAvuXnfE92wGXNn9iFzede45"
    b"N5yHzlvnnRPvpnMruV3xiX3ofdutyXpgLn3BBOyIib2fxwEjE1GvpyQVLQskLsBc+UJLAIWDgL+N6ON7QlCUxIJiCbGi2FKsIfYW"
    b"6+JoIrZAlkuLDcRMYh6RC1HhqXAWGJ0kDAEuiwop2MFmOgndnREceQC93YEUBRpPg9u7YUr7+TMgcQ6mSjVgUHe/uBfd0+5Wdz16"
    b"ehWyuwHx7nHfunfRR1lYTfTdCEyZe9CRTeA7bmFaFYHD64tJvJW48An50UmNaf/v+mwMjp60O61Bi9N4+gZuYg50eBGSjMkyEn7P"
    b"ASeOYuWZ4Z5yR7n13aD7j3PAGel0cco6OZyAE7Nt+43N7WQ7zsnjFHOGOoOdv53/nPRuZ/T4OzfI+oNhTNYYuiEJbnQGNNaPuONe"
    b"VK4cMnBYsIRCYndxvvi3+E4MSEWkOlIvqY80T5omrcFaLG2VpkpLpKFSX6mNVEYqKLniB6BzmThIrCWmFj8gj+PAkoLwhE4GT/np"
    b"LbIYqiQVOQUHUpFzTLnhrDqLuDfcKUBaPjfJueNsdiY6/Z3GTjWnnJPbKeEUdCo4PzntndHOWue0k+TkxE7XuMfdtOxnNg0ISANc"
    b"7+Ey9PQCaP0AtMVg1Ow5zSv8jLVaGAk2XyNsBgamgd1bCA0EL6q6Bwq3NjzCVTiciuQlnHRTLvHj6IuC7B0mS0e3qpsI/G1w/nB6"
    b"IYLKTlYnn5PJye+Udio5fXFtB6L56hRza7vL3ctAZCt0x02osarwRLfR2wOgS6IkPfa9hv5NfUJxoROQuA+zRBYzAm9NxcHo7eni"
    b"HvTyYfT1QfGyeBqdfkZcJa4TF4r9xDHIYnUxtxgWwsJeMOcfyGVeIZGegwrqCNdjQvtMw1RNS54Djb0x5WR+HhqjJxgwC3vlXsU+"
    b"xruT3HZuU7ctmKiDWwfn3zj+kLsNU9IPzTEc0/we++ZrRsAFveRZ4L4mwzG9JmloRaB+LF0C1XWGHqUXMSm30Z10NPi5Gs1GE8ke"
    b"IKYEdPcOfLcAv802YubKbCvQlce956x2OgB1Yfumvcqebve0W9tN7Ho4WtkD7bH2TvuCzewizm/OTueDU9Edi1nzI/j6HisFpv2P"
    b"t4RiVMEZe6mAubwNk7iOOEC8LiaK5aTfpFnSNemOlF4OyLXkmnILubfcUh4uN5J7ytXkqnJeWZKZdEo6Kw3BZwtIKeJ98GhX0Ss+"
    b"RgXqCh7hKO2HCXkLzFiKPOBLoBRDbD6ryghbjOzI7kNnnlMf6Htk/21Psfvbje2SdnE7o50Hq6TdyO5mz7CP2a/s3E5bZ72T7JRw"
    b"l7lPwUmr4De6wstlJUOhsIuhgx/QHJhyO4X3QjrxZ/TSXHE9qntaXCluEGeKrcA9rvAG2GwApbYX8zsrOGYYHP5uXg/KfzHU9nP0"
    b"ahF0xnKnu1PI+WA/tBfh7oPtZnYfu77d1x5qj7MP2Wdtxy7o/OpsBF/+4PZzt7galMZ6OO8KfCNmXm0yBfO0KO0M9ERoVUyKw0KC"
    b"kBfsN0bcL54XHVGWCks1pAZSP6mjNFYaJA2XRqDbe0st0PWlpEwSEz8Co9vEPphLecQnwh2hr9AavXQZLqcCFMAxMh1K+Ss0W0eg"
    b"4RkUd1uWkz2Buhji1nALYrZ8cHY5fzmrnHHOUmc88rYBbPTSsZzybmNooPOuAicxnn2E2x4EXozxzsDXZ5KTdoKfuk6zCgWFHlAU"
    b"s9BDi4UTUBDz0dvVhfLCa3iDUeiHRHy+MnT3KJ6bnwE7CGw6UP+v08cp7py3p9rV7bB105pt9bcaW2WsAlZeq6BVzvoVr9dZ9y0Z"
    b"CF1kf7Z/cpY4fqigm24LsGNhuBiXLyEfSQ/6mhbGbBDRt0/FtNJMICweuPtTviSH5B+UckoXpY8yUZmnTFWWKuOUUXhVTymjxCtv"
    b"5AvybPkXuYj8WNotdZZSS88wuSsBjZOEMsIlOo4G6RGo7q9Afl5+CypXY1vcem6Ks8Cp5yTaW+2Odjb7tbXdmmg1sapa6ax4S7Mc"
    b"M6uVxqpldbCmWletJKseuuyFXQnfYU5397ZbB24xL/ykDN+SRLqCEXOBj98JDYG9K2Je8PVoaYa0XjoqrZUOSxOkkVIjySd9FWcD"
    b"Ew4Ysw5c1zDqoWuhHv6GM34GD0jZOrckZvNIp4rz1V5jT7bz2bnsJGTvhXXYemLdthIsr53f7mRPsm/bht3cmeM8dSq7w9yvbn50"
    b"2Bfox638M29FVsJFNYAH/EKzQHVvE94K+cTG4jRxr/gPsJhdKi21RO8OQqdPlZZLi6QF0jJpijRdGoirzaRyUl7g8ZN4Fnv5HSyZ"
    b"WXwHVIwQqglUOAcdUonG4G67Q/c+wqSpz1OQiwHsR5aEyTHELe8y5w3mzGJnmNPO+cWpi15v6nTE1FnsbHFeoPpl4Cp2ul5oy3nQ"
    b"37n4UuiVonDKx0ghKJnt9B31gM37CGuFM1iv4BZuCNcxa2YK7eFgY3Q5NLmX/kXaA43zeFZ+iDWC1hrjOpga5Zyn9mw7u51izbW6"
    b"WYWtJPOjud88am43d5hXzTumbOW3ulibrXdWNeAx2e7gnHNKQUNkBr9mAEKywaNloLPhWSYJSUIX8bZYRpovOVI1ea38Ts6q/KHM"
    b"VB4rYSVerauWUfuqv6pd1X5qLbW1mkPNpEaUs8pOpYNSVYnKB+URcjb5hTROKiTdQl97xTVCOeEilNwrTK8odJXMp7N04MTc7jbM"
    b"wBvoEBdRV7TemXPMlqZqPjb2GJOMIUZXo53R2xhhLDIuGUlGOXOSedOsaC20fPaftmUvQEa3uBXYJTaAR/gyaJwjtDH8VVvo2VrS"
    b"NkmQe8gr5S9yvFJaaak0QXQVlYKKKZ+UZ8m55LdAgSytF/3iJiEoTKUi7Ube8Mb8FKvMdrqF3aNOGec+eFCyLyGf5SzBumheMReb"
    b"a83N5mrzofnMTIeuGW09stLYA+xrdg5we8jp4F5zS0N7poMvNHknco+UgUqlQhvhOLR3J3GnmCRWkAZIe6TnkkeuKP8sj5bnyGvk"
    b"4/I+dPMZeb98RF4hz5N/x/QpL/vld9IBaaJUT/JLN8VJQGRI2CA0FSJ0A60Odzud5CWXeQ8ojM2sAXuPaVHW/QwGrO9kc67a6+w/"
    b"7Ep2RduL5bOZlQcd1MqeaG+zdbuwM9l55OSDmvzqdmI3MB3387TQ9BbpRp/QfEDgS6G8OAe87JGCUgVwdxWpB3r7B0mRDoqzxFLi"
    b"U+AkjbCaFqEbyA9kDbzTZPbabeHehSI8ZReyD1k1rFvmUDPevGmMNVoYOQzZYPoX3WekMWoYw43dhmL+Yp4yC1gbraz2bruUc80Z"
    b"4MbcfawK/8IXkVxQW12EOHRiIemMVEK+LOdQtiiu8qt6Tn2nttB6a+u1p9pNLd5jatQT53muvdOOaLO1gVpeTVcPqd2AywtKP/Dk"
    b"VrmOfA8T56s4UiTiMHjCoTQFk/Qp7wx1UZudQ1/ugSLcbhe1T1iVrcdmH1M2Dxq/GumMh/oy/Xe9iV5GL6fn12voHfSh+ln9rV7V"
    b"WGq8NQabl8321lurm53RWek0cSPuEtaIh/kacFAKnS6UFY+LP0tPparydTktOuiS8lUppVZRf1HbqTXVYqqongerF1euyEPk95iL"
    b"KfBdL4Q8wjrKSTNyk6fj8+CkO7pPnZ/R3V1tai8H5gTrgrnS7Gt2MRuYTc32OFtmnjR1s4w13rpmFUCFX9otMROLwGEJ0GFvoR1u"
    b"8orwAkE6lP4D9zIT3JJHHCceACeWl9pDbx+QkiS/nFFuBp3TB6uHPFnuJg/D0VT+SS4sZ5IdIPagtFDqgqktSuehOBqJqvi3MFzI"
    b"IfwLRZKL/kO6AAl74KQFPhGe5L47HHPyvDMX3JRkn7ZH2M3tArZiR60P4PWQpVupMDs72BswX7JDnV8BH61wDXc0e8Z+5Y94OXIJ"
    b"Pb2MZhQ6wmflE/uL98Qv0GltpK7wCkOl36XuUGFBxPKHWEQ8gR57j5n+ARPvAi/HV2CqDHHvQO8fhcLaYWWzNpnNzGuoWxUjrL/X"
    b"l+t/6Yv0ufrf+mU9YNQz5hgpRiPzvFneOmPVt5/bI5008D9dmI8f5V2h/4/R9pjRG5Cvh1I7+aPcW3mmtFIPqpmAuKNAYAVPX88C"
    b"zwHPRc8/nsee+55rnp2eZbhW3RPwXNPmaZW0JHWhWlq9Cx7S5aHI5wjpo9hLvCJUFtZSh/Qih3g2PpRddIu6Q53n6NtZmMbtzHtG"
    b"S+OQ3lr/J9Y3li92LDoz2jyaJZoxakWUaI5o2ejI6KGoEhsUexzrpH/WJxvFzH/NVVZ7O59DoTX2sBlgodo0tfBJOCb+IVWUP8iz"
    b"lULqTrWotlT7olXx9PbM9/zlWYrHjp68nrfacC2rtkz1qVOUW3JJeRS6XRKLCv3pZnKXZ+Q/sXlAY05niv3KamrdAP4+GtONioat"
    b"X9O36Uv0xfpq/YT+Uk9rtDXWGczoZF4ya1iHrIr2Obue88zpCUfzP5YVbFOVXCO/0Me0NabcT+JRMT/c3zuphjxNfipnUJopc5U9"
    b"yn+Ko8SpBdWialnMnEJqVlVVQ+iiLcpQpbISVE7Kk+Sy8gOgMrd0Ac7mA5CdSphL89GlQOJGnoavZekxZ7K7q+D3jtsN7E/WTKuY"
    b"9cncaPY0a5jp0efM0I20Zn6zhbkIczIveuiF1QUqozXYfKibiR2Cj2VQauXpGzoQXn+tmFHaLAXkwfI/clD5VZmsLFB2K8uVP5Xf"
    b"lCzKS3m8HCdvBConim+EYsKf9BIRSG3Udbv7ycngtLXXWc/MKuYCI6qP1r/EpsUKx+5Et0QHRdtGO0U7RmdEj0SN6C+xg7Gi+n69"
    b"jvHe+J/ZEBryjr3GGeT+xLJzQh6R/XSm0EosLH2RdgOHQfW02lR7rfX1PPE09W71Mm9930jfft8131tfyPfa98p33LfaN9BX0Kd7"
    b"V3p/8qZ4Rnuye1Zo2bS/VAl1fi/XkPdKBlzDVuErrUUnkms8LW/KVrnPUOn+9j5LsVqZu4xUxgD9VaxV7F60RzQSWRlpHBEiT8K7"
    b"wyvCq8Nrw5fCSeEikamR55FW0UfR7jGvvlcfbJSG7nhvnbH3OyvcWWwaH0j60pZCZVQ7Kt2V5yu1VEOdqqX3zPV88dTxjvZu8Z70"
    b"HsHjaG8Vb5JnhiedZ6FmqW3VXcpnuZjcSZomnhbuY1YXJLX4VLbJfQ0N3s2+B22z0MxnrjAaGhF9kz5Db6H/pDfVf9bH6ev1p3oh"
    b"zJunRh3ziFnCOmpVsa/YXZ3PzjT3B7aF/cTvwhFEEZdFB2PqdQAWs0vjpatSDrkztM8LWVEqKO2UYcpiZZ2yVzmuHMCxU1mpLFQG"
    b"Ke2VSkpACcmHwJc/y5p8E9O6hPQW/ruoeEvoKTC6gP5At5Ny5DCvxS+w6uyeW9995PRwXkFXp7Z3QlsY5llznFnBzG2GMVM+Gc8N"
    b"bvxg1oYWumVmt+ZYiVZvO2IPcAJQO+WgG6fwwuQNGUDzCKfgXkNiB+kVGGmbnFr5GT7hsHJKuaKcVpYo/ZVCyn0oCUEeI0XhCHcK"
    b"slCdziDnoFtLs/buCvhQr93RWmvaUFrnka/b4JgfYzej26KTo0NxzIn+HbWjNWI7YvH6//Tsxj6jg+m1/ram242drG6ye5Gt4n+Q"
    b"n+iPQkQ4Jf4pNZSZfEjpgJou1jJ5VnrSev/wPvUWBPZ2+x76qD+N/0d/fn8qv8f/znfIN89X06f4Dnmbe13PFE9GzyotTvsf+ruD"
    b"ckRW5R7SGjFJKCS0h949xykvzH5yZzvr7aeW1ypmjjHW6ZFYxdiEqBmpFbkebhq+kjI3JUfK1+R7ySuSDyUfTL6fnD2lZcrFlLLh"
    b"Y+HOETF6I7o4NkLvbbQ2+1r97OnONvco+8wpzSbUEusif+2Uump5TQVvT/Fm9m3yZfUP9B/2f/An+sP+h/6l/jb+T74hvmRvVe9K"
    b"z0PNUIuoJZXackuppthMqEurkca8Bmvt9nUm2EetV2YRc4rxQv9N/y82IVYm9j56K7ojuil6Nno9Goj9FFsYk/WuUBEDMXOWm6Ws"
    b"x9Ycu4zzydngNmMKP8O7k7T0b/QJwZRND2+XETo2AB94X8mg/qbuU//B1CmvtdB+14ZpU7Sx2gCtm1ZFy6VFwASz1RoqU3aBQQ15"
    b"rpxb3gdXc0wsjepnEWbTMGmDbP6A3vng1oLqiXdGw2e1t56bncHkf0Kl3dRn6w30vLqmh2OC7tWL6X30NTrXOxpXkbvH5mgrr33D"
    b"Xuj87GZkX9kRPpt0hKIwhHPiJKkYpssIxasuVpPUztoG7bYme2zN1V5pq7UemqnOUL1qV+UiEFlR6iOOE9bQTWQ3P8r2uWedc/Z1"
    b"66NpGXmNdvrSWFL05+j5SLPI1/D6cP9ww3CtcPPw0PC+MIn8FnkT6ReNi52NjdNbGAXN1GBHy3Yd7ko8DnnLJGQFQ/tlLr9STqgL"
    b"tCYer/ew9ydwYVv/VX+pwB+BC4GUQDBYIpgvmCeYJvgicDowNJAv8Mzf06/6Z/qIb5L3maeBZ732Ce7mD8yYqJRRaiMOEpbT8+QW"
    b"5yzI8rlNnTb2dGujeR6TL6veMbYy+l+kSmReWA6PTGHJa5MrJfOki0nrklYnLUk6kfQxKV/yrOSE5OEpgfDe8O+RKtFsMb8uG3Fm"
    b"Drixzs4c9zB7wzPRckJPcYo0X96lrFIXaiM8pb2ib4Uvv3+v3/K3CIwPzAisCPQNVAno/sn+TP6Jvn+9xb0dPHO1Heph5bL8t3QG"
    b"KmgH2GYjX8d2w8E8sjmc4HDzipHf2Az9eik2MlY2ljpmRaNRDWqifWxtLCXWAhqoinHWaAbHOAX68ZY9ysnj3nUnsDzgxsEkju6h"
    b"FYVbQgvxmtgESjGbPBF6Nh/m3XrltSJiMjeD2p6kjldnAn0jsNqq1dX8akx5qKzFp4orr+WNUJa6tEWqJD0TB4kxYRa4aBrV6DCS"
    b"wjvwq6wa2+Cmcyc7IbuX/a/VFjOym+kY86HVEvWt+lgo8PLQ4CXA68Pw2tZrGweNAuYms5b1wJpsV0LvnHTHsHo8F5jxNJR3XfTN"
    b"OWkYfOsmpYy6WdW0LtoS7aL2r/YQj0u1lpqkLVEzqnOUt3I5eYS0QbwvfKQuSUtS8/yssFvKaW63siaZO+AAiuj9Yk+guq5GxkWy"
    b"RD6F74R34HgWThUZENkTqQz9VQf9vFofadSGJ0xnv7MTnTfuLbDLZfKQ3hV2iqelafJg5ReVaO+1Pz1FvK+8zX0JwONhf55Am8Cm"
    b"wL3A54A/KAXVYFLgZmBboHugcOChf5Q/m3+1r6RvozeNd5rnvlZBG6+eVDSloNxNmiGuFi7TW+Q1D8MhCK7gKHa8ldbMYRTTa8c6"
    b"RKdG9obfp5RKGZ38Jql10r3EEYkZEp+EjoWWhLaFzoYSQw0S1yXmSzqV1C25ZIoQjob1iBIrqXcw1pufrArOcvcra0Z2Uip2ktbK"
    b"H5UsWnlPW28TX1V/hsDlwPCgHuwadyLuZRyN1+NuxC2NKxF3Olg8OCFw2Z/oU33xXsmTot5StsjDpdpieuEp2c9nsM5uS6eqXctq"
    b"bw4wDoC7G8RuRatFP0Y2RFpFmkbKRapHhkXmRL5EakRXRUvGNsRq6SF9ktHCZOYZa7ld38nvhqBm5/AqxEevY1KXFe+IQ6UM8iI5"
    b"P3AYVKeo/6rFtQnaCS2i5fLUgpodhDXY091T31PCQz13tJVaI82j7VEbq0nK74qi/AlE/i49ECuLa4UQbUgXkf94Ud6fHXO5U9tZ"
    b"YD+3SljTwYrNjLNwfhfRLWJsD/T2T9GiWCWBiGnRi9FcsVmo/kq9FLTaFrOP1cjO78S7ARZjBo+RN/STcE88Km2W+ymV1Bi6urRn"
    b"lyeDdyh02l3vC+8N7w5vX28q7yZPFs9Y7RYcYRGlntxAaiRWFnLSOPKeXXN3OTPs8VZfs48xSp8ZOxWNRuqiunnC51J6pZRISZMi"
    b"peRKqYXpl5LSOhwLz4rUjGaIPYs91q8YF8x31js7tVsMnTGBzKYnhH/E55KgJCkR9ZN2yLPB28Ln95/1Vwr8E6gaXB5kwdxxXePG"
    b"xY2JmxXXI65+XOa468HpwVzBo4F6geP+kv6lvkRvXe9szw1N1UqrHZUp8krpsHhduEc/ko88xFw32ZEczZatXGZOo7LeOTYoujvy"
    b"bzhNeGDKkeT8yeuSsiadT+yemCuRhZ6GXoSSQ+kS2yXuTsyUtDapbPLr5C0po8LdIx2j3WIT9A3GXTMIz7DQ/YdlhdrZInwWc8u1"
    b"lUHqKG2kZ6i3pi/O/7e/aeBpoGJwSvBU8EbwenBvcEgwb/BEoGxgsz/mK+fr553iWa1tUlcpq+Qp0h9iL+En+hOpxMuzxmDwMXCF"
    b"z8yq5jxDMpboWfTHsaWxzrEOQGYb6PLNsVisnr5Kz4yp6DHXm3msq1YfmzqHnBbwqFtYFf6WTyTxdBstJuwXSoubxNTSSOmBVEAe"
    b"KR+Tdbm40hLefp2yD1P7pvIETHlJuascUpZBN7ZWasErPJbPwEWUk6m8VuoleaUdYkc4mFlCVmEjrUD3k0rkCC/O97Ef2Xo3tTvT"
    b"CWBW+zB14qz9Zlnzk7HQqGykN27pB/XN+jQcO/XbehqjqrHBcI0uZqLZ3RLsjXYVhzlb3Z6sGH/ND5D+NJ+QICyA4vks/SH7lfHK"
    b"V6WpOk+9rUbATipm3ll1mloMLrWNckeuIi+Q3og5xV+FmZgq93kS01gpt4EzxN5m3TSzmr8Ze/Wi+kJoxmvwLqWjavRlxIqYkVzw"
    b"M39Ff4jNRWccAle7xhVzjNXDLu+kc4PsA3vJb8LD7BCmioOln+QsSlTZrg7WfvAc9/RAT/TxvfSV8m/xv/BnD3QJ9A4sCywPzA4s"
    b"wXm9QMbAVf9ifwn/I98fvrB3qlf39IAaK6BNU28r6ZRW8p/SafElZkteWo78wjuyAe4EZ5K91Fpj7jQu6HdjejRdtEZkTHh/iiel"
    b"Q/KFpHrAY//ELIkPwIrrQ9tDd0ORUBMg8sekM0ltkjOip66Fr0fuRl/FUhuVzBHWOZu6rdhfPIHUECaJZyVHzqZW0X7yVPcW9jm+"
    b"I/5OgY+BdsHDweRg+rjscf64N8E1wSrBG4GqgVX+BF8OX2NvX89QbZw6Qukrd5caizWEsjQfKcSLsEpuWyDysGWZjc2jRmHjhN4W"
    b"GuxubFNsXmx+bEXsTCwUK6hP0P/RaxjHjOLmabOR9dwab2d0TjhdXAZENgAi/yRZMK1rCJeFBuJlsRKcarzcVz4np1daAHm3lYiS"
    b"X62qNlf7q91x9FIbqrXVzODDe8pMoDKTckoeLWeWD0rtpZfiYJEJgwSd9qMPyM/kAM/MZ7P3bkv3tJPNWWJTeyhiHWyK5nKjmPFO"
    b"X6C3glYUdAt948bywn/N0V/opY3tRnZzp1nPemUtsxs6Hvexu4wN4tWJl75DTw8Wy8C9LEO3/K00UveqWaATl2pXtVvaDe2QNkqr"
    b"pr1QB6gpiP6QbEklpV7ieGE93Qs3dZVdcO85L+w3lmZlNesZ0/TTsRyxydFYZH4kP6b0sfBiuNKd4SfhHJEhkY+RnlEe3Rnrppcx"
    b"vGYMU+4/O8lJgmb8geSktYXGYkupj9xaaafW17J5FO9Z73hfaf8ZfwfM5vLBDcGnwWzgwxZxPeNaxlWIyxT3KLg4WCP4JNA/kATd"
    b"+MhX3jfb+58nr6ejtlq9qCTImeSC4PAuQh86jczgS+H+tzpn7WvWIzMGtsmrN4kNBTN+DBcPT0l5k9ws+RqmdGLiqsT2iXkTUyXS"
    b"RH9iKTDjnkQlaUiSkjw3uU6KAod9MrIquip2UN9vvDdlO58zEJ76GjxMFqGd2E+aLK9VpqsztB6egl7dO9eXDz1EAx0CMwM7A8cC"
    b"awOTAtUCCf5ZcF+Tfa+8pb1jPfu096qi5lfqyr9Iw8Vpwjp6FTMwPW/Ixrv/OnmcueCbcVZ265TZ16xsCmbIeAd36hjpzBrmRPMU"
    b"tHcf67JV2l5jp3GmOcQd64bdYewT68Kf8hrkKMlKR6HKRYUZwj9CUOwizhHPiI7ol6pL7aRu0hxpmrRY2i4tkP6SVkhTpHlSX6mT"
    b"1FzKL2WTYuJt8bA4UWwjFoILPCtMEKrDSx+ifWlGeo0MJOnJGd4KWnw5K8GeuD3cIKZkbce2F9p1bcHeao2xqliqFTYvIMrj5h7z"
    b"nvnS1Kza1mCweHp7gP3aruWcd2q6p9yW7CHrxRmfRH6g62lB4YCQXdwoCojvbykq1ZZ/k8fJ6+Q/sXrJeWUir5fqSglg6pDQRThO"
    b"S9Ex5AEvyQewm25atzNcTLw9wnprNjX/MToaMX2d3kzPrCfHHsXuxZ7EorEceid9l+4zRhlhYyLU4lF4+8zOCzi/vqwajydvoV7n"
    b"CJ3FUpIuXZDHK2XVz+pMrZjnpKee96K3pG+dL9lXxz/1uzO1/akC6QO+gOt/5t/vn+Sv7td9f/nq+F56B3ijUD4foHIPqhnUbspB"
    b"2ZFKoMLrhFvUIelINf4L6+fOcVaAb26ZLwzZyKLXjA2JLon8F84Y7pVyOTlX8uak7EnHErskpk78FDoN5fh36N9QhsRfE48nlkg6"
    b"CG7UUq6nbA/PiEyPzo2t0i8bb81sdgtnunuXEVKPjhS2ik+lRNmvptJET5LnnHeCr6T/kr9O4HCABaoHOwd7BLsFSwfF4O5A3cA/"
    b"/hr+3T7mrYl5vVV7pIYVFSq3GPixmzCIbiAHeQLLxVq5x1DhIfZr+FXRmmM2N33I8hVjk7HXOGrcBC4LmL3MgybF++es3PZKW3Ym"
    b"O5YzyHXd7izKevN/eH9yhtSnh6kizBfuQUOuFq+CgfpKa6WYJMv1wZWj5D3yVvm8fFk+JV+St6D24+R2cgVM6bvSQqmxpEDxtBE9"
    b"4kqhnHCfNqYppDtJ4KP5KzYa7NjbDTu/OZY9Cp2zwapgvTRnmtVNYl411huTjIHGYGOo8T/jgPHKKGz2Nu+Yxa218NOr4GCuOD3c"
    b"1GwH68oVsgue2qJrhCriObGNdEuqIu+TU+TGyihllXJB2ascVuYorZQfldNyJ/kLkHpHrChOFp7QLFA3S/hBluLmdhtBwZ61AtYv"
    b"5i4jzhivE31GrDR8zLbo2Gh3zOc/ojuir6G0V8Z8+nK9uPHEWGC2tvLYHueD8697m52BezlMTwqHxK3SX/KfynC1sZbTk+jZ5G3n"
    b"s31z/ekD8wKJgabBecHLwWiQB9PGkbiE4MXgzGATuJgVgdyBff4C/iU+6mvm3ev5pJXXeqnLoCleSpmlHGJtoQPtRGby8WyTu9M5"
    b"Yv9nPUU1sxvV9FGxZfDS2SNdwtdSfkz5X3Km5HlJlZL+S5yPOV0usRh4sTLONiZ+Svwl6WRS9eR3yUNSaodNTOlL0XmxPfpyY7N5"
    b"yzpjc4ew3LwuaUgHCb3E36Ue8i9KKZVitgzwZPEu82b1jfNd86X1F/Y399f2l/On89/2LfEV9l31NvOe81T1LNGicApzlQ9yDrmP"
    b"dFT8KjQTZkDnNiGLeSE+lqVhm90cbooz2mmOefif/dY+Yp+3L9t3bMNO5dR0fnd2OiGnpDvCverGse5sN7NYcz6Hf8bE6Ut2k8ek"
    b"MK1Kp9LN9DR1aQqYpzgQ1UGoJ3QVOgu/CD2ElkJToZVQEcxXBpqwgCBC15j0X/qGnqRH6SY6jY6nbWkDWph6aBK5TNaRCaQByU0i"
    b"/ABfxOvwrPwlW8yGsExwiLvd/m4t13IeOmudYU5jp6jjQy8l2o/sZPupbdppncxOJ2egc8D54uRFzIfdjKwtO8fS8d7g8sxkBnlO"
    b"ctGZ9Bz1ILYhwl7hgfBMkMWIoAtfhVPCVqG3UEL4RJfQKvQxGUxMPotLfB7zsImu1x3lyM5UMOMadMRdc5xZznxjXDcmGyOMQUYL"
    b"Y7Yxwbhg2EYx8y/zjTnAemp1sV17slPVvesuZHV4jF8hQ6BphG8TQSolv5c3KtXAizO0eM92Tw7vCq/f18t3zhfvb+Kf7D/kv+z/"
    b"6P/kf+t/7T/m3+rv56/qN307fF18yd6/vJm9hz2lPMu0IlpfNUGppEySQ1KcNEBcAWYM0LykMyq73r3ovIa+yW3VMLsbc/U9sQ/R"
    b"tNFmkaXh/1IqpqxIVpMnJ6VJWgcu9CTeh25cEToaOgNPXSlxZKKV2A2yYk1y/ZQs4Zfhu5GT0aOxa/p9I2xmsEuiw+ew3fwjidCc"
    b"YmmpBDo6t5pDS9b2ekZ6Zd82X2b/n/7n6Kx6gV8CnQM1A3kD7/2r/XX893zdfbe99byrPS487Fz1rRJUusqLpEfQ5i2FwzREfiV7"
    b"eRA6I+oucLO6O5wBjuY8tLfYvewedg27kt3ErmoPtsfYm+xXtm03dUY5l+FSm7k73S9uIzabJbCyfBL047d/7biPiLQ5HQmkGcj6"
    b"H8IK4akQFnKLtcRO4ihxnrhG3CUeEg+IJ8Qt4jbxf7jWRywv5sVEPCcsFhoBq3fpDFqTfiUrSH3ygc/jpfhN9geLYwfdVsDgeqeJ"
    b"49q77GF2dtu1/rYWWrOtZlZPq7n1qzUOk/uM9cz6we5u77C9TnvntlMQUaZjc1kGPoanI6OJQ0bRJ7Q1MJhK7CnuEBPE7FIdqaPU"
    b"X+oBXVEe9bwvzhLLiXeFvsJHOoA+RxT7uY/3Y+fcH9yBzj07vz3Hss2O5hejg2Hri/Tyuqwfjm2LTYlNjq2J7YilxPLrk/UEvbPx"
    b"yZhk5rceWOvsNk4lNw1LZJ/4OXKB7hbWiEulUXJ/pbFaQCOe255Z3ka+r77/+fPDqeSDD30QzBFXNW4avPSSuLlxneNax4lw02OC"
    b"anBXIE9ghT+9/zffJW9GbyPPSu0sFG42pZTcXuopThHm0bVkN1j8qnvTeWMnQMdkMssb7cGMJ6JPIiUjA8KnU0qnjAYzTkr6MekW"
    b"ZnSDRDOUFHqNCe1JTJfYI/GvRClpTNLHpJnJWVJupMwJN4jkj9LYx9gb/Y7xj/nEemwnOB9dnZk8QmL0lXBX3CXNkH9S4tUTakvN"
    b"0Dp43nkqeSd4H3jfetP60vmCPu69h+7p6s2E/unueaeN1WRtgOpXOypfMINOSq2lbWJl8YRQRHiAmZhElpCiJJGv5215WR5lT8Ek"
    b"K9gmNo0tgGJbxI6xw+xflsxEXpRX492AvBX8GH8IbpSh7AqSCqTm979U7EbakHaYr/VJZ1IL12qRPKTM9782T01kohEbus3gLhhC"
    b"/P437GmJhxQmWUjp73973Z7UJp3w7V/IUPxKN6xGpBmp9v3vHiWSzJ/zw/wvPo535jX4t7/Fe8rOsKVsCuvEGrJyLAPLyCyXQ9Em"
    b"fX9Mz1JBazZgzdEt89kF9pk5rDJvyofz7fidj5jafty1PKLuTOqQLnDvZUgO3OUNX8kn8ArcZJdZF1aK3XLHuxXcq85Mp4Bz255n"
    b"F7U/WrutX6wSQOQZuLo/zSnmHHO4udXcbz42f7TqWOusmFUHkyW/s90p7+53O7B3bC4vQ+6QBTS38F6YDbWYLE2UKys3lYGqps3S"
    b"cnsWYMZN8n7wNsZM++zL7W/vn+Lf7T/lv+V/BFdzAR56LOae1//WN9FXw/fBO9Sbz7vMU9hzQIvX1qsRuP9r0LoDpa2Ye9Uwqw+S"
    b"u1zhNVkzd5mz3X5seawfzA7GBH1fLCGaM9otciDspLRJuZicJ/lgUrGka4kjErMlRkOnQrtCf4W2he6HYqE6iQvBjiOT7KS1yXVT"
    b"xPCt8MbIjOiI2ED9d2OMOdvaaB907rvvmMPTwM/kF3NL2WRN+aKcVCdpFT0vPGO9pneU76Evj3+wf7r/pP8I9rPd38tf329BFTf3"
    b"PfL28SZ42nsewzNuUlOpvZRbcmF5hpQiNhPPCPmE1TQtXQBsrEO177FxrAh8wxa3o1vODbgfnMfOKee4s9855Jx2bjr/OVEnk1vY"
    b"7QBHs9F97hpuWdYNDHQHKrIk787n83vAXUlUeRa5RN7B51SnXelizORH9AtlNK+QU6gtNBAaCu3Ahz/jvBSu+IUv9BbdQYfTNlBq"
    b"n8gxMoBUJTrfz0fwwvwz2w585GIf3PXuYEQluK+gIBY7I8GBHZyG3/8lWWdnirMakUadLG5rd4V7383BerF9TOHN+Foe5RXITPKA"
    b"eGg7OpEeQSRhqIpvf61TVlCEAFh5E/xYJvoBHPoDOcsr8aesMbvvtnBPOvWdPXZxe7eV0zpqljLvGD0Nxbio99fr62n0aMyIvYRK"
    b"/FH/Wd+g/6u3hNoub943O1oZoXimO63cXMzDX/EH5CjdLqwTp0jT5K7KL2o1TfU4nn3eMb56/vv+5YHMwRXB4nFD4z7FFYtvHb86"
    b"fm38vvi98TPjB8eXjv8ctzKuVNzpYK3gXnia3/2nfIqvqre/Z6l2RL2rvJajki5SURJcdLjJCJPcGPSEamUwyxll9QGx6dH9ERrJ"
    b"F56R8jK5bPLZpEJJ5xK7JZLE66GZoV6hNqGGoc6hkaHNoU+h4okLEmnSyCRv8nq4apZyKDw+8mu0QCyV7uj/GU/NG9Yx+7SzyV3B"
    b"FvBe0OGlBSr+J86RmsquPF8po+5UC2srtAStoWe855jnpSfFo3q5x/T8B4+22NPWU8DzVFuiNdS+qJvUyupHKPXcyj9yPzmbfAHz"
    b"Kbd0EbOpmmgIN4VxQkchvxCjr+l2upKORtWa0RI0P01FRRomL8kTchweehX5E7quKXilABGJw88CLzN5G14f8z7MrrPVbCI4qSyL"
    b"Z2H3kXvE3ebOcCe7w9zf3IFuJ3cAtNzI7391c9p9DRznZPVYH7YS/PUV6rghH8n38ttgzsK4w2Sw9kXyH0khWWhWWpHWo3VoJ8TU"
    b"GpHVB6tXgtLMTf3UIp/JPcS2HWj7g/wGRi0D1jZ5Cr/CT/LNfDzm9C+8Kqa+yC32mO1hm9kg1oqVZ46b4O5xJ7rd3fSu7ZwAtts4"
    b"gvPUXm03A/r+tfZbo61SVlbrgXnIXGR2NjuYJc3CZiEzk1nGLAu/N8ZcYj4xA1ZTazs4sb19xS7h7HWKgxMbsEesP09NtpIW1KTL"
    b"hUZQBUuk6vILebKSQz2iNtKeaZ097z1dvDe9NXyrfIaviX8WuFAIFAn8GugaGBsYHfg9MCDwU6BMQAnc9a/0N/Vr/n2+lr4QeDTg"
    b"netJ7RkPR9BWPQLf9Zt8TlKlOuJS4RSVaRnShq9me9zPTryT3+5ljTD3GM90M1Yr1iO6PZISLhT+X8rz5DrJJ5LyJZ1MrA8/vS7U"
    b"MlQkpIXCCW6CFCoc6hpaFaKJHRP/SeyVlJi0OblFSqpwcvhwZFd0aWwqHM2f5lprh73DuedeY294EnlLDeGF+FA6J89TBqmFtNfa"
    b"Yk9+73FvZd8mnwauX+C/6U/w635/INn/yn/eP97/q5/6d/o6+957Z3hTYzc/euZrPm26GlX6Ku/kJvJVqba0BxN8H1zIVVqZ/keG"
    b"EI6ZXI9zzOpvf9f4Elme7jZyK0LPR5330I83nCPgzPOo40PnifPZ8bhp3EruL+4Qd617zP0I11OG9Waz2FlgLQ1vxPuBo65jxufC"
    b"fO8K7CyFZ7lHPhCZUpoZjPjt787S0tRUoBHymlwjh8l8Mg7KtgzJSj7x+3wb5mgfTNJcXOCv2W22H4piHjTFGDYMfD6MTWVzoC0O"
    b"sZPsGTOZl5fjjflAvoTvxHcToCzykFKkHmmF9U1XNIKq+JHEkY94fyFUiMqvYfIXYifQNXHuDKeac85uaXNrmJXPOmg2MEXzf0Zz"
    b"QzROfP8vndX1nHpmPbueT2+hD9YP6q5ezzhj5DC3mRWtS9ZYO5cD9naHsGa8AAlQnf4n3BFPSDvkZcpEtTe4Izem2WXfFH/NwNfA"
    b"jGC+uHVx2eNnxf8bXyZVl1RzUu1NtSXVvlT/w3n5VE/j58Xnj98QVyJubjAUaBKY5L/hM7wZvLU8jbUuaj+lh9xX6iK2FprQ6qQM"
    b"z8t+dNM4qe1UVryZ0yis14v1ic6JXAmTcMOU9clu0uCkD4mDE72Ju0PdQ/lDTsLzhHsJdxPeJ2ihUqHRob9DORPnJbLEBUlpkg8n"
    b"d0uRw/fDUyMtooVjSbEX+i5jvjnKamhXh3NIcR+wpXw0qUA5PS/0FnNJp6XW8le5r5KgtFHPqVm1QdohLUUr4Gng+cMz2bPQs9kz"
    b"z7MGZ309vT2FPDk9Ee2UtlvrotXS0mg31YNqb7WqGlSvK1uUHkp5RVJuyOvkrnJ52ZWuSculNlJx6Yt4RJwolhE90JmjhRrCB7qf"
    b"dqReeht+Og95xIeBcb5N9rLsoTvfrex+cXY7rZ2c8OZr7BF2GTuzHbGuYa23NltbraXWOeuk9dwK2OntbvZ0+6Sd2qnirHBew2/M"
    b"cx+4ldj/2EfWFOpNgoLcRfxgwN00EfNgqrBbMIS8YiNxsrhIPC7eFR+Ln8UP4nvxhXgHMa7D9eZwREy4ImzA/P/27yMn0ZY0AezU"
    b"Ee78MP+Zx8CJldlXcHVR964z1MnmHLH72F77gNXLUqxL5iAzr5lgLDf6GUWMmP5AX63/qffA/K0Lr1JNrwUE9tfn6Mf113p+o5Ox"
    b"01DNZuYVM5e1xMpm/wn0bXBKuf+6HVlavoP/TFS6grYTLOEvsaOUJO2R6yjvlEVqau2sVtNzydPBe9Lb0LfX54FGPO7PHOgWmBZ4"
    b"FkgMpAlWD5YItgjWx2O5oBD8GjgXGBVoEXD8B/w9/Aa4poDvmLeO94CnsmeVpmq/q6eUvEp/eT+4sbQ4WthHn0CRl+dd2Gx3p3PH"
    b"1q30VjmzhzEJqvFdVI02jUwNX0zJkdI1+WZS2aSViYUSt4dqh1ISliX8llA2IS7Bl6AkpEuoldAnYX9CINQx9D7UNfFT4qakssk8"
    b"+W7KtPD0SNtog1hbvYzxq/mr1dKe4Axw/8fW8IXkCF2LvW6QhsvDlGpqQHulTfVU877w/gbe7+G/5i8aGBzYHXgbsAJpg5mCniAJ"
    b"PgjsCPwBv/0BOcjnv+ir63vhbe195PnVc0arAj2ZRp2svJXby6eBww2iJs4SItBxBhkIPTKN5+CnoaQkth7+Np17wVmGuVbY8Tuv"
    b"7Lv2EXs7fPhauNnd9ln7kf3ZjnMKOc2dsc5fYE0PGHMIdOhzNyNrCu9xloVZAd6Rz+Jn4ClSk8pwLpPIcnDhLfIYkzlCXOKlDirK"
    b"SAIJ49pNco6sJyvh23+D4ylP8pMMJMpD/AE/zY8AvYv5NHTG73BZnXh7+JXmUA71eV1e5fuE/vb/8sjG04NRDfaSXWUHwaHD4H9+"
    b"ZCYUwzy3JTj9iTPfaeRIzlG7Lxz7HWuCVdF6a24w25k+84Wx0OhmVDW4bui39bP6DX0/FOJ7XTAaGj2Mv42g2cl8CU68bjW3n9r/"
    b"c7K7b9zlrBEvDIb/m64UfhNbSLlkGXg8pC7RunvKeB3vSd9wf57A7UDPoB0cGxeL6x5/ND5NqgapxqTaDF48mWpjqkmpeqZKk+rf"
    b"+HHxSvxfcf64icHPgUKBaf4Tvi/enN4ynl+1vmp/ZYI8RholjhUG0AGkF2/POrttnA6Yz/3MycYK/VjsbTR1tElkQfhVSsWUTclp"
    b"k/+XlDtpX2JnOOjr8C0jQ/1CA0OdQnNCa0PXQ1kxt/cl+pP6JMWSOiWHk6empA6fC7eJxEXPRAfGSqMPdxg9zBxWgrXG7old3nMX"
    b"s/I8kS8jpegL2lcg4gLRJy2UNHmI/EGupaxSbKWqOlO9q3K1htZHm6ed0+5qUc3vSeUp4SnoKeOp5imCvsrn+QHL1EztqXZaO6xN"
    b"1oZqjbVsmle7pm5WR6ll1LTqVWjMtgpRrsuj5Jzye2msVEx6JvYRc4sHwT4ulGU+ehZe2OKjeBZ+kdX5/vdoZTDFp6GuBMr/T7uS"
    b"ncr+bB0HL86wxljDrUHWKOv/WLoGMEeWtltVjXhmNatvbdu+a9u2dde27d27d23btnXXtjkZJJ3urqr/JM+/9XSS6WST7rfOe9BB"
    b"TzNXmkfMJyY3C1qdrJXWKyu13Qt+y7Jb8tVc8MZig3ACUfuQvhuSnXCFf9EJ9Dx1sPxsCFvITrFv7DtLqyRT0iv5FV1Jp/xmj9hN"
    b"cPdQ+N5v9AZtQUvSp2QolPisnCgzyU1IM2/5LCSvXXZX+5s1xypmnTdHmsnMs6GhcIFhtDU1shlfgpfAiGPBgS2DTYPNgq2D/cGP"
    b"W4BAGSxljDQuGElDPUNXQ3nMFabLmmBJa5zt5It5RniZGkgqo0lSepDWRnaerKRWj6jVtedaXz0O2iwc45yWsyfyZgX3Rjfx1PVs"
    b"9Lz3ZPa28071HvL+5/3u5V7d5/IpPg5ndcu70zva29qb0vvGs95T2+Pz7HQ3dluuKa5crr3OUs7LjjKOs3phfbOWElj8qlRTdjGV"
    b"daQniU56yN2CihZ8qZ1olbRmme9CWUMzjPvBAsGFQGbLxCMJ+RI2xaeM3xaXM+6Cv4Pfij0W2y22QKz4c+/PmT9b/mz+swfX7/64"
    b"Y6vGTo19GlvEv8zviZsc54tfFV884WnCxMRSge+B/cFBRtlQCsziMWuO3YZXEx44sCtkBu3B8ig/lCNqDy29fkfv53A5Nzizu7a5"
    b"srqnuuPc1TxzPK88qreUt4O3GzhxrHegd4C3ojeb1/Ic8szwlICTXOsu4n7tGupirg3OjM6DjrKOI3pd/bRWS7unVlFfR77LMAyZ"
    b"dzHSxB7SER5ujayDnHsEWTqbMOAnF/Fe8JMFuZeHbBOO6Zv9y/5gE67wZEjApeDExvK5/BxybhAZs7joLiaLdeI2mMohs8ky4Mn+"
    b"cppcJXfI0/I6XN4L+UF+lF/kD8zxJ/lc3sM4AhbcIudj9JM9ZAtZAr4wudRlSDwU9+EhV4vFYgCeubYoIrKDwxOgm2f4Lj6bD+at"
    b"sXUZubRf2+eQu0fZLewiYPUv1nlrhTXYqmNltqj1CKllkdkDmSSfGWXK0Gsk40vIL0dC+0LHQudC90OfQxT31TSnmkfN32YNa7z1"
    b"1ipnz7ejeD/+nffB3oyQllxEctNztDuTbKdSS41T12hl9N/6dEdB5wNnN5fHvdidy7PXk9e7zxvjm+375CsTtTjqclR0dKHoRtFD"
    b"ontHj4vuFF01umD0+6iTUd2itKjjvgK+G94q3k2enJ4+7puuzK76zm2OO7rQKmn11GnKJnYEjiQgM8jKoimfZW+07sN5FAqNMPYE"
    b"rUD9wNpEPbFPwvv4dvFf4obFJYs75+/hL+qPjb0Yuy92Uuy82Amx02L3xO6N9cfG+Gv71/nv+MvFTY/7HNc+fl98hYTNCVkS9yZm"
    b"CJwIlAheCTY3XhkjQ6HQKjODdcCqa5+3+/E3fKDQZR+ZnIwgNpkOlhzG/mNVldOKT52pvlQramu0X1odfZH+Tc/jGIoM98dR2tnO"
    b"udF5wxnrzAuG7Oca5Vrg2u/a6rqN7H3FdR23Trqmw2P2dOUDe75wXnTOcZZxZnEeBdOWcjzUtyCLf9UmaT4gtLKaqMyAlzzLirEn"
    b"dCCNI2tJDnJB9gQyNgINX/l63oBz5JyRdjU7tf3UumAtsYZb/az6SKu1rNpWS6uzNcpaaB2x7lvULmA3B0YugGeqI3Pf4Ravjexz"
    b"SaSUleUieUnashK0fFPklyFikHNq06rwhD1x3ZFWoPlpRvqDPIGOD4CGxyNHd5M55W0xSuQR5/B8Ot9nN4GfWAHM3UEmcZhXQ+1D"
    b"KUN3jRFGDYMYt4Lrg4PBhGWCeYPpglmRToohmXQNrgteDopgI2Oy8d2oiPScwhxg/jEHWB+skbZtz+TZ0QENkY4mkhz0Am0LnVqq"
    b"FFNvqu21gDZGT+JY6EjqXOaUzvGu965q7r3ugLuFZ4XnmSejt6p3oneV96T3ufeVNwG8+N371nvJe8w7y9sPPKF5X3jmepp5XJ4j"
    b"7v5ul/uYq7Hru3OWM4lzp6MweKKKfhw4PKEWUHcpaZW5jLGe9DmpTrbIdHKseM9bQAEy2zOtz2YXcH+x0DbDZywMysC4AAuMT4xK"
    b"XAF2vBTfNd4RfziuV1y6uO/+bf4J/vb+IsBoSn9af15/Vn8Lf29w4gs/i+sQtyWOx/WOvxZfLeF4QvnEy4nNAr8DE4OFjMvGaKjE"
    b"TfMfqzjqcYK3hmrfk0tIC/qZnmMNFVM5rBbQvmr9db++wJHgGO386qzhOuTirqbuJe47bpcnl6eJp4dnsGeyZyguO3oqot/i3NfR"
    b"r/XcKd3nXWOQdq47JyDlnHK0d3zXVwKDF7Wu2m91VeT7kUOBwXOsLfOyc0BDfvqSbCDdSU4igJl1cphsJMvKGKTTP+K1eAY8XRNn"
    b"xUlxASn3irgKLnwqnojP4rv4LYQwhCa9kuLxLqnhMhE8GRKvRELk/50R84DsvqKzaCnSIenGowfvR35PojtvyCtwB3fyh+jNHfYY"
    b"YL62XQ7ZSbEN6551y9pm/WvNtbpZA6xqVkXolc/KAD/vh9+5HtYWcOBec6m51pxhTgfPDTXHmoOB0uEY4/D3POjwbrDfffOrKc08"
    b"VnlrkPWPddZy2LntofYh+7fdAEnoG68iloITOsr7sjzZQ/LQf2kWtoxlVjYpmdVjan7tIvjgmt7Z8djR3fnF2d711dXYfd9dFhqd"
    b"1NvZe9Ub7Wvl2+C75/NG5Y2qH9U1qk/UsKjOUW2iSkclifrhW+vr7UvhO+zt5P3oGe0Jufu6v7qqQ6cdztaOHfpPrbQ2QN2nfGcx"
    b"rCUdRw7L3yJatOQT7eOWZuU3p4ZuAIOjgmcC+QOrE+2EBQkU3rFo/Mm4Ucgwz/37/X39zf0l/OmAvBh/bn95f1P/JP92/wd/xriu"
    b"cfviaHzb+EPxmRImJvxJ6J54O7FJ4FKgYvBasKRxxagUOh+qZ541G1lXrRr2PbsMv85Lij2iqFwoU5KxYIwO9BDNzWawD6y+sloR"
    b"cM1bVBu+ZaX2UsunD9B366aewzHAsdlxx5HKWdjZw7nUud35EQk8mauoq5irpau1q6NroKsT0nc7Vx1XVVd2OM1Y5y3nDucIZ31n"
    b"Gucrx05HZ0cWxwd9jl5Pt8G+HTQTr9JO/aZsUWoqr9g6+LoXdAnNTL+QOaQQseQ/sg304yY0uZ3IAld5ga+FYjfglaCaOqf8A9L0"
    b"m8jx9Ef2c9tvf7YVHsWTQlWL4VF9gbvFwN96fpUf4y/5O/4UrvI9j+cGf4LLG/w8tH8GHtMRab4I/2y/sDfa3eyGtm09RaJqZhWy"
    b"3pg7zb/NnGYwdDA0KlQVRvmxsdkYYtQychgcOeQm8sj+4KrgxuC24A6kk8dBauQ26hlL4RGjwaCbQj6zs3nHLGttt3KDv/PwHby4"
    b"uCEayHg5gaShp2hNFsumKunUM2odOPdhuupYhAr/60ztWuxS3EPcT92lwIjvPaW8I5GLA1DnGr5uviG+pb75vmUYY3xDfc18BX1R"
    b"vhfejd7+SJdvPKs9ZT2x7qXubO5nrlauOOdCp3BscqRxLNHz6zO1dNo8NahMVZ6zjuwWLUAPEQcyZqyoLx7z3HwLtGgIfEcH81mo"
    b"beic0cC4FqwafBJoGviaODbRk7gnoUFCbPyG+IbxevytuJlxLeMKxAn/D+jzSf9p/z7/Bf9d/1u/Oy57XNu4hXFX49LEt4o/GB+d"
    b"0D3hRUKFxEOJRQJbkGcOB/8yHhkdQyK0wCxg3bS62F7MbTXxSQyXOch+Uo/+pn1ZMmWJEqPuU1Npa7XU+jDd0Os79kAxmjj3OH85"
    b"cwNrC1wXXR9d0pXencNdzF3WXdRdyJ3V7YFHfu467Frp6uoq74p23QZWOzlzOQOOdY7hjjyO9/ohvYWeR3+nLdH6acmRabZHvoEc"
    b"q1xWlilNldKKYA/ZQTaBdWXlWRpknBf0NN1Ip9JetBktBi110M/kMTlEVpHJpAOpTbKT8O9gn5MbwKhNZA7JxQOxFupaXiQX74DA"
    b"cchDTv7Inm33tdPbv5HU/7aag+VeIAH1MRuZqcyvoRuheaEhoVqh7CFv6JNxzzhgrDVmAWv9jJZGE6OuUcmoZlTEqAn0NTI6GV2N"
    b"obh/AR531nhgWIYSKhSqHeoYWhHaGnoZ0swsZk9zErrehCv621oDV1jQ7mSfQI/UAgoTeD1oswaH+0QWRLqKosOppK3YW9YaHqkl"
    b"+LCidk3LoV+BO9rmKOmc68zhmuGKd41xX3bX8GzwxHm6edd7hbcqEHjV99OXNapaVIeocVHjoxZETYsaEdU/qnJUjqgE32HfJF8e"
    b"3yvvNG8q7wlPec95dy33PmjWQucPRwvHOt3Q6miz1DdKGqUd20AfkUykqVwsnsCzt7KXo/8KmUND99FtU4O/A40D1xIrJp5JqJnw"
    b"JL5/fDJwY6+4/HHfgLyl/l7+Tv4a/qr+hv46/r/94/2b/M/9IX+NuJFxZ+JSxTeJPxPvSeiJ3JI3cWuiIzA4EBtoFLwXrGDsM/Kg"
    b"YslQKdPshQzawD5qF+YLuCr6i5uiqlwmNdKDHCMF6VD6kpZl49CvhZTZylclqzpLvaWm0QZquzShVddnIOekcNRzLEDq5o5azoFI"
    b"PB+dCc4yrmau/q6drk2uJ1CUT67kbtuVzB2Dyyj3d6D3P6Si1a7ertquLK5vzvPI4PWc0c7bjrmOqg6h79V76jH6ZWTv9NoDdZSa"
    b"VX2sjFDyKo/ZRFaYvaIL4e4CZCtpS/5HbiKF1IGW3xfzRSuRVXznx5F2W6KrVf4fkvUMu41d3Y6xTeu1tdfaaA212lhVrVSW13pn"
    b"XoHCTjKHmbXMAmYK81PoSWhLaGaof6hMKFfINB4aJ4wZQGI1I50hwXKHg0uDf8MPlgimDirBb4GHgauB/YHdgY2BVYHNgTW4fSZw"
    b"KxAXYMibbYITgxeDwWA5Y6bxn5EvNCX0JdTAPGUWtraAE7fZRcDC9dD5o6BFB0kTmkCXsXLKc2WymhWK3Evn+jpHMedlZ1uk5r7u"
    b"H+4uSI7VwYVJfX19p3x6VD2g7lTUiygZlSU6Y3T56ALROaNzRCdE/Y46FjUjqkuUK+qtb6qvmO+3d4i3gPeQp4bnq7uJOwgX/9H5"
    b"t/OOo43jnF5Q36YxbYL6TKmhHGQeNo0+IzXIQemWU8QrXpefstMBjcQaZP5Ahz032hgvgq2ByAEBNbAuMXfiy4RBCemBymHxNeJD"
    b"cafilsc1iasUlyou6E/wP/G/gkt86Y/307hMWNs7blncnTh3fJX4ZfGP4wsmzEx4lFA7cW1iVGBi4F2gV/C/YEPUu3Locai2+cBs"
    b"bz20BkDZBnIiBiNdT5UKWUwonUk1Noglsg7KHaWqui7yjeHLWh59uH5DT+9oDbX94MiAPDPRedr5ykmQV0q42oIxB7nmuCa45rtm"
    b"u8a7piLjdHU1dZVx5XJ5odYPnEedC1CT+s7McC2PHAcccxwtHRUcDqj2GX263l8vpifVf2n7tdVaZ60cEPlKvaYuUDurVVVV/ajs"
    b"V0YrzZSUyjd2iA1n1ZkKfVlAa9FoepWMI3+RH3IbMjWTF5GHU4rb0Ods/Irdx85pn7KGWZmsC+YEM6P5NDQnVDpkGNuNPkZ241tw"
    b"T3BAsHrQFfwQOB6YFRgRqBUoFcgW0AOuwJ/E34n+xE+JocRgohpIG8geqBRoFRgSWIJc+CKgIaO0Di4Jng0mBksYXYydxkcjW2hg"
    b"aBdU5y9k6vdmPmseqlvaXmR/tFvxjTylGIPU3gp5PzuSUpBMox9pJzBiZeW+UkY9rJbW1mm59GW6zzHD4Xf0Qb2quPagi0fBJRbx"
    b"zPY88uSDAu/3Jnqz+Nr6pvk2+m77nvl++ITvj8/wffbd8J31zfT18pX2xSPL9PZm9d73dPPEeP6Fap2Dj7rsLODc6sjoGK7HabW0"
    b"7WoKtY1yiaVkXegNEkV6yyvCK4bya1CQudYrs7Z5EgltteExJgdTBWcHcgfOJDZO1BLXJ7RPiEl4GL81vm980/g88Snjk8YnxHnj"
    b"FVyXxBgaPz/+WDxNyJgwJGFXwi9gbyJqWCgwKfA1UCj4bzA2WBuaooZ6hy6EMpvj4b9LWtOtb6jTPPubXZDP4Q95ZjFcHBZuWU8u"
    b"kW9lJtKH7CAJpAgdBp1MpNXZaHaReZRySHsXlSi1pTpZfa96tSbaRu2SlgX+b6b+TA/oNRyDHRscXxyKs4Kzm3OG87DzrjPe6XZl"
    b"g6OsikTX1NUZ3NnS1dBV2lXKlczFXJ+dx51bnX2cdZ3p4ShPO/o7KjlUxyFgswBqtlNrqqXVToMlc6sPlAVKIeUnW8L+Yib9h7ai"
    b"Ap6/N/GS25HPQ3wVS0Qz4RCX+Hhektv2AXu0XQLMeMUaZzW1kluvzUPmQLOBmdL8EroUmhXqF6qAahvGdWMvmLAP9DifkcJICH4A"
    b"t+0PrgXHTQh2CLYKNgbqqgRzBXMGi4AbC+NWPvxdHizYNTgquCK4M/go+CuYwahuDESVnxpZwSerQmaomLnE/AmfuM9S7SHo9zrI"
    b"+BWQwirK47IquUoawoN0g/aMURzqIjWjtkErqB/QCztOOHI7dzozuCYiMzZxH3On9rTxHPMEPMW8g5Gfb3l/eJ2+tL6cvgK+7Bgu"
    b"X8D7wrvNO89bB3r83jPd09QTcG9wt3S/dy1z5XQddXZwPnEMcUh9tJ5CnwtvtFqNUVcq6ZUV8EFraXK6Fgq9RBaQa0RucY7n4w/s"
    b"ZvZT4MM2N5tVzOuhaaGY0BljuBFtPApODpYMqsFjgZmBZoH0AZ54N3Fv4vLEUYm9EtsCqfWwNE5slzgIa/5NPJJ4K5Gih2sHJgc2"
    b"BH4G0gUbBDfDUac3ehsrDQJGmAzdSIu8d8f0WaOt41a0PcjeZafgXfh2nkw0ETvhZqrKrfK3LEOWkQckH9B4jCZhddm/7D3LpAxA"
    b"zvijFFS7qnvVl+r/tObaOO0CPHcqva7eS1+tn9Zf67ojg6O8ozlwNd6xzLHRscNx3nHScdNxD9dPHWdxeRke8jA8+iRwQBMk7nKO"
    b"tI704MfXYMj5wHVjvZyeRv+iPdD+hWY3AB5N9aS6RO2gZlYtZZ8yQamqBNlN8GNJ4HIN7U6T0DPIYGnJfTleppePxVCRVtzhXXlq"
    b"ftZuZae091htI9/k7wcsXgjNgMuLNY4YPY1SBjHOAXk9ghWCOYL+wMfA9cD2wK7AvMDswILAuMDCwOLA0sChwNHAPbgdHsgdrBbs"
    b"AgQeCn4KpoaPHAUkvzUyh1qHFobewAG1Mbear4HAEeiBzHYH+5Lt4934ZZ408guBBeGEfsrW5DhJB+35TpuzMywHesxQuqiX1WLa"
    b"Ui2kddePIyWOdzxwlHGOd75w5nH1cZ1yBV2l3YPcm90P3cSTw/OXp7NngGeyZ45nlme+Z6xnqKeTp5InV+QTgNvcPdyF3Qmu9a4e"
    b"LofrmLO3Mx5+v5jjrj5Yf68t0nRtLjp7jpJbWYMUvY1G0RUkFZkmY+QsoYulcNgr7Mz2Gqucdc5saQaAxSKh/4zRRn7jdXA5tOB/"
    b"0JDTgemB/oEGSNkFA0kDMYF0AW+gSKBooEZgOMahwPNAfKAq+nh18G1QBjsY043bRsZQdSS556F0Zn9zrfkbutHH2g1GzIEqrbVv"
    b"IruU4b2BwvNcEzlEPTFHLBWvRJxIKZvJFnKjPCCfy/D5bPpEfgX5C4kj1Wgbuojepz9pKdaJLWfPmQ7nMUk5ophAaB91t/pKzaw1"
    b"0+ZqtzRDK653hupc0GP1NFDjPo6xjt1A5SNHouOPI7XT50znzO5M4szp1HHbcLx0vIJjX+8Y4ajvKOuw9DdI7wPBuQ79PlJ3fS0T"
    b"fOQstbGaqJxSeiiplftsKCvC7mNWC9GnZB6yzEc5UeaVb5FfiomnfCqyyzt7oV3VDiDFdrVirGfmPGSWlOZdJI32oRIhLXTTOGSM"
    b"NNoBVckNzfgcvBG8gET8L8b44Gxw46jgnODY4GK4xrVgy1PgwDdBFcpVBPmyg/GvscF4btBQplCn0PjQ2dDvUA6zm7na/GJmtgZa"
    b"Ry1qt7S32Lbdju/hKcRIcUvUkatlMjKDvCAD6Hn6FzvOUiqbFUuZpH5Vm2p3tez6ZuhLN/RrjHOs86QzvauFa4PrgyuJu5l7gHur"
    b"+7T7mTvg9ruTeLhbuk2k7IfuLe6Z7i7uPG7mPuOa5qrmCjiPwD95nWeRU5yOrXoZOJ+hYMQTalH1K9gkxPay/7HbtD19hRzoJSdl"
    b"S/lCrED3XuP9uMLPgBk99jGri5XFuouK1Ted5qPQP6Eu4DI19ME4CV6baHRGuitnlIaaZDcKGlmNskYJox7SXS9jCe6/ZrwxpFEw"
    b"VC00NrQydDuUEMpqNjVHRY51pbCKWz2Q645b3Epq17cH2Mvtu/ZLOzNYuROfzlfwp/wljxH5RG0xQswQJ8QdYQKTZWQnOVbukVdl"
    b"SKYl1chgspTcIX9IDtqEjqcn4Xn+xxoi+55gf1gGpa0yS7kAVGZTu6lz0OkJ0J5m2nBtt3Zbs7T0eiXkk9H6NiTqp/pXPaTHOJI7"
    b"SjhyQZerOEqCIQs6qjsKOzJhDdcZkvd1/bC+UB+qN4RiC+21thksWVNzas/VxWpraM0DZYbyl5LA1rDWLJ7upfVpHNkU+aX5kTKr"
    b"vCxaCrdYwmvw5/Yk+Maz1kjLad0we5upzReh4UjPAeOYMQ04TGN8REpZHuwfrB+sFEwbjIGDjAs4gj8DBLcUqHKOYF3w4bDgpuCR"
    b"4Neg0ygGjzjXuGTEIqO0xTw9DHnMJuYMVDq51dhab723CthjwIopeC9+gLtFZ7FDxMgO0OdspCt5Cb2ZRG1amh1gbqUdHGNadYr6"
    b"Asy4QPuolUU6fKdncoyEdgQclZ09nMecj5xeV1lXXdd0jN2uE2DKB67zrhuu4/hrBfS8k6u8K6PrrfMqEFzfmRY4XI2KWvp+6FVy"
    b"fZPWRrPVf9SaKpIS9Pkoa8X8dAbNT0+RDoTLObI8/OIQkUxsh0L67T1AiGkdsVpaGa3b5kKzoRljvg5tC00K1QwVQwf/NJ4BkUeN"
    b"jcZW4x9jl7HNOGw8Bv5cIT1UINQZLuVI6HTICBU1q5r/mvtNv5nXqmstt05a8VYeu7E92z5kv7ejeFFgbwzfwS/yV9wlnKK0qCjq"
    b"wy12FYvBi/+IA2KzuAJf8xDjLTgy/Eu4qswli8myspfsAj+5SV6Q36VKCpEmZArZTD4SjVaio+kqGkd9QMUSdoGlUkoqc5QTwGV5"
    b"4PKw+lRNB2YbqR3VnmlevbDeRh+jr9NP6g/1BN3S00LVczlKOQpgKezI4cjsSOqw9d/6f/pBfS1STVM9rx7QHmsrtJ5acc2vnlZH"
    b"q8VUQ9mpdFYyKJeRtAuwB3Q+zU1fk5kkG3krh2KLH4g+Iq84w4fxrPyCPdPOYn+0ViBPJ7NOmjORo53m29C60LBQnVDGkA2lPWZs"
    b"MRbC9Y0wmhqtjBZGJaM98nRboyu6fboxBhy4xzhrfDL+GDGoeN1Qn9AiZJVnIQ7X09rsYe4y75nxZjWrgbXVuoOeb273t6/bhJfj"
    b"i/ktnk70E4eEQ3aWm2UUaUMOkPS0E31Ms7Bp7Bsro+xQ/EpX6IpP66tt1zIAQ7v1oJ4TCW+bI96Rz1ndOde5xnnB+dP53ZnEldyV"
    b"1JXd5XSFf/3urfOhc51zkbOls5jT5TwHZakPz/MEnrseqrYPOIzWDqs91STqQaWvIthJ1hLO5gitShldhxRty39lY2mKXaKtSCIu"
    b"8JGR3+LcY3eyC9jfrAPWZKuildX6aF6Atg40O5glzGym1zRDv0LvQq8jv4T4LPQBmhAKucxMZiGzHpzQaHOfedr8bsbgf/ayBlt7"
    b"rPvWbyuvXcYeBSSesd/YIbsIXmcIXm0Vv8TPcpPH81TwrIVEQ+CxP+ZuGvC4QOwX68QlIPKG+C3eCUVGwU2UluVk28iZh7bIk/IV"
    b"eDI9KU+6kDlQ73dERH6Pdjw9S9/AXdZivdkWdo/ZrJjSGpg8qnxQkqgl1U7o/gPqXfBlWi2/1krro01H+jkAbXqq+bWA5kIPJ9Hz"
    b"4DKXnlWP1rPrXNP0oHZfe6ntQr6eAZatqaXUfqk3kbC7qUXUOOW0MlEppqjKbtad5WMn6RKajT6E9iQhcXKwzCA/iBbYvxPo92x8"
    b"n/03cuIFVLc4ansYdc2Hmu4J/RtqHCoJj/7eeG3sQ8ZebkwBX44yJhiTjJnGUvT/IeOG8crgRgooe8vQEDif06HEUBL0/VCo2Gvz"
    b"m1nM6mhNtJ5aH6yydnt7CaodtJvyQfwkqpwDbnGTiBcFZF95VMbKcmQUuUR02oAupU9oDtaZ7WMJrDg465Siq9XUSeoVlatltb+1"
    b"bdoLLQoq211fgGTzDG4nqSM7/HVdRzNHd0cHx0BHJ4x20JWq6OAYR4L+Qj8Gzz1ML6ln019qx1DhMlpW7ZK6FonTo76Cn6qpcLaf"
    b"dWFZ2Hk6hRahd8kWkhPsuEpWkKnkQuiiA4icx9NwnS+zewGRj6yLVnerlpXaemreNudCazubJc3SZjozCTSGmUnNNGZyrCkHBh1l"
    b"TjAPmP/BEea0yiOTrEZfanZ2u489zb5s/7FT82ZwAjuBv3ieWhQR7YC7pWKDOBf5jEEsquSSQqSWLplMppYUM2gLn9RlvAifw8QW"
    b"f/CYAC6JTMB6t0wrC8v8sh18xni5Fn3+FSMzOqwd2U72E4tkpDWBic00CAWvD548wEIsu9ICLv2U8lvJpNZGMt6kXlcDanKtPPLP"
    b"CG2xtlW7ot3QvmvfoOaabmrRWIieoH3WnmuXtYNQrylaQ60CfM8b9ZY6Dukpu/pZOaf0VsoriWwH+5tlZM/oQlqOBslW0pj4yCHZ"
    b"W/5PXhMTRUHxma/kzbkr8n2UinYy+wYYso+V14q2ngCTy8w+YLYSZk7UlplG6Bt6/nnoB7r+W/g79KHkJjWzmkXMwmYns7k5GbOx"
    b"0byC/GebCp4j/NuO462l1mn0Prdi7EqR7y/st2/bGs/MW/IpfDf/jfTSUMwSh1HDYkDkJflZViYTwI6ZaUm6DR2cls1i61lypLKZ"
    b"yhvFi5y2VH2murUm2jDs/VfN1mrodfTx+r/6Rv2ufgsq/g3jB7zOc6jLWX0nnPkgvQPcTCpklLPaPPRtSe0dOn8Y6p1SPa5sVUor"
    b"aZXrbBJrDEdzj/YFM/4h+5AFMoAbV8ohMrf8Jo6Cv/8SFn/AZ/M+PA8X6Kpl9iK7rl3aTmt/tz7D5+2D3s6E4xlk9bY6Y+kIdzzA"
    b"GmdNs1bCmR+zXmJE22nsEnYXu4e9wd5rP4Rr9vJKvAEfjJnYwp/wL9zieUU20Uh0goNZIiZBj/cgO98QZ8V98UA8F0/Fe4yXQOdT"
    b"6PNX8VHwCDPGCyqjJZN5ZEpodSVZTQ6CXi+DE98n34Alk0XOrdifTCS7yD3yk6Sm5WlLqOZW7DNjyYDI7qj1KXaLUdSjtNJVGaas"
    b"hYbfRYbU1KxqJXiZ/uoQZJO16gb1jHpcva3eVx+o79Qn6lso/EP8fVE9qm5RV6rj1b5qE7WwmlpNUK4pe5TBSj0lm/ICzuBvVol5"
    b"2WEgshgl9BDpSfIhWa+CG1LlftEdCnCbr+HVeDS/hi5tYrvsz9a/1hirhpXcUq2z5glzMfRlqFkZCl4BSlTWzAL8lTGLwgvWN3uZ"
    b"48zp5l486oVpmT6rDJzhIGudddD6ZDnsrHY7ux+SylX7q50VqWkIn8/P8F/cK2qIbmKVuIiaZpb10b075QfpJNVJX7KRPCOSVKFd"
    b"6XrkQQ7/2IUtZddYHMuiNMV+7cP+heC+C6nD1QHqLniTqyrTvqtZtIxaHq2qVlarg1EXtxpqBbSKWnYtiZZWe62GXcxO9V+1O5Qo"
    b"B3z1B7j4FUpPpZbiUP6gb6ewRiwF+0530eG0InXTS2Q9qQ1u/Cz/kdPQvz55CtjoLFwiEQw2hTflmbhl37F3wHf3tMvbRW23Tew/"
    b"1kPrHTrwkXXeum29sP6zLOuXld7OiLTYAQq0zd5tx0IdSgCBw/g+fhi+WUce6S7GAm9H0ZWWyC0ry6pyNFLJisj58nbBAx4Frnag"
    b"NxbJhXKUHIH72gFxFWUW8KRXxkKrnyAFnkOm2QL0hs8wth3Mukfshr+8jpzzQRgiicws60DHxwKfR6QNV1SGDCHTyG3yDUxZH45y"
    b"F31BvawY68fmsSvsF1igptJJWaQcVm4rRPWqxdUGalt1sjoVeNylHgL6LoA9b0Suj2LNanUuZqWDWk9Nr6ZRnyo3lDVw/h2VOGax"
    b"jUBiK/aF/qEj4RbS0cvkMClLipBb2Ks+UgHTz4E7Lyx+8nt8AhQ7O1f5DfugPQGKWseOsVOh519CT45au60t1jJ0/mJrLq7nW6vQ"
    b"7busnXDe162bwN1X1DwKj89vl8P/7IgcOMVebO+yj9gP7A92PPLK/3gFXp/3RJJfwY/zR/wP1Ci/aIV8vwI9/05kRWX7ya3yitSQ"
    b"tDqTf9G/NqlMu9Pt9BV1ACn92CH2GrkmXJ/16NlvSjI1i9pRbQa2XKRuB9vtUePVc+pvJJ676jd1n/pYXYVOnQ5f2EXNjRGvPFOO"
    b"KNPhEEsrKZWv4IEF8AIlmMJe0i10DK1HM9Bf5CqZj46tTAgJokeWyAGyiMwh/Zjro/Br3UUHkQJb/h259jVfwsOfXAqfQ6kN74ZE"
    b"2AJOuCEvy2vzerwK74E9HgTWG4luX4AuPIU0/Av+JI3IJKqLmmIQxgqxEZ75EZ7dFr9EUplcpv//s1CWkjVklcj58srJmrIkHGFx"
    b"YK8g3GF6zB2Far+HMt8Gzq6BOa8Bh5fEEXFBHIOTPC3u4Z5X4jOeU4NqZ8f/qy1byOHoqw3yvLwjuXSQvKQhaUUWo9bnwZW/SUFa"
    b"lLajE+gCeor+B9REsTysIhhzIFvBtrOz7A37zVQlk5IH6bid0giVHKQsVDZA288om5Tjynllt3IJyN0ClzgXvDpd6RH5tf6yqHYi"
    b"e8mOstmsPyvPkrBfdCedQ2vRtPQT2UaGkpJEyotyNrYxlXwuVorBIodg4gYqO5xngTN6bh+116Dn29sF7dy2sJj93Hpr3bPOoPd3"
    b"Yzlp3YUXfGIFkAST2BnsfHZDuzl8+BJ7tf3Ivm8rwF9+3oH3xozt4zcxC1Eip6greoup6Npr4o2IipzDrjsqtFcelD/htzNGzio6"
    b"gywn58gbEiLp4C8aRc7udxDVeU2jwV2lWVPWhs3Efm1A9x5hsew5+s4Nx5dfcSqlkNyKKoWVXEoF5X9KGSWNkhmq48A9BvvC3rM7"
    b"7Bg7jr6fx4bgeZqwrCxD5H3+h8iZq4D8JrQEVaEgp8hxKFoXUotER84ZuFMul83A4enkb7izlWKv6AXXXRc+Mqt4CnW9DNexH45y"
    b"CZ/Gx2NMAALn4vY/UN+d/AZ/yH9wp0gpyojGUPwFqMAtaKxPZpKN4OtmQU33yI/ynkxOVJKJVCS5SFtSBUm4My67YKkC1UiHbEwI"
    b"A1ffBJ6Wy/myK/BVFNik8hPY7zD4cJYYKDriNcL5Oy14JkpkFOmEL/JNvmpYW18MED3BnOvEVeA0IErIv+RA4HO3NIHOiuRvMOUd"
    b"8omkAlN2hIafoV+RJXOD1Uazbew28OhW0iOFN1K6KX8DhdORltcoBzB2AoGr0OuzlJXKKPR7J6UEZoMqFrsJLz6fdWC1mYfF0XN0"
    b"Fh1Mc9Ik9DFZRyaDHTORD8hb02VHWQAu+B1cycrIt6VzCSpi+R1+iG+PVHUAbw1/VwMqXg7eJnwum8K4ro7eb4Pu7ww2HQDsTgeC"
    b"V/DNfBN44gS/De/zin/nidyAHntFevBAQVSjnGgmqoqh8OYTwcgz0cGbwQj3RQIcT0qkhDJyJNL+WnkV7JicOOC2O6FnjsNvU6Cj"
    b"FBxOfzju3fQDjaXpWF7WgHVlw+C9V2NfL2M8Ze/YfWYAb7/ZM1TgNdvJLqGnl7DJrCNrz4qwXMzJvtGn6Mq1qEdbWoGmok76ANUP"
    b"n1WuL2a8PHERhYTPnHpcLkZ9hgIrLVCjvDKjlMIN9/hTvIZbu425vwRdvYq9uCjOg4lugZ1uwsE9EH6MEDotOf5PYTBcBSTGJnIO"
    b"FHcenneNfA8s/ZRCBmRWePgiQFgxMFQp0iZyZuRO2IrwUpdUJUWxNj3JgloImSAfYxyXm5CUB8hJ6IzqYM4omROcHUBn30R/h1V5"
    b"pVguZojZYqSYjGW4GI/kNRHVngoOXgtndB45/BE48wOSjwqmLQa1D3/6ejz6YScq/1zGyfA5vMNnWe1FRpOlZA+5QF6CGRgtCKfX"
    b"lA6Ezq6jO+gV9HA8FTQzyw7+bMZasOFA7Az2D2ZkE1hwMzuHBHoI3b8W17PZMtzfB5gsAy3ysgT6lu6lazAPtWhxmkg+kJ1goXak"
    b"IGbgCVzJWNkDbj25fB85O2NfKFJ+kVko4jV/y/fwg3w1n8QXQ2nHw8P3inxLdgywOAtr/+Xr+S5+hV/jn7mfO9CLBUQVoK6HmA8W"
    b"COvHEyGBukLY+wZggt6YmRnyEFzQM7BBnKRg6cIkhtSBOjYgg0nryFlE/4F/XEMuwnHfJ9fIU/IO4w+JIwHot05NdK+NxUddNCNV"
    b"oLBumpwmpR4aTXVcUsqoJImEQ4H+kF/kNflKHpJX5Cae7QI5i2UrOQOF2kZWkdnQqtFkLBlAupH2kXNllwZGspMkJCmJl/Hyrbwu"
    b"b8NDhPlxvJyCZNARe1EWGpoXCp4NNUuB9OCUHjhLFezpwtqsMh/QUgk17YZ9nYu9PSZfR87ZXgX4GoC9nECuILHHYnBSnKanDTHT"
    b"LeDc+tCJdBIdRyfT8Zj5QbQDrYOREXsYwvbfwDZPx6yVISnJT+B6DTxkI7yeJh/BR8yD8tRGDnCAUx7Ake7lk+EQemP0BHv0B6v0"
    b"Bod0BGsPBnfsBevEYs5SivIYs8Gr59Fttqgs66FztsunUo+c3XAg2Q33EkvSA42d4Wc20mPghO80FcuGHm/LarHxwNk0NpdNZWtw"
    b"vRLXc9kINgp+vyVrCBYoxgT8/2t6Aho3GfvUlOanaWgC+Q9zMA+Vb0OKw59b8gccxB503Dg5DO62JuqXFZh0yaQyjJ/wd1ctKMoP"
    b"ERTf0fEWttUJz+yTGaAPOaASBdH71fC/WsIdt8YsNYH3ayF7QUM6wJm2gQ63Re+1wv1NI2dmrgW1q415qoNb1SNnMmyE+5sBof0x"
    b"ZkV+XWO73CzvQ4u+yKD0y3zQyipIE/XJOPDXMrISODpNLoHRPgBjfhIkP0g0/UKisHdxRKFP0cfhs3ZfjJzlfBGZQwaRHvj/1ZCQ"
    b"0xMuvwFdx6AMi5EGBgMtzbH1lbE/eeCuPNjz7yKsFnEYL5Eo3gsT+xyC/48GznKDwcPveLQCjy+Ey7kgD8uXMhEoy0kKgM1747UW"
    b"Y+6OwWf8BJtko3lpdcxgZzqXzqYb6Gm6B/N4hf7E+ExdcPRe5ge/BOhv+os+w3ydxL2r4RkmwjV0oIUxawz5/i4S/hI8dzM46uQk"
    b"AT18SC5FfTtiqzNgph6Lu8guS8QEMEBdqHEmIDJGJPDk4gk06i1SwVd+CT73Ab/L3/DHWPMN7sLE0OAeUoJ3wtrVRjQXf8MZjwfj"
    b"r8czvkUF0uPZK0HNm6ALR+JVjwKjBpx9AfIXvMQ48MYBbN1H1D2M1Ya0Nx0B5VlPL9IH9Hnkt6JSwiVmAiKzAZPZWWEsmeCO3Exj"
    b"Jn1J39MjdB84cgD6sDTUKjl48gs5hJkbC9dQG/ubihjQk2twc6vlVGCkN2arocwF5GUBDrMi86WWDLeisaTByA29qIhZCr9b2hvq"
    b"NgXOf03kmzXPgKoEzJZO/odnLQnGqYU5a41e6E76IylMJH3IVDICTDid9MOtfqj4YOxlXzBUEzy2HHomHzCUFCP8Gyq35Suw1EZ0"
    b"0Ei5Xw7Ca41FNwzB69fFvGTENqpImBZQFEBW/wGH9x5Z833k3LCvgKrw2W1NYCsZUkA6eLYMYLgiQGMzJNiByKiD0Q3DkKBny/Xo"
    b"0N3o03NQx2vyP2jsJxk+4/QnVCb8/cmAZKiSj0QRN7YwKakAjalEWkDfRmC/FmOW9qBn7kTYPAPNRGuCD4bAMW2Ab7pDE6gJN5aP"
    b"/QXlag9mmQol2wpXsZftRvI8glsbsWYK0kN7VoPlZOlY+IzFa+h02g2znoZega6NhcJnJA/B2WNlCbDzE7FVDAMzJhN/+AVo1lRe"
    b"lFfklP+0P9ub7Rv2RHujPRZjut0H+XKgvcGeYx+2T9i37QSkzELwYb34aLjcu8iXGeCpBsCFXgcH5UOGmgIk3ED9kyHz9IdqhX8H"
    b"Qqf54Op701F0MT0EtnyLbuLUoE6WirmAuWhsdUqgLgq+PAG99pDep8eh8GuAuzFIA/VpAeyJDzzyhYRd+ipgYCK0qT14ozj2LQV8"
    b"sgOqqWLmBRgkAdX/gLo/w1/voTEGuEqBi/ZgBtISL8kBdc1FspJsyGZZ0S0Z4IKS4zpp5BeBQjIN+S4J+QaF+gxH8p88g6xyFM5w"
    b"A/hvGpbhmPVRmP1pYKhZQP0E3BoONZwul4Efl8qz6MWT8h3+XwiXAcy9LbPgNfNCRSvgsgYuS5KW4Pgm2Poi8MMZoSz/g9NXSACI"
    b"/Sa3yRN4vRFwbXXB0UWRLFPKEJD5EL5vH5LIEujTFKjbUNEa3r8VWKUjkm5XONxOWBd2GlPFBnFAnBPP4fkd0INy4PLh2Nqj8LdB"
    b"6UV/dYS+7yU7yDdwYVraDGq7GOx2HRxowVPlY43gb/+OnB13N7sIF/WO3WCf2Fv42q/sAfsId/WE7WAH2Sq4runAXjNwRxIWD8we"
    b"BaMOpVVpEfiSj+Qokv5g5Izs6IKHkd8c6QktSw+H8FJcFtvgDkcCi5VFduEUunjLXyA77ePHI98nWQCcLYBaT4PLGsTHIlvO5Z3g"
    b"9sfzUXBZY6HZq7GEP/X/iT/jQa4j9xRCBmom2ovRYiF49xpqRqGKJeG1+kJXtstHcL+p0YPtyTCyGs7nFXGh62rRTsicK7D/j+Aq"
    b"U7FkrC4riwr0RWfNZpPg4ufBWc5gy9GD46DmLVlnVhKsmQpa/pNexT7PBrs2gUdNR7+SR9CEMFtVjpx/8ht4eQ/mcxz2vIUsDT//"
    b"P7CPS34F43yDc/bDw3+Arw+/a/8Yuh6KzFhaME4ZaHN74GA60LUfyvhEvgGe3MBSPnjzMD92gXuajG5YCie0Any/Gss+eMVTuLWb"
    b"rIfGrsK9kzED4W911wHW8qNbwr949R5+/iyYaxWYezTcQEu8Wl7wIoeefkKS+IB0+UpsFCcjeDsmpsPdL0Gnb4aT343LQ8DXVbjj"
    b"F8gcn4QBr5QGepQPWC0Gx1QZvdEO3DsC3mkeOHIHxjUw/Ut5F735A3NA0RUpwIo5gf2S2K4a4Prm4Ko+YI3FZDu86Qm42y/wD9mg"
    b"tE2guOPo/Ah/fAVHuFkhloN1Z83ZBLaILWZnIufEvguUvgM2Y5HG/Owe+w9pbDPc/zQguQv+R2YWoLfh+0eBY7PSOMz+XPBUZhKL"
    b"jh0D9+OQr8CNHYHHEFLkHuTLTjwazPgcvLjd7m73s2vaxewSdlI7q+22U9opsOS2s9t17Gp2X3uSvQDsedV28/T8LySB6cDyD54N"
    b"WBwkrqAT/wdnNQgd8FB6kG86w+udAvqS0NyRX8mbBr4/RX+g+yi2NA18ZDksbVhV1g3d1YLVj/ydneUH5jRGwPOv6AXsy0b449Go"
    b"Tk1aEa44Gbz+R/IWHuwQcDAXuBgBhAzCzHdFD1ZHqsuBJR14JxsYpyDYMC+4OiVqoIOFPBgx8GFRYNMQZugbFOwjGDWspffkaeBl"
    b"RwQxi8FyI4HKvsiC3YGdtpjx5pjzRnAjYf9YAZ6kGrSyGe7pBtc5BElhHnz/7shxsesYcUCygqwV1sQsYPHKyL6NSSMsHeGk2gHZ"
    b"TXFdB6go+//b6iImcPMQ/LULvTQJvNtelgI3JpVBkSguoMI7wHorRcvImd+LggOSiQrif3BQBYUmiuG6gCiF6xa4928xSSwGk14H"
    b"ej0yBlvdA9t4XJ6SlozBKw6M5JG7JBnNA980jS6AY3pFfWDFqqwfGGAdO8xus1cskdksmZJKyaTkV7IrRZScSm4lM/6OUgSLw/23"
    b"odCroc798P9KQOt+gF3+oUuAvgpQtA/kCZzjdDiYQvDRL5FflqBOLWRxOJMEpMQTYo0YJwaKauIvpEiHUMUD/h5ctwecNxX8OIIP"
    b"5H/zVrwdb8pr8Xq8Oi/P6/CSuK7BS2N9Bd6at+HNkUy78dkYy/gRMOtzeE2Dx4j0ohY85TDxD+r2AhyUHFVohiy6FQpkybTwVP3J"
    b"cjiTb8RJy0IfJkCRj0O1Q7QA9qYpemoclGE3u4oue8G+QBsCUAcbqvCNPWan0X0LcO9gZKG2LAsriH3/jMSzDM9Th5ZHKv2D9LYa"
    b"CaAlcJkNHfgjcnRhsewMZ1gSI7PU4Rq/iAA65414Bs/7KvJu6jPxBX4tERnaC47MGjly0wmJZrhcBISdgFY/ALf9gA/2AdF5MZvl"
    b"wSsNwJQ90HNjSCc4435gmZHo/H7AWCNSD91YEh0QAzT65XcoxGkgYQm2ZQyetxs8Uzk4Rg9U5DNY7gE05SI4cS98+Crgba5Yhqw4"
    b"G5cTsWYeGHIX1l7A/dexzU/A8L+QWggSWVpsaVWMfkhjkzAWwJ9uB6tfgfd9DNfyCcyuwoXkAdqrYIsaYLs7YRtHkxlI5XtRrdvw"
    b"U8+QoX6QzOj0MrQakDQUurOabgYX3IUShWhy+PnC4MVGkcw5C/5wJWbjADT8BruAubrELuP2oYh/nAlsdgOzVGY+5mEPwa1raDs8"
    b"p4/6yTkyExXLSSi5gI5vBVY3RPjszY2AxwQw224+gHfn6Xgy/sE+b++xZ9jD7E5gwnJ2aTuDXdBObWex8+JWJbuU3dTubA+159u7"
    b"7Yv2F/BjRih5N76dX0H2KSxKItdsxNwmkdnQh3PlPhkPB1mZ9IJyXQZKHOC10shcA7CfW6C1/9FYZBcvS85iWHEsNZBZykKLM2I/"
    b"XKw0U8CeDvaTauw6stsJVOYAum4NHQvsdaNdIkcQCiG/ZaRJaQz2VKdvgPLn8OB3gPez0J4j6MttwOYceJe+qEMb6GcLIKU5OrUO"
    b"UJUTCyFJyB94te/yMubvKDzbPjDiCijeULBiC+S/KmDF4lDxsKrmk8mQH8LvEWSQUWAtHzJSbuxvZVkYbqgOUlMHoHgw9GEGxmJ0"
    b"4Sp4yANgy9t4/je4/CJfgIf/RI4RPYaj+Ah/+RyPOYxlKZA0HSoePk7QDK9bBPkrDdKNCRW/A8TuEvuBzbliAfLjYDEczrELrltB"
    b"l3pjTBZDoOyLoXyHgdmX4o+IlqmwVfXwjEvA2W+wj9nAwl3JNLIJnPU98p56FzoDWfI/+gm8mJdVYr3ZUDikPew4FPgRo0qIaeBC"
    b"ohRT3EpGJatisuzKN2axH0DfI7YWvDgVzNASmSUF0uZ1qN9M5J5G8GIp6ROo/0oyBOjPgUz3GYy0T05GbWrK/MgvseJp5HdAl4j+"
    b"YPvGSNR5BRPx3A88/QeG28bXRVLNKN4PCO0KZmwT4cS6vASWkrwKr4a80xBrWoIlu4BFh0GrF/EN/CC/DB/5iyvg28KiieiGzt4i"
    b"zqAiIVFY1oLWrcc8f0XSyIBt60HWAZ1PkNqyo2cmInPdoDeh3zHgu6asAXzxFPjGXchqZ8GSt+FOwseFn7Ir6MDzbBvumQtH2Q/J"
    b"rhr4MS2882904AE4yW60LZ4zFY0n98kx+LpRUMWwcicjCZiNm+C4NZiZYdCsLpFjiKXBKiWBpFLwlsXBV6VleVkdCtwCfds5gqrp"
    b"yCwr5BbU8Rjy2U0g5ysQxIElPfILqMmxpMaSAosTLGRIE/f/gFv7D8l2B/7fDCj4MKC0I9iwFNjMBwf7K3LE+aI4iiqtj7DgSGhr"
    b"+P2IrtDZNqhgS1w3Bdpair6iD+ZrBnz5MmSTf8QNoO0JuPGZyCht+MZKshD2pzm2NOwuLgHVL4H2eJkStc4PjawOFzOITAECV6Dq"
    b"p5Erf5B4koJG02JIGvVoa9oVDnEqXUp30f30GjLmUzipOJoWbJAL+bkYmK4aOLEbcLqQ9Wfb2Ri2AX5+PmZiMluPuZqOpTf8fnM8"
    b"rhLmI4YF6RPkmZVQ7HZ4hYyRPLMKrroa+NlB7sDH9IAHSoftfwDeHw3fmBWZ+jVfzFdAk8vzAvyzTfgR+xQS9QR7lt3N7mW3tVvZ"
    b"jXHZ1O5o98eaufZMe619yT6NdC3slMBlTT4f2eccNznndURDMQdO+ybYMRWc1iDM4k04smjkxvpkKLzyVvKSfABH5oSPbE1bRpzk"
    b"EroNzvASPU9fwLl8hKt8S236hSZCH75Qwr6AP/1Y9zvyK+APUavrQO4VephephvAmKvQ2auA55XoyDm0Lx1Ee9FWtCOtDjdUArqT"
    b"B7X4H/VQhop8Ja/BnUciHbsBfrMnfG1lKG0lEv4sXZxMQsKu7QXyy36gdiZ07+/IUceqUO58YMYUyLYaKqjKd0hqT9Frn4CLP+I/"
    b"LI/hS8KfT/kDFfXKjyIdslEKZCMvMJ4KKCyE68qRd25rICnXheusDf6rg1sN0QH18IhS0NwseJ0M0O9U0kROscR9PN9VqPhtoPa8"
    b"WI0ss1osEkvBjnPAkQuRdDbg1naM3aj7OWzPd0GwlXnhkNoi+c9FjrkZSZE5kKlGkAXkHnkAH18QejwV9TpP39MgzQO/3pZNRG48"
    b"DMZ7yeKZZKmUdEph+MS/lEpKVaWOUk6pqRRVCikFFA9co5+9Z2/YFmhz+Ahym8g7lX56C5wwA9huRr3Q5fuY7y3QoHbo2BB6eA16"
    b"szP2u5Skksnw+9Pr4OkGieqitMiCRJ3IP/NbwNIhuL81YMRxvD9vC06szRuAE8shp5TkRXGdj5eN3KoG51iDN4Kf7Mo7InVP40P5"
    b"Fr4QefwihoDu54KvLotM0xjuZzbq9wQpNgYzUVcORN9uQLr7ItNE3r1cBPW8ArUIkOLATB86JXJM6yVQGIUUUwy815aNhUOZz3ai"
    b"Gw/DnZxi1+BSToIp96Jm27D2X/TkPNYMPVuIVUR+C1IPO0Pv03VgydFQi+rQiyh4yefwK5uh2kNJd/im4mAMHxJNgnwNzbwEBjsK"
    b"b7kDvbMMY5pcCDWZKaeAaybJWfh7Kth0nFyNNctx/xy5DnMc/sWzxZExA85yLC6HQ9kHowcHgKs6wA+VAtd6geDwO4g/wGPPxCnk"
    b"4c2oyxIxCm6wq+gsOoiKcNkFRRlRXGRA+kgLhsiKVJJdZBa5RR6sKQF33wBevA9Ycxz4cR66fbt4CPz74XGTgdFLoVt6YEuXwA+c"
    b"Rn1/Si8yUxF41w6Ro7zbyXHyAl3oAEKy00q0Cjq2J7LyQrqHHkFnv6HvKGMSTBj24eVYHdaQdQLT9WWTwIHzwYZLwX+rUe/NWHaw"
    b"TfCGq3BrKcaCiIp1Zr1YXbirwuBSD/sF5jhJdwKVfTED+cEDfrimnVCpZqQ0Uv1PeIYlqFBF9NzPyK+FjBX54fI+IXkc4BOBwgq8"
    b"DHdyhT+wH9r77ZX2JjDhXLsHxt/gxYF2F7u3PTLyCd8V9lb7mP3IfmVTngoobQrfOIfv4lf5H54MFewCTdkiLkeOhqeDV++FuTsN"
    b"B++BO6sNvzYaGWYv9OIbtCI9zUzLRX4ddyYYbTVdi304g279Dxz5HRzI2GcohgodTsssmhT+Usf+JsEep8OtlCwalzGoYxQTeJxN"
    b"46H1H4DmF/Q1UH0BPHoICX4rxkK6GKm8NzxBOdoPvFyS5qUGyUjvohdOQru2kllwle3BkiVRsSTA6nf5Dj7vEFA6FXhsjj0pChXP"
    b"KB0yzHs/xT3o5SlxSGyCzobzxjwxQkxBnw8RQ+FShgJr/UUveLmwyv6N6zH4ayLWj4W7G43HjwPDjYNGTRArwHAzgdLxqNsM6PBS"
    b"/L00crkYf03DK0wG/80Xy8EkS+Ac/4FOb8Nrn0PCfho5nhg+PhU+ll9ONpZd5UQ4i/B7Nl+R573ovb/IZKjSNhIHVcpF/6INkPkW"
    b"gsU+UUlzQVc7QYPXA2mPImcDSK4kA/9VVMorbZTWSjNltFIPSwfc7g2WbAZ2LKrEYIR/Ae4K2wpUdkSmzAckE3aPXqSz6HCwbn5U"
    b"9y05ilceQwog8wXlRbicvpFj/qnA3Fehz8vFVNETfVZIxAhFvAQW9/OdfDkfzUfyTlDdhrwYL8Lz8xQ8C3dzD4/ilh3GaMhOwg07"
    b"Gn87eQ4ejcfkBVPWwegELh3K5/F/4Div8BvwjUGeEt1dE9w4AmqyCvW6Bm70oBPaAZk75Fo4mo8yKylD6kI1piBvPCFBVKkQ7QSl"
    b"XUZ303uok0mzs/RwkI1ZDzYHHbotcgwrnNquo2Y3oCVP4SPfgC9vwkfug+deDxadB0/TBapRgpUCSh0sAZi8DC1fiNEP6tGUpoVC"
    b"BUkieU/OkAvwMUvJBGT8jvBWFYDCtOAUhXD4vqfo4MtQuDPo4/A7O8vAlxPAj4OByh6yPhS2HNS1EDQ1m1SxdwHxFeMG9PSo2An8"
    b"zIZ6DgAKm8P//QUfXVREwaMHuCZ+8A/8E3r3BT/Cr8NtH8Uc7AInbObHsJyASh3hN6FWD/kb/gr+x+ZuqFgOUQnP1BZYninWAoeX"
    b"RBx0PCNSTl1k6VHYym1IKO9lDCmMlDIauXEr/Mh1VJbBp1SjtVHbGejIK+jOnzSAXJgHjrA2skdHNgFauwSctw4O/SQ8+lt2j/nZ"
    b"J6QUqnxlTDHwl6J8Zwb7hnUvcP9NzMMl6NIB/M8Z4NDmYNMcGCY81S16nC6nY+CUStEcNAEe9XDk6Hdlkh2VDf+G3DhkiGJIgLGo"
    b"1fbIJ4ryConkchhpeAJScR2eHYk6YH+wL9tn7Q32UntR5HN+nSJesb3dz25njwBPTrfHgxs32rvsm/Y9O8627Uw8D2+BZ5iF9HMK"
    b"VY6HUhcGEwzEnBwT70X4feNW8EfLoIKnMMPfZW70SmOkrPGo13FyGwyZQDJBQcojfTRDxcaAI/eCIx9DQz7BL8aB+VzgwiyoXzEk"
    b"7r9YLaScBqhiUyC1E+uKLNOFDcDtfpHb7eG12wPFHVkFKHgpVhLakxwKpIJHFfYMKf48POpBVGwJHQYtaUhrQs2z0vDxjddkD5LP"
    b"JGxb+CwIhYFOEwzzCDN9AClkJHxYSTg7HzyPH1p5SZwEv/0L1e0FHqwItBQSuUQ+oYr0wuDhfy+x3EdV3gF3n/k1IOwJcPgUefEW"
    b"sHaDv8Wal0DnY/TwfeS/dzyRu8R7nk384ulEauGBn0qBZy4pyotmoh6YpDd6fBa6fIvYhwT0BBUOf0InC3q9KjplFOp8AUokJCXZ"
    b"SFPSCN32D7mKPeOkKCo8FNpwMMKKGZB/OwFF08FuW9kX8GJSxQlOLKVUUXqCDWcoPZQpylxlhLJcmahMUmYrA5ShSj+lLliyALzk"
    b"/4DRIJB7Cpl6KmvHmrD/MS+U7CjYpC+QmA+u4Cs0ZzXSU2Pg0EmeYrsWwYU3QIoLq8tlIHEKdKMBsJhJxPGfqNE+vge8OAfJuQ2Y"
    b"MT+yTAzPGuFFhQdtxr/Z0v5uJ9qGHQtltm2Ne3lynhrcmBvZuhbcZfhzMdP5Ar4efX0BdQ9/Gi41nFA9zM4UMUnsRdXuCafkomLk"
    b"G2FhV3ZHnpcuwuDfGpE2yBMLyF3ykIRIamhoA+zLBLoIVTsd+byFAwktM6vJygNlXZDaZsBL/ssWowqbMbZjhJ3MLiS8jVgb5sdB"
    b"kc9gtI0c7yrCsrPU0BDKnsPNnENi3Al/Ood2xqvUpkVpgchnaWLRwQ+g2OFjbzMinw7sDF9bGt7LS/6HXBOPHH1RXgGvb4kc0euO"
    b"ZFMbfq0wOjwVvI8fCSb8OdENYg1UdSyUuoOoKirDt2QGmqgQQOR3oO8peO8car4OXDgV12P5atR+HN/IB4AXJyJPruNzsX49eOIM"
    b"qnmfvwdWGfCdCr6ygGiHrD0Car0Cr3ZdxMKPpgYOq6FPxmLLLsvb0g1uLwvV6UwWwxFdIc/gRJLTwrTy/78vexRK8YN+oyngeIqB"
    b"G+vB9/WEC5yHKh4H1z1j58B/j7CEU4qqvGM21PszC7HX7AO06Dp483TkWMciIHkSqtyeVUGCyctiwbgP4EQP0oF0BPx6+LMuX8kr"
    b"+MV/SR/SiuSD+wnKE3AQI2RPVC8pxn1gYz32qLcoB0w6xW9U6DhUdj4fAVQ1BcLK8ww8I7TatJPyH7ZpW/ZbW+df7aDt5X/sjNzH"
    b"08FlZuXteV3el09GRY+ghi/4M57A06D29aDSg+EIVkW+LfsT+S6zzA/f1QHJYLncBSQ+koRoSHgVwD9/o3fmk13gyefkEflDoqiK"
    b"HJyf1okcdRiF1LcEbvI43QXNvYiEHYsEmIb9gN/xsIwR11wdrFkLla2MWyXBicXhwiuCE6uxAlDsgnhUbuZjqVjYVwaQyn/CuT+k"
    b"m5CYNtLuQH1NcHL4/Z1cUBULPXGD7CZrwY8D4SLLApEe9PUn+QD9swaKPVD2R3cXh9KEP5f8A+7nodgh9sDhTQVHdkN6q4P9LwDs"
    b"pEMiSQkF8gk/GPIXxm8obyzq/Zl/xOUP/PURa99CT35hPUf9NKGL8CdbUyPRFECGKQdEV8dzNkdF/wbOF8GhHhD7kWDuIRuG0OO5"
    b"ZE5sTzNwznRs3cHI5yOCMjscRwvSlYwE128iH+HRXXAoJWkvIGUl3UJvwlcnoI4pgcfq6PKxbBy6exM7CAW+A8b7AR/0m8VBk6ny"
    b"liWwr3BGH6HPt4HEPXBNC4DD4ah1+BhjNuZm7zEz26FoE4D5cG4JH197TfbBqw4gveHJshAXeYkarkb2aw+vE/78jlf+J75BWXbD"
    b"OfdDQqsYOaNPWjgZIu7yR3Ar29CPS5CRF6FD50Te9RsR+UT1RCjxMPjLqUDtVtw+xTcBw3dw/Y0/h7qI/+PqPeDlqMs97tk9vbfk"
    b"pBMIofcWQJDeu4ACIioqoFz7xd6wXXu9chHbFVFBAWmCgPQWOiSEGlJJP8nJ6WXPnp33+3xnwn3fN/uZk9nd2Zn/PP+n/J72H7DN"
    b"TKh3cOV45Pf9aMRvgW5uwZJFX05UNc1JF4Bw3oMMfy29Lr0VOQ7fryOZkhyVvBOUE5W7N0O5N5MXsSpV4LsFhYPQYO8tfB1c/MvC"
    b"rfgjD0HDlwpbC2Xs9yys7lx05nZov13gwH3gvH3lvn3wx6Pmdxo6ta1Yg33eirVfzS9f5RwPFP5SuKpwDT7TVwsfKJyDfoyni3QX"
    b"auDF9cmi5DFoeG3yE7jxEjzS47DWeyVJ0ppEr9DToN4bmfWvp/+Rno9OOhLpnp1OVN5CS/0TyfuTsZevwDeXYldPAJ9vD42bQX0N"
    b"aMeWyorJ5sqLcN1SXn2Tj8F9z8CPK7HVG+HQHpDTGBa7BU0Y9f7zsNKHV06Emhdwzi/jJf0FL2YxMj5WWVtpSnfCb7kYv+oHSMi1"
    b"8OG9aPCl4KAm/JbT0EY/S34EbrwHjNyfzCzsgnY8H175Ia/7sKYr8fSGC01w0t4goKOxPedjbT9X/ACc+ZXiZ/CWPwGW/Grx23jM"
    b"X+J1Bejw/aChI4oX4LHsB83TwtTiikKsWH1P4QZw+dcKl3CFvQr7F9JkDF68Cx/mSnyYC+DGvdHYw9bc/hWf8DPpufgyO6Rt6RA+"
    b"2Ivc1/Xwy2fw946unAFCnoc0lierK+smo2diETjmEdc9vA/P5E62B9l/kW0Zf1dzzHowTngrXZX5lf3hwbPQiJ+sXFb5nmta3MvZ"
    b"X4dub1Vq0+HKfFDNflz/hPSzZnJvSK9KnwTdLEnHkOM5+K/7Jscy7x9LPgpH/gyOvA0LsyhZB55M4Mpp4J1DzOB/GNTzNfDeb7C2"
    b"/8BjfrjwXGEFPs8wf8Ob3lKoLY4WEvh0slApVOHDVNAAG9CIryO7iwovgETvKDxY+DU+9o841zfQipcyS8eBD+YUOuDHEXDsIuz1"
    b"tcn/gLs/C444ltFFZHvQ2oM7oObPQWefSk/Hk9kJBNTIHY7gp72BjN+KBH4XCnwM1Hwe/Hhi5Qg4aneQ5HZoyu5KZ6Wx0gavNVbq"
    b"sN6tlaQSFeb1aIR2ZHkeaHN/jn0H+vAYfn8OKPFjcOG38KZ/X7kOqv4bPPAGnD9ZacW33xsLfQaa+rOgsT8ysmfTlWl/2p7MRYLe"
    b"l5wB+vlW8jc0/QNJbWFTshMydzjo5IOF78GPN+krLoKXxgqThWnoyD3MwixA3x1ffBd8dxzcdwJ48Dzevxe0fgLWZg9kfCZ2prY4"
    b"AFXfhP6PFP6IZP8XfPgJNO9RhdmFpFBfeAxv+o9mZ9+dfDzZMVkAJhtB+9yTPghO+yXo+yI8wMhlDVbKII6Xod31lWu41+9Uzueu"
    b"j+d1BPQ4GLrMxdpWQaFxJLmApWmqTEx28v90KDkVlD4Neu1eORZan1q5GC/v85XPVb7v891uwoo8WnkBmm21w6YT7n8HluTU9By4"
    b"8UtolJ+nP0v/hEdwd7o4XZRuSQfSYtLNbO+P/ES37IeSL4LafsG93JzclzwJ6lmJV1hK2grT8TMOKBxaOKNwWuEyaPo5+PIrcOYP"
    b"sON/KfyhcCd24hY8xpsKC6HSP7HFN8Or94KTHkNyH8Ay34Rl/jW0+wGz8WX8lzjLeXibxxV2L+xRmIp2rCksTzbjaT+c/JO5/D36"
    b"5QoQ+An4qNuhw/uRnkdBGX/F3vwa5PhlsM8J2Ow5eDVN6UowyQuVu9h+gJ78duWb8OWHsEDvq5wLnc4FFZ1X2RFf5FDk/lQoeRTU"
    b"3gt/b4/KAjB2eN1n8t15fHd+5SOgw6/Aid9jdn4GEv0TfH4/lH2lstzIdlqZl85EMx8FVT+VXp7+Bqr+i5lekvakpXQK8390chJI"
    b"4zN4MH+Cji8nq5JCoYn73B/tdQbo5/NI9G2Fa8Hl9yqvpUJ9sRXUMxutNx3rPQduPBjuOxnrczh6cEfQd0exHU3ax7GvY2WehZ53"
    b"gr9/jK8ez4o6DD90Cry4EgR+G8jrv5NPIs1HJYcnO2BbKsz3s+ktILUfM94PpSehn3ZP60E7kU96FYrdA378VeUXla/CTVdgXz9U"
    b"eS8c9r7KYWjLY+DNE6DY0XxyInj8ArjvI9D0UuNnXwV3/hQO/D1W/5bKDZWFzMKr2OQllWL6RqUrTcD2u6az0gOg16HpeVi187HP"
    b"l8CL/2WG7QaQ7MNw4yvpVrRjS1LAU9gNH/BMbPaHeF2RfDv5ITryd/DjbeZOInuzJZlfqIMjd0NXngQXXYK/88XCxei4z8JfV6Lt"
    b"rip8G878Npz308JvwZtX8foxyP07SO93C/8JD15ROBfLf2jho2jEA/h9C/qiGipOooc3Jq8kr8KHjya/Bjf+gFF8Hq/0XORkn2R7"
    b"7F91sjFdg1Z/jPH/Of1R+tX0C+nZoOH9sTqz4MlqbPYQHLO+cje47m9I5rV4G1dV/guu+oLRxs9jdT8NLS+Dyu9Dks9l71x0wUXg"
    b"zY/x/yeh66eg69fwmn9d+REa4/dQ9l+VRyrPVJaiFQfQwgXsc5f+U6DFS6DrN12V/w6ouSQdsqZjf7Tje5Lzk28kXwaP/zl5CF9i"
    b"cdJSGEh2L2wP9U6DCp/i9UNo9r+gyFuxtU+Dg5ZhPVbgby8DDa1Fb25mW8X+Yv5/Hvl+Br/yYfDhzWiBq9EG3wJJXVI4HZ24ANw9"
    b"1f6JV3ndmtyORvkO0nBBciqj2cna0xVI8n3Q7hr8h//AjzkiPQ792MndbLB/MHjy32CR36HXvgQO/yh0+BiUuQyqfYDtQuj0QWn1"
    b"EWM2n+X7b0DdiPXewfGPQvEHKiuxIVXpc5VmbFZUv3SnB6fzkdp904+nJ4MRrkg/gfR+EcT16/RmvPy74MMXsXub7PgpJB1ox/l4"
    b"XAdhFU8Ee1+ETvoM/Hgl3PhLpOxWOOR59NVbcMtWXmVQZTN2dQ6U3Rk67GblxNnouFMLFxVOxJ6/Rw/owsL74brzeH8xdv6DhQvg"
    b"4EuxJ2dy3DyO6Si8AxzQwTaGLduYbIKOi7Fr92On/wQ3XolsXwQ9D8XbmpbMTibBZevwEp4A9V6HZH0fmn7S7oQjwCJ7GRWfrKyr"
    b"DFeeRYc9XnkI+vwN+v4BH+dqLO3VcOYf0JzXymtXYU1+x//XVP5a+Q1W5a/4Qv+2I/FOeO9pUOhSq4o2yoNV8HrkJOehUQ5MD8fa"
    b"nJF+kBkN3+XbjOYPWJtHGNtq7M1E2oYun29d5eWgny8kf8BmPqCt6bXyfhp68nC8mmOhzUnI8UeR6F/BXbcju/9E5/0VRPNntF9E"
    b"NR7ikwfh17uxMDfDu9cg4d/j+C/wq0vQsycj2zujF4uFxsIazv5scjca5KfYlrj2SWjHnZIZ+Kwbme17GOFv4cafoB2/hKY6C301"
    b"F16pVOrQkZu435ddAf4RNNy/QT3Xgyh/xf7PsQ5XQ6XroNpNUO0mdOCNHHdX5TF7zF6vLIPiQ7ndqINSneme6bT0WOzyCWCqQ+HB"
    b"I9KvcNVPokUuB2V/HQv9x/R/4caoAH0Sj2A1HLkhTRnlVDyuLrhxCmjnABD4xcnpoN9Lk++CI3+Jxfwz/Hh78gwexuvYgZXosX54"
    b"sgFZnFloK8yAGtPwRXaEvvuy7Q+H7oMHFNGbQ0DvBxTmY6N24DUTbyX8lbbCRFJBjjfht0RkZzH68L7kTvXIL3l9Nfk6KPZiOzFP"
    b"BDfuyuy2IN9DaS++zJL0KSTqTuz178wcXpF+jPs8G111OK/d4MupIKJ67dBW+GgF3LS8sgpvbglUexEv/CVouBiee55PHuGbByor"
    b"+Px5o+eboe1GuLAfrBOVOxVXCJmFBtk13dGnjRzNlc7gipfCi9/A2lxlNUpUZb4GRXuR8GpszXz040mM/lKQ2xVY7P+ChjclD2K1"
    b"X8IKjIKQW6FaW+FodNqZ0OlY5PWYwsfRmhEt/E/k9tOgoY/g630U3+dzyPYn0YRn8u1h9iwegvRvB72nY1/aC6NJX7IFnREVAPdh"
    b"WSJO9iVQ16lw5M5QcUYSmbjlPtNxIUjtuvRXjPzzyNOFSNbR2Jdd8QdbQeEj+LxvVdZAsegUvgNq3IpkP4ysLvJZLbeBWSKWthCK"
    b"PQ49X+M1wlE1aV8l9EFbOp1zzcN6HAGK+jCc+J/pBejFb4Cvf8zrv5m1qF19Eu34NFrxUSv9NoHCNqQNSE0x2SVpTPbAHu4M9d6B"
    b"P3NRcnzyKXtMrkwuS36LP3Et0vaH5Eb+vx+aPon8vYin84p2YS38uQFqrE/G4dKBpLrQkzQXepN6dF50kIbm68PSb+bdZnhwC0dv"
    b"4DdLeb2A1/kCXsszUPAOaPgrvJevYWMuRzufyziOtmNgNiOsB08Uk6XM9vPcwbNoo3+lv+DefoC9vgJ5u5DX6cj7KfDjUen28OQc"
    b"eGiW/Td1Pq+mNa3iXRUYsyZtsKuqA46dzgzMQOt142POhIq78v9B8N3hnOEQbNleYP7dsciHQ9OIcX41PRGtfBHU/Xb6OeXht+nf"
    b"kPLAjf/Cj3kc7bgBix1xx/lwwTuQ8tOwOBfAHZ/ER/w5nPnP5O/c8ePwzipw8iC+Yh2abT7bEfqMB+MZn4sEn4/eO82niJ5UOAF7"
    b"fAwa9UCO2R6r0okOaEXHNoCgKskSqP8E2uI+EP/fk++Bs77g85qPY0Z3RztOSeLfMmzLY4zwVpDOb/Gtvw/dPg2KOyc9LT0MvonO"
    b"zF2gVTe6rZC2pyWQX2rlSIqFqEpH2avnbztYsAPO60b/zcLaz8Ve7AyFDuUsZ6TH2OV0Ljri/Vjl/wRZfxOqfTv9afpDcOtvtdAx"
    b"ezeDFx9hexXUuBqOXAvq7knLIO96a7K6mfVdwRmHchfHQcHzkvciXxckP0o+h3/4O3DQTcnV6K87kxuSfyPnd0PTJ/E6lmPHl8Gb"
    b"zyD1C6HLYui8HC5bzSdLsR0vsD0FrR6Hl++GYlH1GFT7DZz+C/j8R+Cr76NFvgH/fQSdeELyfnjwRJ8Mtw8+6lTGVgsSr09WpaPp"
    b"KpDGuvRe5Cp6Ch5w1aI/cae/gb5fE6V/HSpcAp3fi2xewOsstugyPFW/Y4HPJzkOj/gQkMwCuOtQbMo7+e449k7F7zuF745DAx6H"
    b"xo1Kn3czY+GHfoTzfQo5jw6vL3Gl7+sTXsXs3sz2LGN6LX0jXcoYe/EOW5Nm/Jld4YYTsNnniDq+mHwCSv6YO/4DaOQvyb+g5QPi"
    b"oDfRmUuTiFb387ffDNkw8j3Ga5J3FT4LaY/erTVY/GUgp9fQtIug+FPQ80HoGfU6PwV1fwd6fj35IIjr3ejnd8GNRzu7s5NNoIil"
    b"zP0KEOSzjDkQ+FXYl1+mlyHVn+DOP4v2fzf3vw+eznzkclf4bCf2ZrGFfO8GH+6DHp2PPp1rXdQBUO8d0upY0Mu5IPlPsX0TOn0X"
    b"HvwuyODHXOV3Ruf+yethePAR6PSIWbYVaURLKngwpbQKiakHObYy1u0Z8Z7I895Y6wPwxd4JR55g7Cz48kK45EPo/cv11b6gp/M5"
    b"0d130GhfgrZfh7t+zae3svd3fLpf8ff7+OY/5bvfovP+hF74EzPxezTET9EQX+Porzs3H8eOfRLb/Hnm61J08ml4AMcZm9/Vbtlu"
    b"tHYRLJGmI4x7GZpnMXP+EtZxsb15t8CPtyJz13LnP0Vf/gz6/sys9k/gye/z/2d8ste3oM6nOOKK9DvsfUVP6Cdoueif/y4z8h1+"
    b"+0MQ6U/Quj/lF1cZ0f4vJPpXnOV/9QF/xee/4e+voO81vK7j3V/S6/ENb8EC3gqtQ+JfZlTr+LsaznwLPTkOF3QlM7mXXZIjseHn"
    b"+ozZy6Hq16DklVDmR1Dvz/BodGD+Ez13FzK8ECl+2Wc6vuK2HN4LZPMivPso7x+Hi5+An/8Fzf+aXAeVf8mZrky+CTU/iWY8k/Mf"
    b"gp0+gLndVemoTobtz1mM3DyLfnocPvkHdLvK7rcfQ4uvI2efQaN9Aiv+ifRipPqjyOInkOdLeF0IPS/g248ok5dA0Y+xfZXf/ITt"
    b"v6Hiz9L/Yf8PnPF/od2fRTE3IbP3QqF/gVxvBvf/E+v2KJR6Gnv9Ilj2DfTLSlef2pqGvtmK3S4kgb+r8RimQred0UkHYL8PhSsj"
    b"03UM0n1Ocjb3eB7W+2P8/zm9nS8j7VfCR5+HD8P3+TKc+S2++zqffBEb/zl49+P8/xHocwkc/WEodCHc9h6w6bvht1PsiD+Zax3K"
    b"a3evOY9tjmNoTHYAMdazP5JOYXwT6MdN6J3obxi3L6EXX7aP+3mN/SeQtufTF7ivh5C3yNO9wD2/AHc8wetBrFTwyuNa1fvxgh9h"
    b"Jv7N/7HO0d9BojfAUTdgd2+wk+D3bL+FmtdB379qY/4Ex/7ZSraboPqNvL8aKv+c7e8csZD3T0PvuOLjjGoxFH6Nsb2F9FcYZ5cd"
    b"Wt1Qd2e4Y1/u8Uju9iQk/tjkA1DiEmTxA9AqYhqXJ18BK31Tav4E6v03duP72JHoTPsO736ARP8MXP8/0P6/+f+7HPUF5PoK6P5l"
    b"dMZX0YyXI9lnc7ZToXH0ZByJ1ZuPrZkKfujE0jQkA2k/43oTei2BNxcy8rt43ezdX+Pre8rhN7nbL8Kt30R//gAu/DZc+zVk9xv6"
    b"cD/l7y+gzM/hv6vkv79Cn39A1Xug7t3Mwj1ojufgvDXQ5y1rCGMFvvVw3YiyugH73JisTWcyompQxVA6HS8hrHVj0oZGbwCHz0aW"
    b"dkNvhn84BdmaA2fsDKfMg2fm8U1wzQFs+6FRd8Wyzoeb9uCOD+H7dyZ78e4Qvj+C749g71C8u+iSOhSte0xyIHOwgM+P5tvwU4Lj"
    b"94Fee3Kevfhsd860J2PYj+vvDPVasDaVdDb2uorxjTLmCTT7UBod9yPM9jK8sZj5LaCQ8fR1OHMDUtYDFsnuOiRuHTphAlrUJOvS"
    b"YWTvrbQJzp7glz2cbyu/GwXlD7EFr/dDp03Qbxk89TqztZjXY/D6g7wegWvvg97xup7Xn/Wq/8zs/QmN+Rv2Io72B3Xm9fZW34U+"
    b"eASufYpZf4bZf4lzr9f/HoEr6uCOGdB7Z+59H5DmkbzOhUffr1X6LPtfgcNivbqPggn/k/+/Btd9W/77FJz5Jbjwe/DeleiH/0g+"
    b"DU9fisRfwO+i6vwkKP4OqL0b1JzNfHW7EkZVktFwCyNYDW02oqU2wS2vodEf5+9D6KvQXo/ZwfEv7v5u+Okp/r7G9gJ38RB7j/Kr"
    b"RRz1Mv8vNsa1BGq9zCzE36Uc8ap+5zL2wsd7iZl4kfuPbvmNnG0DemQxEvEc117O91v0A9cyU1vZH2ZmRxljGWkOK96El9PM2Ovh"
    b"ySY01Bz4Yk9otwP81wkXzWBvD6RtL77bXrS8G5/PhY9aXQVmBndex/fRSR2cFK8JOGHSyFx0dI5w3epkPXv9cldfOqkuGeL6Y8rM"
    b"1jTWDKiHisNp1Jt1MooGJWQOuCxkZVeuvCcIYxe4fjf4eQH7xzGuY5SHkxjdCXx6iL21Rxnp34/PD+RXB/P7Pfl/Gr+L+owYbVtS"
    b"yUc4CGeuhCrLoPNaKP8G9HsQ6t8u+r7FLbDQ9WjT29CZt8GN1/Lt1foJkWX4E5x4G9/eyVE3Ma+3gXMfNcZ2PzOwCH0UfZIxD8tc"
    b"yWKAv/3cdS/UmUROpqBPY1RtjK8FTp0Hxy7gPg/nDo5Ego/GqhyJjTlOu3UmOP8cuPA9VuhdxnaR1Sef5LiLeRf9su/g20O0RwvQ"
    b"ATsYPdsLKrRx5graKdaOqkZHleWHHrhkKXuL4aJVemgPM9ZX4NHV3MfrcOUL8NpLvt7kTjbwfg3cFnz1OhRchs1dI0+tS+MpWDXJ"
    b"qGtIDafN8EEDV6pOonO0w+xvPdRvVd9U8X+ROy7CNdHF2covGvjFOHzQw7ZVfbIyrU3WQK9RrjfB+DZAt+WMeb08/SZjjD7qLfne"
    b"G1b8vcVRa3m3Ho5fC73X8futvIbgvDH+Tzm+ivtP4cPRNOI4DeCsWuYh1jQKHq6AIIbTqXzaiO6egDvHeVcnt4fGjOjFbMY/G6qG"
    b"HdyB/yN/E1y5HzN3IDx4FLwYuOBE5usUtMY5oPuYu/PQQGeyvSc5gzk8wf/juGPVUQfAq/shZ9txzgaksjnpTdvxTQe5s6D9Y2Kf"
    b"f8FrD6AZ70Qf/je68Mr0j2Cwb8GfX8R+/QBEdbVeT2DUq0CrUbf+C5DAdWy3wKW3WPv+mJhijV1k0feToLkbuL8mEGcbEr4d49gH"
    b"+TuUvwcrVWeyvQt+OglLfDTcGCtCnZLf5RF8dhB7B3P/h0GHw6DLwfx6d2R3Blt4hrO0gTXcVx2z3ozMd0D9eq45ypX7oP8os1yF"
    b"nmhi/puSQO0NUGAqWyvSEvo1YjI1zMAYszIEbQq8GuCt6iS02ST8N4y2GYePQsuU4KIBzrmBd+u0Q2vTCdfg6JH7h/hmDNr2c/x6"
    b"zr+RK47zbQI3jDOeEiitkb8dnDl4IYE2wce1vFoYdzvfNXNsjGKU345xzbCda7neIs7yHFdZDoVH0BRlZm01NH8QDr0dmXsEaQvP"
    b"+Ck+uxvevY/jXsWerVMPrWCmBzhHr9w8yVabDDKiavmiE20829Uq9obCYedD/53qXLyH+bnY3u73aLXejXU7B0R2GTP2dY77Avrj"
    b"PFDusXx2qpwZ3HcWfHey/HcEejfqz+dxlRaltcCdxipPveain5MXX0JHRE39PdzFw2jDhVjnB9B+f4avfgV/XYdmvA+uu4e9/3Xl"
    b"snv4/wZw6m/53e9Fm4Gt/sHevXDy4+jah6TEUs73Once/vlqXmuYj9ADG9liNYyojA9u2h4eDcS0B9pugWuDRQ7oCLj0LO7rAvjx"
    b"g1Dicu74Q7w7Gat+OLb+FF4Xu87l/hwVNuQ0znQ4lNwFem7P/M6x470TanehiYr838O8rrRKezl6ZYne8HJm6AXt7UYQzGpt8irG"
    b"vZnvhtBJ/Xy+Ts4LG7cZ7hmAN2vglU626VA0JGEa12tC1muwUA1IXJfrljSz18x3Qf/4vhnOa0CHtiMjbZxnDD54ndEtgmNXq+OW"
    b"cL3IdT/NlZ4y7/QsI3yS8TzLTD0NLR9ne4YRv8bf1/ksMMXrevVL+X8Dn69Tl5aY1zHRwih3FasMhp0cUZ4GkNWRNFYC2KzFDpQ7"
    b"wl5oxribGcxLF3vb8/le/L8LmnAGuiFsUHivQe/D0H3vhOc+DI99nll5P57X2fDmJ9GDX8V6XYSPcCxbRDgv4e/Z8PCx/PI8+PEi"
    b"6HIAerKK+QqLMhXbMCVZil6PtRBXwT9PwnN3YbH/gWb8A5z2Yzjwh2jBH6IZv2G1+tdA/tGN+w180x/i1X8Pf+AbcOw3Ofrn1snd"
    b"jDZ9BN8h1vx7AMo8JBbu4b63GBOuc3Z2EbkfgPQdwd/juZvT0JGnM9KTlcDoIY8IyOlGJY5iOwbOO5WRnwavHsdd7M+nO4vsd+IM"
    b"sfrINLhwGvw3FfpNY95nIO3TxUO1ckAt9rOW61fxXejp0IQ1fJIyIxEpmLBvcww+CT+tF54bwcqVmMmUuW2CZ5pB6H28WyIH9elz"
    b"hm0NSxmrE62Hx4MPViPrq7jvFXy7RgSf5WbGPVuJ62yF8gOcLzi6G008ixFEv2ho9wLjC53cwsgKSWCBOqQo+GgIKeqFjlGztiyN"
    b"mOtTXPNZXm+hDTaiIcOvvxNp+iefPWSX1lPMwjPMxqOM+lG4cxFYZQX/r2GEkcPsY0ThvUy6auZsqBU4db4+eHDd6dD4XGbkrOR9"
    b"dvy/F/m/hP8vsc/hc2yxDsp/oA0/bGT/P4xZXcBxZzJ/J8KXx3KeY1yhaS5zN4fX/NySZfQuqRs3MJrX06i3fJXRPczd3Y583YWG"
    b"fxz8+DSeyz1ov7/wSXg3d+LP3Gq07Va8m+tcOe9GY3z3YrHv4fM/8/vf8O73aMa/ohf/ya8f4tePQYXHoNNTXOVVXuuMf2xEaoeg"
    b"QsUup0b4sxX0Pl+/cTd48hAoEEjjIrgwVtN4P38/gI34MBbiYihxAT7RBWjLD4goY7WNM3l/LHx7KFwbkfojrPmZm2vJbs5fBxUm"
    b"meEh9NwmtPR6ZnGAkQ2pEZejbdYrl4v0Wl5m71nXr1vL3C2Gl16QuzagXdZDwwG2MWxmibsoyNkNooTGJLujjiSQSZ3dyK28YlWE"
    b"hM+DA5uSYRH9Fn67zlXo1rKtQ2tvhrsjsxgc9pp/n3K1mbsYcfQDrQUNbYXKS/XR1kLZNYzwTd6/wu9fZWQrXJtmFUdtSqO6O1BD"
    b"XGGScZfSsPtV8nmN2CRiZU2MLrPSjXBJrD62GzJ7EJ/uyJy0QNUu5mMfUNExzM9RUHYBcxP9P4GrPuB2FnNwMTrkEv7PePYiPo2Z"
    b"u5SjPsT3Z8GdR8PZsUpOdIwdgDaJNSJ3yqk1Ai3DDx3gzt6QI5/V0t7hWik3pT9F2/0S1Pj79Ap7eWIFq88Y/YxnX3wh/Wr6XVBk"
    b"rPAX0fMfw69XG5n7i+v0/gtejFzTi9Boufpio3i6wNXTdD402J677tYDOcTq+BPNFBzPmM9Cns52LbdY5yNk7BS47QRXdjlJLXqw"
    b"HnYcvxu/2As7cgi8fBjn2g+qzQP1zEa6t4MbY92uXdCS0/m+0Xufyud1fNMIlTvknbCg9daz1ItmYr4mcr4dY+STWukecWAgnFXM"
    b"/Hruaj17y/j7Bv/HykiRGwyeWsqxr8BZK+CX6NHr0172ycm9/D7WpEnQkJNiySr26pOoQptQT/WDA/r5fpjvJtJAnOuMj4SuXarf"
    b"sgReex6uexXqroTKK7FHr8GrT/D9nYzkHj5/CY2wBs3wir5aoPil/F3COFZxjkGrtMbN/jZw1zOSqEnYyZxboJ1D4cbT2Y9V8s7B"
    b"Xp0Hb8Wqeu8HIV2KVoh1Pi83FvwZ3n2M/YvQj+fxXRbTj1WmjmbWTjD+tK+x/znw8mxoPhcKdysRVeCEBBvdJ9XWMNKotnwJnfCU"
    b"fvbjaPaom4hVrCJ2ebfrZcSqUDfocccKUX/AEv/RaNCf4Lzg22vgv2t5dyfaMXzueEpL+OgP8nmc8QGu8aixpSVcb6X+fWQdQz82"
    b"68lFvGMntn2Rx1gza1+jQ0cifycgh++GMu+HKrGW3IXc/fut0LqY/y9FI34EC3Ee78ITPxuOPRMKHqW3fYjrmR2a7GTktws6d8OD"
    b"3XrAgf6CB4Zcfa7sKgq9zHhYwvBXgzrrtcMrtL+r+HYdx2zxNcznMfp+bHAfdB2HbxK4qYjGq1YDVyUlvZXoTugHpYTnU8Qbr002"
    b"wFvj8PI419goV6+Vn5dwpaDQq8zGK3DP02jpp/j7PPMR6xU+a27+efZeEo8/LuJfqP5cyRnC7ixli1X1wvZt5ToR7xuU68NjqOG+"
    b"a/WVuo19t4NptnMlm4ghzbOiNTzMfaDWgfrOx8BFhzEHB0DXo6Hqmcj+CeqIC6XzJXx6Gd9FDO8c3sUTFE6CMy9i78PGh98HT58H"
    b"ujoEnt6RI/fSO5jO/zO4+hR0b4xpTCSyRsu5BJl+Spt6J/z3DzjperjsD2Zs/gdf+udowCvRj1+0N/zLaM2IIf8A7Rj94j/GXv8Q"
    b"W/0/8OL18OnfjL9Hz+4T0PQRaLPQ+Gmgns1QZEsaHfoxjg7rPXeBArsYl90HCuyLZB7AfQcnHc3f0/W3IwZ0JhQ62yjvKWjU6KN/"
    b"h38P0Cc/Sh15MvQ8jNdBWoMDzQ7vyf8HmA3bw7jSTPZ2cI3DmcxBxPamuz7mdszQHLRmSxJYbodkE1KS4bzwutYb0+xRz22AiyL2"
    b"87I+w1I+Wcjnj5izCPl+Gqo+wrGPGyN6gu8e04tbKCoIe/wcnLIUPuyFqzZy5FJ4JjRuH8cPOCublYmIloV2fUu/aw08t5YrhFZ8"
    b"jW/Ckj/H3uvM3lvqyBe06w+ZQQkdvZhfvyTO3OR1hpmFCbgz8PEEc9DJPe8LNxwCJ+4KDedDwQXQNKzRu9AD72e7DM57H37KGcmV"
    b"yPvHzbF/i8++6Aqkl+K7fAiNcDnHf4bffRjLdjqceSxceQSv4Oq9oPNOzHL467FGX5KEFxtx0E1ajMBJq6DMKld8ehYt9hy6cKGr"
    b"/NwCR96GP3IbWu4GODNqKe6E7+40Kn6jGZzfGZH8q2sBXmM28Vfow1g3+y6Ovpf3/+Cct/PZY0abn+S8r3H+N4wehwT0Q9vxtF+v"
    b"chS6BK7KosAz2PZ0taz9zDKcxt55+jIRM/g4d/h56PUx5fHjIJHLoFFEHf7Db0+DVhdx9Ifh2LPk2+N5F3waa/vtB+cdgpbcAdq0"
    b"JtPs5ZyP7upIwreYkayAA9dqo7cYByziuUSGrwc+igjq5tyTiHjqqJ8M6m+vZZ5jva4Rti2uVDfE3jojlQPy2QZ4I7ZVUP4V6P88"
    b"nPoivLMMy7ESWr2g57EYT/IZPZDHzLk9CgWfwvJGfilWq7uP39yX5y9eNMb/HLyY8eZyo5ErHFG/mCCeaBHPfZhIW4yBzobK84wi"
    b"bg9C3BkOyeLbOyPr20OhQIbhV56Ltnwf/58FNUMLHgunnWeU9xwk/2J79850uxi6v0ct+FE15LlGds41wnMCXHky9D+Da7wLvXgs"
    b"Z92FOWiFQxvh/sDYjUbt+6BYZHci5/cKd7YQfrknvR+Oi3rbiN/8Hi77LVrwGtfH+A6a8EfpV8CHXwElfhus+F0++YY58R+hE6+E"
    b"Z38Ah8YqqXdgw++Qo8NLfwoN8ghUeppZCjnP5jmz0BGjDq6I6H8g5U7jM/sx4n3M5EZ+K3JeZ0Cx87mHU5G3I7nH43mdxv6x6Mp3"
    b"cqfH8O54o2LHi6/fY442fKF3KenHWn+0N5/EequHQ53oyY6V5w7h/71cOzhWgd0LTb2DOc/I5U0zBhV5jhqxfz9c12cWcIXRkz6p"
    b"t9l+tkXmuSIa84pebuT3X+W+X7DmMRBdxANfgosWctx9WtiI1Dxg9udhzvQwPPYmVNsC4o4c10Nc6Vau8QBnfo3fr+BMb7h205Ps"
    b"P86xz/uLJ+D8hXDiEmM8S9hbyZV72La4GssQPFoFNqsXj9aA2bpAipE1n2uvxHTpEDnEBa5I+0H2P2AM+2K2y+GwwIifRtY/q16M"
    b"tfM+zWdfgQe/yZFfgg8/klwB534BnrwMVHUa5ziIbU/m4iBm8miueJRrfc5wDd5K2uhKA6NK9jqzDCFRi9NYU+kZ+PB5qzbuhY8W"
    b"ou/ug6uuFx1GhPHPcOPf4csb7Ju5hu+vS3/iJ9fyPtZ4vRqrfjN7t4sn7+LdPejP2/LV0h61OvYhrrHIbOIirU7g+61QO3KK1Uaa"
    b"W3jNBk1HTuxAV1xZwL0cx99TXK3yaDgyYrAXQKsPi1LOUy9ewp1HJcwH89f5WI8z3M7ndTLHHwetjpWTj4QukcfaE/u0wJjXPGi0"
    b"nzmxWfDd7ujKyN9Opt1gmYgFVcOJEfkO5BUrkYW1GxX19os335Smr/H9EjMoK62beI291838hMVcKJ8+Kwp8Ah59Gq57FiSzUGx9"
    b"D1S63xztrfqQd5gdux4+jJqDe6Dvo9D+YVc5foCjHoAXIx73rNHsh/X9I577IiOLCGkPsp8wzvDFJtMWs0Td3NP2osTdoPECZC5y"
    b"DwfqYUQM4iRt88nw0slmYs+Ax06E506HwhehJz8BzT/PHHwaSn8A+/xevZkLjWpcCIeeha06h733snch8v9eaHyGuuRUsdfB5gvn"
    b"mvsMWtebRe6Dwj3M/xbjTRm1XuaOIjYVd36jK6+F3f2r60P+Dt332/Sb9n58z9qC76kXv8vn3xc7/thVob/Pkb9g+701GpFVjBWe"
    b"b81z2lH3EToj8m392q7Nafirw9CqL52LZx+RriZ0U71rru+pxtoH3jgc6p3A++O5lyP0us9mO4d7PRUZPBEaRZX/MVaynita/gjv"
    b"LuSo0/h7CpQ9zSz3GfwN7zAqL0KrHgedj+DMxzMzJ3HNd2rFD4Jyu3O1mLE90ZPz0BydRocaGF0d2rw1iVqAAeg3hubZCg+sF/lF"
    b"tfwSOCQ6yN6ES+KO7+fvI/DOvXDdzXwXnPYk0roQutzOMX+D5rfz6b3I7f3mse5Akh+BBxdqWx7nsyfsG38MHnyI9/fZvxKZhfvh"
    b"vSeQ7RfZXmaLbOYKUdBGpWKVOaHwm6MmcNSVaBMo24DszeKudoMzot7lANeVPxlanOKTMMIWv8/YzCVw2+XW534Czfef9tNE9dCX"
    b"0YGfcbX6r/L/J/n0stzDfp/YMbTB8fDsQZzpMGzPUVD0QLBAaMYdjQPXGvPdDIJYp2+/HL6ICoDwpp+UW+KOb7MO6O9mWm7HW45n"
    b"84Xm+w2va62sutp6mKutA/qFGjIqLH7JL78F1X5qPdzP4O2rrKC5iTPd7gq4D6ABortzMVdapge43E7PxUb+tiLJ/cxx5JWb0Y1R"
    b"7TIF+Qk53tWcaNShhAwfBFdFRvts89VHwnmnG3s4g71zoEPUDp2PljxPr+5cjjkb+saqv2dpQc7Qyod3eKJ+0EHQ6gB08OFGNeZZ"
    b"hTrNtVJnGKUMi90Enm1TvxTNNodnPIJOHEamhxn9uKvDr7F34xXoGnmRFfZqRY5uFXcedvtmjvgb1uEhaPUcNH4MSt2H7D+Ux2av"
    b"5ZNfm/e6Tcrd4iquv4fjfgM9w698kmOe5vP7rd96zGrjZ3JU8IIR0pVv1wgETSv8bUZumvK1GFu4qy6rGveFE/c293AU93sMPBOd"
    b"toFsTodCZ4v73gfFLrXS7WIo+gm2S9CG56Eb38cnn+bIL4EaP2YkMdai+SyS/UF+d4r5mfeibd/lauIHm9HdiWvEc6dmwo+Rm2hD"
    b"KtqhYqt1bFnkbAn0ewHavWId44PwzNPQ4AlocSP3ezXU+K1VfbEu6TXGEq/i9Tv05O/4Pzjz12zRZ/87aHqNlWl/g5Y3woP/1EaH"
    b"XnjeXOkj8P0KrlFCJ/RBs5fBMa/ChRHNa7KWKbIjHfLiTHN6s60jmZdz5J7Wh4TO35+7jXjYsfw9Lq+2OF1seB6fnC+3vds4+AlQ"
    b"6kzencH/J1nfehzfvNN6oKN4F9750fm59rQKa3fONdM1BHZAN0/l+jOh3iwjkt1Y7Q5sX4pMR15pnTUhgcuijn8pWvENq1JeVVe9"
    b"zn0uMk7xDPf+ENru31qgO9i7i/14usC9/L3V2pPb4KnrOPJOefUGjw47HpnWp90LX/AlEc9T0jJwaOCsJVb8LeX1qlp6LXP6GmNc"
    b"jqRU0swnC70+kO7oMxFmouH3Rt/Pt1LonXDnQeZcTjIqfaKW4xwoFjX+Z8F/8fymi3h3BTT+LLJ+AbrwNHTiRXJmfHs+PHuxXvR5"
    b"0P5MznAYvz+Qs0b3+0HWE8wXD80x1hu5gKhoKagdV9i5EfmQl8xshg0NhP06d/281uI5eOoROOoO7cj1xh2vhxK/YfujlZM36m1H"
    b"bubuvP70bj6/jbNc78oFjyPB90Ddf0PlJ4yYxXqoQbk3uM4q7Mo682ixdnPUA/Qb8603iz6VbRrjboYj2riL7eHL3bmfna1Vikjk"
    b"AdxpeCT7cOeHm80+EC47gk8iDxX67zikNPycs42dHyX/hY9zolUYZxgz2tcI0YGuD3u8Z94bzt/XLHdWrzIf6ZjPSKYk00U5zVAx"
    b"MtNREbY+bZcfR7iDMlQcgweHoeg67u5JPr0T+j7KfS9nbw2UfQmKPghF/umavMFnwWM3yot3qP0e4Mg7+XuL0d77od1d0PE2V619"
    b"UuvyIntv4uO8YoffSjXvYugZkZyVzmm/3BirC9SidbLajMjHhi4Kf3oP/t+Fe+qGY6Yb+9rXGqhDkcXDkM0TjCgeI/45Wyk+x+3d"
    b"vAt9eSL8ebT68GT2DkRnHgqOP5u/H9ADD9k+Ns+E7QWVDzQbGLhgDtfcEcuyHaNowZcpG4FNGXFEbnuMmG2GR1brU7+hN/OCFvVJ"
    b"aLAIfotVof7G59dBrYj33Mu7e6w+/ZeRnODS6KGI7Pa98OOD7IU/dJNZxqgXvBsa3W1MLGoTYrXz140ob7S2Z9BoSGQaAomNW20z"
    b"BX+hU1zRxdij6mFO7v3tBD139RkMB3FPR/B/1NPFeg67wml7W2N/iNb8tLzaP+xxxCOPMUZ0pvHLszjyPaL3qEY9BYod4WzsJ27c"
    b"g1/vCB3jKvNFjeHrT0Ouwwutgx/rmNskiXruMVDGVuN3G+2fXm0leo+5j9Vwy2oot8goTOT2HrJG6k701o189m8rK29EVu/Sy7sb"
    b"Sj9ivUlQMLThk/ziQc4ScZ7n9Vmidm+pa1lE7cQyrfMbxixXG018Kw0UtppRZasL9IDJI88TVbRzrezoQrJ25n0WQwtkvhfUOES7"
    b"kNXqHCsVz3A7EaoFJgpsfg70+iCc+h548gi48TD9nMN8/te7+PxIoxWhHyI+tJ81qPtyrZ3Ny0Zuuotrtmpjoi6jjLT0m4MahIKR"
    b"n13tU4iW5yjnNfMxr2gFApE8C4We0YN7Cj5cCI3u4fPb2e7kmH/Bn/eK0u/SPwzZfQqaPWe1xOsc+5bxxdf4dC3UX8Z1Mvl9A2mI"
    b"mG+P8bq30niiYUT6xuDFDfixvWmzo51uPUETcjTTuvl2nwLWbUZlb7hzJ2sk9zE6E08p3E1pDIwSEYUFcGpU5r4DSkXN2mFGzxew"
    b"HWqE52D4NY45RLsfufE9RAIR8ZnFNo1rRERuT669F5y4g7VGLWZ0U6RlgG2rnvagtT2j3GWf2ZqIqyzWaj+P3EXdyAPc+UJoGZHE"
    b"sD+vQb2nfd7JS7x7ygrToN8j1pk8Ad1i1bCHfKpnxIYeZlYe4LxPy+H3csYnxATPWuPTx1miMuxNn2lU4pqRx4watmGfLjQANqtB"
    b"uqdwF53GdaIbpt1V83YTQYZcHwnVDpMqh0Gt40R9Bxone5eI8kyjjgfChwcZSwxduDdW5zBXf1hgxfnhUvNgOTzLqO2o/ugUc1Xx"
    b"rmDkewtzG7GyOma+BhvTA/Ve17ddCd2WsL1gd07EUTM8cj80C7SzFPldAfUegSJ/5+hb+PYJqBrVFS9bIRKxspehZnh2C/nVi9qO"
    b"l8Tyb7gu/hL4Lrixj3MM6oPGquljfLolLVkfOCDGGUwL5tHiyVGJ9TbVcF5RjzYQeJPcOE1tFRmU+f49GP21wC6dyK8ewd0vgCYH"
    b"GLE8wjrlfaBScNvxVgyF1xxHHWl+ah/e7a/PN9/uhr3gu4g97urzJw5gHAcyjum8m0h3tf8i6mpDP6Zp9C7GmHuh7GbjKoHF3+Be"
    b"XjVb8xx3/IxYaCHvHoRXQ0suR1KXQcNHfVrAMxx7K9+Ex/wWeGcte4/BWbdzTNRIvJTnJhZZoficK3dH3U50bUcmcBPzMey23Ez6"
    b"K6Cdpdi/qPapYXRR6VybRCVlMyMPeZpiD/Vu7O/I38hKzRHb7as3d4D56YOtzjsLSpysvTmLd+dBmzOMPJwLN58Pxx2FZdkRjp3v"
    b"OiCBduYzB7typsirRa/2PtZfdLuGQJurHVRZITECP2605ngzUrOBme8z9t1jfuBNa0BeN0O6hDt909r8hVqYx6xHCgkNDL0YGoX2"
    b"vM9q73gO5jPSLKuNeFaezmzyKvbftP8hKmDW8oqowzDWZIs6sTqJmGwv9jlNo3prCzpxkBGW02rXk+gyNl5h/putD2xU0wcOnmMF"
    b"xDzoupO+zh58E3Vl2ynpe9rbuJsVJ3vKYYdAqX2MMRxkhupga9Bib3/3duDzuWLGOXzXwSczeb+7Verh/+2AZMxzFHPwubZjhPXs"
    b"D6FzhqzgGTKjFK8eew+2yBmrjY5HTvAFq2se5bOnpe8iP3nGnpAnODZk/mk/e4o5eFoU/7I5/dc49k19lKh9etPe2BeYwSX2UT0N"
    b"/R7n2mv5vCFZaDXQW9a6hV7cmLYla/AP4+lvocdn81nU2LWZpd+duwg5i2xMC5LZKFV2gJt24P4P4s4PMZ93pH2OIdHvNBcRfXLv"
    b"NP9/qH8P4hf7GrlcALUPsO9mX+h0gH1889QdU5yvdjsoo7KvwQ7uGiufNyg5axjxEmj5OrRbh5T1KslPWR2ymG8fg3Oek8OegbNe"
    b"1AeJ7Xm7oF5ib5E5hOgfCRu/zKq51839hz5cmqPDFXYxrdaKDWhF+u3/6XXtgBhFVAk2JivxVnvQM1G3ErLTxtZp5VV4DtPZuq21"
    b"mcodRa5/ljZnR2i7K3vxdJSu/Il622u/ow9pB/lxvvHDHeDG7c2BzYJ20/h2F2PAU6DdDny2P2fahzPP4ugWe1BmWVs1ky3iPE1W"
    b"y0bf32gaT6uKSqyoTxyCmmNmaCbNAQ/6hIul6Pw3+SxyDP1QaQRqhUwuEllGfHwR9Ig6vuVqgDet6ounbKxmbzHHPqnue8aa2xXQ"
    b"7XEk+CmRVfTeLLEWcKt+01Lj8Ivhx+ehZnQlpBxVAzVTKzPLPt03KturrbaeYl1wILioYdoR2k6FKq1wXvDOO7jPg+DR+VqL/fJI"
    b"YVSR7mV91Dvde0feObY3dNstj9DuKhLd1U7nwFFz7Y5q4bsm9ETUqmwHF043hhfeap2R+aIUjCr6MqOOPvkRNVfEBQahXJ+oZxlU"
    b"WWMONeIVr/D/Qrg26o/fhFM3ItPLzOQEjn4pzy5u4NeZnt1oHcEGaL3FOtQ+UdUWKJX19pWsvo1MaiLW3mDHxjD6cC06fCSN3FXk"
    b"jMfTJmtOpzP/M81jT/EJZnVyyhR7Bru465nG0VrUZVkn3h7WYsxVc07V9s6F29rQAHHkbsxFZEuDS6dZ5TTDp3buCBVr+CaRxxv5"
    b"Jk13sttvWhK10fHkpk7GEhG8ydxjHXHma9Dyfcz5q9xJoOIxqFOCLnHfr5mhWW19xRao1QPNgkaL5KmQ21fhzTXG26IKNuqqeqXn"
    b"W1YPrYXWvT6ncgtHD+s5r4YX14tXX2cMUfM7aE39myKejWms9BR1O9FxUba6KHKbHUl0qka1xAy5YlYSa4kEp0R+ZB5UmmKv2J5i"
    b"yh3FfnOV6720PhmWCd13pM9v3RPuOpFfH2Ht/gKffhlYcT5/O5XrsGChG5utfZ5hVjKFfokVoSOMplfvP3pVRvUHx6FGIVnsagPR"
    b"4f2i6CcQ5Zva2lfYXwUVN8J90U3/qvVPy1xvZpmRw6jtDLy02Hrnta7qMgadytAwOtbeZLaW8i64sip5K52w3iBybCV7qApJ1PGV"
    b"pV8tYwy5qRiF7LIquwppiudOdBjFbTCjMNutDQqE372b0Ytm9dxUIzO76TuGbE63eilyPKEP5utXBpYJGzVfnt4R/t7F3r3pZvOj"
    b"4zTqY4P3p9in0myUpMD/Bb5NoeKkddnRWbNGm92PVC1P20HmgT+itnU5nPkKvLKRuy7aabDcGuPF0P5Ve2deTSvSLOojx+1AiIjh"
    b"BHw6rEaYwD4lSdQybubYFO0wKcUHjSittnpjo32hfUr6VlcWiD7BzUr6RuxMr0h8zE7FxNr7ClYnKssjAz8dKrbKlZGrm+0zLA+E"
    b"5u/grqNrMU2P592hyv1+dtfNlIY78D6e7LqX/Y4h3Xtrp6aqAWJFg3a2NiO108SMU7nGTGWgEymOKF70H0RX0phPV+6zn3HESvmQ"
    b"7KBF1B9v4hVV9eusgIyOuYgevAKFnuGo5Uj4gLy5Wnldx/cD2ouoWg7/JKpqN0rBHp9gW+L3Az6FqR6LXJdstqJpC9y2ltnbZBdb"
    b"9FINu1djX90QIy0bnQi0E31tiRWxsTJCQQ5p4110+nRYr9hoF0oDlIknWjXahxIeZAvvGqBQq6sptkLDbtFn1DfvwLE7ynXRvzmX"
    b"4+vg0BRk2GqlfMG8dbfXrJcvRxlLKQ3kE1p7Mo3Ou8C9Mdsl3vVbTbwV3gsMss4I0GakbBl3/aq1jYGTYi+871GoO+5z16KifEy+"
    b"Cq4a1CeKTzeZC4+ulh77Pjc7W0G/eGp51K4nnHNQK1eErr1I+HKovFGvcEMaK2hFPWutNa3BnTOwhTOTOK4eGmfRtEn7HLuMX0V9"
    b"WbfxgzZr63ZWRrfn0725652gyBSlfg+1QFQu7ym+Di4MCu7qU4kD4YS9ilVBOp2ZmJF6Zythi6qELC4xloZkb0aSt6Sp+LssZfq4"
    b"zwHvfK1VUWEFltnjs8FoUNB1jbioxz7/oNJ6q6xiHaTl3O0qzpb1WayDBm8il29wpXV2g6zj3TKuuYp5Cb0cnaAVOLIearaw1SfD"
    b"Vpb1arNL9us3WH/dyrGdyXi+zlJTklUqN1mFWJdnmBrkl2xFsHYtUBUUDCvUYmanysrFDi3FPLlrGtZqd868g50ys+CxWdKpTh3c"
    b"YldBs91DZdBhVPE0uF5N1CE0WkVbNH47xkyHHayIz8bhiaimnkijVzHRgygaCeq3onDUfGLZiu7I0ve7TkoljV6tcTsQ+6z4KyKn"
    b"8UTqkjMRMbCQ4+iOHpcHwyJHzWVYldXqlPX6ppGvXM+sDjCjVXoI0WUYNebRZR/UrbMzq9YKui3QNWxlII4p3En03VZARSW7WGuT"
    b"kLx5STzPs0H+bBS1R4Zxuno06NbIfksSuYpO88+xVsDOasE2Oxuy3NpU6L4j15oP53dK3Xa7eye1fa1JINuodxxPmx1j0KGJ+4uu"
    b"8CH7J9YZD4qqnxXsBR7ZKObr0xsvKde9xguXStewRqv5fKsVYym/T5KgStAx6jQq6o9RKRToNWixgW+yyomodQpPsCWJSpngzYjZ"
    b"NqkrIzOcSdJkGrmQXjhnSPyzJd0RuepMIqq/nRSusQs0EeHVu9Uaba23+6NWOkR+LPzMuGIgqenWbAxy1ug0ju6peMZwxDvbOFOz"
    b"nQldfDKHLSRgJO3m6EZxT3zebHVUk3sRbQ68USX6LafBrX1wbVSIF60yXstZQ5vVJNFnX4EatUl0rHTyzTT5Jrim076E6LYOSzbK"
    b"+7cY9UaPjT7aQb4dltND3pvYoh9ygGuu4WorrS8fMzI/Yq6jYuVlGUQVqxfVMZ4t1g+Hl9Njp3/Eo3ug4FalLaxUYxJjDgQ/j9F0"
    b"QdcyNEisCk3TWfrHc7QgUXs14218E6sazkVaZ2nNZjHieWzTrDtpggeLSacRstmMcb7x5dA9Uxh/PPd9XIvTwzgjLxIx/Cb922HX"
    b"rAgOGrHjLaQxfKCIYq2FSiG/Y2lo2dWMPOrIazlDMSml23rtIgsdKLAHCo3wPnRyvRixYv1Oo33WwcFTsDBTkuhIL6i9J9OsEzqy"
    b"hWEDE1dYbklGnK0haDOYY+E6u1jq1VmR+2yBv6LzKLErOfqjS9xZ2Yq6Zu1srOAzi9ndLgm/o5lrtPF5Km9MWPkbvWOJ1ngL8zOo"
    b"fGyFI3rsg434bYud2lOh50y+abHfsCB/F/UWG4xh1OXVhIMcNZZG7Dy0wWQaCLSdM3Q5/g7r4It6awN27pWMD3foKUUt4Jh1if3M"
    b"6Dr7xEuuDBBP4421K/r0SjN9G738m9JAPuv5finj6HHNiRX6CmF/+rWGPdbx9WrfJ+0ICV4dEHMEt28Rv0dfxZhyNGpNS9B9q7Yi"
    b"qqMjxpUo4Q0i6lo99jHjcq1GIDp8Wman1ia8lzlmNeqNfCYcG11zbfy+UT05TR0RdqjZ6uCy+rLaiFro8PE0sbe8Wkkf965r9ILC"
    b"8sToaxx3vzZ/LJ20iy6VGydciSXTEnX2xQflUiPctUa5o/qz06hT6MqCvJSqp+tE3EU7S1rs9owoUFTodut1b1Z+Ey15tTGhreLO"
    b"yNdVRKWTrsY0pv0c1pJuNa8cubJRdUnwVqZpGtVe4+qrYbkx+DK6+SM/FDIUmeltXS7VrgUQVY+pUjzmWKr9PvyuBusqQsYajaxU"
    b"yZE1PuF+KuePGRpL53LfEe2I2P4k91elvmhzTkPzhF2M3pXEjsMGa4jaXbeiWrRSZy9J0bOPwd293NmQ1Nhs1HvYtU4CPa5iVMuM"
    b"6q1mVC9zD6vNxm3D8wP2FPby/6DZiM3ihfF0yK7IVE6NtQkyb63M+6lcI6xG2fe1YphWuw+Lrq3RksceUmWsw8hSvda+xq3ZrcCx"
    b"qb+rlvvatEw14qFU+R/TNobnVUprpHZBndTm+gwxwy1G2cblrRrOEb+uyLstrugRWi3QVOiHsnNZK880yJMTdgol/j+hvR42N51x"
    b"Uqr27PddtXyVyLkjuX6MruJ4TkzU5fa5SkRoxzGtS5uYLRtRqoZPlemy6L3s/pBcW2ssKdZvak4Cs0WkqUotEzOQitzGmIcqq1XD"
    b"+5pQb4zaAVrQvmZ8P+GKNpkerVK3NRohzdY4CY1RZ39ohzHnJl/tfN4pNg0LNssjIhrdbQ/1VHvp4rczucZ2ni00Z7cYtV5ZjXuM"
    b"9TBCh4TOjE79VGyeZbMG7XIcMbozIlYNdBl2bJMYaa3RnzHXQixpy0Obxj1meZHww2IvchSxHkDkJSb00sM+hG6KqyXOX8GVVEpK"
    b"dZWykVmpDGl3KH+RDWxVlurF+DXi/BZ5ts2oz7j2PxBo9CKNqVdTV3Urat8CbU24Rkvoy0m1R7OeeNjnsF3BoSug0kZX5ujNkVFZ"
    b"qhSSeL7xsLwcembCOS+qZeIOq9QnE0ZIRrVyUSMRzxzu04aV0qh8a3LlkaIyErxWI2KLMdXn/FbRm61orSppSd4t2fdZsBtkPOeh"
    b"Udf1HBJLNUPbslHi2ItRxTpBgSJq1fmj6biorNpzBeqYNKYY0pGq2YPfy2n4Npvt0A9LNQhN+vkk7rNZWaxVSmKtnYYcf9aaU6xl"
    b"LrI++kb2ApXVOE8deY1QcGR0+Lfbh91ovKCAtqwxO1rr/LWoh5KkwXrLmlxXZxQOyR90tbBaa9QnzXqt1ZKvVRsG5y1ztZbN9i1G"
    b"DqLfmtf+3JMfEGdulEMH0knrOGNOQ/tPuPZLtfnG0DtJvl5Cg//XW9HdomZMrHqpdz2XTr8PjzNiFOW03T7hVnF9vX3doR07pVlZ"
    b"6o2nnVbQjKjhMstZpUwOw4OjRtiKWtAq16QJGhTM1tYaJ9jqbJREn132hmZ6qaKfmfWVlFyFJjFqnMnXhJa0TgRbUtsMy78l+Tnz"
    b"CIILa+XexOtVaR9CI4Tn0C1uq+IMM+CxKXoOU0XB4Wt2MZrGpCKPjYsFo1qoTtmJ1XSq7VsOHhzPV4obTMdzb3dIT3dM3BG5gnI6"
    b"KGeWHHPRu6313ipqhmoxY410LjOGMrRtMKYX0eZaOauYrzIwK99rNDsxwyxPPfPVKfpP4MZ27XUgp4hwTZG/Z1gDEVQPCz2sLh4E"
    b"by3D6kdcpJW9KXBiyGiPSHHCOEch6RFV9updRqQp7jDscWDMDVBgrXmIsMyrlNphfdTw/zdprfv1J+K+A4sFbZJcXkfVz7VGPSb0"
    b"OTOr2yRurtN3bBaBdNo7GzhxqlGRaXoyNXZoJsZBwg8vms1u0RfNOLfKY0r6OV3yTrZaS5/17JvVBJPGtdqSsGzVWsDhvDOy5Pgz"
    b"1FbJ8VtBmzai9gmvI9B6PG04rHO72DERs09aMVGrNZq0Nm9E3B4IoujKeI2MqU0cGZQOrV1vJKXGarmCHkaPXc19eWSlZFwkLFXg"
    b"gJCIXjVhjKJgrjnLWMQI+4wXN/BpnGEyR7mDIpSm3C4XrCeLDooutWatY2swBhD3OIM76zZa2mzeJmoWwmuJVXuK8lxk3wtJhvS7"
    b"nK2wYBHxa9d+tdhdHhm8gjPXoIaZIvpsUZe0GnnKdMiAPtOA6LFKhFzrqomB/0asS6mkm+XEpVBkhXpylfW48ZzvPruK+12VYpP+"
    b"96CcOiKSHLPze8ye82x+x5XjSaWxSi+joHasdj2Zdm1uo1ixJo+WNYh7sxxClTXL0XOSaKOnejftrvbSpA9aI9YcNwYa50xFpmU1"
    b"TlR1bcZLGjTmOwClY2WzQEp1SbZm65CRwAGkcx382m//+AhzOqxdrhOtZbUkI/lMj4h0SurFUWWsnPseJRFcIJWwz+PmjSL6U5v7"
    b"1ZO5ba5oQ+vtOxzS5wm90OtqdNViyUYt5zBH1xgl6dMr7/M3Zb2xco6zQtoDOxbUkoNy5bBVoInHjrsSVEmfbFTuzGrz2rTnwd9T"
    b"jfeETExTduq0rRFHKprxqFbau5mPbFWo8CW7naF2kWSL3Ngklmpy9pqSRvmu6HyGVz5s/iQ0xbBRzzFt1ajxuQb1ddGV2DYbtyha"
    b"6ZYY8+4zklnONWTJddOqXB+q11U0Jlz3smSMOGLMY1rwDEWutbe0zwqX5mSt5x2WLyf1Vgdc563J+U1dE3LICoMWdWMici6ae5ku"
    b"PqkTOUaOtVrr3eo9t6gJG0UrHcZ52zwm8bgG10SZyyxOT2LWZ6PZ57qmWhO070qGjGaUci+5IKKq5CstTOarGoyI8EtGdyIuWOUa"
    b"F13Geib8PPNcs9hNOV+dofC2JQ49OGpOpi6PivbrNQZSCk3Vq4dUFiUWtekDub6LeH5keUJrlvRKEiv9JvUSI1LVYPy9bCy0N7fY"
    b"gSj6xIIx0h50V1ROR01Hh5G/8H+65PUsFpr5e+FTtanVp/Ob7fS3mq2Gy/5GNHIX7n5aEpKxi5HSer6ZaVy9zSqCKuPD1foyHWqI"
    b"ZnmwXaw1VX3TKPaqtstqSK98EOS/WZQ95Gpn4SGWlegR/ZlN3P8a0fQqRvmGvLqev1mUOPRfthLSWq1w8OZqO5SyvNyw/ni/x06m"
    b"W/MYUFCo3hhKSfwU8ZVEa1ZlVC2sQavyGB5d1Je0u3bhHKkUcdPZbFNcE7DD+v5YXaBGGx76MpBno5HhdiNG2SqCFTPDjdr9Br32"
    b"ydwTz+xDjRH1mI86I2URd8qQTEXvt5GrR9QjsNSEtrnekZfTzOpVWzddY/VGxZWhho0XjbnCYdC0pOxVtLFF+LAOjqgYPW7T3k64"
    b"XkqP3vuY34bdGJZCqdxXa1xnwshmyfOmYvFhtXLY115HUFLCU3XChF510bzZkCPcCD3Xq3vG1A3TjRGFTg3/rUs5bNO3qpJfSmmX"
    b"1O2GLuERd8lxczluthwavBe1w5HZqHPNj1bzkdOg1DQtcsQltzd20q5GCURQq6darZ9abQy1YuQtPJYaEfdEGjhivZZoyGhAaPpx"
    b"s4dZNmNI+zzoaqjhx22xC3eTGdpBseWIXbmBdMJOrDKS12uVWlieLVI/qyqIGclyGWVXDYp4y4ArYPbDDVvkhgl4cli7XZNkWKX+"
    b"/7XCaujMLmsdm41HNlojVedaszVWbE0Rb85QFxbELRX982Y5tiDaqVPGwx6369E25ZGd2Jr0EuqQwc5ki+8yD7QqydbzbJFuBb2k"
    b"AS35Nt1a0oMpuHJmyYh6lfaw2uP6jOmVjV2ELqvPvffQ1ZHLiehtAs3asSbB+Zu40koxwaiVIVmFyIA8OG4PTlHfeq1HR2xoJVyz"
    b"UY+p3/NlmaGyIxh3L4vARuS8YPxiQjRYJT6qshq81Sqpbo7plnc61ZexSmPI8XQRUZcr7taYsy1D5So/Cz6sdV39Fn8Xnuk0zjPH"
    b"aH3I+vai90CngZNmqIEbjET3S+cY07gRrMC9BSOqJdclG1bLTeI1F8wjxnMP4u4jZvOWWcO3+Gyta+G+ZcV4RHwCNw6YG48seCIl"
    b"J8w1ZvUtFa10aIwqrtnivKRGXsrptlWfwwJ2SLVANHO14G3ey4g0Cb8udFyTUdZqs7xNcmuNWKVKiZ5h1KyL+Z/FLzJr0ZJ3b7ZL"
    b"9UDtTXmss9nMWWKELOg9biymyehl5n8MqMEnlJ7wAiaNp2TrdBeMqWfxqwmztXV51UlZzDI1edO1FCMmGb1vK0Sgg2a0GsVEo3rC"
    b"JeNmESELbTdiJiF89ix7NqZPVdannPTIsisGFrTf1fLriPGfHjVqKa8LDGpPiGqr8thUeMvxBIFetpJZnNBhVaLvWDt7rlmfaYxx"
    b"L46Zr1UJlD7L7PhYuit3PUurtBcj3IcRTk8iBrAzZ91BnZFhqqJrmbdquZqMvJXNIJVFLo16fs1qo4K5qiH9ry3yY5ZRyWLXvT4x"
    b"YFTPOVaEH5HXhrXFY66rEGgxYpHjZrpr0IiBMwNhrpNeoUX7XVOqN4/3VMzkZJZkVGRdpQ9Y0NOMNccLeteZBxp6vNmK0JDkdvZm"
    b"G8mpVw9G5qbKCoNmpTCwS4aom5LprvQckhn52qh+SZLZRtnDq45sT2Dsqhxbp7kXXyU/ZqihwQxFtfZ6wqh3Yu4uW7Nr0lmPb8fU"
    b"SomZpvo8UzJiHqSi11A2xlXIffQhNVshyWSzpLw2KrMjVl2PKOMVu+Q26G2sN747LsUDEw6ZPZ/QQxwVV4Vt3mpmt2wNQ5yrKB4O"
    b"iRg3Wh/6P6Q+0cfPJL/FPF3kQFrN11aLuav1f5vln3atTqtRnG513hQzYlVWDdVa2dHualjhJzdz7FRxU1iobs8S3DpDuY+nZgYG"
    b"a1Daw65F/iYo050sS3dji4jlOvTNa+LWCeOoUU8d3tiQNY+D5l3Cxm50Dcce/ehha9EiV73V2oNspYLULq94ukGTSLPXKNEKbVAq"
    b"j4+IdnqMOjdL/3b2ovZi3Mheq7VrU8yiRgS009hUWZpVa0malbWIYGXosWDcp145bOOIOvFxu355q1Hyhvz/xrc9vDYzCHXWyYzD"
    b"s1HFEDwYlQpzXIM94tWztNv1oqeIkrYaFQ4N0+lII7PbZhd/lR7vgLnhrWaDQ/9kXlpR/zerzcqeB5JK0bKrHo7qH/ZriUbyNTI3"
    b"y1ujeoep9K9YLRDrAjaana1NljOStdr7dfqBo1qg0HwDxhwr4v9UzFrJc+QDZonDl9pqDiw1T95utDVb5S8qjBqtBA5/ul5uqzZW"
    b"2GRlSwJmrLWKqOjzBjqtJG+yqrDTiM1cY251RhqrRUxTjUy2OnvNSn2Nq7BsNYIZ9TUbjQqXjT3E2Ip2Q9RYOdYn1h7MLXWfT9qI"
    b"SOKo65FXXIN9jVVbIZ9rfJ7GhHWRY65B3edK+JHLnjAyudGIQlTQrBEvjlqlWvBaWU3CoM/jaDIGsi1LksXimqRWeKyN+hfj9t9V"
    b"m3WqURKzvGinuc5pWt/2PPrQnGOYGrFlo1izVUmuNbLeLWXCd58rDwaK7HLF9tCR9Xnkt5jHnqqTbOWIap/mUvKpR7VGAWIV+NA6"
    b"gTG3OL/j2t3oE+zPvdqSVnZITTcqX22xAiPqOdbo+yy3ziKQS+iFpSLJVfx6jXZkq3Lca+QmopDrRY+Tzk/EMbJ6vzGzFpu175Pa"
    b"5ZJIN6uWaLWyrU3Em8Wygq5ZZqWgrakTs9RLnzTtVmO2iM9r5LTOXA82G7uYpt/cmK+KtJ1WZhYyuJOeZVS2zLCeK3g70GfQbybj"
    b"mG9Fb6I+GWLmRrWDWWZ23IzAiNH8qmQ4j/aOe8+ZZPZZcztpbWSaZhWX/erGUasHt5qp7s+7msOHHvSbsthyq1vZaoxq4xQ9Umow"
    b"R1gjRjablI0mq6kGRI5jxtpaHGPm2xb0xRqspZywEiq1iq1b9FijtS7Y5zFTjpmqVQ8M2G0mod74WFXeWdNoNL1Vj6bR7GqgzcA6"
    b"iSg0NMCEKzE05PzYqIZOtPBD1kUFpsg8gyqxZJXrahec7w3a7CHjEs15PW6/CK9f3DdgjKxGrRaUCs1WEsmUpdmQsdle9UBgn1H7"
    b"VKrNXA6oU0dFRxUle8B5G89zhxW9zxprqQaMMw3pR1cZ4asx3l2ld5jJV50x7Br9kWq9xQYrSYtv+4l11qjM0ubW2WNWsaO5W2s+"
    b"Xf2Z5SRqjHVXs5fmMY4sEhzosMXIciDxFr2nRi1OVZ6bTNMs/z5u5UqsIBJ4KKobYk37DUZzo9bsLaOQY3Z/BN4ZscNxQo4MyzPi"
    b"qpQl44xVnKWkh53YCZnp2Cz6XRZ3Bmqa0BNqd4WsyDE0aO9ifgfstIv4d4/ZoXozRh3i7tDwLXkev8YYQaPVOgXXS+j0mRRT9Fwm"
    b"c3+lNee4Vnm1yb+NZg9qlPqgeqMWu8V40ahed+Cm4PIJ40B1njdsXLNVLYl9EKEZI4LYnFf7DsubQ65/HRpoFWeL/sFW9jrMIKda"
    b"3DH9w5LUGDXqOiSm3KClGLc2KmiY9ZGOiLgzaR6Rx7L3FSMdaZpx4YjodCT3D8tpVp9UMnNTZ71lVCGGX1K20meKGc2s1jJ79kfU"
    b"7jTltaJTlfdaNV88caUqxzf1OQ6app1t0mpH7XjEzGaLxDP+axaFR2RnulmNNldra1KKa62+7JW2gVMH0g7zQVntSTH3p0eNmxV8"
    b"znToqsRq1TpXuBkS4wyYjRq3fmKjsZpRc9bxjJqwGuPGGuvyaE5YoNXy13pGuMxYb8S512uJs/qorOKvYHaw2mzQsHnjMfMWVcaQ"
    b"a9U9qe8KetntxiAr1vSPyD8d1pg0yp81esRTrLVIRN/xhKHRdJoZgNnGWCMzM5NR7GTleoYWB8SO7eqJFiMPQ+k07UdnMiS+CZ06"
    b"bNdfxEHGzBVnme9RcyRF7XSnEYlqq6Mn8+hz6Kagwmo11bAVz4H+Umvz0jxTNZx7JONKbEkdOWhPUo91mAXrMIv2f22UXiVnpdpo"
    b"4kBe9TKZZpXaWd3FuBH7Ql6nVrFqaMysfUUpajV3WW1EsdrYbJsarE4fpSBfhf4rGEcsqu+m5dnmsD3hUQfaaZZqTWrNRpFRkv++"
    b"zuhFxVx06MlEHVlvZVq1vmLEWUfNAYy5SnSLPkVYkTokaIpxq6wCqd8I7rheYK9yHTGHTcZfN+WeyaiWInTm1nyVq5Lym9VKlNJt"
    b"+ftxLUgmu0PqwNTKyE4jEmGL2l2ZaFyNXXGrFtmUlZ2C9zOZPzGpRVqmZk7HtdctVlTPZiRzrGPYjjnfxSxHu/WSUfdY0IbU59Gh"
    b"cVFjxNMj2tuo3z2u75RpxPCx5ohxAttOU44TZaKiHszqF4tJVu2V5fYK+jhZvW+aZlnCCbljJH/WT0Quslj0pP7eqHmuGjHMFivD"
    b"lnHFt8SSG61BTYyUD3qezSLJ4KmNjHSl9OoVFSZWNqZyd524sVbqhuceli1qKBt8Etc062sjyhuVltsxi7OtXov+9J2M9tQrj2Py"
    b"YbNR21Z1Xr3WJYuktWqT63M7E15KQZwePuSoz+doMY8xy9xKjbohyXF4yP2QNU1RA75Z1DMhL9ZaTzaZZ2EmrAEbsDZkWJ84dOPo"
    b"2+ikpOxmPDZsrCbrVKjWyg/LZz1SezzNqDNiDCf1zFWiw4JR47LZhy1WxgxZmVdvvXJBLFFKs4rEstqyYuVhvVslzeL3TXkssEEu"
    b"nGqvSaJMjltJVmUcskoqNRjlapcitXl0sTWPp2cRngb3sqrPrO4z+5vVtqWuNxbrSpddb3/UroI4Ysw4eX2S1VUPWyUxLl0btJpR"
    b"K9rOLAdW67U6tlF6FqzQ78szx1m0a9C8Qa3PFQiM2KC9HsktcpJkeeZxqV50LxU3lvIsT9ajWMrrgqvMQcbMZehnOK+Kb1DCs8hV"
    b"mjbk1XaJmKfKNUebzfV16d3UGj+bSLukUbsSG3o1q2yu6IFvi3AUrRCoVdan5p5gauVRk+eviLrjyF5rdwIrbYJbN4vBtlq5UjRK"
    b"VpPntobNAwzKNyVjBNu8mglpVrYXZyKv5xwXY9cb3a24MkWWQ53IK6b7pW1RfqvTeo3ktcv/l0+rF9vElZrzXpIhZ7hol0aDcb0G"
    b"ZbdR3yE0zBRj9nVa2tBHHf6mxkhM0LvRuGoxx5RZxLVFi9RkrWS1sfGgf5YpbMmfIdWgPpxt7jqrr4hukjGfED4udm00Y9lg5DGr"
    b"wS1ardiX1+42WzMzbh1CxpGTZpzr8qfjDeV1NqN55LGoZQ8LvS3WnWWiq96uPq/kMp1VWpaNY2fVTyMizW21tpvyrGKtNTyJlUUF"
    b"uxuy7owRY7mNUjLLmI/oGU6an67L68cy7syqukfkwcDkYTGCgkXzYHVGfWeJN+vzzGvGi1XJtie6TYifaqRsu7HNLDZRZbys3fma"
    b"tHZy0FrnRL81bHIi+m60p2LSaMu2HoKyeHvceESjGDJkNvzF4LAtZpxT4zUZH2bP5BzTrtQZ4whk1GmmKjrfO7BCs12vObg41kcP"
    b"pF+wujPr9xyyfmBbLCIqvUak5aQYLTRnrVqo7FoDZffq1ZUt6qmw/i3q/0lx+f9x5aTUrHGvPf+8Ront0FupsiJqwqz1tmxBbd4P"
    b"UtDrrPjcsi6RWCt3PhOKdOhLR7VNVOxmXWL19seX85xrndHw4KAGqTgoEhm0aqZo5Vgh1wHRe7DVLMAmtWid/TUt5pWz7ESvkcVa"
    b"7XBBlLpKpFoyTtTtszISPfp+qzR77U+M+MJm863NVg5lVRJZTVuVPJj14gSOyZBxxG3H5MBsb4o8mnk5E3k3eL2eXa3c16EerdZW"
    b"j4m+UyM3bdaONloLkK2M3WI1cvBMrMQx046mrIZkwOhzdd6vWBHplOSuUprpy6ymbzK3AiNGC7ch5iw/VdT/HdNqZJWeqdg667gf"
    b"swNhMO81i78joqMGn7RYbxZoNM3qz0fE/ZN6Pg3ivdB/JbOFA3beVYnSJhx1o/maKdYojqjz++DufjVk1KYO5FRtUhInzO01vt33"
    b"1CqFRz06/MeSVfHZ8xoDdQ/5lMg2ObDD7q/woOuVg0RtMi5+nbTuKOtWHLKqMeqme535utw3HBPLZXXcaZrVkQ1571VJVkMxnNeg"
    b"ZRm8olXeZS1TWbqnVk/0iV9GrJ6PUQ+IbsJjik6rTY5kQL4tOKNj1vQWnesafehKmtV8jIkb0jzCl9UhV1v3PKltSoyd1ea1tlXm"
    b"S8t5/1K9kcksJtTmDGRr+JSMhWWR4HGfgRoxyy3g7sj+ROZ3qnHFaudgPI/eTVgZ0K+uzKqNM49hWz/PiHKc0WxQNFw2PxW+Tb1x"
    b"/pDfrKq5ZF1FxCkLIuh6q023SrVRo+iNcm9mj7O6vsAFW5WLiDVl1rk6j4yMKrd9zmqj8e+If3ahJWYlUTmQmFPdhA7IqjEDERVF"
    b"xtVK37j8Vvd2111dHg9qUDvW5vHKGmOHtdZHFYxfZh14NXa4t+QdppOOr8EZbDACP+zZC/pQda6ps8WKrCqrodrVSFmnTNa3UrA7"
    b"dUKL3fp2V3WjdBgQN2c9XmO5/9EkTUZdZ2+zK/eUxX5V2v0sw1hl/rHyNnWz84znz1IdE683WeERViq06jQwa0vOlRNWpLepMUes"
    b"Myvn0lTI+wwG1WGJmYYWZTRNM1rVaUmqc4SZVY2OWbfcIGLpti4stQMjyzfW5xSuFQNU+fsMp9bls1ZUXw7nef927n+aEb3Qd+1a"
    b"itLbFaAldWN13jkQHD6oFhiUovVa8oJ1ppPa8xq17oDabUC5G835Mix7h7mqeuV4s3WVY9rxNJeCwP4tVuCP2VM1lstK9duVgS1a"
    b"80S5GhClpR5T/bZ3m9XtFqXdpFyZ6vnU5Viv7FYnP2XxjXHjNNmzR9utfhyQuv3o2T4rz+NqpTTj96wHviCnjrlX9vyJc1lv/U61"
    b"1QeVNM15cltkvPL/qeYpJKXcAy9L3ZG8tm7Yrr6KFGy2knZUTJT14zQopcN572udnJl4/eyZbRV9l3E/HTevUcylopJm8ZMR6Zl1"
    b"wpSM8qxHe0W8KaJGc5KoIcxsU9HIasxtuzVM8asm69QL1pM0qEv/r9O2LDWzmHZw9RSv0eQzgAvGZ0Or1ebPNW4ReTWIGIbzNVcy"
    b"b7U676kbUmqaRb9p7pOFzzPFDF5YgVg7v1lfKKNR1vORVeKX9eqq1adjdk72ifsyPZBoxzbZa1JrDCSrpt5qXLhF9BSR8Gn8osk8"
    b"dXOeH8zWWsnW46jV34oO3G5/MR19PdOce4tV6xOioKxPtKD1SdzLqh4m9YMGrWPMftGhpWjOvePxnMObHFki941I56L+UZP0GDeu"
    b"OJw/IbxsbCcRP9TpJwy/rdVHrexvlb/HlboBI8/tWuJGa8smfO79hNntUfmrKKbK/Ldh8ydFuxw61JdROxkeU40Vuo1ak9p8fZWS"
    b"/Jd1CtdaB1knIijlVUY10r0uP+OwXZPN/i7r++nzXUWtE7MyRWxbq42NKrVJ/bZsFiaNGKbeb2vOqSPuVbluar0aMM2luNX8X8xl"
    b"i9W5PWrRMfFMl9SqU+JrjLTFPXWAgncw/lAnulxvbWHWHV6rBh/wfkpKekk5Lti70Pr/w4FjefX0ZN53PG7fZxYXrhZZd0nP6jzu"
    b"mT29rlpuKecIJ67YanVWnXWGJWdzQutSUoNX5dGVQWvzUr2DjlxnVqz26nS+C0pjn9JY1levlfOa7ZFqyNFLUe1YK24qa21rtdFV"
    b"yvZQ3p2QOnO95vuzM7fos5atJKzNq3FH/cW27oWwox3yYGC+bqg8Tb+iWT1XseIwMF620mNFXDSWdwiNqI0z+tSrG0eNvqa5zkv1"
    b"0utylJNZlAx7Zz3jzY6zbJfuFj2wGvmtyjP3y0tF6zOb7EGbMEY5/PbemFdLzNzVupWlyYTV7lV2ntZqIZqMytXlEh0WejLvq2m2"
    b"pr5D/BXXbhMllp2jEW1d2fmsVoMW8ixhZgG3ypuptaTtyka2Wl6Sd5mWrQaYKsKJmql2e6S3iBFG7NVoyuUzo1bFex+VRwvyX4tn"
    b"zaR0MJ+3rOtjSGyd8WOmcSa9cklOqzey0+wVMotY8TqJkjiqJKZeI6tFm1AXTxNdtNj5kvlD42bE4u7G5OF+EWGdvknt21JRUQ6L"
    b"SbYqbSnXzJM+OyAw4oCxkVHz1dmVY87GncdCrmcHXa+qM9fd69Idk5Vo81G9yU0ggR69p0kx5RTxYaNrA4yoJcaU1Ib8ukX1UV1O"
    b"4w6PbjBWF9VPEXvr0L/PNETWi1jJe/sbxYipa6Vl3crVSfbkuYKrPbQb6U3Eb4Ouv5CtglCUz4q579Ng30wmZQNI1To73OpyDDWi"
    b"RQj+anbESVLI0dGQ1eUzXdekPfeiW53ZWmdu0rhnSb6JvMSAK1O3OPqGHK9VywMjOXUzT2xcG1yXd48U81q/TJoyxBcoPePPfud8"
    b"sysqZB1HTd5Nn51ANcY6Zycr0rnWm0T92nZojS4xarP2JVsZIcMTWa6jmK8X0ZSvazOgH9Ehfq/xLtYwx1v1o7PzdeonZbH+beuA"
    b"ZDxXEJlkPSqTSkzJuWp428o25nXfg/m659XatgH1V+ZJT0ihiFz2cC9rzeHEymObzLwmSVZdX/O2p1AU408aL+iyoiusVZc2cVg0"
    b"O6n0F/Q7M12xrb43m51WpbnkUVV55+3/rRCRccFoHhcbdvQDRnhqld/EkWf9PkWtXI26sVppWGdnTFxtfb5iTqpPX5WjjEElr0bp"
    b"39Y/PqZ1Gcg7r8eMqada+q58dYIqR1ibo542ZSPR4xzWQ6gVhdfnY8+sUtFxt+cStxWuj3jXuPakV6+sS43ZrJXtl79KIpKi9qjZ"
    b"KE3WEd6n1k5zPV/KMympUZwGsUO1UjgsvSfyXqaK9EnN5rToO9UYge7V0qRp1nUccZrQNoNp9pS8WjF8YKiogOzJve62/PfjfjPu"
    b"VWveXkci029DuR0Y1OaUjeJ1iVkzhFFxXZgs9xw5tTVqr1RvN/it1frVRn8/mWZPZsj6FupFpv05EqgWT45Lq8z+ZysYVHxXr5dT"
    b"zNfeySICZfFch+dqFKVM5JGtVA1ZehvNZnHDFjFEttLdaE7hSt61nyHJRJTYrD4fT7Ne8Kw+ZTTHrFkEIPNutvlM5be9h+yI7FzZ"
    b"M64zqzbiLPQb5eyWOi3GkDdqDzLaN/2/ejoalKMsPjaofm9QzzWKBrLMRqC0Fusee7VeWX1Pk/0ofbkVS9UeZWexPddHhVzyMq4q"
    b"K6sZ5avy9Wa3+ZXZ6i/1oqpK3h1fLe2HxUXFvLd94v/TZVcr8o34Xazosb1rNtXYedpjj282541Sp9mRjJg7LuXyldG4LvcqCp6v"
    b"MfcStvFoKp7tMu5Ub6xyXL23LUJcKy6eKp9HJm+WXDmmBegxH5StrVsvls84sKyd6FAiqvIse7aiwJDyXqfmDa0+VR8nqFJrvKhX"
    b"m9KSR6QnRTetOf5tEY015TTJ6pmKYtrMVtTknYkTue8TyL5ZmziaZtQuet7MijVo21v0MYedkZIaoZyvk7fN20/T/4v9NeSVSlvU"
    b"Va2i0facZzL5qkoy5JStkFAtfqmX0qk2Iqs4L+eWOavJGzXeMS5XdRuzqlazZsiqoA+UdfBkXJ2tJJWtdFC2OrvPWatOspU6Mr5p"
    b"M/dVJQ8P6ieM5AgyW1Uhu6dJkV7FGNCEiHU8j36nb6P3bTnqcSWvT7+5yw6ymclb2vLRHI9ncbxxn4G4VU+1mGSrHk1oiTMPe0gN"
    b"WCfamWrcNCJxXfDVLHPwWUXlkCip8rZezNZaLOVSWNHCThgDaHP+Mt4dzq1k1puQqnHqc601qn7O1rQous5lq1TL7HWaZqhp24zV"
    b"ayeyHpGC8c9BPdwsKl2XW6Iar5P5EttoP5qPsyHXDVVmBWryPrHanI8q5mUzv3zCp9gMiNTrlNREqmW+f+Z/ZzgziyFVq5W26oEG"
    b"z/QY2clQcaNdGE1SOP1/ujoT5saR7AgDBECAt6Q+ZmYPr8P//x85whG7dszZ3ZJ4gcTpRuZXRczaYUfvzLZEAlXvyMyXT38yWteP"
    b"/sYX4WA3Ich7RdmVqqBeWXXk3rk+KXRn7Z816rOsiEutTlAipqLgzCdUm1ed54sy20788kdpgIwYnhVR/FZcd5ezTrEfw1SJ540T"
    b"Vfx+g2veQK/ntOG89vHc52S6UXe9jLE2pc4tFPEX9D6ubFs975znfSNLT0/uoidc6rm+6Js0+rwn1fLWb/h01fyuhM52yfcJ98lT"
    b"4K77M77NSI09qGZpcbgd9A48q1fRsxszLRXHe9VlC72hnW7PSdrsV/kCflQVcVAFc+Rs2/n6TTVaKlefLWrBjju+EBJQ4hbkTNGL"
    b"Na8U3+xsMaHve53V8KetcsBaKNBFGeuuWmCpn9/oSd+EDPgOLMkiT5pW8+nrVHEmQnoG9YwXMMwNeO0Q0Xc/lw787EAlfVWGdga3"
    b"X82V6aRcT+xGp+MMddMZLhXREj3ZWtnFp2qjPsh8T85kaKGO4xPVxfQ7vmmS90k5ZaOa3nfOU2RrnQtXlSECXfWTC3QzJ6qocPJd"
    b"WVl9sVftt+S/c1dHPyER5qL8bzbUVg33Y8QDwv+k0U3oYNCPOkWeKzHXn+NaM4IU+omP2iHxVYhmK/Tus+5pKR74pP/GqPOXJd5/"
    b"knICn/XGlzpl7+osMvDNKYqZIx1Hc1LPYhheNBPvXuOu6jjHRSbVMzjIMW3QyTtSyzdgxqkQgj/UUXSqqMwg3TRdsRWqu4//vtQ9"
    b"velbn3VrC/VNARnxrXNltiTWNOo8Q2dxgQMshA5c6aLtcVSoXnHHZn++CjcgR8UKFqIGsXPccje/Yt7dFdmeiBMiXqrnbIVnQ+/h"
    b"OvdXzS5Pqt/fdY/uUevU66c7q75qYmwlT9QP0qRslCVvOuPf1Gc6Btlj8E0Y/RbU6VV33NGhIRtl+FAlifHhNWjmWzyXb7qHxqqm"
    b"N/Qi3H4pXP2ok+NbbEwyRfd94b5l0t66a3Y0d+eRqyYeyK2FIsBNkWelmnqrytDeH41uz4YNzGdFl0TbHe00mqo3rRVZ7NaaqsY/"
    b"K+J0ZJe78kyIWQk3xff1q3qOqUOd3vzP8Ol28rsrYm7Uy45jQwS0esH1o3/KQjVQP4aOoBTH6UqhVlVYqx4wIrBUnXxQHMqUETP1"
    b"DNPnfVLV7krmRobOdL+NStZiXY9yqnlWVNroFnSjZx5H5aq1qqiDas1WVdiv0qJOVdhXIff2TExjjm10116EbC3Uh/2qvvGueFCo"
    b"H9+qT93gjuQeOI2RKud7t5zGd+JghXfQnjNdj5vIdHfiar8IbV9qqu8DMXlUF/1CRR8cQXOdxGdhVK9UQjtF6z/gCCp9TkcVI883"
    b"eicj8tns7LniWav+GYRInPWEjb7v9Bx97k70jxXz7Xvd4zRZwOS+yavssxSpn5N/jf+QeqzQN7/wfkuwuLv6+y0Y0wUUKrDmifqq"
    b"K990qy4xEZ7yjahv96hMJ/yqc/27EOVS7I+9q26xRx3j//cZO4OMFWCv7mgW+JJaB3oTXrsD3fD5HJhFcA3tajqwsCt9evdDCymL"
    b"jpofff9e+f8iRaHP9Y/SEB+Zzp72tP5DDqtTPWKcIrhguYKzCsef8SYNxZru7025IE3cfd9xW+2Vfc6KzCuxi89CRu/EqAX51D2P"
    b"0YgF/MZNJ6bW75460V+kcLoJE39WjjGnWwhV3+FGbcZnUC9eiqV4EmY1jEbFzGAZMXuXJ2OqqP1JvFqr594rJuxA5AN/7oyToWH3"
    b"loQTLo5F4hriRefrFvFg94QHto6edI+W4PutfrK714EsbcwtJTuZL5/i0q/q/6f78LN039Obv6jT6WHKzfBav2H/v1z3psYDdQF7"
    b"s1PkLJSLflcuOoOMJRF9SOSnNT3vSaH0JCTaFaRx0V6xIPhobsEIciELezzzzOmO+GEe1Is5DzSqLK86L+YSP4rleJcr6UWM3xM1"
    b"m9UL/t8eNqvT2TGu08NzLeFT3B3elX/MeeV0DM6ztVxjfpCafuIeflRse1e1mhAdXtGd5TqlCzqPDL7tqE/Q6S648i5A1EJdEVDM"
    b"I/jZXk88vM0OT7Ib3aoRlOAeYgaxF5ryUVHeeKO9vG86x6mUHAOOoe5CpqyzV0zyTPNJPHCnrvdH3ZW1HGBOzCjmdJHD6JNcUpW1"
    b"cQqwpVpr9FzedW+nTv0447V36Jpv4trs1NKgMbB/yxmP0UZ1cqm69CDW6DxaNbdCDxt6mkbPvAbXsEb6zASy8/kSLmERXSqdORLY"
    b"/6veX/BXPumULhL3fZmyS6OzetdPrUCPcjQxXWQoM1WUZoM7Oki/xx2McRfZDTNcHXnkqp92n3Wirj4e9U6u89nOap7ABoxixC9M"
    b"cvWw4ikxsdab6dXrrGDaA46W8zdaqZA+KP8UqqW+SQn1h1gRc4of9GRDh27+66juyn1gzzncyenrKi+lL5rKm7Snkx7mq5Qxb0JI"
    b"X/C97UdrWxOp1A66G9a+ThHqo7LipAH96/d8/B86RSsQxy1apg7X01Gfq9eZcE+30GTlV7jdgrNivWCPK98Y68MVLOJ0D37Tb55Q"
    b"haln+fn7ffhVb++kmaUNffar6tSLTpYRHOOxH8R1tXjBGNXxSXCnViva+cZ+0n1wZTlI02+F40nxbAXy08TZZevr16p9rCAw9rAE"
    b"f3Al+QwaU3BCHSGtLS916qwCWMgf8f80BZELq/isDrBRRXKkBstjfm5jbGzBzIy97pSrO2b/94qOV0W2TvnZKHuPlvCd3s486y06"
    b"OOV6Y1tpO1qQtXCu7Qa+F5v5TXXvTW9gp/N9Y4L/Kn7qD3QTzojW77i2OeFrNPKkc3zoK+UDd43v8pC+CEX+rDp/KV7GndBOKPtv"
    b"0l3fVLG96BOMejorqn3781p3YM4rFce115xTqrx6VdZulREaRbav4pGm2i2w03cpIp9UF0+dzYTDTvlno6olidWM42ZFXGzgcsy2"
    b"XpTZRmlmPM1r/bbRBmc5d/FWYE2/4SzO5Q2s6iyf8xfhopOa9b+EMffSm7xTzdjNv1EcrXDFr/V2fIYznM4WTAjkyvDWIwS89wIf"
    b"1OibB2TuAgp0h/FcwYgn3Jorin77LtXMXprZqImxBdj6qzqWqfd91Xeq8F7MyNve3FKJl12SrRtFSNedA77uufiNhoo0oS4d+VOp"
    b"uPMq9OGqHuyj+vs9uzDMbB2iKmULJlOJ9bMn3EPdVuIQOIA6lqqi78IvjJs9qTI7a6rvD+kOtyB671KjXqMbx53T9yw97zTP+Z/J"
    b"/2gzxMSZ/6z3XSgOJUn4P58xc35WWnbiEjs654YMbr1kLYxmqbc14I1bwDUupbY4SJuykXZ1msD98L26+qRuyNWDI0aJUsfRfRAO"
    b"m9FnL8itvd63uYBKp8UTrqM4rpOi4EF3baSPdjUzzDZQVOBIK3UnB52hIWJvjbL3EHUW2azKSMVqPAlBGfXEMu51AtdyQiMV2NSB"
    b"zLwAcVigDR5HY0rudZ3FwkYWd0stvUkbNwukinlHIY7DGDQGvhfpDFnvmPa1DvCkbaWT88CrHHOneP8un/GzvpOdpKwVsN5qrxrw"
    b"ndxj3VUdq6Ak1kgdzHWh03mlSt+p03vR7GE/3mIuzJIruH2iqdRfpdYw4+AKaIzf+YYOq8AZeolaN1MPV6rHDfljqtaNTNqlPkFJ"
    b"0IG+LhLn7bVUIi+K4yfqrQJ+O4P5rdgeYTe0m2q0UtF1q6r5GtVTPc9hOtXfvlc3X+RDfJYf0y6yUs7QdqmoVVukoOJ31ZqOwN4r"
    b"soStzPQbJh3Xj0LnO53sd1gDV5SNlFQ7IY47nblcmkbXwZfI5VzAsh0rHQmtdPCeixubK3pcFS9xuqaGlbT22v/2qs/8TRlrp1rH"
    b"mbpBm7Ykgrf6yUumpK1au+tm96pLV6B+ZXS3X+jUfVV3lwuldsx0Dg86yhBDQyd9ULaa+oVKGdoxNyPvtDy1s2r0ls+z5N3c9GRW"
    b"sLRJEnYqFIoBF2JSo/4tzGm9Ckt3/WE1UYWrY8joi6i4srLFKJpdwlczNMMI5JKsNsKFW/10m1VfS3bSZIrojjtLOe1/0xTcu2o3"
    b"8zaBsQqo7BpNjG9pEblwczfuURLYAzt2Z+BJ7Uzd1vNP1mikq9nEnxkVd6NhXrqPXF+iz/dBKvGTkPWTzrl3BzRS2W2pv13zlVHb"
    b"31Gtu06/KL+YF6tUw95iV9jCVJpjX8lt+qCJugmx+IhKYuo/fpZK+V17qj4JH31Wrkz1rKzrdfzPlZNT+KidPl2ivNtya+1PaWV5"
    b"HxVnlf7zwCznnnfoM7Yk5n1UXWZNnudZ7uxnsAquQzNVwSeNo7mOb0zNTx5w/6H9a1M/8qwe7VXRJQPT9wT4s+KvUcav+qY5VWLg"
    b"WI1EPjGve4++m8YWWnjqMFtuTa4z4ohqtEOb6IzZxVOQ4w3Uwe4ttK32i7ThnTbm/U38s7G2Rs91JdeRV2XrSkzGT8KKr8LIejiV"
    b"QnntWXntDJK0TqzatTbnTdzDWXhageZgCQLeCXHxfIxrZk8yHNSlJsTYQi64B+WIpc5oTSzNqRbNO75KYZYQb0OWdhRJwSuXIMcd"
    b"vFqHwtaKuYvyd0ns7HEEDorCQX8y5rJg04QZmdAD5lGl8kmRf8LjfxIuldL/uK68q1stqKHaP6kiB1iVCiQzg1F7F5vgrD/oru6V"
    b"rZ++9wr/0KaoVJP0/ydEtIqVjKe1XtVBLOOkZqVMFNAKq3VrYdretVTQBwS9+Z37vKW+GeEkXemEjn+Fcrenerwozu5g1i/wLo4K"
    b"vl9rHOmddYzfblSvTGjFXzRrkKtzPgrlzWfo1w1GaCXl8nSSJ27ms+bXzaG24wCPuVbW2OtnfpOzzc/MBmW89RWIhWdgnjWp040d"
    b"z2yJBvZVmMReeNizfts31SM1bJRnlErQtzCBlugmfNU3aFFA9GgBO2opb/HxdLSZVcfm0CG2ejtbvZce3OIHYTjWnp5Q3V+p7ZLE"
    b"ONEm6h57cTo32Jh2pmPxPy+FfR1gFVrFvoFTstA7cIXTc19S4sWr0IBKvOon/SmBL/Y0zKOC2TDfOIL1ePLbNekXPW8z8Ss2ejgT"
    b"1Do9diTNVN+7mnJ/swBFFpCYWFmw0AlxhrigWl4qBh/ReW05kzURvuRmLZlFeBeLOYLnvkclxZGuL00cCzY8y0Uyv9VmeBLqqArc"
    b"4ygMLJWz8wOPylXXDKqQc/UTZyGdg2LjJ/HYjSZRfqd3yKOeJvTDBcrdRbJi3sY68J0ihKcbCr2dr+qxzurmK06r8Tj38RdQmqAD"
    b"D9H6IESpJj+uUbT6ztRsWf0gpPIoJM260ENUiprXbyNr2LJ1sKe22jNZMzAH048p99waUOsfL3oDK3JgTT4pwMBvoPMZCK6RvlGM"
    b"ck7cv1ELXtG9Gz29o3cqqLkDA3FXtZmTz0JdmcFEhS2AU4XzQe8psFg+ATWsQ1CwWHUz6L47ipsnNuYWNMhjZJG9PS/oxPbqq174"
    b"jR3voIVvtJZ6kdzRDNgp4EwuLlCylsqHZilD5rr/2991d7XU9zOyXXKv18zK3Kgwr9zNQufjTPZb6kTmRIiGarEd/b1XbOaxktnT"
    b"P65jfPpDZGnpdDyPFjiXEpZh7gWUwRAN/KQwS1OCqTlu7tDdnJVJKlX2G73NoLN3752js/8qD4yjap4nad0+qqpzjWAtlWfErOcv"
    b"QQtauK5W9fWVpxX4Y+P17/p7tU7PgbmDKziq76s3dLbKxR18QUbN59szMPmaw4snwvS3aOavcAELOGtzu61u15m4nhM5OqYJXlRV"
    b"HYT1n2H6Qo25wMXaOG4B+2AdsWvpkyq9laJkmNQxu+2JupVypOfbW3Q+gREM53FBFWR18hZM8giX07P7s4qo34LTk0Znvz7qZBLU"
    b"HjfcUlKe8Ao38wuZZEsPfRRWuEFT9oc2bm5RL/8q765SVegzPkChA9yiDz8xa9jxzJdCub+gQXJdcib2b3WyF8x4JUwQDNzM+ZSM"
    b"8/hIR+x+pCFibtitOfA+HKWW4iysiTNDY3wk4ww6Sl5A7pZMx4VaOI1zqxuhpgcpQxZwIHed5pHJWmtor8p85tsbtD4VGvuaCqaI"
    b"ebXS+dzq3DfSOH4RA52CiobJo6tQ1lZVwSc98Uox6FXn6M624OCwPo7hDA1MZnZsx/QMRiLk4RQxnlpvveL8+zx71mOAXTHf/a6M"
    b"90AYN3pvSWLF2WfU5RML/r/qn+w54Bkrq066f/Muc4++QENi7ZjnSF1vHVUdeWbiENHNg/7ZkmpyhwLrla2wdz3xo2rrDZVloncS"
    b"drUaPc1wo68UrU8Ra31l3sA4f40fs++T+eZwwpZo/Ap0fxfwxQ2R5cKO4CVzDrs4YfhBTHpJHF4QG1rmFldk8oY37+jUok0eVY2k"
    b"TFj2sb4LqsSOJ7dmR2zIMR0VoKfG5wzaAm1vD0qbJX18J48dTmECM6Fb7GJP3fJEC7Jp0FX7/l3UaVmt+qz8nwq3vKCnK+Pfdxed"
    b"0EcmKLVH1RBBO+/7faMqsv7Kby04KruzeIJdCiopd4qeMbY7ffhvnMCoQ36uUFyEPq4kOgVmueVt+PS2uPpcha68ocEYyUqOZ94v"
    b"HiLMnTO0wFXZW9hSqo3JMeB3abO3cuDxJPoNVU1JhF+isDHrsCJuV+pbze62ozudLd839DAV+SGDb5n2FXz93i//Uw44R3HKB2l1"
    b"dsxNXTgtGVPa4Z+fYk/YgHXfmcjdRrTL85hW77VgizmVSqMbUqmW+CAlVKPYYW1gq99VEjP8dK7KF54AKvQnuzcEbdQWNP1RW9jr"
    b"bWTmZs8n9H1+ZNoElv6RMROUTcH7uoxIY4iwGZqenve40j1rmAY4iCFpqX6X6O6CMqEWwvQZXc1ZUbli1rQDjcm5Sw8EK+dGtty9"
    b"Pu6cNvO9wouvpAu98HMHJgnMpzov7aXevCpTv0qVukNf/XCey4gww5hSF1eR7ayYCHCsyrkdwSNgBxaTJgEDyYgc4ZYvcNi4RX1T"
    b"iNAn3A6WIM0Veoo7Wnv74hstG0Gua1WtFyH2aVIQs/2nVfzMG3wCFlQCr/AU7n+smgq6+3TWdy6SgCGXzOk8lDB+v54FPtBvvoJ4"
    b"91KcfVGWXksNE2bdBtjIBbMEG87NSfnMkwVhU3hHL5/NHBFGoV3PsCpXtl8ncebSWO4L+q8QyYPHgiehEhDNNPEsea0ba0bjKkzg"
    b"qAp2KYTxhVrQasQtmS3nDnRMpvTggRnq9zOnbaUnf9M5aVB6bFA8XIWVOkqFnnBgK3rw+XJ9mzCXfWQ79SLOJCTKxOZEBtwI/P97"
    b"UPtUscBT/V80MWeUbK+MvKEqqoVJvzCVaxRsDdo+cgJu8X6d+fcd/2mrrO25IdfkHWdqr5j1TRzwWajAM9NcNfieJ1PeNR03If81"
    b"u4jNLgxSQoUZHJ++x/MMOPxjNtT/zRuc8BV+JKM/CB7Q8/n9lpm9Uaj6qxD7Hc/cU+M/iQ+/sEf5GZQgj5PZKZPZrrS/6Q6s1TF+"
    b"1DdJ5Rf0O9+8Ak3NiNVZnIMa6fJcXVUoHb/xaXIyckN/90G1sJXO/djAYg2glO4ewhNvYNvNC65QE70xfVih2Gj5NjnZNqP792+3"
    b"T421tpVu+i9SHRfkOOdy6zav1M0ZPeCbooA9U9Zo+is0fr28Sg7S09ufaPLg8p67Fm3MEmTYPOSLVGA/SA8+9WKlOjbf78CieVah"
    b"kpvPj/qkNTNxO2WrGj3BlSnjVNrfr6qjn3DkbsDdXe33zI+3dAojG+1Wsf5KUYL7Tt3j7PIisooZP3ONf5/ncb1H+V2Toi96Dmvh"
    b"SC9ygFrIge9f8i+0e9BOde6jc8tn1VWquPoGxpHAAlZMd/tkBa/aM7jZCF7q0+hs+hznGYw0/aZ645mI7dr2gH4pTOQ5E+1mkxk1"
    b"OFdK5R5qDCOhZ72LnOmWmsqkB026MpWdRgzgAs54ZT67wCVvjS9OChrpym03Q8zt8mQGtGSyd9C5exLzZEceu0Qc1eU2xJEtc7CB"
    b"8/P0yYsqqlax3DMXWxyltuT/SdP78zj5nu8V6bfkuRvuRWt0nhlz8I0y+yZOwj4xoeX543V8ytc4oRrQ7Wb2ie4oa0tQmdDR5ETE"
    b"D6gKJz2pY2wDn7jVb+/1JzMHGe/wFlUQt/he7d5qpd2gv3HQzb5Gp5Q+YoLuqO3bMp9x/VkK7g1TbcWffNFeNIOdxsmKljj+mBye"
    b"V57WZ76qfv+oTnmtbuSIN5FnHsKkf89s40IbP/4iB6FCcb0ePaU35SPXNFYrtFI7v2hebnKt/EHIexGrK8/j7PH2GNiY9h6R1yPn"
    b"fBjDLQieBgsYRd+3F7xwXZdNuta/aM7D2r/pP/0WeaxBuJnR3fpPU/UdqFGDZ1SY1rIu03cwnXV7nig0wuEu41UTBC9MjVifcpC6"
    b"/xW3oQ0qluByVMMUeGfF444uQaOsDH1SpbXVXNFR9UhAA3KQiZ5KvaKmSiOLEzD3gO6XqDqGmQtWhgba81aB1XGPsYahzFGaumNs"
    b"QP+qmE9LndJX4nwV/3ZD/zMyu+vb9A5/vuVOBrxyA2fzznd2lLhrXucP9XBLeJHXPykNWqYiHB2dHXd4NG1wlviNrc3ZjJHIQJRC"
    b"F5Uxu7uAoblGP6irKvHp5p9wTJl2Fv1NzgSdNAtH5jCrqDNYwtkfNeNqD7RQG18iOmzlvP+esRdXhYvE2+V2xLYz3VKL5jRwRq72"
    b"7nw+f9cvVMcPZianF8t5FwscA4/wjqVch36R3usojmvL7Ln10UuwReMdoc9JmCw9xZnMr4oHo9C9DzCFNT1FxsRKF1GfLlaVIzHa"
    b"6OKFib6N+PZcUWWKmDs21xm92YnvrcC7UmpC1/PudoLLl5/jbVzEe57DRBWROUyprbaq6lIUIhXofRrz6Vq/dYPrqPnMgilVT2uf"
    b"xPVewTQCdxPQ/px8+QqKX+KEuARVXlLxWYnhfq4EYzY+5NmyNE6+72Iu3oAo28/oq2ZnOs08fBS/saZ/eXAYHYz4Yzb5OvOdCZ5h"
    b"63gvSum0vsij7iyWtFKtuiPzhdM7MsVrz5hXdUgZpyVM1Q1jYEWCL6Udi3rp6F/ivIMdOE+c9gIE0Pko8JfhxrZ6A87ESeL43fJW"
    b"3Lsf1K+Fb2dWv6Hms+bzGBFWIyhJEj7RO13uB9V0Z7LOlhyQR2YnaF7yyLAFrccYK9CefjOJfvPu1gOjHe5ch56l5+4F7LD4E4JT"
    b"MV11n3kEWd8ZkAI/3+Co1BLvzW2EXq5jW00zY4Dd3ZdSPFu3MQjz+1/NFLTCpT7K73er7NHiHbVGWWANS3A98H1dUccnzLZl9MdH"
    b"PLbMFboqGYnpdzzKwvxoGn1hM+qsgB0WUQdZRxXaNeYax4mOOvgDGpcbjpNGtLpZl3LGx77Ek6uLev4b+z8Ck9b9G6Na4JBkFfUH"
    b"3OdPcqN5UVdiHjNhIrKjFmr0J8/jl9EfcUUtbTzbmIo7hiueoMala/rcF6ZOa7JlHascYxLmOXyirIAMqqAFSrcGbWAR+9Rypnh1"
    b"b1aw+6RR97SnQ65hzJLYY06T3r+Rj5P4fq7w6z1TtFsU0xl9xBlNQCdV/6/qyBtiXk2fvY67oPKoPurH0D0Gfisgcb7XZ3pye2ud"
    b"VHWGE/Z4dxXYXeAXBmGdz1LNTptopun8v+kbpZFrcA36LExjqo4+wQP2EQteRP5iwWnp4a4q8v7DhbKZRcnAqyxiBZyi47eeLEU9"
    b"4ionJ5KFaJsKVdpS8T2mUtbx2wfkxvrPEHlGItcaB4kl00tHcrrR8BblVtBV5qi8jqBnnxQ5s5kCNCP/ZpEvKXkaCfj6MAbGfZEE"
    b"1WH40wge+nC32EVuaEn8HJi+d2Qu6LsfkXNDHH28B3POF/ydjBwGPiPkygvcmh0A72DpobrezPiLmpjXwn5l9DHWRdaR3WjRdATs"
    b"topVZ0q0SmZMWsbUbLhz32A2QzyYI781XIF1Mg8v5wJecMF0Soam50I8WOFV9OAwwnz2LSJdNTs0bhEpPzFXMPAd1jOnpQdj4kh9"
    b"BIFfSxn2CgewZA6vhF218/GP0uWPYtKPyl0j/U0aOeAliGvQBSZUeFkSVKsjCOJGb9Rai69gETv0Xqt4hw5oE911PyrBAqfdRp3t"
    b"JzlYbNVh+jPW4reeVPdVMyfDUN1XOKZZm/wiVcSbmPk3FM/92KMkGFCQtfHWB3c/e9jUMBMFGJWVUKFi+oZ3xtyl3BElzIMnsZ5t"
    b"I0bXoOILTipWvpgjqOG3V/y+DPdAVyYFLp0r2NT3OH1U476Sz+Kfa1mrpRzzWmadn1WRTC4of9UmzCu68memh1cwAeZo7fEVMk8X"
    b"30quaLfm2wZFUUmP599fEX1G8MUSBv4Ueah7rGivfLoDiNUy3t21MCfjhuZYdngB3blXZcSWHzV6DbZrfbH1DZ5ovTPxUKsKf8Ft"
    b"+BdNah7wdriB5/Sogy+wN+HdvwvRssPMgcnzNGKJdvJ27VfA+hyprR3d7ZuXwcIHhLuJNWXgkZbKb1+oLYzPDNrW4trD+yODA1IH"
    b"cl7D3KfUyP4OZtDu3N/gTLJGfdeCdV8j2jHgfH6PsSZXH/LYAZFH/YV1Ka7ig0KtZBqsRI32iH11dGa5oboKOsYVmTHjb3vq66S5"
    b"yE90FG96NhVd22OGwMjxkV7NHjMnabNeiYAJMbjA4TQjpjVRffXQAoW61t/KKrQyZpBMVd+Ob/eO420zy1qlftYZZcOeXrTl92do"
    b"jVq6sY1wylox7Rx5gA0TJLUq5xdiURe9XDzV+C5GwmqEje6Ku0PrLe/wfsEJ60oMMo4XVKo7PmmvZ2NF0wcpwbZy0P5FcyO3mRfl"
    b"AS/Ko/x7PgsvtabBE0+b2XRhEnOJJ17PM4XQivmzUjmmJjN6ntGO5iGnBTednp6ngDP/ot++lgL1Cf/gRTKwM+mIh+GzcI0r09st"
    b"VZ/1q2emiy9oBO0VlqKfvcdqeBGzctj6MMCDdkxfGMNzZWt10SYiABtm3400T1NGU4fn2QGfKeeiwARZb1nBZNYRJe5QAA2a0n5G"
    b"9X2K7gU5E/d/jr1V5AUfbjBLEFhPOxSwa55ODbOLe7LaHde94L6/QPPTUR2GmaiQb1I8EBvlpj6iA2a/SnSfi4itPVFXD3hJnahW"
    b"3WfU+Ob3MHXWye/UVb6wx6AZ7WEfkOp15LfDOwmaqR60toiq++BfnUdf6AYXqgrP4G42AZVRZ7dUXv1sgtHsUJhlTPEjv9Pnrol0"
    b"bexK+jGPeo2MzvUz/ltHVUovejdBlfRgZoypjkLb3+IE0/QTfvl+sr7qPjawJzU+pzVPe6enaWetx+TTGy6p7vDt6fpJM3gV3UjP"
    b"HpHgKVZpCuVFeM8p8mVX8mFw/N8R3Qa5ZfxFuxAKttgbswxOF/cZx5sQhQcUmJ/Yf+b6bgvfFLDg80x/EOLjHWzJ/akVnT8qUvc6"
    b"N3a73xLVe2J2zcSb1Q2hblxJz7QDPVzI9fhn7SpKkmmD9H8l/9QOo4I74JmIF1VXaxQmdzjSaRfq35P/Hv/x/W+32uL7V3nAZiil"
    b"eur/4OITuuxhzKK71BIn3scbPaHCd6RaghDU8D3TXMVP3z/RQXW+lQTWboe5kioiZ2GfTZYEVfaGKJfGrncbOds9bFaCK+k1Ih1t"
    b"ZLD7yJKN4BibOM190E6hz8K92ri1IgFD+ILf4Zon+qzZxB2+HSX7s47MA5TRZ8RPLxEm8vfvb2qHg8E/5a7qLmJPtBy4g2FnzxLW"
    b"chf1euFe5NTnZ5ChhAoo+EJtmQ8J57mhIyj/dMbzmfr/HivSMB3gfUFP6OwCa3NWNtlHpdQze0Ty6LEbKj3vbLiQL9aRSzfqUs34"
    b"pTe8kC8RG/tdGvI11c0pToVccK95Uo65RgX3G8/QE9sPtcsG/VnDLETK2Qqu5GsmJVdMe53xaF2gh7JKr4xqngd7cYmz156bXM6e"
    b"YEA6e3TqPTrpfqZxzJm5Wsx2orhqcb1TxWyY8QZH6t82avmbWUW80H14U22xiHXjALZZ6jyEvWol/qgld/cCqljEn7SGGTxSXyXR"
    b"efc623ywnGmsAr7vXFlw38y7bnXHfLNSbVb7lU0oH+UO+caEyR48fonSN03SWS1i/nyER36BiWqj5q6FL1ijYK7Y1nHSHTqAb4eO"
    b"113xNvaTu8hn2ZUm5NBlzLZG+/15lni5BDfgll4tjT3qnTmiB77nn7TDu7VhijJhGrvBT6vEP7TRSZy20fz6PSp//f5bD8xgbuie"
    b"jLfkyZnJiU756Zv4nAKe2TVUF2eE2siFFpyjhnhzQYmQ4Lthr/2AS6XUp8bGCu7tEV3aD3SsD0/qjvrpI967LXzbEUykRV1j7+iw"
    b"26qLWPQN/8UCtqAmE6fs0ws+loExurIzajvruIcxTBc9ENCLnvhF+rmtfLPsBNhHXVkWtw1uI5u34P36J4VbbeX5jVjQxc0V96jB"
    b"MPJonsQ3+8I8yI7zFJwjHY/NfwSM/J1eKYVX2aOiHuguL2h+k+Thshlcm4Ku1njINc7CN9Hdy7NwC7qKZ7L2FRQhZaq/x808TI2O"
    b"3IICdsDbMOytV1BJpvg3LCMv5SyQRwVvy09YzirVJN4cd40hqt64z5eos/H+pB8iYrcngyaJp45X6A4KYUtWyN9niK49ce6xAzZD"
    b"ECZ4vqH2DY6dK5B1M2krnBMPcWvvRrt552rMho0YpTpb687DNFjNjosTnKRjjzuRAr7VHeRBUSgw156yfVMkPRNJpz99wrVthJ2p"
    b"I7Zr/b41gwF9zIVBfMAtKol4lJnbkNWzqKku0Mq9xpkyn2PPGD02IRRRP/qYjsiiK7M3fX6QS+1VG99/iUq9d/m5ndnZU4KaGFGt"
    b"oodSAfuX47p+5b6twCXCNrSrdE1fpNX4QT3cPtbWtzitk6qW/ow745Iu9IZ7xoW64Y47+kfmiPOopQu7rq/Ra7oj17uauulnNkxv"
    b"Gys8ooC7w2RVbPAKWumgF/0DbNnYkU/jtCPl79/rxR/E8O/AHTMU8g9F+hafqLBjasM8wR0Pr6Dbz0G+7QGwJ2NkZNA+Vmf+LUs2"
    b"h2yZP+rxjLvQ0yZxSitoFzpOo3FU+3mv5c/5B7uQHcHfo+vADR+QmrP6QRrnT9KRHWPXV7P3z8hwUPOOEXENfW0vdPwZXOjCPTBe"
    b"alXfFhXfe9ycFGYiPbMT9mwYrQ77P7xdxBylJ4uNe2fgUO9UJzt+7jp6X1bsgLJSdE9/f53t/X7MhFV8lwubeLPIxtzh0Rdx610T"
    b"/4Y58YINSVdFH88L7GPW3mm32b/UHS6kcPzp+xP+SZiVdfgXMmSNK2bJ9FcbsQuf954Kf02GqNGNL2D4giI/w+uuRHHfcdPc3RQw"
    b"M89wjeZTfTKtUHzVzVuiQh/AeQK3PfIJQ7X+8HgJM+OhAwz+Bgl+uuVsptH/dhnZXmON35jMD4xt8B1IUaEGN+gjfFaYsBzQKiSz"
    b"fcUDKgmjH/fYMV/jzP8iCZ+3/BMy9Jg9Cj5UJZ3CTR3Qk7JHYOfyOKc+n0d4VD9hSjigykGNZqxpCxNyjdsk6j/xn4FXGMFTFvT+"
    b"Bf+mjeqsR81wR1u5gvlpZptMgnN1gvZgYOOh1VhnfvdjPjFMG2XJ3J97GacE/D9djL8dFfkwjpF7bdD3+b3cZyob8yCOnXemLmq+"
    b"wyZqbio6yodmP2iB7jNNZdA8PxPxF2wAfI3TcO/k0gpGNnDK1cyf4Mw2w0ekuhGjg4fHyOz6evYMRljVW+T9+5kbU0JntsQP8gYz"
    b"0BIzrdFfRNeCNGLcK5TK5v2fQD0qvOmO6I8DQ+vcbBVVKZXhR2FQd+0C8Xy4K/Vp5+OP8gywZ4f3fy3xLAibHH1Wgh5yPm+aMJfX"
    b"4tDT0sVu6ItLdlOe4Z0W3Mo1CPAbc7kLpmlDnRmqAleEj1mqLZ5rFT871E13uJO98vY+9pLhU4V56cVMk1lEz8YK90/zR+MYVJee"
    b"+Rv+5NWSo+IJCvNvOhn28kuSHM/yY2RJPTt+13zCR/okb1cOdfgtsvQZW3nv6KhK9mQZE77htvosvGv5/R3+VR764bu/kGedr59m"
    b"DI2jZECl5tqbZVRK97GGvUdtc88ODTP37tRb/lRHTwC7AlXo0cOuxHtUWq6iN90mKuXTiF4P0Qssm8WeoA54gsMLU9/Byd9o9yvq"
    b"2Z7pgF30OHeuupOfwqaosJtlyr5TPfSNDaaTsmjyAPwGTlvpd823HReoq+0v/NiBFPwH9mDz1pU+pjkGHA6H6AqZzJRqdfSkbYkO"
    b"eVQKhTh2ijrvm+qLsMXIfzpHHGKEi3Ef+jhRJbXPFsfu82wy7KEDdwy2XuOBV84RnSpWJEve3RIvoQF/gYDCeuOuO+lBmfIVjuGJ"
    b"6esG7O4RRcboMrZgtu8If5ehJ3MfexaLd467IhN5ltnN0N3zQ33cCqU4RJ+RPdOeFecszBp0UckSerxeSOD8U5dgbndw4KW86l/w"
    b"yAj3q8JZ8w11cJglS5LgCTCfsA3amlD3D8wpBs3whix9ZT44jXmgYbNRwd6QBXxgwrbSYQxMRxG3IJWRccpQgzdMwK3A/LuZb+ma"
    b"U3FmNnbH2biAHT28Tqs4y1sl/w9QSwECFAMUAAAACAAAACFcBDsWPBUSAACYOAAADQAAAAAAAAAAAAAAgAEAAAAATWluZWNyYWZ0"
    b"LnR0ZlBLAQIUAxQAAAAIAAAAIVwTJLTva7wAAFTJAAAWAAAAAAAAAAAAAACAAUASAABtaWRuaWdodF9sYW5kc2NhcGUuanBnUEsB"
    b"AhQDFAAAAAgAAAAhXLXwWqhvUwAAbIIAABUAAAAAAAAAAAAAAIAB384AAHVpX2F1ZGlvL3NmeF9iYWNrLndhdlBLAQIUAxQAAAAI"
    b"AAAAIVwOVwoArA4AAMIgAAAWAAAAAAAAAAAAAACAAYEiAQB1aV9hdWRpby9zZnhfaG92ZXIud2F2UEsBAhQDFAAAAAgAAAAhXGoa"
    b"lyE3pQAALCsBAB0AAAAAAAAAAAAAAIABYTEBAHVpX2F1ZGlvL3NmeF9yZWxlYXNlX21haW4ud2F2UEsBAhQDFAAAAAgAAAAhXBRg"
    b"pU6CVgEALCYCABYAAAAAAAAAAAAAAIAB09YBAHVpX2F1ZGlvL3VpX2FwcGVhci53YXZQSwECFAMUAAAACAAAACFc0BeJhggaAQAs"
    b"wgEAGQAAAAAAAAAAAAAAgAGJLQMAdWlfYXVkaW8vdWlfZGlzYXBwZWFyLndhdlBLBQYAAAAABwAHANwBAADIRwQAAAA="
)


if __name__ == "__main__":
    try:
        prepare_assets()
        main()
    except Exception as error:
        if sys.stderr:
            traceback.print_exc()
        startup_error(f"Havoc Midnight could not start.\n\n{error}")
        raise SystemExit(1)
