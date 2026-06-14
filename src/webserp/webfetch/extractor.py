"""webfetch extraction pipeline."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Iterable

from lxml import etree, html

from .markdown import convert_elements, markdown_to_text
from .metadata import extract_metadata
from .structured_data import extract_data_island_markdown, extract_structured_data
from .topology import LinkTopologyAnalyzer
from .types import CandidateScore, ExtractionCandidate, MarkdownAssets, WebFetchResult

CONTENT_CLASS_RE = re.compile(r"article|content|post|entry|body|main|story", re.I)
NOISE_CLASS_RE = re.compile(
    r"sidebar|menu|nav|footer|header|cookie|popup|modal|share|social|related|recommend|advert|sponsor|promo|breadcrumb",
    re.I,
)
TABLE_NOISE_CLASS_RE = re.compile(
    r"sidebar|menu|nav|footer|cookie|popup|modal|share|social|related|recommend|advert|sponsor|promo|breadcrumb",
    re.I,
)
NOISE_PHRASES = (
    "cookie settings",
    "accept cookies",
    "privacy policy",
    "related articles",
    "share this article",
    "advertisement",
    "top tutorials",
    "sign up",
    "log in",
    "相关阅读",
    "分享到",
    "广告",
)
BLOCK_XPATH = (
    "//article | //main | //*[@role='main'] | //h1 | //h2 | //h3 | //h4 | //h5 | //h6 | "
    "//p | //pre | //table | //ul | //ol | //blockquote | //img"
)
CANDIDATE_XPATH = "//article | //main | //*[@role='main'] | //section | //div | //td | //body"


def extract(html_text: str, url: str, *, final_url: str | None = None, status: int = 200) -> WebFetchResult:
    source_url = final_url or url
    raw_root = _parse_html(html_text)
    metadata = extract_metadata(raw_root, source_url)
    structured_data = extract_structured_data(html_text, raw_root)

    root = deepcopy(raw_root)
    _strip_non_content_nodes(root)

    topology = LinkTopologyAnalyzer(source_url)
    poison_ids = _poison_ids(root, topology)

    candidates = _build_candidates(root, source_url, metadata.title, poison_ids, topology)
    best_dom = _best_candidate(candidates)
    data_md = ""
    if _should_use_data_island(best_dom):
        data_md = extract_data_island_markdown(raw_root, best_dom.score.text_chars if best_dom else 0)

    if data_md:
        candidates.append(_markdown_candidate("data_island", data_md, metadata.title))
        if best_dom and _should_enrich_with_data_island(best_dom):
            enriched_md = best_dom.markdown + "\n\n" + data_md
            candidates.append(_markdown_candidate("data_enriched", enriched_md, metadata.title, best_dom.assets))

    winner = _best_candidate(candidates) or _empty_candidate()
    links = topology.analyze(root, winner.assets.links)
    warnings = []
    if winner.score.text_chars < 120:
        warnings.append("low_text_content")
    if winner.name == "body_fallback":
        warnings.append("fallback_strategy_used")

    return WebFetchResult(
        url=url,
        final_url=source_url,
        status=status,
        title=metadata.title,
        description=metadata.description,
        markdown=winner.markdown,
        text=winner.text,
        links=links,
        images=_dedupe_images(winner.assets.images),
        code_blocks=winner.assets.code_blocks,
        structured_data=structured_data,
        metadata=metadata,
        meta={
            "strategy": winner.name,
            "candidates": {candidate.name: candidate.score.as_dict() for candidate in candidates},
            "warnings": warnings,
        },
    )


def _parse_html(html_text: str) -> html.HtmlElement:
    if not html_text.strip():
        return html.fromstring("<html><body></body></html>")
    parser = html.HTMLParser(encoding="utf-8", recover=True)
    root = html.fromstring(html_text, parser=parser)
    if _tag(root) not in {"html", "body"}:
        wrapper = html.Element("html")
        body = html.Element("body")
        body.append(root)
        wrapper.append(body)
        return wrapper
    return root


def _strip_non_content_nodes(root: html.HtmlElement) -> None:
    for tag in ("script", "style", "noscript", "iframe", "svg", "canvas", "button", "input", "textarea"):
        etree.strip_elements(root, tag, with_tail=False)


def _build_candidates(
    root: html.HtmlElement,
    base_url: str,
    title: str,
    poison_ids: set[str],
    topology: LinkTopologyAnalyzer,
) -> list[ExtractionCandidate]:
    candidates: list[ExtractionCandidate] = []

    semantic = _first(root.xpath("//article | //main | //*[@role='main']"))
    if semantic is not None:
        candidates.append(_element_candidate("semantic", [semantic], base_url, title, poison_ids))

    scored = _best_scored_node(root, topology)
    if scored is not None:
        candidates.append(_element_candidate("scored", [scored], base_url, title, poison_ids))

    structural = _structural_elements(root, poison_ids)
    if structural:
        candidates.append(_element_candidate("structural", structural, base_url, title, poison_ids))

    body = _first(root.xpath("//body"))
    if body is None:
        body = root
    candidates.append(_element_candidate("body_fallback", [body], base_url, title, poison_ids))

    return _dedupe_candidates(candidates)


def _element_candidate(
    name: str,
    elements: list[html.HtmlElement],
    base_url: str,
    title: str,
    poison_ids: set[str],
) -> ExtractionCandidate:
    markdown, text, assets = convert_elements(elements, base_url, exclude_keys=poison_ids)
    score = _score_candidate(name, markdown, text, assets, title)
    return ExtractionCandidate(name=name, markdown=markdown, text=text, assets=assets, score=score)


def _markdown_candidate(
    name: str,
    markdown: str,
    title: str,
    assets: MarkdownAssets | None = None,
) -> ExtractionCandidate:
    text = markdown_to_text(markdown)
    assets = assets or MarkdownAssets()
    score = _score_candidate(name, markdown, text, assets, title)
    return ExtractionCandidate(name=name, markdown=markdown.strip(), text=text, assets=assets, score=score)


def _score_candidate(
    name: str,
    markdown: str,
    text: str,
    assets: MarkdownAssets,
    title: str,
) -> CandidateScore:
    text_chars = len(_compact_text(text))
    cjk_chars = _cjk_count(text)
    heading_count = len(re.findall(r"(?m)^#{1,6}\s+", markdown))
    table_rows = len(re.findall(r"(?m)^\|.*\|$", markdown))
    list_items = len(re.findall(r"(?m)^\s*(?:-|\d+\.)\s+", markdown))
    code_blocks = len(assets.code_blocks)
    image_count = len(assets.images)
    link_text_chars = sum(len(_compact_text(link.text)) for link in assets.links)
    link_density = link_text_chars / max(1, text_chars)

    structure_score = min(
        60.0,
        heading_count * 1.5
        + min(30, table_rows * 2.0)
        + code_blocks * 12.0
        + min(20, list_items * 0.5)
        + image_count * 0.5,
    )
    text_score = min(75.0, math.log1p(text_chars) * 8.0)
    if cjk_chars > 0:
        text_score += min(10.0, math.log1p(cjk_chars) * 1.5)

    link_penalty = max(0.0, (link_density - 0.28) * 90.0)
    noise_penalty = _noise_penalty(markdown)
    title_bonus = 0.0
    if title and _compact_text(title) and _compact_text(title) in _compact_text(markdown):
        title_bonus = 8.0
    if name == "body_fallback":
        noise_penalty += 18.0
    if name == "data_island":
        structure_score *= 0.5
        noise_penalty += 4.0
    if name == "data_enriched":
        structure_score += 3.0

    final = text_score + structure_score + title_bonus - link_penalty - noise_penalty
    reason = _reason(name, text_chars, structure_score, link_density, noise_penalty)
    return CandidateScore(
        text_chars=text_chars,
        cjk_chars=cjk_chars,
        structure_score=structure_score,
        link_density=link_density,
        link_penalty=link_penalty,
        noise_penalty=noise_penalty,
        title_bonus=title_bonus,
        final_score=final,
        reason=reason,
    )


def _best_candidate(candidates: list[ExtractionCandidate]) -> ExtractionCandidate | None:
    viable = [candidate for candidate in candidates if candidate.score.text_chars >= 40 or candidate.assets.code_blocks]
    if not viable:
        return None
    return max(viable, key=lambda candidate: candidate.score.final_score)


def _best_scored_node(root: html.HtmlElement, topology: LinkTopologyAnalyzer) -> html.HtmlElement | None:
    best: tuple[html.HtmlElement, float] | None = None
    for node in root.xpath(CANDIDATE_XPATH):
        text = _compact_text(node.text_content())
        if len(text) < 80:
            continue
        score = math.log1p(len(text)) * 5.0
        tag = _tag(node)
        if tag in {"article", "main"} or node.get("role") == "main":
            score += 35.0
        attrs = " ".join(filter(None, [node.get("class"), node.get("id")]))
        if CONTENT_CLASS_RE.search(attrs):
            score += 18.0
        if NOISE_CLASS_RE.search(attrs):
            score -= 22.0
        score += len(node.xpath(".//p")) * 2.0
        score += len(node.xpath(".//pre")) * 8.0
        score += len(node.xpath(".//table")) * 8.0
        link_len = sum(len(_compact_text(a.text_content())) for a in node.xpath(".//a"))
        link_density = link_len / max(1, len(text))
        if link_density > 0.55:
            score *= 0.25
        elif link_density > 0.35:
            score *= 0.55
        score -= min(30.0, topology.link_mass(node) / 4.0)
        if best is None or score > best[1]:
            best = (node, score)
    return best[0] if best else None


def _structural_elements(root: html.HtmlElement, poison_ids: set[str]) -> list[html.HtmlElement]:
    selected: list[html.HtmlElement] = []
    selected_keys: set[str] = set()
    for node in root.xpath(BLOCK_XPATH):
        if _has_selected_ancestor(node, selected_keys):
            continue
        tag = _tag(node)
        high_value = tag in {"article", "main", "pre", "table"}
        if not high_value and _has_poison_ancestor(node, poison_ids):
            continue
        if high_value and _link_density(node) >= 0.65:
            continue
        if tag in {"ul", "ol"} and _link_density(node) >= 0.55 and not node.xpath(".//pre | .//table"):
            continue
        text = _compact_text(node.text_content())
        if tag not in {"img", "pre", "table"} and len(text) < 8:
            continue
        selected.append(node)
        selected_keys.add(_node_key(node))
    return selected


def _should_use_data_island(best_dom: ExtractionCandidate | None) -> bool:
    if best_dom is None:
        return True
    if best_dom.score.text_chars < 80:
        return True
    if best_dom.name == "body_fallback" and best_dom.score.text_chars < 120:
        return True
    return False


def _should_enrich_with_data_island(best_dom: ExtractionCandidate) -> bool:
    return best_dom.name == "body_fallback" and best_dom.score.text_chars < 80


def _poison_ids(root: html.HtmlElement, topology: LinkTopologyAnalyzer) -> set[str]:
    ids = set()
    for node in root.xpath("//nav | //footer | //header | //aside"):
        ids.update(_node_key(child) for child in node.iter())

    for node in root.xpath("//div | //section"):
        if _node_key(node) in ids:
            continue
        if node.xpath(".//article | .//main | .//*[@role='main']"):
            continue
        attrs = " ".join(filter(None, [node.get("class"), node.get("id")]))
        if NOISE_CLASS_RE.search(attrs) or topology.link_mass(node) > 55.0:
            ids.update(_node_key(child) for child in node.iter())

    for node in root.xpath("//table | //tr | //td | //th"):
        if _node_key(node) in ids:
            continue
        if node.xpath(".//article | .//main | .//*[@role='main']"):
            continue
        attrs = " ".join(filter(None, [node.get("class"), node.get("id")]))
        if TABLE_NOISE_CLASS_RE.search(attrs) or topology.link_mass(node) > 55.0:
            ids.update(_node_key(child) for child in node.iter())
    return ids


def _dedupe_candidates(candidates: list[ExtractionCandidate]) -> list[ExtractionCandidate]:
    result = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate.name, candidate.markdown[:200])
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _empty_candidate() -> ExtractionCandidate:
    score = CandidateScore(reason="no viable candidate")
    return ExtractionCandidate("", "", "", MarkdownAssets(), score)


def _reason(name: str, text_chars: int, structure_score: float, link_density: float, noise_penalty: float) -> str:
    parts = [f"{name}: {text_chars} text chars"]
    if structure_score >= 15:
        parts.append("strong structure")
    if link_density > 0.35:
        parts.append("high link density")
    if noise_penalty:
        parts.append("noise penalty applied")
    return ", ".join(parts)


def _noise_penalty(markdown: str) -> float:
    lower = markdown.lower()
    penalty = 0.0
    for phrase in NOISE_PHRASES:
        if phrase.lower() in lower:
            penalty += 5.0
    return penalty


def _dedupe_images(images):
    result = []
    seen = set()
    for image in images:
        if image.src in seen:
            continue
        seen.add(image.src)
        result.append(image)
    return result


def _first(values: Iterable[object]) -> html.HtmlElement | None:
    for value in values:
        if isinstance(value, html.HtmlElement):
            return value
    return None


def _tag(node: etree._Element) -> str:
    return str(node.tag).lower() if isinstance(node.tag, str) else ""


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _cjk_count(text: str) -> int:
    return sum("\u4e00" <= ch <= "\u9fff" for ch in text)


def _node_key(node: etree._Element) -> str:
    return node.getroottree().getpath(node)


def _has_poison_ancestor(node: etree._Element, poison_ids: set[str]) -> bool:
    current = node
    while current is not None:
        if _node_key(current) in poison_ids:
            return True
        current = current.getparent()
    return False


def _has_selected_ancestor(node: etree._Element, selected_ids: set[str]) -> bool:
    current = node.getparent()
    while current is not None:
        if _node_key(current) in selected_ids:
            return True
        current = current.getparent()
    return False


def _link_density(node: etree._Element) -> float:
    text_len = len(_compact_text(node.text_content())) or 1
    link_len = sum(len(_compact_text(a.text_content())) for a in node.xpath(".//a"))
    return link_len / text_len
