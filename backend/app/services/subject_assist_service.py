from __future__ import annotations

import json
from typing import Any

from app.clients.openai_compatible_client import OpenAICompatibleError, chat_completion


class SubjectAssistError(RuntimeError):
    pass


SYSTEM_PROMPT = (
    "You help build synthetic image dataset tasks. "
    "Return strict JSON only with keys categories, extra_desc. "
    "categories must be a 2-6 item array of concise English snake_case labels. "
    "extra_desc must be concise Simplified Chinese, focus on scene, action, occlusion, lighting, and dataset usefulness. "
    "If the subject involves people, default to Chinese human appearance and mention Chinese facial or identity features unless the user explicitly requests another ethnicity."
)


def suggest_subject_fields(
    *,
    base_url: str,
    api_key: str,
    model: str,
    subject: str,
) -> dict[str, Any]:
    user_prompt = (
        f"目标对象：{subject}\n"
        "请补全适合图像生成数据集任务的字段，输出 JSON：\n"
        "{\n"
        '  "categories": ["string"],\n'
        '  "extra_desc": "string"\n'
        "}\n"
        "要求：categories 用英文标签；extra_desc 用中文且不要超过120字；如果涉及人物，默认限定为中国人的外貌与特征。"
    )

    try:
        content = chat_completion(
            base_url=base_url,
            api_key=api_key,
            model=model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except OpenAICompatibleError as exc:
        raise SubjectAssistError(str(exc)) from exc

    parsed = _parse_json_response(content)
    categories = parsed.get("categories")
    extra_desc = str(parsed.get("extra_desc", "")).strip()
    if not isinstance(categories, list) or not categories:
        raise SubjectAssistError("subject_assist_invalid_categories")
    cleaned_categories = [str(item).strip() for item in categories if str(item).strip()]
    if not cleaned_categories:
        raise SubjectAssistError("subject_assist_empty_categories")
    if not extra_desc:
        raise SubjectAssistError("subject_assist_empty_extra_desc")

    return {
        "categories": cleaned_categories[:6],
        "extra_desc": extra_desc[:120],
    }


def _parse_json_response(content: str) -> dict[str, Any]:
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SubjectAssistError("subject_assist_invalid_json") from exc
    if not isinstance(parsed, dict):
        raise SubjectAssistError("subject_assist_invalid_payload")
    return parsed
