from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REC_DIR = BASE_DIR / "rec"
CLIPS_DIR = BASE_DIR / "clips"

VIDEO_EXTENSIONS = {".mp4", ".ts", ".mkv", ".mov"}
POLL_INTERVAL_SECONDS = 3
STABLE_WAIT_SECONDS = 2

# 1080x1920 vertical split output (960 + 960)
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
HALF_HEIGHT = OUTPUT_HEIGHT // 2

# Clip timing (in seconds)
CLIP_START_SECONDS = 0
CLIP_DURATION_SECONDS = 30

# Crop regions: (width, height, x, y)
TOP_CROP = (1280, 720, 0, 0)
BOTTOM_CROP = (1280, 720, 0, 0)

# Disk & cleanup guardrails
DELETE_PROCESSED_SOURCE = True
MAX_CLIPS_TO_KEEP = 20
