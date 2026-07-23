# -*- coding: utf-8 -*-
"""
Gemini 2.5 Flash를 활용한 이 앱만의 차별화 기능.

기존 프로젝트에서 쓰시던 google-genai SDK 패턴을 그대로 따릅니다.
secrets.toml에 GEMINI_API_KEY 가 있어야 합니다.

제공 기능
1. recommend_institutions : 사용자 우선순위 기반 맞춤 검진기관 추천 + 근거 설명
2. generate_prep_checklist : 선택한 검진 항목에 맞춘 검진 준비물/주의사항 체크리스트

⚠️ 의료적 판단(질병 진단, 검사 필요성 등)은 하지 않고
   '행정적·절차적 안내'로 범위를 한정한 프롬프트로 설계했습니다.
"""
from __future__ import annotations

import json

import streamlit as st
from google import genai

MODEL_NAME = "gemini-2.5-flash"


def _get_client() -> genai.Client:
    api_key = st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY가 secrets.toml에 설정되어 있지 않습니다.")
    return genai.Client(api_key=api_key)


def recommend_institutions(user_profile: dict, candidates: list[dict], top_n: int = 3) -> dict:
    """후보 검진기관 리스트 중 사용자 조건에 가장 적합한 top_n을 추천합니다.

    user_profile 예시:
        {"연령대": "40대", "성별": "여성",
         "우선순위": ["집에서 가까움", "여성전문의", "토요일 진료"],
         "받고싶은검진": ["일반건강검진", "유방암검진", "자궁경부암검진"]}

    candidates: hmc_database.search_local() 결과를 dict 리스트로 변환한 것 (최대 30건 권장)
    """
    client = _get_client()

    # 토큰 절약을 위해 추천에 필요한 필드만 추려서 전달
    trimmed = [
        {
            "hmc_no": c.get("hmc_no"),
            "기관명": c.get("hmc_nm"),
            "기관종별": c.get("ykindnm"),
            "주소": c.get("loc_addr"),
            "전화": c.get("hmc_tel_no") or c.get("exmdr_tel_no"),
        }
        for c in candidates[:30]
    ]

    prompt = f"""
당신은 국가건강검진기관 정보를 안내하는 상담원입니다.
아래 [사용자 조건]과 [후보 기관 목록]을 참고하여 가장 적합한 기관 최대 {top_n}곳을 추천하세요.

규칙:
- 반드시 [후보 기관 목록]에 있는 기관 중에서만 hmc_no를 골라야 합니다. 목록에 없는 기관을 만들어내지 마세요.
- 질병 진단이나 특정 검사가 필요한지 여부 같은 의학적 판단은 하지 마세요. 행정적/절차적 안내에만 집중하세요.
- 각 추천에는 왜 이 기관을 골랐는지 사용자 조건과 연결한 짧은 이유를 반드시 포함하세요.
- 정보가 부족해 확신할 수 없는 경우 그 사실을 솔직히 밝히세요.
- 응답은 아래 JSON 스키마만 출력하세요. 다른 텍스트, 코드블록 표시(```) 없이 순수 JSON만 출력합니다.

JSON 스키마:
{{
  "recommendations": [
    {{"hmc_no": "string", "기관명": "string", "추천이유": "string"}}
  ],
  "일반안내": "string (검진 예약 시 공통으로 챙기면 좋은 팁 1~2문장)"
}}

[사용자 조건]
{json.dumps(user_profile, ensure_ascii=False, indent=2)}

[후보 기관 목록]
{json.dumps(trimmed, ensure_ascii=False, indent=2)}
"""

    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    text = (response.text or "").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"recommendations": [], "일반안내": text}


def generate_prep_checklist(selected_exam_types: list[str]) -> str:
    """선택한 검진 항목에 맞춘 준비물/주의사항 체크리스트(마크다운 텍스트)를 생성합니다."""
    client = _get_client()

    prompt = f"""
당신은 국가건강검진 예약자를 위한 준비 안내 도우미입니다.
아래 [선택한 검진 항목]에 맞춰 검진 당일/사전 준비사항 체크리스트를 마크다운으로 작성하세요.

포함할 내용 (해당되는 경우에만):
- 금식 필요 여부와 권장 금식 시간
- 지참해야 할 서류 (신분증, 검진표 등 일반적으로 알려진 것)
- 검진 전 피해야 할 행동(과도한 운동, 음주 등 일반 상식 수준)
- 복용 중인 약이 있다면 병원에 미리 알리라는 안내

제약:
- 특정 질환에 대한 의학적 판단이나 진단은 하지 마세요.
- 개인마다 다를 수 있으니 최종 확인은 예약한 검진기관에 문의하라는 문구를 마지막에 꼭 넣으세요.
- 마크다운 체크박스(- [ ]) 형식을 사용하세요.

[선택한 검진 항목]
{', '.join(selected_exam_types) if selected_exam_types else '일반건강검진'}
"""

    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    return (response.text or "").strip()
