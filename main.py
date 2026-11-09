# -*- coding: utf-8 -*-
"""
정치 한 걸음
Streamlit 메인 앱

필수 저장소 파일
- main.py
- Quiz.txt
- NEWS.txt
- requirements.txt

Streamlit Community Cloud > App settings > Secrets
[API_KEYS]
OPENASSEMBLY_KEY = "열린국회정보 인증키"
DATA_GO_KR_KEY = "공공데이터포털 일반 인증키(Decoding 키 권장)"
KOSIS_KEY = "KOSIS 인증키"
VWORLD_KEY = "브이월드 인증키"

[APP]
VWORLD_DOMAIN = "https://실제-배포된-앱-주소"

선택 설정(정확한 상세 요청 주소를 알게 된 API부터 추가)
[API_URLS]
ASSEMBLY_SCHEDULE = "국회일정 통합 API 상세 요청 주소"
MOIS_BENEFIT = "공공서비스 API 상세 요청 주소"
MOIS_COUNCIL_SEATS = "지방의회의원 정수 API 상세 요청 주소"
MOIS_POPULATION = "행정동 인구 API 상세 요청 주소"

[API_CODES]
ASSEMBLY_SCHEDULE = "국회일정 통합 API 코드"

주의:
- 인증키는 코드에 넣지 않습니다.
- 알려지지 않은 상세 요청 주소나 필수 검색 변수를 임의로 만들어 호출하지 않습니다.
- API 응답 실패는 해당 자료 영역에만 표시하고 앱 전체는 계속 작동합니다.
"""

from __future__ import annotations

import calendar
import html
import json
import random
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

try:
    import feedparser
except ImportError:  # requirements.txt에 포함되어 있으나, 최소 XML 대체 파서도 제공합니다.
    feedparser = None

import pandas as pd
import requests
import streamlit as st

try:
    import folium
    from streamlit_folium import st_folium
    HAS_MAP = True
except ImportError:
    folium = None
    st_folium = None
    HAS_MAP = False


# ============================================================
# 1. 페이지 설정 / 공통 디자인
# ============================================================

st.set_page_config(
    page_title="정치 한 걸음",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).resolve().parent
QUIZ_PATH = BASE_DIR / "Quiz.txt"
NEWS_PATH = BASE_DIR / "NEWS.txt"
KST = ZoneInfo("Asia/Seoul")

def korea_now() -> datetime:
    """Streamlit 서버 시간대와 무관하게 한국 표준시를 사용합니다."""
    return datetime.now(KST)

def korea_today() -> date:
    return korea_now().date()

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] {font-family:'Noto Sans KR', sans-serif;}
    .block-container {padding-top:1.05rem; padding-bottom:2.2rem; max-width:1280px;}
    .app-header {padding:.8rem .35rem 1rem .35rem; margin-bottom:.3rem;}
    .app-header h1 {font-size:1.8rem; line-height:1.3; margin:0 0 .2rem 0; font-weight:800; color:var(--text-color);}
    .app-header p {font-size:1rem; margin:0; color:var(--secondary-text-color);}
    .hero {padding:.15rem 0 .85rem 0; color:var(--text-color); margin-bottom:.4rem; border-bottom:1px solid var(--border-color, #dedede);}
    .hero h1 {font-size:1.55rem; line-height:1.35; margin:0 0 .2rem 0; font-weight:800; color:var(--text-color);}
    .hero p {font-size:.94rem; margin:0; color:var(--secondary-text-color);}
    .section-title {font-size:1.12rem; font-weight:800; margin:.3rem 0 .65rem;}
    .muted {color:var(--secondary-text-color); font-size:.86rem;}
    .quiz-panel {border:1px solid var(--border-color, #dedede); border-radius:16px; padding:1rem 1.05rem; background:var(--secondary-background-color);}
    .api-card {border:1px solid var(--border-color, #dedede); border-radius:14px; padding:.9rem; min-height:130px; background:var(--secondary-background-color);}
    .api-card-title {font-weight:800; font-size:1rem; margin:.25rem 0;}
    .api-card-desc {color:var(--secondary-text-color); font-size:.84rem; line-height:1.5;}
    .news-card {border:1px solid var(--border-color, #dedede); border-radius:12px; padding:.72rem .85rem; margin:.4rem 0; background:var(--secondary-background-color);}
    .news-title {font-weight:700; line-height:1.5; margin:.2rem 0;}
    .news-meta {font-size:.78rem; color:var(--secondary-text-color); margin-bottom:.35rem;}
    .news-summary {font-size:.88rem; line-height:1.55;}
    .org-node {border:1px solid var(--border-color, #dedede); border-radius:12px; padding:.9rem; text-align:center; background:var(--secondary-background-color); margin:.25rem 0;}
    .org-node strong {font-size:1rem;}
    .org-node small {color:var(--secondary-text-color);}
    div[data-testid="stVerticalBlock"] {gap:.55rem;}
    div[data-testid="stMetric"] {border:1px solid var(--border-color, #dedede); border-radius:12px; padding:.7rem;}
    div[data-testid="stSidebar"] {min-width:250px;}
    .tiny-note {font-size:.82rem; color:var(--secondary-text-color);}
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# 2. 설정 / 비밀키 / HTTP / 데이터 형식 통일
# ============================================================

def get_secret(section: str, key: str, default: str = "") -> str:
    """TOML 중첩 섹션과 평면 키를 모두 읽고, 빈 값은 기본값으로 처리합니다."""
    try:
        section_data = st.secrets.get(section, {})
        if hasattr(section_data, "get"):
            value = section_data.get(key, default)
            if value is not None and str(value).strip():
                return str(value).strip()
    except Exception:
        pass
    try:
        value = st.secrets.get(key, default)
        return str(value).strip() if value is not None else default
    except Exception:
        return default


def _is_placeholder(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return True
    markers = ("인증키", "실제-배포", "실제 도메인", "상세 요청 주소", "api 코드", "<", ">", "placeholder")
    return any(marker in text for marker in markers)


def api_key(key_name: str) -> str:
    value = get_secret("API_KEYS", key_name)
    return "" if _is_placeholder(value) else value


def api_url(url_name: str, default: str = "") -> str:
    value = get_secret("API_URLS", url_name, default)
    if _is_placeholder(value):
        return ""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return ""
    return value


def api_code(code_name: str, default: str = "") -> str:
    value = get_secret("API_CODES", code_name, default)
    return "" if _is_placeholder(value) else value


def safe_string(value, fallback="정보 없음") -> str:
    if value is None:
        return fallback
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value if value else fallback


def is_safe_http_url(value: str) -> bool:
    """외부 링크는 사용자 정보가 없는 정상 HTTP(S) 주소만 허용합니다."""
    try:
        url = str(value or "").strip()
        if any(char in url for char in ("\r", "\n", "\t")):
            return False
        parsed = urlsplit(url)
        return (
            parsed.scheme.lower() in ("http", "https")
            and bool(parsed.netloc)
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def xml_element_to_value(element):
    children = list(element)
    if not children:
        return (element.text or "").strip()
    result = {}
    for child in children:
        # 네임스페이스가 붙은 XML 태그도 필드명으로 일관되게 사용합니다.
        tag = child.tag.split("}")[-1]
        value = xml_element_to_value(child)
        if tag in result:
            if not isinstance(result[tag], list):
                result[tag] = [result[tag]]
            result[tag].append(value)
        else:
            result[tag] = value
    return result


def parse_payload(response: requests.Response):
    body = response.text.strip()
    if not body:
        return None
    content_type = response.headers.get("Content-Type", "").lower()
    body_lower = body[:300].lower()
    if "text/html" in content_type or body_lower.startswith(("<!doctype html", "<html")):
        return {"원문": body[:4000]}
    if "json" in content_type or body[:1] in ("{", "["):
        try:
            return response.json()
        except ValueError:
            pass
    try:
        return xml_element_to_value(ET.fromstring(body))
    except ET.ParseError:
        return {"원문": body[:4000]}


def find_rows(node):
    """API별 JSON/XML 래퍼 안에서 여러 건 또는 단일 건의 레코드를 찾습니다."""
    if isinstance(node, list):
        if node and all(isinstance(x, dict) for x in node):
            return node
        for child in node:
            rows = find_rows(child)
            if rows:
                return rows
    elif isinstance(node, dict):
        # 대소문자·XML 네임스페이스 차이를 흡수합니다.
        key_map = {str(key).split("}")[-1].lower(): key for key in node}
        preferred = ("row", "item", "items", "list", "records", "data", "result")
        for name in preferred:
            original_key = key_map.get(name)
            if original_key is None:
                continue
            value = node[original_key]
            if name in ("row", "item") and isinstance(value, dict):
                # 공공데이터 XML은 결과가 한 건일 때 item/row가 배열이 아닌 객체입니다.
                if not any(str(k).lower() in ("header", "body", "response", "totalcount") for k in value):
                    return [value]
            rows = find_rows(value)
            if rows:
                return rows
        for value in node.values():
            rows = find_rows(value)
            if rows:
                return rows
    return []

def inspect_api_error(payload):
    """HTTP 200으로 반환되는 공공데이터·열린국회정보 자체 오류를 감지합니다."""
    text = json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    known = {
        "SERVICE_KEY_IS_NULL": "인증키가 요청에 포함되지 않았습니다.",
        "SERVICE_ACCESS_DENIED_ERROR": "해당 API의 이용 권한을 확인할 수 없습니다.",
        "SERVICE_KEY_IS_NOT_REGISTERED_ERROR": "등록되지 않은 인증키입니다.",
        "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR": "일일 호출 한도를 초과했습니다.",
        "LIMITED_NUMBER_OF_SERVICE_REQUESTS_PER_SECOND_EXCEEDS_ERROR": "초당 호출 한도를 초과했습니다.",
        "INVALID_REQUEST_PARAMETER_ERROR": "요청 변수의 이름 또는 값이 올바르지 않습니다.",
        "NO_OPENAPI_SERVICE_ERROR": "요청한 API 기능을 찾을 수 없습니다.",
        "DEADLINE_HAS_EXPIRED_ERROR": "인증키의 이용기간이 만료되었습니다.",
        "INFO-100": "열린국회정보 인증키가 누락되었습니다.",
        "INFO-200": "열린국회정보 인증키가 올바르지 않습니다.",
        "INFO-300": "열린국회정보 호출 한도를 초과했습니다.",
        "DATA-000": "조회 결과가 없습니다.",
    }
    upper_text = text.upper()
    for code, message in known.items():
        if code.upper() in upper_text:
            # DATA-000은 오류가 아니라 정상적인 무조회 결과일 수 있으므로 상위 호출부에서 빈 결과로 처리합니다.
            if code == "DATA-000":
                return
            raise RuntimeError(f"{message} ({code})")

    if isinstance(payload, dict):
        # ODCloud 계열은 오류 시 {code: 음수, msg: ...} 형태를 사용할 수 있습니다.
        if "code" in payload:
            try:
                if int(payload.get("code")) < 0:
                    raise RuntimeError("API 인증 또는 요청 조건 오류가 발생했습니다. 인증키와 요청 변수를 확인해 주세요.")
            except (TypeError, ValueError):
                pass
        # data.go.kr의 일부 응답은 resultCode/resultMsg를 사용하고, 다른 API는 RESULT.CODE를 사용합니다.
        flattened = json.dumps(payload, ensure_ascii=False).upper()
        has_error_marker = any(token in flattened for token in ("ERROR", "FAIL", "INVALID", "DENIED"))
        has_message_field = any(token in flattened for token in ("RESULTMSG", "RETURNAUTHMSG", "RESULT_MSG", "MESSAGE"))
        if has_error_marker and has_message_field:
            raise RuntimeError("API 서버가 오류 응답을 반환했습니다. 요청 변수와 이용 권한을 확인해 주세요.")


def safe_exception_category(exc: Exception) -> str:
    """예외 메시지에 요청 URL·쿼리 인증키가 포함될 수 있어 예외 종류만 반환합니다."""
    if isinstance(exc, requests.Timeout):
        return "응답 시간 초과"
    if isinstance(exc, requests.HTTPError):
        return "HTTP 상태 오류"
    if isinstance(exc, requests.ConnectionError):
        return "서버 연결 오류"
    if isinstance(exc, requests.RequestException):
        return "네트워크 요청 오류"
    return "응답 형식 또는 처리 오류"


@st.cache_data(ttl=300, show_spinner=False)
def http_get_json_or_xml(url: str, params_serialized: str, timeout: int = 18):
    """API 응답의 파싱 결과와 원문을 함께 보존합니다."""
    params = json.loads(params_serialized)
    response = requests.get(
        url,
        params=params,
        timeout=(5, timeout),
        headers={"User-Agent": "PoliticsOneStep/1.0"},
        allow_redirects=False,
    )
    response.raise_for_status()
    if 300 <= response.status_code < 400:
        # 인증키가 포함된 요청을 다른 호스트/프로토콜로 전달하지 않습니다.
        raise RuntimeError("인증정보가 포함된 API 요청의 리디렉션은 자동으로 따라가지 않습니다.")
    if len(response.content) > 15_000_000:
        raise RuntimeError("API 응답이 15MB를 초과하여 안전하게 처리하지 않았습니다.")
    raw_text = response.text
    payload = parse_payload(response)
    inspect_api_error(payload)
    return {
        "payload": payload,
        "raw_text": raw_text,
        "content_type": response.headers.get("Content-Type", ""),
    }


def call_api(label: str, url: str, params: dict, timeout: int = 18):
    if not url:
        return [], f"{label}: 상세 요청 주소가 아직 연결되지 않았습니다. 공식 활용가이드의 요청 주소가 필요합니다."
    parsed_url = urlsplit(url)
    if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.username or parsed_url.password:
        return [], f"{label}: 인증정보 보호를 위해 사용자 정보가 없는 HTTPS 요청 주소만 허용합니다."

    # 이전 조회 결과가 실패한 요청의 결과처럼 남지 않도록 먼저 초기화합니다.
    st.session_state["api_last_raw_text"] = ""
    st.session_state["api_last_raw_content_type"] = ""
    st.session_state["api_last_raw_label"] = label
    try:
        result = http_get_json_or_xml(url, json.dumps(params, ensure_ascii=False), timeout)
        payload = result.get("payload")
        st.session_state["api_last_raw_text"] = result.get("raw_text", "")
        st.session_state["api_last_raw_content_type"] = result.get("content_type", "")

        if isinstance(payload, dict) and set(payload.keys()) == {"원문"}:
            raw = str(payload.get("원문", ""))
            if raw.lstrip().startswith(("<html", "<!doctype html", "{", "[")):
                return [], f"{label}: API가 JSON/XML 자료 대신 웹페이지 또는 해석할 수 없는 응답을 반환했습니다. 요청 주소와 응답 형식을 확인해 주세요."

        rows = find_rows(payload)
        if not rows and isinstance(payload, dict):
            # 오류 래퍼·메시지 객체를 일반 데이터 행으로 오인하지 않습니다.
            normalized_keys = {str(k).lower() for k in payload}
            wrapper_keys = {
                "cmmmsgheader", "header", "response", "resultcode", "resultmsg", "원문",
                "data", "items", "item", "row", "records", "totalcount", "currentcount",
                "matchcount", "page", "perpage", "code", "msg", "error",
            }
            if not normalized_keys.intersection(wrapper_keys):
                rows = [payload]
        if not rows:
            return [], f"{label}: 서버 응답은 받았지만 표시할 데이터가 없습니다. 검색 조건·기준시점·페이지를 확인해 주세요."
        return rows, ""
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "알 수 없음"
        return [], f"{label}: 서버가 HTTP {status} 오류를 반환했습니다. 요청 주소와 API 서버 상태를 확인해 주세요."
    except Exception as exc:
        # 예외 문자열에는 URL 쿼리(서비스키)가 포함될 수 있으므로 그대로 화면에 표시하지 않습니다.
        return [], f"{label}: {safe_exception_category(exc)}가 발생했습니다. 활용가이드의 요청 변수·인증키·서버 상태를 확인해 주세요."


def _spreadsheet_safe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """CSV/Excel 수식 주입을 막기 위해 위험한 문자열 셀 앞에 작은따옴표를 붙입니다."""
    safe = frame.copy()
    dangerous_prefixes = ("=", "+", "-", "@", "\t", "\r")
    for column in safe.columns:
        safe[column] = safe[column].map(
            lambda value: "'" + value if isinstance(value, str) and value.lstrip().startswith(dangerous_prefixes) else value
        )
    return safe


def table_view(rows, max_rows=200, search_key=None):
    if not rows:
        st.info("표시할 데이터가 없습니다.")
        return
    frame = pd.json_normalize(rows).head(max_rows)
    base_columns = [str(col).split(".")[-1] for col in frame.columns]
    seen_columns = {}
    unique_columns = []
    for column in base_columns:
        seen_columns[column] = seen_columns.get(column, 0) + 1
        unique_columns.append(column if seen_columns[column] == 1 else f"{column}_{seen_columns[column]}")
    frame.columns = unique_columns

    if search_key:
        query = st.text_input("항목 검색", key=search_key, placeholder="표 안에서 찾을 단어를 입력하세요.")
        if query.strip():
            mask = frame.astype(str).apply(lambda col: col.str.contains(re.escape(query.strip()), case=False, na=False)).any(axis=1)
            frame = frame.loc[mask]
    st.caption(f"표시 행 수: {len(frame):,}개" if len(frame) else "검색 결과가 없습니다.")
    st.dataframe(frame, use_container_width=True, hide_index=True, height=min(520, 52 + 36 * min(len(frame), 12)))

    export_frame = _spreadsheet_safe_frame(frame)
    c1, c2 = st.columns(2)
    with c1:
        csv_bytes = export_frame.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "CSV 다운로드",
            data=csv_bytes,
            file_name="정치한걸음_공공자료.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c2:
        try:
            buffer = BytesIO()
            export_frame.to_excel(buffer, index=False, engine="openpyxl")
            st.download_button(
                "엑셀 다운로드",
                data=buffer.getvalue(),
                file_name="정치한걸음_공공자료.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        except Exception:
            st.caption("엑셀 생성에 실패했습니다. requirements.txt의 openpyxl 설치 여부를 확인해 주세요.")


def first_field(row: dict, keys, default=""):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return safe_string(value, default)
    return default


# ============================================================
# 3. Quiz.txt: 사람이 수정하기 쉬운 형식 → 딕셔너리
# ============================================================

SAMPLE_QUIZ_TEXT = """# 정치 한 걸음 Quiz.txt
# 한 문제를 [문제]부터 --- 전까지 작성합니다.
# 선택지는 | 로 구분하며, 정답은 선택지 번호(1부터 시작)입니다.
# 분야는 정치교과 / 통합사회 등을 사용하세요.

[문제]
분야: 정치 제도
문제: 대한민국에서 법률을 제정하는 국가기관은 어디인가?
선택지: 정부|국회|법원|헌법재판소
정답: 2
해설: 국회는 국민의 대표기관이자 입법기관으로서 법률을 제정합니다.
난이도: 쉬움
태그: 국회,입법부

---
[문제]
분야: 국회
문제: 대한민국 국회의원의 임기는 몇 년인가?
선택지: 2년|4년|5년|6년
정답: 2
해설: 국회의원의 임기는 4년입니다.
난이도: 쉬움
태그: 국회의원,임기

---
[문제]
분야: 행정부
문제: 국무회의의 의장은 누구인가?
선택지: 대통령|국무총리|국회의장|대법원장
정답: 1
해설: 국무회의의 의장은 대통령이며, 국무총리는 부의장입니다.
난이도: 쉬움
태그: 국무회의,대통령

---
[문제]
분야: 권력분립
문제: 국가 권력을 입법·행정·사법으로 나누어 서로 견제하게 하는 원리는?
선택지: 국민주권|권력분립|지방자치|법치주의
정답: 2
해설: 권력분립은 국가 권력이 한 기관에 집중되는 것을 방지합니다.
난이도: 보통
태그: 권력분립,국가권력

---
[문제]
분야: 통합사회
문제: 인간다운 생활을 위해 국가에 일정한 급부와 제도 마련을 요구할 수 있는 권리는?
선택지: 자유권|참정권|사회권|청구권
정답: 3
해설: 사회권은 교육·근로·사회보장 등 인간다운 생활을 보장받기 위한 권리입니다.
난이도: 보통
태그: 기본권,사회권

---
[문제]
분야: 지방자치
문제: 지역 주민이 지역의 일을 스스로 결정하고 처리하는 제도는?
선택지: 지방자치|권력융합|사법심사|관료제
정답: 1
해설: 지방자치는 주민의 참여를 바탕으로 지역의 자율성을 보장합니다.
난이도: 쉬움
태그: 지방자치,주민참여

---
[문제]
분야: 선거
문제: 민주주의에서 선거가 수행하는 가장 핵심적인 기능은?
선택지: 법률 해석|대표자 선출과 정치적 의사 표현|재판 진행|행정명령 발령
정답: 2
해설: 선거는 국민이 대표자를 선출하고 정치적 의사를 표현하는 핵심적인 정치 참여 방식입니다.
난이도: 쉬움
태그: 선거,민주주의
"""


def parse_quiz_file_detailed(raw_text: str):
    """문제 데이터를 읽고 누락·중복·정답 오류를 함께 진단합니다."""
    questions = []
    issues = []
    blocks = [block for block in re.split(r"(?m)^\s*---+\s*$", raw_text) if "[문제]" in block]
    seen_questions = set()

    for block_number, block in enumerate(blocks, 1):
        fields = {}
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line == "[문제]":
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()

        question = fields.get("문제", "").strip()
        options = [x.strip() for x in fields.get("선택지", "").split("|") if x.strip()]
        try:
            answer = int(fields.get("정답", "0"))
        except ValueError:
            answer = 0

        reasons = []
        if not question:
            reasons.append("문제 내용이 비어 있음")
        if len(options) < 2:
            reasons.append("선택지가 2개 미만")
        if len(set(options)) != len(options):
            reasons.append("중복 선택지가 있음")
        if not 1 <= answer <= len(options):
            reasons.append("정답 번호가 선택지 범위를 벗어남")
        if question and question in seen_questions:
            reasons.append("중복 문제")

        if reasons:
            issues.append(f"{block_number}번째 문제: " + ", ".join(reasons))
            continue

        seen_questions.add(question)
        questions.append({
            "분야": fields.get("분야", "정치교과"),
            "문제": question,
            "선택지": options,
            "정답": answer,
            "해설": fields.get("해설", "해설이 등록되지 않았습니다."),
            "난이도": fields.get("난이도", "보통"),
            "태그": [x.strip() for x in fields.get("태그", "").split(",") if x.strip()],
            "출처": "Quiz.txt",
        })

    if not blocks:
        issues.append("[문제] 형식의 문제 블록을 찾지 못했습니다.")
    return questions, issues


def parse_quiz_file(raw_text: str):
    """기존 호출부 호환용: 유효한 문제 목록만 반환합니다."""
    questions, _ = parse_quiz_file_detailed(raw_text)
    return questions


@st.cache_data(show_spinner=False)
def load_quiz_file(modified_at: float):
    if not QUIZ_PATH.exists():
        questions, issues = parse_quiz_file_detailed(SAMPLE_QUIZ_TEXT)
        return questions, False, issues
    try:
        questions, issues = parse_quiz_file_detailed(QUIZ_PATH.read_text(encoding="utf-8"))
        return questions, True, issues
    except Exception:
        questions, issues = parse_quiz_file_detailed(SAMPLE_QUIZ_TEXT)
        return questions, False, ["Quiz.txt를 UTF-8로 읽지 못해 내장 예시 문제를 사용합니다."] + issues


# ============================================================
# 4. NEWS.txt: 등록된 RSS 주소만 불러오기
# ============================================================

SAMPLE_NEWS_TEXT = """# 형식: 국내|언론사|RSS주소 또는 국제|언론사|RSS주소
# 아래 13개 주소만 기본 등록되어 있습니다. 새 RSS를 추가할 때만 직접 줄을 추가하세요.
국내|KBS 세계|http://world.kbs.co.kr/rss/rss_news.htm?lang=k
국내|KBS 뉴스|https://news.kbs.co.kr/rss/news.xml
국내|연합뉴스 정치|https://www.yna.co.kr/rss/politics.xml
국제|연합뉴스 국제|https://www.yna.co.kr/rss/international.xml
국내|연합뉴스 종합|https://www.yna.co.kr/rss/news.xml
국제|BBC World|http://feeds.bbci.co.uk/news/world/rss.xml
국제|BBC Politics|http://feeds.bbci.co.uk/news/politics/rss.xml
국제|CNN World|http://rss.cnn.com/rss/edition_world.rss
국제|CNN Politics|http://rss.cnn.com/rss/cnn_allpolitics.rss
국제|Reuters World|https://www.reuters.com/arc/outboundfeeds/rss/world/
국제|AP|https://feedx.net/rss/ap.xml
국제|AFP|https://www.afp.com/en/actus/afp_communique/all/feed
국제|France24·AFP|https://www.france24.com/en/rss
"""


def parse_news_sources(raw_text: str):
    sources = []
    issues = []
    seen_urls = set()
    for line_number, line in enumerate(raw_text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|", 2)]
        if len(parts) != 3:
            issues.append(f"{line_number}행: 형식 오류(국내/국제|언론사|RSS 주소 필요)")
            continue
        region, publisher, url = parts
        if region not in ("국내", "국제") or not publisher:
            issues.append(f"{line_number}행: 지역 구분 또는 언론사명이 올바르지 않습니다.")
            continue
        if not is_safe_http_url(url):
            issues.append(f"{line_number}행: RSS 주소 형식이 올바르지 않습니다.")
            continue
        if url in seen_urls:
            issues.append(f"{line_number}행: 중복 RSS 주소를 제외했습니다.")
            continue
        seen_urls.add(url)
        sources.append({"region": region, "publisher": publisher, "url": url})
    if not sources:
        issues.append("사용 가능한 RSS 주소가 없습니다. NEWS.txt의 형식을 확인해 주세요.")
    return sources, issues


def load_news_sources_with_issues():
    if not NEWS_PATH.exists():
        return parse_news_sources(SAMPLE_NEWS_TEXT)
    try:
        return parse_news_sources(NEWS_PATH.read_text(encoding="utf-8"))
    except Exception:
        sources, issues = parse_news_sources(SAMPLE_NEWS_TEXT)
        return sources, ["NEWS.txt를 UTF-8로 읽지 못해 기본 RSS 목록을 사용합니다."] + issues


def load_news_sources():
    """기존 호출부 호환용: 유효한 RSS 목록만 반환합니다."""
    sources, _ = load_news_sources_with_issues()
    return sources


def _rss_entries_without_feedparser(content: bytes):
    """feedparser가 없는 실행환경에서도 RSS 2.0과 Atom을 최소한 표시합니다."""
    root = ET.fromstring(content)
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{*}entry")
    parsed = []
    for item in items:
        fields = {}
        for child in list(item):
            tag = child.tag.split("}")[-1].lower()
            if tag == "link" and child.attrib.get("href"):
                value = child.attrib.get("href", "")
            else:
                value = " ".join(child.itertext()).strip()
            fields[tag] = value
        parsed.append(fields)
    return parsed


@st.cache_data(ttl=300, show_spinner=False)
def fetch_rss_items(url: str):
    """외부 RSS 요청에 명시적인 시간제한을 두어 한 피드가 전체 화면을 멈추지 않게 합니다."""
    response = requests.get(
        url,
        timeout=(5, 10),
        headers={"User-Agent": "Mozilla/5.0 PoliticsOneStep/1.0", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"},
    )
    response.raise_for_status()
    if len(response.content) > 5_000_000:
        raise RuntimeError("RSS 응답이 5MB를 초과하여 안전하게 처리하지 않았습니다.")

    if feedparser is not None:
        feed = feedparser.parse(response.content)
        if getattr(feed, "bozo", False) and not feed.entries:
            raise RuntimeError(str(getattr(feed, "bozo_exception", "RSS 응답을 읽지 못했습니다.")))
        entries = list(feed.entries[:30])
    else:
        entries = _rss_entries_without_feedparser(response.content)[:30]

    articles = []
    for entry in entries:
        get_value = entry.get if hasattr(entry, "get") else lambda key, default="": default
        summary = get_value("summary", "") or get_value("description", "") or get_value("content", "") or ""
        if isinstance(summary, list):
            summary = " ".join(str(x.get("value", "")) for x in summary if isinstance(x, dict))
        summary = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", str(summary))
        summary = re.sub(r"<[^>]*>", " ", summary)
        summary = html.unescape(re.sub(r"\s+", " ", summary)).strip()
        published = get_value("published", "") or get_value("updated", "") or get_value("pubdate", "")
        timestamp = 0
        parsed_time = get_value("published_parsed", None) or get_value("updated_parsed", None)
        if parsed_time:
            try:
                timestamp = int(calendar.timegm(parsed_time))
            except Exception:
                timestamp = 0
        if not timestamp and published:
            try:
                parsed_date = parsedate_to_datetime(str(published))
                if parsed_date.tzinfo is None:
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                timestamp = int(parsed_date.timestamp())
            except Exception:
                timestamp = 0
        link_value = get_value("link", "")
        if not link_value and hasattr(entry, "get"):
            links = entry.get("links", []) or []
            if links and isinstance(links[0], dict):
                link_value = links[0].get("href", "")
        articles.append({
            "title": safe_string(get_value("title", ""), "제목 없음"),
            "link": str(link_value or "").strip(),
            "summary": summary[:460],
            "published": safe_string(published, "날짜 정보 없음"),
            "published_timestamp": timestamp,
        })
    return articles


def collect_all_news():
    """국내·국제 피드를 한 번에 병렬 수집해 두 열의 표시 대기 시간을 줄입니다."""
    sources, source_issues = load_news_sources_with_issues()
    grouped = {"국내": [], "국제": []}
    errors = {"국내": [], "국제": []}
    if not sources:
        for region in errors:
            errors[region].extend(source_issues)
        return grouped, errors, source_issues

    with ThreadPoolExecutor(max_workers=min(10, len(sources))) as executor:
        future_map = {executor.submit(fetch_rss_items, source["url"]): source for source in sources}
        for future in as_completed(future_map):
            source = future_map[future]
            try:
                for article in future.result():
                    article["publisher"] = source["publisher"]
                    grouped[source["region"]].append(article)
            except Exception as exc:
                errors[source["region"]].append(f"{source['publisher']}: 피드 수신에 실패했습니다 ({safe_exception_category(exc)}).")

    for region in grouped:
        seen, unique = set(), []
        for article in grouped[region]:
            key = (article.get("title", ""), article.get("link", ""))
            if key not in seen:
                unique.append(article)
                seen.add(key)
        unique.sort(key=lambda item: item.get("published_timestamp", 0), reverse=True)
        grouped[region] = unique
        if not unique and not errors[region]:
            errors[region].append("해당 분류에서 표시할 기사가 없습니다.")
    return grouped, errors, source_issues


def collect_news(region: str):
    """기존 함수 호환용. 새 화면은 collect_all_news()를 사용합니다."""
    grouped, errors, _ = collect_all_news()
    return grouped.get(region, []), errors.get(region, [])

# ============================================================
# 5. 12개 API 카탈로그와 API별 호출 어댑터
# ============================================================

API_GROUPS = [
    {
        "id": "assembly", "name": "국회", "icon": "🏛️",
        "description": "국회의원·본회의 표결·국회 일정",
        "items": ["member", "vote", "schedule"],
    },
    {
        "id": "election", "name": "선거", "icon": "🗳️",
        "description": "당선인·후보자·선거구 정보",
        "items": ["winner", "candidate"],
    },
    {
        "id": "government", "name": "행정부", "icon": "🏢",
        "description": "공공서비스·기관별 공무원·중앙행정기관 하부기구",
        "items": ["benefit", "staff", "suborg"],
    },
    {
        "id": "local", "name": "지방행정", "icon": "🗺️",
        "description": "지방의회 정수·주민등록 인구",
        "items": ["council", "population"],
    },
    {
        "id": "statistics", "name": "국가통계", "icon": "📊",
        "description": "KOSIS 지역·사회 지표 통계",
        "items": ["kosis"],
    },
    {
        "id": "map", "name": "행정구역 지도", "icon": "📍",
        "description": "브이월드 WMS/WFS 행정구역 경계",
        "items": ["vworld"],
    },
]

API_ITEMS = {
    "member": {
        "title": "국회의원 정보 통합 API", "short": "국회의원",
        "description": "국회의원 이름·정당·지역구 등 기본 정보를 조회합니다.",
        "group": "국회", "key": "OPENASSEMBLY_KEY",
        "url": "https://open.assembly.go.kr/portal/openapi/ALLNAMEMBER",
        "status": "요청 주소 확인",
        "source_url": "https://open.assembly.go.kr/",
    },
    "vote": {
        "title": "국회의원 본회의 표결정보", "short": "본회의 표결",
        "description": "국회의원의 본회의 안건별 찬성·반대·기권 등 표결 자료입니다.",
        "group": "국회", "key": "OPENASSEMBLY_KEY",
        "url": "https://open.assembly.go.kr/portal/openapi/nojepdqqaweusdfbi",
        "status": "국회 대수·의안 ID 입력 필요",
        "source_url": "https://open.assembly.go.kr/",
    },
    "schedule": {
        "title": "국회일정 통합 API", "short": "국회일정",
        "description": "본회의·위원회 일정과 의정활동 일정을 조회합니다.",
        "group": "국회", "key": "OPENASSEMBLY_KEY",
        "url": "",
        "status": "상세 API 코드 확인 필요",
    },
    "winner": {
        "title": "중앙선거관리위원회 당선인 정보", "short": "당선인",
        "description": "선거 ID와 선거 종류, 시도·선거구를 지정해 당선인 정보를 조회합니다.",
        "group": "선거", "key": "DATA_GO_KR_KEY",
        "url": "https://apis.data.go.kr/9760000/WinnerInfoInqireService2/getWinnerInfoInqire",
        "status": "요청 주소 확인",
        "source_url": "https://www.data.go.kr/data/15000864/openapi.do",
    },
    "candidate": {
        "title": "중앙선거관리위원회 후보자 통합검색", "short": "후보자",
        "description": "후보자 이름을 기준으로 후보 이력과 기본 정보를 검색합니다.",
        "group": "선거", "key": "DATA_GO_KR_KEY",
        "url": "https://apis.data.go.kr/9760000/CndaSrchService/getCndaSrchInqire",
        "status": "이름 검색 요청변수 확인 필요",
        "source_url": "https://www.data.go.kr/data/15140045/openapi.do",
    },
    "benefit": {
        "title": "행정안전부 공공서비스(혜택) 정보", "short": "공공서비스",
        "description": "중앙부처·지자체 등이 제공하는 공공서비스 목록과 상세 정보입니다.",
        "group": "행정부", "key": "DATA_GO_KR_KEY",
        "url": "https://api.odcloud.kr/api/gov24/v3/serviceList",
        "status": "정부24 공공서비스 목록 API 연결",
        "source_url": "https://www.data.go.kr/data/15113968/openapi.do",
    },
    "staff": {
        "title": "행정안전부 기관별 공무원 정원", "short": "공무원 정원",
        "description": "기준연도와 기관별 공무원 정원 통계를 확인합니다.",
        "group": "행정부", "key": "DATA_GO_KR_KEY",
        "url": "https://apis.data.go.kr/1741000/FixedNumberCivilServantsOrg/getFixedNumberCivilServantsOrgList",
        "status": "요청 주소 확인",
        "source_url": "https://www.data.go.kr/data/15077900/openapi.do",
    },
    "suborg": {
        "title": "행정안전부 중앙행정기관별 하부기구", "short": "중앙기관 하부기구",
        "description": "중앙행정기관의 보조·보좌기관 관련 통계를 확인합니다.",
        "group": "행정부", "key": "DATA_GO_KR_KEY",
        "url": "https://apis.data.go.kr/1741000/SubOrganEachCenterExecutive/getSubOrganEachCenterExecutive",
        "status": "요청 주소 확인",
        "source_url": "https://www.data.go.kr/data/15107327/openapi.do",
    },
    "council": {
        "title": "행정안전부 기수별 지방의회의원 정수", "short": "지방의회 정수",
        "description": "지방의회의 기수별·유형별 의원 정수 통계입니다. 퀴즈가 아닌 지역 정보에 사용합니다.",
        "group": "지방행정", "key": "DATA_GO_KR_KEY",
        "url": "",
        "status": "상세 요청 주소 확인 필요",
        "source_url": "https://www.data.go.kr/data/15107372/openapi.do",
    },
    "population": {
        "title": "행정안전부 행정동별 주민등록 인구 및 세대현황", "short": "주민등록 인구",
        "description": "행정구역·통계년월별 인구와 세대 현황을 확인합니다.",
        "group": "지방행정", "key": "DATA_GO_KR_KEY",
        "url": "",
        "status": "상세 요청 주소 확인 필요",
        "source_url": "https://www.data.go.kr/data/15108065/openapi.do",
    },
    "kosis": {
        "title": "국가데이터처 KOSIS 공유서비스", "short": "KOSIS 통계",
        "description": "지역별 인구·출생 등 국가통계의 목록과 자료를 조회합니다.",
        "group": "국가통계", "key": "KOSIS_KEY",
        "url": "https://kosis.kr/openapi/statisticsList.do",
        "status": "통계표 선택 필요",
        "source_url": "https://kosis.kr/openapi/devGuide/devGuide_0201List.do",
    },
    "vworld": {
        "title": "국토교통부 행정구역도 WMS/WFS", "short": "행정구역도",
        "description": "광역시도·시군구·읍면동의 경계 공간정보를 지도에 표시합니다.",
        "group": "지도", "key": "VWORLD_KEY",
        "url": "https://api.vworld.kr/req/wfs",
        "status": "WFS 레이어 연결",
        "source_url": "https://www.vworld.kr/",
    },
}


def open_assembly_call(item_id: str, extra=None):
    key = api_key("OPENASSEMBLY_KEY")
    if not key:
        return [], "Streamlit Secrets에 OPENASSEMBLY_KEY를 등록해 주세요."
    item = API_ITEMS[item_id]
    url = item["url"]
    if item_id == "schedule":
        url = api_url("ASSEMBLY_SCHEDULE")
        if not url:
            schedule_code = api_code("ASSEMBLY_SCHEDULE")
            if schedule_code:
                url = "https://open.assembly.go.kr/portal/openapi/" + schedule_code.strip()
        if not url:
            return [], "국회일정 통합 API의 상세 요청 주소 또는 API 코드를 Secrets의 API_URLS/API_CODES에 등록해 주세요."
    if item_id == "vote":
        if not extra or not extra.get("AGE") or not extra.get("BILL_ID"):
            return [], "본회의 표결정보 조회에는 국회 대수(AGE)와 의안 ID(BILL_ID)가 필요합니다."
    params = {"KEY": key, "Type": "xml", "pIndex": 1, "pSize": 100}
    if extra:
        params.update(extra)
    return call_api(item["title"], url, params)


def data_go_call(item_id: str, extra=None):
    """공공데이터포털 API 어댑터. 확인되지 않은 파라미터 이름은 임의로 전송하지 않습니다."""
    key = api_key("DATA_GO_KR_KEY")
    if not key:
        return [], "Streamlit Secrets에 DATA_GO_KR_KEY를 등록해 주세요."
    if item_id not in API_ITEMS:
        return [], "등록되지 않은 공공데이터 항목입니다."

    item = API_ITEMS[item_id]
    url = item["url"]
    params = {
        "serviceKey": key,
        "pageNo": 1,
        "numOfRows": 100,
        "resultType": "json",
    }
    extra = extra or {}

    if item_id == "winner":
        if not extra.get("sgId") or not extra.get("sgTypecode"):
            return [], "당선인 조회에는 선거 ID(sgId)와 선거종류코드(sgTypecode)가 필요합니다."
        params.update(extra)
    elif item_id == "candidate":
        if not extra.get("name"):
            return [], "후보자 통합검색은 이름 검색어가 필요합니다."
        name_param = api_code("CANDIDATE_NAME_PARAM")
        if not name_param:
            return [], "후보자 이름 검색의 정확한 요청변수 이름이 확인되지 않았습니다. 공식 활용가이드를 확인한 뒤 API_CODES.CANDIDATE_NAME_PARAM에 등록해 주세요."
        params[name_param] = str(extra["name"]).strip()
    elif item_id in ("staff", "suborg"):
        params["type"] = "xml"
        params.pop("resultType", None)
        if item_id == "staff" and extra.get("bas_yy"):
            if not re.fullmatch(r"\d{4}", str(extra["bas_yy"]).strip()):
                return [], "기준년도는 YYYY 형식으로 입력해 주세요."
            params["bas_yy"] = str(extra["bas_yy"]).strip()
    elif item_id == "benefit":
        # data.go.kr의 공식 OpenAPI Swagger: /gov24/v3/serviceList
        url = api_url("MOIS_BENEFIT", item["url"])
        if not url:
            return [], "공공서비스 API의 HTTPS 요청 주소 설정을 확인해 주세요."
        params = {"serviceKey": key, "page": 1, "perPage": 100, "returnType": "JSON"}
        keyword = str(extra.get("keyword", "")).strip()
        if keyword:
            params["cond[서비스명::LIKE]"] = keyword
    elif item_id == "council":
        url = api_url("MOIS_COUNCIL_SEATS")
        if not url:
            return [], "지방의회의원 정수 API 상세 요청 주소를 API_URLS.MOIS_COUNCIL_SEATS에 등록해야 합니다."
        params["type"] = "xml"
        params.pop("resultType", None)
    elif item_id == "population":
        url = api_url("MOIS_POPULATION")
        if not url:
            return [], "행정동별 인구 API의 정확한 상세 요청 주소를 API_URLS.MOIS_POPULATION에 등록해야 합니다."
        month = str(extra.get("statsYm", "")).strip()
        admin_code = str(extra.get("admCd", "")).strip()
        month_param = api_code("MOIS_POPULATION_MONTH_PARAM")
        admin_param = api_code("MOIS_POPULATION_ADMIN_PARAM")
        if not re.fullmatch(r"\d{6}", month) or not 1 <= int(month[4:6]) <= 12:
            return [], "통계년월은 YYYYMM 형식으로 입력해 주세요."
        if not admin_code or not admin_code.isdigit():
            return [], "지역별 주민등록 인구를 조회하려면 숫자로 된 행정기관코드가 필요합니다."
        if not month_param or not admin_param:
            return [], "인구 API의 통계년월·행정기관코드 요청변수 이름을 공식 활용가이드에서 확인한 뒤 API_CODES에 등록해야 합니다. 임의의 변수명은 전송하지 않습니다."
        params["type"] = "xml"
        params.pop("resultType", None)
        params.update({month_param: month, admin_param: admin_code})

    if extra and item_id not in ("winner", "candidate", "benefit", "population", "staff"):
        params.update(extra)
    return call_api(item["title"], url, params)


def kosis_list_call(parent_id: str, view_code: str):
    key = api_key("KOSIS_KEY")
    if not key:
        return [], "Streamlit Secrets에 KOSIS_KEY를 등록해 주세요."
    if not parent_id.strip():
        return [], "KOSIS 통계목록을 조회하려면 목록 시작 ID(parentListId)가 필요합니다."
    params = {
        "method": "getList",
        "apiKey": key,
        "vwCd": view_code,
        "parentListId": parent_id.strip(),
        "format": "json",
        "jsonVD": "Y",
    }
    return call_api("KOSIS 통계목록", "https://kosis.kr/openapi/statisticsList.do", params)


def validate_kosis_period_range(period: str, start_period: str, end_period: str):
    """KOSIS 주기별 시점 형식과 시작·종료 범위를 확인합니다."""
    formats = {
        "D": (r"\d{8}", "일은 YYYYMMDD 형식"),
        "M": (r"\d{4}(0[1-9]|1[0-2])", "월은 YYYYMM 형식(월 01~12)"),
        "Q": (r"\d{4}0[1-4]", "분기는 YYYY01~YYYY04 형식"),
        "S": (r"\d{4}0[1-2]", "반기는 YYYY01~YYYY02 형식"),
        "Y": (r"\d{4}", "연도는 YYYY 형식"),
    }
    if period not in formats:
        return "지원하는 KOSIS 수록주기는 일(D)·월(M)·분기(Q)·반기(S)·연(Y)입니다."
    if not start_period and not end_period:
        return ""
    if not start_period or not end_period:
        return "기간을 지정하려면 시작 시점과 종료 시점을 모두 입력해 주세요. 둘 다 비우면 최신 시점 1개를 조회합니다."
    pattern, description = formats.get(period, (r"\d{4}", "시점은 YYYY 형식"))
    if not re.fullmatch(pattern, start_period) or not re.fullmatch(pattern, end_period):
        return f"{description}으로 시작·종료 시점을 입력해 주세요."
    if start_period > end_period:
        return "시작 시점은 종료 시점보다 늦을 수 없습니다."
    return ""


def kosis_data_call(org_id: str, table_id: str, item_id: str, obj_l1: str, period: str, start_period: str = "", end_period: str = ""):
    key = api_key("KOSIS_KEY")
    if not key:
        return [], "Streamlit Secrets에 KOSIS_KEY를 등록해 주세요."
    required = [org_id, table_id, item_id, obj_l1, period]
    if not all(str(x).strip() for x in required):
        return [], "기관 ID·통계표 ID·항목 ID·분류값·수록주기를 입력해야 합니다."
    start_period = str(start_period or "").strip()
    end_period = str(end_period or "").strip()
    period_error = validate_kosis_period_range(str(period).strip(), start_period, end_period)
    if period_error:
        return [], period_error

    params = {
        "method": "getList",
        "apiKey": key,
        "orgId": str(org_id).strip(),
        "tblId": str(table_id).strip(),
        "itmId": str(item_id).strip(),
        "objL1": str(obj_l1).strip(),
        "prdSe": str(period).strip(),
        "format": "json",
        "jsonVD": "Y",
    }
    if start_period and end_period:
        params["startPrdDe"] = start_period
        params["endPrdDe"] = end_period
    return call_api("KOSIS 통계자료", "https://kosis.kr/openapi/Param/statisticsParameterData.do", params)


# ============================================================
# 6. 공통 UI 조각
# ============================================================

def render_app_header():
    st.markdown(
        '<div class="app-header"><h1>🏛️ 정치 한 걸음</h1>'
        '<p>정치를 배우고, 자료를 읽고, 스스로 판단하기</p></div>',
        unsafe_allow_html=True,
    )


def render_hero(title, subtitle):
    st.markdown(
        f'<div class="hero"><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>',
        unsafe_allow_html=True,
    )

def render_section(title, caption=None):
    st.markdown(f'<div class="section-title">{html.escape(title)}</div>', unsafe_allow_html=True)
    if caption:
        st.caption(caption)


def render_quiz_question(question, radio_key, index=None):
    # Quiz.txt는 사용자가 직접 수정하므로 문제 문구를 Markdown/HTML로 해석하지 않습니다.
    st.markdown(f"**{html.escape(str(question.get('문제', '문제 내용 없음')))}**")
    st.caption(f"{question.get('분야', '정치교과')} · 난이도 {question.get('난이도', '보통')}")
    return st.radio(
        "선택지를 고르세요.",
        question["선택지"],
        key=radio_key,
        index=index,
        label_visibility="collapsed",
    )


def google_search_link(label: str, term: str):
    st.link_button(label, "https://www.google.com/search?q=" + quote_plus(term), use_container_width=True)


# ============================================================
# 7. 퀴즈 상태 / 객관식 진행 / 결과 모달
# ============================================================

def initialize_state():
    initial = {
        "page": "홈",
        "quiz_active": False,
        "quiz_result_open": False,
        "quiz_questions": [],
        "quiz_current": 0,
        "quiz_answers": [],
        "quiz_right_count": 0,
        "quiz_title": "",
        "quiz_return_page": "정치 퀴즈·미니게임",
        "home_daily_result": None,
        "api_selected_group": "assembly",
        "api_selected_item": "",
        "quiz_mode": "today",
        "local_selected_sido": "",
        "local_selected_sigungu": "",
        "org_detail": "",
        "org_return_page": "정부 조직",
        "local_level": "광역자치단체",
        "local_selected_sido_code": "",
        "local_selected_sigungu": "",
        "local_selected_sigungu_code": "",
        "local_population_admin_code": "",
    }
    for key, value in initial.items():
        if key not in st.session_state:
            st.session_state[key] = value


def begin_quiz(questions, title, return_page=None):
    st.session_state.quiz_questions = questions
    st.session_state.quiz_current = 0
    st.session_state.quiz_answers = []
    st.session_state.quiz_right_count = 0
    st.session_state.quiz_title = title
    st.session_state.quiz_active = True
    st.session_state.quiz_result_open = False
    if return_page:
        st.session_state.quiz_return_page = return_page


@st.dialog("퀴즈 결과", width="large")
def show_quiz_result_dialog():
    answers = st.session_state.quiz_answers
    total = len(answers)
    correct = sum(1 for item in answers if item["정답여부"])
    topics = sorted(set(item["분야"] for item in answers if item.get("분야")))
    weak = {}
    for item in answers:
        if not item["정답여부"]:
            weak[item.get("분야", "기타")] = weak.get(item.get("분야", "기타"), 0) + 1

    m1, m2, m3 = st.columns(3)
    m1.metric("푼 문제", f"{total}개")
    m2.metric("정답", f"{correct}개")
    m3.metric("정답률", f"{(correct / total * 100):.0f}%" if total else "0%")

    st.markdown("**다룬 주제**")
    st.write(" · ".join(topics) if topics else "기록된 주제가 없습니다.")
    if weak:
        st.markdown("**다시 살펴볼 주제**")
        for topic, count in weak.items():
            st.write(f"- {topic}: 오답 {count}개")
    else:
        st.success("오답이 없습니다.")

    with st.expander("문제별 풀이 확인", expanded=False):
        for number, item in enumerate(answers, 1):
            st.markdown(f"**{number}. {html.escape(str(item['문제']))}**")
            st.write(f"내 답: {item['선택답']} / 정답: {item['정답']}")
            st.caption(item.get("해설", ""))

    if st.button("나가기", type="primary", use_container_width=True):
        st.session_state.quiz_active = False
        st.session_state.quiz_result_open = False
        st.session_state.page = st.session_state.quiz_return_page
        st.rerun()


def render_quiz_type_selector(quiz_questions):
    st.divider()
    render_section("퀴즈 종류 선택")
    options = [
        ("today", "📋", "오늘의 퀴즈"),
        ("multiple", "☷", "객관식"),
        ("crossword", "▦", "십자말풀이"),
        ("fillblank", "↔", "빈칸 채우기"),
    ]
    cols = st.columns(4)
    for col, (mode, icon, label) in zip(cols, options):
        with col:
            if st.button(f"{icon}\n{label}", key=f"quiz_mode_{mode}", use_container_width=True):
                st.session_state.quiz_mode = mode
                if mode in ("today", "multiple") and quiz_questions:
                    ordered = list(quiz_questions)
                    if mode == "today":
                        digest = int(korea_today().strftime("%Y%m%d"))
                        offset = digest % len(ordered)
                        ordered = ordered[offset:] + ordered[:offset]
                    else:
                        random.shuffle(ordered)
                    begin_quiz(ordered[:min(10, len(ordered))], "오늘의 퀴즈" if mode == "today" else "객관식 퀴즈", st.session_state.get("quiz_return_page", "홈"))
                else:
                    st.session_state.quiz_active = False
                st.rerun()


def filter_member_frame(frame: pd.DataFrame, district: str) -> pd.DataFrame:
    """지역구 검색어를 정규식이 아닌 일반 문자열로 처리합니다."""
    query = str(district or "").strip()
    if not query:
        return frame
    return frame[frame["지역구"].astype(str).str.contains(query, case=False, regex=False, na=False)]


def render_live_quiz_tools():
    """교과 퀴즈 화면을 유지하면서 실시간 인물 문제도 같은 퀴즈 흐름으로 진입하게 합니다."""
    with st.expander("실시간 정치인 자료로 퀴즈 만들기", expanded=False):
        st.caption("API가 실제로 반환한 의원·당선인 자료만 문제에 사용합니다.")
        district = st.text_input("지역구 이름(선택)", placeholder="예: 수원시, 종로구 등", key="live_district_input")
        if st.button("국회의원 자료 조회", key="live_member_fetch", type="primary"):
            with st.spinner("국회의원 자료를 가져오는 중입니다..."):
                rows, message = open_assembly_call("member")
            st.session_state.live_member_rows = rows
            st.session_state.live_member_error = message
        if st.session_state.get("live_member_error"):
            st.warning(st.session_state.live_member_error)
        member_rows = st.session_state.get("live_member_rows", [])
        if member_rows:
            members = [normalize_member_record(row) for row in member_rows]
            df = pd.DataFrame([{k: m[k] for k in ("이름", "정당", "지역구", "대수")} for m in members])
            # 사용자 입력은 정규식이 아닌 일반 문자열로 처리합니다.
            df = filter_member_frame(df, district)
            st.caption(f"조회 결과 {len(df)}명")
            st.dataframe(df, use_container_width=True, hide_index=True, height=220)
            can_start_member_quiz = len(df) >= 1 and len(members) >= 4
            if st.button("이 자료로 인물 퀴즈 시작", key="live_member_quiz_start", disabled=not can_start_member_quiz):
                quiz = generate_member_quiz(member_rows, district)
                if quiz:
                    begin_quiz([quiz], "실시간 정치인 퀴즈", st.session_state.get("quiz_return_page", "홈"))
                    st.rerun()
                st.warning("서로 다른 의원 자료가 4명 이상 필요합니다.")

        st.markdown("**당선인 자료로 퀴즈 만들기**")
        c1, c2 = st.columns(2)
        with c1:
            election_id = st.text_input("선거 ID (sgId)", placeholder="예: 20240410", key="live_winner_id")
        with c2:
            election_type = st.text_input("선거종류코드 (sgTypecode)", placeholder="공식 선거 코드 확인", key="live_winner_type")
        c3, c4 = st.columns(2)
        with c3:
            sido = st.text_input("시도명 (선택)", key="live_winner_sido")
        with c4:
            district_name = st.text_input("선거구명 (선택)", key="live_winner_district")
        if st.button("당선인 자료 조회", key="live_winner_fetch"):
            extra = {"sgId": election_id.strip(), "sgTypecode": election_type.strip()}
            if sido.strip():
                extra["sdName"] = sido.strip()
            if district_name.strip():
                extra["sggName"] = district_name.strip()
            rows, message = data_go_call("winner", extra)
            st.session_state.winner_rows = rows
            st.session_state.winner_error = message
        if st.session_state.get("winner_error"):
            st.warning(st.session_state.winner_error)
        winner_rows = st.session_state.get("winner_rows", [])
        if winner_rows:
            table_view(winner_rows, 80)
            quiz = generate_winner_quiz(winner_rows)
            if quiz and st.button("당선인 인물 퀴즈 시작", key="live_winner_quiz_start", type="primary"):
                begin_quiz([quiz], "당선인 인물 퀴즈", st.session_state.get("quiz_return_page", "홈"))
                st.rerun()


def render_quiz_session(quiz_questions):
    questions = st.session_state.quiz_questions
    if not questions:
        st.info("출제할 문제가 없습니다. Quiz.txt의 문제 형식을 확인해 주세요.")
        st.session_state.quiz_active = False
        render_quiz_type_selector(quiz_questions)
        return

    if st.session_state.quiz_result_open:
        show_quiz_result_dialog()
        return

    current = st.session_state.quiz_current
    if current >= len(questions):
        st.session_state.quiz_result_open = True
        st.rerun()
        return

    left, right = st.columns([5, 1])
    with left:
        st.markdown("### 정치 퀴즈")
        st.caption(f"오늘의 퀴즈 · {current + 1} / {len(questions)}")
    with right:
        if st.button("↪ 퀴즈 종료", key="quiz_exit", use_container_width=True):
            st.session_state.quiz_result_open = True
            st.rerun()
    st.progress((current + 1) / len(questions))

    question = questions[current]
    with st.container(border=True):
        st.caption(question.get("분야", "오늘의 정치 상식"))
        st.markdown(f"### {html.escape(question['문제'])}")
        selected = st.radio(
            "선택지", question["선택지"], key=f"session_answer_{current}",
            index=None, label_visibility="collapsed",
        )
        if st.button("정답 제출", type="primary", disabled=selected is None, key=f"session_submit_{current}"):
            try:
                correct_index = int(question["정답"]) - 1
                correct_answer = question["선택지"][correct_index]
            except (ValueError, IndexError, TypeError):
                st.error("문제의 정답 항목이 올바르지 않습니다. Quiz.txt의 정답 번호를 확인해 주세요.")
                return
            is_correct = selected == correct_answer
            st.session_state.quiz_answers.append({
                "문제": question["문제"],
                "선택답": selected,
                "정답": correct_answer,
                "정답여부": is_correct,
                "해설": question.get("해설", ""),
                "분야": question.get("분야", "실시간 정치자료"),
            })
            st.session_state.quiz_current += 1
            if st.session_state.quiz_current >= len(questions):
                st.session_state.quiz_result_open = True
            st.rerun()

    render_quiz_type_selector(quiz_questions)
    render_live_quiz_tools()

# ============================================================
# 8. 실시간 API 퀴즈 생성
# ============================================================

def normalize_member_record(row):
    return {
        "이름": first_field(row, ["NAAS_NM", "HG_NM", "name", "NAME"], "정보 없음"),
        "정당": first_field(row, ["PLPT_NM", "POLY_NM", "POL_NM", "jdName"], "정보 없음"),
        "지역구": first_field(row, ["ORIG_NM", "ELECD_NM", "sggName"], "정보 없음"),
        "대수": first_field(row, ["UNITS", "DAESU", "AGE", "UNIT_CD"], "정보 없음"),
        "raw": row,
    }


def generate_member_quiz(member_rows, desired_district=""):
    members = [normalize_member_record(row) for row in member_rows]
    members = [m for m in members if m["이름"] != "정보 없음"]
    if desired_district.strip():
        district_matches = [m for m in members if desired_district.strip() in m["지역구"]]
    else:
        district_matches = members
    if not district_matches or len(members) < 4:
        return None
    correct = random.choice(district_matches)
    distractors = [m["이름"] for m in members if m["이름"] != correct["이름"]]
    if len(set(distractors)) < 3:
        return None
    options = random.sample(list(dict.fromkeys(distractors)), 3) + [correct["이름"]]
    random.shuffle(options)
    region_phrase = f"'{correct['지역구']}' 지역구" if correct["지역구"] != "정보 없음" else "자료에 표시된"
    return {
        "분야": "실시간 정치인",
        "문제": f"국회 API 자료에서 {region_phrase} 국회의원으로 확인되는 인물은 누구일까요?",
        "선택지": options,
        "정답": options.index(correct["이름"]) + 1,
        "해설": f"국회 API 응답에서 {correct['이름']} 의원의 지역구는 {correct['지역구']}, 정당은 {correct['정당']}으로 표시됩니다. 기준 시점과 원자료를 함께 확인하세요.",
        "난이도": "실시간 자료",
    }


def generate_winner_quiz(winner_rows):
    """당선인 API 결과에 포함된 실제 이름만으로 선거구 인물 문제 생성."""
    people = []
    for row in winner_rows:
        name = first_field(row, ["name", "NAME", "NAM", "winnerName", "당선인명"])
        district = first_field(row, ["sggName", "SGG_NAME", "sgg_nm", "선거구명"])
        party = first_field(row, ["jdName", "JD_NAME", "POLY_NM", "정당명"])
        if name != "정보 없음":
            people.append({"name": name, "district": district, "party": party})
    # 선거구 정보가 없는 행은 특정 선거구 당선인 문제의 정답 후보로 쓰지 않습니다.
    unique = {person["name"]: person for person in people if person["district"] != "정보 없음"}
    people = list(unique.values())
    if len(people) < 4:
        return None
    target = random.choice(people)
    distractors = random.sample([p["name"] for p in people if p["name"] != target["name"]], 3)
    choices = distractors + [target["name"]]
    random.shuffle(choices)
    return {
        "분야": "실시간 당선인",
        "문제": f"{target['district']} 선거구의 당선인으로 API 자료에 기록된 인물은 누구일까요?",
        "선택지": choices,
        "정답": choices.index(target["name"]) + 1,
        "해설": f"당선인 API 자료에서 {target['name']}은(는) {target['district']} 선거구, 정당 {target['party']}로 조회되었습니다.",
        "난이도": "실시간 자료",
    }


# ============================================================
# 9. 화면: 홈 (고정한 메인 UI)
# ============================================================

def go_to_api_item(item_id: str):
    st.session_state.page = "정치 자료 탐색"
    st.session_state.api_selected_item = item_id
    st.session_state.api_detail_rows = []
    st.session_state.api_detail_error = ""
    st.session_state.api_detail_item = ""
    st.rerun()


def render_home(quiz_questions):
    # 메인 화면은 첨부된 최종 시안의 퀴즈 상단 + 뉴스/자료 바로가기 하단 구성을 따릅니다.
    with st.container(border=True):
        title_col, badge_col = st.columns([4, 1])
        with title_col:
            st.markdown("### 오늘의 퀴즈")
        with badge_col:
            st.markdown("<div style='text-align:right'><span style='background:#d7f4e4;color:#08783b;padding:4px 10px;border-radius:20px;font-size:.82rem'>오늘의 문제</span></div>", unsafe_allow_html=True)
        st.caption("※ 국회·선거·행정부 관련 자료를 바탕으로 한 퀴즈가 제공됩니다.")
        st.caption("오늘의 문제는 Quiz.txt의 등록 문항에서 출제되며, API 실시간 자료 퀴즈는 퀴즈 화면에서 이용할 수 있습니다.")
        today_question = None
        if quiz_questions:
            digest = int(korea_today().strftime("%Y%m%d"))
            today_question = quiz_questions[digest % len(quiz_questions)]

        if today_question:
            st.markdown("### 오늘의 정치 상식")
            st.markdown(f"<div style='font-size:1.18rem;line-height:1.6;margin:.25rem 0 .7rem'>{html.escape(today_question['문제'])}</div>", unsafe_allow_html=True)
            result = st.session_state.get("home_daily_result")
            if result and result.get("문제") != today_question["문제"]:
                st.session_state.home_daily_result = None
                result = None
            if not result:
                selected = st.radio(
                    "선택지를 고르세요.", today_question["선택지"], index=None,
                    key=f"home_daily_choice_{korea_today().strftime('%Y%m%d')}", label_visibility="collapsed",
                )
                if st.button("정답 제출", type="primary", disabled=selected is None, key="home_submit"):
                    correct_answer = today_question["선택지"][today_question["정답"] - 1]
                    st.session_state.home_daily_result = {
                        "문제": today_question["문제"],
                        "정답여부": selected == correct_answer,
                        "내답": selected,
                        "정답": correct_answer,
                        "해설": today_question.get("해설", "해설이 등록되지 않았습니다."),
                    }
                    st.rerun()
            if result:
                if result["정답여부"]:
                    st.success("정답입니다.")
                else:
                    st.error(f"오답입니다. 정답은 '{result['정답']}'입니다.")
                st.write(result["해설"])
                if st.button("퀴즈·미니게임 화면으로 이동", type="primary", use_container_width=True, key="home_to_quiz"):
                    st.session_state.quiz_return_page = "홈"
                    st.session_state.quiz_mode = "today"
                    st.session_state.quiz_active = False
                    st.session_state.page = "정치 퀴즈·미니게임"
                    st.rerun()
        else:
            st.info("출제할 문제가 없습니다. Quiz.txt의 문제 형식을 확인해 주세요.")

    st.write("")
    news_col, shortcut_col = st.columns([.78, 2.25], gap="large")
    with news_col:
        render_section("뉴스")
        if st.button("◔  국내", key="home_news_domestic", use_container_width=True):
            st.session_state.news_focus = "국내"
            st.session_state.page = "뉴스 속보"
            st.rerun()
        if st.button("◎  국제", key="home_news_global", use_container_width=True):
            st.session_state.news_focus = "국제"
            st.session_state.page = "뉴스 속보"
            st.rerun()
    with shortcut_col:
        render_section("자료 바로가기")
        shortcut_items = [
            ("member", "♙", "국회의원"),
            ("vote", "☑", "본회의 표결"),
            ("schedule", "▦", "국회 일정"),
            ("winner", "♙", "당선인"),
            ("candidate", "⌕", "후보자"),
            ("benefit", "♧", "공공서비스"),
        ]
        for start in (0, 3):
            cols = st.columns(3)
            for col, (item_id, icon, label) in zip(cols, shortcut_items[start:start + 3]):
                with col:
                    if st.button(f"{icon}\n{label}", key=f"home_api_{item_id}", use_container_width=True):
                        go_to_api_item(item_id)
        st.caption("선택하면 해당 공공자료의 설명과 원자료를 확인할 수 있습니다.")

# ============================================================
# 10. 화면: 퀴즈와 미니게임
# ============================================================

def render_quiz_hub(quiz_questions):
    mode = st.session_state.get("quiz_mode", "today")
    if st.session_state.quiz_active:
        render_quiz_session(quiz_questions)
        return

    if mode == "games":
        render_hero("미니게임", "퀴즈 유형을 선택해 정치 학습을 시작하세요.")
        with st.container(border=True):
            st.markdown("### 게임 유형")
            st.write("현재 이용할 수 있는 유형은 오늘의 퀴즈와 객관식입니다. 십자말풀이와 빈칸 채우기는 문제 형식과 생성 규칙을 확정한 뒤 연결할 예정입니다.")
        render_quiz_type_selector(quiz_questions)
        return

    if mode in ("crossword", "fillblank"):
        render_hero("정치 퀴즈 · 미니게임", "퀴즈 유형을 선택해 학습을 이어가세요.")
        with st.container(border=True):
            if mode == "crossword":
                st.markdown("### ▦ 십자말풀이")
                st.info("십자말풀이 화면은 문제 데이터 구조와 격자 생성 규칙을 확정한 뒤 연결할 예정입니다. 현재는 다른 퀴즈 유형을 이용할 수 있습니다.")
            else:
                st.markdown("### ↔ 빈칸 채우기")
                st.info("빈칸 채우기 화면은 Quiz.txt에 빈칸형 문제 형식을 추가한 뒤 연결할 예정입니다. 현재는 다른 퀴즈 유형을 이용할 수 있습니다.")
        render_quiz_type_selector(quiz_questions)
        return

    if not quiz_questions:
        render_hero("정치 퀴즈 · 미니게임", "출제 자료를 확인해 주세요.")
        st.warning("Quiz.txt에서 유효한 문제를 찾지 못했습니다.")
        render_quiz_type_selector(quiz_questions)
        return

    # 퀴즈 페이지에 진입하면 시작 버튼 없이 바로 첫 문제를 표시합니다.
    ordered = list(quiz_questions)
    if mode == "today":
        digest = int(korea_today().strftime("%Y%m%d"))
        offset = digest % len(ordered)
        ordered = ordered[offset:] + ordered[:offset]
    else:
        random.shuffle(ordered)
    begin_quiz(ordered[:min(10, len(ordered))], "오늘의 퀴즈" if mode == "today" else "객관식 퀴즈", st.session_state.get("quiz_return_page", "홈"))
    st.rerun()

# ============================================================
# 11. 화면: 뉴스 (국내/국제 2열 + 각 목록 자체 스크롤)
# ============================================================

def render_news():
    render_hero("뉴스·속보", "지정된 언론사의 RSS를 통해 국내·국제 주요 뉴스를 확인합니다.")
    grouped, grouped_errors, source_issues = collect_all_news()
    domestic, domestic_errors = grouped["국내"], grouped_errors["국내"]
    international, international_errors = grouped["국제"], grouped_errors["국제"]
    if source_issues:
        with st.expander(f"NEWS.txt 설정 확인 ({len(source_issues)}건)", expanded=False):
            for issue in source_issues:
                st.warning(issue)

    col_domestic, col_global = st.columns(2, gap="medium")
    for col, title, items, errors in [
        (col_domestic, "국내", domestic, domestic_errors),
        (col_global, "국제", international, international_errors),
    ]:
        with col:
            st.markdown(f"### {title}")
            with st.container(height=650, border=True):
                if not items:
                    st.info("기사를 불러오지 못했습니다. NEWS.txt의 RSS 주소와 언론사 서버 상태를 확인해 주세요.")
                for article in items:
                    link = article["link"]
                    title_html = (
                        f'<a href="{html.escape(link, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(article["title"])}</a>'
                        if is_safe_http_url(link) else html.escape(article["title"])
                    )
                    st.markdown(
                        f'<div class="news-card"><div class="muted">{html.escape(article["publisher"])}</div>'
                        f'<div class="news-title">{title_html}</div>'
                        f'<div class="news-meta">{html.escape(article["published"])}</div>'
                        f'<div class="news-summary">{html.escape(article["summary"])}</div></div>',
                        unsafe_allow_html=True,
                    )
            if errors:
                with st.expander(f"일부 RSS 연결 오류 ({len(errors)})"):
                    for err in errors:
                        st.caption(err)

    st.divider()
    render_section("언론사 바로가기")
    outlets = [
        ("KBS", "📰", "https://news.kbs.co.kr/"),
        ("연합뉴스", "▤", "https://www.yna.co.kr/"),
        ("Reuters", "◉", "https://www.reuters.com/"),
        ("AP", "◎", "https://apnews.com/"),
        ("AFP", "◈", "https://www.afp.com/"),
        ("BBC", "◍", "https://www.bbc.com/news"),
        ("CNN", "▣", "https://edition.cnn.com/"),
    ]
    cols = st.columns(7)
    for col, (name, icon, url) in zip(cols, outlets):
        with col:
            st.link_button(f"{icon} {name}", url, use_container_width=True)

# ============================================================
# 12. 화면: 정치 자료 탐색 - 6개 아이콘 / 12개 API
# ============================================================

API_EDUCATION = {
    "member": "대의 민주주의, 국회의 구성, 국회의원의 역할",
    "vote": "입법 과정, 다수결 원칙, 국회의 의사결정",
    "schedule": "국회의 회의 운영과 의정활동",
    "winner": "선거 제도와 대표성",
    "candidate": "선거와 정당, 후보자 공약과 대표성",
    "benefit": "복지국가, 사회보장, 정부의 역할",
    "staff": "행정기관의 역할과 행정 조직",
    "suborg": "중앙행정기관과 행정 조직의 계층",
    "council": "지방자치와 지방의회의 구성",
    "population": "인구 구조, 지역 격차, 행정구역별 인구",
    "kosis": "인구 구조·도시화·사회 변화와 통계 해석",
    "vworld": "행정구역과 지방자치, 공간정보의 활용",
}


def _api_item_icon(item_id):
    return {
        "member": "♙", "vote": "☑", "schedule": "▦", "winner": "♙",
        "candidate": "⌕", "benefit": "♧", "staff": "▥", "suborg": "♧",
        "council": "♙", "population": "▤", "kosis": "▥", "vworld": "⌖",
    }.get(item_id, "▤")


def render_api_catalog():
    render_hero("정치 자료 탐색", "공식 공공데이터를 사람이 읽기 쉬운 표로 확인하고 관련 교과 개념을 함께 살펴보세요.")
    st.caption("※ 국회·선거·행정부 관련 자료는 퀴즈 출제에도 활용됩니다.")
    for group in API_GROUPS:
        st.divider()
        head, count_col = st.columns([4, 1])
        with head:
            st.markdown(f"### {group['name']} · {group['description']}")
        with count_col:
            st.markdown(f"<div style='text-align:right;color:var(--secondary-text-color);padding-top:.4rem'>{len(group['items'])}개 API</div>", unsafe_allow_html=True)

        item_list = group["items"]
        card_columns = st.columns(min(3, len(item_list)), gap="small")
        for index, item_id in enumerate(item_list):
            item = API_ITEMS[item_id]
            col = card_columns[index]
            with col:
                st.markdown(
                    f'<div class="api-card"><div style="font-size:1.35rem">{_api_item_icon(item_id)}</div>'
                    f'<div class="api-card-title">{html.escape(item["title"])}</div>'
                    f'<div class="api-card-desc">{html.escape(item["description"])}</div>'
                    f'<p class="tiny-note"><b>교과 연계</b><br>{html.escape(API_EDUCATION.get(item_id, "정치 제도와 공공자료 이해"))}</p>'
                    f'<span style="font-size:.75rem;background:var(--secondary-background-color);padding:3px 8px;border-radius:15px">원자료 · 표/엑셀 · 항목 검색</span></div>',
                    unsafe_allow_html=True,
                )
                if st.button("자료 자세히 보기", key=f"open_api_{item_id}", use_container_width=True):
                    st.session_state.api_selected_item = item_id
                    st.session_state.api_detail_rows = []
                    st.session_state.api_detail_error = ""
                    st.session_state.api_detail_item = ""
                    st.rerun()


def _fetch_selected_api(item_id, extra=None):
    if item_id in ("member", "vote", "schedule"):
        return open_assembly_call(item_id, extra)
    if item_id in ("winner", "candidate", "benefit", "staff", "suborg", "council", "population"):
        return data_go_call(item_id, extra)
    return [], "이 자료는 별도의 조회 입력 화면에서 불러옵니다."


def render_api_detail(item_id):
    item = API_ITEMS.get(item_id)
    if not item:
        st.warning("선택한 자료를 찾을 수 없습니다.")
        if st.button("자료 목록으로 돌아가기"):
            st.session_state.api_selected_item = ""
            st.rerun()
        return

    provider = {
        "국회": "국회 국회사무처",
        "선거": "중앙선거관리위원회",
        "행정부": "행정안전부",
        "지방행정": "행정안전부",
        "국가통계": "국가데이터처 KOSIS",
        "지도": "국토교통부 VWorld",
    }.get(item["group"], item["group"])
    top_left, top_right = st.columns([4, 1])
    with top_left:
        render_hero(item["title"], f"자료 제공: {provider} · 원본 출처 표시")
    with top_right:
        if st.button("← 목록", key="api_detail_back", use_container_width=True):
            st.session_state.api_selected_item = ""
            st.session_state.api_detail_rows = []
            st.session_state.api_detail_error = ""
            st.session_state.api_detail_item = ""
            st.rerun()

    st.markdown("### 이 자료는 무엇인가?")
    st.write(item["description"])
    st.markdown("### 교과서와 연결하기")
    with st.container(border=True):
        st.write(API_EDUCATION.get(item_id, "정치 제도와 공공자료를 이해하는 데 활용할 수 있습니다."))
        st.caption("공공자료는 기준 시점·조사 단위·기관별 정의를 확인한 뒤 해석해야 합니다.")

    if item.get("source_url"):
        st.link_button("공식 제공기관·활용 안내", item["source_url"])

    st.markdown("### 자료 조회")
    google_search_link("🔎 관련 항목 검색", item["short"])
    if item.get("status") and ("확인 필요" in item["status"] or "확인" in item["status"]):
        st.caption(f"연동 상태: {item['status']}. 확인되지 않은 요청변수는 임의로 전송하지 않습니다.")

    extra = {}
    if item_id == "winner":
        c1, c2 = st.columns(2)
        with c1:
            sgid = st.text_input("선거 ID (sgId)", placeholder="예: 20240410", key="detail_winner_id")
        with c2:
            sgtype = st.text_input("선거종류코드 (sgTypecode)", placeholder="공식 선거 코드 확인", key="detail_winner_type")
        c3, c4 = st.columns(2)
        with c3:
            sd_name = st.text_input("시도명 (선택)", key="detail_winner_sido")
        with c4:
            sgg_name = st.text_input("선거구명 (선택)", key="detail_winner_sgg")
        extra = {"sgId": sgid.strip(), "sgTypecode": sgtype.strip()}
        if sd_name.strip(): extra["sdName"] = sd_name.strip()
        if sgg_name.strip(): extra["sggName"] = sgg_name.strip()
    elif item_id == "candidate":
        name = st.text_input("후보자 이름", key="detail_candidate_name")
        extra = {"name": name.strip()} if name.strip() else {}
    elif item_id == "vote":
        c1, c2 = st.columns(2)
        with c1:
            age = st.text_input("국회 대수 (AGE)", placeholder="예: 22", key="detail_vote_age")
        with c2:
            bill_id = st.text_input("의안 ID (BILL_ID)", placeholder="표결 대상 의안 ID", key="detail_vote_bill")
        extra = {"AGE": age.strip(), "BILL_ID": bill_id.strip()}
    elif item_id == "staff":
        base_year = st.text_input("기준년도 (bas_yy, 선택)", placeholder="예: 2025", key="detail_staff_year")
        extra = {"bas_yy": base_year.strip()} if base_year.strip() else {}
    elif item_id == "population":
        month = st.text_input("통계년월 (YYYYMM)", value=korea_now().strftime("%Y%m"), key="detail_population_month")
        admin_code = st.text_input("행정기관코드 (필수)", key="detail_population_admin", help="선택한 행정구역과 일치하는 공식 행정기관코드를 입력해야 합니다.")
        extra = {"statsYm": month.strip(), "admCd": admin_code.strip()}
    elif item_id == "benefit":
        keyword = st.text_input("공공서비스 검색어 (선택)", key="detail_benefit_keyword")
        extra = {"keyword": keyword.strip()} if keyword.strip() else {}
    elif item_id == "kosis":
        st.caption("KOSIS는 통계목록 ID와 통계표의 기관·항목·분류 코드가 필요합니다.")
        c1, c2 = st.columns(2)
        with c1:
            view_code = st.selectbox("통계 목록 유형", ["MT_GTITLE02", "MT_GTITLE01", "MT_ZTITLE", "MT_OTITLE"], key="detail_kosis_view")
        with c2:
            parent_id = st.text_input("목록 ID (처음 조회는 A)", value="A", key="detail_kosis_parent")
        if st.button("통계표 목록 불러오기", key="detail_kosis_list"):
            rows, message = kosis_list_call(parent_id, view_code)
            st.session_state.api_detail_rows = rows
            st.session_state.api_detail_error = message
            st.session_state.api_detail_item = item_id
        c3, c4, c5 = st.columns(3)
        with c3: org_id = st.text_input("기관 ID (orgId)", key="detail_kosis_org")
        with c4: table_id = st.text_input("통계표 ID (tblId)", key="detail_kosis_tbl")
        with c5: item_code = st.text_input("항목 ID (itmId)", value="ALL", key="detail_kosis_itm")
        c6, c7, c8 = st.columns(3)
        with c6: obj_l1 = st.text_input("분류값 (objL1)", value="00", key="detail_kosis_obj", help="'00'은 기본 입력값일 뿐입니다. 선택한 통계표의 분류/항목 정보에서 실제 분류 코드를 확인해야 합니다.")
        with c7: period = st.selectbox("수록주기", ["Y", "S", "Q", "M", "D"], key="detail_kosis_period")
        period_help = {
            "D": "YYYYMMDD", "M": "YYYYMM (월 01~12)",
            "Q": "YYYY01~YYYY04 (분기 1~4)", "S": "YYYY01~YYYY02 (반기 1~2)",
            "Y": "YYYY",
        }[period]
        with c8: start_period = st.text_input("시작 시점 (선택)", key="detail_kosis_start", help=f"{period_help} 형식. 기간 조회는 시작·종료 시점을 모두 입력합니다.")
        end_period = st.text_input("종료 시점 (선택)", key="detail_kosis_end", help=f"{period_help} 형식. 둘 다 비우면 최신 시점 1개를 조회합니다.")
        if st.button("통계자료 조회", key="detail_kosis_fetch", type="primary"):
            rows, message = kosis_data_call(org_id, table_id, item_code, obj_l1, period, start_period, end_period)
            st.session_state.api_detail_rows = rows
            st.session_state.api_detail_error = message
            st.session_state.api_detail_item = item_id
    elif item_id == "vworld":
        level = st.selectbox("행정구역 단위", ["시도", "시군구", "읍면동"], key="detail_vworld_level")
        if st.button("행정구역 데이터 불러오기", key="detail_vworld_fetch", type="primary"):
            geo, message = load_vworld_geojson(level)
            st.session_state.api_detail_geo = geo
            st.session_state.api_detail_error = message
            st.session_state.api_detail_item = item_id
    else:
        st.caption("추가 검색 조건이 필요하지 않은 자료입니다.")

    if item_id not in ("kosis", "vworld"):
        if st.button("원자료 불러오기", key=f"detail_fetch_{item_id}", type="primary"):
            if item_id == "schedule":
                extra = {}
            rows, message = _fetch_selected_api(item_id, extra)
            st.session_state.api_detail_rows = rows
            st.session_state.api_detail_error = message
            st.session_state.api_detail_item = item_id

    if st.session_state.get("api_detail_item") == item_id and st.session_state.get("api_detail_error"):
        st.warning(st.session_state.api_detail_error)
    if st.session_state.get("api_detail_item") == item_id and st.session_state.get("api_detail_rows"):
        st.markdown("### 정리된 원자료")
        st.caption("현재 조회는 API 어댑터의 기본 페이지(최대 100건)를 사용하며, 표에는 최대 300행까지 표시합니다. 전체 자료가 필요하면 원 API의 페이지 기능을 추가로 확인해야 합니다.")
        table_view(st.session_state.api_detail_rows, 300, search_key=f"api_search_{item_id}")
        raw_text = st.session_state.get("api_last_raw_text", "")
        if raw_text:
            content_type = st.session_state.get("api_last_raw_content_type", "").lower()
            extension = "json" if "json" in content_type or raw_text.lstrip().startswith(("{", "[")) else "xml"
            with st.expander("원본 응답 보기", expanded=False):
                st.code(raw_text[:20000], language=extension)
                st.download_button(
                    "원본 응답 다운로드", data=raw_text.encode("utf-8"),
                    file_name=f"{item_id}_original.{extension}",
                    mime="application/json" if extension == "json" else "application/xml",
                )

    if item_id == "vworld" and st.session_state.get("api_detail_item") == item_id:
        geo = st.session_state.get("api_detail_geo")
        if geo:
            if geo.get("_truncated_notice"):
                st.warning(geo["_truncated_notice"])
            st.caption(f"GeoJSON 유형: {geo.get('type', '정보 없음')} · 경계 개수: {len(geo.get('features', []))}")
            if geo.get("features"):
                if HAS_MAP:
                    st_folium(
                        build_admin_map(geo, 7 if st.session_state.get("detail_vworld_level") == "시도" else 9),
                        height=520, use_container_width=True,
                        returned_objects=[], key=f"vworld_detail_map_{st.session_state.get('detail_vworld_level', 'level')}",
                    )
                table_view([feature.get("properties", {}) for feature in geo["features"][:100]], 100)


def render_data_explorer():
    item_id = st.session_state.get("api_selected_item", "")
    if item_id:
        render_api_detail(item_id)
    else:
        render_api_catalog()

# ============================================================
# 13. VWorld WFS / Folium 지도
# ============================================================

def normalize_vworld_geojson(payload):
    """VWorld 응답 래퍼를 풀고 지도에 사용할 수 있는 GeoJSON 피처만 남깁니다."""
    current = payload
    for key in ("response", "result", "featureCollection"):
        if isinstance(current, dict) and key in current:
            current = current[key]
    if not isinstance(current, dict) or current.get("type") != "FeatureCollection":
        return None
    features = current.get("features")
    if not isinstance(features, list):
        return None
    valid_features = [
        feature for feature in features
        if isinstance(feature, dict)
        and feature.get("type", "Feature") == "Feature"
        and isinstance(feature.get("properties", {}), dict)
        and isinstance(feature.get("geometry"), dict)
        and feature["geometry"].get("type")
        and isinstance(feature["geometry"].get("coordinates"), list)
        and bool(feature["geometry"].get("coordinates"))
    ]
    normalized = dict(current)
    normalized["features"] = valid_features
    return normalized


def load_vworld_geojson(level: str):
    key = api_key("VWORLD_KEY")
    if not key:
        return None, "Streamlit Secrets에 VWORLD_KEY를 등록해 주세요."
    domain = get_secret("APP", "VWORLD_DOMAIN", "")
    parsed_domain = urlsplit(domain)
    if _is_placeholder(domain) or parsed_domain.scheme not in ("https", "http") or not parsed_domain.netloc:
        return None, "브이월드에 등록한 실제 서비스 도메인을 APP.VWORLD_DOMAIN에 입력해 주세요."
    # VWorld 행정구역 레이어 식별자는 공식 레이어 코드 표기(대문자)를 유지합니다.
    layer = {
        "시도": "LT_C_ADSIDO_INFO",
        "시군구": "LT_C_ADSIGG_INFO",
        "읍면동": "LT_C_ADEMD_INFO",
    }.get(level)
    if not layer:
        return None, "지원하지 않는 행정구역 단위입니다."
    params = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typename": layer,
        "output": "application/json",
        "srsName": "EPSG:4326",
        "maxFeatures": 1000,
        "key": key,
        "domain": domain,
    }
    try:
        response = requests.get(
            "https://api.vworld.kr/req/wfs", params=params, timeout=(5, 25),
            headers={"User-Agent": "PoliticsOneStep/1.0", "Accept": "application/json, application/geo+json, application/xml"},
            allow_redirects=False,
        )
        response.raise_for_status()
        if 300 <= response.status_code < 400:
            return None, "브이월드 요청이 다른 주소로 리디렉션되었습니다. 공식 WFS 주소와 서비스 설정을 확인해 주세요."
        if len(response.content) > 30_000_000:
            return None, "브이월드 지도 응답이 30MB를 초과하여 안전하게 처리하지 않았습니다."
        try:
            payload = response.json()
        except ValueError:
            return None, "브이월드가 JSON이 아닌 응답을 반환했습니다. WFS 설정과 응답 형식을 확인해 주세요."
        inspect_api_error(payload)
        geo = normalize_vworld_geojson(payload)
        if not geo:
            return None, "WFS 응답이 GeoJSON FeatureCollection 형식이 아닙니다. 레이어명·도메인·응답 형식을 확인해 주세요."
        if not isinstance(geo.get("features"), list) or not geo.get("features"):
            return None, "해당 행정구역 경계 데이터가 비어 있습니다."
        if len(geo["features"]) >= 1000:
            geo = dict(geo)
            geo["_truncated_notice"] = "VWorld 요청 상한(1,000개)에 도달했을 수 있습니다. 읍면동 전체 경계는 일부만 표시될 수 있습니다."
        return geo, ""
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "알 수 없음"
        return None, f"브이월드가 HTTP {status} 오류를 반환했습니다. 인증키·도메인·요청 권한을 확인해 주세요."
    except Exception as exc:
        return None, f"브이월드 요청 중 {safe_exception_category(exc)}가 발생했습니다. 인증키·도메인·레이어를 확인해 주세요."


def region_property(feature, candidates):
    props = feature.get("properties", {}) or {}
    for key in candidates:
        value = props.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return "이름 정보 없음"


def region_code(feature, candidates):
    """행정구역 코드의 앞자리 0을 보존해 문자열로 반환합니다."""
    value = region_property(feature, candidates)
    if value == "이름 정보 없음":
        return ""
    digits = re.sub(r"\D", "", value)
    # 숫자형으로 직렬화되며 시도코드의 앞자리 0이 사라진 경우 1자리 코드를 보정합니다.
    return digits.zfill(2) if len(digits) == 1 else digits


def filter_sigungu_geojson(geojson, sido_code):
    if not geojson or not sido_code:
        return None, "시도 코드가 없어 시군구 자료를 구분할 수 없습니다."
    filtered = []
    for feature in geojson.get("features", []):
        props = feature.get("properties", {}) or {}
        code = region_code({"properties": props}, ("sig_cd", "SIG_CD", "sig_cd2"))
        if code.startswith(sido_code):
            filtered.append(feature)
    if not filtered:
        return None, "선택한 시도에 해당하는 시군구 경계가 없습니다. VWorld 속성 코드 형식을 확인해 주세요."
    return {**geojson, "features": filtered}, ""


def build_admin_map(geojson, zoom):
    features = (geojson or {}).get("features", [])
    if not isinstance(features, list) or not features:
        raise ValueError("지도에 표시할 행정구역 경계가 없습니다.")
    properties = [feature.get("properties", {}) or {} for feature in features]
    name_fields = ("ctp_kor_nm", "sig_kor_nm", "emd_kor_nm", "name", "NAME")
    # 모든 피처에 공통으로 존재하는 이름 필드만 툴팁으로 사용합니다.
    tooltip_field = next((field for field in name_fields if all(field in props for props in properties)), None)
    tooltip = folium.GeoJsonTooltip(fields=[tooltip_field], aliases=["행정구역"], sticky=True) if tooltip_field else None
    map_geojson = {"type": "FeatureCollection", "features": features}
    m = folium.Map(location=[36.3, 127.8], zoom_start=zoom, tiles="CartoDB positron", control_scale=True)
    boundary_layer = folium.GeoJson(
        map_geojson,
        name="행정구역",
        style_function=lambda feature: {
            "fillColor": "#93c5fd", "color": "#1e3a8a", "weight": 1.2, "fillOpacity": 0.22,
        },
        highlight_function=lambda feature: {
            "fillColor": "#fbbf24", "color": "#b45309", "weight": 2.8, "fillOpacity": 0.4,
        },
        tooltip=tooltip,
    ).add_to(m)
    try:
        bounds = boundary_layer.get_bounds()
        if bounds and len(bounds) == 2 and all(len(point) == 2 for point in bounds):
            m.fit_bounds(bounds, padding=(12, 12))
    except Exception:
        # 일부 잘못된 경계 좌표가 전체 지도를 깨뜨리지 않도록 기본 중심·확대율을 유지합니다.
        pass
    folium.LayerControl().add_to(m)
    return m


# ============================================================
# 14. 화면: 정부 조직 / 국회 조직 / 법원 조직
# ============================================================

def render_node(title, role, key):
    st.markdown(
        f'<div class="org-node" title="{html.escape(role)}"><strong>{html.escape(title)}</strong><br>'
        f'<small>{html.escape(role)}</small></div>',
        unsafe_allow_html=True,
    )
    if st.button(f"{title} 자세히 보기", key=f"org_detail_{key}", use_container_width=True):
        st.session_state.org_detail = title
        st.session_state.org_return_page = st.session_state.get("page", "정부 조직")
        st.session_state.page = "기관 상세"
        st.rerun()


def render_government():
    render_hero("정부 조직", "행정부의 기본 구조와 중앙행정기관 관련 통계를 살펴봅니다.")
    st.info("정부 조직은 개편될 수 있습니다. 정부디렉터리시스템 API는 신청 대기 중이므로, 현재 화면은 헌법상 기본 구조와 승인된 행정안전부 통계를 중심으로 구성했습니다.")
    render_node("대통령", "행정부 수반 · 국가원수", "president")
    st.markdown("<div style='text-align:center'>↓</div>", unsafe_allow_html=True)
    render_node("국무총리", "대통령을 보좌하고 행정 각부를 통할", "prime")
    st.markdown("<div style='text-align:center'>↓</div>", unsafe_allow_html=True)
    render_node("중앙행정기관", "부·처·청 등 중앙행정기관이 정책과 행정업무 수행", "ministries")

    if st.session_state.org_detail:
        render_org_detail()

    st.divider()
    render_section("중앙행정기관 관련 통계")
    a, b = st.columns(2)
    with a:
        if st.button("기관별 공무원 정원 조회", use_container_width=True):
            rows, message = data_go_call("staff")
            st.session_state.gov_staff_rows = rows
            st.session_state.gov_staff_error = message
        if st.session_state.get("gov_staff_error"):
            st.warning(st.session_state.gov_staff_error)
        if st.session_state.get("gov_staff_rows"):
            table_view(st.session_state.gov_staff_rows, 120)
    with b:
        if st.button("기관별 하부기구 통계 조회", use_container_width=True):
            rows, message = data_go_call("suborg")
            st.session_state.gov_suborg_rows = rows
            st.session_state.gov_suborg_error = message
        if st.session_state.get("gov_suborg_error"):
            st.warning(st.session_state.gov_suborg_error)
        if st.session_state.get("gov_suborg_rows"):
            table_view(st.session_state.gov_suborg_rows, 120)


def render_congress():
    render_hero("국회 조직", "입법부의 주요 기관과 국회의 기능을 살펴봅니다.")
    render_node("대한민국 국회", "국민의 대표기관 · 입법기관", "assembly")
    cols = st.columns(2)
    for col, title, role, key in [
        (cols[0], "국회의장단", "의장과 부의장으로 구성되며 국회 운영을 주재", "chair"),
        (cols[1], "위원회", "상임위원회와 특별위원회에서 소관 안건 심사", "committee"),
        (cols[0], "국회사무처", "국회의 의정활동과 행정 업무 지원", "secretariat"),
        (cols[1], "국회 소속기관", "국회도서관·예산정책처·입법조사처 등", "affiliated"),
    ]:
        with col:
            render_node(title, role, key)
    if st.session_state.org_detail:
        render_org_detail()
    st.link_button("국회 공식 홈페이지", "https://www.assembly.go.kr/")


def render_court():
    render_hero("법원 조직", "사법부의 기본적인 법원 체계와 역할을 살펴봅니다.")
    render_node("대법원", "최고법원 · 사법부의 최고기관", "supreme")
    cols = st.columns(2)
    for col, title, role, key in [
        (cols[0], "고등법원", "주로 지방법원 등의 판결에 대한 항소심 담당", "high"),
        (cols[1], "지방법원", "일반적인 민사·형사 사건의 1심 등 담당", "district"),
        (cols[0], "가정법원·행정법원", "가사·소년·행정 등 전문 분야 담당", "special"),
        (cols[1], "법원행정처", "법원의 인사·예산·시설 등 사법행정 지원", "admin"),
    ]:
        with col:
            render_node(title, role, key)
    if st.session_state.org_detail:
        render_org_detail()
    st.link_button("대한민국 법원 공식 홈페이지", "https://www.scourt.go.kr/")


def render_org_detail():
    title = st.session_state.org_detail
    st.divider()
    st.subheader(f"{title} 상세")
    descriptions = {
        "대통령": "대통령은 국가원수이며 행정부 수반입니다. 헌법과 법률이 정한 권한과 책임을 수행합니다.",
        "국무총리": "국무총리는 대통령을 보좌하고 행정 각부를 통할합니다.",
        "중앙행정기관": "중앙행정기관은 국가 정책을 수립·집행합니다. 부·처·청 등 기관별 설치와 소속 관계는 법령과 공식 조직 자료를 기준으로 확인해야 합니다.",
        "대한민국 국회": "국회는 법률 제정, 예산안 심의·확정, 국정 감시 등의 기능을 수행합니다.",
        "국회의장단": "국회의장단은 국회의 회의와 운영을 주재하고 조정합니다.",
        "위원회": "위원회는 소관 분야의 법률안과 청원 등을 심사합니다.",
        "국회사무처": "국회사무처는 국회의 의정활동과 입법·행정 업무를 지원합니다.",
        "국회 소속기관": "국회도서관, 국회예산정책처, 국회입법조사처 등은 전문적인 정보·분석을 제공합니다.",
        "대법원": "대법원은 대한민국의 최고법원입니다.",
        "고등법원": "고등법원은 주로 지방법원 등의 판결에 대한 항소심을 담당합니다.",
        "지방법원": "지방법원은 일반적인 민사·형사 사건의 재판을 담당합니다.",
        "가정법원·행정법원": "전문 법원은 가사·소년·행정 등 특정 분야 사건을 담당합니다.",
        "법원행정처": "법원행정처는 법원의 인사·예산·시설 등 사법행정을 지원합니다.",
    }
    st.write(descriptions.get(title, "공식 조직 자료가 확인되면 세부 내용을 추가합니다."))
    if st.button("조직도 화면으로 돌아가기"):
        st.session_state.org_detail = ""
        st.session_state.page = st.session_state.get("org_return_page", "정부 조직")
        st.rerun()


# ============================================================
# 15. 화면: 지방 정부 (시도 → 시군구 → 지역 정보)
# ============================================================


def _set_local_level(level: str):
    """위젯 생성 전 실행되는 콜백에서 탐색 단계만 변경합니다."""
    st.session_state["local_level"] = level


def _change_local_sido():
    """기초자치단체 화면에서 시도 선택 단계로 복귀합니다."""
    st.session_state["local_level"] = "광역자치단체"
    st.session_state["local_selected_sigungu"] = ""
    st.session_state["local_selected_sigungu_code"] = ""
    st.session_state["local_sigungu_geo"] = None
    st.session_state["local_sigungu_error"] = ""
    st.session_state["local_population_rows"] = []
    st.session_state["local_population_error"] = ""
    st.session_state["local_council_rows"] = []
    st.session_state["local_council_error"] = ""
    st.session_state["local_population_admin_code"] = ""
    st.session_state.pop("local_sigungu_fallback_select", None)


def _reset_local_region_data():
    """지역 선택이 바뀌면 이전 지역에서 조회한 표와 입력 코드를 지웁니다."""
    st.session_state["local_population_rows"] = []
    st.session_state["local_population_error"] = ""
    st.session_state["local_council_rows"] = []
    st.session_state["local_council_error"] = ""
    st.session_state["local_population_admin_code"] = ""


def _selected_feature_by_tooltip(features, tooltip, name_fields):
    if not tooltip:
        return None
    normalized = re.sub(r"\s+", " ", html.unescape(str(tooltip))).strip()
    return next(
        (feature for feature in features
         if region_property(feature, name_fields) == normalized),
        None,
    )


def render_local_government():
    render_hero("지방 정부", "대한민국 지도에서 지역을 선택해 지방행정·지방의회·지역 통계를 확인합니다.")
    st.caption("지방의회 정수 자료는 행정안전부 통계연보의 기수별·유형별 집계입니다. 선택한 지역의 현재 의석 수로 단정하지 않습니다.")

    if not HAS_MAP:
        st.error("지도 기능을 사용하려면 requirements.txt의 folium과 streamlit-folium 설치가 필요합니다.")
        return

    level = st.radio("탐색 단계", ["광역자치단체", "기초자치단체"], horizontal=True, key="local_level")

    if level == "광역자치단체":
        if st.session_state.get("local_sido_geo") is None:
            if st.button("전국 광역자치단체 지도 불러오기", type="primary"):
                geo, message = load_vworld_geojson("시도")
                st.session_state.local_sido_geo = geo
                st.session_state.local_sido_error = message
                st.session_state.local_sido_last_click_count = 0
                st.session_state.local_selected_sido = ""
                st.session_state.local_selected_sido_code = ""
                st.session_state.local_selected_sigungu = ""
                st.session_state.local_selected_sigungu_code = ""
                st.session_state.local_sigungu_geo = None
                st.session_state.pop("local_sido_fallback_select", None)
                st.session_state.pop("local_sigungu_fallback_select", None)
                _reset_local_region_data()
                st.rerun()
        if st.session_state.get("local_sido_error"):
            st.warning(st.session_state.local_sido_error)
        geo = st.session_state.get("local_sido_geo")
        if geo:
            if geo.get("_truncated_notice"):
                st.warning(geo["_truncated_notice"])
            map_object = build_admin_map(geo, 7)
            map_result = st_folium(
                map_object, height=570, use_container_width=True,
                returned_objects=["last_active_drawing", "last_object_clicked_tooltip", "last_object_clicked_count"],
                key="local_sido_map",
            ) or {}
            sido_features = geo.get("features", [])
            click_count = map_result.get("last_object_clicked_count") or 0
            previous_click_count = st.session_state.get("local_sido_last_click_count", 0)
            new_map_click = click_count != previous_click_count
            if new_map_click:
                st.session_state.local_sido_last_click_count = click_count
            name_fields = ("ctp_kor_nm", "CTP_KOR_NM", "name", "NAME")
            drawing = map_result.get("last_active_drawing") if new_map_click else None
            clicked_feature = drawing if isinstance(drawing, dict) and drawing.get("properties") else None
            if new_map_click and clicked_feature is None:
                clicked_feature = _selected_feature_by_tooltip(
                    sido_features, map_result.get("last_object_clicked_tooltip"), name_fields
                )
            if clicked_feature:
                props = clicked_feature.get("properties", {}) or {}
                selected = region_property({"properties": props}, name_fields)
                selected_code = region_code({"properties": props}, ("ctprvn_cd", "CTPRVN_CD"))
                if selected != "이름 정보 없음" and selected != st.session_state.get("local_selected_sido"):
                    st.session_state.local_selected_sido = selected
                    st.session_state.local_selected_sido_code = selected_code
                    st.session_state.local_sido_fallback_select = selected
                    st.session_state.local_sigungu_geo = None
                    st.session_state.local_selected_sigungu = ""
                    st.session_state.local_selected_sigungu_code = ""
                    _reset_local_region_data()

            sido_names = [region_property(feature, name_fields) for feature in sido_features]
            sido_names = [name for name in sido_names if name != "이름 정보 없음"]
            if sido_names:
                current = st.session_state.get("local_selected_sido", "")
                sido_options = ["선택하세요"] + sido_names
                default_index = sido_options.index(current) if current in sido_names else 0
                # 위젯을 만들기 전에 선택 상태를 맞춰 지도 클릭과 목록 선택이 어긋나지 않게 합니다.
                if current in sido_names and st.session_state.get("local_sido_fallback_select") != current:
                    st.session_state.local_sido_fallback_select = current
                chosen = st.selectbox(
                    "지도에서 선택하지 못했거나 목록으로 선택하려면 지역을 고르세요.",
                    sido_options, index=default_index, key="local_sido_fallback_select",
                )
                if chosen and chosen != "선택하세요" and chosen != st.session_state.get("local_selected_sido"):
                    feature = next((f for f in sido_features if region_property(f, name_fields) == chosen), {})
                    st.session_state.local_selected_sido = chosen
                    st.session_state.local_selected_sido_code = region_code(feature, ("ctprvn_cd", "CTPRVN_CD"))
                    st.session_state.local_sigungu_geo = None
                    st.session_state.local_selected_sigungu = ""
                    st.session_state.local_selected_sigungu_code = ""
                    _reset_local_region_data()
                    st.rerun()

            selected = st.session_state.get("local_selected_sido", "")
            if selected:
                st.success(f"선택한 광역자치단체: {selected}")
                st.button(
                    "이 지역의 기초자치단체 보기", type="primary",
                    on_click=_set_local_level, args=("기초자치단체",),
                    key="go_local_sigungu",
                )

    else:
        selected_sido = st.session_state.get("local_selected_sido", "")
        selected_sido_code = st.session_state.get("local_selected_sido_code", "")
        if not selected_sido:
            st.info("먼저 '광역자치단체' 단계에서 시·도를 선택해 주세요.")
            st.button("광역자치단체 단계로 이동", on_click=_set_local_level, args=("광역자치단체",))
        else:
            st.caption(f"상위 지역: {selected_sido}")
            st.button("다른 광역자치단체 선택", key="local_change_sido", on_click=_change_local_sido)

            if st.session_state.get("local_sigungu_geo") is None:
                if st.button("시군구 경계 불러오기", type="primary"):
                    raw_geo, message = load_vworld_geojson("시군구")
                    if raw_geo:
                        filtered_geo, filter_message = filter_sigungu_geojson(raw_geo, selected_sido_code)
                        st.session_state.local_sigungu_geo = filtered_geo
                        message = filter_message
                    else:
                        st.session_state.local_sigungu_geo = None
                    st.session_state.local_sigungu_error = message
                    st.session_state.local_selected_sigungu = ""
                    st.session_state.local_selected_sigungu_code = ""
                    st.session_state.pop("local_sigungu_fallback_select", None)
                    st.session_state.local_sigungu_last_click_count = 0
                    _reset_local_region_data()
                    st.rerun()
            if st.session_state.get("local_sigungu_error"):
                st.warning(st.session_state.local_sigungu_error)
            geo = st.session_state.get("local_sigungu_geo")
            if geo:
                if geo.get("_truncated_notice"):
                    st.warning(geo["_truncated_notice"])
                map_object = build_admin_map(geo, 9)
                map_result = st_folium(
                    map_object, height=570, use_container_width=True,
                    returned_objects=["last_active_drawing", "last_object_clicked_tooltip", "last_object_clicked_count"],
                    key=f"local_sigungu_map_{selected_sido_code}",
                ) or {}
                sigungu_features = geo.get("features", [])
                name_fields = ("sig_kor_nm", "SIG_KOR_NM", "name", "NAME")
                click_count = map_result.get("last_object_clicked_count") or 0
                previous_click_count = st.session_state.get("local_sigungu_last_click_count", 0)
                new_map_click = click_count != previous_click_count
                if new_map_click:
                    st.session_state.local_sigungu_last_click_count = click_count
                drawing = map_result.get("last_active_drawing") if new_map_click else None
                clicked_feature = drawing if isinstance(drawing, dict) and drawing.get("properties") else None
                if new_map_click and clicked_feature is None:
                    clicked_feature = _selected_feature_by_tooltip(
                        sigungu_features, map_result.get("last_object_clicked_tooltip"), name_fields
                    )
                if clicked_feature:
                    props = clicked_feature.get("properties", {}) or {}
                    selected = region_property({"properties": props}, name_fields)
                    selected_code = region_code({"properties": props}, ("sig_cd", "SIG_CD"))
                    if selected != "이름 정보 없음" and selected != st.session_state.get("local_selected_sigungu"):
                        st.session_state.local_selected_sigungu = selected
                        st.session_state.local_selected_sigungu_code = selected_code
                        st.session_state.local_sigungu_fallback_select = selected
                        _reset_local_region_data()

                sigungu_names = [region_property(feature, name_fields) for feature in sigungu_features]
                sigungu_names = [name for name in sigungu_names if name != "이름 정보 없음"]
                if sigungu_names:
                    current = st.session_state.get("local_selected_sigungu", "")
                    sigungu_options = ["선택하세요"] + sigungu_names
                    default_index = sigungu_options.index(current) if current in sigungu_names else 0
                    if current in sigungu_names and st.session_state.get("local_sigungu_fallback_select") != current:
                        st.session_state.local_sigungu_fallback_select = current
                    chosen = st.selectbox(
                        "지도에서 선택하지 못했거나 목록으로 선택하려면 시·군·구를 고르세요.",
                        sigungu_options, index=default_index, key="local_sigungu_fallback_select",
                    )
                    if chosen and chosen != "선택하세요" and chosen != st.session_state.get("local_selected_sigungu"):
                        feature = next((f for f in sigungu_features if region_property(f, name_fields) == chosen), {})
                        st.session_state.local_selected_sigungu = chosen
                        st.session_state.local_selected_sigungu_code = region_code(feature, ("sig_cd", "SIG_CD"))
                        _reset_local_region_data()
                        st.rerun()
                if st.session_state.get("local_selected_sigungu"):
                    st.success(f"선택한 기초자치단체: {st.session_state.local_selected_sigungu}")

    selected_region = (
        st.session_state.get("local_selected_sigungu")
        if level == "기초자치단체"
        else st.session_state.get("local_selected_sido")
    )
    if selected_region:
        st.divider()
        render_section(f"{selected_region} 지역 정보")
        st.caption("선택 지역 이름과 지도 경계는 연결되지만, 주민등록 API 행정기관코드는 별도 공식 코드입니다. 두 코드 체계가 확인된 뒤 입력해야 정확한 통계가 조회됩니다.")
        admin_code = st.text_input(
            "주민등록 인구 API 행정기관코드 (필수)", key="local_population_admin_code",
            placeholder="공식 행정기관코드 입력",
        ).strip()
        c1, c2 = st.columns(2)
        with c1:
            if st.button("주민등록 인구·세대 자료 조회", use_container_width=True):
                month = korea_now().strftime("%Y%m")
                rows, message = data_go_call("population", {"statsYm": month, "admCd": admin_code})
                st.session_state.local_population_rows = rows
                st.session_state.local_population_error = message
            if st.session_state.get("local_population_error"):
                st.warning(st.session_state.local_population_error)
            if st.session_state.get("local_population_rows"):
                st.caption("이 API는 통·반 단위까지 제공할 수 있으므로, 반환된 행을 지역 전체 인구로 오인하거나 단순 합산하지 마세요.")
                table_view(st.session_state.local_population_rows, 100)
        with c2:
            st.caption("기수별·유형별 지방의회 의원 정수 통계이며, 선택 지역의 현재 의석 수와 일대일로 대응하지 않습니다.")
            if st.button("지방의회 의원 정수 자료 조회", use_container_width=True):
                rows, message = data_go_call("council", {})
                st.session_state.local_council_rows = rows
                st.session_state.local_council_error = message
            if st.session_state.get("local_council_error"):
                st.warning(st.session_state.local_council_error)
            if st.session_state.get("local_council_rows"):
                table_view(st.session_state.local_council_rows, 100)
        st.markdown("**지역 사회 통계**")
        st.caption("출생률·인구구성 등의 지표는 KOSIS에서 통계표 ID와 분류값을 지정해 조회합니다. 통계표별 기준연도와 산출 단위를 함께 확인해야 합니다.")
        if st.button("KOSIS 통계 탐색 화면으로 이동"):
            st.session_state.page = "정치 자료 탐색"
            st.session_state.api_selected_item = "kosis"
            st.rerun()


# ============================================================
# 16. 앱 사이드바 / 라우팅
# ============================================================

def render_sidebar():
    st.markdown("### 메뉴")
    nav_items = [
        ("홈", "⌂  홈", "home"),
        ("정치 퀴즈·미니게임", "▤  정치 퀴즈", "quiz"),
        ("정치 퀴즈·미니게임", "♧  미니게임", "games"),
        ("뉴스 속보", "▧  뉴스·속보", "news"),
        ("정치 자료 탐색", "⌕  정치 자료 탐색", "data"),
    ]
    for page, label, mode in nav_items:
        if st.button(label, key=f"nav_{mode}", use_container_width=True):
            st.session_state.page = page
            if mode == "quiz":
                st.session_state.quiz_mode = "today"
                st.session_state.quiz_active = False
                st.session_state.quiz_return_page = "홈"
            elif mode == "games":
                st.session_state.quiz_mode = "games"
                st.session_state.quiz_active = False
                st.session_state.quiz_return_page = "홈"
            elif mode == "data":
                st.session_state.api_selected_item = ""
            st.rerun()

    st.divider()
    st.markdown("### 공부하기")
    study_items = [
        ("정부 조직", "♧  정부 조직"),
        ("국회 조직", "🏛️  국회 조직"),
        ("법원 조직", "⚖️  법원 조직"),
        ("지방 정부", "🗺️  지방정부"),
        ("정보 확인 가이드", "☑  정보 확인 가이드"),
    ]
    for page_name, label in study_items:
        if st.button(label, key=f"nav_study_{page_name}", use_container_width=True):
            st.session_state.page = page_name
            if page_name == "지방 정부":
                st.session_state.local_level = "광역자치단체"
            st.session_state.org_detail = ""
            st.rerun()

    st.divider()
    st.button("☷  시뮬레이션 · 준비 중", disabled=True, use_container_width=True)
    if not QUIZ_PATH.exists():
        st.caption("Quiz.txt가 없으면 내장 예시 문제로 실행됩니다.")
    if not NEWS_PATH.exists():
        st.caption("NEWS.txt가 없으면 기본 RSS 목록으로 실행됩니다.")


def render_information_guide():
    render_hero("정보 확인 가이드", "정치 자료와 뉴스의 출처·기준 시점을 확인하는 방법입니다.")
    with st.container(border=True):
        st.markdown("### 공공데이터 확인")
        st.write("자료 제공기관, 조사 기준일, 지역 단위, 항목 정의를 함께 확인합니다. 통계 수치를 비교할 때는 동일한 기준연도와 집계 단위인지 살펴봅니다.")
        st.markdown("### 뉴스 확인")
        st.write("기사의 최초 보도 시각과 수정 시각, 원문 출처, 인용된 공식 자료를 확인합니다. 하나의 기사만으로 결론을 내리지 않고 관련 자료를 교차 확인합니다.")
        st.markdown("### 검색 결과 활용")
        st.write("검색 결과는 출처를 찾기 위한 출발점입니다. 실제 판단에는 기관의 원자료와 언론사의 원문을 확인합니다.")


def main():
    initialize_state()
    quiz_mtime = QUIZ_PATH.stat().st_mtime if QUIZ_PATH.exists() else 0.0
    quiz_questions, quiz_file_exists, quiz_issues = load_quiz_file(quiz_mtime)

    # 첨부된 시안처럼 제목·설명 아래에 메뉴 열과 본문 열을 나란히 배치합니다.
    with st.container(border=True):
        render_app_header()
        nav_col, content_col = st.columns([0.9, 2.55], gap="large")
        with nav_col:
            render_sidebar()
        with content_col:
            if quiz_issues:
                with st.expander(f"퀴즈 파일 확인 필요 ({len(quiz_issues)}건)", expanded=False):
                    for issue in quiz_issues:
                        st.warning(issue)
            if quiz_file_exists and not quiz_questions:
                st.error("Quiz.txt에서 유효한 문제를 찾지 못했습니다. 내장 예시로 자동 대체하지 않았습니다.")
            page = st.session_state.page
            if page == "홈":
                render_home(quiz_questions)
            elif page == "정치 퀴즈·미니게임":
                render_quiz_hub(quiz_questions)
            elif page == "뉴스 속보":
                render_news()
            elif page == "정치 자료 탐색":
                render_data_explorer()
            elif page == "정보 확인 가이드":
                render_information_guide()
            elif page == "정부 조직":
                render_government()
            elif page == "국회 조직":
                render_congress()
            elif page == "법원 조직":
                render_court()
            elif page == "지방 정부":
                render_local_government()
            elif page == "기관 상세":
                render_hero("기관 상세", "조직도에서 선택한 기관의 역할과 기능을 확인합니다.")
                render_org_detail()
            else:
                render_hero("페이지를 찾을 수 없습니다.", "홈 화면으로 돌아가 주세요.")
                if st.button("홈으로 이동"):
                    st.session_state.page = "홈"
                    st.rerun()

if __name__ == "__main__":
    main()
