"""ORM 模型汇总：在此导入可保证 Base.metadata 收集到全部表。"""

from app.models.ai import AiMessage, AiSession
from app.models.attachment import Attachment
from app.models.billing import FeePeriod, FeePlan, Payment
from app.models.case import Case
from app.models.case_event import CaseEvent
from app.models.case_lawyer import CaseLawyer
from app.models.client import ClientProfile
from app.models.contract import Contract
from app.models.dict import DictItem
from app.models.document import DocTemplate, Document
from app.models.follow import FollowRecord
from app.models.kb_document import KbDocument
from app.models.law_article import LawArticle
from app.models.log import OperationLog
from app.models.message import Message
from app.models.notification import Notification
from app.models.payment_order import PaymentOrder
from app.models.schedule import Schedule
from app.models.setting import AIConfig, FirmInfo
from app.models.user import User

__all__ = [
    "AIConfig",
    "AiMessage",
    "AiSession",
    "Attachment",
    "Case",
    "CaseEvent",
    "CaseLawyer",
    "ClientProfile",
    "Contract",
    "DictItem",
    "DocTemplate",
    "Document",
    "FeePeriod",
    "FeePlan",
    "FirmInfo",
    "FollowRecord",
    "KbDocument",
    "LawArticle",
    "Message",
    "Notification",
    "OperationLog",
    "Payment",
    "PaymentOrder",
    "Schedule",
    "User",
]
