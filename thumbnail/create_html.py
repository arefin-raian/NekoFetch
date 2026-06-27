import re
import base64

with open(r'C:\Users\Admin\Documents\NekoFetch\thumbnail\temp.svg', 'rb') as f:
    svg = f.read().decode('utf-8', errors='ignore')

# Replace xlink:href with href for HTML5 compatibility
svg = svg.replace('xlink:href=', 'href=')

# Write the SVG as-is to HTML
html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=1440, initial-scale=1.0">
    <title>Movie Template</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            background: #000;
        }}
        .template {{
            width: 1440px;
            height: 810px;
            position: relative;
            overflow: hidden;
        }}
        .editable {{
            cursor: pointer;
        }}
        .editable:hover {{
            outline: 2px dashed #00ff00;
        }}
    </style>
</head>
<body>
    <div class="template">
        {svg}
    </div>
</body>
</html>'''

with open(r'C:\Users\Admin\Documents\NekoFetch\thumbnail\template.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Template created: template.html")