# 국가건강검진기관 찾기

국민건강보험공단 공공데이터(검진기관 찾기 API, B550928)를 활용해
지역별 국가건강검진기관을 검색하고 AI 맞춤 추천을 받는 Streamlit 앱입니다.

## 폴더 구조

```
.
├── Home.py                     # ⭐ 메인 진입점 (Streamlit Cloud Main file path)
├── views/
│   ├── home.py                 # 홈 화면
│   └── hmc_finder.py           # 검색/동기화/AI추천 화면
├── lib/
│   ├── __init__.py
│   ├── nhis_api.py             # 공공데이터포털 API 클라이언트
│   ├── coord_utils.py          # 좌표 변환
│   ├── hmc_database.py         # SQLite 로컬 캐시 + 엑셀 다운로드
│   └── ai_features.py          # Gemini AI 추천 / 체크리스트
├── data/                       # 최초 실행 시 hmc_cache.db 자동 생성 (git 제외)
├── .streamlit/
│   └── secrets.toml.example    # secrets.toml 만들 때 참고용
├── requirements.txt
└── .gitignore
```

> **왜 파일명이 전부 영문인가요?** zip 압축/해제나 git clone 과정에서 한글 파일명이
> 깨지는(mojibake) 문제를 원천적으로 피하기 위해서입니다. 대신 사이드바에 보이는
> 한글 메뉴 이름은 `Home.py`에서 아래처럼 `st.navigation`으로 지정합니다:
>
> ```python
> home_page = st.Page("views/home.py", title="홈", icon="🏠", default=True)
> hmc_page = st.Page("views/hmc_finder.py", title="검진기관 찾기", icon="🏥")
> pg = st.navigation([home_page, hmc_page])
> pg.run()
> ```
>
> 나중에 페이지를 추가하실 때도 파일명은 영문으로 만들고 `title=`만 원하는
> 한글로 지정하시면 됩니다. (`st.navigation`/`st.Page`는 streamlit 1.36 이상 필요 —
> `requirements.txt`에 이미 반영되어 있습니다.)

## 1. GitHub에 새 저장소로 올리기

1. GitHub에서 새 저장소 생성 (예: `hmc-finder`)
2. 저장소 웹 UI의 **"Add file → Upload files"**로 위 폴더 구조 그대로 드래그 앤 드롭
   - `.streamlit/secrets.toml.example`은 올려도 안전합니다 (실제 키가 아닌 예시 파일)
   - `data/` 폴더는 비어있어도 되고 안 올려도 됩니다 (실행 시 자동 생성)
3. Commit

## 2. Streamlit Cloud 배포

1. [share.streamlit.io](https://share.streamlit.io) → **New app**
2. 방금 만든 GitHub 저장소 선택
3. **Main file path**: `Home.py` ⭐ (이게 이번 질문의 "메인"입니다)
4. **Advanced settings → Secrets**에 아래 내용 입력 (실제 키로 교체):

```toml
NHIS_HMC_SERVICE_KEY = "공공데이터포털 일반인증키(디코딩)"
GEMINI_API_KEY = "Gemini API 키"
```

5. **Deploy** 클릭

## 3. 배포 후 확인 순서

1. 사이드바에서 "검진기관 찾기" 페이지 진입
2. 시/도 → 시/군/구 선택
3. "데이터 동기화" 버튼 클릭 (해당 지역 API 최초 1회 호출)
4. 검색 결과 표 + 지도 확인
5. AI 맞춤 추천, 체크리스트 생성 테스트

## 4. 배포 전 실제로 검증해야 하는 가정 3가지

Swagger 문서만으로는 확정할 수 없었던 부분이라, 위 3번 과정에서 직접 확인 후
필요하면 코드 한 줄만 고치면 됩니다.

| # | 가정 | 확인 방법 | 틀렸을 때 수정할 곳 |
|---|------|-----------|---------------------|
| 1 | 좌표계가 EPSG:5174(TM) | 동기화 후 지도 핀이 실제 주소와 맞는지 확인 | `lib/coord_utils.py`의 `DEFAULT_SOURCE_EPSG` (5179, 5181 등으로 교체) |
| 2 | 검진 가능여부 코드값이 "1"/"Y" 계열 | `df["gren_chrg_type_cd"].unique()`로 실제 값 확인 | `lib/hmc_database.py`의 `CHRG_AVAILABLE_VALUES` |
| 3 | `getHolidaysHmcList` 파라미터가 `getRegnHmcList`와 동일 | 호출 시 400 에러 여부 확인 (현재 UI에는 미연결, API 함수만 존재) | `lib/nhis_api.py`의 `get_holidays_hmc_list()` |

이 3가지 외의 API 호출(코드 조회 4종 + getRegnHmcList + getHmcList)은
캡처해주신 Swagger 스펙 그대로 정확히 매핑했습니다.

## 5. 설계 포인트

- **트래픽 절약**: 개발계정 일일 트래픽 10,000건을 아끼기 위해, 시군구 단위로
  "동기화" 버튼을 누를 때만 API를 호출하고 전체를 SQLite에 저장합니다.
  이후 검색·필터는 전부 로컬 DB에서 처리됩니다.
- **getRegnHmcList vs getHmcList**: `getHmcList`는 기관명이 필수라 지역 브라우징에
  안 맞아서, 전체 조회는 시군구코드만 필수인 `getRegnHmcList`로 하고 `getHmcList`는
  기관명 정밀검색용 함수(`nhis_api.search_hmc_by_name`)로 따로 빼두었습니다.
- **AI 기능**: 의학적 판단(진단, 검사 필요성)은 하지 않고 행정적/절차적 안내로만
  범위를 한정한 프롬프트로 설계했습니다.

## 6. 로컬 테스트

```bash
git clone <저장소 URL>
cd hmc-finder
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# secrets.toml에 실제 키 입력 후
streamlit run Home.py
```

---
배포 후 에러 메시지가 뜨면 어느 단계(동기화/검색/AI추천)에서 어떤 메시지가
나왔는지 알려주시면 바로 원인 파악해서 고쳐드리겠습니다.
