import re

with open(r'C:\Users\Admin\Documents\NekoFetch\thumbnail\temp.svg', 'rb') as f:
    svg = f.read().decode('utf-8', errors='ignore')

# Look for transform=matrix anywhere
matches = re.findall(r'transform="matrix\(([^"]+)\)"', svg)
print('Found', len(matches), 'matrix transforms')
for m in matches[:30]:
    print(m[:100])