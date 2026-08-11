"""TEDS (Tree-Edit-Distance-based Similarity) scoring for table structure.

Same metric family as PubTabNet / ICDAR table recognition and Upstage's own
DP-Bench, so the numbers are comparable to published table-recognition scores:
each `<table>` is parsed into a tree, APTED computes the tree edit distance, and

    TEDS = 1 - distance / max(|tree_gt|, |tree_pred|)

Two conventions worth stating, because they decide what counts as an error:

* `rowspan`/`colspan` are folded into a cell's node label
  (`td[rowspan=6,colspan=1]`), so a merged cell and an unmerged one are a
  *structural* mismatch (full rename cost), not a text mismatch. This is what
  makes the Upstage markdown-duplication behaviour — one `rowspan=6` cell
  re-emitted as six repeated cells — score low, which is the point.
* `<tr>` directly under `<table>` is wrapped in an implicit `<tbody>`, matching
  the HTML tree-construction spec. Otherwise an engine that omits the optional
  `<tbody>` tag would be penalized for markup style rather than structure.

Cell *text* is compared with a normalized character edit distance and only
contributes when the two cells are otherwise structurally identical, exactly as
in the original TEDS formulation.
"""

from __future__ import annotations

from html.parser import HTMLParser
from itertools import permutations
from typing import Any

from apted import APTED, Config

from . import scoring

CELL_TAGS = frozenset({"td", "th"})
SECTION_TAGS = frozenset({"thead", "tbody", "tfoot"})
ROW_TAG = "tr"
TABLE_TAG = "table"
STRUCTURAL_TAGS = CELL_TAGS | SECTION_TAGS | {ROW_TAG, TABLE_TAG}

# Above this many tables on one page the exhaustive GT<->prediction assignment
# stops being cheap. The real corpus tops out at 2 tables per page, so this is
# a guard against pathological engine output, not a normal path.
MAX_EXHAUSTIVE_TABLES = 6


class TableNode:
    """One node of a table tree: a tag, its span identity, and its text."""

    __slots__ = ("tag", "rowspan", "colspan", "children", "_text")

    def __init__(self, tag: str, rowspan: int = 1, colspan: int = 1):
        self.tag = tag
        self.rowspan = rowspan
        self.colspan = colspan
        self.children: list["TableNode"] = []
        self._text: list[str] = []

    @property
    def name(self) -> str:
        """Label used for tree comparison. APTED reads `.name` by default."""
        if self.tag in CELL_TAGS:
            return f"{self.tag}[rowspan={self.rowspan},colspan={self.colspan}]"
        return self.tag

    @property
    def content(self) -> str:
        return scoring.normalize("".join(self._text))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<TableNode {self.name} {len(self.children)} children>"


def tree_size(node: TableNode) -> int:
    return 1 + sum(tree_size(child) for child in node.children)


def _span(attrs: dict[str, str | None], key: str) -> int:
    try:
        value = int(str(attrs.get(key, "1")).strip())
    except (TypeError, ValueError):
        return 1
    return value if value >= 1 else 1


class _TableTreeBuilder(HTMLParser):
    """Tolerant table parser.

    Engine output is not guaranteed to be well-formed — closing `</td>` and
    `</tr>` tags are routinely omitted — so open cells and rows are closed
    implicitly when the next structural tag arrives, the way a browser does.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[TableNode] = []
        self._stack: list[TableNode] = []

    # -- stack helpers ----------------------------------------------------
    def _top(self) -> TableNode | None:
        return self._stack[-1] if self._stack else None

    def _push(self, node: TableNode) -> None:
        parent = self._top()
        if parent is not None:
            parent.children.append(node)
        elif node.tag == TABLE_TAG:
            self.tables.append(node)
        self._stack.append(node)

    def _close_through(self, tags: frozenset[str] | set[str]) -> None:
        while self._stack and self._stack[-1].tag in tags:
            self._stack.pop()

    # -- HTMLParser hooks -------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in STRUCTURAL_TAGS:
            return

        attr_map = {k.lower(): v for k, v in attrs}

        if tag in CELL_TAGS:
            self._close_through(CELL_TAGS)
            if self._top() is None or self._top().tag != ROW_TAG:
                self._start_row()
            self._push(
                TableNode(tag, _span(attr_map, "rowspan"), _span(attr_map, "colspan"))
            )
            return

        if tag == ROW_TAG:
            self._close_through(CELL_TAGS)
            self._close_through({ROW_TAG})
            self._start_row()
            return

        if tag in SECTION_TAGS:
            self._close_through(CELL_TAGS)
            self._close_through({ROW_TAG})
            self._close_through(SECTION_TAGS)
            if self._top() is not None and self._top().tag == TABLE_TAG:
                self._push(TableNode(tag))
            return

        self._push(TableNode(TABLE_TAG))

    def _start_row(self) -> None:
        # HTML tree construction inserts a <tbody> around bare <tr>s; doing the
        # same here means `<table><tr>` and `<table><tbody><tr>` compare equal.
        if self._top() is not None and self._top().tag == TABLE_TAG:
            self._push(TableNode("tbody"))
        self._push(TableNode(ROW_TAG))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag not in STRUCTURAL_TAGS:
            return
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        node = self._top()
        if node is not None and node.tag in CELL_TAGS:
            node._text.append(data)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br":
            node = self._top()
            if node is not None and node.tag in CELL_TAGS:
                node._text.append(" ")
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


def parse_tables(html: str) -> list[TableNode]:
    """Parse every top-level `<table>` in `html` into a tree."""
    if not html or not html.strip():
        return []
    builder = _TableTreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.tables


def split_table_blocks(text: str) -> list[str]:
    """Pull `<table>...</table>` blocks out of free-form model output.

    Claude is asked for bare HTML, but a stray markdown fence or a sentence of
    preamble must not turn into a parse failure that scores as a missing table.
    """
    if not text:
        return []
    blocks: list[str] = []
    lowered = text.lower()
    cursor = 0
    while True:
        start = lowered.find("<table", cursor)
        if start == -1:
            return blocks
        end = lowered.find("</table>", start)
        if end == -1:
            blocks.append(text[start:])
            return blocks
        end += len("</table>")
        blocks.append(text[start:end])
        cursor = end


def normalized_edit_distance(a: str, b: str) -> float:
    """Levenshtein distance divided by the longer string's length."""
    if a == b:
        return 0.0
    if not a or not b:
        return 1.0

    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (char_a != char_b),
                )
            )
        previous = current
    return previous[-1] / max(len(a), len(b))


class TedsConfig(Config):
    """APTED cost model.

    A label mismatch (different tag, or different rowspan/colspan) costs a full
    rename. Only cells that already agree structurally are compared on text, so
    span errors can never be discounted down to a text-level difference.
    """

    valuecls = float

    def delete(self, node: TableNode) -> float:
        return 1.0

    def insert(self, node: TableNode) -> float:
        return 1.0

    def rename(self, node1: TableNode, node2: TableNode) -> float:
        if node1.name != node2.name:
            return 1.0
        if node1.tag in CELL_TAGS:
            content1, content2 = node1.content, node2.content
            if content1 or content2:
                return normalized_edit_distance(content1, content2)
        return 0.0

    def children(self, node: TableNode) -> list[TableNode]:
        return node.children


def teds(gt_tree: TableNode, pred_tree: TableNode) -> float:
    distance = APTED(gt_tree, pred_tree, TedsConfig()).compute_edit_distance()
    denominator = max(tree_size(gt_tree), tree_size(pred_tree))
    if not denominator:
        return 0.0
    return max(0.0, min(1.0, 1.0 - distance / denominator))


def flatten_headers(table: TableNode) -> TableNode:
    """Rewrite a table tree so header markup no longer distinguishes cells.

    `<th>` becomes `<td>` and thead/tbody/tfoot collapse into one `<tbody>`,
    leaving the cell grid and its spans as the only thing compared. CLOVA's
    General OCR returns a bare grid with no header concept, so under the strict
    metric it would lose points on every header row for a capability it does
    not claim. Scoring both ways separates "got the grid wrong" from "does not
    emit header markup".
    """
    flat = TableNode(TABLE_TAG)
    body = TableNode("tbody")
    flat.children.append(body)

    def collect_rows(node: TableNode) -> None:
        for child in node.children:
            if child.tag in SECTION_TAGS:
                collect_rows(child)
            elif child.tag == ROW_TAG:
                row = TableNode(ROW_TAG)
                for cell in child.children:
                    if cell.tag not in CELL_TAGS:
                        continue
                    copy = TableNode("td", cell.rowspan, cell.colspan)
                    copy._text = [cell.content]
                    row.children.append(copy)
                body.children.append(row)

    collect_rows(table)
    return flat


def _best_assignment(matrix: list[list[float]], n_pred: int) -> list[int | None]:
    """Pick one prediction per GT table maximizing the total score.

    Only 1-2 tables per page exist in this corpus, so an exhaustive search is
    cheaper than pulling in an assignment-problem dependency. Beyond
    `MAX_EXHAUSTIVE_TABLES` it degrades to greedy rather than blowing up.
    """
    n_gt = len(matrix)
    if not n_gt or not n_pred:
        return [None] * n_gt

    if max(n_gt, n_pred) > MAX_EXHAUSTIVE_TABLES:
        assignment: list[int | None] = [None] * n_gt
        taken: set[int] = set()
        order = sorted(
            ((matrix[g][p], g, p) for g in range(n_gt) for p in range(n_pred)),
            reverse=True,
        )
        for _, gt_index, pred_index in order:
            if assignment[gt_index] is None and pred_index not in taken:
                assignment[gt_index] = pred_index
                taken.add(pred_index)
        return assignment

    # Pad with None so that when there are fewer predictions than ground-truth
    # tables, every choice of *which* table goes unmatched is considered — not
    # just leaving the trailing ones empty.
    slots: list[int | None] = list(range(n_pred)) + [None] * max(0, n_gt - n_pred)
    best: list[int | None] = [None] * n_gt
    best_total = -1.0
    for candidate in permutations(slots, n_gt):
        total = sum(matrix[g][p] for g, p in enumerate(candidate) if p is not None)
        if total > best_total:
            best_total = total
            best = list(candidate)
    return best


def score_tables(
    ground_truth_htmls: list[str], predicted_htmls: list[str]
) -> dict[str, Any]:
    """Score one page's predicted tables against its ground-truth tables.

    Every ground-truth table must be matched; an unmatched one scores 0, so a
    missing table is penalized. Extra predicted tables are reported but not
    penalized — an engine that also finds a table the ground truth does not
    cover has not made the scored tables any worse.

    `no_prediction` separates "the engine returned no table at all" from "the
    engine returned a badly structured table", which the report presents
    differently.
    """
    gt_trees = [tree for html in ground_truth_htmls for tree in parse_tables(html)]
    pred_trees = [tree for html in predicted_htmls for tree in parse_tables(html)]

    matrix = [[teds(gt, pred) for pred in pred_trees] for gt in gt_trees]
    assignment = _best_assignment(matrix, len(pred_trees))

    gt_flat = [flatten_headers(tree) for tree in gt_trees]
    pred_flat = [flatten_headers(tree) for tree in pred_trees]

    tables = []
    for gt_index, pred_index in enumerate(assignment):
        matched_pred = pred_index is not None
        tables.append(
            {
                "gt_index": gt_index,
                "pred_index": pred_index,
                "teds": matrix[gt_index][pred_index] if matched_pred else 0.0,
                "teds_header_agnostic": (
                    teds(gt_flat[gt_index], pred_flat[pred_index])
                    if matched_pred
                    else 0.0
                ),
                "n_nodes_gt": tree_size(gt_trees[gt_index]),
                "n_nodes_pred": (
                    tree_size(pred_trees[pred_index]) if matched_pred else 0
                ),
            }
        )

    matched = {p for p in assignment if p is not None}

    def page_mean(key: str) -> float | None:
        return sum(t[key] for t in tables) / len(tables) if tables else None

    return {
        "teds": page_mean("teds"),
        "teds_header_agnostic": page_mean("teds_header_agnostic"),
        "n_tables_gt": len(gt_trees),
        "n_tables_pred": len(pred_trees),
        "no_prediction": not pred_trees,
        "missing_tables": sum(1 for entry in tables if entry["pred_index"] is None),
        "extra_tables": sorted(set(range(len(pred_trees))) - matched),
        "tables": tables,
    }
