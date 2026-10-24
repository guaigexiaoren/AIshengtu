from __future__ import annotations

import re
from dataclasses import dataclass

from .constants import (
    MODE_DRESS_UP,
    MODE_FREE_COMPOSE,
    MODE_REFERENCE,
    MODE_TEXT,
)
from .settings import AUTO_STRATEGY_VALUE

MODEL_NANO_BANANA_2 = "gemini-3.1-flash-image"
MODEL_NANO_BANANA_2_1 = "gemini-nano-banana-2.1"
MODEL_NANO_BANANA_PRO = "gemini-3-pro-image"

_PRECISION_PATTERNS = (
    re.compile(r"(?<![A-Za-z])(?:logo|slogan)(?![A-Za-z])", re.IGNORECASE),
    re.compile(r"(?:品牌名称|包装设计|包装文字|海报|标题文字|宣传语|版式)"),
    re.compile(r"(?:精确|准确|清晰|可读).{0,6}(?:文字|字体)"),
    re.compile(r"(?:添加|生成|写上|排版|放置).{0,12}(?:文字|标题|标语|标志)"),
)
_CONSISTENCY_PATTERNS = (
    re.compile(r"(?:多个?|多位)(?:人物|角色|模特)|多人"),
    re.compile(r"(?:多件|多套|多个)服装"),
    re.compile(
        r"(?:服装|人物|角色|模特).{0,8}(?:保持一致|一致性)|"
        r"(?:一致|统一).{0,8}(?:服装|人物|角色|模特)"
    ),
)
_EDIT_PATTERNS = (
    re.compile(
        r"(?:更换|替换|改变|修改|重做)(?:人物|角色|模特)?(?:的)?"
        r"(?:背景|场景|姿势|动作|体型|身材|表情|主体)"
    ),
    re.compile(
        r"(?:背景|场景|姿势|动作|体型|身材|表情).{0,10}"
        r"(?:改为|换成|替换成|变成|调整)"
    ),
    re.compile(
        r"(?:增加|添加|移除|删除).{0,8}(?:人物|角色|模特|主体)"
    ),
)


@dataclass(frozen=True)
class ModelDecision:
    model: str
    strategy: str
    reason: str


def _matches(patterns: tuple[re.Pattern[str], ...], prompt: str) -> bool:
    return any(pattern.search(prompt) for pattern in patterns)


def choose_model(
    *,
    prompt: str,
    mode: str,
    reference_count: int,
    strategy: str,
) -> ModelDecision:
    precise_layout = _matches(_PRECISION_PATTERNS, prompt)
    consistency = _matches(_CONSISTENCY_PATTERNS, prompt)
    explicit_edit = _matches(_EDIT_PATTERNS, prompt)

    if precise_layout:
        return ModelDecision(
            MODEL_NANO_BANANA_PRO,
            strategy,
            "需要精确文字或版式，选择 Nano Banana Pro。",
        )

    if strategy == AUTO_STRATEGY_VALUE:
        if consistency or reference_count >= 4:
            return ModelDecision(
                MODEL_NANO_BANANA_2_1,
                strategy,
                "多图一致性要求较高，选择 Nano Banana 2.1。",
            )
        if (
            explicit_edit
            or reference_count >= 2
            or mode in (MODE_DRESS_UP, MODE_FREE_COMPOSE)
        ):
            return ModelDecision(
                MODEL_NANO_BANANA_PRO,
                strategy,
                "需要参考图编辑或换装，选择 Nano Banana Pro。",
            )
        return ModelDecision(
            MODEL_NANO_BANANA_2,
            strategy,
            "单图普通编辑或文字生图，选择 Nano Banana 2。",
        )

    if consistency or reference_count >= 3:
        return ModelDecision(
            MODEL_NANO_BANANA_2_1,
            strategy,
            "多图一致性要求较高，选择 Nano Banana 2.1。",
        )
    if reference_count or mode in (
        MODE_REFERENCE,
        MODE_DRESS_UP,
        MODE_FREE_COMPOSE,
    ):
        return ModelDecision(
            MODEL_NANO_BANANA_PRO,
            strategy,
            "参考图编辑或换装，选择 Nano Banana Pro。",
        )
    if mode == MODE_TEXT:
        return ModelDecision(
            MODEL_NANO_BANANA_2,
            strategy,
            "纯文字生图，选择 Nano Banana 2。",
        )
    return ModelDecision(
        MODEL_NANO_BANANA_PRO,
        strategy,
        "未识别的任务类型，保守选择 Nano Banana Pro。",
    )
