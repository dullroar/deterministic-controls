"""Check `translation.untranslated-heuristic` (advisory only).

Run me when: you want a hint that a translated Markdown file still has text in the source language.

This is a heuristic. It can be wrong in both directions. So it is advisory:
every finding has severity `info`, and the check never fails a run.

For each target file of the mapping the check splits the prose into segments
(paragraphs, list items, table cells, headings). It skips front matter,
fences, inline code, URLs, link destinations, `{{macro}}` and `[[macro]]`
tokens and the do-not-translate phrases of the parameter `dnt`. For each
segment it counts the words, and the words that are in the stopword list of
the source language. If the share is over the threshold, it reports the
segment.

No language is hard coded in the logic. The stopword list is a parameter.

Parameters:

- `mapping`: the mapping file (see `translation_common`). Absent: no findings.
- `exceptions`: optional exception file.
- `dnt`: optional text file, one do-not-translate phrase for each line.
- `source_stopwords`: list of source-language function words.
  The default is a list of unambiguous English function words.
- `target_stopwords`: words removed from the source list, because they are
  also words of the target language.
- `threshold`: share of stopwords that triggers a finding (default 0.30).
- `min_words`: shorter segments are skipped (default 6).

Rule ID: `segment`. A file of the target that is missing is not reported
here. The checks `translation.fences` and others report it.
"""

from __future__ import annotations

import re

from deterministic_controls.checks import translation_common as tc
from deterministic_controls.core.api import Context, Finding

CHECK_ID = "translation.untranslated-heuristic"
RULES = ("segment",)

DEFAULT_THRESHOLD = 0.30
DEFAULT_MIN_WORDS = 6

DEFAULT_SOURCE_STOPWORDS = tuple(
    "the and of to is are was were that with for this you your not from it be can "
    "what which when if or by an at on in has have will would should does do been "
    "being their there then than these those into about because while where who "
    "how why also only just but more most some any each every other such both".split()
)

_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
_CODE_SPAN = re.compile(r"(`+).+?\1")
_MACRO = re.compile(r"\{\{.*?\}\}|\[\[.*?\]\]")
_AUTOLINK = re.compile(r"<[A-Za-z][A-Za-z0-9+.-]*:[^>\s]*>")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_LINK_DEST = re.compile(r"(?<=\])\([^)\s]*(?:\s+[^)]*)?\)")
_URL = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://\S+|\bwww\.\S+")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_HEADING = re.compile(r"^ {0,3}#{1,6}(?:\s+|$)")
_SEPARATOR_ROW = re.compile(r"^[\s|:\-]+$")


def _parameter_words(context: Context, name: str, default: tuple[str, ...]) -> list[str]:
    value = context.parameters.get(name)
    if value is None:
        return list(default)
    if not isinstance(value, list) or not all(isinstance(w, str) for w in value):
        raise tc.ConfigError(f"parameter '{name}' must be a list of strings")
    return value


def _number(context: Context, name: str, default: float, kind: type) -> float:
    value = context.parameters.get(name)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise tc.ConfigError(f"parameter '{name}' must be a number")
    if kind is int and int(value) != value:
        raise tc.ConfigError(f"parameter '{name}' must be a whole number")
    if value < 0:
        raise tc.ConfigError(f"parameter '{name}' must not be negative")
    return kind(value)


def _load_dnt(context: Context) -> list[re.Pattern[str]]:
    value = context.parameters.get("dnt")
    if value is None:
        return []
    rel = tc._clean_relpath(value, "parameter 'dnt'")
    try:
        path = context.resolve(rel)
    except ValueError as error:
        raise tc.ConfigError(f"parameter 'dnt' leaves the repository: {value}", rel) from error
    if not path.is_file():
        raise tc.ConfigError(f"parameter 'dnt' names a missing file: {rel}", rel)
    try:
        text = context.read_text(rel)
    except (OSError, UnicodeDecodeError) as error:
        raise tc.ConfigError(f"cannot read {rel}: {error}", rel) from error
    phrases = sorted({p.strip() for p in text.splitlines() if p.strip()}, key=len, reverse=True)
    return [re.compile(rf"(?<!\w){re.escape(p)}(?!\w)", re.IGNORECASE) for p in phrases]


def _mask(text: str, dnt: list[re.Pattern[str]]) -> str:
    for pattern in (_CODE_SPAN, _MACRO, _AUTOLINK, _HTML_TAG, _LINK_DEST, _URL):
        text = pattern.sub(" ", text)
    for pattern in dnt:
        text = pattern.sub(" ", text)
    return text


def _segments(scan: tc.Scan) -> list[tuple[int, str]]:
    """Return (first line number, raw text) for each prose segment."""
    result: list[tuple[int, str]] = []
    paragraph: list[str] = []
    start = 0

    def flush() -> None:
        nonlocal paragraph
        if paragraph:
            result.append((start, " ".join(paragraph)))
        paragraph = []

    for line in scan.lines:
        if line.kind == tc.PROSE:
            text = line.text.strip()
            if _HEADING.match(line.text):
                flush()
                result.append((line.number, text))
                continue
            if _LIST_ITEM.match(line.text):
                flush()  # a list item starts a new segment and can continue
                start = line.number
                paragraph.append(text)
                continue
            if not paragraph:
                start = line.number
            paragraph.append(text)
        elif line.kind == tc.TABLE_ROW:
            flush()
            if _SEPARATOR_ROW.match(line.text):
                continue
            for cell in tc.split_table_row(line.text):
                result.append((line.number, cell))
        else:
            flush()
    flush()
    return result


def entry(context: Context) -> list[Finding]:
    parameters = {
        key: value for key, value in context.parameters.items()
        if not (key in ("mapping", "exceptions", "dnt") and value == "")
    }
    context = Context(context.root, parameters)
    try:
        threshold = _number(context, "threshold", DEFAULT_THRESHOLD, float)
        min_words = _number(context, "min_words", DEFAULT_MIN_WORDS, int)
        stop = {w.lower() for w in _parameter_words(
            context, "source_stopwords", DEFAULT_SOURCE_STOPWORDS)}
        stop -= {w.lower() for w in _parameter_words(context, "target_stopwords", ())}
        dnt = _load_dnt(context)
        mapping = tc.load_mapping(context)
        exceptions = tc.load_exceptions(context)
        if mapping is None:
            return []
        pairs, _pair_findings = tc.pair_documents(context, mapping, CHECK_ID)
    except tc.ConfigError as error:
        return [tc.bad_config_finding(CHECK_ID, error)]

    findings: list[Finding] = []
    for pair in pairs:
        if not pair.target_exists:
            continue
        scan = tc.scan_markdown(context.read_text(pair.target))
        for number, raw in _segments(scan):
            words = [w.lower() for w in _WORD.findall(_mask(raw, dnt))]
            if not words or len(words) < min_words:
                continue
            hits = sum(1 for w in words if w in stop)
            share = hits / len(words)
            if share > threshold:
                findings.append(tc.make_finding(
                    CHECK_ID, "segment", pair.target, number,
                    f"heuristic: {share:.0%} of {len(words)} words are source-language "
                    "stopwords; the segment may be untranslated",
                    source=pair.source, severity="info", evidence=raw[:80]))
    try:
        return tc.apply_exceptions(CHECK_ID, findings, exceptions)
    except tc.ConfigError as error:  # pragma: no cover - defensive
        return [tc.bad_config_finding(CHECK_ID, error)]
