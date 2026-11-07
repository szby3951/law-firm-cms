"""富文本（HTML）→ docx 导出工具。

前端文书编辑器（7.2 的 wangEditor）产出 HTML，这里用一个轻量解析器把
常见块级/行内标签还原为 python-docx 的段落、表格与图片，并按法律文书
的排版习惯输出：

- 标题：二号加粗居中；
- 正文：宋体小四、1.5 倍行距、首行缩进 2 字符；
- 表格：Table Grid 边框、五号字；
- 图片：居中，最大宽度 15cm。

不做完整 HTML 渲染（不支持 CSS 布局/字体颜色），只保证内容与结构正确。
"""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser

from docx import Document as DocxDocument
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

# 正文与标题字体：法律文书习惯用宋体，避免导出后字体回退成 Calibri
BODY_FONT = "宋体"
TITLE_SIZE = Pt(22)  # 二号
BODY_SIZE = Pt(12)  # 小四
TABLE_SIZE = Pt(10.5)  # 五号

# 会被当作独立段落处理的块级标签
_BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "li", "blockquote", "pre"}
_HEADING_SIZES = {"h1": Pt(16), "h2": Pt(15), "h3": Pt(14), "h4": Pt(12)}

_BASE64_IMAGE = re.compile(r"^data:image/[\w.+-]+;base64,(.+)$", re.DOTALL)


@dataclass
class _Run:
    """一个行内片段：文本 + 加粗/斜体标记。"""

    text: str
    bold: bool = False
    italic: bool = False


@dataclass
class _Block:
    """一个块级元素：段落、标题、列表项、表格或图片。"""

    kind: str = "p"
    runs: list[_Run] = field(default_factory=list)
    align: str | None = None
    rows: list[list[str]] = field(default_factory=list)
    image: bytes | None = None


class _HtmlBlockParser(HTMLParser):
    """把 HTML 切成块级元素序列，行内只保留加粗/斜体信息。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self._runs: list[_Run] = []
        self._kind: str | None = None
        self._align: str | None = None
        self._bold = 0
        self._italic = 0
        # 表格解析状态
        self._in_table = False
        self._table_rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    # -- 行内 -------------------------------------------------------------
    def _append(self, text: str) -> None:
        """追加文本到当前块，相同格式的相邻片段合并。"""
        text = text.replace("\xa0", " ")
        if not text:
            return
        bold, italic = self._bold > 0, self._italic > 0
        if self._runs:
            last = self._runs[-1]
            if last.bold == bold and last.italic == italic:
                last.text += text
                return
        self._runs.append(_Run(text=text, bold=bold, italic=italic))

    def _flush(self) -> None:
        """结束当前块，压入结果列表。"""
        kind = self._kind or "p"
        runs = self._runs
        align = self._align
        self._runs = []
        self._kind = None
        self._align = None
        if not runs:
            return
        # 纯空白段落保留一个空段（用于分隔署名、日期等），避免全被吞掉
        if len(runs) == 1 and not runs[0].text.strip() and "\n" not in runs[0].text:
            return
        self.blocks.append(_Block(kind=kind, runs=runs, align=align))

    # -- 标签 -------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in ("strong", "b"):
            self._bold += 1
            return
        if tag in ("em", "i"):
            self._italic += 1
            return
        if tag == "br":
            self._append("\n")
            return
        if tag == "img":
            self._push_image(dict(attrs).get("src") or "")
            return
        if tag == "table":
            self._flush()
            self._in_table = True
            self._table_rows = []
            return

        if self._in_table:
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th"):
                self._cell = []
            return

        if tag in _BLOCK_TAGS:
            self._flush()
            self._kind = tag
            self._align = _parse_align(dict(attrs).get("style") or "")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        """自闭合标签（如 ``<br/>``、``<img/>``）。"""
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("strong", "b"):
            self._bold = max(0, self._bold - 1)
            return
        if tag in ("em", "i"):
            self._italic = max(0, self._italic - 1)
            return
        if tag == "table":
            self._close_cell()
            self._close_row()
            if self._table_rows:
                self.blocks.append(
                    _Block(kind="table", rows=self._table_rows)
                )
            self._table_rows = []
            self._in_table = False
            return

        if self._in_table:
            if tag in ("td", "th"):
                self._close_cell()
            elif tag == "tr":
                self._close_row()
            return

        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_table:
            if self._cell is not None:
                self._cell.append(data)
            return
        self._append(data)

    # -- 表格/图片辅助 -----------------------------------------------------
    def _close_cell(self) -> None:
        if self._cell is None:
            return
        text = unescape("".join(self._cell)).replace("\xa0", " ").strip()
        if self._row is None:
            self._row = []
        self._row.append(text)
        self._cell = None

    def _close_row(self) -> None:
        if self._row is None:
            return
        if any(cell for cell in self._row):
            self._table_rows.append(self._row)
        self._row = None

    def _push_image(self, src: str) -> None:
        """仅处理 base64 内嵌图片，外链图片跳过（避免导出时联网下载）。"""
        match = _BASE64_IMAGE.match(src.strip())
        if not match:
            return
        try:
            raw = base64.b64decode(match.group(1), validate=False)
        except (ValueError, TypeError):
            return
        if raw:
            self._flush()
            self.blocks.append(_Block(kind="image", image=raw))


def _parse_align(style: str) -> str | None:
    """从 style 属性里取 text-align。"""
    lowered = style.replace(" ", "").lower()
    if "text-align:center" in lowered:
        return "center"
    if "text-align:right" in lowered:
        return "right"
    if "text-align:justify" in lowered:
        return "justify"
    return None


def _looks_like_html(text: str) -> bool:
    """粗略判断正文是 HTML 还是纯文本。"""
    return bool(
        re.search(
            r"<(p|div|br|h[1-6]|ul|ol|li|table|img|strong)\b",
            text,
            re.IGNORECASE,
        )
    )


def html_to_text(content: str | None) -> str:
    """把 HTML 正文转成纯文本，用于列表摘要与全文搜索。"""
    if not content:
        return ""
    if not _looks_like_html(content):
        return re.sub(r"\s+", " ", content).strip()
    text = re.sub(
        r"<(br|/p|/div|/li|/tr|/h[1-6])\s*/?>",
        "\n",
        content,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    lines = [
        re.sub(r"[ \t\r\f\v]+", " ", line).strip()
        for line in unescape(text).splitlines()
    ]
    return "\n".join(line for line in lines if line)


def _setup_document() -> DocxDocument:
    """页面与默认样式：A4、公文页边距、宋体正文。"""
    doc = DocxDocument()
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(3.17)
    section.right_margin = Cm(3.17)

    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = BODY_SIZE
    # 中文字体需要单独设置 eastAsia，否则 Word 会回退到西文字体
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    normal.paragraph_format.line_spacing = 1.5
    return doc


def _style_run(run, *, size, bold: bool = False, italic: bool = False) -> None:
    """统一设置字体、字号、加粗/斜体与中文字体。"""
    run.font.name = BODY_FONT
    run.font.size = size
    run.bold = bold
    run.italic = italic
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), BODY_FONT)


def _add_runs(paragraph, block: _Block, default_bold: bool = False) -> None:
    """把块内片段写入段落，``\n`` 转为换行。"""
    for run in block.runs:
        pieces = run.text.split("\n")
        for idx, piece in enumerate(pieces):
            if idx:
                paragraph.add_run().add_break()
            if piece:
                _style_run(
                    paragraph.add_run(piece),
                    size=BODY_SIZE,
                    bold=run.bold or default_bold,
                    italic=run.italic,
                )


def _add_table(doc: DocxDocument, rows: list[list[str]]) -> None:
    """追加表格：首行视为表头加粗，整体 Table Grid 边框。"""
    cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=cols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for r_idx, row in enumerate(rows):
        for c_idx in range(cols):
            cell = table.cell(r_idx, c_idx)
            text = row[c_idx] if c_idx < len(row) else ""
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.line_spacing = 1.0
            run = paragraph.add_run(text)
            _style_run(run, size=TABLE_SIZE, bold=(r_idx == 0))
    doc.add_paragraph()


def _add_image(doc: DocxDocument, raw: bytes) -> None:
    """追加图片，宽度不超过正文宽度（15cm）。"""
    try:
        doc.add_picture(io.BytesIO(raw), width=Cm(15))
    except Exception:  # noqa: BLE001  图片格式不受支持时降级为占位文字
        doc.add_paragraph("［图片］")
        return
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER


def build_docx(title: str, content: str | None) -> bytes:
    """把文书标题与正文渲染成 docx 字节流。

    ``content`` 为 HTML 时按结构解析，为纯文本时按行拆段。
    """
    doc = _setup_document()

    blocks: list[_Block] = []
    if content and content.strip():
        if _looks_like_html(content):
            parser = _HtmlBlockParser()
            parser.feed(content)
            parser.close()
            blocks = parser.blocks
        else:
            for line in content.splitlines():
                text = line.strip()
                if text:
                    blocks.append(_Block(kind="p", runs=[_Run(text=text)]))

    # 标题：若正文首块已经就是标题（模板常把标题写进正文），不重复输出
    title_text = (title or "").strip()
    first_text = ""
    if blocks:
        first_text = "".join(r.text for r in blocks[0].runs).strip()
    if title_text and first_text != title_text:
        heading = doc.add_paragraph()
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        heading.paragraph_format.space_after = Pt(18)
        heading.paragraph_format.line_spacing = 1.5
        _style_run(heading.add_run(title_text), size=TITLE_SIZE, bold=True)

    for block in blocks:
        if block.kind == "image":
            if block.image:
                _add_image(doc, block.image)
            continue
        if block.kind == "table":
            _add_table(doc, block.rows)
            continue

        paragraph = doc.add_paragraph()
        fmt = paragraph.paragraph_format
        if block.kind in _HEADING_SIZES:
            fmt.space_before = Pt(12)
            fmt.space_after = Pt(6)
            if block.align == "center":
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in block.runs:
                _style_run(
                    paragraph.add_run(run.text),
                    size=_HEADING_SIZES[block.kind],
                    bold=True,
                )
            continue

        if block.kind == "li":
            fmt.left_indent = Pt(24)
            _add_runs(paragraph, block)
        elif block.kind == "blockquote":
            fmt.left_indent = Pt(24)
            fmt.right_indent = Pt(24)
            _add_runs(paragraph, block)
        else:
            # 正文首行缩进 2 字符（小四 12pt → 24pt）
            fmt.first_line_indent = Pt(24)
            _add_runs(paragraph, block)

        if block.align == "center":
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif block.align == "right":
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
