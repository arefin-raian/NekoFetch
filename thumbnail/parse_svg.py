import re
import base64
import os

with open(r'C:\Users\Admin\Documents\NekoFetch\thumbnail\temp.svg', 'rb') as f:
    svg = f.read().decode('utf-8', errors='ignore')

matches = re.findall(r'transform="([^"]+)"', svg)
print('Found', len(matches), 'transforms')
for m in matches[:50]:
    print(m[:100])

# Extract all image elements with transform
img_pattern = r'<image[^>]*xlink:href="data:image/([^;]+);base64,([^"]+)"[^>]*width="([^"]+)"[^>]*height="([^"]+)"[^>]*transform="([^"]*)"'
images = re.findall(img_pattern, svg)

# Also get images without transform
img_pattern2 = r'<image[^>]*xlink:href="data:image/([^;]+);base64,([^"]+)"[^>]*width="([^"]+)"[^>]*height="([^"]+)"[^>]*/'
img_pattern3 = r'<g[^>]*transform="([^"]+)".*?<image[^>]*xlink:href="data:image/([^;]+);base64,([^"]+)"[^>]*width="([^"]+)"[^>]*height="([^"]+)"[^>]*/'

# Get all transforms with images
g_img_pattern = r'<g transform="([^"]+)"><g>.*?</g><image[^>]*xlink:href="data:image/([^;]+);base64,([^"]+)"[^>]*width="([^"]+)"[^>]*height="([^"]+)"'
g_images = re.findall(g_img_pattern, svg, re.DOTALL)

print('=== IMAGES WITH TRANSFORMS ===')
for img in g_images[:20]:
    print(f"Transform: {img[0]}, Type: {img[1]}, Width: {img[3]}, Height: {img[4]}")

# Extract all transforms to understand layout
transform_pattern = r'<g transform="translate\(([^,]+),([^)]+)\)"'
transforms = re.findall(transform_pattern, svg)

print('\n=== TRANSLATE TRANSFORMS (first 30) ===')
for t in transforms[:30]:
    print(f"x={t[0]}, y={t[1]}")

# Extract text content
text_pattern = r'<text[^>]*>([^<]+)</text>'
texts = re.findall(text_pattern, svg)

print('\n=== TEXT CONTENT ===')
for t in texts[:30]:
    print(t)