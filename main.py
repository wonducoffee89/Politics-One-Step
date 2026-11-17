# -*- coding: utf-8 -*-
"""
정치 한 걸음
Streamlit 메인 앱

저장소 파일
- main.py
- Quiz.txt
- NEWS.txt
- requirements.txt
- README.md
- 지역코드_연계표.xlsx (사용자 편집 가능한 지역·API 코드북)
- secrets_example.toml (설정 참고용)
- tests/test_core.py (개발 검수용)

Streamlit Community Cloud > App settings > Secrets
[API_KEYS]
ASSEMBLY_KEY = "열린국회정보 공통 인증키"
DATA_GO_KR_KEY = "공공데이터포털 개인 인증키 (선거 2 + 행안부 5개 API 공통)"
KOSIS_KEY = "KOSIS 인증키"
VWORLD_KEY = "VWorld 인증키"

[APP]
VWORLD_DOMAIN = "https://실제-배포된-앱-주소"

중요:
- 승인된 12개 API 서비스는 발급처별 공통 인증키 4개로 관리합니다.
- 국회사무처 3개 API는 ASSEMBLY_KEY 하나를 공유합니다.
- 중앙선거관리위원회 2개와 행정안전부 5개 API는 DATA_GO_KR_KEY 하나를 공유합니다.
- KOSIS와 VWorld는 각각 별도 키를 사용합니다.
- 요청 주소와 API 매개변수는 코드의 API_ITEMS 및 API 어댑터에 정의합니다.
- 실제 인증키는 코드나 GitHub에 저장하지 않습니다.
- 정부디렉터리시스템 표준 API는 신청 대기 중이므로 사용하지 않습니다.
- API 오류는 해당 영역에만 표시하고 앱 전체는 계속 작동합니다.
"""

from __future__ import annotations

import calendar
import hashlib
import html
import json
import math
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
REGION_CODEBOOK_PATH = BASE_DIR / "지역코드_연계표.xlsx"
# 친구가 만든 Streamlit 앱 주소를 나중에 이 변수에 넣으면 시뮬레이션 화면에 삽입됩니다.
SIMULATION_APP_URL = ""
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
    .api-card {border:1px solid var(--border-color, #dedede); border-radius:14px; padding:.9rem; min-height:176px; background:var(--secondary-background-color);}
    .api-card-title {font-weight:800; font-size:1rem; margin:.25rem 0;}
    .api-card-desc {color:var(--secondary-text-color); font-size:.84rem; line-height:1.5;}
    .news-card {border:1px solid var(--border-color, #dedede); border-radius:12px; padding:.72rem .85rem; margin:.4rem 0; background:var(--secondary-background-color);}
    .news-title {font-weight:700; line-height:1.5; margin:.2rem 0;}
    .news-meta {font-size:.78rem; color:var(--secondary-text-color); margin-bottom:.35rem;}
    .news-summary {font-size:.88rem; line-height:1.55;}
    .org-node {border:1px solid var(--border-color, #dedede); border-radius:12px; padding:.9rem; text-align:center; background:var(--secondary-background-color); margin:.25rem 0; min-height:76px;}
    .org-node-hover {cursor:help; transition:border-color .15s ease, box-shadow .15s ease;}
    .org-node-hover:hover {border-color:var(--primary-color); box-shadow:0 2px 10px rgba(0,0,0,.08);}
    .org-node-title {font-weight:750; font-size:1rem; color:var(--text-color);}
    .org-node-role {font-size:.88rem; color:var(--secondary-text-color); margin-top:.3rem; line-height:1.45;}
    .org-node-icon {display:block; font-size:1.2rem; margin-bottom:.2rem;}
    .org-node strong {font-size:1rem;}
    .org-node small {color:var(--secondary-text-color);}
    div[data-testid="stButton"] > button {white-space:pre-wrap; line-height:1.45;}
    .region-metric {border:1px solid var(--border-color, #dedede);border-radius:12px;padding:.8rem .9rem;min-height:112px;background:var(--secondary-background-color);}
    .region-metric .metric-name {font-size:.88rem;color:var(--secondary-text-color);margin-bottom:.35rem;}
    .region-metric .metric-value {font-size:1.18rem;font-weight:800;line-height:1.35;overflow-wrap:anywhere;}
    .region-metric .metric-meta {font-size:.75rem;color:var(--secondary-text-color);margin-top:.35rem;}
    .org-arrow {text-align:center;color:var(--secondary-text-color);font-size:1.1rem;padding:.25rem 0;}
    div[data-testid="stVerticalBlock"] {gap:.55rem;}
    div[data-testid="stMetric"] {border:1px solid var(--border-color, #dedede); border-radius:12px; padding:.7rem;}
    div[data-testid="stSidebar"] {min-width:250px;}
    .tiny-note {font-size:.82rem; color:var(--secondary-text-color);}

    :root {
      --pastel-blue:#EAF4FF; --pastel-sky:#E7F7FB; --pastel-pink:#FFF0F5;
      --pastel-orange:#FFF3E8; --pastel-yellow:#FFF9DF; --pastel-green:#EAF7EF;
      --pastel-purple:#F2EEFF; --pastel-mint:#E7F7F2;
    }
    .app-header {background:linear-gradient(100deg,#F0F7FF 0%,#FFF5F0 50%,#F8F1FF 100%);border-radius:18px;padding:1rem 1.15rem;}
    .quiz-panel {background:linear-gradient(135deg,#F1F7FF,#FFF8F1);border-color:#DCE8F5;}
    .pastel-card {border:1px solid #E2E7EF;border-radius:14px;padding:.9rem;background:#FCFDFF;margin:.35rem 0;}
    .pastel-icon {display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;border-radius:14px;font-size:1.55rem;margin-right:.65rem;vertical-align:middle;}
    .pastel-icon.blue{background:var(--pastel-blue)} .pastel-icon.sky{background:var(--pastel-sky)}
    .pastel-icon.pink{background:var(--pastel-pink)} .pastel-icon.orange{background:var(--pastel-orange)}
    .pastel-icon.yellow{background:var(--pastel-yellow)} .pastel-icon.green{background:var(--pastel-green)}
    .pastel-icon.purple{background:var(--pastel-purple)} .pastel-icon.mint{background:var(--pastel-mint)}
    .news-card {background:linear-gradient(120deg,#FFFFFF,#F9FBFF);border-color:#E4EAF2;}
    .news-card .publisher-mark {display:inline-flex;align-items:center;gap:.35rem;color:#657184;font-size:.78rem;font-weight:650;margin-bottom:.3rem;}
    .news-card .publisher-mark img {width:20px;height:20px;object-fit:contain;border-radius:6px;background:#fff;padding:2px;border:1px solid #E8EDF3;}
    .news-card .publisher-fallback {width:20px;height:20px;align-items:center;justify-content:center;font-size:1rem;}
    .api-card {background:linear-gradient(140deg,#FFFFFF,#F8FBFF);border-color:#E2E8F0;min-height:160px;}
    .api-group-heading {display:flex;align-items:center;gap:.8rem;margin:.2rem 0 .7rem;}
    .api-group-heading img {width:48px;height:48px;object-fit:contain;padding:5px;border-radius:14px;background:#F5F8FC;border:1px solid #E6EBF2;}
    .api-group-heading .subtitle {font-size:.78rem;color:#87909D;font-weight:500;margin-left:.5rem;}
    .api-card-title {font-size:.98rem;}
    .quiz-feedback {border-radius:14px;padding:.85rem 1rem;margin:.65rem 0;border:1px solid #DCE6F0;background:#F7FAFF;}
    .sidebar-section-label {font-weight:800;font-size:.96rem;padding:.65rem .35rem .3rem;margin-top:.2rem;border-top:1px solid #E7EAF0;color:#46546A;}
    div[data-testid="stSidebar"] button {border-radius:12px;min-height:2.45rem;}
    div[data-testid="stButton"] > button {background:#F7FAFD!important;border:1px solid #E1E8F0!important;color:#33465B!important;border-radius:12px;transition:transform .12s ease, box-shadow .12s ease;white-space:pre-wrap;line-height:1.45;}
    div[data-testid="stLinkButton"] > a {background:#F7F4FF!important;border:1px solid #E6DFF7!important;color:#51466F!important;border-radius:12px;}
    div[class*="st-key-softbutton-blue"] div[data-testid="stButton"] > button {background:#EAF4FF!important;border-color:#D4E7FB!important;color:#234A70!important;}
    div[class*="st-key-softbutton-sky"] div[data-testid="stButton"] > button {background:#E7F7FB!important;border-color:#CDECF2!important;color:#285B66!important;}
    div[class*="st-key-softbutton-pink"] div[data-testid="stButton"] > button {background:#FFF0F5!important;border-color:#F6DCE7!important;color:#74465A!important;}
    div[class*="st-key-softbutton-orange"] div[data-testid="stButton"] > button {background:#FFF3E8!important;border-color:#F4E0CD!important;color:#765334!important;}
    div[class*="st-key-softbutton-yellow"] div[data-testid="stButton"] > button {background:#FFF9DF!important;border-color:#F1E9C5!important;color:#75652B!important;}
    div[class*="st-key-softbutton-green"] div[data-testid="stButton"] > button {background:#EAF7EF!important;border-color:#D4EBDD!important;color:#315E42!important;}
    div[class*="st-key-softbutton-purple"] div[data-testid="stButton"] > button {background:#F2EEFF!important;border-color:#E1DBF8!important;color:#55477B!important;}
    div[class*="st-key-softbutton-mint"] div[data-testid="stButton"] > button {background:#E7F7F2!important;border-color:#CFECE2!important;color:#315F51!important;}
    div[data-testid="stButton"] > button:hover, div[data-testid="stLinkButton"] > a:hover {transform:translateY(-1px);box-shadow:0 3px 10px rgba(60,80,110,.10);}
    .publisher-shortcut {border:1px solid #E7EAF0;border-radius:13px;padding:.55rem .45rem;background:#FBFCFE;text-align:center;min-height:100px;}
    .publisher-shortcut img {width:30px;height:30px;object-fit:contain;background:#fff;border:1px solid #E7EBF1;border-radius:8px;padding:3px;}
    .publisher-shortcut .publisher-fallback {width:30px;height:30px;align-items:center;justify-content:center;font-size:1.35rem;}
    .publisher-shortcut .name {font-size:.82rem;font-weight:700;color:#526174;margin:.25rem 0 .35rem;}
    div[class*="st-key-news-publisher-blue"] div[data-testid="stLinkButton"] > a {background:#EAF4FF!important;border-color:#D4E7FB!important;color:#234A70!important;}
    div[class*="st-key-news-publisher-sky"] div[data-testid="stLinkButton"] > a {background:#E7F7FB!important;border-color:#CDECF2!important;color:#285B66!important;}
    div[class*="st-key-news-publisher-pink"] div[data-testid="stLinkButton"] > a {background:#FFF0F5!important;border-color:#F6DCE7!important;color:#74465A!important;}
    div[class*="st-key-news-publisher-orange"] div[data-testid="stLinkButton"] > a {background:#FFF3E8!important;border-color:#F4E0CD!important;color:#765334!important;}
    div[class*="st-key-news-publisher-yellow"] div[data-testid="stLinkButton"] > a {background:#FFF9DF!important;border-color:#F1E9C5!important;color:#75652B!important;}
    div[class*="st-key-news-publisher-green"] div[data-testid="stLinkButton"] > a {background:#EAF7EF!important;border-color:#D4EBDD!important;color:#315E42!important;}
    div[class*="st-key-news-publisher-purple"] div[data-testid="stLinkButton"] > a {background:#F2EEFF!important;border-color:#E1DBF8!important;color:#55477B!important;}
    .api-group-logo {display:flex;align-items:center;justify-content:center;width:52px;height:52px;border-radius:15px;background:#F7FAFD;border:1px solid #E3EAF2;overflow:hidden;}
    .api-group-logo img {width:38px;height:38px;object-fit:contain;}
    .api-group-logo .fallback {font-size:1.8rem;line-height:1;}
    .quiz-feedback.correct {background:#EDF8F0;border-color:#D5EBDD;}
    .quiz-feedback.incorrect {background:#FFF1F3;border-color:#F1D9DE;}
    .news-control {background:#F8FAFD;border:1px solid #E5EAF1;border-radius:12px;padding:.5rem .65rem;}
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
    markers = ("인증키", "전용키", "여기에_", "실제-배포", "실제 도메인", "placeholder", "your_")
    return any(marker in text for marker in markers)


API_PROVIDER_KEY_NAMES = ("ASSEMBLY_KEY", "DATA_GO_KR_KEY", "KOSIS_KEY", "VWORLD_KEY")

def api_key_status(key_name: str) -> str:
    """네 발급처별 인증키 중 해당 키가 등록되었는지 확인합니다."""
    value = get_secret("API_KEYS", key_name)
    if _is_placeholder(value):
        return "미등록"
    for other_name in API_PROVIDER_KEY_NAMES:
        if other_name == key_name:
            continue
        other_value = get_secret("API_KEYS", other_name)
        if not _is_placeholder(other_value) and other_value == value:
            return "중복"
    return "등록됨"


def api_key(key_name: str) -> str:
    """발급처별 공통 인증키를 반환합니다."""
    if key_name not in API_PROVIDER_KEY_NAMES or api_key_status(key_name) != "등록됨":
        return ""
    return get_secret("API_KEYS", key_name)


def api_key_error_message(key_name: str) -> str:
    status = api_key_status(key_name)
    if status == "중복":
        return f"Streamlit Secrets의 API_KEYS.{key_name} 값이 다른 발급처 키와 중복됩니다. 발급처별 키 네 개가 서로 올바른지 확인해 주세요."
    return f"Streamlit Secrets의 API_KEYS.{key_name}에 해당 발급처 인증키를 등록해 주세요."


def api_key_is_configured(key_name: str) -> bool:
    return api_key_status(key_name) == "등록됨"


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
국내|KBS|http://world.kbs.co.kr/rss/rss_news.htm?lang=k
국내|KBS|https://news.kbs.co.kr/rss/news.xml
국내|연합뉴스|https://www.yna.co.kr/rss/politics.xml
국제|연합뉴스|https://www.yna.co.kr/rss/international.xml
국내|연합뉴스|https://www.yna.co.kr/rss/news.xml
국제|BBC|http://feeds.bbci.co.uk/news/world/rss.xml
국제|BBC|http://feeds.bbci.co.uk/news/politics/rss.xml
국제|CNN|http://rss.cnn.com/rss/edition_world.rss
국제|CNN|http://rss.cnn.com/rss/cnn_allpolitics.rss
국제|Reuters|https://www.reuters.com/arc/outboundfeeds/rss/world/
국제|AP|https://feedx.net/rss/ap.xml
국제|AFP·France24|https://www.afp.com/en/actus/afp_communique/all/feed
국제|AFP·France24|https://www.france24.com/en/rss
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
                    article["region"] = source["region"]
                    article["feed_url"] = source["url"]
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
# 5. 12개 API 카탈로그와 발급처별 공통 인증키 호출 어댑터
# ============================================================

API_GROUPS = [
    {
        "id": "assembly", "name": "국회 정보", "icon": "🏛️", "subtitle": "입법부 · 국회사무처", "logo": "https://assembly.go.kr/",
        "items": ["member", "vote", "schedule"],
    },
    {
        "id": "election", "name": "선거 정보", "icon": "🗳️", "subtitle": "중앙선거관리위원회", "logo": "https://www.nec.go.kr/",
        "items": ["winner", "candidate"],
    },
    {
        "id": "government", "name": "정부 정보", "icon": "🏢", "subtitle": "행정부 · 행정안전부", "logo": "https://www.mois.go.kr/",
        "items": ["benefit", "staff", "suborg"],
    },
    {
        "id": "local", "name": "지방정부 정보", "icon": "🗺️", "subtitle": "지방행정 · 행정안전부", "logo": "https://www.mois.go.kr/",
        "items": ["council", "population"],
    },
    {
        "id": "statistics", "name": "국가 통계", "icon": "📊", "subtitle": "국가데이터처 · KOSIS", "logo": "https://kosis.kr/",
        "items": ["kosis"],
    },
    {
        "id": "map", "name": "공간정보", "icon": "🌐", "subtitle": "국토교통부 · VWorld", "logo": "https://www.vworld.kr/",
        "items": ["vworld"],
    },
]

API_ITEMS = {
    "member": {
        "title": "국회의원 정보 통합 API", "short": "국회의원",
        "description": "국회의원 이름·정당·지역구 등 기본 정보를 조회합니다.",
        "group": "국회", "key": "ASSEMBLY_KEY",
        "url": "https://open.assembly.go.kr/portal/openapi/ALLNAMEMBER",
        "status": "요청 주소 확인",
        "source_url": "https://open.assembly.go.kr/",
    },
    "vote": {
        "title": "국회의원 본회의 표결정보", "short": "본회의 표결",
        "description": "국회의원의 본회의 안건별 찬성·반대·기권 등 표결 자료입니다.",
        "group": "국회", "key": "ASSEMBLY_KEY",
        "url": "https://open.assembly.go.kr/portal/openapi/nojepdqqaweusdfbi",
        "status": "국회 대수·의안 ID 입력 필요",
        "source_url": "https://open.assembly.go.kr/",
    },
    "schedule": {
        "title": "국회일정 통합 API", "short": "국회일정",
        "description": "본회의·위원회 일정과 의정활동 일정을 조회합니다.",
        "group": "국회", "key": "ASSEMBLY_KEY",
        "url": "https://open.assembly.go.kr/portal/openapi/ALLSCHEDULE",
        "status": "공식 국회일정 통합 API 코드 ALLSCHEDULE 사용",
        "source_url": "https://open.assembly.go.kr/",
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
        "status": "공식 이름 검색변수 name 반영",
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
        "url": "https://apis.data.go.kr/1741000/NumberLocalCouncilMemberNumber/getNumberLocalCouncilMemberNumber",
        "status": "공식 getNumberLocalCouncilMemberNumber 사용",
        "source_url": "https://www.data.go.kr/data/15107372/openapi.do",
    },
    "population": {
        "title": "행정안전부 행정동별 주민등록 인구 및 세대현황", "short": "주민등록 인구",
        "description": "행정구역·통계년월별 인구와 세대 현황을 확인합니다.",
        "group": "지방행정", "key": "DATA_GO_KR_KEY",
        "url": "https://apis.data.go.kr/1741000/admmPpltnHhStus",
        "status": "공식 요청주소·요청변수 연결 (조회 기간 최대 3개월)",
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
        "description": "브이월드 WMTS 배경지도 위에 광역시도·시군구·읍면동 WFS 경계를 표시합니다.",
        "group": "지도", "key": "VWORLD_KEY",
        "url": "https://api.vworld.kr/req/wfs",
        "status": "WMTS 배경지도·WFS 경계 사용 (WMS 별도 미적용)",
        "source_url": "https://www.vworld.kr/",
    },
}

API_KEY_NAMES = {item_id: item["key"] for item_id, item in API_ITEMS.items()}


def validate_api_key_configuration():
    """12개 API 서비스가 발급처별 인증키 네 개에 정확히 연결됐는지 검사합니다."""
    expected_keys = {"ASSEMBLY_KEY", "DATA_GO_KR_KEY", "KOSIS_KEY", "VWORLD_KEY"}
    expected_items = {
        "member", "vote", "schedule", "winner", "candidate", "benefit",
        "staff", "suborg", "council", "population", "kosis", "vworld",
    }
    if set(API_ITEMS) != expected_items:
        raise RuntimeError("API_ITEMS의 12개 서비스 구성이 예상 목록과 다릅니다.")
    keys = {item.get("key", "") for item in API_ITEMS.values()}
    if keys != expected_keys:
        raise RuntimeError("12개 API의 인증키 연결이 네 발급처 키와 일치하지 않습니다.")
    return True


validate_api_key_configuration()


def open_assembly_call(item_id: str, extra=None):
    """열린국회정보 API 3종은 하나의 ASSEMBLY_KEY로 호출합니다."""
    item = API_ITEMS[item_id]
    key_name = item["key"]
    key = api_key(key_name)
    if not key:
        return [], api_key_error_message(key_name)
    url = item["url"]
    if not url:
        return [], "이 국회 API의 요청 주소가 코드에 등록되지 않았습니다. 개발자 확인이 필요합니다."
    if item_id == "vote":
        if not extra or not extra.get("AGE") or not extra.get("BILL_ID"):
            return [], "본회의 표결정보 조회에는 국회 대수(AGE)와 의안 ID(BILL_ID)가 필요합니다."
    params = {"KEY": key, "Type": "xml", "pIndex": 1, "pSize": 100}
    if extra:
        params.update(extra)
    return call_api(item["title"], url, params)


def _month_index(value: str):
    """YYYYMM을 월 순번으로 바꾸며, 형식이 아니면 None을 반환합니다."""
    value = str(value or "").strip()
    if not re.fullmatch(r"\d{6}", value):
        return None
    year, month = int(value[:4]), int(value[4:])
    if year < 1900 or not 1 <= month <= 12:
        return None
    return year * 12 + month - 1


def build_mois_population_params(api_key_value: str, admin_code: str, start_month: str,
                                 end_month: str | None = None, level="기초자치단체",
                                 page_no=1, num_of_rows=100):
    """행정안전부 주민등록 인구 API의 공식 요청변수를 구성합니다.

    공식 파라미터: admmCd, srchFrYm, srchToYm, lv, regSeCd, type, numOfRows, pageNo.
    조회 기간은 최대 3개월이며, 단일 월 조회는 시작·종료월에 같은 값을 넣습니다.
    """
    admin_code = str(admin_code or "").strip()
    start_month = str(start_month or "").strip()
    end_month = str(end_month or start_month).strip()
    start_index = _month_index(start_month)
    end_index = _month_index(end_month)
    if start_index is None or end_index is None:
        return None, "조회년월은 YYYYMM 형식이어야 하며 월은 01~12 범위여야 합니다."
    if start_month < "202210" or end_month < "202210":
        return None, "이 API는 2022년 10월 이후 자료를 조회할 수 있습니다."
    if start_index > end_index:
        return None, "조회 시작년월은 종료년월보다 늦을 수 없습니다."
    if end_index - start_index > 2:
        return None, "한 번의 조회 기간은 최대 3개월입니다. 기간을 나누어 조회해 주세요."
    if not admin_code or not admin_code.isdigit():
        return None, "주민등록 행정기관코드는 숫자로 입력해야 합니다. VWorld 법정구역 코드와 다를 수 있습니다."

    level_map = {
        "광역자치단체": "5", "시도": "5", "시·도": "5",
        "기초자치단체": "6", "시군구": "6", "시·군·구": "6",
        "광역시도 단위": "1", "시군구 단위": "2", "읍면동 단위": "3",
        "읍면동 통반 단위": "4", "단일 시도 단위": "5",
        "단일 시군구 단위": "6", "단일 읍면동 단위": "7",
    }
    level_value = level_map.get(str(level).strip(), str(level).strip())
    if level_value not in {"1", "2", "3", "4", "5", "6", "7"}:
        return None, "조회결과구분(lv)은 1~7 중에서 선택해야 합니다."
    try:
        page_no = int(page_no)
        num_of_rows = int(num_of_rows)
    except (TypeError, ValueError):
        return None, "페이지 번호와 페이지당 건수는 숫자로 입력해야 합니다."
    if page_no < 1 or not 1 <= num_of_rows <= 100:
        return None, "페이지 번호는 1 이상, 페이지당 건수는 1~100이어야 합니다."

    return {
        "serviceKey": api_key_value,
        "admmCd": admin_code,
        "srchFrYm": start_month,
        "srchToYm": end_month,
        "lv": level_value,
        "regSeCd": "1",
        "type": "JSON",
        "numOfRows": num_of_rows,
        "pageNo": page_no,
    }, ""


def filter_public_service_rows(rows, keyword: str):
    """서비스명 서버 필터가 공식 목록 명세에 없으므로 현재 페이지를 안전하게 로컬 검색합니다."""
    keyword = str(keyword or "").strip()
    if not keyword:
        return rows, ""
    needle = re.sub(r"\s+", "", keyword).casefold()
    fields = ("서비스명", "서비스목적요약", "서비스분야", "지원대상", "지원내용", "소관기관명")
    matched = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        haystack = " ".join(str(row.get(field, "")) for field in fields)
        if needle in re.sub(r"\s+", "", haystack).casefold():
            matched.append(row)
    if matched:
        return matched, ""
    return [], "현재 조회한 페이지에서 검색어와 일치하는 공공서비스가 없습니다. 페이지 번호를 바꾸거나 검색어를 확인해 주세요."


def data_go_call(item_id: str, extra=None):
    """공공데이터포털 개인 키 하나를 NEC 2개·행안부 5개 API에 공통 사용합니다."""
    if item_id not in API_ITEMS:
        return [], "등록되지 않은 공공데이터 항목입니다."

    item = API_ITEMS[item_id]
    key_name = item["key"]
    key = api_key(key_name)
    if not key:
        return [], api_key_error_message(key_name)
    url = item["url"]
    extra = extra or {}
    params = {
        "serviceKey": key,
        "pageNo": 1,
        "numOfRows": 100,
        "resultType": "json",
    }
    benefit_keyword = ""

    if item_id == "winner":
        if not extra.get("sgId") or not extra.get("sgTypecode"):
            return [], "당선인 조회에는 선거 ID(sgId)와 선거종류코드(sgTypecode)가 필요합니다."
        params.update(extra)
    elif item_id == "candidate":
        # 중앙선거관리위원회 후보자 통합검색 공식 명세의 이름 검색변수는 name입니다.
        candidate_name = str(extra.get("name", "")).strip()
        if not candidate_name:
            return [], "후보자 통합검색은 이름 검색어가 필요합니다."
        params["name"] = candidate_name
    elif item_id in ("staff", "suborg"):
        params["type"] = "xml"
        params.pop("resultType", None)
        if item_id == "staff" and extra.get("bas_yy"):
            if not re.fullmatch(r"\d{4}", str(extra["bas_yy"]).strip()):
                return [], "기준년도는 YYYY 형식으로 입력해 주세요."
            params["bas_yy"] = str(extra["bas_yy"]).strip()
    elif item_id == "benefit":
        # 공식 목록 API에는 서비스명 LIKE 검색변수가 없어, 현재 페이지를 수신한 뒤 로컬에서 검색합니다.
        url = item["url"]
        benefit_keyword = str(extra.get("keyword", "")).strip()
        try:
            page = int(extra.get("page", 1))
        except (TypeError, ValueError):
            return [], "페이지 번호는 1 이상의 정수로 입력해 주세요."
        if page < 1:
            return [], "페이지 번호는 1 이상의 정수로 입력해 주세요."
        params = {"serviceKey": key, "page": page, "perPage": 100, "returnType": "JSON"}
    elif item_id == "council":
        # 공공데이터포털 공식 명세의 고정 요청 주소를 사용합니다.
        params["type"] = "xml"
        params.pop("resultType", None)
    elif item_id == "population":
        # 공공데이터포털 공식 명세의 요청주소·변수명을 그대로 사용합니다.
        month = str(extra.get("month") or extra.get("statsYm", "")).strip()
        start_month = str(extra.get("start_month") or month).strip()
        end_month = str(extra.get("end_month") or month).strip()
        admin_code = str(extra.get("admin_code") or extra.get("admCd", "")).strip()
        level = extra.get("level", "기초자치단체")
        population_params, error = build_mois_population_params(
            key, admin_code, start_month, end_month, level,
            page_no=extra.get("pageNo", 1), num_of_rows=extra.get("numOfRows", 100),
        )
        if error:
            return [], error
        params = population_params
        url = item["url"]

    if extra and item_id not in ("winner", "candidate", "benefit", "population", "staff"):
        params.update(extra)
    rows, message = call_api(item["title"], url, params)
    if item_id == "benefit" and not message and benefit_keyword:
        return filter_public_service_rows(rows, benefit_keyword)
    return rows, message

KOSIS_VIEW_CODE_LABELS = {
    "MT_ZTITLE": "국내통계 · 주제별",
    "MT_OTITLE": "국내통계 · 기관별",
    "MT_GTITLE01": "e-지방지표 · 주제별",
    "MT_GTITLE02": "e-지방지표 · 지역별",
    "MT_GTITLE03": "e-지방지표 · 테마별",
}


def kosis_list_call(parent_id: str, view_code: str):
    key = api_key("KOSIS_KEY")
    if not key:
        return [], api_key_error_message("KOSIS_KEY")
    if not parent_id.strip():
        return [], "KOSIS 통계목록을 조회하려면 목록 시작 ID(parentListId)가 필요합니다."
    if view_code not in KOSIS_VIEW_CODE_LABELS:
        return [], "공식 KOSIS 통계목록 유형에서 지원하는 뷰 코드를 선택해 주세요."
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
        return [], api_key_error_message("KOSIS_KEY")
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


PASTEL_COLORS = ("blue", "sky", "pink", "orange", "yellow", "green", "purple", "mint")

def soft_button(label: str, key: str, color: str = "blue", **kwargs):
    """버튼마다 은은한 파스텔 배경을 적용하는 공통 버튼입니다."""
    color = color if color in PASTEL_COLORS else "blue"
    safe_key = re.sub(r"[^a-zA-Z0-9_-]", "-", key)
    with st.container(key=f"softbutton-{color}-{safe_key}"):
        return st.button(label, key=key, **kwargs)


def favicon_url(homepage: str) -> str:
    """언론사·기관 홈페이지의 파비콘을 작은 로고로 보여 줍니다."""
    parsed = urlsplit(homepage or "")
    domain = parsed.netloc or parsed.path
    domain = domain.split("@")[ -1 ].split(":")[0]
    return f"https://www.google.com/s2/favicons?domain={quote_plus(domain)}&sz=128" if domain else ""


# ============================================================
# 7. 퀴즈 상태 / 객관식 진행 / 결과 모달
# ============================================================

def initialize_state():
    initial = {
        "page": "홈",
        "quiz_active": False,
        "quiz_result_open": False,
        "quiz_answer_submitted": False,
        "quiz_today_completed_date": "",
        "quiz_questions": [],
        "quiz_current": 0,
        "quiz_answers": [],
        "quiz_right_count": 0,
        "quiz_title": "",
        "quiz_return_page": "정치 퀴즈",
        "home_daily_result": None,
        "news_focus": "",
        "live_candidate_pool": [],
        "local_region_data_cache": {},
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
        "local_stage": "sido",
        "local_sido_feature": None,
        "local_sigungu_feature": None,
        "local_sido_attempted": False,
        "local_sigungu_attempted": False,
        "local_population_rows": [],
        "local_population_error": "",
        "local_council_rows": [],
        "local_council_error": "",
        "local_kosis_rows": [],
        "local_kosis_error": "",
        "local_kosis_region_name": "",
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
    st.session_state.quiz_answer_submitted = False
    if return_page:
        st.session_state.quiz_return_page = return_page


@st.dialog("퀴즈 결과", width="large", dismissible=False)
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
            source = item.get("출처", "")
            if source and is_safe_http_url(source):
                st.link_button("문제의 공식 자료 출처", source, key=f"quiz_result_source_{number}")

    if st.button("결과 닫기 · 퀴즈 화면으로 돌아가기", type="primary", use_container_width=True):
        is_daily = str(st.session_state.get("quiz_title", "")).startswith("오늘의 퀴즈")
        completed = bool(st.session_state.quiz_questions) and len(st.session_state.quiz_answers) == len(st.session_state.quiz_questions)
        if is_daily and completed:
            st.session_state.quiz_today_completed_date = korea_today().isoformat()
            st.session_state.home_daily_result = {
                "완료": True, "푼문제": len(st.session_state.quiz_answers),
                "정답": correct, "정답률": (correct / total * 100) if total else 0,
            }
        st.session_state.quiz_active = False
        st.session_state.quiz_result_open = False
        st.session_state.quiz_answer_submitted = False
        target_page = "정치 퀴즈" if (is_daily and completed) else st.session_state.get("quiz_return_page", "정치 퀴즈")
        st.session_state.page = target_page
        if target_page == "정치 퀴즈":
            st.session_state.quiz_mode = "today"
        st.rerun()


def render_quiz_type_selector(quiz_questions):
    """오늘의 퀴즈 외에 선택할 수 있는 일반 객관식 연습 문제만 제공합니다."""
    st.divider()
    render_section("추가 학습")
    with st.container(border=True):
        st.markdown("<div style='text-align:center;font-size:2rem'>🎯</div><div style='text-align:center;font-weight:750'>객관식 연습 퀴즈</div>", unsafe_allow_html=True)
        if soft_button("객관식 연습 시작", "quiz_mode_multiple", color="orange", use_container_width=True):
            st.session_state.quiz_mode = "multiple"
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
        selected_sido = st.session_state.get("local_selected_sido", "")
        selected_region = st.session_state.get("local_selected_sigungu", "")
        nec_defaults = lookup_nec_region_params(selected_sido, selected_region)
        with c3:
            sido = st.text_input("시도명 (선택)", value=nec_defaults.get("sdName", selected_sido), key="live_winner_sido")
        with c4:
            district_name = st.text_input("선거구명 (선택)", value=nec_defaults.get("sggName", selected_region), key="live_winner_district")
        if nec_defaults.get("wiwName"):
            st.caption(f"지역코드 엑셀의 wiwName 후보: {nec_defaults['wiwName']} (NEC 작업별 변수 확인 후 사용)")
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

        st.divider()
        st.markdown("**후보자 경력 자료로 퀴즈 만들기**")
        st.caption("중앙선거관리위원회 후보자 통합검색은 이름을 기준으로 후보자의 경력·학력·정당·선거·당선 여부 등을 제공합니다. 여러 인물을 검색해 경력 자료를 모으면 비교형 퀴즈를 만들 수 있습니다.")
        candidate_name = st.text_input("후보자 이름 검색", placeholder="예: 이재명", key="live_candidate_name")
        if st.button("후보자 경력 검색 및 자료 모으기", key="live_candidate_fetch", disabled=not candidate_name.strip()):
            rows, message = data_go_call("candidate", {"name": candidate_name.strip()})
            st.session_state.live_candidate_error = message
            if rows:
                existing = st.session_state.get("live_candidate_pool", [])
                combined = existing + rows
                deduplicated = {}
                for row in combined:
                    try:
                        key = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                    except TypeError:
                        key = repr(row)
                    deduplicated.setdefault(key, row)
                st.session_state.live_candidate_pool = list(deduplicated.values())
                st.session_state.live_candidate_error = ""
        if st.session_state.get("live_candidate_error"):
            st.warning(st.session_state.live_candidate_error)
        candidate_pool = st.session_state.get("live_candidate_pool", [])
        if candidate_pool:
            normalized_candidates = [normalize_candidate_record(row) for row in candidate_pool]
            preview = [{
                "이름": item["이름"], "정당": item["정당"], "선거": item["선거"],
                "선거구": item["선거구"], "확인된 경력": " / ".join(item["경력"]) or "응답에 경력 필드 없음",
            } for item in normalized_candidates]
            st.caption(f"누적 검색 자료 {len(candidate_pool)}건 · 이름이 다른 인물 {len({x['이름'] for x in normalized_candidates if x['이름'] != '정보 없음'})}명")
            st.dataframe(pd.DataFrame(preview), use_container_width=True, hide_index=True, height=220)
            career_quiz = generate_candidate_career_quiz(candidate_pool)
            if career_quiz:
                if st.button("후보자 경력 퀴즈 시작", key="live_candidate_quiz_start", type="primary"):
                    begin_quiz([career_quiz], "실시간 정치인 경력 퀴즈", st.session_state.get("quiz_return_page", "홈"))
                    st.rerun()
            else:
                st.info("서로 다른 인물 2명 이상과, 비교할 수 있는 경력 자료가 충분히 모이면 경력 퀴즈를 만들 수 있습니다. 현재 응답에 경력 필드가 있는지도 확인해 주세요.")
            if st.button("누적 후보자 자료 비우기", key="live_candidate_clear"):
                st.session_state.live_candidate_pool = []
                st.rerun()


def render_quiz_session(quiz_questions):
    questions = st.session_state.quiz_questions
    if not questions:
        st.info("출제할 문제가 없습니다. Quiz.txt의 문제 형식을 확인해 주세요.")
        st.session_state.quiz_active = False
        return

    if st.session_state.quiz_result_open:
        show_quiz_result_dialog()
        return

    current = st.session_state.quiz_current
    if current >= len(questions):
        st.session_state.quiz_result_open = True
        st.rerun()
        return

    question = questions[current]
    left, right = st.columns([5, 1])
    with left:
        quiz_title = st.session_state.get("quiz_title") or "정치 퀴즈"
        st.markdown(f"### {html.escape(str(quiz_title))}")
        st.caption(f"{current + 1} / {len(questions)} 문제")
    with right:
        if soft_button("↪ 퀴즈 종료", "quiz_exit", color="pink", use_container_width=True):
            st.session_state.quiz_result_open = True
            st.rerun()
    st.progress((current + 1) / len(questions))

    with st.container(border=True):
        st.caption(question.get("분야", "오늘의 정치 상식"))
        st.markdown(f"### {html.escape(question['문제'])}")
        if not st.session_state.get("quiz_answer_submitted", False):
            selected = st.radio(
                "선택지", question["선택지"], key=f"session_answer_{current}",
                index=None, label_visibility="collapsed",
            )
            if soft_button("정답 제출", f"session_submit_{current}", color="blue", type="primary", disabled=selected is None, use_container_width=True):
                try:
                    correct_index = int(question["정답"]) - 1
                    correct_answer = question["선택지"][correct_index]
                except (ValueError, IndexError, TypeError):
                    st.error("문제의 정답 항목이 올바르지 않습니다. Quiz.txt의 정답 번호를 확인해 주세요.")
                    return
                is_correct = selected == correct_answer
                st.session_state.quiz_answers.append({
                    "문제": question["문제"], "선택답": selected, "정답": correct_answer,
                    "정답여부": is_correct, "해설": question.get("해설", ""),
                    "분야": question.get("분야", "실시간 정치자료"), "출처": question.get("출처", ""),
                })
                st.session_state.quiz_answer_submitted = True
                st.rerun()
        else:
            answer = st.session_state.quiz_answers[-1]
            if answer["정답여부"]:
                st.success(f"정답입니다! 선택한 답: {html.escape(str(answer['선택답']))}")
            else:
                st.error(f"오답입니다. 선택한 답: {html.escape(str(answer['선택답']))} · 정답: {html.escape(str(answer['정답']))}")
            st.markdown("**해설**")
            st.write(answer.get("해설") or "등록된 해설이 없습니다.")
            source = answer.get("출처", "")
            if source and is_safe_http_url(source):
                st.link_button("관련 자료 출처 확인", source)
            st.divider()
            if current + 1 < len(questions):
                if soft_button("다음 문제", f"quiz_next_{current}", color="green", type="primary", use_container_width=True):
                    st.session_state.quiz_current += 1
                    st.session_state.quiz_answer_submitted = False
                    st.rerun()
            else:
                if soft_button("오늘의 결과 보기" if str(st.session_state.get("quiz_title", "")).startswith("오늘의") else "퀴즈 결과 보기", "quiz_show_final_result", color="purple", type="primary", use_container_width=True):
                    st.session_state.quiz_result_open = True
                    st.rerun()

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
    """국회 API에 실제로 포함된 현역 의원 정보로 지역구 문제를 만듭니다."""
    members = [normalize_member_record(row) for row in member_rows]
    # 동일 의원이 여러 응답 행에 중복된 경우 선택지에서 중복되지 않도록 합니다.
    unique = {}
    for member in members:
        if member["이름"] != "정보 없음":
            unique.setdefault(member["이름"], member)
    members = list(unique.values())
    query = str(desired_district or "").strip()
    district_matches = [m for m in members if query.casefold() in m["지역구"].casefold()] if query else members
    if not district_matches or len(members) < 4:
        return None
    correct = random.choice(district_matches)
    distractors = [m["이름"] for m in members if m["이름"] != correct["이름"]]
    if len(distractors) < 3:
        return None
    options = random.sample(distractors, 3) + [correct["이름"]]
    random.shuffle(options)
    region_phrase = f"'{correct['지역구']}' 지역구" if correct["지역구"] != "정보 없음" else "자료에 표시된"
    return {
        "분야": "실시간 정치인",
        "문제": f"국회 API 자료에서 {region_phrase} 국회의원으로 확인되는 인물은 누구일까요?",
        "선택지": options,
        "정답": options.index(correct["이름"]) + 1,
        "해설": f"국회 API 응답에서 {correct['이름']} 의원의 지역구는 {correct['지역구']}, 정당은 {correct['정당']}으로 표시됩니다. 기준 시점과 원자료를 함께 확인하세요.",
        "난이도": "실시간 자료",
        "출처": "https://open.assembly.go.kr/",
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
        "출처": "https://www.data.go.kr/data/15000864/openapi.do",
    }


def normalize_candidate_record(row):
    """후보자 API의 실제 응답 필드 중 이름·선거·정당·경력만 정리합니다.

    API 제공기관이 필드명을 바꾸거나 복수 경력 필드를 보내는 경우를 고려해
    이름은 알려진 별칭을 우선 사용하고, 경력은 career/경력 키만 모읍니다.
    """
    if not isinstance(row, dict):
        return {"이름": "정보 없음", "정당": "정보 없음", "선거": "정보 없음", "선거구": "정보 없음", "경력": []}

    name = first_field(row, ["CNDDA_NM", "CAND_NM", "CANDIDATE_NM", "candidateName", "candidateNm", "name", "NAME", "성명", "후보자명", "후보자성명"])
    party = first_field(row, ["JD_NAME", "JD_NM", "jdName", "partyName", "POLY_NM", "정당명", "정당"])
    election = first_field(row, ["SG_NAME", "SG_NM", "electionName", "선거명", "선거"])
    district = first_field(row, ["SGG_NAME", "SGG_NM", "sggName", "선거구명", "선거구"])
    election_id = first_field(row, ["SG_ID", "SGID", "sgId", "선거ID", "선거 아이디"])
    election_type = first_field(row, ["SG_TYPECODE", "SG_TYPE_CODE", "sgTypecode", "선거종류코드"])

    careers = []
    for key, value in row.items():
        key_text = str(key).strip().lower()
        normalized = re.sub(r"[^0-9a-z가-힣]", "", key_text)
        if "career" not in normalized and "경력" not in normalized:
            continue
        candidate_value = safe_string(value, "")
        if candidate_value and candidate_value != "정보 없음":
            # 하나의 응답 필드 안에 줄바꿈/세미콜론으로 여러 이력이 들어온 경우만 분리합니다.
            for part in re.split(r"[\r\n;；]+", candidate_value):
                part = re.sub(r"\s+", " ", part).strip(" ·,|-")
                if part and part not in careers:
                    careers.append(part)

    return {
        "이름": name, "정당": party, "선거": election, "선거 ID": election_id,
        "선거종류": election_type, "선거구": district, "경력": careers, "raw": row,
    }


def generate_candidate_career_quiz(candidate_rows):
    """후보자 API가 반환한 경력 사실만으로 인물 경력 객관식 문제를 만듭니다.

    보기의 오답은 다른 후보자 응답에 실제로 기록된 경력에서 가져옵니다.
    서로 다른 인물의 경력 자료가 충분하지 않으면 문제를 만들지 않습니다.
    """
    normalized = [normalize_candidate_record(row) for row in candidate_rows if isinstance(row, dict)]
    people = {}
    for person in normalized:
        if person["이름"] == "정보 없음" or not person["경력"]:
            continue
        # 같은 이름의 후보자가 여러 선거·선거구에 등장할 수 있으므로 이름만으로 합치지 않습니다.
        identity = (
            person["이름"], person["선거 ID"], person["선거종류"],
            person["선거"], person["선거구"], person["정당"],
        )
        people.setdefault(identity, {**person, "경력": []})
        for career in person["경력"]:
            if career not in people[identity]["경력"]:
                people[identity]["경력"].append(career)

    career_pool = []
    for identity, person in people.items():
        for career in person["경력"]:
            career_pool.append((identity, career, person))
    if len(people) < 2:
        return None

    targets = [entry for entry in career_pool if sum(1 for other in career_pool if other[0] != entry[0] and other[1] != entry[1]) >= 3]
    if not targets:
        return None
    target_identity, target_career, target_person = random.choice(targets)
    target_name = target_person["이름"]
    distractors = list(dict.fromkeys(
        career for identity, career, _ in career_pool
        if identity != target_identity and career != target_career
    ))
    if len(distractors) < 3:
        return None
    choices = random.sample(distractors, 3) + [target_career]
    random.shuffle(choices)
    election_context = target_person["선거"] if target_person["선거"] != "정보 없음" else "후보자 통합검색 자료"
    district_context = f" {target_person['선거구']}" if target_person["선거구"] != "정보 없음" else ""
    return {
        "분야": "실시간 정치인 경력",
        "문제": f"{election_context}{district_context}에 출마한 {target_name}의 후보자 자료에 기록된 경력은 무엇일까요?",
        "선택지": choices,
        "정답": choices.index(target_career) + 1,
        "해설": f"중앙선거관리위원회 후보자 자료에서 {target_name}의 {election_context}{district_context} 관련 경력으로 '{target_career}'이(가) 확인됩니다. 동일 이름의 후보자가 있을 수 있으므로 선거 ID·선거구·정당 및 원자료를 함께 확인해야 합니다.",
        "난이도": "실시간 자료",
        "출처": "https://www.data.go.kr/data/15140045/openapi.do",
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
    """홈의 오늘의 문제를 보여주고, 전체 퀴즈 완료 상태와 별도 답변 상태를 구분합니다."""
    today_key = korea_today().isoformat()
    completed_today = st.session_state.get("quiz_today_completed_date") == today_key
    with st.container(border=True):
        title_col, badge_col = st.columns([4, 1])
        with title_col:
            st.markdown("### 오늘의 퀴즈")
        with badge_col:
            st.markdown("<div style='text-align:right'><span style='background:#d7f4e4;color:#08783b;padding:4px 10px;border-radius:20px;font-size:.82rem'>오늘의 문제</span></div>", unsafe_allow_html=True)
        st.caption("※ 국회·선거·행정부 관련 자료를 바탕으로 한 퀴즈가 제공됩니다.")
        st.caption("교과 퀴즈는 Quiz.txt에서 출제하고, 실시간 인물 퀴즈는 공식 정치인·선거 자료를 활용합니다.")

        if not quiz_questions:
            st.info("출제할 문제가 없습니다. Quiz.txt의 문제 형식을 확인해 주세요.")
        else:
            digest = int(korea_today().strftime("%Y%m%d"))
            today_question = quiz_questions[digest % len(quiz_questions)]
            if completed_today:
                st.success("🎉 오늘의 퀴즈 완료!")
                result = st.session_state.get("home_daily_result") or {}
                if result.get("푼문제") is not None:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("푼 문제", f"{result.get('푼문제', 0)}개")
                    m2.metric("정답", f"{result.get('정답', 0)}개")
                    m3.metric("정답률", f"{result.get('정답률', 0):.0f}%")
                st.caption("오늘의 문제 풀이가 완료되어 홈 화면에서는 새로운 답안을 받지 않습니다.")
                if soft_button("오늘의 퀴즈 결과 확인", "home_open_today_result", color="green", type="primary", use_container_width=True):
                    st.session_state.page = "정치 퀴즈"
                    st.session_state.quiz_mode = "today"
                    st.rerun()
            else:
                st.markdown("### 오늘의 정치 상식")
                st.markdown(f"<div style='font-size:1.18rem;line-height:1.6;margin:.25rem 0 .7rem'>{html.escape(today_question['문제'])}</div>", unsafe_allow_html=True)
                result = st.session_state.get("home_daily_result")
                # 결과 요약 딕셔너리와 홈의 1문항 답변 딕셔너리를 혼동하지 않습니다.
                if result and result.get("문제") != today_question["문제"]:
                    st.session_state.home_daily_result = None
                    result = None
                if not result:
                    selected = st.radio(
                        "선택지를 고르세요.", today_question["선택지"], index=None,
                        key=f"home_daily_choice_{today_key.replace('-', '')}", label_visibility="collapsed",
                    )
                    if st.button("정답 제출", type="primary", disabled=selected is None, key="home_submit"):
                        correct_answer = today_question["선택지"][int(today_question["정답"]) - 1]
                        st.session_state.home_daily_result = {
                            "문제": today_question["문제"],
                            "정답여부": selected == correct_answer,
                            "내답": selected,
                            "정답": correct_answer,
                            "해설": today_question.get("해설", "해설이 등록되지 않았습니다."),
                        }
                        st.rerun()
                else:
                    if result.get("정답여부"):
                        st.success("정답입니다!")
                    else:
                        st.error(f"오답입니다. 정답은 '{result.get('정답', '확인 필요')}'입니다.")
                    st.markdown("**해설**")
                    st.write(result.get("해설") or "등록된 해설이 없습니다.")
                    if soft_button("전체 정치 퀴즈로 이동", "home_to_quiz", color="blue", type="primary", use_container_width=True):
                        st.session_state.quiz_return_page = "정치 퀴즈"
                        st.session_state.quiz_mode = "today"
                        st.session_state.quiz_active = False
                        st.session_state.page = "정치 퀴즈"
                        st.rerun()

    st.write("")
    news_col, shortcut_col = st.columns([.78, 2.25], gap="large")
    with news_col:
        render_section("뉴스")
        if soft_button("🇰🇷  국내", "home_news_domestic", color="sky", use_container_width=True):
            st.session_state.news_focus = "국내"
            st.session_state.page = "뉴스 속보"
            st.rerun()
        if soft_button("🌐  국제", "home_news_global", color="orange", use_container_width=True):
            st.session_state.news_focus = "국제"
            st.session_state.page = "뉴스 속보"
            st.rerun()
    with shortcut_col:
        render_section("자료 바로가기")
        shortcut_items = [
            ("member", "👥", "국회의원"),
            ("vote", "🗳️", "본회의 표결"),
            ("schedule", "📅", "국회 일정"),
            ("winner", "🏅", "당선인"),
            ("candidate", "🔎", "후보자"),
            ("benefit", "🤝", "공공서비스"),
        ]
        for start in (0, 3):
            cols = st.columns(3)
            for col, (item_id, icon, label) in zip(cols, shortcut_items[start:start + 3]):
                with col:
                    if soft_button(f"{icon}\n{label}", f"home_api_{item_id}", color=PASTEL_COLORS[(start + len(label)) % len(PASTEL_COLORS)], use_container_width=True):
                        go_to_api_item(item_id)
        st.caption("선택하면 해당 공공자료의 설명과 원자료를 확인할 수 있습니다.")

# ============================================================
# 10. 화면: 정치 퀴즈
# ============================================================

def render_quiz_hub(quiz_questions):
    """오늘의 퀴즈를 기본 화면으로 바로 시작하고, 완료 후 객관식 연습을 제공합니다."""
    if st.session_state.quiz_active:
        render_quiz_session(quiz_questions)
        return

    today_done = st.session_state.get("quiz_today_completed_date") == korea_today().isoformat()
    if st.session_state.get("quiz_mode", "today") == "multiple" and not today_done:
        if not quiz_questions:
            render_hero("정치 퀴즈", "Quiz.txt의 문항을 확인해 주세요.")
            st.warning("출제할 문제가 없습니다.")
            return
        practice = list(quiz_questions)
        random.shuffle(practice)
        begin_quiz(practice[:min(10, len(practice))], "객관식 연습 퀴즈", "정치 퀴즈")
        st.rerun()
        return

    if today_done:
        render_hero("정치 퀴즈", "오늘의 정치 교과 퀴즈를 완료했습니다.")
        st.success("🎉 오늘의 퀴즈 완료!")
        result = st.session_state.get("home_daily_result") or {}
        m1, m2, m3 = st.columns(3)
        m1.metric("푼 문제", f"{result.get('푼문제', len(st.session_state.quiz_answers))}개")
        m2.metric("정답", f"{result.get('정답', sum(1 for x in st.session_state.quiz_answers if x.get('정답여부')))}개")
        m3.metric("정답률", f"{result.get('정답률', 0):.0f}%")
        if st.button("오늘의 퀴즈 결과 다시 보기", key="quiz_reopen_result", use_container_width=True):
            st.session_state.quiz_result_open = True
            st.rerun()
        if st.button("객관식 연습 퀴즈 시작", key="quiz_start_multiple_after_today", use_container_width=True):
            st.session_state.quiz_mode = "multiple"
            st.rerun()
    else:
        if not quiz_questions:
            render_hero("정치 퀴즈", "Quiz.txt의 문항을 확인해 주세요.")
            st.warning("출제할 문제가 없습니다. Quiz.txt의 문제 형식과 필수 항목을 확인해 주세요.")
            return
        # 날짜를 바탕으로 문항 순서를 고정해 새로고침해도 같은 오늘의 세트가 출제됩니다.
        ordered = list(quiz_questions)
        digest = int(korea_today().strftime("%Y%m%d"))
        offset = digest % len(ordered) if ordered else 0
        ordered = ordered[offset:] + ordered[:offset]
        begin_quiz(ordered[:min(10, len(ordered))], "오늘의 퀴즈", "정치 퀴즈")
        st.rerun()
        return

    st.divider()
    render_live_quiz_tools()

# ============================================================
# 11. 화면: 뉴스 (국내/국제 2열 + 각 목록 자체 스크롤)
# ============================================================

def _publisher_homepage(publisher: str, feed_url: str = "") -> str:
    """NEWS.txt의 언론사 이름과 RSS 주소로 홈페이지 바로가기를 구성합니다."""
    label = str(publisher or "").casefold()
    mapping = {
        "kbs": "https://news.kbs.co.kr/", "연합뉴스": "https://www.yna.co.kr/",
        "bbc": "https://www.bbc.com/news", "cnn": "https://edition.cnn.com/",
        "reuters": "https://www.reuters.com/", "ap": "https://apnews.com/",
        "afp": "https://www.afp.com/", "france24": "https://www.france24.com/",
    }
    for token, url in mapping.items():
        if token in label:
            return url
    host = urlsplit(feed_url or "").netloc.lower()
    if host.startswith("feeds."):
        host = host[6:]
    if host.startswith("rss."):
        host = host[4:]
    if host.startswith("world."):
        host = host[6:]
    if host.startswith("news."):
        host = host[5:]
    return f"https://{host}/" if host else "https://www.google.com/"


NEWS_PASTEL_PALETTES = [
    ("#F0F7FF", "#DDEBFA", "#416485"),
    ("#F0FAFC", "#DCEFF3", "#3E6871"),
    ("#FFF4F7", "#F7E1E8", "#815363"),
    ("#FFF7EF", "#F5E6D6", "#806044"),
    ("#FFFBE8", "#F2ECCB", "#766A34"),
    ("#F0F8F2", "#DDEEE2", "#456B50"),
    ("#F5F2FF", "#E8E0F8", "#5F527D"),
]
NEWS_PUBLISHER_SHORTCUT_COLORS = ("blue", "sky", "pink", "orange", "yellow", "green", "purple")


def news_publisher_palette(publisher: str):
    """언론사마다 중립적인 파스텔 색을 고정적으로 배정합니다."""
    digest = hashlib.sha256(str(publisher or "").encode("utf-8")).digest()
    return NEWS_PASTEL_PALETTES[digest[0] % len(NEWS_PASTEL_PALETTES)]


def publisher_symbol(publisher: str) -> str:
    """외부 파비콘이 로드되지 않을 때 보여줄 직관적인 색상 이모지 대체 아이콘입니다."""
    symbols = {
        "KBS": "📺", "연합뉴스": "📰", "BBC": "🌐", "CNN": "📡",
        "Reuters": "🌍", "AP": "🗞️", "AFP·France24": "🌎",
    }
    return symbols.get(str(publisher or ""), "📰")


def _news_article_html(article: dict) -> str:
    publisher = str(article.get("publisher", "언론사"))
    home = _publisher_homepage(publisher, article.get("feed_url", ""))
    icon = favicon_url(home)
    symbol = publisher_symbol(publisher)
    link = article.get("link", "")
    bg1, bg2, border_color = news_publisher_palette(publisher)
    title_html = (
        f'<a href="{html.escape(link, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(str(article.get("title", "제목 없음")))}</a>'
        if is_safe_http_url(link) else html.escape(str(article.get("title", "제목 없음")))
    )
    return (
        f'<div class="news-card" style="background:linear-gradient(120deg,{bg1},{bg2});border-color:{border_color}55">'
        f'<div class="publisher-mark"><img src="{html.escape(icon, quote=True)}" alt="" '
        f"""onerror="this.style.display='none';this.nextElementSibling.style.display='inline-flex'">"""
        f'<span class="publisher-fallback" style="display:none">{html.escape(symbol)}</span>{html.escape(publisher)}</div>' 
        f'<div class="news-title">{title_html}</div>'
        f'<div class="news-meta">{html.escape(str(article.get("published", "날짜 정보 없음")))}</div>'
        f'<div class="news-summary">{html.escape(str(article.get("summary", "")))}</div></div>'
    )


def filter_news_articles(articles, region="종합", publisher="전체 언론사", keyword="", sort_order="최신순"):
    """수집된 RSS 기사 안에서 범위·언론사·키워드를 필터링하고 정렬합니다."""
    filtered = [
        dict(item) for item in (articles or [])
        if region == "종합" or str(item.get("region", "")) == region
    ]
    if publisher and publisher != "전체 언론사":
        filtered = [item for item in filtered if str(item.get("publisher", "")) == publisher]
    needle = re.sub(r"\s+", "", str(keyword or "")).casefold()
    if needle:
        filtered = [
            item for item in filtered
            if needle in re.sub(r"\s+", "", " ".join((
                str(item.get("title", "")), str(item.get("summary", "")),
                str(item.get("publisher", "")),
            ))).casefold()
        ]
    if sort_order == "오래된순":
        filtered.sort(key=lambda item: int(item.get("published_timestamp", 0) or 0))
    elif sort_order == "언론사순":
        filtered.sort(key=lambda item: (str(item.get("publisher", "")), -int(item.get("published_timestamp", 0) or 0)))
    else:
        filtered.sort(key=lambda item: int(item.get("published_timestamp", 0) or 0), reverse=True)
    return filtered


def render_news():
    render_hero("뉴스·속보", "여러 언론사의 국내·국제 보도를 검색하고 원문 출처를 확인합니다.")
    grouped, grouped_errors, source_issues = collect_all_news()
    sources, _ = load_news_sources_with_issues()
    domestic, international = grouped["국내"], grouped["국제"]
    if source_issues:
        with st.expander(f"NEWS.txt 설정 확인 ({len(source_issues)}건)", expanded=False):
            for issue in source_issues:
                st.warning(issue)

    all_items = domestic + international
    for article in all_items:
        if not article.get("feed_url"):
            article["feed_url"] = ""

    focus = st.session_state.get("news_focus", "")
    default_view = focus if focus in ("국내", "국제") else "종합"
    view_options = ["종합", "국내", "국제"]
    filter_col, search_col, sort_col = st.columns([1.0, 2.3, 1.25])
    with filter_col:
        view_mode = st.selectbox("기사 범위", view_options, index=view_options.index(default_view), key="news_view_mode")
    publisher_options = ["전체 언론사"] + list(dict.fromkeys(x["publisher"] for x in sources))
    with search_col:
        keyword = st.text_input("키워드 검색", placeholder="기사 제목·요약·언론사 검색", key="news_keyword")
    with sort_col:
        sort_order = st.selectbox("정렬", ["최신순", "오래된순", "언론사순"], key="news_sort_order")
    publisher = st.selectbox("언론사", publisher_options, key="news_publisher_filter")

    filtered = filter_news_articles(all_items, view_mode, publisher, keyword, sort_order)

    st.caption(f"검색 결과 {len(filtered)}건 · 검색은 현재 수집된 RSS 기사에서 수행됩니다.")
    if view_mode == "종합" and publisher == "전체 언론사" and not keyword.strip():
        col_domestic, col_global = st.columns(2, gap="medium")
        for col, title, items in [(col_domestic, "🇰🇷 국내", domestic), (col_global, "🌐 국제", international)]:
            with col:
                st.markdown(f"### {title}")
                with st.container(height=610, border=True):
                    sorted_items = [x for x in filtered if x.get("region") == ("국내" if "국내" in title else "국제")]
                    for article in sorted_items:
                        st.markdown(_news_article_html(article), unsafe_allow_html=True)
                    if not sorted_items:
                        st.info("표시할 기사가 없습니다. RSS 응답과 NEWS.txt를 확인해 주세요.")
                errors = grouped_errors["국내" if "국내" in title else "국제"]
                if errors:
                    with st.expander(f"일부 RSS 연결 오류 ({len(errors)})"):
                        for err in errors:
                            st.caption(err)
    else:
        with st.container(height=620, border=True):
            for article in filtered:
                st.markdown(_news_article_html(article), unsafe_allow_html=True)
            if not filtered:
                st.info("검색 조건과 일치하는 기사가 없습니다. 검색어·언론사·국내외 범위를 바꿔 보세요.")

    st.divider()
    render_section("언론사 바로가기", "NEWS.txt에 등록된 언론사만 자동으로 표시합니다.")
    unique_outlets = []
    seen = set()
    for source in sources:
        if source["publisher"] in seen:
            continue
        seen.add(source["publisher"])
        unique_outlets.append((source["publisher"], _publisher_homepage(source["publisher"], source["url"])))
    cols = st.columns(min(7, max(1, len(unique_outlets))))
    for index, (name, url) in enumerate(unique_outlets):
        color = NEWS_PUBLISHER_SHORTCUT_COLORS[index % len(NEWS_PUBLISHER_SHORTCUT_COLORS)]
        with cols[index % len(cols)]:
            icon = favicon_url(url)
            symbol = publisher_symbol(name)
            with st.container(key=f"news-publisher-card-{color}-{index}"):
                st.markdown(
                    f'<div class="publisher-shortcut"><img src="{html.escape(icon, quote=True)}" alt="" '
                    f"""onerror="this.style.display='none';this.nextElementSibling.style.display='inline-flex'">"""
                    f'<span class="publisher-fallback" style="display:none">{html.escape(symbol)}</span>'
                    f'<div class="name">{html.escape(name)}</div></div>',
                    unsafe_allow_html=True,
                )
                st.link_button("홈페이지 바로가기", url, use_container_width=True, key=f"news_publisher_home_{index}")

# ============================================================
# 12. 화면: 정치 자료 탐색 - 6개 기관 그룹 / 12개 API
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


def render_api_catalog():
    render_hero("정치 자료 탐색", "공식 공공데이터를 읽기 쉬운 형태로 확인하고 교과 개념과 연결합니다.")
    st.caption("※ 국회·선거·행정부 자료는 퀴즈에도 활용됩니다. 자료의 기준일과 제공기관을 함께 확인하세요.")
    configured = sum(api_key_status(key) == "등록됨" for key in API_PROVIDER_KEY_NAMES)
    st.info(f"인증키 상태: {configured}/4개 · 12개 API 서비스는 발급처별 공통 키 네 개를 사용합니다.")

    palette = ("blue", "pink", "orange", "mint", "purple", "sky")
    for group_index, group in enumerate(API_GROUPS):
        st.divider()
        icon_col, title_col, count_col = st.columns([.65, 4.3, 1], gap="small")
        with icon_col:
            logo_url = favicon_url(group.get("logo", ""))
            st.markdown(
                f"<div class='api-group-logo {palette[group_index]}'>"
                f"<img src='{html.escape(logo_url, quote=True)}' alt='{html.escape(group['icon'], quote=True)}' "
                f"onerror=\"this.style.display='none';this.nextElementSibling.style.display='inline';\">"
                f"<span class='fallback' style='display:none'>{html.escape(group['icon'])}</span></div>",
                unsafe_allow_html=True,
            )
        with title_col:
            st.markdown(
                f"<div class='api-group-heading'><div><b style='font-size:1.16rem'>{html.escape(group['name'])}</b> "
                f"<span class='subtitle'>{html.escape(group.get('subtitle',''))}</span></div></div>",
                unsafe_allow_html=True,
            )
        with count_col:
            st.markdown(f"<div style='text-align:right;color:#8993A1;padding-top:.55rem;font-size:.84rem'>{len(group['items'])}개 자료</div>", unsafe_allow_html=True)

        columns = st.columns(min(3, len(group["items"])), gap="small")
        for index, item_id in enumerate(group["items"]):
            item = API_ITEMS[item_id]
            with columns[index % len(columns)]:
                color = palette[(group_index + index) % len(palette)]
                with st.container(key=f"api-card-{item_id}"):
                    st.markdown(
                        f"<div class='api-card' style='background:linear-gradient(145deg,#fff,{ {'blue':'#F3F8FF','pink':'#FFF5F8','orange':'#FFF8F0','mint':'#F1FAF7','purple':'#F7F5FF','sky':'#F1FAFC'}[color]})'>"
                        f"<div class='api-card-title'>{html.escape(item['short'])}</div>"
                        f"<div class='api-card-desc'>{html.escape(item['description'])}</div>"
                        f"<p class='tiny-note'><b>인증키</b> · {html.escape(api_key_status(item['key']))}</p>"
                        f"<p class='tiny-note'><b>교과 연계</b><br>{html.escape(API_EDUCATION.get(item_id, '정치 제도와 공공자료 이해'))}</p>"
                        f"<span style='font-size:.75rem;color:#778294;background:#fff;padding:3px 8px;border-radius:15px;border:1px solid #E7EBF1'>원자료 · 표 · 엑셀</span></div>",
                        unsafe_allow_html=True,
                    )
                    if soft_button("자료 자세히 보기", f"open_api_{item_id}", color=color, use_container_width=True):
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

    key_name = item.get("key", "")
    if key_name:
        if api_key_is_configured(key_name):
            st.caption(f"🔑 이 자료는 {key_name} 공통 인증키로 연결됩니다. 해당 발급처의 여러 API가 같은 키를 공유합니다.")
        else:
            st.warning(f"이 자료를 조회하려면 Streamlit Secrets의 [API_KEYS].{key_name}에 해당 발급처 인증키를 등록해 주세요.")

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
        nec_defaults = lookup_nec_region_params(
            st.session_state.get("local_selected_sido", ""),
            st.session_state.get("local_selected_sigungu", ""),
        )
        with c3:
            sd_name = st.text_input("시도명 (선택)", value=nec_defaults.get("sdName", ""), key="detail_winner_sido")
        with c4:
            sgg_name = st.text_input("선거구명 (선택)", value=nec_defaults.get("sggName", ""), key="detail_winner_sgg")
        if nec_defaults.get("wiwName"):
            st.caption(f"엑셀의 wiwName 후보: {nec_defaults['wiwName']} (endpoint별 요청변수 확인 필요)")
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
        month = st.text_input("조회년월 (YYYYMM)", value=korea_now().strftime("%Y%m"), key="detail_population_month")
        admin_code = st.text_input("행정기관코드 (필수)", key="detail_population_admin", help="공식 행정기관코드입니다. VWorld 법정구역 코드와 다를 수 있습니다.")
        level = st.selectbox(
            "조회결과 단위 (lv)",
            ["5", "6", "7", "1", "2", "3", "4"],
            format_func=lambda value: {
                "1": "광역시도 단위", "2": "시군구 단위", "3": "읍면동 단위",
                "4": "읍면동 통반 단위", "5": "단일 시도", "6": "단일 시군구", "7": "단일 읍면동",
            }[value],
            key="detail_population_level",
        )
        extra = {"month": month.strip(), "admin_code": admin_code.strip(), "level": level}
    elif item_id == "benefit":
        keyword = st.text_input("공공서비스 검색어 (선택)", key="detail_benefit_keyword")
        page = st.number_input("조회 페이지", min_value=1, max_value=1000, value=1, step=1, key="detail_benefit_page")
        st.caption("공식 목록 API에 서비스명 검색 변수가 없어, 선택한 페이지의 최대 100건을 받은 뒤 화면에서 검색합니다.")
        extra = {"keyword": keyword.strip(), "page": int(page)}
    elif item_id == "kosis":
        st.caption("KOSIS는 통계목록 ID와 통계표의 기관·항목·분류 코드가 필요합니다.")
        c1, c2 = st.columns(2)
        with c1:
            view_code = st.selectbox("통계 목록 유형", ["MT_GTITLE01", "MT_GTITLE02", "MT_GTITLE03", "MT_ZTITLE", "MT_OTITLE"], key="detail_kosis_view")
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
        return None, api_key_error_message("VWORLD_KEY")
    domain = get_secret("APP", "VWORLD_DOMAIN", "")
    parsed_domain = urlsplit(domain)
    if (
        _is_placeholder(domain)
        or parsed_domain.scheme != "https"
        or not parsed_domain.hostname
        or parsed_domain.username is not None
        or parsed_domain.password is not None
        or parsed_domain.path not in ("", "/")
        or parsed_domain.query
        or parsed_domain.fragment
    ):
        return None, "브이월드에 등록한 HTTPS 서비스 도메인만 APP.VWORLD_DOMAIN에 입력해 주세요. 경로나 쿼리는 제외합니다."
    # WFS 레이어명은 지역코드_연계표.xlsx에서 읽고, 확인된 공식 기본값으로만 대체합니다.
    layer = lookup_vworld_wfs_layer(level)
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


def population_admin_code_from_feature(feature):
    """WFS 속성에 주민등록 행정기관코드가 명시된 경우에만 자동 사용합니다.

    VWorld의 법정구역 코드(sig_cd 등)를 주민등록 행정기관코드로 간주하지 않습니다.
    """
    return region_code(feature, (
        "adm_cd", "ADM_CD", "admCd", "ADM_CD_10", "admin_code", "adminCode",
        "행정기관코드", "행정기관코드값",
    ))


def filter_sigungu_geojson(geojson, sido_code="", sido_name=""):
    """시도 코드 접두어를 우선 사용하고, 불일치 시 코드북의 현행 지역명으로 대조합니다."""
    if not geojson or not isinstance(geojson.get("features"), list):
        return None, "VWorld 시군구 경계 자료가 비어 있습니다."
    configured_field = lookup_vworld_property_field("lt_c_adsigg_info")
    name_field = lookup_vworld_name_field("lt_c_adsigg_info")
    name_fields = tuple([name_field] if name_field else []) + ("sig_kor_nm", "SIG_KOR_NM", "sig_nm", "sigungu_nm", "name", "NAME")
    code_fields = tuple([configured_field] if configured_field else []) + ("sig_cd", "SIG_CD", "sig_cd2", "SIG_CD2")
    filtered = []
    if sido_code:
        for feature in geojson.get("features", []):
            code = region_code(feature, code_fields)
            if code and code.startswith(str(sido_code)):
                filtered.append(feature)
    # WFS 코드 필드가 없거나 개편 후 코드 접두어가 달라졌으면 이름을 사용해 안전하게 대조합니다.
    if not filtered and sido_name:
        for feature in geojson.get("features", []):
            feature_name = region_property(feature, name_fields)
            if match_local_codebook_name(sido_name, feature_name):
                filtered.append(feature)
    # 코드가 없는 경우에도 코드북에 이름이 있는 지역만 지도 선택 대상으로 둡니다.
    elif filtered and sido_name:
        allowed = set(get_local_region_names(sido_name))
        matched = []
        for feature in filtered:
            feature_name = region_property(feature, name_fields)
            canonical = match_local_codebook_name(sido_name, feature_name)
            if canonical and (not allowed or canonical in allowed):
                matched.append(feature)
        if matched:
            filtered = matched
    if not filtered:
        return None, (
            "선택한 광역자치단체에 해당하는 현행 시·군·구 경계를 찾지 못했습니다. "
            "지역코드_연계표.xlsx의 VWorld 코드·필드명과 최신 행정구역 명칭을 확인해 주세요."
        )
    return {**geojson, "features": filtered}, ""


def build_admin_map(geojson, zoom):
    features = (geojson or {}).get("features", [])
    if not isinstance(features, list) or not features:
        raise ValueError("지도에 표시할 행정구역 경계가 없습니다.")
    properties = [feature.get("properties", {}) or {} for feature in features]
    configured_name_fields = [
        lookup_vworld_name_field("lt_c_adsido_info"),
        lookup_vworld_name_field("lt_c_adsigg_info"),
        lookup_vworld_name_field("lt_c_ademd_info"),
        lookup_vworld_name_field("lt_c_adri_info"),
    ]
    name_fields = tuple(dict.fromkeys([field for field in configured_name_fields if field] + [
        "ctp_kor_nm", "sig_kor_nm", "emd_kor_nm", "li_kor_nm", "name", "NAME"
    ]))
    # 모든 피처에 공통으로 존재하는 이름 필드만 툴팁으로 사용합니다.
    tooltip_field = next((field for field in name_fields if all(field in props for props in properties)), None)
    tooltip = folium.GeoJsonTooltip(fields=[tooltip_field], aliases=["행정구역"], sticky=True) if tooltip_field else None
    map_geojson = {"type": "FeatureCollection", "features": features}
    m = folium.Map(location=[36.3, 127.8], zoom_start=zoom, tiles=None, control_scale=True)
    vworld_key = api_key("VWORLD_KEY")
    if vworld_key:
        # VWorld 공식 Folium 예제의 WMTS Base 타일 경로를 사용합니다.
        # 이 URL은 브라우저에서 직접 호출되므로 VWorld 콘솔에서 등록 도메인을 제한해야 합니다.
        folium.TileLayer(
            tiles=f"https://api.vworld.kr/req/wmts/1.0.0/{quote_plus(vworld_key)}/Base/{{z}}/{{y}}/{{x}}.png",
            attr="공간정보 오픈플랫폼(브이월드)",
            name="브이월드 기본지도",
            overlay=False,
            control=True,
            show=True,
            max_zoom=19,
        ).add_to(m)
        # VWorld 타일 장애 시 사용자가 직접 전환할 수 있는 대체 배경입니다.
        folium.TileLayer(
            tiles="CartoDB positron",
            attr="CartoDB",
            name="대체 배경지도",
            overlay=False,
            control=True,
            show=False,
        ).add_to(m)
    else:
        folium.TileLayer(
            tiles="CartoDB positron",
            attr="CartoDB",
            name="대체 배경지도 (VWorld 키 미등록)",
            overlay=False,
            control=True,
            show=True,
        ).add_to(m)
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

ORG_DETAILS = {
    "president": {
        "title": "대통령", "head": "대통령", "parent": "국가 최고 행정부", 
        "duty": "국가원수이자 행정부 수반으로서 헌법과 법률이 정한 국가 운영 권한과 책임을 수행합니다.",
        "children": "대통령 소속기관 및 국무총리·중앙행정기관과 관련됩니다.",
        "scale": "기관별 인력은 행정안전부 공무원 정원 통계와 각 기관 자료로 확인합니다.",
        "note": "정부 조직도는 이해를 위한 상위 구조입니다. 모든 기관이 대통령의 직접 지휘를 받는다는 뜻은 아닙니다.",
        "source": "https://www.org.go.kr/"
    },
    "presidential": {
        "title": "대통령 소속기관", "head": "기관별 장(원장·위원장 등)", "parent": "대통령 관련 조직",
        "duty": "국가 감사, 국가안보, 정보, 경호 등 헌법과 법률에 따라 정해진 기능을 수행하는 기관들이 포함됩니다.",
        "children": "감사원·국가정보원·대통령비서실·국가안보실·대통령경호처 등. 기관별 법적 소속과 독립성은 각각 다릅니다.",
        "scale": "기관별 정원은 각 기관의 공식 자료를 기준으로 확인합니다.",
        "note": "화면은 대표 사례를 묶은 개요이며, 모든 기관의 세부 지휘 관계를 하나로 단순화하지 않습니다.",
        "source": "https://www.org.go.kr/"
    },
    "prime": {
        "title": "국무총리", "head": "국무총리", "parent": "대통령의 보좌 및 행정 각부 통할",
        "duty": "대통령을 보좌하고 행정 각부를 통할합니다.",
        "children": "국무조정실·국무총리비서실 및 법령상 국무총리 소속 기관과 관련됩니다.",
        "scale": "하부기구와 공무원 정원은 행정안전부 승인 통계로 확인합니다.",
        "note": "국무총리 소속기관과 중앙행정기관의 소속 관계는 기관별 법령·직제에 따라 다릅니다.",
        "source": "https://www.org.go.kr/"
    },
    "central": {
        "title": "중앙행정기관", "head": "기관 유형에 따라 장관·처장·청장·위원장 등", "parent": "정부조직법과 개별 설치 법령",
        "duty": "전국 범위의 국가 행정사무를 담당합니다. 부·처·청 등은 법적 설치 근거와 소속 관계가 서로 다릅니다.",
        "children": "부·처·청 및 법률에 따라 설치된 합의제 행정기관 등으로 구성됩니다.",
        "scale": "기관별 공무원 정원 및 하부기구 통계는 아래 행정안전부 자료 조회를 이용합니다.",
        "note": "중앙행정기관 수는 기준일에 따라 달라질 수 있습니다.",
        "source": "https://www.org.go.kr/intrcn/orgnzt/viewSystm.do"
    },
    "ministry": {
        "title": "부", "head": "장관", "parent": "대통령·국무총리 통할 아래 국가행정사무 수행",
        "duty": "기능별 또는 대상별로 국가 행정사무를 담당하는 행정각부입니다.",
        "children": "각 부의 소속청 및 소속기관은 개별 직제에 따릅니다.",
        "scale": "기준일 2026-10-02 정부기구도에 19부로 표시됩니다.",
        "note": "개별 부의 명칭과 소속기관은 정부조직 개편에 따라 변경될 수 있습니다.",
        "source": "https://www.org.go.kr/orgnzt/chart/viewEng.do"
    },
    "office": {
        "title": "처", "head": "처장", "parent": "주로 국무총리 소속",
        "duty": "여러 부에 관련되는 기능을 통합하거나 전문적인 행정 업무를 담당합니다.",
        "children": "각 처의 하부조직은 해당 기관의 직제에 따릅니다.",
        "scale": "기준일 2026-10-02 정부기구도에 6처로 표시됩니다.",
        "note": "처의 법적 소속·권한은 개별 설치 법령을 함께 확인해야 합니다.",
        "source": "https://www.org.go.kr/intrcn/orgnzt/viewSystm.do"
    },
    "agency": {
        "title": "청", "head": "청장", "parent": "일반적으로 소관 행정각부 소속",
        "duty": "독자성이 높고 집행적인 행정사무를 전문적으로 담당합니다.",
        "children": "소속기관과 하부기구는 각 청의 직제에 따릅니다.",
        "scale": "기준일 2026-10-02 정부기구도에 19청으로 표시됩니다.",
        "note": "모든 청이 동일한 부에 소속되는 것은 아니므로 기관별 소속 관계를 확인합니다.",
        "source": "https://www.org.go.kr/intrcn/orgnzt/viewSystm.do"
    },
    "commission": {
        "title": "위원회", "head": "위원장", "parent": "설치 법률에 따른 독립·소속 합의제 기관",
        "duty": "정책 심의·의결, 규제·감독 등 법률로 정한 합의제 행정 기능을 수행합니다.",
        "children": "상임위원·사무처 등 세부 구성은 위원회마다 다릅니다.",
        "scale": "기준일 2026-10-02 정부기구도에 6위원회로 표시됩니다.",
        "note": "위원회는 설치 근거와 소속이 서로 다를 수 있습니다.",
        "source": "https://www.org.go.kr/intrcn/orgnzt/viewSystm.do"
    },
    "institute": {
        "title": "원", "head": "원장", "parent": "기관별 설치 법령",
        "duty": "감사·연구·통계 등 기관별 고유 기능을 수행합니다.",
        "children": "원별 세부 조직과 소속은 공식 조직도를 확인합니다.",
        "scale": "정부기구도 참고 분류에 포함된 유형입니다. 기관별 수와 범위는 공식 기준일 자료를 확인합니다.",
        "note": "원은 단일한 소속 형태를 의미하지 않습니다.",
        "source": "https://www.org.go.kr/"
    },
    "office_unit": {
        "title": "실", "head": "실장", "parent": "대통령·국무총리 또는 각 기관 내부 조직",
        "duty": "정책 조정·지원·기획 등 기관별 기능을 수행합니다.",
        "children": "실·국·과 등 하부조직은 해당 기관 직제에 따릅니다.",
        "scale": "정부기구도에 표시된 보조기관 유형입니다. 세부 정원은 기관별 자료로 확인합니다.",
        "note": "실은 기관 자체와 구별되는 내부·보조 조직일 수 있습니다.",
        "source": "https://www.org.go.kr/"
    },
    "assembly": {
        "title": "대한민국 국회", "head": "국회의장", "parent": "입법부·국민의 대표기관",
        "duty": "법률 제정, 국가 예산 심의·확정, 국정 감시 등 헌법상 권한을 수행합니다.",
        "children": "국회의장단, 위원회, 국회사무처, 국회 소속기관 등으로 구성됩니다.",
        "scale": "의원 구성·위원회·의사일정은 열린국회정보 API 및 국회 공식 자료를 이용합니다.",
        "note": "국회는 행정부의 하위기관이 아닌 별도의 헌법기관입니다.",
        "source": "https://www.assembly.go.kr/"
    },
    "chair": {
        "title": "국회의장단", "head": "국회의장·국회부의장", "parent": "대한민국 국회",
        "duty": "국회 회의를 주재하고 의사 진행 및 국회 운영을 조정합니다.",
        "children": "의장과 부의장으로 구성됩니다.", "scale": "인적 구성은 국회 공식 홈페이지에서 확인합니다.",
        "note": "의장단은 국회 운영을 담당하며 각 위원회의 심사 기능과 구별됩니다.", "source": "https://www.assembly.go.kr/"
    },
    "committee": {
        "title": "위원회", "head": "위원장", "parent": "대한민국 국회",
        "duty": "소관 분야의 법률안·예산안·청원 등을 심사합니다.",
        "children": "상임위원회와 특별위원회 등으로 구성됩니다.", "scale": "현재 위원회 명단과 구성은 국회 공식 자료로 확인합니다.",
        "note": "위원회별 소관 분야와 구성은 회기·국회 운영에 따라 변동될 수 있습니다.", "source": "https://www.assembly.go.kr/"
    },
    "secretariat": {
        "title": "국회사무처", "head": "국회사무총장", "parent": "대한민국 국회",
        "duty": "국회의 의정활동과 입법·행정 업무를 지원합니다.",
        "children": "의사·행정·입법 지원 부서 등으로 구성되며 세부 직제는 공식 자료를 따릅니다.",
        "scale": "공식 조직 및 인사 자료를 기준으로 확인합니다.", "note": "국회의 의정활동 지원 조직입니다.", "source": "https://www.assembly.go.kr/"
    },
    "affiliated": {
        "title": "국회 소속기관", "head": "기관별 기관장", "parent": "대한민국 국회",
        "duty": "국회도서관·국회예산정책처·국회입법조사처 등 전문 자료·분석 업무를 수행합니다.",
        "children": "국회도서관, 국회예산정책처, 국회입법조사처 등.",
        "scale": "기관별 조직도와 정원은 각 기관 공식 자료를 확인합니다.", "note": "국회 본회의·위원회와 구별되는 전문 지원기관입니다.", "source": "https://www.assembly.go.kr/"
    },
    "supreme": {
        "title": "대법원", "head": "대법원장", "parent": "대한민국 법원의 최고법원",
        "duty": "상고사건 등을 최종심으로 심판하고 법원 조직의 최고기관 역할을 합니다.",
        "children": "고등법원·지방법원 및 전문법원 체계와 관련되며, 법원행정처 등 지원 조직이 있습니다.",
        "scale": "법원별 관할·설치 현황은 법원 공식 조직 안내를 확인합니다.",
        "note": "법원의 종류 간 심급·관할 관계는 화면의 단순 상하 배열과 다를 수 있습니다.",
        "source": "https://www.scourt.go.kr/judiciary/organization/chart/index.html"
    },
    "high": {
        "title": "고등법원", "head": "법원장", "parent": "대한민국 법원",
        "duty": "주로 지방법원 등의 판결에 대한 항소·항고 사건을 심판합니다.",
        "children": "서울·대전·대구·부산·광주·수원 고등법원 및 원외재판부 등.",
        "scale": "법원별 관할 및 설치 장소는 공식 법원 조직 안내를 확인합니다.", "note": "일반적인 재판의 항소심을 담당합니다.", "source": "https://www.scourt.go.kr/judiciary/organization/high/index.html"
    },
    "district": {
        "title": "지방법원", "head": "법원장", "parent": "대한민국 법원",
        "duty": "일반적인 민사·형사 사건의 1심 등을 담당합니다.",
        "children": "지원·시군법원·등기소 등이 설치될 수 있습니다.", "scale": "관할과 설치 현황은 공식 법원 조직 안내를 확인합니다.",
        "note": "사건 종류와 절차에 따라 관할·심급이 달라질 수 있습니다.", "source": "https://www.scourt.go.kr/"
    },
    "special": {
        "title": "전문법원", "head": "법원장", "parent": "법원 체계 내 전문 관할 법원",
        "duty": "특정 분야 사건을 전문적으로 담당합니다.",
        "children": "특허법원·가정법원·행정법원·회생법원 등.",
        "scale": "법원마다 담당 사건과 심급이 다릅니다.", "note": "특허법원은 고등법원급, 가정·행정·회생법원은 지방법원급으로 이해하면 되며 세부 관할은 별도 확인합니다.",
        "source": "https://www.scourt.go.kr/judiciary/organization/specialized/index.html"
    },
    "court_admin": {
        "title": "법원행정처 등", "head": "법원행정처장 등", "parent": "대법원 소속 사법행정 지원 조직",
        "duty": "법원의 인사·예산·시설 등 사법행정을 지원합니다.",
        "children": "법원행정처·법원도서관·사법연수원·법원공무원교육원 등.",
        "scale": "세부 조직은 대법원 공식 조직도를 확인합니다.", "note": "재판을 담당하는 법원과 사법행정 지원 조직을 구분합니다.", "source": "https://www.scourt.go.kr/judiciary/organization/chart/index.html"
    },
    "local_executive": {
        "title": "지방 행정부", "head": "시·도지사 또는 시장·군수·구청장", "parent": "해당 지방자치단체의 집행기관",
        "duty": "지역 정책과 예산을 집행하고 주민 생활과 지역 행정을 담당합니다.",
        "children": "부단체장, 실·국·본부, 과·담당관 등. 실제 편제는 지방자치단체마다 다릅니다.",
        "scale": "해당 지자체의 공식 조직도·정원 자료가 필요합니다.",
        "note": "화면은 일반적인 구조 예시이며 선택 지역의 실제 조직도를 복제한 것이 아닙니다.", "source": "https://www.mois.go.kr/"
    },
    "local_council": {
        "title": "지방 의회", "head": "지방의회 의장", "parent": "해당 지방자치단체의 의결기관",
        "duty": "조례 제정·개정, 예산 심의·확정, 행정사무 감사·조사 등 지방자치단체의 주요 사항을 심의·의결합니다.",
        "children": "의장단, 상임·특별위원회, 의회사무국·의회사무과 등. 실제 편제는 지방의회마다 다릅니다.",
        "scale": "행정안전부 통계연보의 기수별 지방의회의원 정수는 참고 자료이며 현재 특정 지역의 의석 수로 단정할 수 없습니다.",
        "note": "지역별 공식 조직도 데이터는 별도 확보 전까지 일반 구조로 표시합니다.", "source": "https://www.mois.go.kr/"
    },
}


# 2026-10-02 정부기구도 및 2026-10-02 시행 정부조직법 기준으로 확인한 기관 목록입니다.
GOVERNMENT_ORG_BASE_DATE = "2026-10-02"
GOVERNMENT_ORG_COUNTS = {"부": 19, "처": 6, "청": 19, "위원회": 6}
GOVERNMENT_ORG_VERIFICATION = {
    "부": "정부조직법 제29조 기준 확인",
    "처": "2026-10-02 정부기구도 기준 확인",
    "청": "목록명 전수 대조 필요 — 정부디렉터리 API 승인 대기",
    "위원회": "2026-10-02 정부기구도 기준 확인",
}
GOVERNMENT_ORG_LISTS = {
    "부": [
        "재정경제부", "과학기술정보통신부", "교육부", "외교부", "통일부", "법무부", "국방부",
        "행정안전부", "국가보훈부", "문화체육관광부", "농림축산식품부", "산업통상부",
        "보건복지부", "기후에너지환경부", "고용노동부", "성평등가족부", "국토교통부",
        "해양수산부", "중소벤처기업부",
    ],
    "처": ["기획예산처", "인사혁신처", "법제처", "식품의약품안전처", "국가데이터처", "지식재산처"],
    # 정부기구도(영문) 이미지에 표시된 소속청 명칭을 한국어로 정리한 목록입니다.
    # 검찰청·통계청·특허청의 개편 영향과 기관 분류를 원본 기구도에서 재대조하도록 상태 경고를 함께 둡니다.
    "청": [
        "국세청", "관세청", "조달청", "재외동포청", "검찰청", "병무청", "방위사업청",
        "경찰청", "소방청", "국가유산청", "농촌진흥청", "산림청", "질병관리청",
        "기상청", "행정중심복합도시건설청", "새만금개발청", "해양경찰청",
        "우주항공청", "통계청",
    ],
    "위원회": ["방송미디어통신위원회", "공정거래위원회", "국민권익위원회", "금융위원회", "개인정보보호위원회", "원자력안전위원회"],
}


def organization_code_mismatch(expected_count: int, names: list[str]) -> bool:
    """정의된 기관 목록이 공식 기준 개수와 다르면 코드 최신화가 필요합니다."""
    return len(names) != expected_count or len(set(names)) != len(names)


def render_government_category_list(category: str):
    names = GOVERNMENT_ORG_LISTS.get(category, [])
    expected = GOVERNMENT_ORG_COUNTS.get(category, len(names))
    if organization_code_mismatch(expected, names):
        st.warning(f"코드 최신화 필요: {category} 목록 {len(names)}개 / 기준 {expected}개. 정부기구도 원본을 다시 확인해 주세요.")
    elif category == "청":
        st.warning(f"코드 최신화 필요: {GOVERNMENT_ORG_VERIFICATION.get(category)}. 아래 기관명은 참고용 목록이며, 정식 현행 명칭은 공식 기관별 기구도와 추가 대조가 필요합니다.")
    else:
        st.caption(f"{GOVERNMENT_ORG_BASE_DATE} 기준 목록 · {len(names)}개 · {GOVERNMENT_ORG_VERIFICATION.get(category, '')}")
    cols = st.columns(3)
    for i, name in enumerate(names):
        with cols[i % 3]:
            st.markdown(f"<div class='pastel-card'>{html.escape(name)}</div>", unsafe_allow_html=True)
    st.link_button("정부조직관리정보시스템에서 최신 기관별 기구도 확인", "https://www.org.go.kr/cop/bbs/getInstiChartList.do?pageIndex=1")


def _org_open_detail(detail_key: str, return_page: str):
    st.session_state.org_detail = detail_key
    st.session_state.org_return_page = return_page
    st.session_state.page = "기관 상세"
    st.rerun()


def render_node(title, role, key, detail_key=None, return_page=None, icon=""):
    """조직도 노드를 표시합니다. 마우스오버 정보만 제공하고 클릭 이동은 하지 않습니다.

    이전 합의에서는 기관 상세 페이지 이동을 후속 확장으로 남겨 두었습니다.
    따라서 카드 클릭으로 다른 페이지에 진입시키지 않고, 기본 브라우저 툴팁으로
    현직 기관장 이름은 승인된 인사 API가 확보되기 전까지 미연동 상태로 안내하고, 핵심 업무·조직 규모를 제공합니다. 상하·소속 관계는 도표에 둡니다.
    """
    detail_key = detail_key or key
    detail = ORG_DETAILS.get(detail_key, {})
    leader_name = detail.get("leader_name", "현직 기관장: 현재 승인된 API에서 인사정보를 제공하지 않아 미연동")
    tooltip = "\n".join([
        leader_name,
        f"직위: {detail.get('head', '기관별 상이')}",
        f"주요 업무: {detail.get('duty', role)}",
        f"조직 규모: {detail.get('scale', '공식 자료 확인')}",
        f"참고: {detail.get('note', '세부 사항은 공식 자료 확인')}",
    ])
    icon_html = f'<span class="org-node-icon">{html.escape(icon)}</span>' if icon else ""
    st.markdown(
        '<div class="org-node org-node-hover" title="' + html.escape(tooltip, quote=True) + '">'
        + icon_html
        + '<div class="org-node-title">' + html.escape(str(title)) + '</div>'
        + '<div class="org-node-role">' + html.escape(str(role)) + '</div>'
        + '</div>',
        unsafe_allow_html=True,
    )


def render_government():
    render_hero("정부 조직", "행정부의 상하·소속 관계와 중앙행정기관의 유형을 살펴봅니다.")
    st.caption("조직 기준일: 2026.10.02 · 정부조직관리정보시스템의 공식 정부기구도 및 시행 정부조직법 기준. 최신 조직개편은 공식 원본과 대조해야 합니다.")
    with st.container(border=True):
        center = st.columns([1, 2, 1])[1]
        with center:
            render_node("대통령", "국가원수 · 행정부 수반", "president", "president", "정부 조직", "🏛️")
        st.markdown('<div class="org-arrow">↓</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            render_node("대통령 소속기관", "소속·직속 기관", "presidential", "presidential", "정부 조직", "🏢")
        with c2:
            render_node("국무총리", "대통령 보좌 · 행정 각부 통할", "prime", "prime", "정부 조직", "▣")
        st.markdown('<div class="org-arrow">↓</div>', unsafe_allow_html=True)
        st.markdown("**중앙행정기관 및 주요 기관 유형**")
        cols = st.columns(3, gap="small")
        categories = [
            ("부", "19개", "ministry", "각부 장관이 소관 국가행정사무를 통할"),
            ("처", "6개", "office", "전문·통합 행정 기능"),
            ("청", "19개", "agency", "집행 중심의 전문 행정사무"),
            ("위원회", "6개", "commission", "합의제 행정 기능"),
            ("원", "유형", "institute", "감사·연구·통계 등 기관별 기능"),
            ("실", "유형", "office_unit", "정책 조정·기획·지원 조직"),
        ]
        for index, (title, count, key, desc) in enumerate(categories):
            with cols[index % 3]:
                render_node(title, f"{count} · {desc}", key, key, "정부 조직", {"ministry":"🏢","office":"📁","agency":"🏛️","commission":"⚖️","institute":"📚","office_unit":"🧭"}[key])
                if title in GOVERNMENT_ORG_LISTS:
                    with st.expander(f"{title} 전체 목록 보기 ({count})", expanded=False):
                        render_government_category_list(title)
                else:
                    with st.expander(f"{title} 유형 설명", expanded=False):
                        st.write(desc)
                        st.caption("이 항목은 정부기구도에 표시되는 조직 유형입니다. 개별 기관 목록은 공식 기구도에서 확인하세요.")
        st.caption("조직도 기준일: 2026-10-02. 현재 승인된 12개 API에는 기관별 현직 기관장 이름을 제공하는 인사정보 API가 포함되지 않아 이름은 임의로 표시하지 않습니다. 정부디렉터리시스템 API 승인 또는 별도 공식 인사정보 API 확보 후 연동할 수 있습니다.")

    a, b = st.columns(2)
    with a:
        if st.button("기관별 공무원 정원 통계 보기", use_container_width=True):
            st.session_state.page = "정치 자료 탐색"
            st.session_state.api_selected_item = "staff"
            st.rerun()
    with b:
        if st.button("중앙행정기관 하부기구 통계 보기", use_container_width=True):
            st.session_state.page = "정치 자료 탐색"
            st.session_state.api_selected_item = "suborg"
            st.rerun()
    st.link_button("정부조직관리정보시스템 공식 자료", "https://www.org.go.kr/orgnzt/chart/viewEng.do")


def render_congress():
    render_hero("국회 조직", "입법부의 주요 기관과 국회의 기능을 살펴봅니다.")
    with st.container(border=True):
        center = st.columns([1, 2, 1])[1]
        with center:
            render_node("대한민국 국회", "국민의 대표기관 · 입법기관", "assembly", "assembly", "국회 조직", "🏛️")
        st.markdown('<div class="org-arrow">↓</div>', unsafe_allow_html=True)
        left, right = st.columns(2, gap="small")
        with left:
            render_node("국회의장단", "국회의장 · 부의장", "chair", "chair", "국회 조직")
            render_node("국회사무처", "국회 의정·행정 지원", "secretariat", "secretariat", "국회 조직")
        with right:
            render_node("위원회", "상임위원회 · 특별위원회", "committee", "committee", "국회 조직")
            render_node("국회 소속기관", "도서관 · 예산정책처 · 입법조사처 등", "affiliated", "affiliated", "국회 조직")
    st.link_button("대한민국 국회 공식 홈페이지", "https://www.assembly.go.kr/")


def render_court():
    render_hero("법원 조직", "사법부의 기본적인 법원 체계와 법원별 역할을 살펴봅니다.")
    st.caption("아래는 이해를 위한 조직 개요입니다. 법원의 종류·심급·관할이 모두 동일한 상하 관계라는 뜻은 아닙니다.")
    with st.container(border=True):
        center = st.columns([1, 2, 1])[1]
        with center:
            render_node("대법원", "대한민국 법원의 최고법원", "supreme", "supreme", "법원 조직", "⚖️")
        st.markdown('<div class="org-arrow">↓</div>', unsafe_allow_html=True)
        left, right = st.columns(2, gap="small")
        with left:
            render_node("고등법원", "일반 재판의 항소심 중심", "high", "high", "법원 조직")
            render_node("전문법원", "특허 · 가정 · 행정 · 회생법원 등", "special", "special", "법원 조직")
        with right:
            render_node("지방법원", "일반 민사·형사 사건의 1심 등", "district", "district", "법원 조직")
            render_node("법원행정처 등", "사법행정 및 전문 지원 조직", "court_admin", "court_admin", "법원 조직")
    st.link_button("대한민국 법원 공식 조직 안내", "https://www.scourt.go.kr/judiciary/organization/chart/index.html")


def render_org_detail():
    detail_key = st.session_state.get("org_detail", "")
    detail = ORG_DETAILS.get(detail_key)
    if not detail:
        st.warning("선택한 기관의 상세 정보를 찾을 수 없습니다.")
        if st.button("조직도로 돌아가기"):
            st.session_state.page = st.session_state.get("org_return_page", "정부 조직")
            st.rerun()
        return
    st.divider()
    st.subheader(detail["title"])
    st.caption(f"기관장 직위: {detail.get('head', '기관별 상이')} · 상위 소속: {detail.get('parent', '공식 자료 확인')}")
    st.markdown("**주요 업무**")
    st.write(detail.get("duty", "공식 자료를 확인해 주세요."))
    st.markdown("**소속·하부조직**")
    st.write(detail.get("children", "공식 조직도를 확인해 주세요."))
    st.markdown("**조직 규모 및 통계**")
    st.write(detail.get("scale", "공식 통계 확인 필요"))
    if detail.get("note"):
        st.info(detail["note"])
    if detail.get("source"):
        st.link_button("공식 출처 확인", detail["source"])
    if st.button("조직도 화면으로 돌아가기", use_container_width=True):
        st.session_state.org_detail = ""
        st.session_state.page = st.session_state.get("org_return_page", "정부 조직")
        st.rerun()


# ============================================================
# 15. 화면: 지방 정부 (시도 → 시군구 → 지역 정보)
# ============================================================


# 지역명·코드의 실제 관리 원본은 GitHub 저장소의 지역코드_연계표.xlsx입니다.
# 엑셀에서 코드를 수정하면 앱이 파일 수정 시각을 기준으로 다시 읽습니다.
KOREA_SIDO_FALLBACK = [
    "서울특별시", "전남광주통합특별시", "부산광역시", "대구광역시", "인천광역시",
    "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도",
    "충청북도", "충청남도", "전북특별자치도", "경상북도", "경상남도", "제주특별자치도",
]


@st.cache_data(ttl=600, show_spinner=False)
def _read_region_codebook_sheet(path_text: str, modified_ns: int, sheet_name: str):
    """엑셀 시트를 읽습니다. 파일이 없거나 열 제목이 깨져도 앱 전체를 중단하지 않습니다."""
    try:
        frame = pd.read_excel(path_text, sheet_name=sheet_name, dtype=str, engine="openpyxl")
        return frame.fillna("")
    except Exception:
        return pd.DataFrame()


def load_region_codebook_sheet(sheet_name: str = "광역_기초목록"):
    try:
        modified_ns = REGION_CODEBOOK_PATH.stat().st_mtime_ns
    except OSError:
        return pd.DataFrame()
    return _read_region_codebook_sheet(str(REGION_CODEBOOK_PATH), modified_ns, sheet_name)


def _normalize_region_label(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def get_sido_names() -> list[str]:
    """엑셀의 현행 광역자치단체명을 우선 사용하고, 파일 누락 시 현행 목록으로 대체합니다."""
    frame = load_region_codebook_sheet("광역_기초목록")
    if not frame.empty and {"단계", "지역명", "자치단체여부"}.issubset(frame.columns):
        selected = frame[(frame["단계"] == "광역") & (frame["자치단체여부"] == "예")]
        names = [str(value).strip() for value in selected["지역명"].tolist() if str(value).strip()]
        if names:
            return list(dict.fromkeys(names))
    return list(KOREA_SIDO_FALLBACK)


def find_region_codebook_row(sido_name: str, region_name: str = "", step: str | None = None):
    """광역명+지역명으로 코드북 행을 찾습니다. 코드값이 빈 경우에도 행 자체는 반환합니다."""
    frame = load_region_codebook_sheet("광역_기초목록")
    if frame.empty or "지역명" not in frame.columns:
        return None
    sido_norm = _normalize_region_label(sido_name)
    region_norm = _normalize_region_label(region_name)
    for _, row in frame.iterrows():
        row_step = str(row.get("단계", "")).strip()
        row_sido = _normalize_region_label(row.get("상위광역명", ""))
        row_name = _normalize_region_label(row.get("지역명", ""))
        if step and row_step != step:
            continue
        if region_norm:
            if row_name != region_norm and not region_norm.endswith(row_name):
                continue
            if row_step == "광역":
                if row_name != region_norm:
                    continue
            elif row_sido != sido_norm:
                continue
        else:
            if row_step != "광역" or row_name != sido_norm:
                continue
        return row.to_dict()
    return None


def lookup_region_codebook_value(sido_name: str, region_name: str, column_name: str, step: str | None = None) -> str:
    row = find_region_codebook_row(sido_name, region_name, step)
    value = str(row.get(column_name, "")).strip() if row else ""
    return "" if value.lower() in {"nan", "none"} else value


def get_local_region_names(sido_name: str) -> list[str]:
    """자치단체인 기초지역과 제주 행정시를 반환합니다. 일반구는 기초자치단체에서 제외합니다."""
    frame = load_region_codebook_sheet("광역_기초목록")
    if frame.empty or not {"단계", "상위광역명", "지역명", "행정구역유형", "자치단체여부"}.issubset(frame.columns):
        return []
    sido_norm = _normalize_region_label(sido_name)
    rows = frame[
        (frame["상위광역명"].map(_normalize_region_label) == sido_norm)
        & (frame["단계"].isin(["기초", "행정시"]))
    ]
    names = []
    for _, row in rows.iterrows():
        kind = str(row.get("행정구역유형", "")).strip()
        is_local = str(row.get("자치단체여부", "")).strip() == "예"
        if is_local or kind == "행정시":
            name = str(row.get("지역명", "")).strip()
            if name:
                names.append(name)
    return list(dict.fromkeys(names))


def match_sido_codebook_name(name: str) -> str:
    """지도에서 받은 이름을 현재 코드북의 광역자치단체명과 대조합니다."""
    target = _normalize_region_label(name)
    for current_name in get_sido_names():
        if _normalize_region_label(current_name) == target:
            return current_name
    return ""


def match_local_codebook_name(sido_name: str, name: str) -> str:
    """VWorld 피처 이름(상위지역명이 붙은 경우 포함)을 코드북의 현행 시군구명으로 정규화합니다."""
    target = _normalize_region_label(name)
    candidates = get_local_region_names(sido_name)
    exact = [candidate for candidate in candidates if _normalize_region_label(candidate) == target]
    if len(exact) == 1:
        return exact[0]
    suffix = [candidate for candidate in candidates if target.endswith(_normalize_region_label(candidate))]
    return suffix[0] if len(suffix) == 1 else ""


def lookup_population_admin_code(sido_name: str, region_name: str, level: str) -> str:
    """엑셀에서 주민등록 API admmCd를 찾습니다. KiKcd_H와 같은 코드 체계의 열을 보조로 읽습니다.

    MOIS_admmCd(행정기관코드)와 MOIS_KiKcd_H(행정동코드)는 모두 MOIS 행정기관코드 계열입니다.
    사용자가 둘 중 하나만 입력해도 조회에 쓰며, 법정동(KiKcd_B), KiKmix, VWorld 코드는 절대 대체 사용하지 않습니다.
    """
    step = "광역" if level == "광역자치단체" else "기초"
    row = find_region_codebook_row(sido_name, region_name, step=step)
    if not row:
        return ""
    for column in ("MOIS_admmCd(행정기관코드)", "MOIS_KiKcd_H(행정동코드)"):
        value = str(row.get(column, "") or "").strip()
        if value.lower() in {"nan", "none"}:
            continue
        # 코드가 숫자 문자열로 보존된 경우에만 사용합니다. Excel 숫자 셀에서 앞자리 0이
        # 사라졌을 수 있으므로, 사용안내에서 셀 서식을 텍스트로 유지하도록 안내합니다.
        if value and value.isdigit():
            return value
    return ""


def is_single_tier_local_authority(sido_name: str) -> bool:
    """세종처럼 별도 시·군·구 단계가 없는 단층제 광역자치단체인지 확인합니다."""
    row = find_region_codebook_row(sido_name, sido_name, step="기초")
    return bool(row and str(row.get("행정구역유형", "")).strip() == "특별자치시(단층제)")


def lookup_admin_legal_dong_mappings(sido_name: str, sigungu_name: str, administrative_dong_name: str) -> list[dict]:
    """행정동_법정동_매핑 시트에서 정확히 일치하는 사용자 입력 매핑을 모두 반환합니다."""
    frame = load_region_codebook_sheet("행정동_법정동_매핑")
    required = {"광역자치단체명", "시군구명", "행정동명"}
    if frame.empty or not required.issubset(frame.columns):
        return []
    sido_norm = _normalize_region_label(sido_name)
    sigungu_norm = _normalize_region_label(sigungu_name)
    dong_norm = _normalize_region_label(administrative_dong_name)
    if not sido_norm or not dong_norm:
        return []
    selected = frame[
        (frame["광역자치단체명"].map(_normalize_region_label) == sido_norm)
        & (frame["시군구명"].map(_normalize_region_label) == sigungu_norm)
        & (frame["행정동명"].map(_normalize_region_label) == dong_norm)
    ]
    columns = [
        "광역자치단체명", "시군구명", "행정동명",
        "MOIS_행정기관코드(KiKcd_H/admmCd)", "법정동명",
        "MOIS_법정동코드(KiKcd_B)", "MOIS_KiKmix_원문행",
        "시행일", "현재사용여부", "폐지일", "출처파일", "확인상태", "메모",
    ]
    return [
        {column: str(row.get(column, "")).strip() for column in columns}
        for _, row in selected.iterrows()
    ]


def lookup_vworld_code(sido_name: str, region_name: str, level: str) -> str:
    step = "광역" if level == "시도" else None
    return lookup_region_codebook_value(sido_name, region_name, "VWorld_지역코드", step)


def _normalize_vworld_layer_name(value: str) -> str:
    """WFS 레이어 식별자는 대소문자 표기를 정규화해 비교합니다."""
    return re.sub(r"\s+", "", str(value or "")).upper()


def lookup_vworld_wfs_layer(level: str) -> str:
    """VWorld_레이어 시트에서 WFS 레이어명을 읽습니다. 미등록 시 검증된 기본값을 씁니다."""
    fallbacks = {
        "광역": "LT_C_ADSIDO_INFO",
        "시군구": "LT_C_ADSIGG_INFO",
        "읍면동": "LT_C_ADEMD_INFO",
        "리": "LT_C_ADRI_INFO",
    }
    frame = load_region_codebook_sheet("VWorld_레이어")
    if not frame.empty and {"단계", "WFS레이어명(공식)"}.issubset(frame.columns):
        rows = frame[frame["단계"].astype(str).str.strip() == str(level).strip()]
        if not rows.empty:
            candidate = str(rows.iloc[0].get("WFS레이어명(공식)", "")).strip()
            if re.fullmatch(r"LT_C_[A-Z0-9_]+", _normalize_vworld_layer_name(candidate)):
                return _normalize_vworld_layer_name(candidate)
    return fallbacks.get(level, "")


def _vworld_layer_rows(layer_name: str):
    frame = load_region_codebook_sheet("VWorld_레이어")
    if frame.empty or "WFS레이어명(공식)" not in frame.columns:
        return frame
    target = _normalize_vworld_layer_name(layer_name)
    return frame[frame["WFS레이어명(공식)"].map(_normalize_vworld_layer_name) == target]


def lookup_vworld_property_field(layer_name: str) -> str:
    frame = _vworld_layer_rows(layer_name)
    if frame.empty:
        return ""
    field_column = "코드 필드명(공식 예제 확인)" if "코드 필드명(공식 예제 확인)" in frame.columns else "속성 필드명(응답 확인 후 입력)"
    if field_column not in frame.columns:
        return ""
    return str(frame.iloc[0].get(field_column, "") or "").strip()


def lookup_vworld_name_field(layer_name: str) -> str:
    """지역코드 엑셀의 VWorld 명칭 필드를 우선 사용합니다(레이어 대소문자 무관)."""
    frame = _vworld_layer_rows(layer_name)
    if frame.empty or "명칭 필드명(공식 예제 확인)" not in frame.columns:
        return ""
    return str(frame.iloc[0].get("명칭 필드명(공식 예제 확인)", "") or "").strip()


def lookup_nec_region_params(sido_name: str = "", region_name: str = "") -> dict:
    """NEC_선거지역명 시트의 지역명 후보를 반환합니다. 값은 코드가 아닌 문자열 검색어입니다."""
    frame = load_region_codebook_sheet("NEC_선거지역명")
    if frame.empty:
        return {"sdName": "", "sggName": "", "wiwName": ""}
    sido_col = "광역자치단체명(sdName 후보)"
    sgg_col = "기초지역명(sggName 후보)"
    wiw_col = "기초지역명(wiwName 후보)"
    if not {sido_col, sgg_col, wiw_col}.issubset(frame.columns):
        return {"sdName": "", "sggName": "", "wiwName": ""}
    sido_norm = _normalize_region_label(sido_name)
    region_norm = _normalize_region_label(region_name)
    candidates = []
    for _, row in frame.iterrows():
        row_sido = _normalize_region_label(row.get(sido_col, ""))
        row_sgg = _normalize_region_label(row.get(sgg_col, ""))
        if sido_norm and row_sido != sido_norm:
            continue
        if region_norm and row_sgg != region_norm:
            continue
        if not region_norm and row_sgg:
            continue
        candidates.append(row)
    if not candidates:
        return {"sdName": "", "sggName": "", "wiwName": ""}
    row = candidates[0]
    return {
        "sdName": str(row.get(sido_col, "")).strip(),
        "sggName": str(row.get(sgg_col, "")).strip(),
        "wiwName": str(row.get(wiw_col, "")).strip(),
    }


def lookup_kosis_codebook_config(sido_name: str, region_name: str, metric_label: str) -> dict:
    """KOSIS 일반 지표 설정과 지역별 OBJ_L1 매핑을 병합합니다. 빈 값은 추정하지 않습니다."""
    result = {"ORG_ID": "", "TBL_ID": "", "ITM_ID": "", "OBJ_L1": "", "OBJ_L2": "", "OBJ_L3": "", "PRD_SE": ""}
    metrics = load_region_codebook_sheet("KOSIS_통계표별")
    if not metrics.empty and "지표명" in metrics.columns:
        rows = metrics[metrics["지표명"].astype(str).str.strip() == str(metric_label).strip()]
        if not rows.empty:
            row = rows.iloc[0]
            for key, column in (("ORG_ID", "ORG_ID"), ("TBL_ID", "TBL_ID"), ("ITM_ID", "ITM_ID"),
                                ("OBJ_L1", "OBJ_L1(지역분류)"), ("OBJ_L2", "OBJ_L2"),
                                ("OBJ_L3", "OBJ_L3"), ("PRD_SE", "PRD_SE")):
                value = str(row.get(column, "")).strip()
                if value and value.lower() not in {"nan", "none"}:
                    result[key] = value
    region_map = load_region_codebook_sheet("KOSIS_지역분류_매핑")
    required = {"광역자치단체명", "지역명", "지표명"}
    if not region_map.empty and required.issubset(region_map.columns):
        sido_norm = _normalize_region_label(sido_name)
        region_norm = _normalize_region_label(region_name)
        selected = region_map[
            (region_map["광역자치단체명"].map(_normalize_region_label) == sido_norm)
            & (region_map["지역명"].map(_normalize_region_label) == region_norm)
            & (region_map["지표명"].astype(str).str.strip() == str(metric_label).strip())
        ]
        if len(selected) == 1:
            row = selected.iloc[0]
            for key, column in (("OBJ_L1", "OBJ_L1(지역분류값)"), ("OBJ_L2", "OBJ_L2"), ("OBJ_L3", "OBJ_L3"),
                                ("ORG_ID", "ORG_ID(선택)"), ("TBL_ID", "TBL_ID(선택)"),
                                ("ITM_ID", "ITM_ID(선택)"), ("PRD_SE", "PRD_SE(선택)")):
                value = str(row.get(column, "")).strip()
                if value and value.lower() not in {"nan", "none"}:
                    result[key] = value
    return result


def _region_cache_key(level: str, region_name: str) -> str:
    """광역·기초 지역의 통계가 서로 덮어쓰이지 않도록 고유 키를 만듭니다."""
    return f"{str(level).strip()}::{str(region_name).strip()}"


def _region_widget_token(level: str, region_name: str) -> str:
    raw = _region_cache_key(level, region_name)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _region_data_cache(level: str, region_name: str) -> dict:
    cache = st.session_state.get("local_region_data_cache", {})
    return cache.get(_region_cache_key(level, region_name), {}) if isinstance(cache, dict) else {}


def _save_region_data_cache(level: str, region_name: str, **updates):
    cache = st.session_state.get("local_region_data_cache", {})
    if not isinstance(cache, dict):
        cache = {}
    key = _region_cache_key(level, region_name)
    current = dict(cache.get(key, {}))
    current.update(updates)
    cache[key] = current
    st.session_state.local_region_data_cache = cache


def _reset_local_region_data():
    """이전 단일 상태 변수는 초기화하되, 지역별로 분리한 조회 캐시는 보존합니다."""
    for key, value in {
        "local_population_rows": [], "local_population_error": "",
        "local_council_rows": [], "local_council_error": "",
        "local_kosis_rows": [], "local_kosis_error": "",
        "local_population_admin_code": "",
    }.items():
        st.session_state[key] = value


def _select_sido(name: str, feature=None):
    st.session_state.local_selected_sido = name
    st.session_state.local_sido_feature = feature
    configured_field = lookup_vworld_property_field("lt_c_adsido_info")
    fields = tuple([configured_field] if configured_field else []) + ("ctprvn_cd", "CTPRVN_CD", "ctprvnCode", "CTP_CD")
    st.session_state.local_selected_sido_code = (region_code(feature or {}, fields) if feature else "") or lookup_vworld_code(name, name, "시도")
    st.session_state.local_selected_sigungu = ""
    st.session_state.local_selected_sigungu_code = ""
    st.session_state.local_sigungu_feature = None
    st.session_state.local_sigungu_geo = None
    st.session_state.local_sigungu_attempted = False
    st.session_state.local_stage = "sigungu"
    st.session_state.page = "지방정부 시군구"
    _reset_local_region_data()


def _select_sigungu(name: str, feature=None):
    st.session_state.local_selected_sigungu = name
    st.session_state.local_sigungu_feature = feature
    configured_field = lookup_vworld_property_field("lt_c_adsigg_info")
    fields = tuple([configured_field] if configured_field else []) + ("sig_cd", "SIG_CD", "sig_cd2", "SIG_CD2")
    sido_name = st.session_state.get("local_selected_sido", "")
    st.session_state.local_selected_sigungu_code = (region_code(feature or {}, fields) if feature else "") or lookup_vworld_code(sido_name, name, "시군구")
    st.session_state.local_stage = "detail"
    st.session_state.page = "지방정부 상세"
    _reset_local_region_data()


def _change_local_sido():
    st.session_state.local_stage = "sido"
    st.session_state.page = "지방 정부"
    st.session_state.local_selected_sido = ""
    st.session_state.local_selected_sido_code = ""
    st.session_state.local_sido_feature = None
    st.session_state.local_selected_sigungu = ""
    st.session_state.local_selected_sigungu_code = ""
    st.session_state.local_sigungu_feature = None
    st.session_state.local_sigungu_geo = None
    st.session_state.local_sigungu_attempted = False
    _reset_local_region_data()


def _selected_feature_by_tooltip(features, tooltip, name_fields):
    if not tooltip:
        return None
    # 지도 위젯 버전에 따라 tooltip이 HTML 조각으로 돌아오는 경우도 정규화합니다.
    normalized = html.unescape(str(tooltip))
    normalized = re.sub(r"<[^>]*>", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return next(
        (feature for feature in features if region_property(feature, name_fields) == normalized),
        None,
    )


def _ensure_local_map(level: str):
    """페이지 진입 시 한 번만 행정구역을 불러옵니다. 오류면 선택 목록으로 대체합니다."""
    if level == "시도":
        if st.session_state.get("local_sido_attempted"):
            return st.session_state.get("local_sido_geo"), st.session_state.get("local_sido_error", "")
        st.session_state.local_sido_attempted = True
        with st.spinner("전국 행정구역 지도를 불러오는 중입니다..."):
            geo, message = load_vworld_geojson("시도")
        st.session_state.local_sido_geo = geo
        st.session_state.local_sido_error = message
        return geo, message
    if st.session_state.get("local_sigungu_attempted"):
        return st.session_state.get("local_sigungu_geo"), st.session_state.get("local_sigungu_error", "")
    st.session_state.local_sigungu_attempted = True
    with st.spinner(f"{st.session_state.get('local_selected_sido', '선택 지역')}의 시·군·구 경계를 불러오는 중입니다..."):
        raw_geo, message = load_vworld_geojson("시군구")
    if raw_geo:
        sido_name = st.session_state.get("local_selected_sido", "")
        sido_code = st.session_state.get("local_selected_sido_code", "") or lookup_vworld_code(sido_name, sido_name, "시도")
        filtered, filter_message = filter_sigungu_geojson(raw_geo, sido_code, sido_name)
        geo = filtered
        message = filter_message
    else:
        geo = None
    st.session_state.local_sigungu_geo = geo
    st.session_state.local_sigungu_error = message
    return geo, message


def _ring_area_km2(ring):
    """GeoJSON 경위도 ring의 구면 면적을 계산합니다(법정 면적이 아닌 경계 기반 계산값)."""
    if not isinstance(ring, list) or len(ring) < 4:
        return 0.0
    radius_m = 6371008.8
    total = 0.0
    try:
        for first, second in zip(ring, ring[1:]):
            lon1, lat1 = float(first[0]), float(first[1])
            lon2, lat2 = float(second[0]), float(second[1])
            total += (math.radians(lon2 - lon1) *
                      (2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2))))
        return abs(total * radius_m * radius_m / 2.0) / 1_000_000.0
    except (TypeError, ValueError, IndexError):
        return 0.0


def geojson_area_km2(feature):
    """Polygon/MultiPolygon 외곽링에서 내부 hole을 빼 경계 면적을 계산합니다."""
    if not isinstance(feature, dict):
        return None
    geometry = feature.get("geometry") or {}
    gtype, coords = geometry.get("type"), geometry.get("coordinates")
    if not isinstance(coords, list):
        return None
    polygons = [coords] if gtype == "Polygon" else coords if gtype == "MultiPolygon" else []
    if not polygons:
        return None
    total = 0.0
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            continue
        outer = _ring_area_km2(polygon[0])
        holes = sum(_ring_area_km2(ring) for ring in polygon[1:])
        total += max(0.0, outer - holes)
    return total if total > 0 else None


def _numeric_value(value):
    if value is None:
        return None
    text = re.sub(r"[,\s]", "", str(value))
    try:
        number = float(text)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def population_summary(rows):
    """행정동·통반 원자료에서 하나의 집계행만 확인될 때만 총인구 요약값을 반환합니다."""
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    patterns = ("총인구수", "총인구", "totpop", "totalpopulation", "total_pop", "popltncnt")
    for key, value in row.items():
        normalized = re.sub(r"[^0-9a-z가-힣]", "", str(key).lower())
        if any(pattern in normalized for pattern in patterns):
            number = _numeric_value(value)
            if number is not None:
                return int(number) if number.is_integer() else number
    return None


def _metric_card(name, value, unit, basis):
    has_value = value not in (None, "")
    value_text = str(value) if has_value else "자료 연결 대기"
    unit_text = f" {unit.strip()}" if has_value and unit else ""
    meta_parts = [basis]
    if unit:
        meta_parts.append(f"단위: {unit.strip()}")
    html_block = (
        '<div class="region-metric">'
        f'<div class="metric-name">{html.escape(name)}</div>'
        f'<div class="metric-value">{html.escape(value_text + unit_text)}</div>'
        f'<div class="metric-meta">{html.escape(" · ".join(meta_parts))}</div>'
        '</div>'
    )
    st.markdown(html_block, unsafe_allow_html=True)


KOSIS_METRIC_RULES = {
    "출생아 수": {"metric_key": "births", "keywords": ("출생아수",), "unit_kind": "count"},
    "합계출산율": {"metric_key": "fertility", "keywords": ("합계출산율",), "unit_kind": "rate_count"},
    "고령인구 비율": {"metric_key": "elderly_share", "keywords": ("고령인구비율", "65세이상인구비율"), "unit_kind": "percent"},
    "청년인구 비율": {"metric_key": "youth_share", "keywords": ("청년인구비율",), "unit_kind": "percent", "requires_age_19_34": True},
}


def _kosis_normalized_text(value):
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def _region_aliases(region_name: str):
    aliases = {str(region_name).strip()}
    provincial = {
        "서울특별시": ("서울",), "부산광역시": ("부산",), "대구광역시": ("대구",),
        "인천광역시": ("인천",), "광주광역시": ("광주",), "대전광역시": ("대전",),
        "울산광역시": ("울산",), "세종특별자치시": ("세종",), "경기도": ("경기",),
        "강원특별자치도": ("강원", "강원도"), "충청북도": ("충북",), "충청남도": ("충남",),
        "전북특별자치도": ("전북", "전라북도"), "전라남도": ("전남",),
        "경상북도": ("경북",), "경상남도": ("경남",), "제주특별자치도": ("제주",),
    }
    aliases.update(provincial.get(str(region_name).strip(), ()))
    return {_kosis_normalized_text(value) for value in aliases if value}


def _parse_kosis_numeric(value):
    """KOSIS 수치에서 쉼표와 표시 단위만 제거하고, 숫자가 아니면 None을 반환합니다."""
    raw = str(value or "").strip().replace(",", "")
    raw = raw.replace("%", "").replace("명", "").strip()
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", raw):
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def extract_kosis_region_metric(rows, metric_label: str, region_name: str):
    """KOSIS 원자료가 지표명·단위·지역·기준시점을 모두 확인할 때만 카드에 연결합니다."""
    rule = KOSIS_METRIC_RULES.get(metric_label)
    if not rule:
        return None, "지역 통계 카드에 연결할 지표를 선택하지 않았습니다. 원자료 표만 표시합니다."
    if not isinstance(rows, list) or not rows:
        return None, "KOSIS 응답에 자료 행이 없어 지역 통계 카드에 연결하지 않았습니다."

    aliases = _region_aliases(region_name)
    candidates = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_name = first_field(row, ("ITM_NM", "itmNm", "ITEM_NM", "항목명"), "")
        table_name = first_field(row, ("TBL_NM", "tblNm", "통계표명"), "")
        combined_name = _kosis_normalized_text(f"{table_name} {item_name}")
        if not any(keyword in combined_name for keyword in rule["keywords"]):
            continue

        unit = first_field(row, ("UNIT_NM", "unitNm", "단위명"), "")
        unit_text = _kosis_normalized_text(unit)
        if rule["unit_kind"] in ("count", "rate_count"):
            # 천명·만명 등 배율 단위는 단위를 변환하지 않는 한 카드의 '명'과 혼동될 수 있어 제외합니다.
            if "명" not in unit_text or "%" in unit or any(scale in unit_text for scale in ("천", "만", "억")):
                continue
        if rule["unit_kind"] == "percent" and not ("%" in unit or "퍼센트" in unit_text):
            continue

        if rule.get("requires_age_19_34"):
            # 청년기본법의 19~34세 기준이 원자료 명칭에서 확인되지 않으면 같은 지표로 간주하지 않습니다.
            age_text = f"{table_name} {item_name} {first_field(row, ('CMMT_DC', '주석'), '')}"
            compact_age = re.sub(r"\s+", "", age_text)
            if not any(token in compact_age for token in ("19~34", "19∼34", "19-34", "19세~34세", "19세부터34세")):
                continue

        # KOSIS의 분류명(C1_NM~C8_NM) 중 선택 지역을 명시하는 행만 채택합니다.
        location_values = []
        for index in range(1, 9):
            value = first_field(row, (f"C{index}_NM", f"c{index}Nm"), "")
            if value:
                location_values.append(value)
        matched_location = next((value for value in location_values if _kosis_normalized_text(value) in aliases), "")
        if not matched_location:
            continue

        period = first_field(row, ("PRD_DE", "prdDe", "수록시점"), "")
        if not re.fullmatch(r"\d{4,8}", period):
            continue
        value = first_field(row, ("DT", "dt", "수치값"), "")
        number = _parse_kosis_numeric(value)
        if number is None:
            continue
        candidates.append({
            "value": number,
            "display_value": f"{number:,.0f}" if rule["unit_kind"] == "count" else f"{number:,.2f}".rstrip("0").rstrip("."),
            "period": period,
            "raw_unit": unit,
            "table_name": table_name,
            "item_name": item_name,
            "region_label": matched_location,
        })

    if not candidates:
        return None, (
            f"응답에서 {region_name}에 해당하는 '{metric_label}' 자료를 확인하지 못했습니다. "
            "통계표·항목·지역 분류값·단위를 확인하고 원자료 표를 참고해 주세요."
        )
    latest_period = max(item["period"] for item in candidates)
    latest = [item for item in candidates if item["period"] == latest_period]
    if len(latest) != 1:
        return None, (
            f"가장 최근 기준시점({latest_period})에 같은 지역의 자료가 여러 행 반환되어 "
            "성별·세부 분류 등을 임의 합산하지 않았습니다. 분류 조건을 더 좁혀 주세요."
        )
    return latest[0], ""


def update_kosis_metric_values(existing_values, metric_label: str, rows, region_name: str, request_error=""):
    """선택 지표의 이전 값은 먼저 제거하고, 새 응답이 정확히 맞을 때만 다시 저장합니다."""
    updated = dict(existing_values or {})
    rule = KOSIS_METRIC_RULES.get(metric_label)
    if not rule:
        return updated, ""
    metric_key = rule["metric_key"]
    updated.pop(metric_key, None)
    if request_error or not rows:
        return updated, "새 조회 결과가 없어 이전 수치를 지웠습니다. 조회 조건과 API 응답을 확인해 주세요."
    metric_value, message = extract_kosis_region_metric(rows, metric_label, region_name)
    if metric_value:
        updated[metric_key] = metric_value
    return updated, message


def render_region_statistics(region_name: str, feature=None, level="기초자치단체", parent=False):
    """시안의 7개 항목을 고정 순서로 보여주며 지역별 조회 결과를 분리합니다."""
    region_data = _region_data_cache(level, region_name)
    rows = region_data.get("population_rows", [])
    area = geojson_area_km2(feature) if feature else None
    population = population_summary(rows)
    density = population / area if population is not None and area else None
    area_value = f"{area:,.1f}" if area is not None else None
    pop_value = f"{population:,}" if isinstance(population, int) else f"{population:,.1f}" if population is not None else None
    density_value = f"{density:,.0f}" if density is not None else None

    st.markdown("### 지역 기본 정보")
    st.caption(f"{region_name} · {level} · 지표별 기준월·기준연도를 구분해 표시합니다.")
    population_month = region_data.get("population_month", "")
    population_basis = f"행정안전부 · 기준월 {population_month}" if population_month else "행정안전부 · 기준월 표시"
    kosis_metrics = region_data.get("kosis_metric_values", {})
    births = kosis_metrics.get("births", {})
    fertility = kosis_metrics.get("fertility", {})
    elderly = kosis_metrics.get("elderly_share", {})
    youth = kosis_metrics.get("youth_share", {})
    metric_defs = [
        ("면적", area_value, "km²", "VWorld 경계 기반 참고 계산값 · 공표 면적 아님"),
        ("주민등록인구", pop_value, "명", population_basis),
        ("인구밀도", density_value, "명/km²", "확인된 주민등록인구 ÷ 경계 기반 면적"),
        ("출생아 수", births.get("display_value"), "명", f"KOSIS · 기준시점 {births.get('period', '자료 연결 대기')}"),
        ("합계출산율", fertility.get("display_value"), "명/가임여성 1명", f"KOSIS · 가임기간(15~49세) 기준 · 기준시점 {fertility.get('period', '자료 연결 대기')}"),
        ("고령인구 비율", elderly.get("display_value"), "%", f"KOSIS · 65세 이상 기준 · 기준시점 {elderly.get('period', '자료 연결 대기')}"),
        ("청년인구 비율", youth.get("display_value"), "%", f"KOSIS · 19~34세 기준 확인 · 기준시점 {youth.get('period', '자료 연결 대기')}"),
    ]
    cols = st.columns(3, gap="small")
    for idx, (name, value, unit, basis) in enumerate(metric_defs):
        with cols[idx % 3]:
            _metric_card(name, value, unit, basis)
    if rows and population is None:
        st.caption("인구 원자료가 여러 행이거나 집계 필드를 확인할 수 없어 총인구를 임의 합산하지 않았습니다. 아래 원자료를 확인하세요.")
    st.caption("면적은 행정구역 경계의 경위도 좌표로 계산한 참고값이며, 공표된 법정·통계 면적을 대체하지 않습니다. 통계가 연결되지 않은 지표는 숫자를 추정하지 않습니다.")


def _region_data_tools(region_name: str, level: str, feature=None):
    """지역별 통계를 수집합니다. 광역·기초 자료를 별도 저장하고 원자료를 함께 표시합니다."""
    cache = _region_data_cache(level, region_name)
    token = _region_widget_token(level, region_name)
    sido_name = st.session_state.get("local_selected_sido", "")
    explicit_admin_code = population_admin_code_from_feature(feature)
    codebook_admin_code = lookup_population_admin_code(sido_name, region_name, level)
    auto_admin_code = explicit_admin_code or codebook_admin_code
    vworld_code = region_code(feature or {}, (
        lookup_vworld_property_field("lt_c_adsigg_info" if level != "광역자치단체" else "lt_c_adsido_info"),
        "ctprvn_cd", "CTPRVN_CD", "sig_cd", "SIG_CD", "emd_cd", "EMD_CD",
    )) if feature else lookup_vworld_code(sido_name, region_name, "시군구" if level != "광역자치단체" else "시도")

    with st.expander("지역 통계 원자료 조회 및 기준 설정", expanded=False):
        st.markdown("**주민등록인구·세대현황**")
        st.caption("행정안전부 API는 통계년월과 행정기관코드를 기준으로 자료를 제공합니다. VWorld의 법정구역 코드와 주민등록 행정기관코드는 동일하다고 가정하지 않습니다.")
        if vworld_code:
            st.caption(f"지도에서 확인한 VWorld 행정구역 코드: {vworld_code}")
        if explicit_admin_code:
            st.caption("지도 응답에 주민등록 행정기관코드가 직접 포함되어 있어 자동 입력했습니다.")
        elif codebook_admin_code:
            st.caption("지역코드_연계표.xlsx에서 해당 지역의 MOIS admmCd를 읽어 자동 입력했습니다.")
        else:
            st.caption("지역코드_연계표.xlsx의 MOIS_admmCd가 비어 있어 직접 입력이 필요합니다. KiKcd_B·VWorld 코드를 대신 넣지 마세요.")
        c1, c2 = st.columns(2)
        with c1:
            month = st.text_input(
                "통계년월 (YYYYMM)", value=cache.get("population_month", korea_now().strftime("%Y%m")),
                key=f"local_month_{token}",
            )
        with c2:
            admin_code = st.text_input(
                "주민등록 행정기관코드", value=cache.get("population_admin_code", auto_admin_code),
                key=f"local_population_admin_{token}", placeholder="공식 행정기관코드",
                help="VWorld 코드와 별도일 수 있습니다. 공식 행정기관코드를 확인한 뒤 입력하세요.",
            )
        if st.button("주민등록 원자료 조회", key=f"local_population_fetch_{token}", type="primary"):
            population_level = "5" if level == "광역자치단체" else "6"
            rows, message = data_go_call("population", {
                "month": month.strip(), "admin_code": admin_code.strip(), "level": population_level,
            })
            _save_region_data_cache(
                level, region_name,
                population_rows=rows, population_error=message,
                population_month=month.strip(), population_admin_code=admin_code.strip(),
            )
            cache = _region_data_cache(level, region_name)
        if cache.get("population_error"):
            st.warning(cache["population_error"])
        if cache.get("population_rows"):
            st.caption(f"{region_name} · 기준월 {cache.get('population_month', '확인 필요')} · 원자료")
            table_view(cache["population_rows"], 100)

        with st.expander("행정동·법정동 코드 매핑표 확인", expanded=False):
            st.caption("지역코드_연계표.xlsx의 행정동_법정동_매핑 시트에서 사용자가 입력한 행정동·법정동 연결만 조회합니다. 빈 코드나 이름이 비슷한 행은 자동으로 추정하지 않습니다.")
            dong_lookup_name = st.text_input("행정동명", key=f"local_dong_mapping_name_{token}", placeholder="예: 행정동명")
            if st.button("엑셀 매핑표 조회", key=f"local_dong_mapping_lookup_{token}", disabled=not dong_lookup_name.strip()):
                mapping_rows = lookup_admin_legal_dong_mappings(
                    sido_name,
                    "" if level == "광역자치단체" else region_name,
                    dong_lookup_name.strip(),
                )
                if mapping_rows:
                    st.dataframe(pd.DataFrame(mapping_rows), use_container_width=True, hide_index=True)
                else:
                    st.info("일치하는 매핑 행이 없습니다. 지역코드_연계표.xlsx의 행정동_법정동_매핑 시트에 행정동명과 확인된 코드를 입력해 주세요.")

        st.divider()
        st.markdown("**지방의회의원 정수 통계**")
        st.caption("기수별·유형별 전국 통계입니다. 특정 기초자치단체의 현재 의석 수로 단정하지 않고 지역 정보의 참고자료로 표시합니다.")
        if st.button("지방의회 정수 원자료 조회", key=f"local_council_fetch_{token}"):
            rows, message = data_go_call("council", {})
            _save_region_data_cache(level, region_name, council_rows=rows, council_error=message)
            cache = _region_data_cache(level, region_name)
        if cache.get("council_error"):
            st.warning(cache["council_error"])
        if cache.get("council_rows"):
            table_view(cache["council_rows"], 100)

        st.divider()
        st.markdown("**KOSIS 지역통계 찾기 및 조회**")
        st.caption("KOSIS e-지방지표에는 고령인구비율·청년인구비율·출생아수·합계출산율 등이 있습니다. 통계표마다 분류 코드가 다르므로 원자료의 표·항목·지역 코드를 확인한 뒤 조회합니다.")
        list_col1, list_col2 = st.columns(2)
        with list_col1:
            view_code = st.selectbox(
                "통계목록 유형",
                ["MT_GTITLE01", "MT_GTITLE02", "MT_GTITLE03"],
                key=f"local_kosis_view_{token}",
                format_func=lambda value: {
                    "MT_GTITLE01": "e-지방지표 · 주제별",
                    "MT_GTITLE02": "e-지방지표 · 지역별",
                    "MT_GTITLE03": "e-지방지표 · 테마별",
                }.get(value, value),
            )
        with list_col2:
            parent_id = st.text_input("목록 ID (첫 조회는 A)", value="A", key=f"local_kosis_parent_{token}")
        if st.button("KOSIS 통계표 목록 불러오기", key=f"local_kosis_list_fetch_{token}"):
            rows, message = kosis_list_call(parent_id, view_code)
            _save_region_data_cache(level, region_name, kosis_list_rows=rows, kosis_list_error=message)
            cache = _region_data_cache(level, region_name)
        if cache.get("kosis_list_error"):
            st.warning(cache["kosis_list_error"])
        if cache.get("kosis_list_rows"):
            table_view(cache["kosis_list_rows"], 100)
            st.caption("목록의 TBL_ID·ORG_ID와 통계표 설명을 확인한 뒤 아래 조회 항목을 입력하세요.")

        metric_target = st.selectbox(
            "원자료를 지역 통계 카드에 연결",
            ["원자료 표만 조회", "출생아 수", "합계출산율", "고령인구 비율", "청년인구 비율"],
            key=f"local_kosis_metric_target_{token}",
            help="지역코드_연계표.xlsx의 KOSIS_통계표별·KOSIS_지역분류_매핑 시트 값을 우선 불러옵니다. 빈칸은 직접 입력할 수 있습니다.",
        )
        kosis_defaults = lookup_kosis_codebook_config(
            st.session_state.get("local_selected_sido", region_name if level == "광역자치단체" else ""),
            region_name,
            metric_target,
        ) if metric_target != "원자료 표만 조회" else {}
        c1, c2, c3 = st.columns(3)
        with c1:
            org_id = st.text_input("기관 ID (orgId)", value=kosis_defaults.get("ORG_ID", ""), key=f"local_kosis_org_{token}")
        with c2:
            table_id = st.text_input("통계표 ID (tblId)", value=kosis_defaults.get("TBL_ID", ""), key=f"local_kosis_table_{token}")
        with c3:
            item_id = st.text_input("항목 ID (itmId)", value=kosis_defaults.get("ITM_ID", "ALL") or "ALL", key=f"local_kosis_item_{token}")
        c4, c5 = st.columns(2)
        with c4:
            region_code_input = st.text_input(
                "지역 분류값 (objL1)", value=kosis_defaults.get("OBJ_L1", ""), key=f"local_kosis_region_{token}",
                help="KOSIS 통계표별 지역 분류값입니다. 엑셀에서 입력한 코드가 있으면 자동으로 불러옵니다. 다른 행정코드를 대신 넣지 마세요.",
            )
        with c5:
            period = st.selectbox("수록주기", ["Y", "S", "Q", "M", "D"], index=( ["Y", "S", "Q", "M", "D"].index(kosis_defaults.get("PRD_SE")) if kosis_defaults.get("PRD_SE") in ["Y", "S", "Q", "M", "D"] else 0 ), key=f"local_kosis_period_{token}")
        period_help = {"D": "YYYYMMDD", "M": "YYYYMM", "Q": "YYYY01~YYYY04", "S": "YYYY01~YYYY02", "Y": "YYYY"}[period]
        c6, c7 = st.columns(2)
        with c6:
            start_period = st.text_input("시작 시점 (선택)", key=f"local_kosis_start_{token}", help=period_help)
        with c7:
            end_period = st.text_input("종료 시점 (선택)", key=f"local_kosis_end_{token}", help=period_help)
        if kosis_defaults:
            st.caption("기관·통계표·항목·지역 분류 기본값은 지역코드_연계표.xlsx에서 불러왔습니다. 비어 있는 셀은 엑셀에서 채우거나 여기서 직접 입력할 수 있습니다.")
        if st.button("KOSIS 지역통계 원자료 조회", key=f"local_kosis_fetch_{token}"):
            rows, message = kosis_data_call(org_id, table_id, item_id, region_code_input, period, start_period, end_period)
            updates = {"kosis_rows": rows, "kosis_error": message, "kosis_metric_error": ""}
            if metric_target != "원자료 표만 조회":
                metric_values, metric_message = update_kosis_metric_values(
                    cache.get("kosis_metric_values", {}), metric_target, rows, region_name, message,
                )
                updates["kosis_metric_values"] = metric_values
                updates["kosis_metric_error"] = metric_message
            _save_region_data_cache(level, region_name, **updates)
            st.rerun()
        if cache.get("kosis_error"):
            st.warning(cache["kosis_error"])
        if cache.get("kosis_metric_error"):
            st.info(cache["kosis_metric_error"])
        if cache.get("kosis_rows"):
            table_view(cache["kosis_rows"], 100)
        st.link_button("KOSIS e-지방지표에서 지표 정의·기준연도 확인", "https://kosis.kr/visual/eRegionIndex/eRegionTheme.do")


def _render_local_map(geo, level, map_key, zoom):
    """지도 렌더링과 클릭된 행정구역의 이름을 반환합니다."""
    if not HAS_MAP or not geo or not geo.get("features"):
        return None, ""
    map_object = build_admin_map(geo, zoom)
    result = st_folium(
        map_object, height=520, use_container_width=True,
        returned_objects=["last_object_clicked_tooltip", "last_object_clicked_count", "last_active_drawing"],
        key=map_key,
    ) or {}
    layer_name = "lt_c_adsido_info" if level == "시도" else "lt_c_adsigg_info"
    configured_name_field = lookup_vworld_name_field(layer_name)
    fields = tuple([configured_name_field] if configured_name_field else []) + (
        ("ctp_kor_nm", "CTP_KOR_NM", "sido_nm", "name", "NAME")
        if level == "시도" else
        ("sig_kor_nm", "SIG_KOR_NM", "sig_nm", "sigungu_nm", "name", "NAME")
    )
    features = geo.get("features", [])
    click_count = result.get("last_object_clicked_count") or 0
    counter_key = f"{map_key}_last_click"
    previous = st.session_state.get(counter_key, 0)
    clicked = None
    if click_count != previous:
        st.session_state[counter_key] = click_count
        drawing = result.get("last_active_drawing")
        if isinstance(drawing, dict) and drawing.get("properties"):
            clicked = drawing
        else:
            clicked = _selected_feature_by_tooltip(features, result.get("last_object_clicked_tooltip"), fields)
    if clicked:
        return region_property(clicked, fields), clicked
    return None, None


def render_local_government():
    """전국 지도 → 광역자치단체 → 시군구 화면으로 이동합니다."""
    render_hero("지방 정부", "대한민국 지도에서 광역자치단체를 선택한 뒤 해당 지역의 기초자치단체를 살펴봅니다.")
    st.caption("지역명과 API별 코드는 저장소의 지역코드_연계표.xlsx에서 관리합니다. 빈 코드 셀은 직접 확인 후 입력할 수 있습니다.")
    geo, message = _ensure_local_map("시도")
    if message:
        st.warning(message)
    sido_names = get_sido_names()
    feature_by_sido = {}
    if geo and HAS_MAP:
        if geo.get("_truncated_notice"):
            st.warning(geo["_truncated_notice"])
        selected, feature = _render_local_map(geo, "시도", "local_sido_map_final", 7)
        if selected:
            canonical = match_sido_codebook_name(selected)
            if canonical:
                _select_sido(canonical, feature)
                st.rerun()
            else:
                st.warning(f"지도에서 선택한 '{selected}'은 지역코드_연계표.xlsx의 현행 광역명과 일치하지 않습니다. 행정구역 개편 후 WFS 경계가 갱신되었는지 확인해 주세요.")
        configured_name_field = lookup_vworld_name_field("lt_c_adsido_info")
        name_fields = tuple([configured_name_field] if configured_name_field else []) + ("ctp_kor_nm", "CTP_KOR_NM", "sido_nm", "name", "NAME")
        for map_feature in geo.get("features", []):
            map_name = region_property(map_feature, name_fields)
            canonical = match_sido_codebook_name(map_name)
            if canonical:
                feature_by_sido[canonical] = map_feature
        missing = [name for name in sido_names if name not in feature_by_sido]
        if missing:
            st.warning("VWorld 지도 응답에서 다음 현행 광역자치단체 경계를 찾지 못했습니다: " + ", ".join(missing) + ". 아래 목록 선택은 가능하지만, 해당 지역의 지도 경계는 WFS 최신 자료가 필요합니다.")
        choice = st.selectbox("광역자치단체 선택", ["선택하세요"] + sido_names, key="codebook_sido_choice")
        if choice != "선택하세요" and st.button("선택한 광역자치단체로 이동", key="codebook_sido_next", type="primary"):
            _select_sido(choice, feature_by_sido.get(choice))
            st.rerun()
    else:
        if not REGION_CODEBOOK_PATH.exists():
            st.warning("지역코드_연계표.xlsx가 없습니다. GitHub 저장소 최상위에 엑셀 파일을 올려 주세요. 내장된 2026년 현행 광역명 목록으로 임시 선택을 제공합니다.")
        cols = st.columns(3)
        for index, name in enumerate(sido_names):
            with cols[index % 3]:
                if st.button(name, key=f"fallback_sido_{index}", use_container_width=True):
                    _select_sido(name, None)
                    st.rerun()


def render_local_sigungu():
    """선택한 광역자치단체의 시군구 경계 지도와 광역 통계를 함께 표시합니다."""
    sido = st.session_state.get("local_selected_sido", "")
    if not sido:
        st.warning("먼저 광역자치단체를 선택해 주세요.")
        if st.button("전국 지도 보기"):
            st.session_state.page = "지방 정부"
            st.rerun()
        return
    top_left, top_right = st.columns([4, 1])
    with top_left:
        render_hero(sido, f"{sido}의 기초자치단체를 선택하세요.")
    with top_right:
        if st.button("← 전국 지도", use_container_width=True):
            _change_local_sido()
            st.rerun()

    # 세종특별자치시는 단층제이므로 별도 시·군·구 선택 지도 단계가 없습니다.
    if is_single_tier_local_authority(sido):
        st.info("세종특별자치시는 광역자치단체와 기초자치단체가 분리되지 않는 단층제입니다. 별도의 시·군·구 경계 선택 없이 상세 화면으로 이동합니다.")
        with st.container(border=True):
            st.markdown("### 세종특별자치시")
            st.caption("광역자치단체(단층제) · 별도 기초자치단체 없음")
            if st.button("세종특별자치시 상세 보기", key="sejong_single_tier_detail", type="primary", use_container_width=True):
                _select_sigungu(sido, st.session_state.get("local_sido_feature"))
                st.rerun()
        st.divider()
        st.markdown(f"### {sido} 광역자치단체 기본 정보")
        render_region_statistics(sido, st.session_state.get("local_sido_feature"), "광역자치단체", parent=True)
        _region_data_tools(sido, "광역자치단체", st.session_state.get("local_sido_feature"))
        return

    geo, message = _ensure_local_map("시군구")
    if message:
        st.warning(message)
    candidates = get_local_region_names(sido)
    feature_by_region = {}
    if geo and HAS_MAP:
        if geo.get("_truncated_notice"):
            st.warning(geo["_truncated_notice"])
        selected, feature = _render_local_map(geo, "시군구", f"local_sigungu_map_final_{st.session_state.get('local_selected_sido_code', 'none')}", 9)
        if selected:
            canonical = match_local_codebook_name(sido, selected)
            if canonical:
                _select_sigungu(canonical, feature)
                st.rerun()
            else:
                st.warning(f"지도에서 선택한 '{selected}'은 지역코드_연계표.xlsx의 현행 자치단체 목록과 일치하지 않습니다. 일반구 또는 개편 전 명칭일 수 있습니다.")
        configured_name_field = lookup_vworld_name_field("lt_c_adsigg_info")
        fields = tuple([configured_name_field] if configured_name_field else []) + ("sig_kor_nm", "SIG_KOR_NM", "sig_nm", "sigungu_nm", "name", "NAME")
        for map_feature in geo.get("features", []):
            map_name = region_property(map_feature, fields)
            canonical = match_local_codebook_name(sido, map_name)
            if canonical:
                feature_by_region[canonical] = map_feature
        missing = [name for name in candidates if name not in feature_by_region]
        if missing:
            st.warning("엑셀에는 있지만 현재 VWorld 시군구 응답에서 경계를 찾지 못한 지역: " + ", ".join(missing) + ". 지도 경계 자료가 최신 개편을 반영하는지 확인하세요.")
        choices = ["선택하세요"] + candidates
        choice = st.selectbox("기초자치단체 선택", choices, key=f"codebook_sigungu_choice_{_region_widget_token('광역자치단체', sido)}")
        if choice != "선택하세요" and st.button("선택한 지역 상세 보기", key="codebook_sigungu_next", type="primary"):
            _select_sigungu(choice, feature_by_region.get(choice))
            st.rerun()
    else:
        if not candidates:
            st.warning("지역코드_연계표.xlsx에서 이 광역자치단체의 기초자치단체 이름을 찾지 못했습니다. 엑셀의 광역_기초목록 시트를 확인해 주세요.")
        else:
            st.info("VWorld 경계를 불러오지 못해 엑셀의 현행 지역명 목록을 사용합니다. 지도 면적 계산은 경계가 연결되기 전까지 제공되지 않습니다.")
            choice = st.selectbox("기초자치단체 선택", ["선택하세요"] + candidates, key=f"manual_codebook_sigungu_{_region_widget_token('광역자치단체', sido)}")
            if choice != "선택하세요" and st.button("선택한 지역 상세 보기", key="manual_codebook_sigungu_next", type="primary"):
                _select_sigungu(choice, None)
                st.rerun()

    st.divider()
    st.markdown(f"### {sido} 광역자치단체 기본 정보")
    render_region_statistics(sido, st.session_state.get("local_sido_feature"), "광역자치단체", parent=True)
    _region_data_tools(sido, "광역자치단체", st.session_state.get("local_sido_feature"))
    st.caption("위 통계는 선택한 광역자치단체 기준입니다. 아래 지도 또는 엑셀의 지역명 목록에서 기초자치단체를 선택하면 별도 상세 화면으로 이동합니다.")

def render_local_detail():
    sido = st.session_state.get("local_selected_sido", "")
    sigungu = st.session_state.get("local_selected_sigungu", "")
    if not sigungu:
        st.warning("선택된 기초자치단체가 없습니다.")
        if st.button("지역 선택 화면으로 돌아가기"):
            st.session_state.page = "지방정부 시군구"
            st.rerun()
        return
    if st.button("← 지역 선택", key="local_detail_back", use_container_width=False):
        st.session_state.page = "지방정부 시군구"
        st.rerun()

    detail_row = find_region_codebook_row(sido, sigungu, step="기초") or find_region_codebook_row(sido, sigungu) or {}
    region_type = str(detail_row.get("행정구역유형", "기초자치단체")).strip()
    is_admin_city = region_type == "행정시"
    is_single_tier = region_type == "특별자치시(단층제)"
    badge_text = "행정시" if is_admin_city else "광역자치단체(단층제)" if is_single_tier else "기초자치단체"
    statistics_level = "광역자치단체" if is_single_tier else "기초자치단체"
    with st.container(border=True):
        title_col, badge_col = st.columns([4, 1])
        with title_col:
            st.markdown(f"### {sigungu}")
        with badge_col:
            st.markdown(f"<div style='text-align:right'><span style='background:var(--secondary-background-color);padding:4px 9px;border-radius:20px'>{html.escape(badge_text)}</span></div>", unsafe_allow_html=True)
        st.markdown("<div style='text-align:center;font-weight:800;font-size:1.05rem'>지역 기본 정보</div>", unsafe_allow_html=True)
        st.caption("면적 · 주민등록인구 · 인구밀도 · 출생아 수 · 합계출산율 · 고령인구 · 청년인구")
        render_region_statistics(sigungu, st.session_state.get("local_sigungu_feature"), statistics_level)
        st.divider()
        left, right = st.columns(2, gap="small")
        with left:
            st.markdown("### 지방 행정부")
            leader_label = "세종특별자치시장" if is_single_tier else "시장·군수·구청장"
            leader_role = "광역자치단체의 장 · 집행기관" if is_single_tier else "지방자치단체의 장 · 집행기관"
            render_node(leader_label, leader_role, "local_mayor", "local_executive", "지방정부 상세", "🏢")
            st.markdown('<div class="org-arrow">↓</div>', unsafe_allow_html=True)
            render_node("부단체장", "부시장·부군수·부구청장 등", "local_deputy", "local_executive", "지방정부 상세")
            st.markdown('<div class="org-arrow">↓</div>', unsafe_allow_html=True)
            render_node("실·국·본부", "정책 분야별 행정조직", "local_bureaus", "local_executive", "지방정부 상세")
            st.caption("과·담당관 등 하부조직은 지자체별 직제에 따라 달라집니다.")
        with right:
            if is_admin_city:
                st.markdown("### 광역 지방 의회")
                st.markdown("**제주특별자치도의회**")
                st.caption("제주시·서귀포시는 행정시이므로 별도의 기초자치단체 의회가 없습니다. 지방의회는 제주특별자치도 단위로 구성됩니다.")
            elif is_single_tier:
                st.markdown("### 지방 의회")
                render_node("세종특별자치시의회", "광역자치단체의 지방의회 · 의결기관", "local_council_root", "local_council", "지방정부 상세", "🏛️")
                st.markdown('<div class="org-arrow">↓</div>', unsafe_allow_html=True)
                render_node("의장단·상임위원회", "의장·부의장 · 소관 분야 심사", "local_committee", "local_council", "지방정부 상세")
                st.markdown('<div class="org-arrow">↓</div>', unsafe_allow_html=True)
                render_node("의회사무처", "의정활동 및 의회 운영 지원", "local_council_office", "local_council", "지방정부 상세")
                st.caption("세종특별자치시의회는 단층제 광역자치단체의 의회입니다.")
            else:
                st.markdown("### 지방 의회")
                render_node("시·군·구의회", "지역 주민 대표 · 의결기관", "local_council_root", "local_council", "지방정부 상세", "🏛️")
                st.markdown('<div class="org-arrow">↓</div>', unsafe_allow_html=True)
                render_node("의장단·상임위원회", "의장·부의장 · 소관 분야 심사", "local_committee", "local_council", "지방정부 상세")
                st.markdown('<div class="org-arrow">↓</div>', unsafe_allow_html=True)
                render_node("의회사무국·사무과", "의정활동 및 의회 운영 지원", "local_council_office", "local_council", "지방정부 상세")
                st.caption("실제 위원회·사무조직 편제는 지역별로 다릅니다.")
        st.caption(f"{sigungu}의 실제 조직도를 그대로 복제한 것이 아니라, 지방 행정부와 지방 의회를 구분해 보여 주는 일반 구조 예시입니다.")

    st.divider()
    _region_data_tools(sigungu, statistics_level, st.session_state.get("local_sigungu_feature"))
    st.link_button("지방자치·행정안전부 공식 자료", "https://www.mois.go.kr/")


# ============================================================
# 16. 앱 사이드바 / 라우팅
# ============================================================



def _reset_local_navigation():
    """지방정부 메뉴를 새로 열 때 이전 지역 선택·조회 결과를 초기화합니다."""
    st.session_state.local_stage = "sido"
    st.session_state.local_sido_attempted = False
    st.session_state.local_sido_geo = None
    st.session_state.local_selected_sido = ""
    st.session_state.local_selected_sigungu = ""
    st.session_state.local_selected_sido_code = ""
    st.session_state.local_selected_sigungu_code = ""
    st.session_state.local_sido_feature = None
    st.session_state.local_sigungu_feature = None
    st.session_state.local_sigungu_geo = None
    st.session_state.local_sigungu_attempted = False
    st.session_state.local_region_data_cache = {}
    _reset_local_region_data()


def render_sidebar():
    st.markdown("### 메뉴")
    nav_items = [
        ("홈", "🏠  홈", "home", "blue"),
        ("정치 퀴즈", "🧠  정치 퀴즈", "quiz", "yellow"),
        ("뉴스 속보", "📰  뉴스·속보", "news", "pink"),
        ("정치 자료 탐색", "🔎  정치 자료 탐색", "data", "sky"),
    ]
    for page, label, mode, color in nav_items:
        if soft_button(label, f"nav_{mode}", color=color, use_container_width=True):
            st.session_state.page = page
            if mode == "quiz":
                st.session_state.quiz_mode = "today"
                st.session_state.quiz_active = False
                st.session_state.quiz_return_page = "정치 퀴즈"
            elif mode == "data":
                st.session_state.api_selected_item = ""
            st.rerun()

    st.markdown("<div class='sidebar-section-label'>📚 공부하기</div>", unsafe_allow_html=True)
    study_items = [
        ("정부 조직", "🏢  정부 조직", "orange"),
        ("국회 조직", "🏛️  국회 조직", "blue"),
        ("법원 조직", "⚖️  법원 조직", "purple"),
        ("지방 정부", "🗺️  지방정부", "mint"),
    ]
    for page_name, label, color in study_items:
        if soft_button(label, f"nav_study_{page_name}", color=color, use_container_width=True):
            st.session_state.page = page_name
            if page_name == "지방 정부":
                _reset_local_navigation()
            st.session_state.org_detail = ""
            st.rerun()
    if soft_button("📘  정보 확인 가이드", "nav_information_guide", color="sky", use_container_width=True):
        st.session_state.page = "정보 확인 가이드"
        st.rerun()

    st.divider()
    if soft_button("🧪  시뮬레이션", "nav_simulation", color="purple", use_container_width=True):
        st.session_state.page = "시뮬레이션"
        st.rerun()
    if not QUIZ_PATH.exists():
        st.caption("Quiz.txt가 없으면 내장 예시 문제로 실행됩니다.")
    if not NEWS_PATH.exists():
        st.caption("NEWS.txt가 없으면 기본 RSS 목록으로 실행됩니다.")



def render_simulation():
    render_hero("시뮬레이션", "외부 Streamlit 웹앱을 이 화면 안에서 실행합니다.")
    if not str(SIMULATION_APP_URL or "").strip():
        st.info("연결할 외부 Streamlit 앱 주소가 아직 등록되지 않았습니다.")
        st.write("친구가 만든 앱의 HTTPS 주소를 확인한 뒤 main.py 상단의 `SIMULATION_APP_URL`에 입력하면 이 화면에 삽입할 수 있습니다.")
        st.caption("상대 앱이 iframe 삽입을 허용하지 않으면 브라우저 보안 정책으로 표시되지 않을 수 있습니다. 그 경우 별도 탭으로 여는 링크 방식이 필요합니다.")
        return
    if not is_safe_http_url(SIMULATION_APP_URL) or not str(SIMULATION_APP_URL).lower().startswith("https://"):
        st.error("SIMULATION_APP_URL에는 유효한 HTTPS 주소만 입력할 수 있습니다.")
        return
    st.components.v1.iframe(SIMULATION_APP_URL, height=850, scrolling=True)

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
            elif page == "정치 퀴즈":
                render_quiz_hub(quiz_questions)
            elif page == "뉴스 속보":
                render_news()
            elif page == "정치 자료 탐색":
                render_data_explorer()
            elif page == "정보 확인 가이드":
                render_information_guide()
            elif page == "시뮬레이션":
                render_simulation()
            elif page == "정부 조직":
                render_government()
            elif page == "국회 조직":
                render_congress()
            elif page == "법원 조직":
                render_court()
            elif page == "지방 정부":
                render_local_government()
            elif page == "지방정부 시군구":
                render_local_sigungu()
            elif page == "지방정부 상세":
                render_local_detail()
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
