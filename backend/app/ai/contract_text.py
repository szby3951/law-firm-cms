"""合同文本抽取与章节切分（任务拆解 9.5.1）。

一份 30 页的合同直接塞进提示词有两个问题：超出上下文窗口，以及让模型把注意力
摊薄到无关条款上。所以先做三件事：

1. **抽文本**：``.docx`` / ``.pdf`` / ``.txt``，把段落与表格都读出来；
2. **切条款**：按「第X条」「一、」「1.」这类标题切成 clause，条号贯穿全文，
   跨批次审查时模型给出的「第 12 条」始终指同一处；
3. **定位要素**：用关键词把「主体/金额/期限/违约/解除/管辖」等维度各自映射到
   具体条款上，缺失的维度直接列出来——「有没有管辖条款」这种判断不需要模型，
   规则命中率比模型更稳，也更适合事后解释。

切分是**按标题**而不是按固定字数：合同条款被腰斩后，「第 3 条约定……「前述款项」
到底指什么」这类问题就再也查不清了。只有确实找不到任何标题的文本（扫描件或
纯段落粘贴）才退化为按段落分组。

``.doc``（97-2003 二进制格式）不支持，遇到时提示另存为 ``.docx``——硬解析出错
的合同文本比不解析更危险。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "ELEMENT_DIMENSIONS",
    "REQUIRED_DIMENSIONS",
    "SUPPORTED_SUFFIXES",
    "Clause",
    "ContractDigest",
    "ContractTextError",
    "digest_contract",
    "extract_text",
    "normalize_text",
    "render_clause",
    "split_batches",
    "split_clauses",
]

# 支持直接读文件的格式；``.doc`` 明确不支持
SUPPORTED_SUFFIXES = (".docx", ".pdf", ".txt", ".md")

# 关键词维度表：命中后按命中次数排序，取前几个条款作为「相关条款」
ELEMENT_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "主体信息": (
        "甲方", "乙方", "委托人", "受托人", "身份证", "统一社会信用代码",
        "住所", "法定代表人", "联系人",
    ),
    "标的与范围": (
        "委托事项", "服务内容", "代理事项", "工作范围", "标的", "委托代理",
        "代理权限", "法律服务",
    ),
    "金额与费用": (
        "金额", "代理费", "律师费", "报酬", "价款", "费用", "支付", "元",
        "发票", "账户",
    ),
    "期限与生效": (
        "生效", "期限", "有效期", "起至", "届满", "履行期限", "签署", "终止日期",
    ),
    "违约责任": ("违约", "赔偿责任", "逾期", "滞纳金", "罚则"),
    "解除与终止": ("解除", "终止", "撤销", "退费", "结案"),
    "争议解决": ("争议解决", "管辖", "仲裁", "诉讼", "受诉法院"),
    "保密": ("保密", "商业秘密", "个人隐私", "信息保护"),
    "知识产权": ("知识产权", "著作权", "成果归属", "专利", "商标"),
    "通知送达": ("送达", "通知", "电子邮件", "通讯地址"),
}

# 一份合同「应当有」的维度，缺失即为风险（保密/知识产权等按合同性质可选）
REQUIRED_DIMENSIONS = (
    "主体信息",
    "标的与范围",
    "金额与费用",
    "期限与生效",
    "违约责任",
    "争议解决",
)

_CN_NUM = "〇零一二三四五六七八九十百千两"
_MAX_DIM_CLAUSES = 3
_MAX_PLACEHOLDER_SAMPLES = 12


class ContractTextError(RuntimeError):
    """合同文本抽取/切分失败，message 直接面向用户展示。"""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Clause:
    """一个条款（或退化模式下的一个段落组）。"""

    no: int
    title: str
    body: str
    section: str | None = None
    """所属章节（第X章），仅用于给模型提供上下文。"""

    @property
    def chars(self) -> int:
        return len(self.title) + len(self.body)

    def excerpt(self, limit: int = 40) -> str:
        text = " ".join((self.body or self.title).split())
        return text if len(text) <= limit else f"{text[:limit]}…"


@dataclass(slots=True)
class ContractDigest:
    """合同文本的结构化摘要，供提示词拼装与规则预检使用。"""

    text: str
    source: str
    char_count: int
    clauses: list[Clause]
    elements: dict[str, list[int]] = field(default_factory=dict)
    """维度 → 命中条款号（按相关度倒序，最多 3 个）。"""

    missing: list[str] = field(default_factory=list)
    """未命中任何条款的必备维度。"""

    placeholder_count: int = 0
    placeholders: list[dict] = field(default_factory=list)
    """未填写空白：[{clause_no, sample}]。"""

    truncated: bool = False
    """超长合同是否被裁掉了尾部条款。"""

    @property
    def clause_count(self) -> int:
        return len(self.clauses)

    def locate(self, quote: str) -> tuple[int | None, bool]:
        """在合同里定位一段原文，返回 ``(条款号, 是否精确命中)``。

        模型给的「原文定位」经常带着书名号、引号、省略号，也可能把两句话拼成
        一句。这里先做规范化精确匹配，再退化为前缀匹配——两者都不中时仍然保留
        该风险（模型可能只是没摘准），但会标记 ``located=False``，前端提示人工
        核对，绝不把编造的引文当成合同原文展示。
        """
        target = _normalize_for_match(quote)
        if len(target) < 4:
            return None, False

        for clause in self.clauses:
            if target in _normalize_for_match(clause.body) or target in _normalize_for_match(
                clause.title
            ):
                return clause.no, True

        # 模型常把引文截到一半或加了省略号：用前 10 字再试一次
        head = target[:10]
        if len(head) >= 6:
            for clause in self.clauses:
                if head in _normalize_for_match(f"{clause.title}\n{clause.body}"):
                    return clause.no, False
        return None, False


# ---------------------------------------------------------------------------
# 文本抽取
# ---------------------------------------------------------------------------


def normalize_text(raw: str) -> str:
    """统一换行、全角空格，并把连续空行压成一个（模型对空行不敏感，省 token）。"""
    text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ")
    lines: list[str] = []
    blanks = 0
    for line in text.split("\n"):
        stripped = line.rstrip()
        if not stripped.strip():
            blanks += 1
            if blanks > 1:
                continue
        else:
            blanks = 0
        lines.append(stripped)
    return "\n".join(lines).strip()


def extract_text(path: Path) -> tuple[str, str]:
    """从合同文件里抽文本，返回 ``(正文, 来源标识)``。

    :raises ContractTextError: 格式不支持、文件损坏、扫描件（无可提取文字）
    """
    if not path.is_file():
        raise ContractTextError("合同文件不存在或已被移除，请重新上传")

    suffix = path.suffix.lower()
    if suffix == ".docx":
        text, source = _docx_text(path), "docx"
    elif suffix == ".pdf":
        text, source = _pdf_text(path), "pdf"
    elif suffix in (".txt", ".md"):
        text, source = _plain_text(path), suffix.lstrip(".")
    elif suffix == ".doc":
        raise ContractTextError(
            "暂不支持 .doc 旧格式，请另存为 .docx 后重新上传，或直接粘贴合同正文"
        )
    else:
        raise ContractTextError(
            f"不支持的文件格式 {suffix or '（未知）'}，"
            f"可审查的格式：{'、'.join(SUPPORTED_SUFFIXES)}"
        )

    text = normalize_text(text)
    if len(text) < 50:
        hint = "，可能是扫描件或图片版 PDF" if source == "pdf" else ""
        raise ContractTextError(
            f"未能从文件中提取到有效文字（{len(text)} 字）{hint}。"
            "请上传可复制文字的版本，或直接粘贴合同正文"
        )
    return text, source


def _docx_text(path: Path) -> str:
    """读 docx 段落 + 表格。合同里的当事人信息、金额常在表格里，不能只看段落。"""
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - 依赖缺失时给出可执行提示
        raise ContractTextError("服务端缺少 python-docx，无法解析 Word 文件") from exc

    try:
        document = docx.Document(str(path))
    except Exception as exc:  # 加密/损坏文件的异常类型不固定
        raise ContractTextError(
            "Word 文件无法打开（可能已加密或损坏），请另存后重新上传"
        ) from exc

    blocks: list[str] = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))
    return "\n".join(blocks)


def _pdf_text(path: Path) -> str:
    """读 PDF 文字层。扫描件没有文字层，交给上层提示用户。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ContractTextError("服务端缺少 pypdf，无法解析 PDF，请上传 Word 版本") from exc

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ContractTextError("PDF 已加密，请提供未加密的版本") from exc
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except ContractTextError:
        raise
    except Exception as exc:
        raise ContractTextError("PDF 解析失败，请转换为 Word 或直接粘贴正文") from exc
    return "\n".join(page for page in pages if page)


def _plain_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ContractTextError("文本文件编码无法识别，请另存为 UTF-8 后重试")


# ---------------------------------------------------------------------------
# 切分
# ---------------------------------------------------------------------------

_ARTICLE_RE = re.compile(rf"^第[{_CN_NUM}\d]+条[ \t]*(?P<title>[^\n]*)$")
_CHAPTER_RE = re.compile(rf"^第[{_CN_NUM}\d]+章[ \t]*(?P<title>[^\n]*)$")
_CN_HEADING_RE = re.compile(rf"^[{_CN_NUM}]{{1,3}}、[ \t]*(?P<title>[^\n]*)$")
_NUM_HEADING_RE = re.compile(r"^\d{1,2}[.、．][ \t]*(?P<title>[^\n]*)$")

# 「第五百八十五条之规定」「第九条、第十条」这类是正文里的引用，不是条款标题
_PROSE_AFTER = ("之", "、", "，", ",", "。", "；", ";", "规定", "所", "的", "第", "至", "起")

_PLACEHOLDER_RE = re.compile(r"【[^】]{0,12}】|_{3,}|[XxＸ×]{2,}|＿{2,}")


def _article_heading(line: str) -> str | None:
    match = _ARTICLE_RE.match(line)
    if not match:
        return None
    title = match.group("title").strip()
    # 无标题时只接受「第十条」这种短行，避免把换行后的法条引用当成条款
    if not title:
        return "" if len(line) <= 12 else None
    if title.startswith(_PROSE_AFTER):
        return None
    return title


def split_clauses(text: str) -> list[Clause]:
    """把合同切成条款。优先按「第X条」，其次「一、」「1.」，都没有则按段落。"""
    lines = text.split("\n")
    marks = _find_marks(lines)

    articles = [m for m in marks if m[0] == "条"]
    if len(articles) >= 2:
        return _build_clauses(lines, articles, marks)

    plain = [m for m in marks if m[0] in ("一", "数字")]
    if len(plain) >= 2:
        # 「一、」比「1.」更接近条款层级，两种都有时取前者
        kind = "一" if sum(1 for m in plain if m[0] == "一") >= 2 else "数字"
        return _build_clauses(lines, [m for m in plain if m[0] == kind], marks)

    return _paragraph_clauses(text)


def _find_marks(lines: list[str]) -> list[tuple[str, int, str]]:
    """扫描全文，返回 ``[(类型, 行号, 标题)]``。"""
    marks: list[tuple[str, int, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 120:
            continue
        chapter = _CHAPTER_RE.match(stripped)
        if chapter and len(stripped) <= 40:
            marks.append(("章", index, chapter.group("title").strip()))
            continue
        title = _article_heading(stripped)
        if title is not None:
            marks.append(("条", index, title))
            continue
        cn_heading = _CN_HEADING_RE.match(stripped)
        if cn_heading and len(stripped) <= 60:
            marks.append(("一", index, cn_heading.group("title").strip()))
            continue
        num_heading = _NUM_HEADING_RE.match(stripped)
        if num_heading and len(stripped) <= 60:
            marks.append(("数字", index, num_heading.group("title").strip()))
    return marks


def _build_clauses(
    lines: list[str],
    marks: list[tuple[str, int, str]],
    all_marks: list[tuple[str, int, str]],
) -> list[Clause]:
    """按给定标题位置组装条款，章节标题只用于标注 ``section``。

    第一个标题之前的文字（合同名称、甲乙方、鉴于条款）单独成为「合同首部」一条：
    当事人的名称、证件号、住所几乎都写在这里，丢掉它模型就只能看到一堆
    「甲方」「乙方」而不知道是谁。
    """
    chapter_at = {index: title for kind, index, title in all_marks if kind == "章"}
    clauses: list[Clause] = []

    first_line = marks[0][1]
    preamble = "\n".join(ln.strip() for ln in lines[:first_line] if ln.strip())
    if preamble:
        clauses.append(Clause(no=1, title="合同首部（标题、当事人与鉴于条款）", body=preamble))

    section: str | None = None

    for pos, (_, line_no, title) in enumerate(marks):
        # 本条之前最近的章节标题
        for chapter_line in range(line_no, -1, -1):
            if chapter_line in chapter_at:
                chapter_title = chapter_at[chapter_line]
                section = f"第{_chapter_no(lines[chapter_line])}章 {chapter_title}".strip()
                break

        next_line = marks[pos + 1][1] if pos + 1 < len(marks) else len(lines)
        head_line = lines[line_no].strip()
        body_lines = lines[line_no + 1 : next_line]
        body = "\n".join(ln.strip() for ln in body_lines if ln.strip())

        # 标题行本身很长（标题与正文写在同一行）时，把整行并入正文，标题只截一段
        if len(head_line) > 60:
            body = f"{head_line}\n{body}".strip()
            head = f"{head_line[:60]}…"
        else:
            head = head_line

        clauses.append(
            Clause(
                no=len(clauses) + 1,
                title=head or title,
                body=body,
                section=section,
            )
        )
    return clauses


def _chapter_no(line: str) -> str:
    match = re.match(rf"^第([{_CN_NUM}\d]+)章", line.strip())
    return match.group(1) if match else ""


def _paragraph_clauses(text: str, target: int = 800) -> list[Clause]:
    """没有标题可依时的退化路径：按空行分段，再合并到约 ``target`` 字一组。"""
    raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(raw_paragraphs) <= 1:
        # 连空行都没有（常见于 PDF 抽出的整块文本）：按行分组
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        raw_paragraphs = []
        buffer: list[str] = []
        for line in lines:
            buffer.append(line)
            if sum(len(x) for x in buffer) >= 200:
                raw_paragraphs.append("\n".join(buffer))
                buffer = []
        if buffer:
            raw_paragraphs.append("\n".join(buffer))

    groups: list[str] = []
    current = ""
    for paragraph in raw_paragraphs:
        if current and len(current) + len(paragraph) > target:
            groups.append(current)
            current = paragraph
        else:
            current = f"{current}\n{paragraph}".strip() if current else paragraph
    if current:
        groups.append(current)

    return [
        Clause(no=index, title=f"第 {index} 段", body=group, section=None)
        for index, group in enumerate(groups, 1)
    ]


# ---------------------------------------------------------------------------
# 摘要
# ---------------------------------------------------------------------------


def digest_contract(
    text: str, *, source: str = "paste", max_chars: int = 60000
) -> ContractDigest:
    """切分 + 要素定位 + 空白项预检，产出提示词与预检共用的结构。"""
    normalized = normalize_text(text)
    if len(normalized) < 50:
        raise ContractTextError("合同正文过短（少于 50 字），无法进行风险审查")

    clauses = split_clauses(normalized)
    truncated = False

    if len(normalized) > max_chars:
        kept: list[Clause] = []
        used = 0
        for clause in clauses:
            length = clause.chars
            if kept and used + length > max_chars:
                break
            kept.append(clause)
            used += length
        if kept:
            clauses = [
                Clause(no=i, title=c.title, body=c.body, section=c.section)
                for i, c in enumerate(kept, 1)
            ]
            truncated = True

    elements, missing = _index_elements(clauses)
    placeholder_count, placeholders = _scan_placeholders(clauses)

    return ContractDigest(
        text="\n".join(render_clause(c) for c in clauses),
        source=source,
        char_count=sum(c.chars for c in clauses),
        clauses=clauses,
        elements=elements,
        missing=missing,
        placeholder_count=placeholder_count,
        placeholders=placeholders,
        truncated=truncated,
    )


def _index_elements(clauses: list[Clause]) -> tuple[dict[str, list[int]], list[str]]:
    """关键词命中统计：维度 → 相关条款号（最多 3 个）。"""
    elements: dict[str, list[int]] = {}
    for dimension, keywords in ELEMENT_DIMENSIONS.items():
        scored: list[tuple[int, int]] = []
        for clause in clauses:
            haystack = f"{clause.title}\n{clause.body}"
            score = sum(haystack.count(word) for word in keywords)
            if score:
                scored.append((score, clause.no))
        if scored:
            scored.sort(key=lambda item: (-item[0], item[1]))
            elements[dimension] = [no for _, no in scored[:_MAX_DIM_CLAUSES]]

    missing = [name for name in REQUIRED_DIMENSIONS if name not in elements]
    return elements, missing


def _scan_placeholders(clauses: list[Clause]) -> tuple[int, list[dict]]:
    """统计「【　】」「XX」「____」这类未填写空白，模板合同几乎必有。"""
    count = 0
    samples: list[dict] = []
    for clause in clauses:
        for match in _PLACEHOLDER_RE.finditer(clause.body):
            count += 1
            if len(samples) < _MAX_PLACEHOLDER_SAMPLES:
                start = max(0, match.start() - 8)
                end = min(len(clause.body), match.end() + 8)
                samples.append(
                    {
                        "clause_no": clause.no,
                        "sample": " ".join(clause.body[start:end].split()),
                    }
                )
    return count, samples


# ---------------------------------------------------------------------------
# 提示词渲染与分批
# ---------------------------------------------------------------------------


def _normalize_for_match(text: str) -> str:
    """比对用规范化：去掉空白与常见标点，避免「，」与「,」导致匹配失败。"""
    return re.sub(r"[\s，,。；;：:、\u3000\"'“”‘’《》()（）\[\]【】…\.\-—_]+", "", text or "")


def render_clause(clause: Clause, *, max_chars: int | None = None) -> str:
    """把一个条款渲染成提示词里的段落，条号与章节都带上。"""
    head = f"【条款 {clause.no}】{clause.title}".rstrip()
    if clause.section:
        head += f"（{clause.section}）"
    body = clause.body.strip()
    if max_chars is not None and len(body) > max_chars:
        body = f"{body[:max_chars]}\n…（该条过长，以下省略）"
    return f"{head}\n{body}" if body else head


def split_batches(
    clauses: list[Clause], *, max_chars: int, max_batches: int
) -> tuple[list[list[Clause]], bool]:
    """把条款按体积打包成若干批，返回 ``(批次, 是否因超限被截断)``。

    单条超过 ``max_chars`` 的（长附件条款）会在批内截断，另存一份裁剪后的副本，
    保证提示词不会一条就撑爆。
    """
    batches: list[list[Clause]] = []
    current: list[Clause] = []
    size = 0

    for clause in clauses:
        rendered = len(render_clause(clause))
        if rendered > max_chars:
            body_limit = max(200, max_chars - len(clause.title) - 40)
            clause = Clause(
                no=clause.no,
                title=clause.title,
                body=clause.body[:body_limit],
                section=clause.section,
            )
            rendered = len(render_clause(clause))

        if current and size + rendered > max_chars:
            batches.append(current)
            current, size = [], 0
            if len(batches) >= max_batches:
                return batches, True

        current.append(clause)
        size += rendered

    if current:
        batches.append(current)
    return batches[:max_batches], len(batches) > max_batches
