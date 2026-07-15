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
        raise ValueError(f"마스터 DB에 필수 컬럼이 누락되었습니다: {missing}")
    
    df["상품코드"] = df["상품코드"].str.strip()
    
    out_cols = required.copy()
    if "내포입" in df.columns:
        out_cols.append("내포입")
        
    res_df = df[out_cols].query("상품코드 != ''").reset_index(drop=True)
    if "내포입" in res_df.columns:
        res_df["내포입"] = pd.to_numeric(res_df["내포입"], errors="coerce").fillna(1)
    else:
        res_df["내포입"] = 1
        
    return res_df
@st.cache_data(ttl=3600)
def load_code_mapping_from_gsheet(spreadsheet_url: str) -> pd.DataFrame:
    """
    Google Sheets에서 채널별 상품코드 매핑 테이블 로드.
    사용자 제공 포맷: A열=채널상품코드, C열=표준상품코드 (모든 채널 공통 적용 'ALL')
    """
    mapping_dfs = []
    
    try:
        csv_url = build_gsheet_csv_url(spreadsheet_url, "채널매핑")
        df = pd.read_csv(csv_url, dtype=str).fillna("")
        
        # 1. 통합 매핑 시트 구조 확인 (A열, C열)
        if df.shape[1] >= 3:
            sub_df = pd.DataFrame({
                "채널": "ALL",  # 모든 채널 공통 적용
                "채널상품코드": df.iloc[:, 0].astype(str).str.strip(),
                "표준상품코드": df.iloc[:, 2].astype(str).str.strip()
            })
            sub_df = sub_df[(sub_df["채널상품코드"] != "") & (sub_df["표준상품코드"] != "") & (sub_df["채널상품코드"] != "상품코드")]
            sub_df["채널상품코드"] = sub_df["채널상품코드"].str.replace(r'\.0$', '', regex=True)
            mapping_dfs.append(sub_df)
    except Exception as e:
        print(f"채널매핑 시트 로드 에러: {e}")
        pass
        
    # 폴백: 기존 신세계면세점 단일 시트 구조
    if not mapping_dfs:
        try:
            csv_url = build_gsheet_csv_url(spreadsheet_url, "신세계면세점")
            df = pd.read_csv(csv_url, dtype=str).fillna("")
            if df.shape[1] >= 3:
                sub_df = pd.DataFrame({
                    "채널": "신세계면세점",
                    "채널상품코드": df.iloc[:, 0].str.strip(),
                    "표준상품코드": df.iloc[:, 2].str.strip()
                })
                sub_df = sub_df[(sub_df["채널상품코드"] != "") & (sub_df["표준상품코드"] != "")]
                sub_df["채널상품코드"] = sub_df["채널상품코드"].str.replace(r'\.0$', '', regex=True)
                mapping_dfs.append(sub_df)
        except Exception as e:
            print(f"신세계면세점 매핑 시트 로드 에러: {e}")
            pass
    
    if mapping_dfs:
        return pd.concat(mapping_dfs, ignore_index=True)
        
    return pd.DataFrame(columns=["채널", "채널상품코드", "표준상품코드"])

def translate_product_codes(df: pd.DataFrame, channel: str, mapping_df: pd.DataFrame) -> pd.DataFrame:
    """매핑 테이블을 참조하여 DataFrame 내부의 '상품코드'를 표준상품코드로 일괄 변환"""
    if mapping_df.empty or "상품코드" not in df.columns:
        return df
        
    # '채널' 필터링 ('ALL'이면 모든 채널 허용)
    channel_map = mapping_df[(mapping_df["채널"] == channel) | (mapping_df["채널"] == "ALL")]
    if channel_map.empty:
        return df
        
    mapping_dict = dict(zip(channel_map["채널상품코드"], channel_map["표준상품코드"]))
    df["상품코드"] = df["상품코드"].apply(lambda code: mapping_dict.get(str(code).strip(), code))
    return df


@st.cache_data(ttl=3600)
def load_po_from_gsheet(spreadsheet_url: str, sheet_name: str = "발주") -> pd.DataFrame:
    """
    Google Sheets에서 발주(PO) 및 입고 예정 데이터를 로드.
    예상 컬럼: 발주번호, 외주처, 상품코드, 상품명, 발주수량, 납기예정일, 입고상태
    """
    try:
        csv_url = build_gsheet_csv_url(spreadsheet_url, sheet_name)
        df = pd.read_csv(csv_url, dtype=str).fillna("")
        df.columns = df.columns.str.strip()

        if "상품코드" not in df.columns:
            # 사용자가 '상품코드' 대신 'WMS 상품코드(Plus CL)' 등을 쓴 경우를 대비한 맵핑
            code_candidate = _find_col_by_keyword(df, ["상품코드", "품목코드"], required=False)
            if code_candidate:
                df["상품코드"] = df[code_candidate]
            else:
                print("발주 시트에 '상품코드'를 포함하는 컬럼이 없습니다.")
                return pd.DataFrame()
            
        df["상품코드"] = df["상품코드"].str.strip()
        df = df.query("상품코드 != ''").copy()
        
        # 외주처(발주처) 정제
        vendor_col = _find_col(df, ["발주처", "외주처", "거래처"], required=False)
        if vendor_col:
            df["외주처"] = df[vendor_col].str.strip()
        else:
            df["외주처"] = ""
            
        # 상품명 정제
        name_col = _find_col(df, ["제품명", "상품명"], required=False)
        if name_col:
            df["상품명"] = df[name_col].str.strip()
        else:
            df["상품명"] = ""
        
        # 수량 정제
        qty_col = _find_col(df, ["발주수량", "수량", "입고예정수량"], required=False)
        if qty_col:
            df["발주수량"] = clean_numeric(df[qty_col])
        else:
            df["발주수량"] = 0.0
            
        # 납기예정일 정제
        date_col = _find_col(df, ["납기예정", "납기예정일", "입고예정일", "예정일", "납기일"], required=False)
        if date_col:
            df["납기예정일"] = pd.to_datetime(df[date_col], errors="coerce").dt.date
        else:
            df["납기예정일"] = None
            
        # 상태 정제 (옵션)
        status_col = _find_col(df, ["진행사항", "진행상태", "상태", "입고상태"], required=False)
        if status_col:
            df["입고상태"] = df[status_col].str.strip()
        else:
            df["입고상태"] = "대기"
            
        # 입고상태가 '완료'인 것은 시뮬레이션의 '예정' 수량에서 제외하기 위해 필요
        return df.reset_index(drop=True)
    except Exception as e:
        print(f"PO 시트 로드 에러: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_transfer_from_gsheet(spreadsheet_url: str, sheet_name: str = "선적") -> pd.DataFrame:
    """
    Google Sheets에서 국내->해외 선적(이동) 데이터를 로드.
    예상 컬럼: 상품코드, 출발지, 도착지, 선적수량, 선적일, 하차예정일, 상태
    """
    try:
        csv_url = build_gsheet_csv_url(spreadsheet_url, sheet_name)
        df = pd.read_csv(csv_url, dtype=str).fillna("")
        df.columns = df.columns.str.strip()

        if "상품코드" not in df.columns:
            code_candidate = _find_col_by_keyword(df, ["상품코드", "품목코드"], required=False)
            if code_candidate:
                df["상품코드"] = df[code_candidate]
            else:
                return pd.DataFrame()
                
        df["상품코드"] = df["상품코드"].str.strip()
        df = df.query("상품코드 != ''").copy()
        
        # 기본 정보 매핑
        source_col = _find_col(df, ["출발지", "출고처", "보내는곳"], required=False)
        df["출발지"] = df[source_col].str.strip() if source_col else "CK로지스"
        
        dest_col = _find_col(df, ["도착지", "입고처", "받는곳"], required=False)
        df["도착지"] = df[dest_col].str.strip() if dest_col else "US 창고"
        
        qty_col = _find_col(df, ["선적수량", "수량", "이동수량"], required=False)
        df["선적수량"] = clean_numeric(df[qty_col]) if qty_col else 0.0
        
        depart_col = _find_col(df, ["선적일", "출발일", "출고일", "출고예정일"], required=False)
        df["선적일"] = pd.to_datetime(df[depart_col], errors="coerce").dt.date if depart_col else None
        
        arrive_col = _find_col(df, ["하차예정일", "하차일", "도착예정일", "입고예정일"], required=False)
        df["하차예정일"] = pd.to_datetime(df[arrive_col], errors="coerce").dt.date if arrive_col else None
        
        status_col = _find_col(df, ["상태", "진행상태", "진행사항"], required=False)
        df["상태"] = df[status_col].str.strip() if status_col else "대기"

        return df.reset_index(drop=True)
    except Exception as e:
        print(f"선적 시트 로드 에러: {e}")
        return pd.DataFrame()


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
def decrypt_xlsx(file_obj, password) -> bytes:
    """
    msoffcrypto-tool을 사용해 비밀번호가 걸린 xlsx 파일을 복호화.
    password는 단일 문자열이거나 시도할 비밀번호 문자열들의 리스트일 수 있습니다.
    반환: 복호화된 xlsx 파일의 bytes
    """
    import msoffcrypto

    content = file_obj.read() if hasattr(file_obj, "read") else open(file_obj, "rb").read()
    
    passwords = [password] if isinstance(password, str) else password
    
    last_err = None
    for pwd in passwords:
        try:
            encrypted = io.BytesIO(content)
            office_file = msoffcrypto.OfficeFile(encrypted)
            office_file.load_key(password=pwd)
            decrypted = io.BytesIO()
            office_file.decrypt(decrypted)
            return decrypted.getvalue()
        except Exception as e:
            last_err = e
            continue
            
    raise Exception(f"복호화 실패. 시도한 비밀번호가 모두 틀렸습니다. (마지막 에러: {last_err})")



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
def parse_ownist_shipping_file(file_obj, password) -> pd.DataFrame:
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
# 일자별 마감 현황 파일 파싱 (통합: 신세계, 롯데, 신라, 현대, 도착보장)
# ────────────────────────────────────────────────
def parse_multi_channel_file(file_obj, target_date: datetime.date, channel_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    모든 면세점/도착보장 채널의 엑셀을 처리하는 통합 파서.
    대표님이 확정하신 채널별 고정 알파벳(열) 인덱스를 기준으로 데이터를 추출합니다.
    """
    try:
        # 헤더 없이 순수 데이터로 모두 읽기 (열 인덱스 접근을 위해)
        df = pd.read_excel(file_obj, header=None, dtype=str)
    except Exception as e:
        if "datetime" in str(e).lower() or "date" in str(e).lower():
            raise ValueError(f"[{channel_name}] 엑셀 파일 내부에 손상된 날짜 포맷이 포함되어 파싱할 수 없습니다. 엑셀을 열고 '다른 이름으로 저장(덮어쓰기)' 한 뒤 다시 업로드해 주세요.")
        raise
        
    code_col = None
    ship_col = None
    inv_col = None
    amt_col = None

    # 알파벳을 인덱스로 변환하는 헬퍼 (A=0, B=1, ..., Z=25, AA=26, AQ=42)
    def col_idx(letter: str) -> int:
        idx = 0
        for char in letter.upper():
            idx = idx * 26 + (ord(char) - ord('A') + 1)
        return idx - 1

    # 1. 채널별 하드코딩 매핑
    if channel_name == "롯데면세점":
        code_col = col_idx("K")
        ship_col = col_idx("Z")
        inv_col = col_idx("AQ")
    elif channel_name == "도착보장":
        code_col = col_idx("F")
        ship_col = col_idx("P")  # 출고 B2C
        inv_col = col_idx("V")   # 기말재고 가용
    elif channel_name == "신라면세점":
        # 신라는 파일 이름이나 데이터의 내용으로 재고/출고 구분
        # B열(1)에 데이터가 있으면 보통 재고, G열(6)이면 출고
        # 여기서는 파일 하나의 열 갯수나 첫 번째 행 텍스트로 구분
        if df.shape[1] > col_idx("K") and "EC판매수량" in str(df.iloc[:, col_idx("K")]):
            code_col = col_idx("G")
            ship_col = col_idx("K")
        elif df.shape[1] > col_idx("H"):
            code_col = col_idx("B")
            inv_col = col_idx("H")
    elif channel_name == "신세계면세점":
        code_col = col_idx("D")
        ship_col = col_idx("Q")
        inv_col = col_idx("S")
    elif channel_name == "현대면세점":
        code_col = col_idx("C")
        ship_col = col_idx("T")
        inv_col = col_idx("V")
    else:
        # Fallback (혹시 모를 에러 방지)
        code_col = col_idx("A")

    if code_col >= df.shape[1]:
        raise ValueError(f"[{channel_name}] 파일의 열 개수가 부족합니다. (요구 열 인덱스: {code_col}, 실제 열 개수: {df.shape[1]})")

    # 2. 데이터 추출
    df = df.dropna(subset=[code_col])
    # 헤더 행 등 상품코드가 아닌 한글 텍스트들은 0을 포함하지 않는 경우가 많아 필터링 (간단히 상품코드만 추출)
    df[code_col] = df[code_col].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
    df = df[(df[code_col] != '') & (df[code_col].str.lower() != 'nan')]
    
    # 헤더 행 제외 (상품코드가 일반적으로 알파벳/숫자 조합이므로 순수 한글이나 '상품코드' 문구 제외)
    df = df[~df[code_col].str.contains("상품코드|SKU|Item", case=False, na=False)]

    # Shipping Data 구성
    ship_df = pd.DataFrame()
    if ship_col is not None and ship_col < df.shape[1]:
        ship_df = df[[code_col]].copy()
        ship_df.columns = ['상품코드']
        ship_df['상품명'] = ''
        ship_df['출고량'] = clean_numeric(df[ship_col])
        ship_df['주문금액합계'] = 0.0
        
        # 반품(음수)도 포함하기 위해 0이 아닌 것만 필터링
        ship_df = ship_df[ship_df['출고량'] != 0].copy()
        ship_df['출고일자'] = target_date
        ship_df['주문사'] = channel_name
        
        prefix_map = {"신세계면세점": "SSG", "롯데면세점": "LOT", "신라면세점": "SLA", "현대면세점": "HYD", "도착보장": "NAV"}
        prefix = prefix_map.get(channel_name, "ETC")
        ship_df['주문번호'] = f"{prefix}-{target_date.strftime('%Y%m%d')}"
    
    # Inventory Data 구성
    inv_df = pd.DataFrame()
    if inv_col is not None and inv_col < df.shape[1]:
        inv_df = df[[code_col]].copy()
        inv_df.columns = ['상품코드']
        inv_df['현재고'] = clean_numeric(df[inv_col])
        # 현재고가 음수인 경우는 0으로 치환하거나 그대로 둘 수 있음 (보통 0이상 유지)
    
    return ship_df, inv_df

def _find_col_by_keyword(df: pd.DataFrame, keywords: list, required: bool = True):
    for kw in keywords:
        for col in df.columns:
            if kw in col:
                return col
    if required:
        raise KeyError(f"필수 컬럼을 찾을 수 없습니다. (키워드: {keywords}) - 현재 컬럼: {list(df.columns)}")
    return None


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

def aggregate_shipping_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """월별 × 상품코드별 출고수량 집계 (출고현황 탭용 피벗 원본)"""
    # 출고일자를 월(YYYY-MM)로 변환
    df_copy = df.copy()
    # 출고일자가 문자열이든 datetime이든 'YYYY-MM' 형식으로 추출
    df_copy["출고월"] = pd.to_datetime(df_copy["출고일자"]).dt.strftime("%Y-%m")
    
    return (
        df_copy.groupby(["출고월", "상품코드"], as_index=False)["출고수량"]
          .sum()
          .sort_values(["출고월", "상품코드"])
          .reset_index(drop=True)
    )


def aggregate_shipping_by_product(df: pd.DataFrame) -> pd.DataFrame:
    """상품코드 및 채널별 총 출고수량 집계"""
    group_cols = ["상품코드", "채널"] if "채널" in df.columns else ["상품코드"]
    return (
        df.groupby(group_cols, as_index=False)["출고수량"]
          .sum()
          .rename(columns={"출고수량": "총출고수량"})
    )


# ────────────────────────────────────────────────
# 지표 산출 (핵심 비즈니스 로직)
# ────────────────────────────────────────────────
def get_previous_three_months(today_date: "datetime.date") -> tuple["datetime.date", "datetime.date"]:
    """현재 월을 제외한 직전 3개월의 시작일과 종료일을 반환"""
    # 이번 달 1일
    first_day_this_month = today_date.replace(day=1)
    # 직전 달 마지막 날 (종료일)
    end_date = first_day_this_month - timedelta(days=1)
    
    # 3개월 전 1일 (시작일)
    target_month = today_date.month - 3
    target_year = today_date.year
    if target_month <= 0:
        target_month += 12
        target_year -= 1
    start_date = datetime(target_year, target_month, 1).date()
    
    return start_date, end_date

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
    start_date, end_date = get_previous_three_months(today)
    
    # 해당 기간(직전 3개월)의 총 일수 계산
    target_days = (end_date - start_date).days + 1

    # 직전 3개월 출고 집계 (당월 제외)
    recent     = filter_shipping_by_date(shipping_df, start_date, end_date)
    recent_agg = aggregate_shipping_by_product(recent)

    # 당월 출고 집계
    curr_month_start = today.replace(day=1)
    curr_ship = filter_shipping_by_date(shipping_df, curr_month_start, today)
    curr_agg = aggregate_shipping_by_product(curr_ship).rename(columns={"총출고수량": "당월 출고량"})

    # 마스터 기준 병합
    df = master_df.merge(inventory_df, on="상품코드", how="left")
    
    # recent_agg를 병합할 때 채널이 있다면 채널도 기준으로 삼음
    if "채널" in df.columns and "채널" in recent_agg.columns:
        df = df.merge(recent_agg, on=["상품코드", "채널"], how="left")
    else:
        df = df.merge(recent_agg, on="상품코드", how="left")
        
    if "채널" in df.columns and "채널" in curr_agg.columns:
        df = df.merge(curr_agg[["상품코드", "채널", "당월 출고량"]], on=["상품코드", "채널"], how="left")
    else:
        if "당월 출고량" in curr_agg.columns:
            df = df.merge(curr_agg[["상품코드", "당월 출고량"]], on="상품코드", how="left")
        else:
            df["당월 출고량"] = 0.0
        
    df["현재고"]    = df["현재고"].fillna(0)
    df["총출고수량"] = df["총출고수량"].fillna(0)
    df["당월 출고량"] = df["당월 출고량"].fillna(0)

    # 채널 결측치 처리 (마스터에만 있고 재고/출고 내역이 없는 상품)
    if "채널" in df.columns:
        df["채널"] = df["채널"].fillna("-")

    # ── 지표 계산 ──────────────────────────────
    df["3개월 총출고량"]      = df["총출고수량"]
    df["3개월 월평균 출고량"]  = df["3개월 총출고량"] / 3
    df["3개월 일평균 출고량"]  = df["3개월 총출고량"] / target_days

    df["사용가능(월)"] = df.apply(
        lambda r: safe_divide(r["현재고"], r["3개월 월평균 출고량"]), axis=1
    )
    df["사용가능(일)"] = df.apply(
        lambda r: safe_divide(r["현재고"], r["3개월 일평균 출고량"]), axis=1
    )
    df["안전재고"]      = df["3개월 월평균 출고량"] * SAFETY_RATIO
    df["안전재고 미만"] = df["현재고"] - df["안전재고"]
    df["예상소진일"]    = df["사용가능(일)"].apply(lambda v: _calc_expiry(v, today))

    cols = []
    if "채널" in df.columns:
        cols.append("채널")
        
    cols.extend([
        "구분", "품목구분", "상품코드", "상품명",
        "현재고", "당월 출고량",
        "3개월 총출고량", "3개월 월평균 출고량", "3개월 일평균 출고량",
        "사용가능(월)", "사용가능(일)",
        "안전재고", "안전재고 미만",
        "예상소진일",
    ])
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
