"""敏感信息脱敏（任务拆解 9.3.7 / 9.9.2）。

**只脱敏送往模型与日志的文本，不改数据库里的原文。** 理由：

- 合规要求是「送入 LLM 前打码、日志无明文」（9.9.2），业务数据本身属于律所
  内部资料，仍需完整保留，否则律师回看历史会话会看到残缺的事实描述；
- 但日志里绝不能出现身份证、手机号——排障的人未必有权看案卷。

实现方式是正则替换，覆盖中国法务实务里最常出现的五类字段：

============  ==============================  ==========================
字段           示例                             脱敏后
============  ==============================  ==========================
身份证         110101199003071234              110101********1234
手机号         13800138000                     138****8000
银行卡         6222021234567890123             6222***********0123
邮箱           zhangsan@example.com            z***@example.com
姓名           当事人：张三                     当事人：张*
============  ==============================  ==========================

**替换顺序：先长后短。** 18 位身份证里含 11 位连续数字，若先跑手机号规则，
会把身份证中段误判成手机号，留下 ``110101138****8000234`` 这种既泄露又不合法
的结果。因此按「身份证 → 银行卡 → 手机号 → 邮箱 → 姓名」依次处理。

姓名的识别只能靠「称谓 + 汉字」的上下文，且**只取 2 个字**（复姓取 3 个字）：
取 3~4 个字会把「当事人张三欠钱不还」里的"欠钱"一起吞掉，把整句话打残。
代价是「王小明」只会被打成「王*明」——单独一个"明"字不具可识别性，可接受。
纯姓名（"张三欠钱不还"）无上下文可依，正则无法在不误伤普通词语的前提下识别，
这是本方案的已知边界；真正上线应叠加 NER 模型。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 身份证：18 位，末位可能是 X。前后不能紧邻字母数字，避免误伤更长的编号
_ID_CARD = re.compile(r"(?<![0-9A-Za-z])(\d{6})\d{8}(\d{3}[\dXx])(?![0-9A-Za-z])")
# 银行卡：16~19 位连续数字
_BANK_CARD = re.compile(r"(?<!\d)(\d{4})\d{8,11}(\d{4})(?!\d)")
# 手机号：1 开头 11 位，且不能是更长数字串的一部分
_PHONE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
# 邮箱：只保留首字母与域名。**必须限定 ASCII**——Python 的 \w 默认匹配中文，
# 用 \w 会把"邮箱zhangsan@..."里的"箱"当成首字母，打码后变成"邮***@..."。
_EMAIL = re.compile(
    r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)"
)

# 复姓表：命中时连姓带名取 3 个字（欧阳修 → 欧**）
_COMPOUND = (
    "欧阳", "司马", "上官", "诸葛", "东方", "皇甫", "尉迟", "公孙", "慕容",
    "长孙", "宇文", "司徒", "司空", "令狐", "夏侯", "端木", "南宫", "西门",
    "独孤", "轩辕", "赫连", "澹台",
)
_COMPOUND_SET = frozenset(_COMPOUND)

# 常见单姓（覆盖绝大多数中国人）。这是姓名识别的**第二道闸门**：
# 只有「称谓 + 姓氏 + 一个字」才算人名。少了这道校验，"当事人约定违约金"
# 里的"约定"会被当成名字打成"约*"，把正常提问改坏——这是实测踩到的坑。
_SURNAMES = frozenset(
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田"
    "董袁潘蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹"
    "孟熊秦邱江尹薛段雷侯龙史陶黎贺顾毛郝龚邵万钱严武戴莫孔汤温康施尤辛洪"
    "翟殷颜倪章鲁岳齐涂樊凌毕单季裴霍苗谷盛曲翁冉骆蓝路游靳管柴蒙鲍喻祁蒲"
    "房滕屈饶解牟艾尤阳时穆农司卓古吉缪简车项连芦麦褚娄窦戚岑景党宫费卜冷"
    "晏席卫米柏宗瞿桂佟臧闵苟邬边卞姬师和仇栾隋商刁沙荣巫寇桑郎甄丛仲虞敖"
    "巩明佘池查麻苑迟邝封谈匡鞠惠荆乐冀郁胥南班储原栗燕楚鄢劳谌奚皮粟冼蔺"
    "楼闻厉伊仝郜阚权帅屠豆朴盖练廉禹井祖漆巴丰支卿国狄平计索宣晋相初门云"
)

# 姓名：仅在称谓后出现时识别。普通姓名为 2 个字，复姓为 3 个字
_NAME = re.compile(
    r"(姓名|当事人|委托人|代理人|被告|原告|申请人|被申请人|联系人|客户)"
    r"([：:\s]{0,3})"
    rf"((?:{'|'.join(_COMPOUND)})[\u4e00-\u9fa5]|[\u4e00-\u9fa5]{{2}})"
)

# 称谓后面跟着的常是说明性词语而非人名
_NAME_STOPWORDS = {
    "本人",
    "双方",
    "对方",
    "各方",
    "公司",
    "单位",
    "代理",
    "委托",
    "联系",
    "信息",
    "姓名",
    "电话",
    "地址",
    "签字",
    "盖章",
    "不详",
    "未知",
}


@dataclass(slots=True)
class MaskResult:
    """脱敏结果：处理后的文本 + 各类命中次数（用于审计与前端提示）。"""

    text: str
    hits: dict[str, int] = field(default_factory=dict)

    @property
    def masked(self) -> bool:
        return bool(self.hits)

    @property
    def summary(self) -> str:
        labels = {
            "id_card": "身份证",
            "bank_card": "银行卡",
            "phone": "手机号",
            "email": "邮箱",
            "name": "姓名",
        }
        return "、".join(
            f"{labels.get(key, key)}×{count}" for key, count in self.hits.items()
        )

    def to_dict(self) -> dict[str, object]:
        """给 SSE ``meta`` 事件用的简要信息（不含原文）。"""
        return {"masked": self.masked, "hits": self.hits, "summary": self.summary}


def _mask_id(match: re.Match[str]) -> str:
    return f"{match.group(1)}{'*' * 8}{match.group(2)}"


def _mask_bank(match: re.Match[str]) -> str:
    middle = len(match.group(0)) - 8
    return f"{match.group(1)}{'*' * middle}{match.group(2)}"


def _mask_phone(match: re.Match[str]) -> str:
    return f"{match.group(1)}****{match.group(2)}"


def _mask_email(match: re.Match[str]) -> str:
    return f"{match.group(1)}***@{match.group(2)}"


def _is_person_name(name: str) -> bool:
    """判断「称谓」后面的两个字是不是人名。

    两道闸门：不在停用词里，且首字是常见姓氏（复姓按前两字判断）。
    只靠"称谓 + 两个汉字"会把"当事人约定""原告主张"里的动词当成名字。
    """
    if len(name) < 2 or name in _NAME_STOPWORDS:
        return False
    return name[:2] in _COMPOUND_SET or name[0] in _SURNAMES


def _mask_name(match: re.Match[str]) -> str:
    title, sep, name = match.group(1), match.group(2), match.group(3)
    if not _is_person_name(name):
        return match.group(0)
    return f"{title}{sep}{name[0]}{'*' * (len(name) - 1)}"


def mask_sensitive(text: str) -> MaskResult:
    """对一段文本做脱敏，返回 :class:`MaskResult`。"""
    if not text:
        return MaskResult(text="", hits={})

    result = text
    hits: dict[str, int] = {}

    result, n = _ID_CARD.subn(_mask_id, result)
    if n:
        hits["id_card"] = n

    result, n = _BANK_CARD.subn(_mask_bank, result)
    if n:
        hits["bank_card"] = n

    result, n = _PHONE.subn(_mask_phone, result)
    if n:
        hits["phone"] = n

    result, n = _EMAIL.subn(_mask_email, result)
    if n:
        hits["email"] = n

    # 姓名的计数不能直接用 subn 的 n：停用词（"当事人本人"）与非姓氏词
    # （"当事人约定"）同样会匹配到正则，但不会被替换
    real_names = [m for m in _NAME.finditer(result) if _is_person_name(m.group(3))]
    result = _NAME.sub(_mask_name, result)
    if real_names:
        hits["name"] = len(real_names)

    return MaskResult(text=result, hits=hits)


def mask_text(text: str) -> str:
    """只取脱敏后的文本，供不需要统计的调用点使用。"""
    return mask_sensitive(text).text
