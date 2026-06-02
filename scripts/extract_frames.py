#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract video frames with ffmpeg into a local output directory.",
    )
    parser.add_argument("video", type=Path, help="Input video file path.")
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=30,
        help="Extract one frame every N source frames. Default: 30.",
    )
    parser.add_argument(
        "-s",
        "--seconds",
        type=float,
        default=None,
        help="Extract one frame every N seconds instead of using frame interval.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for extracted frames. Default: output.",
    )
    parser.add_argument(
        "--prefix",
        default="frame",
        help="Output filename prefix. Default: frame.",
    )
    parser.add_argument(
        "--format",
        choices=("jpg", "png"),
        default="jpg",
        help="Output image format. Default: jpg.",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=2,
        help="ffmpeg -q:v value for jpg output, 2 is high quality. Default: 2.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow ffmpeg to overwrite existing output files.",
    )
    args = parser.parse_args()

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        parser.error("ffmpeg not found in PATH. Install ffmpeg first.")

    video_path = args.video.expanduser().resolve()
    if not video_path.exists() or not video_path.is_file():
        parser.error(f"input video does not exist: {video_path}")

    if args.seconds is not None and args.seconds <= 0:
        parser.error("--seconds must be greater than 0")
    if args.seconds is None and args.interval < 1:
        parser.error("--interval must be at least 1")
    if args.quality < 2 or args.quality > 31:
        parser.error("--quality must be between 2 and 31")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = output_dir / f"{sanitize_prefix(args.prefix)}_%06d.{args.format}"

    if args.seconds is not None:
        frame_filter = f"fps=1/{args.seconds:g}"
        mode_label = f"every {args.seconds:g} seconds"
    else:
        frame_filter = f"select=not(mod(n\\,{args.interval}))"
        mode_label = f"every {args.interval} frames"

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if args.overwrite else "-n",
        "-i",
        str(video_path),
        "-vf",
        frame_filter,
        "-vsync",
        "vfr",
    ]
    if args.format == "jpg":
        command.extend(["-q:v", str(args.quality)])
    command.append(str(output_pattern))

    print(f"Extracting {mode_label} from {video_path}")
    print(f"Output: {output_dir}")
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        return exc.returncode

    frame_count = len(list(output_dir.glob(f"{sanitize_prefix(args.prefix)}_*.{args.format}")))
    print(f"Done. Found {frame_count} {args.format} frame(s) in {output_dir}")
    return 0


def sanitize_prefix(value: str) -> str:
    sanitized = "".join(char for char in value.strip() if char.isalnum() or char in {"_", "-"}).strip("_-")
    return sanitized or "frame"


if __name__ == "__main__":
    raise SystemExit(main())
