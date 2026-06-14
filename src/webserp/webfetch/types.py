"""Typed output structures for webfetch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Metadata:
    title: str = ""
    description: str = ""
    author: str = ""
    published_date: str = ""
    language: str = ""
    site_name: str = ""
    image: str = ""
    favicon: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "description": self.description,
            "author": self.author,
            "published_date": self.published_date,
            "language": self.language,
            "site_name": self.site_name,
            "image": self.image,
            "favicon": self.favicon,
        }


@dataclass
class Link:
    text: str
    href: str
    type: str = "content"
    is_external: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "href": self.href,
            "type": self.type,
            "is_external": self.is_external,
        }


@dataclass
class Image:
    alt: str
    src: str

    def as_dict(self) -> dict[str, str]:
        return {"alt": self.alt, "src": self.src}


@dataclass
class CodeBlock:
    language: str
    code: str

    def as_dict(self) -> dict[str, str]:
        return {"language": self.language, "code": self.code}


@dataclass
class MarkdownAssets:
    links: list[Link] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    code_blocks: list[CodeBlock] = field(default_factory=list)


@dataclass
class CandidateScore:
    text_chars: int = 0
    cjk_chars: int = 0
    structure_score: float = 0.0
    link_density: float = 0.0
    link_penalty: float = 0.0
    noise_penalty: float = 0.0
    title_bonus: float = 0.0
    final_score: float = 0.0
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "text_chars": self.text_chars,
            "cjk_chars": self.cjk_chars,
            "structure_score": round(self.structure_score, 3),
            "link_density": round(self.link_density, 3),
            "link_penalty": round(self.link_penalty, 3),
            "noise_penalty": round(self.noise_penalty, 3),
            "title_bonus": round(self.title_bonus, 3),
            "final_score": round(self.final_score, 3),
            "reason": self.reason,
        }


@dataclass
class ExtractionCandidate:
    name: str
    markdown: str
    text: str
    assets: MarkdownAssets
    score: CandidateScore


@dataclass
class WebFetchResult:
    url: str
    final_url: str
    status: int
    title: str
    description: str
    markdown: str
    text: str
    links: list[Link]
    images: list[Image]
    code_blocks: list[CodeBlock]
    structured_data: list[Any]
    metadata: Metadata
    meta: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "title": self.title,
            "description": self.description,
            "markdown": self.markdown,
            "text": self.text,
            "links": [link.as_dict() for link in self.links],
            "images": [image.as_dict() for image in self.images],
            "code_blocks": [block.as_dict() for block in self.code_blocks],
            "structured_data": self.structured_data,
            "metadata": self.metadata.as_dict(),
            "meta": self.meta,
        }
