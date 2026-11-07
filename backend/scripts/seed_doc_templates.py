"""文书模板种子数据（幂等）。

执行：``python scripts/seed_doc_templates.py``

写入 6 份常用诉讼/非诉文书模板，正文为富文本 HTML 并带 ``{变量}`` 占位符，
供「选择模板 → 自动填充案件字段 → 在线编辑 → 导出 docx」全流程使用。

重复执行安全：按 ``(doc_type, name)`` 判断是否已存在，存在则跳过。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings

TEMPLATES: list[dict[str, str]] = [
    {
        "doc_type": "complaint",
        "name": "民事起诉状",
        "content": (
            "<p>原告：{客户姓名}，证件号 {客户证件号}，住{客户地址}，"
            "联系电话：{客户电话}。</p>"
            "<p>被告：{对方当事人}。</p>"
            "<p>诉讼请求：</p>"
            "<p>一、判令被告向原告支付款项人民币 {标的额} 元；</p>"
            "<p>二、判令被告承担本案全部诉讼费用。</p>"
            "<p>事实与理由：</p>"
            "<p>原告与被告因{案由}发生纠纷。……（请补充交易背景、"
            "履行经过、违约事实及证据线索）。</p>"
            "<p>综上，原告的诉讼请求有事实与法律依据，恳请贵院依法支持。</p>"
            "<p>此致</p>"
            "<p>{受理法院}</p>"
            '<p style="text-align:right">具状人：{客户姓名}</p>'
            '<p style="text-align:right">{今日日期}</p>'
        ),
    },
    {
        "doc_type": "response",
        "name": "民事答辩状",
        "content": (
            "<p>答辩人（被告）：{客户姓名}，证件号 {客户证件号}，"
            "住{客户地址}，联系电话：{客户电话}。</p>"
            "<p>被答辩人（原告）：{对方当事人}。</p>"
            "<p>答辩人因被答辩人诉答辩人{案由}一案（案号：{案号}），"
            "现提出答辩意见如下：</p>"
            "<p>一、被答辩人主张的事实与客观情况不符。……</p>"
            "<p>二、被答辩人的诉讼请求缺乏法律依据。……</p>"
            "<p>三、关于本案证据，答辩人保留质证与补充举证的权利。</p>"
            "<p>综上，请求贵院依法驳回被答辩人的全部诉讼请求。</p>"
            "<p>此致</p>"
            "<p>{受理法院}</p>"
            '<p style="text-align:right">答辩人：{客户姓名}</p>'
            '<p style="text-align:right">{今日日期}</p>'
        ),
    },
    {
        "doc_type": "agency_argument",
        "name": "代理词（一审）",
        "content": (
            "<p>尊敬的审判长、审判员：</p>"
            "<p>{律所名称}接受本案原告{客户姓名}的委托，指派{委托律师}律师"
            "担任其与{对方当事人}{案由}纠纷一案的诉讼代理人。现结合庭审"
            "查明的事实与证据，发表如下代理意见：</p>"
            "<p>一、关于本案事实：原被告之间存在真实、合法的法律关系，"
            "原告已按约履行义务。……</p>"
            "<p>二、关于法律适用：被告的行为已构成违约，应依约承担"
            "人民币 {标的额} 元的给付责任。……</p>"
            "<p>三、关于证据：原告提交的合同、转账凭证、往来函件等证据"
            "形成完整证据链，足以证明其主张。</p>"
            "<p>综上，恳请合议庭依法支持原告的全部诉讼请求。</p>"
            '<p style="text-align:right">代理人：{委托律师}</p>'
            '<p style="text-align:right">{律所名称}</p>'
            '<p style="text-align:right">{今日日期}</p>'
        ),
    },
    {
        "doc_type": "lawyer_letter",
        "name": "律师函（催告履行）",
        "content": (
            "<p>致：{对方当事人}</p>"
            "<p>{律所名称}接受{客户姓名}的委托，指派{委托律师}律师就"
            "贵方与其之间{案由}事宜，郑重致函如下：</p>"
            "<p>一、根据委托人提供的材料，贵方尚欠付人民币 {标的额} 元，"
            "且已逾期多日未予履行。……</p>"
            "<p>二、请贵方于收到本函之日起七日内，与委托人联系并完成"
            "上述款项的支付，或就履行方案作出书面答复。</p>"
            "<p>三、如贵方逾期未予回应，本所将协助委托人依法提起诉讼、"
            "申请财产保全，并追究贵方的违约责任，由此产生的一切法律后果"
            "及费用由贵方承担。</p>"
            "<p>特此函告。</p>"
            '<p style="text-align:right">{律所名称}</p>'
            '<p style="text-align:right">律师：{委托律师}</p>'
            '<p style="text-align:right">{今日日期}</p>'
        ),
    },
    {
        "doc_type": "opinion",
        "name": "法律意见书",
        "content": (
            "<p>致：{客户姓名}</p>"
            "<p>根据贵方委托，{律所名称}就{案件标题}（案号：{案号}）"
            "相关法律问题出具本意见书。</p>"
            "<p>一、基本事实</p>"
            "<p>贵方与{对方当事人}因{案由}发生争议，涉案金额人民币 "
            "{标的额} 元，目前由{受理法院}受理。……</p>"
            "<p>二、法律分析</p>"
            "<p>（一）关于合同效力……</p>"
            "<p>（二）关于违约责任……</p>"
            "<p>（三）关于诉讼时效……</p>"
            "<p>三、结论与建议</p>"
            "<p>建议贵方在举证期限内补充关键证据，并优先考虑协商和解；"
            "如协商不成，可依法主张全部债权及相应利息。</p>"
            "<p>本意见仅基于贵方提供的材料作出，供贵方决策参考。</p>"
            '<p style="text-align:right">{律所名称}</p>'
            '<p style="text-align:right">律师：{委托律师}</p>'
            '<p style="text-align:right">{今日日期}</p>'
        ),
    },
    {
        "doc_type": "poa",
        "name": "授权委托书",
        "content": (
            "<p>委托人：{客户姓名}，证件号 {客户证件号}，"
            "住{客户地址}，联系电话：{客户电话}。</p>"
            "<p>受托人：{委托律师}，{律所名称}律师。</p>"
            "<p>现委托上述受托人在委托人与{对方当事人}{案由}纠纷一案"
            "（案号：{案号}）中，担任委托人的诉讼代理人。</p>"
            "<p>代理权限：代为起诉、应诉、承认或变更诉讼请求、进行调解、"
            "提起上诉、申请执行、签收法律文书等（特别授权）。</p>"
            "<p>委托期限：自本委托书签署之日起至本案终结（含执行）止。</p>"
            '<p style="text-align:right">委托人：{客户姓名}</p>'
            '<p style="text-align:right">受托人：{委托律师}</p>'
            '<p style="text-align:right">{今日日期}</p>'
        ),
    },
]


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        for tpl in TEMPLATES:
            exists = await conn.scalar(
                text(
                    "SELECT COUNT(*) FROM `doc_template` "
                    "WHERE `doc_type` = :doc_type AND `name` = :name"
                ),
                {"doc_type": tpl["doc_type"], "name": tpl["name"]},
            )
            if exists:
                print(f"- 已存在，跳过：{tpl['name']}")
                continue
            await conn.execute(
                text(
                    "INSERT INTO `doc_template` (`doc_type`, `name`, `content`) "
                    "VALUES (:doc_type, :name, :content)"
                ),
                tpl,
            )
            print(f"✓ 写入模板：{tpl['name']}（{tpl['doc_type']}）")

    await engine.dispose()
    print("模板种子数据完成")


if __name__ == "__main__":
    asyncio.run(main())
