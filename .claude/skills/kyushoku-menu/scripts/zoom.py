#!/usr/bin/env python3
"""配膳図の一部を切り出して拡大する。

紙を撮った写真やスクリーンショットは、等倍のままだと日付や献立名を読み違える。
読みたい範囲だけを切り出して拡大すると、格段に読めるようになる。

使い方:
    python3 zoom.py IMAGE --region L T R B [--out OUT] [--scale N] [--rotate DEG]

  --region は左上(L,T)と右下(R,B)を画像全体に対する比率(0〜1)で指定する。
      例) 左上の4分の1        : --region 0 0 0.5 0.5
          上から13%〜35%の帯 : --region 0 0.13 1 0.35

  --rotate は横向きに撮った写真を起こすとき。時計回りの度数。
      例) 反時計回りに寝ている写真を起こす: --rotate -90

出力先を省くと、元画像と同じ場所に <元の名前>_zoom.png として保存する。
保存したPNGは Read ツールで開いて読む。
"""

import argparse
import os
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow が必要です:  pip install Pillow")

# 拡大しすぎると表示側で縮小され、かえって読めなくなる。
MAX_WIDTH = 1900
MAX_HEIGHT = 2000


def main() -> None:
    p = argparse.ArgumentParser(description="配膳図の一部を切り出して拡大する")
    p.add_argument("image", help="配膳図の画像ファイル")
    p.add_argument(
        "--region",
        nargs=4,
        type=float,
        metavar=("L", "T", "R", "B"),
        default=[0.0, 0.0, 1.0, 1.0],
        help="切り出す範囲を比率(0〜1)で。左 上 右 下。既定は全体",
    )
    p.add_argument("--out", help="出力先PNG。省略時は <元の名前>_zoom.png")
    p.add_argument(
        "--scale",
        type=float,
        default=0.0,
        help="拡大率。省略時は表示上限に収まるよう自動で決める",
    )
    p.add_argument(
        "--rotate",
        type=float,
        default=0.0,
        help="回転させる度数（時計回り）。横向きの写真を起こすときに使う",
    )
    args = p.parse_args()

    im = Image.open(args.image)
    if args.rotate:
        # PIL の rotate は反時計回りなので符号を反転して「時計回り」に揃える
        im = im.rotate(-args.rotate, expand=True)

    w, h = im.size
    left, top, right, bottom = args.region
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        sys.exit("--region は 0〜1 で、左<右・上<下 になるように指定してください")

    box = (int(w * left), int(h * top), int(w * right), int(h * bottom))
    crop = im.crop(box)
    if crop.width == 0 or crop.height == 0:
        sys.exit("切り出した範囲が空です。--region を見直してください")

    scale = args.scale
    if scale <= 0:
        scale = min(MAX_WIDTH / crop.width, MAX_HEIGHT / crop.height)
        scale = max(scale, 1.0)  # 縮小はしない

    new_size = (max(1, int(crop.width * scale)), max(1, int(crop.height * scale)))
    crop = crop.resize(new_size, Image.LANCZOS)

    out = args.out
    if not out:
        base, _ = os.path.splitext(args.image)
        out = base + "_zoom.png"
    crop.convert("RGB").save(out)

    print(f"保存: {out}")
    print(f"  元画像 {w}x{h} → 切り出し {box} → 出力 {crop.width}x{crop.height}"
          f"（拡大 {scale:.2f}倍）")
    print("  Read ツールでこのPNGを開いて読んでください。")


if __name__ == "__main__":
    main()
