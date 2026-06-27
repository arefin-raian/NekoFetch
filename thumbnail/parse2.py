import re

with open(r'C:\Users\Admin\Documents\NekoFetch\thumbnail\temp.svg', 'rb') as f:
    svg = f.read().decode('utf-8', errors='ignore')

# Find all g transform=matrix elements
matrix_pattern = r'<g transform="matrix\(([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^)]+)\)"'
matrices = re.findall(matrix_pattern, svg)

print('=== MATRIX TRANSFORMS (first 50) ===')
for m in matrices[:50]:
    print(f'scaleX={m[0]}, scaleY={m[1]}, rot={m[2]}, rot={m[3]}, x={m[4]}, y={m[5]}')