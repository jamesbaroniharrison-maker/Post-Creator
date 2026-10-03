"""Reads the Claude Design post templates (designs/*.html) and fills them in.

Each file is one design: slides marked `<div class="slide light|dark" data-design=..>`,
text spots marked `{{field}}`, repeating elements marked `data-repeat="name"`, a list
of fields with their max word counts, and sample text at max and min item counts.
Nothing is hand-copied: drop an updated file from Claude Design into designs/ and it's
picked up as it is. Filling follows the files' own preview script exactly: repeats
are expanded first (with item numbers), then each slide gets the scalar fields plus
its slide number, slide total and progress.
"""

import functools
import html
import json
import pathlib
import re

DESIGNS_DIR = pathlib.Path(__file__).resolve().parent / "designs"

# Fields the filler works out itself, never the model.
AUTO_FIELDS = {"item_no", "lesson_no", "slide_no", "slide_total", "progress_pct", "lesson_count"}
# Fields with one right answer for every post.
FIXED_FIELDS = {
    "footer_note": "JAMES BARONI HARRISON",
    "name": "James Baroni Harrison",  # quotes are always your own words
    "role": "Baroni Applied Intelligence",
}
HIGHLIGHT_FIELD = "item_highlight"  # "yes" or blank - which repeat item is the human step
PHOTO_FIELD = "photo_url"

_FIELD_CHIP = re.compile(r'<code>\{\{(\w+)\}\}</code><span>([^<]*)</span>')
_REPEAT_BLOCK = re.compile(r'<div class="rp"><div class="rh">repeat: <code>(\w+)</code>(.*?)</div><div class="fg">(.*?)</div></div>', re.S)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class Design:
    def __init__(self, path: pathlib.Path):
        s = path.read_text(encoding="utf-8")
        self.key = path.stem
        self.dark = self.key.endswith("_dark")
        title = re.search(r"<h1>(.*?)<span", s, re.S)
        self.name = (title.group(1).strip() if title else self.key) + (" (dark)" if self.dark else "")
        style = s[s.index("<style>") + 7 : s.index("</style>")]
        self.css = style.split("/* ---- preview page only")[0]
        self.body = s[s.index('<main id="designs">') + len('<main id="designs">') : s.index("</main>")].strip()
        size = re.search(r'class="slide[^"]*"[^>]*?width:(\d+)px;height:(\d+)px', self.body)
        self.height = int(size.group(2)) if size else 1350

        fields_html = s[s.index('<div class="fields">') : s.index('<script type="application/json"')]
        self.repeats: dict[str, dict[str, int]] = {}  # repeat -> {item field: max words}
        for name, _, chips in _REPEAT_BLOCK.findall(fields_html):
            self.repeats[name] = {k: _max_words(v) for k, v in _FIELD_CHIP.findall(chips)}
        top = _REPEAT_BLOCK.sub("", fields_html)
        self.fields = {k: _max_words(v) for k, v in _FIELD_CHIP.findall(top)}  # scalar field -> max words

        sample = json.loads(re.search(r'id="sample-data">(.*?)</script>', s, re.S).group(1))
        self.sample = sample.get(self.key) or next(iter(sample.values()))
        self.list_lengths = {
            r: (int(self.sample.get("min", {}).get(r, 1)), len(self.sample.get("r", {}).get(r, [])) or 1)
            for r in self.repeats
        }

    @property
    def needs_photo(self) -> bool:
        return PHOTO_FIELD in self.fields

    @property
    def model_fields(self) -> dict[str, int]:
        """Scalar fields the model fills (not auto, fixed or the photo)."""
        return {k: v for k, v in self.fields.items() if k not in AUTO_FIELDS | set(FIXED_FIELDS) | {PHOTO_FIELD}}

    def model_item_fields(self, repeat: str) -> dict[str, int]:
        return {k: v for k, v in self.repeats[repeat].items() if k not in AUTO_FIELDS}

    def slide_count(self, slots: dict | None = None) -> int:
        n = self.body.count('class="slide ')
        for r in self.repeats:
            if _slide_repeat(self.body, r):
                n += len((slots or {}).get(r) or self.sample["r"][r]) - 1
        return n

    def shape(self) -> str:
        """The JSON shape shown to the model: every field it fills, with its limit."""
        out = {k: f"<= {v} words" for k, v in self.model_fields.items()}
        for r in self.repeats:
            lo, hi = self.list_lengths[r]
            item = {}
            for k, v in self.model_item_fields(r).items():
                item[k] = '"yes" on the ONE item that is the human/your step, "" on the rest' if k == HIGHLIGHT_FIELD else f"<= {v} words"
            out[r] = [item, f"{lo}-{hi} items" if lo != hi else f"exactly {lo} items"]
        return json.dumps(out, ensure_ascii=False)

    def fill(self, slots: dict, photo_url: str = "") -> str:
        """The filled slides as HTML. Values are HTML-escaped."""
        out = self.body
        for r in self.repeats:
            out = _expand_repeat(out, r, slots.get(r) or [])
        # Fixed fields always win, whatever was passed in (quotes are always your own words).
        values = {**{k: v for k, v in slots.items() if isinstance(v, str)}, **FIXED_FIELDS}
        if self.needs_photo:
            values[PHOTO_FIELD] = photo_url
        lessons = slots.get("lessons")
        if "lesson_count" in self.fields and isinstance(lessons, list):
            values["lesson_count"] = str(len(lessons))
        slides = _top_level_slides(out)
        total = len(slides)
        pieces, last = [], 0
        for i, (start, end) in enumerate(slides, start=1):
            pct = round(i / total * 100)
            if "count_done" in values and "count_total" in values:  # milestone progress bar
                try:
                    pct = round(float(values["count_done"]) / float(values["count_total"]) * 100)
                except (ValueError, ZeroDivisionError):
                    pass
            local = {**values, "slide_no": f"{i:02d}", "slide_total": f"{total:02d}", "progress_pct": str(max(0, min(100, pct)))}
            pieces.append(out[last:start])
            pieces.append(_sub(out[start:end], local, url_fields={PHOTO_FIELD}))
            last = end
        pieces.append(out[last:])
        return "".join(pieces)

    def sample_slots(self, mode: str = "max") -> dict:
        slots = dict(self.sample.get("f", {}))
        for r, items in self.sample.get("r", {}).items():
            n = self.sample.get("min", {}).get(r, len(items)) if mode == "min" else len(items)
            slots[r] = [dict(x) for x in items[:n]]
        return slots


def _max_words(text: str) -> int:
    m = re.search(r"max (\d+) word", text)
    return int(m.group(1)) if m else 0


def _sub(fragment: str, values: dict, url_fields: set[str] = frozenset()) -> str:
    def repl(m):
        k = m.group(1)
        if k not in values:
            return m.group(0)
        v = str(values[k])
        return html.escape(v, quote=True) if k not in url_fields else v.replace('"', "%22")
    return _PLACEHOLDER.sub(repl, fragment)


def _element_span(text: str, start: int) -> int:
    """End index of the element whose opening tag starts at `start` (matching nested tags)."""
    tag = re.match(r"<(\w+)", text[start:]).group(1)
    depth, i = 0, start
    pat = re.compile(rf"<(/?){tag}\b[^>]*?(/?)>")
    for m in pat.finditer(text, start):
        if m.group(2):  # self-closing
            continue
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return m.end()
    return len(text)


def _expand_repeat(text: str, name: str, items: list) -> str:
    m = re.search(rf'<\w+[^>]*data-repeat="{name}"', text)
    if not m:
        return text
    start = m.start()
    end = _element_span(text, start)
    element = text[start:end]
    copies = []
    for i, item in enumerate(items, start=1):
        vals = {k: v for k, v in (item or {}).items() if isinstance(v, str)}
        vals.update(item_no=f"{i:02d}", lesson_no=f"{i:02d}")
        vals.setdefault(HIGHLIGHT_FIELD, "")
        copies.append(_sub(element, vals))
    return text[:start] + "".join(copies) + text[end:]


def _slide_repeat(body: str, name: str) -> bool:
    return bool(re.search(rf'<div class="slide [^"]*"[^>]*data-repeat="{name}"', body))


def _top_level_slides(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for m in re.finditer(r'<div class="slide ', text):
        if m.start() < pos:
            continue
        end = _element_span(text, m.start())
        spans.append((m.start(), end))
        pos = end
    return spans


@functools.cache
def load_designs() -> dict[str, Design]:
    return {p.stem: Design(p) for p in sorted(DESIGNS_DIR.glob("*.html"))}
