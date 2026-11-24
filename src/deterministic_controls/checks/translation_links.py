"""Check `translation.links`.

It compares the links of each target document with the links of its source
document. The mapping file gives the pairs, the path renames and the anchor
renames. The check is read-only. It never fetches an external URL.

Rules:

- `destination-differs`: the links of the target are not the links of the
  source after the path renames and anchor renames.
- `external-differs`: an external URL (it has a scheme) is not equal.
- `missing-file`: a relative path of the target does not exist.
- `missing-anchor`: a `#fragment` matches no heading ID and no `id=` or
  `name=` attribute of the target file.
- `line-anchor`: a `#L12` or `#L12-L20` range is invalid or past the end of
  the target file.
- `foreign-repository`: a link or image of the target points into the URL
  named by the optional parameter `source_repository_url`.

The check is generic. It needs no language, book or project name: it works on
any Markdown-to-Markdown translation that has a source manifest. Without the
parameter `mapping` it gives no findings.
"""

from __future__ import annotations

import posixpath
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote

from deterministic_controls.checks import translation_common as tc
from deterministic_controls.core.api import Context, Finding

CHECK_ID = "translation.links"

SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)")
MACRO = re.compile(r"\{\{.*?\}\}|\[\[.*?\]\]")
HTML_COMMENT = re.compile(r"<!--.*?-->")
INLINE_LINK = re.compile(r"\]\(\s*(<[^>\n]*>|[^\s)]*)")
DEFINITION = re.compile(r"^ {0,3}\[([^\]]+)\]:[ \t]*(<[^>\n]*>|\S+)")
HTML_ATTR = re.compile(r"""\b(?:href|src)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>"']+))""", re.I)
AUTOLINK = re.compile(r"<([A-Za-z][A-Za-z0-9+.\-]*:[^\s<>]*)>")
ID_ATTR = re.compile(r"""\b(?:id|name)\s*=\s*(?:"([^"]+)"|'([^']+)')""", re.I)
ATX = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
SETEXT = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
LINE_ANCHOR_LIKE = re.compile(r"^L\d+(?:-.*)?$")
LINE_ANCHOR = re.compile(r"^L(\d+)(?:-L(\d+))?$")
ANCHOR_FILES = (".md", ".markdown", ".html", ".htm")


@dataclass(frozen=True)
class Link:
    line: int
    column: int
    dest: str


def _blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def _masked_lines(scan: tc.Scan) -> list[tuple[int, str]]:
    """Return (line number, text) of the lines outside code, with code masked."""
    result = []
    for line in scan.lines:
        if line.kind in (tc.FRONT_MATTER, tc.FENCE, tc.HTML_COMMENT, tc.BLANK):
            continue
        text = HTML_COMMENT.sub(_blank, line.text)
        text = INLINE_CODE.sub(_blank, text)
        text = MACRO.sub(_blank, text)
        result.append((line.number, text))
    return result


def extract_links(scan: tc.Scan) -> list[Link]:
    """Return links, images and HTML `href` and `src` in document order."""
    links: list[Link] = []
    for number, text in _masked_lines(scan):
        for match in INLINE_LINK.finditer(text):
            links.append(Link(number, match.start(1), match.group(1).strip("<>")))
        definition = DEFINITION.match(text)
        if definition and not definition.group(1).startswith("^"):
            links.append(Link(number, definition.start(2), definition.group(2).strip("<>")))
        for match in HTML_ATTR.finditer(text):
            value = next(g for g in match.groups() if g is not None)
            links.append(Link(number, match.start(), value))
        for match in AUTOLINK.finditer(text):
            links.append(Link(number, match.start(1), match.group(1)))
    return sorted((link for link in links if link.dest), key=lambda l: (l.line, l.column))


# --- Anchors ------------------------------------------------------------------


def heading_id(title: str) -> str:
    """GitHub style heading ID, without the duplicate suffix."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", title)
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"[`*]", "", text)
    text = unicodedata.normalize("NFC", text.strip().lower())
    kept = []
    for ch in text:
        if ch in "-_ " or unicodedata.category(ch)[0] in "LMN":
            kept.append("-" if ch == " " else ch)
    return "".join(kept)


def anchors_of(text: str) -> set[str]:
    """Heading IDs and explicit `id=` or `name=` values of a document."""
    scan = tc.scan_markdown(text)
    result: set[str] = set()
    seen: dict[str, int] = {}

    def add_heading(title: str) -> None:
        explicit = re.search(r"\s*\{#([^\s}]+)\}\s*$", title)
        if explicit:
            result.add(explicit.group(1))
            title = title[: explicit.start()]
        base = heading_id(title)
        count = seen.get(base, 0)
        seen[base] = count + 1
        result.add(base if count == 0 else f"{base}-{count}")

    previous: tc.Line | None = None
    for line in scan.lines:
        if line.kind == tc.PROSE:
            atx = ATX.match(line.text)
            if atx:
                add_heading(atx.group(1) or "")
                previous = None
                continue
            if SETEXT.match(line.text) and previous is not None:
                add_heading(previous.text)
                previous = None
                continue
            previous = line
        else:
            previous = None
    for number, line_text in _masked_lines(scan):
        for match in ID_ATTR.finditer(line_text):
            result.add(match.group(1) or match.group(2))
    return result


def _normalize_fragment(fragment: str) -> str:
    return unicodedata.normalize("NFC", unquote(fragment))


# --- Destinations -------------------------------------------------------------


def _split(dest: str) -> tuple[str, str, str]:
    """Split a destination into path, query and fragment."""
    rest, _, fragment = dest.partition("#")
    path, _, query = rest.partition("?")
    return path, query, fragment


def _key(dest: str, file_path: str) -> tuple:
    """Normal form of a destination as seen from `file_path` (repository path)."""
    if SCHEME.match(dest):
        return ("external", dest)
    if dest.startswith(("/", "\\")):
        return ("opaque", dest)
    path, query, fragment = _split(dest)
    if path:
        absolute = posixpath.normpath(posixpath.join(posixpath.dirname(file_path), unquote(path)))
    else:
        absolute = file_path
    return ("relative", absolute, query, _normalize_fragment(fragment))


def _map_key(key: tuple, mapping: tc.Mapping, source: str, target: str) -> tuple:
    """Map the normal form of a source destination to the expected target form."""
    if key[0] != "relative":
        return key
    _, absolute, query, fragment = key
    fragment = tc.map_anchor(mapping, fragment)
    if absolute == source:
        mapped = target
    else:
        root = mapping.source_root
        prefix = f"{root}/" if root else ""
        if root and absolute == root:
            mapped = mapping.target_root
        elif absolute.startswith(prefix) and not absolute.startswith("../"):
            relative = absolute[len(prefix):]
            relative = mapping.path_renames.get(relative, relative)
            mapped = f"{mapping.target_root}/{relative}" if mapping.target_root else relative
        else:
            mapped = absolute
    return ("relative", mapped, query, fragment)


class _Files:
    """Cached facts about the files that the links point to."""

    def __init__(self, context: Context):
        self.context = context
        self._anchors: dict[str, set[str]] = {}
        self._lines: dict[str, int] = {}

    def exists(self, path: str) -> bool:
        try:
            return self.context.resolve(path or ".").exists()
        except ValueError:
            return False

    def is_file(self, path: str) -> bool:
        try:
            return self.context.resolve(path).is_file()
        except ValueError:
            return False

    def anchors(self, path: str) -> set[str]:
        if path not in self._anchors:
            self._anchors[path] = anchors_of(self.context.read_text(path))
        return self._anchors[path]

    def line_count(self, path: str) -> int:
        if path not in self._lines:
            data = self.context.read_bytes(path)
            count = data.count(b"\n")
            if data and not data.endswith(b"\n"):
                count += 1
            self._lines[path] = count
        return self._lines[path]


# --- The check ----------------------------------------------------------------


def _source_url(context: Context) -> str | None:
    value = context.parameters.get("source_repository_url")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise tc.ConfigError("parameter 'source_repository_url' must be a non-empty string")
    return value.strip().rstrip("/")


def _is_foreign(dest: str, url: str) -> bool:
    low, base = dest.lower(), url.lower()
    return low.startswith(base) and (len(low) == len(base) or low[len(base)] in "/#?")


def _check_target_link(
    files: _Files, link: Link, target: str, source: str
) -> list[Finding]:
    """Rules `missing-file`, `missing-anchor` and `line-anchor` for one link."""
    key = _key(link.dest, target)
    if key[0] != "relative":
        return []
    _, absolute, _query, fragment = key
    found: list[Finding] = []

    def finding(rule: str, message: str) -> Finding:
        return tc.make_finding(
            CHECK_ID, rule, target, link.line, message, source=source, evidence=link.dest)

    if absolute.startswith("../") or absolute == ".." or not files.exists(absolute):
        return [finding("missing-file", f"link target does not exist: {link.dest}")]
    if not fragment or not files.is_file(absolute):
        return found
    if LINE_ANCHOR_LIKE.match(fragment):
        match = LINE_ANCHOR.match(fragment)
        total = files.line_count(absolute)
        if match is None:
            found.append(finding("line-anchor", f"line anchor is not valid: #{fragment}"))
        else:
            first = int(match.group(1))
            last = int(match.group(2)) if match.group(2) else first
            if first < 1 or last < first:
                found.append(finding("line-anchor", f"line range is not valid: #{fragment}"))
            elif last > total:
                found.append(finding(
                    "line-anchor", f"line {last} is past the end of {absolute} ({total} lines)"))
        return found
    if absolute.lower().endswith(ANCHOR_FILES):
        known = {a.lower() for a in files.anchors(absolute)}
        if fragment.lower() not in known:
            found.append(finding("missing-anchor", f"no heading or id matches: #{fragment}"))
    return found


def _compare_pair(
    pair: tc.Pair, mapping: tc.Mapping, source_links: list[Link],
    target_links: list[Link], foreign: set[int],
) -> list[Finding]:
    found: list[Finding] = []
    if len(source_links) != len(target_links):
        extra = target_links[len(source_links)] if len(target_links) > len(source_links) else None
        line = extra.line if extra else (target_links[-1].line if target_links else 1)
        found.append(tc.make_finding(
            CHECK_ID, "destination-differs", pair.target, line,
            f"link count differs: source has {len(source_links)}, target has {len(target_links)}",
            source=pair.source))
    for index, (src, tgt) in enumerate(zip(source_links, target_links)):
        if index in foreign:
            continue
        expected = _map_key(_key(src.dest, pair.source), mapping, pair.source, pair.target)
        actual = _key(tgt.dest, pair.target)
        if expected == actual:
            continue
        rule = "external-differs" if expected[0] == "external" else "destination-differs"
        found.append(tc.make_finding(
            CHECK_ID, rule, pair.target, tgt.line,
            f"link {index + 1} differs: source has '{src.dest}', target has '{tgt.dest}'",
            source=pair.source, evidence=tgt.dest))
    return found


def entry(context: Context) -> list[Finding]:
    # The catalog gives "" for a parameter that is not configured.
    configured = {k: v for k, v in context.parameters.items() if v != ""}
    context = Context(context.root, configured)
    try:
        mapping = tc.load_mapping(context)
        if mapping is None:
            return []
        exceptions = tc.load_exceptions(context)
        url = _source_url(context)
        pairs, findings = tc.pair_documents(context, mapping, CHECK_ID)
    except tc.ConfigError as error:
        return [tc.bad_config_finding(CHECK_ID, error)]

    files = _Files(context)
    for pair in pairs:
        if not pair.target_exists:
            continue
        source_scan = tc.scan_markdown(context.read_text(pair.source))
        target_scan = tc.scan_markdown(context.read_text(pair.target))
        findings.extend(tc.scan_findings(CHECK_ID, pair.target, target_scan, source=pair.source))
        findings.extend(tc.scan_findings(CHECK_ID, pair.source, source_scan))
        source_links = extract_links(source_scan)
        target_links = extract_links(target_scan)
        foreign: set[int] = set()
        for index, link in enumerate(target_links):
            if url and _is_foreign(link.dest, url):
                foreign.add(index)
                findings.append(tc.make_finding(
                    CHECK_ID, "foreign-repository", pair.target, link.line,
                    f"link points into the source repository: {link.dest}",
                    source=pair.source, evidence=link.dest))
            findings.extend(_check_target_link(files, link, pair.target, pair.source))
        findings.extend(_compare_pair(pair, mapping, source_links, target_links, foreign))
    return tc.apply_exceptions(CHECK_ID, findings, exceptions)
