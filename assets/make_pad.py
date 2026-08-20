from PIL import Image, ImageDraw, ImageFont

S = 1200
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def draw_pad(point_id, ink, bg, path, probe=True):
    img = Image.new("RGB", (S, S), bg)
    d = ImageDraw.Draw(img)

    # 1) outer frame : geometry reference + tone reference
    o0, o1 = 40, S - 40
    t = 66
    d.rectangle([o0, o0, o1, o1], outline=ink, width=t)

    i0, i1 = o0 + t, o1 - t

    # 2) orientation blocks : 3 of 4 corners
    b, pad = 72, 22
    for cx, cy in [(i0 + pad, i0 + pad),
                   (i1 - pad - b, i0 + pad),
                   (i0 + pad, i1 - pad - b)]:
        d.rectangle([cx, cy, cx + b, cy + b], fill=ink)

    # 3) point id
    f_id = ImageFont.truetype(FONT_B, 132)
    d.text((S / 2, i0 + 22 + b / 2), point_id, font=f_id, fill=ink, anchor="mm")

    # 4) optional probe line group (sensitivity comparison during trial)
    if probe:
        x0, x1 = 330, i1 - 30
        y = 940
        for w in [3, 7, 15, 32]:
            d.rectangle([x0, y, x1, y + w], fill=ink)
            y += w + 22

    img.save(path, dpi=(300, 300))


for tid in ["1078", "1079", "1080", "1081", "1082"]:
    draw_pad(tid, (0, 0, 0), (255, 255, 255), f"/mnt/user-data/outputs/pad_{tid}_white.png")
    draw_pad(tid, (255, 255, 255), (0, 0, 0), f"/mnt/user-data/outputs/pad_{tid}_black.png")
print("ok")
