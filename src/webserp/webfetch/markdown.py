"""HTML subtree to Markdown conversion for webfetch."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Iterable
from urllib.parse import urljoin

from lxml import etree, html

from .types import CodeBlock, Image, Link, MarkdownAssets

BLOCK_TAGS = {
    "article",
    "aside",
    "blockquote",
    "div",
    "dl",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
}
NOISE_TAGS = {"script", "style", "noscript", "iframe", "svg", "canvas", "button", "input", "textarea"}
CODE_CLASS_RE = re.compile(r"(?:language|lang|highlight)-([A-Za-z0-9_+#.-]+)|\b(js|ts|python|py|rust|go|java|bash|sh|sql|json|yaml|html|css)\b", re.I)
TABLE_SEP_RE = re.compile(r"^\|\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|$")


def convert_elements(
    elements: Iterable[html.HtmlElement],
    base_url: str,
    *,
    exclude_keys: set[str] | None = None,
) -> tuple[str, str, MarkdownAssets]:
    converter = MarkdownConverter(base_url=base_url, exclude_keys=exclude_keys or set())
    markdown = converter.convert_many(elements)
    markdown = collapse_whitespace(markdown)
    text = markdown_to_text(markdown)
    return markdown, text, converter.assets


class MarkdownConverter:
    def __init__(self, base_url: str, exclude_keys: set[str]):
        self.base_url = base_url
        self.exclude_keys = exclude_keys
        self.assets = MarkdownAssets()

    def convert_many(self, elements: Iterable[html.HtmlElement]) -> str:
        parts: list[str] = []
        for element in elements:
            chunk = self.node_to_md(element, list_depth=0)
            if chunk.strip():
                parts.append(chunk.strip())
        return "\n\n".join(parts)

    def node_to_md(self, node: etree._Element, list_depth: int = 0) -> str:
        if _node_key(node) in self.exclude_keys:
            return ""
        tag = _tag(node)
        if tag in NOISE_TAGS:
            return ""

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            text = self.inline_text(node)
            return f"\n\n{'#' * level} {text}\n\n" if text else ""
        if tag == "p":
            text = self.inline_text(node)
            return f"\n\n{text}\n\n" if text else ""
        if tag == "br":
            return "\n"
        if tag == "hr":
            return "\n\n---\n\n"
        if tag == "a":
            return self.link_to_md(node)
        if tag == "img":
            return self.image_to_md(node)
        if tag in {"strong", "b"}:
            text = self.inline_text(node)
            return f"**{text}**" if text else ""
        if tag in {"em", "i"}:
            text = self.inline_text(node)
            return f"*{text}*" if text else ""
        if tag == "code":
            if _has_ancestor(node, "pre"):
                return _collect_text_preserve(node)
            code = _collect_text(node)
            return f"`{code}`" if code else ""
        if tag == "pre":
            return self.pre_to_md(node)
        if tag == "blockquote":
            inner = self.children_to_md(node, list_depth).strip()
            if not inner:
                return ""
            quoted = "\n".join(f"> {line}" for line in inner.splitlines())
            return f"\n\n{quoted}\n\n"
        if tag in {"ul", "ol"}:
            return f"\n\n{self.list_to_md(node, list_depth, ordered=tag == 'ol')}\n\n"
        if tag == "li":
            text = self.inline_text(node)
            return f"{'  ' * list_depth}- {text}\n" if text else ""
        if tag == "table":
            return f"\n\n{self.table_to_md(node)}\n\n"

        return self.children_to_md(node, list_depth)

    def children_to_md(self, node: etree._Element, list_depth: int) -> str:
        out = []
        if node.text:
            out.append(node.text)
        for child in node:
            if isinstance(child.tag, str):
                out.append(self.node_to_md(child, list_depth=list_depth))
            if child.tail:
                out.append(child.tail)
        return _join_chunks(out)

    def inline_text(self, node: etree._Element) -> str:
        out = []
        if node.text:
            out.append(node.text)
        for child in node:
            if isinstance(child.tag, str):
                out.append(self.node_to_md(child, list_depth=0))
            if child.tail:
                out.append(child.tail)
        return " ".join(_join_chunks(out).split())

    def link_to_md(self, node: etree._Element) -> str:
        text = self.inline_text(node)
        href = self.resolve(node.get("href", ""))
        if text and href:
            self.assets.links.append(Link(text=text, href=href))
            return f"[{text}]({href})"
        return text

    def image_to_md(self, node: etree._Element) -> str:
        alt = " ".join((node.get("alt") or "").split())
        src = self.resolve(_best_image_src(node))
        if not src:
            return ""
        self.assets.images.append(Image(alt=alt, src=src))
        return f"![{alt}]({src})"

    def pre_to_md(self, node: etree._Element) -> str:
        code_el = node.xpath(".//code")
        target = code_el[0] if code_el else node
        code = _collect_pre_text(target).strip("\n")
        language = _language(node, target)
        self.assets.code_blocks.append(CodeBlock(language=language, code=code))
        return f"\n\n```{language}\n{code}\n```\n\n"

    def list_to_md(self, node: etree._Element, list_depth: int, ordered: bool) -> str:
        lines = []
        index = 1
        for child in node:
            if _tag(child) != "li":
                continue
            bullet = f"{index}." if ordered else "-"
            if ordered:
                index += 1
            inline_parts = []
            nested_parts = []
            if child.text:
                inline_parts.append(child.text)
            for li_child in child:
                tag = _tag(li_child)
                if tag in {"ul", "ol"}:
                    nested_parts.append(self.list_to_md(li_child, list_depth + 1, ordered=tag == "ol"))
                else:
                    inline_parts.append(self.node_to_md(li_child, list_depth=list_depth))
                if li_child.tail:
                    inline_parts.append(li_child.tail)
            text = " ".join(_join_chunks(inline_parts).split())
            if text:
                lines.append(f"{'  ' * list_depth}{bullet} {text}")
            lines.extend(nested_parts)
        return "\n".join(line for line in lines if line)

    def table_to_md(self, table: etree._Element) -> str:
        rows, is_layout = flatten_table(table)
        if not rows:
            return ""
        if is_layout:
            blocks = []
            for row in rows:
                for cell in row:
                    cell_html = cell.get("html") or ""
                    if not cell_html:
                        continue
                    fragment = html.fragment_fromstring(f"<div>{cell_html}</div>", create_parent=False)
                    block = self.node_to_md(fragment).strip()
                    if block:
                        blocks.append(block)
            return "\n\n".join(blocks)

        width = max(len(row) for row in rows)
        normalized = [row + [{"text": ""}] * (width - len(row)) for row in rows]
        header = [cell["text"] for cell in normalized[0]]
        output = [
            "| " + " | ".join(_escape_table_cell(value) for value in header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for row in normalized[1:]:
            output.append("| " + " | ".join(_escape_table_cell(cell["text"]) for cell in row) + " |")
        return "\n".join(output)

    def resolve(self, value: str) -> str:
        if not value:
            return ""
        value = value.strip()
        if value.startswith(("data:", "blob:", "javascript:", "mailto:", "tel:", "#")):
            return ""
        if value.startswith("//"):
            return "https:" + value
        return urljoin(self.base_url, value)


def flatten_table(table: etree._Element) -> tuple[list[list[dict[str, str]]], bool]:
    matrix: list[list[dict[str, str] | None]] = []
    is_layout = False
    rows = table.xpath(".//tr")
    for y, row in enumerate(rows):
        x = 0
        cells = row.xpath("./th | ./td")
        for cell in cells:
            while len(matrix) > y and len(matrix[y]) > x and matrix[y][x] is not None:
                x += 1
            colspan = _int_attr(cell, "colspan", 1)
            rowspan = _int_attr(cell, "rowspan", 1)
            text = " ".join(cell.text_content().split())
            html_text = "".join(etree.tostring(child, encoding="unicode") for child in cell)
            if cell.text:
                html_text = cell.text + html_text
            if _contains_block(cell):
                is_layout = True
            for dy in range(rowspan):
                target_y = y + dy
                while len(matrix) <= target_y:
                    matrix.append([])
                for dx in range(colspan):
                    target_x = x + dx
                    while len(matrix[target_y]) <= target_x:
                        matrix[target_y].append(None)
                    matrix[target_y][target_x] = {"text": text if dx == 0 and dy == 0 else "", "html": html_text}
            x += colspan
    return [[cell or {"text": "", "html": ""} for cell in row] for row in matrix], is_layout


def collapse_whitespace(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    blank = 0
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line.rstrip())
            blank = 0
            continue
        if in_fence:
            out.append(line.rstrip())
            continue
        stripped = line.rstrip()
        if not stripped:
            blank += 1
            if blank <= 1:
                out.append("")
            continue
        blank = 0
        out.append(stripped)
    return "\n".join(out).strip()


def markdown_to_text(markdown: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", markdown)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    output = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        stripped = line.strip()
        if TABLE_SEP_RE.match(stripped):
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            stripped = "\t".join(cell.strip() for cell in stripped.strip("|").split("|"))
        output.append(stripped)
    return "\n".join(line for line in output if line).strip()


def _tag(node: etree._Element) -> str:
    return str(node.tag).lower() if isinstance(node.tag, str) else ""


def _node_key(node: etree._Element) -> str:
    return node.getroottree().getpath(node)


def _join_chunks(chunks: Iterable[str]) -> str:
    out = ""
    for chunk in chunks:
        if not chunk:
            continue
        if out and not out[-1].isspace() and not chunk[0].isspace() and chunk[0] not in ".,;:!?)]}%":
            out += " "
        out += chunk
    return out


def _collect_text(node: etree._Element) -> str:
    return " ".join(node.text_content().split())


def _collect_text_preserve(node: etree._Element) -> str:
    return "".join(node.itertext())


def _collect_pre_text(node: etree._Element) -> str:
    clone = deepcopy(node)
    for br in clone.xpath(".//br"):
        br.tail = "\n" + (br.tail or "")
    return "".join(clone.itertext())


def _has_ancestor(node: etree._Element, tag: str) -> bool:
    parent = node.getparent()
    while parent is not None:
        if _tag(parent) == tag:
            return True
        parent = parent.getparent()
    return False


def _language(*nodes: etree._Element) -> str:
    for node in nodes:
        cls = node.get("class", "")
        match = CODE_CLASS_RE.search(cls)
        if match:
            return _normalize_lang(match.group(1) or match.group(2) or "")
    return ""


def _normalize_lang(language: str) -> str:
    lower = language.lower()
    return {
        "javascript": "js",
        "typescript": "ts",
        "python": "python",
        "py": "python",
        "shell": "bash",
        "sh": "bash",
        "yml": "yaml",
    }.get(lower, lower)


def _best_image_src(node: etree._Element) -> str:
    for attr in ("src", "data-src", "data-lazy-src", "data-original"):
        value = node.get(attr)
        if value and not value.startswith(("data:", "blob:")):
            return value
    return _best_srcset(node.get("srcset", ""))


def _best_srcset(srcset: str) -> str:
    best_url = ""
    best_size = -1
    for entry in srcset.split(","):
        parts = entry.strip().split()
        if not parts:
            continue
        url = parts[0]
        if url.startswith(("data:", "blob:")):
            continue
        size = 1
        if len(parts) > 1:
            match = re.search(r"(\d+)", parts[1])
            if match:
                size = int(match.group(1))
        if size > best_size:
            best_url = url
            best_size = size
    return best_url


def _contains_block(node: etree._Element) -> bool:
    return any(_tag(desc) in BLOCK_TAGS for desc in node.iterdescendants())


def _int_attr(node: etree._Element, name: str, default: int) -> int:
    try:
        return max(1, int(node.get(name, default)))
    except (TypeError, ValueError):
        return default


def _escape_table_cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")
