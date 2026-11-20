import argparse
import re
import shutil
import subprocess
import time
from collections import deque
from pathlib import Path
from config import REC_DIR
from quota_cleanup import (
    can_generate_clip,
    cleanup_expired_clips,
    record_clip_created,
)

DEFAULT_STREAMERS = [
    {
        "name": "IShowSpeed",
        "urls": [
            "https://www.youtube.com/@IShowSpeed/live",
            "https://www.twitch.tv/ishowspeed",
        ],
    },
    {
        "name": "Kai Cenat",
        "urls": [
            "https://www.twitch.tv/kaicenat",
            "https://www.youtube.com/@KaiCenatLive/live",
        ],
    },
    {
        "name": "N3on",
        "urls": [
            "https://www.twitch.tv/n3on",
            "https://kick.com/n3on",
            "https://www.youtube.com/@n3on/live",
        ],
    },
    {
        "name": "xQc",
        "urls": [
            "https://www.twitch.tv/xqc",
            "https://www.youtube.com/@xqcow/live",
        ],
    },
    {
        "name": "Jynxzi",
        "urls": [
            "https://www.twitch.tv/jynxzi",
            "https://www.youtube.com/@Jynxzi/live",
        ],
    },
]

SPIKE_MULTIPLIER = 2.8
MIN_MSGS_PER_MIN = 30.0
LOUD_DB_THRESHOLD = -14.0
CLIP_SECONDS = 30
COOLDOWN_SECONDS = 180
SAMPLE_WINDOW_SECONDS = 25
IDLE_SLEEP_SECONDS = 15


def measure_audio_max_db(video_path: Path) -> float | None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(video_path),
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", proc.stderr)
    if not match:
        return None
    return float(match.group(1))


def capture_stream_segment(stream_url: str, out_tmp: Path, duration: int = CLIP_SECONDS) -> bool:
    out_tmp.parent.mkdir(parents=True, exist_ok=True)
    if out_tmp.exists():
        out_tmp.unlink()

    if shutil.which("streamlink"):
        cmd = [
            "streamlink",
            "--hls-duration",
            str(duration),
            "-o",
            str(out_tmp),
            stream_url,
            "best",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 35)
        if res.returncode == 0 and out_tmp.exists() and out_tmp.stat().st_size > 0:
            return True

    if shutil.which("yt-dlp"):
        cmd = [
            "yt-dlp",
            "--quiet",
            "--no-warnings",
            "-f",
            "best[height<=720]/best",
            "-o",
            str(out_tmp),
            stream_url,
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 15)
        except subprocess.TimeoutExpired:
            pass
        if out_tmp.exists() and out_tmp.stat().st_size > 0:
            return True

    return False

def is_stream_live(url: str) -> bool:
    try:
        res = subprocess.run(
            ["yt-dlp", "--no-warnings", "--ignore-no-formats-error", "--print", "live_status", url],
            capture_output=True,
            text=True,
            timeout=12,
        )
        return "is_live" in res.stdout.strip().lower()
    except Exception:
        return False


def check_url_for_hype(
    streamer_name: str,
    url: str,
    msg_times: deque[float],
    rate_history: deque[float],
    last_clip_ts: dict[str, float],
    sample_seconds: int = SAMPLE_WINDOW_SECONDS,
) -> bool:
        try:
            if not is_stream_live(url):
                print(f"[OFFLINE] Skipping offline URL: {url}", flush=True)
                return False
            from chat_downloader import ChatDownloader
        except ImportError:
            print("[WARN] chat-downloader not installed", flush=True)
            return False
        start_poll = time.time()
        saw_any_msg = False

        try:
            chat = ChatDownloader().get_chat(url, message_groups=["messages"])
            for msg in chat:
                now = time.time()
                saw_any_msg = True
                msg_times.append(now)

            while msg_times and now - msg_times[0] > 60.0:
                msg_times.popleft()

            current_rate = float(len(msg_times))
            baseline = (sum(rate_history) / len(rate_history)) if len(rate_history) >= 5 else current_rate
            rate_history.append(current_rate)

            is_spike = (
                current_rate >= MIN_MSGS_PER_MIN
                and baseline > 0
                and (current_rate / baseline) >= SPIKE_MULTIPLIER
            )

            if is_spike and (now - last_clip_ts.get(streamer_name, 0.0) >= COOLDOWN_SECONDS):
                allowed, reason = can_generate_clip(streamer_name)
                if not allowed:
                    print(f"[QUOTA] {streamer_name}: {reason}")
                    return True

                print(
                    f"[HYPE] {streamer_name} spike! rate={current_rate:.1f}/m vs "
                    f"base={baseline:.1f}/m ({current_rate / max(baseline, 1e-6):.2f}x)"
                )

                tmp_file = Path(f"/tmp/{streamer_name.lower().replace(' ', '_')}_{int(now)}.mp4")
                if not capture_stream_segment(url, tmp_file, duration=CLIP_SECONDS):
                    print(f"[CAPTURE] Failed to capture from {url}")
                    tmp_file.unlink(missing_ok=True)
                    return True

                peak_db = measure_audio_max_db(tmp_file)
                print(f"[AUDIO] {streamer_name} max_volume={peak_db} dB (threshold={LOUD_DB_THRESHOLD} dB)")
                if peak_db is not None and peak_db < LOUD_DB_THRESHOLD:
                    print(f"[AUDIO] Quiet audio; dropping {tmp_file.name}")
                    tmp_file.unlink(missing_ok=True)
                    return True

                REC_DIR.mkdir(parents=True, exist_ok=True)
                dest_file = REC_DIR / tmp_file.name
                shutil.move(str(tmp_file), str(dest_file))
                last_clip_ts[streamer_name] = time.time()
                quota_state = record_clip_created(streamer_name)
                print(f"[HANDOFF] -> {dest_file} | Quota: {quota_state}")
                return True

            # Rotate to the next streamer after a short sample window so all 5 get checked
            if time.time() - start_poll >= sample_seconds:
                return True
        except Exception as exc:
            if saw_any_msg:
                print(f"[CHAT] {streamer_name} ({url}) ended/interrupted: {exc}")
            return False

        return saw_any_msg


def run_auto_loop(single_name: str | None = None, single_url: str | None = None) -> None:
    last_clip_ts: dict[str, float] = {}
    msg_buffers: dict[str, deque[float]] = {s["name"]: deque() for s in DEFAULT_STREAMERS}
    rate_buffers: dict[str, deque[float]] = {s["name"]: deque(maxlen=30) for s in DEFAULT_STREAMERS}

    if single_url:
        name = single_name or "CustomStreamer"
        msg_buffers.setdefault(name, deque())
        rate_buffers.setdefault(name, deque(maxlen=30))
        while True:
            cleanup_expired_clips()
            check_url_for_hype(
                name,
                single_url,
                msg_buffers[name],
                rate_buffers[name],
                last_clip_ts,
                sample_seconds=60,
            )
            time.sleep(2)

    print("[AUTO] Watching 5 streamers (up to 7/streamer, 35/day, 24h auto-cleanup)...")
    while True:
        cleanup_expired_clips()
        any_live = False

        for streamer in DEFAULT_STREAMERS:
            name = streamer["name"]
            allowed, reason = can_generate_clip(name)
            if not allowed:
                continue

            for url in streamer["urls"]:
                live_or_checked = check_url_for_hype(
                    name,
                    url,
                    msg_buffers[name],
                    rate_buffers[name],
                    last_clip_ts,
                    sample_seconds=SAMPLE_WINDOW_SECONDS,
                )
                if live_or_checked:
                    any_live = True
                    break

        if not any_live:
            print(f"[IDLE] None of the 5 streamers had active chat in this pass. Sleeping {IDLE_SLEEP_SECONDS}s...")
            time.sleep(IDLE_SLEEP_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-monitor 5 streamers for hype clips.")
    parser.add_argument("--url", default=None, help="Optional single live URL override")
    parser.add_argument("--name", default=None, help="Optional streamer label with --url")
    args = parser.parse_args()

    cleanup_expired_clips()
    run_auto_loop(single_name=args.name, single_url=args.url)


if __name__ == "__main__":
    main()
