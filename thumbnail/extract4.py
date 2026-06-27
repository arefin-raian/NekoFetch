import re
import base64
import os

with open(r'C:\Users\Admin\Documents\NekoFetch\thumbnail\temp.svg', 'rb') as f:
    svg = f.read().decode('utf-8', errors='ignore')

# Find all images with matrix transforms
img_matrix = r'<g transform="matrix\(([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^)]+)\)"><g></g><image[^>]*xlink:href="data:image/([^;]+);base64,([^"]+)"[^>]*width="([^"]+)"[^>]*height="([^"]+)"'
images = re.findall(img_matrix, svg)

print('=== MAIN BACKGROUND IMAGE ===')
if images:
    # The background should be the largest image
    for i, img in enumerate(images):
        w = int(float(img[7]))
        h = int(float(img[8]))
        print(f"Image {i}: scaleX={img[0]}, scaleY={img[1]}, x={img[4]}, y={img[5]}, type={img[6]}, width={w}, height={h}")

# Find all g transform=matrix with images inside
all_matrix_imgs = re.findall(r'transform="matrix\(([^)]+)\)"[^>]*><g><image[^>]*xlink:href="data:image/([^;]+);base64,([^"]+)"[^>]*width="([^"]+)"[^>]*height="([^"]+)"', svg)
print(f'\n=== ALL IMAGE POSITIONS: {len(all_matrix_imgs)} ===')
for m in all_matrix_imgs[:30]:
    print(f"matrix=({m[0]}), type={m[1]}, w={m[2]}, h={m[3]}")

# Find translate transforms for text/logos
translate_pattern = r'<g transform="translate\(([^,]+),([^)]+)\)">'
translates = re.findall(translate_pattern, svg)
print(f'\n=== TRANSLATE POSITIONS: {len(translates)} ===')
for t in translates[:50]:
    print(f"x={t[0]}, y={t[1]}")