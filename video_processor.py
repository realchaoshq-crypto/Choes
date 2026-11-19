import subprocess
from pathlib import Path
import config


def build_split_filter() -> str:
    tw, th, tx, ty = config.TOP_CROP
    bw, bh, bx, by = config.BOTTOM_CROP
    half_h = config.HALF_HEIGHT
    out_w = config.OUTPUT_WIDTH

    return (
        f"[0:v]crop={tw}:{th}:{tx}:{ty},scale={out_w}:{half_h}:force_original_aspect_ratio=decrease,"
        f"pad={out_w}:{half_h}:(ow-iw)/2:(oh-ih)/2,setsar=1[top];"
        f"[0:v]crop={bw}:{bh}:{bx}:{by},scale={out_w}:{half_h}:force_original_aspect_ratio=decrease,"
        f"pad={out_w}:{half_h}:(ow-iw)/2:(oh-ih)/2,setsar=1[bot];"
        f"[top][bot]vstack=inputs=2,format=yuv420p[vout]"
    )


def create_vertical_clip(input_path: Path, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = build_split_filter()

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(config.CLIP_START_SECONDS),
        "-t", str(config.CLIP_DURATION_SECONDS),
        "-i", str(input_path),
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] FFmpeg failed on {input_path.name}:\n{result.stderr[-800:]}")
        return False
    return True
