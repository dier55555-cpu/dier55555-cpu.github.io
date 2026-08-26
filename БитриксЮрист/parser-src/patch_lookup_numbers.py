from pathlib import Path
import re

p = Path("/opt/bitrix-delo/scraper/directory/lookup.py")
text = p.read_text(encoding="utf-8")

old_tok = """        if raw in STOPWORDS or len(raw) < 2:
            continue
"""
new_tok = """        if raw in STOPWORDS:
            continue
        # номер участка «8» должен сохраняться
        if len(raw) < 2 and not raw.isdigit():
            continue
"""
if old_tok not in text:
    raise SystemExit("tokenize rule missing")
text = text.replace(old_tok, new_tok, 1)

old_score = """    if record.parser_supported:
        score += 1
    return score
"""
new_score = """    if record.parser_supported:
        score += 1
    nums = [t for t in tokens if t.isdigit()]
    if nums:
        name = _norm_key(record.name)
        for n in nums:
            if re.search(rf"(?:№|номер|участок)\\s*{n}\\b", name) or re.search(rf"\\b{n}\\b", name):
                score += 8
    return score
"""
if "import re" not in text.split("def score_record")[0]:
    text = text.replace("import json\nimport re\n", "import json\nimport re\n", 1)
if old_score not in text:
    raise SystemExit("score end missing")
text = text.replace(old_score, new_score, 1)
p.write_text(text, encoding="utf-8")
print("lookup.py patched")
