"""Structured output contract for a single drafted post."""

import pydantic


class SourceRef(pydantic.BaseModel):
    title: str
    url: str


class DraftOutput(pydantic.BaseModel):
    """What the drafting call must produce for one post, before it's saved to `posts`."""

    convey_statement: str
    text: str
    media_note: str = ""
    hashtags: list[str] = pydantic.Field(default_factory=list)
    tags: list[str] = pydantic.Field(default_factory=list)
    suggested_day: str
    sources: list[SourceRef] = pydantic.Field(default_factory=list)
    compliance_note: str
