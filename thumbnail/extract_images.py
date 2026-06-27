import re
import base64
import os

with open(r'C:\Users\Admin\Documents\NekoFetch\thumbnail\temp.svg', 'rb') as f:
    svg = f.read().decode('utf-8', errors='ignore')

# Extract all base64 images with their full context
img_pattern = r'<g transform="matrix\(([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^)]+)\)">\s*<g></g>\s*<image[^>]*xlink:href="data:image/([^;]+);base64,([^"]+)"[^>]*width="([^"]+)"[^>]*height="([^"]+)"'
images = re.findall(img_pattern, svg)

print(f"Found {len(images)} images")

# Create images directory
os.makedirs(r'C:\Users\Admin\Documents\NekoFetch\thumbnail\images', exist_ok=True)

# Extract and save each image
for i, img in enumerate(images):
    img_type = img[6] if '.' in img[6] else 'png'
    ext = 'jpg' if 'jpeg' in img_type else 'png'
    b64_data = img[7]
    
    # Save image
    path = rf'C:\Users\Admin\Documents\NekoFetch\thumbnail\images\img_{i}.{ext}'
    with open(path, 'wb') as f:
        f.write(base64.b64decode(b64_data))
    print(f"Saved img_{i}.{ext}: x={img[4]}, y={img[5]}, w={img[8]}, h={img[9]}")

# Also look for embedded images without matrix
simple_img_pattern = r'<image[^>]*xlink:href="data:image/([^;]+);base64,([^"]+)"[^>]*/>'
simple_imgs = re.findall(simple_img_pattern, svg)
print(f"\nFound {len(simple_imgs)} additional images")

for i, img in enumerate(simple_imgs[:10]):
    img_type = img[0]
    ext = 'jpg' if 'jpeg' in img_type else 'png'
    b64_data = img[1]
    
    path = rf'C:\Users\Admin\Documents\NekoFetch\thumbnail\images\bg_{i}.{ext}'
    with open(path, 'wb') as f:
        f.write(base64.b64decode(b64_data))
    print(f"Saved bg_{i}.{ext}")