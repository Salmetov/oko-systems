#!/usr/bin/env python3
"""One-time script: extract PNG from SVG and save as favicon.png"""
import base64, re, sys

svg_path = sys.argv[1] if len(sys.argv) > 1 else 'logo_exact.svg'
out_path = sys.argv[2] if len(sys.argv) > 2 else 'favicon.png'

with open(svg_path, 'r') as f:
    svg = f.read()

m = re.search(r'<image[^>]+href="data:image/png;base64,([^"]+)"', svg)
if not m:
    print("PNG not found in SVG")
    sys.exit(1)

data = base64.b64decode(m.group(1))
with open(out_path, 'wb') as f:
    f.write(data)

print(f"Saved {len(data)} bytes to {out_path}")
