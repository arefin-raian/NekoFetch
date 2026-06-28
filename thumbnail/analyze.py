"""Robust extractor for temp.svg (UTF-16 LE)."""
import re, base64, os, sys

with open(r'temp.svg', 'rb') as f:
    raw = f.read()
bom = raw[:2]
enc = 'utf-16-le' if bom == b'\xff\xfe' else 'utf-16-be' if bom == b'\xfe\xff' else 'utf-8'
svg = raw.decode(enc, errors='ignore')
print(f'Encoding: {enc}, len: {len(svg):,}')

m = re.search(r'<svg[^>]*\bwidth="([^"]+)"', svg)
print('width:', m.group(1) if m else '-')
m = re.search(r'<svg[^>]*\bheight="([^"]+)"', svg)
print('height:', m.group(1) if m else '-')
m = re.search(r'<svg[^>]*\bviewBox="([^"]+)"', svg)
print('viewBox:', m.group(1) if m else '-')

# Strip ALL base64 data first for easier regex
svg_nob64 = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+?"', 'data:image/BASE64"', svg)

# Count
print(f'<g> count: {len(re.findall(r"<g[ >]", svg_nob64))}')
print(f'<text> count: {len(re.findall(r"<text[ >]", svg_nob64))}')
print(f'<image> count: {len(re.findall(r"<image[ >]", svg_nob64))}')
print(f'<circle> count: {len(re.findall(r"<circle[ >]", svg_nob64))}')
print(f'<path> count: {len(re.findall(r"<path[ >]", svg_nob64))}')

# Grab each <image> opening tag fully and dump it
print('\n=== <image> OPENING TAGS (first 25) ===')
for i, m in enumerate(re.finditer(r'<image\b[^>]*>', svg_nob64)):
    if i >= 25: break
    tag = m.group(0)
    w = re.search(r'width="([^"]+)"', tag)
    h = re.search(r'height="([^"]+)"', tag)
    x = re.search(r'x="([^"]+)"', tag)
    y = re.search(r'y="([^"]+)"', tag)
    href_short = re.search(r'data:image/([^;]+);base64,', tag)
    print(f'  #{i:02d}: w={w.group(1) if w else "-"} h={h.group(1) if h else "-"} '
          f'x={x.group(1) if x else "-"} y={y.group(1) if y else "-"} type={href_short.group(1) if href_short else "-"}')

# Find IMMEDIATE enclosing <g transform=...> for the first 25 images
print('\n=== <image> ENCLOSING <g TRANSFORM> ===')
img_iter = list(re.finditer(r'<image\b[^>]*>', svg_nob64))
for i, im in enumerate(img_iter[:25]):
    pos = im.start()
    window = svg_nob64[max(0, pos-800):pos]
    # Find last <g transform=... > before pos
    parents = list(re.finditer(r'<g\b[^>]*\btransform="([^"]+)"[^>]*>', window))
    if parents:
        last = parents[-1]
        t = last.group(1)
        # Display
        print(f'  img#{i:02d}: t="{t[:80]}"')
    else:
        print(f'  img#{i:02d}: (no parent g with transform in 800-char window)')

# All text elements (open tag + content)
print('\n=== TEXT ELEMENTS (first 80) ===')
for i, m in enumerate(re.finditer(r'<text\b([^>]*)>([^<]*)</text>', svg_nob64)):
    if i >= 80: break
    a, txt = m.group(1), m.group(2)
    t = re.search(r'\btransform="([^"]+)"', a)
    fs = re.search(r'\bfont-size="([^"]+)"', a)
    ff = re.search(r'\bfont-family="([^"]+)"', a)
    fill = re.search(r'\bfill="([^"]+)"', a)
    print(f'  #{i:02d}: t="{ (t.group(1) if t else "-")[:55]}" txt="{txt[:30]}" '
          f'fs={fs.group(1) if fs else "-"} ff={(ff.group(1) if ff else "-")[:18]} '
          f'fill={fill.group(1) if fill else "-"}')

# Bare matrix transforms on any element (Inkscape)
print('\n=== ALL BARE-MATRIX TRANSFORMS WITH 6 NUMBERS (first 30) ===')
ctr = 0
for m in re.finditer(r'transform="(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?(?:[ ,]-?\d+(?:\.\d+)?(?:e[+-]?\d+)?){5})"', svg_nob64):
    if ctr >= 30: break
    parts = [float(x.strip()) for x in re.split(r'[ ,]', m.group(1))]
    a,b,c,d,e,f = parts[:6]
    print(f'  #{ctr:02d}: a={a:8.4f} b={b:8.4f} c={c:8.4f} d={d:8.4f} e={e:9.2f} f={f:9.2f}')
    ctr += 1

# All translate transforms
print('\n=== ALL TRANSLATE TRANSFORMS (first 30) ===')
ctr = 0
for m in re.finditer(r'transform="translate\(([^)]+)\)"', svg_nob64):
    if ctr >= 30: break
    print(f'  #{ctr:02d}: {m.group(1)}')
    ctr += 1

# Circle elements
print('\n=== <circle> TAGS (first 30) ===')
for i, m in enumerate(re.finditer(r'<circle\b[^>]*/?>', svg_nob64)):
    if i >= 30: break
    print(f'  #{i}: {m.group(0)[:120]}')

# Path elements (in particular <text> paths or clip paths)
print('\n=== <path> SUMMARIES (first 30) ===')
for i, m in enumerate(re.finditer(r'<path\b[^>]*\bd="([^"]+)"', svg_nob64)):
    if i >= 30: break
    d = m.group(1)
    print(f'  #{i}: d="{d[:110]}"')

# Now actually extract images
print('\n=== EXTRACTING BASE64 IMAGES ===')
os.makedirs('images', exist_ok=True)
# Find ALL data:image hits and the surrounding <image ...> tag (look forward/back ~500 chars for width/height)
img_iter = list(re.finditer(r'data:image/([^;]+);base64,([A-Za-z0-9+/=]+)"', svg))
print(f'Found {len(img_iter)} base64 images')
for i, m in enumerate(img_iter):
    ty, b64 = m.group(1), m.group(2)
    pos = m.start()
    # Look back for the enclosing <image ... >
    back = svg[max(0, pos-500):pos]
    # Most recent <image
    img_tag_match = re.search(r'<image([^>]*)$', back)
    img_attrs = img_tag_match.group(1) if img_tag_match else ''
    w = re.search(r'width="([^"]+)"', img_attrs)
    h = re.search(r'height="([^"]+)"', img_attrs)
    x = re.search(r'\bx="([^"]+)"', img_attrs)
    y = re.search(r'\by="([^"]+)"', img_attrs)
    # Look further back for parent <g transform
    parents = list(re.finditer(r'<g\b[^>]*\btransform="([^"]+)"[^>]*>', back))
    parent_t = parents[-1].group(1) if parents else '-'
    ext = 'jpg' if 'jpeg' in ty else 'png'
    out = f'images/img_{i:02d}.{ext}'
    if not os.path.exists(out):
        with open(out, 'wb') as fp:
            fp.write(base64.b64decode(b64))
    print(f'  img #{i:02d} type={ty:>4} sz~{len(b64)*3//4:>8}  '
          f'w={w.group(1) if w else "-"} h={h.group(1) if h else "-"} '
          f'x={x.group(1) if x else "-"} y={y.group(1) if y else "-"} '
          f'pt="{parent_t[:60]}" -> {out}')
