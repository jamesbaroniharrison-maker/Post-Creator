"""The template catalog: each brand template's fields, word limits, and when it fits.

The shapes mirror the Baroni post templates (D:\\Work\\! Branding\\Post Templates.dc.html).
Limits follow the brand guide: 25 words max on a single post, 40 per carousel slide.
`numeric_fields` name the fields whose numbers must appear in the post or its source -
a visual never shows a figure the post didn't actually contain.
"""

import pydantic


def _words(text: str | None) -> int:
    return len((text or "").split())


class Limit(pydantic.BaseModel):
    max_words: int = 0  # 0 = not word-limited
    max_chars: int = 0  # 0 = not char-limited
    required: bool = True


class _Slots(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="ignore")


class Statement(_Slots):
    label: str
    headline: str
    headline_gold: str


class Quote(_Slots):
    label: str
    quote: str
    quote_gold: str


class BigNumber(_Slots):
    label: str
    before_value: str = ""
    after_value: str
    caption: str
    stats: list[str] = []


class BeforeAfter(_Slots):
    label: str
    headline: str
    headline_gold: str
    before: list[str]
    after: list[str]


class ListPost(_Slots):
    label: str
    headline: str
    headline_gold: str
    items: list[str]


class PhotoIntro(_Slots):
    label: str
    headline: str
    headline_gold: str
    line: str


class MythFact(_Slots):
    label: str
    myth: str
    fact: str
    fact_gold: str
    fact_line: str


class Announcement(_Slots):
    label: str
    headline: str
    headline_gold: str
    button: str


class Step(pydantic.BaseModel):
    name: str
    line: str


class DashRow(pydantic.BaseModel):
    label: str
    value: str


class HowItWorks(_Slots):
    label: str
    headline: str
    headline_gold: str
    subline: str
    steps: list[Step]
    you_bring: str = ""
    strip: list[str] = []
    strip_you: int = 0
    dashboard_title: str = ""
    dashboard: list[DashRow] = []
    cta_headline: str
    cta_gold: str
    cta_button: str
    cta_small: str = "Link in comments · save for later"


class BuildStep(pydantic.BaseModel):
    name: str
    desc: str


class Stat(pydantic.BaseModel):
    value: str
    label: str


class CaseStudy(_Slots):
    label: str
    headline: str
    headline_gold: str
    subline: str
    problem_headline: str
    problem_gold: str
    problems: list[str]
    build_headline: str
    build_gold: str
    build_steps: list[BuildStep]
    you_step: int = 0
    before_value: str = ""
    after_value: str
    result_caption: str
    result_stats: list[Stat] = []
    lesson: str
    lesson_gold: str
    lesson_line: str
    cta_headline: str
    cta_gold: str
    cta_button: str
    cta_small: str = "Link in comments · save for later"


class TemplateSpec(pydantic.BaseModel):
    key: str
    name: str
    model: type
    slides: int = 1
    height: int = 1350
    when: str  # what kind of post it suits - shown to the model choosing a template
    shape: str  # the JSON shape and word limits - shown to the model filling it
    numeric_fields: list[str] = []
    needs_photo: bool = False
    list_lengths: dict[str, tuple[int, int]] = {}
    word_limits: dict[str, int] = {}


CATALOG: dict[str, TemplateSpec] = {
    "statement": TemplateSpec(
        key="statement",
        name="Statement",
        model=Statement,
        when="One strong opinion or one-line takeaway.",
        shape='{"label": "2-4 words, e.g. POINT OF VIEW", "headline": "<=8 words", "headline_gold": "<=5 words, the payoff"}',
        word_limits={"label": 4, "headline": 8, "headline_gold": 5},
    ),
    "quote": TemplateSpec(
        key="quote",
        name="Quote",
        model=Quote,
        when="A memorable line the post itself says (James's own words - never a made-up quote from anyone else).",
        shape='{"label": "2-4 words, e.g. IN MY WORDS", "quote": "<=16 words, taken from the post", "quote_gold": "<=6 words, the end of the quote"}',
        word_limits={"label": 4, "quote": 16, "quote_gold": 6},
    ),
    "big_number": TemplateSpec(
        key="big_number",
        name="Big number",
        model=BigNumber,
        when="A real result or metric stated in the post (e.g. 6 hours to 40 minutes).",
        shape='{"label": "2-5 words", "before_value": "optional, <=6 chars e.g. 6h", "after_value": "<=6 chars e.g. 40m", '
        '"caption": "<=16 words", "stats": ["0-3 items, each <=3 words, e.g. 3 CHANNELS"]}',
        numeric_fields=["before_value", "after_value", "stats"],
        list_lengths={"stats": (0, 3)},
        word_limits={"label": 5, "caption": 16},
    ),
    "before_after": TemplateSpec(
        key="before_after",
        name="Before / after",
        model=BeforeAfter,
        when="A clear change: how something worked before vs after.",
        shape='{"label": "2-4 words", "headline": "<=5 words", "headline_gold": "<=4 words", '
        '"before": ["exactly 4 items, each <=6 words"], "after": ["exactly 4 items, each <=6 words"]}',
        list_lengths={"before": (4, 4), "after": (4, 4)},
        word_limits={"label": 4, "headline": 5, "headline_gold": 4},
    ),
    "list": TemplateSpec(
        key="list",
        name="List",
        model=ListPost,
        when="Several parallel points, tips, rules or steps.",
        shape='{"label": "2-5 words, e.g. FIELD NOTES · 5 RULES", "headline": "<=6 words", "headline_gold": "<=4 words", '
        '"items": ["3-5 items, each <=8 words"]}',
        list_lengths={"items": (3, 5)},
        word_limits={"label": 5, "headline": 6, "headline_gold": 4},
    ),
    "photo_intro": TemplateSpec(
        key="photo_intro",
        name="Photo intro",
        model=PhotoIntro,
        when="A post with James's own photo: events, behind the scenes, introductions.",
        shape='{"label": "2-4 words", "headline": "<=7 words", "headline_gold": "<=5 words", "line": "<=12 words"}',
        needs_photo=True,
        word_limits={"label": 4, "headline": 7, "headline_gold": 5, "line": 12},
    ),
    "myth_fact": TemplateSpec(
        key="myth_fact",
        name="Myth / fact",
        model=MythFact,
        when="Correcting a common misconception; a contrarian take.",
        shape='{"label": "2-4 words, e.g. MYTH / FACT", "myth": "<=10 words", "fact": "<=6 words", "fact_gold": "<=5 words", "fact_line": "<=12 words"}',
        word_limits={"label": 4, "myth": 10, "fact": 6, "fact_gold": 5, "fact_line": 12},
    ),
    "announcement": TemplateSpec(
        key="announcement",
        name="Announcement",
        model=Announcement,
        height=1080,
        when="Something new: a launch, an event, availability, a milestone.",
        shape='{"label": "1-3 words, e.g. NOW BOOKING", "headline": "<=6 words", "headline_gold": "<=4 words", "button": "<=6 words call to action"}',
        word_limits={"label": 3, "headline": 6, "headline_gold": 4, "button": 6},
    ),
    "how_it_works": TemplateSpec(
        key="how_it_works",
        name="Carousel: how it works",
        model=HowItWorks,
        slides=5,
        when="A process or method in 3 steps.",
        shape='{"label": "2-5 words", "headline": "<=7 words", "headline_gold": "<=4 words", "subline": "<=10 words", '
        '"steps": [{"name": "1-3 words", "line": "<=14 words"}, exactly 3], "you_bring": "optional <=8 words", '
        '"strip": ["optional: exactly 4 one/two-word stages"], "strip_you": "optional 1-4: the human stage", '
        '"dashboard_title": "optional", "dashboard": [{"label": "<=3 words", "value": "a REAL number from the post"}, 0-3], '
        '"cta_headline": "<=6 words", "cta_gold": "<=4 words", "cta_button": "<=6 words", "cta_small": "<=6 words"}',
        numeric_fields=["dashboard"],
        list_lengths={"steps": (3, 3), "strip": (0, 4), "dashboard": (0, 3)},
        word_limits={"label": 5, "headline": 7, "headline_gold": 4, "subline": 10, "you_bring": 8,
                     "cta_headline": 6, "cta_gold": 4, "cta_button": 6, "cta_small": 6},
    ),
    "case_study": TemplateSpec(
        key="case_study",
        name="Carousel: case study",
        model=CaseStudy,
        slides=6,
        when="A real project with a problem, what was built, and a measured result stated in the post.",
        shape='{"label": "2-5 words", "headline": "<=6 words", "headline_gold": "<=4 words", "subline": "<=18 words", '
        '"problem_headline": "<=6 words", "problem_gold": "<=4 words", "problems": ["exactly 3, each <=10 words"], '
        '"build_headline": "<=4 words", "build_gold": "<=3 words", "build_steps": [{"name": "<=3 words", "desc": "<=7 words"}, 3-5], '
        '"you_step": "0-5: which build step is the human one, 0 for none", "before_value": "optional <=6 chars", '
        '"after_value": "<=6 chars, a REAL number from the post", "result_caption": "<=10 words", '
        '"result_stats": [{"value": "REAL number", "label": "<=3 words"}, 0-2], "lesson": "<=8 words", "lesson_gold": "<=6 words", '
        '"lesson_line": "<=14 words", "cta_headline": "<=6 words", "cta_gold": "<=4 words", "cta_button": "<=6 words", "cta_small": "<=6 words"}',
        numeric_fields=["before_value", "after_value", "result_stats"],
        list_lengths={"problems": (3, 3), "build_steps": (3, 5), "result_stats": (0, 2)},
        word_limits={"label": 5, "headline": 6, "headline_gold": 4, "subline": 18, "problem_headline": 6,
                     "problem_gold": 4, "build_headline": 4, "build_gold": 3, "result_caption": 10, "lesson": 8,
                     "lesson_gold": 6, "lesson_line": 14, "cta_headline": 6, "cta_gold": 4, "cta_button": 6, "cta_small": 6},
    ),
}

# Which templates suit each media pairing the rotation picked for a post.
PAIRING_TEMPLATES: dict[str, list[str]] = {
    "carousel": ["how_it_works", "case_study"],
    "infographic": ["list", "before_after", "myth_fact", "big_number"],
    "chart": ["big_number", "before_after"],
    "candid_photo": ["photo_intro", "statement", "quote"],
    "screenshot": ["statement", "quote"],
    "text_only": ["statement", "quote", "list"],  # only used when you ask for a visual by hand
}


def candidate_templates(media_pairing: str | None, has_photo: bool) -> list[str]:
    keys = PAIRING_TEMPLATES.get(media_pairing or "", list(CATALOG))
    return [k for k in keys if has_photo or not CATALOG[k].needs_photo] or ["statement"]
