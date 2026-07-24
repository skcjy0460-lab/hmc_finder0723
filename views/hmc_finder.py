# -*- coding: utf-8 -*-
"""
국가건강검진기관 찾기 (공공데이터포털 B550928 API 연동)

기존 멀티페이지 Streamlit 프로젝트의 pages/ 폴더에 그대로 넣고,
lib/ 폴더(nhis_api.py, hmc_database.py, coord_utils.py, ai_features.py)를
프로젝트 루트의 공용 lib/ 경로에 병합하시면 됩니다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# 프로젝트 구조에 맞게 lib 경로 보정 (이미 공용 lib을 쓰고 계시면 이 블록은 삭제하세요)
sys.path.append(str(Path(__file__).resolve().parent.parent))

from lib import ai_features, hmc_database, nhis_api  # noqa: E402
from lib.nhis_api import NhisApiError  # noqa: E402

st.title("🏥 국가건강검진기관 찾기")
st.caption("국민건강보험공단 공공데이터(B550928)를 활용한 지역별 검진기관 검색 · AI 맞춤 추천")

with st.expander("🔧 API 연결 진단 (시도 목록이 안 보일 때 눌러보세요)"):
    if st.button("getSiDoList 원본 응답 확인"):
        raw = nhis_api.debug_raw_call(
            nhis_api.BASE_CODE, "getSiDoList", {"numOfRows": 100, "pageNo": 1}
        )
        st.write(f"HTTP 상태 코드: {raw.get('status_code')}")
        st.code(raw.get("url", ""), language="text")
        st.code(raw.get("text", "") or raw.get("error", "(응답 없음)"), language="xml")

    st.divider()
    st.caption("아래는 시/도·시/군/구를 먼저 선택한 뒤, 동기화가 0건일 때 눌러보세요.")
    if st.button("getRegnHmcList 원본 응답 확인"):
        params = {
            "siGunGuCd": st.session_state.get("_debug_si_gun_gu_cd"),
            "siDoCd": st.session_state.get("_debug_si_do_cd"),
            "pageNo": 1,
            "numOfRows": 10,
        }
        raw = nhis_api.debug_raw_call(nhis_api.BASE_HMC, "getRegnHmcList", params)
        st.write(f"요청 파라미터: {params}")
        st.write(f"HTTP 상태 코드: {raw.get('status_code')}")
        st.code(raw.get("url", ""), language="text")
        st.code(raw.get("text", "") or raw.get("error", "(응답 없음)"), language="xml")

EXAM_TYPE_LABELS = list(hmc_database.EXAM_TYPE_FIELDS.keys())


# ---------------------------------------------------------------------------
# 1. 지역 선택
# ---------------------------------------------------------------------------
st.subheader("1️⃣ 지역 선택")

try:
    sido_items = nhis_api.get_sido_list()
except NhisApiError as e:
    st.error(f"시도 목록을 불러오지 못했습니다: {e}")
    sido_items = []

sido_options = {item["siDoNm"]: item["siDoCd"] for item in sido_items if item.get("siDoNm")}

col1, col2 = st.columns(2)
with col1:
    sido_nm = st.selectbox("시/도", options=["선택하세요"] + sorted(sido_options.keys()))

sigungu_options: dict[str, str] = {}
if sido_nm != "선택하세요":
    si_do_cd = sido_options[sido_nm]
    try:
        sigungu_items = nhis_api.get_sigungu_list(si_do_cd)
        sigungu_options = {
            item["siGunGuNm"]: item["siGunGuCd"] for item in sigungu_items if item.get("siGunGuNm")
        }
    except NhisApiError as e:
        st.error(f"시군구 목록을 불러오지 못했습니다: {e}")

with col2:
    sigungu_nm = st.selectbox(
        "시/군/구",
        options=["선택하세요"] + sorted(sigungu_options.keys()),
        disabled=not sigungu_options,
    )

selected_si_gun_gu_cd_raw = sigungu_options.get(sigungu_nm)
selected_si_do_cd = sido_options.get(sido_nm)
# HmcSearchService(getRegnHmcList 등)는 CodeServices의 분리형 코드가 아니라
# 5자리 결합 행정표준코드를 요구하는 것으로 확인되어(2026-07-23), 여기서 변환합니다.
selected_si_gun_gu_cd = nhis_api.build_sigungu_full_code(selected_si_do_cd, selected_si_gun_gu_cd_raw)
st.session_state["_debug_si_gun_gu_cd"] = selected_si_gun_gu_cd
st.session_state["_debug_si_do_cd"] = selected_si_do_cd

if selected_si_gun_gu_cd:
    last_sync = hmc_database.get_last_sync(selected_si_gun_gu_cd)
    sync_col1, sync_col2 = st.columns([3, 1])
    with sync_col1:
        if last_sync:
            st.info(
                f"마지막 동기화: {last_sync['synced_at']} · {last_sync['row_count']}개 기관 저장됨"
            )
        else:
            st.warning("아직 이 지역 데이터가 로컬에 없습니다. 먼저 동기화해주세요.")
    with sync_col2:
        if st.button("🔄 데이터 동기화", use_container_width=True):
            with st.spinner("공공데이터포털에서 검진기관 정보를 가져오는 중..."):
                try:
                    items = nhis_api.fetch_all_regn_hmc(
                        si_gun_gu_cd=selected_si_gun_gu_cd, si_do_cd=selected_si_do_cd
                    )
                    count = hmc_database.upsert_items(
                        items, si_gun_gu_cd=selected_si_gun_gu_cd, si_do_cd=selected_si_do_cd
                    )
                    st.success(f"{count}개 기관 정보를 동기화했습니다.")
                    st.rerun()
                except NhisApiError as e:
                    st.error(f"동기화 실패: {e}")


# ---------------------------------------------------------------------------
# 2. 검진 조건 필터
# ---------------------------------------------------------------------------
st.subheader("2️⃣ 검진 조건")

keyword = st.text_input("기관명 검색 (선택)", placeholder="예: 서울대학교병원")
required_exams = st.multiselect("받고 싶은 검진 항목", options=EXAM_TYPE_LABELS)

st.divider()

# ---------------------------------------------------------------------------
# 3. 검색 결과
# ---------------------------------------------------------------------------
st.subheader("3️⃣ 검색 결과")

df = hmc_database.search_local(
    si_do_cd=selected_si_do_cd,
    si_gun_gu_cd=selected_si_gun_gu_cd,
    hmc_nm_keyword=keyword or None,
    required_exam_types=required_exams or None,
)

if df.empty:
    st.info("조건에 맞는 검진기관이 없습니다. 지역을 동기화했는지, 필터가 너무 좁지 않은지 확인해주세요.")
else:
    st.write(f"총 **{len(df)}개** 기관")

    display_df = df.rename(
        columns={
            "hmc_nm": "기관명",
            "ykindnm": "기관종별",
            "loc_addr": "주소",
            "hmc_tel_no": "전화번호",
            "exmdr_tel_no": "검진문의전화",
        }
    )
    show_cols = [c for c in ["기관명", "기관종별", "주소", "전화번호", "검진문의전화"] if c in display_df.columns]
    st.dataframe(display_df[show_cols], use_container_width=True, hide_index=True)

    map_df = df.dropna(subset=["lat", "lng"])[["lat", "lng", "hmc_nm"]].rename(
        columns={"lat": "latitude", "lng": "longitude"}
    )
    if not map_df.empty:
        st.map(map_df, latitude="latitude", longitude="longitude", size=30)
    else:
        st.caption(
            "좌표 정보를 지도에 표시할 수 없습니다 (좌표계 확인 필요 - "
            "lib/coord_utils.py의 DEFAULT_SOURCE_EPSG 참고)."
        )

    excel_bytes = hmc_database.to_excel_bytes(df)
    st.download_button(
        "📥 검색 결과 엑셀 다운로드",
        data=excel_bytes,
        file_name=f"검진기관_{sigungu_nm if selected_si_gun_gu_cd else '전체'}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.divider()

# ---------------------------------------------------------------------------
# 4. AI 맞춤 추천
# ---------------------------------------------------------------------------
st.subheader("🤖 AI 맞춤 검진기관 추천")

with st.expander("내 조건에 맞는 기관 AI에게 추천받기", expanded=False):
    if df.empty:
        st.caption("먼저 지역을 선택하고 검색 결과를 확보한 뒤 이용해주세요.")
    else:
        age_group = st.selectbox("연령대", ["20대", "30대", "40대", "50대", "60대 이상"])
        gender = st.radio("성별", ["여성", "남성"], horizontal=True)
        priorities = st.multiselect(
            "우선순위 (복수 선택 가능)",
            ["집에서 가까움", "여성 전문의 선호", "토요일 진료 가능", "대형 종합병원 선호", "예약 대기 짧음"],
        )

        if st.button("AI 추천받기", type="primary"):
            with st.spinner("AI가 조건에 맞는 기관을 분석하는 중..."):
                try:
                    profile = {
                        "연령대": age_group,
                        "성별": gender,
                        "우선순위": priorities,
                        "받고싶은검진": required_exams or ["일반건강검진"],
                    }
                    candidates = df.to_dict(orient="records")
                    result = ai_features.recommend_institutions(profile, candidates)

                    recs = result.get("recommendations", [])
                    if not recs:
                        st.warning("AI가 조건에 맞는 기관을 찾지 못했습니다. 조건을 넓혀보세요.")
                    for rec in recs:
                        st.markdown(f"**✅ {rec.get('기관명', '알 수 없음')}**")
                        st.write(rec.get("추천이유", ""))
                        st.markdown("---")

                    if result.get("일반안내"):
                        st.info(result["일반안내"])
                except Exception as e:  # noqa: BLE001
                    st.error(f"AI 추천 중 오류가 발생했습니다: {e}")

# ---------------------------------------------------------------------------
# 5. 검진 준비물 체크리스트
# ---------------------------------------------------------------------------
st.subheader("📋 검진 준비물 체크리스트")

with st.expander("선택한 검진 항목 기준 준비물 안내 받기", expanded=False):
    if st.button("체크리스트 생성"):
        with st.spinner("체크리스트를 생성하는 중..."):
            try:
                checklist = ai_features.generate_prep_checklist(required_exams)
                st.markdown(checklist)
            except Exception as e:  # noqa: BLE001
                st.error(f"체크리스트 생성 중 오류가 발생했습니다: {e}")
