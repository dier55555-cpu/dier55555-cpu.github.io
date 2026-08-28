"""Решатели капчи для формы поиска дела.

По наблюдениям сторонних разработчиков (см. README) капча на сайтах судов —
обычно простая картинка с искажённым текстом (не reCAPTCHA), и на некоторых
сайтах (например, Санкт-Петербурга) она общая на регион, а не на каждый запрос.
Поэтому решение капчи имеет смысл кэшировать в рамках сессии/cookies, а не
решать заново на каждый вызов инструмента.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class CaptchaSolver(ABC):
    @abstractmethod
    def solve(self, image_bytes: bytes) -> str:
        """Возвращает распознанный текст капчи."""


class TwoCaptchaSolver(CaptchaSolver):
    """Обёртка над сервисом 2captcha/rucaptcha (платный, но дешёвый и быстрый
    для простых текстовых капч). Требует `pip install 2captcha-python`.
    """

    def __init__(self, api_key: str, timeout: int = 60):
        from twocaptcha import TwoCaptcha  # локальный импорт, чтобы зависимость была опциональной

        self._solver = TwoCaptcha(api_key)
        self._timeout = timeout

    def solve(self, image_bytes: bytes) -> str:
        result = self._solver.normal(image_bytes, timeout=self._timeout)
        return result["code"].strip()


class ManualCaptchaSolver(CaptchaSolver):
    """Режим без платного сервиса: сохраняет картинку капчи на диск и просит
    оператора ввести код в консоли. Подходит для разовых/тестовых запусков,
    НЕ подходит для автоматического ответа агента пользователю в реальном
    времени (там нужен TwoCaptchaSolver или аналог).
    """

    def __init__(self, save_dir: Path = Path("data/captcha")):
        self.save_dir = save_dir
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def solve(self, image_bytes: bytes) -> str:
        path = self.save_dir / "captcha.png"
        path.write_bytes(image_bytes)
        print(f"Капча сохранена в {path}. Откройте файл и введите код:")
        return input("Код капчи: ").strip()
