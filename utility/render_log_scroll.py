#!/usr/bin/env python3
"""Render a tail -f style log scroll video from a log file.

Fixed terminal viewport: new lines appear at the bottom and push older lines up
(like `tail -f`), not a camera pan over a tall image.

Drop logs into media/log-scrolls/inputs/, then:

  python utility/render_log_scroll.py media/log-scrolls/inputs/my.log
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")

BG = (18, 18, 22)
FG = (210, 214, 220)
DIM = (120, 128, 140)
YELLOW = (230, 190, 80)
BLUE = (110, 160, 240)
GREEN = (120, 200, 140)
RED = (230, 110, 110)
TITLE = (160, 170, 185)
CHROME_BG = (28, 28, 34)

LEVEL_COLORS = {
    "DEBUG": BLUE,
    "INFO": GREEN,
    "WARNING": YELLOW,
    "WARN": YELLOW,
    "ERROR": RED,
    "CRITICAL": RED,
}


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def load_lines(path: Path) -> list[str]:
    text = path.read_bytes().decode("utf-8", errors="replace")
    lines = [strip_ansi(line.rstrip("\n\r")) for line in text.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines or ["(empty log)"]


def pick_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Monaco.ttf",
        "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def font_px(font: ImageFont.ImageFont, fallback: int) -> int:
    size = getattr(font, "size", None)
    return int(size) if size else fallback


def color_for_line(line: str) -> tuple[int, int, int]:
    upper = line.upper()
    for level, color in LEVEL_COLORS.items():
        if level in upper:
            return color
    if line.startswith("---") or line.startswith("==="):
        return DIM
    return FG


def truncate(line: str, max_chars: int) -> str:
    if len(line) <= max_chars:
        return line
    return line[: max_chars - 1] + "…"


def draw_chrome(draw: ImageDraw.ImageDraw, *, width: int, chrome_h: int, title: str, font: ImageFont.ImageFont) -> None:
    draw.rectangle((0, 0, width, chrome_h), fill=CHROME_BG)
    for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        x = 14 + i * 18
        draw.ellipse((x, chrome_h // 2 - 5, x + 10, chrome_h // 2 + 5), fill=color)
    draw.text((70, (chrome_h - font_px(font, 14)) // 2 - 1), title, font=font, fill=TITLE)
    draw.line((0, chrome_h - 1, width, chrome_h - 1), fill=(50, 50, 58))


def visible_window(lines: list[str], revealed: int, visible_lines: int) -> list[str]:
    """Lines currently on screen after `revealed` lines have streamed in (1-based count)."""
    end = max(0, min(revealed, len(lines)))
    start = max(0, end - visible_lines)
    return lines[start:end]


def paint_frame(
    *,
    width: int,
    height: int,
    chrome_h: int,
    pad_x: int,
    pad_top: int,
    line_height: int,
    window: list[str],
    title: str,
    font: ImageFont.ImageFont,
    font_title: ImageFont.ImageFont,
    max_chars: int,
) -> Image.Image:
    """Terminal buffer: fill from the top; newest line is always the last row drawn."""
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    draw_chrome(draw, width=width, chrome_h=chrome_h, title=title, font=font_title)

    y = chrome_h + pad_top
    for line in window:
        draw.text(
            (pad_x, y),
            truncate(line, max_chars),
            font=font,
            fill=color_for_line(line),
        )
        y += line_height
    return img


def revealed_count_for_frame(
    frame_i: int,
    total_frames: int,
    n_lines: int,
    hold_frames: int,
) -> int:
    """How many log lines have appeared by this frame (discrete appends, then hold)."""
    stream_frames = max(1, total_frames - hold_frames)
    if frame_i >= stream_frames:
        return n_lines
    # Spread line reveals evenly across the streaming portion
    # frame 0 → 1 line; last stream frame → all lines
    if n_lines <= 1:
        return n_lines
    progress = frame_i / max(1, stream_frames - 1)
    return 1 + int(progress * (n_lines - 1))


def encode_tail_f(
    lines: list[str],
    *,
    out_mp4: Path,
    duration_s: float,
    visible_lines: int,
    width: int,
    fps: int,
    font_size: int,
    title: str,
    hold_s: float,
) -> None:
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg not found on PATH — install via brew install ffmpeg")

    font = pick_font(font_size)
    font_title = pick_font(14)
    line_height = font_size + 8
    chrome_h = 36
    pad_x = 20
    pad_top = 12
    body_h = visible_lines * line_height + pad_top * 2
    height = chrome_h + body_h
    # even dims for yuv420p
    width -= width % 2
    height -= height % 2

    approx_char_w = max(1, font_px(font, font_size) * 6 // 10)
    max_chars = max(20, (width - 2 * pad_x) // approx_char_w)

    total_frames = max(1, int(round(duration_s * fps)))
    hold_frames = min(total_frames // 2, max(0, int(round(hold_s * fps))))

    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
    print(
        f"Encoding tail -f MP4 → {out_mp4.name}  "
        f"({total_frames} frames, {len(lines)} lines, hold {hold_s:.1f}s)"
    )
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None

    last_revealed = -1
    try:
        for frame_i in range(total_frames):
            revealed = revealed_count_for_frame(frame_i, total_frames, len(lines), hold_frames)
            if revealed != last_revealed:
                window = visible_window(lines, revealed, visible_lines)
                frame = paint_frame(
                    width=width,
                    height=height,
                    chrome_h=chrome_h,
                    pad_x=pad_x,
                    pad_top=pad_top,
                    line_height=line_height,
                    window=window,
                    title=title,
                    font=font,
                    font_title=font_title,
                    max_chars=max_chars,
                )
                frame_bytes = frame.tobytes()
                last_revealed = revealed
            proc.stdin.write(frame_bytes)
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        code = proc.wait()
        if code != 0:
            raise SystemExit(f"ffmpeg failed ({code}):\n{stderr[-2000:]}")
    except BrokenPipeError as exc:
        stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        raise SystemExit(f"ffmpeg pipe broke:\n{stderr[-2000:]}") from exc


def maybe_gif(mp4: Path, gif: Path, fps: int = 12) -> None:
    palette = gif.with_suffix(".palette.png")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(mp4),
            "-vf",
            f"fps={fps},scale=960:-1:flags=lanczos,palettegen=stats_mode=diff",
            str(palette),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(mp4),
            "-i",
            str(palette),
            "-lavfi",
            f"fps={fps},scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5",
            "-loop",
            "0",
            str(gif),
        ],
        check=True,
    )
    palette.unlink(missing_ok=True)


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    default_out_dir = repo / "media" / "log-scrolls" / "outputs"

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_file", type=Path, help="Path to log / .output file")
    parser.add_argument("--out-dir", type=Path, default=default_out_dir)
    parser.add_argument("--duration", type=float, default=120.0, help="Seconds (default 120)")
    parser.add_argument("--visible-lines", type=int, default=10, help="Lines in viewport")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--font-size", type=int, default=18)
    parser.add_argument(
        "--hold",
        type=float,
        default=3.0,
        help="Seconds to hold on final frame after last line (default 3)",
    )
    parser.add_argument(
        "--gif",
        dest="make_gif",
        action="store_true",
        default=False,
        help="Also write animated GIF (large; prefer MP4)",
    )
    args = parser.parse_args()

    log_path = args.log_file.expanduser().resolve()
    if not log_path.is_file():
        raise SystemExit(f"Log file not found: {log_path}")

    lines = load_lines(log_path)
    stem = log_path.stem
    out_dir = args.out_dir
    out_mp4 = out_dir / f"{stem}__scroll-{int(args.duration)}s.mp4"
    out_gif = out_dir / f"{stem}__scroll-{int(args.duration)}s.gif"
    title = f"tail -f  {log_path.name}"

    print(f"Lines: {len(lines)}  |  visible: {args.visible_lines}  |  {args.duration}s @ {args.fps}fps")
    encode_tail_f(
        lines,
        out_mp4=out_mp4,
        duration_s=args.duration,
        visible_lines=args.visible_lines,
        width=args.width,
        fps=args.fps,
        font_size=args.font_size,
        title=title,
        hold_s=args.hold,
    )
    print(f"Wrote {out_mp4}  ({out_mp4.stat().st_size / (1024 * 1024):.1f} MB)")

    if args.make_gif:
        print(f"Encoding GIF → {out_gif.name}")
        maybe_gif(out_mp4, out_gif)
        print(f"Wrote {out_gif}  ({out_gif.stat().st_size / (1024 * 1024):.1f} MB)")


if __name__ == "__main__":
    main()
