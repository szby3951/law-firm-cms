"""轻量 Markdown → HTML 转换（9.4.4 归档用）。

文书表 ``document.content`` 存的是富文本 HTML：前端 wangEditor 打开它继续编辑，
``docx_export`` 也按 ``<p>``/``<h1>``/``<li>`` 解析排版。而模型输出的是 Markdown
（比 HTML 稳，不会被包进代码块或写出错误的标签闭合）。

所以归档时要做一次转换。这里**不引入 markdown 库**，只实现文书真正会用到的子集：

============  ==========================================
``# ~ ####``  标题 → ``<h1>`` ~ ``<h4>``
``**粗体**``  行内 → ``<strong>``
``- / *``     无序列表 → ``<li>``
``1.``        有序列表 → ``<li>``（保留原编号文本）
``>``         引用 → ``<blockquote>``
空行分段      段落 → ``<p>``
============  ==========================================

刻意不支持表格与图片：法律文书正文极少使用，而错误解析表格反而会打乱排版。
若模型真的输出了表格，会退化成普通段落，内容不丢。
"""

from __future__ import annotations

import re
from html import unescape

from app.ai.doc_prompts import PLACEHOLDER  # noqa: F401  占位符格式在提示词里定义

__all__ = ["looks_like_html", "to_html", "to_text"]

_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
_UL_ITEM = re.compile(r"^\s*[-*+]\s+(.*)$")
_OL_ITEM = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_HR = re.compile(r"^\s*([-*_]\s*){3,}$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)([^*\n]+?)(?<!\*)\*(?!\*)")
_CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*$")

_HTML_HINT = re.compile(r"<(p|div|br|h[1-6]|ul|ol|li|table|strong|blockquote)\b", re.IGNORECASE)

# ---- HTML → 纯文本（案件摘要读取 document.content 时用） ----
_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_LI_OPEN = re.compile(r"<li\b[^>]*>", re.IGNORECASE)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_CELL_END = re.compile(r"</(td|th)\s*>", re.IGNORECASE)
_BLOCK_END = re.compile(
    r"</(p|div|h[1-6]|blockquote|tr|section|article)\s*>", re.IGNORECASE
)
_ANY_TAG = re.compile(r"<[^>]+>")



def looks_like_html(text: str | None) -> bool:
    """判断一段正文是富文本还是 Markdown/纯文本。

    前端编辑器提交上来的已经是 HTML，不能再转一次，否则标签会被当作文本转义。
    """
    return bool(text and _HTML_HINT.search(text))


def _escape(text: str) -> str:
    """转义 HTML 特殊字符。先转义再加标签，避免正文里的 ``<`` 破坏结构。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _inline(text: str) -> str:
    """行内格式：先转义，再套粗体/斜体标签。"""
    escaped = _escape(text.strip())
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC.sub(r"<em>\1</em>", escaped)
    return escaped


def to_html(markdown: str | None, *, allow_html: bool = True) -> str:
    """把模型输出的 Markdown 转成 ``document.content`` 可用的 HTML。

    :param allow_html: 输入本身已是 HTML 时是否原样返回。归档/模板导入传 True
        （前端编辑器提交的就是 HTML，转了会二次转义）；**AI 生成的摘要传 False**，
        因为模型输出不受信任，夹带的 ``<script>`` 会被前端 ``v-html`` 直接执行。

    已是 HTML 的内容原样返回——避免二次转义。
    """
    if not markdown or not markdown.strip():
        return ""
    if allow_html and looks_like_html(markdown):
        return markdown.strip()

    blocks: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        text = " ".join(line.strip() for line in paragraph if line.strip())
        paragraph.clear()
        if text:
            blocks.append(f"<p>{_inline(text)}</p>")

    for raw in markdown.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        stripped = line.strip()

        if _CODE_FENCE.match(stripped):
            flush_paragraph()
            continue
        if not stripped:
            flush_paragraph()
            continue
        if _HR.match(stripped):
            flush_paragraph()
            continue

        heading = _HEADING.match(stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        quote = _QUOTE.match(stripped)
        if quote:
            flush_paragraph()
            blocks.append(f"<blockquote>{_inline(quote.group(1))}</blockquote>")
            continue

        ul = _UL_ITEM.match(stripped)
        if ul:
            flush_paragraph()
            blocks.append(f"<li>{_inline(ul.group(1))}</li>")
            continue

        ol = _OL_ITEM.match(stripped)
        if ol:
            flush_paragraph()
            # 保留原编号：法律文书的"1. 2. 3."是内容的一部分，去掉会改变语义
            blocks.append(f"<li>{ol.group(1)}. {_inline(ol.group(2))}</li>")
            continue

        paragraph.append(stripped)

    flush_paragraph()
    return "".join(blocks)


def to_text(content: str | None) -> str:
    """把富文本正文还原成可读纯文本（案件摘要读取 ``document.content`` 时用）。

    只做"能读"级别的还原：块级标签断行、``<li>`` 还原成 ``- ``、实体反转义、
    连续空行压缩。表格退化为按行排列的单元格文本——摘要提示词不要求保留表格，
    但单元格内容不能丢。
    """
    if not content:
        return ""

    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if looks_like_html(text):
        text = _SCRIPT.sub("", text)
        text = _LI_OPEN.sub("\n- ", text)
        text = _BR.sub("\n", text)
        text = _CELL_END.sub(" | ", text)
        text = _BLOCK_END.sub("\n\n", text)
        text = _ANY_TAG.sub("", text)
        text = unescape(text)

    text = text.replace("\xa0", " ").replace("\u3000", " ")
    lines: list[str] = []
    blanks = 0
    for raw in text.split("\n"):
        line = raw.strip()
        if line.endswith("|"):
            line = line[:-1].rstrip()
        if line:
            blanks = 0
            lines.append(line)
        else:
            blanks += 1
            if blanks == 1:
                lines.append("")
    return "\n".join(lines).strip()

