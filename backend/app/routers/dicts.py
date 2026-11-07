"""业务端字典读取接口。

与 ``/api/admin/dicts`` 的区别：这里**只读、只返回候选列表**，任何登录用户
（律师 / 管理员 / 客户）都能取，供立案、合同、文书等表单填充下拉。
写操作仍然只在管理员侧。
"""

from fastapi import APIRouter

from app.dependencies import CurrentUser
from app.schemas.setting import DictOptionsOut
from app.services import dict_cache

router = APIRouter()


@router.get("", response_model=DictOptionsOut, summary="字典候选（全部登录用户可读）")
async def list_options(user: CurrentUser) -> DictOptionsOut:
    """一次性返回全部分类的候选，前端启动时拉一次即可。"""
    return DictOptionsOut(dicts=dict_cache.snapshot())
