"""Check `translation.structure`.

Run me when: a Markdown translation must keep the structure of its source.

For each pair of source and target files (from the parameter `mapping`) the
check compares: headings, table rows and cells, footnotes, bold spans, front
matter keys and Mermaid diagrams. The Mermaid fences are the only fences that
this check reads.

A Mermaid diagram has a skeleton (type, node IDs, arrows, shapes, directives)
and label slots (text that a translator may change). The skeleton is the
diagram with every label emptied. The skeleton and the label slots (line and
role) of the target must equal those of the source. A diagram that the check
does not understand is reported. It is never skipped.

Rule IDs: `headings`, `table-rows`, `table-cells`, `footnotes`, `bold-count`,
`front-matter`, `mermaid-skeleton`, `mermaid-label`, `mermaid-unsupported`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from deterministic_controls.checks import translation_common as tc
from deterministic_controls.core.api import Context, Finding

CHECK_ID = "translation.structure"

RULES = (
    "headings",
    "table-rows",
    "table-cells",
    "footnotes",
    "bold-count",
    "front-matter",
    "mermaid-skeleton",
    "mermaid-label",
    "mermaid-unsupported",
)

# --- Markdown structure -------------------------------------------------------

_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:\s+|$)")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_FOOTNOTE_REF = re.compile(r"\[\^([^\]\s]+)\](?!:)")
_FOOTNOTE_DEF = re.compile(r"^ {0,3}\[\^([^\]\s]+)\]:")
_FM_KEY = re.compile(r"^(\w[\w.-]*)\s*:\s*(.*)$")


def _strip_code(text: str) -> str:
    return _CODE_SPAN.sub("", text)


def _headings(scan: tc.Scan) -> list[tuple[int, int]]:
    result = []
    for line in scan.lines_of(tc.PROSE):
        match = _HEADING.match(line.text)
        if match:
            result.append((line.number, len(match.group(1))))
    return result


def _tables(scan: tc.Scan) -> list[list[tc.Line]]:
    tables: list[list[tc.Line]] = []
    previous = -10
    for line in scan.lines:
        if line.kind != tc.TABLE_ROW:
            continue
        if line.number == previous + 1 and tables:
            tables[-1].append(line)
        else:
            tables.append([line])
        previous = line.number
    return tables


def _text_lines(scan: tc.Scan) -> list[tc.Line]:
    return [l for l in scan.lines if l.kind in (tc.PROSE, tc.TABLE_ROW)]


def _footnotes(scan: tc.Scan) -> tuple[list[str], list[str]]:
    refs: list[str] = []
    defs: list[str] = []
    for line in _text_lines(scan):
        definition = _FOOTNOTE_DEF.match(line.text)
        if definition:
            defs.append(definition.group(1))
        refs.extend(_FOOTNOTE_REF.findall(_strip_code(line.text)))
    return sorted(refs), sorted(defs)


def _bold_count(scan: tc.Scan) -> int:
    return sum(len(_BOLD.findall(_strip_code(l.text))) for l in _text_lines(scan))


def _front_matter(scan: tc.Scan) -> dict[str, str] | None:
    lines = scan.lines_of(tc.FRONT_MATTER)
    if not lines:
        return None
    result: dict[str, str] = {}
    for line in lines[1:]:
        match = _FM_KEY.match(line.text)
        if match:
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            result[match.group(1)] = value
    return result


def _structure_findings(
    source: str, target: str, src: tc.Scan, tgt: tc.Scan, fixed_keys: list[str]
) -> list[Finding]:
    def find(rule: str, line: int | None, message: str) -> Finding:
        return tc.make_finding(CHECK_ID, rule, target, line, message, source=source)

    findings: list[Finding] = []

    # headings
    sh, th = _headings(src), _headings(tgt)
    if [lvl for _, lvl in sh] != [lvl for _, lvl in th]:
        index = next(
            (i for i, (a, b) in enumerate(zip(sh, th)) if a[1] != b[1]),
            min(len(sh), len(th)),
        )
        line = th[index][0] if index < len(th) else (th[-1][0] if th else 1)
        findings.append(find(
            "headings", line,
            f"headings differ: source has {len(sh)}, target has {len(th)}"
            f" (first difference at heading {index + 1})"))

    # tables
    st, tt = _tables(src), _tables(tgt)
    if len(st) != len(tt):
        line = tt[min(len(st), len(tt)) - 1][0].number if tt else 1
        findings.append(find(
            "table-rows", line, f"table count differs: source {len(st)}, target {len(tt)}"))
    for s_table, t_table in zip(st, tt):
        if len(s_table) != len(t_table):
            findings.append(find(
                "table-rows", t_table[0].number,
                f"table row count differs: source {len(s_table)}, target {len(t_table)}"))
            continue
        for s_row, t_row in zip(s_table, t_table):
            s_cells = len(tc.split_table_row(s_row.text))
            t_cells = len(tc.split_table_row(t_row.text))
            if s_cells != t_cells:
                findings.append(find(
                    "table-cells", t_row.number,
                    f"table cell count differs: source {s_cells}, target {t_cells}"))

    # footnotes
    s_refs, s_defs = _footnotes(src)
    t_refs, t_defs = _footnotes(tgt)
    if s_refs != t_refs:
        findings.append(find("footnotes", 1, "footnote references differ"))
    if s_defs != t_defs:
        findings.append(find("footnotes", 1, "footnote definitions differ"))

    # bold
    s_bold, t_bold = _bold_count(src), _bold_count(tgt)
    if s_bold != t_bold:
        findings.append(find(
            "bold-count", 1, f"bold span count differs: source {s_bold}, target {t_bold}"))

    # front matter
    s_fm, t_fm = _front_matter(src), _front_matter(tgt)
    if (s_fm is None) != (t_fm is None):
        findings.append(find("front-matter", 1, "front matter exists in only one file"))
    elif s_fm is not None and t_fm is not None:
        if sorted(s_fm) != sorted(t_fm):
            missing = sorted(set(s_fm) - set(t_fm))
            extra = sorted(set(t_fm) - set(s_fm))
            findings.append(find(
                "front-matter", 1,
                f"front matter keys differ: missing {missing}, extra {extra}"))
        for key in fixed_keys:
            if s_fm.get(key) != t_fm.get(key):
                findings.append(find(
                    "front-matter", 1, f"front matter value of '{key}' differs"))
    return findings


# --- Mermaid ------------------------------------------------------------------


class Unsupported(Exception):
    """The diagram uses something that this check does not understand."""


@dataclass
class Diagram:
    kind: str
    skeleton: list[str] = field(default_factory=list)
    slots: list[tuple[int, str]] = field(default_factory=list)  # (body line index, role)
    problems: list[tuple[int, str]] = field(default_factory=list)  # (body line index, text)


_ENTITY = re.compile(r"#(?:quot|gt|lt|\d+);")
_ID = r"[A-Za-z0-9_]+"
_ARROW = re.compile(r"<?(?:-\.+-|-{2,}|={2,})(?:>|[xo])?|~~~")
_EDGE_LABEL = re.compile(r"\|([^|]*)\|")
_NODE_ID = re.compile(_ID)
_OPENERS = r"\[\[|\[\(|\[/|\[\\|\[|\(\(\(|\(\(|\(\[|\(|\{\{|\{"
_CLOSERS = r"\]\]|\)\]|/\]|\\\]|\]|\)\)\)|\)\)|\]\)|\)|\}\}|\}"
_OPEN = re.compile(_OPENERS)
_QUOTED = re.compile(
    rf'"(.*?)"({_CLOSERS})(?=\s|$|&|;|-|=|~|<|:)'
)
_ACC = re.compile(r"^(accTitle|accDescr)\s*:\s*(.*)$")
_FLOW_KEYWORD = re.compile(r"^(end|direction\s+\w+|classDef\s.*|class\s.*|style\s.*|linkStyle\s.*)$")
_SUBGRAPH = re.compile(rf'^subgraph\s+({_ID})\s*(?:({_OPENERS})"(.*?)"({_CLOSERS}))?\s*$')


def _label_problems(diagram: Diagram, index: int, text: str, role: str) -> None:
    if not text.strip():
        diagram.problems.append((index, f"empty label ({role})"))
    if role in ("node-label", "subgraph-label", "edge-label") and '"' in text:
        diagram.problems.append((index, f"double quote in label ({role}); use #quot;"))
    if role in (
        "message", "note", "block", "participant-alias", "transition"
    ) and ";" in _ENTITY.sub("", text):
        diagram.problems.append((index, f"';' in label ({role})"))


def _slot(diagram: Diagram, index: int, role: str, text: str, *, allow_empty: bool = False) -> None:
    diagram.slots.append((index, role))
    if not (allow_empty and not text.strip()):
        _label_problems(diagram, index, text, role)


def _parse_flow_line(diagram: Diagram, index: int, line: str) -> None:
    if _FLOW_KEYWORD.match(line):
        diagram.skeleton.append(line)
        return
    sub = re.match(r"^subgraph\b", line)
    if sub:
        match = _SUBGRAPH.match(line)
        if not match:
            raise Unsupported(f"subgraph form not understood: {line}")
        if match.group(2):
            diagram.skeleton.append(f"subgraph {match.group(1)}{match.group(2)}{match.group(4)}")
            _slot(diagram, index, "subgraph-label", match.group(3))
        else:
            diagram.skeleton.append(f"subgraph {match.group(1)}")
        return
    out: list[str] = []
    pos = 0
    n = len(line)
    while pos < n:
        ch = line[pos]
        if ch in " \t&;":
            out.append(ch)
            pos += 1
            continue
        arrow = _ARROW.match(line, pos)
        if arrow:
            token = arrow.group(0)
            if token in ("--", "=="):
                raise Unsupported(f"text on link is not understood: {line}")
            out.append(token)
            pos = arrow.end()
            label = _EDGE_LABEL.match(line, pos)
            if label:
                out.append("||")
                _slot(diagram, index, "edge-label", label.group(1))
                pos = label.end()
            continue
        node = _NODE_ID.match(line, pos)
        if node:
            out.append(node.group(0))
            pos = node.end()
            opener = _OPEN.match(line, pos)
            if opener:
                if line[opener.end():opener.end() + 1] != '"':
                    raise Unsupported(f"unquoted node label: {line}")
                quoted = _QUOTED.match(line, opener.end())
                if not quoted:
                    diagram.problems.append((index, "label is not closed on its line"))
                    out.append(opener.group(0))
                    pos = n
                    continue
                out.append(opener.group(0) + quoted.group(2))
                _slot(diagram, index, "node-label", quoted.group(1))
                pos = quoted.end()
            style = re.match(r":::[\w-]+", line[pos:])
            if style:
                out.append(style.group(0))
                pos += style.end()
            continue
        raise Unsupported(f"text not understood: {line}")
    diagram.skeleton.append("".join(out))


_SEQ_MESSAGE = re.compile(
    rf"^({_ID})\s*(-->>|->>|--x|-x|--\)|-\)|-->|->)\s*([+-]?)({_ID})\s*:\s*(.*)$"
)
_SEQ_PARTICIPANT = re.compile(rf"^(participant|actor)\s+({_ID})(?:\s+as\s+(.*))?$")
_SEQ_NOTE = re.compile(rf"^Note\s+(left of|right of|over)\s+({_ID}(?:\s*,\s*{_ID})?)\s*:\s*(.*)$")
_SEQ_BLOCK = re.compile(r"^(loop|alt|else|opt|par|and|critical|option|break)(?:\s+(.*))?$")
_SEQ_PLAIN = re.compile(rf"^(autonumber|end|(?:de)?activate\s+{_ID}|rect\s.*)$")


def _parse_sequence_line(diagram: Diagram, index: int, line: str) -> None:
    if _SEQ_PLAIN.match(line):
        diagram.skeleton.append(line)
        return
    part = _SEQ_PARTICIPANT.match(line)
    if part:
        if part.group(3) is None:
            diagram.skeleton.append(f"{part.group(1)} {part.group(2)}")
        else:
            diagram.skeleton.append(f"{part.group(1)} {part.group(2)} as")
            _slot(diagram, index, "participant-alias", part.group(3))
        return
    note = _SEQ_NOTE.match(line)
    if note:
        diagram.skeleton.append(f"Note {note.group(1)} {note.group(2)}:")
        _slot(diagram, index, "note", note.group(3))
        return
    block = _SEQ_BLOCK.match(line)
    if block:
        diagram.skeleton.append(block.group(1))
        if block.group(2):
            _slot(diagram, index, "block", block.group(2))
        return
    message = _SEQ_MESSAGE.match(line)
    if message:
        diagram.skeleton.append(
            f"{message.group(1)}{message.group(2)}{message.group(3)}{message.group(4)}:")
        _slot(diagram, index, "message", message.group(5))
        return
    raise Unsupported(f"line not understood: {line}")


_STATE_ID = r"(?:\[\*\]|\w+)"
_STATE_ALIAS = re.compile(rf'^state\s+"(.*)"\s+as\s+(\w+)$')
_STATE_TRANSITION = re.compile(rf"^({_STATE_ID})\s*-->\s*({_STATE_ID})(?:\s*:\s*(.*))?$")
_STATE_DESCRIPTION = re.compile(r"^(\w+)\s*:\s*(.*)$")
_STATE_NOTE = re.compile(r"^note\s+(left of|right of)\s+(\w+)\s*:\s*(.*)$")
_STATE_PLAIN = re.compile(
    r"^(state\s+\w+(?:\s*\{|\s*<<\w+>>)?|\}|--|direction\s+\w+|classDef\s.*|class\s.*|style\s.*|\w+)$"
)


def _parse_state_line(diagram: Diagram, index: int, line: str) -> None:
    alias = _STATE_ALIAS.match(line)
    if alias:
        diagram.skeleton.append(f'state "" as {alias.group(2)}')
        _slot(diagram, index, "state-label", alias.group(1))
        return
    transition = _STATE_TRANSITION.match(line)
    if transition:
        text = f"{transition.group(1)} --> {transition.group(2)}"
        if transition.group(3) is None:
            diagram.skeleton.append(text)
        else:
            diagram.skeleton.append(text + " :")
            _slot(diagram, index, "transition", transition.group(3))
        return
    note = _STATE_NOTE.match(line)
    if note:
        diagram.skeleton.append(f"note {note.group(1)} {note.group(2)} :")
        _slot(diagram, index, "note", note.group(3))
        return
    if _STATE_PLAIN.match(line):
        diagram.skeleton.append(line)
        return
    description = _STATE_DESCRIPTION.match(line)
    if description:
        diagram.skeleton.append(f"{description.group(1)} :")
        _slot(diagram, index, "state-description", description.group(2))
        return
    raise Unsupported(f"line not understood: {line}")


_TYPE_FLOW = re.compile(r"^(flowchart|graph)(?:\s+(TB|TD|BT|RL|LR))?$")


def parse_mermaid(body: tuple[str, ...]) -> Diagram:
    """Parse the body of a Mermaid fence. Raise `Unsupported` if not understood."""
    lines = [(i, raw.strip()) for i, raw in enumerate(body) if raw.strip()]
    if not lines:
        raise Unsupported("the diagram is empty")
    first_index, first = lines[0]
    flow = _TYPE_FLOW.match(first)
    if flow:
        kind, parser = "flowchart", _parse_flow_line
    elif first == "sequenceDiagram":
        kind, parser = "sequenceDiagram", _parse_sequence_line
    elif first == "stateDiagram-v2":
        kind, parser = "stateDiagram-v2", _parse_state_line
    else:
        raise Unsupported(f"diagram type not understood: {first.split()[0] if first.split() else first}")
    diagram = Diagram(kind)
    diagram.skeleton.append(first)
    for index, line in lines[1:]:
        if line.startswith("%%{"):
            raise Unsupported("directive is not understood")
        if line.startswith("%%"):
            diagram.skeleton.append("%%")
            diagram.slots.append((index, "comment"))
            continue
        if re.match(r"^click\b", line):
            raise Unsupported("click is not understood")
        acc = _ACC.match(line)
        if acc:
            diagram.skeleton.append(f"{acc.group(1)}:")
            _slot(diagram, index, acc.group(1), acc.group(2))
            continue
        if re.match(r"^accDescr\b", line):
            raise Unsupported("multi-line accDescr is not understood")
        parser(diagram, index, line)
    return diagram


def _mermaid_fences(scan: tc.Scan) -> list[tc.Fence]:
    return [f for f in scan.fences if f.language == "mermaid"]


def _mermaid_findings(
    source: str, target: str, src: tc.Scan, tgt: tc.Scan
) -> list[Finding]:
    def find(rule: str, line: int | None, message: str) -> Finding:
        return tc.make_finding(CHECK_ID, rule, target, line, message, source=source)

    findings: list[Finding] = []
    s_fences, t_fences = _mermaid_fences(src), _mermaid_fences(tgt)
    if len(s_fences) != len(t_fences):
        line = t_fences[-1].open_line if t_fences else 1
        findings.append(find(
            "mermaid-skeleton", line,
            f"diagram count differs: source {len(s_fences)}, target {len(t_fences)}"))
    for s_fence, t_fence in zip(s_fences, t_fences):
        if s_fence.close_line is None or t_fence.close_line is None:
            findings.append(find(
                "mermaid-unsupported", t_fence.open_line, "Mermaid fence is not closed"))
            continue
        try:
            s_diagram = parse_mermaid(s_fence.body)
        except Unsupported as error:
            findings.append(find(
                "mermaid-unsupported", t_fence.open_line,
                f"source diagram is not understood: {error}"))
            continue
        try:
            t_diagram = parse_mermaid(t_fence.body)
        except Unsupported as error:
            findings.append(find(
                "mermaid-unsupported", t_fence.open_line,
                f"diagram is not understood: {error}"))
            continue
        base = t_fence.open_line + 1  # body index 0 is on this line
        for index, text in t_diagram.problems:
            findings.append(find("mermaid-label", base + index, text))
        if s_diagram.kind != t_diagram.kind or s_diagram.skeleton != t_diagram.skeleton:
            position = next(
                (i for i, (a, b) in enumerate(zip(s_diagram.skeleton, t_diagram.skeleton)) if a != b),
                min(len(s_diagram.skeleton), len(t_diagram.skeleton)),
            )
            findings.append(find(
                "mermaid-skeleton", t_fence.open_line,
                f"diagram skeleton differs (first difference at statement {position + 1}"
                f"; source has {len(s_diagram.skeleton)}, target has {len(t_diagram.skeleton)})"))
        elif [r for _, r in s_diagram.slots] != [r for _, r in t_diagram.slots] or [
            i for i, _ in s_diagram.slots
        ] != [i for i, _ in t_diagram.slots]:
            findings.append(find(
                "mermaid-skeleton", t_fence.open_line, "diagram label slots differ"))
    return findings


# --- Entry --------------------------------------------------------------------


def _string_list(context: Context, name: str) -> list[str]:
    value = context.parameters.get(name, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise tc.ConfigError(f"parameter '{name}' must be a list of non-empty strings")
    return value


def entry(context: Context) -> list[Finding]:
    parameters = {
        key: value for key, value in context.parameters.items()
        if not (key in ("mapping", "exceptions") and value == "")
    }
    context = Context(context.root, parameters)
    try:
        disabled = _string_list(context, "disabled_rules")
        unknown = sorted(set(disabled) - set(RULES))
        if unknown:
            raise tc.ConfigError(f"unknown rule in disabled_rules: {', '.join(unknown)}")
        fixed_keys = _string_list(context, "fixed_front_matter_keys")
        mapping = tc.load_mapping(context)
        exceptions = tc.load_exceptions(context)
        if mapping is None:
            return []
        pairs, findings = tc.pair_documents(context, mapping, CHECK_ID)
    except tc.ConfigError as error:
        return [tc.bad_config_finding(CHECK_ID, error)]

    for pair in pairs:
        if not pair.target_exists:
            continue
        src = tc.scan_markdown(context.read_text(pair.source))
        tgt = tc.scan_markdown(context.read_text(pair.target))
        for scan, path in ((src, pair.source), (tgt, pair.target)):
            for problem in scan.problems:
                if problem.rule == "unclosed-fence" and _opens_mermaid(scan, problem.line):
                    continue  # reported as mermaid-unsupported
                findings.append(tc.make_finding(
                    CHECK_ID, problem.rule, pair.target, problem.line,
                    f"{problem.message} in {path}", source=pair.source))
        findings.extend(_structure_findings(pair.source, pair.target, src, tgt, fixed_keys))
        findings.extend(_mermaid_findings(pair.source, pair.target, src, tgt))

    dropped = {f"{CHECK_ID}.{name}" for name in disabled}
    findings = [f for f in findings if f.rule_id not in dropped]
    try:
        return tc.apply_exceptions(CHECK_ID, findings, exceptions)
    except tc.ConfigError as error:  # pragma: no cover - defensive
        return [tc.bad_config_finding(CHECK_ID, error)]


def _opens_mermaid(scan: tc.Scan, line: int) -> bool:
    return any(f.open_line == line and f.language == "mermaid" for f in scan.fences)
