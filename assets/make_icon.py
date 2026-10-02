"""生成应用图标（PNG + 多尺寸 ICO）。

两种用法：

1. 从原图裁剪（默认）—— 常驻脚本，换图或换裁剪范围重跑即可：
       python assets/make_icon.py                    # 默认：整个徽标（含外圈圆环）
       python assets/make_icon.py --ring inner       # 只要中间那块图案
       python assets/make_icon.py --src 别的图.png

   裁剪范围是**自动检测**的，不靠手调比例：
     * 外圆 = 非白/非透明像素的外接正方形（整个徽标的外轮廓）；
     * 内圆 = 浅蓝色区域的边界（中间图案本体，用来排除外圈文字环）。
   遮罩半径恒等于所选圆的半径（见 build_icon 里的换算），
   所以圆环线正好落在图标边缘上，既不多露白底、也不少切图案。

   原图是**透明底 PNG** 也没问题：透明区的 RGB 实测是 225（不是纯黑），
   所以「非白像素」这条判据照样能算对外接框（2026-10-02 验过两种情况结果一致）。

2. 生成一个中性占位图标（手里没有合适的图时用）：
       python assets/make_icon.py --placeholder
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "assets" / "奇迹制造.png"
OUT_PNG = ROOT / "assets" / "app_icon.png"
OUT_ICO = ROOT / "assets" / "app.ico"

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

# 占位图标的配色（和界面主色一致）
PH_BG = (47, 111, 189)
PH_FG = (255, 255, 255)


def _non_white_box(arr) -> tuple[int, int, int, int]:
    mask = (arr < 235).any(axis=2)
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _blue_box(arr) -> tuple[int, int, int, int] | None:
    """浅蓝底（中间图案本体）的外接矩形。

    判据：蓝通道高 + 明显偏蓝 + 绿通道较高 —— 能排除黑色船身、红色波浪、灰白背景。
    """
    r = arr[:, :, 0].astype(int)
    g = arr[:, :, 1].astype(int)
    b = arr[:, :, 2].astype(int)
    mask = (b > 190) & (b - r > 40) & (g > 150)
    ys, xs = np.where(mask)
    if len(xs) < 100:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _square_around(cx: float, cy: float, half: float) -> tuple[int, int, int, int]:
    return (round(cx - half), round(cy - half), round(cx + half), round(cy + half))


def _circle_alpha(size: int, ratio: float = 1.0) -> Image.Image:
    """画圆形遮罩；ratio = 圆半径 / 半边长（1.0 就是内切圆）。

    4 倍超采样再缩小，边缘不会有锯齿。
    """
    big = size * 4
    mask = Image.new("L", (big, big), 0)
    c = big / 2
    r = c * ratio
    ImageDraw.Draw(mask).ellipse((c - r, c - r, c + r, c + r), fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def build_icon(src: Path, pad: float, size: int, circle: bool, ring: str = "outer") -> Image.Image:
    im = Image.open(src).convert("RGB")
    arr = np.array(im)

    ox0, oy0, ox1, oy1 = _non_white_box(arr)
    ocx, ocy = (ox0 + ox1) / 2, (oy0 + oy1) / 2
    orad = max(ox1 - ox0, oy1 - oy0) / 2
    print(f"外圆：直径 {orad * 2:.0f}px  圆心 ({ocx:.0f}, {ocy:.0f})  原图 {im.size}")

    if ring == "outer":
        cx, cy, rad = ocx, ocy, orad
        print("裁切范围：整个徽标（含外圈圆环）")
    else:
        inner = _blue_box(arr)
        if inner is None:
            print("⚠ 没检测到浅蓝底，改用外圆 × 0.78 估计内圆")
            cx, cy, rad = ocx, ocy, orad * 0.78
        else:
            ix0, iy0, ix1, iy1 = inner
            cx, cy = (ix0 + ix1) / 2, (iy0 + iy1) / 2
            rad = max(ix1 - ix0, iy1 - iy0) / 2
        print(f"裁切范围：中间图案  直径 {rad * 2:.0f}px  占外圆半径 {rad / orad:.3f}")

    half = rad * (1.0 + pad)
    box = _square_around(cx, cy, half)
    print(f"裁切框：{box}（边长 {box[2] - box[0]}px，外扩 {pad:.1%}）")

    canvas = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), (255, 255, 255))
    canvas.paste(im.crop(box), (0, 0))
    out = canvas.resize((size, size), Image.LANCZOS).convert("RGBA")
    if circle:
        # half * ratio == rad，即遮罩半径恒等于所选圆的半径：
        # 圆环线正好压在图标边缘上，既不露出圆外白底，也不切掉图案。
        out.putalpha(_circle_alpha(size, ratio=1.0 / (1.0 + pad)))
    return out


def build_placeholder(size: int) -> Image.Image:
    """中性占位图标：圆底 + 一个「作业清单」形状。

    刻意不画任何具体学校 / 品牌的东西 —— 它就是给公开仓库用的默认图标，
    谁要用自己的图标就跑默认模式，或者直接把这个文件替换掉。
    """
    big = size * 4          # 4 倍超采样，边缘不毛糙
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆形底
    pad = big * 0.04
    d.ellipse((pad, pad, big - pad, big - pad), fill=PH_BG)

    # 一张带三行文字的「清单」，整体居中
    w, h = big * 0.40, big * 0.46
    x0, y0 = (big - w) / 2, (big - h) / 2
    x1, y1 = x0 + w, y0 + h
    rad = big * 0.045
    d.rounded_rectangle((x0, y0, x1, y1), radius=rad, fill=PH_FG)

    line_h = big * 0.035
    gap = big * 0.075
    ly = y0 + h * 0.30
    for i in range(3):
        lw = w * (0.62 if i == 2 else 0.86)
        d.rounded_rectangle(
            (x0 + w * 0.12, ly - line_h / 2, x0 + w * 0.12 + lw, ly + line_h / 2),
            radius=line_h / 2, fill=PH_BG,
        )
        ly += gap

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(description="生成应用图标（默认从原图裁剪）")
    ap.add_argument("--src", default=str(DEFAULT_SRC), help="原图路径")
    ap.add_argument("--ring", choices=["outer", "inner"], default="outer",
                    help="outer=整个徽标（默认）；inner=只要中间图案")
    ap.add_argument("--pad", type=float, default=0.012,
                    help="裁切框比所选圆外扩多少（默认 0.012）")
    ap.add_argument("--size", type=int, default=512, help="PNG 边长")
    ap.add_argument("--no-circle", action="store_true", help="不裁成圆形（保留方角）")
    ap.add_argument("--placeholder", action="store_true",
                    help="生成中性占位图标（不用原图）")
    args = ap.parse_args()

    if args.placeholder:
        icon = build_placeholder(args.size)
        print("生成中性占位图标（没有使用任何原图）")
    else:
        src = Path(args.src)
        if not src.exists():
            print(f"找不到原图：{src}")
            print("没有原图的话可以生成一个中性占位图标："
                  "python assets/make_icon.py --placeholder")
            return 1

        global np
        import numpy as np  # noqa: PLC0415  放这里，便于 --help 时不加载

        icon = build_icon(src, args.pad, args.size, circle=not args.no_circle, ring=args.ring)

    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    icon.save(OUT_PNG)
    print(f"已生成 PNG：{OUT_PNG}  ({args.size}×{args.size})")

    icon.save(OUT_ICO, format="ICO", sizes=ICO_SIZES)
    print(f"已生成 ICO：{OUT_ICO}  ({len(ICO_SIZES)} 种尺寸: "
          + ", ".join(f"{w}×{h}" for w, h in ICO_SIZES) + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
