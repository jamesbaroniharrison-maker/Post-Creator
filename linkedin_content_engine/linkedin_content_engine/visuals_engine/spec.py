"""The template catalog: every Baroni post design, what kind of post it suits, and which
of the rotation's media pairings it can serve.

The designs themselves (layout, fields, word limits, item counts) come straight from
the Claude Design files in designs/ - see designs.py. This file only adds the one thing
those files can't know: when each design is the right choice. Alternate (`_alt`) and
dark (`_dark`) versions inherit their base design's description and pairings.
"""

from dataclasses import dataclass, field

from linkedin_content_engine.visuals_engine.designs import Design, load_designs

# Base designs only. `when` is shown to the model choosing a design.
WHEN: dict[str, str] = {
    "statement": "One strong opinion or one-line takeaway.",
    "quote": "A memorable line the post itself says (your own words, never a made-up quote).",
    "big_number": "A real before/after result stated in the post (e.g. 6 hours to 40 minutes).",
    "before_after": "A clear change: how something worked before vs after.",
    "list": "Several parallel points, tips, rules or steps.",
    "photo_intro": "A post with your own photo: events, behind the scenes, introductions.",
    "myth_fact": "Correcting a common misconception; a contrarian take.",
    "announcement": "Something new: a launch, availability, a milestone announcement.",
    "how_it_works": "A process or method in a few steps, with the human step called out.",
    "case_study": "A real project: the problem, what was built, a measured result stated in the post.",
    "hot_take": "One bold opinion plus a one-line reason, inviting people to disagree.",
    "this_vs_that": "Two options compared side by side, with a verdict.",
    "tool_spotlight": "An AI tool or model you tried: what it is, what it's good at, your verdict.",
    "milestone": "Degree or project progress with real counts from the post (e.g. module 3 of 8).",
    "open_question": "An open question you're thinking about, with your current answer.",
    "timeline": "3-5 dated points showing how something developed (dates from the post or source).",
    "stat_context": "One real figure from a news story or source, where it's from, and what it means.",
    "news_breakdown": "Commentary on an AI news story: what happened, why it matters, your take.",
    "lessons_learned": "What you learned from something, one lesson per slide.",
    "build_log": "A project you're building: the problem, what you built, what broke, what's next.",
}

# Which designs suit each media pairing the rotation picked (base keys; their
# alternate and dark versions come along automatically).
PAIRING_TEMPLATES: dict[str, list[str]] = {
    "carousel": ["how_it_works", "case_study", "news_breakdown", "lessons_learned", "build_log"],
    "infographic": ["list", "before_after", "myth_fact", "this_vs_that", "tool_spotlight", "timeline", "big_number"],
    "chart": ["big_number", "stat_context", "before_after", "milestone", "timeline", "announcement"],
    "candid_photo": ["photo_intro", "statement", "quote", "milestone"],
    "screenshot": ["statement", "quote", "hot_take", "open_question", "tool_spotlight", "announcement"],
    "text_only": ["statement", "quote", "hot_take", "open_question", "list", "announcement"],  # only when you ask for a visual by hand
}


@dataclass
class TemplateSpec:
    key: str
    name: str
    design: Design
    when: str
    variant_of: str = ""
    height: int = 1350
    needs_photo: bool = False
    slides: int = 1
    word_limits: dict[str, int] = field(default_factory=dict)
    list_lengths: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def shape(self) -> str:
        return self.design.shape()


def _base_of(key: str) -> str:
    """statement_alt_dark -> statement_alt -> statement."""
    if key.endswith("_dark"):
        return key[: -len("_dark")]
    if key.endswith("_alt"):
        return key[: -len("_alt")]
    return ""


# Item caps tighter than the design file's own max, where rendering showed the max
# pushing the footer into the bottom margin (checked at max sample text).
_MAX_ITEMS: dict[str, dict[str, int]] = {"before_after_alt": {"pairs": 4}}


def _build_catalog() -> dict[str, TemplateSpec]:
    catalog = {}
    for key, d in load_designs().items():
        for repeat, cap in _MAX_ITEMS.get(key.removesuffix("_dark"), {}).items():
            lo, hi = d.list_lengths[repeat]
            d.list_lengths[repeat] = (lo, min(hi, cap))
        root = key
        while _base_of(root):
            root = _base_of(root)
        catalog[key] = TemplateSpec(
            key=key,
            name=d.name,
            design=d,
            when=WHEN.get(root, d.name),
            variant_of=_base_of(key),
            height=d.height,
            needs_photo=d.needs_photo,
            slides=d.slide_count(),
            word_limits=d.model_fields,
            list_lengths=d.list_lengths,
        )
    return catalog


CATALOG: dict[str, TemplateSpec] = _build_catalog()


def _root(key: str) -> str:
    """The original design a variant descends from (statement_alt_dark -> statement)."""
    seen = set()
    while CATALOG.get(key) and CATALOG[key].variant_of and key not in seen:
        seen.add(key)
        key = CATALOG[key].variant_of
    return key


def is_dark(key: str) -> bool:
    return key.endswith("_dark")


def candidate_templates(
    media_pairing: str | None,
    has_photo: bool,
    recent: set[str] | None = None,
    dark: bool | None = None,
) -> list[str]:
    """Designs that suit the pairing (plus their alternate/dark versions), minus any
    used on the last few posts - so the same look doesn't come round twice running.
    `dark` picks the light or dark set (None = either). Each filter only applies if
    something is left after it."""
    base = PAIRING_TEMPLATES.get(media_pairing or "", [k for k in CATALOG if not _base_of(k)])
    keys = [k for k in base if k in CATALOG] + [k for k in CATALOG if k not in base and _root(k) in base]
    keys = [k for k in keys if has_photo or not CATALOG[k].needs_photo] or ["statement"]
    if dark is not None:
        keys = [k for k in keys if is_dark(k) == dark] or keys
    fresh = [k for k in keys if k not in (recent or set())]
    return fresh or keys
