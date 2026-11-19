import time
from pathlib import Path
import config
from video_processor import create_vertical_clip


def is_file_settled(path: Path, wait_seconds: int = config.STABLE_WAIT_SECONDS) -> bool:
    try:
        size_1 = path.stat().st_size
        time.sleep(wait_seconds)
        size_2 = path.stat().st_size
        return size_1 > 0 and size_1 == size_2
    except FileNotFoundError:
        return False


def prune_old_clips(max_keep: int = config.MAX_CLIPS_TO_KEEP) -> None:
    config.CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    clips = sorted(
        [p for p in config.CLIPS_DIR.iterdir() if p.is_file() and p.suffix.lower() in config.VIDEO_EXTENSIONS],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_clip in clips[max_keep:]:
        try:
            old_clip.unlink()
            print(f"[CLEANUP] Removed old clip: {old_clip.name}")
        except OSError as exc:
            print(f"[WARN] Could not remove {old_clip.name}: {exc}")


def process_once() -> None:
    config.REC_DIR.mkdir(parents=True, exist_ok=True)
    config.CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    for src in sorted(config.REC_DIR.iterdir()):
        if not src.is_file() or src.suffix.lower() not in config.VIDEO_EXTENSIONS:
            continue
        if not is_file_settled(src):
            continue

        out_file = config.CLIPS_DIR / f"{src.stem}_vertical.mp4"
        print(f"[PROCESS] {src.name} -> {out_file.name}")
        ok = create_vertical_clip(src, out_file)

        if ok:
            print(f"[DONE] Created {out_file.name}")
            if config.DELETE_PROCESSED_SOURCE:
                try:
                    src.unlink()
                    print(f"[CLEANUP] Deleted source recording: {src.name}")
                except OSError as exc:
                    print(f"[WARN] Could not delete {src.name}: {exc}")
            prune_old_clips()


def main() -> None:
    print(f"[WATCHER] Watching {config.REC_DIR} (1080x1920 split output)...")
    while True:
        process_once()
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()


