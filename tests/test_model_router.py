from __future__ import annotations

import unittest

from yixin.constants import (
    BUILTIN_PROMPT_TEMPLATES,
    MODE_DRESS_UP,
    MODE_REFERENCE,
    MODE_TEXT,
)
from yixin.model_router import (
    MODEL_NANO_BANANA_2,
    MODEL_NANO_BANANA_2_1,
    MODEL_NANO_BANANA_PRO,
    choose_model,
)
from yixin.settings import AUTO_STRATEGY_QUALITY, AUTO_STRATEGY_VALUE


class ModelRouterTests(unittest.TestCase):
    def _choose(
        self,
        *,
        strategy: str,
        prompt: str = "普通图片任务",
        mode: str = MODE_TEXT,
        references: int = 0,
    ) -> str:
        return choose_model(
            prompt=prompt,
            mode=mode,
            reference_count=references,
            strategy=strategy,
        ).model

    def test_quality_strategy_uses_pro_for_ordinary_reference_edits(self) -> None:
        self.assertEqual(
            self._choose(
                strategy=AUTO_STRATEGY_QUALITY,
                mode=MODE_REFERENCE,
                references=1,
            ),
            MODEL_NANO_BANANA_PRO,
        )
        self.assertEqual(
            self._choose(
                strategy=AUTO_STRATEGY_QUALITY,
                mode=MODE_TEXT,
            ),
            MODEL_NANO_BANANA_2,
        )

    def test_value_strategy_uses_nano_2_for_single_reference_edit(self) -> None:
        self.assertEqual(
            self._choose(
                strategy=AUTO_STRATEGY_VALUE,
                mode=MODE_REFERENCE,
                references=1,
            ),
            MODEL_NANO_BANANA_2,
        )

    def test_common_two_image_dress_up_uses_pro_in_both_strategies(self) -> None:
        prompt = BUILTIN_PROMPT_TEMPLATES[0][1]
        for strategy in (AUTO_STRATEGY_QUALITY, AUTO_STRATEGY_VALUE):
            with self.subTest(strategy=strategy):
                self.assertEqual(
                    self._choose(
                        strategy=strategy,
                        prompt=prompt,
                        mode=MODE_DRESS_UP,
                        references=2,
                    ),
                    MODEL_NANO_BANANA_PRO,
                )

    def test_quality_strategy_escalates_three_references(self) -> None:
        self.assertEqual(
            self._choose(
                strategy=AUTO_STRATEGY_QUALITY,
                mode=MODE_DRESS_UP,
                references=3,
            ),
            MODEL_NANO_BANANA_2_1,
        )

    def test_value_strategy_keeps_three_references_on_pro(self) -> None:
        self.assertEqual(
            self._choose(
                strategy=AUTO_STRATEGY_VALUE,
                mode=MODE_DRESS_UP,
                references=3,
            ),
            MODEL_NANO_BANANA_PRO,
        )

    def test_four_references_use_2_1_in_both_strategies(self) -> None:
        for strategy in (AUTO_STRATEGY_QUALITY, AUTO_STRATEGY_VALUE):
            with self.subTest(strategy=strategy):
                self.assertEqual(
                    self._choose(
                        strategy=strategy,
                        mode=MODE_DRESS_UP,
                        references=4,
                    ),
                    MODEL_NANO_BANANA_2_1,
                )

    def test_multiple_people_use_2_1_even_with_two_references(self) -> None:
        for strategy in (AUTO_STRATEGY_QUALITY, AUTO_STRATEGY_VALUE):
            with self.subTest(strategy=strategy):
                self.assertEqual(
                    self._choose(
                        strategy=strategy,
                        prompt="多个模特需要保持服装一致",
                        mode=MODE_DRESS_UP,
                        references=2,
                    ),
                    MODEL_NANO_BANANA_2_1,
                )

    def test_precise_text_uses_pro_first(self) -> None:
        for strategy in (AUTO_STRATEGY_QUALITY, AUTO_STRATEGY_VALUE):
            with self.subTest(strategy=strategy):
                self.assertEqual(
                    self._choose(
                        strategy=strategy,
                        prompt="生成海报，准确渲染品牌 logo 和标题文字",
                        mode=MODE_REFERENCE,
                        references=5,
                    ),
                    MODEL_NANO_BANANA_PRO,
                )

    def test_explicit_change_uses_pro_for_single_reference_value_strategy(
        self,
    ) -> None:
        self.assertEqual(
            self._choose(
                strategy=AUTO_STRATEGY_VALUE,
                prompt="更换背景并调整人物姿势",
                mode=MODE_REFERENCE,
                references=1,
            ),
            MODEL_NANO_BANANA_PRO,
        )

    def test_preservation_language_does_not_trigger_escalation(self) -> None:
        prompt = "保持人物身份、姿态、背景、服装面料、图案和细节不变"
        self.assertEqual(
            self._choose(
                strategy=AUTO_STRATEGY_VALUE,
                prompt=prompt,
                mode=MODE_REFERENCE,
                references=1,
            ),
            MODEL_NANO_BANANA_2,
        )


if __name__ == "__main__":
    unittest.main()
