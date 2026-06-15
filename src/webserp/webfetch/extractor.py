"""webfetch extraction pipeline."""

from __future__ import annotations

import math
import re
from typing import Iterable

from lxml import etree, html

from .markdown import convert_elements, markdown_to_text
from .metadata import extract_metadata
from .structured_data import extract_data_island_markdown, extract_structured_data
from .topology import LinkTopologyAnalyzer
from .types import CandidateScore, ExtractionCandidate, MarkdownAssets, WebFetchResult

CONTENT_CLASS_RE = re.compile(r"article|content|document|docs?|markdown|md-content|post|entry|body|main|story", re.I)
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
SEMANTIC_XPATH = (
    "//article | //main | //*[@role='main'] | //*[@id='content'] | //*[@id='content-inner'] | "
    "//*[@id='artibody'] | //*[@id='article_content'] | //*[@id='UCAP-CONTENT'] | "
    "//*[contains(concat(' ', normalize-space(@class), ' '), ' body ')] | "
    "//*[contains(@class, 'article-content')] | //*[contains(@class, 'content-panel')] | "
    "//*[contains(@class, 'document')] | //*[contains(@class, 'md-content')] | "
    "//*[contains(@class, 'pages_content')]"
)
SEMANTIC_EXACT_XPATH = "//*[@id='content-inner'] | //*[@id='artibody'] | //*[@id='article_content'] | //*[@id='UCAP-CONTENT']"
CANDIDATE_XPATH = f"{SEMANTIC_XPATH} | //section | //div | //td | //body"


def extract(html_text: str, url: str, *, final_url: str | None = None, status: int = 200) -> WebFetchResult:
    source_url = final_url or url
    raw_root = _parse_html(html_text)
    metadata = extract_metadata(raw_root, source_url)
    structured_data = extract_structured_data(html_text, raw_root)

    root = _parse_html(html_text)
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
    markdown = _polish_markdown(winner.markdown, metadata.title)
    text = markdown_to_text(markdown)
    links = topology.analyze(root, winner.assets.links)
    warnings = []
    if winner.score.text_chars < 120:
        warnings.append("low_text_content")
    if winner.name == "body_fallback":
        warnings.append("fallback_strategy_used")
    if not winner.markdown and _compact_text(root.text_content()):
        warnings.append("empty_extraction")

    return WebFetchResult(
        url=url,
        final_url=source_url,
        status=status,
        title=metadata.title,
        description=metadata.description,
        markdown=markdown,
        text=text,
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

    semantic_exact = _first(root.xpath(SEMANTIC_EXACT_XPATH))
    if semantic_exact is not None:
        candidates.append(_element_candidate("semantic_exact", [semantic_exact], base_url, title, poison_ids))

    semantic = _first(root.xpath(SEMANTIC_XPATH))
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
    if name == "semantic_exact":
        structure_score += 40.0
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


def _polish_markdown(markdown: str, title: str) -> str:
    polished = markdown.strip()
    if not polished:
        return polished
    polished = _trim_short_prelude_before_h1(polished, title)
    polished = _trim_duplicate_h1_navigation(polished)
    polished = _ensure_title_heading(polished, title)
    return _strip_leading_notice_lines(polished, title)


def _trim_short_prelude_before_h1(markdown: str, title: str) -> str:
    lines = markdown.splitlines()
    h1_index = _first_h1_index(lines)
    if h1_index is None or h1_index == 0:
        return markdown

    prelude = "\n".join(lines[:h1_index]).strip()
    if not prelude:
        return "\n".join(lines[h1_index:]).strip()

    prelude_text = markdown_to_text(prelude)
    compact_prelude = _compact_text(prelude_text)
    if not compact_prelude:
        if _looks_like_navigation_prelude(prelude, prelude_text):
            return "\n".join(lines[h1_index:]).strip()
        return markdown
    if len(compact_prelude) > 220:
        return markdown

    h1_text = _heading_text(lines[h1_index])
    title_text = _display_title(title)
    if _texts_overlap(compact_prelude, _compact_text(h1_text)):
        return "\n".join(lines[h1_index:]).strip()
    if _texts_overlap(compact_prelude, _compact_text(title_text)):
        return "\n".join(lines[h1_index:]).strip()
    if _looks_like_navigation_prelude(prelude, prelude_text):
        return "\n".join(lines[h1_index:]).strip()
    return markdown


def _trim_duplicate_h1_navigation(markdown: str) -> str:
    lines = markdown.splitlines()
    first_h1 = _first_h1_index(lines)
    if first_h1 is None:
        return markdown

    first_title = _compact_text(_heading_text(lines[first_h1]))
    if not first_title:
        return markdown

    search_limit = min(len(lines), first_h1 + 24)
    for index in range(first_h1 + 1, search_limit):
        if not re.match(r"^#\s+\S", lines[index].strip()):
            continue
        if _compact_text(_heading_text(lines[index])) != first_title:
            continue
        between = "\n".join(lines[first_h1 + 1:index]).strip()
        if _looks_like_navigation_prelude(between, markdown_to_text(between)):
            tail = lines[index + 1:]
            while tail and not tail[0].strip():
                tail = tail[1:]
            return "\n".join([lines[first_h1].strip(), "", *tail]).strip()
    return markdown


def _ensure_title_heading(markdown: str, title: str) -> str:
    title_text = _display_title(title)
    if not title_text:
        return markdown

    lines = markdown.splitlines()
    h1_index = _first_h1_index(lines)
    if h1_index == 0:
        return markdown
    if h1_index is not None:
        first_h1 = _compact_text(_heading_text(lines[h1_index]))
        title_compact = _compact_text(title_text)
        if _texts_overlap(first_h1, title_compact):
            return markdown
        prelude = markdown_to_text("\n".join(lines[:h1_index]))
        if len(_compact_text(prelude)) <= 220 and not _looks_like_question_metadata(prelude):
            return markdown
        return f"# {title_text}\n\n{_demote_h1_headings(markdown)}".strip()

    first_index = _first_nonempty_index(lines)
    if first_index is None:
        return f"# {title_text}"

    first_text = markdown_to_text(lines[first_index]).strip()
    if _same_title_text(_compact_text(first_text), _compact_text(title_text)):
        lines[first_index] = f"# {first_text or title_text}"
        return "\n".join(lines).strip()

    return f"# {title_text}\n\n{_demote_h1_headings(markdown)}".strip()


def _demote_h1_headings(markdown: str) -> str:
    return re.sub(r"(?m)^#(\s+\S)", r"##\1", markdown)


def _looks_like_question_metadata(text: str) -> bool:
    lower = text.lower()
    return "asked" in lower and "viewed" in lower


def _first_h1_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if re.match(r"^#\s+\S", line.strip()):
            return index
    return None


def _first_nonempty_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.strip():
            return index
    return None


def _heading_text(line: str) -> str:
    return re.sub(r"^#{1,6}\s+", "", line.strip()).strip()


def _display_title(title: str) -> str:
    title = " ".join((title or "").split())
    if not title:
        return ""
    pipe_parts = [part.strip() for part in title.split(" | ") if part.strip()]
    if len(pipe_parts) > 1 and len(pipe_parts[0]) >= 4:
        title = pipe_parts[0]

    dash_parts = [part.strip() for part in title.split(" - ") if part.strip()]
    if len(dash_parts) > 1 and len(dash_parts[0]) >= 4 and _looks_like_title_suffix(dash_parts[-1]):
        return " - ".join(dash_parts[:-1])
    return title


def _looks_like_title_suffix(text: str) -> bool:
    lower = text.lower()
    suffix_markers = (
        "api",
        "apis",
        "docs",
        "documentation",
        "developer",
        "reference",
        "web api",
        "web apis",
    )
    return any(marker in lower for marker in suffix_markers)


def _texts_overlap(left: str, right: str) -> bool:
    if len(left) < 6 or len(right) < 6:
        return False
    return left in right or right in left


def _same_title_text(left: str, right: str) -> bool:
    if len(left) < 6 or len(right) < 6:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    return shorter in longer and len(shorter) / len(longer) >= 0.75


def _looks_like_navigation_prelude(markdown: str, text: str) -> bool:
    lower = text.lower()
    if any(
        marker in lower
        for marker in (
            "view all docs",
            "documentation",
            "api reference",
            "skip to content",
            "repository files navigation",
            "open more actions menu",
            "read in english",
            "access to this page requires authorization",
            "changing directories",
        )
    ):
        return True

    nonempty = [line.strip() for line in markdown.splitlines() if line.strip()]
    if not nonempty:
        return False
    image_or_link_lines = sum(1 for line in nonempty if line.startswith("![") or re.fullmatch(r"\[[^\]]+\]\([^)]+\)", line))
    return image_or_link_lines / len(nonempty) >= 0.6


def _strip_leading_notice_lines(markdown: str, title: str) -> str:
    if "wikipedia" not in (title or "").lower() and "维基百科" not in (title or ""):
        return markdown

    lines = markdown.splitlines()
    h1_index = _first_h1_index(lines)
    if h1_index is None:
        return markdown

    cleaned = lines[: h1_index + 1]
    limit = min(len(lines), h1_index + 28)
    index = h1_index + 1
    while index < len(lines):
        line = lines[index]
        if index < limit and _is_leading_notice_line(line):
            index += 1
            continue
        if cleaned and cleaned[-1].startswith("#") and line.strip():
            cleaned.append("")
        cleaned.append(line)
        index += 1
    return "\n".join(cleaned).strip()


def _is_leading_notice_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    text = markdown_to_text(stripped).strip()
    lower = text.lower()
    if not text:
        return True
    if stripped.startswith("![") or re.match(r"^\[!\\?\[", stripped):
        return True
    notice_markers = (
        "from wikipedia, the free encyclopedia",
        "this article needs additional citations",
        "this section contains instructions or advice",
        "find sources:",
        "learn how and when to remove this message",
        "维基百科，自由的百科全书",
        "本页使用了标题或全文手工转换",
        "此條目或其章節",
        "请协助補充",
        "致使用者：请搜索",
    )
    return any(marker in lower or marker in text for marker in notice_markers)


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
        if _is_content_like_node(node):
            continue
        if node.xpath(".//article | .//main | .//*[@role='main']"):
            continue
        attrs = " ".join(filter(None, [node.get("class"), node.get("id")]))
        if NOISE_CLASS_RE.search(attrs) or _is_link_cluster_noise(node, topology):
            ids.update(_node_key(child) for child in node.iter())

    for node in root.xpath("//table | //tr | //td | //th"):
        if _node_key(node) in ids:
            continue
        if _is_content_like_node(node):
            continue
        if node.xpath(".//article | .//main | .//*[@role='main']"):
            continue
        attrs = " ".join(filter(None, [node.get("class"), node.get("id")]))
        if TABLE_NOISE_CLASS_RE.search(attrs) or _is_link_cluster_noise(node, topology):
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


def _is_content_like_node(node: etree._Element) -> bool:
    tag = _tag(node)
    if tag in {"article", "main"}:
        return True
    if (node.get("role") or "").lower() == "main":
        return True
    attrs = " ".join(filter(None, [node.get("class"), node.get("id")]))
    if CONTENT_CLASS_RE.search(attrs):
        return True
    return (node.get("id") or "").lower() in {"content", "content-inner", "artibody", "article_content", "ucap-content"}


def _is_link_cluster_noise(node: etree._Element, topology: LinkTopologyAnalyzer) -> bool:
    if topology.link_mass(node) <= 55.0:
        return False
    if _link_density(node) < 0.55:
        return False
    long_paragraphs = [
        paragraph for paragraph in node.xpath(".//p")
        if len(_compact_text(paragraph.text_content())) >= 80
    ]
    return len(long_paragraphs) < 2


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
