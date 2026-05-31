"""
生成「句中词形分析」行首 Lucide 风格 PNG（48→24 抗锯齿），供 word_info_dialog 内嵌 base64。
运行：python tools/generate_lookup_icons.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

COLOR = (13, 110, 253, 255)  # #0d6efd
S = 48  # supersample
OUT = 24
ST = 3.2  # stroke ~1.6px @24


def _downsample(im: Image.Image) -> Image.Image:
    return im.resize((OUT, OUT), Image.Resampling.LANCZOS)


def _draw_tag() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    # 书签形标签 + 左下圆孔（示意 Lucide Tag）
    pts = [(14, 8), (34, 8), (38, 14), (38, 36), (24, 44), (10, 36), (10, 14)]
    dr.polygon(pts, outline=COLOR, width=int(ST))
    dr.ellipse((14, 28, 22, 36), outline=COLOR, width=int(ST))
    return _downsample(im)


def _draw_layers() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    # 三层平行四边形（示意 Lucide Layers）
    layers = [
        [(10, 30), (38, 22), (40, 28), (12, 36)],
        [(8, 22), (36, 14), (38, 20), (10, 28)],
        [(6, 14), (34, 6), (36, 12), (8, 20)],
    ]
    for p in layers:
        dr.polygon(p, outline=COLOR, width=int(ST))
    return _downsample(im)


def _draw_clock() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    pad = 6
    dr.ellipse(
        (pad, pad, S - pad, S - pad),
        outline=COLOR,
        width=int(ST),
    )
    cx, cy = S / 2, S / 2
    # 时针指向约 10 点
    dr.line((cx, cy, cx - 8, cy - 6), fill=COLOR, width=int(ST))
    # 分针指向约 3 点
    dr.line((cx, cy, cx + 10, cy - 2), fill=COLOR, width=int(ST))
    return _downsample(im)


def _draw_person() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    # 头圆 + 肩弧（示意 Lucide User）
    dr.ellipse((18, 8, 30, 20), outline=COLOR, width=int(ST))
    dr.arc((8, 22, 40, 46), start=200, end=340, fill=COLOR, width=int(ST))
    return _downsample(im)


def _draw_grid() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    m = 7
    x0, x1, x2, x3 = m, m + 11, m + 22, S - m
    y0, y1, y2, y3 = m, m + 11, m + 22, S - m
    for x in (x1, x2):
        dr.line((x, y0, x, y3), fill=COLOR, width=int(ST))
    for y in (y1, y2):
        dr.line((x0, y, x3, y), fill=COLOR, width=int(ST))
    dr.rectangle((x0, y0, x3, y3), outline=COLOR, width=int(ST))
    return _downsample(im)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "assets" / "lookup_icons"
    out_dir.mkdir(parents=True, exist_ok=True)
    makers = {
        "tag": _draw_tag,
        "layers": _draw_layers,
        "clock": _draw_clock,
        "person": _draw_person,
        "grid": _draw_grid,
    }
    for name, fn in makers.items():
        im = fn()
        im.save(out_dir / f"{name}.png", format="PNG", optimize=True)
    import runpy

    runpy.run_path(
        str(Path(__file__).resolve().parent / "embed_lookup_icons.py"),
        run_name="__main__",
    )


if __name__ == "__main__":
    main()
