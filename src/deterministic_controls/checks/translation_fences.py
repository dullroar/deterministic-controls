"""Check `translation.fences`.

Any translation keeps code blocks byte for byte. This check pairs each source
Markdown file with its target file (parameter `mapping`) and compares the
fenced blocks in order.

Rules (the finding path is the target path, or the source path for a source
fence that never closes):

- `translation.fences.count`: the number of fences differs.
- `translation.fences.kind`: the fence character or the language tag differs.
- `translation.fences.code-differs`: the body is not byte-identical.
- `translation.fences.unclosed`: a fence never closes. It is never a skip.
- `translation.fences.inline-code`: with `inline_code = true`, the multiset
  of inline code spans differs.
- `translation.fences.missing-target` and the other mapping rules come from
  `translation_common`.
- `translation.fences.bad-config`: a parameter is present but wrong.

Parameters: `mapping` (absent: the check passes), `exceptions`,
`translatable_kinds` (default `["mermaid"]`; blocks of these kinds are not
compared here) and `inline_code` (default `false`).

The check reads files as bytes. A line ending difference is a difference.
"""

from __future__ import annotations

import re
from collections import Counter

from deterministic_controls.checks import translation_common as tc
from deterministic_controls.core.api import Context, Finding

CHECK_ID = "translation.fences"

_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")


def _read(context: Context, path: str) -> str:
    # Bytes, not text: `read_text` would change CRLF to LF.
    return context.read_bytes(path).decode("utf-8", errors="surrogateescape")


def _raw_lines(text: str) -> list[str]:
    raw = text.split("\n")
    if raw and raw[-1] == "":
        raw.pop()
    return raw


def _params(context: Context) -> tuple[set[str], bool]:
    kinds = context.parameters.get("translatable_kinds", ["mermaid"])
    if not isinstance(kinds, list) or not all(isinstance(k, str) for k in kinds):
        raise tc.ConfigError("parameter 'translatable_kinds' must be a list of strings")
    inline = context.parameters.get("inline_code", False)
    if not isinstance(inline, bool):
        raise tc.ConfigError("parameter 'inline_code' must be true or false")
    return set(kinds), inline


def _bodies(scan: tc.Scan, raw: list[str]) -> list[str]:
    result = []
    for fence in scan.fences:
        end = len(raw) if fence.close_line is None else fence.close_line - 1
        result.append("\n".join(raw[fence.open_line:end]))
    return result


def _spans(scan: tc.Scan) -> Counter:
    spans: Counter = Counter()
    for line in scan.lines:
        if line.kind in (tc.PROSE, tc.TABLE_ROW):
            for match in _CODE_SPAN.finditer(line.text):
                spans[match.group(2)] += 1
    return spans


def _compare(pair: tc.Pair, source_text: str, target_text: str,
             kinds: set[str], inline: bool) -> list[Finding]:
    findings: list[Finding] = []
    src_scan = tc.scan_markdown(source_text)
    tgt_scan = tc.scan_markdown(target_text)
    unclosed = False
    for path, scan, other in ((pair.source, src_scan, None), (pair.target, tgt_scan, pair.source)):
        for problem in scan.problems:
            if problem.rule == "unclosed-fence":
                unclosed = True
                findings.append(tc.make_finding(
                    CHECK_ID, "unclosed", path, problem.line, problem.message, source=other))
    if unclosed:
        return findings
    src_fences, tgt_fences = src_scan.fences, tgt_scan.fences
    if len(src_fences) != len(tgt_fences):
        findings.append(tc.make_finding(
            CHECK_ID, "count", pair.target, 1,
            f"fence count differs: source {len(src_fences)}, target {len(tgt_fences)}",
            source=pair.source))
    else:
        src_bodies = _bodies(src_scan, _raw_lines(source_text))
        tgt_bodies = _bodies(tgt_scan, _raw_lines(target_text))
        for index, (a, b) in enumerate(zip(src_fences, tgt_fences)):
            if (a.char, a.language) != (b.char, b.language):
                findings.append(tc.make_finding(
                    CHECK_ID, "kind", pair.target, b.open_line,
                    f"fence {index + 1} kind differs: source {a.char!r} {a.language!r}, "
                    f"target {b.char!r} {b.language!r}",
                    source=pair.source))
                continue
            if a.language in kinds:
                continue
            if src_bodies[index] != tgt_bodies[index]:
                findings.append(tc.make_finding(
                    CHECK_ID, "code-differs", pair.target, b.open_line,
                    f"fence {index + 1} body is not byte-identical to the source",
                    source=pair.source))
    if inline:
        src_spans, tgt_spans = _spans(src_scan), _spans(tgt_scan)
        if src_spans != tgt_spans:
            for span, number in sorted((src_spans - tgt_spans).items()):
                findings.append(tc.make_finding(
                    CHECK_ID, "inline-code", pair.target, 1,
                    f"inline code span dropped {number} time(s)",
                    source=pair.source, evidence=span))
            for span, number in sorted((tgt_spans - src_spans).items()):
                findings.append(tc.make_finding(
                    CHECK_ID, "inline-code", pair.target, 1,
                    f"inline code span invented {number} time(s)",
                    source=pair.source, evidence=span))
    return findings


def entry(context: Context) -> list[Finding]:
    # The catalog must declare each parameter, and TOML has no null. The
    # catalog default "" for `mapping` and `exceptions` means "not configured".
    params = {
        key: value for key, value in context.parameters.items()
        if not (key in ("mapping", "exceptions") and value == "")
    }
    context = Context(context.root, params)
    try:
        mapping = tc.load_mapping(context)
        if mapping is None:
            return []
        exceptions = tc.load_exceptions(context)
        kinds, inline = _params(context)
        pairs, findings = tc.pair_documents(context, mapping, CHECK_ID)
    except tc.ConfigError as error:
        return [tc.bad_config_finding(CHECK_ID, error)]
    for pair in pairs:
        if pair.target_exists:
            findings.extend(_compare(
                pair, _read(context, pair.source), _read(context, pair.target), kinds, inline))
    return sorted(tc.apply_exceptions(CHECK_ID, findings, exceptions), key=Finding.sort_key)
