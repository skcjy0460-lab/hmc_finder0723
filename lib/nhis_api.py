# -*- coding: utf-8 -*-
"""
국민건강보험공단_검진기관 찾기 조회 API (B550928/HmcSearchService)
국민건강보험공단_국가건강검진기관정보 코드 조회서비스 (B550928/CodeServices)

공식 Swagger 문서 기준으로 작성됨 (2026-07 확인).

⚠️ 확인이 필요한 가정 사항 (README_검진기관찾기_통합가이드.md 참고)
1. 데이터포맷이 포털 메타에는 XML로 표기되어 있으나 Swagger 응답 예시는 JSON 스키마이므로,
   `_type=json` 파라미터를 함께 보내고 실패 시 XML로 자동 폴백합니다.
2. header.resultCode 성공값이 "00"인지 "0000"인지 문서에 명시되어 있지 않아
   SUCCESS_CODES 상수에 자주 쓰이는 값들을 모두 넣어두었습니다. 실제 응답을 받은 뒤
   다르면 이 상수만 수정하면 됩니다.
3. getHmcList는 Swagger상 hmcNm이 필수(required)로 표기되어 있지만, 실제로는 빈 문자열도
   허용하는 공공데이터포털 API가 많습니다. 빈 문자열 호출이 거부되면 지역 조회는
   getRegnHmcList를 기본으로 쓰고 getHmcList는 '기관명 검색 전용'으로만 사용하세요.
   (본 모듈은 이미 그렇게 역할을 분리해서 설계했습니다.)
4. getHolidaysHmcList 파라미터는 Swagger 캡처가 없어 getRegnHmcList와 동일한 패턴
   (serviceKey, siDoCd, siGunGuCd, hmcNm, pageNo, numOfRows)으로 가정했습니다.
   실제 호출 시 400 에러가 나면 이 함수의 params만 실제 스펙에 맞게 수정하면 됩니다.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import requests
import streamlit as st

BASE_HMC = "https://apis.data.go.kr/B550928/HmcSearchService"
BASE_CODE = "https://apis.data.go.kr/B550928/CodeServices"

SUCCESS_CODES = {"00", "0000", "0", "200"}
REQUEST_TIMEOUT = 25
MAX_RETRIES = 2  # 최초 시도 + 1회 재시도


class NhisApiError(Exception):
    """NHIS 검진기관 API 호출/응답 오류"""


def _http_get_with_retry(url: str, params: dict):
    """공공데이터포털 서버가 가끔 느릴 때가 있어 타임아웃 시 1회 재시도합니다."""
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_exc = exc
    raise last_exc  # type: ignore[misc]


def _get_service_key() -> str:
    """secrets.toml 에 저장된 서비스키를 반환합니다.

    .streamlit/secrets.toml 예시:
        NHIS_HMC_SERVICE_KEY = "발급받은_디코딩된_일반인증키"
    """
    key = st.secrets.get("NHIS_HMC_SERVICE_KEY")
    if not key:
        raise NhisApiError(
            "NHIS_HMC_SERVICE_KEY가 secrets.toml에 설정되어 있지 않습니다. "
            "공공데이터포털에서 발급받은 일반 인증키(디코딩 키)를 등록해주세요."
        )
    return key


def _parse_xml(text: str) -> dict:
    """data.go.kr 표준 XML 응답을 dict로 변환 (JSON 파싱 실패 시 폴백용)."""
    root = ET.fromstring(text)

    def node_to_dict(node: ET.Element) -> Any:
        children = list(node)
        if not children:
            return (node.text or "").strip()
        result: dict[str, Any] = {}
        for child in children:
            value = node_to_dict(child)
            if child.tag in result:
                # 동일 태그가 여러 개면 리스트로 누적 (item 여러 건)
                if isinstance(result[child.tag], list):
                    result[child.tag].append(value)
                else:
                    result[child.tag] = [result[child.tag], value]
            else:
                result[child.tag] = value
        return result

    return node_to_dict(root)


def debug_raw_call(base_url: str, operation: str, params: dict) -> dict:
    """진단용: 파싱/검증 없이 실제 HTTP 응답을 그대로 반환합니다.

    시도 목록이 비어있는 등 원인을 알 수 없을 때, 이 함수의 결과를 화면에
    그대로 띄워서 실제 API가 무엇을 반환하는지 확인하는 용도입니다.
    """
    url = f"{base_url}/{operation}"
    query = {"serviceKey": _get_service_key(), "_type": "json"}
    query.update({k: v for k, v in params.items() if v not in (None, "")})

    try:
        resp = _http_get_with_retry(url, query)
    except requests.RequestException as exc:
        return {"status_code": None, "error": str(exc), "text": ""}

    return {
        "status_code": resp.status_code,
        "url": resp.url.split("serviceKey=")[0] + "serviceKey=***",
        "text": resp.text[:2000],
    }


def _request(base_url: str, operation: str, params: dict) -> dict:
    """공통 GET 요청 + JSON/XML 이중 파싱 + resultCode 검증."""
    url = f"{base_url}/{operation}"
    query = {"serviceKey": _get_service_key(), "_type": "json"}
    query.update({k: v for k, v in params.items() if v not in (None, "")})

    try:
        resp = _http_get_with_retry(url, query)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise NhisApiError(f"[{operation}] 네트워크 오류: {exc}") from exc

    text = resp.text.strip()
    parsed: dict
    if text.startswith("{"):
        try:
            parsed = resp.json()
        except ValueError as exc:
            raise NhisApiError(f"[{operation}] JSON 파싱 실패: {exc}\n원문: {text[:300]}") from exc
    else:
        try:
            parsed = _parse_xml(text)
        except ET.ParseError as exc:
            raise NhisApiError(f"[{operation}] XML 파싱 실패: {exc}\n원문: {text[:300]}") from exc

    # 실제 응답이 {"response": {"header":..., "body":...}} 처럼 한 겹 더 감싸져 오는
    # 케이스가 확인되어(2026-07-23), header/body를 찾기 전에 먼저 벗겨냅니다.
    if isinstance(parsed, dict) and "response" in parsed and isinstance(parsed["response"], dict):
        parsed = parsed["response"]

    header = parsed.get("header") or parsed.get("cmmMsgHeader") or {}
    result_code = str(header.get("resultCode", "")).strip()
    if header and result_code not in SUCCESS_CODES:
        msg = header.get("resultMsg", "알 수 없는 오류")
        raise NhisApiError(f"[{operation}] API 오류 (code={result_code}): {msg}")

    return parsed


def _extract_items(parsed: dict) -> tuple[list[dict], int]:
    """body.items.item 을 항상 list[dict] 형태로 정규화하고 totalCount를 함께 반환."""
    body = parsed.get("body") or {}
    items_wrap = body.get("items")
    if not items_wrap:
        return [], int(body.get("totalCount") or 0)

    item = items_wrap.get("item") if isinstance(items_wrap, dict) else items_wrap
    if item is None:
        items = []
    elif isinstance(item, list):
        items = item
    else:
        items = [item]

    total = int(body.get("totalCount") or len(items) or 0)
    return items, total


# ---------------------------------------------------------------------------
# 코드 조회 서비스 (B550928/CodeServices)
# ---------------------------------------------------------------------------

def build_sigungu_full_code(si_do_cd, si_gun_gu_cd) -> str | None:
    """CodeServices가 반환하는 분리형 코드(siDoCd 2자리 + siGunGuCd 3자리)를
    HmcSearchService가 요구하는 것으로 확인된 5자리 결합 행정표준코드로 변환합니다.

    예: siDoCd=27(대구), siGunGuCd=290(달서구) -> "27290"
    (2026-07-23 실제 API 테스트로 확인됨: 분리 코드로 호출 시 totalCount=0)
    """
    if si_do_cd in (None, "") or si_gun_gu_cd in (None, ""):
        return None
    return f"{int(si_do_cd)}{int(si_gun_gu_cd):03d}"


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_sido_list() -> list[dict]:
    """시도 코드 목록"""
    parsed = _request(BASE_CODE, "getSiDoList", {"numOfRows": 100, "pageNo": 1})
    items, _ = _extract_items(parsed)
    return items


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_sigungu_list(si_do_cd: str) -> list[dict]:
    """시군구 코드 목록 (시도코드 하위)"""
    parsed = _request(
        BASE_CODE, "getSiGunGuList", {"siDoCd": si_do_cd, "numOfRows": 200, "pageNo": 1}
    )
    items, _ = _extract_items(parsed)
    return items


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_hchtype_list() -> list[dict]:
    """검진종류 코드 목록"""
    parsed = _request(BASE_CODE, "getHchTypeList", {"numOfRows": 100, "pageNo": 1})
    items, _ = _extract_items(parsed)
    return items


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_medic_inst_list() -> list[dict]:
    """의료기관 구분 코드 목록"""
    parsed = _request(BASE_CODE, "getMedicInstList", {"numOfRows": 100, "pageNo": 1})
    items, _ = _extract_items(parsed)
    return items


# ---------------------------------------------------------------------------
# 검진기관 찾기 조회 서비스 (B550928/HmcSearchService)
# ---------------------------------------------------------------------------

def get_regn_hmc_list_page(
    si_gun_gu_cd: str,
    si_do_cd: str | None = None,
    hmc_nm: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 100,
) -> tuple[list[dict], int]:
    """지역별 검진기관 안내 (siGunGuCd 필수) - 1페이지 조회.

    지역 브라우징의 기본 API. hmcNm 없이도 호출 가능하므로
    시군구 단위 전체 목록을 로컬 DB에 동기화할 때 사용합니다.
    """
    parsed = _request(
        BASE_HMC,
        "getRegnHmcList",
        {
            "siGunGuCd": si_gun_gu_cd,
            "siDoCd": si_do_cd,
            "hmcNm": hmc_nm,
            "pageNo": page_no,
            "numOfRows": num_of_rows,
        },
    )
    return _extract_items(parsed)


def fetch_all_regn_hmc(
    si_gun_gu_cd: str, si_do_cd: str | None = None, page_size: int = 100, max_pages: int = 50
) -> list[dict]:
    """지정 시군구의 검진기관 전체를 페이지네이션하며 모두 가져옵니다."""
    all_items: list[dict] = []
    page_no = 1
    while page_no <= max_pages:
        items, total = get_regn_hmc_list_page(
            si_gun_gu_cd=si_gun_gu_cd, si_do_cd=si_do_cd, page_no=page_no, num_of_rows=page_size
        )
        if not items:
            break
        all_items.extend(items)
        if len(all_items) >= total:
            break
        page_no += 1
    return all_items


def search_hmc_by_name(
    hmc_nm: str,
    si_do_cd: str | None = None,
    si_gun_gu_cd: str | None = None,
    loc_addr: str | None = None,
    hmc_rdat_cd: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 50,
) -> tuple[list[dict], int]:
    """검진기관통합조건검색 (기관명 필수) - 기관명으로 정밀 검색할 때 사용."""
    if not hmc_nm:
        raise NhisApiError("getHmcList는 검진기관명(hmc_nm)이 반드시 필요합니다.")
    parsed = _request(
        BASE_HMC,
        "getHmcList",
        {
            "hmcNm": hmc_nm,
            "siDoCd": si_do_cd,
            "siGunGuCd": si_gun_gu_cd,
            "locAddr": loc_addr,
            "hmcRdatCd": hmc_rdat_cd,
            "pageNo": page_no,
            "numOfRows": num_of_rows,
        },
    )
    return _extract_items(parsed)


def get_hchk_types_hmc_list(
    hch_type: str | None = None, page_no: int = 1, num_of_rows: int = 100
) -> tuple[list[dict], int]:
    """검진종류별 검진기관 안내 (전국구 조회, 검진종류 필터만 적용)"""
    parsed = _request(
        BASE_HMC,
        "getHchkTypesHmcList",
        {"hchType": hch_type, "pageNo": page_no, "numOfRows": num_of_rows},
    )
    return _extract_items(parsed)


def fetch_all_nationwide_hmc(page_size: int = 500, max_pages: int = 200) -> list[dict]:
    """getRegnHmcList의 지역 파라미터가 정상 동작하지 않는 것으로 확인되어(2026-07-23),
    getHchkTypesHmcList(전국조회)로 전체 데이터를 한 번에 가져오는 방식으로 대체합니다.
    각 item에 이미 siDoCd/siGunGuCd가 포함되어 있어 로컬에서 지역 필터링이 가능합니다.
    """
    all_items: list[dict] = []
    page_no = 1
    while page_no <= max_pages:
        items, total = get_hchk_types_hmc_list(page_no=page_no, num_of_rows=page_size)
        if not items:
            break
        all_items.extend(items)
        if len(all_items) >= total:
            break
        page_no += 1
    return all_items


def get_holidays_hmc_list(
    si_do_cd: str | None = None,
    si_gun_gu_cd: str | None = None,
    hmc_nm: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 100,
) -> tuple[list[dict], int]:
    """공휴일 검진기관 안내

    ⚠️ 파라미터명은 getRegnHmcList와 동일할 것으로 가정한 것입니다.
    실제 400 에러가 발생하면 Swagger에서 정확한 파라미터를 확인해 수정하세요.
    """
    parsed = _request(
        BASE_HMC,
        "getHolidaysHmcList",
        {
            "siDoCd": si_do_cd,
            "siGunGuCd": si_gun_gu_cd,
            "hmcNm": hmc_nm,
            "pageNo": page_no,
            "numOfRows": num_of_rows,
        },
    )
    return _extract_items(parsed)
