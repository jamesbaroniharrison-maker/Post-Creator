"""Structured output contract for a single drafted post (spec Â§7 level 4 done-when check)."""

import pydantic


class SourceRef(pydantic.BaseModel):
    title: str
    url: str


class DraftOutput(pydantic.BaseModel):
    """What the drafting call must produce for one post, before it's saved to `posts`."""

    text: str
    hashtags: list[str] = pydantic.Field(default_factory=list)
    tags: list[str] = pydantic.Field(default_factory=list)
    suggested_day: str
    sources: list[SourceRef] = pydantic.Field(default_factory=list)
    compliance_note: str
