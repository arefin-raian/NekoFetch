import subprocess, json

files = [
    "playground/downloads/Naruto_Shippuden_Ep01_SUB_720p.mp4",
    "playground/downloads/Naruto_Shippuden_Ep01_DUB_1080p.mp4",
]

for f in files:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", f],
        capture_output=True, text=True,
    )
    d = json.loads(r.stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next(s for s in d["streams"] if s["codec_type"] == "audio")
    print(f"{f.split('/')[-1]}: {v['width']}x{v['height']}, "
          f"dur={d['format']['duration'][:8]}s, "
          f"vcodec={v['codec_name']}, acodec={a['codec_name']}")
