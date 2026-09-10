import json

from document_selection import (
    DOCUMENT_CATEGORY_BY_TITLE,
    DOCUMENT_OVERVIEW_GROUPS,
    build_final_document_counts,
    build_pre_meeting_document_counts,
    document_category_for_title,
    document_description_for_title,
    document_sort_key,
    format_risk_facts_for_prompt,
)
from templates import (
    TEMPLATE_COMPLIANCE_PLAN,
    TEMPLATE_DOCUMENT_LIST,
)


COMMON_OUTPUT_RULES = """硬性输出要求：
1. 只输出正式文档正文，不要输出"以下是""好的""说明如下"等解释性文字。
2. 不要使用 Markdown 标记，包括但不限于 #、*、```。
3. 标题层级尽量保持模板口径：一级用"一、二、三"，二级用"（一）（二）（三）"，三级用"1. 2. 3."。
4. 会议记录没有依据的企业事实不得编造；无法确认的内容用"需进一步确认"表述。
5. 口吻应为律师或法务顾问向企业正式交付的书面口吻，内容可直接复制到 Word。"""


def _format_allowed_document_names() -> str:
    lines = []
    sequence = 1
    for category, titles in DOCUMENT_OVERVIEW_GROUPS:
        lines.append(category)
        for title in titles:
            lines.append(f"{sequence}.《{title}》")
            sequence += 1
    return "\n".join(lines)


ALLOWED_DOCUMENT_NAMES = _format_allowed_document_names()


def build_allowed_document_names(document_counts: dict[str, int] | None = None) -> str:
    if not document_counts:
        return ALLOWED_DOCUMENT_NAMES

    count_categories = getattr(document_counts, "categories", {})
    dynamic_titles = [
        title
        for title in document_counts
        if title and title not in DOCUMENT_CATEGORY_BY_TITLE
    ]
    if not dynamic_titles:
        return ALLOWED_DOCUMENT_NAMES

    lines = ["", "本次律师勾选或后端识别的动态文书"]
    used_titles: set[str] = set()
    for category, _ in DOCUMENT_OVERVIEW_GROUPS:
        category_titles = [
            title
            for title in dynamic_titles
            if document_category_for_title(title, count_categories) == category
        ]
        if not category_titles:
            continue
        lines.append(category)
        for title in sorted(category_titles, key=lambda item: document_sort_key(item, count_categories)):
            lines.append(f"- 《{title}》")
            used_titles.add(title)

    rest_titles = [title for title in dynamic_titles if title not in used_titles]
    if rest_titles:
        lines.append("其他动态文书")
        for title in sorted(rest_titles):
            lines.append(f"- 《{title}》")

    return ALLOWED_DOCUMENT_NAMES + "\n" + "\n".join(lines)


def _group_document_titles(document_counts: dict[str, int] | None) -> list[tuple[str, list[str]]]:
    if not document_counts:
        return []

    count_categories = getattr(document_counts, "categories", {})
    grouped: list[tuple[str, list[str]]] = []
    used_titles: set[str] = set()
    for category, _ in DOCUMENT_OVERVIEW_GROUPS:
        category_titles = [
            title
            for title in document_counts
            if document_category_for_title(title, count_categories) == category
        ]
        category_titles.sort(key=lambda item: document_sort_key(item, count_categories))
        if category_titles:
            grouped.append((category, category_titles))
            used_titles.update(category_titles)

    rest_titles = [title for title in document_counts if title not in used_titles]
    if rest_titles:
        grouped.append(("其他动态文书", sorted(rest_titles)))
    return grouped


def build_document_list_text(document_counts: dict[str, int] | None = None) -> str:
    grouped_titles = _group_document_titles(document_counts)

    lines = [
        "劳动用工合规专项服务文书清单",
        "",
        "▌文书清单（总览）",
        "序号 | 文书名称 | 份数",
    ]

    sequence = 1
    for category, titles in grouped_titles:
        lines.append(f"{category} | {category} | ")
        for title in titles:
            lines.append(f"{sequence} | 《{title}》 | ")
            sequence += 1

    if sequence == 1:
        lines.append("本次未勾选文书 | 本次未勾选文书 | ")

    lines.extend(["", "各文书作用说明"])

    explanation_sequence = 1
    for category, titles in grouped_titles:
        lines.append(category)
        for title in titles:
            lines.append(f"{explanation_sequence}. 《{title}》")
            lines.append(document_description_for_title(title) or "建议结合企业实际确认是否启用")
            explanation_sequence += 1

    if explanation_sequence == 1:
        lines.append("本次未勾选需要展示的文书。")

    return "\n".join(lines)


def prompt_extract_meeting_facts(
    transcript: str,
    pre_meeting: dict = None,
) -> str:
    pre_meeting_attachment = ""
    if pre_meeting:
        pre_meeting_attachment = "\n\n律师会前勾选内容（仅用于辅助判断，不得替代会议证据）：\n" + json.dumps(
            pre_meeting,
            ensure_ascii=False,
            indent=2,
        )

    return f"""你是劳动用工合规项目的文书识别助手。请先理解腾讯会议纪要中的业务事实和风险点，再判断这些风险点需要哪些标准文书。

重要要求：
1. 不要直接写文书清单；只输出 JSON。
2. 每个风险事实必须有会议纪要原文证据，证据应尽量摘录原句或近似原句。
3. related_documents 只能使用下方允许清单中的标准文书名称，必须带书名号外的纯名称，不得自造名称。
4. 如果只是泛泛提到某个词，但没有形成企业实际场景或风险，不要输出。
5. 需要做遗漏自检，至少检查这些方向：劳动合同签署/续签/变更、试用期/转正、社保/公积金、工伤、考勤/加班/请假/年假、入职、薪资、离职、规章制度、保密/竞业/培训。

风险类型到文书的判断口径：
- 未签劳动合同/补签劳动合同：劳动合同、限期签订劳动合同通知书
- 合同续签/到期续签：劳动合同续签协议
- 放弃续签：放弃续签劳动合同声明
- 试用期延长：延长试用期协议
- 试用期辞退：试用期辞退通知书
- 转正管理：转正审批表
- 不缴社保/放弃社保：自愿放弃缴纳社保承诺书
- 个人缴纳社保：关于本人社会保险的说明（个人缴纳）
- 其他单位缴纳社保：关于本人社会保险的说明（其他单位缴纳）
- 不缴公积金/放弃公积金：自愿放弃缴纳住房公积金承诺书
- 其他单位缴纳公积金：关于本人住房公积金的说明（其他单位缴纳）
- 工伤申报/工伤风险：工伤认定申请表
- 工伤赔偿/工伤费用领取：工伤赔偿协议书、工伤赔偿费用领取单
- 没有规章制度/制度未确认：规章制度、规章制度确认书
- 民主程序/制度公示：民主程序会议签到表、规章制度确认书
- 没有考勤/工时不规范：考勤表
- 加班管理问题：加班审批表
- 请假管理：请假审批表
- 年假/未休年假：年假安排通知书
- 节假日安排/放假通知：节假日安排通知书
- 入职登记/面试登记：面试登记表
- 无离职证明入职：无离职证明承诺书
- 背景调查：背景调查授权书
- 入职承诺：员工入职承诺书
- 工资发放账号：工资发放账号确认书
- 工资条/工资结构/工资拆分：工资条模板
- 薪资调整：薪资调整确认单
- 离职申请/辞职：离职申请书
- 辞退/解除通知：辞退通知书
- 限期返岗/旷工返岗：限期返岗通知书
- 协商解除/解除劳动关系：解除劳动关系协议
- 离职交接：离职交接单
- 离职证明：离职证明
- 保密义务：保密协议
- 竞业限制：竞业限制协议
- 培训服务期：培训服务期协议

允许使用的文书名称清单：
{ALLOWED_DOCUMENT_NAMES}

输出 JSON 格式必须严格如下，不要输出 Markdown，不要输出解释文字：
{{
  "risk_facts": [
    {{
      "risk_type": "风险类型",
      "evidence": "会议纪要原文证据",
      "related_documents": ["标准文书名称"]
    }}
  ],
  "self_check": {{
    "劳动合同签署/续签/变更": "已检查/无明确依据",
    "试用期/转正": "已检查/无明确依据",
    "社保/公积金": "已检查/无明确依据",
    "工伤": "已检查/无明确依据",
    "考勤/加班/请假/年假": "已检查/无明确依据",
    "入职": "已检查/无明确依据",
    "薪资": "已检查/无明确依据",
    "离职": "已检查/无明确依据",
    "规章制度": "已检查/无明确依据",
    "保密/竞业/培训": "已检查/无明确依据"
  }}
}}

腾讯会议纪要：
{transcript}{pre_meeting_attachment}"""


def prompt_compliance_plan(transcript: str, pre_meeting: dict = None, company_name: str = None) -> str:
    additional_info = ""
    if pre_meeting:
        import json
        additional_info = "\n\n律师会前勾选内容：\n" + json.dumps(pre_meeting, ensure_ascii=False, indent=2)

    company_instruction = ""
    if company_name:
        company_instruction = f'\n\n**企业名称**：请在文档开头使用"{company_name}"作为企业名称。'

    return f"""请以附件一为格式和内容风格模板，结合附件二（腾讯会议文字记录）{
        '和律师会前勾选内容' if additional_info else ''
    }，输出一份《劳动用工合规计划书》。
{additional_info}{company_instruction}

写作要求：
1. 文档开头参照模板保留企业名称、英文副标题、中文主标题的结构；企业名称{'使用上面指定的企业名称' if company_name else '应从会议记录中提取，无法确认时写"XX公司"'}。
2. 必须包含三大部分，且一级分节标题必须逐字使用下面三行，便于套用 Word 模板样式：
   第一部分 企业用工基本情况；
   第二部分 现有用工管理核心情况及风险；
   第三部分 劳动用工合规整改清单。
3. 第一部分只写"（一）企业概况"一个小节，用一段正式文字提炼企业行业、地点、员工规模、用工类型、工作时间、薪酬结构、社保公积金、规章制度、入离职等基础情况，不要拆成编号列表。
4. 第二部分按模板写成若干"（一）（二）（三）"小节，每个小节下面用自然段说明风险，不要写成大量加粗编号清单。
5. 第三部分要按风险类别生成整改清单，每个整改事项必须按以下固定格式输出：
   1. 整改事项名称
   整改要求：……
   适用对象：……
   核心要点：……
   配套动作：……
   其中"整改要求"和"配套动作"必须单独成行，便于套用模板的橙色/绿色底纹。
6. 不要照抄模板里的案例企业事实，要根据会议记录替换成当前企业事实。

{COMMON_OUTPUT_RULES}

附件一（模板）：
{TEMPLATE_COMPLIANCE_PLAN}

附件二（会议记录）：
{transcript}"""


def prompt_document_list(
    transcript: str,
    compliance_plan: str = "",
    pre_meeting: dict = None,
    backend_document_counts: dict[str, int] | None = None,
    risk_facts: list[dict] | None = None,
) -> str:
    pre_meeting_reference = ""
    pre_meeting_attachment = ""
    if pre_meeting:
        pre_meeting_reference = "、附件四（律师会前勾选内容）"
        checked_counts = build_final_document_counts(pre_meeting)
        checked_documents = "\n".join(
            f"- 《{title}》：{count}份" for title, count in checked_counts.items()
        )
        pre_meeting_attachment = "\n\n附件四（律师会前勾选内容）：\n" + json.dumps(
            pre_meeting,
            ensure_ascii=False,
            indent=2,
        )
        if checked_documents:
            pre_meeting_attachment += "\n\n后端已识别的律师勾选文书及份数：\n" + checked_documents

    backend_document_counts = backend_document_counts or build_final_document_counts(
        pre_meeting,
        transcript,
        risk_facts=risk_facts,
    )
    backend_documents = "\n".join(
        f"- 《{title}》：{count}份" for title, count in backend_document_counts.items()
    )
    allowed_document_names = build_allowed_document_names(backend_document_counts)
    fixed_document_list = build_document_list_text(backend_document_counts)
    backend_attachment = ""
    if backend_documents:
        backend_attachment = "\n\n附件五（后端根据律师勾选内容识别出的最终候选文书）：\n" + backend_documents

    return f"""请以附件一为格式和内容风格模板，结合附件二（腾讯会议文字记录）{pre_meeting_reference}，输出一份《劳动用工合规专项服务文书清单》。

写作要求：
1. 保留模板的两大结构："文书清单（总览）"和"各文书作用说明"。
2. "文书清单（总览）"必须使用纯文本表格，列名必须逐字为"序号 | 文书名称 | 份数"，每一行都用英文竖线 | 分隔；分类行也要写成"一、用工模式与劳动合同签署 | 一、用工模式与劳动合同签署 | "这种格式，便于套用模板的浅蓝分类行；"份数"列不要填写内容，保持空白。
3. 文书分类优先保持模板的八大类：用工模式与劳动合同签署、社保/公积金及工伤合规、规章制度合规、工时/加班与休假合规、员工入职合规、薪资发放合规、员工离职合规、专项协议合规。
4. 文书名称必须严格从下方"允许使用的文书名称清单"中选择，并逐字使用清单里的名称和书名号；不得自造文书名称、不得改写文书名称、不得输出近义名称；只能选择附件四和附件五实际涉及的文书，不要把模板中的全部文书都输出。
5. "份数"列保持空白，不要写"需确认"、"1"或其他数量。
6. "各文书作用说明"必须采用附件六中的固定说明；每个文书名称单独一行，说明文字另起一行，不要把"1.《文书名》：说明内容"写在同一行。
7. 不要输出与当前企业明显无关的解释；如模板文书可能不适用，应写明"建议结合企业实际确认是否启用"。
8. 如提供附件四（律师会前勾选内容），附件四中的律师勾选文书是本次文书清单的唯一依据，必须全部纳入"文书清单（总览）"和"各文书作用说明"；不得从会议纪要或其他来源补充未勾选的文书。
9. 必须优先采用附件五中的最终候选文书，附件五里的每一份具体文书都必须出现在"文书清单（总览）"和"各文书作用说明"中；不得把具体文书合并成《劳动合同》《规章制度》《工资条模板》等通用名称。
10. 各文书作用说明使用附件六固定说明，不要结合会议纪要自行改写。
11. 文书清单总览和各文书作用说明必须一一对应：总览里出现的文书，说明部分必须说明；说明部分不要额外解释总览里没有列出的文书。
12. 生成内容应是"本次项目涉及的文书清单"，不是模板全集。没有被律师勾选内容或附件五支持的模板文书，不要输出。

允许使用的文书名称清单：
{allowed_document_names}

{COMMON_OUTPUT_RULES}

附件一（模板）：
{TEMPLATE_DOCUMENT_LIST}

附件二（会议记录）：
{transcript}{pre_meeting_attachment}{backend_attachment}

附件六（必须逐字输出的文书清单正文）：
{fixed_document_list}"""


# 兼容旧调用名。
def prompt_checklist(transcript: str) -> str:
    return prompt_compliance_plan(transcript)


def prompt_doclist(transcript: str, checklist: str, pre_meeting: dict = None) -> str:
    return prompt_document_list(transcript, checklist, pre_meeting)
