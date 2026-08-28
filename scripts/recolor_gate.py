#!/usr/bin/env python3
"""Recolor the gate asset's flat material.

The real PQ gates are orange (#ff3200 per organizers, "95% the same as the
original sim"); the stock asset was pure blue. This edits every material's
pbrMetallicRoughness.baseColorFactor in assets/gate.glb, converting the
given sRGB hex to the linear color space glTF specifies. A one-time backup
of the original is kept next to it.

Usage:
    python scripts/recolor_gate.py            # -> #ff3200
    python scripts/recolor_gate.py '#00ff00'  # any hex
"""

import json
import shutil
import struct
import sys
from pathlib import Path

GLB = Path(__file__).resolve().parent.parent / "assets" / "gate.glb"
BACKUP = GLB.with_name("gate_original_blue.glb")
DEFAULT_HEX = "#ff3200"


def srgb_to_linear(c8: int) -> float:
    c = c8 / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def main():
    hexcol = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HEX).lstrip("#")
    rgb = [int(hexcol[i:i + 2], 16) for i in (0, 2, 4)]
    factor = [round(srgb_to_linear(c), 5) for c in rgb] + [1.0]

    data = GLB.read_bytes()
    magic, ver, total = struct.unpack("<III", data[:12])
    assert magic == 0x46546C67, "not a glb"
    clen, ctype = struct.unpack("<II", data[12:20])
    assert ctype == 0x4E4F534A, "first chunk not JSON"
    gltf = json.loads(data[20:20 + clen])
    rest = data[20 + clen:]

    if not BACKUP.exists():
        shutil.copy2(GLB, BACKUP)
        print(f"backup -> {BACKUP.name}")

    for m in gltf.get("materials", []):
        m.setdefault("pbrMetallicRoughness", {})["baseColorFactor"] = factor
        print(f"material {m.get('name', '?')[:24]}... -> "
              f"#{hexcol} linear={factor[:3]}")

    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)           # 4-byte alignment
    out = (struct.pack("<III", magic, ver, 12 + 8 + len(js) + len(rest))
           + struct.pack("<II", len(js), 0x4E4F534A) + js + rest)
    GLB.write_bytes(out)
    print(f"wrote {GLB.name} ({len(out)} bytes)")


if __name__ == "__main__":
    main()
