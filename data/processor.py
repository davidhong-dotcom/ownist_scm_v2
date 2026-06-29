"""
data/processor.py
-----------------
데이터 전처리 로직 모듈 (UI 로직과 완전 분리)
실제 파일 컬럼 구조 기반으로 작성:
  - 현재고: '상품코드', '창고존', '현재고' (적치존 필터 후 집계)
  - 출고현황: '일 자', '상품코드', '수불수량' (콤마 포함 문자열)
  - Google Sheets: 시트명 'DB', 컬럼 구분/품목구분/상품코드/상품명
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import io
import streamlit as st


# ────────────────────────────────────────────────
# 상수
# ────────────────────────────────────────────────
KST = ZoneInfo("Asia/Seoul")
RECENT_DAYS     = 90    # 지표 산출 기준 기간 (일)
SAFETY_RATIO    = 1.5   # 안전재고 배수
INVENTORY_ZONE  = "적치존"  # 현재고 집계 기준 창고존


# ────────────────────────────────────────────────
# 공통 유틸
# ────────────────────────────────────────────────
def get_today_kst() -> "datetime.date":
    """한국 시간(KST) 기준 오늘 날짜 반환"""
    return datetime.now(KST).date()


def clean_numeric(series: pd.Series) -> pd.Series:
    """
    숫자 컬럼 정규화: 콤마 및 문자(개, EA 등) 제거 → float 변환.
    변환 불가 값은 0으로 대체.
    """
    # 1. 콤마 제거
    s = series.astype(str).str.replace(",", "", regex=False)
    # 2. 숫자(소수점 포함) 부분만 정규식으로 추출 (예: "6개" -> "6", " 10 " -> "10")
    s = s.str.extract(r'([-+]?\d*\.?\d+)')[0]
    # 3. float 변환
    return pd.to_numeric(s, errors="coerce").fillna(0)


def safe_divide(numerator: float, denominator: float, fallback="출고없음"):
    """ZeroDivisionError 방지: denominator == 0 이면 fallback 반환"""
    if pd.isna(denominator) or denominator == 0:
        return fallback
    return numerator / denominator


# ────────────────────────────────────────────────
# 마스터 DB (Google Sheets → CSV export)
# ────────────────────────────────────────────────
def build_gsheet_csv_url(spreadsheet_url: str, sheet_name: str = "DB") -> str:
    """
    Google Sheets 편집 URL에서 CSV export URL 생성.
    사용자가 붙여넣은 URL 형식:
      https://docs.google.com/spreadsheets/d/{ID}/edit?gid={GID}#gid={GID}
    또는 이미 export URL인 경우 그대로 반환.
    """
    import re

    # 이미 export URL 형식이면 그대로 사용
    if "export?format=csv" in spreadsheet_url:
        return spreadsheet_url

    # Sheet ID 추출
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", spreadsheet_url)
    if not m:
        raise ValueError("유효한 Google Sheets URL이 아닙니다.")
    sheet_id = m.group(1)

    # gid 추출 (없으면 0)
    gid_m = re.search(r"[?&#]gid=(\d+)", spreadsheet_url)
    gid = gid_m.group(1) if gid_m else "0"

    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/export?format=csv&gid={gid}"
    )


@st.cache_data(ttl=3600)
def load_master_from_gsheet(spreadsheet_url: str, sheet_name: str = "DB") -> pd.DataFrame:
    """
    Google Sheets에서 마스터 DB 로드.
    시트명 'DB', 컬럼: 구분 / 품목구분 / 상품코드 / 상품명
    """
    csv_url = build_gsheet_csv_url(spreadsheet_url, sheet_name)
    df = pd.read_csv(csv_url, dtype=str).fillna("")
    df.columns = df.columns.str.strip()

    required = ["구분", "품목구분", "상품코드", "상품명"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(
            f"마스터 DB에 필수 컬럼이 없습니다: {missing}\n"
            f"실제 컬럼: {list(df.columns)}"
        )

    df["상품코드"] = df["상품코드"].str.strip()
    return df[required].query("상품코드 != ''").reset_index(drop=True)


def load_master_from_file(file_obj) -> pd.DataFrame:
    """CSV / Excel 파일로 마스터 DB 로드 (로컬 테스트·대체용)"""
    name = getattr(file_obj, "name", "")
    if str(name).endswith(".csv"):
        df = pd.read_csv(file_obj, dtype=str).fillna("")
    else:
        df = pd.read_excel(file_obj, dtype=str).fillna("")
    df.columns = df.columns.str.strip()
    df["상품코드"] = df["상품코드"].str.strip()
    return df[["구분", "품목구분", "상품코드", "상품명"]].query("상품코드 != ''").reset_index(drop=True)


# ────────────────────────────────────────────────
# 현재고 파일 파싱
# 실제 컬럼: 상품코드, 창고존, 현재고
# 적치존(INVENTORY_ZONE) 기준으로 필터 후 상품코드별 합산
# ────────────────────────────────────────────────
def parse_inventory_file(file_obj) -> pd.DataFrame:
    """
    현재고 엑셀(.xls/.xlsx) 파싱.
    - 창고존 == '적치존' 행만 사용
    - 상품코드별 현재고 합산
    반환 컬럼: 상품코드(str), 현재고(float)
    """
    raw = _read_xls_or_xlsx(file_obj)
    raw.columns = raw.columns.str.strip()

    # 컬럼 유연 매핑
    code_col = _find_col(raw, ["상품코드", "품목코드", "코드"])
    zone_col = _find_col(raw, ["창고존", "존", "구역"], required=False)
    qty_col  = _find_col(raw, ["현재고", "재고수량", "수량", "재고"])

    raw[code_col] = raw[code_col].astype(str).str.strip()

    # 창고존 필터 (컬럼 있을 때만)
    if zone_col and zone_col in raw.columns:
        filtered = raw[raw[zone_col].astype(str).str.strip() == INVENTORY_ZONE].copy()
    else:
        filtered = raw.copy()

    filtered[qty_col] = clean_numeric(filtered[qty_col])

    result = (
        filtered
        .groupby(code_col, as_index=False)[qty_col]
        .sum()
        .rename(columns={code_col: "상품코드", qty_col: "현재고"})
    )
    return result.query("상품코드 != '' and 상품코드 != 'nan'").reset_index(drop=True)


# ────────────────────────────────────────────────
# 비밀번호 보호 xlsx 복호화 헬퍼
# ────────────────────────────────────────────────
def decrypt_xlsx(file_obj, password: str) -> bytes:
    """
    msoffcrypto-tool을 사용해 비밀번호가 걸린 xlsx 파일을 복호화.
    반환: 복호화된 xlsx 파일의 bytes
    """
    import msoffcrypto

    content = file_obj.read() if hasattr(file_obj, "read") else open(file_obj, "rb").read()
    encrypted = io.BytesIO(content)
    office_file = msoffcrypto.OfficeFile(encrypted)
    office_file.load_key(password=password)
    decrypted = io.BytesIO()
    office_file.decrypt(decrypted)
    return decrypted.getvalue()


# ────────────────────────────────────────────────
# 기간별 출고완료 내역 파싱 (비밀번호 xlsx)
# 컬럼 매핑:
#   B(idx 1)  : 주문사
#   H(idx 7)  : 주문번호 (동일 주문번호 = 한 주문)
#   L(idx 11) : 출고일시
#   X(idx 23) : 상품코드
#   Y(idx 24) : 상품명
#   AC(idx 28): 출고량
#   AD(idx 29): 금액 (동일 주문번호끼리 합산 → 주문금액합계)
# ────────────────────────────────────────────────
def parse_ownist_shipping_file(file_obj, password: str) -> pd.DataFrame:
    """
    기간별 출고완료 내역_(주)오니스트_YYYYMMDD_YYYYMMDD.xlsx 파싱.

    반환 컬럼:
        출고일자(date), 주문사(str), 주문번호(str),
        상품코드(str), 상품명(str), 출고량(float), 주문금액합계(float)
    """
    # 복호화
    decrypted_bytes = decrypt_xlsx(file_obj, password)

    raw = pd.read_excel(
        io.BytesIO(decrypted_bytes),
        engine="openpyxl",
        dtype=str,
    ).fillna("")

    # 열 인덱스 기반 추출 (컬럼명이 깨질 수 있으므로 iloc 사용)
    # B=1, H=7, L=11, X=23, Y=24, AC=28, AD=29
    IDX = {"주문사": 1, "주문번호": 7, "출고일시": 11,
           "상품코드": 23, "상품명": 24, "출고량": 28, "금액": 29}

    df = pd.DataFrame({k: raw.iloc[:, v] for k, v in IDX.items()})

    # 데이터 정제
    df["출고일자"]  = pd.to_datetime(df["출고일시"], errors="coerce").dt.date
    df["출고량"]    = clean_numeric(df["출고량"])
    df["금액"]      = clean_numeric(df["금액"])
    df["상품코드"]  = df["상품코드"].astype(str).str.strip()
    df["주문번호"]  = df["주문번호"].astype(str).str.strip()
    df["주문사"]    = df["주문사"].astype(str).str.strip()
    df["상품명"]    = df["상품명"].astype(str).str.strip()

    # 유효 행만 유지
    df = df.dropna(subset=["출고일자"])
    df = df[df["상품코드"].str.strip() != ""].reset_index(drop=True)

    # 동일 주문번호의 금액 합산 → 주문금액합계 컬럼 추가
    order_amount = (
        df.groupby("주문번호", as_index=False)["금액"]
          .sum()
          .rename(columns={"금액": "주문금액합계"})
    )
    df = df.merge(order_amount, on="주문번호", how="left")
    df = df.drop(columns=["금액", "출고일시"])

    return df[[
        "출고일자", "주문사", "주문번호",
        "상품코드", "상품명", "출고량", "주문금액합계"
    ]].reset_index(drop=True)


# ────────────────────────────────────────────────
# 일자별 출고현황 파일 파싱 (새로운 포맷)
# ────────────────────────────────────────────────
def parse_daily_shipping_file(file_obj) -> pd.DataFrame:
    """
    일자별 출고현황_YYYYMMDD_HHMMSS.xls 파싱 (암호 없음)
    
    A열(0): 출고일자
    E열(4): 거래처명(주문사)
    F열(5): 상품코드
    H열(7): 상품명
    S열(18): 출고수량
    """
    # 암호가 없으므로 바로 읽기
    raw = pd.read_excel(
        file_obj,
        dtype=str,
    ).fillna("")

    # 열 인덱스 기반 추출
    # A=0, E=4, F=5, H=7, S=18
    IDX = {"출고일자": 0, "주문사": 4, "상품코드": 5, "상품명": 7, "출고량": 18}

    df = pd.DataFrame({k: raw.iloc[:, v] for k, v in IDX.items()})

    # 데이터 정제
    df["출고일자"]  = pd.to_datetime(df["출고일자"], errors="coerce").dt.date
    df["출고량"]    = clean_numeric(df["출고량"])
    df["상품코드"]  = df["상품코드"].astype(str).str.strip()
    df["주문사"]    = df["주문사"].astype(str).str.strip()
    df["상품명"]    = df["상품명"].astype(str).str.strip()

    # 주문번호와 금액이 없으므로, 주문사를 가짜 주문번호로 생성하여 고유키 충돌 방지
    df["주문번호"]  = "집계-" + df["주문사"]
    df["주문금액합계"] = 0.0

    # 유효 행만 유지
    df = df.dropna(subset=["출고일자"])
    df = df[df["상품코드"].str.strip() != ""].reset_index(drop=True)

    # 동일 출고일자, 주문사, 상품코드가 여러 줄 있을 수 있으므로 반환 전 합산은 하지 않고,
    # supabase_client.py 의 upsert 로직에서 groupby 하도록 둡니다.

    return df[[
        "출고일자", "주문사", "주문번호",
        "상품코드", "상품명", "출고량", "주문금액합계"
    ]].reset_index(drop=True)


# ────────────────────────────────────────────────
# 일자별 출고현황 파일 파싱 (기존 WMS 형식)
# 실제 컬럼: '일 자', '상품코드', '수불수량'
# ────────────────────────────────────────────────
def parse_shipping_file(file_obj) -> pd.DataFrame:
    """
    일자별 출고현황 엑셀(.xls/.xlsx) 파싱.
    - 날짜: '일 자' 컬럼
    - 수량: '수불수량' 컬럼 (콤마 포함 문자열)
    반환 컬럼: 상품코드(str), 출고일자(date), 출고수량(float)
    """
    raw = _read_xls_or_xlsx(file_obj)
    raw.columns = raw.columns.str.strip()

    code_col = _find_col(raw, ["상품코드", "품목코드", "코드"])
    date_col = _find_col(raw, ["일 자", "일자", "출고일자", "날짜", "출고일", "일  자"])
    qty_col  = _find_col(raw, ["수불수량", "출고수량", "수량", "출고량"])

    df = pd.DataFrame({
        "상품코드": raw[code_col].astype(str).str.strip(),
        "출고일자": pd.to_datetime(raw[date_col], errors="coerce"),
        "출고수량": clean_numeric(raw[qty_col]),
    })

    df = df.dropna(subset=["출고일자"])
    df["출고일자"] = df["출고일자"].dt.date
    return df.query("상품코드 != '' and 상품코드 != 'nan'").reset_index(drop=True)


# ────────────────────────────────────────────────
# 출고 데이터 필터링 / 집계
# ────────────────────────────────────────────────
def filter_shipping_by_date(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    """시작일~종료일 범위 필터"""
    mask = (df["출고일자"] >= start_date) & (df["출고일자"] <= end_date)
    return df[mask].copy()


def aggregate_shipping_daily(df: pd.DataFrame) -> pd.DataFrame:
    """일자 × 상품코드별 출고수량 집계 (출고현황 탭용 피벗 원본)"""
    return (
        df.groupby(["출고일자", "상품코드"], as_index=False)["출고수량"]
          .sum()
          .sort_values(["출고일자", "상품코드"])
          .reset_index(drop=True)
    )


def aggregate_shipping_by_product(df: pd.DataFrame) -> pd.DataFrame:
    """상품코드별 총 출고수량 집계"""
    return (
        df.groupby("상품코드", as_index=False)["출고수량"]
          .sum()
          .rename(columns={"출고수량": "총출고수량"})
    )


# ────────────────────────────────────────────────
# 지표 산출 (핵심 비즈니스 로직)
# ────────────────────────────────────────────────
def compute_metrics(
    master_df: pd.DataFrame,
    inventory_df: pd.DataFrame,
    shipping_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    최근 90일 출고 기준 재고 지표 산출.
    입력:
      master_df   : 구분, 품목구분, 상품코드, 상품명
      inventory_df: 상품코드, 현재고
      shipping_df : 상품코드, 출고일자, 출고수량 (전체 기간)
    반환: 지표 테이블 DataFrame
    """
    today   = get_today_kst()
    cutoff  = today - timedelta(days=RECENT_DAYS)

    # 최근 90일 출고 집계
    recent     = filter_shipping_by_date(shipping_df, cutoff, today)
    recent_agg = aggregate_shipping_by_product(recent)

    # 마스터 기준 병합
    df = master_df.merge(inventory_df, on="상품코드", how="left")
    df = df.merge(recent_agg, on="상품코드", how="left")
    df["현재고"]    = df["현재고"].fillna(0)
    df["총출고수량"] = df["총출고수량"].fillna(0)

    # ── 지표 계산 ──────────────────────────────
    df["3개월 총출고량"]      = df["총출고수량"]
    df["3개월 월평균 출고량"]  = df["3개월 총출고량"] / 3
    df["3개월 일평균 출고량"]  = df["3개월 총출고량"] / RECENT_DAYS

    df["사용가능(월)"] = df.apply(
        lambda r: safe_divide(r["현재고"], r["3개월 월평균 출고량"]), axis=1
    )
    df["사용가능(일)"] = df.apply(
        lambda r: safe_divide(r["현재고"], r["3개월 일평균 출고량"]), axis=1
    )
    df["안전재고"]      = df["3개월 월평균 출고량"] * SAFETY_RATIO
    df["안전재고 미만"] = df["현재고"] - df["안전재고"]
    df["예상소진일"]    = df["사용가능(일)"].apply(lambda v: _calc_expiry(v, today))

    cols = [
        "구분", "품목구분", "상품코드", "상품명",
        "현재고",
        "3개월 총출고량", "3개월 월평균 출고량", "3개월 일평균 출고량",
        "사용가능(월)", "사용가능(일)",
        "안전재고", "안전재고 미만",
        "예상소진일",
    ]
    return df[cols].reset_index(drop=True)


def _calc_expiry(usable_days, today):
    if isinstance(usable_days, str):
        return "출고없음"
    try:
        v = float(usable_days)
    except Exception:
        return "-"
    if np.isinf(v) or v > 36500:
        return "∞"
    return (today + timedelta(days=v)).strftime("%Y-%m-%d")


# ────────────────────────────────────────────────
# 내부 헬퍼
# ────────────────────────────────────────────────
def _read_xls_or_xlsx(file_obj) -> pd.DataFrame:
    """
    .xls / .xlsx 모두 지원.
    - xlsx/xlsm 이면 openpyxl로 직접 읽음.
    - xls 이면:
      1. LibreOffice(soffice)가 설치되어 있는 경우 변환 시도
      2. 만약 soffice가 없거나(WinError 2) 에러 발생 시 xlrd 엔진으로 직접 읽기 시도
      3. 그래도 실패하면 openpyxl 엔진으로 직접 읽기 시도
    """
    import subprocess, tempfile, os

    content = file_obj.read() if hasattr(file_obj, "read") else open(file_obj, "rb").read()
    name    = getattr(file_obj, "name", "") or ""

    # ── xlsx / xlsm → openpyxl 직접 읽기 ──
    if str(name).lower().endswith((".xlsx", ".xlsm")):
        return pd.read_excel(io.BytesIO(content), engine="openpyxl", dtype=str).fillna("")

    # ── xls ──
    # 1단계: LibreOffice(soffice) 변환 시도 (설치되어 있고 실행 가능할 때만)
    libreoffice_success = False
    xlsx_content = None
    
    with tempfile.TemporaryDirectory() as tmpdir:
        src = os.path.join(tmpdir, "input.xls")
        with open(src, "wb") as f:
            f.write(content)

        try:
            result = subprocess.run(
                ["soffice", "--headless", "--convert-to", "xlsx", "--outdir", tmpdir, src],
                capture_output=True, timeout=15,
            )
            xlsx_path = os.path.join(tmpdir, "input.xlsx")
            if result.returncode == 0 and os.path.exists(xlsx_path):
                with open(xlsx_path, "rb") as f:
                    xlsx_content = f.read()
                libreoffice_success = True
        except Exception:
            # soffice가 시스템에 없거나 실행 에러(WinError 2 등) 발생 시 pass
            pass

    if libreoffice_success and xlsx_content is not None:
        try:
            return pd.read_excel(io.BytesIO(xlsx_content), engine="openpyxl", dtype=str).fillna("")
        except Exception:
            pass

    # 2단계: xlrd로 직접 읽기 시도
    try:
        return pd.read_excel(io.BytesIO(content), engine="xlrd", dtype=str).fillna("")
    except Exception as xlrd_err:
        # 3단계: openpyxl로 직접 읽기 시도 (가끔 xls 확장자이지만 실제 포맷은 xlsx인 경우 대비)
        try:
            return pd.read_excel(io.BytesIO(content), engine="openpyxl", dtype=str).fillna("")
        except Exception as openpyxl_err:
            raise ValueError(
                f"Excel 파일을 읽을 수 없습니다.\n"
                f"- xlrd 오류: {xlrd_err}\n"
                f"- openpyxl 오류: {openpyxl_err}"
            )


def _find_col(df: pd.DataFrame, candidates: list, required: bool = True):
    """후보 컬럼명 중 실제 존재하는 첫 번째 반환. required=False 이면 없어도 None 반환."""
    for c in candidates:
        if c in df.columns:
            return c
    if not required:
        return None
    raise KeyError(
        f"필수 컬럼 없음. 후보: {candidates}\n실제 컬럼: {list(df.columns)}"
    )
