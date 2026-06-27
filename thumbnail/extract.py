import re
import base64
import os

with open(r'C:\Users\Admin\Documents\NekoFetch\thumbnail\temp.svg', 'rb') as f:
    svg = f.read().decode('utf-8', errors='ignore')

# Extract base64 images with their positions
# Pattern for images inside g tags with transforms
g_img_pattern = r'<g transform="matrix\(([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^)]+)\)"><g><image[^>]*xlink:href="data:image/([^;]+);base64,([^"]+)"[^>]*width="([^"]+)"[^>]*height="([^"]+)"'
g_images = re.findall(g_img_pattern, svg)

print('=== IMAGES WITH MATRIX TRANSFORMS ===')
for i, img in enumerate(g_images[:20]):
    print(f"Image {i}: scaleX={img[0]}, scaleY={img[1]}, x={img[4]}, y={img[5]}, type={img[6]}, w={img[7]}, h={img[8]}")

# Extract all base64 images
all_imgs_pattern = r'xlink:href="data:image/([^;]+);base64,([^"]+)"'
all_imgs = re.findall(all_imgs_pattern, svg)
print(f'\n=== TOTAL IMAGES: {len(all_imgs)} ===')