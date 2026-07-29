# -*- coding: utf-8 -*-
"""
공공데이터포털의 "국민건강보험공단_검진기관기본" 같은 파일데이터(csv/xlsx)를
읽어서 로컬 DB에 병합하는 모듈.

이 파일데이터는 API(HmcSearchService)와 달리 검진기관명/주소/전화번호
정도만 제공하고 검진종류별 지원여부·좌표는 없는 것으로 보입니다. 그래서:
- 주소 텍스트에서 시/도·시/군/구를 문자열 매칭으로 추정해 지역코드를 붙입니다.
- 검진종류 지원여부 컬럼은 전부 NULL로 두고, 화면에서는 "정보없음 - 병원에 문의"로 안내합니다.
- source='file_import'로 표시해 API 데이터와 구분합니다.

실제 파일의 정확한 컬럼명은 내려받아보기 전까지 확정할 수 없으므로,
컬럼명은 키워드 포함 여부로 유연하게 찾습니다 (자동 필드 감지).
"""
from __future__ import annotations

import hashlib
import io

import pandas as pd

# 컬럼명에 아래 키워드가 포함되어 있으면 해당 필드로 인식합니다.
# 필수: hmc_nm, loc_addr. 나머지는 있으면 쓰고 없으면 비워둡니다.
FIELD_KEYWORDS = {
    "hmc_nm": ["검진기관명", "기관명", "병원명", "명칭"],
    "loc_addr": ["소재지주소", "주소"],
    "hmc_tel_no": ["전화번호", "전화", "연락처"],
    "ykindnm": ["기관종별", "종별"],
    "si_do_nm": ["시도명", "시/도"],
    "si_gun_gu_nm": ["시군구명", "시/군/구"],
    "lat": ["위도"],
    "lng": ["경도"],
}

# 검진종류별 지원여부 컬럼 (Y/N, 1/0, 가능/불가능 등으로 채우면 됨).
# 키는 hmc_database.EXAM_TYPE_FIELDS의 한글 라벨과 동일하게 맞춰서 그대로 재사용합니다.
EXAM_TYPE_COLUMN_TO_API_FIELD = {
    "일반건강검진": "grenChrgTypeCd",
    "영유아검진": "ichkChrgTypeCd",
    "위암검진": "stmcaExmdChrgTypeCd",
    "간암검진": "lvcaExmdChrgTypeCd",
    "대장암검진": "ccExmdChrgTypeCd",
    "유방암검진": "bcExmdChrgTypeCd",
    "자궁경부암검진": "cvxcaExmdChrgTypeCd",
    "구강검진": "oralChrgTypeCd",
    "폐암검진": "lungcaChrgTypeCd",
}
TRUE_VALUES = {"Y", "y", "예", "가능", "1", "TRUE", "true", "O", "o"}

ENCODINGS_TO_TRY = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]


class FileImportError(Exception):
    pass


def load_table(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """csv 또는 xlsx 파일 바이트를 DataFrame으로 읽습니다 (인코딩 자동 감지)."""
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(file_bytes))

    last_exc: Exception | None = None
    for enc in ENCODINGS_TO_TRY:
        try:
            return pd.read_csv(io.BytesIO(file_bytes), encoding=enc)
        except (UnicodeDecodeError, UnicodeError) as exc:
            last_exc = exc
            continue
    raise FileImportError(f"CSV 인코딩을 인식하지 못했습니다 (시도: {ENCODINGS_TO_TRY}): {last_exc}")


def detect_columns(columns: list[str]) -> dict[str, str]:
    """실제 컬럼명 중 어떤 것이 어느 필드에 해당하는지 키워드로 추정합니다.

    반환값: {표준필드명: 실제컬럼명}. 못 찾은 필드는 키에서 빠집니다.
    """
    mapping: dict[str, str] = {}
    for field, keywords in FIELD_KEYWORDS.items():
        for col in columns:
            col_str = str(col)
            if any(kw in col_str for kw in keywords):
                mapping[field] = col
                break
    return mapping


def _make_synthetic_hmc_no(hmc_nm: str, loc_addr: str) -> str:
    """파일데이터는 hmcNo가 없을 수 있어, 이름+주소로 안정적인 고유 ID를 생성합니다.
    API 데이터(hmcNo가 순수 숫자)와 절대 겹치지 않도록 접두어를 붙입니다.
    """
    digest = hashlib.sha1(f"{hmc_nm}|{loc_addr}".encode("utf-8")).hexdigest()[:16]
    return f"FILE_{digest}"


def match_region_by_name(
    si_do_nm: str | None, si_gun_gu_nm: str | None, sido_list: list[dict], sigungu_by_sido: dict
) -> tuple[str | None, str | None]:
    """시도명/시군구명이 명시적으로 주어졌을 때 이름으로 정확히 매칭합니다."""
    si_do_cd = None
    if si_do_nm:
        for sido in sido_list:
            if sido.get("siDoNm") == si_do_nm or si_do_nm in sido.get("siDoNm", ""):
                si_do_cd = sido.get("siDoCd")
                break
    if si_do_cd is None or not si_gun_gu_nm:
        return si_do_cd, None

    for sgg in sigungu_by_sido.get(str(si_do_cd), []):
        if sgg.get("siGunGuNm") == si_gun_gu_nm or si_gun_gu_nm in sgg.get("siGunGuNm", ""):
            return si_do_cd, sgg.get("siGunGuCd")
    return si_do_cd, None


def match_region(address: str, sido_list: list[dict], sigungu_by_sido: dict) -> tuple[str | None, str | None]:
    """주소 텍스트 맨 앞부분에서 시/도, 시/군/구를 문자열 포함 매칭으로 추정합니다.

    sido_list: nhis_api.get_sido_list() 결과
    sigungu_by_sido: {si_do_cd(str): nhis_api.get_sigungu_list(si_do_cd) 결과} 캐시 딕셔너리
    """
    if not address:
        return None, None

    matched_sido = None
    for sido in sido_list:
        nm = sido.get("siDoNm", "")
        # "서울특별시" 뿐 아니라 "서울" 같은 축약형도 대응
        short_nm = nm.replace("특별자치도", "").replace("특별자치시", "").replace("광역시", "").replace("특별시", "").replace("도", "")
        if nm and address.startswith(nm):
            matched_sido = sido
            break
        if short_nm and address.startswith(short_nm):
            matched_sido = sido
            break
    if not matched_sido:
        return None, None

    si_do_cd = matched_sido.get("siDoCd")
    sigungu_list = sigungu_by_sido.get(str(si_do_cd), [])
    for sgg in sigungu_list:
        sgg_nm = sgg.get("siGunGuNm", "")
        if sgg_nm and sgg_nm in address:
            return si_do_cd, sgg.get("siGunGuCd")

    return si_do_cd, None


def build_rows(
    df: pd.DataFrame, sido_list: list[dict], sigungu_by_sido: dict
) -> tuple[list[dict], int, int]:
    """DataFrame을 hmc_database.upsert_items가 기대하는 item(dict) 리스트로 변환합니다.

    기관명/주소만 있는 최소 파일도, 검진종류별 지원여부·위도경도까지 채운
    확장 양식(양식 다운로드 참고)도 모두 지원합니다.

    반환값: (item 리스트, 지역 매칭 성공 건수, 전체 행수)
    """
    col_map = detect_columns(list(df.columns))
    if "hmc_nm" not in col_map or "loc_addr" not in col_map:
        raise FileImportError(
            f"필수 컬럼(기관명, 주소)을 찾지 못했습니다. 실제 컬럼: {list(df.columns)}"
        )

    # 검진종류 컬럼은 정확한 한글 라벨로만 인식 (양식의 헤더와 동일해야 함)
    exam_cols_present = {
        label: label for label in EXAM_TYPE_COLUMN_TO_API_FIELD if label in df.columns
    }

    items: list[dict] = []
    matched_count = 0
    for _, row in df.iterrows():
        hmc_nm = str(row.get(col_map["hmc_nm"], "")).strip()
        loc_addr = str(row.get(col_map.get("loc_addr", ""), "")).strip()
        if not hmc_nm or not loc_addr or hmc_nm == "nan" or loc_addr == "nan":
            continue

        # 1순위: 시도명/시군구명 컬럼이 명시되어 있으면 이름으로 정확히 매칭
        si_do_nm = str(row.get(col_map.get("si_do_nm", ""), "")).strip() or None
        si_gun_gu_nm = str(row.get(col_map.get("si_gun_gu_nm", ""), "")).strip() or None
        if si_do_nm and si_do_nm != "nan":
            si_do_cd, si_gun_gu_cd = match_region_by_name(
                si_do_nm, si_gun_gu_nm, sido_list, sigungu_by_sido
            )
        else:
            # 2순위: 주소 텍스트에서 자동 추정
            si_do_cd, si_gun_gu_cd = match_region(loc_addr, sido_list, sigungu_by_sido)
        if si_do_cd is not None:
            matched_count += 1

        item = {
            "hmcNo": _make_synthetic_hmc_no(hmc_nm, loc_addr),
            "hmcNm": hmc_nm,
            "locAddr": loc_addr,
            "hmcTelNo": str(row.get(col_map.get("hmc_tel_no", ""), "")).strip() or None,
            "ykindnm": str(row.get(col_map.get("ykindnm", ""), "")).strip() or None,
            "siDoCd": si_do_cd,
            "siGunGuCd": si_gun_gu_cd,
        }

        # 위도/경도가 채워져 있으면 그대로 사용 (WGS84 범위 안이면 coord_utils가 변환 없이 통과시킴)
        lat_raw = row.get(col_map.get("lat", ""))
        lng_raw = row.get(col_map.get("lng", ""))
        if pd.notna(lat_raw) and pd.notna(lng_raw):
            item["cyVl"] = str(lat_raw)  # cy = 위도
            item["cxVl"] = str(lng_raw)  # cx = 경도

        # 검진종류별 지원여부 (Y/N 등 -> "1"/"0")
        for label, api_field in EXAM_TYPE_COLUMN_TO_API_FIELD.items():
            if label in exam_cols_present:
                raw_val = str(row.get(label, "")).strip()
                item[api_field] = "1" if raw_val in TRUE_VALUES else "0"

        items.append(item)

    return items, matched_count, len(df)
