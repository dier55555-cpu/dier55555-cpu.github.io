from __future__ import annotations

import json
import unittest
from pathlib import Path

from parser.sudrf import extract_text, is_blocked, load_courts, to_markdown

ROOT = Path(__file__).resolve().parents[1]

BLOCKED_HTML = """
<HTML><HEAD><TITLE>ГАС Правосудие</TITLE></HEAD>
<BODY>
<h3> Этот запрос заблокирован по соображениям безопасности (G)</h3>
Ваш ip: 3.14.55.178
</BODY></HTML>
"""

COURT_HTML = """
<html><head><title>Советский районный суд г. Воронежа</title></head>
<body>
<h1>Контакты</h1>
<p>394051, г. Воронеж, ул. Домостроителей, д. 26</p>
<p>Тел.: (473) 278-82-52</p>
<a href="/modules.php?name=sud_delo">Судебное делопроизводство</a>
<script>document.write('ignore me')</script>
</body></html>
"""


class SudrfParserTests(unittest.TestCase):
    def test_blocked_page_detected(self) -> None:
        self.assertTrue(is_blocked(BLOCKED_HTML))
        self.assertFalse(is_blocked(COURT_HTML))

    def test_extract_text_drops_scripts(self) -> None:
        text, links = extract_text(COURT_HTML)
        self.assertIn("Домостроителей", text)
        self.assertNotIn("ignore me", text)
        self.assertTrue(any("sud_delo" in href for href in links))

    def test_config_has_six_voronezh_courts(self) -> None:
        courts = load_courts(ROOT / "courts" / "config.json")
        self.assertEqual(len(courts), 6)
        ids = {c["id"] for c in courts}
        self.assertEqual(
            ids,
            {
                "sovetsky",
                "kominternovsky",
                "zheleznodorozhny",
                "levoberezhny",
                "centralny",
                "leninsky",
            },
        )
        for court in courts:
            self.assertTrue(court["official_url"].startswith("https://"))
            self.assertIn("sudrf.ru", court["official_url"])
            self.assertTrue(court["pages"]["cases"].endswith("name=sud_delo"))

    def test_to_markdown_marks_blocked_pages(self) -> None:
        scrape = {
            "court": json.loads((ROOT / "courts" / "config.json").read_text(encoding="utf-8"))[
                "courts"
            ][0],
            "pages": {
                "https://sovetsky--vrn.sudrf.ru/": {
                    "ok": False,
                    "blocked": True,
                    "error": "blocked_by_sudrf",
                    "text": "",
                }
            },
        }
        md = to_markdown(scrape)
        self.assertIn("Советский районный суд", md)
        self.assertIn("заблокирована", md)


if __name__ == "__main__":
    unittest.main()
