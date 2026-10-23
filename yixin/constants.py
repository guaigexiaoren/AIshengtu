from __future__ import annotations

APP_NAME = "亦欣AI生图工作台"
APP_ORGANIZATION = "亦欣"

API_BASE_URL = "https://liuguang.ai/v1"
GENERATION_ENDPOINT = "/images/generations"

MODEL_OPTIONS = (
    ("Nano Banana 2.1", "gemini-nano-banana-2.1"),
    ("Nano Banana 2", "gemini-3.1-flash-image"),
    ("Nano Banana Pro", "gemini-3-pro-image"),
)
DEFAULT_MODEL = "gemini-3-pro-image"
MODEL_IDS = frozenset(model_id for _, model_id in MODEL_OPTIONS)

ASPECT_RATIOS = (
    "auto",
    "1:1",
    "3:2",
    "4:3",
    "5:4",
    "16:9",
    "21:9",
    "2:3",
    "3:4",
    "4:5",
    "9:16",
)
DEFAULT_ASPECT_RATIO = "3:4"

RESOLUTIONS = ("auto", "1K", "2K", "4K")
DEFAULT_RESOLUTION = "2K"

MAX_BATCH_SIZE = 4
MAX_REFERENCE_IMAGES = 14
MAX_BATCH_ASSETS = 50
DEFAULT_BATCH_SIZE = 1

TASK_QUEUED = "queued"
TASK_RUNNING = "running"
TASK_SUCCESS = "success"
TASK_FAILED = "failed"
TASK_CANCELLED = "cancelled"
TASK_STATUSES = frozenset(
    {TASK_QUEUED, TASK_RUNNING, TASK_SUCCESS, TASK_FAILED, TASK_CANCELLED}
)

MODE_TEXT = "text"
MODE_REFERENCE = "reference"
MODE_DRESS_UP = "dress_up"
MODE_LABELS = {
    MODE_TEXT: "文字生图",
    MODE_REFERENCE: "参考图编辑",
    MODE_DRESS_UP: "批量换装",
}

STATUS_LABELS = {
    TASK_QUEUED: "排队中",
    TASK_RUNNING: "执行中",
    TASK_SUCCESS: "成功",
    TASK_FAILED: "失败",
    TASK_CANCELLED: "已取消",
}

CONNECT_TIMEOUT_SECONDS = 15
REQUEST_TIMEOUT_SECONDS = 300
DOWNLOAD_ATTEMPTS = 3

TEMP_RETENTION_DAYS = 7
MAX_API_KEY_LENGTH = 512
MIN_API_KEY_LENGTH = 10
