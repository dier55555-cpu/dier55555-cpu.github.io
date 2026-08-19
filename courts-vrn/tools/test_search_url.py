import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from search_url import case_search_url, find_court, load_courts

ROOT = Path(__file__).resolve().parents[1]


class CourtsPackTest(unittest.TestCase):
    def test_six_courts(self):
        data = load_courts()
        ids = {c["id"] for c in data["courts"]}
        self.assertEqual(
            ids,
            {
                "sovetsky",
                "kominternovsky",
                "zheleznodorozhny",
                "levoberezhny",
                "centralny",
                "lensud",
            },
        )

    def test_json_has_search_urls(self):
        for court in load_courts()["courts"]:
            self.assertIn("modules.php?name=sud_delo", court["search_url"])
            self.assertTrue(court["email"].endswith("@sudrf.ru"))

    def test_lookup(self):
        self.assertEqual(find_court("Коминтерновский")["id"], "kominternovsky")
        self.assertIn("lensud", case_search_url("ленинский"))

    def test_kb_mentions_all_hosts(self):
        kb = (ROOT / "kb" / "knowledge-base.md").read_text(encoding="utf-8")
        for court in load_courts()["courts"]:
            host = court["host"].replace("https://", "")
            self.assertIn(host, kb)


if __name__ == "__main__":
    unittest.main()
