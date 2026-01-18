from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw


@dataclass(frozen=True)
class BBox:
    left: int
    top: int
    right: int
    bottom: int

    def width(self) -> int:
        return self.right - self.left

    def height(self) -> int:
        return self.bottom - self.top


def _find_plot_bbox_in_region(
    rgb: np.ndarray,
    x_min_frac: float,
    x_max_frac: float,
    y_min_frac: float,
    y_max_frac: float,
    dark_threshold: int,
    row_frac_threshold: float,
    col_frac_threshold: float,
) -> BBox:
    h, w, _ = rgb.shape
    x0 = int(w * x_min_frac)
    x1 = int(w * x_max_frac)
    y0 = int(h * y_min_frac)
    y1 = int(h * y_max_frac)

    roi = rgb[y0:y1, x0:x1, :]
    gray = (
        0.299 * roi[:, :, 0].astype(np.float32)
        + 0.587 * roi[:, :, 1].astype(np.float32)
        + 0.114 * roi[:, :, 2].astype(np.float32)
    )
    mask = gray < float(dark_threshold)

    row_frac = mask.mean(axis=1)
    col_frac = mask.mean(axis=0)

    row_candidates = np.where(row_frac >= float(row_frac_threshold))[0]
    col_candidates = np.where(col_frac >= float(col_frac_threshold))[0]

    if row_candidates.size == 0 or col_candidates.size == 0:
        raise RuntimeError(
            "Could not auto-detect plot bbox. Try passing --bbox-left/top/right/bottom."
        )

    top = int(y0 + row_candidates.min())
    bottom = int(y0 + row_candidates.max())
    left = int(x0 + col_candidates.min())
    right = int(x0 + col_candidates.max())

    # Add a small margin so we include the border line itself.
    pad = 2
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(w - 1, right + pad)
    bottom = min(h - 1, bottom + pad)

    return BBox(left=left, top=top, right=right, bottom=bottom)


def _find_plot_bbox_right_half(
    rgb: np.ndarray,
    x_min_frac: float,
    y_min_frac: float,
    y_max_frac: float,
    dark_threshold: int,
    row_frac_threshold: float,
    col_frac_threshold: float,
) -> BBox:
    return _find_plot_bbox_in_region(
        rgb=rgb,
        x_min_frac=x_min_frac,
        x_max_frac=1.0,
        y_min_frac=y_min_frac,
        y_max_frac=y_max_frac,
        dark_threshold=dark_threshold,
        row_frac_threshold=row_frac_threshold,
        col_frac_threshold=col_frac_threshold,
    )


def _find_plot_bbox_left_half(
    rgb: np.ndarray,
    x_max_frac: float,
    y_min_frac: float,
    y_max_frac: float,
    dark_threshold: int,
    row_frac_threshold: float,
    col_frac_threshold: float,
) -> BBox:
    return _find_plot_bbox_in_region(
        rgb=rgb,
        x_min_frac=0.0,
        x_max_frac=x_max_frac,
        y_min_frac=y_min_frac,
        y_max_frac=y_max_frac,
        dark_threshold=dark_threshold,
        row_frac_threshold=row_frac_threshold,
        col_frac_threshold=col_frac_threshold,
    )


def _refine_bbox_to_plot_box(
    rgb: np.ndarray,
    bbox: BBox,
    dark_threshold: int,
    col_line_frac_threshold: float,
    row_line_frac_threshold: float,
) -> BBox:
    """
    Refine a coarse bbox (which may include axis labels) to the inner plot box
    by snapping to the darkest vertical/horizontal lines (borders/gridlines).
    """
    h, w, _ = rgb.shape
    crop = rgb[bbox.top : bbox.bottom, bbox.left : bbox.right, :]
    if crop.size == 0:
        return bbox

    gray = (
        0.299 * crop[:, :, 0].astype(np.float32)
        + 0.587 * crop[:, :, 1].astype(np.float32)
        + 0.114 * crop[:, :, 2].astype(np.float32)
    )
    mask = gray < float(dark_threshold)

    ch, cw = mask.shape
    y0 = int(ch * 0.10)
    y1 = int(ch * 0.95)
    x0 = int(cw * 0.10)
    x1 = int(cw * 0.95)

    col_band = mask[y0:y1, :]
    row_band = mask[:, x0:x1]

    col_frac = col_band.mean(axis=0)
    row_frac = row_band.mean(axis=1)

    col_candidates = np.where(col_frac >= float(col_line_frac_threshold))[0]
    row_candidates = np.where(row_frac >= float(row_line_frac_threshold))[0]

    if col_candidates.size == 0 or row_candidates.size == 0:
        return bbox

    left_inner = int(col_candidates.min())
    right_inner = int(col_candidates.max())
    top_inner = int(row_candidates.min())
    bottom_inner = int(row_candidates.max())

    # Guard against pathological results
    if right_inner - left_inner < int(cw * 0.30) or bottom_inner - top_inner < int(ch * 0.30):
        return bbox

    return BBox(
        left=max(0, bbox.left + left_inner),
        top=max(0, bbox.top + top_inner),
        right=min(w - 1, bbox.left + right_inner),
        bottom=min(h - 1, bbox.top + bottom_inner),
    )


def _read_uv_series(excel_path: str) -> tuple[np.ndarray, np.ndarray]:
    df = pd.read_excel(excel_path)
    needed = {"Wavelength", "UV Response"}
    missing = needed.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in XLSX: {sorted(missing)}")

    uv = df.loc[df["UV Response"].notna(), ["Wavelength", "UV Response"]].copy()
    uv = uv.sort_values("Wavelength")

    x = uv["Wavelength"].to_numpy(dtype=float)
    y = uv["UV Response"].to_numpy(dtype=float)
    return x, y


def _read_als_series(excel_path: str) -> tuple[np.ndarray, np.ndarray]:
    df = pd.read_excel(excel_path)
    needed = {"Wavelength", "ALS response"}
    missing = needed.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in XLSX: {sorted(missing)}")

    als = df.loc[df["ALS response"].notna(), ["Wavelength", "ALS response"]].copy()
    als = als.sort_values("Wavelength")

    x = als["Wavelength"].to_numpy(dtype=float)
    y = als["ALS response"].to_numpy(dtype=float)
    return x, y


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Overlay digitized UV and ALS responses from XLSX on top of the plots in ltr390_response.png"
    )
    parser.add_argument(
        "--image",
        type=str,
        default="ltr390_response.png",
        help="Path to the response PNG.",
    )
    parser.add_argument(
        "--excel",
        type=str,
        default="spectral_response_digitized.xlsx",
        help="Path to the digitized XLSX.",
    )
    parser.add_argument(
        "--out-full",
        type=str,
        default="uv_response_overlay_full.png",
        help="Output path for full-image overlay (now includes BOTH UV and ALS curves).",
    )
    parser.add_argument(
        "--out-zoom",
        type=str,
        default="uv_response_overlay_zoom_axes.png",
        help="Output path for UV zoomed overlay (with axes).",
    )
    parser.add_argument(
        "--out-zoom-als",
        type=str,
        default="als_response_overlay_zoom_axes.png",
        help="Output path for ALS zoomed overlay (with axes).",
    )
    parser.add_argument(
        "--out-debug",
        type=str,
        default="uv_response_bbox_debug.png",
        help="Output path for bbox debug image (shows BOTH plot bboxes).",
    )

    # Axis mapping for the UV response panel in the image
    parser.add_argument("--x-min", type=float, default=250.0)
    parser.add_argument("--x-max", type=float, default=550.0)

    # Axis mapping for the ALS response panel in the image
    parser.add_argument("--als-x-min", type=float, default=300.0)
    parser.add_argument("--als-x-max", type=float, default=1100.0)

    parser.add_argument("--y-min", type=float, default=0.0)
    parser.add_argument("--y-max", type=float, default=1.1)
    parser.add_argument(
        "--y-data-unit-max",
        type=float,
        default=1.0,
        help=(
            "Max value represented by the digitized y-units. "
            "If your digitized data is normalized 0..1 but the image axis is 0..1.1, "
            "leave this at 1.0 and set --y-max 1.1 (default)."
        ),
    )
    parser.add_argument(
        "--y-scale-mode",
        type=str,
        choices=["multiply", "divide"],
        default="divide",
        help=(
            "How to apply the y scale factor (y_max / y_data_unit_max) to the digitized data. "
            "Use 'multiply' when digitized 1.0 should map to image 1.1; use 'divide' for the inverse."
        ),
    )

    # Auto-detection tuning (works for the provided ltr390_response.png)
    parser.add_argument("--x-min-frac", type=float, default=0.55)
    parser.add_argument("--als-x-max-frac", type=float, default=0.48)
    parser.add_argument("--y-min-frac", type=float, default=0.12)
    parser.add_argument("--y-max-frac", type=float, default=0.80)
    parser.add_argument("--dark-threshold", type=int, default=150)
    parser.add_argument("--row-frac-threshold", type=float, default=0.12)
    parser.add_argument("--col-frac-threshold", type=float, default=0.10)

    # Manual bbox override (pixel coords in the source image)
    parser.add_argument("--bbox-left", type=int, default=-1)
    parser.add_argument("--bbox-top", type=int, default=-1)
    parser.add_argument("--bbox-right", type=int, default=-1)
    parser.add_argument("--bbox-bottom", type=int, default=-1)
    parser.add_argument("--als-bbox-left", type=int, default=-1)
    parser.add_argument("--als-bbox-top", type=int, default=-1)
    parser.add_argument("--als-bbox-right", type=int, default=-1)
    parser.add_argument("--als-bbox-bottom", type=int, default=-1)

    args = parser.parse_args()

    img = Image.open(args.image).convert("RGB")
    rgb = np.array(img)

    if args.bbox_left >= 0 and args.bbox_top >= 0 and args.bbox_right >= 0 and args.bbox_bottom >= 0:
        bbox_uv = BBox(
            left=int(args.bbox_left),
            top=int(args.bbox_top),
            right=int(args.bbox_right),
            bottom=int(args.bbox_bottom),
        )
    else:
        bbox_uv = _find_plot_bbox_right_half(
            rgb=rgb,
            x_min_frac=float(args.x_min_frac),
            y_min_frac=float(args.y_min_frac),
            y_max_frac=float(args.y_max_frac),
            dark_threshold=int(args.dark_threshold),
            row_frac_threshold=float(args.row_frac_threshold),
            col_frac_threshold=float(args.col_frac_threshold),
        )
        bbox_uv = _refine_bbox_to_plot_box(
            rgb=rgb,
            bbox=bbox_uv,
            dark_threshold=max(int(args.dark_threshold), 220),
            col_line_frac_threshold=0.90,
            row_line_frac_threshold=0.75,
        )

    if (
        args.als_bbox_left >= 0
        and args.als_bbox_top >= 0
        and args.als_bbox_right >= 0
        and args.als_bbox_bottom >= 0
    ):
        bbox_als = BBox(
            left=int(args.als_bbox_left),
            top=int(args.als_bbox_top),
            right=int(args.als_bbox_right),
            bottom=int(args.als_bbox_bottom),
        )
    else:
        bbox_als = _find_plot_bbox_left_half(
            rgb=rgb,
            x_max_frac=float(args.als_x_max_frac),
            y_min_frac=float(args.y_min_frac),
            y_max_frac=float(args.y_max_frac),
            dark_threshold=int(args.dark_threshold),
            row_frac_threshold=float(args.row_frac_threshold),
            col_frac_threshold=float(args.col_frac_threshold),
        )
        bbox_als = _refine_bbox_to_plot_box(
            rgb=rgb,
            bbox=bbox_als,
            dark_threshold=max(int(args.dark_threshold), 220),
            col_line_frac_threshold=0.90,
            row_line_frac_threshold=0.75,
        )

    x_uv, y_uv = _read_uv_series(args.excel)
    x_als, y_als = _read_als_series(args.excel)
    y_scale = float(args.y_max) / float(args.y_data_unit_max)
    if args.y_scale_mode == "multiply":
        y_uv = y_uv * y_scale
        y_als = y_als * y_scale
    else:
        y_uv = y_uv / y_scale
        y_als = y_als / y_scale

    # Debug: draw bbox on the original image
    debug = img.copy()
    draw = ImageDraw.Draw(debug)
    draw.rectangle(
        [bbox_uv.left, bbox_uv.top, bbox_uv.right, bbox_uv.bottom],
        outline=(0, 255, 255),
        width=3,
    )
    draw.rectangle(
        [bbox_als.left, bbox_als.top, bbox_als.right, bbox_als.bottom],
        outline=(255, 0, 255),
        width=3,
    )
    debug.save(args.out_debug)

    # Build full-image overlay: background is original image, a transparent axes sits exactly on the UV plot bbox.
    import matplotlib.pyplot as plt

    w, h = img.size
    dpi = 150
    fig = plt.figure(figsize=(w / dpi, h / dpi), dpi=dpi)

    bg_ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    bg_ax.imshow(img)
    bg_ax.set_axis_off()

    # UV overlay (right plot)
    left = bbox_uv.left / w
    width = bbox_uv.width() / w
    bottom = 1.0 - (bbox_uv.bottom / h)
    height = bbox_uv.height() / h

    overlay_ax = fig.add_axes([left, bottom, width, height])
    overlay_ax.set_facecolor((0, 0, 0, 0))
    overlay_ax.patch.set_alpha(0.0)

    crop_uv = rgb[bbox_uv.top : bbox_uv.bottom, bbox_uv.left : bbox_uv.right, :]
    overlay_ax.plot(x_uv, y_uv, color="#00FFFF", linewidth=2.0)
    overlay_ax.set_xlim(float(args.x_min), float(args.x_max))
    overlay_ax.set_ylim(float(args.y_min), float(args.y_max))
    overlay_ax.set_aspect("auto")
    overlay_ax.set_axis_off()

    # ALS overlay (left plot)
    als_left = bbox_als.left / w
    als_width = bbox_als.width() / w
    als_bottom = 1.0 - (bbox_als.bottom / h)
    als_height = bbox_als.height() / h

    overlay_ax_als = fig.add_axes([als_left, als_bottom, als_width, als_height])
    overlay_ax_als.set_facecolor((0, 0, 0, 0))
    overlay_ax_als.patch.set_alpha(0.0)
    overlay_ax_als.plot(x_als, y_als, color="#FF00FF", linewidth=2.0)
    overlay_ax_als.set_xlim(float(args.als_x_min), float(args.als_x_max))
    overlay_ax_als.set_ylim(float(args.y_min), float(args.y_max))
    overlay_ax_als.set_aspect("auto")
    overlay_ax_als.set_axis_off()

    fig.savefig(args.out_full, pad_inches=0.0)
    plt.close(fig)

    # Zoomed overlay: show the cropped plot region with real axes, then draw the digitized curve on top.
    fig2, ax2 = plt.subplots(figsize=(8.5, 4.6), dpi=150)
    ax2.imshow(
        crop_uv,
        extent=[float(args.x_min), float(args.x_max), float(args.y_min), float(args.y_max)],
        origin="upper",
        aspect="auto",
    )
    ax2.plot(x_uv, y_uv, color="#00FFFF", linewidth=2.5)
    ax2.set_xlim(float(args.x_min), float(args.x_max))
    ax2.set_ylim(float(args.y_min), float(args.y_max))
    ax2.set_xlabel("Wavelength [nm]")
    ax2.set_ylabel("Normalized responsivity")
    ax2.grid(False)
    fig2.tight_layout()
    fig2.savefig(args.out_zoom)
    plt.close(fig2)

    crop_als = rgb[bbox_als.top : bbox_als.bottom, bbox_als.left : bbox_als.right, :]
    fig3, ax3 = plt.subplots(figsize=(10.5, 4.6), dpi=150)
    ax3.imshow(
        crop_als,
        extent=[
            float(args.als_x_min),
            float(args.als_x_max),
            float(args.y_min),
            float(args.y_max),
        ],
        origin="upper",
        aspect="auto",
    )
    ax3.plot(x_als, y_als, color="#FF00FF", linewidth=2.5)
    ax3.set_xlim(float(args.als_x_min), float(args.als_x_max))
    ax3.set_ylim(float(args.y_min), float(args.y_max))
    ax3.set_xlabel("Wavelength [nm]")
    ax3.set_ylabel("Normalized responsivity")
    ax3.grid(False)
    fig3.tight_layout()
    fig3.savefig(args.out_zoom_als)
    plt.close(fig3)

    print(
        f"Detected UV plot bbox: left={bbox_uv.left}, top={bbox_uv.top}, right={bbox_uv.right}, bottom={bbox_uv.bottom} (px)"
    )
    print(
        f"Detected ALS plot bbox: left={bbox_als.left}, top={bbox_als.top}, right={bbox_als.right}, bottom={bbox_als.bottom} (px)"
    )
    print(
        f"Applied y scale: {y_scale:.6g} (mode={args.y_scale_mode}, y_data_unit_max={float(args.y_data_unit_max):.6g} -> y_max={float(args.y_max):.6g})"
    )
    print(f"Wrote: {args.out_debug}")
    print(f"Wrote: {args.out_full}")
    print(f"Wrote: {args.out_zoom}")
    print(f"Wrote: {args.out_zoom_als}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


