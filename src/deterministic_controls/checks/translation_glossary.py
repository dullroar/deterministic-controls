"""Check `translation.glossary`: approved and banned renderings of terms.

The check is generic. It works on any Markdown-to-Markdown translation that
has a mapping file. The terms come from a glossary file, not from code.

Parameters:

- `glossary`: a TOML file (or a JSON file, name ends in `.json`) with an array
  of tables `[[terms]]`. A term has `id`, `en` (source text), `target`
  (approved rendering) and `banned` (list of strings, may be empty).
- `mapping`: the pack mapping file. It pairs source and target documents.
- `dnt`: optional text file with one do-not-translate phrase on each line.
- `exceptions`: optional exception file of the pack.

No `glossary` parameter: no findings. A glossary file that is missing or has
bad syntax gives `bad-glossary`. It is never a pass.

Matching rule: the text is normalized to Unicode NFC. Letter case is ignored.
A match is a whole word: the characters before and after it are not letters,
digits or combining marks. So `net` does not match in `network`. Fenced
blocks, front matter, whole-line HTML comments, inline code, URLs, autolinks,
HTML tags and link destinations are skipped. The check works on a whole
document: a term is "in the source" if it is in any non-skipped text of the
source document.

Rules:

- `bad-glossary`: a term without `id`, `en` or `target`; a duplicate `id`; a
  `banned` entry that is empty or not a string; an approved rendering that is
  in its own `banned` list; a banned word that is the approved rendering of
  another term; a missing or bad glossary or DNT file.
- `missing-rendering`: the source holds the term, the target holds no
  approved rendering of it.
- `banned-term`: the source holds the term and the target holds a banned
  word of it.
- `dnt-missing`: a DNT phrase is in the source and not in the target.
"""

from __future__ import annotations

import json
import re
import tomllib
import unicodedata
from dataclasses import dataclass

from deterministic_controls.checks import translation_common as tc
from deterministic_controls.core.api import Context, Finding

CHECK_ID = "translation.glossary"

_MASKS = (
    re.compile(r"`+[^`]*?`+"),  # inline code
    re.compile(r"<[^<>\n]*>"),  # autolinks and HTML tags
    re.compile(r"\]\([^)\n]*\)"),  # link destinations
    re.compile(r"^\s*\[[^\]\n]+\]:\s*\S+", re.MULTILINE),  # reference definitions
    re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://\S+"),  # bare URLs
    re.compile(r"\bwww\.\S+"),
)


@dataclass(frozen=True)
class Term:
    id: str
    en: str
    target: str
    banned: tuple[str, ...]


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Return (line number, masked line) for each line that the check reads."""
    scan = tc.scan_markdown(text)
    result = []
    for line in scan.lines:
        if line.kind in (tc.PROSE, tc.TABLE_ROW):
            masked = unicodedata.normalize("NFC", line.text)
            for pattern in _MASKS:
                masked = pattern.sub(_blank, masked)
            result.append((line.number, masked))
    return result


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or unicodedata.category(ch).startswith("M")


def find_word(line: str, phrase: str) -> bool:
    """True if `phrase` is in `line` as a whole word. NFC and case are ignored."""
    hay, needle = _norm(line), _norm(phrase)
    if not needle:
        return False
    start = hay.find(needle)
    while start != -1:
        end = start + len(needle)
        before_ok = start == 0 or not _is_word_char(hay[start - 1])
        after_ok = end == len(hay) or not _is_word_char(hay[end])
        if before_ok and after_ok:
            return True
        start = hay.find(needle, start + 1)
    return False


def _first_line(lines: list[tuple[int, str]], phrase: str) -> int | None:
    for number, text in lines:
        if find_word(text, phrase):
            return number
    return None


# --- Glossary loading --------------------------------------------------------


def _load_terms(context: Context) -> tuple[list[Term], str, list[str]] | None:
    """Return (terms, glossary path, problems), or None if not configured."""
    loaded = tc._read_parameter_file(context, "glossary")
    if loaded is None:
        return None
    rel, text = loaded
    try:
        if rel.endswith(".json"):
            data = json.loads(text)
        else:
            data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, json.JSONDecodeError) as error:
        raise tc.ConfigError(f"glossary file has bad syntax: {error}", rel) from error
    if not isinstance(data, dict) or not isinstance(data.get("terms", []), list):
        raise tc.ConfigError("glossary must have an array of tables 'terms'", rel)
    problems: list[str] = []
    terms: list[Term] = []
    seen: set[str] = set()
    for index, row in enumerate(data.get("terms", []), 1):
        if not isinstance(row, dict):
            problems.append(f"term {index} is not a table")
            continue
        values = {}
        for key in ("id", "en", "target"):
            value = row.get(key)
            if not isinstance(value, str) or not value.strip():
                problems.append(f"term {index} has no '{key}'")
            else:
                values[key] = value.strip()
        banned_raw = row.get("banned", [])
        banned: list[str] = []
        if not isinstance(banned_raw, list):
            problems.append(f"term {index}: 'banned' must be a list")
            banned_raw = []
        for word in banned_raw:
            if not isinstance(word, str) or not word.strip():
                problems.append(f"term {index}: a banned entry is empty or not a string")
            else:
                banned.append(word.strip())
        if len(values) < 3:
            continue
        if values["id"] in seen:
            problems.append(f"duplicate term id: {values['id']}")
            continue
        seen.add(values["id"])
        term = Term(values["id"], values["en"], values["target"], tuple(banned))
        if _norm(term.target) in {_norm(b) for b in term.banned}:
            problems.append(f"term {term.id}: approved rendering is in its own banned list")
        terms.append(term)
    for term in terms:
        for other in terms:
            if other is not term and _norm(other.target) in {_norm(b) for b in term.banned}:
                problems.append(
                    f"term {term.id}: banned word is the approved rendering of term {other.id}")
    return terms, rel, problems


def _load_dnt(context: Context) -> list[str]:
    loaded = tc._read_parameter_file(context, "dnt")
    if loaded is None:
        return []
    _, text = loaded
    return [line.strip() for line in text.splitlines() if line.strip()]


# --- Check -------------------------------------------------------------------


def _check_pair(
    pair: tc.Pair, source_text: str, target_text: str, terms: list[Term], dnt: list[str],
) -> list[Finding]:
    findings: list[Finding] = []
    source_lines = prose_lines(source_text)
    target_lines = prose_lines(target_text)
    for finding in tc.scan_findings(CHECK_ID, pair.target, tc.scan_markdown(target_text),
                                    source=pair.source):
        findings.append(finding)
    for term in terms:
        if _first_line(source_lines, term.en) is None:
            continue
        if _first_line(target_lines, term.target) is None:
            findings.append(tc.make_finding(
                CHECK_ID, "missing-rendering", pair.target, 1,
                f"term {term.id}: approved rendering '{term.target}' is not in the target",
                source=pair.source, evidence=term.en))
        for word in term.banned:
            line = _first_line(target_lines, word)
            if line is not None:
                findings.append(tc.make_finding(
                    CHECK_ID, "banned-term", pair.target, line,
                    f"term {term.id}: banned word '{word}' is in the target",
                    source=pair.source, evidence=word))
    for phrase in dnt:
        if _first_line(source_lines, phrase) is not None \
                and _first_line(target_lines, phrase) is None:
            findings.append(tc.make_finding(
                CHECK_ID, "dnt-missing", pair.target, 1,
                f"do-not-translate phrase is not in the target: {phrase}",
                source=pair.source, evidence=phrase))
    return findings


def entry(context: Context) -> list[Finding]:
    # The catalog defaults are empty strings. An empty string means "not set".
    params = {k: v for k, v in context.parameters.items() if v != ""}
    context = Context(context.root, params)
    if context.parameters.get("glossary") is None:
        return []
    try:
        loaded = _load_terms(context)
        assert loaded is not None
        terms, glossary_path, problems = loaded
        dnt = _load_dnt(context)
    except tc.ConfigError as error:
        return [tc.make_finding(CHECK_ID, "bad-glossary", error.path, None, str(error))]
    if problems:
        return [tc.make_finding(CHECK_ID, "bad-glossary", glossary_path, None, p)
                for p in problems]
    try:
        mapping = tc.load_mapping(context)
        rows = tc.load_exceptions(context)
        if mapping is None:
            return []
        pairs, findings = tc.pair_documents(context, mapping, CHECK_ID)
    except tc.ConfigError as error:
        return [tc.bad_config_finding(CHECK_ID, error)]
    for pair in pairs:
        if not pair.target_exists:
            continue
        findings.extend(_check_pair(
            pair, context.read_text(pair.source), context.read_text(pair.target), terms, dnt))
    return tc.apply_exceptions(CHECK_ID, findings, rows)
