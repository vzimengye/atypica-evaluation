from __future__ import annotations

import json
from typing import Any


QUESTION_SET: list[dict[str, Any]] = [
    {
        "id": "B1Q1",
        "block_id": "block_1",
        "block_label": "Block 1. Decision Context",
        "question_number": 1,
        "target": "先把受访者带回到一个具体场景里。",
        "question": "想请您聊聊最近一次花心思买东西或者订服务的经历。不一定是特别贵的，但得是您认真挑过、纠结过的。比如：换手机、买衣服、报个健身课、给家里买个大件电器，甚至只是为了选一家好餐厅请客。为什么这件事在当时对你重要？",
        "use_for_persona": True,
        "evaluation_focus": ["decision_context"],
    },
    {
        "id": "B1Q2",
        "block_id": "block_1",
        "block_label": "Block 1. Decision Context",
        "question_number": 2,
        "target": "先把受访者带回到一个具体场景里。",
        "question": "最后你做了什么决定？如果当时什么都不做，会有什么后果吗？",
        "use_for_persona": True,
        "evaluation_focus": ["decision_context"],
    },
    {
        "id": "B1Q3",
        "block_id": "block_1",
        "block_label": "Block 1. Decision Context",
        "question_number": 3,
        "target": "先把受访者带回到一个具体场景里。",
        "question": "这个决定最后是你一个人说了算，还是得顾及别人，例如家人朋友？",
        "use_for_persona": True,
        "evaluation_focus": ["decision_context", "stakeholders"],
    },
    {
        "id": "B1Q4",
        "block_id": "block_1",
        "block_label": "Block 1. Decision Context",
        "question_number": 4,
        "target": "先把受访者带回到一个具体场景里。",
        "question": "当时心里有没有预算、时间、精力、试错成本之类的上下限？例如最多花多少钱、费多大劲。",
        "use_for_persona": True,
        "evaluation_focus": ["constraints", "thresholds"],
    },
    {
        "id": "B2Q1",
        "block_id": "block_2",
        "block_label": "Block 2. Consideration Set",
        "question_number": 1,
        "target": "知道 TA 真正会比较什么，以及默认基准是什么。",
        "question": "当时你最先想到的几个方案是什么？为什么？",
        "use_for_persona": True,
        "evaluation_focus": ["consideration_set"],
    },
    {
        "id": "B2Q2",
        "block_id": "block_2",
        "block_label": "Block 2. Consideration Set",
        "question_number": 2,
        "target": "知道 TA 真正会比较什么，以及默认基准是什么。",
        "question": "你后来具体去看了哪些品牌、产品、服务或者替代做法？哪怕是打算‘干脆不买了’或者‘找个旧的先凑合’也算。",
        "use_for_persona": True,
        "evaluation_focus": ["consideration_set"],
    },
    {
        "id": "B2Q3",
        "block_id": "block_2",
        "block_label": "Block 2. Consideration Set",
        "question_number": 3,
        "target": "知道 TA 真正会比较什么，以及默认基准是什么。",
        "question": "在这些选项里，有没有哪个是你一开始最心动的？为什么？",
        "use_for_persona": True,
        "evaluation_focus": ["consideration_set", "initial_preference"],
    },
    {
        "id": "B2Q4",
        "block_id": "block_2",
        "block_label": "Block 2. Consideration Set",
        "question_number": 4,
        "target": "知道 TA 真正会比较什么，以及默认基准是什么。",
        "question": "有没有哪个方案你原本很感兴趣，但后来放弃了？",
        "use_for_persona": False,
        "evaluation_focus": ["abandonment", "barriers"],
    },
    {
        "id": "B2Q5",
        "block_id": "block_2",
        "block_label": "Block 2. Consideration Set",
        "question_number": 5,
        "target": "知道 TA 真正会比较什么，以及默认基准是什么。",
        "question": "有没有哪家是你扫了一眼就觉得‘这肯定不行’的？是什么细节（比如名字、包装、甚至某条评价）让你瞬间觉得不适合？",
        "use_for_persona": False,
        "evaluation_focus": ["instant_rejection", "barriers", "trust"],
    },
    {
        "id": "B3Q1",
        "block_id": "block_3",
        "block_label": "Block 3. Evaluation Criteria",
        "question_number": 1,
        "target": "知道 TA 真正如何做取舍，而不只是知道 TA 喜欢什么。",
        "question": "您挑这类东西时，第一眼最看重什么？价格、品牌、效果、颜值、朋友推荐……为什么这个对您最关键？",
        "use_for_persona": True,
        "evaluation_focus": ["evaluation_criteria"],
    },
    {
        "id": "B3Q2",
        "block_id": "block_3",
        "block_label": "Block 3. Evaluation Criteria",
        "question_number": 2,
        "target": "知道 TA 真正如何做取舍，而不只是知道 TA 喜欢什么。",
        "question": "当有两个选项看起来都不错时，是什么细微的差别或者条件的变化让你最后拍了板？",
        "use_for_persona": True,
        "evaluation_focus": ["trade_offs", "decision_rules"],
    },
    {
        "id": "B3Q3",
        "block_id": "block_3",
        "block_label": "Block 3. Evaluation Criteria",
        "question_number": 3,
        "target": "知道 TA 真正如何做取舍，而不只是知道 TA 喜欢什么。",
        "question": "如果一个东西别的方面都很好，但唯独[某个核心指标]差一点，你还能接受吗？",
        "use_for_persona": False,
        "evaluation_focus": ["thresholds", "trade_offs"],
    },
    {
        "id": "B4Q1",
        "block_id": "block_4",
        "block_label": "Block 4. Drivers, Barriers & Trust Signals",
        "question_number": 1,
        "target": "知道什么会打动 TA、让 TA 犹豫、让 TA 失去信任。",
        "question": "在对比的时候，看到什么样的信息（比如大 V 测评、老同学转发、官方质检报告、或者是‘假一赔十’的承诺）会让你觉得：‘嗯，这家可以，值得认真看看’或者‘嗯，可以相信’？",
        "use_for_persona": True,
        "evaluation_focus": ["trust_signals", "drivers"],
    },
    {
        "id": "B4Q2",
        "block_id": "block_4",
        "block_label": "Block 4. Drivers, Barriers & Trust Signals",
        "question_number": 2,
        "target": "知道什么会打动 TA、让 TA 犹豫、让 TA 失去信任。",
        "question": "反之，有没有会让你不太喜欢或者犹豫的因素？是什么？他们一般到了什么程度，会让你从“有点犹豫”变成“算了，不考虑了”？",
        "use_for_persona": True,
        "evaluation_focus": ["barriers", "thresholds", "deal_breakers"],
    },
    {
        "id": "B4Q3",
        "block_id": "block_4",
        "block_label": "Block 4. Drivers, Barriers & Trust Signals",
        "question_number": 3,
        "target": "知道什么会打动 TA、让 TA 犹豫、让 TA 失去信任。",
        "question": "什么样的广告方式或表达，会让你本能地觉得“这家在忽悠我”？",
        "use_for_persona": False,
        "evaluation_focus": ["trust", "ad_skepticism"],
    },
    {
        "id": "B4Q4",
        "block_id": "block_4",
        "block_label": "Block 4. Drivers, Barriers & Trust Signals",
        "question_number": 4,
        "target": "知道什么会打动 TA、让 TA 犹豫、让 TA 失去信任。",
        "question": "如果满屏都是好评，和一个有几个中肯差评的方案相比，你会更倾向于相信哪一个？",
        "use_for_persona": False,
        "evaluation_focus": ["trust", "review_heuristics"],
    },
    {
        "id": "B5Q1",
        "block_id": "block_5",
        "block_label": "Block 5. Trade-offs & Counterfactuals",
        "question_number": 1,
        "target": "测这个人会不会因为条件变化而改变判断。",
        "question": "咱们换个情况想想，看看您的想法会不会变：如果当时它贵了 20%，或者另一个原本很贵的牌子/方案突然打五折，你会改主意吗？",
        "use_for_persona": False,
        "evaluation_focus": ["counterfactual", "price_shift"],
    },
    {
        "id": "B5Q2",
        "block_id": "block_5",
        "block_label": "Block 5. Trade-offs & Counterfactuals",
        "question_number": 2,
        "target": "测这个人会不会因为条件变化而改变判断。",
        "question": "那如果买这个东西需要等一个月才发货，或者购买流程特别麻烦，你还会坚持选它吗？",
        "use_for_persona": False,
        "evaluation_focus": ["counterfactual", "friction_shift"],
    },
    {
        "id": "B5Q3",
        "block_id": "block_5",
        "block_label": "Block 5. Trade-offs & Counterfactuals",
        "question_number": 3,
        "target": "测这个人会不会因为条件变化而改变判断。",
        "question": "如果你身边很信任的人明确告诉你“这东西不好用”，但网上评分很高，你听谁的？",
        "use_for_persona": False,
        "evaluation_focus": ["counterfactual", "social_influence", "trust_conflict"],
    },
    {
        "id": "B6Q1",
        "block_id": "block_6",
        "block_label": "Block 6. Reflection & Self-Explanation",
        "question_number": 1,
        "target": "拿到更自然、更接近真人表达的语言方式。",
        "question": "回过头看，您觉得自己在做这种决定时，是那种‘货比三家’的理智派，还是‘看对眼了就买’的感觉派？",
        "use_for_persona": True,
        "evaluation_focus": ["self_description", "language_style"],
    },
    {
        "id": "B6Q2",
        "block_id": "block_6",
        "block_label": "Block 6. Reflection & Self-Explanation",
        "question_number": 2,
        "target": "拿到更自然、更接近真人表达的语言方式。",
        "question": "你觉得自己最大的决策弱点是什么？以前有没有哪次买完就后悔的经历？当时是被什么给“蒙蔽”了？",
        "use_for_persona": False,
        "evaluation_focus": ["reflection", "decision_weakness"],
    },
    {
        "id": "B6Q3",
        "block_id": "block_6",
        "block_label": "Block 6. Reflection & Self-Explanation",
        "question_number": 3,
        "target": "拿到更自然、更接近真人表达的语言方式。",
        "question": "如果要把这次经验分享给别人（例如好友，家人），你会怎么讲述自己做出这个决定的过程？你会提醒 TA 避开什么坑？",
        "use_for_persona": False,
        "evaluation_focus": ["self_explanation", "advice_style"],
    },
]


def questions_for_persona() -> list[dict[str, Any]]:
    return [item for item in QUESTION_SET if item["use_for_persona"]]


def holdout_questions() -> list[dict[str, Any]]:
    return [item for item in QUESTION_SET if not item["use_for_persona"]]


def question_ids(use_for_persona: bool) -> list[str]:
    return [item["id"] for item in QUESTION_SET if item["use_for_persona"] == use_for_persona]


def protocol_json(questions: list[dict[str, Any]] | None = None) -> str:
    return json.dumps(questions or QUESTION_SET, ensure_ascii=False, indent=2)


def protocol_markdown(questions: list[dict[str, Any]] | None = None) -> str:
    selected = questions or QUESTION_SET
    lines: list[str] = []
    current_block = None
    for item in selected:
        if item["block_id"] != current_block:
            current_block = item["block_id"]
            lines.extend(
                [
                    item["block_label"],
                    f"目标：{item['target']}",
                ]
            )
        lines.append(f"{item['question_number']}. {item['question']}")
        lines.append("")
    return "\n".join(lines).strip()


def split_summary() -> dict[str, Any]:
    building = questions_for_persona()
    holdout = holdout_questions()
    return {
        "mode": "fixed_holdout_phase_1",
        "building_question_ids": [item["id"] for item in building],
        "holdout_question_ids": [item["id"] for item in holdout],
        "building_count": len(building),
        "holdout_count": len(holdout),
    }


def group_answers_by_block(question_answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in question_answers:
        block_id = item.get("block_id", "")
        block = grouped.setdefault(
            block_id,
            {
                "block_id": block_id,
                "block_label": item.get("block_label", block_id),
                "target": item.get("target", ""),
                "items": [],
            },
        )
        block["items"].append(item)
    return list(grouped.values())


def render_ground_truth_markdown(title: str, question_answers: list[dict[str, Any]]) -> str:
    grouped = group_answers_by_block(question_answers)
    lines = [f"# {title}", ""]
    for block in grouped:
        lines.extend(
            [
                f"## {block['block_label']}",
                f"目标：{block['target']}",
                "",
            ]
        )
        for item in block["items"]:
            lines.extend(
                [
                    f"### {item.get('id', '')} - Q{item.get('question_number', '')}",
                    f"**Question:** {item.get('question', '')}",
                    f"**Answered:** {item.get('answer_status', 'unknown')}",
                    f"**Answer summary:** {item.get('answer_summary', '') or 'No clear answer extracted.'}",
                ]
            )
            example = item.get("concrete_example", "")
            if example:
                lines.append(f"**Concrete example:** {example}")
            evidence = item.get("evidence_snippets", [])
            if evidence:
                lines.append("**Evidence snippets:**")
                lines.extend(f"- {snippet}" for snippet in evidence)
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_split_markdown(split: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Evaluation Split",
            "",
            f"- Mode: {split.get('mode', 'unknown')}",
            f"- Persona building questions: {split.get('building_count', 0)}",
            f"- Holdout evaluation questions: {split.get('holdout_count', 0)}",
            "",
            "## Persona Building Question IDs",
            *(f"- {item}" for item in split.get("building_question_ids", [])),
            "",
            "## Holdout Question IDs",
            *(f"- {item}" for item in split.get("holdout_question_ids", [])),
            "",
            "## Holdout Purpose",
            "- Judge: compare AI interview answers against withheld human answers.",
            "- Task Benchmark: score unseen task behavior using the persona built from building-only inputs.",
            "- Stability: rerun the unseen task benchmark on the same persona package.",
            "",
        ]
    )
