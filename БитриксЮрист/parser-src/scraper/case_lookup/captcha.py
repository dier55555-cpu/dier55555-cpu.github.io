"""Решатели капчи для формы поиска дела."""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from pathlib import Path


class CaptchaSolver(ABC):
    @abstractmethod
    def solve(self, image_bytes: bytes) -> str:
        """Возвращает распознанный текст капчи."""


class TwoCaptchaSolver(CaptchaSolver):
    """Обёртка над 2captcha/rucaptcha. Нужен `pip install 2captcha-python`."""

    def __init__(self, api_key: str, timeout: int = 90):
        from twocaptcha import TwoCaptcha

        self._solver = TwoCaptcha(api_key)
        self._timeout = timeout

    def solve(self, image_bytes: bytes) -> str:
        if not image_bytes:
            raise ValueError("пустая картинка капчи")
        b64 = base64.b64encode(image_bytes).decode("ascii")
        # language=1 — кириллица (msudrf kcaptcha)
        result = self._solver.normal(
            b64,
            timeout=self._timeout,
            lang="ru",
            language=1,
            minLen=4,
            maxLen=8,
        )
        code = result["code"] if isinstance(result, dict) else str(result)
        return code.strip()


class ManualCaptchaSolver(CaptchaSolver):
    def __init__(self, save_dir: Path = Path("data/captcha")):
        self.save_dir = save_dir
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def solve(self, image_bytes: bytes) -> str:
        path = self.save_dir / "captcha.png"
        path.write_bytes(image_bytes)
        print(f"Капча сохранена в {path}. Откройте файл и введите код:")
        return input("Код капчи: ").strip()
