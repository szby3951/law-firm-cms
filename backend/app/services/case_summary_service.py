"""案件摘要的数据聚合（任务拆解 9.6.1）。

摘要的质量取决于「送进去的材料是否完整、是否有层次」，而不是提示词写得多花。
这个模块只做一件事：把一个案件的分散数据整理成 :class:`CaseBundle`，供
:mod:`app.services.ai_service` 拼提示词。

**材料不是堆得越多越好。** 一案可能有几十份文书、合同与附件，全塞进去会稀释
真正重要的内容，还会超出上下文。这里按「对摘要的贡献」排序后按预算裁剪：

1. 案情描述（律师自己写的，信息密度最高）
2. 案件文书（起诉状/答辩状/代理词，含主张与事实）
3. 案件附件（证据材料的文本层）
4. 合同审查报告（9.5 的结论，比合同全文更浓缩）
5. 合同全文（长且与审查报告重复，预算充足才纳入）

被裁掉的材料不会静默消失：标题与原因写进 ``skipped``，提示词里单列
「未纳入本次摘要的材料」，让模型在「材料缺口」一节里如实说明，而不是假装
已经看全了卷宗。

**不脱敏。** 摘要是律师内部工作底稿，姓名、金额、案号、身份证号必须与卷宗
一一对应；权限收在「仅承办律师/管理员可触发」（架构文档 6.5）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import contract_prompts, contract_text, doc_html
from app.config import settings
from app.models.attachment import Attachment
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.client import ClientProfile
from app.models.contract import Contract
from app.models.document import Document
from app.models.schedule import Schedule
from app.models.user import User
from app.schemas.document import DOC_TYPE_LABELS
from app.services import case_service

logger = logging.getLogger(__name__)

__all__ = [
    "CASE_TYPE_LABELS",
    "EVENT_LABELS",
    "MATERIAL_LABELS",
    "SCHEDULE_LABELS",
    "STATUS_LABELS",
    "CaseBundle",
    "CaseMaterial",
    "collect_case_bundle",
]

STATUS_LABELS = {
    "consulting": "咨询中",
    "filed": "已立案",
    "handling": "办理中",
    "pending_close": "待结案",
    "closed": "已结案",
    "withdrawn": "已退案",
}

CASE_TYPE_LABELS = {"litigation": "诉讼", "non_litigation": "非诉"}

EVENT_LABELS = {
    "filing": "立案",
    "accept": "受理",
    "hearing": "开庭",
    "evidence": "举证",
    "judgment": "裁判",
    "other": "其他",
}

SCHEDULE_LABELS = {
    "hearing": "开庭",
    "deadline": "期限",
    "visit": "回访",
    "meeting": "会议",
}

MATERIAL_LABELS = {
    "description": "案情描述",
    "document": "案件文书",
    "attachment": "案件材料",
    "review": "合同审查报告",
    "contract": "合同",
}

# 可抽取文本的附件格式；图片/压缩包只记文件名，不硬读
_TEXT_SUFFIXES = {".docx", ".pdf", ".txt", ".md"}


@dataclass(slots=True)
class CaseMaterial:
    """一份可送入提示词的材料。``chars`` 是原文全长，不是节选后长度。"""

    kind: str
    title: str
    text: str
    chars: int
    truncated: bool = False
    note: str | None = None

    @property
    def kind_label(self) -> str:
        return MATERIAL_LABELS.get(self.kind, "材料")

    @property
    def included_chars(self) -> int:
        return len(self.text)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "kind_label": self.kind_label,
            "title": self.title,
            "text": self.text,
            "chars": self.chars,
            "truncated": self.truncated,
            "note": self.note,
        }

    def to_out(self) -> dict[str, Any]:
        """给前端的材料清单：只报元信息，不回传正文（可能几万字）。"""
        return {
            "kind": self.kind,
            "kind_label": self.kind_label,
            "title": self.title,
            "chars": self.chars,
            "included_chars": self.included_chars,
            "truncated": self.truncated,
            "note": self.note,
        }


@dataclass(slots=True)
class CaseBundle:
    """一个案件的摘要输入。字段都是值类型，可安全跨请求边界传递。"""

    case_id: int
    case_no: str
    case_title: str
    meta: dict[str, str]
    timeline: list[str]
    schedules: list[str]
    materials: list[CaseMaterial] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    total_chars: int = 0
    truncated: bool = False

    @property
    def material_count(self) -> int:
        return len(self.materials)


def _fmt_time(value: datetime | None, *, with_time: bool = False) -> str:
    if value is None:
        return "未登记"
    return value.strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")


def _fmt_amount(value: Any) -> str:
    if value is None:
        return "未填写"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "未填写"
    return f"¥{amount:,.2f}" if amount else "未填写"


def _build_meta(
    case: Case,
    client: ClientProfile | None,
    lawyers: list[tuple[Any, str | None]],
) -> dict[str, str]:
    """案件档案 → 提示词里按顺序展示的键值对。"""
    lead = [name for rel, name in lawyers if rel.duty == "lead" and name]
    assist = [name for rel, name in lawyers if rel.duty != "lead" and name]
    lawyer_text = ""
    if lead:
        lawyer_text += f"主办 {('、'.join(lead))}"
    if assist:
        lawyer_text += ("；" if lawyer_text else "") + f"协办 {('、'.join(assist))}"
    if not lawyer_text:
        lawyer_text = "未分配"

    meta = {
        "案号": case.case_no,
        "案件名称": case.title,
        "案由": case.case_cause or "未填写",
        "案件类型": CASE_TYPE_LABELS.get(case.case_type, case.case_type),
        "当前阶段": STATUS_LABELS.get(case.status, case.status),
        "标的额": _fmt_amount(case.amount),
        "受理法院/机构": case.court or "未填写",
        "对方当事人": case.opposing_party or "未填写",
        "委托客户": client.name if client else f"客户 #{case.client_id}",
        "承办律师": lawyer_text,
        "立案时间": _fmt_time(case.created_at, with_time=True),
    }
    if case.closed_at:
        meta["结案时间"] = _fmt_time(case.closed_at, with_time=True)
    return meta


def _format_event(event: CaseEvent) -> str:
    label = EVENT_LABELS.get(event.event_type, event.event_type)
    desc = (event.description or "").strip() or "无说明"
    return f"{_fmt_time(event.event_date)}｜{label}｜{desc}"


def _format_schedule(schedule: Schedule, now: datetime) -> str:
    label = SCHEDULE_LABELS.get(schedule.schedule_type, schedule.schedule_type)
    text = f"{_fmt_time(schedule.event_date, with_time=True)}｜{label}｜{schedule.title}"
    if schedule.remark:
        text += f"（{schedule.remark}）"
    if schedule.event_date < now:
        text += "【已逾期未完成】"
    return text


def _resolve_upload(rel_path: str | None) -> Path | None:
    """把数据库里的相对路径解析到 upload_dir 内，越界或不存在返回 None。"""
    if not rel_path:
        return None
    root = settings.upload_dir.resolve()
    try:
        path = (root / rel_path).resolve()
        path.relative_to(root)
    except (OSError, ValueError):
        logger.warning("案件材料路径异常，已跳过：%s", rel_path)
        return None
    return path if path.is_file() else None


def _file_text(rel_path: str | None) -> tuple[str | None, str | None]:
    """读取文书/合同/附件文本。返回 ``(正文, 失败原因)``，两者必有其一为 None。"""
    path = _resolve_upload(rel_path)
    if path is None:
        return None, "文件不存在或路径异常"
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        return None, f"{path.suffix or '该格式'} 暂不支持文本提取"
    try:
        text, _source = contract_text.extract_text(path)
    except contract_text.ContractTextError as exc:
        reason = str(exc)
        return None, reason if len(reason) <= 60 else f"{reason[:58]}…"
    except Exception:  # pragma: no cover - 解析库异常类型不固定
        logger.exception("案件材料解析失败：%s", path)
        return None, "文件解析失败"
    return text, None


async def _load_documents(db: AsyncSession, case_id: int) -> list[Document]:
    rows = (
        (
            await db.execute(
                select(Document)
                .where(Document.case_id == case_id)
                .order_by(Document.updated_at.desc(), Document.id.desc())
                .limit(settings.case_summary_max_materials)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _load_contracts(db: AsyncSession, case_id: int) -> list[Contract]:
    rows = (
        (
            await db.execute(
                select(Contract)
                .where(Contract.case_id == case_id)
                .order_by(Contract.created_at.desc(), Contract.id.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _load_attachments(db: AsyncSession, case_id: int) -> list[Attachment]:
    rows = (
        (
            await db.execute(
                select(Attachment)
                .where(Attachment.biz_type == "case", Attachment.biz_id == case_id)
                .order_by(Attachment.created_at.asc(), Attachment.id.asc())
                .limit(settings.case_summary_max_materials)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _load_schedules(db: AsyncSession, case_id: int) -> list[Schedule]:
    """只取未完成日程，按时间正序：最近的期限排在最前，逾期项也在其中。"""
    rows = (
        (
            await db.execute(
                select(Schedule)
                .where(Schedule.case_id == case_id, Schedule.status == "pending")
                .order_by(Schedule.event_date.asc(), Schedule.id.asc())
                .limit(8)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def _candidates(
    case: Case,
    documents: list[Document],
    contracts: list[Contract],
    attachments: list[Attachment],
) -> tuple[list[CaseMaterial], list[str]]:
    """按优先级生成候选材料，同时收集「读不了」的材料说明。"""
    candidates: list[CaseMaterial] = []
    skipped: list[str] = []

    description = (case.description or "").strip()
    if description:
        candidates.append(
            CaseMaterial(
                kind="description",
                title="案情描述",
                text=description,
                chars=len(description),
            )
        )

    for document in documents:
        text = doc_html.to_text(document.content)
        if not text.strip():
            skipped.append(f"《{document.title}》（文书正文为空）")
            continue
        type_label = DOC_TYPE_LABELS.get(document.doc_type or "", "")
        # 标题常已含类型（「武庸民事起诉状」+「起诉状」），不重复拼接
        title = (
            f"{document.title}（{type_label}）"
            if type_label and type_label not in document.title
            else document.title
        )
        candidates.append(
            CaseMaterial(
                kind="document",
                title=title,
                text=text,
                chars=len(text),
            )
        )

    for attachment in attachments:
        text, error = _file_text(attachment.file_path)
        if error or not text:
            skipped.append(f"《{attachment.file_name}》（{error or '未提取到文字'}）")
            continue
        candidates.append(
            CaseMaterial(
                kind="attachment",
                title=attachment.file_name,
                text=text,
                chars=len(text),
            )
        )

    for contract in contracts:
        report = contract.ai_review_report
        if isinstance(report, dict) and report.get("risks") is not None:
            text = contract_prompts.render_text(report)
            candidates.append(
                CaseMaterial(
                    kind="review",
                    title=f"{contract.name} 风险审查",
                    text=text,
                    chars=len(text),
                )
            )

    for contract in contracts:
        text, error = _file_text(contract.file_url)
        if error or not text:
            skipped.append(f"《{contract.name}》（{error or '未提取到文字'}）")
            continue
        candidates.append(
            CaseMaterial(
                kind="contract",
                title=contract.name,
                text=text,
                chars=len(text),
            )
        )

    return candidates, skipped


def _apply_budget(
    candidates: list[CaseMaterial],
    skipped: list[str],
) -> tuple[list[CaseMaterial], list[str], int, bool]:
    """按单份上限、总字数与份数上限裁剪材料。

    :return: ``(入选材料, 未入选说明, 总字数, 是否发生裁剪)``
    """
    item_chars = max(1000, settings.case_summary_item_chars)
    total_chars = max(item_chars, settings.case_summary_total_chars)
    max_items = max(1, settings.case_summary_max_materials)

    selected: list[CaseMaterial] = []
    total = 0
    cut = False

    for material in candidates:
        if material.chars < 20:
            continue
        if len(selected) >= max_items:
            skipped.append(f"《{material.title}》（材料份数已达上限 {max_items}）")
            cut = True
            continue
        remaining = total_chars - total
        if remaining <= 400:
            skipped.append(f"《{material.title}》（超出本次摘要容量）")
            cut = True
            continue

        limit = min(item_chars, remaining)
        text = material.text[:limit].rstrip()
        truncated = material.chars > limit
        note = f"仅前 {limit:,} 字" if truncated else material.note
        selected.append(
            CaseMaterial(
                kind=material.kind,
                title=material.title,
                text=text,
                chars=material.chars,
                truncated=truncated,
                note=note,
            )
        )
        total += len(text)
        if truncated:
            cut = True

    return selected, skipped, total, cut


async def collect_case_bundle(
    db: AsyncSession,
    user: User,
    case_id: int,
    *,
    include_materials: bool = True,
) -> CaseBundle:
    """聚合案件摘要所需的全部输入（权限错误直接抛 403/404）。

    :param include_materials: 关闭后只读案件档案、时间线与日程，不读任何文件，
        用于「案件材料还没整理好，先出一份框架摘要」。
    """
    # 行级权限复用案件模块：律师只能看本人主办/协办，管理员不限，客户 403
    case = await case_service.get_case_detail(db, case_id, user)
    client = await db.get(ClientProfile, case.client_id)
    lawyers = await case_service.list_case_lawyers(db, case.id)
    events = await case_service.list_case_events(db, case.id)
    schedules = await _load_schedules(db, case.id)

    meta = _build_meta(case, client, lawyers)
    # list_case_events 是倒序（最新在前），提示词要求按时间顺序叙述
    timeline = [_format_event(event) for event in reversed(events)]
    now = datetime.now()
    schedule_lines = [_format_schedule(item, now) for item in schedules]

    documents: list[Document] = []
    contracts: list[Contract] = []
    attachments: list[Attachment] = []
    materials: list[CaseMaterial] = []
    skipped: list[str] = []
    total_chars = 0
    truncated = False

    if include_materials:
        documents = await _load_documents(db, case.id)
        contracts = await _load_contracts(db, case.id)
        attachments = await _load_attachments(db, case.id)
        candidates, skipped = _candidates(case, documents, contracts, attachments)
        materials, skipped, total_chars, truncated = _apply_budget(candidates, skipped)
        meta["案卷概况"] = (
            f"文书 {len(documents)} 份、合同 {len(contracts)} 份、"
            f"附件 {len(attachments)} 个；本次纳入 {len(materials)} 份材料"
        )
    else:
        skipped.append("本次未读取案卷材料（律师选择仅依据案件档案）")
        meta["案卷概况"] = "本次未读取案卷材料"

    counts = {
        "documents": len(documents),
        "contracts": len(contracts),
        "attachments": len(attachments),
        "events": len(events),
        "schedules": len(schedules),
        "materials": len(materials),
        "skipped": len(skipped),
        "chars": total_chars,
    }

    logger.info(
        "案件摘要材料聚合 | case=%s | 文书 %d / 合同 %d / 附件 %d | "
        "纳入 %d 份 %d 字 | 裁剪 %s",
        case.id,
        len(documents),
        len(contracts),
        len(attachments),
        len(materials),
        total_chars,
        truncated,
    )

    return CaseBundle(
        case_id=case.id,
        case_no=case.case_no,
        case_title=case.title,
        meta=meta,
        timeline=timeline,
        schedules=schedule_lines,
        materials=materials,
        skipped=skipped,
        counts=counts,
        total_chars=total_chars,
        truncated=truncated,
    )
